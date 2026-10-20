"""Motor de regras determinístico."""

from __future__ import annotations

import logging

from ..conectores.base import Lancamento
from .aprovadas import REGRAS_APROVADAS
from .base import Regra, id_ocorrencia
from .demonstracao import REGRAS_DEMONSTRACAO

log = logging.getLogger(__name__)


def regras_do_modo(modo: str) -> list[Regra]:
    # O modo real nunca usa regras ilustrativas.
    return list(REGRAS_DEMONSTRACAO) if modo == "demonstracao" else list(REGRAS_APROVADAS)


def analisar(lancamentos: list[Lancamento], referencias: dict, regras: list[Regra]) -> list[dict]:
    """Aplica as regras e devolve ocorrências únicas por (lançamento, regra)."""
    por_referencia = {l.referencia: l for l in lancamentos}
    ocorrencias: dict[str, dict] = {}
    for regra in regras:
        for achado in regra.verificar(lancamentos, referencias):
            lanc = por_referencia.get(achado.referencia)
            if lanc is None:
                log.warning("Regra %s apontou referência inexistente %s", regra.codigo, achado.referencia)
                continue
            chave = id_ocorrencia(lanc.referencia, regra.codigo)
            if chave in ocorrencias:
                continue
            ocorrencias[chave] = {
                "id": chave,
                "referencia": lanc.referencia,
                "regra_codigo": regra.codigo,
                "regra_nome": regra.nome,
                "descricao": achado.descricao,
                "evidencia": {
                    "resumo": achado.resumo_evidencia,
                    "condicao": regra.condicao,
                    "regra_aprovada": regra.aprovada,
                    "regra_ilustrativa": regra.ilustrativa,
                    "itens": [item.como_dict() for item in achado.itens],
                    "relacionados": achado.relacionados,
                },
                "clinica": lanc.clinica,
                "categoria": lanc.categoria,
                "data": lanc.data,
                "valor_centavos": lanc.valor_centavos,
            }
    return list(ocorrencias.values())
