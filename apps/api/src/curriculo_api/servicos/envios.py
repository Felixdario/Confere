"""Envio de um currículo para análise (ADR 0007): valida e ingere **na hora** (para o erro sair
em problem+json, não depois na fila), grava a versão e o arquivo, e põe o job na fila do arq.

A ingestão roda de novo no worker, a partir do arquivo em disco: é o que dá ao SSE as etapas reais
de leitura e anonimização, e o arquivo é a única cópia do texto original (o banco guarda só o
texto anonimizado e os valores mascarados).
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import shutil
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from arq.connections import ArqRedis
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from curriculo_api.analise.fabrica import resolver_pasta
from curriculo_api.api.erros import ErroApi
from curriculo_api.config import Settings
from curriculo_api.db.modelos import (
    Analise,
    Curriculo,
    CurriculoVersao,
    UsoDiario,
    Usuario,
    Vaga,
)
from curriculo_api.eventos import chave_job
from curriculo_api.ia.regras import ProvedorRegras
from curriculo_api.ingestao import CurriculoIngerido, Limites, ingerir_curriculo, ingerir_vaga
from curriculo_api.ingestao.tipo_arquivo import detectar_tipo

log = logging.getLogger("curriculo_api.envios")

MENSAGEM_VAGA_SEM_REQUISITOS = (
    "A vaga não tem requisitos reconhecíveis. Cole a vaga com a lista de requisitos (um por "
    "linha, por exemplo sob “Requisitos” e “Diferenciais”)."
)


@dataclass(frozen=True)
class EnvioCurriculo:
    conteudo: bytes | None = field(default=None, repr=False)
    nome_arquivo: str | None = field(default=None, repr=False)
    texto: str | None = field(default=None, repr=False)


def pasta_arquivos(settings: Settings) -> Path:
    return resolver_pasta(settings.pasta_arquivos)


def caminho_do_arquivo(settings: Settings, relativo: str) -> Path:
    base = pasta_arquivos(settings).resolve()
    caminho = (base / relativo).resolve()
    if not caminho.is_relative_to(base):  # defesa: o caminho vem do banco, nunca do cliente
        raise ValueError("caminho fora da pasta de arquivos")
    return caminho


def _titulo_da_vaga(texto: str) -> str:
    for linha in texto.split("\n"):
        limpa = linha.strip().lstrip("#").strip()
        if limpa:
            return limpa[:200]
    return "Vaga"


async def obter_ou_criar_vaga(
    db: AsyncSession, settings: Settings, usuario_id: uuid.UUID, texto: str
) -> Vaga:
    """A mesma vaga colada de novo é a mesma `Vaga` (pelo SHA-256 do texto normalizado): é o
    que permite comparar versões do currículo contra a mesma vaga."""
    ingerida = ingerir_vaga(texto, Limites.de_settings(settings))
    if (
        settings.provedor_ia == "regras"
        and not ProvedorRegras().extrair_vaga_sincrono(ingerida.texto).requisitos
    ):
        raise ErroApi(422, "vaga_sem_requisitos", MENSAGEM_VAGA_SEM_REQUISITOS)
    sha = hashlib.sha256(ingerida.texto.encode()).hexdigest()
    existente = (
        await db.execute(select(Vaga).where(Vaga.usuario_id == usuario_id, Vaga.sha256 == sha))
    ).scalar_one_or_none()
    if existente is not None:
        return existente
    vaga = Vaga(
        usuario_id=usuario_id,
        titulo=_titulo_da_vaga(ingerida.texto),
        texto=ingerida.texto,
        sha256=sha,
        alertas=[a.model_dump() for a in ingerida.alertas],
    )
    # Dois envios simultâneos com a mesma vaga: o segundo reaproveita a do primeiro.
    try:
        async with db.begin_nested():
            db.add(vaga)
            await db.flush()
    except IntegrityError:
        existente = (
            await db.execute(select(Vaga).where(Vaga.usuario_id == usuario_id, Vaga.sha256 == sha))
        ).scalar_one_or_none()
        if existente is None:
            raise
        return existente
    return vaga


async def vaga_do_usuario(db: AsyncSession, usuario_id: uuid.UUID, vaga_id: uuid.UUID) -> Vaga:
    vaga = (
        await db.execute(select(Vaga).where(Vaga.id == vaga_id, Vaga.usuario_id == usuario_id))
    ).scalar_one_or_none()
    if vaga is None:
        raise ErroApi(404, "nao_encontrado", "Vaga não encontrada.")
    return vaga


def _ingerir(envio: EnvioCurriculo, limites: Limites) -> tuple[CurriculoIngerido, str]:
    if envio.conteudo is not None:
        tipo = detectar_tipo(envio.conteudo, envio.nome_arquivo, limites)
        return (
            ingerir_curriculo(
                arquivo=envio.conteudo, nome_arquivo=envio.nome_arquivo, limites=limites
            ),
            tipo,
        )
    return ingerir_curriculo(texto=envio.texto or "", limites=limites), "texto"


async def criar_versao(
    db: AsyncSession,
    settings: Settings,
    usuario_id: uuid.UUID,
    curriculo: Curriculo,
    envio: EnvioCurriculo,
    agora: datetime | None = None,
) -> CurriculoVersao:
    limites = Limites.de_settings(settings)
    ingerido, origem = await run_in_threadpool(_ingerir, envio, limites)
    bruto = envio.conteudo if envio.conteudo is not None else (envio.texto or "").encode("utf-8")
    numero = (
        await db.execute(
            select(func.coalesce(func.max(CurriculoVersao.numero), 0)).where(
                CurriculoVersao.curriculo_id == curriculo.id
            )
        )
    ).scalar_one() + 1
    versao_id = uuid.uuid4()
    extensao = {"pdf": "pdf", "docx": "docx", "texto": "txt"}[origem]
    relativo = f"{usuario_id}/{versao_id}.{extensao}"
    destino = caminho_do_arquivo(settings, relativo)
    destino.parent.mkdir(parents=True, exist_ok=True)
    await run_in_threadpool(destino.write_bytes, bruto)
    agora = agora or datetime.now(UTC)
    versao = CurriculoVersao(
        id=versao_id,
        curriculo_id=curriculo.id,
        usuario_id=usuario_id,
        numero=numero,
        origem=origem,
        arquivo=relativo,
        sha256=hashlib.sha256(bruto).hexdigest(),
        tamanho_bytes=len(bruto),
        texto_anonimizado=ingerido.texto_para_ia,
        removidos=[
            {"tipo": r.tipo, "mascarado": r.mascarado, "ocorrencias": r.ocorrencias}
            for r in ingerido.anonimizacao.removidos
        ],
        alertas=[a.model_dump() for a in ingerido.alertas],
        criado_em=agora,
        expira_em=agora + timedelta(days=settings.retencao_dias),
    )
    db.add(versao)
    await db.flush()
    return versao


async def custo_do_dia(db: AsyncSession, usuario_id: uuid.UUID, dia: date) -> Decimal:
    valor = (
        await db.execute(
            select(UsoDiario.custo_usd).where(
                UsoDiario.usuario_id == usuario_id, UsoDiario.dia == dia
            )
        )
    ).scalar_one_or_none()
    return Decimal(valor or 0)


def _erro_teto(agora: datetime, teto: Decimal) -> ErroApi:
    amanha = datetime.combine(agora.date() + timedelta(days=1), datetime.min.time(), UTC)
    return ErroApi(
        429,
        "teto_custo_diario",
        f"O limite diário de custo de análises (US$ {teto:.2f}) foi atingido. Novas análises "
        "voltam a ser aceitas depois da meia-noite (UTC).",
        cabecalhos={"Retry-After": str(max(1, int((amanha - agora).total_seconds())))},
    )


def reserva_por_analise(settings: Settings) -> Decimal:
    """O pior caso de uma análise, reservado do teto diário no envio. Com regras ou falso o custo é
    zero (nada a reservar); com o provedor real, o teto por análise (ADR 0001)."""
    if settings.provedor_ia != "anthropic":
        return Decimal(0)
    return Decimal(str(settings.teto_custo_analise_usd))


async def exigir_teto_diario(
    db: AsyncSession, settings: Settings, usuario_id: uuid.UUID, agora: datetime | None = None
) -> None:
    """Conferência rápida (sem reserva) antes do trabalho pesado do envio; a garantia é a reserva
    atômica de `reservar_teto`, logo antes de gravar."""
    agora = agora or datetime.now(UTC)
    teto = Decimal(str(settings.teto_custo_diario_usd))
    linha = (
        await db.execute(
            select(UsoDiario.custo_usd, UsoDiario.reservado_usd).where(
                UsoDiario.usuario_id == usuario_id, UsoDiario.dia == agora.date()
            )
        )
    ).first()
    usado = (linha[0] + linha[1]) if linha else Decimal(0)
    if usado + reserva_por_analise(settings) > teto or usado >= teto:
        raise _erro_teto(agora, teto)


async def reservar_teto(
    db: AsyncSession, settings: Settings, usuario_id: uuid.UUID, agora: datetime | None = None
) -> Decimal:
    """ADR 0004, rodada 1 da revisão: reserva **atômica** do pior caso no teto diário (UTC). O
    `UPDATE … WHERE custo + reservado + reserva <= teto` trava a linha do dia: dez envios
    simultâneos não passam juntos do teto. A reserva vira custo real quando a análise termina (ou
    é devolvida se falha). Devolve o valor reservado."""
    agora = agora or datetime.now(UTC)
    dia = agora.date()
    reserva = reserva_por_analise(settings)
    teto = Decimal(str(settings.teto_custo_diario_usd))
    await db.execute(
        insert(UsoDiario)
        .values(usuario_id=usuario_id, dia=dia, custo_usd=0, reservado_usd=0, analises=0)
        .on_conflict_do_nothing(index_elements=[UsoDiario.usuario_id, UsoDiario.dia])
    )
    ocupado = UsoDiario.custo_usd + UsoDiario.reservado_usd
    reservou = (
        await db.execute(
            update(UsoDiario)
            .where(
                UsoDiario.usuario_id == usuario_id,
                UsoDiario.dia == dia,
                ocupado + reserva <= teto,
                ocupado < teto,
            )
            .values(reservado_usd=UsoDiario.reservado_usd + reserva)
            .returning(UsoDiario.dia)
        )
    ).first()
    if reservou is None:
        raise _erro_teto(agora, teto)
    return reserva


@contextlib.asynccontextmanager
async def tratando_conta_apagada(
    db: AsyncSession, settings: Settings, usuario_id: uuid.UUID
) -> AsyncIterator[None]:
    """Um envio que corre junto com "apagar meus dados" bate na chave estrangeira do usuário que
    acabou de sumir: em vez de 500, `409 conta_apagada`, e o arquivo já gravado sai do disco."""
    try:
        yield
    except IntegrityError:
        await db.rollback()
        existe = (await db.execute(select(Usuario.id).where(Usuario.id == usuario_id))).first()
        if existe is None:
            pasta = pasta_arquivos(settings) / str(usuario_id)
            if pasta.is_dir():
                await run_in_threadpool(shutil.rmtree, pasta, True)
            raise ErroApi(
                409, "conta_apagada", "A conta foi apagada durante o envio; nada foi gravado."
            ) from None
        raise ErroApi(
            409, "conflito", "O envio conflitou com outro ao mesmo tempo. Tente de novo."
        ) from None


async def criar_analise(
    db: AsyncSession,
    versao: CurriculoVersao,
    vaga: Vaga,
    usuario_id: uuid.UUID,
    reserva_usd: Decimal = Decimal(0),
) -> Analise:
    analise = Analise(
        reserva_usd=reserva_usd,
        usuario_id=usuario_id,
        curriculo_versao_id=versao.id,
        vaga_id=vaga.id,
        status="na_fila",
        etapas=[],
        avisos=[],
        modelos=[],
        custo_usd=Decimal(0),
    )
    db.add(analise)
    await db.flush()
    return analise


async def enfileirar(redis: ArqRedis, fila: str, prefixo: str, analise_id: uuid.UUID) -> None:
    await redis.enqueue_job(
        "executar_analise",
        str(analise_id),
        _job_id=chave_job(prefixo, analise_id),
        _queue_name=fila,
    )
    log.info("analise.enfileirada", extra={"analise_id": str(analise_id)})


async def acertar_uso(
    db: AsyncSession,
    usuario_id: uuid.UUID,
    dia: date,
    reserva: Decimal,
    custo: Decimal,
    concluida: bool,
) -> None:
    """A reserva do envio vira o custo real: soma o custo, devolve a reserva (sem ficar negativa)
    e conta a análise concluída. Também usado quando a análise falha (custo do que já foi gasto)."""
    comando = insert(UsoDiario).values(
        usuario_id=usuario_id,
        dia=dia,
        custo_usd=custo,
        reservado_usd=0,
        analises=1 if concluida else 0,
    )
    comando = comando.on_conflict_do_update(
        index_elements=[UsoDiario.usuario_id, UsoDiario.dia],
        set_={
            "custo_usd": UsoDiario.custo_usd + custo,
            "reservado_usd": func.greatest(UsoDiario.reservado_usd - reserva, 0),
            "analises": UsoDiario.analises + (1 if concluida else 0),
        },
    )
    await db.execute(comando)
