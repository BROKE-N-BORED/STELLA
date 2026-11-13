# Changelog

## v0.3.1 — 2026-11-13

Real-PC usability patch, from Joshua's first run on his Mint PC.
The v0.3 window opened, but the New Profile form rendered as a
garbled smear over the main window, the desktop icon showed the
generic gear, and the desktop launcher was untrusted.

- New Profile is a real window now (QDialog + exec()), not a
  frameless QWidget child — the form can no longer smear over the
  main window (merged-list T11, audit #4 W1).
- New Profile asks for ONE thing: pick a model. No role, no display
  name, no base ref up front — the profile's name comes from the
  model (`LiquidAI/LFM3-1.7B` -> `lfm3-1-7b`), a clash gets `-2`,
  and role/display/base can be changed later in the profile panel.
  An installed model becomes the Ollama tag; a namespaced id that
  isn't installed becomes the Hugging Face base ref.
- The profile panel explains itself: one plain line under Display
  name, Role, Ollama tag, and Base ref saying what each one is for.
  The Processor row is gone — nothing in Stella ever read that
  field, so showing it only asked a question nobody could answer.
  The stored value stays in profile.json for compatibility.
- New icon: the ✨ sparkles (gold, on transparent), in the SVG,
  all PNG sizes, the window title bar, and the launcher.
- Installer fixes (merged-list T14): `Icon=` is unquoted (GLib
  never stripped quotes from Icon=, which is why the menu showed
  the gear); `StartupNotify=false` so a slow cold start no longer
  trips a "Timeout was reached" launch error; the desktop launcher
  is marked trusted with gio so Cinnamon stops asking; and
  install.sh renders the icon PNGs from the SVG when they're
  missing (fresh clone), using QtSvg from PySide6-Addons.

## v0.3 — 2026-11-13

Sleep phase (Item 4): consolidate new rows without forgetting old ones.

- Sleep engine (stella/sleep.py): a sleep cycle trains a NEW
  low-rank LoRA adapter (rank capped at 8) on the dataset rows
  added since the last sleep, tracked by content hash in a sleep
  manifest. The base and all prior adapters stay frozen. Each cycle
  stores its adapter, checkpoints, rows, and report under
  `sleep/cycle-N/`; an interrupted cycle resumes instead of
  restarting. Consolidation reuses the training engine
  (train_project with a per-cycle work dir) — it does not fork it.
- Dreaming (optional, `--dream`): the local Ollama model writes
  synthetic practice examples, seeded by real rows. Every dreamed
  row passes the same validation as real data, dedupes against
  real and already-dreamed rows, and dreamed rows are capped at
  the number of real rows in the cycle (at most 10 per call). If
  Ollama is unreachable, dreaming is skipped with a plain message
  and sleep still runs on real rows.
- Replay check (the forgetting guard): before a cycle is accepted,
  the new adapter is evaluated on held-out OLD validation rows
  (kept from prior cycles) plus NEW validation rows. A cycle whose
  old loss degrades more than 10% relative (configurable) is
  flagged DEGRADED — saved, never silently accepted. The replay
  loads the base model ONCE and evaluates sequentially by adapter
  swapping; it never loads two models at once.
- RAM guard reused: sleep refuses when the estimate does not fit
  8 GB, with a plain message. Sleep leaves the project status
  alone — it is a background job, not a retrain.
- CLI: `sleep` (with --dream, --dream-model, --rows, --threshold)
  and `sleep-status` (per-cycle stats + unslept row count). Cheap
  checks run before the dependency gate, so a missing dataset or
  "nothing new" is reported even on a base install. The Ctrl+C
  handler sets the pause flag only (no printing inside the signal
  handler — the train command's pause crash is not repeated here).
- Sleep panel in the window: Sleep button (worker-threaded, gated
  on save success), Dream checkbox, cycle list with per-cycle
  stats, click a cycle to read its full report. Sleep and training
  cannot run at the same time (each loads the base model).
- Export/import: sleep cycles travel with the export (manifest +
  adapters + rows + replay reports) and import restores them
  whole — a round-trip test pins it.
- Training engine refactors (small, backward-compatible): per-row
  dataset validation shared by load_dataset and dreaming; one
  public evaluate_loss used by per-epoch validation and the replay
  check; train_project takes a work dir, a status flag, and a
  settings override so sleep can reuse it. The requires_grad
  UserWarning from float(out.loss) is fixed in both places it
  occurred.

## v0.2 — 2026-11-12

First proof loop: the training engine (Item 3).

- Training engine (stella/train.py): CPU micro-LoRA (transformers +
  PEFT), batch 1 with gradient accumulation, completion-only loss,
  train/validate split, per-epoch validation loss, loss log per
  project. LoRA target modules auto-detected from the model.
- RAM guard: estimates base weights + LoRA gradients + AdamW states
  + activations + 1 GB headroom before loading anything, and refuses
  a run that will not fit 8 GB. A full 1.7B fine-tune (~28 GB of
  optimizer state) is refused outright.
- Checkpoints + resume: adapter + optimizer + training state saved
  every N steps; Pause (button or Ctrl+C) checkpoints cleanly and
  `--resume` continues from the saved step, optimizer included.
- GGUF round-trip (stella/gguf.py): merge the adapter into the base,
  convert with llama.cpp to F16 GGUF, quantize (Q4_K_M default),
  write an Ollama Modelfile with the exact `ollama create` command.
  llama.cpp missing is a clear error with install steps, never a
  silent failure.
- Refusal probe (stella/probe.py): 12 benign prompts run before and
  after tuning, refusal-rate change reported and saved. Informational
  for LFM3; a gate for governing-seat tunes.
- Train panel in the window: dataset picker + sample dataset button,
  Start / Pause / Resume, progress bar + loss readout, checkpoint
  list, Export GGUF, Run refusal probe, training log. Training runs
  in a worker thread; the window stays responsive.
- CLI: `train`, `export-gguf`, `probe`; `create-profile --base` sets
  the Hugging Face base ref.
- Sample dataset (data/sample-tool-calls.jsonl): 20 synthetic Forge
  tool-call traces (14 tool calls, 6 plain answers) so the proof
  loop runs without real data.
- Training packages are optional: `bash install-training.sh`
  installs torch CPU + transformers + peft + accelerate (about 2 GB)
  into the private venv. The base install stays light; training
  without them names the installer instead of failing cryptically.
- Exports now carry the trained adapter in `weights/` (and the
  probe results when run) instead of the placeholder note.

## v0.1 — 2026-11-12

First skeleton. No training engine yet (Item 3).

- Profiles with friendly role names, Ollama tag picker (works offline
  when Ollama is down), full create/rename/delete.
- Projects inside profiles: dataset ref, training settings, MetaMorphAi
  mode (morph / compress / both), checkpoints dir, notes.
- Export a project as a folder (manifest, config, README, weights,
  checkpoints) and import it back with verification.
- Native Qt window: profiles left, projects middle, detail right.
- CLI: profiles, projects, export, import, create-profile,
  create-project.
- Installer: private venv, app-menu launcher with star icon, desktop
  icon, `stella` command on PATH.
- Verification fixes (same day): status text shown once, in the
  status bar only (a duplicate label was removed); launcher Exec/Icon
  quoted so install paths with spaces work; installer names the
  `sudo apt install python3-venv` fix if the venv module is missing.
