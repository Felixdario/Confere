"""O vizinho mais próximo da taxonomia vem do pgvector (ADR 0002, fase 4)."""

from __future__ import annotations

from sqlalchemy import delete, func, select, text

from curriculo_api.analise.embeddings import Comparador, EmbutidorFalso
from curriculo_api.analise.vetores_pg import (
    ComparadorPgvector,
    sincronizar_vetores,
    termos_da_taxonomia,
)
from curriculo_api.api.dependencias import Recursos
from curriculo_api.db.modelos import VetorTaxonomia
from curriculo_api.taxonomia import carregar_taxonomia


async def test_vetores_no_banco_e_vizinho_pelo_indice(recursos: Recursos) -> None:
    taxonomia = carregar_taxonomia()
    embutidor = EmbutidorFalso(dim=384)
    async with recursos.fabrica() as db:
        await db.execute(delete(VetorTaxonomia))
        await db.commit()
        gravados = await sincronizar_vetores(db, taxonomia, embutidor)
        assert gravados == len(termos_da_taxonomia(taxonomia))
        assert await sincronizar_vetores(db, taxonomia, embutidor) == 0  # já em dia
        total = (await db.execute(select(func.count()).select_from(VetorTaxonomia))).scalar_one()
        assert total == gravados
        indice = (
            await db.execute(
                text(
                    "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_vetores_taxonomia_hnsw'"
                )
            )
        ).scalar_one()
        assert "hnsw" in indice and "vector_cosine_ops" in indice

    banco = ComparadorPgvector(taxonomia, embutidor, recursos.fabrica)
    memoria = Comparador(taxonomia, embutidor)
    termos = ["React", "Kubernetes orquestrado", "arquitetura de micro-frontends", "Postgres"]
    await banco.preparar(termos)
    assert banco.consultas_banco == len(termos)
    for termo in termos:
        canonica_b, termo_b, sim_b = banco.canonica_mais_proxima(termo)
        canonica_m, termo_m, sim_m = memoria.canonica_mais_proxima(termo)
        # O banco e o caminho em memória acham o mesmo vizinho.
        assert (canonica_b, termo_b) == (canonica_m, termo_m)
        assert abs(sim_b - sim_m) < 1e-4
    # O próprio termo da taxonomia é o vizinho dele mesmo, com cosseno 1.
    assert banco.canonica_mais_proxima("Postgres")[2] > 0.999
