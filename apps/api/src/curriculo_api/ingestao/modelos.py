"""O que a ingestão produz: um `DocumentoLido` único para PDF, DOCX e texto colado."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from curriculo_api.alertas import Alerta
from curriculo_api.config import Settings

Origem = Literal["pdf", "docx", "texto"]
MotivoOculto = Literal[
    "fonte_minuscula",
    "cor_do_fundo",
    "fora_da_pagina",
    "renderizacao_invisivel",
    "docx_oculto",
    "texto_comprimido",
    "invisivel_na_renderizacao",
]

DESCRICAO_MOTIVO: dict[MotivoOculto, str] = {
    "fonte_minuscula": "fonte menor que 4,5 pt",
    "cor_do_fundo": "cor do texto igual (ou quase) à cor do fundo",
    "fora_da_pagina": "texto fora da área visível da página",
    "renderizacao_invisivel": "texto em modo de renderização invisível",
    "docx_oculto": "texto marcado como oculto no Word",
    "texto_comprimido": "texto espremido ou com letras empilhadas até ficar ilegível",
    "invisivel_na_renderizacao": "texto que não aparece na página desenhada (coberto, recortado, "
    "transparente ou sem contraste)",
}


class _Modelo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TrechoOculto(_Modelo):
    texto: str = Field(repr=False)
    motivo: MotivoOculto
    pagina: int | None = Field(default=None, ge=1)


class ImagemEncontrada(_Modelo):
    """Uma imagem do documento (provável foto). Nunca vai para a IA: só a contagem é usada."""

    pagina: int | None = Field(default=None, ge=1)
    largura: float | None = None
    altura: float | None = None


class DocumentoLido(_Modelo):
    origem: Origem
    texto: str = Field(repr=False, description="Só o texto visível, já normalizado.")
    ocultos: tuple[TrechoOculto, ...] = ()
    imagens: tuple[ImagemEncontrada, ...] = ()
    paginas: int | None = Field(default=None, ge=0)
    paginas_sem_texto: tuple[int, ...] = Field(
        default=(),
        description=(
            "Páginas do PDF cujo texto não é selecionável: só imagem (escaneadas) ou pouco texto"
            " com o resto em imagem ou desenhado como vetor (exportação do Canva e afins)."
        ),
    )
    comentarios_nao_lidos: int = Field(
        default=0, ge=0, description="Comentários do DOCX com texto (não são lidos)."
    )
    campos_de_formulario: int = Field(
        default=0, ge=0, description="Campos de formulário do PDF com valor (o texto não é lido)."
    )
    alertas: tuple[Alerta, ...] = ()


@dataclass(frozen=True)
class Limites:
    tamanho_max_bytes: int = 5 * 1024 * 1024
    paginas_max: int = 20
    descompactado_max_bytes: int = 30 * 1024 * 1024
    entradas_zip_max: int = 1000
    texto_max_caracteres: int = 60_000
    tempo_max_por_pagina_s: float = 5.0
    documento_xml_max_bytes: int = 5 * 1024 * 1024

    @classmethod
    def de_settings(cls, settings: Settings) -> Limites:
        return cls(
            tamanho_max_bytes=settings.ingestao_tamanho_max_bytes,
            paginas_max=settings.ingestao_paginas_max,
            descompactado_max_bytes=settings.ingestao_descompactado_max_bytes,
            entradas_zip_max=settings.ingestao_entradas_zip_max,
            texto_max_caracteres=settings.ingestao_texto_max_caracteres,
            tempo_max_por_pagina_s=settings.ingestao_tempo_max_por_pagina_s,
            documento_xml_max_bytes=settings.ingestao_documento_xml_max_bytes,
        )
