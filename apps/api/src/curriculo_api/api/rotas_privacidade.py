"""`GET /privacidade` e `DELETE /eu/dados` (ADR 0004)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from curriculo_api.api.dependencias import Db, RecursosDep, UsuarioAtual, verificar_csrf
from curriculo_api.api.erros import respostas
from curriculo_api.api.esquemas import DadosApagados, ItemGuardado, Privacidade
from curriculo_api.seguranca import COOKIE_CSRF, COOKIE_SESSAO
from curriculo_api.servicos.privacidade import TEXTO_CONSENTIMENTO, apagar_usuario

rotas = APIRouter(tags=["privacidade"], dependencies=[Depends(verificar_csrf)])


@rotas.get(
    "/privacidade",
    summary="O que guardamos e por quanto tempo",
    description="Público. Lido da configuração (`RETENCAO_DIAS`, versão do texto).",
)
async def privacidade(recursos: RecursosDep) -> Privacidade:
    s = recursos.settings
    dias = f"{s.retencao_dias} dias, depois o conteúdo é apagado"
    return Privacidade(
        versao_texto=s.versao_consentimento,
        texto_consentimento=TEXTO_CONSENTIMENTO.format(dias=s.retencao_dias),
        retencao_dias=s.retencao_dias,
        o_que_guardamos=[
            ItemGuardado(
                dado="Arquivo do currículo (PDF, DOCX ou o texto colado)", por_quanto_tempo=dias
            ),
            ItemGuardado(dado="Texto do currículo anonimizado", por_quanto_tempo=dias),
            ItemGuardado(
                dado="O que a anonimização removeu, só o tipo e o valor mascarado (m•••@•••.com)",
                por_quanto_tempo=dias,
            ),
            ItemGuardado(
                dado="Resultado: tabela de requisitos com trechos, feedback e avisos",
                por_quanto_tempo=dias,
            ),
            ItemGuardado(
                dado="Nota, status, custo e datas de cada análise (sem conteúdo)",
                por_quanto_tempo="enquanto a conta existir",
            ),
            ItemGuardado(
                dado="Texto das vagas enviadas", por_quanto_tempo="enquanto a conta existir"
            ),
            ItemGuardado(
                dado="E-mail, hash da senha (argon2) e consentimentos",
                por_quanto_tempo="enquanto a conta existir",
            ),
            ItemGuardado(
                dado="Justificativas das decisões do modo recrutador (texto sobre terceiros)",
                por_quanto_tempo=dias,
            ),
            ItemGuardado(
                dado="Decisões do modo recrutador sem o texto (decisão, quem e quando) e a "
                "auditoria de revelar e baixar o arquivo original",
                por_quanto_tempo="enquanto a conta existir",
            ),
            ItemGuardado(
                dado="Eventos da análise em tempo real (Redis)",
                por_quanto_tempo=f"{s.eventos_ttl_s // 3600} horas",
            ),
        ],
        o_que_vai_para_a_ia=(
            "Só o texto anonimizado do currículo e o texto da vaga. Nesta instalação a análise é "
            "por regras (modo demonstração), sem IA."
            if s.modo_demonstracao
            else "Só o texto anonimizado do currículo e o texto da vaga, nunca o arquivo nem os "
            "dados pessoais removidos."
        ),
        o_que_nunca_guardamos=[
            "O valor original do que a anonimização removeu (nome, e-mail, telefone, CPF…)",
            "O nome original do arquivo",
            "Conteúdo de currículo ou de vaga nos logs",
        ],
        como_apagar="Em “Apagar meus dados” (DELETE /eu/dados): apaga na hora a conta, os "
        "arquivos e tudo o que está no banco e no Redis.",
    )


@rotas.delete(
    "/eu/dados",
    summary="Apagar meus dados",
    description="Apaga na hora tudo da conta: banco (em cascata), arquivos em disco e chaves no "
    "Redis. Encerra a sessão e responde com o que foi apagado. Não há como desfazer.",
    responses=respostas(401, 403),
)
async def apagar_dados(
    usuario: UsuarioAtual, db: Db, recursos: RecursosDep, resposta: Response
) -> DadosApagados:
    resultado = await apagar_usuario(db, recursos.redis, recursos.settings, usuario, recursos.fila)
    seguro = recursos.settings.cookie_seguro
    resposta.delete_cookie(COOKIE_SESSAO, path="/", secure=seguro, httponly=True, samesite="lax")
    resposta.delete_cookie(COOKIE_CSRF, path="/", secure=seguro, samesite="lax")
    return DadosApagados(
        mensagem="Seus dados foram apagados.",
        apagado=resultado.linhas,
        arquivos=resultado.arquivos,
        chaves_redis=resultado.chaves_redis,
    )
