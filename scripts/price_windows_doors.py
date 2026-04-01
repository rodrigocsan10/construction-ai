#!/usr/bin/env python3
"""
Price exterior window + door install (labor + handling + KB markup).

No sales tax on materials (client-supplied). Markup on subtotal per windows_doors.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pricing_utils import retainage_reference

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_TAKEOFF = _PROJECT_ROOT / "outputs" / "takeoff_windows_doors.json"
_TRADE = _PROJECT_ROOT / "config" / "Trades" / "windows_doors.json"
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


def is_commercial(project_type: str) -> bool:
    t = (project_type or "").lower()
    return any(x in t for x in ("multi", "commercial", "apartment", "condo"))


def rate_for_panels(panels: int, rates: dict[str, Any]) -> float:
    if panels >= 4:
        return float(rates.get("larger_than_triple_minimum", 150))
    if panels == 3:
        return float(rates["triple_window"])
    if panels == 2:
        return float(rates["double_window"])
    return float(rates["single_window"])


def write_xlsx(path: Path, rows: list[dict[str, Any]], summary: list[dict[str, Any]]) -> None:
    try:
        import pandas as pd
    except ImportError:
        return
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        pd.DataFrame(rows).to_excel(w, sheet_name="Line items", index=False)
        pd.DataFrame(summary).to_excel(w, sheet_name="Summary", index=False)


def main() -> None:
    ap = argparse.ArgumentParser(description="Price window/door install takeoff")
    ap.add_argument("--takeoff", type=Path, default=_DEFAULT_TAKEOFF)
    ap.add_argument("--trade", type=Path, default=_TRADE)
    ap.add_argument("--markup-pct", type=float, default=None, help="Override config final markup %%")
    ap.add_argument("-o", type=Path, dest="out", default=_OUTPUT_DIR / "estimate_windows_doors_priced.json")
    args = ap.parse_args()

    tpath = args.takeoff.resolve()
    if not tpath.is_file():
        print(f"Missing {tpath} — run takeoff_windows_doors.py first")
        raise SystemExit(1)

    takeoff = load_json(tpath)
    trade = load_json(args.trade.resolve())
    proj = takeoff.get("project") or {}
    ptype = str(proj.get("type", "residential"))
    commercial = is_commercial(ptype)

    inst = trade.get("install_rates") or {}
    rates = inst.get("commercial_multifamily" if commercial else "residential") or {}
    if not rates:
        rates = inst.get("residential") or {}

    handle = trade.get("handling_charges") or {}
    h_win = float(handle.get("per_window", 20))
    h_door = float(handle.get("per_exterior_door", 15))

    mk = trade.get("markup") or {}
    markup_pct = float(args.markup_pct if args.markup_pct is not None else mk.get("final_markup_percent", 20))

    lines: list[dict[str, Any]] = []
    install_sub = 0.0

    for w in takeoff.get("exterior_windows") or []:
        if not isinstance(w, dict):
            continue
        c = int(w.get("count") or 0)
        if c <= 0:
            continue
        panels = int(w.get("panels") or 1)
        r = rate_for_panels(panels, rates)
        ext = c * r
        install_sub += ext
        lines.append(
            {
                "kind": "window",
                "tag": w.get("tag"),
                "description": f"{w.get('type')} ({panels}L) ×{c}",
                "unit_rate": r,
                "qty": c,
                "install_usd": round(ext, 2),
            }
        )

    for d in takeoff.get("exterior_doors") or []:
        if not isinstance(d, dict):
            continue
        c = int(d.get("count") or 0)
        if c <= 0:
            continue
        if str(d.get("category")) == "sliding_glass":
            r = float(rates.get("sliding_glass_door_assembly", 250))
        else:
            r = float(rates.get("exterior_door_each", rates.get("double_window", 75)))
        ext = c * r
        install_sub += ext
        lines.append(
            {
                "kind": "door",
                "tag": d.get("tag"),
                "description": f"{d.get('type')} ({d.get('category')}) ×{c}",
                "unit_rate": r,
                "qty": c,
                "install_usd": round(ext, 2),
            }
        )

    tw = sum(int(w.get("count") or 0) for w in takeoff.get("exterior_windows") or [] if isinstance(w, dict))
    td = sum(int(d.get("count") or 0) for d in takeoff.get("exterior_doors") or [] if isinstance(d, dict))
    handling = tw * h_win + td * h_door

    sub = install_sub + handling
    markup_amt = sub * (markup_pct / 100.0)
    grand = sub + markup_amt

    company = load_json(company_path(_PROJECT_ROOT))
    ret_ref = retainage_reference(company, grand)

    summary = [
        {"line": "Install subtotal", "usd": round(install_sub, 2)},
        {"line": f"Handling ({tw} win @ {h_win} + {td} dr @ {h_door})", "usd": round(handling, 2)},
        {"line": f"Markup ({markup_pct}%)", "usd": round(markup_amt, 2)},
        {"line": "GRAND TOTAL (labor package)", "usd": round(grand, 2)},
    ]
    if float(ret_ref.get("typical_holdback_usd") or 0) > 0:
        summary.extend(
            [
                {
                    "line": f"Retainage reference ({ret_ref.get('retainage_percent')}%)",
                    "usd": float(ret_ref["typical_holdback_usd"]),
                },
                {"line": "Net if retainage held (informational)", "usd": float(ret_ref["net_if_retainage_held_usd"])},
            ]
        )

    priced = {
        "inputs": {
            "project_type": ptype,
            "commercial_rates": commercial,
            "markup_percent": markup_pct,
            "tax_on_materials": False,
        },
        "line_items": lines,
        "summary_usd": {
            "install": round(install_sub, 2),
            "handling": round(handling, 2),
            "markup": round(markup_amt, 2),
            "grand_total": round(grand, 2),
        },
        "summary_table": summary,
        "retainage_reference": ret_ref,
    }

    out = args.out
    if not out.is_absolute():
        out = (Path.cwd() / out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"source_takeoff": str(tpath), "pricing": priced}, f, indent=2)

    xlsx = out.with_name("estimate_windows_doors_priced.xlsx")
    write_xlsx(xlsx, lines, summary)

    print(f"Wrote {out}")
    if xlsx.is_file():
        print(f"Wrote {xlsx}")
    print(f"Grand total (client): ${grand:,.2f}")


if __name__ == "__main__":
    main()
