# STELLA Audit #7 — MetaMorphAi hooks: Task List

**Source:** [audit-07-metamorph-2026-11-12.md](audit-07-metamorph-2026-11-12.md)
(MetaMorphAi hooks audit, 2026-11-12, against v0.2 / commit 9a821e07 —
the report was written 2026-11-13 from a fresh run after the first
auditor was interrupted overnight and left no file).

**This file is a list only.** Nothing here has been fixed or built.
Each task turns one or more audit findings into work with a verifiable
"done". Priorities follow the audit's section 8; within a priority,
a fix comes before the polish that depends on it.

**Finding IDs carry the A7 prefix** (audit #7), matching the merged
list. Cross-references to earlier audits keep their own prefixes
(A2-, A3-, A5-).

**Priority key:** P0 = data loss / silent failure, fix first.
P1 = real functional defect or daily friction. P2 = missing capability
or inconsistency. P3 = polish, display, and scale.

**Effort key:** S = a focused change in one or two files, a day or
less. M = a change across model + GUI + tests, or a small design
decision plus implementation. L = a multi-part build or a design that
needs Joshua's direction on scope first.

**Counts:** 19 tasks — 0 P0, 7 P1, 7 P2, 5 P3.

**Shared fixes with earlier audits:** four findings share their fix
with earlier work and are built once, not twice. The string-metamorph
verify crash (A7-W5 — audit #3's W2, re-confirmed, line moved 128 →
141); the unreachable metamorph notes (A7-W8/U3 — audit #2's W10,
unchanged in v0.2); the name-only New Project (A7-W9/U4 — audit #2's
W12, unchanged in v0.2); and the CLI mode change (A7-G7 — the
metamorph half of the CLI-update gap, A5-G1). In this standalone file
they appear as audit #7 tasks (T8, T9, T10, T14); the merged list
([stella-audit-task-list-123.md](stella-audit-task-list-123.md))
folds them into the single shared tasks. The GUI string-metamorph
crash (A7-W4) is the GUI half of audit #5's W2 (the CLI instance) —
related, not shared: the CLI half is audit #5's task when its list
merges, the GUI half is T4 here.

---

## P0 — fix first

— (none). No data loss and no crash on any normal path: the crashes
found (A7-W2–A7-W5) all need a hand-corrupted `project.json` or
manifest, and the inert mode is documented in the README, not hidden.

---

## P1 — functional defects and daily friction

### T1 — Define what each mode means, in writing, before building the codec

- **Covers:** A7-W1, A7-W7, A7-W10, A7-D1
- **Effort:** S
- **Problem:** The mode does nothing, for either reading. No code
  path in `train.py`, `probe.py`, or `gguf.py` references metamorph
  at all (grep -c = 0 for each). Setting a project to `compress`
  does not change its training, its probe, its GGUF export, or its
  package; setting it to `morph` does not create, track, or manage
  variants. Probed behaviorally (P8): identical-init tiny training
  runs in `morph` and `compress` gave final loss
  `5.564785480499268` for both, 3 steps, 4,096 trainable params,
  same target modules, and byte-identical adapter weights (SHA-256
  prefix `e3a36ab43103649b` for both). `both` is a third label, not
  morph-plus-compress: no code branches on it, and nothing defines
  what the combination would do (A7-W7). The code's own honesty
  marker is stale: `model.py:37` comments `METAMORPH_MODES` with
  "structure only in v0.1 — no codec yet" while the tree is v0.2
  (A7-W10). This is P1, not P0: the README documents the inert mode
  honestly, nothing is lost, and nothing crashes. But it is the
  defining weakness of the component — the name MetaMorphAi
  promises two behaviors and the program delivers neither.
- **Fix:** D1 — a short spec in the README (and a code comment
  replacing the stale `model.py:37` line): what `morph` does, what
  `compress` does, what `both` does and in which order. This is a
  writing task, not a code task — and it is the first task: D2/D3/
  D4/D13/D16 cannot be built correctly against an undefined word.
  The honest rule for the spec: if a mode cannot be defined, it
  comes out of the combo rather than shipping as a third kind of
  nothing (define the modes and wire the first real effect, or
  remove the mode).
- **Done:** The README and the code comment define all three modes
  in writing; `both` has a stated order; the stale v0.1 comment is
  gone. Tests: none — verify by reading the spec against the audit.

### T2 — Export must not crash on `metamorph: null` — and must not leave a partial package

- **Covers:** A7-W2, A7-D8, A7-D9
- **Effort:** S
- **Problem:** `export.py:60` uses `proj.get("metamorph", {...})` —
  but `.get`'s default only applies when the key is *absent*. When
  the key is present with value `null`, the manifest gets
  `metamorph: None`, and line 76
  (`manifest['project']['metamorph'].get(...)`) raises
  `AttributeError: 'NoneType' object has no attribute 'get'`
  (probed, P3). Worse, the crash happens *after* `manifest.json`
  and `config.json` are written: the export folder is left behind
  containing exactly those two files — no README, no `weights/`, no
  `checkpoints/`. A second export attempt then fails with "export
  folder already exists" (audit #3's non-atomicity class,
  export-side; cf. A3-W1 for import).
- **Fix:** D8 — read the block through the shared defensive reader
  (built once in T3): null/missing/wrong-type yields the default
  mode instead of a crash. D9 — build every file's content before
  creating the folder, so a bad block fails before any partial
  package exists (same atomicity direction as the import fix).
- **Done:** A project with `metamorph: null` exports cleanly (mode
  defaults to `morph`), or fails before creating anything — never
  a partial folder. Tests: null export, missing-key export,
  no-partial-package on failure.

### T3 — GUI Save must not crash on a missing metamorph key; one defensive reader for the block

- **Covers:** A7-W3, A7-D8
- **Effort:** S
- **Problem:** `update_project` assumes the stored block exists:
  `model.py:341` reads `data["metamorph"]["mode"]` with no guard.
  With the key deleted from `project.json`, a GUI save — which
  always passes a metamorph dict (`gui.py:582`) — raises
  `KeyError: 'metamorph'` (probed, P4 and P7). `save_project`
  catches only `StellaError`, so the exception escapes the Qt
  slot: the save silently does not happen, and the traceback goes
  to a terminal the menu-launched user never sees (Terminal=false).
  With the block set to `null` instead of missing, the same line
  raises `TypeError: 'NoneType' object is not subscriptable`. A
  display-name-only update on the same file works fine — only the
  metamorph path assumes the block. Root cause: `get_project`
  (`model.py:270-276`) setdefaults `name` and `profile` but not
  `metamorph`.
- **Fix:** D8 — `get_project` setdefaults the block, and one
  helper — e.g. `metamorph_mode(project_dict)` returning a valid
  mode or `"morph"` for null/missing/wrong-type — is used by the
  CLI list, the GUI list + detail fill, export, and verify. Built
  ONCE here, in the model layer; T2, T4, T8, and T15 consume it.
- **Done:** A missing or null metamorph key no longer crashes a
  save — the save works and the mode defaults to `morph`; no
  traceback escapes the Qt slot. Tests: missing-key save, null
  save, string-block save.

### T4 — The GUI project list must not die on a string metamorph

- **Covers:** A7-W4, A7-D8
- **Effort:** S
- **Problem:** `gui.py:449` reads the mode with
  `(p.get("metamorph") or {}).get("mode", "morph")`. The `or {}`
  guards `None` and missing — but a *string* is truthy, so a
  hand-edited `"metamorph": "both"` raises `AttributeError: 'str'
  object has no attribute 'get'` inside `refresh_projects` (probed,
  P7). One bad project kills the whole list refresh, so the window
  cannot show *any* project in that profile. The detail fill at
  `gui.py:534` uses the identical expression and crashes identically
  (masked in practice because the list refresh fails first). The
  CLI instance of this exact pattern is A5-W2 (re-confirmed in
  P5); this is the GUI half, which no earlier audit probed.
- **Fix:** D8 — read the mode through the shared defensive reader
  from T3 in the list and the detail fill. The GUI list should
  degrade to a warning row for a bad project, not die for the whole
  profile (A5-D2's prescription, applied to the GUI half).
- **Done:** A string-metamorph project shows as a warning row;
  every other project in the profile lists normally; the detail
  fill does not crash. Tests: string block in the list, string
  block in the detail fill.

### T5 — Fix the tooltip: honest words, one line

- **Covers:** A7-U1, A7-U2, A7-D6
- **Effort:** S
- **Problem:** `gui.py:322-325`, probed verbatim (P7): "MetaMorphAi:
  morph turns the base into variants, compress shrinks how the
  fine-tune is stored, both does both." Present tense, describing
  effects. None of the three clauses is true (A7-W1, A7-W6). This
  is the *only* tooltip in the entire window (A4-U7) — the one
  explanation the GUI offers anywhere is the one that is wrong —
  and it directly contradicts the README's honest "the codec lands
  in a later item." A user who hovers learns the opposite of the
  truth. The project list compounds it (A7-U2): rows read `Display
  name — both` (`gui.py:449-451`) with no indication the suffix is
  a label, so a user reasonably reads "— compress" as "this project
  will compress."
- **Fix:** D6 — replace the present-tense promise with the truth,
  e.g.: "MetaMorphAi mode — a label for now; the morph/compress
  codec lands in a later item." Do not wait for the codec to fix
  the words. Once the tooltip is honest, the list suffix is a fair
  label (A7-U2) — verify that and note it; the suffix itself does
  not change.
- **Done:** The tooltip states the truth; the list suffix is
  unchanged but no longer misleading beside an honest tooltip.
  Tests: tooltip text assertion.

### T6 — Variant lineage for `morph`: spawn + parent record

- **Covers:** A7-G1, A7-D4
- **Effort:** M
- **Problem:** There is no operation that turns a base into a
  variant differently per mode, no way to spawn a variant project
  from another, and no record of which project descended from
  which. "Morphing" today means "a project exists under a profile"
  — true of every project regardless of mode.
- **Fix:** D4 — a project can spawn a variant project (copy
  settings/dataset, new slug, `metamorph.parent` recorded in the
  manifest); the project list shows lineage. This is what "a base
  model morphs into specialized variants" looks like at Stella's
  scale — not a new architecture, a family tree with a spawn
  operation. Depends on T1 (the definitions): `morph` must mean
  something before a spawn operation can implement it.
- **Done:** Spawning a variant creates a project with the parent
  recorded; the list shows the lineage; export carries the parent
  record. Tests: spawn-through, lineage display, parent in the
  manifest.

### T7 — Wire `compress` to real compression: GGUF quant + package compression

- **Covers:** A7-G2, A7-W6, A7-D2, A7-D3
- **Effort:** M
- **Problem:** No quantization choice driven by mode (GGUF always
  defaults to Q4_K_M, `gguf.py:29`); no adapter compression; no
  package compression; no token-level compression ("the same
  meaning in fewer tokens" has no code behind it — no dataset
  tokenization/dedup step at train time). The only real compression
  in Stella (GGUF quantization) is entirely disconnected from the
  mode that names compression. The measurable form: P2 exported the
  same-shaped project in `morph` and `compress` and diffed the
  packages — identical file lists, and the only mode-caused
  differences are the mode string itself. Total bytes: `morph`
  1,643 B, `compress` 1,665 B — the "compress" package is *larger*,
  because the word "compress" is longer than "morph" (A7-W6).
- **Fix:** D2 — `export-gguf` already takes `--quant` and defaults
  to Q4_K_M (`gguf.py:29,142`). One branch: mode `compress`
  defaults the quant a step smaller (e.g. Q3_K_M), `morph` keeps
  Q4_K_M, `--quant` always overrides, and the choice is printed.
  D3 — mode `compress` ships the export as a compressed archive
  (zip) instead of (or alongside) the plain folder; `morph` keeps
  the plain folder as today. Import must accept both forms. Depends
  on T1 (the definitions). The deep token-level codec is T19, not
  this task.
- **Done:** A `compress` project exports GGUF at the smaller quant
  unless `--quant` overrides; a `compress` export is a zip that
  imports; a `morph` project is unchanged. Tests: quant default
  per mode, override wins, zip export/import round-trip.

---

## P2 — missing capabilities and inconsistencies

### T8 — `verify_export` must not crash on a string metamorph (A3-W2, re-confirmed)

- **Covers:** A7-W5, A7-D8
- **Effort:** S
- **Problem:** `export.py:141` uses the same
  `(proj.get("metamorph") or {}).get(...)` shape, so a hand-edited
  manifest with `"metamorph": "both"` raises `AttributeError:
  'str' object has no attribute 'get'` (probed, P5). This is audit
  #3's W2, unchanged except the line number (128 → 141 as the file
  grew).
- **Fix:** D8 — read the block through the shared defensive reader
  from T3, and validate the manifest schema strictly (the merged
  list folds this onto the existing trust-boundary task — audit #3
  T1 — rather than minting a duplicate; the fix is the same D8
  reader).
- **Done:** A string metamorph in a manifest is refused with a
  readable `StellaError`, never a raw `AttributeError`. Tests:
  string-metamorph manifest refused.

### T9 — Metamorph notes reachable: detail-panel field + CLI flag

- **Covers:** A7-W8, A7-U3, A7-D7
- **Effort:** S
- **Problem:** Folded from A2-W10 (unchanged in v0.2). The combo
  edits mode only; the CLI has `--metamorph` but no notes flag; the
  only ways to set notes are hand-editing `project.json` or
  importing a package that already has them. The GUI save at least
  preserves notes it cannot see (the merge at `model.py:338-350`),
  but a field the user can neither read nor write in the program is
  a dead key with a live name — and it sits beside two other notes
  fields (`settings["notes"]`, which nothing reads or writes, and
  `notes.md`, the only visible one), so a hand-editor cannot tell
  which one matters. The UI half (A7-U3): the detail panel shows
  the mode combo and, below it, the `notes.md` editor labeled
  "Notes" — the panel has a notes surface, but it is the *other*
  notes.
- **Fix:** D7 — a small text area under the combo, saved through
  the existing merge (which already preserves notes correctly),
  plus `--metamorph-notes` on `create-project`. Label it distinctly
  from the `notes.md` area ("Why this mode" vs "Project notes") so
  the three-notes confusion does not get worse. (The merged list
  folds this onto the existing three-notes task — audit #2 T12.)
- **Done:** Metamorph notes are readable and editable in the detail
  panel and settable from the CLI; `notes.md` is unchanged; the
  two surfaces are labeled distinctly. Tests: notes save-through,
  CLI flag sets notes.

### T10 — New Project form with dataset + metamorph

- **Covers:** A7-W9, A7-U4, A7-D10
- **Effort:** S
- **Problem:** Folded from A2-W12. The CLI's `create-project` takes
  `--metamorph`; the GUI's New Project asks for a name and nothing
  else, so every GUI-created project starts as `morph` and the user
  must find the combo afterwards to change it — a combo below the
  fold at 1100×680 (A4's fold finding: the detail panel content is
  1289px against a 567px viewport). The mode's one moment of
  relevance — creation, when the user is deciding what this project
  is *for* — is the moment the GUI does not offer it.
- **Fix:** D10 — restating A2-W12's fix for this component: the
  GUI's New Project takes a dataset and a mode, matching the CLI's
  `create-project`. (The merged list folds this onto the existing
  New Project form task — audit #2 T13.)
- **Done:** Create a project from the GUI with a dataset and a
  metamorph mode in one step; blank fields fall back to the
  defaults. Tests: dialog create-through with dataset + mode.

### T11 — Record the mode in training artifacts

- **Covers:** A7-G3, A7-D5
- **Effort:** S
- **Problem:** Adapter, checkpoints, `train_log.jsonl`, and
  `training_summary.json` never record the mode (scanned clean,
  P8). After a run, nothing in the artifacts says which mode the
  project was in when it trained — so when the codec lands, old
  adapters cannot be told apart by mode, and a future "was this
  adapter compressed?" question has no answer in the artifacts.
- **Fix:** D5 — write the project's mode into
  `training_summary.json` (and the adapter config) at train time,
  starting with the next build — before the codec exists. Cheap,
  and it means provenance is already there when the codec needs
  it. Alongside T7 (provenance records what the codec does).
- **Done:** A training run's summary and adapter config name the
  mode the project was in. Tests: mode recorded in artifacts.

### T12 — Mode-version story before the first codec ships

- **Covers:** A7-G4, A7-D12
- **Effort:** S
- **Problem:** `METAMORPH_MODES` is a closed tuple, and
  `verify_export` rejects any mode outside it (`export.py:141-143`).
  Adding a mode later — or a codec version, which is what a real
  codec needs — has no migration path: old Stella would reject new
  packages outright, and `verify_export` never checks
  `stella_version` at all (A3-W5), so there is no version gate for
  a future mode to ride on.
- **Fix:** D12 — carry a codec version in the manifest when the
  codec lands, and make `verify_export` check `stella_version`
  (A3-W5) so old Stella can refuse — cleanly, with a message — a
  package whose mode it does not understand, instead of crashing
  or silently misreading it. Settle this with the first codec
  release (T7), or the first codec release breaks old imports.
- **Done:** A package with an unknown mode or codec version is
  refused with a readable message, not a crash. Tests:
  unknown-mode refusal, version-gate refusal.

### T13 — Corrupt-block tests for every reader

- **Covers:** A7-G5, A7-D11
- **Effort:** S
- **Problem:** The suite tests valid modes, a bad mode string, and
  the round-trip — but no test covers `null`, missing-key, or
  wrong-type metamorph in `project.json` or a manifest. All three
  crashes in this audit (A7-W2, A7-W3, A7-W4) live in untested
  paths, and A7-W5's re-confirmation shows the one tested corrupt
  case (bad mode string in the manifest, `test_export.py:56-59`)
  does not cover the wrong-*type* case next to it.
- **Fix:** D11 — `null`, missing-key, and wrong-type metamorph in
  `project.json` and in manifests, exercised against the CLI list,
  the GUI list + detail fill + save, export, and verify. Pins T3's
  reader. After T3, T2, and T4 (the defensive reader first, then
  the tests that pin it).
- **Done:** One test per corrupt variant per reader; all pass.
  Tests: this task IS the tests.

### T14 — CLI: change a mode after creation

- **Covers:** A7-G7, A7-D15
- **Effort:** S
- **Problem:** `--metamorph` is create-time only; the CLI has no
  update command at all (A5-G1 / A1-W9 territory), so a CLI-only
  user who wants to change a project's mode must hand-edit JSON or
  open the window.
- **Fix:** D15 (update half) — a `stella update` / `stella show`
  path so a CLI user can change a mode without hand-editing JSON.
  Rides the general CLI-update gap (the merged list folds this onto
  the existing CLI-parity task — the `update-project` command takes
  a `--metamorph` flag). The help-text half of D15 is T17.
- **Done:** A CLI user can change a project's mode after creation
  without hand-editing JSON. Tests: update-project --metamorph
  changes the stored mode.

---

## P3 — polish, display, and scale

### T15 — Validate the notes type at both write points

- **Covers:** A7-W11, A7-D8, A7-D11
- **Effort:** S
- **Problem:** `create_project` (`model.py:314`) and
  `update_project` (`model.py:347-350`) validate the mode but never
  the notes: `notes: 123` and `notes: 456` are stored verbatim
  (probed, P9). Nothing crashes today — the GUI never reads notes,
  and JSON round-trips an int fine — but the manifest's contract
  says notes is text, and a future notes UI (T9) reading an int
  into a text field will crash or render garbage.
- **Fix:** One `isinstance` check at both write points (D8); tests
  ride the D11 suite (T13).
- **Done:** Non-string notes are rejected with a `StellaError` at
  create and update. Tests: int notes rejected at both points.

### T16 — Show the mode in the Train panel

- **Covers:** A7-U5, A7-D14
- **Effort:** S
- **Problem:** Training is where a user would expect the mode to
  act — and the Train panel is silent about it. A user who set
  `compress`, starts a run, and watches the log sees no note that
  compression does not apply to the run. The mode is visible in the
  detail panel and invisible where its effect would be expected, so
  the run's silence reads as "working."
- **Fix:** D14 — one line ("Training as `compress` — mode is a
  label in v0.2") until the codec lands, then the real per-mode
  behavior summary.
- **Done:** The Train panel names the mode and its current
  (non-)effect during a run. Tests: panel shows the mode line.

### T17 — CLI help strings for `--metamorph`

- **Covers:** A7-U6, A7-D15
- **Effort:** S
- **Problem:** `cli.py:248-250` declares the flag with `choices`
  but no `help`, so `stella create-project --help` shows the three
  words and no meaning (noted in A5's design list, line 687). With
  A7-U1's tooltip as the only explanation anywhere, the CLI user
  gets even less.
- **Fix:** D15 (help half) — real `help=` text on `--metamorph`
  (what the modes mean, with the honest "label for now" note). The
  update half of D15 is T14.
- **Done:** `stella create-project --help` explains the modes
  honestly. Tests: help output contains the mode meanings.

### T18 — Per-mode training defaults, after the mode definitions

- **Covers:** A7-G6, A7-D13
- **Effort:** S
- **Problem:** Every mode gets identical `DEFAULT_SETTINGS`
  (`model.py:44-57`). A `compress` project might sensibly default
  to a lower rank; a `morph` project to variant-friendly settings.
  Today the mode cannot even express a preference.
- **Fix:** D13 — once T1 defines the modes, let `compress` suggest
  a lower rank and `morph` suggest variant-friendly settings —
  suggestions in the New Project form, not silent overrides.
- **Done:** The New Project form suggests per-mode defaults;
  accepting or overriding both work. Tests: defaults suggested per
  mode.

### T19 — The token-level codec: a named later item

- **Covers:** A7-D16
- **Effort:** L
- **Problem:** "The same meaning in fewer tokens" at train time —
  dataset tokenization, dedup, and compression-aware training — is
  the deep reading of the codec and the hardest part. It has no code
  behind it anywhere, and no design behind it either.
- **Fix:** D16 — name it as a later item with its own design pass;
  do not let T7's easy wins pretend it is done. After T1 (the
  definitions) and T7 (the easy wins prove the wiring).
- **Done:** A design doc for the token-level codec exists (or the
  codec itself, if the design pass is done in this task — decide at
  build time); T7's wins do not claim it. Tests: per the design
  pass.

---

## Coverage map

Every finding ID from audit #7, and the task(s) covering it.
Nothing dropped.

| Finding | Task(s) | Notes |
|---|---|---|
| A7-W1 — the mode does nothing, for either reading | T1 | |
| A7-W2 — export crashes on `metamorph: null`, leaves a partial package | T2 | |
| A7-W3 — GUI Save crashes with KeyError on a missing metamorph key | T3 | |
| A7-W4 — GUI project list crashes on a string metamorph | T4 | |
| A7-W5 — `verify_export` crashes on a string metamorph | T8 | A3-W2 re-confirmed |
| A7-W6 — `compress` package is 22 bytes BIGGER | T7 | |
| A7-W7 — `both` has no combined semantics | T1 | |
| A7-W8 — `metamorph.notes` unreachable from GUI and CLI | T9 | A2-W10 re-confirmed |
| A7-W9 — GUI New Project is name-only, no metamorph choice | T10 | A2-W12 re-confirmed |
| A7-W10 — stale "structure only in v0.1" comment | T1 | |
| A7-W11 — `notes` accepts any JSON type, unchecked | T15 | |
| A7-U1 — tooltip promises behavior that does not exist | T5 | |
| A7-U2 — project list presents the mode as if it mattered | T5 | |
| A7-U3 — no metamorph-notes field in the detail panel | T9 | |
| A7-U4 — no metamorph choice in New Project | T10 | |
| A7-U5 — Train panel never mentions the mode | T16 | |
| A7-U6 — `--metamorph` has no help string | T17 | |
| A7-G1 — no morph implementation: no variants, no lineage | T6 | |
| A7-G2 — no compression codec anywhere in the pipeline | T7 | |
| A7-G3 — no mode provenance in training artifacts | T11 | |
| A7-G4 — no mode-version story | T12 | |
| A7-G5 — no tests for corrupt metamorph states | T13 | |
| A7-G6 — no per-mode defaults | T18 | |
| A7-G7 — CLI cannot change a mode after creation | T14 | |
| A7-D1 — define what each mode MEANS, in writing | T1 | |
| A7-D2 — wire `compress` to the GGUF quant first | T7 | |
| A7-D3 — compress the export package when mode is `compress` | T7 | |
| A7-D4 — variant lineage for `morph` | T6 | |
| A7-D5 — record the mode in training artifacts now | T11 | |
| A7-D6 — fix the tooltip now | T5 | |
| A7-D7 — metamorph-notes field + CLI flag | T9 | |
| A7-D8 — one defensive reader, used everywhere | T2, T3, T4, T8, T15 | |
| A7-D9 — build the export README before creating the folder | T2 | |
| A7-D10 — New Project form with dataset + metamorph | T10 | |
| A7-D11 — corrupt-block tests for every reader | T13, T15 | |
| A7-D12 — mode-version story before the first codec ships | T12 | |
| A7-D13 — per-mode training defaults, after D1 | T18 | |
| A7-D14 — show the mode in the Train panel | T16 | |
| A7-D15 — CLI help strings + a way to change mode | T14, T17 | |
| A7-D16 — the token-level codec is a named later item | T19 | |

**Coverage check:** 11 weaknesses + 6 UI flaws + 7 gaps + 16 design
suggestions = 40 findings. All 40 appear in the map above, each with
at least one task. 19 tasks total: 0 P0, 7 P1 (T1–T7), 7 P2 (T8–T14),
5 P3 (T15–T19).

**Dependency order (within the priority order above):** T1 first —
the definitions gate T6, T7, T18, and T19. T5 now (one line,
independent of everything). T3 before T2, T4, and T15 (the defensive
reader first, then its consumers). T13 after T3, T2, and T4 (the
corrupt-block tests pin the reader). T12 with the first codec release
(T7). T11 alongside T7 (provenance records what the codec does).
Folded into the merged list's shared tasks: T8 (string-metamorph
verify crash → merged T6, the A3-W2 re-confirmation), T9 (metamorph
notes → merged T64), T10 (New Project form → merged T65), T14 (CLI
mode change → merged T56, the update-project `--metamorph` flag).
