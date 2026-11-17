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

# Disk-space preflight (T133): the training stack needs about 5 GB
# free (R61) — about 2 GB of wheels downloaded plus about 2 GB
# installed into the venv, plus headroom. The peak is UNMEASURED
# (no real training install has ever run on his PC; R23 measures
# it), so 5 GB is the conservative number until then: a false
# refusal costs a cleanup prompt, a false pass costs a download
# dying halfway for lack of disk. The wheels live in
# ~/.cache/stella/wheels (R62) and the venv in $DIR/.venv, both
# usually on the same disk. STELLA_INSTALL_MIN_FREE_KB overrides
# the threshold (tests use it).
MIN_FREE_KB="${STELLA_INSTALL_MIN_FREE_KB:-5242880}"
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

# The download, resumable (R62): pip cannot resume a partial
# wheel, so the wheels are fetched outside pip first — pip lists
# them without downloading (--dry-run --report), each one is
# fetched with HTTP Range resume into a cache dir, and pip then
# installs from the local files. A stopped download picks up
# where it left off on the next run instead of starting over.
# When the wheels cannot be listed or fetched outside pip (an old
# pip, a package with no wheel), the direct download below is the
# fallback — the install is never worse than before. Versions are
# pinned in requirements-train.txt (T130); the file carries the
# CPU wheel index, so torch resolves to the +cpu build.
# STELLA_WHEEL_DIR points the wheel cache elsewhere (tests use it).
WHEELS="${STELLA_WHEEL_DIR:-$HOME/.cache/stella/wheels}"
REPORT="$(mktemp)"
TRAINING_INSTALLED=0
if "$DIR/.venv/bin/python" -m pip install --quiet --timeout 120 --retries 10 --dry-run --report "$REPORT" -r "$DIR/requirements-train.txt" 2>/dev/null; then
  FETCH_RC=0
  "$DIR/.venv/bin/python" -m stella.wheel_fetch fetch "$REPORT" "$WHEELS" || FETCH_RC=$?
  if [ "$FETCH_RC" -eq 0 ]; then
    if "$DIR/.venv/bin/python" -m pip install --quiet --timeout 120 --retries 10 --no-cache-dir --no-index --find-links "$WHEELS" -r "$DIR/requirements-train.txt"; then
      TRAINING_INSTALLED=1
    else
      echo "ERROR: training packages download failed. Check your connection" >&2
      echo "and disk space, then run bash install-training.sh again." >&2
      rm -f "$REPORT"
      exit 1
    fi
  elif [ "$FETCH_RC" -eq 1 ]; then
    # A download failed partway: the partial wheels stay in the
    # cache, so the next run resumes. Never fall back to the
    # direct download here — it would fetch the stopped wheel
    # from scratch and throw the resume away.
    echo "ERROR: the training download stopped partway." >&2
    echo "Run bash install-training.sh again to pick up where it stopped." >&2
    rm -f "$REPORT"
    exit 1
  else
    echo "The wheels could not be fetched one by one, so downloading them directly instead."
  fi
else
  echo "The training wheels could not be listed first, so downloading them directly instead."
fi
rm -f "$REPORT"
if [ "$TRAINING_INSTALLED" -eq 0 ]; then
  # Direct download (T132): a failure ends with a Stella line
  # naming the step and the retry, not raw pip output as the last
  # word. Long timeout + retries: the torch download is big and
  # the default 15s read timeout fails on slow connections.
  # --no-cache-dir (R61): the pip cache would hold a second ~2 GB
  # copy of the wheels beside the venv.
  if ! "$DIR/.venv/bin/python" -m pip install --quiet --timeout 120 --retries 10 --no-cache-dir -r "$DIR/requirements-train.txt"; then
    echo "ERROR: training packages download failed. Check your connection" >&2
    echo "and disk space, then run bash install-training.sh again." >&2
    exit 1
  fi
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
