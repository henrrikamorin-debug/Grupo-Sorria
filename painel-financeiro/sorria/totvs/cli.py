"""Linha de comando do agente TOTVS.

    python -m sorria agente verificar
    python -m sorria agente abrir-navegador          (abre o Chrome do agente para o login no TOTVS)
    python -m sorria agente executar [--origem manual|agendada|claude_code] [--modo navegador|pasta]
                                     [--diagnostico] [--espera MINUTOS]
    python -m sorria agente importar ARQUIVO.csv [--confirmar-arquivo-antigo]
    python -m sorria agente historico
    python -m sorria agente agendamento

Códigos de saída: 0 sucesso · 2 falha ou lote rejeitado · 3 nenhuma exportação
nova · 4 outra execução em andamento · 5 pré-requisito ausente.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .. import config as cfg
from .. import db
from ..acesso import proprietario
from ..cadastros import carregar_filiais
from .classificacao import regras_restricao, validar_regras
from .contratos import carregar as carregar_contratos
from .execucao import AgenteTotvs

CODIGOS = {"sucesso": 0, "importada": 0, "ignorada": 0, "falha": 2, "rejeitada": 2,
           "sem_arquivo": 3, "bloqueada": 4}

CONDICOES_SEM_PRESENCA = (
    "Para a coleta sem ninguém presente: computador ligado e sem suspensão; sessão do Windows aberta (a "
    "tarefa usa /IT, só roda com o usuário conectado); o Chrome do agente aberto com o TOTVS WebApp "
    "autenticado (abra com 'agente abrir-navegador' e entre uma vez). Se a sessão do TOTVS cair, a execução "
    "espera o login por navegador.tempo_login_minutos e depois termina como falha, sem alterar o painel. "
    "Funcionamento com a tela bloqueada ou o Chrome fechado NÃO foi testado: confirme no primeiro dia."
)


def verificar(config: dict) -> int:
    itens = []

    def item(ok: bool | None, texto: str):
        itens.append(("OK " if ok else ("-- " if ok is None else "!! ")) + texto)

    item(config["modo"] == "real", f"Modo do painel: {config['modo']}"
         + ("" if config["modo"] == "real" else " (o painel só mostra dados do TOTVS com \"modo\": \"real\")"))
    item(config["totvs"]["conector"] == "se2_consulta_generica", f"Conector do painel: {config['totvs']['conector']}")
    item(bool(config["totvs"].get("endereco_webapp")), "Endereço do TOTVS WebApp configurado"
         if config["totvs"].get("endereco_webapp") else "Endereço do TOTVS WebApp não configurado (totvs.endereco_webapp)")
    modo = config["agente"]["modo_coleta"]
    item(None, f"Modo de coleta: {modo}")
    if modo == "navegador":
        from .navegador import chrome_respondendo, localizar_chrome
        try:
            import playwright  # noqa: F401
            item(True, "Biblioteca Playwright instalada")
        except ImportError:
            item(False, "Playwright não instalado: py -3 -m pip install -r requirements-navegador.txt")
        executavel = config["navegador"].get("executavel") or localizar_chrome()
        item(bool(executavel), f"Google Chrome: {executavel}" if executavel else "Google Chrome não encontrado")
        porta = int(config["navegador"]["porta_controle"])
        item(None, "Chrome do agente aberto" if chrome_respondendo(porta)
             else "Chrome do agente fechado (a execução abre; o login no TOTVS precisa estar feito)")
        textos = config["navegador"]["textos"]
        item(None, "Abrangência de filiais confirmada na tela: " + ("configurada" if textos.get("filiais_todas")
             else "não configurada (importações ficam \"não confirmadas como completas\" até calibrar)"))
    cadastro = carregar_filiais(cfg.caminho_filiais())
    item(bool(cadastro), f"Cadastro de filiais: {len(cadastro)} filial(is)")
    for aviso in validar_regras(cadastro, regras_restricao(config)):
        item(False, aviso)
    dono = proprietario(cfg.caminho_senha())
    item(bool(dono), "Conta proprietária da área restrita definida" if dono
         else "Conta proprietária não definida: área restrita bloqueada para todos (definir-proprietario)")
    entrada = cfg.pasta_entrada_agente(config)
    entrada.mkdir(parents=True, exist_ok=True)
    item(os.access(entrada, os.W_OK), f"Pasta de entrada da exportação: {entrada}")
    try:
        contratos = carregar_contratos(cfg.caminho_contratos())
        item(None, f"Contratos cadastrados: {len(contratos)}" if contratos
             else "Nenhum contrato cadastrado: análise registra \"Contrato não disponibilizado\"")
    except ValueError as erro:
        item(False, f"contratos.json inválido: {erro}")
    agenda = config["agente"]["agendamento"]
    item(None, "Agendamento: " + ("ativo " if agenda.get("ativo") else "inativo ")
         + (f"nos horários {', '.join(agenda['horarios'])}" if agenda.get("horarios") else "(horários não definidos)"))
    caminho = cfg.caminho_banco({"modo": "real"})
    if caminho.exists():
        db.inicializar(caminho, "real")
        with db.fechando(db.conectar(caminho)) as conexao:
            ultima = conexao.execute("SELECT finalizada_em, arquivo_nome, periodo_inicio FROM importacoes "
                                     "WHERE situacao = 'importada' ORDER BY id DESC LIMIT 1").fetchone()
        item(None, f"Última importação válida: {ultima['finalizada_em']} ({ultima['arquivo_nome']})" if ultima
             else "Nenhuma importação válida ainda")
    print("\n".join(itens))
    print("\n" + CONDICOES_SEM_PRESENCA)
    return 5 if any(l.startswith("!!") for l in itens if "Conta proprietária" not in l) else 0


def agendamento(config: dict) -> int:
    agenda = config["agente"]["agendamento"]
    if not agenda.get("horarios"):
        print("Horários não definidos (agente.agendamento.horarios = []). Nenhum agendamento foi criado.\n"
              "Defina os horários no config.json, por exemplo [\"08:00\", \"14:00\"], e rode de novo.")
        return 5
    if not agenda.get("ativo"):
        print("Agendamento preparado, mas inativo (agente.agendamento.ativo = false). Nada foi criado.")
        return 5
    raiz = cfg.RAIZ
    print("Comandos para o Agendador de Tarefas do Windows (rode no PowerShell, na conta do Windows que usa o TOTVS):")
    for horario in agenda["horarios"]:
        nome = f"Sorria Agente TOTVS {horario.replace(':', 'h')}"
        print(f'schtasks /Create /TN "{nome}" /SC DAILY /ST {horario} /IT /F '
              f'/TR "cmd /c cd /d \\"{raiz}\\" && py -3 -m sorria agente executar --origem agendada"')
    print("\n/IT = só executa com o usuário conectado (necessário para a interface do TOTVS).")
    print(CONDICOES_SEM_PRESENCA)
    return 0


def abrir_navegador(config: dict) -> int:
    """Abre o Chrome dedicado do agente no TOTVS para o login (feito pela pessoa, nunca pelo agente)."""
    from .navegador import ErroNavegador, abrir_chrome, chrome_respondendo

    endereco = config["totvs"].get("endereco_webapp")
    if not endereco:
        print("Configure totvs.endereco_webapp no config.json.")
        return 5
    porta = int(config["navegador"]["porta_controle"])
    if chrome_respondendo(porta):
        print("O Chrome do agente já está aberto. Entre no TOTVS nele, se ainda não entrou, e deixe-o aberto.")
        return 0
    try:
        abrir_chrome(config, cfg.pasta_navegador(), endereco)
    except ErroNavegador as erro:
        print(erro.mensagem)
        return 5
    print("Chrome do agente aberto. Entre no TOTVS (ambiente e módulo Financeiro) nessa janela e deixe-a aberta;\n"
          "a coleta usa essa sessão. Não use essa janela para outros sites.")
    return 0


def main(argv: list[str]) -> int:
    analisador = argparse.ArgumentParser(prog="python -m sorria agente", description=__doc__,
                                         formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = analisador.add_subparsers(dest="comando", required=True)
    sub.add_parser("verificar")
    sub.add_parser("abrir-navegador")
    executar = sub.add_parser("executar")
    executar.add_argument("--origem", default="manual", choices=["manual", "agendada", "claude_code"])
    executar.add_argument("--modo", choices=["navegador", "pasta"], help="padrão: agente.modo_coleta")
    executar.add_argument("--diagnostico", action="store_true",
                          help="grava tela e texto de cada etapa (calibração) em dados/totvs/diagnostico")
    executar.add_argument("--espera", type=float, help="modo pasta: minutos de espera pela exportação")
    importar = sub.add_parser("importar")
    importar.add_argument("arquivo")
    importar.add_argument("--confirmar-arquivo-antigo", action="store_true")
    sub.add_parser("historico")
    sub.add_parser("agendamento")
    argumentos = analisador.parse_args(argv)
    config = cfg.carregar()

    if argumentos.comando == "verificar":
        return verificar(config)
    if argumentos.comando == "agendamento":
        return agendamento(config)
    if argumentos.comando == "abrir-navegador":
        return abrir_navegador(config)
    if getattr(argumentos, "diagnostico", False):
        config["navegador"]["diagnostico"] = "sempre"
    agente = AgenteTotvs(config, cfg.caminho_filiais())
    if argumentos.comando == "historico":
        for linha in agente.historico():
            print(json.dumps(linha, ensure_ascii=False))
        return 0
    if argumentos.comando == "executar":
        resultado = agente.executar(argumentos.origem, espera_minutos=argumentos.espera, modo_coleta=argumentos.modo)
    else:
        caminho = Path(argumentos.arquivo)
        if not caminho.is_file():
            print(f"Arquivo não encontrado: {caminho}")
            return 5
        resultado = agente.executar("manual", arquivo=caminho,
                                    confirmar_arquivo_antigo=argumentos.confirmar_arquivo_antigo)
    resumo = {k: v for k, v in resultado.items() if k != "painel"}
    print(json.dumps(resumo, ensure_ascii=False, indent=2))
    if config["modo"] != "real":
        print("Aviso: o painel está em modo demonstração; mude \"modo\" para \"real\" no config.json para exibir "
              "os dados do TOTVS.")
    return CODIGOS.get(resultado.get("situacao_execucao") or resultado["situacao"], 2)
