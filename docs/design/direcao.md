# Direção de design — Confere

Fase 5. O mundo visual e o sistema estão em [`DESIGN.md`](../../DESIGN.md); a verdade do produto, em
[`PRODUCT.md`](../../PRODUCT.md). Este arquivo diz como a landing e cada tela usam esse mundo, para a
fase 6 construir sem reinventar.

## Como a direção foi escolhida

- **Mundo (impeccable, sorteio de direção, `seed:4b9a3ce4adaa5145`).** Sete candidatos tirados do mundo
  de quem procura emprego no Brasil: autenticação de cartório, gabarito do ENEM, cupom fiscal, carteira
  de trabalho, boletim escolar, marca-texto, bula de remédio. O sorteio indicou o cupom fiscal. O
  usuário escolheu a autenticação de cartório (**"Confere com o original"**), a primeira da minha
  lista. Os seis desafiantes do catálogo foram recusados; deles ficaram três disciplinas: o maior
  número é a porta (cartaz de rua), um eixo vertical ordena as etapas (mergulho) e as versões
  empilhadas, as antigas esmaecidas, mostram a cronologia (adesivos).
- **Landing (design-taste-frontend, seed 1319795672).** Direção `one-motif`: uma forma tirada do
  assunto comanda todo o sistema. A paleta sorteada (preto-ameixa e rosa) brigava com o mundo e foi
  trocada pelas cores do próprio assunto, mantendo as proporções (veja `DESIGN.md`).
- **Telas do app (seed 1900075068).** Estilo `framed-sheet`: moldura tingida em L e o trabalho numa
  folha branca. Aqui a folha é literalmente a folha de ofício com o documento conferido.

**Tradução registrada.** No cartório, o carimbo costuma ser violeta. As regras das duas skills proíbem
violeta e índigo (é a paleta padrão de assistente), então a tinta virou o **azul de carimbo**, que
também é comum nos cartórios. A forma, o gesto e as palavras do carimbo ficam iguais.

## A ideia

> Nesta página, **o carimbo "confere com o original" do cartório** vira **o motivo único**: o
> retângulo de tinta que marca cada requisito comprovado, o botão, o marcador de lista e a faixa que
> divide a página.

Teste do concorrente: outro analisador de currículo não confere trecho por trecho e não se recusa a
afirmar o que não está escrito. Na boca dele, a frase é falsa, então a ideia é deste produto.

**A coisa viva da landing: "Confira você mesmo".** Um caso de exemplo do dataset (`b01-frontend-senior`,
fictício e rotulado como exemplo) aparece como vaga + currículo. A pessoa toca num requisito da vaga, e o
carimbo cai sobre o trecho exato do currículo que o comprova ("CONFERE"). Quando não há trecho, o
carimbo vermelho "NÃO CONSTA" cai na margem. Funciona com teclado e no celular com o polegar. Sem
script, aparece a tabela estática requisito × trecho.

## Landing (modo Persuadir)

### O argumento (uma afirmação por seção)

| Seção | Afirmação | Prova |
| - | - | - |
| Hero | Você vê, antes de se candidatar, o quanto o currículo atende a vaga. | O formulário de verdade e uma folha de exemplo já carimbada. |
| showcase | Só conta o que está escrito. | "Confira você mesmo": o carimbo cai no trecho ou "não consta". |
| how-it-works | A nota é uma conta que você pode refazer. | As seis etapas, da leitura ao feedback, com a fórmula 70/20/10. |
| features | Ele protege você e não inventa nada. | Anonimização, texto oculto, injection, reescritas só com evidência. |
| proof | Foi testado, e o que não foi medido está dito. | 30 casos; números do modo regras; "não medido" carimbado onde cabe (D-46). |
| faq | As dúvidas antes de enviar um documento pessoal. | Modo demonstração, privacidade, apagar dados, recrutador. |
| cta | Comece agora, sem conta para o exemplo. | A tela de nova análise já aberta. |
| footer | Confere. | O nome construído em blocos de carimbo. |

### Texto do primeiro viewport

- `h1` (Libre Franklin 700, caixa alta, duas linhas): **SEU CURRÍCULO, / CONFERIDO.**
- Frase de apoio: "Cole a vaga, envie o currículo e veja cada requisito com o trecho que o comprova,
  ou a falta dele."
- Ação principal (botão-carimbo): **Enviar currículo**. Abre o seletor de arquivo e leva para a nova
  análise com o arquivo e o campo da vaga.
- Junto do botão, sempre visível: "Modo demonstração: análise por regras, sem IA."
- Links: Ver um exemplo · Como a nota é feita · Privacidade.

### Composição (do blueprint sorteado, adaptado)

- **Hero, "cartão ao lado da sala".** 50/50, margens de 12 px. À esquerda, o cartão de papel com a faixa
  de segurança do selo (barras alternadas de tinta e papel) no topo, a marca, o `h1`, a frase, o botão e
  os links. À direita, fixa ao rolar (`sticky`), a folha de ofício com o currículo de exemplo, e três
  carimbos já pousados. Um carimbo gigante "CONFERE COM O ORIGINAL", cortado pela borda da tela, inclinado
  a −3°, entra pela direita atrás da folha. No celular, a folha vem primeiro (48svh) e o cartão sobrepõe
  a borda dela em 24 px.
- **showcase, "um controle, ampliado".** Campo azul-noite em página inteira. O controle é a lista de
  requisitos do exemplo em tamanho de cartaz; tocar num requisito carimba o trecho e troca uma palavra do
  título ("Só conta o que está **escrito**" ↔ "Isto **não consta**").
- **how-it-works, "sanfona de painéis tingidos".** Seis painéis do escuro ao claro na mesma cor: Leitura,
  Anonimização, Extração, Conferência, Nota, Feedback. São as mesmas etapas da tela de progresso. O
  painel Nota mostra a conta do exemplo,
  `obrigatórios 4,5 de 6 → 52,5 · desejáveis 1 de 3 → 6,7 · senioridade 4/5 anos → 8,0 · nota 67`.
- **features, "frases com chaves".** Cinco faixas, cada uma com uma frase e uma chave. Ligada, a faixa
  ganha cor e uma segunda linha com o fato:
  1. "Tira seu nome antes de ler." → nome, foto, idade, gênero, estado civil, endereço, CPF, telefone e e-mail.
  2. "Encontra texto escondido no PDF." → fonte abaixo de 4 pt, cor igual à do fundo, fora da página.
  3. "Ignora ordens escondidas no currículo." → frases de injection sinalizadas, nota calculada sem elas.
  4. "Reescreve só o que você comprovou." → reescrita com competência sem trecho é descartada.
  5. "Mostra a conta da nota." → 70 % obrigatórios, 20 % desejáveis, 10 % senioridade.
- **proof, "marcas grandes em ladrilhos".** Não há logos nem clientes, e nada disso é inventado. Cada
  ladrilho traz uma métrica das evals com o valor medido no modo regras e um carimbo: "medido · regras"
  ou "não medido" (custo, latência e extração com o modelo, D-46). O primeiro ladrilho, duplo e azul,
  tem o título "O que foi testado".
- **faq, "fichas de arquivo com abas".** Fichas sobrepostas como num arquivo de cartório: Modo
  demonstração, Privacidade, A nota, Recrutador, Prompt injection, Apagar meus dados.
- **cta, "o primeiro passo já aberto".** Campo azul; à direita, a caixa real de nova análise (arquivo,
  vaga, botão). À esquerda, embaixo: "CONFIRA O SEU." e a frase do que acontece depois.
- **footer, "a marca construída".** CONFERE em blocos retangulares de tinta com as letras vazadas, alturas
  diferentes e 4 px entre eles. Depois os links, e o crédito das imagens de acervo.

### Imagens (piso de 4 imagens reais)

- Fragmentos da própria interface em HTML (`data-ui`): a folha carimbada, a tabela de requisitos, a
  caixa de nova análise. Contam para o piso.
- Do acervo aberto (fase 6, `assets.mjs`, com crédito no rodapé): carimbos e almofadas de carimbo,
  documentos autenticados antigos, máquina de escrever, arquivo de fichas. Mostram o mundo do cartório e
  nunca se passam pelo produto.
- O movimento sorteado ("crossfade lento") entra nessas fotos de acervo. O momento alto é o carimbo
  caindo.

## Telas do app (modo Operar, estilo `framed-sheet`)

Moldura em L na cor pedra (`--moldura`), folha branca com 8 px de recuo, cantos de 16 px e sem sombra.
O selo "Modo demonstração: análise por regras, sem IA" fica fixo na barra de cima, à direita, em todas
as telas.

| Tela | Pergunta da tela | O achado em primeiro lugar | Blocos (na ordem) |
| - | - | - | - |
| Nova análise | O que falta para começar? | — | Currículo (arquivo ou texto colado), vaga (texto), avisos de formato e tamanho junto do campo, Analisar. |
| Progresso | Em que etapa está? | A etapa atual e o tempo decorrido. | As seis etapas num eixo vertical, carimbadas ao terminar (região viva `aria-live`). O feedback vai preenchendo as seções do resultado pelo JSON parcial do SSE, em vez de mostrar o texto cru. |
| Resultado | Por que tirei essa nota e o que mudo? | "Faltam 2 de 6 obrigatórios: Docker e Kubernetes." | Nota (o maior número da tela) com a conta ao lado; tabela requisito × estado × trecho (o trecho em serifa, como citação); o que aprender; reescritas antes/depois; palavras-chave de ATS; avisos (o que foi removido, texto oculto, injection); Exportar PDF. |
| Histórico | Melhorei desde a última versão? | "67, +9 em relação à versão de 12/11." | Análises por vaga; as versões empilhadas como folhas, as antigas esmaecidas; a comparação mostra a mudança por requisito ("Docker: não consta → confere"). |
| Recrutador | Quem atende os obrigatórios? | "7 de 20 atendem todos os obrigatórios." | Triagem anonimizada ("Candidato 07", sem nome nem foto), nota, obrigatórios x de y e decisão humana (avançar, não avançar, pendente) com justificativa. Nenhum dado removido aparece. |
| Privacidade | O que vocês guardam e por quanto tempo? | A retenção atual em dias. | Configurações em duas colunas: retenção, o que é removido, exportar e apagar meus dados (ação destrutiva com confirmação). |

Estados obrigatórios em todas: vazio (sem análises ainda), carregando, erro com a mensagem da API
("o PDF não tem texto", "a vaga não tem requisitos reconhecíveis"), sem rede e o aviso de embeddings
ausentes.

## Para a fase 6

- O nome e a marca: **Confere** (D-56).
- Fontes pelo `next/font` (Libre Franklin e Source Serif 4), sem link externo em produção.
- CSS: continuar com CSS puro e tokens (D-04). A decisão final de estilo e de bibliotecas fica com a
  pick-ui-library.
- Checagens: `lint.mjs` e `inspect.mjs` (landing) e `inspect.mjs --app` (telas), na build de produção.
- No fim da fase 6, o `DESIGN.md` é revisado a partir do que foi construído (o impeccable pede que ele
  descreva o mundo construído). O desta fase é o contrato de partida.
