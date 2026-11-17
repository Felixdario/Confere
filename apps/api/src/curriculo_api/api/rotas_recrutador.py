"""Modo recrutador (ADR 0004): uma vaga, até 20 currículos, ranking explicado e decisão humana.

- A visão é **anonimizada por padrão**: rótulos ("Candidato A"), sem nome nem contato, e o
  arquivo original não aparece no ranking. Revelar é uma ação explícita, registrada
  (`POST .../revelar`), e só depois dela o arquivo pode ser baixado.
- **Sem rejeição automática**: o sistema ordena e explica; nenhuma rota muda decisão sem um
  `POST .../decisoes` da pessoa, com justificativa obrigatória.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, select

from curriculo_api.api.dependencias import Db, RecursosDep, UsuarioAtual, verificar_csrf
from curriculo_api.api.erros import ErroApi, nao_encontrado, respostas
from curriculo_api.api.esquemas import (
    AvisoAnonimo,
    CandidatoCriado,
    CandidatoDetalhe,
    CandidatoRanking,
    DecisaoSaida,
    NovaDecisao,
    NovoProcesso,
    ProcessoDetalhe,
    ProcessoResumo,
    RegistroAuditoria,
    RequisitoResumo,
    Revelacao,
    VagaResumo,
)
from curriculo_api.api.rotas_analises import (
    enfileirar_ou_falhar,
    exigir_limites_de_analise,
    ler_envio,
)
from curriculo_api.api.sse import abrir_sse
from curriculo_api.db.modelos import (
    Analise,
    AuditoriaRecrutador,
    Candidato,
    Consentimento,
    Curriculo,
    CurriculoVersao,
    DecisaoHumana,
    ProcessoRecrutador,
    Vaga,
)
from curriculo_api.ia.modelos import LacunaIA
from curriculo_api.servicos.consultas import linhas_da_tabela, parcelas_da_analise
from curriculo_api.servicos.envios import (
    caminho_do_arquivo,
    criar_analise,
    criar_versao,
    exigir_teto_diario,
    obter_ou_criar_vaga,
    reservar_teto,
    tratando_conta_apagada,
)

rotas = APIRouter(prefix="/processos", tags=["recrutador"], dependencies=[Depends(verificar_csrf)])

AVISO = (
    "O sistema ordena e explica; não descarta ninguém. Avançar ou não é decisão sua, registrada "
    "com justificativa."
)
LETRAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def rotulo(indice: int) -> str:
    """0 → "Candidato A", 25 → "Candidato Z", 26 → "Candidato AA"."""
    letras = ""
    n = indice + 1
    while n:
        n, resto = divmod(n - 1, 26)
        letras = LETRAS[resto] + letras
    return f"Candidato {letras}"


async def _processo(db: Db, usuario_id: uuid.UUID, processo_id: uuid.UUID) -> ProcessoRecrutador:
    processo = (
        await db.execute(
            select(ProcessoRecrutador).where(
                ProcessoRecrutador.id == processo_id, ProcessoRecrutador.usuario_id == usuario_id
            )
        )
    ).scalar_one_or_none()
    if processo is None:
        raise nao_encontrado("processo")
    return processo


async def _candidato(
    db: Db, usuario_id: uuid.UUID, processo_id: uuid.UUID, candidato_id: uuid.UUID
) -> Candidato:
    candidato = (
        await db.execute(
            select(Candidato).where(
                Candidato.id == candidato_id,
                Candidato.processo_id == processo_id,
                Candidato.usuario_id == usuario_id,
            )
        )
    ).scalar_one_or_none()
    if candidato is None:
        raise nao_encontrado("candidato")
    return candidato


async def _resumo(db: Db, processo: ProcessoRecrutador, limite: int) -> ProcessoResumo:
    vaga = await db.get(Vaga, processo.vaga_id)
    total = (
        await db.execute(
            select(func.count()).select_from(Candidato).where(Candidato.processo_id == processo.id)
        )
    ).scalar_one()
    return ProcessoResumo(
        id=processo.id,
        titulo=processo.titulo,
        vaga=VagaResumo(id=processo.vaga_id, titulo=vaga.titulo if vaga else ""),
        criado_em=processo.criado_em,
        candidatos=total,
        limite_candidatos=limite,
    )


def _decisao(d: DecisaoHumana) -> DecisaoSaida:
    return DecisaoSaida(
        id=d.id,
        decisao=d.decisao,  # type: ignore[arg-type]
        justificativa=d.justificativa,
        justificativa_apagada_em=d.justificativa_apagada_em,
        usuario_id=d.usuario_id,
        criado_em=d.criado_em,
    )


def _eventos_url(candidato: Candidato) -> str:
    return f"/processos/{candidato.processo_id}/candidatos/{candidato.id}/eventos"


def _explicacao(analise: Analise) -> str | None:
    linhas = linhas_da_tabela(analise)
    if analise.status != "concluida" or not linhas:
        return None
    partes = []
    for tipo, nome in (("obrigatorio", "obrigatórios"), ("desejavel", "desejáveis")):
        do_tipo = [linha for linha in linhas if linha.tipo == tipo]
        if not do_tipo:
            continue
        atende = sum(1 for linha in do_tipo if linha.status == "atende")
        parcial = sum(1 for linha in do_tipo if linha.status == "parcial")
        texto = f"{nome}: {atende} de {len(do_tipo)} com evidência"
        if parcial:
            texto += f", {parcial} em parte"
        partes.append(texto)
    decomposicao = analise.decomposicao or {}
    if decomposicao.get("anos_minimos"):
        anos = round(float(decomposicao.get("anos_relevantes", 0)), 1)
        partes.append(f"experiência relevante: {anos:g} de {decomposicao['anos_minimos']} anos")
    return "; ".join(partes).capitalize() + "."


def _ranking_item(
    candidato: Candidato, analise: Analise, decisao: DecisaoHumana | None, posicao: int | None
) -> CandidatoRanking:
    return CandidatoRanking(
        id=candidato.id,
        rotulo=candidato.rotulo,
        posicao=posicao,
        status=analise.status,  # type: ignore[arg-type]
        nota=analise.nota,
        decomposicao=(analise.decomposicao or {}).get("texto"),
        parcelas=parcelas_da_analise(analise),
        requisitos=[
            RequisitoResumo(descricao=linha.descricao, tipo=linha.tipo, status=linha.status)
            for linha in linhas_da_tabela(analise)
        ],
        explicacao=_explicacao(analise),
        decisao=_decisao(decisao) if decisao else None,
        eventos_url=_eventos_url(candidato),
    )


async def _ultimas_decisoes(db: Db, candidatos: list[uuid.UUID]) -> dict[uuid.UUID, DecisaoHumana]:
    if not candidatos:
        return {}
    todas = (
        await db.execute(
            select(DecisaoHumana)
            .where(DecisaoHumana.candidato_id.in_(candidatos))
            .order_by(DecisaoHumana.criado_em)
        )
    ).scalars()
    return {d.candidato_id: d for d in todas}


@rotas.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Criar processo seletivo",
    description="Um processo tem uma vaga e até 20 currículos. Quem envia currículos de "
    "terceiros declara ter base legal (LGPD); a declaração fica registrada.",
    responses=respostas(401, 403, 422),
)
async def criar(
    dados: NovoProcesso, usuario: UsuarioAtual, db: Db, recursos: RecursosDep
) -> ProcessoResumo:
    if not dados.declaro_base_legal:
        raise ErroApi(
            422,
            "base_legal_obrigatoria",
            "Para analisar currículos de outras pessoas, declare que tem base legal (LGPD) para "
            "tratá-los.",
        )
    vaga = await obter_ou_criar_vaga(db, recursos.settings, usuario.id, dados.vaga_texto)
    db.add(
        Consentimento(
            usuario_id=usuario.id,
            tipo="recrutador_base_legal",
            versao_texto=recursos.settings.versao_consentimento,
        )
    )
    processo = ProcessoRecrutador(
        usuario_id=usuario.id, vaga_id=vaga.id, titulo=(dados.titulo or vaga.titulo)[:200]
    )
    db.add(processo)
    await db.commit()
    await db.refresh(processo)
    return await _resumo(db, processo, recursos.settings.max_candidatos_por_processo)


@rotas.get("", summary="Meus processos", responses=respostas(401))
async def listar(usuario: UsuarioAtual, db: Db, recursos: RecursosDep) -> list[ProcessoResumo]:
    processos = (
        await db.execute(
            select(ProcessoRecrutador)
            .where(ProcessoRecrutador.usuario_id == usuario.id)
            .order_by(ProcessoRecrutador.criado_em.desc())
        )
    ).scalars()
    limite = recursos.settings.max_candidatos_por_processo
    return [await _resumo(db, p, limite) for p in processos]


@rotas.get(
    "/{processo_id}",
    summary="Ranking do processo",
    description="Candidatos por nota, com as parcelas e os requisitos de cada um, na visão "
    "anonimizada (rótulos; sem nome, contato nem arquivo).",
    responses=respostas(401, 404),
)
async def obter(
    processo_id: uuid.UUID, usuario: UsuarioAtual, db: Db, recursos: RecursosDep
) -> ProcessoDetalhe:
    processo = await _processo(db, usuario.id, processo_id)
    linhas = (
        await db.execute(
            select(Candidato, Analise)
            .join(Analise, Analise.id == Candidato.analise_id)
            .where(Candidato.processo_id == processo.id)
            .order_by(Candidato.criado_em, Candidato.rotulo)
        )
    ).all()
    decisoes = await _ultimas_decisoes(db, [c.id for c, _ in linhas])
    concluidos = sorted(
        [(c, a) for c, a in linhas if a.status == "concluida" and a.nota is not None],
        key=lambda par: -(par[1].nota or 0),
    )
    outros = [(c, a) for c, a in linhas if (c, a) not in concluidos]
    ranking = [
        _ranking_item(c, a, decisoes.get(c.id), i + 1) for i, (c, a) in enumerate(concluidos)
    ] + [_ranking_item(c, a, decisoes.get(c.id), None) for c, a in outros]
    resumo = await _resumo(db, processo, recursos.settings.max_candidatos_por_processo)
    return ProcessoDetalhe(**resumo.model_dump(), aviso=AVISO, ranking=ranking)


@rotas.post(
    "/{processo_id}/candidatos",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enviar um currículo ao processo",
    description="Um currículo por envio (arquivo PDF/DOCX ou texto). A análise vai para a fila; "
    "o candidato recebe o próximo rótulo. Passado o limite (20), o envio é recusado com 422.",
    responses=respostas(401, 403, 404, 413, 422, 429, 503),
)
async def enviar_candidato(
    processo_id: uuid.UUID,
    request: Request,
    usuario: UsuarioAtual,
    db: Db,
    recursos: RecursosDep,
    arquivo: Annotated[UploadFile | None, File(description="Currículo em PDF ou DOCX.")] = None,
    texto: Annotated[str | None, Form(description="Ou o texto do currículo.")] = None,
) -> CandidatoCriado:
    settings = recursos.settings
    processo = (
        await db.execute(
            select(ProcessoRecrutador)
            .where(
                ProcessoRecrutador.id == processo_id, ProcessoRecrutador.usuario_id == usuario.id
            )
            .with_for_update()  # dois envios ao mesmo tempo não passam juntos do limite
        )
    ).scalar_one_or_none()
    if processo is None:
        raise nao_encontrado("processo")
    total = (
        await db.execute(
            select(func.count()).select_from(Candidato).where(Candidato.processo_id == processo.id)
        )
    ).scalar_one()
    if total >= settings.max_candidatos_por_processo:
        raise ErroApi(
            422,
            "limite_candidatos",
            f"Este processo já tem {total} currículos, o limite é "
            f"{settings.max_candidatos_por_processo}. Crie outro processo para mais candidatos.",
        )
    await exigir_limites_de_analise(recursos, usuario, request)
    await exigir_teto_diario(db, settings, usuario.id)
    envio = await ler_envio(arquivo, texto)
    vaga = await db.get(Vaga, processo.vaga_id)
    if vaga is None:  # pragma: no cover — FK
        raise nao_encontrado("vaga")
    async with tratando_conta_apagada(db, settings, usuario.id):
        curriculo = Curriculo(usuario_id=usuario.id, origem="recrutador")
        db.add(curriculo)
        await db.flush()
        versao = await criar_versao(db, settings, usuario.id, curriculo, envio)
        reserva = await reservar_teto(db, settings, usuario.id)
        analise = await criar_analise(db, versao, vaga, usuario.id, reserva)
        candidato = Candidato(
            processo_id=processo.id,
            usuario_id=usuario.id,
            rotulo=rotulo(total),
            curriculo_versao_id=versao.id,
            analise_id=analise.id,
        )
        db.add(candidato)
        await db.commit()
    await enfileirar_ou_falhar(recursos, db, analise)
    return CandidatoCriado(
        id=candidato.id,
        rotulo=candidato.rotulo,
        status="na_fila",
        eventos_url=_eventos_url(candidato),
    )


@rotas.get(
    "/{processo_id}/candidatos/{candidato_id}/eventos",
    summary="Progresso da análise de um candidato (SSE)",
    description="Como `GET /analises/{id}/eventos`, mas na visão anonimizada: só `etapa`, "
    "`final` e `erro` (sem os pedaços de texto do feedback).",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}, **respostas(400, 401, 404, 429)},
)
async def eventos_do_candidato(
    processo_id: uuid.UUID,
    candidato_id: uuid.UUID,
    request: Request,
    usuario: UsuarioAtual,
    db: Db,
    recursos: RecursosDep,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    desde: Annotated[str | None, Query()] = None,
) -> StreamingResponse:
    candidato = await _candidato(db, usuario.id, processo_id, candidato_id)
    analise_id = candidato.analise_id
    await db.close()
    return await abrir_sse(
        recursos, request, usuario.id, analise_id, last_event_id, desde, so_etapas=True
    )


@rotas.get(
    "/{processo_id}/candidatos/{candidato_id}",
    summary="Explicação de um candidato",
    description="A tabela requisito × evidência (trechos anonimizados), lacunas e o histórico "
    "de decisões. Sem nome, contato nem arquivo.",
    responses=respostas(401, 404),
)
async def obter_candidato(
    processo_id: uuid.UUID, candidato_id: uuid.UUID, usuario: UsuarioAtual, db: Db
) -> CandidatoDetalhe:
    candidato = await _candidato(db, usuario.id, processo_id, candidato_id)
    analise = await db.get(Analise, candidato.analise_id)
    if analise is None:  # pragma: no cover — FK
        raise nao_encontrado("candidato")
    historico = list(
        (
            await db.execute(
                select(DecisaoHumana)
                .where(DecisaoHumana.candidato_id == candidato.id)
                .order_by(DecisaoHumana.criado_em)
            )
        ).scalars()
    )
    base = _ranking_item(candidato, analise, historico[-1] if historico else None, None)
    feedback = analise.feedback or {}
    # Alertas sem o trecho (só tipo e motivo): o trecho pode carregar um nome que a anonimização
    # não pegou fora do cabeçalho.
    avisos = [
        AvisoAnonimo(
            tipo=a.get("tipo", ""), origem=a.get("origem", "curriculo"), motivo=a.get("motivo")
        )
        for a in analise.avisos
    ]
    return CandidatoDetalhe(
        **base.model_dump(),
        tabela=linhas_da_tabela(analise),
        lacunas=[LacunaIA.model_validate(x) for x in feedback.get("lacunas", [])],
        avisos=avisos,
        decisoes=[_decisao(d) for d in historico],
        identidade_revelada_em=candidato.identidade_revelada_em,
        auditoria=await _auditoria(db, candidato.id),
    )


async def _auditoria(db: Db, candidato_id: uuid.UUID) -> list[RegistroAuditoria]:
    registros = (
        await db.execute(
            select(AuditoriaRecrutador)
            .where(AuditoriaRecrutador.candidato_id == candidato_id)
            .order_by(AuditoriaRecrutador.em)
        )
    ).scalars()
    return [
        RegistroAuditoria(acao=r.acao, usuario_id=r.usuario_id, em=r.em)  # type: ignore[arg-type]
        for r in registros
    ]


@rotas.post(
    "/{processo_id}/candidatos/{candidato_id}/decisoes",
    status_code=status.HTTP_201_CREATED,
    summary="Registrar decisão humana",
    description="Avançar, não avançar ou deixar pendente, sempre com justificativa. Fica "
    "registrado quem decidiu e quando; o histórico é mantido. O sistema nunca decide sozinho.",
    responses=respostas(401, 403, 404, 422),
)
async def decidir(
    processo_id: uuid.UUID,
    candidato_id: uuid.UUID,
    dados: NovaDecisao,
    usuario: UsuarioAtual,
    db: Db,
) -> DecisaoSaida:
    candidato = await _candidato(db, usuario.id, processo_id, candidato_id)
    justificativa = dados.justificativa.strip()
    if len(justificativa) < 10:
        raise ErroApi(
            422, "justificativa_obrigatoria", "Escreva uma justificativa (pelo menos 10 letras)."
        )
    decisao = DecisaoHumana(
        candidato_id=candidato.id,
        usuario_id=usuario.id,
        decisao=dados.decisao,
        justificativa=justificativa,
    )
    db.add(decisao)
    await db.commit()
    await db.refresh(decisao)
    return _decisao(decisao)


@rotas.post(
    "/{processo_id}/candidatos/{candidato_id}/revelar",
    summary="Revelar a identidade (ação registrada)",
    description="Sai da visão anonimizada para este candidato: registra quando e libera o "
    "download do arquivo original. Faça isso só quando precisar contatar a pessoa.",
    responses=respostas(401, 403, 404),
)
async def revelar(
    processo_id: uuid.UUID, candidato_id: uuid.UUID, usuario: UsuarioAtual, db: Db
) -> Revelacao:
    candidato = await _candidato(db, usuario.id, processo_id, candidato_id)
    if candidato.identidade_revelada_em is None:
        candidato.identidade_revelada_em = datetime.now(UTC)
    # Toda revelação fica na auditoria, a segunda também (quem e quando).
    db.add(AuditoriaRecrutador(usuario_id=usuario.id, candidato_id=candidato.id, acao="revelar"))
    await db.commit()
    versao = await db.get(CurriculoVersao, candidato.curriculo_versao_id)
    url = (
        f"/processos/{processo_id}/candidatos/{candidato_id}/arquivo"
        if versao is not None and versao.arquivo
        else None
    )
    return Revelacao(
        candidato_id=candidato.id,
        identidade_revelada_em=candidato.identidade_revelada_em,
        arquivo_url=url,
    )


@rotas.get(
    "/{processo_id}/candidatos/{candidato_id}/arquivo",
    summary="Arquivo original (depois de revelar)",
    response_class=FileResponse,
    responses={
        200: {"content": {"application/pdf": {}, "application/octet-stream": {}}},
        **respostas(401, 403, 404),
    },
)
async def arquivo(
    processo_id: uuid.UUID,
    candidato_id: uuid.UUID,
    usuario: UsuarioAtual,
    db: Db,
    recursos: RecursosDep,
) -> FileResponse:
    candidato = await _candidato(db, usuario.id, processo_id, candidato_id)
    if candidato.identidade_revelada_em is None:
        raise ErroApi(
            403,
            "identidade_nao_revelada",
            "O arquivo original só fica disponível depois de revelar a identidade.",
        )
    versao = await db.get(CurriculoVersao, candidato.curriculo_versao_id)
    if versao is None or not versao.arquivo:
        raise nao_encontrado("arquivo")
    caminho = caminho_do_arquivo(recursos.settings, versao.arquivo)
    if not caminho.is_file():
        raise nao_encontrado("arquivo")
    db.add(
        AuditoriaRecrutador(usuario_id=usuario.id, candidato_id=candidato.id, acao="baixar_arquivo")
    )
    await db.commit()
    tipos = {"pdf": "application/pdf", "docx": "application/octet-stream", "texto": "text/plain"}
    return FileResponse(
        caminho,
        media_type=tipos.get(versao.origem, "application/octet-stream"),
        filename=f"{candidato.rotulo.replace(' ', '-').lower()}{caminho.suffix}",
    )
