#!/usr/bin/env bash
# Run the Stella test suite. Run with: bash run_tests.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [ -x "$DIR/.venv/bin/python" ]; then
  PY="$DIR/.venv/bin/python"
else
  PY="python3"
fi

if ! "$PY" -m pytest --version >/dev/null 2>&1; then
  echo "Installing pytest for the test run..."
  "$PY" -m pip install --quiet pytest
fi

# The GUI tests need PySide6. The installed venv already has it; a
# bare checkout installs it for the test run (same as pytest above).
if ! "$PY" -c "import PySide6" 2>/dev/null; then
  echo "Installing PySide6-Essentials for the GUI tests..."
  "$PY" -m pip install --quiet PySide6-Essentials
fi

# Training tests need the training stack; without it they skip cleanly
# (pytest.importorskip), so a base install still goes green. Run
# bash install-training.sh first for the full suite.
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen "$PY" -m pytest tests/ -q
