# ADR 0002 — Embeddings e taxonomia de competências

- **Status:** rascunho (fase 0; limiares calibrados e aceito na fase 3)
- **Data:** 2026-11-15

## Contexto

A correspondência entre requisito da vaga e competência do currículo é feita em código (ADR 0003). Ela
precisa reconhecer:
1. **grafias da mesma coisa**: "React.js", "ReactJS", "React"; "PostgreSQL", "Postgres";
2. **traduções**: "Gestão de projetos" e "Project management";
3. **competências relacionadas**, que valem parcial: Vue para quem pede React;
4. **falsos amigos**, que não podem casar: "JavaScript" não é "Java".

Restrições:
- **Privacidade:** as competências saem de currículos. Mandá-las para uma API de embeddings de terceiros
  amplia a superfície de dados pessoais (ADR 0004).
- **Determinismo:** a mesma entrada precisa dar a mesma nota, ou o teste contrafactual com o provedor
  falso deixa de dar 0.
- **Custo:** zero por análise. A meta total é US$ 0,10 (ADR 0005).
- **Explicável:** a tela precisa dizer por que um requisito foi atendido.

## Opções

### A. Só taxonomia YAML
Um arquivo com competências canônicas, sinônimos e "relacionadas".

- ✅ Determinística, explicável ("ReactJS é sinônimo de React") e revisável em PR.
- ✅ Resolve falsos amigos por construção: JavaScript e Java são entradas diferentes.
- ❌ Tudo que não está no arquivo vira "não atende". Vagas trazem termos novos o tempo todo.

### B. Embeddings por API externa
- ✅ Modelos maiores e melhores em termos raros.
- ❌ Manda texto derivado do currículo para mais um terceiro.
- ❌ Custo e latência por chamada, e dependência de rede nos testes.
- ❌ O modelo pode mudar do lado do fornecedor, e a mesma entrada passa a dar outra nota.

### C. Taxonomia primeiro, embeddings locais (fastembed) como reserva, vetores no pgvector
A taxonomia decide quando conhece o termo. Só os termos fora dela vão para a similaridade de cosseno
com um modelo ONNX local multilíngue, rodando no processo, sem GPU. Os vetores das competências
canônicas e dos termos já vistos ficam numa coluna `vector(384)` do Postgres (pgvector), com índice
HNSW por cosseno.

- ✅ Explicável quando a taxonomia decide, que deve ser a maioria dos casos.
- ✅ Cobre termos novos sem editar o YAML.
- ✅ Local: nada sai da máquina, custo zero e determinístico com o modelo fixado.
- ✅ pgvector já vem na imagem do Postgres e evita um segundo banco.
- ❌ Download do modelo na primeira execução e alguns centésimos de segundo de carga a mais.
- ❌ Embeddings de termos curtos são ruidosos (ver medições). Os limiares precisam de calibração, e o
  embedding nunca deve decidir "relacionada".

### D. Perguntar à IA se o requisito casa
- ✅ Entende contexto.
- ❌ Põe a IA dentro do cálculo da nota, que deveria ser só código, e perde o determinismo.
- ❌ Custo por par requisito × competência.

## Medições

Script: `apps/api/scripts/medir_embeddings.py`. Foi rodado em 2026-11-15 neste Windows 11
(Python 3.13.15, fastembed 0.9.1, CPU), com cache limpo para cada modelo.

`TextEmbedding.list_supported_models()` lista 41 modelos. Os multilíngues só de texto são:
- `paraphrase-multilingual-MiniLM-L12-v2` (384 dimensões, 0,22 GB);
- `paraphrase-multilingual-mpnet-base-v2` (768 dimensões, 1,0 GB);
- `multilingual-e5-large` (1024 dimensões, 2,24 GB);
- `jina-embeddings-v3` (2,29 GB, CC BY-NC);
- `embeddinggemma-300m` (licença Gemma);
- `Qwen3-Embedding-0.6B` (1,1 a 2,4 GB);
- `potion-multilingual-128M` (estático).

Medimos os dois `paraphrase-multilingual`. Eles são treinados para paráfrases curtas, que é o nosso
caso, têm licença Apache-2.0 e o tamanho é compatível com uma API num contêiner pequeno. O e5-large,
o Qwen3 e o jina ficam de fora pelo tamanho (mais de 2 GB) ou pela licença não comercial.

| Medida | MiniLM-L12-v2 | mpnet-base-v2 |
| - | - | - |
| Artefato baixado pelo fastembed | `Qdrant/…-onnx-Q` (quantizado) | `Xenova/…` |
| Download em disco | 252 MB | 1.127 MB |
| 1ª carga (download + sessão ONNX) | 9,4 s | 24,9 s |
| Carga com cache | 0,90 s | 1,85 s |
| Dimensão | 384 | 768 |
| Embutir 19 termos | 26 ms | 87 ms |
| Limite de entrada | 128 tokens | 512 tokens |

Similaridade de cosseno dos pares:

| Par | Esperado | MiniLM-L12-v2 | mpnet-base-v2 |
| - | - | - | - |
| React.js / ReactJS | mesma | 0,927 | 0,926 |
| Node / Node.js | mesma | 0,767 | 0,713 |
| PostgreSQL / Postgres | mesma | 0,567 | 0,707 |
| Gestão de projetos / Project management | mesma (tradução) | 0,963 | 0,966 |
| Inglês fluente / Fluent English | mesma (tradução) | 0,974 | 0,986 |
| Vue.js / React | relacionada | 0,330 | 0,159 |
| Docker / Kubernetes | relacionada | 0,478 | 0,330 |
| JavaScript / Java | diferente (falso amigo) | 0,441 | 0,288 |
| Python / Excel | diferente | 0,205 | 0,180 |
| Contabilidade / React | diferente | 0,318 | 0,228 |

Os tempos vêm de uma execução só, e a carga varia com o disco. A amostra tem 10 pares e serve para
escolher o modelo e checar se os limiares fazem sentido, não para calibrá-los.

Leitura:
1. **Traduções e grafias com pontuação** ficam acima de 0,92 nos dois modelos. É aqui que o embedding
   ajuda.
2. **Abreviações** ficam abaixo de τ_alto nos dois. "Postgres" dá 0,567 no MiniLM, que é "não atende".
   Abreviação comum tem que estar na taxonomia como sinônimo, e não pode depender do embedding.
3. **"Relacionada" não é similaridade.** Vue/React (0,16–0,33) e Docker/Kubernetes (0,33–0,48) ficam
   abaixo de todos os sinônimos e na mesma faixa dos pares diferentes. Só a taxonomia marca
   "relacionadas".
4. **Falso amigo:** JavaScript/Java dá 0,441 no MiniLM, bem abaixo de τ_baixo = 0,70. O par diferente
   mais alto da amostra é Docker/Kubernetes, com 0,478, e fica 0,22 abaixo de τ_baixo.

## Decisão

**Opção C**, com `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.
- **Qualidade:** separa sinônimos de diferentes tão bem quanto o mpnet nesta amostra. A menor
  similaridade entre traduções foi 0,963 e a maior entre diferentes, 0,478.
- **Custo de rodar:** tem 1/4 do tamanho e a metade do tempo de carga do mpnet.
- **Dimensão:** 384 dimensões mantêm o índice pequeno.
- **Limite de entrada:** o limite de 128 tokens não pesa, porque embutimos nomes de competências e não
  frases.

Ordem da correspondência (ADR 0003):
1. Normaliza o termo: caixa, acentos, espaços e pontuação nas pontas. Ficam `#` e `+` (para "C#" e
   "C++" não virarem "c") e o "." inicial (para ".NET" não virar "net"); o "." final sai.
2. Procura na taxonomia por nome canônico ou sinônimo. Achou: mesma canônica dá **atende**, e uma das
   "relacionadas" dá **parcial**.
3. Fora da taxonomia, calcula o cosseno contra as canônicas e os termos já vistos:
   - ≥ τ_alto dá **atende**;
   - entre τ_baixo e τ_alto dá **parcial**;
   - abaixo de τ_baixo dá **não atende**.
4. Registra, para a tela e para as evals, qual regra decidiu ("sinônimo na taxonomia", "similaridade
   0,93").

**Limiares iniciais:** mantemos τ_alto = **0,85** e τ_baixo = **0,70**. As medições não pedem outros
valores. Os dois sinônimos com pontuação e as duas traduções passam folgados de 0,85 (o menor é React.js
com 0,927), e os pares diferentes ficam todos abaixo de 0,48. A faixa parcial (0,70–0,85) pega casos
como Node/Node.js (0,767), que deveriam estar na taxonomia de qualquer forma. A calibração final, com os
pares anotados das evals, sai na fase 3 e vem registrada aqui.

**Taxonomia** em `apps/api/src/curriculo_api/dados/taxonomia.yaml` (caminho e formato atualizados na
fase 1, D-14), carregada por `curriculo_api.taxonomia`:

```yaml
versao: 1
competencias:
  - canonica: React
    categoria: frontend
    sinonimos: [React.js, ReactJS, React JS]
    relacionadas: [Angular, Vue.js]
  - canonica: PostgreSQL
    categoria: banco-de-dados
    sinonimos: [Postgres, PSQL]
    relacionadas: [MySQL, Oracle Database]
```

A `versao` entra no resultado das evals e, na fase 3, no prefixo de cache do prompt. Validada por
Pydantic na carga:
- nenhum termo (canônica ou sinônimo, já normalizado) pode aparecer em duas entradas;
- "relacionada" precisa existir como canônica;
- a relação é simétrica (se Vue lista React, React lista Vue).

**Sinônimo é a mesma coisa**, com outra grafia, abreviação ou tradução ("Postgres", "k8s", "MS Excel",
"English"). Produto de uma categoria (Tasy para prontuário eletrônico), protocolo de uma área (TCP/IP
para redes) ou parte de um processo (triagem de currículos em recrutamento e seleção) entram como
canônicas próprias **relacionadas**, não como sinônimos.

**Modelo e cache:** o modelo é fixado pelo nome e baixado do Hugging Face pelo próprio fastembed, a
fonte oficial da biblioteca, para `data/modelos/`, que fica fora do git. O CI não baixa modelo: os
testes usam um embutidor falso determinístico atrás da mesma interface.

## Consequências

- A taxonomia é parte do produto. Abreviações e sinônimos comuns ("Postgres", "Node", "JS", "k8s",
  "Inglês avançado") precisam estar nela, e as evals medem o quanto ainda cai no embedding.
- No Windows sem modo de desenvolvedor, o `huggingface_hub` avisa que não consegue criar symlinks e
  guarda cópias. É inofensivo: os 252 MB medidos já são o tamanho em disco nesse modo.
- A primeira análise depois de um contêiner novo paga o download (cerca de 9 s aqui). A imagem de
  produção baixa o modelo no build.
- Trocar de modelo invalida os vetores guardados, e eles precisam ser recalculados. Por isso a tabela
  guarda o nome do modelo junto com cada vetor.
