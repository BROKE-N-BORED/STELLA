"""GGUF round-trip tests.

The converter path is proven with a fake runner (no llama.cpp in the
sandbox); the missing-llama.cpp error path is tested for real. The
adapter merge runs on a tiny random model when the training stack is
installed and skips cleanly otherwise.
"""
import json
from pathlib import Path

import pytest

from stella.gguf import (
    convert_to_gguf,
    export_gguf,
    find_llama_cpp,
    merge_adapter,
    write_modelfile,
)
from stella.model import StellaError


def fake_llama_cpp(tmp_path):
    """A directory shaped like a llama.cpp checkout. The quantizer
    is executable, as a real build produces (T102)."""
    import os

    d = tmp_path / "llama.cpp"
    (d / "build" / "bin").mkdir(parents=True)
    (d / "convert_hf_to_gguf.py").write_text("# fake converter\n")
    quantize = d / "build" / "bin" / "llama-quantize"
    quantize.write_text("# fake quantizer\n")
    os.chmod(quantize, 0o755)
    return d


def fake_hf_dir(tmp_path):
    d = tmp_path / "merged-hf"
    d.mkdir()
    (d / "config.json").write_text('{"model_type": "gpt2"}\n')
    (d / "model.safetensors").write_bytes(b"fake weights")
    return d


class FakeRunner:
    """Pretends to be convert + quantize: records commands, writes
    the files the real tools would write."""

    def __init__(self):
        self.commands = []

    def __call__(self, cmd):
        self.commands.append(list(cmd))
        if "convert_hf_to_gguf.py" in cmd[1]:
            out = Path(cmd[cmd.index("--outfile") + 1])
            out.write_bytes(b"GGUF-f16-fake")
        elif "llama-quantize" in cmd[0]:
            src, dst = Path(cmd[1]), Path(cmd[2])
            dst.write_bytes(b"GGUF-" + cmd[3].encode() + b"-fake")


def test_find_llama_cpp_missing_names_install(monkeypatch, tmp_path):
    monkeypatch.setenv("LLAMA_CPP_DIR", str(tmp_path / "empty"))
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(StellaError, match="llama.cpp was not found"):
        find_llama_cpp()


def test_find_llama_cpp_found(monkeypatch, tmp_path):
    d = fake_llama_cpp(tmp_path)
    monkeypatch.setenv("LLAMA_CPP_DIR", str(d))
    convert, quantize = find_llama_cpp()
    assert convert == d / "convert_hf_to_gguf.py"
    assert quantize == d / "build" / "bin" / "llama-quantize"


def test_convert_with_fake_runner(tmp_path):
    hf = fake_hf_dir(tmp_path)
    runner = FakeRunner()
    result = convert_to_gguf(
        hf, tmp_path / "model-q4_k_m.gguf", _runner=runner
    )
    assert result["quant"] == "Q4_K_M"
    assert result["bytes"] > 0
    assert Path(result["gguf"]).read_bytes().startswith(b"GGUF-Q4_K_M")
    # Two commands: convert (F16) then quantize.
    assert len(runner.commands) == 2
    assert "--outtype" in runner.commands[0]
    assert runner.commands[0][runner.commands[0].index("--outtype") + 1] == "f16"
    assert runner.commands[1][-1] == "Q4_K_M"


def test_convert_refuses_non_hf_dir(tmp_path):
    with pytest.raises(StellaError, match="no HF model"):
        convert_to_gguf(tmp_path, tmp_path / "x.gguf", _runner=FakeRunner())


def test_write_modelfile(tmp_path):
    gguf = tmp_path / "m.gguf"
    gguf.write_bytes(b"fake")
    modelfile, command = write_modelfile(
        gguf, tmp_path / "Modelfile", name="lfm3-tool-proof"
    )
    text = modelfile.read_text()
    assert text.startswith(f"FROM {gguf.resolve()}")
    assert "PARAMETER temperature 0.7" in text
    assert command == f"ollama create lfm3-tool-proof -f {modelfile}"


def test_merge_adapter_tiny_model(tmp_path):
    pytest.importorskip("torch", reason="training stack not installed")
    from peft import LoraConfig, get_peft_model
    from transformers import GPT2Config, GPT2LMHeadModel

    from test_train import FakeTokenizer, tiny_model_and_tokenizer

    base, tokenizer = tiny_model_and_tokenizer()
    peft_model = get_peft_model(
        base,
        LoraConfig(
            r=2, lora_alpha=4, target_modules=["c_attn", "c_proj"],
            task_type="CAUSAL_LM",
        ),
    )
    adapter_dir = tmp_path / "adapter"
    peft_model.save_pretrained(str(adapter_dir))

    def loader(base_ref, adapter):
        from peft import PeftModel

        fresh, tok = tiny_model_and_tokenizer()
        return PeftModel.from_pretrained(fresh, str(adapter)), tok

    out = merge_adapter(
        "test/tiny-model", adapter_dir, tmp_path / "merged",
        _model_loader=loader, _dtype="float32",
    )
    assert (out / "config.json").is_file()
    assert (out / "model.safetensors").is_file()
    merged_config = json.loads((out / "config.json").read_text())
    assert merged_config["n_layer"] == 2


def test_export_gguf_end_to_end_with_fakes(tmp_path):
    pytest.importorskip("torch", reason="training stack not installed")
    from stella.model import Store

    store = Store(tmp_path / "home")
    store.create_profile("tiny", base_ref="test/tiny-model")
    store.create_project("tiny", "proof")
    project_dir = store.project_dir("tiny", "proof")
    adapter = project_dir / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}\n")

    def loader(base_ref, adapter_dir):
        from test_train import FakeTokenizer, tiny_model_and_tokenizer

        fresh, tok = tiny_model_and_tokenizer()
        # Merge needs a PeftModel; wrap the tiny model without loading
        # the (fake) adapter weights — the merge math is proven by
        # test_merge_adapter_tiny_model above.
        from peft import LoraConfig, get_peft_model

        wrapped = get_peft_model(
            fresh,
            LoraConfig(
                r=2, lora_alpha=4, target_modules=["c_attn", "c_proj"],
                task_type="CAUSAL_LM",
            ),
        )
        return wrapped, tok

    runner = FakeRunner()
    result = export_gguf(
        store, "tiny", "proof", tmp_path / "out",
        _runner=runner, _model_loader=loader, _dtype="float32",
    )
    assert result["quant"] == "Q4_K_M"
    assert result["ollama_name"] == "tiny-proof"
    assert "ollama create tiny-proof -f" in result["ollama_create"]
    assert Path(result["gguf"]).is_file()
    assert Path(result["modelfile"]).is_file()
    record = json.loads((tmp_path / "out" / "gguf-export.json").read_text())
    assert record["profile"] == "tiny"
    assert store.get_project("tiny", "proof")["status"] == "exported"


def test_export_gguf_without_adapter_fails(tmp_path):
    from stella.model import Store

    store = Store(tmp_path / "home")
    store.create_profile("tiny", base_ref="test/tiny-model")
    store.create_project("tiny", "proof")
    with pytest.raises(StellaError, match="no trained adapter"):
        export_gguf(store, "tiny", "proof", tmp_path / "out",
                    _runner=FakeRunner())


# -- T102: the quantizer must be executable at discovery -------------


def test_find_llama_cpp_rejects_non_executable_quantizer(monkeypatch, tmp_path):
    import os

    d = fake_llama_cpp(tmp_path)
    quantize = d / "build" / "bin" / "llama-quantize"
    os.chmod(quantize, 0o644)
    monkeypatch.setenv("LLAMA_CPP_DIR", str(d))
    with pytest.raises(StellaError, match="not executable"):
        find_llama_cpp()
    # The error names the file and the fix.
    try:
        find_llama_cpp()
    except StellaError as exc:
        assert "llama-quantize" in str(exc)
        assert "chmod +x" in str(exc)


def test_find_llama_cpp_prefers_executable_over_plain_file(monkeypatch, tmp_path):
    # A non-executable quantizer in the first candidate dir does not
    # hide an executable one in a later dir.
    import os

    first = fake_llama_cpp(tmp_path / "first")
    os.chmod(first / "build" / "bin" / "llama-quantize", 0o644)
    second = fake_llama_cpp(tmp_path / "second")
    monkeypatch.setenv("LLAMA_CPP_DIR", str(first))
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "llama.cpp").symlink_to(second, target_is_directory=True)
    convert, quantize = find_llama_cpp()
    assert quantize.resolve() == (
        second / "build" / "bin" / "llama-quantize"
    ).resolve()


# -- T27: --quant is validated up front -------------------------------


def test_export_gguf_rejects_bogus_quant_before_merge(tmp_path):
    pytest.importorskip("torch", reason="training stack not installed")
    from stella.model import Store

    store = Store(tmp_path / "home")
    store.create_profile("tiny", base_ref="test/tiny-model")
    store.create_project("tiny", "proof")
    project_dir = store.project_dir("tiny", "proof")
    adapter = project_dir / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}\n")

    def loader(base_ref, adapter_dir):
        raise AssertionError("the merge must not run for a bogus quant")

    with pytest.raises(StellaError, match="not a quant type"):
        export_gguf(
            store, "tiny", "proof", tmp_path / "out",
            quant="BOGUS", _runner=FakeRunner(), _model_loader=loader,
        )
    # Nothing was merged, nothing was written.
    assert not (tmp_path / "out" / "proof-merged-hf").exists()
    assert not list((tmp_path / "out").glob("*.gguf"))


def test_convert_rejects_bogus_quant(tmp_path):
    hf = fake_hf_dir(tmp_path)
    with pytest.raises(StellaError, match="not a quant type"):
        convert_to_gguf(hf, tmp_path / "x.gguf", quant="BOGUS",
                        _runner=FakeRunner())


@pytest.mark.parametrize("quant", ["Q4_K_M", "Q8_0", "F16", "Q5_K_M", "Q2_K"])
def test_convert_accepts_each_valid_quant(tmp_path, quant):
    hf = fake_hf_dir(tmp_path)
    result = convert_to_gguf(
        hf, tmp_path / f"m-{quant.lower()}.gguf", quant=quant,
        _runner=FakeRunner(),
    )
    assert result["quant"] == quant
    assert Path(result["gguf"]).is_file()


def test_export_gguf_accepts_lowercase_quant(tmp_path):
    # validate_quant normalizes: "q4_k_m" is Q4_K_M, not an error.
    hf = fake_hf_dir(tmp_path)
    result = convert_to_gguf(
        hf, tmp_path / "m.gguf", quant="q4_k_m", _runner=FakeRunner()
    )
    assert result["quant"] == "Q4_K_M"


# -- T26: llama.cpp checked before the merge; cleanup on failure ------


def test_export_gguf_missing_llama_cpp_fails_before_merge(monkeypatch, tmp_path):
    # No llama.cpp anywhere and no test runner: the export must fail
    # in a second with the install hint, before any merge — and leave
    # no merged dir behind. No torch needed: the merge never runs.
    from stella.model import Store

    monkeypatch.setenv("LLAMA_CPP_DIR", str(tmp_path / "empty"))
    monkeypatch.setenv("HOME", str(tmp_path))
    store = Store(tmp_path / "home")
    store.create_profile("tiny", base_ref="test/tiny-model")
    store.create_project("tiny", "proof")
    adapter = store.project_dir("tiny", "proof") / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}\n")

    def loader(base_ref, adapter_dir):
        raise AssertionError("the merge must not run without llama.cpp")

    with pytest.raises(StellaError, match="llama.cpp was not found"):
        export_gguf(
            store, "tiny", "proof", tmp_path / "out", _model_loader=loader,
        )
    assert not (tmp_path / "out" / "proof-merged-hf").exists()


class FailingQuantizeRunner(FakeRunner):
    """Convert succeeds, quantize fails — the failed-export shape."""

    def __call__(self, cmd):
        if "llama-quantize" in cmd[0]:
            raise StellaError("quantizer failed (fake)")
        return super().__call__(cmd)


def test_convert_removes_f16_on_quantize_failure(tmp_path):
    hf = fake_hf_dir(tmp_path)
    out = tmp_path / "model-q4_k_m.gguf"
    with pytest.raises(StellaError, match="quantizer failed"):
        convert_to_gguf(hf, out, _runner=FailingQuantizeRunner())
    assert not (tmp_path / "model-q4_k_m-f16.gguf").exists()
    assert not out.exists()


def test_convert_failure_names_f16_cleanup(tmp_path):
    hf = fake_hf_dir(tmp_path)
    try:
        convert_to_gguf(
            hf, tmp_path / "model-q4_k_m.gguf",
            _runner=FailingQuantizeRunner(),
        )
    except StellaError as exc:
        assert "F16 file was removed" in str(exc)
    else:
        raise AssertionError("the failing quantize did not raise")


def test_export_gguf_cleans_merged_dir_on_failure(tmp_path):
    pytest.importorskip("torch", reason="training stack not installed")
    from stella.model import Store

    store = Store(tmp_path / "home")
    store.create_profile("tiny", base_ref="test/tiny-model")
    store.create_project("tiny", "proof")
    project_dir = store.project_dir("tiny", "proof")
    adapter = project_dir / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}\n")

    def loader(base_ref, adapter_dir):
        from test_train import tiny_model_and_tokenizer

        from peft import LoraConfig, get_peft_model

        fresh, tok = tiny_model_and_tokenizer()
        wrapped = get_peft_model(
            fresh,
            LoraConfig(
                r=2, lora_alpha=4, target_modules=["c_attn", "c_proj"],
                task_type="CAUSAL_LM",
            ),
        )
        return wrapped, tok

    with pytest.raises(StellaError, match="quantizer failed"):
        export_gguf(
            store, "tiny", "proof", tmp_path / "out",
            _runner=FailingQuantizeRunner(), _model_loader=loader,
            _dtype="float32",
        )
    # No orphaned merged weights, no F16 intermediate.
    assert not (tmp_path / "out" / "proof-merged-hf").exists()
    assert not list((tmp_path / "out").glob("*-f16.gguf"))
    assert not list((tmp_path / "out").glob("*.gguf"))


# -- T31: the merge RAM guard ----------------------------------------


def test_estimate_merge_bytes_math():
    from stella.gguf import RAM_HEADROOM_BYTES, estimate_merge_bytes

    assert (
        estimate_merge_bytes(3_460_000_000)
        == 2 * 3_460_000_000 + RAM_HEADROOM_BYTES
    )
    assert RAM_HEADROOM_BYTES == 1024**3


def test_check_merge_fit_lfm3_fits():
    from stella.gguf import check_merge_fit

    # LFM3 bf16: 2 x 3.46 GB + 1 GB headroom = 7.92 GB — under the
    # 8 GB ceiling, but only just. It proceeds.
    check_merge_fit(3_460_000_000)


def test_check_merge_fit_refuses_above_ceiling():
    from stella.gguf import check_merge_fit

    with pytest.raises(StellaError, match="over the 8.00 GB ceiling"):
        check_merge_fit(4_000_000_000)
    try:
        check_merge_fit(4_000_000_000)
    except StellaError as exc:
        # The estimate is named, not just the refusal:
        # 2 x 3.73 GiB + 1 GiB headroom = 8.45 GB.
        assert "8.45 GB" in str(exc)
        assert "merged copy" in str(exc)


def test_merge_warnings_tight_export():
    from stella.gguf import merge_warnings

    # LFM3 fits the merge guard (7.92 GB) but merge + converter
    # together pass the ceiling: the user is told to close apps.
    warnings = merge_warnings(3_460_000_000)
    assert len(warnings) == 1
    assert "Close other apps" in warnings[0]
    assert "converter" in warnings[0]
    assert "separate process" in warnings[0]


def test_merge_warnings_small_model_quiet():
    from stella.gguf import merge_warnings

    assert merge_warnings(1_000_000_000) == []


def test_merge_warnings_silent_when_merge_refused():
    from stella.gguf import merge_warnings

    # A model the guard refuses gets no warning on top.
    assert merge_warnings(20_000_000_000) == []


def test_merge_adapter_refuses_before_loading(monkeypatch, tmp_path):
    # A model that cannot fit is refused before anything loads:
    # the loader is booby-trapped, and no torch is needed — the
    # guard runs before the training deps are even required.
    import stella.train as train_mod
    from stella.gguf import merge_adapter

    def fake_metadata(base_ref):
        return {"base_bytes": 20_000_000_000}

    monkeypatch.setattr(train_mod, "load_model_metadata", fake_metadata)
    monkeypatch.setattr(
        train_mod, "load_base_model",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("the base was loaded")
        ),
    )
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}\n")
    with pytest.raises(StellaError, match="Merging needs about"):
        merge_adapter("someone/huge-model", adapter, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_merge_adapter_guard_uses_base_bytes_hook(tmp_path):
    # _base_bytes skips the metadata read entirely (the test seam
    # for the guard itself).
    from stella.gguf import merge_adapter

    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}\n")
    with pytest.raises(StellaError, match="over the 8.00 GB ceiling"):
        merge_adapter(
            "does/not-matter", adapter, tmp_path / "out",
            _base_bytes=20_000_000_000,
        )


def test_export_gguf_warns_before_merge(monkeypatch, tmp_path):
    # End to end with a real (tiny) load: the metadata says the
    # base is LFM3-sized, so the merge fits but the converter
    # warning fires — before the merge runs — and the export
    # still completes.
    pytest.importorskip("torch", reason="training stack not installed")
    import stella.train as train_mod
    from stella.model import Store
    from test_train import prompt_rows, tiny_model_and_tokenizer, write_dataset

    monkeypatch.setattr(
        train_mod, "load_model_metadata",
        lambda base_ref: {"base_bytes": 3_460_000_000},
    )
    base, tokenizer = tiny_model_and_tokenizer()
    model_dir = tmp_path / "tiny-model"
    base.save_pretrained(str(model_dir))
    tokenizer.save_pretrained(str(model_dir))
    store = Store(tmp_path / "home")
    store.create_profile("tiny", base_ref=str(model_dir))
    data = write_dataset(tmp_path / "d.jsonl", prompt_rows(4))
    store.create_project(
        "tiny", "proof",
        dataset_ref=str(data),
        settings={
            "epochs": 1,
            "batch_size": 1,
            "grad_accum": 1,
            "rank": 2,
            "max_seq_len": 128,
            "checkpoint_steps": 0,
            "val_fraction": 0.25,
            "warmup_steps": 1,
            "seed": 42,
        },
    )
    # The real merge needs a real adapter, not just the config:
    # train one first, with the tiny loader.
    from stella.train import train_project

    train_project(
        store, "tiny", "proof",
        _model_loader=tiny_model_and_tokenizer, _dtype="float32",
    )
    seen: list[str] = []
    result = export_gguf(
        store, "tiny", "proof", tmp_path / "out",
        _runner=FakeRunner(), on_warning=seen.append, _dtype="float32",
    )
    assert len(seen) == 1
    assert "Close other apps" in seen[0]
    assert result["warnings"] == seen
    assert Path(result["gguf"]).is_file()


def test_export_gguf_refuses_huge_merge_before_loading(
    monkeypatch, tmp_path
):
    # The guard, through the full export: no torch needed, nothing
    # merged, no merged dir left behind.
    import stella.train as train_mod
    from stella.model import Store

    monkeypatch.setattr(
        train_mod, "load_model_metadata",
        lambda base_ref: {"base_bytes": 20_000_000_000},
    )
    store = Store(tmp_path / "home")
    store.create_profile("big", base_ref="someone/huge-model")
    store.create_project("big", "proof")
    adapter = store.project_dir("big", "proof") / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}\n")
    with pytest.raises(StellaError, match="Merging needs about"):
        export_gguf(store, "big", "proof", tmp_path / "out",
                    _runner=FakeRunner())
    assert not (tmp_path / "out" / "proof-merged-hf").exists()


# -- T24: an export never deletes the previous GGUF silently --------


def _trained_project(tmp_path):
    """A store with a trained project (fake adapter + tiny loader),
    ready for export_gguf with the fake runner."""
    pytest.importorskip("torch", reason="training stack not installed")
    from stella.model import Store

    store = Store(tmp_path / "home")
    store.create_profile("tiny", base_ref="test/tiny-model")
    store.create_project("tiny", "proof")
    adapter = store.project_dir("tiny", "proof") / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}\n")
    return store


def _tiny_loader(base_ref, adapter_dir):
    from test_train import tiny_model_and_tokenizer

    from peft import LoraConfig, get_peft_model

    fresh, tok = tiny_model_and_tokenizer()
    wrapped = get_peft_model(
        fresh,
        LoraConfig(
            r=2, lora_alpha=4, target_modules=["c_attn", "c_proj"],
            task_type="CAUSAL_LM",
        ),
    )
    return wrapped, tok


def test_export_gguf_second_run_refuses_without_force(tmp_path):
    store = _trained_project(tmp_path)
    first = export_gguf(
        store, "tiny", "proof", tmp_path / "out",
        _runner=FakeRunner(), _model_loader=_tiny_loader,
        _dtype="float32",
    )
    gguf = Path(first["gguf"])
    original = gguf.read_bytes()
    assert original == b"GGUF-Q4_K_M-fake"
    with pytest.raises(StellaError, match="--force"):
        export_gguf(
            store, "tiny", "proof", tmp_path / "out",
            _runner=FakeRunner(), _model_loader=_tiny_loader,
            _dtype="float32",
        )
    # The first file is untouched, byte for byte.
    assert gguf.read_bytes() == original


def test_export_gguf_force_overwrites(tmp_path):
    store = _trained_project(tmp_path)
    first = export_gguf(
        store, "tiny", "proof", tmp_path / "out",
        _runner=FakeRunner(), _model_loader=_tiny_loader,
        _dtype="float32",
    )
    gguf = Path(first["gguf"])
    gguf.write_bytes(b"the previous export, precious")
    second = export_gguf(
        store, "tiny", "proof", tmp_path / "out", force=True,
        _runner=FakeRunner(), _model_loader=_tiny_loader,
        _dtype="float32",
    )
    assert Path(second["gguf"]) == gguf
    assert gguf.read_bytes() == b"GGUF-Q4_K_M-fake"


def test_export_gguf_refusal_happens_before_merge(tmp_path):
    # The refusal is cheap: the loader is booby-trapped, so a
    # merge attempt would explode instead of raising the refusal.
    # No torch needed — nothing loads.
    from stella.model import Store

    store = Store(tmp_path / "home")
    store.create_profile("tiny", base_ref="test/tiny-model")
    store.create_project("tiny", "proof")
    adapter = store.project_dir("tiny", "proof") / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}\n")
    out = tmp_path / "out"
    out.mkdir()
    (out / "proof-q4-k-m.gguf").write_bytes(b"previous export")

    def loader(base_ref, adapter_dir):
        raise AssertionError("the merge must not run for a refusal")

    with pytest.raises(StellaError, match="already exists"):
        export_gguf(
            store, "tiny", "proof", out,
            _runner=FakeRunner(), _model_loader=loader,
        )
    assert (out / "proof-q4-k-m.gguf").read_bytes() == b"previous export"


# -- T74: cancel + phase events ---------------------------------------


def test_run_kills_process_on_cancel():
    """A long converter run is killed when the flag flips — the job
    card's Cancel does not wait for the converter to finish."""
    import threading
    import time

    from stella.gguf import _run

    state = {"stop": False}

    def should_stop():
        return state["stop"]

    threading.Timer(0.5, lambda: state.update(stop=True)).start()
    started = time.monotonic()
    with pytest.raises(StellaError, match="Cancelled"):
        _run(["sleep", "30"], should_stop=should_stop)
    assert time.monotonic() - started < 10


def test_convert_emits_phase_events(tmp_path):
    hf = fake_hf_dir(tmp_path)
    events = []
    convert_to_gguf(
        hf, tmp_path / "model-q4_k_m.gguf",
        _runner=FakeRunner(), on_event=events.append,
    )
    assert [e["phase"] for e in events] == ["convert", "quantize"]
    assert all(e["type"] == "phase" for e in events)
    assert "Converting" in events[0]["message"]
    assert "Q4_K_M" in events[1]["message"]


def test_convert_cancel_between_steps(tmp_path):
    class CancellingRunner(FakeRunner):
        """Cancels after the first command finishes."""

        def __init__(self, state):
            super().__init__()
            self.state = state

        def __call__(self, cmd):
            super().__call__(cmd)
            self.state["stop"] = True

    hf = fake_hf_dir(tmp_path)
    state = {"stop": False}
    runner = CancellingRunner(state)
    with pytest.raises(StellaError, match="Cancelled"):
        convert_to_gguf(
            hf, tmp_path / "model-q4_k_m.gguf",
            _runner=runner, should_stop=lambda: state["stop"],
        )
    # Only the convert ran; the quantize never started.
    assert len(runner.commands) == 1
