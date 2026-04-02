#!/usr/bin/env python3
"""
Local CRM: SQLite-backed leads (stages, notes, UTM fields for ads attribution).

Usage:
  python scripts/crm_cli.py init
  python scripts/crm_cli.py add --project "Building 2" --gc-email gc@x.com --source planhub --state NJ --sf 55000
  python scripts/crm_cli.py list [--stage qualified]
  python scripts/crm_cli.py show <lead_id>
  python scripts/crm_cli.py stage <lead_id> quoted
  python scripts/crm_cli.py note <lead_id> "Called — bid due Friday"
  python scripts/crm_cli.py utm <lead_id> --source google --medium cpc --campaign framing-q2
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from ops_db import get_conn, init_db, row_to_dict


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_init(_: argparse.Namespace) -> None:
    init_db()
    print("OK — schema ready at data/crm/ops.sqlite3")


def cmd_add(args: argparse.Namespace) -> None:
    init_db()
    lid = args.id or uuid.uuid4().hex[:12]
    ts = _now()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO leads (id, source, project_name, gc_name, gc_email, phone, state, zip, trades, est_sf, stage, notes, utm_source, utm_medium, utm_campaign, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                lid,
                args.source or "",
                args.project or "",
                args.gc_name or "",
                args.gc_email or "",
                args.phone or "",
                args.state or "",
                args.zip or "",
                args.trades or "",
                float(args.est_sf) if args.est_sf is not None else None,
                args.stage or "new",
                args.notes or "",
                args.utm_source or "",
                args.utm_medium or "",
                args.utm_campaign or "",
                ts,
                ts,
            ),
        )
        conn.commit()
    print(lid)


def cmd_list(args: argparse.Namespace) -> None:
    init_db()
    q = "SELECT id, project_name, gc_email, stage, est_sf, source, updated_at FROM leads WHERE 1=1"
    params: list[Any] = []
    if args.stage:
        q += " AND stage = ?"
        params.append(args.stage)
    q += " ORDER BY updated_at DESC"
    with get_conn() as conn:
        rows = conn.execute(q, params).fetchall()
    for r in rows:
        print(
            f"{r['id']}\t{r['stage']}\t{r['project_name'] or '—'}\t"
            f"sf={r['est_sf'] or '—'}\t{r['gc_email'] or '—'}\t{r['source'] or '—'}"
        )


def cmd_show(args: argparse.Namespace) -> None:
    init_db()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (args.lead_id,)).fetchone()
    if not row:
        raise SystemExit(f"Unknown lead: {args.lead_id}")
    print(json.dumps(row_to_dict(row), indent=2))


def cmd_stage(args: argparse.Namespace) -> None:
    init_db()
    ts = _now()
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE leads SET stage = ?, updated_at = ? WHERE id = ?",
            (args.new_stage, ts, args.lead_id),
        )
        conn.commit()
    if cur.rowcount == 0:
        raise SystemExit(f"Unknown lead: {args.lead_id}")
    print("OK")


def cmd_note(args: argparse.Namespace) -> None:
    init_db()
    ts = _now()
    with get_conn() as conn:
        row = conn.execute("SELECT notes FROM leads WHERE id = ?", (args.lead_id,)).fetchone()
        if not row:
            raise SystemExit(f"Unknown lead: {args.lead_id}")
        prev = row["notes"] or ""
        block = f"[{ts}] {args.text}"
        new_notes = f"{prev}\n{block}".strip() if prev else block
        conn.execute(
            "UPDATE leads SET notes = ?, updated_at = ? WHERE id = ?",
            (new_notes, ts, args.lead_id),
        )
        conn.commit()
    print("OK")


def cmd_utm(args: argparse.Namespace) -> None:
    init_db()
    ts = _now()
    with get_conn() as conn:
        cur = conn.execute(
            """
            UPDATE leads SET utm_source = COALESCE(?, utm_source), utm_medium = COALESCE(?, utm_medium),
            utm_campaign = COALESCE(?, utm_campaign), updated_at = ?
            WHERE id = ?
            """,
            (
                args.source or None,
                args.medium or None,
                args.campaign or None,
                ts,
                args.lead_id,
            ),
        )
        conn.commit()
    if cur.rowcount == 0:
        raise SystemExit(f"Unknown lead: {args.lead_id}")
    print("OK")


def main() -> None:
    ap = argparse.ArgumentParser(description="Local CRM (SQLite)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="Create DB + tables")
    p_init.set_defaults(func=cmd_init)

    p_add = sub.add_parser("add", help="Insert lead")
    p_add.add_argument("--id")
    p_add.add_argument("--project")
    p_add.add_argument("--gc-name")
    p_add.add_argument("--gc-email")
    p_add.add_argument("--phone")
    p_add.add_argument("--source", help="e.g. planhub, website, referral")
    p_add.add_argument("--state")
    p_add.add_argument("--zip")
    p_add.add_argument("--trades", help="Comma-separated or free text")
    p_add.add_argument("--sf", type=float, dest="est_sf")
    p_add.add_argument("--stage", default="new")
    p_add.add_argument("--notes")
    p_add.add_argument("--utm-source")
    p_add.add_argument("--utm-medium")
    p_add.add_argument("--utm-campaign")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="List leads")
    p_list.add_argument("--stage")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="JSON detail")
    p_show.add_argument("lead_id")
    p_show.set_defaults(func=cmd_show)

    p_stage = sub.add_parser("stage", help="Set pipeline stage")
    p_stage.add_argument("lead_id")
    p_stage.add_argument("new_stage")
    p_stage.set_defaults(func=cmd_stage)

    p_note = sub.add_parser("note", help="Append timestamped note")
    p_note.add_argument("lead_id")
    p_note.add_argument("text")
    p_note.set_defaults(func=cmd_note)

    p_utm = sub.add_parser("utm", help="Set UTM attribution fields")
    p_utm.add_argument("lead_id")
    p_utm.add_argument("--source")
    p_utm.add_argument("--medium")
    p_utm.add_argument("--campaign")
    p_utm.set_defaults(func=cmd_utm)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
