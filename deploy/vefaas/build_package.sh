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
# list prices and the example projects' cost records: shipped in the package, never in git
if [ -f "$ROOT/ui/server/prices_local.json" ]; then
  PY="$ROOT/ui/.venv/bin/python"; [ -x "$PY" ] || PY=python3
  [ -f "$ROOT/deploy/vefaas/make_demo_costs.py" ] && { "$PY" "$ROOT/deploy/vefaas/make_demo_costs.py" >/dev/null || echo "[build] WARNING: example costs not refreshed"; }
  cp "$ROOT/ui/server/prices_local.json" "$STAGE/ui/server/"
  [ -f "$ROOT/ui/server/demo_costs.json" ] && cp "$ROOT/ui/server/demo_costs.json" "$STAGE/ui/server/"
else
  echo "[build] no ui/server/prices_local.json: the site will show time and tokens only"
fi
cp "$ROOT/tools/ma_client.py" "$STAGE/tools/"
# caption editor: the same drawing code, fonts and outro as the agent's video assembly
mkdir -p "$STAGE/skills/video-assembly"
cp -R "$ROOT/skills/video-assembly/scripts" "$ROOT/skills/video-assembly/assets" "$STAGE/skills/video-assembly/"
# direct regeneration checks new stills and takes with the quality gate's still_check / clip_check
mkdir -p "$STAGE/skills/ugc-quality-gate"
cp -R "$ROOT/skills/ugc-quality-gate/scripts" "$STAGE/skills/ugc-quality-gate/"
find "$STAGE/skills" -name "__pycache__" -type d -prune -exec rm -rf {} +
# the recorded demo run (offline replay, "Demo mode" on the history page): left out unless INCLUDE_DEMO=1
if [ "${INCLUDE_DEMO:-0}" = "1" ] && [ -d "$ROOT/runs/demo_caseB" ]; then cp -R "$ROOT/runs/demo_caseB" "$STAGE/runs/"; fi
# read-only copies of delivered jobs (ModelArk keeps session files for about a day). SHOWCASE_JOBS overrides the
# list; SHOWCASE_JOBS="" ships none. Jobs without a folder in ui/data/jobs (e.g. a fresh clone) are skipped.
SHOWCASE_JOBS=${SHOWCASE_JOBS-"job-20261023-120000-blnk job-20261021-131736-l0ge job-20261025-110730-riuf job-20261025-112250-qae3"}
FOUND_JOBS=""
for job in $SHOWCASE_JOBS; do
  if [ -f "$ROOT/ui/data/jobs/$job/job.json" ]; then
    FOUND_JOBS="$FOUND_JOBS $job"
  else
    echo "[build] showcase: no local folder for $job, skipped"
  fi
done
if [ -n "${FOUND_JOBS// /}" ]; then
  "$ROOT/ui/.venv/bin/python" "$ROOT/deploy/vefaas/make_showcase.py" "$ROOT/ui/data/jobs" "$STAGE/runs/showcase" $FOUND_JOBS
else
  echo "[build] showcase: no example projects in this package"
fi

echo "[build] python dependencies for Linux x86_64, Python 3.11 (vendored: no build step needed on the function)"
cat > "$STAGE/requirements.txt" <<'EOF'
fastapi==0.128.8
uvicorn==0.39.0
python-multipart==0.0.20
pillow==11.0.0
imageio-ffmpeg==0.6.0
yt-dlp[default]==2026.10.21
wrapt==1.16.0
Deprecated==1.3.1
pytz==2026.5
six==1.17.0
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
# TOS SDK (project files kept in the bucket): tos and crcmod ship as source only; both are pure Python here
mkdir -p "$OUT/sdist"
"$PY" -m pip download --quiet --no-deps --no-binary=:all: tos==2.9.3 crcmod==1.7 -d "$OUT/sdist"
for t in "$OUT"/sdist/*.tar.gz; do tar xzf "$t" -C "$OUT/sdist"; done
cp -R "$OUT/sdist/tos-2.9.3/tos" "$STAGE/python_deps/"
cp -R "$OUT/sdist/crcmod-1.7/python3/crcmod" "$STAGE/python_deps/"
rm -f "$STAGE/python_deps/crcmod/test.py"
echo "[build] vendored tos 2.9.3 and crcmod 1.7 (pure Python)"

cat > "$STAGE/run.sh" <<'EOF'
#!/usr/bin/env bash
# veFaaS startup command: bash run.sh   (the code directory is read-only: never chmod, never write here)
set -e
cd "$(dirname "$0")"
export PYTHONPATH="$PWD/python_deps:$PWD/ui/server${PYTHONPATH:+:$PYTHONPATH}"
export UI_STATIC_DIR="${UI_STATIC_DIR:-$PWD/ui/web_out}"
export UI_DATA_DIR="${UI_DATA_DIR:-/tmp/ad-replicator/jobs}"
export UI_DOWNLOAD_MAX_BYTES="${UI_DOWNLOAD_MAX_BYTES:-600000}"
# list-price cost per job is shown (set UI_SHOW_COST=0 on the function to hide every amount)
export UI_SHOW_COST="${UI_SHOW_COST:-1}"
# jobs started before this package was built are shipped as showcase copies or left out (their session files expire)
export UI_DISCOVER_AFTER="${UI_DISCOVER_AFTER:-__BUILD_TIME__}"
mkdir -p "$UI_DATA_DIR"
# caption editor: the code folder is read-only and ZIP extraction may drop the execute bit, so run ffmpeg from /tmp
FF_SRC=$(ls python_deps/imageio_ffmpeg/binaries/ffmpeg-linux-* 2>/dev/null | head -1)
if [ -n "$FF_SRC" ] && [ -z "${IMAGEIO_FFMPEG_EXE:-}" ]; then
  cp "$FF_SRC" /tmp/ffmpeg && chmod +x /tmp/ffmpeg && export IMAGEIO_FFMPEG_EXE=/tmp/ffmpeg
fi
exec python3 -m uvicorn main:app --app-dir ui/server --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips '*'
EOF

# DISCOVER_AFTER (ISO time) keeps sessions started before this build on the job list, e.g. runs still under review
sed -i.bak "s/__BUILD_TIME__/${DISCOVER_AFTER:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}/" "$STAGE/run.sh" && rm -f "$STAGE/run.sh.bak"
rm -f "$OUT/ad-replicator-vefaas.zip"
(cd "$STAGE" && zip -qr "$OUT/ad-replicator-vefaas.zip" . -x '*/__pycache__/*' '*.pyc')
echo "[build] $(du -h "$OUT/ad-replicator-vefaas.zip" | cut -f1) $OUT/ad-replicator-vefaas.zip"
