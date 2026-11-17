"""Análises: envio (202 + fila), resultado, histórico paginado, SSE e relatório em PDF."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse
from redis.exceptions import RedisError
from sqlalchemy import select

from curriculo_api.api.dependencias import (
    Db,
    Recursos,
    RecursosDep,
    UsuarioAtual,
    ip_do_cliente,
    verificar_csrf,
)
from curriculo_api.api.erros import ErroApi, nao_encontrado, respostas
from curriculo_api.api.esquemas import (
    AnaliseCriada,
    AnaliseDetalhe,
    CurriculoRef,
    PaginaAnalises,
    VagaResumo,
)
from curriculo_api.api.sse import abrir_sse
from curriculo_api.db.modelos import Analise, Curriculo, Usuario
from curriculo_api.limites import Limite
from curriculo_api.relatorio_pdf import gerar_relatorio
from curriculo_api.servicos import consultas
from curriculo_api.servicos.envios import (
    EnvioCurriculo,
    acertar_uso,
    criar_analise,
    criar_versao,
    enfileirar,
    exigir_teto_diario,
    obter_ou_criar_vaga,
    reservar_teto,
    tratando_conta_apagada,
    vaga_do_usuario,
)

log = logging.getLogger("curriculo_api.analises")
rotas = APIRouter(prefix="/analises", tags=["análises"], dependencies=[Depends(verificar_csrf)])

MENSAGEM_LIMITE_ANALISES = (
    "Você enviou muitas análises na última hora. Espere um pouco e tente de novo."
)


async def exigir_limites_de_analise(
    recursos: Recursos, usuario: Usuario, request: Request, quantidade: int = 1
) -> None:
    settings = recursos.settings
    for _ in range(quantidade):
        await recursos.limitador.consumir(
            Limite("analises_usuario", settings.limite_analises_por_usuario, 3600),
            str(usuario.id),
            MENSAGEM_LIMITE_ANALISES,
        )
        await recursos.limitador.consumir(
            Limite("analises_ip", settings.limite_analises_por_ip, 3600),
            ip_do_cliente(request),
            "Muitas análises a partir desta rede na última hora. Tente de novo mais tarde.",
        )


async def ler_envio(arquivo: UploadFile | None, texto: str | None) -> EnvioCurriculo:
    if (arquivo is None) == (texto is None or not texto.strip()):
        raise ErroApi(
            422,
            "curriculo_ausente",
            "Envie o currículo em um arquivo (PDF ou DOCX) ou cole o texto, um dos dois.",
        )
    if arquivo is not None:
        return EnvioCurriculo(conteudo=await arquivo.read(), nome_arquivo=arquivo.filename)
    return EnvioCurriculo(texto=texto)


@rotas.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enviar currículo para análise",
    description=(
        "Recebe o currículo (arquivo PDF/DOCX **ou** texto colado) e a vaga (texto **ou** o id de "
        "uma vaga já enviada). O arquivo é validado na hora pelo tipo real (assinatura de bytes), "
        "tamanho e páginas, e o texto é lido e anonimizado; erros saem em problem+json. A análise "
        "vai para a fila e a resposta traz o id: acompanhe em `GET /analises/{id}/eventos` (SSE). "
        "Com `curriculo_id`, o envio vira uma nova versão desse currículo (para comparar)."
    ),
    responses=respostas(401, 403, 404, 413, 422, 429, 503),
)
async def enviar(
    request: Request,
    usuario: UsuarioAtual,
    db: Db,
    recursos: RecursosDep,
    arquivo: Annotated[
        UploadFile | None, File(description="Currículo em PDF ou DOCX (até 5 MB).")
    ] = None,
    texto: Annotated[str | None, Form(description="Ou o texto do currículo, colado.")] = None,
    vaga_texto: Annotated[str | None, Form(description="O texto da vaga.")] = None,
    vaga_id: Annotated[uuid.UUID | None, Form(description="Ou o id de uma vaga sua.")] = None,
    curriculo_id: Annotated[
        uuid.UUID | None, Form(description="Opcional: nova versão deste currículo.")
    ] = None,
) -> AnaliseCriada:
    settings = recursos.settings
    await exigir_limites_de_analise(recursos, usuario, request)
    await exigir_teto_diario(db, settings, usuario.id)
    envio = await ler_envio(arquivo, texto)
    if (vaga_id is None) == (vaga_texto is None or not vaga_texto.strip()):
        raise ErroApi(
            422, "vaga_ausente", "Cole o texto da vaga ou escolha uma vaga já enviada, um dos dois."
        )
    async with tratando_conta_apagada(db, settings, usuario.id):
        vaga = (
            await vaga_do_usuario(db, usuario.id, vaga_id)
            if vaga_id is not None
            else await obter_ou_criar_vaga(db, settings, usuario.id, vaga_texto or "")
        )
        if curriculo_id is not None:
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
        else:
            curriculo = Curriculo(usuario_id=usuario.id, origem="proprio")
            db.add(curriculo)
            await db.flush()
        versao = await criar_versao(db, settings, usuario.id, curriculo, envio)
        # Por último, a reserva atômica no teto diário: trava a linha do dia até o commit.
        reserva = await reservar_teto(db, settings, usuario.id)
        analise = await criar_analise(db, versao, vaga, usuario.id, reserva)
        await db.commit()
    await enfileirar_ou_falhar(recursos, db, analise)
    return AnaliseCriada(
        id=analise.id,
        status="na_fila",
        curriculo=CurriculoRef(id=curriculo.id, versao=versao.numero, origem=versao.origem),  # type: ignore[arg-type]
        vaga=VagaResumo(id=vaga.id, titulo=vaga.titulo),
        eventos_url=f"/analises/{analise.id}/eventos",
        resultado_url=f"/analises/{analise.id}",
    )


async def enfileirar_ou_falhar(recursos: Recursos, db: Db, analise: Analise) -> None:
    try:
        await enfileirar(recursos.redis, recursos.fila, recursos.settings.redis_prefixo, analise.id)
    except (RedisError, OSError):
        analise.status = "erro"
        analise.erro_codigo = "fila_indisponivel"
        analise.erro_mensagem = "A fila de análises está fora do ar. Tente de novo em instantes."
        await acertar_uso(
            db, analise.usuario_id, datetime.now(UTC).date(), analise.reserva_usd, Decimal(0), False
        )
        await db.commit()
        raise ErroApi(
            503, "fila_indisponivel", "A fila de análises está fora do ar. Tente de novo."
        ) from None


@rotas.get(
    "",
    summary="Histórico de análises",
    description="As análises dos seus currículos, da mais recente para a mais antiga, paginadas "
    "por cursor (as do modo recrutador ficam nos processos).",
    responses=respostas(400, 401),
)
async def listar(
    usuario: UsuarioAtual,
    db: Db,
    limite: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[
        str | None, Query(description="O `proximo_cursor` da página anterior.")
    ] = None,
) -> PaginaAnalises:
    itens, proximo = await consultas.listar_analises(db, usuario.id, limite, cursor)
    return PaginaAnalises(itens=itens, proximo_cursor=proximo)


@rotas.get(
    "/{analise_id}",
    summary="Resultado da análise",
    description="Nota e decomposição, tabela requisito × evidência (com o trecho), lacunas, "
    "reescritas antes/depois, palavras-chave, avisos (texto oculto, instrução para a IA, PDF sem "
    "texto) e o que a anonimização ignorou (valores mascarados).",
    responses=respostas(401, 404),
)
async def obter(analise_id: uuid.UUID, usuario: UsuarioAtual, db: Db) -> AnaliseDetalhe:
    analise, versao, vaga = await consultas.analise_do_usuario(db, usuario.id, analise_id)
    return consultas.detalhe(analise, versao, vaga)


@rotas.get(
    "/{analise_id}/eventos",
    summary="Eventos da análise em tempo real (SSE)",
    description=(
        "`text/event-stream` com os eventos `etapa` (`{etapa, texto}`: leitura, anonimização, "
        "extração, ancoragem, correspondência, nota, feedback), `texto` (`{texto}`: um pedaço do "
        "feedback enquanto é escrito), `final` (`{status, nota}`) e `erro` (`{codigo, mensagem}`). "
        "Cada evento tem `id`; reconecte com o cabeçalho `Last-Event-ID` (ou `?desde=`) para "
        "continuar sem perder nem repetir. Comentários `: ping` a cada 15 s mantêm a conexão. O "
        "fluxo fecha depois de `final` ou `erro`; reconectando depois do fim (Last-Event-ID igual "
        "ou maior que o do terminal), o terminal é **reenviado** com o mesmo id e o fluxo fecha. "
        "Uma conexão dura no máximo `TEMPO_MAX_ANALISE_S` + 120 s. Até 5 conexões simultâneas "
        "por pessoa (429 acima disso)."
    ),
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "text/event-stream": {
                    "example": 'id: 1\nevent: etapa\ndata: {"etapa": "leitura", "texto": '
                    '"lendo o arquivo"}\n\n'
                }
            }
        },
        **respostas(400, 401, 404, 429),
    },
)
async def eventos(
    analise_id: uuid.UUID,
    request: Request,
    usuario: UsuarioAtual,
    db: Db,
    recursos: RecursosDep,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    desde: Annotated[
        str | None, Query(description="Último id recebido (o mesmo que `Last-Event-ID`).")
    ] = None,
) -> StreamingResponse:
    await consultas.analise_do_usuario(db, usuario.id, analise_id)
    await db.close()  # a conexão do banco não fica presa durante o fluxo
    return await abrir_sse(recursos, request, usuario.id, analise_id, last_event_id, desde)


@rotas.get(
    "/{analise_id}/relatorio.pdf",
    summary="Relatório em PDF",
    description="Gerado no servidor, sem dados pessoais (sem a lista do que foi removido, sem o "
    "arquivo original).",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}, **respostas(401, 404)},
)
async def relatorio(analise_id: uuid.UUID, usuario: UsuarioAtual, db: Db) -> Response:
    analise, versao, vaga = await consultas.analise_do_usuario(db, usuario.id, analise_id)
    pdf = await run_in_threadpool(gerar_relatorio, consultas.detalhe(analise, versao, vaga))
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="relatorio-{analise_id}.pdf"'},
    )
