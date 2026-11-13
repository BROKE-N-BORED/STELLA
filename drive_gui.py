"""Drive the Stella window offscreen and save a screenshot for eyeballing."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from stella.model import Store
from stella.gui import MainWindow

home = Path("/tmp/stella-shoot-home")
import shutil
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
win = MainWindow(store=store)
win.show()
app.processEvents()
# Select the first profile / first project explicitly.
win.profile_list.setCurrentRow(0)
app.processEvents()
win.project_list.setCurrentRow(0)
app.processEvents()
out = Path("/tmp/stella-window.png")
pixmap = win.grab()
pixmap.save(str(out))
print(f"saved {out} {pixmap.width()}x{pixmap.height()} ({out.stat().st_size} bytes)")
print("profiles:", win.profile_list.count(), "projects:", win.project_list.count())
print("profile0:", win.profile_list.item(0).text())
print("project0:", win.project_list.item(0).text())
print("role field:", win.prof_role.text(), "| tag:", win.prof_tag.currentText())
# Second grab: scroll the detail pane to the Train panel (v0.2).
win.detail_scroll.verticalScrollBar().setValue(
    win.detail_scroll.verticalScrollBar().maximum()
)
app.processEvents()
out2 = Path("/tmp/stella-train-panel.png")
pixmap2 = win.grab()
pixmap2.save(str(out2))
print(f"saved {out2} {pixmap2.width()}x{pixmap2.height()} ({out2.stat().st_size} bytes)")
print("train widgets:", win.train_start_btn.text(), "|",
      win.train_pause_btn.text(), "|", win.train_resume_btn.text(), "|",
      win.train_export_gguf_btn.text(), "|", win.train_probe_btn.text())
