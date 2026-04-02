#!/usr/bin/env python3
"""
One-shot: merge → framing takeoff → price framing [→ drywall takeoff → price drywall].

No OpenAI in this script. For LF: pass --lf-json, or --use-sample-lf (demo LF + roof SF),
or run takeoff_framing.py --estimate-lf against the PDF, then run_pipeline.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PY = sys.executable
_SAMPLE_LF = _ROOT / "config" / "examples" / "mt_arlington_sample_lf.json"


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=_ROOT)


def main() -> None:
    ap = argparse.ArgumentParser(description="Merge → takeoff → price (local only).")
    ap.add_argument("--skip-merge", action="store_true")
    ap.add_argument("--lf-json", type=Path, default=None)
    ap.add_argument(
        "--use-sample-lf",
        action="store_true",
        help=f"Use {_SAMPLE_LF.name} for wall LF + roof deck (non-zero takeoff demo)",
    )
    ap.add_argument("--building-sf", type=float, default=None)
    ap.add_argument("--round-trip-miles", type=float, default=0.0)
    ap.add_argument("--working-days", type=int, default=0)
    ap.add_argument("--markup-pct", type=float, default=None)
    ap.add_argument("--include-blockout", action="store_true", help="Framing: commercial blockout crew (KB)")
    ap.add_argument("--equipment-months", type=float, default=0.0, help="Framing: equipment allowance months")
    ap.add_argument("--with-drywall", action="store_true", help="Run takeoff_drywall + price_drywall after framing")
    ap.add_argument("--ceiling-sf", type=float, default=0.0)
    ap.add_argument("--drywall-vertical-carry", action="store_true")
    ap.add_argument(
        "--drywall-mobilization-miles",
        type=float,
        default=0.0,
        help="Drywall mobilization RT miles (with --drywall-mobilization-days)",
    )
    ap.add_argument("--drywall-mobilization-days", type=int, default=0)
    ap.add_argument("--with-windows", action="store_true", help="takeoff_windows_doors + price_windows_doors")
    ap.add_argument("--with-proposal", action="store_true", help="generate_proposal.py after estimates")
    ap.add_argument(
        "--proposal-pdf",
        action="store_true",
        help="With --with-proposal, also write outputs/proposal_draft.pdf (needs fpdf2)",
    )
    ap.add_argument("--with-supplier-email", action="store_true", help="supplier_email.py after framing takeoff")
    args = ap.parse_args()

    if not args.skip_merge:
        run([_PY, str(_ROOT / "scripts" / "merge_profiles.py")])

    if args.lf_json:
        lf_path: Path | None = args.lf_json
    elif args.use_sample_lf:
        if not _SAMPLE_LF.is_file():
            print(f"Missing sample LF file: {_SAMPLE_LF}", flush=True)
            raise SystemExit(1)
        lf_path = _SAMPLE_LF
    else:
        lf_path = None

    tf = [_PY, str(_ROOT / "scripts" / "takeoff_framing.py")]
    if lf_path:
        tf.extend(["--lf-json", str(lf_path.resolve())])
    run(tf)

    pf = [
        _PY,
        str(_ROOT / "scripts" / "price_framing.py"),
        "--round-trip-miles",
        str(args.round_trip_miles),
        "--working-days",
        str(args.working_days),
    ]
    if args.building_sf:
        pf.extend(["--building-sf", str(args.building_sf)])
    if args.markup_pct is not None:
        pf.extend(["--markup-pct", str(args.markup_pct)])
    if args.include_blockout:
        pf.append("--include-blockout")
    if args.equipment_months and args.equipment_months > 0:
        pf.extend(["--equipment-months", str(args.equipment_months)])
    run(pf)

    if args.with_supplier_email:
        run([_PY, str(_ROOT / "scripts" / "supplier_email.py")])

    if args.with_drywall:
        td = [_PY, str(_ROOT / "scripts" / "takeoff_drywall.py")]
        if args.ceiling_sf:
            td.extend(["--ceiling-sf", str(args.ceiling_sf)])
        run(td)
        pd = [_PY, str(_ROOT / "scripts" / "price_drywall.py")]
        if args.drywall_vertical_carry:
            pd.append("--vertical-carry")
        if args.drywall_mobilization_miles > 0 and args.drywall_mobilization_days > 0:
            pd.extend(
                [
                    "--mobilization-round-trip-miles",
                    str(args.drywall_mobilization_miles),
                    "--mobilization-working-days",
                    str(args.drywall_mobilization_days),
                ]
            )
        run(pd)

    if args.with_windows:
        run([_PY, str(_ROOT / "scripts" / "takeoff_windows_doors.py")])
        run([_PY, str(_ROOT / "scripts" / "price_windows_doors.py")])

    if args.with_proposal:
        gp = [_PY, str(_ROOT / "scripts" / "generate_proposal.py")]
        if args.proposal_pdf:
            gp.extend(["--pdf", str(_ROOT / "outputs" / "proposal_draft.pdf")])
        run(gp)


if __name__ == "__main__":
    main()
