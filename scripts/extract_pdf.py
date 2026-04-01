#!/usr/bin/env python3
"""
Construction takeoff: PDF → OpenAI → quantities → pricing → JSON + Excel.
Edit the PRICING and MARKUP sections at the top to match your jobs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_OUTPUT_DIR = _PROJECT_ROOT / "outputs"

load_dotenv(_PROJECT_ROOT / ".env")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# =============================================================================
# PRICING ($ per unit) — material vs labor split (tune for your market)
# =============================================================================
DRYWALL_MATERIAL_PER_SF = 0.55
DRYWALL_LABOR_PER_SF = 0.70

FRAMING_MATERIAL_PER_LF = 8.00
FRAMING_LABOR_PER_LF = 10.00

DOOR_MATERIAL_EACH = 85.00
DOOR_LABOR_EACH = 65.00

WINDOW_MATERIAL_EACH = 70.00
WINDOW_LABOR_EACH = 50.00

ROOFING_MATERIAL_PER_SF = 2.10
ROOFING_LABOR_PER_SF = 1.85

SHEATHING_MATERIAL_PER_SF = 1.40
SHEATHING_LABOR_PER_SF = 0.95

# Concrete: priced when unit is CY or SF (otherwise $0 — review manually)
CONCRETE_MATERIAL_PER_CY = 145.00
CONCRETE_LABOR_PER_CY = 110.00
CONCRETE_SLAB_MATERIAL_PER_SF = 0.35
CONCRETE_SLAB_LABOR_PER_SF = 0.28

# Applied to (material + labor) direct cost before final total
MARKUP_PERCENT = 15.0

# -----------------------------------------------------------------------------
# JSON schema for OpenAI Structured Outputs (strict)
# -----------------------------------------------------------------------------
TAKEOFF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "drywall_sf": {"type": "number", "description": "Drywall area in SF"},
        "framing_lf": {"type": "number", "description": "Framing linear feet"},
        "roofing_sf": {"type": "number", "description": "Roofing area SF"},
        "sheathing_sf": {"type": "number", "description": "Wall/roof sheathing SF"},
        "doors": {
            "type": "array",
            "description": "Door schedule entries",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "type": {"type": "string"},
                    "count": {"type": "number"},
                },
                "required": ["type", "count"],
            },
        },
        "windows": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "type": {"type": "string"},
                    "count": {"type": "number"},
                },
                "required": ["type", "count"],
            },
        },
        "concrete": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "element": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit": {"type": "string", "description": "CY, SF, LF, etc."},
                },
                "required": ["element", "quantity", "unit"],
            },
        },
    },
    "required": [
        "drywall_sf",
        "framing_lf",
        "roofing_sf",
        "sheathing_sf",
        "doors",
        "windows",
        "concrete",
    ],
}

PROMPT_JSON = """You are a construction estimator. Read the attached plan PDF.

Return ONLY data that matches the JSON schema (no markdown, no extra text).
Rules:
- Use numbers only for quantities (estimate decisively if unclear).
- Use 0 for unknown areas/lengths when you must pick a number.
- doors/windows: list each distinct type with count; use empty arrays if none.
- concrete: list each element (slab, footing, stairs, etc.) with quantity + unit (CY, SF, LF).
- roofing_sf: total roof area. sheathing_sf: structural sheathing (walls + roof deck) if shown.
Be consistent and practical for residential/light commercial."""

PROMPT_TEXT_FALLBACK = """You are a construction estimator performing a takeoff.

From this plan, extract measurable quantities. Return STRICTLY in this format:

Drywall (SF): [number]
Framing (LF): [number]
Roofing (SF): [number]
Sheathing (SF): [number]

Doors:
- Type: [tag or size] | Count: [number]

Windows:
- Type: [tag or size] | Count: [number]

Concrete:
- Element: [name] | Quantity: [number] [unit]

Rules: always use numbers; estimate if needed; no "not specified"; be decisive."""


# =============================================================================
# Helpers
# =============================================================================
def clean_number(value: str | None) -> float | None:
    if value is None:
        return None
    value = str(value).replace(",", "").strip()
    if not value:
        return None
    try:
        n = float(value)
        if n.is_integer():
            return int(n)
        return n
    except ValueError:
        return None


def safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def extract_json_from_response(text: str) -> dict[str, Any]:
    """Parse JSON; strip ```json fences if present."""
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


def get_section(text: str, section_name: str, next_section: str | None = None) -> str:
    if next_section:
        pattern = rf"{re.escape(section_name)}:\s*(.*?)(?:\n\s*{re.escape(next_section)}:|\Z)"
    else:
        pattern = rf"{re.escape(section_name)}:\s*(.*?)\Z"
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def parse_line_qty(text: str, label: str) -> float | None:
    match = re.search(rf"{label}\s*:\s*([\d,.\s]+)", text, re.IGNORECASE)
    return clean_number(match.group(1)) if match else None


def parse_doors_windows(text: str, section: str, nxt: str) -> list[dict[str, Any]]:
    body = get_section(text, section, nxt)
    rows = []
    for m in re.finditer(
        r"-\s*Type:\s*(.*?)\s*\|\s*Count:\s*([\d,]+)", body, re.IGNORECASE
    ):
        c = clean_number(m.group(2))
        rows.append({"type": m.group(1).strip(), "count": c if c is not None else 0})
    # Alternate: "Type X — Count: 2"
    if not rows:
        for m in re.finditer(
            r"Type:\s*(.+?)\s*[\|—\-]\s*Count:\s*([\d,]+)", body, re.IGNORECASE
        ):
            c = clean_number(m.group(2))
            rows.append({"type": m.group(1).strip(), "count": c if c is not None else 0})
    return rows


def parse_concrete_text(text: str) -> list[dict[str, Any]]:
    body = get_section(text, "Concrete", None)
    rows = []
    for m in re.finditer(
        r"-\s*Element:\s*(.*?)\s*\|\s*Quantity:\s*([\d,.]+)\s*([A-Za-z]{1,6})?",
        body,
        re.IGNORECASE,
    ):
        qty = clean_number(m.group(2)) or 0.0
        unit = (m.group(3) or "EA").strip()
        rows.append({"element": m.group(1).strip(), "quantity": float(qty), "unit": unit})
    if not rows:
        for m in re.finditer(
            r"Element:\s*(.+?)\s*[\|]\s*Quantity:\s*(.+)", body, re.IGNORECASE
        ):
            rest = m.group(2).strip()
            num = re.match(r"([\d,.]+)\s*([A-Za-z]{1,6})?", rest)
            if num:
                q = clean_number(num.group(1)) or 0.0
                u = (num.group(2) or "EA").strip()
                rows.append({"element": m.group(1).strip(), "quantity": float(q), "unit": u})
    return rows


def takeoff_from_legacy_text(text: str) -> dict[str, Any]:
    """Rebuild takeoff dict from free-form AI text."""
    return {
        "drywall_sf": safe_float(parse_line_qty(text, r"Drywall\s*\(SF\)")),
        "framing_lf": safe_float(parse_line_qty(text, r"Framing\s*\(LF\)")),
        "roofing_sf": safe_float(parse_line_qty(text, r"Roofing\s*\(SF\)")),
        "sheathing_sf": safe_float(parse_line_qty(text, r"Sheathing\s*\(SF\)")),
        "doors": parse_doors_windows(text, "Doors", "Windows"),
        "windows": parse_doors_windows(text, "Windows", "Concrete"),
        "concrete": parse_concrete_text(text),
    }


def normalize_takeoff(data: dict[str, Any]) -> dict[str, Any]:
    """Coerce types so pricing never crashes."""
    data = dict(data)
    data["drywall_sf"] = safe_float(data.get("drywall_sf"))
    data["framing_lf"] = safe_float(data.get("framing_lf"))
    data["roofing_sf"] = safe_float(data.get("roofing_sf"))
    data["sheathing_sf"] = safe_float(data.get("sheathing_sf"))
    for key in ("doors", "windows"):
        items = data.get(key) or []
        fixed = []
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                fixed.append(
                    {
                        "type": str(it.get("type", "")).strip() or "Unknown",
                        "count": safe_float(it.get("count")),
                    }
                )
        data[key] = fixed
    conc = data.get("concrete") or []
    out_c = []
    if isinstance(conc, list):
        for it in conc:
            if not isinstance(it, dict):
                continue
            out_c.append(
                {
                    "element": str(it.get("element", "")).strip() or "Unknown",
                    "quantity": safe_float(it.get("quantity")),
                    "unit": str(it.get("unit", "EA")).strip() or "EA",
                }
            )
    data["concrete"] = out_c
    return data


def sum_counts(items: list[dict[str, Any]]) -> float:
    return sum(safe_float(i.get("count")) for i in items)


def concrete_line_costs(qty: float, unit: str) -> tuple[float, float]:
    u = re.sub(r"[^A-Za-z]", "", unit).upper()
    if u in ("CY", "CUYD", "YD3", "CUYDS"):
        mat = qty * CONCRETE_MATERIAL_PER_CY
        lab = qty * CONCRETE_LABOR_PER_CY
        return mat, lab
    if u in ("SF", "SQFT", "SQF"):
        mat = qty * CONCRETE_SLAB_MATERIAL_PER_SF
        lab = qty * CONCRETE_SLAB_LABOR_PER_SF
        return mat, lab
    return 0.0, 0.0


def extract_pdf_structured(file_path: str) -> tuple[dict[str, Any], str]:
    with open(file_path, "rb") as f:
        uploaded = client.files.create(file=f, purpose="assistants")

    result = client.responses.create(
        model="gpt-4.1",
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": PROMPT_JSON},
                    {"type": "input_file", "file_id": uploaded.id},
                ],
            }
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "construction_takeoff",
                "strict": True,
                "schema": TAKEOFF_SCHEMA,
            }
        },
    )
    raw = (result.output_text or "").strip()
    data = extract_json_from_response(raw)
    return normalize_takeoff(data), raw


def extract_pdf_text_fallback(file_path: str) -> tuple[dict[str, Any], str]:
    with open(file_path, "rb") as f:
        uploaded = client.files.create(file=f, purpose="assistants")

    result = client.responses.create(
        model="gpt-4.1",
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": PROMPT_TEXT_FALLBACK},
                    {"type": "input_file", "file_id": uploaded.id},
                ],
            }
        ],
    )
    raw = (result.output_text or "").strip()
    return normalize_takeoff(takeoff_from_legacy_text(raw)), raw


def build_costs(takeoff: dict[str, Any]) -> dict[str, Any]:
    doors_total = sum_counts(takeoff["doors"])
    windows_total = sum_counts(takeoff["windows"])

    dw_m = takeoff["drywall_sf"] * DRYWALL_MATERIAL_PER_SF
    dw_l = takeoff["drywall_sf"] * DRYWALL_LABOR_PER_SF
    fr_m = takeoff["framing_lf"] * FRAMING_MATERIAL_PER_LF
    fr_l = takeoff["framing_lf"] * FRAMING_LABOR_PER_LF
    dr_m = doors_total * DOOR_MATERIAL_EACH
    dr_l = doors_total * DOOR_LABOR_EACH
    wn_m = windows_total * WINDOW_MATERIAL_EACH
    wn_l = windows_total * WINDOW_LABOR_EACH
    rf_m = takeoff["roofing_sf"] * ROOFING_MATERIAL_PER_SF
    rf_l = takeoff["roofing_sf"] * ROOFING_LABOR_PER_SF
    sh_m = takeoff["sheathing_sf"] * SHEATHING_MATERIAL_PER_SF
    sh_l = takeoff["sheathing_sf"] * SHEATHING_LABOR_PER_SF

    conc_m = conc_l = 0.0
    concrete_lines = []
    for row in takeoff["concrete"]:
        q = row["quantity"]
        u = row["unit"]
        cm, cl = concrete_line_costs(q, u)
        conc_m += cm
        conc_l += cl
        concrete_lines.append(
            {
                "element": row["element"],
                "quantity": q,
                "unit": u,
                "material": round(cm, 2),
                "labor": round(cl, 2),
            }
        )

    total_material = dw_m + fr_m + dr_m + wn_m + rf_m + sh_m + conc_m
    total_labor = dw_l + fr_l + dr_l + wn_l + rf_l + sh_l + conc_l
    direct_cost = total_material + total_labor
    markup_amount = direct_cost * (MARKUP_PERCENT / 100.0)
    grand_total = direct_cost + markup_amount
    profit_dollars = grand_total - direct_cost
    profit_pct_of_revenue = (profit_dollars / grand_total * 100.0) if grand_total else 0.0

    line_items = [
        {
            "item": "Drywall",
            "qty": takeoff["drywall_sf"],
            "unit": "SF",
            "material_rate": DRYWALL_MATERIAL_PER_SF,
            "labor_rate": DRYWALL_LABOR_PER_SF,
            "material_total": round(dw_m, 2),
            "labor_total": round(dw_l, 2),
        },
        {
            "item": "Framing",
            "qty": takeoff["framing_lf"],
            "unit": "LF",
            "material_rate": FRAMING_MATERIAL_PER_LF,
            "labor_rate": FRAMING_LABOR_PER_LF,
            "material_total": round(fr_m, 2),
            "labor_total": round(fr_l, 2),
        },
        {
            "item": "Roofing",
            "qty": takeoff["roofing_sf"],
            "unit": "SF",
            "material_rate": ROOFING_MATERIAL_PER_SF,
            "labor_rate": ROOFING_LABOR_PER_SF,
            "material_total": round(rf_m, 2),
            "labor_total": round(rf_l, 2),
        },
        {
            "item": "Sheathing",
            "qty": takeoff["sheathing_sf"],
            "unit": "SF",
            "material_rate": SHEATHING_MATERIAL_PER_SF,
            "labor_rate": SHEATHING_LABOR_PER_SF,
            "material_total": round(sh_m, 2),
            "labor_total": round(sh_l, 2),
        },
        {
            "item": "Doors (install bundle)",
            "qty": doors_total,
            "unit": "EA",
            "material_rate": DOOR_MATERIAL_EACH,
            "labor_rate": DOOR_LABOR_EACH,
            "material_total": round(dr_m, 2),
            "labor_total": round(dr_l, 2),
        },
        {
            "item": "Windows (install bundle)",
            "qty": windows_total,
            "unit": "EA",
            "material_rate": WINDOW_MATERIAL_EACH,
            "labor_rate": WINDOW_LABOR_EACH,
            "material_total": round(wn_m, 2),
            "labor_total": round(wn_l, 2),
        },
        {
            "item": "Concrete (parsed units only)",
            "qty": "",
            "unit": "",
            "material_rate": "",
            "labor_rate": "",
            "material_total": round(conc_m, 2),
            "labor_total": round(conc_l, 2),
        },
    ]

    return {
        "line_items": line_items,
        "concrete_detail": concrete_lines,
        "totals": {
            "material": round(total_material, 2),
            "labor": round(total_labor, 2),
            "direct_cost": round(direct_cost, 2),
            "markup_percent": MARKUP_PERCENT,
            "markup_amount": round(markup_amount, 2),
            "grand_total": round(grand_total, 2),
            "profit_dollars": round(profit_dollars, 2),
            "profit_percent_of_revenue": round(profit_pct_of_revenue, 2),
        },
        "doors_total": doors_total,
        "windows_total": windows_total,
    }


def write_outputs(
    pdf_path: Path,
    takeoff: dict[str, Any],
    raw_ai: str,
    cost: dict[str, Any],
    extraction_mode: str,
) -> None:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    full = {
        "pdf_file": str(pdf_path),
        "extraction_mode": extraction_mode,
        "takeoff": takeoff,
        "raw_ai_output": raw_ai,
        "cost_breakdown": cost,
    }
    summary = {
        "pdf_file": str(pdf_path),
        "extraction_mode": extraction_mode,
        "drywall_sf": takeoff["drywall_sf"],
        "framing_lf": takeoff["framing_lf"],
        "roofing_sf": takeoff["roofing_sf"],
        "sheathing_sf": takeoff["sheathing_sf"],
        "doors_total": cost["doors_total"],
        "windows_total": cost["windows_total"],
        "totals": cost["totals"],
    }

    out_json = _OUTPUT_DIR / "output.json"
    sum_json = _OUTPUT_DIR / "estimate_summary.json"
    xlsx_path = _OUTPUT_DIR / "estimate.xlsx"

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(full, f, indent=2)

    with open(sum_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    def nz_money(v: Any) -> float:
        if v == "" or v is None:
            return 0.0
        return safe_float(v)

    rows = []
    for li in cost["line_items"]:
        line_tot = nz_money(li["material_total"]) + nz_money(li["labor_total"])
        rows.append(
            {
                "Item": li["item"],
                "Qty": li["qty"],
                "Unit": li["unit"],
                "Mat $/unit": li["material_rate"],
                "Lab $/unit": li["labor_rate"],
                "Material $": li["material_total"],
                "Labor $": li["labor_total"],
                "Line total $": round(line_tot, 2),
            }
        )

    t = cost["totals"]
    rows.append(
        {
            "Item": "--- DIRECT SUBTOTAL ---",
            "Qty": "",
            "Unit": "",
            "Mat $/unit": "",
            "Lab $/unit": "",
            "Material $": t["material"],
            "Labor $": t["labor"],
            "Line total $": t["direct_cost"],
        }
    )
    rows.append(
        {
            "Item": f"Markup ({t['markup_percent']}%)",
            "Qty": "",
            "Unit": "",
            "Mat $/unit": "",
            "Lab $/unit": "",
            "Material $": "",
            "Labor $": "",
            "Line total $": t["markup_amount"],
        }
    )
    rows.append(
        {
            "Item": "GRAND TOTAL",
            "Qty": "",
            "Unit": "",
            "Mat $/unit": "",
            "Lab $/unit": "",
            "Material $": "",
            "Labor $": "",
            "Line total $": t["grand_total"],
        }
    )
    rows.append(
        {
            "Item": "Profit % of revenue (from markup)",
            "Qty": "",
            "Unit": "",
            "Mat $/unit": "",
            "Lab $/unit": "",
            "Material $": "",
            "Labor $": "",
            "Line total $": f"{t['profit_percent_of_revenue']:.1f}%",
        }
    )

    df = pd.DataFrame(rows)
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Estimate", index=False)
        if cost["concrete_detail"]:
            pd.DataFrame(cost["concrete_detail"]).to_excel(
                writer, sheet_name="Concrete detail", index=False
            )
        pd.DataFrame(
            [
                {"field": k, "value": v}
                for k, v in takeoff.items()
                if k not in ("doors", "windows", "concrete")
            ]
            + [{"field": "doors", "value": json.dumps(takeoff["doors"])}]
            + [{"field": "windows", "value": json.dumps(takeoff["windows"])}]
            + [{"field": "concrete", "value": json.dumps(takeoff["concrete"])}]
        ).to_excel(writer, sheet_name="Takeoff snapshot", index=False)


def main() -> None:
    default_pdf = _PROJECT_ROOT / "data" / "Plan1.pdf"
    parser = argparse.ArgumentParser(
        description="Extract construction quantities from a PDF and price them."
    )
    parser.add_argument(
        "pdf",
        nargs="?",
        default=default_pdf,
        type=Path,
        help=f"Path to PDF (default: {default_pdf})",
    )
    parser.add_argument(
        "--text-only",
        action="store_true",
        help="Skip JSON schema; use legacy text format (slower to parse, more variable).",
    )
    args = parser.parse_args()

    pdf_path = args.pdf if args.pdf.is_absolute() else (Path.cwd() / args.pdf).resolve()
    if not pdf_path.is_file():
        print(
            f"Error: PDF not found: {pdf_path}\n"
            f"  Example: python scripts/extract_pdf.py data/Plan1.pdf"
        )
        raise SystemExit(1)

    print("Calling OpenAI (this may take a minute)...")
    mode = "text_fallback"
    raw = ""
    takeoff: dict[str, Any] = {}

    try:
        if args.text_only:
            takeoff, raw = extract_pdf_text_fallback(str(pdf_path))
        else:
            takeoff, raw = extract_pdf_structured(str(pdf_path))
            mode = "json_schema"
    except Exception as e:
        print(f"Structured extraction failed ({e!s}). Falling back to text format...")
        takeoff, raw = extract_pdf_text_fallback(str(pdf_path))
        mode = "text_fallback_after_error"

    cost = build_costs(takeoff)
    write_outputs(pdf_path, takeoff, raw, cost, mode)

    print("\n=== TAKEOFF (normalized) ===")
    print(json.dumps(takeoff, indent=2))
    print("\n=== TOTALS ===")
    print(json.dumps(cost["totals"], indent=2))
    print("\nSaved to outputs/:")
    print("  - output.json")
    print("  - estimate_summary.json")
    print("  - estimate.xlsx")


if __name__ == "__main__":
    main()
