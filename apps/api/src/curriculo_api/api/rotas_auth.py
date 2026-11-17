"""Cadastro, login, logout e `GET /eu` (ADR 0007).

Sessão por cookie `curriculo_sessao` (httpOnly, SameSite=Lax, `Secure` fora de dev/teste) com o
token aleatório; o banco guarda só o SHA-256. Toda rota que muda estado, login e cadastro
inclusive, exige o CSRF double submit: pegue o token em `GET /auth/csrf`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from curriculo_api.api.dependencias import (
    Db,
    RecursosDep,
    UsuarioAtual,
    ip_do_cliente,
    verificar_csrf,
)
from curriculo_api.api.erros import ErroApi, respostas
from curriculo_api.api.esquemas import Cadastro, ConsentimentoSaida, Eu, Login, TokenCsrf
from curriculo_api.config import Settings
from curriculo_api.db.modelos import Consentimento, Sessao, Usuario
from curriculo_api.limites import Limite
from curriculo_api.seguranca import (
    CABECALHO_CSRF,
    COOKIE_CSRF,
    COOKIE_SESSAO,
    csrf_valido,
    hash_senha,
    hash_token,
    novo_token,
    resumo_privado,
    senha_confere,
    token_csrf,
)

rotas = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(verificar_csrf)])
rotas_eu = APIRouter(tags=["auth"])

JANELA_LOGIN_S = 15 * 60
MENSAGEM_LOGIN = "E-mail ou senha incorretos."
MENSAGEM_MUITAS_TENTATIVAS = (
    "Muitas tentativas de entrar em pouco tempo. Espere alguns minutos e tente de novo."
)


def _definir_csrf(resposta: Response, settings: Settings, token: str) -> None:
    resposta.headers[CABECALHO_CSRF] = token
    resposta.set_cookie(
        COOKIE_CSRF,
        token,
        max_age=settings.sessao_dias * 86400,
        httponly=False,  # a página lê e copia no cabeçalho (double submit)
        samesite="lax",
        secure=settings.cookie_seguro,
        path="/",
    )


async def _abrir_sessao(
    db: Db, resposta: Response, recursos: RecursosDep, usuario: Usuario
) -> None:
    settings = recursos.settings
    token = novo_token()
    db.add(
        Sessao(
            usuario_id=usuario.id,
            token_hash=hash_token(token),
            expira_em=datetime.now(UTC) + timedelta(days=settings.sessao_dias),
        )
    )
    await db.commit()
    resposta.set_cookie(
        COOKIE_SESSAO,
        token,
        max_age=settings.sessao_dias * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_seguro,
        path="/",
    )
    # Token CSRF novo, ligado à sessão nova: um token plantado antes do login não vale mais.
    _definir_csrf(resposta, settings, token_csrf(recursos.chave_csrf, token))


async def _eu(db: Db, usuario: Usuario) -> Eu:
    consentimentos = (
        await db.execute(
            select(Consentimento)
            .where(Consentimento.usuario_id == usuario.id)
            .order_by(Consentimento.aceito_em)
        )
    ).scalars()
    return Eu(
        id=usuario.id,
        email=usuario.email,
        criado_em=usuario.criado_em,
        consentimentos=[ConsentimentoSaida.model_validate(c) for c in consentimentos],
    )


@rotas.get(
    "/csrf",
    summary="Token CSRF",
    description="Define o cookie `curriculo_csrf` (legível pela página) e devolve o mesmo valor. "
    "Envie-o no cabeçalho `X-CSRF-Token` em todo POST e DELETE.",
)
async def csrf(request: Request, resposta: Response, recursos: RecursosDep) -> TokenCsrf:
    sessao = request.cookies.get(COOKIE_SESSAO)
    atual = request.cookies.get(COOKIE_CSRF)
    token = (
        atual
        if atual and csrf_valido(recursos.chave_csrf, atual, sessao)
        else token_csrf(recursos.chave_csrf, sessao)
    )
    _definir_csrf(resposta, recursos.settings, token)
    return TokenCsrf(csrf=token)


@rotas.post(
    "/cadastro",
    status_code=status.HTTP_201_CREATED,
    summary="Criar conta",
    description="Cria a conta e já abre a sessão. O consentimento (LGPD) é obrigatório e "
    "registra a versão do texto de `GET /privacidade`.",
    responses=respostas(403, 409, 422, 429),
)
async def cadastro(
    dados: Cadastro, request: Request, resposta: Response, db: Db, recursos: RecursosDep
) -> Eu:
    settings = recursos.settings
    await recursos.limitador.consumir(
        Limite("cadastro_ip", settings.limite_cadastro_por_ip, 3600),
        ip_do_cliente(request),
        "Muitos cadastros a partir desta rede. Tente de novo mais tarde.",
    )
    if not dados.aceito_consentimento:
        raise ErroApi(
            422,
            "consentimento_obrigatorio",
            "Para criar a conta, é preciso aceitar o texto de privacidade (LGPD).",
        )
    if dados.versao_consentimento != settings.versao_consentimento:
        raise ErroApi(
            422,
            "consentimento_desatualizado",
            "O texto de privacidade mudou. Leia a versão atual e aceite de novo.",
        )
    existente = (
        await db.execute(select(Usuario.id).where(func.lower(Usuario.email) == dados.email.lower()))
    ).first()
    if existente is not None:
        raise ErroApi(409, "email_em_uso", "Já existe uma conta com este e-mail. Entre nela.")
    usuario = Usuario(email=dados.email.lower(), senha_hash=hash_senha(dados.senha))
    db.add(usuario)
    try:
        await db.flush()
    except IntegrityError:
        raise ErroApi(409, "email_em_uso", "Já existe uma conta com este e-mail.") from None
    db.add(
        Consentimento(
            usuario_id=usuario.id, tipo="lgpd_titular", versao_texto=dados.versao_consentimento
        )
    )
    await db.flush()
    await db.refresh(usuario)
    await _abrir_sessao(db, resposta, recursos, usuario)
    return await _eu(db, usuario)


@rotas.post(
    "/login",
    summary="Entrar",
    description="Abre a sessão (cookie httpOnly). Limite de tentativas por e-mail e por IP.",
    responses=respostas(401, 403, 429),
)
async def login(
    dados: Login, request: Request, resposta: Response, db: Db, recursos: RecursosDep
) -> Eu:
    settings = recursos.settings
    await recursos.limitador.consumir(
        Limite("login_ip", settings.limite_login_por_ip, JANELA_LOGIN_S),
        ip_do_cliente(request),
        MENSAGEM_MUITAS_TENTATIVAS,
    )
    await recursos.limitador.consumir(
        Limite("login_email", settings.limite_login_por_email, JANELA_LOGIN_S),
        resumo_privado(dados.email),
        MENSAGEM_MUITAS_TENTATIVAS,
    )
    usuario = (
        await db.execute(
            select(Usuario).where(func.lower(Usuario.email) == dados.email.strip().lower())
        )
    ).scalar_one_or_none()
    if not senha_confere(dados.senha, usuario.senha_hash if usuario else None) or usuario is None:
        raise ErroApi(401, "credenciais_invalidas", MENSAGEM_LOGIN)
    await _abrir_sessao(db, resposta, recursos, usuario)
    return await _eu(db, usuario)


@rotas.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sair",
    responses=respostas(403),
)
async def logout(request: Request, resposta: Response, db: Db, recursos: RecursosDep) -> None:
    token = request.cookies.get(COOKIE_SESSAO)
    if token:
        sessao = (
            await db.execute(select(Sessao).where(Sessao.token_hash == hash_token(token)))
        ).scalar_one_or_none()
        if sessao is not None:
            await db.delete(sessao)
            await db.commit()
    seguro = recursos.settings.cookie_seguro
    resposta.delete_cookie(COOKIE_SESSAO, path="/", secure=seguro, httponly=True, samesite="lax")
    # Um token novo, da ausência de sessão (o da sessão encerrada deixa de valer).
    _definir_csrf(resposta, recursos.settings, token_csrf(recursos.chave_csrf, None))


@rotas_eu.get(
    "/eu",
    summary="Quem sou eu",
    description="A conta da sessão atual e os consentimentos registrados.",
    responses=respostas(401),
)
async def eu(usuario: UsuarioAtual, db: Db) -> Eu:
    return await _eu(db, usuario)
