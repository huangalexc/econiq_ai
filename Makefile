# Developer entry points. Everything CI runs is runnable here unchanged.
.DEFAULT_GOAL := help
SHELL := /bin/bash

DB_URL ?= postgresql+psycopg://econiq:econiq@localhost:$(or $(ECONIQ_POSTGRES_PORT),5432)/econiq

.PHONY: help
help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Sync the workspace virtualenv
	uv sync --all-extras

.PHONY: up
up: ## Start Postgres + MinIO + Redis
	docker compose up -d
	@echo "Postgres on $${ECONIQ_POSTGRES_PORT:-5432}, MinIO console on $${ECONIQ_MINIO_CONSOLE_PORT:-9001}"

.PHONY: down
down: ## Stop the local stack (keeps volumes)
	docker compose down

.PHONY: migrate
migrate: ## Apply migrations to the local database
	cd packages/data-models && ECONIQ_DB_URL=$(DB_URL) uv run --project ../.. alembic upgrade head

.PHONY: migration
migration: ## Autogenerate a migration: make migration m="add x"
	cd packages/data-models && ECONIQ_DB_URL=$(DB_URL) uv run --project ../.. alembic revision --autogenerate -m "$(m)"

.PHONY: lint
lint: ## Ruff lint + format check
	uv run ruff check .
	uv run ruff format --check .

.PHONY: fmt
fmt: ## Apply formatting and safe lint fixes
	uv run ruff check . --fix
	uv run ruff format .

.PHONY: typecheck
typecheck: ## Strict mypy over the packages
	uv run mypy packages

.PHONY: test
test: ## Unit tests (no database required)
	uv run pytest -q -m "not integration"

.PHONY: test-integration
test-integration: ## Tests that need the compose stack
	ECONIQ_DB_URL=$(DB_URL) uv run pytest -q -m integration

.PHONY: check
check: lint typecheck test ## Everything CI runs on a pull request
