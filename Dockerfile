# ==============================================================================
# SentinelDispute Production Multi-Stage Dockerfile
# ==============================================================================
# Stage 1: Build & Dependency Wheel Cache
FROM python:3.11-slim AS builder

WORKDIR /build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /build/wheels -r requirements.txt

# ------------------------------------------------------------------------------
# Stage 2: Minimal Distroless / Slim Production Runtime
# ------------------------------------------------------------------------------
FROM python:3.11-slim AS runner

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENVIRONMENT=production \
    PORT=3000

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root system user & group
RUN groupadd -r sentinel && useradd -r -g sentinel -d /app -s /sbin/nologin -c "Sentinel Dispute Service User" sentinel

# Install pre-built wheels
COPY --from=builder /build/wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache /wheels/* && rm -rf /wheels

# Copy application source code
COPY --chown=sentinel:sentinel app ./app
COPY --chown=sentinel:sentinel api ./api
COPY --chown=sentinel:sentinel static ./static
COPY --chown=sentinel:sentinel pyproject.toml .

# Create writable data directory for SQLite fallback / cache
RUN mkdir -p /app/data && chown -R sentinel:sentinel /app/data
ENV SQLITE_DB_PATH=/app/data/sentinel_dispute.db

# Switch to non-privileged user
USER sentinel

# Expose HTTP port
EXPOSE 3000

# Container healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:3000/api/v1/health || exit 1

# Production Gunicorn + Uvicorn worker process manager
CMD ["gunicorn", "app.main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:3000", "--access-logfile", "-", "--error-logfile", "-"]
