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
    # The import keeps the exported settings exactly (whatever this
    # PC's auto-config picked for the source project).
    source = seeded.get_project("lfm3-tool", "tool-calls")
    assert proj["settings"]["rank"] == source["settings"]["rank"]
    assert proj["settings"] == source["settings"]
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


def _rewrite_manifest(pkg, mutate):
    manifest_path = pkg / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    mutate(manifest)
    manifest_path.write_text(json.dumps(manifest))
    return manifest


def _home_snapshot(store):
    """Every file under the home, as {relative path: bytes}."""
    out = {}
    for path in sorted(store.home.rglob("*")):
        if path.is_file():
            out[str(path.relative_to(store.home))] = path.read_bytes()
    return out


# -- T38: export must not crash on metamorph null -------------------


def _corrupt_project_json(store, profile, project, mutate):
    manifest = store.project_dir(profile, project) / "project.json"
    data = json.loads(manifest.read_text())
    mutate(data)
    manifest.write_text(json.dumps(data))


def test_export_null_metamorph(seeded, tmp_path):
    _corrupt_project_json(
        seeded, "lfm3-tool", "tool-calls",
        lambda d: d.update(metamorph=None),
    )
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["project"]["metamorph"]["mode"] == "morph"
    # The full package is there, not a partial one.
    assert (out / "README.md").is_file()
    assert (out / "weights").is_dir()
    assert (out / "checkpoints").is_dir()
    assert "MetaMorphAi mode: **morph**" in (out / "README.md").read_text()


def test_export_missing_metamorph_key(seeded, tmp_path):
    _corrupt_project_json(
        seeded, "lfm3-tool", "tool-calls",
        lambda d: d.pop("metamorph"),
    )
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["project"]["metamorph"]["mode"] == "morph"


def test_export_failure_leaves_no_partial_package(seeded, tmp_path, monkeypatch):
    import shutil

    # A checkpoint file exists, so the copy step runs — and fails.
    ckpt = seeded.project_dir("lfm3-tool", "tool-calls") / "checkpoints"
    (ckpt / "step-1.safetensors").write_bytes(b"fake-weights")
    dest = tmp_path / "exports"
    dest.mkdir()
    real_copy2 = shutil.copy2

    def boom(*args, **kwargs):
        raise OSError("disk went away")

    monkeypatch.setattr(shutil, "copy2", boom)
    with pytest.raises(OSError):
        export_mod.export_project(seeded, "lfm3-tool", "tool-calls", dest)
    # No package folder, no staging dir left behind — and a retry
    # works once the disk is back.
    assert list(dest.iterdir()) == []
    monkeypatch.setattr(shutil, "copy2", real_copy2)
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", dest)
    assert (out / "checkpoints" / "step-1.safetensors").is_file()


# -- T1: strict manifest validation + atomic import -----------------


def _bad_manifest_cases():
    return [
        ("settings as a string",
         lambda m: m["project"].update(settings="rank 8")),
        ("settings as a list",
         lambda m: m["project"].update(settings=[["rank", 8]])),
        ("config as a string",
         lambda m: m["profile"].update(config="ctx 8192")),
        ("dependencies as a string",
         lambda m: m["profile"].update(dependencies="torch")),
        ("dependencies with a non-string item",
         lambda m: m["profile"].update(dependencies=["torch", 7])),
        ("status banana",
         lambda m: m["project"].update(status="banana")),
        ("status as a number",
         lambda m: m["project"].update(status=7)),
        ("metamorph as a string",
         lambda m: m["project"].update(metamorph="both")),
        ("metamorph as an int",
         lambda m: m["project"].update(metamorph=7)),
        ("metamorph mode unknown",
         lambda m: m["project"]["metamorph"].update(mode="shrink")),
        ("role as a number",
         lambda m: m["profile"].update(role=7)),
        ("dataset_ref as a list",
         lambda m: m["project"].update(dataset_ref=["a.jsonl"])),
    ]


@pytest.mark.parametrize("name, mutate", _bad_manifest_cases(),
                         ids=[c[0] for c in _bad_manifest_cases()])
def test_verify_rejects_bad_manifest_variant(seeded, tmp_path, name, mutate):
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    _rewrite_manifest(out, mutate)
    with pytest.raises(StellaError):
        export_mod.verify_export(out)


@pytest.mark.parametrize("name, mutate", _bad_manifest_cases(),
                         ids=[c[0] for c in _bad_manifest_cases()])
def test_import_rejects_bad_manifest_and_leaves_home_untouched(
    seeded, tmp_path, name, mutate
):
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    _rewrite_manifest(out, mutate)
    fresh = Store(tmp_path / "fresh-home")
    before = _home_snapshot(fresh)
    with pytest.raises(StellaError):
        export_mod.import_export(fresh, out)
    # No orphan profile, no partial anything: byte-identical home.
    assert _home_snapshot(fresh) == before
    assert fresh.list_profiles() == []


def test_import_rejects_bad_settings_value_atomically(seeded, tmp_path):
    # A bad settings VALUE (T6's rule) is also caught before the
    # profile is created — never an orphan profile.
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    _rewrite_manifest(
        out, lambda m: m["project"]["settings"].update(rank=-5)
    )
    fresh = Store(tmp_path / "fresh-home")
    with pytest.raises(StellaError, match="rank"):
        export_mod.import_export(fresh, out)
    assert fresh.list_profiles() == []


def test_import_normalizes_uppercase_names(seeded, tmp_path):
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    _rewrite_manifest(
        out,
        lambda m: (
            m["profile"].update(name="Zebra-Prof"),
            m["project"].update(name="Zebra-Proj"),
        ),
    )
    fresh = Store(tmp_path / "fresh-home")
    result = export_mod.import_export(fresh, out)
    # Returned names equal the stored names.
    assert result == {
        "profile": "zebra-prof",
        "profile_existed": False,
        "project": "zebra-proj",
    }
    assert fresh.get_profile("zebra-prof")["name"] == "zebra-prof"
    assert fresh.get_project("zebra-prof", "zebra-proj")["name"] == "zebra-proj"


def test_import_rolls_back_on_late_failure(seeded, tmp_path, monkeypatch):
    # Even a failure AFTER the profile is created (here: the
    # checkpoints copy dies) rolls the home back to how it was.
    import shutil

    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    fresh = Store(tmp_path / "fresh-home")
    real_copy2 = shutil.copy2
    calls = {"n": 0}

    def boom_once(*args, **kwargs):
        calls["n"] += 1
        raise OSError("disk went away")

    # Let the first copy (notes) through, fail on checkpoints? The
    # import copies checkpoints before notes — fail everything and
    # the rollback still has to remove the created profile.
    monkeypatch.setattr(shutil, "copy2", boom_once)
    (out / "checkpoints" / "step-1.bin").write_bytes(b"x")
    with pytest.raises(OSError):
        export_mod.import_export(fresh, out)
    assert fresh.list_profiles() == []
    assert _home_snapshot(fresh) == {}
    monkeypatch.setattr(shutil, "copy2", real_copy2)
