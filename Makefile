.PHONY: setup db db-down contracts check check-server check-web test dev-server dev-web progress

setup:            ## install everything
	cd server && uv sync
	cd web && pnpm install

db:               ## start local Postgres (schema loads from supabase/migrations on first start)
	docker compose up -d --wait db

db-down:
	docker compose down -v

contracts:        ## regenerate JSON schemas + web TypeScript types from server/app/contracts
	cd server && uv run python ../scripts/export_contracts.py
	cd web && rm -rf src/contracts && mkdir -p src/contracts && pnpm -s types

check: check-server check-web  ## what every task must pass before review
	@git diff --quiet -- contracts web/src/contracts || (echo "Contracts out of date: run 'make contracts' and commit" && exit 1)

check-server:
	cd server && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q -m "not live"

check-web:
	cd web && pnpm -s typecheck && pnpm -s lint

dev-server:
	cd server && uv run uvicorn app.main:app --reload --port 8000

dev-web:
	cd web && pnpm dev

progress:         ## print task progress from orchestration/tasks.json
	@python3 scripts/progress.py
