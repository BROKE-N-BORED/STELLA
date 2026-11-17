#!/usr/bin/env bash
# STELLA installer — double-click "Install Stella" or run: bash install.sh
# Installs PySide6 into a private .venv (Mint's Python is externally
# managed, so no --user pip), writes the app-menu launcher, and verifies
# the install works before reporting success.
#
# Run it with bash, never sh: it uses set -euo pipefail and bash arrays.
set -euo pipefail

# T186: --help answers with usage and exits 0, without installing
# anything. Checked before DIR resolution, so nothing happens at all.
if [ "${1:-}" = "--help" ]; then
  echo "Usage: bash install.sh [--help]"
  echo "Installs Stella: a private .venv with PySide6, the app-menu"
  echo "launcher, and the 'stella' command. No training packages —"
  echo "run bash install-training.sh for those."
  exit 0
fi

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

# The receipt records a COMPLETE install (T139): drop any stale one
# up front, so a failed install leaves no receipt behind (T63).
rm -f "$DIR/.stella-install-receipt"

# Disk-space preflight (T133): the base install needs about 500 MB
# (a ~90 MB wheel, ~259 MB installed, plus headroom). Refuse plainly
# before downloading anything when it will not fit.
# STELLA_INSTALL_MIN_FREE_KB overrides the threshold (tests use it).
MIN_FREE_KB="${STELLA_INSTALL_MIN_FREE_KB:-512000}"
AVAIL_KB="$(df -k --output=avail "$DIR" 2>/dev/null | tail -n 1 | tr -d ' ')"
case "$AVAIL_KB" in
  ''|*[!0-9]*) AVAIL_KB="" ;;  # df failed or gave junk: do not block on it
esac
if [ -n "$AVAIL_KB" ] && [ "$AVAIL_KB" -lt "$MIN_FREE_KB" ]; then
  NEED_MB="$((MIN_FREE_KB / 1024))"
  HAVE_MB="$((AVAIL_KB / 1024))"
  echo "ERROR: not enough free disk space to install Stella." >&2
  echo "Stella needs about ${NEED_MB} MB free; this disk has about ${HAVE_MB} MB." >&2
  echo "Free some space and run bash install.sh again." >&2
  exit 1
fi

# Private venv (never touches system Python).
# T42: distinguish the failure causes. The python3-venv message is
# printed ONLY when the venv module is actually missing; any other
# failure prints the real venv error. And cleanup touches only a
# .venv this run created: a stray file (or anything else) that was
# already at .venv is never deleted.
VENV_PREEXISTED=0
[ -e "$DIR/.venv" ] && VENV_PREEXISTED=1
if [ ! -x "$DIR/.venv/bin/python" ]; then
  if ! python3 -c "import venv, ensurepip" 2>/dev/null; then
    echo "ERROR: python3-venv is missing. Run: sudo apt install python3-venv" >&2
    echo "Then run bash install.sh again." >&2
    exit 1
  fi
  VENV_ERR="$(mktemp)"
  if ! python3 -m venv "$DIR/.venv" 2>"$VENV_ERR"; then
    if [ "$VENV_PREEXISTED" -eq 0 ] && [ -d "$DIR/.venv" ]; then
      rm -rf "$DIR/.venv"
    fi
    echo "ERROR: could not create the Python environment:" >&2
    cat "$VENV_ERR" >&2
    rm -f "$VENV_ERR"
    if [ "$VENV_PREEXISTED" -eq 1 ]; then
      echo "Something is already at $DIR/.venv. If it is a broken" >&2
      echo "leftover, remove it (rm -rf $DIR/.venv) and run" >&2
      echo "bash install.sh again." >&2
    else
      echo "Fix that and run bash install.sh again." >&2
    fi
    exit 1
  fi
  rm -f "$VENV_ERR"
fi

# Connectivity pre-check (R60): with no network, pip would retry
# ten times in silence for minutes before the failure line. One
# short request against the package index fails in seconds
# instead, with a plain message. An HTTP answer of any kind means
# the network is up — only a connection failure refuses.
# STELLA_INSTALL_SKIP_NET_CHECK=1 skips the check (tests use it);
# STELLA_INSTALL_NET_CHECK_URL points it elsewhere (tests use a
# dead local address).
if [ -z "${STELLA_INSTALL_SKIP_NET_CHECK:-}" ]; then
  NET_CHECK_URL="${STELLA_INSTALL_NET_CHECK_URL:-https://pypi.org/simple/}"
  echo "Checking the network connection ..."
  if ! "$DIR/.venv/bin/python" -c "
import sys, urllib.request, urllib.error
try:
    req = urllib.request.Request(sys.argv[1], method='HEAD')
    urllib.request.urlopen(req, timeout=10)
except urllib.error.HTTPError:
    pass
except Exception:
    sys.exit(1)
" "$NET_CHECK_URL" 2>/dev/null; then
    echo "ERROR: no network connection. Stella downloads PySide6" >&2
    echo "from the internet, so connect and run bash install.sh again." >&2
    exit 1
  fi
fi

# pip, wrapped (T132): a failure ends with a Stella line naming the
# step and the retry, not raw pip output as the last word. Long
# timeout + retries (T67): the default 15s read timeout fails the
# ~90 MB PySide6 wheel on a slow connection. Versions are pinned
# in requirements-base.txt (T130).
pip_install() { # $1 = step label; rest = pip arguments
  local label="$1"; shift
  # R60: say what is being waited on before the download starts,
  # so a slow connection never looks like a stuck install.
  echo "$label ... this can take a few minutes on a slow connection."
  if ! "$DIR/.venv/bin/python" -m pip install --quiet --timeout 120 --retries 10 "$@"; then
    echo "ERROR: $label failed. Check your connection and disk space," >&2
    echo "then run bash install.sh again." >&2
    exit 1
  fi
}
pip_install "pip upgrade" --upgrade pip
pip_install "PySide6 download" -r "$DIR/requirements-base.txt"

# Fatal check, strengthened (T135): create a throwaway QApplication
# offscreen instead of import-only — an import succeeds even where
# creating a window would fail (missing system GL/EGL libs). On
# failure the real stderr is shown, so a missing lib names itself.
QT_ERR="$(mktemp)"
if ! QT_QPA_PLATFORM=offscreen "$DIR/.venv/bin/python" -c "from PySide6.QtWidgets import QApplication; import sys; app = QApplication(sys.argv)" >"$QT_ERR" 2>&1; then
  echo "ERROR: PySide6 is installed but cannot start a window." >&2
  echo "The real error was:" >&2
  tail -n 20 "$QT_ERR" >&2
  # R57: the doctor knows which package provides a missing
  # library — ask it, so the advice names the package instead of
  # leaving the user to guess. When the error names no known
  # library, the generic line stands.
  if QT_ADVICE="$("$DIR/.venv/bin/python" -m stella.doctor explain "$QT_ERR" 2>/dev/null)"; then
    echo "$QT_ADVICE" >&2
    echo "Then run bash install.sh again." >&2
  else
    echo "If it names a missing library, install it and run bash install.sh again." >&2
  fi
  rm -f "$QT_ERR"
  exit 1
fi
rm -f "$QT_ERR"

# Icon PNGs: the release zip ships them, but a fresh clone has only
# the SVG — render them now so the launcher never points at a
# missing file. (Needs QtSvg, which is why PySide6-Addons is in the
# pinned requirements.) A failed render only warns: the app still
# works, the icon just falls back to the system default.
ICON_MISSING=0
for size in 16 22 24 32 48 64 128 256 512; do
  [ -f "$DIR/assets/stella-$size.png" ] || ICON_MISSING=1
done
[ -f "$DIR/assets/stella.png" ] || ICON_MISSING=1
if [ "$ICON_MISSING" -eq 1 ]; then
  if ! "$DIR/.venv/bin/python" "$DIR/render_icon.py" >/dev/null 2>&1; then
    echo "WARNING: could not render the app icon from assets/stella.svg." >&2
  fi
fi

# Final check, BEFORE any artifact is written (T63): a failed
# install must leave no launcher behind. The version is captured
# here so the success message can label it (T136).
if ! STELLA_VERSION="$("$DIR/.venv/bin/python" -c "import stella; print(stella.__version__)" 2>/dev/null)"; then
  echo "ERROR: Stella did not import after install." >&2
  exit 1
fi

# Icons into the hicolor theme (T138): copies, not references, so
# the menu icon survives a folder move. When the theme install
# fails, the launcher falls back to the absolute path.
if "$DIR/.venv/bin/python" -m stella.install icons "$DIR" "$HOME" 2>/dev/null; then
  ICON_MODE="theme"
else
  ICON_MODE="path"
fi

# App-menu launcher (absolute paths — no quoting tricks needed).
# Written by the shared writer in stella/install.py, so `stella
# doctor` re-writes the same file after a move (T66).
# NOTE: Icon= must NOT be quoted. GLib strips quotes from Exec= but
# NOT from Icon=, so a quoted Icon= shows the generic gear icon.
"$DIR/.venv/bin/python" -m stella.install desktop "$DIR" "$HOME" "$ICON_MODE"

# Desktop copy for double-click launch from the desktop too.
# Cinnamon/Nemo refuse to launch an untrusted .desktop file, so the
# copy is made executable AND marked trusted. The copy is claimed
# in the success message only when it actually landed (T136).
DESKTOP_OK=0
if [ -d "$HOME/Desktop" ]; then
  if cp "$HOME/.local/share/applications/stella.desktop" "$HOME/Desktop/Stella.desktop" 2>/dev/null; then
    DESKTOP_OK=1
    chmod +x "$HOME/Desktop/Stella.desktop" 2>/dev/null || true
    if command -v gio >/dev/null 2>&1; then
      gio set "$HOME/Desktop/Stella.desktop" metadata::trusted true 2>/dev/null || true
    fi
  fi
fi

# Training installer icon on the desktop too (R13): the training
# install is click-only — double-click the icon, no terminal.
# Same trust treatment as the Stella icon above.
# The tree copy's Exec resolves the launcher next to the .desktop
# file (%k) — on the Desktop that folder is ~/Desktop, where the
# launcher is not, so the v0.25.0 Desktop copy failed on
# double-click (python3 could not open the file). The Desktop copy
# therefore names this install's launcher by absolute path; the
# tree copy keeps the portable %k form. The icon is claimed only
# when the copy landed AND the Exec line was rewritten.
TRAIN_DESKTOP_OK=0
if [ -d "$HOME/Desktop" ] && [ -f "$DIR/Install Training Stella.desktop" ]; then
  if cp "$DIR/Install Training Stella.desktop" "$HOME/Desktop/Install Stella Training.desktop" 2>/dev/null; then
    if "$DIR/.venv/bin/python" - "$HOME/Desktop/Install Stella Training.desktop" "$DIR/install_training_launcher.py" <<'PYEOF' 2>/dev/null; then
import sys
desktop_file, launcher = sys.argv[1], sys.argv[2]
lines = open(desktop_file).read().splitlines()
lines = [
    'Exec=python3 "%s"' % launcher if line.startswith("Exec=") else line
    for line in lines
]
open(desktop_file, "w").write("\n".join(lines) + "\n")
PYEOF
      TRAIN_DESKTOP_OK=1
    else
      echo "WARNING: could not point the desktop training icon at this install." >&2
    fi
    chmod +x "$HOME/Desktop/Install Stella Training.desktop" 2>/dev/null || true
    if command -v gio >/dev/null 2>&1; then
      gio set "$HOME/Desktop/Install Stella Training.desktop" metadata::trusted true 2>/dev/null || true
    fi
  fi
fi

# Command line: `stella` on PATH after install.
mkdir -p "$HOME/.local/bin"
ln -sf "$DIR/stella-cli" "$HOME/.local/bin/stella"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
fi

# Install receipt (T139): versions, paths, timestamp. A failed
# receipt write warns but does not fail the install.
if ! "$DIR/.venv/bin/python" -m stella.install receipt "$DIR" "$HOME" "$STELLA_VERSION" 2>/dev/null; then
  echo "WARNING: could not write the install receipt." >&2
fi

# Success message, reflecting reality (T136): the desktop icon is
# claimed only when the copy landed, and `stella` is claimed only
# when ~/.local/bin is already on PATH (Mint adds it at login, so
# a terminal open at install time will not find it yet).
echo "Stella $STELLA_VERSION is installed."
echo "Open it from the app menu (Stella)."
if [ "$DESKTOP_OK" -eq 1 ]; then
  echo "Or double-click Stella on the desktop. No terminal needed."
fi
if [ "$TRAIN_DESKTOP_OK" -eq 1 ]; then
  echo "Training installs from the desktop too (Install Stella Training)."
fi
case ":$PATH:" in
  *":$HOME/.local/bin:"*)
    echo "Command line is available too: stella profiles"
    ;;
  *)
    echo "Command line: open a new terminal (or log out and back in),"
    echo "then: stella profiles"
    ;;
esac
