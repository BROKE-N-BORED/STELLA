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
