# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Principal: quem procura emprego.** Tem um currículo (PDF, DOCX ou texto) e uma vaga específica que
  quer disputar. O trabalho é entender, antes de se candidatar, o quanto o currículo atende a vaga, o que
  falta comprovar e como reescrever trechos sem inventar nada. Volta quando ajusta o currículo e compara
  versões.
- **Secundário: recrutador.** Faz uma triagem de até 20 currículos para uma vaga com a visão
  anonimizada (sem nome, foto, idade, gênero, endereço, contatos) e registra a decisão, que é sempre
  humana.
- **Quem de fato avalia o projeto:** recrutadores e líderes técnicos que chegam pelo portfólio. Eles
  precisam ver um produto que funciona e, logo, o rigor por trás dele: nota explicada, defesa contra
  prompt injection, cuidado com viés e privacidade.

## Product Purpose

Recebe um currículo e uma vaga e devolve uma nota de aderência de 0 a 100 que se explica sozinha: cada
requisito da vaga ligado (ou não) a um trecho literal do currículo, as parcelas da nota, as lacunas, as
palavras-chave de ATS e reescritas antes/depois. Sucesso é a pessoa saber exatamente por que tirou a
nota e o que mudar, e confiar no número porque consegue conferir cada parte.

## Positioning

A nota é calculada por código, não pela IA: a IA (quando ligada) só extrai itens com citação literal,
e o que não tem trecho no currículo é descartado. Reescritas só podem usar competências que já têm
evidência; o que falta vai para "o que aprender", nunca para "o que escrever". Antes de qualquer
análise, o currículo é anonimizado e varrido atrás de texto oculto e frases de prompt injection. Um
analisador comum dá um número opaco e sugere palavras-chave para colar; este mostra a conta e se
recusa a inventar.

## Operating Context

- Fluxo do candidato: enviar currículo (PDF/DOCX ou colar texto) e vaga → acompanhar as etapas em
  tempo real (leitura, anonimização, extração, correspondência, nota, feedback) → ler o resultado →
  exportar PDF → voltar depois e comparar com a versão anterior.
- Fluxo do recrutador: criar uma triagem, enviar até 20 currículos, ver a lista anonimizada com notas
  e evidências, registrar a decisão de cada um.
- Privacidade é parte do uso: retenção configurável, "apagar meus dados", lista do que foi removido
  na anonimização.
- Uso em computador na maior parte (documento e vaga lado a lado), mas o resultado precisa ser legível
  no celular.

## Capabilities and Constraints

- Backend pronto (FastAPI, fila arq, SSE das etapas, Postgres + pgvector, Redis). Front em Next.js 16 /
  React 19, ainda vazio; CSS puro até a escolha de estilo (D-04).
- **Modo demonstração por regras é o padrão** (ADR 0006): análise sem IA, sem rede e sem custo, pela
  mesma ancoragem, nota e filtro. A interface deve dizer isso com clareza: "modo demonstração: análise
  por regras, sem IA". O provedor Anthropic existe, mas só roda pedido explicitamente.
- Fórmula da nota (ADR 0003): obrigatórios 70 %, desejáveis 20 %, senioridade 10 %, com pesos
  renormalizados quando falta um componente. A tela mostra cada parcela, por exemplo
  `obrigatórios 4,5 de 6 → 52,5 · desejáveis 1 de 3 → 6,7 · senioridade 4/5 anos → 8,0 · nota 67`.
- Cada requisito tem estado **atende (1,0)**, **parcial (0,5)** ou **não atende (0)**, com o trecho que
  comprova.
- Avisos que a interface precisa mostrar: texto oculto detectado, frase de injection detectada, PDF sem
  texto, vaga sem requisitos reconhecíveis, modelo de embeddings ausente (só taxonomia).
- O SSE envia fragmentos do JSON do feedback; a forma de exibir é decisão da fase 6.
- Interface só em **pt-BR**. Mercado brasileiro (LGPD, CPF).
- **Em aberto:** nome do produto (sai nesta fase; registrar em `docs/decisoes.md`).

## Evidence on Hand

- 30 casos fictícios de currículo × vaga em `evals/` e relatórios em `docs/evals.md` (provedor falso)
  e `docs/evals-regras.md` (regras). Servem de dados de exemplo para a landing e as telas.
- Seed de demonstração (`make seed`, conta `demo@curriculo.dev`).
- **Não existe e não pode ser inventado:** depoimentos, clientes, números de uso, e qualquer métrica
  medida com o modelo real (precisão, custo, latência, resistência a injection com IA; D-46). Esses
  números só aparecem como "não medidos".

## Product Principles

1. **Toda afirmação tem um trecho.** Nada aparece no resultado sem a citação do currículo que o
   sustenta, ou sem dizer que falta.
2. **A conta é visível.** A nota nunca chega sozinha; as parcelas e os requisitos vêm junto.
3. **Não inventar a pessoa.** Ajudar a dizer melhor o que é verdade, nunca a afirmar o que não há.
4. **Honestidade sobre o modo.** Deixar sempre claro se a análise foi por regras ou por IA, e o que
   não foi medido.
5. **Privacidade antes do conteúdo.** Anonimizar primeiro, mostrar o que foi removido, apagar quando
   pedirem.

## Accessibility & Inclusion

- Estados atende / parcial / não atende nunca só por cor: sempre com rótulo ou ícone e texto.
- Progresso em tempo real anunciado para leitores de tela (região viva), e animações com
  `prefers-reduced-motion`.
- Meta WCAG 2.2 AA; checagem com axe na fase 7.
- O modo recrutador existe para reduzir viés: nenhum dado pessoal removido pode aparecer na visão
  anonimizada.
