"""STELLA v0.34.0 tests — one-click "Put it in Ollama".

The last terminal touchpoint in Stella: after a GGUF export the
window used to present an `ollama create ...` command for the
user to run themselves. Now the export's finish moment offers
ONE button, "Put it in Ollama", which runs the create on the job
card (the T89 engine, gguf.create_in_ollama — the same mechanism
requant and the CLI --create flag use). A model with the same
name already in Ollama is replaced only after the user says so
(default No), in the window and on the CLI alike. The typed
command stays in the log as a detail line for power users; it is
never the required path.
"""
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

import stella.gguf as gguf_mod
import stella.ollama as ollama_mod
from stella.model import STELLA_VERSION, StellaError
from stella.ollama import name_taken

ROOT = Path(__file__).resolve().parent.parent


def _run_cli(home, *args):
    """Run the real `python -m stella.cli` in a subprocess."""
    env = dict(os.environ)
    env["STELLA_HOME"] = str(home)
    return subprocess.run(
        [sys.executable, "-m", "stella.cli", *args],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )


# -- Version --------------------------------------------------------


def test_version_is_0_36_0(home):
    """The version is 0.36.0 everywhere the CLI reports it."""
    assert STELLA_VERSION == "0.36.0"
    res = _run_cli(home, "--version")
    assert res.returncode == 0
    assert "0.36.0" in res.stdout


@pytest.fixture()
def window(qapp, seeded, settings):
    """The main window on the seeded store — the same fixture
    test_v33.py uses."""
    from stella.gui import MainWindow

    win = MainWindow(store=seeded, settings=settings)
    win.show()
    qapp.processEvents()
    if win._model_list_worker is not None:
        win._model_list_worker.wait(5000)
        qapp.processEvents()
    yield win
    from tests.test_gui import _wait_for_all_workers

    _wait_for_all_workers(win, qapp)
    if win._hub_lookup_worker is not None:
        win._hub_lookup_worker.wait(5000)
        qapp.processEvents()
    win.close()


def test_window_title_carries_version(window):
    """The window title carries STELLA 0.36.0."""
    assert "0.36.0" in window.windowTitle()


# -- name_taken: the replace check -----------------------------------


def test_name_taken_matches_plain_and_latest():
    """A model created without a tag is filed by Ollama under
    "<name>:latest" — both spellings are the same model."""
    assert name_taken("p1-proj", ["p1-proj"])
    assert name_taken("p1-proj", ["p1-proj:latest"])
    assert not name_taken("p1-proj", ["other:latest"])
    assert not name_taken("p1-proj", [])


def test_name_taken_tagged_name_matches_only_itself():
    assert name_taken("p1:q4", ["p1:q4"])
    assert not name_taken("p1:q4", ["p1:latest"])


# -- The JobCard's finish-moment action -------------------------------


def test_finish_moment_action_button_waits_for_the_user(qapp):
    """With an action the moment does not time out: the button
    stays up until it is clicked, and the click fires once."""
    from stella.gui import JobCard

    card = JobCard()
    fired = []
    card.finish_moment(
        "GGUF ready.", action_text="Put it in Ollama",
        on_action=lambda: fired.append(True),
    )
    assert card.isVisible()
    assert card.action_btn.isVisible()
    assert card.action_btn.text() == "Put it in Ollama"
    assert card._moment_timer.isActive() is False
    card.action_btn.click()
    assert fired == [True]
    assert card.action_btn.isVisible() is False
    # A second click cannot fire it again.
    card.action_btn.click()
    assert fired == [True]
    card.finish()


def test_finish_moment_action_survives_reduced_motion(qapp):
    """Reduced motion hides a plain moment, but the action
    button still has to be there to click."""
    from stella.gui import JobCard

    card = JobCard()
    card.finish_moment(
        "GGUF ready.", reduced_motion=True,
        action_text="Put it in Ollama", on_action=lambda: None,
    )
    assert card.isVisible()
    assert card.action_btn.isVisible()
    card.finish()
    assert card.action_btn.isVisible() is False


def test_plain_finish_moment_clears_a_stale_action(qapp):
    """A later plain finish (or a new job) never leaves the old
    button behind to fire for a job that is gone."""
    from stella.gui import JobCard

    card = JobCard()
    card.finish_moment(
        "GGUF ready.", action_text="Put it in Ollama",
        on_action=lambda: None,
    )
    assert card.action_btn.isVisible()
    card.finish_moment("Training done.")
    assert card.action_btn.isVisible() is False
    card.finish_moment(
        "GGUF ready.", action_text="Put it in Ollama",
        on_action=lambda: None,
    )
    card.start("Exporting GGUF", True)
    assert card.action_btn.isVisible() is False
    card.finish()


# -- How to Use -------------------------------------------------------


def test_howto_gguf_topic_describes_the_one_click():
    """The GGUF topic no longer tells the user to run a command:
    it names the Put it in Ollama button and the replace ask."""
    from stella.howto import topic_text

    gguf = topic_text("GGUF export to Ollama")
    assert "Put it in Ollama" in gguf
    assert "Nothing to type" in gguf
    assert "asks\nbefore replacing it" in gguf
    assert "create command to run" not in gguf


# -- The export finish moment in the window ----------------------------


def _seed_export(window, seeded, tmp_path, monkeypatch, *, record=True):
    """Run a fake GGUF export from the window: the fake engine
    writes the Modelfile and (unless record=False) the export
    record into the project dir, exactly like the real one."""
    seeded.update_profile("lfm3-tool", role="utility")
    window.set_session("lfm3-tool", "tool-calls")
    modelfile = tmp_path / "Modelfile"
    modelfile.write_text("FROM /tmp/model.gguf\n")
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory",
        lambda *a, **k: str(tmp_path),
    )

    def fake_export(store, profile, project, dest, **kwargs):
        if record:
            (
                seeded.project_dir(profile, project)
                / "gguf-export.json"
            ).write_text(json.dumps({
                "ollama_name": "lfm3-tool-tool-calls",
                "modelfile": str(modelfile),
            }))
        return {
            "gguf": str(tmp_path / "model.gguf"), "gguf_bytes": 123,
            "ollama_create": (
                f"ollama create lfm3-tool-tool-calls -f {modelfile}"
            ),
        }

    monkeypatch.setattr(gguf_mod, "export_gguf", fake_export)
    window.export_gguf_gui()


def test_export_finish_offers_put_it_in_ollama(
    window, seeded, tmp_path, monkeypatch, qapp
):
    """The export's finish moment gains the one button; clicking
    it runs `ollama create` with the export's name and Modelfile,
    and the success line names the model and where it shows up."""
    from tests.test_gui import _wait_for_job

    _seed_export(window, seeded, tmp_path, monkeypatch)
    _wait_for_job(window, qapp)
    card = window.job_card
    assert card.action_btn.isVisible()
    assert card.action_btn.text() == "Put it in Ollama"
    # The typed command is a log detail now, never the path.
    assert "The command, if you want to run it yourself:" in (
        window.train_log.toPlainText()
    )
    seen = []
    monkeypatch.setattr(
        gguf_mod, "create_in_ollama",
        lambda name, mf, **k: seen.append((name, str(mf))) or "created",
    )
    card.action_btn.click()
    _wait_for_job(window, qapp)
    modelfile = tmp_path / "Modelfile"
    assert seen == [("lfm3-tool-tool-calls", str(modelfile))]
    assert (
        "lfm3-tool-tool-calls is in Ollama now. It will show up "
        "in Code Forge's model list."
    ) in window.statusBar().currentMessage()


def test_export_finish_without_record_offers_no_button(
    window, seeded, tmp_path, monkeypatch, qapp
):
    """No export record, nothing to put: the finish moment stays
    a plain summary with no button."""
    from tests.test_gui import _wait_for_job

    _seed_export(window, seeded, tmp_path, monkeypatch, record=False)
    _wait_for_job(window, qapp)
    assert window.job_card.action_btn.isVisible() is False


# -- Replace confirm, failure, missing Ollama -------------------------


def _seed_record(seeded, tmp_path):
    """An export record on disk for the panel-button tests."""
    modelfile = tmp_path / "Modelfile"
    modelfile.write_text("FROM /tmp/model.gguf\n")
    (
        seeded.project_dir("lfm3-tool", "tool-calls")
        / "gguf-export.json"
    ).write_text(json.dumps({
        "ollama_name": "lfm3-tool-tool-calls",
        "modelfile": str(modelfile),
    }))
    return modelfile


def test_put_asks_before_replacing_and_no_runs_nothing(
    window, seeded, tmp_path, monkeypatch, qapp
):
    """The name is taken (the cache says so): the question comes
    first, its default is No, and No runs nothing."""
    from stella.ollama import MODEL_CACHE
    from tests.test_gui import _wait_for_job

    _seed_record(seeded, tmp_path)
    window.set_session("lfm3-tool", "tool-calls")
    MODEL_CACHE.set_snapshot(["lfm3-tool-tool-calls:latest"])
    try:
        asked = []
        monkeypatch.setattr(
            QMessageBox, "question",
            lambda *a, **k: asked.append(a) or QMessageBox.No,
        )
        seen = []
        monkeypatch.setattr(
            gguf_mod, "create_in_ollama",
            lambda name, mf, **k: seen.append(name) or "created",
        )
        window._refresh_go()
        window.train_create_ollama_btn.click()
        _wait_for_job(window, qapp)
        assert len(asked) == 1
        assert "already in Ollama" in asked[0][2]
        assert asked[0][4] == QMessageBox.No  # the default button
        assert seen == []
        assert "Left the Ollama model lfm3-tool-tool-calls" in (
            window.train_log.toPlainText()
        )
    finally:
        MODEL_CACHE.reset()


def test_put_asks_before_replacing_and_yes_replaces(
    window, seeded, tmp_path, monkeypatch, qapp
):
    """Yes on the replace question runs the create."""
    from stella.ollama import MODEL_CACHE
    from tests.test_gui import _wait_for_job

    modelfile = _seed_record(seeded, tmp_path)
    window.set_session("lfm3-tool", "tool-calls")
    MODEL_CACHE.set_snapshot(["lfm3-tool-tool-calls:latest"])
    try:
        monkeypatch.setattr(
            QMessageBox, "question",
            lambda *a, **k: QMessageBox.Yes,
        )
        seen = []
        monkeypatch.setattr(
            gguf_mod, "create_in_ollama",
            lambda name, mf, **k: seen.append((name, str(mf)))
            or "created",
        )
        window._refresh_go()
        window.train_create_ollama_btn.click()
        _wait_for_job(window, qapp)
        assert seen == [("lfm3-tool-tool-calls", str(modelfile))]
    finally:
        MODEL_CACHE.reset()


def test_put_failure_is_a_plain_sentence(
    window, seeded, tmp_path, monkeypatch, qapp
):
    """A failed create lands as plain words in the log and the
    status bar — no traceback, no crash, the window lives."""
    from tests.test_gui import _wait_for_job

    _seed_record(seeded, tmp_path)
    window.set_session("lfm3-tool", "tool-calls")

    def fail(name, mf, **k):
        raise StellaError(
            "Ollama could not create the model. "
            "Is Ollama running on this PC?"
        )

    monkeypatch.setattr(gguf_mod, "create_in_ollama", fail)
    window._refresh_go()
    window.train_create_ollama_btn.click()
    _wait_for_job(window, qapp)
    assert "could not create the model" in (
        window.statusBar().currentMessage()
    )
    assert window.isVisible()


def test_put_with_ollama_missing_is_a_plain_sentence(
    window, seeded, tmp_path, monkeypatch, qapp
):
    """The real create with no ollama binary on PATH: the
    engine's own plain sentence, not a FileNotFoundError."""
    from tests.test_gui import _wait_for_job

    _seed_record(seeded, tmp_path)
    window.set_session("lfm3-tool", "tool-calls")
    monkeypatch.setattr("shutil.which", lambda name: None)
    window._refresh_go()
    window.train_create_ollama_btn.click()
    _wait_for_job(window, qapp)
    assert "Ollama is not installed" in (
        window.statusBar().currentMessage()
    )


# -- CLI parity: --create asks before replacing ------------------------


def _cli_export_setup(home, tmp_path, monkeypatch):
    """A profile + project on the CLI home, with fake export and
    create functions (the T89 CLI test's shape)."""
    import stella.cli as cli_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    _run_cli(home, "create-profile", "p1", "--base", "test/tiny-model")
    _run_cli(home, "create-project", "p1", "proj")
    modelfile = tmp_path / "Modelfile"
    modelfile.write_text("FROM /tmp/model.gguf\n")
    monkeypatch.setattr(
        gguf_mod, "export_gguf",
        lambda *a, **k: {
            "merged_hf": "/tmp/merged",
            "gguf": "/tmp/model.gguf", "quant": "Q4_K_M",
            "gguf_bytes": 123,
            "modelfile": str(modelfile),
            "ollama_name": "p1-proj",
            "ollama_create": f"ollama create p1-proj -f {modelfile}",
        },
    )
    seen = []
    monkeypatch.setattr(
        gguf_mod, "create_in_ollama",
        lambda name, mf, **k: seen.append((name, str(mf))) or "created",
    )
    return cli_mod, seen, modelfile


def test_cli_create_asks_before_replacing_and_no_skips(
    home, tmp_path, monkeypatch, capsys
):
    """--create with the name taken asks [y/N]; No leaves the
    model as it was and still exits 0 (the export itself is
    done)."""
    cli_mod, seen, _mf = _cli_export_setup(home, tmp_path, monkeypatch)
    monkeypatch.setattr(
        ollama_mod, "list_models", lambda *a, **k: ["p1-proj:latest"]
    )
    monkeypatch.setattr("sys.stdin", io.StringIO("n\n"))
    code = cli_mod.main(
        ["export-gguf", "p1", "proj", str(tmp_path), "--create"]
    )
    assert code == 0
    captured = capsys.readouterr()
    assert "already in Ollama" in captured.err
    assert "Left the Ollama model p1-proj as it was." in captured.out
    assert seen == []


def test_cli_create_yes_flag_replaces_without_asking(
    home, tmp_path, monkeypatch, capsys
):
    """--yes answers the replace question ahead of time: the
    create runs even though stdin would have said no."""
    cli_mod, seen, modelfile = _cli_export_setup(
        home, tmp_path, monkeypatch
    )
    monkeypatch.setattr(
        ollama_mod, "list_models", lambda *a, **k: ["p1-proj:latest"]
    )
    monkeypatch.setattr("sys.stdin", io.StringIO("n\n"))
    code = cli_mod.main(
        ["export-gguf", "p1", "proj", str(tmp_path),
         "--create", "--yes"]
    )
    assert code == 0
    assert seen == [("p1-proj", str(modelfile))]
    assert "Created in Ollama as p1-proj." in capsys.readouterr().out


def test_cli_create_yes_answer_replaces(
    home, tmp_path, monkeypatch, capsys
):
    """A typed yes at the prompt replaces the model."""
    cli_mod, seen, modelfile = _cli_export_setup(
        home, tmp_path, monkeypatch
    )
    monkeypatch.setattr(
        ollama_mod, "list_models", lambda *a, **k: ["p1-proj"]
    )
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    code = cli_mod.main(
        ["export-gguf", "p1", "proj", str(tmp_path), "--create"]
    )
    assert code == 0
    assert seen == [("p1-proj", str(modelfile))]


def test_cli_create_free_name_never_asks(
    home, tmp_path, monkeypatch, capsys
):
    """A name nobody has: no question, the create just runs."""
    cli_mod, seen, modelfile = _cli_export_setup(
        home, tmp_path, monkeypatch
    )
    monkeypatch.setattr(
        ollama_mod, "list_models", lambda *a, **k: ["other:latest"]
    )
    monkeypatch.setattr("sys.stdin", io.StringIO("n\n"))
    code = cli_mod.main(
        ["export-gguf", "p1", "proj", str(tmp_path), "--create"]
    )
    assert code == 0
    assert seen == [("p1-proj", str(modelfile))]


def test_cli_export_names_the_create_flag(
    home, tmp_path, monkeypatch, capsys
):
    """Without --create the printed commands stay, and the
    output names the flag that runs them instead."""
    cli_mod, seen, _mf = _cli_export_setup(home, tmp_path, monkeypatch)
    code = cli_mod.main(["export-gguf", "p1", "proj", str(tmp_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "ollama create p1-proj" in out  # the command, as detail
    assert "add --create" in out
    assert seen == []
