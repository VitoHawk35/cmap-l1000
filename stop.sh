#!/bin/bash
echo "正在停止 CMap 服务..."

# 1. 关闭 Screen 会话
screen -S cmap-api -X quit 2>/dev/null
screen -S cmap-web -X quit 2>/dev/null

# 2. 强制清理端口进程 (兜底)
pkill -f "gunicorn.*8001" 2>/dev/null
pkill -f "python -m http.server 8081" 2>/dev/null

# 也可以用更精准的端口查杀
lsof -ti:8001 | xargs kill -9 2>/dev/null
lsof -ti:8081 | xargs kill -9 2>/dev/null

echo "服务已停止。"
screen -wipe 2>/dev/null
