"""Estrutura das regras de conferência.

Toda regra é código determinístico: recebe os lançamentos do retrato e devolve
as ocorrências encontradas, cada uma com a evidência que a originou. Nenhuma
regra chama modelo de IA.

Cada regra documenta condição, campos necessários, exceções e exemplo — o
mesmo formato que será usado para transformar as explicações das gravações e
áudios em regras aprovadas.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable

from ..conectores.base import Lancamento


@dataclass
class ItemEvidencia:
    campo: str
    valor: str
    sensivel: bool = False  # ocultado no modo televisão

    def como_dict(self) -> dict:
        return {"campo": self.campo, "valor": self.valor, "sensivel": self.sensivel}


@dataclass
class Achado:
    """Resultado bruto de uma regra para um lançamento."""
    referencia: str
    descricao: str
    resumo_evidencia: str
    itens: list[ItemEvidencia] = field(default_factory=list)
    relacionados: list[str] = field(default_factory=list)


@dataclass
class Regra:
    codigo: str
    nome: str
    condicao: str
    campos: list[str]
    excecoes: str
    exemplo: str
    verificar: Callable[[list[Lancamento], dict], list[Achado]]
    aprovada: bool = False
    ilustrativa: bool = False

    def metadados(self) -> dict:
        return {
            "codigo": self.codigo, "nome": self.nome, "condicao": self.condicao,
            "campos": self.campos, "excecoes": self.excecoes, "exemplo": self.exemplo,
            "aprovada": self.aprovada, "ilustrativa": self.ilustrativa,
        }


def id_ocorrencia(referencia: str, codigo_regra: str) -> str:
    """Identificação estável: o mesmo lançamento + mesma regra = mesma ocorrência."""
    return hashlib.sha1(f"{codigo_regra}|{referencia}".encode()).hexdigest()[:16]


def formatar_reais(centavos: int | None) -> str:
    if centavos is None:
        return "não informado"
    sinal = "-" if centavos < 0 else ""
    inteiro, resto = divmod(abs(centavos), 100)
    return f"{sinal}R$ {inteiro:,}".replace(",", ".") + f",{resto:02d}"


def formatar_data(iso: str | None) -> str:
    if not iso:
        return "não informada"
    ano, mes, dia = iso[:10].split("-")
    return f"{dia}/{mes}/{ano}"
