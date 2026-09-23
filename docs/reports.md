# Recommendations + reports

## Recommendation engine (`app/recommendations.py`)

Five collectors read **stored module data only** and write `recommendations`
rows; `POST .../recommendations/recalculate` (202, `CALCULATE_RECOMMENDATIONS`
job) replaces OPEN rows — IN_PROGRESS/DISMISSED/COMPLETED are never touched.

- **AUDIT**: top-15 firing rules of the latest completed audit. Impact from
  severity (CRITICAL 9 … NOTICE 2), effort from category.
- **GSC**: striking-distance queries (positions 4–15, ≥500 impressions, CTR
  <5%) and 28-day click decliners (≥30% drop, ≥50 baseline clicks).
- **KEYWORDS**: untracked keywords with opportunity ≥40 and volume ≥500.
- **RANK_TRACKING**: tracked keywords slipped ≥3 positions.
- **GAP**: missing/weak gap rows with opportunity ≥50.

Priority: `score = impact(0–10) × confidence(0–1) × 10 / effort(0.5–5)`,
clamped 0–100; keyword impact derives from the opportunity score so business
upside drives ranking. `GET .../recommendations` filters (type/source/
severity/status/min_score), sorts (score/severity/recent), paginates, and
returns status counts. `PATCH /api/v1/recommendations/{id}` transitions
status (tenant-checked). UI: `recommendations/` Action Center with High
Priority / Quick Wins sections and status buttons; the overview's Top
Opportunities feed from the same table.

## Reports (`app/reports.py`, `app/routers/reports.py`)

`POST .../reports` {SEO_OVERVIEW|AUDIT|KEYWORDS|RANKINGS|COMPETITORS} ×
{CSV|PDF} → `GENERATE_REPORT` job builds section tables from stored data
(CSV with `# section` markers; PDF via reportlab landscape tables) into a
**shared `exports` volume** (`/tmp/seo-exports`, 7-day expiry) so the API
container can serve what the worker wrote. `GET .../reports` lists with
per-export status; download is tenant-checked, readiness-checked (409 while
building) and expiry-checked (410). UI: `reports/` route with generate form,
live status, and authenticated download.
