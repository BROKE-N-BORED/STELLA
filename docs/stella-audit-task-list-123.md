# STELLA Audits #1–#9 + Repo-Audit Verdict — Merged Task List (Profiles + Projects + Export/Import + GUI + CLI + Installer + MetaMorphAi + Training Engine + UI Redesign + Verdict)

**Sources:**
[audit-01-profiles-2026-11-12.md](audit-01-profiles-2026-11-12.md)
(Profiles audit, 2026-11-12),
[audit-02-projects-2026-11-12.md](audit-02-projects-2026-11-12.md)
(Projects audit, 2026-11-12),
[audit-03-export-import-2026-11-12.md](audit-03-export-import-2026-11-12.md)
(Export/Import audit, 2026-11-12), all against v0.1 / commit
e28db915,
[audit-04-gui-2026-11-12.md](audit-04-gui-2026-11-12.md)
(GUI audit, 2026-11-12, against v0.2 / commit 9a821e07 — the first
audit run against v0.2, covering the main window and the Train
panel), and
[audit-05-cli-2026-11-12.md](audit-05-cli-2026-11-12.md)
(CLI audit, 2026-11-12, against v0.2 / commit 9a821e07), and
[audit-06-installer-icon-2026-11-12.md](audit-06-installer-icon-2026-11-12.md)
(Installer + icon audit, 2026-11-12, against v0.2 / commit
9a821e07), and
[audit-07-metamorph-2026-11-12.md](audit-07-metamorph-2026-11-12.md)
(MetaMorphAi hooks audit, 2026-11-12, against v0.2 — the report was
written 2026-11-13 from a fresh run after the first auditor was
interrupted overnight and left no file), and
[audit-08-training-engine-2026-11-13.md](audit-08-training-engine-2026-11-13.md)
(Training engine audit, 2026-11-13, against v0.3 — train.py, gguf.py,
and probe.py in full, plus the tests and CLI/GUI surfaces that call
them; sleep.py out of scope), and
[audit-09-ui-redesign-2026-11-13.md](audit-09-ui-redesign-2026-11-13.md)
(UI redesign audit, 2026-11-13, against v0.8.0 / commit ad1d1f1c —
the current window measured live against the STELLA design brief,
the canonical design rules, and the BNB UI Design Source File
Library's 24 entries with its four-question filter). Standalone per-audit lists:
[audit-01-profiles-task-list.md](audit-01-profiles-task-list.md) (18
tasks),
[audit-02-projects-task-list.md](audit-02-projects-task-list.md) (18
tasks),
[audit-03-export-import-task-list.md](audit-03-export-import-task-list.md)
(20 tasks),
[audit-04-gui-task-list.md](audit-04-gui-task-list.md) (25 tasks),
[audit-05-cli-task-list.md](audit-05-cli-task-list.md) (18 tasks),
and
[audit-06-installer-icon-task-list.md](audit-06-installer-icon-task-list.md)
(25 tasks), and
[audit-07-metamorph-task-list.md](audit-07-metamorph-task-list.md) (19
tasks), and
[audit-08-training-engine-task-list.md](audit-08-training-engine-task-list.md)
(31 tasks), and
[audit-09-ui-redesign-task-list.md](audit-09-ui-redesign-task-list.md)
(26 tasks), and the repo-audit verdict
[repo-audit-verdict-2026-11-12.md](repo-audit-verdict-2026-11-12.md)
(33 findings, R1–R33, from the GitHub repo-audit thread — it has no
standalone task list; its findings fold into this merged list
directly).

**This file is a list only.** Nothing here has been fixed or built.
Each task turns one or more audit findings into work with a verifiable
"done". Tasks are renumbered T1..T194 in priority order (P0 first, then
P1, P2, P3), and ranked by importance within each priority — highest
first — so the list reads as a build order, not an audit-merge order.
The ranking rule, per priority: within P0, data loss / corruption /
silent wrong state first, then crashes on normal paths, then
install-breakers that leave a dead app; within P1, crashes and
data-risk first, then daily friction (things hit every session), then
correctness issues that mislead; within P2, missing capabilities
needed for real use first, then inconsistencies, then nice-to-haves;
within P3, user-visible polish first, then scale/edge polish. Where a
task is a prerequisite for another, it comes first (see the dependency
order at the end of this file); no task moved between priorities in
the reorder.

**Finding IDs are prefixed to disambiguate the audits and the
repo-audit verdict:** A1- = from audit #1 (Profiles), A2- = from
audit #2 (Projects), A3- = from audit #3 (Export/Import), A4- = from
audit #4 (GUI), A5- = from audit #5 (CLI),
A6- = from audit #6 (Installer + icon), A7- = from
audit #7 (MetaMorphAi hooks), A8- = from audit #8 (Training engine), A9- = from audit #9 (UI
redesign), R- = from the repo-audit verdict. Each task carries an **Origin** line naming the
standalone task(s) it came from.

**Merged (deduped) tasks:** fifteen fixes are genuinely shared and are
built once, not twice — damaged-row (A1-W1 + A2-W4 → T3),
trash-on-delete (A1-W5 + A2-W8 → T23), CLI parity (A1-T7 + A2-T11 →
T87, one `cli.py` change), profile export (A1-G4 + A3-W7/G3 → T86),
recipe export (A2-G6 + A3-G2 → T170), dirty tracking (A2-W1 + A4-W5
→ T2, both panels plus the completion refresh), Ollama cache
(A1-W4 + A4-W7 → T43), import trust-boundary window face (A3-W2 +
A4-W8 → T1), status discipline (A3-U1 + A4-U3 → T50), tooltips
(A4-D16 split: row tooltips → T122, settings tooltips → T160), status +
health display (A4-D22 split: status → T53, health → T163), the menu
icon (R4 + A6-W1/W2 → T14, promoted to P0 — one install.sh pass),
the double-click installer + README install section (R3 + A6-W3/U1
→ T64), the window icon (A4-U6/R18 + A6-U5 → T127), and version pins
(R13 + A6-W13 → T130). The icon fix and the desktop-installer fix
each absorb two audit #6 standalone tasks, so six standalone tasks
fold away in total. The import trust-boundary fix (A3-W1 + A3-W2 +
A3-W13 → T1) is one task by the audit's own design. The package
format (T40) is the shared foundation for profile export (T86) and
recipe export (T170): audit #3 settled the format (versioned, named
kinds), so T86 and T170 build on T40 instead of waiting on the audit.
The New Profile dialog went the other way: it was one item inside
the old small-UI-fixes task, but audit #4 raised it to P0, so it is
split out into its own P0 task (T11) and removed from T122. Audit #4
also corrected audit #1's U3 (the dialog is not a separate window at
all — audit #1's report has been corrected in place). A6-U2 splits
across the README install section (T64) and the success message
(T136); A6-D10 splits across the pins (T130) and the install receipt
(T139, record side). Audit #7 folds four standalone tasks into existing ones: the
string-metamorph verify crash (A7-W5 → T1, the A3-W2
re-confirmation), the unreachable metamorph notes (A7-W8/U3 → T114),
the name-only New Project (A7-W9/U4 → T113), and the CLI mode change
(A7-G7 → T87, the update-project `--metamorph` flag); the shared
defensive reader (A7-D8) is built once in T37 and consumed by T38,
T39, and T177, and A7-D15 splits across T87 (update) and T176 (help
text). Audit #5 folds six standalone pieces into existing tasks:
the --steps cap (A5-W3 → T56, the R11 task), the corrupt-profile
warning (A5-W9 → T3), the orphan-profile import (A5-W10 → T1), the
CLI string-metamorph instance (A5-W2 → T39), the missing commands
(A5-G1/G2/G3 → T87), and the verify command (A5-G4 → T105); the
remaining seventeen become seventeen new tasks (T4–T5, T25–T27,
T48, T51, T88, T91, T108–T111, T142, T161, T172, T187).
Audit #8 folds five standalone tasks into existing ones: the
engine one-job lock (A8-W7/D5 → T29, the train-vs-job hole plus
the OOM math), the engine settings-validation half (A8-W8/D6 →
T6, the loop's crash points), the HF error wrapping (A8-W9/D7 →
T5, the raw traceback from a bad base), the cap/resume composition
(A8-W12/D9 → T56, the "already at step 4 of 3" error), and the
F16 intermediate cleanup (A8-W13/D10 → T26, the ~3.4 GB left
behind by a failed quantize); A8-D11's quant half re-confirms T27
while its executability half is a new task (T102), and the
checkpoint-size evidence extends T150; the remaining twenty-six
become twenty-six new tasks (T30–T35, T92–T103, T152–T159).
Everywhere else, tasks stay separate; relationships are noted
in the Covers line.

**Repo-audit verdict (R1–R33):** twelve verdict findings fold
into existing tasks (the weights round-trip now restores probe
results and corrects the status, R1 → T41; the dead "full"
option is removed, not just warned about, R7/R20 → T55; the
re-verified UI flaws fold into their existing tasks), one splits
(R22: shortcuts → T127, menu bar → T169), and the remaining twenty
become twenty-one new tasks (T10, T14, T22, T24, T28, T52, T56, T64–T65, T83, T85, T89–T90, T120, T129–T131, T151, T169, T173–T174).
Audit #5 (CLI) has now merged: R11 = audit #5 W3,
deduped into T56 (one --steps task, not two).

**Audit #6 (Installer + icon):** 56 findings (15 W + 9 U + 7 G +
25 D). Thirteen fold into four existing tasks — the menu icon (R4
+ A6-W1/W2, promoted to P0 as T14), the double-click installer +
README install section (R3 + A6-W3/U1, T64), the window icon
(A4-U6/R18 + A6-U5, T127), and version pins (R13 + A6-W13, T130) —
and the remaining forty-three become nineteen new tasks (T42, T62–T63, T66–T69, T132–T140, T184–T186). Audit #6 also verified the zip's stored
modes are correct (scripts 0o100755), so the exec-bits task (T65)
stands as written for the clone path.

**Audit #7 (MetaMorphAi hooks):** 40 findings (11 W + 6 U + 7 G +
16 D). The mode does nothing for either reading — proven behaviorally
(identical tiny training runs in `morph` and `compress` gave the same
final loss to all 16 digits and byte-identical adapter weights). Four
standalone tasks fold into existing tasks (A7-W5 → T1, A7-W8/U3 →
T114, A7-W9/U4 → T113, A7-G7 → T87) and the remaining fifteen become
fifteen new tasks (T37–T39, T70–T73, T141, T143–T144, T175–T177, T183, T188). No P0s: the crashes
found all need a hand-corrupted file, and the inert mode is
documented, not hidden.

**Audit #5 (CLI):** 47 findings (13 W + 9 U + 7 G +
18 D). The CLI is Stella's second surface — and its headline
safety feature was a coin flip: Ctrl+C paused correctly only when
the signal missed the buffered print window (A5-W1). Six
standalone pieces fold into existing tasks (A5-W3 → T56, A5-W9 →
T3, A5-W10 → T1, A5-W2's CLI metamorph instance → T39, A5-G1/G2/G3
→ T87, A5-G4 → T105) and the remaining seventeen become seventeen
new tasks (T4–T5, T25–T27, T48, T51, T88, T91, T108–T111, T142,
T161, T172, T187). Two P0s: the Ctrl+C crash (T4) and the missing
catch-all (T5).

**Audit #8 (Training engine):** 55 findings (20 W + 6 U + 11 G +
18 D). The engine's core loop is sound — completion-only masking
exact, merge math exact to 0.0, pause/resume continues from the
right place — but nothing about a run is reproducible (torch is
never seeded: the same run twice gives a different adapter, max
weight diff 2.424e-01), the refusal probe is brittle both ways
(6/10 crafted replies misjudged) and passes a silent model, and
the GGUF path leaves multi-GB litter on failure and breaks on
spaced paths. Five standalone tasks fold into existing tasks
(A8-W7/D5 → T29, A8-W8/D6 → T6, A8-W9/D7 → T5, A8-W12/D9 → T56,
A8-W13/D10 → T26) and the remaining twenty-six become twenty-six
new tasks (T30–T35, T92–T103, T152–T159). No P0s: nothing here loses
data or crashes on a normal path.

**Priority key:** P0 = data loss / silent failure, fix first.
P1 = real functional defect or daily friction. P2 = missing capability
or inconsistency. P3 = polish, display, and scale.

**Effort key:** S = a focused change in one or two files, a day or
less. M = a change across model + GUI + tests, or a small design
decision plus implementation. L = a multi-part build or a design that
needs Joshua's direction on scope first.

**Counts:** 194 tasks — 20 P0, 62 P1, 67 P2, 45 P3. (18 + 18 + 20 + 25
+ 18 + 25 + 19 + 31 + 26 standalone tasks minus 27 merges, plus 21 new tasks from the
repo-audit verdict; 12 verdict findings fold into existing tasks
and 1 splits; 13 audit #6 findings fold into 4 existing tasks; 4
audit #7 standalone tasks fold into existing tasks; 6 audit #5
pieces fold into existing tasks; 5 audit #8 standalone tasks fold
into existing tasks. 5 audit #9 tasks supersede existing tasks and
2 moot existing tasks outright (2 more partly moot one); superseded
and mooted tasks stay in the list, marked, so the coverage map still
accounts for their findings.)

---

## P0 — fix first

### T1 — Trust-boundary import: strict manifest validation + atomic import

- **Origin:** audit #3 T1 + audit #4 T8 (merged — one fix; the window face); audit #5 T9 (W10 re-verified on the CLI, merged — same fix)
- **Covers:** A3-W1, A3-W2, A3-W13, A3-D2, A3-D3; A4-W8, A4-D8; A7-W5, A7-D8; A5-W2, A5-W10, A5-D8
- **Effort:** M
- **Problem:** `verify_export` checks the manifest's shape but never
  the *types* of any field, and import is not atomic — so a
  hand-edited or foreign package can crash Stella or leave partial
  state. Probed, each against a hand-edited manifest: `metamorph`
  as a string or int → raw `AttributeError` at `export.py:128`;
  `settings` as a string → raw `ValueError` from
  `merged.update(settings)` *after* the profile was created,
  leaving an orphan empty profile in the home (A3-W1); profile
  `config` as a string → raw `ValueError`; `dependencies` as a
  string → **silently accepted and corrupted** — `"torch"` was
  stored as `['t', 'o', 'r', 'c', 'h']`; `settings` as a list of
  pairs → silently accepted; `status: "banana"` → silently
  accepted. Neither the GUI nor the CLI catches these: both catch
  only `StellaError` (`gui.py:588-591`, `cli.py:136-138`). Probed
  in the driven GUI, the `ValueError` escaped the handler, **no
  warning dialog appeared at all**, and the list showed 0 rows
  while the orphan profile sat on disk; on the CLI it is a raw
  traceback, exit 1, no `stella:` prefix. Separately (A3-W13),
  `import_export` returns the manifest's raw names while the store
  lowercases them — importing `Zebra-Proj` returned profile
  `Zebra-Proj` but stored `zebra-proj`, and the GUI then selected
  the **wrong profile** (row 0, `aaa-first`). Import is the trust
  boundary — packages come from other machines, other people, and
  hand-edits — and it is the one place Stella must never crash on
  bad input. Audit #4 re-verified this in v0.2 (A4-W8): the raw `ValueError` still escapes `import_package` (`gui.py:734`, which catches only `StellaError`), no warning dialog appears, and the orphan profile is invisible in the list because the refresh runs only on the success path. Audit #7
  re-confirmed the string-metamorph crash (A7-W5): a string metamorph
  in the manifest still raises `AttributeError`, now at
  `export.py:141` — the line moved as the file grew, the bug did not.
  The fix is the same strict validation; the shared defensive reader
  (T37) is the implementation for the metamorph field. Audit #5
  re-verified the import instances on the CLI (A5-W2/A5-W10): a
  manifest whose `settings` is a string crashed with a raw
  `ValueError` — and left the newly-created profile behind, the
  same non-atomicity as A3-W1; a string metamorph crashed with
  `AttributeError`.
- **Fix:** D2 — validate the manifest schema strictly in
  `verify_export`: types for every field (settings and config must
  be dicts, dependencies a list, metamorph a dict, dataset ref and
  status strings), the metamorph mode enum, and the version range
  from T40; every failure a `StellaError` with a plain message.
  Nothing downstream should ever see a manifest field it has not
  already validated. Normalize slugs once, at import start
  (A3-W13), so the returned names match the stored names. D3 —
  make import atomic: validate everything first, then write; on
  any failure, roll back (remove the profile/project just created)
  or stage the whole import in a temp directory and move it into
  place last. A failed import must leave the home exactly as it
  was. Add a last-resort catch in the GUI handler so an
  unexpected exception still surfaces as a readable error, never a
  raw crash. (The CLI's catch-all is the traceback-hardening task.) The GUI handler must also refresh the lists on failure (A4-D8), so a failed import never leaves the window showing a home that does not match the disk. (Status validation reuses the lifecycle enum from T53
  once it lands; until then, reject non-string statuses. Settings
  *value* ranges are T6's model validation — this task covers
  types and shape at the boundary.)
- **Done:** Each probed bad manifest (metamorph string/int,
  settings string/list, config string, dependencies string,
  status `banana`, uppercase names) is refused with a readable
  `StellaError` and leaves the home untouched — no orphan profile,
  no corrupted fields. The GUI shows a warning dialog for each;
  the CLI prints a `stella:`-prefixed error and exits 1 with no
  traceback. Importing `Zebra-Proj` selects `zebra-proj` in the
  GUI. Tests: one per probed variant, atomicity (home byte-identical
  after a failed import), normalization (returned names equal the
  stored names). A failed import refreshes the lists, so the window matches the disk even when the import fails.
- **Status:** DONE in v0.9.0 (2026-11-13) — strict manifest schema (types only, no format versioning), slug normalized once at import start, atomic import via staging dir + move, GUI last-resort catch + refresh-on-failure. Verified by coordinator from a fresh unzip: 467 passed / 22 skipped.

### T2 — Dirty tracking, or auto-save on switch (both detail panels)

- **Origin:** audit #2 T1 + audit #4 T5 (merged — one fix); extended by the repo-audit verdict (R25)
- **Covers:** A2-W1, A2-U1, A2-D1; A4-W5, A4-D5; R25
- **Effort:** M
- **Note:** Audit #9 R2 moots the settings half (dirty tracking keeps only name, dataset, notes); the rest of this task stays open.
- **Problem:** There is no dirty tracking anywhere. Edit the notes or
  any field, click another project, and `_show_project_detail`
  reloads from disk — the edits are gone with no warning, no prompt,
  no asterisk. Probed live: typed "UNSAVED edit" into the notes and
  changed the display name, switched projects and back — notes
  reverted to the saved text, display name reverted to the slug.
  Edited fields look identical to saved ones (A2-U1). The same flaw
  covers the profile detail panel (edit a role, switch profiles,
  lose it): the audit states one fix must cover both panels. Audit #4 re-verified the loss in v0.2 (A4-W5) and found a second trigger: `_on_train_finished` refreshes the projects when a run completes, which reloads the detail from disk and discards any edits the user made *during* the run. This is
  a data-loss bug in the program's main daily action (keeping notes
  during a fine-tune). The verdict adds (R25): notes have no visible
  save affordance of their own — the notes editor sits under the
  project Save button with no marker of its own, so an edited note
  looks saved until it is lost.
- **Fix:** Track dirty state for both detail panels (project and
  profile). Mark edited fields (e.g. an asterisk on the Save button
  or a "modified" indicator) and, on leaving a panel with unsaved
  edits, either prompt ("Save changes to this project? Save /
  Discard / Cancel") or auto-save on switch — pick one behavior and
  apply it identically to both panels. Do not prompt when nothing
  changed. The fix must also cover the completion refresh: edits made during a run must survive the run finishing (prompt or auto-save before the refresh, or preserve the in-memory edits across it). The notes editor gets its own visible save affordance: the notes area shows its modified state (e.g. a "modified" marker on the notes section) and its own save control, so the user can see and save notes without hunting for the project Save button.
- **Done:** Edit project notes, switch projects, switch back: the
  edits are preserved (auto-save) or a prompt appeared and the
  choice was honored. Same for a profile role edit across a profile
  switch. No prompt appears when nothing was edited. Edits made during a training run survive the run finishing. The notes area shows its modified state and offers its own save. Tests: GUI tests for the switch-with-edits path on both panels, the completion-refresh path, and the no-prompt-when-clean path.
- **Status:** DONE in v0.10.0 (2026-11-13) — dirty tracking in both detail windows: snapshot-based is_modified, title asterisk, Save/Discard/Cancel prompt on close and on rename (the PROMPT pick, applied identically to both panels), notes-only save, edits survive the train-finish refresh. Pinned by 8 T2 tests.

### T3 — Show corrupt manifests as damaged rows, never silently vanish (profiles + projects)

- **Origin:** audit #1 T1 + audit #2 T4 (merged — one fix); audit #5 T9 (W9 re-verified on the CLI, merged — same fix)
- **Covers:** A1-W1, A1-D4; A2-W4, A2-D4; A5-W9, A5-D8
- **Effort:** M
- **Problem:** Both list functions swallow parse errors and skip the
  row with no warning, no row, no log. Probed on both sides:
  corrupting a `profile.json` removed the profile (and all its
  projects) from the GUI and CLI entirely, and corrupting a
  `project.json` removed the project (settings, notes, and from v0.2
  checkpoints) the same way — while a direct `get_profile` /
  `get_project` still raises a clear "not valid JSON" error. The home
  is meant to be hand-editable, so a hand-edit typo is the most likely
  cause — the user doing exactly what the docs invite is the user most
  likely to hit this. No test covers it on either side. Audit #5 re-verified the
  profiles side on the CLI (A5-W9): a home with one corrupt
  `profile.json` listed the rest and exited 0 with no warning at
  all, and `projects` on the corrupt profile printed `No projects
  in profile 'broken'.` and exited 0.
- **Fix:** `list_profiles` and `list_projects` (and both GUI list
  builds) must surface a broken manifest instead of skipping it: a
  greyed "damaged" row showing the slug and the parse error, plus a
  Repair action that opens the JSON in the text editor. Keep the
  folders untouched; the data is still on disk and the UI must say
  so. One shared implementation across both lists, not two copies.
- **Done:** Corrupt a `profile.json` and a `project.json` by hand,
  open Stella: both appear as greyed rows with their error text;
  Repair opens the file; fixing the JSON by hand and refreshing
  restores both normal rows. New tests: a corrupt manifest is
  reported (not skipped) by both list paths, and the GUI shows the
  damaged row in both panes.
- **Status:** DONE in v0.10.0 (2026-11-13) — broken manifests surface as damaged rows, not silent skips: greyed + italic in the GUI tree (click = status message, double-click opens the manifest for repair), "(damaged: ...)" rows in the CLI lists, skipped by session restore and rename. One shared implementation (_damaged flag in the model).

### T4 — Ctrl+C must pause the run, not crash it

- **Origin:** audit #5 T1
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
  keypress, write it with `os.write(1, ...)` instead. (Second
  Ctrl+C force-quit is T108; the paused-summary wording is T109.)
- **Done:** SIGINT mid-run pauses cleanly — checkpoint saved, exit
  0, `Paused at step N` printed once; `--resume` continues from
  the checkpoint. Tests: subprocess Ctrl+C-pause test against a
  stubbed or tiny training loop (the crash shipped because nothing
  tested the pause — see T142).
- **Status:** DONE in v0.9.0 (2026-11-13) — the print inside cmd_train's _sigint handler is deleted; the handler sets the stop flag only and the "paused" event prints. Pinned by a subprocess Ctrl+C-pause test (tests/_ctrlc_driver.py).

### T5 — `main()` must catch everything; the list commands must read defensively

- **Origin:** audit #5 T2
- **Covers:** A5-W2, A5-D2; A8-W9, A8-D7
- **Effort:** S
- **Problem:** `main()` catches only StellaError
  (`cli.py:287-293`); every other exception escapes as a full
  traceback, exit 1. Verified instances in v0.2: `profiles` on a
  home with a valid-JSON profile manifest missing `"name"` →
  `KeyError: 'name'` at `cli.py:40` (`p['name']` with no default),
  crashing the whole list (`get_profile` sets a default name,
  `list_profiles` does not); `projects` on a project whose
  `metamorph` is a string → `AttributeError: 'str' object has no
  attribute 'get'` at `cli.py:51`; `export` with a destination
  that is a file → `NotADirectoryError` traceback; `import` of a
  manifest with `settings` as a string → `ValueError` traceback
  (`model.py:305`); with `metamorph` as a string →
  `AttributeError` traceback (A3-W1/W2, re-verified on the CLI);
  and the W1 `RuntimeError`. A user who hand-types commands and
  gets a traceback has no idea what went wrong or what to do next.
  The StellaError discipline shows the intended behavior; the
  catch-all is missing. Audit #8 adds the engine instance (A8-W9):
  `load_base_model` calls `AutoTokenizer.from_pretrained` /
  `AutoModelForCausalLM.from_pretrained` with no error wrapping —
  on an empty local dir it raised a raw `ValueError` ("Couldn't
  instantiate the backend tokenizer…"); a bad repo id, a network
  failure, or corrupt weights will surface the same way.
- **Fix:** D2 — wrap the dispatch in `except Exception` that prints
  `stella: <plain message>` to stderr and exits 1, with the
  traceback available behind a `--verbose`/`--debug` flag (see
  T172). Separately, make the list commands defensive:
  `p.get("name")` with a fallback in `cmd_profiles`, and a type
  check on `metamorph` in `cmd_projects` (through the shared
  defensive reader from T37), so one bad manifest degrades to a
  warning line instead of killing the whole list. The import
  instances are fixed at the boundary by T1's strict validation
  (this task is the last-resort net, not the validation); the
  string-metamorph CLI instance is covered by T39's reader work.
  D7 (A8): wrap the `from_pretrained` calls in
  `load_base_model` so an HF load failure raises a StellaError
  naming the repo/path and the likely cause ("not a model folder",
  "no network?", "repo not found").
- **Done:** Every probed bad input prints one clean `stella:` line
  on stderr, exit 1, no traceback (unless `--verbose`); `profiles`
  lists the rest with a warning line for the nameless manifest;
  `projects` lists the rest with a warning row for the
  string-metamorph project. Tests: nameless manifest, string
  metamorph, file-destination export, bad import manifest — all
  clean exits. An HF load failure on a bad repo id or an empty dir
  prints one clean `stella:` line naming the cause.
- **Status:** DONE in v0.9.0 (2026-11-13) — main() catch-all: StellaError and unexpected exceptions print one plain-words line on stderr and exit 1, no raw traceback on the default path; defensive .get("name") in cmd_profiles; HF load failures wrapped as StellaError.

### T6 — Validate settings in the model, once, everywhere

- **Origin:** audit #2 T2
- **Covers:** A2-W2, A2-D2; A2-W7 (model part — method enum); A8-W8, A8-D6
- **Effort:** M
- **Note:** Audit #9 R2 moots the user-facing half (validation moves to the backend auto-config); the rest of this task stays open.
- **Problem:** `update_project` merges any settings dict without
  checking a single value. Probed: rank -5, epochs 0, batch size 0,
  learning rate -0.5, max seq len 999999, and an unknown key `foo`
  were all stored without complaint — and `method="banana"` was
  stored too (A2-W7). The GUI spinboxes constrain only the GUI path;
  the CLI, imports, and hand-edits bypass everything. Training
  (v0.2) will receive nonsense settings and fail cryptically — or
  worse, "train" for 0 epochs and report success. Audit #8 probed
  the engine half (A8-W8): the loop converts settings with bare
  `int()` / `float()` and never range-checks them — rank "banana" →
  raw ValueError, grad_accum=0 → ZeroDivisionError, batch_size=0 →
  ZeroDivisionError, lr -0.5 → ValueError from AdamW, epochs=0 → a
  confusing StellaError, and worse, checkpoint_steps=-1 runs fine
  while silently disabling all mid-run checkpoints and
  warmup_steps=-3 runs fine while silently warping the LR schedule.
  The GUI spinboxes constrain the normal path; this bites on
  hand-edited project.json — the file the docs tell users they can
  fix by hand.
- **Fix:** Validate inside `create_project` / `update_project`, so
  the GUI, CLI, imports, and hand-edits all get the same rules:
  method must be one of `lora`, `full`; rank an integer 1–64; epochs
  an integer 1–100; batch size an integer 1–32; max seq len an
  integer 128–32768; learning rate a finite number in the sane range
  (defined with T7); unknown keys rejected with a `StellaError`
  naming the key. Every rejection must say which value was wrong and
  what is accepted. (Manifests that already contain bad values — hand-edited before this lands — are handled by T21's defensive fill, which falls back to defaults instead of aborting.)
  D6 (A8): validate once more at the top of `train_project` — the
  engine-side half — range-checking every numeric setting (rank ≥ 1,
  lr > 0, epochs ≥ 1, grad_accum ≥ 1, batch ≥ 1, seq ≥ 8,
  checkpoint_steps ≥ 0, warmup ≥ 0, seed any int) and raising a
  StellaError naming the setting, so a bad value is refused before
  the loop starts even if it reached the project file by hand.
- **Done:** Each probed bad value (rank -5, epochs 0, batch 0,
  lr -0.5, seq 999999, unknown key `foo`, method `banana`) is now
  rejected with a readable message; the defaults and all valid values
  still save. The GUI, CLI, and import paths all hit the same rules
  (one bad value tested through each path). Tests for every rule plus
  unknown-key rejection. The engine-side cases (rank "banana",
  grad_accum=0, checkpoint_steps=-1, warmup_steps=-3) are refused
  with a readable message naming the setting.
- **Status:** DONE in v0.9.0 (2026-11-13) — settings validated in the model (SETTING_RULES, ranges matching the chat's), _write_json with allow_nan=False, engine range checks in run_training_loop (RUN_SETTING_RULES).

### T7 — Learning rate as a real numeric input with a sane range

- **Origin:** audit #2 T3
- **Covers:** A2-W3, A2-U3, A2-D3
- **Effort:** S
- **Status:** MOOTED by T16 (Audit #9 R2) — the settings surface goes away entirely; nothing to build here. Kept in the list, marked, so the coverage map still accounts for its findings.
- **Problem:** The GUI's only learning-rate check is `float(...)`,
  and `float()` accepts `"inf"`, `"-inf"`, and `"nan"`. Probed:
  saving lr=inf wrote a bare `Infinity` literal into `project.json`
  — not valid JSON for any tool except Python's lenient parser. The
  field is a bare text box with no placeholder and no range hint
  (A2-U3), so `inf` and `-0.5` look exactly as valid as `0.0002`
  until save — and `inf` passes save.
- **Fix:** Replace the free-text learning rate with a validated
  numeric input (a `QDoubleSpinBox` with range 1e-5–1e-2 and enough
  decimals, or a validated line edit) that rejects inf, nan,
  negative, and zero values with the existing friendly error style,
  and shows a range hint ("0.0001 – 0.01, typical 0.0002"). The
  accepted range must match the model rules from T6. Also guard the
  write layer: `_write_json` must refuse non-finite floats
  (`json.dumps(..., allow_nan=False)`) so an `Infinity` literal can
  never be written into any manifest again. Existing manifests that
  already contain `Infinity` still load (Python is lenient) and
  re-save clean once the value is corrected.
- **Done:** Typing `inf`, `nan`, `-0.5`, or `0` as the learning rate
  is refused with a readable error; `0.0002` saves. A direct write
  of a non-finite value is refused at the JSON layer instead of
  producing an `Infinity` literal. The range hint is visible in the
  UI. Tests: GUI refusal cases, write-layer guard, re-save of a
  legacy `Infinity` manifest.

### T8 — Gate Start training and sample-dataset on save success

- **Origin:** audit #4 T2
- **Covers:** A4-W2, A4-D2
- **Effort:** S
- **Problem:** `start_training` calls `self.save_project()`
  (`gui.py:823`) and never checks whether it worked. Probed: with
  learning rate `abc`, the warning dialog appeared **and the
  training worker started anyway** — training on the stale
  on-disk settings while the user just saw an error about the
  settings they meant to use. The same unchecked save sits in
  `use_sample_dataset` (`gui.py:795`): with a bad LR the warning
  appeared and the log still claimed "Save is done" — and with no
  project selected at all, the same "Save is done" line is logged
  although nothing was saved.
- **Fix:** A4-D2 — have `save_project` return whether it saved,
  and refuse to start training — or to claim "Save is done" —
  when it did not. A failed save must stop the action that
  depends on it. With no project selected, sample-dataset does
  nothing (or warns) instead of logging a save that never
  happened.
- **Done:** Bad learning rate → warning dialog, no worker starts,
  no training on stale settings. Sample dataset with a bad LR →
  no "Save is done" in the log. Sample dataset with no project
  selected → nothing logged as saved. Tests: bad-LR start
  refused, sample-dataset save claim gated, no-selection case.
- **Status:** DONE in v0.10.0 (2026-11-13) — Start training checks the open Project window's unsaved edits first (Save/Discard/Cancel); a bad learning rate sitting unsaved stops the start instead of training on stale settings. Sample-dataset with no project warns and claims nothing.

### T9 — Delete confirms default to No

- **Origin:** audit #4 T4
- **Covers:** A4-W4, A4-D4
- **Effort:** S
- **Problem:** Probed with the real `QMessageBox.question` call
  and a timer driving the modal loop: focus lands on the **Yes**
  button and pressing Enter returns Yes. The dialog's own text
  says the delete "cannot be undone" — and delete is
  unrecoverable (A1-W5, A2-W8: one dialog, then `rmtree`). A
  single Enter keypress, the key every other dialog in the
  program trains the user to press to accept, destroys a profile
  and all its projects, or a project and its checkpoints.
- **Fix:** A4-D4 — make No the default button so Enter never
  deletes. Pair with the trash from T23 so a confirmed delete is
  still recoverable.
- **Done:** In the delete confirm, Enter does not delete; Yes must
  be clicked (or arrowed to) explicitly. Tests: timer-driven modal
  test asserting Enter returns No, on both the profile and the
  project delete.
- **Status:** DONE in v0.9.0 (2026-11-13) — verified already implemented: delete confirms default to No (gui.py), pinned by test_delete_confirm_defaults_to_no. No code change in this version; marked DONE after coordinator verification.

### T10 — Probe loads the base model twice at once; load one at a time

- **Origin:** repo-audit verdict (R2)
- **Covers:** R2
- **Effort:** M
- **Problem:** probe.py loads the base model twice — once for the
  before pass, once for the after pass (probe.py lines 190 and 192,
  confirmed in code by the verdict) — and holds both in memory at
  once. For LFM3 that is about 7 GB on an 8 GB machine, before the
  adapter, the OS, and Stella itself. The first real probe run on
  his PC is likely to OOM — the refusal probe, a v0.2 headline
  feature, cannot run on the machine it was built for. P0 because
  the feature fails on its target machine on first use: the probe
  is the abliteration guard's evidence, and a guard that cannot run
  is a silent hole.
- **Fix:** Load the base once, run the before pass, unload it (free
  the weights), then load the after pass — or load once and swap
  the adapter in place between passes, whichever the engine
  supports. The two passes must never hold two full base models at
  once. The probe's peak RAM should stay inside the 8 GB guard
  (see T28).
- **Done:** A probe run's peak RAM stays under the guard's budget
  with only one base model resident at a time; before/after counts
  and the gate verdict are unchanged; a test with a
  memory-accounting fake (or a small model with the load counted)
  proves the second load happens only after the first is freed.
- **Status:** DONE in v0.10.0 (2026-11-13) — the refusal probe loads one base at a time: before pass, free (del + gc.collect), then the tuned model. Two 1.7B bases are never held at once.

### T11 — Make New Profile a real QDialog

- **Origin:** audit #1 T9 (dialog part, split out) + audit #4 T1
- **Covers:** A1-U2, A1-U3, A1-D10 (dialog part); A4-W1, A4-D1
- **Effort:** M
- **Problem:** `NewProfileDialog` is a plain `QWidget` with a
  parent and no `Qt.Window` flag (`gui.py:62`). Probed on the
  real path (`win.new_profile()`): `isWindow()` is False and its
  geometry is (0, 0, 420, 320) **in parent coordinates** — it
  renders as a frameless, background-less form smeared over the
  top-left of the main window, its labels overlapping the header
  and both lists (screenshot eyeballed). The `WindowModal` flag
  (`gui.py:598`) does nothing on a non-window: probed, the
  profile selection changed behind the open "dialog". Enter does
  nothing (A1-U2: probed, `create_btn.isDefault()` is False and
  no default button is set), Escape does nothing, it is not
  centered, and two can be opened at once, stacked on top of each
  other. The primary creation flow in the program is visually
  broken and behaves like nothing else in the window. (Audit #4
  corrects audit #1's U3, which called it "a separate 420x320
  window" — wrong; audit #1's report has been corrected in
  place. The dialog was one item inside the old small-UI-fixes
  task; audit #4 raises it to P0, so it is split out here as its
  own task.)
- **Fix:** A4-D1 — make it a real `QDialog`: modal, centered on
  the parent, Create as the default button (Enter works), Escape
  closes, one instance at a time. The test concern in the
  docstring is real — drive it with `QTest` + a timer, the way
  the audit drove the modal dialogs — but a test convenience must
  not ship as a broken dialog.
- **Status:** DONE in v0.3.1 (2026-11-13) — real `QDialog` +
  `exec()`, centered on the parent, Create is the default button,
  Enter in the model field creates (the combo line edit's
  `returnPressed` clicks Create), Escape closes, one instance at
  a time (the modal loop blocks a second open). The creation form
  was also simplified to one model pick at Joshua's order (no
  role / display name / base ref up front). Tests pin the dialog
  type, the window flag, Enter-to-create, and the create flow;
  the modal `exec()` path itself is verified by the offscreen
  visual probe, not an automated modal test.
- **Done:** The dialog opens centered on the main window with
  dialog framing; pressing Enter creates the profile; Escape
  closes it; opening it twice yields one dialog; the profile
  selection cannot change behind it. Tests: dialog type, modality
  (selection blocked behind it), Enter submits, Escape closes,
  singleton.

### T12 — Soft tag validation at create and save (warn, don't block)

- **Origin:** audit #1 T2
- **Covers:** A1-W2, A1-D2; A1-W12 (duplicate-tag note)
- **Effort:** S
- **Problem:** Any string is accepted as an Ollama tag. Probed:
  `create_profile("bogus", ollama_tag="not-a-real-model:99")`
  succeeds and stores the tag. The GUI picker offers real tags, but
  the combo is editable and nothing checks the typed value — not at
  create, not at save. A typo (`lfm3:1.7bb`, `qwen3-v1` for
  `qwen3-vl`) only fails later, at train or export time, with an
  error that will not point back at the profile. Separately, nothing
  notes when two profiles point at the same tag (A1-W12).
- **Fix:** At create and at save, check the tag against the installed
  model list (a direct `list_models()` call is fine here — it is a
  user-initiated action, not a click; T43's cache replaces it later).
  If the tag is not installed, warn ("not installed locally — is
  this right?") and let him proceed — a deliberate entry (a tag he
  is about to pull) must never be blocked. Also warn when another
  profile already uses the same tag ("profile X already uses this
  tag"), without blocking.
- **Done:** Create a profile with `not-a-real-model:99`: a warning
  appears and the user can still proceed. Create with a typo'd tag
  while the correct tag is installed: warning appears. Create a
  second profile with an already-used tag: the duplicate note
  appears. Tests cover: warning on uninstalled tag, no warning on
  installed tag, duplicate-tag note, proceed-anyway path.
- **Status:** DONE in v0.10.0 (2026-11-13) — soft tag validation at create and at save: a tag not installed locally, or already used by another profile, warns and asks (Proceed/Cancel, default No) — a deliberate entry is never blocked. An empty tag or an unanswered Ollama never warns.

### T13 — Keep the live training log

- **Origin:** audit #4 T3
- **Covers:** A4-W3, A4-D3
- **Effort:** S
- **Problem:** `_on_train_finished` (`gui.py:850`) appends
  "Trained N steps." to the log, then calls
  `refresh_train_panel` (`gui.py:759`), which overwrites the log
  widget from `train_log.jsonl` on disk. Probed: after a fake run
  finished, the log was **empty** — the whole run record, finish
  message included, erased. With a real run the file exists, so
  instead of a blank log the user gets the raw JSONL records
  (`{"epoch": 1, "loss": ..., "lr": ..., "step": ..., "type":
  "step"}`) in place of the friendly "step 3/4 loss 2.1000"
  lines they watched during the run (the widget shows the file's
  last 30 lines verbatim). Either way the readable run record is
  gone the moment the run ends.
- **Fix:** A4-D3 — do not let the finish refresh overwrite the log
  the user watched: keep the in-memory lines, and when reloading
  from `train_log.jsonl`, render the JSON records as the same
  friendly "step N/total loss x.xxxx" lines instead of raw JSON.
- **Done:** After a run finishes, the log still shows the run's
  lines plus "Trained N steps."; reopening a trained project
  shows friendly lines, never raw JSON records; a run with no log
  file still shows its in-memory lines. Tests: log survives the
  finish refresh, JSONL renders as friendly lines.
- **Status:** DONE in v0.10.0 (2026-11-13) — the live training log keeps its in-memory lines when the panel refreshes; train_log.jsonl re-renders as friendly "step N/total loss x.xxxx" lines on project switch, never raw JSON.

### T14 — Fix the menu icon: unquote `Icon=`, render the PNGs at install time, never point at a missing file

- **Origin:** repo-audit verdict (R4) + audit #6 T1 + audit #6 T2 (merged — one install.sh pass)
- **Covers:** R4; A6-W1, A6-W2, A6-D1, A6-D2
- **Effort:** M
- **Problem:** Two silent icon failures, both proven live.
  (R4/A6-W2) `install.sh` line 54 points the menu icon at
  `assets/stella.png`, which was never generated in the tree —
  `assets/` holds only `stella.svg`, and `render_icon.py` is
  called by nothing (0 mentions in any script, program, or
  README). The published zip DOES carry the PNGs (they ride in
  the zip only — the push path can't carry binaries), so the zip
  install works, but a clone install points the menu entry at a
  file that does not exist. Probed (audit #6 P2): a tree copy
  with `assets/*.png` deleted installed with exit 0 and printed
  "Stella is installed" while the desktop file points at a
  nonexistent file — and the assets dir still held only
  `stella.svg` afterwards. This is the MIMIK v0.2 trap in
  Stella's form: MIMIK's installer died in its icon loop under
  `set -e` before writing the launcher; Stella's installer has no
  icon step at all, so it *succeeds* and silently ships a broken
  menu icon. `render_icon.py` is orphaned — it exists, it works
  (QtSvg is available in the installed venv, probed), and nothing
  invokes it. (A6-W1) Worse, the icon is broken on EVERY install,
  zip included: `install.sh` writes `Icon="$DIR/assets/stella.png"`
  — quoted, the same treatment as `Exec`. But quoting is only
  defined for `Exec` in the desktop-entry spec; `Icon` is a plain
  string, and GLib takes the quotes literally. Probed with ctypes
  against libgio itself (P13) on the generated file from the
  fresh-unzip install: icon string
  `'"/home/.../assets/stella.png"'` — exists as-is: False; stripped
  of quotes: True. The spaced-path install gives the same result;
  the unquoted control resolves on plain and spaced paths alike.
  This is the v0.1 quoting fix backfiring: it was verified by
  *reading* the generated file ("quoted so install paths with
  spaces still launch"), never by asking GLib what the icon
  resolves to. The launch half is true (`Exec` quoting is
  spec-defined and `gio launch` works); the icon half is false.
  The README's "puts Stella in the app menu with its star icon"
  does not hold on any install.
- **Fix:** One install.sh pass (A6-D1 + A6-D2). Unquote `Icon=`
  (one line); `Exec` quoting stays — it is spec-defined and `gio
  launch` works. After the venv exists, if `assets/stella.png` is
  absent, run `render_icon.py` — QtSvg is available in the
  installed venv (probed). Fallback, also probed: point `Icon=` at
  the SVG itself unquoted — GLib resolves it. Either way, never
  write a desktop file whose icon doesn't exist: check the icon
  file before writing, and fail loudly (or warn clearly) if it
  cannot be produced. The installer tests (T69) pin the fix with
  the GLib icon-resolution check.
- **Done:** A clone install (no PNGs in the tree) ends with a
  working menu icon; a zip install still works; the generated
  `Icon=` is unquoted and resolves via GLib on plain and spaced
  paths; install.sh fails loudly if the icon cannot be produced.
  Tests: clone-shape install (PNGs deleted) produces the icon;
  GLib resolution check (T69).
- **Status:** DONE in v0.3.1 (2026-11-13) — `Icon=` unquoted;
  install.sh renders the PNGs from the SVG when missing (QtSvg
  via PySide6-Addons, now installed with the venv); a failed
  render warns clearly instead of failing the install (the Fix
  allows either; the app still works with a fallback icon). The
  icon art also changed to the ✨ sparkles at Joshua's order.
  T69 (dedicated installer tests) remains open — the fix is
  verified by the offscreen icon render + the GLib resolution
  probe from audit #6, not by an automated installer test.

### T15 — Main screen becomes pick a model, pick a job, press go

- **Origin:** audit #9 R1
- **Covers:** A9-U2, A9-U7, A9-G3 (part)
- **Effort:** L
- **Library:** 005 Bento grids, 009 Shape morphing (see R20)
- **Supersedes:** T113 (real New Project form: the job picker is project creation now; the name becomes part of the pick).
- **Note on T44:** the train-panel half is already fixed by the v0.4 restructure (verified live: Start training at y=275, above the fold); R1 finishes the job for Sleep.
- **Status:** DONE in v0.11.0 (2026-11-14) — bento main screen: the hero tile holds pick a model, pick a job, press Go; small tiles carry the glanceable numbers (RAM, speed, progress) once a job runs; the tree stays as the library. Verified by coordinator from a fresh unzip: Go button at y=72, above the fold at 1100x680 and 1366x768, disabled with no job picked.
- **Problem:** The main window is one long scrolling column of sections with no job picker, and at rest it is a wall of empty grey boxes. The brief's core flow does not exist as a screen.
- **Fix:** Replace the session column with a bento main screen. One hero tile holds the flow: pick a model, pick a job (Train, Sleep, Make smaller, Teach a small model), press go. Small tiles carry the glanceable numbers (RAM, speed, progress) once a job runs. The tree stays as the library of what exists. The core flow needs no scrolling at 1100x680.
- **Done:** At 1100x680 the first screen shows the model pick, the job pick, and Go with nothing below the fold; a new user can reach "press go" without scrolling or opening a second window.

### T16 — Settings leave every screen

- **Origin:** audit #9 R2
- **Covers:** A9-U1, A9-D3
- **Effort:** M
- **Library:** 004 Just-in-time GUI, 012 Progressive disclosure
- **Supersedes:** T154 (Advanced settings section: do not build; the brief puts settings under the hood).
- **Mooted by this task:** T7 (learning rate as a numeric input: no learning rate field), T46 (lock settings during a run: no settings to lock), T6's user-facing half (validation moves to the backend auto-config), T2's settings half (dirty tracking keeps only name, dataset, notes).
- **Depends on:** v0.9's auto-config backend. The settings cannot leave the screen until the backend decides them.
- **Status:** DONE in v0.11.0 (2026-11-14) — settings form deleted from the Project window, settings line deleted from the session summary, Training defaults block deleted from Settings, chat template step 4 and the chat greeting rewritten; the chat set_project_settings tool removed outright (the chat window IS UI — a user asking the chat to change a setting by name was touching settings, which the brief forbids). Stored settings fields stay for compatibility; nothing in the UI reads or writes them. CLI pc-info keeps printing the recipe (a deliberate diagnostic, not a screen).
- **Problem:** Rank, learning rate, epochs, batch size, and sequence length are on screen in four places (session summary, Project window form, Settings defaults, chat template step 4). The brief says the backend sets them all and the user never sees them.
- **Fix:** Delete the settings form from the Project window (name, dataset, and notes stay), delete the settings line from the session summary, delete the Training defaults block from Settings, and rewrite chat template step 4 and the chat greeting so they stop naming settings. The stored settings fields stay in the model for compatibility; nothing in the UI reads or writes them.
- **Done:** No rank, learning rate, epochs, batch size, or sequence length string is visible anywhere in the UI; a grep of the visible strings in gui.py, howto.py, and chat_agent.py finds none.

### T17 — First-run setup checklist

- **Origin:** audit #9 R3
- **Covers:** A9-W4, A9-G3
- **Effort:** M
- **Library:** 020 Setup checklist, 014 Teach by playing
- **Status:** DONE in v0.11.0 (2026-11-14) — an empty store shows the three-step first-run checklist (pick a model, get its weights, run a tiny first training on the 20-example sample dataset, a real run) instead of the disabled wall; each step is a button that does the step, a finished step ticks, and dismissing it never brings it back.
- **Problem:** First launch shows an empty tree, guidance that tells the user to pick a project that does not exist, and a wall of disabled controls. Nothing on screen says what to do first.
- **Fix:** On first launch (empty store), the main screen shows a three-step checklist instead of the disabled wall: 1. Pick a model. 2. Get its weights. 3. Run a tiny first training (the 20-example sample dataset, a real run, not a wizard). Each step is a button that does the step; a finished step ticks. The checklist is dismissible and never reappears as a modal.
- **Done:** An empty store shows the checklist; completing a step ticks it; dismissing it never brings it back; the misleading "pick a project in the list" text is gone.

### T18 — Model picker with fit guidance and no default selection

- **Origin:** audit #9 R4
- **Covers:** A9-W1, A9-G5
- **Effort:** M
- **Library:** 012 Progressive disclosure
- **Extends:** T84 (RAM/time estimate in the detail panel: the estimate moves to the picker, where the choice is made).
- **Status:** DONE in v0.11.0 (2026-11-14) — the model picker opens with nothing selected (Enter with no pick does nothing), the profile-name note appears only after a pick; each model row shows one plain line for what it does and a fit verdict (size plus RAM, from the backend's PC measurement).
- **Problem:** The New Profile dialog pre-selects the first model (Enter creates a profile for a model the user never picked), and it shows bare tags with no "what it does" and no fits-this-PC verdict. The user picks blind.
- **Fix:** The dialog opens with nothing selected (`setCurrentIndex(-1)`, as the chat combo already does); the profile-name note appears only after a pick, and Enter with no pick does nothing. Each model row shows one plain line for what it does and a fit verdict (size plus RAM, from the backend's PC measurement). Details beyond that appear on tap, not up front.
- **Done:** The dialog opens with no selection and no name note; every listed model shows what it does and whether it fits this PC.

### T19 — Real menu bar, actions disabled when they cannot work

- **Origin:** audit #9 R5
- **Covers:** A9-W5, A9-U9
- **Effort:** M
- **Library:** none (U38: real Windows-style menus)
- **Supersedes:** T169 (menu bar).
- **Status:** DONE in v0.11.0 (2026-11-14) — a real QMenuBar (File, View, Help); actions that need a selection are disabled until one exists; the Menu button is gone.
- **Problem:** The menu is a button with nine actions in one flat list, and four of them are enabled with nothing selected, answering with modal warnings.
- **Fix:** A real `QMenuBar`: File (New profile, New project, Export project, Import package, Settings), View (Profiles, Projects), Help (How to Use Stella, Chat). Actions that need a selection are disabled until one exists. The Menu button goes away.
- **Done:** With an empty store, the actions that need a selection are greyed out; no menu action answers with a "pick one first" modal.

### T20 — Live training graphs and stats

- **Origin:** audit #9 R6
- **Covers:** A9-G1, A9-G4
- **Effort:** L
- **Library:** 021 Glanceable surfaces, 003 Calm technology
- **Extends:** T151 (loss chart plus run history: elevated from P3 to P0; the brief makes it core).
- **Status:** DONE in v0.11.0 (2026-11-14) — a loss curve (QPainter, redrawn on new points only) plus speed (steps per minute), RAM used, time left, and epoch in the glanceable card; the finished run's curve and summary remain visible. (The run-history half is T151, done in v0.20.0.)
- **Problem:** The only loss readout is one text line. No graph, no speed, no RAM, no time left, no run history. The brief asks for live graphs and stats with a middle-school science software feel, and today there is nothing to watch.
- **Fix:** A loss curve (QPainter, redrawn on new points only, no per-frame cost), plus speed (steps per minute), RAM used, time left, and epoch, in the glanceable card. The UI keeps the loss series from the worker's progress signal (step, total, loss already emitted). Run history is kept per project so the last run's curve is still there after it finishes.
- **Done:** During a run the graph draws, RAM, speed, and time left update, and the finished run's curve and summary remain visible.

## P1 — functional defects and daily friction

### T21 — Fill the detail panel defensively

- **Origin:** audit #4 T6
- **Covers:** A4-W6, A4-D6
- **Effort:** S
- **Problem:** `_show_project_detail` converts settings with bare
  `int(...)` (`gui.py:529-533`) and no guard. Probed: a project
  whose `project.json` says `rank: "high"` — selecting it raised
  `ValueError` out of the signal handler (traceback printed to
  stderr by Qt) and left the panel **mixed**: display name and
  dataset showed the new project, while learning rate, epochs,
  batch, seq len, metamorph, and notes still showed the previous
  project's values. The user now sees one project's settings
  labeled as another's — and clicking Save writes the mixed form
  back to disk, corrupting the project with the other project's
  values (`save_project` reads the form unconditionally,
  `gui.py:560`). The home is meant to be hand-editable, so a
  mistyped value in the JSON turns a selection click into a
  corruption vector. (Model validation — T6 — prevents *new* bad
  values from being saved; this task handles the bad values
  already on disk, hand-edited before validation lands.)
- **Fix:** A4-D6 — a setting of the wrong type falls back to its
  default (and the panel says so) instead of aborting the fill
  mid-way. Never let a read error become a mixed panel, and never
  let a mixed panel be saved. The fallback defaults must match
  T6's ranges.
- **Done:** Select a project with `rank: "high"`: the panel fills
  completely with the default rank and a visible note that the
  stored value was invalid; no traceback; no other project's
  values anywhere in the panel; Save does not write the other
  project's values. Tests: bad-type fill for each setting, mixed
  panel impossible, save-after-bad-fill writes only this
  project's values.
- **Status:** DONE in v0.9.0 (2026-11-13) — ProjectWindow._load is defensive: a bad stored value falls back to the default, the panel shows a "stored value was invalid" note, and the save guard prevents writing the bad value back.

### T22 — Safe torch.load for optimizer.pt (weights_only=True)

- **Origin:** repo-audit verdict (R10)
- **Covers:** R10
- **Effort:** S
- **Problem:** train.py loads optimizer.pt with
  torch.load(weights_only=False) — a pickle deserialization of a
  file that travels cross-machine inside an export package. A
  malicious or corrupted package can execute arbitrary code at
  import/resume time. This is the trust boundary T1 guards for
  manifests; the checkpoint payload needs the same treatment.
- **Fix:** Load optimizer.pt with weights_only=True (and audit
  every other torch.load in the tree for the same flag). If the
  optimizer state cannot load under weights_only, migrate the
  checkpoint format to a safe serialization (safetensors or a
  plain tensor dict) and document the migration for existing
  checkpoints.
- **Done:** No torch.load in the tree runs with weights_only=False;
  a crafted optimizer.pt carrying a pickle payload is refused
  (test with a malicious pickle); existing valid checkpoints still
  resume.
- **Status:** DONE in v0.10.0 (2026-11-13) — optimizer.pt loads with weights_only=True; a malicious pickle is refused, never executed. Audit found it is the only torch.load in the tree, so no migration was needed.

### T23 — Trash instead of delete (profiles + projects)

- **Origin:** audit #1 T5 + audit #2 T8 (merged — one trash system)
- **Covers:** A1-W5, A1-D6; A2-W8, A2-D10
- **Effort:** M
- **Status:** DONE in v0.13.0 (2026-11-14) — deletes move to trash as `<profile>-<project>-<date>`; restore or purge from the Trash window (File menu).
- **Problem:** Both deletes are `shutil.rmtree` behind a single
  Yes/No dialog. `delete_profile` destroys the profile, its
  projects, notes, and (from v0.2) checkpoints; `delete_project`
  destroys a project that may hold hours of training. No trash, no
  backup, no "export first" offer, no undo on either side. One
  misclick past Yes deletes work that may include hours of training.
- **Fix:** One trash system for both: move deleted profiles to
  `~/.stella/trash/<slug>-<date>/` and deleted projects to
  `~/.stella/trash/<profile>-<project>-<date>/`, with a purge action
  (manual, and/or automatic after a stated age). Offer "export all
  projects first" in the profile delete dialog and "export this
  project first" in the project delete dialog. Keep the confirm
  dialogs.
- **Done:** Delete a profile with projects and delete a project: both
  leave their lists, and their full folders (projects, notes,
  checkpoints) appear under `~/.stella/trash/` with dated names;
  restoring either by moving it back works. Both delete dialogs offer
  to export first. Purge removes a trashed item permanently, with its
  own confirm. Tests: delete-to-trash for profiles and projects,
  trash contents intact, purge.

### T24 — GGUF export must not silently delete previous output

- **Origin:** repo-audit verdict (R12)
- **Covers:** R12
- **Effort:** S
- **Problem:** Exporting a GGUF to a directory that already holds
  a previous export deletes the previous output without a word —
  no prompt, no backup, no warning. The previous .gguf cost a
  merge + convert + quantize to produce, and it is gone because
  the user re-ran a command. (Audit #5 W6 (T26) covers the opposite
  direction — a failed export leaving ~3.4 GB of merged weights
  behind; this task is the successful export destroying the
  previous result.)
- **Fix:** Refuse to overwrite an existing GGUF output (or prompt
  to overwrite / write to a new name / move the old output to
  trash per T23 — pick one, document it). The CLI gets a --force
  flag for the deliberate overwrite. Never delete a previous
  export silently.
- **Done:** Exporting twice to the same directory prompts (or
  refuses, or renames) instead of deleting; --force overwrites
  deliberately; the previous output is recoverable after an
  overwrite-with-backup. Tests: second export without --force
  does not destroy the first; --force works.
- **Status:** DONE in v0.10.0 (2026-11-13) — the REFUSE pick: GGUF export refuses to overwrite an existing output with a plain message naming --force, checked before the merge runs; --force on export-gguf overwrites deliberately. Never deletes a previous export silently.

### T25 — Refuse or confirm re-training a trained project, and say when resume extends one

- **Origin:** audit #5 T4
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
  `--force` makes the destructive intent explicit. (The checkpoint
  side — resume from a selected checkpoint — is T150.)
- **Done:** Re-training a trained project without `--force`
  refuses with a readable message and leaves the adapter
  untouched; with `--force` it re-trains; `--resume` on a trained
  project announces the extension and the new total first. Tests:
  refuse without `--force`, `--force` re-trains, resume-on-trained
  announces.
- **Status:** DONE in v0.10.0 (2026-11-13) — re-training a trained project refuses ("already trained. Use --force to re-train it") and leaves the adapter untouched; --force re-trains deliberately. --resume on a trained project announces the extension and the new total first (the extending event, printed by CLI and GUI). The GUI asks before re-training.

### T26 — Check llama.cpp before the merge; clean up the merged dir and the F16 intermediate on failure

- **Origin:** audit #5 T6
- **Covers:** A5-W6, A5-D6; A8-W13, A8-D10
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
  export silently deleting the *previous* output, T24; this task
  is the failed export leaving its own mess behind.) Audit #8 adds
  the F16 half (A8-W13): `convert_to_gguf` deletes the F16 file only
  on the success path — with a failing quantizer the StellaError is
  raised correctly and the F16 file is left behind, ~3.4 GB per failed
  export on a real 1.7B model, with no message naming the file and no
  cleanup on the next run.
- **Fix:** D6 — call the llama.cpp completeness check before the
  merge, not after it, so a missing install fails in a second
  instead of after a multi-minute merge. And if the export fails
  after the merge, remove the merged directory (or say where it
  is and that it is safe to delete) instead of leaving ~3.4 GB
  behind silently. D10 (A8): wrap convert + quantize in try/finally
  so the F16 file is removed when the quantize step fails — and say
  so in the error.
- **Done:** `export-gguf` with no llama.cpp fails in under a few
  seconds with the install hint and no merged dir left behind; a
  failure after the merge leaves no orphaned merged weights (or
  names the dir and says it is safe to delete). Tests:
  missing-llama.cpp fast-fail, no leftover merged dir. A failed
  quantize leaves no F16 intermediate behind (or names it and says
  it is safe to delete).
- **Status:** DONE in v0.10.0 (2026-11-13) — export_gguf checks llama.cpp before the merge, not after; a failed export removes the half-finished merged dir and the F16 intermediate and says so in the error.

### T27 — Validate `--quant` up front

- **Origin:** audit #5 T7
- **Covers:** A5-W7, A5-D7
- **Effort:** S
- **Problem:** `--quant BOGUS` exited 0 and printed `GGUF (BOGUS):
  .../proof-bogus.gguf (800 bytes)` with the full success output.
  Nothing in `cli.py` or `gguf.py` checks the value — no `choices`
  list, no validation against llama.cpp's quant types. With a real
  llama.cpp the failure would come from `llama-quantize` at the
  END of the pipeline, after the merge and the convert — the same
  fail-slow shape as W6, for a value that could be rejected in a
  millisecond. Audit #8's D11 re-confirms this from the engine side:
  validate `quant` against llama.cpp's known list before the merge.
  (The discovery half of D11 — the quantizer must be executable — is
  a separate task, T102.)
- **Fix:** D7 — give `--quant` a `choices` list of the quant types
  llama.cpp accepts (or validate against the installed
  `llama-quantize`'s list), so `--quant BOGUS` fails in a
  millisecond with the valid values named instead of after the
  whole pipeline.
- **Done:** `--quant BOGUS` exits 1 with a plain error naming the
  valid values; every valid quant still exports. Tests: bogus
  quant refused, each valid quant accepted.
- **Status:** DONE in v0.10.0 (2026-11-13) — the GGUF path validates --quant up front with the existing requant.validate_quant (no second validator): a bogus quant fails in a millisecond, before the merge, with the valid values named.

### T28 — The RAM guard must estimate before loading anything

- **Origin:** repo-audit verdict (R8)
- **Covers:** R8
- **Effort:** M
- **Problem:** The RAM guard claims to estimate "before loading
  anything" but loads the base model first — the verdict confirmed
  the drift in code. On 8 GB, loading a 1.7B base to ask whether it
  fits can OOM the machine the guard exists to protect. The
  guard's estimate must come from the model's declared size, not
  from a loaded model.
- **Fix:** Estimate RAM from the base model's config and weights
  metadata (parameter count, dtype, plus the LoRA/optimizer
  overhead the guard already models) without loading the weights.
  The guard refuses (or warns) before any load when the estimate
  exceeds the budget. The dry-run estimate button (T85) and the
  detail-panel estimate (T84) build on this honest estimator.
- **Done:** A run that will not fit is refused before any model
  load (proven with a test that asserts no load happened — e.g. a
  fake loader that records calls); a run that fits proceeds; the
  guard's claim in the docs matches its behavior.
- **Status:** DONE in v0.10.0 (2026-11-13) — the RAM guard estimates from the model's config + weight sizes (load_model_metadata, estimate_training_from_metadata) before loading anything; a run that will not fit is refused before the base is anywhere near memory. A second guard with the real param counts still runs after the load.

### T29 — One job at a time, enforced in the GUI and the engine

- **Origin:** audit #4 T9
- **Covers:** A4-W9, A4-D9; A8-W7, A8-D5
- **Effort:** M
- **Note:** Extended by T74 (Audit #9 R7).
- **Status:** DONE in v0.13.0 (2026-11-14) — one job at a time enforced in the GUI and the engine via a lock file (stella/job_lock.py), so two CLI runs cannot load models at once.
- **Problem:** Probed with slow fake jobs: starting the refusal
  probe while a GGUF export was running started a second
  `JobWorker` alongside the first — and starting a GGUF export
  while training was running started it too. Each start overwrites
  `self._job_worker`, so the first job is orphaned from the
  window's handle (its finish signal still fires, but nothing
  tracks it). On 8 GB, a probe loading a model while a training
  run holds its weights is a real OOM shape, and the window does
  nothing to prevent it. Audit #8 found the
  train-vs-job hole (A8-W7): `start_training` refuses to run while
  sleep runs, but `export_gguf_gui` and `run_probe_gui` have no
  guards at all — no check for a running train/sleep/job, and each
  overwrites `self._job_worker`, orphaning a running job. The RAM
  math says the hole is fatal, not untidy: the probe loads two bases
  (~7 GB for LFM3) while training holds ~5.9 GB — ~13 GB on an 8 GB
  machine — and export-merge (~3.5 GB) during training is over the
  ceiling too.
- **Fix:** A4-D9 — a single running-job slot: GGUF export and the
  probe disable each other and disable during training, with the
  status bar saying what is running. D5 (A8): enforce the single job
  slot in the engine too — a lock (in-process flag or lock file) in
  `train_project` / `export_gguf` / `probe_project` so two
  model-loading jobs cannot run at once even across CLI invocations.
  The GUI guard is the UX; the engine guard is the safety.
- **Done:** Starting a second job while one runs is refused (or
  the button is disabled) with a message naming the running job;
  starting a job during training is refused the same way; no job
  is ever orphaned from the window's handle. Tests: probe-during-
  export refused, export-during-training refused, status names
  the running job. Two model-loading jobs cannot run at once even
  across CLI invocations (the second refuses with a message naming
  the running job).

### T30 — Make the refusal probe trustworthy: detection v2 + chat-template mode

- **Origin:** audit #8 T3
- **Covers:** A8-W4, A8-W5, A8-W6, A8-D2, A8-D3
- **Effort:** M
- **Status:** DONE in v0.13.0 (2026-11-14) — the refusal probe is trustworthy now: first-sentence detection, silent models fail the gate, chat-template prompts.
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

### T31 — Merge RAM guard: the merge/convert steps have no estimate at all

- **Origin:** audit #8 T7
- **Covers:** A8-G2
- **Effort:** S
- **Problem:** The training guard (T28) covers the loop;
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
- **Status:** DONE in v0.10.0 (2026-11-13) — merge RAM guard (estimate_merge_bytes, check_merge_fit in gguf.py): base weights + merged copy + headroom, refused before loading when it does not fit. The converter warning (merge_warnings, on_warning) tells the user to close other apps when merge + converter together pass the ceiling.

### T32 — Seed everything: torch seed at run start + RNG state in checkpoints

- **Origin:** audit #8 T1
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
- **Status:** DONE in v0.10.0 (2026-11-13) — torch.manual_seed at fresh-run start (before the LoRA init), and the torch RNG state saved in every checkpoint and restored on resume. Same seed, same adapter; pause/resume is bit-identical to an uninterrupted run. Old checkpoints without RNG state still resume.

### T33 — Minimum-val guarantee, or a loud warning

- **Origin:** audit #8 T2
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
- **Status:** DONE in v0.10.0 (2026-11-13) — every dataset split keeps at least one validation row: n_val = max(1, round(n x val_fraction)) for n >= 2 (n=2 is 1 train + 1 val, as load_dataset promises). Never silently runs with no val set.

### T34 — Target-module override for unrecognized architectures

- **Origin:** audit #8 T6
- **Covers:** A8-G1
- **Effort:** S
- **Status:** DONE in v0.13.0 (2026-11-14) — the target-module override is honored from a CLI flag and a stored settings field (flag wins); no UI per T16.
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

### T35 — The CLI reports the RAM estimate as "RAM used" — say "estimated"

- **Origin:** audit #8 T5
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
- **Status:** DONE in v0.10.0 (2026-11-13) — the CLI closing line says "about X GB RAM (estimated)", not "GB RAM used": the figure is the pre-run estimate, not a measurement.

### T36 — Close waits for every worker, without freezing

- **Origin:** audit #4 T10
- **Covers:** A4-W10, A4-D10
- **Effort:** M
- **Status:** DONE in v0.13.0 (2026-11-14) — close waits for a running job instead of freezing.
- **Problem:** `closeEvent` (`gui.py:916-919`) waits for the
  *train* worker only. Probed in a separate process: closing the
  window during a GGUF export returned in 0.05s and Qt printed
  `QThread: Destroyed while thread '' is still running` — the
  worker was destroyed mid-flight, which Qt documents as a
  programming error that can crash. Closing during a training run
  whose worker ignores the stop request froze the UI for the full
  15.07-second wait and then printed the same destroyed-thread
  warning anyway. The 15-second freeze has no feedback at all:
  the window just stops responding to a close click.
- **Fix:** A4-D10 — wait for the job worker too; show "Stopping
  training…" and close when the thread ends instead of blocking
  the UI thread for 15 seconds; never destroy a running thread.
  Lands after T29 — with one job slot, there is at most one job
  worker to wait on.
- **Done:** Closing during a job waits (with visible feedback)
  and closes cleanly with no destroyed-thread warning on stderr;
  closing during training shows progress and closes when the
  worker ends instead of freezing the UI. Tests: close-during-job
  in a subprocess (no warning), close-during-training feedback
  shown.

### T37 — GUI Save must not crash on a missing metamorph key; one defensive reader for the block

- **Origin:** audit #7 T3
- **Covers:** A7-W3, A7-D8
- **Effort:** S
- **Problem:** `update_project` assumes the stored block exists:
  `model.py:341` reads `data["metamorph"]["mode"]` with no guard.
  With the key deleted from `project.json`, a GUI save — which
  always passes a metamorph dict (`gui.py:582`) — raises
  `KeyError: 'metamorph'` (probed, audit #7 P4 and P7).
  `save_project` catches only `StellaError`, so the exception
  escapes the Qt slot: the save silently does not happen, and the
  traceback goes to a terminal the menu-launched user never sees
  (Terminal=false). With the block set to `null` instead of
  missing, the same line raises `TypeError: 'NoneType' object is
  not subscriptable`. A display-name-only update on the same file
  works fine — only the metamorph path assumes the block. Root
  cause: `get_project` (`model.py:270-276`) setdefaults `name` and
  `profile` but not `metamorph`.
- **Fix:** D8 — `get_project` setdefaults the block, and one
  helper — e.g. `metamorph_mode(project_dict)` returning a valid
  mode or `"morph"` for null/missing/wrong-type — is used by the
  CLI list, the GUI list + detail fill, export, and verify. Built
  ONCE here, in the model layer; T38, T39, T177, and T1 consume it.
- **Done:** A missing or null metamorph key no longer crashes a
  save — the save works and the mode defaults to `morph`; no
  traceback escapes the Qt slot. Tests: missing-key save, null
  save, string-block save.
- **Status:** DONE in v0.9.0 (2026-11-13) — shared defensive metamorph readers in the model layer (metamorph_mode / metamorph_problem); get_project defaults the block; update_project reads through the reader. No KeyError on a missing block, no AttributeError on a null block.

### T38 — Export must not crash on `metamorph: null` — and must not leave a partial package

- **Origin:** audit #7 T2
- **Covers:** A7-W2, A7-D8, A7-D9
- **Effort:** S
- **Problem:** `export.py:60` uses `proj.get("metamorph", {...})` —
  but `.get`'s default only applies when the key is *absent*. When
  the key is present with value `null`, the manifest gets
  `metamorph: None`, and line 76
  (`manifest['project']['metamorph'].get(...)`) raises
  `AttributeError: 'NoneType' object has no attribute 'get'`
  (probed, audit #7 P3). Worse, the crash happens *after*
  `manifest.json` and `config.json` are written: the export folder
  is left behind containing exactly those two files — no README, no
  `weights/`, no `checkpoints/`. A second export attempt then fails
  with "export folder already exists" (audit #3's non-atomicity
  class, export-side; cf. A3-W1 for import).
- **Fix:** D8 — read the block through the shared defensive reader
  from T37: null/missing/wrong-type yields the default mode instead
  of a crash. D9 — build every file's content before creating the
  folder, so a bad block fails before any partial package exists
  (same atomicity direction as T1's import fix).
- **Done:** A project with `metamorph: null` exports cleanly (mode
  defaults to `morph`), or fails before creating anything — never
  a partial folder. Tests: null export, missing-key export,
  no-partial-package on failure.
- **Status:** DONE in v0.9.0 (2026-11-13) — export goes through the T37 reader and builds all content before creating the folder; no partial package on a bad metamorph block.

### T39 — The GUI project list must not die on a string metamorph

- **Origin:** audit #7 T4 + audit #5 T2 (CLI instance, merged — same reader)
- **Covers:** A7-W4, A7-D8; A5-W2, A5-D2 (CLI instance)
- **Effort:** S
- **Problem:** `gui.py:449` reads the mode with
  `(p.get("metamorph") or {}).get("mode", "morph")`. The `or {}`
  guards `None` and missing — but a *string* is truthy, so a
  hand-edited `"metamorph": "both"` raises `AttributeError: 'str'
  object has no attribute 'get'` inside `refresh_projects` (probed,
  audit #7 P7). One bad project kills the whole list refresh, so
  the window cannot show *any* project in that profile. The detail
  fill at `gui.py:534` uses the identical expression and crashes
  identically (masked in practice because the list refresh fails
  first). The CLI instance of this exact pattern is A5-W2
  (re-confirmed in audit #7 P5): `cli.py:51` raises the same
  `AttributeError` in `cmd_projects`. It is fixed here too — the
  CLI list reads the mode through the same shared reader and
  degrades to a warning line instead of killing the whole list.
- **Fix:** D8 — read the mode through the shared defensive reader
  from T37 in the list and the detail fill. The GUI list should
  degrade to a warning row for a bad project, not die for the whole
  profile (A5-D2's prescription, applied to the GUI half). The CLI list
  (`cmd_projects`) reads the mode through the same reader and
  degrades to a warning line for a bad project.
- **Done:** A string-metamorph project shows as a warning row;
  every other project in the profile lists normally; the detail
  fill does not crash. The CLI `projects` list shows a warning
  line for the string-metamorph project and lists the rest. Tests:
  string block in the list, string block in the detail fill,
  string block in the CLI list.
- **Status:** DONE in v0.9.0 (2026-11-13) — a string-metamorph project shows a warning row in the GUI tree and a warning line in CLI list output. Pinned by test_tree_warns_on_string_metamorph.

### T40 — Settle the package format: versioned format + named kinds

- **Origin:** audit #3 T2
- **Covers:** A3-W5, A3-W6 (format side), A3-G1, A3-G3, A3-D1
- **Effort:** M
- **Status:** DONE in v0.13.0 (2026-11-14) — the package format is versioned (format 1, profile + recipe kinds defined up front, documented in docs/FORMAT.md).
- **Problem:** `stella_version` is stamped on every manifest and
  means nothing: no supported range, no "too new" rejection, no
  migration. Probed: a manifest claiming version `99.0` imports
  fine; a manifest with the field deleted imports fine. What the
  package is today is a *single-project folder* — manifest (one
  profile block + one project block) + a duplicate `config.json` +
  README + placeholder-only `weights/` + checkpoints + notes, with
  no version semantics, no checksums, no timestamps, no
  provenance. The manifest holds exactly one project, so the format
  cannot express "a profile with all its projects" (A3-G3). This
  is a live forward-compat hazard: the first v0.2 package carrying
  real weights will import into v0.1 and lose the weights silently,
  because v0.1 has no way to know the package is newer than it.
  This is the T86/T170 seam: profile export and recipe export both
  build on the kinds defined here.
- **Fix:** Give the format a real version, separate from the app
  version (`format: 1`), with a supported range enforced on import
  and a clear "this package needs a newer Stella" message for
  newer packages. Define the package kinds up front — project
  package (today's), profile package
  (`kind: "stella-profile-export"`, T86), recipe package (T170) —
  as distinct `kind` values sharing one manifest shape, so profile
  and recipe export never become two formats. `weights/` becomes a
  first-class round-tripped member in the same pass (T41).
  Document the format in the repo (a FORMAT doc or a README
  section) so a hand-editing user can read it. The version check
  must land *with or before* the first weights-carrying export.
  (Enforced in `verify_export`, alongside T1's schema validation.)
- **Done:** A package with format 99 is refused with "needs a newer
  Stella"; a legacy v0.1 package (no `format` field) imports under
  a documented rule (treated as format 1, or refused with a
  migration note — decide in implementation and document it). The
  three kinds are defined in one place and share the manifest
  shape. Tests: version rejection, legacy-package handling, kind
  values present.

### T41 — Round-trip `weights/` and probe results

- **Origin:** audit #3 T3; extended by the repo-audit verdict (R1)
- **Covers:** A3-W6, A3-D5; R1
- **Effort:** S
- **Depends on:** T40 (lands with the version check)
- **Status:** DONE in v0.13.0 (2026-11-14) — weights and probe results round-trip through export/import.
- **Problem:** Import copies checkpoints and notes only
  (`export.py:174-187`); `weights/` is not mentioned. Probed: a
  package containing `weights/adapter.safetensors` imported
  successfully — and the imported project has **no** `weights/`
  directory at all. The payload the whole program exists to
  produce has no round-trip. Today that costs nothing (v0.1 ships
  no weights), but the format must be settled *before* v0.2 puts
  weights in the package, or every v0.1 import of a v0.2 package
  will silently eat the fine-tune. The verdict reproduced the drop
  live (R1): a fake adapter and probe results were planted into an
  export, the project marked trained, and imported into a fresh
  home — the imported project had only profile.json, project.json,
  and notes.md, and still claimed status "trained". The export
  carries the adapter and probe_results.json; the import never
  brings them back.
- **Fix:** Copy the weights folder on import (minus the placeholder
  note) and treat it as the payload; export writes real weights
  when they exist. Copy probe_results.json the same way, so the
  refusal evidence travels with the fine-tune. If the manifest
  claims a trained status but the package carries no weights,
  correct the status on import — a project with no weights must
  not claim "trained" (it imports as draft, with a warning). Land
  with T40's version check so no older Stella can silently drop
  it.
- **Done:** Export a project with a weights file, import into a
  fresh home: `weights/` is present with the file byte-identical;
  the placeholder note is not copied as a weight. probe_results.json
  round-trips byte-identical. A package claiming "trained" with no
  weights imports as draft with a warning. A v0.1-era package
  (placeholder only) still imports. Tests: weights round-trip,
  probe-results round-trip, status correction on a weightless
  "trained" package, placeholder handling.

### T42 — Distinguish venv-failure causes; clean up only what you made

- **Origin:** audit #6 T9
- **Covers:** A6-W9, A6-W10, A6-D7
- **Effort:** S
- **Status:** DONE in v0.15.0 (2026-11-14) — the installer names the real failure instead of a blanket message, and cleans up only what it made.
- **Problem:** Any failure of `python3 -m venv` prints the same
  message, whatever the cause. Probed (P6): `.venv` existing as a
  stray file made venv creation fail with `Error: Unable to create
  directory '.../.venv'` — and the installer printed `ERROR:
  python3-venv is missing. Run: sudo apt install python3-venv`.
  Disk-full, permissions, or a broken pre-existing venv dir would
  all get the same wrong advice, sending the user to install a
  package they already have. And `rm -rf "$DIR/.venv"` runs on
  *any* venv-creation failure, before the error message. Probed
  (P6): it deleted the stray file that was in the way. The cleanup
  does not check that `.venv` is a venv, or that this run created
  it. A file (or anything else) a user or another tool put at that
  path is destroyed without asking.
- **Fix:** A6-D7 — check `python3 -c "import venv, ensurepip"` first
  and print the `python3-venv` message only when the module is
  actually missing; otherwise print the real venv error. Only
  `rm -rf` a `.venv` this run created (or one that looks like a
  venv).
- **Done:** A stray file at `.venv` gets the real error (not the
  python3-venv message) and is not deleted; a genuinely missing
  python3-venv still gets the exact named fix. Tests: stray-file
  case, missing-module case.

### T43 — Cache the Ollama model list; fetch off the UI thread

- **Origin:** audit #1 T3 + audit #4 T7 (merged — one fix)
- **Covers:** A1-W4, A1-U4, A1-D5; A4-W7, A4-D7
- **Effort:** M
- **Status:** DONE in v0.14.0 (2026-11-14) — the model list is fetched once at startup into a cache, off the UI thread, so a hung Ollama never freezes a click; refresh re-fetches on demand.
- **Problem:** `_show_profile_detail` calls `list_models()` on every
  selection change, synchronously, with no cache. Probed against a
  counting fake server: window open = 1 fetch, switch to row 1 = 2,
  switch back = 3. Each fetch can block the UI thread up to the
  2-second timeout if Ollama hangs (slow startup, a loaded model, a
  swapping 8 GB box), so clicks can feel dead for up to 2 seconds.
  The New Profile dialog fetches again on open. While Ollama is down
  the tag combo is briefly empty before the stored tag is re-added
  (A1-U4 flicker on every click). Audit #4 re-verified this unchanged in v0.2 (A4-W7): 2 selections = 2 fetches against a counting fake server, and a 1.2-second server delay blocked a click for 1.39 seconds.
- **Fix:** Fetch the installed-model list once at startup into a
  cache; serve every selection change and every combo fill from the
  cache. Refresh on demand only: a Refresh button, and when the New
  Profile dialog opens. Move the fetch to a background thread so a
  hung Ollama never blocks a click; the UI keeps showing the last
  good list (and the stored tag) while a refresh is in flight.
- **Done:** Against a counting fake Ollama server: 1 fetch at
  startup, 0 fetches across any number of profile selection changes,
  1 fetch on explicit Refresh. With Ollama hung (no response within
  the timeout), profile clicks still respond immediately and the
  stored tag stays visible. Tests: fetch-count test, hung-Ollama
  responsiveness test, refresh-button test.

### T44 — Put the Train panel above the fold

- **Origin:** audit #4 T14; extended by the repo-audit verdict (R19)
- **Covers:** A4-U2, A4-D17; R19
- **Effort:** M
- **Note:** Extended by T15 (Audit #9 R1).
- **Problem:** Audit #2's U2, worse in v0.2. Probed geometry at
  1100x680: detail content is 1289px tall in a 567px viewport;
  the Notes editor starts at y=578, `Start training` at y=758,
  the progress bar at y=789, the Training log at y=996. Only the
  "Notes" header peeks out at the bottom of the default window
  (screenshot). The primary action of the v0.2 release — Start
  training — needs a scroll on every visit. The verdict re-verified
  (R19): the Train panel is below the fold. (Coordinate with T160,
  which repositions Notes — both tasks reshape the same detail
  panel, so the layout change should solve Notes and Train
  placement in one pass.)
- **Fix:** A4-D17 — move Train above Notes, or give the detail
  pane a Train tab, or make the sections collapsible — the
  release's headline action should not need a scroll on every
  visit.
- **Done:** A screenshot at 1100x680 shows Start training (and the
  progress bar) without scrolling. Tests: geometry assertion that
  Start training is inside the viewport at default size.
- **Status:** DONE in v0.9.0 (2026-11-13) — verified already true: at 1100x680 the Train panel (Start training, train progress) sits above the fold. Pinned by test_train_panel_above_fold_at_default_size. (Sleep below the fold is T74's problem.)

### T45 — Dataset picker + validation

- **Origin:** audit #2 T6
- **Covers:** A2-W6, A2-U5, A2-G2, A2-D6
- **Effort:** M
- **Status:** DONE in v0.14.0 (2026-11-14) — the dataset picker validates the file with the trainer's own validator and shows its example count, train/check split, and a 3-example preview, naming the malformed line.
- **Problem:** Probed: `dataset_ref="/no/such/place/data.jsonl"` is
  accepted at creation with no complaint. No existence check, no
  format check, no example count, no preview. A mistyped path or a
  wrong-format file fails at train time, not at configure time — the
  most expensive moment to discover it. The field is a bare text box
  with no file picker (A2-U5): paths must be typed by hand, which
  matters more than usual for a user who hand-types from his phone
  screen. There is no dataset management of any kind (A2-G2).
- **Fix:** Add a browse button (file picker) next to the Dataset
  field in the detail panel, and an existence check at save: warn
  when the path does not exist ("dataset not found — is the path
  right?") without blocking (the file may be created or pulled
  later). Wire the JSONL format check, example count, 3-example
  preview, and train/val split display to Item 3's validator when it
  lands; until then, do a basic readability check (file exists, is
  readable, lines parse as JSON) and report the first malformed line
  number. The picker and the existence check land now; the full
  validator wiring is an Item 3 follow-up inside this task.
- **Done:** The picker fills the Dataset field; saving a missing path
  warns; a valid JSONL file shows an example count and a preview; a
  malformed file reports the bad line number. Tests with fake
  datasets: missing path warning, malformed-line report, example
  count, picker fill.

### T46 — Lock the settings during a run

- **Origin:** audit #4 T12
- **Covers:** A4-W13, A4-D12
- **Effort:** S
- **Status:** MOOTED by T16 (Audit #9 R2) — the settings surface goes away entirely; nothing to build here. Kept in the list, marked, so the coverage map still accounts for its findings.
- **Problem:** Probed: mid-run, the rank spinbox accepted 16 and
  Save wrote it to disk. The running worker already loaded its
  config, so the saved settings no longer describe the run in
  progress — and the next run will use settings the user set
  while watching the previous one. Combined with the dirty-
  tracking gap (T2), edits made during a run that are *not*
  saved are discarded by the completion refresh.
- **Fix:** A4-D12 — disable the project form and Save while
  training runs — or warn that a mid-run save does not affect the
  running config. The form should not offer to change a run in
  progress. (T2 preserves edits made before the lock; this task
  stops edits during the run — land them together if possible.)
- **Done:** During a run the settings form is disabled (or a save
  attempt warns that it does not affect the running config); no
  setting can silently change under a run in progress. Tests:
  form disabled mid-run, save warned or refused mid-run.

### T47 — Reset progress/loss per project; pin the panel to the running project

- **Origin:** audit #4 T11
- **Covers:** A4-W11, A4-W12, A4-D11
- **Effort:** M
- **Note:** Extended by T74 (Audit #9 R7).
- **Status:** DONE in v0.14.0 (2026-11-14) — the train panel stays pinned to the running project (the pin label names it) and progress/loss reset per project.
- **Problem:** `refresh_train_panel` never touches the progress
  bar or the loss label (except setting "Pick a project to
  train." when nothing is selected). Probed: after a run on
  `tool-calls`, switching to `short-replies` — never trained —
  still showed the run's progress and loss. The Train-panel
  screenshot shows the contradiction at its worst: a **25%
  progress bar** above the text "Pick a project to train." with
  no project selected at all. And switching projects mid-run
  mixes the panels: the checkpoint list rebuilt to the new
  project's (empty) list while the progress bar and loss label
  kept showing the running project's values. The early return
  ("never wipe the live log mid-run") protects the log but not
  the rest of the panel, so mid-run the Train panel is half one
  project, half another.
- **Fix:** A4-D11 — selecting a project resets the bar and label
  to that project's state, and while a run is live the Train
  panel follows the running project (or says which project is
  running) instead of mixing panels.
- **Done:** Switch projects after a run: the bar and label reset
  to the new project's state (empty for an untrained project).
  With no project selected, the bar is empty and the label says
  so. Mid-run, switching projects leaves the panel showing the
  running project consistently (or naming it). Tests: progress
  reset on switch, no-selection state, mid-run switch consistency.

### T48 — Cheap checks before the train deps gate

- **Origin:** audit #5 T5
- **Covers:** A5-W5, A5-D5
- **Effort:** S
- **Status:** DONE in v0.13.0 (2026-11-14) — cheap checks run before the training-deps gate, so a missing dataset or settings problem is caught without loading the training stack.
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

### T49 — Put the missing-deps hint where the user can see it

- **Origin:** audit #4 T16
- **Covers:** A4-U8, A4-D25
- **Effort:** S
- **Status:** DONE in v0.14.0 (2026-11-14) — missing training tools are a warning dialog, not a status line.
- **Problem:** Start-without-deps writes the install hint to the
  Training log — which sits at y=996, below the fold (A4-U2). The
  status bar says "see the Train log", but the user has to know
  to scroll for it; on first run, the most likely first-run
  failure hides its own fix.
- **Fix:** A4-D25 — a warning dialog, or auto-scroll the detail
  pane to the log when the hint is written — not a status line
  pointing at a below-fold log.
- **Done:** On a first run without the training deps installed,
  the hint is visible without hunting (dialog, or the detail pane
  scrolled to the log). Tests: hint visible after a deps-missing
  start.

### T50 — Keep confirmations visible (import + training-done)

- **Origin:** audit #3 T13 + audit #4 T15 (merged — one fix)
- **Covers:** A3-U1, A3-D14; A4-U3, A4-D18
- **Effort:** S
- **Status:** DONE in v0.14.0 (2026-11-14) — import and training-done confirmations stay visible instead of vanishing.
- **Problem:** `import_package` says "Imported X into Y"
  (`gui.py:595`), then immediately calls `refresh_profiles`
  (`gui.py:596`), whose selection cascade calls `_say` again with
  "Profile: … — project: …". Probed in the driven GUI: after a
  successful import the status bar reads "Profile: lfm3-tool —
  project: tool-calls." — the import confirmation never survives.
  Export gets a dialog; import gets a message that erases itself. Audit #4 re-verified this (A4-U3) and found training has the same shape: `_on_train_finished` says "Trained N steps." and then `refresh_projects` overwrites it with the selection message. Export gets a dialog; import and training-done get messages that erase themselves.
- **Fix:** Don't let the refresh overwrite the status message: say the confirmation *after* any refresh it triggers, or give import and training-done the same success dialog export already has. Pick one; the confirmation must still be visible after the lists settle — for import *and* for a finished training run.
- **Done:** After an import, the status bar (or a dialog) still shows the import confirmation; after a training run finishes, "Trained N steps." is still visible; the refresh no longer overwrites either. Tests: GUI tests asserting both confirmations survive their refreshes.

### T51 — Help text for every flag, examples in every command, fix the doc drift

- **Origin:** audit #5 T8
- **Covers:** A5-U1, A5-U2, A5-D11
- **Effort:** S
- **Status:** DONE in v0.13.0 (2026-11-14) — help text and worked examples on every CLI command; the doc drift is fixed.
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
  before install. (The `--metamorph` help text itself is T176;
  this task is the rest of the flags plus the examples and the
  drift.)
- **Done:** Every flag on every command has help text; every
  command's `--help` shows a worked example; the docstring, README,
  wrapper comment, and empty-home hint all name commands that
  exist. Tests: help output contains the flag meanings and
  examples.

### T52 — Nothing selected on launch

- **Origin:** repo-audit verdict (R21)
- **Covers:** R21
- **Effort:** S
- **Problem:** gui.py lines 436 and 461 auto-select the first
  profile and the first project at launch — confirmed by the
  verdict. That violates his nothing-selected rule: the window
  opens claiming a selection the user never made, and the detail
  panel shows a project the user did not pick. (Per-profile
  project memory, T125, restores the last project when returning to
  a profile within a session — that is a different behavior and
  stays; this task is about launch only.)
- **Fix:** Launch with no profile and no project selected; the
  detail panel shows its empty state and the action buttons follow
  the selection (T124's _update_actions pass). The status bar keeps
  its "Pick a profile to begin." hint.
- **Done:** Launching with profiles and projects present selects
  nothing; the detail panel is empty; selecting a profile then a
  project works as before. Tests: launch state has no selection
  (GUI test asserting current row is -1 / None on both lists).
- **Status:** DONE in v0.9.0 (2026-11-13) — verified already true: nothing is selected on launch, pinned by test_no_selection_by_default. A returning user's restored session is their own pick coming back, not a default.

### T53 — A real status lifecycle, with UI

- **Origin:** audit #2 T5 + audit #4 T23 (status part; merged — one fix); extended by the repo-audit verdict (R16)
- **Covers:** A2-W5, A2-U4, A2-G1, A2-D5; A4-G5, A4-D22 (status part); R16
- **Effort:** M
- **Status:** DONE in v0.13.0 (2026-11-14) — a real status lifecycle (draft, ready, training, paused, done, failed, exported; trained reads as done via legacy alias) shown on every project row, with status_changed timestamps.
- **Problem:** `status` is free text with no lifecycle and no UI.
  Every project is born `draft` and stays `draft` forever — nothing
  transitions it through training, done, failed, or exported, and
  nothing can: the detail panel has no status control (probed: no
  `proj_status` widget exists), the list shows no status (A2-U4),
  and the model accepts any string (probed: `status="banana"` stored
  fine). An exported project still says `draft`. There is no record
  that a project trained, failed, or finished (A2-G1). Audit #4 confirmed the window face (A4-G5): a project that trained, failed, or exported looks exactly like a draft — no widget anywhere shows or changes status. The verdict re-verified (R16): project status is invisible in the list.
- **Fix:** Make status a validated enum — `draft`, `ready`,
  `training`, `done`, `failed`, `exported` — enforced in the model
  (anything else rejected). Show it in the detail panel (read-only
  label, plus the user-driven transition: draft → ready) and in the
  project list row. Drive the other transitions from actions, not
  free text: training/done/failed from the training engine (Item 3
  wires its transitions into this enum when it lands), exported from
  the export action. Record a timestamp with each transition.
- **Done:** Status is visible in the detail panel and the list row;
  an invalid status string is rejected by the model; exporting a
  project flips it to `exported`; a project can move draft → ready
  from the UI. Training transitions are defined (even though Item 3
  wires them later) and documented. Tests: enum rejection, export
  transition, draft → ready, status shown in both surfaces.

### T54 — One source of truth for the base: resolve `base_ref`

- **Origin:** audit #1 T4
- **Covers:** A1-W3, A1-D3
- **Effort:** M
- **Note:** Extended by T79 (Audit #9 R12).
- **Status:** DONE in v0.13.0 (2026-11-14) — the interim sync rule is in place (base_ref is the one source of truth, synced from the tag where they disagree); the drop-vs-define decision is still Joshua's.
- **Problem:** `ollama_tag` and `base_ref` are two fields with one
  meaning and no sync rule. Create with a tag and `base_ref` is set
  to the same value; change the tag later and `base_ref` stays stale
  — probed: tag updated to `lfm3:2b`, `base_ref` still `lfm3:1.7b`.
  Nothing documents which field Item 3 (training) should trust, and
  the New Profile placeholder ("Same as the tag, unless the base
  lives elsewhere") never explains when they *should* differ, so the
  user cannot tell a deliberate split from an accidental one.
- **Fix:** Decide, then implement (the decision is Joshua's call —
  one line): either drop `base_ref` (the tag IS the base ref, with a
  migration that removes it from existing manifests) or define it
  properly as "HF repo / local path for training" with a one-line
  explanation in the UI. Until the decision lands, apply the sync
  rule: changing the tag updates `base_ref` unless the user
  deliberately split them. Document which field training trusts.
- **Done:** The old probe passes: update a tag and `base_ref`
  follows it (or the field is gone and nothing references it). The
  UI explains what the base field is in one line. Existing profiles
  migrate cleanly. The training docs name the field they trust.
  Tests: tag-update sync test, migration test.

### T55 — Remove or disable the dead "full" method option

- **Origin:** audit #2 T7; extended by the repo-audit verdict (R7, R20)
- **Covers:** A2-W7, A2-U6, A2-D7; R7, R20
- **Effort:** S
- **Status:** SUPERSEDED by T189 (Audit #9 R21) — remove the dead option outright. Kept in the list, marked, so the coverage map still accounts for its findings.
- **Problem:** The Method combo offers `full` next to `lora`, with no
  hint that a full fine-tune of a 1.5–2B model on this CPU is
  infeasible (the brief established this: it needs a free cloud GPU).
  A user picking `full` gets a project that can never complete on his
  PC. The choice looks equal; it is not. The verdict proved the
  stronger claim (R7/R20): `full` is not just infeasible — it is
  dead. train.py never reads the method setting (`full` exists only
  as the DEFAULT_TRAIN literal), so selecting it silently trains
  LoRA. The option does nothing at all. (The model side — any method
  string accepted — is fixed by T6's enum.)
- **Fix:** Remove `full` from the Method combo (or disable it with a
  tooltip explaining it needs a cloud GPU and is not implemented —
  one-line decision, Joshua's call). The model enum in T6 keeps
  accepting `full` so old manifests still load; the GUI just stops
  offering a choice that does nothing. LoRA stays the default for
  new projects.
- **Done:** The Method combo offers only `lora` (or `full` is
  present but disabled with its reason shown); selecting `full` can
  no longer silently train LoRA; a new project defaults to `lora`.
  Tests: `full` absent or disabled, default method, old manifest
  with method `full` still loads.

### T56 — --steps is a real cap

- **Origin:** repo-audit verdict (R11) + audit #5 T3 (merged — same finding)
- **Covers:** R11; A5-W3, A5-D3; A8-W12, A8-D9
- **Effort:** S
- **Problem:** --steps does not cap the run: --steps 2 ran 3 steps
  (rounds up to whole epochs), --steps 0 ran the full 9-step run
  (silently uncapped — 0 is falsy, so the cap block is skipped),
  --steps -1 ran 1 epoch. The help text promises a cap ("cap the
  run at N optimizer steps (proof run)") and the behavior
  contradicts it. (Same finding as audit #5 W3, merged here — audit #5's probes
  are the evidence: --steps 2 ran 3 steps, --steps 0 ran the full
  9-step run, --steps -1 ran 1 epoch, with no argparse validation
  at all.) Audit #8 adds the resume half (A8-W12): the cap and resume
  don't compose — pause at step 4, resume with `max_steps=1`, and
  the total recomputes to 3, raising `StellaError: already at step 4
  of 3 — nothing left to train`, a message stating an impossible
  state.
- **Fix:** Validate --steps in argparse (reject 0 and negative
  values with a plain error) and make the cap real: the run stops
  at N optimizer steps (a partial final epoch is fine for a proof
  run — or document the whole-epoch rounding honestly in the help
  text and print the real total before starting). The Training: N
  steps line already prints the real total; the flag text must
  match it. D9 (A8): apply `_max_steps` as a remaining-steps budget
  from the resume point (`start_step + cap`), not an epoch shrink —
  a resume with a cap trains exactly that many more steps.
- **Done:** --steps 2 runs at most 2 steps (or the help text says
  honestly that it rounds up and prints the real total); --steps 0
  and --steps -1 are refused with a readable error. Tests: cap
  respected, 0/negative rejected. Resume with `--steps N` trains
  exactly N more steps from the resume point instead of erroring.
- **Status:** DONE in v0.10.0 (2026-11-13) — --steps is a real cap: run_training_loop takes a remaining-steps budget (start_step + cap, not an epoch shrink), breaks mid-epoch at the cap, and reaching the cap is completion (adapter saved, status trained), not a pause. 0/negative refused in argparse and in the engine.

### T57 — Merge, don't discard, the profile block on import

- **Origin:** audit #3 T4
- **Covers:** A3-W4, A3-U7, A3-D4
- **Effort:** M
- **Status:** DONE in v0.13.0 (2026-11-14) — profile merge on import (keep local or take package), with compare_profile_block and the {field: {local, package}} diff shape as T58's extension point.
- **Problem:** If the profile already exists, `import_export`
  reuses it and never looks at the manifest's profile block
  (`export.py:143-151`). Probed: importing into a home whose
  `lfm3-tool` had tag `other:9b` and role `driver` left the tag
  and role untouched — the package's `lfm3:1.7b` / `fast` were
  dropped without a word. Probed further: exporting two projects
  from one profile, changing the tag between exports, then
  importing both into a fresh home — the **first** package's tag
  won and the second package's profile block was discarded. No
  warning, no diff, no merge, no choice. Because export is
  one-project-at-a-time (A3-W7), this is the normal way a
  multi-project profile moves between machines — so the normal
  path silently drops profile data. The UI face (A3-U7): nothing
  in the window says so, not even the `profile_existed` flag
  import already returns.
- **Fix:** When the profile exists, compare tag / role / base with
  the manifest: identical → silent; different → warn and let the
  user pick keep-local or take-package (a dialog in the GUI; a
  flag or prompt on the CLI). Surface `profile_existed` in the UI
  (a status message, or the preview dialog from T58).
- **Done:** Import with a differing tag: a choice appears and the
  chosen values win; identical blocks import silently; the UI says
  when the profile already existed. Tests: identical-silent,
  differ-choice in both directions, `profile_existed` surfaced.

### T58 — Import preview dialog

- **Origin:** audit #3 T7
- **Covers:** A3-U2, A3-U7, A3-D10
- **Effort:** M
- **Depends on:** T57 (shows the existing-profile warning + merge choice)
- **Status:** DONE in v0.14.0 (2026-11-14) — import shows a preview (profile, project, tag, version, contents, base health, dataset status) before anything lands; the CLI prints the preview before importing and has --preview.
- **Problem:** One click imports. The user never sees what the
  package contains — profile, project, tag, version — before it
  lands. Pick the wrong folder and the first sign is a new profile
  in the list (or an error).
- **Fix:** Before importing, show profile, project, tag, version,
  and contents (checkpoints, weights, dataset ref) — with the
  existing-profile warning when it applies (T57) — and let the user
  confirm or cancel. On the CLI, print the same summary before
  importing (or add a `--preview` flag — decide in implementation).
- **Done:** Import opens a preview showing the package contents;
  Cancel imports nothing; Confirm imports; the existing-profile
  warning appears in the preview when it applies. Tests: preview
  contents, cancel imports nothing, warning shown.

### T59 — Make the dataset part of the package decision

- **Origin:** audit #3 T6
- **Covers:** A3-W8, A3-G7, A3-D7
- **Effort:** M
- **Status:** DONE in v0.14.0 (2026-11-14) — export offers to copy the dataset into the package; a missing dataset on import gets a locate-and-repair box.
- **Problem:** The dataset is never copied: `dataset_ref` is
  carried as a bare string (probed: no trace of the dataset file
  in the package tree). A project whose dataset is
  `/home/joshua/data/forge-traces.jsonl` exports that absolute
  path — into the manifest **and** the README — and the imported
  project points at the same path on a machine where it may not
  exist. Import never checks whether the referenced path exists
  and never warns. The package is portable; its most important
  input is not. (Related: T45 validates the dataset on the
  project side — picker, existence, format; this task is the
  package side — bundling and the import-side repair.)
- **Fix:** At export, offer "copy the dataset in" (with its size
  shown) or keep the reference; at import, check the referenced
  path exists and warn — with a "locate it on this machine" repair
  — when it does not. If the dataset was bundled, import uses the
  bundled copy. Don't block on a missing dataset (it may live
  elsewhere).
- **Done:** Export with "copy in": the dataset file is in the
  package and used on import; export with reference only: import
  warns when the path is missing and offers to locate it; import
  with an existing path is silent. Tests: bundled round-trip,
  missing-path warning, locate repair.

### T60 — One source of truth for settings

- **Origin:** audit #3 T5
- **Covers:** A3-W3, A3-D6
- **Effort:** S
- **Status:** DONE in v0.13.0 (2026-11-14) — settings have one source of truth in the model, read everywhere from the same place.
- **Problem:** `config.json` is required but never read:
  `verify_export` rejects a package missing it
  (`export.py:131-132`), but nothing ever reads the file — import
  takes settings from the manifest only. Probed: a package with
  **invalid JSON** in `config.json` imports fine; a package whose
  `config.json` says rank 999 imports with rank 16 (the
  manifest's value). So the file is simultaneously mandatory and
  meaningless. Worse, it invites exactly the wrong edit: a user
  who opens the file named "config" and changes a setting has
  changed nothing, and nothing tells them.
- **Fix:** Drop `config.json` from the package (the manifest
  already holds the settings) or make import read it and
  cross-check against the manifest — pick one, document it. Never
  require a file you never read. If dropped: `verify_export` no
  longer requires it, and old packages that carry it still import
  (the extra file is ignored).
- **Done:** A package without `config.json` imports (if dropped),
  or a disagreeing `config.json` is refused or flagged (if
  cross-checked); the chosen rule is documented. Tests: missing
  `config.json`, disagreeing `config.json`, invalid-JSON
  `config.json`.

### T61 — Base-health check on import

- **Origin:** audit #3 T8
- **Covers:** A3-W12, A3-D15
- **Effort:** S
- **Status:** DONE in v0.14.0 (2026-11-14) — import warns when the base model is not installed on this machine and never blocks on it.
- **Problem:** Probed: a package whose profile claims `ollama_tag:
  "not-a-real-model:99"` imports silently and the profile looks
  perfectly healthy — until training or Ollama use fails. A package
  arriving from another machine is exactly when the base is most
  likely to be missing. (Related: T163 shows health badges per row;
  this task is the import-time check. Uses the cached model list
  from T43 when it lands; a direct `list_models()` call is fine
  here — import is user-initiated, not a click.)
- **Fix:** On import, check whether the profile's Ollama tag is
  installed on this machine. Warn when it is not installed ("base
  model not installed on this machine — pull it before training"),
  don't block.
- **Done:** Import a package with an uninstalled tag: a warning
  names the tag; an installed tag imports silently. Tests: warning
  on missing tag, silent on installed tag.

### T62 — `run.sh`: check PySide6 before exec, and fail visibly

- **Origin:** audit #6 T5
- **Covers:** A6-W5, A6-D5
- **Effort:** S
- **Status:** DONE in v0.15.0 (2026-11-14) — run.sh checks PySide6 before exec and fails visibly.
- **Problem:** Probed (P7b): venv present, PySide6 absent →

  ```
  File ".../stella/gui.py", line 21, in <module>
      from PySide6.QtCore import Qt, QThread, Signal
  ModuleNotFoundError: No module named 'PySide6'
  ```

  exit 1, no Stella message. This is the state after any pip
  failure mid-install (A6-W11) — and exactly the failure SKULLPT v1.1
  hit on his PC (`run.sh` failed, PySide6 missing, Bench never
  opened). From the menu, with `Terminal=false`, the user sees
  nothing at all: the window just doesn't open, with no error
  anywhere.
- **Fix:** A6-D5 — if the import fails, print the plain "run
  `bash install.sh`" message instead of a traceback. With
  `Terminal=false`, consider a `zenity`/`kdialog` fallback so a
  menu-launch failure is visible at all.
- **Done:** `run.sh` with a venv but no PySide6 prints a plain
  message naming the fix (and shows a dialog when launched from
  the menu); no traceback. Tests: the P7b shape (venv, no
  PySide6).

### T63 — Make install atomic: check before writing artifacts

- **Origin:** audit #6 T4
- **Covers:** A6-W4, A6-D4
- **Effort:** S
- **Status:** DONE in v0.15.0 (2026-11-14) — install is atomic: it checks before writing anything, so a failed install leaves no launcher behind.
- **Problem:** The desktop file and the `~/.local/bin/stella`
  symlink are written *before* the final `import stella` check.
  Probed (P8): with `stella/__init__.py` sabotaged to raise,
  install exited 1 with `ERROR: Stella did not import after
  install.` — and both artifacts were on disk. The menu entry
  exists, clicking it runs `run.sh` into a crash that is invisible
  (`Terminal=false`), and `stella` runs a broken tree. The install
  is not atomic: failure is reported, but the half-installed state
  looks installed.
- **Fix:** A6-D4 — move the final `import stella` check before the
  desktop file and symlink are written — or roll the artifacts
  back on failure. A failed install must leave no launcher behind.
- **Done:** A sabotaged final check exits 1 with no desktop file
  and no symlink left behind; a good install still writes both.
  Tests: sabotage test in T69.

### T64 — Add the double-click Install Stella.desktop; fix the README install section

- **Origin:** repo-audit verdict (R3) + audit #6 T3 + audit #6 T11 (merged — one install-story fix)
- **Covers:** R3; A6-W3, A6-U1, A6-U2 (README part), A6-D3, A6-D16
- **Effort:** M
- **Status:** DONE in v0.15.0 (2026-11-14) — double-click Install Stella.desktop runs the installer (the proven python3 -c pattern, %k as a separate argv token); the README install section is fixed.
- **Problem:** The README promises a double-click "Install Stella"
  and there is no .desktop file anywhere in the tree — confirmed by
  the verdict (no .desktop found) and by the corrections (the
  published v0.2 zip contains the icon PNGs but NO launcher).
  Audit #6 re-verified live (A6-W3): README.md:21 says "Unzip a
  release anywhere, then double-click Install Stella in the
  folder", install.sh:2 says the same, and `find` over the tree
  and the zip listing both show no .desktop file anywhere.
  Double-clicking `install.sh` itself in Nemo opens a text editor
  (or a run prompt) — it does not install. The documented first
  step for the user who hand-types commands from his phone does
  not exist; the only working path is a terminal and
  `bash install.sh`. The README's install paragraph has two more
  false claims (A6-U1): "puts Stella in the app menu with its star
  icon" — the icon is broken by A6-W1 on every install and absent
  by A6-W2 on a clone — and the `stella`-on-PATH claim (A6-U2):
  install.sh ends with "Command line is available too: stella
  profiles", but `~/.local/bin` joins PATH at login (Mint's
  `~/.profile` adds it only if the dir exists at login time), so
  a terminal already open at install time won't find `stella`
  until logout/login.
- **Fix:** Ship Install Stella.desktop (double-click installer,
  runs install.sh with bash — install.sh needs bash, not sh)
  alongside the existing app-menu launcher, with the icon and an
  Exec line that survives spaced install paths (A6-D3; SKULLPT
  v1.2 shipped a real Install-SKULLPT.desktop for exactly this
  reason). Rewrite the README install section (A6-D16): name a
  real first step, qualify the `stella` command ("open a new
  terminal after install, or log out and back in"), and document
  removal (T137) and move/repair (T66). The README's promise and
  the tree must match.
- **Done:** Double-clicking Install Stella.desktop (or launching
  it via gio launch) runs the installer; the desktop file
  validates (desktop-file-validate clean); the README's first
  install step names a file that exists; the `stella` command
  claim carries its condition; removal and repair are documented.

### T65 — Set exec bits in the tree (run.sh, stella-cli, install scripts)

- **Origin:** repo-audit verdict (R5)
- **Covers:** R5
- **Effort:** S
- **Status:** DONE in v0.15.0 (2026-11-14) — exec bits set in the tree (run.sh, stella-cli, install scripts).
- **Problem:** Every file in the tree is 100644 — confirmed by the
  verdict. A clone install leaves run.sh and stella-cli
  non-executable, so the launchers are dead: the user who clones
  and follows the README gets "Permission denied" (or a dead
  desktop entry) instead of Stella. The zip carries stored modes,
  so the zip path works — the clone path does not. Audit #6
  verified the zip side (P15: stored modes correct, scripts
  0o100755; zip-vs-tree diff shows only the dev tool
  `drive_gui.py`) — so this task is the clone path only, and it
  stands as written.
- **Fix:** Set the executable bit on run.sh, stella-cli,
  install.sh, install-training.sh (and any other script the README
  tells the user to run) in the tree, and add a check (a test or a
  release checklist step) that the bits survive — the zip builder
  already stores modes; the tree must carry them too.
- **Done:** A fresh clone has run.sh, stella-cli, install.sh, and
  install-training.sh executable; `bash run.sh` and
  `bash stella-cli` work from a clone without a chmod step. Tests:
  a test (or a CI step, T130) asserts the exec bits on the scripts.

### T66 — Add a repair/doctor path

- **Origin:** audit #6 T7
- **Covers:** A6-W7, A6-G3, A6-D13
- **Effort:** M
- **Status:** DONE in v0.15.0 (2026-11-14) — `stella doctor` checks and repairs the install after a move (venv, PySide6, launcher, symlink, icon, receipt).
- **Problem:** Everything install.sh writes is an absolute path to
  `$DIR`. Probed (P12): after `mv moveme moved-to`, `gio launch`
  on the desktop file exited 1 (`Unable to load application
  information`), `stella` became `command not found` (exit 127,
  dangling symlink) — while `run.sh` from the new location works
  fine (timeout 124), because it resolves its own dir. Re-running
  `install.sh` from the new location would repair it, but nothing
  says so anywhere; the user is left with a dead menu entry and a
  dead command. And after a move (A6-W7) or a broken venv (A6-W5), the
  only recovery is re-running `install.sh` — which works, but
  nothing says so, and there is no `--check`/`doctor` mode that
  verifies the launcher, symlink, icon, and venv and fixes what's
  stale (A6-G3).
- **Fix:** A6-D13 — a `stella doctor` (or `install.sh --repair`)
  that verifies venv, PySide6, launcher, symlink, and icon, and
  re-links what's stale after a move. Repair re-links a working
  icon (T14), not a broken one.
- **Done:** Move the folder, run the doctor: the launcher and the
  `stella` command work again from the new location; a broken
  venv is reported with the fix named. Tests: move-then-doctor.

### T67 — Add `--timeout 120 --retries 10` to install.sh's pip lines

- **Origin:** audit #6 T8
- **Covers:** A6-W8, A6-D6
- **Effort:** S
- **Status:** DONE in v0.15.0 (2026-11-14) — install.sh's pip lines carry --timeout 120 --retries 10.
- **Problem:** `install-training.sh` got `--timeout 120 --retries
  10` as a v0.2 fix because "pip's default 15s read timeout
  repeatedly failed the torch download" (TEST-REPORT defect #4).
  `install.sh:36-37` still runs plain `--quiet` pip installs —
  for a ~90 MB PySide6-Essentials wheel on the same slow
  connection. The base install can fail exactly the way the
  training install used to. (Code reading + the v0.2 defect
  record; not live-probed with a throttled connection.)
- **Fix:** A6-D6 — same fix as install-training.sh already has.
- **Done:** install.sh's pip lines carry the flags; a
  slow-connection install retries instead of failing at 15 s.
  Tests: flags present (grep test).

### T68 — `run_tests.sh` must use the venv, never system pip

- **Origin:** audit #6 T6
- **Covers:** A6-W6, A6-D17
- **Effort:** S
- **Status:** DONE in v0.15.0 (2026-11-14) — run_tests.sh uses the venv, never system pip.
- **Problem:** When no `.venv` exists it falls back to system
  `python3` and runs `"$PY" -m pip install --quiet pytest` (and
  PySide6-Essentials) into system Python. Probed (P11) on this
  sandbox's Python 3.12.3 — the same version as his Mint PC, also
  externally managed:

  ```
  Installing pytest for the test run...
  error: externally-managed-environment
  ```

  exit 1. TEST-REPORT defect #3 claims the bare-checkout path was
  fixed ("it now installs PySide6-Essentials when the import
  fails, so the suite runs from a fresh unzip") — but the
  mechanism installs into system Python, which Mint forbids. The
  documented `bash run_tests.sh` only works after `install.sh`
  has made the venv.
- **Fix:** A6-D17 — create/use `.venv` for the test run, or refuse
  on a bare checkout with "run `bash install.sh` first". Never
  `pip install` into system Python on Mint.
- **Done:** `bash run_tests.sh` on a bare checkout either runs
  the suite via a venv or refuses with the plain message; no
  externally-managed error. Tests: bare-checkout run.

### T69 — Add installer tests, including the GLib icon check

- **Origin:** audit #6 T10
- **Covers:** A6-G2, A6-D12
- **Effort:** M
- **Status:** DONE in v0.15.0 (2026-11-14) — installer tests (31), including the GLib icon check.
- **Problem:** No `test_installer.py`; the only test references
  to the installers assert that error messages *name*
  `install-training.sh` (`test_cli.py:119,160`,
  `test_gui.py:121`, `test_train.py:236`). The installer is
  verified only by the manual fresh-unzip check in
  TEST-REPORT.md — which is how A6-W1 survived: the manual check read
  the desktop file but never asked GLib what the icon resolves to.
- **Fix:** A6-D12 — a `test_installer.py` that runs `install.sh` in
  a scratch HOME and asserts: the desktop file parses, the icon
  resolves via GLib, the symlink works, re-install is idempotent,
  a clone without PNGs renders or warns. The icon-resolution check
  is the one that would have caught A6-W1. Lands alongside T14 — the
  test pins the P0 fix.
- **Done:** The suite includes installer tests covering the
  desktop file, the GLib icon resolution, the symlink, re-install
  idempotence, and the clone-without-PNGs case; the icon test
  fails against the pre-fix installer. Tests: the new file
  itself.

### T70 — Define what each mode means, in writing, before building the codec

- **Origin:** audit #7 T1
- **Covers:** A7-W1, A7-W7, A7-W10, A7-D1
- **Effort:** S
- **Problem:** The mode does nothing, for either reading. No code
  path in `train.py`, `probe.py`, or `gguf.py` references metamorph
  at all (grep -c = 0 for each). Setting a project to `compress`
  does not change its training, its probe, its GGUF export, or its
  package; setting it to `morph` does not create, track, or manage
  variants. Probed behaviorally (audit #7 P8): identical-init tiny
  training runs in `morph` and `compress` gave final loss
  `5.564785480499268` for both, 3 steps, 4,096 trainable params,
  same target modules, and byte-identical adapter weights (SHA-256
  prefix `e3a36ab43103649b` for both). `both` is a third label, not
  morph-plus-compress: no code branches on it, and nothing defines
  what the combination would do (A7-W7). The code's own honesty
  marker is stale: `model.py:37` comments `METAMORPH_MODES` with
  "structure only in v0.1 — no codec yet" while the tree is v0.2
  (A7-W10). This is P1, not P0: the README documents the inert mode
  honestly, nothing is lost, and nothing crashes. But it is the
  defining weakness of the component — the name MetaMorphAi
  promises two behaviors and the program delivers neither.
- **Fix:** D1 — a short spec in the README (and a code comment
  replacing the stale `model.py:37` line): what `morph` does, what
  `compress` does, what `both` does and in which order. This is a
  writing task, not a code task — and it is the first task: the
  wiring (T73, T72, T183, T188) cannot be built correctly against
  an undefined word. The honest rule for the spec: if a mode cannot
  be defined, it comes out of the combo rather than shipping as a
  third kind of nothing (define the modes and wire the first real
  effect, or remove the mode).
- **Done:** The README and the code comment define all three modes
  in writing; `both` has a stated order; the stale v0.1 comment is
  gone. Tests: none — verify by reading the spec against the audit.

### T71 — Fix the tooltip: honest words, one line

- **Origin:** audit #7 T5
- **Covers:** A7-U1, A7-U2, A7-D6
- **Effort:** S
- **Problem:** `gui.py:322-325`, probed verbatim (audit #7 P7):
  "MetaMorphAi: morph turns the base into variants, compress
  shrinks how the fine-tune is stored, both does both." Present
  tense, describing effects. None of the three clauses is true
  (A7-W1, A7-W6). This is the *only* tooltip in the entire window
  (A4-U7) — the one explanation the GUI offers anywhere is the one
  that is wrong — and it directly contradicts the README's honest
  "the codec lands in a later item." A user who hovers learns the
  opposite of the truth. The project list compounds it (A7-U2):
  rows read `Display name — both` (`gui.py:449-451`) with no
  indication the suffix is a label, so a user reasonably reads "—
  compress" as "this project will compress."
- **Fix:** D6 — replace the present-tense promise with the truth,
  e.g.: "MetaMorphAi mode — a label for now; the morph/compress
  codec lands in a later item." Do not wait for the codec to fix
  the words. Once the tooltip is honest, the list suffix is a fair
  label (A7-U2) — verify that and note it; the suffix itself does
  not change.
- **Done:** The tooltip states the truth; the list suffix is
  unchanged but no longer misleading beside an honest tooltip.
  Tests: tooltip text assertion.
- **Status:** DONE in v0.9.0 (2026-11-13) — the metamorph tooltip vanished with the control in v0.8 (zero "metamorph" in gui.py); pinned by the test asserting no metamorph_combo exists.

### T72 — Wire `compress` to real compression: GGUF quant + package compression

- **Origin:** audit #7 T7
- **Covers:** A7-G2, A7-W6, A7-D2, A7-D3
- **Effort:** M
- **Problem:** No quantization choice driven by mode (GGUF always
  defaults to Q4_K_M, `gguf.py:29`); no adapter compression; no
  package compression; no token-level compression ("the same
  meaning in fewer tokens" has no code behind it — no dataset
  tokenization/dedup step at train time). The only real compression
  in Stella (GGUF quantization) is entirely disconnected from the
  mode that names compression. The measurable form: audit #7 P2
  exported the same-shaped project in `morph` and `compress` and
  diffed the packages — identical file lists, and the only
  mode-caused differences are the mode string itself. Total bytes:
  `morph` 1,643 B, `compress` 1,665 B — the "compress" package is
  *larger*, because the word "compress" is longer than "morph"
  (A7-W6).
- **Fix:** D2 — `export-gguf` already takes `--quant` and defaults
  to Q4_K_M (`gguf.py:29,142`). One branch: mode `compress`
  defaults the quant a step smaller (e.g. Q3_K_M), `morph` keeps
  Q4_K_M, `--quant` always overrides, and the choice is printed.
  D3 — mode `compress` ships the export as a compressed archive
  (zip) instead of (or alongside) the plain folder; `morph` keeps
  the plain folder as today. Import must accept both forms. Depends
  on T70 (the definitions). The deep token-level codec is T188, not
  this task.
- **Done:** A `compress` project exports GGUF at the smaller quant
  unless `--quant` overrides; a `compress` export is a zip that
  imports; a `morph` project is unchanged. Tests: quant default
  per mode, override wins, zip export/import round-trip.

### T73 — Variant lineage for `morph`: spawn + parent record

- **Origin:** audit #7 T6
- **Covers:** A7-G1, A7-D4
- **Effort:** M
- **Problem:** There is no operation that turns a base into a
  variant differently per mode, no way to spawn a variant project
  from another, and no record of which project descended from
  which. "Morphing" today means "a project exists under a profile"
  — true of every project regardless of mode.
- **Fix:** D4 — a project can spawn a variant project (copy
  settings/dataset, new slug, `metamorph.parent` recorded in the
  manifest); the project list shows lineage. This is what "a base
  model morphs into specialized variants" looks like at Stella's
  scale — not a new architecture, a family tree with a spawn
  operation. Depends on T70 (the definitions): `morph` must mean
  something before a spawn operation can implement it.
- **Done:** Spawning a variant creates a project with the parent
  recorded; the list shows the lineage; export carries the parent
  record. Tests: spawn-through, lineage display, parent in the
  manifest.

### T74 — One job card for every job, with progress and cancel

- **Origin:** audit #9 R7
- **Covers:** A9-U3, A9-G4 (part), A9-G12
- **Effort:** M
- **Library:** 021 Glanceable surfaces
- **Extends:** T107 (progress and cancel for GGUF/probe jobs), T29 (one job at a time: the card enforces it visibly), T47 (reset progress/loss per project: the card owns per-job state).
- **Status:** DONE in v0.12.0 (2026-11-14) — all six jobs run as cards (train/sleep via their workers feeding the card, requant/distill/export/probe via _start_job_worker) with progress + cancel; a second job is refused in plain words.
- **Problem:** Sleep is a buried section below the fold, and GGUF export and the refusal probe run with no progress and no cancel. The user waits blind.
- **Fix:** Train, Sleep, GGUF export, refusal probe, re-quantize, and distill all run as job cards with a progress bar, a live status line, and a Cancel button. Sleep stops being a section at the bottom of a column. Starting a second job is refused with plain words.
- **Done:** Every job shows progress and offers cancel; no job is below the fold while it runs.

### T75 — Re-quantize and distill get window surfaces

- **Origin:** audit #9 R8
- **Covers:** A9-U2 (part)
- **Effort:** M
- **Library:** 005 Bento grids
- **Status:** DONE in v0.12.0 (2026-11-14) — "Make smaller" (re-quantize) and "Teach a small model" (distill) run from the window as jobs with the same card flow as Train and Sleep; How to Use has zero "terminal" mentions for them.
- **Problem:** Two shipped jobs (v0.8.0) have no window surface: How to Use sends the user to the Chat or to the terminal.
- **Fix:** The job picker lists "Make smaller" (re-quantize) and "Teach a small model" (distill) as jobs with the same card flow as Train and Sleep. How to Use stops sending the user to the terminal for them.
- **Done:** Both jobs start from the window with no typing.

### T76 — Chat: click-to-pick model, plan before it runs

- **Origin:** audit #9 R9
- **Covers:** A9-U5, A9-G11
- **Effort:** M
- **Library:** 010 AI-native patterns, 012 Progressive disclosure
- **Status:** DONE in v0.12.0 (2026-11-14) — the chat shows clickable model buttons when no model is picked, shows its plan before a multi-step run (Run/Cancel), and streams replies as they arrive.
- **Problem:** With no chat model picked, the chat makes the user type a tag by hand from eleven raw names. And the agent never shows its plan before running: one "just do it" can download, create, and start hours of training with no preview.
- **Fix:** When no chat model is picked, the chat shows clickable model buttons from the installed list instead of "type one of these". Before a multi-step plan runs, the agent shows the plan ("I will: 1. ... 2. ...") with Run and Cancel. Replies stream as they arrive.
- **Done:** No typing is needed to pick a chat model; "just do it" shows its plan first and waits for Run.

### T77 — The session follows the profile

- **Origin:** audit #9 R10
- **Covers:** A9-G6
- **Effort:** S
- **Library:** 022 Per-context profiles
- **Supersedes:** T125 (remember the project per profile).
- **Status:** DONE in v0.12.0 (2026-11-14) — the last project is stored per profile; switching back to a profile restores its project (verified live by the coordinator).
- **Problem:** The session is one global slot; switching profiles loses the project context.
- **Fix:** Store the last project per profile; switching profiles restores that profile's project. The active profile is visible at a glance.
- **Done:** Switch away from a profile and back; the project is back.

### T78 — Tree rows show full names, with a health badge

- **Origin:** audit #9 R11
- **Covers:** A9-U6
- **Effort:** S
- **Library:** none
- **Extends:** T163 (health badge per profile row), T164 (richer project rows).
- **Status:** DONE in v0.12.0 (2026-11-14) — a wider tree pane, tooltips carrying the full row text, and a health badge per profile (weights ready, weights missing, Ollama down).
- **Problem:** Long model names truncate in the 235 px pane with no tooltip, so the user cannot read which model a profile is.
- **Fix:** A wider default pane, tooltips carrying the full row text, and a small health badge per profile (weights ready, weights missing, Ollama down).
- **Done:** The MiniCPM5 row is readable in full (tooltip or wrap); each profile shows its weights state at a glance.

### T79 — One honest download row

- **Origin:** audit #9 R12
- **Covers:** A9-W2, A9-W3, A9-D2
- **Effort:** S
- **Library:** none
- **Extends:** T54 (tag/base_ref sync: this is the UI face of it; the model fix stays T54's).
- **Status:** DONE in v0.12.0 (2026-11-14) — one download row, in the main window; the Profile window duplicate is gone; Download is disabled when there is no repo, and the self-referential label is fixed.
- **Problem:** The download row is duplicated in two windows; the button is enabled when there is no repo; and the Profile window says "No Hugging Face repo set" next to a filled Base ref field, telling the user to go to the window they are already in.
- **Fix:** One download row, in the main window; the Profile window's duplicate goes away. Download is disabled when there is no repo, and the label says what to do as a button that opens the profile window. The self-referential label is fixed. The Base ref field stops showing a tag as if it were a repo.
- **Done:** In the no-repo state, Download is disabled and the screen offers a working path to fix it; no duplicate row exists.

### T80 — Collapsible section headers

- **Origin:** audit #9 R13
- **Covers:** A9-U4, A9-G10
- **Effort:** M
- **Library:** 012 Progressive disclosure
- **Status:** DONE in v0.12.0 (2026-11-14) — CollapsibleSection in the main panel, Settings, and the Project window; the action row stays reachable without scrolling the whole form.
- **Problem:** Save project sits below the fold in its own window, and Settings is a 1,165 px scrolling wall in a 625 px viewport. The brief asks for collapsible headers in panels.
- **Fix:** The main panel and Settings get collapsible headers. The action row (Save, Close, Debug report) stays reachable without scrolling the whole form.
- **Done:** At 1100x680, Save project is visible without scrolling; every Settings section is a collapsible group.

### T81 — STELLA's own look: one stylesheet

- **Origin:** audit #9 R14
- **Covers:** A9-G2
- **Effort:** M
- **Library:** 001 Micro-interactions (limited), 002 Spring physics (limited)
- **Status:** DONE in v0.12.0 (2026-11-14) — STELLA's own dark + gold stylesheet (stella/style.py), applied by main() to every window; verified by pixel probe (window bg rgb 28,28,28, gold accent present).
- **Problem:** No application stylesheet exists; the app runs in default Qt grey and could be any program.
- **Fix:** One stylesheet applied by `main()`, drawn from the icon (dark surfaces, one accent), applied to every window. Button press dips to 0.97 over 150 ms. No per-frame blur, no layout thrash, nothing that costs frames on the Vega 3.
- **Done:** The app is recognizable as STELLA in a screenshot; every window carries the look.

### T82 — Keyboard: shortcuts and a visible focus ring

- **Origin:** audit #9 R15
- **Covers:** A9-U8
- **Effort:** S
- **Library:** 023 Focus-first navigation
- **Extends:** T127 (window chrome pass: shortcuts are part of it).
- **Status:** DONE in v0.12.0 (2026-11-14) — shortcuts Ctrl+N, Ctrl+S, Ctrl+G, F1, F2 with a visible 2 px gold focus ring in the stylesheet; tab order in visual order. (F2 later moved to rename in v0.21.0, chat to F3.)
- **Problem:** No keyboard shortcuts exist anywhere, and there is no visible focus styling.
- **Fix:** Shortcuts for the main actions (new profile, new project, start training, How to Use, Chat), a visible focus ring in the stylesheet, and tab order in visual order.
- **Done:** Every main action is reachable by keyboard; the focus ring is visible in a screenshot.

## P2 — missing capabilities and inconsistencies

### T83 — Dataset health panel before training starts

- **Origin:** repo-audit verdict (R27)
- **Covers:** R27
- **Effort:** M
- **Status:** DONE in v0.16.0 (2026-11-14) — before training starts, Stella checks the dataset's health: it blocks on a failing check and asks on a tiny dataset.
- **Problem:** Nothing checks the dataset before a run starts — a
  malformed file, a wrong-format row, or a 3-example dataset
  fails (or silently trains garbage) hours into a run. T45
  validates the dataset at configure time (picker, existence,
  format); this is the pre-flight check at train time: row count,
  format errors, token-length distribution, and a warning when
  the dataset is too small or malformed for the settings.
- **Fix:** A pre-train dataset health check in the Train panel
  (and a CLI pre-flight at train time): row count, valid/invalid
  rows with line numbers, format (prompt/completion vs messages),
  and a rough token estimate; a failing check blocks the run with
  the errors named, a warning (tiny dataset) asks to proceed.
  Builds on T45's validator.
- **Done:** Starting a run with a malformed dataset is refused
  with the bad line numbers; a 3-example dataset warns before
  starting; a healthy dataset shows its row count and format.
  Tests: malformed refusal, tiny-dataset warning, healthy
  summary.

### T84 — RAM/time estimate in the detail panel

- **Origin:** audit #2 T9
- **Covers:** A2-W9, A2-G4, A2-D8
- **Effort:** M
- **Note:** Extended by T18 (Audit #9 R4).
- **Status:** DONE in v0.16.0 (2026-11-14) — the detail panel shows whether the run fits in 8 GB and roughly how long it will take, with zero settings words.
- **Problem:** Rank up to 64, seq len up to 32768, batch up to 32,
  epochs up to 100 — all selectable with no RAM or time estimate.
  The defaults are good, but the extremes are swap death on 8 GB
  with no warning at configure time. Item 3's RAM guard will refuse
  at train time; the settings panel should say so before the user
  invests in a doomed configuration. There is no cost estimate of
  any kind today (A2-G4) — the user configures blind.
- **Fix:** Show a rough estimate in the detail panel for the current
  settings, reusing Item 3's RAM-guard math: "fits in 8 GB" or "will
  not fit" for RAM, plus a rough time note (orders of magnitude, not
  a promise). Warn, don't block: a configuration that will not fit
  gets a visible warning but can still be saved (the user may intend
  to train it elsewhere). The estimate updates as settings change.
  The math comes from Item 3 — if the guard has not landed yet,
  build the estimate display against a small documented estimator
  and swap in the guard's math when it arrives.
- **Done:** Rank 64 + seq 32768 shows "will not fit"; the defaults
  show "fits"; changing a setting updates the estimate; an
  over-large configuration warns but still saves. Tests: estimate
  states for known-good and known-bad settings, update-on-change.

### T85 — Dry-run estimate button (RAM fit + steps + disk, without loading the model)

- **Origin:** repo-audit verdict (R28)
- **Covers:** R28
- **Effort:** M
- **Depends on:** T84 (estimate display), T28 (honest RAM guard)
- **Status:** DONE in v0.16.0 (2026-11-14) — the Estimate button works out RAM fit + steps + disk without loading the model (metadata only, shared with the display).
- **Problem:** There is no way to ask "will this run fit, how
  long, how much disk" without starting the run — the
  detail-panel estimate (T84) shows RAM fit for the current
  settings, but there is no single dry-run that answers all three
  questions before the user commits hours. And any estimate that
  loads the model to compute itself defeats the purpose (R8).
- **Fix:** A "Dry run" / "Estimate" button in the Train panel (and
  a CLI flag): computes RAM fit (from T28's honest estimator —
  metadata only, no model load), the step count for the dataset +
  settings, and the disk needed (checkpoints + adapter + merged
  weights), and shows all three before the user starts. Reuses
  T84's display math; does not duplicate it.
- **Done:** Dry-run on a project shows RAM fit, step count, and
  disk needed without loading the model (proven by a test
  asserting no load happened); an over-budget dry-run warns
  before the run starts. Tests: estimate values for a known
  project, no-load proof.

### T86 — Export a profile on its own

- **Origin:** audit #1 T12 + audit #3 T15 (merged — one profile export)
- **Covers:** A1-G4; A3-W7, A3-G3
- **Effort:** M
- **Depends on:** T40 (package format defines the profile kind)
- **Status:** DONE in v0.18.0 (2026-11-14) — profiles export on their own now (kind stella-profile-export, CLI export-profile, File menu).
- **Problem:** Export is per-project; a profile with zero projects
  cannot be moved, backed up, or shared. Combined with A1-W5, the
  only copy of a profile is the live one. Audit #3 confirmed the
  gap in full: there is no `export_profile` function, no CLI
  command, and the GUI Export button needs a selected project — a
  profile with no projects cannot be exported at all, and a
  profile with N projects must be exported N times, each package
  carrying a full duplicate of the profile block (which feeds
  A3-W4: the second package's profile block is silently discarded
  on import).
- **Fix:** Add profile export using the profile package kind from
  T40 (`kind: "stella-profile-export"`, per audit #3's D1 format
  decision — versioned format, named kinds, version check): a
  package holding the profile manifest (and, as an option, all its
  projects), importable back with the same strict verification the
  project import does (T1). The format decision is settled, so
  this task builds on T40 rather than waiting on the audit. GUI:
  Export offers profile export when a profile is selected; CLI: a
  `stella export-profile` command. Profile notes (T166) are
  included in the package.
- **Done:** Export a project-less profile, delete it, import the
  package: the profile returns with tag, role, base, and settings
  intact. Export with projects includes them. A corrupt profile
  package is refused with a readable error. Tests: round-trip with
  and without projects, corrupt-package rejection.

### T87 — CLI parity: rename, delete, update, show (profiles + projects)

- **Origin:** audit #1 T7 + audit #2 T11 (merged — one `cli.py` change); audit #5 T16 (G1–G3, merged — same commands)
- **Covers:** A1-W9, A1-D11; A2-W11, A2-D13; A7-G7, A7-D15 (update half); A5-G1, A5-G2, A5-G3, A5-D15 (commands/show/settings half)
- **Effort:** M
- **Status:** DONE in v0.18.0 (2026-11-14) — the terminal gains rename, delete, update, and show for profiles and projects (all eight commands + settings flags on create/update-project; the CLI is a power path, not a screen). --processor deliberately NOT included: blocked on T128's undecided processor-field meaning, pinned by test_cli_update_profile_has_no_processor_flag.
- **Problem:** The CLI can list and create profiles and projects but
  cannot rename, delete, or change either. Scripted management (bulk
  rename after the System Test run, for example) has to go through
  the GUI or hand-edited JSON. Audit #5 re-verified all three
  gaps on the CLI (A5-G1/G2/G3): no rename/delete/update
  commands (all probed: exit 2), no show/status/checkpoints
  command (a user cannot ask what a project's dataset is, what
  its settings are, or what checkpoints it has — except by
  reading the JSON by hand; most sharply, no way to see what
  `train` is about to use before starting a run that may take
  hours), and no way to set training settings from the CLI
  (`stella train` always runs the defaults unless the user edits
  the GUI or the JSON by hand).
- **Fix:** One `cli.py` change adding both sets of commands, reusing
  the Store methods and error messages the GUI already uses.
  Profiles: `stella rename-profile <old> <new>`,
  `stella delete-profile <name>` (trash behavior per T23, plus a
  `--purge` flag for permanent removal),
  `stella update-profile <name> [--role ...] [--tag ...]
  [--display ...] [--base ...] [--processor ...]`, and
  `stella show-profile <name>` (full manifest, readable). Projects:
  `stella rename-project <profile> <old> <new>`,
  `stella delete-project <profile> <name>` (trash behavior per T23,
  plus `--purge`),
  `stella update-project <profile> <name>` (flags for display,
  dataset, metamorph, and each setting), and
  `stella show-project <profile> <name>` (full manifest, readable).
  `create-project` also takes settings flags (rank, epochs,
  learning rate, batch size — the same flags as `update-project`),
  and `show-project` lists the project's checkpoints (A5-G2), so
  the user can see what `train --resume` would use.
  Audit #7's G7 — the CLI cannot change a mode after creation — is
  fixed by the update-project `--metamorph` flag above; no separate
  task. (The `--metamorph` help text is T176.)
- **Done:** All eight commands work end to end from a terminal
  against a scratch home; both deletes move to trash (T23); errors
  print the same messages as the GUI. Tests for all eight commands
  including bad-name and missing-item exits.

### T88 — CLI `projects` must refuse a nonexistent profile

- **Origin:** audit #5 T9 (W8/D8 part)
- **Covers:** A5-W8, A5-D8
- **Effort:** S
- **Status:** DONE in v0.18.0 (2026-11-14) — a ghost profile is refused, exit 1.
- **Problem:** `stella projects ghost` → exit 0, `No projects in
  profile 'ghost'.` — byte-identical in shape to an empty real
  profile. `list_projects` returns `[]` when the directory is
  missing, and `cmd_projects` never checks the profile exists. A
  typo'd profile name reads as "you haven't made any projects yet"
  instead of "that profile doesn't exist".
- **Fix:** D8 (existence half) — `cmd_projects` checks the profile
  exists first (`No profile named 'ghost'`, exit 1). (The
  corrupt-warning half of D8 is T3; the atomic-import half is T1.)
- **Done:** `projects` on a nonexistent profile exits 1 with a
  plain error; on an empty real profile it still prints the empty
  message and exits 0. Tests: ghost profile refused, empty real
  profile clean.

### T89 — One-click Ollama create after GGUF export

- **Origin:** repo-audit verdict (R26)
- **Covers:** R26
- **Effort:** S
- **Status:** DONE in v0.18.0 (2026-11-14) — one-click Ollama create after GGUF export (create_in_ollama + GUI button + CLI --create).
- **Problem:** After a GGUF export the user must copy the printed
  `ollama create` command and run it by hand in a terminal — the
  last step of the fine-tune loop is manual. The export already
  prints the exact commands (audit #5 verified); the window just
  never runs them.
- **Fix:** After a successful GGUF export, offer "Create in
  Ollama" (a button in the success dialog / Train panel): runs
  `ollama create <name> -f <Modelfile>` with the exported name,
  shows the output, and reports success or the Ollama error
  plainly. The CLI keeps printing the commands (and gains a
  --create flag if it stays simple).
- **Done:** One click after export creates the model in Ollama
  (verified against a fake Ollama); a failed create shows the
  error; the manual commands are still printed. Tests:
  create-after-export against a fake Ollama, failure path.

### T90 — Probe gate informational mode

- **Origin:** repo-audit verdict (R9)
- **Covers:** R9
- **Effort:** S
- **Status:** DONE in v0.16.0 (2026-11-14) — the refusal probe knows governing seats (Driver, Reviewer, Fast/tester) from the rest: governing seats get the pass/fail gate, everything else gets counts with no verdict. (Coordinator fix: the builder's set was wrong — it gated judge/merger/grader/router and treated driver/fast as informational; fixed to GOVERNING_ROLES = driver, reviewer, tester, fast, with a forgiving substring match on the free-text role.)
- **Problem:** The docs describe an informational probe mode, but
  the probe gate has none — every probe run is a pass/fail gate.
  For a stock base (LFM3) the probe is informational by design
  (the probe is a gate only for governing seats), but there is no
  way to run it that way: the output and exit code always carry a
  verdict.
- **Fix:** Add an informational mode to the probe (a
  --informational flag on the CLI, and the GUI's probe action uses
  it for non-governing profiles): before/after counts and the
  change are reported, no pass/fail verdict, exit 0 regardless of
  the change. The gate mode stays for governing seats (per the
  abliteration guard). (Lands with T10's probe rework if
  convenient — both touch probe.py.)
- **Done:** An informational probe prints the counts and the change
  with no verdict and exits 0 even when refusals rose; a gate
  probe still fails its exit code when the gate fails. Tests: both
  modes, exit codes.

### T91 — A distinct exit code for a failed probe gate

- **Origin:** audit #5 T11
- **Covers:** A5-W12, A5-D10
- **Effort:** S
- **Status:** DONE in v0.16.0 (2026-11-14) — a failed probe gate exits 3 (a crash still exits 1), with the gate verdict to stderr.
- **Problem:** `cmd_probe` returns `0 if passed else 1`
  (`cli.py:189`). A script — or a user reading the exit code —
  cannot tell "the probe ran and the gate failed" from "the probe
  crashed". The gate message itself goes to stdout, mixed with the
  results, so there is no clean way to separate the verdict from
  the numbers either.
- **Fix:** D10 — return a code other than 1 for "probe ran, gate
  failed" (3, say — 2 is argparse's), and print the gate verdict
  to stderr or behind `--json` (T172) so scripts can read the
  verdict separately from the numbers. (The informational probe
  mode is T90 — a gate probe that fails still fails its exit code;
  an informational probe exits 0 regardless.)
- **Done:** A failed gate exits 3 (not 1); a crashed probe still
  exits 1; the verdict is readable separately from the numbers.
  Tests: gate-fail exit 3, crash exit 1, informational exit 0.

### T92 — Probe provenance in the results file

- **Origin:** audit #8 T20
- **Covers:** A8-G3, A8-D16
- **Effort:** S
- **Status:** DONE in v0.16.0 (2026-11-14) — probe results carry their provenance (timestamp, base_ref, adapter, max_new_tokens, prompts_version) and mode.
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

### T93 — Hard-benign prompts in the probe set

- **Origin:** audit #8 T21
- **Covers:** A8-G4
- **Effort:** S
- **Status:** DONE in v0.16.0 (2026-11-14) — 6 hard-benign prompts added to the probe set (18 total, the 12 original unchanged); PROMPTS_VERSION = 2.
- **Problem:** All 12 prompts are trivially benign. A model
  could regain refusals on edgy-but-legitimate requests —
  dual-use help, security-adjacent questions, contentious topics
  — while scoring 0/12. The gate cannot see the failure mode it
  exists to catch at the margin where it matters. (The verdict
  thread's idea of per-role probe sets, T174, points the
  same way.)
- **Fix:** Add hard-benign prompts to the set — requests that
  are legitimate but sit near the refusal boundary — so the
  gate measures the margin, not just the easy middle. Keep the
  12 trivial prompts; the hard ones are additional.
- **Done:** The probe set includes hard-benign prompts; a model
  that refuses only at the margin scores above 0. Tests: set
  contents, a margin-refusing model caught.

### T94 — Surface the probe in the window

- **Origin:** audit #8 T19
- **Covers:** A8-U4, A8-D17
- **Effort:** M
- **Note:** Extended by T148 (Audit #9 R19).
- **Status:** DONE in v0.16.0 (2026-11-14) — the probe is surfaced in the window (View probe results button, ProbeResultsDialog).
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

### T95 — Proof-run control in the window: the GUI can't do a short --steps run

- **Origin:** audit #8 T17
- **Covers:** A8-U2
- **Effort:** S
- **Status:** DONE in v0.16.0 (2026-11-14) — the Proof run button runs 5 steps to prove the setup.
- **Problem:** The CLI has `--steps` for a quick proof run; the
  GUI's Start training always runs the full epoch budget
  (`gui.py:961` passes no `max_steps`, and no control exists).
  A user who wants a 2-minute smoke test before an hours-long run
  has to use the terminal — the thing the window exists to
  avoid.
- **Fix:** A step-cap control in the Train panel (a spin box or
  a "proof run" button that runs a short cap), passed through as
  `max_steps`. Pairs with T56 (the cap must be real).
- **Done:** A window user can start a capped proof run and it
  stops at the cap. Tests: GUI test, cap honored.

### T96 — The val loss in the run summary and the window

- **Origin:** audit #8 T18
- **Covers:** A8-U3, A8-G8
- **Effort:** S
- **Note:** Extended by T148 (Audit #9 R19).
- **Status:** DONE in v0.16.0 (2026-11-14) — the final validation loss is in the run summary and the window (the summary is written only when the finish message carries "Validation loss").
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

### T97 — LFM3 → GGUF conversion pre-flight

- **Origin:** audit #8 T23
- **Covers:** A8-G11
- **Effort:** S
- **Status:** DONE in v0.17.0 (2026-11-14) — the GGUF export checks the converter supports the model's architecture first (parses @Model.register from the installed converter) and refuses an unsupported arch naming it. LFM3 arch support in the real llama.cpp converter needs his PC.
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

### T98 — Resume contract: snapshot settings at pause, warn on drift

- **Origin:** audit #8 T10
- **Covers:** A8-W10, A8-W11, A8-D8
- **Effort:** S
- **Status:** DONE in v0.17.0 (2026-11-14) — resume snapshots settings into training_state.json and warns (never refuses) on drift, and warns on a missing optimizer.pt.
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

### T99 — Bound completions to max_seq_len

- **Origin:** audit #8 T15
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
- **Status:** DONE in v0.10.0 (2026-11-13) — completions are bound to max_seq_len (head + EOS kept, truncated flag); the loop warns with the count of cut examples, shown by the CLI, the GUI, and sleep. No sequence may exceed max_seq_len, because the RAM estimate assumes it cannot.

### T100 — End the completion with the template's turn terminator

- **Origin:** audit #8 T16
- **Covers:** A8-W17, A8-D14
- **Effort:** S
- **Status:** DONE in v0.17.0 (2026-11-14) — the tuned model learns to end its turn the way the chat template expects (renders a probe assistant turn and appends the turn terminator instead of EOS when defined). End-to-end with a real chat-template tokenizer needs his PC.
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

### T101 — Quote paths in the Modelfile and the printed command

- **Origin:** audit #8 T14
- **Covers:** A8-W15, A8-D12
- **Effort:** S
- **Status:** DONE in v0.17.0 (2026-11-14) — the printed Ollama command works when pasted (shlex.quote on the Modelfile FROM + printed command). Whether Ollama's Modelfile parser accepts a quoted FROM needs real Ollama.
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

### T102 — Check the quantizer is executable at discovery

- **Origin:** audit #8 T13
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
  T93; this task is only the executability half.)
- **Done:** A non-executable quantizer is refused at discovery
  with a plain error naming the file; an executable one is
  found as before. Tests: chmod-644 quantizer, executable
  quantizer.
- **Status:** DONE in v0.10.0 (2026-11-13) — find_llama_cpp requires the quantizer to be executable (os.access X_OK); a non-executable file is refused naming the file and the chmod +x fix.

### T103 — Timeout on the converter/quantizer subprocesses

- **Origin:** audit #8 T22
- **Covers:** A8-G7
- **Effort:** S
- **Status:** DONE in v0.17.0 (2026-11-14) — a 30-minute timeout on the converter/quantizer subprocesses, naming the hung step, instead of hanging forever.
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

### T104 — Checksums + sizes in the manifest

- **Origin:** audit #3 T9
- **Covers:** A3-W9, A3-D8
- **Effort:** M
- **Status:** DONE in v0.18.0 (2026-11-14) — every package carries checksums (sha256 + size per file); import refuses a mismatch naming the file; legacy packages import unverified.
- **Problem:** The manifest carries no checksums, sizes, or file
  list. Probed: a checkpoint truncated from 800 bytes to 4
  (`FAKE`) imported without complaint — the corrupted file now
  sits in the home as if it were a real checkpoint. A half-copied
  package, a truncated download, a flipped bit: import cannot
  tell.
- **Fix:** A sha256 (or at least a byte size) per file in the
  manifest, verified on import; a mismatch fails loudly — refuse
  the import, or import with a clear warning naming the file
  (decide in implementation; failing loudly is the default). Cover
  checkpoints, weights, notes, and the dataset when bundled (T59).
- **Done:** A truncated checkpoint is refused or flagged on import;
  an intact package imports silently; the manifest lists a hash +
  size per file. Tests: truncated-file rejection, intact import,
  hash coverage of each member.

### T105 — A verify command

- **Origin:** audit #3 T12; audit #5 T16 (G4, merged — same command)
- **Covers:** A3-G5, A3-D12; A5-G4, A5-D15 (verify half)
- **Effort:** S
- **Depends on:** T1 (schema validation), T40 (version check), T104 (checksums)
- **Status:** DONE in v0.18.0 (2026-11-14) — Check package verifies without importing (check_export + format_check_report + cmd_verify + File > Check package).
- **Problem:** `verify_export` exists but no CLI command or GUI
  action exposes it — the only way to check a package is to
  import it. Audit #5 re-verified the gap on the CLI (A5-G4):
  `verify_export` exists in `export.py:123` and has no CLI
  surface — a user who receives an export package cannot check it
  from the terminal before importing it.
- **Fix:** `stella verify <dir>` on the CLI (and a "Check
  package" action in the GUI) that runs the full verification —
  schema, version, checksums — without importing. Print a
  readable pass/fail per check.
- **Done:** `stella verify` on a good package reports all checks
  pass; on a bad package it names the failing check; nothing is
  imported either way. Tests: verify good/bad, no-import
  guarantee.

### T106 — Progress, cancel, and refresh on failure

- **Origin:** audit #3 T14
- **Covers:** A3-U4, A3-U5
- **Effort:** M
- **Status:** DONE in v0.18.0 (2026-11-14) — export and import run in the background with progress and cancel; lists refresh on failure.
- **Problem:** Export and import run synchronously in the
  button-click handler — no progress indicator, no cancel, no
  background thread. A v0.2-scale checkpoint copy will freeze the
  window with no progress bar and no way to stop it. And after
  the raw-crash failure (A3-W2), the orphan profile exists on disk
  but the list shows 0 rows — `refresh_profiles` runs only on the
  success path (`gui.py:596`), so the user cannot even see the
  stray profile the failure left behind.
- **Fix:** Move export/import to a background thread with a
  progress indicator and a cancel; refresh the lists on failure
  too (once T1 lands, a failed import leaves no orphan to show —
  but the refresh must still run so the window reflects the disk).
  Cancel mid-copy leaves no partial state (ties to T1's
  atomicity).
- **Done:** A large export shows progress and can be cancelled,
  leaving no partial package; a failed import refreshes the lists
  so the window matches the disk. Tests: cancel leaves no partial
  state, failure refreshes the lists.

### T107 — Progress and cancel for GGUF/probe jobs

- **Origin:** audit #4 T22 (job part; checkpoint part → T119); extended by the repo-audit verdict (R23)
- **Covers:** A4-G4, A4-D21 (job part); R23
- **Effort:** M
- **Note:** Extended by T74 (Audit #9 R7).
- **Status:** DONE in v0.18.0 (2026-11-14) — GGUF export shows real phase progress (merge/convert/quantize 1/2/3) and the probe shows per-prompt progress.
- **Problem:** No progress or cancel for GGUF/probe jobs:
  `JobWorker` has no progress signal — a multi-minute GGUF
  export shows only log lines, and there is no way to stop it
  once started. Training has Pause; jobs have nothing. The verdict
  re-verified (R23): GGUF export and probe have no cancel and no
  progress. (The
  checkpoint half of A4-D21 — resume, delete, disk usage — is
  T150.)
- **Fix:** A4-D21 (job part) — a progress signal (or at least an
  indeterminate bar + a stop button) on `JobWorker`. The stop
  acts on the single running job from T29.
- **Done:** A running GGUF/probe job shows progress and can be
  stopped; stopping leaves no partial state. Tests: job progress
  shown, job stop.

### T108 — Second Ctrl+C force-quits; make the download interruptible

- **Origin:** audit #5 T10
- **Covers:** A5-W11, A5-D9
- **Effort:** S
- **Status:** DONE in v0.18.0 (2026-11-14) — a second Ctrl+C quits at once (train + sleep), exit 130.
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
  first Ctrl+C pauses gracefully (T4), the second exits
  immediately. For the base download, run it in a way the stop
  flag can interrupt (or at least print `Downloading base weights
  — Ctrl+C takes effect when the download finishes` so the wait is
  not a mystery).
- **Done:** A second Ctrl+C during a run exits immediately; a
  Ctrl+C during the download either interrupts it or the user was
  told it would wait. Tests: second-Ctrl+C exits (stubbed loop),
  download message shown.

### T109 — Progress for long phases; honest paused/resumed output

- **Origin:** audit #5 T14
- **Covers:** A5-U6, A5-U7, A5-U8, A5-D14
- **Effort:** S
- **Status:** DONE in v0.17.0 (2026-11-14) — long runs print what phase they're in and the paused summary says how far it got.
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
  validation line on a resumed epoch with no new steps. (The GUI
  side — progress/cancel for GGUF/probe jobs — is T107.)
- **Done:** A probe run prints a line per pass; the GGUF merge
  prints a start line; a paused run's tail says Paused, not
  Trained; a resumed run prints no validation line for an epoch it
  did not train. Tests: pass lines present, paused wording, no
  stale validation line.

### T110 — Silence the library warnings on stderr

- **Origin:** audit #5 T12
- **Covers:** A5-U4, A5-D12
- **Effort:** S
- **Status:** DONE in v0.17.0 (2026-11-14) — stderr carries Stella's messages, not the libraries' warnings (filtering only; the .detach() fix was verified already landed).
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

### T111 — CLI-appropriate error text

- **Origin:** audit #5 T13
- **Covers:** A5-U5, A5-D13
- **Effort:** S
- **Status:** DONE in v0.17.0 (2026-11-14) — the CLI's no-dataset error names --dataset; the Train panel wording is kept in the window.
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

### T112 — Clone project, and project templates

- **Origin:** audit #2 T10
- **Covers:** A2-W13, A2-G5, A2-D9
- **Effort:** M
- **Status:** DONE in v0.18.0 (2026-11-14) — clone a project in one click (settings/dataset/mode, no checkpoints), or start from a template (templates as JSON; the LFM3 preset uses audit defaults — rank 8, lr 0.0002, epochs 3, mode "both" — unconfirmed by Joshua, noted in CHANGELOG).
- **Problem:** Same dataset + settings, second try (different rank,
  different metamorph mode) means creating a fresh project and
  re-entering everything. The most common fine-tuning workflow —
  try, compare, vary one knob — has no shortcut. There are no
  known-good starting points either (A2-G5): every project starts
  from the same generic defaults.
- **Fix:** Add a Clone action (GUI button + `Store.clone_project`):
  same dataset, settings, and metamorph mode under a new name, no
  checkpoints copied, fresh notes with a "cloned from X" header
  line. Add project templates: a template picker at New Project
  time, with the first template an "LFM3 tool-format" preset carrying
  known-good settings (confirm the preset values with Joshua, or use
  the audit's recommended defaults as the starting point). Templates
  live as JSON in the tree so new ones can be added without code.
  (Related: T121 clones profiles; the two clone actions share the
  pattern but copy different objects — keep them separate.)
- **Done:** Clone a project: the new project appears with identical
  settings, dataset, and metamorph mode under its own name, zero
  checkpoints, and a "cloned from" note; the original is untouched.
  Creating from the LFM3 template pre-fills the preset values.
  Tests: clone copies settings, clone does not copy checkpoints,
  template pre-fill, clone-name collision rejected.

### T113 — A real New Project form

- **Origin:** audit #2 T13
- **Covers:** A2-W12; A7-W9, A7-U4, A7-D10
- **Effort:** S
- **Status:** SUPERSEDED by T15 (Audit #9 R1) — the job picker is project creation now. Kept in the list, marked, so the coverage map still accounts for its findings.
- **Problem:** The GUI creates a project from a single name prompt —
  no dataset, no metamorph choice, no settings. Every project starts
  identical and must be configured afterwards, one field at a time.
  The CLI already has the flags (`--dataset`, `--metamorph`); the
  GUI never got the form. Audit #7 re-confirmed this unchanged in
  v0.2 (A7-W9, A7-U4): every GUI-created project starts as `morph`,
  and the mode combo sits below the fold at 1100×680 — the mode is
  decided at creation and editable only after scrolling.
- **Fix:** Replace the name-only prompt with a real New Project
  dialog (a QDialog, centered on the parent, Enter submits): name,
  display name, dataset (with the picker from T45), metamorph mode,
  and a template picker (T112) when templates exist. Settings stay in
  the detail panel after creation — the form covers identity,
  dataset, and mode only. Defaults apply when fields are left blank. (Use the same real-QDialog pattern as T11.)
- **Done:** Create a project from the GUI with a dataset and a
  metamorph mode in one step; blank fields fall back to the defaults;
  Enter submits the dialog. Tests: dialog create-through with
  dataset + mode, defaults when blank.

### T114 — Merge the three notes into one surface

- **Origin:** audit #2 T12
- **Covers:** A2-W10, A2-D12; A7-W8, A7-U3, A7-D7
- **Effort:** S
- **Problem:** `metamorph.notes` has no UI (the combo edits mode
  only); `settings["notes"]` exists in the defaults but nothing
  reads or writes it; `notes.md` is the only notes surface the user
  can reach. Three fields with overlapping purposes, two of them
  unreachable — and a user hand-editing the JSON cannot tell which
  one matters. Audit #7 re-confirmed this unchanged in v0.2
  (A7-W8, A7-U3): the combo edits mode only, the CLI has
  `--metamorph` but no notes flag, and the detail panel's Notes area
  is `notes.md` — the other notes.
- **Fix:** Drop `settings["notes"]` (migration removes it from
  existing manifests; document the removal in the CHANGELOG). Add a
  metamorph-notes field to the detail panel — a small text area
  under the MetaMorphAi combo, saved with the project, plus a
  `--metamorph-notes` flag on `stella create-project` (A7-D7). Label
  it distinctly from the `notes.md` area ("Why this mode" vs
  "Project notes"). Keep
  `notes.md` as the running log. Document in the README which notes
  live where: metamorph notes = why this morph/compress choice;
  notes.md = the running log of the fine-tune.
- **Done:** `settings["notes"]` is gone from new and migrated
  manifests; metamorph notes are editable in the detail panel and
  persist, and settable from the CLI at creation; `notes.md` is
  unchanged. Tests: migration removes the
  dead key, metamorph-notes save-through, CLI flag sets notes.

### T115 — Make config and dependencies reachable (JSON editor)

- **Origin:** audit #1 T10
- **Covers:** A1-W7, A1-D12; A1-G1 (first step)
- **Effort:** M
- **Problem:** `config` and `dependencies` exist in the manifest and
  `update_profile` allows changing them, but no UI and no CLI
  reaches them — the only way to set them is hand-editing JSON. The
  "own clean environment" half of the profile promise is currently
  unbuildable through Stella itself. Item 3 will need somewhere to
  put per-profile training config.
- **Fix:** Add a config/deps editor to the detail panel: a plain JSON
  text area for `config` and an editable list for `dependencies`,
  validated on save (bad JSON is rejected with the parse error, and
  nothing is written). Expose both through `update-profile` (T87) as
  well. This is the first step toward A1-G1; full environment
  management is T182.
- **Done:** Edit config JSON in the detail panel, save, reopen: the
  values persist and `show-profile` prints them. Invalid JSON is
  refused with a readable error and the old values stay. Tests:
  save-through, invalid-JSON rejection, CLI update path.

### T116 — Canonical roles wired to the rename plan, with a governing-seat warning

- **Origin:** audit #1 T8
- **Covers:** A1-W6, A1-G2, A1-D8
- **Effort:** M
- **Problem:** There is no canonical seat list, so the rename plan
  (role names from System Test measurements) has nothing to land on,
  and nothing connects a profile's role to a Forge seat or to the
  abliteration guard: a governing seat needs an abliterated base,
  and Stella never checks. A typo'd role ("drvier") silently becomes
  a new pseudo-role.
- **Fix:** Define one canonical role/seat list shared with Forge
  (driver, reviewer, vision, fast, tester, all-rounder, utility —
  confirm the final list with Joshua; it should match the System
  Test rename output). Roles outside the list are still allowed but
  flagged as custom. Add a governing-seat marker on a profile (a
  seat it is bound for, when set): if a governing seat is marked and
  the base is not abliterated, warn before any training starts. (The
  single-control part of A1-W6 — role combo in the detail panel —
  is T122.)
- **Done:** The role field offers the canonical list everywhere it
  appears; a custom role is visibly marked custom; marking a profile
  for a governing seat with a stock base produces a warning naming
  the seat and the base. Tests: canonical list present, custom-role
  flag, governing-seat warning fires and does not fire for an
  abliterated base.

### T117 — Collision options

- **Origin:** audit #3 T10
- **Covers:** A3-W11, A3-D9
- **Effort:** M
- **Status:** DONE in v0.18.0 (2026-11-14) — collisions are choices (overwrite prompt, --force, --as-copy, --replace with trash backup).
- **Problem:** Export refuses an existing folder and import
  refuses an existing project, and that is the end of it: no
  `--force`, no "replace", no "import as a copy under a new name",
  no merge. Every collision is a dead end that sends the user out
  to a file manager to delete or rename by hand — for a user who
  works from his phone screen, that is a real friction point, not
  a nicety.
- **Fix:** Export: an overwrite prompt in the GUI and a `--force`
  flag on the CLI (with a confirm). Import: "import as a copy"
  (new slug) or replace with a backup of the old project (to
  trash, per T23). Collisions should be choices, not dead ends.
- **Done:** Export over an existing folder offers overwrite;
  import of an existing project offers copy-under-new-name or
  replace-with-backup; the old project is recoverable after a
  replace. Tests: each option end to end.

### T118 — Preserve timestamps

- **Origin:** audit #3 T11
- **Covers:** A3-W10, A3-D11
- **Effort:** S
- **Status:** DONE in v0.18.0 (2026-11-14) — created/updated + exported_at in the manifest, restored on import.
- **Problem:** `created` and `updated` are not in the manifest
  (manifest keys are exactly `kind`, `profile`, `project`,
  `stella_version`). Import stamps fresh timestamps
  (`model.py:188`, `model.py:309`). An imported project looks
  brand new; its history — when it was made, when it last changed
  — is gone. (In the probe the source and imported timestamps
  matched only because both ran inside the same second; the
  manifest carries no timestamp to preserve.)
- **Fix:** Carry the original `created` / `updated` in the
  manifest and restore them on import, plus an `exported_at`
  stamp for provenance (the first piece of A3-G6 — the rest is
  T179).
- **Done:** Export then import: `created` / `updated` match the
  source; `exported_at` records the export time. Tests: timestamp
  round-trip, `exported_at` present.

### T119 — Notes backup

- **Origin:** audit #2 T14
- **Covers:** A2-G7, A2-D11
- **Effort:** S
- **Status:** DONE in v0.18.0 (2026-11-14) — notes keep a backup of the previous version (rotating notes.md.1 + README restore docs).
- **Problem:** `notes.md` is a single overwrite on every save; a
  mistaken save loses the previous notes with no backup.
- **Fix:** On each notes save, keep the previous version: a rotating
  `notes.md.1` backup (simplest) or dated copies under a
  `notes-history/` folder capped at N versions — pick the rotating
  single backup unless Joshua wants history. Document the restore
  path (move the backup back over `notes.md`) in the README. (Applies
  to project notes; profile notes from T166 get the same treatment
  when they land.)
- **Done:** Save notes twice; the previous version is recoverable
  from the backup; the restore path is documented. Tests: backup
  created on save, backup holds the previous content.

### T120 — Delete dialogs name what's being destroyed

- **Origin:** repo-audit verdict (R24)
- **Covers:** R24
- **Effort:** S
- **Problem:** The delete confirm dialogs say the delete "cannot
  be undone" but never say what is being destroyed — no
  profile/project name, no project count, no mention of
  checkpoints or notes. The user confirms blind. (T9 makes No
  the default; T23 moves deletes to trash — this task is the
  dialog text itself.)
- **Fix:** The delete dialog names the item (profile or project
  display name + slug), counts what goes with it (N projects,
  checkpoints, notes), and states where it goes (trash, per T23)
  or that it is permanent (purge).
- **Done:** Deleting a profile with projects shows the name, the
  project count, and the trash destination; deleting a project
  names its checkpoints. Tests: dialog text contains the name and
  counts.

### T121 — Clone profile

- **Origin:** audit #1 T6
- **Covers:** A1-W10, A1-D7
- **Effort:** S
- **Problem:** Same base, second role means re-entering everything
  by hand. The common case — one base, two jobs (e.g. qwen3.5:2b as
  all-rounder AND as vision backup) — has no shortcut.
- **Fix:** One Clone action (GUI button + `Store.clone_profile`):
  same tag/base/role/processor/config/deps, new name, no projects
  copied (offer to copy projects as an option if it stays simple).
- **Done:** Clone a profile: the new profile appears with the same
  tag, base, role, and settings under its own name, with zero
  projects; the original is untouched. Tests: clone copies fields,
  clone does not copy projects by default, clone-name collision
  rejected.

### T122 — Small UI fixes: tooltips and role combo in detail

- **Origin:** audit #1 T9 (dialog items split out to T11) + audit #4 T13 (row-tooltips part); extended by the repo-audit verdict (R15)
- **Covers:** A1-U1, A1-U5, A1-D10 (tooltip/role part); A4-U1, A4-D16 (row-tooltips part); A1-W6 (control-consistency part); R15
- **Effort:** M
- **Problem:** Two verified UI flaws, plus a re-verification. (A1-U1) Long tags truncate in the profile list (`maternion/minicpm5-heretic:2b` shows as `matern...`, `qwen3-vl:2b-instru`) and there is no tooltip — the only `setToolTip` in the whole GUI is on the metamorph combo — so hovering tells you nothing. Audit #4 re-verified this (A4-U1): the MiniCPM5 row is 343px of text in a 250px pane with no tooltip, and a horizontal scrollbar is the only escape. The verdict re-verified (R15): long tags truncate in the 260 px profile pane. (A1-U5) Role is a combo in the dialog but a bare text field in the detail panel — same field, two controls, and the suggestions vanish the moment the profile exists. (The dialog items from this task — A1-U2, A1-U3 — moved to the P0 dialog task T11: audit #4 raised the dialog to P0.)
- **Fix:** Set a tooltip on every profile list row showing the full display name, role, and tag (A4-D16, row part). Replace the detail panel's role text field with the same editable combo (canonical list from T116, plus custom entry).
- **Done:** Hovering a truncated row shows the full tag; the detail panel's role field offers the same suggestions as the dialog. Tests: tooltip text present on rows, detail role combo offers the canonical list.

### T123 — Clear the whole panel with no selection

- **Origin:** audit #4 T17
- **Covers:** A4-W14, A4-D13
- **Effort:** S
- **Problem:** The no-project branch of `_show_project_detail`
  (`gui.py:506`) clears the text fields and notes but leaves the
  spinboxes, the method combo, and the metamorph combo showing
  values. Visible in the 1100x680 screenshot: with
  `empty-profile` selected (no projects), the panel shows Method
  `lora`, rank 8, epochs 3, batch 1, seq 1024 — settings for a
  project that does not exist — while Learning rate sits empty
  (it was cleared). `Save project` stays enabled and clicking it
  silently does nothing. The panel state does not reflect the
  selection state.
- **Fix:** A4-D13 — the no-project branch should reset spinboxes,
  combos, and method to blank/default and disable Save, so the
  panel never shows settings for a project that is not there.
- **Done:** With a profile selected but no project, the panel
  shows no settings values and Save is disabled. Tests:
  no-selection panel state, Save disabled.
- **Status:** DONE in v0.9.0 (2026-11-13) — the v0.4 restructure fixed this: a no-project session shows no settings values. Pinned by test_no_project_session_has_no_settings.

### T124 — Buttons follow the selection; panes explain themselves

- **Origin:** audit #4 T20
- **Covers:** A4-U4, A4-U5, A4-D19
- **Effort:** M
- **Problem:** With an empty store, every action button is
  enabled: Start, Resume, Export GGUF, Run refusal probe,
  Export, Import, Rename, Delete. Clicking Rename/Delete/Save
  with no selection does *nothing at all* — no dialog, no status
  change — while Export and New project warn. The same dead click
  teaches two different lessons depending on which button it was.
  And empty panes give no guidance: a profile with no projects
  shows a blank white list; an empty store shows two blank white
  lists. The only voice is the status bar ("Pick a profile to
  begin."). Nothing in the panes says what to do next. (The
  Export button's enablement is T167 — implement consistently in
  the same `_update_actions` pass.)
- **Fix:** A4-D19 — disable actions with nothing to act on, in one
  `_update_actions` pass; put a one-line hint in an empty list
  ("No projects yet — New project to start").
- **Done:** With nothing selected, the action buttons are
  disabled; with a selection, the applicable ones enable; an
  empty list shows its hint. Tests: button states per selection
  state, hint text present in empty panes.

### T125 — Remember the project per profile

- **Origin:** audit #4 T19
- **Covers:** A4-W17, A4-D15
- **Effort:** S
- **Status:** SUPERSEDED by T77 (Audit #9 R10) — the session follows the profile. Kept in the list, marked, so the coverage map still accounts for its findings.
- **Problem:** `_on_profile_selected` resets `_current_project`
  to None (`gui.py:467-473`), so returning to a profile always
  lands on its first project. Probed (corrected): select
  `tool-calls`, switch profiles, switch back — the window shows
  `short-replies` (row 0), not the project the user was working
  on. The first probe passed by coincidence (row 0 happened to be
  the project under test); the corrected probe confirms there is
  no memory.
- **Fix:** A4-D15 — keep the last selected project for each
  profile and restore it on return, instead of always landing on
  row 0.
- **Done:** Select a non-first project, switch profiles, switch
  back: the same project is selected. Tests: project memory
  across a profile round-trip.

### T126 — Give the splitter honest minimums

- **Origin:** audit #4 T18
- **Covers:** A4-W15, A4-W16, A4-D14
- **Effort:** S
- **Problem:** `splitter.setSizes([260, 200, 640])` (`gui.py:270`)
  produced `[270, 273, 531]`: the middle pane cannot be 200px
  wide because its three buttons need ~273px, so the detail pane
  loses ~110px to the button rows. At minimum window size the
  detail pane shrinks to ~331px. The layout's numbers are
  aspirational; the button rows set the real floor. And both list
  panes can be dragged away entirely: `setSizes([0, 0, 1100])`
  collapsed both the profile and project panes to width 0.
  `childrenCollapsible` defaults to true, so a stray drag can
  lose both lists with no obvious restore — the handles are still
  there, but a user who has never seen a collapsed splitter has
  no reason to know that.
- **Fix:** A4-D14 — set minimum widths on the panes (or drop the
  unachievable 200px request) and set `childrenCollapsible` to
  false, so a drag cannot lose a pane.
- **Done:** The panes cannot be dragged to width 0; the requested
  splitter sizes are achievable and honored (within a few pixels);
  the detail pane keeps its width at default and minimum size.
  Tests: drag-to-zero refused, sizes honored.

### T127 — Window chrome pass: icon, geometry, shortcuts

- **Origin:** audit #4 T21 + audit #6 T16 (window-icon part; merged — one fix); extended by the repo-audit verdict (R17, R18, R22)
- **Covers:** A4-U6, A4-G1, A4-G2, A4-D20; A6-U5, A6-D14; R17, R18, R22 (shortcuts part)
- **Effort:** M
- **Note:** Extended by T82 (Audit #9 R15).
- **Problem:** Three chrome gaps. (A4-U6) No window icon:
  `windowIcon().isNull()` is true; the title bar shows Qt's
  default icon, although the gold-star icon ships in `assets/`
  (SVG + PNGs) and the app-menu entry uses it. The running window
  does not look like Stella. (A4-G1) No geometry or state
  persistence: no `QSettings` anywhere — window size, splitter
  positions, and the last selection are forgotten on every
  launch. The user re-arranges the window every time they open
  it. (A4-G2) No keyboard shortcuts: no Ctrl+S to save, no Ctrl+N
  for a new profile/project, no mnemonics on any button. The
  window is mouse-only except for list arrows and Tab. The verdict
  re-verified all three (R17/R18/R22): no geometry persistence, no
  window icon set in code, no menu bar or keyboard shortcuts — the
  shortcuts part is this task; the menu bar is T169. Audit #6
  re-verified the window icon (A6-U5): no `setWindowIcon` / `QIcon`
  anywhere in the tree (grep) — the window, taskbar, and alt-tab
  show Qt's generic icon even though a star icon sits in
  `assets/`. The `.desktop` icon (once T14 is fixed) covers the
  menu, not the running window.
- **Fix:** A4-D20 + A6-D14 — set the window icon from the shipped
  star art (`QIcon` from `assets/stella.png`, guarded if the file
  is missing); persist size, splitter, and last selection with
  `QSettings`; add the two shortcuts that matter (Ctrl+S save,
  Ctrl+N new).
- **Done:** The window shows the star icon (title bar, taskbar,
  alt-tab); relaunching restores the size, splitter positions, and
  last selection; Ctrl+S saves the current panel and Ctrl+N opens
  a new profile/project. Tests: icon set (including the
  missing-file guard), persistence round-trip, shortcuts fire.

### T128 — Define the `processor` field

- **Origin:** audit #1 T11
- **Covers:** A1-W8
- **Effort:** S
- **Problem:** `processor` is a bare text field with no label help,
  no picker, no validation. Is it a tokenizer name, a processor
  class, a local path? The user cannot tell from the window, and
  nothing downstream reads it yet — it is a field waiting for a
  definition.
- **Fix:** Decide what `processor` means (one-line decision needed
  from Joshua: tokenizer/processor identifier, class name, or local
  path — or drop the field if Item 3 does not need it). Then: a
  one-line explanation beside the field, validation or a picker
  matching the definition, and a README line documenting it.
- **Done:** The UI explains what `processor` is in one line; an
  invalid value is rejected or warned about (per the definition);
  the README documents the field. If the decision is to drop it, the
  field is removed from the manifest, the GUI, and the docs, with a
  migration for existing profiles.

### T129 — Fix the maternion typo (6 places)

- **Origin:** repo-audit verdict (R6)
- **Covers:** R6
- **Effort:** S
- **Status:** RESOLVED, no change (2026-11-14) — premise false: the live Ollama namespace is "maternion" (m-a-t-e-r-n-i-o-n, 9 letters, no 'u', no trailing 's'), verified by machine check against the live ollama.com page (crawled 2026-11-14 09:45 UTC); STELLA and Forge already use exactly those 9 letters. T129's quoted "maternions" (10 letters, with 's') and "quaternions" (11 letters) exist neither on Ollama nor in the code. Applying the Fix would have broken the driver tag.
- **Problem:** The word is spelled "maternions" in 6 places and
  "quaternions" in 0 — counted byte-exact by the verdict —
  including live code in drive_gui.py:22, visible in the window.
  A typo in visible UI text and in code, six times over.
- **Fix:** Correct all 6 occurrences (code, comments, UI strings,
  docs) to "quaternions" and grep the tree for the same
  misspelling anywhere else (the verdict notes the same typo shape
  in getcompute). A grep-based test guards against reintroduction.
- **Done:** grep finds 0 occurrences of "maternions" and the
  correct "quaternions" wherever the word is meant; the window
  shows the corrected text. Tests: a spelling guard (grep test)
  for the typo.

### T130 — LICENSE, .gitignore, pinned training requirements, CI

- **Origin:** repo-audit verdict (R13); extended by audit #6 T14 (pin side)
- **Covers:** R13; A6-W13, A6-D10 (pin side)
- **Effort:** M
- **Status:** DONE in v0.15.0 (2026-11-14) — MIT LICENSE, .gitignore covering secrets and venvs, pinned requirements (requirements-base.txt + requirements-train.txt), and CI (base + train jobs running the full suite offscreen). The repo description/topics half is GitHub-side, still owed via browser.
- **Problem:** The repo has no LICENSE, no .gitignore, no pinned
  training requirements, and no CI — and no description or topics
  on GitHub. Anyone cloning the repo gets no license terms, no
  ignore rules (so .venv/ and __pycache__/ land in the tree), no
  reproducible training stack (unpinned torch/transformers/peft/
  accelerate drift), and no automated check that the suite passes.
  Audit #6 proved the pin gap live in code (A6-W13): `pip install
  PySide6-Essentials`, `torch`, `transformers`, `peft`,
  `accelerate` are all unpinned. The train venv happens to hold
  torch 2.15.0+cpu / transformers 5.22.2 / peft 0.21.2 /
  accelerate 1.15.0 because of when it was built, not because the
  script says so. A future release can change behavior under the
  same installer, and nothing records which versions an install
  actually got.
- **Fix:** Add a LICENSE (his call on which — ask, or default to
  MIT and note it), a .gitignore (venv, __pycache__, .stella
  homes, build artifacts), pinned training requirements
  (requirements-train.txt with exact versions matching the
  verified stack: torch 2.15.0+cpu, transformers 5.22.2, peft
  0.21.2, accelerate 1.15.0), a GitHub Actions CI workflow running
  the base suite (and the train suite where feasible), and set the
  repo description + topics on GitHub. Pin PySide6-Essentials in
  the base install too (a requirements-base.txt or the same pinned
  file); install.sh consumes the pinned file. (The record-them
  alternative — writing the installed versions into an install
  receipt — is T139.)
- **Done:** LICENSE present; .gitignore covers venv/pycache/homes;
  install-training.sh consumes the pinned file; install.sh
  consumes the pinned PySide6 version; a fresh install gets
  exactly the verified versions; CI runs the suite on push; the
  repo has a description and topics. Tests: the CI workflow itself
  (a run proves it).

### T131 — Push the current docs to the repo

- **Origin:** repo-audit verdict (R14)
- **Covers:** R14
- **Effort:** S
- **Problem:** What is pushed to GitHub lags what is in the tree:
  audit #4's, audit #5's, audit #6's, audit #7's, and audit #8's reports,
  the standalone task lists, and the updated merged list (now 168
  tasks) are not
  on main yet — the verdict read the repo and found the audits
  stale vs v0.2. (The verdict's specific claim — "audit #3 has no
  task list" — is WRONG: audit #3 has a standalone task list and
  is fully covered in the merged list. The real gap is the push,
  not the writing.)
- **Fix:** Push the current docs (audit #4, #5, #6, #7, and #8 reports,
  all standalone task lists, this merged list) to the repo on the
  next ship cycle, and keep the docs push part of the ship cycle
  so the repo never lags the tree again. (No new writing — the
  docs exist; this task is the push.)
- **Done:** main carries audit #4, #5, #6, #7, and #8 reports and the
  current merged list; the repo's docs match the tree. (Verified
  by read-back after the push.)
- **Status:** DONE in v0.9.0 (2026-11-13) — verified already true: the audit #8 report and audit #4 task list are on main (docs pushes be33e328 + 8f2f0b22 carried them). No code change; marked DONE after coordinator verification.

### T132 — Wrap pip failures in a Stella error

- **Origin:** audit #6 T12
- **Covers:** A6-W11, A6-D8
- **Effort:** S
- **Status:** DONE in v0.15.0 (2026-11-14) — pip failures are wrapped in a Stella error naming the real failure.
- **Problem:** Both installers run pip bare under `set -e`, so a
  pip failure exits at the pip line and the friendly fatal checks
  never run. Probed twice: ENOSPC during the PySide6 install →
  raw `ERROR: Could not install packages due to an OSError:
  [Errno 28] No space left on device`, exit 1, no Stella line;
  dead torch index (P9c) → 180+ seconds of pip `WARNING:
  Retrying ...` lines, no Stella message at all. The user gets
  pip's diagnostics, not Stella's.
- **Fix:** A6-D8 — on a pip exit != 0, print a plain line naming the
  step ("PySide6 download failed — check your connection and run
  `bash install.sh` again") instead of leaving raw pip output as
  the last word.
- **Done:** A failed pip install ends with a Stella line naming
  the step and the retry; raw pip output is no longer the last
  word. Tests: failing-pip harness (dead index or ENOSPC).

### T133 — Disk-space preflight

- **Origin:** audit #6 T13
- **Covers:** A6-W12, A6-D9
- **Effort:** S
- **Status:** DONE in v0.15.0 (2026-11-14) — a disk-space preflight runs before installing.
- **Problem:** Neither installer checks free space before
  downloading (~90 MB wheel / 259 MB installed for the base;
  ~2 GB for training). The only "disk space" strings in the
  scripts are inside the post-failure error messages. On his 1 TB
  HDD this is unlikely to bite, but the failure mode is a
  mid-download ENOSPC with raw pip output (probed in miniature in
  P1's first attempt).
- **Fix:** A6-D9 — check free space before downloading (~500 MB base,
  ~3 GB training) and refuse plainly when it won't fit.
- **Done:** An install with too little free space refuses before
  downloading, naming the space needed; a normal install is
  unaffected. Tests: preflight with a faked small filesystem (or
  a huge estimate).

### T134 — Fast path for a training re-run

- **Origin:** audit #6 T20
- **Covers:** A6-W14, A6-D20
- **Effort:** S
- **Status:** DONE in v0.15.0 (2026-11-14) — a fast path for a training re-run: the venv is kept, no ~2 GB re-download.
- **Problem:** The P9b dry-run probe — same packages, same
  versions, nothing to do — took 148 s: pip re-resolves the torch
  CPU index on every run, and the script prints nothing between
  the header and the torch version line (`--quiet`). A no-op
  second run looks like a hang.
- **Fix:** A6-D20 — check the imports first; if
  torch/transformers/peft/accelerate already import, print
  "training packages already installed" and exit 0 without
  re-resolving the index.
- **Done:** A second run of install-training.sh with everything
  installed exits in seconds with the plain message; a run with
  a missing package still installs it. Tests: second-run timing +
  message.

### T135 — Strengthen the PySide6 check

- **Origin:** audit #6 T21
- **Covers:** A6-W15, A6-D22
- **Effort:** S
- **Status:** DONE in v0.15.0 (2026-11-14) — the PySide6 check is strengthened (a throwaway QApplication proves the GUI can start).
- **Problem:** The fatal check is `import PySide6; from PySide6
  import QtWidgets` with stderr hidden (`2>/dev/null`), and its
  error message names only "a network connection, or ... disk
  space". An import succeeds even where creating a window would
  fail (e.g. missing system GL/EGL libs), and that failure's real
  cause would be swallowed. **Not reproduced in this sandbox** —
  `QApplication` creation worked without the extracted Qt libs
  (P1b) — so this is code reading only, stated as a weakness of
  the check's diagnosis, not as an observed failure.
- **Fix:** A6-D22 — create a throwaway `QApplication` offscreen
  instead of import-only, and surface the real stderr on failure
  so a missing system lib names itself.
- **Done:** The install check creates a `QApplication` offscreen;
  a missing system lib fails the check with the real error named.
  Tests: check passes in the sandbox; failure path names the lib
  (fake a missing lib).

### T136 — Make the success message reflect reality

- **Origin:** audit #6 T15
- **Covers:** A6-U2, A6-U3, A6-U4, A6-U8, A6-D18
- **Effort:** S
- **Status:** DONE in v0.15.0 (2026-11-14) — the success message reflects reality: the installer verifies the install works before saying so.
- **Problem:** "double-click Stella on the desktop. No terminal
  needed." prints even when the desktop copy was skipped (A6-U3:
  `cp ... "$HOME/Desktop/Stella.desktop" 2>/dev/null || true` —
  probed P1: scratch HOME with no `Desktop` dir → no copy, no
  message), and the whole success block prints even though the
  menu icon is broken (A6-W1). The message describes the intended
  install, not the one that landed (A6-U4). And the final check runs
  `import stella; print(stella.__version__)`, so the install
  output contains a lone `0.2` line between "Installing Stella
  from ..." and the success message — a version number with no
  label, looking like stray output (A6-U8). The `stella`-on-PATH
  claim (A6-U2) is conditional — the README half is T64; this task
  is the message half.
- **Fix:** A6-D18 — claim the desktop icon only if the copy landed;
  claim `stella` only if `~/.local/bin` is on PATH (or say to
  open a new terminal); label the version line (`Stella 0.2`).
- **Done:** With no `~/Desktop`, the success message does not
  claim a desktop icon; with `~/.local/bin` off PATH, it says to
  open a new terminal; the version line is labeled. Tests:
  install into a HOME with no Desktop dir; PATH-off case.

### T137 — Add `uninstall.sh` + a removal section in the README

- **Origin:** audit #6 T17
- **Covers:** A6-G1, A6-D11
- **Effort:** M
- **Status:** DONE in v0.15.0 (2026-11-14) — uninstall.sh + a removal section in the README; uninstall removes everything but never touches ~/.stella data without asking.
- **Problem:** No `uninstall.sh`, no removal instructions anywhere
  (grep: zero mentions outside one test comment). Removing Stella
  means hand-deleting the folder,
  `~/.local/share/applications/stella.desktop`,
  `~/Desktop/Stella.desktop`, `~/.local/bin/stella`, and deciding
  about `~/.stella` — and nothing tells the user the list.
- **Fix:** A6-D11 — remove launcher, desktop copy, symlink, venv;
  ask about `~/.stella` data (never delete it silently). Document
  the removal in the README (with T64).
- **Done:** `bash uninstall.sh` removes the launcher, desktop
  copy, symlink, and venv, and asks about `~/.stella` before
  touching it; the README documents removal. Tests: uninstall
  after install leaves no artifacts (except `~/.stella` when
  kept).

### T138 — Install icons into the hicolor theme + render small sizes

- **Origin:** audit #6 T18
- **Covers:** A6-G4, A6-U6, A6-D15
- **Effort:** M
- **Status:** DONE in v0.15.0 (2026-11-14) — icons installed into the hicolor theme (9 sizes) with small sizes rendered.
- **Problem:** The icon is referenced by absolute path from the
  install dir instead of installed into
  `~/.local/share/icons/hicolor/`. A theme install (copies, not
  references) would survive a folder move for the icon, and is
  where size variants belong (A6-G4). And `assets/` holds only
  64/128/256/512 + `stella.png` (256) — no 16/32/48 px files. The
  desktop environment scales the 256 down, and the eyeball probe
  (P10) shows the star stays legible at 16 px — so this is polish,
  not a defect — but a purpose-rendered small set would be crisper
  in panels and trays (A6-U6).
- **Fix:** A6-D15 — copy the PNGs (and 16/22/24/32/48 renders from
  `render_icon.py`) into `~/.local/share/icons/hicolor/`. Builds
  on T14 — the hicolor install consumes the rendered sizes.
- **Done:** The icon files land in the hicolor theme at the
  standard sizes; moving the install folder leaves the menu icon
  intact. Tests: theme files present after install;
  move-then-check-icon.

### T139 — Keep an install receipt

- **Origin:** audit #6 T19
- **Covers:** A6-G5, A6-D21
- **Effort:** S
- **Status:** DONE in v0.15.0 (2026-11-14) — an install receipt records a complete install (a never-installed folder gets its launch artifacts fixed but no receipt).
- **Problem:** Nothing records what an install did —
  PySide6/torch versions, where the artifacts went, when it ran.
  When something breaks later, there is no record to send Arlo.
  (The BNB debug-log-layer direction covers this class of gap for
  project builds generally; here it is just a missing artifact.)
- **Fix:** A6-D21 — versions, paths, and timestamp in the tree
  (and/or `~/.stella/`), so a broken install can be reported with
  facts. The receipt records a complete install (T63), not a failed
  one. (The record-them side of A6-D10 — T130 pins, this task
  records.)
- **Done:** After an install, a receipt file names the
  PySide6/torch versions, the artifact paths, and the install
  time; a failed install writes no receipt (or marks it failed).
  Tests: receipt contents after install.

### T140 — Document an upgrade path

- **Origin:** audit #6 T22
- **Covers:** A6-G6, A6-D24
- **Effort:** S
- **Status:** DONE in v0.15.0 (2026-11-14) — the README documents the upgrade path (unzip over the folder, bash install.sh; profiles untouched).
- **Problem:** v0.1 → v0.2 means unzipping a new folder and
  installing from scratch. Re-installing over the *same* folder
  is idempotent (P3), but a new folder leaves the old install
  orphaned — old venv (~259 MB), old launcher repointed only if
  the user runs the new `install.sh` — and nothing documents the
  upgrade steps or cleans up the old copy.
- **Fix:** A6-D24 — "Unzip the new version, run its `install.sh`,
  delete the old folder" — or make install.sh detect and offer to
  remove a previous install's venv.
- **Done:** The README documents the upgrade steps; following
  them leaves one working install and no orphaned venv. Tests:
  doc review; upgrade-path walkthrough in a scratch HOME.

### T141 — Corrupt-block tests for every reader

- **Origin:** audit #7 T13
- **Covers:** A7-G5, A7-D11
- **Effort:** S
- **Status:** DONE in v0.17.0 (2026-11-14) — corrupt-block tests pin T37's reader for every reader (no reader fixes needed; save heals the block to the default).
- **Problem:** The suite tests valid modes, a bad mode string, and
  the round-trip — but no test covers `null`, missing-key, or
  wrong-type metamorph in `project.json` or a manifest. All three
  crashes in audit #7 (A7-W2, A7-W3, A7-W4) live in untested
  paths, and A7-W5's re-confirmation shows the one tested corrupt
  case (bad mode string in the manifest, `test_export.py:56-59`)
  does not cover the wrong-*type* case next to it.
- **Fix:** D11 — `null`, missing-key, and wrong-type metamorph in
  `project.json` and in manifests, exercised against the CLI list,
  the GUI list + detail fill + save, export, and verify. Pins
  T37's reader. After T37, T38, and T39 (the defensive reader
  first, then the tests that pin it).
- **Done:** One test per corrupt variant per reader; all pass.
  Tests: this task IS the tests.

### T142 — Tests for the risky CLI paths

- **Origin:** audit #5 T15
- **Covers:** A5-G7, A5-D17
- **Effort:** S
- **Problem:** The 14 tests in `test_cli.py` cover happy paths and
  a few clean error paths. Nothing tests: the Ctrl+C pause (T4 —
  the crash shipped untested), `--steps` 0/negative/rounding
  (T56), a corrupt home or a nameless manifest (T3, T5), export to
  a file destination or a bad import manifest (T5, T1), `--quant`
  validation (T27), resume on a trained project (T25), or the
  exit-code/stderr contract for unknown commands. The riskiest
  paths are exactly the untested ones.
- **Fix:** D17 — cover what this audit found untested: a subprocess
  Ctrl+C-pause test against a stubbed or tiny training loop, `--steps`
  0/negative/rounding, corrupt home and nameless manifest,
  file-destination export and bad-manifest import, `--quant`
  validation, resume on a trained project, and the exit-code/stderr
  contract for unknown commands. After the fixes they pin (T4, T5,
  T25, T27, T56 first).
- **Done:** One test per risky path; all pass. Tests: this task IS
  the tests.
- **Status:** DONE in v0.10.0 (2026-11-13) — tests for the risky CLI paths: unknown/no command (exit 2 + usage), --steps 0/negative, --quant BOGUS, corrupt-home lists, resume-on-trained announcement, --force plumbing, converter-warning print, file-destination export, bad-manifest import, nameless manifest. (The Ctrl+C-pause test landed in v0.9.0.)

### T143 — Record the mode in training artifacts

- **Origin:** audit #7 T11
- **Covers:** A7-G3, A7-D5
- **Effort:** S
- **Status:** DONE in v0.17.0 (2026-11-14) — the stored mode string is recorded in training_summary.json + adapter config; no reading picked.
- **Problem:** Adapter, checkpoints, `train_log.jsonl`, and
  `training_summary.json` never record the mode (scanned clean,
  audit #7 P8). After a run, nothing in the artifacts says which
  mode the project was in when it trained — so when the codec
  lands, old adapters cannot be told apart by mode, and a future
  "was this adapter compressed?" question has no answer in the
  artifacts.
- **Fix:** D5 — write the project's mode into
  `training_summary.json` (and the adapter config) at train time,
  starting with the next build — before the codec exists. Cheap,
  and it means provenance is already there when the codec needs
  it. Alongside T72 (provenance records what the codec does). T4 before T108 (the
graceful pause first, then the force-quit on top of it) and T142
(the pause test pins the fix); T56 and T27 before T142 (the --steps
and --quant tests pin their fixes); T5 before T172 (the --verbose
flag exposes the traceback the catch-all hides); T87 before T161
(the CLI commands exist before the GUI mirrors them).
- **Done:** A training run's summary and adapter config name the
  mode the project was in. Tests: mode recorded in artifacts.

### T144 — Mode-version story before the first codec ships

- **Origin:** audit #7 T12
- **Covers:** A7-G4, A7-D12
- **Effort:** S
- **Problem:** `METAMORPH_MODES` is a closed tuple, and
  `verify_export` rejects any mode outside it (`export.py:141-143`).
  Adding a mode later — or a codec version, which is what a real
  codec needs — has no migration path: old Stella would reject new
  packages outright, and `verify_export` never checks
  `stella_version` at all (A3-W5, T40), so there is no version gate
  for a future mode to ride on.
- **Fix:** D12 — carry a codec version in the manifest when the
  codec lands, and make `verify_export` check `stella_version`
  (T40) so old Stella can refuse — cleanly, with a message — a
  package whose mode it does not understand, instead of crashing
  or silently misreading it. Rides T40's version gate; lands with
  the first codec release (T72).
- **Done:** A package with an unknown mode or codec version is
  refused with a readable message, not a crash. Tests:
  unknown-mode refusal, version-gate refusal.

---

### T145 — The finish moment

- **Origin:** audit #9 R16
- **Covers:** A9-G7
- **Effort:** S
- **Library:** 008 Delight done right, 002 Spring physics
- **Status:** DONE in v0.14.0 (2026-11-14) — the finish moment: a 250 ms gold glow when a job completes; reduced motion hides the card outright.
- **Problem:** When a job ends, nothing marks the finish: a log line and a status-bar message, and the screen goes quiet.
- **Fix:** A brief one-shot moment when a job completes: a gold glow on the job card plus a short summary line, under 300 ms, never looping, respecting the reduced-motion preset.
- **Done:** A finished job shows the moment once, then rests.

### T146 — Loading states, never a dead screen

- **Origin:** audit #9 R17
- **Covers:** A9-G8
- **Effort:** S
- **Library:** 011 Skeleton screens
- **Status:** DONE in v0.14.0 (2026-11-14) — loading skeletons (shimmer placeholders) instead of a dead screen while content loads.
- **Problem:** The model list populates silently; with Ollama slow or down the user sees an empty combo and a note, with no "looking" state in between.
- **Fix:** Skeleton rows in the model list while Ollama answers, paired with the real numbers when they arrive; the Ollama status refresh shows it is working.
- **Done:** With Ollama slow, the picker shows skeleton rows, not an empty combo.

### T147 — Reduced-motion and larger-text presets

- **Origin:** audit #9 R18
- **Covers:** A9-G9
- **Effort:** S
- **Library:** 015 Accessibility presets
- **Status:** DONE in v0.14.0 (2026-11-14) — reduced-motion and larger-text presets in Settings; reduced motion covers the dip, the morph, and the finish moment (no spring animation exists in the app, so there is nothing else to disable).
- **Problem:** No accessibility preset exists, and the redesign adds motion (R14, R16, R20) that needs an off switch.
- **Fix:** One Settings section with two presets, in plain words: reduced motion and larger text. Reduced motion disables the dip, spring, morph, and finish moment but keeps every state change.
- **Done:** With reduced motion on, no animation runs and everything still works.

### T148 — Before/after preview before export

- **Origin:** audit #9 R19
- **Covers:** A9-G13
- **Effort:** M
- **Library:** 017 See it before you commit
- **Extends:** T94 (surface the probe in the window), T96 (val loss in run summary and window).
- **Status:** DONE in v0.16.0 (2026-11-14) — export shows the before/after preview before committing (reuses ProbeResultsDialog in export_mode).
- **Problem:** Nothing shows what a fine-tune changed before the user commits to a GGUF export; the probe reports numbers in a dialog.
- **Fix:** Before export, show a side-by-side from the probe: the base model's reply next to the fine-tuned model's reply to the same prompts, so the user sees what changed before committing.
- **Done:** Export offers the preview; the user can export or go back.

### T149 — The job picker becomes the job

- **Origin:** audit #9 R20
- **Covers:** A9-U2 (part)
- **Effort:** S
- **Library:** 009 Shape morphing
- **Status:** DONE in v0.14.0 (2026-11-14) — the job tile morphs into the running job (350 ms, interruptible, instant swap under reduced motion).
- **Problem:** Picking a job and running it are two disconnected moments; the user picks in one place and the job appears in another.
- **Fix:** The picked job tile morphs into the running-job card, under 400 ms, interruptible. The reduced-motion fallback is an instant swap.
- **Done:** Picking a job visibly becomes the running card.

## P3 — polish, display, and scale

### T150 — Checkpoint management: resume, delete, disk usage

- **Origin:** audit #2 T18 + audit #4 T22 (checkpoint part; merged — one fix); extended by the repo-audit verdict (R30)
- **Covers:** A2-W15, A2-G3; A4-G3, A4-D21 (checkpoint part); R30
- **Effort:** M
- **Problem:** `checkpoints/` is created empty and nothing in v0.1 lists, names, or manages it — no list, resume picker, or disk usage. v0.2 (Item 3) has now landed, and audit #4 verified what its Train panel does and does not do (A4-G3): the panel lists checkpoints (`step N loss x.xxxx` per row) but clicking one does nothing — no resume-from-checkpoint, no delete, no disk usage, no detail. The verification this task was waiting on is done; the missing parts are now concrete work. Audit #8 measured
  checkpoint sizes: a tiny checkpoint is 71,440 bytes with
  optimizer.pt 65% of it; an LFM3 rank-8 checkpoint is ≈ 81 MB —
  the disk-usage display this task adds is the only thing that
  shows a user how fast checkpoints eat the disk.
- **Fix:** Build the missing checkpoint actions in the Train panel: resume from a selected checkpoint, delete a checkpoint, disk usage in the list, and a detail view (step, loss, size, date). Add checkpoint pruning (R30): delete all but the newest N checkpoints (N chosen by the user, default keep-newest-3 or per Joshua), with the total size shown before and after. (Job progress and cancel for GGUF/probe jobs is the companion task T107 — the other half of A4-D21.)
- **Done:** The Train panel lists checkpoints with step, loss, size, and date; selecting one offers resume and delete; disk usage is shown. Pruning keeps the newest N and shows the space freed. Tests: resume-from-checkpoint, delete, disk usage display, pruning keeps newest N.

### T151 — Loss chart + run history

- **Origin:** repo-audit verdict (R29)
- **Covers:** R29
- **Effort:** M
- **Note:** Extended by T20 (Audit #9 R6). The loss chart is elevated to P0 there; this task keeps the run-history half.
- **Problem:** Training progress is a log of lines — there is no
  loss chart, and no history of past runs. The user cannot see
  whether the loss is falling smoothly or spiking, and cannot
  compare this run with the last one. train_log.jsonl already
  holds the per-step records; nothing reads them back as a
  picture.
- **Fix:** A loss chart in the Train panel (a simple line chart
  from train_log.jsonl — Qt Charts or a lightweight custom paint,
  no new heavy dependency) plus a run-history list per project
  (each run: date, steps, final loss, settings snapshot). The
  chart updates live during a run.
- **Done:** A finished run shows its loss curve; the history lists
  past runs with their final losses; the chart updates during a
  live run. Tests: chart renders from a fake log, history lists
  two runs.

### T152 — "Loading base model" feedback: the window sits silent for minutes on a cold run

- **Origin:** audit #8 T28
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

### T153 — Size/time warning on the GGUF export button

- **Origin:** audit #8 T27
- **Covers:** A8-U5
- **Effort:** S
- **Problem:** A 1.7B export merges ~3.4 GB, converts, and
  quantizes — minutes of disk churn. The button offers no
  estimate up front and the job has no progress signal
  (`JobWorker` has log + finished only). The user commits to a
  multi-GB, multi-minute job blind. Overlaps T85 (dry-run
  estimate) and T107 (job progress); the export-specific
  half is the up-front warning on the button itself.
- **Fix:** Show the estimate on (or beside) the export button
  before the user commits — merged size, output size, rough
  time — reusing the dry-run estimator when T85 lands.
- **Done:** The export button shows what the export will cost
  (size + rough time) before it starts. Tests: estimate shown,
  matches the dry-run numbers.

### T154 — An Advanced settings section

- **Origin:** audit #8 T29
- **Covers:** A8-G5, A8-G6, A8-D18
- **Effort:** M
- **Status:** SUPERSEDED by T16 (Audit #9 R2) — the brief puts settings under the hood; do not build. Kept in the list, marked, so the coverage map still accounts for its findings.
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
  with the same ranges the engine validates (T6). No more
  hand-editing JSON to reach half the settings.
- **Done:** Every training setting is reachable from the window;
  the Advanced block's ranges match the engine's validation.
  Tests: each setting settable + saved, ranges enforced.

### T155 — Stable val sets via content-hash split

- **Origin:** audit #8 T24
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

### T156 — Train every assistant turn, not just the last

- **Origin:** audit #8 T25
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

### T157 — Accept the "tool" role in messages rows

- **Origin:** audit #8 T31
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
  from the results themselves. Pairs with T156 (multi-turn
  training): a tool trace is a multi-turn conversation.
- **Done:** A messages row with a `tool` turn validates and
  trains (tool content masked, assistant turns trained). Tests:
  tool-role row validates, masking correct.

### T158 — Dataset-size awareness: don't load the whole file into RAM

- **Origin:** audit #8 T30
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

### T159 — Don't double-save / double-emit the final checkpoint

- **Origin:** audit #8 T26
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

### T160 — Notes placement + settings tooltips

- **Origin:** audit #2 T16 + audit #4 T13 (settings-tooltips part; merged — one fix)
- **Covers:** A2-U2, A2-U7; A4-U7, A4-D16 (settings-tooltips part)
- **Effort:** S
- **Problem:** Two detail-panel polish flaws. (A2-U2) The Notes editor
  sits under Save project at the bottom of a scrolling panel; in the
  1100x680 window only the "Notes" header peeks out (visible in the
  v0.1 screenshot). The running log — the field a user touches most
  during a fine-tune — needs a scroll on every visit. (A2-U7) The
  metamorph combo has the GUI's only tooltip; rank, learning rate,
  epochs, batch, and seq len have no explanation of what they do or
  what sane values look like. Audit #4 re-verified this (A4-U7): exactly one widget in the entire window has a tooltip — the metamorph combo. Rank, learning rate, epochs, batch, seq len, the dataset field, and every button have no explanation.
- **Fix:** Reposition Notes so it is visible without scrolling in
  the default 1100x680 window (e.g. move it above the settings form,
  or give the project section its own visible notes area — decide in
  implementation, verified by screenshot). Add a tooltip to every
  settings field explaining what it does and its sane range. (Coordinate with T44, which moves the Train panel above the fold — both tasks reshape the same detail panel, so the layout change should solve Notes and Train placement in one pass.)
- **Done:** A screenshot at 1100x680 shows the Notes editor without
  scrolling; every settings field has a tooltip naming its purpose
  and sane values. Tests: tooltip text present on each settings
  field.

### T161 — GUI parity for the CLI-only options

- **Origin:** audit #5 T17
- **Covers:** A5-G6, A5-D16
- **Effort:** M
- **Problem:** Verified by reading the GUI: `--steps`, `--resume`,
  `--dataset`/`--base` overrides, `--quant`, and
  `--from-checkpoint` have no GUI equivalent. A window user cannot
  do a proof run, resume a paused run, pick a quant, or export
  from a checkpoint — the window's Train panel has Start/Pause/
  Resume buttons but no step cap, and its GGUF/probe actions take
  no options. The parity gap runs both directions (the CLI side is
  T87; this is the other way).
- **Fix:** D16 — add the CLI-only options to the window where they
  fit: a step cap and a resume action in the Train panel, a quant
  choice and a checkpoint picker on the GGUF action — or, if the
  window deliberately stays simple, document that these are
  CLI-only so a window user knows where to go. (The checkpoint
  picker rides T150's checkpoint actions.)
- **Done:** A window user can set a step cap, resume a run, pick a
  quant, and export from a checkpoint — or the window says plainly
  where to go (the CLI) for each. Tests: GUI tests for each option
  or the documented pointer.

### T162 — Single-instance guard

- **Origin:** audit #4 T24
- **Covers:** A4-G7, A4-D23
- **Effort:** S
- **Problem:** `main()` (`gui.py:924`) starts a window with no
  lock file or single-application check. Two Stella processes
  could open the same home and write the same manifests over each
  other.
- **Fix:** A4-D23 — a lock file (or `QtSingleApplication`-style
  check) so a second launch raises the running window instead of
  opening a second writer on the same home.
- **Done:** Launching Stella twice raises the first window; no
  second writer on the home. Tests: second-launch detection
  (subprocess).
- **Status:** DONE in v0.9.0 (2026-11-13) — single-instance guard was already implemented (gui.py QLocalServer); pinned by the subprocess test that starts a first instance and proves a second one cannot take the socket.

### T163 — Health badge per profile row

- **Origin:** audit #1 T13 + audit #4 T23 (health part; merged — one fix)
- **Covers:** A1-W11, A1-U6, A1-D1; A4-G6, A4-D22 (health part)
- **Effort:** S
- **Note:** Extended by T78 (Audit #9 R11).
- **Depends on:** T43 (cached model list)
- **Problem:** Nothing shows whether a profile's tag is actually
  installed. A tag removed from Ollama (`ollama rm`) leaves a
  profile pointing at a missing model with no sign — it looks
  exactly as healthy as every other row until training fails. All
  rows look equally healthy: a profile pointing at a missing model,
  a profile with no tag at all, and a good profile are visually
  identical (A1-U6). Audit #4 confirmed the window face (A4-G6): a profile pointing at a missing model, a profile with no tag, and a good profile are visually identical rows.
- **Fix:** Using the cached model list from T43, show a health badge
  on each row: installed ✓, missing ✗, Ollama down ?. A profile
  pointing at a removed model should look broken at a glance. A
  profile with no tag shows a distinct "no tag" state.
- **Done:** With Ollama up: installed tags show ✓, a removed tag
  shows ✗, a tag-less profile shows "no tag". With Ollama down: all
  rows show ?. Badges update on Refresh (T43). Tests: badge states
  against a fake server, Ollama-down state.

### T164 — Richer project rows

- **Origin:** audit #2 T15
- **Covers:** A2-W14, A2-D14
- **Effort:** S
- **Note:** Extended by T78 (Audit #9 R11).
- **Depends on:** T53 (status must be real before rows show it)
- **Problem:** Rows show display name + metamorph mode only: no
  status, no method, no rank, no dataset. Two projects with the same
  display name and mode are indistinguishable in the list (their
  slugs differ but are never shown).
- **Fix:** Show method + rank in each row (status in the row comes
  from T53). When two projects in the same profile share a display
  name, show the slug as a disambiguator.
- **Done:** Rows show method and rank alongside the status from T53;
  two same-named projects in one profile are distinguishable by
  their slugs. Tests: row text contains method/rank, slug shown on
  collision only.

### T165 — Show what the profile points at (model metadata in the detail panel)

- **Origin:** audit #1 T14
- **Covers:** A1-G3, A1-D9; A1-G5 (last-used); A1-W12 (project count, created/updated display)
- **Effort:** M
- **Problem:** A profile knows only a tag string. No size, quant,
  context length, or capabilities (vision? tools?) are recorded or
  shown, though Ollama's `/api/show` provides them. The list row
  shows no project count, and `created`/`updated` are recorded but
  never displayed (A1-W12). There is no last-used date or activity of
  any kind (A1-G5).
- **Fix:** Fetch model metadata from a cached `/api/show` (same cache
  discipline as T43 — never on the UI thread, never per click) and
  show size, quant, context length, and capabilities in the detail
  panel. Show the project count in the list row and in the detail
  panel, the created/updated dates, and a last-used date — record
  last-used when a profile is selected for training or a project
  under it is trained (define the trigger in the implementation and
  document it).
- **Done:** The detail panel shows size, quant, context, and
  capabilities for an installed tag (from a fake `/api/show` in
  tests), a project count, created/updated dates, and a last-used
  date that updates after a training run. List rows show the project
  count. With Ollama down, metadata shows as unavailable, not as
  blank or wrong. Tests: metadata display from fake `/api/show`,
  project count, last-used update, Ollama-down display.

### T166 — Profile-level notes

- **Origin:** audit #1 T15
- **Covers:** A1-W12 (profile notes)
- **Effort:** S
- **Problem:** Projects have `notes.md`, profiles do not. There is
  nowhere to write why a profile exists, what it is for, or what was
  learned about its base.
- **Fix:** Add `notes.md` per profile (same pattern as project
  notes: `read_notes`/`write_notes` on the Store) with an editor in
  the detail panel and a Save path through the existing Save profile
  flow. Include profile notes in profile export (T86). Profile notes
  get the same backup treatment as project notes (T119).
- **Done:** Write notes in the detail panel, save, reopen: the notes
  persist. Notes survive rename. Profile export includes them.
  Tests: notes round-trip, notes survive rename.

### T167 — README wording + export/import UI polish

- **Origin:** audit #3 T20
- **Covers:** A3-W15, A3-U3, A3-U6
- **Effort:** S
- **Problem:** Three polish flaws. (A3-W15) `README.md:43-44`: "a
  finished fine-tune exports as a usable package (manifest,
  config, weights, checkpoints)". v0.1 exports no weights — the
  package's own `weights/README.txt` says so honestly, but the top
  README lists weights as package content and calls the result
  "usable". A package with no weights is a recipe plus
  checkpoints, not a usable fine-tune. (A3-U3) Both buttons are
  always enabled (probed). Export with no selection warns *after*
  the click ("Pick a project to export.") instead of disabling
  the button until a project is selected. (A3-U6) The export dialog
  never shows the package name. The user picks a parent folder;
  the `<project>-stella-export` name is revealed only in the
  success dialog. On collision the warning shows the full path
  but offers no overwrite or rename (overwrite itself is T117).
- **Fix:** Fix the README claim (weights arrive with T41; until
  then the README says recipe + checkpoints). Disable Export
  until a project is selected (Import needs no selection and stays
  enabled). Show the package name in the export dialog before the
  user picks the folder (or in the picker title).
- **Done:** The README no longer claims weights in a v0.1 package;
  Export is disabled with no project selected; the export dialog
  shows the package name before the folder is picked. Tests:
  button enabled-state, dialog shows the name.

### T168 — Double-click does the obvious thing

- **Origin:** audit #4 T25
- **Covers:** A4-U9, A4-D24
- **Effort:** S
- **Problem:** Neither list responds to a double-click: no
  double-click to rename, no double-click to open, no
  double-click on a checkpoint to see it. Every action is a
  button click away, and the most obvious gesture does nothing.
- **Fix:** A4-D24 — rename on a list double-click; checkpoint
  detail on a checkpoint double-click.
- **Done:** Double-clicking a profile or project row opens
  rename; double-clicking a checkpoint shows its detail. Tests:
  double-click handlers fire.

### T169 — Menu bar (File/Edit/View/Help)

- **Origin:** repo-audit verdict (R22, menu-bar part)
- **Covers:** R22 (menu-bar part; shortcuts part → T127)
- **Effort:** M
- **Status:** SUPERSEDED by T19 (Audit #9 R5) — the real menu bar replaces the Menu button. Kept in the list, marked, so the coverage map still accounts for its findings.
- **Problem:** The window has no menu bar — every action is a
  button, and there is no File/Edit/View/Help surface for the
  actions a desktop program is expected to expose (new
  profile/project, import/export, preferences, about).
  (Keyboard shortcuts are T127's chrome pass; this task is the
  menu bar itself.)
- **Fix:** Add a menu bar with the actions the window already has
  (File: New profile/project, Import, Export, Quit; Edit: Rename,
  Delete; View: refresh; Help: About Stella + the docs link),
  wired to the same handlers as the buttons. Shortcuts from T127
  appear in the menus.
- **Done:** The menu bar exposes the window's actions; each menu
  item does the same thing as its button; Help shows the version.
  Tests: menu actions fire the same handlers.

### T170 — Settings-only export (share a recipe)

- **Origin:** audit #2 T17 + audit #3 T17 (merged — one recipe export)
- **Covers:** A2-G6; A3-G2
- **Effort:** S
- **Depends on:** T40 (package format defines the recipe kind)
- **Problem:** Export is the whole package; there is no way to
  share a recipe (dataset + settings) without weights and
  checkpoints. Audit #3 confirmed the gap (G2): whole package or
  nothing — no way to share a dataset + settings recipe without
  checkpoints.
- **Fix:** Add a recipe export using the recipe package kind from
  T40 (per audit #3's D1 format decision — versioned format,
  named kinds, version check): a small package holding the dataset
  reference, settings, metamorph mode + notes, and project notes —
  no weights, no checkpoints. Importing a recipe creates a new
  project with those values; if the dataset path does not exist on
  the importing machine, warn at import (don't block — the dataset
  may live elsewhere). The format decision is settled, so this
  task builds on T40 rather than waiting on the audit.
- **Done:** Export a recipe, import it into a fresh home: the
  project appears with settings, dataset ref, and metamorph mode
  intact, and no weights or checkpoints. A recipe pointing at a
  missing dataset warns at import. Tests: recipe round-trip,
  missing-dataset warning.

### T171 — Single-file package option

- **Origin:** audit #3 T16; extended by the repo-audit verdict (R33)
- **Covers:** A3-G4, A3-D13; R33
- **Effort:** M
- **Problem:** A package is a folder; sharing means zipping by
  hand. No `.stella` zip (or tar) form that import can read. The
  verdict's idea list asks for the same thing (R33: zip export).
- **Fix:** Export to a `.stella` zip; import reads zips and
  folders alike. One file to email, one file to back up. The zip
  contains exactly the folder package (same manifest, same
  members).
- **Done:** Export to `.stella`, import the zip into a fresh home:
  identical result to a folder import. Tests: zip round-trip,
  folder import unchanged.

### T172 — Machine-readable and quiet output: --json, --quiet, --verbose

- **Origin:** audit #5 T16 (G5/D15 part)
- **Covers:** A5-G5, A5-D15
- **Effort:** M
- **Problem:** No `--json`, `--quiet`, or `--verbose` flag exists
  on any command. The tab-separated list output is close to
  parseable but not a format, and there is no way to get a
  structured result for scripting — or to silence the per-step
  progress lines on a long run, or to ask for the traceback when
  one is actually needed (T5's catch-all hides tracebacks by
  design).
- **Fix:** D15 (output half) — `--json` on the list/show/probe
  commands (structured results for scripting), `--quiet` to
  silence per-step progress on long runs, `--verbose` to print the
  full traceback behind T5's catch-all. (The commands half of D15
  — rename/delete/update/show/settings — is T87; the verify half
  is T105.)
- **Done:** `--json` prints valid JSON for lists and probe
  results; `--quiet` suppresses progress lines; `--verbose` prints
  the traceback a clean error hid. Tests: JSON parses, quiet
  suppresses, verbose shows.

### T173 — Adapter library for sharing bare adapters

- **Origin:** repo-audit verdict (R32)
- **Covers:** R32
- **Effort:** M
- **Problem:** There is no way to share a bare adapter (weights
  only, no project) — export is the whole project package (T41)
  or a recipe with no weights (T170). A user who wants to hand
  someone just the fine-tune has no package for it.
- **Fix:** An adapter export/import: a small package holding the
  adapter weights + a manifest (base, rank, dataset name,
  training summary) — importable into any project with the same
  base, or into a new project created around it. Builds on the
  package format (T40) and the weights round-trip (T41).
- **Done:** Export a bare adapter, import it into a fresh home:
  the adapter lands with its manifest and can be merged (GGUF
  export) or probed. Tests: adapter round-trip, import into a
  project with the same base.

### T174 — Per-role probe sets

- **Origin:** repo-audit verdict (R31)
- **Covers:** R31
- **Effort:** M
- **Problem:** The refusal probe is one fixed 12-prompt set for
  every profile — but a driver, a reviewer, and a tool-calling
  model need different refusal evidence. A role whose job is tool
  calls should be probed on tool-call refusals; a governing seat
  needs the full refusal battery.
- **Fix:** Probe sets per role (a JSON file per role in the tree,
  editable): the probe picks the set for the profile's role
  (canonical roles from T116), falling back to the default 12 when
  no set exists. The probe results record which set ran.
- **Done:** Probing a driver-profile runs the driver set; probing
  a role with no set runs the default 12; probe_results.json names
  the set used. Tests: role-set selection, fallback, set
  recorded.

### T175 — Show the mode in the Train panel

- **Origin:** audit #7 T16
- **Covers:** A7-U5, A7-D14
- **Effort:** S
- **Problem:** Training is where a user would expect the mode to
  act — and the Train panel is silent about it. A user who set
  `compress`, starts a run, and watches the log sees no note that
  compression does not apply to the run. The mode is visible in the
  detail panel and invisible where its effect would be expected, so
  the run's silence reads as "working."
- **Fix:** D14 — one line ("Training as `compress` — mode is a
  label in v0.2") until the codec lands, then the real per-mode
  behavior summary.
- **Done:** The Train panel names the mode and its current
  (non-)effect during a run. Tests: panel shows the mode line.
- **Status:** OVERTAKEN by the v0.8 metamorph UI removal — the control this task would have changed no longer exists (deliberate removal, pinned by tests). Re-scope only if the MetaMorphAi codec lands; the reading pick (morphing spirit vs compression codec) is still undecided.

### T176 — CLI help strings for `--metamorph`

- **Origin:** audit #7 T17
- **Covers:** A7-U6, A7-D15
- **Effort:** S
- **Problem:** `cli.py:248-250` declares the flag with `choices`
  but no `help`, so `stella create-project --help` shows the three
  words and no meaning (noted in A5's design list, line 687). With
  the tooltip (T71) as the only explanation anywhere, the CLI user
  gets even less.
- **Fix:** D15 (help half) — real `help=` text on `--metamorph`
  (what the modes mean, with the honest "label for now" note). The
  update half of D15 rides T87.
- **Done:** `stella create-project --help` explains the modes
  honestly. Tests: help output contains the mode meanings.
- **Status:** OVERTAKEN by the v0.8 metamorph UI removal — the control this task would have changed no longer exists (deliberate removal, pinned by tests). Re-scope only if the MetaMorphAi codec lands; the reading pick (morphing spirit vs compression codec) is still undecided.

### T177 — Validate the notes type at both write points

- **Origin:** audit #7 T15
- **Covers:** A7-W11, A7-D8, A7-D11
- **Effort:** S
- **Problem:** `create_project` (`model.py:314`) and
  `update_project` (`model.py:347-350`) validate the mode but never
  the notes: `notes: 123` and `notes: 456` are stored verbatim
  (probed, audit #7 P9). Nothing crashes today — the GUI never
  reads notes, and JSON round-trips an int fine — but the
  manifest's contract says notes is text, and a future notes UI
  (T114) reading an int into a text field will crash or render
  garbage.
- **Fix:** One `isinstance` check at both write points (D8, the
  shared reader's write-side half); tests ride the D11 suite
  (T141).
- **Done:** Non-string notes are rejected with a `StellaError` at
  create and update. Tests: int notes rejected at both points.

### T178 — Size/disk awareness on export

- **Origin:** audit #3 T19
- **Covers:** A3-W14
- **Effort:** S
- **Problem:** Export copies everything with no total size, no
  disk-space check, and no report of how big the package is. In
  v0.1 checkpoints are tiny, so this is unobservable — but v0.2
  checkpoints and weights will be large, and the copy already runs
  synchronously in the button handler (see A3-U4). The first
  GB-scale export will freeze the window with no warning and no
  progress.
- **Fix:** Report the package size before/after export (in the
  success dialog and the CLI output); check free disk space
  against the estimated package size before copying and
  refuse/warn when it will not fit. (Progress display itself is
  T106.)
- **Done:** Export reports the package size; exporting when disk
  space is short warns before copying. Tests: size reported,
  low-disk warning (fake a small filesystem or a huge estimate).

### T179 — Provenance

- **Origin:** audit #3 T18
- **Covers:** A3-G6
- **Effort:** S
- **Depends on:** T118 (exported_at stamp)
- **Problem:** No `exported_at`, no source machine, no record of
  what was exported where or imported from where. A package found
  on disk cannot say when it was made or from what.
- **Fix:** Build on T118's `exported_at` stamp: record the source
  machine (hostname) in the manifest, and keep a small
  import/export history (a log in the home: what was exported
  where, what was imported from where, when). Show provenance in
  the import preview (T58) when present.
- **Done:** An exported package names its source machine and
  export time; the home keeps an import/export log; the preview
  shows provenance. Tests: provenance fields present, history
  logged.

### T180 — Search, filter, and sort for the profile list

- **Origin:** audit #1 T16
- **Covers:** A1-W12 (search/filter/sort); A1-G6 (search/sort part)
- **Effort:** M
- **Problem:** No search, filter, or sort in the list. Fine at 11
  profiles, thin at 30+. No multi-select or bulk operations either
  (A1-G6 — bulk work is T181).
- **Fix:** Add a filter box above the profile list (matches display
  name, slug, role, and tag), a role filter, and sort options
  (name, role, recently used, project count). Filtering must keep
  the current selection when the selected profile still matches.
- **Done:** Typing in the filter narrows the list live; the role
  filter shows only that role; each sort order reorders correctly;
  selection survives filtering when the profile still matches.
  Tests: filter by text, filter by role, each sort order, selection
  preserved.

### T181 — Bulk operations (multi-select)

- **Origin:** audit #1 T17
- **Covers:** A1-G6 (bulk part)
- **Effort:** M
- **Problem:** No multi-select, no bulk operations — acceptable now,
  a wall later. Every profile action is one at a time.
- **Fix:** Multi-select in the profile list (Ctrl/Shift-click) with
  bulk actions: delete (to trash, T23 — one confirm naming all
  selected), export (T86, one package per profile or a bundle), and
  role change. Single-selection behavior must not change.
- **Done:** Select three profiles, bulk-delete: all three land in
  trash with one confirm naming them. Bulk-export produces one
  package per profile. Bulk role change updates all selected.
  Single-click selection and all single-profile actions still work
  exactly as before. Tests: multi-select delete/export/role change,
  single-selection unchanged.

### T182 — Per-profile environment management (full A1-G1)

- **Origin:** audit #1 T18
- **Covers:** A1-G1 (full)
- **Effort:** L
- **Depends on:** T115 (config/deps reachable)
- **Problem:** Profiles were specced as a clean environment per base
  (weights, config, processor/tokenizer, dependencies). Config/deps
  are dead fields (A1-W7 — first step is T115), there is no per-profile
  venv or dependency install, and no record of which Python packages
  a profile's training needs.
- **Fix:** Design, then build — scope needs Joshua's direction
  before implementation: per-profile venv vs. a shared training venv
  vs. a dependency record only. At minimum: each profile records the
  Python packages its training needs, and `install-training.sh` can
  install from that record. If per-profile venvs are chosen, add
  create/activate/remove per profile and a disk-usage readout (venv
  sizes add up fast on a 1 TB HDD shared with Ollama models).
- **Done:** Per the agreed scope: a profile's dependency record is
  visible and editable (via T115), and the training installer
  consumes it. If venvs are in scope: creating a profile's
  environment, using it for a training run, and removing it all work
  from the GUI, with disk usage shown. Tests per the agreed scope.

### T183 — Per-mode training defaults, after the mode definitions

- **Origin:** audit #7 T18
- **Covers:** A7-G6, A7-D13
- **Effort:** S
- **Problem:** Every mode gets identical `DEFAULT_SETTINGS`
  (`model.py:44-57`). A `compress` project might sensibly default
  to a lower rank; a `morph` project to variant-friendly settings.
  Today the mode cannot even express a preference.
- **Fix:** D13 — once T70 defines the modes, let `compress` suggest
  a lower rank and `morph` suggest variant-friendly settings —
  suggestions in the New Project form (T113), not silent overrides.
- **Done:** The New Project form suggests per-mode defaults;
  accepting or overriding both work. Tests: defaults suggested per
  mode.

### T184 — Replace the pull-weights one-liner

- **Origin:** audit #6 T24
- **Covers:** A6-U9, A6-D23
- **Effort:** S
- **Problem:** `install-training.sh` ends by printing
  `$DIR/.venv/bin/python -c "from huggingface_hub import
  snapshot_download; snapshot_download('LiquidAI/LFM3-1.7B')"` —
  a long line with nested quotes, for a user who hand-types
  commands from his phone screen. The alternative (let the first
  run download) is printed too, which softens it.
- **Fix:** A6-D23 — a `stella pull-weights <repo>` command, or a
  shorter hint — nothing the user has to hand-type with nested
  quotes.
- **Done:** The training installer ends with a short command (or
  none — the first run downloads); no nested-quote one-liner is
  printed. Tests: installer output contains no nested-quote line.

### T185 — Desktop-file polish

- **Origin:** audit #6 T23
- **Covers:** A6-U7, A6-D19
- **Effort:** S
- **Problem:** The generated entry has no `StartupNotify=true`
  (no launch feedback in the panel), no `Keywords` (no search
  terms in the menu), no `Version=1.0`. All optional; all absent.
- **Fix:** A6-D19 — add `StartupNotify=true`, `Keywords`,
  `Version=1.0` to the generated desktop file.
- **Done:** The generated desktop file carries all three;
  desktop-file-validate is clean. Tests: fields present in the
  generated file.

### T186 — `--help` for the scripts

- **Origin:** audit #6 T25
- **Covers:** A6-G7, A6-D25
- **Effort:** S
- **Problem:** `bash install.sh --help` just installs; the
  scripts ignore arguments entirely. Minor — but the first thing
  a careful user types is `--help`.
- **Fix:** A6-D25 — print usage and exit 0 instead of ignoring
  arguments (install.sh, install-training.sh, run.sh).
- **Done:** Each script answers `--help` with usage and exits 0
  without installing or running anything. Tests: `--help` output
  + exit code per script.

### T187 — Small CLI polish: echo normalized names, friendly no-command hint

- **Origin:** audit #5 T18
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

### T188 — The token-level codec: a named later item

- **Origin:** audit #7 T19
- **Covers:** A7-D16
- **Effort:** L
- **Problem:** "The same meaning in fewer tokens" at train time —
  dataset tokenization, dedup, and compression-aware training — is
  the deep reading of the codec and the hardest part. It has no code
  behind it anywhere, and no design behind it either.
- **Fix:** D16 — name it as a later item with its own design pass;
  do not let T72's easy wins pretend it is done. After T70 (the
  definitions) and T72 (the easy wins prove the wiring).
- **Done:** A design doc for the token-level codec exists (or the
  codec itself, if the design pass is done in this task — decide at
  build time); T72's wins do not claim it. Tests: per the design
  pass.

---

---

### T189 — Remove the dead "full" method

- **Origin:** audit #9 R21
- **Covers:** A9-D1
- **Effort:** S
- **Library:** none
- **Supersedes:** T55 (remove/disable dead "full" method: remove it outright).
- **Problem:** The Method combo lists `lora` and `full` with `full` disabled: a visible option the user can never use.
- **Fix:** Drop `full` from the combo. (R2 deletes the settings form anyway; this is the cleanup if the form outlives R2.)
- **Done:** No `full` anywhere in the UI.

### T190 — One tagline everywhere

- **Origin:** audit #9 R22
- **Covers:** A9-D6
- **Effort:** S
- **Library:** none
- **Problem:** The window title and the header carry two different taglines.
- **Fix:** Window title and header use the same line.
- **Done:** One tagline in both places.

### T191 — Status bar shows the session once, in display names

- **Origin:** audit #9 R23
- **Covers:** A9-D4
- **Effort:** S
- **Library:** none
- **Problem:** The session title and the status bar state the same fact twice, in two different namings (display name vs slug).
- **Fix:** Drop the slug repeat from the status bar; the session title carries it.
- **Done:** The status bar no longer repeats the title.

### T192 — Tooltips where they earn their place

- **Origin:** audit #9 R24
- **Covers:** A9-D5
- **Effort:** S
- **Library:** none
- **Problem:** "Dream first" is the only tooltip in the app; nothing else explains itself on hover.
- **Fix:** Tooltips on tree rows (full text) and on any button whose label needs one more word.
- **Done:** Hovering a truncated row shows the full text.

### T193 — How to Use gets search and a link from the empty state

- **Origin:** audit #9 R25
- **Covers:** A9-D7
- **Effort:** S
- **Library:** none
- **Problem:** Thirteen topics in a plain list with no search, and the empty main window never points at the guide.
- **Fix:** A search box over the topics; the empty state links to Getting started.
- **Done:** Searching finds topics; the empty screen offers the guide.

### T194 — Chat window breathing room

- **Origin:** audit #9 R26
- **Covers:** A9-D8
- **Effort:** S
- **Library:** none
- **Problem:** The Chat window's two-line help text is squeezed at the bottom edge of the fixed 700x520 window.
- **Fix:** Resize the window or shorten the help line so the text has room.
- **Done:** The help line has room at the window's size.

## Coverage map (unified — audits #1–#9 + the repo-audit verdict)

Every finding ID from audits #1–#9 and the repo-audit
verdict, and the merged task(s) covering it. Nothing dropped. A1- =
audit #1 (Profiles), A2- = audit #2 (Projects), A3- = audit #3
(Export/Import), A4- = audit #4 (GUI), A5- = audit #5 (CLI), A6- =
audit #6 (Installer + icon), A7- = audit #7 (MetaMorphAi hooks),
A8- = audit #8 (Training engine), A9- = audit #9 (UI redesign),
R- = repo-audit verdict.

| Finding | Task(s) | Notes |
|---|---|---|
| A1-W1 — corrupt manifest vanishes silently | T3 | Damaged row + Repair + tests (profiles side) |
| A1-W2 — any string accepted as a tag | T12 | Soft validation, warn don't block |
| A1-W3 — tag/base_ref drift | T54 | One source of truth + sync rule |
| A1-W4 — every click re-fetches Ollama | T43 | Cache + off-thread fetch |
| A1-W5 — delete unrecoverable | T23 | Trash + export-first offer (profiles side) |
| A1-W6 — role is two controls, no canonical list | T116, T122 | T116 canonical list + seat warning; T122 single role combo |
| A1-W7 — config/deps dead fields | T115 | JSON editor; first step of A1-G1 |
| A1-W8 — processor undefined | T128 | Define it, label it, validate it |
| A1-W9 — no CLI for rename/delete/update | T87 | Four new profile CLI commands |
| A1-W10 — no clone profile | T121 | Clone action |
| A1-W11 — no health indicator | T163 | Health badges (needs T43) |
| A1-W12 — small missing pieces | T12, T165, T166, T180 | T12 duplicate-tag note; T165 project count + created/updated; T166 notes; T180 search/filter/sort |
| A1-U1 — long tags truncate, no tooltip | T122 | Tooltips on rows |
| A1-U2 — Enter does nothing in dialog | T11 | Default button (moved to the P0 dialog task) |
| A1-U3 — dialog is a QWidget, not QDialog | T11 | Real QDialog, centered (audit #4 corrected the description: not a separate window at all) |
| A1-U4 — tag combo re-fetch flicker | T43 | Cache removes the re-fetch |
| A1-U5 — role combo vs text field | T122 | Role combo in detail panel too |
| A1-U6 — all rows look equally healthy | T163 | Health badges |
| A1-G1 — no environment management | T115, T182 | T115 first step (reachable fields); T182 full build |
| A1-G2 — no seat mapping | T116 | Canonical roles + governing-seat warning |
| A1-G3 — no model metadata | T165 | Cached /api/show display |
| A1-G4 — profile cannot be exported alone | T86 | Profile export (format settled by audit #3, T40) |
| A1-G5 — no profile history | T165 | Last-used date |
| A1-G6 — no bulk operations | T180, T181 | T180 search/sort; T181 multi-select bulk |
| A1-D1 — health badge per row | T163 | |
| A1-D2 — soft tag validation | T12 | |
| A1-D3 — one source of truth for base | T54 | |
| A1-D4 — never silently vanish | T3 | |
| A1-D5 — cache model list, off UI thread | T43 | |
| A1-D6 — trash, not delete | T23 | |
| A1-D7 — clone profile | T121 | |
| A1-D8 — canonical roles, rename plan | T116 | |
| A1-D9 — show what the profile points at | T165 | |
| A1-D10 — small UI fixes | T11, T122 | T11 dialog part; T122 tooltip/role part |
| A1-D11 — CLI parity | T87 | |
| A1-D12 — config/deps reachable | T115 | |
| A2-W1 — unsaved edits discarded on switch | T2 | Dirty tracking / auto-save, both panels |
| A2-W2 — zero settings validation in the model | T6 | Ranges + types + unknown-key rejection |
| A2-W3 — inf/nan learning rates write invalid JSON | T7 | Numeric input + write-layer guard |
| A2-W4 — corrupt project manifest vanishes silently | T3 | Damaged row + Repair + tests (projects side) |
| A2-W5 — status is a dead letter | T53 | Lifecycle enum + UI |
| A2-W6 — dataset ref unvalidated text | T45 | Picker + existence + format checks |
| A2-W7 — "full" offered with no warning | T6, T55 | T6 method enum; T55 warning badge |
| A2-W8 — delete unrecoverable | T23 | Trash + export-first offer (projects side) |
| A2-W9 — no sane-range guidance on the extremes | T84 | RAM/time estimate at configure time |
| A2-W10 — three notes, one visible | T114 | Merge into one surface |
| A2-W11 — no CLI parity | T87 | Four new project CLI commands |
| A2-W12 — New Project is name-only | T113 | Real New Project form |
| A2-W13 — no clone / duplicate project | T112 | Clone action + templates |
| A2-W14 — project list shows almost nothing | T53, T164 | T53 status in row; T164 method/rank/slug |
| A2-W15 — checkpoints are a bare folder | T150 | Item 3 follow-up |
| A2-U1 — no dirty indicator, no save warning | T2 | Dirty tracking |
| A2-U2 — Notes sits below the fold | T160 | Reposition Notes |
| A2-U3 — learning rate bare text, no range hint | T7 | Numeric input + hint |
| A2-U4 — no status shown anywhere | T53 | Status in list + detail |
| A2-U5 — dataset is a bare text field | T45 | File picker |
| A2-U6 — "full" offered with no warning | T55 | Warning badge |
| A2-U7 — no tooltips on the settings fields | T160 | Tooltip per field |
| A2-G1 — no training lifecycle | T53 | Lifecycle enum + transitions |
| A2-G2 — no dataset management | T45 | Picker + validation + preview |
| A2-G3 — no checkpoint management | T150 | Item 3 follow-up |
| A2-G4 — no cost estimate | T84 | RAM/time estimate |
| A2-G5 — no project templates or presets | T112 | Templates, LFM3 preset first |
| A2-G6 — no settings-only export | T170 | Recipe export |
| A2-G7 — no notes history | T119 | Rotating notes backup |
| A2-D1 — dirty tracking, or auto-save on switch | T2 | |
| A2-D2 — validate settings in the model | T6 | |
| A2-D3 — learning rate as a real numeric input | T7 | |
| A2-D4 — damaged-row for corrupt manifests | T3 | |
| A2-D5 — a real status lifecycle, with UI | T53 | |
| A2-D6 — dataset picker + validation | T45 | |
| A2-D7 — method guidance | T55 | |
| A2-D8 — RAM/time estimate in the detail panel | T84 | |
| A2-D9 — clone project, and project templates | T112 | |
| A2-D10 — trash-on-delete | T23 | |
| A2-D11 — notes backup | T119 | |
| A2-D12 — merge the three notes into one surface | T114 | |
| A2-D13 — CLI parity | T87 | |
| A2-D14 — richer project rows | T164 | |
| A3-W1 — import not atomic, orphan profile | T1 | Atomic import / rollback |
| A3-W2 — manifest field types never validated | T1 | Strict schema validation |
| A3-W3 — config.json required but never read | T60 | One settings source of truth |
| A3-W4 — profile block silently discarded | T57 | Merge, don't discard |
| A3-W5 — stella_version written but never checked | T40 | Versioned format + version check |
| A3-W6 — weights/ never imported | T40, T41 | T40 format side (first-class member); T41 copy side |
| A3-W7 — no profile export | T86 | Profile export (merged with A1-G4) |
| A3-W8 — dataset never copied, absolute refs break | T59 | Dataset in the package decision |
| A3-W9 — no integrity checks | T104 | Checksums + sizes |
| A3-W10 — timestamps lost | T118 | Preserve created/updated + exported_at |
| A3-W11 — no overwrite/merge/rename on collision | T117 | Collision options |
| A3-W12 — import never checks the base exists | T61 | Base-health check on import |
| A3-W13 — import result names not normalized | T1 | Normalize slug once, at import start |
| A3-W14 — no size/disk awareness | T178 | Size report + disk check |
| A3-W15 — top README overclaims the export | T167 | README wording |
| A3-U1 — import success message overwritten | T50 | Confirmation survives the refresh |
| A3-U2 — no import preview or confirmation | T58 | Preview dialog |
| A3-U3 — export enabled with nothing to export | T167 | Disable until a project is selected |
| A3-U4 — no progress, no cancel | T106 | Background thread + progress + cancel |
| A3-U5 — failed import leaves GUI stale | T106 | Refresh on failure too |
| A3-U6 — export dialog never shows package name | T167 | Show the name before the folder pick |
| A3-U7 — no warning when profile already exists | T57, T58 | T57 merge choice; T58 preview warning |
| A3-G1 — no package format versioning policy | T40 | Versioned format |
| A3-G2 — no settings-only / recipe export | T170 | Recipe export (merged with A2-G6) |
| A3-G3 — no profile-level package kind | T40, T86 | T40 defines the kind; T86 builds it |
| A3-G4 — no single-file package | T171 | .stella zip |
| A3-G5 — no verify-only path | T105 | Verify command |
| A3-G6 — no provenance or history | T179 | Source machine + history (builds on T118) |
| A3-G7 — no dataset bundling option | T59 | Copy-in option + locate repair |
| A3-D1 — settle the package format | T40 |  |
| A3-D2 — validate the manifest schema strictly | T1 |  |
| A3-D3 — make import atomic | T1 |  |
| A3-D4 — merge, don't discard, the profile block | T57 |  |
| A3-D5 — round-trip weights/ | T41 |  |
| A3-D6 — one source of truth for settings | T60 |  |
| A3-D7 — make the dataset part of the package decision | T59 |  |
| A3-D8 — checksums + sizes in the manifest | T104 |  |
| A3-D9 — collision options | T117 |  |
| A3-D10 — import preview dialog | T58 |  |
| A3-D11 — preserve timestamps | T118 |  |
| A3-D12 — a verify command | T105 |  |
| A3-D13 — a single-file package option | T171 |  |
| A3-D14 — keep the import confirmation visible | T50 |  |
| A3-D15 — base-health check on import | T61 |  |
| A4-W1 — New Profile "dialog" is not a dialog at all | T11 | Real QDialog, P0; corrects A1-U3 |
| A4-W2 — Start training ignores a failed save | T8 | Gate Start on save success |
| A4-W3 — training log wiped when a run finishes | T13 | Keep the live log |
| A4-W4 — Enter in the delete confirm deletes | T9 | Delete defaults to No |
| A4-W5 — unsaved edits discarded on switch | T2 | Dirty tracking; second trigger: completion refresh |
| A4-W6 — bad settings abort the detail fill mid-way | T21 | Defensive fill, fall back to defaults |
| A4-W7 — every profile click re-fetches Ollama | T43 | Cache + off-thread fetch (re-verified) |
| A4-W8 — bad import crashes silently in the window | T1 | Window face: catch + refresh on failure |
| A4-W9 — no concurrency guards on jobs | T29 | One job at a time |
| A4-W10 — closing mid-job destroys the running thread | T36 | Close waits for all workers, no freeze |
| A4-W11 — progress and loss are stale per project | T47 | Reset per project |
| A4-W12 — switching projects mid-run mixes the panels | T47 | Pin the panel to the running project |
| A4-W13 — settings editable and saveable during a run | T46 | Lock the settings during a run |
| A4-W14 — panel shows settings with no project selected | T123 | Clear the whole panel |
| A4-W15 — requested splitter sizes not honored | T126 | Honest minimums |
| A4-W16 — both list panes can be dragged away | T126 | Non-collapsible panes |
| A4-W17 — no per-profile project memory | T125 | Remember the project per profile |
| A4-U1 — long rows truncate with no way to read them | T122 | Row tooltips |
| A4-U2 — Notes and Train panel below the fold | T44 | Train above the fold |
| A4-U3 — confirmations overwritten before they can be read | T50 | Status discipline; import + training-done |
| A4-U4 — buttons enabled with nothing to act on | T124 | Buttons follow the selection |
| A4-U5 — empty panes give no guidance | T124 | Empty-state hints |
| A4-U6 — no window icon | T127 | Window chrome pass |
| A4-U7 — one tooltip in the entire window | T160 | Settings tooltips |
| A4-U8 — missing-deps hint goes where the user cannot see it | T49 | Visible deps hint |
| A4-U9 — no double-click anywhere | T168 | Double-click actions |
| A4-G1 — no geometry or state persistence | T127 | QSettings persistence |
| A4-G2 — no keyboard shortcuts | T127 | Ctrl+S / Ctrl+N |
| A4-G3 — checkpoint list is display-only | T150 | Checkpoint actions (v0.2 verified) |
| A4-G4 — no progress or cancel for GGUF/probe jobs | T107 | Job progress + stop |
| A4-G5 — no status display anywhere | T53 | Status in row + detail (window face) |
| A4-G6 — no health indicator | T163 | Health badges (window face) |
| A4-G7 — no single-instance guard | T162 | Lock file / single-application check |
| A4-D1 — make New Profile a real QDialog | T11 | |
| A4-D2 — gate Start and sample-dataset on save success | T8 | |
| A4-D3 — keep the live training log | T13 | |
| A4-D4 — delete confirms default to No | T9 | |
| A4-D5 — dirty tracking, or auto-save on switch | T2 | |
| A4-D6 — fill the detail panel defensively | T21 | |
| A4-D7 — cache the model list; fetch off the UI thread | T43 | |
| A4-D8 — handle import failure in the window | T1 | |
| A4-D9 — one job at a time | T29 | |
| A4-D10 — close waits for every worker, without freezing | T36 | |
| A4-D11 — reset progress/loss per project; pin the panel | T47 | |
| A4-D12 — lock the settings during a run | T46 | |
| A4-D13 — clear the whole panel with no selection | T123 | |
| A4-D14 — give the splitter honest minimums | T126 | |
| A4-D15 — remember the project per profile | T125 | |
| A4-D16 — tooltips where the text is cut or unclear | T122, T160 | T122 row tooltips; T160 settings tooltips |
| A4-D17 — put the Train panel above the fold | T44 | |
| A4-D18 — status discipline: confirm after the refresh | T50 | |
| A4-D19 — buttons follow the selection; panes explain | T124 | |
| A4-D20 — window chrome pass | T127 | |
| A4-D21 — checkpoint actions and job progress | T107, T150 | T107 job progress; T150 checkpoint actions |
| A4-D22 — show status and health | T53, T163 | T53 status; T163 health |
| A4-D23 — single-instance guard | T162 | |
| A4-D24 — double-click does the obvious thing | T168 | |
| A4-D25 — put the missing-deps hint where it can be seen | T49 | |
| R1 — import drops the trained adapter and probe results | T41 | Weights + probe_results round-trip; status corrected when weightless |
| R2 — probe loads the base model twice at once (~7 GB) | T10 | One model resident at a time (P0) |
| R3 — no Install Stella.desktop (README promises one) | T64 | Double-click installer; audit #6 folded in (W3/U1) |
| R4 — menu icon points at a missing assets/stella.png | T14 | Render PNGs at install; unquoted Icon=; never point at a missing file (P0) |
| R5 — all files 100644; clone install leaves scripts non-executable | T65 | Exec bits in the tree; audit #6 verified the zip's stored modes are correct |
| R6 — maternion typo, 6 places incl. live code | T129 | Correct to quaternions + spelling guard |
| R7 — "full" method is a dead option | T55 | Remove/disable; train.py never reads the setting |
| R8 — RAM guard loads the base before estimating | T28 | Estimate from metadata, no load |
| R9 — probe gate has no informational mode | T90 | Informational mode for non-governing profiles |
| R10 — torch.load(weights_only=False) on optimizer.pt | T22 | weights_only=True; pickle refused |
| R11 — --steps cap overshoots whole epochs | T56 | Real cap; same as audit #5 W3 (deduped with A5-W3) |
| R12 — GGUF export silently deletes previous output | T24 | Prompt/refuse/rename; --force for deliberate overwrite |
| R13 — no LICENSE / .gitignore / pinned deps / CI | T130 | License + ignore + pins + CI + repo metadata |
| R14 — pushed docs stale vs v0.2 | T131 | Push current docs; the "audit #3 has no task list" claim is wrong |
| R15 — long tags truncate in the 260 px pane | T122 | Row tooltips (re-verified) |
| R16 — project status invisible in the list | T53 | Status in the row (re-verified) |
| R17 — no geometry persistence | T127 | QSettings persistence (re-verified) |
| R18 — no window icon set in code | T127 | Window icon (re-verified) |
| R19 — Train panel below the fold | T44 | Train above the fold (re-verified) |
| R20 — the "full" option does nothing | T55 | Same fix as R7 |
| R21 — first profile/project auto-selected on launch | T52 | Nothing selected on launch (P1) |
| R22 — no menu bar or keyboard shortcuts | T127, T169 | T127 shortcuts; T169 menu bar |
| R23 — GGUF export and probe have no cancel or progress | T107 | Job progress + stop (re-verified) |
| R24 — delete dialogs don't say what's being destroyed | T120 | Dialog names the item + counts |
| R25 — notes have no visible save affordance | T2 | Notes modified marker + own save control |
| R26 — one-click Ollama create after GGUF export | T89 | Create-in-Ollama button |
| R27 — dataset health panel before training | T83 | Pre-train health check |
| R28 — dry-run estimate button (no model load) | T85 | RAM fit + steps + disk, metadata only |
| R29 — loss chart + run history | T151 | Chart from train_log.jsonl + history list |
| R30 — checkpoint pruning with a size readout | T150 | Prune to newest N, size shown |
| R31 — per-role probe sets | T174 | Probe set per role |
| R32 — adapter library for sharing bare adapters | T173 | Bare-adapter package |
| R33 — zip export | T171 | .stella zip (same as A3-G4) |
| A6-W1 — quoted `Icon=` breaks the menu icon on every install | T14 | Unquote Icon=, keep Exec quoted (P0) |
| A6-W2 — fresh-clone install silently ships a broken icon | T14 | Render PNGs at install when missing (P0) |
| A6-W3 — no double-click installer exists | T64 | Real Install-Stella.desktop |
| A6-W4 — failed install leaves a working-looking launcher + command | T63 | Atomic install |
| A6-W5 — `run.sh` with venv but no PySide6 is a raw traceback | T62 | Check PySide6, fail visibly |
| A6-W6 — `run_tests.sh` can't run on a bare checkout on Mint | T68 | Use the venv, never system pip |
| A6-W7 — moving the folder breaks launcher + command silently | T66 | Repair/doctor path |
| A6-W8 — install.sh pip lines lack `--timeout`/`--retries` | T67 | Same flags as the training installer |
| A6-W9 — every venv failure misdiagnosed as missing python3-venv | T42 | Distinguish causes |
| A6-W10 — venv-failure cleanup deletes whatever sits at `.venv` | T42 | Clean up only what you made |
| A6-W11 — pip failures surface as raw pip output | T132 | Wrap in a Stella error |
| A6-W12 — no disk-space check anywhere | T133 | Preflight before downloading |
| A6-W13 — no version pins | T130 | Pin PySide6 + training stack |
| A6-W14 — training re-run takes ~2.5 min with nothing to do | T134 | Fast path: check imports first |
| A6-W15 — PySide6 import check can't catch a broken GUI start | T135 | Create a throwaway QApplication |
| A6-U1 — README install paragraph promises things that don't exist | T64 | Fix the README install section |
| A6-U2 — "`stella` on PATH" is conditional, installer doesn't say so | T64, T136 | T64 README half; T136 message half |
| A6-U3 — Desktop copy silently skipped when `~/Desktop` missing | T136 | Claim only what landed |
| A6-U4 — success message claims things unconditionally | T136 | Message reflects reality |
| A6-U5 — the running window has no icon | T127 | setWindowIcon in gui.py main() |
| A6-U6 — no 16/32/48 px icon files shipped | T138 | Render small sizes into hicolor |
| A6-U7 — desktop-file polish missing | T185 | StartupNotify, Keywords, Version |
| A6-U8 — install log prints a bare "0.2" | T136 | Label the version line |
| A6-U9 — pull-weights hint is a long quoted one-liner to type | T184 | Shorter command, no nested quotes |
| A6-G1 — no uninstall | T137 | uninstall.sh + README section |
| A6-G2 — no installer tests | T69 | test_installer.py incl. GLib icon check |
| A6-G3 — no repair command | T66 | stella doctor / install.sh --repair |
| A6-G4 — no hicolor icon-theme install | T138 | Copies into ~/.local/share/icons/hicolor/ |
| A6-G5 — no install log or receipt | T139 | Versions, paths, timestamp |
| A6-G6 — no upgrade story | T140 | Documented upgrade path |
| A6-G7 — no `--help` / usage for the scripts | T186 | Usage + exit 0 |
| A6-D1 — unquote `Icon=`, keep `Exec` quoted | T14 | |
| A6-D2 — render the PNGs at install time when missing | T14 | |
| A6-D3 — ship a real double-click installer | T64 | |
| A6-D4 — make install atomic: check before writing artifacts | T63 | |
| A6-D5 — `run.sh`: check PySide6 before exec, fail visibly | T62 | |
| A6-D6 — add `--timeout 120 --retries 10` to install.sh | T67 | |
| A6-D7 — distinguish venv-failure causes; clean up only yours | T42 | |
| A6-D8 — wrap pip failures in a Stella error | T132 | |
| A6-D9 — disk-space preflight | T133 | |
| A6-D10 — pin versions, or record them | T130 | Pin side; record side is the receipt (T139) |
| A6-D11 — add `uninstall.sh` + removal docs | T137 | |
| A6-D12 — add installer tests, including the GLib icon check | T69 | |
| A6-D13 — add a repair/doctor path | T66 | |
| A6-D14 — set the window icon in `gui.py main()` | T127 | |
| A6-D15 — install icons into hicolor + render small sizes | T138 | |
| A6-D16 — fix the README install section | T64 | |
| A6-D17 — `run_tests.sh` must use the venv, never system pip | T68 | |
| A6-D18 — make the success message reflect reality | T136 | |
| A6-D19 — desktop-file polish | T185 | |
| A6-D20 — fast path for a training re-run | T134 | |
| A6-D21 — keep an install receipt | T139 | |
| A6-D22 — strengthen the PySide6 check | T135 | |
| A6-D23 — replace the pull-weights one-liner | T184 | |
| A6-D24 — document an upgrade path | T140 | |
| A6-D25 — `--help` for the scripts | T186 | |
| A7-W1 — the mode does nothing, for either reading | T70 | Define the modes (D1); the wiring is T73/T72/T188 |
| A7-W2 — export crashes on `metamorph: null`, leaves a partial package | T38 | Defensive reader + build README before creating the folder |
| A7-W3 — GUI Save crashes with KeyError on a missing metamorph key | T37 | `get_project` setdefaults the block; owns the shared reader |
| A7-W4 — GUI project list crashes on a string metamorph | T39 | Shared reader; degrade to a warning row |
| A7-W5 — `verify_export` crashes on a string metamorph | T1 | A3-W2 re-confirmed; line moved 128 → 141 |
| A7-W6 — `compress` package is 22 bytes BIGGER | T72 | Package compression (D3) |
| A7-W7 — `both` has no combined semantics | T70 | Defined by D1 |
| A7-W8 — `metamorph.notes` unreachable from GUI and CLI | T114 | A2-W10 re-confirmed; detail-panel field + CLI flag |
| A7-W9 — GUI New Project is name-only, no metamorph choice | T113 | A2-W12 re-confirmed |
| A7-W10 — stale "structure only in v0.1" comment | T70 | Updated in the D1 spec pass |
| A7-W11 — `notes` accepts any JSON type, unchecked | T177 | `isinstance` check at both write points |
| A7-U1 — tooltip promises behavior that does not exist | T71 | Honest words, one line |
| A7-U2 — project list presents the mode as if it mattered | T71 | Fair label once the tooltip is honest |
| A7-U3 — no metamorph-notes field in the detail panel | T114 | UI half of W8 |
| A7-U4 — no metamorph choice in New Project | T113 | UI half of W9 |
| A7-U5 — Train panel never mentions the mode | T175 | One line until the codec lands |
| A7-U6 — `--metamorph` has no help string | T176 | Real help text |
| A7-G1 — no morph implementation: no variants, no lineage | T73 | Spawn + parent record |
| A7-G2 — no compression codec anywhere in the pipeline | T72 | Quant wiring + package compression; token codec is T188 |
| A7-G3 — no mode provenance in training artifacts | T143 | Record the mode at train time |
| A7-G4 — no mode-version story | T144 | Codec version in the manifest; version check rides T40 |
| A7-G5 — no tests for corrupt metamorph states | T141 | Pins the defensive reader |
| A7-G6 — no per-mode defaults | T183 | After D1 (T70) |
| A7-G7 — CLI cannot change a mode after creation | T87 | update-project --metamorph flag |
| A7-D1 — define what each mode MEANS, in writing | T70 | The first task; gates the codec |
| A7-D2 — wire `compress` to the GGUF quant first | T72 | Cheapest real effect |
| A7-D3 — compress the export package when mode is `compress` | T72 | Import must accept both forms |
| A7-D4 — variant lineage for `morph` | T73 | Spawn + parent record |
| A7-D5 — record the mode in training artifacts now | T143 | Provenance before the codec needs it |
| A7-D6 — fix the tooltip now | T71 | One line; do not wait for the codec |
| A7-D7 — metamorph-notes field + CLI flag | T114 | Label it distinctly from notes.md |
| A7-D8 — one defensive reader, used everywhere | T37, T38, T39, T177, T1 | Built once in T37; T1 uses it at the boundary |
| A7-D9 — build the export README before creating the folder | T38 | No partial package on failure |
| A7-D10 — New Project form with dataset + metamorph | T113 | Restates A2-W12's fix |
| A7-D11 — corrupt-block tests for every reader | T141, T177 | Pins D8 |
| A7-D12 — mode-version story before the first codec ships | T144 | Version gate rides T40 |
| A7-D13 — per-mode training defaults, after D1 | T183 | Suggestions, not silent overrides |
| A7-D14 — show the mode in the Train panel | T175 | One line until the codec lands |
| A7-D15 — CLI help strings + a way to change mode | T87, T176 | Update rides T87; help text is T176 |
| A7-D16 — the token-level codec is a named later item | T188 | Deep codec, after the easy wins |
| A5-W1 — Ctrl+C pause crashes the run instead of pausing it | T4 | Signal handler must set the flag only (P0) |
| A5-W2 — `main()` catches only StellaError; everything else is a raw traceback | T5, T39, T1 | T5 catch-all + defensive reads (P0); T39 CLI metamorph instance; T1 import instances |
| A5-W3 — `--steps` is not a cap: 0 means "no cap", -1 means "one epoch", 2 runs 3 steps | T56 | R11 task; deduped, not duplicated |
| A5-W4 — re-training a trained project silently overwrites the adapter | T25 | Refuse or --force |
| A5-W5 — the train deps gate fires before cheap checks, masking the real error | T48 | Cheap checks first |
| A5-W6 — `export-gguf` checks llama.cpp AFTER the merge, and leaves the merged weights behind | T26 | Check first; clean up on failure |
| A5-W7 — `--quant` is never validated | T27 | choices list up front |
| A5-W8 — `projects` on a nonexistent profile exits 0, like an empty real profile | T88 | Existence check first |
| A5-W9 — one corrupt profile.json is silently skipped by `profiles` | T3 | A1-W1 re-verified on the CLI |
| A5-W10 — a bad import leaves an orphan profile behind | T1 | A3-W1 re-verified on the CLI |
| A5-W11 — no second-Ctrl+C force quit; Ctrl+C during the base download cannot interrupt it | T108 | Second Ctrl+C exits; download interruptible or announced |
| A5-W12 — a failed probe gate returns exit 1, the same as an error | T91 | Distinct exit code (3) |
| A5-W13 — `--resume` on a completed project silently extends the training | T25 | Announce the extension |
| A5-U1 — most flags have no help text, and no command shows examples | T51 | Help + examples (--metamorph text itself is T176) |
| A5-U2 — the docs disagree with the commands that exist | T51 | Docstring, README, wrapper, hint |
| A5-U3 — uppercase names are silently lowercased | T187 | Echo the stored name |
| A5-U4 — library chatter pollutes stderr on every heavy run | T110 | Filter warnings; fix the float() call |
| A5-U5 — a CLI error tells the user to use the GUI | T111 | Name the CLI fix |
| A5-U6 — a paused run's final summary reads like a completed run | T109 | Paused wording, not Trained |
| A5-U7 — resume prints a stale validation line for an epoch with no new steps | T109 | Skip the re-evaluated line |
| A5-U8 — long operations print nothing on stdout until they finish | T109 | A line per pass / per phase |
| A5-U9 — bare `stella` gives argparse's usage error, no friendly hint | T187 | Print the command list |
| A5-G1 — no rename, delete, or update commands for profiles or projects | T87 | Eight new commands (A1-W9/A2-W11) |
| A5-G2 — no way to inspect a profile or project from the CLI | T87 | show-profile/show-project + checkpoints |
| A5-G3 — no CLI way to set training settings | T87 | Settings flags on create/update |
| A5-G4 — no `verify` command, though the function exists | T105 | stella verify (A3-G5) |
| A5-G5 — no machine-readable or quiet output | T172 | --json/--quiet/--verbose |
| A5-G6 — the GUI lacks the CLI-only options (parity, the other way) | T161 | Step cap, resume, quant, checkpoint picker |
| A5-G7 — no test coverage for the risky CLI paths | T142 | Pins the W1/W3/W7/W13 fixes |
| A5-D1 — the SIGINT handler sets the flag and nothing else | T4 | |
| A5-D2 — catch-all in `main()`, plus defensive reads in the list commands | T5, T39 | T5 catch-all; T39 metamorph reader |
| A5-D3 — validate `--steps` and say what it really does | T56 | |
| A5-D4 — refuse or confirm re-training and resume-on-trained | T25 | |
| A5-D5 — reorder the train checks: cheap first, deps gate last | T48 | |
| A5-D6 — check llama.cpp first in `export-gguf`; clean up on failure | T26 | |
| A5-D7 — validate `--quant` up front | T27 | |
| A5-D8 — existence checks, corrupt warnings, atomic import | T88, T3, T1 | T88 existence; T3 corrupt warnings; T1 atomicity |
| A5-D9 — second Ctrl+C force-quits; make the download interruptible | T108 | |
| A5-D10 — a distinct exit code for a failed probe gate | T91 | |
| A5-D11 — help text for every flag, examples in every command, fix the drift | T51 | |
| A5-D12 — silence the library warnings | T110 | |
| A5-D13 — CLI-appropriate error text | T111 | |
| A5-D14 — progress for long phases; honest paused/resumed output | T109 | |
| A5-D15 — the missing commands: rename/delete/update, show, settings, verify, --json | T87, T105, T172 | Commands/show/settings T87; verify T105; output T172 |
| A5-D16 — GUI parity for the CLI-only options | T161 | |
| A5-D17 — tests for the risky paths | T142 | |
| A5-D18 — small polish: echo normalized names, friendly no-command hint | T187 |
| A8-W1 — no torch seeding: the same run twice gives a different adapter | T32 | |
| A8-W2 — resume diverges: torch RNG state isn't saved | T32 | |
| A8-W3 — datasets under 6 examples get no validation at all | T33 | |
| A8-W4 — `is_refusal` is brittle both ways: 6 of 10 crafted replies misjudged | T30 | |
| A8-W5 — the gate passes vacuously: empty results and a silent model pass | T30 | |
| A8-W6 — the probe doesn't use the chat template | T30 | |
| A8-W7 — no mutual exclusion between Train and the GGUF/probe jobs | T29 | A4-W9, re-probed with the train-vs-job hole |
| A8-W8 — bad settings crash the loop with raw tracebacks, or run silently wrong | T6 | A2-W2 at the loop's conversions |
| A8-W9 — HF load failures surface as raw tracebacks, not StellaError | T5 | A5-W2 at the model loader |
| A8-W10 — resume silently ignores changed settings | T98 | |
| A8-W11 — resume with a missing optimizer.pt silently restarts the optimizer | T98 | |
| A8-W12 — resume + --steps gives the nonsense error "already at step 4 of 3" | T56 | Adjacent to R11/A5-W3 |
| A8-W13 — a failed quantize leaves the multi-GB F16 intermediate on disk | T26 | F16 half of A5-W6 |
| A8-W14 — a non-executable llama-quantize passes discovery, then raw PermissionError | T102 | |
| A8-W15 — the printed `ollama create` command breaks on spaced paths | T101 | |
| A8-W16 — completions are never truncated: a long completion blows past max_seq_len | T99 | |
| A8-W17 — with a chat template, the completion never learns the turn terminator | T100 | |
| A8-W18 — the val set churns when the dataset grows | T155 | |
| A8-W19 — multi-turn conversations only train the final turn | T156 | |
| A8-W20 — the final checkpoint double-saves and double-emits | T159 | |
| A8-U1 — the CLI reports the RAM estimate as "RAM used" | T35 | |
| A8-U2 — no proof-run control in the window | T95 | |
| A8-U3 — the Train panel never shows the val loss in the summary line | T96 | |
| A8-U4 — the probe result has no home in the window | T94 | |
| A8-U5 — the GGUF export button gives no size/time warning | T153 | Overlaps T85/T89 |
| A8-U6 — no "loading base model" feedback | T152 | |
| A8-G1 — no target-module override | T34 | |
| A8-G2 — no merge RAM guard | T31 | |
| A8-G3 — probe_results.json carries no provenance | T92 | |
| A8-G4 — the prompt set has no hard-benign prompts | T93 | |
| A8-G5 — five of eleven training settings have no GUI or CLI surface | T154 | |
| A8-G6 — no LoRA hyperparameters beyond rank | T154 | |
| A8-G7 — no timeout on the converter/quantizer subprocesses | T103 | |
| A8-G8 — the run summary carries no val loss | T96 | Rides with U3 |
| A8-G9 — no dataset-size awareness: the whole file loads into RAM | T158 | |
| A8-G10 — the "tool" role is rejected | T157 | |
| A8-G11 — the LFM3 → GGUF conversion is unproven | T97 | |
| A8-D1 — seed everything: torch seed at run start + RNG state in checkpoints | T32 | |
| A8-D2 — refusal detection v2: first-sentence matching + an apology allowlist | T30 | |
| A8-D3 — probe through the chat template | T30 | |
| A8-D4 — minimum-val guarantee, or a loud warning | T33 | |
| A8-D5 — one job at a time, enforced in the engine, not just the GUI | T29 | |
| A8-D6 — validate settings once, at the top of train_project | T6 | |
| A8-D7 — wrap HF load failures in StellaError | T5 | |
| A8-D8 — resume contract: snapshot settings at pause, warn on drift | T98 | |
| A8-D9 — compose caps with resume: remaining-steps budget | T56 | |
| A8-D10 — clean up intermediates on failure | T26 | |
| A8-D11 — check executability at discovery; validate quant up front | T102 | Quant half is A5-W7 (T27) |
| A8-D12 — quote paths in the Modelfile and the printed command | T101 | |
| A8-D13 — bound completions to max_seq_len | T99 | |
| A8-D14 — end the completion with the template's turn terminator | T100 | |
| A8-D15 — stable val sets via content-hash split | T155 | |
| A8-D16 — probe provenance in the results file | T92 | |
| A8-D17 — surface the probe in the window | T94 | |
| A8-D18 — an Advanced settings section | T154 | |
| A9-W1 — New Profile picks the first model for the user | T18 | |
| A9-W2 — The Profile window contradicts itself about Base ref | T79 | |
| A9-W3 — Download model is enabled when there is no repo to download from | T79 | |
| A9-W4 — The empty-store guidance tells the user to pick something that does not exist | T17 | |
| A9-W5 — Four of nine menu actions are enabled with nothing selected and answer with a modal warning | T19 | |
| A9-U1 — Training settings are on screen in four places; the brief says the user never sees them | T16 | |
| A9-U2 — There is no "pick a job" surface | T15, T75, T149 | |
| A9-U3 — Sleep is below the fold at both sizes, including his own screen | T74 | |
| A9-U4 — Save project is below the fold in its own window, and half of Settings is hidden | T80 | |
| A9-U5 — Chat makes the user type a model tag by hand | T76 | |
| A9-U6 — Tree rows truncate long model names, with no tooltip anywhere to recover them | T78 | |
| A9-U7 — The main window at rest is a wall of empty grey boxes | T15 | |
| A9-U8 — No keyboard shortcuts, no visible focus ring | T82 | |
| A9-U9 — The menu is a button, not a menu bar | T19 | |
| A9-G1 — No graphs or charts anywhere | T20 | |
| A9-G2 — No visual identity of its own | T81 | |
| A9-G3 — No first-run onboarding | T17, T15 | |
| A9-G4 — No glanceable training status card | T20, T74 | |
| A9-G5 — No model-fit guidance at pick time | T18 | |
| A9-G6 — No per-profile project memory | T77 | |
| A9-G7 — No finish moment | T145 | |
| A9-G8 — No loading or skeleton states | T146 | |
| A9-G9 — No reduced-motion or accessibility preset | T147 | |
| A9-G10 — No collapsible headers in the panels | T80 | |
| A9-G11 — Chat shows no plan before it runs | T76 | |
| A9-G12 — No progress or cancel on GGUF export and the refusal probe | T74 | |
| A9-G13 — No before/after view of what a fine-tune changed | T148 | |
| A9-D1 — The dead "full" method is still listed in the combo | T189 | |
| A9-D2 — The download row is duplicated in two windows | T79 | |
| A9-D3 — Learning rate is a free-text field | T16 | |
| A9-D4 — The status bar repeats the session title in slug form | T191 | |
| A9-D5 — "Dream first" is the only tooltip in the app | T192 | |
| A9-D6 — Two taglines | T190 | |
| A9-D7 — How to Use has no search and no link from the empty state | T193 | |
| A9-D8 — The Chat window's help line is squeezed at the bottom edge | T194 | |

**Coverage check:** audit #1: 12 weaknesses + 6 UI flaws + 6 gaps +
12 design suggestions = 36 findings. Audit #2: 15 weaknesses + 7 UI
flaws + 7 gaps + 14 design suggestions = 43 findings. Audit #3: 15
weaknesses + 7 UI flaws + 7 gaps + 15 design suggestions = 44 findings.
Audit #4: 17 weaknesses + 9 UI flaws + 7 gaps + 25 design suggestions
= 58 findings. Audit #5: 13 weaknesses + 9 UI flaws + 7 gaps + 18
design suggestions = 47 findings. Audit #6: 15 weaknesses + 9 UI flaws + 7 gaps + 25
design suggestions = 56 findings. Audit #7: 11 weaknesses + 6 UI
flaws + 7 gaps + 16 design suggestions = 40 findings. Audit #8: 20 weaknesses + 6 UI
flaws + 11 gaps + 18 design suggestions = 55 findings. Audit #9: 5 weaknesses + 9 UI
flaws + 13 gaps + 8 design suggestions = 35 findings. Repo-audit
verdict: 14 weaknesses + 11 UI flaws + 8 ideas = 33 findings. Total
447 findings. All 447 appear in the map above, each with at least
one task. 194 tasks total: 20 P0 (T1–T20), 62 P1 (T21–T82), 67 P2
(T83–T149), 45 P3 (T150–T194).

**Dependency order (within the priority order above):** T6 before T7
(the model rules define the learning-rate range the GUI enforces);
T6 before T21's fallback defaults (the defensive fill must match the
model ranges); T1 before T40 (the version check is enforced in
`verify_export` alongside the schema validation) and T105 (the verify
command runs the full verification); T43 before T61 (the base-health
check uses the cached list) and T163 (badges need the cache); T40
before T41 (weights round-trip lands with the version check), T86
(profile export uses the profile kind), and T170 (recipe export uses
the recipe kind); T57 before T58 (the preview shows the merge
choice); T116 before T122 (the detail role combo shows the canonical
list); T23 before T87's deletes and T181's bulk delete (both delete
to trash); T115 before T182 (reachable fields before full environment
management); T86 before T181's bulk export (profile export must
exist first); T53 before T164 (status must be real before rows show
it); T45 before T59 (the dataset picker before the dataset handling
in the package); T104 before T105 (the verify command checks the
checksums); T118 before T179 (provenance builds on the `exported_at`
stamp); T29 before T36 (the close handler waits on the single job
slot) and T107 (the stop button acts on the single running job); T44
and T160 reshape the same detail panel — land them together or
coordinate the layout; T2 and T46 cover the same mid-run edits from
opposite sides (T46 locks the form so there is less to preserve; T2
preserves what was edited before the lock); T45's full validation
and T84's estimate depend on Item 3 (the validator engine and the
RAM-guard math) — the picker, the existence check, and the estimate
display can land first and be wired to Item 3 when it arrives; T150
no longer waits on v0.2 — it has landed, and audit #4 verified the
gaps, so the checkpoint actions are concrete work. T12 works
standalone with a direct fetch; T43's cache improves it later. T28 before T85 (the dry-run estimate uses the honest RAM-guard
math) and T84 (the detail-panel estimate reuses the same
estimator); T45 before T83 (the health panel builds on the
dataset validator); T41 before T173 (the adapter library builds on
the weights round-trip); T127 before T169 (the menu bar shows T127's
shortcuts); T23 before T24's overwrite-with-backup (the old output
goes to trash); T125 and T52 coexist (T52 is launch-only; T125
restores the project within a session). T14 before T69 (the
installer tests pin the icon fix), T66 (repair re-links a working
icon, not a broken one), and T138 (the hicolor install consumes the
rendered sizes); T63 before T139 (the receipt records a complete
install, not a failed one); T137 and T66 before the
README-documentation part of T64 (the install section documents
removal and repair). T70 before T73,
T72, T183, and T188 (the definitions gate the lineage, the
compression wiring, the per-mode defaults, and the token codec); T37
before T38, T39, and T177 (the shared reader first, then its
consumers); T141 after T37, T38, and T39 (the corrupt-block tests pin
the reader); T144 with the first codec release (T72) and after T40
(the version gate); T71 now (the tooltip fix is one line and
independent of everything); T143 alongside T72 (provenance records
what the codec does). T32 before T98 (the seeding fix and the
resume contract both touch the checkpoint format — land the RNG
state first, then the settings snapshot); T30 before T90 and T174
(the probe must be trustworthy before its informational mode and
per-role sets are built on it); T96 before T151 (the loss chart
shows the val loss the summary now carries); T6's model-validation half stands alone (T154, Advanced settings, is
superseded by Audit #9 R2 — the settings leave the screen entirely);
T28 before T31 (the merge guard reuses the training estimator);
T99 before trusting T28's bound (a completion longer than
max_seq_len breaks the estimate the guard relies on); T102 with
T26 and T27 (the three GGUF fail-fast fixes touch the same path —
land them together); T97 before the first real LFM3 export (the
pre-flight check must exist before the merge it guards).
