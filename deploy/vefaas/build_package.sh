#!/usr/bin/env bash
# Builds the BytePlus veFaaS "Web Application" package for the Ad Replicator UI (one Python service: static web app +
# FastAPI backend on port 8000), following the Enterprise AI Agent Implementation Guide (Native Python 3.11 runtime,
# startup command `bash run.sh`, read-only code directory).
#   bash deploy/vefaas/build_package.sh            -> deploy/vefaas/dist/ad-replicator-vefaas.zip
# No secrets go into the package: ARK_API_KEY and UI_BASIC_AUTH are set as environment variables in the console.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="$ROOT/deploy/vefaas/dist"
STAGE="$OUT/stage"
PY=${PYTHON:-python3}

rm -rf "$STAGE" && mkdir -p "$STAGE/ui" "$STAGE/tools" "$STAGE/runs"

echo "[build] web app (static export)"
(cd "$ROOT/ui/web" && rm -rf .next out && npm run build >/dev/null)
cp -R "$ROOT/ui/web/out" "$STAGE/ui/web_out"

echo "[build] backend"
mkdir -p "$STAGE/ui/server"
cp "$ROOT"/ui/server/*.py "$STAGE/ui/server/"
cp "$ROOT/tools/ma_client.py" "$STAGE/tools/"
# the recorded demo run (offline replay, "Demo mode" on the history page): left out unless INCLUDE_DEMO=1
if [ "${INCLUDE_DEMO:-0}" = "1" ] && [ -d "$ROOT/runs/demo_caseB" ]; then cp -R "$ROOT/runs/demo_caseB" "$STAGE/runs/"; fi
# read-only copies of delivered jobs (ModelArk keeps session files for about a day); SHOWCASE_JOBS overrides the list
SHOWCASE_JOBS=${SHOWCASE_JOBS:-"job-20261023-120000-blnk job-20261021-131736-l0ge"}
if [ -n "$SHOWCASE_JOBS" ]; then
  "$ROOT/ui/.venv/bin/python" "$ROOT/deploy/vefaas/make_showcase.py" "$ROOT/ui/data/jobs" "$STAGE/runs/showcase" $SHOWCASE_JOBS
fi

echo "[build] python dependencies for Linux x86_64, Python 3.11 (vendored: no build step needed on the function)"
cat > "$STAGE/requirements.txt" <<'EOF'
fastapi==0.128.8
uvicorn==0.39.0
python-multipart==0.0.20
EOF
"$PY" -m pip download --quiet --only-binary=:all: --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 \
  --python-version 3.11 --implementation cp -d "$OUT/wheels" -r "$STAGE/requirements.txt"
"$PY" - "$OUT/wheels" "$STAGE/python_deps" <<'EOF'
import sys, zipfile, pathlib
src, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
dst.mkdir(parents=True, exist_ok=True)
for whl in sorted(src.glob("*.whl")):
    zipfile.ZipFile(whl).extractall(dst)
print(f"[build] vendored {len(list(src.glob('*.whl')))} wheels")
EOF

cat > "$STAGE/run.sh" <<'EOF'
#!/usr/bin/env bash
# veFaaS startup command: bash run.sh   (the code directory is read-only: never chmod, never write here)
set -e
cd "$(dirname "$0")"
export PYTHONPATH="$PWD/python_deps:$PWD/ui/server${PYTHONPATH:+:$PYTHONPATH}"
export UI_STATIC_DIR="${UI_STATIC_DIR:-$PWD/ui/web_out}"
export UI_DATA_DIR="${UI_DATA_DIR:-/tmp/ad-replicator/jobs}"
export UI_DOWNLOAD_MAX_BYTES="${UI_DOWNLOAD_MAX_BYTES:-600000}"
# prices per video are hidden by default (set UI_SHOW_COST=1 on the function to show them)
export UI_SHOW_COST="${UI_SHOW_COST:-0}"
# jobs started before this package was built are shipped as showcase copies or left out (their session files expire)
export UI_DISCOVER_AFTER="${UI_DISCOVER_AFTER:-__BUILD_TIME__}"
mkdir -p "$UI_DATA_DIR"
exec python3 -m uvicorn main:app --app-dir ui/server --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips '*'
EOF

sed -i.bak "s/__BUILD_TIME__/$(date -u +%Y-%m-%dT%H:%M:%SZ)/" "$STAGE/run.sh" && rm -f "$STAGE/run.sh.bak"
rm -f "$OUT/ad-replicator-vefaas.zip"
(cd "$STAGE" && zip -qr "$OUT/ad-replicator-vefaas.zip" . -x '*/__pycache__/*' '*.pyc')
echo "[build] $(du -h "$OUT/ad-replicator-vefaas.zip" | cut -f1) $OUT/ad-replicator-vefaas.zip"
