# STELLA Audits #1–#2 — Merged Task List (Profiles + Projects)

**Sources:**
[audit-01-profiles-2026-11-12.md](audit-01-profiles-2026-11-12.md)
(Profiles audit, 2026-11-12) and
[audit-02-projects-2026-11-12.md](audit-02-projects-2026-11-12.md)
(Projects audit, 2026-11-12), both against v0.1 / commit e28db915.
Standalone per-audit lists:
[audit-01-profiles-task-list.md](audit-01-profiles-task-list.md) (18
tasks) and
[audit-02-projects-task-list.md](audit-02-projects-task-list.md) (18
tasks).

**This file is a list only.** Nothing here has been fixed or built.
Each task turns one or more audit findings into work with a verifiable
"done". Tasks are renumbered T1..T33 in priority order (P0 first, then
P1, P2, P3; dependency order inside each priority).

**Finding IDs are prefixed to disambiguate the two audits:** A1- = from
audit #1 (Profiles), A2- = from audit #2 (Projects). Each task carries
an **Origin** line naming the standalone task(s) it came from.

**Merged (deduped) tasks:** three fixes are genuinely shared and are
built once, not twice — damaged-row (A1-W1 + A2-W4 → T1), trash-on-delete
(A1-W5 + A2-W8 → T6), and CLI parity (A1-T7 + A2-T11 → T13, one
`cli.py` change). Dirty tracking (T3) is a single task covering BOTH
the project and profile detail panels. Everywhere else, tasks stay
separate; relationships are noted in the Covers line.

**Priority key:** P0 = data loss / silent failure, fix first.
P1 = real functional defect or daily friction. P2 = missing capability
or inconsistency. P3 = polish, display, and scale.

**Effort key:** S = a focused change in one or two files, a day or
less. M = a change across model + GUI + tests, or a small design
decision plus implementation. L = a multi-part build or a design that
needs Joshua's direction on scope first.

**Counts:** 33 tasks — 5 P0, 6 P1, 12 P2, 10 P3. (18 + 18 standalone
tasks minus 3 merges.)

---

## P0 — fix first

### T1 — Show corrupt manifests as damaged rows, never silently vanish (profiles + projects)

- **Origin:** audit #1 T1 + audit #2 T4 (merged — one fix)
- **Covers:** A1-W1, A1-D4; A2-W4, A2-D4
- **Effort:** M
- **Problem:** Both list functions swallow parse errors and skip the
  row with no warning, no row, no log. Probed on both sides:
  corrupting a `profile.json` removed the profile (and all its
  projects) from the GUI and CLI entirely, and corrupting a
  `project.json` removed the project (settings, notes, and from v0.2
  checkpoints) the same way — while a direct `get_profile` /
  `get_project` still raises a clear "not valid JSON" error. The home
  is meant to be hand-editable, so a hand-edit typo is the most likely
  cause — the user doing exactly what the docs invite is the user most
  likely to hit this. No test covers it on either side.
- **Fix:** `list_profiles` and `list_projects` (and both GUI list
  builds) must surface a broken manifest instead of skipping it: a
  greyed "damaged" row showing the slug and the parse error, plus a
  Repair action that opens the JSON in the text editor. Keep the
  folders untouched; the data is still on disk and the UI must say
  so. One shared implementation across both lists, not two copies.
- **Done:** Corrupt a `profile.json` and a `project.json` by hand,
  open Stella: both appear as greyed rows with their error text;
  Repair opens the file; fixing the JSON by hand and refreshing
  restores both normal rows. New tests: a corrupt manifest is
  reported (not skipped) by both list paths, and the GUI shows the
  damaged row in both panes.

### T2 — Soft tag validation at create and save (warn, don't block)

- **Origin:** audit #1 T2
- **Covers:** A1-W2, A1-D2; A1-W12 (duplicate-tag note)
- **Effort:** S
- **Problem:** Any string is accepted as an Ollama tag. Probed:
  `create_profile("bogus", ollama_tag="not-a-real-model:99")`
  succeeds and stores the tag. The GUI picker offers real tags, but
  the combo is editable and nothing checks the typed value — not at
  create, not at save. A typo (`lfm3:1.7bb`, `qwen3-v1` for
  `qwen3-vl`) only fails later, at train or export time, with an
  error that will not point back at the profile. Separately, nothing
  notes when two profiles point at the same tag (A1-W12).
- **Fix:** At create and at save, check the tag against the installed
  model list (a direct `list_models()` call is fine here — it is a
  user-initiated action, not a click; T7's cache replaces it later).
  If the tag is not installed, warn ("not installed locally — is
  this right?") and let him proceed — a deliberate entry (a tag he
  is about to pull) must never be blocked. Also warn when another
  profile already uses the same tag ("profile X already uses this
  tag"), without blocking.
- **Done:** Create a profile with `not-a-real-model:99`: a warning
  appears and the user can still proceed. Create with a typo'd tag
  while the correct tag is installed: warning appears. Create a
  second profile with an already-used tag: the duplicate note
  appears. Tests cover: warning on uninstalled tag, no warning on
  installed tag, duplicate-tag note, proceed-anyway path.

### T3 — Dirty tracking, or auto-save on switch (both detail panels)

- **Origin:** audit #2 T1
- **Covers:** A2-W1, A2-U1, A2-D1
- **Effort:** M
- **Problem:** There is no dirty tracking anywhere. Edit the notes or
  any field, click another project, and `_show_project_detail`
  reloads from disk — the edits are gone with no warning, no prompt,
  no asterisk. Probed live: typed "UNSAVED edit" into the notes and
  changed the display name, switched projects and back — notes
  reverted to the saved text, display name reverted to the slug.
  Edited fields look identical to saved ones (A2-U1). The same flaw
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

### T4 — Validate settings in the model, once, everywhere

- **Origin:** audit #2 T2
- **Covers:** A2-W2, A2-D2; A2-W7 (model part — method enum)
- **Effort:** M
- **Problem:** `update_project` merges any settings dict without
  checking a single value. Probed: rank -5, epochs 0, batch size 0,
  learning rate -0.5, max seq len 999999, and an unknown key `foo`
  were all stored without complaint — and `method="banana"` was
  stored too (A2-W7). The GUI spinboxes constrain only the GUI path;
  the CLI, imports, and hand-edits bypass everything. Training
  (v0.2) will receive nonsense settings and fail cryptically — or
  worse, "train" for 0 epochs and report success.
- **Fix:** Validate inside `create_project` / `update_project`, so
  the GUI, CLI, imports, and hand-edits all get the same rules:
  method must be one of `lora`, `full`; rank an integer 1–64; epochs
  an integer 1–100; batch size an integer 1–32; max seq len an
  integer 128–32768; learning rate a finite number in the sane range
  (defined with T5); unknown keys rejected with a `StellaError`
  naming the key. Every rejection must say which value was wrong and
  what is accepted.
- **Done:** Each probed bad value (rank -5, epochs 0, batch 0,
  lr -0.5, seq 999999, unknown key `foo`, method `banana`) is now
  rejected with a readable message; the defaults and all valid values
  still save. The GUI, CLI, and import paths all hit the same rules
  (one bad value tested through each path). Tests for every rule plus
  unknown-key rejection.

### T5 — Learning rate as a real numeric input with a sane range

- **Origin:** audit #2 T3
- **Covers:** A2-W3, A2-U3, A2-D3
- **Effort:** S
- **Problem:** The GUI's only learning-rate check is `float(...)`,
  and `float()` accepts `"inf"`, `"-inf"`, and `"nan"`. Probed:
  saving lr=inf wrote a bare `Infinity` literal into `project.json`
  — not valid JSON for any tool except Python's lenient parser. The
  field is a bare text box with no placeholder and no range hint
  (A2-U3), so `inf` and `-0.5` look exactly as valid as `0.0002`
  until save — and `inf` passes save.
- **Fix:** Replace the free-text learning rate with a validated
  numeric input (a `QDoubleSpinBox` with range 1e-5–1e-2 and enough
  decimals, or a validated line edit) that rejects inf, nan,
  negative, and zero values with the existing friendly error style,
  and shows a range hint ("0.0001 – 0.01, typical 0.0002"). The
  accepted range must match the model rules from T4. Also guard the
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

### T6 — Trash instead of delete (profiles + projects)

- **Origin:** audit #1 T5 + audit #2 T8 (merged — one trash system)
- **Covers:** A1-W5, A1-D6; A2-W8, A2-D10
- **Effort:** M
- **Problem:** Both deletes are `shutil.rmtree` behind a single
  Yes/No dialog. `delete_profile` destroys the profile, its
  projects, notes, and (from v0.2) checkpoints; `delete_project`
  destroys a project that may hold hours of training. No trash, no
  backup, no "export first" offer, no undo on either side. One
  misclick past Yes deletes work that may include hours of training.
- **Fix:** One trash system for both: move deleted profiles to
  `~/.stella/trash/<slug>-<date>/` and deleted projects to
  `~/.stella/trash/<profile>-<project>-<date>/`, with a purge action
  (manual, and/or automatic after a stated age). Offer "export all
  projects first" in the profile delete dialog and "export this
  project first" in the project delete dialog. Keep the confirm
  dialogs.
- **Done:** Delete a profile with projects and delete a project: both
  leave their lists, and their full folders (projects, notes,
  checkpoints) appear under `~/.stella/trash/` with dated names;
  restoring either by moving it back works. Both delete dialogs offer
  to export first. Purge removes a trashed item permanently, with its
  own confirm. Tests: delete-to-trash for profiles and projects,
  trash contents intact, purge.

### T7 — Cache the Ollama model list; fetch off the UI thread

- **Origin:** audit #1 T3
- **Covers:** A1-W4, A1-U4, A1-D5
- **Effort:** M
- **Problem:** `_show_profile_detail` calls `list_models()` on every
  selection change, synchronously, with no cache. Probed against a
  counting fake server: window open = 1 fetch, switch to row 1 = 2,
  switch back = 3. Each fetch can block the UI thread up to the
  2-second timeout if Ollama hangs (slow startup, a loaded model, a
  swapping 8 GB box), so clicks can feel dead for up to 2 seconds.
  The New Profile dialog fetches again on open. While Ollama is down
  the tag combo is briefly empty before the stored tag is re-added
  (A1-U4 flicker on every click).
- **Fix:** Fetch the installed-model list once at startup into a
  cache; serve every selection change and every combo fill from the
  cache. Refresh on demand only: a Refresh button, and when the New
  Profile dialog opens. Move the fetch to a background thread so a
  hung Ollama never blocks a click; the UI keeps showing the last
  good list (and the stored tag) while a refresh is in flight.
- **Done:** Against a counting fake Ollama server: 1 fetch at
  startup, 0 fetches across any number of profile selection changes,
  1 fetch on explicit Refresh. With Ollama hung (no response within
  the timeout), profile clicks still respond immediately and the
  stored tag stays visible. Tests: fetch-count test, hung-Ollama
  responsiveness test, refresh-button test.

### T8 — One source of truth for the base: resolve `base_ref`

- **Origin:** audit #1 T4
- **Covers:** A1-W3, A1-D3
- **Effort:** M
- **Problem:** `ollama_tag` and `base_ref` are two fields with one
  meaning and no sync rule. Create with a tag and `base_ref` is set
  to the same value; change the tag later and `base_ref` stays stale
  — probed: tag updated to `lfm3:2b`, `base_ref` still `lfm3:1.7b`.
  Nothing documents which field Item 3 (training) should trust, and
  the New Profile placeholder ("Same as the tag, unless the base
  lives elsewhere") never explains when they *should* differ, so the
  user cannot tell a deliberate split from an accidental one.
- **Fix:** Decide, then implement (the decision is Joshua's call —
  one line): either drop `base_ref` (the tag IS the base ref, with a
  migration that removes it from existing manifests) or define it
  properly as "HF repo / local path for training" with a one-line
  explanation in the UI. Until the decision lands, apply the sync
  rule: changing the tag updates `base_ref` unless the user
  deliberately split them. Document which field training trusts.
- **Done:** The old probe passes: update a tag and `base_ref`
  follows it (or the field is gone and nothing references it). The
  UI explains what the base field is in one line. Existing profiles
  migrate cleanly. The training docs name the field they trust.
  Tests: tag-update sync test, migration test.

### T9 — A real status lifecycle, with UI

- **Origin:** audit #2 T5
- **Covers:** A2-W5, A2-U4, A2-G1, A2-D5
- **Effort:** M
- **Problem:** `status` is free text with no lifecycle and no UI.
  Every project is born `draft` and stays `draft` forever — nothing
  transitions it through training, done, failed, or exported, and
  nothing can: the detail panel has no status control (probed: no
  `proj_status` widget exists), the list shows no status (A2-U4),
  and the model accepts any string (probed: `status="banana"` stored
  fine). An exported project still says `draft`. There is no record
  that a project trained, failed, or finished (A2-G1).
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

### T10 — Dataset picker + validation

- **Origin:** audit #2 T6
- **Covers:** A2-W6, A2-U5, A2-G2, A2-D6
- **Effort:** M
- **Problem:** Probed: `dataset_ref="/no/such/place/data.jsonl"` is
  accepted at creation with no complaint. No existence check, no
  format check, no example count, no preview. A mistyped path or a
  wrong-format file fails at train time, not at configure time — the
  most expensive moment to discover it. The field is a bare text box
  with no file picker (A2-U5): paths must be typed by hand, which
  matters more than usual for a user who hand-types from his phone
  screen. There is no dataset management of any kind (A2-G2).
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

### T11 — Method guidance: warn on "full"

- **Origin:** audit #2 T7
- **Covers:** A2-W7, A2-U6, A2-D7
- **Effort:** S
- **Problem:** The Method combo offers `full` next to `lora`, with no
  hint that a full fine-tune of a 1.5–2B model on this CPU is
  infeasible (the brief established this: it needs a free cloud GPU).
  A user picking `full` gets a project that can never complete on his
  PC. The choice looks equal; it is not. (The model side — any method
  string accepted — is fixed by T4's enum.)
- **Fix:** `full` gets a warning badge in the UI ("not feasible on
  this PC — needs a cloud GPU") and a tooltip explaining both methods;
  or it is hidden until a cloud path exists — one-line decision,
  Joshua's call. LoRA stays the default for new projects.
- **Done:** Selecting `full` shows the warning (or `full` is absent
  until a cloud path exists, per the decision); a new project
  defaults to `lora`; the tooltip explains both methods. Tests:
  default method, warning shown on selecting `full`.

---

## P2 — missing capabilities and inconsistencies

### T12 — Clone profile

- **Origin:** audit #1 T6
- **Covers:** A1-W10, A1-D7
- **Effort:** S
- **Problem:** Same base, second role means re-entering everything
  by hand. The common case — one base, two jobs (e.g. qwen3.5:2b as
  all-rounder AND as vision backup) — has no shortcut.
- **Fix:** One Clone action (GUI button + `Store.clone_profile`):
  same tag/base/role/processor/config/deps, new name, no projects
  copied (offer to copy projects as an option if it stays simple).
- **Done:** Clone a profile: the new profile appears with the same
  tag, base, role, and settings under its own name, with zero
  projects; the original is untouched. Tests: clone copies fields,
  clone does not copy projects by default, clone-name collision
  rejected.

### T13 — CLI parity: rename, delete, update, show (profiles + projects)

- **Origin:** audit #1 T7 + audit #2 T11 (merged — one `cli.py` change)
- **Covers:** A1-W9, A1-D11; A2-W11, A2-D13
- **Effort:** M
- **Problem:** The CLI can list and create profiles and projects but
  cannot rename, delete, or change either. Scripted management (bulk
  rename after the System Test run, for example) has to go through
  the GUI or hand-edited JSON.
- **Fix:** One `cli.py` change adding both sets of commands, reusing
  the Store methods and error messages the GUI already uses.
  Profiles: `stella rename-profile <old> <new>`,
  `stella delete-profile <name>` (trash behavior per T6, plus a
  `--purge` flag for permanent removal),
  `stella update-profile <name> [--role ...] [--tag ...]
  [--display ...] [--base ...] [--processor ...]`, and
  `stella show-profile <name>` (full manifest, readable). Projects:
  `stella rename-project <profile> <old> <new>`,
  `stella delete-project <profile> <name>` (trash behavior per T6,
  plus `--purge`),
  `stella update-project <profile> <name>` (flags for display,
  dataset, metamorph, and each setting), and
  `stella show-project <profile> <name>` (full manifest, readable).
- **Done:** All eight commands work end to end from a terminal
  against a scratch home; both deletes move to trash (T6); errors
  print the same messages as the GUI. Tests for all eight commands
  including bad-name and missing-item exits.

### T14 — Canonical roles wired to the rename plan, with a governing-seat warning

- **Origin:** audit #1 T8
- **Covers:** A1-W6, A1-G2, A1-D8
- **Effort:** M
- **Problem:** There is no canonical seat list, so the rename plan
  (role names from System Test measurements) has nothing to land on,
  and nothing connects a profile's role to a Forge seat or to the
  abliteration guard: a governing seat needs an abliterated base,
  and Stella never checks. A typo'd role ("drvier") silently becomes
  a new pseudo-role.
- **Fix:** Define one canonical role/seat list shared with Forge
  (driver, reviewer, vision, fast, tester, all-rounder, utility —
  confirm the final list with Joshua; it should match the System
  Test rename output). Roles outside the list are still allowed but
  flagged as custom. Add a governing-seat marker on a profile (a
  seat it is bound for, when set): if a governing seat is marked and
  the base is not abliterated, warn before any training starts. (The
  single-control part of A1-W6 — role combo in the detail panel —
  is T15.)
- **Done:** The role field offers the canonical list everywhere it
  appears; a custom role is visibly marked custom; marking a profile
  for a governing seat with a stock base produces a warning naming
  the seat and the base. Tests: canonical list present, custom-role
  flag, governing-seat warning fires and does not fire for an
  abliterated base.

### T15 — Small UI fixes: tooltips, Enter-to-create, real dialog, role combo in detail

- **Origin:** audit #1 T9
- **Covers:** A1-U1, A1-U2, A1-U3, A1-U5, A1-D10; A1-W6 (control-consistency part)
- **Effort:** M
- **Problem:** Four verified UI flaws. (A1-U1) Long tags truncate in
  the profile list (`maternion/minicpm5-heretic:2b` shows as
  `matern...`, `qwen3-vl:2b-instruct` as `qwen3-vl:2b-instru`) and
  there is no tooltip — the only `setToolTip` in the whole GUI is on
  the metamorph combo — so hovering tells you nothing. (A1-U2) Enter
  does nothing in the New Profile dialog: probed,
  `create_btn.isDefault()` is False and no default button is set.
  (A1-U3) The New Profile dialog is a plain QWidget, not a QDialog: a
  separate 420x320 window, not centered on the parent, with no
  dialog framing. (A1-U5) Role is a combo in the dialog but a bare
  text field in the detail panel — same field, two controls, and the
  suggestions vanish the moment the profile exists.
- **Fix:** Set a tooltip on every profile list row showing the full
  display name, role, and tag. Make Create the dialog's default
  button so Enter submits. Convert the New Profile dialog to a real
  QDialog centered on the parent window. Replace the detail panel's
  role text field with the same editable combo (canonical list from
  T14, plus custom entry).
- **Done:** Hovering a truncated row shows the full tag; pressing
  Enter in the New Profile dialog creates the profile; the dialog
  opens centered on the main window with dialog framing; the detail
  panel's role field offers the same suggestions as the dialog.
  Tests: tooltip text present on rows, default-button set, dialog is
  a QDialog, detail role combo offers the canonical list.

### T16 — Make config and dependencies reachable (JSON editor)

- **Origin:** audit #1 T10
- **Covers:** A1-W7, A1-D12; A1-G1 (first step)
- **Effort:** M
- **Problem:** `config` and `dependencies` exist in the manifest and
  `update_profile` allows changing them, but no UI and no CLI
  reaches them — the only way to set them is hand-editing JSON. The
  "own clean environment" half of the profile promise is currently
  unbuildable through Stella itself. Item 3 will need somewhere to
  put per-profile training config.
- **Fix:** Add a config/deps editor to the detail panel: a plain JSON
  text area for `config` and an editable list for `dependencies`,
  validated on save (bad JSON is rejected with the parse error, and
  nothing is written). Expose both through `update-profile` (T13) as
  well. This is the first step toward A1-G1; full environment
  management is T29.
- **Done:** Edit config JSON in the detail panel, save, reopen: the
  values persist and `show-profile` prints them. Invalid JSON is
  refused with a readable error and the old values stay. Tests:
  save-through, invalid-JSON rejection, CLI update path.

### T17 — Define the `processor` field

- **Origin:** audit #1 T11
- **Covers:** A1-W8
- **Effort:** S
- **Problem:** `processor` is a bare text field with no label help,
  no picker, no validation. Is it a tokenizer name, a processor
  class, a local path? The user cannot tell from the window, and
  nothing downstream reads it yet — it is a field waiting for a
  definition.
- **Fix:** Decide what `processor` means (one-line decision needed
  from Joshua: tokenizer/processor identifier, class name, or local
  path — or drop the field if Item 3 does not need it). Then: a
  one-line explanation beside the field, validation or a picker
  matching the definition, and a README line documenting it.
- **Done:** The UI explains what `processor` is in one line; an
  invalid value is rejected or warned about (per the definition);
  the README documents the field. If the decision is to drop it, the
  field is removed from the manifest, the GUI, and the docs, with a
  migration for existing profiles.

### T18 — Export a profile on its own

- **Origin:** audit #1 T12
- **Covers:** A1-G4
- **Effort:** M
- **Problem:** Export is per-project; a profile with zero projects
  cannot be moved, backed up, or shared. Combined with A1-W5, the
  only copy of a profile is the live one.
- **Fix:** Add profile export: a package holding the profile manifest
  (and, as an option, all its projects), importable back with the
  same verification the project import already does. Note the seam:
  the package format belongs to export/import, so this task should
  land alongside (or just after) audit #3's export/import work to
  avoid two formats.
- **Done:** Export a project-less profile, delete it, import the
  package: the profile returns with tag, role, base, and settings
  intact. Export with projects includes them. A corrupt profile
  package is refused with a readable error. Tests: round-trip with
  and without projects, corrupt-package rejection.

### T19 — RAM/time estimate in the detail panel

- **Origin:** audit #2 T9
- **Covers:** A2-W9, A2-G4, A2-D8
- **Effort:** M
- **Problem:** Rank up to 64, seq len up to 32768, batch up to 32,
  epochs up to 100 — all selectable with no RAM or time estimate.
  The defaults are good, but the extremes are swap death on 8 GB
  with no warning at configure time. Item 3's RAM guard will refuse
  at train time; the settings panel should say so before the user
  invests in a doomed configuration. There is no cost estimate of
  any kind today (A2-G4) — the user configures blind.
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

### T20 — Clone project, and project templates

- **Origin:** audit #2 T10
- **Covers:** A2-W13, A2-G5, A2-D9
- **Effort:** M
- **Problem:** Same dataset + settings, second try (different rank,
  different metamorph mode) means creating a fresh project and
  re-entering everything. The most common fine-tuning workflow —
  try, compare, vary one knob — has no shortcut. There are no
  known-good starting points either (A2-G5): every project starts
  from the same generic defaults.
- **Fix:** Add a Clone action (GUI button + `Store.clone_project`):
  same dataset, settings, and metamorph mode under a new name, no
  checkpoints copied, fresh notes with a "cloned from X" header
  line. Add project templates: a template picker at New Project
  time, with the first template an "LFM3 tool-format" preset carrying
  known-good settings (confirm the preset values with Joshua, or use
  the audit's recommended defaults as the starting point). Templates
  live as JSON in the tree so new ones can be added without code.
  (Related: T12 clones profiles; the two clone actions share the
  pattern but copy different objects — keep them separate.)
- **Done:** Clone a project: the new project appears with identical
  settings, dataset, and metamorph mode under its own name, zero
  checkpoints, and a "cloned from" note; the original is untouched.
  Creating from the LFM3 template pre-fills the preset values.
  Tests: clone copies settings, clone does not copy checkpoints,
  template pre-fill, clone-name collision rejected.

### T21 — Merge the three notes into one surface

- **Origin:** audit #2 T12
- **Covers:** A2-W10, A2-D12
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

### T22 — A real New Project form

- **Origin:** audit #2 T13
- **Covers:** A2-W12
- **Effort:** S
- **Problem:** The GUI creates a project from a single name prompt —
  no dataset, no metamorph choice, no settings. Every project starts
  identical and must be configured afterwards, one field at a time.
  The CLI already has the flags (`--dataset`, `--metamorph`); the
  GUI never got the form.
- **Fix:** Replace the name-only prompt with a real New Project
  dialog (a QDialog, centered on the parent, Enter submits): name,
  display name, dataset (with the picker from T10), metamorph mode,
  and a template picker (T20) when templates exist. Settings stay in
  the detail panel after creation — the form covers identity,
  dataset, and mode only. Defaults apply when fields are left blank.
- **Done:** Create a project from the GUI with a dataset and a
  metamorph mode in one step; blank fields fall back to the defaults;
  Enter submits the dialog. Tests: dialog create-through with
  dataset + mode, defaults when blank.

### T23 — Notes backup

- **Origin:** audit #2 T14
- **Covers:** A2-G7, A2-D11
- **Effort:** S
- **Problem:** `notes.md` is a single overwrite on every save; a
  mistaken save loses the previous notes with no backup.
- **Fix:** On each notes save, keep the previous version: a rotating
  `notes.md.1` backup (simplest) or dated copies under a
  `notes-history/` folder capped at N versions — pick the rotating
  single backup unless Joshua wants history. Document the restore
  path (move the backup back over `notes.md`) in the README. (Applies
  to project notes; profile notes from T26 get the same treatment
  when they land.)
- **Done:** Save notes twice; the previous version is recoverable
  from the backup; the restore path is documented. Tests: backup
  created on save, backup holds the previous content.

---

## P3 — polish, display, and scale

### T24 — Health badge per profile row

- **Origin:** audit #1 T13
- **Covers:** A1-W11, A1-U6, A1-D1
- **Effort:** S
- **Depends on:** T7 (cached model list)
- **Problem:** Nothing shows whether a profile's tag is actually
  installed. A tag removed from Ollama (`ollama rm`) leaves a
  profile pointing at a missing model with no sign — it looks
  exactly as healthy as every other row until training fails. All
  rows look equally healthy: a profile pointing at a missing model,
  a profile with no tag at all, and a good profile are visually
  identical (A1-U6).
- **Fix:** Using the cached model list from T7, show a health badge
  on each row: installed ✓, missing ✗, Ollama down ?. A profile
  pointing at a removed model should look broken at a glance. A
  profile with no tag shows a distinct "no tag" state.
- **Done:** With Ollama up: installed tags show ✓, a removed tag
  shows ✗, a tag-less profile shows "no tag". With Ollama down: all
  rows show ?. Badges update on Refresh (T7). Tests: badge states
  against a fake server, Ollama-down state.

### T25 — Show what the profile points at (model metadata in the detail panel)

- **Origin:** audit #1 T14
- **Covers:** A1-G3, A1-D9; A1-G5 (last-used); A1-W12 (project count, created/updated display)
- **Effort:** M
- **Problem:** A profile knows only a tag string. No size, quant,
  context length, or capabilities (vision? tools?) are recorded or
  shown, though Ollama's `/api/show` provides them. The list row
  shows no project count, and `created`/`updated` are recorded but
  never displayed (A1-W12). There is no last-used date or activity of
  any kind (A1-G5).
- **Fix:** Fetch model metadata from a cached `/api/show` (same cache
  discipline as T7 — never on the UI thread, never per click) and
  show size, quant, context length, and capabilities in the detail
  panel. Show the project count in the list row and in the detail
  panel, the created/updated dates, and a last-used date — record
  last-used when a profile is selected for training or a project
  under it is trained (define the trigger in the implementation and
  document it).
- **Done:** The detail panel shows size, quant, context, and
  capabilities for an installed tag (from a fake `/api/show` in
  tests), a project count, created/updated dates, and a last-used
  date that updates after a training run. List rows show the project
  count. With Ollama down, metadata shows as unavailable, not as
  blank or wrong. Tests: metadata display from fake `/api/show`,
  project count, last-used update, Ollama-down display.

### T26 — Profile-level notes

- **Origin:** audit #1 T15
- **Covers:** A1-W12 (profile notes)
- **Effort:** S
- **Problem:** Projects have `notes.md`, profiles do not. There is
  nowhere to write why a profile exists, what it is for, or what was
  learned about its base.
- **Fix:** Add `notes.md` per profile (same pattern as project
  notes: `read_notes`/`write_notes` on the Store) with an editor in
  the detail panel and a Save path through the existing Save profile
  flow. Include profile notes in profile export (T18). Profile notes
  get the same backup treatment as project notes (T23).
- **Done:** Write notes in the detail panel, save, reopen: the notes
  persist. Notes survive rename. Profile export includes them.
  Tests: notes round-trip, notes survive rename.

### T27 — Search, filter, and sort for the profile list

- **Origin:** audit #1 T16
- **Covers:** A1-W12 (search/filter/sort); A1-G6 (search/sort part)
- **Effort:** M
- **Problem:** No search, filter, or sort in the list. Fine at 11
  profiles, thin at 30+. No multi-select or bulk operations either
  (A1-G6 — bulk work is T28).
- **Fix:** Add a filter box above the profile list (matches display
  name, slug, role, and tag), a role filter, and sort options
  (name, role, recently used, project count). Filtering must keep
  the current selection when the selected profile still matches.
- **Done:** Typing in the filter narrows the list live; the role
  filter shows only that role; each sort order reorders correctly;
  selection survives filtering when the profile still matches.
  Tests: filter by text, filter by role, each sort order, selection
  preserved.

### T28 — Bulk operations (multi-select)

- **Origin:** audit #1 T17
- **Covers:** A1-G6 (bulk part)
- **Effort:** M
- **Problem:** No multi-select, no bulk operations — acceptable now,
  a wall later. Every profile action is one at a time.
- **Fix:** Multi-select in the profile list (Ctrl/Shift-click) with
  bulk actions: delete (to trash, T6 — one confirm naming all
  selected), export (T18, one package per profile or a bundle), and
  role change. Single-selection behavior must not change.
- **Done:** Select three profiles, bulk-delete: all three land in
  trash with one confirm naming them. Bulk-export produces one
  package per profile. Bulk role change updates all selected.
  Single-click selection and all single-profile actions still work
  exactly as before. Tests: multi-select delete/export/role change,
  single-selection unchanged.

### T29 — Per-profile environment management (full A1-G1)

- **Origin:** audit #1 T18
- **Covers:** A1-G1 (full)
- **Effort:** L
- **Depends on:** T16 (config/deps reachable)
- **Problem:** Profiles were specced as a clean environment per base
  (weights, config, processor/tokenizer, dependencies). Config/deps
  are dead fields (A1-W7 — first step is T16), there is no per-profile
  venv or dependency install, and no record of which Python packages
  a profile's training needs.
- **Fix:** Design, then build — scope needs Joshua's direction
  before implementation: per-profile venv vs. a shared training venv
  vs. a dependency record only. At minimum: each profile records the
  Python packages its training needs, and `install-training.sh` can
  install from that record. If per-profile venvs are chosen, add
  create/activate/remove per profile and a disk-usage readout (venv
  sizes add up fast on a 1 TB HDD shared with Ollama models).
- **Done:** Per the agreed scope: a profile's dependency record is
  visible and editable (via T16), and the training installer
  consumes it. If venvs are in scope: creating a profile's
  environment, using it for a training run, and removing it all work
  from the GUI, with disk usage shown. Tests per the agreed scope.

### T30 — Richer project rows

- **Origin:** audit #2 T15
- **Covers:** A2-W14, A2-D14
- **Effort:** S
- **Depends on:** T9 (status must be real before rows show it)
- **Problem:** Rows show display name + metamorph mode only: no
  status, no method, no rank, no dataset. Two projects with the same
  display name and mode are indistinguishable in the list (their
  slugs differ but are never shown).
- **Fix:** Show method + rank in each row (status in the row comes
  from T9). When two projects in the same profile share a display
  name, show the slug as a disambiguator.
- **Done:** Rows show method and rank alongside the status from T9;
  two same-named projects in one profile are distinguishable by
  their slugs. Tests: row text contains method/rank, slug shown on
  collision only.

### T31 — Notes placement + settings tooltips

- **Origin:** audit #2 T16
- **Covers:** A2-U2, A2-U7
- **Effort:** S
- **Problem:** Two detail-panel polish flaws. (A2-U2) The Notes editor
  sits under Save project at the bottom of a scrolling panel; in the
  1100x680 window only the "Notes" header peeks out (visible in the
  v0.1 screenshot). The running log — the field a user touches most
  during a fine-tune — needs a scroll on every visit. (A2-U7) The
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

### T32 — Settings-only export (share a recipe)

- **Origin:** audit #2 T17
- **Covers:** A2-G6
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
  audit #3's export/import work to avoid two formats (same seam as
  T18).
- **Done:** Export a recipe, import it into a fresh home: the project
  appears with settings, dataset ref, and metamorph mode intact, and
  no weights or checkpoints. A recipe pointing at a missing dataset
  warns at import. Tests: recipe round-trip, missing-dataset warning.

### T33 — Checkpoint management follow-up (Item 3 scope)

- **Origin:** audit #2 T18
- **Covers:** A2-W15, A2-G3
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

## Coverage map (unified — both audits)

Every finding ID from both audits, and the merged task(s) covering
it. Nothing dropped. A1- = audit #1 (Profiles), A2- = audit #2
(Projects).

| Finding | Task(s) | Notes |
|---|---|---|
| A1-W1 — corrupt manifest vanishes silently | T1 | Damaged row + Repair + tests (profiles side) |
| A1-W2 — any string accepted as a tag | T2 | Soft validation, warn don't block |
| A1-W3 — tag/base_ref drift | T8 | One source of truth + sync rule |
| A1-W4 — every click re-fetches Ollama | T7 | Cache + off-thread fetch |
| A1-W5 — delete unrecoverable | T6 | Trash + export-first offer (profiles side) |
| A1-W6 — role is two controls, no canonical list | T14, T15 | T14 canonical list + seat warning; T15 single role combo |
| A1-W7 — config/deps dead fields | T16 | JSON editor; first step of A1-G1 |
| A1-W8 — processor undefined | T17 | Define it, label it, validate it |
| A1-W9 — no CLI for rename/delete/update | T13 | Four new profile CLI commands |
| A1-W10 — no clone profile | T12 | Clone action |
| A1-W11 — no health indicator | T24 | Health badges (needs T7) |
| A1-W12 — small missing pieces | T2, T25, T26, T27 | T2 duplicate-tag note; T25 project count + created/updated; T26 notes; T27 search/filter/sort |
| A1-U1 — long tags truncate, no tooltip | T15 | Tooltips on rows |
| A1-U2 — Enter does nothing in dialog | T15 | Default button |
| A1-U3 — dialog is a QWidget, not QDialog | T15 | Real QDialog, centered |
| A1-U4 — tag combo re-fetch flicker | T7 | Cache removes the re-fetch |
| A1-U5 — role combo vs text field | T15 | Role combo in detail panel too |
| A1-U6 — all rows look equally healthy | T24 | Health badges |
| A1-G1 — no environment management | T16, T29 | T16 first step (reachable fields); T29 full build |
| A1-G2 — no seat mapping | T14 | Canonical roles + governing-seat warning |
| A1-G3 — no model metadata | T25 | Cached /api/show display |
| A1-G4 — profile cannot be exported alone | T18 | Profile export (seam with audit #3) |
| A1-G5 — no profile history | T25 | Last-used date |
| A1-G6 — no bulk operations | T27, T28 | T27 search/sort; T28 multi-select bulk |
| A1-D1 — health badge per row | T24 | |
| A1-D2 — soft tag validation | T2 | |
| A1-D3 — one source of truth for base | T8 | |
| A1-D4 — never silently vanish | T1 | |
| A1-D5 — cache model list, off UI thread | T7 | |
| A1-D6 — trash, not delete | T6 | |
| A1-D7 — clone profile | T12 | |
| A1-D8 — canonical roles, rename plan | T14 | |
| A1-D9 — show what the profile points at | T25 | |
| A1-D10 — small UI fixes | T15 | |
| A1-D11 — CLI parity | T13 | |
| A1-D12 — config/deps reachable | T16 | |
| A2-W1 — unsaved edits discarded on switch | T3 | Dirty tracking / auto-save, both panels |
| A2-W2 — zero settings validation in the model | T4 | Ranges + types + unknown-key rejection |
| A2-W3 — inf/nan learning rates write invalid JSON | T5 | Numeric input + write-layer guard |
| A2-W4 — corrupt project manifest vanishes silently | T1 | Damaged row + Repair + tests (projects side) |
| A2-W5 — status is a dead letter | T9 | Lifecycle enum + UI |
| A2-W6 — dataset ref unvalidated text | T10 | Picker + existence + format checks |
| A2-W7 — "full" offered with no warning | T4, T11 | T4 method enum; T11 warning badge |
| A2-W8 — delete unrecoverable | T6 | Trash + export-first offer (projects side) |
| A2-W9 — no sane-range guidance on the extremes | T19 | RAM/time estimate at configure time |
| A2-W10 — three notes, one visible | T21 | Merge into one surface |
| A2-W11 — no CLI parity | T13 | Four new project CLI commands |
| A2-W12 — New Project is name-only | T22 | Real New Project form |
| A2-W13 — no clone / duplicate project | T20 | Clone action + templates |
| A2-W14 — project list shows almost nothing | T9, T30 | T9 status in row; T30 method/rank/slug |
| A2-W15 — checkpoints are a bare folder | T33 | Item 3 follow-up |
| A2-U1 — no dirty indicator, no save warning | T3 | Dirty tracking |
| A2-U2 — Notes sits below the fold | T31 | Reposition Notes |
| A2-U3 — learning rate bare text, no range hint | T5 | Numeric input + hint |
| A2-U4 — no status shown anywhere | T9 | Status in list + detail |
| A2-U5 — dataset is a bare text field | T10 | File picker |
| A2-U6 — "full" offered with no warning | T11 | Warning badge |
| A2-U7 — no tooltips on the settings fields | T31 | Tooltip per field |
| A2-G1 — no training lifecycle | T9 | Lifecycle enum + transitions |
| A2-G2 — no dataset management | T10 | Picker + validation + preview |
| A2-G3 — no checkpoint management | T33 | Item 3 follow-up |
| A2-G4 — no cost estimate | T19 | RAM/time estimate |
| A2-G5 — no project templates or presets | T20 | Templates, LFM3 preset first |
| A2-G6 — no settings-only export | T32 | Recipe export |
| A2-G7 — no notes history | T23 | Rotating notes backup |
| A2-D1 — dirty tracking, or auto-save on switch | T3 | |
| A2-D2 — validate settings in the model | T4 | |
| A2-D3 — learning rate as a real numeric input | T5 | |
| A2-D4 — damaged-row for corrupt manifests | T1 | |
| A2-D5 — a real status lifecycle, with UI | T9 | |
| A2-D6 — dataset picker + validation | T10 | |
| A2-D7 — method guidance | T11 | |
| A2-D8 — RAM/time estimate in the detail panel | T19 | |
| A2-D9 — clone project, and project templates | T20 | |
| A2-D10 — trash-on-delete | T6 | |
| A2-D11 — notes backup | T23 | |
| A2-D12 — merge the three notes into one surface | T21 | |
| A2-D13 — CLI parity | T13 | |
| A2-D14 — richer project rows | T30 | |

**Coverage check:** audit #1: 12 weaknesses + 6 UI flaws + 6 gaps +
12 design suggestions = 36 findings. Audit #2: 15 weaknesses + 7 UI
flaws + 7 gaps + 14 design suggestions = 43 findings. Total 79
findings. All 79 appear in the map above, each with at least one
task. 33 tasks total: 5 P0 (T1–T5), 6 P1 (T6–T11), 12 P2 (T12–T23),
10 P3 (T24–T33).

**Dependency order (within the priority order above):** T4 before T5
(the model rules define the learning-rate range the GUI enforces);
T7 before T24 (badges need the cache); T14 before T15 (the detail
role combo shows the canonical list); T6 before T13's deletes and
T28's bulk delete (both delete to trash); T16 before T29 (reachable
fields before full environment management); T18 before T28's bulk
export (profile export must exist first); T9 before T30 (status must
be real before rows show it); T10's full validation and T19's
estimate depend on Item 3 (the validator engine and the RAM-guard
math) — the picker, the existence check, and the estimate display
can land first and be wired to Item 3 when it arrives; T33 stays open
until v0.2 lands; T18 and T32 land alongside (or just after) audit
#3's export/import work to avoid two package formats. T2 works
standalone with a direct fetch; T7's cache improves it later.
