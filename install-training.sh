#!/usr/bin/env bash
# STELLA training installer — run once, only if you want to train.
#   bash install-training.sh
# Adds the training packages (torch CPU, transformers, peft,
# accelerate) into Stella's private .venv. This is a big download
# (about 2 GB) and takes a few minutes — that is why it is separate
# from the base install, which stays light (PySide6 only).
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

echo "Installing Stella training packages into $DIR/.venv ..."
echo "(about 2 GB — torch CPU, transformers, peft, accelerate)"

if [ ! -x "$DIR/.venv/bin/python" ]; then
  echo "ERROR: Stella is not installed yet. Run bash install.sh first." >&2
  exit 1
fi

# torch from the CPU wheel index (no CUDA — this PC has no GPU),
# the rest from PyPI. Long timeout + retries: the torch download is
# big and the default 15s read timeout fails on slow connections.
"$DIR/.venv/bin/python" -m pip install --quiet --timeout 120 --retries 10 torch --index-url https://download.pytorch.org/whl/cpu
"$DIR/.venv/bin/python" -m pip install --quiet --timeout 120 --retries 10 transformers peft accelerate

# Fatal check: the training stack must import, or the install failed.
if ! "$DIR/.venv/bin/python" -c "import torch, transformers, peft, accelerate" 2>/dev/null; then
  echo "ERROR: training packages installed but cannot be imported." >&2
  echo "Try again with a network connection, or check disk space." >&2
  exit 1
fi

"$DIR/.venv/bin/python" -c "import torch; print('torch', torch.__version__, '— CPU threads:', torch.get_num_threads())"

echo ""
echo "Training packages installed. Next: pull the base weights, e.g."
echo "  $DIR/.venv/bin/python -c \"from huggingface_hub import snapshot_download; snapshot_download('LiquidAI/LFM3-1.7B')\""
echo "or set the profile base_ref to LiquidAI/LFM3-1.7B and let the"
echo "first training run download them (about 3.5 GB)."
echo "Then train from the Stella window, or: stella train <profile> <project>"
