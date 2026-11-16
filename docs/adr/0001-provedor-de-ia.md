# ADR 0001 — Provedor de IA

- **Status:** implementado na fase 3 e validado sem rede (cliente falso do SDK); aceito depois da
  primeira rodada `make eval PROVEDOR=anthropic`, com custo e latência medidos
- **Data:** 2026-11-15

## Contexto

O pipeline chama um modelo de linguagem em três pontos:
1. **extrair o currículo**: experiências, competências, formação, idiomas e certificações, cada item com
   o `trecho` literal que o comprova;
2. **extrair a vaga**: requisitos obrigatórios e desejáveis, senioridade e anos mínimos;
3. **escrever o feedback**: lacunas, palavras-chave de ATS e reescritas antes/depois, em streaming para
   a tela.

A nota em si é calculada em código (ADR 0003). A IA só extrai e redige.

Requisitos:
1. **Testável sem rede e sem chave.** Os testes, o CI e o modo demo não podem depender da API nem gastar
   dinheiro.
2. **Saída estruturada e validada.** Toda resposta vira um modelo Pydantic. JSON inválido não pode chegar
   ao cálculo.
3. **Custo médio ≤ US$ 0,10 e p95 ≤ 60 s por análise** (ADR 0005), com o custo de cada chamada registrado.
4. **Troca de modelo sem tocar em código**: se o Haiku não bater as metas de extração, trocar por Sonnet é
   só uma variável de ambiente.
5. **Currículo e vaga são dados, nunca instruções** (ADR 0004).

### Preços

Lidos em platform.claude.com em 2026-11-15, por milhão de tokens (MTok):

| Modelo | ID | Entrada | Saída |
| - | - | - | - |
| Claude Haiku 5.5 | `claude-haiku-5-5` | US$ 0,10 | US$ 0,50 |
| Claude Sonnet 5.5 | `claude-sonnet-5-5` | US$ 2 | US$ 10 |
| Claude Opus 5.5 | `claude-opus-5-5` | US$ 4 | US$ 20 |

O preço do Haiku 5.5 vale para prompts de até 100 mil tokens; um currículo e uma vaga ficam muito
abaixo disso. A leitura em cache do Opus 5.5 custa US$ 0,20 por MTok.

Conferido de novo na fase 3 (2026-11-16, mesma página, tabela "Model pricing"), já com o cache, em
US$/MTok:

| Modelo | Entrada | Escrita 5 min | Escrita 1 h | Leitura | Saída |
| - | - | - | - | - | - |
| Haiku 5.5 (prompt ≤ 100 mil tokens) | 0,10 | 0,125 | 0,20 | 0,01 | 0,50 |
| Haiku 5.5 (prompt > 100 mil tokens) | 0,50 | 0,625 | 1 | 0,05 | 2,50 |
| Sonnet 5.5 | 2 | 2,50 | 4 | 0,10 | 10 |
| Opus 5.5 | 4 | 5 | 8 | 0,20 | 20 |
| Opus 5 e Opus 4.8 (reservas do fallback) | 5 | 6,25 | 10 | 0,50 | 25 |

A tabela versionada do código é `curriculo_api/ia/precos.py` (`VERSAO_PRECOS = "2026-11-16"`). O
"tamanho do prompt" da faixa do Haiku conta entrada + escrita + leitura de cache, e a requisição
inteira é cobrada pela faixa em que cai.

## Opções

### A. SDK oficial chamado direto no pipeline
Cada etapa chama `anthropic.AsyncAnthropic` onde precisa.

- ✅ Menos código.
- ❌ Testar exige *mock* do cliente HTTP em cada teste, frágil a mudanças do SDK.
- ❌ Sem modo demo sem chave.
- ❌ O registro de custo e a nova tentativa ficariam espalhados pelas etapas.

### B. Interface própria `ProvedorIA` com duas implementações
Um `Protocol` com as três operações do pipeline:

```python
class ProvedorIA(Protocol):
    @property
    def nome(self) -> str: ...  # "falso" ou "anthropic"
    async def extrair_curriculo(self, texto: TextoAnonimizado) -> Resposta[CurriculoExtraido]: ...
    async def extrair_vaga(self, texto: str) -> Resposta[VagaExtraida]: ...
    def escrever_feedback(self, tabela: TabelaDaNota, curriculo: CurriculoExtraido,
                          vaga: VagaExtraida) -> AsyncIterator[EventoFeedback]: ...

@dataclass(frozen=True)
class Resposta[T]:
    saida: T                         # o modelo Pydantic validado
    usos: tuple[RegistroUso, ...]    # um registro por chamada, novas tentativas inclusive
```

Atualizado na fase 1 (D-13): as extrações devolvem `Resposta[T]` em vez da saída pura, para que o
custo de cada chamada viaje junto com o resultado, sem estado mutável no provedor (que é
compartilhado entre requisições na fase 4). O feedback entrega o uso no último evento do fluxo.
Implementação em `curriculo_api/ia/` (`provedor.py`, `modelos.py`, `falso.py`, `fabrica.py`).

- `ProvedorAnthropic`: o SDK oficial, com as regras abaixo.
- `ProvedorFalso`: devolve respostas gravadas em `evals/` e `tests/`, escolhidas pelo hash do texto de
  entrada, e emite o feedback em pedaços, simulando o streaming. É determinístico.

A escolha é feita na inicialização: sem `ANTHROPIC_API_KEY` definida (ou vazia), usa o falso, e
`GET /saude` informa qual está ativo.

- ✅ Testes, CI e demo sem rede, sem chave e com resultado idêntico entre execuções.
- ✅ A tolerância contrafactual com o falso é **0 ponto**, por construção (ADR 0004).
- ✅ A nova tentativa, o *timeout*, o registro de custo e o tratamento de recusa ficam num lugar só.
- ❌ As gravações precisam ser regeneradas quando o schema muda. Um teste falha se uma gravação não
  valida contra o modelo Pydantic atual.
- ❌ O falso não mede a qualidade do modelo real: isso é papel de `make eval PROVEDOR=anthropic`.

### C. Camada multi-provedor genérica (LiteLLM ou similar)
- ✅ Troca de fornecedor por configuração.
- ❌ Esconde recursos específicos de que dependemos: `messages.parse` com Pydantic, `effort`, prompt
  caching com `cache_control`, `stop_reason: "refusal"` e o uso de cache em `usage`.
- ❌ Mais uma dependência entre nós e o SDK, que atrasa recursos novos.
- Resolve um problema que não temos: o projeto usa um fornecedor só.

## Decisão

**Opção B.** Os detalhes do `ProvedorAnthropic` são estes.

### Modelos e esforço

| Etapa | Variável | Padrão | `output_config.effort` |
| - | - | - | - |
| Extração (currículo e vaga) | `CLAUDE_MODELO_EXTRACAO` | `claude-haiku-5-5` | `low` |
| Feedback | `CLAUDE_MODELO_FEEDBACK` | `claude-opus-5-5` | `medium` |

- O Opus 5.5 rejeita `thinking: {type: "disabled"}` e `budget_tokens` (400) e não aceita `tool_choice`
  forçado (`any`/`tool`). Por isso o pensamento fica no padrão adaptativo e o esforço controla
  profundidade e gasto.
- Informamos `effort` sempre, porque o padrão do Opus 5.5 e do Haiku 5.5 é `medium`.
- Sem `temperature`, `top_p` ou `top_k`: os modelos novos rejeitam valores fora do padrão.

### Saída estruturada

Planejado: `client.messages.parse(..., output_format=ModeloPydantic)` lendo
`response.parsed_output`. **Implementado (fase 3):** `client.messages.create(...,
output_config={"effort": ..., "format": {"type": "json_schema", "schema":
anthropic.transform_schema(Modelo)}})`, a forma "Raw Schema" da documentação, com o mesmo schema
que o `parse` enviaria, e a validação Pydantic feita por nós (`Modelo.model_validate_json` sobre os
blocos `text`). Motivo: no SDK 2.8 o `parse` valida dentro da chamada e, quando a validação falha
(resposta cortada por `max_tokens`, recusa no meio, ou uma regra nossa como "fim antes do início"),
levanta `ValidationError` sem devolver a mensagem. Perderíamos o `usage` da tentativa (o custo
some do registro e do teto) e o `stop_reason` (a recusa tem de ser checada antes do conteúdo). O
resultado validado é o mesmo.
- O schema enviado não aceita restrições como `minLength`, `maxLength`, `minimum` e `maximum`. O SDK
  as remove do schema e o Pydantic as valida do nosso lado.
- Restrições de negócio também ficam no Pydantic, por exemplo: o `trecho` não pode ser vazio, o fim
  não pode vir antes do início, e anos não podem ser negativos.
- Não usamos `tool_choice` forçado para obter JSON: a saída estruturada resolve isso nos dois modelos.

### Nova tentativa

Se a resposta não validar (JSON inválido ou `ValidationError`), fazemos **1** nova tentativa. Ela leva
a mensagem de erro do Pydantic no prompt ("a resposta anterior falhou nesta validação: …"). Se falhar
de novo, a etapa termina com um erro claro. Erros de rede, 429 e 5xx ficam com as novas tentativas do
SDK (`max_retries=2`), que são contadas à parte.

### Tempo limite por etapa

Cada etapa tem um limite próprio, configurável:
- extração: 20 s (`CLAUDE_TIMEOUT_EXTRACAO_S`);
- feedback: 40 s até o primeiro evento (`CLAUDE_TIMEOUT_FEEDBACK_PRIMEIRO_EVENTO_S`) e 40 s sem
  nenhum evento novo (`CLAUDE_TIMEOUT_FEEDBACK_OCIOSO_S`), sem limite de duração enquanto houver
  fluxo.

Esses valores iniciais são calibrados pela latência medida na fase 3. Usamos
`client.with_options(timeout=..., max_retries=...)`, lembrando que o tempo total pode chegar a
`timeout × (max_retries + 1)`. Por isso o orçamento da etapa é controlado por `asyncio.timeout` em
volta da chamada.

### Streaming do feedback

O feedback usa `client.messages.stream(...)` (no Opus, `client.beta.messages.stream(...)` com o
fallback, abaixo) **com a mesma saída estruturada** (`output_config.format`): streaming e saída
estruturada combinam. O texto que chega é o JSON sendo escrito; o provedor o repassa em eventos
`texto` (um iterador assíncrono de `EventoFeedback`: `etapa`, `texto`, `final`) para o SSE da fase 4,
e o evento `final` traz o `FeedbackIA` validado e o uso de cada chamada. A tela da fase 6 decide se
mostra o JSON cru ou se o interpreta aos poucos; a saída que conta é só a validada. A mensagem final
(`get_final_message()`) dá o `usage` e o `stop_reason`. Uma resposta inválida gera a mesma nova
tentativa das extrações, com um evento `etapa` "nova tentativa do feedback".

### Recusa

Checamos `stop_reason` antes de ler o conteúdo. Em `"refusal"`:
- registramos `stop_details.category`, sem o texto do currículo;
- a etapa termina com a mensagem "não foi possível analisar este conteúdo".

No Opus 5.5 ligamos o fallback do servidor: beta `server-side-fallback-2026-07-01` com
`fallbacks: "default"`; no SDK Python, `client.beta.messages.stream(...,
betas=["server-side-fallback-2026-07-01"], fallbacks="default")` (`CLAUDE_FALLBACK_FEEDBACK`, ligado
por padrão). Quando um modelo de reserva responde, `usage.iterations` traz uma entrada
`fallback_message`; o custo soma cada iteração pelo preço do próprio modelo (Opus 5 e Opus 4.8 estão
na tabela) e o registro de uso marca `fallback: true` com o modelo que respondeu. O Haiku 5.5 **não tem** fallback do servidor, então a recusa na extração é
tratada no cliente.

### Prompt caching

As instruções fixas de cada etapa e a taxonomia de competências (ADR 0002) ficam no começo do prompt,
num bloco de `system` com `cache_control: {type: "ephemeral"}`. Currículo e vaga vêm depois do ponto
de cache.
- Nada variável pode entrar antes do ponto de cache: nem data, nem ID, nem taxonomia em ordem instável.
  A taxonomia é serializada com chaves ordenadas.
- Verificação: um teste de integração (sob comando, com chave) roda duas extrações seguidas e exige
  `usage.cache_read_input_tokens > 0` na segunda.
- O cache só existe acima de um tamanho mínimo de prefixo, que depende do modelo: 512 tokens no
  Haiku 5.5 e no Opus 5.5. O `system` de cada etapa tem de 9,8 mil a 10,5 mil caracteres (8,7 mil
  das regras e da taxonomia), bem acima do mínimo; o número real de tokens sai do `usage` da
  primeira rodada.
- Sem chave, a verificação é feita em teste sem rede: o `system` é idêntico byte a byte entre
  chamadas da mesma etapa (e o bloco de regras + taxonomia é idêntico entre etapas), o
  `cache_control` fica no último bloco e nenhum dado variável entra antes dele. O teste com
  `cache_read_input_tokens > 0` fica para a rodada real.

### Custo por chamada

Cada chamada grava um registro com:
- etapa, modelo, tentativa e duração;
- `input_tokens`, `output_tokens`, `cache_creation_input_tokens` e `cache_read_input_tokens`;
- custo em US$, calculado pela tabela de preços versionada no código.

O custo do dia alimenta o teto `TETO_CUSTO_DIARIO_USD` (ADR 0004). O conteúdo do currículo nunca entra
nesse registro.

### Dados, não instruções

Currículo e vaga entram na mensagem do usuário, cada um num bloco delimitado (`<curriculo>…</curriculo>`
e `<vaga>…</vaga>`, com o delimitador escapado se aparecer no texto). As instruções do `system` dizem
que o conteúdo desses blocos é dado a analisar e que qualquer instrução dentro deles deve ser ignorada.
- O currículo chega anonimizado e com o texto oculto já sinalizado (ADR 0004).
- O feedback recebe a tabela da nota pronta e não pode alterá-la. A regra da evidência (ADR 0003) é
  checada em código.

## Consequências

- O pipeline depende só de `ProvedorIA`. O SDK aparece num único módulo, `ia/anthropic.py`.
- `make check` e o CI não precisam de chave nem de rede. A qualidade real é medida em
  `make eval PROVEDOR=anthropic`.
- Trocar a extração para `claude-sonnet-5-5` é mudar `CLAUDE_MODELO_EXTRACAO`. Isso custa 20× mais por
  token e deve ser medido nas evals antes.
- **Risco de custo do feedback:** a saída do Opus custa US$ 20/MTok, e com esforço `medium` os tokens
  de raciocínio também são cobrados como saída. A meta de US$ 0,10 por análise deixa cerca de 5 mil
  tokens de saída para o feedback inteiro. Se as evals mostrarem que a meta não fecha, as alternativas
  são, nesta ordem:
  1. esforço `low` no feedback;
  2. limitar o tamanho do feedback no prompt;
  3. `CLAUDE_MODELO_FEEDBACK=claude-sonnet-5-5` (metade do preço).

  A troca de esforço ou de modelo só vale com as evals de qualidade passando.
- As gravações do provedor falso são versionadas junto com o dataset das evals (fase 1).

## Implementação (fase 3)

- **Módulos:** `ia/anthropic.py` (o único que importa o SDK), `ia/prompts.py` (prompts e
  delimitadores), `ia/precos.py` (tabela versionada), `ia/orcamento.py` (teto), `ia/fabrica.py`.
- **Robustez:** erros do SDK viram erros tipados com mensagem em pt-BR (`ErroLimiteDeTaxa` 429,
  `ErroServidor` 5xx/529, `ErroConexao`, `TempoEsgotado`, `ErroRequisicao` 400/404/422,
  `ErroAutenticacao` 401/403, `Recusa`, `SaidaInvalida`); a mensagem da API não é repassada (pode
  citar trechos da requisição). Todo erro carrega `usos`, as chamadas já cobradas.
- **Nova tentativa:** a mensagem do usuário da 2ª tentativa é a mesma da 1ª mais um bloco com os
  erros de validação (só caminho e mensagem do Pydantic, sem o valor de entrada); o `system` não
  muda, então o prefixo cacheado vale nas duas.
- **Teto por análise** (`TETO_CUSTO_ANALISE_USD`, padrão US$ 0,60; era 0,30, ver a rodada 1):
  antes de cada chamada, a entrada é estimada com `messages.count_tokens` (gratuito; se falhar, pelo
  tamanho em caracteres ÷ 2,5, estimativa conservadora ainda não medida) e o pior caso é toda a
  entrada ao preço da escrita em cache mais `max_tokens` de saída. Se gasto real + reservas + pior
  caso passar do teto, a chamada não é feita (`TetoDeCustoExcedido`). O pior caso fica reservado até
  a chamada terminar, porque currículo e vaga são extraídos em paralelo (em `TaskGroup`: se uma
  falha, a outra é cancelada). O mesmo mecanismo, com um orçamento pai, faz o `TETO_USD` das evals.
- **Logs:** só metadados (etapa, modelo, tentativa, tokens, custo, duração, `stop_reason`,
  categoria da recusa, request id). Testes com `caplog` conferem que nem o currículo nem a mensagem
  da API aparecem, inclusive em erro, recusa e saída inválida.
- **Testes sem rede** (`tests/test_provedor_anthropic.py`, `tests/sdk_falso.py`): montagem do prompt
  (delimitadores, neutralização de tags dentro dos dados, `cache_control`, prefixo idêntico),
  parâmetros proibidos ausentes (`temperature`, `thinking`, `tool_choice`), custo pelo `usage`
  (cache, faixa acima de 100 mil do Haiku, iterações de fallback), nova tentativa, tempo limite
  (extração, primeiro evento e ocioso), 429/5xx/400/401/403/conexão, recusa, fallback e teto.
- **Sem chave:** `make eval PROVEDOR=anthropic` sai com código 2 e a mensagem "ANTHROPIC_API_KEY não
  está definida…", sem gravar nada.

## Rodada 1 da fase 3 (revisão do Validador)

- **Delimitadores:** antes de entrar no prompt, os dados passam por NFKC, perdem os caracteres de
  largura zero e têm **todo** `<` e `>` trocado por `‹` e `›`, não só as tags conhecidas. Assim
  `</curriculo foo=1>`, `</curri\u200bculo>`, `＜/curriculo＞`, `</currículo>` e `<\n/curriculo\n>`
  não fecham o bloco de dados (teste em `tests/test_ataques_fase3.py`). A ancoragem desfaz a troca
  ao comparar. O detector da ingestão passou a alertar a tag com atributos (`</curriculo foo=1>`);
  largura zero e largura cheia já saíam na chave de casamento. Fica de fora: entidades HTML
  (`&lt;/curriculo&gt;`), que não fecham nada no texto que o modelo recebe.
- **Pior caso com fallback:** no feedback com `fallbacks: "default"`, a reserva é duas vezes (a
  tentativa e a do modelo de reserva) o pior caso ao preço do modelo mais caro da cadeia (Opus 5.5,
  Opus 5, Opus 4.8: US$ 6,25 de escrita em cache e US$ 25 de saída). Com `max_tokens` = 8.000 e uns
  10 mil tokens de entrada, isso dá cerca de US$ 0,53, acima do teto antigo de US$ 0,30: por isso
  o padrão de `TETO_CUSTO_ANALISE_USD` subiu para US$ 0,60. Antes, um fallback podia gastar US$ 0,44
  com teto de 0,30; agora a chamada é barrada antes.
- **Reserva cobrada sem `usage`:** quando a chamada termina sem resposta (tempo esgotado, conexão
  caída, cancelamento pelo `TaskGroup` porque a outra extração falhou), o pior caso reservado vira
  gasto, porque o servidor pode ter cobrado. Erro HTTP da API (4xx/5xx) só libera a reserva.
  Antes, três tempos esgotados seguidos deixavam o gasto em zero.
- **`count_tokens` com tempo limite** próprio: `CLAUDE_TIMEOUT_COUNT_TOKENS_S` (5 s) e no máximo
  1/4 do tempo da etapa; se passar, vale a estimativa pelo tamanho. Na extração, o prazo da etapa
  começa antes do `count_tokens`, que conta dentro dele.
