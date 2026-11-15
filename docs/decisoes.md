# Decisões

Decisões curtas e não bloqueantes. As grandes viram ADR em `docs/adr/`.

## D-01 — Portas (2026-11-15)
Postgres + pgvector na **5434**, Redis 7 na **6381**, API na **8010** e web na **3010**. As portas 5432,
5433 e 6380 já são de outros projetos do portfólio (o Pontual e o Pulo). O nome do projeto Compose é
`curriculo`, então `make down` só mexe nos contêineres e volumes deste repositório.

## D-02 — Skills (2026-11-15)
Estão todas presentes: impeccable, design-taste-frontend, emil-design-eng, animate, break-ui,
review-animations, pick-ui-library e dupla-agentes. `review-animations` e `pick-ui-library` têm
`disable-model-invocation: true`, então o agente lê o `SKILL.md` delas e segue as instruções à mão.

## D-03 — uv e make via winget (2026-11-15)
Com autorização do usuário, uv 0.13.8 e GNU Make 4.4.1 foram instalados via winget no escopo do usuário
(`--scope user`). O instalador por script do uv foi bloqueado. Todas as dependências do projeto são
locais: `.venv` em `apps/api` e `node_modules` no workspace.

## D-04 — Sem Tailwind por enquanto (2026-11-15)
O web começa com CSS puro (`globals.css`). A escolha de estilo depende da direção de design da fase 5
(impeccable / design-taste-frontend) e da pick-ui-library na fase 6. Instalar Tailwind agora seria
decidir antes da hora.

## D-05 — TypeScript 6 e ESLint 9 (2026-11-15)
- **TypeScript:** a última versão no npm é a 7.0.2, o compilador nativo. Ficamos em `^6.0.3`, como no
  projeto 3, porque o Next.js 16 usa a API JavaScript do compilador. A 7 não foi testada aqui.
- **ESLint:** ficamos em `^9.39.5`. Com o 10, o `pnpm add` acusou peers não atendidos em plugins do
  `eslint-config-next` 16.4.6: `eslint-plugin-import`, `eslint-plugin-jsx-a11y` e `eslint-plugin-react`
  aceitam no máximo o 9.

## D-06 — `next typegen` antes do `tsc` (2026-11-15)
O `next-env.d.ts` do Next 16 importa os tipos gerados em `.next/types/`. Por isso o script `typecheck`
roda `next typegen && tsc --noEmit`, e o `next-env.d.ts` fica fora do git, como o Next recomenda. Assim
o CI checa tipos sem precisar de `next build`.

## D-07 — Python ≥ 3.12, desenvolvimento em 3.13 (2026-11-15)
O `requires-python` é `>=3.12`, e ruff e mypy miram 3.12. O `.python-version` fixa 3.13, que é o Python
da máquina e o que o `setup-uv` instala no CI. No Windows, sempre via `uv run` ou `py -3.13`, nunca
`python`.

## D-08 — Uploads numa pasta do host (2026-11-15)
`PASTA_ARQUIVOS=data/arquivos`, criada por `make install` e ignorada pelo git (`data/`). Nesta fase a
API roda no host, então um volume do Compose não seria visto por ela. Quando a API entrar no Compose, a
pasta vira bind mount no mesmo caminho.

## D-09 — Makefile portável e `DOCKER` sobrescrevível (2026-11-15)
As receitas usam só `cd dir && comando`, que funciona no `sh` do Git Bash, no `cmd` e no Linux do CI. No
Windows o `docker.exe` fica fora do PATH, então se passa o caminho:
`make up DOCKER="$LOCALAPPDATA/Programs/DockerDesktop/resources/bin/docker.exe"`.
Também há `make db-check`, que consulta a versão da extensão `vector`.

## D-10 — Modelo de embeddings (2026-11-15)
`paraphrase-multilingual-MiniLM-L12-v2` pelo fastembed, com as medições no ADR 0002. O cache de modelos
fica em `data/` e não vai para o git. O CI não baixa modelo.
