# Progresso

Analisador de currículos com IA, projeto 4 de 4 do portfólio. O plano completo está em `.dupla/plano.md`
(fora do git). Este arquivo é o ponto de partida de cada sessão: "continue pelo PROGRESSO.md".

## Como trabalhar (modo econômico)

- Uma fase por sessão. No fim: atualizar este arquivo, commit, parar.
- Skill `dupla-agentes` em modo econômico: sem modo trio nem paralelo; uma validação independente só no
  fim do projeto.
- Carregar cada skill só na fase em que ela é usada.
- Ler só o necessário (grep, `git diff`); mostrar resumo e erros das saídas longas.
- Durante a fase, rodar só os testes afetados; a suíte completa no fim.
- Nunca push, deploy ou apagar arquivos sem perguntar. Commits terminam com
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Sem gasto com a API da Anthropic** (D-46). Modo demo por regras (ADR 0006); nunca pedir chave.

## Estado

| Fase | Situação | Commit |
| - | - | - |
| 0 Plano, esqueleto, ADRs | feita | `382648d` |
| 1 Dataset e harness de evals | feita (30 casos fictícios) | `4f58755` |
| 2 Ingestão, texto oculto, injection, anonimização | feita | `7207daf` |
| 3 Pipeline de IA | feita com o provedor falso; evals reais não rodadas (D-46) | `1515969` |
| 4 API (auth, fila, SSE, recrutador, LGPD, demo) | feita | `b38d6b9` |
| 5 Direção de design | feita: nome Confere, mundo de cartório | `0dec746` |
| 6 Front | feita: landing + 6 telas na API real, Playwright do fluxo | (este commit) |
| **7 Polimento** | **próxima** | — |
| 8 Portfólio (README) | pendente | — |

Decisões: ADRs 0001–0007 em `docs/adr/` e D-01 a D-62 em `docs/decisoes.md`.

## Próximo passo: fase 7 — polimento

- O que existe: landing (`apps/web/src/app/page.tsx`, "Confira você mesmo" sobre o b01), `/entrar`
  (com "Entrar na demonstração"), `/nova`, `/analises/[id]` (progresso por SSE e resultado),
  `/historico`, `/curriculos/[id]` (comparação), `/recrutador` e `/recrutador/[id]`, `/privacidade`.
  O front fala com a API por `/api/*` (rewrite do Next, D-59).
- Checar com axe (WCAG 2.2 AA) todas as telas; leitores de tela no progresso (região viva) e nos
  carimbos (`role="img"` com rótulo).
- `inspect.mjs --app` não entra com sessão: as telas do app foram revisadas por capturas do Playwright.
  Avaliar um jeito de passar o cookie ao inspetor.
- Pendências herdadas da fase 3 (listadas abaixo) e o `break-ui` nas telas (nomes longos, vaga sem
  requisitos, 20 candidatos).
- Decidir com o usuário: as duas imagens descartadas em `apps/web/public/acervo/` (fora do commit).
- Aceite: axe sem violações, `make check` e `corepack pnpm test:e2e` verdes.

## Como verificar

```bash
make up DOCKER="$LOCALAPPDATA/Programs/DockerDesktop/resources/bin/docker.exe"
make check
make test-integracao
make eval
make eval PROVEDOR=regras
make seed
```

`make check` = ruff, mypy estrito, ESLint, tsc e testes rápidos (834). `corepack pnpm test:e2e` roda o
Playwright (landing, fluxo principal e recrutador, no desktop e no celular) com a API, o worker e o
seed de pé; ele entra uma vez na conta demo, porque a API limita 5 logins a cada 15 min por e-mail. `make test-integracao` precisa
do Compose de pé (36 testes). Na última execução, todos passaram.

## Ambiente (Windows 11)

- PATH novo em cada shell: `$env:Path = [Environment]::GetEnvironmentVariable('Path','User') + ';' + [Environment]::GetEnvironmentVariable('Path','Machine')`.
- uv 0.13.8 e GNU Make 4.4.1 via winget; Python só por `uv run` (o `python` é o alias da Store).
- pnpm só por `corepack pnpm` (restaurar carets depois de `add`).
- Docker fora do PATH: `$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe`; reabrir
  com `Start-Process "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe"`.
- Portas: Postgres 5434, Redis 6381, API 8010, web 3010.
- Encoding: editar com Edit/Write; varredura antes do commit com `Ã[§£©¡³ºª­]|â€` (o `Ã` sozinho dá
  falso alarme em "NÃO").
- Playwright com `channel: 'chrome'`, nunca `playwright install`.

## Pendências e riscos

- CI de integração escrito mas nunca rodado no GitHub (nada foi enviado).
- Modelo de embeddings (~220 MB) baixado em `data/modelos` nesta máquina (fora do git); em outra, rode
  `make modelos`. Sem ele, o demo usa só a taxonomia e avisa na análise.
- Não medidos (D-46): extração pelo modelo, custo, latência, cache e calibração de τ.
- Para a fase 7: fontes muito finas perto do limiar do detector de texto oculto; lista de lugares e
  empresas protegidos curta; negação detectada por oração; filtro de reescritas descarta algumas legítimas.
- `CHAVE_CSRF` precisa ser definida se houver mais de um processo da API.
- A página de decisão do impeccable (`serve-question --start`) trava neste terminal; usar as perguntas da sessão.
- Depois da fase 8, com autorização: atualizar o README de perfil em `C:\Users\eduar\perfil-github`.
