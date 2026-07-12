.PHONY: up down build dev-api dev-web test lint

# Full local stack: two containers (frontend + backend)
up:
	docker compose up --build

down:
	docker compose down

# Development without Docker
dev-api:
	cd apps/api && uv run alembic upgrade head && uv run uvicorn factory_api.main:app --reload --port 8000

dev-web:
	cd apps/web && npm run dev

test:
	uv run pytest apps/api/tests -q

lint:
	uv run ruff check .
	cd apps/web && npm run typecheck
