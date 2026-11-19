# STELLA v0.32.0 — Test Report

Report cards attach to a model's profile, and Stella reads them to
know what the model is good and weak at. OST cards are understood;
other sources' cards are stored, not understood. Plus one verified
bridge entry (Granite 4.1), disjoint from report cards.

## What was built

- New module `stella/report_cards.py`: attach (copy in, never link),
  list (newest first), remove, and parse OST cards. Per-file cap
  10 MB, refused in plain words. Storage:
  `profiles/<slug>/report-cards/`; no manifest, the directory
  listing is the list.
- OST parser handles five shapes, all found on disk first (see
  "OST format" below): per-template result files, a single
  per-model summary block, multi-model summaries keyed by slug,
  OST GUI reports (`{"generated", "models": [...]}`), and JSON
  lists of per-template results. Multi-model files pick the entry
  matching the profile's tag (case-insensitive); no match means
  not understood, never guessed. A bad file never raises.
- Strengths: score >= 80 is good at, <= 40 is not good at, in
  between is silence; speed is never a strength; unknown template
  ids are skipped, never guessed. Card evidence beats the
  built-in strengths table at display time; the table itself is
  unchanged. Newest card wins; removing it falls back at once.
  Source line: "From its OST report card, Nov 2026."
- Profile window (simple view): "Report cards" section after the
  strengths — list (name + month-year), one-line detail for the
  selected card, Add / Open / Remove. Cards are immediate store
  ops, not form edits. Remove confirms, defaulting to No.
- Export/import: profile export carries `report-cards/` (same
  pattern as sleep/ in project export); import restores cards
  only for a newly created profile — an existing profile keeps
  its own cards. Clone does NOT carry cards (same as notes).
- Bridge: `huihui_ai/granite4.1-abliterated:3b` maps to
  `ibm-granite/granite-4.1-3b-base` (verified on the Hub
  2026-11-18: config.json + 2 safetensors, transformers library,
  zero GGUF files). The mismatch guard now catches the LFM3 repo
  typed into a Granite profile. The reviewer and bonsai-2 stay
  unknown (unverified / no repo).

## OST format (found on disk, read-only)

- Per-template result file: `ost/results/<slug>/<system>/
  <YYYY-MM-DD-HHMMSS>-<template>.json` (OST v22 `save_run_file`).
  Fields: template, template_name, template_score, passed, total,
  capability, timestamp, model, model_slug, tasks, avg_decode_tok_s.
- Per-model summary JSON: dict keyed by model slug; each value has
  model, slug, templates_scored, overall_score, mean_decode_tok_s,
  templates (id -> name, capability, score, passed, total, ...).
- OST GUI report: `bench-results-<stamp>.json` with `models` as a
  LIST of per-model results.
- Fixtures use the real LFM3 numbers from
  `results-summary-3models.json` (overall 70.0, 15 templates:
  tool_calling/structured_output/instruction/grounded_qa/
  summarization/refusal 100, math 90, coding/knowledge 80,
  multi_turn/reasoning 60, code_repair/role_following 40,
  long_context/planning 0, speed score None).
- PDFs are STORED, not parsed — Stella has no PDF parser
  dependency. The JSON is the machine-readable truth.

## Suite (fresh unzip, 5 chunks, 2,093 tests)

- Chunk 00: 416 passed.
- Chunk 01: 365 passed, 8 skipped.
- Chunk 02a: 221 passed, 1 failed — test_job_card_morphs_from_
  button_rect, a load flake (passed 3/3 solo).
- Chunk 02b: 210 passed, 3 skipped, 7 failed — all installer
  exec-bit tests, an artifact of the verifier's first unzip
  (Python zipfile drops modes). Re-extracted with `unzip`
  (modes restored) and test_installer.py re-ran clean:
  61 passed, 3 skipped.
- Chunk 03: 397 passed, 23 skipped.
- Chunk 04: 408 passed, 33 skipped, 1 failed —
  test_cli_debug_report pinned the old version string
  ("DEBUG REPORT: stella 0.31.0"); a real stale pin missed in
  the version move. Fixed in place to 0.32.0 and re-verified.
- Totals: 2,017 passed, 67 skipped, 9 failed-and-explained
  above (1 load flake, 7 unzip artifacts, 1 stale pin fixed).

## Like the user (offscreen drive)

`drive_report_cards.py` drives the real Add button (picker
answered), the real Remove button (confirm answered Yes), and
screenshots each step. Checked by eye: the empty state reads
"No report cards yet." with Add enabled and Open/Remove greyed;
after adding the LFM3 card the strengths change to the card's
(good: answering from given text, following instructions, saying
no to bad requests, summing up, using tools, writing in a set
format, maths, knowledge questions, writing code; not good:
making plans, reading long documents, fixing code, staying in
character) with "From its OST report card, Nov 2026."; the
selected card reads "OST tested this model: overall 70 out of
100."; after removing, the strengths fall back to the table.
No jargon anywhere on screen.

## Defects found and fixed in place

- One real defect, in a test: `test_cli_debug_report`
  (test_v29.py) pinned the debug report header to the old
  version ("DEBUG REPORT: stella 0.31.0") — a stale pin missed
  when the version tests moved. Updated to 0.32.0, re-verified.
- Two environmental failures during verification, both
  diagnosed and re-verified green:
  1. `test_second_main_exits_zero_while_first_runs` failed 3/3
     solo: the workspace TMPDIR had been deleted mid-run, so
     Qt's tempPath pointed at a missing directory and
     QLocalServer.listen failed with "Name error" — the first
     instance ran without the single-instance guard. Recreated
     the TMPDIR; the test passed 3/3.
  2. Verify chunk 01 failed with 97 PermissionError errors: a
     system-wide EPERM write burst (AGENTS.md). Waited for a
     clear window (tempfile.mkdtemp probe loop) and re-ran.
  3. Seven installer exec-bit tests failed in chunk 02b: the
     verifier's first unzip used Python zipfile, which drops
     file modes. Re-extracted with `unzip`; test_installer.py
     re-ran clean (61 passed, 3 skipped).

## Still needs Joshua's real-PC verdict

- Attaching a real OST card from his PC (the fixtures are real
  format + real numbers, but the attach flow has only run
  offscreen in the sandbox).
- The Granite download: his Granite profile's stored LFM3 repo
  should now warn and offer the IBM base on "Get its weights".
- The LFM3 proof run itself (unchanged from v0.31.0).


# STELLA v0.31.0 — Test Report

Measured 2026-11-18 by the builder from a fresh unzip of the
release zip. Python 3.12.3, PySide6 offscreen Qt,
forge-v2-testenv; TMPDIR a sibling of the tree. Joshua's order
from his real-PC session the same day: the Profile window was
not child-simple ("I dont know what anybody this is"), and
nobody should assign roles by hand ("it shoukd be able to get
the accurate weights and know what the model is good at and
what it isnt good at"). The Profile window is now a simple view
(name, plain what-it-does, strengths in plain words, one
download button, projects) with everything technical behind one
closed Details flap; roles are derived from a curated strengths
table grounded only in the roster audit and OST's graded LFM3
card.

## Suite: 1991 passed, 67 skipped (2059 collected)

The single-process full run OOMs on this 6 GB VM, so the suite
ran in 4 chunks from the fresh unzip: non-GUI (1616 passed, 67
skipped, 12:32) + test_gui.py in 3 chunks (130 + 122 + 123
passed). Counts reconcile exactly to the 2059 collected (2031
in v0.30.0 + 28 net new: test_v31.py has 32 tests including the
2 version pins moved from test_v30.py, test_v30.py lost those
2, test_gui.py lost 1 net (two role-combo tests replaced by
one has-no-role-combo test), test_v22.py lost 1 (the
multi-select role change test, replaced by a comment)).

One failure appeared in the run and is a load flake, not a
regression: tests/test_gui.py::
test_install_training_button_disabled_while_job_runs failed in
the second GUI chunk while the box sat at load ~12 with another
thread's suite running. It passes 3/3 solo (20.6s, 9.3s, 8.7s),
and v0.31.0 touches nothing under it (the install-training
button logic is unchanged).

The first verification run of this version showed 15 failures,
all understood and fixed before this run: 8 installer tests +
1 uninstall test were the Python-zipfile extraction artifact
(proven again this version: zipfile.extract writes 664 while
the `unzip` CLI restores the stored 755 — the zip itself was
correct; the v0.30.0 report records the same lesson); 2 were
real defects in the new How to Use text (em-dashes in two topic
strings, and the Profiles topic had dropped the "Used for
dreaming" / "The refusal probe does not use it" sentences) —
both fixed in place; 3 were version pins (the two v0.30.0
version tests moved to test_v31.py per the per-version
convention, the debug-report header pin updated to 0.31.0).
The fixed areas were re-run green in the build copy (187
passed, 3 skipped) before the zip was rebuilt and the full
suite re-run from the fresh unzip.

The 67 skips are the v0.30.0 skips unchanged (65 training-stack
skips — no torch in forge-v2-testenv — plus the 2 tool skips
for desktop-file-validate / shellcheck, neither installed in
the sandbox).

Environment notes: verification ran under heavy load from
another thread's suite (load 12-24 during the first run, down
to ~1 by the last GUI chunk). No EPERM burst hit this run. Zip
extraction for verification used the `unzip` CLI, never
Python's zipfile.extractall (see above).

The `malloc_consolidate(): unaligned fastbin chunk detected`
post-run line did not reproduce in any chunk — exit code 0
throughout.

## CLI smoke: green

`stella-cli --version` reports 0.31.0. `stella-cli pc-info`
runs and measures the box. The CLI `--role` flags are kept
(power-user path; 15+ CLI tests pin them) but create-profile
derives the role when `--role` is omitted, and update
re-derives on a tag change unless `--role` is given explicitly.

## GUI drive: green (verify like the user)

drive script offscreen (stella-v31-drive.py): the window opens,
4 screenshots saved and eyeballed. The simple view for LFM3
reads "It can write and answer, and use tools." / "Size on
disk: 1.0 GB." / "Good at: using tools, answering fast, reading
long documents." / "Not good at: long multi-step jobs, it
still refuses some ordinary work." / "Training files are not
downloaded yet." with one "Download the training files" button
and the projects list. Granite (the model from Joshua's
screenshot) reads the same way. An unknown model reads
honestly: "Stella does not know what this model can do yet." /
"Not measured yet." / "No projects yet." Details opens with
Role "No role yet", the governing-seat combo, and the rest of
the technical fields working. One defect found by eyeballing
the screenshots and fixed in place: the size line left a blank
gap for unknown models (an empty label still takes a line), so
it is now hidden when the size is not known.

## Sweeps

Em-dash: the suite's visible-text pins all pass; howto.py
carries 0 em-dashes; the em-dashes in strengths.py are
docstring/comment only (excluded by the AST sweep, which
passed). "Base ref": zero occurrences in stella/ outside the
base_ref code identifier (unchanged from v0.30.0). No manual
role editing path remains in the window: role_combo,
custom_role, and _bulk_change_role have zero matches in
gui.py. Secrets grep: clean. Zip modes: 0o100755 for scripts,
0o100644 for plain files, with file-type bits throughout;
testzip clean, no self-inclusion.

## Merge notes

No merge: v0.31.0 was built in one isolated copy and merged
into the live tree by rsync (diff-clean, no --delete). The
bridge map is untouched (no new repos, no guessing unknown
tags). The strengths table and the bridge map are different
tables for different purposes: Granite has strengths (from the
audit) but no bridge repo, and the mismatch guard still cannot
catch a Granite profile carrying the wrong repo — Joshua's
Granite profile still has LiquidAI/LFM3-1.7B typed into it
and needs a hand fix in the profile window. Report-card upload
is NOT in this version (planned v0.32.0).

---

# STELLA v0.30.0 — Test Report

Measured 2026-11-18 by the builder from a fresh unzip of the
release zip. Python 3.12.3, PySide6 offscreen Qt,
forge-v2-testenv; TMPDIR a sibling of the tree. Two real-PC
defects in one version: the bridge fix (no-repo walls offer
the Hugging Face repo) and the wheel fix (the %2B torch
filename + the install-training.sh fallback).

## Suite: 1963 passed, 67 skipped (2031 collected)

The single-process full run OOMs on this 6 GB VM, so the suite
ran in 12 pieces from the fresh unzip: 9 non-GUI pieces (1586
passed, 67 skipped) + test_gui.py in 3 chunks (130 + 124 + 123
passed). Counts reconcile exactly to the 2031 collected (1997
in v0.29.0 + 34 net new: 24 in tests/test_v30.py including the
2 version pins moved from test_v29.py, 10 in
tests/test_wheel_fetch.py, 2 in tests/test_installer.py).

One failure appeared in the run and is a load flake, not a
regression: tests/test_installer.py::
test_uninstall_leaves_a_newer_install_alone was killed by
pytest-timeout (>300s) while waiting on subprocess I/O, in a
piece that ran 9:12 under heavy load. It passes 3/3 solo in
about 2.5s each, and v0.30.0 touches nothing under it
(uninstall.sh and the uninstall logic are unchanged). The two
CLI failures from the pre-wheel-fix verification run
(test_cli_train_ctrl_c_pauses, the requant JSON-sweep timeout)
did not reproduce in this run: test_cli.py passed 251/251.

The 67 skips are the v0.29.0 skips unchanged (65 training-stack
skips — no torch in forge-v2-testenv — plus the 2 tool skips
for desktop-file-validate / shellcheck, neither installed in
the sandbox).

Environment notes: verification ran through the system-wide
EPERM write storm (2026-11-18, recorded in AGENTS.md) — file
writes intermittently fail with "Operation not permitted" in
bursts, which makes pytest runs redirected to a file produce
empty logs and exit 120. The suite ran with output captured
into shell variables through pipes (never redirected to a
file), in 12 small pieces so each finishes inside a calm
window, with storm-aware retries (a piece is valid only when
its output carries a pytest summary line and no storm
keywords). Every piece was valid on attempt 1 in the final
run. A runtime restart killed the first chain mid-GUI0; the
three GUI chunks were re-run cleanly afterwards (all valid on
attempt 1). Zip extraction for verification used the `unzip`
CLI, never Python's zipfile.extractall (which ignores stored
Unix modes and made 8 installer tests fail in an earlier
attempt).

The `malloc_consolidate(): unaligned fastbin chunk detected`
post-run line did not reproduce in any piece — exit code 0
throughout.

## CLI smoke: green

`stella-cli --version` reports 0.30.0. `stella-cli bridge
lfm3:1.7b` suggests LiquidAI/LFM3-1.7B. `stella-cli distill
--help` shows --timeout (default 300). `stella-cli doctor`
runs and names its problems (the sandbox has no install
receipt, as in v0.29.0).

## GUI drive: green

drive_gui.py offscreen: the window opens, the session is set,
5 screenshots saved with real sizes. The profile window shows
the renamed "Hugging Face repo" label with its plain-words
help line; the main window shows "No Hugging Face repo set."
in plain words (no "Base ref" anywhere on screen). The
profile window's repo field shows the example repo as a
placeholder when the stored value is a tag, not a repo id
(pre-existing T79 behavior, unchanged).

## Sweeps

Em-dash: the suite's visible-text pins all pass; howto.py
carries 0 em-dashes. "Base ref": zero occurrences in stella/,
README.md, data/, and the shell scripts (code identifiers keep
the base_ref name; historical developer docs under docs/ keep
the wording). Secrets grep: clean. Zip modes: 0o100755 for
scripts, 0o100644 for plain files, with file-type bits
throughout; repair_launcher.py ships 0o100755 (its exec bit is
set in the tree), the other launcher .py files 0o100644
(invoked via python3, no exec bit needed). testzip clean, no
self-inclusion.

## The wheel fix, verified against the real failure

The defect was a filename: pip's report spells torch's version
with %2B, the fetch saved the wheel under that encoded name,
and pip's --find-links could not parse it as a version. The
new tests fetch a wheel whose URL contains %2B and assert the
saved name has `+` and parses as a valid wheel name; a
pre-placed encoded twin with a matching hash is renamed into
place with no re-download (the fake server's log stays empty);
a twin with a bad hash is left alone and the wheel is fetched
fresh; and the script tests prove the --no-index failure falls
through to the direct download (and that the download-failed
error only shows when both paths fail). The traversal guard
still holds: five hostile URLs with encoded slashes/dots are
all refused.

## Merge notes

No merge: v0.30.0 was built in one isolated copy and merged
into the live tree by rsync (diff-clean, no --delete). The
bridge map is untouched (no new repos, no guessing unknown
tags). Known gap, by design: the mismatch guard cannot catch
a Granite profile carrying the wrong repo, because Granite is
not in the bridge map — Joshua's Granite profile still has
LiquidAI/LFM3-1.7B typed into it and needs a hand fix in the
profile window.

---

# STELLA v0.29.0 — Test Report

Measured 2026-11-18 by the coordinator from a fresh unzip of the
release zip. Python 3.12.3, PySide6 offscreen Qt,
forge-v2-testenv; TMPDIR a sibling of the tree.

## Suite: 1930 passed, 67 skipped (1997 collected)

The single-process full run OOMs on this 6 GB VM, so the suite ran
in 4 chunks from the fresh unzip: non-GUI 1553 passed + 67 skipped,
test_gui.py in 3 chunks (130 + 124 + 123 passed). Counts reconcile
exactly to the 1997 collected (1925 in v0.28.0 + 72 new across the
two halves: 40 in tests/test_v29.py from the chat/CLI half, 24
from the installer half, plus parametrised CLI cases for the five
new commands). Zero failures in the completed runs.

The 67 skips are the v0.28.0 training-stack skips (65 — no torch in
forge-v2-testenv) plus 2 new ones: the tests that run
desktop-file-validate / shellcheck when the tools are installed
(R120/R121), and neither tool is installed in the sandbox.

Environment note: the first GUI chunk 01/02 runs timed out at the
40-minute cap with load-flake failures (the box had ~400 MB free
with another thread's Ollama test running). Clean verbose re-runs
passed 124 and 123 with zero failures, no code change between the
runs — the timeouts were load, not a merge defect (same pattern as
the v0.24.0 verification flakes).

Slowest single test: 11.68s (test_stylesheet_is_stellas_own_look),
measured by builder B; the pytest-timeout value in pytest.ini
(R128) is 300s — ~25x with room for a loaded machine. The timeout
mechanism was verified with deliberately hung tests (plain and
GUI): both failed by timeout in ~5s.

The `malloc_consolidate(): unaligned fastbin chunk detected`
post-run line from the v0.3 report did NOT reproduce in any chunk
run — no teardown abort, exit code 0 throughout.

## CLI smoke: green

`stella-cli --version` reports 0.29.0. All five new commands
(mark-ready, notes, probe-results, howto, debug-report) are
present with help; `howto` lists its topics with Getting started
first.

## GUI drive: green

drive_gui.py offscreen: the window opens, the session is set,
5 screenshots saved. The main window screenshot is clean; the
session summary shows the R113 disclosure line live ("Training
settings are changed from the terminal: stella update-project
lfm3-tool tool-calls --seed 7").

## Sweeps

Em-dash: the suite's visible-text pins all pass
(test_no_em_dash_in_visible_text, test_no_em_dash_in_any_topic,
test_no_em_dash_in_tool_text, test_no_em_dash_in_provider_text,
test_chat_window_has_no_em_dash); howto.py carries 0 em-dashes.
Secrets grep: clean. Shellcheck 0.10.0 over *.sh + stella-cli:
clean; desktop-file-validate 0.27 over all four .desktop files
including the new Repair Stella entry: clean (both run from
fetched tools — neither is installed in the sandbox). Zip modes:
0o100755/0o100644 with file-type bits throughout; the launcher
.py files ship 0o100644 as in v0.28.0 (invoked via python3, no
exec bit needed).

## Merge notes

No merge-interaction defects: the two halves touched disjoint
files except README.md (hand-merged: A's five new commands +
B's pre-install icon note and Repair Stella lead). One fix in
place at merge: a pre-existing em-dash in install.sh's --help
echo (user-visible output) replaced with a hyphen; no test
pinned the string. R113's disclosure uses --seed 7 as the
example flag: the task's --rank 16 example violates three
pinned T16 tests that forbid rank/epochs wording on screen,
and relaxing them would re-decide T16.

---

# STELLA v0.28.0 — Test Report

Verified 2026-11-18 by the coordinator from a FRESH UNZIP of
stella-v0.28.zip (1,202,323 bytes, SHA-256
3430a9d2f3bb87a09cb6944a14cd007d08db7072faac3421c5056b95b9ec54f3),
not from the builders' claims. Python 3.12.3, PySide6 offscreen Qt,
forge-v2-testenv; TMPDIR under the workspace (STELLA has no
QFileSystemWatcher, so this is safe).

## Suite: 1856 passed, 65 skipped (1925 collected)

The single-process full run OOMs on this 6 GB VM, so the suite ran
in 4 chunks from the same fresh unzip: non-GUI 1479 passed + 65
skipped + 4 failed, test_gui.py in 3 chunks (130 + 124 + 123
passed, zero failures). Counts reconcile exactly to the 1925
collected. All 4 failures were the coordinator's own merge errors,
fixed in place and re-verified green from a second fresh unzip of
the rebuilt zip (103 passed: all 101 test_v28.py + both gitignore
tests):

- test_dropping_jsonl_on_pick_dataset_sets_it and
  test_dropping_jsonl_on_project_dataset_field: NameError — the
  merged test_v28.py was missing B's `shutil` import (the drop
  tests copy the sample dataset). One import added.
- test_gitignore_covers_receipt_venv_and_pycache and
  test_gitignore_covers_providers_json: the merge repo's scratch
  .gitignore (3 lines) leaked into the zip instead of the
  product .gitignore. The product file was restored in the merge
  tree before the rebuild; the zip now carries it (verified by
  diff). The push manifest excludes .gitignore as usual, and the
  live tree always had the product file.
- No load flakes hit in this run.

## CLI smoke: green

`stella-cli --version` reports 0.28.0; --help lists the new
`delete-checkpoint` and `prune-checkpoints` commands.

## GUI drive: green

drive_gui.py offscreen: window opens, job buttons Train / Sleep /
Make smaller / Teach a small model, Go, Export GGUF, Run refusal
probe. Screenshots eyeballed clean — and the menu shot visibly
proves R94: Quit with Ctrl+Q at the bottom of the File menu,
after a separator.

## Sweeps

Em-dash sweep of non-docstring string literals: 0 hits. Secrets
grep: clean. Zip modes: all scripts 0o100755, all plain files
0o100644, file-type bits present; all entries deflated.

## Merge notes

Two conflicts, both test files: tests/test_v27.py (both builders
removed the version pins — kept A's section header, the NOTE line
was shared) and tests/test_v28.py (add/add — combined: A's file
as base for the stronger version test, B's helpers + slice tests
appended; B's duplicate version tests dropped). The merge caught
one duplicate-definition slip (B's version tests sat between its
helpers and its R93 marker, so the first extraction kept them)
and the two defects above. No merge-interaction defects in
product code.

---

# STELLA v0.27.0 — Test Report

Verified 2026-11-17 by the coordinator from a FRESH UNZIP of
stella-v0.27.zip (1,165,983 bytes, SHA-256
dc345d04ab412bf7ccabdef2855b0389b0477cf9838e177f60ce8649ebe549e7),
not from the builders' claims. Python 3.12.3, PySide6 offscreen Qt,
forge-v2-testenv; TMPDIR under the workspace (STELLA has no
QFileSystemWatcher, so this is safe).

## Suite: 1749 passed, 65 skipped (1821 collected)

The single-process full run OOMs on this 6 GB VM, so the suite ran
in 4 chunks from the same fresh unzip: non-GUI 1373 passed + 65
skipped + 6 failed, test_gui.py in 3 chunks (129 + 124 + 123
passed + 1 failed). Counts reconcile exactly to the 1821
collected. Of the 7 failures, 4 were real merge defects fixed in
place and re-verified green, and 3 are proven load flakes:

- test_json_sweep_no_command_silently_returns_text[sleep-delete]
  and [sleep-prune]: KeyError — Builder A's R52 sweep map had no
  entries for Builder B's new R66 commands. The product gate
  already refused --json for them correctly; the fix was two
  entries in the sweep's arg map (test-only).
- test_fetch_downloads_a_wheel_from_scratch and
  test_fetch_finalizes_a_complete_partial_file: the fake wheel
  server logged each request AFTER serving the body, so the test
  asserted on the log before the handler thread appended to it
  (the log entry was there by the time pytest formatted the
  failure). The server now logs before serving (test-only).
- test_cli_train_ctrl_c_pauses and
  test_cli_train_second_ctrl_c_exits_at_once: signal timing under
  load. 5 solo runs: fail, fail, pass, pass, split — the pair
  passes when the box is quiet. Same flake as v0.25.0/v0.26.0.
- test_second_main_exits_zero_while_first_runs: second-launch
  timing under load. 3/3 solo. Same flake as v0.26.0.

The fixed tests were re-run from a second fresh unzip of the
rebuilt zip: 27 passed (16 wheel_fetch + 2 sweep + 9 test_v27).

## CLI smoke: green

`stella-cli --version` reports 0.27.0; --help lists sleep-delete,
sleep-prune, save-key, clone-profile, clone-project;
`sleep-delete --help` works; `profiles --json` prints [].

## GUI drive: green

drive_gui.py offscreen: window opens, job buttons Train / Sleep /
Make smaller / Teach a small model, Go, Export GGUF, Run refusal
probe. Screenshot eyeballed clean — and it visibly proves R92:
How to Use opens on Getting started, the topic selected and its
body shown, with the R70 topics (Bridge, Checkpoints, Governing
seats, Recipe and adapter packages) in the list.

## Sweeps

Em-dash sweep of non-docstring string literals: 0 hits. Secrets
grep: clean. Zip modes: all scripts 0o100755, all plain files
0o100644, file-type bits present; all entries deflated.

## Merge notes

Two conflicts, both additive: README.md (kept A's clone-project
line + B's updated train line) and tests/test_v27.py (both
builders created it — combined: B's file as base, one copy of
the version tests + each half's slice tests). The merge caught
two real defects neither builder's green run showed: the JSON
sweep KeyError above, and the R13 desktop training icon — its
Exec used the %k pattern, which resolves to the Desktop folder,
so the Desktop copy was broken since v0.25.0. install.sh now
rewrites the Desktop copy's Exec to the absolute launcher path
(the tree copy keeps the portable %k form), uninstall.sh removes
the Desktop training icon when it names this install, and the
installer tests now double-click the Desktop copy for real.

---

# STELLA v0.26.0 — Test Report

Verified 2026-11-17 by the coordinator from a FRESH UNZIP of
stella-v0.26.zip (1,118,059 bytes, SHA-256
dca72ee7546cf61e9147e59fe20d8f76a7b99aae0e21c5f1ecb95b162eaed215),
not from the builders' claims. Python 3.12.3, PySide6 offscreen Qt,
forge-v2-testenv; TMPDIR under the workspace.

## Suite: 1569 passed, 64 skipped (1633 collected)

The single-process full run OOMs on this 6 GB VM, so the suite ran
in 4 chunks from the same fresh unzip: non-GUI 1205 passed + 64
skipped, test_gui.py in 3 chunks (126 + 119 + 119 passed). Counts
reconcile exactly to the 1633 collected. Zero failures in the
completed runs. A runtime restart killed the first GUI chunk-02
run at ~60% with one unidentified failure showing in the dots;
the full re-run of that chunk is 119/119 green, so it was a load
flake (load average above 25 at the time), not a regression.

## CLI smoke: green

`stella-cli --version` reports 0.26.0; `create-project --help`
still lists `--method` (R28); `export-gguf --help` lists
`--from-sleep` (R3, still there).

## GUI drive: green

drive_gui.py offscreen: window opens, job buttons Train / Sleep /
Make smaller / Teach a small model, Go, Export GGUF, Run refusal
probe, Install training. Screenshot eyeballed clean — and it
visibly proves R41: the status bar reads "Ready." with a live
session, not "Pick a profile to begin."

## Sweeps

Em-dash sweep of non-docstring string literals: 0 hits. Secrets
grep: clean. Zip modes: all scripts 0o100755, all plain files
0o100644, file-type bits present; all entries deflated.

## Merge notes

Two conflicts, both additive: tests/test_gui.py (both builders
added tests at the same spot — kept both) and tests/test_v26.py
(both builders created it — combined: one copy of the version
tests + each half's slice tests). No merge-interaction defects
this version (unlike v0.25.0's R3/R4 modal hang).

---

# STELLA v0.25.0 — Test Report

Verified 2026-11-17 by the coordinator from a FRESH UNZIP of
stella-v0.25.zip (1,081,271 bytes, SHA-256
46d00c4cd486cd4c7fffee4048a352dfa920b3c060d72117562333ae49083e27),
not from the builders' claims. Python 3.12.3, PySide6 offscreen Qt,
forge-v2-testenv; TMPDIR under the workspace (STELLA has no
QFileSystemWatcher, so this is safe).

## Suite: 1485 passed, 64 skipped (1551 collected)

The single-process full run OOMs on this 6 GB VM (killed at ~51%),
so the suite ran in 4 chunks, all from the same fresh unzip:
non-GUI 1134 passed + 64 skipped, test_gui.py in 3 chunks
(122 + 114 + 115 passed). Counts reconcile exactly to the
1551 collected.

Two chunk failures, both proven load flakes by 3/3 solo re-runs:
test_cli_train_second_ctrl_c_exits_at_once (signal timing under a
load average above 10) and
test_job_card_finish_moment_shows_summary_then_hides (250 ms
animation timing under the same load). Neither builder touched the
code under either test.

One real merge-interaction defect, found by the chunked run and
fixed in place: Builder A's new R3 GUI test exported from the
seeded governing profile, and Builder B's R4 gate refuses that
export with a modal warning — the test hung in the modal with no
user to dismiss it. The test now uses a non-governing profile,
exactly like B's T161 test. It passes solo in 14 s and inside the
re-run chunk (115 passed).

## CLI smoke: green

`stella-cli --version` reports 0.25.0; `profiles` gives the
plain-words empty state; `pc-info` picks rank 4 / seq 512 at low
available RAM; `export-gguf --help` lists `--from-sleep`; `chat
--help` works.

## GUI drive: green

drive_gui.py offscreen: window opens, menu bar File/View/Help, job
buttons Train / Sleep / Make smaller / Teach a small model, Go,
Export GGUF, Run refusal probe, Install training button visible,
no settings strings on screen. Screenshot eyeballed clean.

## Sweeps

Em-dash sweep of non-docstring string literals: 0 hits (one new
em-dash in the R3 How to Use text was found and fixed in place).
Secrets grep: clean. Zip modes: all scripts 0o100755, all plain
files 0o100644, file-type bits present; all entries deflated.

## Not verified (needs his PC / real services)

R19–R23 stay hard-gated: the LFM3 proof run, a real sleep-adapter
merge, a real `ollama create` from a Stella export, the literal
double-click of Install Stella.desktop on Mint, and the real 2 GB
training install. Groq/Gemini lists were re-checked against the
providers' pages on build day and tested against fake servers
only — no live key was used.

---

# STELLA v0.3 — Test Report

Verified 2026-11-13 in the sandbox (Python 3.12.3, PySide6 offscreen
Qt; training stack torch 2.15.0+cpu, transformers 5.22.2, peft
0.21.2, accelerate 1.15.0). Every check below was run from a FRESH
UNZIP of stella-v0.3.zip, not assumed. The v0.3 builder was
interrupted before verifying; this report is the finisher's
verification of the finished tree.

## Suite: 142/142 green

`bash run_tests.sh` (pytest, from a fresh unzip).

- Train venv (full stack): **142 passed, 15 warnings, 106.9s.**
- Base install (PySide6 only, no torch): **120 passed, 22 skipped,
  8.2s** — the training tests skip cleanly, the suite still goes
  green.

Per file: test_model 30, test_sleep 24, test_train 23, test_cli 18,
test_gui 17, test_export 11, test_probe 8, test_gguf 8, test_ollama 3.

The 15 warnings are all one known peft warning (`fan_in_fan_out`
on the tiny Conv1D test model) — a test artifact, not a product
issue. The v0.2 `float(out.loss)` requires_grad UserWarning is
FIXED (both occurrences now use `.detach()`).

Note: both suite runs print `malloc_consolidate(): unaligned
fastbin chunk detected` AFTER pytest's summary, with exit code 0 —
a post-run Qt teardown artifact in the sandbox, not a test failure
(the same post-OK teardown abort seen on other Qt suites here).

New in v0.3 (32 tests): test_sleep.py (24) — manifest/hash
round-trips, orphan-report reconciliation, unslept counts, dreaming
(filter/dedupe/cap/Ollama-down skip/no-tag skip), export/import
round-trip of sleep cycles, end-to-end tiny cycles (cycle 1 + a
second cycle replaying against old rows), dreaming with a fake
Ollama server, Ollama-down still sleeps, replay verdicts with
canned losses (DEGRADED at +50%, OK at -10%, exactly +10% is NOT
degraded), the single-load proof (replay loads once; a full sleep
loads twice total — one consolidate, one replay), rank capped at 8,
RAM-guard refusal, pause-then-resume completing the same cycle,
plus the two regression tests for defect 1 below. test_cli.py (+4)
— sleep help, sleep-status with no cycles, sleep with no base_ref
(cheap checks before the dependency gate), sleep with missing deps.
test_gui.py (+4) — Sleep panel widgets exist, cycle list shows a
seeded cycle, start-sleep with no deps logs the install hint,
start-sleep gated on save failure (bad learning rate starts
nothing).

## CLI smoke: 22/22 green (script /tmp/stella-v03-smoke.py)

Driven through `bash stella-cli` exactly as on a PC, from the fresh
unzip: `--version` says 0.3; create-profile/create-project;
sleep-status with no cycles; sleep with no dataset and sleep with a
missing --rows file both exit 1 with a plain error and NO traceback
(cheap checks run before the dependency gate); an API sleep with
dream=True against a fake Ollama server (the CLI has no tiny-model
hook, so the model step runs through the API exactly as the tests
do) completed cycle 1 with 2 dreamed rows kept, 6 real rows, old
losses None on cycle 1 (not faked), manifest 6 slept / 2 dreamed
hashes, and dream + replay + done events; CLI sleep-status then
showed `cycle 1 ... 2 dreamed` and `6 rows slept on, 0 of 6 still
awake`; CLI export carried sleep/ (manifest, cycle-1 report,
adapter) and CLI import into a fresh home restored it whole
(manifest hashes, adapter file, sleep-status shows cycle 1).

## GUI drive: 16/16 green (script /tmp/stella-v03-gui-drive.py)

The real window, offscreen, against the smoke home (a finished
cycle 1): window visible; profile + project listed; Sleep button
present and enabled; "Dream first" checkbox present and unchecked;
cycle list shows 1 item reading `cycle 1 — OK — 6 new, 2 dreamed`;
clicking it opens the report dialog with the real numbers (cycle 1,
OK, 6 new / 2 dreamed, new loss, threshold); no bare `&` in any
visible label; start-sleep with the training deps hidden logs the
install-training.sh hint and starts no worker.

## Defects found and fixed in place (by the finisher)

1. **Resume path crashed on a partially-written cycle dir
   (sleep.py).** `_find_unfinished_cycle` only required
   `train_rows.jsonl`, but the resume branch then read
   `cycle_input.json` with an unguarded `json.loads` + key access
   and `val_rows.jsonl` with no missing-file handling. The
   fresh-cycle path writes train_rows, val_rows, then cycle_input
   in sequence — a crash between the writes left a dir that made
   every later `sleep` die with a raw traceback (FileNotFoundError /
   JSONDecodeError / KeyError — the CLI catches only StellaError).
   Fixed: the finder now requires all three input files (a partial
   dir is ignored and the next fresh cycle reuses its number and
   overwrites it — safe, because no checkpoints or adapter can
   exist before cycle_input.json is written, training only starts
   after it); the cycle_input parse + key access is wrapped and
   raises a plain StellaError naming the cycle and the fix
   (delete the cycle dir, re-run sleep — no rows are lost, they are
   still in the dataset); `_load_rows_file` turns OSError into
   StellaError. Pinned by two regression tests
   (`test_sleep_partial_cycle_dir_self_heals`,
   `test_sleep_corrupt_cycle_input_is_a_plain_error`).
2. **Smoke-script bug (not product code):** the first smoke run
   looked for the export in the given dir instead of the
   `<project>-stella-export` subdir export_project creates, so 6
   checks failed on paths while the export itself was correct
   (the listing showed sleep/ complete with manifest, report,
   adapter, checkpoints). Fixed in the script; re-run 22/22.

No other defects found. The design was checked against the brief
in full: new LoRA adapter per cycle on new rows only (content-hash
manifest, base + prior adapters frozen); dreaming validated,
deduped, capped, skipped cleanly when Ollama is down; replay check
flags DEGRADED past the threshold and never silently passes a
cycle; one model at a time in the replay path (proven by the
single-load tests); RAM guard + checkpoint/resume reused from
train.py; CLI sleep + sleep-status; worker-threaded Sleep panel
with Dream checkbox + cycle list; export/import carries sleep/
whole; README states the honest limits (SFT only, no RL on CPU; no
MoE routing — Ollama cannot route LoRA experts, adapters merge via
GGUF export; Google's numbers are authors'-only, unreplicated).

## Secrets check

Grep of the finished tree for hardcoded keys/tokens/passwords/
credentialed URLs: ZERO matches. No .env, providers.json,
credentials, .pem, or .key files anywhere. Stella talks to local
Ollama and public Hugging Face downloads only. The repo
`.gitignore` (added 2026-11-13) covers .env, providers.json,
credential/secret files, .pem/.key/id_rsa, __pycache__, .venv,
.stella/, and zips.

## Not verified (needs his PC / real services)

- A real LFM3 sleep cycle (sandbox proves the pipeline on a tiny
  random model only — same standing caveat as the v0.2 proof run).
- Dreaming against his real Ollama models (fake server only here).
- Real llama.cpp GGUF merge of a sleep adapter (the merge path is
  the v0.2 one, unchanged).
- The visible window, Nemo double-click install, and app-menu icon
  on his Mint PC (standing v0.1/v0.2 caveat).
- The 120s dream timeout against a slow local CPU model (the
  timeout path itself is proven by the Ollama-down tests).

---

# v0.2 — still applies (installer files unchanged in v0.3)

Verified 2026-11-12 in the sandbox. Kept here because the installer,
installed-app, and training-stack checks were not re-run for v0.3 —
those files did not change.

## v0.2 suite: 110/110 green

test_model 30, test_train 23, test_cli 14, test_gui 13,
test_export 11, test_probe 8, test_gguf 8, test_ollama 3.

## v0.2 fresh-unzip check

Unzipped `stella-v0.2.zip` to a clean directory: exec bits survived
extraction (`install.sh`, `install-training.sh`, `run.sh`,
`stella-cli`, `run_tests.sh` all `rwxr-xr-x`), and the suite runs
110/110 green from the fresh tree.

## v0.2 installer check (sandbox, fake HOME)

`bash install.sh` from the fresh unzip: creates the private `.venv`,
installs PySide6-Essentials, passes both fatal import checks, writes
`~/.local/share/applications/stella.desktop` (absolute Exec/Icon,
quoted so install paths with spaces still launch) and a desktop copy,
links `stella` into `~/.local/bin`, exits 0. If `python3-venv` is
missing, the installer says so and names the fix
(`sudo apt install python3-venv`) instead of failing cryptically.

## v0.2 installed-app check

Through the installed `stella` command (fake HOME + fake PATH):
create profile, create project, list both, export to a folder, import
the package into a second fresh home, list again — full round-trip OK.
The GUI was driven from the installed venv (offscreen): window renders
1100x680, three panes populated, role/tag/detail all correct, and the
Train panel renders with all controls (dataset buttons, Start/Pause/
Resume, progress bar, checkpoints, Export GGUF, refusal probe, log).

## v0.2 training-stack check (sandbox)

`bash install-training.sh` installs torch CPU + transformers + peft +
accelerate into the private venv and passes its import check (torch
2.15.0+cpu, transformers 5.22.2, peft 0.21.2, accelerate 1.15.0).
The training tests that need the stack ran against it: the tiny-model
LoRA run, pause/resume, adapter merge, and probe all passed.

## v0.2 defects found and fixed in place

1. LoRA target expectation: the first test run asserted GPT-2 targets
   were `["c_attn", "c_proj"]`, but the detector also correctly found
   `c_fc` (the MLP intermediate projection is LoRA-able too). The
   code was right; the test expectation was wrong — fixed to
   `["c_attn", "c_fc", "c_proj"]`.
2. Slow dependency gate: `training_deps_missing()` imported torch to
   check for it, which takes 10+ seconds and timed out the CLI
   subprocess test at 60s. It now uses `importlib.util.find_spec`
   (no import) — the gate answers in under a second; the real
   imports happen when training actually starts.
3. `run_tests.sh` on a bare checkout: the GUI tests need PySide6,
   which the script did not install (only pytest). It now installs
   PySide6-Essentials when the import fails, so the suite runs from
   a fresh unzip. Training tests skip cleanly without the training
   stack.
4. `install-training.sh` robustness, from the sandbox install that
   built the test venv: pip's default 15s read timeout repeatedly
   failed the torch download, so both install lines now carry
   `--timeout 120 --retries 10`. And the printed pull-weights hint
   used system `python3`, which has no huggingface_hub — it now
   names the venv python, which has it (via transformers).

## Still needs Joshua's real-PC verdict (the Item 3 closer)

- The LFM3 proof run itself: `bash install-training.sh`, profile
  with base ref `LiquidAI/LFM3-1.7B`, sample dataset, `stella train`
  (hours on CPU — watch the loss fall), `stella probe`, llama.cpp
  install, `stella export-gguf`, `ollama create`, and a live test
  in Forge (one clean tool call, no fenced JSON). The sandbox proved
  the pipeline on a tiny random model only; no 1.7B weights were
  downloaded or trained here.
- LFM3 loads with `trust_remote_code=True` (its config maps the
  model to remote modeling code) — untested until the real pull.
- The visible window on his Mint desktop (sandbox only proves
  offscreen rendering), Nemo double-click install, the app-menu icon.
- The Ollama tag picker against his real Ollama (sandbox used a fake
  server + the offline fallback).
- PySide6 + training-package install times on his machine (one
  download each at install).
