.PHONY: setup services db sandbox-image api worker web dev test lint check-seeds offline

setup:            ## install backend + frontend dependencies
	cd backend && uv sync
	cd frontend && npm install
	@test -f backend/.env || cp .env.example backend/.env

services:         ## start Postgres + Mailpit
	docker compose up -d --wait

db: services      ## apply migrations and seed the curriculum
	cd backend && uv run alembic upgrade head && uv run python -m app.cli seed

sandbox-image:    ## build the isolated code-execution image
	docker build -t ai-academy-sandbox:latest backend/sandbox

api:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

worker:
	cd backend && uv run python -m app.worker

web:
	cd frontend && npm run dev

dev:              ## API + worker + web in one terminal (Ctrl-C stops all)
	$(MAKE) -j3 api worker web

offline:          ## run everything on SQLite with the offline AI provider and unsafe local sandbox (no Docker, no API key)
	mkdir -p backend/var
	cd backend && DATABASE_URL=sqlite:///./var/offline.db uv run alembic upgrade head && DATABASE_URL=sqlite:///./var/offline.db uv run python -m app.cli seed
	DATABASE_URL=sqlite:///./var/offline.db AI_PROVIDER=fake SANDBOX_BACKEND=unsafe-local SANDBOX_ALLOW_UNSAFE_LOCAL=true EMAIL_PROVIDER=console $(MAKE) -j3 api worker web

test:
	cd backend && uv run pytest -q
	cd frontend && npx tsc --noEmit && npx eslint src

lint:
	cd backend && uv run ruff check app tests
	cd frontend && npx eslint src

check-seeds:      ## validate seed lessons and run every reference solution against its tests
	cd backend && SANDBOX_BACKEND=unsafe-local SANDBOX_ALLOW_UNSAFE_LOCAL=true uv run python -m app.cli check-seeds
