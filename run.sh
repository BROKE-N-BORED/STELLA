#!/usr/bin/env bash
# STELLA launcher — opens the Stella window. No terminal needed.
# Run it with: bash run.sh
set -euo pipefail

# T186: --help answers with usage and exits 0, without launching
# anything. Checked before DIR resolution, so nothing happens at all.
if [ "${1:-}" = "--help" ]; then
  echo "Usage: bash run.sh [--help]"
  echo "Opens the Stella window. Any other arguments are passed to"
  echo "the Stella command line (run 'stella --help' for those)."
  exit 0
fi

DIR="$(cd "$(dirname "$0")" && pwd)"
# Resolve symlinks, so launching through a link still finds this folder.
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
cd "$DIR"

# Fail visibly (T62): from the menu, with Terminal=false, the user
# sees nothing at all when the launch dies — so a failure prints a
# plain message AND, when there is no terminal to read it in, shows
# a dialog through zenity or kdialog if one is installed. Never a
# silent traceback from the menu icon.
fail_visible() { # $1 = plain message naming the fix
  echo "$1" >&2
  if [ ! -t 1 ]; then
    if command -v zenity >/dev/null 2>&1; then
      zenity --error --no-wrap --title="Stella" --text="$1" 2>/dev/null || true
    elif command -v kdialog >/dev/null 2>&1; then
      kdialog --error "$1" --title "Stella" 2>/dev/null || true
    fi
  fi
  exit 1
}

if [ -x "$DIR/.venv/bin/python" ]; then
  PY="$DIR/.venv/bin/python"
else
  fail_visible "Stella is not installed yet. Run: bash install.sh (from the Stella folder)"
fi

# PySide6 check, before exec (T62): a venv without PySide6 — the
# state after any pip failure mid-install — used to die with a raw
# ModuleNotFoundError traceback, invisible from the menu.
if ! "$PY" -c "import PySide6; from PySide6 import QtWidgets" 2>/dev/null; then
  fail_visible "Stella is not fully installed: PySide6 is missing. Run: bash install.sh (from the Stella folder)"
fi

exec "$PY" -m stella "$@"
