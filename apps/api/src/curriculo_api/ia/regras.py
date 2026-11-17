"""Provedor local por regras (ADR 0006): o modo demonstração, sem IA, sem rede e sem custo.

Sem chave da Anthropic (sempre, neste portfólio: D-46), o provedor falso só responde os textos
gravados das evals. Para que qualquer pessoa possa enviar **qualquer** currículo, este provedor
implementa a mesma interface (`ProvedorIA`) com regras determinísticas:

- **extração do currículo**: seções pelos títulos; experiências pelas linhas com datas e separador
  ("Cargo — Empresa — mar/2022 – atual"); competências, idiomas e certificações pelo casamento de
  termos da taxonomia (canônicas e sinônimos, palavra inteira, flexão só de plural e gênero);
  formação pelas linhas de curso superior, técnico, pós ou MBA. Todo item leva como `trecho` a
  própria linha do texto anonimizado, então passa pela **mesma ancoragem** da IA (ADR 0003):
  negação, injection e marcadores continuam descartando;
- **extração da vaga**: requisitos pelos itens de lista sob títulos de obrigatórios ou de
  diferenciais; a competência é o primeiro termo da taxonomia da linha (fora dela, a própria linha,
  que vai para o embedding); anos e nível lidos da linha;
- **feedback**: montado por modelos de texto a partir da tabela já calculada (lacunas, palavras-
  chave da vaga e "o que aprender"). **Nenhuma reescrita**: sem um modelo de linguagem, reescrever
  sem inventar não é seguro (ADR 0006).

Limitações conhecidas (ADR 0006): termos fora da taxonomia no currículo não viram competência;
experiência em duas linhas (cargo numa, empresa e datas na outra) sai com o cargo errado; a vaga
com uma competência por linha funciona melhor que a vaga em prosa.
"""

from __future__ import annotations

import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import TYPE_CHECKING, Literal

from curriculo_api.analise.formatacao import decimal_br
from curriculo_api.analise.niveis import nivel_de
from curriculo_api.ancoragem import datas_do_trecho, ocorrencias
from curriculo_api.ia.modelos import (
    AprenderIA,
    Certificacao,
    Competencia,
    CurriculoExtraido,
    Etapa,
    EventoFeedback,
    Experiencia,
    FeedbackIA,
    Formacao,
    Idioma,
    LacunaIA,
    LinhaRequisito,
    Nivel,
    RegistroUso,
    Requisito,
    Resposta,
    TabelaDaNota,
    TextoAnonimizado,
    VagaExtraida,
)
from curriculo_api.ingestao.normalizacao import sem_acentos
from curriculo_api.taxonomia import Taxonomia, carregar_taxonomia

if TYPE_CHECKING:
    from curriculo_api.ia.orcamento import Orcamento

MODELO = "regras"
AVISO_MODO_DEMO = "Modo demonstração: análise por regras, sem IA."
TAMANHO_DO_PEDACO = 60

TipoSecao = Literal[
    "cabecalho",
    "resumo",
    "experiencias",
    "formacao",
    "competencias",
    "idiomas",
    "certificacoes",
    "outros",
]

_SECOES: tuple[tuple[TipoSecao, re.Pattern[str]], ...] = (
    (
        "experiencias",
        re.compile(r"experiencia|experience|historico profissional|trajetoria|work history"),
    ),
    ("formacao", re.compile(r"formacao|educacao|education|escolaridade|academic")),
    ("idiomas", re.compile(r"idioma|language|linguas")),
    (
        "certificacoes",
        re.compile(r"certifica|curso|course|registro|licen|treinamento|training"),
    ),
    (
        "competencias",
        re.compile(r"habilidade|competencia|skill|conhecimento|tecnologia|ferramenta|stack"),
    ),
    ("resumo", re.compile(r"resumo|sobre|perfil|summary|profile|objetivo|about")),
)
_PALAVRAS_DE_TITULO = 6
_MARCADOR = re.compile(r"\[[A-Z_]{2,}\]")
_ITEM_DE_LISTA = re.compile(r"^\s*(?:[-*•·▪◦‣–]|\d{1,2}[.)])\s+")
_SEPARADOR = re.compile(r"\s+[—–|]\s+|\s+-\s+|\s+@\s+|\s+at\s+|\s*·\s*")
_GRAU = re.compile(
    r"\b(?:bacharel\w*|licenciatura|graduacao|graduado|graduada|tecnologo|tecnologa|"
    r"tecnico em|tecnica em|pos[- ]graduacao|especializacao|mba|mestrado|doutorado|"
    r"bachelor|master|degree|bsc|msc|phd|ensino medio)\b"
)
_ANOS = re.compile(r"(?<!\d)(\d{1,2})\s*\+?\s*(?:anos|ano|years|year|yrs)\b")
_ANOS_DE_EXPERIENCIA = re.compile(
    r"(?:minim[oa] de\s*|pelo menos\s*|at least\s*)?(\d{1,2})\s*\+?\s*(?:anos?|years?)\s+"
    r"(?:de\s+|of\s+)?(?:experiencia|experience|atuacao|vivencia)"
    r"|(?:experiencia|experience)\s+(?:minima\s+)?(?:de\s+)?(\d{1,2})\s*\+?\s*(?:anos?|years?)"
)
_OBRIGATORIOS = re.compile(
    r"obrigat|requisit|requirement|must|precis|esperamos|exigid|necessari|qualifica|"
    r"o que voce|what you|you have|voce tem"
)
_DESEJAVEIS = re.compile(
    r"desejave|diferencia|nice to have|plus|bonus|preferenci|preferred|seria bom|"
    r"ganha pontos|good to have|extras?\b"
)
_IGNORAR_NA_VAGA = re.compile(
    r"sobre|about|beneficio|benefit|oferecemos|we offer|responsabilidade|responsibilit|"
    r"atividades|o que vai fazer|what you will do|you will|local|salario|contrata"
)
_NIVEL_DA_VAGA: tuple[tuple[Nivel, re.Pattern[str]], ...] = (
    ("senior", re.compile(r"\b(?:senior|sr|especialista|lead)\b")),
    ("pleno", re.compile(r"\b(?:pleno|mid|mid-level|midlevel|intermediate)\b")),
    ("junior", re.compile(r"\b(?:junior|jr|entry[- ]level|trainee|estagio|estagiari\w*)\b")),
)
_INGLES = re.compile(
    r"\b(?:requirements|nice to have|experience|years|we are|you will|about the role|skills|"
    r"and|with|the|for)\b"
)
_PREFIXOS_DE_REQUISITO = re.compile(
    r"^(?:experiencia (?:solida |comprovada )?(?:com|em|de)|conhecimento (?:em|de)|"
    r"conhecimentos (?:em|de)|dominio (?:de|em)|vivencia (?:com|em)|nocoes de|"
    r"experience (?:with|in)|knowledge of|proficiency in)\s+",
)


@dataclass(frozen=True)
class _Forma:
    texto: str
    canonica: str
    categoria: str
    curta: re.Pattern[str] | None
    """Termo de até 3 caracteres ("Go", "R", "JS", "SAE"): só vale com a mesma caixa no texto."""


def _dobrar(texto: str) -> str:
    return " ".join(sem_acentos(texto).casefold().split())


def _formas(taxonomia: Taxonomia) -> list[_Forma]:
    formas: list[_Forma] = []
    for entrada in taxonomia.arquivo.competencias:
        for termo in (entrada.canonica, *entrada.sinonimos):
            curta = None
            if len(re.sub(r"\W", "", termo)) <= 3:
                curta = re.compile(rf"(?<![\w#+.]){re.escape(termo)}(?![\w#+])")
            formas.append(_Forma(termo, entrada.canonica, entrada.categoria, curta))
    # O termo mais longo primeiro: "Power BI" antes de "BI", "Apache Airflow" antes de "Airflow".
    formas.sort(key=lambda f: -len(f.texto))
    return formas


@dataclass(frozen=True)
class _Achado:
    forma: _Forma
    posicao: int
    """Índice da primeira palavra do termo na linha (para escolher o primeiro termo)."""


class _Casador:
    def __init__(self, taxonomia: Taxonomia) -> None:
        self.taxonomia = taxonomia
        self.formas = _formas(taxonomia)

    def achados(self, linha: str) -> list[_Achado]:
        """Uma ocorrência por canônica (a de maior termo), na ordem em que aparecem na linha."""
        dobrada = _dobrar(linha)
        por_canonica: dict[str, _Achado] = {}
        for forma in self.formas:
            if forma.canonica in por_canonica:
                continue
            if forma.curta is not None:
                m = forma.curta.search(linha)
                if m is None:
                    continue
                posicao = len(linha[: m.start()].split())
            else:
                primeira = _dobrar(forma.texto).split()[0][:3]
                if primeira not in dobrada:
                    continue
                achados = ocorrencias(forma.texto, linha)
                if not achados:
                    continue
                posicao = achados[0][0]
            por_canonica[forma.canonica] = _Achado(forma, posicao)
        return sorted(por_canonica.values(), key=lambda a: (a.posicao, -len(a.forma.texto)))


def _uso(etapa: Etapa, inicio: float) -> RegistroUso:
    return RegistroUso(
        etapa=etapa,
        modelo=MODELO,
        duracao_ms=round((time.perf_counter() - inicio) * 1000),
        input_tokens=0,
        output_tokens=0,
        custo_usd=Decimal(0),
    )


def _sem_lista(linha: str) -> str:
    return _ITEM_DE_LISTA.sub("", linha).strip()


_TITULO_SIMPLES = re.compile(
    r"^(?:experiencias?(?: profissionais?)?|experience|work experience|historico profissional|"
    r"formacao(?: academica)?|educacao|education|escolaridade|idiomas|linguas|languages|"
    r"habilidades(?: tecnicas)?|competencias(?: tecnicas)?|skills|technical skills|"
    r"conhecimentos(?: tecnicos)?|certificacoes|certificados|certifications|"
    r"cursos(?: e certificacoes| livres| complementares| e registro)?|courses|"
    r"resumo(?: profissional)?|sobre mim|summary|profile|perfil(?: profissional)?|objetivo|"
    r"projetos|projects)$"
)


def _titulo_de_secao(linha: str) -> str | None:
    """O texto do título, se a linha for um: "## Experiência", "Habilidades:",
    "EXPERIÊNCIA PROFISSIONAL" ou um nome de seção sozinho na linha ("Formação")."""
    bruta = linha.strip()
    if not bruta:
        return None
    if bruta.startswith("#"):
        return bruta.lstrip("#").strip()
    sem_dois_pontos = bruta.rstrip(":").strip()
    if _ITEM_DE_LISTA.match(bruta) or len(sem_dois_pontos.split()) > _PALAVRAS_DE_TITULO:
        return None
    if re.search(r"\d", sem_dois_pontos):
        return None
    dobrada = _dobrar(sem_dois_pontos)
    if _TITULO_SIMPLES.match(dobrada):
        return sem_dois_pontos
    if any(padrao.search(dobrada) for _, padrao in _SECOES) and (
        bruta.endswith(":") or (sem_dois_pontos.isupper() and len(sem_dois_pontos) > 3)
    ):
        return sem_dois_pontos
    return None


def _tipo_de_secao(titulo: str) -> TipoSecao:
    dobrado = _dobrar(titulo)
    for tipo, padrao in _SECOES:
        if padrao.search(dobrado):
            return tipo
    return "outros"


@dataclass(frozen=True)
class _Linha:
    texto: str
    """Sem o marcador de lista: é o trecho que vai para a ancoragem."""
    secao: TipoSecao
    titulo: bool
    lista: bool = False


LINHAS_DE_CABECALHO_SEM_SECOES = 3
TRECHOS_POR_COMPETENCIA = 2
_PRIORIDADE: dict[TipoSecao, int] = {
    "experiencias": 0,
    "competencias": 1,
    "certificacoes": 2,
    "outros": 3,
    "formacao": 4,
    "idiomas": 4,
    "resumo": 5,
    "cabecalho": 6,
}


def _linhas(texto: str) -> list[_Linha]:
    """As linhas não vazias com a seção de cada uma. O cabeçalho (antes do primeiro título) é
    contato e nome; num texto sem títulos, só as primeiras linhas contam como cabeçalho."""
    linhas: list[_Linha] = []
    secao: TipoSecao = "cabecalho"
    for bruta in texto.split("\n"):
        titulo = _titulo_de_secao(bruta)
        if titulo is not None:
            secao = _tipo_de_secao(titulo) if not bruta.lstrip().startswith("# ") else secao
            linhas.append(_Linha(titulo, secao, True))
            continue
        limpa = _sem_lista(bruta)
        if limpa:
            linhas.append(_Linha(limpa, secao, False, bool(_ITEM_DE_LISTA.match(bruta))))
    if all(linha.secao == "cabecalho" for linha in linhas):
        linhas = [
            linha if i < LINHAS_DE_CABECALHO_SEM_SECOES else _Linha(linha.texto, "outros", False)
            for i, linha in enumerate(linhas)
        ]
    return linhas


def _partes(linha: str) -> list[str]:
    return [p.strip(" ,;()") for p in _SEPARADOR.split(linha) if p.strip(" ,;()")]


def _so_datas(parte: str) -> bool:
    if datas_do_trecho(parte) is None:
        return False
    resto = re.sub(r"\d", " ", _dobrar(parte))
    resto = re.sub(
        r"\b(?:jan|fev|feb|mar|abr|apr|mai|may|jun|jul|ago|aug|set|sep|out|oct|nov|dez|dec)\w*",
        " ",
        resto,
    )
    resto = re.sub(
        r"\b(?:atual|atualmente|o momento|momento|presente|present|hoje|current|now|ate|de|a|"
        r"desde|since|to|em andamento)\b",
        " ",
        resto,
    )
    return not re.search(r"[a-z]{2,}", resto)


def _experiencia(linha: _Linha) -> Experiencia | None:
    if linha.titulo or linha.lista or linha.secao in ("formacao", "certificacoes", "idiomas"):
        return None
    if _MARCADOR.search(linha.texto) or _GRAU.search(_dobrar(linha.texto)):
        return None
    datas = datas_do_trecho(linha.texto)
    if datas is None:
        return None
    partes = _partes(linha.texto)
    textuais = [p for p in partes if not _so_datas(p)]
    if len(partes) < 2 or not textuais or len(textuais) == len(partes):
        return None
    cargo = re.sub(r"\(?\b(?:19|20)\d{2}\b.*$", "", textuais[0]).strip(" ,;(-–—") or textuais[0]
    empresa = textuais[1] if len(textuais) > 1 else "não informada"
    try:
        return Experiencia(
            cargo=cargo, empresa=empresa, inicio=datas[0], fim=datas[1], trecho=linha.texto
        )
    except ValueError:
        return None


def _formacao(linha: _Linha) -> Formacao | None:
    if linha.titulo or _MARCADOR.search(linha.texto):
        return None
    if not _GRAU.search(_dobrar(linha.texto)):
        return None
    partes = [p for p in _partes(linha.texto) if not _so_datas(p)]
    if not partes:
        return None
    anos = re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", linha.texto)
    return Formacao(
        curso=partes[0],
        instituicao=partes[1] if len(partes) > 1 else None,
        conclusao=int(anos[-1]) if anos else None,
        trecho=linha.texto,
    )


class ProvedorRegras:
    """Determinístico, sem rede e sem chave. Custo zero, registrado como tal."""

    def __init__(self, taxonomia: Taxonomia | None = None) -> None:
        self._taxonomia = taxonomia or carregar_taxonomia()
        self._casador = _Casador(self._taxonomia)

    @property
    def nome(self) -> str:
        return MODELO

    # --- currículo --------------------------------------------------------------------------

    def extrair_curriculo_sincrono(self, texto: str) -> CurriculoExtraido:
        linhas = _linhas(texto)
        experiencias: list[Experiencia] = []
        indice_da_linha: dict[int, int] = {}
        for i, linha in enumerate(linhas):
            experiencia = _experiencia(linha)
            if experiencia is not None:
                indice_da_linha[i] = len(experiencias)
                experiencias.append(experiencia)

        # Região de cada experiência: da linha dela até a próxima experiência ou título.
        regiao: dict[int, int] = {}
        atual: int | None = None
        for i, linha in enumerate(linhas):
            if i in indice_da_linha:
                atual = indice_da_linha[i]
            elif linha.titulo:
                atual = None
            if atual is not None:
                regiao[i] = atual

        competencias: dict[str, list[tuple[int, int, Competencia]]] = {}
        ligacoes: dict[str, set[int]] = {}
        idiomas: dict[str, Idioma] = {}
        certificacoes: dict[str, Certificacao] = {}
        formacao: list[Formacao] = []
        for i, linha in enumerate(linhas):
            if linha.titulo or linha.secao == "cabecalho" or _MARCADOR.search(linha.texto):
                continue
            if len(linha.texto.split()) < 2:
                continue
            curso = _formacao(linha)
            if curso is not None and linha.secao in ("formacao", "outros", "certificacoes"):
                formacao.append(curso)
                continue  # o nome de uma graduação não vira competência (D-15)
            cabecalho_de_experiencia = i in indice_da_linha
            for achado in self._casador.achados(linha.texto):
                forma = achado.forma
                if forma.categoria == "idioma":
                    idiomas.setdefault(
                        forma.canonica,
                        Idioma(
                            idioma=forma.texto,
                            nivel=_rotulo_nivel(linha.texto),
                            trecho=linha.texto,
                        ),
                    )
                    continue
                if forma.categoria == "certificacao":
                    certificacoes.setdefault(
                        forma.canonica,
                        Certificacao(
                            nome=_nome_certificacao(linha.texto),
                            competencia=forma.canonica,
                            trecho=linha.texto,
                        ),
                    )
                    continue
                if cabecalho_de_experiencia:
                    continue  # o cargo ("Desenvolvedora Front-end") não é evidência de competência
                competencias.setdefault(forma.canonica, []).append(
                    (_PRIORIDADE[linha.secao], i, Competencia(nome=forma.texto, trecho=linha.texto))
                )
                ligacoes.setdefault(forma.canonica, set())
                if i in regiao:
                    ligacoes[forma.canonica].add(regiao[i])

        # Até dois trechos por competência, das seções mais fortes primeiro (experiência, lista
        # de habilidades): se a ancoragem descarta um (linha com injection, negação), o outro fica.
        itens: list[Competencia] = []
        for canonica, candidatos in competencias.items():
            for _, _, competencia in sorted(candidatos, key=lambda c: (c[0], c[1]))[
                :TRECHOS_POR_COMPETENCIA
            ]:
                itens.append(
                    competencia.model_copy(
                        update={"experiencias": tuple(sorted(ligacoes[canonica]))}
                    )
                )

        return CurriculoExtraido(
            experiencias=tuple(experiencias),
            competencias=tuple(itens),
            formacao=tuple(formacao),
            idiomas=tuple(idiomas.values()),
            certificacoes=tuple(certificacoes.values()),
        )

    async def extrair_curriculo(
        self, texto: TextoAnonimizado, *, orcamento: Orcamento | None = None
    ) -> Resposta[CurriculoExtraido]:
        inicio = time.perf_counter()
        saida = self.extrair_curriculo_sincrono(texto)
        return Resposta(saida=saida, usos=(_uso("extrair_curriculo", inicio),))

    # --- vaga -------------------------------------------------------------------------------

    def extrair_vaga_sincrono(self, texto: str) -> VagaExtraida:
        brutas = [linha for linha in texto.split("\n") if linha.strip()]
        titulo = next(
            (
                _sem_lista(linha.lstrip("#").strip())
                for linha in brutas
                if _sem_lista(linha.lstrip("#").strip())
            ),
            "Vaga",
        )
        dobrado = _dobrar(texto)
        idioma: Literal["pt", "en"] = (
            "en" if len(_INGLES.findall(dobrado)) > len(dobrado.split()) * 0.06 else "pt"
        )
        nivel = _nivel_da_vaga(titulo, texto)
        anos_vaga: int | None = None

        alguma_secao_de_requisitos = any(
            _secao_da_vaga(t) is not None
            for t in (_titulo_de_vaga(linha) for linha in brutas)
            if t is not None
        )
        # Sem nenhum título de requisitos, os itens de lista (até o primeiro título) são os
        # obrigatórios: "- Python\n- SQL" é uma vaga válida.
        tipo_atual: Literal["obrigatorio", "desejavel"] | None = (
            None if alguma_secao_de_requisitos else "obrigatorio"
        )
        requisitos: list[Requisito] = []
        vistos: set[tuple[str, str]] = set()
        primeira_e_titulo = bool(brutas) and not _ITEM_DE_LISTA.match(brutas[0])
        for bruta in brutas[1:] if primeira_e_titulo else brutas:
            titulo_secao = _titulo_de_vaga(bruta)
            if titulo_secao is not None:
                tipo_atual = _secao_da_vaga(titulo_secao)
                if tipo_atual is None and not alguma_secao_de_requisitos:
                    tipo_atual = (
                        None if _IGNORAR_NA_VAGA.search(_dobrar(titulo_secao)) else "obrigatorio"
                    )
                continue
            linha = _sem_lista(bruta)
            dobrada = _dobrar(linha)
            anos_exp = _ANOS_DE_EXPERIENCIA.search(dobrada)
            achados = self._casador.achados(linha)
            if anos_exp is not None:
                anos = int(anos_exp.group(1) or anos_exp.group(2))
                anos_vaga = max(anos_vaga or 0, anos)
                if not _ITEM_DE_LISTA.match(bruta) or not _termo_antes_dos_anos(achados, linha):
                    continue  # "Mínimo de 5 anos de experiência…" é da vaga, não um requisito
            if tipo_atual is None or not _ITEM_DE_LISTA.match(bruta):
                continue
            competencia = achados[0].forma.texto if achados else _termo_livre(linha)
            if not competencia:
                continue
            chave = (tipo_atual, achados[0].forma.canonica if achados else _dobrar(competencia))
            if chave in vistos:
                continue
            vistos.add(chave)
            anos_req = _ANOS.search(dobrada)
            requisitos.append(
                Requisito(
                    descricao=linha,
                    tipo=tipo_atual,
                    competencia=competencia,
                    anos_minimos=int(anos_req.group(1))
                    if anos_req and anos_exp is not None
                    else None,
                    nivel=nivel_de(linha),
                )
            )
        if anos_vaga is None:
            m = _ANOS_DE_EXPERIENCIA.search(dobrado)
            anos_vaga = int(m.group(1) or m.group(2)) if m else None
        return VagaExtraida(
            titulo=titulo[:200],
            idioma=idioma,
            nivel=nivel,
            anos_minimos=anos_vaga,
            requisitos=tuple(requisitos),
        )

    async def extrair_vaga(
        self, texto: str, *, orcamento: Orcamento | None = None
    ) -> Resposta[VagaExtraida]:
        inicio = time.perf_counter()
        saida = self.extrair_vaga_sincrono(texto)
        return Resposta(saida=saida, usos=(_uso("extrair_vaga", inicio),))

    # --- feedback ---------------------------------------------------------------------------

    def montar_feedback(
        self, tabela: TabelaDaNota, vaga: VagaExtraida, texto: TextoAnonimizado
    ) -> FeedbackIA:
        obrigatorios = [linha for linha in tabela.linhas if linha.tipo == "obrigatorio"]
        desejaveis = [linha for linha in tabela.linhas if linha.tipo == "desejavel"]
        lacunas = [linha for linha in tabela.linhas if linha.status != "atende"]

        def com_evidencia(linhas: list[LinhaRequisito]) -> int:
            return sum(1 for linha in linhas if linha.status == "atende")

        frases = [
            "Esta análise foi feita por regras, sem IA (modo demonstração): as competências "
            "foram reconhecidas pela taxonomia do sistema, e cada uma tem o trecho do currículo "
            "que a comprova."
        ]
        if obrigatorios:
            frases.append(
                f"Dos {len(obrigatorios)} requisitos obrigatórios da vaga, "
                f"{com_evidencia(obrigatorios)} têm evidência clara no currículo."
            )
        if desejaveis:
            frases.append(
                f"Dos {len(desejaveis)} diferenciais, {com_evidencia(desejaveis)} têm evidência "
                "clara."
            )
        if tabela.anos_minimos:
            anos = decimal_br(
                Fraction(tabela.anos_relevantes).limit_denominator(12), 1, cortar_zero=True
            )
            frases.append(
                f"A vaga pede {_anos_texto(str(tabela.anos_minimos))} de experiência; as "
                f"experiências relevantes somam {_anos_texto(anos)}."
            )
        if lacunas:
            nomes = ", ".join(linha.competencia_pedida for linha in lacunas[:4])
            frases.append(f"As principais lacunas são: {nomes}.")
        else:
            frases.append("Não encontramos lacunas entre os requisitos da vaga.")
        frases.append(
            "Sem IA, o sistema não sugere reescritas: ele só aponta o que a vaga pede e onde o "
            "currículo já mostra isso."
        )

        lacunas_ia = [
            LacunaIA(requisito=linha.descricao, comentario=_comentario(linha)) for linha in lacunas
        ]
        aprender = [
            AprenderIA(
                competencia=linha.competencia_pedida,
                sugestao=(
                    f"Um curso introdutório ou um projeto prático de {linha.competencia_pedida} "
                    "ajuda a construir essa experiência."
                ),
            )
            for linha in lacunas
        ]
        palavras: list[str] = []
        for requisito in vaga.requisitos:
            if requisito.competencia not in palavras:
                palavras.append(requisito.competencia)
        return FeedbackIA(
            resumo=" ".join(frases),
            lacunas=tuple(lacunas_ia),
            palavras_chave_ats=tuple(palavras),
            reescritas=(),
            o_que_aprender=tuple(aprender),
        )

    async def escrever_feedback(
        self,
        tabela: TabelaDaNota,
        curriculo: CurriculoExtraido,
        vaga: VagaExtraida,
        texto: TextoAnonimizado,
        *,
        orcamento: Orcamento | None = None,
    ) -> AsyncIterator[EventoFeedback]:
        inicio = time.perf_counter()
        yield EventoFeedback(tipo="etapa", texto="escrevendo as sugestões")
        feedback = self.montar_feedback(tabela, vaga, texto)
        palavras = feedback.resumo.split(" ")
        pedaco: list[str] = []
        for palavra in palavras:
            pedaco.append(palavra)
            if sum(len(p) + 1 for p in pedaco) >= TAMANHO_DO_PEDACO:
                yield EventoFeedback(tipo="texto", texto=" ".join(pedaco) + " ")
                pedaco = []
        if pedaco:
            yield EventoFeedback(tipo="texto", texto=" ".join(pedaco))
        yield EventoFeedback(
            tipo="final", feedback=feedback, usos=(_uso("escrever_feedback", inicio),)
        )


def _anos_texto(valor: str) -> str:
    """ "1 ano", "1,5 ano", "3 anos" (concordância; abaixo de 2 é singular)."""
    try:
        numero = float(valor.replace(",", "."))
    except ValueError:
        return f"{valor} anos"
    return f"{valor} ano" if numero < 2 else f"{valor} anos"


def _comentario(linha: LinhaRequisito) -> str:
    competencia = linha.competencia_pedida
    casada = linha.competencia_casada
    status = linha.status
    if status == "parcial" and casada:
        return (
            f"O currículo mostra {casada}, que é próxima de {competencia}, mas não a mesma "
            "competência ou não no tempo ou nível pedidos."
        )
    if status == "parcial":
        return f"Há evidência de {competencia}, mas abaixo do tempo ou do nível pedidos."
    return f"Não encontramos no currículo um trecho que mostre {competencia}."


def _rotulo_nivel(linha: str) -> str | None:
    return nivel_de(linha)


def _nome_certificacao(linha: str) -> str:
    partes = [p for p in _partes(linha) if not _so_datas(p)]
    return (partes[0] if partes else linha)[:200]


def _titulo_de_vaga(linha: str) -> str | None:
    """O título de uma seção da vaga: com `#`, terminado em `:`, ou (rodada 1 da revisão) uma
    linha curta sozinha, sem marcador de lista, com o nome de uma seção conhecida ("Requisitos",
    "Diferenciais", "Nice to have", "**Qualificações**"), com ou sem `:` e negrito."""
    bruta = linha.strip()
    if _ITEM_DE_LISTA.match(bruta):
        return None
    limpa = re.sub(r"^[#\s]+|[*_]{2}", "", bruta).strip().rstrip(":").strip()
    if not limpa or len(limpa.split()) > _PALAVRAS_DE_TITULO:
        return None
    if bruta.startswith("#") or bruta.rstrip("*_ ").endswith(":"):
        return limpa
    dobrada = _dobrar(limpa)
    if _TITULO_DE_VAGA.match(dobrada):
        return limpa
    return None


_TITULO_DE_VAGA = re.compile(
    r"^(?:requisitos?(?: obrigatorios| desejaveis| tecnicos| minimos)?|obrigatorios?|"
    r"diferenciais|desejaveis|desejavel|nice to have|good to have|bonus|plus|extras?|"
    r"requirements?|must have|qualifica(?:coes|cao|tions?)|o que (?:esperamos|buscamos)|"
    r"o que voce (?:vai )?precisa(?:r| ter)?|what you(?:'ll)? need|you have|"
    r"responsabilidades|atividades|beneficios|benefits|sobre (?:a vaga|nos|a empresa)|"
    r"about(?: the role| us)?|responsibilities|o que oferecemos|we offer|local)$"
)


def _secao_da_vaga(titulo: str) -> Literal["obrigatorio", "desejavel"] | None:
    dobrado = _dobrar(titulo)
    if _DESEJAVEIS.search(dobrado):
        return "desejavel"
    if _OBRIGATORIOS.search(dobrado):
        return "obrigatorio"
    return None


def _nivel_da_vaga(titulo: str, texto: str) -> Nivel | None:
    candidatos = [_dobrar(titulo)]
    candidatos += [
        _dobrar(linha)
        for linha in texto.split("\n")
        if re.match(r"\s*(?:nivel|level|senioridade|seniority)\s*:", _dobrar(linha))
    ]
    for alvo in candidatos:
        for nivel, padrao in _NIVEL_DA_VAGA:
            if padrao.search(alvo):
                return nivel
    return None


def _termo_antes_dos_anos(achados: list[_Achado], linha: str) -> bool:
    """ "React (3+ anos)": o termo vem antes do número, então os anos são do requisito."""
    m = _ANOS.search(_dobrar(linha))
    if m is None or not achados:
        return False
    palavras_antes = len(_dobrar(linha)[: m.start()].split())
    return achados[0].posicao < palavras_antes


def _termo_livre(linha: str) -> str:
    """Requisito sem termo da taxonomia: a linha sem o começo genérico ("Experiência com…"), que
    a correspondência compara pelo embedding (ADR 0002)."""
    termo = re.sub(r"\s*\([^)]*\)\s*$", "", linha).strip(" .;:")
    dobrado = _dobrar(termo)
    m = _PREFIXOS_DE_REQUISITO.match(dobrado)
    if m is not None:
        termo = " ".join(termo.split()[len(m.group(0).split()) :])
    return termo[:120]
