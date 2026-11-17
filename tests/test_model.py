"""Data-model tests: profiles, projects, validation, notes."""
import json
import re

import pytest

from stella.model import StellaError, validate_slug


def test_create_and_list_profile(store):
    data = store.create_profile(
        "lfm3-tool", ollama_tag="lfm3:1.7b", role="fast"
    )
    assert data["name"] == "lfm3-tool"
    assert data["role"] == "fast"
    assert data["ollama_tag"] == "lfm3:1.7b"
    assert data["kind"] == "profile"
    profiles = store.list_profiles()
    assert [p["name"] for p in profiles] == ["lfm3-tool"]
    # Manifest on disk is human-readable JSON.
    text = (store.home / "profiles" / "lfm3-tool" / "profile.json").read_text()
    assert json.loads(text)["role"] == "fast"


def test_profile_manifest_round_trip(store):
    store.create_profile("p1", ollama_tag="a:1b", role="driver",
                         config={"ctx": 8192}, dependencies=["x"])
    again = store.get_profile("p1")
    assert again["config"] == {"ctx": 8192}
    assert again["dependencies"] == ["x"]


def test_duplicate_profile_rejected(store):
    store.create_profile("p1")
    with pytest.raises(StellaError):
        store.create_profile("p1")


def test_missing_profile(store):
    with pytest.raises(StellaError):
        store.get_profile("nope")


def test_update_profile(store):
    store.create_profile("p1", role="fast")
    updated = store.update_profile("p1", role="reviewer", display_name="Rev")
    assert updated["role"] == "reviewer"
    assert updated["display_name"] == "Rev"
    assert store.get_profile("p1")["role"] == "reviewer"


def test_update_profile_rejects_unknown_field(store):
    store.create_profile("p1")
    with pytest.raises(StellaError):
        store.update_profile("p1", name="other")


def test_rename_profile(store):
    store.create_profile("old", role="fast")
    store.create_project("old", "proj")
    renamed = store.rename_profile("old", "new")
    assert renamed["name"] == "new"
    assert store.get_project("new", "proj")["profile"] == "new"
    with pytest.raises(StellaError):
        store.get_profile("old")
    assert (store.home / "profiles" / "new" / "profile.json").is_file()


def test_tag_update_syncs_base_ref(store):
    # T54: the audit probe — update a tag and base_ref follows it.
    store.create_profile("p1", ollama_tag="lfm3:1.7b")
    assert store.get_profile("p1")["base_ref"] == "lfm3:1.7b"
    updated = store.update_profile("p1", ollama_tag="lfm3:2b")
    assert updated["base_ref"] == "lfm3:2b"


def test_tag_update_keeps_split_base_ref(store):
    # T54: a base_ref that differs from the old tag is a deliberate
    # split — it stays.
    store.create_profile(
        "p1", ollama_tag="lfm3:1.7b", base_ref="LiquidAI/LFM3-1.7B"
    )
    updated = store.update_profile("p1", ollama_tag="lfm3:2b")
    assert updated["base_ref"] == "LiquidAI/LFM3-1.7B"


def test_tag_update_syncs_empty_base_ref(store):
    # T54: an empty base_ref follows the new tag too.
    store.create_profile("p1")
    updated = store.update_profile("p1", ollama_tag="lfm3:2b")
    assert updated["base_ref"] == "lfm3:2b"


def test_explicit_base_ref_wins_over_sync(store):
    # T54: a base_ref passed in the same call always wins.
    store.create_profile("p1", ollama_tag="lfm3:1.7b")
    updated = store.update_profile(
        "p1", ollama_tag="lfm3:2b", base_ref="someone/else"
    )
    assert updated["base_ref"] == "someone/else"


def test_update_without_tag_change_leaves_base_ref(store):
    # T54: the sync only fires on a tag change.
    store.create_profile("p1", ollama_tag="lfm3:1.7b")
    updated = store.update_profile("p1", role="fast")
    assert updated["base_ref"] == "lfm3:1.7b"
    updated = store.update_profile("p1", ollama_tag="lfm3:1.7b")
    assert updated["base_ref"] == "lfm3:1.7b"


def test_rename_profile_collision(store):
    store.create_profile("a")
    store.create_profile("b")
    with pytest.raises(StellaError):
        store.rename_profile("a", "b")


def test_delete_profile(store):
    # T23: deleting moves to the trash, dated, contents intact.
    store.create_profile("p1")
    store.create_project("p1", "proj")
    trashed = store.delete_profile("p1")
    assert store.list_profiles() == []
    assert not (store.home / "profiles" / "p1").exists()
    assert trashed.is_dir()
    assert trashed.parent == store.trash_dir
    assert trashed.name.startswith("p1-")
    assert (trashed / "profile.json").is_file()
    assert (trashed / "projects" / "proj" / "project.json").is_file()


def test_delete_project_moves_to_trash_with_contents(store):
    # T23: checkpoints and notes survive the move to the trash.
    store.create_profile("p1")
    store.create_project("p1", "proj")
    store.write_notes("p1", "proj", "keep me\n")
    pdir = store.project_dir("p1", "proj")
    ckpt = pdir / "checkpoints" / "1"
    ckpt.mkdir(parents=True)
    (ckpt / "adapter_model.safetensors").write_bytes(b"w")
    trashed = store.delete_project("p1", "proj")
    assert store.list_projects("p1") == []
    assert trashed.name.startswith("p1-proj-")
    assert (trashed / "notes.md").read_text() == "keep me\n"
    assert (
        trashed / "checkpoints" / "1" / "adapter_model.safetensors"
    ).read_bytes() == b"w"


def test_trash_names_are_dated_and_unique(store):
    # T23: <base>-YYYYMMDD-HHMMSS, with a -2 suffix when two
    # deletes land in the same second.
    store.create_profile("p1")
    store.create_project("p1", "a")
    store.create_project("p1", "b")
    first = store.delete_project("p1", "a")
    second = store.delete_project("p1", "b")
    assert first.name != second.name
    for name in (first.name, second.name):
        assert re.search(r"-\d{8}-\d{6}(-\d+)?$", name), name
    entries = store.list_trash()
    assert {e["project"] for e in entries} == {"a", "b"}
    assert all(e["kind"] == "project" for e in entries)
    assert all(e["profile"] == "p1" for e in entries)
    assert all(e["trashed"].startswith("20") for e in entries)


def test_restore_by_moving_back(store):
    # T23: restoring is a plain move back — no special code needed.
    store.create_profile("p1")
    store.create_project("p1", "proj")
    trashed = store.delete_project("p1", "proj")
    dest = store.home / "profiles" / "p1" / "projects" / "proj"
    trashed.rename(dest)
    assert store.get_project("p1", "proj")["name"] == "proj"
    assert store.list_trash() == []


# -- R2: restore from the trash ---------------------------------------


def test_restore_trash_profile_opens_afterwards(store):
    """R2: a restored profile comes back under its real name and
    opens — the dated trash folder is not the name it keeps."""
    store.create_profile("p1", ollama_tag="x:1b")
    store.create_project("p1", "proj")
    trashed = store.delete_profile("p1")
    restored = store.restore_trash(trashed.name)
    assert restored == {
        "kind": "profile", "profile": "p1", "project": "",
    }
    assert store.get_profile("p1")["ollama_tag"] == "x:1b"
    assert [p["name"] for p in store.list_projects("p1")] == ["proj"]
    assert store.list_trash() == []


def test_restore_trash_project_keeps_contents(store):
    """R2: a restored project comes back with its notes and
    checkpoints, under its real name inside its profile."""
    store.create_profile("p1")
    store.create_project("p1", "proj")
    store.write_notes("p1", "proj", "keep me\n")
    ckpt = store.project_dir("p1", "proj") / "checkpoints" / "1"
    ckpt.mkdir(parents=True)
    (ckpt / "adapter_model.safetensors").write_bytes(b"w")
    trashed = store.delete_project("p1", "proj")
    restored = store.restore_trash(trashed.name)
    assert restored == {
        "kind": "project", "profile": "p1", "project": "proj",
    }
    assert store.get_project("p1", "proj")["name"] == "proj"
    assert store.read_notes("p1", "proj") == "keep me\n"
    assert (
        store.project_dir("p1", "proj") / "checkpoints" / "1"
        / "adapter_model.safetensors"
    ).read_bytes() == b"w"
    assert store.list_trash() == []


def test_restore_trash_refuses_name_clash(store):
    """R2: when a live profile with the same name exists, the
    restore is refused — nothing is renamed or overwritten, and
    the trashed item stays in the trash."""
    store.create_profile("p1")
    trashed = store.delete_profile("p1")
    store.create_profile("p1", ollama_tag="new:1b")
    with pytest.raises(StellaError, match="already exists"):
        store.restore_trash(trashed.name)
    assert trashed.is_dir()
    assert store.get_profile("p1")["ollama_tag"] == "new:1b"


def test_restore_trash_refuses_project_without_profile(store):
    """R2: a trashed project whose profile is gone is refused —
    restore the profile first."""
    store.create_profile("p1")
    store.create_project("p1", "proj")
    trashed = store.delete_project("p1", "proj")
    store.delete_profile("p1")
    with pytest.raises(StellaError, match="profile .* is gone"):
        store.restore_trash(trashed.name)
    assert trashed.is_dir()


def test_restore_trash_refuses_unknown_item(store):
    """R2: a trash folder with no manifest cannot be identified,
    so it cannot be restored."""
    store.trash_dir.mkdir(parents=True, exist_ok=True)
    mystery = store.trash_dir / "mystery-20260101-000000"
    mystery.mkdir()
    (mystery / "some-file.txt").write_text("x")
    with pytest.raises(StellaError, match="no manifest"):
        store.restore_trash(mystery.name)
    assert mystery.is_dir()


def test_restore_trash_rejects_paths(store):
    """R2: the restore name is a plain trash entry name, never a
    path — the same guard as purge."""
    with pytest.raises(StellaError):
        store.restore_trash("../profiles")
    with pytest.raises(StellaError):
        store.restore_trash("no-such-item")


def test_purge_trash_deletes_forever(store):
    # T23: purge is the only permanent delete.
    store.create_profile("p1")
    trashed = store.delete_profile("p1")
    store.purge_trash(trashed.name)
    assert not trashed.exists()
    assert store.list_trash() == []
    with pytest.raises(StellaError):
        store.purge_trash("no-such-item")
    with pytest.raises(StellaError):
        store.purge_trash("../profiles")


def test_empty_trash(store):
    # T23: emptying removes every trashed item, and reports how many.
    store.create_profile("p1")
    store.create_project("p1", "a")
    store.create_project("p1", "b")
    store.delete_project("p1", "a")
    store.delete_project("p1", "b")
    assert store.empty_trash() == 2
    assert store.list_trash() == []
    assert store.empty_trash() == 0


def test_destroy_methods_leave_no_trash(store):
    # T23: the import rollback's destroy path leaves the home
    # exactly as it was — no trash folder behind.
    store.create_profile("p1")
    store.create_project("p1", "proj")
    store._destroy_project("p1", "proj")
    store._destroy_profile("p1")
    assert store.list_profiles() == []
    assert not store.trash_dir.exists()


def test_create_project_defaults(store):
    # No explicit settings: this PC picks them (auto-config), so the
    # rank/seq match the computed recipe for this machine's RAM.
    from stella.autoconfig import compute_settings, measure_pc

    store.create_profile("p1")
    data = store.create_project("p1", "proj")
    expected = compute_settings(measure_pc(store.home)["ram_available_gb"])
    assert data["settings_source"] == "auto"
    assert data["settings"]["method"] == "lora"
    assert data["settings"]["rank"] == expected["rank"]
    assert data["settings"]["max_seq_len"] == expected["max_seq_len"]
    assert data["settings"]["learning_rate"] == 0.0002
    assert data["settings"]["epochs"] == 3
    assert data["settings"]["batch_size"] == 1
    assert data["metamorph"]["mode"] == "morph"
    assert data["status"] == "draft"
    pdir = store.home / "profiles" / "p1" / "projects" / "proj"
    assert (pdir / "checkpoints").is_dir()
    assert (pdir / "notes.md").is_file()


def test_create_project_needs_profile(store):
    with pytest.raises(StellaError):
        store.create_project("ghost", "proj")


def test_project_metamorph_modes(store):
    store.create_profile("p1")
    for mode in ("morph", "compress", "both"):
        store.create_project("p1", f"proj-{mode}", metamorph_mode=mode)
    assert store.get_project("p1", "proj-both")["metamorph"]["mode"] == "both"
    with pytest.raises(StellaError):
        store.create_project("p1", "bad", metamorph_mode="shrink")


def test_update_project_merges_settings(store):
    store.create_profile("p1")
    store.create_project("p1", "proj")
    updated = store.update_project("p1", "proj", settings={"rank": 16})
    assert updated["settings"]["rank"] == 16
    assert updated["settings"]["method"] == "lora"  # untouched keys survive
    updated = store.update_project(
        "p1", "proj", metamorph={"mode": "compress", "notes": "small"}
    )
    assert updated["metamorph"] == {"mode": "compress", "notes": "small"}


def test_target_modules_setting_validated(store):
    # T34: target_modules is a list of layer names, or empty for
    # auto-detection; anything else is refused, naming the setting.
    from stella.model import validate_settings

    assert validate_settings({"target_modules": []}) == {
        "target_modules": []
    }
    assert validate_settings({"target_modules": ["q_proj", " k_proj "]}) == {
        "target_modules": ["q_proj", "k_proj"]
    }
    for bad in ("q_proj", ["q_proj", 7], ["q_proj", ""], ["  "], [None]):
        with pytest.raises(StellaError, match="target_modules"):
            validate_settings({"target_modules": bad})
    with pytest.raises(StellaError, match="target_modules"):
        validate_settings({"target_module": ["q_proj"]})


def test_create_project_stores_target_modules(store):
    # T34: the setting survives a create + read round trip.
    store.create_profile("p1")
    data = store.create_project(
        "p1", "proj", settings={"target_modules": ["weird_a", "weird_b"]}
    )
    assert data["settings"]["target_modules"] == ["weird_a", "weird_b"]
    assert store.get_project("p1", "proj")["settings"]["target_modules"] == [
        "weird_a", "weird_b",
    ]


def test_update_project_rejects_invalid_status(store):
    # T53: status is a validated enum — "banana" is rejected.
    store.create_profile("p1")
    store.create_project("p1", "proj")
    with pytest.raises(StellaError, match="status must be one of"):
        store.update_project("p1", "proj", status="banana")
    with pytest.raises(StellaError, match="status must be one of"):
        store.update_project("p1", "proj", status=5)


def test_update_project_stamps_status_changed(store):
    # T53: every real transition stamps status_changed; a
    # same-status update does not re-stamp.
    store.create_profile("p1")
    store.create_project("p1", "proj")
    assert "status_changed" not in store.get_project("p1", "proj")
    updated = store.update_project("p1", "proj", status="ready")
    assert updated["status_changed"]
    first = updated["status_changed"]
    updated = store.update_project("p1", "proj", status="ready")
    assert updated["status_changed"] == first
    updated = store.update_project("p1", "proj", status="training")
    assert updated["status_changed"] >= first


def test_legacy_trained_status_reads_as_done(store):
    # T53: a v0.1-v0.12 "trained" project reads as "done" — in
    # memory; the file on disk is untouched until a write happens.
    store.create_profile("p1")
    store.create_project("p1", "proj")
    manifest = store.project_dir("p1", "proj") / "project.json"
    data = json.loads(manifest.read_text())
    data["status"] = "trained"
    manifest.write_text(json.dumps(data))
    assert store.get_project("p1", "proj")["status"] == "done"
    assert store.list_projects("p1")[0]["status"] == "done"
    assert json.loads(manifest.read_text())["status"] == "trained"
    store.update_project("p1", "proj", status="done")
    assert json.loads(manifest.read_text())["status"] == "done"


def test_update_project_accepts_legacy_trained(store):
    # T53: writing the old word stores the new one, never the old.
    store.create_profile("p1")
    store.create_project("p1", "proj")
    updated = store.update_project("p1", "proj", status="trained")
    assert updated["status"] == "done"


def test_rename_and_delete_project(store):
    store.create_profile("p1")
    store.create_project("p1", "old")
    renamed = store.rename_project("p1", "old", "new")
    assert renamed["name"] == "new"
    trashed = store.delete_project("p1", "new")
    assert store.list_projects("p1") == []
    # T23: the delete went to the trash, under the renamed name.
    assert trashed.name.startswith("p1-new-")
    assert store.list_trash()[0]["project"] == "new"


def test_notes_round_trip(store):
    store.create_profile("p1")
    store.create_project("p1", "proj")
    store.write_notes("p1", "proj", "First run: rank 8, lr 0.0002.\n")
    assert store.read_notes("p1", "proj") == "First run: rank 8, lr 0.0002.\n"


@pytest.mark.parametrize("bad", ["", "..", "../evil", "a/b", "a\\b", ".hidden",
                                 "has space", "a" * 65, "with.dot"])
def test_slug_validation_rejects(bad):
    with pytest.raises(StellaError):
        validate_slug(bad, "name")


def test_slug_validation_lowercases():
    assert validate_slug("UPPER") == "upper"
    assert validate_slug("  Lfm3-Tool ") == "lfm3-tool"


@pytest.mark.parametrize("good", ["a", "abc-123", "lfm3_tool", "x" * 64])
def test_slug_validation_accepts(good):
    assert validate_slug(good) == good


def test_path_escape_blocked(store):
    # Even a hand-built traversal must not leave the home.
    store.create_profile("safe")
    for evil in ("..", "../..", "..%2f.."):
        with pytest.raises(StellaError):
            store.profile_dir(evil)
    # Nothing escaped: home holds only profiles/.
    assert sorted(p.name for p in store.home.iterdir()) == ["profiles"]


def _corrupt_project_json(store, profile, project, mutate):
    """Hand-edit a project.json in place (the file the docs invite
    users to fix by hand)."""
    manifest = store.project_dir(profile, project) / "project.json"
    data = json.loads(manifest.read_text())
    mutate(data)
    manifest.write_text(json.dumps(data))
    return manifest


# -- T37: the defensive metamorph reader ----------------------------


def test_metamorph_mode_reader():
    from stella.model import metamorph_mode

    assert metamorph_mode({"metamorph": {"mode": "both"}}) == "both"
    assert metamorph_mode({"metamorph": {"mode": "compress"}}) == "compress"
    assert metamorph_mode({}) == "morph"  # missing block
    assert metamorph_mode({"metamorph": None}) == "morph"  # null block
    assert metamorph_mode({"metamorph": "both"}) == "morph"  # string block
    assert metamorph_mode({"metamorph": 7}) == "morph"  # int block
    assert metamorph_mode({"metamorph": {}}) == "morph"  # no mode key
    assert metamorph_mode({"metamorph": {"mode": "shrink"}}) == "morph"


def test_metamorph_problem_reader():
    from stella.model import metamorph_problem

    assert metamorph_problem({"metamorph": {"mode": "both"}}) is None
    assert metamorph_problem({}) is None  # absent is fine, not broken
    assert metamorph_problem({"metamorph": None}) is not None
    assert metamorph_problem({"metamorph": "both"}) is not None
    assert metamorph_problem({"metamorph": {"mode": "shrink"}}) is not None


def test_get_project_defaults_metamorph_block(store):
    store.create_profile("p1")
    store.create_project("p1", "proj")
    _corrupt_project_json(store, "p1", "proj", lambda d: d.pop("metamorph"))
    assert store.get_project("p1", "proj")["metamorph"]["mode"] == "morph"
    _corrupt_project_json(
        store, "p1", "proj", lambda d: d.update(metamorph=None)
    )
    assert store.get_project("p1", "proj")["metamorph"]["mode"] == "morph"
    _corrupt_project_json(
        store, "p1", "proj", lambda d: d.update(metamorph="both")
    )
    assert store.get_project("p1", "proj")["metamorph"]["mode"] == "morph"


def test_update_project_missing_metamorph_key(store):
    store.create_profile("p1")
    store.create_project("p1", "proj")
    _corrupt_project_json(store, "p1", "proj", lambda d: d.pop("metamorph"))
    # No KeyError: the save works and the mode defaults to morph.
    updated = store.update_project(
        "p1", "proj", metamorph={"notes": "kept my note"}
    )
    assert updated["metamorph"]["mode"] == "morph"
    assert updated["metamorph"]["notes"] == "kept my note"


def test_update_project_null_metamorph(store):
    store.create_profile("p1")
    store.create_project("p1", "proj")
    _corrupt_project_json(
        store, "p1", "proj", lambda d: d.update(metamorph=None)
    )
    updated = store.update_project("p1", "proj", metamorph={"mode": "both"})
    assert updated["metamorph"]["mode"] == "both"


def test_update_project_string_metamorph(store):
    store.create_profile("p1")
    store.create_project("p1", "proj")
    _corrupt_project_json(
        store, "p1", "proj", lambda d: d.update(metamorph="both")
    )
    updated = store.update_project(
        "p1", "proj", display_name="Still saves"
    )
    assert updated["display_name"] == "Still saves"
    updated = store.update_project(
        "p1", "proj", metamorph={"mode": "compress"}
    )
    assert updated["metamorph"]["mode"] == "compress"


# -- T6: validate settings in the model -----------------------------


@pytest.mark.parametrize(
    "bad",
    [
        {"rank": -5},
        {"rank": 0},
        {"rank": 65},
        {"rank": "banana"},
        {"rank": 2.5},
        {"rank": True},
        {"epochs": 0},
        {"epochs": 101},
        {"batch_size": 0},
        {"batch_size": 33},
        {"learning_rate": -0.5},
        {"learning_rate": 2.0},
        {"learning_rate": float("inf")},
        {"learning_rate": float("nan")},
        {"max_seq_len": 127},
        {"max_seq_len": 999999},
        {"grad_accum": 0},
        {"checkpoint_steps": -1},
        {"val_fraction": 0.6},
        {"warmup_steps": -3},
        {"foo": 1},  # unknown key
        {"method": "banana"},
        {"method": "LORA"},
    ],
)
def test_create_project_rejects_bad_settings(store, bad):
    store.create_profile("p1")
    with pytest.raises(StellaError):
        store.create_project("p1", "proj", settings=bad)


@pytest.mark.parametrize(
    "bad",
    [
        {"rank": -5},
        {"epochs": 0},
        {"learning_rate": float("inf")},
        {"learning_rate": float("nan")},
        {"foo": 1},
        {"method": "banana"},
    ],
)
def test_update_project_rejects_bad_settings(store, bad):
    store.create_profile("p1")
    store.create_project("p1", "proj")
    rank_before = store.get_project("p1", "proj")["settings"]["rank"]
    with pytest.raises(StellaError):
        store.update_project("p1", "proj", settings=bad)
    # Nothing was stored: the old settings survive untouched.
    assert store.get_project("p1", "proj")["settings"]["rank"] == rank_before


def test_settings_rejection_names_the_key(store):
    store.create_profile("p1")
    with pytest.raises(StellaError, match="rank"):
        store.create_project("p1", "proj", settings={"rank": -5})
    with pytest.raises(StellaError, match="foo"):
        store.create_project("p1", "proj", settings={"foo": 1})


def test_valid_settings_still_save(store):
    store.create_profile("p1")
    data = store.create_project(
        "p1",
        "proj",
        settings={
            "method": "full",
            "rank": 64,
            "learning_rate": 0.001,
            "epochs": 100,
            "batch_size": 32,
            "grad_accum": 64,
            "max_seq_len": 32768,
            "checkpoint_steps": 0,
            "val_fraction": 0.5,
            "warmup_steps": 1000,
            "seed": -1,
            "notes": "edge values",
        },
    )
    assert data["settings"]["rank"] == 64
    assert data["settings"]["method"] == "full"
    updated = store.update_project("p1", "proj", settings={"rank": 1})
    assert updated["settings"]["rank"] == 1


def test_write_json_refuses_nan(tmp_path):
    from stella.model import _write_json

    with pytest.raises(StellaError, match="not a real number"):
        _write_json(tmp_path / "bad.json", {"x": float("nan")})
    with pytest.raises(StellaError, match="not a real number"):
        _write_json(tmp_path / "bad.json", {"x": float("inf")})
    assert not (tmp_path / "bad.json").exists()


def test_slug_from_model():
    from stella.model import slug_from_model

    assert slug_from_model("LiquidAI/LFM3-1.7B") == "lfm3-1-7b"
    assert slug_from_model("maternion/minicpm5-heretic:2b") == "minicpm5-heretic-2b"
    assert slug_from_model("qwen3.5:4b") == "qwen3-5-4b"
    assert slug_from_model("lfm3") == "lfm3"
    assert slug_from_model("  Qwen/Qwen3-0.6B  ") == "qwen3-0-6b"
    assert slug_from_model("!!!") == "profile"


# -- T3: corrupt manifests are damaged rows, never silent skips -----


def test_list_profiles_reports_corrupt_manifest(seeded):
    import json

    manifest = (
        seeded.home / "profiles" / "lfm3-tool" / "profile.json"
    )
    manifest.write_text("{not valid json", encoding="utf-8")
    rows = seeded.list_profiles()
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "lfm3-tool"
    assert row["_damaged"] is True
    assert "not valid JSON" in row["_error"]
    # The folder is untouched: fixing the JSON by hand restores it.
    manifest.write_text(
        json.dumps({"name": "lfm3-tool", "role": "fast"}),
        encoding="utf-8",
    )
    rows = seeded.list_profiles()
    assert len(rows) == 1
    assert rows[0].get("_damaged") is None
    assert rows[0]["role"] == "fast"


def test_list_projects_reports_corrupt_manifest(seeded):
    manifest = (
        seeded.home / "profiles" / "lfm3-tool" / "projects"
        / "tool-calls" / "project.json"
    )
    manifest.write_text("[1, 2, 3]", encoding="utf-8")  # valid JSON, not an object
    rows = seeded.list_projects("lfm3-tool")
    assert len(rows) == 1
    assert rows[0]["name"] == "tool-calls"
    assert rows[0]["_damaged"] is True
    assert "must hold a JSON object" in rows[0]["_error"]


def test_list_profiles_keeps_good_rows_beside_damaged(store):
    store.create_profile("good", ollama_tag="x:1b")
    store.create_profile("broken", ollama_tag="y:1b")
    manifest = store.home / "profiles" / "broken" / "profile.json"
    manifest.write_text("{oops", encoding="utf-8")
    rows = store.list_profiles()
    assert [r["name"] for r in rows] == ["broken", "good"]
    assert rows[0]["_damaged"] is True
    assert rows[1].get("_damaged") is None


def test_list_profiles_bad_bytes_are_one_damaged_row(store):
    """R7: invalid UTF-8 in one manifest is one damaged row — the
    rest of the list still works. UnicodeDecodeError is neither a
    JSONDecodeError nor an OSError, so it used to escape the
    damaged-row handling and take out the whole list."""
    store.create_profile("good", ollama_tag="x:1b")
    store.create_profile("broken", ollama_tag="y:1b")
    manifest = store.home / "profiles" / "broken" / "profile.json"
    manifest.write_bytes(b'{"name": "broken", "role": "\xff\xfe"}')
    rows = store.list_profiles()
    assert [r["name"] for r in rows] == ["broken", "good"]
    assert rows[0]["_damaged"] is True
    assert "cannot read" in rows[0]["_error"]
    assert rows[1].get("_damaged") is None


def test_list_projects_bad_bytes_are_one_damaged_row(seeded):
    """R7: invalid UTF-8 in one project manifest is one damaged
    row, like a bad profile manifest."""
    manifest = (
        seeded.home / "profiles" / "lfm3-tool" / "projects"
        / "tool-calls" / "project.json"
    )
    manifest.write_bytes(b'{"name": "tool-calls", "\xff": 1}')
    rows = seeded.list_projects("lfm3-tool")
    assert len(rows) == 1
    assert rows[0]["name"] == "tool-calls"
    assert rows[0]["_damaged"] is True
    assert "cannot read" in rows[0]["_error"]


def test_read_notes_bad_bytes_raise_plain_error(seeded):
    """R7: invalid UTF-8 in a project's notes is a plain error
    naming the project, not a raw UnicodeDecodeError."""
    from stella.model import StellaError

    notes = (
        seeded.home / "profiles" / "lfm3-tool" / "projects"
        / "tool-calls" / "notes.md"
    )
    notes.write_bytes(b"# notes\n\xff\xfe bad bytes\n")
    with pytest.raises(StellaError, match="cannot read"):
        seeded.read_notes("lfm3-tool", "tool-calls")


def test_read_profile_notes_bad_bytes_raise_plain_error(seeded):
    """R7: the same bad-bytes guard for profile notes."""
    from stella.model import StellaError

    notes = seeded.home / "profiles" / "lfm3-tool" / "notes.md"
    notes.write_bytes(b"\xff\xfe")
    with pytest.raises(StellaError, match="cannot read"):
        seeded.read_profile_notes("lfm3-tool")


def test_rename_profile_skips_damaged_project(seeded):
    import json

    manifest = (
        seeded.home / "profiles" / "lfm3-tool" / "projects"
        / "tool-calls" / "project.json"
    )
    manifest.write_text("{oops", encoding="utf-8")
    data = seeded.rename_profile("lfm3-tool", "renamed")
    assert data["name"] == "renamed"
    # The damaged project moved with the profile, still damaged.
    rows = seeded.list_projects("renamed")
    assert len(rows) == 1
    assert rows[0]["_damaged"] is True

# -- T112: clone project ----------------------------------------------


def _seeded_project_with_knobs(store):
    """A profile + project with explicit settings, a dataset, and
    a metamorph mode + notes — the clone's source."""
    store.create_profile("p1", ollama_tag="lfm3:1.7b", role="fast")
    store.create_project(
        "p1", "orig",
        display_name="Original",
        dataset_ref="data.jsonl",
        settings={"rank": 16, "epochs": 5},
        metamorph_mode="compress",
        metamorph_notes="squeeze it down",
    )
    return store


def test_clone_project_copies_settings_dataset_mode(store):
    """T112 Done: the clone has identical settings, dataset, and
    metamorph mode under its own name, and a "cloned from" note."""
    _seeded_project_with_knobs(store)
    data = store.clone_project("p1", "orig", "second-try")
    assert data["name"] == "second-try"
    clone = store.get_project("p1", "second-try")
    orig = store.get_project("p1", "orig")
    assert clone["settings"] == orig["settings"]
    assert clone["settings"]["rank"] == 16
    assert clone["settings"]["epochs"] == 5
    assert clone["dataset_ref"] == "data.jsonl"
    from stella.model import metamorph_mode

    assert metamorph_mode(clone) == "compress"
    assert clone["metamorph"]["notes"] == "squeeze it down"
    assert clone["status"] == "draft"
    notes = store.read_notes("p1", "second-try")
    assert "Cloned from orig." in notes
    # The display name travels (it was custom).
    assert clone["display_name"] == "Original"


def test_clone_does_not_copy_checkpoints_or_adapter(store):
    """T112 Done: zero checkpoints in the clone, no adapter."""
    _seeded_project_with_knobs(store)
    pdir = store.project_dir("p1", "orig")
    (pdir / "checkpoints" / "step-10").mkdir(parents=True)
    (pdir / "checkpoints" / "step-10" / "training_state.json").write_text(
        '{"step": 10}'
    )
    adapter = pdir / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text('{"r": 16}')
    store.clone_project("p1", "orig", "second-try")
    clone_dir = store.project_dir("p1", "second-try")
    assert list((clone_dir / "checkpoints").iterdir()) == []
    assert not (clone_dir / "adapter").exists()
    # The original keeps its checkpoints and adapter.
    assert (pdir / "checkpoints" / "step-10").is_dir()
    assert (adapter / "adapter_config.json").is_file()


def test_clone_name_collision_rejected(store):
    """T112 Done: cloning onto an existing name is refused."""
    _seeded_project_with_knobs(store)
    store.create_project("p1", "taken")
    with pytest.raises(StellaError, match="already exists"):
        store.clone_project("p1", "orig", "taken")


def test_clone_leaves_original_untouched(store):
    """T112 Done: the original is untouched by the clone."""
    _seeded_project_with_knobs(store)
    store.write_notes("p1", "orig", "original notes\n")
    before = store.get_project("p1", "orig")
    store.clone_project("p1", "orig", "second-try")
    assert store.get_project("p1", "orig") == before
    assert store.read_notes("p1", "orig") == "original notes\n"


def test_clone_copies_bundled_dataset_file(store):
    """T112: when the dataset file lives inside the source project
    (a bundled import), the file travels into the clone, so the
    clone's ref still resolves."""
    _seeded_project_with_knobs(store)
    pdir = store.project_dir("p1", "orig")
    (pdir / "data.jsonl").write_text(
        '{"prompt": "a", "completion": "b"}\n'
    )
    store.clone_project("p1", "orig", "second-try")
    clone_file = store.project_dir("p1", "second-try") / "data.jsonl"
    assert clone_file.is_file()
    assert clone_file.read_text() == '{"prompt": "a", "completion": "b"}\n'


def test_clone_default_display_becomes_new_name(store):
    """T112: a default display name (equal to the slug) becomes
    the new slug, not the old one."""
    store.create_profile("p1")
    store.create_project("p1", "orig")
    store.clone_project("p1", "orig", "second-try")
    assert store.get_project("p1", "second-try")["display_name"] == (
        "second-try"
    )


# -- T119: notes backup -----------------------------------------------


def test_notes_backup_holds_previous_content(store):
    """T119 Done: save notes twice; the previous version is
    recoverable from notes.md.1."""
    store.create_profile("p1")
    store.create_project("p1", "proj")
    store.write_notes("p1", "proj", "first version\n")
    store.write_notes("p1", "proj", "second version\n")
    assert store.read_notes("p1", "proj") == "second version\n"
    backup = store.project_dir("p1", "proj") / "notes.md.1"
    assert backup.is_file()
    assert backup.read_text(encoding="utf-8") == "first version\n"


def test_notes_backup_rotates_to_latest_previous(store):
    """T119: the single backup always holds the version just
    before the current one."""
    store.create_profile("p1")
    store.create_project("p1", "proj")
    store.write_notes("p1", "proj", "v1\n")
    store.write_notes("p1", "proj", "v2\n")
    store.write_notes("p1", "proj", "v3\n")
    backup = store.project_dir("p1", "proj") / "notes.md.1"
    assert backup.read_text(encoding="utf-8") == "v2\n"


# -- T118: timestamp restore ------------------------------------------


def test_create_restores_given_timestamps(store):
    """T118: create_profile / create_project with created/updated
    store those stamps instead of "now"."""
    store.create_profile(
        "p1", created="2026-11-01T10:00:00+00:00",
        updated="2026-11-02T11:00:00+00:00",
    )
    prof = store.get_profile("p1")
    assert prof["created"] == "2026-11-01T10:00:00+00:00"
    assert prof["updated"] == "2026-11-02T11:00:00+00:00"
    store.create_project(
        "p1", "proj", created="2026-11-03T12:00:00+00:00"
    )
    proj = store.get_project("p1", "proj")
    assert proj["created"] == "2026-11-03T12:00:00+00:00"
    assert "updated" not in proj


# -- T87: purge --------------------------------------------------------


def test_purge_profile_and_project_delete_forever(store):
    """T87: --purge removes without the trash."""
    store.create_profile("p1")
    store.create_project("p1", "proj")
    store.purge_project("p1", "proj")
    with pytest.raises(StellaError):
        store.get_project("p1", "proj")
    assert store.list_trash() == []
    store.purge_profile("p1")
    with pytest.raises(StellaError):
        store.get_profile("p1")
    assert store.list_trash() == []
    with pytest.raises(StellaError, match="no profile"):
        store.purge_profile("ghost")
    with pytest.raises(StellaError, match="no project"):
        store.purge_project("p1", "ghost")


# -- v0.19.0: T114, T116, T121 ----------------------------------------


def test_settings_notes_dropped_from_new_projects(store):
    """T114 Done: settings["notes"] is gone from new manifests."""
    from stella.model import DEFAULT_SETTINGS

    assert "notes" not in DEFAULT_SETTINGS
    store.create_profile("p1")
    data = store.create_project("p1", "proj")
    assert "notes" not in data["settings"]
    on_disk = json.loads(
        (
            store.home / "profiles" / "p1" / "projects" / "proj"
            / "project.json"
        ).read_text()
    )
    assert "notes" not in on_disk["settings"]


def test_settings_notes_migrated_from_old_manifest(store):
    """T114 Done: migration removes the dead key from an existing
    manifest, in memory and on disk."""
    store.create_profile("p1")
    store.create_project("p1", "proj")
    manifest = (
        store.home / "profiles" / "p1" / "projects" / "proj"
        / "project.json"
    )
    data = json.loads(manifest.read_text())
    data["settings"]["notes"] = "a note from before the drop"
    manifest.write_text(json.dumps(data))
    got = store.get_project("p1", "proj")
    assert "notes" not in got["settings"]
    again = json.loads(manifest.read_text())
    assert "notes" not in again["settings"]


def test_settings_notes_migrated_by_list_projects(store):
    """T114: the list path migrates too, not just get_project."""
    store.create_profile("p1")
    store.create_project("p1", "proj")
    manifest = (
        store.home / "profiles" / "p1" / "projects" / "proj"
        / "project.json"
    )
    data = json.loads(manifest.read_text())
    data["settings"]["notes"] = "stale"
    manifest.write_text(json.dumps(data))
    listed = store.list_projects("p1")
    assert "notes" not in listed[0]["settings"]
    assert "notes" not in json.loads(manifest.read_text())["settings"]


def test_validate_settings_drops_legacy_notes():
    """T114: a settings dict carrying the old key validates, with
    the key dropped — old packages import instead of failing."""
    from stella.model import validate_settings

    cleaned = validate_settings({"notes": "old", "rank": 8})
    assert cleaned == {"rank": 8}


def test_canonical_roles_list():
    """T116 Done: one canonical role/seat list, the roster's seat
    vocabulary."""
    from stella.model import CANONICAL_ROLES

    assert CANONICAL_ROLES == (
        "driver", "reviewer", "vision", "fast", "tester",
        "all-rounder", "utility",
    )


def test_is_custom_role():
    """T116: a role outside the canonical list is custom; a
    canonical role or a blank one is not."""
    from stella.model import is_custom_role

    assert is_custom_role("drvier") is True
    assert is_custom_role("judge") is True
    assert is_custom_role("fast") is False
    assert is_custom_role(" Fast ") is False
    assert is_custom_role("") is False
    assert is_custom_role(None) is False


def test_looks_abliterated_heuristic():
    """T116: the abliteration heuristic reads the tag/base name
    markers — there is no stored flag."""
    from stella.model import looks_abliterated

    assert looks_abliterated(
        {"ollama_tag": "maternion/minicpm5-heretic:2b"}
    ) is True
    assert looks_abliterated({"base_ref": "x/uncensored-7b"}) is True
    assert looks_abliterated({"base_ref": "x/abliterated-7b"}) is True
    assert looks_abliterated({"ollama_tag": "lfm3:1.7b"}) is False
    assert looks_abliterated({"base_ref": "LiquidAI/LFM3-1.7B"}) is False
    assert looks_abliterated({}) is False


def test_governing_seat_warning():
    """T116 Done: marking a profile for a governing seat with a
    stock base produces a warning naming the seat and the base;
    an abliterated base, an unmarked profile, or a governing
    role alone does not warn."""
    from stella.model import governing_seat_warning

    warning = governing_seat_warning(
        {"governing_seat": "driver", "base_ref": "LiquidAI/LFM3-1.7B"}
    )
    assert warning is not None
    assert "driver" in warning
    assert "LiquidAI/LFM3-1.7B" in warning
    # An abliterated base does not warn.
    assert governing_seat_warning(
        {"governing_seat": "driver", "ollama_tag": "x-heretic:2b"}
    ) is None
    # No marker, no warning — a governing role alone does not
    # warn here (the probe gates governing roles at probe time).
    assert governing_seat_warning(
        {"role": "driver", "base_ref": "LiquidAI/LFM3-1.7B"}
    ) is None
    assert governing_seat_warning(
        {"governing_seat": "", "base_ref": "LiquidAI/LFM3-1.7B"}
    ) is None
    # A non-governing seat value never warns.
    assert governing_seat_warning(
        {"governing_seat": "vision", "base_ref": "x"}
    ) is None


def test_governing_seat_stored_and_validated(store):
    """T116: the marker is stored on create and update, and a
    seat that is not governing is refused, not stored."""
    data = store.create_profile("p1", governing_seat="reviewer")
    assert data["governing_seat"] == "reviewer"
    assert store.get_profile("p1")["governing_seat"] == "reviewer"
    with pytest.raises(StellaError, match="governing seat"):
        store.create_profile("p2", governing_seat="vision")
    with pytest.raises(StellaError, match="governing seat"):
        store.update_profile("p1", governing_seat="bogus")
    updated = store.update_profile("p1", governing_seat="")
    assert updated["governing_seat"] == ""
    # The seat name normalizes to lowercase.
    updated = store.update_profile("p1", governing_seat="Driver")
    assert updated["governing_seat"] == "driver"


def test_clone_profile_copies_fields(store):
    """T121 Done: the clone has the same tag, base, role,
    processor, config, and dependencies under its own name, with
    zero projects; the original is untouched. The processor is
    copied verbatim (T128: its meaning is undecided). The
    governing-seat marker is NOT copied — a binding is per
    profile."""
    store.create_profile(
        "p1", ollama_tag="lfm3:1.7b", role="fast",
        display_name="LFM3 Tool Seat", base_ref="LiquidAI/LFM3-1.7B",
        processor="some-processor-value", config={"ctx": 8192},
        dependencies=["torch", "peft"], governing_seat="driver",
    )
    store.create_project("p1", "proj")
    clone = store.clone_profile("p1", "p2")
    assert clone["name"] == "p2"
    assert clone["display_name"] == "LFM3 Tool Seat"
    assert clone["ollama_tag"] == "lfm3:1.7b"
    assert clone["role"] == "fast"
    assert clone["base_ref"] == "LiquidAI/LFM3-1.7B"
    assert clone["processor"] == "some-processor-value"
    assert clone["config"] == {"ctx": 8192}
    assert clone["dependencies"] == ["torch", "peft"]
    assert clone["governing_seat"] == ""
    assert store.list_projects("p2") == []
    # The original is untouched, projects and all.
    assert [p["name"] for p in store.list_projects("p1")] == ["proj"]
    assert store.get_profile("p1")["governing_seat"] == "driver"


def test_clone_profile_default_display_name_becomes_new_slug(store):
    """T121: a default display name (equal to the slug) becomes
    the new slug instead of lying about which profile it is."""
    store.create_profile("p1")
    clone = store.clone_profile("p1", "p2")
    assert clone["display_name"] == "p2"


def test_clone_profile_copies_projects_when_asked(store):
    """T121: with copy_projects, each project is cloned too —
    same dataset/settings/mode, no checkpoints, fresh notes."""
    store.create_profile("p1", ollama_tag="lfm3:1.7b")
    store.create_project(
        "p1", "proj", dataset_ref="data.jsonl",
        metamorph_mode="both", metamorph_notes="why both",
    )
    (store.home / "profiles" / "p1" / "projects" / "proj"
     / "checkpoints" / "step-10").mkdir(parents=True)
    store.clone_profile("p1", "p2", copy_projects=True)
    copied = store.get_project("p2", "proj")
    assert copied["dataset_ref"] == "data.jsonl"
    assert copied["metamorph"]["mode"] == "both"
    assert copied["metamorph"]["notes"] == "why both"
    ckpts = (
        store.home / "profiles" / "p2" / "projects" / "proj"
        / "checkpoints"
    )
    assert list(ckpts.iterdir()) == []
    assert "Cloned from proj" in store.read_notes("p2", "proj")
    # The source keeps its checkpoint.
    src_ckpts = (
        store.home / "profiles" / "p1" / "projects" / "proj"
        / "checkpoints"
    )
    assert [d.name for d in src_ckpts.iterdir()] == ["step-10"]


def test_clone_profile_collision_rejected(store):
    """T121 Done: a clone-name collision is rejected."""
    store.create_profile("p1")
    store.create_profile("p2")
    with pytest.raises(StellaError, match="already exists"):
        store.clone_profile("p1", "p2")
    with pytest.raises(StellaError, match="no profile"):
        store.clone_profile("ghost", "p3")


def test_clone_project_into_another_profile(store):
    """T121: clone_project's target_profile clones into a
    different profile instead of the source one."""
    store.create_profile("p1")
    store.create_profile("p2")
    store.create_project("p1", "proj", dataset_ref="data.jsonl")
    store.clone_project("p1", "proj", "proj", target_profile="p2")
    assert store.get_project("p2", "proj")["dataset_ref"] == "data.jsonl"
    assert [p["name"] for p in store.list_projects("p1")] == ["proj"]


# -- v0.21.0: T177 (notes type), T166 (profile notes), T165 ---------
# -- (last-used), T179 (history log) --------------------------------


def test_create_project_rejects_int_notes(store):
    """T177: non-string notes are rejected at create_project."""
    store.create_profile("p1")
    with pytest.raises(StellaError, match="notes must be text"):
        store.create_project("p1", "proj", metamorph_notes=123)
    # None counts as absent, the import validator's convention.
    data = store.create_project("p1", "proj", metamorph_notes=None)
    assert data["metamorph"]["notes"] == ""


def test_update_project_rejects_int_notes(store):
    """T177: non-string notes are rejected at update_project."""
    store.create_profile("p1")
    store.create_project("p1", "proj")
    with pytest.raises(StellaError, match="notes must be text"):
        store.update_project(
            "p1", "proj", metamorph={"mode": "morph", "notes": 456}
        )
    # A mode-only update leaves good notes alone.
    store.update_project(
        "p1", "proj", metamorph={"mode": "both", "notes": "why both"}
    )
    store.update_project("p1", "proj", metamorph={"mode": "morph"})
    assert store.get_project("p1", "proj")["metamorph"]["notes"] == (
        "why both"
    )


def test_profile_notes_round_trip(store):
    """T166: profile notes write and read back; a profile with no
    notes reads as empty."""
    store.create_profile("p1")
    assert store.read_profile_notes("p1") == ""
    store.write_profile_notes("p1", "Why this profile exists.")
    assert store.read_profile_notes("p1") == "Why this profile exists."
    with pytest.raises(StellaError, match="no profile"):
        store.write_profile_notes("ghost", "x")


def test_profile_notes_keep_backup(store):
    """T166: profile notes get the same rotating .1 backup as
    project notes (T119)."""
    store.create_profile("p1")
    store.write_profile_notes("p1", "first version")
    store.write_profile_notes("p1", "second version")
    backup = store.profile_dir("p1") / "notes.md.1"
    assert backup.read_text(encoding="utf-8") == "first version"
    assert store.read_profile_notes("p1") == "second version"


def test_profile_notes_survive_rename(store):
    """T166: notes survive a profile rename — the file lives in
    the profile folder, so the rename moves it along."""
    store.create_profile("p1")
    store.write_profile_notes("p1", "still here after the rename")
    store.rename_profile("p1", "p2")
    assert store.read_profile_notes("p2") == "still here after the rename"


def test_create_profile_last_used_defaults_empty(store):
    """T165: a new profile has never been used."""
    data = store.create_profile("p1")
    assert data["last_used"] == ""
    assert store.get_profile("p1")["last_used"] == ""


def test_touch_last_used_stamps_without_touching_updated(store):
    """T165: touch_last_used stamps last_used and leaves `updated`
    alone — using a profile is not editing it."""
    store.create_profile("p1", updated="2026-01-01T00:00:00Z")
    data = store.touch_last_used("p1")
    assert data["last_used"] != ""
    assert data["updated"] == "2026-01-01T00:00:00Z"
    assert store.get_profile("p1")["last_used"] == data["last_used"]


def test_history_records_exports_and_imports(store):
    """T179: the home keeps an import/export history log."""
    assert store.read_history() == []
    store.record_history({
        "kind": "export", "package": "project",
        "profile": "p1", "project": "proj", "path": "/tmp/out",
    })
    store.record_history({
        "kind": "import", "package": "profile",
        "profile": "p1", "project": "", "path": "/tmp/in",
    })
    entries = store.read_history()
    assert len(entries) == 2
    assert entries[0]["kind"] == "export"
    assert entries[0]["project"] == "proj"
    assert entries[0]["when"] != ""
    assert entries[1]["kind"] == "import"
    assert entries[1]["package"] == "profile"


def test_history_skips_bad_lines(store):
    """T179: a hand-corrupted history line is skipped, never fatal."""
    store.record_history({"kind": "export", "package": "project"})
    log = store.home / "history.jsonl"
    log.write_text(
        log.read_text(encoding="utf-8") + "not json\n",
        encoding="utf-8",
    )
    assert len(store.read_history()) == 1


def test_history_trims_to_newest(store):
    """T179: the log stays small — past 500 entries it trims to
    the newest 200."""
    for i in range(501):
        store.record_history({
            "kind": "export", "package": "project",
            "profile": f"p{i}", "project": "", "path": "",
        })
    entries = store.read_history()
    assert len(entries) == 200
    assert entries[0]["profile"] == "p301"
    assert entries[-1]["profile"] == "p500"


# -- v0.26.0: R37 — the model layer type-checks its inputs ----------


def test_create_profile_refuses_wrong_types(store):
    """R37: a config that is not an object, or dependencies that
    are not a list of text, are refused in plain words — and
    nothing is stored."""
    with pytest.raises(
        StellaError, match="config must be an object"
    ):
        store.create_profile("bad-config", config="abc")
    assert "bad-config" not in [p["name"] for p in store.list_profiles()]
    with pytest.raises(
        StellaError, match="dependencies must be a list of text"
    ):
        store.create_profile("bad-deps", dependencies="torch")
    assert "bad-deps" not in [p["name"] for p in store.list_profiles()]
    with pytest.raises(StellaError, match="role must be text"):
        store.create_profile("bad-role", role=42)
    assert "bad-role" not in [p["name"] for p in store.list_profiles()]


def test_update_profile_refuses_wrong_types(store):
    """R37: the same checks apply on update — a bad value is
    refused and the stored record is untouched."""
    store.create_profile("p1", config={"ctx": 8192})
    with pytest.raises(
        StellaError, match="config must be an object"
    ):
        store.update_profile("p1", config="x")
    assert store.get_profile("p1")["config"] == {"ctx": 8192}
    with pytest.raises(
        StellaError, match="dependencies must be a list of text"
    ):
        store.update_profile("p1", dependencies="torch")
    assert store.get_profile("p1")["dependencies"] == []


def test_create_project_refuses_wrong_types(store):
    """R37: a project with non-text fields or a settings value
    that is not an object is refused, and nothing is stored."""
    store.create_profile("p1")
    with pytest.raises(
        StellaError, match="display_name must be text"
    ):
        store.create_project("p1", "bad-display", display_name=7)
    assert "bad-display" not in [p["name"] for p in store.list_projects("p1")]
    with pytest.raises(
        StellaError, match="settings must be an object"
    ):
        store.create_project("p1", "bad-settings", settings="lora")
    assert "bad-settings" not in [p["name"] for p in store.list_projects("p1")]


# -- v0.26.0: R40 — a clone names the projects it could not copy ----


def test_clone_profile_names_skipped_damaged_projects(store):
    """R40: cloning a profile with one damaged project copies the
    healthy one and NAMES the damaged one in the returned record
    — the clone never reports success while silently missing a
    project."""
    store.create_profile("p1")
    store.create_project("p1", "good")
    store.create_project("p1", "broken")
    (store.project_dir("p1", "broken") / "project.json").write_text(
        "{this is not json"
    )
    clone = store.clone_profile("p1", "p2", copy_projects=True)
    assert store.get_project("p2", "good") is not None
    assert "broken" not in [p["name"] for p in store.list_projects("p2")]
    skipped = clone.get("skipped_damaged_projects")
    assert skipped is not None
    assert [entry["name"] for entry in skipped] == ["broken"]
    assert skipped[0]["error"]


def test_clone_profile_omits_skip_key_when_nothing_skipped(store):
    """R40: the skipped-projects key is absent when every project
    copied — its presence always means something was dropped."""
    store.create_profile("p1")
    store.create_project("p1", "good")
    clone = store.clone_profile("p1", "p2", copy_projects=True)
    assert "skipped_damaged_projects" not in clone
