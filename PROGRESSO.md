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
| 5 Direção de design | feita: nome Confere, mundo de cartório | (este commit) |
| **6 Front** | **próxima** | — |
| 7 Polimento | pendente | — |
| 8 Portfólio (README) | pendente | — |

Decisões: ADRs 0001–0007 em `docs/adr/` e D-01 a D-57 em `docs/decisoes.md`.

## Próximo passo: fase 6 — front

- Ler primeiro: `PRODUCT.md`, `DESIGN.md`, `docs/design/direcao.md` e o brief da landing
  (`apps/web/.impeccable/surfaces/apps-web-src-app-page-tsx.md`). O nome é **Confere** (D-56) e o mundo
  é "Confere com o original" (D-57).
- Antes: `make modelos` (embeddings, ~220 MB, gratuito).
- Skills: `pick-ui-library` (gráficos, upload, tabelas, toasts; ler à mão), `impeccable` e
  `design-taste-frontend` (landing: `draw.mjs --show` reimprime a direção salva em `.taste-skill/`),
  `animate` (o carimbo caindo, as etapas, a revelação da nota). Carregar uma de cada vez.
- Telas: landing (com "Confira você mesmo" sobre o caso b01), nova análise + progresso por SSE,
  resultado, histórico e comparação, recrutador, privacidade, todas na API real; seed
  `demo@curriculo.dev`; Playwright do fluxo principal (`corepack pnpm test:e2e`).
- Checagens de design: `lint.mjs` e `inspect.mjs` (landing; `--app` nas telas) na build de produção.
- No fim da fase: revisar o `DESIGN.md` a partir do que foi construído.
- Aceite: fluxo principal no Playwright, `make check` verde, commit `feat(web): ...`.

## Como verificar

```bash
make up DOCKER="$LOCALAPPDATA/Programs/DockerDesktop/resources/bin/docker.exe"
make check
make test-integracao
make eval
make eval PROVEDOR=regras
make seed
```

`make check` = ruff, mypy estrito, ESLint, tsc e testes rápidos (834). `make test-integracao` precisa
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
- Modelo de embeddings (~220 MB, gratuito) não baixado: `make modelos`. Sem ele o demo usa só a taxonomia
  e avisa na análise. Precisa para a fase 6.
- Não medidos (D-46): extração pelo modelo, custo, latência, cache e calibração de τ.
- Para a fase 7: fontes muito finas perto do limiar do detector de texto oculto; lista de lugares e
  empresas protegidos curta; negação detectada por oração; filtro de reescritas descarta algumas legítimas.
- Eventos `texto` do SSE são fragmentos do JSON estruturado; a fase 6 decide como mostrar.
- `CHAVE_CSRF` precisa ser definida se houver mais de um processo da API.
- A página de decisão do impeccable (`serve-question --start`) trava neste terminal; usar as perguntas da sessão.
- Depois da fase 8, com autorização: atualizar o README de perfil em `C:\Users\eduar\perfil-github`.
