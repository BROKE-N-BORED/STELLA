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
