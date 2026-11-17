#!/usr/bin/env bash
# STELLA uninstaller — run: bash uninstall.sh
# Removes the launcher, desktop copy, `stella` command, menu icons,
# venv, and install receipt. Your Stella data in ~/.stella is KEPT
# unless you ask to remove it (never deleted silently).
#
#   bash uninstall.sh              ask about ~/.stella, then remove
#   bash uninstall.sh --yes        remove, keep ~/.stella, no questions
#   bash uninstall.sh --remove-data remove everything including ~/.stella
#
# Run it with bash, never sh: it uses set -euo pipefail.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
# Resolve symlinks, so uninstalling through a link still finds this folder.
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
cd "$DIR"

REMOVE_DATA=0
YES=0
for arg in "$@"; do
  case "$arg" in
    --yes) YES=1 ;;
    --remove-data) REMOVE_DATA=1 ;;
    --help|-h)
      echo "usage: bash uninstall.sh [--yes] [--remove-data]"
      echo "  --yes          remove Stella, keep your data in ~/.stella"
      echo "  --remove-data  remove Stella and your data in ~/.stella"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg (try bash uninstall.sh --help)" >&2
      exit 1
      ;;
  esac
done

# Ask about the data BEFORE removing anything, so stopping here
# leaves the install intact. Default is No: data is never deleted
# silently, and a non-interactive run (piped stdin) keeps it.
if [ "$YES" -eq 0 ] && [ "$REMOVE_DATA" -eq 0 ]; then
  printf "Remove your Stella data in %s too? [y/N] " "$HOME/.stella"
  read -r answer || answer=""
  case "$answer" in
    y|Y|yes|YES) REMOVE_DATA=1 ;;
  esac
fi

echo "Removing Stella ..."

# R59: only remove launch artifacts that point at THIS install.
# After an upgrade, the launcher, desktop icon, and command point
# at the NEW folder — an old folder's uninstall must leave them
# alone. A launcher belongs to this install when its Exec line
# names this folder's run.sh ("$DIR/run.sh" as a fixed string, so
# a neighbouring folder like "$DIR-2" never matches); the command
# belongs to it when the symlink resolves to this folder's
# stella-cli. Anything else is left alone, with a line saying so.
# The third argument overrides the marker (the desktop training
# icon names install_training_launcher.py, not run.sh).
remove_launcher_if_ours() { # $1 = file, $2 = plain name, $3 = marker (default $DIR/run.sh)
  local file="$1" name="$2" marker="${3:-$DIR/run.sh}" other=""
  [ -e "$file" ] || return 0
  if grep -Fq "$marker" "$file" 2>/dev/null; then
    rm -f "$file"
  elif [ "$marker" = "$DIR/run.sh" ]; then
    other="$(grep '^Exec=' "$file" 2>/dev/null | head -n 1 | sed 's/^Exec="//; s|/run.sh".*$||; s|/run.sh$||')"
    if [ -n "$other" ]; then
      echo "The $name points at another install ($other), so it was left alone."
    else
      echo "The $name does not point at this install, so it was left alone."
    fi
  else
    echo "The $name does not point at this install, so it was left alone."
  fi
}
remove_launcher_if_ours "$HOME/.local/share/applications/stella.desktop" "menu launcher"
remove_launcher_if_ours "$HOME/Desktop/Stella.desktop" "desktop icon"
# The desktop training icon (v0.27.0 form names this install's
# launcher by absolute path, so ownership is checkable; the
# v0.25.0 %k form names no install and is left alone — litter
# beats breaking another install's icon).
remove_launcher_if_ours "$HOME/Desktop/Install Stella Training.desktop" "desktop training icon" "$DIR/install_training_launcher.py"
if [ -e "$HOME/.local/bin/stella" ] || [ -L "$HOME/.local/bin/stella" ]; then
  link_target="$(readlink -f "$HOME/.local/bin/stella" 2>/dev/null || true)"
  if [ "$link_target" = "$DIR/stella-cli" ]; then
    rm -f "$HOME/.local/bin/stella"
  else
    echo "The stella command points at another install (${link_target:-unknown}), so it was left alone."
  fi
fi

# Menu icons (hicolor theme, T138). The shared remover also refreshes
# the icon cache when the tool is available.
if [ -x "$DIR/.venv/bin/python" ]; then
  "$DIR/.venv/bin/python" -c "
import sys; sys.path.insert(0, '$DIR')
from stella import install as _i
from pathlib import Path as _P
_i.remove_hicolor_icons(_P.home())
" 2>/dev/null || true
else
  for size in 16 22 24 32 48 64 128 256 512; do
    rm -f "$HOME/.local/share/icons/hicolor/${size}x${size}/apps/stella.png"
  done
  if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true
  fi
fi

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
fi

rm -rf "$DIR/.venv"
rm -f "$DIR/.stella-install-receipt"

if [ "$REMOVE_DATA" -eq 1 ]; then
  rm -rf "$HOME/.stella"
  echo "Removed Stella and your Stella data in $HOME/.stella."
else
  echo "Removed Stella. Your data is still in $HOME/.stella."
fi
echo "Delete the folder $DIR to finish removing it."
