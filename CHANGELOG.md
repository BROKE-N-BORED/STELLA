# Changelog

## v0.15.0 — 2026-11-14

The installer-coherence slice (audit tasks T42, T62, T63, T64, T65,
T66, T67, T68, T69, T130, T132, T133, T134, T135, T136, T137, T138,
T139, T140): the installer tells the truth about failures, installs
are pinned and receipted, the icons live in the hicolor theme, and
there is a double-click installer, an uninstaller, and a doctor.

- T42 — venv failures name the real cause: the python3-venv message
  prints only when the venv module is actually missing; any other
  failure prints the real venv error. Cleanup touches only a .venv
  this run created — a stray file already at .venv is never deleted.
- T62 — run.sh checks PySide6 before exec: a venv without PySide6
  prints a plain "run bash install.sh" message (with a zenity or
  kdialog dialog when there is no terminal to read it in) instead
  of a raw traceback invisible from the menu.
- T63 — install is atomic: the final `import stella` check runs
  before the launcher and symlink are written, so a failed install
  leaves no launcher behind.
- T64 — Install Stella.desktop ships in the tree: double-click it
  to install (it runs install.sh with bash and survives spaced
  paths). The README install section names the real first step,
  qualifies the `stella` command (new terminal or log out/in),
  and documents removal and repair.
- T65 — the scripts carry exec bits in the tree (run.sh,
  stella-cli, install.sh, install-training.sh, run_tests.sh,
  uninstall.sh, Install Stella.desktop), pinned by a test.
- T66 — `stella doctor` checks the venv, PySide6, launcher,
  symlink, and icon, and re-links what is stale after a move; a
  broken venv is reported with the fix named. `--check` only
  reports, without fixing.
- T67 — install.sh's pip lines carry `--timeout 120 --retries 10`,
  like install-training.sh already did.
- T68 — run_tests.sh refuses on a bare checkout with "run bash
  install.sh first" instead of pip-installing into system Python.
- T69 — tests/test_installer.py runs the real installers in a
  scratch HOME: desktop file, icon resolution, symlink, re-install
  idempotence, clone without PNGs, and the failure cases.
- T130 — LICENSE (MIT), pinned requirements (requirements-base.txt:
  PySide6-Essentials/Addons 6.12.0; requirements-train.txt: torch
  2.15.0+cpu, transformers 5.22.2, peft 0.21.2, accelerate 1.15.0),
  both installers consume the pinned files, and a GitHub Actions
  CI workflow runs the base suite (plus the training-stack suite
  in its own job). The repo description/topics half is GitHub-side,
  not tree work.
- T132 — pip failures end with a Stella line naming the step and
  the retry, in both installers.
- T133 — disk-space preflight: the base install refuses below
  ~500 MB free, the training install below ~3 GB, before
  downloading anything.
- T134 — a training re-run with everything already installed
  prints "Training packages are already installed." and exits in
  seconds instead of re-resolving the torch index.
- T135 — the PySide6 check creates a throwaway QApplication
  offscreen instead of import-only, and surfaces the real stderr
  on failure so a missing system lib names itself.
- T136 — the success message reflects reality: the desktop icon
  is claimed only when the copy landed, `stella` is claimed only
  when ~/.local/bin is on PATH (otherwise it says to open a new
  terminal), and the version line is labeled ("Stella 0.15.0").
- T137 — uninstall.sh removes the launcher, desktop copy, symlink,
  menu icons, venv, and receipt, and asks about ~/.stella before
  touching it (default No); the README documents removal.
- T138 — icons install into the hicolor theme at 16/22/24/32/48/
  64/128/256/512, rendered by render_icon.py, so the menu icon
  survives a folder move; the launcher uses the theme name.
- T139 — install.sh writes an install receipt (.stella-install-
  receipt): versions, artifact paths, install time. A failed
  install writes no receipt; install-training.sh refreshes it
  with the torch versions.
- T140 — the README documents the upgrade path: unzip the new
  version, run its install.sh, delete the old folder.

## v0.14.0 — 2026-11-14

The models + UI-polish slice (audit tasks T43, T45, T47, T49, T50,
T58, T59, T61, T145, T146, T147, T149): the model list is cached
and fetched off the UI thread, imports show a preview first and
check the base model, datasets are validated where they are
picked, and the window gets a finish moment, loading states, a
job morph, and accessibility presets.

- T43 — the Ollama model list is cached and fetched off the UI
  thread: one fetch at startup, none on any click, and a Refresh
  button (plus a refresh when the New Profile dialog opens) for
  the rest. The window keeps showing the last good list while a
  refresh is in flight, and a hung Ollama never blocks a click.
- T61 — base-health check on import: a package whose profile
  tag is not installed on this PC warns (naming the tag) instead
  of importing silently and failing later. The check uses the
  cached model list (T43); it never blocks the import.
- T45 — dataset picker + validation: the Project window has a
  Browse button next to the Dataset field, and the field now
  explains itself: a valid file shows its example count, the
  train/check split, and a 3-example preview; a missing file
  warns ("Dataset not found. Is the path right?") without
  blocking the save; a malformed file names the bad line. The
  Train panel's dataset pick reports the same check.
- T47 — the Train panel resets per project and stays pinned to
  the running project: switching projects resets the progress
  bar as well as the loss line, the no-selection state shows an
  empty bar, and switching mid-run leaves the panel on the
  running project (naming it) instead of mixing panels.
- T49 — the missing-training-packages hint is a warning dialog
  now, not a line in the below-fold Train log: on a first run
  without the training stack, the fix is visible without hunting.
- T50 — confirmations survive their refresh: the training-done
  and sleep-done messages are said after the refresh that used
  to overwrite them, so "Trained N steps." is still in the
  status bar after the lists settle (import already did this).
- T59 — the dataset is part of the package decision: export
  offers to copy the dataset in (with its size shown) or keep
  the reference; a bundled dataset is used on import; an
  unbundled reference that is missing on this PC warns and
  offers to locate the file here.
- T58 — import preview dialog: before anything lands, the
  window shows the package's profile, project, tag, version,
  and contents, with the existing-profile warning (T57's
  compare) and the base-health and dataset status, and the
  user confirms or cancels. Cancel imports nothing. The CLI
  prints the same summary before importing, and --preview
  prints it without importing.
- T145 — the finish moment: when a job completes, the job card
  glows gold once with a short summary line, under 300 ms,
  never looping. The reduced-motion preset skips the glow.
- T146 — loading states, never a dead screen: the model list
  shows skeleton rows while Ollama answers, replaced by the
  real rows (with fit verdicts) when they arrive; the Ollama
  status refresh shows it is working.
- T149 — the job picker becomes the job: the picked job tile
  morphs into the running-job card, under 400 ms, and the
  morph stops cleanly if the job is cancelled. Reduced motion
  swaps instantly instead.
- T147 — accessibility presets in Settings: reduced motion
  (turns off the press dip, the job morph, and the finish
  moment, and keeps every state change) and larger text (bigger
  words everywhere), both in plain words and remembered.

## v0.13.0 — 2026-11-14

The export/import + projects slice (audit #3/#8 tasks T23, T29,
T30, T34, T36, T40, T41, T48, T51, T53, T54, T57, T60): packages
are versioned, weights round-trip, deletes go to a trash, and
the project lifecycle has one vocabulary everywhere.

- T29 — one job at a time, enforced by the engine: a lock file
  (`job.lock` in the home) is held for the whole job, so a second
  job — from the window, the CLI, or a second Stella — is refused
  in plain words naming the running job. The kernel releases the
  lock if the holder dies, so a crash can never wedge the home.
  Sleep takes the lock once and its inner training call skips it.
- T36 — closing the window waits for every worker: close during
  a job asks the workers to stop, says "Stopping ..." in the
  status bar, the job card, and the log, and closes for real
  when the last worker ends. The window never destroys a running
  thread (the old Qt abort), and never blocks the UI waiting.
- T40 — package format versioning: the manifest carries `format`
  (this Stella writes and reads format 1), separate from the app
  version. A newer format is refused with "this package needs a
  newer Stella"; a package with no format field is a legacy
  v0.1-v0.12 package and reads as format 1. The three package
  kinds (`stella-export`, `stella-profile-export`,
  `stella-recipe-export`) are defined in one place, and importing
  a known kind this Stella cannot import yet says what the
  package is. The format is documented in docs/FORMAT.md.
- T41 — weights and probe results round-trip: the package's
  weights/ land in the project's adapter/ dir on import (byte
  identical), and probe_results.json comes back too. A package
  whose manifest claims a finished status but carries no weights
  imports as a draft, with a warning in the window and on the
  CLI. The placeholder note is never copied as a weight.
- T23 — trash on delete: deleting a profile or project moves it
  to `trash/` (dated folder), and the confirm dialog offers
  export-first. The File menu's Trash window lists what is
  there, purges one item forever (its own confirm, defaulting
  to No), or empties the trash. Moving a trash folder back
  restores it. Import rollback still destroys outright, so a
  failed import leaves no trash folder behind.
- T30 — probe v2: refusals are read from the reply's first
  sentence, with new markers, a compliance override (a reply
  that starts answering is not a refusal), and the "can't
  believe" idiom excluded. Replies with no answer are counted
  and shown in the CLI, the window, and the chat. The probe
  gate fails a silent model, and an empty prompt list is
  refused. Replies are generated through the chat template
  when the tokenizer has one.
- T34 — target-module override: `--target-modules` on the CLI
  (or `target_modules` in the project settings, CLI wins) picks
  the LoRA target modules instead of auto-detection. A name
  the model does not have is refused with the available names
  listed. No UI: training settings stay out of the window
  (T16).
- T48 — cheap checks first: training reports a bad profile,
  missing dataset, missing base, or nothing-to-resume BEFORE
  the dependency gate, so a mistake is never answered with
  "install the training stack". The dependency check fires
  only when everything else is ready.
- T51 — CLI help everywhere: every flag and positional on all
  15 commands has help, and every command's `--help` shows a
  worked example. The module docstring, the empty-home hint,
  the `stella-cli` wrapper comment, and the README now all list
  the same 15 commands.
- T54 — base_ref sync rule (interim, until Joshua decides drop
  vs define): changing a profile's tag moves base_ref to the
  new tag when the base was following the old tag (or empty);
  a deliberately split base stays split, and an explicit base
  in the same save always wins. Training trusts base_ref.
- T60 — config.json dropped: the manifest already holds the
  settings, and nothing ever read the config.json copy, so
  export stops writing it. Old packages that carry it still
  import; a disagreeing or unreadable config.json is ignored
  and the manifest's values win.
- T53 — one status lifecycle, reconciled: the task's enum
  (draft/ready/training/done/failed/exported) and the engine's
  `trained`/`paused` are now one vocabulary: `draft`, `ready`,
  `training`, `paused`, `done`, `failed`, `exported`. Mapping:
  engine `trained` is now `done` (the task's word, plainer);
  `paused` is kept (pause/resume is a real state with no slot
  in the task enum); `ready` and `failed` are new. A crash
  marks the project `failed`, a graceful stop marks it
  `paused`. `trained` survives only as a legacy alias: old
  project files and old packages read as `done`, and are
  rewritten with the current word on the next write. The
  window shows the status on every tree row and in the
  project window, with a Mark ready button on drafts.
- T57 — merge, don't discard, the profile block on import:
  when the profile already exists, tag / role / base are
  compared with the manifest — identical blocks import
  silently; differing blocks ask (a dialog in the window,
  `--profile-merge keep|take` or a prompt on the CLI). With no
  way to ask, the local values are kept and a warning says so.
  "Take" makes the stored block exactly the package's, and a
  failed import restores the local values. The window and the
  CLI both say when the profile already existed. Extension
  point for T58: `compare_profile_block` in export.py (and its
  diff shape) is what the import preview dialog reuses.

## v0.12.0 — 2026-11-14

The UI rebuild, P1 slice (audit #9, tasks T74-T82): every job
runs as a card, the chat plans before it runs, and STELLA gets
its own look.

- T74 — one job card for every job: Train, Sleep, GGUF export,
  refusal probe, re-quantize, and distill all run as a card
  under the hero, with a progress bar, a live status line, and
  a Cancel button. Sleep stops being a section at the bottom of
  a column. Starting a second job is refused in plain words
  ("A job is already running. Wait for it to finish, or cancel
  it first."). Train and Sleep cancel after the current step
  with a checkpoint saved; the other jobs stop at the next check
  point (a running subprocess is killed). The engines gained
  cancel checks and progress events to feed the card
  (`should_stop` / `on_event` in distill, requant, gguf, probe).
- T75 — re-quantize and distill get window surfaces: both jobs
  already started from the job picker; now they run as job
  cards too, and How to Use stops sending the user to the
  terminal for them. Both start from the window with no typing.
- T76 — chat: click-to-pick model, plan before it runs. When
  no chat model is picked, the chat shows clickable model
  buttons from the installed list instead of "type one of
  these". Before a multi-step plan runs, the agent shows the
  plan ("I will: 1. ... 2. ...") with Run and Cancel buttons
  and waits for the go-ahead. Replies stream as they arrive
  (Ollama `chat_stream`); a tool block is never streamed, so
  the user never sees JSON.
- T77 — the session follows the profile: the last project is
  remembered per profile, so switching profiles restores that
  profile's project. The memory lives in QSettings and survives
  restarts.
- T78 — tree rows show full names, with a health badge: the
  tree pane defaults wider (340 px), every row carries its full
  text as a tooltip, and each profile row shows a health dot —
  green when the weights are ready, amber when they are not,
  grey when Ollama is down and the weights are not ready
  (weights ready wins over Ollama down, since training can
  start without Ollama). The tooltip carries the health line.
- T79 — one honest download row: the Profile window's duplicate
  download row is gone; the main window's row is the only one.
  Download is disabled when there is no repo, and a "Set the
  model source..." button shows instead, opening the profile
  window where Base ref gets set. The Base ref field stops
  showing a tag as if it were a repo (a tag-valued base_ref
  shows blank, with a placeholder saying what belongs there).
- T80 — collapsible section headers: the main panel's train
  details (Dataset, Checkpoints, Training log, Sleep) and every
  Settings section are collapsible groups, open by default.
  The Project window's action row (Save, Rename, Delete,
  Close) is pinned below the scroll area, so Save is visible
  without scrolling.
- T81 — STELLA's own look: one stylesheet (`stella/style.py`),
  drawn from the icon — dark surfaces, the gold accent — applied
  by `main()` to every window. Button presses dip to 0.97 over
  150 ms. No per-frame cost: the sheet is static, the dip is a
  press-only geometry animation.
- T82 — keyboard: shortcuts for the main actions (Ctrl+N new
  profile, Ctrl+Shift+N new project, Ctrl+G run the picked job,
  Ctrl+S save, F1 How to Use, F2 Chat), a visible gold focus
  ring in the stylesheet, and tab order in visual order on the
  main screen and every dedicated window.

## v0.11.0 — 2026-11-14

The UI rebuild, P0 slice (audit #9, tasks T15-T20): the window
becomes toy-simple. Pick a model, pick a job, press go — nothing
else on the way.

- T15 — the main screen is a bento tile now: 1. Pick a model,
  2. Pick a job (Train, Sleep, Make smaller, Teach a small model),
  3. Press go. The Train and Sleep buttons are gone; Go runs the
  picked job. With no project yet, Go asks for the job name
  inline and creates the project as part of the pick (this
  supersedes T113). With no dataset yet, Go offers the sample or
  a file pick, inline. The tree stays as the library. The model
  pick, the job pick, and Go all sit above the fold at 1100x680.
- T16 — settings leave every screen. The settings form is gone
  from the Project window (name, dataset, notes stay), the
  settings line is gone from the session summary, the Training
  defaults block is gone from Settings, and the chat template,
  the chat greeting, and the How to Use topics stop naming
  settings. Stored settings still exist in the model for
  compatibility; nothing in the UI reads or writes them. The
  chat agent's set_project_settings tool is removed outright —
  a model-facing settings path would still be the user touching
  settings through the chat, which the Brief forbids.
- T17 — first-run setup checklist: on first launch the main
  screen shows three steps (1. Pick a model. 2. Get its weights.
  3. Run a tiny first training, a real 20-example run) instead
  of a disabled wall. Each step is a button that does the step;
  a finished step ticks. Dismissible, never reappears as a modal,
  and a running job always shows the main screen instead.
- T18 — the model picker is a list now: each row shows one plain
  line for what the model does plus a fit verdict (Fits this PC,
  Too big for this PC, or honestly unknown) from the backend's
  PC measurement. Details (size plus RAM numbers) appear on tap,
  not up front. Nothing is selected by default; Enter with no
  pick does nothing.
- T19 — a real menu bar (File, View, Help) replaces the Menu
  button. Actions that need a selection (New project, Export
  project, Profiles, Projects) are disabled until one exists,
  instead of opening a "pick one first" modal.
- T20 — live training graphs and stats: a loss curve drawn on
  new points only, plus speed (steps a minute), RAM used, time
  left, and epoch, in the glanceable card under the hero. The
  last run's curve is rebuilt from the project's run log, so it
  is still there after the run finishes.

## v0.10.0 — 2026-11-13

The finish list, second slice: the RAM guards estimate before
loading anything, the training loop is reproducible and honestly
capped, and the destructive paths (re-train, re-export) ask or
refuse instead of silently destroying finished work.

- T28 — the RAM guard estimates from the model's config + weight
  sizes (`load_model_metadata`, `estimate_training_from_metadata`)
  before loading anything; a run that will not fit is refused
  before the base is anywhere near memory. A second guard with
  the real param counts still runs after the load.
- T31 — merge RAM guard (`estimate_merge_bytes`, `check_merge_fit`
  in `gguf.py`): base + merged copy + headroom, refused before
  loading when it does not fit. The converter warning
  (`merge_warnings`, `on_warning`) tells the user to close other
  apps when merge + converter together pass the ceiling.
- T32 — seed everything: `torch.manual_seed` at fresh-run start
  (before the LoRA init), and the torch RNG state saved in every
  checkpoint and restored on resume. Same seed, same adapter;
  pause/resume is bit-identical to an uninterrupted run. Old
  checkpoints without RNG state still resume.
- T56 — `--steps` is a real cap: `run_training_loop` takes a
  remaining-steps budget, breaks mid-epoch at the cap, and
  reaching the cap is completion (adapter saved, status trained),
  not a pause. 0/negative refused in argparse and in the engine.
  The old epochs-shrink hack is gone.
- T25 — re-training a trained project refuses ("already trained.
  Use --force to re-train it") and leaves the adapter untouched;
  `--force` re-trains deliberately. `--resume` on a trained
  project announces the extension and the new total first (the
  `extending` event, printed by the CLI and the GUI). The GUI
  asks before re-training. Sleep is never blocked (it runs with
  `update_status=False`).
- T24 — GGUF export refuses to overwrite an existing GGUF (the
  REFUSE pick, checked before the merge); `--force` on
  `export-gguf` overwrites deliberately. Never deletes a previous
  export silently.
- T26 — `export_gguf` checks llama.cpp before the merge; a failed
  export removes the half-finished merged dir and the F16
  intermediate and says so in the error.
- T27 — the GGUF path validates `--quant` up front with the
  existing `requant.validate_quant` (no second validator): a
  bogus quant fails in a millisecond, before the merge.
- T102 — `find_llama_cpp` requires an executable quantizer; a
  non-executable file is refused naming the file and the
  `chmod +x` fix.
- T99 — completions are bound to `max_seq_len` (head + EOS kept,
  `truncated` flag); the loop warns with the count of cut
  examples, shown by the CLI, the GUI, and sleep.
- T2 — dirty tracking in the Profile and Project windows:
  snapshot-based `is_modified`, title asterisk, Save/Discard/
  Cancel on close and on rename, notes-only save.
- T3 — damaged manifests are rows, not silent skips: greyed +
  italic in the GUI tree (click = status message, double-click
  opens the manifest for repair), `(damaged: ...)` rows in the
  CLI lists, skipped by session restore and rename.
- T8 — Start training checks the open Project window's unsaved
  edits first (Save/Discard/Cancel); a bad learning rate sitting
  unsaved stops the start instead of training on stale settings.
- T10 — the refusal probe loads one base at a time (before run,
  free, after run) instead of holding both in memory.
- T12 — soft tag validation: creating a profile (or saving one)
  with an Ollama tag that is not installed locally warns and
  asks, default No. An empty tag or an unanswered Ollama never
  warns.
- T13 — the live training log keeps its in-memory lines when the
  panel refreshes; JSONL re-renders as friendly
  `step N/total loss x.xxxx` lines on project switch.
- T22 — checkpoint resume loads `optimizer.pt` with
  `weights_only=True`; a malicious pickle is refused, never
  executed.
- T33 — every dataset split keeps at least one validation row
  (n=2 is 1 train + 1 val, as `load_dataset` promises).
- T35 — the CLI closing line says "GB RAM (estimated)", not
  "GB RAM used": the figure is the pre-run estimate, not a
  measurement.
- T142 — tests for the risky CLI paths: unknown/no command (exit
  2 + usage), `--steps` 0/negative, `--quant BOGUS`, corrupt-home
  lists, resume-on-trained announcement, `--force` plumbing,
  converter-warning print.

## v0.9.0 — 2026-11-13

Auto-config backend plus the P0 foundations from the finish list.
The backend now measures the PC and picks the training settings,
so the user never has to; the trust boundary (import/export) is
strict and atomic; and the model, the CLI, and the engine all
validate settings the same way.

- Auto-config (new `stella/autoconfig.py`, Qt-free, stdlib only):
  `measure_pc()` reads CPU count + model, RAM total/available,
  free disk on the Stella home filesystem, and load; 
  `compute_settings()` picks the recipe by documented conservative
  rules — batch size always 1 on CPU; rank 8, learning rate 2e-4,
  3 epochs, max sequence length 1024; rank 4 and seq 512 when less
  than 4 GB of RAM is available. New projects get the computed
  settings with `settings_source="auto"`; training re-measures at
  run start for auto projects and stores the fresh values. Anything
  a human set (Project window, chat, import) is `"manual"` and is
  never recomputed. New command: `stella pc-info` prints the
  measurement and the picked settings in plain words.
- T37 — one defensive metamorph reader (`metamorph_mode` in the
  model layer): a missing, null, or wrong-type block yields the
  default mode instead of a crash. `get_project` defaults the
  block; `update_project` reads through the reader.
- T38 — export reads metamorph through the reader and builds the
  whole package in a staging dir, moved into place only when every
  file is written: no crash on `metamorph: null`, no partial
  package on failure.
- T39 — a string-metamorph project shows a warning row in the GUI
  tree and a warning line in the CLI project list, via the reader.
- T1 — trust-boundary import: strict manifest schema in
  `verify_export` (types for settings, config, dependencies,
  status, metamorph mode); slugs normalized once at import start,
  so returned names match stored names; import is atomic
  (settings validated before anything is created, plus rollback of
  anything created on a late failure); the GUI import handler gets
  a last-resort catch and refreshes the lists on failure. No format
  versioning here — that stays T40's.
- T4 — the train command's Ctrl+C handler no longer prints from
  inside the signal handler (the pause message already comes from
  the `paused` event), matching the sleep handler. Subprocess
  Ctrl+C-pause test: pause, checkpoint saved, exit 0.
- T5 — `main()` catches everything: one clean `stella:` line, exit
  1, no raw traceback on the default path. `profiles` reads
  defensively (a nameless manifest degrades to a warning line).
  HF load failures in `load_base_model` are wrapped as StellaError
  naming the repo/path and the likely cause.
- T6 — settings validated in the model (`validate_settings`,
  ranges matching the chat's table, now the single table both use):
  bad rank/epochs/batch/learning rate/seq len, unknown keys, and a
  bad method are all refused with the key named. `_write_json`
  refuses NaN/inf. The engine re-checks every numeric setting it
  reads (`validate_run_settings` at the top of `train_project` and
  `run_training_loop`) instead of bare int()/float().
- T21 — the Project window fills defensively: a bad stored value
  falls back to the default with a "stored value was invalid" note,
  the fill never aborts mid-way, and Save can never write another
  project's values back.
- Pinning tests (no behavior change): T44 geometry (Start training
  + progress bar inside the 1100x680 viewport), T71 (no metamorph
  promise text in any visible GUI string), T123 (no-project session
  summary holds no settings values; no project window opens with no
  selection), T162 (a second launch against a live first instance
  exits 0 with no second window).

## v0.8.0 — 2026-11-13

This completes the stopped v0.5 scope (re-quantize + distill),
shipping as v0.8.0 because v0.6 and v0.7 shipped in between. The
new work is engine, command line, and Chat tools, plus one window
change: the MetaMorphAi control is gone from the Project window.
It did nothing (training ignored it), so it gets no control. The
stored mode stays in project files for compatibility, and saving
a project leaves it untouched.

- Re-quantize (new `stella/requant.py`, `stella-cli requant <tag>`):
  take an installed Ollama model and make a smaller copy at a
  smaller quant (default Q4_K_M). Stella finds the model's GGUF
  file from Ollama's own manifests (with `ollama show --modelfile`
  as the fallback), checks llama-quantize and Ollama exist, checks
  free disk before writing, quantizes, and registers the copy as a
  new tag with `ollama create`. The original model is never
  touched, and the new tag must not already exist. Bogus quant
  names are rejected up front, never passed to the tool.
- Distillation (new `stella/distill.py`, `stella-cli distill
  <profile> <project> --teacher <tag> --prompts <file>`): a teacher
  model in Ollama answers a list of prompts, one per line, and its
  answers become the project's dataset (distilled.jsonl, prompt /
  completion rows, validated like any dataset). Empty answers are
  skipped and counted, identical pairs are kept once, and a re-run
  skips prompts already answered. Training is not started: the
  user looks at the dataset first, then runs `stella train`.
- Ollama client gains `generate()` (one /api/generate call, plain
  words on failure) and `reachable()`; distill uses both.
- Chat gains two tools: `distill` and `requant`, so the Chat can
  run both jobs for you. The training template is unchanged: the
  full template rework is a later version.
- How to Use gains two topics: "Making a model smaller" and
  "Teaching a small model", honest about the limits: re-quantizing
  an already-quantized model loses a little quality, and neither
  feature removes capabilities from the original model. They make
  a new smaller one.

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
