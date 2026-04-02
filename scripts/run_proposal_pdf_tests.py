#!/usr/bin/env python3
"""Generate 3 regression PDFs from config/proposal_examples/*.json (strict validation)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PY = sys.executable
_BUILD = _ROOT / "scripts" / "build_proposal_pdf.py"

SCENARIOS: list[tuple[str, str]] = [
    ("config/proposal_examples/scenario_a_lump_sum_client.json", "outputs/proposal_test_A_lump_client.pdf"),
    ("config/proposal_examples/scenario_b_internal_itemized.json", "outputs/proposal_test_B_internal.pdf"),
    ("config/proposal_examples/scenario_c_pa_short_validity.json", "outputs/proposal_test_C_pa_itemized.pdf"),
]


def main() -> None:
    for inp, outp in SCENARIOS:
        cmd = [
            _PY,
            str(_BUILD),
            "--input",
            str(_ROOT / inp),
            "--output",
            str(_ROOT / outp),
            "--strict",
        ]
        print("+", " ".join(cmd), flush=True)
        subprocess.run(cmd, check=True, cwd=_ROOT)
    print("OK — review PDFs for leaks: A must hide traps; B must show watermark + internal notes; C PA tax + 15d validity.", flush=True)


if __name__ == "__main__":
    main()
