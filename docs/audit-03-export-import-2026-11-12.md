# STELLA Audit #3 — Export / Import

**Audited:** 2026-11-12 evening, against the v0.1 tree as shipped
(commit e28db915, Release v0.1). Scope: everything an export package
is and does — the package format, `stella/export.py` in full, the
export/import paths in `stella/gui.py` and `stella/cli.py`, and the
export/import tests. Profiles were #1, projects #2; the window as a
whole (#4), the CLI as a whole (#5), the installer (#6), and
MetaMorphAi (#7) get their own audits.

**Method:** read `stella/export.py` (192 lines) in full, the
export/import handlers in `gui.py` and `cli.py`, and
`tests/test_export.py`, `tests/test_cli.py`, `tests/test_gui.py`;
probed live behavior with scratch homes under `/tmp` (model-level
probes plus a driven offscreen GUI window) and real CLI subprocess
runs. Every weakness below was verified by probe or direct code
citation. Probe scripts: `/tmp/export-probes.py` and
`/tmp/export-gui-probes.py` (scratch, not shipped).

**Design intent (from the brief):** a finished project exports as a
usable package. The merged task list flags T18 (profile export) and
T32 (recipe export) to land alongside/after this audit's work "to
avoid two package formats" — so this audit also settles what the
package format is today and what it must become (see §5, G1/G3 and
§6, D1).

---

## 1. Features and functions

### The package (`export.py`)

- An export is a **folder**, `<project>-stella-export/`, created
  inside a destination directory the user picks:
  - `manifest.json` — the whole record: `stella_version`,
    `kind: "stella-export"`, a `profile` block (name, display_name,
    role, ollama_tag, base_ref, processor, config, dependencies)
    and a `project` block (name, display_name, dataset_ref,
    settings, metamorph block, status).
  - `config.json` — the training settings, byte-identical to
    `manifest.project.settings` (probed: the two dicts compare
    equal).
  - `README.md` — human summary: display names, role, base,
    metamorph mode, dataset, status, contents list, import
    instructions.
  - `weights/` — contains only `README.txt`, a placeholder note
    saying no weights exist yet and the folder ships empty on
    purpose.
  - `checkpoints/` — copied from the project, files and
    subdirectories, if any exist; created empty otherwise.
  - `notes.md` — the project's notes, copied if present.
- Granularity is **exactly one project**. There is no
  `export_profile` function, no profile-level export, no
  whole-profile export, and no settings-only export. A profile
  with no projects cannot be exported at all (probed: the API
  takes `(store, profile, project, dest)` and there is no other
  entry point).
- Export refuses to overwrite: if the output folder already
  exists, it raises `StellaError("export folder already exists")`
  (`export.py:37`). No `--force`, no overwrite prompt.
- Export creates the destination tree (`mkdir(parents=True)`,
  `export.py:39`) and writes the manifest/config with sorted keys.

### Import (`export.py`, `verify_export` + `import_export`)

- `verify_export` checks: `manifest.json` exists and parses as
  JSON, `kind == "stella-export"`, profile and project are dicts,
  both names are valid slugs, the metamorph mode is one of
  `morph`/`compress`/`both`, and `config.json` exists. It does
  **not** check `stella_version`, field types, or `config.json`
  contents.
- `import_export` recreates the profile if missing (same slug,
  role, base, config, processor, dependencies from the manifest)
  and reuses it if present; creates the project (settings merged
  over the defaults, metamorph mode + notes, status applied after
  creation); copies checkpoints (files and subdirectories) and
  notes. It does **not** copy `weights/`. It returns
  `{"profile", "profile_existed", "project"}`.
- Import refuses a duplicate project (`StellaError`, from
  `create_project`). Import ignores the package folder's name
  entirely — it reads the manifest.
- The dataset is never copied: `dataset_ref` is carried as a
  string only.

### GUI (`gui.py:172-180`, `562-597`)

- Two buttons in the bottom bar, always enabled: "Export project"
  and "Import package".
- Export needs a selected project (otherwise a warning dialog:
  "Pick a project to export."), then a folder picker starting at
  the home directory. Success: status-bar message plus an
  information dialog with the full output path. Failure: warning
  dialog with the error.
- Import opens a folder picker, imports immediately with no
  preview or confirmation, then selects the imported
  profile/project and refreshes the lists. Success feedback is a
  status-bar message only (and see U1: it is overwritten at once).
  Failure: warning dialog with the error.
- Export and import run synchronously in the button-click handler
  — no progress indicator, no cancel, no background thread.

### CLI (`cli.py:48-58`)

- `stella export <profile> <project> <dir>` — prints
  `Exported to <path>`.
- `stella import <export-dir>` — prints
  `Imported project '<project>' into profile '<profile>'`.
  It does not print whether the profile already existed.
- No `verify` command: `verify_export` exists but no CLI surface
  exposes it. No profile export, no overwrite flag.
- `main` catches only `StellaError` (`cli.py:136-138`); any other
  exception escapes as a raw traceback.

### Tests covering export/import

- `test_export.py` (11 tests): package structure, checkpoint
  copy, refuse-existing-dir, missing project, verify good /
  not-an-export / bad metamorph / bad JSON, round-trip into a
  fresh home (profile + project + settings + notes), import into
  an existing profile, duplicate-project rejection.
- `test_cli.py`: CLI export + import round-trip, CLI export of a
  missing project.
- `test_gui.py`: **zero** export/import tests — the buttons are
  never driven.
- No test covers: manifest field types, `stella_version`
  handling, `weights/` behavior, `config.json` disagreement,
  profile-block discard on second import, timestamps, folder
  rename, paths with spaces, absolute dataset refs, truncated
  checkpoints, partial-import failure, or any GUI feedback.

---

## 2. Strengths

1. **Round-trip fidelity on the happy path is genuinely good.**
   Probed field-by-field: every profile field (display name, role,
   tag, base ref, processor, config, dependencies), settings
   (including a non-default rank and lr), metamorph mode +
   notes, status, dataset ref, notes, and checkpoints — files
   **and** subdirectories — survive export → import into a fresh
   home byte-for-byte.
2. **Slug validation on import is airtight.** Probed:
   `../evil`, `my project` (space), and a missing profile name are
   all rejected with clear errors. A hostile manifest cannot climb
   out of the home through a name.
3. **Folder-name independence.** Import reads the manifest, not
   the folder: a renamed package (no `-stella-export` suffix), a
   moved package, and paths with spaces all import fine (probed).
4. **Tolerant of missing optional parts.** A package missing
   `README.md`, `notes.md`, `checkpoints/`, or `weights/` still
   imports (probed all four) — only the manifest and `config.json`
   are required.
5. **The weights placeholder is honest.** `weights/README.txt`
   says plainly that no weights exist yet and the folder ships
   empty on purpose — the package itself never pretends otherwise.
6. **Export refuses to overwrite.** An existing export folder is
   never silently clobbered.
7. **Duplicate import is refused cleanly** — a `StellaError`
   with a clear message, no partial project left behind.
8. **Uppercase names normalize.** A manifest naming the profile
   `LFM3-Tool` imports as `lfm3-tool` (probed) — the slug rules
   are enforced on the way in.
9. **The manifest is plain JSON**, human-readable and
   hand-editable, matching Stella's "read or fix it by hand"
   design. Extra/unknown fields are ignored, which leaves room
   for forward-compatible additions.
10. **Good happy-path test coverage** (11 export tests + CLI
    round-trip) for a v0.1.

---

## 3. Weaknesses (all verified)

### W1 — Import is not atomic: a bad manifest leaves an orphan profile (P0)

`import_export` creates the profile first (`export.py:152`), then
creates the project (`export.py:164`). If project creation fails,
the profile stays. Probed: a manifest whose `settings` is the
string `"rank 8"` raised a raw `ValueError` — and the fresh home
was left with a profile `lfm3-tool` containing nothing. The
profile was created from the same untrusted package that then
failed; the user gets an error *and* a stray empty profile, with
nothing saying the two are connected. The failure modes that
trigger this are all in W2.

### W2 — Manifest field types are never validated: raw crashes on a hand-edited package (P0)

`verify_export` (`export.py:110-133`) checks the manifest is a
dict, the kind, the names, and the metamorph *mode* — but never
the *types* of any field. Probed, each against a hand-edited
manifest:

- `metamorph` as a string or int → `AttributeError: 'str' object
  has no attribute 'get'` at `export.py:128` (`.get` called on a
  non-dict). No partial state (it fails in verification), but a
  raw crash.
- `settings` as a string → raw `ValueError` from
  `merged.update(settings)` (`model.py:298`), after the profile
  was created (see W1).
- profile `config` as a string → raw `ValueError` from
  `dict(config)` (`model.py:186`).
- `dependencies` as a string → **silently accepted and
  corrupted**: `"torch"` was stored as `['t', 'o', 'r', 'c', 'h']`
  via `list(dependencies)` (`model.py:187`).
- `settings` as a list of pairs → silently accepted
  (`dict.update` accepts pairs).
- `status: "banana"` → silently accepted (same free-text status
  as audit #2, W5).

Neither the GUI nor the CLI catches these: the GUI's import
handler catches only `StellaError` (`gui.py:588-591`), the CLI's
`main` likewise (`cli.py:136-138`). Probed in the driven GUI: the
`ValueError` escaped the handler, **no warning dialog appeared at
all**, and the list showed 0 rows while the orphan profile sat on
disk. Probed on the CLI: a raw traceback, exit 1, no `stella:`
prefix. Import is the trust boundary — packages come from other
machines, other people, and hand-edits — and it is the one place
Stella must never crash on bad input.

### W3 — `config.json` is required but never read: two sources of truth (P1)

`verify_export` rejects a package missing `config.json`
(`export.py:131-132`), but nothing ever reads the file — import
takes settings from the manifest only. Probed: a package with
**invalid JSON** in `config.json` imports fine; a package whose
`config.json` says rank 999 imports with rank 16 (the manifest's
value). So the file is simultaneously mandatory and meaningless.
Worse, it invites exactly the wrong edit: a user who opens the
file named "config" and changes a setting has changed nothing,
and nothing tells them.

### W4 — The imported profile block is silently discarded when the profile exists (P1)

If the profile already exists, `import_export` reuses it and
never looks at the manifest's profile block (`export.py:143-151`).
Probed: importing into a home whose `lfm3-tool` had tag
`other:9b` and role `driver` left the tag and role untouched —
the package's `lfm3:1.7b` / `fast` were dropped without a word.
Probed further: exporting two projects from one profile, changing
the tag between exports, then importing both into a fresh home —
the **first** package's tag won and the second package's profile
block was discarded. No warning, no diff, no merge, no choice.
Because export is one-project-at-a-time (W7), this is the normal
way a multi-project profile moves between machines — so the
normal path silently drops profile data.

### W5 — `stella_version` is written but never checked (P1)

The manifest carries `stella_version` (`export.py:42`) and
nothing reads it. Probed: a manifest claiming version `99.0`
imports fine; a manifest with the field deleted imports fine.
There is no supported-version range, no "this package needs a
newer Stella", no migration path. Combined with W6 this is a
live forward-compat hazard: the first v0.2 package carrying real
weights will import into v0.1 and lose the weights silently,
because v0.1 has no way to know the package is newer than it.

### W6 — `weights/` is never imported (P1)

Import copies checkpoints and notes only (`export.py:174-187`);
`weights/` is not mentioned. Probed: a package containing
`weights/adapter.safetensors` imported successfully — and the
imported project has **no** `weights/` directory at all. The
payload the whole program exists to produce has no round-trip.
Today that costs nothing (v0.1 ships no weights), but the format
must be settled *before* v0.2 puts weights in the package, or
every v0.1 import of a v0.2 package will silently eat the
fine-tune. See D1.

### W7 — No profile export, and no whole-profile export (P1)

Export is one project only. A profile with no projects cannot be
exported, backed up, or shared at all — there is no
`export_profile`, no CLI command, and the GUI Export button
needs a selected project. A profile with N projects must be
exported N times, each package carrying a full duplicate of the
profile block (which feeds W4). This is the merged task list's
T18 (A1-G4), flagged to land with this audit's format work.

### W8 — The dataset is never copied, and absolute refs break on import (P1)

Export carries `dataset_ref` as a bare string; no dataset file
enters the package (probed: no trace of the dataset file in the
package tree). A project whose dataset is
`/home/joshua/data/forge-traces.jsonl` exports that absolute path
— into the manifest **and** the README — and the imported project
points at the same path on a machine where it may not exist.
Import never checks whether the referenced path exists and never
warns. The package is portable; its most important input is not.
(Cross-ref audit #2, W6: the dataset ref is unvalidated text.)

### W9 — No integrity checks on anything in the package (P2)

The manifest carries no checksums, sizes, or file list. Probed:
a checkpoint truncated from 800 bytes to 4 (`FAKE`) imported
without complaint — the corrupted file now sits in the home as if
it were a real checkpoint. A half-copied package, a truncated
download, a flipped bit: import cannot tell.

### W10 — Timestamps are lost (P2)

`created` and `updated` are not in the manifest (manifest keys
are exactly `kind`, `profile`, `project`, `stella_version`).
Import stamps fresh timestamps (`model.py:188`, `model.py:309`).
An imported project looks brand new; its history — when it was
made, when it last changed — is gone. (In the probe the source
and imported timestamps matched only because both ran inside the
same second; the manifest carries no timestamp to preserve.)

### W11 — No overwrite, merge, or rename on collision (P2)

Export refuses an existing folder and import refuses an existing
project, and that is the end of it: no `--force`, no "replace",
no "import as a copy under a new name", no merge. Every collision
is a dead end that sends the user out to a file manager to delete
or rename by hand — for a user who works from his phone screen,
that is a real friction point, not a nicety.

### W12 — Import never checks the base exists locally (P2)

Probed: a package whose profile claims `ollama_tag:
"not-a-real-model:99"` imports silently and the profile looks
perfectly healthy — until training or Ollama use fails. A package
arriving from another machine is exactly when the base is most
likely to be missing. (Cross-ref audit #1, W11: no health
indicator for missing tags.)

### W13 — The import result names are not normalized (P2)

`import_export` returns the manifest's raw names
(`export.py:143`: `slug = prof["name"]`), while the store
lowercases them. Probed: importing a package named `Zebra-Proj`
returned profile `Zebra-Proj` but stored `zebra-proj`. In the
GUI, `import_package` sets the selection from the returned names
(`gui.py:593-594`) and `refresh_profiles` matches rows by exact
name — so the imported profile is not found, selection falls back
to row 0, and the window ends up showing the **wrong profile**
(probed in the driven GUI: `aaa-first` selected instead of
`zebra-proj`, project `aaa-job` instead of the imported one).

### W14 — No size or disk awareness on export (P3)

Export copies everything with no total size, no disk-space check,
and no report of how big the package is. In v0.1 checkpoints are
tiny, so this is unobservable — but v0.2 checkpoints and weights
will be large, and the copy already runs synchronously in the
button handler (see U4). The first GB-scale export will freeze
the window with no warning and no progress.

### W15 — The top README overclaims what an export is (P3)

`README.md:43-44`: "a finished fine-tune exports as a usable
package (manifest, config, weights, checkpoints)". v0.1 exports
no weights — the package's own `weights/README.txt` says so
honestly, but the top README lists weights as package content and
calls the result "usable". A package with no weights is a recipe
plus checkpoints, not a usable fine-tune. The claim should wait
for the weights.

---

## 4. UI flaws (verified)

- **U1 — The import success message is overwritten before the
  user can read it.** `import_package` says "Imported X into Y"
  (`gui.py:595`), then immediately calls `refresh_profiles`
  (`gui.py:596`), whose selection cascade calls `_say` again with
  "Profile: … — project: …". Probed in the driven GUI: after a
  successful import the status bar reads "Profile: lfm3-tool —
  project: tool-calls." — the import confirmation never survives.
  Export gets a dialog; import gets a message that erases itself.
- **U2 — No import preview or confirmation.** One click imports.
  The user never sees what the package contains — profile,
  project, tag, version — before it lands. Pick the wrong folder
  and the first sign is a new profile in the list (or an error).
- **U3 — Export is enabled with nothing to export.** Both
  buttons are always enabled (probed). Export with no selection
  warns *after* the click ("Pick a project to export.") instead
  of disabling the button until a project is selected.
- **U4 — No progress, no cancel, on a synchronous copy.** Export
  and import run in the button-click handler. A v0.2-scale
  checkpoint copy will freeze the window with no progress bar and
  no way to stop it.
- **U5 — A failed import leaves the GUI stale.** After the
  raw-crash failure (W2), the orphan profile exists on disk but
  the list shows 0 rows — `refresh_profiles` runs only on the
  success path (`gui.py:596`). The user cannot even see the stray
  profile the failure left behind.
- **U6 — The export dialog never shows the package name.** The
  user picks a parent folder; the `<project>-stella-export` name
  is revealed only in the success dialog. On collision the
  warning shows the full path but offers no overwrite or rename.
- **U7 — No warning when the imported profile already exists.**
  The UI face of W4: importing into an existing profile silently
  drops the package's profile block, and nothing in the window
  says so — not even the `profile_existed` flag import already
  returns.

---

## 5. Gaps (against the design intent)

- **G1 — No package format versioning policy.** `stella_version`
  is stamped on every manifest and means nothing: no supported
  range, no "too new" rejection, no migration. **Format verdict
  (settling the T18/T32 flag):** what the package is today is a
  *single-project folder*: manifest (one profile block + one
  project block) + a duplicate `config.json` + README +
  placeholder-only `weights/` + checkpoints + notes, with no
  version semantics, no checksums, no timestamps, no provenance.
  What it must become before v0.2 ships weights: a *versioned*
  format — a format version with a supported range enforced on
  import (reject newer with a clear message), `weights/` as a
  first-class round-tripped member, one settings source of truth,
  checksums, and named package kinds (see D1). The version check
  must land *with or before* the first weights-carrying export:
  without it, v0.1 will silently eat v0.2 weights.
- **G2 — No settings-only / recipe export** (audit #2, G6;
  merged task list T32): whole package or nothing. There is no
  way to share a dataset + settings recipe without checkpoints.
- **G3 — No profile-level package kind** (audit #1, G4; T18):
  the manifest holds exactly one project, so the format cannot
  express "a profile with all its projects". Profile export needs
  its own package kind (`kind: "stella-profile-export"`), not a
  project package with the project block left out.
- **G4 — No single-file package.** A package is a folder;
  sharing means zipping by hand. No `.stella` zip (or tar) form
  that import can read.
- **G5 — No verify-only path.** `verify_export` exists but no
  CLI command or GUI action exposes it — the only way to check a
  package is to import it.
- **G6 — No provenance or history.** No `exported_at`, no source
  machine, no record of what was exported where or imported from
  where. A package found on disk cannot say when it was made or
  from what.
- **G7 — No dataset bundling option.** Export offers no "include
  the dataset" choice (with its size shown); import offers no
  "point me at the dataset on this machine" repair. The dataset
  question is simply not part of the package (see W8).

---

## 6. Innovation and design suggestions

- **D1 — Settle the package format (the T18/T32 seam).** Give
  the format a real version, separate from the app version
  (`format: 1`), with a supported range enforced on import and a
  clear "this package needs a newer Stella" message. Define the
  package kinds up front — project package (today's), profile
  package (T18), recipe package (T32) — as distinct `kind`
  values sharing one manifest shape, so T18 and T32 never become
  two formats. `weights/` becomes a first-class round-tripped
  member in the same pass (D5).
- **D2 — Validate the manifest schema strictly in
  `verify_export`.** Types for every field: settings and config
  must be dicts, dependencies a list, metamorph a dict, dataset
  ref and status strings; reject an unknown `stella_version`
  major; every failure a `StellaError` with a plain message.
  Nothing downstream should ever see a manifest field it has not
  already validated.
- **D3 — Make import atomic.** Validate everything first, then
  write; on any failure, roll back (remove the profile/project
  just created) or stage the whole import in a temp directory and
  move it into place last. A failed import must leave the home
  exactly as it was.
- **D4 — Merge, don't discard, the profile block on import.**
  When the profile exists, compare tag / role / base with the
  manifest: identical → silent; different → warn and let the
  user pick keep-local or take-package. Never silently drop
  profile data.
- **D5 — Round-trip `weights/`.** Copy the weights folder on
  import (minus the placeholder note) and treat it as the
  payload. Land with D1's version check so no older Stella can
  silently drop it.
- **D6 — One source of truth for settings.** Drop `config.json`
  from the package (the manifest already holds the settings) or
  make import read it and cross-check against the manifest.
  Never require a file you never read.
- **D7 — Make the dataset part of the package decision.** At
  export, offer "copy the dataset in" (with its size) or keep
  the reference; at import, check the referenced path exists and
  warn — with a "locate it on this machine" repair — when it
  does not.
- **D8 — Checksums + sizes in the manifest.** A sha256 (or at
  least a byte size) per file, verified on import, so a
  truncated checkpoint or half-copied package fails loudly
  instead of poisoning the home.
- **D9 — Collision options.** Export: overwrite prompt / force
  flag. Import: "import as a copy" (new slug) or replace with a
  backup of the old project. Collisions should be choices, not
  dead ends.
- **D10 — Import preview dialog.** Before importing, show
  profile, project, tag, version, and contents (checkpoints,
  weights, dataset ref) — with the existing-profile warning when
  it applies — and let the user confirm or cancel.
- **D11 — Preserve timestamps.** Carry the original `created` /
  `updated` in the manifest and restore them on import, plus an
  `exported_at` stamp for provenance.
- **D12 — A verify command.** `stella verify <dir>` on the CLI
  (and a "Check package" action in the GUI) that runs the full
  verification — schema, version, checksums — without importing.
- **D13 — A single-file package option.** Export to a `.stella`
  zip; import reads zips and folders alike. One file to email,
  one file to back up.
- **D14 — Keep the import confirmation visible.** Don't let the
  refresh overwrite the status message (say it after the
  refresh, or add an import success dialog matching export's).
- **D15 — Base-health check on import.** Warn when the profile's
  Ollama tag is not installed on this machine (ties to audit #1,
  D1) — the moment the user most needs to know.

---

## 7. Recommended improvements (his to direct)

- **P0:** D2 manifest schema validation (W2) + D3 atomic import
  (W1) — one trust-boundary fix; a package must never crash
  Stella or leave partial state.
- **P1:** D1 settle the package format (W5, W6, G1, G3 — the
  T18/T32 seam; the version check must land before the first
  weights-carrying export); D4 profile-block merge (W4); D6 one
  settings source of truth (W3); D7 dataset handling (W8); D10
  import preview (U2, U7); D5 weights round-trip (W6); D15
  base-health check (W12); W13 result normalization (fold into
  D2/D3 — normalize the slug once, at import start).
- **P2:** D8 checksums (W9); D9 collision options (W11); D11
  timestamps (W10); D12 verify command (G5); D14 import
  confirmation (U1); U4 progress/cancel + U5 refresh-on-failure;
  the profile export itself (W7, T18) once D1 defines its
  package kind.
- **P3:** D13 single-file package (G4); G2 recipe export (T32)
  once D1 defines its kind; G6 provenance; W14 size/disk
  awareness; W15 README wording; U3/U6 polish.

## 8. Out of scope for this audit

Profiles (#1), projects (#2), the window as a whole (#4), the CLI
as a whole (#5), installer + icon (#6), MetaMorphAi hooks (#7),
and the training engine (Item 3, in flight — audited after v0.2
ships). W8 shares its fix with projects (A2-W6/D6 dataset
validation); W12 with profiles (A1-W11/D1 health indicator);
W7/G3 and G2 are the merged task list's T18 and T32, whose
package kinds this audit defines in D1. The version check in D1
is the one finding with a deadline: it must land before v0.2
ships weights, or v0.1 imports will silently drop them.
