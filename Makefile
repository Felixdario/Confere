# Funciona com GNU make no Windows (cmd ou sh do Git Bash) e no Linux do CI.
# Só usa `cd dir && comando`, que vale nos dois shells.
# No Windows o docker não está no PATH: make up DOCKER="$LOCALAPPDATA/Programs/DockerDesktop/resources/bin/docker.exe"

DOCKER ?= docker
UV ?= uv
PNPM ?= corepack pnpm
API := apps/api
PROVEDOR ?= falso
CASOS ?=
TETO_USD ?=
RESULTADO ?=
EVAL_ARGS := --provedor $(PROVEDOR)
ifneq ($(strip $(CASOS)),)
EVAL_ARGS += --casos $(CASOS)
endif
ifneq ($(strip $(TETO_USD)),)
EVAL_ARGS += --teto-usd $(TETO_USD)
endif
TAU_ARGS :=
ifneq ($(strip $(RESULTADO)),)
TAU_ARGS += --resultado ../../$(RESULTADO)
endif
COMPOSE := $(DOCKER) compose -p curriculo -f docker-compose.yml

.PHONY: install lint typecheck test check up down db-check eval calibrar-tau gravacoes fixtures dev-api dev-web

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
# make eval PROVEDOR=anthropic CASOS=b01,b02 TETO_USD=2.00
#                               -> API real, só sob comando e com a chave do usuário. TETO_USD é
#                                  obrigatório: a execução para antes de uma chamada que passaria
#                                  dele (custo real somado do usage). CASOS filtra os casos.
eval:
	cd $(API) && $(UV) run python -m curriculo_api.evals.rodar $(EVAL_ARGS)

# Grade de τ_alto/τ_baixo refeita em código sobre as extrações da última execução real (ou de
# RESULTADO=evals/resultados/<arquivo>.json), sem chamar a API de novo.
calibrar-tau:
	cd $(API) && $(UV) run python -m curriculo_api.evals.calibrar_tau $(TAU_ARGS)

# Regenera evals/gravacoes/ a partir das anotações (rode depois de mudar um caso, a ingestão ou a
# anonimização: o hash é o do texto anonimizado).
gravacoes:
	cd $(API) && $(UV) run python -m curriculo_api.evals.gravacoes

# Regenera os PDFs/DOCX reais de alguns casos (evals/casos/<id>/curriculo.{pdf,docx}) a partir do
# curriculo.md, com o texto oculto renderizado de verdade. Rode antes de `make gravacoes`.
fixtures:
	cd $(API) && $(UV) run python -m curriculo_api.evals.fixtures

dev-api:
	cd $(API) && $(UV) run uvicorn curriculo_api.main:app --reload --port 8010

dev-web:
	$(PNPM) dev
