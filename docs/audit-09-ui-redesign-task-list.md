# STELLA UI redesign task list (Audit #9)

Source: [Audit #9: STELLA UI redesign](audit-09-ui-redesign-2026-11-13.md) (2026-11-13, against v0.8.0). This file is a list only: it states what to build, not how the build is scheduled. The UI rebuild lands as its own version after v0.9, because R2 depends on v0.9's auto-config backend.

**Priority key.** P0: blocks the brief's core flow (pick a model, pick a job, press go) or is broken/confusing today. P1: real functional defect or daily friction. P2: missing capability or inconsistency. P3: polish, display, scale.

**Effort key.** S: focused change in 1-2 files. M: across model plus GUI plus tests, or a small design decision plus implementation. L: multi-part build or needs Joshua's direction on scope.

**Counts: 26 tasks (6 P0 / 9 P1 / 5 P2 / 6 P3), covering all 35 Audit #9 findings (5 W / 9 U / 13 G / 8 D).**

**No-duplication note.** This list does not duplicate the merged list (`stella-audit-task-list-123.md`). Where a redesign task replaces a merged-list task it says SUPERSEDES with the T-number; where it builds on one it says EXTENDS. Mooted tasks (their surface goes away entirely) are named under R2. Tasks the redesign does not touch (T2's name/dataset/notes half, T30, T52, T91, T130, T132, T133, T140, T145, T160, T17, T105, and the rest) stay open in the merged list as they are. **T-numbers cited here refer to the merged list as of 2026-11-13 (168 tasks, before this merge); the merge renumbered them — see the merged list for current numbers.**

## P0

### R1 — Main screen becomes pick a model, pick a job, press go

- **Covers:** A9-U2, A9-U7, A9-G3 (part)
- **Effort:** L
- **Library:** 005 Bento grids, 009 Shape morphing (see R20)
- **Supersedes:** T98 (real New Project form: the job picker is project creation now; the name becomes part of the pick). **Note on T38:** the train-panel half is already fixed by the v0.4 restructure (verified live: Start training at y=275, above the fold); R1 finishes the job for Sleep.
- **Problem:** The main window is one long scrolling column of sections with no job picker, and at rest it is a wall of empty grey boxes. The brief's core flow does not exist as a screen.
- **Fix:** Replace the session column with a bento main screen. One hero tile holds the flow: pick a model, pick a job (Train, Sleep, Make smaller, Teach a small model), press go. Small tiles carry the glanceable numbers (RAM, speed, progress) once a job runs. The tree stays as the library of what exists. The core flow needs no scrolling at 1100x680.
- **Done:** At 1100x680 the first screen shows the model pick, the job pick, and Go with nothing below the fold; a new user can reach "press go" without scrolling or opening a second window.

### R2 — Settings leave every screen

- **Covers:** A9-U1, A9-D3
- **Effort:** M
- **Library:** 004 Just-in-time GUI, 012 Progressive disclosure
- **Supersedes:** T134 (Advanced settings section: do not build; the brief puts settings under the hood). **Mooted by this task:** T7 (learning rate as a numeric input: no learning rate field), T40 (lock settings during a run: no settings to lock), T6's user-facing half (validation moves to the backend auto-config), T2's settings half (dirty tracking keeps only name, dataset, notes).
- **Depends on:** v0.9's auto-config backend. The settings cannot leave the screen until the backend decides them.
- **Problem:** Rank, learning rate, epochs, batch size, and sequence length are on screen in four places (session summary, Project window form, Settings defaults, chat template step 4). The brief says the backend sets them all and the user never sees them.
- **Fix:** Delete the settings form from the Project window (name, dataset, and notes stay), delete the settings line from the session summary, delete the Training defaults block from Settings, and rewrite chat template step 4 and the chat greeting so they stop naming settings. The stored settings fields stay in the model for compatibility; nothing in the UI reads or writes them.
- **Done:** No rank, learning rate, epochs, batch size, or sequence length string is visible anywhere in the UI; a grep of the visible strings in gui.py, howto.py, and chat_agent.py finds none.

### R3 — First-run setup checklist

- **Covers:** A9-W4, A9-G3
- **Effort:** M
- **Library:** 020 Setup checklist, 014 Teach by playing
- **Problem:** First launch shows an empty tree, guidance that tells the user to pick a project that does not exist, and a wall of disabled controls. Nothing on screen says what to do first.
- **Fix:** On first launch (empty store), the main screen shows a three-step checklist instead of the disabled wall: 1. Pick a model. 2. Get its weights. 3. Run a tiny first training (the 20-example sample dataset, a real run, not a wizard). Each step is a button that does the step; a finished step ticks. The checklist is dismissible and never reappears as a modal.
- **Done:** An empty store shows the checklist; completing a step ticks it; dismissing it never brings it back; the misleading "pick a project in the list" text is gone.

### R4 — Model picker with fit guidance and no default selection

- **Covers:** A9-W1, A9-G5
- **Effort:** M
- **Library:** 012 Progressive disclosure
- **Extends:** T69 (RAM/time estimate in the detail panel: the estimate moves to the picker, where the choice is made).
- **Problem:** The New Profile dialog pre-selects the first model (Enter creates a profile for a model the user never picked), and it shows bare tags with no "what it does" and no fits-this-PC verdict. The user picks blind.
- **Fix:** The dialog opens with nothing selected (`setCurrentIndex(-1)`, as the chat combo already does); the profile-name note appears only after a pick, and Enter with no pick does nothing. Each model row shows one plain line for what it does and a fit verdict (size plus RAM, from the backend's PC measurement). Details beyond that appear on tap, not up front.
- **Done:** The dialog opens with no selection and no name note; every listed model shows what it does and whether it fits this PC.

### R5 — Real menu bar, actions disabled when they cannot work

- **Covers:** A9-W5, A9-U9
- **Effort:** M
- **Library:** none (U38: real Windows-style menus)
- **Supersedes:** T149 (menu bar).
- **Problem:** The menu is a button with nine actions in one flat list, and four of them are enabled with nothing selected, answering with modal warnings.
- **Fix:** A real `QMenuBar`: File (New profile, New project, Export project, Import package, Settings), View (Profiles, Projects), Help (How to Use Stella, Chat). Actions that need a selection are disabled until one exists. The Menu button goes away.
- **Done:** With an empty store, the actions that need a selection are greyed out; no menu action answers with a "pick one first" modal.

### R6 — Live training graphs and stats

- **Covers:** A9-G1, A9-G4
- **Effort:** L
- **Library:** 021 Glanceable surfaces, 003 Calm technology
- **Extends:** T131 (loss chart plus run history: elevated from P3 to P0; the brief makes it core).
- **Problem:** The only loss readout is one text line. No graph, no speed, no RAM, no time left, no run history. The brief asks for live graphs and stats with a middle-school science software feel, and today there is nothing to watch.
- **Fix:** A loss curve (QPainter, redrawn on new points only, no per-frame cost), plus speed (steps per minute), RAM used, time left, and epoch, in the glanceable card. The UI keeps the loss series from the worker's progress signal (step, total, loss already emitted). Run history is kept per project so the last run's curve is still there after it finishes.
- **Done:** During a run the graph draws, RAM, speed, and time left update, and the finished run's curve and summary remain visible.

## P1

### R7 — One job card for every job, with progress and cancel

- **Covers:** A9-U3, A9-G4 (part), A9-G12
- **Effort:** M
- **Library:** 021 Glanceable surfaces
- **Extends:** T92 (progress and cancel for GGUF/probe jobs), T23 (one job at a time: the card enforces it visibly), T41 (reset progress/loss per project: the card owns per-job state).
- **Problem:** Sleep is a buried section below the fold, and GGUF export and the refusal probe run with no progress and no cancel. The user waits blind.
- **Fix:** Train, Sleep, GGUF export, refusal probe, re-quantize, and distill all run as job cards with a progress bar, a live status line, and a Cancel button. Sleep stops being a section at the bottom of a column. Starting a second job is refused with plain words.
- **Done:** Every job shows progress and offers cancel; no job is below the fold while it runs.

### R8 — Re-quantize and distill get window surfaces

- **Covers:** A9-U2 (part)
- **Effort:** M
- **Library:** 005 Bento grids
- **Problem:** Two shipped jobs (v0.8.0) have no window surface: How to Use sends the user to the Chat or to the terminal.
- **Fix:** The job picker lists "Make smaller" (re-quantize) and "Teach a small model" (distill) as jobs with the same card flow as Train and Sleep. How to Use stops sending the user to the terminal for them.
- **Done:** Both jobs start from the window with no typing.

### R9 — Chat: click-to-pick model, plan before it runs

- **Covers:** A9-U5, A9-G11
- **Effort:** M
- **Library:** 010 AI-native patterns, 012 Progressive disclosure
- **Problem:** With no chat model picked, the chat makes the user type a tag by hand from eleven raw names. And the agent never shows its plan before running: one "just do it" can download, create, and start hours of training with no preview.
- **Fix:** When no chat model is picked, the chat shows clickable model buttons from the installed list instead of "type one of these". Before a multi-step plan runs, the agent shows the plan ("I will: 1. ... 2. ...") with Run and Cancel. Replies stream as they arrive.
- **Done:** No typing is needed to pick a chat model; "just do it" shows its plan first and waits for Run.

### R10 — The session follows the profile

- **Covers:** A9-G6
- **Effort:** S
- **Library:** 022 Per-context profiles
- **Supersedes:** T110 (remember the project per profile).
- **Problem:** The session is one global slot; switching profiles loses the project context.
- **Fix:** Store the last project per profile; switching profiles restores that profile's project. The active profile is visible at a glance.
- **Done:** Switch away from a profile and back; the project is back.

### R11 — Tree rows show full names, with a health badge

- **Covers:** A9-U6
- **Effort:** S
- **Library:** none
- **Extends:** T143 (health badge per profile row), T144 (richer project rows).
- **Problem:** Long model names truncate in the 235 px pane with no tooltip, so the user cannot read which model a profile is.
- **Fix:** A wider default pane, tooltips carrying the full row text, and a small health badge per profile (weights ready, weights missing, Ollama down).
- **Done:** The MiniCPM5 row is readable in full (tooltip or wrap); each profile shows its weights state at a glance.

### R12 — One honest download row

- **Covers:** A9-W2, A9-W3, A9-D2
- **Effort:** S
- **Library:** none
- **Extends:** T48 (tag/base_ref sync: this is the UI face of it; the model fix stays T48's).
- **Problem:** The download row is duplicated in two windows; the button is enabled when there is no repo; and the Profile window says "No Hugging Face repo set" next to a filled Base ref field, telling the user to go to the window they are already in.
- **Fix:** One download row, in the main window; the Profile window's duplicate goes away. Download is disabled when there is no repo, and the label says what to do as a button that opens the profile window. The self-referential label is fixed. The Base ref field stops showing a tag as if it were a repo.
- **Done:** In the no-repo state, Download is disabled and the screen offers a working path to fix it; no duplicate row exists.

### R13 — Collapsible section headers

- **Covers:** A9-U4, A9-G10
- **Effort:** M
- **Library:** 012 Progressive disclosure
- **Problem:** Save project sits below the fold in its own window, and Settings is a 1,165 px scrolling wall in a 625 px viewport. The brief asks for collapsible headers in panels.
- **Fix:** The main panel and Settings get collapsible headers. The action row (Save, Close, Debug report) stays reachable without scrolling the whole form.
- **Done:** At 1100x680, Save project is visible without scrolling; every Settings section is a collapsible group.

### R14 — STELLA's own look: one stylesheet

- **Covers:** A9-G2
- **Effort:** M
- **Library:** 001 Micro-interactions (limited), 002 Spring physics (limited)
- **Problem:** No application stylesheet exists; the app runs in default Qt grey and could be any program.
- **Fix:** One stylesheet applied by `main()`, drawn from the icon (dark surfaces, one accent), applied to every window. Button press dips to 0.97 over 150 ms. No per-frame blur, no layout thrash, nothing that costs frames on the Vega 3.
- **Done:** The app is recognizable as STELLA in a screenshot; every window carries the look.

### R15 — Keyboard: shortcuts and a visible focus ring

- **Covers:** A9-U8
- **Effort:** S
- **Library:** 023 Focus-first navigation
- **Extends:** T112 (window chrome pass: shortcuts are part of it).
- **Problem:** No keyboard shortcuts exist anywhere, and there is no visible focus styling.
- **Fix:** Shortcuts for the main actions (new profile, new project, start training, How to Use, Chat), a visible focus ring in the stylesheet, and tab order in visual order.
- **Done:** Every main action is reachable by keyboard; the focus ring is visible in a screenshot.

## P2

### R16 — The finish moment

- **Covers:** A9-G7
- **Effort:** S
- **Library:** 008 Delight done right, 002 Spring physics
- **Problem:** When a job ends, nothing marks the finish: a log line and a status-bar message, and the screen goes quiet.
- **Fix:** A brief one-shot moment when a job completes: a gold glow on the job card plus a short summary line, under 300 ms, never looping, respecting the reduced-motion preset.
- **Done:** A finished job shows the moment once, then rests.

### R17 — Loading states, never a dead screen

- **Covers:** A9-G8
- **Effort:** S
- **Library:** 011 Skeleton screens
- **Problem:** The model list populates silently; with Ollama slow or down the user sees an empty combo and a note, with no "looking" state in between.
- **Fix:** Skeleton rows in the model list while Ollama answers, paired with the real numbers when they arrive; the Ollama status refresh shows it is working.
- **Done:** With Ollama slow, the picker shows skeleton rows, not an empty combo.

### R18 — Reduced-motion and larger-text presets

- **Covers:** A9-G9
- **Effort:** S
- **Library:** 015 Accessibility presets
- **Problem:** No accessibility preset exists, and the redesign adds motion (R14, R16, R20) that needs an off switch.
- **Fix:** One Settings section with two presets, in plain words: reduced motion and larger text. Reduced motion disables the dip, spring, morph, and finish moment but keeps every state change.
- **Done:** With reduced motion on, no animation runs and everything still works.

### R19 — Before/after preview before export

- **Covers:** A9-G13
- **Effort:** M
- **Library:** 017 See it before you commit
- **Extends:** T79 (surface the probe in the window), T81 (val loss in run summary and window).
- **Problem:** Nothing shows what a fine-tune changed before the user commits to a GGUF export; the probe reports numbers in a dialog.
- **Fix:** Before export, show a side-by-side from the probe: the base model's reply next to the fine-tuned model's reply to the same prompts, so the user sees what changed before committing.
- **Done:** Export offers the preview; the user can export or go back.

### R20 — The job picker becomes the job

- **Covers:** A9-U2 (part)
- **Effort:** S
- **Library:** 009 Shape morphing
- **Problem:** Picking a job and running it are two disconnected moments; the user picks in one place and the job appears in another.
- **Fix:** The picked job tile morphs into the running-job card, under 400 ms, interruptible. The reduced-motion fallback is an instant swap.
- **Done:** Picking a job visibly becomes the running card.

## P3

### R21 — Remove the dead "full" method

- **Covers:** A9-D1
- **Effort:** S
- **Library:** none
- **Supersedes:** T49 (remove/disable dead "full" method: remove it outright).
- **Problem:** The Method combo lists `lora` and `full` with `full` disabled: a visible option the user can never use.
- **Fix:** Drop `full` from the combo. (R2 deletes the settings form anyway; this is the cleanup if the form outlives R2.)
- **Done:** No `full` anywhere in the UI.

### R22 — One tagline everywhere

- **Covers:** A9-D6
- **Effort:** S
- **Library:** none
- **Problem:** The window title and the header carry two different taglines.
- **Fix:** Window title and header use the same line.
- **Done:** One tagline in both places.

### R23 — Status bar shows the session once, in display names

- **Covers:** A9-D4
- **Effort:** S
- **Library:** none
- **Problem:** The session title and the status bar state the same fact twice, in two different namings (display name vs slug).
- **Fix:** Drop the slug repeat from the status bar; the session title carries it.
- **Done:** The status bar no longer repeats the title.

### R24 — Tooltips where they earn their place

- **Covers:** A9-D5
- **Effort:** S
- **Library:** none
- **Problem:** "Dream first" is the only tooltip in the app; nothing else explains itself on hover.
- **Fix:** Tooltips on tree rows (full text) and on any button whose label needs one more word.
- **Done:** Hovering a truncated row shows the full text.

### R25 — How to Use gets search and a link from the empty state

- **Covers:** A9-D7
- **Effort:** S
- **Library:** none
- **Problem:** Thirteen topics in a plain list with no search, and the empty main window never points at the guide.
- **Fix:** A search box over the topics; the empty state links to Getting started.
- **Done:** Searching finds topics; the empty screen offers the guide.

### R26 — Chat window breathing room

- **Covers:** A9-D8
- **Effort:** S
- **Library:** none
- **Problem:** The Chat window's two-line help text is squeezed at the bottom edge of the fixed 700x520 window.
- **Fix:** Resize the window or shorten the help line so the text has room.
- **Done:** The help line has room at the window's size.

## Coverage map (verified both directions)

Finding to task:

- A9-W1: R4. A9-W2: R12. A9-W3: R12. A9-W4: R3. A9-W5: R5.
- A9-U1: R2. A9-U2: R1, R8, R20. A9-U3: R7. A9-U4: R13. A9-U5: R9. A9-U6: R11. A9-U7: R1. A9-U8: R15. A9-U9: R5.
- A9-G1: R6. A9-G2: R14. A9-G3: R3, R1. A9-G4: R6, R7. A9-G5: R4. A9-G6: R10. A9-G7: R16. A9-G8: R17. A9-G9: R18. A9-G10: R13. A9-G11: R9. A9-G12: R7. A9-G13: R19.
- A9-D1: R21. A9-D2: R12. A9-D3: R2. A9-D4: R23. A9-D5: R24. A9-D6: R22. A9-D7: R25. A9-D8: R26.

Task to finding (reverse check):

- R1: A9-U2, A9-U7, A9-G3. R2: A9-U1, A9-D3. R3: A9-W4, A9-G3. R4: A9-W1, A9-G5. R5: A9-W5, A9-U9. R6: A9-G1, A9-G4. R7: A9-U3, A9-G4, A9-G12. R8: A9-U2. R9: A9-U5, A9-G11. R10: A9-G6. R11: A9-U6. R12: A9-W2, A9-W3, A9-D2. R13: A9-U4, A9-G10. R14: A9-G2. R15: A9-U8. R16: A9-G7. R17: A9-G8. R18: A9-G9. R19: A9-G13. R20: A9-U2. R21: A9-D1. R22: A9-D6. R23: A9-D4. R24: A9-D5. R25: A9-D7. R26: A9-D8.

All 35 findings are covered; all 26 tasks map to at least one finding.
