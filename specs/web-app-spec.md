# Transfer ROI Rankings  Interactive Web App Spec

> **Status:** Draft spec created from user interviews
> **Last updated:** June 4, 2026

---

## 1. 🎯 Project Vision

An interactive web application that analyzes football transfers across European competitions, calculates ROI for each transfer, and ranks clubs by their ability to buy low and sell high. The primary goal is to produce a **competitive leaderboard** that answers: *Which football clubs are the best at buying low and selling high?*

### Audience
- **Public / portfolio**  Showcase on GitHub, LinkedIn, etc.
- Football fans and data enthusiasts

---

## 2. 🏗️ Architecture

```
transfer-roi-rankings/            ← Monorepo
│
├── app/                          ← Next.js frontend
│   ├── pages/
│   │   ├── index.tsx             ← Dashboard / Overview
│   │   ├── rankings.tsx          ← Club Rankings Leaderboard
│   │   ├── clubs/[id].tsx        ← Club Detail Page
│   │   ├── players/[id].tsx      ← Player Detail Page
│   │   ├── explorer.tsx          ← Transfer Explorer
│   │   └── compare.tsx           ← Head-to-Head Comparison
│   ├── components/               ← Shared UI components
│   ├── lib/                      ← API client, utils
│   ├── styles/                   ← Global styles
│   └── tailwind.config.ts        ← daisyUI theme config
│
├── api/                          ← Python FastAPI backend
│   ├── main.py                   ← FastAPI entry point
│   ├── routers/
│   │   ├── clubs.py              ← Club endpoints
│   │   ├── players.py            ← Player endpoints
│   │   ├── transfers.py          ← Transfer endpoints
│   │   └── pipeline.py           ← Pipeline trigger endpoint
│   ├── models/                   ← SQLAlchemy / Pydantic models
│   ├── services/                 ← Business logic
│   └── requirements.txt
│
├── src/                          ← Python data pipeline (existing)
│   ├── clean.py
│   ├── pairs.py
│   ├── metrics.py
│   └── config.py
│
├── package.json
└── README.md
```

### Data Flow

```
KaggleHub → src/ pipeline (triggered from UI)
                │
                ▼
          PostgreSQL DB
                │
                ▼
        FastAPI REST API
                │
                ▼
        Next.js Frontend
```

---

## 3. ⚙️ Tech Stack

### Frontend  Next.js + daisyUI
| Layer | Choice | Why |
|-------|--------|-----|
| Framework | Next.js 14+ (React) | SSR, file-based routing, Vercel deploy |
| Styling | Tailwind CSS + daisyUI | Component library with 30+ built-in themes. Provides ready-made tables, cards, modals, sidebar, etc. Themes selected: `emerald` (green), `aqua` (blue), `dark` (dark). Switchable via `data-theme` attribute. |
| Charts | Recharts / Plotly.js | Interactive scatter plots, radar charts, bar charts |
| State | React Query (TanStack Query) | Server state management, caching, refetching |
| Search | Fuse.js (client-side fuzzy search) | Lightweight fuzzy search for clubs and players |

### Backend  FastAPI + PostgreSQL
| Layer | Choice | Why |
|-------|--------|-----|
| Framework | FastAPI | Async, auto-docs, Python, integrates with data pipeline |
| Database | PostgreSQL | Reliable, concurrent access, good for public deployment |
| ORM | SQLAlchemy 2.0 | Mature, async support |
| Migrations | Alembic | Schema versioning |
| Deployment | Railway / Render | Easy FastAPI deployment, free tier |

### Data Pipeline (Python)
| Script | Purpose |
|--------|---------|
| `src/pipeline.py` | Orchestrator that runs clean → pairs → metrics |
| `src/clean.py` | Load & clean raw CSVs, filter 2000–2025 |
| `src/pairs.py` | Build buy-sell pairs, calculate ROI/tenure |
| `src/metrics.py` | Aggregate by club, compute composite score |
| Trigger | Via web UI "Refresh Data" button → calls FastAPI endpoint → runs pipeline → writes to PostgreSQL |

---

## 4. 📄 Pages & Views

### 4.1 Dashboard / Overview (`/`)
- **Purpose:** Landing page with high-level stats and key insights
- **Elements:**
  - Hero section with project title, tagline
  - Key stat cards: total transfers analyzed, total clubs, total profit across all clubs, biggest single profit transfer
  - Spotlight section: Top 3 clubs by composite score (with mini stats)
  - Latest / notable transfers callout
  - Quick links to other pages

### 4.2 Club Rankings Leaderboard (`/rankings`)
- **Purpose:** Ranked table of all clubs sorted by default metric
- **Default sort:** Median ROI %
- **Key metrics displayed:**
  - Median ROI %
  - Annualized ROI %
  - Total Profit (€)
  - Hit Rate %
  - Value Creation %
  - Volume (# transfers)
  - Composite Score
- **Features:**
  - Sortable columns (click to sort asc/desc)
  - Filter by league (dropdown of all European leagues)
  - Filter by time range: pre-set periods (Last 5y, Last 10y, All time) + custom date slider
  - Minimum transfers threshold (default 10, adjustable)
  - Click a club row → navigates to Club Detail page
  - Scatter plot: ROI % vs Hit Rate (toggleable, embedded in page)

### 4.3 Club Detail Page (`/clubs/[id]`)
- **Purpose:** Deep dive into a single club's transfer performance
- **Elements:**
  - Club header: name, league badge, key stat cards (ROI, profit, hit rate, volume, score)
  - Radar chart: club's metrics vs league average vs top club
  - All transfers table for this club (sortable by date, fee, profit, ROI)
  - Time-series: Profit/ROI over time
  - Top 5 most profitable transfers
  - Top 5 worst transfers (biggest losses)

### 4.4 Player Detail Page (`/players/[id]`)
- **Purpose:** View a player's transfer history and value trajectory
- **Elements:**
  - Player header: name, position, age, current club
  - Transfer history timeline (all transfers with fees, clubs, dates)
  - Market value over time chart (from player_valuations data)
  - Profit/ROI for each transfer involving this player

### 4.5 Transfer Explorer (`/explorer`)
- **Purpose:** Interactive exploration of individual transfers
- **Elements:**
  - Scatter plot: Buy Fee (x-axis) vs Sell Fee (y-axis), colored by ROI
  - Filters panel:
    - Club (buying or selling)
    - Player position
    - Minimum ROI
    - Time range
    - League
  - Below scatter: detailed table of matching transfers
  - Click a point → highlight row in table and vice versa
  - Tooltip on hover: player name, clubs, fees, ROI, date

### 4.6 Head-to-Head Comparison (`/compare`)
- **Purpose:** Side-by-side comparison of any two clubs
- **Elements:**
  - Two club selectors with fuzzy search autocomplete
  - Radar chart comparing 6 key metrics
  - Side-by-side stat table
  - Comparison bar charts for individual metrics
  - Shareable link: `/compare?club1=ajax&club2=benfica`

---

## 5. 🎨 Design & UX

### Theme
- **Framework:** daisyUI with built-in themes (`data-theme` attribute)
- **Multiple themes available (switchable via theme toggle in UI):**
  - `emerald`  Fresh green theme (pitch feel, primary)
  - `aqua`  Blue/cyan theme (cool tone)
  - `dark`  Dark theme (default, easy on the eyes)
  - User can add more daisyUI themes later (e.g. `night`, `forest`, `garden`)
- **Theme toggle:** A sun/moon icon in the sidebar header to cycle between themes or open a theme picker
- **Components to leverage from daisyUI:**
  - `Table`  for all data tables (sortable, striped)
  - `Drawer` / `Sidebar`  for navigation (multi-page layout)
  - `Card`  for stat cards, club cards
  - `Dropdown`  for filters
  - `Modal`  for detail popups
  - `Range` slider  for date range
  - `Tooltip`  for chart interactions
  - `ThemeController`  for the theme toggle
- **User can tweak design later**  theme colors, layout refinements, add custom themes over daisyUI base

### Navigation
- Persistent left sidebar with icons
- Sections: Dashboard, Rankings, Explorer, Compare
- Club & Player detail pages accessible via links from tables

### Responsiveness
- Desktop-first (analytics dashboard)
- Tablet-friendly: sidebar collapses to hamburger menu
- Mobile: stacked layouts, simplified tables

### Polish (production-ready)
- Loading skeletons / spinners
- Empty states with helpful messages
- Error states with retry buttons
- Smooth page transitions
- Interactive tooltips on all charts
- Keyboard navigation support

---

## 6. 🔌 API Endpoints (FastAPI)

### Clubs
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/clubs` | List all clubs with aggregated metrics. Query params: `league`, `min_transfers`, `sort_by`, `sort_order`, `year_from`, `year_to` |
| GET | `/api/clubs/{id}` | Single club detail with all metrics |
| GET | `/api/clubs/{id}/transfers` | All transfers for a club |
| GET | `/api/clubs/compare?ids=1,2` | Comparison data for two clubs |

### Players
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/players` | Search/list players. Query params: `q` (fuzzy search), `position`, `club_id` |
| GET | `/api/players/{id}` | Player detail with transfer history & valuation timeline |

### Transfers
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/transfers` | List transfers with filters. Query params: `club_id`, `position`, `min_roi`, `year_from`, `year_to`, `page`, `per_page` |

### Dashboard
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/dashboard/stats` | High-level stats: total transfers, clubs, profit, biggest transfer |
| GET | `/api/dashboard/top-clubs` | Top 10 clubs by composite score |

### Pipeline
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/pipeline/run` | Trigger the data pipeline. Runs clean → pairs → metrics → writes to PostgreSQL |
| GET | `/api/pipeline/status` | Check if data is loaded and last refresh timestamp |

### Search
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/search?q={query}` | Unified fuzzy search across clubs and players |

---

## 7. 📊 Database Schema (PostgreSQL)

### Clubs Table
```sql
CREATE TABLE clubs (
    club_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    domestic_competition_id TEXT,
    league_name TEXT,
    total_transfers INTEGER,
    median_roi FLOAT,
    annualized_roi FLOAT,
    total_profit FLOAT,
    hit_rate FLOAT,
    value_creation FLOAT,
    composite_score FLOAT,
    last_updated TIMESTAMP
);
```

### Players Table
```sql
CREATE TABLE players (
    player_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    position TEXT,
    date_of_birth DATE,
    current_club_id INTEGER
);
```

### Transfers Table
```sql
CREATE TABLE transfers (
    transfer_id SERIAL PRIMARY KEY,
    player_id INTEGER REFERENCES players,
    player_name TEXT,
    from_club_id INTEGER REFERENCES clubs,
    to_club_id INTEGER REFERENCES clubs,
    from_club_name TEXT,
    to_club_name TEXT,
    transfer_date DATE,
    transfer_fee FLOAT,
    buy_fee FLOAT,
    sell_fee FLOAT,
    profit FLOAT,
    roi_pct FLOAT,
    annualized_roi_pct FLOAT,
    tenure_days INTEGER,
    tenure_years FLOAT,
    peak_value FLOAT,
    value_creation_pct FLOAT,
    player_position TEXT,
    age_at_transfer FLOAT
);
```

### Player Valuations Table
```sql
CREATE TABLE player_valuations (
    id SERIAL PRIMARY KEY,
    player_id INTEGER REFERENCES players,
    date DATE,
    market_value_in_eur FLOAT,
    current_club_id INTEGER
);
```

---

## 8. 🔍 Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Full-stack over static** | API enables on-demand filtering, searching, and future pipeline triggers from UI |
| **PostgreSQL over SQLite** | Needed for concurrent API access if deployed publicly |
| **daisyUI over hand-rolled** | Speeds up development with pre-built components; user can customize theme |
| **Pipeline triggerable from UI** | User wants a "Refresh Data" button  makes it feel like a complete app |
| **All European leagues** | Let users filter by league rather than pre-filtering  more flexible |
| **Median ROI % as default sort** | More robust than mean, less skewed by outliers |
| **Fuzzy search** | Essential for good UX when searching clubs/players |
| **Vercel + Railway/Render** | Best free-tier combo for Next.js + FastAPI deployment |

---

## 9. 🗺️ Implementation Order

### Phase A  Backend Foundation
1. Set up FastAPI project structure in `api/`
2. Define SQLAlchemy models matching the schema above
3. Set up Alembic migrations
4. Create API endpoints (clubs, players, transfers, dashboard, search)
5. Write pipeline runner that loads cleaned CSVs into PostgreSQL
6. Test all endpoints

### Phase B  Frontend Foundation
1. Initialize Next.js app with Tailwind + daisyUI
2. Set up sidebar navigation layout
3. Create API client layer (fetch calls to FastAPI)
4. Build Dashboard page (`/`)
5. Build Club Rankings page (`/rankings`) with table + scatter plot
6. Build Club Detail page (`/clubs/[id]`)
7. Build Transfer Explorer (`/explorer`)
8. Build Head-to-Head Comparison (`/compare`)
9. Build Player Detail page (`/players/[id]`)

### Phase C  Polish & Deploy
1. Add loading states, error handling, empty states
2. Responsive layout tweaks
3. daisyUI theme customization (green/dark/blue football theme)
4. Fuzzy search integration
5. Deployment: Vercel (Next.js) + Railway/Render (FastAPI + PostgreSQL)
6. README with screenshots and deployment instructions

---

## 10. 🧪 Testing Strategy

- **Backend:** pytest + httpx (async) for API endpoint tests
- **Frontend:** Vitest + React Testing Library for component tests
- **E2E:** Playwright for critical user flows (view rankings → click club → see detail)
- **Data accuracy:** Spot-check known transfers (Coutinho to Barcelona, etc.)

---

## 11. 🚀 Deployment

| Service | What | Why |
|---------|------|-----|
| **Vercel** | Next.js frontend | Native Next.js support, free tier, automatic deploys from GitHub |
| **Railway / Render** | FastAPI + PostgreSQL | Simple Python deployment, managed PostgreSQL, free tier |
| **GitHub** | Source code + issues | Public repo for portfolio |

---

## 12. 📈 Future Enhancements (Post-MVP)

- Inflation adjustment for fees across years
- Loan transfer filtering / flagging
- Player performance correlation (goals/assists vs transfer ROI)
- Dark mode toggle
- Export to PDF/CSV
- Shareable club comparison URLs
- Automated weekly data refresh via GitHub Actions cron
