# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# gcc is needed only if any dep lacks a pre-built wheel (e.g. on ARM).
# asyncpg and argon2-cffi both ship binary wheels for amd64/arm64, so this
# is a safety net rather than a strict requirement.
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

# --- dependency layer (cached as long as pyproject.toml doesn't change) ---
COPY pyproject.toml .
# Stub __init__.py so pip can resolve the package metadata without the real source.
RUN mkdir -p src/life_dashboard && touch src/life_dashboard/__init__.py

RUN python -m venv /venv && \
    /venv/bin/pip install --no-cache-dir --upgrade pip && \
    /venv/bin/pip install --no-cache-dir .

# --- application layer (rebuilds only when source changes) ---
COPY src/ src/
# Reinstall the package itself (deps already in venv; --no-deps skips re-downloading them).
RUN /venv/bin/pip install --no-cache-dir --no-deps .


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# asyncpg speaks the Postgres wire protocol directly — no libpq needed.
# No extra apt packages required.

RUN useradd --create-home --shell /bin/bash appuser
WORKDIR /app

COPY --chown=appuser:appuser --from=builder /venv /venv
COPY --chown=appuser:appuser alembic.ini .
COPY --chown=appuser:appuser migrations/ migrations/

ENV PATH="/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Port is documented here; the actual bind comes from the HOST/PORT env vars
# passed in docker-compose.yml (or the defaults in settings.py).
EXPOSE 8000

# Run as non-root.
USER appuser

# NOTE: Alembic migrations are intentionally NOT run here. Run them as a
# one-off command before deploying a new image:
#   docker compose run --rm api alembic upgrade head
CMD ["uvicorn", "life_dashboard.main:app", "--host", "0.0.0.0", "--port", "8000"]
