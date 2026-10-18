"""日报 / 周报 — 手动记录的主观完成内容。

与「日志」（系统自动汇总的文件/任务活动）不同，这里是**人手动写**的：

* 日报（daily）：今天完成了啥、做了啥 —— 一天一篇；
* 周报（weekly）：本周做了啥、下周计划 —— 一周一篇（以周一日期为键）。

数据仍是 Vault 里的 Markdown，路径：

* ``vault/dreport/daily/<YYYY>/<YYYY-MM-DD>.md``
* ``vault/dreport/weekly/<YYYY>/<YYYY-MM-DD>.md``  （键 = 该周周一日期）

一年一目录，天然「按年归档」；文件自动进知识库目录树 + 全文检索。
只依赖标准库。
"""
import datetime
import os
import re

import vault

DREPORT_SUBDIR = "dreport"
KINDS = ("daily", "weekly")

# 新建一篇时塞进正文的开头骨架。
_TEMPLATES = {
    "daily": (
        "\n## 今日完成\n\n## 进行中\n\n## 明日计划\n\n"
        "## 风险 / 阻塞\n\n## 备注\n"
    ),
    "weekly": (
        "\n## 本周完成\n\n## 下周计划\n\n## 问题与风险\n\n## 其他\n"
    ),
}


# --------------------------------------------------------------------------
# Path helpers
# --------------------------------------------------------------------------
def dreport_root() -> str:
    return os.path.join(vault.vault_root(), DREPORT_SUBDIR)


def _kind(kind: str) -> str:
    if kind not in KINDS:
        raise ValueError("kind 必须是 daily 或 weekly")
    return kind


def _date_dir(kind: str, year: str) -> str:
    return os.path.join(dreport_root(), kind, str(year))


def _rel_for(kind: str, key: str) -> str:
    """vault 相对路径：``dreport/<kind>/<YYYY>/<key>.md``。"""
    return f"{DREPORT_SUBDIR}/{kind}/{key[:4]}/{key}.md"


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_date(d: str):
    if not _DATE_RE.match(d or ""):
        raise ValueError("日期格式应为 YYYY-MM-DD")
    try:
        datetime.date.fromisoformat(d)
    except ValueError:
        raise ValueError("非法日期：" + str(d))


def _validate_key(kind: str, key: str):
    _validate_date(key)
    if kind == "weekly":
        # 周报以「周一」为键，保证一年里的周不重不漏。
        if datetime.date.fromisoformat(key).weekday() != 0:
            raise ValueError("周报键必须是周一日期（YYYY-MM-DD）")


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


def _week_range(monday_str: str) -> str:
    """返回 ``MM-DD ~ MM-DD`` 形式的周区间标签。"""
    mon = datetime.date.fromisoformat(monday_str)
    sun = mon + datetime.timedelta(days=6)
    return f"{mon.month:02d}-{mon.day:02d} ~ {sun.month:02d}-{sun.day:02d}"


# --------------------------------------------------------------------------
# Read
# --------------------------------------------------------------------------
def years(kind: str) -> list:
    """所有有记录的年份（倒序），附该年篇数。"""
    kind = _kind(kind)
    root = os.path.join(dreport_root(), kind)
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


def year(kind: str, y: str) -> dict:
    """某一年的全部记录（按键升序），以及各月篇数（日报用）。"""
    kind = _kind(kind)
    _validate_date(y + "-01-01")
    d = _date_dir(kind, y)
    entries = []
    if os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            if not name.lower().endswith(".md"):
                continue
            key = name[:-3]
            if not _DATE_RE.match(key):
                continue
            try:
                text = vault.read_file(f"{DREPORT_SUBDIR}/{kind}/{y}/{name}")
            except (OSError, UnicodeDecodeError):
                continue
            meta, body = _parse_fm(text)
            entries.append({
                "key": key,
                "title": meta.get("title") or key,
                "tags": meta.get("tags", []),
                "has_body": bool(body.strip()),
            })
    months = {}
    for e in entries:
        m = int(e["key"][5:7])
        months[m] = months.get(m, 0) + 1
    return {"year": y, "kind": kind, "entries": entries, "months": months}


def weeks(kind: str, y: str) -> list:
    """某一年的全部周（以周一为键，连续覆盖全年），附是否有记录。

    仅对 weekly 有意义；返回 ``[{"key","label","has"}]``，按周升序。
    """
    kind = _kind(kind)
    _validate_date(y + "-01-01")
    if kind != "weekly":
        return []
    entries = {e["key"] for e in year(kind, y).get("entries", [])}
    jan1 = datetime.date(int(y), 1, 1)
    # 该年第一个周一（可能落在上一年最后几天，保证周连续）。
    start = jan1 - datetime.timedelta(days=jan1.weekday())
    dec31 = datetime.date(int(y), 12, 31)
    end = dec31 - datetime.timedelta(days=dec31.weekday())
    out = []
    cur = start
    while cur <= end:
        ks = cur.isoformat()
        out.append({
            "key": ks,
            "label": _week_range(ks),
            "has": ks in entries,
        })
        cur += datetime.timedelta(days=7)
    return out


def load(kind: str, key: str) -> dict:
    """读取某篇日报/周报；不存在时返回 ``exists=False``（不落盘）。"""
    kind = _kind(kind)
    _validate_key(kind, key)
    rel = _rel_for(kind, key)
    try:
        text = vault.read_file(rel)
    except FileNotFoundError:
        return {"kind": kind, "key": key, "path": rel, "exists": False,
                "title": "", "tags": [], "body": ""}
    meta, body = _parse_fm(text)
    return {
        "kind": kind,
        "key": key,
        "path": rel,
        "exists": True,
        "title": meta.get("title") or _title_from_body(body, key),
        "tags": meta.get("tags", []),
        "body": body,
    }


# --------------------------------------------------------------------------
# Write / delete
# --------------------------------------------------------------------------
def save(kind: str, key: str, title=None, tags=None, body=None) -> dict:
    """新建或覆盖某篇日报/周报。返回写完后重新加载的记录。"""
    kind = _kind(kind)
    _validate_key(kind, key)
    rel = _rel_for(kind, key)
    body = (body or "").strip() + "\n"
    title = (title or "").strip() or key  # 标题留空 → 用键兜底
    tags = _as_list(tags)
    text = _dump_fm(title, tags) + "\n" + body
    vault.write_file(rel, text)
    return load(kind, key)


def delete(kind: str, key: str) -> bool:
    kind = _kind(kind)
    _validate_key(kind, key)
    rel = _rel_for(kind, key)
    ok = vault.delete_file(rel)
    # 年份目录空了就顺手删掉，保持 vault 干净（不影响任何其它数据）。
    yr_dir = _date_dir(kind, key[:4])
    try:
        if os.path.isdir(yr_dir) and not os.listdir(yr_dir):
            os.rmdir(yr_dir)
    except OSError:
        pass
    return ok
