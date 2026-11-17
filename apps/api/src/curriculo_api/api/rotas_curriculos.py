"""Currículos e comparação de versões contra a mesma vaga."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from curriculo_api.api.dependencias import Db, UsuarioAtual
from curriculo_api.api.erros import nao_encontrado, respostas
from curriculo_api.api.esquemas import Comparacao, CurriculoDetalhe, VersaoResumo
from curriculo_api.db.modelos import Curriculo, CurriculoVersao
from curriculo_api.servicos import consultas

rotas = APIRouter(prefix="/curriculos", tags=["currículos"])


def _detalhe(curriculo: Curriculo, versoes: list[CurriculoVersao]) -> CurriculoDetalhe:
    return CurriculoDetalhe(
        id=curriculo.id,
        criado_em=curriculo.criado_em,
        versoes=[
            VersaoResumo(
                versao=v.numero,
                origem=v.origem,  # type: ignore[arg-type]
                criado_em=v.criado_em,
                expira_em=v.expira_em,
                conteudo_apagado=v.conteudo_apagado_em is not None,
            )
            for v in versoes
        ],
    )


@rotas.get(
    "",
    summary="Meus currículos",
    description="Os currículos enviados por você (sem os do modo recrutador), com as versões.",
    responses=respostas(401),
)
async def listar(usuario: UsuarioAtual, db: Db) -> list[CurriculoDetalhe]:
    curriculos = list(
        (
            await db.execute(
                select(Curriculo)
                .where(Curriculo.usuario_id == usuario.id, Curriculo.origem == "proprio")
                .order_by(Curriculo.criado_em.desc())
            )
        ).scalars()
    )
    versoes = list(
        (
            await db.execute(
                select(CurriculoVersao)
                .where(CurriculoVersao.curriculo_id.in_([c.id for c in curriculos]))
                .order_by(CurriculoVersao.numero)
            )
        ).scalars()
    )
    return [_detalhe(c, [v for v in versoes if v.curriculo_id == c.id]) for c in curriculos]


@rotas.get(
    "/{curriculo_id}",
    summary="Um currículo e suas versões",
    responses=respostas(401, 404),
)
async def obter(curriculo_id: uuid.UUID, usuario: UsuarioAtual, db: Db) -> CurriculoDetalhe:
    curriculo = (
        await db.execute(
            select(Curriculo).where(
                Curriculo.id == curriculo_id,
                Curriculo.usuario_id == usuario.id,
                Curriculo.origem == "proprio",
            )
        )
    ).scalar_one_or_none()
    if curriculo is None:
        raise nao_encontrado("currículo")
    versoes = list(
        (
            await db.execute(
                select(CurriculoVersao)
                .where(CurriculoVersao.curriculo_id == curriculo.id)
                .order_by(CurriculoVersao.numero)
            )
        ).scalars()
    )
    return _detalhe(curriculo, versoes)


@rotas.get(
    "/{curriculo_id}/comparacao",
    summary="Comparar versões contra a mesma vaga",
    description=(
        "Compara a análise concluída de duas versões deste currículo contra a mesma vaga: por "
        'padrão as duas mais recentes (ou `de` e `para`). Devolve a frase ("A nota subiu de 58 '
        'para 76.") e os requisitos que mudaram de status.'
    ),
    responses=respostas(401, 404, 409, 422),
)
async def comparar(
    curriculo_id: uuid.UUID,
    usuario: UsuarioAtual,
    db: Db,
    vaga: Annotated[uuid.UUID, Query(description="O id da vaga.")],
    de: Annotated[int | None, Query(ge=1, description="Versão de partida.")] = None,
    para: Annotated[int | None, Query(ge=1, description="Versão de chegada.")] = None,
) -> Comparacao:
    return await consultas.comparar(db, usuario.id, curriculo_id, vaga, de, para)
