.PHONY: migrate setup db db-down contracts check check-server check-web test e2e dev-server dev-web progress

setup:            ## install everything
	cd server && uv sync
	cd web && pnpm install

DB_NAME := boardnotes-db
CONTAINER ?= $(shell command -v podman >/dev/null 2>&1 && echo podman || echo docker)

db:               ## start local Postgres on :5433 (schema loads from supabase/migrations on first start)
	@$(CONTAINER) start $(DB_NAME) >/dev/null 2>&1 || $(CONTAINER) run -d --name $(DB_NAME) \
		-e POSTGRES_USER=boardnotes -e POSTGRES_PASSWORD=boardnotes -e POSTGRES_DB=boardnotes \
		-p 5433:5432 -v $(CURDIR)/supabase/migrations:/docker-entrypoint-initdb.d:ro,Z docker.io/library/postgres:16 >/dev/null
	@until $(CONTAINER) exec $(DB_NAME) pg_isready -U boardnotes >/dev/null 2>&1; do sleep 1; done; echo "Postgres ready on localhost:5433"

db-down:          ## stop and delete the local database
	-$(CONTAINER) rm -f $(DB_NAME)

migrate:          ## apply pending migrations to DATABASE_URL (add ENV=SUPABASE_DATABASE_URL for the hosted db)
	uv run --project server python scripts/migrate.py --env $(or $(ENV),DATABASE_URL)

contracts:        ## regenerate JSON schemas + web TypeScript types from server/app/contracts
	cd server && uv run python ../scripts/export_contracts.py
	cd web && rm -rf src/contracts && mkdir -p src/contracts && pnpm -s types

check: check-server check-web  ## what every task must pass before review
	@git diff --quiet -- contracts web/src/contracts || (echo "Contracts out of date: run 'make contracts' and commit" && exit 1)

check-server:
	cd server && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q -m "not live"

check-web:
	cd web && pnpm -s typecheck && pnpm -s lint && pnpm -s test

e2e:              ## browser tests: real API (fake models, throwaway db) on :8010 + web on :3010 (needs `make db`)
	cd web && pnpm exec playwright install chromium && pnpm -s test:e2e

dev-server:
	cd server && uv run uvicorn app.main:app --reload --port 8000

dev-web:
	cd web && pnpm dev

progress:         ## print task progress from orchestration/tasks.json
	@python3 scripts/progress.py
