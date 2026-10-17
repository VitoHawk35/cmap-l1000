#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/keji/cmap"
PID_FILE="$APP_DIR/.cmap-api.pid"
LOG_FILE="$APP_DIR/cmap-api.log"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8001}"
HTTPS_CERT="${HTTPS_CERT:-$APP_DIR/certs/cmap.crt}"
HTTPS_KEY="${HTTPS_KEY:-$APP_DIR/certs/cmap.key}"

cd "$APP_DIR"
source /home/keji/miniconda3/etc/profile.d/conda.sh
conda activate cmap

if [ -f "$PID_FILE" ]; then
  OLD_PID="$(cat "$PID_FILE")"
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "cmap-api 已在运行，PID: $OLD_PID"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

HTTPS_ARGS=""
if [ -f "$HTTPS_CERT" ] && [ -f "$HTTPS_KEY" ]; then
  HTTPS_ARGS="--certfile $HTTPS_CERT --keyfile $HTTPS_KEY"
  PROTOCOL="https"
  echo "使用 HTTPS 证书: $HTTPS_CERT"
else
  PROTOCOL="http"
  echo "未找到 HTTPS 证书，使用 HTTP"
fi

echo "启动 cmap-api: $PROTOCOL://$HOST:$PORT"
nohup gunicorn -w 1 --threads 8 -k uvicorn.workers.UvicornWorker \
  --bind "$HOST:$PORT" \
  --timeout 900 \
  --keep-alive 60 \
  $HTTPS_ARGS \
  app.main:app > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
echo "已后台启动，PID: $(cat "$PID_FILE")"
echo "日志文件: $LOG_FILE"
