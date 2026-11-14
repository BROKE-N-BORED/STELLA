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
- v0.6.0 provider chat (2026-11-13): a Chat window (Menu, then
  Chat) where an AI chat sets up and runs training for you, walking
  the 8-step training template one step at a time. Say just do it
  and it runs the whole thing. Pick the chat model in Settings.
  `stella-cli chat` is the same agent as a terminal chat.
- v0.7.0 provider connections (2026-11-13): the chat can also talk
  to Groq, Gemini, or any OpenAI-compatible service with your own
  key. Add keys in Settings under AI providers; they stay on this
  PC in a private file. `stella-cli chat --provider groq --model
  <name>` is the terminal form.
- v0.8.0 smaller models (2026-11-13, completes the v0.5 scope): make
  an installed model smaller with `bash stella-cli requant <tag>`
  (a new, smaller copy; the original is untouched), and teach a
  small model from a big one with `bash stella-cli distill
  <profile> <project> --teacher <tag> --prompts <file>` (the
  teacher's answers become the project's dataset). The Chat can
  run both jobs too: just ask it.
- v0.9.0 auto-config backend (2026-11-13): Stella measures this PC
  (CPU, RAM, disk, load) and picks the training settings for it —
  new projects get the right recipe with no knobs to turn, and
  training re-checks the PC at every run start. `bash stella-cli
  pc-info` shows what the PC can do and which settings Stella
  picked. Import/export is strict and atomic (a bad package is
  refused cleanly and leaves nothing behind), settings are
  validated the same way everywhere, and the Project window falls
  back to the usual value with a note when a stored value is bad
  instead of crashing.
- v0.10.0 guards and honesty (2026-11-13): the RAM guards estimate
  before loading anything (training from the model's config +
  weight sizes, the merge from base + merged copy + headroom),
  training is reproducible (same seed, same adapter; pause/resume
  is bit-identical), `--steps` is a real cap, and the destructive
  paths ask or refuse instead of silently destroying finished
  work — re-training a trained project needs `--force`, re-exporting
  over an existing GGUF needs `--force`, and resume on a trained
  project announces the extension first. Damaged manifests show
  as rows instead of vanishing, and the Profile/Project windows
  warn about unsaved edits.
- v0.11.0 UI rebuild, P0 slice (2026-11-14): the main screen is
  pick a model, pick a job, press go — one hero tile, no
  scrolling at 1100x680, with a first-run setup checklist
  (pick a model, get its weights, run a tiny first training)
  for an empty store. Training settings left every screen: the
  backend picks the recipe and nothing in the UI names a
  setting. The model picker shows what each model does plus a
  fit verdict for this PC, with nothing selected by default. A
  real menu bar (File, View, Help) replaces the Menu button,
  with actions disabled until they can work. Training shows a
  live loss curve plus speed, RAM, time left, and epoch, and
  the last run's curve is still there after it finishes.
- v0.12.0 UI rebuild, P1 slice (2026-11-14): every job runs as
  a card under the hero, with progress, a live status line, and
  a Cancel button; a second job is refused in plain words. The
  chat picks its model with clickable buttons, shows its plan
  before it runs, and streams its replies. The session follows
  the profile. Tree rows show full names with a health dot per
  profile. The download row lives in the main window only, and
  is honest about a missing repo. Sections collapse, Save stays
  visible, and STELLA has its own dark-and-gold look with
  keyboard shortcuts and a visible focus ring.
- v0.13.0 export/import + projects (2026-11-14): packages carry
  a format version, weights and probe results round-trip, and
  the profile block is merged on import (keep yours or take
  the package's) instead of dropped. Deletes go to a trash
  you can empty from the File menu. One job runs at a time,
  closing waits for workers, and projects have one status
  vocabulary (draft, ready, training, paused, done, failed,
  exported). The CLI explains every flag with a worked
  example, and training reports cheap mistakes before the
  dependency gate.
- v0.14.0 models + UI polish (2026-11-14): the model list is
  cached and fetched off the UI thread, so clicks never wait
  on Ollama; imports show a preview first and warn when the
  base model is not installed; datasets are validated where
  they are picked; export offers to bundle the dataset; the
  Train panel resets per project and stays with the running
  one; and the window gets a finish moment, loading states,
  a job morph, and reduced-motion and larger-text presets.
- v0.15.0 installer coherence (2026-11-14): the installer is
  honest now — venv failures name the real cause, pip failures
  end with a Stella line instead of raw pip output, disk space
  is checked before downloading, and a failed install leaves
  no launcher behind. Installs are pinned (PySide6 6.12.0,
  torch 2.15.0+cpu) with a receipt recording what landed, the
  icons live in the hicolor theme at every size, and there is
  a double-click installer, an uninstaller, and `stella
  doctor` to repair an install after the folder moves.
- v0.16.0 pre-train estimates + probe cluster (2026-11-14):
  the Train panel shows a dataset health line and a RAM/time
  estimate before a run starts, with an Estimate button (and
  `stella train --dry-run`) for the full dry run; a tiny
  dataset asks before training. The refusal probe is
  informational for most profiles and a gate for governing
  seats (a failed gate exits 3), its results carry provenance
  and 6 hard-benign prompts, the evidence opens in a dialog
  after each run, and Export GGUF previews the before/after
  replies before committing. A proof-run button starts a
  5-step smoke test, and finished runs report the val loss
  next to the training loss.
- v0.17.0 training-engine honesty (2026-11-14): resume warns
  when settings drifted since the pause or the optimizer file
  is gone (settings are snapshotted into every checkpoint);
  the probe prints a line per pass, GGUF export a line per
  phase, and a paused run says "Paused after N steps"; the
  converter and quantizer time out after 30 minutes naming
  the hung step; the GGUF pre-flight refuses an architecture
  the installed converter does not support before the merge;
  completions end with the chat template's turn terminator;
  the printed `ollama create` command works with spaced
  paths; library warnings stay off stderr; and the mode a run
  trained with is recorded in its summary and adapter config.
- v0.18.0 export/import/clone (2026-11-14): profiles export
  and import whole (File > Export profile, `stella
  export-profile`); packages carry checksums and timestamps
  and are checked before import (`stella verify`, File >
  Check package); export and import run on the job card with
  progress and cancel; collisions are choices (overwrite
  prompt, import as a copy, replace to trash); projects clone
  and start from templates (first template: LFM3 tool-format);
  the CLI can rename, delete, update, and show profiles and
  projects; a second Ctrl+C exits a run at once; and project
  notes keep a rotating backup (notes.md.1).
- v0.19.0 profiles/roles/chrome (2026-11-14): profiles clone
  (Profile window > Clone, with an offer to copy the projects
  too); the role field is a combo over one canonical seat list
  (driver, reviewer, vision, fast, tester, all-rounder,
  utility — unconfirmed with Joshua, so other roles are still
  allowed and flagged as custom); a profile can be bound for a
  Forge governing seat, and a bound profile warns before
  training unless its base is abliterated; config and
  dependencies are editable in the profile window and through
  `update-profile`; the project window shows the stored mode
  with a "Why this mode" notes field; delete dialogs name the
  item and count what goes with it; empty lists say what to do
  next; the splitter cannot lose a pane; and the dead
  `settings["notes"]` key is gone (old manifests migrate on
  read).
- v0.20.0 checkpoints + run history (2026-11-14): checkpoints
  are managed now, each row showing its step, loss, size, and
  date, with resume from any checkpoint, delete, and pruning
  down to the newest few with the space freed shown; past runs
  list with their final losses and a click draws the run's loss
  curve; the window says "Loading <model>..." while the base
  loads instead of sitting silent; the export button shows what
  the export will cost before you commit; training learns from
  every assistant turn, not just the last, and accepts
  tool-call traces; the train/check split stays stable as rows
  are added; and big datasets validate without loading the
  whole file into RAM.
- v0.21.0 profiles/rows/provenance (2026-11-14): the Train panel
  has the CLI's options in the window (a step cap, per-run dataset
  and base overrides, a quant choice and a checkpoint picker on
  Export GGUF); profile rows show a tag-health marker (installed,
  missing, Ollama down, no tag) next to the weights dot, and the
  project count; project rows show the dataset file and the slug
  when two projects share a name; the Profile window shows what
  the profile points at (size, quant, context, capabilities from
  Ollama), the dates, and a last-used date stamped when a training
  run starts; profiles have notes of their own, which travel in
  profile exports; exports report their size and refuse when the
  disk will not fit; packages name the machine that made them,
  and the home keeps an import/export history log. F2 renames the
  picked row (double-click still opens it), and the Project
  window's Notes sit at the top, visible without scrolling.

## Install

Unzip a release anywhere, then double-click **Install Stella** in the
folder (the file is `Install Stella.desktop`, next to `install.sh`).
If double-clicking opens a text editor instead, right-click the file
and choose Allow Launching, then double-click it again. Or run one
short command in a terminal inside the folder:

`bash install.sh`

That sets up Stella's own Python environment, puts **Stella** in the
app menu with its ✨ sparkles icon, and puts a **Stella** icon on the desktop.
After that, just click it — no terminal needed to run Stella.

To launch from a terminal instead:

`bash run.sh`

The `stella` command works after install — open a new terminal
first (or log out and back in), because Mint only adds
`~/.local/bin` to PATH at login. A terminal already open at install
time will not find `stella` until then.

## Upgrade to a new version

Unzip the new version somewhere, run its `install.sh`, then delete
the old folder. The new install re-points the menu launcher and the
`stella` command at the new folder; deleting the old folder removes
its old venv too, so nothing is left orphaned. Your data lives in
`~/.stella`, not in the folder, so it survives the upgrade untouched.
Re-running `install.sh` in the same folder is safe too — it is
idempotent and just refreshes the install.

## Moved the folder? Repair it

Everything the installer writes points at the folder it ran from,
so moving the folder leaves a dead menu entry and a dead `stella`
command (the window itself still runs from the new location with
`bash run.sh`). Fix it from a terminal inside the moved folder:

`bash stella-cli doctor`

The doctor checks the venv, PySide6, launcher, command, and icons,
and re-links what is stale. `stella doctor --check` only reports,
without fixing. Re-running `bash install.sh` from the new folder
repairs it the same way.

## Remove Stella

From a terminal inside the Stella folder:

`bash uninstall.sh`

That removes the menu launcher, the desktop icon, the `stella`
command, the menu icons, and the Python environment. Your data in
`~/.stella` is kept unless you say to remove it — the uninstaller
asks, and the default answer is No. Delete the folder afterwards
to finish removing it.

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
  vision…) so the roster reads by job, not by cryptic tag — the role
  field offers one canonical seat list (driver, reviewer, vision,
  fast, tester, all-rounder, utility), and a role outside it is kept
  and flagged as custom. A profile can also be **bound for a Forge
  governing seat** (driver, reviewer, tester, fast): a bound profile
  warns before training unless its base is abliterated, and its
  refusal probe runs as a gate. The Ollama tag stays the identifier
  underneath. For training, a profile also carries a **base ref**: the
  Hugging Face repo of the base weights (e.g. `LiquidAI/LFM3-1.7B`),
  or a local folder of HF weights. Training never starts from a GGUF
  or an Ollama tag — fine-tuning needs transformers weights.
- **Projects** — fine-tunes live inside a profile as projects: own
  dataset, training settings, checkpoints, notes, fully customizable.
- **Export** — a finished fine-tune exports as a usable package
  (manifest, trained adapter, checkpoints, probe results,
  sleep cycles) and imports back in.

All Stella data lives in `~/.stella/` as plain JSON and Markdown, so
you can read it or fix it by hand. Set `STELLA_HOME` to move it.

Project notes keep one backup: every time notes are saved, the
previous `notes.md` is copied to `notes.md.1` first, so a mistaken
save loses nothing. To get the previous notes back, move the backup
over the notes file: in the project's folder under `~/.stella/`
(`profiles/<profile>/projects/<project>/`), rename `notes.md.1`
to `notes.md`. Only the latest previous save is kept — each save
replaces the backup. Profile notes work the same way, in the
profile's own folder (`profiles/<profile>/`).

Which notes live where: a project has two notes surfaces. The
**"Why this mode"** field in the Project window says why this
project's morph/compress mode was picked (set at creation with
`stella create-project --metamorph-notes`, or later with
`stella update-project --metamorph-notes`); it lives in the
project manifest. **Project notes** (`notes.md`) is the running
log of the fine-tune — anything worth remembering as the work
goes on. The old `settings["notes"]` key is gone: it lived in
the defaults but nothing ever read or wrote it, and old
manifests drop it when they are read.

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
- **Base model**: training loads the base from the profile's Base
  ref — a Hugging Face repo like `LiquidAI/LFM3-1.7B`, or a local
  folder of weights — never from the Ollama tag. The Base ref
  usually follows the tag when it changes, and only differs when
  the training weights live somewhere else.
- **RAM guard**: before loading anything, Stella estimates the run
  from the model's config + weight sizes (never from a loaded
  model): base weights + LoRA gradients + AdamW states +
  activations + 1 GB headroom, and refuses to start if it will
  not fit 8 GB. The merge gets the same treatment (base + merged
  copy + headroom). A full fine-tune of a 1.7B model needs ~28 GB
  of optimizer state alone — it is refused outright, every time.
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
   `bash stella-cli create-project lfm3-tool tool-calls --dataset sample-tool-calls.jsonl`
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

`stella export <profile> <project> <dir> [--bundle-dataset] [--force]`

`stella export-profile <profile> <dir> [--with-projects] [--force]`

`stella import <export-dir> [--profile-merge keep|take] [--preview] [--as-copy] [--replace]`

`stella verify <export-dir>`

`stella create-profile <name> [--tag <ollama-tag>] [--role <role>] [--display <name>] [--base <hf-repo>]`

`stella create-project <profile> <name> [--display <name>] [--dataset <file>] [--template <name>] [--metamorph morph|compress|both] [--metamorph-notes <why>] [--rank N] [--epochs N] [--learning-rate F] [--batch-size N]`

`stella rename-profile <old> <new>`

`stella delete-profile <name> [--purge]`

`stella update-profile <name> [--role <role>] [--tag <tag>] [--display <name>] [--base <hf-repo>] [--config <json>] [--dependencies <a,b>] [--governing-seat <seat>]`

`stella show-profile <name>`

`stella rename-project <profile> <old> <new>`

`stella delete-project <profile> <name> [--purge]`

`stella update-project <profile> <name> [--display <name>] [--dataset <file>] [--metamorph morph|compress|both] [--metamorph-notes <why>] [--rank N] [--epochs N] [--learning-rate F] [--batch-size N]`

`stella show-project <profile> <name>`

`stella train <profile> <project> [--steps N] [--resume] [--force] [--dataset FILE] [--base REF] [--target-modules q_proj,k_proj]`

`stella export-gguf <profile> <project> <dir> [--quant Q4_K_M] [--from-checkpoint N] [--force] [--create]`

`stella probe <profile> <project>`

`stella sleep <profile> <project> [--dream] [--dream-model TAG] [--rows FILE] [--threshold 0.10]`

`stella sleep-status <profile> <project>`

`stella chat [--provider ollama|groq|gemini|custom] [--model <name>]`

`stella requant <tag> [--quant Q4_K_M] [--as <tag>]`

`stella pc-info`

`stella distill <profile> <project> --teacher <tag> --prompts <file>`

`stella doctor [--check]`

Every command's `--help` shows a worked example, e.g.
`stella create-profile --help`.

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
