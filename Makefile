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

export PYTHONPATH := .:services/hl:services/vault:services/engine:services/discovery:services/api

.PHONY: help install dev test eval openapi up down mcp-install

help: ## list targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'

install: ## python venv (uv) + web deps (npm ci)
	@command -v uv >/dev/null || { echo "uv not found: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
	test -d .venv || uv venv --python 3.13 .venv
	VIRTUAL_ENV=.venv uv pip install -r pyproject.toml --extra dev
	cd $(WEB_DIR) && npm ci

dev: ## api + engine + scout + web together; Ctrl-C stops all four
	@test -f .env || echo "warning: no .env (copy .env.example). The engine exits without COPYCAT_ACCOUNT_ADDRESS unless you add an account in the web UI."
	@trap 'kill $$(jobs -p) 2>/dev/null; wait' INT TERM EXIT; \
	$(PY) -m api & \
	$(PY) -m engine & \
	env -u COPYCAT_AGENT_KEY COPYCAT_HL_PRIORITY=background $(PY) -m discovery.scout serve & \
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

up: ## docker compose up (api, engine, scout, web)
	docker compose up -d --build

down: ## docker compose down
	docker compose down

mcp-install: ## print (or with RUN=1, run) the `claude mcp add` command and install the /copycat-thesis slash command
	@echo 'claude mcp add copycat -s user -- $(CURDIR)/services/mcp/run.sh'
	@echo 'mkdir -p ~/.claude/commands && cp $(CURDIR)/services/mcp/claude/commands/copycat-thesis.md ~/.claude/commands/'
	@if [ "$(RUN)" = "1" ]; then 	  claude mcp add copycat -s user -- $(CURDIR)/services/mcp/run.sh && 	  mkdir -p $$HOME/.claude/commands && 	  cp $(CURDIR)/services/mcp/claude/commands/copycat-thesis.md $$HOME/.claude/commands/ && 	  echo "installed: copycat MCP server + /copycat-thesis"; 	else echo "(dry run; re-run with RUN=1 to execute)"; fi
