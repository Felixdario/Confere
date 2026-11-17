---
name: Confere
description: Analisador de currículos que só aceita o que está escrito, item por item, com a conta da nota à vista.
colors:
  carimbo: '#1F4FD8'
  carimbo-claro: '#6F8BFF'
  carimbo-fundo: '#E6ECFC'
  tinta: '#16182A'
  suave: '#5E6172'
  papel: '#F7F7F4'
  folha: '#FFFFFF'
  moldura: '#F1F0EC'
  borda-folha: '#E7E6E1'
  noite: '#0E1426'
  noite-superficie: '#18203A'
  noite-tinta: '#FFFFFF'
  noite-suave: '#B9C3E6'
  confere: '#1F4FD8'
  parcial: '#8F5A00'
  parcial-fundo: '#FBF0DC'
  nao-consta: '#C42B2B'
  nao-consta-fundo: '#FBE6E4'
  aviso-tinta: '#8F5A00'
  aviso-fundo: '#FBF0DC'
typography:
  display: 'Libre Franklin 700'
  texto: 'Source Serif 4 400/600, itálico para citações'
  interface: 'Libre Franklin 400/500/600 (telas do app)'
radius:
  landing: 0
  folha: 16
  controle: 0
status: contrato de partida (fase 5); revisar a partir do que for construído no fim da fase 6
---

# Design — Confere

O mundo é a **autenticação de cartório**: a folha de ofício conferida contra o original, e o carimbo
"confere com o original" sobre o que foi comprovado. Este arquivo guarda as decisões duradouras de cor,
tipo, forma, componentes e movimento. Como cada tela usa isso está em
[`docs/design/direcao.md`](docs/design/direcao.md).

## 1. O motivo: o carimbo

Uma forma só, em três ou quatro escalas muito diferentes: **um retângulo de tinta chapada, cantos retos,
com o texto vazado em caixa alta**. É o carimbo visto de perto.

| Escala | Onde | Como |
| - | - | - |
| Gigante | Hero da landing | "CONFERE COM O ORIGINAL" a ~120vh de largura, cortado pela borda, inclinado a −3°, atrás da folha de exemplo. |
| Grande | Estado do requisito no showcase, nota no resultado | Carimbo de 64–120 px de altura, inclinado de −2° a −4° (ângulo fixo por item, nunca aleatório a cada renderização). |
| Texto | Estado na tabela, marcador de lista, botões | Retângulo reto, sem inclinação, para não atrapalhar a leitura em linhas. |
| Faixa | Divisão da landing, topo do cartão do hero | Faixa de segurança do selo: barras de 28 px alternando tinta e papel. |

Nunca um segundo motivo (círculo, selo redondo, blob). O carimbo é sempre preenchido. Uma moldura de
carimbo em linha fina é proibida pelas regras da casa.

## 2. Cor

**Estratégia.** Landing: *Committed*. O azul de carimbo e o campo azul-noite são donos de regiões
inteiras: o showcase, o cta e o rodapé em `noite`, e um painel em `carimbo`. O miolo fica em `papel` e
`folha`. Telas do app: *Restrained*. A moldura e a folha são neutras, e a cor só aparece nos estados dos
requisitos, no sublinhado da aba ativa e na ação principal (menos de 3 % da tela).

**Cena física.** Quem procura emprego lê o resultado à noite ou no intervalo, num notebook ao lado da
vaga aberta: precisa de papel claro e texto escuro para ler trechos longos. Por isso o app é claro. O
escuro fica só nos campos de cor da landing.

**Papéis**

- `papel` é o fundo da landing; `folha` é a folha de ofício (sempre branca); `moldura` é o L tingido
  do app (pedra).
- `tinta` é o texto corrido (sempre a tinta cheia, nunca cinza); `suave` só para notas secundárias.
- `carimbo` serve à ação principal, ao estado "confere", à aba ativa e aos links. Ele dá 6,6:1 sobre
  branco.
- `noite` é o campo escuro da landing. Sobre ele, o botão é `folha` com texto `tinta`, e o carimbo usa
  `carimbo-claro` (5,9:1).
- Estados: `confere` (azul), `parcial` (âmbar escuro, 5,8:1), `nao-consta` (vermelho, 5,6:1), cada
  um com um fundo pálido para a linha da tabela.

**Estados nunca só por cor.** Cada estado tem palavra e forma:

| Estado | Palavra do carimbo | Valor | Forma |
| - | - | - | - |
| Atende | CONFERE | 1,0 | carimbo cheio em `confere` |
| Parcial | EM PARTE | 0,5 | carimbo cheio em `parcial` |
| Não atende | NÃO CONSTA | 0 | carimbo cheio em `nao-consta`, na margem (não há trecho para cobrir) |

**Tradução registrada.** O carimbo de cartório costuma ser violeta, mas violeta e índigo são proibidos
pelas skills (é a paleta padrão de assistente). A tinta é o azul de carimbo, também comum. Sem
exceção de inspetor para isso.

## 3. Tipo

- **Libre Franklin 700** para o display: tracking −0,035em, entrelinha 0,92. Caixa alta só no título do
  hero, no texto dos carimbos e na marca; os títulos de seção vão em caixa de frase.
- **Source Serif 4** para o texto da landing (400, 600 para ênfase, itálico para citação), com
  entrelinha 1,55 e linhas de 45 a 75 caracteres.
- **No app**, a interface é Libre Franklin (400/500/600). A Source Serif 4 fica para **o texto do
  currículo e da vaga**: todo trecho citado aparece em serifa. A serifa é o documento; o grotesco é a voz
  do sistema. Essa regra é o que identifica o produto nas telas.
- Algarismos tabulares (`font-variant-numeric: tabular-nums`) em notas, parcelas e tabelas. Vírgula
  decimal ("4,5 de 6").
- Escala da landing, cinco passos no máximo:

```css
:root {
  --passo-pequeno: clamp(0.8125rem, 0.79rem + 0.1vw, 0.875rem); /* nunca menos de 13 px */
  --passo-texto: clamp(1.0625rem, 1rem + 0.25vw, 1.1875rem);
  --passo-destaque: clamp(1.25rem, 1.1rem + 0.7vw, 1.625rem);
  --passo-titulo: clamp(2rem, 1.3rem + 3.2vw, 4rem);
  --passo-hero: clamp(3rem, 1rem + 7vw, 8.5rem);
}
```

- No app: corpo 15–16 px, rótulos 14 px, título da tela 24 px e a nota do resultado em 96–120 px. Ela é
  o maior número da tela (a disciplina do cartaz: o maior número é a porta).
- Sem monoespaçada, nem para ids: id de análise em Libre Franklin com algarismos tabulares.

## 4. Espaço e forma

- Landing: um grid de 12 colunas, margens externas iguais de 12 px (≥ 1024 px: 24 px) e 120–240 px
  entre seções. Cantos retos em tudo; a folha de exemplo do hero também é reta.
- App (`framed-sheet`): moldura em L com barra lateral de 228 px e barra superior de 48 px no mesmo tom,
  sem fio entre elas. A folha `folha` fica com 8 px de recuo das bordas direita e inferior, canto de
  16 px, borda de 1 px em `borda-folha` e nenhuma sombra. Dentro dela, 24 px de respiro e no máximo três
  níveis (moldura, folha, cartão).
- Botões: retangulares, cantos retos, preenchimento chapado, altura de 44 px (52 px no celular). Um
  formato só no produto inteiro.

## 5. Componentes

- **Botão principal.** Fundo `carimbo` e texto `folha` em Libre Franklin 600. Ao pressionar, é o gesto do
  carimbo: escala 0,97 por 90 ms e volta. Foco visível com contorno de 2 px em `tinta`, deslocado 2 px.
- **Carimbo de estado.** É um `<span>` com o texto real ("CONFERE"), não uma imagem, e um rótulo
  acessível completo ("Atende: 1,0").
- **Trecho.** Citação em Source Serif 4 itálico, com o carimbo `confere` sobreposto na borda e um link
  para a posição no texto do currículo.
- **Linha de requisito.** Requisito, obrigatório ou desejável, carimbo, valor, trecho. As tabelas podem
  ter fios (são tabelas de verdade), em `borda-folha`.
- **A conta da nota.** Uma linha com as parcelas, `obrigatórios 4,5 de 6 → 52,5 · desejáveis 1 de 3 →
  6,7 · senioridade 4/5 anos → 8,0 · nota 67`, montada com os mesmos números da tabela, nunca digitada à
  parte.
- **Reescrita antes/depois.** Duas colunas na folha: antes em `suave`, depois em `tinta`, e embaixo o
  trecho que autoriza a reescrita.
- **Selo do modo.** "Modo demonstração: análise por regras, sem IA", sempre visível e em texto, não ícone.
- **Avisos.** Faixa em `aviso-fundo` com texto em `aviso-tinta`: texto oculto, injection, PDF sem texto,
  embeddings ausentes. Diz o que aconteceu e o que foi feito.
- **Versões.** Folhas empilhadas com 6 px de deslocamento; as anteriores com a opacidade do texto em
  0,6, como papel térmico velho, mas ainda legíveis.

## 6. Movimento

- **Assinatura: o carimbo cai.** A escala vai de 1,15 a 1, a opacidade de 0 a 1 e a rotação de −6° ao
  ângulo final, em 180 ms com `cubic-bezier(0.2, 0.9, 0.3, 1)`, e mais um abaixamento de 1 px no
  impacto. Só `transform` e `opacity`.
- Etapas da análise: cada etapa é carimbada ao terminar, com o mesmo gesto menor (120 ms).
- Revelação da nota: os algarismos ficam em casas fixas e se acertam da esquerda para a direita, num
  evento visível só.
- Landing: entrada por seção (título, texto e figura, defasados em 60–90 ms, subindo 24 px) e um
  crossfade lento entre as fotos de acervo.
- Com `prefers-reduced-motion`, nada se desloca: o carimbo aparece direto no lugar, e o conteúdo nunca
  depende da animação para existir.

## 7. Proibido aqui

Gradiente, sombra em repouso, vidro, rótulo pequeno acima do título, numeração 01/02/03, monoespaçada,
fios finos decorativos, cards com ícone, violeta/índigo, creme com terracota, emoji, números de uso
inventados, depoimentos, logos de clientes, e qualquer métrica do modelo real apresentada como medida
(D-46).
