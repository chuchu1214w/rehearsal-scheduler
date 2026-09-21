# 舞团排练排程系统:一个镜像同时包含后端与已构建的前端。
# 数据库放在 /data(挂持久卷),对外端口 8000。
#
# 第一步:构建前端
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 第二步:后端运行环境
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATABASE_URL=sqlite:////data/app.db \
    FRONTEND_DIST=/srv/frontend/dist \
    APP_TIMEZONE=Asia/Seoul \
    PORT=8000
WORKDIR /srv
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/app backend/app
COPY backend/solver backend/solver
RUN pip install ./backend
COPY --from=web /web/dist frontend/dist
COPY scripts/backup.py scripts/seed_demo.py scripts/
RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"
CMD ["sh", "-c", "uvicorn app.asgi:app --app-dir backend --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
