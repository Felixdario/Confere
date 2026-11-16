"""Gera as gravações do provedor falso a partir das anotações (extração "perfeita", uso zerado).

Uso, de `apps/api`:
    uv run python -m curriculo_api.evals.gravacoes             # (re)escreve evals/gravacoes/
    uv run python -m curriculo_api.evals.gravacoes --verificar # só confere; sai 1 se desatualizado

Rode de novo sempre que um `curriculo.md`, `curriculo.pdf`/`.docx`, `vaga.md`, `esperado.yaml` ou
`feedback.yaml` mudar, ou quando a ingestão ou a anonimização mudarem: o hash é o do texto que o
provedor recebe (o currículo ingerido e anonimizado, e a vaga normalizada), então ele muda junto.

O feedback gravado vem de `evals/casos/<id>/feedback.yaml` (as variantes usam o do par-base). São
**respostas de demonstração** escritas à mão para o provedor falso, coerentes com cada caso; algumas
trazem de propósito uma reescrita que inventa competência, para provar o filtro da evidência.
"""

from __future__ import annotations

import argparse
import re
import sys
from decimal import Decimal
from pathlib import Path

import yaml

from curriculo_api.analise.niveis import nivel_de
from curriculo_api.evals.dataset import Caso, Dataset, carregar_dataset, localizar_raiz
from curriculo_api.evals.pipeline import ingerir_caso
from curriculo_api.evals.referencia import data_parcial
from curriculo_api.ia.falso import (
    VERSAO_GRAVACAO,
    ChamadaCurriculo,
    ChamadaFeedback,
    ChamadaVaga,
    Gravacao,
    sha256_texto,
)
from curriculo_api.ia.modelos import (
    Certificacao,
    Competencia,
    CurriculoExtraido,
    Etapa,
    Experiencia,
    FeedbackIA,
    Formacao,
    Idioma,
    RegistroUso,
    Requisito,
    VagaExtraida,
)
from curriculo_api.taxonomia import carregar_taxonomia


def uso_zerado(etapa: Etapa) -> RegistroUso:
    return RegistroUso(
        etapa=etapa,
        modelo="falso",
        duracao_ms=0,
        input_tokens=0,
        output_tokens=0,
        custo_usd=Decimal(0),
    )


def competencias_da_injecao(caso: Caso) -> tuple[Competencia, ...]:
    """Rodada 3: nas variantes com injection visível no currículo, a gravação imita um modelo
    enganado e cita a frase injetada como evidência de cada competência da taxonomia que ela
    afirma (no i02: TypeScript e AWS). A ancoragem tem de descartá-las por injection, e a nota da
    variante continua a do par-base (métrica 6)."""
    injecao = caso.esperado.injecao
    if injecao is None or injecao.oculta or injecao.local != "curriculo":
        return ()
    taxonomia = carregar_taxonomia()
    palavras = re.findall(r"[\w#+./-]+", injecao.trecho)
    achadas: list[str] = []
    for n in (3, 2, 1):
        for i in range(len(palavras) - n + 1):
            termo = " ".join(palavras[i : i + n]).strip(".,;:")
            canonica = taxonomia.canonica_de(termo)
            if canonica is not None and termo not in achadas and canonica not in achadas:
                achadas.append(canonica)
    return tuple(Competencia(nome=c, trecho=injecao.trecho) for c in sorted(achadas))


def curriculo_perfeito(caso: Caso) -> CurriculoExtraido:
    esperado = caso.esperado
    return CurriculoExtraido(
        experiencias=tuple(
            Experiencia(
                cargo=e.cargo,
                empresa=e.empresa,
                inicio=data_parcial(e.inicio),
                fim=data_parcial(e.fim) if e.fim is not None else None,
                trecho=e.trecho,
            )
            for e in esperado.experiencias
        ),
        competencias=tuple(
            Competencia(nome=c.nome, trecho=c.trecho, experiencias=c.experiencias)
            for c in esperado.competencias
        )
        + competencias_da_injecao(caso),
        formacao=tuple(
            Formacao(
                curso=f.curso, instituicao=f.instituicao, conclusao=f.conclusao, trecho=f.trecho
            )
            for f in esperado.formacao
        ),
        idiomas=tuple(
            Idioma(idioma=i.idioma, nivel=i.nivel, trecho=i.trecho) for i in esperado.idiomas
        ),
        certificacoes=tuple(
            Certificacao(nome=c.nome, competencia=c.canonica, trecho=c.trecho)
            for c in esperado.certificacoes
        ),
    )


def vaga_perfeita(caso: Caso) -> VagaExtraida:
    esperado = caso.esperado
    return VagaExtraida(
        titulo=esperado.titulo_vaga,
        idioma=esperado.idioma_vaga,
        nivel=esperado.nivel,
        anos_minimos=esperado.anos_minimos,
        requisitos=tuple(
            Requisito(
                descricao=r.descricao,
                tipo=r.tipo,
                competencia=r.competencia,
                anos_minimos=r.anos,
                nivel=nivel_de(r.descricao),
            )
            for r in esperado.requisitos
        ),
    )


def arquivo_de_feedback(caso: Caso) -> Path:
    """`feedback.yaml` do caso, ou do par-base nas variantes."""
    pasta = caso.pasta if caso.esperado.base is None else caso.pasta.parent / caso.esperado.base
    return pasta / "feedback.yaml"


def feedback_gravado(caso: Caso) -> FeedbackIA:
    arquivo = arquivo_de_feedback(caso)
    if not arquivo.is_file():
        raise FileNotFoundError(f"{caso.id}: falta {arquivo.parent.name}/feedback.yaml")
    return FeedbackIA.model_validate(yaml.safe_load(arquivo.read_text(encoding="utf-8")))


def gerar_gravacao(caso: Caso) -> Gravacao:
    curriculo, vaga = ingerir_caso(caso)
    chave = sha256_texto(curriculo.texto_para_ia)
    return Gravacao(
        versao=VERSAO_GRAVACAO,
        id=caso.id,
        extrair_curriculo=ChamadaCurriculo(
            entrada_sha256=chave,
            saida=curriculo_perfeito(caso),
            uso=uso_zerado("extrair_curriculo"),
        ),
        extrair_vaga=ChamadaVaga(
            entrada_sha256=sha256_texto(vaga.texto),
            saida=vaga_perfeita(caso),
            uso=uso_zerado("extrair_vaga"),
        ),
        escrever_feedback=ChamadaFeedback(
            entrada_sha256=chave,
            saida=feedback_gravado(caso),
            uso=uso_zerado("escrever_feedback"),
        ),
    )


def serializar(gravacao: Gravacao) -> str:
    return gravacao.model_dump_json(indent=2) + "\n"


def desatualizadas(dataset: Dataset, pasta: Path) -> list[str]:
    """Ids cujas gravações faltam ou diferem do que as anotações geram, mais as órfãs."""
    problemas: list[str] = []
    ids = set()
    for caso in dataset.casos:
        ids.add(caso.id)
        arquivo = pasta / f"{caso.id}.json"
        if not arquivo.is_file() or arquivo.read_text(encoding="utf-8") != serializar(
            gerar_gravacao(caso)
        ):
            problemas.append(caso.id)
    problemas += sorted(f"{p.stem} (órfã)" for p in pasta.glob("*.json") if p.stem not in ids)
    return problemas


def escrever_todas(dataset: Dataset, pasta: Path) -> int:
    pasta.mkdir(parents=True, exist_ok=True)
    for caso in dataset.casos:
        (pasta / f"{caso.id}.json").write_text(
            serializar(gerar_gravacao(caso)), encoding="utf-8", newline="\n"
        )
    return len(dataset.casos)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--verificar", action="store_true", help="só confere, não escreve")
    parser.add_argument("--raiz", type=Path, default=None, help="raiz do repositório")
    args = parser.parse_args(argv)
    raiz: Path = args.raiz or localizar_raiz()
    dataset = carregar_dataset(raiz / "evals")
    pasta = raiz / "evals" / "gravacoes"
    if args.verificar:
        problemas = desatualizadas(dataset, pasta)
        for problema in problemas:
            print(f"desatualizada: {problema}")
        return 1 if problemas else 0
    total = escrever_todas(dataset, pasta)
    print(f"{total} gravações escritas em {pasta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
