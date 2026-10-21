"""Executor do TOTVS no navegador contra o SIMULADOR local (tests/simulador_totvs.py).

Prova o mecanismo (Chrome controlado, espera de login, filtros, Exp. CSV,
captura do download, importação, painel), não a coleta no TOTVS real.
Precisa do Playwright e de um Chrome/Chromium: defina SORRIA_CHROME ou deixe o
Chromium do Playwright em /opt/pw-browsers. Sem eles os testes são pulados.
"""

from __future__ import annotations

import glob
import json
import os
import socket
import threading
import time
import unittest
import urllib.request
from pathlib import Path

from test_agente_totvs import BaseAgente

from sorria import config as cfg
from sorria import db
from sorria.totvs.navegador import acao_proibida

try:
    import playwright  # noqa: F401
    PLAYWRIGHT = True
except ImportError:
    PLAYWRIGHT = False

CHROME = os.environ.get("SORRIA_CHROME") or next(iter(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome")), None)
PROIBIDOS = {"Incluir", "Excluir", "Alterar", "Baixar"}


class TestGuarda(unittest.TestCase):
    def test_acoes_de_alteracao_sao_bloqueadas(self):
        for texto in ("Incluir", "Excluir", "Alterar", "Baixar", "Estornar", "Borderô", "Pagar", "Salvar"):
            self.assertTrue(acao_proibida(texto), texto)
        for texto in ("SE2 - Contas a Pagar", "Exp. CSV", "Filtrar", "Aplicar", "Confirmar", "Consulta Genérica", "Sim"):
            self.assertFalse(acao_proibida(texto), texto)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(PLAYWRIGHT and CHROME, "Playwright/Chromium indisponível")
class TestExecutorNavegador(BaseAgente):
    def setUp(self):
        super().setUp()
        from simulador_totvs import Simulador
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
        self.sim = Simulador()
        self.config["modo"] = "real"
        self.config["agente"]["modo_coleta"] = "navegador"
        self.config["totvs"]["endereco_webapp"] = self.sim.endereco
        nav = self.config["navegador"]
        nav.update({"executavel": CHROME, "porta_controle": porta_livre(), "tempo_login_minutos": 1,
                    "tempo_passo_segundos": 15, "tempo_exportacao_minutos": 1,
                    "argumentos_extras": ["--headless=new", "--no-sandbox"]})
        nav["textos"]["filiais_todas"] = ["Todas as filiais"]
        self.agente = self._agente()
        self.servidor = None

    def _agente(self):
        from sorria.totvs.execucao import AgenteTotvs
        return AgenteTotvs(self.config, cfg.caminho_filiais(), dormir=lambda s: None)

    def tearDown(self):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                navegador = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{self.config['navegador']['porta_controle']}")
                navegador.new_browser_cdp_session().send("Browser.close")
        except Exception:  # noqa: BLE001
            pass
        self.sim.fechar()
        if self.servidor:
            self.servidor.shutdown()
            self.servidor.server_close()
        super().tearDown()

    def iniciar_painel(self):
        from sorria.coleta import ServicoColeta
        from sorria.conectores.totvs_se2 import ConectorTotvsSE2
        from sorria.regras import regras_do_modo
        from sorria.servidor import Aplicacao
        caminho = cfg.caminho_banco({"modo": "real"})
        self.config["servidor"]["porta"] = porta_livre()
        servico = ServicoColeta(self.config, caminho, ConectorTotvsSE2(caminho), regras_do_modo("real", self.config))
        self.servidor = Aplicacao(self.config, caminho, servico, servico.regras).criar_servidor()
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.config['servidor']['porta']}"

    def pessoa_entra_quando_pedido(self):
        """Simula a pessoa: só entra no TOTVS depois que o agente pede login."""
        def esperar():
            limite = time.time() + 60
            while time.time() < limite:
                with self.banco() as c:
                    if c.execute("SELECT 1 FROM execucoes_agente WHERE etapa = 'aguardando_login'").fetchone():
                        urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                            urllib.request.Request(self.sim.endereco.replace("/webapp/", "/__login"), data=b"",
                                                   method="POST"), timeout=5)
                        return
                time.sleep(0.2)
        threading.Thread(target=esperar, daemon=True).start()

    def get(self, url):
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=10) as r:
            return r.read().decode()

    def test_coleta_completa_pelo_navegador(self):
        base = self.iniciar_painel()
        # Arquivo antigo na entrada: não pode ser usado.
        entrada = cfg.pasta_entrada_agente(self.config)
        entrada.mkdir(parents=True, exist_ok=True)
        (entrada / "antigo.csv").write_text("lixo", encoding="utf-8")
        self.pessoa_entra_quando_pedido()

        r = self.agente.executar("agendada")
        self.assertEqual(r.get("situacao_execucao"), "sucesso", r.get("mensagem"))
        self.assertEqual((r["situacao"], r["novos"]), ("importada", 3))
        self.assertTrue(r["completa"], r["pendencias"])
        self.assertTrue(r["painel_confirmado"]["confirmado"], r["painel_confirmado"])
        self.assertEqual(self.sim.exportacoes, 1)
        self.assertFalse(PROIBIDOS & set(self.sim.cliques), self.sim.cliques)
        for esperado in ("Consulta Genérica", "SE2 - Contas a Pagar", "Confirmar", "Filtrar", "Aplicar", "Exp. CSV", "Sim"):
            self.assertIn(esperado, self.sim.cliques)
        self.assertTrue((entrada / "antigo.csv").exists())  # não foi tocado
        with self.banco() as c:
            e = c.execute("SELECT * FROM execucoes_agente ORDER BY id DESC LIMIT 1").fetchone()
            i = c.execute("SELECT * FROM importacoes ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual((e["modo_coleta"], e["situacao"], e["painel_confirmado"]), ("navegador", "sucesso", 1))
        self.assertIn(f"_{e['id']}", e["arquivo_caminho"])  # pasta desta execução
        self.assertEqual((i["total_conferido"], i["completa"]), (1, 1))
        self.assertEqual(json.loads(i["escopo"])["filiais_confirmadas"], True)

        # Painel: mostra a coleta nova e não revela o escritório a quem não tem acesso.
        situacao = json.loads(self.get(base + "/api/situacao"))
        self.assertEqual(situacao["importacao"]["id"], i["id"])
        self.assertEqual(situacao["nivel"], "ok")
        inicio = time.strftime("%Y-%m-01")
        for rota in ("/api/situacao", f"/api/painel?inicio={inicio}", f"/api/ocorrencias.csv?inicio={inicio}"):
            corpo = self.get(base + rota)
            for proibido in ("031801", "COLABORADOR", "500000", "5.000,00", '"titulos": 3', '"rejeitadas": 1'):
                self.assertNotIn(proibido, corpo, f"{rota}: {proibido}")

        # Segunda rodada (sessão do TOTVS já aberta, um valor mudou): atualiza sem duplicar.
        self.sim.versao = 2
        r2 = self._agente().executar("agendada")
        self.assertEqual(r2.get("situacao_execucao"), "sucesso", (r2.get("mensagem"), self.sim.cliques, self.sim.exportacoes))
        self.assertEqual((r2["novos"], r2["atualizados"]), (0, 3))
        self.assertEqual(self.total(), (3, 110000 + 25050 + 500000))
        self.assertFalse(PROIBIDOS & set(self.sim.cliques))

    def test_sem_login_termina_sem_alterar_o_painel(self):
        self.config["navegador"]["tempo_login_minutos"] = 0.05
        self.config["navegador"]["tempo_passo_segundos"] = 5
        r = self.agente.executar("agendada")
        self.assertEqual((r["situacao"], r["etapa"]), ("falha", "aguardando_login"))
        self.assertIn("sessão autenticada", r["mensagem"])
        self.assertEqual(self.total(), (0, 0))
        self.assertEqual(self.sim.exportacoes, 0)

    def test_texto_proibido_na_configuracao_nao_e_clicado(self):
        self.sim.logado = True
        self.config["navegador"]["textos"]["filtro_abrir"] = ["Excluir"]  # configuração errada
        r = self.agente.executar("agendada")
        self.assertEqual((r["situacao"], r["etapa"]), ("falha", "filtro"))
        self.assertIn("ação de alteração", r["mensagem"])
        self.assertNotIn("Excluir", self.sim.cliques)
        self.assertEqual(self.sim.exportacoes, 0)

    def test_filtro_nao_aplicado_impede_exportacao(self):
        self.sim.logado = True
        self.config["navegador"]["textos"]["filtro_operador"] = "Próximo Mês"  # não existe na tela
        self.config["agente"]["tentativas"] = 1
        r = self.agente.executar("agendada")
        self.assertEqual((r["situacao"], r["etapa"]), ("falha", "filtro"))
        self.assertEqual(self.sim.exportacoes, 0)
        with self.banco() as c:
            diag = c.execute("SELECT diagnostico FROM execucoes_agente ORDER BY id DESC LIMIT 1").fetchone()[0]
        self.assertTrue(diag and list(Path(diag).glob("*filtro.png")))


if __name__ == "__main__":
    unittest.main()
