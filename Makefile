# Funciona com GNU make no Windows (cmd ou sh do Git Bash) e no Linux do CI.
# Só usa `cd dir && comando`, que vale nos dois shells.
# No Windows o docker não está no PATH: make up DOCKER="$LOCALAPPDATA/Programs/DockerDesktop/resources/bin/docker.exe"

DOCKER ?= docker
UV ?= uv
PNPM ?= corepack pnpm
API := apps/api
COMPOSE := $(DOCKER) compose -p curriculo -f docker-compose.yml

.PHONY: install lint typecheck test check up down db-check eval dev-api dev-web

install:
	cd $(API) && $(UV) sync
	$(PNPM) install
	cd $(API) && $(UV) run python -c "import pathlib; pathlib.Path('../../data/arquivos').mkdir(parents=True, exist_ok=True)"

lint:
	cd $(API) && $(UV) run ruff check .
	cd $(API) && $(UV) run ruff format --check .
	$(PNPM) lint

typecheck:
	cd $(API) && $(UV) run mypy
	$(PNPM) typecheck

test:
	cd $(API) && $(UV) run pytest

check: lint typecheck test

up:
	$(COMPOSE) up -d --wait

down:
	$(COMPOSE) down

db-check:
	$(COMPOSE) exec -T postgres psql -U curriculo -d curriculo -c "SELECT extversion FROM pg_extension WHERE extname = 'vector'"

eval:
	@echo O harness de evals chega na fase 1. Nada a rodar ainda.

dev-api:
	cd $(API) && $(UV) run uvicorn curriculo_api.main:app --reload --port 8010

dev-web:
	$(PNPM) dev
