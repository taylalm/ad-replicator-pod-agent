#!/usr/bin/env bash
# Install the ugc-video-analyzer dependencies only if they are missing.
# Uses pip only: apt is unreliable in the Managed Agents sandbox (plain HTTP is blocked).
set -u
if python3 -c "import PIL, imageio_ffmpeg" 2>/dev/null; then
  echo '{"ok": true, "installed": false, "message": "pillow and imageio-ffmpeg already present"}'
  exit 0
fi
if ! timeout 180 pip install --quiet --root-user-action=ignore pillow imageio-ffmpeg </dev/null; then
  echo '{"ok": false, "error": "pip install of pillow/imageio-ffmpeg failed or timed out after 180 s"}'
  exit 1
fi
python3 -c "import PIL, imageio_ffmpeg; print('{\"ok\": true, \"installed\": true, \"ffmpeg\": \"' + imageio_ffmpeg.get_ffmpeg_exe() + '\"}')"
