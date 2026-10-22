#!/usr/bin/env bash
# Install Playwright + Chromium + Chromium's system libraries, only what is missing.
# The sandbox blocks plain HTTP, so apt is pointed at an HTTPS Ubuntu mirror first.
# Every step has a timeout. First run takes about 1-2 minutes; later runs in the same session are instant.
set -u
log() { echo "[ensure-deps] $*" >&2; }

can_launch() {
  timeout 60 python3 - <<'EOF' >/dev/null 2>&1
from playwright.sync_api import sync_playwright
p = sync_playwright().start(); b = p.chromium.launch(); b.close(); p.stop()
EOF
}

if python3 -c "import playwright" 2>/dev/null && can_launch; then
  echo '{"ok": true, "installed": false, "message": "Playwright and Chromium already working"}'
  exit 0
fi

if ! python3 -c "import playwright" 2>/dev/null; then
  log "pip install playwright"
  timeout 180 pip install --quiet --root-user-action=ignore playwright </dev/null \
    || { echo '{"ok": false, "error": "pip install playwright failed or timed out"}'; exit 1; }
fi

log "download Chromium"
timeout 300 python3 -m playwright install chromium </dev/null >/dev/null \
  || { echo '{"ok": false, "error": "playwright install chromium failed or timed out (cdn.playwright.dev)"}'; exit 1; }

if ! can_launch; then
  log "install Chromium system libraries via HTTPS apt mirror"
  for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list; do
    [ -f "$f" ] && sed -i 's|http://archive.ubuntu.com|https://mirrors.edge.kernel.org|g; s|http://security.ubuntu.com|https://mirrors.edge.kernel.org|g' "$f"
  done
  timeout 180 apt-get -o Acquire::https::Timeout=20 -o Acquire::Retries=0 -qq update </dev/null >/dev/null 2>&1 \
    || { echo '{"ok": false, "error": "apt-get update via HTTPS mirror failed or timed out"}'; exit 1; }
  DEBIAN_FRONTEND=noninteractive timeout 420 python3 -m playwright install-deps chromium </dev/null >/dev/null 2>&1 \
    || { echo '{"ok": false, "error": "playwright install-deps chromium failed or timed out"}'; exit 1; }
fi

if can_launch; then
  echo '{"ok": true, "installed": true, "message": "Playwright, Chromium and system libraries ready"}'
else
  echo '{"ok": false, "error": "Chromium still cannot launch after installing dependencies"}'
  exit 1
fi
