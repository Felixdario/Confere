"""A regra da evidência no feedback (ADR 0003, passo 5), checada em código.

O modelo do feedback recebe a tabela pronta e escreve resumo, lacunas, palavras-chave de ATS,
reescritas e "o que aprender". Aqui, antes de entregar (rodada 1 da fase 3):

- **normalização** de tudo o que o modelo escreveu: NFKC, sem largura zero, homóglifos
  cirílicos/gregos → latim. "Kube\\u200brnetes" e "Kubеrnetes" (com "е" cirílico) viram
  "Kubernetes" antes de qualquer conferência;
- **reescrita** só é entregue se:
  1. o "antes" tem pelo menos `PALAVRAS_MINIMAS_ANTES` palavras e é trecho ancorado do currículo;
  2. toda competência que ela cita — as que o modelo declarou e as que o código encontra no
     "depois" pela taxonomia (termos curtos como "K8s" valem em qualquer caixa, menos tudo em
     minúscula para os só de letras: "go" solto não é Go) — tem item ancorado (competência,
     idioma ou certificação);
  3. **o "depois" só diz o que o currículo diz**: cada palavra do "depois" está no texto do
     currículo (com variação de fim de palavra) ou no vocabulário comum de `vocabulario.py`; todo
     número está no currículo. "Apache Kafka", "EKS", "Docker Swarm", "machine-learning",
     "reduziram 40%", "2 milhões de usuários" e "time de 12 pessoas" caem aqui;
  as outras são descartadas e contadas, e as competências sem evidência que a vaga pede vão para
  "o que aprender", nunca para "o que escrever";
- **resumo**: frases que falam de nota, score, pontuação, porcentagem ou status de requisito
  ("atende", "parcial") saem. A nota da tela vem sempre do código;
- **lacunas** são as linhas da tabela que não atendem, na ordem da tabela; o comentário do modelo
  entra quando ele cita o requisito, senão vale o motivo calculado;
- **palavras-chave de ATS**: só termos com pelo menos 2 letras ou dígitos que aparecem, como
  palavras inteiras, na vaga;
- **o que aprender**: cada item tem de corresponder a um requisito parcial ou não atendido da
  tabela, e a sugestão não pode mandar escrever, declarar ou acrescentar a competência no
  currículo.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from curriculo_api.analise.correspondencia import evidencias_de
from curriculo_api.analise.niveis import PALAVRAS_DE_NIVEL
from curriculo_api.analise.vocabulario import VOCABULARIO_COMUM
from curriculo_api.ancoragem import (
    formas_do_termo,
    normalizar_para_ancora,
    termo_no_texto,
    trecho_ancorado,
)
from curriculo_api.flexao import mesma_palavra
from curriculo_api.ia.modelos import (
    AprenderIA,
    CurriculoExtraido,
    Feedback,
    FeedbackIA,
    LacunaIA,
    Reescrita,
    ReescritaDescartada,
    TabelaDaNota,
)
from curriculo_api.ingestao.normalizacao import HOMOGLIFOS, remover_largura_zero, sem_acentos
from curriculo_api.taxonomia import Taxonomia, normalizar_termo

MotivoDescarte = Literal["afirmacao_sem_evidencia", "nivel_sem_evidencia", "toca_lacuna"]
_FRONTEIRA_ANTES = r"(?<![\w#+])"
_FRONTEIRA_DEPOIS = r"(?![\w#+])"
LIMITE_TERMO_CURTO = 3
PALAVRAS_MINIMAS_ANTES = 4
PREFIXO_FLEXAO = 5
_TABELA_HOMOGLIFOS = {ord(k): v for k, v in HOMOGLIFOS.items()}
_PREFIXOS_DO_VOCABULARIO = frozenset(
    p[:PREFIXO_FLEXAO] for p in VOCABULARIO_COMUM if len(p) > PREFIXO_FLEXAO
)
_PALAVRA = re.compile(r"[^\W_]+")
_FRASES = re.compile(r"(?<=[.!?])\s+")
_FALA_DE_NOTA = re.compile(
    r"\b(?:nota|notas|score|scores|scoring|pontua\w*|pontos?|rating|grade|ranking|aprovad\w*|"
    r"reprovad\w*|atende|atendem|atendid\w*|nao atende|parcial\w*|percentual|porcentagem)\b"
    r"|\d+\s*%|\b\d{1,3}\s*(?:/|de|of|out of)\s*100\b"
)
_MANDA_ESCREVER = re.compile(
    r"\b(?:escrev\w*|declar\w*|adicion\w*|acrescent\w*|inclua|incluir|coloqu\w*|ponha|cite|"
    r"mencion\w*|liste|write|add|claim|list|put|state)\b.{0,60}\b(?:curriculo|cv|resume|"
    r"perfil|linkedin|que (?:voce )?domina|que (?:voce )?sabe)\b"
)
RESUMO_OMITIDO = (
    "O resumo do modelo foi omitido porque falava de nota ou de status; a nota e o status de "
    "cada requisito estão na tabela calculada pelo sistema."
)
SUGESTAO_SEM_EVIDENCIA = (
    "Uma reescrita sugerida citava {nome}, que o currículo não comprova. Se você tem essa "
    "experiência, mostre-a com um exemplo real; se não tem, estude e pratique antes."
)


def limpar(texto: str) -> str:
    """NFKC, sem largura zero, homóglifos → latim (o que o modelo escreveu, antes de conferir)."""
    return unicodedata.normalize("NFKC", remover_largura_zero(texto)).translate(_TABELA_HOMOGLIFOS)


@dataclass(frozen=True)
class _Padrao:
    canonica: str
    regex: re.Pattern[str]
    curto_de_letras: bool


@lru_cache(maxsize=4)
def _padroes(taxonomia: Taxonomia) -> tuple[_Padrao, ...]:
    padroes: list[_Padrao] = []
    for entrada in taxonomia.arquivo.competencias:
        for termo in (entrada.canonica, *entrada.sinonimos):
            normalizado = normalizar_termo(termo)
            curto = len(normalizado) <= LIMITE_TERMO_CURTO
            padroes.append(
                _Padrao(
                    canonica=entrada.canonica,
                    regex=re.compile(_FRONTEIRA_ANTES + re.escape(normalizado) + _FRONTEIRA_DEPOIS),
                    curto_de_letras=curto and normalizado.isalpha(),
                )
            )
    return tuple(padroes)


def competencias_citadas(texto: str, taxonomia: Taxonomia) -> frozenset[str]:
    """Canônicas da taxonomia que aparecem no texto (já limpo de largura zero e homóglifos).
    Termos curtos só de letras ("Go", "R") não valem quando escritos todo em minúscula ("go"
    solto é verbo); os com dígito ou símbolo ("k8s", "C#") valem em qualquer caixa."""
    limpo = limpar(texto)
    normalizado = normalizar_termo(limpo)
    achadas: set[str] = set()
    for padrao in _padroes(taxonomia):
        if not padrao.curto_de_letras:
            if padrao.regex.search(normalizado):
                achadas.add(padrao.canonica)
            continue
        # Curto e só de letras: procura no texto original, e a ocorrência não pode ser minúscula.
        alvo = re.compile(padrao.regex.pattern, re.IGNORECASE)
        for m in alvo.finditer(sem_acentos(limpo)):
            if not m.group(0).islower():
                achadas.add(padrao.canonica)
                break
    return frozenset(achadas)


def _palavras(texto: str) -> list[str]:
    return _PALAVRA.findall(sem_acentos(limpar(texto)).casefold())


def palavras_sem_evidencia(depois: str, texto_curriculo: str) -> list[str]:
    """Palavras do "depois" que não estão no currículo nem no vocabulário comum, e números que
    não estão no currículo."""
    do_curriculo = set(_palavras(texto_curriculo))
    prefixos = {p[:PREFIXO_FLEXAO] for p in do_curriculo if len(p) >= PREFIXO_FLEXAO}
    prefixos |= _PREFIXOS_DO_VOCABULARIO
    faltando: list[str] = []
    for palavra in _palavras(depois):
        if palavra in do_curriculo:
            continue
        if any(ch.isdigit() for ch in palavra):
            faltando.append(palavra)
            continue
        if palavra in VOCABULARIO_COMUM:
            continue
        if len(palavra) >= PREFIXO_FLEXAO + 1 and palavra[:PREFIXO_FLEXAO] in prefixos:
            continue
        faltando.append(palavra)
    return faltando


RADICAIS_DE_AFIRMACAO = (
    # pt: responsabilidade, escopo e resultado
    "lider",
    "gerenc",
    "coorden",
    "chefi",
    "supervis",
    "reduz",
    "reduc",
    "aument",
    "automat",
    "migr",
    "implant",
    "implement",
    "otimiz",
    "econom",
    "cresc",
    "planej",
    "entreg",
    "lanc",
    "impulsion",
    "alavanc",
    "expand",
    "dobr",
    "tripl",
    # en
    "led",
    "lead",
    "manag",
    "coordinat",
    "supervis",
    "reduc",
    "increas",
    "automat",
    "migrat",
    "implement",
    "optimi",
    "saved",
    "saving",
    "grew",
    "grow",
    "deliver",
    "launch",
    "drove",
    "boost",
    "doubl",
    "expand",
)
"""Radicais de verbos e substantivos que afirmam responsabilidade, escopo ou resultado. No
"depois", só valem se o currículo já usa o mesmo radical (rodada 3): "Liderei a equipe",
"Reduzi prazos" e "Automatizei processos" não podem aparecer num currículo que não diz isso."""


def afirmacoes_sem_evidencia(depois: str, texto_curriculo: str) -> list[str]:
    do_curriculo = _palavras(texto_curriculo)
    faltando = []
    for palavra in _palavras(depois):
        for radical in RADICAIS_DE_AFIRMACAO:
            if palavra.startswith(radical) and (len(radical) > 3 or palavra == radical):
                if not any(p.startswith(radical) for p in do_curriculo):
                    faltando.append(palavra)
                break
    return faltando


def niveis_sem_evidencia(depois: str, antes: str) -> list[str]:
    """Palavras de nível ("avançado", "fluente", "C1") no "depois" que o "antes" não tem: a
    reescrita não pode subir o nível de nada."""
    do_antes = set(_palavras(antes))
    return [p for p in _palavras(depois) if p in PALAVRAS_DE_NIVEL and p not in do_antes]


def toca_lacuna(
    depois: str, antes: str, texto_curriculo: str, tabela: TabelaDaNota, taxonomia: Taxonomia
) -> list[str]:
    """Palavras de um requisito parcial ou não atendido (descrição, canônica ou sinônimo) que
    aparecem no "depois" e não estão nem no "antes" nem no currículo: a reescrita está tentando
    tapar a lacuna com texto."""
    palavras_depois = _palavras(depois)
    conhecidas = _palavras(antes) + _palavras(texto_curriculo)
    tocadas: list[str] = []
    for linha in tabela.linhas:
        if linha.status == "atende":
            continue
        for forma in (linha.descricao, *formas_do_termo(linha.competencia_pedida, taxonomia)):
            for alvo in _palavras(forma):
                if len(alvo) < 4 or alvo in VOCABULARIO_COMUM:
                    continue
                if any(mesma_palavra(alvo, p) for p in palavras_depois) and not any(
                    mesma_palavra(alvo, p) for p in conhecidas
                ):
                    tocadas.append(alvo)
    return sorted(set(tocadas))


def _chave(taxonomia: Taxonomia, termo: str) -> str:
    return taxonomia.chave_de(termo)


def _chaves_das_lacunas(tabela: TabelaDaNota, taxonomia: Taxonomia) -> dict[str, str]:
    """Chave → descrição, para cada requisito parcial ou não atendido."""
    chaves: dict[str, str] = {}
    for linha in tabela.linhas:
        if linha.status == "atende":
            continue
        chaves[_chave(taxonomia, linha.competencia_pedida)] = linha.descricao
        chaves[_chave(taxonomia, linha.descricao)] = linha.descricao
    return chaves


def _corresponde_a_lacuna(
    competencia: str, tabela: TabelaDaNota, chaves: dict[str, str], taxonomia: Taxonomia
) -> bool:
    if _chave(taxonomia, competencia) in chaves:
        return True
    return any(
        linha.status != "atende" and termo_no_texto(competencia, linha.descricao)
        for linha in tabela.linhas
    )


def filtrar_feedback(
    bruto: FeedbackIA,
    tabela: TabelaDaNota,
    curriculo: CurriculoExtraido,
    texto_curriculo: str,
    texto_vaga: str,
    taxonomia: Taxonomia,
) -> Feedback:
    comprovadas = {e.chave for e in evidencias_de(curriculo, taxonomia)}
    lacunas_chaves = _chaves_das_lacunas(tabela, taxonomia)
    entregues: list[Reescrita] = []
    descartadas: list[ReescritaDescartada] = []
    aprender: list[AprenderIA] = []
    ja_em_aprender: set[str] = set()

    def aprender_se_pode(item: AprenderIA) -> None:
        competencia = limpar(item.competencia)
        chave = _chave(taxonomia, competencia)
        if chave in ja_em_aprender:
            return
        if not _corresponde_a_lacuna(competencia, tabela, lacunas_chaves, taxonomia):
            return
        if _MANDA_ESCREVER.search(sem_acentos(limpar(item.sugestao)).casefold()):
            return
        ja_em_aprender.add(chave)
        aprender.append(AprenderIA(competencia=competencia, sugestao=limpar(item.sugestao)))

    for item in bruto.o_que_aprender:
        aprender_se_pode(item)

    for proposta in bruto.reescritas:
        antes, depois = limpar(proposta.antes), limpar(proposta.depois)
        if len(_palavras(antes)) < PALAVRAS_MINIMAS_ANTES:
            descartadas.append(ReescritaDescartada(motivo="antes_curto"))
            continue
        if not trecho_ancorado(antes, texto_curriculo):
            descartadas.append(ReescritaDescartada(motivo="antes_sem_ancora"))
            continue
        declaradas = {_chave(taxonomia, limpar(c)): limpar(c) for c in proposta.competencias}
        declaradas = {k: v for k, v in declaradas.items() if v.strip()}
        detectadas = {c: c for c in competencias_citadas(depois, taxonomia)}
        citadas = {**detectadas, **declaradas}
        faltando = sorted(nome for chave, nome in citadas.items() if chave not in comprovadas)
        if faltando:
            descartadas.append(
                ReescritaDescartada(
                    motivo="competencia_sem_evidencia", competencias_sem_evidencia=tuple(faltando)
                )
            )
            for nome in faltando:
                aprender_se_pode(
                    AprenderIA(competencia=nome, sugestao=SUGESTAO_SEM_EVIDENCIA.format(nome=nome))
                )
            continue
        estranhas = palavras_sem_evidencia(depois, texto_curriculo)
        if estranhas:
            descartadas.append(
                ReescritaDescartada(
                    motivo="termo_fora_do_curriculo", termos_fora_do_curriculo=len(estranhas)
                )
            )
            continue
        conferencias: tuple[tuple[MotivoDescarte, list[str]], ...] = (
            ("afirmacao_sem_evidencia", afirmacoes_sem_evidencia(depois, texto_curriculo)),
            ("nivel_sem_evidencia", niveis_sem_evidencia(depois, antes)),
            ("toca_lacuna", toca_lacuna(depois, antes, texto_curriculo, tabela, taxonomia)),
        )
        falha = next(((m, a) for m, a in conferencias if a), None)
        if falha is not None:
            descartadas.append(
                ReescritaDescartada(motivo=falha[0], termos_fora_do_curriculo=len(falha[1]))
            )
            continue
        entregues.append(
            Reescrita(
                antes=antes,
                depois=depois,
                competencias=tuple(sorted({_chave(taxonomia, n) for n in citadas.values()})),
            )
        )

    return Feedback(
        resumo=_resumo(bruto.resumo),
        lacunas=tuple(_lacunas(bruto.lacunas, tabela)),
        palavras_chave_ats=tuple(_palavras_na_vaga(bruto.palavras_chave_ats, texto_vaga)),
        reescritas=tuple(entregues),
        reescritas_descartadas=tuple(descartadas),
        o_que_aprender=tuple(aprender),
    )


def _resumo(texto: str) -> str:
    frases = [f for f in _FRASES.split(limpar(texto).strip()) if f.strip()]
    mantidas = [f for f in frases if not _FALA_DE_NOTA.search(sem_acentos(f).casefold())]
    return " ".join(mantidas) if mantidas else RESUMO_OMITIDO


def _lacunas(propostas: Iterable[LacunaIA], tabela: TabelaDaNota) -> list[LacunaIA]:
    comentarios: dict[str, str] = {}
    for lacuna in propostas:
        comentarios.setdefault(
            normalizar_para_ancora(limpar(lacuna.requisito)), limpar(lacuna.comentario)
        )
    return [
        LacunaIA(
            requisito=linha.descricao,
            comentario=comentarios.get(normalizar_para_ancora(linha.descricao), linha.motivo),
        )
        for linha in tabela.linhas
        if linha.status != "atende"
    ]


def _palavras_na_vaga(palavras: Iterable[str], texto_vaga: str) -> list[str]:
    vaga = " " + " ".join(_palavras(texto_vaga)) + " "
    vistas: set[str] = set()
    saida: list[str] = []
    for palavra in palavras:
        partes = _palavras(palavra)
        chave = " ".join(partes)
        if sum(len(p) for p in partes) < 2 or chave in vistas:
            continue
        if f" {chave} " in vaga:
            vistas.add(chave)
            saida.append(limpar(palavra).strip())
    return saida
