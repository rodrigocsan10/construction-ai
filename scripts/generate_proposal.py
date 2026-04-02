#!/usr/bin/env python3
"""
Client proposal draft from priced JSON (scope, assumptions, payment template, totals).

Reads optional:
  - outputs/estimate_*_priced.json, takeoff_framing.json
  - config/Trades/*.json (scope bullets)
  - config/ company.json (company name)

Writes:
  - outputs/proposal_draft.md (default)
  - outputs/proposal_draft.pdf (--pdf) if fpdf2 is installed
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_OUT = _ROOT / "outputs" / "proposal_draft.md"
_TRADES = _ROOT / "config" / "Trades"


def company_path(root: Path) -> Path:
    spaced = root / "config" / " company.json"
    if spaced.is_file():
        return spaced
    return root / "config" / "company.json"


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else None


def trade_scope_lines(trade_file: str) -> list[str]:
    p = _TRADES / trade_file
    d = load_json(p)
    if not d:
        return []
    inc = d.get("scope_includes") or []
    exc = d.get("scope_excludes") or []
    lines: list[str] = []
    if inc:
        lines.append("**Includes (summary):** " + "; ".join(str(x) for x in inc[:8]) + ("…" if len(inc) > 8 else ""))
    if exc:
        lines.append("**Excludes (summary):** " + "; ".join(str(x) for x in exc[:6]) + ("…" if len(exc) > 6 else ""))
    return lines


def strip_md_for_pdf(s: str) -> str:
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = s.replace("#", "").replace("|", " ")
    return s


def write_pdf(path: Path, body_lines: list[str]) -> None:
    try:
        from fpdf import FPDF
    except ImportError as e:
        raise RuntimeError("Install fpdf2: pip install fpdf2") from e

    class PDF(FPDF):
        def footer(self) -> None:
            self.set_y(-15)
            self.set_font("Helvetica", "I", 8)
            self.cell(0, 10, f"Page {self.page_no()}", align="C")

    pdf = PDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)
    for raw in body_lines:
        line = strip_md_for_pdf(raw).strip()
        if not line:
            pdf.ln(3)
            continue
        if line.startswith("---"):
            pdf.ln(2)
            continue
        try:
            pdf.multi_cell(0, 5, line)
        except Exception:
            pdf.multi_cell(0, 5, line.encode("ascii", "replace").decode("ascii"))
        pdf.ln(1)
    pdf.output(str(path))


def payment_table_rows(total: float) -> list[tuple[str, float, float]]:
    """Milestone label, percent, dollar amount."""
    pct = [("Deposit upon signed agreement", 10.0), ("Mobilization / start", 25.0), ("Progress (mid-project)", 40.0), ("Substantial completion", 22.0), ("Final / punch closeout", 3.0)]
    return [(a, b, round(total * b / 100.0, 2)) for a, b in pct]


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate proposal markdown (+ optional PDF)")
    ap.add_argument("--framing-priced", type=Path, default=_ROOT / "outputs" / "estimate_framing_priced.json")
    ap.add_argument("--drywall-priced", type=Path, default=_ROOT / "outputs" / "estimate_drywall_priced.json")
    ap.add_argument("--windows-priced", type=Path, default=_ROOT / "outputs" / "estimate_windows_doors_priced.json")
    ap.add_argument("--takeoff-framing", type=Path, default=_ROOT / "outputs" / "takeoff_framing.json")
    ap.add_argument("-o", type=Path, dest="out", default=_DEFAULT_OUT)
    ap.add_argument("--pdf", type=Path, default=None, help="Also write PDF (requires fpdf2), e.g. outputs/proposal_draft.pdf")
    args = ap.parse_args()

    company = load_json(company_path(_ROOT)) or {}
    co_name = str(company.get("company_name") or "Contractor")

    lines: list[str] = []
    lines.append(f"# Proposal — {date.today().isoformat()}")
    lines.append("")
    lines.append(f"**Prepared by:** {co_name}")
    lines.append("")
    lines.append("*Generated from estimate files — review all figures and legal language before sending.*")
    lines.append("")
    lines.append("---")
    lines.append("")

    to = load_json(args.takeoff_framing.resolve())
    proj_name = "Project"
    if to:
        proj = to.get("project") or {}
        proj_name = str(proj.get("name") or proj_name)
    lines.append(f"## {proj_name}")
    lines.append("")

    lines.append("## Scope of work (reference)")
    lines.append("*Confirm final scope in the written contract; below mirrors current trade configs.*")
    lines.append("")
    for tf, title in [
        ("rough_framing.json", "### Rough framing + sheathing"),
        ("drywall_insulation.json", "### Drywall & insulation"),
        ("windows_doors.json", "### Exterior windows & doors (install only)"),
    ]:
        lines.append(title)
        for s in trade_scope_lines(tf):
            lines.append(f"- {s}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Investment summary")
    lines.append("")
    lines.append("| Package | Total (client) |")
    lines.append("| --- | ---: |")

    pkg_total = 0.0
    fp = load_json(args.framing_priced.resolve())
    if fp:
        pr = fp.get("pricing") or {}
        g = float(pr.get("grand_total_client") or 0)
        pkg_total += g
        lines.append(f"| Rough framing + sheathing | ${g:,.2f} |")
    dp = load_json(args.drywall_priced.resolve())
    if dp:
        su = (dp.get("pricing") or {}).get("summary_usd") or {}
        g = float(su.get("grand_total") or 0)
        pkg_total += g
        lines.append(f"| Drywall & insulation | ${g:,.2f} |")
    wp = load_json(args.windows_priced.resolve())
    if wp:
        su = (wp.get("pricing") or {}).get("summary_usd") or {}
        g = float(su.get("grand_total") or 0)
        pkg_total += g
        lines.append(f"| Windows & doors (labor package) | ${g:,.2f} |")
    lines.append(f"| **Subtotal (packages above)** | **${pkg_total:,.2f}** |")
    lines.append("")
    lines.append("*Taxes, bonds, permits, or owner-directed changes may adjust the final contract amount.*")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Assumptions & clarifications")
    lines.append("")
    if to:
        hdrs = to.get("headers_from_doors") or []
        if hdrs:
            lines.append("- **Headers:** Sized from door schedule where widths are parseable; **verify all headers with structural drawings.**")
            disc = next((h.get("disclaimer") for h in hdrs if isinstance(h, dict) and h.get("disclaimer")), None)
            if disc:
                lines.append(f"- **Header disclaimer:** {disc}")
        sh = (to.get("sheathing") or {})
        if sh.get("profile_suggests_zip_tape_roller"):
            lines.append("- **ZIP sheathing:** Estimate includes an allowance for tape/roller labor where the plan profile flags ZIP; confirm with field conditions.")
        eqn = to.get("equipment_notes") or {}
        if isinstance(eqn, dict) and eqn.get("proposal_language"):
            lines.append(f"- **Equipment:** {eqn.get('proposal_language')}")
    lines.append("- **Tax:** Subject to ST-8/ST-5 or jurisdiction rules as stated in contract.")
    lines.append("- **Retainage:** If applicable, retainage is a **cash-flow timing** matter — amounts on priced JSON include an informational retainage line where configured; contract governs.")
    lines.append("- **Windows/doors:** Client-supplied materials unless otherwise stated in contract.")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Suggested payment schedule (edit % / milestones)")
    lines.append("")
    if pkg_total > 0:
        lines.append("| Milestone | % | Amount |")
        lines.append("| --- | ---: | ---: |")
        for label, pct, amt in payment_table_rows(pkg_total):
            lines.append(f"| {label} | {pct:.0f}% | ${amt:,.2f} |")
        lines.append("")
        lines.append("*Percentages sum to 100%. Adjust to your GC agreement and lien rules.*")
    else:
        lines.append("*No priced totals found — fill amounts after pricing, or run the estimate pipeline first.*")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Acceptance")
    lines.append("")
    lines.append("Authorized signature: _____________________________  Date: __________")
    lines.append("")
    lines.append("Print name / title: _____________________________")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Next steps")
    lines.append("- Confirm scope, schedule, and tax treatment.")
    lines.append("- Provide structural / shop drawings for final header and hardware verification.")
    lines.append("")

    if fp:
        pr = fp.get("pricing") or {}
        lines.append("### Appendix — framing pricing notes")
        lines.append(f"- Grand total: **${float(pr.get('grand_total_client') or 0):,.2f}**")
        inp = pr.get("inputs") or {}
        if inp.get("roof_labor_tier"):
            lines.append(f"- Roof labor tier: `{inp.get('roof_labor_tier')}` ({inp.get('labor_rate_rule', '')})")
        zt = pr.get("zip_tape_roller_labor") or {}
        if zt.get("applied"):
            lines.append(
                f"- ZIP tape/roller labor est.: ${float(zt.get('usd') or 0):,.2f} ({zt.get('wall_sheets')} sheets × ${zt.get('per_sheet_usd')})"
            )
        rr = pr.get("retainage_reference") or {}
        if float(rr.get("typical_holdback_usd") or 0) > 0:
            lines.append(
                f"- Retainage (informational): ~${float(rr.get('typical_holdback_usd') or 0):,.2f} typical holdback on contract value."
            )
        lines.append("")

    out = args.out
    if not out.is_absolute():
        out = (Path.cwd() / out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines)
    out.write_text(text, encoding="utf-8")
    print(f"Wrote {out}")

    if args.pdf:
        pdf_path = args.pdf
        if not pdf_path.is_absolute():
            pdf_path = (Path.cwd() / pdf_path).resolve()
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            write_pdf(pdf_path, lines)
            print(f"Wrote {pdf_path}")
        except RuntimeError as e:
            print(f"PDF skipped: {e}")


if __name__ == "__main__":
    main()
