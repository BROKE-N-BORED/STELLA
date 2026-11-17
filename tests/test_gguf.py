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
    is_vision_architecture,
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


# -- R5: vision models refuse, in plain words ------------------------


@pytest.mark.parametrize("arch", [
    "Qwen2_5_VLForConditionalGeneration",
    "Qwen2VLForConditionalGeneration",
    "Qwen3VLForConditionalGeneration",
    "LlavaForConditionalGeneration",
    "Gemma3ForConditionalGeneration",
    "Llama4ForConditionalGeneration",
    "Idefics3ForConditionalGeneration",
    "PaliGemmaForConditionalGeneration",
    "MiniCPMV",
    "Moondream2ForConditionalGeneration",
])
def test_is_vision_architecture_spots_vision_models(arch):
    assert is_vision_architecture(arch) is True


@pytest.mark.parametrize("arch", [
    "LlamaForCausalLM",
    "Qwen2ForCausalLM",
    "GPT2LMHeadModel",
    "GemmaForCausalLM",
    "MistralForCausalLM",
    "Lfm2ForCausalLM",
    "",
])
def test_is_vision_architecture_leaves_text_models_alone(arch):
    assert is_vision_architecture(arch) is False


def test_is_vision_architecture_flags_any_vl_name():
    # The "VL" marker is deliberately broad: no real text-only
    # architecture carries "VL" in its name, so flagging one is
    # the safe direction (a refusal, not a lost-vision export).
    assert is_vision_architecture("Qwen2_5_VLForCausalLM") is True


def test_export_gguf_refuses_vision_base(tmp_path):
    # R5: a vision base refuses before the merge starts — the
    # loader is never called, so no merge is attempted and no
    # half-finished weights are left behind.
    from stella.model import Store

    store = Store(tmp_path / "home")
    store.create_profile("vl", base_ref="Qwen/Qwen2.5-VL-3B-Instruct")
    store.create_project("vl", "proof")
    adapter = store.project_dir("vl", "proof") / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}\n")

    def never_called(base_ref, adapter_dir):
        raise AssertionError("the merge must not start for a VL base")

    with pytest.raises(StellaError, match="can see pictures"):
        export_gguf(
            store, "vl", "proof", tmp_path / "out",
            _runner=FakeRunner(), _model_loader=never_called,
            _base_arch="Qwen2_5_VLForConditionalGeneration",
        )
    assert not (tmp_path / "out" / "proof-merged-hf").exists()


# -- R3: sleep adapters export through the same GGUF path -------------


def _sleep_project(tmp_path, cycle=2):
    """A project with a finished sleep cycle adapter (and no
    trained adapter, so a plain export would refuse)."""
    from stella.model import Store

    store = Store(tmp_path / "home")
    store.create_profile("tiny", base_ref="test/tiny-model")
    store.create_project("tiny", "proof")
    adapter = (
        store.project_dir("tiny", "proof")
        / "sleep" / f"cycle-{cycle}" / "adapter"
    )
    adapter.mkdir(parents=True)
    (adapter / "adapter_config.json").write_text("{}\n")
    return store, adapter


class _StubModel:
    """A torch-free stand-in for a merged model: records what the
    merge was asked to save."""

    def merge_and_unload(self):
        return self

    def save_pretrained(self, out_dir):
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "config.json").write_text(
            '{"model_type": "gpt2"}\n'
        )
        (out / "model.safetensors").write_bytes(b"stub weights")


class _StubTokenizer:
    def save_pretrained(self, out_dir):
        Path(out_dir, "tokenizer_config.json").write_text("{}\n")


def test_export_gguf_from_sleep_uses_cycle_adapter(monkeypatch, tmp_path):
    # R3: --from-sleep N merges the sleep cycle's adapter, not the
    # trained one — the loader receives the cycle's adapter dir,
    # and the record names the cycle. Torch-free: the loader and
    # the training-deps check are stubbed (this pins the adapter
    # resolution, not the merge).
    import stella.train

    store, adapter = _sleep_project(tmp_path)
    seen = {}
    monkeypatch.setattr(
        stella.train, "require_training_deps", lambda: None
    )

    def stub_loader(base_ref, adapter_dir):
        seen["adapter_dir"] = Path(adapter_dir)
        return _StubModel(), _StubTokenizer()

    result = export_gguf(
        store, "tiny", "proof", tmp_path / "out",
        from_sleep=2, _runner=FakeRunner(), _model_loader=stub_loader,
        _base_arch="GPT2LMHeadModel",
    )
    assert seen["adapter_dir"] == adapter
    assert Path(result["gguf"]).read_bytes() == b"GGUF-Q4_K_M-fake"
    record = json.loads(
        (tmp_path / "out" / "gguf-export.json").read_text()
    )
    assert record["from_sleep"] == 2
    assert record["adapter"] == str(adapter)


def test_export_gguf_from_sleep_missing_cycle_refuses(tmp_path):
    # R3: a cycle with no adapter on disk refuses before the merge
    # starts — the loader is never called.
    from stella.model import Store

    store = Store(tmp_path / "home")
    store.create_profile("tiny", base_ref="test/tiny-model")
    store.create_project("tiny", "proof")

    def never_called(base_ref, adapter_dir):
        raise AssertionError("the merge must not start")

    with pytest.raises(StellaError, match="no sleep adapter for cycle 3"):
        export_gguf(
            store, "tiny", "proof", tmp_path / "out",
            from_sleep=3, _runner=FakeRunner(),
            _model_loader=never_called,
        )


def test_export_gguf_from_sleep_and_checkpoint_refuses(tmp_path):
    # R3: two adapter sources at once is a plain refusal, not a
    # silent pick of one over the other.
    store, _adapter = _sleep_project(tmp_path)
    with pytest.raises(StellaError, match="pick one adapter"):
        export_gguf(
            store, "tiny", "proof", tmp_path / "out",
            from_sleep=2, from_checkpoint=1,
            _runner=FakeRunner(), _model_loader=lambda a, b: (None, None),
        )


# -- R4: the refusal-probe gate enforced at export -------------------


def _gated_store(tmp_path, *, governing=True, probe=None):
    """A store with a trained adapter and an optional saved probe
    result ('passed', 'failed', or None for no result)."""
    import json

    from stella.model import Store

    store = Store(tmp_path / "home")
    store.create_profile(
        "tiny", base_ref="test/tiny-model",
        role="fast" if governing else "utility",
    )
    store.create_project("tiny", "proof")
    adapter = store.project_dir("tiny", "proof") / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}\n")
    if probe is not None:
        rising = probe == "failed"
        result = {
            "mode": "gate",
            "before": {
                "total": 2, "refusals": 0, "empty": 0, "rate": 0.0,
            },
            "after": {
                "total": 2, "refusals": 1 if rising else 0,
                "empty": 0, "rate": 0.5 if rising else 0.0,
            },
            "delta": 0.5 if rising else 0.0,
        }
        path = (
            store.project_dir("tiny", "proof") / "probe_results.json"
        )
        path.write_text(json.dumps(result), encoding="utf-8")
    return store


def _fake_merge_adapter(base_ref, adapter_dir, merged_dir, **kwargs):
    """A merge that writes a minimal HF dir, no weights needed."""
    merged_dir.mkdir(parents=True, exist_ok=True)
    (merged_dir / "config.json").write_text(
        '{"model_type": "gpt2"}\n'
    )


def test_export_gguf_governing_without_probe_refuses(tmp_path):
    """R4: a governing profile with no probe result cannot export
    — refused before any folder is made or any work starts."""
    store = _gated_store(tmp_path, governing=True, probe=None)
    with pytest.raises(StellaError, match="refusal probe"):
        export_gguf(store, "tiny", "proof", tmp_path / "out",
                    _runner=FakeRunner())
    assert not (tmp_path / "out").exists()


def test_export_gguf_governing_failed_gate_refuses(tmp_path):
    """R4: a governing profile whose probe failed cannot export."""
    store = _gated_store(tmp_path, governing=True, probe="failed")
    with pytest.raises(StellaError, match="did not pass"):
        export_gguf(store, "tiny", "proof", tmp_path / "out",
                    _runner=FakeRunner())
    assert not (tmp_path / "out").exists()


def test_export_gguf_governing_passed_gate_proceeds(
    tmp_path, monkeypatch
):
    """R4: a governing profile with a passed probe exports."""
    import stella.gguf as gguf_mod

    store = _gated_store(tmp_path, governing=True, probe="passed")
    monkeypatch.setattr(gguf_mod, "merge_adapter", _fake_merge_adapter)
    result = export_gguf(
        store, "tiny", "proof", tmp_path / "out",
        _runner=FakeRunner(),
        _model_loader=lambda *a, **k: (None, None),
    )
    assert Path(result["gguf"]).is_file()


def test_export_gguf_non_governing_needs_no_probe(
    tmp_path, monkeypatch
):
    """R4: a non-governing profile exports with no probe result —
    the gate does not apply, and nothing else changed."""
    import stella.gguf as gguf_mod

    store = _gated_store(tmp_path, governing=False, probe=None)
    monkeypatch.setattr(gguf_mod, "merge_adapter", _fake_merge_adapter)
    result = export_gguf(
        store, "tiny", "proof", tmp_path / "out",
        _runner=FakeRunner(),
        _model_loader=lambda *a, **k: (None, None),
    )
    assert Path(result["gguf"]).is_file()


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


# -- T97: LFM3 -> GGUF conversion pre-flight --------------------------


def _fake_converter_dir(tmp_path, archs):
    """A fake llama.cpp checkout whose converter registers the
    given architectures, the way the real convert_hf_to_gguf.py
    does with @Model.register."""
    import os

    d = tmp_path / "llama.cpp"
    (d / "build" / "bin").mkdir(parents=True)
    lines = ["# fake converter"]
    for arch in archs:
        lines.append(f'@Model.register("{arch}")')
        lines.append(f"class {arch}Model: pass")
    (d / "convert_hf_to_gguf.py").write_text("\n".join(lines) + "\n")
    quantize = d / "build" / "bin" / "llama-quantize"
    quantize.write_text("# fake quantizer\n")
    os.chmod(quantize, 0o755)
    return d


def test_converter_supported_archs_parses_registrations(tmp_path):
    from stella.gguf import converter_supported_archs

    d = _fake_converter_dir(
        tmp_path, ["LlamaForCausalLM", "Lfm2ForCausalLM"]
    )
    assert converter_supported_archs(d / "convert_hf_to_gguf.py") == {
        "LlamaForCausalLM", "Lfm2ForCausalLM",
    }


def test_converter_supported_archs_none_when_unparseable(tmp_path):
    from stella.gguf import converter_supported_archs

    d = fake_llama_cpp(tmp_path)
    assert converter_supported_archs(d / "convert_hf_to_gguf.py") is None


def test_check_converter_supports_arch_refuses_unknown(tmp_path):
    from stella.gguf import check_converter_supports_arch

    d = _fake_converter_dir(tmp_path, ["LlamaForCausalLM"])
    convert = d / "convert_hf_to_gguf.py"
    with pytest.raises(StellaError) as excinfo:
        check_converter_supports_arch("WeirdArchForCausalLM", convert)
    # The arch and the converter are both named.
    assert "WeirdArchForCausalLM" in str(excinfo.value)
    assert str(convert) in str(excinfo.value)


def test_check_converter_supports_arch_passes_supported(tmp_path):
    from stella.gguf import check_converter_supports_arch

    d = _fake_converter_dir(tmp_path, ["LlamaForCausalLM"])
    check_converter_supports_arch(
        "LlamaForCausalLM", d / "convert_hf_to_gguf.py"
    )


def _seed_trained_project(store, tmp_path):
    """A project with a (fake) trained adapter, ready to export."""
    store.create_profile("tiny", base_ref="test/tiny-model")
    store.create_project("tiny", "proof")
    adapter = store.project_dir("tiny", "proof") / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}\n")
    return store


class _FakeMergedModel:
    """A merged model that saves a fake HF dir — no torch needed."""

    def merge_and_unload(self):
        return self

    def save_pretrained(self, path):
        Path(path).mkdir(parents=True, exist_ok=True)
        (Path(path) / "config.json").write_text(
            '{"model_type": "llama"}\n'
        )


class _FakeSaveTokenizer:
    def save_pretrained(self, path):
        Path(path).mkdir(parents=True, exist_ok=True)
        (Path(path) / "tokenizer_config.json").write_text("{}\n")


def test_export_gguf_preflight_refuses_unsupported_arch(tmp_path):
    from stella.model import Store

    d = _fake_converter_dir(tmp_path, ["LlamaForCausalLM"])
    store = _seed_trained_project(Store(tmp_path / "home"), tmp_path)

    def loader(base_ref, adapter_dir):
        raise AssertionError("the merge must not run for an unsupported arch")

    with pytest.raises(StellaError) as excinfo:
        export_gguf(
            store, "tiny", "proof", tmp_path / "out",
            _runner=FakeRunner(), _model_loader=loader,
            llama_cpp=(
                d / "convert_hf_to_gguf.py",
                d / "build" / "bin" / "llama-quantize",
            ),
            _base_arch="WeirdArchForCausalLM",
        )
    assert "WeirdArchForCausalLM" in str(excinfo.value)
    assert str(d / "convert_hf_to_gguf.py") in str(excinfo.value)
    # Refused before the merge: no merged dir, no GGUF.
    assert not (tmp_path / "out" / "proof-merged-hf").exists()
    assert not (tmp_path / "out" / "proof-q4-k-m.gguf").exists()


def test_export_gguf_preflight_passes_supported_arch(tmp_path, monkeypatch):
    from stella.model import Store

    # The pre-flight needs no torch; stub the deps gate the merge
    # calls so the test runs on a base install too.
    import stella.train as train_mod

    monkeypatch.setattr(train_mod, "require_training_deps", lambda: None)
    d = _fake_converter_dir(tmp_path, ["LlamaForCausalLM"])
    store = _seed_trained_project(Store(tmp_path / "home"), tmp_path)

    def loader(base_ref, adapter_dir):
        return _FakeMergedModel(), _FakeSaveTokenizer()

    result = export_gguf(
        store, "tiny", "proof", tmp_path / "out",
        _runner=FakeRunner(), _model_loader=loader,
        llama_cpp=(
            d / "convert_hf_to_gguf.py",
            d / "build" / "bin" / "llama-quantize",
        ),
        _base_arch="LlamaForCausalLM",
    )
    assert Path(result["gguf"]).is_file()
    assert (tmp_path / "out" / "proof-merged-hf" / "config.json").is_file()


def test_export_gguf_preflight_passes_when_list_unreadable(
    tmp_path, monkeypatch
):
    # A converter with no registrations cannot be checked — the
    # export proceeds rather than refusing on a guess.
    from stella.model import Store

    import stella.train as train_mod

    monkeypatch.setattr(train_mod, "require_training_deps", lambda: None)
    d = fake_llama_cpp(tmp_path)
    store = _seed_trained_project(Store(tmp_path / "home"), tmp_path)

    def loader(base_ref, adapter_dir):
        return _FakeMergedModel(), _FakeSaveTokenizer()

    result = export_gguf(
        store, "tiny", "proof", tmp_path / "out",
        _runner=FakeRunner(), _model_loader=loader,
        llama_cpp=(
            d / "convert_hf_to_gguf.py",
            d / "build" / "bin" / "llama-quantize",
        ),
        _base_arch="WeirdArchForCausalLM",
    )
    assert Path(result["gguf"]).is_file()


# -- T101: quote paths in the Modelfile and the printed command ------


def test_write_modelfile_quotes_spaced_paths(tmp_path):
    import shlex

    dest = tmp_path / "my models"
    dest.mkdir()
    gguf = dest / "model-q4_k_m.gguf"
    gguf.write_bytes(b"fake")
    modelfile, command = write_modelfile(
        gguf, dest / "Modelfile", name="tiny-proof"
    )
    # The printed command works when pasted: shlex.split recovers
    # the spaced path as one token.
    assert shlex.split(command) == [
        "ollama", "create", "tiny-proof", "-f", str(dest / "Modelfile"),
    ]
    # The FROM line carries the quoted path.
    text = modelfile.read_text()
    assert text.startswith(f"FROM {shlex.quote(str(gguf.resolve()))}")


def test_write_modelfile_plain_paths_unchanged(tmp_path):
    import shlex

    gguf = tmp_path / "m.gguf"
    gguf.write_bytes(b"fake")
    modelfile, command = write_modelfile(
        gguf, tmp_path / "Modelfile", name="tiny-proof"
    )
    # shlex.quote is a no-op without spaces: the old exact strings.
    assert modelfile.read_text().startswith(f"FROM {gguf.resolve()}")
    assert command == f"ollama create tiny-proof -f {modelfile}"
    assert shlex.split(command) == [
        "ollama", "create", "tiny-proof", "-f", str(modelfile),
    ]


# -- T103: timeout on the converter/quantizer subprocesses ------------


def test_run_times_out_on_hung_subprocess():
    import sys
    import time

    from stella.gguf import _run

    start = time.monotonic()
    with pytest.raises(StellaError) as excinfo:
        _run(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=0.5, step="quantizer",
        )
    # Killed promptly, not waited out — and the step is named.
    assert time.monotonic() - start < 10
    assert "quantizer timed out" in str(excinfo.value)


def test_run_with_timeout_allows_fast_command():
    import sys

    from stella.gguf import _run

    _run([sys.executable, "-c", "pass"], timeout=60, step="converter")


# -- S22: tool errors in plain words (GGUF side) ----------------------

def test_run_translates_unsupported_architecture():
    """The converter's raw 'not supported' becomes a plain-words
    message — with the raw line kept as a detail."""
    import sys

    from stella.gguf import _run
    from stella.model import StellaError

    code = (
        "import sys\n"
        "sys.stderr.write('Model architecture lfm9 is not '\n"
        "                 'supported\\n')\n"
        "sys.exit(1)\n"
    )
    with pytest.raises(StellaError) as excinfo:
        _run(
            [sys.executable, "-c", code],
            step="converter",
        )
    message = str(excinfo.value)
    assert message.startswith("the converter failed (1).")
    assert "does not support this model type" in message
    assert "architecture lfm9 is not supported" in message


def test_run_unknown_error_keeps_raw_tail():
    """An unmapped converter error still shows its raw tail,
    behind a plain-words lead."""
    import sys

    from stella.gguf import _run
    from stella.model import StellaError

    code = (
        "import sys\n"
        "sys.stderr.write('converter exploded mysteriously 777\\n')\n"
        "sys.exit(1)\n"
    )
    with pytest.raises(StellaError) as excinfo:
        _run([sys.executable, "-c", code], step="quantizer")
    message = str(excinfo.value)
    assert "The tool failed." in message
    assert "converter exploded mysteriously 777" in message


def test_subprocess_timeout_is_generous():
    # A real 1.7B convert takes minutes: the bound is minutes, not
    # seconds.
    from stella.gguf import SUBPROCESS_TIMEOUT_SECONDS

    assert SUBPROCESS_TIMEOUT_SECONDS >= 600

# -- T89: one-click Ollama create after GGUF export ------------------


def test_create_in_ollama_runs_the_command(tmp_path):
    """T89 Done: create-after-export runs `ollama create` with the
    exported name and Modelfile (verified against a fake Ollama)."""
    from stella.gguf import create_in_ollama

    modelfile = tmp_path / "Modelfile"
    modelfile.write_text("FROM /tmp/model.gguf\n")
    seen = []

    def fake_ollama(cmd):
        seen.append(cmd)
        return "success"

    out = create_in_ollama(
        "lfm3-tool-tool-calls", modelfile, _runner=fake_ollama
    )
    assert out == "success"
    assert seen == [[
        "ollama", "create", "lfm3-tool-tool-calls",
        "-f", str(modelfile),
    ]]


def test_create_in_ollama_failure_reports_the_error(tmp_path):
    """T89 Done: a failed create shows the Ollama error plainly."""
    from stella.gguf import create_in_ollama
    from stella.model import StellaError

    modelfile = tmp_path / "Modelfile"
    modelfile.write_text("FROM /tmp/model.gguf\n")

    def failing_ollama(cmd):
        raise StellaError("ollama create failed: model not found")

    with pytest.raises(StellaError, match="model not found"):
        create_in_ollama(
            "x-y", modelfile, _runner=failing_ollama
        )


def test_create_in_ollama_needs_a_modelfile(tmp_path):
    """T89: no Modelfile means no create — the error says to
    export first."""
    from stella.gguf import create_in_ollama
    from stella.model import StellaError

    with pytest.raises(StellaError, match="no Modelfile"):
        create_in_ollama("x-y", tmp_path / "Modelfile")


def test_create_in_ollama_missing_binary_says_so(tmp_path, monkeypatch):
    """T89: a missing `ollama` binary is a plain error, not a raw
    FileNotFoundError."""
    import shutil

    from stella.gguf import create_in_ollama
    from stella.model import StellaError

    modelfile = tmp_path / "Modelfile"
    modelfile.write_text("FROM /tmp/model.gguf\n")
    monkeypatch.setattr(shutil, "which", lambda *a, **k: None)
    with pytest.raises(StellaError, match="Ollama is not installed"):
        create_in_ollama("x-y", modelfile)


def test_create_in_ollama_cancel_kills_the_process(tmp_path):
    """T89/T107: cancelling a create kills the Ollama process."""
    import time

    from stella.gguf import create_in_ollama
    from stella.model import StellaError

    modelfile = tmp_path / "Modelfile"
    modelfile.write_text("FROM /tmp/model.gguf\n")
    # A fake ollama that sleeps: the cancel must kill it promptly.
    script = tmp_path / "ollama"
    script.write_text(
        "#!/bin/sh\nsleep 30\n"
    )
    script.chmod(0o755)
    import os

    env_path = os.environ.get("PATH", "")
    monkeypatch_path = str(tmp_path) + os.pathsep + env_path
    import unittest.mock as mock

    with mock.patch.dict(os.environ, {"PATH": monkeypatch_path}):
        start = time.monotonic()
        with pytest.raises(StellaError, match="Cancelled"):
            create_in_ollama(
                "x-y", modelfile, should_stop=lambda: True
            )
    assert time.monotonic() - start < 10


# -- v0.20.0: T153 (export estimate) + T152 (merge loading event) ------


def _estimable_export_project(tmp_path, total_size=3_460_000_000):
    """A project with a trained adapter on a local fake model —
    the export estimate runs entirely offline against it."""
    from stella.model import Store

    model_dir = tmp_path / "model"
    model_dir.mkdir(parents=True)
    (model_dir / "config.json").write_text(json.dumps({
        "hidden_size": 2048, "num_hidden_layers": 24,
        "intermediate_size": 8192, "torch_dtype": "bfloat16",
    }))
    (model_dir / "model.safetensors.index.json").write_text(json.dumps({
        "metadata": {"total_size": total_size},
    }))
    store = Store(tmp_path / "home")
    store.create_profile("p1", base_ref=str(model_dir))
    store.create_project("p1", "proj")
    adapter = store.project_dir("p1", "proj") / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}\n")
    return store


def test_estimate_export_names_merged_output_and_time(tmp_path):
    # T153 Done: the estimate names the merged size, the output
    # size, and a rough time — from metadata only, no model load.
    from stella.gguf import estimate_export, format_export_estimate

    store = _estimable_export_project(tmp_path)
    estimate = estimate_export(store, "p1", "proj")
    assert estimate["merged_bytes"] == 3_460_000_000
    # 1.73B params at Q4_K_M's 4.85 bits per weight.
    assert estimate["gguf_bytes"] == int(1_730_000_000 * 4.85 / 8)
    # R31: the disk need is the peak — merged + F16 intermediate
    # (about the merged size again) + GGUF output, all on disk at
    # once during the quantize step.
    assert estimate["f16_bytes"] == estimate["merged_bytes"]
    assert estimate["disk_bytes"] == (
        2 * estimate["merged_bytes"] + estimate["gguf_bytes"]
    )
    assert estimate["quant"] == "Q4_K_M"
    assert estimate["time_note"]
    text = format_export_estimate(estimate)
    assert "3.2 GB" in text  # merged
    assert "1000 MB" in text  # GGUF output
    assert "Q4_K_M" in text
    assert "roughly" in text.lower()


def test_estimate_export_refuses_without_adapter(tmp_path):
    # T153: with nothing trained there is nothing to estimate.
    from stella.gguf import estimate_export
    from stella.model import Store

    store = Store(tmp_path / "home")
    store.create_profile("p1", base_ref="somewhere/model")
    store.create_project("p1", "proj")
    with pytest.raises(StellaError, match="no trained adapter"):
        estimate_export(store, "p1", "proj")


def test_merge_adapter_emits_loading_with_model_name(tmp_path):
    # T152: the merge says which model it is loading, before it
    # loads it.
    pytest.importorskip("torch", reason="training stack not installed")
    from test_train import FakeTokenizer, tiny_model_and_tokenizer

    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir()
    (adapter_dir / "adapter_config.json").write_text("{}\n")

    def loader(base_ref, adapter):
        fresh, tok = tiny_model_and_tokenizer()
        from peft import LoraConfig, get_peft_model

        wrapped = get_peft_model(
            fresh,
            LoraConfig(
                r=2, lora_alpha=4, target_modules=["c_attn", "c_proj"],
                task_type="CAUSAL_LM",
            ),
        )
        return wrapped, tok

    events = []
    merge_adapter(
        "test/tiny-model", adapter_dir, tmp_path / "merged",
        _model_loader=loader, _dtype="float32", on_event=events.append,
    )
    loading = [e for e in events if e.get("type") == "loading"]
    assert len(loading) == 1
    assert loading[0]["model"] == "test/tiny-model"
    assert "test/tiny-model" in loading[0]["message"]


# -- v0.26.0: R31 — the export refuses on a short disk ---------------


def test_export_gguf_refuses_when_disk_is_short(monkeypatch, tmp_path):
    """R31: the export refuses up front when the disk cannot hold
    the peak (merged + F16 + output) — before any merge work,
    with the peak named."""
    import shutil
    from collections import namedtuple

    usage = namedtuple("usage", "total used free")
    store = _estimable_export_project(tmp_path)
    # Peak: 2 * 3.46 GB merged + ~1.05 GB GGUF. Free space that
    # covers merged + output (the old, wrong need) must refuse.
    monkeypatch.setattr(
        shutil, "disk_usage",
        lambda path: usage(10**10, 0, 3_460_000_000 + 1_050_000_000),
    )
    with pytest.raises(StellaError, match="Not enough free disk"):
        export_gguf(
            store, "p1", "proj", tmp_path / "out",
            _runner=FakeRunner(),
        )


def test_format_export_estimate_names_peak_disk(tmp_path):
    """R31: the estimate text names the peak disk need, so the
    user sees the F16 intermediate in the number."""
    from stella.gguf import estimate_export, format_export_estimate

    store = _estimable_export_project(tmp_path)
    text = format_export_estimate(estimate_export(store, "p1", "proj"))
    assert "busiest point" in text
    assert "F16" in text
    assert "7.4 GB" in text  # 2 x 3.2 GB merged + ~1.0 GB GGUF


# -- v0.26.0: R33 — interrupts clean up the merged weights -----------


def test_export_gguf_interrupt_removes_merged_dir(tmp_path):
    """R33: a Ctrl+C during the convert leaves no merged weights
    behind — the interrupt is still re-raised, never swallowed."""
    from stella.model import Store

    store = Store(tmp_path / "home")
    store.create_profile("tiny", base_ref="test/tiny-model")
    store.create_project("tiny", "proof")
    adapter = store.project_dir("tiny", "proof") / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}\\n")
    out = tmp_path / "out"

    def interrupting_runner(cmd):
        if "convert_hf_to_gguf.py" in cmd[1]:
            raise KeyboardInterrupt()
        raise AssertionError(f"unexpected command: {cmd}")

    def fake_merge(base_ref, adapter_dir, merged_dir, **kwargs):
        merged_dir.mkdir(parents=True)
        (merged_dir / "config.json").write_text('{"model_type": "gpt2"}\\n')
        (merged_dir / "model.safetensors").write_bytes(b"fake weights")
        return merged_dir

    import stella.gguf as gguf_mod

    real_merge = gguf_mod.merge_adapter
    gguf_mod.merge_adapter = fake_merge
    try:
        with pytest.raises(KeyboardInterrupt):
            export_gguf(
                store, "tiny", "proof", out,
                _runner=interrupting_runner,
            )
    finally:
        gguf_mod.merge_adapter = real_merge
    assert not (out / "proof-merged-hf").exists()


def test_convert_interrupt_removes_partial_gguf(tmp_path):
    """R33: a Ctrl+C during the quantize leaves no partial GGUF
    behind."""
    hf = fake_hf_dir(tmp_path)

    def interrupting_runner(cmd):
        if "convert_hf_to_gguf.py" in cmd[1]:
            out = Path(cmd[cmd.index("--outfile") + 1])
            out.write_bytes(b"GGUF-f16-fake")
            return
        if "llama-quantize" in cmd[0]:
            Path(cmd[2]).write_bytes(b"half-written")
            raise KeyboardInterrupt()
        raise AssertionError(f"unexpected command: {cmd}")

    target = tmp_path / "model-q4_k_m.gguf"
    with pytest.raises(KeyboardInterrupt):
        convert_to_gguf(hf, target, _runner=interrupting_runner)
    assert not target.exists()
    assert not (tmp_path / "model-q4_k_m.f16.gguf").exists()
