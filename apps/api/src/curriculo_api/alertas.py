"""Alertas da ingestão (ADR 0004). Sinalizam, nunca punem: a nota não usa alerta nenhum.

- `texto_oculto`: texto que a pessoa não vê no documento (fonte < 4 pt, cor ≈ fundo, fora da
  página, modo de renderização invisível, `w:vanish`). Sai do texto analisado; o alerta mostra o
  trecho.
- `instrucao_para_ia`: frase com cara de instrução ao modelo ("ignore as instruções…"). Continua no
  texto (é conteúdo visível), e a fase 3 a delimita como dado.
- `pdf_sem_texto`: página só com imagem (PDF escaneado); sem OCR nesta versão.
- `comentario_nao_lido`: o DOCX tem comentários com texto, que não são lidos.
- `formulario_nao_lido`: o PDF tem campos de formulário preenchidos, cujo texto não é lido.
- `nome_nao_identificado`: a anonimização não achou o nome no topo e não apagou nada por palpite.

O `trecho` é conteúdo do currículo: vai para a tela, nunca para os logs (fica fora do `repr`).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TipoAlerta = Literal[
    "texto_oculto",
    "instrucao_para_ia",
    "pdf_sem_texto",
    "formulario_nao_lido",
    "comentario_nao_lido",
    "nome_nao_identificado",
]


class Alerta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tipo: TipoAlerta
    origem: Literal["curriculo", "vaga"]
    trecho: str = Field(repr=False)
    motivo: str | None = Field(default=None, description="Por que o alerta disparou, em pt-BR.")
    pagina: int | None = Field(default=None, ge=1, description="Página do PDF, quando se sabe.")
