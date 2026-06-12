#!/usr/bin/env bash
set -euo pipefail

app_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo_dir="$(cd "$app_dir/../.." && pwd)"
cd "$repo_dir"

image_name="dingtalk-cp-bot:openclaw-check"
docker build --quiet --network host -f Dockerfile.cp -t "$image_name" . >/dev/null

docker run --rm --network host \
  --env-file "$app_dir/.env" \
  -e TZ=Asia/Shanghai \
  -v "$app_dir/downloads:/app/downloads" \
  -v "$app_dir/files:/app/files:ro" \
  "$image_name" \
  python openclaw_check.py "$@"
