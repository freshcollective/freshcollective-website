#!/usr/bin/env bash
# Fresh Collective dev environment health check.
#
# Run from anywhere: bash <repo>/scripts/health-check.sh
#
# The repository location is derived from this script's own path, so the
# check always reports on the checkout it lives in. Nothing is hardcoded —
# running the copy in a stale worktree reports on that worktree, which is
# the honest answer rather than a misleading one.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$REPO_DIR/backend"
FRONTEND_DIR="$REPO_DIR/frontend"

BACKEND_URL="http://127.0.0.1:8000"
FRONTEND_URL="http://localhost:3000"

PASS="✓"
FAIL="✗"
ok=true

echo ""
echo "Fresh Collective — Dev Health Check"
echo "===================================="
echo "Checkout: $REPO_DIR"
branch=$(git -C "$REPO_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
echo "Branch:   $branch"
if [ "$branch" != "main" ] && [ "$branch" != "unknown" ]; then
  echo "          NOTE: not on main. Development normally happens on main"
  echo "          in the fc-merge checkout."
fi
echo ""

# ── Layout ───────────────────────────────────────────────────────────────────

for d in "$BACKEND_DIR" "$FRONTEND_DIR"; do
  if [ ! -d "$d" ]; then
    echo "$FAIL  Missing expected directory: $d"
    ok=false
  fi
done

# ── Backend ──────────────────────────────────────────────────────────────────

# /health exists in every environment; /docs is dev-only, so it is the
# weaker probe.
if curl -fsS --max-time 3 "$BACKEND_URL/health" > /dev/null 2>&1; then
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

# ── Backend virtual environment ──────────────────────────────────────────────

if [ -x "$BACKEND_DIR/.venv/bin/python" ]; then
  echo "$PASS  Backend venv present ($("$BACKEND_DIR/.venv/bin/python" --version 2>&1))"
else
  echo "$FAIL  No virtual environment at $BACKEND_DIR/.venv"
  echo "      → Create it: cd $BACKEND_DIR && python3 -m venv .venv &&"
  echo "                   .venv/bin/pip install -r requirements.txt"
  ok=false
fi

# ── Alembic migration ────────────────────────────────────────────────────────

if [ -x "$BACKEND_DIR/.venv/bin/alembic" ]; then
  alembic_out=$(cd "$BACKEND_DIR" && .venv/bin/alembic current 2>&1 || true)
  if echo "$alembic_out" | grep -q "(head)"; then
    rev=$(echo "$alembic_out" | grep "(head)" | awk '{print $1}')
    echo "$PASS  Database migration at head ($rev)"
  else
    echo "$FAIL  Migration not at head"
    echo "      → Run: cd $BACKEND_DIR && .venv/bin/alembic upgrade head"
    ok=false
  fi
else
  echo "  ?  Alembic check skipped (no .venv in $BACKEND_DIR)"
fi

echo ""

# ── Summary ──────────────────────────────────────────────────────────────────

if [ "$ok" = true ]; then
  echo "All checks passed. Environment is healthy."
else
  echo "One or more checks failed. See above."
fi

echo ""
