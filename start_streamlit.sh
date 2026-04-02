#!/usr/bin/env bash
# Launch the Streamlit UI (does not modify existing start.sh).
set -euo pipefail
cd "$(dirname "$0")"
if [[ -d .venv ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
elif [[ -d venv ]]; then
  # shellcheck source=/dev/null
  source venv/bin/activate
else
  echo "Create a venv first: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi
exec streamlit run scripts/app.py
