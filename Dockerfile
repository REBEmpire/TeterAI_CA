# ── Stage 1: Build React frontend ─────────────────────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /app/src/ui/web
COPY src/ui/web/package*.json ./
RUN npm ci
COPY src/ui/web/ ./
RUN npm run build

# ── Stage 2: Python runtime ────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime
WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install Python dependencies (no dev extras, frozen lockfile)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application source
COPY src/ src/
COPY main.py ./

# Copy compiled React app from stage 1
# server.py resolves: Path(__file__).parent.parent / "web" / "dist" → src/ui/web/dist/
COPY --from=frontend /app/src/ui/web/dist/ src/ui/web/dist/

# src/ must be on the path for absolute imports (e.g. "from ui.api.server import app")
ENV PYTHONPATH=/app/src

# Cloud Run injects PORT (default 8080); bind to all interfaces
ENV PORT=8080

CMD uvicorn main:app --host 0.0.0.0 --port $PORT
