# Stage 1: Build React + TypeScript + Vite frontend bundle
FROM node:22-alpine AS web-builder
WORKDIR /build/web

COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
RUN npm run build

# Stage 2: Python 3.12 runtime with FastAPI, NumPy & Numba
FROM python:3.12-slim
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

# Install package and runtime dependencies
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Copy built frontend static assets
COPY --from=web-builder /build/web/dist ./web/dist

EXPOSE 8000

CMD ["python", "-m", "market_tracker.api.app"]

