# syntax=docker/dockerfile:1

# ---- 1. 构建前端 ----
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

# ---- 2. 运行环境 ----
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    MAC_IN_DOCKER=1 \
    MAC_HOST=0.0.0.0 \
    MAC_PORT=18760 \
    MAC_DATA_DIR=/data \
    MAC_CONFIG=/config/config.yaml \
    MAC_WORKSPACE=/workspace

WORKDIR /app
COPY backend/requirements.lock backend/requirements.lock
RUN pip install --no-cache-dir -r backend/requirements.lock

COPY backend/ backend/
COPY --from=web /web/dist frontend/dist
COPY config.example.yaml VERSION ./

# 以普通用户运行；数据、配置、工作目录都放在可挂载的卷里
RUN useradd --create-home --uid 1000 app \
 && mkdir -p /data /config /workspace \
 && chown -R app:app /data /config /workspace /app
USER app
VOLUME ["/data", "/workspace"]
EXPOSE 18760

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/' % os.environ.get('MAC_PORT','18760'), timeout=4)" || exit 1

CMD ["python", "backend/main.py"]
