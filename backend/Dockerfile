# Backend image: the API (Django), the Celery worker and beat.
#   docker compose --profile app up -d --build      (local: runs runserver instead)
# Production builds pass --build-arg UV_SYNC_ARGS=--no-dev (deploy/docker-compose.prod.yml).
FROM python:3.14.8-slim-trixie

ARG UV_SYNC_ARGS=""
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    XDG_CACHE_HOME=/tmp/cache \
    PATH=/opt/venv/bin:$PATH

# WeasyPrint lays out text with Pango; DejaVu fonts include the rupee sign (₹).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv

WORKDIR /app
# Dependencies first (cached layer), exactly as locked.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-install-project $UV_SYNC_ARGS

# Fontconfig (used by WeasyPrint) needs a writable cache; the app user has no home.
ENV XDG_CACHE_HOME=/tmp/cache
COPY . .
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
USER app

ARG RELEASE=dev
ENV RELEASE=$RELEASE
EXPOSE 8000
CMD ["gunicorn", "-c", "config/gunicorn_conf.py", "config.wsgi"]
