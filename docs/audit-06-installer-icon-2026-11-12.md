# STELLA Audit #6 — Installer + icon

**Date:** 2026-11-12 (evening)
**Against:** the v0.2 tree at `~/workspace/stella/` (commit 9a821e07)
and the shipped zip `stella-v0.2.zip` (207,391 B,
SHA-256 `7c3106c9791f1c3e3acf2e5c5eefe557a2c9dececcae8acd5e6de1c64c487096`).
**Scope:** component #6 of 7 — `install.sh`, `install-training.sh`,
`run.sh`, `stella-cli` (installer side only; audit #5 covered the
wrapper's resolution behavior), `render_icon.py`, the icon assets, the
generated `.desktop` file, `run_tests.sh` (installer-adjacent), and the
README's install story. The training engine, GUI, and CLI internals are
other audits' territory.

**This file is a list only.** Nothing here has been fixed or built.

**Counts:** 15 weaknesses, 9 UI flaws, 7 gaps, 25 design suggestions
= **56 findings**. Priorities: 2 P0, 9 P1, 15 P2, 5 P3 (§8).

---

## 1. Scope and method

### Read in full

- `install.sh` (86 lines), `install-training.sh` (45),
  `run.sh` (29), `stella-cli` (30), `render_icon.py` (31),
  `run_tests.sh` (30)
- `assets/stella.svg` (1,303 B) and the five PNGs
  (64/128/256/512 + `stella.png`, a byte-copy of the 256)
- `stella/gui.py` `main()` (app name / window icon),
  `stella/__init__.py`, `drive_gui.py` (dev tool, not in the zip)
- `README.md` (install sections), `CHANGELOG.md`,
  `TEST-REPORT.md` (installer + installed-app sections)
- Audits #1–#5, for format and for cross-referenced findings
  (audit #5's wrapper coverage was re-verified only where the
  installer side changes it)

### Probes (all live, all with real runs)

Scratch HOMEs under `/tmp/stella-audit06/home*` (never the real `~`,
never the real `~/.local/share/applications`); install dirs under
`~/workspace/stella-audit06/` (workspace disk — `/tmp` is a 512 MB
tmpfs and pip's unpack temp dies there). Qt env from AGENTS.md for the
PySide6 import checks. Every probe below names its exit code and its
exact output where it matters.

| # | Probe | Result |
|---|---|---|
| P1 | Fresh-unzip install: unzip the v0.2 zip, `bash install.sh` | Exit 0, 57 s, `.venv` 259 MB; desktop file + `stella` symlink written; no `~/Desktop` in scratch HOME → no desktop copy, silently |
| P1b | Installed-app check: `stella profiles` / create / list via PATH; `bash run.sh` from `/tmp`, offscreen | All exit 0; run.sh still running at the 25 s timeout (window open). PySide6 import AND `QApplication` creation both work WITHOUT the extracted Qt libs in this sandbox |
| P2 | Fresh-CLONE install: tree copy with `assets/*.png` deleted | Exit 0, "Stella is installed" — while the desktop file's Icon points at a file that does not exist |
| P3 | Re-install over the P1 install | Exit 0, 30 s, artifacts rewritten |
| P4 | Install into a path with SPACES; `gio launch` the desktop file | Exit 0; `gio launch` exit 0 and two `python -m stella` processes observed running |
| P5 | Missing `python3-venv`, via a PATH shim whose `python3 -m venv` fails like ensurepip-missing | Exit 1, exact message `ERROR: python3-venv is missing. Run: sudo apt install python3-venv`; `.venv` cleaned up |
| P6 | `.venv` exists as a stray FILE | Exit 1 — but the message is the python3-venv one (wrong diagnosis); the stray file was deleted by the cleanup `rm -rf` |
| P7a | `run.sh`, no venv | Clean message, exit 1 |
| P7b | `run.sh`, venv present but PySide6 absent | Raw `ModuleNotFoundError: No module named 'PySide6'` traceback, exit 1 |
| P7c | `stella-cli`, no venv | Works via the system-python3 fallback, exit 0 (audit #5 re-verified) |
| P8 | Sabotaged final import check (`stella/__init__.py` raises) | Exit 1, `ERROR: Stella did not import after install.` — desktop file AND `stella` symlink left behind |
| P9a | `install-training.sh`, no base install | Clean message, exit 1 |
| P9b | `install-training.sh` run TWICE, via a `--dry-run` scratch copy against the real train venv | Exit 0, `torch 2.15.0+cpu` — idempotent, but took 148 s doing nothing |
| P9c | `install-training.sh`, dead torch index (scratch copy, `127.0.0.1:9`) | Still in pip's retry loop at the 180 s probe timeout (exit 124); raw pip WARNING lines only, no Stella message; pip's final failure was NOT observed |
| P10 | Icon eyeball: render the SVG at 16/32/48 with QtSvg, view the 256 PNG | Star legible at 16 px; PNG dims verified (64/128/256/512 + 256 default) |
| P11 | `run_tests.sh` on a bare checkout, system python3 | Exit 1, `externally-managed-environment` |
| P12 | Move the installed folder, then launch | `gio launch` exit 1; `stella` → command not found (127, dangling symlink); `run.sh` from the new location works (timeout 124) |
| P13 | GLib ctypes probe: ask libgio how it parses the generated desktop file | Quoted `Icon=` returns the path WITH literal quotes — does not exist. Unquoted control (plain and spaced paths) and unquoted SVG both resolve. `Exec` commandline correct; `executable` field truncates at the space |
| P14 | `stella` on PATH | Login shell has `~/.local/bin` on PATH in this sandbox — but only because the dir existed at login; the mechanism is login-time |
| P15 | Zip-vs-tree drift | `diff -rq` (excluding docs, `__pycache__`): only `drive_gui.py` differs. Stored modes correct (scripts `0o100755`). Zip SHA matches |

### What I could not test

- `desktop-file-validate` is not installed in the sandbox (and neither
  are `gtk-launch` or `update-desktop-database`); `gio` is. The GLib
  ctypes probe (P13) is the authority on desktop-file parsing instead.
- No Cinnamon/Nemo session exists here, so the menu icon's *appearance*
  was judged through GLib's own icon resolution, not by looking at a
  menu. Nemo double-click behavior (what double-clicking `install.sh`
  actually does) is likewise unprobed — the finding is that the
  double-click *target* the README names does not exist, which needs no
  desktop session to establish.
- The real 2 GB training install was not re-downloaded (P9b dry-ran
  against the existing train venv); the dead-network failure's tail
  (pip's final error + the script's exit code) was not observed — the
  retry loop outlasted the 180 s probe timeout.
- His Mint PC's `~/.profile` PATH behavior was not probed on his
  machine; the sandbox login shell was (P14).
- WM_CLASS was not probed (no `xprop`); `StartupWMClass=Stella`
  matches `setApplicationName("Stella")` by code reading.

### Probe-environment notes (not Stella findings)

- My first P1 attempt failed with pip `ENOSPC` because the probe's own
  `TMPDIR`/`PIP_CACHE_DIR` pointed at the 512 MB tmpfs (a `~`-expansion
  mistake after exporting the scratch HOME). The retry in the same
  directory completed — which incidentally proved re-running after a
  failed pip install recovers (see Strengths). A second ENOSPC, from a
  216 MB stale `pip-unpack-*` dir in `/tmp`, was cleaned the same way.
- `pkill -f stella` once matched the probe shell's own command line
  (the known self-match trap); stray Stella processes were then killed
  by PID. All probe processes were stopped before this report was
  written.

---

## 2. Features and functions

What the installer + icon do today:

- **`install.sh`** — creates a private `.venv` (never touches system
  Python), upgrades pip, installs `PySide6-Essentials`, runs two fatal
  import checks (PySide6; `stella` itself), writes
  `~/.local/share/applications/stella.desktop` (absolute, quoted
  Exec/Icon), copies it to `~/Desktop/Stella.desktop`, symlinks
  `~/.local/bin/stella` → `stella-cli`, runs `update-desktop-database`
  if present. Names the `sudo apt install python3-venv` fix when venv
  creation fails. Symlink-resolves its own location.
- **`install-training.sh`** — refuses cleanly without a base install;
  installs `torch` (CPU index) + `transformers peft accelerate` with
  `--timeout 120 --retries 10`; fatal import check; prints the torch
  version + a pull-weights hint.
- **`run.sh`** — venv python or a clean "not installed" message;
  `exec python -m stella`. Symlink-resolves, works from any directory.
- **`stella-cli`** — venv python, else system `python3` fallback
  (audit #5).
- **`render_icon.py`** — renders the SVG to 512/256/128/64 PNGs with
  QtSvg and copies the 256 as `stella.png`. Build-time only — nothing
  invokes it (W2).
- **Icon** — gold 4-point star, violet halo, navy rounded field,
  small sparks (SVG source + 5 PNGs in the zip; SVG only in the repo —
  the push cannot carry binaries).
- **`run_tests.sh`** — pytest + PySide6 bootstrap, then the suite.

---

## 3. Strengths

1. **The happy path works end to end, for real.** Fresh-unzip install
   exits 0 in under a minute (warm cache), both fatal import checks
   pass, the desktop file and symlink land, `stella profiles` /
   create / list round-trip through the installed command, and `run.sh`
   opens the window (P1, P1b).
2. **Recovery after a failed install works.** The ENOSPC failure above
   left a partial venv; re-running `install.sh` reused it and finished
   clean. Re-install over a good install is idempotent too (P3, exit 0).
3. **Spaced install paths work for install AND launch.** The v0.1
   quoting fix holds for `Exec`: install into `spaced dir` exits 0 and
   `gio launch` starts the app from there (P4). (The same quoting
   breaks `Icon` — W1.)
4. **The python3-venv guard works and names the fix.** The shim probe
   (P5) produced exactly `ERROR: python3-venv is missing. Run: sudo
   apt install python3-venv`, exit 1, with the partial `.venv` cleaned
   up. The v0.1 defect fix is present and correct.
5. **The training installer's guards are clean.** No base install →
   plain message, exit 1 (P9a). A second run is idempotent (P9b, exit 0,
   `torch 2.15.0+cpu`). The `--timeout 120 --retries 10` flags from the
   v0.2 fix are present on both pip lines (verified in the file).
6. **`run.sh` fails cleanly when nothing is installed** (P7a) and works
   from any directory (P1b). The `stella-cli` system-python fallback
   means the CLI works before install (P7c, audit #5 re-verified).
7. **The zip is clean.** Stored modes are correct (scripts `0o100755`,
   plain files `0o100644`); zip-vs-tree diff shows only the dev tool
   `drive_gui.py` (P15); the zip SHA matches the shipped file.
8. **The icon artwork is good and survives downscaling.** Eyeballed at
   16/32/48 px (QtSvg renders) and at 256 px (the shipped PNG): the
   gold star reads clearly at every size, including 16 px, where the
   small sparks become dots but the star itself stays legible.
9. **Private venv, no system-Python writes.** The installer never runs
   `pip install --user` or touches system Python — the Mint
   EXTERNALLY-MANAGED trap is avoided in the installer itself (it
   survives in `run_tests.sh` — W6).
10. **`StartupWMClass=Stella` matches `setApplicationName("Stella")`**
    (`gui.py:925`), so the running window associates with the launcher.
11. **Small guards are in place:** `update-desktop-database` is
    `command -v`-guarded, the Desktop copy tolerates failure
    (`|| true`), all four scripts symlink-resolve their own location.

---

## 4. Weaknesses

### W1 — The quoted `Icon=` breaks the menu icon on EVERY install (P0)

`install.sh` writes `Icon="$DIR/assets/stella.png"` — quoted, the
same treatment as `Exec`. But quoting is only defined for `Exec` in
the desktop-entry spec; `Icon` is a plain string, and GLib takes the
quotes literally. Probed with ctypes against libgio itself (P13),
on the generated file from the fresh-unzip install:

```
icon string: '"/home/hatch/workspace/stella-audit06/fresh/stella/assets/stella.png"'
icon path exists as-is: False
icon path exists stripped of quotes: True
```

The spaced-path install gives the same result. The unquoted control
resolves (`exists as-is: True`) — including on the spaced path, so
spaces are not a reason to quote `Icon`. The menu entry therefore
shows a generic icon on every install, zip or clone, spaced or not.

This is the v0.1 quoting fix backfiring: it was verified by *reading*
the generated file ("quoted so install paths with spaces still
launch" — TEST-REPORT.md), never by asking GLib what the icon
resolves to. The launch half is true (`Exec` quoting is spec-defined
and `gio launch` works); the icon half is false. The README's "puts
Stella in the app menu with its star icon" does not hold on any
install, and the real-PC verdict that would have caught it is still
open.

Secondary effect from the same probe: `g_app_info_get_executable`
truncates at the space on a spaced install — it returned
`"/home/hatch/workspace/stella-audit06/spaced` — while
`g_app_info_get_commandline` is correct. Launching works (it uses the
commandline), but anything matching on the executable path sees a
wrong value.

### W2 — A fresh-clone install silently ships a broken icon; nothing ever renders the PNGs (P0)

The GitHub push cannot carry binary PNGs, so the repo has the SVG
source but no rendered PNGs. `install.sh` never calls
`render_icon.py` (0 mentions in any script, program, or README) and
never checks the icon file exists. Probed (P2): a tree copy with
`assets/*.png` deleted installed with exit 0 and printed "Stella is
installed", while the desktop file points at
`.../assets/stella.png`, which does not exist — and the assets dir
still held only `stella.svg` afterwards.

This is the MIMIK v0.2 trap in Stella's form: MIMIK's installer died
in its icon loop under `set -e` before writing the launcher; Stella's
installer has no icon step at all, so it *succeeds* and silently
ships a broken menu icon. `render_icon.py` is orphaned — it exists,
it works (QtSvg is available in the installed venv, probed), and
nothing invokes it. Even with W1 fixed, a clone install still has no
icon file at all.

### W3 — No double-click installer exists, but the README and install.sh promise one (P1)

README.md:21: "Unzip a release anywhere, then double-click **Install
Stella** in the folder". `install.sh:2` says the same. There is no
`Install Stella` file: `find` over the tree and the zip listing both
show no `.desktop` file anywhere (only `install.sh` and
`install-training.sh`). Double-clicking `install.sh` itself in Nemo
opens a text editor (or a run prompt) — it does not install. The
documented first step for the user who hand-types commands from his
phone does not exist; the only working path is a terminal and
`bash install.sh`. (SKULLPT v1.2 shipped a real
`Install-SKULLPT.desktop` for exactly this reason.)

### W4 — A failed install leaves a working-looking menu launcher and `stella` command (P1)

The desktop file and the `~/.local/bin/stella` symlink are written
*before* the final `import stella` check. Probed (P8): with
`stella/__init__.py` sabotaged to raise, install exited 1 with
`ERROR: Stella did not import after install.` — and both artifacts
were on disk. The menu entry exists, clicking it runs `run.sh` into a
crash that is invisible (`Terminal=false`), and `stella` runs a
broken tree. The install is not atomic: failure is reported, but the
half-installed state looks installed.

### W5 — `run.sh` with a venv but no PySide6 is a raw traceback — invisible from the menu (P1)

Probed (P7b): venv present, PySide6 absent →

```
File ".../stella/gui.py", line 21, in <module>
    from PySide6.QtCore import Qt, QThread, Signal
ModuleNotFoundError: No module named 'PySide6'
```

exit 1, no Stella message. This is the state after any pip failure
mid-install (W11) — and exactly the failure SKULLPT v1.1 hit on his
PC (`run.sh` failed, PySide6 missing, Bench never opened). From the
menu, with `Terminal=false`, the user sees nothing at all: the window
just doesn't open, with no error anywhere.

### W6 — `run_tests.sh` cannot run on a bare checkout on Mint (P1)

When no `.venv` exists it falls back to system `python3` and runs
`"$PY" -m pip install --quiet pytest` (and PySide6-Essentials) into
system Python. Probed (P11) on this sandbox's Python 3.12.3 — the
same version as his Mint PC, also externally managed:

```
Installing pytest for the test run...
error: externally-managed-environment
```

exit 1. TEST-REPORT defect #3 claims the bare-checkout path was fixed
("it now installs PySide6-Essentials when the import fails, so the
suite runs from a fresh unzip") — but the mechanism installs into
system Python, which Mint forbids. The documented `bash run_tests.sh`
only works after `install.sh` has made the venv.

### W7 — Moving or renaming the install folder breaks the launcher and the `stella` command, silently (P1)

Everything install.sh writes is an absolute path to `$DIR`. Probed
(P12): after `mv moveme moved-to`, `gio launch` on the desktop file
exited 1 (`Unable to load application information`), `stella` became
`command not found` (exit 127, dangling symlink) — while `run.sh`
from the new location works fine (timeout 124), because it resolves
its own dir. Re-running `install.sh` from the new location would
repair it, but nothing says so anywhere; the user is left with a dead
menu entry and a dead command.

### W8 — `install.sh`'s pip lines have no `--timeout`/`--retries` (P1)

`install-training.sh` got `--timeout 120 --retries 10` as a v0.2 fix
because "pip's default 15s read timeout repeatedly failed the torch
download" (TEST-REPORT defect #4). `install.sh:36-37` still runs
plain `--quiet` pip installs — for a ~90 MB PySide6-Essentials wheel
on the same slow connection. The base install can fail exactly the
way the training install used to. (Code reading + the v0.2 defect
record; not live-probed with a throttled connection.)

### W9 — Every venv failure is misdiagnosed as "python3-venv is missing" (P1)

Any failure of `python3 -m venv` prints the same message, whatever
the cause. Probed (P6): `.venv` existing as a stray file made venv
creation fail with `Error: Unable to create directory
'.../.venv'` — and the installer printed `ERROR: python3-venv is
missing. Run: sudo apt install python3-venv`. Disk-full, permissions,
or a broken pre-existing venv dir would all get the same wrong
advice, sending the user to install a package they already have.

### W10 — The venv-failure cleanup deletes whatever sits at `.venv` (P2)

`rm -rf "$DIR/.venv"` runs on *any* venv-creation failure, before the
error message. Probed (P6): it deleted the stray file that was in the
way. The cleanup does not check that `.venv` is a venv, or that this
run created it. A file (or anything else) a user or another tool put
at that path is destroyed without asking.

### W11 — Pip failures surface as raw pip output, with no Stella message (P2)

Both installers run pip bare under `set -e`, so a pip failure exits
at the pip line and the friendly fatal checks never run. Probed
twice: ENOSPC during the PySide6 install → raw `ERROR: Could not
install packages due to an OSError: [Errno 28] No space left on
device`, exit 1, no Stella line; dead torch index (P9c) → 180+ seconds
of pip `WARNING: Retrying ...` lines, no Stella message at all. The
user gets pip's diagnostics, not Stella's.

### W12 — No disk-space check anywhere (P2)

Neither installer checks free space before downloading (~90 MB wheel
/ 259 MB installed for the base; ~2 GB for training). The only
"disk space" strings in the scripts are inside the post-failure error
messages. On his 1 TB HDD this is unlikely to bite, but the failure
mode is a mid-download ENOSPC with raw pip output (probed in
miniature in P1's first attempt).

### W13 — No version pins (P2)

`pip install PySide6-Essentials`, `torch`, `transformers`, `peft`,
`accelerate` are all unpinned. The train venv happens to hold torch
2.15.0+cpu / transformers 5.22.2 / peft 0.21.2 / accelerate 1.15.0
because of when it was built, not because the script says so. A
future release can change behavior under the same installer, and
nothing records which versions an install actually got.

### W14 — A training re-run takes ~2.5 minutes even when everything is installed (P2)

The P9b dry-run probe — same packages, same versions, nothing to do —
took 148 s: pip re-resolves the torch CPU index on every run, and the
script prints nothing between the header and the torch version line
(`--quiet`). A no-op second run looks like a hang.

### W15 — The PySide6 import check cannot catch a broken GUI start (P2)

The fatal check is `import PySide6; from PySide6 import QtWidgets`
with stderr hidden (`2>/dev/null`), and its error message names only
"a network connection, or ... disk space". An import succeeds even
where creating a window would fail (e.g. missing system GL/EGL libs),
and that failure's real cause would be swallowed. **Not reproduced in
this sandbox** — `QApplication` creation worked without the extracted
Qt libs (P1b) — so this is code reading only, stated as a weakness of
the check's diagnosis, not as an observed failure.

---

## 5. UI flaws

### U1 — The README's install paragraph promises things that don't exist (P1)

Two false claims in the first install paragraph: "double-click
**Install Stella**" (no such file — W3) and "puts **Stella** in the
app menu with its star icon" (the icon is broken by W1 on every
install, absent by W2 on a clone). The doc face of W1/W2/W3.

### U2 — "`stella` on PATH" is conditional, and the installer doesn't say so (P2)

`install.sh` ends with "Command line is available too: stella
profiles". `~/.local/bin` joins PATH at login (Mint's `~/.profile`
adds it only if the dir exists at login time). A terminal already open
at install time — or a first install where `~/.local/bin` didn't exist
at login — won't find `stella` until logout/login. Probed (P14): a
fresh login shell in this sandbox HAS `~/.local/bin` on PATH, but
that proves the mechanism, not the claim — the claim holds only for
terminals opened after a login where the dir existed.

### U3 — The Desktop copy is silently skipped when `~/Desktop` doesn't exist (P2)

`cp ... "$HOME/Desktop/Stella.desktop" 2>/dev/null || true`. Probed
(P1): scratch HOME with no `Desktop` dir → no copy, no message. On
Mint `~/Desktop` exists, so this bites only on a renamed/localized
Desktop folder — but then the success message's desktop claim is
false, silently.

### U4 — The success message claims things unconditionally (P2)

"double-click Stella on the desktop. No terminal needed." prints even
when the desktop copy was skipped (U3), and the whole success block
prints even though the menu icon is broken (W1). The message describes
the intended install, not the one that landed.

### U5 — The running window has no icon (P2)

No `setWindowIcon` / `QIcon` anywhere in the tree (grep). The window,
taskbar, and alt-tab show Qt's generic icon even though a star icon
sits in `assets/`. The `.desktop` icon (once W1 is fixed) covers the
menu, not the running window.

### U6 — No 16/32/48 px icon files are shipped (P3)

`assets/` holds only 64/128/256/512 + `stella.png` (256). The desktop
environment scales the 256 down, and the eyeball probe (P10) shows the
star stays legible at 16 px — so this is polish, not a defect. A
purpose-rendered small set would be crisper in panels and trays.

### U7 — Desktop-file polish is missing (P3)

The generated entry has no `StartupNotify=true` (no launch feedback
in the panel), no `Keywords` (no search terms in the menu), no
`Version=1.0`. All optional; all absent.

### U8 — The install log prints a bare "0.2" (P3)

The final check runs `import stella; print(stella.__version__)`, so
the install output contains a lone `0.2` line between "Installing
Stella from ..." and the success message — a version number with no
label, looking like stray output.

### U9 — The pull-weights hint is a long quoted one-liner to type by hand (P3)

`install-training.sh` ends by printing
`$DIR/.venv/bin/python -c "from huggingface_hub import
snapshot_download; snapshot_download('LiquidAI/LFM3-1.7B')"` — a long
line with nested quotes, for a user who hand-types commands from his
phone screen. The alternative (let the first run download) is printed
too, which softens it.

---

## 6. Gaps

### G1 — No uninstall (P2)

No `uninstall.sh`, no removal instructions anywhere (grep: zero
mentions outside one test comment). Removing Stella means hand-deleting
the folder, `~/.local/share/applications/stella.desktop`,
`~/Desktop/Stella.desktop`, `~/.local/bin/stella`, and deciding about
`~/.stella` — and nothing tells the user the list.

### G2 — No installer tests (P1)

No `test_installer.py`; the only test references to the installers
assert that error messages *name* `install-training.sh`
(`test_cli.py:119,160`, `test_gui.py:121`, `test_train.py:236`). The
installer is verified only by the manual fresh-unzip check in
TEST-REPORT.md — which is how W1 survived: the manual check read the
desktop file but never asked GLib what the icon resolves to.

### G3 — No repair command (P2)

After a move (W7) or a broken venv (W5), the only recovery is
re-running `install.sh` — which works, but nothing says so, and there
is no `--check`/`doctor` mode that verifies the launcher, symlink,
icon, and venv and fixes what's stale.

### G4 — No hicolor icon-theme install (P2)

The icon is referenced by absolute path from the install dir instead
of installed into `~/.local/share/icons/hicolor/`. A theme install
(copies, not references) would survive a folder move for the icon,
and is where size variants belong.

### G5 — No install log or receipt (P2)

Nothing records what an install did — PySide6/torch versions, where
the artifacts went, when it ran. When something breaks later, there
is no record to send Arlo. (The BNB debug-log-layer direction covers
this class of gap for project builds generally; here it is just a
missing artifact.)

### G6 — No upgrade story (P2)

v0.1 → v0.2 means unzipping a new folder and installing from scratch.
Re-installing over the *same* folder is idempotent (P3), but a new
folder leaves the old install orphaned — old venv (~259 MB), old
launcher repointed only if the user runs the new `install.sh` — and
nothing documents the upgrade steps or cleans up the old copy.

### G7 — No `--help` / usage for the scripts (P3)

`bash install.sh --help` just installs; the scripts ignore arguments
entirely. Minor — but the first thing a careful user types is
`--help`.

---

## 7. Design suggestions (priority order)

**P0 — fix first**

- **D1 — Unquote `Icon=`, keep `Exec` quoted.** (W1) One line in
  `install.sh`. The GLib probe (P13) proves unquoted `Icon` resolves
  on plain and spaced paths alike; `Exec` quoting is spec-defined and
  stays. Verify the fix with the same ctypes probe — or better, make
  the probe a test (D12).
- **D2 — Render the PNGs at install time when they're missing.**
  (W2) After the venv exists, if `assets/stella.png` is absent, run
  `render_icon.py` — QtSvg is available in the installed venv
  (probed). Fallback, also probed: point `Icon=` at the SVG itself
  unquoted — GLib resolves it. Either way, never write a desktop file
  whose icon doesn't exist; check the file before writing.

**P1 — functional defects**

- **D3 — Ship a real double-click installer.** (W3) An
  `Install-Stella.desktop` in the zip that runs `install.sh` in a
  terminal (SKULLPT v1.2 did this), or fix the README to tell the
  terminal truth. The README's first install step must name a file
  that exists.
- **D4 — Make install atomic: check before writing artifacts.**
  (W4) Move the final `import stella` check before the desktop file
  and symlink are written — or roll the artifacts back on failure. A
  failed install must leave no launcher behind.
- **D5 — `run.sh`: check PySide6 before exec, and fail visibly.**
  (W5) If the import fails, print the plain "run `bash install.sh`"
  message instead of a traceback. With `Terminal=false`, consider a
  `zenity`/`kdialog` fallback so a menu-launch failure is visible at
  all.
- **D6 — Add `--timeout 120 --retries 10` to install.sh's pip lines.**
  (W8) Same fix as install-training.sh already has.
- **D7 — Distinguish venv-failure causes; clean up only what you made.**
  (W9, W10) Check `python3 -c "import venv, ensurepip"` first and
  print the `python3-venv` message only when the module is actually
  missing; otherwise print the real venv error. Only `rm -rf` a
  `.venv` this run created (or one that looks like a venv).
- **D12 — Add installer tests, including the GLib icon check.**
  (G2) A `test_installer.py` that runs `install.sh` in a scratch
  HOME and asserts: the desktop file parses, the icon resolves via
  GLib, the symlink works, re-install is idempotent, a clone without
  PNGs renders or warns. The icon-resolution check is the one that
  would have caught W1.
- **D17 — `run_tests.sh` must use the venv, never system pip.**
  (W6) Create/use `.venv` for the test run, or refuse on a bare
  checkout with "run `bash install.sh` first". Never
  `pip install` into system Python on Mint.
- **D13 — Add a repair/doctor path.** (W7, G3) A `stella doctor`
  (or `install.sh --repair`) that verifies venv, PySide6, launcher,
  symlink, and icon, and re-links what's stale after a move.
- **D16 — Fix the README install section.** (U1, U2, W3-doc) Name a
  real first step, qualify the `stella` command ("open a new terminal
  after install, or log out and back in"), document removal (D11) and
  move/repair (D13).

**P2 — missing capabilities and inconsistencies**

- **D8 — Wrap pip failures in a Stella error.** (W11) On a pip exit
  != 0, print a plain line naming the step ("PySide6 download failed
  — check your connection and run `bash install.sh` again") instead
  of leaving raw pip output as the last word.
- **D9 — Disk-space preflight.** (W12) Check free space before
  downloading (~500 MB base, ~3 GB training) and refuse plainly when
  it won't fit.
- **D10 — Pin versions, or record them.** (W13, G5) Pin
  `PySide6-Essentials`, `torch`, `transformers`, `peft`, `accelerate`
  to the verified versions — or at minimum write the installed
  versions into an install receipt (D21).
- **D20 — Fast path for a training re-run.** (W14) Check the imports
  first; if torch/transformers/peft/accelerate already import, print
  "training packages already installed" and exit 0 without
  re-resolving the index.
- **D22 — Strengthen the PySide6 check.** (W15) Create a throwaway
  `QApplication` offscreen instead of import-only, and surface the
  real stderr on failure so a missing system lib names itself.
- **D18 — Make the success message reflect reality.** (U3, U4, U8)
  Claim the desktop icon only if the copy landed; claim `stella`
  only if `~/.local/bin` is on PATH (or say to open a new terminal);
  label the version line (`Stella 0.2`).
- **D14 — Set the window icon in `gui.py main()`.** (U5)
  `QIcon` from `assets/stella.png`, guarded if the file is missing,
  so the running window shows the star.
- **D11 — Add `uninstall.sh` + a removal section in the README.**
  (G1) Remove launcher, desktop copy, symlink, venv; ask about
  `~/.stella` data (never delete it silently).
- **D15 — Install icons into the hicolor theme + render small sizes.**
  (U6, G4) Copy the PNGs (and 16/22/24/32/48 renders from
  `render_icon.py`) into `~/.local/share/icons/hicolor/`.
- **D21 — Keep an install receipt.** (G5) Versions, paths, and
  timestamp in the tree (and/or `~/.stella/`), so a broken install
  can be reported with facts.
- **D24 — Document an upgrade path.** (G6) "Unzip the new version,
  run its `install.sh`, delete the old folder" — or make install.sh
  detect and offer to remove a previous install's venv.

**P3 — polish**

- **D19 — Desktop-file polish.** (U7) `StartupNotify=true`,
  `Keywords`, `Version=1.0`.
- **D23 — Replace the pull-weights one-liner.** (U9) A
  `stella pull-weights <repo>` command, or a shorter hint — nothing
  the user has to hand-type with nested quotes.
- **D25 — `--help` for the scripts.** (G7) Print usage and exit 0
  instead of ignoring arguments.

---

## 8. Prioritized recommendations

| Priority | Items | What it fixes |
|---|---|---|
| **P0** | W1 (D1), W2 (D2) | The menu icon: broken on every install by the quotes, absent on a clone because nothing renders it. Both are silent — the install reports success either way |
| **P1** | W3 (D3), W4 (D4), W5 (D5), W6 (D17), W7 (D13), W8 (D6), W9 (D7), G2 (D12), U1 (D16) | The documented install path doesn't exist; failed installs leave launchers; broken venvs fail invisibly; the test script can't run on a bare checkout; moves break everything; pip timeouts and venv misdiagnosis; no installer tests |
| **P2** | W10 (D7), W11 (D8), W12 (D9), W13 (D10), W14 (D20), W15 (D22), U2 (D16/D18), U3 (D18), U4 (D18), U5 (D14), G1 (D11), G3 (D13), G4 (D15), G5 (D21), G6 (D24) | Destructive cleanup, raw pip errors, no disk check, no pins, slow no-op re-runs, weak GUI check, conditional PATH claims, silent desktop skip, unconditional success message, no window icon, no uninstall/repair/theme install/receipt/upgrade |
| **P3** | U6 (D15), U7 (D19), U8 (D18), U9 (D23), G7 (D25) | Small icon sizes, desktop-file polish, bare version line, typed one-liner, `--help` |

**Dependency order (within the priority order above):** D1 before D2
(the icon must resolve before rendering it matters); D2 before D15
(the hicolor install consumes the rendered sizes); D12 alongside D1
(the icon-resolution test pins the P0 fix); D4 before D21 (the
receipt should record a complete install, not a failed one); D13
after D1/D2 (repair re-links a working icon, not a broken one).

**Cross-references to earlier audits:** audit #5 covered the
`stella-cli` wrapper's `.venv` detection, symlink resolution, and cwd
behavior — re-verified where the installer side touches it (P7c, P1b)
and not re-probed from scratch. Audit #5's W2 (raw tracebacks from
`main()`) is the same class as W5/W11 here (raw errors instead of
Stella messages) but in different code. Audit #4's W9/W10 (jobs
running together, close-during-job) do not touch the installer.
No earlier audit covered the installer or the icon.

**Coverage check:** 15 weaknesses + 9 UI flaws + 7 gaps + 25 design
suggestions = 56 findings. Every W/U/G maps to at least one D (§7);
every D names the finding(s) it addresses.
