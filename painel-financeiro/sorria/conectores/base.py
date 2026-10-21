"""Contrato entre a coleta (TOTVS ou demonstração) e o restante do sistema.

O painel, as regras e a exportação conhecem apenas ``Lancamento`` e
``ResultadoColeta``. Trocar a origem dos dados significa escrever um novo
conector que devolva esses objetos; nada na apresentação precisa mudar.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date


@dataclass
class Lancamento:
    referencia: str                 # chave única do lançamento na origem
    clinica: str                    # vazio: preenchido pelo cadastro de filiais
    categoria: str                  # vazio: definida pelo prefixo do título
    data: str                       # AAAA-MM-DD (data de referência do lançamento)
    valor_centavos: int | None      # None quando a origem não informa valor
    descricao: str = ""
    favorecido: str | None = None
    pessoa_fisica: bool = False     # favorecido é pessoa física (dado pessoal)
    documento: str | None = None    # CPF/CNPJ — dado sensível
    dados_bancarios: str | None = None  # banco/agência/conta — dado sensível
    filial: str | None = None       # código da filial no TOTVS (ex.: "016501")
    titulo: str | None = None       # número do título no TOTVS, exibido como referência
    prefixo: str | None = None      # prefixo do título; define a categoria
    responsavel: str | None = None  # quem cuida da filial (resolvido pelo cadastro)
    extras: dict = field(default_factory=dict)  # demais campos da origem


@dataclass
class ResultadoColeta:
    lancamentos: list[Lancamento]
    simulada: bool
    # Dados auxiliares usados pelas regras (ex.: cadastro de fornecedores).
    referencias: dict = field(default_factory=dict)
    observacao: str = ""


class ConectorNaoConfigurado(RuntimeError):
    """A integração ainda não foi configurada; nenhuma coleta real é possível."""


class Conector(ABC):
    nome: str = "base"
    simulado: bool = False

    @abstractmethod
    def coletar(self, inicio: date, fim: date) -> ResultadoColeta:
        """Lê os lançamentos do período. Nunca altera dados na origem."""

    def descricao(self) -> dict:
        return {"nome": self.nome, "simulado": self.simulado, "configurado": True}
