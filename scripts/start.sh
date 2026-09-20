#!/usr/bin/env bash
# 本机一键启动:准备 Python 环境 → 构建前端(首次或 REBUILD=1)→ 启动后端(同时托管前端)
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  echo "▶ 创建 Python 虚拟环境 .venv"
  python3 -m venv .venv
fi
echo "▶ 安装 / 更新后端依赖"
./.venv/bin/pip install -q -e "backend[dev]"

if [ ! -f frontend/dist/index.html ] || [ "${REBUILD:-0}" = "1" ]; then
  echo "▶ 构建前端(需要 Node.js)"
  (cd frontend && npm install --no-audit --no-fund && npm run build)
fi

PORT="${PORT:-8000}"
echo
echo "✅ 启动完成:在浏览器打开 http://localhost:${PORT}"
echo "   同一 Wi-Fi 的成员可访问 http://<你的电脑局域网地址>:${PORT}"
echo "   按 Ctrl+C 停止"
echo
exec ./.venv/bin/uvicorn app.asgi:app --app-dir backend --host "${HOST:-0.0.0.0}" --port "${PORT}"

