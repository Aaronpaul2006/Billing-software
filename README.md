# Construction Billing Platform

Multi-tenant cloud billing and business management for construction companies
and contractors in India: quotations, GST invoices, RA bills, retention, TDS,
payments, expenses, and a consolidated owner dashboard on web and mobile.

**Status:** backend through Phase 3 (billing, payments, reports, RA bills, retention, TDS);
web app in progress. See [PROGRESS.md](PROGRESS.md).

## Documentation

- [Architecture](docs/01-architecture.md): stack, multi-tenancy, security, roadmap
- [API design](docs/02-api-design.md): REST conventions and endpoints
- [Database schema](db/schema.sql): PostgreSQL data model with Row-Level Security

## Stack

Python · Django + Django REST Framework · PostgreSQL · Celery + Redis · S3-compatible storage
· Web: React + TypeScript (Vite), Tailwind + shadcn/ui, TanStack Query

## Local services

```bash
cp .env.example .env        # local-dev placeholders; .env is gitignored
docker compose up -d --wait  # Postgres :5433, Redis :6380, S3 (SeaweedFS) :8333, Mailpit :1025 / UI :8025
```

## Backend

```bash
cd backend
uv sync
uv run python scripts/bootstrap_db.py           # roles: billing_owner / billing_app
uv run python manage.py migrate --database=owner
uv run pytest
uv run python manage.py runserver   # http://127.0.0.1:8000/healthz, /api/v1/docs/
```

## Web app

```bash
cd web
npm ci
npm run dev        # http://localhost:5173 ; /api is proxied to the backend on 127.0.0.1:8000
npm test           # Vitest + Testing Library, API mocked with MSW
npm run lint && npm run typecheck && npm run build
```

After an API change: regenerate `backend/openapi.json`
(`DJANGO_SETTINGS_MODULE=config.settings.test uv run python manage.py spectacular --format openapi-json --file openapi.json`
in `backend/`), then `npm run gen:api` in `web/`. CI fails if either is stale.

## Running the whole backend in Docker

```bash
docker compose --profile app up -d --build   # + api (http://127.0.0.1:8000), Celery worker and beat
docker compose --profile app run --rm api python manage.py migrate --database=owner
docker compose --profile app run --rm api python manage.py setup_storage   # bucket + CORS for uploads
docker compose --profile app run --rm api pytest   # incl. real PDF rendering (WeasyPrint)
docker compose --profile scan up -d clamav   # optional virus scanner; then CLAMD_HOST in .env
```

Running the API on the host instead (`manage.py runserver`): set
`CELERY_TASK_ALWAYS_EAGER=true` in `.env` so emails, PDFs and upload checks run
without a worker.

## Running the schema checks

```bash
cd db/tests
npm install
npm test
```
