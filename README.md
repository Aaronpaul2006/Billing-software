# Construction Billing Platform

Multi-tenant cloud billing and business management for construction companies
and contractors in India: quotations, GST invoices, RA bills, retention, TDS,
payments, expenses, and a consolidated owner dashboard on web and mobile.

**Status:** design complete, backend scaffolding next. See [PROGRESS.md](PROGRESS.md).

## Documentation

- [Architecture](docs/01-architecture.md): stack, multi-tenancy, security, roadmap
- [API design](docs/02-api-design.md): REST conventions and endpoints
- [Database schema](db/schema.sql): PostgreSQL data model with Row-Level Security

## Stack

Python · Django + Django REST Framework · PostgreSQL · Celery + Redis · S3-compatible storage

## Local services

```bash
cp .env.example .env        # local-dev placeholders; .env is gitignored
docker compose up -d --wait  # Postgres :5433, Redis :6380, S3 (SeaweedFS) :8333, Mailpit :1025 / UI :8025
```

## Backend

```bash
cd backend
uv sync
uv run pytest
uv run python manage.py runserver   # http://127.0.0.1:8000/healthz, /api/v1/docs/
```

## Running the schema checks

```bash
cd db/tests
npm install
npm test
```
