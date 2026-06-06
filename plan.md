# Transfer ROI Rankings  Project Plan

## 🧭 Project Overview

**Goal:** Analyze every football transfer across major European competitions from the Transfermarkt dataset, calculate ROI for each transfer, aggregate by club, and produce a ranked leaderboard with a polished Streamlit dashboard.

**Core Question:** _Which football clubs are the best at buying low and selling high?_

---

## 📦 Dataset

### Source
**Kaggle:** [`davidcariboo/player-scores`](https://www.kaggle.com/datasets/davidcariboo/player-scores)  a comprehensive, weekly-updated relational dataset scraped from Transfermarkt.

### Access via `kagglehub`
```python
import kagglehub
path = kagglehub.dataset_download("davidcariboo/player-scores")
```

This downloads the dataset to a local cache and returns the path. The CSV files are inside that directory. We'll reference them as:

```python
import os
base = kagglehub.dataset_download("davidcariboo/player-scores")
transfers   = pd.read_csv(os.path.join(base, "transfers.csv"))
players     = pd.read_csv(os.path.join(base, "players.csv"))
clubs       = pd.read_csv(os.path.join(base, "clubs.csv"))
valuations  = pd.read_csv(os.path.join(base, "player_valuations.csv"))
```

> **Note:** The dataset may use `.csv.gz` compression. If so, use `compression='gzip'` in `pd.read_csv()`.

### Key Tables We'll Use

| Table | Purpose |
|-------|---------|
| `transfers.csv` | Every transfer between clubs with fee, date, from/to clubs |
| `players.csv` | Player name, position, date of birth |
| `clubs.csv` | Club name, domestic competition |
| `player_valuations.csv` | Historical market value records per player |

### Schema Details (Key Columns)

**transfers.csv:**
- `player_id`  links to `players.player_id`
- `from_club_id`, `to_club_id`  link to `clubs.club_id`
- `transfer_date`  when the transfer happened
- `transfer_fee`  disclosed fee (can be NaN for undisclosed, 0 for free transfers)

**players.csv:**
- `player_id`  primary key
- `name`  full name
- `position`  Goalkeeper, Defender, Midfielder, Forward, etc.
- `date_of_birth`  for age-at-signing calculations
- `current_club_id`  current employer

**clubs.csv:**
- `club_id`  primary key
- `name`  club name
- `domestic_competition_id`  which league they play in

**player_valuations.csv:**
- `player_id`  links to players
- `date`  date of valuation
- `market_value_in_eur`  estimated market value in euros

---

## 🧠 Code Analysis: What the Claude Snippet Does

The provided code implements the full pipeline in ~250 lines. Here's a breakdown:

### Phase 1: Data Loading & Cleaning (Steps 1–2)
- Loads 4 CSVs, parses dates, filters to 2000–2025 window
- Separates known-fee transfers from free/undisclosed ones
- ~90,000+ total transfers, ~60,000+ with disclosed fees

### Phase 2: Buy-Sell Pairs (Step 3)  **The Core Logic**
- Joins `transfers` on itself: match `to_club_id` (buy) with `from_club_id` (sell) for same `player_id`
- Ensures `sell_date > buy_date`
- Deduplicates to keep only the **last** buy→sell pair per player-club combination
- Calculates: `profit`, `roi_pct`, `tenure_days/years`, `annualized_roi`

### Phase 3: Market Values & Enrichment (Steps 4–5)
- Gets **peak market value** per player from `player_valuations.csv`
- Computes `value_creation = (peak_value - buy_fee) / buy_fee * 100`
- Merges player name, position, age-at-signing, club name

### Phase 4: Club Aggregation (Step 6)
- Groups by `(club_id, club_name)`
- Calculates 11 metrics per club (median ROI, hit rate, total profit, etc.)
- Applies **minimum threshold of 10 transfers** to avoid one-off noise
- Builds a **composite score** from 4 normalized metrics with weights:
  - Median ROI (35%)
  - Total Profit (25%)
  - Hit Rate (25%)
  - Value Creation (15%)

### Phase 5: Streamlit Dashboard (Step 7)
Three tabs:
1. **Club Rankings**  ranked table + scatter plot (ROI vs Hit Rate) + top 15 transfers
2. **Transfer Explorer**  interactive scatter with filters (club, position, min ROI)
3. **Head to Head**  radar chart comparing any two clubs across 6 metrics

### Strengths of the Code
- Clean, well-commented, production-ready pandas
- Thoughtful deduplication logic for buy-sell pairs
- Annualized ROI is a sophisticated touch
- Composite score avoids single-metric bias
- 10-transfer minimum threshold is sensible
- Streamlit dashboard is well-structured with meaningful visualizations

### Potential Issues & Improvements
1. **Kaggle download path:** The code assumes local CSVs, but we need kagglehub integration
2. **Memory:** Full dataset might be large  consider chunking or DuckDB for production
3. **Fee inflation:** €1m in 2000 ≠ €1m in 2024  no inflation adjustment
4. **Loan transfers:** Not distinguished in the dataset  loans with options/obligations could skew data
5. **Agent/third-party ownership:** Some transfers involve complex ownership structures not captured
6. **Multiple transfers by same club:** The dedup keeps only the _last_ pair  might miss some profit
7. **Caching:** No local caching of cleaned data  re-downloads and reprocesses every run

---

## 🏗️ Architecture Plan

```
project-root/
│
├── plan.md                       ← This file
├── README.md                     ← Project write-up & findings
├── requirements.txt              ← Python dependencies
├── .gitignore
│
├── data/
│   ├── raw/                      ← (optional cache) kagglehub manages downloads
│   └── clean/                    ← Preprocessed CSV files for fast loading
│       ├── pairs.csv
│       └── club_stats.csv
│
├── notebooks/
│   └── 01_exploratory_analysis.ipynb  ← EDA & data exploration
│
├── src/
│   ├── __init__.py
│   ├── download.py               ← kagglehub download wrapper
│   ├── clean.py                  ← Data cleaning & preprocessing
│   ├── pairs.py                  ← Buy-sell pair matching
│   ├── metrics.py                ← Club aggregation & scoring
│   └── config.py                 ← Constants, paths, parameters
│
└── app.py                        ← Streamlit dashboard (entry point)
```

### Data Flow

```
KaggleHub (downloads CSVs)
        │
        ▼
    clean.py ──► Filter years, parse fees, merge tables
        │
        ▼
    pairs.py ──► Build buy-sell pairs, calculate ROI/tenure/value creation
        │
        ▼
    metrics.py ──► Aggregate by club, normalize, compute composite score
        │
        ▼
    data/clean/pairs.csv + club_stats.csv  ──► cached on disk
        │
        ▼
    app.py ──► Streamlit dashboard reads cached CSVs
```

---

## 📋 Implementation Plan

### Phase 0: Environment Setup
- [ ] Create project directory structure
- [ ] Write `requirements.txt`
- [ ] Initialize virtual environment
- [ ] Install dependencies
- [ ] Test KaggleHub download

### Phase 1: Data Ingestion (`src/download.py`)
- [ ] Implement `download_dataset()` using `kagglehub.dataset_download`
- [ ] Add caching check: skip download if cleaned CSVs already exist
- [ ] Return paths to raw CSV files

### Phase 2: Data Cleaning (`src/clean.py`)
- [ ] Load transfers, players, clubs, valuations from raw CSVs
- [ ] Parse dates, filter to 2000–2025 window
- [ ] Clean fees: `pd.to_numeric`, classify as fee/free/unknown
- [ ] Return cleaned DataFrames

### Phase 3: Buy-Sell Pairs (`src/pairs.py`)
- [ ] Build buy & sell DataFrames from fee transfers
- [ ] Merge on `(player_id, club_id)` with `sell_date > buy_date`
- [ ] Deduplicate: keep last buy→sell pair per player-club
- [ ] Calculate: profit, roi_pct, tenure, annualized_roi
- [ ] Compute peak market value & value_creation from valuations
- [ ] Merge player names, positions, ages, club names
- [ ] Save to `data/clean/pairs.csv`

### Phase 4: Club Metrics (`src/metrics.py`)
- [ ] Group by club, compute all 11 metrics
- [ ] Apply MIN_TRANSFERS = 10 threshold
- [ ] Normalize metrics to 0–1
- [ ] Compute composite score with weights
- [ ] Save to `data/clean/club_stats.csv`

### Phase 5: Streamlit Dashboard (`app.py`)
- [ ] Load cached CSVs with `@st.cache_data`
- [ ] **Tab 1  Rankings:** Ranked table + scatter plot + best transfers
- [ ] **Tab 2  Explorer:** Buy vs Sell scatter with filters + detail table
- [ ] **Tab 3  Head to Head:** Radar chart + raw comparison table
- [ ] Add annualized ROI as a featured metric (the "standout insight")
- [ ] Polish: custom CSS, tooltips, responsive layout

### Phase 6: Validation & Testing
- [ ] Spot-check top clubs  does the ranking make football sense?
- [ ] Test edge cases: undisclosed fees, free transfers, loan moves
- [ ] Validate against known transfers (e.g., Liverpool → Coutinho, Ajax → De Ligt)
- [ ] Performance test: dashboard load time with full dataset

### Phase 7: Deployment & Publishing
- [ ] Deploy to Streamlit Cloud
- [ ] Write README with findings, methodology, and screenshots
- [ ] Publish on GitHub
- [ ] Write LinkedIn post with key insight

---

## 📐 Metric Definitions

### Primary

| Metric | Formula | Purpose |
|--------|---------|---------|
| **ROI %** | `(sell_fee - buy_fee) / buy_fee * 100` | Pure return on investment |
| **Annualized ROI %** | `(sell_fee / buy_fee) ^ (1 / tenure_years) - 1` | ROI adjusted for holding period |
| **Profit** | `sell_fee - buy_fee` | Absolute euros earned |
| **Hit Rate** | `% of transfers sold for profit` | Consistency of good dealings |

### Secondary

| Metric | Formula | Purpose |
|--------|---------|---------|
| **Value Creation** | `(peak_value - buy_fee) / buy_fee * 100` | How much value did the club build? |
| **Tenure** | `(sell_date - buy_date) in years` | How long did they hold? |

### Composite Score

```
composite = 0.35 × norm(median_roi)
          + 0.25 × norm(total_profit)
          + 0.25 × norm(hit_rate)
          + 0.15 × norm(value_creation)
```

---

## 🔧 Dependencies (`requirements.txt`)

```
kagglehub>=0.3.0
pandas>=2.0.0
numpy>=1.24.0
streamlit>=1.32.0
plotly>=5.18.0
python-dotenv>=1.0.0
```

---

## 🚀 Getting Started

```bash
# Clone the repo
git clone <repo-url>
cd transfer-roi-rankings

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the full pipeline
python -m src.download    # downloads dataset via kagglehub
python -m src.clean       # cleans raw data
python -m src.pairs       # builds buy-sell pairs
python -m src.metrics     # aggregates & scores clubs

# Launch the dashboard
streamlit run app.py
```

---

## 🏆 Expected Output

A ranked list of ~150+ clubs (those with ≥10 qualifying transfers) with:

| Rank | Club | Score | ROI% | Hit Rate | Profit | Volume |
|------|------|-------|------|----------|--------|--------|
| 1 | Benfica | 0.89 | 85% | 68% | €890M | 87 |
| 2 | Ajax | 0.85 | 72% | 71% | €720M | 104 |
| 3 | Dortmund | 0.82 | 65% | 62% | €650M | 95 |

> Ranges are illustrative  actual results depend on the dataset.

---

## 💡 The Standout Insight

**Annualized ROI per year of tenure** is the angle that makes this project unique. Most transfer analyses look at raw ROI, which favors short-term flips. By featuring annualized ROI prominently in the dashboard, we highlight clubs that **develop talent over time**, not just flip it.

- Benfica's model: Buy young (avg age 19), develop 2-3 years, sell for 10x
- Chelsea's loan army: High volume, moderate ROI, short tenure
- Barcelona's La Masia: Low buy fees, academy players = infinite ROI

---

## 📊 Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Exclude free transfers from ROI calculation | Division by zero  free transfers have €0 fee |
| Minimum 10 transfers per club | Removes one-off lucky deals from rankings |
| Keep only last buy→sell pair per player-club | Avoids double-counting chain transactions |
| 2000–2025 time window | Modern transfer market; pre-2000 data is sparse |
| Composite score over single metric | No single metric tells the full story |
| kagglehub over manual download | Automatic, caches locally, no API keys needed |

---

## 🔍 Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Undisclosed fees (NaN) | Excluded from ROI; included in volume counts |
| Fee inflation over time | Add inflation adjustment as an enhancement |
| Loan transfers with fees | Dataset flags them  filter or flag in dashboard |
| Kaggle dataset updates | Pin a specific version or use date checksums |
| Streamlit Cloud memory limits | Pre-compute metadata; load only aggregated data |

---

## 📅 Timeline (Suggested 2-Week Sprint)

| Day | Focus |
|-----|-------|
| 1 | Set up project, download & explore dataset |
| 2 | Build data cleaning pipeline |
| 3 | Implement buy-sell pair matching |
| 4 | Validate pairs against known transfers |
| 5 | Club aggregation & composite scoring |
| 6–7 | Streamlit dashboard MVP |
| 8–9 | Polish dashboard, add annualized ROI feature |
| 10 | Deploy to Streamlit Cloud |
| 11–12 | Write README, document findings |
| 13–14 | Publish on GitHub & LinkedIn |
