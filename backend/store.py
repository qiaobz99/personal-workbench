"""SQLite storage layer.

* ``docs``  — FTS5 full-text index over the Vault's Markdown files.
* ``tasks`` — kanban board items.
* ``meta``  — small key/value settings.

The core application only depends on the Python standard library, so this
module never imports third-party packages.
"""
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
