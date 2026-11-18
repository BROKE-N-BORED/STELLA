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
import threading
import time
import urllib.error
import urllib.request

from .model import StellaError

DEFAULT_URL = "http://localhost:11434"
TIMEOUT_SECONDS = 2.0
CHAT_TIMEOUT_SECONDS = 120.0
GENERATE_TIMEOUT_SECONDS = 300.0


class OllamaError(Exception):
    """Ollama did not answer, or answered with something unusable."""


def ollama_url() -> str:
    return os.environ.get("STELLA_OLLAMA_URL", DEFAULT_URL).rstrip("/")


def _fetch_tags(url: str | None = None,
                timeout: float = TIMEOUT_SECONDS) -> tuple[list, bool]:
    """One /api/tags call. Returns (models, ok): models is the raw
    list of model dicts (possibly empty), ok is True when the
    server answered with a readable payload. A server that is up
    with no models installed answers ([], True) — that is
    different from down ([], False), and the cache needs the
    difference. Never raises."""
    base = (url or ollama_url()).rstrip("/")
    try:
        req = urllib.request.Request(base + "/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return [], False
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return [], False
    return models, True


def list_models(url: str | None = None, timeout: float = TIMEOUT_SECONDS) -> list[str]:
    """Return installed Ollama model tags, or [] if unreachable."""
    models, _ok = _fetch_tags(url, timeout)
    names = []
    for entry in models:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            names.append(entry["name"])
    return sorted(names)


def list_model_sizes(url: str | None = None,
                     timeout: float = TIMEOUT_SECONDS) -> dict[str, int]:
    """Installed Ollama model tags with their size in bytes, or {}
    if unreachable. Same /api/tags call as list_models — the size
    is what the model picker shows in its fit verdict (T18)."""
    models, _ok = _fetch_tags(url, timeout)
    sizes = {}
    for entry in models:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        size = entry.get("size")
        if isinstance(name, str) and isinstance(size, int):
            sizes[name] = size
    return sizes


class ModelListCache:
    """The installed-model list, cached (T43).

    One fetch feeds every combo fill and every tag check in the
    window: reads never touch the network, refreshes happen only
    on demand (startup, the Refresh button, the New Profile
    dialog opening). A refresh is one /api/tags call that yields
    both the names and the sizes. Thread-safe: refresh() runs on
    a worker thread while the UI thread reads the snapshot.

    Two races are closed here, not left to callers. Refreshes to
    the same URL racing each other make one fetch between them
    (the second waits for the first and takes its result);
    refreshes to different URLs fetch concurrently. And a stale
    refresh never overwrites a fresher one: each refresh takes a
    ticket when it starts, and only a refresh whose ticket is at
    least the newest completed one writes — so a slow fetch that
    lands after a fast one is discarded, not stored.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._models: list[str] = []
        self._sizes: dict[str, int] = {}
        self._loaded = False
        self._ollama_up = False
        self._fetched_at = 0.0
        self._in_flight: dict[str, threading.Event] = {}
        self._ticket = 0
        self._completed_ticket = 0

    def snapshot(self) -> tuple[list[str], dict[str, int], bool, bool, float]:
        """(models, sizes, loaded, ollama_up, fetched_at): the last
        good list, or the empty list when nothing was ever fetched.
        Never touches the network."""
        with self._lock:
            return (
                list(self._models),
                dict(self._sizes),
                self._loaded,
                self._ollama_up,
                self._fetched_at,
            )

    def models(self) -> list[str]:
        """The cached model tags, or [] when nothing was fetched."""
        with self._lock:
            return list(self._models)

    def sizes(self) -> dict[str, int]:
        """The cached model sizes, or {} when nothing was fetched."""
        with self._lock:
            return dict(self._sizes)

    @property
    def loaded(self) -> bool:
        """True once any refresh (or seed) has landed."""
        with self._lock:
            return self._loaded

    @property
    def ollama_up(self) -> bool:
        """True when the last refresh reached Ollama."""
        with self._lock:
            return self._ollama_up

    def refresh(self, url: str | None = None,
                timeout: float = TIMEOUT_SECONDS) -> tuple:
        """Fetch the list now and store it. Returns the snapshot.
        Always fetches (a refresh is a refresh) — except when
        another thread is already refreshing the same URL, in
        which case this waits for that fetch and returns its
        result. A refresh that lands after a newer one started is
        discarded (the ticket guard), never stored over it."""
        url = (url or ollama_url()).rstrip("/")
        with self._lock:
            self._ticket += 1
            ticket = self._ticket
            event = self._in_flight.get(url)
            if event is not None:
                in_flight = True
            else:
                event = threading.Event()
                self._in_flight[url] = event
                in_flight = False
        if in_flight:
            # Bounded wait: the in-flight fetch cannot outlast its
            # own timeout by much; a stale snapshot beats a hang.
            event.wait(timeout + 5)
            return self.snapshot()
        try:
            models, ok = _fetch_tags(url, timeout)
            names = sorted(
                entry["name"]
                for entry in models
                if isinstance(entry, dict)
                and isinstance(entry.get("name"), str)
            )
            sizes = {
                entry["name"]: entry["size"]
                for entry in models
                if isinstance(entry, dict)
                and isinstance(entry.get("name"), str)
                and isinstance(entry.get("size"), int)
            }
            with self._lock:
                if ticket >= self._completed_ticket:
                    self._models = names
                    self._sizes = sizes
                    self._loaded = True
                    self._ollama_up = ok
                    self._fetched_at = time.monotonic()
                    self._completed_ticket = ticket
        finally:
            with self._lock:
                if self._in_flight.get(url) is event:
                    del self._in_flight[url]
            event.set()
        return self.snapshot()

    def set_snapshot(self, models, sizes=None, ollama_up: bool = True):
        """Set the cached list outright. Tests seed the cache this
        way; refresh() sets it from a real fetch. The seed counts
        as the newest write, so a refresh that started before it
        cannot overwrite it when it lands."""
        with self._lock:
            self._models = list(models)
            self._sizes = dict(sizes or {})
            self._loaded = True
            self._ollama_up = ollama_up
            self._fetched_at = time.monotonic()
            self._completed_ticket = self._ticket

    def reset(self):
        """Drop the cached list (tests). A refresh that started
        before the reset cannot refill it when it lands."""
        with self._lock:
            self._models = []
            self._sizes = {}
            self._loaded = False
            self._ollama_up = False
            self._fetched_at = 0.0
            self._completed_ticket = self._ticket


# -- /api/show: what a profile points at (T165) ---------------------
# The same cache discipline as T43: the window never fetches on the
# UI thread and never fetches per click — one background refresh
# per tag, then every read serves from the cache.

# model_info keys that carry the context length, in the order to
# try them: the llama.cpp backends name it llama.context_length,
# older payloads shorten it. The first int found wins.
_SHOW_CONTEXT_KEYS = (
    "llama.context_length",
    "general.context_length",
    "context_length",
    "n_ctx",
)


def _fetch_show_payload(tag: str, url: str | None = None,
                        timeout: float = TIMEOUT_SECONDS) -> tuple:
    """One /api/show call. Returns (payload, ok): payload is the
    parsed body (or None), ok is True when the server answered
    with a readable payload. A server that answers 404 for an
    unknown tag is UP with no payload — ([], True)-style, like
    _fetch_tags — so the caller can tell "not installed" from
    "Ollama down". Never raises."""
    base = (url or ollama_url()).rstrip("/")
    body = json.dumps({"model": tag}).encode("utf-8")
    req = urllib.request.Request(
        base + "/api/show",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError:
        # The server answered: it is up, the tag is not installed
        # (or the request was bad). Either way there is no info.
        return None, True
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None, False
    if not isinstance(payload, dict):
        return None, False
    return payload, True


def parse_show_info(payload: dict | None) -> dict | None:
    """An /api/show payload as the plain fields the profile panel
    shows: size_bytes, quant, context (tokens), capabilities,
    parameter_size, family. None when there is no payload to read.
    Every field is defensive: a missing or wrong-typed value reads
    as empty, never a crash — Ollama's payload shape varies by
    backend and version."""
    if not isinstance(payload, dict):
        return None
    details = payload.get("details")
    if not isinstance(details, dict):
        details = {}
    model_info = payload.get("model_info")
    if not isinstance(model_info, dict):
        model_info = {}
    size = payload.get("size")
    context = None
    for key in _SHOW_CONTEXT_KEYS:
        value = model_info.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            context = value
            break
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, list):
        capabilities = []
    capabilities = [c for c in capabilities if isinstance(c, str)]
    parameter_size = details.get("parameter_size")
    family = details.get("family")
    return {
        "size_bytes": size if isinstance(size, int) else None,
        "quant": (
            details.get("quantization_level")
            if isinstance(details.get("quantization_level"), str)
            else ""
        ),
        "context": context,
        "capabilities": capabilities,
        "parameter_size": (
            parameter_size if isinstance(parameter_size, str) else ""
        ),
        "family": family if isinstance(family, str) else "",
    }


def fetch_show(tag: str, url: str | None = None,
               timeout: float = TIMEOUT_SECONDS) -> dict | None:
    """One /api/show call, parsed — or None when Ollama is down,
    the tag is not installed, or the payload is unreadable.
    Never raises."""
    payload, _ok = _fetch_show_payload(tag, url, timeout)
    return parse_show_info(payload)


class ModelShowCache:
    """Per-tag /api/show results, cached (T165).

    Same discipline as ModelListCache: reads never touch the
    network, refreshes happen only on demand (a profile window
    opening, the model-list Refresh landing), on a worker thread.
    One entry per tag: the parsed info (or None when the fetch
    found nothing), whether Ollama was up for it, and when it
    was fetched. Refreshes of the same tag racing each other
    make one fetch between them; different tags fetch
    concurrently.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._entries: dict[str, dict] = {}
        self._in_flight: dict[str, threading.Event] = {}

    def info(self, tag: str) -> dict | None:
        """The cached info for a tag, or None when nothing was
        ever fetched for it (or the fetch found nothing). Never
        touches the network."""
        with self._lock:
            entry = self._entries.get(tag)
            return dict(entry["info"]) if entry and entry["info"] else None

    def loaded(self, tag: str) -> bool:
        """True once any refresh (or seed) has landed for this tag."""
        with self._lock:
            return tag in self._entries

    def ollama_up(self, tag: str) -> bool:
        """True when the last refresh for this tag reached Ollama.
        False when nothing was ever fetched — the window shows
        "not loaded yet" then, not "down"."""
        with self._lock:
            entry = self._entries.get(tag)
            return bool(entry and entry["ollama_up"])

    def refresh(self, tag: str, url: str | None = None,
                timeout: float = TIMEOUT_SECONDS) -> tuple:
        """Fetch the info for one tag now and store it. Returns
        (info, ollama_up): info is the parsed dict, or None when
        the fetch found nothing. A refresh that finds another
        thread already fetching the same tag waits for it and
        returns its result."""
        url = (url or ollama_url()).rstrip("/")
        key = f"{url}\n{tag}"
        with self._lock:
            event = self._in_flight.get(key)
            if event is not None:
                in_flight = True
            else:
                event = threading.Event()
                self._in_flight[key] = event
                in_flight = False
        if in_flight:
            event.wait(timeout + 5)
            with self._lock:
                entry = self._entries.get(tag)
            if entry is None:
                return None, False
            return entry["info"], entry["ollama_up"]
        try:
            payload, ok = _fetch_show_payload(tag, url, timeout)
            info = parse_show_info(payload)
            with self._lock:
                self._entries[tag] = {
                    "info": info,
                    "ollama_up": ok,
                    "fetched_at": time.monotonic(),
                }
        finally:
            with self._lock:
                if self._in_flight.get(key) is event:
                    del self._in_flight[key]
            event.set()
        return info, ok

    def set_snapshot(self, tag: str, info, ollama_up: bool = True):
        """Set the cached info for one tag outright. Tests seed
        the cache this way; refresh() sets it from a real fetch."""
        with self._lock:
            self._entries[tag] = {
                "info": dict(info) if info is not None else None,
                "ollama_up": ollama_up,
                "fetched_at": time.monotonic(),
            }

    def reset(self, tag: str | None = None):
        """Drop the cached info — one tag, or all of it (tests)."""
        with self._lock:
            if tag is None:
                self._entries.clear()
            else:
                self._entries.pop(tag, None)


# The one show cache the window reads (T165): every profile panel
# serves from here, and only a refresh ever fetches.
SHOW_CACHE = ModelShowCache()


# The one cache the window reads (T43): every combo fill and tag
# check serves from here, and only a refresh ever fetches.
MODEL_CACHE = ModelListCache()


def reachable(url: str | None = None, timeout: float = TIMEOUT_SECONDS) -> bool:
    """True when the Ollama server answers on localhost."""
    base = (url or ollama_url()).rstrip("/")
    try:
        req = urllib.request.Request(base + "/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def generate_full(
    model: str,
    prompt: str,
    url: str | None = None,
    timeout: float = GENERATE_TIMEOUT_SECONDS,
    *,
    num_predict: int = 1024,
    temperature: float = 0.7,
    keep_alive: str | None = None,
) -> dict:
    """One /api/generate call, no streaming, with the full result.

    Returns {"text", "done_reason"}: the reply text plus Ollama's
    done_reason ("stop", "length", ...). R35: the old `generate`
    discarded everything but the text, so a teacher answer cut off
    at the token cap (done_reason "length") was saved as a full
    answer with no marker. Callers that must know whether the
    answer finished use this; callers that only need the text use
    `generate`, which calls this and returns the text. Same
    failures, same plain-words errors as `generate`.
    """
    base = (url or ollama_url()).rstrip("/")
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
        },
    }
    if keep_alive is not None:
        body["keep_alive"] = keep_alive
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        base + "/api/generate",
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
            detail = exc.read().decode("utf-8", "replace")
        except OSError:
            pass
        if "not found" in detail.lower() or "does not exist" in detail.lower():
            raise StellaError(
                f"Ollama does not have a model called {model!r}. "
                "Check the tag, or pull the model first."
            ) from exc
        raise StellaError(
            f"Ollama could not answer (HTTP {exc.code}). "
            "Is the model still loading? Try again in a minute."
        ) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        # R80: no raw exception text in the user-facing message —
        # the sentence already says what to do. The raw error
        # stays on the exception chain (from exc) for debugging.
        raise StellaError(
            "Ollama did not answer. Is Ollama running on this PC?"
        ) from exc
    except ValueError as exc:
        raise StellaError(
            "Ollama answered with something Stella could not read. "
            "Try again."
        ) from exc
    text = body.get("response") if isinstance(body, dict) else None
    if not isinstance(text, str):
        raise StellaError("Ollama answered but gave no text. Try again.")
    done_reason = body.get("done_reason") if isinstance(body, dict) else None
    return {
        "text": text,
        "done_reason": done_reason if isinstance(done_reason, str) else None,
    }


def generate(
    model: str,
    prompt: str,
    url: str | None = None,
    timeout: float = GENERATE_TIMEOUT_SECONDS,
    *,
    num_predict: int = 1024,
    temperature: float = 0.7,
    keep_alive: str | None = None,
) -> str:
    """One /api/generate call, no streaming. Returns the reply text.

    Raises StellaError in plain words on any failure: Ollama down,
    the model not installed, or a reply with no text. The default
    timeout is generous on purpose: a local CPU model answers slowly.
    `keep_alive` (S4) is Ollama's keep-alive for the model, e.g.
    "30m": how long the model stays loaded after this call. When
    set it goes into the payload; when absent no keep_alive key is
    sent at all, so existing callers are unaffected.
    """
    return generate_full(
        model, prompt, url=url, timeout=timeout,
        num_predict=num_predict, temperature=temperature,
        keep_alive=keep_alive,
    )["text"]


def chat_stream(
    model: str,
    messages: list[dict],
    *,
    url: str | None = None,
    timeout: float = CHAT_TIMEOUT_SECONDS,
    on_token=None,
) -> str:
    """One /api/chat call with streaming (T76, entry 010).

    Calls on_token(chunk) for each piece of the reply as it
    arrives, and returns the full reply text. Same failure
    behavior as chat: OllamaError in plain words.
    """
    base = (url or ollama_url()).rstrip("/")
    payload = json.dumps(
        {
            "model": model,
            "messages": messages,
            "stream": True,
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
            parts: list[str] = []
            for raw_line in resp:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line.decode("utf-8"))
                except ValueError:
                    continue
                message = obj.get("message") if isinstance(obj, dict) else None
                content = (
                    message.get("content")
                    if isinstance(message, dict)
                    else None
                )
                if isinstance(content, str) and content:
                    parts.append(content)
                    if on_token is not None:
                        on_token(content)
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
    text = "".join(parts)
    if not text.strip():
        raise OllamaError("Ollama answered with no text.")
    return text


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
