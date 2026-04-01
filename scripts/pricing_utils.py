"""Shared helpers for estimate scripts (retainage display, etc.)."""

from __future__ import annotations

from typing import Any


def retainage_reference(company: dict[str, Any], grand_total: float) -> dict[str, Any]:
    """KB typical GC retainage — informational; does not change grand_total."""
    try:
        pct = float(company.get("retainage_percent") or 0)
    except (TypeError, ValueError):
        pct = 0.0
    g = round(grand_total, 2)
    if pct <= 0 or g <= 0:
        return {
            "retainage_percent": 0.0,
            "typical_holdback_usd": 0.0,
            "grand_total_client": g,
            "net_if_retainage_held_usd": g,
            "note": "Set retainage_percent in company.json; shown for cash-flow planning only.",
        }
    hold = round(g * pct / 100.0, 2)
    return {
        "retainage_percent": pct,
        "typical_holdback_usd": hold,
        "grand_total_client": g,
        "net_if_retainage_held_usd": round(g - hold, 2),
        "note": "Not deducted from grand total — typical GC holdback per KB.",
    }


def zip_tape_roller_addon_framing(takeoff: dict[str, Any], trade: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    """KB ZIP tape + roller extra per wall sheathing sheet when profile flags ZIP."""
    sh = takeoff.get("sheathing") or {}
    try:
        wall_sheets = int(sh.get("wall_sheathing_sheets_4x8_equiv") or 0)
    except (TypeError, ValueError):
        wall_sheets = 0
    flag = bool(sh.get("profile_suggests_zip_tape_roller"))
    sh_rules = trade.get("sheathing_rules") or {}
    try:
        per = float(sh_rules.get("zip_tape_roller_addon_per_wall_sheet_usd", 0))
    except (TypeError, ValueError):
        per = 0.0
    if not flag or wall_sheets <= 0 or per <= 0:
        return 0.0, {"applied": False}
    usd = float(wall_sheets) * per
    return usd, {
        "applied": True,
        "wall_sheets": wall_sheets,
        "per_sheet_usd": per,
        "note": str(sh_rules.get("zip_tape_roller_note", "")),
    }
