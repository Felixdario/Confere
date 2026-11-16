"""Calibração de τ_alto/τ_baixo (ADR 0002) a partir de uma execução REAL das evals.

Uso, de `apps/api` (ou `make calibrar-tau [RESULTADO=evals/resultados/<arquivo>.json]`):
    uv run python -m curriculo_api.evals.calibrar_tau [--resultado ARQUIVO] [--raiz PASTA]

A execução com `PROVEDOR=anthropic` guarda, por caso, o currículo mantido pela ancoragem e a vaga
extraída (`DetalheCaso.extracao`). Este comando refaz só a parte em código (correspondência e
nota) para cada par (τ_alto, τ_baixo) de uma grade, sem chamar a API de novo, e mede contra o
gabarito:
- **status certos**: requisitos cujo status calculado é o `status_esperado` anotado;
- **nota na faixa**: pares-base com a nota dentro da faixa anotada (métrica 4);
- **por embedding**: decisões tomadas pela similaridade (quanto o τ pesa de fato).

Sai 2 se não houver execução real com extrações. Sem rede além do download do modelo de
embeddings na primeira vez (ADR 0002).
"""

from __future__ import annotations

import argparse
import io
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from curriculo_api.analise.correspondencia import Correspondente, Limiares
from curriculo_api.analise.embeddings import Comparador, Embutidor, EmbutidorFastEmbed
from curriculo_api.analise.erros import ErroAnalise
from curriculo_api.analise.fabrica import resolver_pasta
from curriculo_api.analise.nota import calcular_tabela
from curriculo_api.ancoragem import normalizar_para_ancora
from curriculo_api.config import obter_settings
from curriculo_api.evals.dataset import Dataset, carregar_dataset, localizar_raiz
from curriculo_api.evals.harness import Execucao
from curriculo_api.taxonomia import Taxonomia, carregar_taxonomia

SAIDA_OK = 0
SAIDA_SEM_EXECUCAO_REAL = 2
GRADE_ALTO = (0.75, 0.80, 0.85, 0.90, 0.95)
GRADE_BAIXO = (0.55, 0.60, 0.65, 0.70, 0.75, 0.80)

MENSAGEM_SEM_EXECUCAO = (
    "Nenhuma execução real com extrações em evals/resultados/. Rode antes "
    "`make eval PROVEDOR=anthropic CASOS=... TETO_USD=...` (precisa da chave) e depois "
    "`make calibrar-tau`."
)


@dataclass(frozen=True)
class PontoDaGrade:
    alto: float
    baixo: float
    status_certos: int
    requisitos: int
    na_faixa: int
    pares_base: int
    por_embedding: int


def ultima_execucao_real(pasta: Path) -> Path | None:
    candidatos = sorted(pasta.glob("*-anthropic.json"))
    return candidatos[-1] if candidatos else None


def calibrar(
    execucao: Execucao,
    dataset: Dataset,
    taxonomia: Taxonomia,
    embutidor: Embutidor,
    grade_alto: Sequence[float] = GRADE_ALTO,
    grade_baixo: Sequence[float] = GRADE_BAIXO,
) -> list[PontoDaGrade]:
    casos = dataset.por_id()
    comparador = Comparador(taxonomia, embutidor)
    com_extracao = [
        (c.id, c.extracao) for c in execucao.casos if c.extracao is not None and c.id in casos
    ]
    pontos: list[PontoDaGrade] = []
    for alto in grade_alto:
        for baixo in grade_baixo:
            if baixo > alto:
                continue
            certos = total = na_faixa = base = por_embedding = 0
            for caso_id, extracao in com_extracao:
                caso = casos[caso_id]
                correspondente = Correspondente(
                    taxonomia,
                    comparador,
                    Limiares(alto=alto, baixo=baixo),
                    dataset.config.data_referencia,
                )
                curriculo, vaga = extracao.curriculo_mantido, extracao.vaga
                resultado = correspondente.corresponder(curriculo, vaga)
                esperados = {
                    normalizar_para_ancora(r.descricao): r.status_esperado
                    for r in caso.esperado.requisitos
                }
                for linha in resultado.linhas:
                    status = esperados.get(normalizar_para_ancora(linha.descricao))
                    if status is not None:
                        total += 1
                        certos += status == linha.status
                    por_embedding += linha.regra == "similaridade"
                if caso.esperado.tipo != "base":
                    continue
                base += 1
                try:
                    tabela = calcular_tabela(
                        resultado.linhas,
                        curriculo,
                        vaga,
                        resultado.chaves_atendidas,
                        taxonomia,
                        dataset.config.data_referencia,
                    )
                except ErroAnalise:
                    continue
                minimo, maximo = caso.esperado.faixa_nota
                na_faixa += minimo <= tabela.nota <= maximo
            pontos.append(PontoDaGrade(alto, baixo, certos, total, na_faixa, base, por_embedding))
    return pontos


def formatar(pontos: Sequence[PontoDaGrade], atual: tuple[float, float]) -> list[str]:
    def pct(a: int, b: int) -> str:
        return "—" if b == 0 else f"{100 * a / b:.1f} %".replace(".", ",")

    linhas = [
        "| τ_alto | τ_baixo | Status certos | Nota na faixa (base) | Por embedding | |",
        "| - | - | - | - | - | - |",
    ]
    melhor = max(pontos, key=lambda p: (p.na_faixa, p.status_certos, -p.por_embedding))
    for p in pontos:
        marcas = []
        if (p.alto, p.baixo) == atual:
            marcas.append("atual")
        if p == melhor:
            marcas.append("melhor")
        linhas.append(
            f"| {p.alto:.2f} | {p.baixo:.2f} | {p.status_certos}/{p.requisitos} "
            f"({pct(p.status_certos, p.requisitos)}) | {p.na_faixa}/{p.pares_base} "
            f"({pct(p.na_faixa, p.pares_base)}) | {p.por_embedding} | {', '.join(marcas)} |"
        )
    return linhas


def main(
    argv: list[str] | None = None,
    *,
    escrever: Callable[[str], None] = print,
    embutidor: Embutidor | None = None,
) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Calibra τ com uma execução real das evals.")
    parser.add_argument("--resultado", type=Path, default=None)
    parser.add_argument("--raiz", type=Path, default=None)
    args = parser.parse_args(argv)
    raiz: Path = args.raiz or localizar_raiz()
    caminho = args.resultado or ultima_execucao_real(raiz / "evals" / "resultados")
    if caminho is None or not caminho.is_file():
        escrever(MENSAGEM_SEM_EXECUCAO)
        return SAIDA_SEM_EXECUCAO_REAL
    execucao = Execucao.model_validate_json(caminho.read_text(encoding="utf-8"))
    if not any(c.extracao is not None for c in execucao.casos):
        escrever(MENSAGEM_SEM_EXECUCAO)
        return SAIDA_SEM_EXECUCAO_REAL
    settings = obter_settings()
    embutidor = embutidor or EmbutidorFastEmbed(
        settings.modelo_embeddings, resolver_pasta(settings.pasta_modelos)
    )
    pontos = calibrar(execucao, carregar_dataset(raiz / "evals"), carregar_taxonomia(), embutidor)
    escrever(f"Calibração de τ com {caminho.name} ({embutidor.nome}):")
    for linha in formatar(pontos, (settings.tau_alto, settings.tau_baixo)):
        escrever(linha)
    escrever(
        "Escolha o par e registre no ADR 0002 com estes números; mude TAU_ALTO/TAU_BAIXO e rode "
        "make eval de novo para conferir."
    )
    return SAIDA_OK


if __name__ == "__main__":
    sys.exit(main())
