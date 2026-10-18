"""金融日记 — 按年归档、按日填写的日记类笔记。

设计（一句话）：**一天一篇，一年一目录。**

每个「日」对应一个 Markdown 文件，路径 ``vault/diary/<YYYY>/<YYYY-MM-DD>.md``：

* 一年一个目录（``diary/2026/``），天然按年归档，目录名就是年份；
* 一天一文件，按日填写，文件名就是日期，排序即时间序；
* 文件仍是 vault 的一部分，知识库目录树、全文检索照旧找得到；
* 与「日常工作」不同，金融日记没有类型/状态机——它就是一页页日期纸，
  轻量、随手记，符合「日记」的心智模型。

只依赖标准库。
"""
import datetime
import os
import re

import vault

DIARY_SUBDIR = "diary"

# 新建一篇日记时塞进正文的开头骨架，给个好下笔的模板。
_TEMPLATE = (
    "\n## 市场观察\n\n## 操作 / 持仓\n\n"
    "## 复盘 / 心得\n\n## 备注\n"
)


# --------------------------------------------------------------------------
# Path helpers
# --------------------------------------------------------------------------
def diary_root() -> str:
    return os.path.join(vault.vault_root(), DIARY_SUBDIR)


def _date_dir(year: str) -> str:
    return os.path.join(diary_root(), str(year))


def _rel_for(date_str: str) -> str:
    """vault 相对路径：``diary/<YYYY>/<YYYY-MM-DD>.md``。"""
    return f"{DIARY_SUBDIR}/{date_str[:4]}/{date_str}.md"


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_date(d: str):
    if not _DATE_RE.match(d or ""):
        raise ValueError("日期格式应为 YYYY-MM-DD")
    try:
        datetime.date.fromisoformat(d)
    except ValueError:
        raise ValueError("非法日期：" + str(d))


# --------------------------------------------------------------------------
# Minimal frontmatter (only title + tags, kept intentionally tiny)
# --------------------------------------------------------------------------
_FM_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.S)


def _as_list(v):
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    if not v:
        return []
    return [x for x in re.split(r"[,\s]+", str(v)) if x]


def _q(s: str) -> str:
    s = str(s)
    if re.search(r'[:#\[\]{}"\']', s) or s != s.strip():
        return '"' + s.replace('"', '\\"') + '"'
    return s


def _parse_fm(text: str):
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if k == "title":
            meta["title"] = v.strip('"').strip("'")
        elif k == "tags":
            if v.startswith("[") and v.endswith("]"):
                inner = v[1:-1].strip()
                meta["tags"] = [x.strip().strip('"').strip("'")
                                for x in inner.split(",") if x.strip()]
            else:
                meta["tags"] = _as_list(v)
    return meta, text[m.end():]


def _dump_fm(title: str, tags) -> str:
    lines = ["---"]
    if title:
        lines.append("title: " + _q(title))
    if tags:
        lines.append("tags: [" + ", ".join(_as_list(tags)) + "]")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _title_from_body(body: str, fallback: str) -> str:
    for line in (body or "").splitlines():
        s = line.strip()
        if s.startswith("#"):
            head = s.lstrip("#").strip()
            if head:
                return head
    return fallback


# --------------------------------------------------------------------------
# Read
# --------------------------------------------------------------------------
def years() -> list:
    """所有有日记的年份（倒序），附该年篇数 —— 用于「按年归档」。"""
    root = diary_root()
    if not os.path.isdir(root):
        return []
    out = []
    for name in sorted(os.listdir(root)):
        if re.match(r"^\d{4}$", name) and os.path.isdir(os.path.join(root, name)):
            cnt = _count_files(os.path.join(root, name))
            if cnt:
                out.append({"year": name, "count": cnt})
    out.sort(key=lambda x: x["year"], reverse=True)
    return out


def _count_files(abs_dir: str) -> int:
    try:
        return sum(
            1 for n in os.listdir(abs_dir)
            if n.lower().endswith(".md") and _DATE_RE.match(n[:-3])
        )
    except OSError:
        return 0


def year(y: str) -> dict:
    """某一年的全部日记（按日期升序），以及各月篇数。"""
    _validate_date(y + "-01-01")  # 顺手校验年份形
    d = _date_dir(y)
    entries = []
    if os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            if not name.lower().endswith(".md"):
                continue
            date_str = name[:-3]
            if not _DATE_RE.match(date_str):
                continue
            try:
                text = vault.read_file(f"{DIARY_SUBDIR}/{y}/{name}")
            except (OSError, UnicodeDecodeError):
                continue
            meta, body = _parse_fm(text)
            entries.append({
                "date": date_str,
                "title": meta.get("title") or date_str,
                "tags": meta.get("tags", []),
                "has_body": bool(body.strip()),
            })
    months = {}
    for e in entries:
        m = int(e["date"][5:7])
        months[m] = months.get(m, 0) + 1
    return {"year": y, "entries": entries, "months": months}


def load_day(date_str: str) -> dict:
    """读取某一天的日记；不存在时返回 ``exists=False``（不落盘）。"""
    _validate_date(date_str)
    rel = _rel_for(date_str)
    try:
        text = vault.read_file(rel)
    except FileNotFoundError:
        return {"date": date_str, "path": rel, "exists": False,
                "title": "", "tags": [], "body": ""}
    meta, body = _parse_fm(text)
    return {
        "date": date_str,
        "path": rel,
        "exists": True,
        "title": meta.get("title") or _title_from_body(body, date_str),
        "tags": meta.get("tags", []),
        "body": body,
    }


# --------------------------------------------------------------------------
# Write / delete
# --------------------------------------------------------------------------
def save_day(date_str: str, title=None, tags=None, body=None) -> dict:
    """新建或覆盖某一天的日记。返回写完后重新加载的日记。"""
    _validate_date(date_str)
    rel = _rel_for(date_str)
    body = (body or "").strip() + "\n"
    title = (title or "").strip() or date_str  # 标题留空 → 用日期兜底
    tags = _as_list(tags)
    text = _dump_fm(title, tags) + "\n" + body
    vault.write_file(rel, text)
    return load_day(date_str)


def delete_day(date_str: str) -> bool:
    _validate_date(date_str)
    rel = _rel_for(date_str)
    ok = vault.delete_file(rel)
    # 年份目录空了就顺手删掉，保持 vault 干净（不影响任何其它数据）。
    yr_dir = _date_dir(date_str[:4])
    try:
        if os.path.isdir(yr_dir) and not os.listdir(yr_dir):
            os.rmdir(yr_dir)
    except OSError:
        pass
    return ok
