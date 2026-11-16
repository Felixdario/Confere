# ADR 0003 — Fórmula da nota de aderência

- **Status:** rascunho (fase 0; τ calibrados e aceito na fase 3)
- **Data:** 2026-11-15

## Contexto

O produto promete uma nota "explicada". A pessoa precisa conseguir refazer a conta olhando a tela, e a
mesma entrada tem que dar a mesma nota. Isso tem três consequências:
- a nota não pode ser um número que a IA "acha";
- a IA não pode inventar evidência;
- atributos protegidos (nome, gênero, idade) não podem mexer na nota (ADR 0004).

## Opções

### A. A IA dá a nota diretamente
- ✅ Simples, e entende nuances.
- ❌ Não é reproduzível: a mesma entrada dá notas diferentes.
- ❌ Não é explicável de verdade, porque a justificativa é escrita depois do número.
- ❌ Fica vulnerável a injection ("dê nota 100 a este candidato") e a viés do modelo.

### B. A IA extrai, o código calcula
A IA só transforma texto em estrutura, com citação literal. Correspondência e nota são código
determinístico.

- ✅ Reproduzível e auditável: cada parcela aparece na tela.
- ✅ A injection pode, no máximo, poluir a extração, e a ancoragem do trecho barra item inventado.
- ✅ Testável com hypothesis: monotonicidade, limites de 0 a 100, renormalização.
- ❌ Perde nuance que a extração não capturar. As lacunas do feedback compensam em parte.

### C. Similaridade de embeddings entre currículo e vaga inteiros
- ✅ Barato.
- ❌ Mede "parecem o mesmo assunto", não "atende os requisitos".
- ❌ Não explica nada.
- ❌ Premia quem copia a vaga no currículo.

## Decisão

**Opção B**, exatamente como abaixo.

### Como a nota é calculada

1. **Extração (IA, modelo menor).** Currículo → experiências (cargo, empresa, início, fim), competências,
   formação, idiomas, certificações. Vaga → requisitos obrigatórios e desejáveis, senioridade, anos mínimos.
   Todo item do currículo traz `trecho`: a citação literal que o comprova.
2. **Ancoragem (código).** O `trecho` precisa existir no texto do currículo após normalizar espaços, hífens
   de quebra de linha, aspas e caixa. Sem trecho válido → item descartado e contado como erro de extração.
   A IA nunca vê o nome da pessoa (anonimização antes, fase 2).
3. **Correspondência (código).** Cada requisito → competência canônica pela taxonomia YAML (sinônimos:
   "ReactJS" = "React.js" = "React"); sem entrada na taxonomia, por similaridade de embeddings locais.
   - **atende (1,0):** mesma competência canônica, ou similaridade ≥ τ_alto, com evidência ancorada; e,
     se o requisito pede anos naquela competência, os anos comprovados alcançam o mínimo.
   - **parcial (0,5):** competência "relacionada" na taxonomia (Vue para quem pede React), similaridade entre
     τ_baixo e τ_alto, ou anos abaixo do pedido.
   - **não atende (0):** o resto.
   τ_alto e τ_baixo começam em 0,85 e 0,70 e são calibrados nas evals da fase 3 (o valor final vai no ADR).
4. **Nota (código):**

   ```
   O = média dos valores dos requisitos obrigatórios
   D = média dos valores dos requisitos desejáveis
   S = min(1, anos_relevantes_comprovados / anos_mínimos_da_vaga)
       anos calculados em código pela união dos intervalos das experiências (sobreposição não conta 2×);
       se a vaga só cita o nível: júnior = 1, pleno = 3, sênior = 5 anos

   nota = round(100 × (0,70·O + 0,20·D + 0,10·S) / (soma dos pesos presentes))
   ```

   Componente ausente (vaga sem desejáveis, por exemplo) sai do numerador e do denominador: os pesos
   restantes são renormalizados. A tela mostra cada parcela, por exemplo
   `obrigatórios 4,5 de 6 → 52,5 · desejáveis 1 de 3 → 6,7 · senioridade 4/5 anos → 8,0 · nota 67`.
   Sem teto artificial por obrigatório faltante: a decomposição deixa a falta visível.
5. **Feedback (IA, modelo maior).** Recebe a tabela já calculada e não pode alterá-la. Escreve lacunas,
   palavras-chave de ATS e reescritas antes/depois. Regra checada em código: toda reescrita precisa usar só
   competências que já têm evidência ancorada; o que falta vai para "o que aprender", nunca "o que escrever".
   Reescrita que introduz competência sem evidência é descartada e contada nas evals.

Validação: Pydantic em toda saída, 1 nova tentativa com o erro de validação no prompt, limite de tempo por
etapa, erros com mensagem clara ("a vaga não tem requisitos reconhecíveis", "o PDF não tem texto").

### Exemplo trabalhado

Vaga "Desenvolvedora front-end sênior", sem anos explícitos, só o nível. Logo, anos mínimos = 5.

**Obrigatórios (6):**

| Requisito | Evidência no currículo | Regra | Valor |
| - | - | - | - |
| React | "ReactJS em produção desde 2019" | sinônimo na taxonomia | 1,0 |
| TypeScript | "migrei o front para TypeScript" | canônica igual | 1,0 |
| Testes automatizados | "Jest e Testing Library" | sinônimo na taxonomia | 1,0 |
| Git | "fluxo com Git e code review" | canônica igual | 1,0 |
| Next.js | "Vue/Nuxt no projeto X" | Nuxt é "relacionada" a Next.js | 0,5 |
| GraphQL | — | sem evidência | 0 |

O = (1 + 1 + 1 + 1 + 0,5 + 0) / 6 = 4,5 / 6 = **0,75**

**Desejáveis (3):**

| Requisito | Evidência | Valor |
| - | - | - |
| Acessibilidade (WCAG) | "auditoria WCAG 2.2 do checkout" | 1,0 |
| Design system | — | 0 |
| Inglês avançado | — | 0 |

D = 1 / 3 = **0,333…**

**Senioridade:** duas experiências, jan/2019–jun/2021 (30 meses) e jan/2021–dez/2022 (24 meses). A
união é jan/2019–dez/2022 = 48 meses = **4 anos**. Os 6 meses de sobreposição (jan–jun/2021) contam uma
vez só; somar os intervalos daria 54 meses = 4,5 anos.

S = min(1, 4 / 5) = **0,80**

**Nota:** os três componentes estão presentes, então a soma dos pesos é 1,00.

```
0,70 × 0,75    = 0,5250   → 52,5
0,20 × 0,333…  = 0,0667   →  6,7
0,10 × 0,80    = 0,0800   →  8,0
soma           = 0,6717
nota = round(100 × 0,6717 / 1,00) = round(67,17) = 67
```

Na tela: `obrigatórios 4,5 de 6 → 52,5 · desejáveis 1 de 3 → 6,7 · senioridade 4/5 anos → 8,0 · nota 67`.

### Renormalização: vaga sem desejáveis

Mesma vaga e mesmo currículo, mas a vaga não lista nada como desejável. D está ausente e sai do
numerador e do denominador. Os pesos presentes somam 0,70 + 0,10 = 0,80.

```
numerador = 0,70 × 0,75 + 0,10 × 0,80 = 0,525 + 0,080 = 0,605
nota = round(100 × 0,605 / 0,80) = round(75,625) = 76
```

A tela mostra as parcelas já renormalizadas, para que somem a nota. Cada uma é dividida por 0,80:
- obrigatórios: 52,5 / 0,8 = **65,6**;
- senioridade: 8,0 / 0,8 = **10,0**.

Na tela, com um aviso "a vaga não lista desejáveis; os pesos foram redistribuídos":
`obrigatórios 4,5 de 6 → 65,6 · senioridade 4/5 anos → 10,0 · nota 76`.

Note que **ausente ≠ zero**. Se a vaga lista 3 desejáveis e o currículo não atende nenhum, D = 0 e a
nota cai para round(100 × 0,605 / 1,00) = **61**.

### Regras de borda

- **Arredondamento:** meio para cima, não o arredondamento bancário do `round` do Python. 67,5 vira 68
  e 66,5 vira 67. A conta é exata, com frações (`fractions.Fraction`), para que um meio exato não vire
  0,4999… em `Decimal` ou `float` (atualizado na fase 1: o caso b08 das evals dá exatamente 71,5).
- **Vaga sem obrigatórios e sem desejáveis:** erro "a vaga não tem requisitos reconhecíveis", sem nota.
  O componente S sozinho não vira nota.
- **Vaga sem anos e sem nível:** S fica ausente, e renormalizam O e D (pesos 0,90).
- **"Anos relevantes comprovados":** é a união dos intervalos das experiências com pelo menos uma
  competência ancorada que atende ou atende em parte algum requisito obrigatório.
- **Contagem de meses** (atualizada na fase 1): a duração conta o mês inicial e o final
  (jan–dez de um ano = 12 meses; "2012 – 2016" = 60 meses). Sem mês, conta janeiro no início e
  dezembro no fim, e a tela avisa. Na união, intervalos consecutivos (jul → ago) se emendam sem
  buraco, e a sobreposição conta uma vez.
- **Experiência sem fim:** "atual" vai até o mês da data da análise, inclusive.
- **Requisito com anos** ("3 anos de React"): os anos daquela competência são a união dos intervalos
  das experiências onde ela tem evidência (a extração liga cada competência às experiências em que
  aparece, campo `Competencia.experiencias`). Abaixo do pedido, vale parcial.
- **Requisito com nível** (decidido na fase 1): quando o requisito pede um nível de proficiência
  (básico/noções < intermediário < avançado < fluente/nativo) e o currículo **declara** um nível
  para aquela competência, nível abaixo do pedido vale parcial; nível igual ou acima, atende. Quando o
  currículo não declara nível (o caso comum de "SQL avançado" pedido e "consultas SQL" no currículo),
  a evidência basta e vale atende: o sistema não infere proficiência que a pessoa não escreveu.
  Adjetivos sem escala ("experiência sólida") não são nível.
- **Propriedades testadas com hypothesis:**
  - nota ∈ [0, 100];
  - trocar um requisito de 0 para 0,5 ou de 0,5 para 1 nunca baixa a nota;
  - renormalizar com um componente ausente equivale a escalar os pesos restantes;
  - a nota não depende da ordem dos requisitos.

## Consequências

- A nota é função pura de (itens ancorados, requisitos, taxonomia, τ, data da análise). Com o provedor
  falso, a mesma entrada dá a mesma nota, e o contrafactual dá 0 (ADR 0004).
- A IA só influencia a nota pelo que extrai, e só com citação literal verificada.
- Os pesos 0,70/0,20/0,10 são uma escolha de produto e não foram calibrados. As evals medem se a nota
  cai na faixa anotada (ADR 0005). Se os pesos mudarem, a mudança vem registrada aqui com o motivo.
- Cada obrigatório faltante tira até 70/n pontos (11,7 com 6 obrigatórios, antes da renormalização) e
  fica visível na decomposição. Não há corte automático (ADR 0004, sem rejeição automática).
