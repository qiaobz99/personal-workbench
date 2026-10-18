"""SQLite storage layer.

* ``docs``  — FTS5 full-text index over the Vault's Markdown files.
* ``tasks`` — kanban board items.
* ``meta``  — small key/value settings.

The core application only depends on the Python standard library, so this
module never imports third-party packages.
"""
import math
import os
import re
import sqlite3

import config


# --------------------------------------------------------------------------
# Connection / schema
# --------------------------------------------------------------------------
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    cur = conn.cursor()

    # Full-text index. ``content`` is the only indexed column; path/title/mtime
    # are stored as unindexed metadata so we can return them directly.
    cur.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(
            path UNINDEXED,
            title UNINDEXED,
            content,
            mtime UNINDEXED,
            tokenize='unicode61'
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            notes       TEXT DEFAULT '',
            status      TEXT NOT NULL DEFAULT 'todo',
            priority    TEXT DEFAULT 'medium',
            tags        TEXT DEFAULT '',
            due         TEXT DEFAULT '',
            created_at  TEXT DEFAULT (datetime('now')),
            updated_at  TEXT DEFAULT (datetime('now'))
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )

    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
# Full-text index maintenance
# --------------------------------------------------------------------------
def upsert_doc(path: str, title: str, content: str, mtime: str) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM docs WHERE path = ?", (path,))
    cur.execute(
        "INSERT INTO docs(path, title, content, mtime) VALUES (?, ?, ?, ?)",
        (path, title, content, mtime),
    )
    conn.commit()
    conn.close()


def delete_doc(path: str) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM docs WHERE path = ?", (path,))
    conn.commit()
    conn.close()


def get_content(path: str) -> str:
    """Full indexed text for one Vault file (used to build RAG context)."""
    conn = get_conn()
    row = conn.execute(
        "SELECT content FROM docs WHERE path = ?", (path,)
    ).fetchone()
    conn.close()
    return row["content"] if row else ""


def prune_docs(keep_paths) -> int:
    """Drop index rows whose file is gone (deleted, renamed or moved).

    ``reindex()`` only upserts, so without this a renamed file leaves its old
    path behind forever -- search would keep returning dead paths and stale
    titles. Returns the number of rows removed.
    """
    keep = set(keep_paths)
    conn = get_conn()
    rows = conn.execute("SELECT path FROM docs").fetchall()
    stale = [r["path"] for r in rows if r["path"] not in keep]
    if stale:
        conn.executemany("DELETE FROM docs WHERE path = ?", [(p,) for p in stale])
        conn.commit()
    conn.close()
    return len(stale)


def count_docs() -> int:
    conn = get_conn()
    n = conn.execute("SELECT count(*) FROM docs").fetchone()[0]
    conn.close()
    return n


def build_fts_query(text: str):
    """Turn free text into a safe FTS5 query (AND of double-quoted terms).

    FTS5 raises on malformed syntax, so we strip punctuation and require an
    explicit boolean AND between terms instead of relying on the default OR.
    """
    terms = [t for t in re.split(r"\s+", text.strip()) if t]
    safe = []
    for t in terms:
        t = t.replace('"', "").replace("'", "").strip()
        if t:
            safe.append('"' + t + '"')
    return " AND ".join(safe) if safe else None


def search_fts(query: str, limit: int = 50):
    q = build_fts_query(query)
    if not q:
        return []
    conn = get_conn()
    cur = conn.cursor()
    try:
        rows = cur.execute(
            """
            SELECT path, title,
                   snippet(docs, 2, '<mark>', '</mark>', '…', 12) AS snippet,
                   mtime
            FROM docs
            WHERE docs MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (q, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# Free-text (natural-language / CJK) retrieval
# --------------------------------------------------------------------------
# A question is not a keyword list: "合规管理岗简历有啥我的项目1内容是啥" shares
# no substring with the note that answers it, so both FTS5 (which cannot split
# CJK without a dictionary) and the substring fallback return nothing. We strip
# the question-framing words below first, then treat the rest as keywords.
# Multi-character phrases come first so "你是什么" is removed before "是".
_FILLER_PHRASES = (
    "你能不能", "可不可以", "有没有", "是不是", "你是什么", "我有啥",
    "有哪几个", "有哪些", "内容是什么", "内容是啥", "请问一下",
    "帮我看看", "告诉我", "我想知道", "为什么", "请问", "帮我",
    "你是", "我的", "你的", "我有", "你有", "有没", "有啥", "是啥",
    "这个", "那个", "这些", "那些", "什么", "怎么", "如何", "哪些",
    "哪个", "多少", "一下", "可以", "能否", "是否", "是什么", "内容是",
)

# Characters that on their own carry no retrieval signal. A window made only of
# these (e.g. "你是", "什么") is dropped; one that merely contains them ("的简",
# "行为") is kept, because Chinese words do use them.
_STOP_CHARS = set(
    "的了是我你他她它们有没有吗呢吧啊呀啥什么怎如何多少哪个这那可以请"
    "关于和与或在就都也还很太会能说帮想要把被该些种样于之而且但因所以如果虽然"
)


def build_nl_terms(query: str) -> list:
    """Turn a natural-language question into candidate keywords.

    Question framing is stripped, then every remaining CJK run is expanded into
    2- and 3-character sliding windows (so "合规管理岗" also yields "合规" /
    "管理" / "简历"-style fragments that actually appear in notes). ASCII words
    are kept as-is.
    """
    text = query or ""
    stripped = text
    for p in sorted(_FILLER_PHRASES, key=len, reverse=True):
        stripped = stripped.replace(p, " ")

    def harvest(source: str) -> set:
        out = set()
        for run in re.findall(r"[\u4e00-\u9fff]+", source):
            for n in (2, 3):
                for i in range(len(run) - n + 1):
                    g = run[i : i + n]
                    # A window that begins or ends on a function word is a
                    # slicing artefact ("的转化", "议没"), not a keyword.
                    if g[0] in _STOP_CHARS or g[-1] in _STOP_CHARS:
                        continue
                    out.add(g)
        for tok in re.findall(r"[A-Za-z0-9_][A-Za-z0-9_+.#/-]*", source):
            if len(tok) >= 2:
                out.add(tok.lower())
        return out

    terms = harvest(stripped)
    if not terms:
        # Everything was question framing ("你好", "你是？") -- keep the raw
        # windows so behaviour degrades to the old substring behaviour.
        terms = harvest(text)
    return sorted(terms)


def search_nl(query: str, limit: int = 50):
    """Retrieve notes for a whole question, ranked by keyword coverage.

    Terms that are too common to discriminate (they appear in a large share of
    the Vault, e.g. "模型" for an AI-notes corpus) are dropped, so a question the
    Vault genuinely does not answer still returns nothing instead of noise.
    """
    terms = build_nl_terms(query)
    if not terms:
        return []

    conn = get_conn()
    rows = conn.execute("SELECT path, title, content, mtime FROM docs").fetchall()
    conn.close()
    if not rows:
        return []

    has_ascii = any(t.isascii() for t in terms)
    df = {t: 0 for t in terms}
    per_doc = []
    for r in rows:
        content = r["content"] or ""
        if has_ascii:
            content = content.lower()
        matched = [t for t in terms if t in content]
        if not matched:
            continue
        for t in matched:
            df[t] += 1
        per_doc.append((r, content, matched))

    # Discard terms that are too common to be discriminative.
    cutoff = max(2, int(len(rows) * 0.4))
    keep = {t for t in terms if df[t] <= cutoff}
    if not keep:
        return []
    # A lone 2-character keyword only counts when it is rare enough to be
    # specific on its own (e.g. "简历"); otherwise one common word must not be
    # enough to drag unrelated notes into the context window.
    rare = max(2, int(len(rows) * 0.05))

    def weight(t: str) -> float:
        """Rarer keywords say more about a note than common ones do."""
        return math.log(1.0 + len(rows) / (1.0 + df[t])) * len(t)

    results = []
    for r, content, matched in per_doc:
        hits = [t for t in matched if t in keep]
        if not hits:
            continue
        if len(hits) < 2 and not (len(hits[0]) >= 3 or df[hits[0]] <= rare):
            continue
        title = r["title"] or ""
        title = title.lower() if has_ascii else title
        score = 0.0
        for t in hits:
            w = weight(t)
            score += w
            if t in title:
                # A keyword in the note's title is a decisive signal.
                score += w * 3
        anchor = min(
            (i for i in (content.find(t) for t in hits) if i >= 0), default=0
        )
        start = max(0, anchor - 40)
        end = min(len(content), anchor + 120)
        snip = content[start:end].replace("\n", " ")
        if start > 0:
            snip = "…" + snip
        if end < len(content):
            snip = snip + "…"
        results.append(
            {
                "path": r["path"],
                "title": r["title"],
                "snippet": snip,
                "mtime": r["mtime"],
                "score": score,
                "_n": len(hits),
            }
        )

    results.sort(key=lambda x: (-x["score"], -x["_n"], x["path"]))
    for x in results:
        x.pop("_n", None)
        x.pop("score", None)
    return results[:limit]


_WS_RE = re.compile(r"\s+")


def _squeeze(text: str) -> str:
    """Drop every whitespace char: '5 个工作日' -> '5个工作日'."""
    return _WS_RE.sub("", text)


def _squeeze_to_orig(content: str, sq_pos: int) -> int:
    """Map a position in the squeezed text back to the original string."""
    n = 0
    for i, ch in enumerate(content):
        if not ch.isspace():
            if n == sq_pos:
                return i
            n += 1
    return len(content)


def search_substring(query: str, limit: int = 50):
    """Chinese-friendly fallback.

    FTS5's default ``unicode61`` tokenizer does not split CJK text, so short
    multi-character CJK phrases that are not standalone tokens miss. We scan
    the indexed documents in Python and keep those whose content contains
    every whitespace-separated term.

    Vault notes style numbers with a space ("第 40 条", "5 个工作日"), so the
    same phrase typed without spaces used to return nothing. Every document is
    therefore matched twice: exactly as typed, then with all whitespace removed
    from both the query and the content.
    """
    terms = [t for t in re.split(r"\s+", query.strip()) if t]
    if not terms:
        return []
    sq_query = _squeeze(query)
    conn = get_conn()
    rows = conn.execute(
        "SELECT path, title, content, mtime FROM docs"
    ).fetchall()
    conn.close()
    results = []
    for r in rows:
        content = r["content"] or ""
        sq_idx = -1
        if sq_query and len(sq_query) >= 2:
            sq_idx = _squeeze(content).find(sq_query)
        if sq_idx >= 0:
            s = _squeeze_to_orig(content, sq_idx)
            e = _squeeze_to_orig(content, sq_idx + len(sq_query) - 1) + 1
            start = max(0, s - 40)
            end = min(len(content), e + 80)
            snip = content[start:end].replace("\n", " ")
            hit = content[s:e]
            if hit:
                snip = snip.replace(hit, "<mark>" + hit + "</mark>", 1)
        elif all(t in content for t in terms):
            idx = content.find(terms[0])
            start = max(0, idx - 40)
            end = min(len(content), idx + len(terms[0]) + 80)
            snip = content[start:end].replace("\n", " ")
            for t in terms:
                snip = snip.replace(t, "<mark>" + t + "</mark>")
        else:
            continue
        if start > 0:
            snip = "…" + snip
        if end < len(content):
            snip = snip + "…"
        results.append(
            {
                "path": r["path"],
                "title": r["title"],
                "snippet": snip,
                "mtime": r["mtime"],
            }
        )
        if len(results) >= limit:
            break
    return results


# --------------------------------------------------------------------------
# Tasks (kanban)
# --------------------------------------------------------------------------
VALID_STATUS = ("todo", "doing", "done")
VALID_PRIORITY = ("low", "medium", "high")


def _clean_task(row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "notes": row["notes"],
        "status": row["status"],
        "priority": row["priority"],
        "tags": row["tags"],
        "due": row["due"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_tasks(status: str = None) -> list:
    conn = get_conn()
    if status:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE status = ? ORDER BY updated_at DESC",
            (status,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM tasks ORDER BY updated_at DESC").fetchall()
    conn.close()
    return [_clean_task(r) for r in rows]


def create_task(title, notes="", status="todo", priority="medium", tags="", due="") -> dict:
    status = status if status in VALID_STATUS else "todo"
    priority = priority if priority in VALID_PRIORITY else "medium"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO tasks(title, notes, status, priority, tags, due)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (title, notes, status, priority, tags, due),
    )
    tid = cur.lastrowid
    conn.commit()
    conn.close()
    return get_task(tid)


def get_task(tid: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
    conn.close()
    return _clean_task(row) if row else None


def update_task(tid: int, **fields) -> dict:
    allowed = {"title", "notes", "status", "priority", "tags", "due"}
    sets = []
    vals = []
    for k, v in fields.items():
        if k in allowed:
            if k == "status" and v not in VALID_STATUS:
                v = "todo"
            if k == "priority" and v not in VALID_PRIORITY:
                v = "medium"
            sets.append(f"{k} = ?")
            vals.append(v)
    if not sets:
        return get_task(tid)
    sets.append("updated_at = datetime('now')")
    conn = get_conn()
    conn.execute(
        f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", (*vals, tid)
    )
    conn.commit()
    conn.close()
    return get_task(tid)


def delete_task(tid: int) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM tasks WHERE id = ?", (tid,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# --------------------------------------------------------------------------
# Meta
# --------------------------------------------------------------------------
def get_meta(key: str, default=None):
    conn = get_conn()
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_meta(key: str, value: str) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()
