# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    DJANGO_ENV=prod

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 lyneci \
    && useradd --uid 10001 --gid 10001 --no-log-init --create-home lyneci

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=lyneci:lyneci . /app

RUN mkdir -p /app/media /app/staticfiles \
    && chown -R lyneci:lyneci /app/media /app/staticfiles \
    && FERNET_SECRET_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
       SECRET_KEY="build-only-secret-key-not-used-at-runtime-000000000000000000000000" \
       DJANGO_SETTINGS_MODULE=leoTrade.settings.test \
       python manage.py collectstatic --noinput

USER lyneci

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/health/live/ || exit 1

CMD ["uvicorn", "leoTrade.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers", "--forwarded-allow-ips=*"]
