# Construction AI — plan takeoff & estimates

End-to-end flow: **plan analysis → merged profile → framing / drywall / windows takeoffs → priced JSON + XLSX**. Business rules live in `outputs/KNOWLEDGE_BASE.md/KNOWLEDGE_BASE.md` (copy in-repo).

## Setup

```bash
cd construction-ai
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create **`.env`** in the project root (never commit):

```bash
OPENAI_API_KEY=sk-...
```

Company defaults: `config/ company.json` or `config/company.json` (leading-space filename is supported by scripts).

## Why quantities are sometimes zero

**Wall linear feet** must come from somewhere: embedded profile LF, **`--lf-json`**, or AI **`takeoff_framing.py --estimate-lf`** on the PDF. Without LF, drywall GWB and wall sheathing sheet counts stay near **zero**.

## Quick demo (sample LF + full pipeline)

Uses `config/examples/mt_arlington_sample_lf.json` (replace with your real takeoff file for production):

```bash
source .venv/bin/activate
python scripts/run_pipeline.py --skip-merge --use-sample-lf \
  --building-sf 55000 --working-days 60 --round-trip-miles 80 \
  --with-drywall --with-windows --with-proposal --proposal-pdf --with-supplier-email
```

*(Do not type `...` on the command line — that was only shorthand in chat. Every token must be a real flag or value.)*

- **`--skip-merge`**: skip if `outputs/plan_profile_complete.json` is already current.
- Add **`--include-blockout`** / **`--equipment-months 2`** for KB framing adders.
- Drywall mobilization: **`--drywall-mobilization-miles 80 --drywall-mobilization-days 45`**.

## Main scripts (by step)

| Step | Script |
|------|--------|
| Plan analysis (OpenAI + PDF) | `scripts/analyze_plans.py` |
| Merge page JSON | `scripts/merge_profiles.py` |
| Framing takeoff | `scripts/takeoff_framing.py` (`--lf-json`, `--estimate-lf` + PDF) |
| Framing price | `scripts/price_framing.py` |
| Drywall takeoff | `scripts/takeoff_drywall.py` |
| Drywall price | `scripts/price_drywall.py` |
| Windows/doors | `scripts/takeoff_windows_doors.py`, `scripts/price_windows_doors.py` |
| Draft proposal (Markdown + simple PDF) | `scripts/generate_proposal.py` (`--pdf outputs/proposal_draft.pdf`) |
| **Branded 5-page proposal PDF** (bid modes, confidentiality) | `scripts/build_proposal_pdf.py` — see below |
| Email proposal (SMTP) | `scripts/email_proposal.py` (configure `.env` per `config/integrations.example.json`) |
| Supplier email body | `scripts/supplier_email.py` |
| **CRM** (SQLite) | `scripts/crm_cli.py` |
| **Lead pipeline** (CSV → filters → CRM) | `scripts/lead_pipeline.py` + `config/lead_pipeline.example.json` |
| **Market intel** (won/lost, $/SF) | `scripts/market_intel.py` |
| **Analytics** (GA4 CSV import, lead UTM) | `scripts/analytics_ingest.py` |
| **Template emails** (+ optional `--send`) | `scripts/render_outbound_email.py`, `scripts/email_sequence.py` |
| **Bid package** (PDF + photos + manifest) | `scripts/bid_package.py` (after `build_proposal_pdf.py`) |
| **CRM webhook** | `scripts/crm_webhook.py` (`CRM_WEBHOOK_URL` in `.env`) |
| **Ops smoke test** | `scripts/run_ops_demo.py` (temp DB; writes `outputs/bid_packages_demo/`) |
| Git autosave (optional) | `scripts/git_autosave.sh` + `launchd/README.txt` |

Outputs default under **`outputs/`**. Git ignores **`.env`**, **`.venv/`**, **`data/*.pdf`**, and **`outputs/*.xlsx` / `*.csv`**.

## Estimating features (KB-aligned)

- **ZIP tape + roller**: When the merged profile’s `sheathing` indicates ZIP or `zip_tape_required`, framing pricing adds **`zip_tape_roller_addon_per_wall_sheet_usd`** (see `config/Trades/rough_framing.json` → `sheathing_rules`).
- **Retainage**: All three pricers attach **`retainage_reference`** from `company.json` (`retainage_percent`) — **informational**; grand total is not reduced.
- **Floor/roof**: Framing takeoff includes **`floor_roof_estimating`** (supplier-quote vs dimensional guidance; roof labor tier for pricing).

### Ops & growth (local-first)

```bash
python scripts/crm_cli.py init
python scripts/lead_pipeline.py import config/examples/planhub_export_sample.csv --dry-run
python scripts/lead_pipeline.py import path/to/planhub_export.csv --to-crm --config config/lead_pipeline.example.json
python scripts/run_ops_demo.py   # end-to-end smoke (temporary CRM DB)
```

- **`docs/ROADMAP.md`** — what is scaffolded vs. still manual (API sync, scheduling).
- **`config/integrations.example.json`** — SMTP, webhook, PlanHub notes.
- **`outputs/KNOWLEDGE_BASE.md/KNOWLEDGE_BASE.md`** — **OPERATIONS & GROWTH** table.

## Roadmap (product / integrations)

- **`docs/ROADMAP.md`** — security notes; deferred items (vendor API, bi-directional CRM).
- **`config/integrations.example.json`** — env var names; copy to `integrations.json` locally (gitignored) if you prefer a file.
- **Knowledge base → “FUTURE MODULES”** — steel/concrete deferred; deeper SaaS integrations listed there.

Steel/concrete trades are **out of scope** for now. **Ops scaffold** (local CRM, CSV lead import, market intel, GA ingest, template emails, bid package folder, optional webhook) lives under `scripts/` — see **Ops & growth** below. Proposal **send** still needs SMTP in `.env`.

### Branded proposal PDF (`build_proposal_pdf.py`)

Input is **one JSON file** (schema: `config/proposal_input.schema.md`). It renders **5 Letter-size pages**: cover, investment (lump-sum-only vs itemized by `bid_mode`), scope paragraphs, payment schedule + **NJ/PA tax note** + assumptions, signatures.

- **`meta.bid_mode`:** `lump_sum` (client total only; hides `line_items`), `itemized`, `internal_review` (full detail + **CONFIDENTIAL** footer).
- **`meta.confidentiality`:** `client` | `internal` (internal triggers confidential footer).
- **Milestone filter:** payment rows with `"client_visible": false` are omitted on client-facing PDFs unless internal; use **0%** for internal-only rows so visible milestones still sum to **100%**.
- **Accent color:** edit `ACCENT_HEX` in `scripts/pdf_styles.py` (default `#D97706`).
- **Company block:** set `company.name`, `address`, `phone`, `email`, optional `logo_path` (e.g. `assets/logo.png`). Swap **Construction AI** in examples for your legal name.
- **Validity:** `meta.validity_days` (default **30**; scenario C uses **15**).
- **Tax:** `tax.jurisdiction` `NJ` | `PA` | `OTHER`, or `tax.custom_note` to override.

**Regression PDFs (3):**

```bash
python scripts/run_proposal_pdf_tests.py
```

Outputs: `outputs/proposal_test_A_lump_client.pdf`, `proposal_test_B_internal.pdf`, `proposal_test_C_pa_itemized.pdf`. Check A does **not** show internal line items or internal notes; B shows watermark + internal notes + hidden payment row; C shows PA wording + short validity.

```bash
python scripts/build_proposal_pdf.py -i config/proposal_examples/scenario_a_lump_sum_client.json -o outputs/my_proposal.pdf --strict
```

## Git

```bash
git add -A && git commit -m "Describe change" && git push
```
