"""Export / import tests, including the full round-trip."""
import json

import pytest

from stella import export as export_mod
from stella.model import StellaError, Store


def test_export_structure(seeded, tmp_path):
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    assert out.name == "tool-calls-stella-export"
    assert (out / "manifest.json").is_file()
    # T60: no config.json — the manifest holds the settings.
    assert not (out / "config.json").exists()
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
                      "profile_diff": {}, "profile_choice": None,
                      "project": "tool-calls", "warnings": []}
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


def test_package_without_config_json_imports(seeded, tmp_path):
    # T60: a package without config.json imports — the file is no
    # longer required (and no longer written).
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    assert not (out / "config.json").exists()
    fresh = Store(tmp_path / "fresh-home")
    result = export_mod.import_export(fresh, out)
    assert result["project"] == "tool-calls"
    source = seeded.get_project("lfm3-tool", "tool-calls")
    assert fresh.get_project("lfm3-tool", "tool-calls")["settings"] == (
        source["settings"]
    )


def test_disagreeing_config_json_imports_with_manifest_values(
    seeded, tmp_path
):
    # T60: an old package carrying a config.json that disagrees
    # with the manifest imports with the MANIFEST's values — the
    # file is ignored, never read.
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    (out / "config.json").write_text(
        json.dumps({"rank": 999, "method": "lora"}) + "\n"
    )
    fresh = Store(tmp_path / "fresh-home")
    export_mod.import_export(fresh, out)
    source = seeded.get_project("lfm3-tool", "tool-calls")
    assert fresh.get_project("lfm3-tool", "tool-calls")["settings"] == (
        source["settings"]
    )
    assert (
        fresh.get_project("lfm3-tool", "tool-calls")["settings"]["rank"]
        != 999
    )


def test_invalid_json_config_json_imports(seeded, tmp_path):
    # T60: an old package carrying an invalid-JSON config.json
    # imports fine — the file is never parsed.
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    (out / "config.json").write_text("{ not json at all\n")
    fresh = Store(tmp_path / "fresh-home")
    result = export_mod.import_export(fresh, out)
    assert result["project"] == "tool-calls"


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
        "profile_diff": {},
        "profile_choice": None,
        "project": "zebra-proj",
        "warnings": [],
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


# -- T40: versioned format + named kinds -----------------------------


def test_export_stamps_format_1(seeded, tmp_path):
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["format"] == 1
    assert manifest["kind"] == "stella-export"


def test_verify_rejects_newer_format(seeded, tmp_path):
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    _rewrite_manifest(out, lambda m: m.update(format=99))
    with pytest.raises(StellaError) as exc:
        export_mod.verify_export(out)
    assert "needs a newer Stella" in str(exc.value)
    assert "99" in str(exc.value)


def test_verify_rejects_bad_format_type(seeded, tmp_path):
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    _rewrite_manifest(out, lambda m: m.update(format="1"))
    with pytest.raises(StellaError, match="whole number"):
        export_mod.verify_export(out)
    out2 = export_mod.export_project(
        seeded, "lfm3-tool", "tool-calls", tmp_path / "second"
    )
    _rewrite_manifest(out2, lambda m: m.update(format=0))
    with pytest.raises(StellaError, match="unknown package format"):
        export_mod.verify_export(out2)


def test_legacy_package_without_format_imports(seeded, tmp_path):
    # A v0.1-v0.12 package carries no format field: it reads as
    # format 1 and imports as usual (the documented legacy rule).
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    _rewrite_manifest(out, lambda m: m.pop("format"))
    manifest = export_mod.verify_export(out)
    assert manifest["project"]["name"] == "tool-calls"
    fresh = Store(tmp_path / "fresh-home")
    result = export_mod.import_export(fresh, out)
    assert result["project"] == "tool-calls"


def test_package_kinds_are_defined_in_one_place():
    assert set(export_mod.PACKAGE_KINDS) == {
        "stella-export",
        "stella-profile-export",
        "stella-recipe-export",
    }


def test_verify_names_a_known_but_unimportable_kind(seeded, tmp_path):
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    _rewrite_manifest(out, lambda m: m.update(kind="stella-profile-export"))
    with pytest.raises(StellaError) as exc:
        export_mod.verify_export(out)
    assert "profile package" in str(exc.value)
    assert "only import project packages" in str(exc.value)


def test_verify_rejects_unknown_kind(seeded, tmp_path):
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    _rewrite_manifest(out, lambda m: m.update(kind="banana"))
    with pytest.raises(StellaError, match="bad manifest kind"):
        export_mod.verify_export(out)


# -- T41: round-trip weights/ and probe results ----------------------


def _plant_adapter(store, files=None):
    """A fake trained adapter in the seeded project, so export has
    real weights to carry."""
    adapter = store.project_dir("lfm3-tool", "tool-calls") / "adapter"
    adapter.mkdir(exist_ok=True)
    files = files or {
        "adapter_config.json": b'{"r": 8}',
        "adapter_model.safetensors": b"fake-adapter-bytes",
    }
    for name, content in files.items():
        (adapter / name).write_bytes(content)
    return adapter


def test_weights_round_trip_byte_identical(seeded, tmp_path):
    _plant_adapter(seeded)
    seeded.update_project("lfm3-tool", "tool-calls", status="done")
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    assert (out / "weights" / "adapter_model.safetensors").is_file()
    fresh = Store(tmp_path / "fresh-home")
    result = export_mod.import_export(fresh, out)
    assert result["warnings"] == []
    adapter = fresh.project_dir("lfm3-tool", "tool-calls") / "adapter"
    assert (adapter / "adapter_model.safetensors").read_bytes() == (
        b"fake-adapter-bytes"
    )
    assert (adapter / "adapter_config.json").read_bytes() == b'{"r": 8}'
    # The finished status survives when the weights are really there.
    assert fresh.get_project("lfm3-tool", "tool-calls")["status"] == "done"


def test_probe_results_round_trip_byte_identical(seeded, tmp_path):
    probe = {"before": {"rate": 0.0}, "after": {"rate": 0.0}, "delta": 0.0}
    pdir = seeded.project_dir("lfm3-tool", "tool-calls")
    (pdir / "probe_results.json").write_text(json.dumps(probe))
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    fresh = Store(tmp_path / "fresh-home")
    export_mod.import_export(fresh, out)
    imported = fresh.project_dir("lfm3-tool", "tool-calls") / "probe_results.json"
    assert json.loads(imported.read_text()) == probe


def test_legacy_trained_package_imports_as_done(seeded, tmp_path):
    # T53: a v0.1-v0.12 package whose manifest says "trained"
    # imports as "done" (with weights, so the status survives).
    _plant_adapter(seeded)
    seeded.update_project("lfm3-tool", "tool-calls", status="done")
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    manifest = json.loads((out / "manifest.json").read_text())
    manifest["project"]["status"] = "trained"
    (out / "manifest.json").write_text(json.dumps(manifest))
    fresh = Store(tmp_path / "fresh-home")
    export_mod.import_export(fresh, out)
    assert fresh.get_project("lfm3-tool", "tool-calls")["status"] == "done"


def test_weightless_done_package_imports_as_draft(seeded, tmp_path):
    # The verdict's case (R1): the manifest claims "done", the
    # package carries only the placeholder note. The project must
    # not claim to be finished.
    seeded.update_project("lfm3-tool", "tool-calls", status="done")
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    assert (out / "weights" / "README.txt").is_file()
    fresh = Store(tmp_path / "fresh-home")
    result = export_mod.import_export(fresh, out)
    assert fresh.get_project("lfm3-tool", "tool-calls")["status"] == "draft"
    assert len(result["warnings"]) == 1
    assert "no trained weights" in result["warnings"][0]
    assert "draft" in result["warnings"][0]


def test_weightless_exported_package_imports_as_draft(seeded, tmp_path):
    seeded.update_project("lfm3-tool", "tool-calls", status="exported")
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    fresh = Store(tmp_path / "fresh-home")
    result = export_mod.import_export(fresh, out)
    assert fresh.get_project("lfm3-tool", "tool-calls")["status"] == "draft"
    assert result["warnings"]


def test_placeholder_note_is_not_copied_as_a_weight(seeded, tmp_path):
    # A v0.1-era package (placeholder only) still imports — and no
    # adapter/ dir is conjured from the placeholder note.
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    fresh = Store(tmp_path / "fresh-home")
    result = export_mod.import_export(fresh, out)
    assert result["warnings"] == []
    pdir = fresh.project_dir("lfm3-tool", "tool-calls")
    assert not (pdir / "adapter").exists()
    assert fresh.get_project("lfm3-tool", "tool-calls")["status"] == "draft"


# -- T57: merge, don't discard, the profile block on import --------


def _home_with_profile(tmp_path, name, tag, role, base=""):
    """A home whose profile already exists, with no projects yet."""
    home = Store(tmp_path / name)
    home.create_profile("lfm3-tool", ollama_tag=tag, role=role,
                        base_ref=base)
    return home


def test_compare_profile_block(seeded):
    local = {"ollama_tag": "a:1", "role": "fast", "base_ref": "B",
             "display_name": "Mine", "config": {"x": 1}}
    package = {"ollama_tag": "a:2", "role": "fast", "base_ref": "B",
               "display_name": "Theirs", "config": {}}
    diff = export_mod.compare_profile_block(local, package)
    assert diff == {"ollama_tag": {"local": "a:1", "package": "a:2"}}
    # Identical blocks (other fields ignored) -> no diff.
    assert export_mod.compare_profile_block(local, dict(local)) == {}
    assert export_mod.describe_profile_diff(diff) == "tag"
    assert export_mod.describe_profile_diff(
        {"ollama_tag": {}, "role": {}, "base_ref": {}}) == (
        "tag, role and base")


def test_import_identical_profile_block_is_silent(seeded, tmp_path):
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls",
                                    tmp_path)
    home = _home_with_profile(tmp_path, "same", "lfm3:1.7b", "fast")
    result = export_mod.import_export(home, out)
    assert result["profile_existed"] is True
    assert result["profile_diff"] == {}
    assert result["profile_choice"] is None
    assert result["warnings"] == []
    prof = home.get_profile("lfm3-tool")
    assert (prof["ollama_tag"], prof["role"]) == ("lfm3:1.7b", "fast")


def test_import_differing_profile_keeps_local_by_default(
        seeded, tmp_path):
    # The audit probe: tag other:9b / role driver already here,
    # package carries lfm3:1.7b / fast. No choice mechanism -> the
    # local values win, and the warning names the fields.
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls",
                                    tmp_path)
    home = _home_with_profile(tmp_path, "diff", "other:9b", "driver")
    result = export_mod.import_export(home, out)
    assert result["profile_diff"] == {
        "ollama_tag": {"local": "other:9b", "package": "lfm3:1.7b"},
        "role": {"local": "driver", "package": "fast"},
        # The local base follows its tag (other:9b), the package's
        # follows its tag (lfm3:1.7b) — so the base differs too.
        "base_ref": {"local": "other:9b", "package": "lfm3:1.7b"},
    }
    assert result["profile_choice"] == "keep"
    assert len(result["warnings"]) == 1
    assert "tag, role and base" in result["warnings"][0]
    assert "kept" in result["warnings"][0]
    prof = home.get_profile("lfm3-tool")
    assert (prof["ollama_tag"], prof["role"]) == ("other:9b", "driver")


def test_import_differing_profile_takes_package_when_chosen(
        seeded, tmp_path):
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls",
                                    tmp_path)
    home = _home_with_profile(tmp_path, "take", "other:9b", "driver",
                              base="other/weights")
    result = export_mod.import_export(home, out, profile_choice="take")
    assert result["profile_choice"] == "take"
    assert result["warnings"] == []
    prof = home.get_profile("lfm3-tool")
    # The package's block exactly: its base follows its own tag.
    assert (prof["ollama_tag"], prof["role"], prof["base_ref"]) == (
        "lfm3:1.7b", "fast", "lfm3:1.7b")


def test_import_differing_profile_keeps_local_when_chosen(
        seeded, tmp_path):
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls",
                                    tmp_path)
    home = _home_with_profile(tmp_path, "keep", "other:9b", "driver")
    result = export_mod.import_export(home, out, profile_choice="keep")
    assert result["profile_choice"] == "keep"
    # An explicit choice needs no warning — the user chose.
    assert result["warnings"] == []
    prof = home.get_profile("lfm3-tool")
    assert (prof["ollama_tag"], prof["role"]) == ("other:9b", "driver")


def test_import_profile_conflict_callback_decides(seeded, tmp_path):
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls",
                                    tmp_path)
    seen = {}

    def ask(slug, diff):
        seen["slug"] = slug
        seen["diff"] = diff
        return "take"

    home = _home_with_profile(tmp_path, "cb", "other:9b", "driver")
    result = export_mod.import_export(home, out, on_profile_conflict=ask)
    assert seen["slug"] == "lfm3-tool"
    assert set(seen["diff"]) == {"ollama_tag", "role", "base_ref"}
    assert result["profile_choice"] == "take"
    assert home.get_profile("lfm3-tool")["ollama_tag"] == "lfm3:1.7b"


def test_import_take_merge_rolls_back_on_late_failure(
        seeded, tmp_path):
    # The profile already exists AND the project does too: the
    # take-merge runs, then create_project fails — the profile
    # must come back with its old values.
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls",
                                    tmp_path)
    home = _home_with_profile(tmp_path, "rb", "other:9b", "driver")
    home.create_project("lfm3-tool", "tool-calls")
    with pytest.raises(StellaError):
        export_mod.import_export(home, out, profile_choice="take")
    prof = home.get_profile("lfm3-tool")
    assert (prof["ollama_tag"], prof["role"]) == ("other:9b", "driver")


def test_import_rejects_bad_profile_choice(seeded, tmp_path):
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls",
                                    tmp_path)
    fresh = Store(tmp_path / "fresh-home")
    with pytest.raises(StellaError, match="profile_choice"):
        export_mod.import_export(fresh, out, profile_choice="merge")
