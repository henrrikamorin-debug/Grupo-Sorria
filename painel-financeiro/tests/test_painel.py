"""Testes do painel. Execute com:  python -m unittest discover -s tests -v"""

from __future__ import annotations

import copy
import csv
import io
import json
import logging
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from sorria import config as cfg
from sorria import db
from sorria.analise import Filtros, FiltroInvalido, montar_painel
from sorria.coleta import ServicoColeta, _consolidar
from sorria.conectores.base import Conector, Lancamento, ResultadoColeta
from sorria.conectores.demonstracao import ConectorDemonstracao
from sorria.conectores.totvs import ConectorTotvsPendente
from sorria.exportacao import gerar_csv
from sorria.privacidade import OCULTO, limpar_texto, mascarar_ocorrencia
from sorria.regras import analisar, regras_do_modo
from sorria.regras.base import Achado, ItemEvidencia, Regra
from sorria.situacao import montar_situacao

HOJE = date(2026, 10, 20)

logging.disable(logging.CRITICAL)  # falhas são provocadas de propósito nos testes


def _lanc(ref, valor, clinica="Clínica A", categoria="Cat 1", dia=HOJE, **extras):
    return Lancamento(referencia=ref, clinica=clinica, categoria=categoria, data=dia.isoformat(),
                      valor_centavos=valor, descricao="teste", favorecido="Pessoa Teste",
                      pessoa_fisica=True, documento="123.456.789-09",
                      dados_bancarios="Banco 999 · Ag. 1234 · CC 56789-0", extras=extras)


def _regra(codigo, condicao):
    def verificar(lancamentos, _ref):
        return [Achado(l.referencia, f"{codigo} em {l.referencia}", "resumo",
                       [ItemEvidencia("CPF/CNPJ", l.documento, sensivel=True),
                        ItemEvidencia("Valor", str(l.valor_centavos))])
                for l in lancamentos if condicao(l)]
    return Regra(codigo, f"Regra {codigo}", "cond", [], "", "", verificar, aprovada=True)


class ConectorFixo(Conector):
    nome = "teste"
    simulado = False

    def __init__(self, lancamentos):
        self.lancamentos = lancamentos
        self.falhar = False
        self.evento: threading.Event | None = None

    def coletar(self, inicio, fim):
        if self.evento:
            self.evento.wait(5)
        if self.falhar:
            raise RuntimeError("origem indisponível")
        return ResultadoColeta(lancamentos=list(self.lancamentos), simulada=False)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._dados_antes = os.environ.get("SORRIA_DADOS")
        os.environ["SORRIA_DADOS"] = self.tmp.name  # senha, cadastros e relatórios do teste
        self.caminho = Path(self.tmp.name) / "teste.sqlite3"
        self.config = copy.deepcopy(cfg.PADRAO)
        self.config["modo"] = "real"
        db.inicializar(self.caminho, "real")

    def tearDown(self):
        if self._dados_antes is None:
            os.environ.pop("SORRIA_DADOS", None)
        else:
            os.environ["SORRIA_DADOS"] = self._dados_antes
        self.tmp.cleanup()

    def servico(self, lancamentos, regras=None):
        conector = ConectorFixo(lancamentos)
        regras = regras if regras is not None else [
            _regra("R1", lambda l: l.valor_centavos and l.valor_centavos > 1000),
            _regra("R2", lambda l: l.clinica == "Clínica A"),
        ]
        return ServicoColeta(self.config, self.caminho, conector, regras)

    def painel(self, filtros=None, tv=False):
        with db.fechando(db.conectar(self.caminho)) as conexao:
            return montar_painel(conexao, filtros or Filtros(), tv=tv)


class TestCalculos(Base):
    def test_valor_somado_uma_vez_por_lancamento(self):
        # L1 dispara R1 e R2 (duas ocorrências); L2 só R2; L3 só R1.
        servico = self.servico([
            _lanc("L1", 5000), _lanc("L2", 700), _lanc("L3", 2000, clinica="Clínica B"),
            _lanc("L4", 100, clinica="Clínica B"),
        ])
        self.assertEqual(servico.executar()["situacao"], "sucesso")
        p = self.painel()
        k = p["indicadores"]
        self.assertEqual(k["registros_analisados"], 4)
        self.assertEqual(k["ocorrencias"], 4)
        self.assertEqual(k["lancamentos_afetados"], 3)
        self.assertEqual(k["valor_associado_centavos"], 5000 + 700 + 2000)
        por_clinica = {g["rotulo"]: g for g in p["graficos"]["por_clinica"]}
        self.assertEqual(por_clinica["Clínica A"]["ocorrencias"], 3)
        self.assertEqual(por_clinica["Clínica A"]["valor_centavos"], 5700)
        self.assertEqual(por_clinica["Clínica B"]["valor_centavos"], 2000)
        serie = p["graficos"]["por_periodo"]["serie"]
        self.assertEqual(sum(b["valor_centavos"] for b in serie), 7700)

    def test_valor_ausente_nao_soma(self):
        self.servico([_lanc("L1", None), _lanc("L2", 3000)]).executar()
        k = self.painel()["indicadores"]
        self.assertEqual(k["valor_associado_centavos"], 3000)
        self.assertEqual(k["lancamentos_sem_valor"], 1)

    def test_filtros(self):
        self.servico([
            _lanc("L1", 5000, dia=HOJE - timedelta(days=40)),
            _lanc("L2", 5000, clinica="Clínica B", categoria="Cat 2"),
        ]).executar()
        inicio = (HOJE - timedelta(days=10)).isoformat()
        p = self.painel(Filtros(inicio=inicio, fim=HOJE.isoformat()))
        self.assertEqual(p["indicadores"]["registros_analisados"], 1)
        self.assertEqual({o["referencia"] for o in p["ocorrencias"]}, {"L2"})
        p = self.painel(Filtros(categoria="Cat 1"))
        self.assertEqual({o["referencia"] for o in p["ocorrencias"]}, {"L1"})
        p = self.painel(Filtros(situacao="resolvida"))
        self.assertEqual(p["indicadores"]["ocorrencias"], 0)
        self.assertEqual(p["indicadores"]["pendencias"], 0)

    def test_granularidade_do_periodo(self):
        self.servico([_lanc("L1", 5000)]).executar()
        casos = {7: "dia", 90: "semana", 365: "mes"}
        for dias, esperado in casos.items():
            inicio = (HOJE - timedelta(days=dias - 1)).isoformat()
            p = self.painel(Filtros(inicio=inicio, fim=HOJE.isoformat()))
            self.assertEqual(p["graficos"]["por_periodo"]["granularidade"], esperado)
        p = self.painel(Filtros(inicio=(HOJE - timedelta(days=6)).isoformat(), fim=HOJE.isoformat()))
        self.assertEqual(len(p["graficos"]["por_periodo"]["serie"]), 7)

    def test_filtros_invalidos(self):
        with self.assertRaises(FiltroInvalido):
            Filtros.de_parametros({"inicio": ["2026-13-01"]})
        with self.assertRaises(FiltroInvalido):
            Filtros.de_parametros({"inicio": ["2026-10-20"], "fim": ["2026-10-01"]})
        with self.assertRaises(FiltroInvalido):
            Filtros.de_parametros({"situacao": ["qualquer"]})


class TestColeta(Base):
    def test_falha_preserva_ultima_coleta_valida(self):
        servico = self.servico([_lanc("L1", 5000)])
        servico.executar()
        servico.conector.falhar = True
        resultado = servico.executar()
        self.assertEqual(resultado["situacao"], "falha")
        self.assertEqual(self.painel()["indicadores"]["registros_analisados"], 1)
        with db.fechando(db.conectar(self.caminho)) as conexao:
            s = montar_situacao(conexao, self.config, servico)
        self.assertTrue(s["ultima_tentativa_falhou"])
        self.assertEqual(s["nivel"], "alerta")
        self.assertIn("origem indisponível", s["ultima_tentativa"]["mensagem"])

    def test_coleta_vazia_apos_dados_e_falha(self):
        servico = self.servico([_lanc("L1", 5000)])
        servico.executar()
        servico.conector.lancamentos = []
        self.assertEqual(servico.executar()["situacao"], "falha")
        self.assertEqual(self.painel()["indicadores"]["registros_analisados"], 1)

    def test_execucoes_nao_se_sobrepoem(self):
        servico = self.servico([_lanc("L1", 5000)])
        servico.conector.evento = threading.Event()
        primeira = threading.Thread(target=servico.executar)
        primeira.start()
        while not servico.em_andamento:
            pass
        self.assertEqual(servico.executar()["situacao"], "ignorada")
        servico.conector.evento.set()
        primeira.join()

    def test_trava_entre_processos(self):
        outro = self.servico([_lanc("L1", 5000)])
        servico = self.servico([_lanc("L1", 5000)])
        with db.fechando(db.conectar(self.caminho)) as conexao:
            self.assertTrue(outro._adquirir_trava(conexao))
        self.assertEqual(servico.executar()["situacao"], "ignorada")

    def test_referencia_repetida_na_origem_nao_duplica(self):
        self.servico([_lanc("L1", 5000), _lanc("L1", 5000)]).executar()
        p = self.painel()
        self.assertEqual(p["indicadores"]["registros_analisados"], 1)
        self.assertEqual(p["indicadores"]["valor_associado_centavos"], 5000)

    def test_situacao_mantida_entre_coletas(self):
        servico = self.servico([_lanc("L1", 5000)])
        servico.executar()
        id_ = self.painel()["ocorrencias"][0]["id"]
        with db.fechando(db.conectar(self.caminho)) as conexao:
            conexao.execute("UPDATE situacao_ocorrencias SET situacao = 'resolvida' WHERE id = ?", (id_,))
        servico.executar()
        situacoes = {o["id"]: o["situacao"] for o in self.painel()["ocorrencias"]}
        self.assertEqual(situacoes[id_], "resolvida")

    def test_agendador_executa_periodicamente(self):
        self.config["coleta"]["intervalo_minutos"] = 0.004  # ~0,24 s, só para o teste
        servico = self.servico([_lanc("L1", 5000)])
        servico.iniciar_agendador()
        try:
            import time
            time.sleep(1.2)
        finally:
            servico.parar_agendador()
        with db.fechando(db.conectar(self.caminho)) as conexao:
            linhas = conexao.execute("SELECT origem, situacao, iniciada_em, finalizada_em FROM coletas ORDER BY id").fetchall()
        self.assertGreaterEqual(len(linhas), 3)
        self.assertEqual(linhas[0]["origem"], "inicial")
        self.assertTrue(all(l["situacao"] == "sucesso" for l in linhas))
        self.assertFalse(servico.agendador_ativo)

    def test_interrompida_vira_falha(self):
        with db.fechando(db.conectar(self.caminho)) as conexao:
            conexao.execute("INSERT INTO coletas (iniciada_em, situacao, origem, simulada, conector) "
                            "VALUES (?, 'em_andamento', 'agendada', 0, 'x')", (db.agora_iso(),))
        self.servico([])
        with db.fechando(db.conectar(self.caminho)) as conexao:
            self.assertEqual(conexao.execute("SELECT situacao FROM coletas").fetchone()[0], "falha")

    def test_banco_de_outro_modo_e_recusado(self):
        with self.assertRaises(db.ModoIncompativel):
            db.inicializar(self.caminho, "demonstracao")


class TestModos(Base):
    def test_modo_real_nao_usa_regras_ilustrativas(self):
        self.assertTrue(all(not r.ilustrativa for r in regras_do_modo("real")))
        self.assertTrue(all(r.ilustrativa for r in regras_do_modo("demonstracao")))

    def test_totvs_nao_configurado(self):
        servico = ServicoColeta(self.config, self.caminho, ConectorTotvsPendente(), [])
        self.assertEqual(servico.executar()["situacao"], "falha")
        with db.fechando(db.conectar(self.caminho)) as conexao:
            s = montar_situacao(conexao, self.config, servico)
        self.assertEqual(s["nivel"], "nao_configurado")
        self.assertIsNone(s["ultima_coleta_sucesso"])

    def test_demonstracao_gera_todas_as_regras_e_multiplas_por_lancamento(self):
        resultado = ConectorDemonstracao(hoje=HOJE).coletar(HOJE - timedelta(days=119), HOJE)
        self.assertTrue(resultado.simulada)
        lancamentos = _consolidar(resultado, cfg.PADRAO)
        self.assertTrue(all(l.clinica and l.categoria for l in lancamentos))
        ocorrencias = analisar(lancamentos, resultado.referencias, regras_do_modo("demonstracao"))
        codigos = {o["regra_codigo"] for o in ocorrencias}
        self.assertEqual(codigos, {f"DEMO-0{i}" for i in range(1, 8)})
        por_ref = {}
        for o in ocorrencias:
            por_ref[o["referencia"]] = por_ref.get(o["referencia"], 0) + 1
        self.assertTrue(any(n > 1 for n in por_ref.values()))
        self.assertEqual(len({o["id"] for o in ocorrencias}), len(ocorrencias))

    def test_situacao_demo_nunca_parece_real(self):
        config = copy.deepcopy(self.config)
        config["modo"] = "demonstracao"
        caminho = Path(self.tmp.name) / "demo.sqlite3"
        db.inicializar(caminho, "demonstracao")
        servico = ServicoColeta(config, caminho, ConectorDemonstracao(hoje=HOJE), regras_do_modo("demonstracao"))
        servico.executar()
        with db.fechando(db.conectar(caminho)) as conexao:
            s = montar_situacao(conexao, config, servico)
        self.assertEqual(s["nivel"], "demonstracao")
        self.assertIn("simulada", s["titulo"].lower())
        self.assertNotIn("ativa", s["titulo"].lower())


class TestPrivacidade(Base):
    def test_modo_tv_oculta_sensiveis(self):
        self.servico([_lanc("L1", 5000)]).executar()
        normal = self.painel()["ocorrencias"][0]
        tv = self.painel(tv=True)["ocorrencias"][0]
        texto_tv = json.dumps(tv, ensure_ascii=False)
        self.assertIn("123.456.789-09", json.dumps(normal, ensure_ascii=False))
        self.assertNotIn("123.456.789-09", texto_tv)
        self.assertIn(OCULTO, texto_tv)

    def test_filtro_de_texto(self):
        texto = "CPF 123.456.789-09, CNPJ 12.345.678/0001-90, Ag. 1234 CC 56789-0, a@b.com.br"
        limpo = limpar_texto(texto)
        for trecho in ("123.456.789-09", "12.345.678/0001-90", "56789", "a@b.com.br"):
            self.assertNotIn(trecho, limpo)

    def test_filtro_preserva_referencias_valores_e_datas(self):
        texto = "Mesmo favorecido e valor de DEMO-2610-00728, R$ 2.125,97 em 20/10/2026"
        self.assertEqual(limpar_texto(texto), texto)

    def test_mascarar_nao_altera_original(self):
        original = {"descricao": "x", "evidencia": {"itens": [{"campo": "c", "valor": "v", "sensivel": True}]}}
        mascarar_ocorrencia(original)
        self.assertEqual(original["evidencia"]["itens"][0]["valor"], "v")


class TestExportacao(unittest.TestCase):
    def test_csv(self):
        base = {"clinica": "=CMD()", "regra_codigo": "R1", "regra_nome": "n", "descricao": "d",
                "data": "2026-10-20", "situacao_rotulo": "Pendente", "primeira_deteccao": "2026-10-20T10:00:00+00:00"}
        ocorrencias = [
            {**base, "referencia": "L1", "valor_centavos": 123456},
            {**base, "referencia": "L1", "valor_centavos": 123456, "regra_codigo": "R2"},
            {**base, "referencia": "L2", "valor_centavos": None},
        ]
        conteudo = gerar_csv(ocorrencias, demonstracao=True).decode("utf-8")
        self.assertTrue(conteudo.startswith("﻿"))
        linhas = list(csv.reader(io.StringIO(conteudo.lstrip("﻿")), delimiter=";"))
        self.assertEqual(len(linhas), 4)
        self.assertEqual(linhas[1][0], "DEMONSTRAÇÃO — DADOS FICTÍCIOS")
        self.assertEqual(linhas[1][2], "'=CMD()")
        self.assertEqual([l[8] for l in linhas[1:]], ["1234,56", "", ""])
        self.assertEqual(linhas[1][7], "1234,56")


class TestServidor(Base):
    def setUp(self):
        super().setUp()
        from sorria.servidor import Aplicacao
        self.config["servidor"]["porta"] = 0
        self.servico_ = self.servico([_lanc("L1", 5000)])
        self.servico_.executar()
        self.app = Aplicacao(self.config, self.caminho, self.servico_, self.servico_.regras)
        self.http = self.app.criar_servidor()
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.http.server_address[1]}"

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        super().tearDown()

    def get(self, caminho):
        with urllib.request.urlopen(self.base + caminho, timeout=5) as resposta:
            return resposta.status, resposta.headers, resposta.read()

    def post(self, caminho, corpo, cabecalho=True):
        cabecalhos = {"Content-Type": "application/json"}
        if cabecalho:
            cabecalhos["X-Painel-Sorria"] = "1"
        requisicao = urllib.request.Request(self.base + caminho, data=json.dumps(corpo).encode(),
                                            headers=cabecalhos, method="POST")
        try:
            with urllib.request.urlopen(requisicao, timeout=5) as resposta:
                return resposta.status, json.loads(resposta.read())
        except urllib.error.HTTPError as erro:
            return erro.code, json.loads(erro.read())

    def test_painel_e_modo_tv(self):
        status, _, corpo = self.get("/api/painel")
        self.assertEqual(status, 200)
        self.assertIn("123.456.789-09", corpo.decode())
        _, _, corpo = self.get("/api/painel?tv=1")
        self.assertNotIn("123.456.789-09", corpo.decode())
        _, _, corpo = self.get("/api/ocorrencias.csv?tv=1")
        self.assertNotIn("123.456.789-09", corpo.decode())

    def test_filtro_invalido_400(self):
        with self.assertRaises(urllib.error.HTTPError) as erro:
            self.get("/api/painel?inicio=xx")
        self.assertEqual(erro.exception.code, 400)

    def test_escrita_exige_cabecalho(self):
        status, _ = self.post("/api/coleta", {}, cabecalho=False)
        self.assertEqual(status, 403)

    def test_alterar_situacao(self):
        _, _, corpo = self.get("/api/painel")
        id_ = json.loads(corpo)["ocorrencias"][0]["id"]
        status, resposta = self.post(f"/api/ocorrencias/{id_}/situacao", {"situacao": "em_analise"})
        self.assertEqual((status, resposta["situacao"]), (200, "em_analise"))
        status, _ = self.post(f"/api/ocorrencias/{id_}/situacao", {"situacao": "apagada"})
        self.assertEqual(status, 400)

    def test_falha_simulada_so_em_demonstracao(self):
        status, _ = self.post("/api/coleta", {"simular_falha": True})
        self.assertEqual(status, 400)

    def test_agente_desativado(self):
        status, resposta = self.post("/api/agente/perguntar", {"pergunta": "resumo"})
        self.assertEqual(status, 503)
        self.assertIn("desativado", resposta["erro"])

    def test_estaticos(self):
        status, cabecalhos, _ = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("default-src 'self'", cabecalhos["Content-Security-Policy"])
        with self.assertRaises(urllib.error.HTTPError):
            self.get("/static/../sorria/db.py")


if __name__ == "__main__":
    unittest.main()
