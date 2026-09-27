"""Work Zone — structured work items stored as Markdown in ``vault/work/``.

Design in one line: **one set of files, two views.**

The Knowledge view shows ``vault/work/`` as a plain directory tree. The Work
Zone view projects the *same* files into typed work items (requirement /
design / dev / bug / convention) by reading a small YAML-ish frontmatter
block. Nothing is duplicated — Markdown stays the single source of truth, so
the whole thing remains greppable, editable in any editor, and readable by an
LLM.

Progress lives *in the file*: every status transition appends one timestamped
line under a ``## 进展`` heading. Lose the SQLite database and the history is
still there; copy ``vault/`` to another machine and the history comes along.

Standard library only.
"""
import datetime
import os
import re
import zipfile
import xml.etree.ElementTree as ET

import vault

WORK_SUBDIR = "work"

# Default name recorded on auto-generated timeline lines. Never hard-code a
# real person here — this repo is public. Override with ``KB_OWNER``.
DEFAULT_ACTOR = os.environ.get("KB_OWNER", "我")

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------
TYPES = ("requirement", "design", "dev", "bug", "convention", "note")

TYPE_LABEL = {
    "requirement": "需求",
    "design": "设计",
    "dev": "开发",
    "bug": "Bug",
    "convention": "约定",
    "note": "笔记",
}

TYPE_PREFIX = {
    "requirement": "REQ",
    "design": "DES",
    "dev": "DEV",
    "bug": "BUG",
    "convention": "CONV",
    "note": "NOTE",
}

# Where a brand-new item of a given type is filed, relative to vault/work/.
TYPE_DIR = {
    "requirement": "req",
    "design": "design",
    "dev": "dev",
    "bug": "bug",
    "convention": "_conventions",
    "note": "",
}

# State machine per type. The first entry is the default for a new item.
STATUS_FLOW = {
    "requirement": [
        "backlog", "analyzing", "designing", "dev",
        "testing", "staging", "released", "paused", "dropped",
    ],
    "design": ["draft", "reviewing", "approved", "archived"],
    "dev": ["todo", "doing", "blocked", "done"],
    "bug": ["open", "locating", "fixing", "verifying", "closed", "wontfix"],
    "convention": ["active", "archived"],
    "note": ["draft", "done"],
}

STATUS_LABEL = {
    "backlog": "待分析",
    "analyzing": "分析中",
    "designing": "设计中",
    "dev": "开发中",
    "testing": "联调中",
    "staging": "已提测",
    "released": "已上线",
    "paused": "已暂停",
    "dropped": "已放弃",
    "draft": "草稿",
    "reviewing": "评审中",
    "approved": "已定稿",
    "archived": "已归档",
    "todo": "待开始",
    "doing": "进行中",
    "blocked": "受阻",
    "done": "已完成",
    "open": "已提出",
    "locating": "定位中",
    "fixing": "修复中",
    "verifying": "待验证",
    "closed": "已关闭",
    "wontfix": "不予修复",
    "active": "生效中",
}

# Statuses that mean "this item is finished" — excluded from 进行中.
TERMINAL = {"released", "dropped", "closed", "wontfix", "archived", "done"}

PRIORITIES = ("high", "medium", "low")
SEVERITIES = ("blocker", "major", "minor", "trivial")
VERDICTS = ("", "缺陷", "需求变更")

SEVERITY_LABEL = {
    "blocker": "阻断",
    "major": "严重",
    "minor": "一般",
    "trivial": "轻微",
}

PROGRESS_HEAD = "## 进展"

_FIELDS = (
    "id", "type", "title", "project", "status", "priority", "owner",
    "created", "updated", "tags", "refs", "severity", "verdict",
)

# Ordered key list used when writing frontmatter back out.
_FM_ORDER = _FIELDS


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
def work_root() -> str:
    return os.path.join(vault.vault_root(), WORK_SUBDIR)


def _iter_files():
    """Every Markdown/text file under vault/work/, as vault-relative paths."""
    root = work_root()
    if not os.path.isdir(root):
        return []
    vroot = vault.vault_root()
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if not d.startswith(".") and d != "__pycache__"
        ]
        for name in filenames:
            if name.startswith(".") or name == "__pycache__":
                continue
            if not name.lower().endswith((".md", ".markdown", ".txt")):
                continue
            abs_path = os.path.join(dirpath, name)
            out.append(os.path.relpath(abs_path, vroot).replace(os.sep, "/"))
    return sorted(out)


# --------------------------------------------------------------------------
# Frontmatter (minimal YAML subset: scalars + inline lists)
# --------------------------------------------------------------------------
_FM_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.S)


def parse_frontmatter(text: str):
    """Split ``text`` into (meta, body).

    Only accepts the block as frontmatter when *every* non-empty line looks
    like ``key: value`` — otherwise a document that merely starts with a
    horizontal rule (``---``) would be silently truncated.
    """
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    raw_lines = [ln.strip() for ln in m.group(1).splitlines()]
    lines = [ln for ln in raw_lines if ln and not ln.startswith("#")]
    if not lines or any(":" not in ln for ln in lines):
        return {}, text

    meta = {}
    for line in lines:
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if not key:
            continue
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            items = [x.strip().strip('"').strip("'") for x in inner.split(",")]
            meta[key] = [x for x in items if x]
        else:
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            meta[key] = val
    return meta, text[m.end():]


def _yaml_scalar(v) -> str:
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(str(x) for x in v) + "]"
    s = "" if v is None else str(v)
    if s == "":
        return ""
    if re.search(r"[:#\[\]{}\"']", s) or s != s.strip():
        return '"' + s.replace('"', '\\"') + '"'
    return s


def dump_frontmatter(meta: dict) -> str:
    keys = [k for k in _FM_ORDER if k in meta]
    keys += [k for k in meta if k not in _FM_ORDER]
    lines = ["---"]
    for k in keys:
        lines.append(f"{k}: {_yaml_scalar(meta[k])}")
    lines.append("---")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Inference (so hand-written / imported files still show up correctly)
# --------------------------------------------------------------------------
_DIR_TYPE = {
    "req": "requirement",
    "requirement": "requirement",
    "design": "design",
    "dev": "dev",
    "bug": "bug",
    "_conventions": "convention",
    "conventions": "convention",
}

_NAME_TYPE_HINTS = (
    ("需求", "requirement"),
    ("requirement", "requirement"),
    ("prd", "requirement"),
    ("设计", "design"),
    ("design", "design"),
    ("bug", "bug"),
    ("缺陷", "bug"),
    ("故障", "bug"),
    ("问题", "bug"),
    ("issue", "bug"),
    ("纪律", "convention"),
    ("约定", "convention"),
    ("规范", "convention"),
    ("convention", "convention"),
    ("开发", "dev"),
    ("任务", "dev"),
)


def _guess_type_from_name(name: str) -> str:
    n = (name or "").lower()
    for hint, ttype in _NAME_TYPE_HINTS:
        if hint in n:
            return ttype
    return "note"


def _infer_type(rel_path: str, meta: dict) -> str:
    declared = (meta.get("type") or "").strip().lower()
    if declared in TYPES:
        return declared
    parts = rel_path.replace("\\", "/").split("/")[1:]  # drop "work"
    for seg in [p.lower() for p in parts[:-1]]:
        if seg in _DIR_TYPE:
            return _DIR_TYPE[seg]
    return _guess_type_from_name(parts[-1] if parts else rel_path)


def _project_of(rel_path: str) -> str:
    parts = rel_path.replace("\\", "/").split("/")
    return parts[1] if len(parts) >= 3 else ""


def _infer_id(rel_path: str, meta: dict) -> str:
    declared = (meta.get("id") or "").strip()
    if declared:
        return declared
    m = re.match(r"^\s*([A-Za-z]{2,8})[-_ ]?(\d{1,5})", os.path.basename(rel_path))
    if m:
        return f"{m.group(1).upper()}-{int(m.group(2)):03d}"
    return ""


def _infer_title(rel_path: str, meta: dict, body: str) -> str:
    declared = (meta.get("title") or "").strip()
    if declared:
        return declared
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("#"):
            head = s.lstrip("#").strip()
            if head:
                return head
    base = os.path.splitext(os.path.basename(rel_path))[0]
    base = re.sub(r"^[A-Za-z]{2,8}[-_ ]?\d{1,5}[-_ ]*", "", base).strip()
    return base or os.path.basename(rel_path)


def _as_list(v):
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    if not v:
        return []
    return [x for x in re.split(r"[,\s]+", str(v)) if x]


def _default_status(ttype: str) -> str:
    return STATUS_FLOW.get(ttype, ["draft"])[0]


# --------------------------------------------------------------------------
# Progress timeline (stored in the body, newest first)
# --------------------------------------------------------------------------
def progress_entries(body: str):
    """Parse the ``## 进展`` section into [{date, time, text}, …]."""
    out = []
    inside = False
    for line in (body or "").splitlines():
        s = line.strip()
        if s.startswith("#"):
            inside = s.lstrip("#").strip() == "进展"
            continue
        if not inside or not s.startswith("-"):
            continue
        txt = s.lstrip("-").strip()
        m = re.match(r"(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?\s+(.*)", txt)
        if m:
            out.append({"date": m.group(1), "time": m.group(2) or "", "text": m.group(3)})
        elif txt:
            out.append({"date": "", "time": "", "text": txt})
    return out


def append_progress(body: str, line: str) -> str:
    """Insert ``- line`` directly under the 进展 heading (newest on top)."""
    lines = (body or "").splitlines()
    for i, raw in enumerate(lines):
        s = raw.strip()
        if s.startswith("#") and s.lstrip("#").strip() == "进展":
            lines.insert(i + 1, "- " + line)
            return "\n".join(lines)
    tail = (body or "").rstrip("\n")
    return (tail + "\n\n" if tail else "") + PROGRESS_HEAD + "\n- " + line + "\n"


def _stamp(now: datetime.datetime) -> str:
    return now.strftime("%Y-%m-%d %H:%M")


# --------------------------------------------------------------------------
# Read
# --------------------------------------------------------------------------
def load(rel_path: str) -> dict:
    """Load one work item: frontmatter merged with inferred defaults."""
    text = vault.read_file(rel_path)
    meta, body = parse_frontmatter(text)
    ttype = _infer_type(rel_path, meta)

    tags = _as_list(meta.get("tags"))
    refs = _as_list(meta.get("refs"))
    status = (meta.get("status") or "").strip()
    if status not in STATUS_FLOW.get(ttype, []):
        status = _default_status(ttype)
    priority = (meta.get("priority") or "").strip()
    if priority not in PRIORITIES:
        priority = "medium"
    severity = (meta.get("severity") or "").strip()
    if severity not in SEVERITIES:
        severity = ""
    verdict = (meta.get("verdict") or "").strip()
    if verdict not in VERDICTS:
        verdict = ""

    progress = progress_entries(body)
    last = progress[0] if progress else {"date": "", "time": "", "text": ""}

    return {
        "path": rel_path.replace(os.sep, "/"),
        "name": os.path.basename(rel_path),
        "type": ttype,
        "id": _infer_id(rel_path, meta),
        "title": _infer_title(rel_path, meta, body),
        "project": (meta.get("project") or "").strip() or _project_of(rel_path),
        "status": status,
        "priority": priority,
        "owner": (meta.get("owner") or "").strip(),
        "created": (meta.get("created") or "").strip(),
        "updated": (meta.get("updated") or "").strip(),
        "tags": tags,
        "refs": refs,
        "severity": severity,
        "verdict": verdict,
        "body": body,
        "progress": progress,
        "last_activity": last,
        "mtime": int(os.path.getmtime(vault._resolve(rel_path))),
        "has_frontmatter": bool(meta),
    }


def list_items(type=None, project=None, status=None, q=None):
    """Every work item, optionally filtered. Reads straight off disk."""
    items = []
    for rel in _iter_files():
        try:
            items.append(load(rel))
        except (OSError, ValueError, UnicodeDecodeError):
            continue

    if type:
        items = [it for it in items if it["type"] == type]
    if project:
        items = [it for it in items if it["project"] == project]
    if status:
        items = [it for it in items if it["status"] == status]
    if q:
        needle = str(q).strip().lower()
        def hit(it):
            hay = " ".join([
                it["id"], it["title"], it["project"], " ".join(it["tags"]),
                TYPE_LABEL.get(it["type"], ""), it["body"],
            ]).lower()
            return needle in hay
        items = [it for it in items if hit(it)]

    items.sort(key=lambda it: (it.get("updated") or "", it["id"]), reverse=True)
    return items


def projects():
    root = work_root()
    if not os.path.isdir(root):
        return []
    return sorted(
        d for d in os.listdir(root)
        if os.path.isdir(os.path.join(root, d)) and not d.startswith("_")
    )


def meta():
    return {
        "types": [{"value": t, "label": TYPE_LABEL[t]} for t in TYPES],
        "type_dir": TYPE_DIR,
        "status_flow": STATUS_FLOW,
        "status_label": STATUS_LABEL,
        "priorities": list(PRIORITIES),
        "severities": [{"value": s, "label": SEVERITY_LABEL[s]} for s in SEVERITIES],
        "verdicts": list(VERDICTS),
        "projects": projects(),
        "work_dir": work_root(),
    }


# --------------------------------------------------------------------------
# Aggregation for the 总览 tab
# --------------------------------------------------------------------------
def board():
    items = list_items()
    today = datetime.date.today()
    today_s = today.isoformat()
    window_start = (today - datetime.timedelta(days=6)).isoformat()

    counts = {t: 0 for t in TYPES}
    for it in items:
        counts[it["type"]] = counts.get(it["type"], 0) + 1

    tracked = [it for it in items if it["type"] != "convention"]
    active = [it for it in tracked if it["status"] not in TERMINAL]
    stuck = [it for it in tracked if it["status"] in ("paused", "blocked")]

    today_items = [
        it for it in items
        if any(p["date"] == today_s for p in it["progress"])
    ]

    entries = []
    for it in items:
        for p in it["progress"]:
            if p["date"] and p["date"] >= window_start:
                entries.append({
                    "path": it["path"], "id": it["id"], "title": it["title"],
                    "type": it["type"], "date": p["date"], "time": p["time"],
                    "text": p["text"],
                })
    entries.sort(key=lambda e: (e["date"], e["time"]), reverse=True)

    released = sum(1 for e in entries if "released" in e["text"])
    closed = sum(1 for e in entries if "closed" in e["text"])

    return {
        "total": len(items),
        "counts": counts,
        "active_count": len(active),
        "stuck_count": len(stuck),
        "week_entry_count": len(entries),
        "released_this_week": released,
        "closed_this_week": closed,
        "today": today_items[:12],
        "active": active[:20],
        "stuck": stuck[:10],
        "entries": entries[:40],
        "projects": projects(),
    }


def progress(days: int = 7):
    days = max(1, min(int(days or 7), 90))
    start = (datetime.date.today() - datetime.timedelta(days=days - 1)).isoformat()
    out = []
    for it in list_items():
        for p in it["progress"]:
            if p["date"] and p["date"] >= start:
                out.append({
                    "path": it["path"], "id": it["id"], "title": it["title"],
                    "type": it["type"], "date": p["date"], "time": p["time"],
                    "text": p["text"],
                })
    out.sort(key=lambda e: (e["date"], e["time"]), reverse=True)
    return {"days": days, "start": start, "count": len(out), "entries": out}


# --------------------------------------------------------------------------
# Create / update / delete
# --------------------------------------------------------------------------
_UNSAFE = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def _slug(text: str) -> str:
    s = _UNSAFE.sub(" ", text or "").strip()
    s = re.sub(r"\s+", "-", s)
    return s[:40].strip("-.")


def next_id(ttype: str) -> str:
    prefix = TYPE_PREFIX.get(ttype, "NOTE")
    top = 0
    pat = re.compile(rf"^{prefix}[-_]?(\d{{1,6}})", re.I)
    for rel in _iter_files():
        m = pat.match(os.path.basename(rel))
        if m:
            top = max(top, int(m.group(1)))
    return f"{prefix}-{top + 1:03d}"


_TEMPLATE = {
    "requirement": (
        "\n## 背景 / 需求描述\n\n## 方案设计\n\n## 影响范围\n\n"
        "## 进展\n\n## 结论 / 复盘\n"
    ),
    "design": (
        "\n## 目标\n\n## 方案\n\n## 表结构 / 接口\n\n## 影响范围\n\n"
        "## 进展\n\n## 评审记录\n"
    ),
    "dev": (
        "\n## 改动内容\n\n## 涉及文件\n\n## SQL / 配置\n\n## 提测\n\n## 进展\n"
    ),
    "bug": "\n## 原因\n\n## 方案\n\n## 进展\n",
    "convention": "\n## 内容\n\n## 说明\n",
    "note": "\n## 内容\n",
}


def _unique_path(rel_path: str) -> str:
    if not os.path.exists(vault._resolve(rel_path)):
        return rel_path
    stem, ext = os.path.splitext(rel_path)
    for i in range(2, 200):
        cand = f"{stem}-{i}{ext}"
        if not os.path.exists(vault._resolve(cand)):
            return cand
    raise ValueError("too many files with the same name")


def create(type, title, project="", priority="medium", owner="", tags=None,
           body=None, status=None, severity="", verdict="", actor=None,
           origin=None, dedupe=True):
    """Create a work item file. Returns the freshly loaded item."""
    ttype = type if type in TYPES else "note"
    title = (title or "").strip() or "未命名"
    project = (project or "").strip()
    actor = actor or DEFAULT_ACTOR
    now = datetime.datetime.now()
    today_s = now.date().isoformat()

    item_id = next_id(ttype)
    parts = [WORK_SUBDIR]
    if project:
        parts.append(_slug(project) or project)
    sub = TYPE_DIR.get(ttype, "")
    if sub:
        parts.append(sub)
    slug = _slug(title)
    parts.append(f"{item_id}-{slug}.md" if slug else f"{item_id}.md")
    rel_path = "/".join(parts)
    if dedupe:
        rel_path = _unique_path(rel_path)

    if status not in STATUS_FLOW.get(ttype, []):
        status = _default_status(ttype)

    if body is None:
        text_body = f"# {item_id} {title}\n" + _TEMPLATE.get(ttype, "\n")
    else:
        text_body = body
        if not re.match(r"^\s*#\s", text_body):
            text_body = f"# {item_id} {title}\n\n" + text_body
    if PROGRESS_HEAD not in text_body:
        text_body = text_body.rstrip("\n") + "\n\n" + PROGRESS_HEAD + "\n"

    note = origin or actor
    text_body = append_progress(text_body, f"{_stamp(now)}  创建（{note}）")

    fm = {
        "id": item_id,
        "type": ttype,
        "title": title,
        "project": project,
        "status": status,
        "priority": priority if priority in PRIORITIES else "medium",
        "owner": owner or "",
        "created": today_s,
        "updated": today_s,
        "tags": _as_list(tags),
        "refs": [],
        "severity": severity if severity in SEVERITIES else "",
        "verdict": verdict if verdict in VERDICTS else "",
    }
    vault.write_file(rel_path, dump_frontmatter(fm) + "\n" + text_body)
    return load(rel_path)


def update(rel_path: str, fields=None, body=None, actor=None):
    """Update fields and/or body. Status changes append a timeline line."""
    fields = dict(fields or {})
    actor = actor or DEFAULT_ACTOR
    now = datetime.datetime.now()
    today_s = now.date().isoformat()

    item = load(rel_path)
    ttype = item["type"]
    old_status = item["status"]

    merged = {k: item.get(k) for k in _FIELDS}
    for k in _FIELDS:
        if k in fields and fields[k] is not None and k not in ("id", "type", "created"):
            merged[k] = fields[k]
    merged["id"] = item["id"] or next_id(ttype)
    merged["type"] = ttype

    new_body = item["body"] if body is None else body

    new_status = str(merged.get("status") or old_status).strip()
    if new_status not in STATUS_FLOW.get(ttype, []):
        new_status = old_status
    if new_status != old_status:
        new_body = append_progress(
            new_body, f"{_stamp(now)}  状态 {old_status} → {new_status}（{actor}）"
        )
    merged["status"] = new_status

    if merged.get("priority") not in PRIORITIES:
        merged["priority"] = "medium"
    if merged.get("severity") not in SEVERITIES:
        merged["severity"] = ""
    if merged.get("verdict") not in VERDICTS:
        merged["verdict"] = ""
    merged["tags"] = _as_list(merged.get("tags"))
    merged["refs"] = _as_list(merged.get("refs"))
    merged["project"] = (merged.get("project") or "").strip()
    merged["title"] = (merged.get("title") or "").strip() or item["title"]
    merged["created"] = merged.get("created") or today_s
    merged["updated"] = today_s

    text = dump_frontmatter(merged) + "\n" + new_body.lstrip("\n")
    vault.write_file(rel_path, text)
    return load(rel_path)


def delete(rel_path: str) -> bool:
    return vault.delete_file(rel_path)


# --------------------------------------------------------------------------
# Import (P1 — the "bring my history in" path)
# --------------------------------------------------------------------------
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_IMPORT_EXT = (".md", ".markdown", ".txt", ".docx")


def read_docx_text(abs_path: str) -> str:
    """Extract plain text from a .docx using only the standard library.

    Paragraph styles named ``Heading N`` become ``#`` * N, so imported
    documents keep a usable outline.
    """
    with zipfile.ZipFile(abs_path) as zf:
        xml = zf.read("word/document.xml")
    root = ET.fromstring(xml)
    out = []
    for para in root.iter(_W + "p"):
        style = ""
        ppr = para.find(_W + "pPr")
        if ppr is not None:
            pstyle = ppr.find(_W + "pStyle")
            if pstyle is not None:
                style = (pstyle.get(_W + "val") or "").strip()
        text = "".join(t.text or "" for t in para.iter(_W + "t")).strip()
        if not text:
            continue
        m = re.match(r"(?i)^heading\s*(\d)$", style)
        if m:
            text = "#" * min(int(m.group(1)), 6) + " " + text
        elif style.lower().startswith("heading"):
            text = "# " + text
        out.append(text)
    return "\n\n".join(out)


def scan_import_dir(dir_path: str, max_files: int = 500):
    """List importable documents under a local directory (read-only)."""
    if not dir_path or not str(dir_path).strip():
        raise ValueError("请填写目录路径")
    root = os.path.abspath(os.path.expanduser(str(dir_path).strip()))
    if not os.path.isdir(root):
        raise ValueError("目录不存在或无权限：" + root)

    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if not d.startswith(".") and d != "__pycache__"
        ]
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in _IMPORT_EXT:
                continue
            abs_path = os.path.join(dirpath, name)
            files.append({
                "name": name,
                "abs": abs_path.replace(os.sep, "/"),
                "rel": os.path.relpath(abs_path, root).replace(os.sep, "/"),
                "ext": ext,
                "size": os.path.getsize(abs_path),
                "mtime": int(os.path.getmtime(abs_path)),
                "guess_type": _guess_type_from_name(name),
            })
            if len(files) >= max_files:
                break
        if len(files) >= max_files:
            break

    files.sort(key=lambda f: -f["mtime"])
    return {"dir": root, "count": len(files), "files": files}


def _title_from_content(content: str, filename: str) -> str:
    for line in (content or "").splitlines():
        s = line.strip()
        if s.startswith("#"):
            head = s.lstrip("#").strip()
            if head:
                return head
    return os.path.splitext(os.path.basename(filename))[0]


def import_files(files, project="", type=None, actor=None):
    """Import documents into the Work Zone, verbatim and idempotently.

    Original text is preserved as-is; only structural wrapping is added. An
    existing file is never overwritten — a ``-2`` suffix is used instead.
    """
    dest = (project or "").strip() or "_inbox"
    actor = actor or DEFAULT_ACTOR
    created, skipped = [], []

    for raw in files or []:
        abs_path = os.path.abspath(os.path.expanduser(str(raw).strip()))
        if not os.path.isfile(abs_path):
            skipped.append({"file": abs_path, "reason": "文件不存在"})
            continue
        ext = os.path.splitext(abs_path)[1].lower()
        try:
            if ext == ".docx":
                content = read_docx_text(abs_path)
            else:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
        except Exception as exc:  # noqa: BLE001 - report, don't crash the batch
            skipped.append({"file": abs_path, "reason": f"{type(exc).__name__}: {exc}"})
            continue

        name = os.path.basename(abs_path)
        ttype = type if type in TYPES else _guess_type_from_name(name)
        title = _title_from_content(content, name)
        try:
            item = create(
                type=ttype,
                title=title,
                project=dest,
                body=content,
                origin=f"导入：{name}",
                actor=actor,
            )
        except (OSError, ValueError) as exc:
            skipped.append({"file": abs_path, "reason": str(exc)})
            continue
        created.append(item)

    return {"count": len(created), "items": created, "skipped": skipped}
