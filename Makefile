# Recipes start with ">" instead of a tab.
.RECIPEPREFIX = >
.DEFAULT_GOAL := help
TEST_DB ?= postgresql://chat:chat@localhost:5433/chat_test
PORT ?= 8000

help: ## List commands
> @grep -E '^[a-z-]+:.*## ' Makefile | awk -F ':.*## ' '{ printf "  make %-14s %s\n", $$1, $$2 }'

setup: ## Create .env and install backend + frontend dependencies
> @test -f .env || cp .env.example .env
> cd backend && uv sync
> cd frontend && npm install

db-up: ## Start Postgres in Docker and wait until it is healthy
> docker compose up -d --wait postgres

db-down: ## Stop Postgres (data is kept)
> docker compose down

backend: ## API on http://127.0.0.1:8000 (reloads on change)
> cd backend && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

frontend: ## UI on http://localhost:5173
> cd frontend && npm run dev

start: ## Build the UI, then serve UI + API from one server on http://127.0.0.1:$(PORT)
> cd frontend && npm run build
> cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port $(PORT)

dev: ## Backend and frontend together
> $(MAKE) -j2 backend frontend

demo: ## Try it with no Ollama, keys or database (offline model, chats in memory)
> $(MAKE) -j2 demo-backend frontend

demo-backend: ## Backend for make demo
> cd backend && DATABASE_URL= ENABLE_FAKE_MODEL=true DEFAULT_MODEL=fake:echo uv run uvicorn app.main:app --port 8000

test: ## Backend tests (in memory and against Postgres) and frontend tests
> cd backend && uv run pytest -q
> cd backend && USE_POSTGRES=1 TEST_DATABASE_URL=$(TEST_DB) uv run pytest -q
> cd frontend && npm test

lint: ## ruff, ESLint, Prettier and tsc
> cd backend && uv run ruff check . && uv run ruff format --check .
> cd frontend && npm run lint && npm run format:check && npm run typecheck

format: ## Auto-format everything
> cd backend && uv run ruff format . && uv run ruff check --fix .
> cd frontend && npm run format

.PHONY: help setup db-up db-down backend frontend start dev demo demo-backend test lint format
