#!/usr/bin/env python3
"""
Lead pipeline: import PlanHub (or any) job CSV → filter by state / SF / trade keywords → optional CRM insert.

PlanHub and other portals export different column names — map them in JSON (see config/lead_pipeline.example.json).

Usage:
  python scripts/lead_pipeline.py --config config/lead_pipeline.example.json \\
    import config/examples/planhub_export_sample.csv --dry-run
  python scripts/lead_pipeline.py --config config/lead_pipeline.example.json \\
    import path/to/export.csv --to-crm
"""

from __future__ import annotations

import argparse
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ops_db import get_conn, init_db

_ROOT = Path(__file__).resolve().parent.parent


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_config(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "columns" not in data:
        raise SystemExit("Config must include 'columns' map: logical_name -> CSV header")
    return data


def normalize_frame(df: pd.DataFrame, colmap: dict[str, str]) -> pd.DataFrame:
    """Rename CSV columns to logical names where headers match."""
    inv = {v.strip(): k for k, v in colmap.items()}
    rename = {c: inv[c] for c in df.columns if str(c).strip() in inv}
    out = df.rename(columns=rename)
    return out


def _coerce_sf(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    return s


def apply_filters(df: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    f = cfg.get("filters") or {}
    out = df.copy()
    if "est_sf" in out.columns:
        out["_sf"] = _coerce_sf(out["est_sf"])
        lo = f.get("min_sf")
        hi = f.get("max_sf")
        if lo is not None:
            out = out[out["_sf"].fillna(0) >= float(lo)]
        if hi is not None:
            out = out[out["_sf"].fillna(1e12) <= float(hi)]
    states = f.get("states_allowlist")
    if states and "state" in out.columns:
        allow = {str(x).strip().upper() for x in states}
        out = out[out["state"].astype(str).str.upper().isin(allow)]
    keywords = f.get("trade_keywords")
    if keywords and "trades" in out.columns:
        pat = "|".join(re.escape(k.lower()) for k in keywords)
        mask = out["trades"].astype(str).str.lower().str.contains(pat, na=False, regex=True)
        out = out[mask]
    return out.drop(columns=["_sf"], errors="ignore")


def _fix_zip(v: Any) -> str:
    if pd.isna(v) or v is None:
        return ""
    s = str(v).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    if s.isdigit() and len(s) < 5:
        return s.zfill(5)
    return s


def row_to_lead_tuple(row: pd.Series, source: str, ts: str) -> tuple[Any, ...]:
    lid = uuid.uuid4().hex[:12]
    def g(k: str, default: str = "") -> str:
        if k not in row.index:
            return default
        v = row[k]
        if pd.isna(v):
            return default
        return str(v).strip()

    sf = None
    if "est_sf" in row.index and pd.notna(row["est_sf"]):
        try:
            sf = float(row["est_sf"])
        except (TypeError, ValueError):
            sf = None

    return (
        lid,
        source,
        g("project_name"),
        g("gc_name"),
        g("gc_email"),
        g("phone"),
        g("state"),
        g("zip"),
        g("trades"),
        sf,
        "new",
        "",
        "",  # utm
        "",
        "",
        ts,
        ts,
    )


def cmd_import(args: argparse.Namespace) -> None:
    cfg = load_config(args.config.resolve())
    csv_path = args.csv.resolve()
    if not csv_path.is_file():
        raise SystemExit(f"Missing CSV: {csv_path}")

    df = pd.read_csv(csv_path)
    df = normalize_frame(df, cfg["columns"])
    filtered = apply_filters(df, cfg)
    if "zip" in filtered.columns:
        filtered = filtered.copy()
        filtered["zip"] = filtered["zip"].map(_fix_zip)
    source = cfg.get("import_source_label") or "csv_import"

    print(f"Rows in file: {len(df)}  After filters: {len(filtered)}")
    if args.dry_run or not args.to_crm:
        for _, row in filtered.head(50).iterrows():
            pname = row.get("project_name", row.iloc[0] if len(row) else "")
            print(f"  — {pname}")
        if len(filtered) > 50:
            print(f"  … ({len(filtered) - 50} more)")
        return

    init_db()
    ts = _now()
    cols = (
        "id, source, project_name, gc_name, gc_email, phone, state, zip, trades, est_sf, "
        "stage, notes, utm_source, utm_medium, utm_campaign, created_at, updated_at"
    )
    with get_conn() as conn:
        for _, row in filtered.iterrows():
            tup = row_to_lead_tuple(row, source, ts)
            conn.execute(f"INSERT INTO leads ({cols}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", tup)
        conn.commit()
    print(f"Inserted {len(filtered)} leads into CRM")


def main() -> None:
    ap = argparse.ArgumentParser(description="Lead pipeline CSV import + filters")
    ap.add_argument(
        "--config",
        type=Path,
        default=_ROOT / "config" / "lead_pipeline.example.json",
        help="Column map + filters JSON",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_imp = sub.add_parser("import", help="Import CSV")
    p_imp.add_argument("csv", type=Path)
    p_imp.add_argument("--dry-run", action="store_true")
    p_imp.add_argument("--to-crm", action="store_true", help="Write matching rows to SQLite CRM")
    p_imp.set_defaults(func=cmd_import)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
