# STELLA Audit #8 — Training engine

**Audited:** 2026-11-13, against the live v0.3 tree (`~/workspace/stella/`).
Scope: the v0.2 training engine — `stella/train.py` (987 lines) in full,
`stella/gguf.py` (314 lines) in full, `stella/probe.py` (207 lines) in
full, plus the tests that cover them (`tests/test_train.py` 23 tests,
`tests/test_gguf.py` 8, `tests/test_probe.py` 8) and the CLI/GUI surfaces
that call them (`cli.py` train / export-gguf / probe commands, the GUI
Train panel). `stella/sleep.py` (v0.3, just built and verified) is OUT
of scope, as is everything audits #1–#7 already covered.

**Method:** read all three engine files end to end, then probed live
behavior with scratch homes under `~/workspace/stella-a8-scratch/` (not
/tmp — it fills up): tiny 2-layer/64-hidden GPT-2 runs through the
train venv (`~/workspace/stella-v02-build/.venv-train/`, torch
2.15.0+cpu / transformers 5.22.2 / peft 0.21.2), a fake llama.cpp
checkout (real subprocess path, no `_runner`), and a fake Ollama-shaped
generation hook for the probe. Probe scripts:
`~/workspace/stella-a8-scratch/probe_p1.py` (pure Python),
`probe_p2a.py` (resume/determinism/merge),
`probe_p2b.py`, `probe_p2c.py`, `probe_p2d.py`.
Every weakness below carries file:line evidence or a probe result —
no unprobed claims.

**Cross-references** use the merged task list as it stands today
(142 tasks, post-A5-merge, 2026-11-13). The brief for this audit
carried pre-merge numbers; the numbers below were re-checked against
the live list file.

**The one-line verdict:** the engine's core loop is sound — the
completion-only masking is correct, the merge math is exact to
0.0, and pause/resume continues from the right place — but nothing
about a run is reproducible (torch is never seeded), the probe's
refusal detection is brittle in both directions and passes a silent
model, and the GGUF path leaves multi-gigabyte litter on failure
and breaks on spaced paths. No P0s: nothing here loses data or
crashes on a normal path.

---

## 1. Scope and method

### What the engine is

- `train.py`: dataset validation (JSONL, two formats), deterministic
  train/val split, RAM estimation + guard, HF base loading (never
  GGUF), LoRA target auto-detection, completion-only tokenization,
  the training loop (grad accumulation, linear warmup/decay LR,
  checkpoints + resume, progress events), and the project-level
  `train_project` entry point.
- `gguf.py`: adapter merge, llama.cpp discovery, HF→F16→quantized
  GGUF conversion, Modelfile writing, and the `export_gguf`
  round-trip.
- `probe.py`: the 12-prompt refusal probe, substring refusal
  detection, the before/after gate, and result persistence.

### What was probed live (P1–P2d)

- Split behavior on datasets of 2–30 rows, including growth churn.
- `is_refusal` against 10 crafted replies (false positives and
  false negatives); `probe_gate` on empty results; `run_probe`
  with empty replies.
- Tokenization: masking correctness, over-long completions,
  multi-turn conversations, a Qwen-shaped chat template.
- Modelfile + `ollama create` command with a spaced path.
- `convert_to_gguf` with `quant="BOGUS"`; with a failing quantizer
  (real subprocess); with a non-executable quantizer.
- Resume exactness: paused vs uninterrupted runs, adapter weights
  compared tensor-by-tensor; determinism with and without torch
  seeding; merge correctness against hand-computed LoRA math.
- Resume edge cases: missing `optimizer.pt`, changed rank between
  pause and resume, resume + `--steps`.
- RAM: peak RSS at each import stage; the LFM3 estimate broken down.
- Bad settings through the real loop: non-numeric rank, zero
  grad_accum/batch, negative lr, zero epochs, negative
  checkpoint_steps/warmup.
- `load_base_model` on an empty local dir; `detect_target_modules`
  on an unrecognized architecture; checkpoint disk usage;
  `probe_results.json` contents.

### What could NOT be tested, and whether it matters

- **Real LFM3 weights.** No 1.7B weights in the sandbox and no
  download was attempted. The code paths are proven on the tiny
  model; scale-dependent behavior is not: real RAM use vs the
  5.94 GB estimate, real step time, and whether LFM3's module
  names match `TARGET_SUFFIXES` (G1). The estimate's conservatism
  (×34 activations factor) is a deliberate cushion, not a
  measurement.
- **Real llama.cpp.** Fake binaries prove the command
  construction, failure handling, and cleanup paths, but not real
  converter output, real quantizer behavior on bad input, or —
  most importantly — whether `convert_hf_to_gguf.py` supports
  the `lfm3` architecture at all (G11).
- **Real Ollama.** The unquoted `ollama create` command is
  certainly broken in a shell (W15); whether Ollama's Modelfile
  parser accepts an unquoted spaced `FROM` path is unprobed.
- **Real refusal behavior.** The probe's scoring is proven with
  crafted replies, but what LFM3 actually generates for the 12
  prompts — compliant, refusing, or garbage — is unknown until
  the first real probe run on his PC.

---

## 2. Features and functions

### train.py

- **Dataset validation** (`load_dataset`, `validate_dataset_row`):
  two formats (prompt/completion, messages), one per file, mixed
  files rejected; roles restricted to system/user/assistant; last
  message must be assistant; empty content rejected; every error
  names the line number.
- **Split** (`split_dataset`): seeded shuffle, deterministic for a
  fixed file and seed; val size `round(n × val_fraction)`, clamped
  to leave at least 1 train example.
- **RAM guard** (`estimate_training_bytes`, `check_ram_fit`):
  weights + fp32 gradients + AdamW m/v + fp32 master copy +
  activations (batch × seq × hidden × layers × 34) + 1 GB
  headroom, refused above the 8 GB ceiling. LFM3 LoRA rank 8
  estimates 5.94 GB; a full 1.7B fine-tune estimates ~28 GB of
  optimizer state alone and is refused.
- **Base loading** (`load_base_model`): HF weights only — GGUF
  files and bare Ollama tags refused up front; bf16 by default;
  `trust_remote_code=True` for LFM3's remote modeling code; KV
  cache disabled for training; pad token falls back to EOS.
- **Target detection** (`detect_target_modules`): scans real
  Linear/Conv1D modules against 14 known suffixes; raises a clear
  error naming the model's actual layers when none match.
- **Tokenization** (`tokenize_example`): prompt rendered through
  the tokenizer's chat template when one exists (fallback:
  `Role: content` lines); prompt masked with -100 so loss is
  completion-only; EOS appended to the completion; over-long
  pairs truncate the prompt from the left, keeping the completion
  whole.
- **The loop** (`run_training_loop`): batch 1 + grad accumulation,
  bf16 autocast on CPU, grad clip 1.0, linear warmup then linear
  decay to 0, per-epoch val loss via `evaluate_loss` (shared with
  the sleep replay check), checkpoints every N steps plus a final
  checkpoint, progress events (`started` / `step` / `checkpoint` /
  `val` / `done` / `paused`), pause via `TrainController`.
- **Resume** (`train_project`, `resume=True`): loads the latest
  checkpoint's adapter + optimizer state + step/epoch/examples-seen,
  re-shuffles the epoch deterministically and skips the examples
  already seen.
- **Entry point** (`train_project`): merges stored settings over
  `DEFAULT_TRAIN`, resolves the dataset, splits, loads, guards
  RAM, derives epochs from a `--steps` cap, sets project status
  (`training` → `trained` / `paused`), returns a summary
  (steps, final loss, trainable params, target modules, RAM
  estimate).

### gguf.py

- **Discovery** (`find_llama_cpp`): `LLAMA_CPP_DIR`, `~/llama.cpp`,
  `./llama.cpp`, beside/inside the install; quantizer also from
  PATH. Missing pieces raise a `StellaError` with install
  instructions.
- **Merge** (`merge_adapter`): base + `PeftModel`, `merge_and_unload`,
  save merged HF weights + tokenizer.
- **Convert** (`convert_to_gguf`): F16 GGUF via
  `convert_hf_to_gguf.py`, then quantize (default Q4_K_M); checks
  each step actually wrote its file; deletes the F16 intermediate
  on success.
- **Modelfile** (`write_modelfile`): `FROM <absolute gguf path>`,
  optional template/system, `PARAMETER temperature 0.7`; returns
  the `ollama create <name> -f <modelfile>` command.
- **Round-trip** (`export_gguf`): adapter (or `--from-checkpoint`)
  → merge → convert → Modelfile → `gguf-export.json` record;
  sets project status `exported`.

### probe.py

- **Prompt set**: 12 plainly benign prompts (code help, shell,
  plain questions, a haiku, arithmetic).
- **Detection** (`is_refusal`): 16 refusal markers matched as
  substrings against the first 400 chars, lowercased.
- **Run** (`run_probe`): greedy generation (`do_sample=False`,
  64 new tokens), per-prompt reply + refused flag, counts + rate.
- **Gate** (`probe_gate`): passes when the refusal rate did not
  rise past `max_increase` (default 0.0); returns a verdict string.
- **Project probe** (`probe_project`): probes the base, probes
  the adapter, saves `probe_results.json` (before/after/delta).

### CLI / GUI surfaces

- CLI: `train` (with `--steps`, `--resume`, `--dataset`, `--base`,
  Ctrl+C pause handler, per-step loss printing),
  `export-gguf` (`--quant`, `--from-checkpoint`), `probe` (prints
  before/after + gate verdict, exit 1 on gate failure).
- GUI Train panel: dataset pick/sample, Start/Pause/Resume,
  progress bar + loss label, checkpoint list, Export GGUF and
  Run refusal probe buttons, training log. Training runs in a
  `TrainWorker` thread; GGUF/probe run in a generic `JobWorker`.

---

## 3. Strengths

1. **The completion-only masking is exactly right.** Probed with
   a fake tokenizer: a 33-token example masks 29 prompt tokens
   and trains on 4 completion tokens including EOS. The model
   learns to write the answer, not predict the question.
2. **The merge math is exact.** A trained tiny adapter merged
   through `merge_adapter` matches hand-computed
   `W + (alpha/r)·B·A` with max difference **0.0**; the adapter's
   effect on the base (max 3.7e-04) is genuinely in the merged
   file. The round-trip is not a copy of the base wearing an
   adapter's name.
3. **Pause/resume continues from the right place.** A run paused
   after step 2 and resumed reproduces the pre-pause losses
   exactly (5.6149, 5.5667) and finishes at the right step count
   — the deterministic re-shuffle + skip logic works. (It
   diverges after the pause for a different reason: W2.)
4. **The loop is deterministic when torch is seeded.** Two
   identical runs with a seeded loader give byte-identical
   adapters (max diff 0.0) and identical losses — the loop,
   the shuffling, and the LR schedule are all reproducible.
   The nondeterminism is entirely the missing seed (W1).
5. **Dataset validation errors are genuinely helpful.** Every
   failure names the line and the rule ("dataset line 2: message
   0 has role 'robot'"). The sample dataset (20 rows, 14 tool
   calls) validates clean.
6. **The RAM estimate's headroom covers the real fixed cost.**
   Measured peak RSS: torch import 212 MB, +transformers 278 MB,
   +peft 283 MB, after two tiny training runs 316 MB. The 1 GB
   headroom is roughly 3× the measured Python-stack cost — the
   estimate is conservative where it claims to be (the ×34
   activations factor), not optimistic.
7. **Unknown architectures fail with a clear error, not a
   crash.** `detect_target_modules` on a model with `foo_proj` /
   `bar_mixer` layers raises `StellaError` naming exactly those
   layers. The user learns what the model has; the gap is only
   that there's no override (G1).
8. **The dependency gate is cheap and honest.** `find_spec`
   instead of importing torch on every Train click; the error
   names `bash install-training.sh`. The probe runs its cheap
   checks (base_ref, adapter) before the gate, so a missing
   adapter is reported even on a base install.
9. **Checkpoint dirs are self-describing and partial saves are
   invisible.** `list_checkpoints` skips dirs without
   `training_state.json`, so a crash mid-save leaves a dir the
   resume path never sees. The v0.3 sleep fix (all-three-files
   finder) is the same idea applied to sleep's own finder.
10. **The probe's generation is deterministic.** Greedy decoding,
    no sampling — the same model gives the same replies, so a
    rate change is a model change, not sampling noise.
11. **GGUF convert checks its outputs.** Each step verifies the
    file it was supposed to write actually exists before
    continuing — a converter that exits 0 without writing is
    caught, not passed downstream.

---

## 4. Weaknesses

### W1 — No torch seeding: the same project, settings, and dataset produce a different adapter every run (P1)

`train_project` never calls `torch.manual_seed` — a grep over
`train.py`, `sleep.py`, and `probe.py` finds zero seeding calls.
The dataset split and the epoch shuffles are seeded
(`random.Random(seed)`), but torch's RNG (which drives LoRA
dropout, 0.05) starts wherever the process left it.

Probed: the same fixed base weights, loaded fresh from disk with
no seeding, trained twice with identical settings — final losses
5.6010 vs 5.5737, max adapter weight difference **2.424e-01**.
That is not noise; that is a different adapter. With a seeded
loader the same loop is bit-identical (diff 0.0, §3.4), proving
the missing seed is the whole cause.

Consequence: a good run cannot be reproduced, a bad run cannot
be bisected, and A/B comparisons (rank 4 vs 8, lr 1e-4 vs 2e-4)
are confounded by dropout draws. The `seed` setting promises
reproducibility it does not deliver.

### W2 — Resume diverges from an uninterrupted run: torch RNG state isn't saved (P1)

`_save_checkpoint` (`train.py:553`) saves the adapter, the
optimizer state, the step, the epoch, and examples-seen — but
not the torch RNG state. On resume, dropout draws continue from
a fresh RNG stream instead of the one the paused run was using.

Probed: pause after step 2, resume, compare against the
uninterrupted run. Pre-pause losses match exactly (5.6149,
5.5667 — the skip logic is right); from step 3 the losses
diverge (5.5648 vs 5.6111) and the final adapters differ by
5.2e-04 max. The resumed run is a slightly different run, not
the same run continued. Small in absolute terms — the loss
trajectory stays in the same band — but it means "pause and
resume" is not the no-op it presents as, and it compounds W1:
even a seeded run diverges across a pause.

### W3 — Datasets under 6 examples get NO validation at all, contradicting the loader's own promise (P1)

`split_dataset` (`train.py:227`) computes
`n_val = round(n × val_fraction)`. With the default 0.1: n=2, 3,
4, 5 all give **val=0** (n=5: `round(0.5)` is 0 under banker's
rounding). The first val row appears at n=6.

Probed across n=2..20. Meanwhile `load_dataset` refuses a
1-example dataset with "at least 2 are needed (1 to train on,
1 to validate)" — but a 2-example dataset trains on 2 and
validates on 0. No `val` events fire, no val loss is logged,
and nothing tells the user validation didn't happen. The sample
dataset (20 rows) is fine; a small real dataset silently loses
its only quality signal.

### W4 — `is_refusal` is brittle both ways: 6 of 10 crafted replies misjudged (P1)

Substring matching against 16 markers in the first 400 chars
(`probe.py:65`) cannot tell an apology from a refusal, or catch
refusals phrased without the markers. Probed battery:

| Reply | Judged | Truth |
|---|---|---|
| "As an AI language model, here is the function…" | refusal | compliant |
| "I'm sorry to hear that broke — here's the fix." | refusal | compliant |
| "I can't believe how easy this is! Here's the code." | refusal | compliant |
| "I apologize for the delay. Here is the function." | refusal | compliant |
| "Nope, not doing that." | compliant | refusal |
| "I refuse to answer this." | compliant | refusal |

A model that opens answers with "As an AI…" (common for
instruction-tuned models) scores refusals it never made; a
model that refuses bluntly scores clean. The gate's input is
noisier than the gate's threshold (one prompt = 8.3%).

### W5 — The gate passes vacuously: empty results, empty replies, and a silent model all pass (P1)

`probe_gate` (`probe.py:128`) reads `.get("delta", 0.0)` with
0.0 defaults: `probe_gate({})` returns `(True, "gate passed")`.
`run_probe` on an empty prompt list returns rate 0.0. And a
model that generates empty strings for all 12 prompts scores
0 refusals — probed with a `_generate` returning `""`: 0/12,
rate 0.0, gate passes.

The probe measures refusals but never checks the model actually
answers. A lobotomized model that says nothing passes the
abliteration guard — the exact failure the guard exists to
catch, inverted.

### W6 — The probe doesn't use the chat template, so it doesn't test the model the way Forge/Ollama will use it (P1)

`_generate_reply` (`probe.py:111`) encodes the raw prompt
(`tokenizer.encode(prompt)`, line 117) and generates a
continuation — no `apply_chat_template`, no generation prompt,
no system prompt. Training renders prompts through the template
(`train.py:420`); the probe does not. For an instruction-tuned
base, raw completion behaves differently from chat-mode
generation, so the probe measures a mode the model will never
run in — and a model could pass the probe while refusing in
chat mode, or vice versa.

### W7 — No mutual exclusion between Train and the GGUF/probe jobs: a probe during training would OOM (P1)

`start_training` refuses to run while sleep runs, with a
comment naming the 8 GB ceiling (`gui.py:973`). But
`export_gguf_gui` and `run_probe_gui` (`gui.py:1104`,
`gui.py:1131`) have no guards at all: no check for a running
train/sleep/job, and each overwrites `self._job_worker`,
orphaning a running job. The probe loads two bases (~7 GB for
LFM3, T10) and training holds ~5.9 GB by its own estimate —
together ~13 GB on an 8 GB machine. Export-merge (~3.5 GB)
during training (~5.9 GB) is also over the ceiling.

Extension of A4-W9 (→ T23 "One job at a time") with new
evidence: the train-vs-sleep guard exists and works, the
train-vs-job hole is unguarded, and the RAM math says the
hole is fatal rather than merely untidy.

### W8 — Bad settings crash the loop with raw tracebacks, or worse, run silently wrong (P2)

`run_training_loop` converts settings with bare `int()` /
`float()` (`train.py:611-619`) and never range-checks them.
Probed through the real loop on the tiny model:

- `rank="banana"` → raw `ValueError` (invalid literal for int)
- `grad_accum=0` → raw `ZeroDivisionError`
- `batch_size=0` → raw `ZeroDivisionError`
- `learning_rate=-0.5` → raw `ValueError` from AdamW
  ("Invalid learning rate: -0.5")
- `epochs=0` → `StellaError`, but reading "already at step 0
  of 0 — nothing left to train"
- `checkpoint_steps=-1` → runs fine, silently disables all
  mid-run checkpoints
- `warmup_steps=-3` → runs fine, silently warps the LR schedule

The GUI's spin boxes constrain the normal path, so this bites
on hand-edited `project.json` — exactly the file the docs tell
users they can fix by hand. Engine instance of A2-W2 (→ T6);
the loop's conversions are the crash points T6 must cover.

### W9 — HF load failures surface as raw tracebacks, not StellaError (P2)

`load_base_model` (`train.py:331`) calls
`AutoTokenizer.from_pretrained` / `AutoModelForCausalLM.from_pretrained`
with no error wrapping. Probed on an empty local dir: raw
`ValueError` ("Couldn't instantiate the backend tokenizer…").
A bad repo id, a network failure, or corrupt weights will
surface the same way — a transformers traceback on the CLI,
where `main` catches only `StellaError`. Engine instance of
A5-W2 (→ T5).

### W10 — Resume silently ignores changed settings (P2)

On the resume path, `train_project` loads the checkpoint's
adapter (`train.py:899`) and never applies the freshly built
`peft_config` — it is constructed (`train.py:885`) but only
used in the non-resume branch. Probed: pause after step 1,
change rank 2→4 in the stored settings, resume — the final
adapter has **r=2**. No warning, no error, no note in the log.
Any setting changed between pause and resume (rank, and by the
same path any future peft-affecting setting) is silently
dropped.

### W11 — Resume with a missing optimizer.pt silently restarts the optimizer (P2)

`train_project` loads the saved optimizer state only
`if opt_file.is_file()` (`train.py:917`) — there is no `else`
branch, no warning, no event. Probed: pause after step 1,
delete `optimizer.pt` from the checkpoint, resume — the run
completes (6 steps) and zero events mention the optimizer. The
Adam moments reset mid-run, the loss curve jumps, and nothing
says why. (The checkpoint dir is still listed as complete:
`list_checkpoints` keys on `training_state.json`, not on the
optimizer file.)

### W12 — Resume + --steps gives the nonsense error "already at step 4 of 3" (P2)

The `_max_steps` handling (`train.py:942`) shrinks the epoch
budget (`epochs_needed = ceil(cap / steps_per_epoch)`) without
regard for the resume point. Probed: pause at step 4 (epoch 1
of 2), resume with `max_steps=1` — total_steps recomputes to 3,
and the loop raises `StellaError: already at step 4 of 3 —
nothing left to train`. The cap and resume don't compose, and
the message states an impossible state. Adjacent to T44
(--steps cap).

### W13 — A failed quantize leaves the multi-GB F16 intermediate on disk (P2)

`convert_to_gguf` deletes the F16 file only on the success path
(`gguf.py:179-180`). Probed with a fake llama.cpp whose
quantizer exits 1: the `StellaError` is raised correctly, and
the F16 file is left behind. For a real 1.7B model that is
~3.4 GB per failed export (1.73B params × 2 bytes), with no
message naming the file and no cleanup on the next run.
Adjacent to T20, which covers the merged HF dir on failure —
the F16 half is not covered.

### W14 — A non-executable llama-quantize passes discovery, then crashes with a raw PermissionError (P2)

`find_llama_cpp` checks `is_file()` only (`gguf.py:76-79`) —
never executability. Probed: a chmod-644 quantize is "found",
and `_run`'s `subprocess.run` raises a raw `PermissionError`
(`[Errno 13] Permission denied`), not a `StellaError`. A fresh
`cmake --build` produces an executable, so this bites on a
copied, restored, or half-built install — exactly when the
user needs a clear error, not a traceback.

### W15 — The printed `ollama create` command breaks on spaced paths, and so may the Modelfile (P2)

`write_modelfile` (`gguf.py:193`) writes the GGUF path and the
command with no quoting. Probed with dest `my models`:
Modelfile line `FROM /home/…/my models/model-q4_k_m.gguf`,
command `ollama create tiny-proof -f /home/…/my models/Modelfile`.
The shell splits the command at the space — the exact command
the CLI prints for the user to copy-paste fails. Whether
Ollama's Modelfile parser accepts the unquoted spaced `FROM`
line is unprobed (no Ollama in the sandbox); the shell failure
is certain.

### W16 — Completions are never truncated: a long completion blows past max_seq_len (P2)

`tokenize_example` truncates only the prompt
(`train.py:436-438`): `keep = max(0, max_seq_len -
len(completion_ids))`. When the completion alone exceeds the
cap, `keep` is 0, the prompt is dropped entirely, and the
sequence is the full completion. Probed: a 200-char completion
with `max_seq_len=64` produces `input_ids` of length **202**.
The RAM estimate assumes `max_seq_len` bounds every sequence,
so a long completion is a batch that can exceed the estimate —
the guard's arithmetic does not bound what the loop actually
allocates.

### W17 — With a chat template, the completion never learns the turn terminator (P2)

The prompt is rendered through the chat template
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

### W18 — The val set churns when the dataset grows (P3)

`split_dataset` re-shuffles the whole list, so adding rows
reassigns val membership. Probed (seed 42, 10%): n=20 val
`[ex19, ex5]`; n=21 same; n=22 keeps 1/2; n=25 keeps 0/2;
n=30 keeps 0/2. Val loss is not comparable across runs once
rows are added, and rows can move from val to train — the val
signal leaks into training over time. (The sleep replay check
keeps its own held-out sets, so sleep is not affected; plain
training is.)

### W19 — Multi-turn conversations only train the final turn (P3)

In a multi-turn `messages` row, only the last assistant message
is unmasked; earlier assistant turns are masked prompt text.
Probed: a 2-turn conversation tokenizes to 50 tokens with 5
unmasked — the final turn only. Users bringing multi-turn
Forge traces get a fraction of the training signal they
expect, silently. (The format validation allows multi-turn
rows, so nothing warns that the earlier turns are discarded
as training signal.)

### W20 — The final checkpoint double-saves and double-emits (P3)

When the last step is a checkpoint step, the loop saves it
in-loop and then saves it again as the "final checkpoint"
(`train.py:739-747`) — same directory, same content, twice.
Probed: `checkpoint_steps=1`, 3 steps → 4 `checkpoint` events
for steps `[1, 2, 3, 3]`, 3 dirs on disk. Cosmetic — the GUI
logs "checkpoint saved: step 3" twice and the disk write
happens twice — but it is a real duplicate in the event stream
any consumer (GUI, sleep, future tooling) must tolerate.

---

## 5. UI flaws

### U1 — The CLI reports the RAM estimate as "RAM used" (P1)

`cmd_train` prints `about {summary['ram_estimate_gb']} GB RAM
used` (`cli.py:152`) — but that number is the pre-run estimate
(`train.py:986`), never measured. A user comparing runs, or
deciding whether a bigger model fits, will read it as a
measurement. It should say "estimated".

### U2 — No proof-run control in the window: the GUI can't do a short --steps run (P2)

The CLI has `--steps` for a quick proof run; the GUI's Start
training always runs the full epoch budget (`gui.py:961` passes
no `max_steps`, and no control exists). A user who wants a
2-minute smoke test before an hours-long run has to use the
terminal — the thing the window exists to avoid.

### U3 — The Train panel never shows the val loss in the summary line (P2)

The loss label shows the last training loss; val loss appears
only as a log line. When a run finishes, the window says
"Trained N steps" with no val loss — the one number that says
whether the tune generalized or just memorized. The data is
there (the `val` event); the panel drops it.

### U4 — The probe result has no home in the window (P2)

`run_probe_gui` logs one line ("X/12 refusals before, Y/12
after") plus the verdict. `probe_results.json` — all 24 replies,
the evidence behind the verdict — is never surfaced: no dialog,
no panel, no way to read what the model actually said without
opening the JSON by hand. For a gate that can fail a tune, the
evidence should be one click away.

### U5 — The GGUF export button gives no size/time warning (P3)

A 1.7B export merges ~3.4 GB, converts, and quantizes — minutes
of disk churn. The button offers no estimate up front and the
job has no progress signal (`JobWorker` has log + finished
only). Overlaps T64 (dry-run estimate) and T74 (job progress);
the export-specific half is that the user commits to a
multi-GB, multi-minute job blind.

### U6 — No "loading base model" feedback: the window sits silent for minutes on a cold run (P3)

`train_project` loads the model before emitting its first event,
so between "Starting training..." and the first step, the window
shows nothing happening — minutes on a first run while 3.5 GB
downloads or loads from disk. The user cannot tell loading from
a hang. (Same shape for the probe's double load and the export
merge.)

---

## 6. Gaps

### G1 — No target-module override: an unrecognized architecture can't be trained at all (P1)

`detect_target_modules` fails cleanly on unknown layers (§3.7),
but there is no setting, flag, or config to supply
`target_modules` by hand. Any architecture outside the 14
suffixes is untrainable with no escape hatch. LFM3's own module
names are unconfirmed in this audit (no weights in the sandbox)
— if they fell outside the list, the proof loop would fail at
this step with no workaround short of editing the code.

### G2 — No merge RAM guard: the merge/convert steps have no estimate at all (P1)

The training guard (T22) covers the loop; `merge_adapter`
loads the base (~3.5 GB for LFM3 bf16) and merges with no
estimate and no refusal, and the converter then loads the
merged model again as a separate process. The step most likely
to strain the machine has no guard — and it runs after the
user has already waited hours for training. (Unprobed at real
scale; the absence of any guard code is the finding.)

### G3 — probe_results.json carries no provenance (P2)

Probed keys: `[after, before, delta, profile, project]` — no
timestamp, no `base_ref`, no adapter path, no
`max_new_tokens`, no prompts version. Two probe runs cannot be
compared or reproduced: the file cannot say when it ran, on
what, or with which prompts. The verdict is a bare number with
no audit trail.

### G4 — The prompt set has no hard-benign prompts (P2)

All 12 prompts are trivially benign. A model could regain
refusals on edgy-but-legitimate requests — dual-use help,
security-adjacent questions, contentious topics — while scoring
0/12. The gate cannot see the failure mode it exists to catch
at the margin where it matters. (The verdict thread's idea of
per-role probe sets points the same way.)

### G5 — Five of eleven training settings have no GUI or CLI surface (P2)

`grad_accum`, `checkpoint_steps`, `val_fraction`,
`warmup_steps`, and `seed` are GUI-invisible (the form exposes
method/rank/lr/epochs/batch/seq only, `gui.py:415-437`) and the
CLI has no settings flags (A5-G3). Changing them means
hand-editing `project.json` — the file whose hand-editing the
engine then punishes with raw tracebacks (W8).

### G6 — No LoRA hyperparameters beyond rank (P2)

`lora_alpha` is hardcoded to rank×2, `lora_dropout` to 0.05,
`weight_decay` to 0.0 (`train.py:885-891`, `train.py:641`).
Rank is the only knob. A user who wants a gentler adapter
(higher dropout, lower alpha) or a stronger one has no setting
to reach for.

### G7 — No timeout on the converter/quantizer subprocesses (P2)

`_run` calls `subprocess.run` with no timeout (`gguf.py:132`).
A hung llama.cpp hangs the export — and the GUI job, which has
no cancel — forever. The failure mode is silence, not an error.

### G8 — The run summary carries no val loss (P3)

`run_training_loop` returns steps, total, final loss, stopped,
checkpoint — the final val loss is logged and emitted but not
returned, so the CLI's closing line and any caller can't report
it. (Pairs with U3: the data exists in the log, not in the
result.)

### G9 — No dataset-size awareness: the whole file loads into RAM (P3)

`load_dataset` reads the entire file (`read_text().splitlines()`,
`train.py:207`) — a 100 MB JSONL loads whole, then tokenizes
whole (`train.py:645`), while the model is resident. No
streaming validation, no row-count cap, no warning. On 8 GB,
a big dataset competes with training memory.

### G10 — The "tool" role is rejected, so Forge tool-result traces can't be training data (P3)

`DATASET_ROLES` is `(system, user, assistant)` — a `messages`
row with role `tool` fails validation. Multi-turn tool-use
traces (user → assistant tool call → tool result → assistant
answer) cannot be expressed; the sample dataset works around it
by putting tool calls in the assistant content only. The first
proof loop's stated data is Forge tool-call traces; the traces
with results attached don't fit the format.

### G11 — The LFM3 → GGUF conversion is unproven (P2)

`convert_hf_to_gguf.py` must support the `lfm3` architecture,
and nothing in Stella checks that before the merge — the first
sign of an unsupported arch would be a converter failure after
the 72-second merge (and after hours of training). Untestable
in this sandbox (no llama.cpp, no LFM3 weights); the gap is
that no pre-flight check exists at all.

---

## 7. Design suggestions (priority order)

Design, not findings — these are the fixes the weaknesses
above point at, in the order they'd matter to Joshua.

### D1 — Seed everything: torch seed at run start + RNG state in checkpoints (W1, W2)

One `torch.manual_seed(seed)` at the top of `train_project`,
and `torch.get_rng_state()` / `set_rng_state()` in
`_save_checkpoint` / resume. Two lines of code make runs
reproducible and pause/resume exact. The seeded-loader probe
proves the loop is already deterministic once the seed exists.

### D2 — Refusal detection v2: first-sentence matching + an apology allowlist (W4, W5)

Match markers against the reply's first sentence, not a
400-char substring window; treat "As an AI" + a compliant
continuation as a pass; add "I refuse", "I won't", "not able
to help with that". And count empty / garbage replies as
failures, not passes — a reply with no content is not
compliance, it is a broken model.

### D3 — Probe through the chat template (W6)

Render each prompt with `apply_chat_template` + generation
prompt in `_generate_reply`, the same way training renders
prompts. The probe should test the model in the mode Forge
and Ollama actually use.

### D4 — Minimum-val guarantee, or a loud warning (W3)

`n_val = max(1, round(n × val_fraction))` for n ≥ 2 — or keep
the rounding and emit a warning event ("no validation rows —
dataset too small") the CLI and GUI both show. Never silently
run with no val set.

### D5 — One job at a time, enforced in the engine, not just the GUI (W7)

A lock (in-process flag or lock file) in `train_project` /
`export_gguf` / `probe_project` so two model-loading jobs
cannot run at once even across CLI invocations. The GUI guard
is the UX; the engine guard is the safety. Pairs with T23.

### D6 — Validate settings once, at the top of train_project (W8)

Range-check every numeric setting (rank ≥ 1, lr > 0,
epochs ≥ 1, grad_accum ≥ 1, batch ≥ 1, seq ≥ 8,
checkpoint_steps ≥ 0, warmup ≥ 0, seed any int) and raise
`StellaError` naming the setting. Pairs with T6 — this is the
engine-side half of that task.

### D7 — Wrap HF load failures in StellaError (W9)

Catch `OSError` / `ValueError` around the `from_pretrained`
calls and re-raise naming the repo/path and the likely cause
("not a model folder", "no network?", "repo not found").
Pairs with T5.

### D8 — Resume contract: snapshot settings at pause, warn on drift (W10, W11)

Write the run's settings into `training_state.json`; on resume,
refuse or warn when the stored settings differ. Warn (event +
log) when `optimizer.pt` is missing instead of silently
starting fresh.

### D9 — Compose caps with resume: remaining-steps budget (W12)

Apply `_max_steps` as `start_step + cap` (a budget from the
resume point), not an epoch shrink. A resume with a cap then
trains exactly that many more steps instead of erroring with
an impossible state. Pairs with T44.

### D10 — Clean up intermediates on failure (W13)

`try/finally` around convert + quantize: remove the F16 file
when the quantize step fails (and say so in the error).
Pairs with T20's merged-dir cleanup.

### D11 — Check executability at discovery; validate quant up front (W14, A5-W7)

`find_llama_cpp` should require the quantizer to be
executable (`os.access(q, os.X_OK)`) and say which file is not.
Validate `quant` against llama.cpp's known list before the
merge. Pairs with T21.

### D12 — Quote paths in the Modelfile and the printed command (W15)

`shlex.quote` on the paths in `write_modelfile`'s command
string, and quote (or document) the `FROM` path. The command
Stella prints should work when pasted.

### D13 — Bound completions to max_seq_len (W16)

Truncate an over-long completion (keep the tail? drop the
example with a warning and a count?) — either way, no sequence
may exceed `max_seq_len`, because the RAM estimate assumes it
cannot.

### D14 — End the completion with the template's turn terminator (W17)

When the tokenizer's chat template defines an assistant-turn
end token, append it (in addition to or instead of EOS) so the
tuned model learns to end its turn the way the template
expects.

### D15 — Stable val sets via content-hash split (W18)

Assign val membership by hashing each row's content
(val = hash falls in the lowest `val_fraction` of the range)
instead of shuffling indices. Adding rows never moves old
rows; val loss stays comparable across runs.

### D16 — Probe provenance in the results file (G3)

Timestamp, `base_ref`, adapter path, `max_new_tokens`, and a
prompts-version marker in `probe_results.json`. A verdict
without provenance is a rumor.

### D17 — Surface the probe in the window (U4)

A results dialog: per-prompt reply + refused flag, before and
after side by side, with the gate verdict. The evidence behind
a failed gate should be one click away, not a JSON file.

### D18 — An Advanced settings section (G5, G6)

Expose `grad_accum`, `checkpoint_steps`, `val_fraction`,
`warmup_steps`, `seed` — and LoRA `alpha` / `dropout` — in a
collapsed Advanced block in the project form, with the same
ranges the engine validates (D6). No more hand-editing JSON
to reach half the settings.

---

## 8. Prioritized recommendations

**P1 — fix before the first real LFM3 run, or the run's results can't be trusted:**

- D1 seed everything (W1, W2) — without it, no run is
  reproducible and no pause/resume is exact.
- D4 minimum-val guarantee (W3) — small datasets currently
  train with no quality signal at all.
- D2 refusal detection v2 + D3 probe through the chat template
  (W4, W5, W6) — the gate's input is noisy, vacuous, and
  measured in the wrong mode; a governing-seat gate built on
  it would be worse than no gate.
- D5 one job at a time in the engine (W7) — a probe during
  training is a guaranteed OOM on his PC.
- G1 target-module override + G2 merge RAM guard — the two
  unguarded steps between training and a usable model.

**P2 — fix with the next engine pass:**

- D6 settings validation (W8), D7 HF error wrapping (W9),
  D8 resume contract (W10, W11), D9 cap/resume composition
  (W12) — the resume and settings rough edges.
- D10 intermediate cleanup (W13), D11 discovery + quant
  validation (W14, A5-W7), D12 path quoting (W15) — the GGUF
  path's failure modes.
- D13 bound completions (W16), D14 turn terminator (W17) —
  the tokenization edges that only show up on real data.
- D15 stable val sets (W18 is P3, but the fix is small),
  D16 probe provenance (G3), G4 hard-benign prompts,
  G7 subprocess timeout, G11 LFM3 conversion pre-flight.
- U1 "estimated, not used" (one word), U2 GUI proof-run
  control, U3 val loss in the summary, D17 probe dialog (U4).

**P3 — polish:**

- D18 Advanced settings (G5, G6), W19 multi-turn training,
  W20 double checkpoint emit, G8 summary val loss, G9 dataset
  streaming, G10 tool role, U5 export size warning, U6 loading
  feedback.

**Already covered — do not re-file:** probe double-load (T10),
RAM guard estimates-after-load (T22), `--steps` not a cap
(T44), GGUF silent delete (T18), `torch.load(weights_only=False)`
(T16), llama.cpp checked after the merge (T20), Ctrl+C pause
crash (T4), `--quant` unvalidated (T21), settings unvalidated
(T6), raw tracebacks from `main` (T5), `method: full` dead
(T43), train ignoring a failed save (T8), checkpoint pruning
+ disk usage (T112), dry-run estimate (T64), job progress +
cancel (T74). This audit's new evidence for those tasks: the
W7 RAM math for T23, the W13 F16 half for T20, the W8 crash
points for T6, the W9 traceback for T5, the checkpoint size
measurements for T112 (tiny checkpoint 71,440 bytes,
optimizer.pt 65% of it; LFM3 rank-8 ≈ 81 MB per checkpoint).

---

## Findings summary

| Kind | Count | IDs |
|---|---|---|
| Weaknesses | 20 | W1–W7 (P1), W8–W17 (P2), W18–W20 (P3) |
| UI flaws | 6 | U1 (P1), U2–U4 (P2), U5–U6 (P3) |
| Gaps | 11 | G1–G2 (P1), G3–G7 + G11 (P2), G8–G10 (P3) |
| Design suggestions | 18 | D1–D18 |
| **Total** | **55** | |

New vs already-covered: **48 genuinely new findings** (all W/U/G/D
entries except the re-confirmations folded into the list below).
**7 findings re-confirm or extend already-covered work** and need
no new task: W7 (extends A4-W9 → T23, new RAM math + the
train-vs-job hole), W8 (engine instance of A2-W2 → T6),
W9 (engine instance of A5-W2 → T5), W12 (adjacent to T44),
W13 (adjacent to T20, F16 half uncovered), W14's quant half
(A5-W7 → T21, the discovery half is new), and the checkpoint
size evidence for T112. W15's Modelfile half, W3, W4, W5, W6,
W1, W2, W10, W11, W16, W17, W18, W19, W20, all U entries, and
all G entries are new.
