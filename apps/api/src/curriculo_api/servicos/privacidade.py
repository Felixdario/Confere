"""LGPD na prática (ADR 0004): o que guardamos, "apagar meus dados" e a retenção.

- `apagar_usuario`: conta as linhas de cada tabela, apaga o usuário (o resto vai em cascata),
  apaga a pasta dele em `PASTA_ARQUIVOS` e as chaves dele no Redis (eventos, canal, job e
  resultado do arq, limites por usuário e por e-mail). Devolve as contagens.
- `limpar_vencidos`: para cada versão de currículo com `expira_em` no passado, apaga o arquivo do
  disco, o texto anonimizado, a lista do que foi removido e os alertas, e nas análises dela a
  tabela, o feedback e os avisos (que citam trechos). Ficam a nota, o status, o custo e as datas:
  métricas agregadas, sem conteúdo. Também apaga sessões vencidas. O relógio é injetável.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from curriculo_api.config import Settings
from curriculo_api.db.modelos import (
    Analise,
    AuditoriaRecrutador,
    Candidato,
    Consentimento,
    Curriculo,
    CurriculoVersao,
    DecisaoHumana,
    ProcessoRecrutador,
    Sessao,
    UsoDiario,
    Usuario,
    Vaga,
)
from curriculo_api.eventos import chave_canal, chave_job, chave_stream, marcar_apagadas
from curriculo_api.seguranca import resumo_privado
from curriculo_api.servicos.envios import caminho_do_arquivo, pasta_arquivos

log = logging.getLogger("curriculo_api.privacidade")

TABELAS_DO_USUARIO: tuple[tuple[str, type], ...] = (
    ("sessoes", Sessao),
    ("consentimentos", Consentimento),
    ("curriculos", Curriculo),
    ("curriculo_versoes", CurriculoVersao),
    ("vagas", Vaga),
    ("analises", Analise),
    ("processos_recrutador", ProcessoRecrutador),
    ("candidatos", Candidato),
    ("decisoes_humanas", DecisaoHumana),
    ("auditoria_recrutador", AuditoriaRecrutador),
    ("uso_diario", UsoDiario),
)

TEXTO_CONSENTIMENTO = (
    "Para analisar seu currículo, guardamos o arquivo que você envia e o texto dele já "
    "anonimizado (sem nome, contato, documentos, endereço, data de nascimento, idade, gênero e "
    "estado civil). Só o texto anonimizado e a vaga são analisados, por regras (modo "
    "demonstração) ou por um modelo de IA; o arquivo e os dados pessoais nunca vão para a IA. "
    "Guardamos arquivo, texto e resultados por {dias} dias e depois apagamos o conteúdo; você "
    "pode apagar tudo a qualquer momento em “Apagar meus dados”. Ao enviar currículos de outras "
    "pessoas (modo recrutador), você declara ter base legal para tratá-los."
)


@dataclass
class Apagamento:
    linhas: dict[str, int] = field(default_factory=dict)
    arquivos: int = 0
    chaves_redis: int = 0


async def _apagar_chaves(redis: Redis, chaves: list[str]) -> int:
    total = 0
    for inicio in range(0, len(chaves), 500):
        lote = chaves[inicio : inicio + 500]
        if lote:
            total += int(await redis.delete(*lote))
    return total


async def chaves_da_analise(redis: Redis, prefixo: str, analise_id: uuid.UUID) -> list[str]:
    job = chave_job(prefixo, analise_id)
    return [
        chave_stream(prefixo, analise_id),
        chave_canal(prefixo, analise_id),
        f"arq:job:{job}",
        f"arq:result:{job}",
        f"arq:retry:{job}",
        f"arq:in-progress:{job}",
    ]


async def _chaves_por_padrao(redis: Redis, padrao: str) -> list[str]:
    return [
        c.decode() if isinstance(c, bytes) else str(c)
        async for c in redis.scan_iter(match=padrao, count=500)
    ]


async def apagar_usuario(
    db: AsyncSession, redis: Redis, settings: Settings, usuario: Usuario, fila: str
) -> Apagamento:
    resultado = Apagamento()
    uid = usuario.id
    for nome, modelo in TABELAS_DO_USUARIO:
        resultado.linhas[nome] = (
            await db.execute(
                select(func.count()).select_from(modelo).where(modelo.usuario_id == uid)  # type: ignore[attr-defined]
            )
        ).scalar_one()
    analises = list(
        (await db.execute(select(Analise.id).where(Analise.usuario_id == uid))).scalars()
    )

    # Antes de tudo, a marca "apagada" de cada análise (rodada 1 da revisão): um job que esteja
    # rodando para na próxima etapa ou evento e apaga o que criou no Redis.
    prefixo = settings.redis_prefixo
    await marcar_apagadas(redis, prefixo, analises)
    if analises:
        # Jobs ainda na fila (sorted set do arq): tira os desta pessoa antes de alguém pegá-los.
        await redis.zrem(fila, *[chave_job(prefixo, a) for a in analises])

    # Banco: um DELETE no usuário; o resto vai em cascata (ON DELETE CASCADE em toda tabela).
    await db.execute(delete(Usuario).where(Usuario.id == uid))
    resultado.linhas["usuarios"] = 1
    await db.commit()

    # Disco: a pasta do usuário inteira.
    pasta = pasta_arquivos(settings) / str(uid)
    if pasta.is_dir():
        resultado.arquivos = sum(1 for p in pasta.rglob("*") if p.is_file())
        await asyncio.to_thread(shutil.rmtree, pasta)

    # Redis: eventos e jobs das análises, limites e conexões do usuário e do e-mail.
    chaves: list[str] = [f"{prefixo}:sse:usuario:{uid}"]
    for analise_id in analises:
        chaves += await chaves_da_analise(redis, prefixo, analise_id)
    chaves += await _chaves_por_padrao(redis, f"{prefixo}:limite:*:{uid}:*")
    chaves += await _chaves_por_padrao(
        redis, f"{prefixo}:limite:login_email:{resumo_privado(usuario.email)}:*"
    )
    resultado.chaves_redis = await _apagar_chaves(redis, chaves)
    log.info(
        "privacidade.dados_apagados",
        extra={
            "linhas": sum(resultado.linhas.values()),
            "arquivos": resultado.arquivos,
            "chaves_redis": resultado.chaves_redis,
        },
    )
    return resultado


@dataclass
class Limpeza:
    versoes: int = 0
    arquivos: int = 0
    analises: int = 0
    sessoes: int = 0
    chaves_redis: int = 0
    justificativas: int = 0


def _agora() -> datetime:
    return datetime.now(UTC)


async def limpar_vencidos(
    db: AsyncSession,
    redis: Redis,
    settings: Settings,
    agora: Callable[[], datetime] = _agora,
) -> Limpeza:
    instante = agora()
    resultado = Limpeza()
    vencidas = list(
        (
            await db.execute(
                select(CurriculoVersao).where(
                    CurriculoVersao.expira_em <= instante,
                    CurriculoVersao.conteudo_apagado_em.is_(None),
                )
            )
        ).scalars()
    )
    ids = [v.id for v in vencidas]
    for versao in vencidas:
        if versao.arquivo:
            try:
                caminho = caminho_do_arquivo(settings, versao.arquivo)
                if caminho.is_file():
                    await asyncio.to_thread(caminho.unlink)
                    resultado.arquivos += 1
            except ValueError:  # pragma: no cover — caminho fora da pasta
                pass
        versao.arquivo = None
        versao.texto_anonimizado = None
        versao.removidos = []
        versao.alertas = []
        versao.conteudo_apagado_em = instante
    resultado.versoes = len(vencidas)
    if ids:
        analises = list(
            (
                await db.execute(select(Analise.id).where(Analise.curriculo_versao_id.in_(ids)))
            ).scalars()
        )
        resultado.analises = len(analises)
        await db.execute(
            update(Analise)
            .where(Analise.curriculo_versao_id.in_(ids))
            .values(tabela=None, feedback=None, avisos=[])
        )
        chaves: list[str] = []
        for analise_id in analises:
            chaves += [chave_stream(settings.redis_prefixo, analise_id)]
        resultado.chaves_redis = await _apagar_chaves(redis, chaves)
    # Justificativas sobre terceiros (modo recrutador) seguem a retenção do processo: depois de
    # RETENCAO_DIAS ficam a decisão, quem decidiu e quando; o texto sai.
    limite = instante - timedelta(days=settings.retencao_dias)
    justificativas = await db.execute(
        update(DecisaoHumana)
        .where(DecisaoHumana.criado_em <= limite, DecisaoHumana.justificativa.is_not(None))
        .values(justificativa=None, justificativa_apagada_em=instante)
        .returning(DecisaoHumana.id)
    )
    resultado.justificativas = len(justificativas.all())
    apagadas = await db.execute(
        delete(Sessao).where(Sessao.expira_em <= instante).returning(Sessao.id)
    )
    resultado.sessoes = len(apagadas.all())
    await db.commit()
    log.info(
        "retencao.limpeza",
        extra={
            "versoes": resultado.versoes,
            "arquivos": resultado.arquivos,
            "analises": resultado.analises,
            "sessoes": resultado.sessoes,
            "justificativas": resultado.justificativas,
        },
    )
    return resultado
