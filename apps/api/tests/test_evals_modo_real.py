"""Modo real das evals sem rede: `CASOS`, `TETO_USD` (aborta antes de passar do teto), mensagens
sem chave e `make calibrar-tau`. O SDK é o cliente falso de `sdk_falso.py`."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from curriculo_api.config import Settings
from curriculo_api.evals import calibrar_tau
from curriculo_api.evals.dataset import Dataset
from curriculo_api.evals.gravacoes import gerar_gravacao
from curriculo_api.evals.harness import executar
from curriculo_api.evals.pipeline import ingerir_caso
from curriculo_api.evals.rodar import (
    MENSAGEM_SEM_TETO,
    SAIDA_PROVEDOR_INDISPONIVEL,
    criar_pipeline,
    rodar,
    selecionar_casos,
)
from curriculo_api.ia.anthropic import ConfigAnthropic, ProvedorAnthropic
from curriculo_api.ia.falso import ProvedorFalso
from curriculo_api.ia.orcamento import Orcamento
from curriculo_api.taxonomia import Taxonomia
from sdk_falso import Chamada, ClienteFalso, RespostaFluxo, mensagem, uso

T = datetime(2026, 11, 16, 9, 0, 0, tzinfo=UTC)


def test_casos_por_prefixo_e_desconhecidos(dataset: Dataset) -> None:
    escolhido = selecionar_casos(dataset, "b02, b01,b01-frontend-senior")
    assert [c.id for c in escolhido.casos] == ["b01-frontend-senior", "b02-backend-pleno-node"]
    assert selecionar_casos(dataset, None) is dataset
    with pytest.raises(ValueError, match="z99"):
        selecionar_casos(dataset, "b01,z99")


def test_sem_chave_mensagem_clara_e_nada_gravado(raiz: Path, tmp_path: Path) -> None:
    saida: list[str] = []
    codigo = rodar(
        raiz,
        "anthropic",
        pasta_resultados=tmp_path / "res",
        caminho_relatorio=tmp_path / "evals.md",
        escrever=saida.append,
        casos="b01,b02",
        teto_usd="2.00",
        settings=Settings(anthropic_api_key=None),
    )
    assert codigo == SAIDA_PROVEDOR_INDISPONIVEL
    assert len(saida) == 1 and "ANTHROPIC_API_KEY não está definida" in saida[0]
    assert not (tmp_path / "res").exists() and not (tmp_path / "evals.md").exists()


def test_real_exige_teto(raiz: Path, tmp_path: Path) -> None:
    saida: list[str] = []
    codigo = rodar(
        raiz,
        "anthropic",
        pasta_resultados=tmp_path / "res",
        escrever=saida.append,
        casos="b01",
        settings=Settings(anthropic_api_key=SecretStr("sk-ant-teste-sem-rede")),
    )
    assert codigo == SAIDA_PROVEDOR_INDISPONIVEL and saida == [MENSAGEM_SEM_TETO]
    assert not (tmp_path / "res").exists()


def test_casos_invalidos_e_teto_invalido(raiz: Path, tmp_path: Path) -> None:
    exemplos: list[tuple[dict[str, Any], str]] = [
        ({"casos": "x1"}, "x1"),
        ({"teto_usd": "-1"}, "positivo"),
    ]
    for kwargs, trecho in exemplos:
        saida: list[str] = []
        codigo = rodar(raiz, "falso", pasta_resultados=tmp_path, escrever=saida.append, **kwargs)
        assert codigo == SAIDA_PROVEDOR_INDISPONIVEL and trecho in saida[0]


def test_subconjunto_com_o_falso_marca_sem_casos(raiz: Path, tmp_path: Path) -> None:
    saida: list[str] = []
    codigo = rodar(
        raiz,
        "falso",
        pasta_resultados=tmp_path / "res",
        caminho_relatorio=tmp_path / "evals.md",
        agora=T,
        escrever=saida.append,
        casos="b01,b02",
    )
    assert codigo == 0
    relatorio = (tmp_path / "evals.md").read_text(encoding="utf-8")
    assert "n/a (sem casos)" in relatorio  # injection e contrafactual não rodaram
    assert "| `b01-frontend-senior` |" in relatorio and "`c01" not in relatorio


class _ClienteDasGravacoes(ClienteFalso):
    """Responde como o modelo responderia, com as saídas das gravações, escolhidas pelo texto
    anonimizado que aparece na mensagem; o uso é fixo e alto no feedback."""

    def __init__(self, dataset: Dataset) -> None:
        super().__init__()
        self._casos = [(ingerir_caso(c), gerar_gravacao(c)) for c in dataset.casos]

    def _achar(self, kwargs: dict[str, Any]) -> Any:
        usuario = "\n".join(c["text"] for m in kwargs["messages"] for c in m["content"])
        for (curriculo, vaga), gravacao in self._casos:
            if curriculo.texto_para_ia.strip() in usuario:
                return gravacao, "curriculo"
            if vaga.texto.strip() in usuario:
                return gravacao, "vaga"
        raise AssertionError("mensagem sem caso conhecido")

    async def _create(self, **kwargs: Any) -> Any:
        self.chamadas.append(Chamada("create", kwargs, {}))
        gravacao, etapa = self._achar(kwargs)
        saida: Any = (
            gravacao.extrair_curriculo.saida
            if etapa == "curriculo"
            else gravacao.extrair_vaga.saida
        )
        return mensagem(saida.model_dump_json(), usage=uso(3000, 800))

    def _stream_beta(self, **kwargs: Any) -> Any:
        gravacao, _ = self._achar(kwargs)
        final = mensagem(
            gravacao.escrever_feedback.saida.model_dump_json(),
            modelo="claude-opus-5-5",
            usage=uso(6000, 10_000),
        )
        self.fluxos.append(RespostaFluxo(final))
        return super()._stream_beta(**kwargs)


def test_teto_da_execucao_aborta_antes_de_passar(dataset: Dataset, taxonomia: Taxonomia) -> None:
    subconjunto = selecionar_casos(dataset, "b01,b02,b03")
    cliente = _ClienteDasGravacoes(subconjunto)
    provedor = ProvedorAnthropic(
        cliente, taxonomia, ConfigAnthropic(estimar_com_count_tokens=False)
    )
    teto = Decimal("0.68")  # cabe o b01 inteiro; o feedback do b02 (pior caso com fallback) não
    orcamento = Orcamento(teto, escopo="execucao")
    pipeline = criar_pipeline(provedor, Settings(anthropic_api_key=SecretStr("x")), orcamento)
    execucao = asyncio.run(
        executar(
            subconjunto,
            pipeline,
            taxonomia,
            provedor="anthropic",
            inicio=T,
            git="teste",
            modelos={"extracao": "claude-haiku-5-5", "feedback": "claude-opus-5-5"},
            esforco={"extracao": "low", "feedback": "medium"},
            tau={"alto": 0.85, "baixo": 0.70},
            guardar_extracoes=True,
        )
    )
    b01, b02, b03 = execucao.casos
    assert b01.erro is None and b01.nota == 90
    assert b01.custo_usd is not None and b01.custo_usd > 0 and b01.chamadas == 3
    assert b01.modelos == ("claude-haiku-5-5", "claude-opus-5-5")
    assert b01.esforco == {"extracao": "low", "feedback": "medium"}
    assert b01.tau == {"alto": 0.85, "baixo": 0.70} and b01.extracao is not None
    assert b02.erro is not None and "teto de custo desta execução" in b02.erro
    assert b03.erro == "não rodou: a execução parou no teto de custo (TETO_USD)"
    assert orcamento.gasto <= teto and orcamento.reservado == 0
    assert len(cliente.das("beta.stream")) == 1  # o feedback do b02 nunca foi chamado
    assert not execucao.passou


def test_calibrar_tau_com_extracoes(
    raiz: Path, dataset: Dataset, taxonomia: Taxonomia, tmp_path: Path
) -> None:
    from curriculo_api.analise.embeddings import EmbutidorFalso

    base = selecionar_casos(dataset, "b01,b02,b14")
    pipeline = criar_pipeline(ProvedorFalso(raiz / "evals" / "gravacoes"), Settings())
    execucao = asyncio.run(
        executar(
            base,
            pipeline,
            taxonomia,
            provedor="anthropic",  # finge uma execução real para guardar as extrações
            inicio=T,
            git="teste",
            modelos={},
            esforco=None,
            tau={"alto": 0.85, "baixo": 0.70},
            guardar_extracoes=True,
        )
    )
    pontos = calibrar_tau.calibrar(execucao, dataset, taxonomia, EmbutidorFalso())
    atual = next(p for p in pontos if (p.alto, p.baixo) == (0.85, 0.70))
    assert atual.status_certos == atual.requisitos == 23
    assert atual.na_faixa == atual.pares_base == 3
    assert all(p.baixo <= p.alto for p in pontos)
    linhas = calibrar_tau.formatar(pontos, (0.85, 0.70))
    assert any("atual" in linha for linha in linhas)

    arquivo = tmp_path / "2026-11-16T090000-anthropic.json"
    arquivo.write_text(execucao.model_dump_json(), encoding="utf-8")
    saida: list[str] = []
    codigo = calibrar_tau.main(
        ["--raiz", str(raiz), "--resultado", str(arquivo)],
        escrever=saida.append,
        embutidor=EmbutidorFalso(),
    )
    assert codigo == calibrar_tau.SAIDA_OK
    assert saida[0].startswith("Calibração de τ com 2026-11-16T090000-anthropic.json")
    assert any("| 0.85 | 0.70 |" in linha and "atual" in linha for linha in saida)


def test_calibrar_tau_sem_execucao_real(tmp_path: Path) -> None:
    (tmp_path / "evals" / "resultados").mkdir(parents=True)
    saida: list[str] = []
    codigo = calibrar_tau.main(["--raiz", str(tmp_path)], escrever=saida.append)
    assert codigo == calibrar_tau.SAIDA_SEM_EXECUCAO_REAL
    assert "make eval PROVEDOR=anthropic" in saida[0]
