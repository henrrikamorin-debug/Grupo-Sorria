"""Situação da integração exibida no painel.

Distingue claramente: coleta simulada (demonstração), integração não
configurada, coleta real atualizada, dados desatualizados e última falha.
Recarregar o painel NÃO gera nova coleta; apenas lê o último retrato válido.
"""

from __future__ import annotations

from datetime import datetime, timezone


def _minutos_desde(iso: str | None) -> float | None:
    if not iso:
        return None
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 60


def montar_situacao(conexao, config: dict, servico) -> dict:
    ultimo_sucesso = conexao.execute(
        "SELECT * FROM coletas WHERE situacao = 'sucesso' ORDER BY id DESC LIMIT 1").fetchone()
    ultima = conexao.execute(
        "SELECT * FROM coletas WHERE situacao != 'em_andamento' ORDER BY id DESC LIMIT 1").fetchone()
    historico = [dict(r) for r in conexao.execute(
        "SELECT id, iniciada_em, finalizada_em, situacao, origem, simulada, registros, ocorrencias, mensagem "
        "FROM coletas ORDER BY id DESC LIMIT 8")]

    modo = config["modo"]
    conector = servico.conector.descricao()
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
