#!/usr/bin/env python3
"""
Smoke-test lead pipeline, CRM, market intel, email drafts, bid package (no SMTP).

Uses a temporary SQLite DB (OPS_SQLITE_PATH) so your real data/crm/ops.sqlite3 is untouched.

Run from repo root:
  python scripts/run_ops_demo.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
SCR = _ROOT / "scripts"


def run(cmd: list[str], env: dict[str, str]) -> None:
    print("+", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=str(_ROOT), env=env)
    if r.returncode != 0:
        raise SystemExit(r.returncode)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="construction_ai_ops_") as tmp:
        db_path = Path(tmp) / "ops.sqlite3"
        env = os.environ.copy()
        env["OPS_SQLITE_PATH"] = str(db_path)

        run([PY, str(SCR / "crm_cli.py"), "init"], env)
        run(
            [
                PY,
                str(SCR / "lead_pipeline.py"),
                "--config",
                str(_ROOT / "config" / "lead_pipeline.example.json"),
                "import",
                str(_ROOT / "config" / "examples" / "planhub_export_sample.csv"),
                "--to-crm",
            ],
            env,
        )
        run([PY, str(SCR / "crm_cli.py"), "list"], env)

        import sqlite3

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT id FROM leads ORDER BY created_at LIMIT 1").fetchone()
        conn.close()
        if not row:
            raise SystemExit("No leads after import")
        lid = row["id"]
        print(f"Demo lead id: {lid}", flush=True)

        run(
            [
                PY,
                str(SCR / "render_outbound_email.py"),
                "-t",
                str(_ROOT / "config" / "email_templates" / "introduction.txt"),
                "-l",
                lid,
                "--print",
            ],
            env,
        )

        drafts = Path(tmp) / "email_drafts"
        run(
            [
                PY,
                str(SCR / "email_sequence.py"),
                "-l",
                lid,
                "-c",
                str(_ROOT / "config" / "email_sequence.example.json"),
                "--out-dir",
                str(drafts),
            ],
            env,
        )

        run(
            [
                PY,
                str(SCR / "market_intel.py"),
                "record",
                "--outcome",
                "won",
                "--trade",
                "framing",
                "--amount",
                "709000",
                "--sf",
                "121000",
                "--lead-id",
                lid,
            ],
            env,
        )
        run([PY, str(SCR / "market_intel.py"), "report", "--trade", "framing"], env)

        pdf = _ROOT / "outputs" / "proposal_test_A_lump_client.pdf"
        if not pdf.is_file():
            run([PY, str(SCR / "run_proposal_pdf_tests.py")], os.environ.copy())

        pkg_root = _ROOT / "outputs" / "bid_packages_demo"
        pkg_dir = pkg_root / "demo_job"
        if pkg_dir.exists():
            shutil.rmtree(pkg_dir)
        run(
            [
                PY,
                str(SCR / "bid_package.py"),
                "--name",
                "demo_job",
                "--pdf",
                str(pdf),
                "--proposal-json",
                str(_ROOT / "config" / "proposal_examples" / "scenario_a_lump_sum_client.json"),
                "--out-dir",
                str(pkg_root),
            ],
            os.environ.copy(),
        )

        run([PY, str(SCR / "crm_webhook.py"), "--lead-id", lid, "--dry-run"], env)

    print("\nOK — ops demo complete (temporary CRM DB discarded). Bid package: outputs/bid_packages_demo/demo_job/")


if __name__ == "__main__":
    main()
