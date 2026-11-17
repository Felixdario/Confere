"""Leituras para a API, sempre filtradas pelo dono (ADR 0007): quem não é dono recebe 404, igual
a um id que não existe."""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from curriculo_api.ancoragem import termo_no_texto
from curriculo_api.api.erros import ErroApi, nao_encontrado
from curriculo_api.api.esquemas import (
    AnaliseDetalhe,
    AnaliseResumo,
    Aviso,
    Comparacao,
    CurriculoRef,
    Decomposicao,
    ErroAnaliseSaida,
    EtapaFeita,
    Ignorado,
    MudancaDeRequisito,
    PalavraChave,
    PontoDaComparacao,
    VagaResumo,
)
from curriculo_api.db.modelos import Analise, Curriculo, CurriculoVersao, Vaga
from curriculo_api.ia.modelos import (
    AprenderIA,
    LacunaIA,
    LinhaRequisito,
    Parcela,
    Reescrita,
)
from curriculo_api.ia.regras import AVISO_MODO_DEMO

PROVEDORES_DEMO = frozenset({"regras", "falso"})


async def analise_do_usuario(
    db: AsyncSession,
    usuario_id: uuid.UUID,
    analise_id: uuid.UUID,
    origens: tuple[str, ...] = ("proprio",),
) -> tuple[Analise, CurriculoVersao, Vaga]:
    linha = (
        await db.execute(
            select(Analise, CurriculoVersao, Vaga)
            .join(CurriculoVersao, CurriculoVersao.id == Analise.curriculo_versao_id)
            .join(Curriculo, Curriculo.id == CurriculoVersao.curriculo_id)
            .join(Vaga, Vaga.id == Analise.vaga_id)
            .where(
                Analise.id == analise_id,
                Analise.usuario_id == usuario_id,
                # Análise de candidato (modo recrutador) só pelas rotas do processo, na visão
                # anonimizada: por aqui sairiam os trechos dos alertas e o que foi ignorado.
                Curriculo.origem.in_(origens),
            )
        )
    ).first()
    if linha is None:
        raise nao_encontrado("análise")
    return linha[0], linha[1], linha[2]


def referencia(versao: CurriculoVersao) -> CurriculoRef:
    return CurriculoRef(id=versao.curriculo_id, versao=versao.numero, origem=versao.origem)  # type: ignore[arg-type]


def resumo(analise: Analise, versao: CurriculoVersao, vaga: Vaga) -> AnaliseResumo:
    return AnaliseResumo(
        id=analise.id,
        status=analise.status,  # type: ignore[arg-type]
        nota=analise.nota,
        criado_em=analise.criado_em,
        concluido_em=analise.concluido_em,
        curriculo=referencia(versao),
        vaga=VagaResumo(id=vaga.id, titulo=vaga.titulo),
        provedor=analise.provedor,
    )


def linhas_da_tabela(analise: Analise) -> list[LinhaRequisito]:
    return [LinhaRequisito.model_validate(linha) for linha in analise.tabela or []]


def parcelas_da_analise(analise: Analise) -> list[Parcela]:
    return [Parcela.model_validate(p) for p in (analise.decomposicao or {}).get("parcelas", [])]


def detalhe(analise: Analise, versao: CurriculoVersao, vaga: Vaga) -> AnaliseDetalhe:
    feedback: dict[str, Any] = analise.feedback or {}
    texto = versao.texto_anonimizado or ""
    palavras = [
        PalavraChave(termo=termo, no_curriculo=bool(texto) and termo_no_texto(termo, texto))
        for termo in feedback.get("palavras_chave_ats", [])
    ]
    demo = (analise.provedor or "regras") in PROVEDORES_DEMO
    decomposicao = None
    if analise.decomposicao:
        decomposicao = Decomposicao(
            texto=analise.decomposicao.get("texto", ""),
            parcelas=parcelas_da_analise(analise),
            anos_relevantes=analise.decomposicao.get("anos_relevantes", 0),
            anos_minimos=analise.decomposicao.get("anos_minimos"),
        )
    avisos_da_analise = analise.avisos if analise.status == "concluida" else []
    avisos = avisos_da_analise or (versao.alertas or []) + (vaga.alertas or [])
    return AnaliseDetalhe(
        id=analise.id,
        status=analise.status,  # type: ignore[arg-type]
        etapas=[EtapaFeita.model_validate(e) for e in analise.etapas],
        criado_em=analise.criado_em,
        iniciado_em=analise.iniciado_em,
        concluido_em=analise.concluido_em,
        curriculo=referencia(versao),
        vaga=VagaResumo(id=vaga.id, titulo=vaga.titulo),
        modo_demonstracao=demo,
        aviso_modo=(
            AVISO_MODO_DEMO
            if analise.provedor == "regras"
            else "Modo demonstração: resposta gravada de um caso fictício, sem IA."
            if analise.provedor == "falso"
            else None
        ),
        provedor=analise.provedor,
        modelos=list(analise.modelos),
        custo_usd=analise.custo_usd,
        nota=analise.nota,
        decomposicao=decomposicao,
        requisitos=linhas_da_tabela(analise),
        resumo=feedback.get("resumo"),
        lacunas=[LacunaIA.model_validate(x) for x in feedback.get("lacunas", [])],
        reescritas=[Reescrita.model_validate(x) for x in feedback.get("reescritas", [])],
        reescritas_descartadas=len(feedback.get("reescritas_descartadas", [])),
        palavras_chave=palavras,
        o_que_aprender=[AprenderIA.model_validate(x) for x in feedback.get("o_que_aprender", [])],
        avisos=[Aviso.model_validate(_aviso(a)) for a in avisos],
        ignorado=[Ignorado.model_validate(x) for x in versao.removidos],
        conteudo_apagado=versao.conteudo_apagado_em is not None,
        erro=(
            ErroAnaliseSaida(codigo=analise.erro_codigo, mensagem=analise.erro_mensagem or "")
            if analise.erro_codigo
            else None
        ),
    )


def _aviso(dados: dict[str, Any]) -> dict[str, Any]:
    return {
        "tipo": dados.get("tipo", ""),
        "origem": dados.get("origem", "curriculo"),
        "motivo": dados.get("motivo"),
        "trecho": dados.get("trecho") or "",
        "pagina": dados.get("pagina"),
    }


# --- paginação por cursor ---------------------------------------------------------------------


def codificar_cursor(criado_em: datetime, analise_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{criado_em.isoformat()}|{analise_id}".encode()).decode()


def decodificar_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        texto = base64.urlsafe_b64decode(cursor.encode()).decode()
        instante, ident = texto.split("|", 1)
        momento = datetime.fromisoformat(instante)
        # Sem fuso, ou fora de uma faixa plausível ("0001-01-01+14:00" estoura no banco): 400.
        if momento.tzinfo is None or not 2000 <= momento.astimezone(UTC).year <= 2200:
            raise ValueError
        return momento, uuid.UUID(ident)
    except (ValueError, UnicodeDecodeError, OverflowError):
        raise ErroApi(400, "cursor_invalido", "O cursor de paginação é inválido.") from None


async def listar_analises(
    db: AsyncSession, usuario_id: uuid.UUID, limite: int, cursor: str | None
) -> tuple[list[AnaliseResumo], str | None]:
    consulta = (
        select(Analise, CurriculoVersao, Vaga)
        .join(CurriculoVersao, CurriculoVersao.id == Analise.curriculo_versao_id)
        .join(Curriculo, Curriculo.id == CurriculoVersao.curriculo_id)
        .join(Vaga, Vaga.id == Analise.vaga_id)
        .where(Analise.usuario_id == usuario_id, Curriculo.origem == "proprio")
        .order_by(Analise.criado_em.desc(), Analise.id.desc())
        .limit(limite + 1)
    )
    if cursor:
        instante, ident = decodificar_cursor(cursor)
        consulta = consulta.where(
            or_(
                Analise.criado_em < instante,
                and_(Analise.criado_em == instante, Analise.id < ident),
            )
        )
    linhas = (await db.execute(consulta)).all()
    itens = [resumo(a, v, g) for a, v, g in linhas[:limite]]
    proximo = None
    if len(linhas) > limite:
        ultimo = linhas[limite - 1][0]
        proximo = codificar_cursor(ultimo.criado_em, ultimo.id)
    return itens, proximo


# --- comparação de versões ---------------------------------------------------------------------


def _frase(de: int, para: int) -> str:
    if para > de:
        return f"A nota subiu de {de} para {para}."
    if para < de:
        return f"A nota caiu de {de} para {para}."
    return f"A nota ficou em {para}."


async def comparar(
    db: AsyncSession,
    usuario_id: uuid.UUID,
    curriculo_id: uuid.UUID,
    vaga_id: uuid.UUID,
    de: int | None,
    para: int | None,
) -> Comparacao:
    curriculo = (
        await db.execute(
            select(Curriculo).where(
                Curriculo.id == curriculo_id, Curriculo.usuario_id == usuario_id
            )
        )
    ).scalar_one_or_none()
    vaga = (
        await db.execute(select(Vaga).where(Vaga.id == vaga_id, Vaga.usuario_id == usuario_id))
    ).scalar_one_or_none()
    if curriculo is None:
        raise nao_encontrado("currículo")
    if vaga is None:
        raise nao_encontrado("vaga")
    linhas = (
        await db.execute(
            select(Analise, CurriculoVersao)
            .join(CurriculoVersao, CurriculoVersao.id == Analise.curriculo_versao_id)
            .where(
                CurriculoVersao.curriculo_id == curriculo_id,
                Analise.vaga_id == vaga_id,
                Analise.usuario_id == usuario_id,
                Analise.status == "concluida",
            )
            .order_by(CurriculoVersao.numero, Analise.concluido_em)
        )
    ).all()
    # A análise mais recente de cada versão.
    por_versao: dict[int, Analise] = {}
    for analise, versao in linhas:
        por_versao[versao.numero] = analise
    if len(por_versao) < 2:
        raise ErroApi(
            409,
            "comparacao_indisponivel",
            "Para comparar, analise pelo menos duas versões deste currículo contra esta vaga.",
        )
    pontos = {
        numero: PontoDaComparacao(
            versao=numero, analise_id=a.id, nota=a.nota or 0, criado_em=a.criado_em
        )
        for numero, a in sorted(por_versao.items())
    }
    numeros = sorted(pontos)
    numero_de = de if de is not None else numeros[-2]
    numero_para = para if para is not None else numeros[-1]
    if numero_de not in pontos or numero_para not in pontos:
        raise ErroApi(404, "nao_encontrado", "Versão sem análise concluída contra esta vaga.")
    antes = {linha.descricao: linha for linha in linhas_da_tabela(por_versao[numero_de])}
    depois = {linha.descricao: linha for linha in linhas_da_tabela(por_versao[numero_para])}
    mudancas: list[MudancaDeRequisito] = []
    for descricao in [*antes, *(d for d in depois if d not in antes)]:
        a, b = antes.get(descricao), depois.get(descricao)
        status_a = a.status if a else None
        status_b = b.status if b else None
        if status_a != status_b:
            mudancas.append(
                MudancaDeRequisito(
                    requisito=descricao,
                    tipo=(a or b).tipo,  # type: ignore[union-attr]
                    de=status_a,
                    para=status_b,
                )
            )
    p_de, p_para = pontos[numero_de], pontos[numero_para]
    return Comparacao(
        curriculo_id=curriculo_id,
        vaga=VagaResumo(id=vaga.id, titulo=vaga.titulo),
        versoes=list(pontos.values()),
        de=p_de,
        para=p_para,
        diferenca=p_para.nota - p_de.nota,
        frase=_frase(p_de.nota, p_para.nota),
        mudancas=mudancas,
    )
