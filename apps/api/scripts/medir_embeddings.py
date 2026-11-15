"""Mede modelos multilíngues do fastembed para o ADR 0002.

Uso (de apps/api):
    uv run python scripts/medir_embeddings.py [--modelo NOME ...] [--cache PASTA]

Para cada modelo: tamanho em disco do download, tempo do primeiro carregamento (com download),
tempo de carga já em cache, dimensão, tempo para embutir os termos e a similaridade de cosseno
de pares de competências. Imprime uma tabela em Markdown.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding

MODELOS_PADRAO = [
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
]

# (a, b, o que esperamos)
PARES: list[tuple[str, str, str]] = [
    ("React.js", "ReactJS", "mesma"),
    ("Node", "Node.js", "mesma"),
    ("PostgreSQL", "Postgres", "mesma"),
    ("Gestão de projetos", "Project management", "mesma"),
    ("Inglês fluente", "Fluent English", "mesma"),
    ("Vue.js", "React", "relacionada"),
    ("Docker", "Kubernetes", "relacionada"),
    ("JavaScript", "Java", "diferente (falso amigo)"),
    ("Python", "Excel", "diferente"),
    ("Contabilidade", "React", "diferente"),
]


def tamanho_pasta(pasta: Path) -> int:
    return sum(p.stat().st_size for p in pasta.rglob("*") if p.is_file())


def cosseno(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def medir(nome: str, cache_raiz: Path) -> None:
    cache = cache_raiz / nome.replace("/", "__")
    if cache.exists():
        shutil.rmtree(cache)
    cache.mkdir(parents=True)

    t0 = time.perf_counter()
    TextEmbedding(model_name=nome, cache_dir=str(cache))
    t_primeira = time.perf_counter() - t0
    tamanho_mb = tamanho_pasta(cache) / 1_000_000

    t0 = time.perf_counter()
    modelo = TextEmbedding(model_name=nome, cache_dir=str(cache))
    t_carga = time.perf_counter() - t0

    termos = sorted({t for a, b, _ in PARES for t in (a, b)})
    t0 = time.perf_counter()
    vetores = dict(zip(termos, modelo.embed(termos), strict=True))
    t_embed = time.perf_counter() - t0
    dim = len(next(iter(vetores.values())))

    print(f"\n### {nome}\n")
    print("| Medida | Valor |")
    print("| - | - |")
    print(f"| Download em disco | {tamanho_mb:.0f} MB |")
    print(f"| 1ª carga (download + sessão ONNX) | {t_primeira:.1f} s |")
    print(f"| Carga com cache | {t_carga:.2f} s |")
    print(f"| Dimensão | {dim} |")
    print(f"| Embutir {len(termos)} termos | {t_embed * 1000:.0f} ms |")
    print("\n| Par | Esperado | Cosseno |")
    print("| - | - | - |")
    for a, b, esperado in PARES:
        print(f"| {a} / {b} | {esperado} | {cosseno(vetores[a], vetores[b]):.3f} |")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modelo", action="append", dest="modelos")
    parser.add_argument("--cache", type=Path, default=Path("../../data/modelos-medicao"))
    args = parser.parse_args()
    modelos: list[str] = args.modelos or MODELOS_PADRAO
    cache_raiz: Path = args.cache
    print(f"Python {sys.version.split()[0]}; cache em {cache_raiz.resolve()}")
    for nome in modelos:
        medir(nome, cache_raiz)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
