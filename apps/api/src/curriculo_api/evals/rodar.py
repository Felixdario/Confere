"""CLI das evals. `make eval` chama isto.

Uso, de `apps/api`:
    uv run python -m curriculo_api.evals.rodar [--provedor falso|anthropic] [--raiz PASTA]
        [--casos b01,b02] [--teto-usd 2.00]

- `--casos` (`CASOS` no make): só os casos listados, pelo id completo ou pelo prefixo antes do
  primeiro "-" (`b01` = `b01-frontend-senior`). As métricas sem casos do tipo delas ficam "n/a".
- `--teto-usd` (`TETO_USD` no make): teto de custo da execução inteira, obrigatório com o provedor
  real. Antes de cada chamada, o gasto real já somado (do `usage`) mais o pior caso da próxima
  chamada é comparado com o teto; se passaria, a execução para ali, sem chamar.

Grava `evals/resultados/<AAAA-MM-DD>T<hhmmss>-<provedor>.json` (hora UTC) e `docs/evals.md`, que
compara com a execução anterior do mesmo provedor. Sai 0 se todas as metas aplicáveis passaram,
1 se alguma falhou (ou houve caso com erro) e 2 se o provedor não está disponível ou os argumentos
são inválidos.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pydantic import ValidationError

from curriculo_api.analise.embeddings import EmbutidorFalso
from curriculo_api.analise.fabrica import criar_analisador
from curriculo_api.config import Settings, obter_settings
from curriculo_api.evals.dataset import Dataset, carregar_dataset, localizar_raiz
from curriculo_api.evals.harness import Execucao, executar
from curriculo_api.evals.pipeline import Pipeline, PipelineCompleto
from curriculo_api.evals.relatorio import formatar_valor, gerar_relatorio, situacao_texto
from curriculo_api.ia.fabrica import NomeProvedor, criar_provedor
from curriculo_api.ia.orcamento import Orcamento
from curriculo_api.ia.provedor import ProvedorIA, ProvedorIndisponivel
from curriculo_api.taxonomia import carregar_taxonomia

SAIDA_OK = 0
SAIDA_META_FALHOU = 1
SAIDA_PROVEDOR_INDISPONIVEL = 2

MENSAGEM_SEM_TETO = (
    "Com PROVEDOR=anthropic, informe o teto de custo da execução: make eval PROVEDOR=anthropic "
    "TETO_USD=2.00 (a execução para antes de uma chamada que passaria dele)."
)


def git_describe(raiz: Path) -> str:
    try:
        processo = subprocess.run(
            ["git", "describe", "--always", "--dirty", "--tags"],  # noqa: S607 — comando fixo
            cwd=raiz,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "desconhecido"
    return processo.stdout.strip() or "desconhecido"


def nome_do_resultado(inicio: datetime, provedor: str) -> str:
    return f"{inicio.astimezone(UTC):%Y-%m-%dT%H%M%S}-{provedor}.json"


def encontrar_anterior(pasta: Path, provedor: str, atual: str) -> tuple[Path, Execucao] | None:
    """A execução mais recente do mesmo provedor com nome anterior a `atual` (ordem do nome =
    ordem do tempo). Arquivos de formato antigo ou ilegíveis são pulados."""
    candidatos = sorted(
        p for p in pasta.glob(f"*-{provedor}.json") if p.name < atual and p.name != atual
    )
    for caminho in reversed(candidatos):
        try:
            return caminho, Execucao.model_validate_json(caminho.read_text(encoding="utf-8"))
        except (ValidationError, ValueError):
            continue
    return None


def _relativo(caminho: Path, raiz: Path) -> str:
    try:
        return caminho.resolve().relative_to(raiz.resolve()).as_posix()
    except ValueError:
        return caminho.as_posix()


class CasosDesconhecidos(ValueError):
    pass


def selecionar_casos(dataset: Dataset, filtro: str | None) -> Dataset:
    """`"b01,b02"` → só esses casos (id completo ou prefixo antes do primeiro "-")."""
    if not filtro or not filtro.strip():
        return dataset
    pedidos = [p.strip() for p in filtro.split(",") if p.strip()]
    escolhidos = []
    desconhecidos = []
    for pedido in pedidos:
        achados = [c for c in dataset.casos if pedido in (c.id, c.id.split("-", 1)[0])]
        if not achados:
            desconhecidos.append(pedido)
        escolhidos += achados
    if desconhecidos:
        raise CasosDesconhecidos(
            "casos desconhecidos em CASOS: " + ", ".join(desconhecidos) + " (use ids como b01)"
        )
    unicos = tuple(sorted({c.id: c for c in escolhidos}.values(), key=lambda c: c.id))
    return replace(dataset, casos=unicos)


def criar_pipeline(
    provedor_ia: ProvedorIA, settings: Settings, orcamento_execucao: Orcamento | None = None
) -> PipelineCompleto:
    """O `Analisador` da API. Com o provedor falso, o embutidor é o falso (sem baixar modelo e
    sem rede; as gravações usam nomes da taxonomia, então o embedding quase nunca decide); com o
    real, o fastembed do ADR 0002."""
    # Com o de regras também: as evals não baixam modelo (D-31), e a linha de base do modo
    # demonstração fica reproduzível no CI (ADR 0006). Termos fora da taxonomia não casam.
    embutidor = EmbutidorFalso() if provedor_ia.nome in ("falso", "regras") else None
    return PipelineCompleto(
        criar_analisador(
            provedor_ia, settings, embutidor=embutidor, orcamento_pai=orcamento_execucao
        )
    )


def _teto(texto: str | float | Decimal | None) -> Decimal | None:
    if texto is None or (isinstance(texto, str) and not texto.strip()):
        return None
    try:
        valor = Decimal(str(texto).replace(",", "."))
    except InvalidOperation:
        raise ValueError(f"TETO_USD inválido: {texto!r}") from None
    if valor <= 0:
        raise ValueError("TETO_USD precisa ser positivo")
    return valor


def rodar(
    raiz: Path,
    provedor: NomeProvedor,
    *,
    pasta_gravacoes: Path | None = None,
    pasta_resultados: Path | None = None,
    caminho_relatorio: Path | None = None,
    pipeline: Pipeline | None = None,
    agora: datetime | None = None,
    escrever: Callable[[str], None] = print,
    casos: str | None = None,
    teto_usd: str | float | Decimal | None = None,
    settings: Settings | None = None,
) -> int:
    pasta_evals = raiz / "evals"
    pasta_resultados = pasta_resultados or pasta_evals / "resultados"
    caminho_relatorio = caminho_relatorio or raiz / "docs" / (
        "evals-regras.md" if provedor == "regras" else "evals.md"
    )
    settings = settings or obter_settings()

    try:
        teto = _teto(teto_usd)
        dataset = selecionar_casos(carregar_dataset(pasta_evals), casos)
    except ValueError as exc:
        escrever(str(exc))
        return SAIDA_PROVEDOR_INDISPONIVEL

    orcamento: Orcamento | None = None
    if pipeline is None:
        try:
            provedor_ia = criar_provedor(
                provedor,
                pasta_gravacoes=pasta_gravacoes or pasta_evals / "gravacoes",
                settings=settings,
            )
        except ProvedorIndisponivel as exc:
            escrever(str(exc))
            return SAIDA_PROVEDOR_INDISPONIVEL
        if provedor == "anthropic" and teto is None:
            escrever(MENSAGEM_SEM_TETO)
            return SAIDA_PROVEDOR_INDISPONIVEL
        if teto is not None:
            orcamento = Orcamento(teto, escopo="execucao")
        pipeline = criar_pipeline(provedor_ia, settings, orcamento)

    if provedor in ("falso", "regras"):
        modelos: dict[str, str] = {"extracao": provedor, "feedback": provedor}
        esforco: dict[str, str] | None = None
    else:
        modelos = {
            "extracao": settings.claude_modelo_extracao,
            "feedback": settings.claude_modelo_feedback,
        }
        esforco = {
            "extracao": settings.claude_esforco_extracao,
            "feedback": settings.claude_esforco_feedback,
        }

    inicio = (agora or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    execucao = asyncio.run(
        executar(
            dataset,
            pipeline,
            carregar_taxonomia(),
            provedor=provedor,
            inicio=inicio,
            git=git_describe(raiz),
            modelos=modelos,
            esforco=esforco,
            tau={"alto": settings.tau_alto, "baixo": settings.tau_baixo},
            guardar_extracoes=provedor == "anthropic",
        )
    )
    execucao = execucao.model_copy(
        update={
            "filtro_casos": tuple(c.id for c in dataset.casos) if casos else None,
            "teto_usd": teto,
            "gasto_usd": orcamento.gasto if orcamento is not None else None,
        }
    )

    pasta_resultados.mkdir(parents=True, exist_ok=True)
    nome = nome_do_resultado(inicio, provedor)
    caminho_json = pasta_resultados / nome
    if caminho_json.exists():
        raise FileExistsError(f"{caminho_json} já existe; espere um segundo e rode de novo")
    anterior = encontrar_anterior(pasta_resultados, provedor, nome)
    caminho_json.write_text(
        execucao.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    caminho_relatorio.parent.mkdir(parents=True, exist_ok=True)
    caminho_relatorio.write_text(
        gerar_relatorio(
            execucao,
            _relativo(caminho_json, raiz),
            (_relativo(anterior[0], raiz), anterior[1]) if anterior else None,
        ),
        encoding="utf-8",
        newline="\n",
    )

    escrever(f"Evals ({provedor}, {len(dataset.casos)} casos, código {execucao.git}):")
    for m in execucao.metricas:
        valor = formatar_valor(m.valor, m.unidade) if m.valor is not None else "—"
        escrever(f"  {m.numero:>3}  {m.nome}: {valor}  [meta {m.meta}] -> {situacao_texto(m)}")
    for caso in execucao.erros:
        escrever(f"  erro em {caso.id}: {caso.erro}")
    if orcamento is not None:
        escrever(f"Gasto real: US$ {orcamento.gasto:.4f} de US$ {orcamento.limite:.2f}")
    escrever(f"Resultado: {_relativo(caminho_json, raiz)}")
    escrever(f"Relatório: {_relativo(caminho_relatorio, raiz)}")
    if anterior:
        escrever(f"Comparado com: {_relativo(anterior[0], raiz)}")
    escrever("PASSOU" if execucao.passou else "FALHOU")
    return SAIDA_OK if execucao.passou else SAIDA_META_FALHOU


def main(argv: list[str] | None = None) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Roda as evals do analisador de currículos.")
    parser.add_argument("--provedor", choices=["falso", "regras", "anthropic"], default="falso")
    parser.add_argument("--raiz", type=Path, default=None, help="raiz do repositório")
    parser.add_argument("--casos", default=None, help="ids separados por vírgula (b01,b02)")
    parser.add_argument("--teto-usd", default=None, help="teto de custo da execução, em US$")
    args = parser.parse_args(argv)
    provedor: NomeProvedor = (
        "anthropic"
        if args.provedor == "anthropic"
        else "regras"
        if args.provedor == "regras"
        else "falso"
    )
    return rodar(args.raiz or localizar_raiz(), provedor, casos=args.casos, teto_usd=args.teto_usd)


if __name__ == "__main__":
    sys.exit(main())
