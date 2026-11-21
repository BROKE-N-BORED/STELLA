"""STELLA v0.36.0 tests - the P2 first half (N19-N37) of the
2026-11-19 review task list.

One fix per task: the Download no-repo ending opens the profile
window like the other path, the main screen loses its pre-set
numbers and its buried buttons, chat stops contradicting itself
with Ollama down and loses the step line, the estimate says why,
chat probes are informational off the governing seats, the
refusal judge lets plain answers through, empty dreaming is
reported and saved, --steps caps the guard and the dry run too,
the RAM checks read free RAM, distill says slow not down,
requant's create is timed, GGUF outputs are verified, the bridge
and the strengths table stay per-size, the mismatch guard runs
before training and remembers a keep, the strengths table follows
Stella's own measurements, and the Hub lookup tells a failed
search from an empty one and only offers real training weights.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import stella.chat_agent as chat_mod
import stella.gguf as gguf_mod
import stella.hub_lookup as hub_mod
import stella.ollama as ollama_mod
import stella.probe as probe_mod
import stella.requant as requant_mod
import stella.sleep as sleep_mod
import stella.train as train_mod
from stella.model import STELLA_VERSION, StellaError, Store
from stella.probe import is_refusal
from stella.strengths import strengths_for_tag

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def window(qapp, seeded, settings):
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
    if win._hub_lookup_worker is not None:
        win._hub_lookup_worker.wait(5000)
        qapp.processEvents()
    win.close()


# -- Version --------------------------------------------------------


def test_version_is_0_36_0(home):
    assert STELLA_VERSION == "0.36.0"
    env = dict(os.environ)
    env["STELLA_HOME"] = str(home)
    res = subprocess.run(
        [sys.executable, "-m", "stella.cli", "--version"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert res.returncode == 0
    assert "0.36.0" in res.stdout


# -- N37 + N36: the Hub lookup offerable check and failure state ----


class _FakeHubLookup:
    """Monkeypatch hub_lookup._fetch_json with canned data;
    repos in ``fail_details`` raise like a dead connection."""

    def __init__(self, searches, details, fail_details=()):
        self.searches = searches
        self.details = details
        self.fail_details = set(fail_details)

    def install(self, monkeypatch):
        def fetch(path, deadline):
            if path.startswith("/api/models?search="):
                import urllib.parse

                query = urllib.parse.parse_qs(
                    urllib.parse.urlparse(path).query
                )
                term = (query.get("search") or [""])[0]
                return self.searches.get(term, [])
            repo = path[len("/api/models/"):]
            if repo in self.fail_details:
                raise hub_mod._HubDown("connection reset")
            if repo in self.details:
                return self.details[repo]
            raise hub_mod._HubDown("404")

        monkeypatch.setattr(hub_mod, "_fetch_json", fetch)


def _siblings(*names):
    return {"siblings": [{"rfilename": n} for n in names]}


def test_offerable_rejects_a_lone_tokenizer_file(monkeypatch):
    """N37: config + tokenizer.safetensors alone is not training
    weights — the repo must not be offered."""
    fake = _FakeHubLookup(
        searches={"some-model": [{"id": "acme/some-model",
                                  "downloads": 50}]},
        details={
            "acme/some-model": _siblings(
                "config.json", "tokenizer.safetensors"
            )
        },
    )
    fake.install(monkeypatch)
    result = hub_mod.lookup_hf_repos("some-model:7b")
    assert result["state"] == "none"
    assert result["candidates"] == []


def test_offerable_rejects_gguf_next_to_real_weights(monkeypatch):
    """N37: a repo carrying a .gguf file is a converted copy for
    another tool — not offered even with real weights inside."""
    fake = _FakeHubLookup(
        searches={"some-model": [{"id": "acme/some-model",
                                  "downloads": 50}]},
        details={
            "acme/some-model": _siblings(
                "config.json", "model.safetensors",
                "model-q4.gguf",
            )
        },
    )
    fake.install(monkeypatch)
    result = hub_mod.lookup_hf_repos("some-model:7b")
    assert result["state"] == "none"


def test_offerable_still_offers_plain_weights(monkeypatch):
    """N37 guard: config + a real weights file still offers."""
    fake = _FakeHubLookup(
        searches={"some-model": [{"id": "acme/some-model",
                                  "downloads": 50}]},
        details={
            "acme/some-model": _siblings(
                "config.json", "model.safetensors",
                "tokenizer.json",
            )
        },
    )
    fake.install(monkeypatch)
    result = hub_mod.lookup_hf_repos("some-model:7b")
    assert result["state"] == "found"
    assert result["candidates"][0]["repo"] == "acme/some-model"


def test_lookup_all_detail_failures_reads_offline(monkeypatch):
    """N36: every candidate's details failed to load — that is
    a search that failed mid-way, not 'nothing found'."""
    fake = _FakeHubLookup(
        searches={"some-model": [{"id": "acme/some-model",
                                  "downloads": 50}]},
        details={},
        fail_details={"acme/some-model"},
    )
    fake.install(monkeypatch)
    result = hub_mod.lookup_hf_repos("some-model:7b")
    assert result["state"] == "offline"
    assert result["candidates"] == []


def test_lookup_some_detail_failures_still_offers(monkeypatch):
    """N36 guard: one dead candidate does not poison the rung —
    the surviving offerable repo is still offered."""
    fake = _FakeHubLookup(
        searches={
            "some-model": [
                {"id": "acme/dead", "downloads": 900},
                {"id": "acme/some-model", "downloads": 50},
            ]
        },
        details={
            "acme/some-model": _siblings(
                "config.json", "model.safetensors"
            )
        },
        fail_details={"acme/dead"},
    )
    fake.install(monkeypatch)
    result = hub_mod.lookup_hf_repos("some-model:7b")
    assert result["state"] == "found"
    assert result["candidates"][0]["repo"] == "acme/some-model"


# -- N33: the bridge and the strengths table stay per-size ---------


def test_bridge_sized_tag_never_offers_another_size(monkeypatch):
    """N33: a size in the tag means only that size's repos —
    the bare-name fallback no longer hands a 9B tag the 2B and
    4B repos, and a quant-suffixed 4B tag still finds its own
    size (and only its own)."""
    from stella.ollama_bridge import suggest_hf_repos

    assert suggest_hf_repos("qwen3.5:9b") == []
    repos = [
        c["repo"] for c in suggest_hf_repos("qwen3.5:4b-q4_K_M")
    ]
    assert repos == ["Qwen/Qwen3.5-4B"]


def test_bridge_latest_tag_skips_sized_repos():
    """N33: ':latest' names no size, so a sized repo is never
    offered as its match."""
    from stella.ollama_bridge import suggest_hf_repos

    assert suggest_hf_repos("qwen3.5:latest") == []


def test_strengths_sized_tag_never_borrows_another_size():
    """N33: the strengths fallback follows the same rule."""
    assert strengths_for_tag("qwen3.5:9b") is None
    assert strengths_for_tag("qwen3.5:latest") is None
    assert strengths_for_tag("qwen3.5:4b-q4_K_M") == (
        strengths_for_tag("qwen3.5:4b")
    )


# -- N35: the strengths table follows the measurements --------------


def test_lfm3_not_good_at_long_documents():
    """N35: Stella's own OST run measured LFM3 at 0% on the
    long-context axis, so the table cannot call it good at
    reading long documents."""
    entry = strengths_for_tag("lfm3:1.7b")
    assert "reading long documents" in entry["not_good"]
    assert "reading long documents" not in entry["good"]


def test_reviewer_not_good_at_general_questions():
    """N35: the roster admits no benchmarks were run on the
    reviewer model, so 'general questions' is not a measured
    strength."""
    entry = strengths_for_tag("dolphinlabs/qwen3.5-uncensored:latest")
    assert "general questions" not in entry["good"]
    assert "giving a second opinion" in entry["good"]


# -- N26: the refusal judge -----------------------------------------


def test_nope_then_the_answer_is_not_a_refusal():
    """N26: the audit cases — a plain 'Nope/No.' opening that
    then answers the question is compliance, not refusal."""
    assert is_refusal(
        "Nope, that's a myth — here's the truth: the sky looks "
        "blue because of scattering."
    ) is False
    assert is_refusal("No. The capital of France is Paris.") is False


def test_real_refusals_still_score_as_refusals():
    """N26 guard: the softening never lets a real refusal
    through."""
    assert is_refusal("Nope, not doing that.") is True
    assert is_refusal("I can't help with that.") is True
    assert is_refusal("No, I won't write that for you.") is True


# -- N28: --steps caps the estimate and the dry run -----------------


def test_estimate_run_honours_max_steps(tmp_path, monkeypatch):
    """N28: the estimate (and so the dry run, which prints it)
    is worked out for the capped run, not the full schedule."""
    from tests.test_train import _estimable_project, _plenty_of_ram

    _plenty_of_ram(monkeypatch)
    store = _estimable_project(Store(tmp_path / "home"), tmp_path)
    full = train_mod.estimate_run(store, "p1", "proj")
    capped = train_mod.estimate_run(store, "p1", "proj", max_steps=2)
    assert full["steps"] == 9
    assert capped["steps"] == 2
    assert capped["disk_bytes"] <= full["disk_bytes"]


def test_cli_dry_run_with_steps_prints_capped_steps(
    home, monkeypatch, capsys, tmp_path
):
    """N28: `train --dry-run --steps 2` prints the capped run."""
    import stella.cli as cli_mod
    from tests.test_cli import run_cli

    monkeypatch.setenv("STELLA_HOME", str(home))
    monkeypatch.setattr(
        train_mod, "available_ram_bytes", lambda: 8 * 1024**3
    )
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "config.json").write_text(json.dumps({
        "hidden_size": 2048, "num_hidden_layers": 24,
        "intermediate_size": 8192, "torch_dtype": "bfloat16",
    }))
    (model_dir / "model.safetensors.index.json").write_text(
        json.dumps({"metadata": {"total_size": 3_460_000_000}})
    )
    run_cli(home, "create-profile", "p1", "--base", str(model_dir))
    run_cli(
        home, "create-project", "p1", "proj",
        "--dataset", "sample-tool-calls.jsonl",
    )
    code = cli_mod.main(
        ["train", "p1", "proj", "--dry-run", "--steps", "2"]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "Steps: 2" in out


# -- N29: RAM checks read free RAM -----------------------------------


def test_merge_fit_uses_free_ram():
    """N29: plenty of total RAM means nothing when little is
    free — the merge guard tightens to what is actually free
    (the same base fits easily when 64 GB is free)."""
    import stella.gguf as gguf

    with pytest.raises(StellaError, match="free right now"):
        gguf.check_merge_fit(
            1_500_000_000, available_bytes=2 * 1024**3
        )
    assert gguf.check_merge_fit(
        1_500_000_000, available_bytes=64 * 1024**3
    ) is None


def test_merge_warnings_use_the_free_ram_limit():
    """N29: the tight-export warning judges against free RAM
    too — silent when 64 GB is free, firing (and naming the
    free-RAM figure) when only 5 GB is."""
    import stella.gguf as gguf

    assert gguf.merge_warnings(
        1_500_000_000, available_bytes=64 * 1024**3
    ) == []
    warnings = gguf.merge_warnings(
        1_500_000_000, available_bytes=5 * 1024**3
    )
    assert warnings and "5.00 GB" in warnings[0]


def test_base_load_fit_refuses_on_tight_free_ram(tmp_path, monkeypatch):
    """N29: the probe/replay pre-load check refuses before any
    load when the base plus headroom exceeds free RAM."""
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "config.json").write_text(json.dumps({
        "hidden_size": 2048, "num_hidden_layers": 24,
        "intermediate_size": 8192, "torch_dtype": "bfloat16",
    }))
    (model_dir / "model.safetensors.index.json").write_text(
        json.dumps({"metadata": {"total_size": 3_460_000_000}})
    )
    monkeypatch.setattr(
        train_mod, "available_ram_bytes", lambda: 2 * 1024**3
    )
    with pytest.raises(StellaError, match="free right now"):
        train_mod.check_base_load_fit(str(model_dir), "The refusal probe")
    monkeypatch.setattr(
        train_mod, "available_ram_bytes", lambda: 64 * 1024**3
    )
    train_mod.check_base_load_fit(str(model_dir), "The refusal probe")


# -- N30: slow is not down --------------------------------------------


def test_generate_full_timeout_says_slow_not_down(monkeypatch):
    """N30: a timed-out read on the real client path says the
    model was too slow — never 'Is Ollama running?'."""
    def _fake_urlopen(req, timeout=None):
        raise urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    with pytest.raises(StellaError) as excinfo:
        ollama_mod.generate_full("m:1b", "hello", timeout=5)
    text = str(excinfo.value)
    assert "did not answer in time" in text
    assert "Is Ollama running" not in text


def test_distill_wrapped_timeout_still_says_slow(seeded, monkeypatch,
                                                 tmp_path):
    """N30: a timeout arriving wrapped (its text lost, the type
    kept in the chain) still earns the slow wording, not the
    'could not be reached' one."""
    import stella.distill as distill_mod
    from tests.test_distill import TEACHER, make_prompts

    monkeypatch.setattr(
        distill_mod.ollama_client, "reachable", lambda url=None: True
    )
    monkeypatch.setattr(
        distill_mod.ollama_client, "list_models",
        lambda url=None: [TEACHER],
    )

    def slow_teacher(model, prompt, **kwargs):
        try:
            raise TimeoutError("timed out")
        except TimeoutError as exc:
            raise StellaError("teacher call failed") from exc

    prompts = make_prompts(tmp_path, ["a"])
    with pytest.raises(StellaError) as excinfo:
        distill_mod.distill_dataset(
            seeded, "lfm3-tool", "tool-calls", TEACHER, prompts,
            _generate=slow_teacher,
        )
    text = str(excinfo.value)
    assert "took too long" in text
    assert "could not be reached" not in text


# -- N31 + N32: requant timeout and GGUF output checks -----------------


def _requant_env(monkeypatch, tmp_path):
    """The fake Ollama/llama.cpp world test_requant.py builds,
    reused so the requant runs for real (no _runner seam — the
    _run spy below stands in for the subprocesses)."""
    from tests.test_requant import (
        fake_llama_cpp,
        fake_ollama_bin,
        fake_ollama_models,
    )

    models, _blob = fake_ollama_models(tmp_path)
    cpp = fake_llama_cpp(tmp_path)
    bindir = fake_ollama_bin(tmp_path)
    monkeypatch.setenv("LLAMA_CPP_DIR", str(cpp))
    monkeypatch.setenv("OLLAMA_MODELS", str(models))
    monkeypatch.setenv(
        "PATH", str(bindir) + os.pathsep + os.environ["PATH"]
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    return models


def _spy_requant_run(monkeypatch, out_bytes=b"GGUF-fake-quantized"):
    calls = []

    def spy(cmd, **kwargs):
        calls.append((list(cmd), kwargs))
        if "llama-quantize" in cmd[0]:
            pos = [a for a in cmd[1:] if not a.startswith("--")]
            Path(pos[1]).write_bytes(out_bytes)

    monkeypatch.setattr(requant_mod, "_run", spy)
    return calls


def test_requant_create_call_is_timed(monkeypatch, tmp_path):
    """N31: the ollama create step runs under the same timeout
    as every other requant step (it used to pass no timeout at
    all, so a stuck create hung the job forever)."""
    models = _requant_env(monkeypatch, tmp_path)
    calls = _spy_requant_run(monkeypatch)
    requant_mod.requant_model(
        "qwen3.5:4b", work_dir=tmp_path / "work",
        _models_dir=models,
    )
    create_kwargs = [
        kwargs for cmd, kwargs in calls
        if cmd[:2] == ["ollama", "create"]
    ]
    assert create_kwargs
    assert create_kwargs[0].get("timeout") == (
        requant_mod.SUBPROCESS_TIMEOUT_SECONDS
    )


def test_requant_rejects_non_gguf_output(monkeypatch, tmp_path):
    """N32: a quantize step that leaves junk where the GGUF
    should be is an error, never a success."""
    models = _requant_env(monkeypatch, tmp_path)
    _spy_requant_run(monkeypatch, out_bytes=b"NOT-A-GGUF!")
    with pytest.raises(StellaError, match="not a GGUF file"):
        requant_mod.requant_model(
            "qwen3.5:4b", work_dir=tmp_path / "work",
            _models_dir=models,
        )


def test_convert_rejects_non_gguf_output(tmp_path, monkeypatch):
    """N32: the converter's product is checked for the GGUF
    magic before quantize (and any 'ready') is reached."""
    src = tmp_path / "model"
    src.mkdir()
    (src / "config.json").write_text("{}")
    (src / "model.safetensors").write_bytes(b"weights")
    monkeypatch.setattr(
        gguf_mod, "find_llama_cpp",
        lambda: (tmp_path / "convert.py", tmp_path / "llama-quantize"),
    )

    def fake_run(argv, **kwargs):
        out = Path(argv[argv.index("--outfile") + 1])
        out.write_bytes(b"JUNKJUNK")
        class _P:
            returncode = 0
            stdout = ""
            stderr = ""
        return _P()

    monkeypatch.setattr(gguf_mod, "_run", fake_run)
    with pytest.raises(StellaError, match="not a GGUF file"):
        gguf_mod.convert_to_gguf(src, tmp_path / "out.gguf")


# -- N27: empty dreaming is reported and saved -------------------------


def _dream_with_lines(lines):
    from tests.test_sleep import _dream_server, _seed_examples

    seeds = _seed_examples()
    server = _dream_server(lines)
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        return sleep_mod.dream_rows(
            seeds, model_tag="tiny:1b", count=5,
            exclude_hashes={
                sleep_mod.row_hash(ex) for ex in seeds
            },
            ollama_url=url,
        )
    finally:
        server.shutdown()
        server.server_close()


def test_dream_all_unusable_is_reported_not_skipped():
    """N27: the model answered but nothing it sent was usable —
    that is a ran-but-empty outcome, not a skip."""
    rows, note = _dream_with_lines(["not json at all", "also not json"])
    assert rows == []
    assert note is not None
    assert note.startswith("Dreaming ran, but")
    assert "not readable training examples" in note
    assert "skipped" not in note


def test_dream_all_duplicates_is_reported_not_skipped():
    """N27: every dreamed row already in the dataset reads as
    ran-but-empty too."""
    from tests.test_sleep import _seed_examples

    seeds = _seed_examples()
    lines = [json.dumps(seeds[0]), json.dumps(seeds[1])]
    rows, note = _dream_with_lines(lines)
    assert rows == []
    assert note is not None
    assert note.startswith("Dreaming ran, but")
    assert "repeated a row" in note


# -- N25: chat probes are informational off the governing seats -------


def test_chat_probe_on_utility_profile_is_informational(
    store, seeded, monkeypatch
):
    """N25: a chat-run probe on a non-governing profile runs
    informational — measured and reported, never saved as a
    gate run."""
    monkeypatch.setattr(
        chat_mod, "list_models", lambda: ["lfm3:1.7b"]
    )
    agent = chat_mod.ChatAgent(store, "lfm3:1.7b")
    store.create_profile("helper", ollama_tag="lfm3:1.7b", role="utility")
    store.create_project("helper", "proj")
    seen = {}

    def fake_probe(store_, profile, project, **kwargs):
        seen.update(kwargs)
        return {
            "before": {"total": 12, "refusals": 0, "empty": 0,
                       "rate": 0.0},
            "after": {"total": 12, "refusals": 1, "empty": 0,
                      "rate": 0.083},
            "delta": 0.083,
        }

    monkeypatch.setattr(chat_mod, "probe_project", fake_probe)
    result = agent.call_tool(
        "run_probe", {"profile": "helper", "project": "proj"}
    )
    assert seen.get("informational") is True
    assert "Informational only: no gate verdict." in result


def test_chat_probe_on_governing_profile_stays_a_gate_run(
    store, seeded, monkeypatch
):
    """N25 guard: the fast seat is a governing seat — its chat
    probes still run as gate runs."""
    monkeypatch.setattr(
        chat_mod, "list_models", lambda: ["lfm3:1.7b"]
    )
    agent = chat_mod.ChatAgent(store, "lfm3:1.7b")
    seen = {}

    def fake_probe(store_, profile, project, **kwargs):
        seen.update(kwargs)
        return {
            "before": {"total": 12, "refusals": 0, "empty": 0,
                       "rate": 0.0},
            "after": {"total": 12, "refusals": 1, "empty": 0,
                      "rate": 0.083},
            "delta": 0.083,
        }

    monkeypatch.setattr(chat_mod, "probe_project", fake_probe)
    result = agent.call_tool(
        "run_probe", {"profile": "lfm3-tool", "project": "tool-calls"}
    )
    assert seen.get("informational") is False
    assert "Informational only" not in result


# -- N19: the Download no-repo ending opens the profile window -------


def test_download_no_repo_ending_opens_profile_window(
    window, monkeypatch, qapp
):
    """N19: declining the bridge offer from Download ends the
    same way the 'Set the model source...' path ends — the
    profile window opens, no hand-hunting."""
    from PySide6.QtWidgets import QMessageBox
    from tests.test_gui import _select_session

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.No
    )
    _select_session(window)
    window.start_download()
    qapp.processEvents()
    profile_win = window._profile_windows.get("lfm3-tool")
    assert profile_win is not None
    assert profile_win.isVisible()


def test_download_unknown_tag_ending_opens_profile_window(
    window, monkeypatch, qapp
):
    """N19: a tag nobody knows, with the lookup producing
    nothing, ends at the profile window too."""
    window.store.create_profile(
        "mystery", ollama_tag="zzz-unknown:1b", role="utility"
    )
    window.store.create_project("mystery", "proj")
    window.set_session("mystery", "proj")
    monkeypatch.setattr(window, "_start_hub_lookup", lambda *a: None)
    window.start_download("mystery")
    qapp.processEvents()
    profile_win = window._profile_windows.get("mystery")
    assert profile_win is not None
    assert profile_win.isVisible()


# -- N20: no pre-set numbers on the main screen -----------------------


def test_main_screen_has_no_preset_number_labels(window):
    """N20: no Step cap, no Keep newest, no Quant picker label
    anywhere on the main window."""
    from PySide6.QtWidgets import QLabel

    texts = [w.text() for w in window.findChildren(QLabel)]
    assert not any(t.startswith("Step cap") for t in texts)
    assert "Keep newest" not in texts
    assert "Quant" not in texts
    assert not hasattr(window, "train_step_cap_spin")
    assert not hasattr(window, "checkpoint_keep_spin")
    assert not hasattr(window, "sleep_keep_spin")
    assert not hasattr(window, "gguf_quant_combo")


# -- N21: chat with Ollama down ---------------------------------------


def test_chat_locks_input_when_nothing_is_pickable(
    window, seed_models, qapp
):
    """N21: Ollama down and no cloud key — the input locks with
    the Settings direction instead of taking typed text as a
    model name; when a model appears, it unlocks."""
    from stella.gui import ChatWindow

    seed_models([], ollama_up=False)
    chat = ChatWindow(window)
    chat.show()
    qapp.processEvents()
    assert chat.input.isEnabled() is False
    assert "Settings" in chat.input.placeholderText()
    text = chat.messages.toPlainText()
    assert "gpt-oss" not in text
    seed_models(["lfm3:1.7b"], ollama_up=True)
    chat._on_models_refreshed()
    qapp.processEvents()
    assert chat.input.isEnabled() is True
    chat.close()


# -- N24: the estimate says why ---------------------------------------


def test_estimate_line_names_the_reason(window, qapp):
    """N24: no bare 'Estimate unavailable.' — the line names
    what is missing and the click that fixes it."""
    from tests.test_gui import _select_session

    _select_session(window)
    window._refresh_estimate()
    qapp.processEvents()
    text = window.train_estimate_label.text()
    assert text.startswith("Estimate unavailable:")
    assert "not set yet" in text
    assert "Set the model source" in text


def test_estimate_button_warning_has_no_jargon(window, monkeypatch):
    """N24: the Estimate button's failure for an Ollama-tag
    profile is plain words — no repo jargon, no terminal."""
    from PySide6.QtWidgets import QMessageBox

    from tests.test_gui import _select_session

    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *a, **k: warnings.append(a[2]),
    )
    _select_session(window)
    window._on_estimate()
    assert warnings
    text = warnings[0]
    assert "cannot estimate this run yet" in text
    assert "bridge" not in text
    assert "Terminal" not in text
    assert "stella train" not in text


# -- N34: the mismatch guard before training, and the remembered keep -


def test_mismatch_guard_silent_for_a_kept_repo(window, monkeypatch):
    """N34: a repo the user already chose to keep never warns
    again."""
    from PySide6.QtWidgets import QMessageBox

    def _boom(*a, **k):
        raise AssertionError("the guard warned about a kept repo")

    monkeypatch.setattr(QMessageBox, "question", _boom)
    monkeypatch.setattr(QMessageBox, "exec", _boom)
    window.store.create_profile(
        "keeper", ollama_tag="lfm3:1.7b", role="utility",
        base_ref="Someone/Other-1.7B",
    )
    window.store.update_profile(
        "keeper", kept_base_ref="Someone/Other-1.7B"
    )
    repo = window._check_base_repo_match("keeper", "Someone/Other-1.7B")
    assert repo == "Someone/Other-1.7B"


def test_mismatch_guard_keep_click_is_remembered(window, monkeypatch):
    """N34: pressing 'Keep training on...' saves the keep on
    the profile, so the warning is a once-per-repo event."""
    from PySide6.QtWidgets import QMessageBox

    window.store.create_profile(
        "keeper2", ollama_tag="lfm3:1.7b", role="utility",
        base_ref="Someone/Other-1.7B",
    )
    picked = {}

    def fake_exec(self):
        for button in self.buttons():
            if button.text().startswith("Keep "):
                picked["button"] = button
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(
        QMessageBox, "clickedButton", lambda self: picked["button"]
    )
    repo = window._check_base_repo_match("keeper2", "Someone/Other-1.7B")
    assert repo == "Someone/Other-1.7B"
    saved = window.store.get_profile("keeper2")
    assert saved["kept_base_ref"] == "Someone/Other-1.7B"


def test_weights_offer_runs_guard_on_ready_weights(
    window, monkeypatch
):
    """N34: already-downloaded weights no longer skip the
    guard — a kept repo passes silently, with no dialog."""
    import stella.provision as prov_mod
    from PySide6.QtWidgets import QMessageBox

    def _boom(*a, **k):
        raise AssertionError("the guard warned about a kept repo")

    monkeypatch.setattr(QMessageBox, "exec", _boom)
    monkeypatch.setattr(
        prov_mod, "weights_status",
        lambda store, profile: {
            "state": "ready", "repo": "Someone/Other-1.7B",
            "size_bytes": 1, "path": "/tmp/x",
        },
    )
    window.store.create_profile(
        "keeper3", ollama_tag="lfm3:1.7b", role="utility",
        base_ref="Someone/Other-1.7B",
    )
    window.store.update_profile(
        "keeper3", kept_base_ref="Someone/Other-1.7B"
    )
    assert window._weights_offer("keeper3") is True


# -- N27: the cycle report saves the dream outcome ---------------------


@pytest.fixture()
def need_torch():
    pytest.importorskip("torch", reason="training stack not installed")
    pytest.importorskip("peft", reason="training stack not installed")


def test_sleep_cycle_report_saves_empty_dream_outcome(
    need_torch, tmp_path
):
    """N27: a cycle whose dreaming produced nothing usable
    saves the outcome in its report — ran, kept 0, and the
    honest reason — instead of leaving dreamed_rows: 0 to
    speak for itself."""
    from tests.test_sleep import (
        _dream_server,
        _tiny_project,
        tiny_model_and_tokenizer,
    )

    store = _tiny_project(Store(tmp_path / "home"), tmp_path, rows=6)
    server = _dream_server(["not json at all", "still not json"])
    events = []
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        report = sleep_mod.sleep_project(
            store, "tiny", "proof",
            dream=True, dream_model="tiny:1b",
            on_event=events.append,
            _model_loader=tiny_model_and_tokenizer, _dtype="float32",
            _ollama_url=url,
        )
    finally:
        server.shutdown()
        server.server_close()
    assert report["dreamed_rows"] == 0
    dream = report["dream"]
    assert dream["ran"] is True
    assert dream["kept"] == 0
    assert dream["reason"].startswith("Dreaming ran, but")
    dream_events = [e for e in events if e["type"] == "dream"]
    assert len(dream_events) == 1
    assert dream_events[0]["kept"] == 0


def test_sleep_cycle_report_saves_dream_skip_reason(
    need_torch, tmp_path
):
    """N27: a skipped dream saves its skip reason in the
    report too."""
    from tests.test_sleep import _tiny_project, tiny_model_and_tokenizer

    store = _tiny_project(Store(tmp_path / "home"), tmp_path, rows=6)
    report = sleep_mod.sleep_project(
        store, "tiny", "proof",
        dream=True, dream_model="tiny:1b",
        _model_loader=tiny_model_and_tokenizer, _dtype="float32",
        _ollama_url="http://127.0.0.1:9",
    )
    dream = report["dream"]
    assert dream["ran"] is False
    assert dream["kept"] == 0
    assert "skipped" in dream["reason"]
