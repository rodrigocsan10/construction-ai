#!/usr/bin/env python3
"""
Price drywall takeoff using drywall_insulation.json subcontract sheet rates + insulation floors.

Reads:
  - outputs/takeoff_drywall.json
  - config/Trades/drywall_insulation.json
  - config/ company.json (tax / markup alignment with framing)

Writes:
  - outputs/estimate_drywall_priced.json
  - outputs/estimate_drywall_priced.xlsx
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pricing_utils import retainage_reference

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_TAKEOFF = _PROJECT_ROOT / "outputs" / "takeoff_drywall.json"
_TRADE = _PROJECT_ROOT / "config" / "Trades" / "drywall_insulation.json"
_OUTPUT_DIR = _PROJECT_ROOT / "outputs"


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


def write_xlsx(path: Path, summary: list[dict[str, Any]], lines: list[dict[str, Any]]) -> None:
    try:
        import pandas as pd
    except ImportError:
        return
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        pd.DataFrame(summary).to_excel(w, sheet_name="Summary", index=False)
        pd.DataFrame(lines).to_excel(w, sheet_name="Detail", index=False)


def main() -> None:
    ap = argparse.ArgumentParser(description="Price drywall + insulation takeoff")
    ap.add_argument("--takeoff", type=Path, default=_DEFAULT_TAKEOFF)
    ap.add_argument("--trade", type=Path, default=_TRADE)
    ap.add_argument("--finish-level", type=int, default=None, help="0-5 (default from trade config)")
    ap.add_argument("--vertical-carry", action="store_true", help="Apply $/sheet/floor when multifamily")
    ap.add_argument("--tax-pct", type=float, default=None)
    ap.add_argument("--tax-exempt", action="store_true")
    ap.add_argument("--markup-pct", type=float, default=None, help="On material allowance (sub labor is fixed)")
    ap.add_argument(
        "--mobilization-round-trip-miles",
        type=float,
        default=0.0,
        help="KB mobilization: miles × company rate × days (with --mobilization-working-days)",
    )
    ap.add_argument("--mobilization-working-days", type=int, default=0)
    ap.add_argument(
        "--skip-kb-extras",
        action="store_true",
        help="Omit fire caulk / furring / scissor lines from takeoff kb_optional_allowances",
    )
    ap.add_argument("-o", type=Path, dest="out", default=_OUTPUT_DIR / "estimate_drywall_priced.json")
    args = ap.parse_args()

    tpath = args.takeoff.resolve()
    if not tpath.is_file():
        print(f"Missing {tpath}")
        raise SystemExit(1)

    takeoff = load_json(tpath)
    trade = load_json(args.trade.resolve())
    company = load_json(company_path(_PROJECT_ROOT))

    pricing = trade.get("pricing") or {}
    hang = float(pricing.get("hang_per_sheet", 10))
    fin_key = str(args.finish_level if args.finish_level is not None else pricing.get("default_when_plans_silent", 4))
    levels = pricing.get("finish_levels") or {}
    fin_block = levels.get(fin_key) or levels.get(str(fin_key)) or {}
    finish = float(fin_block.get("finish_cost", 11))
    labor_per_sheet = hang + finish

    totals = takeoff.get("totals") or {}
    sheets = int(totals.get("total_sheet_count_est") or 0)
    wall_sheets = int(totals.get("wall_sheet_count_est") or 0)
    ceil_sheets = int(totals.get("ceiling_sheet_count_est") or 0)
    insul_sf = float(totals.get("insulation_sf") or 0)
    insul_batt_pcs = int(totals.get("insulation_wall_batt_pieces_est") or 0)
    insul_fg_bags = int(totals.get("insulation_fiberglass_bags_est") or 0)
    insul_mw_bundles = int(totals.get("insulation_mineral_wool_bundles_est") or 0)
    insul_ceil_batt_pcs = int(totals.get("insulation_ceiling_batt_pieces_est") or 0)

    ins_cfg = trade.get("insulation") or {}
    ins_p = ins_cfg.get("pricing") or {}
    # Split insulation cost by kind from wall rows
    fg_sf = mw_sf = 0.0
    for row in takeoff.get("wall_rows") or []:
        if not isinstance(row, dict):
            continue
        try:
            s = float(row.get("insulation_sf") or 0)
        except (TypeError, ValueError):
            s = 0.0
        if s <= 0:
            continue
        k = str(row.get("insulation_kind", "fiberglass_batt"))
        if k == "mineral_wool":
            mw_sf += s
        else:
            fg_sf += s

    try:
        fg_rate = float((ins_p.get("fiberglass_batt") or {}).get("minimum_installed_per_sf", 1.25))
    except (TypeError, ValueError):
        fg_rate = 1.25
    try:
        mw_rate = float((ins_p.get("mineral_wool") or {}).get("minimum_installed_per_sf", 2.0))
    except (TypeError, ValueError):
        mw_rate = 2.0

    insulation_client = fg_sf * fg_rate + mw_sf * mw_rate

    proj = takeoff.get("project") or {}
    try:
        floors = max(1, int(float(proj.get("floors") or 1)))
    except (TypeError, ValueError):
        floors = 1

    vcarry = trade.get("vertical_carry") or {}
    try:
        v_rate = float(vcarry.get("charge_per_sheet_per_floor", 0.75))
    except (TypeError, ValueError):
        v_rate = 0.75
    vertical_charge = 0.0
    if args.vertical_carry and floors > 1:
        # sheets × floors above grade-1 approximated as floors-1
        vertical_charge = sheets * v_rate * max(0, floors - 1)

    kb = takeoff.get("kb_optional_allowances") or {}
    kb_fire = kb_fur = kb_lift = 0.0
    if not args.skip_kb_extras:
        try:
            kb_fire = float(kb.get("fire_caulking_usd") or 0)
        except (TypeError, ValueError):
            kb_fire = 0.0
        try:
            kb_fur = float(kb.get("furring_extra_usd") or 0)
        except (TypeError, ValueError):
            kb_fur = 0.0
        try:
            kb_lift = float(kb.get("scissor_lift_usd") or 0)
        except (TypeError, ValueError):
            kb_lift = 0.0
    kb_extras = kb_fire + kb_fur + kb_lift

    try:
        mob_rate = float(company.get("mobilization_rate_per_mile", 0.5))
    except (TypeError, ValueError):
        mob_rate = 0.5
    mob_days = max(0, int(args.mobilization_working_days or 0))
    mob_miles = max(0.0, float(args.mobilization_round_trip_miles or 0))
    drywall_mobilization = mob_miles * mob_rate * mob_days if mob_days > 0 and mob_miles > 0 else 0.0

    labor_sub_total = (
        sheets * labor_per_sheet + vertical_charge + insulation_client + kb_extras + drywall_mobilization
    )

    try:
        mat_markup_cfg = float(pricing.get("material_markup_percent", 10))
    except (TypeError, ValueError):
        mat_markup_cfg = 10.0
    markup_pct = args.markup_pct if args.markup_pct is not None else mat_markup_cfg
    # Subcontract model: hang/finish already "client" rates; optional small markup pass on whole sub total
    markup_dollars = labor_sub_total * (markup_pct / 100.0)

    try:
        tax = float(company.get("default_tax_rate_percent", 6.625)) if args.tax_pct is None else args.tax_pct
    except (TypeError, ValueError):
        tax = 6.625
    taxable = labor_sub_total + markup_dollars
    tax_d = 0.0 if args.tax_exempt else taxable * (tax / 100.0)

    grand = taxable + tax_d
    ret_ref = retainage_reference(company, grand)

    summary_rows = [
        {"line": "Hang + finish (per sheet) × total sheets", "detail": f"{sheets} @ ${labor_per_sheet:.2f}/sheet", "usd": round(sheets * labor_per_sheet, 2)},
        {"line": "  (wall sheets)", "detail": str(wall_sheets), "usd": ""},
        {"line": "  (ceiling sheets)", "detail": str(ceil_sheets), "usd": ""},
        {"line": "Insulation (floor pricing)", "detail": f"FG SF {fg_sf:.0f} @ {fg_rate} + MW SF {mw_sf:.0f} @ {mw_rate}", "usd": round(insulation_client, 2)},
        {
            "line": "Insulation order qty (est.)",
            "detail": (
                f"wall batts {insul_batt_pcs}; FG bags {insul_fg_bags}; MW bundles {insul_mw_bundles}"
                + (f"; ceiling batt pcs {insul_ceil_batt_pcs}" if insul_ceil_batt_pcs else "")
            ),
            "usd": "",
        },
        {"line": "Vertical carry", "detail": f"floors={floors}" if args.vertical_carry else "off", "usd": round(vertical_charge, 2)},
        {
            "line": "KB: fire caulking (est.)",
            "detail": f"fire-rated wall SF {kb.get('fire_rated_wall_sf', 0)}" if kb_fire else "—",
            "usd": round(kb_fire, 2) if kb_fire else "",
        },
        {
            "line": "KB: furring / RC extra (est.)",
            "detail": f"furring-related SF {kb.get('furring_channel_wall_sf', 0)}" if kb_fur else "—",
            "usd": round(kb_fur, 2) if kb_fur else "",
        },
        {
            "line": "KB: scissor lift (1 mo est.)",
            "detail": f"wall h > {kb.get('wall_height_ft', '')} ft" if kb_lift else "—",
            "usd": round(kb_lift, 2) if kb_lift else "",
        },
        {
            "line": "Mobilization (KB formula)",
            "detail": f"{mob_miles} RT mi × ${mob_rate} × {mob_days} days" if drywall_mobilization else "off",
            "usd": round(drywall_mobilization, 2) if drywall_mobilization else "",
        },
        {"line": f"Markup ({markup_pct}%)", "detail": "on sub total", "usd": round(markup_dollars, 2)},
        {"line": "Sales tax", "detail": f"{tax}%" if not args.tax_exempt else "exempt", "usd": round(tax_d, 2)},
        {"line": "GRAND TOTAL", "detail": "", "usd": round(grand, 2)},
    ]
    if float(ret_ref.get("typical_holdback_usd") or 0) > 0:
        summary_rows.extend(
            [
                {
                    "line": f"Retainage reference ({ret_ref.get('retainage_percent', 0)}%)",
                    "detail": str(ret_ref.get("note", ""))[:80],
                    "usd": float(ret_ref["typical_holdback_usd"]),
                },
                {
                    "line": "Net if retainage held (informational)",
                    "detail": "",
                    "usd": float(ret_ref["net_if_retainage_held_usd"]),
                },
            ]
        )

    priced = {
        "inputs": {
            "finish_level": fin_key,
            "hang_per_sheet": hang,
            "finish_per_sheet": finish,
            "labor_per_sheet_combined": labor_per_sheet,
            "vertical_carry_applied": bool(args.vertical_carry),
            "mobilization_round_trip_miles": mob_miles,
            "mobilization_working_days": mob_days,
            "kb_extras_skipped": bool(args.skip_kb_extras),
            "markup_percent": markup_pct,
            "tax_percent": 0.0 if args.tax_exempt else tax,
            "tax_model_note": "Subcontract bundle: tax on (subtotal + markup), not materials-first ladder",
        },
        "summary_usd": {
            "drywall_labor_sheets": round(sheets * labor_per_sheet, 2),
            "insulation": round(insulation_client, 2),
            "vertical_carry": round(vertical_charge, 2),
            "kb_extras_fire_furr_lift": round(kb_extras, 2),
            "mobilization": round(drywall_mobilization, 2),
            "markup": round(markup_dollars, 2),
            "sales_tax": round(tax_d, 2),
            "grand_total": round(grand, 2),
        },
        "summary_table": summary_rows,
        "retainage_reference": ret_ref,
    }

    out = args.out
    if not out.is_absolute():
        out = (Path.cwd() / out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"source_takeoff": str(tpath), "pricing": priced, "takeoff_totals": totals}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    xlsx = out.with_name("estimate_drywall_priced.xlsx")
    write_xlsx(xlsx, summary_rows, takeoff.get("wall_rows") or [])

    print(f"Wrote {out}")
    if xlsx.is_file():
        print(f"Wrote {xlsx}")
    print(f"Grand total (client): ${grand:,.2f}")


if __name__ == "__main__":
    main()
