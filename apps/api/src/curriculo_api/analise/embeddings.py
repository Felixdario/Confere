"""Embeddings locais para termos fora da taxonomia (ADR 0002).

- `EmbutidorFastEmbed`: o modelo fixado pelo nome (`MODELO_EMBEDDINGS`), carregado só na primeira
  vez que um termo cai fora da taxonomia (com as gravações das evals isso não acontece) e com
  cache de vetores em memória e, para a taxonomia, em disco (`<pasta_modelos>/vetores/`).
- `EmbutidorFalso`: determinístico, para os testes (o CI não baixa modelo).

Os vetores saem normalizados (norma 1): o cosseno é o produto escalar. O pgvector entra na fase 4.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt

from curriculo_api.taxonomia import Taxonomia, normalizar_termo

log = logging.getLogger("curriculo_api.analise.embeddings")

Vetor = npt.NDArray[np.float32]


@runtime_checkable
class Embutidor(Protocol):
    @property
    def nome(self) -> str: ...

    def embutir(self, termos: Sequence[str]) -> list[Vetor]: ...


def _normalizado(vetor: Iterable[float]) -> Vetor:
    v = np.asarray(list(vetor), dtype=np.float32)
    norma = float(np.linalg.norm(v))
    return v / norma if norma else v


def cosseno(a: Vetor, b: Vetor) -> float:
    return float(np.dot(a, b))


class EmbutidorFastEmbed:
    """fastembed (ONNX, CPU). A carga do modelo é preguiçosa."""

    def __init__(
        self,
        modelo: str,
        pasta_cache: Path,
        fabrica: Callable[[str, str], Any] | None = None,
    ) -> None:
        self._modelo_nome = modelo
        self._pasta = pasta_cache
        self._fabrica = fabrica
        self._modelo: Any = None
        self._memoria: dict[str, Vetor] = {}

    @property
    def nome(self) -> str:
        return self._modelo_nome

    def _carregar(self) -> Any:
        if self._modelo is None:
            if self._fabrica is not None:
                self._modelo = self._fabrica(self._modelo_nome, str(self._pasta))
            else:
                from fastembed import TextEmbedding

                self._pasta.mkdir(parents=True, exist_ok=True)
                self._modelo = TextEmbedding(
                    model_name=self._modelo_nome, cache_dir=str(self._pasta)
                )
            log.info("embeddings.modelo_carregado", extra={"modelo": self._modelo_nome})
        return self._modelo

    def embutir(self, termos: Sequence[str]) -> list[Vetor]:
        faltando = sorted({t for t in termos if t not in self._memoria})
        if faltando:
            modelo = self._carregar()
            for termo, vetor in zip(faltando, modelo.embed(faltando), strict=True):
                self._memoria[termo] = _normalizado(vetor)
        return [self._memoria[t] for t in termos]


class EmbutidorFalso:
    """Vetores determinísticos: cada termo normalizado vira um vetor pseudoaleatório fixo (termos
    diferentes ficam quase ortogonais). `pares` força similaridades conhecidas para os testes."""

    def __init__(self, pares: Mapping[tuple[str, str], float] | None = None, dim: int = 64) -> None:
        self._dim = dim
        self._pares = {
            tuple(sorted((normalizar_termo(a), normalizar_termo(b)))): s
            for (a, b), s in (pares or {}).items()
        }
        self.chamadas = 0

    @property
    def nome(self) -> str:
        return "falso"

    def embutir(self, termos: Sequence[str]) -> list[Vetor]:
        self.chamadas += 1
        return [self._vetor(t) for t in termos]

    def _vetor(self, termo: str) -> Vetor:
        semente = int.from_bytes(hashlib.sha256(normalizar_termo(termo).encode()).digest()[:8])
        return _normalizado(np.random.default_rng(semente).standard_normal(self._dim))

    def similaridade(self, a: str, b: str) -> float | None:
        chave = tuple(sorted((normalizar_termo(a), normalizar_termo(b))))
        return self._pares.get(chave)


class Comparador:
    """Similaridade de cosseno entre termos, com os vetores da taxonomia em cache (memória e,
    com o modelo real, disco: `.npz` identificado pelo modelo, pela versão e pelo conteúdo da
    taxonomia). Nada é calculado enquanto ninguém pergunta."""

    def __init__(
        self, taxonomia: Taxonomia, embutidor: Embutidor, pasta: Path | None = None
    ) -> None:
        self._taxonomia = taxonomia
        self.embutidor = embutidor
        self._pasta = pasta
        self._termos: list[tuple[str, str]] | None = None  # (termo, canônica)
        self._matriz: npt.NDArray[np.float32] | None = None
        self.consultas = 0

    def _todos(self) -> list[tuple[str, str]]:
        return sorted(
            (termo, entrada.canonica)
            for entrada in self._taxonomia.arquivo.competencias
            for termo in (entrada.canonica, *entrada.sinonimos)
        )

    def _arquivo_cache(self, termos: list[tuple[str, str]]) -> Path | None:
        if self._pasta is None or isinstance(self.embutidor, EmbutidorFalso):
            return None
        conteudo = "\n".join(f"{t}\t{c}" for t, c in termos)
        resumo = hashlib.sha256(
            f"{self.embutidor.nome}\n{self._taxonomia.versao}\n{conteudo}".encode()
        ).hexdigest()[:16]
        return self._pasta / "vetores" / f"taxonomia-{resumo}.npz"

    def _taxonomia_vetorizada(self) -> tuple[list[tuple[str, str]], npt.NDArray[np.float32]]:
        if self._termos is not None and self._matriz is not None:
            return self._termos, self._matriz
        termos = self._todos()
        arquivo = self._arquivo_cache(termos)
        matriz: npt.NDArray[np.float32] | None = None
        if arquivo is not None and arquivo.is_file():
            with np.load(arquivo) as dados:
                matriz = np.asarray(dados["vetores"], dtype=np.float32)
            if matriz.shape[0] != len(termos):
                matriz = None
        if matriz is None:
            matriz = np.stack(self.embutidor.embutir([t for t, _ in termos]))
            if arquivo is not None:
                arquivo.parent.mkdir(parents=True, exist_ok=True)
                np.savez(arquivo, vetores=matriz)
        self._termos, self._matriz = termos, matriz
        return termos, matriz

    def _forcada(self, a: str, b: str) -> float | None:
        if isinstance(self.embutidor, EmbutidorFalso):
            return self.embutidor.similaridade(a, b)
        return None

    def similaridades(self, termo: str, candidatos: Sequence[str]) -> list[float]:
        self.consultas += 1
        if not candidatos:
            return []
        vetores = self.embutidor.embutir([termo, *candidatos])
        base = vetores[0]
        resultado: list[float] = []
        for candidato, vetor in zip(candidatos, vetores[1:], strict=True):
            forcada = self._forcada(termo, candidato)
            resultado.append(forcada if forcada is not None else cosseno(base, vetor))
        return resultado

    def canonica_mais_proxima(self, termo: str) -> tuple[str, str, float]:
        """(canônica, termo da taxonomia mais parecido, cosseno)."""
        self.consultas += 1
        termos, matriz = self._taxonomia_vetorizada()
        (vetor,) = self.embutidor.embutir([termo])
        similaridades = [float(x) for x in matriz @ vetor]
        for i, (termo_tax, _) in enumerate(termos):
            forcada = self._forcada(termo, termo_tax)
            if forcada is not None:
                similaridades[i] = forcada
        indice = int(np.argmax(similaridades))
        return termos[indice][1], termos[indice][0], similaridades[indice]
