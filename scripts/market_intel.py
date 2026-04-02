#!/usr/bin/env python3
"""
Market intelligence: record bid outcomes ($, SF, trade) and summarize $/SF.

Usage:
  python scripts/market_intel.py record --outcome won --trade framing --amount 709000 --sf 121000 [--lead-id abc]
  python scripts/market_intel.py report [--trade framing] [--days 365]
"""

from __future__ import annotations

import argparse
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any

from ops_db import get_conn, init_db


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_record(args: argparse.Namespace) -> None:
    init_db()
    dpsf = None
    sf = args.building_sf
    if sf and sf > 0 and args.amount is not None:
        dpsf = round(float(args.amount) / float(sf), 4)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO bid_outcomes (lead_id, trade, outcome, bid_amount, building_sf, dollars_per_sf, close_reason, recorded_at)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                args.lead_id or "",
                args.trade or "",
                args.outcome,
                float(args.amount) if args.amount is not None else None,
                float(sf) if sf is not None else None,
                dpsf,
                args.reason or "",
                _now(),
            ),
        )
        conn.commit()
    print(f"Recorded outcome={args.outcome} trade={args.trade} $/SF={dpsf}")


def cmd_report(args: argparse.Namespace) -> None:
    init_db()
    since = None
    if args.days:
        since = (datetime.now(timezone.utc) - timedelta(days=int(args.days))).strftime("%Y-%m-%dT%H:%M:%SZ")
    q = "SELECT outcome, trade, bid_amount, building_sf, dollars_per_sf, recorded_at FROM bid_outcomes WHERE 1=1"
    params: list[Any] = []
    if args.trade:
        q += " AND trade = ?"
        params.append(args.trade)
    if since:
        q += " AND recorded_at >= ?"
        params.append(since)
    q += " ORDER BY recorded_at DESC"
    with get_conn() as conn:
        rows = conn.execute(q, params).fetchall()

    if not rows:
        print("No records.")
        return

    dpsf_vals = [r["dollars_per_sf"] for r in rows if r["dollars_per_sf"] is not None]
    print(f"Records: {len(rows)}")
    if dpsf_vals:
        print(f"$/SF mean: {statistics.mean(dpsf_vals):.4f}  median: {statistics.median(dpsf_vals):.4f}")
    by_out: dict[str, int] = {}
    for r in rows:
        by_out[r["outcome"]] = by_out.get(r["outcome"], 0) + 1
    print("By outcome:", ", ".join(f"{k}={v}" for k, v in sorted(by_out.items())))

    print("\nLast 15:")
    for r in rows[:15]:
        print(
            f"  {r['recorded_at'][:10]}  {r['outcome']:<8}  {r['trade'] or '—':<12}  "
            f"${r['bid_amount'] or 0:,.0f}  SF={r['building_sf'] or '—'}  $/SF={r['dollars_per_sf']}"
        )


def main() -> None:
    ap = argparse.ArgumentParser(description="Bid outcomes / market intel")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_rec = sub.add_parser("record", help="Append one outcome row")
    p_rec.add_argument("--outcome", required=True, choices=("won", "lost", "no_bid", "pending", "negotiating"))
    p_rec.add_argument("--trade", default="", help="e.g. framing, drywall, windows")
    p_rec.add_argument("--amount", type=float, help="Bid price ($)")
    p_rec.add_argument("--sf", type=float, dest="building_sf", help="Building SF for $/SF")
    p_rec.add_argument("--lead-id", default="", dest="lead_id")
    p_rec.add_argument("--reason", help="Close / no-bid reason")
    p_rec.set_defaults(func=cmd_record)

    p_rep = sub.add_parser("report", help="Summarize stored outcomes")
    p_rep.add_argument("--trade")
    p_rep.add_argument("--days", type=int, default=365)
    p_rep.set_defaults(func=cmd_report)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
