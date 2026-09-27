"""Daily / weekly report aggregation.

Builds a structured report from the Vault: which notes were created or
modified in the period, the day's daily note (if any), and the current task
board state. Pure stdlib — no AI call required, so it always works offline.
"""
import datetime
import os

import vault
import store
import chroma_client

_DOC_EXT = (".md", ".markdown", ".txt")


def _iter_vault_files():
    root = vault.vault_root()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "__pycache__"]
        for name in filenames:
            if not name.lower().endswith(_DOC_EXT) or name.startswith("."):
                continue
            abs_path = os.path.join(dirpath, name)
            rel = os.path.relpath(abs_path, root).replace(os.sep, "/")
            yield rel, abs_path


def _read(rel: str) -> str:
    try:
        return vault.read_file(rel)
    except Exception:
        return ""


def daily_report(date: str = None) -> dict:
    """``date`` is ``YYYY-MM-DD``; defaults to today (local)."""
    if not date:
        date = datetime.date.today().isoformat()
    day = datetime.date.fromisoformat(date)
    start = datetime.datetime(day.year, day.month, day.day, 0, 0, 0)
    end = start + datetime.timedelta(days=1)

    created, modified = [], []
    for rel, abs_path in _iter_vault_files():
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(abs_path))
        if start <= mtime < end:
            (created if mtime >= start else modified).append(rel)

    daily_note = _read(f"daily/{date}.md")
    tasks = store.list_tasks()

    return {
        "type": "daily",
        "date": date,
        "created": sorted(created),
        "modified": sorted(modified),
        "daily_note": daily_note,
        "tasks": {
            "todo": [t for t in tasks if t["status"] == "todo"],
            "doing": [t for t in tasks if t["status"] == "doing"],
            "done": [t for t in tasks if t["status"] == "done"],
        },
        "task_counts": {
            "todo": sum(1 for t in tasks if t["status"] == "todo"),
            "doing": sum(1 for t in tasks if t["status"] == "doing"),
            "done": sum(1 for t in tasks if t["status"] == "done"),
        },
    }


def weekly_report(week_start: str = None) -> dict:
    """ISO week starting Monday. ``week_start`` is ``YYYY-MM-DD``."""
    if week_start:
        monday = datetime.date.fromisoformat(week_start)
    else:
        today = datetime.date.today()
        monday = today - datetime.timedelta(days=today.weekday())
    days = [monday + datetime.timedelta(days=i) for i in range(7)]
    start = datetime.datetime(monday.year, monday.month, monday.day, 0, 0, 0)
    end = start + datetime.timedelta(days=7)

    created, modified = [], []
    for rel, abs_path in _iter_vault_files():
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(abs_path))
        if start <= mtime < end:
            (created if mtime >= start else modified).append(rel)

    tasks = store.list_tasks()
    return {
        "type": "weekly",
        "week_start": monday.isoformat(),
        "week_end": (monday + datetime.timedelta(days=6)).isoformat(),
        "created": sorted(created),
        "modified": sorted(modified),
        "tasks": {
            "todo": [t for t in tasks if t["status"] == "todo"],
            "doing": [t for t in tasks if t["status"] == "doing"],
            "done": [t for t in tasks if t["status"] == "done"],
        },
        "task_counts": {
            "todo": sum(1 for t in tasks if t["status"] == "todo"),
            "doing": sum(1 for t in tasks if t["status"] == "doing"),
            "done": sum(1 for t in tasks if t["status"] == "done"),
        },
    }


def overview_stats() -> dict:
    """Quick numbers for the dashboard."""
    total_docs = store.count_docs()
    tasks = store.list_tasks()
    today = datetime.date.today().isoformat()
    week_ago = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()

    # Count files modified this week.
    root = vault.vault_root()
    recent = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "__pycache__"]
        for name in filenames:
            if not name.lower().endswith(_DOC_EXT):
                continue
            abs_path = os.path.join(dirpath, name)
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(abs_path)).isoformat()
            if mtime >= week_ago:
                recent += 1

    return {
        "total_docs": total_docs,
        "task_counts": {
            "todo": sum(1 for t in tasks if t["status"] == "todo"),
            "doing": sum(1 for t in tasks if t["status"] == "doing"),
            "done": sum(1 for t in tasks if t["status"] == "done"),
        },
        "recent_this_week": recent,
        "today": today,
        "semantic_available": chroma_client.is_available(),
    }
