# Data Enrichment Specification - transfermarkt-api Backfill

## Overview

The existing Transfer ROI Rankings dataset (Kaggle) is incomplete - it contains 47,701 players but only ~5,079 have transfers records and many players lack valuations, correct positions, and other fields. This spec defines a one-time backfill process using the [felipeall/transfermarkt-api](https://github.com/felipeall/transfermarkt-api) to scrape missing data from Transfermarkt and fill the gaps.

## Goals

- Enrich players in the top 5 European leagues + Liga Portugal with all missing data
- Fill transfer histories, market valuations, player profiles (positions, clubs, etc.)
- Re-run the analytics pipeline (ROI, composite scores) after enrichment
- Work as a standalone script invoked on demand

## Non-Goals

- Real-time / live scraping during normal API operation
- Creating new database tables beyond the existing 4 (clubs, players, transfers, player_valuations)
- Committing or distributing scraped data

## External API: transfermarkt-api

### Source
- **Repository**: https://github.com/felipeall/transfermarkt-api
- **License**: Open source (MIT)
- **Method**: Web scraping of transfermarkt.com public pages

### Available Endpoints

#### Player Endpoints

| Endpoint | Returns |
|----------|---------|
| GET /search/{player_name} | Search results matching player name (with page_number param) |
| GET /{player_id}/profile | Player profile: name, DOB, position, club, foot, height, nationality, market value |
| GET /{player_id}/market_value | Market value history over time (date -> value) |
| GET /{player_id}/transfers | Full transfer history with dates, clubs, fees |
| GET /{player_id}/stats | Season-by-season stats (appearances, goals, assists) |
| GET /{player_id}/injuries | Injury history |
| GET /{player_id}/achievements | Trophy / award history |
| GET /{player_id}/jersey_numbers | Jersey numbers per season |

#### Club Endpoints

| Endpoint | Returns |
|----------|---------|
| GET /search/{club_name} | Search results matching club name |
| GET /{club_id}/profile | Club profile: name, league, stadium, market value, squad size |
| GET /{club_id}/players | Current squad players (optional season_id param) |

#### Competition Endpoints

| Endpoint | Returns |
|----------|---------|
| GET /search/{competition_name} | Search results matching competition name |
| GET /{competition_id}/clubs | Clubs in the competition (optional season_id param) |

### Integration Method

**Chosen: Python library directly (not Docker).**

The transfermarkt-api code will be cloned as a Git submodule or copied into the project and called from Python. This avoids running a separate Docker container and allows direct data streaming into the existing SQLAlchemy session.

### Rate Limiting

- **Conservative**: 2-3 seconds between API calls (configurable)
- **Retry strategy**: Up to 3 retries with exponential backoff (1s -> 2s -> 4s), then skip and log

## Target League Scope

Priority order (top 5 European leagues + Liga Portugal):

| League | Competition ID |
|--------|---------------|
| English Premier League | GB1 |
| LaLiga | ES1 |
| Serie A | IT1 |
| Bundesliga | L1 |
| Ligue 1 | FR1 |
| Liga Portugal | PO1 |

Future expansion to other leagues can be done by modifying the league list in config.

## Data Mapping

### Existing Tables (SQLAlchemy Models)

#### players table - fields to backfill

| CSV Field | transfermarkt-api Source | Notes |
|-----------|-------------------------|-------|
| name | /profile (player name) | Already populated, can update |
| position | /profile (position) | Often missing in CSV |
| sub_position | /profile | Often missing in CSV |
| date_of_birth | /profile (DOB) | |
| current_club_id | /profile (current club ID) | |
| current_club_name | /profile (current club name) | |
| foot | /profile (foot) | Often null |
| height_in_cm | /profile (height) | Often null |
| market_value_in_eur | /profile (market value) | May be stale |
| highest_market_value_in_eur | /market_value (max value) | Can compute from history |

#### transfers table - fields to backfill

| CSV Field | transfermarkt-api Source | Notes |
|-----------|-------------------------|-------|
| player_id | /transfers | Links to player |
| player_name | /transfers | |
| from_club_id | /transfers (seller club ID) | |
| to_club_id | /transfers (buyer club ID) | |
| from_club_name | /transfers | |
| to_club_name | /transfers | |
| transfer_date | /transfers | |
| transfer_season | /transfers | |
| transfer_fee | /transfers | |
| market_value_in_eur | /transfers (MV at time of transfer) | |

> Note: The analytics pipeline populates computed fields (buy_fee, sell_fee, profit, roi_pct, etc.) so they do not need to be scraped directly.

#### player_valuations table - fields to backfill

| CSV Field | transfermarkt-api Source | Notes |
|-----------|-------------------------|-------|
| player_id | /market_value | Links to player |
| date | /market_value (date of valuation) | |
| market_value_in_eur | /market_value | |
| current_club_id | /market_value | |
| current_club_name | /market_value | |

#### clubs table - fields to backfill

| CSV Field | transfermarkt-api Source | Notes |
|-----------|-------------------------|-------|
| name | /profile | May update name |
| club_code | /profile | Transfermarkt URL slug |
| domestic_competition_id | /profile (league ID) | |

### Looking up Clubs by Name

Since club IDs may differ between systems, use the club name to match:
1. For each club, call GET /clubs/search/{club_name}
2. Find the matching club in search results by name similarity
3. Use the returned ID for subsequent /clubs/{club_id}/profile calls
4. Update the club record in the existing clubs table

## Error Handling

- **Retry**: Up to 3 retries with exponential backoff (1s -> 2s -> 4s)
- **Skip**: If all retries fail, log the error and move to the next player/club
- **Log format**: Structured JSON logs with player_id, error message, timestamp
- **Summary report**: After completion, print: total processed, succeeded, failed, skipped

## Execution

### Script: scripts/enrich_data.py

A standalone Python script that:
1. Connects to the existing database via SQLAlchemy
2. Discovers players from the target leagues who need enrichment
3. Fetches data from transfermarkt-api for each player (with rate limiting)
4. Upserts data into existing tables (players, transfers, player_valuations)
5. Re-runs the analytics pipeline to recompute ROI pairs and club scores
6. Reports a summary of what was enriched

### Command

```bash
cd /path/to/project
python scripts/enrich_data.py \
  --leagues GB1,ES1,IT1,L1,FR1,PO1 \
  --rate-limit 2.5 \
  --retries 3 \
  --auto-analytics
```

### Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| --leagues | Top 5 + PO1 | Comma-separated league IDs |
| --rate-limit | 2.5 | Seconds between API calls |
| --retries | 3 | Max retries per player |
| --auto-analytics | True | Re-run analytics after enrichment |
| --dry-run | False | Print what would be done without making changes |
| --start-from | None | Resume from a specific player_id |
| --batch-size | None | Process N players then stop (for testing) |

### Phases

#### Phase 1: Club Enrichment
1. Query all clubs from target leagues
2. For each club, search by name in transfermarkt-api
3. Get club profile, update club record (name, code, league)
4. Get club players (current squad) -> mark for player enrichment

#### Phase 2: Player Profile Enrichment
1. For each player, fetch /profile
2. Update player record (position, DOB, club, foot, height, market value)
3. Fetch /market_value -> update/insert valuations
4. Fetch /transfers -> update/insert transfers

#### Phase 3: Analytics Re-run
1. Run compute_buy_sell_pairs() from api.services.analytics
2. Run compute_club_metrics() from api.services.analytics
3. Update last_updated timestamps

### Transaction Safety
- Each player is processed in its own transaction
- If a player fails after 3 retries, partial data for that player is rolled back
- The script commits after each successful player to avoid losing progress

## Implementation Details

### Dependencies

The transfermarkt-api project depends on:
- Python 3.10+
- httpx (HTTP client)
- BeautifulSoup4 (HTML parsing)
- lxml

These will need to be added to the project's requirements.txt or managed via the existing .venv.

### Project Structure Changes

```
scripts/
  enrich_data.py              # Main enrichment script
  enrich/
    __init__.py
    player_enricher.py        # Player-specific enrichment logic
    club_enricher.py          # Club-specific enrichment logic
    analytics_runner.py       # Wrapper to re-run analytics
    transfermarkt_client.py   # API client with rate limiting
```

Alternatively, the transfermarkt-api code can be vendored directly into the project as a dependency.

### Rate Limiting Implementation

```python
import asyncio

class RateLimiter:
    def __init__(self, min_interval: float = 2.5):
        self.min_interval = min_interval
        self.last_call_time = 0.0

    async def wait(self):
        now = asyncio.get_event_loop().time()
        elapsed = now - self.last_call_time
        if elapsed < self.min_interval:
            await asyncio.sleep(self.min_interval - elapsed)
        self.last_call_time = asyncio.get_event_loop().time()
```

## Q&A Summary (from Interview)

| Question | Answer |
|----------|--------|
| Which data gaps to fill? | Everything - all missing data across all entity types |
| Scale approach? | Full one-time backfill script |
| Integration method? | Python library directly - call scraping functions, not Docker |
| Target players? | By league - top 5 European leagues + Liga Portugal |
| Data storage? | Existing tables only - no new tables |
| Error handling? | Retry then skip - 3 retries with backoff |
| Rate limit? | Conservative - 2-3 seconds between calls |
| Execution mode? | Standalone script (scripts/enrich_data.py) |
| Analytics re-run? | Both - auto re-run after backfill + manual trigger available |
| Club matching? | Compare names - search by name, match by name similarity |
| Leagues to target (custom)? | GB1, ES1, IT1, L1, FR1, PO1 |

## Edge Cases

### 1. Players Who Move Between Clubs Within the Same Transfer Window

A player may be bought and sold by the same club within a single transfer window (e.g., a January signing who is immediately loaned out, or a player used as a makeweight in another deal). The transfermarkt-api returns all transfers chronologically, so the raw data will contain these.

#### Detection
- Compare the buy and sell dates for each club-player pair in the enriched data
- If the tenure is less than ~30 days, flag it as a same-window transaction
- In extreme cases, a player could be bought and sold on the same day (e.g., as part of a complex multi-club deal)

#### Handling in Analytics
- **Include in ROI calculations**: These transfers are real and should count toward a club's metrics, even if the tenure is extremely short
- **Separate reporting**: Add a flag or separate view in the frontend to distinguish "quick flips" (tenure < 6 months) from longer-term investments
- **Annualized ROI distortion**: Same-window flips produce extreme annualized ROI values (e.g., a 50% profit in 2 days annualized to ~7,300%). Mitigation:
  - Cap annualized ROI at a reasonable maximum (e.g., ±500%) in the analytics pipeline
  - Allow filtering out windows transfers in the frontend
  - Store raw ROI alongside capped annualized ROI

#### Implementation
```python
MIN_TENURE_DAYS = 1  # Minimum tenure to count as a real transfer (0 = same-day)
MAX_ANNUALIZED_ROI = 500.0  # Cap annualized ROI to ±500%

def detect_window_flip(tenure_days: int | None) -> bool:
    """Return True if this transfer looks like a same-window flip."""
    if tenure_days is None:
        return False
    return tenure_days < 180  # Less than ~6 months

def cap_annualized_roi(roi: float | None) -> float | None:
    if roi is None:
        return None
    return max(min(roi, MAX_ANNUALIZED_ROI), -MAX_ANNUALIZED_ROI)
```

### 2. Players Who Return to a Club on Loan

A player may be signed permanently, loaned back to their former club, or return to a club they previously played for on a loan deal. These create circular transfer patterns that the analytics pipeline must handle correctly.

#### Example Scenarios
- **Scenario A**: Club A buys Player X from Club B. Player X is immediately loaned back to Club B for the season. The analytics sees: buy (A <- B), loan (A -> B). The loan return (B -> A) should not be treated as a sell.
- **Scenario B**: Player X plays for Club A, is sold to Club B, but returns to Club A on loan 2 years later. This is a legitimate loan that should not create a false buy-sell pair.
- **Scenario C**: Player X is at Club A, leaves on a free transfer, returns 5 years later on a permanent deal. This is a genuine new transfer, not a loan.

#### Existing Infrastructure
- The existing `api/utils.py` already has a `detect_loans()` function that identifies loan transfers by finding paired transfers with swapped clubs within ~2 years
- The `classify_transfer()` function marks fee-free transfers with swapped club pairs as `"loan"` type

#### Handling in Enrichment
1. **Loan classification**: When inserting transfers from the API, run the existing `detect_loans()` logic to mark loan transfers with `transfer_type = "loan"`
2. **Exclude loans from ROI pairs**: The analytics pipeline should ensure loan transfers (both out and return) are excluded from buy-sell pair computation:
   - A loan-out should not count as a "sell" for ROI purposes
   - A loan-return should not count as a "buy" for ROI purposes
3. **Retain loan data**: Loans should still be stored in the transfers table for display purposes, just excluded from analytics

#### Edge Case: Loan-with-option-to-buy
- Transfermarkt often lists these as separate entries: a loan transfer (fee = €0 or small loan fee) followed by a permanent transfer (fee > 0) at the end of the loan
- The analytics should treat the eventual permanent transfer as the real buy, not the initial loan
- Detection heuristic: if a loan transfer is followed by a paid transfer to the same club within 18 months, treat the paid transfer as the effective buy and exclude the loan from pair calculations

```python
def is_loan_with_option_to_buy(loans: list[Transfer], subsequent_paid: list[Transfer]) -> bool:
    """Check if a loan was followed by a permanent transfer to the same club."""
    for loan in loans:
        for paid in subsequent_paid:
            if (
                paid.to_club_id == loan.to_club_id
                and paid.transfer_date
                and loan.transfer_date
                and 0 < (paid.transfer_date - loan.transfer_date).days <= 548  # ~18 months
            ):
                return True
    return False
```

### 3. Data Consistency Checks

After enrichment, the data must pass a series of consistency checks to ensure integrity before the analytics pipeline re-runs. These checks cover referential integrity, temporal consistency, and numerical plausibility.

#### Referential Integrity Checks
- **Orphaned transfers**: Every `transfer.player_id` must exist in the `players` table. Orphaned transfers should be flagged but not deleted (they may reference players not yet enriched).
- **Orphaned valuations**: Every `player_valuation.player_id` must exist in the `players` table.
- **Club references**: Every `player.current_club_id` should ideally reference a club in the `clubs` table. Null is acceptable for free agents.

#### Temporal Consistency Checks
- **Date ordering**: For each player, transfer dates must be strictly increasing. If the API returns out-of-order transfers, the script should sort them before inserting.
- **Loan return timing**: A loan-out must precede the corresponding loan-return. Violations indicate data corruption.
- **Valuation dates**: Market valuation dates must be non-decreasing for each player. If the API returns valuations out of order, sort before inserting.
- **Age at transfer**: A player's transfer date must be after their date of birth. Transfers before age 14 should be flagged as suspicious.
- **Future transfers**: Transfer dates should not be more than 30 days in the future. These may be pre-arranged deals and should be included but flagged.

#### Numerical Plausibility Checks
- **Transfer fee sanity**: Fees should be positive for permanent transfers, zero or null for loans, free transfers, and youth promotions. Fees > €500M should be verified against the source.
- **Market value sanity**: Market values should be >= 0. Values > €300M are suspicious and should be flagged.
- **Tenure sanity**: Tenure between buy and sell should not exceed 20 years for the same club-player pair.
- **ROI sanity**: ROI values > ±10,000% should be flagged for manual review.

#### Deduplication Checks
- **Duplicate transfers**: Before inserting new transfers from the API, check for existing rows with the same (player_id, from_club_id, to_club_id, transfer_date) composite key. Skip duplicates.
- **Duplicate valuations**: Check for existing rows with the same (player_id, date, market_value_in_eur) composite key before inserting.
- **Overlapping transfer periods**: A player should not have two overlapping transfers (e.g., being at Club A and Club B simultaneously). Flag if detected.

#### Post-Enrichment Integrity Report

The script should output a consistency report after enrichment:

```
=== DATA CONSISTENCY REPORT ===

Referential Integrity:
  Orphaned transfers: 0
  Orphaned valuations: 0
  Clubs referenced but not in DB: 12

Temporal Consistency:
  Out-of-order transfers fixed: 3
  Future-dated transfers flagged: 1
  Transfers before age 14 flagged: 0

Numerical Plausibility:
  Fees > €500M flagged: 0
  MV > €300M flagged: 1 (player_id: 8198, MV: 120M - OK)
  ROI > ±10,000% flagged: 2

Deduplication:
  Duplicate transfers skipped: 15
  Duplicate valuations skipped: 42

Overall: PASS (5 warnings, 0 errors)
```

#### Failing Strategy
| Severity | Action |
|----------|--------|
| Error (e.g., negative fee) | Skip the transfer, log the issue, continue |
| Warning (e.g., high ROI) | Flag with a note, include in analytics but mark for review |
| Info (e.g., duplicate skipped) | Log and continue |

If error count exceeds a configurable threshold (default: 50 errors), halt the enrichment and prompt the user to investigate before continuing.
