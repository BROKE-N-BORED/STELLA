"""Helper for the T36 close-during-job test: opens the real window
offscreen, starts a slow fake job, closes mid-job, and exits when
the window closes. The test asserts exit 0 with no "QThread:
Destroyed while thread is still running" on stderr.

Usage: python tests/_close_driver.py <home-dir>
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from stella.gui import MainWindow  # noqa: E402
from stella.model import Store  # noqa: E402
from stella.style import apply_stella_style  # noqa: E402

home = Path(sys.argv[1])
store = Store(home)
if not store.list_profiles():
    store.create_profile("p1", ollama_tag="x:1b")
    store.create_project("p1", "proj")

app = QApplication([])
apply_stella_style(app)
settings = QSettings(str(home / "settings.ini"), QSettings.Format.IniFormat)
win = MainWindow(store=store, settings=settings)
win.show()
app.processEvents()
win.set_session("p1", "proj")


def job(ctx):
    for _ in range(200):
        if ctx.is_cancelled():
            return "stopped"
        time.sleep(0.05)
    return "done"


win._start_job_worker(job, "A long job", False)
assert win._job_worker.isRunning()
# Close mid-job: the window must ask the job to stop, show the
# feedback, and close when the job ends — never destroy the thread.
QTimer.singleShot(300, win.close)
sys.exit(app.exec())
