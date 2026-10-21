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
        # "se2_consulta_generica": o painel (modo real) lê os títulos de Contas a
        # Pagar importados pelo agente a partir do Exp. CSV da Consulta Genérica.
        "conector": "se2_consulta_generica",
        "endereco_webapp": "https://escritorio135422.protheus.cloudtotvs.com.br:4010/webapp/",
    },
    "agente": {
        # "navegador": o agente opera o TOTVS WebApp no Chrome (sorria/totvs/navegador.py)
        # e captura o download. "pasta": só aguarda um CSV salvo na pasta de entrada.
        "modo_coleta": "navegador",
        # Filiais que a exportação deve abranger. Vazio = todas as filiais do cadastro.
        "filiais_esperadas": [],
        # Pasta onde a exportação (Exp. CSV) deve ser salva. Vazio = dados/totvs/entrada.
        "pasta_entrada": "",
        "padrao_arquivo": "*.csv",
        # Espera pela exportação durante uma execução.
        "tempo_espera_minutos": 20,
        "intervalo_verificacao_segundos": 5,
        # O arquivo só é considerado pronto quando o tamanho fica estável por este tempo.
        "segundos_tamanho_estavel": 4,
        "tolerancia_relogio_segundos": 120,
        # Importação manual: arquivos mais antigos exigem confirmação explícita.
        "idade_maxima_horas": 12,
        "max_percentual_linhas_rejeitadas": 5,
        "tamanho_codigo_filial": 6,
        # Tentativas para falhas temporárias (arquivo travado, banco ocupado).
        "tentativas": 3,
        "espera_entre_tentativas_segundos": 30,
        "tempo_maximo_execucao_minutos": 40,
        # Sem horários definidos o agendamento não é criado.
        "agendamento": {"ativo": False, "horarios": []},
        # Após este tempo sem importação válida o painel avisa "dados desatualizados".
        "tolerancia_desatualizacao_horas": 26,
        # Verificações objetivas de Contas a Pagar (em validação, ver docs/AGENTE_TOTVS.md).
        "verificacoes_se2": True,
    },
    "navegador": {
        # Chrome dedicado ao agente: perfil próprio (dados/navegador/perfil) e porta de
        # controle aberta só neste computador. A sessão do TOTVS fica aberta nessa janela.
        "executavel": "",  # vazio = procura o Google Chrome instalado
        "porta_controle": 9333,
        "argumentos_extras": [],
        # Espera pelo login no TOTVS (feito por uma pessoa; o agente nunca digita senha).
        "tempo_login_minutos": 15,
        "tempo_passo_segundos": 60,
        "tempo_exportacao_minutos": 10,
        # Capturas de tela e textos de cada etapa (podem conter dados confidenciais;
        # ficam em dados/totvs/diagnostico e são apagados após "dias_diagnostico").
        "diagnostico": "falha",  # "falha" | "sempre" | "nunca"
        "dias_diagnostico": 7,
        # Textos da tela usados em cada etapa. O agente só clica em elementos cujo texto
        # esteja nesta lista e nunca em ações de alteração (ver ACOES_PROIBIDAS).
        "textos": {
            "menu_pronto": ["Pesquisar"],
            "pesquisa": ["Pesquisar"],
            "rotina": ["Consulta Genérica"],
            "tabela": "SE2",
            "tabela_descricao": "Contas a Pagar",
            "confirmar": ["Confirmar", "OK", "Ok"],
            "filtro_abrir": ["Filtrar", "Filtro", "Gerenciar filtros"],
            "filtro_campo": "Vencimento",
            "filtro_operador": "Mês Atual",
            "filtro_aplicar": ["Aplicar", "Filtrar", "Confirmar", "OK"],
            "exportar": ["Exp. CSV"],
            "confirmar_exportacao": ["Sim", "OK", "Confirmar"],
            # Texto que a tela mostra quando a consulta abrange todas as filiais esperadas.
            # Vazio = abrangência não confirmada pela tela (a importação fica "não completa").
            "filiais_todas": [],
            # Textos que indicam outros filtros ativos (a coleta para se aparecerem).
            "outros_filtros": [],
            "sessao_encerrada": ["Sessão encerrada", "Conexão perdida", "conexão com o servidor foi perdida"],
        },
    },
    "categorias": {
        # Prefixo do título no TOTVS -> categoria exibida no painel.
        # Ex.: {"MAT": "Materiais odontológicos", "LAB": "Laboratório de prótese"}
        "por_prefixo": {},
        # Título sem prefixo no TOTVS.
        "sem_prefixo": "Diversos",
    },
    "responsaveis": {
        # Quem cuida de cada filial. Padrão: a DIVISÃO da planilha de filiais
        # (TICKET 1 a 6). Ordem de prioridade:
        #   1. por_filial: {"016501": "Nome"}  (código TOTVS da filial)
        #   2. coluna RESPONSÁVEL da planilha de filiais, se existir
        #   3. divisão: "TICKET 1", ou "TICKET 1 — Nome" se houver
        #      por_divisao: {"TICKET 1": "Nome"}
        "por_filial": {},
        "por_divisao": {},
        "sem_responsavel": "Sem responsável definido",
    },
    "acesso_restrito": {
        # Filiais cujos dados só aparecem após digitar a senha (ex.: o escritório,
        # que concentra a folha dos colaboradores e os pagamentos a PJ).
        # Só a conta proprietária libera (python -m sorria definir-proprietario).
        "filiais": ["031801"],
        # Regras adicionais explícitas (códigos do TOTVS). Vazias até serem informadas.
        "naturezas": [],
        "prefixos": [],
        # Título de filial fora do cadastro: classificação incerta, fica restrito.
        "restringir_sem_cadastro": True,
        "minutos_sessao": 30,
    },
    "relatorio_mensal": {
        # Gerado automaticamente no 1º dia de cada mês, sobre o mês anterior.
        "habilitado": True,
        "quantidade_destaque": 5,
        # Filiais com menos lançamentos no mês não entram no ranking de dificuldade.
        "minimo_lancamentos": 5,
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
    if config["agente"]["modo_coleta"] not in ("navegador", "pasta"):
        raise ValueError("agente.modo_coleta deve ser \"navegador\" ou \"pasta\"")


def caminho_banco(config: dict) -> Path:
    """Cada modo tem seu próprio arquivo: dados fictícios e reais nunca se misturam."""
    return pasta_dados() / f"{config['modo']}.sqlite3"


def pasta_dados() -> Path:
    return Path(os.environ.get("SORRIA_DADOS", RAIZ / "dados"))


def caminho_filiais() -> Path:
    """Cadastro de filiais importado da planilha (fora do repositório)."""
    return pasta_dados() / "filiais.json"


def caminho_senha() -> Path:
    """Hash da senha da área restrita (a senha em si nunca é gravada)."""
    return pasta_dados() / "acesso.json"


def pasta_relatorios(config: dict) -> Path:
    return pasta_dados() / "relatorios" / config["modo"]


def caminho_contratos() -> Path:
    """Cadastro de contratos (opcional) para conferir cobranças."""
    return pasta_dados() / "contratos" / "contratos.json"


def pasta_agente(config: dict) -> Path:
    """Pasta de trabalho do agente TOTVS: entrada, processados, rejeitados."""
    return pasta_dados() / "totvs"


def pasta_navegador() -> Path:
    """Perfil do Chrome dedicado ao agente (contém a sessão do TOTVS; fora do repositório)."""
    return pasta_dados() / "navegador" / "perfil"


def pasta_entrada_agente(config: dict) -> Path:
    configurada = (config.get("agente", {}).get("pasta_entrada") or "").strip()
    return Path(configurada) if configurada else pasta_agente(config) / "entrada"
