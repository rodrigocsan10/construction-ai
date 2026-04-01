#!/usr/bin/env python3
"""
Draft client proposal text from priced JSON outputs (KB-aligned assumptions).

Reads optional:
  - outputs/estimate_framing_priced.json
  - outputs/estimate_drywall_priced.json
  - outputs/estimate_windows_doors_priced.json
  - outputs/takeoff_framing.json (header disclaimer, equipment note)

Writes:
  - outputs/proposal_draft.md (default)
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_OUT = _ROOT / "outputs" / "proposal_draft.md"


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else None


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate proposal draft markdown from priced outputs")
    ap.add_argument("--framing-priced", type=Path, default=_ROOT / "outputs" / "estimate_framing_priced.json")
    ap.add_argument("--drywall-priced", type=Path, default=_ROOT / "outputs" / "estimate_drywall_priced.json")
    ap.add_argument("--windows-priced", type=Path, default=_ROOT / "outputs" / "estimate_windows_doors_priced.json")
    ap.add_argument("--takeoff-framing", type=Path, default=_ROOT / "outputs" / "takeoff_framing.json")
    ap.add_argument("-o", type=Path, dest="out", default=_DEFAULT_OUT)
    args = ap.parse_args()

    lines: list[str] = []
    lines.append(f"# Proposal draft — {date.today().isoformat()}")
    lines.append("")
    lines.append("*Machine-generated from estimate JSON. Review all numbers and assumptions before sending.*")
    lines.append("")

    to = load_json(args.takeoff_framing.resolve())
    if to:
        proj = to.get("project") or {}
        name = proj.get("name") or "Project"
        lines.append(f"## {name}")
        lines.append("")
        hdrs = to.get("headers_from_doors") or []
        if hdrs:
            lines.append("### Framing assumptions")
            lines.append("- Headers: assumed per door schedule where widths parsed; verify against structural drawings.")
            disc = next((h.get("disclaimer") for h in hdrs if isinstance(h, dict) and h.get("disclaimer")), None)
            if disc:
                lines.append(f"- **Disclaimer:** {disc}")
            lines.append("")
        eqn = to.get("equipment_notes") or {}
        if isinstance(eqn, dict) and eqn.get("proposal_language"):
            lines.append(f"- Equipment: {eqn.get('proposal_language')}")
            lines.append("")

    fp = load_json(args.framing_priced.resolve())
    if fp:
        pr = fp.get("pricing") or {}
        inp = pr.get("inputs") or {}
        lines.append("### Rough framing + sheathing (summary)")
        lines.append(f"- Grand total (client): **${pr.get('grand_total_client', 0):,.2f}**")
        if inp.get("roof_labor_tier"):
            lines.append(f"- Roof labor tier: `{inp.get('roof_labor_tier')}` — {inp.get('labor_rate_rule', '')}")
        mat = pr.get("material") or {}
        lines.append(
            f"- Materials: raw ${mat.get('raw_subtotal', 0):,.2f} + tax/markup as shown in estimate JSON."
        )
        bo = pr.get("blockout_crew") or {}
        if bo.get("applied"):
            lines.append(f"- Blockout crew included: **${bo.get('usd', 0):,.2f}**")
        eq = pr.get("equipment_allowance") or {}
        if eq.get("applied"):
            lines.append(f"- Equipment allowance: **${eq.get('usd', 0):,.2f}** ({eq.get('months')} mo × ${eq.get('monthly_rate')}/mo est.)")
        lines.append("")

    dp = load_json(args.drywall_priced.resolve())
    if dp:
        pr = dp.get("pricing") or {}
        su = pr.get("summary_usd") or {}
        lines.append("### Drywall & insulation (summary)")
        lines.append(f"- Grand total (client): **${su.get('grand_total', 0):,.2f}**")
        lines.append("- Subcontract sheet model; see JSON for hang/finish level, insulation floors, KB extras (fire caulk, furring, lift), mobilization if entered.")
        lines.append("")

    wp = load_json(args.windows_priced.resolve())
    if wp:
        pr = wp.get("pricing") or {}
        su = pr.get("summary_usd") or {}
        g = su.get("grand_total", 0)
        lines.append("### Exterior windows & doors install (summary)")
        lines.append(f"- Grand total (client): **${float(g):,.2f}**")
        lines.append("- Labor + handling; client-supplied units per KB.")
        lines.append("")

    lines.append("### Next steps")
    lines.append("- Confirm scope, tax status (ST-8/ST-5 exempt), and job duration for mobilization.")
    lines.append("- Attach structural sheets for header and hardware verification.")
    lines.append("")

    out = args.out
    if not out.is_absolute():
        out = (Path.cwd() / out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
