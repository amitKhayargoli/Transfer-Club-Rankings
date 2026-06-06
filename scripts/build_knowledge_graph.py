"""
Build a knowledge graph from the Transfer Club Rankings project conversation.
Generates:
  1. knowledge_graph.json  structured nodes + edges
  2. knowledge_graph.html  interactive vis.js visualization
"""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "knowledge-graph"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────
# Define all entities (nodes)
# ──────────────────────────────────────────────

nodes = [
    # ── Files ────────────────────────────────
    {"id": "api_config_py", "label": "api/config.py", "group": "file", "title": "Configuration: MIN_TRANSFERS=3, MIN_BUY_FEE=100K"},
    {"id": "api_utils_py", "label": "api/utils.py", "group": "file", "title": "Utility functions: classify_transfer, detect_loans"},
    {"id": "api_services_analytics_py", "label": "api/services/analytics.py", "group": "file", "title": "Core analytics pipeline"},
    {"id": "api_routers_players_py", "label": "api/routers/players.py", "group": "file", "title": "Player API endpoints"},
    {"id": "api_routers_clubs_py", "label": "api/routers/clubs.py", "group": "file", "title": "Club API endpoints"},
    {"id": "api_schemas_py", "label": "api/schemas.py", "group": "file", "title": "Pydantic schemas: TransferBase"},
    {"id": "api_models_py", "label": "api/models.py", "group": "file", "title": "SQLAlchemy ORM models"},
    {"id": "app_club_detail", "label": "app/src/pages/clubs/[id].tsx", "group": "file", "title": "Club detail page with sort/filter/badges"},
    {"id": "app_player_detail", "label": "app/src/pages/players/[id].tsx", "group": "file", "title": "Player detail page with badges"},
    {"id": "app_index", "label": "app/src/pages/index.tsx", "group": "file", "title": "Dashboard page"},
    {"id": "app_lib_api", "label": "app/src/lib/api.ts", "group": "file", "title": "API client + TypeScript interfaces"},
    {"id": "audit_md", "label": "audit.md", "group": "file", "title": "Project audit  all changes documented"},

    # ── Config Values ────────────────────────
    {"id": "MIN_TRANSFERS", "label": "MIN_TRANSFERS=3", "group": "config", "title": "Min matched pairs to score a club (was 5→2→3)"},
    {"id": "MIN_BUY_FEE", "label": "MIN_BUY_FEE=€100K", "group": "config", "title": "Min buy fee to include a pair in ROI calc"},

    # ── Pipeline Components ──────────────────
    {"id": "compute_buy_sell_pairs", "label": "compute_buy_sell_pairs()", "group": "pipeline", "title": "Matches buy→sell pairs per player per club"},
    {"id": "compute_club_metrics", "label": "compute_club_metrics()", "group": "pipeline", "title": "Aggregates pairs into club scores"},
    {"id": "run_full_analytics", "label": "run_full_analytics()", "group": "pipeline", "title": "Orchestrates full pipeline"},

    # ── Utility Functions ────────────────────
    {"id": "classify_transfer", "label": "classify_transfer()", "group": "function", "title": "Returns: paid, loan, youth_promotion, free, etc."},
    {"id": "detect_loans", "label": "detect_loans()", "group": "function", "title": "Finds loan pairs: swapped clubs within 730 days"},
    {"id": "enrich_transfer_types", "label": "enrich_transfer_types()", "group": "function", "title": "Club endpoint: classifies + propagates profit"},
    {"id": "formatEuro", "label": "formatEuro()", "group": "function", "title": "Frontend: formats € values with decimals"},

    # ── Features ─────────────────────────────
    {"id": "transfer_type_badges", "label": "Transfer Type Badges", "group": "feature", "title": "Paid / Loan / Youth / Reserves / Expired / Retired / Free"},
    {"id": "loan_detection", "label": "Loan Detection", "group": "feature", "title": "Heuristic: swapped clubs within 730 days, both fee-free"},
    {"id": "sort_filter_chips", "label": "Sort + Filter Chips", "group": "feature", "title": "Sort by date/fee, filter by transfer type"},
    {"id": "min_buy_fee_filter", "label": "MIN_BUY_FEE Filter", "group": "feature", "title": "Excludes sub-€100K buys to prevent ROI inflation"},

    # ── Bugs / Fixes ─────────────────────────
    {"id": "orm_corruption_bug", "label": "ORM Auto-Commit Bug", "group": "bug", "title": "Modifying ORM objects in-place persisted corrupted data"},
    {"id": "format_Null_bug", "label": "formatEuro Null Bug", "group": "bug", "title": "!value treated €0 as falsy → showed dash"},

    # ── Clubs ────────────────────────────────
    {"id": "sevilla", "label": "Sevilla", "group": "club", "title": "#1 ranked: 11 pairs, 321% ROI, 82% hit rate, €154M profit"},
    {"id": "real_madrid", "label": "Real Madrid", "group": "club", "title": "#25: 4 pairs, 145% ROI"},
    {"id": "bayern", "label": "Bayern Munich", "group": "club", "title": "#133: 4 pairs, -23% ROI"},
    {"id": "barcelona", "label": "Barcelona", "group": "club", "title": "#135: 5 pairs, -15% ROI"},
    {"id": "psg", "label": "PSG", "group": "club", "title": "#104: 3 pairs, -32% ROI"},
    {"id": "liverpool", "label": "Liverpool", "group": "club", "title": "#16: 9 pairs, 122% ROI"},
    {"id": "spezia", "label": "Spezia Calcio", "group": "club", "title": "Excluded (2 pairs): Gyasi €1K→€2M = 199,900% ROI"},
    {"id": "benfica", "label": "Benfica", "group": "club", "title": "#37: 4 pairs"},
    {"id": "arsenal", "label": "Arsenal", "group": "club", "title": "Excluded (2 pairs at threshold 3)"},
    {"id": "ac_milan", "label": "AC Milan", "group": "club", "title": "Excluded (2 pairs at threshold 3)"},
    {"id": "inter_milan", "label": "Inter Milan", "group": "club", "title": "#89: 7 pairs"},

    # ── Players ──────────────────────────────
    {"id": "coutinho", "label": "Philippe Coutinho", "group": "player", "title": "€135M Liverpool→Barcelona, -€115M loss for Barca"},
    {"id": "messi", "label": "Lionel Messi", "group": "player", "title": "No transfer records in dataset"},
    {"id": "ronaldo", "label": "Cristiano Ronaldo", "group": "player", "title": "No transfer records in dataset"},
    {"id": "gyasi", "label": "Emmanuel Gyasi", "group": "player", "title": "Spezia: €1K→€2M = 199,900% ROI (filtered by MIN_BUY_FEE)"},

    # ── Data Issues ──────────────────────────
    {"id": "fee_sparsity", "label": "92.5% Transfers No Fee", "group": "data_issue", "title": "37,206 of 40,208 transfers have €0/no fee"},
    {"id": "missing_messi_ronaldo", "label": "Messi/Ronaldo Missing", "group": "data_issue", "title": "No transfer records in the Kaggle dataset"},
    {"id": "missing_clubs", "label": "Clubs with 0 Pairs", "group": "data_issue", "title": "Tottenham, Atletico, Dortmund, Leverkusen"},

    # ── Datasets ─────────────────────────────
    {"id": "kaggle_dataset", "label": "davidcariboo/player-scores", "group": "dataset", "title": "Current Kaggle dataset (weekly updates)"},
    {"id": "github_dataset", "label": "dcaribou/transfermarkt-datasets", "group": "dataset", "title": "Canonical GitHub source"},
    {"id": "ewenme_transfers", "label": "ewenme/transfers (alt)", "group": "dataset", "title": "Alternative: European league transfers since 1992"},

    # ── Frontend Pages ──────────────────────
    {"id": "page_club_detail", "label": "Club Detail Page", "group": "page", "title": "/clubs/[id]  badges, sort, filter chips"},
    {"id": "page_player_detail", "label": "Player Detail Page", "group": "page", "title": "/players/[id]  badges, market value chart"},
    {"id": "page_rankings", "label": "Rankings Page", "group": "page", "title": "/rankings  135 clubs sorted by score"},
    {"id": "page_dashboard", "label": "Dashboard", "group": "page", "title": "/  overview stats"},

    # ── Session 2: Enrichment Pipeline & ETA ─
    {"id": "enrich_data_py", "label": "scripts/enrich_data.py", "group": "file", "title": "Main enrichment script with ETA display"},
    {"id": "RATE_LIMIT_1S", "label": "Rate Limit = 1.0s", "group": "config", "title": "Default rate limit changed from 2.5s→1.0s"},
    {"id": "eta_display", "label": "ETA Progress Display", "group": "feature", "title": "Shows remaining time (Xh Ym) every 10 players in enrichment log"},
    {"id": "233_clubs_scored", "label": "233 Clubs Scored", "group": "pipeline", "title": "233 clubs with composite scores after full enrichment"},
    {"id": "2848_pairs", "label": "2,848 Buy-Sell Pairs", "group": "pipeline", "title": "Total computed buy-sell pairs after enrichment + analytics"},
    {"id": "top5_fully_enriched", "label": "Top 5 Leagues 100%", "group": "pipeline", "title": "22 remaining players enriched. PL/LaLiga/SA/BL/L1 now fully complete"},
    {"id": "po1_gap", "label": "PO1: 1,888 Missing", "group": "data_issue", "title": "Liga Portugal: 82.4% of 2,292 active players still need scraping"},
    {"id": "nl1_gap", "label": "NL1: 1,662 Missing", "group": "data_issue", "title": "Eredivisie: 85.1% of 1,952 active players still need scraping"},
    {"id": "other_leagues_gap", "label": "Other EU: 14K Missing", "group": "data_issue", "title": "TR1, GR1, RU1, BE1, SC1, A1, DK1, PL1, etc. ~14K players total"},
    {"id": "sell_league_recommendation", "label": "Scrape PO1→NL1→BE1→A1", "group": "feature", "title": "Decision: Only selling leagues (Portugal, Eredivisie, Belgium, Austria) are worth scraping"},
    {"id": "skip_buyer_leagues", "label": "Skip TR1/GR1/RU1/SC1", "group": "feature", "title": "Decision: Turkish, Greek, Russian, Scottish leagues are net buyers, not worth scraping"},
    {"id": "brentford", "label": "Brentford", "group": "club", "title": "#20 overall, top PL club: 11 pairs, €199M profit, 367% median ROI"},
    {"id": "famalicao", "label": "Famalicão", "group": "club", "title": "#10 overall, top PO1 club: 6 pairs, €53.6M profit, 100% hit rate"},
    {"id": "lecce", "label": "Lecce", "group": "club", "title": "#12 overall, top IT1 club: 16 pairs, €101.7M profit, 100% hit rate"},
    {"id": "brighton", "label": "Brighton", "group": "club", "title": "#3 sell leader: 26 pairs, €273M profit (PL's best seller)"},
    {"id": "dortmund", "label": "Borussia Dortmund", "group": "club", "title": "#1 sell leader: 21 pairs, €302M profit"},
    {"id": "ajax", "label": "Ajax", "group": "club", "title": "#8 sell leader: 23 pairs, €204M profit (Eredivisie's best seller)"},
]

# ──────────────────────────────────────────────
# Define all relationships (edges)
# ──────────────────────────────────────────────

edges = [
    # Config → File
    {"from": "MIN_TRANSFERS", "to": "api_config_py", "label": "defined in"},
    {"from": "MIN_BUY_FEE", "to": "api_config_py", "label": "defined in"},

    # Pipeline → File
    {"from": "compute_buy_sell_pairs", "to": "api_services_analytics_py", "label": "defined in"},
    {"from": "compute_club_metrics", "to": "api_services_analytics_py", "label": "defined in"},
    {"from": "run_full_analytics", "to": "api_services_analytics_py", "label": "defined in"},

    # Pipeline → Config
    {"from": "compute_buy_sell_pairs", "to": "MIN_BUY_FEE", "label": "uses"},
    {"from": "compute_club_metrics", "to": "MIN_TRANSFERS", "label": "uses"},

    # Functions → File
    {"from": "classify_transfer", "to": "api_utils_py", "label": "defined in"},
    {"from": "detect_loans", "to": "api_utils_py", "label": "defined in"},
    {"from": "enrich_transfer_types", "to": "api_utils_py", "label": "defined in"},
    {"from": "formatEuro", "to": "app_club_detail", "label": "used in"},
    {"from": "formatEuro", "to": "app_player_detail", "label": "used in"},

    # Features → Functions
    {"from": "loan_detection", "to": "detect_loans", "label": "implemented by"},
    {"from": "transfer_type_badges", "to": "classify_transfer", "label": "uses"},
    {"from": "sort_filter_chips", "to": "app_club_detail", "label": "implemented in"},
    {"from": "min_buy_fee_filter", "to": "MIN_BUY_FEE", "label": "configures"},
    {"from": "min_buy_fee_filter", "to": "compute_buy_sell_pairs", "label": "applied in"},

    # Bugs → Files/Fixes
    {"from": "orm_corruption_bug", "to": "api_routers_players_py", "label": "affected"},
    {"from": "orm_corruption_bug", "to": "api_routers_clubs_py", "label": "affected"},
    {"from": "format_Null_bug", "to": "app_index", "label": "affected"},
    {"from": "format_Null_bug", "to": "app_club_detail", "label": "affected"},
    {"from": "format_Null_bug", "to": "app_player_detail", "label": "affected"},

    # Clubs → Data
    {"from": "spezia", "to": "gyasi", "label": "inflated by"},
    {"from": "spezia", "to": "MIN_TRANSFERS", "label": "excluded by"},
    {"from": "arsenal", "to": "MIN_TRANSFERS", "label": "excluded by"},
    {"from": "ac_milan", "to": "MIN_TRANSFERS", "label": "excluded by"},
    {"from": "sevilla", "to": "compute_club_metrics", "label": "scored by"},
    {"from": "real_madrid", "to": "compute_club_metrics", "label": "scored by"},
    {"from": "barcelona", "to": "compute_club_metrics", "label": "scored by"},

    # Data Issues → Dataset
    {"from": "fee_sparsity", "to": "kaggle_dataset", "label": "affects"},
    {"from": "missing_messi_ronaldo", "to": "kaggle_dataset", "label": "gap in"},
    {"from": "missing_clubs", "to": "kaggle_dataset", "label": "gap in"},

    # Players → Clubs
    {"from": "coutinho", "to": "barcelona", "label": "played for"},
    {"from": "coutinho", "to": "liverpool", "label": "played for"},
    {"from": "messi", "to": "barcelona", "label": "played for"},
    {"from": "ronaldo", "to": "real_madrid", "label": "played for"},
    {"from": "gyasi", "to": "spezia", "label": "played for"},

    # Players → Data Issues
    {"from": "messi", "to": "missing_messi_ronaldo", "label": "affected by"},
    {"from": "ronaldo", "to": "missing_messi_ronaldo", "label": "affected by"},

    # Datasets
    {"from": "kaggle_dataset", "to": "github_dataset", "label": "mirrors"},
    {"from": "ewenme_transfers", "to": "kaggle_dataset", "label": "alternative to"},

    # Pages → Files
    {"from": "page_club_detail", "to": "app_club_detail", "label": "rendered by"},
    {"from": "page_player_detail", "to": "app_player_detail", "label": "rendered by"},

    # Pages → Features
    {"from": "page_club_detail", "to": "sort_filter_chips", "label": "includes"},
    {"from": "page_club_detail", "to": "transfer_type_badges", "label": "shows"},
    {"from": "page_player_detail", "to": "transfer_type_badges", "label": "shows"},

    # Routes → Pages
    {"from": "api_routers_clubs_py", "to": "page_club_detail", "label": "powers"},
    {"from": "api_routers_players_py", "to": "page_player_detail", "label": "powers"},

    # Audit → Everything
    {"from": "audit_md", "to": "api_config_py", "label": "documents"},
    {"from": "audit_md", "to": "orm_corruption_bug", "label": "documents"},
    {"from": "audit_md", "to": "MIN_TRANSFERS", "label": "documents"},
    {"from": "audit_md", "to": "MIN_BUY_FEE", "label": "documents"},
    {"from": "audit_md", "to": "missing_messi_ronaldo", "label": "documents"},

    # Schema → Routes
    {"from": "api_schemas_py", "to": "api_routers_players_py", "label": "used by"},
    {"from": "api_schemas_py", "to": "api_routers_clubs_py", "label": "used by"},

    # Models → Schema
    {"from": "api_models_py", "to": "api_schemas_py", "label": "mapped to"},

    # Loan detection → Club endpoint
    {"from": "enrich_transfer_types", "to": "api_routers_clubs_py", "label": "used by"},
    {"from": "classify_transfer", "to": "api_routers_players_py", "label": "used by"},

    # API client → Frontend
    {"from": "app_lib_api", "to": "app_club_detail", "label": "used by"},
    {"from": "app_lib_api", "to": "app_player_detail", "label": "used by"},

    # ── Session 2 Edges ──────────────────────

    # Config → File
    {"from": "RATE_LIMIT_1S", "to": "enrich_data_py", "label": "configured in"},
    {"from": "eta_display", "to": "enrich_data_py", "label": "implemented in"},

    # Stats → Pipeline
    {"from": "233_clubs_scored", "to": "compute_club_metrics", "label": "produced by"},
    {"from": "2848_pairs", "to": "compute_buy_sell_pairs", "label": "produced by"},
    {"from": "top5_fully_enriched", "to": "enrich_data_py", "label": "completed by"},

    # Data gaps → Enrichment
    {"from": "po1_gap", "to": "top5_fully_enriched", "label": "next after"},
    {"from": "nl1_gap", "to": "po1_gap", "label": "next after"},
    {"from": "other_leagues_gap", "to": "nl1_gap", "label": "bigger pool"},

    # Decisions
    {"from": "sell_league_recommendation", "to": "po1_gap", "label": "addresses"},
    {"from": "sell_league_recommendation", "to": "nl1_gap", "label": "addresses"},
    {"from": "skip_buyer_leagues", "to": "other_leagues_gap", "label": "skips"},

    # Updated clubs → metrics
    {"from": "brentford", "to": "compute_club_metrics", "label": "scored by"},
    {"from": "famalicao", "to": "compute_club_metrics", "label": "scored by"},
    {"from": "lecce", "to": "compute_club_metrics", "label": "scored by"},
    {"from": "brighton", "to": "compute_club_metrics", "label": "scored by"},
    {"from": "dortmund", "to": "compute_club_metrics", "label": "scored by"},
    {"from": "ajax", "to": "compute_club_metrics", "label": "scored by"},

    # Sell ranking
    {"from": "dortmund", "to": "brighton", "label": "ranked above"},
    {"from": "brighton", "to": "ajax", "label": "ranked above"},

    # Enrichment script → API
    {"from": "enrich_data_py", "to": "compute_buy_sell_pairs", "label": "triggers"},
    {"from": "enrich_data_py", "to": "compute_club_metrics", "label": "triggers"},

    # ETA → rate limit
    {"from": "eta_display", "to": "RATE_LIMIT_1S", "label": "works with"},

    # All scored clubs
    {"from": "233_clubs_scored", "to": "brentford", "label": "includes"},
    {"from": "233_clubs_scored", "to": "famalicao", "label": "includes"},
    {"from": "233_clubs_scored", "to": "lecce", "label": "includes"},
]


# ──────────────────────────────────────────────
# Color scheme by group
# ──────────────────────────────────────────────

group_colors = {
    "file":       {"background": "#2d3748", "border": "#4a5568", "font": "#e2e8f0"},
    "config":     {"background": "#d69e2e", "border": "#b7791f", "font": "#1a202c"},
    "pipeline":   {"background": "#3182ce", "border": "#2b6cb0", "font": "#ffffff"},
    "function":   {"background": "#38a169", "border": "#2f855a", "font": "#ffffff"},
    "feature":    {"background": "#805ad5", "border": "#6b46c1", "font": "#ffffff"},
    "bug":        {"background": "#e53e3e", "border": "#c53030", "font": "#ffffff"},
    "club":       {"background": "#dd6b20", "border": "#c05621", "font": "#ffffff"},
    "player":     {"background": "#319795", "border": "#2c7a7b", "font": "#ffffff"},
    "data_issue": {"background": "#e53e3e", "border": "#c53030", "font": "#ffffff"},
    "dataset":    {"background": "#4a5568", "border": "#718096", "font": "#e2e8f0"},
    "page":       {"background": "#0bc5ea", "border": "#00a3c4", "font": "#1a202c"},
}

# ──────────────────────────────────────────────
# Save JSON
# ──────────────────────────────────────────────

graph_data = {
    "nodes": nodes,
    "edges": edges,
}

json_path = OUT_DIR / "knowledge_graph.json"
with open(json_path, "w") as f:
    json.dump(graph_data, f, indent=2)
print(f"Saved JSON: {json_path}")

# ──────────────────────────────────────────────
# Generate interactive HTML
# ──────────────────────────────────────────────

# Build nodes JSON for vis.js
vis_nodes = []
for n in nodes:
    g = n["group"]
    colors = group_colors.get(g, {"background": "#718096", "border": "#4a5568", "font": "#ffffff"})
    vis_nodes.append({
        "id": n["id"],
        "label": n["label"],
        "title": n.get("title", ""),
        "group": g,
        "color": {
            "background": colors["background"],
            "border": colors["border"],
        },
        "font": {"color": colors["font"], "size": 12, "face": "monospace"},
        "shape": "box",
        "size": 15,
    })

vis_edges = []
for e in edges:
    vis_edges.append({
        "from": e["from"],
        "to": e["to"],
        "label": e["label"],
        "arrows": "to",
        "font": {"size": 10, "color": "#a0aec0", "strokeWidth": 2, "strokeColor": "#1a202c"},
        "color": {"color": "#4a5568", "opacity": 0.6},
        "width": 1,
    })

# Build groups config for vis.js (in Python to avoid f-string escaping issues)
vis_groups = {}
for g in group_colors:
    vis_groups[g] = {"shape": "box", "font": {"face": "monospace"}}
vis_groups_json = json.dumps(vis_groups)

# Build legend from group_colors to keep in sync
legend_items = ""
for g, colors in group_colors.items():
    label = g.replace("_", " ").title()
    legend_items += f'<span style="display:inline-block; background:{colors["background"]}; color:{colors["font"]}; padding:2px 10px; border-radius:4px; font-size:12px; font-family:monospace;">{label}</span>'

# Build vis.js data JSON strings
vis_nodes_json = json.dumps(vis_nodes)
vis_edges_json = json.dumps(vis_edges)

html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Transfer Club Rankings  Knowledge Graph</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #1a202c; color: #e2e8f0; font-family: system-ui, -apple-system, sans-serif; }}
  #header {{ padding: 16px 24px; background: #2d3748; border-bottom: 1px solid #4a5568; }}
  #header h1 {{ font-size: 20px; font-weight: 600; }}
  #header p {{ font-size: 13px; color: #a0aec0; margin-top: 4px; }}
  #legend {{ padding: 8px 24px; background: #2d3748; border-bottom: 1px solid #4a5568; }}
  #legend-inner {{ display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }}
  #mynetwork {{ width: 100%; height: calc(100vh - 100px); }}
  .vis-tooltip {{ background: #2d3748 !important; color: #e2e8f0 !important; border: 1px solid #4a5568 !important; border-radius: 8px !important; padding: 8px 12px !important; font-size: 13px !important; font-family: monospace !important; box-shadow: 0 4px 12px rgba(0,0,0,0.4) !important; }}
  .vis-network:focus {{ outline: none; }}
</style>
</head>
<body>
<div id="header">
  <h1>🧠 Transfer Club Rankings  Knowledge Graph</h1>
  <p>Built from conversation: datasets · pipeline · bugs · fixes · clubs · players · features · data gaps</p>
</div>
<div id="legend"><div id="legend-inner">{legend_items}</div></div>
<div id="mynetwork"></div>
<script>
  const nodes = new vis.DataSet({vis_nodes_json});
  const edges = new vis.DataSet({vis_edges_json});

  const container = document.getElementById('mynetwork');
  const data = {{ nodes, edges }};
  const options = {{
    physics: {{
      solver: 'forceAtlas2Based',
      forceAtlas2Based: {{
        gravitationalConstant: -40,
        centralGravity: 0.005,
        springLength: 200,
        springConstant: 0.02,
        damping: 0.4,
      }},
      stabilization: {{ iterations: 200 }},
    }},
    layout: {{
      improvedLayout: true,
    }},
    edges: {{
      smooth: {{
        type: 'curvedCW',
        roundness: 0.15,
      }},
    }},
    interaction: {{
      hover: true,
      tooltipDelay: 100,
      navigationButtons: true,
      keyboard: true,
    }},
    groups: {vis_groups_json},
  }};

  const network = new vis.Network(container, data, options);
</script>
</body>
</html>"""

html_path = OUT_DIR / "knowledge_graph.html"
with open(html_path, "w") as f:
    f.write(html_content)
print(f"Saved HTML: {html_path}")

# ──────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────

print(f"\nKnowledge graph built successfully!")
print(f"  Nodes: {len(nodes)}")
print(f"  Edges: {len(edges)}")
print(f"  Groups: {len(set(n['group'] for n in nodes))}")
print(f"\nFiles:")
print(f"  {json_path}")
print(f"  {html_path}")


if __name__ == "__main__":
    pass  # Script runs top-to-bottom; this guard prevents side effects on import
