# STELLA Audit #4 — GUI: Task List

**Source:** [audit-04-gui-2026-11-12.md](audit-04-gui-2026-11-12.md)
(GUI audit, 2026-11-12, against v0.2 / commit 9a821e07 — the first
audit run against v0.2, so it covers the main window **and** the
Train panel).

**This file is a list only.** Nothing here has been fixed or built.
Each task turns one or more audit findings into work with a verifiable
"done". Priorities follow the audit's section 7; within a priority,
a fix comes before the polish that depends on it.

**Priority key:** P0 = data loss / silent failure, fix first.
P1 = real functional defect or daily friction. P2 = missing capability
or inconsistency. P3 = polish, display, and scale.

**Effort key:** S = a focused change in one or two files, a day or
less. M = a change across model + GUI + tests, or a small design
decision plus implementation. L = a multi-part build or a design that
needs Joshua's direction on scope first.

**Counts:** 25 tasks — 5 P0, 11 P1, 7 P2, 2 P3.

**Shared fixes with audits #1, #2, and #3:** several findings
re-verify earlier findings and share their fix — they are built
once, not twice. Dirty tracking (W5/D5 — with Projects W1/D1,
audit #2 T1); Ollama cache (W7/D7 — with Profiles W4/D5, audit #1
T3); import failure in the window (W8/D8 — the root fix is the
trust boundary, audit #3 T1; this file's T8 is the window face);
status discipline (U3/D18 — with Export/Import U1/D14, audit #3
T13); tooltips (U1/D16 — with Profiles U1/D10, audit #1 T9; U7 —
with Projects U7, audit #2 T16); status + health display (G5/G6/D22
— with Projects D5 / Profiles D1, audit #2 T5 / audit #1 T13);
checkpoint actions (G3 — with Projects W15/G3, audit #2 T18). In
this standalone file they appear as GUI tasks; the merged list
([stella-audit-task-list-123.md](stella-audit-task-list-123.md))
folds them into the single shared tasks. The dialog (W1/D1) is the
exception: audit #1 listed it as one item inside its small-UI-fixes
task, but audit #4 raises it to P0, so it is split out into its own
P0 task here and in the merged list. Audit #4 also CORRECTED audit
#1's U3 (the dialog is not a separate window at all — see T1);
audit #1's report has been corrected in place.

---

## P0 — fix first

### T1 — Make New Profile a real QDialog

- **Covers:** W1, D1
- **Effort:** M
- **Problem:** `NewProfileDialog` is a plain `QWidget` with a
  parent and no `Qt.Window` flag (`gui.py:62`). Probed on the
  real path (`win.new_profile()`): `isWindow()` is False and its
  geometry is (0, 0, 420, 320) **in parent coordinates** — it
  renders as a frameless, background-less form smeared over the
  top-left of the main window, its labels overlapping the header
  and both lists (screenshot eyeballed). The `WindowModal` flag
  (`gui.py:598`) does nothing on a non-window: probed, the
  profile selection changed behind the open "dialog". Enter does
  nothing (no default button), Escape does nothing, it is not
  centered, and two can be opened at once, stacked on top of each
  other. The primary creation flow in the program is visually
  broken and behaves like nothing else in the window. (This
  corrects audit #1's U3, which called it "a separate 420x320
  window" — wrong; audit #1's report has been corrected.)
- **Fix:** D1 — make it a real `QDialog`: modal, centered on the
  parent, Create as the default button (Enter works), Escape
  closes, one instance at a time. The test concern in the
  docstring is real — drive it with `QTest` + a timer, the way
  the audit drove the modal dialogs — but a test convenience must
  not ship as a broken dialog.
- **Done:** The dialog opens centered on the main window with
  dialog framing; pressing Enter creates the profile; Escape
  closes it; opening it twice yields one dialog; the profile
  selection cannot change behind it. Tests: dialog type, modality
  (selection blocked behind it), Enter submits, Escape closes,
  singleton.

### T2 — Gate Start training and sample-dataset on save success

- **Covers:** W2, D2
- **Effort:** S
- **Problem:** `start_training` calls `self.save_project()`
  (`gui.py:823`) and never checks whether it worked. Probed: with
  learning rate `abc`, the warning dialog appeared **and the
  training worker started anyway** — training on the stale
  on-disk settings while the user just saw an error about the
  settings they meant to use. The same unchecked save sits in
  `use_sample_dataset` (`gui.py:795`): with a bad LR the warning
  appeared and the log still claimed "Save is done" — and with no
  project selected at all, the same "Save is done" line is logged
  although nothing was saved.
- **Fix:** D2 — have `save_project` return whether it saved, and
  refuse to start training — or to claim "Save is done" — when it
  did not. A failed save must stop the action that depends on it.
  With no project selected, sample-dataset does nothing (or warns)
  instead of logging a save that never happened.
- **Done:** Bad learning rate → warning dialog, no worker starts,
  no training on stale settings. Sample dataset with a bad LR →
  no "Save is done" in the log. Sample dataset with no project
  selected → nothing logged as saved. Tests: bad-LR start refused,
  sample-dataset save claim gated, no-selection case.

### T3 — Keep the live training log

- **Covers:** W3, D3
- **Effort:** S
- **Problem:** `_on_train_finished` (`gui.py:850`) appends
  "Trained N steps." to the log, then calls
  `refresh_train_panel` (`gui.py:759`), which overwrites the log
  widget from `train_log.jsonl` on disk. Probed: after a fake run
  finished, the log was **empty** — the whole run record, finish
  message included, erased. With a real run the file exists, so
  instead of a blank log the user gets the raw JSONL records
  (`{"epoch": 1, "loss": ..., "lr": ..., "step": ..., "type":
  "step"}`) in place of the friendly "step 3/4 loss 2.1000"
  lines they watched during the run (the widget shows the file's
  last 30 lines verbatim). Either way the readable run record is
  gone the moment the run ends.
- **Fix:** D3 — do not let the finish refresh overwrite the log
  the user watched: keep the in-memory lines, and when reloading
  from `train_log.jsonl`, render the JSON records as the same
  friendly "step N/total loss x.xxxx" lines instead of raw JSON.
- **Done:** After a run finishes, the log still shows the run's
  lines plus "Trained N steps."; reopening a trained project
  shows friendly lines, never raw JSON records; a run with no log
  file still shows its in-memory lines. Tests: log survives the
  finish refresh, JSONL renders as friendly lines.

### T4 — Delete confirms default to No

- **Covers:** W4, D4
- **Effort:** S
- **Problem:** Probed with the real `QMessageBox.question` call
  and a timer driving the modal loop: focus lands on the **Yes**
  button and pressing Enter returns Yes. The dialog's own text
  says the delete "cannot be undone" — and delete is
  unrecoverable (audit #1 W5, audit #2 W8: one dialog, then
  `rmtree`). A single Enter keypress, the key every other dialog
  in the program trains the user to press to accept, destroys a
  profile and all its projects, or a project and its checkpoints.
- **Fix:** D4 — make No the default button so Enter never deletes.
  Pair with the trash from audit #1 (D6) so a confirmed delete is
  still recoverable.
- **Done:** In the delete confirm, Enter does not delete; Yes must
  be clicked (or arrowed to) explicitly. Tests: timer-driven modal
  test asserting Enter returns No, on both the profile and the
  project delete.

### T5 — Dirty tracking, or auto-save on switch

- **Covers:** W5, D5
- **Effort:** M
- **Problem:** Audit #2's W1, re-verified in v0.2: typed notes and
  a changed display name, switched projects and back — notes
  reverted to the saved text, display name reverted to the slug.
  There is still no dirty tracking, no asterisk, no prompt, no
  auto-save, in either detail panel. The completion path adds a
  second trigger: `_on_train_finished` refreshes the projects,
  which reloads the detail from disk and discards any edits the
  user made during the run. One fix must cover both panels.
  (Shared with audit #2, D1 / T1 — this file's task is the GUI
  audit's record of it; the merged list folds both into the
  single dirty-tracking task.)
- **Fix:** D5 — mark edited fields, prompt on leaving with unsaved
  edits, or save on switch — covering both detail panels and the
  completion refresh. Pick one behavior and apply it identically
  to both panels; do not prompt when nothing changed.
- **Done:** Edit project notes, switch projects, switch back: the
  edits are preserved (auto-save) or a prompt appeared and the
  choice was honored. Same for a profile role edit across a
  profile switch. Edits made during a training run survive the
  run finishing. No prompt appears when nothing was edited.
  Tests: GUI tests for the switch-with-edits path on both panels,
  the completion-refresh path, and the no-prompt-when-clean path.

---

## P1 — functional defects and daily friction

### T6 — Fill the detail panel defensively

- **Covers:** W6, D6
- **Effort:** S
- **Problem:** `_show_project_detail` converts settings with bare
  `int(...)` (`gui.py:529-533`) and no guard. Probed: a project
  whose `project.json` says `rank: "high"` — selecting it raised
  `ValueError` out of the signal handler (traceback printed to
  stderr by Qt) and left the panel **mixed**: display name and
  dataset showed the new project, while learning rate, epochs,
  batch, seq len, metamorph, and notes still showed the previous
  project's values. The user now sees one project's settings
  labeled as another's — and clicking Save writes the mixed form
  back to disk, corrupting the project with the other project's
  values (`save_project` reads the form unconditionally,
  `gui.py:560`). The home is meant to be hand-editable, so a
  mistyped value in the JSON turns a selection click into a
  corruption vector. (Model validation — audit #2's T2 —
  prevents *new* bad values from being saved; this task handles
  the bad values already on disk, hand-edited before validation
  lands.)
- **Fix:** D6 — a setting of the wrong type falls back to its
  default (and the panel says so) instead of aborting the fill
  mid-way. Never let a read error become a mixed panel, and never
  let a mixed panel be saved.
- **Done:** Select a project with `rank: "high"`: the panel fills
  completely with the default rank and a visible note that the
  stored value was invalid; no traceback; no other project's
  values anywhere in the panel; Save does not write the other
  project's values. Tests: bad-type fill for each setting, mixed
  panel impossible, save-after-bad-fill writes only this
  project's values.

### T7 — Cache the model list; fetch off the UI thread

- **Covers:** W7, D7
- **Effort:** M
- **Problem:** Audit #1's W4, unchanged in v0.2.
  `_show_profile_detail` calls `list_models()` synchronously on
  every selection (`gui.py:483`), with no cache. Probed against a
  counting fake server: 2 selections = 2 fetches; with a 1.2-second
  server delay, a selection click blocked for 1.39 seconds. The
  New Profile dialog fetches again on construct (`gui.py:78`). On
  a swapping 8 GB box with a slow Ollama startup, clicks can feel
  dead for up to the 2-second timeout. (Shared with audit #1,
  D5 / T3 — this file's task is the GUI audit's record of it;
  the merged list folds both into the single Ollama-cache task.)
- **Fix:** D7 — fetch once at startup, refresh on demand, never
  block a click on the network. Serve every selection change and
  every combo fill from the cache; move the fetch to a background
  thread so a hung Ollama never blocks a click.
- **Done:** Against a counting fake Ollama server: 1 fetch at
  startup, 0 fetches across any number of profile selection
  changes, 1 fetch on explicit Refresh. With Ollama hung, profile
  clicks still respond immediately and the stored tag stays
  visible. Tests: fetch-count test, hung-Ollama responsiveness
  test, refresh-button test.

### T8 — Handle import failure in the window

- **Covers:** W8, D8
- **Effort:** S
- **Problem:** Audit #3's W2, re-verified in v0.2: importing a
  package whose `settings` is a string raised a raw `ValueError`
  out of `import_package` (`gui.py:734`, which catches only
  `StellaError`) — **no warning dialog appeared at all**, and the
  orphan empty profile the failed import left on disk was
  invisible in the list (refresh runs only on the success path).
  The window's face of the trust-boundary crash is total silence.
  (The root fix is audit #3's D2/D3 — validate the manifest, make
  import atomic — audit #3 T1. This task is the window side.)
- **Fix:** D8 — catch broadly in `import_package`, refresh the
  lists on failure so an orphan is visible, and say what
  happened.
- **Done:** A bad import shows a warning dialog naming the
  problem, and the lists refresh so the window matches the disk —
  an orphan left by the failure is visible (until atomic import
  lands, when a failed import leaves no orphan at all). Tests:
  bad-import dialog shown, lists refreshed on failure.

### T9 — One job at a time

- **Covers:** W9, D9
- **Effort:** M
- **Problem:** Probed with slow fake jobs: starting the refusal
  probe while a GGUF export was running started a second
  `JobWorker` alongside the first — and starting a GGUF export
  while training was running started it too. Each start overwrites
  `self._job_worker`, so the first job is orphaned from the
  window's handle (its finish signal still fires, but nothing
  tracks it). On 8 GB, a probe loading a model while a training
  run holds its weights is a real OOM shape, and the window does
  nothing to prevent it.
- **Fix:** D9 — a single running-job slot: GGUF export and the
  probe disable each other and disable during training, with the
  status bar saying what is running.
- **Done:** Starting a second job while one runs is refused (or
  the button is disabled) with a message naming the running job;
  starting a job during training is refused the same way; no job
  is ever orphaned from the window's handle. Tests: probe-during-
  export refused, export-during-training refused, status names
  the running job.

### T10 — Close waits for every worker, without freezing

- **Covers:** W10, D10
- **Effort:** M
- **Problem:** `closeEvent` (`gui.py:916-919`) waits for the
  *train* worker only. Probed in a separate process: closing the
  window during a GGUF export returned in 0.05s and Qt printed
  `QThread: Destroyed while thread '' is still running` — the
  worker was destroyed mid-flight, which Qt documents as a
  programming error that can crash. Closing during a training run
  whose worker ignores the stop request froze the UI for the full
  15.07-second wait and then printed the same destroyed-thread
  warning anyway. The 15-second freeze has no feedback at all:
  the window just stops responding to a close click.
- **Fix:** D10 — wait for the job worker too; show "Stopping
  training…" and close when the thread ends instead of blocking
  the UI thread for 15 seconds; never destroy a running thread.
- **Done:** Closing during a job waits (with visible feedback)
  and closes cleanly with no destroyed-thread warning on stderr;
  closing during training shows progress and closes when the
  worker ends instead of freezing the UI. Tests: close-during-job
  in a subprocess (no warning), close-during-training feedback
  shown.

### T11 — Reset progress/loss per project; pin the panel to the running project

- **Covers:** W11, W12, D11
- **Effort:** M
- **Problem:** `refresh_train_panel` never touches the progress
  bar or the loss label (except setting "Pick a project to
  train." when nothing is selected). Probed: after a run on
  `tool-calls`, switching to `short-replies` — never trained —
  still showed the run's progress and loss. The Train-panel
  screenshot shows the contradiction at its worst: a **25%
  progress bar** above the text "Pick a project to train." with
  no project selected at all. And switching projects mid-run
  mixes the panels: the checkpoint list rebuilt to the new
  project's (empty) list while the progress bar and loss label
  kept showing the running project's values. The early return
  ("never wipe the live log mid-run") protects the log but not
  the rest of the panel, so mid-run the Train panel is half one
  project, half another.
- **Fix:** D11 — selecting a project resets the bar and label to
  that project's state, and while a run is live the Train panel
  follows the running project (or says which project is running)
  instead of mixing panels.
- **Done:** Switch projects after a run: the bar and label reset
  to the new project's state (empty for an untrained project).
  With no project selected, the bar is empty and the label says
  so. Mid-run, switching projects leaves the panel showing the
  running project consistently (or naming it). Tests: progress
  reset on switch, no-selection state, mid-run switch consistency.

### T12 — Lock the settings during a run

- **Covers:** W13, D12
- **Effort:** S
- **Problem:** Probed: mid-run, the rank spinbox accepted 16 and
  Save wrote it to disk. The running worker already loaded its
  config, so the saved settings no longer describe the run in
  progress — and the next run will use settings the user set
  while watching the previous one. Combined with W5, edits made
  during a run that are *not* saved are discarded by the
  completion refresh.
- **Fix:** D12 — disable the project form and Save while training
  runs — or warn that a mid-run save does not affect the running
  config. The form should not offer to change a run in progress.
- **Done:** During a run the settings form is disabled (or a save
  attempt warns that it does not affect the running config); no
  setting can silently change under a run in progress. Tests:
  form disabled mid-run, save warned or refused mid-run.

### T13 — Tooltips where the text is cut or the meaning is not obvious

- **Covers:** U1, U7, D16
- **Effort:** S
- **Problem:** (U1) Audit #1's U1, unchanged in v0.2: the
  MiniCPM5 row is 343px of text in a 250px pane, and the item has
  no tooltip — the 1100x680 screenshot shows
  `MiniCPM5 Driver [driver] — maternion/min...`, with a
  horizontal scrollbar as the only escape. Hovering tells you
  nothing. (U7) One tooltip in the entire window: exactly one
  widget has a tooltip — the metamorph combo. Rank, learning rate,
  epochs, batch, seq len, the dataset field, and every button have
  no explanation of what they do or what sane values look like
  (audit #2's U7, unchanged). (Shared: the row part with audit #1,
  D10 / T9; the settings part with audit #2, U7 / T16. The merged
  list splits D16 across the small-UI-fixes task and the settings-
  tooltips task.)
- **Fix:** D16 — row tooltips with the full label; help text on
  rank, learning rate, epochs, batch, and seq len with sane
  ranges.
- **Done:** Hovering a truncated row shows the full display name,
  role, and tag; every settings field has a tooltip naming its
  purpose and sane values. Tests: tooltip text present on rows and
  on each settings field.

### T14 — Put the Train panel above the fold

- **Covers:** U2, D17
- **Effort:** M
- **Problem:** Audit #2's U2, worse in v0.2. Probed geometry at
  1100x680: detail content is 1289px tall in a 567px viewport;
  the Notes editor starts at y=578, `Start training` at y=758,
  the progress bar at y=789, the Training log at y=996. Only the
  "Notes" header peeks out at the bottom of the default window
  (screenshot). The primary action of the v0.2 release — Start
  training — needs a scroll on every visit. (Coordinate with the
  Notes repositioning, audit #2 T16 — both tasks reshape the same
  detail panel, so the layout change should solve Notes and Train
  placement in one pass.)
- **Fix:** D17 — move Train above Notes, or give the detail pane a
  Train tab, or make the sections collapsible — the release's
  headline action should not need a scroll on every visit.
- **Done:** A screenshot at 1100x680 shows Start training (and the
  progress bar) without scrolling. Tests: geometry assertion that
  Start training is inside the viewport at default size.

### T15 — Status discipline: confirm after the refresh

- **Covers:** U3, D18
- **Effort:** S
- **Problem:** Audit #3's U1, re-verified: after a successful
  import the status bar reads "Profile: … — project: …" — the
  "Imported …" message never survives its own refresh. Training
  has the same shape: `_on_train_finished` says "Trained N
  steps." and then `refresh_projects` overwrites it with the
  selection message. Export gets a dialog; import and
  training-done get messages that erase themselves. (Shared with
  audit #3, D14 / T13 — this file's task is the GUI audit's
  record of it, with the training-done case added; the merged
  list folds both into the single confirmation task.)
- **Fix:** D18 — say the confirmation *after* any refresh it
  triggers, or give import and training-done the same success
  dialog export already has. A confirmation the window erases
  itself is not a confirmation.
- **Done:** After an import, the status bar (or a dialog) still
  shows the import confirmation; after a training run finishes,
  "Trained N steps." is still visible; the refresh no longer
  overwrites either. Tests: GUI tests asserting both
  confirmations survive their refreshes.

### T16 — Put the missing-deps hint where the user can see it

- **Covers:** U8, D25
- **Effort:** S
- **Problem:** Start-without-deps writes the install hint to the
  Training log — which sits at y=996, below the fold. The status
  bar says "see the Train log", but the user has to know to scroll
  for it; on first run, the most likely first-run failure hides
  its own fix.
- **Fix:** D25 — a warning dialog, or auto-scroll the detail pane
  to the log when the hint is written — not a status line pointing
  at a below-fold log.
- **Done:** On a first run without the training deps installed,
  the hint is visible without hunting (dialog, or the detail pane
  scrolled to the log). Tests: hint visible after a deps-missing
  start.

---

## P2 — missing capabilities and inconsistencies

### T17 — Clear the whole panel with no selection

- **Covers:** W14, D13
- **Effort:** S
- **Problem:** The no-project branch of `_show_project_detail`
  (`gui.py:506`) clears the text fields and notes but leaves the
  spinboxes, the method combo, and the metamorph combo showing
  values. Visible in the 1100x680 screenshot: with
  `empty-profile` selected (no projects), the panel shows Method
  `lora`, rank 8, epochs 3, batch 1, seq 1024 — settings for a
  project that does not exist — while Learning rate sits empty
  (it was cleared). `Save project` stays enabled and clicking it
  silently does nothing. The panel state does not reflect the
  selection state.
- **Fix:** D13 — the no-project branch should reset spinboxes,
  combos, and method to blank/default and disable Save, so the
  panel never shows settings for a project that is not there.
- **Done:** With a profile selected but no project, the panel
  shows no settings values and Save is disabled. Tests:
  no-selection panel state, Save disabled.

### T18 — Give the splitter honest minimums

- **Covers:** W15, W16, D14
- **Effort:** S
- **Problem:** `splitter.setSizes([260, 200, 640])` (`gui.py:270`)
  produced `[270, 273, 531]`: the middle pane cannot be 200px
  wide because its three buttons need ~273px, so the detail pane
  loses ~110px to the button rows. At minimum window size the
  detail pane shrinks to ~331px. The layout's numbers are
  aspirational; the button rows set the real floor. And both list
  panes can be dragged away entirely: `setSizes([0, 0, 1100])`
  collapsed both the profile and project panes to width 0.
  `childrenCollapsible` defaults to true, so a stray drag can
  lose both lists with no obvious restore — the handles are still
  there, but a user who has never seen a collapsed splitter has
  no reason to know that.
- **Fix:** D14 — set minimum widths on the panes (or drop the
  unachievable 200px request) and set `childrenCollapsible` to
  false, so a drag cannot lose a pane.
- **Done:** The panes cannot be dragged to width 0; the requested
  splitter sizes are achievable and honored (within a few pixels);
  the detail pane keeps its width at default and minimum size.
  Tests: drag-to-zero refused, sizes honored.

### T19 — Remember the project per profile

- **Covers:** W17, D15
- **Effort:** S
- **Problem:** `_on_profile_selected` resets `_current_project`
  to None (`gui.py:467-473`), so returning to a profile always
  lands on its first project. Probed (corrected): select
  `tool-calls`, switch profiles, switch back — the window shows
  `short-replies` (row 0), not the project the user was working
  on. The first probe passed by coincidence (row 0 happened to be
  the project under test); the corrected probe confirms there is
  no memory.
- **Fix:** D15 — keep the last selected project for each profile
  and restore it on return, instead of always landing on row 0.
- **Done:** Select a non-first project, switch profiles, switch
  back: the same project is selected. Tests: project memory
  across a profile round-trip.

### T20 — Buttons follow the selection; panes explain themselves

- **Covers:** U4, U5, D19
- **Effort:** M
- **Problem:** With an empty store, every action button is
  enabled: Start, Resume, Export GGUF, Run refusal probe,
  Export, Import, Rename, Delete. Clicking Rename/Delete/Save
  with no selection does *nothing at all* — no dialog, no status
  change — while Export and New project warn. The same dead click
  teaches two different lessons depending on which button it was.
  And empty panes give no guidance: a profile with no projects
  shows a blank white list; an empty store shows two blank white
  lists. The only voice is the status bar ("Pick a profile to
  begin."). Nothing in the panes says what to do next. (The
  Export button's enablement is audit #3's T20 — implement
  consistently in the same pass.)
- **Fix:** D19 — disable actions with nothing to act on, in one
  `_update_actions` pass; put a one-line hint in an empty list
  ("No projects yet — New project to start").
- **Done:** With nothing selected, the action buttons are
  disabled; with a selection, the applicable ones enable; an
  empty list shows its hint. Tests: button states per selection
  state, hint text present in empty panes.

### T21 — Window chrome pass: icon, geometry, shortcuts

- **Covers:** U6, G1, G2, D20
- **Effort:** M
- **Problem:** Three chrome gaps. (U6) No window icon:
  `windowIcon().isNull()` is true; the title bar shows Qt's
  default icon, although the gold-star icon ships in `assets/`
  (SVG + PNGs) and the app-menu entry uses it. The running window
  does not look like Stella. (G1) No geometry or state
  persistence: no `QSettings` anywhere — window size, splitter
  positions, and the last selection are forgotten on every
  launch. The user re-arranges the window every time they open
  it. (G2) No keyboard shortcuts: no Ctrl+S to save, no Ctrl+N
  for a new profile/project, no mnemonics on any button. The
  window is mouse-only except for list arrows and Tab.
- **Fix:** D20 — set the window icon from the shipped star art;
  persist size, splitter, and last selection with `QSettings`;
  add the two shortcuts that matter (Ctrl+S save, Ctrl+N new).
- **Done:** The window shows the star icon; relaunching restores
  the size, splitter positions, and last selection; Ctrl+S saves
  the current panel and Ctrl+N opens a new profile/project.
  Tests: icon set, persistence round-trip, shortcuts fire.

### T22 — Checkpoint actions and job progress

- **Covers:** G3, G4, D21
- **Effort:** M
- **Problem:** (G3) The checkpoint list is display-only: clicking
  a checkpoint does nothing — no resume-from-checkpoint, no
  delete, no disk usage, no detail. The Train panel owns
  checkpoints now (audit #2's W15, expected in v0.1) but still
  cannot act on them. (G4) No progress or cancel for GGUF/probe
  jobs: `JobWorker` has no progress signal — a multi-minute GGUF
  export shows only log lines, and there is no way to stop it
  once started. Training has Pause; jobs have nothing. (Shared:
  the checkpoint part with audit #2, W15/G3 / T18; the merged
  list folds the checkpoint part into the checkpoint-management
  task and keeps the job part as its own task.)
- **Fix:** D21 — resume from a selected checkpoint, delete a
  checkpoint, disk usage in the list; a progress signal (or at
  least an indeterminate bar + a stop button) on `JobWorker`.
- **Done:** Selecting a checkpoint offers resume and delete; the
  list shows disk usage; a running GGUF/probe job shows progress
  and can be stopped. Tests: resume-from-checkpoint, delete,
  disk usage display, job stop.

### T23 — Show status and health

- **Covers:** G5, G6, D22
- **Effort:** M
- **Problem:** (G5) No status display anywhere: audit #2's W5/G1,
  window face — no widget shows or changes a project's status, in
  the list or the detail panel. A project that trained, failed,
  or exported looks exactly like a draft. (G6) No health
  indicator: audit #1's W11, window face — a profile pointing at
  a missing model, a profile with no tag, and a good profile are
  visually identical rows. Nothing in the window says whether the
  base exists. (Shared: the status part with audit #2, D5 / T5;
  the health part with audit #1, D1 / T13. The merged list splits
  D22 across the status-lifecycle task and the health-badge task.)
- **Fix:** D22 — a status line in the project row and detail
  panel, driven by training and export; a health badge per
  profile row from the cached model list.
- **Done:** Status is visible in the project row and detail panel
  and changes when a project trains or exports; health badges
  distinguish installed, missing, and tag-less profiles. Tests:
  status display, badge states against a fake server.

---

## P3 — polish, display, and scale

### T24 — Single-instance guard

- **Covers:** G7, D23
- **Effort:** S
- **Problem:** `main()` (`gui.py:924`) starts a window with no
  lock file or single-application check. Two Stella processes
  could open the same home and write the same manifests over each
  other.
- **Fix:** D23 — a lock file (or `QtSingleApplication`-style
  check) so a second launch raises the running window instead of
  opening a second writer on the same home.
- **Done:** Launching Stella twice raises the first window; no
  second writer on the home. Tests: second-launch detection
  (subprocess).

### T25 — Double-click does the obvious thing

- **Covers:** U9, D24
- **Effort:** S
- **Problem:** Neither list responds to a double-click: no
  double-click to rename, no double-click to open, no
  double-click on a checkpoint to see it. Every action is a
  button click away, and the most obvious gesture does nothing.
- **Fix:** D24 — rename on a list double-click; checkpoint detail
  on a checkpoint double-click.
- **Done:** Double-clicking a profile or project row opens
  rename; double-clicking a checkpoint shows its detail. Tests:
  double-click handlers fire.

---

## Coverage map

Every finding ID from the audit, and the task(s) covering it. Nothing
dropped.

| Finding | Task(s) | Notes |
|---|---|---|
| W1 — New Profile "dialog" is not a dialog at all | T1 | Real QDialog; corrects audit #1 U3 |
| W2 — Start training ignores a failed save | T2 | Gate Start on save success |
| W3 — training log wiped when a run finishes | T3 | Keep the live log |
| W4 — Enter in the delete confirm deletes | T4 | Delete defaults to No |
| W5 — unsaved edits discarded on switch | T5 | Dirty tracking / auto-save, both panels + completion refresh |
| W6 — bad settings abort the detail fill mid-way | T6 | Defensive fill, fall back to defaults |
| W7 — every profile click re-fetches Ollama | T7 | Cache + off-thread fetch (shared with audit #1) |
| W8 — bad import crashes silently in the window | T8 | Window face of the trust boundary |
| W9 — no concurrency guards on jobs | T9 | One job at a time |
| W10 — closing mid-job destroys the running thread | T10 | Close waits for all workers, no freeze |
| W11 — progress and loss are stale per project | T11 | Reset per project |
| W12 — switching projects mid-run mixes the panels | T11 | Pin the panel to the running project |
| W13 — settings editable and saveable during a run | T12 | Lock the settings during a run |
| W14 — panel shows settings with no project selected | T17 | Clear the whole panel |
| W15 — requested splitter sizes not honored | T18 | Honest minimums |
| W16 — both list panes can be dragged away | T18 | Non-collapsible panes |
| W17 — no per-profile project memory | T19 | Remember the project per profile |
| U1 — long rows truncate with no way to read them | T13 | Row tooltips |
| U2 — Notes and Train panel below the fold | T14 | Train above the fold |
| U3 — confirmations overwritten before they can be read | T15 | Status discipline |
| U4 — buttons enabled with nothing to act on | T20 | Buttons follow the selection |
| U5 — empty panes give no guidance | T20 | Empty-state hints |
| U6 — no window icon | T21 | Window chrome pass |
| U7 — one tooltip in the entire window | T13 | Settings tooltips |
| U8 — missing-deps hint goes where the user cannot see it | T16 | Visible deps hint |
| U9 — no double-click anywhere | T25 | Double-click actions |
| G1 — no geometry or state persistence | T21 | QSettings persistence |
| G2 — no keyboard shortcuts | T21 | Ctrl+S / Ctrl+N |
| G3 — checkpoint list is display-only | T22 | Checkpoint actions |
| G4 — no progress or cancel for GGUF/probe jobs | T22 | Job progress + stop |
| G5 — no status display anywhere | T23 | Status in row + detail |
| G6 — no health indicator | T23 | Health badges |
| G7 — no single-instance guard | T24 | Lock file / single-application check |
| D1 — make New Profile a real QDialog | T1 | |
| D2 — gate Start and sample-dataset on save success | T2 | |
| D3 — keep the live training log | T3 | |
| D4 — delete confirms default to No | T4 | |
| D5 — dirty tracking, or auto-save on switch | T5 | |
| D6 — fill the detail panel defensively | T6 | |
| D7 — cache the model list; fetch off the UI thread | T7 | |
| D8 — handle import failure in the window | T8 | |
| D9 — one job at a time | T9 | |
| D10 — close waits for every worker, without freezing | T10 | |
| D11 — reset progress/loss per project; pin the panel | T11 | |
| D12 — lock the settings during a run | T12 | |
| D13 — clear the whole panel with no selection | T17 | |
| D14 — give the splitter honest minimums | T18 | |
| D15 — remember the project per profile | T19 | |
| D16 — tooltips where the text is cut or unclear | T13 | |
| D17 — put the Train panel above the fold | T14 | |
| D18 — status discipline: confirm after the refresh | T15 | |
| D19 — buttons follow the selection; panes explain | T20 | |
| D20 — window chrome pass | T21 | |
| D21 — checkpoint actions and job progress | T22 | |
| D22 — show status and health | T23 | |
| D23 — single-instance guard | T24 | |
| D24 — double-click does the obvious thing | T25 | |
| D25 — put the missing-deps hint where it can be seen | T16 | |

**Coverage check:** 17 weaknesses + 9 UI flaws + 7 gaps + 25 design
suggestions = 58 findings. All 58 appear in the map above, each with
at least one task. 25 tasks total: 5 P0 (T1–T5), 11 P1 (T6–T16),
7 P2 (T17–T23), 2 P3 (T24–T25).

**Dependency order (within the priority order above):** T7 before
T23 (health badges read the cached model list); T9 before T10 (the
close handler waits on the single job slot); T5 and T12 cover the
same mid-run edits from opposite sides (T12 locks the form so there
is less to preserve; T5 preserves what was edited before the lock
— either order works, land them together if possible); T14
coordinates with audit #2's T16 (Notes placement) — one layout pass
for the detail panel. Folded into the merged list's shared tasks:
T5 (dirty tracking → merged T3), T7 (Ollama cache → merged T12),
T8 (import failure window face → merged T6), T13 (tooltips → merged
T35 + T62), T15 (status discipline → merged T30), T22 (checkpoint
part → merged T64; job part → merged T54), T23 (status + health →
merged T14 + T55). T1 is split out of audit #1's small-UI-fixes
task (merged T7) — the dialog is a P0 of its own.
