#!/usr/bin/env bash
# Package each skill folder as dist/<name>-<version>.zip with exactly one top-level folder.
# Usage: tools/zip_skills.sh [version-suffix]   e.g. tools/zip_skills.sh v3
set -euo pipefail
cd "$(dirname "$0")/.."
ver="${1:-dev}"; mkdir -p dist
for d in skills/*/; do
  name=$(basename "$d"); find "$d" -name __pycache__ -prune -exec rm -rf {} +
  (cd skills && zip -qr "../dist/${name}-${ver}.zip" "$name")
  echo "dist/${name}-${ver}.zip"
done
