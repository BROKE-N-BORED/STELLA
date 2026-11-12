# Changelog

## v0.1 — 2026-11-12

First skeleton. No training engine yet (Item 3).

- Profiles with friendly role names, Ollama tag picker (works offline
  when Ollama is down), full create/rename/delete.
- Projects inside profiles: dataset ref, training settings, MetaMorphAi
  mode (morph / compress / both), checkpoints dir, notes.
- Export a project as a folder (manifest, config, README, weights,
  checkpoints) and import it back with verification.
- Native Qt window: profiles left, projects middle, detail right.
- CLI: profiles, projects, export, import, create-profile,
  create-project.
- Installer: private venv, app-menu launcher with star icon, desktop
  icon, `stella` command on PATH.
- Verification fixes (same day): status text shown once, in the
  status bar only (a duplicate label was removed); launcher Exec/Icon
  quoted so install paths with spaces work; installer names the
  `sudo apt install python3-venv` fix if the venv module is missing.
