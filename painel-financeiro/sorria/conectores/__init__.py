from __future__ import annotations

from .base import Conector, ConectorNaoConfigurado, Lancamento, ResultadoColeta
from .demonstracao import ConectorDemonstracao
from .totvs import ConectorTotvsPendente

# Conectores reais disponíveis, por nome usado em config.json -> totvs.conector.
CONECTORES_REAIS: dict[str, type[Conector]] = {
    "nao_configurado": ConectorTotvsPendente,
}


def criar_conector(config: dict) -> Conector:
    if config["modo"] == "demonstracao":
        # Com o cadastro de filiais importado, a demonstração usa as filiais
        # e tickets reais (com valores e ocorrências fictícios).
        from ..cadastros import carregar_filiais
        from ..config import caminho_filiais
        return ConectorDemonstracao(filiais=carregar_filiais(caminho_filiais()))
    nome = config["totvs"].get("conector", "nao_configurado")
    if nome not in CONECTORES_REAIS:
        raise ValueError(f"conector TOTVS desconhecido: {nome!r}")
    return CONECTORES_REAIS[nome]()


__all__ = [
    "Conector", "ConectorNaoConfigurado", "Lancamento", "ResultadoColeta",
    "criar_conector",
]
