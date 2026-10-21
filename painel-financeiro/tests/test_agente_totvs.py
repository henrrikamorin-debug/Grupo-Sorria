"""Testes do agente TOTVS (Contas a Pagar SE2). Todos os dados aqui são DE TESTE."""

from __future__ import annotations

import json
import os
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from test_painel import Base

from sorria import config as cfg
from sorria import db, relatorio
from sorria.acesso import definir_proprietario
from sorria.analise import Filtros, montar_painel
from sorria.cadastros import salvar_filiais
from sorria.totvs.execucao import AgenteTotvs
from sorria.totvs.se2 import ArquivoInvalido, converter_data, converter_valor, ler_exportacao

HOJE = date.today()
MES = HOJE.strftime("%m/%Y")
CABECALHO = ("Filial;Prefixo;No. Titulo;Parcela;Tipo;Natureza;Fornecedor;Loja;Nome Fornece;DT Emissao;"
             "Vencimento;Vencto Real;Vlr.Titulo;Saldo;DT Baixa;Historico")
CADASTRO = {"016501": {"nome": "GOIÂNIA I", "divisao": "TICKET 1"},
            "017401": {"nome": "ANÁPOLIS I", "divisao": "TICKET 2"},
            "031801": {"nome": "ESCRITÓRIO", "divisao": "TICKET 2"}}


def linha(filial="016501", numero="000012345", valor="1.234,56", dia=10, fornecedor="000123", saldo=None,
          prefixo="MAT", parcela="", nome="FORNECEDOR DE TESTE", natureza="20101", mes=None):
    venc = (mes or HOJE).replace(day=dia).strftime("%d/%m/%Y")
    return (f"{filial};{prefixo};{numero};{parcela};NF;{natureza};{fornecedor};01;{nome};01/{MES};{venc};{venc};"
            f"{valor};{saldo if saldo is not None else valor};;TESTE")


class BaseAgente(Base):
    def setUp(self):
        super().setUp()
        salvar_filiais(CADASTRO, cfg.caminho_filiais())
        self.config["agente"]["espera_entre_tentativas_segundos"] = 0
        self.config["agente"]["segundos_tamanho_estavel"] = 0
        self.config["agente"]["intervalo_verificacao_segundos"] = 0
        self.agente = AgenteTotvs(self.config, cfg.caminho_filiais(), dormir=lambda s: None)
        self.pasta_csv = Path(self.tmp.name) / "csv"
        self.pasta_csv.mkdir()

    def csv(self, nome: str, linhas: list[str], cabecalho: str = CABECALHO, mtime: float | None = None) -> Path:
        caminho = self.pasta_csv / nome
        caminho.write_bytes(("\n".join([cabecalho, *linhas]) + "\n").encode("cp1252"))
        if mtime is not None:
            os.utime(caminho, (mtime, mtime))
        return caminho

    def importar(self, caminho: Path, **kw) -> dict:
        return self.agente.executar("manual", arquivo=caminho, **kw)

    def banco(self):
        return db.fechando(db.conectar(cfg.caminho_banco({"modo": "real"})))

    def total(self, publico: bool = False):
        with self.banco() as c:
            where = " WHERE restrito = 0" if publico else ""
            return tuple(c.execute(f"SELECT COUNT(*), COALESCE(SUM(valor_centavos), 0) FROM titulos_pagar{where}").fetchone())


class TestLeitura(unittest.TestCase):
    def test_valores_datas_e_codigos_brasileiros(self):
        self.assertEqual(converter_valor("1.234,56"), Decimal("1234.56"))
        self.assertEqual(converter_valor("R$ 10,05"), Decimal("10.05"))
        self.assertEqual(converter_valor("(1.000,00)"), Decimal("-1000.00"))
        self.assertEqual(converter_valor("0,10") + converter_valor("0,20"), Decimal("0.30"))  # sem erro de float
        self.assertEqual(converter_data("05/10/2026"), date(2026, 10, 5))
        self.assertEqual(converter_data("05/10/26"), date(2026, 10, 5))
        self.assertEqual(converter_data("20261005"), date(2026, 10, 5))
        self.assertIsNone(converter_data("  /  /  "))
        with self.assertRaises(ValueError):
            converter_data("31/02/2026")
        conteudo = (CABECALHO + "\n" + linha(filial="16501", numero="000000042", valor="0,10") + "\n").encode("cp1252")
        t = ler_exportacao(conteudo).titulos[0]
        self.assertEqual((t.filial, t.numero, t.fornecedor, t.valor_centavos), ("016501", "000000042", "000123", 10))
        self.assertEqual(t.vencimento, HOJE.replace(day=10).isoformat())
        self.assertNotEqual(ler_exportacao(conteudo).avisos, [])  # zeros completados ficam registrados

    def test_cabecalho_tecnico_e_vencimento_real_distinto(self):
        conteudo = ("E2_FILIAL;E2_NUM;E2_FORNECE;E2_VENCTO;E2_VENCREA;E2_VALOR\n"
                    "016501;000000001;000123;10/10/2026;12/10/2026;100,00\n").encode()
        t = ler_exportacao(conteudo).titulos[0]
        self.assertEqual((t.vencimento, t.vencimento_real), ("2026-10-10", "2026-10-12"))

    def test_arquivo_invalido(self):
        with self.assertRaises(ArquivoInvalido):
            ler_exportacao(b"nome;idade\nana;30\n")
        with self.assertRaises(ArquivoInvalido):
            ler_exportacao(b"Filial;Prefixo;No. Titulo;Tipo\n016501;MAT;1;NF\n")  # sem vencimento/valor/fornecedor


class TestImportacao(BaseAgente):
    def test_reimportar_nao_duplica(self):
        linhas = [linha(numero="000000001"), linha(numero="000000002", valor="10,00", filial="017401")]
        r1 = self.importar(self.csv("teste_a.csv", linhas))
        self.assertEqual((r1["situacao"], r1["novos"]), ("importada", 2))
        antes = self.total()
        r2 = self.importar(self.csv("teste_b.csv", linhas))  # mesmo conteúdo, outro nome
        self.assertEqual(r2["situacao"], "ignorada")
        r3 = self.importar(self.csv("teste_c.csv", list(reversed(linhas))))  # conteúdo diferente, mesmos títulos
        self.assertEqual((r3["situacao"], r3["novos"], r3["atualizados"]), ("importada", 0, 2))
        self.assertEqual(self.total(), antes)

    def test_atualiza_valor_e_nao_apaga_ausentes(self):
        self.importar(self.csv("teste_a.csv", [linha(numero="000000001"), linha(numero="000000002", filial="017401")]))
        self.importar(self.csv("teste_b.csv", [linha(numero="000000001", valor="99,00"), linha(numero="000000003", filial="017401")]))
        with self.banco() as c:
            titulos = dict(c.execute("SELECT numero, valor_centavos FROM titulos_pagar"))
        self.assertEqual(titulos, {"000000001": 9900, "000000002": 123456, "000000003": 123456})

    def test_periodo_incorreto_rejeita_lote(self):
        mes_passado = (HOJE.replace(day=1) - timedelta(days=1))
        r = self.importar(self.csv("teste.csv", [linha(), linha(numero="2", filial="017401", mes=mes_passado)]))
        self.assertEqual(r["situacao"], "rejeitada")
        self.assertIn("fora de", r["mensagem"])
        self.assertEqual(self.total(), (0, 0))

    def test_filial_unica_e_linhas_invalidas(self):
        r = self.importar(self.csv("teste.csv", [linha(numero="1"), linha(numero="2")]))
        self.assertEqual(r["situacao"], "rejeitada")
        self.assertIn("única filial", r["mensagem"])
        r = self.importar(self.csv("teste2.csv", [linha(numero="1"), linha(numero="2", filial="017401", valor="abc")]))
        self.assertEqual(r["situacao"], "rejeitada")  # 50% de linhas inválidas > limite
        with self.banco() as c:
            self.assertGreater(c.execute("SELECT COUNT(*) FROM importacoes WHERE situacao='rejeitada'").fetchone()[0], 1)

    def test_arquivo_antigo_exige_confirmacao(self):
        antigo = time.time() - 3 * 86400
        r = self.importar(self.csv("teste.csv", [linha(), linha(numero="2", filial="017401")], mtime=antigo))
        self.assertEqual(r["situacao"], "rejeitada")
        r = self.importar(self.csv("teste2.csv", [linha(), linha(numero="2", filial="017401")], mtime=antigo),
                          confirmar_arquivo_antigo=True)
        self.assertEqual(r["situacao"], "importada")

    def test_chave_repetida_e_mudanca_de_layout(self):
        r = self.importar(self.csv("teste.csv", [linha(), linha(), linha(numero="9", filial="017401")]))
        self.assertIn("repetida", r["mensagem"])
        self.importar(self.csv("ok.csv", [linha(), linha(numero="2", filial="017401")]))
        sem_parcela = CABECALHO.replace("Parcela;", "")
        linhas = [l.replace(";;NF;", ";NF;", 1) for l in [linha(numero="7"), linha(numero="8", filial="017401")]]
        r = self.importar(self.csv("layout.csv", linhas, cabecalho=sem_parcela))
        self.assertEqual(r["situacao"], "rejeitada")
        self.assertIn("chave", r["mensagem"])

    def test_classificacao_nao_usa_nome_do_fornecedor(self):
        self.importar(self.csv("teste.csv", [
            linha(numero="1", nome="MATERIAL PARA ESCRITORIO LTDA"),       # nome não restringe
            linha(numero="2", filial="031801"),                              # filial restrita
            linha(numero="3", filial="999999", fornecedor="000777")]))       # sem cadastro: incerta
        with self.banco() as c:
            restritos = dict(c.execute("SELECT numero, motivo_restricao FROM titulos_pagar WHERE restrito = 1"))
        self.assertEqual(set(restritos), {"2", "3"})
        self.assertIn("incerta", restritos["3"])


class TestPainelAgente(BaseAgente):
    def setUp(self):
        super().setUp()
        self.config["modo"] = "real"
        self.linhas = [linha(numero="1", valor="1.000,00"), linha(numero="2", filial="017401", valor="250,50", saldo="0,00"),
                       linha(numero="3", filial="031801", valor="5.000,00", nome="COLABORADOR DE TESTE")]

    def painel(self, autorizado: bool):
        with self.banco() as c:
            inicio = HOJE.replace(day=1).isoformat()
            return montar_painel(c, Filtros(inicio=inicio), ocultar_filiais=not autorizado)

    def test_totais_do_painel_conferem_com_o_arquivo(self):
        r = self.importar(self.csv("teste.csv", self.linhas))
        self.assertEqual(r["painel"]["situacao"], "sucesso")
        dono, publico = self.painel(True), self.painel(False)
        self.assertEqual(dono["indicadores"]["registros_analisados"], 3)
        self.assertEqual(publico["indicadores"]["registros_analisados"], 2)
        self.assertEqual(r["valor_publico_centavos"] + r["valor_restrito_centavos"], 100000 + 25050 + 500000)
        with self.banco() as c:
            soma = c.execute("SELECT SUM(valor_centavos) FROM lancamentos WHERE restrito = 0").fetchone()[0]
        self.assertEqual(soma, r["valor_publico_centavos"])

    def test_falha_preserva_ultima_versao_valida(self):
        self.importar(self.csv("teste.csv", self.linhas))
        antes = self.painel(True)["indicadores"]
        r = self.importar(self.csv("ruim.csv", ["linha;quebrada"]))
        self.assertEqual(r["situacao"], "rejeitada")
        self.assertEqual(self.painel(True)["indicadores"], antes)
        from sorria.conectores.totvs_se2 import ConectorTotvsSE2
        from sorria.situacao import montar_situacao

        class Servico:
            conector = ConectorTotvsSE2(cfg.caminho_banco({"modo": "real"}))
            em_andamento = agendador_ativo = False
            proxima_execucao = None
        with self.banco() as c:
            s = montar_situacao(c, self.config, Servico(), autorizado=False)
        self.assertEqual(s["nivel"], "alerta")
        self.assertTrue(s["ultima_tentativa_falhou"])
        self.assertEqual(s["importacao"]["arquivo_nome"], "teste.csv")   # a última válida, não a falha
        self.assertIsNone(s["importacao"]["restritos"])
        self.assertIsNone(s["importacao"]["linhas_lidas"])
        self.assertTrue(s["conferencia"]["confere"])

    def test_outro_usuario_nao_recebe_dados_do_escritorio(self):
        from sorria.servidor import Aplicacao
        from sorria.conectores.totvs_se2 import ConectorTotvsSE2
        from sorria.coleta import ServicoColeta
        from sorria.regras import regras_do_modo
        self.importar(self.csv("teste.csv", self.linhas))
        definir_proprietario(cfg.caminho_senha(), "dono", "senha-de-teste-1")
        self.config["servidor"]["porta"] = 0
        caminho = cfg.caminho_banco({"modo": "real"})
        servico = ServicoColeta(self.config, caminho, ConectorTotvsSE2(caminho), regras_do_modo("real", self.config))
        app = Aplicacao(self.config, caminho, servico, servico.regras)
        http = app.criar_servidor()
        threading.Thread(target=http.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{http.server_address[1]}"

        def req(rota, corpo=None, cookie=None):
            cab = {"Content-Type": "application/json", "X-Painel-Sorria": "1", **({"Cookie": cookie} if cookie else {})}
            r = urllib.request.Request(base + rota, data=json.dumps(corpo).encode() if corpo is not None else None,
                                       headers=cab, method="POST" if corpo is not None else "GET")
            try:
                with urllib.request.urlopen(r, timeout=5) as resp:
                    return resp.status, resp.headers, resp.read().decode()
            except urllib.error.HTTPError as erro:
                return erro.code, erro.headers, erro.read().decode()
        try:
            inicio = HOJE.replace(day=1).isoformat()
            for rota in (f"/api/painel?inicio={inicio}", f"/api/ocorrencias.csv?inicio={inicio}", "/api/situacao",
                         f"/api/painel?inicio={inicio}&clinica=ESCRIT%C3%93RIO", "/api/agente/contexto"):
                _, _, corpo = req(rota)
                for proibido in ('"filial": "031801"', ";031801;", "COLABORADOR", "5.000,00", "500000",
                                 "625050", '"titulos": 3', '"registros": 3'):
                    self.assertNotIn(proibido, corpo, f"{rota}: {proibido}")
            status, _, _ = req("/api/acesso/desbloquear", {"usuario": "outra.pessoa", "senha": "senha-de-teste-1"})
            self.assertEqual(status, 401)
            status, cab, _ = req("/api/acesso/desbloquear", {"usuario": "dono", "senha": "senha-de-teste-1"})
            cookie = cab["Set-Cookie"].split(";")[0]
            _, _, corpo = req(f"/api/painel?inicio={inicio}", cookie=cookie)
            self.assertIn('"filial": "031801"', corpo)
            _, _, corpo = req(f"/api/painel?inicio={inicio}&tv=1", cookie=cookie)
            self.assertNotIn('"filial": "031801"', corpo)  # TV nunca mostra
            mes = HOJE.strftime("%Y-%m")
            req("/api/relatorios", {"mes": mes}, cookie=cookie)
            _, _, pagina = req(f"/relatorios/relatorio-{mes}.html")
            self.assertNotIn("031801", pagina)
            self.assertNotIn("ESCRITÓRIO", pagina)
        finally:
            http.shutdown()
            http.server_close()


class TestExecucao(BaseAgente):
    def test_sem_exportacao_nova(self):
        self.csv("velho.csv", [linha()], mtime=time.time() - 3600)
        self.agente.entrada = self.pasta_csv
        r = self.agente.executar("agendada", espera_minutos=0)
        self.assertEqual(r["situacao"], "sem_arquivo")

    def test_aguarda_arquivo_novo_na_entrada(self):
        self.pasta_csv = self.agente.entrada
        self.pasta_csv.mkdir(parents=True, exist_ok=True)
        self.csv("antigo.csv", [linha(numero="9"), linha(numero="8", filial="017401")], mtime=time.time() - 3600)
        novo = self.csv("novo.csv", [linha(numero="1"), linha(numero="2", filial="017401")])
        r = self.agente.executar("claude_code", espera_minutos=0)
        self.assertEqual((r["situacao"], r["situacao_execucao"]), ("importada", "sucesso"))
        self.assertFalse(novo.exists())  # movido para processados
        with self.banco() as c:
            self.assertEqual({r[0] for r in c.execute("SELECT numero FROM titulos_pagar")}, {"1", "2"})

    def test_execucoes_simultaneas_sao_bloqueadas(self):
        outro = AgenteTotvs(self.config, cfg.caminho_filiais(), dormir=lambda s: None)
        with self.banco() as c:
            self.assertTrue(outro._adquirir(c, -1))
        r = self.agente.executar("agendada", espera_minutos=0)
        self.assertEqual(r["situacao"], "bloqueada")

    def test_retomada_apos_interrupcao(self):
        arquivo = self.csv("interrompido.csv", [linha(numero="1"), linha(numero="2", filial="017401")])
        agora = datetime.now(timezone.utc)
        with self.banco() as c:
            c.execute("INSERT INTO execucoes_agente (iniciada_em, situacao, origem, etapa, periodo_inicio, arquivo_caminho) "
                      "VALUES (?, 'em_andamento', 'agendada', 'importando', ?, ?)",
                      ((agora - timedelta(minutes=1)).isoformat(timespec="seconds"),
                       HOJE.replace(day=1).isoformat(), str(arquivo)))
        r = self.agente.executar("agendada", espera_minutos=0)
        self.assertEqual(r["situacao"], "importada")
        with self.banco() as c:
            situacoes = [x[0] for x in c.execute("SELECT situacao FROM execucoes_agente ORDER BY id")]
        self.assertEqual(situacoes, ["interrompida", "sucesso"])

    def test_tentativas_limitadas_para_falha_temporaria(self):
        import sorria.totvs.execucao as modulo
        original = modulo.importar_arquivo
        chamadas = []

        def instavel(*a, **kw):
            chamadas.append(1)
            if len(chamadas) < 3:
                raise PermissionError("arquivo em uso pelo navegador")
            return original(*a, **kw)
        modulo.importar_arquivo = instavel
        try:
            r = self.importar(self.csv("teste.csv", [linha(), linha(numero="2", filial="017401")]))
        finally:
            modulo.importar_arquivo = original
        self.assertEqual((r["situacao"], len(chamadas)), ("importada", 3))
        modulo.importar_arquivo = lambda *a, **kw: (_ for _ in ()).throw(PermissionError("sempre"))
        try:
            r = self.importar(self.csv("teste2.csv", [linha(numero="5"), linha(numero="6", filial="017401")]))
        finally:
            modulo.importar_arquivo = original
        self.assertEqual(r["situacao"], "falha")


if __name__ == "__main__":
    unittest.main()
