"""
Shared SQLite store for CRM leads, bid outcomes (market intel), and GA-style sessions.
Database path: data/crm/ops.sqlite3 (created on first use).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
OPS_DB_PATH = (
    Path(os.environ["OPS_SQLITE_PATH"]).resolve()
    if os.environ.get("OPS_SQLITE_PATH")
    else _ROOT / "data" / "crm" / "ops.sqlite3"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id TEXT PRIMARY KEY,
    source TEXT,
    project_name TEXT,
    gc_name TEXT,
    gc_email TEXT,
    phone TEXT,
    state TEXT,
    zip TEXT,
    trades TEXT,
    est_sf REAL,
    stage TEXT NOT NULL DEFAULT 'new',
    notes TEXT,
    utm_source TEXT,
    utm_medium TEXT,
    utm_campaign TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bid_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id TEXT,
    trade TEXT,
    outcome TEXT NOT NULL,
    bid_amount REAL,
    building_sf REAL,
    dollars_per_sf REAL,
    close_reason TEXT,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (lead_id) REFERENCES leads(id)
);

CREATE TABLE IF NOT EXISTS analytics_ga_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    row_date TEXT,
    session_source TEXT,
    session_medium TEXT,
    session_campaign TEXT,
    sessions INTEGER,
    engaged_sessions INTEGER,
    conversions INTEGER,
    imported_at TEXT NOT NULL,
    source_file TEXT
);

CREATE INDEX IF NOT EXISTS idx_leads_stage ON leads(stage);
CREATE INDEX IF NOT EXISTS idx_outcomes_trade ON bid_outcomes(trade);
CREATE INDEX IF NOT EXISTS idx_outcomes_recorded ON bid_outcomes(recorded_at);
"""


def db_path() -> Path:
    return OPS_DB_PATH


def get_conn() -> sqlite3.Connection:
    OPS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(OPS_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}
