"""CLI das evals. `make eval` chama isto.

Uso, de `apps/api`:
    uv run python -m curriculo_api.evals.rodar [--provedor falso|anthropic] [--raiz PASTA]

Grava `evals/resultados/<AAAA-MM-DD>T<hhmmss>-<provedor>.json` (hora UTC) e `docs/evals.md`, que
compara com a execução anterior do mesmo provedor. Sai 0 se todas as metas aplicáveis passaram,
1 se alguma falhou (ou houve caso com erro) e 2 se o provedor não está disponível.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from curriculo_api.config import obter_settings
from curriculo_api.evals.dataset import carregar_dataset, localizar_raiz
from curriculo_api.evals.harness import Execucao, executar
from curriculo_api.evals.pipeline import Pipeline, PipelineExtracao
from curriculo_api.evals.relatorio import formatar_valor, gerar_relatorio, situacao_texto
from curriculo_api.ia.fabrica import NomeProvedor, criar_provedor
from curriculo_api.ia.provedor import ProvedorIndisponivel
from curriculo_api.taxonomia import carregar_taxonomia

SAIDA_OK = 0
SAIDA_META_FALHOU = 1
SAIDA_PROVEDOR_INDISPONIVEL = 2


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
) -> int:
    pasta_evals = raiz / "evals"
    pasta_resultados = pasta_resultados or pasta_evals / "resultados"
    caminho_relatorio = caminho_relatorio or raiz / "docs" / "evals.md"
    settings = obter_settings()

    if pipeline is None:
        try:
            provedor_ia = criar_provedor(
                provedor, pasta_gravacoes=pasta_gravacoes or pasta_evals / "gravacoes"
            )
        except ProvedorIndisponivel as exc:
            escrever(str(exc))
            return SAIDA_PROVEDOR_INDISPONIVEL
        pipeline = PipelineExtracao(provedor_ia)

    if provedor == "falso":
        modelos = {"extracao": "falso", "feedback": "falso"}
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

    dataset = carregar_dataset(pasta_evals)
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
        )
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
    parser.add_argument("--provedor", choices=["falso", "anthropic"], default="falso")
    parser.add_argument("--raiz", type=Path, default=None, help="raiz do repositório")
    args = parser.parse_args(argv)
    provedor: NomeProvedor = "anthropic" if args.provedor == "anthropic" else "falso"
    return rodar(args.raiz or localizar_raiz(), provedor)


if __name__ == "__main__":
    sys.exit(main())
