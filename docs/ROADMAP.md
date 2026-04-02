# Product roadmap (integrations & automation)

Engineering estimates and `README.md` cover **what runs today**. This file tracks **gaps** between the local scaffold and full SaaS-style automation.

## Implemented (scaffold — local / CSV / SMTP)

- [x] **SMTP outbound** — `scripts/email_proposal.py`, `scripts/render_outbound_email.py` (`smtp_util.py`; configure `.env` per `config/integrations.example.json`).
- [x] **Local CRM** — SQLite `data/crm/ops.sqlite3` via `scripts/crm_cli.py` (optional `OPS_SQLITE_PATH` for tests).
- [x] **Lead pipeline** — `scripts/lead_pipeline.py` imports vendor CSV with column map + filters (`config/lead_pipeline.example.json`).
- [x] **Market intel** — `scripts/market_intel.py` records outcomes and rolls up $/SF.
- [x] **Web analytics import** — `scripts/analytics_ingest.py ga-csv` for GA4 exports; UTM fields on leads.
- [x] **Bid package folder** — `scripts/bid_package.py` after `build_proposal_pdf.py`.
- [x] **Webhook** — `scripts/crm_webhook.py` POSTs lead JSON when `CRM_WEBHOOK_URL` is set.
- [x] **Demo driver** — `scripts/run_ops_demo.py`.

## Still manual or future

- [ ] **Vendor API** — PlanHub (or other) live pull; store keys in env; retries and idempotency.
- [ ] **Scheduled jobs** — cron / launchd for CSV download, ingest, or reminder sends.
- [ ] **Bi-directional CRM** — sync stages from HubSpot/Airtable back into SQLite (or migrate off SQLite).
- [ ] **Open/click tracking** — only if you add a provider or self-hosted pixel (not in repo).

## Security

- API keys and SMTP passwords: **environment variables** or host secret manager — not committed JSON with real values.
