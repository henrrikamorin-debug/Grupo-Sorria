"""Ocultação de dados pessoais e bancários no modo televisão.

A ocultação é feita no servidor: no modo televisão, esses dados nem chegam ao
navegador da TV. Há duas camadas:

1. campos da evidência marcados como ``sensivel`` são substituídos;
2. qualquer texto livre passa por um filtro de padrões (CPF, CNPJ, agência,
   conta, e-mail, telefone) como proteção adicional.
"""

from __future__ import annotations

import re

OCULTO = "oculto no modo TV"

_PADROES = [
    re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),                  # CPF
    re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"),           # CNPJ
    re.compile(r"\b(?:ag(?:ência|encia)?\.?|cc|c/c|conta)\s*[:nº°]*\s*[\d.\-/ ]{3,}\d",
               re.IGNORECASE),                                         # agência/conta
    re.compile(r"\bbanco\s+\d{3}\b", re.IGNORECASE),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),                           # e-mail
    re.compile(r"\(?\b\d{2}\)?\s?9?\d{4}-?\d{4}\b"),                  # telefone
    re.compile(r"\bchave\s+pix\b.*", re.IGNORECASE),
]


def limpar_texto(texto: str | None) -> str | None:
    if not texto:
        return texto
    for padrao in _PADROES:
        texto = padrao.sub("•••", texto)
    return texto


def mascarar_evidencia(evidencia: dict) -> dict:
    itens = []
    for item in evidencia.get("itens", []):
        if item.get("sensivel"):
            itens.append({**item, "valor": OCULTO})
        else:
            itens.append({**item, "valor": limpar_texto(item.get("valor"))})
    return {**evidencia, "resumo": limpar_texto(evidencia.get("resumo")), "itens": itens}


def mascarar_ocorrencia(ocorrencia: dict) -> dict:
    return {
        **ocorrencia,
        "descricao": limpar_texto(ocorrencia.get("descricao")),
        "evidencia": mascarar_evidencia(ocorrencia.get("evidencia", {})),
    }
