"""Gera os arquivos reais (PDF e DOCX) de alguns casos das evals a partir do `curriculo.md`.

Uso, de `apps/api` (é o que `make fixtures` chama):
    uv run python -m curriculo_api.evals.fixtures             # (re)escreve os arquivos
    uv run python -m curriculo_api.evals.fixtures --verificar # confere; sai 1 se desatualizados

Os binários ficam versionados em `evals/casos/<id>/curriculo.{pdf,docx}` (poucos KB cada): as evals
e os testes não dependem do reportlab, que é só de desenvolvimento. A verificação é semântica
(o arquivo versionado e um recém-gerado dão o mesmo texto visível e os mesmos trechos ocultos),
porque bytes de PDF e de zip podem variar entre versões do zlib.

O trecho entre `<!-- oculto -->` e `<!-- /oculto -->` vira texto oculto de verdade, de três jeitos:
- `branco`: texto branco sobre o papel branco, em linhas próprias;
- `minusculo`: fonte de 1 pt, na mesma linha do texto visível;
- `fora`: fora da área da página (à direita da borda).
Cada pedaço do trecho oculto pode usar um jeito (o i06 usa 1 pt e fora da página).

As funções `pdf_de_linhas` e `docx_de_paragrafos` também servem aos testes da ingestão.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from curriculo_api.evals.dataset import MARCADOR_OCULTO, Dataset, carregar_dataset, localizar_raiz

ModoOculto = Literal["branco", "minusculo", "fora"]

LARGURA_A4, ALTURA_A4 = 595.2756, 841.8898
MARGEM = 50.0
FONTE = "Vera"
FONTE_NEGRITO = "VeraBd"
DATA_FIXA = (2026, 11, 1, 0, 0, 0)


@dataclass(frozen=True)
class Fixture:
    caso: str
    formato: Literal["pdf", "docx"]
    modos_ocultos: tuple[ModoOculto, ...] = ()
    """Um modo por pedaço do trecho oculto (o trecho é dividido em partes iguais por palavras)."""


FIXTURES: tuple[Fixture, ...] = (
    Fixture("b16-administrativo-sem-desejaveis", "docx"),
    Fixture("b13-ml-senior-en", "pdf"),
    Fixture("b14-java-para-front-end", "pdf"),
    Fixture("i05-oculta-en-instrucao", "pdf", ("branco",)),
    Fixture("i06-oculta-palavras-chave", "pdf", ("minusculo", "fora")),
)


# --- PDF -----------------------------------------------------------------------------------------


@dataclass
class Trecho:
    """Um pedaço de linha a desenhar."""

    texto: str
    tamanho: float = 10.0
    negrito: bool = False
    cor: tuple[float, float, float] = (0.0, 0.0, 0.0)
    modo_oculto: ModoOculto | None = None
    modo_renderizacao: Literal[0, 1, 2, 3, 4, 5, 6, 7] = 0


@dataclass
class Linha:
    trechos: list[Trecho] = field(default_factory=list)
    espaco_antes: float = 0.0
    x: float | None = None
    y: float | None = None


def _registrar_fontes() -> None:
    import reportlab
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    pasta = Path(os.path.dirname(reportlab.__file__)) / "fonts"
    registradas = pdfmetrics.getRegisteredFontNames()
    for nome, arquivo in ((FONTE, "Vera.ttf"), (FONTE_NEGRITO, "VeraBd.ttf")):
        if nome not in registradas:
            pdfmetrics.registerFont(TTFont(nome, str(pasta / arquivo)))


def pdf_de_linhas(
    paginas: Sequence[Sequence[Linha]],
    *,
    tamanho_pagina: tuple[float, float] = (LARGURA_A4, ALTURA_A4),
    caixa_de_corte: tuple[float, float, float, float] | None = None,
    imagens: Sequence[tuple[int, float, float, float, float]] = (),
    retangulos: Sequence[tuple[int, float, float, float, float, tuple[float, float, float]]] = (),
    criptografar: str | None = None,
) -> bytes:
    """Desenha páginas de linhas com reportlab, de forma determinística (`invariant`).

    Linha larga demais tem a fonte reduzida até caber (mínimo 6 pt), para que nenhuma linha do
    Markdown seja quebrada (a ancoragem literal da fase 1 não junta linhas). `imagens` são
    retângulos cinza desenhados como imagem: (página, x, y, largura, altura); `retangulos` são
    retângulos preenchidos desenhados antes do texto: (página, x, y, largura, altura, cor RGB).
    A primeira linha de 10 pt fica com a linha de base em y ≈ 782 (A4).
    """
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfgen import canvas

    _registrar_fontes()
    saida = io.BytesIO()
    argumentos: dict[str, Any] = {"pagesize": tamanho_pagina, "invariant": 1}
    if criptografar is not None:
        from reportlab.lib.pdfencrypt import StandardEncryption

        argumentos["encrypt"] = StandardEncryption(criptografar, canPrint=0)
    tela = canvas.Canvas(saida, **argumentos)
    largura, altura = tamanho_pagina
    util = largura - 2 * MARGEM
    for numero, linhas in enumerate(paginas, start=1):
        if caixa_de_corte is not None:
            tela.setCropBox(caixa_de_corte)
        for pagina_img, x, y, w, h in imagens:
            if pagina_img == numero:
                tela.drawImage(ImageReader(_png_cinza()), x, y, w, h)
        for pagina_ret, x, y, w, h, cor in retangulos:
            if pagina_ret == numero:
                tela.setFillColorRGB(*cor)
                tela.rect(x, y, w, h, stroke=0, fill=1)
        y = altura - MARGEM
        for linha in linhas:
            y -= linha.espaco_antes
            visiveis = [t for t in linha.trechos if t.modo_oculto is None]
            largura_visivel = sum(
                pdfmetrics.stringWidth(t.texto, FONTE_NEGRITO if t.negrito else FONTE, t.tamanho)
                for t in visiveis
            )
            escala = min(1.0, util / largura_visivel) if largura_visivel else 1.0
            maior = max((t.tamanho for t in visiveis), default=10.0) * escala
            y_linha = linha.y if linha.y is not None else y - maior
            x = linha.x if linha.x is not None else MARGEM
            for t in linha.trechos:
                fonte = FONTE_NEGRITO if t.negrito else FONTE
                encolher = t.modo_oculto is None and escala < 1
                tamanho = max(6.0, t.tamanho * escala) if encolher else t.tamanho
                x_trecho = largura + 40 if t.modo_oculto == "fora" else x
                objeto = tela.beginText(x_trecho, y_linha)
                objeto.setFont(fonte, tamanho)
                objeto.setFillColorRGB(*t.cor)
                if t.modo_renderizacao:
                    objeto.setTextRenderMode(t.modo_renderizacao)
                objeto.textOut(t.texto)
                tela.drawText(objeto)
                if t.modo_oculto != "fora":
                    x += pdfmetrics.stringWidth(t.texto, fonte, tamanho)
            y = y_linha - maior * 0.35
        tela.showPage()
    tela.save()
    return saida.getvalue()


def _png_cinza() -> io.BytesIO:
    """Um PNG 2×2 cinza, escrito à mão (sem Pillow)."""
    import struct
    import zlib

    def bloco(tipo: bytes, dados: bytes) -> bytes:
        return (
            struct.pack(">I", len(dados))
            + tipo
            + dados
            + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF)
        )

    cru = b"".join(b"\x00" + b"\x80\x80\x80" * 2 for _ in range(2))
    png = (
        b"\x89PNG\r\n\x1a\n"
        + bloco(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
        + bloco(b"IDAT", zlib.compress(cru))
        + bloco(b"IEND", b"")
    )
    return io.BytesIO(png)


def _dividir(texto: str, partes: int) -> list[str]:
    palavras = texto.split()
    tamanho = -(-len(palavras) // partes)
    return [" ".join(palavras[i : i + tamanho]) for i in range(0, len(palavras), tamanho)]


def _quebrar(texto: str, tamanho: float, util: float) -> list[str]:
    from reportlab.pdfbase import pdfmetrics

    linhas: list[str] = []
    atual = ""
    for palavra in texto.split():
        candidato = f"{atual} {palavra}".strip()
        if pdfmetrics.stringWidth(candidato, FONTE, tamanho) > util and atual:
            linhas.append(atual)
            atual = palavra
        else:
            atual = candidato
    if atual:
        linhas.append(atual)
    return linhas


def linhas_de_markdown(md: str, modos: Sequence[ModoOculto] = ()) -> list[list[Linha]]:
    """Converte o Markdown do caso em linhas: `#` vira o nome em negrito, `##` o título da seção,
    `- ` vira marcador "•". O trecho oculto é desenhado conforme `modos`."""
    _registrar_fontes()
    linhas: list[Linha] = []
    espaco = 0.0
    for bruta in md.split("\n"):
        if not bruta.strip():
            espaco += 6.0
            continue
        if bruta.startswith("## "):
            linhas.append(Linha([Trecho(bruta[3:], 12.5, negrito=True)], espaco_antes=espaco + 4))
        elif bruta.startswith("# "):
            linhas.append(Linha([Trecho(bruta[2:], 17.0, negrito=True)], espaco_antes=espaco))
        else:
            texto = "• " + bruta[2:] if bruta.startswith("- ") else bruta
            oculto = MARCADOR_OCULTO.search(texto)
            if oculto is None:
                linhas.append(Linha([Trecho(texto)], espaco_antes=espaco))
            else:
                antes, depois = texto[: oculto.start()], texto[oculto.end() :]
                pedacos = _dividir(oculto.group(1), len(modos) or 1)
                linha = Linha([Trecho(antes)] if antes.strip() else [], espaco_antes=espaco)
                extras: list[Linha] = []
                for pedaco, modo in zip(pedacos, modos or ("branco",), strict=False):
                    if modo == "branco":
                        util = LARGURA_A4 - 2 * MARGEM
                        extras += [
                            Linha([Trecho(t, cor=(1.0, 1.0, 1.0), modo_oculto="branco")])
                            for t in _quebrar(pedaco, 10.0, util)
                        ]
                    elif modo == "minusculo":
                        linha.trechos.append(Trecho(" " + pedaco, 1.0, modo_oculto="minusculo"))
                    else:
                        linha.trechos.append(Trecho(pedaco, modo_oculto="fora"))
                if depois.strip():
                    linha.trechos.append(Trecho(depois))
                linhas.append(linha)
                linhas += extras
        espaco = 0.0
    # Pagina a cada ~50 linhas (os casos cabem numa página; a regra existe para os testes).
    return [linhas[i : i + 50] for i in range(0, len(linhas), 50)] or [[]]


def pdf_de_markdown(md: str, modos: Sequence[ModoOculto] = ()) -> bytes:
    return pdf_de_linhas(linhas_de_markdown(md, modos))


# --- DOCX ----------------------------------------------------------------------------------------


@dataclass
class Paragrafo:
    texto: str
    estilo: str | None = None
    oculto: Literal["vanish", "branco", "minusculo"] | None = None
    """Formatação do parágrafo inteiro."""
    runs: Sequence[tuple[str, Literal["vanish", "branco", "minusculo"] | None]] = ()
    """Se preenchido, substitui `texto`: pedaços com formatação própria."""


def _formatar_run(run: Any, oculto: str | None) -> None:
    from docx.shared import Pt, RGBColor

    if oculto == "vanish":
        run.font.hidden = True
    elif oculto == "branco":
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    elif oculto == "minusculo":
        run.font.size = Pt(1)


def docx_de_paragrafos(
    corpo: Sequence[Paragrafo],
    *,
    cabecalho: Sequence[str] = (),
    rodape: Sequence[str] = (),
    tabela: Sequence[Sequence[str]] = (),
) -> bytes:
    """DOCX determinístico (datas fixas no zip e nas propriedades)."""
    import datetime as dt

    import docx

    documento = docx.Document()
    propriedades = documento.core_properties
    momento = dt.datetime(*DATA_FIXA)
    propriedades.created = propriedades.modified = propriedades.last_printed = momento
    propriedades.author = propriedades.last_modified_by = "evals"
    propriedades.revision = 1
    secao = documento.sections[0]
    if cabecalho:
        secao.header.paragraphs[0].text = cabecalho[0]
        for texto in cabecalho[1:]:
            secao.header.add_paragraph(texto)
    if rodape:
        secao.footer.paragraphs[0].text = rodape[0]
        for texto in rodape[1:]:
            secao.footer.add_paragraph(texto)
    for p in corpo:
        paragrafo = documento.add_paragraph(style=p.estilo)
        for texto, oculto in p.runs or ((p.texto, p.oculto),):
            _formatar_run(paragrafo.add_run(texto), oculto)
    if tabela:
        grade = documento.add_table(rows=len(tabela), cols=max(len(r) for r in tabela))
        for i, linha in enumerate(tabela):
            for j, texto in enumerate(linha):
                grade.cell(i, j).text = texto
    bruto = io.BytesIO()
    documento.save(bruto)
    return _zip_deterministico(bruto.getvalue())


def _zip_deterministico(conteudo: bytes) -> bytes:
    entrada = zipfile.ZipFile(io.BytesIO(conteudo))
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as destino:
        for info in entrada.infolist():
            nova = zipfile.ZipInfo(info.filename, date_time=DATA_FIXA)
            nova.compress_type = zipfile.ZIP_DEFLATED
            nova.external_attr = 0o600 << 16
            destino.writestr(nova, entrada.read(info.filename))
    return saida.getvalue()


def docx_de_markdown(md: str) -> bytes:
    """O cabeçalho de contato (antes da primeira seção) vai para o cabeçalho do Word; `##` vira
    "Heading 2", `- ` vira "List Bullet" e o resto, parágrafo comum."""
    indice = md.find("\n## ")
    topo, resto = (md[:indice], md[indice + 1 :]) if indice >= 0 else ("", md)
    cabecalho = [linha.removeprefix("# ") for linha in topo.split("\n") if linha.strip()]
    corpo: list[Paragrafo] = []
    for linha in resto.split("\n"):
        if not linha.strip():
            continue
        if linha.startswith("## "):
            corpo.append(Paragrafo(linha[3:], "Heading 2"))
        elif linha.startswith("- "):
            corpo.append(Paragrafo(linha[2:], "List Bullet"))
        else:
            corpo.append(Paragrafo(linha))
    return docx_de_paragrafos(corpo, cabecalho=cabecalho)


# --- CLI -----------------------------------------------------------------------------------------


def caminho(raiz: Path, fixture: Fixture) -> Path:
    return raiz / "evals" / "casos" / fixture.caso / f"curriculo.{fixture.formato}"


def gerar(dataset: Dataset, fixture: Fixture) -> bytes:
    md = dataset.por_id()[fixture.caso].curriculo
    if fixture.formato == "docx":
        return docx_de_markdown(md)
    return pdf_de_markdown(md, fixture.modos_ocultos)


def _assinatura(conteudo: bytes) -> tuple[str, tuple[tuple[str, str, int | None], ...]]:
    from curriculo_api.ingestao import ler_arquivo

    documento = ler_arquivo(conteudo)
    return documento.texto, tuple((o.texto, o.motivo, o.pagina) for o in documento.ocultos)


def desatualizadas(raiz: Path) -> list[str]:
    dataset = carregar_dataset(raiz / "evals")
    problemas: list[str] = []
    esperados = {caminho(raiz, f) for f in FIXTURES}
    for fixture in FIXTURES:
        arquivo = caminho(raiz, fixture)
        if not arquivo.is_file():
            problemas.append(f"{fixture.caso}: falta {arquivo.name}")
        elif _assinatura(arquivo.read_bytes()) != _assinatura(gerar(dataset, fixture)):
            problemas.append(f"{fixture.caso}: {arquivo.name} difere do gerado")
    for extra in sorted((raiz / "evals" / "casos").glob("*/curriculo.*")):
        if extra.suffix in {".pdf", ".docx"} and extra not in esperados:
            problemas.append(f"{extra.parent.name}: {extra.name} sem entrada em FIXTURES")
    return problemas


def escrever_todas(raiz: Path) -> int:
    dataset = carregar_dataset(raiz / "evals")
    for fixture in FIXTURES:
        caminho(raiz, fixture).write_bytes(gerar(dataset, fixture))
    return len(FIXTURES)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--verificar", action="store_true", help="só confere, não escreve")
    parser.add_argument("--raiz", type=Path, default=None, help="raiz do repositório")
    args = parser.parse_args(argv)
    raiz: Path = args.raiz or localizar_raiz()
    if args.verificar:
        problemas = desatualizadas(raiz)
        for problema in problemas:
            print(f"desatualizado: {problema}")
        return 1 if problemas else 0
    total = escrever_todas(raiz)
    print(f"{total} arquivos escritos em evals/casos/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
