#!/usr/bin/env bash
# Run the Stella test suite. Run with: bash run_tests.sh
#
# The suite runs in Stella's own .venv, never in system Python:
# Mint's Python is externally managed, so pip installing pytest
# into it fails (T68). Run bash install.sh first on a bare checkout.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [ ! -x "$DIR/.venv/bin/python" ]; then
  echo "Stella is not installed yet. Run bash install.sh first," >&2
  echo "then run bash run_tests.sh again." >&2
  exit 1
fi
PY="$DIR/.venv/bin/python"

# R128: pytest-timeout supplies the per-test timeout in pytest.ini —
# without the plugin the timeout would silently do nothing, so it is
# installed wherever pytest is (here and both CI jobs).
if ! "$PY" -m pytest --version >/dev/null 2>&1 || ! "$PY" -c "import pytest_timeout" 2>/dev/null; then
  echo "Installing pytest and pytest-timeout into the Stella venv for the test run..."
  "$PY" -m pip install --quiet --timeout 120 --retries 10 pytest pytest-timeout
fi

# The GUI tests need PySide6. The installed venv already has it; a
# venv without it gets it here, inside the venv (never system pip).
if ! "$PY" -c "import PySide6" 2>/dev/null; then
  echo "Installing PySide6-Essentials into the Stella venv for the GUI tests..."
  "$PY" -m pip install --quiet --timeout 120 --retries 10 PySide6-Essentials
fi

# Training tests need the training stack; without it they skip cleanly
# (pytest.importorskip), so a base install still goes green. Run
# bash install-training.sh first for the full suite.
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen "$PY" -m pytest tests/ -q
