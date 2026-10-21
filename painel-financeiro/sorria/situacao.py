"""Situação da integração exibida no painel.

Distingue claramente: coleta simulada (demonstração), integração não
configurada, coleta real atualizada, dados desatualizados e última falha.
Recarregar o painel NÃO gera nova coleta; apenas lê o último retrato válido.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone


def _minutos_desde(iso: str | None) -> float | None:
    if not iso:
        return None
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 60


def _publico(linha, autorizado: bool) -> dict | None:
    """Sem autorização, os totais da coleta não incluem a área restrita."""
    if linha is None:
        return None
    dados = dict(linha)
    if not autorizado:
        for total, restritos in (("registros", "registros_restritos"), ("ocorrencias", "ocorrencias_restritas")):
            if dados.get(total) is not None:
                dados[total] -= dados.get(restritos) or 0
    dados.pop("registros_restritos", None)
    dados.pop("ocorrencias_restritas", None)
    return dados


def montar_situacao(conexao, config: dict, servico, autorizado: bool = False) -> dict:
    ultimo_sucesso = conexao.execute(
        "SELECT * FROM coletas WHERE situacao = 'sucesso' ORDER BY id DESC LIMIT 1").fetchone()
    ultima = conexao.execute(
        "SELECT * FROM coletas WHERE situacao != 'em_andamento' ORDER BY id DESC LIMIT 1").fetchone()
    historico = [_publico(r, autorizado) for r in conexao.execute(
        "SELECT id, iniciada_em, finalizada_em, situacao, origem, simulada, registros, ocorrencias, mensagem, "
        "registros_restritos, ocorrencias_restritas FROM coletas ORDER BY id DESC LIMIT 8")]
    ultimo_sucesso, ultima = _publico(ultimo_sucesso, autorizado), _publico(ultima, autorizado)

    modo = config["modo"]
    conector = servico.conector.descricao()
    if conector.get("se2") and modo == "real":
        return montar_situacao_se2(conexao, config, servico, conector, autorizado)
    tolerancia = config["coleta"]["tolerancia_desatualizacao_minutos"]
    minutos = _minutos_desde(ultimo_sucesso["finalizada_em"]) if ultimo_sucesso else None
    desatualizado = minutos is None or minutos > tolerancia
    ultima_falhou = ultima is not None and ultima["situacao"] == "falha"

    if modo != "demonstracao" and not conector["configurado"]:
        nivel, titulo = "nao_configurado", "Integração TOTVS não configurada"
        detalhe = "Nenhuma coleta real é possível até o conector ser implementado."
    elif ultimo_sucesso is None:
        nivel, titulo = ("falha", "Nenhuma coleta concluída") if ultima_falhou else (
            "aguardando", "Aguardando primeira coleta")
        detalhe = ultima["mensagem"] if ultima_falhou else ""
    elif desatualizado:
        nivel, titulo = "desatualizado", "Dados desatualizados"
        detalhe = f"Sem coleta bem-sucedida há {int(minutos)} min."
    elif ultima_falhou:
        nivel, titulo = "alerta", "Última coleta falhou"
        detalhe = "Exibindo a última coleta válida."
    else:
        nivel, titulo, detalhe = "ok", "Integração ativa", ""

    if modo == "demonstracao":
        # Nunca apresentar a coleta simulada como integração real.
        titulo = "Coleta simulada — demonstração" if nivel == "ok" else f"Coleta simulada — {titulo.lower()}"
        nivel = "demonstracao" if nivel == "ok" else nivel
        detalhe = ("Nenhum dado vem do TOTVS. Os registros são fictícios. " + detalhe).strip()

    return {
        "modo": modo,
        "demonstracao": modo == "demonstracao",
        "nivel": nivel,
        "titulo": titulo,
        "detalhe": detalhe,
        "conector": conector,
        "ultima_coleta_sucesso": dict(ultimo_sucesso) if ultimo_sucesso else None,
        "ultima_tentativa": dict(ultima) if ultima else None,
        "ultima_tentativa_falhou": ultima_falhou,
        "minutos_desde_sucesso": None if minutos is None else round(minutos, 1),
        "desatualizado": desatualizado,
        "tolerancia_minutos": tolerancia,
        "coleta_em_andamento": servico.em_andamento,
        "agendador_ativo": servico.agendador_ativo,
        "intervalo_minutos": config["coleta"]["intervalo_minutos"],
        "proxima_coleta_prevista": (
            datetime.fromtimestamp(servico.proxima_execucao, timezone.utc).isoformat(timespec="seconds")
            if servico.proxima_execucao and servico.agendador_ativo else None),
        "historico": historico,
        "servidor_agora": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def montar_situacao_se2(conexao, config: dict, servico, conector: dict, autorizado: bool) -> dict:
    """Situação quando o painel é alimentado pelo agente TOTVS (Contas a Pagar SE2).

    "Última coleta válida" = última importação aceita (não a recarga do painel).
    Sem autorização, nenhum total inclui a área restrita.
    """
    from .totvs.importacao import ORIGEM

    importacao = conexao.execute(
        "SELECT * FROM importacoes WHERE situacao = 'importada' ORDER BY id DESC LIMIT 1").fetchone()
    tentativa = conexao.execute(
        "SELECT * FROM execucoes_agente WHERE situacao != 'em_andamento' ORDER BY id DESC LIMIT 1").fetchone()
    andamento = conexao.execute(
        "SELECT etapa, mensagem FROM execucoes_agente WHERE situacao = 'em_andamento' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    execucoes = [dict(r) for r in conexao.execute(
        "SELECT e.id, e.iniciada_em, e.finalizada_em, e.situacao, e.origem, e.etapa, e.tentativas, e.mensagem, "
        "e.modo_coleta, e.painel_confirmado, i.arquivo_nome, i.situacao AS importacao FROM execucoes_agente e "
        "LEFT JOIN importacoes i ON i.id = e.importacao_id ORDER BY e.id DESC LIMIT 8")]
    tolerancia_h = float(config["agente"]["tolerancia_desatualizacao_horas"])
    minutos = _minutos_desde(importacao["finalizada_em"]) if importacao else None
    desatualizado = minutos is None or minutos > tolerancia_h * 60
    falhou = bool(tentativa and importacao and tentativa["situacao"] in ("falha", "sem_arquivo", "interrompida")
                  and tentativa["id"] > (importacao["execucao_id"] or 0))

    if importacao is None:
        nivel, titulo = ("falha", "Coleta TOTVS falhou") if tentativa and tentativa["situacao"] == "falha" else (
            "aguardando", "Aguardando primeira coleta do TOTVS")
        detalhe = (tentativa["mensagem"] or "") if tentativa else "Nenhuma exportação SE2 importada ainda."
    elif desatualizado:
        nivel, titulo = "desatualizado", "Dados desatualizados"
        detalhe = f"Sem importação válida há {int(minutos // 60)} h."
    elif falhou:
        nivel, titulo = "alerta", "Última coleta não concluída"
        detalhe = f"{tentativa['mensagem'] or tentativa['situacao']} — exibindo a última importação válida."
    else:
        nivel, titulo, detalhe = "ok", "Coleta TOTVS válida e completa", ""

    dados_importacao = conferencia = None
    pendencias: list[dict] = []
    completa = None
    if importacao:
        # Pendências que envolvem a área restrita só aparecem para quem tem acesso.
        pendencias = [p for p in json.loads(importacao["pendencias"] or "[]") if autorizado or not p.get("restrita")]
        if importacao["completa"] is not None:
            completa = bool(importacao["completa"] if autorizado else importacao["completa_publica"])
        if nivel == "ok" and not completa:
            nivel, titulo = "alerta", "Coleta TOTVS importada — não confirmada como completa"
            detalhe = " ".join(p["texto"] for p in pendencias if p.get("bloqueia")) or \
                "Importação anterior às verificações de completude."
        avisos = json.loads(importacao["avisos"] or "[]")
        dados_importacao = {
            "id": importacao["id"], "finalizada_em": importacao["finalizada_em"],
            "arquivo_nome": importacao["arquivo_nome"], "origem": importacao["origem"],
            "periodo_inicio": importacao["periodo_inicio"], "periodo_fim": importacao["periodo_fim"],
            "campo_periodo": importacao["campo_periodo"],
            # O total de linhas inclui a área restrita: só para quem tem autorização.
            "linhas_lidas": importacao["linhas_lidas"] if autorizado else None,
            "titulos": importacao["publicos"] + (importacao["restritos"] if autorizado else 0),
            "novos": importacao["novos"] if autorizado else None,
            "atualizados": importacao["atualizados"] if autorizado else None,
            "rejeitadas": importacao["rejeitadas"] if autorizado else importacao["rejeitadas_publicas"],
            "completa": completa, "pendencias": pendencias,
            "total_conferido": (None if importacao["total_conferido"] is None else bool(importacao["total_conferido"]))
            if autorizado else None,
            "escopo": json.loads(importacao["escopo"]) if importacao["escopo"] else None,
            "colunas_ausentes": json.loads(importacao["colunas_ausentes"] or "[]"),
            "avisos": avisos if autorizado else [a for a in avisos if "restrit" not in a.lower()],
            "restritos": importacao["restritos"] if autorizado else None,
            "filiais_sem_cadastro": importacao["filiais_sem_cadastro"] if autorizado else None,
        }
        # Conferência: títulos do período no painel x títulos do arquivo.
        filtro = "" if autorizado else " AND restrito = 0"
        painel = conexao.execute(
            "SELECT COUNT(*), COALESCE(SUM(valor_centavos), 0), "
            "COALESCE(SUM(CASE WHEN ultima_importacao = ? THEN 0 ELSE 1 END), 0) FROM titulos_pagar "
            "WHERE vencimento BETWEEN ? AND ?" + filtro,
            (importacao["id"], importacao["periodo_inicio"], importacao["periodo_fim"])).fetchone()
        arquivo_qtd = importacao["publicos"] + (importacao["restritos"] if autorizado else 0)
        arquivo_valor = importacao["valor_publico_centavos"] + (importacao["valor_restrito_centavos"] if autorizado else 0)
        conferencia = {"painel_titulos": painel[0], "painel_valor_centavos": painel[1],
                       "arquivo_titulos": arquivo_qtd, "arquivo_valor_centavos": arquivo_valor,
                       "fora_da_ultima_exportacao": painel[2],
                       "confere": painel[0] == arquivo_qtd and painel[1] == arquivo_valor}

    return {
        "modo": "real", "demonstracao": False, "se2": True,
        "nivel": nivel, "titulo": titulo, "detalhe": detalhe, "conector": conector,
        "origem": ORIGEM,
        "ultima_coleta_sucesso": ({"finalizada_em": importacao["finalizada_em"], "registros": dados_importacao["titulos"]}
                                  if importacao else None),
        "ultima_tentativa": ({k: tentativa[k] for k in ("id", "iniciada_em", "finalizada_em", "situacao", "origem",
                                                         "etapa", "mensagem")} if tentativa else None),
        "ultima_tentativa_falhou": falhou,
        "importacao": dados_importacao, "conferencia": conferencia,
        "minutos_desde_sucesso": None if minutos is None else round(minutos, 1),
        "desatualizado": desatualizado,
        "tolerancia_minutos": int(tolerancia_h * 60),
        "coleta_em_andamento": bool(andamento), "etapa_em_andamento": andamento["etapa"] if andamento else None,
        # Login pendente no TOTVS: alguém precisa entrar na janela do Chrome do agente.
        "acao_necessaria": (andamento["mensagem"] if andamento and andamento["etapa"] == "aguardando_login" else None),
        "agendador_ativo": bool(config["agente"]["agendamento"].get("ativo") and config["agente"]["agendamento"].get("horarios")),
        "agendamento": config["agente"]["agendamento"],
        "intervalo_minutos": None, "proxima_coleta_prevista": None,
        "historico": [], "execucoes_agente": execucoes,
        "servidor_agora": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
