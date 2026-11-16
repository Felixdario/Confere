from pathlib import Path

import pytest

from curriculo_api.evals.dataset import Dataset, carregar_dataset, localizar_raiz
from curriculo_api.taxonomia import Taxonomia, carregar_taxonomia


@pytest.fixture(scope="session")
def raiz() -> Path:
    return localizar_raiz()


@pytest.fixture(scope="session")
def dataset(raiz: Path) -> Dataset:
    return carregar_dataset(raiz / "evals")


@pytest.fixture(scope="session")
def taxonomia() -> Taxonomia:
    return carregar_taxonomia()
