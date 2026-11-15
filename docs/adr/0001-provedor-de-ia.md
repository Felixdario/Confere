# ADR 0001 — Provedor de IA

- **Status:** rascunho (fase 0; aceito na fase 3, com custo e latência medidos nas evals)
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
abaixo disso. A leitura em cache do Opus 5.5 custa US$ 0,20 por MTok. Os preços de escrita e leitura em
cache dos outros modelos entram na tabela de preços do código na fase 3, conferidos na mesma página.

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
    async def extrair_curriculo(self, texto: TextoAnonimizado) -> CurriculoExtraido: ...
    async def extrair_vaga(self, texto: str) -> VagaExtraida: ...
    def escrever_feedback(self, tabela: TabelaDaNota, curriculo: CurriculoExtraido,
                          vaga: VagaExtraida) -> AsyncIterator[EventoFeedback]: ...
```

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

As extrações usam `client.messages.parse(..., output_format=ModeloPydantic)` e leem
`response.parsed_output`.
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
- extração: 20 s;
- feedback: 40 s até o primeiro evento, sem limite de duração enquanto houver fluxo.

Esses valores iniciais são calibrados pela latência medida na fase 3. Usamos
`client.with_options(timeout=..., max_retries=...)`, lembrando que o tempo total pode chegar a
`timeout × (max_retries + 1)`. Por isso o orçamento da etapa é controlado por `asyncio.timeout` em
volta da chamada.

### Streaming do feedback

O feedback usa `client.messages.stream(...)`. O texto é repassado à tela por SSE (fase 4), e a
mensagem final (`get_final_message()`) dá o `usage` e o `stop_reason`.

### Recusa

Checamos `stop_reason` antes de ler o conteúdo. Em `"refusal"`:
- registramos `stop_details.category`, sem o texto do currículo;
- a etapa termina com a mensagem "não foi possível analisar este conteúdo".

No Opus 5.5 ligamos o fallback do servidor: beta `server-side-fallback-2026-07-01` com
`fallbacks: "default"`. O Haiku 5.5 **não tem** fallback do servidor, então a recusa na extração é
tratada no cliente.

### Prompt caching

As instruções fixas de cada etapa e a taxonomia de competências (ADR 0002) ficam no começo do prompt,
num bloco de `system` com `cache_control: {type: "ephemeral"}`. Currículo e vaga vêm depois do ponto
de cache.
- Nada variável pode entrar antes do ponto de cache: nem data, nem ID, nem taxonomia em ordem instável.
  A taxonomia é serializada com chaves ordenadas.
- Verificação: um teste de integração (sob comando, com chave) roda duas extrações seguidas e exige
  `usage.cache_read_input_tokens > 0` na segunda.
- O cache só existe acima de um tamanho mínimo de prefixo, que depende do modelo. Se as instruções e a
  taxonomia ficarem abaixo dele, o teste falha e isso vai registrado aqui.

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
