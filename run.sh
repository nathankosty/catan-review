#!/usr/bin/env bash
# One-command local startup: FastAPI backend (:8000) + Vite dev server (:5173).
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "First run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi
source .venv/bin/activate
export PATH="/opt/homebrew/bin:$PATH"
export PYTHONHASHSEED=0   # reproducible seeded games/analysis (see DECISIONS.md)

# Make sure the UI has a sample to load even with no backend.
mkdir -p web/public
[ -f data/games/sample.review.json ] && cp -f data/games/sample.review.json web/public/sample.review.json || true

echo "Starting FastAPI on :8000 ..."
uvicorn catan_review.api:app --port 8000 --reload &
BACK=$!
trap "kill $BACK 2>/dev/null || true" EXIT

echo "Starting Vite on :5173 ..."
( cd web && npm run dev )
