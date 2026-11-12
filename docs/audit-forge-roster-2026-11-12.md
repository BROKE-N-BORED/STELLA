# Stella Item 1 — Code Forge Roster Audit

**Date:** 2026-11-12 ~15:36–15:50 EST. **Auditor:** Arlo, Stella dev thread (2d7b2739).
**Machine:** HP All-in-One, Ryzen 3 3250U (2C/4T), 8 GB DDR4, CPU-only, 1 TB HDD, Linux Mint, Ollama, Forge context 8192.
**Sources:** `ollama list` screenshots verified 2026-11-09 (8 models) and 2026-11-12 ~15:49 (11 models — the 3 new pulls below); Sweep #2 report (2026-11-09/10, `~/workspace/research_notes/code-forge-model-sweep-2-20261110-0405/report.md`); HF 2B sweep (2026-11-12, `~/workspace/research_notes/huggingface-2b-models-sweep-20261112-0151/report.md`); Forge tree `~/workspace/code-forge-subtitle-build/forge/` (seats.py, governor.py, modelfit.py, providers.py, main.py). Benchmark figures are vendor-reported unless marked independent. No tok/s has ever been measured on Joshua's actual machine — every speed figure here is interpolated from other hardware. OLLAMA-SYSTEM-TEST v2 exists to measure it and has not been run on his PC yet; that is this audit's biggest honesty gap.

**CORRECTION — RESOLVED 2026-11-12 ~15:49 (fresh `ollama list` screenshot): the vision seat is FILLED with the right tag — `qwen3-vl:2b-instruct`, 1.9 GB, pulled 2026-11-11 ~22:49 from the emailed list (Gmail 1a1cdef768f039cd). The audit's original "empty" verdict used the stale 2026-11-09 list. The same screenshot shows two more new pulls: `qwen3.5:2b-q4_K_M` (1.9 GB, all-rounder, same night) and `qwen3.5:4b` (3.3 GB, pulled 2026-11-12 ~06:49). Roster is now 11 models; the table and gaps sections below are updated. Still unverified: whether the vision model has actually parsed an image inside Forge yet, and real tok/s for any model on this machine.

## Installed roster (verified 2026-11-12 — 11 models)

Total on disk ≈ 20.8 GB (disk is not the constraint — 1 TB HDD; RAM is).

| Model | Size | Seat | Verdict |
|---|---|---|---|
| maternion/minicpm5-heretic:2b | 2.7 GB Q8_0 | Driver | KEEP — tune-up candidate |
| dolphinlabs/qwen3.5-uncensored:latest | 2.1 GB Q8_0 | Reviewer | KEEP — contested, trial challenger |
| eriktonon/bonsai-2-uncensored:2b | 911 MB | Fast / tester | KEEP — re-pull pending |
| bonsai-2:4b (stock) | 1.2 GB | Control only, no seat | KEEP as control, or CUT if never benchmarked |
| lfm3:1.7b | 1.1 GB | Fast tool/test + understudy (trial) | KEEP — best first fine-tune |
| huihui_ai/granite4.1-abliterated:3b | 2.1 GB | Understudy / reviewer (trial) | KEEP on trial, no training yet |
| huihui_ai/qwen2.5-coder-abliterate:1.5b | 1.1 GB | Utility / snippets only | KEEP in its lane only |
| phi4-mini | 2.5 GB | None (rejected) | CUT |
| qwen3-vl:2b-instruct | 1.9 GB | Vision | KEEP — fills the seat, right tag |
| qwen3.5:2b-q4_K_M | 1.9 GB | All-rounder / vision backup | KEEP — consolidation candidate |
| qwen3.5:4b | 3.3 GB | Generalist (trial, Tight) | KEEP on trial — needs a real speed run |

## Per model

### 1. MiniCPM5 Heretic 2B — driver — KEEP, tune-up candidate
- Strengths: best 2B coding numbers published (LiveCodeBench v6 69.1, SWE-bench Verified 46.4, AIME 86.5, MMLU-Pro 70.8, BFCL v4 66.6 — vendor, exact figures contested between vendor tables, ranking stands). Abliterated (refusals 99→5/100 at KL 0.0391). 128K context. Standard Llama arch, stock Ollama.
- Weaknesses: Q8_0 is the slowest reasonable quant on this CPU — decode is memory-bandwidth bound, so Q8 moves ~70% more bytes per token than Q4_K_M (1.56 GB). Known runaway repetition under llama.cpp defaults (min_p=0.05); needs min_p=0. Residual refusals are SFT-baked and cannot be abliterated away without capability damage.
- Waste: the Q8_0 quant itself. Same weights at Q4_K_M = ~1.1 GB smaller, faster decode, more RAM headroom. Caveat: maternion's only tag is Q8_0 (unverified whether they offer Q4); a Q4_K_M heretic GGUF exists from another publisher (Abiray) but is unverified by us.
- Tune-up: (a) zero-training win first — trial Q4_K_M heretic + min_p=0, measure before any training; (b) fine-tune — LoRA on Forge's own tool-call traces to tighten structured-call compliance and Forge tool dialect. CPU feasibility: micro-LoRA only (rank 4–8, few hundred examples, checkpointed, hours); a real run needs a free cloud GPU.
- Note: do NOT make the driver the first Stella proof loop — highest value, hardest CPU train, biggest risk of a bad first result.

### 2. Dolphin Qwen3.5-uncensored — reviewer — KEEP, contested
- Strengths: full-weight Qwen3.5-2B, abliterated, Q8_0. Council-mode second opinion.
- Weaknesses: text-only (no vision). Known overthinking failure unless `/set nothink` is used. Its own page admits "No benchmarks were run." Only 1,743 pulls. Q8_0 slower than Q4.
- Waste: the challenger `huihui_ai/qwen3.5-abliterated:2B` is the same base at Q4 (1.9 GB), with vision+tools, ~732K pulls — strictly better on paper. The incumbent's Q8_0 + text-only + overthinking is dead weight against it.
- Tune-up: A/B trial vs the huihui challenger first (no training — the swap itself may be the tune-up). If the incumbent stays, LoRA for short structured critique format + nothink behavior baked in. CPU feasibility: micro-LoRA only.

### 3. Bonsai-2-uncensored:2b — fast / tester — KEEP, re-pull pending
- Strengths: 911 MB — fastest class on this machine. Abliterated (~99.37% refusal cut). Vision projector bundled since the 3 Nov 2026 listing update. BFCL v3 60.53, HumanEval+ 50.0.
- Weaknesses: knowledge weak (GPQA −18.9 vs its base). Vision documents weakest in family (OmniDocBench 55.64 vs 71.78 base, OCRBench v2 44.20). Measured MMLU ~32–34 (small sample). Publisher marketing ("0.0% hallucination") unverified.
- Waste: the installed copy predates the 3 Nov update and may lack the vision projector — re-pull advised since Sweep #2, not yet done (unverified).
- Tune-up: re-pull likely unnecessary now (installed copy dates ~Nov 5, after the Nov 3 listing update — see zero-training wins). Fine-tuning ternary weights is the least standard path on the roster (thin LoRA ecosystem for ternary) — not a first proof candidate despite its size.

### 4. bonsai-2:4b (stock) — control only — KEEP as control, or CUT
- Strengths: stock default, control/benchmark model. Base-family coding strong.
- Weaknesses: NOT abliterated — deliberately barred from governing seats (seats.py: "must stay absent"). Holds no seat. Overlaps the uncensored 2B for fast work.
- Waste: earns its disk only if benchmarks actually run against it. No benchmark against it recorded since install. Cutting frees 1.2 GB of disk only — RAM is unaffected (it only costs RAM when loaded) — so this is tidiness, not a performance fix. Say so honestly.

### 5. LFM3 1.7B — fast tool/test + understudy — KEEP, best first fine-tune
- Strengths: 1.1 GB, smallest dense model on the roster. Best published small-model tool scores (BFCL v4 71.39 vendor, unreproduced; IFEval 96.66; LiveCodeBench v6 73.46 vendor). Hybrid arch degrades gracefully at long context (only 6 of 24 layers full attention; ~24% decode loss 0→32K vs ~44% for MiniCPM5 in one independent iGPU test). Fast on weak CPUs (~8–15 tok/s interpolated on the 3250U — not a measurement).
- Weaknesses: NOT abliterated (stock) — cannot hold a governing seat. Liquid's own card says not recommended for agentic coding or complex multi-step reasoning. Vendor numbers unreproduced. Licence is LFM Open License v1.0 (free commercial use below $10M revenue — not Apache/MIT).
- Waste: installed but untrialled as a seat — no verdict from real use yet. Its 256K context is unused (Forge runs 8K — correct for RAM, not real waste).
- Tune-up: BEST first Stella proof candidate — smallest dense model, standard architecture, tool-calling is its strength. LoRA on Forge tool traces targeting short multi-step reliability. Most CPU-feasible fine-tune on the roster.

### 6. Granite 4.1-abliterated 3B — understudy / reviewer trial — KEEP on trial
- Strengths: purpose-built tool calling (BFCL v3 60.80), HumanEval 79–82, MMLU 67, IFEval 82.3. No thinking mode — predictable latency, a plus on this CPU. 128K context. Abliterated.
- Weaknesses: huihui calls its own edit "crude, proof-of-concept." An independent Heretic build of the same base reports KL 0.3042 — ~10× the drift of the MiniCPM5 heretic (0.0349), so expect capability cost from the abliteration. Dense 3B Q4 is slower than every 2B. Only 8,034 pulls. No CPU tok/s evidence.
- Waste: overlaps understudy + reviewer seats with LFM3 (faster) and Qwen3.5 (stronger reviewer). 2.1 GB for a seat it has not earned.
- Tune-up: do NOT LoRA to "repair" abliteration drift — retraining an abliterated model can re-teach refusals. Leave weights alone; tune via system prompt + seat assignment. If it earns reviewer-understudy, fine-tune for structured critique format only.

### 7. Qwen2.5-Coder-abliterate 1.5B — utility only — KEEP in its lane
- Strengths: HumanEval 70.7, MBPP 69.2. Sub-1.1 GB, very fast. Good short completion. Abliterated.
- Weaknesses: FAILED as driver (Trial #1, 2026-11-09) — emits bare fenced JSON as chat text instead of structured calls, a documented Qwen-family failure mode; its own template is correct, the model does not follow it. LiveCodeBench 14.6 — collapses on real multi-file tasks. 2024-era base, tag untouched since 25 Nov 2024.
- Waste: none while kept in its lane; the waste was the driver-trial time, already spent.
- Tune-up: the interesting Stella case — its failure is format compliance, exactly what a small LoRA on tool-call-format examples could fix, and at 1.5B it is the most CPU-feasible fine-tune of all. BUT its LCB 14.6 ceiling says it can never drive real agentic coding. Fine-tune only for snippet/completion format, never to chase the driver seat. Alternative first-proof candidate if Joshua wants the clearest before/after demo (fenced JSON → structured call).

### 8. phi4-mini — CUT
- Strengths: genuinely good reasoning per size (GSM8K 88.6, MATH 64, HumanEval 74.4, MMLU 67.3).
- Weaknesses: 3.8B dense, 2.5 GB on disk (3.1 GB loaded). 6.9 tok/s on an i5 laptop → low single digits on the 3250U. Stock (not abliterated). Cannot fill the reviewer seat in usable time.
- Waste: a roster slot + 2.5 GB for a model that cannot do its job in usable time. Hardened reject from two sweeps.
- Action: `ollama rm phi4-mini`. Frees disk, not RAM — the real saving is roster clarity and never picking it by accident.

## Gaps (seats with no model)

- **Vision seat — FILLED, right tag (VERIFIED 2026-11-12 ~15:49).** `qwen3-vl:2b-instruct`, 1.9 GB, pulled 2026-11-11 ~22:49. Still to do: first real image parse inside Forge. Direct weak-CPU evidence says budget minutes per screenshot and unload between calls (10 s to >3 min on a 2-core/8 GB box). Challenger if it disappoints: `lfm3-vl:2b` (1.5 GB).
- **All-rounder — INSTALLED 2026-11-11 night.** `qwen3.5:2b-q4_K_M` (1.9 GB, text+vision+thinking, MMLU-Pro 66.5, MMMU 64.2) is on disk. Stock (not abliterated), so no governing seat — but it covers vision backup + all-rounder duties, and it is the consolidation candidate if the dolphin reviewer loses its A/B.
- **4B generalist — INSTALLED 2026-11-12 morning.** `qwen3.5:4b` (3.3 GB, MMLU-Pro 79.1, GSM8K ~92). Stock, so no governing seat. Fits Forge's own math (need ≈ 4.1 GB at 8K ctx) but Tight in practice with the desktop + Ollama overhead. Needs a real speed run before it earns any seat — a 4B at low-single-digit tok/s helps nobody.
- **Math:** EXAONE Deep 2.4B (MATH-500 92.3) is watch-list only — no verified Ollama tag (community GGUF).
- **Raon-1 Nano:** chat/instruction + long-context candidate only; Forge fork integration in progress. Not part of this installed roster; no tuning until the integration lands and it trials.

## Forge-side waste (how Forge uses the models, not the weights)

- **Driver + reviewer Q8_0 quants** — the single biggest free win (see §1–2). Config/quant choice, not training.
- **Sampler:** driver loops under llama.cpp defaults; min_p=0 is a config fix.
- **Reviewer overthinking:** dolphin needs `/set nothink` — a prompt/config fix.
- **Context:** 8192 standard; KV ≈ 640 MiB at 8K (modelfit.py: 80 MiB/1K). Models with 128K–256K context are capped by design for RAM — not waste.
- **No measurements:** no tok/s ever measured on his machine for any model. OLLAMA-SYSTEM-TEST v2 (repo live, emailed) exists for exactly this and has not been run on his PC. Tune-up priorities should be re-checked after one real run.
- **Council cost:** council mode doubles turn time (driver + reviewer + revision). Worth it only if reviewer quality justifies 2× time — unmeasured.
- **Governing law is enforced in code** (seats.py BASE_ROSTER: exactly 3 pinned abliterated tags; stock bonsai-2:4b deliberately excluded). Any Stella fine-tune that lands in a governing seat must preserve abliteration — a fine-tune that re-teaches refusals breaks the seat. Stella must check this on export (refusal probe before/after).
- **Cloud seats (providers.py):** Groq (gpt-oss-120b/20b), Gemini (3.8/3.6-flash, 3.5-flash-lite), EXAONE (k-exaone_v2.5). EXAONE has no live key or live call yet. Cloud is out of Stella's scope except as a training venue (see below).

## Dead weight, summed up

- Roster dead weight: phi4-mini (cut); bonsai-2:4b (control-only — cut if never benchmarked); qwen2.5-coder as anything but utility.
- In-model dead weight: Q8_0 quants on driver + reviewer (Q4_K_M = same weights, ~40% less RAM traffic per token); thinking traces on the reviewer (nothink); unused 128K–256K context (RAM-capped by design — not real waste).
- The honest totals: cutting phi4-mini + bonsai-2:4b frees ~3.7 GB of disk on a 1 TB drive — tidiness, not speed. The real performance wins are the Q4 swaps, the sampler/prompt fixes, and filling the vision seat.

## Zero-training wins (do these before or alongside Stella — Forge/terminal actions, not Stella builds)

1. Trial Q4_K_M heretic as driver (Abiray GGUF, unverified publisher — verify first) + min_p=0.
2. Trial `huihui_ai/qwen3.5-abliterated:2B` against the dolphin reviewer.
3. ~~Re-pull `eriktonon/bonsai-2-uncensored:2b`~~ — LIKELY UNNECESSARY: the installed copy dates to ~Nov 5, after the Nov 3 listing update, so it probably already has the projector; and the vision seat is filled now anyway. Skip unless a vision test says otherwise.
4. `ollama rm phi4-mini`.
5. ~~Pull `qwen3-vl:2b-instruct` for the vision seat~~ — DONE + VERIFIED 2026-11-12 (instruct build, 1.9 GB). Still to do: first real image parse inside Forge.
6. Run OLLAMA-SYSTEM-TEST v2 on his PC — one real measurement beats every interpolation in this report.

## Stella proof-loop recommendation

- **First fine-tune: LFM3 1.7B** — smallest dense model, tool-calling is its strength, most CPU-feasible LoRA. Target: Forge tool-call format + short multi-step reliability. Seat it earns: fast tool/test executor.
- **Alternative first proof: Qwen2.5-Coder 1.5B format fix** — smallest model of all, clearest before/after (fenced JSON → structured call), but the ceiling is the utility seat.
- **Do NOT start with the driver** — highest value, hardest CPU train, biggest risk of a bad first result.
- **CPU feasibility (honest):** micro-LoRA (rank 4–8, few hundred examples, 1.5–1.7B models) is feasible on CPU, checkpointed, over hours — Stella must support resume/checkpointing. A full fine-tune of a 2–2.5B model on this CPU is not feasible in reasonable time; that needs a free cloud GPU (Colab/Kaggle free tier — Groq/Gemini/Cloudflare do not train). Stella's export step must also accept adapters trained elsewhere.
- **GGUF round-trip (core Stella engineering):** Ollama models are GGUF; fine-tuning needs HF transformers + PEFT, then conversion back to GGUF (llama.cpp convert + quantize). Stella must own that pipeline or it cannot ship a usable Ollama model. That is the heart of Items 2–3.
- **Abliteration guard:** any fine-tune bound for a governing seat must pass a refusal probe before/after — training must not re-teach refusals. Build the probe into Stella's export check.

## What this audit did NOT do

- No model was installed, removed, pulled, or re-pulled. No Forge setting was changed. No training was run. All verdicts are recommendations for Joshua to direct, one item at a time.

## Follow-up (Joshua, 2026-11-12 ~15:53)

- Vision model so far is just the pull — no image parsed in Forge yet.
- Once OLLAMA-SYSTEM-TEST measures each model, he wants to RENAME the models properly by what each is best for, so the 11-model roster stops being confusing. That rename is the payoff of the test run: measured capability + speed per model → a clear name per seat. Stella's profiles should carry those role names when Item 2 lands.
