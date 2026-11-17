"""Vizinho mais próximo da taxonomia no pgvector (ADR 0002, fase 4).

Os vetores de todos os termos da taxonomia (canônicas e sinônimos) ficam em `vetores_taxonomia`,
por modelo de embeddings e versão da taxonomia, com índice HNSW de cosseno. Na análise, antes da
correspondência (que é síncrona), `preparar` embute de uma vez os termos que a taxonomia não
conhece e pergunta ao banco o vizinho mais próximo de cada um (`ORDER BY vetor <=> :v LIMIT 1`).
`canonica_mais_proxima` responde dessas respostas; um termo que não foi preparado (ou o banco fora
do ar) cai no caminho em memória do `Comparador`, o mesmo dos testes de unidade e das evals.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from curriculo_api.analise.embeddings import Comparador, Embutidor
from curriculo_api.db.modelos import DIMENSAO_VETORES, VetorTaxonomia
from curriculo_api.taxonomia import Taxonomia

log = logging.getLogger("curriculo_api.analise.vetores_pg")


def termos_da_taxonomia(taxonomia: Taxonomia) -> list[tuple[str, str]]:
    return sorted(
        (termo, entrada.canonica)
        for entrada in taxonomia.arquivo.competencias
        for termo in (entrada.canonica, *entrada.sinonimos)
    )


async def sincronizar_vetores(db: AsyncSession, taxonomia: Taxonomia, embutidor: Embutidor) -> int:
    """Grava os vetores da taxonomia para (modelo, versão), se ainda não estão todos lá.
    Devolve quantos foram gravados (0 se já estava em dia)."""
    termos = termos_da_taxonomia(taxonomia)
    filtro = (
        VetorTaxonomia.modelo == embutidor.nome,
        VetorTaxonomia.versao_taxonomia == taxonomia.versao,
    )
    existentes = (
        await db.execute(select(func.count()).select_from(VetorTaxonomia).where(*filtro))
    ).scalar_one()
    if existentes == len(termos):
        return 0
    vetores = embutidor.embutir([t for t, _ in termos])
    if vetores and len(vetores[0]) != DIMENSAO_VETORES:
        raise ValueError(
            f"o modelo {embutidor.nome} tem dimensão {len(vetores[0])}; a tabela espera "
            f"{DIMENSAO_VETORES}"
        )
    await db.execute(delete(VetorTaxonomia).where(*filtro))
    db.add_all(
        VetorTaxonomia(
            modelo=embutidor.nome,
            versao_taxonomia=taxonomia.versao,
            termo=termo,
            canonica=canonica,
            vetor=vetor,
        )
        for (termo, canonica), vetor in zip(termos, vetores, strict=True)
    )
    await db.commit()
    log.info("vetores.sincronizados", extra={"termos": len(termos), "modelo": embutidor.nome})
    return len(termos)


class ComparadorPgvector(Comparador):
    def __init__(
        self,
        taxonomia: Taxonomia,
        embutidor: Embutidor,
        fabrica: async_sessionmaker[AsyncSession],
        pasta: Path | None = None,
    ) -> None:
        super().__init__(taxonomia, embutidor, pasta)
        self._fabrica = fabrica
        self._vizinhos: dict[str, tuple[str, str, float]] = {}
        self._sincronizado = False
        self.consultas_banco = 0

    async def preparar(self, termos: Sequence[str]) -> None:
        faltando = sorted({t for t in termos if t not in self._vizinhos})
        if not faltando:
            return
        try:
            async with self._fabrica() as db:
                if not self._sincronizado:
                    await sincronizar_vetores(db, self._taxonomia, self.embutidor)
                    self._sincronizado = True
                vetores = self.embutidor.embutir(faltando)
                for termo, vetor in zip(faltando, vetores, strict=True):
                    distancia = VetorTaxonomia.vetor.cosine_distance(vetor)
                    linha = (
                        await db.execute(
                            select(VetorTaxonomia.canonica, VetorTaxonomia.termo, distancia)
                            .where(
                                VetorTaxonomia.modelo == self.embutidor.nome,
                                VetorTaxonomia.versao_taxonomia == self._taxonomia.versao,
                            )
                            .order_by(distancia)
                            .limit(1)
                        )
                    ).first()
                    self.consultas_banco += 1
                    if linha is not None:
                        canonica, termo_tax, dist = linha
                        self._vizinhos[termo] = (canonica, termo_tax, 1.0 - float(dist))
        except (OSError, SQLAlchemyError):
            # Banco fora do ar: segue pelo caminho em memória (o resultado é o mesmo).
            log.warning("vetores.banco_indisponivel")

    def canonica_mais_proxima(self, termo: str) -> tuple[str, str, float]:
        pronto = self._vizinhos.get(termo)
        if pronto is None:
            return super().canonica_mais_proxima(termo)
        self.consultas += 1
        canonica, termo_tax, similaridade = pronto
        forcada = self._forcada(termo, termo_tax)
        return canonica, termo_tax, forcada if forcada is not None else similaridade
