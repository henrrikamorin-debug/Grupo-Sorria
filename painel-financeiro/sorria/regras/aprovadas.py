"""Regras APROVADAS pelo financeiro — usadas no modo real.

Ainda vazia: as regras serão escritas a partir das gravações de tela e áudios
que descrevem a conferência no TOTVS. Cada regra só entra nesta lista depois de
validada contra exemplos conferidos manualmente (ver docs/REGRAS.md).

Modelo:

    def _minha_verificacao(lancamentos, referencias):
        return [Achado(referencia=..., descricao=..., resumo_evidencia=..., itens=[...])]

    Regra(
        codigo="FIN-01",
        nome="...",
        condicao="...",
        campos=["..."],
        excecoes="...",
        exemplo="...",
        verificar=_minha_verificacao,
        aprovada=True,
    )
"""

from __future__ import annotations

from .base import Regra

REGRAS_APROVADAS: list[Regra] = []
