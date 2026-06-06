# Transfer Club Rankings  Project Audit

## Data Source

- **Primary source:** Kaggle dataset `davidcariboo/player-scores`
- **Canonical GitHub:** [dcaribou/transfermarkt-datasets](https://github.com/dcaribou/transfermarkt-datasets)
- **Updated:** Weekly (auto-refreshed)
- **Raw files:** `data/raw/`  clubs.csv, players.csv, transfers.csv, appearances.csv, competitions.csv, player_valuations.csv
- **Database:** `data/transfer_roi.db` (SQLite, built from raw CSVs)

### Dataset Coverage

| Metric | Count |
|---|---|
| Total transfers in CSV | 40,208 |
| Transfers with fee > 0 | 3,002 (7.5%) |
| No fee / €0 | 37,206 (92.5%) |
| Matched buy-sell pairs (post-filter) | 1,011 |
| Clubs scored (MIN_TRANSFERS=3) | 135 |
| Total players | 47,701 |
| Total clubs | 796 |
| Date range | 2000–2025 |

### Known Missing Players

| Player | In players.csv? | In transfers.csv? |
|---|---|---|
| Lionel Messi (ID 28003) | ✅ | ❌ No transfer records |
| Cristiano Ronaldo (ID 8198) | ✅ | ❌ No transfer records |

Their moves (Barcelona → PSG → Inter Miami for Messi; Real Madrid → Juventus → Man United → Al-Nassr for Ronaldo) are missing likely because they are recent free transfers or were not scraped by this dataset version.

### Known Missing Clubs (no matched pairs in dataset)

| Club | Reason |
|---|---|
| Tottenham Hotspur | 0 matched buy-sell pairs |
| Atlético Madrid | 0 matched buy-sell pairs |
| Borussia Dortmund | 0 matched buy-sell pairs |
| Bayer Leverkusen | 0 matched buy-sell pairs |

### Clubs with 2 pairs (not scored at MIN_TRANSFERS=3)

| Club | Pairs |
|---|---|
| Arsenal | 2 |
| AC Milan | 2 |
| Spezia Calcio | 2 (would be #1 at threshold 2 with 100,837% ROI) |

---

## Analytics Pipeline

### `api/services/analytics.py`

**`compute_buy_sell_pairs()`**
1. Loads all transfers with fee > 0
2. Creates buy & sell rows per transfer
3. Merges on (player_id, club_id) where sell_date > buy_date
4. Deduplicates (keeps last buy→sell pair per player-club)
5. **Filters out pairs where buy_fee < MIN_BUY_FEE (€100K)**  prevents near-free transfers from inflating ROI
6. Computes: profit, ROI%, tenure, annualized ROI, value creation
7. Writes results to Transfer rows (on buy transfer only)

**`compute_club_metrics()`**
1. Loads all transfers with ROI data
2. Groups by club (buying club = to_club_id)
3. Aggregates: total_transfers, median_roi, total_profit, hit_rate, value_creation
4. **Filters clubs with total_transfers < MIN_TRANSFERS (3)**
5. Normalizes each metric to 0-1 range
6. Computes composite score = weighted sum of normalized metrics

### Weights (composite score)

| Metric | Weight |
|---|---|
| Median ROI | 35% |
| Total Profit | 25% |
| Hit Rate | 25% |
| Value Creation | 15% |

---

## Configuration Changes

### `api/config.py`

```python
MIN_YEAR = 2000
MAX_YEAR = 2025
MIN_TRANSFERS = 3          # Was 5, lowered to 2 then raised to 3
MIN_BUY_FEE = 100_000      # Added  filters out sub-€100K buys to prevent ROI inflation
```

### History of MIN_TRANSFERS changes

1. **Original: 5**  Only 67 clubs scored. Real Madrid (4 pairs), Bayern Munich (4), PSG (3), Arsenal (2) missing
2. **Lowered to 2**  214 clubs scored. Added Real Madrid, Bayern, PSG, Arsenal, AC Milan. But Spezia Calcio was #1 with 100,837% ROI (bought Gyasi for €1,000, sold for €2M)
3. **Raised to 3**  135 clubs scored. Added `MIN_BUY_FEE=100K` filter. Spezia excluded. No more inflated ROIs.

---

## Frontend Features

### Transfer Type Tags

| Badge | Type | Color |
|---|---|---|
| **Paid** | Fee-bearing transfer | Green (`badge-success`) |
| **Loan** | Detected loan (swapped clubs within 2 years) | Blue (`badge-info`) |
| **Youth** | Youth/reserve promotion | Purple (`badge-secondary`) |
| **Reserves** | Sent to reserve team | Teal (`badge-accent`) |
| **Expired** | Contract expired → Without Club | Orange (`badge-warning`) |
| **Retired** | Retired | Red (`badge-error`) |
| **Free** | Free transfer / unknown | Gray (`badge-ghost`) |

### Loan Detection Logic (`api/utils.py`  `detect_loans()`)

- Finds paired transfers for the same player with swapped clubs (A→B and B→A)
- Both transfers must have no fee (or fee = 0)
- Checks that transfers are within 730 days of each other (typical loan duration)
- Overrides `free_transfer` classification → `loan`

### Club Detail Page Filters

- **Sort:** Date (default), Fee ↓, Fee ↑
- **Filter by type:** Paid, Loan, Free, Youth, Reserves, Expired, Retired (clickable chips)
- **Count display:** "Showing X of Y transfers"

---

## Bug Fixes

### ORM Auto-commit Corruption (CRITICAL)

**File:** `api/routers/players.py`, `api/routers/clubs.py`

The player and club transfer endpoints were modifying SQLAlchemy ORM objects in-place (`t.profit = buy.profit`) before converting to Pydantic models. Because the ORM tracks changes, these mutations were auto-committed to the database on the next session flush, permanently corrupting the analytics data.

**Fix:** Changed to `data = TransferBase.model_validate(t)` first (creates an independent Pydantic model), then modify `data.profit` instead of `t.profit`.

### Formatting Fix

**File:** `app/src/pages/*.tsx`

`formatEuro()` and `formatPercent()` functions were updated:
- `.toFixed(1)` instead of `.toFixed(0)` to show decimals (€135.0M not €135M)
- `value === null || value === undefined` instead of `!value` to handle €0 correctly
- Applied to clubs, players, rankings, dashboard, compare, explorer pages

---

## Future Improvements

### Data Completeness
- Re-download the latest Kaggle dataset version (weekly updates may include new data)
- Try `ewenme/transfers` GitHub dataset for European league transfer data
- Augment specific missing players (Messi, Ronaldo) from FBref or Transfermarkt directly

### Analytics Quality
- Current issue: small-data clubs (3 pairs) still dominate the top of rankings because normalization widens the range
- Consider: minimum profit floor, confidence weights, or Bayesian shrinkage for low-count clubs
- Annualized ROI could be more meaningful than raw ROI for comparing across different hold periods

### Loan Detection
- Currently heuristic-based (swapped clubs within 730 days)
- Could be improved by checking loan flags in the source data if available
