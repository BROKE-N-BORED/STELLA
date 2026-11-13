"""Sleep phase tests (Item 4).

Pure-Python checks (manifest, hashing, dreaming against a fake
Ollama server, export/import round-trip) run on any install. The
consolidation + replay checks run a real LoRA cycle on a tiny
random model and skip cleanly without the training stack.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from stella.model import StellaError, Store
from stella.sleep import (
    dream_rows,
    list_sleep_cycles,
    load_sleep_manifest,
    replay_check,
    row_hash,
    save_sleep_manifest,
    sleep_project,
    sleep_status,
)
from stella.train import load_dataset

from tests.test_train import (
    FakeTokenizer,
    prompt_rows,
    tiny_model_and_tokenizer,
    write_dataset,
)


def _tiny_project(store, tmp_path, rows=6):
    store.create_profile(
        "tiny", ollama_tag="", role="test", base_ref="test/tiny-model"
    )
    data = write_dataset(tmp_path / "tiny.jsonl", prompt_rows(rows))
    store.create_project(
        "tiny", "proof",
        dataset_ref=str(data),
        settings={
            "epochs": 1,
            "batch_size": 1,
            "grad_accum": 1,
            "rank": 2,
            "max_seq_len": 64,
            "checkpoint_steps": 1,
            "val_fraction": 0.25,
            "warmup_steps": 1,
            "seed": 42,
        },
    )
    return store


def _fake_adapter(project_dir):
    """A cycle adapter dir with the files replay needs to see."""
    adapter = project_dir / "adapter"
    adapter.mkdir(parents=True, exist_ok=True)
    (adapter / "adapter_config.json").write_text("{}\n")
    return adapter


# -- hashing + manifest (no torch) ----------------------------------

def test_row_hash_stable_and_content_based():
    ex = {"messages": [{"role": "user", "content": "hi"},
                       {"role": "assistant", "content": "hello"}]}
    assert row_hash(ex) == row_hash(dict(ex))
    other = {"messages": [{"role": "user", "content": "hi"},
                          {"role": "assistant", "content": "goodbye"}]}
    assert row_hash(ex) != row_hash(other)
    assert len(row_hash(ex)) == 64  # sha256 hex


def test_sleep_manifest_round_trip(tmp_path):
    store = Store(tmp_path / "home")
    store.create_profile("p")
    store.create_project("p", "proj")
    manifest = load_sleep_manifest(store, "p", "proj")
    assert manifest["slept_hashes"] == []
    assert manifest["cycles"] == []
    manifest["slept_hashes"] = ["abc"]
    manifest["cycles"] = [{"cycle": 1, "status": "OK"}]
    save_sleep_manifest(store, "p", "proj", manifest)
    again = load_sleep_manifest(store, "p", "proj")
    assert again["slept_hashes"] == ["abc"]
    assert again["cycles"][0]["cycle"] == 1


def test_manifest_reconciles_orphan_report(tmp_path):
    # A cycle dir with a report.json but no manifest entry (a crash
    # between the report write and the manifest update) heals itself.
    store = Store(tmp_path / "home")
    store.create_profile("p")
    store.create_project("p", "proj")
    cdir = store.project_dir("p", "proj") / "sleep" / "cycle-1"
    cdir.mkdir(parents=True)
    (cdir / "report.json").write_text(json.dumps({
        "cycle": 1, "status": "OK", "timestamp": "2026-11-13T00:00:00",
        "real_rows": 4, "dreamed_rows": 0, "steps": 3,
        "old_loss_before": None, "old_loss_after": None, "new_loss": 1.5,
    }))
    manifest = load_sleep_manifest(store, "p", "proj")
    assert len(manifest["cycles"]) == 1
    assert manifest["cycles"][0]["cycle"] == 1
    assert manifest["cycles"][0]["new_loss"] == 1.5


def test_sleep_status_counts_unslept(tmp_path):
    store = _tiny_project(Store(tmp_path / "home"), tmp_path, rows=6)
    status = sleep_status(store, "tiny", "proof")
    assert status["cycles"] == []
    assert status["total_rows"] == 6
    assert status["unslept_rows"] == 6
    assert status["slept_rows"] == 0
    # Mark 4 rows slept; the count follows.
    examples, _ = load_dataset(tmp_path / "tiny.jsonl")
    manifest = load_sleep_manifest(store, "tiny", "proof")
    manifest["slept_hashes"] = [row_hash(ex) for ex in examples[:4]]
    save_sleep_manifest(store, "tiny", "proof", manifest)
    status = sleep_status(store, "tiny", "proof")
    assert status["slept_rows"] == 4
    assert status["unslept_rows"] == 2


def test_sleep_status_no_dataset(tmp_path):
    store = Store(tmp_path / "home")
    store.create_profile("p")
    store.create_project("p", "proj")
    status = sleep_status(store, "p", "proj")
    assert status["total_rows"] is None
    assert status["unslept_rows"] is None


def test_sleep_no_new_rows_raises(tmp_path):
    store = _tiny_project(Store(tmp_path / "home"), tmp_path, rows=4)
    examples, _ = load_dataset(tmp_path / "tiny.jsonl")
    manifest = load_sleep_manifest(store, "tiny", "proof")
    manifest["slept_hashes"] = [row_hash(ex) for ex in examples]
    save_sleep_manifest(store, "tiny", "proof", manifest)
    with pytest.raises(StellaError, match="No new rows"):
        sleep_project(store, "tiny", "proof", _model_loader=tiny_model_and_tokenizer)


def test_sleep_needs_two_rows(tmp_path):
    store = _tiny_project(Store(tmp_path / "home"), tmp_path, rows=4)
    examples, _ = load_dataset(tmp_path / "tiny.jsonl")
    manifest = load_sleep_manifest(store, "tiny", "proof")
    manifest["slept_hashes"] = [row_hash(ex) for ex in examples[:3]]
    save_sleep_manifest(store, "tiny", "proof", manifest)
    with pytest.raises(StellaError, match="at least 2 rows"):
        sleep_project(store, "tiny", "proof", _model_loader=tiny_model_and_tokenizer)


# -- dreaming (no torch) --------------------------------------------

DREAMED_VALID = [
    {"messages": [{"role": "user", "content": "What is 2+2?"},
                  {"role": "assistant", "content": "4."}]},
    {"messages": [{"role": "user", "content": "Capital of Spain?"},
                  {"role": "assistant", "content": "Madrid."}]},
]


class DreamOllama(BaseHTTPRequestHandler):
    """Fake Ollama: /api/generate returns canned rows — valid, bad
    JSON, an invalid row, and a duplicate of a seed."""

    RESPONSE_LINES = None  # set per test via the server attribute

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        lines = self.server.response_lines
        body = json.dumps({"response": "\n".join(lines)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _dream_server(lines):
    server = ThreadingHTTPServer(("127.0.0.1", 0), DreamOllama)
    server.response_lines = lines
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _seed_examples():
    return [
        {"messages": [{"role": "user", "content": "Question 0?"},
                      {"role": "assistant", "content": "Answer 0."}]},
        {"messages": [{"role": "user", "content": "Question 1?"},
                      {"role": "assistant", "content": "Answer 1."}]},
    ]


def test_dream_rows_filters_and_dedupes():
    seeds = _seed_examples()
    lines = [
        json.dumps(DREAMED_VALID[0]),
        "not json at all",
        json.dumps({"messages": [{"role": "robot", "content": "x"},
                                 {"role": "assistant", "content": "y"}]}),
        json.dumps(DREAMED_VALID[1]),
        json.dumps(seeds[0]),  # duplicate of a seed row
        "```",
    ]
    server = _dream_server(lines)
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        rows, reason = dream_rows(
            seeds, model_tag="tiny:1b", count=5,
            exclude_hashes={row_hash(ex) for ex in seeds},
            ollama_url=url,
        )
    finally:
        server.shutdown()
        server.server_close()
    assert reason is None
    assert len(rows) == 2
    assert rows[0]["messages"][-1]["content"] == "4."
    assert rows[1]["messages"][-1]["content"] == "Madrid."


def test_dream_rows_respects_cap():
    lines = [json.dumps({
        "messages": [{"role": "user", "content": f"Q{i}?"},
                     {"role": "assistant", "content": f"A{i}."}]})
        for i in range(6)]
    server = _dream_server(lines)
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        rows, _ = dream_rows(
            _seed_examples(), model_tag="tiny:1b", count=2, ollama_url=url
        )
    finally:
        server.shutdown()
        server.server_close()
    assert len(rows) == 2


def test_dream_rows_ollama_down_returns_skip():
    # Nothing listens on this port — a skip, never a raise.
    rows, reason = dream_rows(
        _seed_examples(), model_tag="tiny:1b", count=3,
        ollama_url="http://127.0.0.1:9",
    )
    assert rows == []
    assert reason is not None
    assert "skipped" in reason


def test_dream_rows_no_tag_returns_skip():
    rows, reason = dream_rows(_seed_examples(), model_tag="", count=3)
    assert rows == []
    assert "no Ollama model tag" in reason


# -- export / import round-trip of sleep cycles (no torch) ----------

def test_export_import_round_trip_sleep_cycles(tmp_path):
    from stella import export as export_mod

    store = Store(tmp_path / "home")
    store.create_profile("p", ollama_tag="x:1b", role="fast")
    store.create_project("p", "proj")
    # A finished cycle, as sleep would leave it.
    sdir = store.project_dir("p", "proj") / "sleep"
    cdir = sdir / "cycle-1"
    (cdir / "adapter").mkdir(parents=True)
    (cdir / "adapter" / "adapter_config.json").write_text('{"r": 4}\n')
    (cdir / "adapter" / "adapter_model.safetensors").write_bytes(b"fake-weights")
    (cdir / "report.json").write_text(json.dumps({
        "cycle": 1, "status": "OK", "timestamp": "2026-11-13T00:00:00",
        "real_rows": 4, "dreamed_rows": 2, "steps": 3,
        "old_loss_before": None, "old_loss_after": None, "new_loss": 1.5,
    }))
    (cdir / "train_rows.jsonl").write_text('{"messages": []}\n')
    manifest = load_sleep_manifest(store, "p", "proj")
    manifest["slept_hashes"] = ["a1", "b2"]
    manifest["dreamed_hashes"] = ["d1"]
    manifest["cycles"] = [{
        "cycle": 1, "status": "OK", "timestamp": "2026-11-13T00:00:00",
        "real_rows": 4, "dreamed_rows": 2, "steps": 3,
        "old_loss_before": None, "old_loss_after": None, "new_loss": 1.5,
    }]
    save_sleep_manifest(store, "p", "proj", manifest)

    out = export_mod.export_project(store, "p", "proj", tmp_path)
    assert (out / "sleep" / "manifest.json").is_file()
    assert (out / "sleep" / "cycle-1" / "adapter" / "adapter_config.json").is_file()

    fresh = Store(tmp_path / "fresh-home")
    export_mod.import_export(fresh, out)
    imported = load_sleep_manifest(fresh, "p", "proj")
    assert imported["slept_hashes"] == ["a1", "b2"]
    assert imported["dreamed_hashes"] == ["d1"]
    assert len(imported["cycles"]) == 1
    assert imported["cycles"][0]["status"] == "OK"
    adapter = (
        fresh.project_dir("p", "proj") / "sleep" / "cycle-1"
        / "adapter" / "adapter_model.safetensors"
    )
    assert adapter.read_bytes() == b"fake-weights"
    assert sleep_status(fresh, "p", "proj")["cycles"][0]["cycle"] == 1


# -- the real cycle on a tiny model (needs the training stack) ------

@pytest.fixture()
def need_torch():
    return pytest.importorskip("torch", reason="training stack not installed")


def test_sleep_cycle_end_to_end_tiny(need_torch, tmp_path):
    store = _tiny_project(Store(tmp_path / "home"), tmp_path, rows=6)
    events = []
    report = sleep_project(
        store, "tiny", "proof",
        on_event=events.append,
        _model_loader=tiny_model_and_tokenizer,
        _dtype="float32",
    )
    assert report["cycle"] == 1
    assert report["status"] in ("OK", "DEGRADED")
    assert report["real_rows"] == 6
    assert report["dreamed_rows"] == 0
    assert report["steps"] > 0
    assert report["rank"] == 2
    # Cycle 1 has no old rows: old losses are None, never faked.
    assert report["old_loss_before"] is None
    assert report["old_loss_after"] is None
    assert report["new_loss"] is not None
    cdir = store.project_dir("tiny", "proof") / "sleep" / "cycle-1"
    assert (cdir / "adapter" / "adapter_config.json").is_file()
    assert (cdir / "report.json").is_file()
    assert (cdir / "train_rows.jsonl").is_file()
    assert (cdir / "val_rows.jsonl").is_file()
    manifest = load_sleep_manifest(store, "tiny", "proof")
    assert len(manifest["slept_hashes"]) == 6
    assert len(manifest["cycles"]) == 1
    assert manifest["old_val_rows"], "val rows banked for the next cycle"
    # Sleep leaves the project status alone (not a retrain).
    assert store.get_project("tiny", "proof")["status"] == "draft"
    kinds = {e["type"] for e in events}
    assert {"started", "step", "replay", "replay_done", "done"} <= kinds


def test_sleep_second_cycle_replays_against_old(need_torch, tmp_path):
    store = _tiny_project(Store(tmp_path / "home"), tmp_path, rows=6)
    sleep_project(
        store, "tiny", "proof",
        _model_loader=tiny_model_and_tokenizer, _dtype="float32",
    )
    # Four brand-new rows join the dataset.
    data_path = tmp_path / "tiny.jsonl"
    with data_path.open("a", encoding="utf-8") as fh:
        for i in range(6, 10):
            fh.write(json.dumps(
                {"prompt": f"Question {i}?", "completion": f"Answer {i}."}
            ) + "\n")
    report = sleep_project(
        store, "tiny", "proof",
        _model_loader=tiny_model_and_tokenizer, _dtype="float32",
    )
    assert report["cycle"] == 2
    assert report["real_rows"] == 4
    # Cycle 2 has old val rows from cycle 1: the replay ran for real.
    assert report["old_loss_before"] is not None
    assert report["old_loss_after"] is not None
    assert report["old_delta_relative"] is not None
    assert len(list_sleep_cycles(store, "tiny", "proof")) == 2
    manifest = load_sleep_manifest(store, "tiny", "proof")
    assert len(manifest["slept_hashes"]) == 10


def test_sleep_with_dream_fake_ollama(need_torch, tmp_path):
    store = _tiny_project(Store(tmp_path / "home"), tmp_path, rows=6)
    lines = [json.dumps(r) for r in DREAMED_VALID]
    server = _dream_server(lines)
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        report = sleep_project(
            store, "tiny", "proof",
            dream=True, dream_model="tiny:1b",
            _model_loader=tiny_model_and_tokenizer, _dtype="float32",
            _ollama_url=url,
        )
    finally:
        server.shutdown()
        server.server_close()
    assert report["dreamed_rows"] == 2
    manifest = load_sleep_manifest(store, "tiny", "proof")
    assert len(manifest["dreamed_hashes"]) == 2
    # Only real rows count as slept — dreamed rows never mark
    # themselves slept.
    assert len(manifest["slept_hashes"]) == 6


def test_sleep_dream_ollama_down_still_sleeps(need_torch, tmp_path):
    store = _tiny_project(Store(tmp_path / "home"), tmp_path, rows=6)
    events = []
    report = sleep_project(
        store, "tiny", "proof",
        dream=True, dream_model="tiny:1b",
        on_event=events.append,
        _model_loader=tiny_model_and_tokenizer, _dtype="float32",
        _ollama_url="http://127.0.0.1:9",
    )
    assert report["cycle"] == 1
    assert report["dreamed_rows"] == 0
    skipped = [e for e in events if e["type"] == "dream_skipped"]
    assert len(skipped) == 1
    assert "unreachable" in skipped[0]["reason"]


def test_replay_verdict_with_canned_eval(need_torch, tmp_path, monkeypatch):
    import stella.train as train_mod

    store = _tiny_project(Store(tmp_path / "home"), tmp_path, rows=6)
    sleep_project(
        store, "tiny", "proof",
        _model_loader=tiny_model_and_tokenizer, _dtype="float32",
    )
    cdir = store.project_dir("tiny", "proof") / "sleep" / "cycle-1"
    old_val = [{"messages": [{"role": "user", "content": "Q?"},
                             {"role": "assistant", "content": "A."}]}]
    new_val = list(old_val)

    def canned(losses):
        it = iter(losses)

        def fake(model, tokenizer, examples, **kwargs):
            if not examples:
                return None
            return next(it)

        return fake

    # Old loss 1.0 -> 1.5 (+50%): DEGRADED at the 10% threshold.
    monkeypatch.setattr(train_mod, "evaluate_loss", canned([1.0, 1.5, 0.9]))
    result = replay_check(
        store, "tiny", "proof", cdir, old_val, new_val,
        _model_loader=tiny_model_and_tokenizer, _dtype="float32",
        max_seq_len=64,
    )
    assert result["status"] == "DEGRADED"
    assert result["old_delta_relative"] == pytest.approx(0.5)

    # Old loss 1.0 -> 0.9 (-10%): OK.
    monkeypatch.setattr(train_mod, "evaluate_loss", canned([1.0, 0.9, 0.8]))
    result = replay_check(
        store, "tiny", "proof", cdir, old_val, new_val,
        _model_loader=tiny_model_and_tokenizer, _dtype="float32",
        max_seq_len=64,
    )
    assert result["status"] == "OK"

    # Boundary: exactly +10% at a 0.10 threshold is NOT degraded
    # (the rule is "rises MORE than the threshold").
    monkeypatch.setattr(train_mod, "evaluate_loss", canned([1.0, 1.10, 0.8]))
    result = replay_check(
        store, "tiny", "proof", cdir, old_val, new_val,
        threshold=0.10,
        _model_loader=tiny_model_and_tokenizer, _dtype="float32",
        max_seq_len=64,
    )
    assert result["status"] == "OK"


def test_replay_check_loads_once(need_torch, tmp_path):
    store = _tiny_project(Store(tmp_path / "home"), tmp_path, rows=6)
    sleep_project(
        store, "tiny", "proof",
        _model_loader=tiny_model_and_tokenizer, _dtype="float32",
    )
    cdir = store.project_dir("tiny", "proof") / "sleep" / "cycle-1"
    calls = {"n": 0}

    def counting_loader():
        calls["n"] += 1
        return tiny_model_and_tokenizer()

    old_val = [{"messages": [{"role": "user", "content": "Q?"},
                             {"role": "assistant", "content": "A."}]}]
    replay_check(
        store, "tiny", "proof", cdir, old_val, old_val,
        _model_loader=counting_loader, _dtype="float32", max_seq_len=64,
    )
    # The probe's double-load bug would show up as 2 here.
    assert calls["n"] == 1


def test_sleep_loads_twice_total(need_torch, tmp_path):
    store = _tiny_project(Store(tmp_path / "home"), tmp_path, rows=6)
    calls = {"n": 0}

    def counting_loader():
        calls["n"] += 1
        return tiny_model_and_tokenizer()

    sleep_project(
        store, "tiny", "proof",
        _model_loader=counting_loader, _dtype="float32",
    )
    # One load to consolidate, one load for the replay check — the
    # replay must not double-load (that would be 3).
    assert calls["n"] == 2


def test_sleep_rank_capped_at_8(need_torch, tmp_path):
    store = _tiny_project(Store(tmp_path / "home"), tmp_path, rows=6)
    store.update_project("tiny", "proof", settings={"rank": 16})
    report = sleep_project(
        store, "tiny", "proof",
        _model_loader=tiny_model_and_tokenizer, _dtype="float32",
    )
    assert report["rank"] == 8
    config = json.loads(
        (store.project_dir("tiny", "proof") / "sleep" / "cycle-1"
         / "adapter" / "adapter_config.json").read_text()
    )
    assert config["r"] == 8
    # The stored project setting is untouched by the cap.
    assert store.get_project("tiny", "proof")["settings"]["rank"] == 16


def test_sleep_ram_guard_refuses(need_torch, tmp_path):
    store = _tiny_project(Store(tmp_path / "home"), tmp_path, rows=6)
    store.update_project(
        "tiny", "proof", settings={"max_seq_len": 3_000_000}
    )
    with pytest.raises(StellaError, match="over the 8.00 GB ceiling"):
        sleep_project(
            store, "tiny", "proof",
            _model_loader=tiny_model_and_tokenizer, _dtype="float32",
        )


def test_sleep_pause_then_resume_completes(need_torch, tmp_path):
    from stella.train import TrainController

    store = _tiny_project(Store(tmp_path / "home"), tmp_path, rows=6)
    controller = TrainController()

    def stop_after_first_step(event):
        if event.get("type") == "step" and event["step"] >= 1:
            controller.request_stop()

    paused = sleep_project(
        store, "tiny", "proof",
        on_event=stop_after_first_step,
        controller=controller,
        _model_loader=tiny_model_and_tokenizer, _dtype="float32",
    )
    assert paused["status"] == "paused"
    assert paused["cycle"] == 1
    cdir = store.project_dir("tiny", "proof") / "sleep" / "cycle-1"
    assert (cdir / "train_rows.jsonl").is_file()
    assert not (cdir / "report.json").is_file()
    assert list_sleep_cycles(store, "tiny", "proof") == []
    # Nothing is marked slept until the cycle finishes.
    assert load_sleep_manifest(store, "tiny", "proof")["slept_hashes"] == []

    report = sleep_project(
        store, "tiny", "proof",
        _model_loader=tiny_model_and_tokenizer, _dtype="float32",
    )
    assert report["cycle"] == 1  # resumed the same cycle, not a new one
    assert report["status"] in ("OK", "DEGRADED")
    assert (cdir / "adapter" / "adapter_config.json").is_file()
    assert len(list_sleep_cycles(store, "tiny", "proof")) == 1
    assert len(load_sleep_manifest(store, "tiny", "proof")["slept_hashes"]) == 6


def test_sleep_partial_cycle_dir_self_heals(need_torch, tmp_path):
    # A crash between the three sequential writes of the fresh-cycle
    # path leaves a partial cycle dir (train rows only, no val rows,
    # no cycle_input). Sleep must NOT crash on it with a raw
    # traceback — the partial dir is ignored and the fresh cycle
    # reuses its number and overwrites it.
    store = _tiny_project(Store(tmp_path / "home"), tmp_path, rows=6)
    cdir = store.project_dir("tiny", "proof") / "sleep" / "cycle-1"
    cdir.mkdir(parents=True)
    (cdir / "train_rows.jsonl").write_text(
        '{"messages": [{"role": "user", "content": "Q?"}, '
        '{"role": "assistant", "content": "A."}]}\n'
    )
    report = sleep_project(
        store, "tiny", "proof",
        _model_loader=tiny_model_and_tokenizer, _dtype="float32",
    )
    assert report["cycle"] == 1
    assert report["status"] in ("OK", "DEGRADED")
    assert report["real_rows"] == 6
    assert (cdir / "cycle_input.json").is_file()
    assert (cdir / "val_rows.jsonl").is_file()
    assert (cdir / "report.json").is_file()


def test_sleep_corrupt_cycle_input_is_a_plain_error(need_torch, tmp_path):
    # All three input files present, but cycle_input.json is not
    # valid JSON: a plain StellaError naming the cycle, never a raw
    # traceback (the CLI only catches StellaError).
    store = _tiny_project(Store(tmp_path / "home"), tmp_path, rows=6)
    cdir = store.project_dir("tiny", "proof") / "sleep" / "cycle-1"
    cdir.mkdir(parents=True)
    row = (
        '{"messages": [{"role": "user", "content": "Q?"}, '
        '{"role": "assistant", "content": "A."}]}\n'
    )
    (cdir / "train_rows.jsonl").write_text(row)
    (cdir / "val_rows.jsonl").write_text(row)
    (cdir / "cycle_input.json").write_text("{not json\n")
    with pytest.raises(StellaError, match="cycle 1.*damaged"):
        sleep_project(
            store, "tiny", "proof",
            _model_loader=tiny_model_and_tokenizer, _dtype="float32",
        )
