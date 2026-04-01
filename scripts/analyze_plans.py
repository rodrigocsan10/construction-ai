#!/usr/bin/env python3
"""
Run full plan analysis (prompts/plan_analysis.txt) on a construction PDF via OpenAI.
Writes JSON to outputs/plan_analysis.json by default.

Large PDFs often exceed API token limits — use --pages or --max-pages to send a subset.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from openai import RateLimitError
from pypdf import PdfReader, PdfWriter

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PROMPT_PATH = _PROJECT_ROOT / "prompts" / "plan_analysis.txt"
_OUTPUT_DIR = _PROJECT_ROOT / "outputs"

load_dotenv(_PROJECT_ROOT / ".env")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def load_prompt() -> str:
    if not _PROMPT_PATH.is_file():
        raise FileNotFoundError(f"Missing prompt file: {_PROMPT_PATH}")
    return _PROMPT_PATH.read_text(encoding="utf-8")


def pdf_page_count(pdf_path: Path) -> int:
    reader = PdfReader(str(pdf_path))
    return len(reader.pages)


def parse_page_range(spec: str, total_pages: int) -> tuple[int, int]:
    """1-based inclusive range, e.g. '1-50' or '3' for a single page."""
    spec = spec.strip().replace(" ", "")
    if "-" in spec:
        a, b = spec.split("-", 1)
        start, end = int(a), int(b)
    else:
        start = end = int(spec)
    if start < 1:
        start = 1
    if end < start:
        end = start
    if start > total_pages:
        raise ValueError(f"Start page {start} is beyond PDF length ({total_pages} pages).")
    end = min(end, total_pages)
    return start, end


def slice_pdf_pages(src: Path, start: int, end: int) -> Path:
    """Write pages [start, end] (1-based inclusive) to a temp PDF; caller should unlink when done."""
    reader = PdfReader(str(src))
    total = len(reader.pages)
    writer = PdfWriter()
    for i in range(start - 1, end):
        if i < total:
            writer.add_page(reader.pages[i])
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    out = Path(path)
    with open(out, "wb") as f:
        writer.write(f)
    return out


def _parse_json_output(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


def analyze_pdf(pdf_path: str) -> tuple[dict[str, Any], str]:
    instructions = load_prompt()

    with open(pdf_path, "rb") as f:
        uploaded = client.files.create(file=f, purpose="assistants")

    result = client.responses.create(
        model="gpt-4.1",
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": instructions},
                    {"type": "input_file", "file_id": uploaded.id},
                ],
            }
        ],
        text={"format": {"type": "json_object"}},
    )

    raw = (result.output_text or "").strip()
    data = _parse_json_output(raw)
    return data, raw


def main() -> None:
    default_pdf = _PROJECT_ROOT / "data" / "Plan1.pdf"
    parser = argparse.ArgumentParser(
        description="Deep plan analysis (schedules, structure, notes) → JSON."
    )
    parser.add_argument(
        "pdf",
        nargs="?",
        default=default_pdf,
        type=Path,
        help=f"Path to PDF (default: {default_pdf})",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=_OUTPUT_DIR / "plan_analysis.json",
        help=f"Output JSON path (default: {_OUTPUT_DIR / 'plan_analysis.json'})",
    )
    parser.add_argument(
        "--pages",
        type=str,
        default=None,
        metavar="START-END",
        help='Only send this page range (1-based, inclusive), e.g. "1-40"',
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        metavar="N",
        help="Send only the first N pages (same as --pages 1-N). Ignored if --pages is set.",
    )
    parser.add_argument(
        "--list-pages",
        action="store_true",
        help="Print total page count and exit (no API call).",
    )
    args = parser.parse_args()

    pdf_path = args.pdf if args.pdf.is_absolute() else (Path.cwd() / args.pdf).resolve()
    if not pdf_path.is_file():
        print(f"Error: PDF not found: {pdf_path}")
        raise SystemExit(1)

    total = pdf_page_count(pdf_path)
    if args.list_pages:
        print(f"{pdf_path.name}: {total} pages")
        raise SystemExit(0)

    start, end = 1, total
    if args.pages:
        start, end = parse_page_range(args.pages, total)
    elif args.max_pages is not None:
        if args.max_pages < 1:
            print("--max-pages must be at least 1")
            raise SystemExit(1)
        start, end = 1, min(args.max_pages, total)

    tmp_pdf: Path | None = None
    upload_path = pdf_path
    if (start, end) != (1, total):
        tmp_pdf = slice_pdf_pages(pdf_path, start, end)
        upload_path = tmp_pdf
        print(
            f"Using pages {start}-{end} of {total} (smaller upload helps avoid token limits)."
        )

    out_path = args.output
    if not out_path.is_absolute():
        out_path = (Path.cwd() / out_path).resolve()

    print("Calling OpenAI (plan analysis may take a few minutes)...")
    try:
        data, raw = analyze_pdf(str(upload_path))
    except RateLimitError as e:
        err = str(e).lower()
        print("\nOpenAI rate / size limit:", e)
        if "token" in err or "large" in err or "tpm" in err:
            print(
                "\nTip: Your PDF (or full set of pages) is too large for the current limit.\n"
                f"      This file has {total} pages. Try fewer pages, e.g.:\n"
                f'        python scripts/analyze_plans.py "{pdf_path}" --pages 1-25\n'
                f"        python scripts/analyze_plans.py \"{pdf_path}\" --max-pages 30\n"
                "      Run several ranges and merge JSON if needed."
            )
        raise SystemExit(1)
    finally:
        if tmp_pdf is not None and tmp_pdf.is_file():
            tmp_pdf.unlink(missing_ok=True)

    meta = {
        "_source_pdf": str(pdf_path),
        "_pages_analyzed": f"{start}-{end}" if (start, end) != (1, total) else f"1-{total}",
        "_total_pages_in_file": total,
    }
    if isinstance(data, dict):
        out_obj = {**meta, **data}
    else:
        out_obj = {"_meta": meta, "result": data}

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out_obj, f, indent=2)

    print(f"Saved JSON to: {out_path}")
    if raw != json.dumps(data):
        print("(Response was normalized; saved parsed JSON.)")


if __name__ == "__main__":
    main()
