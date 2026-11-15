"""Aplicação FastAPI. OpenAPI em `/docs`."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from curriculo_api import __version__
from curriculo_api.config import obter_settings

app = FastAPI(
    title="Analisador de currículos",
    version=__version__,
    docs_url="/docs",
)


class Saude(BaseModel):
    status: Literal["ok"]
    versao: str
    provedor_ia: Literal["anthropic", "falso"]


@app.get("/saude", tags=["infra"])
async def saude() -> Saude:
    settings = obter_settings()
    return Saude(
        status="ok",
        versao=__version__,
        provedor_ia="falso" if settings.usa_provedor_falso else "anthropic",
    )
