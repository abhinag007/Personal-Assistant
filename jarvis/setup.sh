#!/usr/bin/env bash
# JARVIS — Phase 0 setup (macOS / Apple Silicon)
# Creates a Python virtual environment and installs dependencies.
set -euo pipefail

cd "$(dirname "$0")"

echo "==> JARVIS Phase 0 setup"

# 1. Pick a Python (3.11+ required; 3.12 recommended)
PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "ERROR: python3 not found. Install Python 3.12 (e.g. 'brew install python@3.12')." >&2
  exit 1
fi

PYV="$($PYTHON -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
echo "    Using Python $PYV ($PYTHON)"

# 2. Create the virtual environment
if [ ! -d ".venv" ]; then
  echo "==> Creating virtual environment at ./.venv"
  "$PYTHON" -m venv .venv
else
  echo "==> Reusing existing ./.venv"
fi

# 3. Install dependencies
echo "==> Installing dependencies"
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt

echo ""
echo "==> Done. Next steps:"
echo "      source .venv/bin/activate"
echo "      python -m jarvis.main --onboard      # first-run setup"
echo "      pytest -v                            # run the safety test suite"
