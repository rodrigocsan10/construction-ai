#!/usr/bin/env python3
"""
Construction AI — Streamlit UI (wrapper around existing CLI scripts).

Run from project root:
  streamlit run scripts/app.py
  # or: ./start.sh

Does not re-implement estimating logic — delegates to scripts via subprocess.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Paths (this file lives in scripts/)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
PROFILE_PATH = OUTPUTS_DIR / "plan_profile_complete.json"

TRADE_LABELS = [
    "Rough Framing & Sheathing",
    "Drywall & Insulation",
    "Ext. Windows & Doors",
]
TRADE_SLUG = {
    "Rough Framing & Sheathing": "framing",
    "Drywall & Insulation": "drywall",
    "Ext. Windows & Doors": "windows",
}
SLUG_TO_JSON = {
    "framing": ("takeoff_framing.json", "estimate_framing_priced.json"),
    "drywall": ("takeoff_drywall.json", "estimate_drywall_priced.json"),
    "windows": ("takeoff_windows_doors.json", "estimate_windows_doors_priced.json"),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def find_company_config_path() -> Path | None:
    matches = sorted(glob.glob(str(PROJECT_ROOT / "config" / "*company*.json")))
    if not matches:
        return None
    return Path(matches[0])


def load_company_config() -> dict[str, Any]:
    p = find_company_config_path()
    if not p or not p.is_file():
        return {"company_name": "Construction AI"}
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {"company_name": "Construction AI"}


def load_json_relpath(rel: str) -> Any | None:
    full = PROJECT_ROOT / rel
    if not full.is_file():
        return None
    with open(full, encoding="utf-8") as f:
        return json.load(f)


def save_json_relpath(data: Any, rel: str) -> None:
    full = PROJECT_ROOT / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def run_py_script(script_rel: str, *args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(PROJECT_ROOT / script_rel)] + [str(a) for a in args]
    return subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONUTF8": "1"},
    )


def company_display_name() -> str:
    c = load_company_config()
    return str(c.get("company_name") or "Construction AI")


def init_session_defaults() -> None:
    defaults: dict[str, Any] = {
        "ui_page": "Project Info",
        "workflow_status": "Project info",
        "client_name": "",
        "job_name": "",
        "job_address": "",
        "building_type": "Multifamily",
        "building_sf": 0,
        "floors": 1,
        "plans_ref": "",
        "quote_due": date.today(),
        "job_distance_one_way_mi": 30,
        "working_days": 60,
        "markup_pct": 11.0,
        "state_tax": "NJ (6.625%)",
        "tax_exempt": False,
        "trades_selected": list(TRADE_LABELS),
        "ceiling_sf": 0.0,
        "analyze_max_pages": 0,
        "plan_profile": None,
        "pricing_by_slug": {},
        "grand_total_trades": 0.0,
        "proposal_generated": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v
    for slug in ("framing", "drywall"):
        key = f"bid_mode_{slug}"
        if key not in st.session_state:
            st.session_state[key] = "Material & Labor"


def tax_pct_from_state() -> float:
    if st.session_state.get("tax_exempt"):
        return 0.0
    stt = st.session_state.get("state_tax", "NJ (6.625%)")
    return 6.625 if "NJ" in stt else 6.0


def round_trip_miles() -> float:
    return float(st.session_state.get("job_distance_one_way_mi", 0) or 0) * 2.0


def profile_loaded() -> dict[str, Any] | None:
    if st.session_state.get("plan_profile"):
        return st.session_state["plan_profile"]
    data = load_json_relpath("outputs/plan_profile_complete.json")
    if isinstance(data, dict):
        st.session_state["plan_profile"] = data
        return data
    return None


def wall_types_fire_rows(wall_types: list[Any]) -> list[dict[str, Any]]:
    out = []
    for w in wall_types:
        if not isinstance(w, dict):
            continue
        fr = w.get("fire_rated")
        if isinstance(fr, dict) and fr.get("rated"):
            out.append(
                {
                    "tag": w.get("tag", ""),
                    "fire_rating": fr.get("rating") or fr.get("label") or "rated",
                }
            )
        elif w.get("fire_rating"):
            out.append({"tag": w.get("tag", ""), "fire_rating": w.get("fire_rating")})
    return out


def takeoff_path_for_slug(slug: str) -> Path:
    name, _ = SLUG_TO_JSON[slug]
    return OUTPUTS_DIR / name


def priced_path_for_slug(slug: str) -> Path:
    _, name = SLUG_TO_JSON[slug]
    return OUTPUTS_DIR / name


def trade_labels_to_slugs(labels: list[str]) -> list[str]:
    return [TRADE_SLUG[t] for t in labels if t in TRADE_SLUG]


def framing_labor_only() -> bool:
    return st.session_state.get("bid_mode_framing") == "Labor Only"


def takeoff_summary_for_slug(slug: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return (detail_df, metrics dict)."""
    path = takeoff_path_for_slug(slug)
    if not path.is_file():
        return pd.DataFrame(), {"rows": 0, "note": "Run takeoff first."}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return pd.DataFrame(), {}

    if slug == "framing":
        rows = data.get("wall_type_takeoff") or []
        df = pd.json_normalize(rows) if rows else pd.DataFrame()
        sup = data.get("supplier_list") or []
        metrics = {
            "rows": len(df),
            "supplier_lines": len(sup),
            "note": "Wall-type takeoff rows; supplier list in JSON/CSV/XLSX.",
        }
        return df, metrics

    if slug == "drywall":
        rows = data.get("wall_rows") or []
        df = pd.json_normalize(rows) if rows else pd.DataFrame()
        return df, {"rows": len(df), "note": "Per-wall GWB / insulation quantities."}

    if slug == "windows":
        doors = data.get("doors") or data.get("door_schedule") or []
        wins = data.get("windows") or data.get("window_schedule") or []
        if not doors and not wins:
            # Some profiles nest differently — flatten top-level lists
            df = pd.DataFrame()
            metrics = {"rows": 0, "note": "Open takeoff JSON for schedule detail."}
            return df, metrics
        dfd = pd.json_normalize(doors) if doors else pd.DataFrame()
        dfw = pd.json_normalize(wins) if wins else pd.DataFrame()
        df = pd.concat([dfd, dfw], ignore_index=True) if not dfd.empty or not dfw.empty else pd.DataFrame()
        return df, {"rows": len(df), "note": "Door/window lines from profile takeoff."}

    return pd.DataFrame(), {}


def pricing_grand_from_json(slug: str, data: dict[str, Any]) -> float:
    pr = data.get("pricing") or {}
    if slug == "framing":
        return float(pr.get("grand_total_client") or 0.0)
    su = pr.get("summary_usd") or {}
    return float(su.get("grand_total") or 0.0)


def pricing_lines_dataframe(slug: str, data: dict[str, Any]) -> pd.DataFrame:
    pr = data.get("pricing") or {}
    if slug == "framing":
        lines = pr.get("priced_supplier_lines") or []
        if lines:
            return pd.json_normalize(lines)
        return pd.DataFrame([{"line": "See estimate_framing_priced.json", "note": "grand_total_client in pricing"}])
    if slug == "drywall":
        tbl = pr.get("summary_table") or []
        return pd.DataFrame(tbl) if tbl else pd.DataFrame()
    if slug == "windows":
        items = pr.get("line_items") or []
        return pd.json_normalize(items) if items else pd.DataFrame()
    return pd.DataFrame()


def mobilization_framing_usd(data: dict[str, Any] | None) -> float:
    if not data:
        return 0.0
    pr = data.get("pricing") or {}
    try:
        return float(pr.get("mobilization") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def assemble_proposal_input() -> dict[str, Any]:
    """Build JSON for build_proposal_pdf.py (client lump-sum)."""
    co = load_company_config()
    name = str(co.get("company_name") or "Contractor")
    job = st.session_state.get("job_name") or "Project"
    client = st.session_state.get("client_name") or ""
    lump = float(st.session_state.get("grand_total_trades") or 0.0)
    state = st.session_state.get("state_tax", "NJ (6.625%)")
    juris = "NJ" if "NJ" in state else "PA"

    line_items = []
    for label in st.session_state.get("trades_selected") or []:
        slug = TRADE_SLUG.get(label)
        if not slug:
            continue
        p = st.session_state.get("pricing_by_slug", {}).get(slug)
        if p is not None:
            line_items.append({"label": label, "amount": round(float(p), 2)})

    return {
        "meta": {
            "document_title": f"Proposal — {job}",
            "validity_days": int(st.session_state.get("proposal_valid_days") or 30),
            "bid_mode": "lump_sum",
            "confidentiality": "client",
        },
        "company": {
            "name": name,
            "address": str(co.get("address") or co.get("office_address") or ""),
            "phone": str(co.get("phone") or ""),
            "email": str(co.get("email") or co.get("estimating_email") or ""),
            "logo_path": str(co.get("logo_path") or ""),
        },
        "project": {
            "name": job,
            "owner": client,
            "gc": client,
        },
        "scope_paragraphs": [
            f"Plans referenced: {st.session_state.get('plans_ref') or 'See bid documents attached or incorporated by reference.'}",
            f"Building type: {st.session_state.get('building_type')}; approximate {st.session_state.get('building_sf') or '—'} SF.",
            "Open-shop framing, drywall & insulation, and exterior window/door installation (labor only for openings) per selected trades — verify against contract documents.",
        ],
        "investment": {"lump_sum": round(lump, 2), "line_items": line_items},
        "payment_schedule": [
            {"label": "Contract execution / deposit", "pct": 10, "client_visible": True},
            {"label": "Mobilization & material deposit", "pct": 25, "client_visible": True},
            {"label": "Rough-in milestone", "pct": 25, "client_visible": True},
            {"label": "Dry-in / sheathing complete", "pct": 15, "client_visible": True},
            {"label": "Progress — interior partitions", "pct": 10, "client_visible": True},
            {"label": "Punch & closeout reserve", "pct": 5, "client_visible": True},
            {"label": "Final upon substantial completion", "pct": 10, "client_visible": True},
        ],
        "tax": {"jurisdiction": juris},
        "assumptions": [
            "Tax treatment per jurisdiction note; valid exemption certificates required before exempt invoicing.",
            "Quote valid for the stated term; escalation after expiration unless extended in writing.",
        ],
        "confidential_sections": {"internal_notes": []},
    }


def crm_ensure_db() -> None:
    from ops_db import init_db  # noqa: WPS433

    init_db()


def crm_list_leads_df() -> pd.DataFrame:
    from ops_db import get_conn  # noqa: WPS433

    crm_ensure_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, project_name, gc_name, gc_email, stage, est_sf, source, updated_at FROM leads ORDER BY updated_at DESC"
        ).fetchall()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in rows])


def crm_add_lead(
    *,
    project_name: str,
    gc_name: str,
    est_value: float,
    stage: str,
) -> str:
    from ops_db import get_conn  # noqa: WPS433

    crm_ensure_db()
    lid = uuid.uuid4().hex[:12]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    notes = f"Estimated value (UI): ${est_value:,.0f}" if est_value else ""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO leads (id, source, project_name, gc_name, gc_email, phone, state, zip, trades, est_sf, stage, notes, utm_source, utm_medium, utm_campaign, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                lid,
                "streamlit_ui",
                project_name,
                gc_name,
                "",
                "",
                "",
                "",
                "",
                float(est_value) if est_value else None,
                stage,
                notes,
                "",
                "",
                "",
                ts,
                ts,
            ),
        )
        conn.commit()
    return lid


def market_outcomes_df() -> pd.DataFrame:
    from ops_db import get_conn  # noqa: WPS433

    crm_ensure_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT outcome, trade, bid_amount, building_sf, dollars_per_sf, recorded_at FROM bid_outcomes ORDER BY recorded_at DESC LIMIT 200"
        ).fetchall()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in rows])


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
def sidebar() -> None:
    co_name = company_display_name()
    st.sidebar.markdown(f"### {co_name}")
    st.sidebar.caption("Takeoff & Estimating Tool")
    st.sidebar.divider()
    _pages = [
        "Project Info",
        "Plan Analysis",
        "Trade Takeoff",
        "Pricing Engine",
        "Proposal & Outputs",
        "CRM & Pipeline",
    ]
    _cur = st.session_state.get("ui_page", "Project Info")
    _idx = _pages.index(_cur) if _cur in _pages else 0
    page = st.sidebar.radio("Navigation", _pages, index=_idx)
    st.session_state["ui_page"] = page
    st.sidebar.divider()
    st.sidebar.markdown(f"**Active project:** {st.session_state.get('job_name') or '—'}")
    st.sidebar.markdown(f"**Status:** {st.session_state.get('workflow_status', '—')}")


def page_project_info() -> None:
    st.header("Project Information")
    c1, c2 = st.columns(2)
    with c1:
        st.session_state["client_name"] = st.text_input(
            "Client / GC Name",
            value=st.session_state["client_name"],
            placeholder="ABC Development Group",
        )
        st.session_state["job_name"] = st.text_input(
            "Job Name",
            value=st.session_state["job_name"],
            placeholder="MT. Arlington Building 2",
        )
        st.session_state["job_address"] = st.text_input(
            "Job Address",
            value=st.session_state["job_address"],
            placeholder="123 Main St, Mt. Arlington, NJ 07856",
        )
    with c2:
        st.session_state["building_type"] = st.selectbox(
            "Building Type",
            ["Multifamily", "Commercial", "Custom Residential"],
            index=["Multifamily", "Commercial", "Custom Residential"].index(
                st.session_state["building_type"]
            ),
        )
        st.session_state["building_sf"] = int(
            st.number_input(
                "Total Building SF",
                min_value=0,
                step=500,
                value=int(st.session_state["building_sf"] or 0),
            )
        )
        st.session_state["floors"] = int(
            st.number_input(
                "Number of Floors",
                min_value=1,
                max_value=20,
                value=int(st.session_state["floors"] or 1),
            )
        )

    st.divider()
    st.session_state["plans_ref"] = st.text_input(
        "Plans referenced",
        value=st.session_state["plans_ref"],
        placeholder="Arch A2.1–A2.9, Struct S1–S4, dated 02/15/2026",
    )
    st.session_state["quote_due"] = st.date_input("Quote due date", value=st.session_state["quote_due"])

    st.divider()
    c3, c4, c5 = st.columns(3)
    with c3:
        st.session_state["job_distance_one_way_mi"] = int(
            st.number_input(
                "Distance from 08075 (one-way miles)",
                min_value=1,
                max_value=100,
                value=int(st.session_state["job_distance_one_way_mi"]),
            )
        )
    with c4:
        st.session_state["working_days"] = int(
            st.number_input(
                "Estimated working days",
                min_value=5,
                max_value=300,
                value=int(st.session_state["working_days"]),
            )
        )
    with c5:
        st.session_state["markup_pct"] = float(
            st.slider(
                "Material markup %",
                min_value=10.0,
                max_value=12.0,
                value=float(st.session_state["markup_pct"]),
                step=0.5,
            )
        )

    tx1, tx2 = st.columns(2)
    with tx1:
        opts = ["NJ (6.625%)", "PA (6%)"]
        idx = opts.index(st.session_state["state_tax"]) if st.session_state["state_tax"] in opts else 0
        st.session_state["state_tax"] = st.selectbox("Job state (sales tax)", opts, index=idx)
    with tx2:
        st.session_state["tax_exempt"] = st.checkbox(
            "Tax exempt (ST-8 / ST-5 on file)",
            value=st.session_state["tax_exempt"],
        )

    st.subheader("Trades to include")
    st.session_state["trades_selected"] = st.multiselect(
        "Select trades for this bid",
        TRADE_LABELS,
        default=st.session_state["trades_selected"],
    )

    for label in st.session_state["trades_selected"]:
        slug = TRADE_SLUG[label]
        if label == "Ext. Windows & Doors":
            st.info(f"{label} — labor only (client furnishes materials).")
        else:
            st.selectbox(
                f"{label} — bid mode",
                ["Material & Labor", "Labor Only"],
                key=f"bid_mode_{slug}",
            )

    st.session_state["ceiling_sf"] = float(
        st.number_input(
            "Drywall ceiling SF (optional, 0 = profile/default)",
            min_value=0.0,
            value=float(st.session_state.get("ceiling_sf") or 0.0),
        )
    )

    if st.button("Apply project info to merged profile JSON", help="Updates outputs/plan_profile_complete.json project fields when file exists."):
        if not PROFILE_PATH.is_file():
            st.warning("No plan_profile_complete.json yet — run Plan Analysis first.")
        else:
            prof = load_json_relpath("outputs/plan_profile_complete.json")
            if isinstance(prof, dict):
                proj = prof.get("project") if isinstance(prof.get("project"), dict) else {}
                proj["name"] = st.session_state["job_name"] or proj.get("name", "")
                proj["total_sf"] = int(st.session_state["building_sf"] or 0)
                proj["floors"] = int(st.session_state["floors"] or 1)
                bt = st.session_state["building_type"].lower().replace(" ", "_")
                if "multifamily" in bt:
                    proj["type"] = "multifamily"
                elif "commercial" in bt:
                    proj["type"] = "commercial"
                else:
                    proj["type"] = "residential"
                prof["project"] = proj
                save_json_relpath(prof, "outputs/plan_profile_complete.json")
                st.session_state["plan_profile"] = prof
                st.success("Updated plan_profile_complete.json project block.")
                st.session_state["workflow_status"] = "Profile patched from Project Info"

    ok = bool(st.session_state.get("job_name")) and bool(st.session_state.get("client_name"))
    ok = ok and int(st.session_state.get("building_sf") or 0) > 0
    if ok:
        st.success("Project info complete — ready for Plan Analysis.")
        st.session_state["workflow_status"] = "Ready for plan analysis"
    else:
        st.warning("Enter client name, job name, and building SF > 0 before relying on downstream steps.")


def page_plan_analysis() -> None:
    st.header("Plan Analysis")
    st.session_state["analyze_max_pages"] = int(
        st.number_input(
            "Max PDF pages to send (0 = full file — may hit API limits on large sets)",
            min_value=0,
            value=int(st.session_state.get("analyze_max_pages") or 0),
        )
    )

    up = st.file_uploader("Upload construction plans (PDF)", type=["pdf"])
    if up is not None:
        safe = Path(up.name).name.replace(os.sep, "_")
        if not safe.lower().endswith(".pdf"):
            safe += ".pdf"
        dest = DATA_DIR / safe
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(up.getvalue())
        st.success(f"Saved upload to data/{safe}")

        if st.button("Analyze plans", type="primary"):
            st.session_state["workflow_status"] = "Analyzing plans…"
            with st.spinner("Calling OpenAI — may take a few minutes…"):
                args = ["scripts/analyze_plans.py", str(dest.relative_to(PROJECT_ROOT)), "-o", "outputs/plan_analysis.json"]
                mx = int(st.session_state.get("analyze_max_pages") or 0)
                if mx > 0:
                    args.extend(["--max-pages", str(mx)])
                r1 = run_py_script(*args)
                if r1.returncode != 0:
                    st.error(f"analyze_plans failed:\n{r1.stderr or r1.stdout}")
                    st.session_state["workflow_status"] = "Plan analysis failed"
                    return
                r2 = run_py_script("scripts/merge_profiles.py", "-o", "outputs/plan_profile_complete.json")
                if r2.returncode != 0:
                    st.error(f"merge_profiles failed:\n{r2.stderr or r2.stdout}")
                    st.session_state["workflow_status"] = "Merge failed"
                    return
            prof = load_json_relpath("outputs/plan_profile_complete.json")
            if isinstance(prof, dict):
                st.session_state["plan_profile"] = prof
            st.success("Plan analysis and merge complete.")
            st.session_state["workflow_status"] = "Plan profile ready"

    prof = profile_loaded()
    if prof:
        proj = prof.get("project") or {}
        wt = prof.get("wall_types") or []
        if not isinstance(wt, list):
            wt = []
        c1, c2, c3 = st.columns(3)
        tsf = proj.get("total_sf", "—")
        c1.metric(
            "Building SF (profile)",
            f"{tsf:,}" if isinstance(tsf, (int, float)) else str(tsf),
        )
        c2.metric("Floors", proj.get("floors", "—"))
        c3.metric("Wall types", len(wt))

        st.subheader("Wall types")
        if wt:
            st.dataframe(pd.json_normalize(wt), use_container_width=True, hide_index=True)
        else:
            st.info("No wall_types array in profile.")

        fired = wall_types_fire_rows(wt)
        if fired:
            st.warning(f"{len(fired)} fire-rated wall types — verify drywall layers and rated assemblies.")
            for fw in fired[:40]:
                st.write(f" • {fw.get('tag')}: {fw.get('fire_rating')}")

        with st.expander("Edit plan profile (wall types table)"):
            if wt:
                df = pd.DataFrame(wt)
                edited = st.data_editor(df, num_rows="dynamic", use_container_width=True)
                if st.button("Save wall types to plan_profile_complete.json"):
                    prof["wall_types"] = edited.to_dict(orient="records")
                    save_json_relpath(prof, "outputs/plan_profile_complete.json")
                    st.session_state["plan_profile"] = prof
                    st.success("Saved.")
            else:
                st.caption("Nothing to edit yet.")


def page_trade_takeoff() -> None:
    st.header("Trade takeoff")
    if not PROFILE_PATH.is_file():
        st.warning("Run Plan Analysis first (or place outputs/plan_profile_complete.json).")
        return

    labels = st.session_state.get("trades_selected") or []
    if not labels:
        st.warning("Select at least one trade on Project Info.")
        return

    lf_up = st.file_uploader("Optional: wall LF override JSON (framing)", type=["json"])
    lf_path_arg: str | None = None
    if lf_up is not None:
        p = OUTPUTS_DIR / "ui_lf_override.json"
        p.write_bytes(lf_up.getvalue())
        lf_path_arg = str(p.relative_to(PROJECT_ROOT))

    tabs = st.tabs(labels)
    for i, label in enumerate(labels):
        slug = TRADE_SLUG[label]
        with tabs[i]:
            st.subheader(label)
            if st.button(f"Run {label} takeoff", key=f"btn_takeoff_{slug}"):
                with st.spinner("Running takeoff…"):
                    if slug == "framing":
                        args = ["scripts/takeoff_framing.py"]
                        if lf_path_arg:
                            args += ["--lf-json", lf_path_arg]
                        r = run_py_script(*args)
                    elif slug == "drywall":
                        args = ["scripts/takeoff_drywall.py"]
                        csf = float(st.session_state.get("ceiling_sf") or 0)
                        if csf > 0:
                            args += ["--ceiling-sf", str(csf)]
                        r = run_py_script(*args)
                    else:
                        r = run_py_script("scripts/takeoff_windows_doors.py")
                    if r.returncode != 0:
                        st.error(r.stderr or r.stdout)
                    else:
                        st.success("Takeoff finished.")
                        st.session_state["workflow_status"] = f"Takeoff done: {slug}"
                        st.session_state[f"takeoff_ran_{slug}"] = True

            df, meta = takeoff_summary_for_slug(slug)
            st.caption(meta.get("note", ""))
            if not df.empty:
                st.dataframe(df, use_container_width=True, hide_index=True)
            path = takeoff_path_for_slug(slug)
            if path.is_file():
                st.download_button(
                    f"Download {path.name}",
                    data=path.read_bytes(),
                    file_name=path.name,
                    mime="application/json",
                    key=f"dl_takeoff_{slug}",
                )


def page_pricing() -> None:
    st.header("Pricing engine")
    labels = st.session_state.get("trades_selected") or []
    slugs = trade_labels_to_slugs(labels)
    missing = [s for s in slugs if not takeoff_path_for_slug(s).is_file()]
    if missing:
        st.warning(f"Run takeoffs first. Missing: {', '.join(missing)}")
        return

    with st.expander("Pricing parameters", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            mk = st.slider(
                "Material markup %",
                10.0,
                12.0,
                float(st.session_state.get("markup_pct", 11.0)),
                0.5,
                key="pricing_markup_slider",
            )
        with c2:
            owm = st.number_input(
                "One-way distance (mi)",
                min_value=1,
                max_value=100,
                value=int(st.session_state.get("job_distance_one_way_mi", 30)),
                key="pricing_distance",
            )
        with c3:
            wd = st.number_input(
                "Working days",
                min_value=5,
                max_value=300,
                value=int(st.session_state.get("working_days", 60)),
                key="pricing_wd",
            )
        with c4:
            tr = tax_pct_from_state()
            st.metric("Tax % (materials / models)", f"{tr:.3f}%" if tr > 0 else "EXEMPT")

        inc_block = st.checkbox("Framing: include blockout crew", value=False)
        eq_mo = st.number_input("Framing: equipment months", min_value=0.0, max_value=24.0, value=0.0)
        dv_carry = st.checkbox("Drywall: vertical carry charge", value=False)
        st.session_state["drywall_finish_pricing"] = int(
            st.number_input(
                "Drywall finish level (0–5)",
                min_value=0,
                max_value=5,
                value=int(st.session_state.get("drywall_finish_pricing", 4)),
            )
        )

    rt = float(owm) * 2.0
    bsf = float(st.session_state.get("building_sf") or 0)

    if st.button("Calculate pricing", type="primary"):
        st.session_state["workflow_status"] = "Pricing…"
        tax_args: list[str] = []
        if st.session_state.get("tax_exempt"):
            tax_args.append("--tax-exempt")
        else:
            tax_args.extend(["--tax-pct", str(tr)])

        errs = []
        for slug in slugs:
            if slug == "framing":
                cmd = [
                    "scripts/price_framing.py",
                    "--round-trip-miles",
                    str(rt),
                    "--working-days",
                    str(int(wd)),
                    *tax_args,
                    "--markup-pct",
                    str(mk),
                ]
                if bsf > 0:
                    cmd += ["--building-sf", str(bsf)]
                if framing_labor_only():
                    cmd.append("--labor-only-scope")
                if inc_block:
                    cmd.append("--include-blockout")
                if eq_mo > 0:
                    cmd += ["--equipment-months", str(eq_mo)]
                r = run_py_script(*cmd)
            elif slug == "drywall":
                fl = int(st.session_state.get("drywall_finish_pricing", 4))
                cmd = [
                    "scripts/price_drywall.py",
                    *tax_args,
                    "--markup-pct",
                    str(mk),
                    "--finish-level",
                    str(fl),
                ]
                if dv_carry:
                    cmd.append("--vertical-carry")
                r = run_py_script(*cmd)
            else:
                cmd = ["scripts/price_windows_doors.py", "--markup-pct", str(mk)]
                r = run_py_script(*cmd)
            if r.returncode != 0:
                errs.append(f"{slug}: {r.stderr or r.stdout}")

        if errs:
            st.error("\n\n".join(errs))
            st.session_state["workflow_status"] = "Pricing failed"
            return

        by_slug: dict[str, float] = {}
        frames: dict[str, pd.DataFrame] = {}
        for slug in slugs:
            pth = priced_path_for_slug(slug)
            raw = json.loads(pth.read_text(encoding="utf-8")) if pth.is_file() else {}
            tot = pricing_grand_from_json(slug, raw) if isinstance(raw, dict) else 0.0
            by_slug[slug] = tot
            frames[slug] = pricing_lines_dataframe(slug, raw) if isinstance(raw, dict) else pd.DataFrame()

        st.session_state["pricing_by_slug"] = by_slug
        st.session_state["pricing_lines_by_slug"] = frames
        st.session_state["grand_total_trades"] = sum(by_slug.values())
        # Reference mobilization from framing only (already inside framing total)
        fr = load_json_relpath("outputs/estimate_framing_priced.json")
        st.session_state["mobilization_framing_only"] = mobilization_framing_usd(
            fr if isinstance(fr, dict) else None
        )
        st.session_state["workflow_status"] = "Priced"
        st.success("Pricing complete.")

    if st.session_state.get("pricing_by_slug"):
        gt = float(st.session_state.get("grand_total_trades") or 0)
        st.metric("Grand total (sum of trade client totals)", f"${gt:,.2f}")
        sf = max(float(st.session_state.get("building_sf") or 0), 1.0)
        st.caption(f"≈ ${gt / sf:,.2f} / building SF (approximate)")
        mob = float(st.session_state.get("mobilization_framing_only") or 0)
        if mob > 0:
            st.caption(f"Framing line item includes mobilization ≈ ${mob:,.2f} (not added again to grand total).")

        slug_to_label = {TRADE_SLUG[lb]: lb for lb in st.session_state.get("trades_selected") or []}
        cols = st.columns(max(len(slugs), 1))
        for i, slug in enumerate(slugs):
            with cols[i % len(cols)]:
                st.metric(
                    slug_to_label.get(slug, slug),
                    f"${st.session_state['pricing_by_slug'].get(slug, 0):,.2f}",
                )

        with st.expander("Full cost breakdown (internal)"):
            for slug in slugs:
                st.subheader(slug)
                df = st.session_state.get("pricing_lines_by_slug", {}).get(slug)
                if df is not None and not df.empty:
                    st.dataframe(df, use_container_width=True, hide_index=True)
                else:
                    st.caption("Open priced JSON for detail.")
        st.info("Internal view — client PDF uses lump-sum proposal mode without unit-cost tables.")


def page_proposal() -> None:
    st.header("Proposal & outputs")
    if not st.session_state.get("pricing_by_slug"):
        st.warning("Run Pricing engine first.")
        return

    c1, c2 = st.columns(2)
    with c1:
        st.session_state["proposal_valid_days"] = int(
            st.number_input("Proposal valid (days)", min_value=7, max_value=90, value=30)
        )
    with c2:
        gen_supplier = st.checkbox("Generate supplier RFQ email body", value=True)
        gen_md = st.checkbox("Generate Markdown proposal draft", value=True)

    proposal_pdf = OUTPUTS_DIR / "proposal_ui_client.pdf"

    if st.button("Generate outputs", type="primary"):
        with st.spinner("Writing proposal JSON and running scripts…"):
            payload = assemble_proposal_input()
            save_json_relpath(payload, "outputs/proposal_ui_input.json")
            r = run_py_script(
                "scripts/build_proposal_pdf.py",
                "--input",
                "outputs/proposal_ui_input.json",
                "--output",
                "outputs/proposal_ui_client.pdf",
                "--strict",
            )
            if r.returncode != 0:
                st.error(r.stderr or r.stdout)
            else:
                st.success("Branded proposal PDF built.")
            if gen_md:
                run_py_script("scripts/generate_proposal.py", "-o", "outputs/proposal_ui_draft.md")
            if gen_supplier and takeoff_path_for_slug("framing").is_file():
                run_py_script(
                    "scripts/supplier_email.py",
                    "-o",
                    "outputs/supplier_email_ui.txt",
                )
        st.session_state["proposal_generated"] = True
        st.session_state["workflow_status"] = "Outputs generated"

    st.subheader("Download")
    dc1, dc2 = st.columns(2)
    with dc1:
        st.markdown("**Client-facing**")
        if proposal_pdf.is_file():
            st.download_button(
                "Client proposal (PDF)",
                data=proposal_pdf.read_bytes(),
                file_name=f"Proposal_{st.session_state.get('job_name') or 'project'}.pdf",
                mime="application/pdf",
            )
    with dc2:
        st.markdown("**Internal priced workbooks**")
        for slug in trade_labels_to_slugs(st.session_state.get("trades_selected") or []):
            xlsx = priced_path_for_slug(slug).with_suffix(".xlsx")
            if xlsx.is_file():
                st.download_button(
                    f"{xlsx.name}",
                    data=xlsx.read_bytes(),
                    file_name=xlsx.name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"dl_xlsx_{slug}",
                )

    st.divider()
    st.markdown("**Supplier**")
    sup_txt = OUTPUTS_DIR / "supplier_email_ui.txt"
    legacy = OUTPUTS_DIR / "supplier_email_framing.txt"
    p = sup_txt if sup_txt.is_file() else legacy
    if p.is_file():
        st.text_area("Supplier RFQ email (copy/paste)", p.read_text(encoding="utf-8"), height=220)
        st.download_button("Download supplier email text", p.read_bytes(), file_name=p.name, mime="text/plain")

    md_path = OUTPUTS_DIR / "proposal_ui_draft.md"
    if md_path.is_file():
        with st.expander("Markdown proposal preview"):
            st.markdown(md_path.read_text(encoding="utf-8"))


def page_crm() -> None:
    st.header("CRM & pipeline")
    t1, t2, t3 = st.tabs(["Active bids", "Add lead", "Win / loss"])

    with t1:
        df = crm_list_leads_df()
        if df.empty:
            st.info("No leads in SQLite yet — add one or use scripts/crm_cli.py / lead_pipeline.py.")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)

    with t2:
        lc = st.text_input("GC / client name", key="crm_gc")
        lj = st.text_input("Job / project name", key="crm_job")
        lv = st.number_input("Estimated value ($)", min_value=0.0, value=0.0, key="crm_val")
        st_sel = st.selectbox(
            "Stage",
            ["new", "qualified", "quoted", "negotiating", "won", "lost"],
            index=0,
        )
        if st.button("Add to CRM"):
            if not lj.strip():
                st.error("Job name required.")
            else:
                lid = crm_add_lead(project_name=lj.strip(), gc_name=lc.strip(), est_value=lv, stage=st_sel)
                st.success(f"Added lead id {lid}")

    with t3:
        od = market_outcomes_df()
        if od.empty:
            st.caption("No outcomes yet — use scripts/market_intel.py record or add from CLI.")
        else:
            st.dataframe(od, use_container_width=True, hide_index=True)
            bc = od.groupby("outcome").size()
            if not bc.empty:
                st.bar_chart(bc)


def main() -> None:
    st.set_page_config(page_title=company_display_name() + " — Estimating", layout="wide")
    init_session_defaults()
    sidebar()
    page = st.session_state["ui_page"]
    if page == "Project Info":
        page_project_info()
    elif page == "Plan Analysis":
        page_plan_analysis()
    elif page == "Trade Takeoff":
        page_trade_takeoff()
    elif page == "Pricing Engine":
        page_pricing()
    elif page == "Proposal & Outputs":
        page_proposal()
    else:
        page_crm()


if __name__ == "__main__":
    main()
