# STELLA Audit #2 — Projects

**Audited:** 2026-11-12 evening, against the v0.1 tree as shipped
(commit e28db915, Release v0.1). Scope: everything a *project* is and
does — the project data model, the project pane, the project detail
panel (settings, dataset, metamorph, notes), the checkpoints folder,
project CLI commands, and the project side of create/rename/delete.
Profiles were #1; export/import (#3), the window as a whole (#4), the
CLI as a whole (#5), the installer (#6), and MetaMorphAi (#7) get
their own audits.

**Method:** read `stella/model.py` (project sections), `stella/gui.py`
(project pane, detail panel, project actions), `stella/cli.py`
(project commands) in full; probed live behavior with a scratch home
and a driven GUI window; checked test coverage. Every weakness below
was verified by probe or direct code citation. Probe script:
`/tmp/project-probes.py` (scratch, not shipped).

**Design intent (from the brief):** inside a profile, fine-tunes are
projects — each with its own dataset, training settings, checkpoints,
and notes, fully customizable. A finished project exports as a usable
package.

---

## 1. Features and functions

### Data model (`model.py`, `Store`)

- A project is a folder
  `~/.stella/profiles/<profile>/projects/<slug>/` holding
  `project.json`, `notes.md`, and an empty `checkpoints/` dir.
- Manifest fields: `name` (slug), `display_name`, `profile`
  (pointer back to the owning profile), `dataset_ref`, `settings`,
  `metamorph` (`mode` + `notes`), `status`, `stella_version`,
  `kind`, `created`, `updated`.
- Default settings for a new project: method `lora`, rank 8,
  learning rate 0.0002, epochs 3, batch size 1, max seq len 1024,
  notes `""`.
- Full CRUD: `create_project`, `get_project`, `list_projects`,
  `update_project` (5 allowed fields), `rename_project`,
  `delete_project`. Creation requires the profile to exist first;
  duplicate names are rejected.
- `update_project` merges settings (partial updates keep the rest)
  and validates the metamorph mode (only `morph`, `compress`,
  `both`); when only a mode is given, existing metamorph notes are
  preserved.
- Rename updates the manifest name, the display-name-when-default,
  and the timestamp. Delete removes the whole folder.
- Notes: `read_notes` / `write_notes` on `notes.md`; a new project
  starts with `# <name>\n\nNotes for this fine-tune.\n`.
- Same slug rules, atomic writes, and containment checks as
  profiles. `list_projects` returns manifests sorted by directory
  name; a manifest that fails to parse is skipped.
- `get_project` fills in a missing `profile` pointer from the
  folder it was found in.

### GUI — project pane + detail panel (`gui.py`)

- Middle pane lists the selected profile's projects as
  `Display name — metamorph mode`. New / Rename / Delete buttons
  under the list.
- Detail panel (below the profile section, scrollable): Display
  name, Dataset (text field, placeholder "path or name of the
  training data"), Method (combo: `lora`, `full`), LoRA rank
  (spinbox 1–64), Learning rate (free-text field), Epochs (spinbox
  1–100), Batch size (spinbox 1–32), Max seq len (spinbox
  128–32768), MetaMorphAi (combo: morph/compress/both, with the only
  tooltip in the GUI), Save project, Notes (plain-text editor,
  minimum height 120).
- One Save button writes settings + notes together. A non-numeric
  learning rate is refused with a friendly message ("Learning rate
  must be a number, like 0.0002.").
- New Project is a name-only prompt (QInputDialog). Rename is a
  name prompt prefilled with the current slug. Delete asks once
  ("Delete project X? This cannot be undone.") and proceeds only on
  Yes.
- No status control anywhere in the GUI: no widget shows or changes
  the project's status.

### CLI (`cli.py`)

- `stella projects <profile>` — lists `name, status, metamorph mode`.
- `stella create-project <profile> <name> --display --dataset
  --metamorph` (metamorph restricted to the three modes).
- No CLI for rename, delete, update, or show-one-project.

### Tests covering projects

- `test_model.py`: create defaults (status `draft`, checkpoints dir
  exists), create needs an existing profile, metamorph mode
  validation, settings merge on update, rename + delete, notes
  round-trip.
- `test_gui.py`: detail fills from selection (incl. dataset +
  metamorph + rank), save project writes settings + notes through
  to disk.
- `test_cli.py`: create-project with `--dataset` + `--metamorph`.
- No test covers: settings validation (none exists), status
  transitions (none exist), a corrupt project manifest, dataset
  validation (none exists), or unsaved-edit loss.

---

## 2. Strengths

1. **The defaults are genuinely good.** Rank 8, lr 0.0002, epochs 3,
   batch 1, seq 1024 is a sane CPU micro-LoRA starting point — a new
   project is trainable as-is the moment Item 3 lands, with no
   tuning knowledge required.
2. **Rename is thorough** (same care as profiles): manifest,
   display-name-when-default, timestamp.
3. **No orphan projects.** Creation requires the profile to exist;
   the manifest carries a `profile` pointer back to its owner.
4. **Settings merge, not clobber.** A partial update keeps the
   untouched settings — the GUI can save one field's change without
   wiping the rest.
5. **Metamorph mode is validated.** The one enum in the project is
   enforced (invalid modes rejected, tested), and updating the mode
   preserves the metamorph notes — a careful merge.
6. **Notes are always there.** Plain Markdown, created with a header
   at project creation, editable in the window or in the GUI text
   editor.
7. **The checkpoints folder is pre-created.** The training layout is
   ready before training exists — Item 3 has somewhere to put
   checkpoints from day one.
8. **One Save covers settings + notes.** A single action, no
   split-brain saving where settings save but notes do not (or the
   reverse).
9. **Atomic writes + slug/containment discipline**, shared with
   profiles.
10. **Duplicate names are rejected**, and the learning-rate error
    message is friendly and specific.

---

## 3. Weaknesses (all verified)

### W1 — Unsaved edits are silently discarded on switch (P0)

There is no dirty tracking anywhere. Edit the notes or any field,
click another project, and `_show_project_detail` reloads from disk
— the edits are gone with no warning, no prompt, no asterisk.
Probed live: typed "UNSAVED edit" into the notes and changed the
display name, switched projects and back — notes reverted to the
saved text, display name reverted to the slug. The same flaw covers
the profile detail panel (edit a role, switch profiles, lose it):
one fix must cover both panels. This is a data-loss bug in the
program's main daily action (keeping notes during a fine-tune).

### W2 — Zero settings validation in the model (P0)

`update_project` merges any settings dict without checking a single
value. Probed: rank -5, epochs 0, batch size 0, learning rate -0.5,
max seq len 999999, and an unknown key `foo` were all stored without
complaint. The GUI spinboxes constrain only the GUI path; the CLI,
imports, and hand-edits bypass everything. Training (v0.2) will
receive nonsense settings and fail cryptically — or worse, "train"
for 0 epochs and report success.

### W3 — `inf` / `nan` learning rates write invalid JSON (P0)

The GUI's only learning-rate check is `float(...)`, and `float()`
accepts `"inf"`, `"-inf"`, and `"nan"`. Probed: saving lr=inf wrote
a bare `Infinity` literal into `project.json` — not valid JSON for
any tool except Python's lenient parser. A mistyped LR (`in` →
no, that fails parse; but `inf` passes) corrupts the manifest for
every strict JSON reader, including the export verifier if it ever
runs outside Python.

### W4 — A corrupt project manifest silently vanishes (P1)

Same pattern as profiles W1: `list_projects` swallows the parse
error and skips the row. Probed: corrupting `second/project.json`
removed the project from the list with no warning, while a direct
`get_project` still raises a clear "not valid JSON" error. The
project, its settings, its notes, and (from v0.2) its checkpoints
become invisible in the GUI and CLI.

### W5 — Status is a dead letter (P1)

`status` is free text with no lifecycle and no UI. Every project is
born `draft` and stays `draft` forever — nothing transitions it
through training, done, failed, or exported, and nothing can: the
detail panel has no status control (probed: no `proj_status`
widget exists), the list shows no status, and the model accepts any
string (probed: `status="banana"` stored fine). An exported project
still says `draft`. The field exists only to mislead.

### W6 — The dataset reference is unvalidated text (P1)

Probed: `dataset_ref="/no/such/place/data.jsonl"` is accepted at
creation with no complaint. No existence check, no format check, no
example count, no preview. A mistyped path or a wrong-format file
fails at train time, not at configure time — the most expensive
moment to discover it. (Dataset JSONL validation is specced for
Item 3's training engine; the field itself needs the UI wired to
it.)

### W7 — "full" fine-tuning is offered with no warning (P1)

The Method combo offers `full` next to `lora`, with no hint that a
full fine-tune of a 1.5–2B model on this CPU is infeasible (the
brief established this: it needs a free cloud GPU). A user picking
`full` gets a project that can never complete on his PC, and the
model layer accepts any method string at all (probed:
`method="banana"` stored). The choice looks equal; it is not.

### W8 — Delete is unrecoverable (P1)

Same as profiles W5: one confirm dialog, then `shutil.rmtree` on
the project folder — settings, notes, and (from v0.2) checkpoints.
No trash, no backup, no "export first" offer. One misclick past Yes
deletes a project that may hold hours of training.

### W9 — No sane-range guidance on the extremes (P2)

Rank up to 64, seq len up to 32768, batch up to 32, epochs up to
100 — all selectable with no RAM or time estimate. The defaults are
good, but the extremes are swap death on 8 GB with no warning at
configure time. Item 3's RAM guard will refuse at train time; the
settings panel should say so before the user invests in a doomed
configuration.

### W10 — Three notes, one visible (P2)

`metamorph.notes` has no UI (the combo edits mode only);
`settings["notes"]` exists in the defaults but nothing reads or
writes it; `notes.md` is the only notes surface the user can reach.
Three fields with overlapping purposes, two of them unreachable —
and a user hand-editing the JSON cannot tell which one matters.

### W11 — No CLI parity, uneven in both directions (P2)

The CLI cannot rename, delete, update, or show a project. In the
opposite direction, the CLI's `create-project` takes `--dataset`
and `--metamorph` while the GUI's New Project is name-only. Neither
surface is a superset of the other; scripted project management is
impossible, and GUI creation is deliberately thinner than the CLI.

### W12 — New Project is name-only (P2)

The GUI creates a project from a single name prompt — no dataset,
no metamorph choice, no settings. Every project starts identical
and must be configured afterwards, one field at a time. The CLI
already has the flags; the GUI never got the form.

### W13 — No clone / duplicate project (P2)

Same dataset + settings, second try (different rank, different
metamorph mode) means creating a fresh project and re-entering
everything. The most common fine-tuning workflow — try, compare,
vary one knob — has no shortcut.

### W14 — The project list shows almost nothing (P3)

Rows show display name + metamorph mode only: no status, no method,
no rank, no dataset. Two projects with the same display name and
mode are indistinguishable in the list (their slugs differ but are
never shown).

### W15 — Checkpoints are a bare folder (P3, expected)

`checkpoints/` is created empty and nothing in v0.1 lists, names,
or manages it. This is Item 3's scope (its Train panel will own
checkpoints), so it is a noted gap, not a defect — but v0.1 ships a
folder it cannot show.

---

## 4. UI flaws (verified)

- **U1 — No dirty indicator, no save warning.** The UI face of W1:
  edited fields look identical to saved ones, and switching away
  discards them without a word. No asterisk, no "unsaved changes"
  prompt, no auto-save.
- **U2 — Notes sits below the fold.** The Notes editor is under Save
  project at the bottom of a scrolling panel; in the 1100x680
  window only the "Notes" header peeks out (visible in the v0.1
  screenshot). The running log — the field a user touches most
  during a fine-tune — needs a scroll on every visit.
- **U3 — Learning rate is a bare text field with no range hint.** No
  placeholder, no sane-range note; `inf` and `-0.5` look exactly as
  valid as `0.0002` until save (and `inf` passes save — see W3).
- **U4 — No status shown anywhere.** The UI face of W5: neither the
  list nor the detail panel shows the project's status.
- **U5 — Dataset is a bare text field.** No file picker, no browse
  button — paths must be typed by hand. For a user who hand-types
  from his phone screen, a picker matters more than for most.
- **U6 — "full" offered with no warning.** The UI face of W7.
- **U7 — No tooltips on the settings fields.** The metamorph combo
  has the GUI's only tooltip; rank, learning rate, epochs, batch,
  and seq len have no explanation of what they do or what sane
  values look like.

---

## 5. Gaps (against the design intent)

- **G1 — No training lifecycle.** No states, no transitions, no
  history: a project cannot record that it trained, failed, or
  finished. Status exists as a string and nothing drives it.
- **G2 — No dataset management.** No validation, preview, example
  count, train/val split view, picker, or sample dataset in v0.1
  (Item 3 ships a sample and a validator — the UI wiring is the
  gap).
- **G3 — No checkpoint management.** No list, resume picker, or disk
  usage (Item 3's scope — expected, noted for completeness).
- **G4 — No cost estimate.** No RAM or time estimate for the
  configured settings on his hardware — the user configures blind.
- **G5 — No project templates or presets.** No known-good starting
  points (e.g. an "LFM3 tool-format" preset with proven settings).
- **G6 — No settings-only export.** Export is the whole package;
  there is no way to share a recipe (dataset + settings) without
  weights and checkpoints.
- **G7 — No notes history.** `notes.md` is a single overwrite on
  every save; a mistaken save loses the previous notes with no
  backup.

---

## 6. Innovation and design suggestions

- **D1 — Dirty tracking, or auto-save on switch.** Mark edited
  fields, prompt ("Save changes to this project?") when leaving
  with unsaved edits, or just save on switch. Never silently
  discard — and fix the profile panel in the same pass.
- **D2 — Validate settings in the model, once, everywhere.**
  Ranges + types + method enum + unknown-key rejection inside
  `update_project`/`create_project`, so the GUI, CLI, imports, and
  hand-edits all get the same rules. Training should never receive
  nonsense.
- **D3 — Learning rate as a real numeric input** with a sane range
  (e.g. 1e-5–1e-2), rejecting inf/nan/negative; same treatment for
  every numeric setting.
- **D4 — Damaged-row for corrupt manifests** (same fix as profiles
  D4): show the project greyed with the parse error and a Repair
  action, never silently vanish.
- **D5 — A real status lifecycle, with UI:** draft → ready →
  training → done/failed → exported. Status shown in the list and
  the detail panel; transitions driven by training and export
  actions, not free text.
- **D6 — Dataset picker + validation:** a browse button, existence
  check, JSONL format check, example count, a 3-example preview,
  and train/val split display — wired to Item 3's validator.
- **D7 — Method guidance:** `full` gets a warning badge ("not
  feasible on this PC — needs a cloud GPU") or is hidden until a
  cloud path exists; LoRA stays the default.
- **D8 — RAM/time estimate in the detail panel** for the current
  settings, reusing Item 3's RAM-guard math: "fits in 8 GB" or
  "will not fit" at configure time, not train time.
- **D9 — Clone project, and project templates** (an LFM3 tool-format
  preset with known-good settings as the first one).
- **D10 — Trash-on-delete** (shared with profiles), plus an
  "export first" offer in the delete dialog.
- **D11 — Notes backup:** keep a dated copy on each save (or
  `notes.md.1`), so a mistaken save is recoverable.
- **D12 — Merge the three notes into one surface:** drop
  `settings["notes"]`, keep `notes.md` plus metamorph notes with a
  UI field for the latter.
- **D13 — CLI parity:** `rename-project`, `delete-project`,
  `update-project`, `show-project`.
- **D14 — Richer project rows:** status + method/rank at a glance,
  and show the slug when two display names collide.

---

## 7. Recommended improvements (his to direct)

- **P0:** D1 dirty tracking / auto-save (W1); D2 model-side settings
  validation (W2, W6-method, W7-model); D3 learning-rate range
  (W3).
- **P1:** D4 damaged-row (W4); D5 status lifecycle (W5); D6 dataset
  picker + validation (W6); D7 method guidance (W7); D10 trash
  (W8).
- **P2:** D8 RAM/time estimate (W9); D9 clone + templates (W13, G5);
  D13 CLI parity (W11); D12 notes merge (W10); a real New Project
  form with dataset + metamorph (W12); D11 notes backup (G7).
- **P3:** D14 richer rows (W14); U2 notes placement; U7 tooltips;
  G6 settings-only export.

## 8. Out of scope for this audit

Profiles (#1), export/import (#3 — package format, round-trip,
verification), the window as a whole (#4), the CLI as a whole (#5),
installer + icon (#6), MetaMorphAi hooks (#7), and the training
engine (Item 3, in flight — audited after v0.2 ships). W1's fix must
cover the profile detail panel too (same missing dirty check);
W4/W8/D10 share their fixes with profiles.
