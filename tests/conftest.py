"""Shared fixtures for the Stella test suite."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from stella.model import Store  # noqa: E402


@pytest.fixture()
def home(tmp_path):
    return tmp_path / "stella-home"


@pytest.fixture()
def store(home):
    return Store(home)


@pytest.fixture()
def seeded(store):
    """One profile (lfm3, role fast) with one project."""
    store.create_profile(
        "lfm3-tool", ollama_tag="lfm3:1.7b", role="fast",
        display_name="LFM3 Tool Seat",
    )
    store.create_project(
        "lfm3-tool", "tool-calls",
        dataset_ref="forge-traces.jsonl",
        metamorph_mode="both",
    )
    return store


@pytest.fixture()
def settings(tmp_path):
    """A QSettings on a temp file, so GUI tests never share the real
    ~/.config settings — session restore would otherwise make tests
    order-dependent."""
    from PySide6.QtCore import QSettings

    return QSettings(
        str(tmp_path / "settings.ini"), QSettings.Format.IniFormat
    )


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
