"""Auto-config tests: measure this PC, pick settings for it."""
import pytest

from stella.autoconfig import (
    auto_settings,
    compute_settings,
    format_report,
    measure_pc,
    ram_usage_gb,
)


def test_measure_pc_sane(tmp_path):
    m = measure_pc(tmp_path)
    assert m["cpu_count"] >= 1
    assert isinstance(m["cpu_model"], str) and m["cpu_model"]
    assert m["ram_total_gb"] is None or m["ram_total_gb"] > 0
    assert m["ram_available_gb"] is None or m["ram_available_gb"] >= 0
    if m["ram_total_gb"] is not None and m["ram_available_gb"] is not None:
        assert m["ram_available_gb"] <= m["ram_total_gb"]
    assert m["disk_free_gb"] is None or m["disk_free_gb"] > 0
    assert m["load1"] is None or m["load1"] >= 0


def test_ram_usage_gb_sane():
    """T20: the live RAM reading (used, total) from /proc/meminfo."""
    used, total = ram_usage_gb()
    if (used, total) == (None, None):
        return  # no /proc/meminfo on this platform
    assert 0 <= used < total
    assert total > 0


def test_measure_pc_defaults_to_stella_home(monkeypatch, tmp_path):
    # The disk reading is taken on the Stella home filesystem.
    monkeypatch.setenv("STELLA_HOME", str(tmp_path))
    m = measure_pc()
    assert m["disk_free_gb"] is None or m["disk_free_gb"] > 0


def test_measure_pc_disk_works_before_home_exists(tmp_path):
    # Fresh install: the home dir does not exist yet, but the disk
    # reading still works (nearest existing ancestor).
    missing = tmp_path / "not-created-yet" / "deeper"
    m = measure_pc(missing)
    assert m["disk_free_gb"] is not None
    assert m["disk_free_gb"] > 0


@pytest.mark.parametrize(
    "ram, rank, seq",
    [
        (16.0, 8, 1024),  # plenty of RAM: the usual recipe
        (8.0, 8, 1024),
        (4.0, 8, 1024),  # exactly 4 GB is not "under 4"
        (3.99, 4, 512),  # under 4 GB: the shrunken recipe
        (2.0, 4, 512),
        (0.5, 4, 512),
        (None, 8, 1024),  # unknown RAM: the defaults
    ],
)
def test_compute_settings_rules(ram, rank, seq):
    settings = compute_settings(ram)
    assert settings["rank"] == rank
    assert settings["max_seq_len"] == seq
    assert settings["batch_size"] == 1  # always 1 on CPU
    assert settings["learning_rate"] == 0.0002
    assert settings["epochs"] == 3


def test_compute_settings_uses_model_size():
    # R78: a big base shrinks the recipe before the RAM guard has
    # to refuse the run; a small base leaves it alone. Unknown
    # size counts as plenty.
    big = compute_settings(8.0, model_params_b=3.0)
    assert big["rank"] == 4
    assert big["max_seq_len"] == 512
    assert compute_settings(8.0, model_params_b=70)["rank"] == 4
    assert compute_settings(8.0, model_params_b=2.9)["rank"] == 8
    assert compute_settings(8.0, model_params_b=0.5) == compute_settings(8.0)
    assert compute_settings(8.0, model_params_b=None)["rank"] == 8
    # Low RAM still shrinks a small model on its own.
    assert compute_settings(2.0, model_params_b=0.5)["rank"] == 4


def test_compute_settings_uses_disk_and_cpu():
    # R78: a nearly-full disk spaces checkpoints out; few CPUs
    # shorten the sequence. Rank is a memory knob, not a compute
    # knob, so few CPUs do not change it. Unknown readings count
    # as plenty.
    assert compute_settings(8.0, disk_free_gb=9.9)["checkpoint_steps"] == 200
    assert compute_settings(8.0, disk_free_gb=10.0)["checkpoint_steps"] == 50
    assert compute_settings(8.0, disk_free_gb=None)["checkpoint_steps"] == 50
    assert compute_settings(8.0, cpu_count=2)["max_seq_len"] == 512
    assert compute_settings(8.0, cpu_count=2)["rank"] == 8
    assert compute_settings(8.0, cpu_count=3)["max_seq_len"] == 1024
    assert compute_settings(8.0, cpu_count=None)["max_seq_len"] == 1024


def test_auto_settings_matches_parts(tmp_path):
    measurement, settings = auto_settings(tmp_path)
    assert settings == compute_settings(
        measurement["ram_available_gb"],
        disk_free_gb=measurement["disk_free_gb"],
        cpu_count=measurement["cpu_count"],
    )
    assert set(measurement) == {
        "cpu_count", "cpu_model", "ram_total_gb",
        "ram_available_gb", "disk_free_gb", "load1",
    }


def test_format_report_plain_words(tmp_path):
    measurement, settings = auto_settings(tmp_path)
    report = format_report(measurement, settings)
    assert "CPUs" in report
    assert "RAM" in report
    assert "Free disk" in report
    assert "Training settings for this PC" in report
    assert f"rank {settings['rank']}" in report
    assert "Traceback" not in report


def test_create_project_uses_computed_settings(store):
    store.create_profile("p1")
    data = store.create_project("p1", "proj")
    measurement = measure_pc(store.home)
    expected = compute_settings(
        measurement["ram_available_gb"],
        disk_free_gb=measurement["disk_free_gb"],
        cpu_count=measurement["cpu_count"],
    )
    assert data["settings_source"] == "auto"
    for key, value in expected.items():
        assert data["settings"][key] == value


def test_create_project_explicit_settings_are_manual(store):
    store.create_profile("p1")
    data = store.create_project(
        "p1", "proj", settings={"rank": 16, "epochs": 5}
    )
    assert data["settings_source"] == "manual"
    assert data["settings"]["rank"] == 16
    assert data["settings"]["epochs"] == 5
    # Untouched keys still come from the defaults.
    assert data["settings"]["batch_size"] == 1


def test_update_settings_flips_source_to_manual(store):
    store.create_profile("p1")
    store.create_project("p1", "proj")
    assert store.get_project("p1", "proj")["settings_source"] == "auto"
    updated = store.update_project("p1", "proj", settings={"rank": 16})
    assert updated["settings_source"] == "manual"
    assert updated["settings"]["rank"] == 16


def test_update_without_settings_keeps_source(store):
    store.create_profile("p1")
    store.create_project("p1", "proj")
    updated = store.update_project("p1", "proj", display_name="Renamed")
    assert updated["settings_source"] == "auto"


def test_refresh_auto_settings_recomputes(store, monkeypatch):
    from stella import train as train_mod

    store.create_profile("p1")
    store.create_project("p1", "proj")
    # Pretend the PC now has plenty of RAM: the refresh stores the
    # plenty-RAM recipe and the project stays auto.
    monkeypatch.setattr(
        train_mod, "measure_pc",
        lambda home: {
            "ram_available_gb": 16.0,
            "disk_free_gb": 50.0,
            "cpu_count": 8,
        },
    )
    settings = train_mod.refresh_auto_settings(store, "p1", "proj")
    assert settings["rank"] == 8
    assert settings["max_seq_len"] == 1024
    stored = store.get_project("p1", "proj")
    assert stored["settings"]["rank"] == 8
    assert stored["settings_source"] == "auto"


def test_refresh_auto_settings_leaves_manual_alone(store, monkeypatch):
    from stella import train as train_mod

    store.create_profile("p1")
    store.create_project("p1", "proj", settings={"rank": 16, "epochs": 5})
    monkeypatch.setattr(
        train_mod, "measure_pc",
        lambda home: {"ram_available_gb": 16.0},
    )
    settings = train_mod.refresh_auto_settings(store, "p1", "proj")
    assert settings["rank"] == 16
    assert settings["epochs"] == 5
    stored = store.get_project("p1", "proj")
    assert stored["settings"]["rank"] == 16
    assert stored["settings_source"] == "manual"


def test_refresh_auto_settings_leaves_legacy_alone(store, monkeypatch):
    # A project with no settings_source recorded (pre-v0.9) reads as
    # manual: old hand-tuned settings are never overwritten.
    import json

    from stella import train as train_mod

    store.create_profile("p1")
    store.create_project("p1", "proj", settings={"rank": 16})
    manifest = store.project_dir("p1", "proj") / "project.json"
    data = json.loads(manifest.read_text())
    del data["settings_source"]
    manifest.write_text(json.dumps(data))
    monkeypatch.setattr(
        train_mod, "measure_pc",
        lambda home: {"ram_available_gb": 16.0},
    )
    settings = train_mod.refresh_auto_settings(store, "p1", "proj")
    assert settings["rank"] == 16


def test_train_project_calls_refresh(store, monkeypatch, tmp_path):
    """Wiring: train_project re-resolves auto settings at run start.

    The deps gate is stubbed out and the project has no dataset, so
    the run stops right after the refresh — the spy proves the call
    happened, without needing torch.
    """
    from stella import train as train_mod
    from stella.model import StellaError

    store.create_profile("p1", base_ref="test/tiny-model")
    store.create_project("p1", "proj")
    calls = []
    real_refresh = train_mod.refresh_auto_settings
    monkeypatch.setattr(train_mod, "require_training_deps", lambda: None)
    monkeypatch.setattr(
        train_mod, "refresh_auto_settings",
        lambda s, prof, proj, **kwargs: (
            calls.append((prof, proj)) or real_refresh(s, prof, proj)
        ),
    )
    with pytest.raises(StellaError, match="no dataset"):
        train_mod.train_project(store, "p1", "proj")
    assert calls == [("p1", "proj")]


def test_train_project_skips_refresh_for_sleep(store, monkeypatch, tmp_path):
    """Sleep runs (update_status=False) never rewrite the project."""
    from stella import train as train_mod
    from stella.model import StellaError

    store.create_profile("p1", base_ref="test/tiny-model")
    store.create_project("p1", "proj")
    calls = []
    monkeypatch.setattr(train_mod, "require_training_deps", lambda: None)
    monkeypatch.setattr(
        train_mod, "refresh_auto_settings",
        lambda s, prof, proj: calls.append((prof, proj)) or {},
    )
    with pytest.raises(StellaError, match="no dataset"):
        train_mod.train_project(store, "p1", "proj", update_status=False)
    assert calls == []
