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
- Item 3 — Stella v0.2 training engine: done, verified in the sandbox.
  The real LFM3 proof run on your PC is the closer (see below).

## Install

Unzip a release anywhere, then double-click **Install Stella** in the
folder (or run one short command in a terminal inside the folder):

`bash install.sh`

That sets up Stella's own Python environment, puts **Stella** in the
app menu with its star icon, and puts a **Stella** icon on the desktop.
After that, just click it — no terminal needed to run Stella.

To launch from a terminal instead:

`bash run.sh`

## Install the training packages (only if you want to train)

The base install stays light (PySide6 only). Training needs torch,
transformers, peft and accelerate — about a 2 GB download. Run once
in the Stella folder:

`bash install-training.sh`

Without it, the Train panel and `stella train` tell you to run it —
nothing trains silently and nothing downloads on its own.

## How it works

- **Profiles** — one dedicated environment per base model: weights
  reference, config, processor/tokenizer, dependencies. The base stays
  clean and untouched — Stella only ever points at it, never modifies
  it. Each profile carries a friendly **role** name (driver, reviewer,
  vision…) so the roster reads by job, not by cryptic tag. The Ollama
  tag stays the identifier underneath. For training, a profile also
  carries a **base ref**: the Hugging Face repo of the base weights
  (e.g. `LiquidAI/LFM3-1.7B`), or a local folder of HF weights.
  Training never starts from a GGUF or an Ollama tag — fine-tuning
  needs transformers weights.
- **Projects** — fine-tunes live inside a profile as projects: own
  dataset, training settings, checkpoints, notes, fully customizable.
- **Export** — a finished fine-tune exports as a usable package
  (manifest, config, trained adapter, checkpoints, probe results)
  and imports back in.

All Stella data lives in `~/.stella/` as plain JSON and Markdown, so
you can read it or fix it by hand. Set `STELLA_HOME` to move it.

## Training (v0.2)

Micro-LoRA on CPU: rank 4–8, a few hundred examples, batch 1 with
gradient accumulation, checkpointed throughout, resumable. Steps are
slow on a Ryzen 3 — hours for a real run — and that is expected.

- **Dataset**: one JSON object per line (`.jsonl`), either
  `{"prompt": ..., "completion": ...}` or
  `{"messages": [{"role": "user", ...}, {"role": "assistant", ...}]}`.
  Stella validates the file before training starts and names the
  exact line of any bad row. Loss is only on the completion — the
  model learns to write the answer, not to predict the question.
  A bundled sample (`sample-tool-calls.jsonl`, 20 synthetic Forge
  tool-call traces) is in the Train panel for the proof run.
- **RAM guard**: before loading anything, Stella estimates the run
  (base weights + LoRA gradients + AdamW states + activations + 1 GB
  headroom) and refuses to start if it will not fit 8 GB. A full
  fine-tune of a 1.7B model needs ~28 GB of optimizer state alone —
  it is refused outright, every time.
- **Checkpoints**: saved every N steps (default 50) under the
  project's `checkpoints/step-N/`, each with the adapter, the
  optimizer state, and the training state. Pause any time (Pause
  button, or Ctrl+C in the terminal) and resume with `--resume` —
  the run continues from the saved step, optimizer included.
- **Log**: every step's loss goes to the project's `train_log.jsonl`
  and the Train panel's log view; each epoch ends with a validation
  loss on a held-out split.
- **GGUF round-trip**: after training, Export GGUF (or
  `stella export-gguf`) merges the adapter into the base, converts
  with llama.cpp to F16 GGUF, quantizes to Q4_K_M, and writes an
  Ollama Modelfile with the exact `ollama create` command. llama.cpp
  is a separate one-time install (the export names the steps if it
  is missing).
- **Refusal probe**: a built-in set of 12 plainly benign prompts
  (coding help, shell commands, plain questions) run before and
  after tuning, reporting the refusal-rate change. For LFM3 this is
  informational; for a governing-seat tune it is a gate — if tuning
  re-taught refusals, the gate fails the tune.

## The LFM3 proof run (Item 3 closer — on your PC)

The sandbox proved the pipeline on a tiny random model. The real
proof is LFM3 1.7B on your machine, in this order:

1. `bash install.sh` (if Stella is not installed yet)
2. `bash install-training.sh` (about 2 GB, a few minutes)
3. In Stella, make a profile named `lfm3-tool` with base ref
   `LiquidAI/LFM3-1.7B` (role: fast), and a project named
   `tool-calls` with the sample dataset
   (the Train panel's "Use sample dataset" button).
   Or from a terminal in the Stella folder:
   `bash stella-cli create-profile lfm3-tool --tag lfm3:1.7b --role fast --base LiquidAI/LFM3-1.7B`
   `bash stella-cli create-project lfm3-tool tool-calls --dataset sample-tool-calls.jsonl --metamorph both`
4. Pull the base weights (about 3.5 GB) — the first training run
   downloads them on its own if they are not there yet.
5. `bash stella-cli train lfm3-tool tool-calls`
   (or Start training in the Train panel). Watch the loss fall in
   the log. Pause and resume any time.
6. `bash stella-cli probe lfm3-tool tool-calls`
   (refusal rate before vs after — informational for LFM3).
7. Install llama.cpp once if it is not there (the export names the
   steps), then:
   `bash stella-cli export-gguf lfm3-tool tool-calls ~/Desktop`
8. `ollama create lfm3-tool-tool-calls -f ~/Desktop/Modelfile`
   (the export prints the exact command), then
   `ollama run lfm3-tool-tool-calls` and ask it to list files —
   it should answer with one clean tool call, no fenced JSON.

LFM3 notes: its repo ships remote modeling code, so Stella loads it
with `trust_remote_code=True` (the standard Hugging Face flow for
this model; the repo is Liquid AI's own). The model card was
confirmed live: 1.73B params, BF16, 24 layers, 256K context.

## MetaMorphAi, both readings

- **Morphing** — a base model morphs into specialized variants; each
  project is a metamorphosis of its profile.
- **Compression** — "prediction is compression; the same meaning in
  fewer tokens" — applied to fine-tune storage and serialization.

Every project carries a `metamorph` mode (morph, compress, or both),
recorded in its manifest and in every export. The codec itself lands
in a later item — v0.2 carries the structure.

## Command line

After install, `stella` works in a terminal:

`stella profiles`

`stella projects <profile>`

`stella export <profile> <project> <dir>`

`stella import <export-dir>`

`stella train <profile> <project> [--steps N] [--resume]`

`stella export-gguf <profile> <project> <dir> [--quant Q4_K_M]`

`stella probe <profile> <project>`

Before install, the same commands run as `bash stella-cli ...` from
inside the Stella folder.

## Hardware

Built for a CPU-only Linux Mint PC: Ryzen 3 3250U, 8 GB RAM, no GPU.
Fine-tuning here means small models and micro-LoRA, checkpointed and
resumable. Anything bigger genuinely needs a free cloud GPU — Stella's
export accepts adapters trained elsewhere too. First fine-tune target:
LFM3 1.7B.

## Tests

`bash run_tests.sh` — the suite runs on a base install (training
tests that need torch skip cleanly) and in full after
`bash install-training.sh`. See
[TEST-REPORT.md](TEST-REPORT.md) for the full verification record.
