"""O harness mede de verdade: com as gravações perfeitas as métricas ficam no máximo, e com uma
gravação corrompida de propósito as métricas correspondentes caem."""

import json
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from curriculo_api import ancoragem
from curriculo_api.config import Settings
from curriculo_api.evals.harness import Execucao, ResultadoMetrica
from curriculo_api.evals.pipeline import EntradaAnalise, PipelineCompleto, ResultadoAnalise
from curriculo_api.evals.rodar import (
    SAIDA_META_FALHOU,
    SAIDA_OK,
    SAIDA_PROVEDOR_INDISPONIVEL,
    criar_pipeline,
    encontrar_anterior,
    nome_do_resultado,
    rodar,
)
from curriculo_api.ia import ProvedorFalso
from curriculo_api.ia.modelos import CurriculoExtraido, Idioma

T1 = datetime(2026, 11, 15, 12, 0, 0, tzinfo=UTC)
T2 = datetime(2026, 11, 15, 12, 5, 0, tzinfo=UTC)
CASO = "b01-frontend-senior"

Json = dict[str, Any]


def _metricas(execucao: Execucao) -> dict[str, ResultadoMetrica]:
    return {m.chave: m for m in execucao.metricas}


def _ler_execucao(pasta: Path) -> Execucao:
    (arquivo,) = sorted(pasta.glob("*.json"))[-1:]
    return Execucao.model_validate_json(arquivo.read_text(encoding="utf-8"))


def _mini_repo(raiz_real: Path, destino: Path, casos: list[str]) -> Path:
    """Um repositório de mentira com só alguns casos e as gravações deles."""
    (destino / "evals" / "casos").mkdir(parents=True)
    (destino / "evals" / "gravacoes").mkdir()
    shutil.copy(raiz_real / "evals" / "dataset.yaml", destino / "evals" / "dataset.yaml")
    for caso in casos:
        shutil.copytree(raiz_real / "evals" / "casos" / caso, destino / "evals" / "casos" / caso)
        shutil.copy(
            raiz_real / "evals" / "gravacoes" / f"{caso}.json",
            destino / "evals" / "gravacoes" / f"{caso}.json",
        )
    return destino


def _corromper(repo: Path, caso: str, mudar: Callable[[Json], None]) -> None:
    arquivo = repo / "evals" / "gravacoes" / f"{caso}.json"
    dados: Json = json.loads(arquivo.read_text(encoding="utf-8"))
    mudar(dados["extrair_curriculo"]["saida"])
    arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def _pipeline_falso(repo: Path) -> PipelineCompleto:
    return criar_pipeline(ProvedorFalso(repo / "evals" / "gravacoes"), Settings())


def _rodar(repo: Path, agora: datetime = T1, **kwargs: Any) -> tuple[int, Execucao, list[str]]:
    saida: list[str] = []
    codigo = rodar(
        repo,
        "falso",
        pasta_resultados=repo / "resultados",
        caminho_relatorio=repo / "docs" / "evals.md",
        agora=agora,
        escrever=saida.append,
        **kwargs,
    )
    return codigo, _ler_execucao(repo / "resultados"), saida


# --- dataset completo, gravações perfeitas ------------------------------------------------------


@pytest.fixture(scope="module")
def execucao_perfeita(raiz: Path, tmp_path_factory: pytest.TempPathFactory) -> tuple[int, Path]:
    destino = tmp_path_factory.mktemp("perfeita")
    codigo = rodar(
        raiz,
        "falso",
        pasta_resultados=destino / "resultados",
        caminho_relatorio=destino / "evals.md",
        agora=T1,
        escrever=lambda _: None,
    )
    return codigo, destino


def test_gravacoes_perfeitas_dao_o_maximo(execucao_perfeita: tuple[int, Path]) -> None:
    codigo, destino = execucao_perfeita
    execucao = _ler_execucao(destino / "resultados")
    m = _metricas(execucao)
    assert codigo == SAIDA_OK
    assert len(execucao.casos) == 30
    assert m["ancoragem"].valor == 1.0 and m["ancoragem"].situacao == "passou"
    assert m["descartes"].valor == 0.0 and m["descartes"].situacao == "passou"
    assert m["precisao"].valor == 1.0 and m["precisao"].situacao == "passou"
    assert m["cobertura"].valor == 1.0 and m["cobertura"].situacao == "passou"
    assert not [k for k, v in m.items() if v.situacao == "pendente"]
    for chave in ("nota_na_faixa", "injection_diferenca", "contrafactual", "reescritas"):
        assert m[chave].situacao == "passou", chave
    assert m["nota_na_faixa"].valor == 1.0
    assert m["injection_diferenca"].valor == 0
    assert m["contrafactual"].valor == 0
    assert m["reescritas"].valor == 0
    # Três reescritas inventadas de propósito nas gravações (b02, b12, b13) foram descartadas.
    assert sum(c.reescritas_descartadas or 0 for c in execucao.casos if c.tipo == "base") == 3
    assert all(c.nota is not None for c in execucao.casos)
    assert m["injection_deteccao"].valor == 1.0
    assert m["injection_deteccao"].situacao == "passou"
    assert m["injection_falsos_positivos"].valor == 0
    assert m["injection_falsos_positivos"].situacao == "passou"
    assert m["anonimizacao"].valor == 1.0 and m["anonimizacao"].situacao == "passou"
    assert all(not c.dados_pessoais_restantes for c in execucao.casos)
    assert all(c.evidencias_perdidas == 0 for c in execucao.casos)
    assert {k for k, v in m.items() if v.situacao == "n/a"} == {"custo", "latencia_p95"}
    assert all(not c.a_mais and not c.faltando for c in execucao.casos)


def test_relatorio_tem_a_tabela_do_adr(execucao_perfeita: tuple[int, Path]) -> None:
    _, destino = execucao_perfeita
    relatorio = (destino / "evals.md").read_text(encoding="utf-8")
    assert "| # | Métrica | Meta | Atual | Anterior | Δ | Passou? |" in relatorio
    assert "| 3a | Precisão de competências extraídas | ≥ 0,90 | 1,00 | — | — | sim |" in relatorio
    assert "pendente (fase" not in relatorio and "n/a (falso)" in relatorio
    assert "| 4 | Nota dentro da faixa anotada | ≥ 90 % dos pares | 100,0 % |" in relatorio
    assert "pendente (fase 2)" not in relatorio
    assert "| 5 | Injection: detecção sinalizada | 100 % das variantes | 100,0 % |" in relatorio
    assert "| 11 | Anonimização: dados pessoais removidos | 100 % | 100,0 % |" in relatorio
    assert "Primeira execução deste provedor" in relatorio
    assert "`b01-frontend-senior`" in relatorio


def test_nome_do_resultado() -> None:
    assert nome_do_resultado(T1, "falso") == "2026-11-15T120000-falso.json"


# --- comparação com a execução anterior --------------------------------------------------------


def test_segunda_execucao_compara_com_a_primeira(raiz: Path, tmp_path: Path) -> None:
    repo = _mini_repo(raiz, tmp_path, [CASO, "b02-backend-pleno-node"])
    assert _rodar(repo, T1)[0] == SAIDA_OK
    _corromper(
        repo,
        CASO,
        lambda s: s["competencias"].append(
            {"nome": "code review", "trecho": "fluxo com Git e code review"}
        ),
    )
    codigo, execucao, saida = _rodar(repo, T2)
    relatorio = (repo / "docs" / "evals.md").read_text(encoding="utf-8")

    assert codigo == SAIDA_OK  # 20 de 21 ainda passa de 0,90
    assert any("Comparado com: resultados/2026-11-15T120000-falso.json" in s for s in saida)
    assert "`resultados/2026-11-15T120000-falso.json`" in relatorio
    assert "| 3a | Precisão de competências extraídas | ≥ 0,90 | 0,95 | 1,00 | -0,05 | sim |" in (
        relatorio
    )
    assert "| 3b | Cobertura de competências extraídas | ≥ 0,85 | 1,00 | 1,00 | +0,00 | sim |" in (
        relatorio
    )
    assert f"`{CASO}`: entraram code review; saíram —" in relatorio
    assert _metricas(execucao)["precisao"].valor == pytest.approx(20 / 21)


def test_anterior_ignora_outro_provedor_e_o_futuro(tmp_path: Path) -> None:
    for nome in ("2026-01-01T000000-falso.json", "2026-01-02T000000-anthropic.json"):
        (tmp_path / nome).write_text("{}", encoding="utf-8")
    # Ilegíveis são pulados; nada válido → None.
    assert encontrar_anterior(tmp_path, "falso", "2026-01-03T000000-falso.json") is None


# --- sanidade: gravação corrompida derruba a métrica certa ------------------------------------


@pytest.fixture
def repo_b01(raiz: Path, tmp_path: Path) -> Path:
    return _mini_repo(raiz, tmp_path, [CASO])


def test_competencias_inventadas_derrubam_a_precisao(repo_b01: Path) -> None:
    def inventar(saida: Json) -> None:
        # Itens que passam na ancoragem (o termo está no trecho) mas não estão no gabarito.
        saida["competencias"] += [
            {"nome": "code review", "trecho": "fluxo com Git e code review"},
            {"nome": "checkout", "trecho": "auditoria WCAG 2.2 do checkout"},
        ]

    _corromper(repo_b01, CASO, inventar)
    codigo, execucao, _ = _rodar(repo_b01)
    m = _metricas(execucao)
    assert codigo == SAIDA_META_FALHOU
    assert m["precisao"].valor == pytest.approx(11 / 13)
    assert m["precisao"].situacao == "falhou"
    assert m["cobertura"].valor == 1.0
    assert execucao.casos[0].a_mais == ("checkout", "code review")


def test_trecho_inexistente_e_descartado_e_conta(repo_b01: Path) -> None:
    def inventar_trecho(saida: Json) -> None:
        saida["competencias"][0]["trecho"] = "ReactJS em produção desde 2015"

    _corromper(repo_b01, CASO, inventar_trecho)
    codigo, execucao, _ = _rodar(repo_b01)
    m = _metricas(execucao)
    assert codigo == SAIDA_META_FALHOU
    assert m["descartes"].valor == pytest.approx(1 / 17)
    assert m["descartes"].situacao == "falhou"
    assert m["ancoragem"].valor == 1.0  # o descartado não entra entre os mantidos
    assert execucao.casos[0].faltando == ("React",)
    assert m["cobertura"].valor == pytest.approx(10 / 11)


def test_competencias_faltando_derrubam_a_cobertura(repo_b01: Path) -> None:
    def esquecer(saida: Json) -> None:
        saida["competencias"] = [
            c for c in saida["competencias"] if c["nome"] not in ("ReactJS", "TypeScript")
        ]

    _corromper(repo_b01, CASO, esquecer)
    codigo, execucao, _ = _rodar(repo_b01)
    m = _metricas(execucao)
    assert codigo == SAIDA_META_FALHOU
    assert m["cobertura"].valor == pytest.approx(9 / 11)
    assert m["cobertura"].situacao == "falhou"
    assert m["precisao"].valor == 1.0
    assert execucao.casos[0].faltando == ("React", "TypeScript")


class _PipelineSemFiltro:
    """Um pipeline com bug: mantém tudo o que a IA devolveu, sem ancorar."""

    def __init__(self, interno: PipelineCompleto) -> None:
        self._interno = interno

    @property
    def nome(self) -> str:
        return "sem-filtro"

    async def analisar(self, entrada: EntradaAnalise) -> ResultadoAnalise:
        r = await self._interno.analisar(entrada)
        return r.model_copy(update={"curriculo_mantido": r.curriculo_bruto})


def test_pipeline_sem_ancoragem_e_pego_pela_metrica_1(repo_b01: Path) -> None:
    def inventar_trecho(saida: Json) -> None:
        saida["experiencias"][0]["trecho"] = "Tech Lead — Vitrine Azul — 2015 – atual"

    _corromper(repo_b01, CASO, inventar_trecho)
    pipeline = _PipelineSemFiltro(_pipeline_falso(repo_b01))
    codigo, execucao, _ = _rodar(repo_b01, pipeline=pipeline)
    m = _metricas(execucao)
    assert codigo == SAIDA_META_FALHOU
    assert m["ancoragem"].valor == pytest.approx(16 / 17)
    assert m["ancoragem"].situacao == "falhou"
    assert execucao.casos[0].mantidos_sem_ancora == 1


def test_filtro_bugado_e_pego_pela_verificacao_independente(
    repo_b01: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A métrica 1 não usa `ancoragem.trecho_ancorado`: com o filtro quebrado (aceita tudo), o
    item inventado passa pelo pipeline e a métrica o pega."""

    def inventar_trecho(saida: Json) -> None:
        saida["competencias"][0]["trecho"] = "ReactJS em produção desde 2015"

    _corromper(repo_b01, CASO, inventar_trecho)
    monkeypatch.setattr(ancoragem, "trecho_ancorado", lambda _trecho, _texto: True)
    codigo, execucao, _ = _rodar(repo_b01)
    m = _metricas(execucao)
    assert codigo == SAIDA_META_FALHOU
    assert m["ancoragem"].valor == pytest.approx(16 / 17)
    assert m["ancoragem"].situacao == "falhou"
    assert m["descartes"].valor == 0.0  # o filtro bugado não descartou nada


class _PipelineQueMexeDepoisDoFiltro:
    """Acrescenta um item ancorado depois do filtro e remove outro sem ser por âncora."""

    def __init__(self, interno: PipelineCompleto, *, acrescentar: bool, remover: bool) -> None:
        self._interno = interno
        self._acrescentar = acrescentar
        self._remover = remover

    @property
    def nome(self) -> str:
        return "mexe-depois-do-filtro"

    async def analisar(self, entrada: EntradaAnalise) -> ResultadoAnalise:
        r = await self._interno.analisar(entrada)
        idiomas = list(r.curriculo_mantido.idiomas)
        if self._acrescentar:
            idiomas.append(Idioma(idioma="Inglês", nivel=None, trecho="Inglês — intermediário"))
        if self._remover:
            idiomas = idiomas[1:]
        mantido = r.curriculo_mantido.model_copy(update={"idiomas": tuple(idiomas)})
        return r.model_copy(update={"curriculo_mantido": mantido})


@pytest.mark.parametrize(("acrescentar", "remover"), [(True, False), (False, True), (True, True)])
def test_descartes_contam_so_o_que_o_filtro_descartou(
    repo_b01: Path, acrescentar: bool, remover: bool
) -> None:
    interno = _pipeline_falso(repo_b01)
    pipeline = _PipelineQueMexeDepoisDoFiltro(interno, acrescentar=acrescentar, remover=remover)
    codigo, execucao, _ = _rodar(repo_b01, pipeline=pipeline)
    m = _metricas(execucao)
    assert m["descartes"].valor == 0.0  # nunca negativo, e remoção sem âncora não conta
    assert m["descartes"].situacao == "passou"
    assert execucao.casos[0].itens_descartados == 0
    assert codigo == SAIDA_OK


def test_ancoragem_renumera_as_ligacoes_de_experiencia(repo_b01: Path) -> None:
    def inventar_trecho(saida: Json) -> None:
        saida["experiencias"][0]["trecho"] = "Tech Lead — inventada — 2015 – atual"

    _corromper(repo_b01, CASO, inventar_trecho)
    gravacao = json.loads(
        (repo_b01 / "evals" / "gravacoes" / f"{CASO}.json").read_text(encoding="utf-8")
    )
    bruto = CurriculoExtraido.model_validate(gravacao["extrair_curriculo"]["saida"])
    texto = (repo_b01 / "evals" / "casos" / CASO / "curriculo.md").read_text(encoding="utf-8")
    resultado = ancoragem.ancorar(bruto, texto)
    assert len(resultado.descartados) == 1
    assert len(resultado.mantido.experiencias) == 2
    por_nome = {c.nome: c.experiencias for c in resultado.mantido.competencias}
    assert por_nome["Next.js"] == ()  # só aparecia na experiência descartada
    assert por_nome["ReactJS"] == (0,)  # era a 1, virou a 0
    assert por_nome["jQuery"] == (1,)  # era a 2, virou a 1


def test_gravacao_ausente_vira_erro_do_caso(repo_b01: Path) -> None:
    (repo_b01 / "evals" / "casos" / CASO / "curriculo.md").write_text(
        "# Outra pessoa\n\n## Resumo\n\nNada a ver.\n", encoding="utf-8"
    )
    codigo, execucao, saida = _rodar(repo_b01)
    assert codigo == SAIDA_META_FALHOU
    assert execucao.casos[0].erro is not None and "sha256" in execucao.casos[0].erro
    assert any(s.startswith(f"  erro em {CASO}") for s in saida)


def test_provedor_real_sai_com_mensagem_clara(repo_b01: Path) -> None:
    saida: list[str] = []
    codigo = rodar(
        repo_b01, "anthropic", escrever=saida.append, settings=Settings(anthropic_api_key=None)
    )
    assert codigo == SAIDA_PROVEDOR_INDISPONIVEL
    assert len(saida) == 1 and "ANTHROPIC_API_KEY" in saida[0] and "PROVEDOR=falso" in saida[0]
    assert not (repo_b01 / "evals" / "resultados").exists()
