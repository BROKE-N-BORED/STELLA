# STELLA v0.27.0 — Test Report

Verified 2026-11-17 by the coordinator from a FRESH UNZIP of
stella-v0.27.zip (1,165,983 bytes, SHA-256
dc345d04ab412bf7ccabdef2855b0389b0477cf9838e177f60ce8649ebe549e7),
not from the builders' claims. Python 3.12.3, PySide6 offscreen Qt,
forge-v2-testenv; TMPDIR under the workspace (STELLA has no
QFileSystemWatcher, so this is safe).

## Suite: 1749 passed, 65 skipped (1821 collected)

The single-process full run OOMs on this 6 GB VM, so the suite ran
in 4 chunks from the same fresh unzip: non-GUI 1373 passed + 65
skipped + 6 failed, test_gui.py in 3 chunks (129 + 124 + 123
passed + 1 failed). Counts reconcile exactly to the 1821
collected. Of the 7 failures, 4 were real merge defects fixed in
place and re-verified green, and 3 are proven load flakes:

- test_json_sweep_no_command_silently_returns_text[sleep-delete]
  and [sleep-prune]: KeyError — Builder A's R52 sweep map had no
  entries for Builder B's new R66 commands. The product gate
  already refused --json for them correctly; the fix was two
  entries in the sweep's arg map (test-only).
- test_fetch_downloads_a_wheel_from_scratch and
  test_fetch_finalizes_a_complete_partial_file: the fake wheel
  server logged each request AFTER serving the body, so the test
  asserted on the log before the handler thread appended to it
  (the log entry was there by the time pytest formatted the
  failure). The server now logs before serving (test-only).
- test_cli_train_ctrl_c_pauses and
  test_cli_train_second_ctrl_c_exits_at_once: signal timing under
  load. 5 solo runs: fail, fail, pass, pass, split — the pair
  passes when the box is quiet. Same flake as v0.25.0/v0.26.0.
- test_second_main_exits_zero_while_first_runs: second-launch
  timing under load. 3/3 solo. Same flake as v0.26.0.

The fixed tests were re-run from a second fresh unzip of the
rebuilt zip: 27 passed (16 wheel_fetch + 2 sweep + 9 test_v27).

## CLI smoke: green

`stella-cli --version` reports 0.27.0; --help lists sleep-delete,
sleep-prune, save-key, clone-profile, clone-project;
`sleep-delete --help` works; `profiles --json` prints [].

## GUI drive: green

drive_gui.py offscreen: window opens, job buttons Train / Sleep /
Make smaller / Teach a small model, Go, Export GGUF, Run refusal
probe. Screenshot eyeballed clean — and it visibly proves R92:
How to Use opens on Getting started, the topic selected and its
body shown, with the R70 topics (Bridge, Checkpoints, Governing
seats, Recipe and adapter packages) in the list.

## Sweeps

Em-dash sweep of non-docstring string literals: 0 hits. Secrets
grep: clean. Zip modes: all scripts 0o100755, all plain files
0o100644, file-type bits present; all entries deflated.

## Merge notes

Two conflicts, both additive: README.md (kept A's clone-project
line + B's updated train line) and tests/test_v27.py (both
builders created it — combined: B's file as base, one copy of
the version tests + each half's slice tests). The merge caught
two real defects neither builder's green run showed: the JSON
sweep KeyError above, and the R13 desktop training icon — its
Exec used the %k pattern, which resolves to the Desktop folder,
so the Desktop copy was broken since v0.25.0. install.sh now
rewrites the Desktop copy's Exec to the absolute launcher path
(the tree copy keeps the portable %k form), uninstall.sh removes
the Desktop training icon when it names this install, and the
installer tests now double-click the Desktop copy for real.

---

# STELLA v0.26.0 — Test Report

Verified 2026-11-17 by the coordinator from a FRESH UNZIP of
stella-v0.26.zip (1,118,059 bytes, SHA-256
dca72ee7546cf61e9147e59fe20d8f76a7b99aae0e21c5f1ecb95b162eaed215),
not from the builders' claims. Python 3.12.3, PySide6 offscreen Qt,
forge-v2-testenv; TMPDIR under the workspace.

## Suite: 1569 passed, 64 skipped (1633 collected)

The single-process full run OOMs on this 6 GB VM, so the suite ran
in 4 chunks from the same fresh unzip: non-GUI 1205 passed + 64
skipped, test_gui.py in 3 chunks (126 + 119 + 119 passed). Counts
reconcile exactly to the 1633 collected. Zero failures in the
completed runs. A runtime restart killed the first GUI chunk-02
run at ~60% with one unidentified failure showing in the dots;
the full re-run of that chunk is 119/119 green, so it was a load
flake (load average above 25 at the time), not a regression.

## CLI smoke: green

`stella-cli --version` reports 0.26.0; `create-project --help`
still lists `--method` (R28); `export-gguf --help` lists
`--from-sleep` (R3, still there).

## GUI drive: green

drive_gui.py offscreen: window opens, job buttons Train / Sleep /
Make smaller / Teach a small model, Go, Export GGUF, Run refusal
probe, Install training. Screenshot eyeballed clean — and it
visibly proves R41: the status bar reads "Ready." with a live
session, not "Pick a profile to begin."

## Sweeps

Em-dash sweep of non-docstring string literals: 0 hits. Secrets
grep: clean. Zip modes: all scripts 0o100755, all plain files
0o100644, file-type bits present; all entries deflated.

## Merge notes

Two conflicts, both additive: tests/test_gui.py (both builders
added tests at the same spot — kept both) and tests/test_v26.py
(both builders created it — combined: one copy of the version
tests + each half's slice tests). No merge-interaction defects
this version (unlike v0.25.0's R3/R4 modal hang).

---

# STELLA v0.25.0 — Test Report

Verified 2026-11-17 by the coordinator from a FRESH UNZIP of
stella-v0.25.zip (1,081,271 bytes, SHA-256
46d00c4cd486cd4c7fffee4048a352dfa920b3c060d72117562333ae49083e27),
not from the builders' claims. Python 3.12.3, PySide6 offscreen Qt,
forge-v2-testenv; TMPDIR under the workspace (STELLA has no
QFileSystemWatcher, so this is safe).

## Suite: 1485 passed, 64 skipped (1551 collected)

The single-process full run OOMs on this 6 GB VM (killed at ~51%),
so the suite ran in 4 chunks, all from the same fresh unzip:
non-GUI 1134 passed + 64 skipped, test_gui.py in 3 chunks
(122 + 114 + 115 passed). Counts reconcile exactly to the
1551 collected.

Two chunk failures, both proven load flakes by 3/3 solo re-runs:
test_cli_train_second_ctrl_c_exits_at_once (signal timing under a
load average above 10) and
test_job_card_finish_moment_shows_summary_then_hides (250 ms
animation timing under the same load). Neither builder touched the
code under either test.

One real merge-interaction defect, found by the chunked run and
fixed in place: Builder A's new R3 GUI test exported from the
seeded governing profile, and Builder B's R4 gate refuses that
export with a modal warning — the test hung in the modal with no
user to dismiss it. The test now uses a non-governing profile,
exactly like B's T161 test. It passes solo in 14 s and inside the
re-run chunk (115 passed).

## CLI smoke: green

`stella-cli --version` reports 0.25.0; `profiles` gives the
plain-words empty state; `pc-info` picks rank 4 / seq 512 at low
available RAM; `export-gguf --help` lists `--from-sleep`; `chat
--help` works.

## GUI drive: green

drive_gui.py offscreen: window opens, menu bar File/View/Help, job
buttons Train / Sleep / Make smaller / Teach a small model, Go,
Export GGUF, Run refusal probe, Install training button visible,
no settings strings on screen. Screenshot eyeballed clean.

## Sweeps

Em-dash sweep of non-docstring string literals: 0 hits (one new
em-dash in the R3 How to Use text was found and fixed in place).
Secrets grep: clean. Zip modes: all scripts 0o100755, all plain
files 0o100644, file-type bits present; all entries deflated.

## Not verified (needs his PC / real services)

R19–R23 stay hard-gated: the LFM3 proof run, a real sleep-adapter
merge, a real `ollama create` from a Stella export, the literal
double-click of Install Stella.desktop on Mint, and the real 2 GB
training install. Groq/Gemini lists were re-checked against the
providers' pages on build day and tested against fake servers
only — no live key was used.

---

# STELLA v0.3 — Test Report

Verified 2026-11-13 in the sandbox (Python 3.12.3, PySide6 offscreen
Qt; training stack torch 2.15.0+cpu, transformers 5.22.2, peft
0.21.2, accelerate 1.15.0). Every check below was run from a FRESH
UNZIP of stella-v0.3.zip, not assumed. The v0.3 builder was
interrupted before verifying; this report is the finisher's
verification of the finished tree.

## Suite: 142/142 green

`bash run_tests.sh` (pytest, from a fresh unzip).

- Train venv (full stack): **142 passed, 15 warnings, 106.9s.**
- Base install (PySide6 only, no torch): **120 passed, 22 skipped,
  8.2s** — the training tests skip cleanly, the suite still goes
  green.

Per file: test_model 30, test_sleep 24, test_train 23, test_cli 18,
test_gui 17, test_export 11, test_probe 8, test_gguf 8, test_ollama 3.

The 15 warnings are all one known peft warning (`fan_in_fan_out`
on the tiny Conv1D test model) — a test artifact, not a product
issue. The v0.2 `float(out.loss)` requires_grad UserWarning is
FIXED (both occurrences now use `.detach()`).

Note: both suite runs print `malloc_consolidate(): unaligned
fastbin chunk detected` AFTER pytest's summary, with exit code 0 —
a post-run Qt teardown artifact in the sandbox, not a test failure
(the same post-OK teardown abort seen on other Qt suites here).

New in v0.3 (32 tests): test_sleep.py (24) — manifest/hash
round-trips, orphan-report reconciliation, unslept counts, dreaming
(filter/dedupe/cap/Ollama-down skip/no-tag skip), export/import
round-trip of sleep cycles, end-to-end tiny cycles (cycle 1 + a
second cycle replaying against old rows), dreaming with a fake
Ollama server, Ollama-down still sleeps, replay verdicts with
canned losses (DEGRADED at +50%, OK at -10%, exactly +10% is NOT
degraded), the single-load proof (replay loads once; a full sleep
loads twice total — one consolidate, one replay), rank capped at 8,
RAM-guard refusal, pause-then-resume completing the same cycle,
plus the two regression tests for defect 1 below. test_cli.py (+4)
— sleep help, sleep-status with no cycles, sleep with no base_ref
(cheap checks before the dependency gate), sleep with missing deps.
test_gui.py (+4) — Sleep panel widgets exist, cycle list shows a
seeded cycle, start-sleep with no deps logs the install hint,
start-sleep gated on save failure (bad learning rate starts
nothing).

## CLI smoke: 22/22 green (script /tmp/stella-v03-smoke.py)

Driven through `bash stella-cli` exactly as on a PC, from the fresh
unzip: `--version` says 0.3; create-profile/create-project;
sleep-status with no cycles; sleep with no dataset and sleep with a
missing --rows file both exit 1 with a plain error and NO traceback
(cheap checks run before the dependency gate); an API sleep with
dream=True against a fake Ollama server (the CLI has no tiny-model
hook, so the model step runs through the API exactly as the tests
do) completed cycle 1 with 2 dreamed rows kept, 6 real rows, old
losses None on cycle 1 (not faked), manifest 6 slept / 2 dreamed
hashes, and dream + replay + done events; CLI sleep-status then
showed `cycle 1 ... 2 dreamed` and `6 rows slept on, 0 of 6 still
awake`; CLI export carried sleep/ (manifest, cycle-1 report,
adapter) and CLI import into a fresh home restored it whole
(manifest hashes, adapter file, sleep-status shows cycle 1).

## GUI drive: 16/16 green (script /tmp/stella-v03-gui-drive.py)

The real window, offscreen, against the smoke home (a finished
cycle 1): window visible; profile + project listed; Sleep button
present and enabled; "Dream first" checkbox present and unchecked;
cycle list shows 1 item reading `cycle 1 — OK — 6 new, 2 dreamed`;
clicking it opens the report dialog with the real numbers (cycle 1,
OK, 6 new / 2 dreamed, new loss, threshold); no bare `&` in any
visible label; start-sleep with the training deps hidden logs the
install-training.sh hint and starts no worker.

## Defects found and fixed in place (by the finisher)

1. **Resume path crashed on a partially-written cycle dir
   (sleep.py).** `_find_unfinished_cycle` only required
   `train_rows.jsonl`, but the resume branch then read
   `cycle_input.json` with an unguarded `json.loads` + key access
   and `val_rows.jsonl` with no missing-file handling. The
   fresh-cycle path writes train_rows, val_rows, then cycle_input
   in sequence — a crash between the writes left a dir that made
   every later `sleep` die with a raw traceback (FileNotFoundError /
   JSONDecodeError / KeyError — the CLI catches only StellaError).
   Fixed: the finder now requires all three input files (a partial
   dir is ignored and the next fresh cycle reuses its number and
   overwrites it — safe, because no checkpoints or adapter can
   exist before cycle_input.json is written, training only starts
   after it); the cycle_input parse + key access is wrapped and
   raises a plain StellaError naming the cycle and the fix
   (delete the cycle dir, re-run sleep — no rows are lost, they are
   still in the dataset); `_load_rows_file` turns OSError into
   StellaError. Pinned by two regression tests
   (`test_sleep_partial_cycle_dir_self_heals`,
   `test_sleep_corrupt_cycle_input_is_a_plain_error`).
2. **Smoke-script bug (not product code):** the first smoke run
   looked for the export in the given dir instead of the
   `<project>-stella-export` subdir export_project creates, so 6
   checks failed on paths while the export itself was correct
   (the listing showed sleep/ complete with manifest, report,
   adapter, checkpoints). Fixed in the script; re-run 22/22.

No other defects found. The design was checked against the brief
in full: new LoRA adapter per cycle on new rows only (content-hash
manifest, base + prior adapters frozen); dreaming validated,
deduped, capped, skipped cleanly when Ollama is down; replay check
flags DEGRADED past the threshold and never silently passes a
cycle; one model at a time in the replay path (proven by the
single-load tests); RAM guard + checkpoint/resume reused from
train.py; CLI sleep + sleep-status; worker-threaded Sleep panel
with Dream checkbox + cycle list; export/import carries sleep/
whole; README states the honest limits (SFT only, no RL on CPU; no
MoE routing — Ollama cannot route LoRA experts, adapters merge via
GGUF export; Google's numbers are authors'-only, unreplicated).

## Secrets check

Grep of the finished tree for hardcoded keys/tokens/passwords/
credentialed URLs: ZERO matches. No .env, providers.json,
credentials, .pem, or .key files anywhere. Stella talks to local
Ollama and public Hugging Face downloads only. The repo
`.gitignore` (added 2026-11-13) covers .env, providers.json,
credential/secret files, .pem/.key/id_rsa, __pycache__, .venv,
.stella/, and zips.

## Not verified (needs his PC / real services)

- A real LFM3 sleep cycle (sandbox proves the pipeline on a tiny
  random model only — same standing caveat as the v0.2 proof run).
- Dreaming against his real Ollama models (fake server only here).
- Real llama.cpp GGUF merge of a sleep adapter (the merge path is
  the v0.2 one, unchanged).
- The visible window, Nemo double-click install, and app-menu icon
  on his Mint PC (standing v0.1/v0.2 caveat).
- The 120s dream timeout against a slow local CPU model (the
  timeout path itself is proven by the Ollama-down tests).

---

# v0.2 — still applies (installer files unchanged in v0.3)

Verified 2026-11-12 in the sandbox. Kept here because the installer,
installed-app, and training-stack checks were not re-run for v0.3 —
those files did not change.

## v0.2 suite: 110/110 green

test_model 30, test_train 23, test_cli 14, test_gui 13,
test_export 11, test_probe 8, test_gguf 8, test_ollama 3.

## v0.2 fresh-unzip check

Unzipped `stella-v0.2.zip` to a clean directory: exec bits survived
extraction (`install.sh`, `install-training.sh`, `run.sh`,
`stella-cli`, `run_tests.sh` all `rwxr-xr-x`), and the suite runs
110/110 green from the fresh tree.

## v0.2 installer check (sandbox, fake HOME)

`bash install.sh` from the fresh unzip: creates the private `.venv`,
installs PySide6-Essentials, passes both fatal import checks, writes
`~/.local/share/applications/stella.desktop` (absolute Exec/Icon,
quoted so install paths with spaces still launch) and a desktop copy,
links `stella` into `~/.local/bin`, exits 0. If `python3-venv` is
missing, the installer says so and names the fix
(`sudo apt install python3-venv`) instead of failing cryptically.

## v0.2 installed-app check

Through the installed `stella` command (fake HOME + fake PATH):
create profile, create project, list both, export to a folder, import
the package into a second fresh home, list again — full round-trip OK.
The GUI was driven from the installed venv (offscreen): window renders
1100x680, three panes populated, role/tag/detail all correct, and the
Train panel renders with all controls (dataset buttons, Start/Pause/
Resume, progress bar, checkpoints, Export GGUF, refusal probe, log).

## v0.2 training-stack check (sandbox)

`bash install-training.sh` installs torch CPU + transformers + peft +
accelerate into the private venv and passes its import check (torch
2.15.0+cpu, transformers 5.22.2, peft 0.21.2, accelerate 1.15.0).
The training tests that need the stack ran against it: the tiny-model
LoRA run, pause/resume, adapter merge, and probe all passed.

## v0.2 defects found and fixed in place

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
