"""Provider tests: key storage, cloud chat clients, the agent on a
cloud provider, and the guarantees that keys never leak into debug
reports or exports. No real provider API is ever called and no real
key is used: the HTTP layer is faked and the only key value in this
file is the obviously-fake "test-key-123"."""
import io
import json
import os
import stat
import urllib.error

import pytest

import stella.providers as providers_mod
from stella.chat_agent import ChatAgent
from stella.debug_log import DebugLogger, scrub_dict, scrub_text
from stella.model import StellaError
from stella.providers import (
    PROVIDERS,
    ProviderError,
    chat,
    get_custom_config,
    get_key,
    has_key,
    load_providers,
    make_chat_fn,
    missing_key_message,
    provider_presence,
    providers_path,
    remove_key,
    save_key,
)

FAKE_KEY = "test-key-123"


class FakeResponse:
    """A stand-in for a urllib response: JSON body, context manager."""

    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _chat_payload(text="Hello back."):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


def _fake_urlopen_factory(seen, payload=None, error=None):
    """urlopen fake: records the Request, then answers or raises."""
    def _fake(request, timeout=None):
        seen.append(request)
        if error is not None:
            raise error
        return FakeResponse(payload if payload is not None else _chat_payload())
    return _fake


def _http_error(code, message="bad key"):
    body = io.BytesIO(
        json.dumps({"error": {"message": message}}).encode("utf-8")
    )
    return urllib.error.HTTPError(
        "https://example.invalid/", code, "error", {}, body
    )


# -- key storage ----------------------------------------------------


def test_key_storage_round_trip_and_mode_0600(home):
    save_key(home, "groq", FAKE_KEY)
    path = providers_path(home)
    assert path.is_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert get_key(home, "groq") == FAKE_KEY
    assert has_key(home, "groq")
    assert not has_key(home, "gemini")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"groq": {"api_key": FAKE_KEY}}


def test_save_key_strips_whitespace_and_replaces(home):
    save_key(home, "gemini", "  " + FAKE_KEY + "  ")
    assert get_key(home, "gemini") == FAKE_KEY
    save_key(home, "gemini", "test-key-456")
    assert get_key(home, "gemini") == "test-key-456"


def test_save_key_rejects_empty_and_unknown(home):
    with pytest.raises(StellaError):
        save_key(home, "groq", "   ")
    with pytest.raises(StellaError):
        save_key(home, "ollama", FAKE_KEY)
    with pytest.raises(StellaError):
        save_key(home, "not-a-provider", FAKE_KEY)


def test_remove_key_forgets(home):
    save_key(home, "groq", FAKE_KEY)
    remove_key(home, "groq")
    assert not has_key(home, "groq")
    assert load_providers(home) == {}
    remove_key(home, "groq")  # removing twice is fine


def test_load_providers_missing_or_corrupt_is_empty(home):
    assert load_providers(home) == {}
    providers_path(home).parent.mkdir(parents=True, exist_ok=True)
    providers_path(home).write_text("{not json", encoding="utf-8")
    assert load_providers(home) == {}
    providers_path(home).write_text("[1, 2]", encoding="utf-8")
    assert load_providers(home) == {}


def test_custom_config_round_trip(home):
    save_key(
        home, "custom", FAKE_KEY,
        base_url="https://example.com/v1/", model="my-model",
    )
    assert get_custom_config(home) == {
        "base_url": "https://example.com/v1",
        "model": "my-model",
    }
    assert get_key(home, "custom") == FAKE_KEY


def test_provider_presence_never_holds_a_key(home):
    save_key(home, "groq", FAKE_KEY)
    presence = provider_presence(home)
    assert presence["groq"] == "key saved"
    assert presence["gemini"] == "no key"
    assert FAKE_KEY not in json.dumps(presence)


def test_gitignore_covers_providers_json():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    ignored = (root / ".gitignore").read_text(encoding="utf-8")
    assert "providers.json" in ignored


# -- chat clients ---------------------------------------------------


def _request_body(request):
    return json.loads(request.data.decode("utf-8"))


def test_groq_chat_request_shape(home, monkeypatch):
    save_key(home, "groq", FAKE_KEY)
    seen = []
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen_factory(seen, _chat_payload("Hi from Groq.")),
    )
    text = chat(
        "groq", "openai/gpt-oss-120b",
        [{"role": "user", "content": "Say hi."}], home,
    )
    assert text == "Hi from Groq."
    assert len(seen) == 1
    req = seen[0]
    assert req.full_url == PROVIDERS["groq"]["endpoint"]
    assert req.get_header("Authorization") == f"Bearer {FAKE_KEY}"
    assert req.get_header("Content-type") == "application/json"
    body = _request_body(req)
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["messages"] == [{"role": "user", "content": "Say hi."}]
    assert body["temperature"] == 0.3


def test_gemini_chat_uses_bearer_and_openai_endpoint(home, monkeypatch):
    save_key(home, "gemini", FAKE_KEY)
    seen = []
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen_factory(seen, _chat_payload("Hi from Gemini.")),
    )
    text = chat(
        "gemini", "gemini-3.8-flash",
        [{"role": "user", "content": "Say hi."}], home,
    )
    assert text == "Hi from Gemini."
    req = seen[0]
    assert req.full_url == PROVIDERS["gemini"]["endpoint"]
    assert "generativelanguage.googleapis.com" in req.full_url
    assert "/openai/chat/completions" in req.full_url
    assert req.get_header("Authorization") == f"Bearer {FAKE_KEY}"


def test_custom_chat_uses_saved_base_url(home, monkeypatch):
    save_key(
        home, "custom", FAKE_KEY,
        base_url="https://example.com/v1", model="my-model",
    )
    seen = []
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen_factory(seen, _chat_payload("Hi from custom.")),
    )
    text = chat(
        "custom", "my-model",
        [{"role": "user", "content": "Say hi."}], home,
    )
    assert text == "Hi from custom."
    assert seen[0].full_url == "https://example.com/v1/chat/completions"


def test_chat_missing_key_is_plain_words(home):
    with pytest.raises(ProviderError) as exc:
        chat(
            "groq", "openai/gpt-oss-120b",
            [{"role": "user", "content": "hi"}], home,
        )
    assert "No Groq key saved yet" in str(exc.value)
    assert "Settings" in str(exc.value)


def test_chat_custom_without_address_is_plain_words(home):
    save_key(home, "custom", FAKE_KEY)
    with pytest.raises(ProviderError) as exc:
        chat(
            "custom", "my-model",
            [{"role": "user", "content": "hi"}], home,
        )
    assert "address" in str(exc.value)


def test_chat_unknown_provider_is_plain_words(home):
    with pytest.raises(ProviderError):
        chat(
            "nope", "model",
            [{"role": "user", "content": "hi"}], home,
        )


def test_chat_401_says_the_key_was_rejected(home, monkeypatch):
    save_key(home, "groq", FAKE_KEY)
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen_factory([], error=_http_error(401)),
    )
    with pytest.raises(ProviderError) as exc:
        chat(
            "groq", "openai/gpt-oss-120b",
            [{"role": "user", "content": "hi"}], home,
        )
    assert "key was rejected" in str(exc.value)


def test_chat_429_says_busy(home, monkeypatch):
    save_key(home, "groq", FAKE_KEY)
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen_factory([], error=_http_error(429, "slow down")),
    )
    with pytest.raises(ProviderError) as exc:
        chat(
            "groq", "openai/gpt-oss-120b",
            [{"role": "user", "content": "hi"}], home,
        )
    assert "busy" in str(exc.value)


def test_chat_network_failure_is_plain_words(home, monkeypatch):
    save_key(home, "gemini", FAKE_KEY)
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen_factory(
            [], error=urllib.error.URLError("no route"),
        ),
    )
    with pytest.raises(ProviderError) as exc:
        chat(
            "gemini", "gemini-3.8-flash",
            [{"role": "user", "content": "hi"}], home,
        )
    assert "Could not reach Gemini" in str(exc.value)


def test_chat_empty_reply_is_plain_words(home, monkeypatch):
    save_key(home, "groq", FAKE_KEY)
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen_factory([], {"choices": []}),
    )
    with pytest.raises(ProviderError) as exc:
        chat(
            "groq", "openai/gpt-oss-120b",
            [{"role": "user", "content": "hi"}], home,
        )
    assert "no text" in str(exc.value)


def test_make_chat_fn_missing_key_raises_only_when_called(home):
    fn = make_chat_fn("groq", home)
    with pytest.raises(ProviderError) as exc:
        fn("openai/gpt-oss-120b", [{"role": "user", "content": "hi"}])
    assert "No Groq key saved yet" in str(exc.value)


# -- test_connection ------------------------------------------------


def test_test_connection_ok_and_failure(home, monkeypatch):
    save_key(home, "groq", FAKE_KEY)
    seen = []
    monkeypatch.setattr(
        "urllib.request.urlopen", _fake_urlopen_factory(seen)
    )
    ok, message = providers_mod.test_connection("groq", home=home)
    assert ok is True
    assert "Your key works" in message
    body = _request_body(seen[0])
    assert body["max_tokens"] == 16
    assert body["messages"] == [{"role": "user", "content": "Say hi."}]


def test_test_connection_no_key(home):
    ok, message = providers_mod.test_connection("gemini", home=home)
    assert ok is False
    assert "No Gemini key saved yet" in message


def test_test_connection_rejected_key(home, monkeypatch):
    save_key(home, "gemini", FAKE_KEY)
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen_factory([], error=_http_error(401)),
    )
    ok, message = providers_mod.test_connection("gemini", home=home)
    assert ok is False
    assert "key was rejected" in message


def test_test_connection_ollama(monkeypatch):
    monkeypatch.setattr(
        providers_mod, "list_models", lambda: ["lfm3:1.7b"]
    )
    ok, _message = providers_mod.test_connection("ollama")
    assert ok is True
    monkeypatch.setattr(providers_mod, "list_models", lambda: [])
    ok, message = providers_mod.test_connection("ollama")
    assert ok is False
    assert "not answering" in message


def test_test_connection_custom_needs_a_model(home):
    save_key(home, "custom", FAKE_KEY, base_url="https://example.com/v1")
    ok, message = providers_mod.test_connection("custom", home=home)
    assert ok is False
    assert "model" in message.lower()


# -- R11/R12: the curated lists hold models that work ----------------


def test_curated_model_lists_are_current():
    """R11/R12, checked 2026-11-17 against the providers' own
    pages: Groq self-serve is the two GPT-OSS production models
    (the Llamas are Enterprise-only since 2026-08-16); Gemini
    for a new key is 3.8-flash + 3.5-flash-lite (2.0-flash shut
    down, 2.5 deprecated and closed to new users). The dead IDs
    must not creep back, and neither may the two traps:
    qwen/qwen3.8-27b (preview, may be discontinued) and
    gemini-3.1-pro-preview (zero free-tier quota)."""
    assert PROVIDERS["groq"]["models"] == [
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
    ]
    assert PROVIDERS["gemini"]["models"] == [
        "gemini-3.8-flash",
        "gemini-3.5-flash-lite",
    ]
    dead = {
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "gemini-2.0-flash",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "qwen/qwen3.8-27b",
        "gemini-3.1-pro-preview",
    }
    for provider in ("groq", "gemini"):
        assert not (set(PROVIDERS[provider]["models"]) & dead)


def test_test_connection_uses_the_working_default(home, monkeypatch):
    """R11/R12: with no model picked, Test connection calls the
    first curated model — which must be one that works for an
    ordinary key. Proven against the fake server: the request
    body carries the new default, not a dead Llama or 2.5 ID."""
    for provider, default in (
        ("groq", "openai/gpt-oss-120b"),
        ("gemini", "gemini-3.8-flash"),
    ):
        save_key(home, provider, FAKE_KEY)
        seen = []
        monkeypatch.setattr(
            "urllib.request.urlopen", _fake_urlopen_factory(seen)
        )
        ok, _message = providers_mod.test_connection(provider, home=home)
        assert ok is True
        assert _request_body(seen[0])["model"] == default


# -- the agent on a cloud provider ----------------------------------


def test_agent_missing_key_reply_is_plain_words(store, monkeypatch):
    """No key saved: the agent answers in plain words and never
    touches the provider's network. The only HTTP call is the local
    Ollama model list (which fails closed to [])."""
    seen = []
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen_factory(
            seen, error=urllib.error.URLError("no route"),
        ),
    )
    agent = ChatAgent(store, "openai/gpt-oss-120b", provider="groq")
    reply = agent.reply("hi")
    assert "No Groq key saved yet" in reply
    assert "Settings" in reply
    assert seen, "expected the local Ollama list call"
    assert all(req.full_url.endswith("/api/tags") for req in seen)


def test_agent_replies_through_a_cloud_provider(store, monkeypatch):
    save_key(store.home, "groq", FAKE_KEY)
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen_factory([], _chat_payload("Hello, cloud user.")),
    )
    agent = ChatAgent(store, "openai/gpt-oss-120b", provider="groq")
    assert agent.reply("hi") == "Hello, cloud user."


def test_agent_set_provider_switches_the_client(store, monkeypatch):
    save_key(store.home, "gemini", FAKE_KEY)
    seen = []
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen_factory(seen, _chat_payload("Hi from Gemini.")),
    )
    agent = ChatAgent(store, "lfm3:1.7b", provider="ollama")
    agent.set_provider("gemini", "gemini-3.8-flash")
    assert agent.provider == "gemini"
    assert agent.model == "gemini-3.8-flash"
    assert agent.reply("hi") == "Hi from Gemini."
    # The first call is the local Ollama model list; the chat call
    # itself went to Gemini.
    assert any(
        "generativelanguage.googleapis.com" in req.full_url for req in seen
    )


# -- keys never leak -------------------------------------------------


def test_debug_report_never_holds_a_key(store, tmp_path):
    save_key(store.home, "groq", FAKE_KEY)
    save_key(store.home, "gemini", FAKE_KEY)
    log = DebugLogger("stella", "0.7.0", log_dir=str(tmp_path / "logs"))
    log.set_setting("home", str(store.home))
    # What the GUI registers: presence only, never values.
    log.set_setting("chat_providers", provider_presence(store.home))
    # Even the raw file contents pass through the scrubber redacted.
    scrubbed = scrub_dict(load_providers(store.home))
    assert FAKE_KEY not in json.dumps(scrubbed)
    assert scrubbed["groq"]["api_key"] == "[REDACTED], present"
    report = log.build_report()
    assert FAKE_KEY not in report
    assert "key saved" in report


def test_scrub_text_redacts_bare_provider_keys():
    assert "gsk_" not in scrub_text("key is gsk_abcdefghijklmnop1234")
    assert "AIza" not in scrub_text("key is AIzaSyAbCdEfGhIjKlMnOpQrStUv")
    assert "[REDACTED]" in scrub_text(
        "Authorization: Bearer gsk_abcdefghijklmnop1234"
    )


def test_export_package_never_holds_providers_json(store, seeded, tmp_path):
    from stella.export import export_project

    save_key(store.home, "groq", FAKE_KEY)
    out = export_project(store, "lfm3-tool", "tool-calls", tmp_path)
    names = [p.name for p in out.rglob("*")]
    assert "providers.json" not in names
    for path in out.rglob("*"):
        if path.is_file():
            assert FAKE_KEY not in path.read_text(
                encoding="utf-8", errors="ignore"
            )


# -- CLI ------------------------------------------------------------


def test_cli_chat_missing_key_exits_1(store, monkeypatch, capsys):
    from stella.cli import main

    monkeypatch.setenv("STELLA_HOME", str(store.home))
    code = main(
        ["chat", "--provider", "groq", "--model", "openai/gpt-oss-120b"]
    )
    assert code == 1
    assert "No Groq key saved yet" in capsys.readouterr().out


def test_cli_chat_unknown_provider_is_rejected(store, monkeypatch):
    from stella.cli import main

    monkeypatch.setenv("STELLA_HOME", str(store.home))
    with pytest.raises(SystemExit):
        main(["chat", "--provider", "nope"])


def test_missing_key_message_names_settings():
    message = missing_key_message("gemini")
    assert "Gemini" in message
    assert "Settings" in message
    assert "AI providers" in message
    assert "—" not in message


def test_no_em_dash_in_provider_text(home):
    for pid, info in PROVIDERS.items():
        assert "—" not in info["display"]
        for name in info["models"]:
            assert "—" not in name
    assert "—" not in missing_key_message("groq")
    ok, message = providers_mod.test_connection("groq", home=home)
    assert not ok
    assert "—" not in message


# -- v0.26.0: R51 — dated lists, staleness warning -------------------


def test_curated_lists_carry_check_dates():
    """R51: every curated list records when it was checked; the
    live and user-supplied lists carry no date to rot."""
    from datetime import date

    from stella.providers import list_checked_date

    assert list_checked_date("groq") == date(2026, 11, 17)
    assert list_checked_date("gemini") == date(2026, 11, 17)
    assert list_checked_date("ollama") is None
    assert list_checked_date("custom") is None
    assert list_checked_date("no-such-provider") is None


def test_list_stale_threshold():
    """R51: fresh within 90 days of the check date, stale after."""
    from datetime import date

    from stella.providers import list_stale

    assert list_stale("groq", today=date(2026, 11, 17)) is False
    assert list_stale("groq", today=date(2027, 2, 15)) is False  # day 90
    assert list_stale("groq", today=date(2027, 2, 16)) is True  # day 91
    assert list_stale("gemini", today=date(2027, 2, 16)) is True
    # Uncurated providers are never stale.
    assert list_stale("ollama", today=date(2027, 2, 16)) is False
    assert list_stale("custom", today=date(2027, 2, 16)) is False


def test_stale_list_notes_fresh_and_stale():
    """R51: no notes while fresh; one plain-words note per stale
    list, naming the date — and no em-dash in any of it."""
    from datetime import date

    from stella.providers import stale_list_notes

    assert stale_list_notes(today=date(2026, 11, 17)) == []
    notes = stale_list_notes(today=date(2027, 3, 1))
    assert len(notes) == 2
    assert any("Groq" in n and "2026-11-17" in n for n in notes)
    assert any("Gemini" in n and "2026-11-17" in n for n in notes)
    assert all("—" not in n for n in notes)
    assert all("try another one" in n for n in notes)


def test_missing_check_date_counts_as_stale(monkeypatch):
    """R51: a curated list with no check date is noticed, not
    silent — never checked is worse than checked long ago."""
    from stella.providers import list_stale, stale_list_notes

    monkeypatch.delitem(PROVIDERS["groq"], "checked")
    assert list_stale("groq") is True
    notes = stale_list_notes()
    assert any("Groq" in n and "no check date" in n for n in notes)
