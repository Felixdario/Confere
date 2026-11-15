# Evals

Aqui fica o dataset de avaliação do pipeline: 25–30 pares fictícios de currículo e vaga, com variantes
de prompt injection e contrafactuais (nome, gênero, idade), anotados com competências esperadas, faixa
de nota e lacunas. Chega na **fase 1**.

- `make eval` roda o harness com o provedor falso e gera `docs/evals.md`, comparando com a execução
  anterior. Por enquanto só avisa que o harness chega na fase 1.
- `make eval PROVEDOR=anthropic` usa a API real e só roda sob comando, com a chave do usuário. Nunca no CI.
- Metas e definições das métricas: [ADR 0005](../docs/adr/0005-metas-das-evals.md).

Todos os dados são fictícios. Nenhum currículo real entra neste diretório.
