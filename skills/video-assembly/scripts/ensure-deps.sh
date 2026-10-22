#!/usr/bin/env bash
# Install the video-assembly dependencies only if they are missing: pillow + imageio-ffmpeg via pip,
# and the Noto Color Emoji font via apt (HTTPS mirror; plain HTTP is blocked in the sandbox) so captions
# can carry the emoji the client's ads use. The emoji font is optional: captions render without it.
set -u
log() { echo "[ensure-deps] $*" >&2; }
EMOJI=/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf

if ! python3 -c "import PIL, imageio_ffmpeg" 2>/dev/null; then
  if ! timeout 180 pip install --quiet --root-user-action=ignore pillow imageio-ffmpeg </dev/null; then
    echo '{"ok": false, "error": "pip install of pillow/imageio-ffmpeg failed or timed out after 180 s"}'
    exit 1
  fi
fi

if [ ! -f "$EMOJI" ]; then
  log "install Noto Color Emoji via HTTPS apt mirror"
  for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list; do
    [ -f "$f" ] && sed -i 's|http://archive.ubuntu.com|https://mirrors.edge.kernel.org|g; s|http://security.ubuntu.com|https://mirrors.edge.kernel.org|g' "$f"
  done
  timeout 180 apt-get -o Acquire::https::Timeout=20 -o Acquire::Retries=0 -qq update </dev/null >/dev/null 2>&1 || log "apt update failed; captions will render without emoji"
  DEBIAN_FRONTEND=noninteractive timeout 240 apt-get -qq install -y fonts-noto-color-emoji </dev/null >/dev/null 2>&1 || log "emoji font install failed; captions will render without emoji"
fi

python3 - <<'EOF'
import json, os
import imageio_ffmpeg
emoji = os.path.isfile("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf")
print(json.dumps({"ok": True, "ffmpeg": imageio_ffmpeg.get_ffmpeg_exe(), "emoji_font": emoji,
                  "note": None if emoji else "Noto Color Emoji missing: emoji in captions are skipped"}))
EOF
