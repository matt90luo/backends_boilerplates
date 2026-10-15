# Tiny SaaS backend — common developer tasks.
.DEFAULT_GOAL := help
SHELL := /bin/bash
PORT ?= 8000

.PHONY: help install migrate seed dev worker test test-integration lint format check smoke up down create-tables drop-tables

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Install (or refresh) the Python environment
	uv sync

migrate: ## Apply database migrations
	uv run alembic upgrade head

seed: ## Create the admin user, demo packages and demo services
	uv run python -m tinysaas.cli seed

dev: ## Run the API with autoreload
	uv run uvicorn main:app --reload --port $(PORT)

worker: ## Run the arq worker (async service tasks)
	uv run arq tinysaas.worker.WorkerSettings

test: ## Run the unit + API test suite (no external services needed)
	uv run pytest

test-integration: ## Run the tests that need local PostgreSQL/Redis/RustFS
	uv run pytest -m integration tests/integration

lint: ## Check style and types
	uv run ruff check src tests alembic
	uv run mypy

format: ## Format the code
	uv run ruff format src tests alembic
	uv run ruff check --fix src tests alembic

smoke: ## End-to-end smoke test against a running API (see scripts/smoke.sh)
	bash scripts/smoke.sh

up: ## Start PostgreSQL + Redis + RustFS with docker compose
	docker compose -f docker-compose.dev.yml up -d postgres redis rustfs

down: ## Stop the compose services
	docker compose -f docker-compose.dev.yml down

create-tables: ## Create tables from the ORM metadata (no Alembic)
	uv run python -m tinysaas.cli create-tables

drop-tables: ## Drop every table (destructive)
	uv run python -m tinysaas.cli drop-tables
