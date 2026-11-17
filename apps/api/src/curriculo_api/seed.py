"""`make seed`: a conta de demonstração `demo@curriculo.dev` / `demo1234` com análises prontas.

Idempotente: se a conta existe, tudo dela é apagado (o mesmo `apagar_usuario` de "apagar meus
dados") e recriado igual. Usa só casos fictícios do dataset das evals (`evals/casos/`):

- análises com o **provedor falso** (respostas gravadas, feedback escrito à mão, D-30), para a
  tela de resultado ficar rica: b02 (texto colado) e i05 (PDF real com texto oculto e instrução
  para a IA, que aparecem nos avisos);
- um **histórico com duas versões** do mesmo currículo contra a mesma vaga (b01): a versão 1 é o
  b01 sem a seção de habilidades e sem as linhas de Next.js, Jest e GraphQL, analisada por regras; a
  versão 2 é o b01 inteiro, pelo falso. A nota sobe (o seed confere);
- um **processo de recrutador** com a vaga do b01 e quatro candidatos, todos pelo provedor de
  regras (o mesmo critério para todos), e uma decisão humana registrada com justificativa.

Nada aqui chama rede: o embutidor é o falso (D-31) e o pgvector não é necessário.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from arq import create_pool
from arq.connections import RedisSettings
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from curriculo_api.analise.embeddings import EmbutidorFalso
from curriculo_api.analise.fabrica import criar_analisador, resolver_pasta
from curriculo_api.api.rotas_recrutador import rotulo
from curriculo_api.config import Settings, obter_settings
from curriculo_api.db.modelos import (
    Analise,
    Candidato,
    Consentimento,
    Curriculo,
    DecisaoHumana,
    ProcessoRecrutador,
    Usuario,
)
from curriculo_api.db.sessao import criar_fabrica, criar_motor
from curriculo_api.evals.dataset import localizar_raiz
from curriculo_api.ia.falso import ProvedorFalso
from curriculo_api.ia.regras import ProvedorRegras
from curriculo_api.logs import configurar_logs
from curriculo_api.seguranca import hash_senha
from curriculo_api.servicos.envios import (
    EnvioCurriculo,
    criar_analise,
    criar_versao,
    obter_ou_criar_vaga,
)
from curriculo_api.servicos.execucao import Executor
from curriculo_api.servicos.privacidade import apagar_usuario

EMAIL = "demo@curriculo.dev"
SENHA = "demo1234"
CANDIDATOS = (
    "b01-frontend-senior",
    "b14-java-para-front-end",
    "b02-backend-pleno-node",
    "i01-visivel-pt-fim",
)
LINHAS_TIRADAS_DA_V1 = ("Next.js", "Jest", "GraphQL")


@dataclass
class ResumoSeed:
    usuario_id: uuid.UUID
    analises: dict[str, uuid.UUID] = field(default_factory=dict)
    notas: dict[str, int | None] = field(default_factory=dict)
    curriculo_historico: uuid.UUID | None = None
    vaga_historico: uuid.UUID | None = None
    processo: uuid.UUID | None = None


def _caso(raiz: Path, caso: str, arquivo: str) -> Path:
    return raiz / "evals" / "casos" / caso / arquivo


def versao_reduzida(curriculo: str) -> str:
    """O b01 sem a seção de habilidades e sem as linhas que citam Next.js, Jest e GraphQL."""
    saida: list[str] = []
    pular = False
    for linha in curriculo.split("\n"):
        if linha.startswith("## "):
            pular = linha.strip().lower() in ("## habilidades", "## competências")
        if pular or any(termo in linha for termo in LINHAS_TIRADAS_DA_V1):
            continue
        saida.append(linha)
    return "\n".join(saida)


async def _analisar(
    db: AsyncSession,
    executor: Executor,
    settings: Settings,
    usuario_id: uuid.UUID,
    curriculo: Curriculo,
    envio: EnvioCurriculo,
    vaga_texto: str,
) -> Analise:
    vaga = await obter_ou_criar_vaga(db, settings, usuario_id, vaga_texto)
    versao = await criar_versao(db, settings, usuario_id, curriculo, envio)
    analise = await criar_analise(db, versao, vaga, usuario_id)
    await db.commit()
    status = await executor.executar(analise.id)
    if status != "concluida":
        raise RuntimeError(f"a análise de demonstração terminou com status {status}")
    await db.refresh(analise)
    return analise


async def semear(
    settings: Settings,
    fabrica: async_sessionmaker[AsyncSession],
    redis: Redis,
    raiz: Path | None = None,
) -> ResumoSeed:
    raiz = raiz or localizar_raiz()
    fila = f"{settings.redis_prefixo}:fila"
    # O pré-teste de requisitos da vaga é do modo regras; o seed usa os dois provedores.
    settings_seed = settings.model_copy(update={"provedor_ia": "regras"})
    embutidor = EmbutidorFalso(dim=384)
    falso = Executor(
        settings_seed,
        fabrica,
        redis,
        criar_analisador(
            ProvedorFalso(resolver_pasta(settings.pasta_gravacoes)), settings, embutidor=embutidor
        ),
    )
    regras = Executor(
        settings_seed,
        fabrica,
        redis,
        criar_analisador(ProvedorRegras(), settings, embutidor=embutidor),
    )

    async with fabrica() as db:
        existente = (
            await db.execute(select(Usuario).where(func.lower(Usuario.email) == EMAIL))
        ).scalar_one_or_none()
        if existente is not None:
            await apagar_usuario(db, redis, settings, existente, fila)
        usuario = Usuario(email=EMAIL, senha_hash=hash_senha(SENHA))
        db.add(usuario)
        await db.flush()
        db.add(
            Consentimento(
                usuario_id=usuario.id,
                tipo="lgpd_titular",
                versao_texto=settings.versao_consentimento,
            )
        )
        await db.commit()
        resumo = ResumoSeed(usuario_id=usuario.id)

        def ler(caso: str, arquivo: str) -> str:
            return _caso(raiz, caso, arquivo).read_text("utf-8")

        # 1. Texto colado, provedor falso.
        cv = Curriculo(usuario_id=usuario.id, origem="proprio")
        db.add(cv)
        await db.flush()
        a = await _analisar(
            db,
            falso,
            settings_seed,
            usuario.id,
            cv,
            EnvioCurriculo(texto=ler("b02-backend-pleno-node", "curriculo.md")),
            ler("b02-backend-pleno-node", "vaga.md"),
        )
        resumo.analises["b02"] = a.id
        resumo.notas["b02"] = a.nota

        # 2. PDF real com texto oculto e instrução para a IA (avisos na tela).
        cv = Curriculo(usuario_id=usuario.id, origem="proprio")
        db.add(cv)
        await db.flush()
        pdf = _caso(raiz, "i05-oculta-en-instrucao", "curriculo.pdf")
        a = await _analisar(
            db,
            falso,
            settings_seed,
            usuario.id,
            cv,
            EnvioCurriculo(conteudo=pdf.read_bytes(), nome_arquivo="curriculo.pdf"),
            ler("i05-oculta-en-instrucao", "vaga.md"),
        )
        resumo.analises["i05"] = a.id
        resumo.notas["i05"] = a.nota

        # 3. Histórico: duas versões do mesmo currículo contra a mesma vaga; a nota sobe.
        cv = Curriculo(usuario_id=usuario.id, origem="proprio")
        db.add(cv)
        await db.flush()
        vaga_b01 = ler("b01-frontend-senior", "vaga.md")
        completo = ler("b01-frontend-senior", "curriculo.md")
        v1 = await _analisar(
            db,
            regras,
            settings_seed,
            usuario.id,
            cv,
            EnvioCurriculo(texto=versao_reduzida(completo)),
            vaga_b01,
        )
        v2 = await _analisar(
            db, falso, settings_seed, usuario.id, cv, EnvioCurriculo(texto=completo), vaga_b01
        )
        if (v1.nota or 0) >= (v2.nota or 0):
            raise RuntimeError(f"o histórico de demonstração não sobe ({v1.nota} → {v2.nota})")
        resumo.analises["historico_v1"] = v1.id
        resumo.analises["historico_v2"] = v2.id
        resumo.notas["historico_v1"] = v1.nota
        resumo.notas["historico_v2"] = v2.nota
        resumo.curriculo_historico = cv.id
        resumo.vaga_historico = v2.vaga_id

        # 4. Recrutador: a vaga do b01, quatro candidatos por regras e uma decisão registrada.
        vaga = await obter_ou_criar_vaga(db, settings_seed, usuario.id, vaga_b01)
        db.add(
            Consentimento(
                usuario_id=usuario.id,
                tipo="recrutador_base_legal",
                versao_texto=settings.versao_consentimento,
            )
        )
        processo = ProcessoRecrutador(
            usuario_id=usuario.id, vaga_id=vaga.id, titulo="Front-end sênior (demonstração)"
        )
        db.add(processo)
        await db.commit()
        candidatos: list[Candidato] = []
        for indice, caso in enumerate(CANDIDATOS):
            cv = Curriculo(usuario_id=usuario.id, origem="recrutador")
            db.add(cv)
            await db.flush()
            versao = await criar_versao(
                db, settings_seed, usuario.id, cv, EnvioCurriculo(texto=ler(caso, "curriculo.md"))
            )
            analise = await criar_analise(db, versao, vaga, usuario.id)
            candidato = Candidato(
                processo_id=processo.id,
                usuario_id=usuario.id,
                rotulo=rotulo(indice),
                curriculo_versao_id=versao.id,
                analise_id=analise.id,
            )
            db.add(candidato)
            await db.commit()
            await regras.executar(analise.id)
            candidatos.append(candidato)
        db.add(
            DecisaoHumana(
                candidato_id=candidatos[0].id,
                usuario_id=usuario.id,
                decisao="avancar",
                justificativa="Tem React, TypeScript e Next.js em produção; chamar para a "
                "entrevista técnica.",
            )
        )
        await db.commit()
        resumo.processo = processo.id
    return resumo


async def _principal() -> int:
    configurar_logs()
    settings = obter_settings()
    motor = criar_motor(settings.database_url)
    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        resumo = await semear(settings, criar_fabrica(motor), redis)
    finally:
        await redis.aclose()
        await motor.dispose()
    print(f"Conta de demonstração pronta: {EMAIL} / {SENHA}")
    for nome, nota in resumo.notas.items():
        print(f"  {nome}: nota {nota}")
    print(f"  processo de recrutador com {len(CANDIDATOS)} candidatos e 1 decisão registrada")
    return 0


def main() -> int:
    return asyncio.run(_principal())


if __name__ == "__main__":
    sys.exit(main())
