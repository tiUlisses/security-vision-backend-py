# syntax=docker/dockerfile:1

FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements*.txt pyproject.toml poetry.lock* ./

RUN python -m venv /venv \
 && /venv/bin/pip install --upgrade pip \
 && if [ -f requirements.txt ]; then \
      /venv/bin/pip install -r requirements.txt; \
    elif [ -f poetry.lock ] || [ -f pyproject.toml ]; then \
      /venv/bin/pip install poetry \
      && poetry export --without-hashes -f requirements.txt -o /tmp/requirements.txt \
      && /venv/bin/pip install -r /tmp/requirements.txt; \
    else \
      echo 'Nenhum gerenciador de dependências suportado encontrado (requirements.txt / poetry).' && exit 1; \
    fi

FROM python:3.11-slim AS prod

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/venv/bin:$PATH"

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 curl \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /venv /venv
COPY . .

RUN chmod +x ./docker/entrypoint.sh \
 && adduser --disabled-password --gecos '' appuser \
 && mkdir -p /app/media \
 && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

ENTRYPOINT ["./docker/entrypoint.sh"]
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
