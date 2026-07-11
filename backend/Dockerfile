FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system deps needed by asyncpg / bcrypt
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl \
    && rm -rf /var/lib/apt/lists/*

# ── Dependencies ────────────────────────────────────────────────────────────
FROM base AS deps

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

# ── Production image ─────────────────────────────────────────────────────────
FROM deps AS production

COPY . .

RUN addgroup --system forgeai && adduser --system --ingroup forgeai forgeai
USER forgeai

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["sh", "-c", "python -m alembic upgrade head && exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
