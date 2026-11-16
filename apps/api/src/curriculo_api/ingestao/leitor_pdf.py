"""Leitura de PDF com pdfplumber: texto visível, texto oculto, imagens e páginas escaneadas.

Cada caractere é classificado antes da extração. Os ocultos saem do texto analisado e viram
`TrechoOculto` (com motivo e página); o texto visível passa por ordem de leitura (detecção simples
de duas colunas), junção de hífen de quebra de linha, remoção de cabeçalho e rodapé repetidos e
`normalizar_texto`.

Critérios de oculto (ADR 0004), na ordem em que são testados:
1. `fora_da_pagina`: o centro do caractere fica fora da área visível (mediabox ∩ cropbox);
2. `fonte_minuscula`: tamanho efetivo (tamanho da fonte × escala vertical da matriz) < 4,5 pt;
3. `texto_comprimido`: escala horizontal efetiva (`Tz` × matriz) < 30 %;
4. `renderizacao_invisivel`: modo de renderização 3 ou 7, exceto numa página escaneada (imagem
   cobrindo > 80 % da página e nenhum texto visível fora dela), onde é a camada de OCR;
5. **renderização** (decisão principal para cor, fundo, sobreposição, opacidade e recorte): a página
   é desenhada pelo pdfium e o caractere sem contraste visível na caixa dele é oculto
   (`invisivel_na_renderizacao`, ou `cor_do_fundo` quando a heurística de cor também apontava).
   Se a página não pôde ser desenhada (ou tem `/Rotate`), vale a heurística de cor: distância RGB
   < `LIMIAR_COR` entre o texto e o último retângulo preenchido sob ele (ou o branco).
"""

from __future__ import annotations

import io
import logging
import math
import time
from collections.abc import Callable, Iterable, Sequence
from typing import Any

import pdfplumber
import pdfplumber.page as _pagina_pdfplumber
from pdfminer.pdfdocument import PDFEncryptionError, PDFPasswordIncorrect

from curriculo_api.ingestao.erros import (
    ArquivoCorrompido,
    ErroIngestao,
    MuitasPaginas,
    PdfCriptografado,
    PdfPesado,
    TextoGrande,
)
from curriculo_api.ingestao.modelos import (
    DocumentoLido,
    ImagemEncontrada,
    Limites,
    MotivoOculto,
    TrechoOculto,
)
from curriculo_api.ingestao.normalizacao import (
    juntar_hifens_de_quebra,
    normalizar_texto,
    remover_cabecalhos_e_rodapes,
)
from curriculo_api.ingestao.renderizacao import (
    CONTRASTE_MINIMO,
    FRACAO_MINIMA_DE_TINTA,
    PaginaRenderizada,
    Renderizador,
)

log = logging.getLogger("curriculo_api.ingestao")

FONTE_MINIMA_PT = 4.5
"""4 pt (o ataque `fonte_4_0` do Validador) ainda passa por texto de rodapé; 4,5 pt é o menor que
um currículo usa na prática. Rodapé legítimo em 3,5–4,4 pt vira oculto (limiar de fronteira)."""
COMPRESSAO_MINIMA = 0.3
"""Escala horizontal (`Tz`) abaixo de 30 % espreme o texto até virar um traço."""
ESPACAMENTO_MINIMO = -0.25
"""Espaçamento entre caracteres (`Tc`) abaixo de −25 % do tamanho da fonte empilha as letras umas
sobre as outras (kerning apertado de verdade fica em −2 a −5 %)."""
LIMIAR_COR = 0.25
"""Heurística de cor, usada quando a página não pode ser desenhada: distância euclidiana máxima
entre texto e fundo, com RGB em 0–1 (o máximo é √3 ≈ 1,73)."""
BRANCO = (1.0, 1.0, 1.0)
MODOS_INVISIVEIS = frozenset({3, 7})

Objeto = dict[str, Any]
Rgb = tuple[float, float, float]


# --- modo de renderização ------------------------------------------------------------------------
# O pdfminer conhece o modo de renderização (`Tr`) do estado de texto, mas não o copia para o
# caractere, e o pdfplumber só copia atributos de uma lista fixa. A subclasse abaixo guarda o modo
# em cada caractere, e o atributo entra na lista. Se uma versão futura mudar esses internos, a
# detecção por modo fica indisponível (`MODO_DE_RENDERIZACAO_DISPONIVEL` falso) e um teste avisa.


def _instalar_modo_de_renderizacao() -> bool:
    base = getattr(_pagina_pdfplumber, "PDFPageAggregatorWithMarkedContent", None)
    atributos = getattr(_pagina_pdfplumber, "ALL_ATTRS", None)
    if base is None or not isinstance(atributos, set):
        return False
    if getattr(base, "_curriculo_modo_instalado", False):
        return True

    class _ComModoDeRenderizacao(base):  # type: ignore[misc, valid-type]
        _curriculo_modo_instalado = True
        _modo_atual = 0

        def render_string(self, textstate: Any, *args: Any, **kwargs: Any) -> Any:
            self._modo_atual = int(getattr(textstate, "render", 0) or 0)
            try:  # espaçamento entre caracteres (Tc) relativo ao tamanho da fonte
                self._espacamento = float(textstate.charspace) / (float(textstate.fontsize) or 1.0)
            except (AttributeError, TypeError, ValueError):
                self._espacamento = 0.0
            return super().render_string(textstate, *args, **kwargs)

        def render_char(self, *args: Any, **kwargs: Any) -> Any:
            avanco = super().render_char(*args, **kwargs)
            objetos = getattr(self.cur_item, "_objs", None)
            if objetos:
                obj = objetos[-1]
                obj.modo_renderizacao = self._modo_atual
                obj.espacamento_relativo = getattr(self, "_espacamento", 0.0)
                # args = (matriz, fonte, tamanho, escala Tz, rise, cid, …), pdfminer.six 2026.
                try:
                    a, b, c, d = (float(v) for v in args[0][:4])
                    vertical = math.hypot(c, d)
                    obj.tamanho_efetivo = float(args[2]) * vertical
                    obj.compressao_horizontal = (
                        float(args[3]) * math.hypot(a, b) / vertical if vertical else 0.0
                    )
                except (IndexError, TypeError, ValueError):
                    pass
            return avanco

    _pagina_pdfplumber.PDFPageAggregatorWithMarkedContent = _ComModoDeRenderizacao  # type: ignore[misc]
    atributos.update(
        {"modo_renderizacao", "tamanho_efetivo", "compressao_horizontal", "espacamento_relativo"}
    )
    return True


MODO_DE_RENDERIZACAO_DISPONIVEL = _instalar_modo_de_renderizacao()


# --- cores ---------------------------------------------------------------------------------------


def para_rgb(cor: Any) -> Rgb | None:
    """Cinza (1 componente), RGB (3) ou CMYK (4) → RGB em 0–1. Padrão ou indefinida → `None`."""
    if cor is None:
        return None
    if isinstance(cor, int | float):
        cor = (cor,)
    if not isinstance(cor, tuple | list) or not all(isinstance(v, int | float) for v in cor):
        return None
    v = [min(1.0, max(0.0, float(x))) for x in cor]
    if len(v) == 1:
        return (v[0], v[0], v[0])
    if len(v) == 3:
        return (v[0], v[1], v[2])
    if len(v) == 4:
        c, m, y, k = v
        return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    return None


def distancia_cor(a: Rgb, b: Rgb) -> float:
    return math.dist(a, b)


# --- classificação -------------------------------------------------------------------------------


def _centro(obj: Objeto) -> tuple[float, float]:
    return ((obj["x0"] + obj["x1"]) / 2, (obj["top"] + obj["bottom"]) / 2)


def _contem(caixa: Sequence[float], x: float, y: float) -> bool:
    x0, top, x1, bottom = caixa
    return x0 <= x <= x1 and top <= y <= bottom


def _area_visivel(pagina: Any) -> tuple[float, float, float, float]:
    mx0, mtop, mx1, mbottom = pagina.mediabox
    cx0, ctop, cx1, cbottom = pagina.cropbox
    return (max(mx0, cx0), max(mtop, ctop), min(mx1, cx1), min(mbottom, cbottom))


def tamanho_efetivo(obj: Objeto) -> float:
    """Altura da fonte em pontos pela matriz (vale para texto girado, onde `size` é a largura)."""
    valor = obj.get("tamanho_efetivo")
    return float(valor if valor is not None else obj.get("size") or 0)


def compressao(obj: Objeto) -> float:
    valor = obj.get("compressao_horizontal")
    return float(valor) if valor is not None else 1.0


AREA_ESCANEADA = 0.8


def pagina_escaneada(pagina: Any) -> bool:
    """Imagem cobrindo mais de 80 % da página e nenhum texto desenhado de verdade fora dela."""
    x0, top, x1, bottom = _area_visivel(pagina)
    area = max(1.0, (x1 - x0) * (bottom - top))
    imagens = [(i["x0"], i["top"], i["x1"], i["bottom"]) for i in pagina.images]
    coberta = sum(
        max(0.0, min(x1, b[2]) - max(x0, b[0])) * max(0.0, min(bottom, b[3]) - max(top, b[1]))
        for b in imagens
    )
    if coberta / area <= AREA_ESCANEADA:
        return False
    for c in pagina.chars:
        if c.get("modo_renderizacao", 0) in MODOS_INVISIVEIS or not c.get("text", "").strip():
            continue
        x, y = _centro(c)
        if not any(_contem(b, x, y) for b in imagens):
            return False
    return True


class _Classificador:
    def __init__(self, pagina: Any, desenho: PaginaRenderizada | None, escaneada: bool) -> None:
        self.area = _area_visivel(pagina)
        self.desenho = desenho
        self.escaneada = escaneada
        self._palavra_visivel: dict[int, bool] = {}
        self.fundos: list[tuple[tuple[float, float, float, float], Rgb]] = []
        for r in pagina.rects:
            cor = para_rgb(r.get("non_stroking_color"))
            if r.get("fill") and cor is not None:
                self.fundos.append(((r["x0"], r["top"], r["x1"], r["bottom"]), cor))
        self.imagens = [(i["x0"], i["top"], i["x1"], i["bottom"]) for i in pagina.images]

    def _sobre_imagem(self, x: float, y: float) -> bool:
        return any(_contem(caixa, x, y) for caixa in self.imagens)

    def _fundo(self, x: float, y: float) -> Rgb:
        for caixa, cor in reversed(self.fundos):
            if _contem(caixa, x, y):
                return cor
        return BRANCO

    def _sinal_de_cor(self, obj: Objeto, x: float, y: float) -> bool:
        cor = para_rgb(obj.get("non_stroking_color"))
        if cor is None or self._sobre_imagem(x, y):
            return False
        return distancia_cor(cor, self._fundo(x, y)) < LIMIAR_COR

    def motivo(self, obj: Objeto) -> MotivoOculto | None:
        x, y = _centro(obj)
        if not _contem(self.area, x, y):
            return "fora_da_pagina"
        if tamanho_efetivo(obj) < FONTE_MINIMA_PT:
            return "fonte_minuscula"
        if (
            compressao(obj) < COMPRESSAO_MINIMA
            or float(obj.get("espacamento_relativo") or 0.0) < ESPACAMENTO_MINIMO
        ):
            return "texto_comprimido"
        if obj.get("modo_renderizacao", 0) in MODOS_INVISIVEIS:
            return None if self.escaneada else "renderizacao_invisivel"
        if not obj.get("text", "").strip():
            return None  # espaço não deixa tinta; o agrupamento junta pelo vão
        sinal_de_cor = self._sinal_de_cor(obj, x, y)
        if self.desenho is None:
            return "cor_do_fundo" if sinal_de_cor else None
        if self.desenho.por_diferenca:
            if self._palavra_visivel.get(id(obj), True):
                return None
        else:
            contraste = self.desenho.contraste(obj["x0"], obj["top"], obj["x1"], obj["bottom"])
            if contraste >= CONTRASTE_MINIMO:
                return None
        return "cor_do_fundo" if sinal_de_cor else "invisivel_na_renderizacao"

    def preparar(self, chars: Sequence[Objeto]) -> None:
        """Decide a visibilidade por palavra (caracteres seguidos, sem espaço, na mesma linha),
        pela diferença entre o desenho com e sem texto."""
        self._palavra_visivel.clear()
        desenho = self.desenho
        if desenho is None or not desenho.por_diferenca:
            return
        palavra: list[Objeto] = []

        def fechar() -> None:
            if not palavra:
                return
            x0 = min(c["x0"] for c in palavra)
            x1 = max(c["x1"] for c in palavra)
            topo = min(c["top"] for c in palavra)
            base = max(c["bottom"] for c in palavra)
            so_pontuacao = not any(ch.isalnum() for c in palavra for ch in c.get("text", ""))
            visivel = (
                so_pontuacao
                or desenho.fracao_de_tinta(x0, topo, x1, base) >= FRACAO_MINIMA_DE_TINTA
            )
            for c in palavra:
                self._palavra_visivel[id(c)] = visivel
            palavra.clear()

        for c in chars:
            if not c.get("text", "").strip():
                fechar()
                continue
            if palavra:
                anterior = palavra[-1]
                tamanho = max(1.0, tamanho_efetivo(c))
                if c.get("upright", True) != anterior.get("upright", True):
                    mesma_linha = colado = False
                elif c.get("upright", True):
                    mesma_linha = abs(c["top"] - anterior["top"]) <= tamanho * 0.5
                    colado = abs(c["x0"] - anterior["x1"]) <= tamanho * 0.5
                else:  # girado: perto nas duas direções
                    xc, yc = _centro(c)
                    xa, ya = _centro(anterior)
                    mesma_linha = colado = math.hypot(xc - xa, yc - ya) <= tamanho * 1.5
                if not (mesma_linha and colado):
                    fechar()
            palavra.append(c)
        fechar()


# --- ordem de leitura ----------------------------------------------------------------------------


LINHAS_MINIMAS_POR_COLUNA = 4


def _calha_de_colunas(palavras: Sequence[Objeto], largura: float) -> tuple[float, float] | None:
    """Procura uma calha vertical (faixa sem palavra nenhuma) no meio da página que separe duas
    colunas com texto dos dois lados. Palavras que cruzam a calha só são aceitas no topo (o nome
    centralizado, por exemplo): devolve (x da calha, y abaixo do qual há colunas). Entre as
    posições válidas, ficam as que reconhecem o maior cabeçalho (o que atravessa a calha vai
    antes das colunas), e delas o meio da faixa contígua mais larga."""
    if len(palavras) < 12:
        return None
    validas: list[tuple[int, float, float]] = []
    for passo in range(25, 76):
        x = largura * passo / 100
        corte = _corte_se_coluna(palavras, x)
        if corte is not None:
            validas.append((passo, x, corte))
    if not validas:
        return None
    maior_corte = max(c for _, _, c in validas)
    validas = [v for v in validas if v[2] == maior_corte]
    faixas: list[list[tuple[int, float, float]]] = [[validas[0]]]
    for item in validas[1:]:
        if item[0] == faixas[-1][-1][0] + 1:
            faixas[-1].append(item)
        else:
            faixas.append([item])
    faixa = max(faixas, key=len)
    _, x, corte = faixa[len(faixa) // 2]
    return x, corte


def _corte_se_coluna(palavras: Sequence[Objeto], x: float) -> float | None:
    cruzam = [p for p in palavras if p["x0"] < x < p["x1"]]
    esquerda = [p for p in palavras if p["x1"] <= x]
    direita = [p for p in palavras if p["x0"] >= x]
    corte = max((p["bottom"] for p in cruzam), default=0.0)
    abaixo_esq = [p for p in esquerda if p["top"] >= corte]
    abaixo_dir = [p for p in direita if p["top"] >= corte]
    linhas_esq = {round(p["top"]) for p in abaixo_esq}
    linhas_dir = {round(p["top"]) for p in abaixo_dir}
    if min(len(linhas_esq), len(linhas_dir)) < LINHAS_MINIMAS_POR_COLUNA:
        return None
    if any(p["top"] < corte - 0.5 and p["bottom"] > corte + 0.5 for p in esquerda + direita):
        return None
    # As duas colunas precisam se sobrepor na vertical (senão é só texto alinhado à esquerda
    # seguido de texto à direita, que a ordem padrão já lê certo).
    topo = max(min(p["top"] for p in abaixo_esq), min(p["top"] for p in abaixo_dir))
    fundo = min(max(p["bottom"] for p in abaixo_esq), max(p["bottom"] for p in abaixo_dir))
    if fundo - topo < 0.3 * (max(p["bottom"] for p in palavras) - corte):
        return None
    # Uma calha de verdade tem folga: as palavras da esquerda terminam bem antes da direita.
    folga = min(p["x0"] for p in abaixo_dir) - max(p["x1"] for p in abaixo_esq)
    if folga < 12:
        return None
    # Tabela (data à esquerda, descrição à direita, na mesma linha) não é coluna: lá a maioria
    # das linhas da esquerda tem par na direita com a mesma altura. Em colunas, não.
    alinhadas = sum(1 for t in linhas_esq if {t - 1, t, t + 1} & linhas_dir)
    if alinhadas > 0.5 * len(linhas_esq):
        return None
    return corte


def _extrair(pagina: Any) -> str:
    texto: str = pagina.extract_text(x_tolerance=1.5, y_tolerance=3) or ""
    return texto


def _linhas_giradas(chars: Sequence[Objeto]) -> list[str]:
    """Texto girado (não "upright"): o pdfplumber o lê letra por letra, de trás para frente. Aqui
    os caracteres são agrupados pela linha de base (direção da matriz) e lidos ao longo dela."""
    grupos: dict[tuple[int, int], list[tuple[float, Objeto]]] = {}
    for c in chars:
        a, b = float(c["matrix"][0]), float(c["matrix"][1])
        norma = math.hypot(a, b) or 1.0
        a, b = a / norma, b / norma
        e, f = float(c["matrix"][4]), float(c["matrix"][5])
        ao_longo, através = a * e + b * f, -b * e + a * f
        tamanho = max(1.0, tamanho_efetivo(c))
        chave = (round(math.degrees(math.atan2(b, a))), round(através / (tamanho * 0.5)))
        grupos.setdefault(chave, []).append((ao_longo, c))
    linhas = []
    for chave in sorted(grupos, key=lambda k: (k[0], -k[1])):
        itens = sorted(grupos[chave], key=lambda item: item[0])
        partes: list[str] = []
        fim_anterior: float | None = None
        for posicao, c in itens:
            if fim_anterior is not None and posicao - fim_anterior > 0.25 * tamanho_efetivo(c):
                partes.append(" ")
            partes.append(c.get("text", ""))
            fim_anterior = posicao + float(c.get("adv") or 0)
        linha = " ".join("".join(partes).split())
        if linha:
            linhas.append(linha)
    return linhas


def _texto_em_ordem_de_leitura(pagina_visivel: Any) -> str:
    girados = [c for c in pagina_visivel.chars if not c.get("upright", True)]
    visivel = pagina_visivel.filter(
        lambda o: o.get("object_type") != "char" or o.get("upright", True)
    )
    texto = _texto_reto(visivel)
    if girados:
        texto = "\n".join(p for p in (texto, *_linhas_giradas(girados)) if p.strip())
    return texto


def _texto_reto(visivel: Any) -> str:
    palavras = visivel.extract_words(x_tolerance=1.5, y_tolerance=3)
    calha = _calha_de_colunas(palavras, float(visivel.width))
    if calha is None:
        return _extrair(visivel)
    x, corte = calha
    x0, top, x1, bottom = visivel.bbox
    partes = []
    if corte > top:
        partes.append(_extrair(visivel.within_bbox((x0, top, x1, min(bottom, corte + 0.5)))))
    corte = max(top, corte + 0.5)
    partes.append(_extrair(visivel.within_bbox((x0, corte, x, bottom))))
    partes.append(_extrair(visivel.within_bbox((x, corte, x1, bottom))))
    return "\n".join(p for p in partes if p.strip())


# --- leitura -------------------------------------------------------------------------------------


def _abrir(conteudo: bytes) -> Any:
    # As exceções do pdfminer podem carregar trechos do PDF: o erro público não as encadeia.
    try:
        return pdfplumber.open(io.BytesIO(conteudo))
    except Exception as exc:  # o pdfminer levanta de tudo um pouco para PDF malformado
        criptografado = _e_criptografia(exc)
    if criptografado:
        raise PdfCriptografado from None
    raise ArquivoCorrompido("pdf") from None


def _e_criptografia(exc: BaseException | None) -> bool:
    vistos = 0
    while exc is not None and vistos < 10:
        if isinstance(exc, PDFPasswordIncorrect | PDFEncryptionError):
            return True
        if any(isinstance(a, PDFPasswordIncorrect | PDFEncryptionError) for a in exc.args):
            return True
        exc = exc.__cause__ or exc.__context__
        vistos += 1
    return False


def _agrupar_ocultos(
    pagina: Any, numero: int, motivos: Iterable[MotivoOculto], motivo_de: Callable[[Objeto], Any]
) -> list[TrechoOculto]:
    trechos = []
    for motivo in motivos:
        filtrada = pagina.filter(
            lambda o, m=motivo: o.get("object_type") == "char" and motivo_de(o) == m
        )
        texto = " ".join((_extrair(filtrada)).split())
        if texto:
            trechos.append(TrechoOculto(texto=texto, motivo=motivo, pagina=numero))
    return trechos


def ler_pdf(conteudo: bytes, limites: Limites | None = None) -> DocumentoLido:
    limites = limites or Limites()
    pdf = _abrir(conteudo)
    try:
        renderizador: Renderizador | None = Renderizador(conteudo)
    except Exception:  # sem desenho, valem as heurísticas
        log.warning("ingestao.pdf.renderizacao_indisponivel", extra={"pagina": None})
        renderizador = None
    criptografado = False
    try:
        return _ler_paginas(pdf, limites, renderizador)
    except ErroIngestao:
        raise
    except Exception as exc:
        criptografado = _e_criptografia(exc)
    finally:
        pdf.close()
        if renderizador is not None:
            renderizador.fechar()
    if criptografado:
        raise PdfCriptografado from None
    raise ArquivoCorrompido("pdf") from None


ORDEM_DOS_MOTIVOS: tuple[MotivoOculto, ...] = (
    "fora_da_pagina",
    "fonte_minuscula",
    "texto_comprimido",
    "renderizacao_invisivel",
    "cor_do_fundo",
    "invisivel_na_renderizacao",
)


def _desenhar(
    renderizador: Renderizador | None, indice: int, pagina: Any
) -> PaginaRenderizada | None:
    if renderizador is None:
        return None
    try:
        x0, topo, _, _ = pagina.cropbox
        return renderizador.desenhar(indice, (float(x0), float(topo)))
    except Exception:  # o pdfium recusa alguns PDFs que o pdfminer lê: vale a heurística
        log.warning("ingestao.pdf.renderizacao_indisponivel", extra={"pagina": indice + 1})
        return None


def _ler_paginas(pdf: Any, limites: Limites, renderizador: Renderizador | None) -> DocumentoLido:
    paginas = pdf.pages
    total = len(paginas)
    if total > limites.paginas_max:
        raise MuitasPaginas(total, limites.paginas_max)

    textos: list[str] = []
    ocultos: list[TrechoOculto] = []
    imagens: list[ImagemEncontrada] = []
    sem_texto: list[int] = []
    caracteres = 0
    for numero, pagina in enumerate(paginas, start=1):
        inicio = time.perf_counter()
        chars = pagina.chars
        caracteres += len(chars)
        if caracteres > 1.2 * limites.texto_max_caracteres:
            raise TextoGrande(limites.texto_max_caracteres, arquivo=True)
        classificador = _Classificador(
            pagina, _desenhar(renderizador, numero - 1, pagina), pagina_escaneada(pagina)
        )
        classificador.preparar(chars)
        cache: dict[int, MotivoOculto | None] = {}

        def motivo_de(
            obj: Objeto, c: _Classificador = classificador, k: dict[int, Any] = cache
        ) -> Any:
            chave = id(obj)
            if chave not in k:
                k[chave] = c.motivo(obj) if obj.get("object_type") == "char" else None
            return k[chave]

        motivos_na_pagina = {m for m in (motivo_de(c) for c in chars) if m is not None}
        visivel = pagina.filter(lambda o, f=motivo_de: f(o) is None)
        textos.append(_texto_em_ordem_de_leitura(visivel))
        ocultos += _agrupar_ocultos(
            pagina, numero, [m for m in ORDEM_DOS_MOTIVOS if m in motivos_na_pagina], motivo_de
        )
        imagens += [
            ImagemEncontrada(
                pagina=numero,
                largura=round(float(i["x1"] - i["x0"]), 1),
                altura=round(float(i["bottom"] - i["top"]), 1),
            )
            for i in pagina.images
        ]
        visiveis = [c for c in chars if motivo_de(c) is None and c.get("text", "").strip()]
        if not visiveis and pagina.images:
            sem_texto.append(numero)
        pagina.flush_cache()
        if time.perf_counter() - inicio > limites.tempo_max_por_pagina_s:
            raise PdfPesado(numero, limites.tempo_max_por_pagina_s)

    textos = remover_cabecalhos_e_rodapes([juntar_hifens_de_quebra(t) for t in textos])
    texto = normalizar_texto("\n\n".join(t for t in textos if t.strip()))
    if len(texto) > limites.texto_max_caracteres:
        raise TextoGrande(limites.texto_max_caracteres, arquivo=True)
    return DocumentoLido(
        origem="pdf",
        texto=texto,
        ocultos=tuple(ocultos),
        imagens=tuple(imagens),
        paginas=total,
        paginas_sem_texto=tuple(sem_texto),
        campos_de_formulario=_campos_preenchidos(pdf),
    )


def _campos_preenchidos(pdf: Any) -> int:
    """Quantos campos de formulário (AcroForm) têm valor: o texto deles não é lido (ADR 0004)."""
    try:
        anotacoes = [a for p in pdf.pages for a in (p.annots or [])]
    except Exception:
        return 0
    total = 0
    for a in anotacoes:
        dados = a.get("data") or {}
        if str(dados.get("FT", "")).strip("/'\" ") in {"Tx", "Ch"} and dados.get("V"):
            total += 1
    return total
