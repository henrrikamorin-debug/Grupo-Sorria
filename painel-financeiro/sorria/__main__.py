"""Linha de comando do painel.

    python -m sorria iniciar    inicia servidor + agendador (primeiro plano)
    python -m sorria parar      encerra o serviço em execução
    python -m sorria situacao   mostra a situação da última coleta
    python -m sorria coletar    executa uma coleta agora, sem servidor
    python -m sorria importar-filiais ARQUIVO.xlsx
                                importa o cadastro de filiais (planilha de controle)
    python -m sorria definir-senha
                                define a senha da área restrita (escritório)
    python -m sorria relatorio [AAAA-MM]
                                gera o relatório mensal (padrão: mês anterior)
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import signal
import sys
import urllib.request
from logging.handlers import RotatingFileHandler

from . import config as cfg
from . import db
from .coleta import ServicoColeta
from .conectores import criar_conector
from .regras import regras_do_modo

PASTA_LOGS = cfg.RAIZ / "logs"
ARQUIVO_PID = cfg.RAIZ / "dados" / "servico.pid"

log = logging.getLogger("sorria")


def configurar_log() -> None:
    PASTA_LOGS.mkdir(parents=True, exist_ok=True)
    formato = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    arquivo = RotatingFileHandler(PASTA_LOGS / "painel.log", maxBytes=2_000_000, backupCount=5,
                                  encoding="utf-8")
    arquivo.setFormatter(formato)
    console = logging.StreamHandler()
    console.setFormatter(formato)
    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    raiz.handlers[:] = [arquivo, console]


def _processo_ativo(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        identificador = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not identificador:
            return False
        codigo = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(identificador, ctypes.byref(codigo))
        kernel32.CloseHandle(identificador)
        return codigo.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _ler_pid() -> int | None:
    try:
        return int(ARQUIVO_PID.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _preparar(config: dict):
    caminho = cfg.caminho_banco(config)
    db.inicializar(caminho, config["modo"])
    servico = ServicoColeta(config, caminho, criar_conector(config), regras_do_modo(config["modo"]),
                            caminho_filiais=cfg.caminho_filiais())
    return caminho, servico


def iniciar(config: dict) -> int:
    from .servidor import Aplicacao

    pid = _ler_pid()
    if pid and pid != os.getpid() and _processo_ativo(pid):
        print(f"O serviço já está em execução (PID {pid}).")
        return 1
    caminho, servico = _preparar(config)
    aplicacao = Aplicacao(config, caminho, servico, servico.regras)
    servico.ao_concluir.append(aplicacao.gerar_relatorio_pendente)
    try:
        servidor = aplicacao.criar_servidor()
    except OSError as erro:
        print(f"Não foi possível abrir a porta {config['servidor']['porta']}: {erro}")
        return 1
    ARQUIVO_PID.parent.mkdir(parents=True, exist_ok=True)
    ARQUIVO_PID.write_text(str(os.getpid()))

    def sinal_encerrar(*_):
        aplicacao.encerrar()

    signal.signal(signal.SIGTERM, sinal_encerrar)
    host, porta = servidor.server_address[:2]
    endereco = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{porta}"
    log.info("Modo: %s | banco: %s", config["modo"].upper(), caminho)
    if config["modo"] == "demonstracao":
        log.warning("MODO DEMONSTRAÇÃO — DADOS FICTÍCIOS. Nenhum dado é coletado do TOTVS.")
    log.info("Painel disponível em %s  (modo TV: %s/?tv=1)", endereco, endereco)
    servico.iniciar_agendador()
    try:
        servidor.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        servico.parar_agendador()
        servidor.server_close()
        if _ler_pid() == os.getpid():
            ARQUIVO_PID.unlink(missing_ok=True)
        log.info("Serviço encerrado.")
    return 0


def parar(config: dict) -> int:
    pid = _ler_pid()
    if not pid or not _processo_ativo(pid):
        ARQUIVO_PID.unlink(missing_ok=True)
        print("O serviço não está em execução.")
        return 0
    porta = config["servidor"]["porta"]
    requisicao = urllib.request.Request(
        f"http://127.0.0.1:{porta}/api/encerrar", data=b"{}", method="POST",
        headers={"Content-Type": "application/json", "X-Painel-Sorria": "1"})
    try:
        urllib.request.urlopen(requisicao, timeout=5).read()
        print(f"Encerramento solicitado ao serviço (PID {pid}).")
    except OSError:
        os.kill(pid, signal.SIGTERM)
        print(f"Sinal de encerramento enviado ao processo {pid}.")
    return 0


def situacao(config: dict) -> int:
    caminho = cfg.caminho_banco(config)
    if not caminho.exists():
        print("Nenhuma coleta registrada ainda.")
        return 0
    with db.fechando(db.conectar(caminho)) as conexao:
        linhas = conexao.execute(
            "SELECT id, iniciada_em, situacao, origem, simulada, registros, ocorrencias, mensagem "
            "FROM coletas ORDER BY id DESC LIMIT 10").fetchall()
    pid = _ler_pid()
    print(f"Modo: {config['modo']} | serviço: "
          f"{'em execução (PID %s)' % pid if pid and _processo_ativo(pid) else 'parado'}")
    for linha in linhas:
        print(json.dumps(dict(linha), ensure_ascii=False))
    return 0


def coletar(config: dict) -> int:
    _, servico = _preparar(config)
    resultado = servico.executar("manual (linha de comando)")
    print(json.dumps(resultado, ensure_ascii=False))
    return 0 if resultado["situacao"] != "falha" else 2


def importar_filiais(config: dict, arquivo: str | None) -> int:
    from .cadastros import importar_filiais_xlsx, salvar_filiais

    if not arquivo:
        print("Informe o arquivo: python -m sorria importar-filiais CONTROLE_FILIAL_TOTVS.xlsx")
        return 2
    cadastro, avisos = importar_filiais_xlsx(cfg.Path(arquivo))
    salvar_filiais(cadastro, cfg.caminho_filiais())
    print(f"{len(cadastro)} filiais importadas para {cfg.caminho_filiais()}.")
    for aviso in avisos:
        print(f"  aviso: {aviso}")
    restritas = [cadastro.get(c, {}).get("nome", f"{c} (não está na planilha)")
                 for c in config["acesso_restrito"]["filiais"]]
    print(f"Área restrita (com senha): {', '.join(restritas) or 'nenhuma'}")
    return 0


def definir_senha(config: dict, _arquivo=None) -> int:
    from .acesso import definir_senha as gravar

    senha = getpass.getpass("Nova senha da área restrita: ")
    if senha != getpass.getpass("Repita a senha: "):
        print("As senhas não conferem. Nada foi alterado.")
        return 1
    try:
        gravar(cfg.caminho_senha(), senha)
    except ValueError as erro:
        print(erro)
        return 1
    print("Senha definida. Reinicie o serviço se ele estiver em execução para encerrar sessões abertas.")
    return 0


def gerar_relatorio(config: dict, mes: str | None) -> int:
    from . import relatorio
    from .cadastros import carregar_filiais

    caminho = cfg.caminho_banco(config)
    db.inicializar(caminho, config["modo"])
    mes = mes or relatorio.mes_anterior()
    with db.fechando(db.conectar(caminho)) as conexao:
        resultado = relatorio.gerar_e_salvar(conexao, config, mes, carregar_filiais(cfg.caminho_filiais()),
                                             cfg.pasta_relatorios(config),
                                             ocultar_filiais=config["acesso_restrito"]["filiais"])
    print(f"Relatório de {mes}: {cfg.pasta_relatorios(config) / f'relatorio-{mes}.html'}")
    print(f"Filiais em destaque: {', '.join(resultado['destaques']) or 'nenhuma'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(prog="python -m sorria", description=__doc__,
                                         formatter_class=argparse.RawDescriptionHelpFormatter)
    analisador.add_argument("comando", choices=["iniciar", "parar", "situacao", "coletar", "importar-filiais",
                                                "definir-senha", "relatorio"])
    analisador.add_argument("argumento", nargs="?", help="arquivo .xlsx ou mês AAAA-MM, conforme o comando")
    argumentos = analisador.parse_args(argv)
    configurar_log()
    config = cfg.carregar()
    simples = {"iniciar": iniciar, "parar": parar, "situacao": situacao, "coletar": coletar}
    if argumentos.comando in simples:
        return simples[argumentos.comando](config)
    com_argumento = {"importar-filiais": importar_filiais, "definir-senha": definir_senha,
                     "relatorio": gerar_relatorio}
    return com_argumento[argumentos.comando](config, argumentos.argumento)


if __name__ == "__main__":
    sys.exit(main())
