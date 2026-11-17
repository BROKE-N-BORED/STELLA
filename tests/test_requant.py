"""Re-quantize tests.

No real llama.cpp, no real Ollama, no real downloads: the Ollama
models dir is faked (manifests + blobs), llama-quantize and
`ollama create` go through an injected runner (or a small fake
script on PATH for the CLI end-to-end test), and the disk check is
faked with a monkeypatched disk_usage.
"""
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
from collections import namedtuple
from pathlib import Path

import pytest

from stella import requant as requant_mod
from stella.model import StellaError
from stella.requant import (
    _read_gguf_source_quant,
    default_new_tag,
    find_llama_quantize,
    gguf_has_vision,
    requant_model,
    resolve_model_blob,
    validate_new_tag,
    validate_quant,
)
from test_cli import run_cli

BLOB_DIGEST = "ab" * 32


def _gguf_header(tensor_type: int = 8) -> bytes:
    """A minimal real GGUF header: one tensor of the given type."""
    out = bytearray()
    out += b"GGUF"
    out += struct.pack("<I", 3)  # version
    out += struct.pack("<Q", 1)  # tensor count
    out += struct.pack("<Q", 0)  # metadata count
    name = b"weight.q"
    out += struct.pack("<Q", len(name)) + name
    out += struct.pack("<I", 1)  # n_dims
    out += struct.pack("<Q", 128)  # dim 0
    out += struct.pack("<I", tensor_type)
    out += struct.pack("<Q", 0)  # offset
    return bytes(out)


def fake_ollama_models(tmp_path, tag="qwen3.5:4b", blob_bytes=None):
    """A directory shaped like ~/.ollama/models with one model."""
    models = tmp_path / "ollama-models"
    manifest_dir = (
        models / "manifests" / "registry.ollama.ai" / "library" / "qwen3.5"
    )
    manifest_dir.mkdir(parents=True)
    blob = models / "blobs" / ("sha256-" + BLOB_DIGEST)
    blob.parent.mkdir(parents=True)
    blob.write_bytes(
        blob_bytes if blob_bytes is not None
        else _gguf_header(8) + b"\x00" * 100
    )
    manifest = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
        "layers": [
            {
                "mediaType": "application/vnd.ollama.image.model",
                "digest": "sha256:" + BLOB_DIGEST,
                "size": blob.stat().st_size,
            },
            {
                "mediaType": "application/vnd.ollama.image.template",
                "digest": "sha256:" + "cd" * 32,
                "size": 10,
            },
        ],
    }
    (manifest_dir / "4b").write_text(json.dumps(manifest))
    return models, blob


def fake_llama_cpp(tmp_path, executable=True):
    """A directory shaped like a llama.cpp checkout."""
    d = tmp_path / "llama.cpp"
    (d / "build" / "bin").mkdir(parents=True)
    q = d / "build" / "bin" / "llama-quantize"
    q.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "args = [a for a in sys.argv[1:] if not a.startswith('--')]\n"
        "src, dst, quant = args[0], args[1], args[2]\n"
        "data = open(src, 'rb').read()\n"
        "open(dst, 'wb').write(b'GGUF-' + quant.encode() + b'-fake'\n"
        "                      + data[:10])\n"
    )
    if executable:
        q.chmod(0o755)
    return d


def fake_ollama_bin(tmp_path, *, show_from=None, record=None):
    """An executable `ollama` stub on a fresh bin dir.

    Answers `show <tag> --modelfile` with a FROM line when
    show_from is set, and records `create` calls to `record`.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    script = bindir / "ollama"
    lines = ["#!/usr/bin/env python3", "import sys"]
    if record is not None:
        lines.append(
            f"open({str(record)!r}, 'a').write(' '.join(sys.argv[1:]) + chr(10))"
        )
    if show_from is not None:
        lines.append("if sys.argv[1:2] == ['show']:")
        lines.append(f"    print('FROM {show_from}')")
    script.write_text("\n".join(lines) + "\n")
    script.chmod(0o755)
    return bindir


class FakeRunner:
    """Pretends to be llama-quantize + `ollama create`."""

    def __init__(self, fail_create=False):
        self.commands = []
        self.fail_create = fail_create

    def __call__(self, cmd):
        self.commands.append(list(cmd))
        if "llama-quantize" in cmd[0]:
            pos = [a for a in cmd[1:] if not a.startswith("--")]
            src, dst, quant = Path(pos[0]), Path(pos[1]), pos[2]
            assert src.is_file(), "quantize got a missing source"
            dst.write_bytes(b"GGUF-" + quant.encode() + b"-fake")
        elif cmd[0] == "ollama" and cmd[1] == "create":
            if self.fail_create:
                raise StellaError("Ollama refused the create (fake)")
        else:
            raise AssertionError(f"unexpected command: {cmd}")


@pytest.fixture()
def env_setup(monkeypatch, tmp_path):
    """Fake llama.cpp + fake ollama on PATH + fake models dir."""
    models, blob = fake_ollama_models(tmp_path)
    cpp = fake_llama_cpp(tmp_path)
    bindir = fake_ollama_bin(tmp_path)
    monkeypatch.setenv("LLAMA_CPP_DIR", str(cpp))
    monkeypatch.setenv("OLLAMA_MODELS", str(models))
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("HOME", str(tmp_path))
    return {"models": models, "blob": blob, "cpp": cpp, "bin": bindir}


# -- quant validation -----------------------------------------------

def test_validate_quant_accepts_and_normalizes():
    assert validate_quant("Q4_K_M") == "Q4_K_M"
    assert validate_quant("q4_k_m") == "Q4_K_M"
    assert validate_quant("  Q8_0 ") == "Q8_0"
    assert validate_quant("Q2_K") == "Q2_K"


def test_validate_quant_rejects_bogus():
    for bad in ("BOGUS", "", "Q9_ZZ", "Q4_K_X", "4bit"):
        with pytest.raises(StellaError, match="not a quant type"):
            validate_quant(bad)


def test_default_new_tag():
    assert default_new_tag("qwen3.5:4b", "Q4_K_M") == "qwen3.5:4b-q4-k-m"
    assert default_new_tag("lfm3", "Q4_K_M") == "lfm3:q4-k-m"
    assert (
        default_new_tag("matern/minicpm5-heretic:2b", "Q5_K_M")
        == "matern/minicpm5-heretic:2b-q5-k-m"
    )


def test_validate_new_tag():
    assert validate_new_tag("qwen3.5:4b-q4-k-m") == "qwen3.5:4b-q4-k-m"
    with pytest.raises(StellaError, match="not a valid model name"):
        validate_new_tag("Has Spaces")
    with pytest.raises(StellaError, match="not a valid model name"):
        validate_new_tag("UPPER:1b")
    with pytest.raises(StellaError, match="must not be empty"):
        validate_new_tag("")


# -- blob resolution --------------------------------------------------

def test_resolve_blob_via_manifest(tmp_path):
    models, blob = fake_ollama_models(tmp_path)
    assert resolve_model_blob("qwen3.5:4b", models) == blob


def test_resolve_blob_missing_model(tmp_path):
    models = tmp_path / "empty-models"
    models.mkdir()
    with pytest.raises(StellaError, match="does not have a model"):
        resolve_model_blob("ghost:1b", models)


def test_resolve_blob_not_gguf(tmp_path):
    models, blob = fake_ollama_models(
        tmp_path, blob_bytes=b"NOT-A-GGUF-FILE" + b"\x00" * 50
    )
    with pytest.raises(StellaError, match="not a GGUF model file"):
        resolve_model_blob("qwen3.5:4b", models)


def test_resolve_blob_reads_only_the_magic(tmp_path):
    # R6: the magic check reads 4 bytes, not the file. A 256 MB
    # sparse blob (a header, then holes) resolves with a traced
    # peak far under the file size — the old read_bytes() peaked
    # at the whole blob (1.05 GB for a 1.1 GB model).
    import tracemalloc

    models, blob = fake_ollama_models(tmp_path)
    with open(blob, "r+b") as handle:
        handle.seek(256 * 1024 * 1024 - 1)
        handle.write(b"\x00")
    assert blob.stat().st_size == 256 * 1024 * 1024
    tracemalloc.start()
    try:
        assert resolve_model_blob("qwen3.5:4b", models) == blob
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 16 * 1024 * 1024


def test_resolve_blob_via_modelfile_fallback(tmp_path, monkeypatch):
    models = tmp_path / "ollama-models"
    models.mkdir()
    blob = tmp_path / "somewhere.gguf"
    blob.write_bytes(_gguf_header(8) + b"\x00" * 10)
    bindir = fake_ollama_bin(tmp_path, show_from=str(blob))
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    assert resolve_model_blob("fallback:1b", models) == blob


def _gguf_with_big_metadata(tensor_types, token_count=70000):
    """A GGUF whose metadata is over 1 MB: a tokenizer token
    array like a real Ollama blob's (7.85 MB on LFM3 1.7B), then
    one tensor per type in `tensor_types`."""
    out = bytearray()
    out += b"GGUF"
    out += struct.pack("<I", 3)  # version
    out += struct.pack("<Q", len(tensor_types))  # tensor count
    out += struct.pack("<Q", 1)  # metadata count
    key = b"tokenizer.ggml.tokens"
    out += struct.pack("<Q", len(key)) + key
    out += struct.pack("<I", 9)  # array
    out += struct.pack("<I", 8)  # of strings
    out += struct.pack("<Q", token_count)
    for i in range(token_count):
        token = f"tok{i:06d}".encode()
        out += struct.pack("<Q", len(token)) + token
    for index, tensor_type in enumerate(tensor_types):
        name = f"blk.{index}.weight".encode()
        out += struct.pack("<Q", len(name)) + name
        out += struct.pack("<I", 1)  # n_dims
        out += struct.pack("<Q", 128)  # dim 0
        out += struct.pack("<I", tensor_type)
        out += struct.pack("<Q", 0)  # offset
    return bytes(out)


def test_read_gguf_source_quant(tmp_path):
    header = tmp_path / "h.gguf"
    header.write_bytes(_gguf_header(8))
    assert _read_gguf_source_quant(header) == ("Q8_0", 8.5)
    header.write_bytes(_gguf_header(11))
    assert _read_gguf_source_quant(header) == ("Q4_K", 4.85)
    header.write_bytes(b"GGUF" + b"\x00" * 100)
    assert _read_gguf_source_quant(header) == (None, None)
    header.write_bytes(b"not gguf at all")
    assert _read_gguf_source_quant(header) == (None, None)


def test_read_gguf_source_quant_big_metadata(tmp_path):
    # S15: a real Ollama blob's metadata is 7.85 MB, past the old
    # 1 MB read cap — the parse died mid-metadata and every real
    # model read as "unknown". The reader streams now, so the
    # quant past 1 MB of tokenizer tokens still reads.
    header = tmp_path / "big.gguf"
    data = _gguf_with_big_metadata([11, 11, 8])
    assert len(data) > 1024 * 1024
    header.write_bytes(data)
    assert _read_gguf_source_quant(header) == ("Q4_K", 4.85)


def test_read_gguf_source_quant_truncated_big_metadata(tmp_path):
    # A file cut off inside the big metadata array is unreadable,
    # not a crash: the never-raises contract holds.
    header = tmp_path / "cut.gguf"
    data = _gguf_with_big_metadata([11, 11, 8])
    header.write_bytes(data[:600 * 1024])
    assert _read_gguf_source_quant(header) == (None, None)


def test_read_gguf_source_quant_missing_file(tmp_path):
    assert _read_gguf_source_quant(tmp_path / "ghost.gguf") == (
        None, None,
    )


# -- R5: vision detection ---------------------------------------------


def _gguf_with_arch_and_tensors(arch=None, tensor_names=("weight.q",)):
    """A GGUF header with an optional general.architecture metadata
    entry and the given tensor names."""
    out = bytearray()
    out += b"GGUF"
    out += struct.pack("<I", 3)  # version
    out += struct.pack("<Q", len(tensor_names))  # tensor count
    out += struct.pack("<Q", 1 if arch is not None else 0)  # kv count
    if arch is not None:
        key = b"general.architecture"
        out += struct.pack("<Q", len(key)) + key
        out += struct.pack("<I", 8)  # string
        value = arch.encode()
        out += struct.pack("<Q", len(value)) + value
    for name in tensor_names:
        encoded = name.encode()
        out += struct.pack("<Q", len(encoded)) + encoded
        out += struct.pack("<I", 1)  # n_dims
        out += struct.pack("<Q", 128)  # dim 0
        out += struct.pack("<I", 8)  # Q8_0
        out += struct.pack("<Q", 0)  # offset
    return bytes(out)


def test_gguf_has_vision_detects_projector_tensors(tmp_path):
    header = tmp_path / "vl.gguf"
    header.write_bytes(_gguf_with_arch_and_tensors(
        tensor_names=("blk.0.attn_q.weight", "mmproj.weight")))
    assert gguf_has_vision(header) is True
    header.write_bytes(_gguf_with_arch_and_tensors(
        tensor_names=("blk.0.attn_q.weight", "token_embd.weight")))
    assert gguf_has_vision(header) is False


def test_gguf_has_vision_detects_vision_architecture(tmp_path):
    header = tmp_path / "vl.gguf"
    for arch in ("llava", "qwen2vl", "qwen3vl", "moondream2"):
        header.write_bytes(_gguf_with_arch_and_tensors(arch=arch))
        assert gguf_has_vision(header) is True, arch
    for arch in ("llama", "qwen2", "gpt2"):
        header.write_bytes(_gguf_with_arch_and_tensors(arch=arch))
        assert gguf_has_vision(header) is False, arch
    header.write_bytes(b"not a gguf file at all")
    assert gguf_has_vision(header) is False
    assert gguf_has_vision(tmp_path / "ghost.gguf") is False


def _fake_vision_models(tmp_path):
    """fake_ollama_models plus a projector layer in the manifest:
    the shape Ollama stores a vision model in."""
    models, blob = fake_ollama_models(tmp_path)
    manifest_path = (
        models / "manifests" / "registry.ollama.ai" / "library"
        / "qwen3.5" / "4b"
    )
    manifest = json.loads(manifest_path.read_text())
    manifest["layers"].append({
        "mediaType": "application/vnd.ollama.image.projector",
        "digest": "sha256:" + "ef" * 32,
        "size": 12345,
    })
    manifest_path.write_text(json.dumps(manifest))
    return models, blob


def test_requant_refuses_vision_model_with_projector_layer(tmp_path):
    # R5: a manifest with a projector layer is a vision model —
    # requant refuses before llama-quantize or `ollama create`
    # ever run, so no text-only copy is ever registered.
    models, _blob = _fake_vision_models(tmp_path)
    runner = FakeRunner()
    with pytest.raises(StellaError, match="can see pictures"):
        requant_model("qwen3.5:4b", _models_dir=models, _runner=runner)
    assert runner.commands == []


def test_requant_refuses_vision_model_with_mmproj_tensors(tmp_path):
    # R5: the header-scan backstop, for a GGUF carrying its
    # projector tensors in the model file itself.
    blob_bytes = _gguf_with_arch_and_tensors(
        tensor_names=("mmproj.weight", "mmproj.bias"))
    models, _blob = fake_ollama_models(tmp_path, blob_bytes=blob_bytes)
    runner = FakeRunner()
    with pytest.raises(StellaError, match="can see pictures"):
        requant_model("qwen3.5:4b", _models_dir=models, _runner=runner)
    assert runner.commands == []


# -- llama.cpp discovery ----------------------------------------------

def test_find_llama_quantize_found(env_setup):
    found = find_llama_quantize()
    assert found.name == "llama-quantize"
    assert os.access(found, os.X_OK)


def test_find_llama_quantize_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("LLAMA_CPP_DIR", str(tmp_path / "empty"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(StellaError, match="llama-quantize was not found"):
        find_llama_quantize()


def test_find_llama_quantize_skips_non_executable(monkeypatch, tmp_path):
    cpp = fake_llama_cpp(tmp_path, executable=False)
    monkeypatch.setenv("LLAMA_CPP_DIR", str(cpp))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(StellaError, match="llama-quantize was not found"):
        find_llama_quantize()


# -- full requant -----------------------------------------------------

def test_requant_happy_path(env_setup, tmp_path):
    runner = FakeRunner()
    events = []
    before = hashlib.sha256(env_setup["blob"].read_bytes()).hexdigest()
    report = requant_model(
        "qwen3.5:4b",
        work_dir=tmp_path / "work",
        on_event=events.append,
        _runner=runner,
        _models_dir=env_setup["models"],
    )
    assert report["source_tag"] == "qwen3.5:4b"
    assert report["source_quant"] == "Q8_0"
    assert report["new_tag"] == "qwen3.5:4b-q4-k-m"
    assert report["quant"] == "Q4_K_M"
    assert report["output_bytes"] > 0
    assert report["ollama_run"] == "ollama run qwen3.5:4b-q4-k-m"
    # Two commands: quantize, then ollama create.
    assert len(runner.commands) == 2
    assert runner.commands[0][-1] == "Q4_K_M"
    assert runner.commands[1][:3] == ["ollama", "create", "qwen3.5:4b-q4-k-m"]
    # The original blob is untouched, byte for byte.
    after = hashlib.sha256(env_setup["blob"].read_bytes()).hexdigest()
    assert after == before
    # Work files are cleaned up after a successful create.
    assert list((tmp_path / "work").glob("*.gguf")) == []
    assert not (tmp_path / "work" / "Modelfile").exists()
    kinds = [e["type"] for e in events]
    assert kinds == ["found", "quantized", "created"]


def test_requant_with_explicit_as_tag(env_setup, tmp_path):
    runner = FakeRunner()
    report = requant_model(
        "qwen3.5:4b", new_tag="qwen-small:4b",
        work_dir=tmp_path / "work", _runner=runner,
        _models_dir=env_setup["models"],
    )
    assert report["new_tag"] == "qwen-small:4b"
    assert runner.commands[1][2] == "qwen-small:4b"


def test_requant_bogus_quant_rejected(env_setup, tmp_path):
    with pytest.raises(StellaError, match="not a quant type"):
        requant_model(
            "qwen3.5:4b", quant="BOGUS",
            work_dir=tmp_path / "work", _runner=FakeRunner(),
            _models_dir=env_setup["models"],
        )


def test_requant_missing_model(env_setup, tmp_path):
    with pytest.raises(StellaError, match="does not have a model"):
        requant_model(
            "ghost:1b",
            work_dir=tmp_path / "work", _runner=FakeRunner(),
            _models_dir=env_setup["models"],
        )


def test_requant_missing_llama_cpp(monkeypatch, tmp_path, env_setup):
    # Point every search dir somewhere empty: LLAMA_CPP_DIR, HOME,
    # the working dir, and PATH must all lack llama-quantize. (The
    # fixture's fake lives at tmp_path/llama.cpp, so HOME and cwd
    # must move away from tmp_path itself.)
    (tmp_path / "nohome").mkdir()
    (tmp_path / "nowhere").mkdir()
    monkeypatch.setenv("LLAMA_CPP_DIR", str(tmp_path / "empty"))
    monkeypatch.setenv("HOME", str(tmp_path / "nohome"))
    monkeypatch.setenv("PATH", str(env_setup["bin"]))
    monkeypatch.chdir(tmp_path / "nowhere")
    with pytest.raises(StellaError, match="llama-quantize was not found"):
        requant_model(
            "qwen3.5:4b",
            work_dir=tmp_path / "work", _runner=FakeRunner(),
            _models_dir=env_setup["models"],
        )


def test_requant_missing_ollama(monkeypatch, tmp_path, env_setup):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(StellaError, match="ollama command was not found"):
        requant_model(
            "qwen3.5:4b",
            work_dir=tmp_path / "work", _runner=FakeRunner(),
            _models_dir=env_setup["models"],
        )


def test_requant_new_tag_already_exists(monkeypatch, env_setup, tmp_path):
    monkeypatch.setattr(
        requant_mod, "list_models", lambda: ["qwen3.5:4b-q4-k-m"]
    )
    with pytest.raises(StellaError, match="already has a model"):
        requant_model(
            "qwen3.5:4b",
            work_dir=tmp_path / "work", _runner=FakeRunner(),
            _models_dir=env_setup["models"],
        )


def test_requant_same_tag_refused(env_setup, tmp_path):
    with pytest.raises(StellaError, match="same as the original"):
        requant_model(
            "qwen3.5:4b", new_tag="qwen3.5:4b",
            work_dir=tmp_path / "work", _runner=FakeRunner(),
            _models_dir=env_setup["models"],
        )


def test_requant_not_enough_disk(monkeypatch, env_setup, tmp_path):
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(
        shutil, "disk_usage",
        lambda path: usage(10**9, 10**9 - 1000, 1000),
    )
    with pytest.raises(StellaError, match="Not enough free disk"):
        requant_model(
            "qwen3.5:4b",
            work_dir=tmp_path / "work", _runner=FakeRunner(),
            _models_dir=env_setup["models"],
        )


def test_requant_create_failure_keeps_work_file(env_setup, tmp_path):
    runner = FakeRunner(fail_create=True)
    work = tmp_path / "work"
    with pytest.raises(StellaError, match="still at"):
        requant_model(
            "qwen3.5:4b",
            work_dir=work, _runner=runner,
            _models_dir=env_setup["models"],
        )
    # The smaller file survives the failed create, for a retry.
    assert len(list(work.glob("*.gguf"))) == 1
    assert (work / "Modelfile").is_file()


# -- CLI end to end (real subprocess, fake tools on PATH) --------------

def test_cli_requant_end_to_end(monkeypatch, tmp_path, home):
    models, blob = fake_ollama_models(tmp_path)
    cpp = fake_llama_cpp(tmp_path)
    record = tmp_path / "ollama-calls.txt"
    bindir = fake_ollama_bin(tmp_path, record=record)
    monkeypatch.setenv("LLAMA_CPP_DIR", str(cpp))
    monkeypatch.setenv("OLLAMA_MODELS", str(models))
    monkeypatch.setenv("STELLA_HOME", str(home))
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    before = hashlib.sha256(blob.read_bytes()).hexdigest()
    res = run_cli(home, "requant", "qwen3.5:4b")
    assert res.returncode == 0, res.stderr
    assert "qwen3.5:4b-q4-k-m" in res.stdout
    assert "untouched" in res.stdout
    assert "ollama run qwen3.5:4b-q4-k-m" in res.stdout
    calls = record.read_text()
    assert "create qwen3.5:4b-q4-k-m -f" in calls
    after = hashlib.sha256(blob.read_bytes()).hexdigest()
    assert after == before


def test_cli_requant_bogus_quant_exit_1(monkeypatch, tmp_path, home):
    models, _blob = fake_ollama_models(tmp_path)
    cpp = fake_llama_cpp(tmp_path)
    bindir = fake_ollama_bin(tmp_path)
    monkeypatch.setenv("LLAMA_CPP_DIR", str(cpp))
    monkeypatch.setenv("OLLAMA_MODELS", str(models))
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    res = run_cli(home, "requant", "qwen3.5:4b", "--quant", "BOGUS")
    assert res.returncode == 1
    assert "not a quant type" in res.stderr


def test_cli_requant_missing_model_exit_1(monkeypatch, tmp_path, home):
    models = tmp_path / "empty-models"
    models.mkdir()
    cpp = fake_llama_cpp(tmp_path)
    bindir = fake_ollama_bin(tmp_path)
    monkeypatch.setenv("LLAMA_CPP_DIR", str(cpp))
    monkeypatch.setenv("OLLAMA_MODELS", str(models))
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    res = run_cli(home, "requant", "ghost:1b")
    assert res.returncode == 1
    assert "does not have a model" in res.stderr


# -- T74: cancel ------------------------------------------------------


def test_run_kills_process_on_cancel():
    """A long quantize is killed when the flag flips — the job
    card's Cancel does not wait for the quantizer to finish."""
    import threading
    import time

    from stella.requant import _run

    state = {"stop": False}

    def should_stop():
        return state["stop"]

    threading.Timer(0.5, lambda: state.update(stop=True)).start()
    started = time.monotonic()
    with pytest.raises(StellaError, match="Cancelled"):
        _run(["sleep", "30"], what="sleeping", should_stop=should_stop)
    assert time.monotonic() - started < 10


# -- S1: partial + empty output cleanup --------------------------------

def test_requant_failure_removes_partial_output(env_setup, tmp_path):
    """A failed quantize leaves no half-written model behind."""
    work = tmp_path / "work"

    def failing_runner(cmd):
        if "llama-quantize" in cmd[0]:
            pos = [a for a in cmd[1:] if not a.startswith("--")]
            Path(pos[1]).write_bytes(b"half-written")
            raise StellaError("quantizer failed (fake)")
        raise AssertionError(f"unexpected command: {cmd}")

    with pytest.raises(StellaError, match="quantizer failed"):
        requant_model(
            "qwen3.5:4b",
            work_dir=work, _runner=failing_runner,
            _models_dir=env_setup["models"],
        )
    assert list(work.glob("*.gguf")) == []


def test_requant_empty_output_is_cleaned_up(env_setup, tmp_path):
    """A quantizer that writes an empty file is cleaned up before
    the complaint, so no 0-byte model sits in the work folder."""
    work = tmp_path / "work"

    def empty_runner(cmd):
        if "llama-quantize" in cmd[0]:
            pos = [a for a in cmd[1:] if not a.startswith("--")]
            Path(pos[1]).write_bytes(b"")
            return
        raise AssertionError(f"unexpected command: {cmd}")

    with pytest.raises(StellaError, match="wrote no file"):
        requant_model(
            "qwen3.5:4b",
            work_dir=work, _runner=empty_runner,
            _models_dir=env_setup["models"],
        )
    assert list(work.glob("*.gguf")) == []


def test_requant_found_event_carries_double_quant_warning(
    env_setup, tmp_path
):
    # S1/S14: an already-quantized source (Q8_0 here) warns that
    # shrinking rounds the weights a second time.
    events = []
    requant_model(
        "qwen3.5:4b",
        work_dir=tmp_path / "work", on_event=events.append,
        _runner=FakeRunner(), _models_dir=env_setup["models"],
    )
    found = events[0]
    assert found["type"] == "found"
    assert found["requantize_warning"] is not None
    assert "already quantized" in found["requantize_warning"]
    assert "second time" in found["requantize_warning"]


def test_requant_no_warning_for_unquantized_source(
    env_setup, tmp_path
):
    # S1/S14: a positively unquantized source (F16 here) gets no
    # warning — there is no second rounding to warn about.
    models, _blob = fake_ollama_models(
        tmp_path / "f16", blob_bytes=_gguf_header(1) + b"\x00" * 100
    )
    events = []
    requant_model(
        "qwen3.5:4b",
        work_dir=tmp_path / "work", on_event=events.append,
        _runner=FakeRunner(), _models_dir=models,
    )
    assert events[0]["requantize_warning"] is None


# -- S21: live progress on the requant run ------------------------------

def test_parse_quantize_progress():
    from stella.requant import _parse_quantize_progress

    # The format llama-quantize really prints (on stderr).
    assert _parse_quantize_progress(
        "[  12/ 287] blk.0.attn_q.weight - [2048, 2048], "
        "type = q4_K, size = 2.250 MiB"
    ) == (12, 287)
    assert _parse_quantize_progress("[1/3] a.weight") == (1, 3)
    assert _parse_quantize_progress("tensor 120 of 339") == (120, 339)
    assert _parse_quantize_progress("120 of 339 tensors") == (120, 339)
    # Metadata lines carry no count.
    assert _parse_quantize_progress(
        "llama_model_loader: - kv   0: general.architecture str = lfm3"
    ) is None
    assert _parse_quantize_progress(
        "llama_model_loader: loaded meta data with 45 key-value "
        "pairs and 287 tensors"
    ) is None
    assert _parse_quantize_progress("") is None
    # Insane counts are not believed.
    assert _parse_quantize_progress("[ 5/ 0 ] x") is None
    assert _parse_quantize_progress("[ 300/ 287 ] x") is None


def test_run_streams_quantize_progress():
    """Per-tensor lines arrive as progress events while the
    quantizer runs — from stdout and stderr both."""
    from stella.requant import _run

    code = (
        "import sys, time\n"
        "print('[  1/ 3] a.weight', flush=True)\n"
        "print('[  2/ 3] b.weight', file=sys.stderr, flush=True)\n"
        "print('[  3/ 3] c.weight', flush=True)\n"
    )
    events = []
    _run(
        [sys.executable, "-c", code], what="shrinking",
        on_progress=events.append,
    )
    assert events == [
        {"type": "quantize_progress", "done": 1, "total": 3},
        {"type": "quantize_progress", "done": 2, "total": 3},
        {"type": "quantize_progress", "done": 3, "total": 3},
    ]


def test_run_still_working_when_no_count():
    """A silent quantizer gets a periodic 'still working' event
    (interval shortened for the test) so the run never looks dead."""
    from stella.requant import _run

    code = "import time; time.sleep(0.7)"
    events = []
    _run(
        [sys.executable, "-c", code], what="shrinking",
        on_progress=events.append, _still_working_seconds=0.2,
    )
    kinds = [e["type"] for e in events]
    assert kinds and all(k == "still_working" for k in kinds)


def test_run_no_still_working_once_count_seen():
    """Once tensor counts are flowing, no 'still working' line is
    needed — the counts themselves show the run is alive. A
    'still working' before the first count is fine: the child
    may take a while to start under load, and the run genuinely
    has no count yet."""
    from stella.requant import _run

    code = (
        "import time\n"
        "print('[  1/ 3] a.weight', flush=True)\n"
        "time.sleep(0.6)\n"
        "print('[  2/ 3] b.weight', flush=True)\n"
    )
    events = []
    _run(
        [sys.executable, "-c", code], what="shrinking",
        on_progress=events.append, _still_working_seconds=0.2,
    )
    kinds = [e["type"] for e in events]
    first_count = kinds.index("quantize_progress")
    assert "still_working" not in kinds[first_count:]
    assert [
        e["done"] for e in events
        if e["type"] == "quantize_progress"
    ] == [1, 2]


def test_run_survives_non_utf8_output():
    """Raw non-UTF-8 bytes in the tool's output (tokenizer vocab
    in the metadata dump) must not kill the reader."""
    from stella.requant import _run

    code = (
        "import sys\n"
        "sys.stdout.buffer.write(b'\\xff\\xfe not utf8\\n')\n"
        "sys.stdout.buffer.flush()\n"
        "print('[  1/ 1] a.weight', flush=True)\n"
    )
    events = []
    _run(
        [sys.executable, "-c", code], what="shrinking",
        on_progress=events.append,
    )
    assert events == [
        {"type": "quantize_progress", "done": 1, "total": 1}
    ]


def test_requant_progress_flows_to_events(env_setup, tmp_path):
    """End to end with a real subprocess: the fake quantizer's
    per-tensor lines become progress events between found and
    quantized."""
    script = env_setup["cpp"] / "build" / "bin" / "llama-quantize"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "args = [a for a in sys.argv[1:] if not a.startswith('--')]\n"
        "src, dst, quant = args[0], args[1], args[2]\n"
        "print('[  1/ 2] a.weight', file=sys.stderr, flush=True)\n"
        "print('[  2/ 2] b.weight', file=sys.stderr, flush=True)\n"
        "open(dst, 'wb').write(b'GGUF-' + quant.encode() + b'-fake')\n"
    )
    script.chmod(0o755)
    events = []
    requant_model(
        "qwen3.5:4b",
        work_dir=tmp_path / "work", on_event=events.append,
        _models_dir=env_setup["models"],
    )
    kinds = [e["type"] for e in events]
    assert kinds == [
        "found", "quantize_progress", "quantize_progress",
        "quantized", "created",
    ]
    progress = [e for e in events if e["type"] == "quantize_progress"]
    assert [(e["done"], e["total"]) for e in progress] == [(1, 2), (2, 2)]


# -- S22: tool errors in plain words (requant side) --------------------

def test_run_translates_requantize_disabled():
    """The raw 'requantizing from type q4_K is disabled' becomes
    a plain-words message — with the raw line kept as a detail."""
    from stella.requant import _run

    code = (
        "import sys\n"
        "sys.stderr.write('error: requantizing from type q4_K '\n"
        "                 'is disabled\\n')\n"
        "sys.exit(1)\n"
    )
    with pytest.raises(StellaError) as excinfo:
        _run([sys.executable, "-c", code], what="Shrinking 'x' to Q4_K_M")
    message = str(excinfo.value)
    assert "already quantized" in message
    assert "too old" in message
    assert "requantizing from type q4_K is disabled" in message
    assert "The tool said:" in message


def test_run_unknown_error_keeps_raw_tail():
    """An unmapped error still shows its raw tail, behind a
    plain-words lead."""
    from stella.requant import _run

    code = (
        "import sys\n"
        "sys.stderr.write('weird boom 12345\\n')\n"
        "sys.exit(1)\n"
    )
    with pytest.raises(StellaError) as excinfo:
        _run([sys.executable, "-c", code], what="Shrinking 'x' to Q4_K_M")
    message = str(excinfo.value)
    assert "The tool failed." in message
    assert "weird boom 12345" in message
