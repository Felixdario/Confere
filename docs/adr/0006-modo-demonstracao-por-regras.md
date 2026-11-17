# ADR 0006 — Modo demonstração por regras (`ProvedorRegras`)

- **Status:** aceito (fase 4), com a linha de base medida nas evals
- **Data:** 2026-11-16

## Contexto

O projeto é de portfólio e não gasta com a API da Anthropic (D-46): não há chave, e não haverá.
O provedor falso (ADR 0001) só responde os textos gravados das evals, pelo SHA-256 do texto
anonimizado; qualquer outro currículo termina em `gravacao_ausente`. Um visitante que envia o
próprio currículo precisa de uma análise de verdade, sem custo, sem rede e sem fingir que há IA.

## Opções

### A. Só o provedor falso
- ✅ Nada a construir.
- ❌ Só os 30 casos fictícios funcionam; o produto não pode ser experimentado.

### B. Modelo local (LLM pequeno no CPU)
- ✅ Análise "com IA" sem custo de API.
- ❌ Centenas de MB a alguns GB de modelo, latência de dezenas de segundos no CPU, extração
  pior que a de um modelo grande e difícil de medir.

### C. Provedor por regras atrás da mesma interface
- ✅ Determinístico, instantâneo, sem rede; passa pela **mesma** ancoragem, correspondência, nota
  e filtro do feedback que o provedor real; o contrafactual é 0 por construção.
- ❌ Só reconhece o que a taxonomia conhece; não reescreve; erra em formatos de currículo que
  fogem do comum.

## Decisão

**Opção C.** `curriculo_api/ia/regras.py`, `ProvedorRegras`, implementa `ProvedorIA`.

- **Seleção:** `PROVEDOR_IA=regras|falso|anthropic`, padrão `regras`. O `anthropic` só roda se
  pedido explicitamente e com chave; o `falso` continua para os testes e para o seed.
- **Extração do currículo:** seções pelos títulos (`## Experiência`, "Habilidades:", "FORMAÇÃO");
  experiências pelas linhas com datas e separador ("Cargo — Empresa — mar/2022 – atual", datas
  lidas por `ancoragem.datas_do_trecho`); competências, idiomas e certificações pelo casamento de
  termos da taxonomia (canônicas e sinônimos, palavra inteira, flexão só de plural e gênero; termos
  de até 3 caracteres, como "Go", "R", "SAE", só com a mesma caixa); formação pelas linhas de
  graduação, curso técnico, pós ou MBA (o nome do curso não vira competência, D-15). O `trecho` é
  sempre a própria linha do texto anonimizado, e cada competência leva até dois trechos (da
  experiência e da lista de habilidades antes do resumo): se a ancoragem descarta um por estar numa
  linha de injection ou negado ("Nunca usei Kubernetes"), o outro fica.
- **Extração da vaga:** itens de lista sob títulos de obrigatórios ("Requisitos", "O que
  esperamos") ou de diferenciais ("Desejáveis", "Nice to have"); sem nenhum título de requisitos,
  os itens de lista são obrigatórios. A competência é o primeiro termo da taxonomia na linha; fora
  dela, a linha sem o começo genérico ("Experiência com…"), que vai para o embedding (pgvector no
  worker). "Mínimo de N anos de experiência" vira o `anos_minimos` da vaga; nível do requisito por
  `niveis.nivel_de`; senioridade pelo título ou "Nível: pleno".
- **Feedback:** modelos de texto a partir da tabela já calculada: resumo ("análise por regras, sem
  IA"; quantos obrigatórios e diferenciais têm evidência; anos relevantes; principais lacunas),
  lacunas com comentário por status, palavras-chave da vaga e "o que aprender" para cada lacuna.
  **Nenhuma reescrita**: sem um modelo de linguagem, reescrever sem inventar não é seguro. Tudo
  passa pelo `filtrar_feedback` (ADR 0003, passo 5), como o texto de um modelo.
- **Custo e uso:** `RegistroUso` com `modelo="regras"`, tokens e custo zero e a duração real.
- **Tela:** `GET /analises/{id}` traz `modo_demonstracao: true` e
  `aviso_modo = "Modo demonstração: análise por regras, sem IA."` (com o falso, "resposta gravada
  de um caso fictício, sem IA").
- **Pré-teste da vaga:** com `PROVEDOR_IA=regras`, `POST /analises` extrai a vaga na hora e, sem
  requisitos, responde `422 vaga_sem_requisitos` em problem+json.

## Linha de base nas evals (`make eval PROVEDOR=regras`, 2026-11-16)

É a **primeira medição real de extração** do projeto: o falso devolve o gabarito (as métricas 2–4,
6 e 7 são tautológicas com ele, D-41). Não há meta para o modo por regras; os números são a linha
de base. Resultado em `evals/resultados/2026-11-16T232924-regras.json`, relatório em
`docs/evals-regras.md`. Embutidor falso (as evals não baixam modelo, D-31).

| Métrica | Regras |
| - | - |
| 1. Ancoragem dos itens mantidos | 100 % |
| 2. Descartados por trecho inválido | 0 de 192 (0 %) |
| 3a/3b. Precisão / cobertura de competências | 0,97 / 1,00 (Σ\|E∩A\| = 105, Σ\|E\| = 108, Σ\|A\| = 105) |
| 4. Nota dentro da faixa | 15 de 16 pares-base (93,8 %); fora: b13 (49, faixa 50–60) |
| 6. Injection: diferença contra a versão limpa | 0 |
| 7. Contrafactual | 0 |
| 8. Reescritas sem evidência | 0 (nenhuma reescrita) |
| 9/10. Custo / latência p95 | US$ 0 / 0,1 s |

Falsos positivos de competência: "Redes de computadores" no b05 e no b08 ("redes sociais") e BLS
no b07 (é certificação no gabarito).

**Leitura honesta desses números.** Eles são **otimistas**: o dataset foi escrito com o
vocabulário da taxonomia (todas as competências anotadas estão nela, por construção, ADR 0002), e
as regras foram ajustadas olhando esses 30 casos (a prioridade de trecho por seção nasceu do i03).
Currículos reais, com termos fora da taxonomia, tabelas e formatos livres, vão dar cobertura bem
menor. A linha de base serve para comparar mudanças nas regras, não como promessa de qualidade.

## Consequências

- Qualquer currículo em PDF, DOCX ou texto pode ser analisado de graça, em menos de um segundo.
- O resultado é explicável e reprodutível, mas limitado ao que a taxonomia conhece: termo fora dela
  no currículo não vira competência (no requisito, vai para o embedding).
- Experiência em duas linhas (cargo numa, empresa e datas na outra) sai com o cargo errado; vaga em
  prosa, sem lista, não tem requisitos reconhecíveis.
- O feedback é útil mas genérico; reescritas só existem com um modelo de linguagem.
- Com uma chave, `PROVEDOR_IA=anthropic` troca o provedor sem mudar mais nada (ADR 0001).

## Rodada 1 da revisão da fase 4 (2026-11-17)

- **Títulos de seção da vaga:** uma linha curta sozinha, sem marcador de lista, com o nome de uma seção conhecida também vale como título, com ou sem `:`, `#` ou negrito (`**Requisitos**`). Exemplos: "Requisitos", "Diferenciais", "Desejáveis", "Nice to have", "Requirements", "Qualificações". Antes, "Requisitos" + "Diferenciais:" fazia os obrigatórios sumirem. Há teste com 6 formatos.
- **"1 ano de experiência com…"** (singular) agora é reconhecido como o tempo mínimo da vaga, como "N anos". Antes virava um requisito a mais, que dava lacuna ao mesmo tempo que a senioridade dizia 4/1. Corrigida também a concordância "1 ano"/"N anos" no texto.
- Reexecutei as evals com regras (`2026-11-17T164412-regras.json`): nenhuma métrica mudou e nenhum par mudou de faixa. O dataset não tem esses formatos.