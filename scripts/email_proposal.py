#!/usr/bin/env python3
"""
Send proposal markdown (or plain text) via SMTP — Phase A automation stub.

Requires env (see config/integrations.example.json):
  SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD,
  PROPOSAL_FROM_EMAIL

Usage:
  python scripts/email_proposal.py --to gc@example.com --subject "Proposal — Building 2" \\
    --file outputs/proposal_draft.md
"""

from __future__ import annotations

import argparse
from pathlib import Path

from smtp_util import send_plain_email


def main() -> None:
    ap = argparse.ArgumentParser(description="Email proposal file (SMTP)")
    ap.add_argument("--to", required=True, action="append", dest="recipients", help="Recipient (repeat for multiple)")
    ap.add_argument("--subject", required=True)
    ap.add_argument("--file", type=Path, required=True, help="Markdown or .txt body")
    ap.add_argument("--dry-run", action="store_true", help="Print MIME summary only")
    args = ap.parse_args()

    path = args.file.resolve()
    if not path.is_file():
        raise SystemExit(f"Missing {path}")

    body = path.read_text(encoding="utf-8")
    send_plain_email(
        recipients=args.recipients,
        subject=args.subject,
        body=body,
        dry_run=args.dry_run,
    )
    if not args.dry_run:
        print(f"Sent to {args.recipients}")


if __name__ == "__main__":
    main()
