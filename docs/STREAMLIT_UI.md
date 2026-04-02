# Streamlit web UI

New files only: `scripts/app.py`, `start_streamlit.sh`, and this doc. Your existing `start.sh` and `.streamlit/config.toml` are unchanged.

## Install

`streamlit` is already listed in `requirements.txt`. If needed:

```bash
pip install streamlit>=1.30.0
```

## Run

From the project root:

```bash
streamlit run scripts/app.py
```

Or:

```bash
chmod +x start_streamlit.sh   # once
./start_streamlit.sh
```

The app wraps the same CLI scripts (`analyze_plans.py`, `merge_profiles.py`, takeoffs, pricers, `build_proposal_pdf.py`, `generate_proposal.py`, `supplier_email.py`) via subprocess. Outputs include:

- `outputs/proposal_ui_client.pdf` — branded client proposal
- `outputs/proposal_ui_input.json` — input used for that PDF
- `outputs/proposal_ui_draft.md` — optional markdown draft
- `outputs/supplier_email_ui.txt` — optional supplier RFQ body

CRM tab uses `scripts/ops_db.py` (same SQLite as `crm_cli.py`).
