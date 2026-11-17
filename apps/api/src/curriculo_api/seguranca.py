"""Senhas (argon2id), tokens de sessão e CSRF (ADR 0007).

- A senha vira hash argon2id (`argon2-cffi`, parâmetros padrão da biblioteca, RFC 9106).
- O token de sessão é aleatório (32 bytes) e vai só no cookie httpOnly; o banco guarda o SHA-256
  dele, então um vazamento do banco não dá sessões válidas.
- O token CSRF é outro valor aleatório num cookie legível pela página (double submit): a página o
  copia no cabeçalho `X-CSRF-Token`, que outro site não consegue ler nem definir.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_HASHER = PasswordHasher()
# Hash de uma senha que ninguém tem: o login de e-mail inexistente gasta o mesmo tempo.
_HASH_FICTICIO = _HASHER.hash(secrets.token_urlsafe(16))

COOKIE_SESSAO = "curriculo_sessao"
COOKIE_CSRF = "curriculo_csrf"
CABECALHO_CSRF = "X-CSRF-Token"


def hash_senha(senha: str) -> str:
    return _HASHER.hash(senha)


def senha_confere(senha: str, hash_salvo: str | None) -> bool:
    try:
        return _HASHER.verify(hash_salvo or _HASH_FICTICIO, senha) and hash_salvo is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def novo_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_iguais(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and hmac.compare_digest(str(a), str(b))


def _assinatura_csrf(chave: bytes, nonce: str, sessao: str | None) -> str:
    vinculo = hash_token(sessao) if sessao else "anonima"
    return hmac.new(chave, f"{nonce}|{vinculo}".encode(), hashlib.sha256).hexdigest()[:40]


def token_csrf(chave: bytes, sessao: str | None) -> str:
    """Token CSRF ligado à sessão (rodada 1 da revisão): `<nonce>.<HMAC(nonce | sessão)>`. Antes
    do login, a "sessão" é a ausência dela; depois do login (e do logout) o token muda."""
    nonce = secrets.token_urlsafe(16)
    return f"{nonce}.{_assinatura_csrf(chave, nonce, sessao)}"


def csrf_valido(chave: bytes, token: str, sessao: str | None) -> bool:
    nonce, _, assinatura = token.partition(".")
    if not nonce or not assinatura:
        return False
    return hmac.compare_digest(assinatura, _assinatura_csrf(chave, nonce, sessao))


def resumo_privado(valor: str) -> str:
    """SHA-256 curto de um identificador (o e-mail no limite de login): a chave do Redis não
    carrega o e-mail."""
    return hashlib.sha256(valor.strip().casefold().encode()).hexdigest()[:24]
