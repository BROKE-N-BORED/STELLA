"""Drive the Stella window offscreen and save screenshots for eyeballing.

Grabs: the main window (session set), the menu open, the Profile
window, the How to Use window. Run with the Qt test env:

  LD_LIBRARY_PATH=~/workspace/qt-libs/root/usr/lib/x86_64-linux-gnu \
  __EGL_VENDOR_LIBRARY_DIRS=~/workspace/qt-libs/root/usr/share/glvnd/egl_vendor.d \
  QT_QPA_PLATFORM=offscreen TMPDIR=/tmp \
  ~/workspace/forge-v2-testenv/bin/python drive_gui.py
"""
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from stella.gui import MainWindow
from stella.model import Store

home = Path("/tmp/stella-shoot-home")
if home.exists():
    shutil.rmtree(home)
store = Store(home)
store.create_profile("lfm3-tool", ollama_tag="lfm3:1.7b", role="fast",
                     display_name="LFM3 Tool Seat")
store.create_profile("minicpm5-driver", ollama_tag="maternion/minicpm5-heretic:2b",
                     role="driver", display_name="MiniCPM5 Driver")
store.create_profile("qwen3-vision", ollama_tag="qwen3-vl:2b-instruct",
                     role="vision", display_name="Qwen3 Vision")
store.create_project("lfm3-tool", "tool-calls", dataset_ref="forge-traces.jsonl",
                     metamorph_mode="both")
store.create_project("lfm3-tool", "short-replies", metamorph_mode="morph")
store.write_notes("lfm3-tool", "tool-calls",
                  "Goal: tighter tool-call format, fewer fenced-JSON slips.\n")
store.create_project("minicpm5-driver", "forge-dialect", metamorph_mode="morph")

app = QApplication([])
settings = QSettings("/tmp/stella-shoot-settings.ini",
                     QSettings.Format.IniFormat)
win = MainWindow(store=store, settings=settings)
win.show()
app.processEvents()
# Set the session: lfm3-tool / tool-calls, and expand the profile.
win.set_session("lfm3-tool", "tool-calls")
app.processEvents()
print("profiles:", win.tree.topLevelItemCount(),
      "projects under lfm3-tool:",
      win.tree.topLevelItem(0).childCount()
      if win.tree.topLevelItemCount() else 0)
print("session:", win.session_title.text())
print("summary:", win.session_summary.text().replace("\n", " | "))


def _save(widget, name):
    out = Path(f"/tmp/{name}")
    pixmap = widget.grab()
    pixmap.save(str(out))
    print(f"saved {out} {pixmap.width()}x{pixmap.height()} "
          f"({out.stat().st_size} bytes)")


# 1. Main window with a session set.
_save(win, "stella-v04-window.png")

# 2. The menu open. showMenu() pops it; grab the window (the popup
# is a separate top-level window offscreen, so grab the menu itself).
win.menu_button.showMenu()
app.processEvents()
menu = win.menu
_save(menu, "stella-v04-menu.png")
menu.close()
app.processEvents()

# 3. The Profile window.
prof_win = win.open_profile_window("lfm3-tool")
app.processEvents()
_save(prof_win, "stella-v04-profile.png")
print("profile window title:", prof_win.windowTitle())

# 4. The How to Use window, first topic selected.
howto = win.open_howto_window()
howto.topic_list.setCurrentRow(0)
app.processEvents()
_save(howto, "stella-v04-howto.png")

# 5. The session scrolled to the Train panel.
win.session_scroll.verticalScrollBar().setValue(
    win.session_scroll.verticalScrollBar().maximum()
)
app.processEvents()
_save(win, "stella-v04-train-panel.png")
print("train widgets:", win.train_start_btn.text(), "|",
      win.train_pause_btn.text(), "|", win.train_resume_btn.text(), "|",
      win.train_export_gguf_btn.text(), "|", win.train_probe_btn.text())
print("activity:", win.activity_text.text())
