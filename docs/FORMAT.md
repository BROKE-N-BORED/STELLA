# STELLA package format

A STELLA export is a folder you can keep, share, or move to another
PC. This file is the format's definition, so a hand-editing user can
read it and so later versions never drift into two formats.

## Layout

    <project>-stella-export/
      manifest.json       # profile + project + versions (the record)
      README.md           # human summary: what this is, how to use it
      weights/            # the trained LoRA adapter, when training has
                          # run. Ships a placeholder note until then —
                          # Stella never pretends weights exist.
      checkpoints/        # copied from the project, if any exist
      probe_results.json  # refusal-probe before/after, if run
      sleep/              # sleep cycles (adapters, manifest, replay
                          # reports), if any were run
      notes.md            # the project's notes, if any

No `config.json`: v0.1-v0.12 exports carried one (a copy of the
manifest's settings), but nothing ever read it — import always
took the settings from the manifest — so v0.13 stopped writing it
(T60). Old packages that carry it still import; the file is
ignored.

## Format version

The manifest carries `format`, a whole number, separate from the app
version (`stella_version` records which Stella wrote the package;
`format` says what shape the package is). This Stella writes
format 1 and reads format 1.

- A package with a HIGHER format is refused on import with "this
  package needs a newer Stella". An older Stella must never import
  a newer package silently and lose what the newer format carries
  (the first weights-carrying export is exactly the case the check
  exists for).
- A package with NO `format` field is a legacy package (written by
  v0.1-v0.12, before format versioning) and reads as format 1 —
  the shape is the same, so it imports as usual.
- A package with a `format` that is not a whole number, or below
  the supported range, is refused as a bad manifest.

## Kinds

Four kinds share one manifest shape, so profile, recipe, and
adapter export never become separate formats:

| `kind` | What it is | Status |
|---|---|---|
| `stella-export` | Project package: one profile block + one project | Importable now |
| `stella-profile-export` | Profile package: a profile with all its projects (T86) | Importable since v0.18.0 |
| `stella-recipe-export` | Recipe package: a reusable training recipe (T170) | Importable since v0.22.0 |
| `stella-adapter-export` | Adapter package: bare trained adapter weights (T173) | Importable since v0.22.0 |

An unknown `kind` is refused as not a Stella export.

## Manifest shape (format 1, project package)

```json
{
  "stella_version": "0.18.0",
  "format": 1,
  "kind": "stella-export",
  "exported_at": "2026-11-14T11:00:00Z",
  "profile": {
    "name": "lfm3-tool",
    "display_name": "LFM3 Tool Seat",
    "role": "fast",
    "ollama_tag": "lfm3:1.7b",
    "base_ref": "LiquidAI/LFM3-1.7B",
    "processor": "",
    "config": {},
    "dependencies": [],
    "created": "2026-11-12T09:00:00Z",
    "updated": "2026-11-14T10:00:00Z"
  },
  "project": {
    "name": "tool-calls",
    "display_name": "Tool calls",
    "dataset_ref": "forge-traces.jsonl",
    "settings": {"rank": 8, "learning_rate": 0.0002, "...": "..."},
    "settings_source": "auto",
    "metamorph": {"mode": "morph", "notes": ""},
    "status": "draft",
    "created": "2026-11-12T09:05:00Z",
    "updated": "2026-11-14T10:00:00Z"
  },
  "files": {
    "README.md": {"size": 512, "sha256": "…"},
    "notes.md": {"size": 40, "sha256": "…"}
  }
}
```

- `profile.name` and `project.name` are slugs (lowercase letters,
  numbers, dashes, underscores). Import normalizes them once, so
  the returned names match the stored names.
- `project.status` is one of the project lifecycle statuses (see
  the model: `draft`, `ready`, `training`, `paused`, `done`,
  `failed`, `exported`). A legacy `trained` status (written by
  v0.12 and earlier) reads as `done`. Anything else is refused on
  import.
- `project.metamorph.mode` is one of `morph`, `compress`, `both`.
- `project.settings` holds the training settings; the model
  validates their values on import, before anything is created,
  so a bad value cannot strand a half-created profile behind it.
- `project.settings_source` (v0.28.0, R88) is `auto` or `manual`:
  whether the settings were picked by the PC or set by a human.
  An `auto` project re-resolves its settings for the importing PC
  instead of freezing the source PC's values. Packages that
  predate the field (v0.27.0 and earlier) have no field, and
  import as `manual`, as before.
- `exported_at` (v0.18.0, T118) is when the package was made, in
  UTC ISO form. `profile.created` / `profile.updated` and
  `project.created` / `project.updated` are the records' own
  stamps, restored on import; a package without them imports as
  before, with fresh stamps. `source_machine` (v0.21.0, T179) is
  the hostname of the machine that made the package, shown in the
  import preview when present. `profile.last_used` (v0.21.0,
  T165) is when a training run last started under the profile,
  restored on import like the other stamps.
- `files` (v0.18.0, T104) lists every file in the package except
  `manifest.json` itself, each with its size in bytes and its
  SHA-256 hex digest — the adapter, checkpoints, notes, probe
  results, sleep cycles, and the bundled dataset when one
  travels with the package. Import verifies every listed file:
  a missing file refuses the import as incomplete, a changed
  file refuses it as damaged, both naming the file. Extra files
  not in the list are ignored. A package with no `files` list
  (written before v0.18.0) imports as before, unverified.

## Profile packages (v0.18.0, T86)

A profile package is a folder `<profile>-stella-profile-export/`
with the same manifest shape, except the `project` block is
replaced by a `projects` list of project blocks, and each
project's payload (weights, checkpoints, notes, probe results,
sleep) lives under `projects/<slug>/`. Datasets are referenced,
never bundled. A profile package with no projects carries an
empty list. The profile notes travel at the package root as
`profile-notes.md` (v0.21.0, T166) when the profile has any; on
import they are restored only when the profile is newly created
— an existing profile keeps its own notes. Import restores the
profile and every project in one atomic step; it refuses while
any of the package's projects already exist in that profile,
naming them.

## Recipe packages (v0.22.0, T170)

A recipe package is a folder `<project>-stella-recipe-export/`
holding the training recipe and nothing else: the profile block,
the project block (dataset reference, settings, metamorph mode +
notes, project notes), the README, and `notes.md`. No weights, no
checkpoints, no probe results, no sleep cycles — a recipe is
small on purpose, so it can be shared and re-run anywhere.
Importing a recipe creates a new project with those values (the
same profile merge and collision choices as a project import). A
dataset that is not on the importing PC warns at import, but
never blocks it — the recipe still lands, and the dataset can be
found later.

## Adapter packages (v0.22.0, T173)

An adapter package is a folder `<project>-stella-adapter-export/`
holding bare trained adapter weights plus a manifest `adapter`
block: the adapter name and display name, the base it was trained
on (`base`, the profile's base_ref or Ollama tag), the rank, the
dataset name and reference, the status, and the training summary
(steps and final loss from the latest checkpoint). The weights
travel under `weights/`; there is no project payload beyond that.
Importing an adapter lands it in a project with the same base —
either a new project created around it (named after the adapter,
with the adapter's rank and dataset reference, status `done`), or
an existing project the user picks. The base must match: an
adapter trained on one base never lands on a project for another.
A target that already has a trained adapter refuses the import;
a new-project import whose name is taken lands under a copy name
(`<name>-copy`, then `-copy-2`, ...), never refusing.

## Single-file packages (v0.22.0, T171)

Any package kind can travel as one file: a `.stella` zip holding
exactly the folder package — the same manifest, the same members,
at the zip root (manifest.json at the top, not nested). Export
writes the zip with `stella export --zip` (or the File menu's
"as single file" entries); import, verify, check, and preview
read a `.stella` file exactly like a folder. A zip whose members
escape the package folder (a `../` member) is refused whole —
no partial extract.

## Import rules

- The profile is created from the manifest when it does not exist
  yet. When it DOES exist, the manifest's profile block is
  compared with the local one (tag, role, base): identical blocks
  import silently; differing blocks ask (keep local, or take the
  package's) instead of silently dropping the package's values.
- The project must not already exist in that profile — unless the
  user chooses otherwise (v0.18.0, T117): import as a copy under
  a new slug (`<name>-copy`, then `-copy-2`, ...), or replace,
  moving the old project to the trash first. With no choice the
  import refuses, naming the options.
- Import is atomic: a failure anywhere leaves the home exactly as
  it was (a profile created by a failed import is removed again).
- `weights/` and `probe_results.json` round-trip: the adapter and
  the refusal evidence travel with the fine-tune. A package whose
  manifest claims a finished status but carries no weights imports
  as a draft, with a warning — a project with no weights must not
  claim to be finished.
