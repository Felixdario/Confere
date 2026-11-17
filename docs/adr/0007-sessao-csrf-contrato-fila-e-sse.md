# ADR 0007 — Sessão, CSRF, contrato da API, fila e SSE

- **Status:** aceito (fase 4)
- **Data:** 2026-11-16

## Contexto

A fase 4 expõe o pipeline (ADRs 0001–0006) numa API para o web (fase 6): contas, upload,
análise assíncrona com progresso em tempo real, histórico, modo recrutador e LGPD. Referência de
sessão: o outro projeto do autor (cookie httpOnly + CSRF double submit, ADR-034 de lá).

## Decisões

### Banco

- **SQLAlchemy 2 assíncrono (asyncpg) + Alembic** (`apps/api/migracoes/`, `make migrar`). A
  migração inicial (`0001`) cria a extensão `vector` e todas as tabelas: `usuarios` (e-mail único
  por `lower(email)`), `sessoes`, `consentimentos`, `curriculos`, `curriculo_versoes`, `vagas`,
  `analises`, `processos_recrutador`, `candidatos`, `decisoes_humanas`, `uso_diario` e
  `vetores_taxonomia`.
- **Toda tabela com dado de alguém tem `usuario_id` com `ON DELETE CASCADE`**, mesmo quando o dono
  também é alcançável por outra chave: o isolamento é um filtro simples em toda consulta, e apagar
  a conta é um `DELETE` em `usuarios`.
- **IDs UUID v4**: não dá para adivinhar nem enumerar.
- **O que não vai para o banco:** o valor original do que a anonimização removeu (só tipo, valor
  mascarado e ocorrências), o nome original do arquivo e o texto bruto do currículo (o arquivo
  enviado fica no disco, em `PASTA_ARQUIVOS/<usuario>/<versao>.<ext>`, até a retenção).
- **pgvector de verdade:** os vetores da taxonomia (384 dimensões, MiniLM) ficam em
  `vetores_taxonomia` com índice HNSW `vector_cosine_ops`. No worker, `ComparadorPgvector`
  embute de uma vez, antes da correspondência (que é síncrona), os termos fora da taxonomia e busca
  o vizinho mais próximo com `ORDER BY vetor <=> :v LIMIT 1`. Banco fora do ar → caminho em memória
  (o mesmo dos testes de unidade e das evals). O tipo `vector` trafega como texto: o codec binário
  do asyncpg recusa o texto que o `pgvector.sqlalchemy` envia nas comparações.

### Sessão e CSRF

- **Cookie `curriculo_sessao`**: token aleatório de 32 bytes, `HttpOnly`, `SameSite=Lax`,
  `Path=/`, `Secure` fora de `AMBIENTE=dev|teste`, validade `SESSAO_DIAS` (7). O banco guarda só o
  SHA-256 do token; logout apaga a sessão.
- **CSRF double submit em toda rota que muda estado (POST e DELETE), login e cadastro inclusive:**
  o cabeçalho `X-CSRF-Token` tem de ser igual ao cookie `curriculo_csrf` (legível pela página),
  emitido por `GET /auth/csrf`. Diferença consciente do outro projeto: lá o CSRF protegia só o
  refresh; aqui a sessão inteira é cookie, então toda mutação precisa dele. Sem token, `403 csrf`.
- **Senhas com argon2id** (`argon2-cffi`, parâmetros padrão). Login de e-mail inexistente verifica
  um hash fictício (mesmo tempo) e responde a mesma mensagem.
- **Limites (Redis, janela fixa):** login por e-mail (5 em 15 min, chave com o SHA-256 do e-mail) e
  por IP (30), cadastro por IP (10/h), análises por usuário (30/h) e por IP (60/h). Passou, `429`
  com `Retry-After`.
- **Teto de custo diário por usuário** (`TETO_CUSTO_DIARIO_USD`): `uso_diario` soma o custo real
  de cada análise (UTC); no teto, `429 teto_custo_diario` até a meia-noite. Com regras ou falso o
  custo é 0, mas o caminho é o mesmo e é testado.

### Contrato

- **Erros em `application/problem+json`** (RFC 9457) com `codigo` estável, `detail` em pt-BR e
  `id_requisicao`. A validação devolve campo e motivo, **nunca o valor enviado**. Erros da ingestão
  (PDF sem texto, tipo real, extensão, zip suspeito, macro…) saem como `422`; arquivo grande, `413`
  (o corpo é cortado pelo `Content-Length` ou durante a leitura, antes do multipart).
- **`POST /analises` responde `202`** com o id e os links de eventos e resultado. Antes, na hora:
  limites, teto, leitura e anonimização do arquivo (o erro sai já em problem+json) e, no modo por
  regras, o pré-teste da vaga. A mesma vaga colada de novo é a mesma `Vaga` (SHA-256 do texto
  normalizado); `curriculo_id` cria a próxima versão do currículo.
- **Histórico por cursor** (`criado_em`, `id`), comparação de versões em
  `GET /curriculos/{id}/comparacao?vaga=` ("A nota subiu de 58 para 76." e os requisitos que
  mudaram), relatório em PDF gerado no servidor (reportlab, sem dados pessoais).
- **OpenAPI** com tags, descrições, exemplos e o modelo `Problema` em toda rota;
  `docs/openapi.json` versionado (`make openapi`), e um teste falha se ficar desatualizado.
- **Isolamento:** quem não é dono recebe `404`, igual a um id inexistente. Um teste percorre todas
  as rotas com id do OpenAPI.

### Fila

- **arq** (Redis), fila `<REDIS_PREFIXO>:fila`, job `executar_analise` com id
  `<prefixo>:analise:<id>` (apagável no "apagar meus dados"), até 2 tentativas e tempo máximo
  `TEMPO_MAX_ANALISE_S`. O worker relê o arquivo do disco e roda o pipeline inteiro: as etapas de
  leitura e anonimização do SSE são reais, e o arquivo é a única cópia do original.
- Cron diário às 03:00 UTC: a retenção (ADR 0004). `make worker` sobe o worker.

### SSE

- `GET /analises/{id}/eventos` (`text/event-stream`): `etapa` (`leitura`, `anonimizacao`,
  `extracao`, `ancoragem`, `correspondencia`, `nota`, `feedback`), `texto` (pedaços do feedback),
  `final` e `erro`. O pipeline passou a separar leitura e anonimização em duas etapas.
- **Estado persistido + aviso:** o worker grava cada evento num stream do Redis com id explícito
  `<n>-0` e publica `n` no canal da análise. O SSE assina o canal **antes** de ler e, a cada aviso
  ou heartbeat, lê do stream tudo depois do último id enviado. Reconexão com `Last-Event-ID` (ou
  `?desde=`) continua de `n + 1`, sem perder nem repetir; um aviso perdido não perde evento.
- **Heartbeat** `: ping` a cada `SSE_HEARTBEAT_S` (15 s); `retry: 3000` no início; fecha no
  `final` ou no `erro`. Sem stream (expirou em `EVENTOS_TTL_S`, ou a análise veio do seed), o
  banco responde com o `final`/`erro`.

### Logs

- JSON por linha, com `id_requisicao` (aceito de `X-Request-ID` ou gerado, devolvido no cabeçalho).
  O acesso registra a rota **modelo** (`/analises/{analise_id}`), status e duração, nunca a query.
- O erro inesperado é tratado num middleware ASGI próprio, não no handler de `Exception` do
  Starlette (que relança e deixa o servidor registrar a mensagem): o log leva só o tipo e os quadros
  da pilha, sem mensagem; a resposta é um `500` em problem+json.

## Consequências

- O web (fase 6) precisa de `credentials: 'include'`, pegar o CSRF em `GET /auth/csrf` e mesma
  origem (ou CORS com origem exata, `CORS_ORIGENS`).
- A ingestão roda duas vezes por envio (na API, para validar; no worker, para as etapas): alguns
  segundos a mais por PDF grande, aceitos.
- Testes de integração (`make test-integracao`) usam um banco criado por execução e um prefixo de
  Redis próprio; o fluxo completo roda com uvicorn e worker do arq reais no mesmo laço de eventos.

## Rodada 1 da revisão (2026-11-17)

O Validador independente confirmou IDOR, sessão, CSRF/CORS, upload, corridas no rate limit e no
limite de 20, decisão humana, logs e demo, e achou oito falhas. Cada uma tem teste de regressão em
`tests/integracao/test_revisao_fase4.py`.

- **SSE com um assinante por processo.** Antes, cada conexão SSE tinha o próprio pub/sub no Redis.
  Com cerca de 2.000 conexões, o pool se esgotava, o login e o envio de **outra** pessoa davam 500,
  e as conexões não voltavam. Agora `eventos.Assinante` faz um único `PSUBSCRIBE` no padrão dos
  canais e acorda em memória as conexões da análise.
  - O pool da API é bloqueante, com teto (`REDIS_MAX_CONEXOES`, 50).
  - Conexões SSE simultâneas: até `LIMITE_SSE_POR_USUARIO` (5) por pessoa e `LIMITE_SSE_POR_IP` (10) por IP, contadas no Redis. Acima disso, `429 limite_de_conexoes`.
  - Teste com 50 conexões: o pool cresce no máximo 10, o login de outra pessoa dá 200, e todas as vagas de conexão voltam.
- **O SSE sempre fecha.**
  - Se o último evento do stream é terminal e o cliente já o tem (`Last-Event-ID` igual ou maior, que é o que o `EventSource` manda ao reconectar), o terminal é **reenviado com o mesmo id** e o fluxo fecha. O front trata `final`/`erro` repetido como idempotente.
  - O status no banco é conferido a cada heartbeat.
  - A conexão dura no máximo `SSE_DURACAO_MAX_S` (padrão `TEMPO_MAX_ANALISE_S` + 120 s) e fecha com `: tempo máximo desta conexão; reconecte`.
- **Ids de evento:** `Last-Event-ID` e `desde` só aceitam `^[0-9]{1,18}$`; o resto é `400 id_de_evento_invalido`. Cursor sem fuso ou fora de 2000–2200 é `400 cursor_invalido`.
- **CSRF ligado à sessão.**
  - O token é `<nonce>.<HMAC(chave, nonce | SHA-256 da sessão ou "anonima")>`, e a validação confere o cookie, o cabeçalho e o HMAC da sessão atual.
  - Login, cadastro e logout emitem um token novo (no cookie e no cabeçalho `X-CSRF-Token` da resposta). Um token plantado antes do login deixa de valer depois dele.
  - A chave é `CHAVE_CSRF`; sem ela, cada processo sorteia uma (com mais de um processo da API, defina a chave).
- **Teto diário atômico.**
  - No envio, logo antes do commit: `UPDATE uso_diario SET reservado_usd = reservado_usd + :reserva WHERE custo + reservado + :reserva <= :teto`. A linha do dia fica travada até o commit.
  - A reserva é `TETO_CUSTO_ANALISE_USD` com o provedor real e zero com regras ou falso.
  - Ao terminar, a reserva vira o custo real (`acertar_uso`); se a análise falha, a reserva volta e o gasto já feito fica.
  - O worker confere de novo o custo real do dia antes de chamar o provedor.
  - Corrida medida: com 3,80 de 5,00 usados e 10 envios simultâneos, passaram 2 e os outros 8 receberam 429.
- **"Apagar meus dados" com análise em andamento.**
  - `apagar_usuario` primeiro grava uma marca curta por análise (`<prefixo>:apagada:<sha256(id)>`, 1 h) e tira os jobs da fila. Só depois apaga o banco.
  - O `Publicador` confere a marca antes de cada evento, e o worker confere a análise a cada etapa. Ao abortar, apaga o stream e o canal no fim do job, mesmo que algo tenha sido escrito entre a conferência e o apagamento.
  - Os jobs não guardam resultado (`keep_result=0`).
  - Um envio que corre junto com o apagamento recebe `409 conta_apagada` em vez de 500, e o arquivo sai do disco.
- **Recrutador.**
  - `/analises/*` só aceita currículos `proprio`.
  - O candidato não expõe `analise_id`; o progresso dele vem de `GET /processos/{p}/candidatos/{c}/eventos`, só com `etapa`, `final` e `erro`.
  - Na resposta do candidato, os alertas saem sem `trecho`. Revelar e baixar o arquivo ficam em `auditoria_recrutador` (o histórico vai na resposta do candidato).
- **Embeddings:** `make modelos` baixa o MiniLM uma vez. Sem ele, o worker avisa no log, usa `ComparadorSemEmbeddings` (só a taxonomia) e a análise ganha o aviso "o modelo de embeddings não está instalado (make modelos)". Nunca baixa no meio de uma análise.

### Limitações registradas, sem correção nesta fase

- **Enumeração de e-mail no cadastro:** `409 email_em_uso` revela que a conta existe. O login não revela.
- **Logout por sessão:** encerra só a sessão atual; as de outros aparelhos continuam até vencer (`SESSAO_DIAS`).
- **IP nas chaves de limite:** ficam com o IP por até 1 h (a janela) e não são apagadas no "apagar meus dados", porque não são da conta.
- **Arquivo poliglota** (PDF seguido de zip): é lido como PDF pela assinatura (ADR 0004).
- **Contagem de conexões SSE:** se um processo da API morrer com conexões abertas, a contagem só zera quando a chave expira (duração máxima da conexão + 60 s).