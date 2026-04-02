#!/usr/bin/env python3
"""
POST CRM lead JSON to a webhook (Airtable automation, Zapier, Make, internal API).

Set CRM_WEBHOOK_URL in .env (see config/integrations.example.json).

Usage:
  python scripts/crm_webhook.py --lead-id <id> [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

from ops_db import get_conn, init_db, row_to_dict


def main() -> None:
    ap = argparse.ArgumentParser(description="POST lead JSON to CRM_WEBHOOK_URL")
    ap.add_argument("--lead-id", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    url = os.getenv("CRM_WEBHOOK_URL", "").strip()
    if not url and not args.dry_run:
        raise SystemExit("Set CRM_WEBHOOK_URL in .env")

    init_db()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (args.lead_id,)).fetchone()
    if not row:
        raise SystemExit(f"Unknown lead: {args.lead_id}")

    payload = {"type": "construction_ai.lead", "lead": row_to_dict(row)}
    body = json.dumps(payload).encode("utf-8")

    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            print(f"OK HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Webhook HTTP {e.code}: {e.read()[:500]!r}") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"Webhook failed: {e}") from e


if __name__ == "__main__":
    main()
