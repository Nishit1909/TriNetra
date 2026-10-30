# TriNetra (SIH26189): one container serves the built React frontend and the FastAPI API.

# ---- 1. build the frontend ----
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. runtime ----
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY backend/requirements-live.txt backend/requirements-live.txt
RUN pip install -r backend/requirements-live.txt
COPY backend/ backend/
COPY analysis_model/ analysis_model/
COPY --from=web /web/dist frontend/dist
RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app
WORKDIR /app/backend
ENV PORT=8080
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'
