#!/usr/bin/env bash
# STELLA launcher — opens the Stella window. No terminal needed.
# Run it with: bash run.sh
set -euo pipefail

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

if [ -x "$DIR/.venv/bin/python" ]; then
  PY="$DIR/.venv/bin/python"
else
  echo "Stella is not installed yet. Run: bash install.sh" >&2
  exit 1
fi

exec "$PY" -m stella "$@"
