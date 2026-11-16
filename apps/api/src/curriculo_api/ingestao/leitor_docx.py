"""Leitura de DOCX: cabeçalhos, corpo (parágrafos, tabelas, controles de conteúdo, caixas de texto)
e rodapés, em ordem, separando o texto oculto.

O python-docx abre o pacote; o XML é percorrido à mão porque a API dele não expõe caixas de texto,
ignora controles de conteúdo e repete células mescladas. Critérios de oculto (ADR 0004), com a
propriedade efetiva do trecho (formatação direta → estilo de caractere → estilo de parágrafo →
padrão do documento):
- `docx_oculto`: `w:vanish` ou `w:specVanish` ligado;
- `fonte_minuscula`: `w:sz` < 8 meios-pontos (4 pt);
- `cor_do_fundo`: cor do texto (`w:color` ou cor de tema de fundo) a menos de `LIMIAR_COR` da cor
  do fundo (sombreamento do trecho, realce, sombreamento do parágrafo ou da célula, fundo da
  página ou branco).

Limitações: alternância de propriedades entre estilos (`vanish` ligado num estilo e desligado no
herdado) usa a primeira ocorrência; estilos de tabela e texto fora da página (âncoras com posição
negativa) não são considerados.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import docx
from docx.oxml.ns import qn

from curriculo_api.ingestao.erros import ArquivoCorrompido, TextoGrande
from curriculo_api.ingestao.leitor_pdf import BRANCO, LIMIAR_COR, Rgb, distancia_cor
from curriculo_api.ingestao.modelos import (
    DocumentoLido,
    ImagemEncontrada,
    Limites,
    MotivoOculto,
    TrechoOculto,
)
from curriculo_api.ingestao.normalizacao import normalizar_texto
from curriculo_api.ingestao.tipo_arquivo import verificar_docx

MEIOS_PONTOS_MINIMOS = 8
EMU_POR_PONTO = 12700
_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
_A_BLIP = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
_V_IMAGEDATA = "{urn:schemas-microsoft-com:vml}imagedata"
_WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
_WP_EXTENT = f"{_WP}extent"
_WP_ANCHOR = f"{_WP}anchor"
_CT_NOTAS = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml",
)
_CT_COMENTARIOS = "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
_CT_CABECALHO = "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"
_CT_RODAPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"
_CORES_DE_REALCE: dict[str, Rgb] = {
    "white": (1.0, 1.0, 1.0),
    "black": (0.0, 0.0, 0.0),
    "yellow": (1.0, 1.0, 0.0),
    "green": (0.0, 1.0, 0.0),
    "cyan": (0.0, 1.0, 1.0),
    "magenta": (1.0, 0.0, 1.0),
    "blue": (0.0, 0.0, 1.0),
    "red": (1.0, 0.0, 0.0),
    "lightGray": (0.75, 0.75, 0.75),
    "darkGray": (0.5, 0.5, 0.5),
}
_TEMAS_CLAROS = {"background1", "light1"}
_TEMAS_ESCUROS = {"text1", "dark1"}
_FALSO = {"0", "false", "off"}


def _hex(valor: str | None) -> Rgb | None:
    if not valor or len(valor) != 6:
        return None
    try:
        return (int(valor[0:2], 16) / 255, int(valor[2:4], 16) / 255, int(valor[4:6], 16) / 255)
    except ValueError:
        return None


def _ligado(el: Any) -> bool:
    return el is not None and (el.get(qn("w:val")) or "true").lower() not in _FALSO


class _Estilos:
    def __init__(self, elemento: Any) -> None:
        self._por_id: dict[str, Any] = {}
        self._padrao_paragrafo: str | None = None
        self._rpr_padrao = None
        if elemento is None:
            return
        for estilo in elemento.findall(qn("w:style")):
            ident = estilo.get(qn("w:styleId"))
            if ident:
                self._por_id[ident] = estilo
                padrao = estilo.get(qn("w:default")) in {"1", "true", "on"}
                if estilo.get(qn("w:type")) == "paragraph" and padrao:
                    self._padrao_paragrafo = ident
        defaults = elemento.find(qn("w:docDefaults"))
        if defaults is not None:
            self._rpr_padrao = defaults.find(f"{qn('w:rPrDefault')}/{qn('w:rPr')}")

    def cadeia(self, ident: str | None) -> list[Any]:
        """`w:rPr` do estilo e dos estilos em que ele se baseia, do mais específico ao geral."""
        saida: list[Any] = []
        vistos: set[str] = set()
        while ident and ident not in vistos and ident in self._por_id:
            vistos.add(ident)
            estilo = self._por_id[ident]
            rpr = estilo.find(qn("w:rPr"))
            if rpr is not None:
                saida.append(rpr)
            base = estilo.find(qn("w:basedOn"))
            ident = base.get(qn("w:val")) if base is not None else None
        return saida

    def fontes_de_propriedade(self, run: Any, paragrafo: Any) -> list[Any]:
        fontes: list[Any] = []
        rpr = run.find(qn("w:rPr"))
        if rpr is not None:
            fontes.append(rpr)
            estilo = rpr.find(qn("w:rStyle"))
            if estilo is not None:
                fontes += self.cadeia(estilo.get(qn("w:val")))
        ppr = paragrafo.find(qn("w:pPr")) if paragrafo is not None else None
        pestilo = ppr.find(qn("w:pStyle")) if ppr is not None else None
        fontes += self.cadeia(
            pestilo.get(qn("w:val")) if pestilo is not None else self._padrao_paragrafo
        )
        if self._rpr_padrao is not None:
            fontes.append(self._rpr_padrao)
        return fontes


def _propriedade(fontes: list[Any], nome: str) -> Any:
    for rpr in fontes:
        el = rpr.find(qn(nome))
        if el is not None:
            return el
    return None


@dataclass
class _Leitura:
    estilos: _Estilos
    fundo_pagina: Rgb
    largura_pagina_emu: int = 612 * EMU_POR_PONTO
    altura_pagina_emu: int = 792 * EMU_POR_PONTO
    visiveis: list[str] = field(default_factory=list)
    ocultos: list[TrechoOculto] = field(default_factory=list)


def _cor_do_texto(fontes: list[Any]) -> Rgb | None:
    cor = _propriedade(fontes, "w:color")
    if cor is None:
        return None
    tema = cor.get(qn("w:themeColor"))
    if tema in _TEMAS_CLAROS:
        return BRANCO
    if tema in _TEMAS_ESCUROS:
        return (0.0, 0.0, 0.0)
    return _hex(cor.get(qn("w:val")))


def _sombreamento(pai: Any, caminho: str) -> Rgb | None:
    if pai is None:
        return None
    shd = pai.find(caminho)
    return _hex(shd.get(qn("w:fill"))) if shd is not None else None


def _fundo(fontes: list[Any], paragrafo: Any, celula: Any, padrao: Rgb) -> Rgb:
    shd = _propriedade(fontes, "w:shd")
    if shd is not None and (cor := _hex(shd.get(qn("w:fill")))) is not None:
        return cor
    realce = _propriedade(fontes, "w:highlight")
    if realce is not None and (cor := _CORES_DE_REALCE.get(realce.get(qn("w:val")) or "")):
        return cor
    if paragrafo is not None:
        cor = _sombreamento(paragrafo.find(qn("w:pPr")), qn("w:shd"))
        if cor is not None:
            return cor
    if celula is not None:
        cor = _sombreamento(celula.find(qn("w:tcPr")), qn("w:shd"))
        if cor is not None:
            return cor
    return padrao


def _motivo_do_run(run: Any, paragrafo: Any, celula: Any, leitura: _Leitura) -> MotivoOculto | None:
    fontes = leitura.estilos.fontes_de_propriedade(run, paragrafo)
    if _ligado(_propriedade(fontes, "w:vanish")) or _ligado(_propriedade(fontes, "w:specVanish")):
        return "docx_oculto"
    tamanho = _propriedade(fontes, "w:sz")
    if tamanho is not None:
        try:
            if int(tamanho.get(qn("w:val")) or "0") < MEIOS_PONTOS_MINIMOS:
                return "fonte_minuscula"
        except ValueError:
            pass
    cor = _cor_do_texto(fontes)
    fundo = _fundo(fontes, paragrafo, celula, leitura.fundo_pagina)
    if cor is not None and distancia_cor(cor, fundo) < LIMIAR_COR:
        return "cor_do_fundo"
    return None


def _texto_do_run(run: Any) -> str:
    partes: list[str] = []
    for el in run:
        if el.tag == qn("w:t"):
            partes.append(el.text or "")
        elif el.tag == qn("w:tab"):
            partes.append("\t")
        elif el.tag in (qn("w:br"), qn("w:cr")):
            partes.append("\n")
        elif el.tag == qn("w:noBreakHyphen"):
            partes.append("-")
    return "".join(partes)


def _dentro_de_fallback(el: Any, limite: Any) -> bool:
    atual = el.getparent()
    while atual is not None and atual is not limite:
        if atual.tag == _MC_FALLBACK:
            return True
        atual = atual.getparent()
    return False


def _paragrafo_dono(el: Any) -> Any:
    atual = el.getparent()
    while atual is not None and atual.tag != qn("w:p"):
        atual = atual.getparent()
    return atual


def _ler_paragrafo(paragrafo: Any, celula: Any, leitura: _Leitura) -> Iterator[str]:
    visivel: list[str] = []
    oculto_atual: tuple[MotivoOculto, list[str]] | None = None

    def fechar_oculto() -> None:
        nonlocal oculto_atual
        if oculto_atual is not None:
            texto = " ".join("".join(oculto_atual[1]).split())
            if texto:
                leitura.ocultos.append(TrechoOculto(texto=texto, motivo=oculto_atual[0]))
            oculto_atual = None

    caixas: list[Any] = []
    for el in paragrafo.iter(qn("w:r"), qn("w:txbxContent")):
        if _dentro_de_fallback(el, paragrafo):
            continue
        if el.tag == qn("w:txbxContent"):
            if _paragrafo_dono(el) is paragrafo:
                caixas.append(el)
            continue
        if _paragrafo_dono(el) is not paragrafo:
            continue  # run de uma caixa de texto: lido com a caixa
        if el.getparent() is not None and el.getparent().tag == qn("w:del"):
            continue  # texto apagado com controle de alterações
        texto = _texto_do_run(el)
        if not texto:
            continue
        motivo = _motivo_do_run(el, paragrafo, celula, leitura)
        if motivo is None:
            fechar_oculto()
            visivel.append(texto)
        else:
            if oculto_atual is None or oculto_atual[0] != motivo:
                fechar_oculto()
                oculto_atual = (motivo, [])
            oculto_atual[1].append(texto)
    fechar_oculto()
    linha = "".join(visivel)
    if linha.strip():
        yield linha
    for caixa in caixas:
        if _caixa_fora_da_pagina(caixa, leitura):
            texto = " ".join("".join(t.text or "" for t in caixa.iter(qn("w:t"))).split())
            if texto:
                leitura.ocultos.append(TrechoOculto(texto=texto, motivo="fora_da_pagina"))
            continue
        yield from _ler_blocos(caixa, None, leitura)


def _elemento(parte: Any) -> Any:
    """O XML de uma parte do pacote (o python-docx só dá `element` às partes que conhece)."""
    elemento = getattr(parte, "element", None)
    if elemento is not None:
        return elemento
    from docx.oxml import parse_xml

    return parse_xml(parte.blob)


def _caixa_fora_da_pagina(caixa: Any, leitura: _Leitura) -> bool:
    """Caixa de texto ancorada com deslocamento que a põe inteira fora da página."""
    ancora = caixa.getparent()
    while ancora is not None and ancora.tag != _WP_ANCHOR:
        ancora = ancora.getparent()
    if ancora is None:
        return False
    extensao = ancora.find(_WP_EXTENT)
    try:
        largura = int(extensao.get("cx") or 0) if extensao is not None else 0
        altura = int(extensao.get("cy") or 0) if extensao is not None else 0
    except ValueError:
        largura = altura = 0
    for eixo, tamanho, limite in (
        ("positionH", largura, leitura.largura_pagina_emu),
        ("positionV", altura, leitura.altura_pagina_emu),
    ):
        posicao = ancora.find(f"{_WP}{eixo}/{_WP}posOffset")
        if posicao is None or not (posicao.text or "").strip().lstrip("-").isdigit():
            continue
        deslocamento = int((posicao.text or "0").strip())
        if deslocamento + tamanho <= 0 or deslocamento >= limite:
            return True
    return False


def _ler_tabela(tabela: Any, leitura: _Leitura) -> Iterator[str]:
    for linha in tabela.findall(qn("w:tr")):
        celulas = [list(_ler_blocos(tc, tc, leitura)) for tc in linha.findall(qn("w:tc"))]
        cheias = [c for c in celulas if any(p.strip() for p in c)]
        if all(len(c) == 1 for c in cheias):
            juntas = " | ".join(c[0].strip() for c in cheias)
            if juntas:
                yield juntas
        else:
            for celula in cheias:
                yield from celula


def _ler_blocos(container: Any, celula: Any, leitura: _Leitura) -> Iterator[str]:
    for filho in container:
        if filho.tag == qn("w:p"):
            yield from _ler_paragrafo(filho, celula, leitura)
        elif filho.tag == qn("w:tbl"):
            yield from _ler_tabela(filho, leitura)
        elif filho.tag == qn("w:sdt"):
            conteudo = filho.find(qn("w:sdtContent"))
            if conteudo is not None:
                yield from _ler_blocos(conteudo, celula, leitura)
        elif filho.tag in (qn("w:customXml"), qn("w:ins"), qn("w:smartTag")):
            yield from _ler_blocos(filho, celula, leitura)


def _imagens(elemento: Any) -> list[ImagemEncontrada]:
    imagens: list[ImagemEncontrada] = []
    for extent in elemento.iter(_WP_EXTENT):
        pai = extent.getparent()
        if pai is not None and any(True for _ in pai.iter(_A_BLIP)):
            try:
                largura = int(extent.get("cx") or 0) / EMU_POR_PONTO
                altura = int(extent.get("cy") or 0) / EMU_POR_PONTO
            except ValueError:
                largura = altura = 0
            imagens.append(ImagemEncontrada(largura=round(largura, 1), altura=round(altura, 1)))
    imagens += [
        ImagemEncontrada()
        for el in elemento.iter(_V_IMAGEDATA)
        if not _dentro_de_fallback(el, None)
    ]
    return imagens


def ler_docx(
    conteudo: bytes, limites: Limites | None = None, *, ja_verificado: bool = False
) -> DocumentoLido:
    limites = limites or Limites()
    if not ja_verificado:
        verificar_docx(conteudo, limites)
    try:
        documento = docx.Document(io.BytesIO(conteudo))
    except Exception:  # pacote OPC inválido, XML quebrado etc.; a mensagem de terceiros não vai
        documento = None
    if documento is None:
        raise ArquivoCorrompido("docx") from None

    corpo = documento.element.body
    fundo = documento.element.find(qn("w:background"))
    fundo_pagina = (_hex(fundo.get(qn("w:color"))) if fundo is not None else None) or BRANCO
    leitura = _Leitura(estilos=_Estilos(documento.styles.element), fundo_pagina=fundo_pagina)

    partes = sorted(documento.part.package.iter_parts(), key=lambda p: str(p.partname))
    cabecalhos = [p for p in partes if p.content_type == _CT_CABECALHO]
    rodapes = [p for p in partes if p.content_type == _CT_RODAPE]
    notas = [p for p in partes if p.content_type in _CT_NOTAS]
    comentarios = [p for p in partes if p.content_type == _CT_COMENTARIOS]
    tamanho = corpo.find(f"{qn('w:sectPr')}/{qn('w:pgSz')}")
    if tamanho is not None:
        try:  # twips → EMU (1 twip = 635 EMU)
            leitura.largura_pagina_emu = int(tamanho.get(qn("w:w")) or 12240) * 635
            leitura.altura_pagina_emu = int(tamanho.get(qn("w:h")) or 15840) * 635
        except ValueError:
            pass

    linhas: list[str] = []
    vistos: set[str] = set()
    imagens: list[ImagemEncontrada] = []
    for parte in cabecalhos:
        bloco = "\n".join(_ler_blocos(parte.element, None, leitura))
        if bloco.strip() and bloco not in vistos:
            vistos.add(bloco)
            linhas.append(bloco)
        imagens += _imagens(parte.element)
    linhas += list(_ler_blocos(corpo, None, leitura))
    imagens += _imagens(corpo)
    for parte in rodapes:
        bloco = "\n".join(_ler_blocos(parte.element, None, leitura))
        if bloco.strip() and bloco not in vistos:
            vistos.add(bloco)
            linhas.append(bloco)
        imagens += _imagens(parte.element)
    # Notas de rodapé e de fim aparecem no documento impresso: entram, no fim, com as mesmas regras
    # de oculto. As de tipo separador são só a linha que separa as notas do texto.
    for parte in notas:
        for nota in _elemento(parte):
            if nota.get(qn("w:type")) in {"separator", "continuationSeparator"}:
                continue
            bloco = "\n".join(_ler_blocos(nota, None, leitura))
            if bloco.strip():
                linhas.append(bloco)
    # Comentários não fazem parte do documento que a pessoa entrega: não são lidos (alerta).
    com_texto = sum(
        1
        for parte in comentarios
        for comentario in _elemento(parte)
        if "".join(t.text or "" for t in comentario.iter(qn("w:t"))).strip()
    )

    texto = normalizar_texto("\n".join(linhas))
    if len(texto) > limites.texto_max_caracteres:
        raise TextoGrande(limites.texto_max_caracteres, arquivo=True)
    return DocumentoLido(
        origem="docx",
        texto=texto,
        ocultos=tuple(leitura.ocultos),
        imagens=tuple(imagens),
        paginas=None,
        comentarios_nao_lidos=com_texto,
    )
