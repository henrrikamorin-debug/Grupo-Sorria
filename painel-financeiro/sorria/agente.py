"""Interface com o agente financeiro de IA — DESATIVADA por padrão.

Princípios de economia:

* filtros, cálculos e regras ficam no código determinístico; a coleta
  periódica nunca chama IA;
* o agente só é chamado sob demanda (endpoint ``/api/agente/perguntar``);
* o contexto enviado é mínimo e sem dados pessoais ou bancários
  (indicadores agregados + lista resumida de ocorrências já mascaradas);
* respostas idênticas são reaproveitadas do cache local;
* cada chamada registra o consumo de tokens informado pela API em ``uso_ia``;
* há limite diário de chamadas.

Requisitos para ativar (nada disso vem da sessão ou assinatura do Claude Code):
uma conta na Claude Platform com API habilitada e faturamento, uma chave de
API em variável de ambiente (nome em ``agente_ia.variavel_chave_api``), o
pacote ``anthropic`` instalado e ``agente_ia.habilitado = true``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
from datetime import datetime, timezone

from . import db
from .analise import Filtros, montar_painel

log = logging.getLogger(__name__)

SISTEMA = (
    "Você é um assistente do setor financeiro do Grupo Sorria. Responda em português, "
    "de forma objetiva, usando somente os dados fornecidos no contexto. Os indicadores e "
    "ocorrências foram calculados por regras determinísticas; não recalcule valores nem "
    "invente lançamentos. Se o contexto indicar modo demonstração, deixe claro que os "
    "dados são fictícios. Se faltar informação, diga o que falta."
)


class AgenteIndisponivel(RuntimeError):
    pass


class AgenteFinanceiro:
    def __init__(self, config: dict):
        self.config = config
        self.cfg = config["agente_ia"]

    @property
    def habilitado(self) -> bool:
        return bool(self.cfg.get("habilitado"))

    def estado(self, conexao) -> dict:
        hoje = datetime.now(timezone.utc).date().isoformat()
        uso = conexao.execute(
            "SELECT COUNT(*) AS chamadas, COALESCE(SUM(tokens_entrada), 0) AS entrada, "
            "COALESCE(SUM(tokens_saida), 0) AS saida, COALESCE(SUM(reaproveitado), 0) AS reaproveitadas "
            "FROM uso_ia WHERE substr(em, 1, 10) = ?", (hoje,)).fetchone()
        return {
            "habilitado": self.habilitado,
            "provedor": self.cfg["provedor"],
            "modelo": self.cfg["modelo"],
            "variavel_chave_api": self.cfg["variavel_chave_api"],
            "variavel_definida": bool(os.environ.get(self.cfg["variavel_chave_api"])),
            "sdk_instalado": importlib.util.find_spec("anthropic") is not None,
            "limite_chamadas_dia": self.cfg["limite_chamadas_dia"],
            "uso_hoje_utc": dict(uso),
        }

    def contexto(self, conexao, filtros: Filtros) -> dict:
        """Dados mínimos para o agente: agregados e ocorrências mascaradas, sem evidências."""
        painel = montar_painel(conexao, filtros, tv=True)
        limite = int(self.cfg["max_ocorrencias_contexto"])
        return {
            "modo": self.config["modo"],
            "dados_ficticios": self.config["modo"] == "demonstracao",
            "filtros": painel["filtros"],
            "indicadores": painel["indicadores"],
            "por_clinica": painel["graficos"]["por_clinica"],
            "por_categoria": painel["graficos"]["por_categoria"],
            "ocorrencias_total": len(painel["ocorrencias"]),
            "ocorrencias_amostra": [
                {k: o[k] for k in ("referencia", "regra_codigo", "regra_nome", "descricao", "clinica",
                                   "categoria", "data", "valor_centavos", "situacao")}
                for o in painel["ocorrencias"][:limite]
            ],
            "observacao_valores": "valor_centavos em centavos de real; soma sem repetição por lançamento.",
        }

    def perguntar(self, conexao, pergunta: str, filtros: Filtros) -> dict:
        if not self.habilitado:
            raise AgenteIndisponivel("Agente de IA desativado (agente_ia.habilitado = false).")
        pergunta = (pergunta or "").strip()
        if not pergunta or len(pergunta) > 2000:
            raise ValueError("Pergunta vazia ou longa demais (máx. 2000 caracteres).")

        conteudo = db.json_dump({"pergunta": pergunta, "contexto": self.contexto(conexao, filtros)})
        modelo = self.cfg["modelo"]
        chave = hashlib.sha256(f"{modelo}|{SISTEMA}|{conteudo}".encode()).hexdigest()

        em_cache = conexao.execute("SELECT resposta FROM cache_ia WHERE hash = ?", (chave,)).fetchone()
        if em_cache:
            self._registrar(conexao, modelo, None, None, chave, reaproveitado=True)
            return {"resposta": em_cache["resposta"], "reaproveitada": True, "uso": None}

        hoje = datetime.now(timezone.utc).date().isoformat()
        chamadas = conexao.execute(
            "SELECT COUNT(*) FROM uso_ia WHERE reaproveitado = 0 AND substr(em, 1, 10) = ?",
            (hoje,)).fetchone()[0]
        if chamadas >= int(self.cfg["limite_chamadas_dia"]):
            raise AgenteIndisponivel("Limite diário de chamadas ao agente atingido.")

        texto, uso, recusada = self._chamar_api(modelo, conteudo)
        self._registrar(conexao, modelo, uso.get("entrada"), uso.get("saida"), chave, reaproveitado=False)
        if recusada:
            raise AgenteIndisponivel("O modelo recusou a solicitação.")
        conexao.execute("INSERT OR REPLACE INTO cache_ia (hash, modelo, resposta, criado_em) VALUES (?, ?, ?, ?)",
                        (chave, modelo, texto, db.agora_iso()))
        return {"resposta": texto, "reaproveitada": False, "uso": uso}

    def _chamar_api(self, modelo: str, conteudo: str) -> tuple[str, dict, bool]:
        if self.cfg["provedor"] != "anthropic":
            raise AgenteIndisponivel(f"Provedor não suportado: {self.cfg['provedor']}")
        try:
            import anthropic
        except ImportError as erro:
            raise AgenteIndisponivel("Pacote 'anthropic' não instalado (pip install anthropic).") from erro

        chave_api = os.environ.get(self.cfg["variavel_chave_api"])
        cliente = anthropic.Anthropic(api_key=chave_api) if chave_api else anthropic.Anthropic()
        try:
            resposta = cliente.beta.messages.create(
                model=modelo,
                max_tokens=int(self.cfg["max_tokens"]),
                system=SISTEMA,
                messages=[{"role": "user", "content": conteudo}],
                # Se o modelo recusar, a própria API tenta o modelo recomendado.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.APIConnectionError as erro:
            raise AgenteIndisponivel("Sem conexão com a API do agente.") from erro
        except anthropic.RateLimitError as erro:
            raise AgenteIndisponivel("Limite de uso da API atingido; tente mais tarde.") from erro
        except anthropic.APIStatusError as erro:
            raise AgenteIndisponivel(f"A API recusou a chamada (HTTP {erro.status_code}).") from erro

        uso = {"entrada": getattr(resposta.usage, "input_tokens", None),
               "saida": getattr(resposta.usage, "output_tokens", None)}
        if resposta.stop_reason == "refusal":
            return "", uso, True
        texto = "".join(bloco.text for bloco in resposta.content if bloco.type == "text").strip()
        return texto, uso, False

    @staticmethod
    def _registrar(conexao, modelo, entrada, saida, chave, reaproveitado: bool) -> None:
        conexao.execute(
            "INSERT INTO uso_ia (em, finalidade, modelo, tokens_entrada, tokens_saida, reaproveitado, hash_entrada) "
            "VALUES (?, 'pergunta', ?, ?, ?, ?, ?)",
            (db.agora_iso(), modelo, entrada, saida, int(reaproveitado), chave))
