# Stella + OST improvement task list — record (2026-11-15)

Ordered highest to lowest priority by Arlo, 2026-11-15 ~00:27 EST,
from hands-on use of Stella 0.23.0 and OST v16 on Arlo's VM, plus
the trim-testing research report
(~/workspace/research_notes/testing-ai-models-for-trimming-20261115-0306/report.md).
Pasted by Joshua to the STELLA thread 2026-11-15 ~09:07 EST; ordered
to fix/implement ~09:09 ("These need to be fixed and or implemented
into Stella to ensure they are working as they are supposed to").

Ordering rule: fix what's broken or blocking first, then the proof
the trim mission rests on, then correctness guards, then workflow
polish.

**Numbering:** Joshua's pasted list is canonical (24 items, below).
The combined file at ~/workspace/improvement-lists/
stella-ost-task-list.md inserts the single-file HF defect as #2,
shifting every later number +1 there (distill timeout is #4 there,
RAM-before-training #7, double-quant #15, unknown quant #16,
checkpoint/resume #17, cleanup #18, doctor #20, install #21,
progress #22, plain-words #23, Ollama bridge #24). The ITEMS are
identical — only the numbers differ. This file uses Joshua's
numbers; the defect is listed separately as D1.

**Scope:** this file records the STELLA half, shipped in v0.24.0.
The 11 OST items belong to the OST thread and were NOT built here;
they are listed below marked OST THREAD so the list stays whole.

Items marked [FIXED HERE] already had a working fix in Arlo's live
Stella install (~/workspace/stella-live/stella/) — they were
ported into the release, not built from scratch.

## P0 — broken or blocking

1. [Stella] [FIXED HERE] Ship the requant fix. As released, requant
   fails on every real Ollama model in ~14s — llama-quantize is
   called without --allow-requantize. Proven: 1.04 GB -> 718 MB,
   loads and answers, original untouched.
   **Status: DONE in v0.24.0** (ported from the live install;
   requant suite 26 passed).

2. [OST] Check RAM before loading each model. Ollama dying on load
   killed Joshua's real-PC runs twice; a crash mid-run wastes the
   whole benchmark. Verified: no memory check in the code —
   currently manual (free -h before each model). Wait or skip
   instead of crashing.
   **Status: OST THREAD — not built here.**

3. [Stella] Let the user set the distill timeout. Fixed 300s per
   prompt, no CLI knob (verified: no timeout option in cli.py). On
   a slow CPU box one prompt crawled at 1 token in 115s and never
   got an answer in 5 attempts.
   **Status: DONE in v0.24.0** (`stella-cli distill --timeout`,
   Distill dialog spinbox, chat distill tool arg; default 300).

4. [Stella] Keep the teacher model warm during a distill run.
   Stella never sets keep-alive (verified: no keep_alive anywhere
   in the code), so with Ollama's default the model reloads on
   every prompt, 30-60s each.
   **Status: DONE in v0.24.0** (keep_alive "30m" on every teacher
   call; unloads on its own after the run, never kept forever).

5. [OST] Resume an interrupted run. A restart or OOM wipes hours of
   testing. Verified: resume exists for pulls only, not runs.
   **Status: OST THREAD — not built here.**

6. [Stella] Check RAM before training starts. Estimate whether
   model + optimizer fit and say so up front instead of dying
   halfway through an hours-long run. The training probe is
   measuring the real ceiling now.
   **Status: DONE in v0.24.0** (recalibrated: weights counted at
   the probe-grounded 0.5x resident fraction, limit is the RAM
   actually free; 3B at seq 512 now fits at 5.57 GB where it was
   refused at 8.06 GB; the guard still overstates every measured
   peak).

7. [OST] Enforce one model loaded at a time. Set and verify the
   Ollama limit itself so a stray setting can't load two models
   and OOM.
   **Status: OST THREAD — not built here.**

## P1 — proof integrity (needed to trust the trim)

8. [OST] Paired before/after with a pre-declared margin. Run the
   same items before and after, declare the allowed drop up front
   (e.g. -2 pts on role pass rate), report pass/fail on that. "No
   significant difference" is not proof — this is the one the
   whole "trimmed without damage" claim rests on.
   **Status: OST THREAD — not built here.**

9. [OST] Bigger "certify" mode. 108 prompts per run is fine for a
   quick check; ~250 items to catch a ~10-pt regression, ~500+ for
   a tight margin. Keep the quick run, add a thorough one for the
   final call.
   **Status: OST THREAD — not built here.**

10. [OST] Per-role slices. Group scores by Forge role (driver,
    vision, tool, coder) instead of one overall number — a model
    can look fine overall and be broken for its actual job.
    **Status: OST THREAD — not built here.**

11. [OST] Test the shipped artifact. Score the actual quantized
    file that will ship, not the source model, so the grade
    matches what runs.
    **Status: OST THREAD — not built here.**

12. [OST] Surface speed per template. Decode speed is already
    recorded per run (avg_decode_tok_s); show it per template so
    "really fast" is measured per job, not just overall.
    **Status: OST THREAD — not built here.**

13. [OST] Bring Compare to the command line. The window already
    has a Compare tab, but the trimming workflow is headless — a
    headless before/after diff per template closes the loop.
    **Status: OST THREAD — not built here.**

## P2 — correctness guards

14. [Stella] [FIXED HERE] Warn before double-quantizing. Shrinking
    an already-quantized model rounds the weights a second time
    and can lose noticeably more quality. Say it in plain words
    before the run.
    **Status: DONE in v0.24.0** (ported from the live install;
    warns unless the source is positively known unquantized).

15. [Stella] Fix the "unknown" quant reading. The GGUF parser
    reports the source quant as "unknown" on real Ollama files,
    so size estimates are guesses.
    **Status: DONE in v0.24.0** (the parser read only the first
    1 MB; real metadata is 7.85 MB — the header is now streamed.
    Verified live: Q5_K, 5.5 bits per weight. Note: the file's
    manifest name said Q4_K_M, but its tensors say Q5_K — the
    parser reports what the file is.)

16. [Stella] Checkpoint and resume for training. CPU training runs
    for hours; a restart shouldn't mean starting over.
    **Status: ALREADY DONE** (no build). Engine resume with RNG
    restore, CLI --resume/--from-checkpoint, GUI Resume button
    and checkpoint picker, 16 tests — all pre-existing, verified
    in v0.24.0 (14 resume tests pass, incl. a tiny end-to-end
    pause/resume).

17. [Stella] [FIXED HERE] Clean up partial files on failure. A
    failed requant left a 197 MB partial.gguf behind.
    **Status: DONE in v0.24.0** (ported from the live install;
    partials removed on failure, empty output cleared).

18. [OST] Keep "not eligible" loud in the summary. Capability
    screening already records it right (never a failure) — make
    sure the summary shows it clearly so a model with ineligible
    templates doesn't read as broken.
    **Status: OST THREAD — not built here.**

## P3 — workflow and polish

19. [Stella] Doctor should give the fix that actually works. After
    a restart it flags the broken EGL library and says "run
    install.sh again", which doesn't fix it — the Qt library path
    does.
    **Status: DONE in v0.24.0** (the doctor diagnoses
    missing-library errors and names the system package + the
    exact install command, e.g. sudo apt install libegl1.
    Unmapped errors keep the old wording. The "Qt library path"
    fix named in the list is specific to the dev VM and is NOT
    in the product — see item 20.)

20. [Stella] Make the install survive restarts. Bundle the Qt
    libraries or wrap the launcher so the path is always set; the
    user shouldn't have to know about library paths.
    **Status: NO PRODUCT DEFECT — not built.** The restart
    problem (Qt libraries wiped) exists only on the dev VM,
    which wipes system packages on restart. On Joshua's Mint PC
    the system Qt libraries persist across restarts, and
    install.sh already checks the window starts. Bundling Qt
    libraries or sandbox paths into the product would be wrong;
    recorded here so the decision isn't re-litigated.

21. [Stella] Show live progress on long jobs. Distill, requant
    and training go quiet for minutes — show prompt 3 of 5, step
    X of Y, an ETA, so it doesn't look dead.
    **Status: DONE in v0.24.0** (requant streams the quantizer's
    per-tensor progress; train and distill terminal lines carry
    an ETA once enough units finished to measure a rate. The GUI
    distill job card already showed prompt N of M — verified,
    not built.)

22. [Stella] Translate tool errors into plain words. The raw
    llama error ("requantizing from type q4_K is disabled")
    means nothing to a normal user — say what went wrong and
    what to do.
    **Status: DONE in v0.24.0** (known errors lead with a
    plain-words explanation + what to do; the raw lines stay as
    detail, never hidden).

23. [Stella] Bridge from Ollama to training. Training refuses
    GGUF files and Ollama tags and needs the Hugging Face
    original — help the user get from the model they already
    have to the weights Stella needs.
    **Status: DONE in v0.24.0** (`stella bridge <tag>` suggests
    the HF repo for known models — curated, each repo verified
    on the Hub, the user confirms; never silently guessed.
    Models with no verifiable repo, e.g. bonsai-2, stay unknown
    rather than guessed. The train refusal now explains the
    problem and names the bridge command.)

24. [OST] One-command setup. The venv, temp-dir and port setup
    took manual fiddling — a setup script plus a README with the
    exact commands would save an hour.
    **Status: OST THREAD — not built here.**

## D1 — single-file Hugging Face defect (not in the pasted list)

From the Install Ollama thread's morning report, same morning
(2026-11-15); #2 in the combined file. The Hugging Face Hub API
returns size: None for EVERY sibling of a single-file model, so
`stella train` and --dry-run refused with "the size of its weights
could not be read" before training starts. It blocked training by
repo id entirely, including LFM3-1.7B — Stella's own documented
first target. Evidence: the training probe's
dryrun-1p5b-autoconfig.log shows the exact refusal for
Qwen/Qwen2.5-Coder-1.5B.
**Status: DONE in v0.24.0** (the remote metadata path resolves
each weight file's size with a HEAD request, ranged-GET fallback,
instead of trusting the siblings' size field. Verified live:
3,087,467,144 bytes for Qwen2.5-Coder-1.5B, exact match with the
SHA-verified local file.)

## Checked and NOT gaps

- Stella distill already saves each answer as it lands and resumes
  past answered prompts on a re-run (append mode +
  skipped_resumed).
- OST already has a Compare tab in the window (item 13 is headless
  only).
- OST already records decode speed per run (item 12 is
  per-template surfacing only).
