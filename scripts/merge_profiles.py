#!/usr/bin/env python3
"""
Merge outputs/plan_analysis*.json into a single plan_profile_complete.json.

- wall_types, doors, windows: concatenate, dedupe by tag (keep richest entry).
- Other objects (project, structural, ...): field-wise merge; prefer values with more content.
- List fields inside objects: concatenate where sensible, else dedupe.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_OUTPUTS = _PROJECT_ROOT / "outputs"
_DEFAULT_OUT = _DEFAULT_OUTPUTS / "plan_profile_complete.json"

# Arrays keyed by tag (case-insensitive)
TAGGED_ARRAYS: tuple[tuple[str, str], ...] = (
    ("wall_types", "tag"),
    ("doors", "tag"),
    ("windows", "tag"),
)


def richness_score(v: Any) -> float:
    """Higher = more informative (for picking one of several field values)."""
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(abs(v)) + (0.5 if v else 0.0)
    if isinstance(v, str):
        return float(len(v.strip()))
    if isinstance(v, dict):
        return sum(richness_score(x) for x in v.values())
    if isinstance(v, list):
        return float(len(v)) + sum(richness_score(x) for x in v if isinstance(x, dict))
    return 1.0


def item_depth_score(obj: dict[str, Any]) -> float:
    """Total richness of a schedule row (for tie-breaking duplicate tags)."""
    return richness_score(obj)


def merge_tagged_arrays(
    blobs: list[dict[str, Any]], array_key: str, tag_key: str
) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for blob in blobs:
        items = blob.get(array_key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            raw = item.get(tag_key, "")
            tag = str(raw).strip()
            norm = tag.lower() if tag else ""
            if not norm:
                norm = f"__no_tag_{len(best)}"
            score = item_depth_score(item)
            prev = best.get(norm)
            if prev is None or score > item_depth_score(prev):
                best[norm] = item
    # Stable sort by tag for readability
    return sorted(best.values(), key=lambda x: str(x.get(tag_key, "")).lower())


def merge_list_concat_unique(parts: list[list[Any]]) -> list[Any]:
    out: list[Any] = []
    seen: set[str] = set()
    for lst in parts:
        if not isinstance(lst, list):
            continue
        for x in lst:
            key = json.dumps(x, sort_keys=True) if isinstance(x, (dict, list)) else repr(x)
            if key not in seen:
                seen.add(key)
                out.append(x)
    return out


def merge_dicts_richest(*dicts: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge dicts: nested dicts merge; lists concat+dedupe; scalars pick richest."""
    objs = [d for d in dicts if isinstance(d, dict)]
    if not objs:
        return {}
    keys: set[str] = set()
    for o in objs:
        keys |= o.keys()
    out: dict[str, Any] = {}
    for k in sorted(keys):
        vals = [o[k] for o in objs if k in o]
        if not vals:
            continue
        if all(isinstance(v, dict) for v in vals):
            out[k] = merge_dicts_richest(*vals)
            continue
        if all(isinstance(v, list) for v in vals):
            out[k] = merge_list_concat_unique(vals)
            continue
        if any(isinstance(v, dict) for v in vals) and any(not isinstance(v, dict) for v in vals):
            # Mixed — pick richest single value
            out[k] = max(vals, key=richness_score)
            continue
        out[k] = max(vals, key=richness_score)
    return out


def load_plan_blobs(outputs_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (data blobs, metadata about each file)."""
    pattern = "plan_analysis*.json"
    files = sorted(outputs_dir.glob(pattern))
    blobs: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for path in files:
        if path.name == "plan_profile_complete.json":
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            continue
        blobs.append(data)
        sources.append(
            {
                "file": path.name,
                "path": str(path.resolve()),
                "_source_pdf": data.get("_source_pdf"),
                "_pages_analyzed": data.get("_pages_analyzed"),
                "_total_pages_in_file": data.get("_total_pages_in_file"),
            }
        )
    return blobs, sources


def merge_profiles(blobs: list[dict[str, Any]]) -> dict[str, Any]:
    if not blobs:
        return {}

    merged: dict[str, Any] = {}

    # Project + nested objects (excluding tagged arrays handled separately)
    dict_keys = {"project", "structural", "sheathing", "finishes", "general_notes"}
    for dk in dict_keys:
        parts = [b[dk] for b in blobs if dk in b and isinstance(b[dk], dict)]
        if parts:
            merged[dk] = merge_dicts_richest(*parts)

    for array_key, tag_key in TAGGED_ARRAYS:
        merged[array_key] = merge_tagged_arrays(blobs, array_key, tag_key)

    # Any other top-level keys (forward compatible)
    known = set(dict_keys) | {a for a, _ in TAGGED_ARRAYS} | {
        "_source_pdf",
        "_pages_analyzed",
        "_total_pages_in_file",
    }
    for b in blobs:
        for k, v in b.items():
            if k in known or k.startswith("_"):
                continue
            if k in merged:
                if isinstance(v, dict) and isinstance(merged[k], dict):
                    merged[k] = merge_dicts_richest(merged[k], v)
                elif isinstance(v, list) and isinstance(merged.get(k), list):
                    merged[k] = merge_list_concat_unique([merged[k], v])
                else:
                    merged[k] = max([merged[k], v], key=richness_score)
            else:
                merged[k] = v

    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge plan_analysis*.json into one profile.")
    parser.add_argument(
        "-d",
        "--outputs-dir",
        type=Path,
        default=_DEFAULT_OUTPUTS,
        help=f"Folder with plan_analysis*.json (default: {_DEFAULT_OUTPUTS})",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=_DEFAULT_OUT,
        help=f"Output file (default: {_DEFAULT_OUT})",
    )
    args = parser.parse_args()

    out_dir = args.outputs_dir.resolve()
    if not out_dir.is_dir():
        print(f"Error: not a directory: {out_dir}")
        raise SystemExit(1)

    blobs, sources = load_plan_blobs(out_dir)
    if not blobs:
        print(f"No plan_analysis*.json files found in {out_dir}")
        raise SystemExit(1)

    profile = merge_profiles(blobs)
    profile["_merge_meta"] = {
        "sources": sources,
        "merged_file_count": len(sources),
    }

    out_path = args.output
    if not out_path.is_absolute():
        out_path = (Path.cwd() / out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)

    print(f"Merged {len(sources)} file(s) → {out_path}")
    for s in sources:
        print(f"  - {s['file']}")


if __name__ == "__main__":
    main()
