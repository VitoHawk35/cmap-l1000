#!/bin/bash
set -euo pipefail

APP_DIR="/home/keji/cmap"
cd "$APP_DIR"

# 先停止旧服务
"$APP_DIR/stop_all.sh" >/dev/null 2>&1 || true
sleep 1

HTTPS_CERT="${HTTPS_CERT:-$APP_DIR/certs/cmap.crt}"
HTTPS_KEY="${HTTPS_KEY:-$APP_DIR/certs/cmap.key}"

if [ -f "$HTTPS_CERT" ] && [ -f "$HTTPS_KEY" ]; then
  PROTOCOL="https"
else
  PROTOCOL="http"
fi

# 启动后端 API（使用 start.sh，支持 PID/日志/HTTPS）
"$APP_DIR/start.sh"

# 启动前端（后台 screen）
screen -dmS cmap-web python3 -m http.server 8081

echo "========================================"
echo "服务已成功启动！"
echo "后端 API: ${PROTOCOL}://10.39.15.238:8001"
echo "前端页面: http://10.39.15.238:8081"
echo "========================================"
