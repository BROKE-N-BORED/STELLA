"""Ollama-to-training bridge tests (S23).

No network: the curated map is pinned in code, and the Hub
existence of every repo in it was verified by hand on 2026-11-15
(see ollama_bridge.KNOWN_BRIDGE). The Modelfile hint is faked by
patching requant._modelfile_blob.
"""
import pytest

from stella.model import StellaError
from stella.ollama_bridge import (
    bridge_error_message,
    classify_base_ref,
    format_bridge_report,
    suggest_hf_repos,
)
from test_cli import run_cli


def test_suggest_known_tags():
    assert suggest_hf_repos("lfm3") == [
        {"repo": "LiquidAI/LFM3-1.7B",
         "source": "Liquid AI's own repo for this model"}
    ]
    assert suggest_hf_repos("lfm3:1.7b")[0]["repo"] == "LiquidAI/LFM3-1.7B"
    assert suggest_hf_repos("qwen3.5:4b") == [
        {"repo": "Qwen/Qwen3.5-4B",
         "source": "Qwen's own repo for this model"}
    ]
    assert suggest_hf_repos("qwen3.5:2b")[0]["repo"] == "Qwen/Qwen3.5-2B"
    assert suggest_hf_repos("qwen3-vl:2b-instruct")[0]["repo"] == (
        "Qwen/Qwen3-VL-2B-Instruct"
    )
    assert suggest_hf_repos("qwen2.5-coder:1.5b")[0]["repo"] == (
        "Qwen/Qwen2.5-Coder-1.5B"
    )
    assert suggest_hf_repos(
        "huihui_ai/qwen2.5-coder-abliterate:1.5b"
    )[0]["repo"] == "Qwen/Qwen2.5-Coder-1.5B"
    assert suggest_hf_repos("maternion/minicpm5-heretic:2b") == [
        {"repo": "openbmb/MiniCPM5-2B",
         "source": "the base model this Ollama tag is tuned from"}
    ]


def test_suggest_tag_without_version_lists_versions():
    repos = [c["repo"] for c in suggest_hf_repos("qwen3.5")]
    assert repos == ["Qwen/Qwen3.5-2B", "Qwen/Qwen3.5-4B"]
    # Both qwen3-vl entries point at the same repo: deduped.
    assert suggest_hf_repos("qwen3-vl") == [
        {"repo": "Qwen/Qwen3-VL-2B-Instruct",
         "source": "Qwen's own repo for this model"}
    ]


def test_suggest_unknown_tag_is_empty_not_a_guess():
    # bonsai-2 has no verifiable Hub transformers repo, so it
    # stays unknown — never a fabricated guess.
    assert suggest_hf_repos("eriktonon/bonsai-2-uncensored:2b") == []
    assert suggest_hf_repos("ghost-model:9b") == []
    assert suggest_hf_repos("") == []


def test_suggest_matches_case_insensitively():
    assert suggest_hf_repos("Qwen3.5:4B")[0]["repo"] == "Qwen/Qwen3.5-4B"


def test_classify_base_ref(tmp_path):
    assert classify_base_ref("model.gguf")[0] == "gguf"
    assert classify_base_ref("MODEL.GGUF")[0] == "gguf"
    assert classify_base_ref("qwen3.5:4b")[0] == "ollama"
    assert classify_base_ref("lfm3")[0] == "ollama"
    assert classify_base_ref("huihui_ai/qwen2.5-coder-abliterate:1.5b")[0] == (
        "ollama"
    )
    assert classify_base_ref("Qwen/Qwen2.5-Coder-1.5B")[0] == "hf"
    assert classify_base_ref("LiquidAI/LFM3-1.7B")[0] == "hf"
    folder = tmp_path / "weights"
    folder.mkdir()
    assert classify_base_ref(str(folder))[0] == "local"


def test_bridge_error_known_tag_names_repo_and_command():
    message = bridge_error_message("qwen3.5:4b")
    assert "Ollama tag" in message
    assert "Qwen/Qwen3.5-4B" in message
    assert "stella bridge qwen3.5:4b" in message
    assert "Hugging Face transformers weights" in message


def test_bridge_error_unknown_tag_says_so():
    message = bridge_error_message("ghost-model:9b")
    assert "doesn't know" in message
    assert "huggingface.co" in message
    # No fabricated repo id anywhere in the message.
    assert "Qwen/" not in message
    assert "LiquidAI/" not in message


def test_bridge_error_gguf():
    message = bridge_error_message("model-q4_k_m.gguf")
    assert "GGUF file" in message
    assert "Hugging Face transformers weights" in message


def test_load_model_metadata_refuses_tag_without_network(monkeypatch):
    # S23: the tag is caught before any Hub fetch — the fetch is
    # rigged to explode, so reaching it would fail the test.
    import stella.train as train_mod
    from stella.train import load_model_metadata

    def _boom(*args, **kwargs):
        raise AssertionError("the tag reached the network")

    monkeypatch.setattr(train_mod, "_fetch_hf_file", _boom)
    with pytest.raises(StellaError) as excinfo:
        load_model_metadata("qwen3.5:4b")
    assert "stella bridge qwen3.5:4b" in str(excinfo.value)
    with pytest.raises(StellaError, match="GGUF file"):
        load_model_metadata("model-q4_k_m.gguf")


def test_train_project_refuses_tag_with_bridge_error(tmp_path):
    from stella.model import Store
    from stella.train import train_project

    store = Store(tmp_path / "home")
    store.create_profile("g", base_ref="qwen3.5:4b")
    store.create_project("g", "p")
    with pytest.raises(StellaError) as excinfo:
        train_project(store, "g", "p")
    message = str(excinfo.value)
    assert "Qwen/Qwen3.5-4B" in message
    assert "stella bridge qwen3.5:4b" in message


def test_bridge_report_known_tag(monkeypatch):
    import stella.requant as requant_mod

    monkeypatch.setattr(
        requant_mod, "_modelfile_blob", lambda tag: None
    )
    report = format_bridge_report("qwen3.5:4b")
    assert "Qwen/Qwen3.5-4B" in report
    assert "update-profile <profile> --base Qwen/Qwen3.5-4B" in report


def test_bridge_report_unknown_tag(monkeypatch):
    import stella.requant as requant_mod

    monkeypatch.setattr(
        requant_mod, "_modelfile_blob", lambda tag: None
    )
    report = format_bridge_report("ghost-model:9b")
    assert "doesn't know" in report
    assert "update-profile <profile> --base owner/model-name" in report


def test_bridge_report_names_modelfile_blob(monkeypatch, tmp_path):
    import stella.requant as requant_mod

    blob = tmp_path / "sha256-abc"
    blob.write_bytes(b"GGUF")
    monkeypatch.setattr(
        requant_mod, "_modelfile_blob", lambda tag: blob
    )
    report = format_bridge_report("qwen3.5:4b")
    assert "sha256-abc" in report
    assert "not weights training can use" in report


def test_cli_bridge_known_tag(home, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    res = run_cli(home, "bridge", "qwen3.5:4b")
    assert res.returncode == 0, res.stderr
    assert "Qwen/Qwen3.5-4B" in res.stdout
    assert "stella update-profile" in res.stdout


def test_cli_bridge_unknown_tag(home, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    res = run_cli(home, "bridge", "ghost-model:9b")
    assert res.returncode == 0, res.stderr
    assert "doesn't know" in res.stdout
