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
| 6 Front | feita: landing + 6 telas na API real, Playwright do fluxo | `9aed011` |
| 7 Polimento | feita: axe sem violações, break-ui corrigido | `9bef471` |
| 8 Portfólio (README) | feita: README pt-BR e en, capturas, validação independente | (este commit) |

Decisões: ADRs 0001–0007 em `docs/adr/` e D-01 a D-66 em `docs/decisoes.md`.

## Próximo passo

O projeto está completo nas 8 fases. O que sobra depende do usuário:

- Publicado em 2026-11-18 em https://github.com/Felixdario/Confere; o README de perfil (`888e9d8`)
  também foi enviado, com os 52 links conferidos. Conferir o resultado do primeiro CI
  (https://github.com/Felixdario/Confere/actions) e corrigir o que falhar.
- Com chave da Anthropic: `make eval PROVEDOR=anthropic CASOS=b01,b02 TETO_USD=1.00` e, depois, os 30
  casos; preencher os ADRs 0001–0005 com números medidos.
- Capturas do README: `make seed` e, com a API, o worker e o web de pé,
  `CAPTURAS=1 corepack pnpm test:e2e --project=desktop capturas` em `apps/web`. O worker precisa ser
  reiniciado depois de mudar o código da análise (o arq não recarrega).

## Como verificar

```bash
make up DOCKER="$LOCALAPPDATA/Programs/DockerDesktop/resources/bin/docker.exe"
make check
make test-integracao
make eval
make eval PROVEDOR=regras
make seed
```

`make check` = ruff, mypy estrito, ESLint, tsc e testes rápidos (835). `corepack pnpm test:e2e` roda o
Playwright (axe em todas as telas nos dois temas, landing, fluxo principal e recrutador, no desktop e no celular) com a API, o worker e o
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

- Primeiro CI no GitHub em andamento desde o push de 2026-11-18; resultado ainda não conferido.
- Modelo de embeddings (~220 MB) baixado em `data/modelos` nesta máquina (fora do git); em outra, rode
  `make modelos`. Sem ele, o demo usa só a taxonomia e avisa na análise.
- Não medidos (D-46): extração pelo modelo, custo, latência, cache e calibração de τ.
- Limiares aceitos (D-65): fonte mínima de 4,5 pt no detector de texto oculto, lista curta de termos
  protegidos (ampliar vaza nomes), negação por oração, filtro de reescritas que descarta algumas legítimas.
- break-ui: seletor de dados só em dev (`?dados=pior|um|cheio`, D-64). A análise "só desejáveis"
  (`a2f42afb…`) foi criada à mão na conta demo e saiu no `make seed` da fase 8; o seed não a recria.
- `CHAVE_CSRF` precisa ser definida se houver mais de um processo da API.
- A página de decisão do impeccable (`serve-question --start`) trava neste terminal; usar as perguntas da sessão.
- README de perfil atualizado com o Confere (`888e9d8` no perfil-github) e enviado.
