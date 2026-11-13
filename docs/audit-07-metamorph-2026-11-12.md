# STELLA Audit #7 — MetaMorphAi hooks

Date: 2026-11-12 (report written 2026-11-13 from a fresh run; the first
auditor was interrupted overnight and left no file). Target: the live
v0.2 tree at `~/workspace/stella/`. The v0.3 build tree
(`~/workspace/stella-v03-build/`) was ignored per brief.

**The central question, answered first:** does metamorph DO anything
today, for either of Joshua's two readings — (a) the morphing spirit
(a base model morphing into specialized variants) or (b) the
compression codec ("prediction is compression; the same meaning in
fewer tokens", applied to fine-tune storage/serialization)?

**No. For both readings, the answer is no.** Metamorph is a stored
label — a `{mode, notes}` block that is validated, displayed, and
carried through export/import, and read by nothing that trains,
converts, probes, or quantizes. The code says so itself
(`model.py:37`: "structure only in v0.1 — no codec yet"), the README
says so (`README.md:148-150`: "The codec itself lands in a later
item — v0.2 carries the structure"), and this audit proves it
behaviorally: two identical tiny training runs, one `morph` and one
`compress`, produced the same final loss to all 16 digits and
byte-identical adapter weights (P8). The one place that does NOT say
so is the GUI tooltip, which describes the modes as if they already
work (U1) — and it is the only tooltip in the whole window (A4-U7).

No P0s in this audit: nothing here loses data or crashes on a normal
path. The crashes found (W2–W5) all need a hand-corrupted
`project.json` or manifest, and the inert mode is documented, not
hidden. The top finding is W1 (P1): the flagship concept is a label.

## 1. Scope and method

### Read in full

- `stella/model.py` — the metamorph block, `METAMORPH_MODES`, create /
  update validation and merge semantics.
- `stella/gui.py` — the combo, the list suffix, the detail fill, save.
- `stella/cli.py` — `--metamorph`, the `projects` listing.
- `stella/export.py` — manifest, README, verify, import (whole file).
- `stella/train.py`, `stella/probe.py`, `stella/gguf.py` — grepped for
  any metamorph read (there is none; see §2).
- `README.md` (§MetaMorphAi), `drive_gui.py` (seed data only).
- Tests: `tests/test_model.py`, `tests/test_export.py`,
  `tests/test_cli.py`, `tests/test_gui.py`, `tests/conftest.py`
  (metamorph-relevant cases only).
- Earlier audits, for cross-references: #2 (W10, W12, U7), #3 (W1, W2,
  W5), #4 (U7), #5 (W2, D2), #6 (format template).

### Probes (all live, all with scratch homes under /tmp)

- **P1 — Model, three modes + invalid modes** (`/tmp/a7/probe1.py`,
  system python3, `STELLA_HOME=/tmp/a7/home1`): create one project
  per mode with notes; create/update with mode `shrink`; notes-only
  and mode-only updates; non-dict metamorph at update.
- **P2 — Export/import round-trip** (same script): export a `both`
  project with notes, import into a fresh home, compare; export a
  `morph` and a `compress` project and diff the two packages file by
  file, including total bytes.
- **P3 — Corrupt block, export side**: `metamorph: null` in
  `project.json`, then export; inspect what the crash leaves behind.
- **P4 — Corrupt block, update side**: `metamorph` key deleted, then
  `update_project` with and without a metamorph field; same with the
  block set to null (separate one-liner probe).
- **P5 — Corrupt block, read side**: `metamorph` as a string in
  `project.json`, then the CLI `projects` list; `metamorph` as a
  string in an export manifest, then `verify_export` (A3-W2
  confirmation).
- **P6 — CLI**: `stella-cli create-project --metamorph shrink`
  (subprocess, exit code + stderr); `stella-cli projects` output.
- **P7 — GUI** (`/tmp/a7/probe2.py`, forge testenv, offscreen):
  window on a scratch home with one project per mode; list labels;
  combo per selection; change mode + save, check disk and notes
  preservation; tooltip text; string-metamorph project, then
  `refresh_projects`; missing-key project, then Save.
- **P8 — Training** (`/tmp/a7/probe3b.py`, train venv, torch
  2.15.0+cpu): two tiny LoRA runs (2-layer/64-hidden GPT-2, same
  dataset, settings, seed, and — critically — the same torch seed
  before each model build, so both start from the identical random
  init), modes `morph` vs `compress`; compare steps, trainable
  params, final loss, target modules, adapter weight hashes; scan
  training artifacts for any metamorph mention. An earlier unseeded
  run (probe3) differed in final loss only because the two random
  inits differed — the seeded re-run is the valid comparison.
- **P9 — Notes validation** (one-liner probe): `notes` set to `123`
  via update and `456` via create.

### What I could not test

- **A real LFM3 run per mode.** Unnecessary, and the tiny-model proof
  is stronger: with identical inits the two runs agree to the last
  digit, which a big-model run could not show more precisely. The
  code proof is closed anyway — `train.py` contains zero references
  to metamorph (grep -c = 0), so no model size changes the answer.
- **A live llama.cpp GGUF run per mode.** Same reasoning:
  `gguf.py` has zero metamorph references; the quant comes from the
  `--quant` flag / `DEFAULT_QUANT`, never from the project. A live
  run could only re-prove it.
- **Real Ollama.** Metamorph never touches Ollama (no read in
  `ollama.py`, no tag/mode interaction anywhere), so there is
  nothing to probe against a live server.

### Probe-environment notes (not Stella findings)

- The unseeded training comparison (probe3) initially looked like a
  mode effect (final loss 5.6394 vs 5.5252). It was not: each run
  built a fresh random model, so the inits differed. The seeded
  re-run (P8) is the result that counts. Lesson recorded here so a
  future auditor does not re-learn it: seed the loader, not just
  the training config.
- Two of my own check scripts were too strict and reported false
  FAILs, both explained in place: the export diff (P2) flagged
  `notes.md` / `weights/README.txt`, which differ by project NAME,
  not mode; the GUI widget scan (P7) flagged Qt's own `metaObject`
  attributes. Neither is a Stella defect.

## 2. Features and functions

What the metamorph block IS today — the complete inventory. Every
read and write in the tree:

**Storage.** Each project carries `metamorph: {mode, notes}` in
`project.json` (`model.py:314`). The mode set is closed:
`METAMORPH_MODES = ("morph", "compress", "both")` (`model.py:37`).
Default mode is `morph` everywhere (create default, CLI default,
export/import fallback, GUI fallback).

**Writes.**
- `create_project(..., metamorph_mode, metamorph_notes)` —
  `model.py:288-314`. Mode validated; unknown mode raises
  `StellaError` with the valid list.
- `update_project(..., metamorph={...})` — `model.py:338-350`.
  Non-dict rejected; mode validated; a partial dict merges —
  mode-only updates keep the notes, notes-only updates keep the
  mode (probed, P1).
- GUI Save project — `gui.py:582` passes
  `metamorph={"mode": <combo text>}` only, so notes survive a GUI
  save via the merge (probed, P7).
- CLI `create-project --metamorph` — `cli.py:203,248-250`,
  argparse `choices` (bad mode exits 2, probed P6).
- Import — `export.py:176-184` passes mode + notes from the
  manifest into `create_project`.

**Reads (display only).**
- CLI `projects` list — `cli.py:51-52`: `name, status, metamorph:
  <mode>`.
- GUI project list — `gui.py:449-451`: rows read
  `Display name — <mode>`.
- GUI detail fill — `gui.py:534-536`: sets the combo to the stored
  mode (unknown mode falls back to index 0, i.e. `morph`).
- Export manifest — `export.py:60`: the block is copied verbatim.
- Export README — `export.py:76`: one line,
  `MetaMorphAi mode: **<mode>**`.
- Export verify — `export.py:141-143`: unknown mode rejected.

**What does NOT exist — the closed list.**
- `train.py`: **0** references to metamorph (grep -c). Training
  reads settings (rank, lr, epochs…), dataset, and base ref only.
  The mode cannot change a run, and P8 proves it does not.
- `probe.py`: **0** references. The refusal probe never sees the
  mode (`probe.py:166` calls `get_project` only to check the
  project exists).
- `gguf.py`: **0** references. Quantization is `DEFAULT_QUANT =
  "Q4_K_M"` (`gguf.py:29`) or the `--quant` flag — a `morph` project
  and a `compress` project produce the same GGUF by construction.
- No variant/spawn/lineage logic anywhere (no "morph this base
  into a variant" operation exists).
- No codec of any kind: no adapter compression, no package
  compression, no token-level compression, no quantization wiring.
- No mode in any training artifact (adapter, checkpoints,
  `train_log.jsonl`, `training_summary.json` — scanned clean, P8).
- No `metamorph.notes` surface: no GUI widget, no CLI flag (A2-W10;
  see W8).

**Documentation.** `README.md:141-150` states both readings honestly
and says the codec "lands in a later item — v0.2 carries the
structure." The code comment at `model.py:37` says the same thing
but still names v0.1 (W10).

**Tests covering metamorph.** `test_model.py:88,100-118` (defaults,
all three modes, bad mode, update merge);
`test_export.py:23,56-59,84` (manifest mode, bad mode rejected,
round-trip mode); `test_cli.py:47` (create with `--metamorph both`);
`test_gui.py:36` (combo shows `both`); `conftest.py:37` (seeded
fixture uses `both`). All test the label behaving as a label. None
test a corrupt block (G5) or the mode's (non-)effect on training.

## 3. Strengths

- **Validation is clean where it exists.** Bad modes are rejected
  with a plain `StellaError` at create and update (P1), and with
  argparse exit 2 at the CLI (P6) — no tracebacks on the intended
  paths. The error names the valid modes.
- **The update merge is careful.** Mode-only and notes-only partial
  updates each preserve the other field (P1) — the exact semantics
  a later notes UI will need, already correct at the model layer.
- **Round-trip fidelity is real.** Mode + notes survive
  export → import into a fresh home byte-identical (P2). The
  manifest carries the whole block, and import passes it through
  rather than re-defaulting.
- **The GUI save preserves notes it cannot see.** Save passes only
  the mode (`gui.py:582`) and the merge keeps the notes (P7) — so a
  user who hand-set notes in JSON does not lose them by clicking
  Save. (The notes are still unreachable from the UI — W8 — but
  they are not destroyed by it.)
- **The README is honest.** It states both readings, says plainly
  the codec is a later item, and does not claim v0.2 compresses
  anything. The documentation does not oversell; only the GUI
  tooltip does (U1).
- **The block is forward-compatible in shape.** The manifest
  already carries mode + notes with a version field alongside, so a
  future codec can record what it did per project without a format
  break — provided the mode-version story (G4) is settled when the
  codec lands.

## 4. Weaknesses

### W1 — The mode does nothing, for either reading (P1)

The flagship concept is inert. No code path in `train.py`,
`probe.py`, or `gguf.py` references metamorph at all (grep -c = 0
for each). Setting a project to `compress` does not change its
training, its probe, its GGUF export, or its package; setting it to
`morph` does not create, track, or manage variants. P8 is the
behavioral proof: identical-init tiny runs in `morph` and
`compress` gave final loss `5.564785480499268` for both, 3 steps,
4,096 trainable params, same target modules, and byte-identical
adapter weights (SHA-256 prefix `e3a36ab43103649b` for both).

This is P1, not P0: the README documents it honestly, nothing is
lost, and nothing crashes. But it is the defining weakness of the
component — the name MetaMorphAi promises two behaviors and the
program delivers neither. What each reading would actually need is
specified in §7 (D1–D4, D16); until D1 (the definition) exists,
every other metamorph fix is polish on a label.

### W2 — Export crashes on `metamorph: null`, and leaves a partial package (P1)

`export.py:60` uses `proj.get("metamorph", {...})` — but `.get`'s
default only applies when the key is *absent*. When the key is
present with value `null`, the manifest gets `metamorph: None`,
and line 76 (`manifest['project']['metamorph'].get(...)`) raises
`AttributeError: 'NoneType' object has no attribute 'get'`
(probed, P3). Worse, the crash happens *after* `manifest.json`
and `config.json` are written: the export folder is left behind
containing exactly those two files — no README, no `weights/`, no
`checkpoints/`. A second export attempt then fails with "export
folder already exists" (A3's non-atomicity class, export-side;
cf. A3-W1 for import). The fix is one `or {}` (D8) plus building
the README text before creating the folder (D9).

### W3 — GUI Save crashes with `KeyError` when the metamorph key is missing (P1)

`update_project` assumes the stored block exists:
`model.py:341` reads `data["metamorph"]["mode"]` with no guard.
With the key deleted from `project.json`, a GUI save — which
always passes a metamorph dict (`gui.py:582`) — raises
`KeyError: 'metamorph'` (probed, P4 and P7). `save_project`
catches only `StellaError`, so the exception escapes the Qt slot:
the save silently does not happen, and the traceback goes to a
terminal the menu-launched user never sees (Terminal=false).
With the block set to `null` instead of missing, the same line
raises `TypeError: 'NoneType' object is not subscriptable`
(probed, P4). A display-name-only update on the same file works
fine — only the metamorph path assumes the block. Root cause:
`get_project` (`model.py:270-276`) setdefaults `name` and
`profile` but not `metamorph` (D8).

### W4 — The GUI project list crashes on a string metamorph (P1)

`gui.py:449` reads the mode with
`(p.get("metamorph") or {}).get("mode", "morph")`. The `or {}`
guards `None` and missing — but a *string* is truthy, so a
hand-edited `"metamorph": "both"` raises `AttributeError: 'str'
object has no attribute 'get'` inside `refresh_projects` (probed,
P7). One bad project kills the whole list refresh, so the window
cannot show *any* project in that profile. The detail fill at
`gui.py:534` uses the identical expression and crashes identically
(same line shape; masked in practice because the list refresh
fails first). The CLI instance of this exact pattern is A5-W2
(re-confirmed in P5); this is the GUI half, which no earlier
audit probed. Fix with the shared defensive reader (D8).

### W5 — `verify_export` crashes on a string metamorph: A3-W2, re-confirmed (P2)

`export.py:141` uses the same `(proj.get("metamorph") or
{}).get(...)` shape, so a hand-edited manifest with
`"metamorph": "both"` raises `AttributeError: 'str' object has no
attribute 'get'` (probed, P5). This is audit #3's W2, unchanged
except the line number (128 → 141 as the file grew). Listed here
so the task-list merge can fold it onto the existing A3-W2 task
rather than minting a duplicate; the fix is the same D8 reader.

### W6 — `compress` does not shrink the package — it is 22 bytes BIGGER (P2)

P2 exported the same-shaped project in `morph` and `compress` and
diffed the packages: identical file lists
(`README.md`, `config.json`, `manifest.json`, `notes.md`,
`weights/README.txt`), and the only mode-caused differences are
the mode string itself in `manifest.json` and `README.md`
(`notes.md` / `weights/README.txt` differ only by project name).
Total bytes: `morph` 1,643 B, `compress` 1,665 B — the "compress"
package is *larger*, because the word "compress" is longer than
"morph". The mode's name promises compression of the fine-tune's
storage; the export delivers the opposite by 22 bytes. This is
the measurable form of W1's compression half, and the reason D3
(package compression) is the honest first codec step.

### W7 — `both` has no combined semantics (P2)

`both` is a third label, not morph-plus-compress: no code anywhere
branches on it, and nothing defines what the combination would do
(train two variants? compress the morphed output? in which
order?). Today it is indistinguishable from the other two modes
in behavior — which is to say, equally inert. When the codec
lands, `both` needs a written definition (D1) or it becomes a
fourth kind of nothing.

### W8 — `metamorph.notes` is unreachable from the GUI and the CLI (P2)

Folded from A2-W10 (unchanged in v0.2). The combo edits mode
only; the CLI has `--metamorph` but no notes flag; the only ways
to set notes are hand-editing `project.json` or importing a
package that already has them. The GUI save at least preserves
notes it cannot see (§3), but a field the user can neither read
nor write in the program is a dead key with a live name — and it
sits beside two other notes fields (`settings["notes"]`, which
nothing reads or writes, and `notes.md`, the only visible one),
so a hand-editor cannot tell which one matters. Fix: D7.

### W9 — GUI New Project is name-only: no metamorph choice at creation (P2)

Folded from A2-W12. The CLI's `create-project` takes
`--metamorph`; the GUI's New Project asks for a name and nothing
else, so every GUI-created project starts as `morph` and the user
must find the combo afterwards to change it. The mode's one
moment of relevance — creation, when the user is deciding what
this project is *for* — is the moment the GUI does not offer it.
Fix: D10.

### W10 — The code's own honesty marker is stale: "structure only in v0.1" (P3)

`model.py:37` comments `METAMORPH_MODES` with "structure only in
v0.1 — no codec yet." The tree is v0.2, which shipped a whole
training engine without touching metamorph — the comment was
never updated, so the code now claims a version behind. Small,
but this comment is the one place the code tells the next reader
the truth about the component; a stale truth-marker invites the
next reader to assume v0.2 changed something. Fix with the D1
spec pass (update the comment to the version that defines the
modes, or drop the version from it).

### W11 — `notes` accepts any JSON type, unchecked (P3)

`create_project` (`model.py:314`) and `update_project`
(`model.py:347-350`) validate the mode but never the notes:
`notes: 123` and `notes: 456` are stored verbatim (probed, P9).
Nothing crashes today — the GUI never reads notes, and JSON
round-trips an int fine — but the manifest's contract says notes
is text, and a future notes UI (D7) reading an int into a text
field will crash or render garbage. One `isinstance` check at
both write points (D8).

## 5. UI flaws

### U1 — The tooltip promises behavior that does not exist (P1)

`gui.py:322-325`, probed verbatim (P7):

> "MetaMorphAi: morph turns the base into variants, compress
> shrinks how the fine-tune is stored, both does both."

Present tense, describing effects. None of the three clauses is
true (W1, W6). This is the *only* tooltip in the entire window
(A4-U7) — the one explanation the GUI offers anywhere is the one
that is wrong — and it directly contradicts the README's honest
"the codec lands in a later item." A user who hovers learns the
opposite of the truth. One-line fix (D6); do not wait for the
codec to fix the words.

### U2 — The project list presents the mode as if it mattered (P2)

Rows read `Display name — both` (`gui.py:449-451`), with no
indication the suffix is a label. Beside the tooltip (U1), the
list sells the mode as a live property of the project — a user
reasonably reads "— compress" as "this project will compress."
Once the tooltip is honest (D6), the list suffix is a fair label;
until then it is part of the same misrepresentation. (Distinct
from U1: U1 is the words, U2 is the presentation.)

### U3 — No metamorph-notes field in the detail panel (P2)

The UI half of W8 (A2-W10). The detail panel shows the mode combo
and, below it, the `notes.md` editor labeled "Notes" — so the
panel has a notes surface, but it is the *other* notes. The
manifest's `metamorph.notes` has no field, no display, and no
hint it exists. A user who sets notes by hand-editing JSON can
never see them in the window. Fix: D7.

### U4 — No metamorph choice in New Project (P2)

The UI half of W9 (A2-W12). Creation is name-only; the mode must
be changed after the fact, in a combo below the fold at 1100×680
(A4's fold finding — the detail panel content is 1289px against a
567px viewport). The mode is decided at creation and editable
only after scrolling. Fix: D10.

### U5 — The Train panel never mentions the mode (P3)

Training is where a user would expect the mode to act — and the
Train panel is silent about it. A user who set `compress`,
starts a run, and watches the log sees no note that compression
does not apply to the run. The mode is visible in the detail
panel and invisible where its effect would be expected, so the
run's silence reads as "working." Fix: D14 (one line in the
panel until the codec lands).

### U6 — `--metamorph` has no help string (P3)

`cli.py:248-250` declares the flag with `choices` but no `help`,
so `stella create-project --help` shows the three words and no
meaning (noted in A5's design list, line 687). With U1's tooltip
as the only explanation anywhere, the CLI user gets even less.
Fix: D15.

## 6. Gaps

### G1 — No morph implementation: no variants, no lineage (P1)

There is no operation that turns a base into a variant
differently per mode, no way to spawn a variant project from
another, and no record of which project descended from which.
"Morphing" today means "a project exists under a profile" — true
of every project regardless of mode. What the reading needs is
specified in D4 (spawn + lineage in the manifest).

### G2 — No compression codec anywhere in the pipeline (P1)

No quantization choice driven by mode (GGUF always defaults to
Q4_K_M, `gguf.py:29`); no adapter compression; no package
compression (W6); no token-level compression ("the same meaning
in fewer tokens" has no code behind it — no dataset
tokenization/dedup step at train time). The only real
compression in Stella (GGUF quantization) is entirely
disconnected from the mode that names compression. The honest
first steps are D2 (quant wiring) and D3 (package compression);
the deep token-level codec is D16, explicitly a later item.

### G3 — No mode provenance in training artifacts (P2)

Adapter, checkpoints, `train_log.jsonl`, and
`training_summary.json` never record the mode (scanned clean,
P8). After a run, nothing in the artifacts says which mode the
project was in when it trained — so when the codec lands, old
adapters cannot be told apart by mode, and a future "was this
adapter compressed?" question has no answer in the artifacts.
Fix: D5 (record the mode at train time, starting now, so the
provenance exists before the codec needs it).

### G4 — No mode-version story (P2)

`METAMORPH_MODES` is a closed tuple, and `verify_export` rejects
any mode outside it (`export.py:141-143`). Adding a mode later —
or a codec version, which is what a real codec needs — has no
migration path: old Stella would reject new packages outright,
and `verify_export` never checks `stella_version` at all
(A3-W5), so there is no version gate for a future mode to ride
on. Settle this with D12 before the first real codec ships, or
the first codec release breaks old imports.

### G5 — No tests for corrupt metamorph states (P2)

The suite tests valid modes, a bad mode string, and the
round-trip — but no test covers `null`, missing-key, or
wrong-type metamorph in `project.json` or a manifest. All three
crashes in this audit (W2, W3, W4) live in untested paths, and
W5's re-confirmation shows the one tested corrupt case (bad mode
string in the manifest, `test_export.py:56-59`) does not cover
the wrong-*type* case next to it. Fix: D11.

### G6 — No per-mode defaults (P3)

Every mode gets identical `DEFAULT_SETTINGS` (`model.py:44-57`).
A `compress` project might sensibly default to a lower rank; a
`morph` project to variant-friendly settings. Today the mode
cannot even express a preference. This only makes sense after D1
defines the modes — until then it is a note, not a task. (D13.)

### G7 — The CLI cannot change a mode after creation (P2)

`--metamorph` is create-time only; the CLI has no update command
at all (A5-G1 / A1-W9 territory), so a CLI-only user who wants to
change a project's mode must hand-edit JSON or open the window.
Folded from the CLI gaps; the metamorph half is fixed by D15.

## 7. Design suggestions (priority order)

These are DESIGN, not findings — proposals for what to build,
clearly separated from §§4–6.

### D1 — Define what each mode MEANS, in writing, before building the codec (W1, W7, W10)

A short spec in the README (and a code comment replacing the
stale `model.py:37` line): what `morph` does, what `compress`
does, what `both` does and in which order. Everything else in
this section depends on it — D2/D3/D4/D13/D16 cannot be built
correctly against an undefined word. This is the first task, and
it is a writing task, not a code task.

### D2 — Wire `compress` to the GGUF quant first: the cheapest real effect (W1, G2)

`export-gguf` already takes `--quant` and defaults to Q4_K_M
(`gguf.py:29,142`). One branch: mode `compress` defaults the
quant a step smaller (e.g. Q3_K_M), `morph` keeps Q4_K_M,
`--quant` always overrides, and the choice is printed. Real,
visible, testable behavior for the mode with the smallest
possible change — and it makes "compress shrinks how the
fine-tune is stored" true at the GGUF level.

### D3 — Compress the export package when the mode is `compress` (W1, W6, G2)

Mode `compress` → the export ships as a compressed archive (zip)
instead of (or alongside) the plain folder; `morph` → plain
folder as today. This makes the mode's promise true at the
package level and directly answers W6's 22-bytes-bigger
embarrassment. Import must accept both forms.

### D4 — Variant lineage for `morph`: spawn + parent record (G1)

A project can spawn a variant project (copy settings/dataset,
new slug, `metamorph.parent` recorded in the manifest); the
project list shows lineage. This is what "a base model morphs
into specialized variants" looks like at Stella's scale — not a
new architecture, a family tree with a spawn operation.

### D5 — Record the mode in training artifacts now (G3)

Write the project's mode into `training_summary.json` (and the
adapter config) at train time, starting with the next build —
before the codec exists. Cheap, and it means provenance is
already there when the codec needs it.

### D6 — Fix the tooltip now: honest words, one line (U1)

Replace the present-tense promise with the truth, e.g.:
"MetaMorphAi mode — a label for now; the morph/compress codec
lands in a later item." Do not wait for the codec to fix the
words. (Also fixes the A4-U7 sting: the window's only tooltip
stops being its only lie.)

### D7 — Add a metamorph-notes field to the detail panel + a CLI flag (W8, U3)

A small text area under the combo, saved through the existing
merge (which already preserves notes correctly — §3), plus
`--metamorph-notes` on `create-project`. Label it distinctly
from the `notes.md` area ("Why this mode" vs "Project notes") so
the three-notes confusion (A2-W10) does not get worse.

### D8 — One defensive reader for the block, used everywhere (W2, W3, W4, W5, W11)

A single helper — e.g. `metamorph_mode(project_dict)` returning
a valid mode or `"morph"` for null/missing/wrong-type — used by
the CLI list, the GUI list + detail fill, export, and verify;
plus `get_project` setdefaulting the block, and a type check on
`notes` at both write points. One fix closes all four crashes
and the notes-type hole. The GUI list should degrade to a
warning row for a bad project, not die for the whole profile
(A5-D2's prescription, applied to the GUI half).

### D9 — Build the export README text before creating the folder (W2)

Compute every file's content first, then create the directory
and write — so a bad block fails before any partial package
exists. (Same atomicity direction as A3-W1's import fix.)

### D10 — New Project form with dataset + metamorph (W9, U4)

Restating A2-W12's fix for this component: the GUI's New Project
takes a dataset and a mode, matching the CLI's `create-project`.
The mode is chosen when the project is conceived, not hunted
down afterwards below the fold.

### D11 — Corrupt-block tests for every reader (G5)

`null`, missing-key, and wrong-type metamorph in `project.json`
and in manifests, exercised against the CLI list, the GUI list +
detail fill + save, export, and verify. Pins D8.

### D12 — Mode-version story before the first codec ships (G4)

Carry a codec version in the manifest when the codec lands, and
make `verify_export` check `stella_version` (A3-W5) so old
Stella can refuse — cleanly, with a message — a package whose
mode it does not understand, instead of crashing or silently
misreading it.

### D13 — Per-mode training defaults, after D1 (G6)

Once the modes are defined, let `compress` suggest a lower rank
and `morph` suggest variant-friendly settings — suggestions in
the New Project form, not silent overrides.

### D14 — Show the mode in the Train panel (U5)

One line ("Training as `compress` — mode is a label in v0.2")
until the codec lands, then the real per-mode behavior summary.
Stops the run's silence from reading as "working."

### D15 — CLI help strings + a way to change mode after creation (U6, G7)

Real `help=` text on `--metamorph` (what the modes mean, with
the honest "label for now" note), and a `stella update` /
`stella show` path so a CLI user can change a mode without
hand-editing JSON (rides the general CLI-update gap, A5-G1).

### D16 — The token-level codec is a named later item, not forgotten (W1, G2)

"The same meaning in fewer tokens" at train time — dataset
tokenization, dedup, and compression-aware training — is the
deep reading of the codec and the hardest part. Name it as a
later item with its own design pass; do not let D2/D3's easy
wins pretend it is done.

## 8. Prioritized recommendations

| Priority | Items | What it fixes |
|---|---|---|
| **P0** | — (none) | No data loss and no crash on any normal path; the inert mode is documented, not hidden |
| **P1** | W1 (D1, D2, D3, D16), W2 (D8, D9), W3 (D8), W4 (D8), U1 (D6), G1 (D4), G2 (D2, D3, D16) | The mode does nothing for either reading; export/GUI crashes on corrupt blocks; the window's only tooltip promises behavior that does not exist; no morph or compression implementation at all |
| **P2** | W5 (D8), W6 (D3), W7 (D1), W8 (D7), W9 (D10), U2 (D6, D14), U3 (D7), U4 (D10), G3 (D5), G4 (D12), G5 (D11), G7 (D15) | Re-confirmed import crash; the compress package is bigger, not smaller; `both` undefined; notes unreachable; no mode choice at creation; list presentation; no mode provenance, version story, corrupt-block tests, or CLI mode change |
| **P3** | W10 (D1), W11 (D8, D11), U5 (D14), U6 (D15), G6 (D13) | Stale comment; unvalidated notes type; Train panel silence; missing CLI help; no per-mode defaults |

**Dependency order (within the priority order above):** D1 first —
the definitions gate D2/D3/D4/D13/D16. D6 now (one line,
independent of everything). D8 before D11 (the defensive reader
first, then the tests that pin it). D5 alongside D2/D3 (provenance
records what the codec does). D12 with the first codec release
(the version rides the first real mode behavior). D16 last (the
deep codec, after the easy wins prove the wiring).

**Cross-references to earlier audits:** A2-W10 (notes unreachable)
and A2-W12 (name-only New Project) are folded here as W8/W9 and
U3/U4, unchanged in v0.2. A3-W2 (string metamorph in the manifest)
is re-confirmed as W5 (line moved 128 → 141); A3-W1 (non-atomic
import) is the same class as W2's partial export; A3-W5 (version
never checked) gates G4. A5-W2 already covers the CLI instance of
the string-metamorph crash (`cli.py:51`); W4 is the GUI half,
which no earlier audit probed. A4-U7 (the metamorph combo is the
window's only tooltip) is the reason U1 stings. A2-U7 (no tooltips
elsewhere) is unchanged. No earlier audit covered the mode's
(non-)effect on training, the export-side null crash, or the
missing-key save crash — W1, W2, W3, W6, and G3 are new here.

**Coverage check:** 11 weaknesses + 6 UI flaws + 7 gaps + 16 design
suggestions = 40 findings. Every W/U/G maps to at least one D
(§7); every D names the finding(s) it addresses.
