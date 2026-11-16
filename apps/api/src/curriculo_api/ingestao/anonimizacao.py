"""Anonimização antes da IA (ADR 0004): tira nome, foto, nascimento/idade, gênero, estado civil,
família, endereço, CPF, RG, telefone, e-mail, links pessoais e nacionalidade/naturalidade.

Estratégia, em quatro passos sobre o texto visível:
1. **padrões no texto todo** — e-mail, links pessoais, CPF (com ou sem pontuação, válido ou não),
   RG, telefone, CEP, campos rotulados ("Data de nascimento:", "Sexo:", "Estado civil:",
   "Endereço:", "Idade:", "Nacionalidade:", "Apelido:") e as formas em primeira pessoa com
   marcador claro ("tenho 45 anos", "nasci em…", "sou casada", "mãe de dois filhos", "moro na
   Rua X, 10", "Sra."). O rótulo sai junto com o valor.
2. **cabeçalho de contato** — as linhas antes da primeira seção, divididas nos separadores. Ali, e
   só ali, saem também os valores sem rótulo: cidade com UF, logradouro com número, idade ("52
   anos", mas não "10 anos de experiência"), gênero e nacionalidade.
3. **nome** — descoberto nas 3 primeiras linhas não vazias do cabeçalho (ou num campo "Nome:"),
   só se nenhuma parte for termo da taxonomia ou palavra de cargo/área e o candidato não aparecer
   como cargo numa linha de experiência. Sem candidato, nada é apagado por palpite (a ingestão
   emite `nome_nao_identificado`). Achado o nome, saem toda sequência de partes dele (com
   partículas e iniciais no meio: "Beatriz C. Souza") e **toda parte isolada** com inicial
   maiúscula e palavra inteira, exceto as que são termo da taxonomia. Comparação sem acento, com
   classes Unicode (Nguyễn, Ślusarczyk, Adeyemi).
4. **linhas só de marcadores** — uma linha que, depois disso, só tem marcadores e separadores vira
   `[DADOS_PESSOAIS]` (linhas seguidas viram uma só). Assim o formato do cabeçalho (quais dados a
   pessoa pôs, em que ordem) não muda o texto que a IA vê.

A lista do que saiu (tipo, valor original e ocorrências) vai para a tela "o que foi ignorado"; o
valor fica fora do `repr` e nunca é logado.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from functools import lru_cache
from importlib import resources
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from curriculo_api.ingestao.normalizacao import dobrar_1a1, sem_acentos

TipoDado = Literal[
    "nome",
    "email",
    "telefone",
    "cpf",
    "rg",
    "nascimento",
    "idade",
    "genero",
    "estado_civil",
    "familia",
    "endereco",
    "link",
    "nacionalidade",
    "foto",
]

MARCADORES: dict[TipoDado, str] = {
    "nome": "[NOME]",
    "email": "[EMAIL]",
    "telefone": "[TELEFONE]",
    "cpf": "[CPF]",
    "rg": "[RG]",
    "nascimento": "[NASCIMENTO]",
    "idade": "[IDADE]",
    "genero": "[GENERO]",
    "estado_civil": "[ESTADO_CIVIL]",
    "familia": "[FAMILIA]",
    "endereco": "[ENDERECO]",
    "link": "[LINK]",
    "nacionalidade": "[NACIONALIDADE]",
    "foto": "",
}
MARCADOR_DE_LINHA = "[DADOS_PESSOAIS]"


class _Modelo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ItemRemovido(_Modelo):
    tipo: TipoDado
    valor: str = Field(repr=False, description="O valor original. Vai para a tela, nunca para log.")
    ocorrencias: int = Field(ge=1)

    @property
    def mascarado(self) -> str:
        return mascarar(self.tipo, self.valor)


class Anonimizacao(_Modelo):
    texto: str = Field(repr=False)
    removidos: tuple[ItemRemovido, ...]
    nome_encontrado: bool
    nome: str | None = Field(
        default=None, repr=False, description="O nome descoberto (para anonimizar outros trechos)."
    )

    def do_tipo(self, tipo: TipoDado) -> list[ItemRemovido]:
        return [r for r in self.removidos if r.tipo == tipo]


def mascarar(tipo: TipoDado, valor: str) -> str:
    """Forma para a lista visível quando não se quer o valor inteiro ("m•••@•••.com")."""
    if tipo == "foto":
        return valor
    if tipo == "email" and "@" in valor:
        usuario, _, dominio = valor.partition("@")
        sufixo = dominio.rsplit(".", 1)[-1] if "." in dominio else ""
        return f"{usuario[:1]}•••@•••.{sufixo}" if sufixo else f"{usuario[:1]}•••@•••"
    if tipo == "nome":
        return " ".join(f"{p[:1]}•••" for p in valor.split())
    digitos = re.sub(r"\D", "", valor)
    if tipo in {"telefone", "cpf", "rg"} and len(digitos) >= 4:
        return "•••" + digitos[-2:]
    return valor[:1] + "•••" if valor else valor


# --- listas --------------------------------------------------------------------------------------

PARTICULAS = frozenset(
    [
        "da",
        "de",
        "do",
        "das",
        "dos",
        "e",
        "di",
        "du",
        "del",
        "della",
        "van",
        "von",
        "der",
        "den",
        "la",
        "le",
        "y",
        "d'",
        "d’",
        "al",
        "el",
        "bin",
        "ibn",
        "ben",
    ]
)
SUFIXOS_DE_NOME = frozenset(
    {"junior", "jr", "jr.", "filho", "filha", "neto", "neta", "sobrinho", "segundo", "terceiro"}
)
PALAVRAS_DE_TITULO = frozenset(
    sem_acentos(p)
    for p in (
        "currículo curriculum vitae resume résumé cv perfil profile desenvolvedor desenvolvedora "
        "developer engenheiro engenheira engineer analista analyst gerente manager assistente "
        "assistant coordenador coordenadora consultor consultora designer enfermeiro enfermeira "
        "contador contadora técnico técnica estagiário estagiária vendedor vendedora professor "
        "professora diretor diretora especialista specialist supervisor supervisora auxiliar "
        "administrativo administrativa executivo executiva sênior senior pleno júnior junior "
        "front-end back-end full-stack frontend backend fullstack dados data cientista scientist "
        "objetivo resumo experiência experience formação education habilidades skills product "
        "produto owner tech lead líder leader head chefe ux ui qa devops sre scrum master agile "
        "coach marketing digital growth vendas account customer success suporte support "
        "operações operations logística logistics financeiro financeira finance comercial "
        "jurídico advogado advogada lawyer médico médica psicólogo psicóloga arquiteto arquiteta "
        "architect recursos humanos rh people talent recrutador recrutadora recruiter business "
        "intelligence bi analytics software sistemas systems projetos projects officer cto ceo "
        "cfo coo founder fundador fundadora sócio sócia partner trainee estágio intern atendente "
        "operador operadora vendedor representante pesquisador pesquisadora researcher redator "
        "redatora copywriter social media mídia media editor editora"
    )
    .lower()
    .split()
)
SECOES = frozenset(
    sem_acentos(s)
    for s in (
        "resumo",
        "resumo profissional",
        "perfil",
        "perfil profissional",
        "sobre mim",
        "objetivo",
        "objetivo profissional",
        "experiência",
        "experiências",
        "experiência profissional",
        "experiências profissionais",
        "histórico profissional",
        "formação",
        "formação acadêmica",
        "educação",
        "escolaridade",
        "competências",
        "habilidades",
        "conhecimentos",
        "idiomas",
        "certificações",
        "cursos",
        "projetos",
        "summary",
        "professional summary",
        "profile",
        "about",
        "about me",
        "objective",
        "experience",
        "work experience",
        "professional experience",
        "employment",
        "employment history",
        "education",
        "skills",
        "technical skills",
        "languages",
        "certifications",
        "projects",
    )
)
UFS = "AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO"
NACIONALIDADES = (
    r"brasileir[oa]|brazilian|portugues[ae]?|portuguesa|argentin[oa]|uruguai[oa]|paraguai[oa]|"
    r"venezuelan[oa]|colombian[oa]|peruan[oa]|chilen[oa]|boliviano|boliviana|angolan[oa]|"
    r"mocambican[oa]|haitian[oa]|cuban[oa]|american[oa]|estadunidense|italian[oa]|espanhol[a]?|"
    r"frances[a]?|alem[aã]o|alem[aã]|japones[a]?|chines[a]?|naturalizad[oa]"
)

# --- padrões -------------------------------------------------------------------------------------

_I = re.IGNORECASE
_SEP_CAMPO = r"[^\n·|•;]"
_DATA = (
    r"(?:\d{1,2}\s*[/.-]\s*\d{1,2}\s*[/.-]\s*\d{2,4}"
    r"|\d{1,2}\s+de\s+[a-zç]+\s+de\s+\d{4}"
    r"|\d{1,2}(?:st|nd|rd|th)?\s+[a-z]+\.?,?\s+\d{4}"
    r"|[a-z]+\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})"
)

Padrao = tuple[TipoDado, re.Pattern[str]]

PADROES_GLOBAIS: tuple[Padrao, ...] = (
    (
        "email",
        re.compile(r"(?:\be-?mail\s*:?\s*)?(?P<valor>[\w.+-]+@[\w-]+(?:\.[\w-]+)+)", _I),
    ),
    (
        "link",
        re.compile(
            r"(?:\b(?:linkedin|github|gitlab|portf[oó]lio|site|website|blog|behance|lattes)\s*:\s*)?"
            r"(?P<valor>(?:https?://|www\.)[^\s<>()\"']+|\b(?:[a-z]{2,3}\.)?(?:linkedin\.com|"
            r"github\.com|gitlab\.com|behance\.net|dribbble\.com|medium\.com|instagram\.com|"
            r"facebook\.com|twitter\.com|x\.com|lattes\.cnpq\.br|github\.io)/?[^\s<>()\"']*)",
            _I,
        ),
    ),
    (
        "cpf",
        re.compile(
            r"(?:\bCPF\b\s*(?:n[º°o.]*\s*)?:?\s*)?(?P<valor>(?<![\d.])\d{3}\.\d{3}\.\d{3}\s?-\s?\d{2}"
            r"(?![\d]))",
            _I,
        ),
    ),
    (
        "cpf",
        re.compile(r"\bCPF\b\s*(?:n[º°o.]*\s*)?:?\s*(?P<valor>\d[\d.\s/-]{9,16}\d)", _I),
    ),
    ("cpf", re.compile(r"(?<![\d.+/-])(?P<valor>\d{11})(?![\d])")),
    (
        "rg",
        re.compile(
            r"\b(?:RG|R\.G\.|identidade)\b\s*(?:n[º°o.]*\s*)?:?\s*(?P<valor>[\dXx][\dXx.\s/-]{4,14}"
            r"[\dXx](?:\s*[-/]?\s*(?:SSP|SESP|SDS|DETRAN|IFP|PC|SJS)\s*[-/]?\s*[A-Z]{2})?)",
        ),
    ),
    (
        "telefone",
        re.compile(
            r"(?:\b(?:tel(?:efone)?|cel(?:ular)?|fone|whats(?:app)?|phone|mobile|contato)\b\.?\s*"
            r":?\s*)?(?P<valor>(?:\+\s?\d{1,3}\s?)?\(\s?\d{2,3}\s?\)\s?9?\d{4}[-.\s]?\d{4}(?!\d))",
            _I,
        ),
    ),
    (
        "telefone",
        re.compile(
            r"(?:\b(?:tel(?:efone)?|cel(?:ular)?|fone|whats(?:app)?|phone|mobile)\b\.?\s*:?\s*)?"
            r"(?P<valor>\+\s?\d{1,3}[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,5}){2,4}(?!\d))",
            _I,
        ),
    ),
    (
        "telefone",
        re.compile(
            r"\b(?:tel(?:efone)?|cel(?:ular)?|fone|whats(?:app)?|phone|mobile)\b\.?\s*:?\s*"
            r"(?P<valor>\d[\d\s.()-]{7,16}\d)",
            _I,
        ),
    ),
    ("telefone", re.compile(r"(?<![\d/.,-])(?P<valor>(?:\d{2}\s)?9\d{4}-\d{4})(?![\d])")),
    ("endereco", re.compile(r"(?:\bCEP\b\s*:?\s*)?(?P<valor>(?<!\d)\d{5}-\d{3}(?!\d))", _I)),
    ("endereco", re.compile(r"\bCEP\b\s*:?\s*(?P<valor>\d{8})(?!\d)", _I)),
    (
        "nascimento",
        re.compile(
            r"\b(?:data de nascimento|data nasc\.?|nascimento|(?P<genero>nascid[oa]) em|nasc\.|"
            r"date of birth|birth ?date|born(?: on)?|d\.o\.b\.?|dob)\s*:?\s*"
            rf"(?P<valor>{_DATA}(?:\s*\(\s*\d{{1,3}}\s*(?:anos|years)\s*\))?)",
            _I,
        ),
    ),
    (
        "idade",
        re.compile(
            r"\b(?:idade|age)\s*:\s*(?P<valor>\d{1,3}(?:\s*(?:anos|years))?)\b"
            r"|(?P<valor2>\b\d{1,3}\s*anos de idade\b|\b\d{1,3}\s*years? old\b)",
            _I,
        ),
    ),
    (
        "genero",
        re.compile(
            r"\b(?:sexo|g[eê]nero|gender|sex)\s*:\s*(?P<valor>[a-zà-ÿ]+(?:[\s-]+bin[aá]ri[oa])?)",
            _I,
        ),
    ),
    (
        "estado_civil",
        re.compile(
            r"\b(?:estado civil|marital status)\s*:\s*(?P<valor>[a-zà-ÿ]+(?:\s*\(a\))?"
            r"(?:\s+est[aá]vel)?)",
            _I,
        ),
    ),
    (
        "nacionalidade",
        re.compile(
            r"(?:\b(?:nacionalidade|naturalidade|nationality|citizenship)\s*:?|\bnatural de\s*:)\s*"
            rf"(?P<valor>[a-zà-ÿ]{_SEP_CAMPO}{{0,60}}?)(?=\s*(?:[·|•;\n]|$))",
            _I,
        ),
    ),
    (
        "endereco",
        re.compile(
            r"\b(?:endere[cç]o(?: residencial)?|address|resid[eê]ncia|reside em|moro em|"
            rf"bairro)\s*:\s*(?P<valor>{_SEP_CAMPO}{{2,160}}?)(?=\s*(?:[·|•;\n]|$))",
            _I,
        ),
    ),
)

# Só no cabeçalho, segmento inteiro (entre separadores) ou palavra dentro dele.
_CIDADE_UF = re.compile(
    r"^(?:cidade\s*:\s*)?[A-ZÀ-Ý][\wÀ-ÿ'.]*(?:[\s-]+(?:d[aeo]s?\s+)?[A-ZÀ-Ý][\wÀ-ÿ'.]*)*"
    rf"\s*(?:[–—/,-]\s*|\s+)(?:{UFS}|Brasil|Brazil)(?:\s*[,–—-]\s*(?:Brasil|Brazil))?$"
)
_LOGRADOURO = re.compile(
    r"\b(?:Rua|R\.|Avenida|Av\.?|Alameda|Al\.|Travessa|Tv\.|Estrada|Rodovia|Praça|Largo)\s+"
    r"[^,\n·|•]{2,80},?\s*(?:n[º°o.]*\s*)?\d{1,5}\b[^\n·|•]*"
)
_ESTADO_CIVIL = re.compile(
    r"\b(?:solteir[oa]|casad[oa]|divorciad[oa]|separad[oa]|vi[uú]v[oa]|uni[aã]o est[aá]vel|"
    r"single|married|divorced|widowed)(?:\s*\(a\))?\b",
    _I,
)
_IDADE = re.compile(
    r"\b\d{1,3}\s*(?:anos|years)\b(?!\s+(?:de|of)\s+(?:experi|atua|carreira|mercado|trabalho|"
    r"profiss|work|industry))",
    _I,
)
_GENERO = re.compile(
    r"\b(?:masculino|feminino|homem|mulher|male|female|n[aã]o[- ]bin[aá]ri[oa]|non-binary)\b", _I
)
_NACIONALIDADE = re.compile(rf"\b(?:{NACIONALIDADES})\b", _I)
_SEPARADORES = re.compile(r"(\s+[·|•]\s+|\s*\t\s*|\s{3,})")
_MARCADOR = re.compile(r"^\[[A-Z_]+\]$")

# Formas no corpo, com marcador claro (primeira pessoa, honorífico, família, moradia).
_ANOS_NAO_IDADE = r"(?!\s+(?:de|of|em|na|no|como|atuando|trabalhando)\b)"
PADROES_DO_CORPO: tuple[Padrao, ...] = (
    (
        "nascimento",
        re.compile(
            rf"\b(?:nasci|nasceu|born)\s+(?:em|no dia|on|in)\s+(?P<valor>{_DATA}|\d{{4}})", _I
        ),
    ),
    (
        "nacionalidade",
        re.compile(
            r"\b(?:nasci|nasceu|sou natural)\s+(?:em|de|na|no)\s+(?P<valor>[A-ZÀ-Ý][\w'-]+"
            r"(?:\s+(?:d[aeo]s?\s+)?[A-ZÀ-Ý][\w'-]+)*)"
        ),
    ),
    (
        "idade",
        re.compile(
            rf"\b(?:tenho|completei|i am|i'm)\s+(?P<valor>\d{{1,3}}\s*(?:anos|years)"
            rf"(?:\s+old)?){_ANOS_NAO_IDADE}",
            _I,
        ),
    ),
    (
        "estado_civil",
        re.compile(
            r"\b(?:sou|estou|i am|i'm)\s+(?P<valor>(?:solteir|casad|divorciad|separad|vi[uú]v)[oa]"
            r"(?:\s*\(a\))?|noiv[oa]|single|married|divorced|widowed|engaged)\b",
            _I,
        ),
    ),
    (
        "estado_civil",
        re.compile(
            r"\b(?P<valor>(?:solteir|casad|divorciad|vi[uú]v)[oa](?:\s*\(a\))?|uni[aã]o est[aá]vel)"
            r"\b(?!\s+(?:com|de|em)\s+(?:o|a|os|as)?\s*(?:projeto|time|equipe|empresa|cliente))",
            _I,
        ),
    ),
    (
        "familia",
        re.compile(
            r"\b(?P<valor>(?:m[ãa]e|pai|mother|father)\s+(?:de|of)\s+[^.,;\n]{1,40}"
            r"|(?:tenho|i have)\s+(?:\d+|um|uma|dois|duas|tr[eê]s|one|two|three)\s+"
            r"(?:filh[oa]s?|children|kids|sons?|daughters?)|filh[oa]s?\s*:\s*\d+)",
            _I,
        ),
    ),
    (
        "genero",
        re.compile(r"(?<![\w.])(?P<valor>(?:Sr|Sra|Srta|Mr|Mrs|Ms|Miss)\.?)(?=\s+[A-ZÀ-Ý\[])"),
    ),
    (
        "endereco",
        re.compile(
            r"\b(?:moro|resido|reside|vivo|i live)\s+(?:n[ao]s?|em|at|on|in)\s+"
            r"(?P<valor>(?:a\s+|à\s+)?(?:Rua|R\.|Avenida|Av\.?|Alameda|Travessa|Estrada|Praça|"
            r"Street|St\.|Avenue|Ave\.)\s+[^.\n;]{2,120})",
            _I,
        ),
    ),
    (
        "nome",
        re.compile(
            r"\b(?:apelido|nickname|nome social|social name)\s*:\s*(?P<valor>[^\n·|•;.,]{1,40})", _I
        ),
    ),
)


# --- registro ------------------------------------------------------------------------------------


class _Registro:
    def __init__(self) -> None:
        self._contagem: dict[tuple[TipoDado, str], int] = {}

    def anotar(self, tipo: TipoDado, valor: str) -> str:
        valor = " ".join(valor.split())
        chave = (tipo, valor)
        self._contagem[chave] = self._contagem.get(chave, 0) + 1
        return MARCADORES[tipo]

    def itens(self) -> tuple[ItemRemovido, ...]:
        return tuple(
            ItemRemovido(tipo=tipo, valor=valor, ocorrencias=n)
            for (tipo, valor), n in self._contagem.items()
        )


def _valor(m: re.Match[str]) -> str:
    for grupo in ("valor", "valor2"):
        if grupo in m.re.groupindex and m.group(grupo):
            return m.group(grupo)
    return m.group(0)


def _cpf_valido(digitos: str) -> bool:
    if len(digitos) != 11 or len(set(digitos)) == 1:
        return False
    for tamanho in (9, 10):
        soma = sum(
            int(d) * p for d, p in zip(digitos[:tamanho], range(tamanho + 1, 1, -1), strict=True)
        )
        if (soma * 10) % 11 % 10 != int(digitos[tamanho]):
            return False
    return True


# --- cabeçalho -----------------------------------------------------------------------------------


def _titulo_de_secao(linha: str) -> bool:
    s = linha.strip()
    if re.match(r"^#{2,6}\s", s):
        return True
    s = s.lstrip("#").strip().rstrip(":").strip()
    return 0 < len(s) <= 40 and sem_acentos(s).lower() in SECOES


def fim_do_cabecalho(linhas: list[str], maximo: int = 20) -> int:
    """Índice da primeira linha que não é cabeçalho de contato."""
    for i, linha in enumerate(linhas[:maximo]):
        if i > 0 and _titulo_de_secao(linha):
            return i
    cheias = 0
    for i, linha in enumerate(linhas[:maximo]):
        if len(linha) > 160:
            return i
        if linha.strip():
            cheias += 1
            if cheias > 6:
                return i
    return min(len(linhas), maximo)


_ROTULO_NOME = re.compile(r"^\s*(?:nome(?: completo)?|name|full name)\s*:\s*(?P<nome>.+)$", _I)
_PONTUACAO_DE_NOME = "'’-."


def _token_de_nome(token: str) -> bool:
    """Palavra de nome em qualquer alfabeto: letras (com apóstrofo, hífen ou ponto de inicial) e
    a primeira letra maiúscula (ou tudo em maiúsculas)."""
    letras = "".join(c for c in token if c not in _PONTUACAO_DE_NOME)
    return bool(letras) and letras.isalpha() and letras[0].isupper() and token[0] not in "-."


def _dobrada(palavra: str) -> str:
    return sem_acentos(palavra).lower().strip(".,")


def parece_nome(texto: str, protegidas: frozenset[str] = frozenset()) -> bool:
    s = texto.strip().lstrip("#").strip()
    tokens = s.split()
    if not 2 <= len(tokens) <= 12 or len(s) > 150:
        return False
    if any(c.isdigit() or c in "@/|·•:,;()[]{}&+" for c in s):
        return False
    partes = tecnicas = 0
    for token in tokens:
        dobrado = _dobrada(token)
        if dobrado in PARTICULAS:
            continue
        if not _token_de_nome(token) or dobrado in PALAVRAS_DE_TITULO:
            return False
        partes += 1
        tecnicas += dobrado in protegidas
    # "Python Django" ou "React Native" não são nome; "Beatriz Nogueira Sales" é (só uma parte
    # coincide com a taxonomia, e ela não sai sozinha do texto).
    return partes >= 2 and tecnicas * 2 <= partes and tecnicas < partes


_LINHA_DE_EXPERIENCIA = re.compile(r"\d{4}|[—–|]| - ")


def _aparece_como_cargo(candidato: str, linhas: list[str], indice: int) -> bool:
    """O candidato reaparece numa linha de experiência (com ano ou separador de cargo)?"""
    alvo = _dobrada(candidato)
    for i, linha in enumerate(linhas):
        if i != indice and alvo in _dobrada(linha) and _LINHA_DE_EXPERIENCIA.search(linha):
            return True
    return False


def descobrir_nome(
    linhas: list[str], fim: int, protegidas: frozenset[str] = frozenset()
) -> str | None:
    """O nome da pessoa, ou `None` (sem palpite: nada é apagado como nome)."""
    for linha in linhas[:fim]:
        rotulo = _ROTULO_NOME.match(linha)
        if rotulo and parece_nome(rotulo.group("nome"), protegidas):
            return " ".join(rotulo.group("nome").split())
    vistas = 0
    for i, linha in enumerate(linhas[:fim]):
        s = linha.strip().lstrip("#").strip()
        if not s:
            continue
        vistas += 1
        if vistas > 3:
            break
        if parece_nome(s, protegidas) and not _aparece_como_cargo(s, linhas, i):
            return " ".join(s.split())
    return None


def _anonimizar_segmento(segmento: str, registro: _Registro) -> str:
    s = segmento.strip()
    if not s or _MARCADOR.match(s):
        return segmento
    if _CIDADE_UF.match(s) or _LOGRADOURO.search(s):
        return segmento.replace(s, registro.anotar("endereco", s))

    def trocar(padrao: re.Pattern[str], tipo: TipoDado, texto: str) -> str:
        return padrao.sub(lambda m: registro.anotar(tipo, m.group(0)), texto)

    s2 = trocar(_ESTADO_CIVIL, "estado_civil", s)
    s2 = trocar(_IDADE, "idade", s2)
    s2 = trocar(_GENERO, "genero", s2)
    s2 = trocar(_NACIONALIDADE, "nacionalidade", s2)
    return segmento.replace(s, s2) if s2 != s else segmento


_SEPARADORES_DO_CABECALHO = re.compile(r"(\s+[·|•]\s+|\s*\t\s*|\s{3,}|,\s+)")


def _anonimizar_linha_de_cabecalho(linha: str, registro: _Registro) -> str:
    """Segmentos entre ·, |, • e tabulação. Um segmento que é endereço ("Porto Alegre, RS", "Rua X
    120, Lapa, São Paulo") sai inteiro; os outros ainda são divididos na vírgula ("Homem, 61
    anos")."""
    partes = _SEPARADORES.split(linha)
    saida: list[str] = []
    for i, parte in enumerate(partes):
        s = parte.strip()
        if i % 2 or not s or _CIDADE_UF.match(s) or _LOGRADOURO.search(s):
            saida.append(parte if i % 2 else _anonimizar_segmento(parte, registro))
            continue
        pedacos = _SEPARADORES_DO_CABECALHO.split(parte)
        saida.append(
            "".join(
                p if j % 2 else _anonimizar_segmento(p, registro) for j, p in enumerate(pedacos)
            )
        )
    return "".join(saida)


# --- nome ----------------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def palavras_da_taxonomia() -> frozenset[str]:
    """Os termos técnicos de uma palavra só: os da taxonomia ("Oracle", "Go", "Python", "Excel")
    e a lista `tecnologias` de `dados/termos_protegidos.yaml` (Julia, Ruby, Rust, Swift…).
    Palavras soltas de termos compostos ("sales" de "B2B sales") não entram: são comuns demais."""
    from curriculo_api.taxonomia import carregar_taxonomia  # import tardio: evita ciclo

    palavras: set[str] = set()
    for entrada in carregar_taxonomia().arquivo.competencias:
        for termo in (entrada.canonica, *entrada.sinonimos):
            if len(termo.split()) == 1:
                palavras.add(_dobrada(termo).strip("()"))
    palavras.update(_dobrada(t) for t in _lista_protegida()["tecnologias"])
    return frozenset(p for p in palavras if p)


@lru_cache(maxsize=1)
def _lista_protegida() -> dict[str, list[str]]:
    texto = (
        resources.files("curriculo_api").joinpath("dados/termos_protegidos.yaml").read_text("utf-8")
    )
    dados = yaml.safe_load(texto)
    return {
        chave: [str(t) for t in dados.get(chave) or []]
        for chave in ("tecnologias", "lugares", "empresas")
    }


@lru_cache(maxsize=1)
def termos_protegidos() -> frozenset[str]:
    """Tudo o que nunca sai sozinho: termos técnicos, lugares e empresas homônimos de nomes."""
    lista = _lista_protegida()
    extras = {_dobrada(t) for chave in ("lugares", "empresas") for t in lista[chave]}
    return palavras_da_taxonomia() | frozenset(extras)


def partes_do_nome(nome: str) -> list[str]:
    return [p for p in nome.split() if _dobrada(p) not in PARTICULAS and len(p.strip(".")) >= 2]


def _comeca_maiuscula(token: str) -> bool:
    letras = [c for c in token if c.isalpha()]
    return bool(letras) and letras[0].isupper()


_UFS_OU_PAIS = rf"(?:{UFS}|Brasil|Brazil|Portugal|USA|EUA)"
_DEPOIS_LUGAR = re.compile(
    rf"^(?:[ \t]*\([ \t]*{_UFS_OU_PAIS}[ \t]*\)|[ \t]*[,/–—-][ \t]*{_UFS_OU_PAIS}\b)"
)
# A palavra vizinha, pulando no máximo uma partícula ("Prefeitura de Vila…", "Banco do Brasil").
_PARTICULA_ENTRE = r"(?:(?:da|de|do|das|dos|del|di|du)[ \t]+)?"
_TOKEN_ANTES = re.compile(rf"(\S+)[ \t]+{_PARTICULA_ENTRE}$", re.IGNORECASE)
_TOKEN_DEPOIS = re.compile(rf"^[ \t]+{_PARTICULA_ENTRE}(\S+)", re.IGNORECASE)


def _colada_a_nome_proprio(texto: str, inicio: int, fim: int, partes: frozenset[str]) -> bool:
    """A palavra faz parte de um nome próprio maior ("São Paulo", "Banco Santander", "Rosa Chá",
    "Paulo Afonso") ou é uma cidade seguida de UF ("Natal (RN)", "Natal, RN")?"""
    linha_inicio = texto.rfind("\n", 0, inicio) + 1
    linha_fim = texto.find("\n", fim)
    linha_fim = len(texto) if linha_fim < 0 else linha_fim
    antes = _TOKEN_ANTES.search(texto[linha_inicio:inicio])
    depois = _TOKEN_DEPOIS.match(texto[fim:linha_fim])

    def vizinha_propria(token: str) -> bool:
        limpo = token.strip("\"'“”‘’()[]")
        return (
            bool(limpo)
            and limpo[-1].isalnum()
            and _comeca_maiuscula(limpo)
            and not limpo.startswith("[")
            and _dobrada(limpo) not in partes
            and _dobrada(limpo) not in PARTICULAS
        )

    if antes and vizinha_propria(antes.group(1)):
        return True
    if depois and vizinha_propria(depois.group(1).rstrip(".,;:!?")):
        return True
    return bool(_DEPOIS_LUGAR.match(texto[fim:linha_fim]))


def _remover_nome(texto: str, nome: str, protegidas: frozenset[str], registro: _Registro) -> str:
    partes = partes_do_nome(nome)
    if not partes:
        return texto
    todas = frozenset(_dobrada(p) for p in partes)
    protegidas = protegidas | termos_protegidos()
    dobradas = sorted({dobrar_1a1(p) for p in partes}, key=len, reverse=True)
    parte = "(?:" + "|".join(re.escape(p) for p in dobradas) + ")"
    particula = (
        "(?:" + "|".join(re.escape(p) for p in sorted(PARTICULAS, key=len, reverse=True)) + ")"
    )
    inicial = r"\w\."
    ligacao = rf"(?:[ \t]+(?:{particula}[ \t]+|{inicial}[ \t]+)*|-)"
    sequencia = re.compile(rf"(?<![\w@/.-]){parte}(?:{ligacao}{parte})+(?![\w@-])")
    # Sozinhos, "Filho", "Neto", "Júnior" são palavras comuns ("Souza & Filhos"): só em sequência.
    # Sozinha, a parte sai só se não for termo protegido (técnico, lugar, empresa) nem sufixo
    # ("Filho", "Neto"), e se não estiver colada a outro nome próprio (ADR 0004, rodada 2).
    soltas = sorted(
        {
            dobrar_1a1(p)
            for p in partes
            if _dobrada(p) not in SUFIXOS_DE_NOME and _dobrada(p) not in protegidas
        },
        key=len,
        reverse=True,
    )

    def aplicar(padrao: re.Pattern[str], aceitar: Callable[[str, int, int], bool]) -> None:
        nonlocal texto
        dobrado = dobrar_1a1(texto)
        trocas = [
            (m.start(), m.end())
            for m in padrao.finditer(dobrado)
            if aceitar(texto, m.start(), m.end())
        ]
        for inicio, fim in reversed(trocas):
            registro.anotar("nome", texto[inicio:fim])
            texto = texto[:inicio] + MARCADORES["nome"] + texto[fim:]

    def aceitar_sequencia(original: str, inicio: int, fim: int) -> bool:
        tokens = re.split(r"[ \t-]+", original[inicio:fim])
        return all(_comeca_maiuscula(t) for t in tokens if _dobrada(t) not in PARTICULAS)

    def aceitar_isolada(original: str, inicio: int, fim: int) -> bool:
        return _comeca_maiuscula(original[inicio:fim]) and not _colada_a_nome_proprio(
            original, inicio, fim, todas
        )

    aplicar(sequencia, aceitar_sequencia)
    if soltas:
        isolada = re.compile(
            rf"(?<![\w@/.-])(?:{'|'.join(re.escape(p) for p in soltas)})(?![\w@-])"
        )
        aplicar(isolada, aceitar_isolada)
    return texto


# --- tudo junto ----------------------------------------------------------------------------------


def _aplicar(padroes: Iterable[Padrao], texto: str, nome: str | None, registro: _Registro) -> str:
    partes_dobradas = [_dobrada(p) for p in partes_do_nome(nome)] if nome else []
    for tipo, padrao in padroes:

        def trocar(m: re.Match[str], tipo: TipoDado = tipo) -> str:
            valor = _valor(m).rstrip(".,;:)")
            if not valor:
                return m.group(0)
            inicio_valor = m.group(0).rfind(valor)
            sobra = m.group(0)[inicio_valor + len(valor) :]
            if tipo == "link" and not _link_pessoal(valor, partes_dobradas):
                return m.group(0)
            if tipo == "cpf" and re.fullmatch(r"\d{11}", valor):
                tipo_real: TipoDado = "cpf"
                if not _cpf_valido(valor) and valor[2] == "9":
                    tipo_real = "telefone"
                return registro.anotar(tipo_real, valor) + sobra
            if "genero" in m.re.groupindex and m.group("genero"):
                registro.anotar("genero", m.group("genero"))  # "Nascida em" revela o gênero
            return registro.anotar(tipo, valor) + sobra

        texto = padrao.sub(trocar, texto)
    return texto


_DOMINIOS_PESSOAIS = re.compile(
    r"linkedin\.com|github\.com|github\.io|gitlab\.com|behance\.net|dribbble\.com|medium\.com/@|"
    r"instagram\.com|facebook\.com|twitter\.com|x\.com/|lattes\.cnpq\.br",
    _I,
)


def _link_pessoal(url: str, partes_dobradas: Iterable[str]) -> bool:
    if _DOMINIOS_PESSOAIS.search(url):
        return True
    dobrada = sem_acentos(url).lower()
    return any(len(p) >= 3 and p in dobrada for p in partes_dobradas)


_SO_MARCADORES = re.compile(r"^[#>\s]*(?:\[[A-Z_]+\][\s·|•,;:/–—-]*)+$")


def _juntar_linhas_de_marcadores(texto: str) -> str:
    """Linha só de marcadores e separadores → `[DADOS_PESSOAIS]` (as seguidas viram uma). A linha
    que é só o nome (`# [NOME]`) fica, com a marcação de título."""
    saida: list[str] = []
    for linha in texto.split("\n"):
        if _SO_MARCADORES.match(linha) and linha.strip().lstrip("#").strip() != MARCADORES["nome"]:
            if saida and saida[-1] == MARCADOR_DE_LINHA:
                continue
            if len(saida) >= 2 and saida[-1] == "" and saida[-2] == MARCADOR_DE_LINHA:
                saida.pop()
                continue
            saida.append(MARCADOR_DE_LINHA)
        else:
            saida.append(linha)
    return "\n".join(saida)


def anonimizar_trecho(texto: str, nome: str | None) -> str:
    """Os padrões do texto todo e o nome, para um trecho solto (texto oculto, frase de alerta)."""
    registro = _Registro()
    texto = _aplicar((*PADROES_GLOBAIS, *PADROES_DO_CORPO), texto, nome, registro)
    if nome is not None:
        texto = _remover_nome(texto, nome, palavras_da_taxonomia(), registro)
    return texto


def anonimizar(
    texto: str, *, imagens: int = 0, protegidas: frozenset[str] | None = None
) -> Anonimizacao:
    """Anonimiza o texto visível de um currículo. `imagens` = quantas imagens o documento tinha
    (fotos): elas nunca seguem adiante, e a contagem entra na lista do que foi removido."""
    if protegidas is None:
        protegidas = palavras_da_taxonomia()
    registro = _Registro()
    linhas = texto.split("\n")
    fim = fim_do_cabecalho(linhas)
    nome = descobrir_nome(linhas, fim, protegidas)

    texto = _aplicar(PADROES_GLOBAIS, texto, nome, registro)
    texto = _aplicar(PADROES_DO_CORPO, texto, nome, registro)
    linhas = texto.split("\n")
    for i in range(min(fim, len(linhas))):
        linhas[i] = _anonimizar_linha_de_cabecalho(linhas[i], registro)
    texto = "\n".join(linhas)
    if nome is not None:
        texto = _remover_nome(texto, nome, protegidas, registro)
    texto = _juntar_linhas_de_marcadores(texto)
    if imagens:
        registro.anotar(
            "foto",
            f"{imagens} imagem descartada" if imagens == 1 else f"{imagens} imagens descartadas",
        )
    return Anonimizacao(
        texto=texto, removidos=registro.itens(), nome_encontrado=nome is not None, nome=nome
    )
