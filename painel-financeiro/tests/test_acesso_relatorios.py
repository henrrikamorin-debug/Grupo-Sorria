"""Testes de categorias por prefixo, cadastro de filiais, área restrita e relatório mensal."""

from __future__ import annotations

import json
import sqlite3
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

from test_painel import HOJE, Base, ConectorFixo, _lanc

from sorria import config as cfg
from sorria import db, relatorio
from sorria.acesso import AcessoNegado, MuitasTentativas, Sessoes, conferir_senha, definir_senha
from sorria.analise import Filtros
from sorria.cadastros import classificar_categoria, importar_filiais_xlsx
from sorria.coleta import ServicoColeta, _consolidar
from sorria.conectores.base import Lancamento, ResultadoColeta

ESCRITORIO = "031801"


def _titulo(ref, filial, prefixo, valor, dia=HOJE):
    return Lancamento(referencia=ref, clinica="", categoria="", data=dia.isoformat(), valor_centavos=valor,
                      favorecido="Pessoa Teste", pessoa_fisica=True, documento="123.456.789-09",
                      filial=filial, titulo=f"0000{ref}", prefixo=prefixo)


class TestCategorias(unittest.TestCase):
    def test_sem_prefixo_vira_diversos(self):
        mapa = {"MAT": "Materiais"}
        self.assertEqual(classificar_categoria(None, mapa), "Diversos")
        self.assertEqual(classificar_categoria("   ", mapa), "Diversos")
        self.assertEqual(classificar_categoria("mat ", mapa), "Materiais")
        self.assertEqual(classificar_categoria("XYZ", mapa), "Prefixo XYZ")

    def test_consolidacao_usa_cadastro_e_prefixo(self):
        config = json.loads(json.dumps(cfg.PADRAO))
        config["categorias"]["por_prefixo"] = {"FOL": "Folha"}
        resultado = ResultadoColeta([_titulo("1", "016501", "FOL", 100), _titulo("2", "999999", "", 100)],
                                    simulada=False)
        lancamentos = _consolidar(resultado, config, {"016501": {"nome": "GOIÂNIA I"}})
        self.assertEqual([(l.clinica, l.categoria) for l in lancamentos],
                         [("GOIÂNIA I", "Folha"), ("Filial 999999", "Diversos")])


class TestFiliais(unittest.TestCase):
    def test_importa_planilha(self):
        linhas = [["DIVISÃO", "NOME FILIAL ", " FILIAL ", "FILIAL TOTVS", "CNPJ ", "UF"],
                  ["TICKET 1", "  EMPRESA A LTDA", "GOIÂNIA I ", "016501", "31.624.639/0001-71", "GO"],
                  ["TICKET 2", "EMPRESA B", "ESCRITÓRIO", "031801", "51.039.604/0001-82", "GO"],
                  ["TICKET 2", "", "SEM CÓDIGO", "", "", "DF"],
                  ["TICKET 3", "EMPRESA C", "PARACATU", "036401", "27.324.440/001-40", "MG"]]

        def celula(coluna, linha, valor):
            return (f'<c r="{chr(65 + coluna)}{linha}" t="inlineStr"><is><t>{valor}</t></is></c>' if valor else "")

        xml_linhas = "".join(f'<row r="{i + 1}">' + "".join(celula(j, i + 1, v) for j, v in enumerate(l)) + "</row>"
                             for i, l in enumerate(linhas))
        ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        rel = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
        with self.subTest("xlsx"), self._tmp() as pasta:
            arquivo = Path(pasta) / "filiais.xlsx"
            with zipfile.ZipFile(arquivo, "w") as z:
                z.writestr("xl/workbook.xml", f'<workbook {ns} {rel}><sheets><sheet name="TOTVS" sheetId="1" r:id="rId1"/></sheets></workbook>')
                z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                           '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/></Relationships>')
                z.writestr("xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData>{xml_linhas}</sheetData></worksheet>")
            cadastro, avisos = importar_filiais_xlsx(arquivo)
        self.assertEqual(sorted(cadastro), ["016501", "031801", "036401"])
        self.assertEqual(cadastro["016501"]["nome"], "GOIÂNIA I")
        self.assertEqual(cadastro["016501"]["razao_social"], "EMPRESA A LTDA")
        self.assertEqual(cadastro["031801"]["divisao"], "TICKET 2")
        self.assertTrue(any("SEM CÓDIGO" in a for a in avisos))
        self.assertTrue(any("036401" in a and "CNPJ" in a for a in avisos))

    @staticmethod
    def _tmp():
        import tempfile
        return tempfile.TemporaryDirectory()


class TestSenha(Base):
    def test_hash_e_conferencia(self):
        caminho = cfg.caminho_senha()
        with self.assertRaises(ValueError):
            definir_senha(caminho, "curta")
        definir_senha(caminho, "senha-boa-123")
        self.assertNotIn("senha-boa-123", caminho.read_text())
        self.assertTrue(conferir_senha(caminho, "senha-boa-123"))
        self.assertFalse(conferir_senha(caminho, "senha-errada"))

    def test_sessoes_e_limite_de_tentativas(self):
        sessoes = Sessoes(cfg.caminho_senha(), minutos=30)
        with self.assertRaises(AcessoNegado):
            sessoes.desbloquear("qualquer")  # sem senha definida: bloqueado
        definir_senha(cfg.caminho_senha(), "senha-boa-123")
        token, _ = sessoes.desbloquear("senha-boa-123")
        self.assertTrue(sessoes.valida(token))
        sessoes.encerrar(token)
        self.assertIsNone(sessoes.valida(token))
        for _ in range(5):  # MAX_TENTATIVAS erradas
            with self.assertRaises(AcessoNegado):
                sessoes.desbloquear("errada!!")
        with self.assertRaises(MuitasTentativas):
            sessoes.desbloquear("senha-boa-123")

    def test_sessao_expira(self):
        definir_senha(cfg.caminho_senha(), "senha-boa-123")
        sessoes = Sessoes(cfg.caminho_senha(), minutos=0.0001)
        token, _ = sessoes.desbloquear("senha-boa-123")
        import time
        time.sleep(0.05)
        self.assertIsNone(sessoes.valida(token))


class TestServidorRestrito(Base):
    def setUp(self):
        super().setUp()
        from sorria.servidor import Aplicacao
        self.config["servidor"]["porta"] = 0
        conector = ConectorFixo([_titulo("1", "016501", "MAT", 5000), _titulo("2", ESCRITORIO, "FOL", 9000)])
        regra_todos = __import__("test_painel")._regra("R1", lambda l: True)
        self.servico_ = ServicoColeta(self.config, self.caminho, conector, [regra_todos])
        self.servico_.executar()
        self.app = Aplicacao(self.config, self.caminho, self.servico_, self.servico_.regras)
        self.http = self.app.criar_servidor()
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.http.server_address[1]}"

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        super().tearDown()

    def req(self, caminho, corpo=None, cookie=None):
        cabecalhos = {"Content-Type": "application/json", "X-Painel-Sorria": "1"}
        if cookie:
            cabecalhos["Cookie"] = cookie
        dados = json.dumps(corpo).encode() if corpo is not None else None
        requisicao = urllib.request.Request(self.base + caminho, data=dados, headers=cabecalhos,
                                            method="POST" if corpo is not None else "GET")
        try:
            with urllib.request.urlopen(requisicao, timeout=5) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as erro:
            return erro.code, erro.headers, erro.read()

    def filiais_no_painel(self, sufixo="", cookie=None):
        _, _, corpo = self.req("/api/painel" + sufixo, cookie=cookie)
        dados = json.loads(corpo)
        return {o["filial"] for o in dados["ocorrencias"]}, dados

    def test_escritorio_so_com_senha_e_nunca_na_tv(self):
        filiais, dados = self.filiais_no_painel()
        self.assertEqual(filiais, {"016501"})
        self.assertEqual(dados["indicadores"]["registros_analisados"], 1)
        self.assertFalse(dados["acesso"]["senha_definida"])
        status, _, _ = self.req("/api/acesso/desbloquear", {"senha": "qualquer-coisa"})
        self.assertEqual(status, 401)

        definir_senha(cfg.caminho_senha(), "senha-boa-123")
        status, _, _ = self.req("/api/acesso/desbloquear", {"senha": "errada-123"})
        self.assertEqual(status, 401)
        status, cabecalhos, _ = self.req("/api/acesso/desbloquear", {"senha": "senha-boa-123"})
        self.assertEqual(status, 200)
        cookie_bruto = cabecalhos["Set-Cookie"]
        self.assertIn("HttpOnly", cookie_bruto)
        cookie = cookie_bruto.split(";")[0]

        filiais, dados = self.filiais_no_painel(cookie=cookie)
        self.assertEqual(filiais, {"016501", ESCRITORIO})
        self.assertTrue(dados["acesso"]["desbloqueado"])
        filiais, _ = self.filiais_no_painel("?tv=1", cookie=cookie)
        self.assertEqual(filiais, {"016501"})
        _, _, csv_restrito = self.req("/api/ocorrencias.csv", cookie=cookie)
        _, _, csv_livre = self.req("/api/ocorrencias.csv")
        self.assertIn(ESCRITORIO, csv_restrito.decode())
        self.assertNotIn(ESCRITORIO, csv_livre.decode())

        self.req("/api/acesso/bloquear", {}, cookie=cookie)
        filiais, _ = self.filiais_no_painel(cookie=cookie)
        self.assertEqual(filiais, {"016501"})

    def test_situacao_de_ocorrencia_restrita_exige_senha(self):
        with db.fechando(db.conectar(self.caminho)) as conexao:
            id_ = conexao.execute("SELECT id FROM ocorrencias WHERE filial = ?", (ESCRITORIO,)).fetchone()[0]
        status, _, _ = self.req(f"/api/ocorrencias/{id_}/situacao", {"situacao": "resolvida"})
        self.assertEqual(status, 401)

    def test_relatorio_pela_api(self):
        status, _, corpo = self.req("/api/relatorios", {"mes": HOJE.strftime("%Y-%m")})
        self.assertEqual(status, 200)
        _, _, lista = self.req("/api/relatorios")
        self.assertEqual(json.loads(lista)["relatorios"][0]["mes"], HOJE.strftime("%Y-%m"))
        status, _, pagina = self.req(f"/relatorios/relatorio-{HOJE:%Y-%m}.html")
        self.assertEqual(status, 200)
        self.assertNotIn("FOL", pagina.decode().split("<main>")[1].split("Ocorrências por regra")[0].replace("FOLHA", ""))
        status, _, _ = self.req("/relatorios/../acesso.json")
        self.assertEqual(status, 404)


class TestRelatorio(Base):
    def test_ranking_por_percentual_e_sem_area_restrita(self):
        self.config["relatorio_mensal"]["minimo_lancamentos"] = 2
        dia = date(2026, 9, 15)
        lancs = (
            [_titulo(f"A{i}", "000001", "MAT", 1000, dia) for i in range(10)]          # 2 de 10 com problema
            + [_titulo(f"B{i}", "000002", "MAT", 500 + i, dia) for i in range(4)]      # 2 de 4 com problema
            + [_titulo("C0", "000003", "MAT", 1000, dia)]                               # 1 lançamento: fora
            + [_titulo(f"E{i}", ESCRITORIO, "FOL", 99999, dia) for i in range(3)]
        )
        problema = {"A0", "A1", "B0", "B1", "C0", "E0", "E1"}
        regra = __import__("test_painel")._regra("R1", lambda l: l.referencia in problema)
        servico = ServicoColeta(self.config, self.caminho, ConectorFixo(lancs), [regra])
        servico.executar()
        filiais = {"000001": {"nome": "Filial A", "divisao": "TICKET 1"}, "000002": {"nome": "Filial B"},
                   "000003": {"nome": "Filial C"}}
        with db.fechando(db.conectar(self.caminho)) as conexao:
            dados = relatorio.calcular(conexao, self.config, "2026-09", filiais, ocultar_filiais=[ESCRITORIO])
            relatorio.gerar_e_salvar(conexao, self.config, "2026-09", filiais, cfg.pasta_relatorios(self.config),
                                     ocultar_filiais=[ESCRITORIO])
        self.assertEqual([l["clinica"] for l in dados["ranking"]], ["Filial 000002", "Filial 000001"])
        self.assertEqual(dados["ranking"][0]["taxa"], 0.5)
        self.assertEqual([l["clinica"] for l in dados["fora_do_ranking"]], ["Filial 000003"])
        self.assertEqual(dados["totais"]["registros"], 15)
        self.assertEqual(dados["totais"]["ocorrencias"], 5)
        pagina = (cfg.pasta_relatorios(self.config) / "relatorio-2026-09.html").read_text(encoding="utf-8")
        self.assertNotIn("123.456.789-09", pagina)
        self.assertNotIn(ESCRITORIO, pagina)
        self.assertEqual(relatorio.listar(cfg.pasta_relatorios(self.config))[0]["mes"], "2026-09")

    def test_mes_anterior(self):
        self.assertEqual(relatorio.mes_anterior(date(2026, 1, 1)), "2025-12")
        self.assertEqual(relatorio.mes_anterior(date(2026, 10, 31)), "2026-09")
        with self.assertRaises(ValueError):
            relatorio.calcular(None, self.config, "2026-13", {})


class TestMigracao(unittest.TestCase):
    def test_banco_antigo_ganha_colunas(self):
        import tempfile
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "antigo.sqlite3"
            conexao = sqlite3.connect(caminho)
            conexao.execute("CREATE TABLE lancamentos (referencia TEXT PRIMARY KEY, clinica TEXT NOT NULL, "
                            "categoria TEXT NOT NULL, data TEXT NOT NULL, valor_centavos INTEGER, "
                            "descricao TEXT NOT NULL DEFAULT '', favorecido TEXT, pessoa_fisica INTEGER NOT NULL DEFAULT 0, "
                            "documento TEXT, dados_bancarios TEXT, extras TEXT NOT NULL DEFAULT '{}', coleta_id INTEGER NOT NULL)")
            conexao.close()
            db.inicializar(caminho, "demonstracao")
            with db.fechando(db.conectar(caminho)) as c:
                colunas = {r["name"] for r in c.execute("PRAGMA table_info(lancamentos)")}
            self.assertTrue({"filial", "titulo", "prefixo"} <= colunas)


if __name__ == "__main__":
    unittest.main()
