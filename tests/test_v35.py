"""STELLA v0.35.0 tests - the P1 batch (N1-N18) of the
2026-11-19 review task list.

One fix per task: the requant type table reads real ggml ids,
the Hub lookup only offers the model that was picked, report
cards check the model for every shape and merge across cards,
a retrain or base change stales a saved probe pass, requant
verifies its create before deleting the only copy, distill
gates on this run's rows, chat names failed steps and only
honours a repo confirm after a real offer, plan approval
respects negation, and the user-visible words lose the
terminal lines, package names and unexplained jargon.
"""
import io
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

import stella.chat_agent as chat_mod
import stella.cli as cli_mod
import stella.hub_lookup as hub_mod
from stella.chat_agent import ChatAgent
from stella.model import STELLA_VERSION, StellaError, Store
from stella.requant import _TENSOR_TYPE_QUANT, _read_gguf_source_quant

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def need_torch():
    pytest.importorskip("torch", reason="training stack not installed")
    pytest.importorskip("peft", reason="training stack not installed")


# -- Version --------------------------------------------------------


def test_version_is_0_36_0_everywhere(home):
    assert STELLA_VERSION == "0.36.0"
    env = dict(os.environ)
    env["STELLA_HOME"] = str(home)
    res = subprocess.run(
        [sys.executable, "-m", "stella.cli", "--version"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert res.returncode == 0
    assert "0.36.0" in res.stdout


# -- N1: the ggml tensor-type table ---------------------------------


def _gguf_with_types(tmp_path, specs):
    out = bytearray()
    out += b"GGUF"
    out += struct.pack("<I", 3)
    out += struct.pack("<Q", len(specs))
    out += struct.pack("<Q", 0)
    for index, (ttype, elements) in enumerate(specs):
        name = f"blk.{index}.weight".encode()
        out += struct.pack("<Q", len(name)) + name
        out += struct.pack("<I", 1)
        out += struct.pack("<Q", elements)
        out += struct.pack("<I", ttype)
        out += struct.pack("<Q", 0)
    path = tmp_path / "t.gguf"
    path.write_bytes(bytes(out))
    return path


@pytest.mark.parametrize(
    "ttype,name,bpw",
    [
        (9, "Q8_1", 8.5), (10, "Q2_K", 3.35), (11, "Q3_K", 3.9),
        (12, "Q4_K", 4.85), (13, "Q5_K", 5.5), (14, "Q6_K", 6.6),
        (15, "Q8_K", 8.5), (16, "IQ2_XXS", 2.06),
        (20, "IQ4_NL", 4.5), (23, "IQ4_XS", 4.25),
        (27, "I64", 64.0), (28, "F64", 64.0), (30, "BF16", 16.0),
    ],
)
def test_tensor_table_matches_ggml_h(tmp_path, ttype, name, bpw):
    """The real ggml.h ids: 9 is Q8_1, 12 is Q4_K, 15 is Q8_K."""
    assert _TENSOR_TYPE_QUANT[ttype] == (name, bpw)
    path = _gguf_with_types(tmp_path, [(ttype, 100_000)])
    assert _read_gguf_source_quant(path) == (name, bpw)


def test_q8k_dominant_file_reads_q8k_not_f32(tmp_path):
    """The audit case: a Q8_K-dominant file used to read as F32
    (id 15 was mapped to a 2-bit type, so F32 won the byte vote
    and the double-quant warning was suppressed)."""
    path = _gguf_with_types(
        tmp_path, [(15, 100_000), (15, 100_000), (0, 128)]
    )
    assert _read_gguf_source_quant(path) == ("Q8_K", 8.5)


# -- N2: the Hub lookup only offers the picked model -----------------


class _FakeHubLookup:
    """Monkeypatch hub_lookup._fetch_json with canned data."""

    def __init__(self, searches, details):
        self.searches = searches
        self.details = details

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
            if repo in self.details:
                return self.details[repo]
            raise hub_mod._HubDown("404")

        monkeypatch.setattr(hub_mod, "_fetch_json", fetch)


def _weights(*names):
    return {
        "siblings": [{"rfilename": "config.json"}]
        + [{"rfilename": n} for n in names]
    }


def test_hub_lookup_reviewer_tag_offers_nothing_unrelated(monkeypatch):
    """The audit case: dolphinlabs/qwen3.5-uncensored:latest was
    offered DeepSeek heretic builds at 9B/4B and a DavidAU 9B.
    None of them is this model, so the honest answer is none."""
    tag = "dolphinlabs/qwen3.5-uncensored:latest"
    repos = [
        {"id": "someone/DeepSeek-V4-Pro-Qwen3.5-Heretic-9B",
         "downloads": 9000},
        {"id": "other/DeepSeek-V4-Pro-Qwen3.5-Heretic-4B",
         "downloads": 8000},
        {"id": "DavidAU/Qwen3.5-9B", "downloads": 7000},
    ]
    _FakeHubLookup(
        searches={"qwen3.5-uncensored": repos},
        details={r["id"]: _weights("model.safetensors") for r in repos},
    ).install(monkeypatch)
    result = hub_mod.lookup_hf_repos(tag)
    assert result == {"state": "none", "candidates": []}


def test_hub_lookup_still_offers_the_real_repo(monkeypatch):
    tag = "dolphinlabs/qwen3.5-uncensored:latest"
    repo = "dolphinlabs/qwen3.5-uncensored"
    _FakeHubLookup(
        searches={"qwen3.5-uncensored": [{"id": repo, "downloads": 5}]},
        details={repo: _weights("model.safetensors")},
    ).install(monkeypatch)
    result = hub_mod.lookup_hf_repos(tag)
    assert result["state"] == "found"
    assert [c["repo"] for c in result["candidates"]] == [repo]


def test_hub_lookup_size_mismatch_is_not_offered(monkeypatch):
    """A 9B repo is not the 4B model the user picked."""
    _FakeHubLookup(
        searches={
            "qwen3.5": [
                {"id": "Qwen/Qwen3.5-9B", "downloads": 100},
                {"id": "Qwen/Qwen3.5-4B", "downloads": 50},
            ]
        },
        details={
            "Qwen/Qwen3.5-9B": _weights("model.safetensors"),
            "Qwen/Qwen3.5-4B": _weights("model.safetensors"),
        },
    ).install(monkeypatch)
    result = hub_mod.lookup_hf_repos("qwen3.5:4b")
    assert [c["repo"] for c in result["candidates"]] == [
        "Qwen/Qwen3.5-4B"
    ]


def test_hub_lookup_base_repo_for_tuned_tag_still_offers(monkeypatch):
    """The Granite shape: the tuned tag's base repo (name says
    base, size agrees) is a true match and stays offerable."""
    repo = "ibm-granite/granite-4.1-3b-base"
    _FakeHubLookup(
        searches={
            "granite4.1-abliterated": [{"id": repo, "downloads": 10}]
        },
        details={repo: _weights("model.safetensors")},
    ).install(monkeypatch)
    result = hub_mod.lookup_hf_repos("huihui_ai/granite4.1-abliterated:3b")
    assert [c["repo"] for c in result["candidates"]] == [repo]


# -- N3 + N4: report cards -------------------------------------------


def _run_file(model, template, score, ts, total=5):
    return {
        "template": template, "template_score": score,
        "passed": 5, "total": total, "model": model,
        "timestamp": ts,
    }


def test_single_file_card_for_another_model_is_unread(store, tmp_path):
    from stella.report_cards import add_report_card, list_report_cards

    store.create_profile("lfm3-tool", ollama_tag="lfm3:1.7b")
    path = tmp_path / "bonsai.json"
    path.write_text(json.dumps(_run_file(
        "eriktonon/bonsai-2-uncensored:2b", "coding", 100.0,
        "2026-11-16T10:00:00",
    )))
    card = add_report_card(store, "lfm3-tool", path)
    assert card["kind"] == "ost-other"
    assert card["parsed"] is None
    assert list_report_cards(store, "lfm3-tool")[0]["kind"] == "ost-other"


def test_list_card_for_another_model_is_unread(tmp_path):
    from stella.report_cards import parse_ost_card

    path = tmp_path / "runs.json"
    path.write_text(json.dumps([
        _run_file("bonsai-2:4b", "coding", 100.0, "2026-11-16T10:00:00"),
        _run_file("bonsai-2:4b", "math", 90.0, "2026-11-16T11:00:00"),
    ]))
    assert parse_ost_card(path, tag_hint="lfm3:1.7b") is None
    assert parse_ost_card(path, tag_hint="bonsai-2:4b") is not None


def test_strengths_merge_across_all_cards(store, tmp_path):
    """N4: one file per test, attached one by one - the merged
    strengths cover every test, newest result per test winning."""
    from stella.report_cards import add_report_card, strengths_from_cards

    store.create_profile("lfm3-tool", ollama_tag="lfm3:1.7b")
    cards = [
        _run_file("lfm3:1.7b", "coding", 100.0, "2026-11-16T10:00:00"),
        _run_file("lfm3:1.7b", "math", 90.0, "2026-11-16T10:00:00"),
        _run_file("lfm3:1.7b", "long_context", 0.0, "2026-11-16T10:00:00"),
        # A newer coding run at a middle score replaces the 100.
        _run_file("lfm3:1.7b", "coding", 60.0, "2026-11-17T10:00:00"),
    ]
    for i, data in enumerate(cards):
        path = tmp_path / f"card{i}.json"
        path.write_text(json.dumps(data))
        add_report_card(store, "lfm3-tool", path)
    entry = strengths_from_cards(store, "lfm3-tool")
    assert entry is not None
    assert entry["good"] == ["maths"]
    assert entry["not_good"] == ["reading long documents"]


# -- N5 + N13: the probe gate ----------------------------------------


def _governing_store(store):
    store.create_profile(
        "seat", ollama_tag="lfm3:1.7b", role="fast",
        base_ref="LiquidAI/LFM3-1.7B", governing_seat="driver",
    )
    store.create_project("seat", "proj")
    return store


def _passed_result(store, **overrides):
    result = {
        "mode": "gate",
        "before": {"total": 2, "refusals": 0, "empty": 0, "rate": 0.0},
        "after": {"total": 2, "refusals": 0, "empty": 0, "rate": 0.0},
        "delta": 0.0,
        "base_ref": "LiquidAI/LFM3-1.7B",
    }
    result.update(overrides)
    path = store.project_dir("seat", "proj") / "probe_results.json"
    path.write_text(json.dumps(result))
    return path


def _adapter(store, mtime=None):
    adapter = store.project_dir("seat", "proj") / "adapter"
    adapter.mkdir(parents=True, exist_ok=True)
    config = adapter / "adapter_config.json"
    config.write_text("{}\n")
    if mtime is not None:
        os.utime(config, (mtime, mtime))
    return adapter


def test_gate_refusal_without_adapter_says_train_first(store):
    from stella.probe import require_passed_probe

    _governing_store(store)
    with pytest.raises(StellaError) as exc:
        require_passed_probe(store, "seat", "proj")
    text = str(exc.value)
    assert "safety check" in text
    assert "Train the model" in text
    assert "governing seat" not in text
    assert "stella probe" not in text


def test_gate_refusal_with_adapter_says_run_the_probe(store):
    from stella.probe import require_passed_probe

    _governing_store(store)
    _adapter(store)
    with pytest.raises(StellaError) as exc:
        require_passed_probe(store, "seat", "proj")
    text = str(exc.value)
    assert "Run the refusal probe first" in text
    assert "Train the model" not in text


def test_gate_refuses_a_result_for_a_different_base(store):
    from stella.probe import require_passed_probe

    _governing_store(store)
    _adapter(store)
    _passed_result(store, base_ref="SomeoneElse/Other-1B")
    with pytest.raises(StellaError, match="different base model"):
        require_passed_probe(store, "seat", "proj")


def test_gate_refuses_a_result_older_than_the_adapter(store):
    import time

    from stella.probe import require_passed_probe

    _governing_store(store)
    _adapter(store, mtime=time.time())
    _passed_result(
        store, timestamp="2020-01-01T00:00:00+00:00"
    )
    with pytest.raises(StellaError, match="does not count"):
        require_passed_probe(store, "seat", "proj")


def test_gate_passes_for_a_fresh_matching_result(store):
    import time
    from datetime import datetime, timezone

    from stella.probe import require_passed_probe

    _governing_store(store)
    _adapter(store, mtime=time.time() - 3600)
    _passed_result(
        store,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    verdict = require_passed_probe(store, "seat", "proj")
    assert verdict is not None and "Gate passed" in verdict


def test_training_a_new_adapter_drops_the_saved_probe(
    need_torch, tmp_path
):
    """N5: the run that lands a new adapter invalidates the
    saved probe result, so the gate measures the new adapter."""
    from stella.train import train_project
    from tests.test_train import _tiny_project, tiny_model_and_tokenizer

    store = _tiny_project(Store(tmp_path / "home"), tmp_path)
    probe_file = store.project_dir("tiny", "proof") / "probe_results.json"
    probe_file.write_text(json.dumps({"mode": "gate"}))
    train_project(
        store, "tiny", "proof",
        _model_loader=tiny_model_and_tokenizer, _dtype="float32",
    )
    assert not probe_file.exists()


# -- N6: requant verifies the create ----------------------------------


def test_requant_unverified_create_keeps_the_file(
    monkeypatch, tmp_path
):
    from tests.test_requant import (
        FakeRunner,
        fake_llama_cpp,
        fake_ollama_bin,
        fake_ollama_models,
    )
    from stella.requant import requant_model

    models, _blob = fake_ollama_models(tmp_path)
    cpp = fake_llama_cpp(tmp_path)
    bindir = fake_ollama_bin(tmp_path)
    monkeypatch.setenv("LLAMA_CPP_DIR", str(cpp))
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    runner = FakeRunner(fail_verify=True)
    with pytest.raises(StellaError) as exc:
        requant_model(
            "qwen3.5:4b", work_dir=tmp_path / "work",
            _runner=runner, _models_dir=models,
        )
    text = str(exc.value)
    assert "not in Ollama now" in text
    assert "still at" in text
    kept = list((tmp_path / "work").rglob("*.gguf"))
    assert len(kept) == 1


# -- N7: distill gates on this run ------------------------------------


def test_distill_all_failed_with_stale_rows_refuses(
    seeded, monkeypatch, tmp_path
):
    from stella import ollama as ollama_mod
    from stella.distill import distill_dataset

    monkeypatch.setattr(ollama_mod, "reachable", lambda url=None: True)
    monkeypatch.setattr(
        ollama_mod, "list_models", lambda url=None: ["teacher:1b"]
    )
    project_dir = seeded.project_dir("lfm3-tool", "tool-calls")
    stale = project_dir / "distilled.jsonl"
    stale.write_text(
        json.dumps({"prompt": "old one", "completion": "old"}) + "\n"
        + json.dumps({"prompt": "old two", "completion": "old"}) + "\n"
    )
    prompts = tmp_path / "prompts.txt"
    prompts.write_text("new one\nnew two\nnew three\n")

    def fail(tag, prompt):
        raise StellaError("the teacher had no answer (fake)")

    with pytest.raises(StellaError, match="no new dataset was made"):
        distill_dataset(
            seeded, "lfm3-tool", "tool-calls", "teacher:1b", prompts,
            _generate=fail,
        )
    project = seeded.get_project("lfm3-tool", "tool-calls")
    assert project.get("dataset_ref") != "distilled.jsonl"


# -- N8 + N9 + N10: chat ----------------------------------------------


class _Scripted:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, model, messages):
        self.calls.append(messages)
        if self.replies:
            return self.replies.pop(0)
        return "Done. Anything else?"


def _tool_block(name, args=None):
    return "```tool\n" + json.dumps(
        {"tool": name, "args": args or {}}
    ) + "\n```"


@pytest.fixture()
def agent(store, monkeypatch):
    monkeypatch.setattr(
        chat_mod, "list_models", lambda: ["lfm3:1.7b", "qwen3.5:2b"]
    )
    return ChatAgent(store, "lfm3:1.7b")


def test_chat_failed_step_is_named_in_the_final_reply(agent, seeded):
    """N8: the dataset step fails; the model's 'all done' claim
    must not stand alone."""
    scripted = _Scripted([
        _tool_block("set_project_dataset", {
            "profile": "lfm3-tool", "project": "tool-calls",
            "path": "/no/such/file.jsonl",
        }),
        "All done! Everything is finished.",
    ])
    agent._chat_fn = scripted
    agent.current_profile = "lfm3-tool"
    agent.current_project = "tool-calls"
    reply = agent.reply("set the dataset and finish")
    assert "All done" in reply
    assert "What did not work" in reply


def test_chat_confirm_without_an_offer_sets_nothing(agent, seeded):
    """N9: a confirm flag in the model's first-ever tool call,
    with no offer ever shown, must not set the repo."""
    result = agent.call_tool(
        "download_weights",
        {
            "profile": "lfm3-tool", "confirm": True,
            "repo": "LiquidAI/LFM3-1.7B",
        },
    )
    assert seeded.get_profile("lfm3-tool")["base_ref"] == "lfm3:1.7b"
    assert "LiquidAI/LFM3-1.7B" in result  # the offer itself


def test_chat_bare_confirm_confirms_the_single_candidate(
    agent, seeded, monkeypatch
):
    """N9 mirror: one candidate on the table, a confirming call
    with no repo name confirms it instead of re-offering."""
    first = agent.call_tool(
        "download_weights", {"profile": "lfm3-tool"}
    )
    assert "LiquidAI/LFM3-1.7B" in first
    monkeypatch.setattr(chat_mod, "hub_available", lambda: True)
    monkeypatch.setattr(chat_mod, "run_download", lambda repo, **k: 0)
    second = agent.call_tool(
        "download_weights",
        {"profile": "lfm3-tool", "confirm": True},
    )
    assert seeded.get_profile("lfm3-tool")["base_ref"] == (
        "LiquidAI/LFM3-1.7B"
    )
    assert "downloaded and ready" in second


@pytest.mark.parametrize(
    "message", ["yes but not yet", "go ahead and do something else entirely"]
)
def test_plan_negation_never_runs_the_plan(agent, message):
    """N10: negation wins over the approval prefix."""
    agent.reply("just do it")
    assert agent.pending_plan is not None
    scripted = _Scripted(["I ran the plan."])
    agent._chat_fn = scripted
    agent.reply(message)
    assert agent.pending_plan is None
    for call in scripted.calls:
        for msg in call:
            assert "Run the plan we agreed on" not in msg.get(
                "content", ""
            )


def test_plan_plain_approval_still_runs(agent):
    agent.reply("just do it")
    scripted = _Scripted(["Done it."])
    agent._chat_fn = scripted
    reply = agent.reply("go ahead")
    assert reply == "Done it."
    users = [m for m in scripted.calls[0] if m["role"] == "user"]
    assert any("Run the plan we agreed on" in m["content"] for m in users)


# -- N11 + N12 + N18: words in the window and the guide ---------------


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


def test_main_screen_summary_has_no_terminal_line(window, qapp):
    from tests.test_gui import _select_session

    _select_session(window)
    qapp.processEvents()
    summary = window.session_summary.text()
    assert "picked for this PC automatically" in summary
    assert "terminal" not in summary
    assert "update-project" not in summary
    assert "--seed" not in summary


def test_missing_training_message_is_plain(window, seeded, monkeypatch, qapp):
    """N12: pressing Go for Train without the training stack
    shows the plain message - one direction, no package names,
    no terminal line."""
    import stella.gui as gui_mod
    import stella.train as train_mod

    monkeypatch.setattr(
        train_mod, "training_deps_missing", lambda: ["torch"]
    )
    # The GUI module imported the names into its own call sites
    # lazily (from .train import ...), so patching train_mod is
    # enough; the dialog text is captured via _warn.
    warnings = []
    monkeypatch.setattr(window, "_warn", warnings.append)
    monkeypatch.setattr(window, "_train_log_line", lambda *a, **k: None)
    window.set_session("lfm3-tool", "tool-calls")
    window.start_training()
    qapp.processEvents()
    assert warnings, "the missing-training dialog never showed"
    text = warnings[-1]
    assert "Training is not set up on this PC yet" in text
    assert "Install training" in text
    assert "main screen" in text
    for banned in ("torch", "transformers", "peft", "accelerate",
                   "terminal", "Train panel", "install-training"):
        assert banned not in text, banned
    assert gui_mod is not None


def test_howto_troubleshooting_names_real_buttons():
    """N18: the profile window's real button, the automatic
    lookup first, manual entry last, no typed example repo."""
    from stella.howto import topic_text

    body = topic_text("Troubleshooting")
    flat = " ".join(body.split())
    assert "Download the training files" in flat
    assert "searches Hugging Face itself" in flat
    assert "Only if that search finds nothing" in flat
    assert "LiquidAI/LFM3-1.7B" not in flat
    assert "for example" not in flat


# -- N13: the export gate refusal in the window ------------------------


def test_export_gate_refusal_in_window_is_plain(
    window, seeded, monkeypatch, qapp
):
    seeded.create_profile(
        "seat-tool", ollama_tag="lfm3:1.7b",
        base_ref="LiquidAI/LFM3-1.7B", governing_seat="driver",
    )
    seeded.create_project("seat-tool", "tool-calls")
    window.refresh_tree()
    window.set_session("seat-tool", "tool-calls")
    warnings = []
    monkeypatch.setattr(window, "_warn", warnings.append)
    window.export_gguf_gui()
    qapp.processEvents()
    assert warnings
    text = warnings[-1]
    assert "safety check" in text
    assert "Train the model" in text
    assert "governing seat" not in text
    assert "stella probe" not in text


# -- N14: run.sh -------------------------------------------------------


def test_run_sh_failure_names_the_double_click_first():
    text = (ROOT / "run.sh").read_text()
    assert "Double-click Install Stella" in text
    assert "extracted Stella folder" in text
    # The click action is named before the bash form, which
    # stays only as a secondary line.
    assert text.index("Double-click Install Stella") < text.index(
        "bash install.sh"
    )


# -- N15: uninstall ----------------------------------------------------


def test_uninstall_offers_the_wheel_cache():
    text = (ROOT / "uninstall.sh").read_text()
    assert ".cache/stella/wheels" in text
    assert "wheel cache. Remove it?" in text
    assert "still on this PC" in text
    readme = (ROOT / "README.md").read_text()
    assert ".cache/stella/wheels" in readme


# -- N16: CLI sleep confirms -------------------------------------------


def _seed_cli_sleep(home):
    from tests.test_cli import run_cli

    run_cli(home, "create-profile", "p1", "--tag", "x:1b")
    run_cli(home, "create-project", "p1", "proj")


def _plant_cycle(store_home, cycle=1):
    from stella.model import Store as _Store

    store = _Store(store_home)
    cdir = (
        store.project_dir("p1", "proj") / "sleep" / f"cycle-{cycle}"
    )
    cdir.mkdir(parents=True)
    (cdir / "adapter.bin").write_bytes(b"x" * 2048)
    from stella.sleep import (
        load_sleep_manifest,
        save_sleep_manifest,
    )

    manifest = load_sleep_manifest(store, "p1", "proj")
    manifest["cycles"] = [
        {"cycle": cycle, "status": "OK", "steps": 1,
         "real_rows": 2, "dreamed_rows": 0}
    ]
    save_sleep_manifest(store, "p1", "proj", manifest)
    return cdir


def test_cli_sleep_delete_asks_first_and_no_keeps(home, monkeypatch, capsys):
    _seed_cli_sleep(home)
    monkeypatch.setenv("STELLA_HOME", str(home))
    cdir = _plant_cycle(home)
    monkeypatch.setattr("sys.stdin", io.StringIO("n\n"))
    code = cli_mod.main(["sleep-delete", "p1", "proj", "1"])
    assert code == 1
    assert cdir.is_dir()
    assert "forever" in capsys.readouterr().err


def test_cli_sleep_delete_yes_flag_deletes(home, monkeypatch, capsys):
    _seed_cli_sleep(home)
    monkeypatch.setenv("STELLA_HOME", str(home))
    cdir = _plant_cycle(home)
    monkeypatch.setattr("sys.stdin", io.StringIO("n\n"))
    code = cli_mod.main(["sleep-delete", "p1", "proj", "1", "--yes"])
    assert code == 0
    assert not cdir.exists()


def test_cli_sleep_prune_asks_first(home, monkeypatch, capsys):
    _seed_cli_sleep(home)
    monkeypatch.setenv("STELLA_HOME", str(home))
    cdir1 = _plant_cycle(home, 1)
    _plant_cycle(home, 2)
    # The manifest now lists only cycle 2 (the helper rewrote
    # it); add cycle 1 back so prune has something to doom.
    from stella.model import Store as _Store
    from stella.sleep import load_sleep_manifest, save_sleep_manifest

    store = _Store(home)
    manifest = load_sleep_manifest(store, "p1", "proj")
    manifest["cycles"] = [
        {"cycle": 1, "status": "OK", "steps": 1,
         "real_rows": 2, "dreamed_rows": 0},
        {"cycle": 2, "status": "OK", "steps": 1,
         "real_rows": 2, "dreamed_rows": 0},
    ]
    save_sleep_manifest(store, "p1", "proj", manifest)
    monkeypatch.setattr("sys.stdin", io.StringIO("\n"))
    code = cli_mod.main(["sleep-prune", "p1", "proj", "--keep", "1"])
    assert code == 1
    assert cdir1.is_dir()


# -- N17: sleep with only a tmp checkpoint ------------------------------


def test_sleep_tmp_only_checkpoints_restart_the_cycle(
    need_torch, tmp_path
):
    """A cycle interrupted during its first checkpoint save:
    only a step-N.tmp folder exists. Sleep restarts the cycle's
    training instead of resuming from nothing and refusing."""
    from stella.sleep import sleep_project
    from stella.train import TrainController
    from tests.test_sleep import _tiny_project
    from tests.test_train import tiny_model_and_tokenizer

    store = _tiny_project(Store(tmp_path / "home"), tmp_path, rows=6)
    controller = TrainController()

    def stop_early(event):
        if event.get("type") == "step" and event["step"] >= 1:
            controller.request_stop()

    paused = sleep_project(
        store, "tiny", "proof",
        on_event=stop_early, controller=controller,
        _model_loader=tiny_model_and_tokenizer, _dtype="float32",
    )
    assert paused["status"] == "paused"
    cdir = store.project_dir("tiny", "proof") / "sleep" / "cycle-1"
    ckpts = cdir / "checkpoints"
    # Leave only a crashed save behind.
    import shutil

    for child in list(ckpts.iterdir()):
        if child.is_dir():
            shutil.rmtree(child)
    (ckpts / "step-1.tmp").mkdir()
    report = sleep_project(
        store, "tiny", "proof",
        _model_loader=tiny_model_and_tokenizer, _dtype="float32",
    )
    assert report["cycle"] == 1
    assert report["status"] in ("OK", "DEGRADED")
