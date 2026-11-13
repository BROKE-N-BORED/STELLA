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
    """A directory shaped like a llama.cpp checkout."""
    d = tmp_path / "llama.cpp"
    (d / "build" / "bin").mkdir(parents=True)
    (d / "convert_hf_to_gguf.py").write_text("# fake converter\n")
    (d / "build" / "bin" / "llama-quantize").write_text("# fake quantizer\n")
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
