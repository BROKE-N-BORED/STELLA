# STELLA — GitHub repo audit thread verdict (2026-11-12)

Pasted by Joshua into the STELLA Dev thread (2d7b2739) on 2026-11-12 ~21:21 EST.
Source: the repo-audit thread (b074e650). Verbatim, as received.

---

Verdict: a real, coherent v0.2 — a standalone Linux program for fine-tuning LLM models on your PC. Not the stem-separation/key-and-BPM engine — that's StemLab, and the README says so explicitly. 39 files, about 388 KB; 3,332 lines of source plus 1,398 lines of tests. Head 9a821e07, 4 commits, tags v0.1 and v0.2, 0 issues. No description, topics, or license.

Features: profiles (one per base model, role names plus HF base ref), projects (fine-tunes inside profiles), export/import packages, a Qt GUI (1100×680), and a v0.2 training engine — CPU micro-LoRA with checkpoints/resume and an 8 GB RAM guard, GGUF round-trip (merge, llama.cpp convert, Q4_K_M, Ollama Modelfile), and a 12-prompt refusal probe. CLI has 9 subcommands. Sample dataset: 20 rows, 14 tool-call plus 6 plain.

Strengths: the suite claim holds — 110 collected, 100 passed, 10 skipped (torch tests, no torch in the sandbox). CLI verified live end to end; GUI renders cleanly at 1100×680. Honest docs — README admits the real LFM3 proof run on your PC is still outstanding. Installer is well built (private venv, fatal import checks, python3-venv fix named). Lazy torch imports (base install works without the 2 GB stack); atomic JSON writes; settings merge preserves non-GUI fields. Version single-sourced.

Weaknesses: import drops the trained adapter and probe results — the export carries them, the import never brings them back, so a round-tripped "trained" project has no weights. The probe loads the base model twice at once (about 7 GB for LFM3 on an 8 GB machine) — likely OOM on the first real run. Install surface over-promises: README's double-click "Install Stella" doesn't exist (no .desktop in the tree); menu icon points at assets/stella.png, which was never generated (only stella.svg exists; render_icon.py is called by nothing); all files are 100644, so a clone install leaves run.sh and stella-cli non-executable and the launchers dead. maternion typo 6 times, quaternion 0 — same as getcompute, including live code in drive_gui.py:22, visible in the window. "full" method is a dead option — GUI offers it, train.py never reads the setting; selecting it silently trains LoRA. Related drift: RAM guard claims to estimate "before loading anything" but loads the base first; probe gate has no informational mode despite the docs. Also: torch.load(weights_only=False) on optimizer.pt (pickle, cross-machine via export), --steps cap overshoots whole epochs, GGUF export silently deletes previous output, no LICENSE/CI/pinned deps, in-repo audits stale vs v0.2 (audit #3 has no task list).

UI flaws: long Ollama tags truncate in the 260 px profile pane; project status is invisible in the list; no geometry persistence; no window icon set in code; the Train panel is below the fold; the "full" method option does nothing; first profile and first project are auto-selected on launch, against your nothing-selected rule; no menu bar or keyboard shortcuts; GGUF export and probe have no cancel and no progress; delete dialogs don't say what's being destroyed; notes have no visible save affordance of their own.

Ideas: one-click Ollama create after GGUF export, a dataset health panel before training starts, a dry-run estimate button (RAM fit plus step count plus disk needed, computed without loading the model), a loss chart plus run history, checkpoint pruning with a size readout, per-role probe sets, an adapter library for sharing bare adapters, and zip export.

Top 5: fix import to restore the trained adapter and probe results (one function, plus a regression test with a planted adapter). Fix the install surface: ship the icon PNGs, add the double-click Install Stella.desktop, set exec bits in the tree. Make the probe load models one at a time. Fix the maternion typo (6 places) and remove/disable the dead "full" option. Add LICENSE, .gitignore, pinned training requirements, and CI — and refresh the in-repo audit lists for v0.2.

I verified the big claims myself: I cloned HEAD 9a821e07 and ran the suite (100 passed, 10 skipped, 29.5 seconds). I reproduced the import drop live — planted a fake adapter and probe results into an export, marked it trained, imported into a fresh home, and the imported project had only profile.json, project.json, and notes.md while keeping status "trained". I confirmed the probe's double load in code (probe.py lines 190 and 192), counted the typo byte-exact (maternion 6×, quaternion 0×), confirmed there's no .desktop anywhere, assets/ holds only stella.svg, render_icon.py is called by nothing, install.sh line 54 points the icon at the missing PNG, every file is 100644, the "full" option exists only as the DEFAULT_TRAIN literal in train.py, torch.load uses weights_only=False, and the first profile and project are auto-selected (gui.py lines 436 and 461). What I couldn't verify: whether GitHub Releases exist for tags v0.1/v0.2, the real LFM3 run on your PC, real llama.cpp convert/quantize, real Ollama interaction, or whether a published zip contains the icon PNGs or an Install Stella launcher.

One note: a new repo appeared tonight — Adaptive-Conceptual-Resonance-ACR-, created 21:11 EST, verified live and public. I've added it to the queue as #28; it audits last.

BNB-SKILLS is being audited now.

---

## Corrections noted by Arlo in this thread (2026-11-12 ~21:21)

- "Audit #3 has no task list" is WRONG — audit #3 has a standalone task list
  (audit-03-export-import-task-list.md, 20 tasks) and is fully covered in the
  merged list. Do not create a task for it.
- GitHub Releases for v0.1 and v0.2 DO exist (both live, assets verified
  byte-exact by download). The verdict's "couldn't verify" on this is settled.
- The published v0.2 zip DOES contain the icon PNGs (they ride in the zip
  only — the push path can't carry binaries). It does NOT contain an Install
  Stella launcher — no .desktop exists anywhere.
- Audit #6 (Installer + icon) is running in this thread at the time the
  verdict landed; its own findings will merge later and must dedup against
  the install-surface tasks added from this verdict.
