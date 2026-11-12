# STELLA ✨

A standalone Linux program for fine-tuning models on your own PC.

Stella is **fresh and separate from StemLab** — same family, different branch.
StemLab trains his own model for key/BPM/instrument ID and clean stem
separation. Stella fine-tunes models: take a base, shape it for its proper
job, export it as a usable package.

## How it works

- **Profiles** — one dedicated environment per base model: weights, config,
  processor/tokenizer, dependencies. The base stays clean and untouched.
  Each profile carries a friendly role name (driver, reviewer, vision…),
  so the roster reads by job, not by cryptic tag.
- **Projects** — fine-tunes live inside a profile as projects: own dataset,
  training settings, checkpoints, notes, fully customizable.
- **Export** — a finished fine-tune exports as a usable package
  (weights + config) to run elsewhere, including Code Forge.

## MetaMorphAi, both readings

- **Morphing** — a base model morphs into specialized variants; each
  project is a metamorphosis of its profile.
- **Compression** — "prediction is compression; the same meaning in fewer
  tokens" — applied to fine-tune storage and serialization.

## First route

Audit the Code Forge roster for strengths, weaknesses, and wasted
performance, then attune each model to its proper seat and cut dead
weight so Forge performs better. The audit is done:
[docs/audit-forge-roster-2026-11-12.md](docs/audit-forge-roster-2026-11-12.md).
First fine-tune target: LFM3 1.7B (smallest dense model, most CPU-feasible
LoRA).

## Hardware

Built for a CPU-only Linux Mint PC: Ryzen 3 3250U, 8 GB RAM, no GPU.
Fine-tuning here means small models and micro-LoRA, checkpointed and
resumable. Anything bigger genuinely needs a free cloud GPU — Stella's
export accepts adapters trained elsewhere too.

## Status

- Item 1 — Forge roster audit: done, verified.
- Item 2 — Stella v0.1 skeleton (profiles, projects, export, Qt GUI):
  building.
