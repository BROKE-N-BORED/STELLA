# STELLA Audit #6 — Installer + icon: Task List

**Source:** [audit-06-installer-icon-2026-11-12.md](audit-06-installer-icon-2026-11-12.md)
(Installer + icon audit, 2026-11-12, against v0.2 / commit 9a821e07).

**This file is a list only.** Nothing here has been fixed or built.
Each task turns one or more audit findings into work with a verifiable
"done". Priorities follow the audit's section 8; within a priority,
a fix comes before the polish that depends on it.

**Priority key:** P0 = data loss / silent failure, fix first.
P1 = real functional defect or daily friction. P2 = missing capability
or inconsistency. P3 = polish, display, and scale.

**Effort key:** S = a focused change in one or two files, a day or
less. M = a change across model + GUI + tests, or a small design
decision plus implementation. L = a multi-part build or a design that
needs Joshua's direction on scope first.

**Counts:** 25 tasks — 2 P0, 9 P1, 11 P2, 3 P3.

**Shared fixes with the repo-audit verdict and audit #4:** four
findings share their fix with earlier work and are built once, not
twice. The menu icon (W1/W2 — with verdict R4, the icon PNGs);
the double-click installer (W3 — with verdict R3); the window icon
(U5 — with audit #4 U6 / verdict R18, the window chrome pass); and
version pins (W13 — with verdict R13, the pinned training
requirements). In this standalone file they appear as installer
tasks (T1, T2, T3, T16, T14); the merged list
([stella-audit-task-list-123.md](stella-audit-task-list-123.md))
folds them into the single shared tasks. The exec-bits task
(verdict R5) has no audit #6 finding — audit #6 verified the zip's
stored modes are correct (P15), so it stands as written for the
clone path. Audit #5's W2 (raw tracebacks from `main()`) is the same
class as W5/W11 here (raw errors instead of Stella messages) but in
different code — related, not shared.

---

## P0 — fix first

### T1 — Unquote `Icon=`, keep `Exec` quoted

- **Covers:** W1, D1
- **Effort:** S
- **Problem:** `install.sh` writes `Icon="$DIR/assets/stella.png"`
  — quoted, the same treatment as `Exec`. But quoting is only
  defined for `Exec` in the desktop-entry spec; `Icon` is a plain
  string, and GLib takes the quotes literally. Probed with ctypes
  against libgio itself (P13), on the generated file from the
  fresh-unzip install: icon string
  `'"/home/.../assets/stella.png"'` — exists as-is: False; stripped
  of quotes: True. The spaced-path install gives the same result.
  The unquoted control resolves (`exists as-is: True`) — including
  on the spaced path, so spaces are not a reason to quote `Icon`.
  The menu entry therefore shows a generic icon on every install,
  zip or clone, spaced or not. This is the v0.1 quoting fix
  backfiring: it was verified by *reading* the generated file
  ("quoted so install paths with spaces still launch" —
  TEST-REPORT.md), never by asking GLib what the icon resolves to.
  The launch half is true (`Exec` quoting is spec-defined and `gio
  launch` works); the icon half is false. The README's "puts Stella
  in the app menu with its star icon" does not hold on any install,
  and the real-PC verdict that would have caught it is still open.
- **Fix:** D1 — unquote `Icon=` (one line in `install.sh`). The
  GLib probe (P13) proves unquoted `Icon` resolves on plain and
  spaced paths alike; `Exec` quoting is spec-defined and stays.
  Verify the fix with the same ctypes probe — or better, make the
  probe a test (T10).
- **Done:** A fresh install's desktop file has an unquoted `Icon=`;
  GLib resolves it to the file (probed via ctypes) on a plain and
  a spaced path; the menu entry shows the star. Tests: the
  icon-resolution check in the installer tests (T10).

### T2 — Render the PNGs at install time when they're missing

- **Covers:** W2, D2
- **Effort:** M
- **Problem:** The GitHub push cannot carry binary PNGs, so the
  repo has the SVG source but no rendered PNGs. `install.sh` never
  calls `render_icon.py` (0 mentions in any script, program, or
  README) and never checks the icon file exists. Probed (P2): a
  tree copy with `assets/*.png` deleted installed with exit 0 and
  printed "Stella is installed", while the desktop file points at
  `.../assets/stella.png`, which does not exist — and the assets
  dir still held only `stella.svg` afterwards. This is the MIMIK
  v0.2 trap in Stella's form: MIMIK's installer died in its icon
  loop under `set -e` before writing the launcher; Stella's
  installer has no icon step at all, so it *succeeds* and silently
  ships a broken menu icon. `render_icon.py` is orphaned — it
  exists, it works (QtSvg is available in the installed venv,
  probed), and nothing invokes it. Even with T1 fixed, a clone
  install still has no icon file at all.
- **Fix:** D2 — after the venv exists, if `assets/stella.png` is
  absent, run `render_icon.py` — QtSvg is available in the
  installed venv (probed). Fallback, also probed: point `Icon=` at
  the SVG itself unquoted — GLib resolves it. Either way, never
  write a desktop file whose icon doesn't exist; check the file
  before writing, and fail loudly (or warn clearly) if the icon
  cannot be produced.
- **Done:** A clone-shape install (PNGs deleted) ends with a
  working menu icon; a zip install still works; install.sh fails
  loudly (or warns clearly) if the icon cannot be produced.
  Tests: clone-shape install produces the icon (T10).

---

## P1 — functional defects and daily friction

### T3 — Ship a real double-click installer

- **Covers:** W3, D3
- **Effort:** S
- **Problem:** README.md:21: "Unzip a release anywhere, then
  double-click **Install Stella** in the folder". `install.sh:2`
  says the same. There is no `Install Stella` file: `find` over
  the tree and the zip listing both show no `.desktop` file
  anywhere (only `install.sh` and `install-training.sh`).
  Double-clicking `install.sh` itself in Nemo opens a text editor
  (or a run prompt) — it does not install. The documented first
  step for the user who hand-types commands from his phone does
  not exist; the only working path is a terminal and
  `bash install.sh`. (SKULLPT v1.2 shipped a real
  `Install-SKULLPT.desktop` for exactly this reason.)
- **Fix:** D3 — ship an `Install-Stella.desktop` in the zip that
  runs `install.sh` in a terminal, or fix the README to tell the
  terminal truth. The README's first install step must name a file
  that exists.
- **Done:** Double-clicking Install Stella.desktop (or launching
  it via gio launch) runs the installer; the desktop file
  validates (desktop-file-validate clean); the README's install
  instructions match what ships.

### T4 — Make install atomic: check before writing artifacts

- **Covers:** W4, D4
- **Effort:** S
- **Problem:** The desktop file and the `~/.local/bin/stella`
  symlink are written *before* the final `import stella` check.
  Probed (P8): with `stella/__init__.py` sabotaged to raise,
  install exited 1 with `ERROR: Stella did not import after
  install.` — and both artifacts were on disk. The menu entry
  exists, clicking it runs `run.sh` into a crash that is invisible
  (`Terminal=false`), and `stella` runs a broken tree. The install
  is not atomic: failure is reported, but the half-installed state
  looks installed.
- **Fix:** D4 — move the final `import stella` check before the
  desktop file and symlink are written — or roll the artifacts
  back on failure. A failed install must leave no launcher behind.
- **Done:** A sabotaged final check exits 1 with no desktop file
  and no symlink left behind; a good install still writes both.
  Tests: sabotage test in T10.

### T5 — `run.sh`: check PySide6 before exec, and fail visibly

- **Covers:** W5, D5
- **Effort:** S
- **Problem:** Probed (P7b): venv present, PySide6 absent →

  ```
  File ".../stella/gui.py", line 21, in <module>
      from PySide6.QtCore import Qt, QThread, Signal
  ModuleNotFoundError: No module named 'PySide6'
  ```

  exit 1, no Stella message. This is the state after any pip
  failure mid-install (W11) — and exactly the failure SKULLPT v1.1
  hit on his PC (`run.sh` failed, PySide6 missing, Bench never
  opened). From the menu, with `Terminal=false`, the user sees
  nothing at all: the window just doesn't open, with no error
  anywhere.
- **Fix:** D5 — if the import fails, print the plain "run
  `bash install.sh`" message instead of a traceback. With
  `Terminal=false`, consider a `zenity`/`kdialog` fallback so a
  menu-launch failure is visible at all.
- **Done:** `run.sh` with a venv but no PySide6 prints a plain
  message naming the fix (and shows a dialog when launched from
  the menu); no traceback. Tests: the P7b shape (venv, no
  PySide6).

### T6 — `run_tests.sh` must use the venv, never system pip

- **Covers:** W6, D17
- **Effort:** S
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
- **Fix:** D17 — create/use `.venv` for the test run, or refuse
  on a bare checkout with "run `bash install.sh` first". Never
  `pip install` into system Python on Mint.
- **Done:** `bash run_tests.sh` on a bare checkout either runs
  the suite via a venv or refuses with the plain message; no
  externally-managed error. Tests: bare-checkout run.

### T7 — Add a repair/doctor path

- **Covers:** W7, G3, D13
- **Effort:** M
- **Problem:** Everything install.sh writes is an absolute path to
  `$DIR`. Probed (P12): after `mv moveme moved-to`, `gio launch`
  on the desktop file exited 1 (`Unable to load application
  information`), `stella` became `command not found` (exit 127,
  dangling symlink) — while `run.sh` from the new location works
  fine (timeout 124), because it resolves its own dir. Re-running
  `install.sh` from the new location would repair it, but nothing
  says so anywhere; the user is left with a dead menu entry and a
  dead command. And after a move (W7) or a broken venv (W5), the
  only recovery is re-running `install.sh` — which works, but
  nothing says so, and there is no `--check`/`doctor` mode that
  verifies the launcher, symlink, icon, and venv and fixes what's
  stale (G3).
- **Fix:** D13 — a `stella doctor` (or `install.sh --repair`)
  that verifies venv, PySide6, launcher, symlink, and icon, and
  re-links what's stale after a move. Repair re-links a working
  icon (T2), not a broken one.
- **Done:** Move the folder, run the doctor: the launcher and the
  `stella` command work again from the new location; a broken
  venv is reported with the fix named. Tests: move-then-doctor.

### T8 — Add `--timeout 120 --retries 10` to install.sh's pip lines

- **Covers:** W8, D6
- **Effort:** S
- **Problem:** `install-training.sh` got `--timeout 120 --retries
  10` as a v0.2 fix because "pip's default 15s read timeout
  repeatedly failed the torch download" (TEST-REPORT defect #4).
  `install.sh:36-37` still runs plain `--quiet` pip installs —
  for a ~90 MB PySide6-Essentials wheel on the same slow
  connection. The base install can fail exactly the way the
  training install used to. (Code reading + the v0.2 defect
  record; not live-probed with a throttled connection.)
- **Fix:** D6 — same fix as install-training.sh already has.
- **Done:** install.sh's pip lines carry the flags; a
  slow-connection install retries instead of failing at 15 s.
  Tests: flags present (grep test).

### T9 — Distinguish venv-failure causes; clean up only what you made

- **Covers:** W9, W10, D7
- **Effort:** S
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
- **Fix:** D7 — check `python3 -c "import venv, ensurepip"` first
  and print the `python3-venv` message only when the module is
  actually missing; otherwise print the real venv error. Only
  `rm -rf` a `.venv` this run created (or one that looks like a
  venv).
- **Done:** A stray file at `.venv` gets the real error (not the
  python3-venv message) and is not deleted; a genuinely missing
  python3-venv still gets the exact named fix. Tests: stray-file
  case, missing-module case.

### T10 — Add installer tests, including the GLib icon check

- **Covers:** G2, D12
- **Effort:** M
- **Problem:** No `test_installer.py`; the only test references
  to the installers assert that error messages *name*
  `install-training.sh` (`test_cli.py:119,160`,
  `test_gui.py:121`, `test_train.py:236`). The installer is
  verified only by the manual fresh-unzip check in
  TEST-REPORT.md — which is how W1 survived: the manual check read
  the desktop file but never asked GLib what the icon resolves to.
- **Fix:** D12 — a `test_installer.py` that runs `install.sh` in
  a scratch HOME and asserts: the desktop file parses, the icon
  resolves via GLib, the symlink works, re-install is idempotent,
  a clone without PNGs renders or warns. The icon-resolution check
  is the one that would have caught W1. Lands alongside T1 — the
  test pins the P0 fix.
- **Done:** The suite includes installer tests covering the
  desktop file, the GLib icon resolution, the symlink, re-install
  idempotence, and the clone-without-PNGs case; the icon test
  fails against the pre-fix installer. Tests: the new file
  itself.

### T11 — Fix the README install section

- **Covers:** U1, U2, D16
- **Effort:** S
- **Problem:** Two false claims in the first install paragraph:
  "double-click **Install Stella**" (no such file — W3) and "puts
  **Stella** in the app menu with its star icon" (the icon is
  broken by W1 on every install, absent by W2 on a clone). The doc
  face of W1/W2/W3. And `install.sh` ends with "Command line is
  available too: stella profiles". `~/.local/bin` joins PATH at
  login (Mint's `~/.profile` adds it only if the dir exists at
  login time). A terminal already open at install time — or a
  first install where `~/.local/bin` didn't exist at login —
  won't find `stella` until logout/login (U2). Probed (P14): a
  fresh login shell in this sandbox HAS `~/.local/bin` on PATH,
  but that proves the mechanism, not the claim — the claim holds
  only for terminals opened after a login where the dir existed.
- **Fix:** D16 — name a real first step, qualify the `stella`
  command ("open a new terminal after install, or log out and back
  in"), document removal (T17) and move/repair (T7).
- **Done:** The README's first install step names a file that
  exists; the `stella` command claim carries its condition;
  removal and repair are documented. Tests: doc review (the
  README is prose — no test asserts it).

---

## P2 — missing capabilities and inconsistencies

### T12 — Wrap pip failures in a Stella error

- **Covers:** W11, D8
- **Effort:** S
- **Problem:** Both installers run pip bare under `set -e`, so a
  pip failure exits at the pip line and the friendly fatal checks
  never run. Probed twice: ENOSPC during the PySide6 install →
  raw `ERROR: Could not install packages due to an OSError:
  [Errno 28] No space left on device`, exit 1, no Stella line;
  dead torch index (P9c) → 180+ seconds of pip `WARNING:
  Retrying ...` lines, no Stella message at all. The user gets
  pip's diagnostics, not Stella's.
- **Fix:** D8 — on a pip exit != 0, print a plain line naming the
  step ("PySide6 download failed — check your connection and run
  `bash install.sh` again") instead of leaving raw pip output as
  the last word.
- **Done:** A failed pip install ends with a Stella line naming
  the step and the retry; raw pip output is no longer the last
  word. Tests: failing-pip harness (dead index or ENOSPC).

### T13 — Disk-space preflight

- **Covers:** W12, D9
- **Effort:** S
- **Problem:** Neither installer checks free space before
  downloading (~90 MB wheel / 259 MB installed for the base;
  ~2 GB for training). The only "disk space" strings in the
  scripts are inside the post-failure error messages. On his 1 TB
  HDD this is unlikely to bite, but the failure mode is a
  mid-download ENOSPC with raw pip output (probed in miniature in
  P1's first attempt).
- **Fix:** D9 — check free space before downloading (~500 MB base,
  ~3 GB training) and refuse plainly when it won't fit.
- **Done:** An install with too little free space refuses before
  downloading, naming the space needed; a normal install is
  unaffected. Tests: preflight with a faked small filesystem (or
  a huge estimate).

### T14 — Pin versions, or record them

- **Covers:** W13, D10
- **Effort:** S
- **Problem:** `pip install PySide6-Essentials`, `torch`,
  `transformers`, `peft`, `accelerate` are all unpinned. The train
  venv happens to hold torch 2.15.0+cpu / transformers 5.22.2 /
  peft 0.21.2 / accelerate 1.15.0 because of when it was built,
  not because the script says so. A future release can change
  behavior under the same installer, and nothing records which
  versions an install actually got.
- **Fix:** D10 — pin `PySide6-Essentials`, `torch`,
  `transformers`, `peft`, `accelerate` to the verified versions —
  or at minimum write the installed versions into an install
  receipt (T19).
- **Done:** A fresh install gets exactly the verified versions
  (pinned files), or the receipt records what was installed.
  Tests: pinned files consumed by both installers; receipt lists
  versions (T19).

### T15 — Make the success message reflect reality

- **Covers:** U2, U3, U4, U8, D18
- **Effort:** S
- **Problem:** "double-click Stella on the desktop. No terminal
  needed." prints even when the desktop copy was skipped (U3:
  `cp ... "$HOME/Desktop/Stella.desktop" 2>/dev/null || true` —
  probed P1: scratch HOME with no `Desktop` dir → no copy, no
  message), and the whole success block prints even though the
  menu icon is broken (W1). The message describes the intended
  install, not the one that landed (U4). And the final check runs
  `import stella; print(stella.__version__)`, so the install
  output contains a lone `0.2` line between "Installing Stella
  from ..." and the success message — a version number with no
  label, looking like stray output (U8). The `stella`-on-PATH
  claim (U2) is conditional — the README half is T11; this task
  is the message half.
- **Fix:** D18 — claim the desktop icon only if the copy landed;
  claim `stella` only if `~/.local/bin` is on PATH (or say to
  open a new terminal); label the version line (`Stella 0.2`).
- **Done:** With no `~/Desktop`, the success message does not
  claim a desktop icon; with `~/.local/bin` off PATH, it says to
  open a new terminal; the version line is labeled. Tests:
  install into a HOME with no Desktop dir; PATH-off case.

### T16 — Set the window icon in `gui.py main()`

- **Covers:** U5, D14
- **Effort:** S
- **Problem:** No `setWindowIcon` / `QIcon` anywhere in the tree
  (grep). The window, taskbar, and alt-tab show Qt's generic icon
  even though a star icon sits in `assets/`. The `.desktop` icon
  (once T1 is fixed) covers the menu, not the running window.
- **Fix:** D14 — `QIcon` from `assets/stella.png`, guarded if
  the file is missing, so the running window shows the star.
- **Done:** The running window, taskbar, and alt-tab show the star
  icon; a missing icon file does not crash startup. Tests: window
  icon set (GUI test), missing-file guard.

### T17 — Add `uninstall.sh` + a removal section in the README

- **Covers:** G1, D11
- **Effort:** M
- **Problem:** No `uninstall.sh`, no removal instructions anywhere
  (grep: zero mentions outside one test comment). Removing Stella
  means hand-deleting the folder,
  `~/.local/share/applications/stella.desktop`,
  `~/Desktop/Stella.desktop`, `~/.local/bin/stella`, and deciding
  about `~/.stella` — and nothing tells the user the list.
- **Fix:** D11 — remove launcher, desktop copy, symlink, venv;
  ask about `~/.stella` data (never delete it silently). Document
  the removal in the README (with T11).
- **Done:** `bash uninstall.sh` removes the launcher, desktop
  copy, symlink, and venv, and asks about `~/.stella` before
  touching it; the README documents removal. Tests: uninstall
  after install leaves no artifacts (except `~/.stella` when
  kept).

### T18 — Install icons into the hicolor theme + render small sizes

- **Covers:** G4, U6, D15
- **Effort:** M
- **Problem:** The icon is referenced by absolute path from the
  install dir instead of installed into
  `~/.local/share/icons/hicolor/`. A theme install (copies, not
  references) would survive a folder move for the icon, and is
  where size variants belong (G4). And `assets/` holds only
  64/128/256/512 + `stella.png` (256) — no 16/32/48 px files. The
  desktop environment scales the 256 down, and the eyeball probe
  (P10) shows the star stays legible at 16 px — so this is polish,
  not a defect — but a purpose-rendered small set would be crisper
  in panels and trays (U6).
- **Fix:** D15 — copy the PNGs (and 16/22/24/32/48 renders from
  `render_icon.py`) into `~/.local/share/icons/hicolor/`. Builds
  on T2 — the hicolor install consumes the rendered sizes.
- **Done:** The icon files land in the hicolor theme at the
  standard sizes; moving the install folder leaves the menu icon
  intact. Tests: theme files present after install;
  move-then-check-icon.

### T19 — Keep an install receipt

- **Covers:** G5, D21
- **Effort:** S
- **Problem:** Nothing records what an install did —
  PySide6/torch versions, where the artifacts went, when it ran.
  When something breaks later, there is no record to send Arlo.
  (The BNB debug-log-layer direction covers this class of gap for
  project builds generally; here it is just a missing artifact.)
- **Fix:** D21 — versions, paths, and timestamp in the tree
  (and/or `~/.stella/`), so a broken install can be reported with
  facts. The receipt records a complete install (T4), not a failed
  one. (The record-them side of D10 — T14 pins, this task
  records.)
- **Done:** After an install, a receipt file names the
  PySide6/torch versions, the artifact paths, and the install
  time; a failed install writes no receipt (or marks it failed).
  Tests: receipt contents after install.

### T20 — Fast path for a training re-run

- **Covers:** W14, D20
- **Effort:** S
- **Problem:** The P9b dry-run probe — same packages, same
  versions, nothing to do — took 148 s: pip re-resolves the torch
  CPU index on every run, and the script prints nothing between
  the header and the torch version line (`--quiet`). A no-op
  second run looks like a hang.
- **Fix:** D20 — check the imports first; if
  torch/transformers/peft/accelerate already import, print
  "training packages already installed" and exit 0 without
  re-resolving the index.
- **Done:** A second run of install-training.sh with everything
  installed exits in seconds with the plain message; a run with
  a missing package still installs it. Tests: second-run timing +
  message.

### T21 — Strengthen the PySide6 check

- **Covers:** W15, D22
- **Effort:** S
- **Problem:** The fatal check is `import PySide6; from PySide6
  import QtWidgets` with stderr hidden (`2>/dev/null`), and its
  error message names only "a network connection, or ... disk
  space". An import succeeds even where creating a window would
  fail (e.g. missing system GL/EGL libs), and that failure's real
  cause would be swallowed. **Not reproduced in this sandbox** —
  `QApplication` creation worked without the extracted Qt libs
  (P1b) — so this is code reading only, stated as a weakness of
  the check's diagnosis, not as an observed failure.
- **Fix:** D22 — create a throwaway `QApplication` offscreen
  instead of import-only, and surface the real stderr on failure
  so a missing system lib names itself.
- **Done:** The install check creates a `QApplication` offscreen;
  a missing system lib fails the check with the real error named.
  Tests: check passes in the sandbox; failure path names the lib
  (fake a missing lib).

### T22 — Document an upgrade path

- **Covers:** G6, D24
- **Effort:** S
- **Problem:** v0.1 → v0.2 means unzipping a new folder and
  installing from scratch. Re-installing over the *same* folder
  is idempotent (P3), but a new folder leaves the old install
  orphaned — old venv (~259 MB), old launcher repointed only if
  the user runs the new `install.sh` — and nothing documents the
  upgrade steps or cleans up the old copy.
- **Fix:** D24 — "Unzip the new version, run its `install.sh`,
  delete the old folder" — or make install.sh detect and offer to
  remove a previous install's venv.
- **Done:** The README documents the upgrade steps; following
  them leaves one working install and no orphaned venv. Tests:
  doc review; upgrade-path walkthrough in a scratch HOME.

---

## P3 — polish, display, and scale

### T23 — Desktop-file polish

- **Covers:** U7, D19
- **Effort:** S
- **Problem:** The generated entry has no `StartupNotify=true`
  (no launch feedback in the panel), no `Keywords` (no search
  terms in the menu), no `Version=1.0`. All optional; all absent.
- **Fix:** D19 — add `StartupNotify=true`, `Keywords`,
  `Version=1.0` to the generated desktop file.
- **Done:** The generated desktop file carries all three;
  desktop-file-validate is clean. Tests: fields present in the
  generated file.

### T24 — Replace the pull-weights one-liner

- **Covers:** U9, D23
- **Effort:** S
- **Problem:** `install-training.sh` ends by printing
  `$DIR/.venv/bin/python -c "from huggingface_hub import
  snapshot_download; snapshot_download('LiquidAI/LFM3-1.7B')"` —
  a long line with nested quotes, for a user who hand-types
  commands from his phone screen. The alternative (let the first
  run download) is printed too, which softens it.
- **Fix:** D23 — a `stella pull-weights <repo>` command, or a
  shorter hint — nothing the user has to hand-type with nested
  quotes.
- **Done:** The training installer ends with a short command (or
  none — the first run downloads); no nested-quote one-liner is
  printed. Tests: installer output contains no nested-quote line.

### T25 — `--help` for the scripts

- **Covers:** G7, D25
- **Effort:** S
- **Problem:** `bash install.sh --help` just installs; the
  scripts ignore arguments entirely. Minor — but the first thing
  a careful user types is `--help`.
- **Fix:** D25 — print usage and exit 0 instead of ignoring
  arguments (install.sh, install-training.sh, run.sh).
- **Done:** Each script answers `--help` with usage and exits 0
  without installing or running anything. Tests: `--help` output
  + exit code per script.

---

## Coverage map

Every finding ID from the audit, and the task(s) covering it. Nothing
dropped.

| Finding | Task(s) | Notes |
|---|---|---|
| W1 — quoted `Icon=` breaks the menu icon on every install | T1 | Unquote Icon=, keep Exec quoted |
| W2 — fresh-clone install silently ships a broken icon | T2 | Render PNGs at install when missing |
| W3 — no double-click installer exists | T3 | Real Install-Stella.desktop |
| W4 — failed install leaves a working-looking launcher + command | T4 | Atomic install |
| W5 — `run.sh` with venv but no PySide6 is a raw traceback | T5 | Check PySide6, fail visibly |
| W6 — `run_tests.sh` can't run on a bare checkout on Mint | T6 | Use the venv, never system pip |
| W7 — moving the folder breaks launcher + command silently | T7 | Repair/doctor path |
| W8 — install.sh pip lines lack `--timeout`/`--retries` | T8 | Same flags as the training installer |
| W9 — every venv failure misdiagnosed as missing python3-venv | T9 | Distinguish causes |
| W10 — venv-failure cleanup deletes whatever sits at `.venv` | T9 | Clean up only what you made |
| W11 — pip failures surface as raw pip output | T12 | Wrap in a Stella error |
| W12 — no disk-space check anywhere | T13 | Preflight before downloading |
| W13 — no version pins | T14 | Pin, or record in the receipt (T19) |
| W14 — training re-run takes ~2.5 min with nothing to do | T20 | Fast path: check imports first |
| W15 — PySide6 import check can't catch a broken GUI start | T21 | Create a throwaway QApplication |
| U1 — README install paragraph promises things that don't exist | T11 | Fix the README install section |
| U2 — "`stella` on PATH" is conditional, installer doesn't say so | T11, T15 | T11 README half; T15 message half |
| U3 — Desktop copy silently skipped when `~/Desktop` missing | T15 | Claim only what landed |
| U4 — success message claims things unconditionally | T15 | Message reflects reality |
| U5 — the running window has no icon | T16 | setWindowIcon in gui.py main() |
| U6 — no 16/32/48 px icon files shipped | T18 | Render small sizes into hicolor |
| U7 — desktop-file polish missing | T23 | StartupNotify, Keywords, Version |
| U8 — install log prints a bare "0.2" | T15 | Label the version line |
| U9 — pull-weights hint is a long quoted one-liner to type | T24 | Shorter command, no nested quotes |
| G1 — no uninstall | T17 | uninstall.sh + README section |
| G2 — no installer tests | T10 | test_installer.py incl. GLib icon check |
| G3 — no repair command | T7 | stella doctor / install.sh --repair |
| G4 — no hicolor icon-theme install | T18 | Copies into ~/.local/share/icons/hicolor/ |
| G5 — no install log or receipt | T19 | Versions, paths, timestamp |
| G6 — no upgrade story | T22 | Documented upgrade path |
| G7 — no `--help` / usage for the scripts | T25 | Usage + exit 0 |
| D1 — unquote `Icon=`, keep `Exec` quoted | T1 | |
| D2 — render the PNGs at install time when missing | T2 | |
| D3 — ship a real double-click installer | T3 | |
| D4 — make install atomic: check before writing artifacts | T4 | |
| D5 — `run.sh`: check PySide6 before exec, fail visibly | T5 | |
| D6 — add `--timeout 120 --retries 10` to install.sh | T8 | |
| D7 — distinguish venv-failure causes; clean up only yours | T9 | |
| D8 — wrap pip failures in a Stella error | T12 | |
| D9 — disk-space preflight | T13 | |
| D10 — pin versions, or record them | T14 | |
| D11 — add `uninstall.sh` + removal docs | T17 | |
| D12 — add installer tests, including the GLib icon check | T10 | |
| D13 — add a repair/doctor path | T7 | |
| D14 — set the window icon in `gui.py main()` | T16 | |
| D15 — install icons into hicolor + render small sizes | T18 | |
| D16 — fix the README install section | T11 | |
| D17 — `run_tests.sh` must use the venv, never system pip | T6 | |
| D18 — make the success message reflect reality | T15 | |
| D19 — desktop-file polish | T23 | |
| D20 — fast path for a training re-run | T20 | |
| D21 — keep an install receipt | T19 | |
| D22 — strengthen the PySide6 check | T21 | |
| D23 — replace the pull-weights one-liner | T24 | |
| D24 — document an upgrade path | T22 | |
| D25 — `--help` for the scripts | T25 | |

**Coverage check:** 15 weaknesses + 9 UI flaws + 7 gaps + 25 design
suggestions = 56 findings. All 56 appear in the map above, each with
at least one task. 25 tasks total: 2 P0 (T1–T2), 9 P1 (T3–T11),
11 P2 (T12–T22), 3 P3 (T23–T25).

**Dependency order (within the priority order above):** T1 before
T2 (the icon must resolve before rendering it matters); T2 before
T18 (the hicolor install consumes the rendered sizes); T10 alongside
T1 (the icon-resolution test pins the P0 fix); T4 before T19 (the
receipt should record a complete install, not a failed one); T7
after T1/T2 (repair re-links a working icon, not a broken one); T17
and T7 before the README-documentation part of T11 (the install
section documents removal and repair). Folded into the merged list's
shared tasks: T1 + T2 (menu icon → merged T12, promoted to P0), T3 +
T11 (double-click installer + README install section → merged T34),
T16 (window icon → merged T69), T14 (pins → merged T73; the
record-them side is the receipt task, merged T86). U2 splits across
the README task (T11) and the success-message task (T15).
