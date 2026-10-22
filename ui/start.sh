#!/usr/bin/env bash
# One command to run the UI: backend (FastAPI, :8787) + web (Next.js, :3000).
#   ARK_API_KEY=... ui/start.sh            # production web build (default)
#   UI_DEV=1 ui/start.sh                   # Next dev server with hot reload
# The API key is read only by the backend process (tools/ma_client.py); it never reaches the browser.
set -euo pipefail
UI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$UI_DIR"

PY=${PYTHON:-python3}
if [ ! -x .venv/bin/python ]; then
  echo "[start] creating python venv"
  "$PY" -m venv .venv
fi
.venv/bin/python -m pip install -q -r server/requirements.txt

if [ ! -d web/node_modules ]; then
  echo "[start] installing web dependencies"
  (cd web && if [ -f package-lock.json ]; then npm ci; else npm install; fi)
fi

if [ -z "${ARK_API_KEY:-}" ] && [ ! -f "$HOME/.arkcli-bp/config.yaml" ]; then
  echo "[start] WARNING: ARK_API_KEY is not set and no arkcli profile was found: demo mode works, new runs will fail." >&2
fi

mkdir -p data/jobs
# prices per video are hidden on the local site; UI_SHOW_COST=1 shows them
export UI_SHOW_COST="${UI_SHOW_COST:-0}"
if [ "${UI_DEV:-0}" = "1" ]; then
  # development: backend on :8787, Next dev server on :3000 forwarding /api/* to it (hot reload)
  echo "[start] backend on http://localhost:8787"
  UI_PORT=8787 .venv/bin/python server/main.py &
  BACK=$!
  trap 'kill $BACK 2>/dev/null || true' EXIT
  cd web && npx next dev -p 3000
else
  # production: one process serves the static web app and /api on one port (same as the veFaaS deployment)
  if [ ! -f web/out/index.html ] || [ "${UI_REBUILD:-0}" = "1" ]; then
    echo "[start] building web (static export)"
    (cd web && npm run build)
  fi
  PORT="${UI_PORT:-3000}"
  echo
  echo "  Open http://localhost:${PORT}   (set UI_BASIC_AUTH=user:pass to require a sign-in)"
  echo
  UI_PORT="$PORT" exec .venv/bin/python server/main.py
fi
