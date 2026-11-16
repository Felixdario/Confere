"""Verificação de texto oculto por renderização (pypdfium2), com diferença de desenhos.

As heurísticas por caractere (cor x retângulo de fundo, tamanho, modo de renderização) não veem o
que é desenhado por cima, curvas de fundo, opacidade, recorte (clipping) ou contorno branco. Por
isso a decisão principal é olhar a página desenhada, e de um jeito que resista a adulteração do
fundo: a página é desenhada **duas vezes**, uma normal e outra **sem os objetos de texto**, e o
texto só é visível onde os dois desenhos diferem. Uma linha preta cruzando texto branco, listras,
gradiente ou um padrão da mesma cor do texto aparecem iguais nos dois desenhos e não contam como
tinta do texto (rodada 2 da fase 2).

A decisão é por **palavra** (caracteres seguidos, sem espaço, na mesma linha), porque a caixa de um
ponto ou de um hífen tem pouca tinta: a palavra é visível se a fração de pixels da caixa dela que
mudou de cor (distância RGB ≥ `DIFERENCA_DE_PIXEL`) passa de `FRACAO_MINIMA_DE_TINTA`.

Quando há texto dentro de form XObjects (que não dá para tirar sem reescrever o conteúdo), a
página volta para a medida antiga: contraste WCAG dentro da caixa do caractere.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

ESCALA = 2.0
"""144 dpi: um caractere de 4,5 pt tem ~9 px de altura."""
DIFERENCA_DE_PIXEL = 0.3
"""Distância RGB (0–1; o máximo é √3) a partir da qual um pixel "mudou" com o texto. Cinza #D6D6D6
sobre branco dá 0,28 (ilegível, oculto); #BFBFBF dá 0,44; branco sobre amarelo, 0,82 (visível)."""
FRACAO_MINIMA_DE_TINTA = 0.10
"""Fração dos pixels da caixa da palavra que precisa mudar. Medido: texto preto, cinza #999999 ou
#BBBBBB, de 4,5 a 12 pt, e branco sobre amarelo mudam 17–43 % da caixa; texto branco sobre listras
finas muda ~6 % e cruzando uma linha preta, ~4 %. Palavras só de pontuação (".", "-") têm pouca
tinta por natureza e não são julgadas."""
CONTRASTE_MINIMO = 1.5
"""Medida antiga (só para páginas com texto em form XObject): razão WCAG dentro da caixa."""

Imagem = npt.NDArray[np.float32]


def _linear(v: Imagem) -> Imagem:
    """sRGB (0–1) → luminância relativa."""
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4).astype(np.float32)


@dataclass
class PaginaRenderizada:
    com_texto: Imagem
    sem_texto: Imagem | None
    origem_x: float
    origem_topo: float

    @property
    def por_diferenca(self) -> bool:
        return self.sem_texto is not None

    def _janela(self, x0: float, topo: float, x1: float, base: float) -> tuple[slice, slice]:
        altura, largura = self.com_texto.shape[:2]
        px0 = max(0, math.floor((x0 - self.origem_x) * ESCALA))
        px1 = min(largura, math.ceil((x1 - self.origem_x) * ESCALA))
        py0 = max(0, math.floor((topo - self.origem_topo) * ESCALA))
        py1 = min(altura, math.ceil((base - self.origem_topo) * ESCALA))
        if px1 <= px0:
            px1 = min(largura, px0 + 1)
        if py1 <= py0:
            py1 = min(altura, py0 + 1)
        return slice(py0, py1), slice(px0, px1)

    def fracao_de_tinta(self, x0: float, topo: float, x1: float, base: float) -> float:
        """Fração dos pixels da caixa que mudam entre o desenho com e sem texto."""
        if self.sem_texto is None:
            raise ValueError("página sem o desenho sem texto")
        linhas, colunas = self._janela(x0, topo, x1, base)
        com = self.com_texto[linhas, colunas]
        sem = self.sem_texto[linhas, colunas]
        if com.size == 0:
            return 0.0
        distancia = np.sqrt(((com - sem) ** 2).sum(axis=-1))
        return float((distancia >= DIFERENCA_DE_PIXEL).mean())

    def contraste(self, x0: float, topo: float, x1: float, base: float) -> float:
        """Razão de contraste WCAG entre o pixel mais claro e o mais escuro da caixa."""
        linhas, colunas = self._janela(x0, topo, x1, base)
        regiao = self.com_texto[linhas, colunas]
        if regiao.size == 0:
            return 1.0
        luminancia = _linear(regiao) @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
        return float((luminancia.max() + 0.05) / (luminancia.min() + 0.05))


def _desenho(pagina: Any) -> Imagem:
    imagem = pagina.render(
        scale=ESCALA, draw_annots=False, may_draw_forms=False, rev_byteorder=True
    )
    matriz: npt.NDArray[np.uint8] = np.asarray(imagem.to_numpy())[..., :3]
    saida: Imagem = matriz.astype(np.float32) / np.float32(255.0)
    return saida


class Renderizador:
    """Abre o PDF no pdfium e desenha página a página, com a rotação da página aplicada (é o
    mesmo espaço de coordenadas que o pdfplumber usa para página com `/Rotate`)."""

    def __init__(self, conteudo: bytes) -> None:
        self._conteudo = conteudo
        self._documento: Any = pdfium.PdfDocument(conteudo)

    def desenhar(self, indice: int, origem: tuple[float, float]) -> PaginaRenderizada:
        pagina = self._documento[indice]
        alterou = False
        try:
            com_texto = _desenho(pagina)
            filtro = [pdfium_c.FPDF_PAGEOBJ_TEXT]
            no_topo = list(pagina.get_objects(filter=filtro, max_depth=1))
            em_qualquer_nivel = sum(1 for _ in pagina.get_objects(filter=filtro, max_depth=8))
            sem_texto: Imagem | None = None
            if em_qualquer_nivel == len(no_topo):
                for objeto in no_topo:
                    pagina.remove_obj(objeto)
                alterou = bool(no_topo)
                sem_texto = _desenho(pagina) if alterou else com_texto
        finally:
            pagina.close()
        if alterou:
            # A página foi alterada em memória: reabre o documento para não afetar outra leitura.
            self._documento.close()
            self._documento = pdfium.PdfDocument(self._conteudo)
        return PaginaRenderizada(
            com_texto=com_texto, sem_texto=sem_texto, origem_x=origem[0], origem_topo=origem[1]
        )

    def fechar(self) -> None:
        self._documento.close()
