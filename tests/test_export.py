"""Export / import tests, including the full round-trip."""
import json

import pytest

from stella import export as export_mod
from stella.model import StellaError, Store


def test_export_structure(seeded, tmp_path):
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    assert out.name == "tool-calls-stella-export"
    assert (out / "manifest.json").is_file()
    assert (out / "config.json").is_file()
    assert (out / "README.md").is_file()
    assert (out / "weights" / "README.txt").is_file()
    assert (out / "checkpoints").is_dir()
    assert (out / "notes.md").is_file()
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["kind"] == "stella-export"
    assert manifest["profile"]["ollama_tag"] == "lfm3:1.7b"
    assert manifest["profile"]["role"] == "fast"
    assert manifest["project"]["metamorph"]["mode"] == "both"
    assert manifest["project"]["dataset_ref"] == "forge-traces.jsonl"


def test_export_copies_checkpoints(seeded, tmp_path):
    ckpt = seeded.project_dir("lfm3-tool", "tool-calls") / "checkpoints"
    (ckpt / "step-100.safetensors").write_bytes(b"fake-weights")
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    assert (out / "checkpoints" / "step-100.safetensors").read_bytes() == b"fake-weights"


def test_export_refuses_existing_dir(seeded, tmp_path):
    export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    with pytest.raises(StellaError):
        export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)


def test_export_missing_project(seeded, tmp_path):
    with pytest.raises(StellaError):
        export_mod.export_project(seeded, "lfm3-tool", "ghost", tmp_path)


def test_verify_accepts_good_export(seeded, tmp_path):
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    manifest = export_mod.verify_export(out)
    assert manifest["project"]["name"] == "tool-calls"


def test_verify_rejects_not_an_export(tmp_path):
    with pytest.raises(StellaError):
        export_mod.verify_export(tmp_path)


def test_verify_rejects_bad_metamorph(seeded, tmp_path):
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    manifest = json.loads((out / "manifest.json").read_text())
    manifest["project"]["metamorph"]["mode"] = "shrink"
    (out / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(StellaError):
        export_mod.verify_export(out)


def test_verify_rejects_bad_json(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "manifest.json").write_text("{not json")
    with pytest.raises(StellaError):
        export_mod.verify_export(pkg)


def test_round_trip_into_fresh_home(seeded, tmp_path):
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    fresh = Store(tmp_path / "fresh-home")
    result = export_mod.import_export(fresh, out)
    assert result == {"profile": "lfm3-tool", "profile_existed": False,
                      "project": "tool-calls"}
    prof = fresh.get_profile("lfm3-tool")
    assert prof["ollama_tag"] == "lfm3:1.7b"
    assert prof["role"] == "fast"
    proj = fresh.get_project("lfm3-tool", "tool-calls")
    assert proj["dataset_ref"] == "forge-traces.jsonl"
    assert proj["metamorph"]["mode"] == "both"
    assert proj["settings"]["rank"] == 8
    # Notes came along too.
    seeded.write_notes("lfm3-tool", "tool-calls", "hello notes")
    out2 = export_mod.export_project(seeded, "lfm3-tool", "tool-calls",
                                     tmp_path / "second")
    fresh2 = Store(tmp_path / "fresh-home-2")
    export_mod.import_export(fresh2, out2)
    assert fresh2.read_notes("lfm3-tool", "tool-calls") == "hello notes"


def test_import_into_existing_profile(seeded, tmp_path):
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    other = Store(tmp_path / "other-home")
    other.create_profile("lfm3-tool", ollama_tag="lfm3:1.7b", role="fast")
    result = export_mod.import_export(other, out)
    assert result["profile_existed"] is True
    assert other.get_project("lfm3-tool", "tool-calls")["name"] == "tool-calls"


def test_import_rejects_duplicate_project(seeded, tmp_path):
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    with pytest.raises(StellaError):
        export_mod.import_export(seeded, out)
