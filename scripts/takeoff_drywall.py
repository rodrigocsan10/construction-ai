#!/usr/bin/env python3
"""
Drywall + insulation takeoff from plan profile + framing takeoff (LF by wall tag).

- Uses wall_types side_a / side_b: counts gypsum-facing SF (LF × height × layers per side).
- Skips obvious non-GWB finishes (masonry, stone, fiber cement lap, CMU, concrete).
- Insulation SF when insulation.required (LF × height — area for pricing / checks).
- Insulation **order qty**: pre-cut **batt pieces** = stud **bays** × **vertical courses**
  (courses = ceil(wall_height ÷ batt length from config). Bays ≈ stud_count−1 from framing
  takeoff, else LF×12÷spacing). Then **bags** (FG) or **bundles** (mineral wool) from typical pack sizes.
- Ceiling insulation: rough **pieces** from ceiling SF ÷ nominal SF/piece (config).
- Sheet count from drywall_rules sheet size vs wall height + waste.

Inputs:
  --profile (plan_profile_complete.json)
  --takeoff-framing (takeoff_framing.json for linear_feet per tag)
  --trade (drywall_insulation.json)
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_PROFILE = _PROJECT_ROOT / "outputs" / "plan_profile_complete.json"
_DEFAULT_FRAMING = _PROJECT_ROOT / "outputs" / "takeoff_framing.json"
_DEFAULT_TRADE = _PROJECT_ROOT / "config" / "Trades" / "drywall_insulation.json"
_OUTPUT_DIR = _PROJECT_ROOT / "outputs"


def load_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(path)
    return data


def side_is_gypsum_scope(board: str) -> bool:
    """True if this face gets GWB/Type X/cement board (counted in drywall trade)."""
    b = (board or "").lower().strip()
    if not b:
        return False
    skip = (
        "masonry",
        "veneer",
        "split face",
        "stone",
        "fiber cement",
        "lap siding",
        "siding",
        "cmu",
        "concrete",
        "metal panel",
    )
    if any(x in b for x in skip):
        return False
    hits = (
        "gypsum",
        "gwb",
        "drywall",
        "sheetrock",
        "type x",
        "type c",
        "green board",
        "moisture",
        "cement board",
        "durock",
    )
    if any(x in b for x in hits):
        return True
    if "5/8" in b or "1/2" in b:
        return True
    return False


def layers_for_side(side: dict[str, Any]) -> int:
    try:
        return max(1, int(side.get("layers") or 1))
    except (TypeError, ValueError):
        return 1


def pick_sheet_sf(wall_height_ft: float, sheet_sizes: dict[str, Any]) -> tuple[float, str]:
    """Pick nominal sheet area (SF) — taller walls use taller sheets."""
    sizes = []
    for name, sf in (sheet_sizes or {}).items():
        try:
            sizes.append((str(name), float(sf)))
        except (TypeError, ValueError):
            continue
    if not sizes:
        return 32.0, "4x8"
    if wall_height_ft <= 8.5:
        return 32.0, "4x8"
    if wall_height_ft <= 10.5:
        for n, sf in sizes:
            if abs(sf - 40) < 1:
                return sf, n
        return 40.0, "4x10"
    if wall_height_ft <= 12.5:
        for n, sf in sizes:
            if abs(sf - 48) < 1:
                return sf, n
        return 48.0, "4x12"
    for n, sf in sizes:
        if sf >= 56:
            return sf, n
    return 64.0, "4x16"


def insulation_kind(spec: str) -> str:
    s = (spec or "").lower()
    if "mineral" in s or "wool" in s or "roxul" in s:
        return "mineral_wool"
    return "fiberglass_batt"


def lf_from_framing_takeoff(takeoff: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in takeoff.get("wall_type_takeoff") or []:
        if not isinstance(row, dict):
            continue
        tag = str(row.get("tag", "")).strip()
        if not tag:
            continue
        try:
            out[tag] = float(row.get("linear_feet") or 0)
        except (TypeError, ValueError):
            out[tag] = 0.0
    return out


def framing_info_by_tag(takeoff: dict[str, Any]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for row in takeoff.get("wall_type_takeoff") or []:
        if not isinstance(row, dict):
            continue
        tag = str(row.get("tag", "")).strip()
        if not tag:
            continue
        try:
            sc = int(row.get("stud_count") or 0)
        except (TypeError, ValueError):
            sc = 0
        try:
            sp = int(row.get("spacing_inches") or 0)
        except (TypeError, ValueError):
            sp = 0
        out[tag] = {"stud_count": sc, "spacing_inches": sp}
    return out


def insulation_waste_pct(trade: dict[str, Any], cli_waste: float) -> float:
    ins = trade.get("insulation") or {}
    w = ins.get("waste_percent") or {}
    try:
        lo = float(w.get("low", 10))
        hi = float(w.get("high", 12))
        mid = (lo + hi) / 2.0
    except (TypeError, ValueError):
        mid = 11.0
    return cli_waste if cli_waste > 0 else mid


def kb_optional_allowances(
    profile: dict[str, Any],
    lf_by_tag: dict[str, float],
    wall_height_ft: float,
    total_gwb_sf: float,
    trade: dict[str, Any],
) -> dict[str, Any]:
    """Detect fire wall SF, furring SF, scissor lift flag from profile + LF (KB gotchas)."""
    kb = trade.get("kb_optional_line_items") or {}
    try:
        fire_rate = float(kb.get("fire_caulking_usd_per_sf_fire_wall", 0))
    except (TypeError, ValueError):
        fire_rate = 0.0
    try:
        fur_rate = float(kb.get("furring_extra_usd_per_sf", 0))
    except (TypeError, ValueError):
        fur_rate = 0.0
    try:
        thresh = float(kb.get("wall_height_ft_scissor_threshold", 12))
    except (TypeError, ValueError):
        thresh = 12.0
    try:
        lift_mo = float(kb.get("scissor_lift_monthly_usd", 5000))
    except (TypeError, ValueError):
        lift_mo = 5000.0

    fire_sf = 0.0
    fur_sf = 0.0
    for wt in profile.get("wall_types") or []:
        if not isinstance(wt, dict):
            continue
        tag = str(wt.get("tag", "")).strip()
        if not tag:
            continue
        try:
            lf = float(lf_by_tag.get(tag, 0.0))
        except (TypeError, ValueError):
            lf = 0.0
        if lf <= 0:
            continue
        face_sf = lf * wall_height_ft
        fr = wt.get("fire_rated") if isinstance(wt.get("fire_rated"), dict) else {}
        if fr.get("rated"):
            fire_sf += face_sf
        side_a = wt.get("side_a") if isinstance(wt.get("side_a"), dict) else {}
        side_b = wt.get("side_b") if isinstance(wt.get("side_b"), dict) else {}
        boards = (str(side_a.get("board", "")) + " " + str(side_b.get("board", ""))).lower()
        if any(x in boards for x in ("resilient", "furring", "hat channel", "rc channel", "rc at", "r/c", "furring channel")):
            fur_sf += face_sf

    fire_usd = round(fire_sf * fire_rate, 2)
    fur_usd = round(fur_sf * fur_rate, 2)
    scissor_usd = round(lift_mo, 2) if wall_height_ft > thresh and total_gwb_sf > 0 else 0.0

    return {
        "fire_rated_wall_sf": round(fire_sf, 2),
        "fire_caulking_usd": fire_usd,
        "furring_channel_wall_sf": round(fur_sf, 2),
        "furring_extra_usd": fur_usd,
        "scissor_lift_usd": scissor_usd,
        "scissor_lift_applies": bool(scissor_usd),
        "wall_height_ft": wall_height_ft,
    }


def batt_packaging_for_wall(
    lf: float,
    wall_height_ft: float,
    stud_count: int,
    spacing_inches: int,
    kind: str,
    batt_cfg: dict[str, Any],
    waste_pct: float,
) -> dict[str, Any]:
    """Pre-cut batt pieces, bags or bundles (estimates)."""
    fg = batt_cfg.get("fiberglass_batt") or {}
    mw = batt_cfg.get("mineral_wool") or {}
    block = fg if kind == "fiberglass_batt" else mw
    try:
        batt_len_ft = float(block.get("precut_length_ft", 7.75))
    except (TypeError, ValueError):
        batt_len_ft = 7.75
    if batt_len_ft <= 0:
        batt_len_ft = 7.75

    courses = max(1, math.ceil(wall_height_ft / batt_len_ft))

    sp = spacing_inches if spacing_inches > 0 else 16
    if stud_count >= 2:
        bays = max(0, stud_count - 1)
    else:
        bays = max(1, int(math.ceil(lf * 12.0 / sp)))

    raw_pieces = bays * courses
    pieces = max(0, int(math.ceil(raw_pieces * (1.0 + waste_pct / 100.0))))

    bags: int | None = None
    bundles: int | None = None
    if kind == "fiberglass_batt":
        try:
            ppb = max(1, int(fg.get("pieces_per_bag_typical", 10)))
        except (TypeError, ValueError):
            ppb = 10
        bags = max(0, int(math.ceil(pieces / ppb))) if pieces else 0
    else:
        try:
            ppb = max(1, int(mw.get("pieces_per_bundle_typical", 6)))
        except (TypeError, ValueError):
            ppb = 6
        bundles = max(0, int(math.ceil(pieces / ppb))) if pieces else 0

    width_map = batt_cfg.get("batt_width_by_stud_spacing_inches") or {}
    try:
        w_in = float(width_map.get(str(sp), width_map.get(sp, 15.25)))
    except (TypeError, ValueError):
        w_in = 15.25
    piece_sf = (w_in / 12.0) * batt_len_ft

    return {
        "insulation_stud_bays_est": bays,
        "insulation_vertical_courses": courses,
        "insulation_batt_pieces_est": pieces,
        "insulation_bags_fiberglass_est": bags,
        "insulation_bundles_mineral_wool_est": bundles,
        "insulation_nominal_piece_sf": round(piece_sf, 2),
        "insulation_batt_length_ft": batt_len_ft,
    }


def run_takeoff(
    profile: dict[str, Any],
    trade: dict[str, Any],
    lf_by_tag: dict[str, float],
    framing_by_tag: dict[str, dict[str, int]],
    wall_height_ft: float,
    ceiling_sf: float,
    waste_pct: float,
) -> dict[str, Any]:
    rules = trade.get("drywall_rules") or {}
    sheet_sizes = rules.get("sheet_sizes_available") or {}
    waste_mult = 1.0 + waste_pct / 100.0
    sheet_sf, sheet_name = pick_sheet_sf(wall_height_ft, sheet_sizes)
    ins_waste = insulation_waste_pct(trade, waste_pct)
    ins_block_cfg = (trade.get("insulation") or {}).get("batt_takeoff") or {}

    rows: list[dict[str, Any]] = []
    total_gwb_sf = 0.0
    total_insul_sf = 0.0
    total_insul_pieces = 0
    total_fg_bags = 0
    total_mw_bundles = 0

    for wt in profile.get("wall_types") or []:
        if not isinstance(wt, dict):
            continue
        tag = str(wt.get("tag", "")).strip()
        if not tag:
            continue
        lf = float(lf_by_tag.get(tag, 0.0))
        fr = framing_by_tag.get(tag) or {}
        stud_count = int(fr.get("stud_count") or 0)
        try:
            wt_spacing = int(wt.get("spacing_inches") or 0)
        except (TypeError, ValueError):
            wt_spacing = 0
        spacing = int(fr.get("spacing_inches") or 0) or wt_spacing or 16

        side_a = wt.get("side_a") if isinstance(wt.get("side_a"), dict) else {}
        side_b = wt.get("side_b") if isinstance(wt.get("side_b"), dict) else {}
        sa = sb = 0.0
        if side_is_gypsum_scope(str(side_a.get("board", ""))):
            sa = lf * wall_height_ft * layers_for_side(side_a)
        if side_is_gypsum_scope(str(side_b.get("board", ""))):
            sb = lf * wall_height_ft * layers_for_side(side_b)
        gwb = sa + sb
        insul_sf = 0.0
        ins_block = wt.get("insulation") if isinstance(wt.get("insulation"), dict) else {}
        kind = insulation_kind(str(ins_block.get("type", "")))
        batt_extra: dict[str, Any] = {}

        if ins_block.get("required") and lf > 0:
            insul_sf = lf * wall_height_ft
            batt_extra = batt_packaging_for_wall(
                lf,
                wall_height_ft,
                stud_count,
                spacing,
                kind,
                ins_block_cfg,
                ins_waste,
            )
            total_insul_pieces += int(batt_extra.get("insulation_batt_pieces_est") or 0)
            if kind == "fiberglass_batt":
                total_fg_bags += int(batt_extra.get("insulation_bags_fiberglass_est") or 0)
            else:
                total_mw_bundles += int(batt_extra.get("insulation_bundles_mineral_wool_est") or 0)

        row: dict[str, Any] = {
            "tag": tag,
            "location": wt.get("location", ""),
            "linear_feet": round(lf, 2),
            "wall_height_ft": wall_height_ft,
            "gwb_side_a_sf": round(sa, 2),
            "gwb_side_b_sf": round(sb, 2),
            "gwb_total_sf": round(gwb, 2),
            "insulation_sf": round(insul_sf, 2),
            "insulation_kind": kind if insul_sf > 0 else "",
            "notes": "" if lf > 0 else "No LF in framing takeoff — add wall type to LF file",
        }
        row.update(batt_extra)
        rows.append(row)

        total_gwb_sf += gwb
        total_insul_sf += insul_sf

    wall_sheets = math.ceil(total_gwb_sf * waste_mult / sheet_sf) if sheet_sf > 0 else 0
    ceil_sheets = math.ceil(ceiling_sf * waste_mult / sheet_sf) if ceiling_sf > 0 and sheet_sf > 0 else 0

    try:
        ceil_nom = float(ins_block_cfg.get("ceiling_unfaced_nominal_sf_per_piece", 40.0))
    except (TypeError, ValueError):
        ceil_nom = 40.0
    if ceil_nom <= 0:
        ceil_nom = 40.0
    ceil_insul_pieces = (
        int(math.ceil(ceiling_sf * (1.0 + ins_waste / 100.0) / ceil_nom)) if ceiling_sf > 0 else 0
    )

    kb_allow = kb_optional_allowances(profile, lf_by_tag, wall_height_ft, total_gwb_sf, trade)

    return {
        "project": profile.get("project"),
        "inputs": {
            "wall_height_ft": wall_height_ft,
            "ceiling_sf": ceiling_sf,
            "waste_percent": waste_pct,
            "insulation_waste_percent": ins_waste,
            "sheet_nominal": sheet_name,
            "sheet_sf": sheet_sf,
        },
        "insulation_quantity_note": (trade.get("insulation") or {}).get("batt_takeoff", {}).get("method", ""),
        "kb_optional_allowances": kb_allow,
        "wall_rows": rows,
        "totals": {
            "gwb_wall_sf": round(total_gwb_sf, 2),
            "ceiling_sf": round(ceiling_sf, 2),
            "gwb_combined_sf": round(total_gwb_sf + ceiling_sf, 2),
            "insulation_sf": round(total_insul_sf, 2),
            "insulation_wall_batt_pieces_est": total_insul_pieces,
            "insulation_fiberglass_bags_est": total_fg_bags,
            "insulation_mineral_wool_bundles_est": total_mw_bundles,
            "insulation_ceiling_batt_pieces_est": ceil_insul_pieces,
            "wall_sheet_count_est": wall_sheets,
            "ceiling_sheet_count_est": ceil_sheets,
            "total_sheet_count_est": wall_sheets + ceil_sheets,
            "kb_optional_subtotal_usd": round(
                float(kb_allow.get("fire_caulking_usd") or 0)
                + float(kb_allow.get("furring_extra_usd") or 0)
                + float(kb_allow.get("scissor_lift_usd") or 0),
                2,
            ),
        },
        "gotchas": trade.get("gotchas"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Drywall + insulation takeoff")
    ap.add_argument("--profile", type=Path, default=_DEFAULT_PROFILE)
    ap.add_argument("--takeoff-framing", type=Path, default=_DEFAULT_FRAMING)
    ap.add_argument("--trade", type=Path, default=_DEFAULT_TRADE)
    ap.add_argument("--wall-height-ft", type=float, default=None)
    ap.add_argument("--ceiling-sf", type=float, default=0.0)
    ap.add_argument("--waste-pct", type=float, default=11.0)
    ap.add_argument("-o", type=Path, dest="out", default=_OUTPUT_DIR / "takeoff_drywall.json")
    args = ap.parse_args()

    profile = load_json(args.profile.resolve())
    if "_merge_meta" in profile:
        profile = {k: v for k, v in profile.items() if k != "_merge_meta"}
    trade = load_json(args.trade.resolve())

    fpath = args.takeoff_framing.resolve()
    if not fpath.is_file():
        print(f"Framing takeoff not found: {fpath}")
        raise SystemExit(1)
    framing = load_json(fpath)
    lf_by_tag = lf_from_framing_takeoff(framing)
    framing_by_tag = framing_info_by_tag(framing)

    wh = args.wall_height_ft
    if wh is None:
        inp = framing.get("inputs") or {}
        try:
            wh = float(inp.get("wall_height_ft") or 10.0)
        except (TypeError, ValueError):
            wh = 10.0

    result = run_takeoff(profile, trade, lf_by_tag, framing_by_tag, wh, args.ceiling_sf, args.waste_pct)

    out = args.out
    if not out.is_absolute():
        out = (Path.cwd() / out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"Wrote {out}")
    t = result["totals"]
    print(f"GWB wall SF: {t['gwb_wall_sf']} | sheets (walls): {t['wall_sheet_count_est']}")
    print(
        f"Insulation SF: {t['insulation_sf']} | "
        f"Wall batts (pcs est): {t.get('insulation_wall_batt_pieces_est', 0)} | "
        f"FG bags est: {t.get('insulation_fiberglass_bags_est', 0)} | "
        f"MW bundles est: {t.get('insulation_mineral_wool_bundles_est', 0)}"
    )
    if t.get("insulation_ceiling_batt_pieces_est", 0):
        print(f"Ceiling batt pieces (rough est): {t['insulation_ceiling_batt_pieces_est']}")
    print(f"Total drywall sheets (+ ceiling): {t['total_sheet_count_est']}")


if __name__ == "__main__":
    main()
