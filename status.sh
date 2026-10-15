#!/bin/bash
set -euo pipefail

APP_DIR="/home/keji/cmap"
HTTPS_CERT="${HTTPS_CERT:-$APP_DIR/certs/cmap.crt}"
HTTPS_KEY="${HTTPS_KEY:-$APP_DIR/certs/cmap.key}"
PID_FILE="$APP_DIR/.cmap-api.pid"

if [ -f "$HTTPS_CERT" ] && [ -f "$HTTPS_KEY" ]; then
  API_PROTOCOL="https"
else
  API_PROTOCOL="http"
fi

echo "========================================"
echo "       CMap 服务状态监控"
echo "========================================"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

check_api() {
  local port=8001
  local pid_running=0
  local pid=""
  if [ -f "$PID_FILE" ]; then
    pid="$(cat "$PID_FILE")"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      pid_running=1
    fi
  fi
  local port_listen
  port_listen=$(lsof -ti:${port} 2>/dev/null | wc -l)

  if [ "$pid_running" -eq 1 ] && [ "$port_listen" -gt 0 ]; then
    echo -e "[${GREEN}OK${NC}] cmap-api: 运行中 (Port ${port}, PID ${pid})"
  else
    echo -e "[${RED}OFF${NC}] cmap-api: 未运行"
  fi
}

check_web() {
  local port=8081
  local screen_present
  screen_present=$(screen -ls | grep -c "cmap-web" || true)
  local port_listen
  port_listen=$(lsof -ti:${port} 2>/dev/null | wc -l)

  if [ "$screen_present" -gt 0 ] && [ "$port_listen" -gt 0 ]; then
    echo -e "[${GREEN}OK${NC}] cmap-web: 运行中 (Port ${port})"
  else
    echo -e "[${RED}OFF${NC}] cmap-web: 未运行"
  fi
}

check_api
check_web

echo "========================================"
echo "后端 API: ${API_PROTOCOL}://10.39.15.238:8001"
echo "前端页面: http://10.39.15.238:8081"
echo "========================================"
