"""Ancoragem (ADR 0003, passo 2): item da IA sem trecho que o comprove é descartado.

Rodada 1 da fase 3: não basta o trecho existir no texto, ele tem de **ligar o item**. Regras, em
ordem (a primeira que falha decide o motivo do descarte):

1. **marcador**: trecho com marcador de anonimização (`[NOME]`, `[EMAIL]`…) não comprova nada;
2. **curto**: o trecho precisa de pelo menos `PALAVRAS_MINIMAS` palavras e `CARACTERES_MINIMOS`
   caracteres (normalizado). "a" ou "Python" sozinhos não são citação;
3. **sem_ancora**: o trecho precisa existir no texto, depois de normalizar dos dois lados (NFKC,
   largura zero, `‹ ›` de volta para `< >` — o prompt escapa os sinais —, caixa, espaços, hífen de
   quebra de linha, aspas e travessões). Acento, pontuação e ordem das palavras continuam valendo;
4. **injecao**: o trecho cai numa linha que a ingestão marcou com `instrucao_para_ia`. Esse
   descarte tem contador próprio e não entra na métrica 2 (não é erro de extração);
5. **termo_fora_do_trecho**: o termo do item (o nome extraído, ou uma forma da canônica e dos
   sinônimos da taxonomia) aparece **dentro** do trecho como palavra inteira, com flexão só de
   plural e gênero ("conciliações" = "conciliação"; "excelente" ≠ "Excel"), e as palavras de um
   termo composto contíguas e em ordem (rodada 3). Uma lista de habilidades ("Python, SQL,
   Docker") comprova cada termo da lista (ADR 0003);
5b. **negacao** (competências, idiomas e certificações, rodada 3): o termo só aparece negado ou
   como aspiração na mesma oração ("Nunca usei Kubernetes", "Sem experiência em AWS", "Quero
   aprender Terraform", "Python não"). Contador próprio, fora da métrica 2;
6. **datas** (experiências, rodada 2): o ano de início e o de fim, ou um marcador de emprego atual
   ("atual", "o momento", "Present"…), aparecem no trecho, e o mês também, se a extração o deu. Se
   não aparecem, a experiência **não** é descartada (o erro é do modelo, não da pessoa): o código
   lê as datas do próprio trecho (`datas_do_trecho`) e, se conseguir, usa essas ("data corrigida
   pelo trecho"); se o trecho não tem datas ou elas são ambíguas, a experiência fica, com as
   ligações das competências, mas sem contar anos (`datas_comprovadas = False`, com aviso).

Depois do filtro:
- o **nível** de idioma e de competência é o que o trecho diz (veja `correspondencia`);
- cada ligação `Competencia.experiencias` só fica se a competência (o trecho dela ou o termo)
  aparece na **região do texto** daquela experiência: da linha da experiência até a próxima
  experiência ou o próximo título de seção. As outras ligações são removidas e contadas.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from curriculo_api.alertas import Alerta
from curriculo_api.flexao import mesma_palavra
from curriculo_api.ia.modelos import (
    Certificacao,
    Competencia,
    CurriculoExtraido,
    DataParcial,
    Experiencia,
    Formacao,
    Idioma,
    SecaoCurriculo,
)
from curriculo_api.ingestao.normalizacao import remover_largura_zero, sem_acentos
from curriculo_api.taxonomia import Taxonomia, carregar_taxonomia

PALAVRAS_MINIMAS = 2
CARACTERES_MINIMOS = 8
PREFIXO_FLEXAO = 5

MotivoDescarte = Literal[
    "marcador",
    "curto",
    "sem_ancora",
    "injecao",
    "termo_fora_do_trecho",
    "datas_fora_do_trecho",  # não é mais usado para descartar (rodada 2); fica por compatibilidade
    "negacao",
]

_HIFEN_DE_QUEBRA = re.compile(r"(?<=[^\W\d_])-[ \t]*\r?\n[ \t]*(?=[a-zà-öø-ÿ])")
_ASPAS_DUPLAS = re.compile(r"[“”„‟«»″]")
_ASPAS_SIMPLES = re.compile(r"[‘’‚‛´`′]")
_TRACOS = re.compile(r"[‐‑‒–—―−]")
_MARCADOR = re.compile(r"\[[A-Z_]{2,}\]")
_PALAVRA = re.compile(r"[\w#+]+")
_TITULO_DE_SECAO = re.compile(
    r"^\s*(?:#+\s*.*|(?:forma[cç][aã]o(?: acad[eê]mica)?|educa[cç][aã]o|education|idiomas|"
    r"languages|habilidades|compet[eê]ncias|skills|certifica[cç](?:[oõ]es|[aã]o)|certifications|"
    r"cursos(?: livres)?|courses|resumo|sobre mim|summary|profile|perfil|projetos|projects|"
    r"experi[eê]ncia(?: profissional)?|experience|work experience|interesses|refer[eê]ncias)"
    r"\s*:?\s*)$",
    re.IGNORECASE,
)
_PALAVRAS_VAZIAS = frozenset(
    [
        "a",
        "o",
        "as",
        "os",
        "de",
        "da",
        "do",
        "das",
        "dos",
        "e",
        "em",
        "no",
        "na",
        "nos",
        "nas",
        "com",
        "para",
        "por",
        "um",
        "uma",
        "of",
        "and",
        "the",
        "in",
        "on",
        "for",
        "with",
        "to",
        "at",
        "by",
        "an",
    ]
)
_MESES: dict[int, tuple[str, ...]] = {
    1: ("jan", "janeiro", "january"),
    2: ("fev", "fevereiro", "feb", "february"),
    3: ("mar", "marco", "march"),
    4: ("abr", "abril", "apr", "april"),
    5: ("mai", "maio", "may"),
    6: ("jun", "junho", "june"),
    7: ("jul", "julho", "july"),
    8: ("ago", "agosto", "aug", "august"),
    9: ("set", "setembro", "sep", "sept", "september"),
    10: ("out", "outubro", "oct", "october"),
    11: ("nov", "novembro", "november"),
    12: ("dez", "dezembro", "dec", "december"),
}
_ATUAL = re.compile(
    r"\b(?:atual|atualmente|o momento|momento|presente|present|hoje|current|currently|now|"
    r"today|em andamento|desde|since)\b"
)


def normalizar_para_ancora(texto: str) -> str:
    """A forma usada para comparar trecho e texto."""
    texto = remover_largura_zero(texto)
    texto = unicodedata.normalize("NFKC", texto).replace("‹", "<").replace("›", ">")
    texto = _HIFEN_DE_QUEBRA.sub("", texto)
    texto = _ASPAS_DUPLAS.sub('"', texto)
    texto = _ASPAS_SIMPLES.sub("'", texto)
    texto = _TRACOS.sub("-", texto)
    return " ".join(texto.casefold().split())


def _dobrado(texto: str) -> str:
    return sem_acentos(normalizar_para_ancora(texto))


def _palavras(texto: str) -> list[str]:
    return _PALAVRA.findall(_dobrado(texto))


class _TemTrecho(Protocol):
    @property
    def trecho(self) -> str: ...


def trecho_ancorado(trecho: str, texto: str) -> bool:
    alvo = normalizar_para_ancora(trecho)
    return bool(alvo) and alvo in normalizar_para_ancora(texto)


MAX_VAZIAS_ENTRE = 2


def ocorrencias(termo: str, texto: str) -> list[tuple[int, int]]:
    """Onde o termo aparece no texto, como intervalos [início, fim) de índices de palavra (rodada
    3): palavra inteira, com flexão só de plural e gênero (`flexao.py`), e as palavras de conteúdo
    de um termo composto contíguas e em ordem (entre elas, no máximo duas palavras vazias: "gestão
    de projetos" casa "gestão dos projetos", não "projeção … gestante")."""
    alvo = _palavras(termo)
    if not alvo:
        return []
    palavras = _palavras(texto)
    conteudo = [p for p in alvo if p not in _PALAVRAS_VAZIAS] or alvo
    achados: list[tuple[int, int]] = []
    for i, primeira in enumerate(palavras):
        if not mesma_palavra(conteudo[0], primeira):
            continue
        j, ok = i, True
        for p in conteudo[1:]:
            k = j + 1
            while (
                k < len(palavras)
                and k - j - 1 < MAX_VAZIAS_ENTRE
                and palavras[k] in (_PALAVRAS_VAZIAS)
                and not mesma_palavra(p, palavras[k])
            ):
                k += 1
            if k < len(palavras) and mesma_palavra(p, palavras[k]):
                j = k
            else:
                ok = False
                break
        if ok:
            achados.append((i, j + 1))
    return achados


def termo_no_texto(termo: str, texto: str) -> bool:
    return bool(ocorrencias(termo, texto))


_NEGACAO_ANTES = re.compile(
    r"\b(?:nunca|nao|sem|nenhum|nenhuma|jamais|quero aprender|pretendo aprender|"
    r"gostaria de aprender|aprendendo|cursando|em curso|futuramente|interesse em|"
    r"never|not|without|no experience|no prior|want to learn|learning|currently studying|"
    r"studying|planning to)\b"
)
_NEGACAO_DEPOIS = re.compile(r"^\W*(?:\w+\W+){0,2}?(?:nao|not)\b")
_ORACAO = re.compile(r"[.;!?]|\bmas\b|\bbut\b|\bporem\b|\bhowever\b")


def _ocorrencia_afirmada(termo: str, trecho: str) -> bool | None:
    """True se o termo aparece no trecho pelo menos uma vez sem negação nem aspiração na mesma
    oração ("Nunca usei Kubernetes", "Quero aprender Terraform", "Python não"); False se só
    aparece negado; None se não aparece."""
    achou = False
    for oracao in _ORACAO.split(_dobrado(trecho)):
        palavras = _PALAVRA.findall(oracao)
        for inicio, fim in ocorrencias(termo, oracao):
            achou = True
            antes = " ".join(palavras[:inicio])
            depois = " ".join(palavras[fim:])
            if not _NEGACAO_ANTES.search(antes) and not _NEGACAO_DEPOIS.search(depois):
                return True
    return False if achou else None


def termo_negado(nomes: Iterable[str | None], trecho: str, taxonomia: Taxonomia) -> bool:
    """O termo está no trecho, mas só negado ou como aspiração."""
    resultados = [
        _ocorrencia_afirmada(forma, trecho)
        for nome in nomes
        if nome
        for forma in formas_do_termo(nome, taxonomia)
    ]
    return not any(r is True for r in resultados) and any(r is False for r in resultados)


def formas_do_termo(nome: str, taxonomia: Taxonomia) -> list[str]:
    canonica = taxonomia.canonica_de(nome)
    formas = [nome]
    if canonica is not None:
        entrada = next(e for e in taxonomia.arquivo.competencias if e.canonica == canonica)
        formas += [entrada.canonica, *entrada.sinonimos]
    return formas


def algum_termo_no_texto(nomes: Iterable[str | None], texto: str, taxonomia: Taxonomia) -> bool:
    return any(
        termo_no_texto(forma, texto)
        for nome in nomes
        if nome
        for forma in formas_do_termo(nome, taxonomia)
    )


def _mes_no_trecho(mes: int, trecho: str) -> bool:
    if set(_palavras(trecho)) & set(_MESES[mes]):
        return True
    return re.search(rf"(?<!\d)0?{mes}\s*[/.-]\s*\d{{2,4}}", _dobrado(trecho)) is not None


def datas_no_trecho(experiencia: Experiencia) -> bool:
    """O ano (e o mês, se informado) do início e do fim, ou o marcador de atual, estão no trecho."""
    dobrado = _dobrado(experiencia.trecho)
    anos = set(re.findall(r"(?<!\d)\d{4}(?!\d)", dobrado))
    if str(experiencia.inicio.ano) not in anos:
        return False
    if experiencia.inicio.mes is not None and not _mes_no_trecho(
        experiencia.inicio.mes, experiencia.trecho
    ):
        return False
    if experiencia.fim is None:
        return _ATUAL.search(dobrado) is not None
    if str(experiencia.fim.ano) not in anos:
        return False
    return experiencia.fim.mes is None or _mes_no_trecho(experiencia.fim.mes, experiencia.trecho)


_MES_POR_NOME = {nome: mes for mes, nomes in _MESES.items() for nome in nomes}
_NOMES_DE_MES = "|".join(sorted(_MES_POR_NOME, key=len, reverse=True))
_DATA_OU_ATUAL = re.compile(
    rf"\b(?P<mes_nome>{_NOMES_DE_MES})\.?\s*(?:/|de|-)?\s*(?P<ano1>(?:19|20)\d{{2}})(?!\d)"
    r"|(?<!\d)(?P<mes_num>0?[1-9]|1[0-2])\s*[/.-]\s*(?P<ano2>(?:19|20)\d{2})(?!\d)"
    r"|(?<!\d)(?P<ano3>(?:19|20)\d{2})(?!\d)"
    r"|(?P<atual>\b(?:atual|atualmente|o momento|presente|present|hoje|current|currently|now|"
    r"today|em andamento)\b)"
)


def datas_do_trecho(
    trecho: str,
) -> tuple[DataParcial, DataParcial | None] | None:
    """Lê início e fim do trecho, pelas regras do ADR 0003: "mar/2022 – atual", "2019 – 2021",
    "Sep 2020 – Present", "03/2019 – 12/2020" ou um ano só ("2024" = o ano inteiro). Devolve
    `None` se não há data, se há mais de duas, se o fim vem antes do início ou se "atual" aparece
    antes da primeira data (ambíguo)."""
    datas: list[DataParcial | None] = []  # None = marcador de atual
    for m in _DATA_OU_ATUAL.finditer(_dobrado(trecho)):
        if m.group("atual"):
            datas.append(None)
            continue
        if m.group("ano1"):
            mes = _MES_POR_NOME[m.group("mes_nome")]
            datas.append(DataParcial(ano=int(m.group("ano1")), mes=mes))
        elif m.group("ano2"):
            datas.append(DataParcial(ano=int(m.group("ano2")), mes=int(m.group("mes_num"))))
        else:
            datas.append(DataParcial(ano=int(m.group("ano3"))))
    if not datas or datas[0] is None or len(datas) > 2:
        return None
    inicio = datas[0]
    if len(datas) == 1:
        return inicio, inicio  # um ano (ou mês) só
    fim = datas[1]
    if fim is not None and fim.indice_fim() < inicio.indice_inicio():
        return None
    return inicio, fim


@dataclass(frozen=True)
class ItemDescartado:
    secao: SecaoCurriculo
    trecho: str = field(repr=False)
    motivo: MotivoDescarte = "sem_ancora"


@dataclass(frozen=True)
class ResultadoAncoragem:
    mantido: CurriculoExtraido
    descartados: tuple[ItemDescartado, ...]
    """Descartes por trecho inválido (métrica 2). Os por injection ficam à parte."""
    descartados_por_injecao: tuple[ItemDescartado, ...] = ()
    descartados_por_negacao: tuple[ItemDescartado, ...] = ()
    """O termo só aparece negado ou como aspiração ("Nunca usei…", "Quero aprender…")."""
    ligacoes_removidas: int = 0
    """Ligações competência → experiência fora da região do texto daquela experiência."""
    datas_corrigidas: int = 0
    """Experiências cujas datas da IA não estavam no trecho e foram lidas do próprio trecho."""
    datas_nao_comprovadas: int = 0
    """Experiências mantidas sem contar anos: nem a IA nem o trecho deram datas confiáveis."""


class _Contexto:
    def __init__(self, texto: str, taxonomia: Taxonomia, alertas: Sequence[Alerta]) -> None:
        self.texto = texto
        self.taxonomia = taxonomia
        brutas = _HIFEN_DE_QUEBRA.sub("", texto).split("\n")
        linhas = [normalizar_para_ancora(linha) for linha in brutas]
        self.trechos_de_alerta = [
            normalizar_para_ancora(a.trecho)
            for a in alertas
            if a.tipo == "instrucao_para_ia" and a.origem == "curriculo" and a.trecho.strip()
        ]
        self.zonas = [
            linha
            for linha in linhas
            if linha
            and any(t in linha or (len(linha) >= 20 and linha in t) for t in self.trechos_de_alerta)
        ]
        # O texto numa linha só, com a posição de cada título de seção.
        self.titulos: list[int] = []
        partes: list[str] = []
        posicao = 0
        for bruta, linha in zip(brutas, linhas, strict=True):
            if not linha:
                continue
            if _TITULO_DE_SECAO.match(bruta.strip()):
                self.titulos.append(posicao)
            partes.append(linha)
            posicao += len(linha) + 1
        self.corrido = " ".join(partes)

    def em_injecao(self, trecho: str) -> bool:
        alvo = normalizar_para_ancora(trecho)
        if any(alvo in zona for zona in self.zonas):
            return True
        return any(t in alvo or alvo in t for t in self.trechos_de_alerta)

    def motivo(
        self, trecho: str, termos: Sequence[str | None], conferir_negacao: bool = True
    ) -> MotivoDescarte | None:
        if _MARCADOR.search(trecho):
            return "marcador"
        normalizado = normalizar_para_ancora(trecho)
        if len(_palavras(trecho)) < PALAVRAS_MINIMAS or len(normalizado) < CARACTERES_MINIMOS:
            return "curto"
        if not trecho_ancorado(trecho, self.texto):
            return "sem_ancora"
        if self.em_injecao(trecho):
            return "injecao"
        if not algum_termo_no_texto(termos, trecho, self.taxonomia):
            return "termo_fora_do_trecho"
        if conferir_negacao and termo_negado(termos, trecho, self.taxonomia):
            return "negacao"
        return None

    def regiao(self, experiencia: Experiencia, todas: Sequence[Experiencia]) -> str | None:
        inicio = self.corrido.find(normalizar_para_ancora(experiencia.trecho))
        if inicio < 0:
            return None
        fins = [len(self.corrido)]
        for outra in todas:
            if outra is experiencia:
                continue
            p = self.corrido.find(normalizar_para_ancora(outra.trecho))
            if p > inicio:
                fins.append(p)
        fins += [t for t in self.titulos if t > inicio]
        return self.corrido[inicio : min(fins)]


def ancorar(
    curriculo: CurriculoExtraido,
    texto: str,
    taxonomia: Taxonomia | None = None,
    alertas: Sequence[Alerta] = (),
) -> ResultadoAncoragem:
    """Filtra cada seção pelas regras do módulo e renumera e confere as ligações de experiência
    das competências mantidas."""
    ctx = _Contexto(texto, taxonomia or carregar_taxonomia(), alertas)
    descartados: list[ItemDescartado] = []
    por_injecao: list[ItemDescartado] = []
    por_negacao: list[ItemDescartado] = []

    def aceitar(secao: SecaoCurriculo, trecho: str, termos: Sequence[str | None]) -> bool:
        motivo = ctx.motivo(trecho, termos, secao in ("competencias", "idiomas", "certificacoes"))
        if motivo is None:
            return True
        destino = (
            por_injecao
            if motivo == "injecao"
            else por_negacao
            if motivo == "negacao"
            else descartados
        )
        destino.append(ItemDescartado(secao=secao, trecho=trecho, motivo=motivo))
        return False

    novo_indice: dict[int, int] = {}
    experiencias: list[Experiencia] = []
    corrigidas = nao_comprovadas = 0
    for i, e in enumerate(curriculo.experiencias):
        if not aceitar("experiencias", e.trecho, [e.cargo, e.empresa]):
            continue
        if not datas_no_trecho(e):
            lidas = datas_do_trecho(e.trecho)
            if lidas is not None:
                e = e.model_copy(update={"inicio": lidas[0], "fim": lidas[1]})
                corrigidas += 1
            else:
                e = e.model_copy(update={"datas_comprovadas": False})
                nao_comprovadas += 1
        novo_indice[i] = len(experiencias)
        experiencias.append(e)

    regioes = [ctx.regiao(e, experiencias) for e in experiencias]
    removidas = 0
    competencias: list[Competencia] = []
    for c in curriculo.competencias:
        if not aceitar("competencias", c.trecho, [c.nome]):
            continue
        ligacoes: list[int] = []
        for i in c.experiencias:
            j = novo_indice.get(i)
            if j is None:
                continue
            regiao = regioes[j]
            if regiao is not None and (
                normalizar_para_ancora(c.trecho) in regiao
                or algum_termo_no_texto([c.nome], regiao, ctx.taxonomia)
            ):
                ligacoes.append(j)
            else:
                removidas += 1
        competencias.append(c.model_copy(update={"experiencias": tuple(ligacoes)}))

    formacao: list[Formacao] = [
        f for f in curriculo.formacao if aceitar("formacao", f.trecho, [f.curso, f.instituicao])
    ]
    idiomas: list[Idioma] = [
        i for i in curriculo.idiomas if aceitar("idiomas", i.trecho, [i.idioma])
    ]
    certificacoes: list[Certificacao] = [
        c
        for c in curriculo.certificacoes
        if aceitar("certificacoes", c.trecho, [c.nome, c.competencia])
    ]
    mantido = CurriculoExtraido(
        experiencias=tuple(experiencias),
        competencias=tuple(competencias),
        formacao=tuple(formacao),
        idiomas=tuple(idiomas),
        certificacoes=tuple(certificacoes),
    )
    return ResultadoAncoragem(
        mantido=mantido,
        descartados=tuple(descartados),
        descartados_por_injecao=tuple(por_injecao),
        descartados_por_negacao=tuple(por_negacao),
        ligacoes_removidas=removidas,
        datas_corrigidas=corrigidas,
        datas_nao_comprovadas=nao_comprovadas,
    )
