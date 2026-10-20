"""Carregamento da configuração do painel.

A configuração padrão fica neste arquivo. Ajustes locais vão em ``config.json``
(na pasta do projeto, ou no caminho indicado pela variável ``SORRIA_CONFIG``).
Segredos (chaves de API, senhas do TOTVS) nunca ficam no arquivo de
configuração: são lidos de variáveis de ambiente cujo *nome* é configurado aqui.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

MODOS_VALIDOS = ("demonstracao", "real")

PADRAO: dict = {
    # "demonstracao" usa dados fictícios gerados localmente.
    # "real" usa somente o conector TOTVS configurado e as regras aprovadas.
    "modo": "demonstracao",
    "servidor": {
        # 127.0.0.1 = acessível apenas neste computador. Para exibir em outra
        # máquina da rede, troque para "0.0.0.0" (ver README, seção Segurança).
        "host": "127.0.0.1",
        "porta": 8750,
    },
    "coleta": {
        "habilitada": True,
        "intervalo_minutos": 10,
        "executar_ao_iniciar": True,
        # Após esse tempo sem coleta bem-sucedida o painel marca os dados
        # como desatualizados.
        "tolerancia_desatualizacao_minutos": 25,
        # Tempo máximo de uma coleta; também é a validade da trava que impede
        # execuções simultâneas.
        "tempo_maximo_minutos": 8,
        # Janela de lançamentos solicitada ao conector a cada coleta.
        "janela_dias": 120,
        # Uma coleta sem nenhum lançamento, logo após um retrato com dados,
        # costuma indicar problema na origem. Por segurança é tratada como
        # falha (preservando o retrato anterior), a menos que seja permitida.
        "aceitar_coleta_vazia": False,
    },
    "totvs": {
        # Ainda não definido: depende do produto TOTVS e da forma de acesso.
        "conector": "nao_configurado",
    },
    "televisao": {
        # A quantidade de linhas por página na TV é calculada pela altura da tela.
        "rotacao_tabela_segundos": 20,
    },
    "agente_ia": {
        "habilitado": False,
        "provedor": "anthropic",
        "modelo": "claude-opus-5-5",
        # Nome da variável de ambiente que contém a chave. A chave em si
        # nunca deve ser gravada neste arquivo nem no repositório.
        "variavel_chave_api": "ANTHROPIC_API_KEY",
        "max_tokens": 4000,
        "limite_chamadas_dia": 20,
        "max_ocorrencias_contexto": 40,
    },
}


def _mesclar(base: dict, extra: dict) -> dict:
    resultado = copy.deepcopy(base)
    for chave, valor in extra.items():
        if isinstance(valor, dict) and isinstance(resultado.get(chave), dict):
            resultado[chave] = _mesclar(resultado[chave], valor)
        else:
            resultado[chave] = valor
    return resultado


def caminho_config() -> Path:
    return Path(os.environ.get("SORRIA_CONFIG", RAIZ / "config.json"))


def carregar(caminho: Path | None = None) -> dict:
    caminho = caminho or caminho_config()
    config = copy.deepcopy(PADRAO)
    if caminho.exists():
        with open(caminho, encoding="utf-8") as arquivo:
            config = _mesclar(config, json.load(arquivo))
    validar(config)
    return config


def validar(config: dict) -> None:
    if config["modo"] not in MODOS_VALIDOS:
        raise ValueError(f"modo inválido: {config['modo']!r}; use {MODOS_VALIDOS}")
    intervalo = config["coleta"]["intervalo_minutos"]
    if not isinstance(intervalo, (int, float)) or intervalo < 1:
        raise ValueError("coleta.intervalo_minutos deve ser um número >= 1")
    if config["coleta"]["tempo_maximo_minutos"] <= 0:
        raise ValueError("coleta.tempo_maximo_minutos deve ser positivo")


def caminho_banco(config: dict) -> Path:
    """Cada modo tem seu próprio arquivo: dados fictícios e reais nunca se misturam."""
    pasta = Path(os.environ.get("SORRIA_DADOS", RAIZ / "dados"))
    return pasta / f"{config['modo']}.sqlite3"
