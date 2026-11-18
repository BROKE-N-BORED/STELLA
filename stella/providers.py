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
from datetime import date
from pathlib import Path

from .model import StellaError, default_home
from .ollama import (
    OllamaError,
    chat as ollama_chat,
    chat_stream as ollama_chat_stream,
    list_models,
)

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
        # R51: when this list was last checked against Groq's own
        # models page. See MODEL_LIST_STALE_AFTER_DAYS below.
        "checked": "2026-11-17",
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
        # R51: when this list was last checked against Google's
        # models page. See MODEL_LIST_STALE_AFTER_DAYS below.
        "checked": "2026-11-17",
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

# The providers with a curated list (R51): Ollama is live from
# the daemon, never curated, and Custom is the user's own model
# name — neither can rot.
CURATED_PROVIDERS = ("groq", "gemini")

# How old a curated list may get before Stella says so (R51).
# 90 days: long enough not to nag about lists that have not
# changed, short enough that the next deprecation is noticed
# within a season. The check is local — a date comparison, no
# network call: the product is offline-first, and any online
# check against a provider's model endpoint needs his say-so
# first. Each release re-checks the lists and moves the dates.
MODEL_LIST_STALE_AFTER_DAYS = 90


def list_checked_date(provider_id: str) -> date | None:
    """When the curated model list was last checked (R51), or None
    when the provider has no curated list or no check date."""
    checked = PROVIDERS.get(provider_id, {}).get("checked")
    if not isinstance(checked, str):
        return None
    try:
        return date.fromisoformat(checked)
    except ValueError:
        return None


def list_stale(provider_id: str, today: date | None = None) -> bool:
    """True when a curated list is older than the threshold (R51).
    Uncurated providers are never stale. A curated list with no
    check date counts as stale — never checked is worse than
    checked long ago, and must be noticed, not silent."""
    if provider_id not in CURATED_PROVIDERS:
        return False
    checked = list_checked_date(provider_id)
    if checked is None:
        return True
    day = today or date.today()
    return (day - checked).days > MODEL_LIST_STALE_AFTER_DAYS


def stale_list_notes(today: date | None = None) -> list[str]:
    """One plain-words note per stale curated list (R51), or [].
    The note names the check date and the next step — it never
    sends the user to a terminal."""
    notes = []
    for pid in CURATED_PROVIDERS:
        if not list_stale(pid, today):
            continue
        display = PROVIDERS[pid]["display"]
        checked = list_checked_date(pid)
        if checked is None:
            notes.append(
                f"The list of {display} models has no check date, "
                "so it may be out of date. If a model fails, try "
                "another one."
            )
        else:
            notes.append(
                f"The list of {display} models was last checked on "
                f"{checked.isoformat()}, over "
                f"{MODEL_LIST_STALE_AFTER_DAYS} days ago, so a model "
                "here may have changed. If one fails, try another one."
            )
    return notes


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
    replaces it. Callers that need to tell corrupt from missing
    use providers_corrupt (R105) — this function deliberately
    cannot tell them apart.
    """
    path = providers_path(home)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


# R105: what a damaged providers.json says, everywhere it is
# reported (the Settings panel, the chat path, the Test button).
# Plain words, and it names the reset — never "no keys", which
# would send the user to re-save keys that are still in the file.
CORRUPT_PROVIDERS_MESSAGE = (
    "Your saved provider keys file is damaged, so Stella cannot "
    "read your keys. Reset it in Settings under AI providers "
    "(the damaged file is kept as a backup), then save your keys "
    "again."
)


def providers_corrupt(home: Path | str | None = None) -> bool:
    """True when providers.json exists but cannot be read as the
    object of saved keys (R105): bad JSON, or valid JSON that is
    not an object. A missing file is not corrupt — it just means
    no keys yet. Never raises: an unreadable file counts as
    corrupt, since Stella cannot read the keys either way."""
    path = providers_path(home)
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return True
    return not isinstance(data, dict)


def _backup_corrupt_file(path: Path) -> Path | None:
    """Copy a corrupt providers file aside before it is replaced
    (R105): providers.json.corrupt, numbered when one already
    exists. Returns the backup path, or None when there was
    nothing to back up. The bytes are copied, never parsed — the
    file is corrupt, so parsing is what failed."""
    if not path.is_file():
        return None
    backup = path.with_name(path.name + ".corrupt")
    if backup.exists():
        n = 1
        while path.with_name(f"{path.name}.corrupt.{n}").exists():
            n += 1
        backup = path.with_name(f"{path.name}.corrupt.{n}")
    try:
        backup.write_bytes(path.read_bytes())
        os.chmod(backup, 0o600)
    except OSError:
        return None
    return backup


def reset_corrupt_providers(home: Path | str | None = None) -> Path | None:
    """Reset a corrupt providers file (R105): the damaged file is
    backed up first (providers.json.corrupt), then removed, so
    saving a key again starts clean. Returns the backup path, or
    None when the file was not corrupt (nothing was done). Never
    goes through the load-then-save path: loading a corrupt file
    reads as {} and saving over it would silently drop the other
    keys without keeping the bytes."""
    path = providers_path(home)
    if not providers_corrupt(home):
        return None
    backup = _backup_corrupt_file(path)
    try:
        path.unlink()
    except OSError:
        return None
    return backup


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
    # R105: a corrupt file reads as {} below, so saving one key
    # would replace it and silently drop the other keys' bytes.
    # Back it up first — the reset path is not the only writer.
    if providers_corrupt(home):
        _backup_corrupt_file(providers_path(home))
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
    # R54: the CLI way is named alongside Settings, so a
    # terminal user is not sent to a window that is not in front
    # of them — and a window user still sees Settings first.
    return (
        f"No {display} key saved yet. Add it in Settings, under AI "
        f"providers, or run: stella save-key {provider_id}."
    )


# -- chat clients ---------------------------------------------------


def _extract_usage(body: dict) -> dict:
    """The token counts from a chat response body (R106): prompt,
    completion, and total tokens, only the ones present and whole
    numbers. {} when the provider reported nothing — a missing
    usage block is not an error, it just means no count to show."""
    usage = body.get("usage") if isinstance(body, dict) else None
    if not isinstance(usage, dict):
        return {}
    counts = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            counts[key] = value
    return counts


def _openai_chat_full(
    display: str,
    endpoint: str,
    api_key: str,
    model: str,
    messages: list[dict],
    *,
    timeout: float,
    max_tokens: int,
) -> tuple[str, dict]:
    """One OpenAI-compatible /chat/completions call. Returns the
    reply text and the token counts (R106), or raises ProviderError
    in plain words."""
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
    return text, _extract_usage(body if isinstance(body, dict) else {})


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
    reply text, or raises ProviderError in plain words. The
    token counts are dropped here; chat_with_usage keeps them."""
    return _openai_chat_full(
        display, endpoint, api_key, model, messages,
        timeout=timeout, max_tokens=max_tokens,
    )[0]


def _openai_chat_stream(
    display: str,
    endpoint: str,
    api_key: str,
    model: str,
    messages: list[dict],
    *,
    timeout: float,
    max_tokens: int,
    on_token=None,
    include_usage: bool = True,
) -> tuple[str, dict]:
    """One streaming OpenAI-compatible /chat/completions call
    (R104). The reply arrives as server-sent events: each `data:`
    line holds one JSON chunk with a `choices[0].delta.content`
    piece, and `data: [DONE]` ends the stream. Calls on_token for
    each piece as it arrives (the same shape as Ollama's
    chat_stream, so the agent's streaming bookkeeping sees cloud
    chunks exactly as Ollama ones) and returns the full text plus
    the token counts (R106 — the final chunk carries `usage` when
    include_usage was asked for). A line that is not JSON yet
    (a chunk split mid-line) is skipped, never fatal. Raises
    ProviderError in plain words."""
    payload: dict = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if include_usage:
        payload["stream_options"] = {"include_usage": True}
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            parts: list[str] = []
            usage: dict = {}
            for raw_line in resp:
                line = raw_line.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    if data == "[DONE]":
                        break
                    continue
                try:
                    chunk = json.loads(data)
                except ValueError:
                    # A partial JSON line (a chunk split mid-line):
                    # skip it, the rest of the stream still counts.
                    continue
                if not isinstance(chunk, dict):
                    continue
                chunk_usage = _extract_usage(chunk)
                if chunk_usage:
                    usage = chunk_usage
                choices = chunk.get("choices")
                if not isinstance(choices, list) or not choices:
                    continue
                first = choices[0]
                if not isinstance(first, dict):
                    continue
                delta = first.get("delta")
                content = (
                    delta.get("content")
                    if isinstance(delta, dict)
                    else None
                )
                if isinstance(content, str) and content:
                    parts.append(content)
                    if on_token is not None:
                        on_token(content)
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
    text = "".join(parts)
    if not text.strip():
        raise ProviderError(f"{display} answered with no text.")
    return text, usage


def _resolve_cloud(
    provider_id: str, home: Path | str | None
) -> tuple[str, str, str]:
    """(display name, chat endpoint, key) for a cloud provider.
    Raises ProviderError in plain words for an unknown provider,
    a missing key, or a custom slot with no address. A damaged
    providers.json (R105) says so instead of reading as no keys:
    the keys may still be in the file, and "no key saved yet"
    would send the user to re-save them."""
    info = PROVIDERS.get(provider_id)
    if info is None:
        raise ProviderError(f"Unknown provider {provider_id!r}.")
    key = get_key(home, provider_id)
    if not key:
        if providers_corrupt(home):
            raise ProviderError(CORRUPT_PROVIDERS_MESSAGE)
        raise ProviderError(missing_key_message(provider_id))
    if provider_id == "custom":
        config = get_custom_config(home)
        base_url = config.get("base_url", "")
        if not base_url:
            raise ProviderError(
                "Custom provider needs its address set. Add it in "
                "Settings under AI providers."
            )
        # R101: a pasted full endpoint URL ends in /chat/completions
        # already — strip it before appending, or the path doubles
        # and the call fails. Only the exact trailing segment is
        # stripped (a base URL that merely contains the string
        # earlier in the path is left alone); stripping repeats so
        # an already-doubled paste is fixed too.
        base = base_url.rstrip("/")
        while base.endswith("/chat/completions"):
            base = base[: -len("/chat/completions")]
        endpoint = base + "/chat/completions"
    else:
        endpoint = info["endpoint"]
    return info["display"], endpoint, key


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
    display, endpoint, key = _resolve_cloud(provider_id, home)
    return _openai_chat(
        display,
        endpoint,
        key,
        model,
        messages,
        timeout=timeout,
        max_tokens=max_tokens,
    )


def chat_with_usage(
    provider_id: str,
    model: str,
    messages: list[dict],
    home: Path | str | None = None,
    *,
    timeout: float = CHAT_TIMEOUT_SECONDS,
    max_tokens: int = 1024,
) -> tuple[str, dict]:
    """One chat call through a provider, plus the token counts
    (R106): (reply text, {"prompt_tokens", "completion_tokens",
    "total_tokens"} — only the counts the provider reported).
    Ollama reports no counts here, so its usage is {}."""
    if provider_id == "ollama":
        return ollama_chat(model, messages, timeout=timeout), {}
    display, endpoint, key = _resolve_cloud(provider_id, home)
    return _openai_chat_full(
        display,
        endpoint,
        key,
        model,
        messages,
        timeout=timeout,
        max_tokens=max_tokens,
    )


def chat_stream_with_usage(
    provider_id: str,
    model: str,
    messages: list[dict],
    home: Path | str | None = None,
    *,
    on_token=None,
    timeout: float = CHAT_TIMEOUT_SECONDS,
    max_tokens: int = 1024,
) -> tuple[str, dict]:
    """One streaming chat call through a provider (R104): calls
    on_token for each piece as it arrives and returns the full
    text plus the token counts (R106). Ollama streams through
    its own client; cloud providers stream SSE. Raises
    ProviderError (or OllamaError) in plain words."""
    if provider_id == "ollama":
        return (
            ollama_chat_stream(
                model, messages, timeout=timeout, on_token=on_token
            ),
            {},
        )
    display, endpoint, key = _resolve_cloud(provider_id, home)
    # Gemini's OpenAI-compatible endpoint does not document
    # stream_options, so it is not sent there: a rejected call
    # would be worse than a missing count, and the non-streaming
    # call still reports Gemini's usage.
    return _openai_chat_stream(
        display,
        endpoint,
        key,
        model,
        messages,
        timeout=timeout,
        max_tokens=max_tokens,
        on_token=on_token,
        include_usage=provider_id != "gemini",
    )


def chat_stream(
    provider_id: str,
    model: str,
    messages: list[dict],
    home: Path | str | None = None,
    *,
    on_token=None,
    timeout: float = CHAT_TIMEOUT_SECONDS,
    max_tokens: int = 1024,
) -> str:
    """One streaming chat call through a provider (R104). Calls
    on_token for each piece as it arrives and returns the full
    reply text. The token counts are dropped here;
    chat_stream_with_usage keeps them."""
    return chat_stream_with_usage(
        provider_id, model, messages, home,
        on_token=on_token, timeout=timeout, max_tokens=max_tokens,
    )[0]


def make_chat_fn(provider_id: str, home: Path | str | None = None):
    """A (model, messages) -> str chat function for the agent loop,
    bound to one provider. Never raises at build time: a missing
    key or an unknown provider surfaces as a plain-words
    ProviderError when the chat actually runs, and the agent turns
    that into a reply instead of a crash. After each call the
    function carries `last_usage`: the token counts from that call
    (R106), {} when the provider reported none."""
    provider = provider_id or "ollama"

    def _fn(model: str, messages: list[dict]) -> str:
        text, usage = chat_with_usage(provider, model, messages, home)
        _fn.last_usage = usage
        return text

    _fn.last_usage = {}
    return _fn


def make_chat_stream_fn(provider_id: str, home: Path | str | None = None):
    """A (model, messages, on_token=None) -> str streaming chat
    function for the agent loop (R104), bound to one provider —
    the cloud twin of Ollama's chat_stream, with the same call
    shape, so the agent's streaming bookkeeping sees cloud chunks
    exactly as Ollama ones. After each call the function carries
    `last_usage`: the token counts from that call (R106)."""
    provider = provider_id or "ollama"

    def _sfn(model: str, messages: list[dict], on_token=None) -> str:
        text, usage = chat_stream_with_usage(
            provider, model, messages, home, on_token=on_token
        )
        _sfn.last_usage = usage
        return text

    _sfn.last_usage = {}
    return _sfn


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
    # R105: a damaged file reads as no keys — say it is damaged
    # instead of sending the user to re-save keys still in it.
    if providers_corrupt(home):
        return False, CORRUPT_PROVIDERS_MESSAGE
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
