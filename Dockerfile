# One image, one Cloud Run service: FastAPI serves the API and the built
# frontend on the same origin (backend/app/core/spa.py). The same image runs
# migrations as a Cloud Run job (infra/gcp/README.md).

# --- frontend build -------------------------------------------------------
FROM node:24-slim AS frontend
WORKDIR /src/frontend
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
# Empty base URL: the browser calls the API on the page's own origin.
RUN VITE_API_BASE_URL= pnpm build

# --- runtime --------------------------------------------------------------
FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY backend/pyproject.toml backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/app ./app
# Editable, no deps (they are pinned above): `app` resolves to /app/app only.
RUN pip install --no-deps -e .
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./
COPY --from=frontend /src/frontend/dist ./static

RUN useradd --system --uid 10001 --home-dir /app paint \
    && mkdir -p /data/raw && chown paint /data/raw
USER paint

ENV ENV=production \
    STATIC_DIR=/app/static \
    RAW_STORE_DIR=/data/raw \
    API_DOCS_ENABLED=false \
    PORT=8080
EXPOSE 8080
# --proxy-headers: Cloud Run terminates TLS; trust its X-Forwarded-* headers.
# Graceful shutdown inside Cloud Run's 10 s SIGTERM window.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*' --timeout-graceful-shutdown 8 --no-server-header"]
