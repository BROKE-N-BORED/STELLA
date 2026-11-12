# STELLA ✨

A standalone Linux program for fine-tuning models on your own PC.

Stella is **fresh and separate from StemLab** — same family, different branch.
StemLab trains his own model for key/BPM/instrument ID and clean stem
separation. Stella fine-tunes models: take a base, shape it for its proper
job, export it as a usable package.

## Status

- Item 1 — Forge roster audit: done, verified, pushed.
  [docs/audit-forge-roster-2026-11-12.md](docs/audit-forge-roster-2026-11-12.md)
- Item 2 — Stella v0.1 skeleton (profiles, projects, export, Qt GUI):
  done, verified, shipped.
- Item 3 — first proof loop (LFM3 1.7B micro-LoRA): building.

## Install

Unzip a release anywhere, then double-click **Install Stella** in the
folder (or run one short command in a terminal inside the folder):

`bash install.sh`

That sets up Stella's own Python environment, puts **Stella** in the
app menu with its star icon, and puts a **Stella** icon on the desktop.
After that, just click it — no terminal needed to run Stella.

To launch from a terminal instead:

`bash run.sh`

## How it works

- **Profiles** — one dedicated environment per base model: weights
  reference, config, processor/tokenizer, dependencies. The base stays
  clean and untouched — Stella only ever points at it, never modifies
  it. Each profile carries a friendly **role** name (driver, reviewer,
  vision…) so the roster reads by job, not by cryptic tag. The Ollama
  tag stays the identifier underneath.
- **Projects** — fine-tunes live inside a profile as projects: own
  dataset, training settings, checkpoints, notes, fully customizable.
- **Export** — a finished fine-tune exports as a usable package
  (manifest, config, weights, checkpoints) and imports back in.

All Stella data lives in `~/.stella/` as plain JSON and Markdown, so
you can read it or fix it by hand. Set `STELLA_HOME` to move it.

## MetaMorphAi, both readings

- **Morphing** — a base model morphs into specialized variants; each
  project is a metamorphosis of its profile.
- **Compression** — "prediction is compression; the same meaning in
  fewer tokens" — applied to fine-tune storage and serialization.

Every project carries a `metamorph` mode (morph, compress, or both),
recorded in its manifest and in every export. The codec itself lands
in a later item — v0.1 carries the structure.

## Command line

After install, `stella` works in a terminal:

`stella profiles`

`stella projects <profile>`

`stella export <profile> <project> <dir>`

`stella import <export-dir>`

Before install, the same commands run as `bash stella-cli ...` from
inside the Stella folder.

## What v0.1 does NOT do yet

No training engine — that is Item 3. v0.1 is the skeleton: profiles,
projects, settings, notes, export and import. A project export's
`weights/` folder ships empty on purpose until training exists.

## Hardware

Built for a CPU-only Linux Mint PC: Ryzen 3 3250U, 8 GB RAM, no GPU.
Fine-tuning here means small models and micro-LoRA, checkpointed and
resumable. Anything bigger genuinely needs a free cloud GPU — Stella's
export accepts adapters trained elsewhere too. First fine-tune target
(Item 3): LFM3 1.7B.

## Tests

`bash run_tests.sh` — 61 tests, all green from a fresh unzip.
See [TEST-REPORT.md](TEST-REPORT.md) for the full verification record.
