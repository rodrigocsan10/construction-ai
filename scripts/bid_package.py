#!/usr/bin/env python3
"""
Bid generator package: assemble branded PDF + optional photos + manifest JSON into a folder for GC upload / email attachment set.

Does not modify the PDF layout — use build_proposal_pdf.py first. This copies artifacts and writes package_manifest.json.

Usage:
  python scripts/build_proposal_pdf.py -i proposal.json -o outputs/my_bid.pdf --strict
  python scripts/bid_package.py --name building2_gc --pdf outputs/my_bid.pdf \\
    --photos assets/site_photo_1.jpg assets/site_photo_2.jpg \\
    --proposal-json proposal.json --out-dir outputs/bid_packages
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def main() -> None:
    ap = argparse.ArgumentParser(description="Assemble bid package folder (PDF + photos + manifest)")
    ap.add_argument("--name", required=True, help="Folder name under out-dir (e.g. job_slug)")
    ap.add_argument("--pdf", type=Path, required=True)
    ap.add_argument("--proposal-json", type=Path, help="Copy source JSON into package for your records")
    ap.add_argument("--photos", type=Path, nargs="*", default=[], help="Image files to include")
    ap.add_argument("--out-dir", type=Path, default=_ROOT / "outputs" / "bid_packages")
    args = ap.parse_args()

    pdf = args.pdf.resolve()
    if not pdf.is_file():
        raise SystemExit(f"Missing PDF: {pdf}")

    out = (args.out_dir / args.name).resolve()
    out.mkdir(parents=True, exist_ok=True)

    dest_pdf = out / pdf.name
    shutil.copy2(pdf, dest_pdf)

    photo_entries: list[dict[str, str]] = []
    for i, ph in enumerate(args.photos):
        ph = ph.resolve()
        if not ph.is_file():
            raise SystemExit(f"Missing photo: {ph}")
        dest = out / f"photo_{i + 1:02d}_{ph.name}"
        shutil.copy2(ph, dest)
        photo_entries.append({"path": dest.name, "sha256_16": _sha256(dest)})

    proposal_name = None
    if args.proposal_json:
        pj = args.proposal_json.resolve()
        if pj.is_file():
            proposal_name = "proposal_input.json"
            shutil.copy2(pj, out / proposal_name)

    manifest = {
        "package_name": args.name,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "primary_pdf": dest_pdf.name,
        "pdf_sha256_16": _sha256(dest_pdf),
        "photos": photo_entries,
        "proposal_json": proposal_name,
        "readme": "Professional bid package: PDF is the executed-style proposal; photos are optional job context.",
    }
    (out / "package_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    readme = out / "PACKAGE_README.txt"
    readme.write_text(
        f"Bid package: {args.name}\n"
        f"Primary proposal: {dest_pdf.name}\n"
        f"Manifest: package_manifest.json\n"
        "—\n"
        "Attach the PDF to email or upload per GC portal instructions.\n",
        encoding="utf-8",
    )

    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
