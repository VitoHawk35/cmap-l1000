#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/keji/cmap"
PID_FILE="$APP_DIR/.cmap-api.pid"
PORT="${PORT:-8001}"
PORTS="${PORTS:-$PORT}"

stop_pid() {
  local pid="$1"
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  echo "停止 cmap-api，PID: $pid"
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 10); do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "进程未及时退出，强制停止。"
  kill -9 "$pid" 2>/dev/null || true
}

if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE")"
  if [ -n "$PID" ]; then
    stop_pid "$PID"
  fi
  rm -f "$PID_FILE"
else
  echo "未找到 PID 文件，将尝试清理占用端口 $PORTS 的 cmap-api/gunicorn 进程。"
fi

for p in $PORTS; do
  PORT_PIDS="$(lsof -ti tcp:"$p" 2>/dev/null || true)"
  if [ -n "$PORT_PIDS" ]; then
    echo "清理占用端口 $p 的残留进程: $PORT_PIDS"
    kill $PORT_PIDS 2>/dev/null || true
    sleep 1
    PORT_PIDS="$(lsof -ti tcp:"$p" 2>/dev/null || true)"
    if [ -n "$PORT_PIDS" ]; then
      kill -9 $PORT_PIDS 2>/dev/null || true
    fi
  fi
done

# 同时停止前端 http.server
screen -S cmap-web -X quit 2>/dev/null || true
pkill -f "http.server 8081" 2>/dev/null || true
PORT_8081_PIDS="$(lsof -ti:8081 2>/dev/null || true)"
if [ -n "$PORT_8081_PIDS" ]; then
  kill -9 $PORT_8081_PIDS 2>/dev/null || true
fi

echo "已停止。"
