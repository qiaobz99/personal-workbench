"""Re-index the Vault into the full-text (FTS5) store and, if available,
the Chroma semantic store.

Called on startup and on demand (UI "Re-index" button / ``POST /api/reindex``).
"""
import os
import re

import config
import vault
import store
import chroma_client

_DOC_EXT = (".md", ".markdown", ".txt")


def _title(content: str, rel_path: str) -> str:
    """Best available human title: front-matter ``title:`` then first heading.

    Vault notes usually open with YAML front-matter and their first Markdown
    heading is a sub-section ("## 基本信息"), which is useless both in the UI
    list and as a retrieval signal, so front-matter wins when it is present.
    """
    head = content[:2000]
    fm = re.match(r"^---\s*\n(.*?)\n---\s*\n", head, re.S)
    if fm:
        for line in fm.group(1).splitlines():
            if line.strip().lower().startswith("title:"):
                t = line.split(":", 1)[1].strip().strip("\"'").strip()
                if t:
                    return t
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("#"):
            t = line.lstrip("#").strip()
            if t:
                return t
    return os.path.basename(rel_path)


def index_file(rel_path: str) -> bool:
    """Index a single Vault file (used after an API write)."""
    abs_path = os.path.join(vault.vault_root(), rel_path.replace("/", os.sep))
    if not os.path.isfile(abs_path):
        return False
    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return False
    rel = rel_path.replace(os.sep, "/")
    store.upsert_doc(rel, _title(content, rel), content, int(os.path.getmtime(abs_path)))
    if chroma_client.is_available():
        chroma_client.index_doc(rel, _title(content, rel), content)
    return True


def reindex() -> dict:
    root = vault.vault_root()
    fts = 0
    semantic = 0
    semantic_on = chroma_client.is_available()
    seen = set()

    for dirpath, dirnames, filenames in os.walk(root):
        # Skip hidden / cache dirs.
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "__pycache__"]
        for name in filenames:
            if not name.lower().endswith(_DOC_EXT) or name.startswith("."):
                continue
            abs_path = os.path.join(dirpath, name)
            rel = os.path.relpath(abs_path, root).replace(os.sep, "/")
            try:
                with open(abs_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except (OSError, UnicodeDecodeError):
                continue
            title = _title(content, rel)
            mtime = int(os.path.getmtime(abs_path))
            store.upsert_doc(rel, title, content, mtime)
            seen.add(rel)
            fts += 1
            if semantic_on and chroma_client.index_doc(rel, title, content):
                semantic += 1

    # Upsert alone leaves rows for files that were deleted / renamed / moved.
    pruned = store.prune_docs(seen)

    return {
        "indexed_fts": fts,
        "indexed_semantic": semantic,
        "semantic_available": semantic_on,
        "pruned_stale": pruned,
    }
