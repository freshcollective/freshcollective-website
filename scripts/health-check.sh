#!/usr/bin/env bash
# Fresh Collective dev environment health check.
# Run from anywhere: bash /home/lindsey/fc-production/scripts/health-check.sh

set -euo pipefail

BACKEND_URL="http://127.0.0.1:8000"
FRONTEND_URL="http://localhost:3000"
BACKEND_DIR="/home/lindsey/fc-production/backend"

PASS="✓"
FAIL="✗"
ok=true

echo ""
echo "Fresh Collective — Dev Health Check"
echo "===================================="
echo ""

# ── Backend ──────────────────────────────────────────────────────────────────

if curl -fsS --max-time 3 "$BACKEND_URL/docs" > /dev/null 2>&1; then
  echo "$PASS  Backend responding at $BACKEND_URL"
else
  echo "$FAIL  Backend NOT responding at $BACKEND_URL"
  echo "      → Start it: ~/.local/bin/fc-run-backend"
  echo "        or:       cd $BACKEND_DIR && .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
  echo ""
  echo "      ECONNREFUSED 127.0.0.1:8000 in Next.js logs always means the"
  echo "      backend process is not running — it is not a code bug."
  ok=false
fi

# ── Frontend ─────────────────────────────────────────────────────────────────

if curl -fsS --max-time 5 "$FRONTEND_URL" > /dev/null 2>&1; then
  echo "$PASS  Frontend responding at $FRONTEND_URL"
else
  echo "$FAIL  Frontend NOT responding at $FRONTEND_URL"
  echo "      → Start it: ~/.local/bin/fc-run-frontend"
  ok=false
fi

# ── Alembic migration ────────────────────────────────────────────────────────

if [ -d "$BACKEND_DIR/.venv" ]; then
  alembic_out=$(cd "$BACKEND_DIR" && .venv/bin/alembic current 2>&1)
  if echo "$alembic_out" | grep -q "(head)"; then
    rev=$(echo "$alembic_out" | grep "(head)" | awk '{print $1}')
    echo "$PASS  Database migration at head ($rev)"
  else
    echo "$FAIL  Migration not at head"
    echo "      → Run: cd $BACKEND_DIR && .venv/bin/alembic upgrade head"
    ok=false
  fi
else
  echo "  ?  Alembic check skipped (no .venv found in $BACKEND_DIR)"
fi

echo ""

# ── Summary ──────────────────────────────────────────────────────────────────

if [ "$ok" = true ]; then
  echo "All checks passed. Environment is healthy."
else
  echo "One or more checks failed. See above."
fi

echo ""
