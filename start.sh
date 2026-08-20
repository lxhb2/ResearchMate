#!/usr/bin/env bash
# ResearchMate 科研助手 · 启动脚本（Linux / macOS）
# 首次运行会自动创建虚拟环境并安装依赖。
set -e
cd "$(dirname "$0")/backend"

# 首次运行：创建虚拟环境并安装依赖
if [ ! -d ".venv" ]; then
  echo "首次运行：创建虚拟环境并安装依赖..."
  python3 -m venv .venv
  ./.venv/bin/pip install --upgrade pip
  ./.venv/bin/pip install -r requirements.txt
fi

# 单端口托管前端（dist 中已含构建好的前端），数据存本地 SQLite
export FRONTEND_DIST="../frontend/dist"
PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
echo "============================================="
echo "ResearchMate 启动中 -> http://localhost:${PORT}/"
echo "============================================="
exec ./.venv/bin/uvicorn app.main:app --host "${HOST}" --port "${PORT}"
