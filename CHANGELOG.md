# Changelog

## v0.7.0 — 2026-11-13

Provider connections: the chat can talk to Groq, Gemini, or any
OpenAI-compatible service with your own key, as well as to a model
on this PC through Ollama.

- New `stella/providers.py`: provider registry, key storage, and
  chat clients. Keys live only in `~/.stella/providers.json`,
  file mode 0600, and never appear in code, exports, or debug
  reports. Groq and Gemini speak the OpenAI chat shape (Gemini
  through Google's OpenAI-compatible endpoint, key as the Bearer
  token). Custom takes any base URL, key, and model name.
- Settings gains an AI providers section: one row per keyed
  provider with a password-style key field, Save, Test (one tiny
  call, run off the UI thread), and Remove. A short line says the
  keys stay on this PC.
- The chat-model picker now groups models by provider: On this PC
  (Ollama), then Groq, Gemini, and Custom. A provider with no key
  saved shows its models greyed out.
- ChatAgent takes a provider + model; a missing key is a plain-words
  message naming Settings, never a crash. `stella-cli chat` takes
  `--provider groq|gemini|custom|ollama` and `--model`.
- Debug-log scrubber now also redacts bare Groq (gsk_...) and
  Google (AIza...) keys.

## v0.6.0 — 2026-11-13

Provider chat: an AI chat inside Stella that sets up and runs
training for the user, instead of forms and panels. Built to the
"as simple as a toy for a 5-year-old" bar.

- Chat window (Menu, then Chat): talk in plain words ("train LFM3
  to write short replies") and the chat asks only for what it
  needs, fills the rest with defaults, and runs the job. Tool calls
  are narrated in plain words while they run, and a Cancel button
  stops the current job. One chat window at a time; the agent loop
  runs in a worker thread, never on the UI thread.
- The training template (new `stella/chat_agent.py`): the 8 steps
  every training run needs, whatever the model (Goal, Base model,
  Data, Settings, Train, Check, Export, Test and back up). The
  agent walks one step at a time and says which step it is on. On
  "just do it" it runs the whole template end to end with the
  defaults and the sample dataset.
- Tool calling that works with small local models: the model emits
  a fenced ```tool block holding one JSON object; the agent
  parses it, runs the tool, and feeds the result back. Malformed
  tool JSON never crashes the loop: the agent asks the user in
  plain words. Capped at 12 tool calls per message.
- Tools wrap the existing engine only (no new training logic):
  list/create profile and project, settings, dataset, sample
  dataset, start training, training status, refusal probe, GGUF
  export, checkpoints, sleep, sleep status, weight downloads,
  How to Use lookup. Settings are validated (rank 1-64, learning
  rate 0-1, and so on); "full" fine-tuning is refused in plain
  words.
- Chat model picker in Settings: pick which installed Ollama model
  the chat talks to. Nothing is picked by default; if none is
  picked, the chat asks which installed model to use instead of
  failing.
- `stella-cli chat`: the same agent as an interactive REPL
  (--model to pick the model, /quit to exit).
- How to Use gains a Chat topic (11 topics now).

## v0.4.0 — 2026-11-13

Redesign + one-click model downloads + built-in guide, from Joshua's
sketch and the "teenagers and old people can use it" bar. The
three-pane window is gone.

- Window redesign: a Menu button top-left (Profiles, New profile,
  Projects, New project, Export, Import, Settings, How to Use
  Stella); a collapsible profile tree on the left (each profile
  expands to show its projects); the main area shows the current
  training session: profile and project summary, model download,
  Train panel, Sleep panel. Clicking a project in the tree sets the
  training session, and the session is remembered across restarts.
  Nothing is selected on first run.
- Dedicated windows, no cramming: double-clicking a profile or a
  project row opens its own window, with the v0.3.1 plain-words help
  lines under every field. Settings has its own window (Stella home,
  Ollama status + host, training defaults, Debug report button).
- One-click model downloads (new `stella/provision.py`): a Download
  model button in the Profile window and the session view. Base
  weights download from Hugging Face in a separate process with a
  progress bar and a Cancel button; interrupted downloads resume
  where they left off. Status shows Not downloaded / Downloading x%
  / Ready + size on disk. When training starts and the weights are
  missing, Stella offers the download first instead of failing.
  Plain-words failures: no network, no Base ref set, not enough disk
  (checked before the download starts).
- How to Use Stella window: a full index (Getting started, Picking a
  model, Profiles, Projects, Training, Sleep, Export and import, The
  refusal probe, GGUF export to Ollama, Troubleshooting) in plain
  words, accurate about what Stella actually does: MetaMorphAi modes
  do nothing yet, full fine-tuning doesn't run on this PC, training
  takes hours on CPU.
- Debug log layer (U12): rotating timestamped logs under the Stella
  home, last-200 ring buffer, traceback capture, scrubbed debug
  report from the Settings window, crash handler in the real app
  entry.
- Single instance (U27): re-clicking the icon focuses the running
  app, never starts a second copy.
- Destructive confirmations default to No, and Escape leaves things
  untouched (U23/U31). The delete confirm used to default to Yes.
- Window geometry and tree expansion are remembered between runs
  (U5); tree expansion and scroll survive refreshes (U28); a visible
  activity light + status text shows what Stella is doing during
  downloads, training, and sleep (U16).
- No em-dashes in any visible UI text (U33): every user-visible
  string in the window, the dialogs, the status messages, and the
  engine error messages was swept. Same words, em-dashes out.

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
