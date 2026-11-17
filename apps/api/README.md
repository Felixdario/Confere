# curriculo-api

API em FastAPI do analisador de currículos. Gerenciada por [uv](https://docs.astral.sh/uv/).
Decisões nos ADRs de `docs/adr/` (sessão, CSRF, fila e SSE no 0007; modo demonstração no 0006).

## Rodar (da raiz do repositório)

```sh
make up          # Postgres + pgvector (5434) e Redis (6381) no Compose
make migrar      # migrações do Alembic (apps/api/migracoes)
make seed        # conta demo@curriculo.dev / demo1234 com análises prontas
make worker      # worker da fila (arq): análises e, às 03:00 UTC, a retenção
make modelos     # opcional: baixa o modelo de embeddings (~220 MB) uma vez, para termos fora da taxonomia
make dev-api     # API em http://localhost:8010 (OpenAPI em /docs)
```

Sem chave de IA (o padrão), `PROVEDOR_IA=regras`: a análise é por regras, sem IA e sem custo, e a
resposta avisa ("Modo demonstração"). `PROVEDOR_IA=falso` responde só os textos gravados das evals.

## Testes

```sh
make check             # ruff, mypy e os testes sem banco
make test-integracao   # com o Compose de pé: banco isolado por execução, worker e SSE reais
make eval              # evals com o provedor falso; PROVEDOR=regras para a linha de base do modo demo
make openapi           # regrava docs/openapi.json (um teste confere que está em dia)
make limpar-vencidos   # a retenção (RETENCAO_DIAS) à mão
```

## Mapa

| Caminho | O quê |
| - | - |
| `api/` | rotas (auth, análises, currículos, recrutador, privacidade), esquemas, erros problem+json, middleware de logs |
| `servicos/` | envio e fila, execução no worker, consultas, privacidade e retenção |
| `db/` | tabelas (SQLAlchemy 2) e sessão; migrações em `migracoes/` |
| `ia/` | provedores: regras (modo demo), falso (gravações) e Anthropic |
| `analise/` | pipeline, correspondência, nota, feedback; `vetores_pg.py` (pgvector) |
| `ingestao/` | leitura de PDF/DOCX, texto oculto, injection e anonimização |
| `eventos.py` | eventos do SSE (stream + pub/sub no Redis) |
| `worker.py`, `seed.py`, `retencao.py`, `relatorio_pdf.py` | fila, demo, retenção, PDF |
