"""Local Ollama lookup for Stella — localhost only, offline-safe.

Used when creating a profile: offer the models already installed on
this PC so the user picks from real tags instead of typing one from
memory. If Ollama is down (or not installed), this returns an empty
list and the GUI falls back to manual tag entry. No network beyond
localhost, no exceptions escape.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

DEFAULT_URL = "http://localhost:11434"
TIMEOUT_SECONDS = 2.0
CHAT_TIMEOUT_SECONDS = 120.0


class OllamaError(Exception):
    """Ollama did not answer, or answered with something unusable."""


def ollama_url() -> str:
    return os.environ.get("STELLA_OLLAMA_URL", DEFAULT_URL).rstrip("/")


def list_models(url: str | None = None, timeout: float = TIMEOUT_SECONDS) -> list[str]:
    """Return installed Ollama model tags, or [] if unreachable."""
    base = (url or ollama_url()).rstrip("/")
    try:
        req = urllib.request.Request(base + "/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return []
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return []
    names = []
    for entry in models:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            names.append(entry["name"])
    return sorted(names)


def chat(
    model: str,
    messages: list[dict],
    *,
    url: str | None = None,
    timeout: float = CHAT_TIMEOUT_SECONDS,
) -> str:
    """One /api/chat call, no streaming. Returns the reply text.

    Unlike list_models, this raises OllamaError on failure: the
    caller (the chat agent) turns every failure into a plain-words
    message for the user instead of silently returning nothing.
    """
    base = (url or ollama_url()).rstrip("/")
    payload = json.dumps(
        {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 1024},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        base + "/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", "")
        except (ValueError, OSError):
            pass
        raise OllamaError(
            f"Ollama said no ({exc.code})"
            + (f": {detail}" if detail else "")
        ) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise OllamaError(
            "Ollama is not answering. Start Ollama and try again."
        ) from exc
    except ValueError as exc:
        raise OllamaError("Ollama answered with something unreadable.") from exc
    message = body.get("message") if isinstance(body, dict) else None
    text = message.get("content") if isinstance(message, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise OllamaError("Ollama answered with no text.")
    return text
