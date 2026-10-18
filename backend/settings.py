"""Runtime-editable settings, persisted in the SQLite ``meta`` table.

The Settings page writes here, so anyone can point the workbench at their
own LLM without editing code. Real environment variables still take
precedence over saved values, which lets a deployment pin a config that the
UI must not silently override.

Resolution order for every field:  env var  >  saved setting  >  default.

``api_key`` / ``model`` / ``base_url`` are stored **per provider**, so
switching from DeepSeek to Ollama never leaks one vendor's key or model name
into another -- each vendor keeps its own.
"""
import os

import store

# provider -> (base_url, default_model). Every provider speaks the
# OpenAI-compatible /v1/chat/completions protocol, so the provider only
# decides the endpoint and the default model name.
PROVIDERS = {
    "deepseek": ("https://api.deepseek.com/v1", "deepseek-chat"),
    "qwen": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "ollama": ("http://localhost:11434/v1", "qwen2.5:7b"),
}
DEFAULT_PROVIDER = "deepseek"

# Ollama runs on the user's own machine and therefore needs no API key.
NO_KEY_PROVIDERS = {"ollama"}

_META_PROVIDER = "llm.provider"
_ENV_PROVIDER = "KB_LLM_PROVIDER"

# field -> env var; stored per provider, e.g. meta key "llm.api_key.ollama".
_PER_PROVIDER = {
    "api_key": "KB_LLM_KEY",
    "model": "KB_LLM_MODEL",
    "base_url": "KB_LLM_BASE_URL",
}

# Human-readable provenance labels, shown in the UI.
SOURCE_LABELS = {
    "env": "环境变量",
    "settings": "设置页",
    "default": "默认值",
    "preview": "未保存",
}


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _meta(key: str) -> str:
    try:
        return (store.get_meta(key) or "").strip()
    except Exception:  # noqa: BLE001 - a missing DB must not break settings
        return ""


def _defaults(provider: str):
    return PROVIDERS.get(provider, PROVIDERS[DEFAULT_PROVIDER])


def resolve_provider() -> str:
    """The provider that is actually in effect right now."""
    return _env(_ENV_PROVIDER) or _meta(_META_PROVIDER) or DEFAULT_PROVIDER


def effective(provider: str = "") -> dict:
    """The live config, or a preview of ``provider`` if one is passed.

    Returns ``{provider, api_key, model, base_url, source}`` where ``source``
    maps each field to "env" / "settings" / "default" (and "preview" for the
    provider itself when previewing an unsaved choice).
    """
    wanted = (provider or "").strip()
    if wanted:
        active = wanted
        source = {"provider": "preview"}
    else:
        active = resolve_provider()
        env_p = _env(_ENV_PROVIDER)
        source = {
            "provider": "env" if env_p else ("settings" if _meta(_META_PROVIDER) else "default")
        }

    cfg = {"provider": active}
    for field, env_name in _PER_PROVIDER.items():
        env = _env(env_name)
        if env:
            cfg[field], source[field] = env, "env"
            continue
        saved = _meta(f"llm.{field}.{active}")
        if saved:
            cfg[field], source[field] = saved, "settings"
            continue
        cfg[field], source[field] = "", "default"

    base_default, model_default = _defaults(active)
    cfg["base_url"] = cfg["base_url"] or base_default
    cfg["model"] = cfg["model"] or model_default
    cfg["source"] = source
    return cfg


def masked_key(key: str) -> str:
    """Never send a full API key back to the browser."""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return key[:4] + "****" + key[-4:]


def is_configured(provider: str = "") -> bool:
    cfg = effective(provider)
    if cfg["provider"] in NO_KEY_PROVIDERS:
        return True
    return bool(cfg["api_key"])


def public_view(provider: str = "") -> dict:
    """Everything the Settings page needs, with the key masked.

    Pass ``provider`` to preview another vendor's stored config (used when
    the user flips the dropdown but has not saved yet).
    """
    cfg = effective(provider)
    active = cfg["provider"]
    return {
        "provider": active,
        "providers": [
            {
                "id": pid,
                "default_model": default_model,
                "needs_key": pid not in NO_KEY_PROVIDERS,
            }
            for pid, (_base, default_model) in PROVIDERS.items()
        ],
        "model": cfg["model"],
        "base_url": cfg["base_url"],
        "key_masked": masked_key(cfg["api_key"]),
        "has_key": bool(cfg["api_key"]),
        "configured": is_configured(active),
        "source": cfg["source"],
        "source_labels": SOURCE_LABELS,
        "env_vars": dict(_PER_PROVIDER, provider=_ENV_PROVIDER),
    }


def save(data: dict) -> dict:
    """Persist values coming from the Settings page.

    A field missing from ``data`` is left untouched -- that is how the UI can
    change the model without ever round-tripping the API key. Values are
    written against the provider named in ``data`` (or the active one).
    """
    if "provider" in data and data.get("provider") is not None:
        chosen = str(data.get("provider") or "").strip()
        store.set_meta(_META_PROVIDER, chosen)
        target = chosen or DEFAULT_PROVIDER
    else:
        target = resolve_provider()

    for field in _PER_PROVIDER:
        if field not in data:
            continue
        raw = data.get(field)
        if raw is None:
            continue
        store.set_meta(f"llm.{field}.{target}", str(raw).strip())

    return public_view(target if "provider" in data else "")
