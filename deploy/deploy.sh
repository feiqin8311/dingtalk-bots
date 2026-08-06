#!/usr/bin/env bash
# Deploy dingtalk-bots to the server.
#
# Default (code-only): rsync source + restart container  (~seconds, no pip)
# Full rebuild:        ./deploy/deploy.sh --rebuild     (when requirements.txt changes)
#
# Usage:
#   ./deploy/deploy.sh
#   ./deploy/deploy.sh --rebuild
#   DEPLOY_HOST=x.x.x.x DEPLOY_PATH=/yida/dingtalk-bots ./deploy/deploy.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/deploy/deploy.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source "$ROOT/deploy/deploy.env"
  set +a
fi

DEPLOY_HOST="${DEPLOY_HOST:-121.41.4.126}"
DEPLOY_USER="${DEPLOY_USER:-root}"
DEPLOY_PATH="${DEPLOY_PATH:-/yida/dingtalk-bots}"
BUILD_HTTP_PROXY="${BUILD_HTTP_PROXY:-http://172.17.0.1:20171}"
BUILD_HTTPS_PROXY="${BUILD_HTTPS_PROXY:-http://172.17.0.1:20171}"
BUILD_NO_PROXY="${BUILD_NO_PROXY:-localhost,127.0.0.1}"
REBUILD=0
for arg in "$@"; do
  case "$arg" in
    --rebuild|-r) REBUILD=1 ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
  esac
done

SSH_BASE=(ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15)
RSYNC_SSH="ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15"
if [[ -n "${DEPLOY_SSH_PASS:-}" ]] && command -v sshpass >/dev/null 2>&1; then
  export SSHPASS="$DEPLOY_SSH_PASS"
  SSH_BASE=(sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15)
  RSYNC_SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15"
fi

remote() {
  "${SSH_BASE[@]}" "${DEPLOY_USER}@${DEPLOY_HOST}" "$@"
}

echo "==> rsync -> ${DEPLOY_USER}@${DEPLOY_HOST}:${DEPLOY_PATH}"
rsync -az --delete \
  --exclude '.git/' \
  --exclude '.codegraph/' \
  --exclude '.DS_Store' \
  --exclude '**/__pycache__/' \
  --exclude '**/*.pyc' \
  --exclude '.env' \
  --exclude '**/.env' \
  --exclude '**/.env.*' \
  --exclude '**/downloads/' \
  --exclude '**/.bot-workspace/' \
  --exclude 'apps/logistics_bot/.state/' \
  --exclude 'apps/lcl_bot/Excel_Files/' \
  --exclude 'apps/lcl_bot/Workflow_State/' \
  --exclude 'apps/track_notify/.state/' \
  --exclude 'apps/pinxiang_bot/output/' \
  --exclude 'files/*.xlsx' \
  --exclude 'deploy/deploy.env' \
  -e "$RSYNC_SSH" \
  "$ROOT/" \
  "${DEPLOY_USER}@${DEPLOY_HOST}:${DEPLOY_PATH}/"

echo "==> ensure runtime dirs"
remote "mkdir -p \
  '${DEPLOY_PATH}/apps/logistics_bot/.state' \
  '${DEPLOY_PATH}/apps/cp_bot/downloads' \
  '${DEPLOY_PATH}/apps/split_bot/.bot-workspace' \
  '${DEPLOY_PATH}/apps/pinxiang_bot/.bot-workspace' \
  '${DEPLOY_PATH}/apps/lcl_bot/Excel_Files' \
  '${DEPLOY_PATH}/apps/lcl_bot/Workflow_State' \
  '${DEPLOY_PATH}/apps/track_notify/.state' \
  '${DEPLOY_PATH}/files'"

if [[ "$REBUILD" -eq 1 ]]; then
  echo "==> rebuild image (proxy ${BUILD_HTTP_PROXY})"
  remote "cd '${DEPLOY_PATH}' && \
    export BUILD_HTTP_PROXY='${BUILD_HTTP_PROXY}' \
           BUILD_HTTPS_PROXY='${BUILD_HTTPS_PROXY}' \
           BUILD_NO_PROXY='${BUILD_NO_PROXY}' && \
    docker compose build dingtalk-bot && \
    docker compose up -d --force-recreate dingtalk-bot && \
    docker compose rm -f -s dingtalk-track-notify 2>/dev/null || true"
else
  echo "==> restart (source mounts, no rebuild)"
  remote "cd '${DEPLOY_PATH}' && docker compose up -d --force-recreate --no-build dingtalk-bot && \
    docker compose rm -f -s dingtalk-track-notify 2>/dev/null || true"
fi

echo "==> health"
remote "docker ps --filter name=^dingtalk-bot\$ --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}' && \
  docker logs --tail 8 dingtalk-bot && \
  docker exec dingtalk-bot python -c \"from pathlib import Path; r=Path('/app/apps/logistics_bot/router.py').read_text(); p=Path('/app/apps/pinxiang_bot/packing.py').read_text(); assert '_BRANCH_STATE_PATH' in r; assert '拼箱数据' in p; print('code_ok')\""

echo "==> done"
