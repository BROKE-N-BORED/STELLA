#!/usr/bin/env bash
# STELLA training installer — run once, only if you want to train.
#   bash install-training.sh
# Adds the training packages (torch CPU, transformers, peft,
# accelerate) into Stella's private .venv. This is a big download
# (about 2 GB) and takes a few minutes — that is why it is separate
# from the base install, which stays light (PySide6 only).
#
# Run it with bash, never sh: it uses set -euo pipefail.
set -euo pipefail

# T186: --help answers with usage and exits 0, without installing
# anything. Checked before DIR resolution, so nothing happens at all.
if [ "${1:-}" = "--help" ]; then
  echo "Usage: bash install-training.sh [--help]"
  echo "Adds the training packages (torch CPU, transformers, peft,"
  echo "accelerate) to Stella's private .venv. About 2 GB."
  echo "Run bash install.sh first."
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

echo "Installing Stella training packages into $DIR/.venv ..."
echo "(about 2 GB - torch CPU, transformers, peft, accelerate)"

if [ ! -x "$DIR/.venv/bin/python" ]; then
  echo "ERROR: Stella is not installed yet. Run bash install.sh first." >&2
  exit 1
fi

# Disk-space preflight (T133): the training stack needs about 3 GB.
# STELLA_INSTALL_MIN_FREE_KB overrides the threshold (tests use it).
MIN_FREE_KB="${STELLA_INSTALL_MIN_FREE_KB:-3145728}"
AVAIL_KB="$(df -k --output=avail "$DIR" 2>/dev/null | tail -n 1 | tr -d ' ')"
case "$AVAIL_KB" in
  ''|*[!0-9]*) AVAIL_KB="" ;;  # df failed or gave junk: do not block on it
esac
if [ -n "$AVAIL_KB" ] && [ "$AVAIL_KB" -lt "$MIN_FREE_KB" ]; then
  NEED_GB="$((MIN_FREE_KB / 1024 / 1024))"
  HAVE_GB="$((AVAIL_KB / 1024 / 1024))"
  echo "ERROR: not enough free disk space for the training packages." >&2
  echo "They need about ${NEED_GB} GB free; this disk has about ${HAVE_GB} GB." >&2
  echo "Free some space and run bash install-training.sh again." >&2
  exit 1
fi

# Fast path (T134): if everything already imports, a second run
# exits in seconds instead of re-resolving the torch index for
# two silent minutes. The receipt is still refreshed, so it names
# the training versions even for a pre-v0.15 install.
if "$DIR/.venv/bin/python" -c "import torch, transformers, peft, accelerate" 2>/dev/null; then
  echo "Training packages are already installed."
  STELLA_VERSION="$("$DIR/.venv/bin/python" -c "import stella; print(stella.__version__)" 2>/dev/null || echo "?")"
  "$DIR/.venv/bin/python" -m stella.install receipt "$DIR" "$HOME" "$STELLA_VERSION" 2>/dev/null || true
  exit 0
fi

# pip, wrapped (T132): a failure ends with a Stella line naming the
# step and the retry, not raw pip output as the last word. Long
# timeout + retries: the torch download is big and the default 15s
# read timeout fails on slow connections. Versions are pinned in
# requirements-train.txt (T130); the file carries the CPU wheel
# index, so torch resolves to the +cpu build.
if ! "$DIR/.venv/bin/python" -m pip install --quiet --timeout 120 --retries 10 -r "$DIR/requirements-train.txt"; then
  echo "ERROR: training packages download failed. Check your connection" >&2
  echo "and disk space, then run bash install-training.sh again." >&2
  exit 1
fi

# Fatal check: the training stack must import, or the install failed.
if ! "$DIR/.venv/bin/python" -c "import torch, transformers, peft, accelerate" 2>/dev/null; then
  echo "ERROR: training packages installed but cannot be imported." >&2
  echo "Try again with a network connection, or check disk space." >&2
  exit 1
fi

"$DIR/.venv/bin/python" -c "import torch; print('torch', torch.__version__, '- CPU threads:', torch.get_num_threads())"

# Install receipt (T139): re-written with the torch versions added.
STELLA_VERSION="$("$DIR/.venv/bin/python" -c "import stella; print(stella.__version__)" 2>/dev/null || echo "?")"
if ! "$DIR/.venv/bin/python" -m stella.install receipt "$DIR" "$HOME" "$STELLA_VERSION" 2>/dev/null; then
  echo "WARNING: could not write the install receipt." >&2
fi

echo ""
echo "Training packages installed. Next: pull the base weights, e.g."
echo "  stella pull-weights LiquidAI/LFM3-1.7B"
echo "or set the profile base_ref to LiquidAI/LFM3-1.7B and let the"
echo "first training run download them (about 3.5 GB)."
echo "Then train from the Stella window, or: stella train <profile> <project>"
