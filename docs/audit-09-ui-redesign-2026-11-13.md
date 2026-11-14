# Audit #9: STELLA UI redesign

**Date:** 2026-11-13
**Audited:** STELLA v0.8.0, live tree `~/workspace/stella/` (read-only audit; nothing in the tree was changed)
**Standard:** the STELLA design brief (`docs/stella-design-brief-2026-11-13.md`), the canonical design rules (`design-rules.md`, U1-U39 + D1-D3, from the BNB UI Design Source File Library), and the library's 24 entries with its four-question filter
**Method:** drove the GUI offscreen (Qt offscreen platform, forge-v2-testenv Python) with a seeded store (3 profiles, 2 projects) and an empty store, at 1100x680 and at 1366x768. Screenshots of every window, measured positions of every control against the viewport, a menu drive with no session, and a sweep of all 348 visible strings for em-dashes and bare ampersands. Probe scripts and screenshots: `~/workspace/stella-a9-scratch/` (`probe.py`, `probe2.py`, `*.png`). Ollama was not running in the sandbox, so the populated state used the real 11-model roster fed through a monkeypatched `list_models`; the empty state used Ollama genuinely down.

## Verdict

The v0.8.0 UI is honest, careful, and well built, and it is not the UI the brief asks for. Every control works, every field explains itself in plain words, and the safety rails (delete confirms, single instance, worker threads) all hold. But the screen a first-time user meets is a long scrolling column of sections in default Qt grey, with training settings on display in three places, no graph anywhere, no job picker, and a whole job (Sleep) below the fold even at 1366x768. Joshua called the v0.4 layout "still extremely confusing"; v0.8.0 rearranged the same parts without changing what the screen is. The redesign in the companion task list does not polish this layout. It replaces the main screen with the brief's flow (pick a model, pick a job, press go) and moves the settings under the hood where the brief puts them.

**Counts: 5 W / 9 U / 13 G / 8 D = 35 findings.** The task list (`audit-09-ui-redesign-task-list.md`) covers all 35 with 26 tasks (6 P0 / 9 P1 / 5 P2 / 6 P3).

## What the current UI is

One main window: a "Menu" button with a nine-action drop-down, a bold header line, an activity dot with status text, a left tree (profiles expand to projects), and a right scrolling session panel. The session panel stacks, top to bottom: a summary line, a Model weights section (status, progress bar, Download model, Cancel), a Train section (dataset pickers, Start/Pause/Resume, progress bar, a loss text line, a checkpoints list, Export GGUF, Run refusal probe, a training log), and a Sleep section (Sleep button, "Dream first" checkbox, a sleep-cycles list). Separate windows hold the profile form, the project form (with the full settings), Settings (home path, Ollama, training defaults, chat model, AI providers, debug report), How to Use (13 topics), and Chat. New Profile is a small dialog with one model combo. The whole thing runs in the default Qt look: no application stylesheet exists anywhere in the tree (see A9-G2).

## Strengths (things that hold, and the redesign keeps)

- **Help lines under every field, in plain words (U20).** The Project and Profile windows explain each field directly underneath it, honestly ("1 fits this PC. Leave it."). This is the copy standard the rebuild should match.
- **Delete confirms default to No, and Escape leaves things untouched (U23/U31).** Verified in code (`gui.py:2317-2328`, `_delete_confirm` sets both default and escape to No).
- **Single instance, geometry persistence, window icon, double-click to open.** All present and working; several audit #4 items were fixed by v0.3.1/v0.4 and still hold.
- **The activity dot and status text always show what the app is doing (U16).** Idle, downloading, training, sleep, job, each with its own color and words.
- **Downloads resume, and the UI says so in plain words.** "If it stops, press Download again: it picks up where it left off, nothing is downloaded twice."
- **The Train panel is above the fold now.** Audit #4's T38 (Start training at y=758 in v0.2) is fixed by the v0.4 restructure: measured live, Start training sits at y=275 at 1100x680. What is still below the fold is Sleep (A9-U3).
- **The "just do it" chat path is the closest thing to the brief's flow in the whole app.** "Say just do it and I will run the whole thing with the usual settings." The redesign makes the window flow match what the chat already promises.
- **Work happens off the UI thread, one job at a time.** Training, sleep, chat, and downloads all run in workers; training and sleep refuse to run together because both would load the base model into 8 GB.
- **No em-dashes and no bare ampersands in any visible string (U33/U11).** All 348 visible strings across every window, plus all 13 How to Use topics and all 8 chat template steps, were swept live: zero found.
- **How to Use opens on "Getting started" with the body already shown.** The first thing a lost user sees is the short path, not an empty pane.

## W: wrong or broken

### A9-W1: New Profile picks the first model for the user

The dialog opens with the model combo already set to the first roster item. Probed live: `currentIndex` is 0 on open, `currentText` is `maternions/minicpm5-heretic:2b`, and the note already reads "Profile name: minicpm5-heretic-2b" before the user has touched anything (screenshot `new-profile-dialog.png`). Create profile is the default button, so pressing Enter creates a profile for a model the user never picked. The combo is populated from `list_models()` with no `setCurrentIndex(-1)`; the Settings window's chat combo does call `setCurrentIndex(-1)` (`gui.py:1187`), so the codebase already knows the right move. Violates U6 (select nothing by default, ever). Only happens when Ollama answers; with Ollama down the combo is empty and the user types. Covered by R4.

### A9-W2: The Profile window contradicts itself about Base ref

The seeded profile's Base ref field shows `lfm3:1.7b`, and directly below it the download label says "No Hugging Face repo set. Set Base ref in the profile window." The field is filled, the label says nothing is set, and the label tells the user to go to the window they are already standing in (screenshot `profile-window.png`, probe2 output). Cause: creating a profile copies the Ollama tag into `base_ref` (merged-list T48), while `weights_status` only counts a value with a slash as a repo. The user sees a filled field and a message saying it is empty. Covered by R12.

### A9-W3: Download model is enabled when there is no repo to download from

With the profile in the no-repo state, the Download model button is enabled in both the main window and the Profile window (probe2: `isEnabled()` True in both). Clicking it does not download; it opens a modal warning (`start_download`, `gui.py:2047-2055`) telling the user to set Base ref. The button promises an action it cannot do, and the guidance arrives after the click as a modal instead of before it as a disabled button or an honest label. Covered by R12.

### A9-W4: The empty-store guidance tells the user to pick something that does not exist

On first launch the session panel says "No training session yet. Pick a project in the list on the left." The list on the left is empty: there is no project to pick, and no button on screen to make one (screenshot `main-empty-1100x680.png`). The only path is Menu, then New profile, then New project, which nothing on the empty screen says. The guidance is not just unhelpful, it is wrong for the state the user is in. Covered by R3.

### A9-W5: Four of nine menu actions are enabled with nothing selected and answer with a modal warning

Driven live on an empty store: Profiles warns "Pick a profile first.", Projects warns "Pick a project first.", New project warns "Pick a profile first, then add a project to it.", Export project warns "Pick a project to export." Each warning is a modal dialog the user must dismiss. Actions that cannot work yet should be disabled until a selection exists, not enabled and scolding. (New profile, Import package, Settings, How to Use, and Chat all work fine with no session.) Covered by R5.

## U: usability

### A9-U1: Training settings are on screen in four places; the brief says the user never sees them

The session summary reads "LoRA rank 8, learning rate 0.0002, 3 epochs." The Project window is a full settings form: Method, LoRA rank, Learning rate, Epochs, Batch size, Max seq len, each with a help line. Settings lists the same five as "Training defaults". And the chat agent's template step 4 names them all again ("Rank, learning rate, epochs, batch size, sequence length. The defaults are fine for this PC."), while the chat greeting offers to run "with the usual settings". The brief is explicit: the backend measures the PC and sets all training settings itself; the user never sees or touches them. Every one of these surfaces is a direct violation of U36, and together they are the single biggest reason the app looks confusing: the screen is full of numbers a five-year-old cannot use and the brief says should not exist. Covered by R2.

### A9-U2: There is no "pick a job" surface

The main window is one scrolling column of sections: download, train, checkpoints, export, probe, log, sleep. Train and Sleep are sections in that column, not jobs the user picks. Re-quantize and distill, shipped in v0.8.0, have no window surface at all: How to Use sends the user to the Chat or to the terminal (`bash stella-cli requant...`, `bash stella-cli distill...`). The brief's core flow, pick a model, pick a job, press go, does not exist as a screen. Covered by R1, R8, R20.

### A9-U3: Sleep is below the fold at both sizes, including his own screen

Measured live: the Sleep button sits at y=754 in a session column 971 px tall, against a viewport of 598 px at 1100x680 and 686 px at 1366x768. A whole job is invisible without scrolling, on the exact screen Joshua uses. Covered by R7 (Sleep becomes a job card like every other job, not a buried section).

### A9-U4: Save project is below the fold in its own window, and half of Settings is hidden

Measured live: the Project window's content is 886 px tall in a 616 px viewport, and the Save project button sits at y=821. The user must scroll to save. The Settings window is worse: 1,165 px of content in a 625 px viewport, so Gemini, Custom, and the Debug report button all sit below the fold in a window that is already 680 px tall on a 768 px screen. Covered by R13.

### A9-U5: Chat makes the user type a model tag by hand

With no chat model picked, the Chat window greets the user with "Which model should I chat with? Type one of these:" followed by eleven raw tags, including `huihui_ai/granite4.1-abliterated:3b` and `maternions/minicpm5-heretic:2b` (screenshot `chat-window.png`). Substring matching exists, but the user still has to type a fragment exactly right, from memory, with no click-to-pick. There is already a perfectly good picker in Settings; the chat should offer clickable model buttons instead. A five-year-old cannot type these tags. Covered by R9.

### A9-U6: Tree rows truncate long model names, with no tooltip anywhere to recover them

Measured live: the tree pane viewport is 235 px wide; the MiniCPM5 row's text is 335 px, so it renders as "MiniCPM5 Driver [driver] (maternio..." at both window sizes. There is exactly one `setToolTip` call in the whole GUI (`gui.py:1769`, the "Dream first" checkbox), so hovering the row tells the user nothing. The user cannot read which model a profile is. Covered by R11.

### A9-U7: The main window at rest is a wall of empty grey boxes

At idle the session panel shows two 0% progress bars and three big blank rectangles (Checkpoints, Training log, Sleep cycles) with nothing in them (screenshots `main-seeded-1100x680.png`, `main-empty-1100x680.png`). Nothing says what to do next; the eye has nowhere to land. The empty state is the state a new user spends the most time in, and it is the least designed screen in the app. Covered by R1.

### A9-U8: No keyboard shortcuts, no visible focus ring

Grep of `gui.py`: no `QShortcut` anywhere, no focus styling anywhere. Keyboard users get the default faint outline and no way to reach the main actions without the mouse. Covered by R15 (library entry 023).

### A9-U9: The menu is a button, not a menu bar

Nine actions in one flat drop-down under a "Menu" button, with no File/Edit/View/Help structure. U38 asks for real Windows-style menus, and the brief repeats it. The flat list also hides the grouping a new user needs: making things, opening things, and getting help are all one undifferentiated column. Covered by R5 (supersedes merged-list T149).

## G: gaps

### A9-G1: No graphs or charts anywhere

Grep of `gui.py`: no QChart, no QPainter graph, no plot of any kind. The only loss readout is one text label: "Step N / total, loss x.xxxx" (`gui.py:2640-2644`, `_on_train_progress`). No speed, no RAM, no time left, no run history. The brief asks for live graphs and stats with a middle-school science software feel: the user watches measurements while the backend adjusts. Today there is nothing to watch. Covered by R6.

### A9-G2: No visual identity of its own

There is no application stylesheet anywhere: `app.styleSheet()` and the main window's `styleSheet()` are both empty strings (probe1), and the only styling in `gui.py` is seven inline snippets (grey help labels, bold headers, activity dot colors). The app runs in the default Qt look and could be any program. U15 asks for pro software with a real identity, never generic SaaS grey. Note for the record: the task brief's premise that gui.py carries a dark stylesheet applied only by `main()` is wrong for STELLA; that lesson came from Pixel Forge, and grepping the tree confirms no `DARK_STYLESHEET` exists here. Covered by R14.

### A9-G3: No first-run onboarding

First launch shows an empty tree, "No training session yet", and a wall of disabled controls. The How to Use "Getting started" topic contains a good five-step path, but it lives inside a dialog the user must open, and nothing on the empty screen points at it. No setup checklist (entry 020), no first-run tiny run (entry 014). Covered by R3 (and R1).

### A9-G4: No glanceable training status card

During a run the only live readouts are a progress bar, the loss text line, and the activity dot. Nothing answers "how is it going" in five seconds (entry 021's test): no epoch, no time left, no speed, no single card to glance at. Covered by R6 and R7.

### A9-G5: No model-fit guidance at pick time

New Profile shows bare tags only: no "what it does", no size, no RAM or fits-this-PC verdict. The user picks blind from eleven cryptic names. U39 asks for guided model and size choices; the brief says model selection shows what the model does and whether it fits this PC. Covered by R4.

### A9-G6: No per-profile project memory

The session is one global slot (`set_session`); switching profiles loses the project context, and returning to a profile does not restore the project the user was working on. Entry 022's face in the current UI. Covered by R10 (supersedes merged-list T110).

### A9-G7: No finish moment

When training ends, `_on_train_finished` (`gui.py:2646-2655`) writes a log line, shows a status-bar message, and refreshes the tree. Nothing marks the finish: no moment, no summary, no "it worked". Entry 008's territory, kept small and cheap. Covered by R16.

### A9-G8: No loading or skeleton states

The New Profile combo populates silently from `list_models()`; with Ollama down the user sees an empty combo and a note, with no "looking for models" state in between. Same for the Ollama status refresh in Settings. Entry 011: never a dead screen. Covered by R17.

### A9-G9: No reduced-motion or accessibility preset

No setting exists and no reduced-motion preference is respected anywhere. Motion today is minimal, so this is not a current pain; it is a gap the redesign must carry so the new motion (entries 001, 002, 009) has an off switch. Entry 015. Covered by R18.

### A9-G10: No collapsible headers in the panels

Settings is one 1,165 px scrolling wall of sections; the session panel is one long column. The brief asks for collapsible headers in panels. Covered by R13.

### A9-G11: Chat shows no plan before it runs

The agent narrates as it goes (`TOOL_NARRATION`, plain words), but never shows "here is what I am about to do" with a chance to stop it. One "just do it" can start a download, create a project, and start hours of training with no preview step. Entry 010. Covered by R9.

### A9-G12: No progress or cancel on GGUF export and the refusal probe

`JobWorker` has no progress signal and no cancel. The activity dot says "job" and the user waits blind; the only way out is to close the app. Merged-list T92 covers this; the redesign folds it into the job card. Covered by R7.

### A9-G13: No before/after view of what a fine-tune changed

The refusal probe reports numbers in a dialog. Nothing shows, side by side, what the base model said and what the fine-tuned model says, before the user commits to a GGUF export. Entry 017. Covered by R19.

## D: details

### A9-D1: The dead "full" method is still listed in the combo

The Project window's Method combo lists `lora` and `full`, with `full` disabled (probe1). A visible option the user can never use. Merged-list T49 covers removal. Covered by R21.

### A9-D2: The download row is duplicated in two windows

Identical Download model, Cancel, and progress bar in the main window and the Profile window, kept in sync by hand (`_on_download_progress` updates both). One source of truth would do. Covered by R12.

### A9-D3: Learning rate is a free-text field

The Project window's learning rate is a `QLineEdit` validated with `float()` only (merged-list T7). Recorded so the removal is deliberate: R2 deletes the field entirely rather than fixing the input. Covered by R2.

### A9-D4: The status bar repeats the session title in slug form

The session title reads "LFM3 Tool Seat / tool-calls" while the status bar reads "Profile: lfm3-tool, project: tool-calls." The same fact twice, in two different namings. Covered by R23.

### A9-D5: "Dream first" is the only tooltip in the app

One `setToolTip` call in all of `gui.py` (line 1769). Nothing else explains itself on hover, including the truncated tree rows (A9-U6). Covered by R24.

### A9-D6: Two taglines

The window title says "STELLA 0.8.0: fine-tune models on your PC" and the header says "STELLA: shape a base model into its proper job". Pick one. Covered by R22.

### A9-D7: How to Use has no search and no link from the empty state

Thirteen topics in a plain list, no search, and the empty main window never points at it. The getting-started path is two clicks away from the screen that needs it most. Covered by R25.

### A9-D8: The Chat window's help line is squeezed at the bottom edge

The two-line help text fits only just inside the fixed 700x520 window (screenshot `chat-window.png`). Cosmetic; fix when the window is rebuilt. Covered by R26.

## Library verdicts: all 24 entries through the filter

The filter (README, canonical copy) asks four questions; failing any one keeps a technique out. Q1: does it make it simpler? Q2: does it survive the toy test? Q3: does it run on his PC (8 GB RAM, no GPU, spinning HDD; transform and opacity only, no layout thrash, no heavy blur per frame)? Q4: does it make the app feel like itself?

| Entry | Verdict | Filter | Why |
|---|---|---|---|
| 001 Micro-interactions | USE, limited | Passes all four | Button press dip to 0.97 over 150 ms and 100-150 ms feedback on real actions only. Cheap transform, no layout thrash. |
| 002 Spring physics | USE, limited | Passes all four | OutBack overshoot on the job-picker open and the finish moment only. Earned, not defaulted. |
| 003 Calm technology | USE | Passes all four | The main screen is calm at rest (a light, a number, a small sparkline) and escalates only on failure. The science-software readout is the identity. |
| 004 Just-in-time GUI | USE | Passes all four | Settings do not exist on screen until the backend cannot decide. The Project window's settings form is deleted, not hidden. |
| 005 Bento grids | USE | Passes all four | Main screen: one hero tile (pick model, pick job, press go), small tiles for RAM, speed, progress. A static grid; nothing moves per frame. |
| 006 Neo-skeuomorphism | SKIP | Fails Q1, Q4 | Music and audio first; a trainer has no knobs to skeuomorph. It would decorate without simplifying and it is not STELLA's feel. |
| 007 Liquid Glass | SKIP | Fails Q3, Q4 | Readability risk on text-heavy screens, and per-frame blur cost on the Vega 3 and spinning HDD. |
| 008 Delight done right | USE | Passes all four | The finish moment only: a brief gold moment when a job completes, under 300 ms, one-shot, never looping. |
| 009 Shape morphing | USE, limited | Passes all four | The job picker becomes the job: the picked job tile morphs into the running-job card, under 400 ms, interruptible. |
| 010 AI-native patterns | USE, limited | Passes all four | Chat shows its plan before it runs, streams replies, and shows trust cues (what it will do, what it did). |
| 011 Skeleton screens | USE, limited | Passes all four | Never a dead screen: the model list shows skeleton rows while Ollama answers, paired with real numbers when they arrive. |
| 012 Progressive disclosure | USE | Passes all four | Minimum now, rest when asked. Already U21; the redesign's core move (settings under the hood). |
| 013 Diegetic UI | SKIP | Fails Q1, Q4 | There is no fiction to live inside for a trainer. Nothing to be diegetic about. |
| 014 Teach by playing | USE | Passes all four | First run is a real tiny run (the 20-example sample dataset), not a setup wizard. Feedback within 0.5 s. |
| 015 Accessibility presets | USE | Passes all four | A reduced-motion preset and a larger-text preset, one place, plain words. The off switch for the new motion. |
| 016 Pie menus | SKIP | Fails Q1, Q2 | Tool pickers for drawing and 3D apps. Four jobs do not need a radial menu, and radial menus are fiddly for the toy test. |
| 017 See it before you commit | USE, limited | Passes all four | Before/after eval preview before GGUF export: show what the fine-tune changed before the user commits. Cheap text comparison, no heavy render. |
| 018 Scrub through time | SKIP | Fails Q1 | Needs thumbnails and a visual timeline; STELLA has no visual timeline. Run history is a list, not a scrubber. |
| 019 Optimistic UI | SKIP | Fails Q1 | Training and export are long, fallible, and destructive-adjacent; never optimistic. The small list actions that could be optimistic (rename, delete) need confirmation instead. Adds rollback complexity for no gain here. |
| 020 Setup checklist | USE | Passes all four | First profile in three steps, first step honestly already ticked, dismissible, never a reappearing modal. |
| 021 Glanceable surfaces | USE | Passes all four | Training status card: epoch, loss, time left, one sparkline. Passes the five-second test. |
| 022 Per-context profiles | USE | Passes all four | One profile per training job; the job's settings follow it; the active profile is visible at a glance. |
| 023 Focus-first navigation | USE | Passes all four | Visible focus ring, tab in visual order. Every app's keyboard focus should be unmistakable. |
| 024 Clip launcher | SKIP | Fails Q1, Q4 | Firing clips is the job in a DAW. STELLA runs one long job at a time. |

**17 in (7 full, 10 limited), 7 out.** The seven the INDEX already mapped to STELLA (003, 004, 005, 008, 020, 021, 022) all pass and all made it in.

## What the redesign keeps vs replaces

**Keeps.** The tree (profiles expand to projects) as the library of what exists, with session restore. The plain-words help lines under every field (U20) as the copy standard. The activity dot and status text (U16) as the always-on state readout; the redesign gives it a bigger job (the glanceable card) but keeps the light. The How to Use index (U22) and its 13 topics, with search added and a link from the empty state. Delete confirms defaulting to No. Single instance, geometry persistence, the window icon, double-click to open. Download resume and its plain-words explanation. The "just do it" chat path. The worker-thread discipline and the one-job-at-a-time guard. The debug log layer (U12).

**Replaces.** The scrolling session column becomes the bento main screen: one hero tile (pick model, pick job, press go), job cards, and glanceable tiles. The Project window's settings form goes away entirely; the window keeps name, dataset, and notes, or folds into the job picker. The Menu button becomes a real menu bar. The session summary's settings line goes away. The New Profile dialog becomes a model picker with fit guidance and no default selection. The Chat model pick becomes click-to-pick, and the chat shows its plan before running. The Settings window's training defaults go away, and the window gets collapsible sections. The default Qt look becomes STELLA's own stylesheet. The loss text line becomes live graphs. The Sleep section becomes a job card like every other job. Re-quantize and distill move from chat and terminal into the job picker.

**Depends on v0.9.** R2 (settings leave every screen) is blocked on v0.9's auto-config backend: the settings cannot leave the screen until the backend decides them. The UI rebuild lands after v0.9 for that reason. The other P0s (R1, R3, R4, R5, R6) do not depend on auto-config, but R6 needs the engine to keep loss history (the worker already emits step, total, and loss per step; the UI must keep the series).

## What I could not check

- **Offscreen only, no real PC.** Colors, fonts, and the real Mint theme may differ from the offscreen render, and spacing may shift slightly under his desktop theme. The measurements (pixel positions, viewport sizes) are exact for the offscreen build; treat them as accurate to a few pixels on his PC.
- **No Ollama in the sandbox.** The populated state used the real 11-model roster fed through a monkeypatched `list_models`. Real Ollama timing (fetch latency, how the list populates) was not observed live.
- **No training run was started.** No training deps and no weights exist in the sandbox, so the live training readouts (loss line updates, pause/resume, the finish) were verified from code, not from a running job.
- **No real download was run.** Download progress and cancel were verified from code.
- **No live chat agent run.** No model was available to talk to; the model-pick flow was probed live, the agent loop was read from code.
- **1366x768 is a resized window, not a real screen.** His PC's taskbar takes some of the 768 px, so usable height is a little less than the screenshots show; the below-the-fold findings are, if anything, understated.
- **Focus visibility was checked by code** (no focus styling exists), not by tabbing through on a real screen.

## Screenshots (in `~/workspace/stella-a9-scratch/`)

`main-empty-1100x680.png`, `main-seeded-1100x680.png`, `main-seeded-scrolled-1100x680.png`, `main-seeded-1366x768.png`, `profile-window.png`, `project-window.png`, `settings-window.png`, `howto-window.png`, `howto-window-topic0.png`, `chat-window.png`, `new-profile-dialog.png`. Probe scripts: `probe.py`, `probe2.py`.
