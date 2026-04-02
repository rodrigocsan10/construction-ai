#!/usr/bin/env bash
# Start the Streamlit estimating UI from the project root.
set -euo pipefail
cd "$(dirname "$0")"

if [[ -d .venv ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
elif [[ -d venv ]]; then
  # shellcheck source=/dev/null
  source venv/bin/activate
else
  echo "No virtualenv found. Create one with:"
  echo "  python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

exec streamlit run scripts/app.py
