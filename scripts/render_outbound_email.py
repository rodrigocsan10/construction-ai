#!/usr/bin/env python3
"""
Email generation: render text templates with CRM lead fields ($placeholders) and optionally send via SMTP.

Templates use Python string.Template syntax: $project_name, $gc_email, $est_sf, $stage, etc.

Usage:
  python scripts/render_outbound_email.py --template config/email_templates/follow_up_7d.txt --lead-id <id> --print
  python scripts/render_outbound_email.py -t config/email_templates/introduction.txt -l <id> --to gc@x.com --subject "Follow up" --send
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from string import Template

from ops_db import get_conn, init_db
from smtp_util import send_plain_email


def lead_mapping(lead_id: str) -> dict[str, str]:
    init_db()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    if not row:
        raise SystemExit(f"Unknown lead: {lead_id}")
    d = {k: row[k] for k in row.keys()}
    out: dict[str, str] = {}
    for k, v in d.items():
        if v is None:
            out[k] = ""
        elif isinstance(v, float):
            out[k] = str(int(v)) if v == int(v) else str(v)
        else:
            out[k] = str(v)
    # Aliases for templates
    out.setdefault("company_name", "")
    return out


def render_template(path: Path, mapping: dict[str, str]) -> str:
    raw = path.read_text(encoding="utf-8")
    return Template(raw).safe_substitute(mapping)


def main() -> None:
    ap = argparse.ArgumentParser(description="Render email template from CRM lead + optional send")
    ap.add_argument("--template", "-t", type=Path, required=True)
    ap.add_argument("--lead-id", "-l", required=True)
    ap.add_argument("--extra-json", type=Path, help="Merge keys into template context (JSON object)")
    ap.add_argument("--print", action="store_true", dest="print_body", help="Write body to stdout")
    ap.add_argument("--out", type=Path, help="Save rendered body to file")
    ap.add_argument("--to", action="append", dest="recipients", help="Recipient (required for --send)")
    ap.add_argument("--subject", help="Required with --send")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="With --send: show MIME only")
    args = ap.parse_args()

    tpl = args.template.resolve()
    if not tpl.is_file():
        raise SystemExit(f"Missing template: {tpl}")

    m = lead_mapping(args.lead_id)
    if args.extra_json:
        extra = json.loads(args.extra_json.read_text(encoding="utf-8"))
        if not isinstance(extra, dict):
            raise SystemExit("--extra-json must be a JSON object")
        for k, v in extra.items():
            m[str(k)] = "" if v is None else str(v)

    body = render_template(tpl, m)

    if args.out:
        args.out.write_text(body, encoding="utf-8")
        print(f"Wrote {args.out}")

    if args.print_body:
        print(body)

    if args.send:
        if not args.recipients or not args.subject:
            raise SystemExit("--send requires --to and --subject")
        send_plain_email(
            recipients=args.recipients,
            subject=args.subject,
            body=body,
            dry_run=args.dry_run,
        )
        if not args.dry_run:
            print(f"Sent to {args.recipients}")

    if not args.out and not args.print_body and not args.send:
        print(body)


if __name__ == "__main__":
    main()
