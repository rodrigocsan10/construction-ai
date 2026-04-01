#!/usr/bin/env python3
"""
Sprint 3 — Rough framing + sheathing takeoff from plan profile + trade config.

Inputs:
  - outputs/plan_profile_complete.json (or --profile)
  - config/Trades/rough_framing.json
  - Optional: --pdf + --estimate-lf → OpenAI estimates wall_linear_feet + roof_deck_sf from drawings
  - Optional: --lf-json overrides (wins over AI + profile embedded LF)

Merge order: AI estimate → profile wall_types[].linear_feet → --lf-json

Outputs:
  - outputs/takeoff_framing.json
  - outputs/wall_lf_estimated.json (when --estimate-lf)
  - outputs/supplier_list_framing.csv (+ .xlsx if pandas installed)

Formulas (KNOWLEDGE_BASE / rough_framing.json):
  Plates LF = wall LF × plates_per_wall (default 3)
  Studs = ceil(LF × waste × 12 ÷ spacing_inches)
  Bracing = ceil(LF ÷ 8)  (2x4 16' sticks)
  Nails ≈ LF × nails_per_lf → boxes of 4000
  Sheathing (wood/metal exterior): gross SF = exterior LF × wall_height × floor_multiplier;
    net SF subtracts door/window area when sizes parse; sheets = net × (1+waste) ÷ 32
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from openai import RateLimitError
from pypdf import PdfReader, PdfWriter

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_PROFILE = _PROJECT_ROOT / "outputs" / "plan_profile_complete.json"
_DEFAULT_TRADE = _PROJECT_ROOT / "config" / "Trades" / "rough_framing.json"
_OUTPUT_DIR = _PROJECT_ROOT / "outputs"
_PROMPT_LF = _PROJECT_ROOT / "prompts" / "framing_lf_estimate.txt"

load_dotenv(_PROJECT_ROOT / ".env")
_openai_client: OpenAI | None = None


def _client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _openai_client


def load_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Expected object at root: {path}")
    return data


def parse_door_opening_ft(size: str) -> tuple[float | None, float | None]:
    """Return (width_ft, height_ft) from strings like 3'-0\" x 7'-0\"."""
    if not size or "x" not in size.lower():
        return None, None
    parts = re.split(r"\s*x\s*", size.strip(), maxsplit=1, flags=re.IGNORECASE)

    def to_feet(chunk: str) -> float | None:
        chunk = chunk.strip()
        m = re.match(r"(\d+)'-(\d+)\"", chunk)
        if not m:
            m = re.match(r"(\d+)'-(\d+)/(\d+)\"", chunk)
            if m:
                whole = int(m.group(1))
                num, den = int(m.group(2)), int(m.group(3))
                return whole + (num / den) / 12.0
            return None
        return int(m.group(1)) + int(m.group(2)) / 12.0

    w = to_feet(parts[0])
    h = to_feet(parts[1]) if len(parts) > 1 else None
    return w, h


def classify_wall_framing(stud_size: str, location: str) -> str:
    s = (stud_size or "").lower()
    loc = (location or "").lower()
    if "cmu" in s or s.strip() == "concrete":
        return "masonry"
    if "metal" in s:
        return "metal"
    if "2x4" in s:
        return "wood_2x4"
    if "2x6" in s:
        return "wood_2x6"
    if "exterior" in loc:
        return "wood_2x6"
    return "wood_2x4"


def header_assumption(width_ft: float, rules: dict[str, Any]) -> str:
    ast = rules.get("assumptions_when_plans_incomplete") or {}
    if width_ft < 4:
        return str(ast.get("opening_under_4ft", "2x8 or 2x10"))
    if width_ft <= 6:
        return str(ast.get("opening_4ft_to_6ft", "2x10 or 2x12"))
    return str(ast.get("opening_over_6ft", "LVL"))


def stud_count(lf: float, spacing_in: int, waste: float) -> int:
    if lf <= 0 or spacing_in <= 0:
        return 0
    return math.ceil(lf * waste * 12.0 / spacing_in)


def bracing_count(lf: float, divisor: float = 8.0) -> int:
    if lf <= 0:
        return 0
    return math.ceil(lf / divisor)


_META_OVERRIDE_KEYS = frozenset(
    {"wall_height_ft", "roof_deck_sf", "lf_is_per_floor", "_comment", "wall_linear_feet"}
)


def merge_lf_sources(
    wall_types: list[dict[str, Any]],
    overrides: dict[str, Any],
    seed: dict[str, float] | None = None,
) -> dict[str, float]:
    """Tag -> LF. Order: seed (AI) → profile embedded → overrides (highest priority)."""
    out: dict[str, float] = dict(seed or {})
    for wt in wall_types:
        if not isinstance(wt, dict):
            continue
        tag = str(wt.get("tag", "")).strip()
        if not tag:
            continue
        for key in ("linear_feet", "lf", "linear_ft"):
            if key in wt and wt[key] is not None:
                try:
                    out[tag] = float(wt[key])
                except (TypeError, ValueError):
                    pass
                break
    wl = overrides.get("wall_linear_feet")
    if isinstance(wl, dict):
        for k, v in wl.items():
            if str(k).startswith("_"):
                continue
            try:
                out[str(k)] = float(v)
            except (TypeError, ValueError):
                pass
    else:
        for k, v in overrides.items():
            if k in _META_OVERRIDE_KEYS:
                continue
            if isinstance(v, (int, float)):
                out[str(k)] = float(v)
    return out


def wall_tags_from_profile(profile: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    for wt in profile.get("wall_types") or []:
        if isinstance(wt, dict):
            t = str(wt.get("tag", "")).strip()
            if t:
                tags.append(t)
    return tags


def pdf_page_count(pdf_path: Path) -> int:
    return len(PdfReader(str(pdf_path)).pages)


def parse_page_range(spec: str, total_pages: int) -> tuple[int, int]:
    spec = spec.strip().replace(" ", "")
    if "-" in spec:
        a, b = spec.split("-", 1)
        start, end = int(a), int(b)
    else:
        start = end = int(spec)
    start = max(1, start)
    if end < start:
        end = start
    if start > total_pages:
        raise ValueError(f"Start page {start} beyond PDF ({total_pages} pages).")
    end = min(end, total_pages)
    return start, end


def slice_pdf_pages(src: Path, start: int, end: int) -> Path:
    reader = PdfReader(str(src))
    writer = PdfWriter()
    total = len(reader.pages)
    for i in range(start - 1, end):
        if i < total:
            writer.add_page(reader.pages[i])
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    out = Path(path)
    with open(out, "wb") as f:
        writer.write(f)
    return out


def _parse_json_response(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


def normalize_lf_estimate(raw: dict[str, Any], required_tags: list[str]) -> dict[str, Any]:
    wl = raw.get("wall_linear_feet")
    if not isinstance(wl, dict):
        wl = {}
    fixed: dict[str, float] = {}
    for tag in required_tags:
        v = wl.get(tag)
        if v is None:
            for k, val in wl.items():
                if str(k).strip().lower() == tag.lower():
                    v = val
                    break
        try:
            fixed[tag] = float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            fixed[tag] = 0.0
    out = dict(raw)
    out["wall_linear_feet"] = fixed
    try:
        out["roof_deck_sf"] = float(raw.get("roof_deck_sf") or 0)
    except (TypeError, ValueError):
        out["roof_deck_sf"] = 0.0
    out.setdefault("notes", "")
    out.setdefault("structural_hardware_notes", "")
    out.setdefault("confidence", "unknown")
    return out


def estimate_lf_from_pdf(
    pdf_path: Path,
    required_tags: list[str],
    pages: str | None,
    per_floor_instruction: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Call OpenAI with PDF. Returns (normalized_estimate, meta_for_audit).
    meta includes temp_file path if sliced (caller deletes).
    """
    if not _PROMPT_LF.is_file():
        raise FileNotFoundError(f"Missing prompt: {_PROMPT_LF}")

    instructions = _PROMPT_LF.read_text(encoding="utf-8")
    tag_lines = "\n".join(f"- {t}" for t in required_tags)
    mode = (
        "LF must be PER FLOOR; state that in notes. User will multiply floors in tooling."
        if per_floor_instruction
        else "LF must be COMBINED TOTAL for the whole building (all floors)."
    )
    user_text = (
        f"REQUIRED TAG LIST (every key required in wall_linear_feet):\n{tag_lines}\n\n"
        f"MODE: {mode}\n"
    )

    tmp_pdf: Path | None = None
    upload_path = pdf_path.resolve()
    meta: dict[str, Any] = {"pdf": str(upload_path), "pages_arg": pages}

    try:
        if pages:
            total = pdf_page_count(upload_path)
            start, end = parse_page_range(pages, total)
            tmp_pdf = slice_pdf_pages(upload_path, start, end)
            upload_path = tmp_pdf
            meta["pages_used"] = f"{start}-{end} of {total}"
            print(f"  Using PDF pages {start}-{end} of {total} for LF estimate.")

        with open(upload_path, "rb") as f:
            uploaded = _client().files.create(file=f, purpose="assistants")

        result = _client().responses.create(
            model="gpt-4.1",
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": instructions + "\n\n" + user_text},
                        {"type": "input_file", "file_id": uploaded.id},
                    ],
                }
            ],
            text={"format": {"type": "json_object"}},
        )
        raw_text = (result.output_text or "").strip()
        raw = _parse_json_response(raw_text)
        normalized = normalize_lf_estimate(raw, required_tags)
        meta["raw_response_chars"] = len(raw_text)
        return normalized, meta
    finally:
        if tmp_pdf is not None and tmp_pdf.is_file():
            tmp_pdf.unlink(missing_ok=True)


def lf_provenance(
    tags: list[str],
    seed: dict[str, float],
    wall_types: list[dict[str, Any]],
    overrides: dict[str, Any],
) -> dict[str, str]:
    """How each tag got its LF (last writer wins: override > profile > AI)."""
    override_tags: set[str] = set()
    wl = overrides.get("wall_linear_feet")
    if isinstance(wl, dict):
        override_tags = {str(k) for k in wl if not str(k).startswith("_")}
    else:
        for k, v in overrides.items():
            if k not in _META_OVERRIDE_KEYS and isinstance(v, (int, float)):
                override_tags.add(str(k))

    profile_tags: set[str] = set()
    for wt in wall_types:
        if not isinstance(wt, dict):
            continue
        tag = str(wt.get("tag", "")).strip()
        if not tag:
            continue
        for key in ("linear_feet", "lf", "linear_ft"):
            if key in wt and wt[key] is not None:
                try:
                    float(wt[key])
                    profile_tags.add(tag)
                except (TypeError, ValueError):
                    pass
                break

    prov: dict[str, str] = {}
    for tag in tags:
        if tag in override_tags:
            prov[tag] = "lf_json_override"
        elif tag in profile_tags:
            prov[tag] = "profile_embedded"
        elif tag in seed:
            prov[tag] = "ai_estimate"
        else:
            prov[tag] = "missing"
    return prov


def total_door_opening_sf(doors: list[dict[str, Any]]) -> float:
    sf = 0.0
    for d in doors:
        if not isinstance(d, dict):
            continue
        try:
            c = float(d.get("count") or 0)
        except (TypeError, ValueError):
            c = 0.0
        if c <= 0:
            continue
        w, h = parse_door_opening_ft(str(d.get("size") or ""))
        if w and h:
            sf += w * h * c
    return sf


def total_window_opening_sf(windows: list[dict[str, Any]]) -> float:
    sf = 0.0
    for wrow in windows:
        if not isinstance(wrow, dict):
            continue
        try:
            c = float(wrow.get("count") or 0)
        except (TypeError, ValueError):
            c = 0.0
        if c <= 0:
            continue
        w, h = parse_door_opening_ft(str(wrow.get("size") or ""))
        if w and h:
            sf += w * h * c
    return sf


def roof_labor_tier(structural: dict[str, Any]) -> str:
    """truss_engineered = lower labor touch; rafter = stick-built roof (KB premium)."""
    roof = structural.get("roof_system") if isinstance(structural.get("roof_system"), dict) else {}
    t = (str(roof.get("type", "")) + " " + str(roof.get("notes", ""))).lower()
    if "rafter" in t and "truss" not in t:
        return "rafter"
    return "truss_engineered"


def floor_estimating_action(structural: dict[str, Any]) -> dict[str, Any]:
    floor = structural.get("floor_system") if isinstance(structural.get("floor_system"), dict) else {}
    typ = str(floor.get("type", "")).lower()
    if any(x in typ for x in ("truss", "tji", "i-joist", "i joist", "engineered", "concrete", "podium")):
        return {
            "action": "supplier_quote_or_engineered",
            "note": "Truss/TJI/concrete/podium — get supplier/engineered takeoff; do not guess joist counts without spans.",
        }
    if "dimensional" in typ or "2x10" in typ or "2x12" in typ or "sawn" in typ:
        return {
            "action": "dimensional_lumber",
            "formula": "Joist count = perpendicular_ft × 1.10 waste × 12 ÷ spacing → round up; length = span rounded up to even foot (KB).",
        }
    return {
        "action": "verify_structural_plans",
        "note": "Floor system unclear in profile — confirm type and spans on structural drawings.",
    }


def build_floor_roof_estimating(structural: dict[str, Any], trade: dict[str, Any]) -> dict[str, Any]:
    return {
        "roof_labor_tier": roof_labor_tier(structural),
        "roof_system": structural.get("roof_system") or {},
        "floor_system": structural.get("floor_system") or {},
        "floor_estimating": floor_estimating_action(structural),
        "roof_rules_reference": trade.get("roof_rules"),
    }


def run_takeoff(
    profile: dict[str, Any],
    trade: dict[str, Any],
    lf_by_tag: dict[str, float],
    wall_height_ft: float,
    stud_length_ft: float,
    sheathing_waste_pct: float,
    lf_floor_mult: int,
    lf_source_by_tag: dict[str, str] | None = None,
    lf_estimation_extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    wall_rules = trade.get("wall_rules") or {}
    plates_per = float(wall_rules.get("plates_per_wall", 3))
    waste = float(wall_rules.get("waste_factor", 1.10))
    nails_per_lf = float(wall_rules.get("nails_per_lf", 10))
    nails_per_box = float(wall_rules.get("nails_per_box", 4000))
    bracing_div = 8.0

    sh_rules = trade.get("sheathing_rules") or {}
    sheet_sf = float(sh_rules.get("sheet_sf", 32))
    subtract_openings = bool(sh_rules.get("subtract_windows_and_doors", True))

    wall_types = profile.get("wall_types") or []
    if not isinstance(wall_types, list):
        wall_types = []

    rows: list[dict[str, Any]] = []
    totals = {
        "total_wall_lf": 0.0,
        "total_plate_lf": 0.0,
        "total_studs": 0,
        "total_bracing_sticks": 0,
        "wood_2x4_studs": 0,
        "wood_2x6_studs": 0,
        "metal_stud_walls_lf": 0.0,
    }

    for wt in wall_types:
        if not isinstance(wt, dict):
            continue
        tag = str(wt.get("tag", "")).strip()
        if not tag:
            continue
        spacing = int(wt.get("spacing_inches") or wall_rules.get("default_spacing_inches") or 16)
        loc = str(wt.get("location", ""))
        stud_size = str(wt.get("stud_size", ""))
        kind = classify_wall_framing(stud_size, loc)

        lf_raw = float(lf_by_tag.get(tag, 0.0))
        lf = lf_raw * lf_floor_mult if lf_floor_mult > 1 else lf_raw

        plates_lf = lf * plates_per if kind in ("wood_2x4", "wood_2x6") else 0.0
        studs = stud_count(lf, spacing, waste) if kind in ("wood_2x4", "wood_2x6", "metal") else 0
        brace = bracing_count(lf, bracing_div) if kind in ("wood_2x4", "wood_2x6") else 0

        src = (lf_source_by_tag or {}).get(tag, "missing")
        if lf > 0:
            note = ""
        elif src == "ai_estimate":
            note = "AI returned 0 — verify on plans or use --lf-json"
        else:
            note = "No LF — run with --estimate-lf or add --lf-json / profile.linear_feet"

        rows.append(
            {
                "tag": tag,
                "location": loc,
                "stud_size_spec": stud_size,
                "framing_class": kind,
                "spacing_inches": spacing,
                "linear_feet": round(lf, 2),
                "linear_feet_source": src,
                "plate_lumber_lf": round(plates_lf, 2),
                "stud_count": studs,
                "bracing_2x4x16_count": brace,
                "notes": note,
            }
        )

        totals["total_wall_lf"] += lf
        totals["total_plate_lf"] += plates_lf
        totals["total_studs"] += studs
        totals["total_bracing_sticks"] += brace
        if kind == "wood_2x4":
            totals["wood_2x4_studs"] += studs
        elif kind == "wood_2x6":
            totals["wood_2x6_studs"] += studs
        elif kind == "metal":
            totals["metal_stud_walls_lf"] += lf

    total_nails = totals["total_wall_lf"] * nails_per_lf
    nail_boxes = math.ceil(total_nails / nails_per_box) if nails_per_box > 0 else 0

    # Exterior sheathing (wood/metal framed exterior walls only)
    ext_lf = sum(
        r["linear_feet"]
        for r in rows
        if str(r.get("location", "")).lower() == "exterior"
        and r["framing_class"] in ("wood_2x4", "wood_2x6", "metal")
    )
    gross_wall_sf = ext_lf * wall_height_ft
    door_sf = total_door_opening_sf(profile.get("doors") or [])
    win_sf = total_window_opening_sf(profile.get("windows") or [])
    opening_sf = (door_sf + win_sf) if subtract_openings else 0.0
    net_wall_sf = max(0.0, gross_wall_sf - opening_sf)
    waste_mult = 1.0 + sheathing_waste_pct / 100.0
    sheathing_wall_sheets = math.ceil(net_wall_sf * waste_mult / sheet_sf) if sheet_sf > 0 else 0

    roof_sf = float(lf_by_tag.get("_roof_deck_sf", 0.0))
    sheathing_roof_sheets = math.ceil(roof_sf * waste_mult / sheet_sf) if roof_sf > 0 and sheet_sf > 0 else 0

    header_rules = trade.get("header_rules") or {}
    disclaimer = str(header_rules.get("disclaimer_text", ""))
    header_lines: list[dict[str, Any]] = []
    for d in profile.get("doors") or []:
        if not isinstance(d, dict):
            continue
        try:
            c = int(float(d.get("count") or 0))
        except (TypeError, ValueError):
            c = 0
        if c <= 0:
            continue
        w_ft, h_ft = parse_door_opening_ft(str(d.get("size") or ""))
        if w_ft is None:
            header_lines.append(
                {
                    "door_tag": d.get("tag"),
                    "count": c,
                    "size": d.get("size"),
                    "opening_width_ft": None,
                    "assumed_header": "UNKNOWN — add door width to schedule",
                    "count_headers": c,
                }
            )
            continue
        hdr = header_assumption(w_ft, header_rules)
        header_lines.append(
            {
                "door_tag": d.get("tag"),
                "count": c,
                "size": d.get("size"),
                "opening_width_ft": round(w_ft, 3),
                "opening_height_ft": round(h_ft, 3) if h_ft else None,
                "assumed_header": hdr,
                "count_headers": c,
                "disclaimer": disclaimer,
            }
        )

    structural = profile.get("structural") if isinstance(profile.get("structural"), dict) else {}

    out: dict[str, Any] = {
        "project": profile.get("project"),
        "inputs": {
            "wall_height_ft": wall_height_ft,
            "stud_length_ft": stud_length_ft,
            "sheathing_waste_pct": sheathing_waste_pct,
            "lf_floor_multiplier": lf_floor_mult,
        },
        "wall_type_takeoff": rows,
        "totals": {
            **{k: (int(v) if isinstance(v, float) and v == int(v) else round(v, 2)) for k, v in totals.items()},
            "framing_nail_count_est": round(total_nails, 0),
            "framing_nail_boxes_4000_est": nail_boxes,
        },
        "sheathing": {
            "exterior_framed_wall_lf": round(ext_lf, 2),
            "gross_exterior_wall_sf": round(gross_wall_sf, 2),
            "opening_sf_subtracted": round(opening_sf, 2),
            "net_exterior_wall_sf": round(net_wall_sf, 2),
            "sheet_size_sf": sheet_sf,
            "waste_percent": sheathing_waste_pct,
            "wall_sheathing_sheets_4x8_equiv": sheathing_wall_sheets,
            "roof_deck_sf": roof_sf,
            "roof_sheathing_sheets_4x8_equiv": sheathing_roof_sheets,
            "profile_sheathing_note": profile.get("sheathing"),
        },
        "headers_from_doors": header_lines,
        "structural_summary": structural,
        "equipment_notes": trade.get("equipment_rules"),
        "floor_roof_estimating": build_floor_roof_estimating(structural, trade),
    }
    if lf_estimation_extras:
        out["lf_estimation"] = lf_estimation_extras
    return out


def build_supplier_lines(result: dict[str, Any], stud_len: int) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    t = result["totals"]
    wl = result["wall_type_takeoff"]

    if t["wood_2x6_studs"] > 0:
        lines.append(
            {
                "category": "lumber",
                "item": f"2x6x{stud_len} KD stud (verify grade/spec)",
                "quantity": t["wood_2x6_studs"],
                "unit": "EA",
                "notes": "From stud count for 2x6 wall types",
            }
        )
    if t["wood_2x4_studs"] > 0:
        lines.append(
            {
                "category": "lumber",
                "item": f"2x4x{stud_len} KD stud",
                "quantity": t["wood_2x4_studs"],
                "unit": "EA",
                "notes": "From stud count for 2x4 wall types",
            }
        )

    plate_lf = t["total_plate_lf"]
    if plate_lf > 0:
        # Split plate lumber by dominant stud type (simple: use 2x6 if any 2x6 studs else 2x4)
        plate_size = "2x6" if t["wood_2x6_studs"] > 0 else "2x4"
        sticks = math.ceil(plate_lf / 16.0)
        lines.append(
            {
                "category": "lumber",
                "item": f"{plate_size}x16 plate / sill (or cut from stock)",
                "quantity": sticks,
                "unit": "EA",
                "notes": f"Total plate LF ≈ {plate_lf:.0f} (÷16' sticks)",
            }
        )

    if t["total_bracing_sticks"] > 0:
        lines.append(
            {
                "category": "lumber",
                "item": "2x4x16 brace / let-in (per KB rule)",
                "quantity": t["total_bracing_sticks"],
                "unit": "EA",
                "notes": "1 per 8 LF of wall (wood walls)",
            }
        )

    sh = result["sheathing"]
    if sh["wall_sheathing_sheets_4x8_equiv"] > 0:
        lines.append(
            {
                "category": "sheathing",
                "item": "Wall sheathing 4x8 equiv (OSB/CDX/ZIP per spec)",
                "quantity": sh["wall_sheathing_sheets_4x8_equiv"],
                "unit": "SHT",
                "notes": str((result.get("sheathing") or {}).get("profile_sheathing_note") or ""),
            }
        )
    if sh["roof_sheathing_sheets_4x8_equiv"] > 0:
        lines.append(
            {
                "category": "sheathing",
                "item": "Roof deck 4x8 equiv",
                "quantity": sh["roof_sheathing_sheets_4x8_equiv"],
                "unit": "SHT",
                "notes": "From roof_deck_sf (AI estimate or lf-json)",
            }
        )

    st = result.get("structural_summary") or {}
    roof_sys = st.get("roof_system") if isinstance(st.get("roof_system"), dict) else {}
    floor_sys = st.get("floor_system") if isinstance(st.get("floor_system"), dict) else {}
    roof_t = str(roof_sys.get("type", "")).lower()
    floor_t = str(floor_sys.get("type", "")).lower()
    if any(x in roof_t for x in ("truss", "tji", "engineered")) or any(
        x in floor_t for x in ("truss", "tji", "joist", "engineered")
    ):
        lines.append(
            {
                "category": "prefab_engineered",
                "item": "Truss / TJI / engineered floor package — formal supplier quote required",
                "quantity": 1,
                "unit": "LOT",
                "notes": "Attach plans; KB: do not self-price trusses without shop drawings",
            }
        )

    le = result.get("lf_estimation") or {}
    shn = str(le.get("structural_hardware_notes", "")).strip()
    if shn:
        lines.append(
            {
                "category": "structural_review",
                "item": "Hardware / connectors (field verify on structural sheets)",
                "quantity": 1,
                "unit": "CHECKLIST",
                "notes": shn[:500] + ("…" if len(shn) > 500 else ""),
            }
        )

    if t["metal_stud_walls_lf"] > 0:
        lines.append(
            {
                "category": "metal_studs",
                "item": "Metal stud/track system (order from supplier with gauge & depth)",
                "quantity": round(t["metal_stud_walls_lf"], 2),
                "unit": "LF wall",
                "notes": "Stud count in takeoff JSON — convert to LF packages per supplier",
            }
        )

    lines.append(
        {
            "category": "fasteners",
            "item": "Framing nails (8d common / per engineer)",
            "quantity": t["framing_nail_boxes_4000_est"],
            "unit": "BOX (4000)",
            "notes": f"~{t['framing_nail_count_est']:.0f} nails est",
        }
    )

    for h in result.get("headers_from_doors") or []:
        if not h.get("assumed_header"):
            continue
        lines.append(
            {
                "category": "headers",
                "item": f"Header assumption: {h.get('assumed_header')}",
                "quantity": h.get("count_headers", 0),
                "unit": "EA opening",
                "notes": f"Door {h.get('door_tag')} {h.get('size')}",
            }
        )

    return lines


def write_supplier_csv(path: Path, lines: list[dict[str, Any]]) -> None:
    if not lines:
        return
    keys = ["category", "item", "quantity", "unit", "notes"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for row in lines:
            w.writerow({k: row.get(k, "") for k in keys})


def write_supplier_xlsx(path: Path, lines: list[dict[str, Any]]) -> None:
    try:
        import pandas as pd
    except ImportError:
        return
    if not lines:
        return
    pd.DataFrame(lines).to_excel(path, index=False)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sprint 3 — framing takeoff: profile + trade config + optional AI LF from PDF."
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=_DEFAULT_PROFILE,
        help=f"plan_profile_complete.json (default: {_DEFAULT_PROFILE})",
    )
    parser.add_argument(
        "--trade",
        type=Path,
        default=_DEFAULT_TRADE,
        help=f"rough_framing.json (default: {_DEFAULT_TRADE})",
    )
    parser.add_argument(
        "--lf-json",
        type=Path,
        default=None,
        help="Overrides (highest priority): wall_linear_feet, roof_deck_sf, wall_height_ft, lf_is_per_floor",
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=None,
        help="Construction PDF (use with --estimate-lf)",
    )
    parser.add_argument(
        "--estimate-lf",
        action="store_true",
        help="Call OpenAI to estimate wall_linear_feet + roof_deck_sf from --pdf",
    )
    parser.add_argument(
        "--pages",
        type=str,
        default=None,
        metavar="START-END",
        help='PDF page range for estimate only, e.g. "1-12" (reduces tokens)',
    )
    parser.add_argument(
        "--lf-per-floor-estimate",
        action="store_true",
        help="Tell AI to return LF per floor (you must set lf_is_per_floor in lf-json or profile tooling)",
    )
    parser.add_argument(
        "--estimate-save",
        type=Path,
        default=_OUTPUT_DIR / "wall_lf_estimated.json",
        help="Save raw LF estimate JSON (default: outputs/wall_lf_estimated.json)",
    )
    parser.add_argument("--wall-height-ft", type=float, default=None, help="Wall height for sheathing SF (default 10)")
    parser.add_argument("--stud-length-ft", type=int, default=10, help="Stud length for supplier list")
    parser.add_argument(
        "--sheathing-waste-pct",
        type=float,
        default=12.0,
        help="Extra SF on wall sheathing (default 12%%)",
    )
    parser.add_argument(
        "-o",
        "--output-json",
        type=Path,
        default=_OUTPUT_DIR / "takeoff_framing.json",
        help="Full takeoff JSON output",
    )
    args = parser.parse_args()

    profile_path = args.profile.resolve()
    if not profile_path.is_file():
        print(f"Profile not found: {profile_path}")
        raise SystemExit(1)

    profile = load_json(profile_path)
    if "_merge_meta" in profile:
        profile = {k: v for k, v in profile.items() if k != "_merge_meta"}

    trade = load_json(args.trade.resolve())

    overrides: dict[str, Any] = {}
    if args.lf_json:
        if not args.lf_json.is_file():
            print(f"LF file not found: {args.lf_json}")
            raise SystemExit(1)
        overrides = load_json(args.lf_json.resolve())

    wall_types = profile.get("wall_types") or []
    if not isinstance(wall_types, list):
        wall_types = []
    tags = wall_tags_from_profile(profile)

    seed_lf: dict[str, float] = {}
    estimate_meta_block: dict[str, Any] | None = None
    audit_estimate: dict[str, Any] = {}

    if args.estimate_lf:
        if not args.pdf or not args.pdf.is_file():
            print("--estimate-lf requires a valid --pdf path")
            raise SystemExit(1)
        if not tags:
            print("Profile has no wall_types[].tag — cannot estimate LF")
            raise SystemExit(1)
        print("Estimating wall LF from PDF via OpenAI…")
        try:
            normalized, meta = estimate_lf_from_pdf(
                args.pdf.resolve(),
                tags,
                args.pages,
                args.lf_per_floor_estimate,
            )
        except RateLimitError as e:
            print("OpenAI rate limit:", e)
            print('Try a smaller PDF range: --pages "1-8"')
            raise SystemExit(1) from e
        except Exception as e:
            print("LF estimation failed:", e)
            raise SystemExit(1) from e

        for t in tags:
            seed_lf[t] = float(normalized["wall_linear_feet"].get(t, 0.0))

        wh_ai = normalized.get("wall_height_assumption_ft")
        try:
            wh_ai_f = float(wh_ai) if wh_ai else 0.0
        except (TypeError, ValueError):
            wh_ai_f = 0.0

        audit_estimate = {
            "wall_linear_feet": normalized["wall_linear_feet"],
            "roof_deck_sf": normalized.get("roof_deck_sf", 0),
            "wall_height_assumption_ft": wh_ai_f,
            "confidence": normalized.get("confidence"),
            "notes": normalized.get("notes"),
            "structural_hardware_notes": normalized.get("structural_hardware_notes"),
            "api_meta": meta,
        }
        estimate_meta_block = {
            "confidence": normalized.get("confidence"),
            "notes": normalized.get("notes"),
            "structural_hardware_notes": normalized.get("structural_hardware_notes"),
            "wall_height_assumption_ft": wh_ai_f,
            "roof_deck_sf": normalized.get("roof_deck_sf"),
        }

        est_path = args.estimate_save
        if not est_path.is_absolute():
            est_path = (Path.cwd() / est_path).resolve()
        est_path.parent.mkdir(parents=True, exist_ok=True)
        with open(est_path, "w", encoding="utf-8") as f:
            json.dump(audit_estimate, f, indent=2)
        print(f"Wrote LF estimate audit: {est_path}")

    wall_height = args.wall_height_ft
    if wall_height is None:
        wall_height = float(overrides.get("wall_height_ft") or 10.0)
    if (
        args.estimate_lf
        and args.wall_height_ft is None
        and not overrides.get("wall_height_ft")
        and audit_estimate.get("wall_height_assumption_ft")
    ):
        try:
            wh = float(audit_estimate["wall_height_assumption_ft"])
            if wh > 0:
                wall_height = wh
                print(f"Using AI wall height assumption: {wall_height} ft")
        except (TypeError, ValueError):
            pass

    roof_sf = float(overrides.get("roof_deck_sf") or 0.0)
    if roof_sf <= 0 and audit_estimate.get("roof_deck_sf"):
        try:
            roof_sf = float(audit_estimate["roof_deck_sf"])
        except (TypeError, ValueError):
            roof_sf = 0.0

    lf_per_floor = bool(overrides.get("lf_is_per_floor", False))
    floors = 1
    proj = profile.get("project") or {}
    try:
        floors = max(1, int(float(proj.get("floors") or 1)))
    except (TypeError, ValueError):
        floors = 1
    lf_floor_mult = floors if lf_per_floor else 1

    lf_by_tag = merge_lf_sources(wall_types, overrides, seed=seed_lf or None)
    lf_by_tag["_roof_deck_sf"] = roof_sf

    provenance = lf_provenance(tags, seed_lf, wall_types, overrides)

    result = run_takeoff(
        profile,
        trade,
        lf_by_tag,
        wall_height_ft=wall_height,
        stud_length_ft=float(args.stud_length_ft),
        sheathing_waste_pct=args.sheathing_waste_pct,
        lf_floor_mult=lf_floor_mult,
        lf_source_by_tag=provenance,
        lf_estimation_extras=estimate_meta_block,
    )

    supplier_lines = build_supplier_lines(result, args.stud_length_ft)
    result["supplier_list"] = supplier_lines

    out_json = args.output_json
    if not out_json.is_absolute():
        out_json = (Path.cwd() / out_json).resolve()
    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    csv_path = out_json.with_name("supplier_list_framing.csv")
    write_supplier_csv(csv_path, supplier_lines)
    xlsx_path = out_json.with_name("supplier_list_framing.xlsx")
    write_supplier_xlsx(xlsx_path, supplier_lines)

    missing_lf = sum(1 for r in result["wall_type_takeoff"] if r["linear_feet"] == 0)
    print(f"Wrote {out_json}")
    print(f"Wrote {csv_path}")
    if xlsx_path.is_file():
        print(f"Wrote {xlsx_path}")
    print(f"Wall types with LF still zero: {missing_lf}")
    print(f"Exterior framed wall LF (for sheathing): {result['sheathing']['exterior_framed_wall_lf']}")
    print(f"Wall sheathing sheets (4x8 equiv): {result['sheathing']['wall_sheathing_sheets_4x8_equiv']}")


if __name__ == "__main__":
    main()
