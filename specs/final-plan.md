# Final Project Plan: Transfer ROI Rankings

## Vision
Prove which football clubs generate the best ROI by buying young players for €10-15M and selling them for triple or quadruple amounts (e.g., Benfica → Enzo Fernandez €120M, Brighton → Joao Pedro €65M).

## Data Scope
- **Timeframe**: 2015–2026 (updated from 2000–2025)
- **Leagues**: Top 5 (GB1, ES1, IT1, FR1, L1) + Liga Portugal (PO1)
- **Focus**: Sell-side profitability (profit from players sold)

## Analytics Enhancements

### 1. Annualized ROI (Fix)
- Currently NULL on clubs table because `compute_club_metrics` doesn't aggregate it
- Fix: Add median of `annualized_roi_pct` from transfer pairs to club aggregation

### 2. New Club Metrics
- `annualized_roi` - median annualized ROI of all transfer pairs
- `profit_per_deal` - average profit per completed buy-sell pair
- `buying_club_premium` - median % difference between sell fee and peak market value (measures how much the buying club overpaid)

### 3. Composite Score Update
- Weight: 25% Median ROI + 20% Total Profit + 20% Hit Rate + 15% Value Creation + 10% Annualized ROI + 10% Profit Per Deal

## Frontend Pages

### 1. Club Page (Redesign)
Narrative-based layout instead of raw stats:
- **Club header**: Logo, name, league, composite score badge, "Best Selling Club" or "Academy Club" label
- **Overview cards**: Profit per deal, total profit, hit rate, annualized ROI
- **Most Profitable Transfers** (top 5 by profit)
- **Highest Transfer Fees** (top 5 by fee)
- **Full Transfer History** (existing table)

### 2. Best-Selling Clubs Page `/sell-clubs`
Ranked by total profit from selling players:
- Club rank, name, logo, league
- Total profit, profit per deal, hit rate
- Most valuable sale (highest sell fee)
- Number of profitable deals
- Sortable by profit, ROI, hit rate, profit per deal

### 3. Academy Clubs Page `/academy-clubs`
Clubs that develop youth talent and sell high:
- Filter by clubs with high % of youth promotions
- Ranked by value creation (peak MV vs buy fee)
- Show profit from academy graduates
- Show average age at sale

### 4. Dashboard Updates
- Hero text updated to "2015–2026"
- Quick link to Best-Selling Clubs
- Quick link to Academy Clubs
- Sidebar navigation updated

## API Endpoints

### New Endpoints
- `GET /api/clubs/sell-leaders` - Clubs ranked by sell-side profitability
- `GET /api/clubs/academy-leaders` - Clubs ranked by academy development

### Updated Endpoints
- `GET /api/clubs/{id}` - Include `profit_per_deal`, `buying_club_premium`
- `GET /api/clubs` - Include new sort fields

## Infra

### Database Migration
Add columns to `clubs` table:
- `annualized_roi FLOAT` (fix - populate in analytics)
- `profit_per_deal FLOAT`
- `buying_club_premium FLOAT`

### Enricher
Run for all target leagues after analytics update:
- GB1, ES1, IT1, FR1, L1, PO1
- With updated 2015-2026 filter

## Execution Order
1. ✅ Config: MIN_YEAR=2015
2. Add DB columns
3. Fix analytics (annualized_roi, profit_per_deal, buying_club_premium)
4. Update API endpoints + schemas
5. Redesign club page
6. Build Best-Selling Clubs page
7. Build Academy Clubs page
8. Update dashboard + sidebar
9. Re-run analytics
10. Re-run enricher for all target leagues
