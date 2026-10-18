"""OpenAI-compatible LLM client for the RAG answer layer.

One implementation serves every provider -- DeepSeek (default), Qwen,
OpenAI and Ollama all speak the same ``/v1/chat/completions`` protocol.
Switching provider is therefore just a configuration change
(``KB_LLM_PROVIDER`` / ``KB_LLM_KEY`` / ``KB_LLM_MODEL``), either from the
in-app Settings page or from environment variables -- never a code edit.

Zero third-party dependencies: the request is a plain stdlib ``urllib`` call.
"""
import json
import urllib.error
import urllib.request

import settings


def is_configured() -> bool:
    """True when the active provider has everything it needs to run."""
    return settings.is_configured()


def provider_info() -> dict:
    """Small descriptor for the UI (which model, and whether it is ready)."""
    cfg = settings.effective()
    return {
        "provider": cfg["provider"],
        "model": cfg["model"],
        "configured": is_configured(),
        "source": cfg["source"],
    }


def chat(system: str, user: str, temperature: float = 0.3, timeout: int = 60) -> str:
    """Send one chat completion request and return the assistant text.

    The config is resolved on every call, so a Settings-page change takes
    effect immediately -- no server restart needed.
    """
    cfg = settings.effective()
    url = (cfg["base_url"] or "").rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg["model"],
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    headers = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(f"LLM HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"LLM 连接失败: {e.reason}") from e
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("LLM 返回为空")
    return (choices[0].get("message") or {}).get("content", "").strip()
