# Stella review task list — 2026-11-19 (v0.34.0)

Status: ALL 83 TASKS OPEN — none started. This list comes from the full-product review of Stella v0.34.0 (commit 64269ca8). The full report is in docs/review-2026-11-19.md.

The review produced 85 findings (0 P0, 18 P1, 37 P2, 30 P3). Two pairs of findings were merged into single tasks because they share one fix (chat repo-confirm: CH-F1 + CH-F8; base-name size fallbacks: NW-F3 + NW-F13), giving 83 tasks: 18 P1, 37 P2, 28 P3. Every finding is covered by exactly one task.

Each task gives: the title, the priority, what is wrong and why it matters, and a pointer to the evidence (file and line, screenshot, or probe) in the review working notes under ~/workspace/stella-review-2026-11-19/.

## P1 — a real user hits it and is stuck, misled, or handed jargon or a dead end

### N1. Requant reads almost every real model's quant wrong (its type table is shifted by one), so the shown quant, the size estimate, and the double-quant warning are all wrong

- **Priority:** P1
- **Source finding(s):** PI-F1 (audit-pipelines.md)
- **What and why:** stella/requant.py's GGUF tensor-type table omits Q8_1 (real ggml id 9), so every id from 9 up is mapped one type too high: a real Q4_K model (Stella's own default output) reads as Q5_K, Q5_K as Q6_K, Q8_K as a 2-bit type. The source quant shown to the user is wrong, the disk estimate is computed from the wrong bits-per-weight, and for Q8_K models the byte-vote can be won by F32 tensors so the source reads as F32 and the double-quant warning is silently suppressed. The existing tests encode the same wrong table, so the suite passes while real files misread. Fix: correct the table to the real ggml enum and fix the test fixtures to use real ids.
- **Evidence:** stella/requant.py:70-80; pipeline probe 4 (crafted headers with real ggml ids: 12 -> 'Q5_K', 15 -> 'IQ2_XXS', Q8_K-dominant file -> 'F32'); upstream ggml.h enum cross-checked. Audit: audit-pipelines.md PI-F1.

### N2. The live Hugging Face lookup offers models that are not the model you picked

- **Priority:** P1
- **Source finding(s):** GA-F1 (audit-gui-a.md)
- **What and why:** For a tag the bridge map leaves unverified (dolphinlabs/qwen3.5-uncensored:latest), the real Hub lookup returned three unrelated repos (two DeepSeek-V4-Pro-Qwen3.5 heretic builds at 9B/4B and a DavidAU Qwen3.5-9B) and the window would ask 'Stella found X on Hugging Face for this model. Use it?' — a plain-words promise that the repo IS this model. One tap on Yes downloads a stranger's weights (9B, on an 8 GB PC) and training proceeds on them. The offerable check only requires config.json plus a .safetensors file; nothing checks the repo is the searched model, and the first search rung accepts whatever the Hub's fuzzy search returns. Fix: only offer repos whose name actually matches the model's name (exact or near-exact); otherwise fall through to the next rung or the honest 'none' ending.
- **Evidence:** scratch/gui-a/real-hub-dolphin.log (two identical real lookups, coordinator re-read); stella/hub_lookup.py:159. Audit: audit-gui-a.md GA-F1.

### N3. A report card for a different model is applied as this model's strengths

- **Priority:** P1
- **Source finding(s):** NW-F1 (audit-newcode.md)
- **What and why:** report_cards.parse_ost_card only checks the model match on multi-model files. The shape OST actually writes — one file per test — returns early without ever comparing the file's model field to the profile, and the list-of-files shape is likewise accepted unchecked. Proven on real files: all 164 parseable OST result files also 'parse' under a deliberately wrong model hint, and end to end, a bonsai-2 card attached to an LFM3 profile is listed as an OST card and its score shows as LFM3's strength — the opposite of the v0.32.0 promise 'flagged, never applied'. Fix: enforce the model match for the single-file and list shapes too (mismatch lists as a stored, unread card).
- **Evidence:** stella/report_cards.py:197-208, 232-243, 262-282; newcode probe_all section A (175 real files) and probe2 section H end-to-end. Audit: audit-newcode.md NW-F1.

### N4. Attaching a model's whole OST run shows strengths from one test only, not the whole run

- **Priority:** P1
- **Source finding(s):** NW-F2 (audit-newcode.md)
- **What and why:** OST's real on-disk shape is one file per test, and the window attaches one file per pick — but strengths_from_cards takes only the single newest OST card whole, never merging tests across the attached cards. Proven for all 11 real models: attach every result file and the profile shows 'Not good at: reading long documents' and no strengths at all — whichever test ran last is long_context. The same data aggregated in OST's own PROFILE.md gives LFM3 9 strengths and 4 weaknesses. The card display also silently overrides the built-in table with this one-test verdict. Fix: merge per-test evidence across all attached OST cards for the profile, newest result per test winning.
- **Evidence:** stella/report_cards.py:545-555; newcode probe_all section B (all 11 models) vs ~/workspace/ollama-live-run/ost/results/lfm3_1.7b/PROFILE.md. Audit: audit-newcode.md NW-F2.

### N5. A passed refusal probe keeps passing after the model is retrained or its base is changed

- **Priority:** P1
- **Source finding(s):** EN-F1 (audit-engine.md)
- **What and why:** The governing-seat gate (closed item R4) checks that a passed probe_results.json exists, but never checks the result belongs to the adapter being exported now: require_passed_probe reads the saved numbers only, and training replaces the adapter without invalidating the file. Probe a tune, pass, force-retrain it into a never-probed adapter — or even change the profile's base model — and Export GGUF still passes on the stale pass. The gate is enforced in every export path; what it enforces can be stale. Fix: invalidate probe_results.json when a run finishes training a new adapter, and/or refuse a result whose recorded base differs from the profile's current one or that predates the adapter.
- **Evidence:** stella/probe.py:573 (require_passed_probe); stella/train.py:2889-2892; engine probe2_stale_gate.py output (gate passed again after retrain + base change). Audit: audit-engine.md EN-F1.

### N6. Requant deletes its only copy of the smaller file after an Ollama create it never checked

- **Priority:** P1
- **Source finding(s):** PI-F3 (audit-pipelines.md)
- **What and why:** Requant takes 'ollama create' success from the exit code alone; nothing checks the new tag actually exists in Ollama afterwards, and the work dir — the only copy of the smaller file — is then deleted. A create that exits 0 without registering the model (wedged or partial Ollama state) leaves the user told to run a model that does not exist, with the smaller file gone. gguf.create_in_ollama has the same exit-code-only pattern, though there the GGUF stays on disk. Fix: verify the new tag is installed (list/show) before deleting the work dir; on a failed check keep the file and say so.
- **Evidence:** stella/requant.py (create step + cleanup); pipeline probes E and F (no-op ollama exiting 0 -> full success report, work dir deleted). Audit: audit-pipelines.md PI-F3.

### N7. Distill reports success when every prompt in the run failed, as long as an old dataset file has 2 rows

- **Priority:** P1
- **Source finding(s):** PI-F2 (audit-pipelines.md)
- **What and why:** Distill's final gate loads the whole distilled.jsonl — including stale rows for prompts not in the current file — and if that total is 2 or more, the run returns a normal report, emits 'done', and re-points the project at the dataset, even when this run asked 0 prompts successfully. The user is told a dataset is ready that contains none of what they just asked for. Fix: base the gate on rows for the current run's prompts; when this run produced no new kept rows and had failures, refuse (or at least do not update the dataset pointer or emit done).
- **Evidence:** stella/distill.py:309-321; pipeline probe J (teacher failed all 3 prompts, 2 stale rows -> success report, dataset_ref updated). Audit: audit-pipelines.md PI-F2.

### N8. Chat can announce 'all done' for a plan whose steps failed

- **Priority:** P1
- **Source finding(s):** CH-F3 (audit-chat.md)
- **What and why:** In chat, tool failures come back as ordinary text results; the agent loop never marks a step failed, never blocks the next step, and returns the model's final claim verbatim. Probed: setting the dataset failed (the dataset stayed unset), the model replied 'All done! Your training finished and the model is exported and backed up', and that sentence is what the user got. The real template step is derived from store state but is only used for narration, never to check the final claim. Fix: track tool failures inside one reply and, if any tool failed, append or force a plain-words 'what did not work' line in the final reply.
- **Evidence:** stella/chat_agent.py reply loop (~877-945); chat probe P6. Audit: audit-chat.md CH-F3.

### N9. Chat can set a model's repo with no user yes at all — and a bare 'confirm' loops forever

- **Priority:** P1
- **Source finding(s):** CH-F1 + CH-F8 (audit-chat.md)
- **What and why:** The chat bridge/hub confirm gate is just a 'confirm: true' flag plus a candidate repo name in the model's own tool call; no state records that an offer was ever shown to the user. Probed: on the first-ever call for a fresh profile, a tool call carrying confirm+repo set base_ref and proceeded to download — the v0.30/v0.33 promise 'never silently sets a repo' holds only if the model behaves. The mirror flaw: with exactly one candidate, a confirming call that omits the repo name (a faithful relay of the user's 'yes') gets the identical offer again, looping until the 12-call cap. Fix: keep a pending-offer flag on the agent session and only honour confirm after an offer was actually returned; let confirm alone confirm a single candidate.
- **Evidence:** stella/chat_agent.py:1145-1154 (coordinator re-read); chat probes P7 and P8. Audit: audit-chat.md CH-F1, CH-F8.

### N10. Chat runs the whole plan when the user says 'yes, but not yet' or 'go ahead and do something else'

- **Priority:** P1
- **Source finding(s):** CH-F2 (audit-chat.md)
- **What and why:** Plan approval matches any message starting with 'yes ' or 'go ahead', and approval is checked before refusal. Probed: both 'yes but not yet' and 'go ahead and do something else entirely' consumed the pending plan and injected the synthetic 'Run the plan we agreed on' instruction — the user gets the opposite of what they said, potentially starting training or downloads. Fix: approve only on an exact approval phrase, or check negation words ('not', 'cancel', 'wait') before the prefix matches.
- **Evidence:** stella/chat_agent.py:95-104, :808; chat probe P9. Audit: audit-chat.md CH-F2.

### N11. The main screen permanently tells the user to change training settings from the terminal

- **Priority:** P1
- **Source finding(s):** GB-F1 (audit-gui-b.md)
- **What and why:** With any project selected, the session summary at the top of the main window permanently reads 'Training settings are changed from the terminal: stella update-project ... --seed 7', and the Project window's Details repeats it. The standing rule (2026-11-18, after the last review closed) is no terminal for the user, ever; this line predates the rule and now conflicts with it — it tells a click-only user the only way to change settings is a place they cannot go. The design brief's answer is that the backend sets settings silently and nothing is shown. Fix: drop the terminal line from both surfaces; if a hint is needed, say the settings are picked for this PC automatically.
- **Evidence:** shots/gui-b/03-main-session-selected.png, 40-export-success-card.png; stella/gui.py:6691 and :3030. Audit: audit-gui-b.md GB-F1.

### N12. The 'training packages missing' message names Python packages, a terminal command, and a panel that does not exist

- **Priority:** P1
- **Source finding(s):** GB-F2 (audit-gui-b.md)
- **What and why:** Pressing Go for Train or Sleep without the training stack pops: 'Training packages missing: torch, transformers, peft, accelerate... Install them by pressing Install training in the Train panel, or by double-clicking Install Stella Training in the Stella folder. It downloads about 2 GB. In a terminal: bash install-training.sh'. Four package names mean nothing to the target user; the message ends by handing them the terminal command the GUI button exists to replace; and there is no labelled 'Train panel' — the Install training button is on the main screen, so the one GUI direction given names a place the user cannot find. Fix: plain words ('Training is not set up on this PC yet'), one direction — the Install training button on this screen — no package names, no terminal line.
- **Evidence:** shots/gui-b/21-sleep-after-go.png, 65-offline-train-go.png; stella/train.py:60. Audit: audit-gui-b.md GB-F2.

### N13. The export probe-gate refusal is unexplained jargon plus a terminal command, and following it loops

- **Priority:** P1
- **Source finding(s):** GB-F3 (audit-gui-b.md)
- **What and why:** For a governing-seat profile, Export GGUF refuses with 'profile ... is bound for a governing seat, so it cannot be exported until its refusal probe passes. Run the refusal probe first (Run refusal probe in the Train panel, or stella probe ...)'. 'Governing seat' is never explained anywhere this user has been; the alternative offered is a terminal command; and following the GUI direction loops — the probe itself refuses ('has no trained adapter yet') — so an untrained governing profile can neither export nor probe, and neither message names the actual first step (train first). The gate itself holds; the finding is the message and the loop. Fix: plain words ('This model has a safety check to pass before it can be exported'), the one next step that works from this state, no CLI alternative.
- **Evidence:** stella/gui.py:10736-10747; stella/probe.py (require_passed_probe wording); gui-b drive2 log. Audit: audit-gui-b.md GB-F3.

### N14. When Stella cannot start, its failure popup tells the user to run a terminal command and never names the double-click fix

- **Priority:** P1
- **Source finding(s):** IN-F2 (audit-installer.md)
- **What and why:** When Stella is launched from the menu with no terminal and the install is missing or broken, run.sh's dialog — precisely the no-terminal situation — says only 'Stella is not installed yet. Run: bash install.sh (from the Stella folder)'. A click-only user cannot act on that, and 'the Stella folder' is unnamed. A click fix exists (double-click Install Stella in the extracted folder) but the dialog never mentions double-clicking anything. Fix: name the click action in the dialog text first; keep the bash form only as a secondary line.
- **Evidence:** run.sh:46 and :53; installer scratch run captured the message verbatim (scratch/inst/run_fail.log). Audit: audit-installer.md IN-F2.

### N15. Uninstall leaves the ~2 GB training wheel cache behind and says removal is finished

- **Priority:** P1
- **Source finding(s):** IN-F1 (audit-installer.md)
- **What and why:** install-training.sh downloads the training wheels into ~/.cache/stella/wheels (about 2 GB). uninstall.sh never mentions that directory: it offers to remove the pip cache (the older R116 fix) but not Stella's own wheel cache, and its closing lines say deleting the folder 'finishes removing it' — a completeness claim that is false for anyone who ever installed training. The README's Remove section makes the same omission. Proven in scratch: a seeded wheel file survived a full uninstall, unmentioned. Fix: give the wheel cache the same treatment as the pip cache (offer, default No, over a size threshold) and name it in the closing summary either way; update the README to match.
- **Evidence:** uninstall.sh (only the pip-cache block at :158-190); install-training.sh:88; installer scratch uninstall run. Audit: audit-installer.md IN-F1.

### N16. The CLI's sleep-delete and sleep-prune delete sleep cycles for good with no 'are you sure?' and no --yes flag

- **Priority:** P1
- **Source finding(s):** CL-F1 (audit-cli.md)
- **What and why:** Every other permanent delete on the CLI asks first, defaulting to No (delete-checkpoint, prune-checkpoints, delete-profile --purge, delete-project --purge), and the window's sleep-cycle delete confirms with the size shown. The two CLI sleep commands are the exception: they call the engine directly — no confirm, and the parser gives them no --yes flag at all. A typo'd cycle number or profile/project pair that happens to match deletes adapters permanently the instant Enter is pressed. Fix: route both through the same confirm helper with a --yes escape, exactly like delete-checkpoint.
- **Evidence:** stella/cli.py:2124 and :2139 (no confirm call); CLI evidence 01-all-help.txt and 06-confirms2.txt; window confirm at stella/gui.py:10592. Audit: audit-cli.md CL-F1.

### N17. A sleep cycle interrupted during its first checkpoint save can never sleep again, and the error names the wrong problem

- **Priority:** P1
- **Source finding(s):** EN-F2 (audit-engine.md)
- **What and why:** Sleep decides a resumed cycle has checkpoints by counting ANY entry in the cycle's checkpoints folder — including a crashed save's step-N.tmp folder. It then resumes training, whose own checkpoint list (which correctly ignores those folders) is empty, so the run dies with 'nothing to resume. This project has no checkpoints yet' — wrong twice (there IS a checkpoint folder; it is a sleep cycle, not 'this project'), and permanent: every later sleep run hits the same wall, and nothing tells the user the cycle folder is the problem or that deleting it is the way out. Fix: base the has-checkpoints decision on the real checkpoint list, so a tmp/orphan-only folder restarts the cycle's consolidation instead of refusing.
- **Evidence:** stella/sleep.py:956 (coordinator re-read); engine probe4_sleep_tmp.py output. Audit: audit-engine.md EN-F2.

### N18. How to Use Troubleshooting sends the user to a button that is not there, and back to the manual Hugging Face hunt (with the exact wrong-repo example)

- **Priority:** P1
- **Source finding(s):** DC-F1 (audit-docs.md)
- **What and why:** The Troubleshooting topic says 'Weights missing. Open the profile and press Download model. If Stella does not know the model's Hugging Face repo yet, it says so: find the model on huggingface.co and set the Hugging Face repo in the profile window, for example LiquidAI/LFM3-1.7B.' Three faults: the profile window's button is 'Download the training files' ('Download model' is the main-window button), so the user hunts a window for a button not in it; since v0.33.0 Stella searches Hugging Face itself, so the manual hunt is only the last-resort ending, not the normal path the topic presents (the guide's own Profiles topic says so correctly); and the example it tells the user to type is the exact repo whose presence in the wrong profile the v0.30.0 mismatch guard exists to catch — Joshua already typed that old example into his Granite profile once. Fix: rewrite the paragraph with the real button names, the automatic lookup first, manual entry last, and no typed example repo.
- **Evidence:** stella/howto.py:461-464 vs the correct text at :165-167; buttons at stella/gui.py:1790 and :5483. Audit: audit-docs.md DC-F1.

## P2 — friction, clutter, inconsistency

### N19. The no-repo ending from Download sends the user hunting by hand and does not open the profile window, while the other path into the same ending does

- **Priority:** P2
- **Source finding(s):** GA-F2 (audit-gui-a.md)
- **What and why:** Pressing Download for a model with no findable repo (bonsai-2) ends in a warning telling the user to find the model on huggingface.co and set the repo in the profile window themselves — for bonsai-2 no trainable repo exists to find — and then leaves them on the main window. The 'Set the model source...' path through the same wall DOES open the profile window when the lookup fails, so the two routes behave differently and the helpful behaviour exists on only one button. Fix: make the Download path end the same way — open the profile window after the honest message.
- **Evidence:** shots/gui-a/09-bonsai-unknown-ending.png, 10-bonsai-after-ending.png; stella/gui.py:7662 vs :7666. Audit: audit-gui-a.md GA-F2.

### N20. A Step cap number sits on the main screen — a training setting the brief says should not be there (plus pre-set numbers in export, prune, and distill)

- **Priority:** P2
- **Source finding(s):** GB-F4 (audit-gui-b.md)
- **What and why:** The brief's named settings (rank, learning rate, epochs, batch size, sequence length) are genuinely nowhere in the GUI — verified on every screen. But the main screen carries a 'Step cap' spinbox that decides how long a training run goes, and the same pattern repeats smaller: the GGUF Quant combo pre-selected to Q4_K_M, checkpoint and sleep 'Keep newest' spins pre-set to 3, the distill wait pre-set to 300 seconds. Each is explained in plain words, so none is a trap; together they are a slow creep back toward a settings panel. Fix: fold Step cap into the existing Proof run idea (a 'short run' choice, not a number) or move it off the main screen; leave the defaults working silently.
- **Evidence:** shots/gui-b/03-main-session-selected.png, 24-distill-dialog.png; stella/gui.py:5686-5687, :5847. Audit: audit-gui-b.md GB-F4.

### N21. Chat with Ollama down contradicts itself: it says pick a model in Settings, then treats typed text as a model name and suggests a cloud model the user cannot use

- **Priority:** P2
- **Source finding(s):** GB-F5 (audit-gui-b.md)
- **What and why:** Offline, the Chat window correctly says Ollama is not answering and to pick a chat model in Settings. But the input box stays live as a model-name box: typing anything ('hello') gets 'Stella: I did not find that model. Type the full model name, for example openai/gpt-oss-120b.' The window's two messages disagree, and the example is a cloud model the user has no key for — typed chat text can never succeed in this state. Fix: in the no-models state, disable the input with the Settings direction, or treat typed text as a cloud pick only when a key exists; never exemplify a model the user cannot pick.
- **Evidence:** shots/gui-b/61-offline-chat.png, 62-offline-chat-sent.png; stella/gui.py:4367-4372. Audit: audit-gui-b.md GB-F5.

### N22. Chat permanently shows 'Step 4 of 8: Recipe.' — a step from a list the user never sees, in words never explained

- **Priority:** P2
- **Source finding(s):** GB-F6 (audit-gui-b.md)
- **What and why:** The Chat window permanently shows a step line such as 'Step 4 of 8: Recipe.' for a project that has only just been created. Nothing in the window lists the 8 steps, says what a 'Recipe' is, or why a brand-new project is already on step 4. It is the one piece of persistent chrome in the chat, it uses internal template vocabulary, and a first-time user cannot act on it. Fix: name steps in the user's words and make the line open the list, or drop the step line from the chat window.
- **Evidence:** shots/gui-b/61-offline-chat.png, 75-chat-exchange.png; stella/chat_agent.py:404-409. Audit: audit-gui-b.md GB-F6.

### N23. At 1366x768 the main window is one ~2,020 px scroll and the export/probe buttons sit far below the fold behind tall empty sections

- **Priority:** P2
- **Source finding(s):** GB-F7 (audit-gui-b.md)
- **What and why:** The session page measures about 2,020 px tall at his screen size. The hero and 'How it is going' fill the first screen; Dataset, Run overrides, Checkpoints (which holds Export GGUF, Put it in Ollama, Run refusal probe, View probe results), Past runs, Training log and Sleep cycles stack below, several as tall empty list boxes before anything exists. The finish actions for a trained project require a long scroll hunt through empty sections — the one-window crowding the core design rule warns about, softened but not solved by collapsible headers that all start open. Fix: start the empty sections collapsed, or move the export/probe actions up beside the job card where the run finishes.
- **Evidence:** shots/gui-b/03-main-session-selected.png, 04-main-scroll-0.png, 04-main-scroll-2.png; drive1 scroll measurements. Audit: audit-gui-b.md GB-F7.

### N24. 'Estimate unavailable.' gives no reason and no next step, and the Estimate button answers with repo jargon plus a terminal command

- **Priority:** P2
- **Source finding(s):** GB-F8 (audit-gui-b.md)
- **What and why:** For a profile whose base is an Ollama tag, the panel's estimate line reads only 'Estimate unavailable.' Pressing Estimate pops a warning about Hugging Face vs Ollama ending 'Run this to see the suggestion again: stella bridge lfm3:1.7b'. The one dry-run offered to a cautious user either says nothing or speaks in repo/tag terms plus a CLI command; the helpful fact — there is a working 'Set the model source...' button right there — is never connected to the estimate. Fix: the estimate line carries the reason and points at the Set the model source button; no CLI line in the modal.
- **Evidence:** shots/gui-b/09-main-after-estimate.png; stella/gui.py:6836-6872; gui-b drive1 log. Audit: audit-gui-b.md GB-F8.

### N25. Probes run from chat are saved as 'gate' runs even for models that hold no seat, so the results window later shows a gate verdict that was never a gate

- **Priority:** P2
- **Source finding(s):** EN-F3 (audit-engine.md)
- **What and why:** The window and the CLI both compute informational mode from the governing-seat check and pass it to the probe; the chat tool never passes it, so every chat-run probe is saved stamped mode 'gate' — and the chat reply appends a gate verdict for profiles whose probe is supposed to be informational. The probe-results dialog reads the mode back from the saved file, so a chat-run probe on a utility or vision profile later displays a gate verdict it should never have had. Fix: have the chat probe tool compute informational mode exactly like the CLI does and pass it through.
- **Evidence:** stella/chat_agent.py:1304 vs stella/gui.py:~10991 and stella/cli.py:~1843; mode recording in stella/probe.py. Audit: audit-engine.md EN-F3.

### N26. The refusal judge scores two plainly compliant answers as refusals

- **Priority:** P2
- **Source finding(s):** EN-F4 (audit-engine.md)
- **What and why:** Two new edge cases misjudge in is_refusal: (1) 'Nope, that's a myth — here's the truth: the sky looks blue because of scattering.' scores REFUSAL — the whole reply is one sentence, 'nope' is a strong marker, so the sentence is skipped by the compliance check and no second sentence exists to save it. (2) 'No. The capital of France is Paris.' scores REFUSAL — the bare 'No.' counts as a refusal and the factual second sentence holds no stock compliance phrase. A terse model — exactly the fast seat's style, whose probe set is full of one-line factual questions — can score refusals for correct answers, inflating the after-rate and failing a good tune at the gate. Fix: treat a bare-No opening as a refusal only when no later sentence actually answers, or soften 'nope' when the same sentence carries a compliance phrase and no refusal verb.
- **Evidence:** engine probe1_refusal.py output (both lines True, controls correct); stella/probe.py is_refusal. Audit: audit-engine.md EN-F4.

### N27. Dreaming that produces nothing usable is reported as if it worked, and no dream outcome or skip reason is saved in the cycle report

- **Priority:** P2
- **Source finding(s):** EN-F5 (audit-engine.md)
- **What and why:** When Ollama answers but every dreamed line is unusable (not JSON, fails validation, all duplicates), dream_rows returns 'ran, kept 0' — indistinguishable from a model that legitimately dreamed only duplicates — and the user who asked for dreamed rows is never told the output was garbage. And even when dreaming IS skipped (Ollama unreachable, no model tag), the reason exists only as a live event: the cycle's report.json has no dream field at all, so afterwards, in the report the user can reopen, a skipped or garbage dream is invisible. Fix: return a note when generation succeeded but zero rows survived validation, and record the dream outcome (ran / skipped + reason / kept count) in report.json.
- **Evidence:** engine probe3_dream_multiturn.py output; stella/sleep.py:571, :878-888, :1016. Audit: audit-engine.md EN-F5.

### N28. The --steps cap is honoured by the training loop but ignored by the disk guard and the dry run, so a 5-step proof run can be refused for a full run's checkpoints

- **Priority:** P2
- **Source finding(s):** EN-F6 (audit-engine.md)
- **What and why:** The loop caps correctly, but train_project's disk guard computes total steps from the full epochs schedule with no reference to max_steps, and the estimate/dry run has no steps parameter at all. A short proof run (--steps 5) is therefore disk-judged — and can be refused — for checkpoints from a full multi-epoch run it will never write, and its dry-run 'Disk:' line quotes the uncapped figure; the refusal then tells the user to free space or delete checkpoints for a run that needed neither. Fix: thread max_steps into the disk-guard step count and into the estimate when the caller has one, mirroring the loop's own rule.
- **Evidence:** stella/train.py:3311-3340 vs :2671-2674; stella/cli.py:1544-1554. Audit: audit-engine.md EN-F6.

### N29. The merge RAM guard judges only the fixed 8 GB ceiling, never the RAM actually free; the replay check and the probe load the base with no RAM check at all

- **Priority:** P2
- **Source finding(s):** EN-F7 (audit-engine.md)
- **What and why:** Training's guard was recalibrated in the v0.24.0 work to judge against the RAM free right now, because Ollama holding models is the normal state of his PC. The merge guard was not: it has no available-RAM input at all. For a 1.7B base the merge estimate is ~7.9 GB — under the ceiling, so it proceeds — even if Ollama is holding several GB and only ~3 GB is free, ending in a mid-merge out-of-memory kill after hours of training instead of an up-front refusal. The sleep replay check and the probe likewise load the base with no fit check first. Fix: give the merge guard the same available-RAM tightening as training's, and add a metadata-based fit check before the replay/probe base loads.
- **Evidence:** stella/gguf.py:189-213; grep: no RAM-guard symbols in stella/sleep.py or stella/probe.py. Audit: audit-engine.md EN-F7.

### N30. Distill's 'the teacher was slow, not down' wording never fires on the real path (a regression of the closed R30 fix)

- **Priority:** P2
- **Source finding(s):** PI-F4 (audit-pipelines.md)
- **What and why:** Distill rewords a teacher failure to 'slow, not down' only when the error text contains 'timed out'. But the real teacher path deliberately strips raw exception text and raises exactly 'Ollama did not answer. Is Ollama running on this PC?' for a timeout too. So a teacher that merely exceeded the per-prompt timeout is reported as Ollama possibly not running — the precise misattribution the closed R30 item was fixed for. The unit tests inject the old '(timed out)' wording, so they pass while the real path is dead. Fix: keep a timeout marker in the real path's plain message, or let distill detect the timeout from the exception chain.
- **Evidence:** stella/distill.py:103-119; stella/ollama.py generate_full error branch; pipeline probe 5 (slow local server). Audit: audit-pipelines.md PI-F4.

### N31. Requant's Ollama create has no timeout, unlike every other step — a hung create hangs requant forever

- **Priority:** P2
- **Source finding(s):** PI-F5 (audit-pipelines.md)
- **What and why:** Requant passes timeout=None for its create step (the code comment acknowledges it as a leftover). The quantizer in the same file has the 30-minute bound, and the same create operation in the GGUF pipeline got one too — both its CLI and window callers pass it. A hung create (Ollama wedged while copying a multi-GB blob on a hard drive) therefore hangs requant indefinitely; the chat-agent caller passes no stop flag either, so that path has no bound and no cancel at all. Fix: give requant's create the same 30-minute bound as the GGUF pipeline's.
- **Evidence:** stella/requant.py:949-956; contrast stella/cli.py:1793-1798 and stella/gui.py:10946-10951. Audit: audit-pipelines.md PI-F5.

### N32. Convert and quantize outputs are never checked to actually be GGUF files before being reported ready

- **Priority:** P2
- **Source finding(s):** PI-F6 (audit-pipelines.md)
- **What and why:** Convert checks only that the output file exists after each step; requant checks existence plus non-zero size. Neither reads the 4-byte GGUF magic — a check the same codebase already performs on inputs. A tool that exits 0 having written garbage (or the wrong file) is reported as a ready GGUF, registered into Ollama, and only fails later, somewhere else, with an error that points at the wrong step. Fix: read the first 4 bytes of converter/quantizer output and require 'GGUF' before reporting success.
- **Evidence:** stella/gguf.py convert_to_gguf checks; stella/requant.py output checks; pipeline probe C (shape of the gap). Audit: audit-pipelines.md PI-F6.

### N33. The bridge offers another size's weights labelled as this model's own repo, and the strengths table likewise gives one size's measured strengths to other sizes

- **Priority:** P2
- **Source finding(s):** NW-F3 + NW-F13 (audit-newcode.md)
- **What and why:** The bridge's version-stripped fallback has no size check: where a family has one curated entry, any other size of that family is offered that entry's repo — qwen2.5-coder:7b and :32b are offered the 1.5B repo, lfm3:9b the 1.7B repo, granite:8b the 3B base — with the source text claiming it is 'this model's own repo' and the dialog defaulting to Yes, so one Enter downloads gigabytes of the wrong model's weights and training proceeds on them. The strengths table has the same shape in display form: its base-name fallback returns the 1.7B model's measured strengths for lfm3:9b, where the honest answer is 'Not measured yet' (its ambiguity guard works only where two entries exist). Fix: require a size match on both base-name fallbacks (the mismatch guard already computes a size hint); otherwise offer nothing and let the live lookup or the honest-unknown path run.
- **Evidence:** stella/ollama_bridge.py:96-105; stella/strengths.py:139-152; newcode probe_all section C (seven wrong-size offers listed). Audit: audit-newcode.md NW-F3, NW-F13.

### N34. The mismatch guard only runs at download time — never before training on already-downloaded weights — and it re-warns forever after the user deliberately keeps a repo

- **Priority:** P2
- **Source finding(s):** NW-F4 (audit-newcode.md)
- **What and why:** Three gaps in the v0.30.0 guard: (a) when weights are already 'ready', the weights-offer path returns immediately, so training and sleep run on a foreign repo's weights with no warning ever; (b) a stored repo for a tag the bridge does not know never warns anywhere, so a hub-found or hand-typed foreign repo on an unknown tag is unguarded; (c) 'Keep the one set' is not remembered — every later download press re-opens the same warning for a repo the user deliberately kept. The guard's size-aware pick itself is correct for the cases constructed. Fix: run the same check on the train/sleep pre-check path when weights are already ready, and remember a keep decision per profile+repo so it warns once.
- **Evidence:** stella/gui.py _check_base_repo_match (~7687-7751), _weights_offer (~7887-7889). Audit: audit-newcode.md NW-F4.

### N35. The built-in strengths table says LFM3 is good at reading long documents; Stella's own OST measurement scored it 0% at exactly that

- **Priority:** P2
- **Source finding(s):** NW-F5 (audit-newcode.md)
- **What and why:** strengths.py lists LFM3 good at 'reading long documents', grounded per its comment in the roster audit's interpolation (hybrid architecture 'degrades gracefully'). The OST run the same file cites as grounding measured LFM3 long_context at 0%. The table claims the opposite of the best evidence Stella itself holds. Spot-checks of the rest of the table against the roster doc held up; one softer case rides along: the dolphin reviewer's 'general questions' is listed good while the roster records its own page admitting no benchmarks were run — an expectation, not a measurement, in a table whose header says it carries what is known, not what is hoped for. Fix: drop 'reading long documents' from LFM3's good list (or move it to not-good per the 0% measurement) and drop or reword the dolphin's 'general questions'.
- **Evidence:** stella/strengths.py:80-84; ~/workspace/ollama-live-run/ost/results/lfm3_1.7b/PROFILE.md line 24 and the raw long_context result file. Audit: audit-newcode.md NW-F5.

### N36. The Hub lookup reports 'nothing found' when Hugging Face actually failed mid-search, instead of 'couldn't reach it, try again'

- **Priority:** P2
- **Source finding(s):** NW-F6 (audit-newcode.md)
- **What and why:** In lookup_hf_repos, a failed detail fetch is swallowed and the rung simply ends with zero offerable repos; if every detail fetch fails (connection dropped after the search call, Hub rate-limiting the detail calls), the lookup walks the whole ladder and returns 'none' — and the window shows 'Stella doesn't know where this model's training files live' (a claim that the search completed and nothing exists) instead of the honest 'couldn't reach Hugging Face, try again'. The user is told a false fact and given no retry cue. Fix: track detail-fetch failures per rung; if a rung had candidates but every detail fetch failed, return the offline ending.
- **Evidence:** stella/hub_lookup.py:215-221; newcode probe_all section E (all detail fetches failing -> {'state': 'none'}). Audit: audit-newcode.md NW-F6.

### N37. The Hub lookup's 'offerable' check passes a repo whose real weights are a GGUF file (a small tokenizer.safetensors is enough)

- **Priority:** P2
- **Source finding(s):** NW-F7 (audit-newcode.md)
- **What and why:** The name filter only rejects repo ids containing 'gguf'/'mlx', and the offerable check only requires config.json plus ANY file ending .safetensors. A repo named without 'gguf' that holds config.json, a small tokenizer.safetensors, and its actual weights as model.gguf passes both gates and is offered as trainable weights; training from it cannot work as offered. (The pure GGUF-only case is correctly rejected, and a config.json in a subfolder is also rejected — a safe false negative.) Fix: require the safetensors payload to be the weights (a model*.safetensors or sharded set, or safetensors totalling a plausible share of the repo), and/or reject repos whose files include .gguf at all.
- **Evidence:** stella/hub_lookup.py:160-173, :199-201; newcode probe_all section E (_offerable({config.json, tokenizer.safetensors, model.gguf}) -> True). Audit: audit-newcode.md NW-F7.

### N38. Provision calls weights 'ready' when a weights file is a dangling symlink to a download that never finished

- **Priority:** P2
- **Source finding(s):** NW-F8 (audit-newcode.md)
- **What and why:** weights_status tests the config with .exists() but the weights with a bare glob list — a snapshot symlink whose blob download never finished still counts as weights present. Training then starts against a snapshot with missing bytes and fails deep inside the run instead of at the honest 'not downloaded' step. Fix: require the globbed weights files to exist (following the symlink) — and ideally that no .incomplete blob remains for the repo — before reporting 'ready'.
- **Evidence:** stella/provision.py:133-141; newcode probe2 section J (dangling-symlink snapshot -> {'state': 'ready'}). Audit: audit-newcode.md NW-F8.

### N39. A local weights folder set as the base is treated as a Hugging Face repo id and reported missing, with a dead-end 'repo does not exist' message

- **Priority:** P2
- **Source finding(s):** NW-F9 (audit-newcode.md)
- **What and why:** is_hf_repo_id is true for any string with '/' and no ':' — including a local path. So a local weights folder (a base kind the bridge itself explicitly blesses) is reported by weights_status as state 'missing' with the path as its 'repo', and the download path would ask the Hub for '/home/user/models/my-model' and report 'That repo does not exist on Hugging Face' — a misleading dead end for a user who pointed Stella at weights already on disk. Fix: classify first (a local path that exists gets its own ready state), reusing the bridge's classify_base_ref, before the repo-id test.
- **Evidence:** stella/provision.py:94-103; newcode probe2 section J. Audit: audit-newcode.md NW-F9.

### N40. Cloning a profile silently drops its report cards and its profile notes, and nothing anywhere says so

- **Priority:** P2
- **Source finding(s):** NW-F10 (audit-newcode.md)
- **What and why:** clone_profile builds the clone fresh and optionally clones projects; it never copies the report-cards folder or the profile notes. The clone's docstring and every user-visible text checked (guide, window) say nothing about this, so a user who clones to preserve a profile loses the attached evidence without a word. Import, by contrast, deliberately restores cards — which makes the clone gap an inconsistency, not a policy. Fix: copy report cards and profile notes on clone like import does for a new profile, or state the drop in the clone dialog.
- **Evidence:** stella/model.py:1049-1120; newcode probe2 section I (clone cards [], notes ''). Audit: audit-newcode.md NW-F10.

### N41. A chat model that has been removed (HTTP 404) dead-ends in raw provider wording, and the stale-list warning only ever shows in Settings, never in chat or the CLI

- **Priority:** P2
- **Source finding(s):** CH-F4 (audit-chat.md)
- **What and why:** The cloud chat paths special-case only 401 and 429; a 404 becomes 'Groq said no (HTTP 404): ...' echoing the provider's own error text, with nothing saying 'that model may have been removed — pick another one'. Separately, the R51 freshness mechanism exists and its dates are currently fresh (checked 2026-11-17), but its only caller is the Settings panel: chat and CLI chat never show the stale-list note, and CLI chat silently defaults to the first listed model — so the exact R11/R12 failure mode (a rotted default model) will surface in chat as an unexplained 'said no'. Fix: map 404/model-not-found to a plain 'no longer offered, pick another model' message, and surface the stale-list notes at CLI chat startup and in the chat window.
- **Evidence:** stella/providers.py:450-453, :595-598, :135-175; sole caller stella/gui.py:3529; chat probes P10 and P13. Audit: audit-chat.md CH-F4.

### N42. Unexpected chat errors are shown to the user with the raw exception text, unscrubbed (paths, URLs, even key-shaped strings)

- **Priority:** P2
- **Source finding(s):** CH-F5 (audit-chat.md)
- **What and why:** The catch-alls in the chat reply path and the tool-call path format the raw exception straight into the user-visible reply. Neither passes through the debug-log scrubber, so any un-curated exception (a library error carrying a file path, a URL, or a key-shaped string a user pasted) is echoed into the chat in raw form — against both the plain-words rule and the spirit of the secrets rule. The curated error types are plain; this is the un-curated tail that is not. Probed: a chat function raising a RuntimeError containing a key-shaped token and a home path produced a reply containing the whole string. Fix: scrub catch-all exception text with the existing scrubber, or replace it with a fixed plain sentence and log the detail scrubbed.
- **Evidence:** stella/chat_agent.py:890 and :969-971; chat probe P15. Audit: audit-chat.md CH-F5.

### N43. Saving a key over a damaged providers.json silently drops the other providers' keys from the live file, and nobody tells the user

- **Priority:** P2
- **Source finding(s):** CH-F6 (audit-chat.md)
- **What and why:** save_key detects the corruption and backs the file up, then loads it as empty and writes only the new key. The other keys survive only inside the .corrupt backup, and no caller tells the user: the CLI just prints 'Saved the key.' The Settings reset flow explains itself; the save flow — the one a user naturally tries first — does not. Probed: a file holding a Groq key, corrupted, then saving a Gemini key leaves has_key('groq') false with no message anywhere. Fix: have save_key report when it backed up a damaged file, and have the CLI and Settings say the old keys file was damaged and kept as a backup, so the other keys need saving again.
- **Evidence:** stella/providers.py:310-313; chat probe P12. Audit: audit-chat.md CH-F6.

### N44. The CLI help promises --json works everywhere except 7 named commands, but 5 more refuse it — with a reason that is not true for them — and two already contain finished, unreachable --json code

- **Priority:** P2
- **Source finding(s):** CL-F2 (audit-cli.md)
- **What and why:** The top help, every subcommand's --json help text, and the module docstring all say --json works everywhere except train, sleep, distill, export-gguf, requant, pull-weights, and chat. In fact howto, delete-checkpoint, prune-checkpoints, sleep-delete, and sleep-prune also refuse it — and the refusal claims 'it prints progress lines as it runs', which is true of none of them; they are instant commands with an obvious single result. Two of them (delete-checkpoint, prune-checkpoints) already contain finished --json output branches that the gate makes unreachable — dead code proving the support was built and then walled off. Fix: add the five to the JSON command set (two need no new code), or at minimum correct the help list and give instant commands a truthful refusal reason.
- **Evidence:** stella/cli.py:174-210 (JSON_COMMANDS), :3636 (gate); CLI evidence 00-top-help.txt, 02-readonly.txt, 04-flags-confirms.txt. Audit: audit-cli.md CL-F2.

### N45. train --dry-run --json failures print no JSON at all, while the same failure in sibling commands prints the JSON error document

- **Priority:** P2
- **Source finding(s):** CL-F3 (audit-cli.md)
- **What and why:** With --json, a failed command is supposed to leave one JSON error document on stdout plus the clean line on stderr; show-profile, verify, and import all do this. But train's dataset pre-flight is handled inside the command itself (print + return 1), bypassing that handler, so the same flag on the same kind of failure yields empty stdout. A script parsing stdout gets JSON for one failure and silence for another. The base-ref failure in the same command DOES produce the envelope, because it raises through main — two shapes from one command. Fix: let the dataset pre-flight raise like the other failures, so the --json error path covers it.
- **Evidence:** stella/cli.py:1552 vs :3643; CLI evidence 03-flows.txt vs 05-train-chat.txt and 02-readonly.txt. Audit: audit-cli.md CL-F3.

### N46. prune-checkpoints reports cheerful success (exit 0) for a profile or project that does not exist; delete-checkpoint blames the checkpoint instead

- **Priority:** P2
- **Source finding(s):** CL-F4 (audit-cli.md)
- **What and why:** The checkpoint commands never check that the profile or project exists — they only list checkpoint folders, and an empty list reads as 'nothing to do'. A typo'd name gets a false success from prune ('has 0 checkpoints; keeping 3 deletes nothing', exit 0) and a wrong diagnosis from delete-checkpoint ('no checkpoint step-5'), while every sibling command names the missing profile/project and exits 1. Seen live too: after a profile was deleted to the trash, prune still exited 0 while sleep-delete correctly said 'no profile named demo'. Fix: resolve the profile/project at the top of both commands, like the siblings do.
- **Evidence:** CLI evidence 06-confirms2.txt and 04-flags-confirms.txt. Audit: audit-cli.md CL-F4.

### N47. The CLI never got v0.34.0's 'Put it in Ollama' name — it still says 'Create the Ollama model' and 'Created in Ollama as', so the action has two names

- **Priority:** P2
- **Source finding(s):** CL-F5 (audit-cli.md)
- **What and why:** v0.34.0's point was one action, one name: both window buttons are 'Put it in Ollama' and the window's success line is '<name> is in Ollama now. It will show up in Code Forge's model list.' The CLI — which the changelog says uses the same engine — calls the same action --create, prints 'Create the Ollama model with:' and finishes 'Created in Ollama as <name>.' A user who learned the action's name in the window will not recognise it in the terminal. The replace question itself is correctly shared (asks, defaults No, --yes pre-answers); only the words diverge. Fix: name the action 'Put it in Ollama' in the CLI output and match the success sentence (keeping in step with task N62 if that sentence is trimmed in the window).
- **Evidence:** stella/cli.py:1767, :1783, :1801 vs stella/gui.py:5868, :10852, :10956; CLI evidence 01-all-help.txt. Audit: audit-cli.md CL-F5.

### N48. create-project accepts a dataset file that does not exist and reports plain success; the dead path only fails later, at train time

- **Priority:** P2
- **Source finding(s):** CL-F6 (audit-cli.md)
- **What and why:** create-project with --dataset /nonexistent.jsonl exits 0 with 'Created project', and show-project then lists the dead path as the project's dataset. The failure only surfaces later, at train or sleep time ('dataset not found'). The CLI already owns the exact check — train's pre-flight runs it and refuses with the path named — but create-project never calls it, so a typo'd path creates a project that can never train while the output says everything is fine. (The check must use the same resolver train uses, since a bare bundled name resolves through Stella's data folders.) Fix: run the dataset health check at create time and refuse, or at minimum warn in plain words, when the dataset resolves to missing or invalid.
- **Evidence:** stella/cli.py:1900 (cmd_create_project); CLI evidence 03-flows.txt. Audit: audit-cli.md CL-F6.

### N49. Every installer and doctor retry message says 'run bash install.sh again' — even inside the double-click windows, where the user cannot type it and the icon they used is never named

- **Priority:** P2
- **Source finding(s):** IN-F3 (audit-installer.md)
- **What and why:** A user who arrived by double-clicking sees failures inside the launcher's terminal window, which closes when they press Enter; they cannot type the command they are told to run, and the message never names the icon they actually used. The pattern is everywhere: install.sh (five places), install-training.sh (four), wheel_fetch.py's failure line, and doctor.py (eight) — the doctor being what the Repair Stella double-click runs. Each message is honest about the cause; the prescribed recovery action is the part a click-only user cannot perform as written. Fix: make the retry line name the click ('double-click Install Stella in this folder again — or, from a terminal, run bash install.sh again') in the shared messages.
- **Evidence:** install.sh:60, :75, :120, :137, :159-161; install-training.sh:37, :61, :112, :131; stella/doctor.py:141, :167, :254, :280, :311, :339, :347, :355; captured outputs in installer scratch. Audit: audit-installer.md IN-F3.

### N50. The training install's first step is minutes of silence — no progress line and no network check before the slow package-listing step

- **Priority:** P2
- **Source finding(s):** IN-F4 (audit-installer.md)
- **What and why:** install-training.sh goes straight from its two header lines into the pip dry-run that lists the wheels. That resolve is slow even on a healthy connection — the script's own comment admits re-resolving takes 'two silent minutes' — and with no network it retries in silence far longer. The base installer learned this lesson in the earlier review (a network pre-check plus a 'this can take a few minutes' line before every pip step); the training installer has neither before this step. A user double-clicking the training icon sees a motionless window and can reasonably conclude it is stuck and close it mid-resolve. Proven in scratch: with a dead proxy, only the two header lines printed for over 4.5 minutes. Fix: print a 'Listing the training packages… this can take a few minutes' line (and reuse the network pre-check) before the resolve.
- **Evidence:** install-training.sh:93 and the comment at :67-69; contrast install.sh:110-147; scratch log scratch/inst/train_fail.log. Audit: audit-installer.md IN-F4.

### N51. The README's LFM3 proof run tells the user to press a 'Start training' button that does not exist

- **Priority:** P2
- **Source finding(s):** DC-F2 (audit-docs.md)
- **What and why:** Proof-run step 5 says '(or Start training in the Train panel)'. There is no 'Start training' button anywhere in the v0.34.0 window: training starts by picking the Train job and pressing Go (or the Proof run button). A first-time user following the README's own closer looks for a button that is not on screen. Fix: change step 5's window path to 'pick Train and press Go in the window'.
- **Evidence:** README.md:502; job row + Go button at stella/gui.py ~5524-5545; the only 'Start training' string in gui.py (:10069) is a sentence in a message, not a button. Audit: audit-docs.md DC-F2.

### N52. The README's version and feature record stops at v0.24.0 — report cards, the live lookup, and Put it in Ollama are nowhere in it

- **Priority:** P2
- **Source finding(s):** DC-F3 (audit-docs.md)
- **What and why:** The README Status list ends with the v0.24.0 bullet. There is no v0.25.0–v0.34.0 entry, and the body never mentions report cards, the live Hugging Face lookup, the simple profile window's strengths, or the Put it in Ollama button (grep: 'report card' 0 hits, 'Put it in Ollama' 0 hits). The README is the front door of a release; a reader gets a feature picture ten versions old, and its GGUF section still presents the typed ollama create command as the way a model gets into Ollama. Fix: add the v0.25.0–v0.34.0 bullets (or point the Status list at the CHANGELOG) and name Put it in Ollama in the GGUF/proof-run steps.
- **Evidence:** README.md Status bullets end ~line 133; README.md:509 (typed create as step 8); CHANGELOG.md:3-183 carries the missing record; button at stella/gui.py:10852. Audit: audit-docs.md DC-F3.

### N53. The README proof run still teaches assigning a role by hand (--role fast), which v0.31.0 abolished

- **Priority:** P2
- **Source finding(s):** DC-F4 (audit-docs.md)
- **What and why:** Step 3 tells the user to make the profile with '(role: fast)' and gives the CLI form create-profile ... --role fast; step 6 explains the probe gate as applying 'since its role is fast'. v0.31.0's whole point (and the How to Use text) is that nobody assigns roles: Stella works the role out from the model, and a governing role is derived only for the tags that actually hold Forge seats. The README presents manual assignment as the normal way to get a governing-seat profile. (The --role flag still exists on the CLI, so the command runs — the teaching is stale, not the command.) Fix: drop --role fast / '(role: fast)' from the proof run and explain the gate via the derived role of the LFM3 tag, as the guide does.
- **Evidence:** README.md:497-499, :505-506; stella/howto.py:156-157; flag at stella/cli.py:2997. Audit: audit-docs.md DC-F4.

### N54. The profile window's own help says the Ollama tag is 'used for dreaming and the refusal probe'; the guide and the code say the probe does not use it

- **Priority:** P2
- **Source finding(s):** DC-F5 (audit-docs.md)
- **What and why:** The help line under 'Ollama tag' in the profile window's Details flap says the tag is 'Used for dreaming and the refusal probe.' The How to Use Profiles topic says the opposite: 'Used for dreaming… The refusal probe does not use it.' The code backs the guide: probe.py has zero ollama_tag references; the tag is read for dreaming in sleep.py. Two user-visible texts in the same product state opposite facts about the same field. Fix: drop 'and the refusal probe' from the profile window's tag help line.
- **Evidence:** stella/gui.py profile Details help (~1845); stella/howto.py:153-155; grep -c ollama_tag stella/probe.py = 0; stella/sleep.py:868. Audit: audit-docs.md DC-F5.

### N55. How to Use never mentions the mismatch warning, and its Bridge topic describes only the old curated lookup — the live Hugging Face search is missing from the topic that should explain it

- **Priority:** P2
- **Source finding(s):** DC-F6 (audit-docs.md)
- **What and why:** When a stored repo is valid but wrong for the model, the download warns and offers 'Use the usual repo instead' / 'Keep the one set' — no How to Use topic mentions this warning or how to choose. And the Bridge topic describes only the curated tag lookup and the CLI; the v0.33.0 live Hugging Face search (the path an unknown model actually takes) appears only as two sentences buried in the Profiles topic, while the Bridge topic's 'Honest limits' still reads as if an unseen tag is a dead end. The two newest download paths are exactly the ones a user hits when a download goes sideways. Fix: add the mismatch warning and the live search to the Bridge topic, one short plain-words paragraph each.
- **Evidence:** guard dialog stella/gui.py:7691-7731; Bridge topic stella/howto.py:104-124 (grep 'mismatch'/'usual repo' in howto.py = 0 hits); stella/hub_lookup.py:174. Audit: audit-docs.md DC-F6.

## P3 — polish

### N56. After a Hub lookup ends, the status bar still says 'Looking on Hugging Face...' while the activity light already says Idle

- **Priority:** P3
- **Source finding(s):** GA-F3 (audit-gui-a.md)
- **What and why:** When a lookup finishes, the activity light is reset to Idle but no closing status is posted for the two endings that do not open a dialog (nothing found / Hugging Face unreachable), so the bar keeps the 'Looking on Hugging Face...' line indefinitely. The two indicators disagree. Fix: post the matching closing status line in those two endings.
- **Evidence:** stella/gui.py:7662 (no status posted); GUI-A drive log 10:00/10:14 (status stayed 'Looking on Hugging Face...' while activity said Idle). Audit: audit-gui-a.md GA-F3.

### N57. A brand-new profile's Details say 'updated unknown'

- **Priority:** P3
- **Source finding(s):** GA-F4 (audit-gui-a.md)
- **What and why:** create_profile stamps 'created' but never 'updated', and the facts line prints 'unknown' for the missing value — a polish-level internal term leaking into the new profile's Details. Fix: stamp updated = created at creation, or skip the 'updated' fact until a first edit sets it.
- **Evidence:** shots/gui-a/14-details-flap.png; stella/model.py create_profile (~866); stella/gui.py _refresh_facts. Audit: audit-gui-a.md GA-F4.

### N58. The profile simple view is dominated by two big empty boxes: the notes flap starts expanded and the report-cards list stretches mostly empty

- **Priority:** P3
- **Source finding(s):** GA-F5 (audit-gui-a.md)
- **What and why:** The Profile notes flap starts expanded (its sibling Details flap starts closed), showing a tall empty text box, and the report-cards list stretches to fill the window even when it holds one short row — so the simple view, which exists to be glanceable, is mostly empty white boxes at 1366x768. Fix: start the notes flap closed like Details, and cap the cards list height to its rows.
- **Evidence:** shots/gui-a/12-new-profile-window.png, 15-card-attached.png; stella/gui.py:1932 vs :1811. Audit: audit-gui-a.md GA-F5.

### N59. The Hugging Face repo field's placeholder is a real repo that belongs to a different model — the exact value the mismatch guard exists to catch

- **Priority:** P3
- **Source finding(s):** GA-F6 (audit-gui-a.md)
- **What and why:** The repo field's grey placeholder text and its help line both show 'LiquidAI/LFM3-1.7B' as the example repo, on every profile — including a Granite profile. It is the same string Joshua once typed into the wrong profile, and the mismatch guard exists because typing an example-looking repo into the wrong profile is a real failure mode. Fix: use a clearly fake example ('owner/model-name') for the placeholder and help.
- **Evidence:** stella/gui.py:1816 and the field's help text. Audit: audit-gui-a.md GA-F6.

### N60. Finish cards keep their working titles and a busy-looking bar after the job is done

- **Priority:** P3
- **Source finding(s):** GB-F9 (audit-gui-b.md)
- **What and why:** When an export or the Put it in Ollama job finishes, the finish card keeps its present-tense title ('Exporting GGUF', 'Putting it in Ollama') and a chunky busy-looking bar, while the body text already says 'GGUF ready' / 'is in Ollama now'. A user glancing at the card cannot tell from its header whether it is still working. Fix: on finish, swap the title to the past tense ('Export done') and stop/fill the bar, matching the body text.
- **Evidence:** shots/gui-b/38-export-finish-card.png, 52-put-in-ollama-done.png; stella/gui.py finish-card code. Audit: audit-gui-b.md GB-F9.

### N61. A damaged dataset is reported one bad line at a time, in parser language — the user fixes line 2, then meets line 3, then line 4

- **Priority:** P3
- **Source finding(s):** GB-F10 (audit-gui-b.md)
- **What and why:** The dataset check stops at the first bad line and reports it in parser vocabulary ('dataset line 2: not valid JSON: Expecting value: line 1 column 1 (char 0)'). With three damaged rows, the user fixes one, re-runs, and is told about the next — three rounds of the same dead end, each in words a non-programmer cannot act on beyond the line number. Fix: validate the whole file in one pass and list every bad line ('lines 2, 3 and 4 look damaged') in plain words.
- **Evidence:** shots/gui-b/28-dataset-damaged.png; dataset check in stella/dataset.py (check_dataset). Audit: audit-gui-b.md GB-F10.

### N62. The Put in Ollama success sentence sends the user to check Code Forge's model list — a different program a Stella-only user may not have

- **Priority:** P3
- **Source finding(s):** GB-F11 (audit-gui-b.md)
- **What and why:** '<name> is in Ollama now. It will show up in Code Forge's model list.' Stella and Code Forge are separate programs; a user who only has Stella is told to verify the result in a program they may not own, and the sentence gives no Stella-side way to see the model is there. Fix: drop the Code Forge clause, or name where in Stella (or Ollama itself) the model shows up. (If this lands, task N47's CLI success sentence should match the trimmed wording.)
- **Evidence:** shots/gui-b/52-put-in-ollama-done.png; stella/gui.py:10955-10958. Audit: audit-gui-b.md GB-F11.

### N63. A 'Make smaller' failure tells the user to 'pull the model' — Ollama's CLI word — and Stella offers no pull button in that flow

- **Priority:** P3
- **Source finding(s):** GB-F12 (audit-gui-b.md)
- **What and why:** When requant cannot find the source model it ends with 'pull the model first' wording. 'Pull' is the Ollama terminal command's verb; the GUI user has no pull button in this flow, so the instruction names an action they cannot take from where they stand. Fix: say 'download the model first' and point at the place in Stella that does it.
- **Evidence:** stella/requant.py:521; stella/ollama.py:514. Audit: audit-gui-b.md GB-F12.

### N64. The probe's status-bar refusal uses the internal project slug and a lowercase fragment instead of the display name and a full sentence

- **Priority:** P3
- **Source finding(s):** GB-F13 (audit-gui-b.md)
- **What and why:** Pressing Run refusal probe before training answers in the status bar with 'project 'tool-calls' has no trained adapter yet. run training first, then probe' — the internal slug rather than the project's display name, and a lowercase fragment rather than a sentence. Everywhere else the window speaks in display names and full sentences. Fix: use the display name and a capitalised full sentence.
- **Evidence:** shots/gui-b/43-probe-no-adapter.png; probe refusal path in stella/gui.py. Audit: audit-gui-b.md GB-F13.

### N65. The New Project dialog starts with the template already chosen and a bare 'OK' button

- **Priority:** P3
- **Source finding(s):** GB-F14 (audit-gui-b.md)
- **What and why:** The dialog opens with the template combo already set to 'No template: start blank' — a default selection, against the select-nothing-by-default rule in spirit (nothing harmful is chosen, but the pattern is the one the rule exists to prevent) — and its confirm button reads 'OK' instead of saying what it does. Fix: leave the template unset until picked (or keep 'start blank' as an explicit first pick), and label the button 'Create project'.
- **Evidence:** shots/gui-b/16-new-project-dialog.png; New Project dialog in stella/gui.py. Audit: audit-gui-b.md GB-F14.

### N66. The probe gate passes a saved result whose before/after total is missing entirely (damaged-file edge)

- **Priority:** P3
- **Source finding(s):** EN-F8 (audit-engine.md)
- **What and why:** In probe_gate, a missing total in the saved probe results makes the 'incomplete result' check slip through (None == 0 is False), so a gate can pass on a result file that does not record how many prompts were even run. Reachable only through a damaged or hand-edited probe_results.json — the product's own writes always include the totals — which is why this is polish-tier, but the gate is the safety-critical reader and should fail closed. Fix: treat a missing or non-integer total as an incomplete result in probe_gate.
- **Evidence:** engine probe1_refusal.py output (missing-total case passes); stella/probe.py probe_gate. Audit: audit-engine.md EN-F8.

### N67. The sleep forgetting threshold accepts nan or negative values, silently disabling or inverting the check while the report records it as a real check

- **Priority:** P3
- **Source finding(s):** EN-F9 (audit-engine.md)
- **What and why:** --threshold is a bare float with no validation anywhere on the path. nan makes every comparison False, so the forgetting check silently never fires while report.json records the threshold as if a real check ran; a negative value inverts the check's meaning. The GUI path uses a fixed default, so this is a CLI-only edge — but the report it produces is dishonest. Fix: validate the threshold (finite, >= 0) at the CLI and in sleep_project, and refuse in plain words otherwise.
- **Evidence:** stella/cli.py:3316; stella/sleep.py replay_check threshold use; engine audit reasoning from code. Audit: audit-engine.md EN-F9.

### N68. Validation loss is silently computed on at most the first 50 rows, and no report says the number is partial

- **Priority:** P3
- **Source finding(s):** EN-F10 (audit-engine.md)
- **What and why:** evaluate_loss defaults to a 50-row limit and both callers (the training loop's validation and the sleep replay check) inherit it. With more than 50 new validation rows, the reported loss is the first 50 in file order — a fine engineering choice that is nowhere disclosed, so a user comparing two runs believes both numbers cover the whole validation set. Fix: say 'first 50 rows' wherever the number is shown or saved, or raise the cap for the replay check where the row count is the point.
- **Evidence:** stella/train.py:2096 (evaluate_loss limit=50), :2691; stella/sleep.py replay_check. Audit: audit-engine.md EN-F10.

### N69. Whether real Ollama accepts the single-quoted FROM line Stella writes into every Modelfile is unprobed — every export to a folder with spaces rides on it

- **Priority:** P3
- **Source finding(s):** PI-F7 (audit-pipelines.md)
- **What and why:** write_modelfile quotes the GGUF path with shlex.quote, producing FROM '/path/with spaces/model.gguf'. The function's own docstring admits it is not verified that Ollama's Modelfile parser accepts single-quoted paths. Every export whose folder contains a space — including the new one-click Put it in Ollama — depends on this. It cannot be settled on this VM (no real Ollama answering); it needs one real-PC or real-Ollama check with a space in the path. Fix: probe it once against a real Ollama; if quotes are rejected, write the path unquoted or escaped per Ollama's parser.
- **Evidence:** stella/gguf.py write_modelfile docstring + shlex.quote use. Audit: audit-pipelines.md PI-F7.

### N70. A failing distill prompt silently burns two full timeouts (about 10 minutes at the default) with no sign of life between attempts

- **Priority:** P3
- **Source finding(s):** PI-F8 (audit-pipelines.md)
- **What and why:** The distill retry loop re-runs a failed prompt once with no event emitted between attempts, so a dead or slow teacher costs two full per-prompt timeouts in silence — at the 300-second default the progress display sits motionless for ~10 minutes on a single prompt, indistinguishable from a hang. Fix: emit a 'retrying' progress event between attempts (and consider not retrying a timeout at full length).
- **Evidence:** stella/distill.py distill_dataset retry loop (no emit). Audit: audit-pipelines.md PI-F8.

### N71. The rule 'import only brings report cards back for a newly created profile' is stated nowhere a user would see, and import gives no warning when cards were skipped

- **Priority:** P3
- **Source finding(s):** NW-F11 (audit-newcode.md)
- **What and why:** Import restores report cards only when the profile did not already exist; importing over an existing profile silently skips the cards, the import result carries no warning, and the How to Use text says only that cards travel with exports. A user re-importing an export to restore a profile loses the cards with no word. Fix: add a warning to the import result when cards were skipped, and state the rule in the Export and import topic.
- **Evidence:** stella/export.py import path (~3075-3085); stella/howto.py:141-152; newcode probe3 section K (import over existing profile -> cards [], warnings []). Audit: audit-newcode.md NW-F11.

### N72. Wheel fetch leaves a hash-mismatching encoded-name twin in the cache forever, and an uppercase .WHL URL loses the resumable-download path

- **Priority:** P3
- **Source finding(s):** NW-F12 (audit-newcode.md)
- **What and why:** Two small cache edges: (a) when a download lands under the %2B-encoded name with a mismatching hash, fetch_file neither removes nor reports the twin, so the cache keeps a permanent dead file (the v0.30.0 fix made the good copy win; the bad twin just lingers); (b) wheels_from_report requires an exact '.whl' suffix, so an uppercase .WHL URL throws CannotFetchError and silently falls back to a direct, non-resumable download. Fix: delete or report the mismatching twin, and match the suffix case-insensitively.
- **Evidence:** stella/wheel_fetch.py:235-244, :158. Audit: audit-newcode.md NW-F12.

### N73. The same tool block twice in one chat reply runs twice, with real side effects (two profiles created)

- **Priority:** P3
- **Source finding(s):** CH-F7 (audit-chat.md)
- **What and why:** Every tool block in a model reply runs by design, but identical duplicates are not deduplicated: a reply containing the same create_profile block twice created two profiles (lfm3-1-7b and lfm3-1-7b-2). Models repeat themselves often enough that this will happen in real use; the second run is pure side effect with no user intent behind it. Fix: skip an exact-duplicate tool block within a single reply (same tool, same arguments), and say in the transcript that the duplicate was skipped.
- **Evidence:** chat probe P8 (duplicate create_profile blocks). Audit: audit-chat.md CH-F7.

### N74. A custom provider address containing a query string becomes a nonsense endpoint, with no warning when it is saved

- **Priority:** P3
- **Source finding(s):** CH-F9 (audit-chat.md)
- **What and why:** The custom provider path appends '/chat/completions' to the saved base URL unconditionally; a base URL pasted with a query string ('https://host/v1?foo=bar') becomes 'https://host/v1?foo=bar/chat/completions' — an endpoint that can never work, failing later as an unexplained provider error. Fix: validate the base URL at save time (no query string / fragment) and say what is wrong, or strip the query before appending.
- **Evidence:** stella/providers.py:636-643. Audit: audit-chat.md CH-F9.

### N75. One malformed tool block discards the whole chat turn, including valid tool calls that came before it

- **Priority:** P3
- **Source finding(s):** CH-F10 (audit-chat.md)
- **What and why:** parse_tool_calls raises on the first malformed block, so a reply with one good tool call and one broken block loses both — the good call never runs and the user gets only the generic 'I got mixed up there'. Fix: parse blocks independently; run the valid ones and note the malformed one as skipped, like the duplicate case in N73.
- **Evidence:** stella/chat_agent.py:290-328. Audit: audit-chat.md CH-F10.

### N76. --quiet is accepted but does nothing on requant and export-gguf, though both print step-by-step progress

- **Priority:** P3
- **Source finding(s):** CL-F7 (audit-cli.md)
- **What and why:** The flag is documented as silencing progress on the long-running commands, and its help names train, sleep, distill, and pull-weights. requant and export-gguf print the same kind of per-step progress but neither handler reads the quiet flag, so --quiet is silently ignored exactly where a script would want it. Fix: honour _is_quiet in both handlers, or name the exclusion in the help.
- **Evidence:** stella/cli.py requant/export-gguf handlers (no _is_quiet read); CLI evidence 01-all-help.txt. Audit: audit-cli.md CL-F7.

### N77. --verbose changes nothing for ordinary failures, though its help says it prints the traceback when a command fails

- **Priority:** P3
- **Source finding(s):** CL-F8 (audit-cli.md)
- **What and why:** The traceback is printed only in main's catch-all branch; ordinary StellaError failures are handled one branch earlier and never look at the verbose flag. So the documented debugging aid does nothing for the failures a user actually hits. Fix: honour verbose in the StellaError branch too (print the traceback to stderr), keeping the default output unchanged.
- **Evidence:** stella/cli.py:3652 vs the StellaError branch above it; CLI evidence 02-readonly.txt (--verbose run byte-identical). Audit: audit-cli.md CL-F8.

### N78. Saying No to a delete confirmation exits 1, but saying No to the Ollama replace question exits 0 — a script cannot tell a deliberate No from a failure on the delete path

- **Priority:** P3
- **Source finding(s):** CL-F9 (audit-cli.md)
- **What and why:** The delete confirms treat a No as an error exit while the export replace question treats it as a clean stop. Both are 'the user changed their mind'; the exit codes should agree (0, with the 'Kept …' line, is the friendlier convention and the one export already uses). Fix: make the delete confirms exit 0 on a deliberate No, keeping real failures at 1.
- **Evidence:** stella/cli.py:1357, :1424 vs :1798; CLI evidence 06-confirms2.txt. Audit: audit-cli.md CL-F9.

### N79. The wheel download failure line shows the user a raw Python error before the installer's own plain-words lines

- **Priority:** P3
- **Source finding(s):** IN-F5 (audit-installer.md)
- **What and why:** When the pre-download fails, wheel_fetch.py prints the raw exception ('could not download torch-…whl: <urlopen error [Errno 111] Connection refused>') to the same screen the user reads. The install script's own following lines are plain and correct ('No network connection, or the download was blocked…'), so the raw line is pure noise on top of a good message. Fix: print a plain 'could not download <file>' line and keep the exception text for the log/debug path only.
- **Evidence:** stella/wheel_fetch.py failure print; scratch log scratch/inst/train_fail.log line 3. Audit: audit-installer.md IN-F5.

### N80. Three of the four double-click launcher scripts ship in the zip without the executable bit (harmless today, against the project's own zip rule)

- **Priority:** P3
- **Source finding(s):** IN-F6 (audit-installer.md)
- **What and why:** install_launcher.py, install_training_launcher.py, and uninstall_launcher.py are stored 0o100644 while repair_launcher.py is 0o100755. Nothing breaks today — every .desktop Exec line runs them through python3, proven end-to-end in the scratch install — but the project's zip rule says launchers ship executable, and any future direct-exec path would fail on exactly the files a user double-clicks. Fix: set the executable bit on the three launchers in the zip build, like the repair launcher already has.
- **Evidence:** zip listing of the shipped stella-v0.34.zip; contrast install.sh stored 0o100755. Audit: audit-installer.md IN-F6.

### N81. The Export and import topic's export list omits the refusal-probe results that its own import list (two sentences later) includes — and the code does export them

- **Priority:** P3
- **Source finding(s):** DC-F7 (audit-docs.md)
- **What and why:** The topic's 'An export carries…' list does not mention probe results; its import list in the next breath says they come back; and the code copies probe_results.json into every export. A reader cannot tell from the export side that their gate evidence travels. Fix: add 'the refusal-probe results' to the export list so the two lists match.
- **Evidence:** stella/howto.py:271-273 vs :279-280; stella/export.py _copy_project_payload (~755). Audit: audit-docs.md DC-F7.

### N82. FORMAT.md's example export manifest still says stella_version 0.29.0 in a tree that writes 0.34.0

- **Priority:** P3
- **Source finding(s):** DC-F8 (audit-docs.md)
- **What and why:** The format doc's example manifest shows 'stella_version': '0.29.0' — five versions stale by the project's own convention (the earlier review's R129 established keeping this example current). Nothing breaks; the doc just quietly drifts. Fix: bump the example to 0.34.0.
- **Evidence:** docs/FORMAT.md:66; stella/model.py:35 (STELLA_VERSION = '0.34.0'). Audit: audit-docs.md DC-F8.

### N83. The Chat topic uses 'validation loss' — a term explained nowhere in the guide

- **Priority:** P3
- **Source finding(s):** DC-F9 (audit-docs.md)
- **What and why:** Chat topic step 6 says Stella reads back 'Validation loss and the refusal probe' when reporting training results. 'Validation loss' appears nowhere else in the guide; the Training topic explains only 'the loss number'. A term used once and defined nowhere is exactly the jargon the guide exists to avoid. Fix: say 'the loss number' in the Chat topic, matching the Training topic's wording.
- **Evidence:** stella/howto.py:58-59 vs :186-189. Audit: audit-docs.md DC-F9.
