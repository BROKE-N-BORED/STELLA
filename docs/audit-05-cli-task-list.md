# STELLA Audit #5 — CLI: Task List

**Source:** [audit-05-cli-2026-11-12.md](audit-05-cli-2026-11-12.md)
(CLI audit, 2026-11-12 evening, against v0.2 / commit 9a821e07).

**This file is a list only.** Nothing here has been fixed or built.
Each task turns one or more audit findings into work with a verifiable
"done". Priorities follow the audit's section 7; within a priority,
a fix comes before the polish that depends on it.

**Finding IDs carry the A5 prefix** (audit #5), matching the merged
list. Cross-references to earlier audits keep their own prefixes
(A1-, A2-, A3-, A7-, R-).

**Priority key:** P0 = data loss / silent failure, fix first.
P1 = real functional defect or daily friction. P2 = missing capability
or inconsistency. P3 = polish, display, and scale.

**Effort key:** S = a focused change in one or two files, a day or
less. M = a change across model + GUI + tests, or a small design
decision plus implementation. L = a multi-part build or a design that
needs Joshua's direction on scope first.

**Counts:** 18 tasks — 2 P0, 6 P1, 7 P2, 3 P3.

**Shared fixes with earlier audits:** several findings share their
fix with earlier work and are built once, not twice. The `--steps`
cap (A5-W3) is the repo-audit verdict's R11, already a merged task;
the corrupt-profile warning (A5-W9) is audit #1's W1, re-verified on
the CLI; the orphan-profile import (A5-W10) is audit #3's W1,
re-verified on the CLI; the import instances of the traceback
finding (A5-W2) are audit #3's W1/W2 at the same trust boundary,
and its string-metamorph instance is the CLI half of audit #7's W4
(the GUI half); the missing commands (A5-G1/G2/G3) are audit #1's W9
and audit #2's W11, re-verified on the CLI; and the verify command
(A5-G4) is audit #3's G5. In this standalone file they appear as
audit #5 tasks (T3, T9, T2, T16); the merged list
([stella-audit-task-list-123.md](stella-audit-task-list-123.md))
folds them into the single shared tasks.

**One probe is not a finding:** the report discloses that its
read-only-home check ran as root and proved nothing (root writes
through read-only permissions). No task comes from it, and it is not
counted in the 47 findings below.

---

## P0 — fix first

### T1 — Ctrl+C must pause the run, not crash it

- **Covers:** A5-W1, A5-D1
- **Effort:** S
- **Problem:** The SIGINT handler prints from inside the signal
  handler (`cli.py:121-124`): it calls `controller.request_stop()`
  and then `print("\nPausing after this step (checkpoint will
  save)...", flush=True)`. If the signal lands while the main
  thread is inside the step-line `print` in `on_event`
  (`cli.py:103-109`), CPython raises `RuntimeError: reentrant call
  inside <_io.BufferedWriter name='<stdout>'>`. That is exactly
  what the probe hit on its first try: SIGINT sent after step 3 of
  a 54-step run → exit 1 with a raw traceback, train log stopped
  at 3 steps, status `paused`, **no checkpoint saved**, no adapter.
  The follow-up `train --resume` then failed with `stella: nothing
  to resume — this project has no checkpoints yet`. All progress
  since the last checkpoint (here: everything) was lost, and the
  run's status says `paused` with nothing to resume from. The race
  is not rare in practice: the natural moment to press Ctrl+C is
  right after a step line appears — which is the window the handler
  re-enters. A second run with `python -u` (unbuffered stdout, no
  `BufferedWriter` to re-enter) paused correctly — checkpoint
  step-4 saved, exit 0, `Paused at step 4 — resume with --resume.`
  — which confirms the mechanism: the crash is the handler's
  `print` against buffered stdout. The comment above the handler
  (`cli.py:117-119`) claims "Ctrl+C pauses cleanly" — the claim is
  false in exactly the window a user hits. This is the CLI's
  headline safety feature, and it is a coin flip.
- **Fix:** D1 — remove the `print` from `_sigint`. The loop already
  prints `Paused at step N — resume with --resume.` via the
  `paused` event, so the handler's message is redundant — and it
  is the thing that crashes. A signal handler should never touch a
  buffered stream; if a message is wanted at the moment of the
  keypress, write it with `os.write(1, ...)` instead.
- **Done:** SIGINT mid-run pauses cleanly — checkpoint saved, exit
  0, `Paused at step N` printed once; `--resume` continues from
  the checkpoint. Tests: subprocess Ctrl+C-pause test against a
  stubbed or tiny training loop (the crash shipped because nothing
  tested the pause — see T15).

### T2 — `main()` must catch everything; the list commands must read defensively

- **Covers:** A5-W2, A5-D2
- **Effort:** S
- **Problem:** `main()` catches only StellaError
  (`cli.py:287-293`); every other exception escapes as a full
  traceback, exit 1. Verified instances in v0.2: `profiles` on a
  home with a valid-JSON profile manifest missing `"name"` →
  `KeyError: 'name'` at `cli.py:40` (`p['name']` with no default),
  crashing the whole list (new in this audit; `get_profile` sets a
  default name, `list_profiles` does not); `projects` on a project
  whose `metamorph` is a string → `AttributeError: 'str' object
  has no attribute 'get'` at `cli.py:51` (new in this audit — the
  CLI half of audit #7's W4, whose GUI half is the same pattern in
  `gui.py:449`); `export` with a destination that is a file →
  `NotADirectoryError` traceback (audit #3, re-verified); `import`
  of a manifest with `settings` as a string → `ValueError`
  traceback (`model.py:305`); with `metamorph` as a string →
  `AttributeError` traceback (A3-W1/W2, re-verified on the CLI);
  and the W1 `RuntimeError` above. A user who hand-types commands
  and gets a traceback has no idea what went wrong or what to do
  next. The StellaError discipline in the audit's §2 shows the
  intended behavior; the catch-all is missing.
- **Fix:** D2 — wrap the dispatch in `except Exception` that prints
  `stella: <plain message>` to stderr and exits 1, with the
  traceback available behind a `--verbose`/`--debug` flag (see
  T16). Separately, make the list commands defensive:
  `p.get("name")` with a fallback in `cmd_profiles`, and a type
  check on `metamorph` in `cmd_projects` (through the shared
  defensive reader from the audit #7 task family), so one bad
  manifest degrades to a warning line instead of killing the whole
  list. The import instances are fixed at the boundary by the
  trust-boundary task (strict validation + atomic import); this
  task is the last-resort net, not the validation.
- **Done:** Every probed bad input prints one clean `stella:` line
  on stderr, exit 1, no traceback (unless `--verbose`); `profiles`
  lists the rest with a warning line for the nameless manifest;
  `projects` lists the rest with a warning row for the
  string-metamorph project. Tests: nameless manifest, string
  metamorph, file-destination export, bad import manifest — all
  clean exits.

---

## P1 — functional defects and daily friction

### T3 — `--steps` must be a real cap, and the help must say what it does

- **Covers:** A5-W3, A5-D3
- **Effort:** S
- **Problem:** The help text says `--steps` will "cap the run at N
  optimizer steps (proof run)" (`cli.py:255-256`). Probes against
  the real tiny run: `--steps 2` → `Training: 3 steps` — the run
  rounds UP to whole epochs, so it EXCEEDS the stated cap (the
  printed total is honest, but the flag does not cap); `--steps 0`
  → `Training: 9 steps` — the full 3-epoch run, because zero is
  falsy and the cap block is skipped entirely (`train.py`:
  `settings["_max_steps"]=0` is falsy), so a user typing
  `--steps 0` expecting a dry run gets a full training run;
  `--steps -1` → `Training: 3 steps` — one epoch, silently.
  There is no argparse validation on the value at all. The
  whole-epoch rounding is defensible; the silent 0/-1 meanings
  and the "cap" wording that the behavior contradicts are not.
  (Same finding as the repo-audit verdict's R11 — the merged list
  folds this onto the existing `--steps` task rather than minting
  a duplicate; the fix is the same.)
- **Fix:** D3 — reject `--steps 0` and negative values in argparse
  (a `type=` check, or a post-parse guard) with a plain error.
  Make the cap real (the run stops at N optimizer steps — a
  partial final epoch is fine for a proof run) or document the
  whole-epoch rounding honestly in the help text and print the
  real total before starting. The `Training: N steps` line already
  prints the real total — the flag text should match it.
- **Done:** `--steps 2` runs at most 2 steps (or the help text
  says honestly that it rounds up and prints the real total);
  `--steps 0` and `--steps -1` are refused with a readable error.
  Tests: cap respected, 0/negative rejected.

### T4 — Refuse or confirm re-training a trained project, and say when resume extends one

- **Covers:** A5-W4, A5-W13, A5-D4
- **Effort:** S
- **Problem:** Running `train` again on a project whose status is
  `trained` exits 0 and re-runs the whole schedule, deleting and
  re-saving the adapter (`run_training_loop` removes the adapter
  dir before saving). Verified: the second run printed the same
  `Training: 3 steps ... Done — adapter saved` output with no
  warning of any kind. A user who re-runs a command from shell
  history — or who forgets a project is already trained — destroys
  a finished adapter and burns the training time again, with no
  prompt and no `--force` to make the intent explicit. And
  `--resume` on a completed project silently extends the training:
  the proof project finished its `--steps 2` run (1 epoch, 3
  steps, status `trained`); `train --resume` on it exited 0 and
  ran steps 4–9 — the full 3-epoch schedule — because the
  `_max_steps` cap from the first run lives only in the CLI
  invocation, not in the project. Nothing in the output says the
  project was already trained or that the run is now extending
  past what the user originally asked for.
- **Fix:** D4 — if a project is already `trained`, `train` should
  refuse with a plain message (`already trained — use --force to
  re-train`) instead of silently overwriting the adapter, and
  `--resume` on a trained project should say it is extending a
  finished run (and what the new total will be) before starting.
  `--force` makes the destructive intent explicit.
- **Done:** Re-training a trained project without `--force`
  refuses with a readable message and leaves the adapter
  untouched; with `--force` it re-trains; `--resume` on a trained
  project announces the extension and the new total first. Tests:
  refuse without `--force`, `--force` re-trains, resume-on-trained
  announces.

### T5 — Cheap checks before the train deps gate

- **Covers:** A5-W5, A5-D5
- **Effort:** S
- **Problem:** On a base install (no torch), `train_project` calls
  `require_training_deps()` before it looks up the profile or the
  dataset. Probes: a nonexistent profile, a missing dataset, and
  `--resume` with no checkpoints all reported `Training packages
  missing: torch, transformers, peft, accelerate.` plus the
  install hint — never the real problem. The user installs the
  packages and only then learns the profile name was wrong.
  `probe` and `export-gguf` already do this the right way (cheap
  checks first, per the code comment in `probe.py`); train is the
  odd one out.
- **Fix:** D5 — move the profile lookup, dataset resolution, and
  checkpoint check ahead of `require_training_deps()` in
  `train_project`, the way `probe` and `export-gguf` already do.
  The deps message should only appear when the run is otherwise
  ready to start.
- **Done:** On a base install, `train` with a bad profile name
  reports the bad profile, not the deps; with a missing dataset,
  the dataset; with no checkpoints, nothing to resume. The deps
  message appears only when everything else is ready. Tests: each
  cheap check fires before the gate on a base install.

### T6 — Check llama.cpp before the merge; clean up the merged dir on failure

- **Covers:** A5-W6, A5-D6
- **Effort:** S
- **Problem:** With llama.cpp missing, the export ran the full
  merge first — 72.1 seconds of wall time on the tiny model,
  `Loading weights` and `Writing model shards` bars on stderr —
  and only then failed with the (good) message `stella: llama.cpp
  is incomplete: missing convert_hf_to_gguf.py, llama-quantize.`
  plus the install hint. The merged directory (`proof-merged-hf`)
  was left behind in the output dir. On the tiny model that is
  kilobytes; on a real 1.7B model it is ~3.4 GB of merged weights
  sitting in the output folder after a failed export, with no
  message saying it is there or that it is safe to delete. The
  check is cheap; the merge is not. The order is backwards. (The
  verdict's R12 covers the opposite direction — a successful
  export silently deleting the *previous* output; this task is the
  failed export leaving its own mess behind.)
- **Fix:** D6 — call the llama.cpp completeness check before the
  merge, not after it, so a missing install fails in a second
  instead of after a multi-minute merge. And if the export fails
  after the merge, remove the merged directory (or say where it
  is and that it is safe to delete) instead of leaving ~3.4 GB
  behind silently.
- **Done:** `export-gguf` with no llama.cpp fails in under a few
  seconds with the install hint and no merged dir left behind; a
  failure after the merge leaves no orphaned merged weights (or
  names the dir and says it is safe to delete). Tests:
  missing-llama.cpp fast-fail, no leftover merged dir.

### T7 — Validate `--quant` up front

- **Covers:** A5-W7, A5-D7
- **Effort:** S
- **Problem:** `--quant BOGUS` exited 0 and printed `GGUF (BOGUS):
  .../proof-bogus.gguf (800 bytes)` with the full success output.
  Nothing in `cli.py` or `gguf.py` checks the value — no `choices`
  list, no validation against llama.cpp's quant types. With a real
  llama.cpp the failure would come from `llama-quantize` at the
  END of the pipeline, after the merge and the convert — the same
  fail-slow shape as W6, for a value that could be rejected in a
  millisecond.
- **Fix:** D7 — give `--quant` a `choices` list of the quant types
  llama.cpp accepts (or validate against the installed
  `llama-quantize`'s list), so `--quant BOGUS` fails in a
  millisecond with the valid values named instead of after the
  whole pipeline.
- **Done:** `--quant BOGUS` exits 1 with a plain error naming the
  valid values; every valid quant still exports. Tests: bogus
  quant refused, each valid quant accepted.

### T8 — Help text for every flag, examples in every command, fix the doc drift

- **Covers:** A5-U1, A5-U2, A5-D11
- **Effort:** S
- **Problem:** `create-profile --tag`, `--role`, and `--display`
  have no help at all (`cli.py:235-237`); only `--base` does.
  `create-project --display`, `--dataset`, and `--metamorph` have
  no help either (`cli.py:246-249`) — `--metamorph` shows its
  choices but not what they mean. None of the nine commands shows
  an example in `--help`. For a user who hand-types from a phone
  screen, `--help` is the manual — and for the two create commands
  it is nearly blank. And the docs disagree with the commands that
  exist: the `cli.py` module docstring (`cli.py:1-11`) lists seven
  commands and omits `create-profile` and `create-project`
  entirely; the README's "Command line" section lists the same
  seven and omits the same two; the `stella-cli` header comment
  says `bash stella <command>` — but the file is `stella-cli`;
  `stella` is only the name after install; and the empty-home hint
  says `or: stella create-profile ...` (`cli.py:31`) — before
  install, that command does not exist; the working form is `bash
  stella-cli create-profile ...`. Four small drifts, one effect: a
  user following the docs types a command that does not exist.
- **Fix:** D11 — give `--tag`, `--role`, `--display`, `--dataset`,
  and `--metamorph` real help strings (what the flag means, with an
  example value), and add an `epilog` with one or two worked
  examples per command — `stella create-profile lfm3 --tag
  lfm3:1.7b --role fast --base LiquidAI/LFM3-1.7B` is the obvious
  first one. Fix the four drifts: the module docstring and README
  list all nine commands, the wrapper comment says `bash
  stella-cli`, and the empty-home hint uses the name that works
  before install. (The `--metamorph` help text itself is audit #7's
  T17 in the merged list; this task is the rest of the flags plus
  the examples and the drift.)
- **Done:** Every flag on every command has help text; every
  command's `--help` shows a worked example; the docstring, README,
  wrapper comment, and empty-home hint all name commands that
  exist. Tests: help output contains the flag meanings and
  examples.

---

## P2 — missing capabilities and inconsistencies

### T9 — Existence checks, corrupt warnings, atomic import

- **Covers:** A5-W8, A5-W9, A5-W10, A5-D8
- **Effort:** S
- **Problem:** Three small trust-boundary holes, all probed on the
  CLI. W8: `stella projects ghost` → exit 0, `No projects in
  profile 'ghost'.` — byte-identical in shape to an empty real
  profile. `list_projects` returns `[]` when the directory is
  missing, and `cmd_projects` never checks the profile exists. A
  typo'd profile name reads as "you haven't made any projects yet"
  instead of "that profile doesn't exist". W9: a home with one
  corrupt `profile.json` (bad JSON) lists the rest and exits 0
  with no warning at all; `projects` on the corrupt profile prints
  `No projects in profile 'broken'.` and exits 0. (A1-W1,
  re-verified on the CLI.) W10: importing a manifest whose
  `settings` is a string crashed with the `ValueError` traceback
  in W2 — and left the newly-created profile behind
  (`['lfm3-tool']` in the profiles dir). The import is not atomic:
  the profile is created before the manifest is validated.
  (A3-W1/W2, re-verified on the CLI.)
- **Fix:** D8 — `projects` should check the profile exists first
  (`No profile named 'ghost'`, exit 1). `profiles` should warn on
  stderr for each unreadable profile instead of skipping it
  silently. Import should validate the manifest before creating
  the profile, so a bad import leaves nothing behind. (In the
  merged list, W9 folds onto the damaged-rows task and W10 onto
  the trust-boundary import task; only the W8 existence check is
  a new merged task.)
- **Done:** `projects` on a nonexistent profile exits 1 with a
  plain error; a corrupt profile is warned about, not skipped; a
  bad import leaves the home untouched. Tests: ghost profile
  refused, corrupt profile warned, failed import leaves no orphan.

### T10 — Second Ctrl+C force-quits; make the download interruptible

- **Covers:** A5-W11, A5-D9
- **Effort:** S
- **Problem:** Code-grounded (`cli.py:121-124`, `train.py`): the
  handler only sets the stop flag and prints, every time —
  pressing Ctrl+C a second time does not force-quit, it just
  re-requests the same graceful stop. And the base-weight download
  (`from_pretrained`, a blocking call) runs before the loop the
  handler can stop: a Ctrl+C during a long download is swallowed
  until the download returns, so a user who fat-fingered the base
  repo waits for the whole download before the run can be stopped.
  Not probed live (no network download in the sandbox); the
  mechanism is direct from the code.
- **Fix:** D9 — track whether a stop was already requested: the
  first Ctrl+C pauses gracefully (T1), the second exits
  immediately. For the base download, run it in a way the stop
  flag can interrupt (or at least print `Downloading base weights
  — Ctrl+C takes effect when the download finishes` so the wait is
  not a mystery).
- **Done:** A second Ctrl+C during a run exits immediately; a
  Ctrl+C during the download either interrupts it or the user was
  told it would wait. Tests: second-Ctrl+C exits (stubbed loop),
  download message shown.

### T11 — A distinct exit code for a failed probe gate

- **Covers:** A5-W12, A5-D10
- **Effort:** S
- **Problem:** `cmd_probe` returns `0 if passed else 1`
  (`cli.py:189`). A script — or a user reading the exit code —
  cannot tell "the probe ran and the gate failed" from "the probe
  crashed". The gate message itself goes to stdout, mixed with the
  results, so there is no clean way to separate the verdict from
  the numbers either.
- **Fix:** D10 — return a code other than 1 for "probe ran, gate
  failed" (3, say — 2 is argparse's), and print the gate verdict
  to stderr or behind `--json` (T16) so scripts can read the
  verdict separately from the numbers.
- **Done:** A failed gate exits 3 (not 1); a crashed probe still
  exits 1; the verdict is readable separately from the numbers.
  Tests: gate-fail exit 3, crash exit 1, informational exit 0.

### T12 — Silence the library warnings on stderr

- **Covers:** A5-U4, A5-D12
- **Effort:** S
- **Problem:** Every `train`, `probe`, and `export-gguf` run prints
  transformers deprecation warnings (`torch_dtype` is deprecated),
  a peft `UserWarning` about `fan_in_fan_out`, the `train.py:642`
  `UserWarning` about converting a tensor with `requires_grad=True`
  to a scalar, and tqdm progress bars (`Loading weights:
  100%|...|`) — all on stderr, before and around Stella's own
  messages. The user cannot tell Stella's errors from library
  noise, and a redirected stderr log is mostly chatter.
- **Fix:** D12 — filter the known-noisy warnings in the CLI entry
  point (`warnings.filterwarnings` for the transformers/peft
  notices, `TRANSFORMERS_NO_ADVISORY_WARNINGS`, tqdm disabled or
  routed), and fix the `train.py:642` float() call with
  `.detach()`. stderr should carry Stella's messages, not the
  libraries'. (Verify at build time: the `train.py:642` float()
  fix may already have landed in v0.3 — if so, this task is the
  filtering only.)
- **Done:** A heavy run's stderr carries Stella's messages and no
  library deprecation warnings or tqdm bars (unless a verbose flag
  asks for them). Tests: stderr of a tiny run contains no
  transformers/peft warnings.

### T13 — CLI-appropriate error text

- **Covers:** A5-U5, A5-D13
- **Effort:** S
- **Problem:** `train` on a project with no dataset prints:
  `stella: project 'nodata' has no dataset set — pick a .jsonl
  dataset in the Train panel, or use the sample dataset`. A
  terminal user has no Train panel open. The error should name the
  CLI fix (`--dataset`, or `create-project --dataset`).
- **Fix:** D13 — the no-dataset error should name the CLI fix:
  `use --dataset <file>` (or `create-project --dataset <file>`).
  Audit the other error strings for GUI pointers the same way.
- **Done:** The no-dataset error names `--dataset`; no CLI error
  string points at a GUI control. Tests: no-dataset error text,
  error-string audit (grep for GUI pointers in `cli.py` error
  paths).

### T14 — Progress for long phases; honest paused/resumed output

- **Covers:** A5-U6, A5-U7, A5-U8, A5-D14
- **Effort:** S
- **Problem:** `probe` prints nothing at all while it loads two
  models and runs 24 generations (12 prompts, before and after) —
  on the tiny model that was a ~6-minute silence (only tqdm bars
  on stderr). `export-gguf` is the same during the merge. A user
  watching the terminal cannot tell a working run from a hung one.
  And a paused run's final summary reads like a completed run: the
  successful pause printed `Paused at step 4 — resume with
  --resume.` and then, on the next line, the same `Trained 4
  steps, final loss 0.5663, 16,384 trainable params, about 1.0 GB
  RAM used.` summary a completed run prints — only the one "Paused"
  line distinguishes them, and the paused run exits 0. A user
  scanning the tail of the output sees a run that looks finished.
  And resume prints a stale validation line: the resumed run
  printed `epoch 1 validation loss 0.5450` before `step 4/9` — a
  re-evaluation of the already completed epoch, with the same value
  as the first run. Harmless, but confusing: the output claims an
  epoch finished that the resumed run never trained.
- **Fix:** D14 — print a line when the probe starts each pass
  (`Probing before tuning...`, `Probing after tuning...`) and when
  the GGUF merge starts, so a multi-minute run is never silent.
  Make the paused summary say `Paused after 4 steps` instead of
  reusing the completed-run wording, and skip the re-evaluated
  validation line on a resumed epoch with no new steps.
- **Done:** A probe run prints a line per pass; the GGUF merge
  prints a start line; a paused run's tail says Paused, not
  Trained; a resumed run prints no validation line for an epoch it
  did not train. Tests: pass lines present, paused wording, no
  stale validation line.

### T15 — Tests for the risky CLI paths

- **Covers:** A5-G7, A5-D17
- **Effort:** S
- **Problem:** The 14 tests in `test_cli.py` cover happy paths and
  a few clean error paths. Nothing tests: the Ctrl+C pause (W1 —
  the crash shipped untested), `--steps` 0/negative/rounding (W3),
  a corrupt home or a nameless manifest (W2/W9), export to a file
  destination or a bad import manifest (W2/W10), `--quant`
  validation (W7), resume (W13), or the exit-code/stderr contract
  for unknown commands. The riskiest paths are exactly the
  untested ones.
- **Fix:** D17 — cover what this audit found untested: a subprocess
  Ctrl+C-pause test against a stubbed or tiny training loop (W1),
  `--steps` 0/negative/rounding (W3), corrupt home and nameless
  manifest (W2/W9), file-destination export and bad-manifest import
  (W2/W10), `--quant` validation (W7), resume on a trained project
  (W13), and the exit-code/stderr contract for unknown commands.
  After the fixes they pin (T1, T2, T3, T4, T7 first).
- **Done:** One test per risky path; all pass. Tests: this task IS
  the tests.

---

## P3 — polish, display, and scale

### T16 — The missing commands: rename/delete/update, show, settings, verify, --json

- **Covers:** A5-G1, A5-G2, A5-G3, A5-G4, A5-G5, A5-D15
- **Effort:** M
- **Problem:** The CLI can create and list, and nothing else. G1:
  there is no `rename-profile`, `delete-profile`,
  `update-profile`, `rename-project`, `delete-project`, or
  `update-project` (all probed: exit 2, unknown command). Every
  mutation beyond creation needs the GUI or hand-editing JSON.
  (A1-W9 and A2-W11, both still holding in v0.2.) G2: there is no
  `show`, `show-profile`, `show-project`, `status`, or
  `checkpoints` command (all probed: exit 2). A user cannot ask
  what a project's dataset is, what its settings are, what
  checkpoints it has, or what state it is in — except by reading
  the JSON files by hand. Most sharply: there is no way to see
  what `train` is about to use (rank, epochs, learning rate)
  before starting a run that may take hours. G3: `create-project`
  takes no settings flags, and there is no update command (G1), so
  the CLI cannot set rank, epochs, learning rate, batch size, or
  any other training setting. `stella train` always runs the
  DEFAULT_TRAIN values (rank 8, lr 0.0002, 3 epochs, batch 1,
  grad_accum 8, max_seq_len 1024, checkpoint every 50 steps)
  unless the user edits the GUI or the JSON by hand. The CLI can
  start a run but cannot shape one. G4: `verify_export` exists in
  `export.py:123` and has no CLI surface. A user who receives an
  export package cannot check it from the terminal before
  importing it — the only check is to import and see what breaks.
  G5: no `--json`, `--quiet`, or `--verbose` flag exists on any
  command. The tab-separated list output is close to parseable but
  not a format, and there is no way to get a structured result for
  scripting — or to silence the per-step progress lines on a long
  run, or to ask for the traceback when one is actually needed
  (see T2).
- **Fix:** D15 — the big one, in priority order:
  `show-profile` / `show-project` / `status` / `checkpoints`
  first (seeing what a run will use is the prerequisite for
  everything else), then `rename`/`delete`/`update` for profiles
  and projects, then settings flags on `create-project` and a
  `set` command, then `verify` over the existing `verify_export`,
  then `--json`/`--quiet`/`--verbose` for scripting and for the
  traceback-on-demand in T2. (In the merged list, G1–G3 fold onto
  the existing CLI-parity task and G4 onto the existing verify
  task; only the `--json`/`--quiet`/`--verbose` output half is a
  new merged task.)
- **Done:** `show`/`status`/`checkpoints` report a project fully;
  rename/delete/update work for profiles and projects;
  `create-project` and update take settings flags; `stella verify`
  checks a package without importing it; `--json` prints valid
  JSON, `--quiet` suppresses progress, `--verbose` shows the
  traceback. Tests: each new command and flag, end to end.

### T17 — GUI parity for the CLI-only options

- **Covers:** A5-G6, A5-D16
- **Effort:** M
- **Problem:** Verified by reading the GUI: `--steps`, `--resume`,
  `--dataset`/`--base` overrides, `--quant`, and
  `--from-checkpoint` have no GUI equivalent. A window user cannot
  do a proof run, resume a paused run, pick a quant, or export
  from a checkpoint — the window's Train panel has Start/Pause/
  Resume buttons but no step cap, and its GGUF/probe actions take
  no options. The parity gap runs both directions (G1–G3 one way,
  this the other).
- **Fix:** D16 — add the CLI-only options to the window where they
  fit: a step cap and a resume action in the Train panel, a quant
  choice and a checkpoint picker on the GGUF action — or, if the
  window deliberately stays simple, document that these are
  CLI-only so a window user knows where to go.
- **Done:** A window user can set a step cap, resume a run, pick a
  quant, and export from a checkpoint — or the window says plainly
  where to go (the CLI) for each. Tests: GUI tests for each option
  or the documented pointer.

### T18 — Small polish: echo normalized names, friendly no-command hint

- **Covers:** A5-U3, A5-U9, A5-D18
- **Effort:** S
- **Problem:** `create-profile UPPER-Case` succeeds and stores
  `upper-case`, with no notice. The user asked for one name and
  got another; the next command that uses the name they typed
  (`stella projects UPPER-Case`) will fail to match it. The
  normalization is fine — the silence is not. And bare `stella`
  gives argparse's usage error (`the following arguments are
  required: command`). Standard argparse, but a first-time user
  gets an error instead of the command list. (The top `--help`
  lists all nine commands; the no-command path could show the
  same.)
- **Fix:** D18 — when a name is normalized, say so (`Created
  profile 'upper-case' (from 'UPPER-Case')`). When run with no
  subcommand, print the command list (the top `--help`) instead of
  argparse's usage error.
- **Done:** Creating with an uppercase name echoes the stored
  name; bare `stella` prints the command list and exits 0. Tests:
  normalization echo, no-command output.

---

## Coverage map

Every finding ID from audit #5, and the task(s) covering it.
Nothing dropped.

| Finding | Task(s) | Notes |
|---|---|---|
| A5-W1 — Ctrl+C pause crashes the run instead of pausing it | T1 | |
| A5-W2 — `main()` catches only StellaError; everything else is a raw traceback | T2 | Import instances ride the trust-boundary task; metamorph instance rides the shared reader |
| A5-W3 — `--steps` is not a cap: 0 means "no cap", -1 means "one epoch", 2 runs 3 steps | T3 | R11 — same finding |
| A5-W4 — re-training a trained project silently overwrites the adapter | T4 | |
| A5-W5 — the train deps gate fires before cheap checks, masking the real error | T5 | |
| A5-W6 — `export-gguf` checks llama.cpp AFTER the merge, and leaves the merged weights behind | T6 | R12 is the opposite direction |
| A5-W7 — `--quant` is never validated | T7 | |
| A5-W8 — `projects` on a nonexistent profile exits 0, like an empty real profile | T9 | |
| A5-W9 — one corrupt profile.json is silently skipped by `profiles` | T9 | A1-W1 re-verified on the CLI |
| A5-W10 — a bad import leaves an orphan profile behind | T9 | A3-W1 re-verified on the CLI |
| A5-W11 — no second-Ctrl+C force quit; Ctrl+C during the base download cannot interrupt it | T10 | |
| A5-W12 — a failed probe gate returns exit 1, the same as an error | T11 | |
| A5-W13 — `--resume` on a completed project silently extends the training | T4 | |
| A5-U1 — most flags have no help text, and no command shows examples | T8 | |
| A5-U2 — the docs disagree with the commands that exist | T8 | |
| A5-U3 — uppercase names are silently lowercased | T18 | |
| A5-U4 — library chatter pollutes stderr on every heavy run | T12 | |
| A5-U5 — a CLI error tells the user to use the GUI | T13 | |
| A5-U6 — a paused run's final summary reads like a completed run | T14 | |
| A5-U7 — resume prints a stale validation line for an epoch with no new steps | T14 | |
| A5-U8 — long operations print nothing on stdout until they finish | T14 | |
| A5-U9 — bare `stella` gives argparse's usage error, no friendly hint | T18 | |
| A5-G1 — no rename, delete, or update commands for profiles or projects | T16 | A1-W9/A2-W11 |
| A5-G2 — no way to inspect a profile or project from the CLI | T16 | |
| A5-G3 — no CLI way to set training settings | T16 | |
| A5-G4 — no `verify` command, though the function exists | T16 | A3-G5 |
| A5-G5 — no machine-readable or quiet output | T16 | |
| A5-G6 — the GUI lacks the CLI-only options (parity, the other way) | T17 | |
| A5-G7 — no test coverage for the risky CLI paths | T15 | |
| A5-D1 — the SIGINT handler sets the flag and nothing else | T1 | |
| A5-D2 — catch-all in `main()`, plus defensive reads in the list commands | T2 | |
| A5-D3 — validate `--steps` and say what it really does | T3 | |
| A5-D4 — refuse or confirm re-training and resume-on-trained | T4 | |
| A5-D5 — reorder the train checks: cheap first, deps gate last | T5 | |
| A5-D6 — check llama.cpp first in `export-gguf`; clean up on failure | T6 | |
| A5-D7 — validate `--quant` up front | T7 | |
| A5-D8 — existence checks, corrupt warnings, atomic import | T9 | |
| A5-D9 — second Ctrl+C force-quits; make the download interruptible | T10 | |
| A5-D10 — a distinct exit code for a failed probe gate | T11 | |
| A5-D11 — help text for every flag, examples in every command, fix the drift | T8 | |
| A5-D12 — silence the library warnings | T12 | |
| A5-D13 — CLI-appropriate error text | T13 | |
| A5-D14 — progress for long phases; honest paused/resumed output | T14 | |
| A5-D15 — the missing commands: rename/delete/update, show, settings, verify, --json | T16 | |
| A5-D16 — GUI parity for the CLI-only options | T17 | |
| A5-D17 — tests for the risky paths | T15 | |
| A5-D18 — small polish: echo normalized names, friendly no-command hint | T18 | |

**Coverage check:** 13 weaknesses + 9 UI flaws + 7 gaps + 18 design
suggestions = 47 findings. All 47 appear in the map above, each with
at least one task. 18 tasks total: 2 P0 (T1–T2), 6 P1 (T3–T8), 7 P2
(T9–T15), 3 P3 (T16–T18).

**Dependency order (within the priority order above):** T1 before
T10 (the graceful pause first, then the force-quit on top of it).
T1, T2, T3, T4, and T7 before T15 (the risky-path tests pin the
fixes). T2 before T16's `--verbose` (the flag exposes the traceback
the catch-all hides). T16's commands before T17 (the CLI commands
exist before the GUI mirrors them). T6 before T7 is not required —
the two GGUF fail-fast fixes are independent — but they touch the
same command, so landing them together is natural. Folded into the
merged list's shared tasks: T3 (`--steps` → the R11 task), T9's W9
(corrupt-profile warning → the damaged-rows task) and W10
(orphan-profile import → the trust-boundary import task), T2's
metamorph instance (CLI string-metamorph → the shared-reader
family), and T16's G1–G3 (missing commands → the CLI-parity task)
and G4 (verify → the verify task).
