"""Vault operations: a directory tree of Markdown files (the source of truth).

All public functions resolve paths *inside* ``config.VAULT_DIR`` and reject
anything that tries to escape it, so the HTTP API can never touch files
outside the Vault.
"""
import os

import config


# --------------------------------------------------------------------------
# Path safety
# --------------------------------------------------------------------------
def _resolve(rel_path: str) -> str:
    """Resolve a Vault-relative path to an absolute path, safely."""
    if not rel_path:
        raise ValueError("empty path")
    # Normalise and prevent path traversal.
    full = os.path.normpath(os.path.join(config.VAULT_DIR, rel_path))
    root = os.path.normpath(config.VAULT_DIR)
    if full != root and not full.startswith(root + os.sep):
        raise ValueError("path escapes the vault")
    return full


def vault_root() -> str:
    return os.path.normpath(config.VAULT_DIR)


# --------------------------------------------------------------------------
# Tree
# --------------------------------------------------------------------------
def list_tree() -> dict:
    """Return a nested dict describing the Vault directory tree."""
    root = vault_root()
    tree = {"name": os.path.basename(root), "path": "", "type": "dir", "children": []}

    def walk(abs_dir: str, node: dict):
        try:
            entries = sorted(os.listdir(abs_dir))
        except OSError:
            return
        for name in entries:
            if name.startswith(".") or name == "__pycache__":
                continue
            abs_path = os.path.join(abs_dir, name)
            rel = os.path.relpath(abs_path, root)
            rel = rel.replace(os.sep, "/")
            if os.path.isdir(abs_path):
                child = {"name": name, "path": rel, "type": "dir", "children": []}
                walk(abs_path, child)
                node["children"].append(child)
            elif name.lower().endswith((".md", ".markdown", ".txt")):
                node["children"].append(
                    {
                        "name": name,
                        "path": rel,
                        "type": "file",
                        "size": os.path.getsize(abs_path),
                        "mtime": int(os.path.getmtime(abs_path)),
                    }
                )

    walk(root, tree)
    return tree


def list_dir(rel_path: str = "") -> list:
    """Flat listing of a single directory."""
    abs_dir = _resolve(rel_path) if rel_path else vault_root()
    if not os.path.isdir(abs_dir):
        return []
    out = []
    for name in sorted(os.listdir(abs_dir)):
        if name.startswith(".") or name == "__pycache__":
            continue
        abs_path = os.path.join(abs_dir, name)
        rel = os.path.relpath(abs_path, vault_root()).replace(os.sep, "/")
        if os.path.isdir(abs_path):
            out.append({"name": name, "path": rel, "type": "dir"})
        elif name.lower().endswith((".md", ".markdown", ".txt")):
            out.append(
                {
                    "name": name,
                    "path": rel,
                    "type": "file",
                    "size": os.path.getsize(abs_path),
                    "mtime": int(os.path.getmtime(abs_path)),
                }
            )
    return out


# --------------------------------------------------------------------------
# File CRUD
# --------------------------------------------------------------------------
def read_file(rel_path: str) -> str:
    abs_path = _resolve(rel_path)
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(rel_path)
    with open(abs_path, "r", encoding="utf-8") as f:
        return f.read()


def write_file(rel_path: str, content: str, create_dirs: bool = True) -> dict:
    abs_path = _resolve(rel_path)
    if create_dirs:
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(content)
    return {
        "path": rel_path.replace(os.sep, "/"),
        "size": os.path.getsize(abs_path),
        "mtime": int(os.path.getmtime(abs_path)),
    }


def delete_file(rel_path: str) -> bool:
    abs_path = _resolve(rel_path)
    if os.path.isfile(abs_path):
        os.remove(abs_path)
        return True
    return False


def file_meta(rel_path: str) -> dict:
    abs_path = _resolve(rel_path)
    return {
        "path": rel_path.replace(os.sep, "/"),
        "exists": os.path.isfile(abs_path),
        "size": os.path.getsize(abs_path) if os.path.isfile(abs_path) else 0,
        "mtime": int(os.path.getmtime(abs_path)) if os.path.isfile(abs_path) else 0,
    }
