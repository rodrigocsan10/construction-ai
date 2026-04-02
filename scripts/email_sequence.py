#!/usr/bin/env python3
"""
Generate a multi-step email sequence (draft bodies + subjects) from config/email_sequence.example.json.

Does not send — use render_outbound_email.py --send per step, or paste from files.

Usage:
  python scripts/email_sequence.py --lead-id <id> --config config/email_sequence.example.json --out-dir outputs/email_drafts/my_lead
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from string import Template

_ROOT = Path(__file__).resolve().parent.parent

# Import lead_mapping from sibling (same dir on sys.path)
from ops_db import get_conn, init_db


def _lead_dict(lead_id: str) -> dict[str, str]:
    init_db()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    if not row:
        raise SystemExit(f"Unknown lead: {lead_id}")
    out: dict[str, str] = {}
    for k in row.keys():
        v = row[k]
        out[k] = "" if v is None else (str(int(v)) if isinstance(v, float) and v == int(v) else str(v))
    return out


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:40] or "step"


def main() -> None:
    ap = argparse.ArgumentParser(description="Render email sequence drafts for a lead")
    ap.add_argument("--lead-id", "-l", required=True)
    ap.add_argument("--config", "-c", type=Path, default=_ROOT / "config" / "email_sequence.example.json")
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()

    cfg_path = args.config.resolve()
    if not cfg_path.is_file():
        raise SystemExit(f"Missing {cfg_path}")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    steps = cfg.get("steps")
    if not isinstance(steps, list) or not steps:
        raise SystemExit("Config must contain 'steps': [ { template, subject }, ... ]")

    m = _lead_dict(args.lead_id)
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, step in enumerate(steps, start=1):
        tpl_p = Path(step["template"])
        if not tpl_p.is_absolute():
            tpl_p = (_ROOT / tpl_p).resolve()
        subj_t = Template(str(step.get("subject") or f"Update $project_name"))
        subject = subj_t.safe_substitute(m)
        body = Template(tpl_p.read_text(encoding="utf-8")).safe_substitute(m)
        tag = _slug(step.get("name") or f"step_{i}")
        base = out_dir / f"{i:02d}_{tag}"
        base.with_suffix(".subject.txt").write_text(subject, encoding="utf-8")
        base.with_suffix(".body.txt").write_text(body, encoding="utf-8")

    print(f"Wrote {len(steps)} steps to {out_dir}")


if __name__ == "__main__":
    main()
