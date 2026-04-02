#!/usr/bin/env python3
"""
Website / ads analytics: import GA4 (or similar) session export CSV into SQLite for offline joins with CRM leads.

GA4 path: Reports → Acquisition → Traffic acquisition → Share → Download CSV.
Column names vary by locale; this script normalizes common English headers.

Usage:
  python scripts/analytics_ingest.py ga-csv ~/Downloads/traffic_acquisition.csv
  python scripts/analytics_ingest.py ga-csv export.csv --summary
  python scripts/analytics_ingest.py lead-utm <lead_id> --source google --medium cpc --campaign framing
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ops_db import get_conn, init_db


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm_col(c: str) -> str:
    return re.sub(r"\s+", " ", str(c).strip().lower())


def normalize_ga_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Map flexible header names to canonical columns."""
    colmap: dict[str, str] = {}
    for c in df.columns:
        n = _norm_col(c)
        if n in ("session primary channel group (dimensional)", "session primary channel group"):
            colmap[c] = "channel"
        elif "session source" in n and "medium" not in n:
            colmap[c] = "session_source"
        elif "session medium" in n:
            colmap[c] = "session_medium"
        elif "session campaign" in n:
            colmap[c] = "session_campaign"
        elif n in ("sessions",) or n.endswith(" sessions"):
            colmap[c] = "sessions"
        elif "engaged sessions" in n:
            colmap[c] = "engaged_sessions"
        elif "key events" in n or n == "conversions":
            colmap[c] = "conversions"
        elif re.match(r"^\d{4}-\d{2}-\d{2}$", n) or n == "date":
            colmap[c] = "row_date"

    out = df.rename(columns=colmap)
    # If first column looks like dates (wide pivot export), melt is complex — skip for v1
    return out


def cmd_ga_csv(args: argparse.Namespace) -> None:
    path = args.csv.resolve()
    if not path.is_file():
        raise SystemExit(f"Missing file: {path}")
    df = pd.read_csv(path)
    df = normalize_ga_dataframe(df)
    need = ["session_source", "session_medium"]
    if not any(c in df.columns for c in need):
        print("Columns found:", list(df.columns))
        raise SystemExit(
            "Could not detect Session source / Session medium columns. "
            "Edit the CSV export or extend normalize_ga_dataframe() in scripts/analytics_ingest.py"
        )

    init_db()
    ts = _now()
    rows_inserted = 0
    with get_conn() as conn:
        for _, row in df.iterrows():
            src = str(row.get("session_source", "") or "").strip() or None
            med = str(row.get("session_medium", "") or "").strip() or None
            camp = str(row.get("session_campaign", "") or "").strip() or None
            rd = str(row.get("row_date", "") or "").strip() or None
            def num(x: Any) -> int | None:
                if x is None or (isinstance(x, float) and pd.isna(x)):
                    return None
                try:
                    return int(float(str(x).replace(",", "")))
                except ValueError:
                    return None

            sess = num(row.get("sessions"))
            eng = num(row.get("engaged_sessions"))
            conv = num(row.get("conversions"))
            if not src and not med:
                continue
            conn.execute(
                """
                INSERT INTO analytics_ga_rows
                (row_date, session_source, session_medium, session_campaign, sessions, engaged_sessions, conversions, imported_at, source_file)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (rd, src, med, camp, sess, eng, conv, ts, str(path)),
            )
            rows_inserted += 1
        conn.commit()

    print(f"Imported {rows_inserted} rows from {path.name}")

    if args.summary:
        cmd_summary(args)


def cmd_summary(args: argparse.Namespace) -> None:
    init_db()
    with get_conn() as conn:
        cur = conn.execute(
            """
            SELECT session_source, session_medium,
                   SUM(COALESCE(sessions,0)) AS s, SUM(COALESCE(conversions,0)) AS c
            FROM analytics_ga_rows
            GROUP BY session_source, session_medium
            ORDER BY s DESC
            LIMIT 20
            """
        )
        rows = cur.fetchall()
    if not rows:
        print("No analytics rows — run ga-csv first.")
        return
    print("Top source/medium by sessions (last import aggregate):")
    for r in rows:
        print(f"  {r['session_source'] or '—'} / {r['session_medium'] or '—'}  sessions={r['s'] or 0}  conv={r['c'] or 0}")


def cmd_lead_utm(args: argparse.Namespace) -> None:
    init_db()
    ts = _now()
    with get_conn() as conn:
        cur = conn.execute(
            """
            UPDATE leads SET utm_source = ?, utm_medium = ?, utm_campaign = ?, updated_at = ?
            WHERE id = ?
            """,
            (args.source or "", args.medium or "", args.campaign or "", ts, args.lead_id),
        )
        conn.commit()
    if cur.rowcount == 0:
        raise SystemExit(f"Unknown lead: {args.lead_id}")
    print("OK")


def main() -> None:
    ap = argparse.ArgumentParser(description="Analytics ingest + lead UTM")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_ga = sub.add_parser("ga-csv", help="Import GA4 traffic CSV")
    p_ga.add_argument("csv", type=Path)
    p_ga.add_argument("--summary", action="store_true", help="Print rollup after import")
    p_ga.set_defaults(func=cmd_ga_csv)

    p_sum = sub.add_parser("summary", help="Rollup imported GA rows")
    p_sum.set_defaults(func=cmd_summary)

    p_u = sub.add_parser("lead-utm", help="Attach UTM fields to a CRM lead")
    p_u.add_argument("lead_id")
    p_u.add_argument("--source", required=True)
    p_u.add_argument("--medium", required=True)
    p_u.add_argument("--campaign", default="")
    p_u.set_defaults(func=cmd_lead_utm)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
