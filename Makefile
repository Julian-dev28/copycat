# copycat: local dev, tests, evals, docker.
# Every Python entrypoint needs the same import roots as pytest (pyproject.toml).

SHELL := /bin/bash
.DEFAULT_GOAL := help

PY        ?= .venv/bin/python
WEB_DIR   := services/web
WEB_PORT  ?= 3000
# Must match COPYCAT_API_PORT in .env. Only used to point the web at the api.
API_PORT  ?= 8787
NEXT_PUBLIC_COPYCAT_API ?= http://localhost:$(API_PORT)

export PYTHONPATH := .:services/hl:services/engine:services/discovery:services/api

.PHONY: help install dev test eval openapi up down

help: ## list targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'

install: ## python venv (uv) + web deps (npm ci)
	@command -v uv >/dev/null || { echo "uv not found: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
	test -d .venv || uv venv --python 3.13 .venv
	VIRTUAL_ENV=.venv uv pip install -r pyproject.toml --extra dev
	cd $(WEB_DIR) && npm ci

dev: ## api + engine + web together; Ctrl-C stops all three
	@test -f .env || echo "warning: no .env (copy .env.example). The engine exits without COPYCAT_ACCOUNT_ADDRESS."
	@trap 'kill $$(jobs -p) 2>/dev/null; wait' INT TERM EXIT; \
	$(PY) -m api & \
	$(PY) -m engine & \
	(cd $(WEB_DIR) && NEXT_PUBLIC_COPYCAT_API=$(NEXT_PUBLIC_COPYCAT_API) exec ./node_modules/.bin/next dev -p $(WEB_PORT)) & \
	wait

test: ## gate tests: pytest + web lint, typecheck, vitest
	$(PY) -m pytest
	cd $(WEB_DIR) && npm run lint && npm run typecheck && npx vitest run

eval: ## live evals against real Hyperliquid (read-only, needs network)
	$(PY) -m pytest -m live

openapi: ## regenerate services/api/openapi.json and the web client types
	$(PY) -m api.openapi_export
	cd $(WEB_DIR) && npm run gen:api

up: ## docker compose up (api, engine, web)
	docker compose up -d --build

down: ## docker compose down
	docker compose down
