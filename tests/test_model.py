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
    store.create_profile("p1")
    data = store.create_project("p1", "proj")
    assert data["settings"]["method"] == "lora"
    assert data["settings"]["rank"] == 8
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
