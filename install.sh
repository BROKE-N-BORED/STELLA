#!/usr/bin/env bash
# STELLA installer — double-click "Install Stella" or run: bash install.sh
# Installs PySide6 into a private .venv (Mint's Python is externally
# managed, so no --user pip), writes the app-menu launcher, and verifies
# the install works before reporting success.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
# Resolve symlinks, so installing through a link still finds this folder.
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
cd "$DIR"

echo "Installing Stella from $DIR ..."

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 was not found. Install Python 3 first." >&2
  exit 1
fi

# Private venv (never touches system Python).
if [ ! -x "$DIR/.venv/bin/python" ]; then
  if ! python3 -m venv "$DIR/.venv"; then
    rm -rf "$DIR/.venv"
    echo "ERROR: python3-venv is missing. Run: sudo apt install python3-venv" >&2
    echo "Then run bash install.sh again." >&2
    exit 1
  fi
fi

"$DIR/.venv/bin/python" -m pip install --quiet --upgrade pip
"$DIR/.venv/bin/python" -m pip install --quiet PySide6-Essentials

# Fatal check: the GUI toolkit must import, or the install has failed.
if ! "$DIR/.venv/bin/python" -c "import PySide6; from PySide6 import QtWidgets" 2>/dev/null; then
  echo "ERROR: PySide6 installed but cannot be imported." >&2
  echo "Try again with a network connection, or check disk space." >&2
  exit 1
fi

# App-menu launcher (absolute paths — no quoting tricks needed).
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/stella.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Stella
Comment=Fine-tune models on your own PC
Exec="$DIR/run.sh"
Icon="$DIR/assets/stella.png"
Terminal=false
Categories=Utility;
StartupWMClass=Stella
EOF

# Desktop copy for double-click launch from the desktop too.
cp "$HOME/.local/share/applications/stella.desktop" "$HOME/Desktop/Stella.desktop" 2>/dev/null || true
chmod +x "$HOME/Desktop/Stella.desktop" 2>/dev/null || true

# Command line: `stella` on PATH after install.
mkdir -p "$HOME/.local/bin"
ln -sf "$DIR/stella-cli" "$HOME/.local/bin/stella"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
fi

# Final check: Stella itself must import.
if ! "$DIR/.venv/bin/python" -c "import stella; print(stella.__version__)" 2>/dev/null; then
  echo "ERROR: Stella did not import after install." >&2
  exit 1
fi

echo "Stella is installed. Open it from the app menu (Stella) or"
echo "double-click Stella on the desktop. No terminal needed."
echo "Command line is available too: stella profiles"
