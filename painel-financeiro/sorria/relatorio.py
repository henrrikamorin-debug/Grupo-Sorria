"""Relatório mensal: filiais com mais dificuldade na conferência.

Gerado automaticamente no 1º dia de cada mês (após a primeira coleta
bem-sucedida do dia) sobre o mês anterior, já fechado; também pode ser gerado
a qualquer momento pelo painel ou por ``python -m sorria relatorio AAAA-MM``.

Critério de dificuldade (determinístico, sem IA): percentual de lançamentos
do mês com pelo menos uma inconsistência; empate decidido por pendências e
depois pelo número de ocorrências. Filiais com poucos lançamentos no mês ficam
fora do ranking (o percentual seria pouco representativo) e aparecem à parte.

O relatório nunca inclui a área restrita (escritório) e oculta dados pessoais
e bancários, porque se destina a ser enviado às filiais.
"""

from __future__ import annotations

import csv
import html
import io
import logging
import re
from calendar import monthrange
from datetime import date, datetime
from pathlib import Path

from .analise import Filtros, ROTULOS_SITUACAO, listar_ocorrencias, sql_ocultar
from .regras.base import formatar_data, formatar_reais

log = logging.getLogger(__name__)

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro"]
LIMITE_LINHAS_DESTAQUE = 40


def mes_anterior(hoje: date | None = None) -> str:
    hoje = hoje or date.today()
    ano, mes = (hoje.year, hoje.month - 1) if hoje.month > 1 else (hoje.year - 1, 12)
    return f"{ano:04d}-{mes:02d}"


def _limites(mes: str) -> tuple[date, date]:
    if not re.fullmatch(r"\d{4}-\d{2}", mes or ""):
        raise ValueError("Mês inválido; use AAAA-MM.")
    ano, numero = map(int, mes.split("-"))
    if not 1 <= numero <= 12:
        raise ValueError("Mês inválido; use AAAA-MM.")
    return date(ano, numero, 1), date(ano, numero, monthrange(ano, numero)[1])


def _nome_mes(mes: str) -> str:
    ano, numero = map(int, mes.split("-"))
    return f"{MESES[numero - 1]} de {ano}"


def _soma_unica(ocorrencias: list[dict]) -> tuple[int, int]:
    valores: dict[str, int | None] = {}
    for o in ocorrencias:
        valores.setdefault(o["referencia"], o["valor_centavos"])
    return sum(v for v in valores.values() if v is not None), len(valores)


def calcular(conexao, config: dict, mes: str, filiais: dict, ocultar_filiais=()) -> dict:
    inicio, fim = _limites(mes)
    ant_inicio, ant_fim = _limites(mes_anterior(inicio))
    condicao, valores = sql_ocultar(ocultar_filiais)
    extra = f" AND {condicao}" if condicao else ""
    registros = {(r["clinica"], r["filial"]): r["total"] for r in conexao.execute(
        "SELECT clinica, filial, COUNT(*) AS total FROM lancamentos WHERE data BETWEEN ? AND ?" + extra
        + " GROUP BY clinica, filial", [inicio.isoformat(), fim.isoformat(), *valores])}
    ocorrencias = listar_ocorrencias(conexao, Filtros(inicio.isoformat(), fim.isoformat()),
                                     tv=True, ocultar_filiais=ocultar_filiais)
    anteriores = listar_ocorrencias(conexao, Filtros(ant_inicio.isoformat(), ant_fim.isoformat()),
                                    tv=True, ocultar_filiais=ocultar_filiais)
    por_anterior: dict[str, int] = {}
    for o in anteriores:
        por_anterior[o["clinica"]] = por_anterior.get(o["clinica"], 0) + 1

    grupos: dict[tuple, list[dict]] = {chave: [] for chave in registros}
    for o in ocorrencias:
        grupos.setdefault((o["clinica"], o["filial"]), []).append(o)

    minimo = int(config["relatorio_mensal"]["minimo_lancamentos"])
    linhas = []
    for (clinica, filial), itens in grupos.items():
        total = registros.get((clinica, filial), 0)
        valor, afetados = _soma_unica(itens)
        pendentes = sum(1 for o in itens if o["situacao"] != "resolvida")
        regras: dict[str, int] = {}
        for o in itens:
            rotulo = f"{o['regra_codigo']} — {o['regra_nome']}"
            regras[rotulo] = regras.get(rotulo, 0) + 1
        cadastro = filiais.get(filial or "", {})
        responsavel = itens[0]["responsavel"] if itens else conexao.execute(
            "SELECT responsavel FROM lancamentos WHERE clinica = ? LIMIT 1", (clinica,)).fetchone()[0]
        linhas.append({
            "clinica": clinica, "filial": filial or "", "divisao": cadastro.get("divisao", ""),
            "responsavel": responsavel or "",
            "uf": cadastro.get("uf", ""), "registros": total, "ocorrencias": len(itens),
            "afetados": afetados, "valor_centavos": valor, "pendentes": pendentes,
            "taxa": afetados / total if total else 0.0,
            "anterior": por_anterior.get(clinica, 0),
            "regras": sorted(regras.items(), key=lambda r: -r[1]),
            "itens": sorted(itens, key=lambda o: (o["situacao"] == "resolvida", o["data"])),
            "ranqueada": total >= minimo,
        })
    linhas.sort(key=lambda l: (-l["taxa"], -l["pendentes"], -l["ocorrencias"], l["clinica"]))
    ranking = [l for l in linhas if l["ranqueada"]]
    for posicao, linha in enumerate(ranking, start=1):
        linha["posicao"] = posicao
    regras_gerais: dict[str, int] = {}
    for o in ocorrencias:
        rotulo = f"{o['regra_codigo']} — {o['regra_nome']}"
        regras_gerais[rotulo] = regras_gerais.get(rotulo, 0) + 1
    por_ticket: dict[str, dict] = {}
    for linha in linhas:
        nome = linha["responsavel"] or "Sem responsável definido"
        t = por_ticket.setdefault(nome, {"nome": nome, "filiais": 0, "registros": 0, "ocorrencias": 0,
                                         "pendentes": 0, "valor_centavos": 0})
        t["filiais"] += 1
        t["registros"] += linha["registros"]
        t["ocorrencias"] += linha["ocorrencias"]
        t["pendentes"] += linha["pendentes"]
        t["valor_centavos"] += linha["valor_centavos"]
    valor, afetados = _soma_unica(ocorrencias)
    return {
        "por_ticket": sorted(por_ticket.values(), key=lambda t: (-t["pendentes"], -t["ocorrencias"], t["nome"])),
        "mes": mes, "nome_mes": _nome_mes(mes), "inicio": inicio.isoformat(), "fim": fim.isoformat(),
        "demonstracao": config["modo"] == "demonstracao",
        "gerado_em": datetime.now().astimezone().strftime("%d/%m/%Y %H:%M"),
        "totais": {"registros": sum(registros.values()), "ocorrencias": len(ocorrencias),
                   "afetados": afetados, "valor_centavos": valor,
                   "pendentes": sum(1 for o in ocorrencias if o["situacao"] != "resolvida"),
                   "anterior": len(anteriores)},
        "ranking": ranking,
        "fora_do_ranking": [l for l in linhas if not l["ranqueada"]],
        "destaques": [l for l in ranking if l["ocorrencias"]][: int(config["relatorio_mensal"]["quantidade_destaque"])],
        "regras": sorted(regras_gerais.items(), key=lambda r: -r[1]),
        "minimo": minimo,
        "area_restrita_excluida": bool(ocultar_filiais),
    }


def _pct(valor: float) -> str:
    return f"{valor * 100:.1f}%".replace(".", ",")


def _variacao(atual: int, anterior: int) -> str:
    if anterior == 0:
        return "—" if atual == 0 else "novo"
    diferenca = atual - anterior
    return f"{'+' if diferenca > 0 else ''}{diferenca} ({_pct(diferenca / anterior)})"


def gerar_html(dados: dict) -> str:
    e = html.escape
    t = dados["totais"]
    faixa = ('<div class="demo">MODO DEMONSTRAÇÃO — DADOS FICTÍCIOS · regras ilustrativas, não aprovadas</div>'
             if dados["demonstracao"] else "")
    ranking = "".join(
        f"<tr><td class='n'>{l['posicao']}º</td><td>{e(l['clinica'])}<small>{e(l['filial'])}"
        f"{' · ' + e(l['divisao']) if l['divisao'] else ''}</small></td><td>{e(l['responsavel'])}</td>"
        f"<td class='n'>{l['registros']}</td><td class='n'>{l['ocorrencias']}</td>"
        f"<td class='n'>{l['afetados']}</td><td class='n forte'>{_pct(l['taxa'])}</td>"
        f"<td class='n'>{l['pendentes']}</td><td class='n'>{e(formatar_reais(l['valor_centavos']))}</td>"
        f"<td class='n'>{e(_variacao(l['ocorrencias'], l['anterior']))}</td></tr>"
        for l in dados["ranking"]) or "<tr><td colspan='10'>Nenhuma filial com lançamentos suficientes no mês.</td></tr>"
    fora = ", ".join(f"{e(l['clinica'])} ({l['registros']} lanç.)" for l in dados["fora_do_ranking"]) or "nenhuma"
    regras = "".join(f"<li>{e(nome)}: <b>{qtd}</b></li>" for nome, qtd in dados["regras"]) or "<li>Nenhuma ocorrência.</li>"

    destaques = []
    for l in dados["destaques"]:
        itens = l["itens"][:LIMITE_LINHAS_DESTAQUE]
        linhas = "".join(
            f"<tr><td>{formatar_data(o['data'])}</td><td>{e(o['titulo'])}</td>"
            f"<td>{e(o['regra_codigo'])} — {e(o['regra_nome'])}</td><td>{e(o['descricao'])}</td>"
            f"<td class='n'>{e(formatar_reais(o['valor_centavos']))}</td>"
            f"<td>{e(ROTULOS_SITUACAO[o['situacao']])}</td></tr>" for o in itens)
        resto = len(l["itens"]) - len(itens)
        destaques.append(
            f"<section class='destaque'><h3>{l['posicao']}º · {e(l['clinica'])}"
            f"{' — ' + e(l['responsavel']) if l['responsavel'] else ''} "
            f"<small>{_pct(l['taxa'])} dos lançamentos com inconsistência · {l['pendentes']} pendente(s)</small></h3>"
            f"<p>Principais regras: {', '.join(f'{e(n)} ({q})' for n, q in l['regras'][:4])}</p>"
            f"<table><thead><tr><th>Data</th><th>Nº do título</th><th>Regra</th><th>Descrição</th>"
            f"<th class='n'>Valor</th><th>Situação</th></tr></thead><tbody>{linhas}</tbody></table>"
            + (f"<p class='nota'>+ {resto} ocorrência(s) não listadas; ver exportação CSV no painel.</p>" if resto else "")
            + "</section>")

    restrita = ("<p class='nota'>A área restrita (escritório: folha e PJ) não faz parte deste relatório.</p>"
                if dados["area_restrita_excluida"] else "")
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Relatório mensal {e(dados['mes'])} — Grupo Sorria</title>
<style>
:root {{ --tinta:#1d1b17; --suave:#5d5a52; --linha:#dedad0; --ouro:#8a6a22; --fundo:#fbfaf6; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--fundo); color:var(--tinta); font:15px/1.45 "Segoe UI", Arial, sans-serif; }}
main {{ max-width:1100px; margin:0 auto; padding:32px 24px 48px; }}
.demo {{ background:#2b230f; color:#f5dc9c; text-align:center; font-weight:700; letter-spacing:.1em; padding:8px; }}
header .grupo {{ color:var(--ouro); letter-spacing:.3em; font-size:12px; font-weight:600; }}
h1 {{ margin:4px 0 2px; font-size:28px; }} h2 {{ font-size:18px; margin:32px 0 10px; border-bottom:2px solid var(--ouro); padding-bottom:4px; }}
h3 {{ font-size:16px; margin:0 0 6px; }} h3 small {{ font-weight:400; color:var(--suave); margin-left:6px; }}
.meta {{ color:var(--suave); }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin-top:20px; }}
.card {{ border:1px solid var(--linha); border-radius:8px; padding:12px 14px; background:#fff; }}
.card span {{ display:block; color:var(--suave); font-size:12px; text-transform:uppercase; letter-spacing:.08em; }}
.card b {{ font-size:22px; }}
table {{ width:100%; border-collapse:collapse; background:#fff; font-variant-numeric:tabular-nums; }}
th, td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--linha); vertical-align:top; }}
th {{ font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:var(--suave); }}
td small {{ display:block; color:var(--suave); font-size:12px; }}
.n {{ text-align:right; white-space:nowrap; }} .forte {{ font-weight:700; }}
.destaque {{ margin-top:22px; page-break-inside:avoid; }}
.nota {{ color:var(--suave); font-size:13px; }}
.criterio {{ background:#fff; border-left:3px solid var(--ouro); padding:8px 12px; }}
.tabela {{ overflow-x:auto; }}
@media print {{ body {{ background:#fff; }} main {{ padding:0; }} .destaque {{ page-break-inside:auto; }} }}
</style></head><body>{faixa}<main>
<header><div class="grupo">GRUPO SORRIA</div><h1>Relatório mensal de inconsistências</h1>
<div class="meta">{e(dados['nome_mes'].capitalize())} ({formatar_data(dados['inicio'])} a {formatar_data(dados['fim'])}) · gerado em {e(dados['gerado_em'])}</div></header>
<div class="cards">
<div class="card"><span>Lançamentos analisados</span><b>{t['registros']}</b></div>
<div class="card"><span>Inconsistências</span><b>{t['ocorrencias']}</b><br><small>mês anterior: {t['anterior']}</small></div>
<div class="card"><span>Lançamentos afetados</span><b>{t['afetados']}</b></div>
<div class="card"><span>Valor associado</span><b>{e(formatar_reais(t['valor_centavos']))}</b><br><small>cada lançamento uma vez</small></div>
<div class="card"><span>Ainda pendentes</span><b>{t['pendentes']}</b></div>
</div>
<h2>Filiais com mais dificuldade</h2>
<p class="criterio">Ordem: percentual de lançamentos do mês com pelo menos uma inconsistência; empate por pendências e depois por número de ocorrências. Filiais com menos de {dados['minimo']} lançamentos no mês ficam fora do ranking: {fora}.</p>
<div class="tabela"><table><thead><tr><th class="n">#</th><th>Filial</th><th>Responsável</th><th class="n">Lançamentos</th><th class="n">Ocorrências</th>
<th class="n">Afetados</th><th class="n">% com problema</th><th class="n">Pendentes</th><th class="n">Valor associado</th><th class="n">Vs. mês anterior</th></tr></thead>
<tbody>{ranking}</tbody></table></div>
<h2>Pendências por ticket</h2>
<div class="tabela"><table><thead><tr><th>Ticket</th><th class="n">Filiais</th><th class="n">Lançamentos</th>
<th class="n">Ocorrências</th><th class="n">Pendentes</th><th class="n">Valor associado</th></tr></thead><tbody>
{''.join(f"<tr><td>{e(t['nome'])}</td><td class='n'>{t['filiais']}</td><td class='n'>{t['registros']}</td><td class='n'>{t['ocorrencias']}</td><td class='n forte'>{t['pendentes']}</td><td class='n'>{e(formatar_reais(t['valor_centavos']))}</td></tr>" for t in dados['por_ticket'])}
</tbody></table></div>
<h2>Detalhamento das {len(dados['destaques'])} filiais em destaque</h2>
{''.join(destaques) or '<p>Nenhuma filial com ocorrências no mês.</p>'}
<h2>Ocorrências por regra</h2><ul>{regras}</ul>
{restrita}
<p class="nota">Relatório gerado automaticamente pelo painel financeiro a partir da última coleta válida. Situações (pendente, em análise, resolvida) refletem o acompanhamento registrado no painel no momento da geração. Dados pessoais e bancários foram omitidos.</p>
</main></body></html>"""


def gerar_csv(dados: dict) -> bytes:
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";", lineterminator="\r\n")
    escritor.writerow(["Origem", "Mês", "Posição", "Filial", "Responsável", "Código TOTVS", "Divisão", "UF", "Lançamentos",
                       "Ocorrências", "Lançamentos afetados", "% com problema", "Pendentes",
                       "Valor associado (R$)", "Ocorrências mês anterior"])
    origem = "DEMONSTRAÇÃO — DADOS FICTÍCIOS" if dados["demonstracao"] else "Coleta TOTVS"
    for l in dados["ranking"] + dados["fora_do_ranking"]:
        escritor.writerow([origem, dados["mes"], l.get("posicao", "fora do ranking"), l["clinica"], l["responsavel"], l["filial"],
                           l["divisao"], l["uf"], l["registros"], l["ocorrencias"], l["afetados"],
                           f"{l['taxa'] * 100:.1f}".replace(".", ","), l["pendentes"],
                           f"{l['valor_centavos'] / 100:.2f}".replace(".", ","), l["anterior"]])
    return ("﻿" + saida.getvalue()).encode("utf-8")


def gerar_e_salvar(conexao, config: dict, mes: str, filiais: dict, pasta: Path, ocultar_filiais=()) -> dict:
    dados = calcular(conexao, config, mes, filiais, ocultar_filiais)
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / f"relatorio-{mes}.html").write_text(gerar_html(dados), encoding="utf-8")
    (pasta / f"relatorio-{mes}.csv").write_bytes(gerar_csv(dados))
    log.info("Relatório mensal de %s gerado em %s.", mes, pasta)
    return {"mes": mes, "ocorrencias": dados["totais"]["ocorrencias"],
            "destaques": [l["clinica"] for l in dados["destaques"]]}


def listar(pasta: Path) -> list[dict]:
    if not pasta.exists():
        return []
    relatorios = []
    for arquivo in sorted(pasta.glob("relatorio-*.html"), reverse=True):
        mes = arquivo.stem.removeprefix("relatorio-")
        if not re.fullmatch(r"\d{4}-\d{2}", mes):
            continue
        relatorios.append({
            "mes": mes, "nome": _nome_mes(mes).capitalize(),
            "gerado_em": datetime.fromtimestamp(arquivo.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
            "csv": (pasta / f"relatorio-{mes}.csv").exists(),
        })
    return relatorios
