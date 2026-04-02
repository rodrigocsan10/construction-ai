#!/usr/bin/env python3
"""
Build 5-page branded proposal PDF from JSON input.

Pages:
  1 — Cover (company, project, date, validity, confidentiality notice)
  2 — Investment (lump-sum-only OR itemized; adaptive by bid_mode)
  3 — Scope (paragraphs pass-through)
  4 — Payment schedule + tax note + assumptions
  5 — Signatures + confidentiality / lump-sum disclaimer

See: config/proposal_input.schema.md
"""

from __future__ import annotations

import argparse
import copy
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from pdf_styles import (
    BODY_PT,
    CONFIDENTIAL_RED,
    LINE_HEIGHT_MM,
    PAGE_MARGIN,
    SECTION_PT,
    SMALL_PT,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TITLE_PT,
    accent_rgb,
)

_ROOT = Path(__file__).resolve().parent.parent


def safe_pdf_text(s: str) -> str:
    """Core fonts: keep printable ASCII; replace smart quotes."""
    t = str(s).replace("\u201c", '"').replace("\u201d", '"').replace("\u2019", "'")
    return t.encode("latin-1", "replace").decode("latin-1")


def tax_note_text(tax: dict[str, Any] | None) -> str:
    if not tax:
        tax = {}
    if tax.get("custom_note"):
        return str(tax["custom_note"])
    j = str(tax.get("jurisdiction") or "NJ").upper()
    if j == "NJ":
        return (
            "New Jersey: taxable materials are generally subject to state sales tax unless a valid exemption applies "
            "(e.g., ST-8 capital improvement or ST-5 nonprofit). Confirm certificates before bid acceptance."
        )
    if j == "PA":
        return (
            "Pennsylvania: sales or use tax often applies at approximately 6% on taxable supplies; "
            "verify project-specific rules and any exemption documentation."
        )
    return (
        "Tax treatment depends on project location, contract structure, and exemption status. "
        "Confirm with your tax advisor and the agreement of record."
    )


def is_internal_view(meta: dict[str, Any]) -> bool:
    return meta.get("bid_mode") == "internal_review" or meta.get("confidentiality") == "internal"


def validate_proposal(data: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    meta = data.get("meta") or {}
    company = data.get("company") or {}
    project = data.get("project") or {}
    if not str(company.get("name") or "").strip():
        errs.append("company.name is required")
    if not str(project.get("name") or "").strip():
        errs.append("project.name is required")
    inv = data.get("investment") or {}
    try:
        lump = float(inv.get("lump_sum") or 0)
    except (TypeError, ValueError):
        lump = -1
    if lump < 0:
        errs.append("investment.lump_sum must be a non-negative number")
    rows = data.get("payment_schedule") or []
    if not rows:
        errs.append("payment_schedule must have at least one row")
    else:
        try:
            total_pct = sum(float(r.get("pct") or 0) for r in rows)
        except (TypeError, ValueError):
            total_pct = -1
        if total_pct < 0 or abs(total_pct - 100.0) > 0.02:
            errs.append(f"payment_schedule pct must sum to 100 (got {total_pct:.2f})")
    mode = meta.get("bid_mode") or "lump_sum"
    if mode not in ("lump_sum", "itemized", "internal_review"):
        errs.append("meta.bid_mode must be lump_sum | itemized | internal_review")
    conf = meta.get("confidentiality") or "client"
    if conf not in ("client", "internal"):
        errs.append("meta.confidentiality must be client | internal")
    return errs


def view_model_for_render(data: dict[str, Any]) -> dict[str, Any]:
    """Apply confidentiality / bid-mode filtering for what appears on a client-facing PDF."""
    d = copy.deepcopy(data)
    meta = d.setdefault("meta", {})
    internal = is_internal_view(meta)
    mode = meta.get("bid_mode") or "lump_sum"

    pay = []
    for row in d.get("payment_schedule") or []:
        if not internal and row.get("client_visible") is False:
            continue
        pay.append(row)
    d["payment_schedule"] = pay

    inv = d.setdefault("investment", {})
    if mode == "lump_sum" and not internal:
        inv.pop("line_items", None)
    if not internal:
        cs = d.get("confidential_sections")
        if isinstance(cs, dict):
            cs.pop("internal_notes", None)
    return d


class ProposalDoc(FPDF):
    def __init__(self, confidential_footer: bool) -> None:
        super().__init__(format="Letter", unit="mm")
        self._conf_footer = confidential_footer
        self.set_auto_page_break(auto=True, margin=20)
        self.set_margins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)

    def footer(self) -> None:
        if self._conf_footer:
            self.set_y(-12)
            self.set_font("Helvetica", "B", SMALL_PT)
            self.set_text_color(*CONFIDENTIAL_RED)
            self.cell(
                0,
                6,
                safe_pdf_text("CONFIDENTIAL — INTERNAL ESTIMATE — NOT FOR DISTRIBUTION"),
                align="C",
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )
            self.set_text_color(*TEXT_PRIMARY)

    def rule_accent(self, y: float | None = None) -> None:
        if y is not None:
            self.set_y(y)
        self.set_draw_color(*accent_rgb())
        self.set_line_width(0.6)
        self.line(PAGE_MARGIN, self.get_y(), self.w - PAGE_MARGIN, self.get_y())
        self.ln(4)

    def heading(self, text: str, level: int = 1) -> None:
        self.set_text_color(*accent_rgb() if level == 1 else TEXT_PRIMARY)
        self.set_font("Helvetica", "B", TITLE_PT if level == 1 else SECTION_PT)
        w = self.w - 2 * PAGE_MARGIN
        self.set_x(PAGE_MARGIN)
        self.multi_cell(w, LINE_HEIGHT_MM + 1, safe_pdf_text(text))
        self.ln(2)
        self.set_text_color(*TEXT_PRIMARY)
        self.set_font("Helvetica", "", BODY_PT)


def render_pdf(data: dict[str, Any], out_path: Path) -> None:
    meta = data.get("meta") or {}
    internal = is_internal_view(meta)
    mode = meta.get("bid_mode") or "lump_sum"
    vm = view_model_for_render(data)

    doc = ProposalDoc(confidential_footer=internal)
    content_w = doc.w - 2 * PAGE_MARGIN
    ac = accent_rgb()
    today = date.today()
    try:
        vd = int(meta.get("validity_days") or 30)
    except (TypeError, ValueError):
        vd = 30
    valid_until = today + timedelta(days=vd)
    company = vm.get("company") or {}
    project = vm.get("project") or {}
    inv = vm.get("investment") or {}
    lump = float(inv.get("lump_sum") or 0)
    line_items = inv.get("line_items") or []

    # ----- Page 1 -----
    doc.add_page()
    # Optional logo
    logo = company.get("logo_path")
    if logo:
        lp = _ROOT / str(logo)
        if lp.is_file():
            try:
                doc.image(str(lp), x=PAGE_MARGIN, y=12, w=40)
                doc.set_y(38)
            except Exception:
                doc.set_y(20)
        else:
            doc.set_y(20)
    else:
        doc.set_y(24)

    doc.set_font("Helvetica", "B", TITLE_PT)
    doc.set_text_color(*ac)
    title = str(meta.get("document_title") or "Proposal")
    doc.cell(0, 12, safe_pdf_text(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    doc.set_text_color(*TEXT_PRIMARY)
    doc.set_font("Helvetica", "", BODY_PT)
    doc.ln(6)
    doc.set_font("Helvetica", "B", 12)
    doc.cell(0, 6, safe_pdf_text(str(company.get("name") or "")), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    doc.set_font("Helvetica", "", BODY_PT)
    for line in filter(None, [company.get("address"), company.get("phone"), company.get("email")]):
        doc.cell(0, 5, safe_pdf_text(str(line)), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    doc.ln(10)
    doc.rule_accent()
    doc.set_font("Helvetica", "B", 14)
    doc.cell(0, 7, safe_pdf_text("Project"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    doc.set_font("Helvetica", "", BODY_PT)
    doc.cell(0, 6, safe_pdf_text(str(project.get("name") or "")), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if project.get("owner"):
        doc.cell(0, 5, safe_pdf_text(f"Owner: {project.get('owner')}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if project.get("gc"):
        doc.cell(0, 5, safe_pdf_text(f"General contractor: {project.get('gc')}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    doc.ln(8)
    doc.set_font("Helvetica", "", BODY_PT)
    doc.cell(0, 5, safe_pdf_text(f"Issue date: {today.isoformat()}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    doc.cell(
        0,
        5,
        safe_pdf_text(f"Proposal valid: {vd} days (through {valid_until.isoformat()})"),
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    doc.ln(6)
    doc.set_font("Helvetica", "I", SMALL_PT)
    doc.set_text_color(*TEXT_MUTED)
    doc.set_x(PAGE_MARGIN)
    doc.multi_cell(
        content_w,
        4,
        safe_pdf_text(
            "This document contains commercial and pricing information. Distribution is limited to the addressee "
            "for bid evaluation unless marked for internal use only."
        ),
    )
    doc.set_text_color(*TEXT_PRIMARY)

    # ----- Page 2 — Investment -----
    doc.add_page()
    doc.heading("Investment summary", level=1)
    doc.rule_accent()

    show_itemized = bool(line_items) and (mode == "itemized" or mode == "internal_review" or internal)

    if mode == "lump_sum" and not show_itemized:
        doc.set_font("Helvetica", "B", 16)
        doc.cell(0, 10, safe_pdf_text(f"Total lump sum: ${lump:,.2f}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        doc.set_font("Helvetica", "", BODY_PT)
        doc.ln(4)
        doc.set_x(PAGE_MARGIN)
        doc.multi_cell(
            content_w,
            LINE_HEIGHT_MM,
            safe_pdf_text(
                "The above is the consolidated contract price for the scope summarized in this proposal, "
                "subject to assumptions and payment terms herein. Detailed line breakdowns are not shown in lump-sum client mode."
            ),
        )
    else:
        if line_items:
            doc.set_font("Helvetica", "B", BODY_PT)
            doc.set_fill_color(245, 245, 245)
            doc.set_draw_color(*ac)
            doc.set_x(PAGE_MARGIN)
            doc.cell(100, 7, safe_pdf_text("Component"), border="B", new_x=XPos.RIGHT, new_y=YPos.TOP)
            doc.cell(0, 7, safe_pdf_text("Amount"), border="B", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            doc.set_font("Helvetica", "", BODY_PT)
            for row in line_items:
                if not isinstance(row, dict):
                    continue
                lbl = str(row.get("label") or "")
                try:
                    amt = float(row.get("amount") or 0)
                except (TypeError, ValueError):
                    amt = 0.0
                doc.set_x(PAGE_MARGIN)
                doc.cell(100, 6, safe_pdf_text(lbl), new_x=XPos.RIGHT, new_y=YPos.TOP)
                doc.cell(0, 6, safe_pdf_text(f"${amt:,.2f}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            doc.ln(4)
        doc.set_font("Helvetica", "B", BODY_PT)
        doc.cell(0, 7, safe_pdf_text(f"Total: ${lump:,.2f}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        doc.set_font("Helvetica", "", BODY_PT)

    cs = data.get("confidential_sections") or {}
    notes = cs.get("internal_notes") if isinstance(cs, dict) else None
    if internal and notes:
        doc.ln(6)
        doc.set_font("Helvetica", "B", BODY_PT)
        doc.cell(
            0,
            6,
            safe_pdf_text("Internal notes (not for client distribution)"),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        doc.set_font("Helvetica", "", SMALL_PT)
        for n in notes if isinstance(notes, list) else []:
            doc.set_x(PAGE_MARGIN)
            doc.multi_cell(content_w, 4, safe_pdf_text(f"- {n}"))

    # ----- Page 3 — Scope -----
    doc.add_page()
    doc.heading("Scope of work", level=1)
    doc.rule_accent()
    doc.set_font("Helvetica", "", BODY_PT)
    paras = vm.get("scope_paragraphs") or []
    if not paras:
        doc.set_x(PAGE_MARGIN)
        doc.multi_cell(content_w, LINE_HEIGHT_MM, safe_pdf_text("Scope to be attached or incorporated by reference."))
    else:
        for i, p in enumerate(paras, 1):
            doc.set_font("Helvetica", "B", BODY_PT)
            doc.cell(0, 6, safe_pdf_text(f"{i}."), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            doc.set_font("Helvetica", "", BODY_PT)
            doc.set_x(PAGE_MARGIN)
            doc.multi_cell(content_w, LINE_HEIGHT_MM, safe_pdf_text(str(p)))
            doc.ln(2)

    # ----- Page 4 — Payment + tax + assumptions -----
    doc.add_page()
    doc.heading("Payment schedule & terms", level=1)
    doc.rule_accent()
    doc.set_font("Helvetica", "B", BODY_PT)
    doc.set_x(PAGE_MARGIN)
    doc.cell(120, 7, safe_pdf_text("Milestone"), border="B", new_x=XPos.RIGHT, new_y=YPos.TOP)
    doc.cell(25, 7, safe_pdf_text("%"), border="B", new_x=XPos.RIGHT, new_y=YPos.TOP)
    doc.cell(0, 7, safe_pdf_text("Amount"), border="B", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    doc.set_font("Helvetica", "", BODY_PT)
    for row in vm.get("payment_schedule") or []:
        if not isinstance(row, dict):
            continue
        lbl = str(row.get("label") or "")
        try:
            pct = float(row.get("pct") or 0)
        except (TypeError, ValueError):
            pct = 0.0
        amt = lump * pct / 100.0
        doc.set_x(PAGE_MARGIN)
        doc.cell(120, 6, safe_pdf_text(lbl), new_x=XPos.RIGHT, new_y=YPos.TOP)
        doc.cell(25, 6, safe_pdf_text(f"{pct:.1f}"), new_x=XPos.RIGHT, new_y=YPos.TOP)
        doc.cell(0, 6, safe_pdf_text(f"${amt:,.2f}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    doc.ln(6)
    doc.set_x(PAGE_MARGIN)
    doc.set_font("Helvetica", "B", SECTION_PT)
    doc.set_text_color(*ac)
    doc.cell(0, 7, safe_pdf_text("Tax note"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    doc.set_text_color(*TEXT_PRIMARY)
    doc.set_font("Helvetica", "", BODY_PT)
    doc.set_x(PAGE_MARGIN)
    doc.multi_cell(doc.w - 2 * PAGE_MARGIN, LINE_HEIGHT_MM, safe_pdf_text(tax_note_text(vm.get("tax"))))
    doc.ln(4)
    doc.set_x(PAGE_MARGIN)
    doc.set_font("Helvetica", "B", SECTION_PT)
    doc.set_text_color(*ac)
    doc.cell(0, 7, safe_pdf_text("Assumptions"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    doc.set_text_color(*TEXT_PRIMARY)
    doc.set_font("Helvetica", "", BODY_PT)
    for a in vm.get("assumptions") or []:
        doc.set_x(PAGE_MARGIN)
        doc.multi_cell(doc.w - 2 * PAGE_MARGIN, LINE_HEIGHT_MM, safe_pdf_text(f"- {a}"))
    if not vm.get("assumptions"):
        doc.set_x(PAGE_MARGIN)
        doc.multi_cell(
            doc.w - 2 * PAGE_MARGIN,
            LINE_HEIGHT_MM,
            safe_pdf_text("- See technical exhibits and drawings incorporated by reference."),
        )

    # ----- Page 5 — Signatures -----
    doc.add_page()
    doc.heading("Acceptance", level=1)
    doc.rule_accent()
    doc.set_font("Helvetica", "", BODY_PT)
    doc.set_x(PAGE_MARGIN)
    doc.multi_cell(
        content_w,
        LINE_HEIGHT_MM,
        safe_pdf_text(
            "By signing below, the parties acknowledge receipt of this proposal and agree to negotiate a written "
            "contract that supersedes any informal understandings. This proposal is not a binding contract until "
            "fully executed agreement and any required deposits are received."
        ),
    )
    doc.ln(12)
    doc.cell(80, 8, safe_pdf_text("Authorized signature — Contractor"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    doc.line(PAGE_MARGIN, doc.get_y() + 2, PAGE_MARGIN + 75, doc.get_y() + 2)
    doc.ln(10)
    doc.cell(80, 8, safe_pdf_text("Date"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    doc.line(PAGE_MARGIN, doc.get_y() + 2, PAGE_MARGIN + 40, doc.get_y() + 2)
    doc.ln(14)
    doc.cell(80, 8, safe_pdf_text("Authorized signature — Customer / GC"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    doc.line(PAGE_MARGIN, doc.get_y() + 2, PAGE_MARGIN + 75, doc.get_y() + 2)
    doc.ln(10)
    doc.cell(80, 8, safe_pdf_text("Date"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    doc.line(PAGE_MARGIN, doc.get_y() + 2, PAGE_MARGIN + 40, doc.get_y() + 2)

    doc.output(str(out_path))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Build branded 5-page proposal PDF from JSON",
        epilog=(
            "Example: %(prog)s -i config/proposal_examples/scenario_a_lump_sum_client.json "
            "-o outputs/proposal.pdf --strict"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--input", "-i", type=Path, required=True, help="Proposal JSON (see config/proposal_input.schema.md)")
    ap.add_argument("--output", "-o", type=Path, required=True)
    ap.add_argument("--strict", action="store_true", help="Exit non-zero if validation fails")
    args = ap.parse_args()

    inp = args.input.resolve()
    if not inp.is_file():
        raise SystemExit(
            f"Missing input: {inp}\n"
            "  Use a real JSON path (not a placeholder name). Try:\n"
            "    config/proposal_examples/scenario_a_lump_sum_client.json\n"
            "  Or run: python scripts/run_proposal_pdf_tests.py"
        )

    with open(inp, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise SystemExit("Input must be a JSON object")

    errs = validate_proposal(data)
    if errs:
        for e in errs:
            print(f"Validation: {e}", flush=True)
        if args.strict:
            raise SystemExit(1)

    out = args.output
    if not out.is_absolute():
        out = (Path.cwd() / out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    render_pdf(data, out)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
