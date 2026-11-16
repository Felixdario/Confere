"""Alertas da ingestão (ADR 0004). A detecção chega na fase 2; o tipo já é usado pelas evals."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

TipoAlerta = Literal["texto_oculto", "instrucao_para_ia"]


class Alerta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tipo: TipoAlerta
    origem: Literal["curriculo", "vaga"]
    trecho: str
