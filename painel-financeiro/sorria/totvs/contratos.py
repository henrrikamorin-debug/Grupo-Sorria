"""Cadastro de contratos para conferir cobranças (opcional).

Nenhuma condição contratual é deduzida dos lançamentos: só vale o que estiver
neste cadastro, preenchido a partir do documento, com o trecho de origem de
cada condição. Sem contrato para o fornecedor, a análise registra
"Contrato não disponibilizado" e segue apenas com a conferência financeira.

Arquivo: ``dados/contratos/contratos.json`` (fora do repositório), lista de:

    {
      "fornecedor": "000123", "loja": "01",              # códigos do TOTVS (loja opcional)
      "documento": "Contrato_Laboratorio_2026.pdf",
      "vigencia_inicio": "2026-01-01", "vigencia_fim": "2026-12-31",
      "valor_centavos": 1250000, "tolerancia_centavos": 0,
      "dia_vencimento": 10,
      "reajuste": {"data": "2027-01-01", "indice": "IPCA"},
      "trechos": {"vigencia": "Cláusula 2.1 ...", "valor": "Cláusula 4.1 ...",
                  "vencimento": "Cláusula 4.3 ...", "reajuste": "Cláusula 5.1 ..."}
    }
"""

from __future__ import annotations

import json
from pathlib import Path

NAO_DISPONIBILIZADO = "Contrato não disponibilizado"


def carregar(caminho: Path) -> list[dict]:
    if not caminho.exists():
        return []
    with open(caminho, encoding="utf-8") as arquivo:
        contratos = json.load(arquivo)
    if not isinstance(contratos, list):
        raise ValueError("contratos.json deve conter uma lista de contratos.")
    for contrato in contratos:
        for campo in ("fornecedor", "documento"):
            if not contrato.get(campo):
                raise ValueError(f"Contrato sem '{campo}' em contratos.json.")
    return contratos


def contrato_do_titulo(contratos: list[dict], fornecedor: str, loja: str, vencimento: str) -> dict | None:
    candidatos = [c for c in contratos if str(c["fornecedor"]) == fornecedor
                  and (not c.get("loja") or str(c["loja"]) == loja)]
    vigentes = [c for c in candidatos
                if (c.get("vigencia_inicio") or "0000") <= vencimento <= (c.get("vigencia_fim") or "9999")]
    return (vigentes or candidatos or [None])[0]


def divergencias(contrato: dict, valor_centavos: int, vencimento: str) -> list[tuple[str, str, str]]:
    """Lista de (conclusão, campo do contrato, trecho). Só compara o que o contrato informa."""
    trechos = contrato.get("trechos", {})
    achados = []
    inicio, fim = contrato.get("vigencia_inicio"), contrato.get("vigencia_fim")
    if (inicio and vencimento < inicio) or (fim and vencimento > fim):
        achados.append((f"Vencimento fora da vigência ({inicio or '…'} a {fim or '…'})", "vigencia",
                        trechos.get("vigencia", "trecho não informado")))
    if contrato.get("valor_centavos") is not None:
        tolerancia = int(contrato.get("tolerancia_centavos") or 0)
        if abs(valor_centavos - int(contrato["valor_centavos"])) > tolerancia:
            reajuste = contrato.get("reajuste") or {}
            observacao = (f"; reajuste previsto em {reajuste.get('data')} ({reajuste.get('indice', 'índice não informado')})"
                          if reajuste.get("data") and vencimento >= reajuste["data"] else "")
            achados.append((f"Valor cobrado difere do contratado{observacao}", "valor",
                            trechos.get("valor", "trecho não informado")))
    if contrato.get("dia_vencimento") and int(vencimento[8:10]) != int(contrato["dia_vencimento"]):
        achados.append((f"Vencimento no dia {vencimento[8:10]}, contrato prevê dia {contrato['dia_vencimento']}",
                        "vencimento", trechos.get("vencimento", "trecho não informado")))
    return achados
