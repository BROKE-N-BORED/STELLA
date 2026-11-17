# STELLA — Review task list, 2026-11-15

**From:** the full-product review of STELLA v0.24.0, 2026-11-15
(see `docs/review-2026-11-15.md` for the report).
**Status:** 129 tasks: 18 done, 105 to do, 6 hard-gated. 0 P0. 23 P1, 52 P2, 54 P3.
**How to read it:** each task has an ID (R1–R129), a priority, the area,
the source finding(s) from the nine audits, the evidence (file:line or
a measured probe), a one-line plain-words description, and what "done"
looks like. Priorities were earned by the evidence, not inflated:
P1 = important (a DONE claim that is false, a feature with no working
path, a safety net with a hole, a list that is wrong today), P2 =
correctness or polish, P3 = nice-to-have.

**Finding IDs:** A1 = training, A2 = GGUF/requant/distill, A3 =
profiles/projects, A4 = GUI, A5 = chat/providers, A6 = CLI, A7 =
installer/doctor, A8 = sleep/probe/docs, A9 = tests. Two findings were
split across two tasks and carry a suffix: A8-8R = the README half of
A8-8, A8-8H = the How to Use half, A8-19R = the README half of A8-19,
A8-19B = the behaviour half. M8 = the two "missing outright" items from
the chat audit (no freshness mechanism, no cost visibility). G2–G5 =
the four real-PC tails that are hard-gated on Joshua's machine.
A3-F6 was withdrawn after a probe disproved it; it is not a task (see
the report).

**Still gated, not in this list:** the 8 hard-gated tasks from the
closed 194-task list (T70, T72, T73, T128, T144, T182, T183, T188)
stay gated on Joshua's decisions. They are listed in the report, not
re-filed here.

---

## P1 — important (R1–R23)

### R1 — New Profile dialog picks the first model by itself; Enter creates a profile you never picked
- **Priority:** P1 · **Area:** GUI · **Sources:** A4-F1 · **Status:** DONE in 0.25.0
- **Evidence:** `stella/gui.py:413` sets `setCurrentRow(-1)` and
  `gui.py:574-575, 582-588` guards Enter with `picked_model()`, but
  after `show()` + `processEvents()` Qt selects row 0 on its own
  (probe2.out: currentRow -1 at construct, 0 after show). Probe3's
  ENTER-TEST pressed Return on a freshly shown dialog and a profile
  `lfm3-1-7b` was created for `lfm3:1.7b`, a model the user never
  picked. T18 is marked DONE in the closed list with the claim "Enter
  with no pick does nothing" — false in v0.24.0. Both T18 tests
  (`tests/test_gui.py:2670, 2710`) never show the dialog, so the suite
  stays green.
- **Problem:** the first-run creation flow makes a choice for the user
  and one stray Enter creates a thing. Breaks U6 (select nothing by
  default, ever) and the 5-year-old rule.
- **Fix:** clear the selection after show (e.g. in `showEvent`, or move
  initial focus off the list) and/or require an explicit user pick
  before `picked_model()` counts a row. Pin it with a test that shows
  the dialog first.
- **Done when:** a shown dialog has no row selected; pressing Enter
  with no pick creates nothing; the regression test shows the dialog.

### R2 — The trash has no way back: no Restore button, and the documented move-back is a trap
- **Priority:** P1 · **Area:** Profiles / GUI · **Sources:** A3-F1, A4-F6 · **Status:** DONE in 0.25.0
- **Evidence:** the Trash window offers only "Delete forever", "Empty
  trash", "Close" (`stella/gui.py:2447-2614`); `stella/model.py` has
  `list_trash` / `purge_trash` / `empty_trash` (`model.py:474-530`)
  and no restore function. T23 is marked DONE with the claim "restore
  or purge from the Trash window" — the purge half holds, the restore
  half does not. The help text says "move its folder back out of the
  trash" — but a dated trash folder moved back as-is is listed
  (manifest name) yet unopenable: probe P14 showed
  `get_profile('trashme')` raising `StellaError: no profile named
  'trashme'` because `get_profile` uses the folder name
  (`model.py:574, 596`).
- **Problem:** delete is a safety net with a hole in it; the only
  documented way back leaves a profile that shows up but won't open.
- **Fix:** add a Restore button (Trash window) and a `restore`
  function (model) that moves the folder back under its real name,
  with a name-clash rule; fix the help text.
- **Done when:** a trashed profile/project can be restored from the
  Trash window and opens afterwards; the trap is gone.

### R3 — Sleep adapters have no way into a model: the merge path the docs claim does not exist
- **Priority:** P1 · **Area:** Sleep / GGUF · **Sources:** A8-1 · **Status:** DONE in 0.25.0
- **Evidence:** GGUF export merges only the project adapter or a
  checkpoint (`stella/gguf.py:704-715`); zero "sleep" references in
  `gguf.py`. No `--from-sleep` or cycle picker exists anywhere. Yet
  `sleep.py`'s docstring, the README, and How to Use all claim sleep
  adapters merge "through the existing GGUF export path".
- **Problem:** the whole point of a sleep cycle — a lighter adapter
  that ends up in a model — has no path. The docs promise a feature
  that is not there.
- **Fix:** add a sleep-adapter source to the GGUF export path (cycle
  picker in the GUI, a CLI flag), or correct every claim to say it is
  not yet possible. The real merge on his PC is R20.
- **Done when:** a finished sleep cycle can be picked as the adapter
  source for a GGUF export, or the docs no longer claim it can.

### R4 — The refusal probe gate is never enforced: a tune can reach Ollama without ever passing it
- **Priority:** P1 · **Area:** Probe / governing seats · **Sources:** A8-2 · **Status:** DONE in 0.25.0
- **Evidence:** nothing auto-probes after training; export never
  consults probe results and proceeds with none
  (`stella/gui.py:9042-9048`); the T148 preview is a choice, not a
  block. A governing-seat tune can reach Ollama without ever passing
  the gate.
- **Problem:** the seat-safety rule (a fine-tune bound for a governing
  seat must pass a refusal probe) is a suggestion, not a gate.
- **Fix:** decide, then build or document: either enforce the probe
  before export for seat-bound profiles, or state plainly in the
  window and docs that the probe is opt-in and why.
- **Done when:** a seat-bound export either cannot proceed without a
  passed probe, or the opt-in nature is stated where the user sees it.

### R5 — Vision models silently lose their vision when requanted or exported
- **Priority:** P1 · **Area:** GGUF / requant · **Sources:** A2-F2 · **Status:** DONE in 0.25.0
- **Evidence:** zero `projector` / `mmproj` references anywhere in the
  tree. Requanting `qwen3-vl:2b-instruct` would register a text-only
  copy with no warning; export has no vision detection or refusal
  (the merge loads with `AutoModelForCausalLM`, which cannot load a
  VL model).
- **Problem:** a user requants a vision model and gets back a model
  that can no longer see, with no warning.
- **Fix:** detect vision weights (projector/mmproj tensors) on the
  requant and export paths; refuse with a plain-words message, or
  carry the vision parts through.
- **Done when:** requanting or exporting a vision model either keeps
  its vision or refuses with a message that says why.

### R6 — Reading a model's type loads the whole model file into RAM
- **Priority:** P1 · **Area:** Requant · **Sources:** A2-F1, A9-8 · **Status:** DONE in 0.25.0
- **Evidence:** `stella/requant.py:320` does `blob.read_bytes()[:4]`
  for a 4-byte magic check. Measured live: 1.05 GB peak RSS for the
  1.1 GB lfm3 blob. A 2.7 GB model would cost 2.7 GB of transient RAM
  on his 8 GB PC. No test pins the bounded read (test blobs are tiny).
- **Problem:** a 4-byte check costs the whole file in RAM — the
  heaviest thing in the room, on a PC where RAM is the hard ceiling.
- **Fix:** read the first 4 bytes with a bounded `read(4)`; add a test
  with a large sparse blob that pins the bound.
- **Done when:** the magic check reads 4 bytes, and a test with a
  large sparse blob proves it.

### R7 — One profile with bad characters in its notes breaks the whole profile list
- **Priority:** P1 · **Area:** Profiles · **Sources:** A3-F2 · **Status:** DONE in 0.25.0
- **Evidence:** invalid UTF-8 in a manifest or notes escapes the
  damaged-row handling as a raw `UnicodeDecodeError` (neither
  `JSONDecodeError` nor `OSError`), so the whole list fails instead of
  one damaged row (`stella/model.py:418, 574, 832, 1179`;
  `stella/export.py:1466, 1498`). Confirmed live by probes P5, P5b,
  P6, P7, P8: `list_profiles`, `get_profile`, `list_projects`,
  `read_notes`, verify, and check-export all raised.
- **Problem:** one bad file takes out the whole list; the user sees a
  crash instead of one damaged row.
- **Fix:** catch `UnicodeDecodeError` in the same damaged-row handling
  that already covers `JSONDecodeError` and `OSError`, in both
  `model.py` and `export.py`.
- **Done when:** a profile with invalid UTF-8 shows as one damaged row
  and the rest of the list still works.

### R8 — Healing an orphaned sleep report drops its hashes, so rows get re-slept and the next check is empty
- **Priority:** P1 · **Area:** Sleep · **Sources:** A8-3 · **Status:** DONE in 0.25.0
- **Evidence:** proven in a scratch probe: the healed cycle reappears
  in the list but `slept_hashes` / `dreamed_hashes` / `old_val_rows`
  stay empty, so rows get re-slept and the next replay check is
  vacuous (empty old val → loss None → OK).
- **Problem:** the heal looks like it worked but silently throws away
  the record of what was already slept.
- **Fix:** make the orphan-report heal rebuild or carry the hash sets
  (or refuse to heal when they cannot be rebuilt, saying so).
- **Done when:** a healed cycle keeps its slept/dreamed hashes and the
  replay check still has something to check against.

### R9 — The doctor writes a launcher with a literal "path" as its icon, and the error is sticky
- **Priority:** P1 · **Area:** Doctor · **Sources:** A7-F1 · **Status:** DONE in 0.25.0
- **Evidence:** proved live, twice: `stella/doctor.py:154` passes the
  mode word where `stella/install.py:66-79` expects the icon value, so
  the doctor writes a launcher with a literal `Icon=path` when
  hicolor icons are absent. It is sticky: the currency check
  (`doctor.py:143-151`) only looks at `Exec=`, so a second run reports
  `OK launcher` / `OK icon` with `Icon=path` still in the file.
- **Problem:** the repair tool writes a broken launcher and then
  reports the broken launcher as fine.
- **Fix:** pass the icon value, not the mode word; make the currency
  check look at `Icon=` too.
- **Done when:** the doctor writes a real icon value and a second run
  no longer calls a `Icon=path` launcher OK.

### R10 — The doctor tells the user to install the wrong package for missing libxcb libraries
- **Priority:** P1 · **Area:** Doctor · **Sources:** A7-F2 · **Status:** DONE in 0.25.0
- **Evidence:** proved via direct `_missing_library` calls: the generic
  `("libxcb", "libxcb1")` substring fallback (`stella/doctor.py:76`)
  catches `libxcb-render` / `shm` / `shape` / `randr` / `xfixes` /
  `sync.so` and misdiagnoses them all as libxcb1. The correct
  packages are `libxcb-render0` etc. (verified as real Ubuntu noble
  package names).
- **Problem:** the user follows the doctor's fix, installs the wrong
  package, and the app still won't start.
- **Fix:** match `"libxcb.so"` exactly instead of the substring
  `"libxcb"`, and map the other libxcb-* libraries to their real
  packages.
- **Done when:** each missing libxcb-* library names its own real
  package.

### R11 — The Groq model list is stale: the default model errors for ordinary accounts
- **Priority:** P1 · **Area:** Providers · **Sources:** A5-F1 · **Status:** DONE in 0.25.0
- **Evidence:** `stella/providers.py:56-58` lists `llama-3.3-70b-versatile`
  (first, so the default), `llama-3.1-8b-instant`, and
  `openai/gpt-oss-120b`. Confirmed via Groq's own deprecations page
  (checked 2026-11-15): both Llama models moved to Enterprise-only on
  2026-08-16. Self-serve now offers `openai/gpt-oss-20b` and
  `openai/gpt-oss-120b` — the 20b model is not listed at all. Only one
  of the three listed models still works for a self-serve key.
- **Problem:** the first model the user is offered errors on an
  ordinary Groq account.
- **Fix:** update the list to the current self-serve models
  (`openai/gpt-oss-120b`, `openai/gpt-oss-20b`) and pick a working
  default. (The lasting fix is R51.)
- **Done when:** every Groq model listed works with a self-serve key,
  starting with the default.

### R12 — The Gemini model list is stale: all three listed models fail for a new user
- **Priority:** P1 · **Area:** Providers · **Sources:** A5-F2 · **Status:** DONE in 0.25.0
- **Evidence:** `stella/providers.py:69-71` lists `gemini-2.0-flash`,
  `gemini-2.5-flash`, `gemini-2.5-pro`. Confirmed via web sources
  (checked 2026-11-15): `gemini-2.0-flash` shut down 2026-06-01; the
  2.5 models return 404 "no longer available to new users" for new
  keys/projects since 2026-09-18 and are deprecated, existing-users-only,
  auto-routed from Dec 1, 2026. For Joshua, who has never made a
  Gemini call from Stella, all three fail. Replacements per the 404
  messages: `gemini-3.8-flash` and `gemini-3.5-flash-lite`.
- **Problem:** every Gemini model offered fails for a new user.
- **Fix:** update the list to models that work for a new key
  (`gemini-3.8-flash`, `gemini-3.5-flash-lite`), with care: some newer
  models (e.g. `gemini-3.1-pro-preview`) have zero free-tier quota.
  (The lasting fix is R51.)
- **Done when:** every Gemini model listed works with a new key.

### R13 — There is no click-only way to install training: the core purpose still needs a terminal
- **Priority:** P1 · **Area:** Installer · **Sources:** A7-F3 · **Status:** DONE in 0.25.0
- **Evidence:** no `.desktop` file, no GUI button. Every surface says
  `bash install-training.sh`: `stella/gui.py:6353`, `stella/cli.py:374`,
  `stella/train.py:54`, `stella/howto.py:36, 315`,
  `stella/provision.py:259`. Fails the immutable click-only rule: he
  never uses the terminal.
- **Problem:** the thing Stella is for — training — cannot be set up
  without typing a command.
- **Fix:** add a click-only training install (a desktop launcher and/or
  a GUI button that runs the install with progress), keeping the
  terminal path for those who want it.
- **Done when:** training can be installed by clicking, with progress
  shown, no terminal needed.

### R14 — Chat on the command line goes silent for the whole run: no narration, no progress
- **Priority:** P1 · **Area:** CLI / chat · **Sources:** A5-F3 · **Status:** DONE in 0.25.0
- **Evidence:** `stella/cli.py:1494` builds the agent with no
  callbacks, so every narration/progress callback is swallowed;
  verified live. During a hours-long training run the user sees
  nothing until it ends.
- **Problem:** the one place a long job's progress should be visible
  shows nothing at all.
- **Fix:** wire the agent's narration/progress callbacks through to
  the CLI chat output.
- **Done when:** CLI chat shows the same plan and progress narration
  the GUI chat shows, as the run goes.

### R15 — `sleep` with no dataset tells the user to pick one "in the Train panel"
- **Priority:** P1 · **Area:** CLI / sleep · **Sources:** A6-W1 · **Status:** DONE in 0.25.0
- **Evidence:** `stella/sleep.py:596-597` prints "Pick a .jsonl dataset
  in the Train panel, or pass --rows". The A5-U5 defect T111 missed,
  because its guard test greps only `cli.py`. Also a truncated tail.
- **Problem:** a command-line user is sent to a GUI panel that is not
  in front of them.
- **Fix:** name the CLI way (pass `--dataset` / `--rows`) and fix the
  truncated tail; widen the T111 guard test to cover `sleep.py`.
- **Done when:** the message tells a CLI user what to type, and the
  guard test covers `sleep.py`.

### R16 — Four tests fail on a plain install without the training stack, so CI's base job would go red
- **Priority:** P1 · **Area:** Tests · **Sources:** A9-1 · **Status:** DONE in 0.25.0
- **Evidence:** `tests/test_train.py:1411, 1440, 1460` call
  `monkeypatch.setattr("huggingface_hub.HfApi")` with no skip gate
  (→ `ModuleNotFoundError` without the package); `:1481` asserts 2e9
  but gets `None` because `_fetch_hf_file_size`'s `hf_hub_url` import
  fails. Masked because the test VM happens to have
  `huggingface_hub`; `install.sh` installs PySide6 only, CI base
  installs base requirements only. Contradicts run_tests.sh's "a base
  install still goes green".
- **Problem:** the suite is red on exactly the install most users have.
- **Fix:** gate those tests on `huggingface_hub` being present (or
  make them not need it), so a base-only install goes green.
- **Done when:** the suite passes on a base-only install with no
  `huggingface_hub`, and CI's base job is green.

### R17 — The Ollama-down settings test is genuinely fragile: a background refresh can overwrite its seed
- **Priority:** P1 · **Area:** Tests · **Sources:** A9-2 · **Status:** DONE in 0.25.0
- **Evidence:** `test_settings_status_says_when_ollama_down` seeds
  "down" via raw `set_snapshot` without `seed_models`, but
  `SettingsWindow.__init__` (`stella/gui.py:2760`) starts a live
  `ModelListWorker` refresh after the seed; the ticket guard only
  blocks earlier refreshes. A probe proved refresh-after-seed
  overwrites the seed.
- **Problem:** a load flake with a proven mechanism — the test can fail
  for no product reason.
- **Fix:** seed with `seed_models([], ollama_up=False)`, as the
  neighbouring test does.
- **Done when:** the test seeds through `seed_models` and no longer
  depends on refresh timing.

### R18 — The button-press test is genuinely fragile: under load it misses the dip entirely
- **Priority:** P1 · **Area:** Tests · **Sources:** A9-3 · **Status:** DONE in 0.25.0
- **Evidence:** `test_press_dip_shrinks_then_restores`, reproduced: a
  150 ms animation, a 2 px dip, 20 ms sampling; clean runs always
  sampled min=119 (never 118 — 1 px real margin); under CPU load 5/10
  probe runs sampled only `[120, 120]`. More likely on Joshua's 2-core
  Ryzen 3 than on the VM.
- **Problem:** a load flake with a proven mechanism — the test can fail
  for no product reason, and more so on his PC.
- **Fix:** sample finer, or assert on the animation's key values plus
  the restore.
- **Done when:** the test passes reliably under CPU load.

## P1 — hard-gated on Joshua's PC (R19–R23)

These cannot be closed on the VM. They are P1 because each one is the
only proof of a claim the product already makes.

### R19 — [HARD-GATED] Run the LFM3 proof run end to end on his PC
- **Priority:** P1 · **Area:** Training · **Sources:** A1-F1 · **Status:** HARD-GATED (needs Joshua's PC)
- **Evidence:** the v0.24.0 RAM recalibration rests on ONE 0.5B probe
  run, never measured at LFM3 1.7B scale or on his PC. If the true
  resident share at 1.7B is 0.8 not 0.5, the true total is ~1 GB over
  the 4.34 GB estimate. No probe artifact exists in the repo.
- **Problem:** the headline "fits" claim for the starter model is
  unproven at the starter model's size, on the machine it must fit on.
- **Fix:** run the LFM3 rank 8 / seq 1024 proof run on his PC and
  record the measured peak RAM; adjust the estimate if it disagrees.
- **Done when:** a measured peak-RAM number for LFM3 1.7B on his PC
  exists, and the estimate matches it.

### R20 — [HARD-GATED] Merge a sleep adapter for real with llama.cpp
- **Priority:** P1 · **Area:** Sleep / GGUF · **Sources:** G2 · **Status:** HARD-GATED (needs Joshua's PC)
- **Evidence:** the merge path does not exist yet (R3); no sleep
  adapter has ever been merged by llama.cpp in a real run.
- **Problem:** the sleep feature's payoff has never been shown to work
  end to end.
- **Fix:** after R3, merge a real sleep adapter with llama.cpp on his
  PC and confirm the merged model loads.
- **Done when:** a sleep adapter has been merged and the merged model
  loads. Depends on R3.

### R21 — [HARD-GATED] Create a model in Ollama from a real Stella export
- **Priority:** P1 · **Area:** GGUF · **Sources:** G3 · **Status:** HARD-GATED (needs Joshua's PC)
- **Evidence:** no real `ollama create` from a Stella export has ever
  run; the code itself flags the quoted FROM line as unprobed.
- **Problem:** the export's final step — the model actually appearing
  in Ollama — has never been shown to work.
- **Fix:** run a real `ollama create` from a Stella export on his PC,
  including the quoted FROM line, and confirm the model runs.
- **Done when:** a Stella export has been created in Ollama and answers.

### R22 — [HARD-GATED] Double-click Install Stella.desktop for real on Mint
- **Priority:** P1 · **Area:** Installer · **Sources:** G4 · **Status:** HARD-GATED (needs Joshua's PC)
- **Evidence:** the double-click path has only ever been probed via
  `gio launch` and direct libgio calls; `gio launch` passed `%k`
  empty where direct libgio passed the correct path, so it is not a
  faithful double-click simulator. A literal Nemo double-click has
  never happened.
- **Problem:** the installer's whole promise — double-click and it
  installs — has never been tested the way he will do it.
- **Fix:** double-click Install Stella.desktop in Nemo on Mint and
  confirm the install runs.
- **Done when:** a literal double-click on Mint has installed Stella.

### R23 — [HARD-GATED] Run the real 2 GB training install on his PC
- **Priority:** P1 · **Area:** Installer · **Sources:** G5 · **Status:** HARD-GATED (needs Joshua's PC)
- **Evidence:** no real training install has ever run on his PC; time,
  peak disk, and peak RAM are all unmeasured (see also R61: the 3 GB
  preflight understates the ~4 GB+ peak).
- **Problem:** the install's size and time are guesses on the machine
  it matters for.
- **Fix:** run the training install on his PC and record time, peak
  disk, and peak RAM.
- **Done when:** measured time, peak disk, and peak RAM for the
  training install on his PC exist.

---

## P2 — correctness / polish (R24–R75)

### R24 — The dry-run "fits" answer ignores the dataset's RAM
- **Priority:** P2 · **Area:** Training · **Sources:** A1-F2 · **Status:** not started
- **Evidence:** proven live: `estimate_run` said fits=True while
  `check_dataset_fit` refused — a 5,000-row dataset with 4.54 GB free
  (`stella/train.py:1228` vs `:2653`).
- **Problem:** the estimate says a run fits when the dataset check
  says it does not; the user is told two things at once.
- **Fix:** make the dry-run/estimate `fits` answer include dataset
  RAM, the same way the run-time check does.
- **Done when:** estimate and the dataset check agree on the same
  dataset and free RAM.

### R25 — Offline, a single-file model link is refused even though the weights are already cached
- **Priority:** P2 · **Area:** Training · **Sources:** A1-F3 · **Status:** not started
- **Evidence:** proven live: offline + single-file Hub ref refused
  despite cached weights (`stella/train.py:947-1011`); the error at
  `:997` names no next step. Cache helpers exist
  (`stella/provision.py:37-53`). Same root: the estimate label does
  UI-thread network I/O for LFM3 and shows "unavailable" offline.
- **Problem:** the weights are on the disk, but Stella says the model
  is unavailable because it cannot reach the network.
- **Fix:** check the cache before refusing; say what to do next when a
  ref genuinely cannot be resolved.
- **Done when:** a cached model works offline, and an uncached one
  gets a message with a next step.

### R26 — Resuming after editing the dataset silently trains the wrong rows
- **Priority:** P2 · **Area:** Training · **Sources:** A1-F4 · **Status:** not started
- **Evidence:** proven live: no dataset fingerprint in checkpoint state
  (`stella/train.py:2314-2321`); a probe showed 3/5 skip overlap after
  adding 2 rows and deleting 1.
- **Problem:** the user edits the dataset, resumes, and trains on the
  wrong rows without being told.
- **Fix:** fingerprint the dataset in checkpoint state and refuse (or
  warn and restart the epoch) when it has changed.
- **Done when:** resuming after a dataset edit is refused or warned
  about, never silent.

### R27 — A hard crash leaves a run showing as "training" forever
- **Priority:** P2 · **Area:** Training · **Sources:** A1-F5 · **Status:** not started
- **Evidence:** proven live: status `"training"` is set at
  `stella/train.py:2831` and only cleared on a propagated exception
  (`:2865`); there is no reconciliation anywhere. The project list
  shows the dead run as live (`stella/gui.py:2322`). No crash notice,
  no resume offer.
- **Problem:** a dead run looks live, and the user is never told it
  crashed.
- **Fix:** reconcile stale `"training"` statuses on start-up (or on
  list), mark the run as crashed, and offer resume where checkpoints
  exist.
- **Done when:** a crashed run shows as crashed, not training, with a
  resume offer when it can be resumed.

### R28 — `method: full` can still be set from the command line, and silently trains LoRA instead
- **Priority:** P2 · **Area:** Training / CLI · **Sources:** A1-F6, A6-W3 · **Status:** not started
- **Evidence:** `--method` still offers `full`
  (`stella/cli.py:805, 2002, 2092`); `validate_settings` accepts it;
  zero readers — the run silently trains LoRA. `show-project` displays
  `method: full` with no warning. T189 mooted only the GUI side.
- **Problem:** the user asks for full fine-tuning and gets LoRA
  without being told.
- **Fix:** remove `full` from `--method` (or refuse it with a
  plain-words message); warn on `show-project` for existing `full`
  settings.
- **Done when:** no CLI path can set `method: full` and silently run
  LoRA.

### R29 — The GGUF parser picks the quant by tensor count, and a near-tie could pick the wrong one
- **Priority:** P2 · **Area:** GGUF · **Sources:** A2-F3 · **Status:** not started
- **Evidence:** the real file is 136 Q5_K tensors vs 133 F32 — a
  near-tie. If F32 won, the double-quant warning would not fire and
  the disk estimate would collapse.
- **Problem:** the quant call rests on a count that is nearly tied,
  not on how much of the file each quant actually is.
- **Fix:** pick the quant by byte-weighted bits-per-weight.
- **Done when:** the parser's quant call follows the bytes, not the
  count, on the real lfm3 blob and on a tied file.

### R30 — A distill timeout or failure aborts the whole run, and the message misleads
- **Priority:** P2 · **Area:** Distill · **Sources:** A2-F4 · **Status:** not started
- **Evidence:** probed with a fake teacher: a timeout/failure aborts
  the whole run — no retry, skip, or report. Answers ARE saved and
  re-runs resume, but the abort message does not say so (unlike
  Cancel), and it misleads: "Is Ollama running on this PC? (timed
  out)".
- **Problem:** one bad prompt kills hours of work, and the message
  points at the wrong cause.
- **Fix:** retry or skip a failed prompt and report it at the end;
  say plainly that saved answers are kept and a re-run resumes.
- **Done when:** a failed prompt does not abort the run, and the
  message names the real cause and the resume behaviour.

### R31 — Export has no disk guard at all, and its estimate leaves out the F16 intermediate
- **Priority:** P2 · **Area:** GGUF · **Sources:** A2-F5 · **Status:** not started
- **Evidence:** export has NO disk guard; its estimate omits the F16
  intermediate (peak ~7.9 GB vs ~4.5 GB stated for LFM3).
- **Problem:** an export can run out of disk halfway, and the estimate
  understates the peak by ~3.4 GB.
- **Fix:** add a free-disk pre-check to export and include the F16
  intermediate in the estimate.
- **Done when:** export refuses (with a plain-words message) when the
  disk cannot hold the peak, and the estimate matches the measured
  peak.

### R32 — The requant disk estimate leaves out Ollama's blob copy
- **Priority:** P2 · **Area:** Requant · **Sources:** A2-F6 · **Status:** not started
- **Evidence:** the requant disk estimate omits Ollama's blob copy
  (peak ≈ 2× the output).
- **Problem:** the estimate understates the peak by about half.
- **Fix:** include Ollama's blob copy in the requant disk estimate.
- **Done when:** the requant estimate matches the measured peak disk
  use.

### R33 — Cleanup only runs on Stella's own errors; Ctrl+C or a disk error leaves partial files behind
- **Priority:** P2 · **Area:** GGUF / requant · **Sources:** A2-F7 · **Status:** not started
- **Evidence:** code-verified: cleanup only on `StellaError` — Ctrl+C
  / `OSError` leave a partial GGUF, F16, or merged dir behind. T26's
  DONE claim covers `StellaError` only. (A live probe was blocked by
  a sandbox write restriction.)
- **Problem:** an interrupted export or requant leaves litter the user
  has to find and delete by hand.
- **Fix:** run the cleanup on `KeyboardInterrupt` and `OSError` too.
- **Done when:** interrupting an export or requant leaves no partial
  files behind.

### R34 — The requant subprocess has no timeout
- **Priority:** P2 · **Area:** Requant · **Sources:** A2-F8 · **Status:** not started
- **Evidence:** requant's subprocess has no timeout; export has 30
  minutes.
- **Problem:** a hung requant runs forever with no way out.
- **Fix:** give the requant subprocess a timeout like export's, with a
  plain-words message when it fires.
- **Done when:** a hung requant stops on a timeout and says so.

### R35 — Teacher answers are silently cut off at 1024 tokens
- **Priority:** P2 · **Area:** Distill · **Sources:** A2-F9 · **Status:** not started
- **Evidence:** teacher answers are silently truncated at 1024 tokens;
  no `done_reason` check.
- **Problem:** the student learns from answers that were cut off
  mid-sentence, with no warning.
- **Fix:** check `done_reason` and either raise the cap, re-ask, or
  mark the answer as truncated.
- **Done when:** a truncated teacher answer is never silently kept as
  a full answer.

### R36 — Importing a recipe from a finished project warns misleadingly and demotes the project
- **Priority:** P2 · **Area:** Profiles · **Sources:** A3-F3 · **Status:** not started
- **Evidence:** confirmed live (probe P10): recipe import from a
  finished project warns "Train it first, then export again" and
  demotes the status; recipes never carry weights by design
  (`stella/export.py:2215, 994`).
- **Problem:** the warning tells the user to do something that cannot
  fix it, and the finished project loses its status.
- **Fix:** say plainly that a recipe has no weights (by design) and
  stop demoting the project.
- **Done when:** importing a recipe from a finished project warns
  truthfully and keeps the project's status.

### R37 — The model layer does not type-check what it is given, so bad values land in the store
- **Priority:** P2 · **Area:** Profiles · **Sources:** A3-F4 · **Status:** not started
- **Evidence:** confirmed live (probe P12): `create_profile(config="abc")`
  raises a raw `ValueError`; `dependencies="torch"` shreds to
  `['t','o','r','c','h']`; `update_profile(config=str)` stores the
  string verbatim (`stella/model.py:605, 671`). Import validates; the
  model does not.
- **Problem:** a wrong type either crashes with raw Python text or
  lands in the store as garbage.
- **Fix:** type-check `config`, `dependencies`, and the other write
  paths in the model layer, with plain-words errors.
- **Done when:** bad types are refused with a plain-words message at
  the model layer, not stored or crashed on.

### R38 — Export does not check what it writes, so Stella exports packages its own verify refuses
- **Priority:** P2 · **Area:** Profiles · **Sources:** A3-F5 · **Status:** not started
- **Evidence:** confirmed live (probe P11): export of a project with a
  hand-edited status `"banana"` SUCCEEDED, while Stella's own verify
  refuses it with "export has unknown project status: 'banana'"
  (`stella/export.py:541, 731`).
- **Problem:** Stella can make a package it cannot open again.
- **Fix:** validate the package against the same rules verify uses,
  before writing it.
- **Done when:** export refuses a package its own verify would refuse.

### R39 — Import has no size or disk guard: no zip-bomb cap, no free-space check
- **Priority:** P2 · **Area:** Profiles · **Sources:** A3-F7 · **Status:** not started
- **Evidence:** confirmed live (probe P3): a 66,372-byte zip extracted
  to 67,108,864 bytes with no cap hit. No free-space pre-check
  (export has one). `stella/export.py:247`.
- **Problem:** a small malicious package can fill the disk on import.
- **Fix:** cap the total extracted size and check free space before
  extracting.
- **Done when:** an oversized package is refused before it extracts,
  and import checks free space first.

### R40 — Cloning a profile silently drops its damaged projects, then reports success
- **Priority:** P2 · **Area:** Profiles · **Sources:** A3-F8 · **Status:** not started
- **Evidence:** code read: profile clone with projects silently drops
  damaged projects, then reports success (`stella/model.py:780`).
- **Problem:** the clone looks complete but is missing projects, with
  no mention of them.
- **Fix:** report the dropped projects (and why) in the clone result,
  or refuse the clone when a project is damaged.
- **Done when:** cloning a profile with a damaged project says so
  instead of silently dropping it.

### R41 — The status bar says "Pick a profile to begin." while a session is live
- **Priority:** P2 · **Area:** GUI · **Sources:** A4-F2 · **Status:** not started
- **Evidence:** every seeded screenshot shows the status bar reading
  "Pick a profile to begin." Cause: T191 removed the session repeat
  ("The status bar keeps whatever the last action said",
  `stella/gui.py:5557-5560`), but the `has_session` branch of
  `refresh_session` never calls `_say`, and `set_session` does not
  either — so the message set by the no-session branch at start-up
  (`gui.py:5578`) survives the session being set.
- **Problem:** the one status surface says something false until some
  later action overwrites it.
- **Fix:** say something true when a session is set (e.g. "Ready." or
  the session in display names) without reintroducing the slug repeat
  T191 removed.
- **Done when:** with a live session, the status bar never reads
  "Pick a profile to begin."

### R42 — The Settings Ollama status text overlaps the Refresh button when the window opens
- **Priority:** P2 · **Area:** GUI · **Sources:** A4-F3 · **Status:** not started
- **Evidence:** with Ollama up and several models, the status label's
  second line is struck through by the "Refresh Ollama status" button
  at open (screenshots `a4-settings-window.png`,
  `a4-settings-5model-t0b.png`). The label is 17 px tall when the long
  text lands and grows to 34 px (probe5b.out); the layout reflows and
  it self-heals within ~2 s.
- **Problem:** visible text corruption on a settings screen, every time
  Ollama reports a multi-model list.
- **Fix:** give the label word wrap plus a layout activation when its
  text lands (or reserve the wrapped height up front).
- **Done when:** opening Settings with a multi-model Ollama list shows
  no overlap at any moment.

### R43 — The fit verdict calls every model "Too big for this PC", including the recommended starter
- **Priority:** P2 · **Area:** GUI · **Sources:** A4-F5 · **Status:** not started
- **Evidence:** in the New Profile dialog every row reads "Too big for
  this PC.", including `lfm3:1.7b`, whose own description in the same
  row says "A good first pick." The details line gives the reason:
  "Needs about 6.4 GB of RAM to train, and this PC has 1.6 GB free."
  The verdict compares estimated training RAM
  (`stella/model_info.py:90-93`) against currently free RAM measured
  once at dialog construct (`stella/gui.py:405-407`,
  `model_info.py:96-104`), never re-measured on Refresh. Measured on
  the VM (1.6 GB free); on his 8 GB PC free RAM can easily sit below
  6.4 GB with Mint and a browser open — not verified on his PC.
- **Problem:** a transient measurement is stated as a permanent
  property of the PC, and it contradicts the row's own recommendation
  in the same breath.
- **Fix:** judge the verdict against a stable measure (total RAM, or
  free RAM with the machine's usual load stated), or soften the row
  verdict to match the details line; resolve the "good first pick /
  too big" contradiction in the row copy.
- **Done when:** the starter model does not read "Too big" alongside
  "A good first pick", and the verdict is re-measured or honestly
  worded.

### R44 — The run-button row is clipped at the bottom edge at 1366x768
- **Priority:** P2 · **Area:** GUI · **Sources:** A4-F7 · **Status:** not started
- **Evidence:** at 1366x768 the Pause / Resume / Proof run / Estimate
  row sits at y=646 with height 31 against a session viewport of
  666 px: the bottom 11 px are below the fold (probe6.out; visible
  half-height in `a4-main-seeded-1366.png`). During a run, Pause
  needs a scroll to use in full. His real PC has a taskbar, so usable
  height is a little less — this is, if anything, understated.
- **Problem:** the control the user reaches for mid-run is half
  hidden at his screen size.
- **Fix:** shorten the glanceable card or move the run-button row above
  the progress bar so the whole row fits in 666 px.
- **Done when:** the full run-button row is visible at 1366x768 with
  no scroll.

### R45 — A typed cloud-model pick is dropped when Ollama is down
- **Priority:** P2 · **Area:** Chat · **Sources:** A5-F4 · **Status:** not started
- **Evidence:** proven live with a Qt probe: when Ollama is down, the
  no-models branch never sets `_awaiting_model`
  (`stella/gui.py:3246-3252, 3357-3360`), so typed messages are
  discarded and `chat_model` stays `''`.
- **Problem:** the user types a cloud model name and it is silently
  thrown away because Ollama is down — even though the cloud model
  does not need Ollama.
- **Fix:** set `_awaiting_model` on the no-models branch too, so a
  typed cloud pick is kept.
- **Done when:** typing a cloud model name with Ollama down keeps the
  pick.

### R46 — Chat history is never shortened: the full history is re-sent (and re-paid for) every turn
- **Priority:** P2 · **Area:** Chat · **Sources:** A5-F5 · **Status:** not started
- **Evidence:** history is never truncated
  (`stella/chat_agent.py:360, 428-434`): the full history is resent
  every turn; 10 entries after 5 turns. On cloud models that is paid
  for every time.
- **Problem:** long chats get slower and, on cloud models, cost more
  with every turn.
- **Fix:** cap the history sent to the model (e.g. keep the last N
  turns, or summarise), keeping the full history in the window.
- **Done when:** a long chat sends a bounded history to the model.

### R47 — A second tool block's raw JSON leaks into the chat, and the call never runs
- **Priority:** P2 · **Area:** Chat · **Sources:** A5-F6 · **Status:** not started
- **Evidence:** the second ```tool block's raw JSON leaks into the chat
  (`stella/chat_agent.py:233-258`); the second call is silently never
  executed.
- **Problem:** the user sees raw JSON in the chat and the second thing
  they asked for never happens.
- **Fix:** run (or explicitly refuse) every tool block in a reply, and
  never show raw tool JSON in the chat.
- **Done when:** a reply with two tool blocks runs both (or says why
  it cannot) and shows no raw JSON.

### R48 — Tool JSON in a ```json fence, or unclosed, is shown as raw text and never runs
- **Priority:** P2 · **Area:** Chat · **Sources:** A5-F7 · **Status:** not started
- **Evidence:** ```json-fenced or unclosed tool JSON is shown as raw
  text, never executed (`stella/chat_agent.py:127`).
- **Problem:** the model asked to do a thing, the user sees code, and
  nothing happens.
- **Fix:** parse ```json-fenced tool JSON and tolerate an unclosed
  fence where the JSON is otherwise complete.
- **Done when:** a ```json-fenced tool call runs, and an unclosed fence
  with complete JSON runs or gets a plain-words note.

### R49 — The template walk is prompt-only: the agent never tracks which step it is on
- **Priority:** P2 · **Area:** Chat · **Sources:** A5-F8 · **Status:** not started
- **Evidence:** the template walk is prompt-only, with no agent-side
  step tracking (`stella/chat_agent.py:106-124`).
- **Problem:** the agent can lose its place in a multi-step template
  and the user cannot see where it is.
- **Fix:** track the template step in the agent and show it.
- **Done when:** the agent knows and shows which template step it is
  on.

### R50 — Every model call re-fetches the Ollama model list, up to 12 tag fetches per loop
- **Priority:** P2 · **Area:** Chat · **Sources:** A5-F9 · **Status:** not started
- **Evidence:** every model call re-fetches the Ollama model list
  (`stella/chat_agent.py:428-434`); up to 12 tag fetches per capped
  loop.
- **Problem:** wasted work on every turn — 12 list fetches where one
  would do.
- **Fix:** fetch the model list once per loop (or cache it for the
  turn) and reuse it.
- **Done when:** one agent loop makes one model-list fetch.

### R51 — The curated model lists have no freshness mechanism: they rotted silently
- **Priority:** P2 · **Area:** Providers · **Sources:** M8-FRESHNESS · **Status:** not started
- **Evidence:** the Groq and Gemini lists (R11, R12) went stale with
  nothing to notice: no freshness check, no expiry, no warning. The
  lists are curated in code (`stella/providers.py`) and only a human
  reading Groq's and Google's pages would have caught it.
- **Problem:** the next deprecation will rot the lists again, silently.
- **Fix:** add a freshness mechanism that fits the offline-first,
  hard-$0 shape (e.g. a dated list with a staleness warning, or a
  check against the provider's model endpoint when online) — do not
  add a background network call without his say-so.
- **Done when:** a stale model list is noticed by the product, not
  only by a user hitting an error.

### R52 — `--json` is silently ignored on about 25 commands
- **Priority:** P2 · **Area:** CLI · **Sources:** A6-W2 · **Status:** not started
- **Evidence:** `--json` silently ignored on ~25 commands (`pc-info`,
  `bridge`, `doctor`, `export`, `train` probed) — plain text with
  exit code 0.
- **Problem:** scripts asking for JSON get plain text and a success
  code, so they fail downstream with no clue.
- **Fix:** honour `--json` on the commands that take it, or refuse the
  flag with a plain-words message on the ones that cannot.
- **Done when:** no command accepts `--json` and silently returns text.

### R53 — Export commands print "Package size: about 0 bytes." before failing on a missing profile
- **Priority:** P2 · **Area:** CLI · **Sources:** A6-W4 · **Status:** not started
- **Evidence:** all four export commands print "Package size: about 0
  bytes." before failing on a missing profile/project.
- **Problem:** a nonsense line ("0 bytes") appears before the real
  error, and looks like the answer.
- **Fix:** check the profile/project exists before printing the size
  line.
- **Done when:** a failed export prints only the error, no "0 bytes"
  line.

### R54 — Chat's pre-flight failures print to stdout, and there is no CLI way to save a provider key
- **Priority:** P2 · **Area:** CLI / chat · **Sources:** A6-W5 · **Status:** not started
- **Evidence:** `chat`'s four pre-flight failures print to stdout, not
  stderr (`stella/cli.py:1463-1495`); there is no CLI way to save a
  provider key, so cloud `chat` is terminal-unusable.
- **Problem:** errors go to the wrong stream, and a CLI-only user
  cannot set up cloud chat at all.
- **Fix:** print the pre-flight failures to stderr; add a CLI command
  to save a provider key (stored the same secure way the GUI stores
  it).
- **Done when:** chat errors go to stderr and a provider key can be
  saved from the CLI.

### R55 — There is no CLI for cloning a profile or a project, though the engine and GUI both have it
- **Priority:** P2 · **Area:** CLI · **Sources:** A6-W6 · **Status:** not started
- **Evidence:** no `clone-profile` / `clone-project` commands, though
  the engine and GUI both offer clone.
- **Problem:** a CLI-only user cannot do something the product can do.
- **Fix:** add `clone-profile` and `clone-project` commands.
- **Done when:** both clones work from the CLI.

### R56 — The nameless-profile warning says the row shows "(unnamed profile)" when it shows the display name
- **Priority:** P2 · **Area:** CLI · **Sources:** A6-W7 · **Status:** not started
- **Evidence:** the nameless-profile warning says "shown as (unnamed
  profile)" while the row shows the display name.
- **Problem:** the warning describes a screen the user is not looking
  at.
- **Fix:** make the warning match what the row actually shows.
- **Done when:** the warning names what the user sees.

### R57 — The installer's Qt-failure advice never names the package to install
- **Priority:** P2 · **Area:** Installer · **Sources:** A7-F4 · **Status:** not started
- **Evidence:** `install.sh:115-124` Qt-failure advice never names the
  apt package, while the doctor knows it.
- **Problem:** the user is told something is missing but not what to
  install.
- **Fix:** name the package in the install.sh advice, the way the
  doctor does.
- **Done when:** a Qt failure names the package to install.

### R58 — The doctor repairs launch files for a folder whose venv is broken
- **Priority:** P2 · **Area:** Doctor · **Sources:** A7-F5 · **Status:** not started
- **Evidence:** probed: the doctor repairs launch artifacts for a
  folder with a broken venv.
- **Problem:** the doctor "fixes" the launcher while the app itself
  still cannot start.
- **Fix:** check the venv first and say the venv is broken instead of
  repairing the launcher.
- **Done when:** with a broken venv, the doctor names the venv problem
  instead of reporting a repaired launcher.

### R59 — Uninstall removes the launcher and symlink without checking they point at this install
- **Priority:** P2 · **Area:** Uninstaller · **Sources:** A7-F6 · **Status:** not started
- **Evidence:** `uninstall.sh:57-59` removes the launcher/symlink
  without checking they point at `$DIR` — an old folder's uninstall
  breaks the new install after an upgrade.
- **Problem:** uninstalling the old copy can break the new copy.
- **Fix:** only remove the launcher/symlink when they point at this
  install's folder.
- **Done when:** uninstalling an old folder leaves a newer install's
  launcher alone.

### R60 — With no network, the base install waits minutes in silence
- **Priority:** P2 · **Area:** Installer · **Sources:** A7-F7 · **Status:** not started
- **Evidence:** `install.sh:99-108`: a no-network base install waits
  minutes in silence.
- **Problem:** the user cannot tell whether the install is working or
  stuck.
- **Fix:** say what is being waited on, and time out with a
  plain-words message when there is no network.
- **Done when:** a no-network install says it is waiting and then
  gives up with a clear message.

### R61 — The training install's 3 GB preflight understates the real ~4 GB+ peak
- **Priority:** P2 · **Area:** Installer · **Sources:** A7-F8 · **Status:** not started
- **Evidence:** the training 3 GB preflight understates the ~4 GB+
  peak (pip cache + venv).
- **Problem:** the check passes on a disk that cannot hold the install.
- **Fix:** raise the preflight to cover pip cache + venv (measure the
  real peak — see R23).
- **Done when:** the preflight number covers the measured peak.

### R62 — The training download has no resume
- **Priority:** P2 · **Area:** Installer · **Sources:** A7-F9 · **Status:** not started
- **Evidence:** the training download has no resume (the weights
  download does).
- **Problem:** an interrupted training install starts the download
  from scratch.
- **Fix:** resume the training download the way the weights download
  resumes.
- **Done when:** a stopped training download picks up where it left
  off.

### R63 — There is no click-only uninstall
- **Priority:** P2 · **Area:** Uninstaller · **Sources:** A7-F10 · **Status:** not started
- **Evidence:** no click-only uninstall exists; uninstall is a script.
- **Problem:** the user who never uses the terminal cannot remove the
  app without one.
- **Fix:** add a click-only uninstall (e.g. a desktop entry or a GUI
  action) that keeps the `~/.stella` data by default and asks first.
- **Done when:** Stella can be uninstalled by clicking, with the data
  kept unless the user says otherwise.

### R64 — The probe judge still misjudges 9 of 11 new edge cases
- **Priority:** P2 · **Area:** Probe · **Sources:** A8-4 · **Status:** not started
- **Evidence:** probe judgement residuals beyond T30: 9/11 new edge
  cases misjudged (2nd-sentence refusals missed, unlisted blunt
  refusals missed, "here is" override fires on refusal lists,
  "cannot help but" false positive).
- **Problem:** the gate's judge gets edge cases wrong, so the gate can
  pass a refusing model or fail a willing one.
- **Fix:** fix the 9 edge cases and pin each with a test.
- **Done when:** all 11 edge cases are judged correctly and pinned by
  tests.

### R65 — The probe gate is relative-only and trusts the caller's delta
- **Priority:** P2 · **Area:** Probe · **Sources:** A8-5 · **Status:** not started
- **Evidence:** the gate is relative-only and trusts caller delta:
  100%→100% passes; rates 0%→50% with a stale `delta: 0.0` passes
  (`stella/probe.py:426`).
- **Problem:** the gate can be passed by a stale number, and a model
  that refuses everything can pass if it refused everything before.
- **Fix:** compute the delta from the measured rates instead of
  trusting the caller's, and require an absolute floor as well as the
  relative change.
- **Done when:** a stale delta cannot pass the gate, and an
  always-refusing model cannot pass on "no change".

### R66 — Sleep cycles pile up with no delete, prune, or size anywhere
- **Priority:** P2 · **Area:** Sleep · **Sources:** A8-6 · **Status:** not started
- **Evidence:** sleep cycles pile up with no delete/prune/size in GUI,
  CLI, or engine (checkpoints got this in v0.20, sleep got none).
- **Problem:** old sleep cycles eat disk forever with no way to clear
  them.
- **Fix:** add sleep-cycle delete/prune and a size display (GUI, CLI,
  engine), the way checkpoints have them.
- **Done when:** a sleep cycle can be deleted or pruned from the GUI
  and the CLI, with its size shown.

### R67 — The governing-seat warning only fires for marked profiles, not role-only ones
- **Priority:** P2 · **Area:** Probe · **Sources:** A8-9 · **Status:** not started
- **Evidence:** the pre-train warning only fires for marked profiles;
  role-only governing profiles (e.g. role=driver, stock base) train
  for hours unwarned — measured `governing_seat_warning` → None.
- **Problem:** a profile that will sit in a governing seat trains for
  hours without the warning it should have had.
- **Fix:** fire the warning for role-only governing profiles too.
- **Done when:** a role=driver profile with a stock base gets the
  governing-seat warning before training.

### R68 — The CLI gates everyone by default while the GUI auto-selects: the two disagree
- **Priority:** P2 · **Area:** Probe / CLI · **Sources:** A8-19B · **Status:** not started
- **Evidence:** CLI probe gates everyone by default; the GUI
  auto-selects. (The README wording half of this finding is R69.)
- **Problem:** the same probe behaves differently depending on where
  the user runs it.
- **Fix:** decide one behaviour and make both surfaces match it.
- **Done when:** CLI and GUI agree on who gets gated by default.

### R69 — README refresh: stale prompt count, missing flags, and the LFM3 probe called "informational"
- **Priority:** P2 · **Area:** Docs · **Sources:** A8-8R, A8-10, A8-19R · **Status:** not started
- **Evidence:** "12 prompts" is stale in `README.md:399` (the default
  is 18, governing 24); the Command line section omits
  `--informational`, distill `--timeout`, train `--dry-run` /
  `--from-checkpoint`, and global `--json` / `--quiet` / `--verbose`;
  the README still calls the LFM3 proof probe "informational" though
  its role is `fast` (governing).
- **Problem:** the README describes a version of the product that no
  longer exists.
- **Fix:** refresh the README: correct prompt counts, list the missing
  flags, and fix the probe's role wording.
- **Done when:** the README's prompt counts, flag list, and probe
  wording match the code.

### R70 — How to Use refresh: wrong governing seats, stale prompt count, missing topics, and more
- **Priority:** P2 · **Area:** Docs · **Sources:** A8-7, A8-8H, A8-11, A8-17, A8-18 · **Status:** not started
- **Evidence:** wrong governing seats named in `stella/probe.py:3-4`
  docstring, `stella/howto.py:228-229` (judge/merger/grader/router;
  code gates driver/reviewer/tester/fast); "12 prompts" stale in
  `howto.py:213` (default 18, governing 24); How to Use "Profiles"
  wrongly says the Ollama tag is used for "the refusal probe"
  (`probe.py` has zero `ollama_tag` references); How to Use has no
  topics for bridge, recipes, adapters, checkpoints, or governing-seat
  binding; the GGUF howto omits the quant picker.
- **Problem:** the in-app guide names the wrong seats, the wrong
  counts, and misses whole features.
- **Fix:** correct the seats (probe docstring + howto), the prompt
  count, and the tag claim; add the missing topics and the quant
  picker. Note: the CHANGELOG v0.16.0 bullet gets a correction note,
  not a rewrite.
- **Done when:** How to Use names the right seats and counts, covers
  the missing features, and the CHANGELOG carries a correction note.

### R71 — The v0.24 test fixture opens the real `~/.stella` store and real settings
- **Priority:** P2 · **Area:** Tests · **Sources:** A9-4 · **Status:** not started
- **Evidence:** `tests/test_v24.py`'s window fixture opens the REAL
  `~/.stella` store and real QSettings (a bare `MainWindow()` — the
  only one in the suite); `closeEvent` writes session/geometry back
  into his real settings.
- **Problem:** running the tests writes into his real settings.
- **Fix:** pass `store=seeded, settings=settings` to the fixture.
- **Done when:** the v0.24 fixture never touches the real store or
  real settings.

### R72 — The HEAD and ranged-GET download helpers are never really executed
- **Priority:** P2 · **Area:** Tests · **Sources:** A9-5 · **Status:** not started
- **Evidence:** the HEAD / ranged-GET leaf functions are never executed
  (`stella/train.py:892, 905` are only ever stubbed in
  `tests/test_train.py:1481-1510`); the Content-Range regex and the
  200-fallback are untested.
- **Problem:** the download-resume code paths have no test coverage at
  all.
- **Fix:** add tests that execute the real HEAD and ranged-GET paths
  (against a local server), covering the Content-Range regex and the
  200-fallback.
- **Done when:** the real HEAD and ranged-GET paths run under test.

### R73 — 12 of 30 plain-words error-map entries are untested
- **Priority:** P2 · **Area:** Tests · **Sources:** A9-6 · **Status:** not started
- **Evidence:** needle-by-needle check: 12/30 entries untested (e.g.
  `enospc`, `bad magic`, `could not connect`, `cannot allocate
  memory` appear nowhere in tests).
- **Problem:** the plain-words errors the user sees most in a failure
  are the ones with no test pinning them.
- **Fix:** add tests pinning each of the 12 untested entries.
- **Done when:** all 30 error-map entries have a test.

### R74 — Test fixture teardown does not wait for jobs, so a worker can leak into the next test
- **Priority:** P2 · **Area:** Tests · **Sources:** A9-7 · **Status:** not started
- **Evidence:** fixture teardown doesn't wait for jobs — `win.close()`
  is ignored while a job runs, so one forgotten `_wait_for_job` leaks
  a worker into the next test. Test-side only; no product gap was
  confirmed.
- **Problem:** a forgotten wait in one test can make the next test
  fail for no product reason.
- **Fix:** make fixture teardown wait for jobs to finish before the
  next test starts.
- **Done when:** a test that forgets `_wait_for_job` cannot leak a
  worker into the next test.

### R75 — Resume is enabled with nothing to resume, and never offered after a pause or crash
- **Priority:** P2 · **Area:** GUI / training · **Sources:** A1-F9, A4-F4 · **Status:** not started
- **Evidence:** on a never-trained draft, Resume is enabled with 0
  checkpoints (`stella/gui.py:5603-5607` enables Resume whenever
  there is a session and nothing is running, with no checkpoint
  check). Clicking it starts a worker the engine then refuses with
  "nothing to resume. This project has no checkpoints yet"
  (`stella/train.py:2594-2607`). Resume is also never offered after a
  pause or crash. T150 (DONE) covers resume-from-selected, delete, and
  disk usage, not this button's enablement.
- **Problem:** the button promises an action it cannot do, and the
  moment resume would actually help, it is not offered.
- **Fix:** enable Resume only when the project has at least one
  checkpoint; offer resume after a pause or crash.
- **Done when:** Resume is greyed out with no checkpoints, and offered
  after a pause or crash.

---

## P3 — nice-to-have (R76–R129)

### R76 — An out-of-memory crash mid-run has no plain-words message
- **Priority:** P3 · **Area:** Training · **Sources:** A1-F7 · **Status:** not started
- **Evidence:** no OOM-specific error path (zero `MemoryError`
  matches in the tree); a mid-run OOM surfaces as raw torch text
  (`stella/gui.py:737`) or a silent death.
- **Problem:** the most likely failure on an 8 GB PC shows raw torch
  text or nothing at all.
- **Fix:** catch `MemoryError` / torch OOM in the training path and
  show a plain-words message (what happened, what to lower).
- **Done when:** a mid-run OOM shows a plain-words message.

### R77 — A crash mid-save leaves orphan checkpoint folders nothing can see or delete
- **Priority:** P3 · **Area:** Training · **Sources:** A1-F8 · **Status:** not started
- **Evidence:** proven live: a crash mid-save leaves orphan checkpoint
  dirs invisible to list/prune/GUI, with no reaper and no CLI delete;
  `_save_checkpoint` (`stella/train.py:1894`) writes in place, with no
  tmp+rename.
- **Problem:** crashed saves leave litter that takes disk and cannot
  be cleaned from anywhere.
- **Fix:** save checkpoints via tmp+rename; add a reaper for orphans
  (and a CLI delete — see R112, which deliberately excludes prune
  because this task owns it).
- **Done when:** a crash mid-save leaves no orphan, and any orphan is
  cleaned or deletable.

### R78 — Autoconfig ignores model size, disk, and CPU, and can silently change rank/seq between runs
- **Priority:** P3 · **Area:** Training · **Sources:** A1-F10 · **Status:** not started
- **Evidence:** autoconfig ignores model size (`model_params_b`
  accepted, unused), disk, and CPU; auto re-resolve can silently
  change rank/seq between runs (`stella/autoconfig.py:161-178`).
- **Problem:** the automatic settings do not look at the model or the
  machine, and can change between runs without saying so.
- **Fix:** use `model_params_b`, disk, and CPU in autoconfig; say
  plainly when a re-resolve changes a setting.
- **Done when:** autoconfig considers the model and the machine, and
  a changed setting is announced.

### R79 — There is no free-disk check in the training path
- **Priority:** P3 · **Area:** Training · **Sources:** A1-F11 · **Status:** not started
- **Evidence:** free disk is measured but never consumed in the
  training path.
- **Problem:** a run can start on a disk that cannot hold its
  checkpoints.
- **Fix:** check free disk before a training run starts and refuse
  with a plain-words message when it cannot hold the run.
- **Done when:** a training run refuses to start when the disk cannot
  hold it.

### R80 — Raw error text leaks into the user-facing messages on the GGUF paths
- **Priority:** P3 · **Area:** GGUF · **Sources:** A2-F10 · **Status:** not started
- **Evidence:** a raw `({exc})` leak in `ollama.generate`, and a raw
  transformers line in `_hf_load_message`.
- **Problem:** the user sees library internals instead of plain words.
- **Fix:** route both through the plain-words error map.
- **Done when:** neither path shows raw library text.

### R81 — CLI export never shows the estimate the GUI shows
- **Priority:** P3 · **Area:** CLI / GGUF · **Sources:** A2-F11 · **Status:** not started
- **Evidence:** CLI export never shows the estimate the GUI shows.
- **Problem:** a CLI user exports blind, without the size/time
  estimate the GUI gives.
- **Fix:** print the same estimate on CLI export.
- **Done when:** CLI export shows the estimate.

### R82 — `create_in_ollama` is called with no timeout
- **Priority:** P3 · **Area:** GGUF · **Sources:** A2-F12 · **Status:** not started
- **Evidence:** `create_in_ollama` is called without a timeout.
- **Problem:** a hung Ollama create hangs the export forever.
- **Fix:** give the call a timeout with a plain-words message when it
  fires.
- **Done when:** a hung Ollama create stops on a timeout and says so.

### R83 — Export deletes the merged dir before the job lock, and unlinks the GGUF unconditionally
- **Priority:** P3 · **Area:** GGUF · **Sources:** A2-F13 · **Status:** not started
- **Evidence:** the merged dir is deleted before the job lock, and the
  GGUF is unlinked unconditionally.
- **Problem:** the cleanup order can delete work that is still in use,
  or delete a file it should have kept.
- **Fix:** order the cleanup after the lock, and only unlink the GGUF
  when the export genuinely failed.
- **Done when:** export cleanup never deletes live work or a good
  file.

### R84 — The `--modelfile` fallback breaks on paths with spaces
- **Priority:** P3 · **Area:** GGUF · **Sources:** A2-F14 · **Status:** not started
- **Evidence:** the `--modelfile` fallback breaks on spaced paths.
- **Problem:** a model file under a path with a space fails to load.
- **Fix:** quote or pass the path safely in the fallback.
- **Done when:** a spaced path works through the `--modelfile`
  fallback.

### R85 — Prompts are not stripped of a byte-order mark
- **Priority:** P3 · **Area:** Distill · **Sources:** A2-F15 · **Status:** not started
- **Evidence:** no BOM strip in prompts.
- **Problem:** a prompt file saved with a BOM starts with an invisible
  character the model sees.
- **Fix:** strip a leading BOM when reading prompts.
- **Done when:** a BOM'd prompt file reads clean.

### R86 — Requant work files can collide by name
- **Priority:** P3 · **Area:** Requant · **Sources:** A2-F16 · **Status:** not started
- **Evidence:** requant work-file name collisions.
- **Problem:** two requants can write over each other's work files.
- **Fix:** make work-file names unique per job.
- **Done when:** two requants cannot share a work-file name.

### R87 — `base_ref` is never checked against the actual weights
- **Priority:** P3 · **Area:** Profiles · **Sources:** A3-F9 · **Status:** not started
- **Evidence:** T54 residual — `base_ref` is never verified against
  actual weights; the health check covers the tag only.
- **Problem:** a profile can point at weights that are not what its
  `base_ref` says, and nothing notices.
- **Fix:** verify `base_ref` against the actual weights in the health
  check.
- **Done when:** a mismatched `base_ref` is reported by the health
  check.

### R88 — `settings_source` is silently lost on a round-trip (auto becomes manual)
- **Priority:** P3 · **Area:** Profiles · **Sources:** A3-F10 · **Status:** not started
- **Evidence:** `settings_source` is lost on round-trip (auto →
  manual, silently).
- **Problem:** a setting that was automatic quietly becomes manual,
  and the user is never told.
- **Fix:** carry `settings_source` through the round-trip.
- **Done when:** an auto setting stays auto after a round-trip.

### R89 — The LFM3 template still carries a dead `settings["notes"]` key
- **Priority:** P3 · **Area:** Profiles · **Sources:** A3-F11 · **Status:** not started
- **Evidence:** the LFM3 template still carries dead
  `settings["notes"]`.
- **Problem:** a dead field in the starter template — exactly what the
  "no dead fields" rule forbids.
- **Fix:** remove the dead key from the template.
- **Done when:** the LFM3 template has no dead `settings["notes"]`.

### R90 — CLI `--purge` has no prompt
- **Priority:** P3 · **Area:** CLI · **Sources:** A3-F13 · **Status:** not started
- **Evidence:** CLI `--purge` has no prompt.
- **Problem:** a destructive command runs with no chance to back out.
- **Fix:** prompt before purging (with a `--yes` escape for scripts).
- **Done when:** `--purge` asks first.

### R91 — The trash shows no size and has no auto-purge age
- **Priority:** P3 · **Area:** Profiles · **Sources:** A3-F14 · **Status:** not started
- **Evidence:** the trash shows no size, no auto-purge age.
- **Problem:** the user cannot tell how much disk the trash holds, and
  it grows forever.
- **Fix:** show the trash's size and add an auto-purge age.
- **Done when:** the trash shows its size and old items are purged on
  schedule.

### R92 — How to Use opens on an empty pane, not Getting started
- **Priority:** P3 · **Area:** GUI · **Sources:** A4-F8 · **Status:** HARD-GATED (design decision for Joshua)
- **Evidence:** opening How to Use shows no topic selected and the
  placeholder "Pick a topic on the left to read how it works."
  (probe3.out). In v0.8.0 it opened on "Getting started" with the body
  already shown — audit-09 listed that as a strength. The v0.23.0
  search task says search "never selects a topic", which is about
  search behaviour; the initial pane is a separate choice.
- **Problem:** the first thing a lost user sees is an empty pane
  instead of the short path.
- **Fix:** a design tension for Joshua to re-decide: open on Getting
  started, or keep the empty pane deliberately.
- **Done when:** the choice is made and the window follows it.

### R93 — A picked job cannot be un-picked; Go stays armed
- **Priority:** P3 · **Area:** GUI · **Sources:** A4-F9 · **Status:** not started
- **Evidence:** once a job button is picked, clicking it again leaves
  it checked, and `setChecked(False)` is ignored — the exclusive
  button group keeps one button checked (probe2.out). The user can
  switch jobs but never return to "no job picked", so Go stays armed.
- **Problem:** there is no way back from a pick.
- **Fix:** make the job buttons non-exclusive toggles, or add a
  clear-pick path.
- **Done when:** a picked job can be un-picked and Go disarms.

### R94 — No Quit in the File menu, no Ctrl+Q
- **Priority:** P3 · **Area:** GUI · **Sources:** A4-F10 · **Status:** not started
- **Evidence:** the File menu has 12 actions and no Quit/Exit
  (`stella/gui.py:4220-4279`); no `quit` action exists anywhere in
  `gui.py`. Closing works via the window chrome.
- **Problem:** a real menu bar conventionally offers Quit, and
  keyboard users have no Ctrl+Q.
- **Fix:** add a Quit action to the File menu with Ctrl+Q.
- **Done when:** File has Quit and Ctrl+Q closes the app.

### R95 — The finish moment lasts 250 ms: too brief to read
- **Priority:** P3 · **Area:** GUI · **Sources:** A4-F11 · **Status:** not started
- **Evidence:** `finish_moment` shows the gold card and hides it on a
  single-shot 250 ms timer (`stella/gui.py:1187-1189, 1281`). Probe6c:
  visible at t=0 and t=+0.1 s, gone by t=+0.3 s. A nine-word summary
  cannot be read in a quarter of a second. Nothing is lost — the same
  line persists in the status bar — but the moment functions as a
  flash, not a readable celebration.
- **Problem:** the celebration of a finished run is over before it can
  be read.
- **Fix:** let the moment linger 2–3 s before hiding.
- **Done when:** the finish card stays readable for 2–3 s.

### R96 — How to Use search with no match gives no "nothing found" message
- **Priority:** P3 · **Area:** GUI · **Sources:** A4-F12 · **Status:** not started
- **Evidence:** searching "zzzznope" leaves zero visible topics and the
  content pane still reads "Pick a topic on the left to read how it
  works." (probe6.out). No feedback that the search matched nothing.
- **Problem:** the user cannot tell whether the search ran or matched
  nothing.
- **Fix:** show one line in the pane ("Nothing matches 'zzzznope'. Try
  fewer words.").
- **Done when:** a no-match search says so.

### R97 — No drag-and-drop for a dataset file
- **Priority:** P3 · **Area:** GUI · **Sources:** A4-F13 · **Status:** not started
- **Evidence:** no widget in the GUI accepts drops (no `setAcceptDrops`
  anywhere in `gui.py`). The only paths to set a dataset are Browse
  and the sample dataset button. BNB library entry 027's one face in
  Stella.
- **Problem:** dropping a `.jsonl` file onto the dataset picker — the
  simplest way to pick a file — does not work.
- **Fix:** accept a dropped `.jsonl` file on the dataset picker.
- **Done when:** dropping a `.jsonl` file onto the dataset picker sets
  the dataset.

### R98 — No shortcut help: F2-rename and Ctrl+S are undiscoverable
- **Priority:** P3 · **Area:** GUI · **Sources:** A4-F14 · **Status:** not started
- **Evidence:** shortcuts exist but there is no `?` overlay, no
  central registry, and no Shortcuts topic among the 13 How to Use
  topics — F2 rename is discoverable only via the right-click menu,
  Ctrl+S only by trying it. BNB library entry 028.
- **Problem:** shortcuts nobody can find are features nobody has.
- **Fix:** add a Shortcuts topic in How to Use (generated from one
  registry, so it cannot drift), or a `?` overlay.
- **Done when:** every shortcut is listed somewhere the user can find.

### R99 — The cap-hit reply is not recorded in the chat history
- **Priority:** P3 · **Area:** Chat · **Sources:** A5-F10 · **Status:** not started
- **Evidence:** the cap-hit reply is not recorded in history.
- **Problem:** the conversation's record has a hole where the agent
  stopped.
- **Fix:** record the cap-hit reply in history like any other reply.
- **Done when:** a cap-hit reply appears in the history.

### R100 — "just do it" only matches at the start of a message
- **Priority:** P3 · **Area:** Chat · **Sources:** A5-F11 · **Status:** not started
- **Evidence:** "just do it" only matches at message start.
- **Problem:** "ok, just do it" does not trigger the plan-first flow
  the greeting promises.
- **Fix:** match the phrase anywhere in the message.
- **Done when:** "just do it" works wherever it appears in a message.

### R101 — A custom base URL ending in `/chat/completions` doubles the path
- **Priority:** P3 · **Area:** Providers · **Sources:** A5-F12 · **Status:** not started
- **Evidence:** a custom base URL ending in `/chat/completions`
  doubles the path.
- **Problem:** a user who pastes the full endpoint URL gets a doubled
  path and a failing call.
- **Fix:** strip a trailing `/chat/completions` from a custom base
  URL before appending it.
- **Done when:** a full endpoint URL works as a custom base URL.

### R102 — The chat-window model buttons are Ollama-only
- **Priority:** P3 · **Area:** Chat · **Sources:** A5-F13 · **Status:** not started
- **Evidence:** the chat-window model buttons are Ollama-only.
- **Problem:** the click-to-pick path — the one a 5-year-old would
  use — does not offer cloud models.
- **Fix:** offer the configured cloud models as buttons too.
- **Done when:** the chat window's buttons include the cloud models.

### R103 — The `resume` / `dest` tool arguments are accepted but undocumented
- **Priority:** P3 · **Area:** Chat · **Sources:** A5-F14 · **Status:** not started
- **Evidence:** `resume` / `dest` tool args are accepted but
  undocumented.
- **Problem:** the agent can be given arguments nobody can learn about.
- **Fix:** document the arguments in the tool help.
- **Done when:** `resume` and `dest` are documented where the tools
  are.

### R104 — Cloud providers never stream
- **Priority:** P3 · **Area:** Chat · **Sources:** A5-F15 · **Status:** not started
- **Evidence:** cloud providers never stream.
- **Problem:** cloud chat answers arrive all at once after a long
  silence, instead of appearing as they come.
- **Fix:** stream cloud provider replies like local ones.
- **Done when:** cloud chat replies stream.

### R105 — A corrupt `providers.json` silently reads as "no keys"
- **Priority:** P3 · **Area:** Providers · **Sources:** A5-F16 · **Status:** not started
- **Evidence:** a corrupt `providers.json` silently reads as "no
  keys".
- **Problem:** a user with saved keys is told they have none, with no
  hint the file is broken.
- **Fix:** say plainly that the file is corrupt (and offer to reset
  it) instead of silently treating it as empty.
- **Done when:** a corrupt `providers.json` produces a plain-words
  message.

### R106 — No cloud cost or usage visibility for cloud chat
- **Priority:** P3 · **Area:** Providers · **Sources:** M8-COST · **Status:** not started
- **Evidence:** there is no cost/usage visibility for cloud chat
  anywhere. Note: the free tier still exists on the remaining
  self-serve Groq models (rate-capped); the gap is that the user
  cannot see what a chat costs or how much of a free tier they have
  used.
- **Problem:** the user cannot see what cloud chat costs them.
- **Fix:** show token/usage counts for cloud chats (and any free-tier
  limits the provider reports).
- **Done when:** a cloud chat shows what it used.

### R107 — The setting-flag help says nothing useful
- **Priority:** P3 · **Area:** CLI · **Sources:** A6-W8 · **Status:** not started
- **Evidence:** content-free setting-flag help.
- **Problem:** the help for a flag does not say what the flag does.
- **Fix:** write real help text for the setting flags.
- **Done when:** every setting flag's help says what it does.

### R108 — `probe --json` prints no JSON on failure
- **Priority:** P3 · **Area:** CLI · **Sources:** A6-W9 · **Status:** not started
- **Evidence:** `probe --json` prints no JSON on failure (unlike
  `verify`).
- **Problem:** a script asking for JSON gets nothing on the failure
  path.
- **Fix:** print a JSON error object on failure, like `verify` does.
- **Done when:** `probe --json` prints JSON on failure too.

### R109 — The `stella-cli` comment lists 9 of 31 commands
- **Priority:** P3 · **Area:** CLI · **Sources:** A6-W10 · **Status:** not started
- **Evidence:** the `stella-cli` comment lists 9 of 31 commands.
- **Problem:** a stale comment misleads anyone reading the code.
- **Fix:** update the comment to list all 31 commands (or drop the
  list).
- **Done when:** the comment matches the command list.

### R110 — CLI help says "MetaMorphAi mode" while the GUI follows the no-metamorph-words rule
- **Priority:** P3 · **Area:** CLI · **Sources:** A6-W11 · **Status:** not started
- **Evidence:** CLI help says "MetaMorphAi mode" vs the GUI's T71
  no-metamorph-words rule.
- **Problem:** the two surfaces use different words for the same thing.
- **Fix:** align the CLI help wording with the GUI's rule (note only
  — the MetaMorphAi reading itself stays gated on Joshua).
- **Done when:** CLI help and the GUI use the same words.

### R111 — Small CLI inconsistencies: delete errors, a stray advisory, doubled "rough", a progress line before its failure
- **Priority:** P3 · **Area:** CLI · **Sources:** A6-W12 · **Status:** not started
- **Evidence:** delete errors omit the profile; a HF Hub advisory
  appears on dry-run stderr; "roughly minutes … (rough)"; a
  `pull-weights` progress line prints before its failure.
- **Problem:** four small rough edges in CLI output.
- **Fix:** name the profile in delete errors; drop the advisory on a
  dry run; fix the doubled "rough"; print the progress line only when
  the pull starts.
- **Done when:** all four are fixed.

### R112 — No CLI for mark-ready/status, notes, viewing probe results, How to Use, or a debug report
- **Priority:** P3 · **Area:** CLI · **Sources:** A6-PARITY · **Status:** not started
- **Evidence:** no CLI for mark-ready/status, notes, view probe
  results, howto, or debug report. Prune is deliberately excluded
  from this bundle — it is covered by R77.
- **Problem:** five GUI things have no CLI equivalent.
- **Fix:** add CLI commands for mark-ready/status, notes, viewing
  probe results, How to Use, and a debug report.
- **Done when:** all five work from the CLI. (Prune: see R77.)

### R113 — Training settings are CLI-only since the GUI form was deleted, and the window never says so
- **Priority:** P3 · **Area:** CLI / GUI · **Sources:** A6-DISCLOSURE · **Status:** not started
- **Evidence:** training settings are CLI-only since T16 deleted the
  GUI form, and the window never says so.
- **Problem:** a user who wants to change a training setting cannot
  find where to do it.
- **Fix:** say in the window (plain words) that training settings live
  on the command line, and where.
- **Done when:** the window tells the user where training settings
  live.

### R114 — The installer file itself shows a generic icon before install
- **Priority:** P3 · **Area:** Installer · **Sources:** A7-F11 · **Status:** not started
- **Evidence:** the installer file itself shows a generic icon
  pre-install (`Icon=stella` is unresolvable before install). No clean
  spec-compliant fix is known — this may be accept-and-document.
- **Problem:** the first thing the user double-clicks looks generic.
- **Fix:** find a spec-compliant way to give the installer its icon
  pre-install, or document that it cannot be done.
- **Done when:** the installer shows its icon, or the limitation is
  documented.

### R115 — The uninstall icon-removal fallback never runs on a venv-branch failure
- **Priority:** P3 · **Area:** Uninstaller · **Sources:** A7-F12 · **Status:** not started
- **Evidence:** the uninstall icon-removal fallback never runs on a
  venv-branch failure.
- **Problem:** a failed uninstall branch leaves the icon behind with
  no fallback.
- **Fix:** make the fallback run on the venv-branch failure too.
- **Done when:** the icon is removed even when the venv branch fails.

### R116 — Uninstall leaves about 2 GB of pip cache behind
- **Priority:** P3 · **Area:** Uninstaller · **Sources:** A7-F13 · **Status:** not started
- **Evidence:** uninstall leaves ~2 GB of pip cache.
- **Problem:** removing Stella leaves 2 GB of cache the user never
  asked to keep.
- **Fix:** offer to remove the pip cache on uninstall.
- **Done when:** uninstall offers to clear the pip cache.

### R117 — An early-failing re-install deletes the previous good receipt
- **Priority:** P3 · **Area:** Installer · **Sources:** A7-F14 · **Status:** not started
- **Evidence:** an early-failing re-install deletes the previous good
  receipt.
- **Problem:** a failed re-install destroys the record of the good
  install it replaced.
- **Fix:** only replace the receipt after a successful install.
- **Done when:** a failed re-install leaves the old receipt alone.

### R118 — The icon render lacks `QT_QPA_PLATFORM=offscreen`
- **Priority:** P3 · **Area:** Installer · **Sources:** A7-F15 · **Status:** not started
- **Evidence:** the icon render lacks `QT_QPA_PLATFORM=offscreen`.
- **Problem:** the icon render can fail where there is no display.
- **Fix:** set `QT_QPA_PLATFORM=offscreen` for the icon render.
- **Done when:** the icon renders without a display.

### R119 — The desktop copy only tries `~/Desktop`
- **Priority:** P3 · **Area:** Installer · **Sources:** A7-F16 · **Status:** not started
- **Evidence:** the desktop copy only tries `~/Desktop`.
- **Problem:** on a system whose desktop folder is elsewhere, the icon
  lands in the wrong place or not at all.
- **Fix:** resolve the desktop folder properly (e.g. via
  `xdg-user-dir DESKTOP`) and fall back to `~/Desktop`.
- **Done when:** the desktop icon lands on the real desktop folder.

### R120 — CI never runs desktop-file-validate or shellcheck, and has no scheduled runs
- **Priority:** P3 · **Area:** CI · **Sources:** A7-F17, A9-CI · **Status:** not started
- **Evidence:** CI never runs desktop-file-validate or shellcheck
  (T64's "validates clean" is unverified anywhere); CI only fires on
  push/PR — there are no scheduled runs.
- **Problem:** two checks nobody runs, and a suite that only runs when
  someone pushes.
- **Fix:** add desktop-file-validate and shellcheck to CI, and add a
  scheduled run.
- **Done when:** CI runs both checks and runs on a schedule.

### R121 — No click-only doctor
- **Priority:** P3 · **Area:** Doctor · **Sources:** A7-F18 · **Status:** not started
- **Evidence:** no click-only doctor exists (mitigated: re-running the
  installer.desktop in the moved folder does repair).
- **Problem:** the repair tool needs the terminal, like the training
  install (R13).
- **Fix:** add a click-only way to run the doctor (or fold it into the
  installer flow).
- **Done when:** the doctor can be run by clicking.

### R122 — `PROMPTS_VERSION` is still 2 after the v0.22 battery change
- **Priority:** P3 · **Area:** Probe · **Sources:** A8-12 · **Status:** not started
- **Evidence:** `PROMPTS_VERSION` is still 2 after the v0.22 battery
  change.
- **Problem:** the version number does not match the battery it
  labels.
- **Fix:** bump `PROMPTS_VERSION` to match the current battery.
- **Done when:** the version matches the battery.

### R123 — A typo in the dream-skip string
- **Priority:** P3 · **Area:** Sleep · **Sources:** A8-13 · **Status:** not started
- **Evidence:** a dream-skip string typo (`" (...). Dreaming
  skipped"`).
- **Problem:** a typo in a user-facing string.
- **Fix:** fix the typo.
- **Done when:** the string reads correctly.

### R124 — The sleep manifest's `stella_version` is "0.3"
- **Priority:** P3 · **Area:** Sleep · **Sources:** A8-14 · **Status:** not started
- **Evidence:** the sleep manifest `stella_version` is `"0.3"`.
- **Problem:** the manifest claims a version from long ago.
- **Fix:** write the real version into the sleep manifest.
- **Done when:** a new sleep manifest carries the real version.

### R125 — Substring over-gating: "breakfast" and "screwdriver" gate the probe
- **Priority:** P3 · **Area:** Probe · **Sources:** A8-16 · **Status:** not started
- **Evidence:** substring over-gating (`breakfast` / `screwdriver`
  gate).
- **Problem:** ordinary words trip the gate because they contain a
  flagged substring.
- **Fix:** match whole words (or word boundaries) instead of
  substrings.
- **Done when:** "breakfast" and "screwdriver" no longer gate.

### R126 — Dreaming can stall the full 120 s on a hung Ollama
- **Priority:** P3 · **Area:** Sleep · **Sources:** A8-20 · **Status:** not started
- **Evidence:** dreaming can stall the full 120 s on a hung Ollama.
- **Problem:** a hung Ollama stalls a sleep cycle for two full minutes
  with nothing to show for it.
- **Fix:** shorten the dreaming timeout or make it interruptible.
- **Done when:** a hung Ollama does not stall dreaming for the full
  120 s.

### R127 — TEST-REPORT.md is stale and the `__init__.py` docstring still says v0.8.0
- **Priority:** P3 · **Area:** Tests / docs · **Sources:** A9-9 · **Status:** not started
- **Evidence:** TEST-REPORT.md is stale (120 passed / 22 skipped vs
  the real 1462 items); `__init__.py`'s docstring still says v0.8.0.
- **Problem:** the test report and the package docstring describe an
  old version.
- **Fix:** refresh TEST-REPORT.md to the real counts and update the
  docstring.
- **Done when:** both match the current suite and version.

### R128 — No pytest config file: no timeouts, no markers
- **Priority:** P3 · **Area:** Tests · **Sources:** A9-10 · **Status:** not started
- **Evidence:** no pytest config file (no timeouts/markers); a hung
  test could hang CI to its 6 h default.
- **Problem:** one hung test can hold CI for six hours.
- **Fix:** add a pytest config with a timeout (and markers where they
  help).
- **Done when:** a hung test times out instead of holding CI.

### R129 — FORMAT.md refresh: the example shows 0.18.0 and omits `governing_seat` and `dataset/`
- **Priority:** P3 · **Area:** Docs · **Sources:** A8-15, A3-F12 · **Status:** not started
- **Evidence:** FORMAT.md's example shows 0.18.0 and omits
  `governing_seat`; the layout omits `dataset/`.
- **Problem:** the format doc describes an old layout.
- **Fix:** refresh FORMAT.md to the current version and layout.
- **Done when:** FORMAT.md matches the current store layout.

---

## Coverage map

Every finding from the nine audits is traced to exactly one task
below. Two findings were split across two tasks (A8-8, A8-19); the
suffix marks which half. One finding was withdrawn (A3-F6) after a
probe disproved it — it is not a task.

| Source finding | Task |
|---|---|
| A1-F1 | R19 (hard-gated) |
| A1-F2 | R24 |
| A1-F3 | R25 |
| A1-F4 | R26 |
| A1-F5 | R27 |
| A1-F6 | R28 |
| A1-F7 | R76 |
| A1-F8 | R77 |
| A1-F9 | R75 |
| A1-F10 | R78 |
| A1-F11 | R79 |
| A2-F1 | R6 |
| A2-F2 | R5 |
| A2-F3 | R29 |
| A2-F4 | R30 |
| A2-F5 | R31 |
| A2-F6 | R32 |
| A2-F7 | R33 |
| A2-F8 | R34 |
| A2-F9 | R35 |
| A2-F10 | R80 |
| A2-F11 | R81 |
| A2-F12 | R82 |
| A2-F13 | R83 |
| A2-F14 | R84 |
| A2-F15 | R85 |
| A2-F16 | R86 |
| A3-F1 | R2 |
| A3-F2 | R7 |
| A3-F3 | R36 |
| A3-F4 | R37 |
| A3-F5 | R38 |
| A3-F6 | withdrawn (probe disproved it — see the report) |
| A3-F7 | R39 |
| A3-F8 | R40 |
| A3-F9 | R87 |
| A3-F10 | R88 |
| A3-F11 | R89 |
| A3-F12 | R129 |
| A3-F13 | R90 |
| A3-F14 | R91 |
| A4-F1 | R1 |
| A4-F2 | R41 |
| A4-F3 | R42 |
| A4-F4 | R75 |
| A4-F5 | R43 |
| A4-F6 | R2 |
| A4-F7 | R44 |
| A4-F8 | R92 |
| A4-F9 | R93 |
| A4-F10 | R94 |
| A4-F11 | R95 |
| A4-F12 | R96 |
| A4-F13 | R97 |
| A4-F14 | R98 |
| A5-F1 | R11 |
| A5-F2 | R12 |
| A5-F3 | R14 |
| A5-F4 | R45 |
| A5-F5 | R46 |
| A5-F6 | R47 |
| A5-F7 | R48 |
| A5-F8 | R49 |
| A5-F9 | R50 |
| A5-F10 | R99 |
| A5-F11 | R100 |
| A5-F12 | R101 |
| A5-F13 | R102 |
| A5-F14 | R103 |
| A5-F15 | R104 |
| A5-F16 | R105 |
| A6-W1 | R15 |
| A6-W2 | R52 |
| A6-W3 | R28 |
| A6-W4 | R53 |
| A6-W5 | R54 |
| A6-W6 | R55 |
| A6-W7 | R56 |
| A6-W8 | R107 |
| A6-W9 | R108 |
| A6-W10 | R109 |
| A6-W11 | R110 |
| A6-W12 | R111 |
| A6-PARITY | R112 |
| A6-DISCLOSURE | R113 |
| A7-F1 | R9 |
| A7-F2 | R10 |
| A7-F3 | R13 |
| A7-F4 | R57 |
| A7-F5 | R58 |
| A7-F6 | R59 |
| A7-F7 | R60 |
| A7-F8 | R61 |
| A7-F9 | R62 |
| A7-F10 | R63 |
| A7-F11 | R114 |
| A7-F12 | R115 |
| A7-F13 | R116 |
| A7-F14 | R117 |
| A7-F15 | R118 |
| A7-F16 | R119 |
| A7-F17 | R120 |
| A7-F18 | R121 |
| A8-1 | R3 |
| A8-2 | R4 |
| A8-3 | R8 |
| A8-4 | R64 |
| A8-5 | R65 |
| A8-6 | R66 |
| A8-7 | R70 |
| A8-8 (README half) | R69 |
| A8-8 (How to Use half) | R70 |
| A8-9 | R67 |
| A8-10 | R69 |
| A8-11 | R70 |
| A8-12 | R122 |
| A8-13 | R123 |
| A8-14 | R124 |
| A8-15 | R129 |
| A8-16 | R125 |
| A8-17 | R70 |
| A8-18 | R70 |
| A8-19 (behaviour) | R68 |
| A8-19 (README half) | R69 |
| A8-20 | R126 |
| A9-1 | R16 |
| A9-2 | R17 |
| A9-3 | R18 |
| A9-4 | R71 |
| A9-5 | R72 |
| A9-6 | R73 |
| A9-7 | R74 |
| A9-8 | R6 |
| A9-9 | R127 |
| A9-10 | R128 |
| A9-CI (no scheduled runs) | R120 |
| M8-FRESHNESS | R51 |
| M8-COST | R106 |
| G2 | R20 (hard-gated) |
| G3 | R21 (hard-gated) |
| G4 | R22 (hard-gated) |
| G5 | R23 (hard-gated) |

**Counts check:** 133 findings filed by the nine audits, minus 1
withdrawn (A3-F6) = 132 live findings, plus 2 missing-outright items
(M8), 4 real-PC tails (G2–G5), and 1 CI gap noted by the tests audit
(A9-CI) = 139 source items. Two findings were split (A8-8, A8-19),
adding 2 parts = 141 traced items. Eight merges folded 20 items into
8 tasks (M1, M2, M4, M5, M6, M11, M12, and A7-F17 + A9-CI in R120),
removing 12: 141 − 12 = 129 tasks. P0: 0. P1: 23 (R1–R23). P2: 52
(R24–R75). P3: 54 (R76–R129).
