"""Simulador LOCAL de telas do TOTVS WebApp, só para testar o executor do navegador.

Não reproduz o TOTVS real: imita o roteiro (login feito por uma pessoa, menu com
Pesquisar dentro de shadow DOM, Consulta Genérica, tabela SE2, gerenciador de
filtros, Exp. CSV com confirmação e download) e coloca botões de alteração
(Incluir, Alterar, Excluir, Baixar) ao lado, para provar que o agente nunca
clica neles. Todos os dados são FICTÍCIOS.
"""

from __future__ import annotations

import http.server
import json
import threading
from datetime import date

INDEX = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>TOTVS (simulado)</title></head>
<body><div id="app"></div><script>
const app = document.getElementById('app');
const registrar = (t) => fetch('/__clique', {method: 'POST', body: t});
document.addEventListener('click', (e) => {
  const alvo = e.composedPath().find((n) => n.tagName === 'BUTTON' || (n.getAttribute && n.getAttribute('role')));
  if (alvo) registrar((alvo.innerText || alvo.title || '').trim());
}, true);
class Pesquisa extends HTMLElement {
  connectedCallback() {
    const raiz = this.attachShadow({mode: 'open'});
    raiz.innerHTML = '<input placeholder="Pesquisar">';
    raiz.querySelector('input').addEventListener('keydown', (e) => {
      const valor = e.target.value;
      if (e.key === 'Enter') setTimeout(() => resultados(valor), 300);
    });
  }
}
customElements.define('wa-pesquisa', Pesquisa);
let logado = null;
async function ciclo() {
  const s = await (await fetch('/__estado')).json();
  if (s.logado !== logado) { logado = s.logado; logado ? menu() : login(); }
  setTimeout(ciclo, 300);
}
function login() {
  app.innerHTML = '<h3>Parâmetros iniciais</h3><label>Usuário <input id="u"></label>' +
    '<label>Senha <input type="password" id="p"></label><button>Entrar</button>';
}
function menu() {
  app.innerHTML = '<nav><span>Favoritos</span> <span>Recentes</span> <span>Consultas</span> <span>Relatórios</span></nav>' +
    '<wa-pesquisa></wa-pesquisa><div id="barra"><button>Incluir</button><button>Excluir</button></div>' +
    '<ul id="resultados"></ul><div id="dialogo"></div><div id="rotina"></div>';
}
function resultados(texto) {
  const ul = document.getElementById('resultados');
  ul.innerHTML = texto.toLowerCase().includes('consulta') ?
    '<li role="option">Consulta Genérica</li><li role="option">Consulta Genérica Relacional</li>' : '';
  ul.querySelector('li') && ul.querySelectorAll('li')[0].addEventListener('click', () => setTimeout(dialogoTabela, 400));
}
function dialogoTabela() {
  const d = document.getElementById('dialogo');
  d.innerHTML = '<div role="dialog"><h4>Consulta Genérica — tabela</h4><input placeholder="Tabela">' +
    '<div id="tabelas"></div><button id="confirmar">Confirmar</button><button>Cancelar</button></div>';
  let escolhida = null;
  d.querySelector('input').addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    const t = document.getElementById('tabelas');
    t.innerHTML = '<div role="row">SE1 - Contas a Receber</div><div role="row">SE2 - Contas a Pagar</div>';
    t.querySelectorAll('[role=row]').forEach((r) => r.addEventListener('click', () => { escolhida = r.innerText; }));
  });
  document.getElementById('confirmar').addEventListener('click', () => {
    if (!escolhida || !escolhida.startsWith('SE2')) return;
    d.innerHTML = '';
    document.getElementById('rotina').innerHTML = '<iframe id="grade" src="/grade" style="width:900px;height:500px"></iframe>';
  });
}
ciclo();
</script></body></html>"""

GRADE = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"></head><body>
<div><button>Filtrar</button><button>Exp. CSV</button><button>Alterar</button><button>Excluir</button>
<button>Baixar</button></div><p id="filtros">Filiais: Todas as filiais</p><div id="dialogo"></div>
<table><tr><td>dados fictícios</td></tr></table>
<script>
const registrar = (t) => fetch('/__clique', {method: 'POST', body: t});
document.addEventListener('click', (e) => {
  const alvo = e.target.closest('button,[role]');
  if (alvo) registrar((alvo.innerText || alvo.title || '').trim());
}, true);
let filtro = false;
const botao = (t) => [...document.querySelectorAll('button')].find((b) => b.innerText === t);
botao('Filtrar').addEventListener('click', () => {
  const d = document.getElementById('dialogo');
  d.innerHTML = '<div role="dialog"><h4>Gerenciador de filtros</h4>' +
    '<select id="campo"><option></option><option>Emissão</option><option>Vencimento</option><option>Fornecedor</option></select>' +
    '<select id="operador"><option></option><option>Igual a</option><option>Mês Atual</option><option>Entre</option></select>' +
    '<button id="aplicar">Aplicar</button><button>Cancelar</button></div>';
  document.getElementById('aplicar').addEventListener('click', () => {
    const campo = document.getElementById('campo').value, operador = document.getElementById('operador').value;
    d.innerHTML = '';
    filtro = campo === 'Vencimento' && operador === 'Mês Atual';
    if (filtro) document.getElementById('filtros').innerText += ' · Vencimento: Mês Atual';
  });
});
botao('Exp. CSV').addEventListener('click', () => {
  const d = document.getElementById('dialogo');
  d.innerHTML = '<div role="dialog"><p>Deseja exportar os registros?</p><button id="sim">Sim</button><button>Não</button></div>';
  document.getElementById('sim').addEventListener('click', () => {
    d.innerHTML = '<p>Gerando arquivo...</p>';
    setTimeout(() => {
      const a = document.createElement('a');
      a.href = '/__exportar?filtro=' + (filtro ? '1' : '0');
      document.body.append(a); a.click(); d.innerHTML = '';
    }, 800);
  });
});
</script></body></html>"""


class Simulador:
    def __init__(self):
        self.logado = False
        self.cliques: list[str] = []
        self.exportacoes = 0
        self.versao = 1
        simulador = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _enviar(self, corpo: bytes, tipo: str, extra: dict | None = None):
                self.send_response(200)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(corpo)))
                for chave, valor in (extra or {}).items():
                    self.send_header(chave, valor)
                self.end_headers()
                self.wfile.write(corpo)

            def do_GET(self):
                if self.path.startswith("/webapp"):
                    self._enviar(INDEX.encode(), "text/html; charset=utf-8")
                elif self.path.startswith("/grade"):
                    self._enviar(GRADE.encode(), "text/html; charset=utf-8")
                elif self.path.startswith("/__estado"):
                    self._enviar(json.dumps({"logado": simulador.logado}).encode(), "application/json")
                elif self.path.startswith("/__exportar"):
                    simulador.exportacoes += 1
                    corpo = simulador.csv("filtro=1" in self.path)
                    self._enviar(corpo, "text/csv", {"Content-Disposition": 'attachment; filename="SE2.csv"'})
                else:
                    self.send_error(404)

            def do_POST(self):
                corpo = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
                if self.path == "/__clique":
                    simulador.cliques.append(corpo)
                elif self.path == "/__login":  # a "pessoa" entra no TOTVS
                    simulador.logado = True
                self._enviar(b"{}", "application/json")

            def log_message(self, *args):
                pass

        self.http = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.endereco = f"http://127.0.0.1:{self.http.server_address[1]}/webapp/"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def csv(self, com_filtro: bool) -> bytes:
        hoje = date.today()
        mes = hoje.strftime("%m/%Y")
        venc = lambda dia: f"{dia:02d}/{mes}" if com_filtro else f"{dia:02d}/01/2020"
        valor_1 = "1.000,00" if self.versao == 1 else "1.100,00"
        linhas = [
            "Filial;Prefixo;No. Titulo;Parcela;Tipo;Natureza;Fornecedor;Loja;Nome Fornece;DT Emissao;Vencimento;"
            "Vencto Real;Vlr.Titulo;Saldo;DT Baixa;Historico",
            f"016501;MAT;000000001;;NF;20101;000123;01;FORNECEDOR FICTICIO;01/{mes};{venc(5)};{venc(5)};{valor_1};{valor_1};;TESTE",
            f"017401;LAB;000000002;A;NF;20102;000124;01;LABORATORIO FICTICIO;01/{mes};{venc(9)};{venc(9)};250,50;0,00;;TESTE",
            f"031801;FOL;000000003;;NF;30101;000900;01;COLABORADOR FICTICIO;01/{mes};{venc(12)};{venc(12)};5.000,00;5.000,00;;TESTE",
        ]
        total = 100000 + (10000 if self.versao != 1 else 0) + 25050 + 500000
        reais = f"{total // 100:,}".replace(",", ".") + f",{total % 100:02d}"
        linhas.append(f"TOTAL GERAL;;;;;;;;;;;;{reais};;;")
        return ("\n".join(linhas) + "\n").encode("cp1252")

    def fechar(self):
        self.http.shutdown()
        self.http.server_close()
