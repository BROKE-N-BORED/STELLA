# STELLA Audit #3 — Export / Import: Task List

**Source:** [audit-03-export-import-2026-11-12.md](audit-03-export-import-2026-11-12.md)
(Export/Import audit, 2026-11-12, against v0.1 / commit e28db915).

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

**Counts:** 20 tasks — 1 P0, 7 P1, 7 P2, 5 P3.

**Shared fixes with audits #1 and #2:** two findings share their fix
with earlier audits and are built once across all three: profile
export (W7/G3 — with Profiles G4, audit #1 T12) and recipe export
(G2 — with Projects G6, audit #2 T17). In this standalone file they
appear as export/import tasks (T15, T17); the merged list
([stella-audit-task-list-123.md](stella-audit-task-list-123.md))
folds them into the single profile-export and recipe-export tasks.
Dataset handling (W8/G7) is related to Projects W6/D6 (audit #2 T6)
and base-health on import (W12/D15) to Profiles W11/D1 (audit #1
T13) — related, not shared: each side keeps its own task, with the
relationship noted.

---

## P0 — fix first

### T1 — Trust-boundary import: strict manifest validation + atomic import

- **Covers:** W1, W2, W13, D2, D3
- **Effort:** M
- **Problem:** `verify_export` checks the manifest's shape but never
  the *types* of any field, and import is not atomic — so a
  hand-edited or foreign package can crash Stella or leave partial
  state. Probed, each against a hand-edited manifest: `metamorph`
  as a string or int → raw `AttributeError` at `export.py:128`;
  `settings` as a string → raw `ValueError` from
  `merged.update(settings)` *after* the profile was created,
  leaving an orphan empty profile in the home (W1); profile
  `config` as a string → raw `ValueError`; `dependencies` as a
  string → **silently accepted and corrupted** — `"torch"` was
  stored as `['t', 'o', 'r', 'c', 'h']`; `settings` as a list of
  pairs → silently accepted; `status: "banana"` → silently
  accepted. Neither the GUI nor the CLI catches these: both catch
  only `StellaError` (`gui.py:588-591`, `cli.py:136-138`). Probed
  in the driven GUI, the `ValueError` escaped the handler, **no
  warning dialog appeared at all**, and the list showed 0 rows
  while the orphan profile sat on disk; on the CLI it is a raw
  traceback, exit 1, no `stella:` prefix. Separately (W13),
  `import_export` returns the manifest's raw names while the store
  lowercases them — importing `Zebra-Proj` returned profile
  `Zebra-Proj` but stored `zebra-proj`, and the GUI then selected
  the **wrong profile** (row 0, `aaa-first`). Import is the trust
  boundary — packages come from other machines, other people, and
  hand-edits — and it is the one place Stella must never crash on
  bad input.
- **Fix:** D2 — validate the manifest schema strictly in
  `verify_export`: types for every field (settings and config must
  be dicts, dependencies a list, metamorph a dict, dataset ref and
  status strings), the metamorph mode enum, and the version range
  from T2; every failure a `StellaError` with a plain message.
  Nothing downstream should ever see a manifest field it has not
  already validated. Normalize slugs once, at import start (W13),
  so the returned names match the stored names. D3 — make import
  atomic: validate everything first, then write; on any failure,
  roll back (remove the profile/project just created) or stage the
  whole import in a temp directory and move it into place last. A
  failed import must leave the home exactly as it was. Add a
  last-resort catch in the GUI handler and the CLI so an unexpected
  exception still surfaces as a readable error, never a raw crash.
  (Status validation reuses the lifecycle enum from audit #2's
  status task once it lands; until then, reject non-string
  statuses. Settings *value* ranges are audit #2's model
  validation — this task covers types and shape at the boundary.)
- **Done:** Each probed bad manifest (metamorph string/int,
  settings string/list, config string, dependencies string,
  status `banana`, uppercase names) is refused with a readable
  `StellaError` and leaves the home untouched — no orphan profile,
  no corrupted fields. The GUI shows a warning dialog for each;
  the CLI prints a `stella:`-prefixed error and exits 1 with no
  traceback. Importing `Zebra-Proj` selects `zebra-proj` in the
  GUI. Tests: one per probed variant, atomicity (home byte-identical
  after a failed import), normalization (returned names equal the
  stored names).

---

## P1 — functional defects and daily friction

### T2 — Settle the package format: versioned format + named kinds

- **Covers:** W5, W6 (format side), G1, G3, D1
- **Effort:** M
- **Problem:** `stella_version` is stamped on every manifest and
  means nothing: no supported range, no "too new" rejection, no
  migration. Probed: a manifest claiming version `99.0` imports
  fine; a manifest with the field deleted imports fine. What the
  package is today is a *single-project folder* — manifest (one
  profile block + one project block) + a duplicate `config.json` +
  README + placeholder-only `weights/` + checkpoints + notes, with
  no version semantics, no checksums, no timestamps, no
  provenance. The manifest holds exactly one project, so the format
  cannot express "a profile with all its projects" (G3). This is a
  live forward-compat hazard: the first v0.2 package carrying real
  weights will import into v0.1 and lose the weights silently,
  because v0.1 has no way to know the package is newer than it.
- **Fix:** Give the format a real version, separate from the app
  version (`format: 1`), with a supported range enforced on import
  and a clear "this package needs a newer Stella" message for
  newer packages. Define the package kinds up front — project
  package (today's), profile package
  (`kind: "stella-profile-export"`, T15), recipe package (T17) —
  as distinct `kind` values sharing one manifest shape, so profile
  and recipe export never become two formats. `weights/` becomes a
  first-class round-tripped member in the same pass (T3).
  Document the format in the repo (a FORMAT doc or a README
  section) so a hand-editing user can read it. The version check
  must land *with or before* the first weights-carrying export.
  (Enforced in `verify_export`, alongside T1's schema validation.)
- **Done:** A package with format 99 is refused with "needs a newer
  Stella"; a legacy v0.1 package (no `format` field) imports under
  a documented rule (treated as format 1, or refused with a
  migration note — decide in implementation and document it). The
  three kinds are defined in one place and share the manifest
  shape. Tests: version rejection, legacy-package handling, kind
  values present.

### T3 — Round-trip `weights/`

- **Covers:** W6, D5
- **Effort:** S
- **Depends on:** T2 (lands with the version check)
- **Problem:** Import copies checkpoints and notes only
  (`export.py:174-187`); `weights/` is not mentioned. Probed: a
  package containing `weights/adapter.safetensors` imported
  successfully — and the imported project has **no** `weights/`
  directory at all. The payload the whole program exists to
  produce has no round-trip. Today that costs nothing (v0.1 ships
  no weights), but the format must be settled *before* v0.2 puts
  weights in the package, or every v0.1 import of a v0.2 package
  will silently eat the fine-tune.
- **Fix:** Copy the weights folder on import (minus the placeholder
  note) and treat it as the payload; export writes real weights
  when they exist. Land with T2's version check so no older Stella
  can silently drop it.
- **Done:** Export a project with a weights file, import into a
  fresh home: `weights/` is present with the file byte-identical;
  the placeholder note is not copied as a weight. A v0.1-era
  package (placeholder only) still imports. Tests: weights
  round-trip, placeholder handling.

### T4 — Merge, don't discard, the profile block on import

- **Covers:** W4, U7, D4
- **Effort:** M
- **Problem:** If the profile already exists, `import_export`
  reuses it and never looks at the manifest's profile block
  (`export.py:143-151`). Probed: importing into a home whose
  `lfm3-tool` had tag `other:9b` and role `driver` left the tag
  and role untouched — the package's `lfm3:1.7b` / `fast` were
  dropped without a word. Probed further: exporting two projects
  from one profile, changing the tag between exports, then
  importing both into a fresh home — the **first** package's tag
  won and the second package's profile block was discarded. No
  warning, no diff, no merge, no choice. Because export is
  one-project-at-a-time (W7), this is the normal way a
  multi-project profile moves between machines — so the normal
  path silently drops profile data. The UI face (U7): nothing in
  the window says so, not even the `profile_existed` flag import
  already returns.
- **Fix:** When the profile exists, compare tag / role / base with
  the manifest: identical → silent; different → warn and let the
  user pick keep-local or take-package (a dialog in the GUI; a
  flag or prompt on the CLI). Surface `profile_existed` in the UI
  (a status message, or the preview dialog from T7).
- **Done:** Import with a differing tag: a choice appears and the
  chosen values win; identical blocks import silently; the UI says
  when the profile already existed. Tests: identical-silent,
  differ-choice in both directions, `profile_existed` surfaced.

### T5 — One source of truth for settings

- **Covers:** W3, D6
- **Effort:** S
- **Problem:** `config.json` is required but never read:
  `verify_export` rejects a package missing it
  (`export.py:131-132`), but nothing ever reads the file — import
  takes settings from the manifest only. Probed: a package with
  **invalid JSON** in `config.json` imports fine; a package whose
  `config.json` says rank 999 imports with rank 16 (the
  manifest's value). So the file is simultaneously mandatory and
  meaningless. Worse, it invites exactly the wrong edit: a user
  who opens the file named "config" and changes a setting has
  changed nothing, and nothing tells them.
- **Fix:** Drop `config.json` from the package (the manifest
  already holds the settings) or make import read it and
  cross-check against the manifest — pick one, document it. Never
  require a file you never read. If dropped: `verify_export` no
  longer requires it, and old packages that carry it still import
  (the extra file is ignored).
- **Done:** A package without `config.json` imports (if dropped),
  or a disagreeing `config.json` is refused or flagged (if
  cross-checked); the chosen rule is documented. Tests: missing
  `config.json`, disagreeing `config.json`, invalid-JSON
  `config.json`.

### T6 — Make the dataset part of the package decision

- **Covers:** W8, G7, D7
- **Effort:** M
- **Problem:** The dataset is never copied: `dataset_ref` is
  carried as a bare string (probed: no trace of the dataset file
  in the package tree). A project whose dataset is
  `/home/joshua/data/forge-traces.jsonl` exports that absolute
  path — into the manifest **and** the README — and the imported
  project points at the same path on a machine where it may not
  exist. Import never checks whether the referenced path exists
  and never warns. The package is portable; its most important
  input is not. (Cross-ref audit #2, W6: the dataset ref is
  unvalidated text — the project-side picker and validation are
  audit #2's T6; this task is the package side.)
- **Fix:** At export, offer "copy the dataset in" (with its size
  shown) or keep the reference; at import, check the referenced
  path exists and warn — with a "locate it on this machine" repair
  — when it does not. If the dataset was bundled, import uses the
  bundled copy. Don't block on a missing dataset (it may live
  elsewhere).
- **Done:** Export with "copy in": the dataset file is in the
  package and used on import; export with reference only: import
  warns when the path is missing and offers to locate it; import
  with an existing path is silent. Tests: bundled round-trip,
  missing-path warning, locate repair.

### T7 — Import preview dialog

- **Covers:** U2, U7, D10
- **Effort:** M
- **Depends on:** T4 (shows the existing-profile warning + merge choice)
- **Problem:** One click imports. The user never sees what the
  package contains — profile, project, tag, version — before it
  lands. Pick the wrong folder and the first sign is a new profile
  in the list (or an error).
- **Fix:** Before importing, show profile, project, tag, version,
  and contents (checkpoints, weights, dataset ref) — with the
  existing-profile warning when it applies (T4) — and let the user
  confirm or cancel. On the CLI, print the same summary before
  importing (or add a `--preview` flag — decide in implementation).
- **Done:** Import opens a preview showing the package contents;
  Cancel imports nothing; Confirm imports; the existing-profile
  warning appears in the preview when it applies. Tests: preview
  contents, cancel imports nothing, warning shown.

### T8 — Base-health check on import

- **Covers:** W12, D15
- **Effort:** S
- **Problem:** Probed: a package whose profile claims `ollama_tag:
  "not-a-real-model:99"` imports silently and the profile looks
  perfectly healthy — until training or Ollama use fails. A package
  arriving from another machine is exactly when the base is most
  likely to be missing. (Ties to audit #1, D1 — the health
  indicator; merged list T24.)
- **Fix:** On import, check whether the profile's Ollama tag is
  installed on this machine (reuse the cached model list when
  audit #1's cache lands; a direct `list_models()` call is fine
  here — import is user-initiated, not a click). Warn when it is
  not installed ("base model not installed on this machine — pull
  it before training"), don't block.
- **Done:** Import a package with an uninstalled tag: a warning
  names the tag; an installed tag imports silently. Tests: warning
  on missing tag, silent on installed tag.

---

## P2 — missing capabilities and inconsistencies

### T9 — Checksums + sizes in the manifest

- **Covers:** W9, D8
- **Effort:** M
- **Problem:** The manifest carries no checksums, sizes, or file
  list. Probed: a checkpoint truncated from 800 bytes to 4
  (`FAKE`) imported without complaint — the corrupted file now
  sits in the home as if it were a real checkpoint. A half-copied
  package, a truncated download, a flipped bit: import cannot
  tell.
- **Fix:** A sha256 (or at least a byte size) per file in the
  manifest, verified on import; a mismatch fails loudly — refuse
  the import, or import with a clear warning naming the file
  (decide in implementation; failing loudly is the default). Cover
  checkpoints, weights, notes, and the dataset when bundled (T6).
- **Done:** A truncated checkpoint is refused or flagged on import;
  an intact package imports silently; the manifest lists a hash +
  size per file. Tests: truncated-file rejection, intact import,
  hash coverage of each member.

### T10 — Collision options

- **Covers:** W11, D9
- **Effort:** M
- **Problem:** Export refuses an existing folder and import
  refuses an existing project, and that is the end of it: no
  `--force`, no "replace", no "import as a copy under a new name",
  no merge. Every collision is a dead end that sends the user out
  to a file manager to delete or rename by hand — for a user who
  works from his phone screen, that is a real friction point, not
  a nicety.
- **Fix:** Export: an overwrite prompt in the GUI and a `--force`
  flag on the CLI (with a confirm). Import: "import as a copy"
  (new slug) or replace with a backup of the old project (to
  trash, per the merged trash task). Collisions should be choices,
  not dead ends.
- **Done:** Export over an existing folder offers overwrite;
  import of an existing project offers copy-under-new-name or
  replace-with-backup; the old project is recoverable after a
  replace. Tests: each option end to end.

### T11 — Preserve timestamps

- **Covers:** W10, D11
- **Effort:** S
- **Problem:** `created` and `updated` are not in the manifest
  (manifest keys are exactly `kind`, `profile`, `project`,
  `stella_version`). Import stamps fresh timestamps
  (`model.py:188`, `model.py:309`). An imported project looks
  brand new; its history — when it was made, when it last changed
  — is gone. (In the probe the source and imported timestamps
  matched only because both ran inside the same second; the
  manifest carries no timestamp to preserve.)
- **Fix:** Carry the original `created` / `updated` in the
  manifest and restore them on import, plus an `exported_at`
  stamp for provenance (the first piece of G6 — the rest is T18).
- **Done:** Export then import: `created` / `updated` match the
  source; `exported_at` records the export time. Tests: timestamp
  round-trip, `exported_at` present.

### T12 — A verify command

- **Covers:** G5, D12
- **Effort:** S
- **Depends on:** T1 (schema validation), T2 (version check), T9 (checksums)
- **Problem:** `verify_export` exists but no CLI command or GUI
  action exposes it — the only way to check a package is to
  import it.
- **Fix:** `stella verify <dir>` on the CLI (and a "Check
  package" action in the GUI) that runs the full verification —
  schema, version, checksums — without importing. Print a
  readable pass/fail per check.
- **Done:** `stella verify` on a good package reports all checks
  pass; on a bad package it names the failing check; nothing is
  imported either way. Tests: verify good/bad, no-import
  guarantee.

### T13 — Keep the import confirmation visible

- **Covers:** U1, D14
- **Effort:** S
- **Problem:** `import_package` says "Imported X into Y"
  (`gui.py:595`), then immediately calls `refresh_profiles`
  (`gui.py:596`), whose selection cascade calls `_say` again with
  "Profile: … — project: …". Probed in the driven GUI: after a
  successful import the status bar reads "Profile: lfm3-tool —
  project: tool-calls." — the import confirmation never survives.
  Export gets a dialog; import gets a message that erases itself.
- **Fix:** Don't let the refresh overwrite the status message (say
  it after the refresh, or add an import success dialog matching
  export's). Pick one; the confirmation must still be visible
  after the lists settle.
- **Done:** After an import, the status bar (or a dialog) still
  shows the import confirmation; the refresh no longer overwrites
  it. Tests: GUI test asserting the confirmation survives the
  refresh.

### T14 — Progress, cancel, and refresh on failure

- **Covers:** U4, U5
- **Effort:** M
- **Problem:** Export and import run synchronously in the
  button-click handler — no progress indicator, no cancel, no
  background thread. A v0.2-scale checkpoint copy will freeze the
  window with no progress bar and no way to stop it. And after
  the raw-crash failure (W2), the orphan profile exists on disk
  but the list shows 0 rows — `refresh_profiles` runs only on the
  success path (`gui.py:596`), so the user cannot even see the
  stray profile the failure left behind.
- **Fix:** Move export/import to a background thread with a
  progress indicator and a cancel; refresh the lists on failure
  too (once T1 lands, a failed import leaves no orphan to show —
  but the refresh must still run so the window reflects the disk).
  Cancel mid-copy leaves no partial state (ties to T1's
  atomicity).
- **Done:** A large export shows progress and can be cancelled,
  leaving no partial package; a failed import refreshes the lists
  so the window matches the disk. Tests: cancel leaves no partial
  state, failure refreshes the lists.

### T15 — Export a profile on its own

- **Covers:** W7, G3
- **Effort:** M
- **Depends on:** T2 (profile package kind)
- **Problem:** Export is one project only. A profile with no
  projects cannot be exported, backed up, or shared at all —
  there is no `export_profile`, no CLI command, and the GUI
  Export button needs a selected project. A profile with N
  projects must be exported N times, each package carrying a full
  duplicate of the profile block (which feeds W4). This is the
  merged task list's T18 (audit #1, G4) — in this standalone file
  it appears as its own task; the merged list folds it into the
  single profile-export task.
- **Fix:** Add profile export using the profile package kind from
  T2 (`kind: "stella-profile-export"`): a package holding the
  profile manifest (and, as an option, all its projects),
  importable back with the same verification the project import
  does (T1). GUI: the Export button offers profile export when a
  profile is selected; CLI: a `stella export-profile` command.
- **Done:** Export a project-less profile, delete it, import the
  package: the profile returns with tag, role, base, and settings
  intact. Export with projects includes them. A corrupt profile
  package is refused with a readable error. Tests: round-trip
  with and without projects, corrupt-package rejection.

---

## P3 — polish, display, and scale

### T16 — Single-file package option

- **Covers:** G4, D13
- **Effort:** M
- **Problem:** A package is a folder; sharing means zipping by
  hand. No `.stella` zip (or tar) form that import can read.
- **Fix:** Export to a `.stella` zip; import reads zips and
  folders alike. One file to email, one file to back up. The zip
  contains exactly the folder package (same manifest, same
  members).
- **Done:** Export to `.stella`, import the zip into a fresh home:
  identical result to a folder import. Tests: zip round-trip,
  folder import unchanged.

### T17 — Recipe export (settings-only)

- **Covers:** G2
- **Effort:** S
- **Depends on:** T2 (recipe package kind)
- **Problem:** Whole package or nothing. There is no way to share
  a dataset + settings recipe without checkpoints. This is the
  merged task list's T32 (audit #2, G6) — in this standalone file
  it appears as its own task; the merged list folds it into the
  single recipe-export task.
- **Fix:** Add a recipe export using the recipe package kind from
  T2: a small package holding the dataset reference, settings,
  metamorph mode + notes, and project notes — no weights, no
  checkpoints. Importing a recipe creates a new project with
  those values; if the dataset path does not exist on the
  importing machine, warn at import (don't block — the dataset
  may live elsewhere).
- **Done:** Export a recipe, import it into a fresh home: the
  project appears with settings, dataset ref, and metamorph mode
  intact, and no weights or checkpoints. A recipe pointing at a
  missing dataset warns at import. Tests: recipe round-trip,
  missing-dataset warning.

### T18 — Provenance

- **Covers:** G6
- **Effort:** S
- **Depends on:** T11 (exported_at stamp)
- **Problem:** No `exported_at`, no source machine, no record of
  what was exported where or imported from where. A package found
  on disk cannot say when it was made or from what.
- **Fix:** Build on T11's `exported_at` stamp: record the source
  machine (hostname) in the manifest, and keep a small
  import/export history (a log in the home: what was exported
  where, what was imported from where, when). Show provenance in
  the import preview (T7) when present.
- **Done:** An exported package names its source machine and
  export time; the home keeps an import/export log; the preview
  shows provenance. Tests: provenance fields present, history
  logged.

### T19 — Size/disk awareness on export

- **Covers:** W14
- **Effort:** S
- **Problem:** Export copies everything with no total size, no
  disk-space check, and no report of how big the package is. In
  v0.1 checkpoints are tiny, so this is unobservable — but v0.2
  checkpoints and weights will be large, and the copy already runs
  synchronously in the button handler (see U4). The first GB-scale
  export will freeze the window with no warning and no progress.
- **Fix:** Report the package size before/after export (in the
  success dialog and the CLI output); check free disk space
  against the estimated package size before copying and
  refuse/warn when it will not fit. (Progress display itself is
  T14.)
- **Done:** Export reports the package size; exporting when disk
  space is short warns before copying. Tests: size reported,
  low-disk warning (fake a small filesystem or a huge estimate).

### T20 — README wording + export/import UI polish

- **Covers:** W15, U3, U6
- **Effort:** S
- **Problem:** Three polish flaws. (W15) `README.md:43-44`: "a
  finished fine-tune exports as a usable package (manifest,
  config, weights, checkpoints)". v0.1 exports no weights — the
  package's own `weights/README.txt` says so honestly, but the top
  README lists weights as package content and calls the result
  "usable". A package with no weights is a recipe plus
  checkpoints, not a usable fine-tune. (U3) Both buttons are
  always enabled (probed). Export with no selection warns *after*
  the click ("Pick a project to export.") instead of disabling
  the button until a project is selected. (U6) The export dialog
  never shows the package name. The user picks a parent folder;
  the `<project>-stella-export` name is revealed only in the
  success dialog. On collision the warning shows the full path
  but offers no overwrite or rename (overwrite itself is T10).
- **Fix:** Fix the README claim (weights arrive with T3; until
  then the README says recipe + checkpoints). Disable Export
  until a project is selected (Import needs no selection and stays
  enabled). Show the package name in the export dialog before the
  user picks the folder (or in the picker title).
- **Done:** The README no longer claims weights in a v0.1 package;
  Export is disabled with no project selected; the export dialog
  shows the package name before the folder is picked. Tests:
  button enabled-state, dialog shows the name.

---

## Coverage map

Every finding ID from the audit, and the task(s) covering it. Nothing
dropped.

| Finding | Task(s) | Notes |
|---|---|---|
| W1 — import not atomic, orphan profile | T1 | Atomic import / rollback |
| W2 — manifest field types never validated | T1 | Strict schema validation |
| W3 — config.json required but never read | T5 | One settings source of truth |
| W4 — profile block silently discarded | T4 | Merge, don't discard |
| W5 — stella_version written but never checked | T2 | Versioned format + version check |
| W6 — weights/ never imported | T2, T3 | T2 format side (first-class member); T3 copy side |
| W7 — no profile export | T15 | Profile export (merged with audit #1 T12) |
| W8 — dataset never copied, absolute refs break | T6 | Dataset in the package decision |
| W9 — no integrity checks | T9 | Checksums + sizes |
| W10 — timestamps lost | T11 | Preserve created/updated + exported_at |
| W11 — no overwrite/merge/rename on collision | T10 | Collision options |
| W12 — import never checks the base exists | T8 | Base-health check on import |
| W13 — import result names not normalized | T1 | Normalize slug once, at import start |
| W14 — no size/disk awareness | T19 | Size report + disk check |
| W15 — top README overclaims the export | T20 | README wording |
| U1 — import success message overwritten | T13 | Confirmation survives the refresh |
| U2 — no import preview or confirmation | T7 | Preview dialog |
| U3 — export enabled with nothing to export | T20 | Disable until a project is selected |
| U4 — no progress, no cancel | T14 | Background thread + progress + cancel |
| U5 — failed import leaves GUI stale | T14 | Refresh on failure too |
| U6 — export dialog never shows package name | T20 | Show the name before the folder pick |
| U7 — no warning when profile already exists | T4, T7 | T4 merge choice; T7 preview warning |
| G1 — no package format versioning policy | T2 | Versioned format |
| G2 — no settings-only / recipe export | T17 | Recipe export (merged with audit #2 T17) |
| G3 — no profile-level package kind | T2, T15 | T2 defines the kind; T15 builds it |
| G4 — no single-file package | T16 | .stella zip |
| G5 — no verify-only path | T12 | Verify command |
| G6 — no provenance or history | T18 | Source machine + history (builds on T11) |
| G7 — no dataset bundling option | T6 | Copy-in option + locate repair |
| D1 — settle the package format | T2 | |
| D2 — validate the manifest schema strictly | T1 | |
| D3 — make import atomic | T1 | |
| D4 — merge, don't discard, the profile block | T4 | |
| D5 — round-trip weights/ | T3 | |
| D6 — one source of truth for settings | T5 | |
| D7 — make the dataset part of the package decision | T6 | |
| D8 — checksums + sizes in the manifest | T9 | |
| D9 — collision options | T10 | |
| D10 — import preview dialog | T7 | |
| D11 — preserve timestamps | T11 | |
| D12 — a verify command | T12 | |
| D13 — a single-file package option | T16 | |
| D14 — keep the import confirmation visible | T13 | |
| D15 — base-health check on import | T8 | |

**Coverage check:** 15 weaknesses + 7 UI flaws + 7 gaps + 15 design
suggestions = 44 findings. All 44 appear in the map above, each with
at least one task. 20 tasks total: 1 P0 (T1), 7 P1 (T2–T8),
7 P2 (T9–T15), 5 P3 (T16–T20).

**Dependency order (within the priority order above):** T1 before T2
(the version check is enforced in `verify_export` alongside the
schema validation); T2 before T3 (weights round-trip lands with the
version check), T15 (profile export uses the profile kind), and T17
(recipe export uses the recipe kind); T4 before T7 (the preview
shows the merge choice); T1, T2, and T9 before T12 (the verify
command runs the full verification); T11 before T18 (provenance
builds on the `exported_at` stamp); T15 and T17 fold into the merged
list's profile-export and recipe-export tasks (see the merged list).
