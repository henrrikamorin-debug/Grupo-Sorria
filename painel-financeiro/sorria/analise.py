"""Filtros, indicadores e agregações do painel (determinísticos).

Regra central dos valores: o valor de um lançamento é somado UMA única vez,
mesmo que o lançamento tenha várias ocorrências. Isso vale para o indicador
geral e para cada barra dos gráficos (dentro de cada grupo).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta

from .db import SITUACOES
from .privacidade import mascarar_ocorrencia

ROTULOS_SITUACAO = {"pendente": "Pendente", "em_analise": "Em análise", "resolvida": "Resolvida"}
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


class FiltroInvalido(ValueError):
    pass


@dataclass
class Filtros:
    inicio: str | None = None
    fim: str | None = None
    clinica: str | None = None
    categoria: str | None = None
    situacao: str | None = None
    responsavel: str | None = None

    @classmethod
    def de_parametros(cls, parametros: dict) -> "Filtros":
        def valor(nome):
            bruto = parametros.get(nome)
            if isinstance(bruto, list):
                bruto = bruto[0] if bruto else None
            bruto = (bruto or "").strip()
            return bruto or None

        filtros = cls(valor("inicio"), valor("fim"), valor("clinica"), valor("categoria"), valor("situacao"),
                      valor("responsavel"))
        for nome in ("inicio", "fim"):
            texto = getattr(filtros, nome)
            if texto:
                try:
                    date.fromisoformat(texto)
                except ValueError as erro:
                    raise FiltroInvalido(f"data inválida em '{nome}': {texto}") from erro
        if filtros.inicio and filtros.fim and filtros.inicio > filtros.fim:
            raise FiltroInvalido("a data inicial é posterior à final")
        if filtros.situacao and filtros.situacao not in SITUACOES:
            raise FiltroInvalido(f"situação desconhecida: {filtros.situacao}")
        return filtros

    def sql(self, com_situacao: bool, ocultar_filiais=()) -> tuple[str, list]:
        condicoes, valores = [], []
        condicao_restrita, valores_restritos = sql_ocultar(ocultar_filiais)
        if condicao_restrita:
            condicoes.append(condicao_restrita); valores.extend(valores_restritos)
        if self.inicio:
            condicoes.append("data >= ?"); valores.append(self.inicio)
        if self.fim:
            condicoes.append("data <= ?"); valores.append(self.fim)
        if self.clinica:
            condicoes.append("clinica = ?"); valores.append(self.clinica)
        if self.categoria:
            condicoes.append("categoria = ?"); valores.append(self.categoria)
        if self.responsavel:
            condicoes.append("responsavel = ?"); valores.append(self.responsavel)
        if com_situacao and self.situacao:
            condicoes.append("situacao = ?"); valores.append(self.situacao)
        return (" WHERE " + " AND ".join(condicoes)) if condicoes else "", valores

    def como_dict(self) -> dict:
        return dict(self.__dict__)


def sql_ocultar(ocultar_filiais) -> tuple[str, list]:
    """Condição que remove as filiais restritas (área com senha)."""
    codigos = sorted(set(ocultar_filiais or ()))
    if not codigos:
        return "", []
    return f"(filial IS NULL OR filial NOT IN ({', '.join('?' * len(codigos))}))", codigos


SQL_OCORRENCIAS = """
SELECT * FROM (
    SELECT o.id, o.referencia, o.regra_codigo, o.regra_nome, o.descricao, o.evidencia,
           o.clinica, o.categoria, o.data, o.valor_centavos, o.coleta_id, o.filial,
           COALESCE(o.titulo, o.referencia) AS titulo, o.responsavel,
           COALESCE(s.situacao, 'pendente') AS situacao,
           COALESCE(s.primeira_deteccao, o.detectada_em) AS primeira_deteccao,
           s.atualizada_em AS situacao_atualizada_em
    FROM ocorrencias o LEFT JOIN situacao_ocorrencias s ON s.id = o.id
)
"""


def listar_ocorrencias(conexao, filtros: Filtros, tv: bool = False, ocultar_filiais=()) -> list[dict]:
    where, valores = filtros.sql(com_situacao=True, ocultar_filiais=ocultar_filiais)
    linhas = conexao.execute(
        SQL_OCORRENCIAS + where + " ORDER BY data DESC, clinica, referencia, regra_codigo", valores
    ).fetchall()
    ocorrencias = []
    for linha in linhas:
        item = dict(linha)
        item["evidencia"] = json.loads(item["evidencia"])
        item["situacao_rotulo"] = ROTULOS_SITUACAO[item["situacao"]]
        ocorrencias.append(mascarar_ocorrencia(item) if tv else item)
    return ocorrencias


def _soma_unica(ocorrencias: list[dict]) -> tuple[int, int]:
    """Soma o valor de cada lançamento uma única vez. Devolve (soma, lançamentos)."""
    valores: dict[str, int | None] = {}
    for o in ocorrencias:
        valores.setdefault(o["referencia"], o["valor_centavos"])
    return sum(v for v in valores.values() if v is not None), len(valores)


def _agrupar(ocorrencias: list[dict], chave) -> list[dict]:
    grupos: dict[str, list[dict]] = {}
    for o in ocorrencias:
        grupos.setdefault(chave(o), []).append(o)
    resultado = []
    for rotulo, itens in grupos.items():
        soma, lancamentos = _soma_unica(itens)
        resultado.append({"rotulo": rotulo, "ocorrencias": len(itens),
                          "lancamentos": lancamentos, "valor_centavos": soma})
    resultado.sort(key=lambda g: (-g["ocorrencias"], -g["valor_centavos"], g["rotulo"]))
    return resultado


def _serie_periodo(ocorrencias: list[dict], inicio: date, fim: date) -> dict:
    dias = (fim - inicio).days + 1
    if dias <= 31:
        granularidade = "dia"
        def bucket(d: date) -> date: return d
        def proximo(d: date) -> date: return d + timedelta(days=1)
        def rotulo(d: date) -> str: return f"{d:%d/%m}"
    elif dias <= 140:
        granularidade = "semana"
        def bucket(d: date) -> date: return d - timedelta(days=d.weekday())
        def proximo(d: date) -> date: return d + timedelta(days=7)
        def rotulo(d: date) -> str: return f"{d:%d/%m}"
    else:
        granularidade = "mes"
        def bucket(d: date) -> date: return d.replace(day=1)
        def proximo(d: date) -> date: return (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        def rotulo(d: date) -> str: return f"{MESES[d.month - 1]}/{d:%y}"

    por_bucket: dict[date, list[dict]] = {}
    for o in ocorrencias:
        por_bucket.setdefault(bucket(date.fromisoformat(o["data"])), []).append(o)
    serie, atual = [], bucket(inicio)
    while atual <= fim:
        itens = por_bucket.get(atual, [])
        soma, lancamentos = _soma_unica(itens)
        fim_bucket = min(proximo(atual) - timedelta(days=1), fim)
        serie.append({"rotulo": rotulo(atual), "inicio": max(atual, inicio).isoformat(),
                      "fim": fim_bucket.isoformat(), "ocorrencias": len(itens),
                      "lancamentos": lancamentos, "valor_centavos": soma})
        atual = proximo(atual)
    return {"granularidade": granularidade, "serie": serie}


def opcoes(conexao, ocultar_filiais=()) -> dict:
    condicao, valores = sql_ocultar(ocultar_filiais)
    where = f" WHERE {condicao}" if condicao else ""
    clinicas = [r[0] for r in conexao.execute(
        f"SELECT DISTINCT clinica FROM lancamentos{where} ORDER BY clinica", valores)]
    categorias = [r[0] for r in conexao.execute(
        f"SELECT DISTINCT categoria FROM lancamentos{where} ORDER BY categoria", valores)]
    limites = conexao.execute(f"SELECT MIN(data), MAX(data) FROM lancamentos{where}", valores).fetchone()
    # Responsável -> filiais que cuida (para o filtro "Responsável" ao lado de "Clínica").
    por_responsavel: dict[str, list[str]] = {}
    for nome, clinica in conexao.execute(
            f"SELECT DISTINCT responsavel, clinica FROM lancamentos{where} ORDER BY responsavel, clinica", valores):
        if nome:
            por_responsavel.setdefault(nome, []).append(clinica)
    return {
        "responsaveis": [{"nome": n, "clinicas": c} for n, c in por_responsavel.items()],
        "clinicas": clinicas,
        "categorias": categorias,
        "situacoes": [{"valor": s, "rotulo": ROTULOS_SITUACAO[s]} for s in SITUACOES],
        "periodo_disponivel": {"inicio": limites[0], "fim": limites[1]},
    }


def montar_painel(conexao, filtros: Filtros, tv: bool = False, ocultar_filiais=()) -> dict:
    where, valores = filtros.sql(com_situacao=False, ocultar_filiais=ocultar_filiais)
    registros = conexao.execute("SELECT COUNT(*) FROM lancamentos" + where, valores).fetchone()[0]
    ocorrencias = listar_ocorrencias(conexao, filtros, tv=tv, ocultar_filiais=ocultar_filiais)
    soma, afetados = _soma_unica(ocorrencias)
    sem_valor = len({o["referencia"] for o in ocorrencias if o["valor_centavos"] is None})
    contagem = {s: 0 for s in SITUACOES}
    for o in ocorrencias:
        contagem[o["situacao"]] += 1

    disponiveis = opcoes(conexao, ocultar_filiais)
    periodo = disponiveis["periodo_disponivel"]
    inicio = filtros.inicio or periodo["inicio"]
    fim = filtros.fim or periodo["fim"]
    por_periodo = (_serie_periodo(ocorrencias, date.fromisoformat(inicio), date.fromisoformat(fim))
                   if inicio and fim else {"granularidade": "dia", "serie": []})

    return {
        "filtros": filtros.como_dict(),
        "indicadores": {
            "registros_analisados": registros,
            "ocorrencias": len(ocorrencias),
            "lancamentos_afetados": afetados,
            "valor_associado_centavos": soma,
            "lancamentos_sem_valor": sem_valor,
            "pendencias": contagem["pendente"] + contagem["em_analise"],
            "por_situacao": contagem,
        },
        "graficos": {
            "por_clinica": _agrupar(ocorrencias, lambda o: o["clinica"]),
            "por_categoria": _agrupar(ocorrencias, lambda o: o["categoria"]),
            "por_periodo": por_periodo,
        },
        "ocorrencias": ocorrencias,
        "opcoes": disponiveis,
    }
