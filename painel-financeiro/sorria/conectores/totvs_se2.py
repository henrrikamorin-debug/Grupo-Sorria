"""Conector real: títulos de Contas a Pagar (SE2) importados pelo agente TOTVS.

O painel não acessa o TOTVS diretamente. O agente importa a exportação da
Consulta Genérica para a tabela ``titulos_pagar``; este conector lê essa
tabela e entrega os títulos ao motor de regras e ao painel.

A data de referência no painel é o VENCIMENTO (o mesmo campo do filtro da
consulta). O valor é o valor do título; o saldo aparece à parte e só quando a
exportação o trouxe.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .. import db
from .base import Conector, ConectorNaoConfigurado, Lancamento, ResultadoColeta


class SemImportacao(ConectorNaoConfigurado):
    pass


class ConectorTotvsSE2(Conector):
    nome = "TOTVS SE2 — Contas a Pagar (agente)"
    simulado = False

    def __init__(self, caminho_banco: Path, contratos: list | None = None):
        self.caminho_banco = caminho_banco
        self.contratos = contratos or []

    def descricao(self) -> dict:
        with db.fechando(db.conectar(self.caminho_banco)) as conexao:
            existe = conexao.execute(
                "SELECT 1 FROM importacoes WHERE situacao = 'importada' LIMIT 1").fetchone()
        return {"nome": self.nome, "simulado": False, "configurado": True, "se2": True,
                "com_importacao": bool(existe)}

    def coletar(self, inicio: date, fim: date) -> ResultadoColeta:
        # Títulos com vencimento a partir do início da janela, inclusive os que vencem
        # depois de hoje (o filtro do TOTVS é o mês inteiro).
        with db.fechando(db.conectar(self.caminho_banco)) as conexao:
            if not conexao.execute("SELECT 1 FROM importacoes WHERE situacao = 'importada' LIMIT 1").fetchone():
                raise SemImportacao("Aguardando a primeira importação do agente TOTVS (Contas a Pagar).")
            linhas = conexao.execute(
                "SELECT t.*, i.arquivo_nome FROM titulos_pagar t LEFT JOIN importacoes i ON i.id = t.ultima_importacao "
                "WHERE t.vencimento >= ? ORDER BY t.vencimento, t.chave", (inicio.isoformat(),)).fetchall()
        lancamentos = []
        for t in linhas:
            numero = t["numero"] + (f"/{t['parcela']}" if t["parcela"] else "")
            lancamentos.append(Lancamento(
                referencia=t["chave"],
                clinica="" if t["filial_cadastrada"] else f"Pendente de classificação ({t['filial']})",
                categoria="",
                data=t["vencimento"],
                valor_centavos=t["valor_centavos"],
                descricao=f"Título {t['prefixo'] + ' ' if t['prefixo'] else ''}{numero}".strip(),
                favorecido=t["nome_fornecedor"] or None,
                filial=t["filial"],
                titulo=numero,
                prefixo=t["prefixo"],
                restrito=bool(t["restrito"]),
                extras={
                    "fornecedor": t["fornecedor"], "loja": t["loja"], "natureza": t["natureza"],
                    "tipo": t["tipo"], "parcela": t["parcela"], "emissao": t["emissao"],
                    "vencimento": t["vencimento"], "vencimento_real": t["vencimento_real"],
                    "saldo_centavos": t["saldo_centavos"], "baixa": t["baixa"],
                    "situacao_titulo": t["situacao_titulo"], "motivo_restricao": t["motivo_restricao"],
                    "filial_cadastrada": bool(t["filial_cadastrada"]),
                    "campos_vazios": json.loads(t["campos_vazios"] or "[]"),
                    "historico": t["historico"], "importacao": t["ultima_importacao"],
                    "arquivo": t["arquivo_nome"],
                },
            ))
        return ResultadoColeta(lancamentos=lancamentos, simulada=False,
                               referencias={"contratos": self.contratos},
                               observacao="Títulos importados da exportação SE2 do TOTVS.")
