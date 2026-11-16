"""Erros da análise com mensagem que pode ir para a tela (nunca cita conteúdo do currículo)."""

from __future__ import annotations


class ErroAnalise(Exception):
    codigo = "erro_analise"

    def __init__(self, mensagem: str) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem


class VagaSemRequisitos(ErroAnalise):
    codigo = "vaga_sem_requisitos"

    def __init__(self) -> None:
        super().__init__("a vaga não tem requisitos reconhecíveis")
