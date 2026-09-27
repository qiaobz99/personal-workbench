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
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()
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
            fts += 1
            if semantic_on and chroma_client.index_doc(rel, title, content):
                semantic += 1

    return {
        "indexed_fts": fts,
        "indexed_semantic": semantic,
        "semantic_available": semantic_on,
    }
