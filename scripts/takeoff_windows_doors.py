#!/usr/bin/env python3
"""
Exterior windows + doors install takeoff from plan profile (counts only).

Uses windows_doors.json rules: labor-only, client-supplied frames.
Filters doors to exterior scope; windows assumed exterior unless clearly interior.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_PROFILE = _PROJECT_ROOT / "outputs" / "plan_profile_complete.json"
_DEFAULT_TRADE = _PROJECT_ROOT / "config" / "Trades" / "windows_doors.json"
_OUTPUT_DIR = _PROJECT_ROOT / "outputs"


def load_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(path)
    return data


def door_is_exterior_scope(d: dict[str, Any]) -> bool:
    t = str(d.get("type", "")).lower().strip()
    if t == "interior" or t.startswith("interior"):
        return False
    if "interior" in t and "exterior" not in t and "hm" not in t:
        return False
    keys = (
        "exterior",
        "aluminum",
        "hm",
        "hollow",
        "metal",
        "storefront",
        "patio",
        "glass",
        "sliding",
        "slider",
        "barn",
        "stair",
    )
    return any(k in t for k in keys)


def door_category(d: dict[str, Any]) -> str:
    """sliding_glass | hinged_exterior"""
    t = str(d.get("type", "")).lower()
    size = str(d.get("size", "")).lower()
    if "slider" in t or "sliding" in t or "glass" in t or "barn" in t:
        return "sliding_glass"
    if "'" in size:
        try:
            # rough width in feet from 6'-0" x ...
            part = size.split("x")[0].strip()
            ft = float(part.split("'")[0].replace("-", "."))
            if ft >= 5.5:
                return "sliding_glass"
        except (ValueError, IndexError):
            pass
    return "hinged_exterior"


def window_panel_count(w: dict[str, Any]) -> int:
    t = str(w.get("type", "")).lower()
    if "triple" in t or "trip" in t:
        return 3
    if "double" in t:
        return 2
    if "single" in t:
        return 1
    if "slider" in t or "sliding" in t:
        return 2
    return 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Exterior windows/doors count takeoff")
    ap.add_argument("--profile", type=Path, default=_DEFAULT_PROFILE)
    ap.add_argument("--trade", type=Path, default=_DEFAULT_TRADE)
    ap.add_argument("-o", type=Path, dest="out", default=_OUTPUT_DIR / "takeoff_windows_doors.json")
    args = ap.parse_args()

    profile = load_json(args.profile.resolve())
    if "_merge_meta" in profile:
        profile = {k: v for k, v in profile.items() if k != "_merge_meta"}
    trade = load_json(args.trade.resolve())

    win_rows: list[dict[str, Any]] = []
    for w in profile.get("windows") or []:
        if not isinstance(w, dict):
            continue
        try:
            c = int(float(w.get("count") or 0))
        except (TypeError, ValueError):
            c = 0
        if c <= 0:
            continue
        panels = window_panel_count(w)
        win_rows.append(
            {
                "tag": w.get("tag"),
                "type": w.get("type"),
                "brand": w.get("brand"),
                "count": c,
                "panels": panels,
                "scope": "exterior_window",
            }
        )

    door_rows: list[dict[str, Any]] = []
    for d in profile.get("doors") or []:
        if not isinstance(d, dict):
            continue
        try:
            c = int(float(d.get("count") or 0))
        except (TypeError, ValueError):
            c = 0
        if c <= 0:
            continue
        if not door_is_exterior_scope(d):
            continue
        door_rows.append(
            {
                "tag": d.get("tag"),
                "type": d.get("type"),
                "size": d.get("size"),
                "count": c,
                "category": door_category(d),
                "scope": "exterior_door",
            }
        )

    tw = sum(r["count"] for r in win_rows)
    td = sum(r["count"] for r in door_rows)

    result = {
        "project": profile.get("project"),
        "trade": trade.get("trade_name"),
        "exterior_windows": win_rows,
        "exterior_doors": door_rows,
        "totals": {
            "exterior_window_units": tw,
            "exterior_door_units": td,
            "interior_doors_excluded_note": "Interior doors excluded per trade scope",
        },
        "config_ref": str(args.trade.resolve()),
    }

    out = args.out
    if not out.is_absolute():
        out = (Path.cwd() / out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"Wrote {out}")
    print(f"Exterior windows (units): {tw} | Exterior doors (units): {td}")


if __name__ == "__main__":
    main()
