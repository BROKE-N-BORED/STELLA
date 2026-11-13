# STELLA Audit #2 — Projects: Task List

**Source:** [audit-02-projects-2026-11-12.md](audit-02-projects-2026-11-12.md)
(Projects audit, 2026-11-12, against v0.1 / commit e28db915).

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

**Counts:** 18 tasks — 3 P0, 5 P1, 6 P2, 4 P3.

**Shared fixes with audit #1:** three findings share their fix with
Profiles and are built once across both: the damaged-row fix (W4,
with Profiles W1), trash-on-delete (W8, with Profiles W5), and dirty
tracking (W1 — the fix must cover the profile detail panel too). In
this standalone file they appear as project-side tasks; the merged
list ([stella-audit-task-list.md](stella-audit-task-list.md))
combines them into single tasks.

---

## P0 — fix first

### T1 — Dirty tracking, or auto-save on switch (both detail panels)

- **Covers:** W1, U1, D1
- **Effort:** M
- **Problem:** There is no dirty tracking anywhere. Edit the notes or
  any field, click another project, and `_show_project_detail`
  reloads from disk — the edits are gone with no warning, no prompt,
  no asterisk. Probed live: typed "UNSAVED edit" into the notes and
  changed the display name, switched projects and back — notes
  reverted to the saved text, display name reverted to the slug.
  Edited fields look identical to saved ones (U1). The same flaw
  covers the profile detail panel (edit a role, switch profiles,
  lose it): the audit states one fix must cover both panels. This is
  a data-loss bug in the program's main daily action (keeping notes
  during a fine-tune).
- **Fix:** Track dirty state for both detail panels (project and
  profile). Mark edited fields (e.g. an asterisk on the Save button
  or a "modified" indicator) and, on leaving a panel with unsaved
  edits, either prompt ("Save changes to this project? Save /
  Discard / Cancel") or auto-save on switch — pick one behavior and
  apply it identically to both panels. Do not prompt when nothing
  changed.
- **Done:** Edit project notes, switch projects, switch back: the
  edits are preserved (auto-save) or a prompt appeared and the
  choice was honored. Same for a profile role edit across a profile
  switch. No prompt appears when nothing was edited. Tests: GUI
  tests for the switch-with-edits path on both panels, and for the
  no-prompt-when-clean path.

### T2 — Validate settings in the model, once, everywhere

- **Covers:** W2, D2; W7 (model part — method enum)
- **Effort:** M
- **Problem:** `update_project` merges any settings dict without
  checking a single value. Probed: rank -5, epochs 0, batch size 0,
  learning rate -0.5, max seq len 999999, and an unknown key `foo`
  were all stored without complaint — and `method="banana"` was
  stored too (W7). The GUI spinboxes constrain only the GUI path;
  the CLI, imports, and hand-edits bypass everything. Training
  (v0.2) will receive nonsense settings and fail cryptically — or
  worse, "train" for 0 epochs and report success.
- **Fix:** Validate inside `create_project` / `update_project`, so
  the GUI, CLI, imports, and hand-edits all get the same rules:
  method must be one of `lora`, `full`; rank an integer 1–64; epochs
  an integer 1–100; batch size an integer 1–32; max seq len an
  integer 128–32768; learning rate a finite number in the sane range
  (defined with T3); unknown keys rejected with a `StellaError`
  naming the key. Every rejection must say which value was wrong and
  what is accepted.
- **Done:** Each probed bad value (rank -5, epochs 0, batch 0,
  lr -0.5, seq 999999, unknown key `foo`, method `banana`) is now
  rejected with a readable message; the defaults and all valid values
  still save. The GUI, CLI, and import paths all hit the same rules
  (one bad value tested through each path). Tests for every rule plus
  unknown-key rejection.

### T3 — Learning rate as a real numeric input with a sane range

- **Covers:** W3, U3, D3
- **Effort:** S
- **Problem:** The GUI's only learning-rate check is `float(...)`,
  and `float()` accepts `"inf"`, `"-inf"`, and `"nan"`. Probed:
  saving lr=inf wrote a bare `Infinity` literal into `project.json`
  — not valid JSON for any tool except Python's lenient parser. The
  field is a bare text box with no placeholder and no range hint
  (U3), so `inf` and `-0.5` look exactly as valid as `0.0002` until
  save — and `inf` passes save.
- **Fix:** Replace the free-text learning rate with a validated
  numeric input (a `QDoubleSpinBox` with range 1e-5–1e-2 and enough
  decimals, or a validated line edit) that rejects inf, nan,
  negative, and zero values with the existing friendly error style,
  and shows a range hint ("0.0001 – 0.01, typical 0.0002"). The
  accepted range must match the model rules from T2. Also guard the
  write layer: `_write_json` must refuse non-finite floats
  (`json.dumps(..., allow_nan=False)`) so an `Infinity` literal can
  never be written into any manifest again. Existing manifests that
  already contain `Infinity` still load (Python is lenient) and
  re-save clean once the value is corrected.
- **Done:** Typing `inf`, `nan`, `-0.5`, or `0` as the learning rate
  is refused with a readable error; `0.0002` saves. A direct write
  of a non-finite value is refused at the JSON layer instead of
  producing an `Infinity` literal. The range hint is visible in the
  UI. Tests: GUI refusal cases, write-layer guard, re-save of a
  legacy `Infinity` manifest.

---

## P1 — functional defects and daily friction

### T4 — Damaged-row for corrupt project manifests

- **Covers:** W4, D4
- **Effort:** M
- **Problem:** Same pattern as Profiles W1: `list_projects` swallows
  a parse error and skips the row. Probed: corrupting
  `second/project.json` removed the project from the list with no
  warning, while a direct `get_project` still raises a clear "not
  valid JSON" error. The project, its settings, its notes, and (from
  v0.2) its checkpoints become invisible in the GUI and CLI.
- **Fix:** Surface a broken project manifest instead of skipping it:
  a greyed "damaged" row in the project list showing the project slug
  and the parse error, plus a Repair action that opens the JSON in
  the text editor. Keep the project's folder untouched; the data is
  still on disk and the UI must say so. Build this together with the
  Profiles damaged-row fix (audit #1, T1) as one fix across both
  list functions — the merged list combines them into a single task.
- **Done:** Corrupt a `project.json` by hand, open Stella: the
  project appears as a greyed row with the error text; Repair opens
  the file; fixing the JSON by hand and refreshing restores the
  normal row. Tests: a corrupt manifest is reported (not skipped) by
  the list path, and the GUI shows the damaged row.

### T5 — A real status lifecycle, with UI

- **Covers:** W5, U4, G1, D5
- **Effort:** M
- **Problem:** `status` is free text with no lifecycle and no UI.
  Every project is born `draft` and stays `draft` forever — nothing
  transitions it through training, done, failed, or exported, and
  nothing can: the detail panel has no status control (probed: no
  `proj_status` widget exists), the list shows no status (U4), and
  the model accepts any string (probed: `status="banana"` stored
  fine). An exported project still says `draft`. There is no record
  that a project trained, failed, or finished (G1).
- **Fix:** Make status a validated enum — `draft`, `ready`,
  `training`, `done`, `failed`, `exported` — enforced in the model
  (anything else rejected). Show it in the detail panel (read-only
  label, plus the user-driven transition: draft → ready) and in the
  project list row. Drive the other transitions from actions, not
  free text: training/done/failed from the training engine (Item 3
  wires its transitions into this enum when it lands), exported from
  the export action. Record a timestamp with each transition.
- **Done:** Status is visible in the detail panel and the list row;
  an invalid status string is rejected by the model; exporting a
  project flips it to `exported`; a project can move draft → ready
  from the UI. Training transitions are defined (even though Item 3
  wires them later) and documented. Tests: enum rejection, export
  transition, draft → ready, status shown in both surfaces.

### T6 — Dataset picker + validation

- **Covers:** W6, U5, G2, D6
- **Effort:** M
- **Problem:** Probed: `dataset_ref="/no/such/place/data.jsonl"` is
  accepted at creation with no complaint. No existence check, no
  format check, no example count, no preview. A mistyped path or a
  wrong-format file fails at train time, not at configure time — the
  most expensive moment to discover it. The field is a bare text box
  with no file picker (U5): paths must be typed by hand, which
  matters more than usual for a user who hand-types from his phone
  screen. There is no dataset management of any kind (G2).
- **Fix:** Add a browse button (file picker) next to the Dataset
  field in the detail panel, and an existence check at save: warn
  when the path does not exist ("dataset not found — is the path
  right?") without blocking (the file may be created or pulled
  later). Wire the JSONL format check, example count, 3-example
  preview, and train/val split display to Item 3's validator when it
  lands; until then, do a basic readability check (file exists, is
  readable, lines parse as JSON) and report the first malformed line
  number. The picker and the existence check land now; the full
  validator wiring is an Item 3 follow-up inside this task.
- **Done:** The picker fills the Dataset field; saving a missing path
  warns; a valid JSONL file shows an example count and a preview; a
  malformed file reports the bad line number. Tests with fake
  datasets: missing path warning, malformed-line report, example
  count, picker fill.

### T7 — Method guidance: warn on "full"

- **Covers:** W7, U6, D7
- **Effort:** S
- **Problem:** The Method combo offers `full` next to `lora`, with no
  hint that a full fine-tune of a 1.5–2B model on this CPU is
  infeasible (the brief established this: it needs a free cloud GPU).
  A user picking `full` gets a project that can never complete on his
  PC. The choice looks equal; it is not. (The model side — any method
  string accepted — is fixed by T2's enum.)
- **Fix:** `full` gets a warning badge in the UI ("not feasible on
  this PC — needs a cloud GPU") and a tooltip explaining both methods;
  or it is hidden until a cloud path exists — one-line decision,
  Joshua's call. LoRA stays the default for new projects.
- **Done:** Selecting `full` shows the warning (or `full` is absent
  until a cloud path exists, per the decision); a new project
  defaults to `lora`; the tooltip explains both methods. Tests:
  default method, warning shown on selecting `full`.

### T8 — Trash instead of delete (projects)

- **Covers:** W8, D10
- **Effort:** M
- **Problem:** Same as Profiles W5: one confirm dialog, then
  `shutil.rmtree` on the project folder — settings, notes, and (from
  v0.2) checkpoints. No trash, no backup, no "export first" offer.
  One misclick past Yes deletes a project that may hold hours of
  training.
- **Fix:** Move deleted projects to
  `~/.stella/trash/<profile>-<project>-<date>/` instead of destroying
  them, with a purge action (manual, and/or automatic after a stated
  age). Offer "export this project first" in the delete dialog. Keep
  the confirm dialog. Build this together with the Profiles trash fix
  (audit #1, T5) as one trash system — the merged list combines them
  into a single task.
- **Done:** Delete a project: it leaves the list, and its full folder
  (settings, notes, checkpoints) appears under `~/.stella/trash/`
  with a dated name; restoring it by moving it back works. The delete
  dialog offers to export the project first. Purge removes a trashed
  project permanently, with its own confirm. Tests: delete-to-trash,
  trash contents intact, purge.

---

## P2 — missing capabilities and inconsistencies

### T9 — RAM/time estimate in the detail panel

- **Covers:** W9, G4, D8
- **Effort:** M
- **Problem:** Rank up to 64, seq len up to 32768, batch up to 32,
  epochs up to 100 — all selectable with no RAM or time estimate.
  The defaults are good, but the extremes are swap death on 8 GB
  with no warning at configure time. Item 3's RAM guard will refuse
  at train time; the settings panel should say so before the user
  invests in a doomed configuration. There is no cost estimate of
  any kind today (G4) — the user configures blind.
- **Fix:** Show a rough estimate in the detail panel for the current
  settings, reusing Item 3's RAM-guard math: "fits in 8 GB" or "will
  not fit" for RAM, plus a rough time note (orders of magnitude, not
  a promise). Warn, don't block: a configuration that will not fit
  gets a visible warning but can still be saved (the user may intend
  to train it elsewhere). The estimate updates as settings change.
  The math comes from Item 3 — if the guard has not landed yet,
  build the estimate display against a small documented estimator
  and swap in the guard's math when it arrives.
- **Done:** Rank 64 + seq 32768 shows "will not fit"; the defaults
  show "fits"; changing a setting updates the estimate; an
  over-large configuration warns but still saves. Tests: estimate
  states for known-good and known-bad settings, update-on-change.

### T10 — Clone project, and project templates

- **Covers:** W13, G5, D9
- **Effort:** M
- **Problem:** Same dataset + settings, second try (different rank,
  different metamorph mode) means creating a fresh project and
  re-entering everything. The most common fine-tuning workflow —
  try, compare, vary one knob — has no shortcut. There are no
  known-good starting points either (G5): every project starts from
  the same generic defaults.
- **Fix:** Add a Clone action (GUI button + `Store.clone_project`):
  same dataset, settings, and metamorph mode under a new name, no
  checkpoints copied, fresh notes with a "cloned from X" header
  line. Add project templates: a template picker at New Project
  time, with the first template an "LFM3 tool-format" preset carrying
  known-good settings (confirm the preset values with Joshua, or use
  the audit's recommended defaults as the starting point). Templates
  live as JSON in the tree so new ones can be added without code.
- **Done:** Clone a project: the new project appears with identical
  settings, dataset, and metamorph mode under its own name, zero
  checkpoints, and a "cloned from" note; the original is untouched.
  Creating from the LFM3 template pre-fills the preset values.
  Tests: clone copies settings, clone does not copy checkpoints,
  template pre-fill, clone-name collision rejected.

### T11 — CLI parity: rename, delete, update, show project

- **Covers:** W11, D13
- **Effort:** S
- **Problem:** The CLI cannot rename, delete, update, or show a
  project. Scripted project management is impossible; everything
  goes through the GUI or hand-edited JSON.
- **Fix:** Add `stella rename-project <profile> <old> <new>`,
  `stella delete-project <profile> <name>` (with the same trash
  behavior as T8, plus a `--purge` flag for permanent removal),
  `stella update-project <profile> <name>` (flags for display,
  dataset, metamorph, and each setting), and
  `stella show-project <profile> <name>` (full manifest, readable).
  Reuse the Store methods and error messages the GUI already uses.
  (In the merged list this task is combined with the profile CLI
  commands from audit #1 into one cli.py change.)
- **Done:** Each command works end to end from a terminal against a
  scratch home; `delete-project` moves the project to trash (T8);
  errors print the same messages as the GUI. Tests for all four
  commands including bad-name and missing-project exits.

### T12 — Merge the three notes into one surface

- **Covers:** W10, D12
- **Effort:** S
- **Problem:** `metamorph.notes` has no UI (the combo edits mode
  only); `settings["notes"]` exists in the defaults but nothing
  reads or writes it; `notes.md` is the only notes surface the user
  can reach. Three fields with overlapping purposes, two of them
  unreachable — and a user hand-editing the JSON cannot tell which
  one matters.
- **Fix:** Drop `settings["notes"]` (migration removes it from
  existing manifests; document the removal in the CHANGELOG). Add a
  metamorph-notes field to the detail panel — a small text area
  under the MetaMorphAi combo, saved with the project. Keep
  `notes.md` as the running log. Document in the README which notes
  live where: metamorph notes = why this morph/compress choice;
  notes.md = the running log of the fine-tune.
- **Done:** `settings["notes"]` is gone from new and migrated
  manifests; metamorph notes are editable in the detail panel and
  persist; `notes.md` is unchanged. Tests: migration removes the
  dead key, metamorph-notes save-through.

### T13 — A real New Project form

- **Covers:** W12
- **Effort:** S
- **Problem:** The GUI creates a project from a single name prompt —
  no dataset, no metamorph choice, no settings. Every project starts
  identical and must be configured afterwards, one field at a time.
  The CLI already has the flags (`--dataset`, `--metamorph`); the
  GUI never got the form.
- **Fix:** Replace the name-only prompt with a real New Project
  dialog (a QDialog, centered on the parent, Enter submits): name,
  display name, dataset (with the picker from T6), metamorph mode,
  and a template picker (T10) when templates exist. Settings stay in
  the detail panel after creation — the form covers identity,
  dataset, and mode only. Defaults apply when fields are left blank.
- **Done:** Create a project from the GUI with a dataset and a
  metamorph mode in one step; blank fields fall back to the defaults;
  Enter submits the dialog. Tests: dialog create-through with
  dataset + mode, defaults when blank.

### T14 — Notes backup

- **Covers:** G7, D11
- **Effort:** S
- **Problem:** `notes.md` is a single overwrite on every save; a
  mistaken save loses the previous notes with no backup.
- **Fix:** On each notes save, keep the previous version: a rotating
  `notes.md.1` backup (simplest) or dated copies under a
  `notes-history/` folder capped at N versions — pick the rotating
  single backup unless Joshua wants history. Document the restore
  path (move the backup back over `notes.md`) in the README.
- **Done:** Save notes twice; the previous version is recoverable
  from the backup; the restore path is documented. Tests: backup
  created on save, backup holds the previous content.

---

## P3 — polish, display, and scale

### T15 — Richer project rows

- **Covers:** W14, D14
- **Effort:** S
- **Depends on:** T5 (status must be real before rows show it)
- **Problem:** Rows show display name + metamorph mode only: no
  status, no method, no rank, no dataset. Two projects with the same
  display name and mode are indistinguishable in the list (their
  slugs differ but are never shown).
- **Fix:** Show method + rank in each row (status in the row comes
  from T5). When two projects in the same profile share a display
  name, show the slug as a disambiguator.
- **Done:** Rows show method and rank alongside the status from T5;
  two same-named projects in one profile are distinguishable by
  their slugs. Tests: row text contains method/rank, slug shown on
  collision only.

### T16 — Notes placement + settings tooltips

- **Covers:** U2, U7
- **Effort:** S
- **Problem:** Two detail-panel polish flaws. (U2) The Notes editor
  sits under Save project at the bottom of a scrolling panel; in the
  1100x680 window only the "Notes" header peeks out (visible in the
  v0.1 screenshot). The running log — the field a user touches most
  during a fine-tune — needs a scroll on every visit. (U7) The
  metamorph combo has the GUI's only tooltip; rank, learning rate,
  epochs, batch, and seq len have no explanation of what they do or
  what sane values look like.
- **Fix:** Reposition Notes so it is visible without scrolling in
  the default 1100x680 window (e.g. move it above the settings form,
  or give the project section its own visible notes area — decide in
  implementation, verified by screenshot). Add a tooltip to every
  settings field explaining what it does and its sane range.
- **Done:** A screenshot at 1100x680 shows the Notes editor without
  scrolling; every settings field has a tooltip naming its purpose
  and sane values. Tests: tooltip text present on each settings
  field.

### T17 — Settings-only export (share a recipe)

- **Covers:** G6
- **Effort:** S
- **Problem:** Export is the whole package; there is no way to share
  a recipe (dataset + settings) without weights and checkpoints.
- **Fix:** Add a recipe export: a small package holding the dataset
  reference, settings, metamorph mode + notes, and project notes —
  no weights, no checkpoints. Importing a recipe creates a new
  project with those values; if the dataset path does not exist on
  the importing machine, warn at import (don't block — the dataset
  may live elsewhere). Note the seam: the package format belongs to
  export/import, so this task should land alongside (or just after)
  audit #3's export/import work to avoid two formats.
- **Done:** Export a recipe, import it into a fresh home: the project
  appears with settings, dataset ref, and metamorph mode intact, and
  no weights or checkpoints. A recipe pointing at a missing dataset
  warns at import. Tests: recipe round-trip, missing-dataset warning.

### T18 — Checkpoint management follow-up (Item 3 scope)

- **Covers:** W15, G3
- **Effort:** M
- **Problem:** `checkpoints/` is created empty and nothing in v0.1
  lists, names, or manages it — no list, resume picker, or disk
  usage. The audit notes this is Item 3's scope (its Train panel
  will own checkpoints), so it is a noted gap, not a defect — but
  v0.1 ships a folder it cannot show.
- **Fix:** Do not build a parallel checkpoint UI in v0.1. When v0.2
  (Item 3) lands, verify its Train panel lists checkpoints (name,
  step, size, date), offers resume-from-checkpoint, and shows disk
  usage — and fill any part it did not deliver. This task stays open
  until v0.2 lands.
- **Done:** Either v0.2's Train panel is verified to list checkpoints
  with resume + disk usage (with test evidence recorded here), or
  the missing parts are built in this task. Tests per the delivered
  scope.

---

## Coverage map

Every finding ID from the audit, and the task(s) covering it. Nothing
dropped.

| Finding | Task(s) | Notes |
|---|---|---|
| W1 — unsaved edits discarded on switch | T1 | Dirty tracking / auto-save, both panels |
| W2 — zero settings validation in the model | T2 | Ranges + types + unknown-key rejection |
| W3 — inf/nan learning rates write invalid JSON | T3 | Numeric input + write-layer guard |
| W4 — corrupt project manifest vanishes silently | T4 | Damaged row + Repair + tests |
| W5 — status is a dead letter | T5 | Lifecycle enum + UI |
| W6 — dataset ref unvalidated text | T6 | Picker + existence + format checks |
| W7 — "full" offered with no warning | T2, T7 | T2 method enum; T7 warning badge |
| W8 — delete unrecoverable | T8 | Trash + export-first offer |
| W9 — no sane-range guidance on the extremes | T9 | RAM/time estimate at configure time |
| W10 — three notes, one visible | T12 | Merge into one surface |
| W11 — no CLI parity | T11 | Four new CLI commands |
| W12 — New Project is name-only | T13 | Real New Project form |
| W13 — no clone / duplicate project | T10 | Clone action + templates |
| W14 — project list shows almost nothing | T5, T15 | T5 status in row; T15 method/rank/slug |
| W15 — checkpoints are a bare folder | T18 | Item 3 follow-up |
| U1 — no dirty indicator, no save warning | T1 | Dirty tracking |
| U2 — Notes sits below the fold | T16 | Reposition Notes |
| U3 — learning rate bare text, no range hint | T3 | Numeric input + hint |
| U4 — no status shown anywhere | T5 | Status in list + detail |
| U5 — dataset is a bare text field | T6 | File picker |
| U6 — "full" offered with no warning | T7 | Warning badge |
| U7 — no tooltips on the settings fields | T16 | Tooltip per field |
| G1 — no training lifecycle | T5 | Lifecycle enum + transitions |
| G2 — no dataset management | T6 | Picker + validation + preview |
| G3 — no checkpoint management | T18 | Item 3 follow-up |
| G4 — no cost estimate | T9 | RAM/time estimate |
| G5 — no project templates or presets | T10 | Templates, LFM3 preset first |
| G6 — no settings-only export | T17 | Recipe export |
| G7 — no notes history | T14 | Rotating notes backup |
| D1 — dirty tracking, or auto-save on switch | T1 | |
| D2 — validate settings in the model | T2 | |
| D3 — learning rate as a real numeric input | T3 | |
| D4 — damaged-row for corrupt manifests | T4 | |
| D5 — a real status lifecycle, with UI | T5 | |
| D6 — dataset picker + validation | T6 | |
| D7 — method guidance | T7 | |
| D8 — RAM/time estimate in the detail panel | T9 | |
| D9 — clone project, and project templates | T10 | |
| D10 — trash-on-delete | T8 | |
| D11 — notes backup | T14 | |
| D12 — merge the three notes into one surface | T12 | |
| D13 — CLI parity | T11 | |
| D14 — richer project rows | T15 | |

**Coverage check:** 15 weaknesses + 7 UI flaws + 7 gaps + 14 design
suggestions = 43 findings. All 43 appear in the map above, each with
at least one task. 18 tasks total: 3 P0 (T1–T3), 5 P1 (T4–T8),
6 P2 (T9–T14), 4 P3 (T15–T18).

**Dependency order (within the priority order above):** T2 before T3
(the model rules define the learning-rate range the GUI enforces);
T5 before T15 (status must be real before rows show it); T8 before
T11's `delete-project` (delete to trash); T6's full validation and
T9's estimate depend on Item 3 (the validator engine and the RAM-guard
math) — the picker, the existence check, and the estimate display can
land first and be wired to Item 3 when it arrives; T18 stays open
until v0.2 lands. T4 and T8 are built together with their Profiles
counterparts (audit #1, T1 and T5) — see the merged list.
