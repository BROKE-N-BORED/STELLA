"""STELLA v0.29.0 tests — P3 batch 2, chat/providers/CLI half
(R103–R113): tool-help args, cloud streaming, corrupt providers
file, cloud token counts, setting-flag help, probe --json errors,
the stella-cli comment, MetaMorphAi wording, small CLI fixes, the
five new CLI commands, and the training-settings disclosure.
"""
import json
import logging
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from stella.model import StellaError, Store

ROOT = Path(__file__).resolve().parent.parent


def _run_cli_subprocess(home, *args):
    """Run the real `python -m stella.cli` in a subprocess."""
    env = dict(os.environ)
    env["STELLA_HOME"] = str(home)
    return subprocess.run(
        [sys.executable, "-m", "stella.cli", *args],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )


def _seed_cli_home(home):
    _run_cli_subprocess(
        home, "create-profile", "p1", "--tag", "lfm3:1.7b",
        "--role", "fast",
    )
    _run_cli_subprocess(
        home, "create-project", "p1", "proj",
        "--dataset", "sample-tool-calls.jsonl",
    )


@pytest.fixture()
def window(qapp, seeded, settings):
    """The main window on the seeded store (one profile, one
    project) — the same fixture test_gui.py uses, defined here so
    this file stands alone. Teardown waits for any running job
    before closing, so a worker cannot leak into the next
    test."""
    from stella.gui import MainWindow

    win = MainWindow(store=seeded, settings=settings)
    win.show()
    qapp.processEvents()
    if win._model_list_worker is not None:
        win._model_list_worker.wait(5000)
        qapp.processEvents()
    yield win
    from tests.test_gui import _wait_for_all_workers

    _wait_for_all_workers(win, qapp)
    win.close()


# -- Version --------------------------------------------------------
# (moved to test_v30.py — the version is 0.30.0 now)


# -- R103: resume / dest documented in TOOL_HELP ----------------------


def test_tool_help_names_resume_and_dest():
    """R103: the start_training help names the resume arg and the
    export_gguf help names the dest arg, following the optional-arg
    pattern run_sleep/distill already use."""
    from stella.chat_agent import TOOL_HELP

    assert '"resume": true' in TOOL_HELP["start_training"]
    assert '"dest"' in TOOL_HELP["export_gguf"]
    assert "—" not in TOOL_HELP["start_training"]
    assert "—" not in TOOL_HELP["export_gguf"]


# -- R104: cloud providers stream -------------------------------------


class _FakeSSEResponse:
    """A stand-in for a urllib SSE response: iterable byte lines,
    context manager."""

    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._lines)


def _sse_lines():
    return [
        b'data: {"choices": [{"delta": {"content": "Hello "}}]}\n',
        # A partial JSON line: skipped, never fatal.
        b'data: {"choices": [{"delta": {"content": "wo',
        b'data: {"choices": [{"delta": {"content": "world."}}]}\n',
        b'data: {"choices": [], "usage": {"prompt_tokens": 5, '
        b'"completion_tokens": 3, "total_tokens": 8}}\n',
        b"data: [DONE]\n",
    ]


def test_cloud_chat_stream_reads_sse(home, monkeypatch):
    """R104: a cloud streaming call reads SSE chunks, calls
    on_token per piece, survives a partial JSON line, and stops
    at data: [DONE]."""
    from stella.providers import chat_stream, save_key

    save_key(home, "groq", "test-key-123")
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout=None: _FakeSSEResponse(_sse_lines()),
    )
    tokens = []
    text = chat_stream(
        "groq", "openai/gpt-oss-20b",
        [{"role": "user", "content": "hi"}], home,
        on_token=tokens.append,
    )
    assert text == "Hello world."
    assert tokens == ["Hello ", "world."]


def test_cloud_chat_stream_reports_usage(home, monkeypatch):
    """R104/R106: the final SSE chunk's usage block comes back
    from chat_stream_with_usage."""
    from stella.providers import chat_stream_with_usage, save_key

    save_key(home, "groq", "test-key-123")
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout=None: _FakeSSEResponse(_sse_lines()),
    )
    text, usage = chat_stream_with_usage(
        "groq", "openai/gpt-oss-20b",
        [{"role": "user", "content": "hi"}], home,
    )
    assert text == "Hello world."
    assert usage == {
        "prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8,
    }


def test_cloud_stream_sends_stream_flag(home, monkeypatch):
    """R104: the streaming call sends stream true (and asks for
    usage on Groq)."""
    from stella.providers import chat_stream, save_key

    save_key(home, "groq", "test-key-123")
    seen = {}

    def _fake(request, timeout=None):
        seen["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeSSEResponse(_sse_lines())

    monkeypatch.setattr(urllib.request, "urlopen", _fake)
    chat_stream(
        "groq", "openai/gpt-oss-20b",
        [{"role": "user", "content": "hi"}], home,
    )
    assert seen["payload"]["stream"] is True
    assert seen["payload"]["stream_options"] == {"include_usage": True}


def test_agent_streams_cloud_like_ollama(store):
    """R104: _refresh_stream_fn gives a cloud provider a stream
    function (not None), keeps Ollama on chat_stream, and keeps a
    supplied stream_fn / chat_fn untouched."""
    from stella.chat_agent import ChatAgent
    from stella.ollama import chat_stream

    agent = ChatAgent(store, "openai/gpt-oss-20b", provider="groq")
    assert agent._stream_fn is not None
    agent.set_provider("ollama", "lfm3:1.7b")
    assert agent._stream_fn is chat_stream
    agent.set_provider("gemini", "gemini-3.8-flash")
    assert agent._stream_fn is not None

    def _fake_stream(model, messages, on_token=None):
        return "x"

    agent2 = ChatAgent(
        store, "m", provider="groq", stream_fn=_fake_stream
    )
    assert agent2._stream_fn is _fake_stream
    agent3 = ChatAgent(
        store, "m", provider="ollama",
        chat_fn=lambda model, messages: "x",
    )
    assert agent3._stream_fn is None


def test_agent_model_call_streams_cloud_chunks(store, monkeypatch):
    """R104: a cloud reply streams through _model_call with the
    same bookkeeping as Ollama's — last_streamed_plain holds the
    streamed words, so the window does not double-print."""
    from stella.chat_agent import ChatAgent
    from stella.providers import save_key

    save_key(store.home, "groq", "test-key-123")
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout=None: _FakeSSEResponse(_sse_lines()),
    )
    agent = ChatAgent(store, "openai/gpt-oss-20b", provider="groq")
    tokens = []
    agent.set_callbacks(on_token=tokens.append)
    text = agent._model_call([{"role": "user", "content": "hi"}])
    assert text == "Hello world."
    assert "".join(tokens) == "Hello world."
    assert agent.last_streamed_plain == "Hello world."
    assert agent.last_usage.get("total_tokens") == 8


def test_agent_model_call_suppresses_cloud_tool_fence(store, monkeypatch):
    """R104: a tool fence in a cloud stream suppresses the rest,
    exactly as for Ollama — the user never sees JSON."""
    from stella.chat_agent import ChatAgent
    from stella.providers import save_key

    save_key(store.home, "groq", "test-key-123")
    lines = [
        b'data: {"choices": [{"delta": {"content": "Before the fence "}}]}\n',
        b'data: {"choices": [{"delta": {"content": "```tool {\\"tool\\": \\"x\\"}"}}]}\n',
        b"data: [DONE]\n",
    ]
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout=None: _FakeSSEResponse(lines),
    )
    agent = ChatAgent(store, "openai/gpt-oss-20b", provider="groq")
    tokens = []
    agent.set_callbacks(on_token=tokens.append)
    text = agent._model_call([{"role": "user", "content": "hi"}])
    assert "```tool" in text
    assert "".join(tokens) == "Before the fence "
    assert agent.last_streamed_plain == "Before the fence"


# -- R105: a corrupt providers.json says so ---------------------------


def test_providers_corrupt_detects_bad_json(home):
    """R105: providers_corrupt tells corrupt from missing — a
    missing file is not corrupt, bad JSON and non-object JSON
    are."""
    from stella.providers import load_providers, providers_corrupt

    assert providers_corrupt(home) is False
    assert load_providers(home) == {}
    from stella.providers import providers_path

    providers_path(home).parent.mkdir(parents=True, exist_ok=True)
    providers_path(home).write_text("{}", encoding="utf-8")
    assert providers_corrupt(home) is False
    providers_path(home).write_text("{not json", encoding="utf-8")
    assert providers_corrupt(home) is True
    assert load_providers(home) == {}
    providers_path(home).write_text("[1, 2]", encoding="utf-8")
    assert providers_corrupt(home) is True
    assert load_providers(home) == {}


def test_reset_corrupt_providers_backs_up_first(home):
    """R105: resetting a corrupt file backs it up
    (providers.json.corrupt) before removing it, and does nothing
    when the file is fine."""
    from stella.providers import (
        load_providers,
        providers_corrupt,
        providers_path,
        reset_corrupt_providers,
    )

    providers_path(home).parent.mkdir(parents=True, exist_ok=True)
    providers_path(home).write_bytes(b"{corrupt bytes")
    backup = reset_corrupt_providers(home)
    assert backup is not None
    assert backup.name == "providers.json.corrupt"
    assert backup.read_bytes() == b"{corrupt bytes"
    assert not providers_path(home).exists()
    assert providers_corrupt(home) is False
    assert load_providers(home) == {}
    assert reset_corrupt_providers(home) is None


def test_save_key_backs_up_corrupt_file(home):
    """R105: saving a key over a corrupt file backs the corrupt
    bytes up first — the load-then-save path must not silently
    drop the other keys."""
    from stella.providers import (
        get_key,
        providers_path,
        save_key,
    )

    providers_path(home).parent.mkdir(parents=True, exist_ok=True)
    providers_path(home).write_bytes(b"{corrupt bytes")
    save_key(home, "groq", "test-key-123")
    assert get_key(home, "groq") == "test-key-123"
    backup = providers_path(home).with_name("providers.json.corrupt")
    assert backup.read_bytes() == b"{corrupt bytes"


def test_chat_on_corrupt_file_says_damaged(home):
    """R105: a chat call with a corrupt file says the file is
    damaged, not "no key saved yet"."""
    import pytest

    from stella.providers import (
        ProviderError,
        chat,
        providers_path,
        test_connection,
    )

    providers_path(home).parent.mkdir(parents=True, exist_ok=True)
    providers_path(home).write_text("{not json", encoding="utf-8")
    with pytest.raises(ProviderError, match="damaged"):
        chat(
            "groq", "openai/gpt-oss-20b",
            [{"role": "user", "content": "hi"}], home,
        )
    ok, message = test_connection("groq", home=home)
    assert ok is False
    assert "damaged" in message


def test_settings_shows_corrupt_notice(window, seeded, qapp):
    """R105: Settings shows the damaged-file notice and the reset
    button when providers.json is corrupt, and hides both when
    the file is fine."""
    from stella.providers import providers_path

    providers_path(seeded.home).parent.mkdir(parents=True, exist_ok=True)
    providers_path(seeded.home).write_text("{not json", encoding="utf-8")
    win = window.open_settings_window()
    qapp.processEvents()
    assert not win._corrupt_label.isHidden()
    assert not win._corrupt_reset_btn.isHidden()
    assert "damaged" in win._corrupt_label.text()
    win.close()


def test_settings_reset_button_backs_up_and_clears(
    window, seeded, qapp, monkeypatch
):
    """R105: the Settings reset asks first (default No), backs the
    damaged file up, and clears the notice."""
    from PySide6.QtWidgets import QMessageBox

    from stella.providers import providers_path

    providers_path(seeded.home).parent.mkdir(parents=True, exist_ok=True)
    providers_path(seeded.home).write_bytes(b"{corrupt bytes")
    win = window.open_settings_window()
    qapp.processEvents()
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: QMessageBox.Yes,
    )
    win._corrupt_reset_btn.click()
    qapp.processEvents()
    assert not providers_path(seeded.home).exists()
    backup = providers_path(seeded.home).with_name(
        "providers.json.corrupt"
    )
    assert backup.read_bytes() == b"{corrupt bytes"
    assert win._corrupt_reset_btn.isHidden()
    assert "kept as providers.json.corrupt" in win._corrupt_label.text()
    win.close()


# -- R106: cloud token counts -----------------------------------------


class _FakeJSONResponse:
    """A stand-in for a urllib JSON response."""

    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _usage_payload():
    return {
        "choices": [
            {"message": {"role": "assistant", "content": "Hello back."}}
        ],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 4,
            "total_tokens": 16,
        },
    }


def test_chat_with_usage_captures_counts(home, monkeypatch):
    """R106: chat_with_usage returns the reply plus the usage
    counts; chat still returns just the text."""
    from stella.providers import chat, chat_with_usage, save_key

    save_key(home, "groq", "test-key-123")
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout=None: _FakeJSONResponse(_usage_payload()),
    )
    text, usage = chat_with_usage(
        "groq", "openai/gpt-oss-20b",
        [{"role": "user", "content": "hi"}], home,
    )
    assert text == "Hello back."
    assert usage == {
        "prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16,
    }
    assert chat(
        "groq", "openai/gpt-oss-20b",
        [{"role": "user", "content": "hi"}], home,
    ) == "Hello back."


def test_chat_with_usage_missing_is_empty(home, monkeypatch):
    """R106: a reply with no usage block reports no counts — a
    missing block is not an error."""
    from stella.providers import chat_with_usage, save_key

    save_key(home, "groq", "test-key-123")
    payload = {
        "choices": [
            {"message": {"role": "assistant", "content": "Hi."}}
        ],
    }
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout=None: _FakeJSONResponse(payload),
    )
    _text, usage = chat_with_usage(
        "groq", "openai/gpt-oss-20b",
        [{"role": "user", "content": "hi"}], home,
    )
    assert usage == {}


def test_agent_last_usage_text(store, monkeypatch):
    """R106: a non-streaming cloud call leaves the turn's counts
    on the agent, in plain words; a fresh agent reports none."""
    from stella.chat_agent import ChatAgent
    from stella.providers import save_key

    agent = ChatAgent(store, "openai/gpt-oss-20b", provider="groq")
    assert agent.last_usage_text() == ""
    save_key(store.home, "groq", "test-key-123")
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout=None: _FakeJSONResponse(_usage_payload()),
    )
    text = agent._model_call([{"role": "user", "content": "hi"}])
    assert text == "Hello back."
    assert agent.last_usage == {
        "prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16,
    }
    assert agent.last_usage_text() == (
        "That reply used 16 tokens (12 sent, 4 back)."
    )


def test_chat_window_shows_usage_line(window, qapp):
    """R106: the chat window shows the token count after a cloud
    reply, and shows nothing when the agent reports none."""
    chat = window.open_chat_window()
    chat._agent = SimpleNamespace(
        last_usage_text=lambda: "That reply used 16 tokens (12 sent, 4 back).",
        last_streamed_plain="",
        pending_plan=None,
        current_profile=None,
        current_project=None,
    )
    chat._on_reply("Hello back.")
    qapp.processEvents()
    assert "That reply used 16 tokens (12 sent, 4 back)." in (
        chat.messages.toPlainText()
    )
    chat._agent = SimpleNamespace(
        last_usage_text=lambda: "",
        last_streamed_plain="",
        pending_plan=None,
        current_profile=None,
        current_project=None,
    )
    chat._on_reply("Local reply.")
    qapp.processEvents()
    assert chat.messages.toPlainText().count("That reply used") == 1
    chat.close()


# -- R107: real help for the setting flags ----------------------------


def test_setting_flag_help_names_range_and_default():
    """R107: every setting flag's help says what it does and names
    its range (from SETTING_RULES) or default — no more
    "training setting: rank"."""
    from stella.cli import SETTING_FLAGS, SETTING_HELP
    from stella.model import DEFAULT_SETTINGS, SETTING_RULES

    for _flag, key, _kind in SETTING_FLAGS:
        help_text = SETTING_HELP[key]
        assert len(help_text) > len(key) + 10, key
        if key == "seed":
            # The 32-bit range is not helpful as numbers; the
            # default is the pin.
            assert "default 42" in help_text
            continue
        _kind, low, high = SETTING_RULES[key]
        low_s = str(int(low)) if float(low) == int(low) else str(low)
        high_s = str(int(high)) if float(high) == int(high) else str(high)
        assert f"{low_s} to {high_s}" in help_text, key
        assert f"default {DEFAULT_SETTINGS[key]}" in help_text, key


def test_create_project_help_shows_setting_help(home):
    """R107: create-project --help shows the real flag help, and
    --method names its values."""
    res = _run_cli_subprocess(home, "create-project", "--help")
    assert res.returncode == 0
    assert "1 to 64" in res.stdout  # rank
    assert "1 to 100" in res.stdout  # epochs
    assert "default 0.0002" in res.stdout  # learning rate
    assert "lora only" in res.stdout  # method
    assert "training setting: rank" not in res.stdout


def test_quant_help_names_common_values(home):
    """R107: --quant help names the common values and points at
    the error's full list, on both commands that take it."""
    for command in ("export-gguf", "requant"):
        res = _run_cli_subprocess(home, command, "--help")
        assert res.returncode == 0
        # argparse wraps the help, so the phrases are checked on
        # the whitespace-flattened text.
        flat = " ".join(res.stdout.split())
        assert "Q5_K_M" in flat, command
        assert "Q8_0" in flat, command
        assert "full list" in flat, command


# -- R108: probe --json prints JSON on failure ------------------------


def test_probe_json_failure_prints_json_error(
    monkeypatch, seeded, capsys
):
    """R108: probe --json against a failure prints a JSON error
    document on stdout (ok false), exit 1 — not silence."""
    import stella.cli as cli
    import stella.probe as probe_mod

    def _boom(*a, **k):
        raise StellaError("no adapter yet: train first")

    monkeypatch.setattr(cli, "_store", lambda: seeded)
    monkeypatch.setattr(probe_mod, "probe_project", _boom)
    code = cli.main(
        ["probe", "lfm3-tool", "tool-calls", "--json"]
    )
    assert code == 1
    out = capsys.readouterr()
    data = json.loads(out.out)
    assert data == {"ok": False, "error": "no adapter yet: train first"}
    assert "stella: no adapter yet" in out.err


def test_probe_human_failure_unchanged(monkeypatch, seeded, capsys):
    """R108: without --json the failure path is unchanged — the
    stderr line, exit 1, nothing on stdout."""
    import stella.cli as cli
    import stella.probe as probe_mod

    def _boom(*a, **k):
        raise StellaError("no adapter yet: train first")

    monkeypatch.setattr(cli, "_store", lambda: seeded)
    monkeypatch.setattr(probe_mod, "probe_project", _boom)
    code = cli.main(["probe", "lfm3-tool", "tool-calls"])
    assert code == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert "stella: no adapter yet" in out.err


def test_probe_json_gate_fail_still_exits_3(monkeypatch, seeded, capsys):
    """R108: the JSON error document does not flatten the exit
    codes — a gate failure still exits 3 with the result JSON."""
    import stella.cli as cli
    import stella.probe as probe_mod

    result = {
        "before": {
            "refusals": 0, "total": 18, "rate": 0.0, "empty": 0,
        },
        "after": {
            "refusals": 9, "total": 18, "rate": 0.5, "empty": 0,
        },
        "delta": 0.5,
        "probe_set": "fast",
        "mode": "gate",
    }
    monkeypatch.setattr(cli, "_store", lambda: seeded)
    monkeypatch.setattr(
        probe_mod, "probe_project", lambda *a, **k: result
    )
    code = cli.main(
        ["probe", "lfm3-tool", "tool-calls", "--gate", "--json"]
    )
    assert code == 3
    out = capsys.readouterr()
    data = json.loads(out.out)
    assert data["probe_set"] == "fast"


# -- R109: the stella-cli comment no longer lists commands ------------


def test_stella_cli_comment_lists_no_commands():
    """R109: the wrapper comment dropped the command list (it went
    stale twice) and points at --help instead."""
    text = (ROOT / "stella-cli").read_text(encoding="utf-8")
    assert "bash stella-cli <command>" in text
    assert "bash stella-cli profiles" not in text
    assert "bash stella-cli probe" not in text
    assert "--help" in text


# -- R110: no MetaMorphAi in CLI help ---------------------------------


def test_no_metamorphai_in_cli_help():
    """R110: no CLI help text contains "MetaMorphAi" (mirroring
    the GUI-side T71 rule), and --metamorph still names its
    values."""
    from stella.cli import build_parser

    parser = build_parser()
    subs = parser._subparsers._group_actions[0].choices
    for name, sub in subs.items():
        assert "MetaMorphAi" not in sub.format_help(), name
    create_help = subs["create-project"].format_help()
    assert "morph, compress" in create_help
    assert "or both" in create_help
    update_help = subs["update-project"].format_help()
    assert "morph, compress" in update_help


# -- R111: four small CLI fixes ---------------------------------------


def test_project_errors_name_the_profile(store, seeded):
    """R111(a): delete/rename/purge/notes errors name the profile,
    matching get_project's wording."""
    with pytest.raises(StellaError, match="in profile 'lfm3-tool'"):
        store.delete_project("lfm3-tool", "ghost")
    with pytest.raises(StellaError, match="in profile 'lfm3-tool'"):
        store.rename_project("lfm3-tool", "ghost", "new")
    with pytest.raises(StellaError, match="in profile 'lfm3-tool'"):
        store.purge_project("lfm3-tool", "ghost")
    with pytest.raises(StellaError, match="in profile 'lfm3-tool'"):
        store.write_notes("lfm3-tool", "ghost", "x")


def test_silence_huggingface_hub_advisory():
    """R111(b): _silence_library_warnings quiets the
    huggingface_hub logger (the unauthenticated-requests advisory
    arrives as a logger.warning, not a warnings.warn) while real
    hub errors still show."""
    import stella.cli as cli_mod

    logger = logging.getLogger("huggingface_hub")
    old_level = logger.level
    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _Capture(level=logging.DEBUG)
    logger.addHandler(handler)
    try:
        cli_mod._silence_library_warnings()
        assert logger.level == logging.ERROR
        logger.warning(
            "You are sending unauthenticated requests to the HF Hub"
        )
        logger.error("a real hub error")
        assert records == ["a real hub error"]
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)


def test_format_estimate_single_rough():
    """R111(c): the time line carries one hedge, not two — the
    time note already says "roughly"."""
    from stella.train import format_estimate

    estimate = {
        "estimate_bytes": 100_000_000,
        "dataset_bytes": 10_000,
        "fits": True,
        "steps": 9,
        "train_examples": 18,
        "val_examples": 2,
        "disk_bytes": 50_000_000,
        "time_note": "roughly minutes",
    }
    report = format_estimate(estimate)
    assert "Time: roughly minutes on this PC." in report
    assert "(rough)" not in report


def test_pull_weights_no_progress_line_before_failure(
    monkeypatch, capsys
):
    """R111(d): a failed pull shows only its error — the progress
    line prints only when a pull actually starts."""
    import stella.cli as cli
    import stella.provision as provision_mod

    monkeypatch.setattr(provision_mod, "hub_available", lambda: True)

    def _failing(repo, _print=print):
        _print("ERROR That repo does not exist on Hugging Face.")
        return 1

    monkeypatch.setattr(provision_mod, "run_download", _failing)
    args = SimpleNamespace(
        repo="org/no-such-repo", json=False, quiet=False,
        verbose=False,
    )
    assert cli.cmd_pull_weights(args) == 1
    out = capsys.readouterr()
    assert "Pulling weights for" not in out.out
    assert "That repo does not exist" in out.err


# -- R112: five new CLI commands --------------------------------------


def test_cli_mark_ready(home):
    """R112: mark-ready sets the status to ready (and prints the
    record with --json)."""
    _seed_cli_home(home)
    res = _run_cli_subprocess(home, "mark-ready", "p1", "proj")
    assert res.returncode == 0
    assert "ready" in res.stdout
    assert Store(home).get_project("p1", "proj")["status"] == "ready"
    res = _run_cli_subprocess(home, "mark-ready", "p1", "proj", "--json")
    assert res.returncode == 0
    assert json.loads(res.stdout)["status"] == "ready"
    res = _run_cli_subprocess(home, "mark-ready", "p1", "ghost")
    assert res.returncode == 1
    assert "no project named 'ghost'" in res.stderr


def test_cli_notes_read_write_and_backup(home):
    """R112: notes reads by default, --set writes through
    write_notes (so the notes.md.1 backup still happens)."""
    _seed_cli_home(home)
    pdir = Store(home).project_dir("p1", "proj")
    # A fresh project seeds its notes; with the file removed the
    # read says there are none yet.
    res = _run_cli_subprocess(home, "notes", "p1", "proj")
    assert res.returncode == 0
    assert "# proj" in res.stdout
    (pdir / "notes.md").unlink()
    res = _run_cli_subprocess(home, "notes", "p1", "proj")
    assert res.returncode == 0
    assert "No notes" in res.stdout
    res = _run_cli_subprocess(
        home, "notes", "p1", "proj", "--set", "first note"
    )
    assert res.returncode == 0
    assert "Saved notes" in res.stdout
    res = _run_cli_subprocess(home, "notes", "p1", "proj")
    assert res.stdout.strip() == "first note"
    res = _run_cli_subprocess(
        home, "notes", "p1", "proj", "--set", "second note"
    )
    assert res.returncode == 0
    res = _run_cli_subprocess(home, "notes", "p1", "proj", "--json")
    assert json.loads(res.stdout)["notes"] == "second note"
    assert (pdir / "notes.md.1").read_text() == "first note"
    res = _run_cli_subprocess(home, "notes", "p1", "ghost")
    assert res.returncode == 1
    assert "no project named 'ghost'" in res.stderr


def test_cli_probe_results(home):
    """R112: probe-results pretty-prints the saved results, fails
    plainly with none, and never re-runs the probe."""
    _seed_cli_home(home)
    res = _run_cli_subprocess(home, "probe-results", "p1", "proj")
    assert res.returncode == 1
    assert "no probe results" in res.stderr
    assert "Run the probe first" in res.stderr
    result = {
        "before": {
            "refusals": 9, "total": 18, "rate": 0.5, "empty": 0,
        },
        "after": {
            "refusals": 1, "total": 18, "rate": 0.06, "empty": 0,
        },
        "delta": -0.44,
        "probe_set": "fast",
        "mode": "informational",
    }
    pdir = Store(home).project_dir("p1", "proj")
    (pdir / "probe_results.json").write_text(json.dumps(result))
    res = _run_cli_subprocess(home, "probe-results", "p1", "proj")
    assert res.returncode == 0
    assert "Refusals: 9/18 before, 1/18 after" in res.stdout
    assert "Probe set: fast (18 prompts)." in res.stdout
    assert "Informational only" in res.stdout
    res = _run_cli_subprocess(home, "probe-results", "p1", "proj", "--json")
    assert res.returncode == 0
    assert json.loads(res.stdout)["probe_set"] == "fast"


def test_cli_howto(home):
    """R112: howto lists the topics with no argument, prints one
    topic by name (case-insensitively), and refuses an unknown
    one plainly."""
    res = _run_cli_subprocess(home, "howto")
    assert res.returncode == 0
    assert "Training" in res.stdout
    assert "Getting started" in res.stdout
    res = _run_cli_subprocess(home, "howto", "Training")
    assert res.returncode == 0
    assert "Training teaches the model" in res.stdout
    res = _run_cli_subprocess(home, "howto", "training")
    assert res.returncode == 0
    assert "Training teaches the model" in res.stdout
    res = _run_cli_subprocess(home, "howto", "No such topic")
    assert res.returncode == 1
    assert "no How to Use topic called" in res.stderr


def test_cli_debug_report(home):
    """R112: debug-report writes the same report the GUI writes
    (same logger, same log dir), and names the file."""
    res = _run_cli_subprocess(home, "debug-report")
    assert res.returncode == 0
    assert "Debug report written to" in res.stdout
    reports = sorted((home / "logs").glob("debug-report-stella-*.txt"))
    assert len(reports) == 1
    text = reports[0].read_text(encoding="utf-8")
    assert "DEBUG REPORT: stella 0.30.0" in text
    assert str(home) in text  # the home setting, as the GUI sets it
    res = _run_cli_subprocess(home, "debug-report", "--json")
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert Path(data["report"]).is_file()


def test_new_commands_listed_in_parser():
    """R112: the five new commands exist in the parser."""
    from stella.cli import build_parser

    subs = build_parser()._subparsers._group_actions[0].choices
    for name in (
        "mark-ready", "notes", "probe-results", "howto",
        "debug-report",
    ):
        assert name in subs, name


# -- R113: the settings disclosure ------------------------------------


def test_project_window_discloses_terminal_settings(window, qapp):
    """R113: the project detail panel names the exact terminal
    command for changing training settings — disclosure only, no
    settings controls come back."""
    from tests.test_gui import _select_session

    _select_session(window)
    win = window.open_project_window("lfm3-tool", "tool-calls")
    qapp.processEvents()
    note = win._settings_note.text()
    assert "Training settings are changed from the terminal" in note
    assert (
        "stella update-project lfm3-tool tool-calls --seed 7" in note
    )
    for attr in ("rank_spin", "lr_edit", "epochs_spin"):
        assert not hasattr(win, attr), attr
    win.close()


def test_session_summary_discloses_terminal_settings(window, qapp):
    """R113: the session summary names the same command."""
    from tests.test_gui import _select_session

    _select_session(window)
    qapp.processEvents()
    summary = window.session_summary.text()
    assert "Training settings are changed from the terminal" in summary
    assert (
        "stella update-project lfm3-tool tool-calls --seed 7"
        in summary
    )


def test_howto_training_mirrors_settings_disclosure():
    """R113: the How to Use Training topic mirrors the line."""
    from stella.howto import topic_text

    body = topic_text("Training")
    assert "Training settings are changed from the terminal" in body
    # The topic wraps the command across lines; flatten to check it.
    flat = " ".join(body.split())
    assert "stella update-project <profile> <project> --seed 7" in flat
