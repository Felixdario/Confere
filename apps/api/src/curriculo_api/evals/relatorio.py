"""Gera `docs/evals.md` a partir de uma execução e da anterior do mesmo provedor (ADR 0005)."""

from __future__ import annotations

from collections.abc import Sequence

from curriculo_api.evals.harness import DetalheCaso, Execucao, ResultadoMetrica, Unidade


def _virgula(texto: str) -> str:
    return texto.replace(".", ",")


def formatar_valor(valor: float | None, unidade: Unidade) -> str:
    if valor is None:
        return "—"
    match unidade:
        case "proporcao":
            return _virgula(f"{valor * 100:.1f}") + " %"
        case "razao":
            return _virgula(f"{valor:.2f}")
        case "pontos" | "contagem":
            return f"{valor:.0f}"
        case "usd":
            return "US$ " + _virgula(f"{valor:.4f}")
        case "segundos":
            return _virgula(f"{valor:.1f}") + " s"


def formatar_delta(atual: float | None, anterior: float | None, unidade: Unidade) -> str:
    if atual is None or anterior is None:
        return "—"
    delta = atual - anterior
    match unidade:
        case "proporcao":
            return _virgula(f"{delta * 100:+.1f}") + " pp"
        case "razao":
            return _virgula(f"{delta:+.2f}")
        case "pontos" | "contagem":
            return f"{delta:+.0f}"
        case "usd":
            return _virgula(f"{delta:+.4f}")
        case "segundos":
            return _virgula(f"{delta:+.1f}") + " s"


def situacao_texto(metrica: ResultadoMetrica | None) -> str:
    if metrica is None:
        return "—"
    match metrica.situacao:
        case "passou":
            return "sim"
        case "falhou":
            return "**não**"
        case "pendente":
            return f"pendente (fase {metrica.fase_pendente})"
        case "n/a":
            return "n/a (falso)"


def _lista(itens: Sequence[str]) -> str:
    return ", ".join(itens) if itens else "—"


def _tabela_metricas(execucao: Execucao, anterior: Execucao | None) -> list[str]:
    antes = {m.chave: m for m in anterior.metricas} if anterior else {}
    linhas = [
        "| # | Métrica | Meta | Atual | Anterior | Δ | Passou? |",
        "| - | - | - | - | - | - | - |",
    ]
    for m in execucao.metricas:
        a = antes.get(m.chave)
        atual = formatar_valor(m.valor, m.unidade) if m.valor is not None else situacao_texto(m)
        if a is None:
            texto_anterior = "—"
        elif a.valor is not None:
            texto_anterior = formatar_valor(a.valor, a.unidade)
        else:
            texto_anterior = situacao_texto(a)
        delta = formatar_delta(m.valor, a.valor if a else None, m.unidade)
        linhas.append(
            f"| {m.numero} | {m.nome} | {m.meta} | {atual} | {texto_anterior} | {delta} "
            f"| {situacao_texto(m)} |"
        )
    return linhas


def _mudancas(execucao: Execucao, anterior: Execucao | None) -> list[str]:
    if anterior is None:
        return ["Primeira execução deste provedor: nada a comparar."]
    linhas: list[str] = []
    antes_m = {m.chave: m for m in anterior.metricas}
    mudaram = [
        f"{m.numero} ({antes_m[m.chave].situacao} → {m.situacao})"
        for m in execucao.metricas
        if m.chave in antes_m and antes_m[m.chave].situacao != m.situacao
    ]
    linhas.append("- Métricas que mudaram de situação: " + _lista(mudaram) + ".")

    antes_c = {c.id: c for c in anterior.casos}
    faixa: list[str] = []
    competencias: list[str] = []
    for caso in execucao.casos:
        velho = antes_c.get(caso.id)
        if velho is None:
            competencias.append(f"  - `{caso.id}`: caso novo")
            continue
        if None not in (caso.na_faixa, velho.na_faixa) and caso.na_faixa != velho.na_faixa:
            estado = "entrou na" if caso.na_faixa else "saiu da"
            faixa.append(f"`{caso.id}` {estado} faixa ({velho.nota} → {caso.nota})")
        entraram = sorted(set(caso.competencias_extraidas) - set(velho.competencias_extraidas))
        sairam = sorted(set(velho.competencias_extraidas) - set(caso.competencias_extraidas))
        if entraram or sairam:
            competencias.append(
                f"  - `{caso.id}`: entraram {_lista(entraram)}; saíram {_lista(sairam)}"
            )
    removidos = sorted(set(antes_c) - {c.id for c in execucao.casos})
    competencias += [f"  - `{caso_id}`: caso removido" for caso_id in removidos]

    if any(c.nota is not None for c in execucao.casos):
        linhas.append("- Pares que mudaram de faixa: " + _lista(faixa) + ".")
    else:
        linhas.append("- Pares que mudaram de faixa: pendente (o pipeline ainda não dá nota).")
    if competencias:
        linhas.append("- Competências extraídas que entraram ou saíram:")
        linhas += competencias
    else:
        linhas.append("- Competências extraídas que entraram ou saíram: nenhuma.")
    return linhas


def _linha_caso(caso: DetalheCaso) -> str:
    if caso.erro is not None:
        return f"| `{caso.id}` | {caso.tipo} | {caso.base or '—'} | erro: {caso.erro} |||||||"
    itens = f"{caso.itens_devolvidos}/{caso.itens_mantidos}/{caso.itens_descartados}"
    if caso.mantidos_sem_ancora:
        itens += f" ({caso.mantidos_sem_ancora} sem âncora)"
    comp = f"{len(caso.competencias_extraidas)}/{len(caso.competencias_anotadas)}"
    nota = "—" if caso.nota is None else str(caso.nota)
    faixa = f"{caso.faixa[0]}–{caso.faixa[1]}"
    if caso.alertas is not None:
        alertas = _lista(caso.alertas)
    elif caso.alertas_esperados:
        alertas = f"pendente (esperados: {_lista(caso.alertas_esperados)})"
    else:
        alertas = "pendente"
    return (
        f"| `{caso.id}` | {caso.tipo} | {caso.base or '—'} | {itens} | {comp} "
        f"| {_lista(caso.a_mais)} | {_lista(caso.faltando)} | {nota} | {faixa} | {alertas} |"
    )


def gerar_relatorio(
    execucao: Execucao,
    caminho_json: str,
    anterior: tuple[str, Execucao] | None,
) -> str:
    exec_anterior = anterior[1] if anterior else None
    contagem = ", ".join(f"{n} {tipo}" for tipo, n in sorted(execucao.casos_por_tipo.items()))
    total = sum(execucao.casos_por_tipo.values())
    falhas = [m for m in execucao.metricas if m.situacao == "falhou"]
    pendentes = sum(m.situacao == "pendente" for m in execucao.metricas)
    nas = sum(m.situacao == "n/a" for m in execucao.metricas)
    if execucao.passou:
        resultado = (
            f"**Resultado: todas as metas aplicáveis passaram** ({pendentes} pendentes, {nas} n/a)."
        )
    else:
        partes = [f"{m.numero} {m.nome}" for m in falhas]
        if execucao.erros:
            partes.append(f"{len(execucao.erros)} casos com erro")
        resultado = "**Resultado: falhou** — " + "; ".join(partes) + "."
    rotulos = {"extracao": "extração"}
    esforco = (
        " · ".join(f"{rotulos.get(k, k)} `{v}`" for k, v in execucao.esforco.items())
        if execucao.esforco
        else "—"
    )
    tau = " · ".join(_virgula(f"{k} {v:.2f}") for k, v in execucao.tau.items())
    modelos = " · ".join(f"{rotulos.get(k, k)} `{v}`" for k, v in execucao.modelos.items())
    texto_anterior = (
        f"`{anterior[0]}` ({anterior[1].inicio:%Y-%m-%d %H:%M:%S} UTC, `{anterior[1].git}`)"
        if anterior
        else "nenhuma"
    )

    linhas = [
        "# Evals",
        "",
        "> Gerado por `make eval`; não edite à mão. Definições e metas: "
        "[ADR 0005](adr/0005-metas-das-evals.md). Dataset: [evals/README.md](../evals/README.md).",
        "",
        "| | |",
        "| - | - |",
        f"| Execução | {execucao.inicio:%Y-%m-%d %H:%M:%S} UTC |",
        f"| Provedor | {execucao.provedor} (pipeline `{execucao.pipeline}`) |",
        f"| Código | `{execucao.git}` |",
        f"| Modelos | {modelos} |",
        f"| Esforço | {esforco} |",
        f"| τ | {tau} |",
        f"| Taxonomia | versão {execucao.taxonomia_versao} |",
        f"| Data de referência | {execucao.data_referencia:%Y-%m-%d} |",
        f"| Casos | {total} ({contagem}) |",
        f"| Resultado bruto | `{caminho_json}` |",
        f"| Anterior (mesmo provedor) | {texto_anterior} |",
        "",
        resultado,
        "",
        "## Métricas",
        "",
        *_tabela_metricas(execucao, exec_anterior),
        "",
        *[f"- {m.numero}: {m.detalhe}" for m in execucao.metricas if m.detalhe],
        "",
        "## Mudanças desde a execução anterior",
        "",
        *_mudancas(execucao, exec_anterior),
        "",
        "## Detalhes por caso",
        "",
        "Itens = devolvidos pela IA / mantidos pela ancoragem / descartados. "
        "Competências = extraídas (E) / anotadas (A), pela canônica da taxonomia.",
        "",
        "| Caso | Tipo | Base | Itens | E/A | A mais | Faltando | Nota | Faixa | Alertas |",
        "| - | - | - | - | - | - | - | - | - | - |",
        *[_linha_caso(c) for c in execucao.casos],
        "",
    ]
    return "\n".join(linhas)
