"""Data-model tests: profiles, projects, validation, notes."""
import json

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


def test_rename_profile_collision(store):
    store.create_profile("a")
    store.create_profile("b")
    with pytest.raises(StellaError):
        store.rename_profile("a", "b")


def test_delete_profile(store):
    store.create_profile("p1")
    store.create_project("p1", "proj")
    store.delete_profile("p1")
    assert store.list_profiles() == []
    assert not (store.home / "profiles" / "p1").exists()


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


def test_rename_and_delete_project(store):
    store.create_profile("p1")
    store.create_project("p1", "old")
    renamed = store.rename_project("p1", "old", "new")
    assert renamed["name"] == "new"
    store.delete_project("p1", "new")
    assert store.list_projects("p1") == []


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
