#!/usr/bin/env bash
# 开发模式:后端自动重载(8000)+ 前端热更新(5173,/api 代理到后端)
set -euo pipefail
cd "$(dirname "$0")/.."
trap 'kill 0' EXIT

./.venv/bin/uvicorn app.asgi:app --app-dir backend --reload --port 8000 &
(cd frontend && npm run dev) &
wait
