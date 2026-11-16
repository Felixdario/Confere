# Funciona com GNU make no Windows (cmd ou sh do Git Bash) e no Linux do CI.
# Só usa `cd dir && comando`, que vale nos dois shells.
# No Windows o docker não está no PATH: make up DOCKER="$LOCALAPPDATA/Programs/DockerDesktop/resources/bin/docker.exe"

DOCKER ?= docker
UV ?= uv
PNPM ?= corepack pnpm
API := apps/api
PROVEDOR ?= falso
COMPOSE := $(DOCKER) compose -p curriculo -f docker-compose.yml

.PHONY: install lint typecheck test check up down db-check eval gravacoes dev-api dev-web

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

# make eval                     -> provedor falso (gravações; sem rede, sem chave)
# make eval PROVEDOR=anthropic  -> API real, só sob comando e com a chave do usuário (fase 3)
eval:
	cd $(API) && $(UV) run python -m curriculo_api.evals.rodar --provedor $(PROVEDOR)

# Regenera evals/gravacoes/ a partir das anotações (rode depois de mudar um caso).
gravacoes:
	cd $(API) && $(UV) run python -m curriculo_api.evals.gravacoes

dev-api:
	cd $(API) && $(UV) run uvicorn curriculo_api.main:app --reload --port 8010

dev-web:
	$(PNPM) dev
