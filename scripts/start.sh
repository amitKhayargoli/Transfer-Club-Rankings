#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Start Transfer Club Rankings - both API backend and frontend.
# ──────────────────────────────────────────────────────────────────────────────
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=== Transfer Club Rankings ==="

# ── 1. Activate virtual environment ─────────────────────────────────────────
if [ ! -d .venv ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi
source .venv/bin/activate

# ── 2. Start API backend (FastAPI) ──────────────────────────────────────────
echo "Starting API backend..."
fuser -k 8000/tcp 2>/dev/null || true
nohup uvicorn api.main:app --host 0.0.0.0 --port 8000 > /tmp/api.log 2>&1 &
API_PID=$!
echo "  API running on http://localhost:8000 (PID $API_PID)"

# ── 3. Build & start frontend (Next.js production) ─────────────────────────
echo "Building frontend..."
cd app
npx next build > /tmp/next-build.log 2>&1
echo "  Build complete"

echo "Starting frontend server..."
fuser -k 3000/tcp 2>/dev/null || true
nohup npx next start -p 3000 > /tmp/frontend.log 2>&1 &
FE_PID=$!
echo "  Frontend running on http://localhost:3000 (PID $FE_PID)"

cd "$PROJECT_ROOT"

echo ""
echo "  ✅  http://localhost:3000  - Frontend"
echo "  ✅  http://localhost:8000  - API"
echo ""
echo "Logs:  tail -f /tmp/api.log  |  tail -f /tmp/frontend.log"
