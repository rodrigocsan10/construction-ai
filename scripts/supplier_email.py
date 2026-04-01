#!/usr/bin/env python3
"""
Build a plain-text email body for lumber/sheathing supplier RFQ from framing takeoff JSON.

Reads:
  outputs/takeoff_framing.json (supplier_list)

Writes:
  outputs/supplier_email_framing.txt (default)
Prints same to stdout.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_TAKEOFF = _ROOT / "outputs" / "takeoff_framing.json"
_RECIPIENTS_NOTE = "84 Lumber, Builders FirstSource, Woodhaven Lumber (KB — edit as needed)"


def main() -> None:
    ap = argparse.ArgumentParser(description="Supplier RFQ email body from takeoff JSON")
    ap.add_argument("--takeoff", type=Path, default=_DEFAULT_TAKEOFF)
    ap.add_argument("-o", type=Path, dest="out", default=_ROOT / "outputs" / "supplier_email_framing.txt")
    args = ap.parse_args()

    path = args.takeoff.resolve()
    if not path.is_file():
        print(f"Missing {path}")
        raise SystemExit(1)

    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise SystemExit(1)

    proj = data.get("project") or {}
    name = proj.get("name") or "Project"
    supplier = data.get("supplier_list") or []

    body: list[str] = []
    body.append(f"Subject: Material quote request — {name}")
    body.append("")
    body.append(f"To: {_RECIPIENTS_NOTE}")
    body.append("")
    body.append("Please quote the following quantities (verify grade/spec on plans). Trusses / engineered members — see attached structural sheets.")
    body.append("")
    body.append("---")
    body.append("")

    for line in supplier:
        if not isinstance(line, dict):
            continue
        cat = line.get("category", "")
        item = line.get("item", "")
        qty = line.get("quantity", "")
        unit = line.get("unit", "")
        notes = line.get("notes", "")
        row = f"[{cat}] {qty} {unit} — {item}"
        if notes:
            row += f" | Note: {notes}"
        body.append(row)

    body.append("")
    body.append("---")
    body.append("")
    body.append("Fire blocking, hardware connectors, and shear nailing — field verify on structural drawings.")
    body.append("")

    text = "\n".join(body)
    print(text)

    out = args.out
    if not out.is_absolute():
        out = (Path.cwd() / out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"\nWrote {out}", flush=True)


if __name__ == "__main__":
    main()
