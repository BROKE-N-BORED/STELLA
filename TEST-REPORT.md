# STELLA v0.2 — Test Report

Verified 2026-11-12 in the sandbox (Python 3.12.3, PySide6 6.12,
offscreen Qt; training stack torch 2.15.0+cpu, transformers 5.22.2,
peft 0.21.2, accelerate 1.15.0). Every check below was run, not assumed.

## Suite: 110/110 green

`bash run_tests.sh` (pytest, from the build tree and from a fresh unzip).
On a base install (PySide6 only) the training tests that need torch
skip cleanly — the suite still goes green; the full 110 run after
`bash install-training.sh`.

- `tests/test_model.py` (30) — profile/project CRUD, rename (incl.
  the projects' stored profile pointer), delete, notes round-trip,
  slug validation (rejects `..`, `a/b`, spaces, dots, over-long
  names; lowercases input), metamorph mode validation, path-escape
  blocking.
- `tests/test_export.py` (11) — export folder structure (manifest,
  config, README, weights, checkpoints, notes), checkpoint copy,
  existing-dir refusal, verify accepts good / rejects missing
  manifest, bad JSON, unknown metamorph mode, full round-trip into a
  fresh home (profile + project + settings + notes match), import
  into an existing profile, duplicate-project rejection.
- `tests/test_cli.py` (14) — `profiles`, `projects`,
  `create-profile` (incl. `--base`), `create-project`, `export`,
  `import`, `train`/`export-gguf`/`probe` error paths (no base ref,
  no adapter, missing deps), `--version`, bad-name exit 1,
  missing-project exit 1, and the CLI-through-symlink regression test.
- `tests/test_gui.py` (13) — window opens with three panes, role +
  tag show in the profile list, detail fills from selection, save
  profile / save project write through to disk, empty-store window,
  no `&` in any visible label, window grabs a real frame, the status
  bar is the only status surface, and the Train panel: widgets
  exist, Start without deps logs the install hint (no worker
  started), Use sample dataset sets the ref, progress updates.
- `tests/test_ollama.py` (3) — model list from a fake localhost
  Ollama server, empty list when Ollama is down, empty list on a bad
  payload.
- `tests/test_train.py` (23) — dataset validation (both formats,
  bad JSON names its line, bad role, last message must be assistant,
  mixed formats rejected, too small rejected), the bundled sample
  dataset validates (20 examples, 14 tool calls / 6 plain),
  deterministic splits, RAM math (LFM3 LoRA fits 8 GB, a full
  1.7B fine-tune is refused, boundary exact), the deps gate names
  install-training.sh, dataset resolution finds the sample,
  LoRA target auto-detection on a tiny GPT-2 (c_attn, c_fc, c_proj),
  a REAL 3-step LoRA run on a tiny random model (adapter saved,
  checkpoints step-1/2/3, loss log, status trained, all event
  kinds), pause-then-resume completing 6 steps across 2 epochs,
  GGUF base and Ollama-tag base both refused, resume with no
  checkpoints refused.
- `tests/test_gguf.py` (8) — llama.cpp discovery (found + missing
  with install hint), convert + quantize through a fake runner
  (both commands, F16 intermediate, Q4_K_M output), non-HF dir
  refused, Modelfile + `ollama create` command, a REAL adapter
  merge on a tiny model (merged config + safetensors), the full
  export end to end with fakes (Modelfile, gguf-export.json, status
  exported), export with no adapter refused.
- `tests/test_probe.py` (8) — refusal phrases detected, plain
  answers not refusals, the 12-prompt set is all benign, counting
  with a fake generator (2/12 refusals), the gate passes on a flat
  or falling rate and fails on a rise, a before/after project probe
  with fakes (0 before, 3 after, delta +0.25, results saved),
  probe with no adapter refused.

## Fresh-unzip check

Unzipped `stella-v0.2.zip` to a clean directory: exec bits survived
extraction (`install.sh`, `install-training.sh`, `run.sh`,
`stella-cli`, `run_tests.sh` all `rwxr-xr-x`), and the suite runs
110/110 green from the fresh tree.

## Installer check (sandbox, fake HOME)

`bash install.sh` from the fresh unzip: creates the private `.venv`,
installs PySide6-Essentials, passes both fatal import checks, writes
`~/.local/share/applications/stella.desktop` (absolute Exec/Icon,
quoted so install paths with spaces still launch) and a desktop copy,
links `stella` into `~/.local/bin`, exits 0. If `python3-venv` is
missing, the installer says so and names the fix
(`sudo apt install python3-venv`) instead of failing cryptically.

## Installed-app check

Through the installed `stella` command (fake HOME + fake PATH):
create profile, create project, list both, export to a folder, import
the package into a second fresh home, list again — full round-trip OK.
The GUI was driven from the installed venv (offscreen): window renders
1100x680, three panes populated, role/tag/detail all correct, and the
Train panel renders with all controls (dataset buttons, Start/Pause/
Resume, progress bar, checkpoints, Export GGUF, refusal probe, log).

## Training-stack check (sandbox)

`bash install-training.sh` installs torch CPU + transformers + peft +
accelerate into the private venv and passes its import check (torch
2.15.0+cpu, transformers 5.22.2, peft 0.21.2, accelerate 1.15.0).
The training tests that need the stack ran against it: the tiny-model
LoRA run, pause/resume, adapter merge, and probe all passed.

## Defects found and fixed in place

1. LoRA target expectation: the first test run asserted GPT-2 targets
   were `["c_attn", "c_proj"]`, but the detector also correctly found
   `c_fc` (the MLP intermediate projection is LoRA-able too). The
   code was right; the test expectation was wrong — fixed to
   `["c_attn", "c_fc", "c_proj"]`.
2. Slow dependency gate: `training_deps_missing()` imported torch to
   check for it, which takes 10+ seconds and timed out the CLI
   subprocess test at 60s. It now uses `importlib.util.find_spec`
   (no import) — the gate answers in under a second; the real
   imports happen when training actually starts.
3. `run_tests.sh` on a bare checkout: the GUI tests need PySide6,
   which the script did not install (only pytest). It now installs
   PySide6-Essentials when the import fails, so the suite runs from
   a fresh unzip. Training tests skip cleanly without the training
   stack.
4. `install-training.sh` robustness, from the sandbox install that
   built the test venv: pip's default 15s read timeout repeatedly
   failed the torch download, so both install lines now carry
   `--timeout 120 --retries 10`. And the printed pull-weights hint
   used system `python3`, which has no huggingface_hub — it now
   names the venv python, which has it (via transformers).

## Still needs Joshua's real-PC verdict (the Item 3 closer)

- The LFM3 proof run itself: `bash install-training.sh`, profile
  with base ref `LiquidAI/LFM3-1.7B`, sample dataset, `stella train`
  (hours on CPU — watch the loss fall), `stella probe`, llama.cpp
  install, `stella export-gguf`, `ollama create`, and a live test
  in Forge (one clean tool call, no fenced JSON). The sandbox proved
  the pipeline on a tiny random model only; no 1.7B weights were
  downloaded or trained here.
- LFM3 loads with `trust_remote_code=True` (its config maps the
  model to remote modeling code) — untested until the real pull.
- The visible window on his Mint desktop (sandbox only proves
  offscreen rendering), Nemo double-click install, the app-menu icon.
- The Ollama tag picker against his real Ollama (sandbox used a fake
  server + the offline fallback).
- PySide6 + training-package install times on his machine (one
  download each at install).
