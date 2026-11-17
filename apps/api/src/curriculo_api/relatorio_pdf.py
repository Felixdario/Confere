"""Relatório da análise em PDF, gerado no servidor com reportlab (ADR 0007).

Sem dados pessoais: leva a nota, a decomposição, a tabela requisito × evidência (com os trechos do
texto **anonimizado**), lacunas, reescritas, palavras-chave e "o que aprender". Não leva a lista do
que foi removido (nem mascarada), os trechos dos alertas nem o arquivo original; os metadados do
PDF (autor, título, assunto) são genéricos.
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from xml.sax.saxutils import escape

from curriculo_api.api.esquemas import AnaliseDetalhe

FONTE = "Vera"
FONTE_NEGRITO = "VeraBd"
STATUS = {"atende": "atende", "parcial": "parcial", "nao_atende": "não atende"}
AVISOS = {
    "texto_oculto": "Texto oculto no arquivo (ignorado na análise)",
    "instrucao_para_ia": "Frase com cara de instrução para a IA (tratada como dado)",
    "pdf_sem_texto": "Página sem texto selecionável",
    "comentario_nao_lido": "Comentários do DOCX não lidos",
    "formulario_nao_lido": "Campos de formulário do PDF não lidos",
    "nome_nao_identificado": "Nome não identificado no topo",
    "calculo": "Aviso do cálculo",
}


def _registrar_fontes() -> None:
    import reportlab
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    pasta = Path(os.path.dirname(reportlab.__file__)) / "fonts"
    registradas = pdfmetrics.getRegisteredFontNames()
    for nome, arquivo in ((FONTE, "Vera.ttf"), (FONTE_NEGRITO, "VeraBd.ttf")):
        if nome not in registradas:
            pdfmetrics.registerFont(TTFont(nome, str(pasta / arquivo)))


def _t(texto: object) -> str:
    # A Vera não tem a seta; o resto do texto em pt-BR ela cobre.
    return escape(str(texto)).replace("→", "=")


def gerar_relatorio(analise: AnaliseDetalhe) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        Flowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    _registrar_fontes()
    base = ParagraphStyle("base", fontName=FONTE, fontSize=9.5, leading=13)
    pequeno = ParagraphStyle("pequeno", parent=base, fontSize=8, leading=10.5)
    titulo = ParagraphStyle("titulo", parent=base, fontName=FONTE_NEGRITO, fontSize=16, leading=20)
    secao = ParagraphStyle(
        "secao", parent=base, fontName=FONTE_NEGRITO, fontSize=11.5, leading=15, spaceBefore=10
    )

    saida = io.BytesIO()
    doc = SimpleDocTemplate(
        saida,
        pagesize=A4,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        topMargin=1.6 * cm,
        bottomMargin=1.6 * cm,
        title="Relatório de aderência",
        author="Analisador de currículos",
        subject="Análise de aderência a uma vaga",
        creator="curriculo-api",
        invariant=1,
    )
    partes: list[Flowable] = [Paragraph("Relatório de aderência", titulo)]
    partes.append(Paragraph(_t(f"Vaga: {analise.vaga.titulo}"), base))
    if analise.aviso_modo:
        partes.append(Paragraph(_t(analise.aviso_modo), pequeno))
    partes.append(Spacer(1, 8))

    if analise.status != "concluida" or analise.nota is None:
        partes.append(Paragraph(_t(f"A análise está com status “{analise.status}”."), base))
    else:
        partes.append(Paragraph(_t(f"Nota: {analise.nota} de 100"), secao))
        if analise.decomposicao is not None:
            partes.append(Paragraph(_t(analise.decomposicao.texto), base))
            for parcela in analise.decomposicao.parcelas:
                partes.append(Paragraph(_t("• " + parcela.resumo), pequeno))

        partes.append(Paragraph("Requisitos e evidências", secao))
        linhas = [
            [
                Paragraph("<b>Requisito</b>", pequeno),
                Paragraph("<b>Tipo</b>", pequeno),
                Paragraph("<b>Situação</b>", pequeno),
                Paragraph("<b>Evidência no currículo</b>", pequeno),
            ]
        ]
        for r in analise.requisitos:
            linhas.append(
                [
                    Paragraph(_t(r.descricao), pequeno),
                    Paragraph("obrigatório" if r.tipo == "obrigatorio" else "desejável", pequeno),
                    Paragraph(_t(STATUS[r.status]), pequeno),
                    Paragraph(_t(r.evidencia or r.motivo), pequeno),
                ]
            )
        tabela = Table(linhas, colWidths=[5 * cm, 2.2 * cm, 2.2 * cm, 8 * cm], repeatRows=1)
        tabela.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BBBBBB")),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEEEEE")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        partes.append(tabela)

        if analise.resumo:
            partes.append(Paragraph("Resumo", secao))
            partes.append(Paragraph(_t(analise.resumo), base))
        if analise.lacunas:
            partes.append(Paragraph("Lacunas", secao))
            for lacuna in analise.lacunas:
                partes.append(Paragraph(_t(f"• {lacuna.requisito}: {lacuna.comentario}"), base))
        if analise.reescritas:
            partes.append(Paragraph("Sugestões de reescrita", secao))
            for reescrita in analise.reescritas:
                partes.append(Paragraph(_t(f"Antes: {reescrita.antes}"), pequeno))
                partes.append(Paragraph(_t(f"Depois: {reescrita.depois}"), base))
                partes.append(Spacer(1, 4))
        if analise.palavras_chave:
            partes.append(Paragraph("Palavras-chave da vaga", secao))
            texto = ", ".join(
                p.termo + ("" if p.no_curriculo else " (ausente)") for p in analise.palavras_chave
            )
            partes.append(Paragraph(_t(texto), base))
        if analise.o_que_aprender:
            partes.append(Paragraph("O que aprender", secao))
            for item in analise.o_que_aprender:
                partes.append(Paragraph(_t(f"• {item.competencia}: {item.sugestao}"), base))
    tipos = sorted({a.tipo for a in analise.avisos})
    if tipos:
        partes.append(Paragraph("Avisos", secao))
        for tipo in tipos:
            partes.append(Paragraph(_t("• " + AVISOS.get(tipo, tipo)), pequeno))
    partes.append(Spacer(1, 10))
    partes.append(
        Paragraph(
            "A nota é calculada em código a partir da tabela acima; dados pessoais foram "
            "removidos antes da análise e não aparecem neste relatório.",
            pequeno,
        )
    )
    doc.build(partes)
    return saida.getvalue()
