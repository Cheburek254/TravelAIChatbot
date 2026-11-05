FROM node:22-alpine AS frontend_builder

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS python_builder

WORKDIR /build
COPY ["data tools/requirements.txt", "./requirements.txt"]
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim AS runner

WORKDIR /app

RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -m -s /sbin/nologin appuser && \
    chown -R appuser:appgroup /app

COPY --from=python_builder /install /usr/local
COPY --chown=appuser:appgroup ["data tools/data/", "/app/data/"]
COPY --chown=appuser:appgroup ["data tools/src/", "/app/src/"]
COPY --chown=appuser:appgroup ["data tools/tests/", "/app/tests/"]
COPY --chown=appuser:appgroup ["data tools/main.py", "/app/main.py"]
COPY --chown=appuser:appgroup test_scenarios.json benchmark.py /app/
COPY --from=frontend_builder --chown=appuser:appgroup /frontend/dist /app/frontend_dist

ENV PYTHONUNBUFFERED=1 \
    APP_PORT=8080 \
    APP_HOST=0.0.0.0 \
    FRONTEND_DIST_DIR=/app/frontend_dist

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health').read()" || exit 1

CMD ["python3", "main.py"]
