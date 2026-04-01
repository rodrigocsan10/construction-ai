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
  --with-drywall --with-windows --with-proposal --with-supplier-email
```

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
| Draft proposal text | `scripts/generate_proposal.py` |
| Supplier email body | `scripts/supplier_email.py` |
| Git autosave (optional) | `scripts/git_autosave.sh` + `launchd/README.txt` |

Outputs default under **`outputs/`**. Git ignores **`.env`**, **`.venv/`**, **`data/*.pdf`**, and **`outputs/*.xlsx` / `*.csv`**.

## Estimating features (KB-aligned)

- **ZIP tape + roller**: When the merged profile’s `sheathing` indicates ZIP or `zip_tape_required`, framing pricing adds **`zip_tape_roller_addon_per_wall_sheet_usd`** (see `config/Trades/rough_framing.json` → `sheathing_rules`).
- **Retainage**: All three pricers attach **`retainage_reference`** from `company.json` (`retainage_percent`) — **informational**; grand total is not reduced.
- **Floor/roof**: Framing takeoff includes **`floor_roof_estimating`** (supplier-quote vs dimensional guidance; roof labor tier for pricing).

## Roadmap (product / integrations)

See **Knowledge base → “FUTURE MODULES”**: steel/concrete deferred; PlanHub, CRM, email automation, richer bid PDFs, market intel, ads — **not implemented in code yet**; this README is the runbook for what exists today.

## Git

```bash
git add -A && git commit -m "Describe change" && git push
```
