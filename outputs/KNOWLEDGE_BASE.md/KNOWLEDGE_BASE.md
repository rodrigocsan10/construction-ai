# CONSTRUCTION AI — COMPLETE KNOWLEDGE BASE

Last updated: April 1, 2026
This document contains ALL business rules, formulas, pricing, and system logic for the Construction AI Takeoff Tool. Use this as the single source of truth when building or updating the system.

---

## COMPANY INFO

- **Zip code:** 08075 (Burlington, NJ)
- **Max job distance:** 100 miles from 08075 (one way)
- **Work type:** Open shop only. No union, no prevailing wage.
- **Labor rates:**
  - Helper: $25/hr
  - Experienced carpenter: $30/hr
  - Foreman: ~$40/hr
- **Default sales tax (NJ):** 6.625% on all materials
- **PA jobs:** 6% sales tax (adjust per location)
- **Tax exempt toggle:** If client has ST-8 (capital improvement) or ST-5 (nonprofit) → tax = 0%
- **Material markup:** 10-12% (below 10% = underbidding, above 12% = overbidding, NO exceptions)
- **Mobilization:** Round trip miles × $0.50/mile × project working days (daily commute cost, not one-time)

---

## LAUNCH TRADES (3 trades for initial release)

1. Rough Framing + Sheathing
2. Drywall & Insulation
3. Exterior Windows & Doors Installation

Steel, concrete — deferred to future release.

---

## TRADE 1: ROUGH FRAMING + SHEATHING

### Scope
**Includes:** Walls (plates, studs, blocking, bracing), headers, floor system (joists or dimensional lumber), roof system (trusses sent to supplier / rafters calculated), sheathing (exterior walls, roof deck), exterior window and door installation, fire blocking, structural hardware installation.

**Excludes:** Interior doors (optional add-on), stairs (sometimes separate on commercial).

### Takeoff Process

**Step 1 — Architectural Plans:**
- Total SF of building
- Number of floors (multifamily)
- Wall type schedule → stud size, spacing, details per wall type
- Demising walls, partition walls, chase liners
- Linear feet per wall type on floor plans
- GO THROUGH OPENINGS — do NOT subtract door openings from LF

**Step 2 — Elevations:**
- Wall height per floor (determines stud length: 9', 10', etc.)

**Step 3 — Structural Plans:**
- LVLs, engineered wood, posts (sizes + locations)
- Hardware: Simpson Strong-Tie connectors, hangers — count each type
- Fastener specs: nail types, screws per engineer specs
- Shear walls: location, plywood type, nailing pattern
- Floor system: trusses vs TGI vs dimensional lumber + spacing + span
- Roof system: trusses vs rafters

### Wall Formulas

```
Plates = LF × 3 (one bottom plate + two top plates)
Studs = LF × 1.10 (waste) × 12 ÷ spacing (16 or 24) → round up
Bracing = LF ÷ 8 → round up (one 2x4 16-footer per 8 ft of wall)
Nails = 10 per LF of wall (box of 4,000 ≈ $45)
```

- Default interior studs: 2x4
- Default exterior studs: 2x6 (but ALWAYS verify on plans)
- Default spacing: 16" OC

### Header Rules
- **Always follow plans first.** If structural drawings specify header sizes per opening, use those.
- **When plans are incomplete, use defensible assumptions:**
  - Opening < 4 ft → 2x8 or 2x10
  - Opening 4-6 ft → 2x10 or 2x12
  - Opening > 6 ft → LVL
  - Code reference: IRC Table R602.7 (residential) or engineered design IBC (commercial)
- **ALWAYS label assumptions on proposals:** "Header sizing assumed per IRC Table R602.7 — pending final structural drawings"
- Headers are counted as EXTRA on top of stud count — separate line items by size (qty + LF of 2x8, 2x10, 2x12, LVL)

### Floor Joist Calculation
```
Joist length = span rounded UP to next even number (15' span → 16' lumber)
Joist count = perpendicular distance × 1.10 (waste) × 12 ÷ spacing → round up
```
- Check subfloor: tongue and groove? Glue? Nailed or screwed? (Screwed = more labor hours)
- If trusses → send plans to truss company for quote
- If dimensional lumber → calculate yourself

### Roof Rules
- **Trusses** = easier, lower price (~$12/SF to client). Send to truss company for quote.
- **Rafters** = harder, more labor ($16-17/SF to client, can go higher). Calculate like floor joists.
- Complex roof = 25-40% price increase over base rate

### Sheathing
```
Gross exterior SF = perimeter × wall height (per floor)
Net SF = gross SF − total window/door area
Sheets = net SF × waste factor ÷ 32 (each sheet = 4×8)
```
- Waste: 10% for square buildings, 12-15% for complex/lots of cuts
- **Types:** OSB (cheapest), CDX (mid), ZIP (expensive — requires tape + roller), Fire-rated (premium)
- **Labor:** $8-9 per sheet (paid to subcontractor)

### Pricing Benchmarks

**Residential (custom homes):**
- Scope: usually labor only
- Sub cost: $7-8/SF
- Client price: $12/SF (trusses, simple) → $16-20/SF (rafters, complex)

**Commercial / multifamily:**
- Scope: usually material + labor
- Sub cost (framing only): $2-3/SF
- Client price: ~$5.86/SF (based on real bid: 121,000 SF at $709K)

### Blockout Crew (commercial/multifamily only)
- What they do: hold downs, hardware installation, blocking, miscellaneous structural
- Crew: 2-3 guys × $30/hr × 9-hour day = $540-$810/day
- Duration: half of framing crew duration
- Example: if framing crew does building in 60 days, blockout = 30 days

### Equipment
- Genie lift / boom / scissor: $5,000/month (includes delivery, insurance — United Rentals)
- Telehandler: $5,000/month (rental + gas)
- Crane: $290/hour
- **Rules:**
  - 1-2 stories: no telehandler needed (optional)
  - 3+ stories: telehandler required
  - Trusses, heavy panels, 3+ floors: crane required
- **Proposal language:** "All equipment necessary for execution included unless otherwise noted."

### Supplier Material List
- System generates clean categorized list: dimensional lumber, engineered wood, sheathing, fasteners, hardware
- Each line: quantity, size, length, species/grade, description
- Format: Excel + clean text for email body
- Recipients: 84 Lumber, Builders FirstSource, Woodhaven Lumber
- Trusses: separate — "See attached plans — request truss quote"

---

## TRADE 2: DRYWALL & INSULATION

### Scope
**Includes:** Drywall hanging, finishing (tape, mud, sand), insulation (batt and mineral wool only).
**Excludes:** Spray foam, blown-in insulation, painting.

### Takeoff Process
**CRITICAL: Measure per wall type, per SIDE.** Each side can have different board types. Cannot just use LF.

1. Read wall type schedule — for each wall type, note what's on EACH side
2. Measure SF per wall type from floor plans (LF × height, per side)
3. Ceilings measured separately as SF

```
Side A sheets = (LF × height) × waste factor ÷ sheet SF
Side B sheets = (LF × height) × waste factor ÷ sheet SF
Ceiling sheets = ceiling SF × waste factor ÷ sheet SF
```

### Sheet Sizes (DO NOT hardcode 32 SF)
- 4×8 = 32 SF
- 4×10 = 40 SF
- 4×12 = 48 SF
- 4×14 = 56 SF
- 4×16 = 64 SF
- AI should optimize: recommend sheet size that produces least waste based on wall height
- User can override

### Board Types
- Standard 1/2" GWB
- 5/8" GWB
- 5/8" Type X (fire-rated)
- 5/8" Type C (enhanced fire-rated)
- Cement board (wet areas) — SAME PRICE as GWB
- Moisture-resistant (green board)

### Fire-Rated Walls — MUST DETECT
- **1-hour:** Single layer 5/8" Type X each side (UL U305, U411, U419)
- **2-hour:** Two layers 5/8" Type X each side (UL U301, U411, U419)
- Fire caulking required at all penetrations
- Fire tape required on joints

### Waste
- 10-12% on walls and ceilings

### Pricing (100% subcontracted, per sheet)
- Hanging: $10/sheet
- Finishing:
  - Level 0: $0 (no finishing)
  - Level 1: $8 (fire tape only)
  - Level 2: $9 (tape + one coat)
  - Level 3: $10 (standard)
  - Level 4: $11 (paint-ready) ← **DEFAULT when plans don't specify**
  - Level 5: $12 (premium skim)
- Material markup: 10%

### Vertical Carry Charge
- When multi-story AND no elevator/hoist: $0.75/sheet/floor above ground
- Status: market test — adjust based on feedback

### Insulation (batt + mineral wool only)
- SF from same wall type measurements as drywall
- Waste: 10-12%
- **Floor prices (never bid below):**
  - Fiberglass batt: $1.25/SF installed
  - Mineral wool: $2.00/SF installed
- Adjust after getting real sub quotes

### Gotchas
- Furring channels / hat track: extra material + labor
- Fire caulking: line item on fire-rated walls
- Scissor lift: required for walls/ceilings above 12 ft ($5,000/month)
- Mobilization: same formula as framing

---

## TRADE 3: EXTERIOR WINDOWS & DOORS INSTALLATION

### Scope
- **Labor only. ALWAYS.** Client furnishes all windows and doors. Never supply them.
- Subs handle their own logistics — no mobilization charge.

### Takeoff
- Count from elevations + window/door schedules
- Note brand (Anderson, Pella = harder install = higher rate)
- Classify: single, double, triple, slider, etc.

### Install Rates

**Residential:**
- Single window: $25
- Double window: $50
- Triple window: $75
- Pattern: $25 × number of panels

**Commercial / multifamily:**
- Single window: $50
- Double window: $75
- Triple window: $100
- Larger than triple: $150 minimum
- Sliding glass doors (assembly required, e.g. Anderson): $250 minimum each

### Handling & Unloading (both residential and commercial)
- Per window: $20
- Per exterior door: $15
- Status: market test

### Markup
- 20% flat on total sub cost (install + handling)
- No material markup (don't supply materials)
- No tax on materials (don't supply materials)

---

## GLOBAL RULES (apply to ALL trades)

### Sales Tax
```
Material cost after tax = material subtotal × 1.06625 (NJ)
Tax applied BEFORE material markup
```
**Framing (labor + material scope):** `price_framing.py` follows this order on supplier-line materials: raw → sales tax → markup → extended.

**Drywall & insulation (100% subcontract model):** Hang/finish and insulation are rolled into a **labor subtotal**, then optional KB extras (fire caulk, furring, scissor lift) and mobilization; **markup** applies to that bundle; **sales tax** is applied to `(subtotal + markup)` in `price_drywall.py`. This is not the same ladder as material bids — document both models in proposals.

**Windows & doors:** Client-supplied materials → **no material tax**; markup on install + handling only.

**PA jobs:** Use `--tax-pct 6` on pricing scripts when the job is taxable in PA (verify filing rules).

### Calculation Order for Material+Labor Bids
```
1. Raw material cost (from supplier or takeoff pricing)
2. + Waste factor (10-15% depending on trade)
3. + Sales tax (6.625% NJ default)
4. + Material markup (10-12%)
5. = Total material cost to client
```
The repo warns if framing material markup is outside the 10–12% band set in `company.json`.

### Mobilization
```
Mobilization = round trip miles × $0.50/mile × project working days
Max distance: 100 miles from 08075 (one way)
```

### Retainage
- Most GCs do 10% retainage
- Usually comes back 1+ year later
- Payment schedule must protect cash flow

---

## SYSTEM ARCHITECTURE

### Pipeline (as implemented)
```
Step 1: Plan analysis     → outputs/plan_analysis*.json  (scripts/analyze_plans.py + prompts/plan_analysis.txt)
Step 1b: Merge profiles   → outputs/plan_profile_complete.json  (scripts/merge_profiles.py)
Step 2: Trade takeoffs    → takeoff_framing.json, takeoff_drywall.json, takeoff_windows_doors.json
Step 3: Pricing           → estimate_*_priced.json + .xlsx
Step 4: Optional outputs  → proposal_draft.md, supplier_email_framing.txt
```
**One-shot orchestration:** `scripts/run_pipeline.py` (merge → framing takeoff → price framing; optional drywall, windows, `--with-proposal`, `--with-supplier-email`).

### File Structure
```
construction-ai/
├── config/
│    ├── company.json          (or " company.json" — leading space filename supported by scripts)
│    ├── equipment.json        (rental reference rates + story rules)
│    └── Trades/
│         ├── rough_framing.json
│         ├── framing_unit_costs.json
│         ├── drywall_insulation.json
│         └── windows_doors.json
├── prompts/
│    ├── plan_analysis.txt
│    └── framing_lf_estimate.txt
├── scripts/
│    ├── analyze_plans.py
│    ├── merge_profiles.py
│    ├── takeoff_framing.py
│    ├── price_framing.py
│    ├── takeoff_drywall.py
│    ├── price_drywall.py
│    ├── takeoff_windows_doors.py
│    ├── price_windows_doors.py
│    ├── run_pipeline.py
│    ├── generate_proposal.py
│    ├── supplier_email.py
│    └── extract_pdf.py        (legacy path)
├── data/                      (plan PDFs)
├── outputs/                   (generated JSON, XLSX, CSV, proposal draft)
├── .env                       (OPENAI_API_KEY for AI steps)
└── requirements.txt
```

### Current Status
- ✅ Config: company, trades, equipment, unit costs
- ✅ Plan analysis + merge to `plan_profile_complete.json`
- ✅ Framing takeoff: plates, studs, bracing, nails, sheathing sheets, headers from doors, supplier list CSV/XLSX; `floor_roof_estimating` (roof labor tier + floor action) from structural profile
- ✅ Framing price: material tax → markup, labor $/building SF with **rafter vs truss_engineered** multiplier, mobilization, optional **blockout crew** and **equipment allowance** (`--include-blockout`, `--equipment-months`)
- ✅ Drywall/insulation takeoff: per-side GWB SF, sheet counts, insulation SF + batt/bag/bundle est.; **kb_optional_allowances** (fire-rated SF, furring SF, scissor lift when wall height > threshold)
- ✅ Drywall price: sheet + insulation + KB extras + optional mobilization (`--mobilization-round-trip-miles`, `--mobilization-working-days`)
- ✅ Windows/doors takeoff + price (KB rates, handling, 20% markup)
- ✅ Draft proposal (`generate_proposal.py`) and supplier RFQ email body (`supplier_email.py`)
- 🔲 Retainage and OH/profit rules: framing applies company overhead/profit on subtotal — tune to match how you bid
- 🔲 Full floor joist counts from spans (only guidance + supplier-quote path unless dimensional floor called out in profile)

### What the Plan Analysis Found (MT. Arlington Building 2)
- Multifamily, 5 floors, ~55,000 SF
- 21+ interior wall types (A1-M2) with full stud/board/fire-rating detail
- Exterior wall types EW1-EW9 (ZIP, polyiso, CMU, metal/wood studs)
- 142+ doors across 14 types
- Windows: Pella Impervia + Andersen 100 Series (premium brands)
- Floor: concrete podium + wood trusses above
- Roof: trusses (lower labor tier)
- Sheathing: ZIP on rated assemblies (tape + roller required)
- Fire-rated walls: 1HR (B1, D1, H1, K1), 2HR (E1, L1, M2), 3HR (F1)
- L1: 2 layers GWB each side — doubles drywall material
- Ceilings: 5/8 Type X on resilient channel at 12" OC
- Weather barrier: drainable WRB + self-adhering membrane

---

## FUTURE MODULES (after launch trades are working)

1. **Steel fabrication & erection** — deferred
2. **Concrete work** — deferred
3. **Lead pipeline** — PlanHub email integration, filter by trade/size/location
4. **CRM** — lead tracking, qualification
5. **Email automation** — auto-send proposals, follow-up sequences, supplier price requests
6. **Bid generator** — professional proposals with job photos, payment schedule
7. **Market intelligence** — track won/lost bids, $/SF trends
8. **Website / Google Ads analytics** — lead source tracking

---

## Next improvements (backlog)
- **Runbook:** see repo root `README.md` (setup, `--use-sample-lf`, pipeline flags, Git notes).
- Parse structural sheets for **per-type hardware counts** (Simpson) and shear plywood SF/nailing
- **Residential** end-to-end test with `project.type: residential` and rafter roof string in `structural.roof_system.type`
- Richer **proposal** PDF (photos, payment schedule) — today: `outputs/proposal_draft.md`
- **ZIP / sheathing:** framing price adds ZIP tape+roller labor when profile flags ZIP (`rough_framing.json` → `sheathing_rules.zip_tape_roller_addon_per_wall_sheet_usd`).
- **Retainage:** shown on priced outputs as `retainage_reference` (informational; from `company.json`).
