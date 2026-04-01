#!/usr/bin/env python3
"""
Sprint 4 — Price framing takeoff (material tax → markup → labor line → mobilization).

Reads:
  - outputs/takeoff_framing.json
  - config/ company.json (or config/company.json)
  - config/Trades/rough_framing.json (benchmarks)
  - config/Trades/framing_unit_costs.json

KB order for materials:
  raw material → sales tax on materials → material markup → extended

Writes:
  - outputs/estimate_framing_priced.json
  - outputs/estimate_framing_priced.xlsx (if pandas)
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_TAKEOFF = _PROJECT_ROOT / "outputs" / "takeoff_framing.json"
_OUTPUT_DIR = _PROJECT_ROOT / "outputs"
_TRADE = _PROJECT_ROOT / "config" / "Trades" / "rough_framing.json"
_UNIT_COSTS = _PROJECT_ROOT / "config" / "Trades" / "framing_unit_costs.json"
_EQUIPMENT = _PROJECT_ROOT / "config" / "equipment.json"


def company_path(root: Path) -> Path:
    spaced = root / "config" / " company.json"
    if spaced.is_file():
        return spaced
    return root / "config" / "company.json"


def load_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(path)
    return data


def unit_cost_for_line(
    line: dict[str, Any],
    costs: dict[str, Any],
) -> tuple[float, str]:
    """Return (unit_price, rule_note)."""
    item = str(line.get("item", ""))
    cat = str(line.get("category", ""))
    by_kw = costs.get("by_item_keyword") or {}
    best_k, best_v = "", 0.0
    for k, v in by_kw.items():
        if str(k).startswith("_"):
            continue
        if k.lower() in item.lower() and len(str(k)) > len(best_k):
            try:
                best_v = float(v)
                best_k = str(k)
            except (TypeError, ValueError):
                pass
    if best_k:
        return best_v, f"keyword:{best_k}"
    cat_d = costs.get("by_category") or {}
    try:
        c = float(cat_d.get(cat, 0))
    except (TypeError, ValueError):
        c = 0.0
    if c > 0:
        return c, f"category:{cat}"
    try:
        d = float(costs.get("default_unit_cost", 0))
    except (TypeError, ValueError):
        d = 0.0
    return d, "default_unit_cost"


def building_sf(takeoff: dict[str, Any], override_sf: float | None) -> tuple[float, str]:
    if override_sf and override_sf > 0:
        return override_sf, "cli"
    proj = takeoff.get("project") or {}
    try:
        tsf = float(proj.get("total_sf") or 0)
    except (TypeError, ValueError):
        tsf = 0.0
    if tsf > 0:
        return tsf, "project.total_sf"
    return 0.0, "missing"


def labor_rate_per_sf(
    project_type: str,
    unit_costs: dict[str, Any],
    roof_tier: str,
) -> tuple[float, str]:
    """$/building SF; rafter tier applies KB-style multiplier from framing_unit_costs.json."""
    pt = (project_type or "").lower()
    rates = unit_costs.get("labor_dollars_per_building_sf") or {}
    is_comm = "multi" in pt or "commercial" in pt
    if is_comm:
        try:
            base = float(rates.get("commercial_multifamily", 2.75))
        except (TypeError, ValueError):
            base = 2.75
        if roof_tier == "rafter":
            try:
                m = float(rates.get("commercial_multifamily_rafter_multiplier", 1.12))
            except (TypeError, ValueError):
                m = 1.12
            return base * m, f"commercial_multifamily × rafter_mult {m}"
        return base, "commercial_multifamily"
    try:
        base = float(rates.get("residential", 7.5))
    except (TypeError, ValueError):
        base = 7.5
    if roof_tier == "rafter":
        try:
            m = float(rates.get("residential_rafter_multiplier", 1.35))
        except (TypeError, ValueError):
            m = 1.35
        return base * m, f"residential × rafter_mult {m}"
    return base, "residential (truss/engineered tier)"


def roof_tier_from_takeoff(takeoff: dict[str, Any]) -> str:
    fre = takeoff.get("floor_roof_estimating") or {}
    tier = fre.get("roof_labor_tier")
    if tier == "rafter":
        return "rafter"
    return "truss_engineered"


def blockout_usd(
    trade: dict[str, Any],
    working_days: int,
    project_type: str,
    enabled: bool,
) -> tuple[float, dict[str, Any]]:
    if not enabled or working_days <= 0:
        return 0.0, {"applied": False}
    pt = (project_type or "").lower()
    if not any(x in pt for x in ("multi", "commercial", "apartment", "condo")):
        return 0.0, {"applied": False, "reason": "KB blockout is commercial/multifamily only"}
    bc = trade.get("blockout_crew") or {}
    cs = bc.get("crew_size") or {}
    try:
        crew_mid = (float(cs.get("min", 2)) + float(cs.get("max", 3))) / 2.0
    except (TypeError, ValueError):
        crew_mid = 2.5
    try:
        hr = float(bc.get("hourly_rate", 30))
    except (TypeError, ValueError):
        hr = 30.0
    try:
        hday = float(bc.get("hours_per_day", 9))
    except (TypeError, ValueError):
        hday = 9.0
    days = max(1, working_days // 2)
    cost = crew_mid * hr * hday * days
    return cost, {
        "applied": True,
        "crew_equivalent": crew_mid,
        "days": days,
        "hourly": hr,
        "hours_per_day": hday,
        "note": "KB: blockout ≈ half of framing duration",
    }


def equipment_allowance_usd(equipment_cfg: dict[str, Any], months: float) -> tuple[float, dict[str, Any]]:
    if months <= 0:
        return 0.0, {"applied": False}
    monthly = equipment_cfg.get("monthly_usd") or {}
    try:
        rate = float(monthly.get("genie_lift_boom_scissor", 5000))
    except (TypeError, ValueError):
        rate = 5000.0
    return rate * months, {"applied": True, "months": months, "monthly_rate": rate, "note": "Primary aerial/monthly allowance — calibrate to rental quote"}


def price_takeoff(
    takeoff: dict[str, Any],
    company: dict[str, Any],
    trade: dict[str, Any],
    unit_costs: dict[str, Any],
    *,
    material_markup_pct: float,
    tax_pct: float,
    tax_exempt: bool,
    scope_labor_and_material: bool,
    round_trip_miles: float,
    working_days: int,
    building_sf_override: float | None,
    include_blockout: bool,
    equipment_months: float,
    equipment_cfg: dict[str, Any],
) -> dict[str, Any]:
    supplier = takeoff.get("supplier_list") or []
    if not isinstance(supplier, list):
        supplier = []

    priced_lines: list[dict[str, Any]] = []
    material_raw = 0.0

    for line in supplier:
        if not isinstance(line, dict):
            continue
        qty_raw = line.get("quantity", 0)
        try:
            qty = float(qty_raw)
        except (TypeError, ValueError):
            qty = 0.0
        unit = str(line.get("unit", "EA"))
        uc, rule = unit_cost_for_line(line, unit_costs)
        ext = qty * uc
        material_raw += ext
        priced_lines.append(
            {
                **line,
                "unit_cost_usd": round(uc, 2),
                "pricing_rule": rule,
                "extension_usd": round(ext, 2),
            }
        )

    tax_mult = 0.0 if tax_exempt or not scope_labor_and_material else tax_pct / 100.0
    material_tax = material_raw * tax_mult if scope_labor_and_material else 0.0
    material_after_tax = material_raw + material_tax
    markup_mult = material_markup_pct / 100.0 if scope_labor_and_material else 0.0
    material_markup_dollars = material_after_tax * markup_mult
    material_to_client = material_after_tax + material_markup_dollars

    bsf, bsf_src = building_sf(takeoff, building_sf_override)
    proj = takeoff.get("project") or {}
    ptype = str(proj.get("type", "commercial"))
    rtier = roof_tier_from_takeoff(takeoff)
    labor_per_sf, labor_rule = labor_rate_per_sf(ptype, unit_costs, rtier)
    labor_subtotal = bsf * labor_per_sf if bsf > 0 else 0.0

    mob_rate = float(company.get("mobilization_rate_per_mile", 0.5))
    mobilization = max(0.0, round_trip_miles) * mob_rate * max(0, working_days)

    b_amt, b_detail = blockout_usd(trade, working_days, ptype, include_blockout)
    eq_amt, eq_detail = equipment_allowance_usd(equipment_cfg, equipment_months)

    subtotal_pre_ops = material_to_client + labor_subtotal + mobilization + b_amt + eq_amt

    oh = float(company.get("overhead_percent", 0) or 0)
    pr = float(company.get("profit_percent", 0) or 0)
    # Simple: OH+profit on subtotal (excludes showing separate tax in OH base — v1)
    oh_d = subtotal_pre_ops * (oh / 100.0)
    profit_d = (subtotal_pre_ops + oh_d) * (pr / 100.0) if pr else 0.0
    grand_total = subtotal_pre_ops + oh_d + profit_d

    return {
        "inputs": {
            "material_markup_percent": material_markup_pct,
            "sales_tax_percent": 0.0 if tax_exempt else tax_pct,
            "tax_exempt": tax_exempt,
            "scope_labor_and_material": scope_labor_and_material,
            "round_trip_miles": round_trip_miles,
            "working_days": working_days,
            "building_sf_used": bsf,
            "building_sf_source": bsf_src,
            "labor_dollars_per_building_sf": labor_per_sf,
            "labor_rate_rule": labor_rule,
            "roof_labor_tier": rtier,
        },
        "material": {
            "raw_subtotal": round(material_raw, 2),
            "sales_tax_on_materials": round(material_tax, 2),
            "after_tax": round(material_after_tax, 2),
            "markup_dollars": round(material_markup_dollars, 2),
            "material_to_client": round(material_to_client, 2),
        },
        "labor_framing_est": {
            "subtotal": round(labor_subtotal, 2),
            "note": "LF-based labor not modeled — $/building SF from framing_unit_costs.json; roof tier from takeoff floor_roof_estimating",
        },
        "blockout_crew": {"usd": round(b_amt, 2), **b_detail},
        "equipment_allowance": {"usd": round(eq_amt, 2), **eq_detail},
        "mobilization": round(mobilization, 2),
        "overhead_usd": round(oh_d, 2),
        "profit_usd": round(profit_d, 2),
        "grand_total_client": round(grand_total, 2),
        "priced_supplier_lines": priced_lines,
        "benchmarks_reference": trade.get("pricing_benchmarks"),
        "retainage_percent_note": company.get("retainage_percent"),
    }


def write_xlsx(path: Path, priced: dict[str, Any]) -> None:
    try:
        import pandas as pd
    except ImportError:
        return
    rows = priced.get("priced_supplier_lines") or []
    if not rows:
        return
    rows_sum = [
        {"item": "Material raw", "usd": priced["material"]["raw_subtotal"]},
        {"item": "Sales tax (materials)", "usd": priced["material"]["sales_tax_on_materials"]},
        {"item": "Material markup", "usd": priced["material"]["markup_dollars"]},
        {"item": "Material to client", "usd": priced["material"]["material_to_client"]},
        {"item": "Labor (est)", "usd": priced["labor_framing_est"]["subtotal"]},
        {"item": "Mobilization", "usd": priced["mobilization"]},
    ]
    bo = priced.get("blockout_crew") or {}
    if float(bo.get("usd") or 0) > 0:
        rows_sum.append({"item": "Blockout crew (KB est.)", "usd": bo["usd"]})
    eq = priced.get("equipment_allowance") or {}
    if float(eq.get("usd") or 0) > 0:
        rows_sum.append({"item": "Equipment allowance (monthly × months)", "usd": eq["usd"]})
    rows_sum.extend(
        [
            {"item": "Overhead", "usd": priced["overhead_usd"]},
            {"item": "Profit", "usd": priced["profit_usd"]},
            {"item": "GRAND TOTAL", "usd": priced["grand_total_client"]},
        ]
    )
    summary = pd.DataFrame(rows_sum)
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        pd.DataFrame(rows).to_excel(w, sheet_name="Line items", index=False)
        summary.to_excel(w, sheet_name="Summary", index=False)


def main() -> None:
    ap = argparse.ArgumentParser(description="Price framing takeoff (Sprint 4).")
    ap.add_argument("--takeoff", type=Path, default=_DEFAULT_TAKEOFF)
    ap.add_argument("--company", type=Path, default=None)
    ap.add_argument("--markup-pct", type=float, default=None, help="Material markup %% (default: mid of company min/max)")
    ap.add_argument("--tax-pct", type=float, default=None, help="Sales tax on materials (default company)")
    ap.add_argument("--tax-exempt", action="store_true")
    ap.add_argument("--labor-only-scope", action="store_true", help="No tax/markup on materials (materials by owner)")
    ap.add_argument("--round-trip-miles", type=float, default=0.0)
    ap.add_argument("--working-days", type=int, default=0)
    ap.add_argument("--building-sf", type=float, default=None, help="Gross SF for labor $/SF when total_sf is 0")
    ap.add_argument(
        "--include-blockout",
        action="store_true",
        help="Add commercial/multifamily blockout crew (half of --working-days) per KB",
    )
    ap.add_argument(
        "--equipment-months",
        type=float,
        default=0.0,
        help="Equipment allowance = monthly rate × months (0=off); see config/equipment.json",
    )
    ap.add_argument("--equipment", type=Path, default=None, help="Override equipment.json path")
    ap.add_argument("-o", type=Path, dest="out", default=_OUTPUT_DIR / "estimate_framing_priced.json")
    args = ap.parse_args()

    takeoff_path = args.takeoff.resolve()
    if not takeoff_path.is_file():
        print(f"Takeoff not found: {takeoff_path}")
        raise SystemExit(1)

    takeoff = load_json(takeoff_path)
    cpath = args.company.resolve() if args.company else company_path(_PROJECT_ROOT)
    if not cpath.is_file():
        print(f"Company config not found: {cpath}")
        raise SystemExit(1)
    company = load_json(cpath)
    trade = load_json(_TRADE)
    unit_costs = load_json(_UNIT_COSTS) if _UNIT_COSTS.is_file() else {}
    eq_path = args.equipment.resolve() if args.equipment else _EQUIPMENT
    equipment_cfg = load_json(eq_path) if eq_path.is_file() else {}

    try:
        mn = float(company.get("material_markup_min_percent", 10))
        mx = float(company.get("material_markup_max_percent", 12))
        mid = (mn + mx) / 2.0
    except (TypeError, ValueError):
        mid = 11.0
    markup = args.markup_pct if args.markup_pct is not None else mid
    if markup < mn - 0.001 or markup > mx + 0.001:
        print(
            f"Warning: material markup {markup}% is outside KB band {mn}–{mx}% (company.json).",
            flush=True,
        )

    try:
        tax = float(company.get("default_tax_rate_percent", 6.625))
    except (TypeError, ValueError):
        tax = 6.625
    if args.tax_pct is not None:
        tax = args.tax_pct

    scope_lm = not args.labor_only_scope

    priced = price_takeoff(
        takeoff,
        company,
        trade,
        unit_costs,
        material_markup_pct=markup,
        tax_pct=tax,
        tax_exempt=args.tax_exempt,
        scope_labor_and_material=scope_lm,
        round_trip_miles=args.round_trip_miles,
        working_days=args.working_days,
        building_sf_override=args.building_sf,
        include_blockout=args.include_blockout,
        equipment_months=max(0.0, float(args.equipment_months or 0)),
        equipment_cfg=equipment_cfg,
    )

    out = args.out
    if not out.is_absolute():
        out = (Path.cwd() / out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "project": takeoff.get("project"),
        "source_takeoff": str(takeoff_path),
        "pricing": priced,
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    xlsx = out.with_name("estimate_framing_priced.xlsx")
    write_xlsx(xlsx, priced)

    print(f"Wrote {out}")
    if xlsx.is_file():
        print(f"Wrote {xlsx}")
    g = priced["grand_total_client"]
    print(f"Grand total (client): ${g:,.2f}")
    if priced["inputs"]["building_sf_used"] <= 0:
        print("Note: building SF is 0 — labor line is $0. Pass --building-sf (e.g. 55000) for multifamily labor est.")


if __name__ == "__main__":
    main()
