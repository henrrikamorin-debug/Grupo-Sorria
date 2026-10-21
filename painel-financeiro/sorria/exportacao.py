"""Exportação CSV das ocorrências filtradas (compatível com Excel em português)."""

from __future__ import annotations

import csv
import io
from datetime import datetime

from .regras.base import formatar_data

CABECALHO = [
    "Origem dos dados", "Clínica", "Código da filial", "Nº do título TOTVS", "Regra", "Descrição",
    "Valor (R$)", "Valor sem repetição (R$)", "Data", "Situação", "Primeira detecção",
]


def _reais(centavos: int | None) -> str:
    if centavos is None:
        return ""
    sinal = "-" if centavos < 0 else ""
    inteiro, resto = divmod(abs(centavos), 100)
    return f"{sinal}{inteiro},{resto:02d}"


def _seguro(texto) -> str:
    """Evita que o Excel interprete o conteúdo como fórmula."""
    texto = "" if texto is None else str(texto)
    if texto and texto[0] in "=+-@\t\r":
        return "'" + texto
    return texto


def _hora_local(iso: str | None) -> str:
    if not iso:
        return ""
    return datetime.fromisoformat(iso).astimezone().strftime("%d/%m/%Y %H:%M")


def gerar_csv(ocorrencias: list[dict], demonstracao: bool) -> bytes:
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";", lineterminator="\r\n")
    escritor.writerow(CABECALHO)
    origem = "DEMONSTRAÇÃO — DADOS FICTÍCIOS" if demonstracao else "Coleta TOTVS"
    vistos: set[str] = set()
    for o in ocorrencias:
        # A coluna "sem repetição" traz o valor só na primeira ocorrência de cada
        # lançamento, para que a soma da coluna não conte o mesmo valor duas vezes.
        primeira = o["referencia"] not in vistos
        vistos.add(o["referencia"])
        escritor.writerow([
            origem,
            _seguro(o["clinica"]),
            _seguro(o.get("filial") or ""),
            _seguro(o.get("titulo") or o["referencia"]),
            _seguro(f"{o['regra_codigo']} — {o['regra_nome']}"),
            _seguro(o["descricao"]),
            _reais(o["valor_centavos"]),
            _reais(o["valor_centavos"]) if primeira else "",
            formatar_data(o["data"]),
            o["situacao_rotulo"],
            _hora_local(o["primeira_deteccao"]),
        ])
    return ("﻿" + saida.getvalue()).encode("utf-8")
