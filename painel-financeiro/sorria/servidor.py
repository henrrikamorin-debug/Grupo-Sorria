"""Servidor HTTP local: entrega a interface e a API do painel.

A interface apenas LÊ o último retrato válido. Recarregar a página não aciona
coleta no TOTVS; quem coleta é o agendador do serviço.
"""

from __future__ import annotations

import json
import logging
from http.cookies import SimpleCookie
import mimetypes
import re
import threading
from datetime import date, datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import db, relatorio
from .acesso import AcessoNegado, MuitasTentativas, Sessoes, senha_definida
from .agente import AgenteFinanceiro, AgenteIndisponivel
from .analise import Filtros, FiltroInvalido, listar_ocorrencias, montar_painel
from .cadastros import carregar_filiais
from .config import RAIZ, caminho_filiais, caminho_senha, pasta_relatorios
from .exportacao import gerar_csv
from .situacao import montar_situacao

log = logging.getLogger(__name__)

PASTA_WEB = RAIZ / "web"
LOCAIS = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
CABECALHO_ESCRITA = "X-Painel-Sorria"
TAMANHO_MAXIMO_CORPO = 64 * 1024
COOKIE_SESSAO = "painel_sessao"

POLITICA_CONTEUDO = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
)


class Aplicacao:
    def __init__(self, config: dict, caminho_banco: Path, servico, regras):
        self.config = config
        self.caminho_banco = caminho_banco
        self.servico = servico
        self.regras = regras
        self.agente = AgenteFinanceiro(config)
        self.servidor: ThreadingHTTPServer | None = None
        self.filiais_restritas = tuple(config["acesso_restrito"]["filiais"])
        self.sessoes = Sessoes(caminho_senha(), float(config["acesso_restrito"]["minutos_sessao"]))
        self.pasta_relatorios = pasta_relatorios(config)
        self._trava_relatorio = threading.Lock()

    def gerar_relatorio(self, mes: str) -> dict:
        with self._trava_relatorio, self.conexao() as conexao:
            return relatorio.gerar_e_salvar(conexao, self.config, mes, carregar_filiais(caminho_filiais()),
                                            self.pasta_relatorios, ocultar_filiais=self.filiais_restritas)

    def gerar_relatorio_pendente(self) -> None:
        """Chamado após cada coleta: gera o relatório do mês anterior se ainda não existe."""
        if not self.config["relatorio_mensal"]["habilitado"]:
            return
        mes = relatorio.mes_anterior()
        if not (self.pasta_relatorios / f"relatorio-{mes}.html").exists():
            self.gerar_relatorio(mes)

    def conexao(self):
        return db.fechando(db.conectar(self.caminho_banco))

    def criar_servidor(self) -> ThreadingHTTPServer:
        aplicacao = self

        class Manipulador(ManipuladorPainel):
            app = aplicacao

        host, porta = self.config["servidor"]["host"], int(self.config["servidor"]["porta"])
        self.servidor = ThreadingHTTPServer((host, porta), Manipulador)
        self.servidor.daemon_threads = True
        return self.servidor

    def encerrar(self) -> None:
        if self.servidor:
            threading.Thread(target=self.servidor.shutdown, daemon=True).start()


class ManipuladorPainel(BaseHTTPRequestHandler):
    app: Aplicacao
    server_version = "PainelSorria/1.0"
    sys_version = ""

    # ---------------------------------------------------------------- utilidades
    def log_message(self, formato, *args):  # silencia o log padrão por requisição
        log.debug("%s - %s", self.address_string(), formato % args)

    def _cabecalhos_comuns(self, tipo: str, tamanho: int, extras: dict | None = None):
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(tamanho))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", POLITICA_CONTEUDO)
        for chave, valor in (extras or {}).items():
            self.send_header(chave, valor)
        self.end_headers()

    def _json(self, dados, status=HTTPStatus.OK, extras: dict | None = None):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cabecalhos_comuns("application/json; charset=utf-8", len(corpo), extras)
        self.wfile.write(corpo)

    def _erro(self, status, mensagem):
        self._json({"erro": mensagem}, status)

    def _parametros(self) -> dict:
        return parse_qs(urlparse(self.path).query)

    def _tv(self, parametros) -> bool:
        # Acessos vindos de outra máquina sempre recebem a versão mascarada.
        if not self._local():
            return True
        return parametros.get("tv", ["0"])[0] in ("1", "true", "sim")

    def _local(self) -> bool:
        return self.client_address[0] in LOCAIS

    def _token(self) -> str | None:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie") or "")
        except Exception:  # noqa: BLE001 — cookie malformado = sem sessão
            return None
        return cookie[COOKIE_SESSAO].value if COOKIE_SESSAO in cookie else None

    def _sessao_expira(self) -> float | None:
        return self.app.sessoes.valida(self._token())

    def _ocultar(self, tv: bool) -> tuple:
        """Filiais restritas ficam ocultas no modo TV e sem sessão desbloqueada."""
        if tv or not self._sessao_expira():
            return self.app.filiais_restritas
        return ()

    def _estado_acesso(self, conexao) -> dict:
        restritas = self.app.filiais_restritas
        nomes = []
        if restritas:
            nomes = [r[0] for r in conexao.execute(
                f"SELECT DISTINCT clinica FROM lancamentos WHERE filial IN ({', '.join('?' * len(restritas))})",
                restritas)]
            cadastro = carregar_filiais(caminho_filiais())
            nomes = nomes or [cadastro.get(c, {}).get("nome", f"Filial {c}") for c in restritas]
        expira = self._sessao_expira()
        return {"filiais": list(restritas), "nomes": nomes, "senha_definida": senha_definida(caminho_senha()),
                "desbloqueado": bool(expira),
                "expira_em": datetime.fromtimestamp(expira, timezone.utc).isoformat(timespec="seconds") if expira else None}

    def _corpo_json(self) -> dict:
        tamanho = int(self.headers.get("Content-Length") or 0)
        if tamanho > TAMANHO_MAXIMO_CORPO:
            raise ValueError("corpo da requisição muito grande")
        bruto = self.rfile.read(tamanho) if tamanho else b"{}"
        dados = json.loads(bruto or b"{}")
        if not isinstance(dados, dict):
            raise ValueError("corpo deve ser um objeto JSON")
        return dados

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        caminho = urlparse(self.path).path
        try:
            if caminho in ("/", "/index.html"):
                return self._arquivo(PASTA_WEB / "index.html")
            if caminho.startswith("/static/"):
                return self._estatico(caminho[len("/static/"):])
            arquivo_relatorio = re.fullmatch(r"/relatorios/(relatorio-\d{4}-\d{2}\.(?:html|csv))", caminho)
            if arquivo_relatorio:
                return self._arquivo(self.app.pasta_relatorios / arquivo_relatorio.group(1))
            rotas = {
                "/api/saude": self._saude,
                "/api/situacao": self._situacao,
                "/api/painel": self._painel,
                "/api/ocorrencias.csv": self._csv,
                "/api/regras": self._regras,
                "/api/agente/estado": self._agente_estado,
                "/api/agente/contexto": self._agente_contexto,
                "/api/acesso": self._acesso,
                "/api/relatorios": self._relatorios,
            }
            if caminho in rotas:
                return rotas[caminho]()
            self._erro(HTTPStatus.NOT_FOUND, "não encontrado")
        except FiltroInvalido as erro:
            self._erro(HTTPStatus.BAD_REQUEST, str(erro))
        except Exception:  # noqa: BLE001
            log.exception("Erro ao atender %s", self.path)
            self._erro(HTTPStatus.INTERNAL_SERVER_ERROR, "erro interno; consulte logs/painel.log")

    def _arquivo(self, arquivo: Path):
        if not arquivo.is_file():
            return self._erro(HTTPStatus.NOT_FOUND, "não encontrado")
        corpo = arquivo.read_bytes()
        tipo = mimetypes.guess_type(arquivo.name)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo in ("application/javascript", "image/svg+xml"):
            tipo += "; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self._cabecalhos_comuns(tipo, len(corpo))
        self.wfile.write(corpo)

    def _estatico(self, relativo: str):
        if not re.fullmatch(r"[\w\-./]+", relativo) or ".." in relativo:
            return self._erro(HTTPStatus.NOT_FOUND, "não encontrado")
        alvo = (PASTA_WEB / relativo).resolve()
        if PASTA_WEB.resolve() not in alvo.parents:
            return self._erro(HTTPStatus.NOT_FOUND, "não encontrado")
        self._arquivo(alvo)

    def _saude(self):
        self._json({"ok": True, "modo": self.app.config["modo"]})

    def _situacao(self):
        with self.app.conexao() as conexao:
            self._json(montar_situacao(conexao, self.app.config, self.app.servico))

    def _painel(self):
        parametros = self._parametros()
        filtros = Filtros.de_parametros(parametros)
        tv = self._tv(parametros)
        with self.app.conexao() as conexao:
            dados = montar_painel(conexao, filtros, tv=tv, ocultar_filiais=self._ocultar(tv))
            dados["situacao"] = montar_situacao(conexao, self.app.config, self.app.servico)
            dados["acesso"] = self._estado_acesso(conexao)
        dados["modo"] = self.app.config["modo"]
        dados["tv"] = tv
        dados["televisao"] = self.app.config["televisao"]
        self._json(dados)

    def _csv(self):
        parametros = self._parametros()
        filtros = Filtros.de_parametros(parametros)
        demonstracao = self.app.config["modo"] == "demonstracao"
        tv = self._tv(parametros)
        with self.app.conexao() as conexao:
            ocorrencias = listar_ocorrencias(conexao, filtros, tv=tv, ocultar_filiais=self._ocultar(tv))
        corpo = gerar_csv(ocorrencias, demonstracao)
        prefixo = "DEMONSTRACAO_" if demonstracao else ""
        nome = f"ocorrencias_{prefixo}{date.today().isoformat()}.csv"
        self.send_response(HTTPStatus.OK)
        self._cabecalhos_comuns("text/csv; charset=utf-8", len(corpo),
                                {"Content-Disposition": f'attachment; filename="{nome}"'})
        self.wfile.write(corpo)

    def _acesso(self):
        with self.app.conexao() as conexao:
            self._json(self._estado_acesso(conexao))

    def _relatorios(self):
        self._json({"relatorios": relatorio.listar(self.app.pasta_relatorios),
                    "mes_anterior": relatorio.mes_anterior(),
                    "automatico": self.app.config["relatorio_mensal"]["habilitado"]})

    def _regras(self):
        self._json({"modo": self.app.config["modo"],
                    "regras": [r.metadados() for r in self.app.regras]})

    def _agente_estado(self):
        with self.app.conexao() as conexao:
            self._json(self.app.agente.estado(conexao))

    def _agente_contexto(self):
        if not self.app.agente.habilitado:
            return self._erro(HTTPStatus.SERVICE_UNAVAILABLE, "interface do agente desativada")
        filtros = Filtros.de_parametros(self._parametros())
        with self.app.conexao() as conexao:
            self._json(self.app.agente.contexto(conexao, filtros))

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        caminho = urlparse(self.path).path
        # Escritas: somente a partir deste computador e com cabeçalho próprio
        # (o cabeçalho impede que outro site dispare ações pelo navegador).
        if not self._local():
            return self._erro(HTTPStatus.FORBIDDEN, "ações permitidas apenas neste computador")
        if self.headers.get(CABECALHO_ESCRITA) != "1":
            return self._erro(HTTPStatus.FORBIDDEN, "cabeçalho de segurança ausente")
        try:
            corpo = self._corpo_json()
            if caminho == "/api/coleta":
                return self._coletar(corpo)
            if caminho == "/api/encerrar":
                self._json({"ok": True, "mensagem": "encerrando"})
                return self.app.encerrar()
            if caminho == "/api/agente/perguntar":
                return self._agente_perguntar(corpo)
            if caminho == "/api/acesso/desbloquear":
                return self._desbloquear(corpo)
            if caminho == "/api/acesso/bloquear":
                return self._bloquear()
            if caminho == "/api/relatorios":
                return self._json(self.app.gerar_relatorio(str(corpo.get("mes") or relatorio.mes_anterior())))
            correspondencia = re.fullmatch(r"/api/ocorrencias/([0-9a-f]{16})/situacao", caminho)
            if correspondencia:
                return self._alterar_situacao(correspondencia.group(1), corpo)
            self._erro(HTTPStatus.NOT_FOUND, "não encontrado")
        except (ValueError, FiltroInvalido) as erro:
            self._erro(HTTPStatus.BAD_REQUEST, str(erro))
        except AgenteIndisponivel as erro:
            self._erro(HTTPStatus.SERVICE_UNAVAILABLE, str(erro))
        except MuitasTentativas as erro:
            self._erro(HTTPStatus.TOO_MANY_REQUESTS, str(erro))
        except AcessoNegado as erro:
            self._erro(HTTPStatus.UNAUTHORIZED, str(erro))
        except Exception:  # noqa: BLE001
            log.exception("Erro ao atender POST %s", self.path)
            self._erro(HTTPStatus.INTERNAL_SERVER_ERROR, "erro interno; consulte logs/painel.log")

    def _coletar(self, corpo: dict):
        simular_falha = bool(corpo.get("simular_falha"))
        origem = "manual (falha simulada)" if simular_falha else "manual"
        self._json(self.app.servico.executar(origem, simular_falha=simular_falha))

    def _desbloquear(self, corpo: dict):
        token, expira = self.app.sessoes.desbloquear(str(corpo.get("senha") or ""))
        minutos = int(round((expira - datetime.now().timestamp()) / 60))
        log.info("Área restrita desbloqueada por %d min.", minutos)
        cookie = f"{COOKIE_SESSAO}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={minutos * 60}"
        self._json({"ok": True, "desbloqueado": True,
                    "expira_em": datetime.fromtimestamp(expira, timezone.utc).isoformat(timespec="seconds")},
                   extras={"Set-Cookie": cookie})

    def _bloquear(self):
        self.app.sessoes.encerrar(self._token())
        self._json({"ok": True, "desbloqueado": False},
                   extras={"Set-Cookie": f"{COOKIE_SESSAO}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"})

    def _alterar_situacao(self, id_ocorrencia: str, corpo: dict):
        nova = corpo.get("situacao")
        if nova not in db.SITUACOES:
            raise ValueError("situação inválida")
        with self.app.conexao() as conexao:
            existe = conexao.execute("SELECT filial FROM ocorrencias WHERE id = ?", (id_ocorrencia,)).fetchone()
            if not existe:
                return self._erro(HTTPStatus.NOT_FOUND, "ocorrência não encontrada")
            if existe["filial"] in self._ocultar(tv=False):
                return self._erro(HTTPStatus.UNAUTHORIZED, "área restrita: desbloqueie com a senha")
            agora = db.agora_iso()
            conexao.execute(
                "INSERT INTO situacao_ocorrencias (id, situacao, primeira_deteccao, atualizada_em) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET situacao = excluded.situacao, "
                "atualizada_em = excluded.atualizada_em", (id_ocorrencia, nova, agora, agora))
        log.info("Situação da ocorrência %s alterada para %s.", id_ocorrencia, nova)
        self._json({"ok": True, "id": id_ocorrencia, "situacao": nova})

    def _agente_perguntar(self, corpo: dict):
        filtros = Filtros.de_parametros(corpo.get("filtros") or {})
        with self.app.conexao() as conexao:
            self._json(self.app.agente.perguntar(conexao, corpo.get("pergunta", ""), filtros))
