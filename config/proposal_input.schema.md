# Proposal PDF input schema (`build_proposal_pdf.py`)

JSON root object:

| Field | Type | Notes |
|-------|------|--------|
| `meta` | object | `document_title`, `validity_days` (default 30), `bid_mode`, `confidentiality` |
| `company` | object | `name`, `address`, `phone`, `email`, optional `logo_path` (relative to repo root) |
| `project` | object | `name`, `owner`, `gc` (optional strings) |
| `scope_paragraphs` | string[] | Passed through to Page 3 |
| `investment` | object | `lump_sum` (number), optional `line_items` `{label, amount}` |
| `payment_schedule` | object[] | `label`, `pct` (number), optional `client_visible` (default true) |
| `tax` | object | `jurisdiction` `NJ` \| `PA` \| `OTHER`, optional `custom_note` |
| `assumptions` | string[] | Bullets for Page 4 |
| `confidential_sections` | object | optional `internal_notes` string[] — stripped in client modes |

### `meta.bid_mode`

- `lump_sum` — Page 2 shows **total only**; `line_items` hidden; `client_visible: false` payment rows hidden.
- `itemized` — Page 2 shows lump sum + line items (if any).
- `internal_review` — Full data; **CONFIDENTIAL** footer on every page; internal notes shown if present.

### `meta.confidentiality`

- `client` — Same filtering as appropriate for external GC (default with `lump_sum`).
- `internal` — Treat like internal review (confidential footer + full detail).

Validation (strict): payment `pct` must sum to 100 ± 0.01; `lump_sum` ≥ 0; required `company.name`, `project.name`.
