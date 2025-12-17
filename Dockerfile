# syntax=docker/dockerfile:1

# ------------------------------------------------------------
# SecurityVision backend (FastAPI) — dev/prod multi-stage image
#
# Targets:
#   - dev : hot-reload (use with docker-compose + bind-mount)
#   - prod: runtime-only (smaller, safer)
# ------------------------------------------------------------

    FROM python:3.11-slim AS builder

    ENV PYTHONDONTWRITEBYTECODE=1 \
        PYTHONUNBUFFERED=1
    
    WORKDIR /app
    
    # System deps for building wheels (asyncpg/cryptography/etc.)
    RUN apt-get update \
     && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
     && rm -rf /var/lib/apt/lists/*
    
    COPY requirements.txt ./
    
    # Install Python deps into an isolated venv we can copy to runtime
    RUN python -m venv /venv \
     && /venv/bin/pip install --upgrade pip \
     && /venv/bin/pip install --no-cache-dir -r requirements.txt
    
    
    FROM python:3.11-slim AS prod
    
    ENV PYTHONDONTWRITEBYTECODE=1 \
        PYTHONUNBUFFERED=1 \
        PATH="/venv/bin:$PATH"
    
    WORKDIR /app
    
    # Runtime libs only
    RUN apt-get update \
     && apt-get install -y --no-install-recommends libpq5 curl \
     && rm -rf /var/lib/apt/lists/*
    
    COPY --from=builder /venv /venv
    COPY . .
    
    RUN chmod +x ./docker/entrypoint.sh
    
    RUN adduser --disabled-password --gecos '' appuser \
     && chown -R appuser:appuser /app
    
    USER appuser
    
    EXPOSE 8000
    
    ENTRYPOINT ["./docker/entrypoint.sh"]
    CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
    
    
    FROM prod AS dev
    CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--reload"]
    