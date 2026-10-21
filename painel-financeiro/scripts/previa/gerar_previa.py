"""Gera uma prévia estática (um único HTML) do painel com dados fictícios.

Uso (na pasta painel-financeiro):
    python3 scripts/previa/gerar_previa.py . previa.html scripts/previa/mock.js
    python3 scripts/previa/gerar_previa.py . painel-publicado.html scripts/previa/mock.js publicar

A prévia nunca usa dados reais: ela roda sempre o conector de demonstração.
"""
import json, re, sys, tempfile
from pathlib import Path
raiz = Path(sys.argv[1]); saida = Path(sys.argv[2])
sys.path.insert(0, str(raiz))
import os
os.environ["SORRIA_DADOS"] = tempfile.mkdtemp()
from sorria import config as cfg, db
from sorria.coleta import ServicoColeta
from sorria.conectores import criar_conector
from sorria.regras import regras_do_modo
from sorria.analise import Filtros, montar_painel
from sorria.situacao import montar_situacao
import logging; logging.disable(logging.CRITICAL)

config = cfg.carregar()
config["modo"] = "demonstracao"  # nunca publicar dados reais
caminho = cfg.caminho_banco(config)
db.inicializar(caminho, config["modo"])
servico = ServicoColeta(config, caminho, criar_conector(config), regras_do_modo(config["modo"]))
servico.executar("inicial")
with db.fechando(db.conectar(caminho)) as cx:
    # A prévia não tem senha: a área restrita (escritório) fica sempre de fora.
    restritas = config["acesso_restrito"]["filiais"]
    normal = montar_painel(cx, Filtros(), ocultar_filiais=restritas)
    tv = montar_painel(cx, Filtros(), tv=True, ocultar_filiais=restritas)
    situacao = montar_situacao(cx, config, servico)
    lanc = [list(r) for r in cx.execute(
        f"SELECT clinica, categoria, data, responsavel FROM lancamentos WHERE filial IS NULL OR filial NOT IN "
        f"({', '.join('?' * len(restritas))})", restritas)] if restritas else [
        list(r) for r in cx.execute("SELECT clinica, categoria, data, responsavel FROM lancamentos")]
situacao["historico"] = situacao["historico"][:1]
dados = {"normal": normal["ocorrencias"], "tv": tv["ocorrencias"], "opcoes": normal["opcoes"],
         "lancamentos": lanc, "situacao": situacao, "televisao": config["televisao"]}

web = raiz / "web"
def sem_modulos(js):
    js = re.sub(r'^import[\s\S]*?from\s+"[^"]+";\n', "", js, flags=re.M)
    return re.sub(r"^export ", "", js, flags=re.M)
js = "\n".join(sem_modulos((web / "js" / f).read_text()) for f in ("formato.js", "graficos.js", "app.js"))
js = js.replace('history.replaceState(null, "", url);', 'try { history.replaceState(null, "", url); } catch {}')
js = js.replace('location.href = `/api/ocorrencias.csv?${parametros(estado.tv ? { tv: "1" } : {})}`;',
                'baixarCsvPrevia();')

if len(sys.argv) > 4 and sys.argv[4] == "publicar":
    for antigo, novo in [
        ('"Última coleta simulada"', '"Dados fictícios gerados em"'),
        ('"Demonstração: coleta simulada a cada " + s.intervalo_minutos + " min pelo serviço local. Atualizar o painel não coleta dados."',
         '"Prévia publicada com dados fictícios. A coleta real será feita pelo serviço local do financeiro, que ainda não está ligado ao TOTVS."'),
    ]:
        assert antigo in js, antigo
        js = js.replace(antigo, novo)
mock = (Path(sys.argv[3])).read_text().replace("__DADOS__", json.dumps(dados, ensure_ascii=False))
html = (web / "index.html").read_text()
html = html.replace('<link rel="stylesheet" href="/static/css/painel.css">',
                    "<style>\n" + (web / "css" / "painel.css").read_text()
                    + "\n#btn-acesso, #btn-relatorios { display: none !important; }\n</style>")
html = html.replace('<script type="module" src="/static/js/app.js"></script>', "")
html = html.replace("<small>Nenhum dado vem do TOTVS · ocorrências e regras são apenas ilustrativas</small>",
                    "<small>PRÉVIA ESTÁTICA · nenhum dado vem do TOTVS · ocorrências e regras são apenas ilustrativas</small>")
html = html.replace("<title>Painel Financeiro — Grupo Sorria</title>", "<title>Prévia — Painel Financeiro Grupo Sorria</title>")
html = html.replace("</body>", "<script>\n" + mock + "\n(function(){\n" + js + "\n})();\n</script>\n</body>")
if len(sys.argv) > 4 and sys.argv[4] == "publicar":
    # A página publicada recebe o esqueleto HTML na publicação: só título, estilo e conteúdo.
    titulo = "<title>Painel Financeiro Sorria</title>\n"
    estilo = re.search(r"<style>[\s\S]*?</style>", html).group(0)
    extra = """<style>
.faixa-demo { top: env(safe-area-inset-top, 0px); }
body::before { content: ""; position: fixed; inset: 0 0 auto; height: env(safe-area-inset-top, 0px); z-index: 49; background: #241d0c; }
.so-normal, .gaveta .so-normal { display: none !important; }
html, body { background: var(--fundo); color: var(--texto); }
</style>
"""
    corpo = re.search(r"<body>([\s\S]*)</body>", html).group(1)
    corpo = corpo.replace("PRÉVIA ESTÁTICA · nenhum dado vem do TOTVS", "Prévia publicada · nenhum dado vem do TOTVS")
    html = titulo + estilo + "\n" + extra + corpo
saida.write_text(html, encoding="utf-8")
print(saida, len(html))
