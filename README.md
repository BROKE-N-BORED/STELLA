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
- Item 4 — Stella v0.3 sleep phase: done, verified in the sandbox.
  Consolidate new rows into a fresh LoRA adapter per cycle, dream
  synthetic rows from the local Ollama model, and check every cycle
  against old rows before accepting it. Same closer as Item 3 — the
  real LFM3 sleep run happens on your PC.
- v0.3.1 usability patch (2026-11-13, from the first real-PC run):
  New Profile is a real window that asks for one thing (pick a
  model); every profile and project field explains itself in plain
  words; new ✨ icon; installer fixes (unquoted Icon=, trusted
  desktop launcher, no launch timeout).
- v0.4.0 redesign (2026-11-13): Menu button + collapsible profile
  tree + training session main area, with Profile, Project,
  Settings, and How to Use windows of their own. One-click model
  downloads (Download model button, progress + Cancel, resumes
  after a stop). Built-in How to Use index. Debug report button in
  Settings. Single instance, geometry memory, delete confirms
  default to No.

## Install

Unzip a release anywhere, then double-click **Install Stella** in the
folder (or run one short command in a terminal inside the folder):

`bash install.sh`

That sets up Stella's own Python environment, puts **Stella** in the
app menu with its ✨ sparkles icon, and puts a **Stella** icon on the desktop.
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
  (manifest, config, trained adapter, checkpoints, probe results,
  sleep cycles) and imports back in.

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

## Sleep (v0.3)

When new examples arrive, you don't retrain from scratch — you
sleep on them. A sleep cycle is an offline background job: slow is
fine, but it must fit in RAM and never forget what the model
already knew.

- **Consolidation** — Stella trains a NEW low-rank LoRA adapter
  (rank capped at 8) on the new rows only — rows added to the
  dataset since the last sleep, tracked by content hash in a sleep
  manifest. The base and all prior adapters stay frozen. Each cycle
  stores its adapter, checkpoints, rows, and report under
  `sleep/cycle-N/`. An interrupted cycle resumes instead of
  restarting.
- **Dreaming** (optional, `--dream`) — the local Ollama model
  writes its own practice examples, seeded by real ones. Every
  dreamed row must pass the same validation as real data, must not
  duplicate a real or already-dreamed row, and dreamed rows are
  capped at the number of real rows in the cycle (at most 10 per
  call). If Ollama is down, dreaming is skipped with a plain
  message and sleep still runs on real rows — never a crash, never
  a hang.
- **Replay check** (the forgetting guard) — before a cycle is
  accepted, the new adapter is evaluated on a held-out mix of OLD
  validation rows (kept from prior cycles) and NEW validation
  rows. If the old loss degrades more than 10% (relative,
  configurable with `--threshold`), the cycle is flagged DEGRADED
  in its report and the cycle list — still saved, never silently
  accepted as good. The replay loads the base model ONCE and
  evaluates old-then-new sequentially; it never loads two models
  at once (two LFM3 loads would be ~7 GB on an 8 GB machine).
- **Status** — `stella sleep-status <profile> <project>` lists
  every cycle (rows, dreamed rows, old-loss delta, OK/DEGRADED)
  and how many dataset rows are still awake. The window's Sleep
  panel shows the same list; click a cycle to read its report.
- **Export** — sleep cycles travel with the export (manifest +
  every cycle's adapter, rows, and replay report) and import
  restores them whole.

What Stella Sleep IS and IS NOT (read this before trusting it):

- It implements the two stages of Google Research's sleep
  framework ("The sleep framework", blog Oct 27, 2026; "Language
  Models Need Sleep", Behrouz et al., arXiv 2606.03979) at
  Stella's scale. Google published NO code, and their numbers are
  the authors' own — not independently reproduced. Stella does
  NOT claim to reproduce Google's results. Their own ablation
  credits dreaming with ~78% of the fact-learning gain while
  consolidation drives reasoning and long-context — at Stella's
  scale, with a 2B local model doing the dreaming, expect far less
  than that.
- No RL refinement — SFT only. Reinforcement learning on top of
  dreaming is not feasible on a CPU-only 8 GB machine.
- No MoE routing — Ollama cannot route LoRA experts. A sleep
  adapter becomes usable the same way any adapter does: merged
  into the base through the GGUF export path.
- Dreaming quality depends entirely on the local model doing the
  dreaming. A weak dreamer writes weak rows; the validation,
  dedupe, and cap are there to limit the damage, not to guarantee
  good data.

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

`stella sleep <profile> <project> [--dream] [--dream-model TAG] [--rows FILE] [--threshold 0.10]`

`stella sleep-status <profile> <project>`

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
