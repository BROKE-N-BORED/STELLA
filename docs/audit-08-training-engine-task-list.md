# STELLA Audit #8 — Training engine: Task List

**Source:** [audit-08-training-engine-2026-11-13.md](audit-08-training-engine-2026-11-13.md)
(Training engine audit, 2026-11-13, against v0.3 — `train.py`,
`gguf.py`, and `probe.py` in full, plus the tests and CLI/GUI
surfaces that call them; `sleep.py` out of scope).

**This file is a list only.** Nothing here has been fixed or built.
Each task turns one or more audit findings into work with a verifiable
"done". Priorities follow the audit's section 8; within a priority,
tasks are in audit order (weaknesses, then UI flaws, then gaps),
and a fix comes before the polish that depends on it.

**Finding IDs carry the A8 prefix** (audit #8), matching the merged
list. Cross-references to earlier audits keep their own prefixes
(A1-, A2-, A3-, A4-, A5-, R-). References to merged-list tasks are
written "merged T<n>" and use the merged list's numbers as they
stand after the audit #5 merge (142 tasks).

**No P0s:** nothing in this audit loses data or crashes on a normal
path. The headline findings are trust problems, not crashes: no run
is reproducible (W1), the refusal probe is brittle both ways and
passes a silent model (W4, W5), and the GGUF path leaves multi-GB
litter on failure (W13).

**Priority key:** P0 = data loss / silent failure, fix first.
P1 = real functional defect or daily friction. P2 = missing capability
or inconsistency. P3 = polish, display, and scale.

**Effort key:** S = a focused change in one or two files, a day or
less. M = a change across model + GUI + tests, or a small design
decision plus implementation. L = a multi-part build or a design that
needs Joshua's direction on scope first.

**Counts:** 31 tasks — 0 P0, 7 P1, 16 P2, 8 P3.

**Shared fixes with earlier audits:** several findings share their
fix with earlier work and are built once, not twice. The engine
one-job lock (A8-W7/D5) is audit #4's W9, re-probed with the
train-vs-job hole and the OOM math; the engine settings-validation
half (A8-W8/D6) is audit #2's W2 at the loop's conversion points;
the HF error wrapping (A8-W9/D7) is audit #5's W2 at the model
loader; the cap/resume composition (A8-W12/D9) is the resume half
of the --steps cap (verdict R11 / audit #5 W3); and the F16
intermediate cleanup (A8-W13/D10) is the quantize half of the
merged-dir cleanup (audit #5 W6). In this standalone file they
appear as audit #8 tasks (T4, T8, T9, T11, T12); the merged list
([stella-audit-task-list-123.md](stella-audit-task-list-123.md))
folds them into the single shared tasks. A8-D11's quant half is
audit #5's W7 (already a merged task); only its executability half
is a new task (T13). The checkpoint-size evidence (tiny checkpoint
71,440 bytes, optimizer.pt 65% of it; LFM3 rank-8 ≈ 81 MB per
checkpoint) extends the merged checkpoint-management task; it is
evidence, not a finding, and is not counted in the 55 below.

---

## P1 — functional defects and daily friction

### T1 — Seed everything: torch seed at run start + RNG state in checkpoints

- **Covers:** A8-W1, A8-W2, A8-D1
- **Effort:** S
- **Problem:** `train_project` never calls `torch.manual_seed` —
  a grep over `train.py`, `sleep.py`, and `probe.py` finds zero
  seeding calls. The dataset split and the epoch shuffles are
  seeded, but torch's RNG (which drives LoRA dropout, 0.05)
  starts wherever the process left it. Probed: the same fixed
  base weights, loaded fresh from disk with no seeding, trained
  twice with identical settings — final losses 5.6010 vs 5.5737,
  max adapter weight difference **2.424e-01**. That is not noise;
  that is a different adapter. A good run cannot be reproduced,
  a bad run cannot be bisected, and A/B comparisons (rank 4 vs 8,
  lr 1e-4 vs 2e-4) are confounded by dropout draws. The `seed`
  setting promises reproducibility it does not deliver. W2 is the
  same hole across a pause: `_save_checkpoint` (`train.py:553`)
  saves the adapter, the optimizer state, the step, the epoch,
  and examples-seen — but not the torch RNG state. Probed: pause
  after step 2, resume — pre-pause losses match exactly (5.6149,
  5.5667), then diverge from step 3 (5.5648 vs 5.6111) and the
  final adapters differ by 5.2e-04 max. "Pause and resume" is not
  the no-op it presents as, and it compounds W1: even a seeded
  run diverges across a pause.
- **Fix:** D1 — one `torch.manual_seed(seed)` at the top of
  `train_project`, and `torch.get_rng_state()` /
  `set_rng_state()` in `_save_checkpoint` / resume. Two lines of
  code make runs reproducible and pause/resume exact. The
  seeded-loader probe proves the loop is already deterministic
  once the seed exists (bit-identical adapters, diff 0.0).
- **Done:** The same project/settings/dataset run twice gives
  byte-identical adapters; a paused-and-resumed run matches the
  uninterrupted run's losses and final weights. Tests: two-run
  determinism, pause/resume exactness (losses + weights).

### T2 — Minimum-val guarantee, or a loud warning

- **Covers:** A8-W3, A8-D4
- **Effort:** S
- **Problem:** `split_dataset` (`train.py:227`) computes
  `n_val = round(n × val_fraction)`. With the default 0.1: n=2,
  3, 4, 5 all give **val=0** (n=5: `round(0.5)` is 0 under
  banker's rounding). The first val row appears at n=6. Probed
  across n=2..20. Meanwhile `load_dataset` refuses a 1-example
  dataset with "at least 2 are needed (1 to train on, 1 to
  validate)" — but a 2-example dataset trains on 2 and validates
  on 0. No `val` events fire, no val loss is logged, and nothing
  tells the user validation didn't happen. The sample dataset (20
  rows) is fine; a small real dataset silently loses its only
  quality signal.
- **Fix:** D4 — `n_val = max(1, round(n × val_fraction))` for
  n ≥ 2 — or keep the rounding and emit a warning event ("no
  validation rows — dataset too small") the CLI and GUI both
  show. Never silently run with no val set.
- **Done:** A 2–5 example dataset either gets a val row or prints
  a visible warning that it has none; the loader's "1 to train
  on, 1 to validate" promise holds. Tests: n=2..6 split sizes,
  warning event when val is empty.

### T3 — Make the refusal probe trustworthy: detection v2 + chat-template mode

- **Covers:** A8-W4, A8-W5, A8-W6, A8-D2, A8-D3
- **Effort:** M
- **Problem:** The probe's refusal detection is brittle both
  ways (W4): substring matching against 16 markers in the first
  400 chars (`probe.py:65`) cannot tell an apology from a
  refusal, or catch refusals phrased without the markers. Probed
  battery: "As an AI language model, here is the function…",
  "I'm sorry to hear that broke — here's the fix.", "I can't
  believe how easy this is! Here's the code.", and "I apologize
  for the delay. Here is the function." all judged refusals
  (compliant); "Nope, not doing that." and "I refuse to answer
  this." judged compliant (refusals). A model that opens answers
  with "As an AI…" scores refusals it never made; a model that
  refuses bluntly scores clean. The gate's input is noisier than
  the gate's threshold (one prompt = 8.3%). Worse, the gate
  passes vacuously (W5): `probe_gate` (`probe.py:128`) reads
  `.get("delta", 0.0)` with 0.0 defaults, so `probe_gate({})`
  returns `(True, "gate passed")`; `run_probe` on an empty
  prompt list returns rate 0.0; and a model that generates empty
  strings for all 12 prompts scores 0 refusals — probed: 0/12,
  rate 0.0, gate passes. A lobotomized model that says nothing
  passes the abliteration guard — the exact failure the guard
  exists to catch, inverted. And the probe doesn't test the model
  the way Forge/Ollama will use it (W6): `_generate_reply`
  (`probe.py:111`) encodes the raw prompt and generates a
  continuation — no `apply_chat_template`, no generation prompt,
  no system prompt — while training renders prompts through the
  template (`train.py:420`). A model could pass the probe while
  refusing in chat mode, or vice versa.
- **Fix:** D2 — refusal detection v2: match markers against the
  reply's first sentence, not a 400-char substring window; treat
  "As an AI" + a compliant continuation as a pass; add "I
  refuse", "I won't", "not able to help with that". And count
  empty / garbage replies as failures, not passes — a reply with
  no content is not compliance, it is a broken model. Require a
  real before/after result for the gate (no empty-results pass).
  D3 — render each prompt with `apply_chat_template` + generation
  prompt in `_generate_reply`, the same way training renders
  prompts.
- **Done:** The 6 misjudged crafted replies are all judged
  correctly; an empty-results probe fails (or refuses to run)
  instead of passing; a silent model fails the gate; the probe
  renders through the chat template. Tests: the crafted-reply
  battery, empty-results gate, empty-reply gate, template-mode
  generation.

### T4 — One job at a time, enforced in the engine, not just the GUI

- **Covers:** A8-W7, A8-D5
- **Effort:** S
- **Problem:** `start_training` refuses to run while sleep runs,
  with a comment naming the 8 GB ceiling (`gui.py:973`). But
  `export_gguf_gui` and `run_probe_gui` (`gui.py:1104`,
  `gui.py:1131`) have no guards at all: no check for a running
  train/sleep/job, and each overwrites `self._job_worker`,
  orphaning a running job. The probe loads two bases (~7 GB for
  LFM3, merged T10) and training holds ~5.9 GB by its own
  estimate — together ~13 GB on an 8 GB machine. Export-merge
  (~3.5 GB) during training (~5.9 GB) is also over the ceiling.
  Extension of A4-W9 (merged T23) with new evidence: the
  train-vs-sleep guard exists and works, the train-vs-job hole
  is unguarded, and the RAM math says the hole is fatal rather
  than merely untidy.
- **Fix:** D5 — a lock (in-process flag or lock file) in
  `train_project` / `export_gguf` / `probe_project` so two
  model-loading jobs cannot run at once even across CLI
  invocations. The GUI guard is the UX; the engine guard is the
  safety. (In the merged list this folds into merged T23, the
  one-job task.)
- **Done:** A second model-loading job refuses with a message
  naming the running job, in the GUI and across CLI invocations;
  no job is ever orphaned from the window's handle. Tests:
  probe-during-training refused, export-during-training refused,
  cross-process lock.

### T5 — The CLI reports the RAM estimate as "RAM used" — say "estimated"

- **Covers:** A8-U1
- **Effort:** S
- **Problem:** `cmd_train` prints `about
  {summary['ram_estimate_gb']} GB RAM used` (`cli.py:152`) — but
  that number is the pre-run estimate (`train.py:986`), never
  measured. A user comparing runs, or deciding whether a bigger
  model fits, will read it as a measurement.
- **Fix:** Say "estimated": `about X GB RAM (estimated)`.
- **Done:** The CLI's closing line says "estimated", never
  "used", for the pre-run number. Tests: output text.

### T6 — Target-module override for unrecognized architectures

- **Covers:** A8-G1
- **Effort:** S
- **Problem:** `detect_target_modules` fails cleanly on unknown
  layers (naming the model's actual layers), but there is no
  setting, flag, or config to supply `target_modules` by hand.
  Any architecture outside the 14 suffixes is untrainable with
  no escape hatch. LFM3's own module names are unconfirmed in
  this audit (no weights in the sandbox) — if they fell outside
  the list, the proof loop would fail at this step with no
  workaround short of editing the code.
- **Fix:** A setting (project settings + a CLI flag) to supply
  `target_modules` by hand, used when set, falling back to
  auto-detection. The error message names the override when
  detection fails.
- **Done:** An unrecognized-architecture model trains with a
  hand-supplied target list; the detection-failure error names
  the override. Tests: override honored, detection fallback,
  error text.

### T7 — Merge RAM guard: the merge/convert steps have no estimate at all

- **Covers:** A8-G2
- **Effort:** S
- **Problem:** The training guard (merged T22) covers the loop;
  `merge_adapter` loads the base (~3.5 GB for LFM3 bf16) and
  merges with no estimate and no refusal, and the converter then
  loads the merged model again as a separate process. The step
  most likely to strain the machine has no guard — and it runs
  after the user has already waited hours for training.
  (Unprobed at real scale; the absence of any guard code is the
  finding.)
- **Fix:** Estimate the merge's memory (base weights + merged
  copy + a headroom) before loading, and refuse with a plain
  message when it does not fit — reusing the training
  estimator's shape. Warn when the converter's separate process
  would push the total over the ceiling.
- **Done:** A merge that would not fit is refused before loading
  anything, with the estimate named; a merge that fits proceeds.
  Tests: estimate math, refusal above the ceiling.

---

## P2 — missing capabilities and inconsistencies

### T8 — Validate settings once, at the top of train_project

- **Covers:** A8-W8, A8-D6
- **Effort:** S
- **Problem:** `run_training_loop` converts settings with bare
  `int()` / `float()` (`train.py:611-619`) and never
  range-checks them. Probed through the real loop on the tiny
  model: `rank="banana"` → raw `ValueError`; `grad_accum=0` →
  raw `ZeroDivisionError`; `batch_size=0` → raw
  `ZeroDivisionError`; `learning_rate=-0.5` → raw `ValueError`
  from AdamW; `epochs=0` → `StellaError`, but reading "already
  at step 0 of 0 — nothing left to train"; `checkpoint_steps=-1`
  → runs fine, silently disabling all mid-run checkpoints;
  `warmup_steps=-3` → runs fine, silently warping the LR
  schedule. The GUI's spin boxes constrain the normal path, so
  this bites on hand-edited `project.json` — exactly the file
  the docs tell users they can fix by hand. Engine instance of
  A2-W2 (merged T6); the loop's conversions are the crash points
  T6 must cover.
- **Fix:** D6 — range-check every numeric setting at the top of
  `train_project` (rank ≥ 1, lr > 0, epochs ≥ 1, grad_accum ≥ 1,
  batch ≥ 1, seq ≥ 8, checkpoint_steps ≥ 0, warmup ≥ 0, seed any
  int) and raise `StellaError` naming the setting. (In the
  merged list this folds into merged T6, the settings-validation
  task — this is the engine-side half of that task.)
- **Done:** Each probed bad value is refused before the loop
  starts with a readable message naming the setting;
  `checkpoint_steps=-1` and `warmup_steps=-3` no longer run
  silently wrong. Tests: every rule, both directions.

### T9 — Wrap HF load failures in StellaError

- **Covers:** A8-W9, A8-D7
- **Effort:** S
- **Problem:** `load_base_model` (`train.py:331`) calls
  `AutoTokenizer.from_pretrained` /
  `AutoModelForCausalLM.from_pretrained` with no error wrapping.
  Probed on an empty local dir: raw `ValueError` ("Couldn't
  instantiate the backend tokenizer…"). A bad repo id, a network
  failure, or corrupt weights will surface the same way — a
  transformers traceback on the CLI, where `main` catches only
  `StellaError`. Engine instance of A5-W2 (merged T5).
- **Fix:** D7 — catch `OSError` / `ValueError` around the
  `from_pretrained` calls and re-raise naming the repo/path and
  the likely cause ("not a model folder", "no network?", "repo
  not found"). (In the merged list this folds into merged T5,
  the catch-all task.)
- **Done:** A bad repo id, an empty dir, and a network failure
  each print one clean `stella:` line naming the cause, exit 1,
  no traceback. Tests: empty dir, bad repo id.

### T10 — Resume contract: snapshot settings at pause, warn on drift

- **Covers:** A8-W10, A8-W11, A8-D8
- **Effort:** S
- **Problem:** On the resume path, `train_project` loads the
  checkpoint's adapter (`train.py:899`) and never applies the
  freshly built `peft_config` — it is constructed
  (`train.py:885`) but only used in the non-resume branch.
  Probed: pause after step 1, change rank 2→4 in the stored
  settings, resume — the final adapter has **r=2**. No warning,
  no error, no note in the log. Any setting changed between
  pause and resume is silently dropped. And resume with a
  missing `optimizer.pt` silently restarts the optimizer (W11):
  `train_project` loads the saved optimizer state only `if
  opt_file.is_file()` (`train.py:917`) — there is no `else`
  branch, no warning, no event. Probed: pause after step 1,
  delete `optimizer.pt`, resume — the run completes and zero
  events mention the optimizer. The Adam moments reset mid-run,
  the loss curve jumps, and nothing says why. (The checkpoint
  dir is still listed as complete: `list_checkpoints` keys on
  `training_state.json`, not on the optimizer file.)
- **Fix:** D8 — write the run's settings into
  `training_state.json`; on resume, refuse or warn when the
  stored settings differ. Warn (event + log) when
  `optimizer.pt` is missing instead of silently starting fresh.
- **Done:** A rank change between pause and resume is refused or
  warned about, never silently dropped; a missing optimizer file
  produces a visible warning event. Tests: changed-rank resume,
  missing-optimizer resume.

### T11 — Compose caps with resume: remaining-steps budget

- **Covers:** A8-W12, A8-D9
- **Effort:** S
- **Problem:** The `_max_steps` handling (`train.py:942`)
  shrinks the epoch budget (`epochs_needed = ceil(cap /
  steps_per_epoch)`) without regard for the resume point.
  Probed: pause at step 4 (epoch 1 of 2), resume with
  `max_steps=1` — total_steps recomputes to 3, and the loop
  raises `StellaError: already at step 4 of 3 — nothing left to
  train`. The cap and resume don't compose, and the message
  states an impossible state. Adjacent to merged T44 (--steps
  cap).
- **Fix:** D9 — apply `_max_steps` as `start_step + cap` (a
  budget from the resume point), not an epoch shrink. A resume
  with a cap then trains exactly that many more steps instead of
  erroring with an impossible state. (In the merged list this
  folds into merged T44, the --steps task.)
- **Done:** Resume with `--steps N` trains exactly N more steps
  from the resume point; the "already at step X of Y" error
  never states an impossible state. Tests: resume + cap,
  fresh + cap unchanged.

### T12 — Clean up intermediates on failure

- **Covers:** A8-W13, A8-D10
- **Effort:** S
- **Problem:** `convert_to_gguf` deletes the F16 file only on
  the success path (`gguf.py:179-180`). Probed with a fake
  llama.cpp whose quantizer exits 1: the `StellaError` is raised
  correctly, and the F16 file is left behind. For a real 1.7B
  model that is ~3.4 GB per failed export (1.73B params × 2
  bytes), with no message naming the file and no cleanup on the
  next run. Adjacent to merged T20, which covers the merged HF
  dir on failure — the F16 half is not covered.
- **Fix:** D10 — `try/finally` around convert + quantize:
  remove the F16 file when the quantize step fails (and say so
  in the error). (In the merged list this folds into merged T20,
  the llama.cpp-first task.)
- **Done:** A failed quantize leaves no F16 intermediate behind
  (or names it and says it is safe to delete). Tests: failing
  quantizer, no leftover F16.

### T13 — Check the quantizer is executable at discovery

- **Covers:** A8-W14, A8-D11
- **Effort:** S
- **Problem:** `find_llama_cpp` checks `is_file()` only
  (`gguf.py:76-79`) — never executability. Probed: a chmod-644
  quantize is "found", and `_run`'s `subprocess.run` raises a
  raw `PermissionError` (`[Errno 13] Permission denied`), not a
  `StellaError`. A fresh `cmake --build` produces an executable,
  so this bites on a copied, restored, or half-built install —
  exactly when the user needs a clear error, not a traceback.
- **Fix:** D11 (discovery half) — `find_llama_cpp` should
  require the quantizer to be executable (`os.access(q,
  os.X_OK)`) and say which file is not. (D11's quant half —
  validate `quant` up front — is audit #5's W7, already merged
  T21; this task is only the executability half.)
- **Done:** A non-executable quantizer is refused at discovery
  with a plain error naming the file; an executable one is
  found as before. Tests: chmod-644 quantizer, executable
  quantizer.

### T14 — Quote paths in the Modelfile and the printed command

- **Covers:** A8-W15, A8-D12
- **Effort:** S
- **Problem:** `write_modelfile` (`gguf.py:193`) writes the GGUF
  path and the command with no quoting. Probed with dest `my
  models`: Modelfile line `FROM /home/…/my models/model-q4_k_m.gguf`,
  command `ollama create tiny-proof -f /home/…/my
  models/Modelfile`. The shell splits the command at the space —
  the exact command the CLI prints for the user to copy-paste
  fails. Whether Ollama's Modelfile parser accepts the unquoted
  spaced `FROM` line is unprobed (no Ollama in the sandbox); the
  shell failure is certain.
- **Fix:** D12 — `shlex.quote` on the paths in
  `write_modelfile`'s command string, and quote (or document)
  the `FROM` path. The command Stella prints should work when
  pasted.
- **Done:** The printed `ollama create` command works when
  pasted with a spaced path; the Modelfile's `FROM` line is
  quoted or documented. Tests: spaced-path export, command
  string, Modelfile line.

### T15 — Bound completions to max_seq_len

- **Covers:** A8-W16, A8-D13
- **Effort:** S
- **Problem:** `tokenize_example` truncates only the prompt
  (`train.py:436-438`): `keep = max(0, max_seq_len -
  len(completion_ids))`. When the completion alone exceeds the
  cap, `keep` is 0, the prompt is dropped entirely, and the
  sequence is the full completion. Probed: a 200-char completion
  with `max_seq_len=64` produces `input_ids` of length **202**.
  The RAM estimate assumes `max_seq_len` bounds every sequence,
  so a long completion is a batch that can exceed the estimate —
  the guard's arithmetic does not bound what the loop actually
  allocates.
- **Fix:** D13 — truncate an over-long completion (keep the tail?
  drop the example with a warning and a count?) — either way, no
  sequence may exceed `max_seq_len`, because the RAM estimate
  assumes it cannot.
- **Done:** No tokenized sequence exceeds `max_seq_len`, whatever
  the completion length; over-long completions are truncated or
  dropped with a count. Tests: 200-char completion at
  max_seq_len=64, normal completions unchanged.

### T16 — End the completion with the template's turn terminator

- **Covers:** A8-W17, A8-D14
- **Effort:** S
- **Problem:** The prompt is rendered through the chat template
  (`train.py:420`), but the completion is the raw assistant
  content plus EOS (`train.py:430-432`) — the template's own
  assistant-turn terminator is never appended. Probed with a
  Qwen-shaped template (`<|im_start|>…<|im_end|>`): the
  completion tokens decode to raw content + `<EOS>`, no
  `<|im_end|>`. For templates where the turn ends with
  `<|im_end|>` rather than EOS, the tuned model never learns to
  end its turn — run-on generation in Ollama. (Proven on the
  code path with a template-shaped fake; end-to-end confirmation
  needs a real chat-template tokenizer.)
- **Fix:** D14 — when the tokenizer's chat template defines an
  assistant-turn end token, append it (in addition to or instead
  of EOS) so the tuned model learns to end its turn the way the
  template expects.
- **Done:** With a Qwen-shaped template, completion tokens end
  with `<|im_end|>`; with no template, behavior is unchanged.
  Tests: template-shaped tokenizer, plain tokenizer.

### T17 — Proof-run control in the window: the GUI can't do a short --steps run

- **Covers:** A8-U2
- **Effort:** S
- **Problem:** The CLI has `--steps` for a quick proof run; the
  GUI's Start training always runs the full epoch budget
  (`gui.py:961` passes no `max_steps`, and no control exists).
  A user who wants a 2-minute smoke test before an hours-long run
  has to use the terminal — the thing the window exists to
  avoid.
- **Fix:** A step-cap control in the Train panel (a spin box or
  a "proof run" button that runs a short cap), passed through as
  `max_steps`. Pairs with merged T44 (the cap must be real).
- **Done:** A window user can start a capped proof run and it
  stops at the cap. Tests: GUI test, cap honored.

### T18 — The val loss in the run summary and the window

- **Covers:** A8-U3, A8-G8
- **Effort:** S
- **Problem:** The loss label shows the last training loss; val
  loss appears only as a log line. When a run finishes, the
  window says "Trained N steps" with no val loss — the one
  number that says whether the tune generalized or just
  memorized. The data is there (the `val` event); the panel
  drops it. And the run summary carries no val loss either
  (G8): `run_training_loop` returns steps, total, final loss,
  stopped, checkpoint — the final val loss is logged and
  emitted but not returned, so the CLI's closing line and any
  caller can't report it.
- **Fix:** Return the final val loss from `run_training_loop`
  (G8), show it in the Train panel's summary line and the CLI's
  closing line (U3). One fix: the summary must carry it for the
  window to show it.
- **Done:** A finished run's summary line (GUI + CLI) shows the
  final val loss next to the training loss. Tests: summary
  carries val loss, panel shows it.

### T19 — Surface the probe in the window

- **Covers:** A8-U4, A8-D17
- **Effort:** M
- **Problem:** `run_probe_gui` logs one line ("X/12 refusals
  before, Y/12 after") plus the verdict. `probe_results.json` —
  all 24 replies, the evidence behind the verdict — is never
  surfaced: no dialog, no panel, no way to read what the model
  actually said without opening the JSON by hand. For a gate
  that can fail a tune, the evidence should be one click away.
- **Fix:** D17 — a results dialog: per-prompt reply + refused
  flag, before and after side by side, with the gate verdict.
- **Done:** A probe run's evidence is one click away in the
  window: every reply, its refused flag, before and after, and
  the verdict. Tests: dialog shows the saved results.

### T20 — Probe provenance in the results file

- **Covers:** A8-G3, A8-D16
- **Effort:** S
- **Problem:** Probed keys of `probe_results.json`: `[after,
  before, delta, profile, project]` — no timestamp, no
  `base_ref`, no adapter path, no `max_new_tokens`, no prompts
  version. Two probe runs cannot be compared or reproduced: the
  file cannot say when it ran, on what, or with which prompts.
  The verdict is a bare number with no audit trail.
- **Fix:** D16 — timestamp, `base_ref`, adapter path,
  `max_new_tokens`, and a prompts-version marker in
  `probe_results.json`. A verdict without provenance is a rumor.
- **Done:** A saved probe result names when it ran, on what
  base and adapter, with what generation settings and prompt
  set. Tests: keys present, two runs distinguishable.

### T21 — Hard-benign prompts in the probe set

- **Covers:** A8-G4
- **Effort:** S
- **Problem:** All 12 prompts are trivially benign. A model
  could regain refusals on edgy-but-legitimate requests —
  dual-use help, security-adjacent questions, contentious topics
  — while scoring 0/12. The gate cannot see the failure mode it
  exists to catch at the margin where it matters. (The verdict
  thread's idea of per-role probe sets, merged T128, points the
  same way.)
- **Fix:** Add hard-benign prompts to the set — requests that
  are legitimate but sit near the refusal boundary — so the
  gate measures the margin, not just the easy middle. Keep the
  12 trivial prompts; the hard ones are additional.
- **Done:** The probe set includes hard-benign prompts; a model
  that refuses only at the margin scores above 0. Tests: set
  contents, a margin-refusing model caught.

### T22 — Timeout on the converter/quantizer subprocesses

- **Covers:** A8-G7
- **Effort:** S
- **Problem:** `_run` calls `subprocess.run` with no timeout
  (`gguf.py:132`). A hung llama.cpp hangs the export — and the
  GUI job, which has no cancel — forever. The failure mode is
  silence, not an error.
- **Fix:** A timeout on the converter and quantizer subprocess
  calls (generous — a real 1.7B convert takes minutes), raising
  a StellaError naming the step that hung when it fires.
- **Done:** A hung converter/quantizer fails with a plain error
  naming the step, instead of hanging forever. Tests: hung
  subprocess times out.

### T23 — LFM3 → GGUF conversion pre-flight

- **Covers:** A8-G11
- **Effort:** S
- **Problem:** `convert_hf_to_gguf.py` must support the `lfm3`
  architecture, and nothing in Stella checks that before the
  merge — the first sign of an unsupported arch would be a
  converter failure after the 72-second merge (and after hours
  of training). Untestable in this sandbox (no llama.cpp, no
  LFM3 weights); the gap is that no pre-flight check exists at
  all.
- **Fix:** A pre-flight check before the merge: confirm the
  base's architecture is one the installed converter supports
  (from the converter's own supported-arch list, or a Stella
  list verified against it), and refuse with a plain message
  when it is not.
- **Done:** An unsupported architecture is refused before the
  merge, naming the arch and the converter; a supported one
  proceeds. Tests: supported arch passes, unsupported refused.

---

## P3 — polish, display, and scale

### T24 — Stable val sets via content-hash split

- **Covers:** A8-W18, A8-D15
- **Effort:** S
- **Problem:** `split_dataset` re-shuffles the whole list, so
  adding rows reassigns val membership. Probed (seed 42, 10%):
  n=20 val `[ex19, ex5]`; n=21 same; n=22 keeps 1/2; n=25 keeps
  0/2; n=30 keeps 0/2. Val loss is not comparable across runs
  once rows are added, and rows can move from val to train — the
  val signal leaks into training over time. (The sleep replay
  check keeps its own held-out sets, so sleep is not affected;
  plain training is.) The auditor flags the fix as small enough
  for the P2 pass, but the finding is P3, so the task stays P3.
- **Fix:** D15 — assign val membership by hashing each row's
  content (val = hash falls in the lowest `val_fraction` of the
  range) instead of shuffling indices. Adding rows never moves
  old rows; val loss stays comparable across runs.
- **Done:** Adding rows to a dataset never changes the val
  membership of existing rows; val loss is comparable across
  runs. Tests: growth from n=20 to n=30, val set stable.

### T25 — Train every assistant turn, not just the last

- **Covers:** A8-W19
- **Effort:** M
- **Problem:** In a multi-turn `messages` row, only the last
  assistant message is unmasked; earlier assistant turns are
  masked prompt text. Probed: a 2-turn conversation tokenizes
  to 50 tokens with 5 unmasked — the final turn only. Users
  bringing multi-turn Forge traces get a fraction of the
  training signal they expect, silently. (The format validation
  allows multi-turn rows, so nothing warns that the earlier
  turns are discarded as training signal.)
- **Fix:** Unmask every assistant turn in a multi-turn row (each
  turn's completion trained, each user turn masked), or warn at
  validation time that only the final turn trains. Training
  every turn is the fix; the warning is the fallback if the
  tokenization rework is too big for one task.
- **Done:** A 2-turn conversation trains both assistant turns
  (or the validator warns that only the final turn trains).
  Tests: multi-turn masking, single-turn unchanged.

### T26 — Don't double-save / double-emit the final checkpoint

- **Covers:** A8-W20
- **Effort:** S
- **Problem:** When the last step is a checkpoint step, the loop
  saves it in-loop and then saves it again as the "final
  checkpoint" (`train.py:739-747`) — same directory, same
  content, twice. Probed: `checkpoint_steps=1`, 3 steps → 4
  `checkpoint` events for steps `[1, 2, 3, 3]`, 3 dirs on disk.
  Cosmetic — the GUI logs "checkpoint saved: step 3" twice and
  the disk write happens twice — but it is a real duplicate in
  the event stream any consumer (GUI, sleep, future tooling)
  must tolerate.
- **Fix:** Skip the final save when the last step was already
  saved in-loop (or skip the in-loop save when it is the last
  step) — one save, one event per checkpoint step.
- **Done:** A 3-step run with `checkpoint_steps=1` emits exactly
  3 `checkpoint` events, one per step. Tests: event stream,
  dirs on disk.

### T27 — Size/time warning on the GGUF export button

- **Covers:** A8-U5
- **Effort:** S
- **Problem:** A 1.7B export merges ~3.4 GB, converts, and
  quantizes — minutes of disk churn. The button offers no
  estimate up front and the job has no progress signal
  (`JobWorker` has log + finished only). The user commits to a
  multi-GB, multi-minute job blind. Overlaps merged T64 (dry-run
  estimate) and merged T74 (job progress); the export-specific
  half is the up-front warning on the button itself.
- **Fix:** Show the estimate on (or beside) the export button
  before the user commits — merged size, output size, rough
  time — reusing the dry-run estimator when merged T64 lands.
- **Done:** The export button shows what the export will cost
  (size + rough time) before it starts. Tests: estimate shown,
  matches the dry-run numbers.

### T28 — "Loading base model" feedback: the window sits silent for minutes on a cold run

- **Covers:** A8-U6
- **Effort:** S
- **Problem:** `train_project` loads the model before emitting
  its first event, so between "Starting training..." and the
  first step, the window shows nothing happening — minutes on a
  first run while 3.5 GB downloads or loads from disk. The user
  cannot tell loading from a hang. (Same shape for the probe's
  double load and the export merge.)
- **Fix:** Emit a `loading` event (or set the status text)
  before the base load, with the model name, so the window shows
  "Loading <base>…" during the load. Same for the probe's load
  and the export merge.
- **Done:** A cold run shows a loading state with the model name
  from the moment Start is pressed until the first step. Tests:
  loading event emitted, status text shown.

### T29 — An Advanced settings section

- **Covers:** A8-G5, A8-G6, A8-D18
- **Effort:** M
- **Problem:** Five of eleven training settings have no GUI or
  CLI surface (G5): `grad_accum`, `checkpoint_steps`,
  `val_fraction`, `warmup_steps`, and `seed` are GUI-invisible
  (the form exposes method/rank/lr/epochs/batch/seq only,
  `gui.py:415-437`) and the CLI has no settings flags (A5-G3).
  Changing them means hand-editing `project.json` — the file
  whose hand-editing the engine then punishes with raw
  tracebacks (W8). And there are no LoRA hyperparameters beyond
  rank (G6): `lora_alpha` is hardcoded to rank×2,
  `lora_dropout` to 0.05, `weight_decay` to 0.0
  (`train.py:885-891`, `train.py:641`). Rank is the only knob. A
  user who wants a gentler adapter (higher dropout, lower alpha)
  or a stronger one has no setting to reach for.
- **Fix:** D18 — expose `grad_accum`, `checkpoint_steps`,
  `val_fraction`, `warmup_steps`, `seed` — and LoRA `alpha` /
  `dropout` — in a collapsed Advanced block in the project form,
  with the same ranges the engine validates (T8). No more
  hand-editing JSON to reach half the settings.
- **Done:** Every training setting is reachable from the window;
  the Advanced block's ranges match the engine's validation.
  Tests: each setting settable + saved, ranges enforced.

### T30 — Dataset-size awareness: don't load the whole file into RAM

- **Covers:** A8-G9
- **Effort:** M
- **Problem:** `load_dataset` reads the entire file
  (`read_text().splitlines()`, `train.py:207`) — a 100 MB JSONL
  loads whole, then tokenizes whole (`train.py:645`), while the
  model is resident. No streaming validation, no row-count cap,
  no warning. On 8 GB, a big dataset competes with training
  memory.
- **Fix:** Stream validation (read line by line, validate
  without holding the file), a row-count/size warning before
  tokenization, and a cap or a clear refusal when the dataset
  would not fit alongside the model.
- **Done:** A 100 MB dataset validates without loading whole;
  the user is warned (or refused) before a dataset that would
  not fit starts tokenizing. Tests: large-file validation
  memory, warning threshold.

### T31 — Accept the "tool" role in messages rows

- **Covers:** A8-G10
- **Effort:** S
- **Problem:** `DATASET_ROLES` is `(system, user, assistant)` —
  a `messages` row with role `tool` fails validation. Multi-turn
  tool-use traces (user → assistant tool call → tool result →
  assistant answer) cannot be expressed; the sample dataset
  works around it by putting tool calls in the assistant content
  only. The first proof loop's stated data is Forge tool-call
  traces; the traces with results attached don't fit the format.
- **Fix:** Accept `tool` as a role in `messages` rows, rendered
  as prompt (masked) content in the conversation — the model
  learns from the assistant turns around the tool results, not
  from the results themselves. Pairs with T25 (multi-turn
  training): a tool trace is a multi-turn conversation.
- **Done:** A messages row with a `tool` turn validates and
  trains (tool content masked, assistant turns trained). Tests:
  tool-role row validates, masking correct.

---

## Coverage map

Every finding ID from audit #8, and the task(s) covering it.
Nothing dropped.

| Finding | Task(s) | Notes |
|---|---|---|
| A8-W1 — no torch seeding: the same run twice gives a different adapter | T1 | |
| A8-W2 — resume diverges: torch RNG state isn't saved | T1 | |
| A8-W3 — datasets under 6 examples get no validation at all | T2 | |
| A8-W4 — `is_refusal` is brittle both ways: 6 of 10 crafted replies misjudged | T3 | |
| A8-W5 — the gate passes vacuously: empty results and a silent model pass | T3 | |
| A8-W6 — the probe doesn't use the chat template | T3 | |
| A8-W7 — no mutual exclusion between Train and the GGUF/probe jobs | T4 | A4-W9, re-probed with the train-vs-job hole |
| A8-W8 — bad settings crash the loop with raw tracebacks, or run silently wrong | T8 | A2-W2 at the loop's conversions |
| A8-W9 — HF load failures surface as raw tracebacks, not StellaError | T9 | A5-W2 at the model loader |
| A8-W10 — resume silently ignores changed settings | T10 | |
| A8-W11 — resume with a missing optimizer.pt silently restarts the optimizer | T10 | |
| A8-W12 — resume + --steps gives the nonsense error "already at step 4 of 3" | T11 | Adjacent to R11/A5-W3 |
| A8-W13 — a failed quantize leaves the multi-GB F16 intermediate on disk | T12 | F16 half of A5-W6 |
| A8-W14 — a non-executable llama-quantize passes discovery, then raw PermissionError | T13 | |
| A8-W15 — the printed `ollama create` command breaks on spaced paths | T14 | |
| A8-W16 — completions are never truncated: a long completion blows past max_seq_len | T15 | |
| A8-W17 — with a chat template, the completion never learns the turn terminator | T16 | |
| A8-W18 — the val set churns when the dataset grows | T24 | |
| A8-W19 — multi-turn conversations only train the final turn | T25 | |
| A8-W20 — the final checkpoint double-saves and double-emits | T26 | |
| A8-U1 — the CLI reports the RAM estimate as "RAM used" | T5 | |
| A8-U2 — no proof-run control in the window | T17 | |
| A8-U3 — the Train panel never shows the val loss in the summary line | T18 | |
| A8-U4 — the probe result has no home in the window | T19 | |
| A8-U5 — the GGUF export button gives no size/time warning | T27 | Overlaps merged T64/T74 |
| A8-U6 — no "loading base model" feedback | T28 | |
| A8-G1 — no target-module override | T6 | |
| A8-G2 — no merge RAM guard | T7 | |
| A8-G3 — probe_results.json carries no provenance | T20 | |
| A8-G4 — the prompt set has no hard-benign prompts | T21 | |
| A8-G5 — five of eleven training settings have no GUI or CLI surface | T29 | |
| A8-G6 — no LoRA hyperparameters beyond rank | T29 | |
| A8-G7 — no timeout on the converter/quantizer subprocesses | T22 | |
| A8-G8 — the run summary carries no val loss | T18 | Rides with U3 |
| A8-G9 — no dataset-size awareness: the whole file loads into RAM | T30 | |
| A8-G10 — the "tool" role is rejected | T31 | |
| A8-G11 — the LFM3 → GGUF conversion is unproven | T23 | |
| A8-D1 — seed everything: torch seed at run start + RNG state in checkpoints | T1 | |
| A8-D2 — refusal detection v2: first-sentence matching + an apology allowlist | T3 | |
| A8-D3 — probe through the chat template | T3 | |
| A8-D4 — minimum-val guarantee, or a loud warning | T2 | |
| A8-D5 — one job at a time, enforced in the engine, not just the GUI | T4 | |
| A8-D6 — validate settings once, at the top of train_project | T8 | |
| A8-D7 — wrap HF load failures in StellaError | T9 | |
| A8-D8 — resume contract: snapshot settings at pause, warn on drift | T10 | |
| A8-D9 — compose caps with resume: remaining-steps budget | T11 | |
| A8-D10 — clean up intermediates on failure | T12 | |
| A8-D11 — check executability at discovery; validate quant up front | T13 | Quant half is A5-W7 (merged T21) |
| A8-D12 — quote paths in the Modelfile and the printed command | T14 | |
| A8-D13 — bound completions to max_seq_len | T15 | |
| A8-D14 — end the completion with the template's turn terminator | T16 | |
| A8-D15 — stable val sets via content-hash split | T24 | |
| A8-D16 — probe provenance in the results file | T20 | |
| A8-D17 — surface the probe in the window | T19 | |
| A8-D18 — an Advanced settings section | T29 | |

**Coverage check:** 20 weaknesses + 6 UI flaws + 11 gaps + 18 design
suggestions = 55 findings. All 55 appear in the map above, each with
at least one task. 31 tasks total: 0 P0, 7 P1 (T1–T7), 16 P2
(T8–T23), 8 P3 (T24–T31).

**Dependency order (within the priority order above):** T1 before
T10 (the seeding fix and the resume contract both touch the
checkpoint format — land the RNG state first, then the settings
snapshot). T3 before T19, T20, and T21 (the probe must be
trustworthy before its dialog, its provenance, and its hard-benign
prompts are built on it). T8 before T29 (the Advanced settings
block enforces the ranges the engine validates). T15 before
trusting the RAM guard (a completion longer than max_seq_len
breaks the estimate the guard relies on). T18 before the loss
chart (the chart shows the val loss the summary now carries).
T13 with T12 and the --quant task (the three GGUF fail-fast fixes
touch the same path — land them together). Folded into the merged
list's shared tasks: T4 (engine one-job lock → the one-job task),
T8 (engine settings validation → the settings-validation task),
T9 (HF error wrapping → the catch-all task), T11 (cap/resume
composition → the --steps task), and T12 (F16 cleanup → the
llama.cpp-first task).
