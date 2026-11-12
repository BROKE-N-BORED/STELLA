# STELLA v0.1 — Test Report

Verified 2026-11-12 in the sandbox (Python 3.12.3, PySide6 6.12,
offscreen Qt). Every check below was run, not assumed.

## Suite: 61/61 green

`bash run_tests.sh` (pytest, from the build tree and from a fresh unzip):

- `tests/test_model.py` — profile/project CRUD, rename (incl. the
  projects' stored profile pointer), delete, notes round-trip, slug
  validation (rejects `..`, `a/b`, spaces, dots, over-long names;
  lowercases input), metamorph mode validation, path-escape blocking.
- `tests/test_export.py` — export folder structure (manifest, config,
  README, weights placeholder, checkpoints, notes), checkpoint copy,
  existing-dir refusal, verify accepts good / rejects missing manifest,
  bad JSON, unknown metamorph mode, full round-trip into a fresh home
  (profile + project + settings + notes match), import into an existing
  profile, duplicate-project rejection.
- `tests/test_cli.py` — `profiles`, `projects`, `create-profile`,
  `create-project`, `export`, `import`, `--version`, bad-name exit 1,
  missing-project exit 1, and the CLI-through-symlink regression test.
- `tests/test_gui.py` — window opens with three panes, role + tag show
  in the profile list, detail fills from selection, save profile /
  save project write through to disk, empty-store window, no `&` in
  any visible label, window grabs a real frame, and the status bar is
  the only status surface (regression test for the duplicate-status
  fix below).
- `tests/test_ollama.py` — model list from a fake localhost Ollama
  server, empty list when Ollama is down, empty list on a bad payload.

## Fresh-unzip check

Unzipped `stella-v0.1.zip` to a clean directory: exec bits survived
extraction (`install.sh`, `run.sh`, `stella-cli`, `run_tests.sh` all
`rwxr-xr-x`), and the suite runs 61/61 green from the fresh tree.

## Installer check (sandbox, fake HOME)

`bash install.sh` from the fresh unzip: creates the private `.venv`
(installs PySide6-Essentials, passes both fatal import checks, writes
`~/.local/share/applications/stella.desktop` (absolute Exec/Icon,
quoted so install paths with spaces still launch) and a desktop copy,
links `stella` into `~/.local/bin`, exits 0. If `python3-venv` is
missing, the installer says so and names the fix
(`sudo apt install python3-venv`) instead of failing cryptically.

## Installed-app check

Through the installed `stella` command (fake HOME + fake PATH):
create profile, create project, list both, export to a folder, import
the package into a second fresh home, list again — full round-trip OK.
The GUI was driven from the installed venv (offscreen): window renders
1100x680, three panes populated, role/tag/detail all correct. The
installed screenshot is byte-identical to the build-tree screenshot.

## Defects found and fixed in place

1. `stella` CLI symlink bug: the wrapper resolved its own dir from
   `$0`, which through the `~/.local/bin/stella` symlink pointed at
   `~/.local/bin` — `python -m stella.cli` failed with
   `ModuleNotFoundError`. Fixed with symlink resolution in `stella-cli`
   (and the same hardening in `run.sh` + `install.sh`); covered by a
   regression test.
2. GUI polish from the first screenshot: Save project was below the
   fold (moved above Notes), the status line never updated on
   selection (now shows the current profile + project), profile pane
   widened for long tags.
3. Duplicate status line (found in independent verification): the
   same text showed in a bottom-bar QLabel and in the status bar.
   Removed the QLabel; the status bar is the only status surface.
   Regression test: `test_status_bar_is_the_only_status`.
4. Launcher paths unquoted (found in independent verification):
   `Exec=`/`Icon=` in the generated `.desktop` would break on install
   paths containing spaces. Now double-quoted.
5. Missing `python3-venv` failed cryptically (found in independent
   verification): the installer now catches a failed venv creation
   and names the fix (`sudo apt install python3-venv`), mirroring
   the OLLAMA-SYSTEM-TEST installer.

## Still needs Joshua's real-PC verdict

- The visible window on his Mint desktop (sandbox only proves
  offscreen rendering), Nemo double-click install, the app-menu icon.
- The Ollama tag picker against his real Ollama (sandbox used a fake
  server + the offline fallback).
- A real profile → project → export → import loop with his own data.
- PySide6 install time on his machine (one download at install).
