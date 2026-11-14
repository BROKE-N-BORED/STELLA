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
        "src, dst, quant = sys.argv[1], sys.argv[2], sys.argv[3]\n"
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
            src, dst, quant = Path(cmd[1]), Path(cmd[2]), cmd[3]
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


def test_resolve_blob_via_modelfile_fallback(tmp_path, monkeypatch):
    models = tmp_path / "ollama-models"
    models.mkdir()
    blob = tmp_path / "somewhere.gguf"
    blob.write_bytes(_gguf_header(8) + b"\x00" * 10)
    bindir = fake_ollama_bin(tmp_path, show_from=str(blob))
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    assert resolve_model_blob("fallback:1b", models) == blob


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
