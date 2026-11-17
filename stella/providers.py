"""STELLA AI providers: the chat can talk to a model on this PC
(Ollama) or a cloud provider (Groq, Gemini, or any OpenAI-compatible
service) using the user's own API key.

Keys live ONLY in <home>/providers.json, file mode 0600. They are
never in code, never in exports, never in debug reports. The file
is a plain JSON object keyed by provider id:

    {"groq": {"api_key": "gsk_..."},
     "gemini": {"api_key": "AIza..."},
     "custom": {"api_key": "...", "base_url": "...", "model": "..."}}

The nested "api_key" name matters: the debug-log scrubber redacts
any value stored under a key name containing "key", so even the
file's contents pass through a report scrubbed. The custom slot is
for ANY other provider, including ones Stella has never heard of:
the user supplies a base URL, a key, and a model name.

HTTP follows the ollama.py pattern (urllib, no new dependency).
Groq and Gemini both speak the OpenAI chat shape: Gemini through
Google's OpenAI-compatible endpoint, with the API key as the
Bearer token.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from .model import StellaError, default_home
from .ollama import OllamaError, chat as ollama_chat, list_models

PROVIDERS_FILE = "providers.json"
CHAT_TIMEOUT_SECONDS = 120.0
TEST_TIMEOUT_SECONDS = 30.0

# provider id -> display name, whether it needs a key, the chat
# endpoint (OpenAI-compatible shape), and a short curated model
# list. Any model name works, not just the curated ones: the lists
# are suggestions, and the custom slot takes any name at all.
PROVIDERS = {
    "ollama": {
        "display": "On this PC (Ollama)",
        "needs_key": False,
        "endpoint": None,
        "models": [],
    },
    "groq": {
        "display": "Groq",
        "needs_key": True,
        "endpoint": "https://api.groq.com/openai/v1/chat/completions",
        # R11: checked 2026-11-17 against Groq's own models page.
        # The Llama models shut down for free/developer tiers on
        # 2026-08-16 and are Enterprise-only now; the self-serve
        # production text models are the two GPT-OSS models.
        # qwen/qwen3.8-27b is deliberately NOT listed: it is a
        # preview model Groq may discontinue at short notice.
        "models": [
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
        ],
    },
    "gemini": {
        "display": "Gemini",
        "needs_key": True,
        "endpoint": (
            "https://generativelanguage.googleapis.com/v1beta/openai/"
            "chat/completions"
        ),
        # R12: checked 2026-11-17 against Google's models page.
        # gemini-2.0-flash is shut down; the 2.5 models are
        # deprecated and closed to new users (they auto-route
        # from 2026-12-01). Google names these two for new
        # projects, and both are free-tier. gemini-3.1-pro-preview
        # is deliberately NOT listed: it has zero free-tier quota.
        "models": [
            "gemini-3.8-flash",
            "gemini-3.5-flash-lite",
        ],
    },
    "custom": {
        "display": "Custom",
        "needs_key": True,
        "endpoint": None,  # the user supplies the base URL
        "models": [],
    },
}

KEYED_PROVIDERS = tuple(
    pid for pid, info in PROVIDERS.items() if info["needs_key"]
)


class ProviderError(Exception):
    """A provider call failed, in plain words for the user."""


# -- key storage ----------------------------------------------------


def providers_path(home: Path | str | None = None) -> Path:
    """Where the keys live: <home>/providers.json, mode 0600."""
    base = Path(home) if home is not None else default_home()
    return base / PROVIDERS_FILE


def load_providers(home: Path | str | None = None) -> dict:
    """The saved provider entries, or {} when none are saved.

    A missing or unreadable file is not an error: it just means no
    keys yet. A corrupt file is treated the same way, so a bad
    providers.json can never break the window; saving a key again
    replaces it.
    """
    path = providers_path(home)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_providers(path: Path, data: dict) -> None:
    """Atomic write, mode 0600 from the first byte: the temp file
    holds keys too, so it gets the tight mode before anything is
    written into it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(
            fd, (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")
        )
    finally:
        os.close(fd)
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)


def save_key(
    home: Path | str | None,
    provider_id: str,
    api_key: str,
    *,
    base_url: str = "",
    model: str = "",
) -> None:
    """Save a key (and, for custom, its base URL and model name)."""
    if provider_id not in KEYED_PROVIDERS:
        raise StellaError(f"no keyed provider called {provider_id!r}")
    key = (api_key or "").strip()
    if not key:
        raise StellaError("paste a key first")
    data = load_providers(home)
    entry: dict = {"api_key": key}
    if provider_id == "custom":
        entry["base_url"] = (base_url or "").strip().rstrip("/")
        entry["model"] = (model or "").strip()
    data[provider_id] = entry
    _write_providers(providers_path(home), data)


def remove_key(home: Path | str | None, provider_id: str) -> None:
    """Forget a saved key. No error when none was saved."""
    data = load_providers(home)
    if provider_id in data:
        del data[provider_id]
        _write_providers(providers_path(home), data)


def get_key(home: Path | str | None, provider_id: str) -> str:
    """The saved key for a provider, or "" when none is saved."""
    entry = load_providers(home).get(provider_id)
    if not isinstance(entry, dict):
        return ""
    key = entry.get("api_key")
    return key if isinstance(key, str) else ""


def has_key(home: Path | str | None, provider_id: str) -> bool:
    return bool(get_key(home, provider_id))


def get_custom_config(home: Path | str | None) -> dict:
    """The custom provider's saved base URL + model name (or {})."""
    entry = load_providers(home).get("custom")
    if not isinstance(entry, dict):
        return {}
    return {
        "base_url": entry.get("base_url") or "",
        "model": entry.get("model") or "",
    }


def provider_presence(home: Path | str | None = None) -> dict:
    """Key presence per provider, for debug reports. Values are
    status words only ("key saved" / "no key"): a key value never
    appears here."""
    return {
        pid: ("key saved" if has_key(home, pid) else "no key")
        for pid in KEYED_PROVIDERS
    }


def missing_key_message(provider_id: str) -> str:
    """Plain words for a provider whose key is not saved yet."""
    display = PROVIDERS.get(provider_id, {}).get("display", provider_id)
    return (
        f"No {display} key saved yet. Add it in Settings, under AI "
        "providers, then come back here."
    )


# -- chat clients ---------------------------------------------------


def _openai_chat(
    display: str,
    endpoint: str,
    api_key: str,
    model: str,
    messages: list[dict],
    *,
    timeout: float,
    max_tokens: int,
) -> str:
    """One OpenAI-compatible /chat/completions call. Returns the
    reply text, or raises ProviderError in plain words."""
    payload = json.dumps(
        {
            "model": model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": max_tokens,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            err = json.loads(exc.read().decode("utf-8")).get("error", "")
            if isinstance(err, dict):
                detail = err.get("message", "") or ""
            elif isinstance(err, str):
                detail = err
        except (ValueError, OSError):
            pass
        if exc.code == 401:
            raise ProviderError(
                "That key was rejected. Check it in Settings under "
                "AI providers and try again."
            ) from exc
        if exc.code == 429:
            raise ProviderError(
                f"{display} is busy (too many requests). Wait a bit "
                "and try again."
            ) from exc
        raise ProviderError(
            f"{display} said no (HTTP {exc.code})"
            + (f": {detail[:200]}" if detail else "")
        ) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ProviderError(
            f"Could not reach {display}. Check the network and "
            "try again."
        ) from exc
    except ValueError as exc:
        raise ProviderError(
            f"{display} answered with something unreadable."
        ) from exc
    text = None
    if isinstance(body, dict):
        choices = body.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(message, dict):
                text = message.get("content")
    if not isinstance(text, str) or not text.strip():
        raise ProviderError(f"{display} answered with no text.")
    return text


def chat(
    provider_id: str,
    model: str,
    messages: list[dict],
    home: Path | str | None = None,
    *,
    timeout: float = CHAT_TIMEOUT_SECONDS,
    max_tokens: int = 1024,
) -> str:
    """One chat call through a provider. Raises ProviderError (or
    OllamaError for the local provider) in plain words."""
    if provider_id == "ollama":
        return ollama_chat(model, messages, timeout=timeout)
    info = PROVIDERS.get(provider_id)
    if info is None:
        raise ProviderError(f"Unknown provider {provider_id!r}.")
    key = get_key(home, provider_id)
    if not key:
        raise ProviderError(missing_key_message(provider_id))
    if provider_id == "custom":
        config = get_custom_config(home)
        base_url = config.get("base_url", "")
        if not base_url:
            raise ProviderError(
                "Custom provider needs its address set. Add it in "
                "Settings under AI providers."
            )
        endpoint = base_url.rstrip("/") + "/chat/completions"
    else:
        endpoint = info["endpoint"]
    return _openai_chat(
        info["display"],
        endpoint,
        key,
        model,
        messages,
        timeout=timeout,
        max_tokens=max_tokens,
    )


def make_chat_fn(provider_id: str, home: Path | str | None = None):
    """A (model, messages) -> str chat function for the agent loop,
    bound to one provider. Never raises at build time: a missing
    key or an unknown provider surfaces as a plain-words
    ProviderError when the chat actually runs, and the agent turns
    that into a reply instead of a crash."""
    provider = provider_id or "ollama"

    def _fn(model: str, messages: list[dict]) -> str:
        return chat(provider, model, messages, home)

    return _fn


def test_connection(
    provider_id: str,
    model: str | None = None,
    home: Path | str | None = None,
) -> tuple[bool, str]:
    """One tiny call to check a provider works. Returns (ok, message)
    in plain words; never raises."""
    if provider_id == "ollama":
        models = list_models()
        if models:
            return True, f"Ollama is answering with {len(models)} model(s)."
        return False, "Ollama is not answering. Start Ollama and try again."
    info = PROVIDERS.get(provider_id)
    if info is None:
        return False, f"Unknown provider {provider_id!r}."
    if not has_key(home, provider_id):
        return False, missing_key_message(provider_id)
    if model is None:
        if provider_id == "custom":
            model = get_custom_config(home).get("model", "")
        elif info["models"]:
            model = info["models"][0]
    if not model:
        return False, (
            "Pick a model first. For Custom, set the model name in "
            "Settings under AI providers."
        )
    try:
        chat(
            provider_id,
            model,
            [{"role": "user", "content": "Say hi."}],
            home,
            timeout=TEST_TIMEOUT_SECONDS,
            max_tokens=16,
        )
    except (ProviderError, OllamaError) as exc:
        return False, str(exc)
    return True, f"{info['display']} answered. Your key works."
