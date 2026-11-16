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

## D-11 — Harness de evals dentro do pacote da API (2026-11-15)
O código fica em `apps/api/src/curriculo_api/evals/` e roda com
`cd apps/api && uv run python -m curriculo_api.evals.rodar` (é o que `make eval` chama). Os dados
ficam na raiz, em `evals/` (casos, gravações, resultados). Motivos:
- o harness passa por ruff, mypy estrito e pytest junto com o resto, sem configuração extra;
- a fase 3 implementa o `Pipeline` real no mesmo pacote e o harness o importa sem `sys.path`;
- `evals/` continua só com dados, legível por quem não abre o código.

## D-12 — Todos os resultados das evals são versionados (2026-11-15)
`evals/resultados/<AAAA-MM-DD>T<hhmmss>-<provedor>.json` (hora UTC) vai para o git, todos, não só o
último. Cada um tem dezenas de KB, e o histórico é o que dá sentido ao Δ: quem clona vê de onde a
execução anterior veio. Execuções de rascunho locais podem ser apagadas antes do commit.

## D-13 — `ProvedorIA` devolve `Resposta[T]` (2026-11-15)
O esboço do ADR 0001 tem `extrair_curriculo(...) -> CurriculoExtraido`. Na implementação, as extrações
devolvem `Resposta[T]` (`saida` + `usos`, um `RegistroUso` por chamada, novas tentativas inclusive). O
custo viaja com o resultado, sem estado mutável no provedor, que é compartilhado entre requisições na
fase 4. Registrado no ADR 0001 (rodada 1 da revisão da fase 1).

## D-14 — Taxonomia em `curriculo_api/dados/taxonomia.yaml` (2026-11-15)
O ADR 0002 cita `curriculo_api/taxonomia/competencias.yaml` e uma lista na raiz do YAML. A fase 1
usa `dados/taxonomia.yaml` (pedido do plano) com `versao` e `competencias` na raiz; a versão entra no
resultado das evals e, na fase 3, no prefixo de cache. O carregador é `curriculo_api.taxonomia`. A
normalização preserva `#` e `+` nas pontas e o "." inicial, para "C#", "C++" e ".NET" não virarem
"c" e "net". Registrado no ADR 0002.

## D-15 — Regras do dataset de evals (2026-11-15)
- **Data de referência fixa** (`evals/dataset.yaml`, 2026-11-01) para "atual": sem ela, a nota de
  referência mudaria com o calendário.
- **Faixa = nota de referência ± 5**, truncada em 0–100, com a nota calculada pela fórmula do ADR 0003
  a partir dos status anotados (oráculo em `curriculo_api/evals/referencia.py`, testado contra os
  exemplos 67/76/61 do ADR).
- **Contrafactuais**: 3 grupos (b03, b06, b11) de par-base + 2 variantes, com cargos neutros em
  gênero nos pares-base desses grupos, e o c07 (b01 → cargos no masculino), que mede a limitação do
  cargo flexionado (ADR 0004). `contrafactual.muda` lista tudo o que difere (nome, gênero, idade,
  estado civil, e-mail, telefone, CPF, endereço, cargo flexionado), conferido por teste; as idades são
  compatíveis com o corpo (graduação aos 20+, primeiro emprego aos 16+, teste).
- **Competências anotadas (conjunto A)** excluem idiomas e certificações, que servem de evidência
  para requisitos em seções próprias.
- **Curso de formação × curso livre** (regra única, rodada 1): o nome de uma graduação, curso técnico,
  pós ou MBA não vira competência ("Bacharelado em Estatística"); um curso livre ou de curta duração
  comprova a competência que o trecho nomeia ("Curso livre de SQL" → SQL; "Curso livre de UX Design"
  → UX Design; "Curso de Marketing Digital" → Marketing digital).
- **Ligação competência → experiência**: cada competência anotada lista os índices das experiências em
  que aparece (`experiencias`). Um teste deriva daí o `relevante` de cada experiência (ADR 0003) e o
  status dos requisitos com anos.
- **Dados de contato**: e-mails só em `example.com` (RFC 2606/6761; `exemplo.com.br` não é reservado)
  e telefones com DDD 00, que não existe. Empresas com nomes inventados e improváveis.
- Schema e regras completas em `evals/README.md`.

## D-16 — Revisão de sinônimos da taxonomia (2026-11-15)
Sinônimo só quando é a mesma coisa (ADR 0002). Na revisão da fase 1:
- **Tasy** saiu de sinônimo de Prontuário eletrônico: é um produto (sistema hospitalar). Virou canônica
  relacionada. No b07, "Registro em prontuário eletrônico Tasy" comprova as duas; o requisito
  "Prontuário eletrônico (Tasy ou MV)" segue atende pela evidência "prontuário eletrônico".
- **TCP/IP** saiu de Redes de computadores: é um protocolo, não a área. Virou canônica relacionada.
  No b10, "Diagnóstico de redes TCP/IP" comprova Redes de computadores (pela palavra "redes") e TCP/IP;
  a nota segue 100.
- **Triagem de currículos** saiu de Recrutamento e seleção: é uma etapa do processo. Virou canônica
  relacionada; no b11, a experiência de assistente continua relevante pela relação.
- **CI, CD** saíram de CI/CD ("CD" sozinho é ambíguo e "CI" é só metade); também saíram "integração
  contínua" e "continuous integration" (só CI).
- Também saíram sinônimos genéricos ou feitos sob medida: "Next" (Next.js), "Spring" (é a família, não o
  Spring Boot), "shell" e "Bash" (Shell script), "fechamento contábil mensal" (frase do currículo),
  "ECD" e "EFD" (são módulos do SPED, não o SPED), "entrevistas com usuários" (é um método de pesquisa),
  "networking" (ambíguo em pt-BR).
- Entraram **UX Design** e **Marketing digital** (regra do curso livre, D-15).
Nenhuma nota de referência mudou por causa da revisão de sinônimos.
