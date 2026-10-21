"""Importação de uma exportação SE2 para o banco do painel.

Validações antes de gravar (qualquer falha rejeita o lote inteiro e nada muda):

* arquivo novo: o mesmo conteúdo (hash SHA-256) já importado é ignorado; na
  coleta do agente o arquivo precisa ter sido gerado depois do início da
  execução; na importação manual, há um limite de idade;
* origem: o cabeçalho precisa ter as colunas de Contas a Pagar (SE2);
* período: todo título válido precisa ter VENCIMENTO (o campo usado no filtro
  da Consulta Genérica) dentro do mês de referência;
* proporção de linhas rejeitadas dentro do limite configurado;
* mesma composição de chave das importações anteriores (evita duplicar);
* mais de uma filial no arquivo (uma só costuma indicar filtro de filial ativo).

Gravação: chave composta filial|prefixo|número|parcela|tipo|fornecedor|loja.
Reimportar atualiza o título; títulos ausentes do arquivo NÃO são apagados.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .. import db
from .classificacao import classificar, regras_restricao, validar_regras
from .se2 import ArquivoInvalido, ler_exportacao, situacao_titulo

log = logging.getLogger(__name__)

ORIGEM = "TOTVS SE2 — Consulta Genérica (Exp. CSV)"


class LoteRejeitado(Exception):
    def __init__(self, mensagem: str, detalhes: dict | None = None):
        super().__init__(mensagem)
        self.detalhes = detalhes or {}


def periodo_mes_atual(hoje: date) -> tuple[date, date]:
    return date(hoje.year, hoje.month, 1), date(hoje.year, hoje.month, monthrange(hoje.year, hoje.month)[1])


def hash_arquivo(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()


def _registrar(conexao, dados: dict) -> int:
    colunas = ", ".join(dados)
    marcadores = ", ".join("?" * len(dados))
    return conexao.execute(f"INSERT INTO importacoes ({colunas}) VALUES ({marcadores})",
                           list(dados.values())).lastrowid


def importar_arquivo(conexao, caminho: Path, config: dict, cadastro: dict, *, hoje: date | None = None,
                     inicio_execucao: datetime | None = None, execucao_id: int | None = None,
                     confirmar_arquivo_antigo: bool = False, aceitar_filial_unica: bool = False,
                     pasta_arquivo: Path | None = None) -> dict:
    """Valida e importa um arquivo. Devolve o resumo (situacao: importada | ignorada | rejeitada)."""
    cfg = config["agente"]
    hoje = hoje or date.today()
    agora = datetime.now(timezone.utc)
    conteudo = caminho.read_bytes()
    resumo_arquivo = {
        "execucao_id": execucao_id, "iniciada_em": agora.isoformat(timespec="seconds"), "origem": ORIGEM,
        "arquivo_nome": caminho.name, "arquivo_hash": hash_arquivo(conteudo), "arquivo_tamanho": len(conteudo),
        "arquivo_modificado_em": datetime.fromtimestamp(caminho.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
        "campo_periodo": "vencimento",
    }
    inicio, fim = periodo_mes_atual(hoje)
    resumo_arquivo.update({"periodo_inicio": inicio.isoformat(), "periodo_fim": fim.isoformat()})

    anterior = conexao.execute(
        "SELECT id, finalizada_em FROM importacoes WHERE arquivo_hash = ? AND situacao = 'importada' "
        "ORDER BY id DESC LIMIT 1", (resumo_arquivo["arquivo_hash"],)).fetchone()
    if anterior:
        mensagem = f"Arquivo já importado (importação nº {anterior['id']}); nada foi alterado."
        id_ = _registrar(conexao, {**resumo_arquivo, "situacao": "ignorada", "mensagem": mensagem,
                                   "finalizada_em": db.agora_iso()})
        log.info("Importação %s ignorada: %s", id_, mensagem)
        _arquivar(caminho, pasta_arquivo, "ignorados", resumo_arquivo["arquivo_hash"])
        return {"situacao": "ignorada", "importacao_id": id_, "mensagem": mensagem}

    try:
        resultado = _validar_e_gravar(conexao, caminho, conteudo, config, cadastro, resumo_arquivo, hoje,
                                      inicio, fim, agora, inicio_execucao, confirmar_arquivo_antigo,
                                      aceitar_filial_unica)
    except (LoteRejeitado, ArquivoInvalido) as erro:
        detalhes = getattr(erro, "detalhes", {})
        id_ = _registrar(conexao, {**resumo_arquivo, "situacao": "rejeitada", "mensagem": str(erro)[:500],
                                   "finalizada_em": db.agora_iso(), **detalhes})
        log.warning("Importação %s rejeitada: %s", id_, erro)
        _arquivar(caminho, pasta_arquivo, "rejeitados", resumo_arquivo["arquivo_hash"])
        return {"situacao": "rejeitada", "importacao_id": id_, "mensagem": str(erro)}
    _arquivar(caminho, pasta_arquivo, "processados", resumo_arquivo["arquivo_hash"])
    return resultado


def _validar_e_gravar(conexao, caminho, conteudo, config, cadastro, resumo_arquivo, hoje, inicio, fim, agora,
                      inicio_execucao, confirmar_arquivo_antigo, aceitar_filial_unica) -> dict:
    cfg = config["agente"]
    modificado = datetime.fromtimestamp(caminho.stat().st_mtime, timezone.utc)
    tolerancia = timedelta(seconds=int(cfg["tolerancia_relogio_segundos"]))
    if modificado > agora + tolerancia:
        raise LoteRejeitado("Data de modificação do arquivo está no futuro; confira o relógio do computador.")
    if inicio_execucao is not None:
        if modificado < inicio_execucao - tolerancia:
            raise LoteRejeitado("O arquivo é anterior ao início desta execução; um relatório antigo não é "
                                "reaproveitado. Gere uma nova exportação.")
    elif not confirmar_arquivo_antigo and agora - modificado > timedelta(hours=float(cfg["idade_maxima_horas"])):
        raise LoteRejeitado(f"Arquivo gerado há mais de {cfg['idade_maxima_horas']} h. Para importar mesmo assim, "
                            "confirme com --confirmar-arquivo-antigo.")

    leitura = ler_exportacao(conteudo, int(cfg["tamanho_codigo_filial"]))
    detalhes = {
        "colunas_chave": json.dumps(leitura.colunas_chave), "colunas_ausentes": json.dumps(leitura.colunas_ausentes),
        "linhas_lidas": leitura.linhas_lidas, "titulos_validos": len(leitura.titulos),
        "rejeitadas": len(leitura.rejeitadas), "avisos": json.dumps(leitura.avisos, ensure_ascii=False),
    }
    if not leitura.titulos:
        raise LoteRejeitado("Nenhum título válido no arquivo.", detalhes)
    limite = float(cfg["max_percentual_linhas_rejeitadas"])
    if leitura.linhas_lidas and 100 * len(leitura.rejeitadas) / leitura.linhas_lidas > limite:
        raise LoteRejeitado(f"{len(leitura.rejeitadas)} de {leitura.linhas_lidas} linhas inválidas "
                            f"(limite {limite:g}%). Confira o layout exportado.", detalhes)
    fora = [t for t in leitura.titulos if not inicio.isoformat() <= t.vencimento <= fim.isoformat()]
    if fora:
        raise LoteRejeitado(
            f"{len(fora)} título(s) com vencimento fora de {inicio:%m/%Y} (ex.: linha {fora[0].linha}). "
            "O filtro da Consulta Genérica deve ser Vencimento = Mês Atual.", detalhes)
    ultima = conexao.execute("SELECT colunas_chave FROM importacoes WHERE situacao = 'importada' "
                             "ORDER BY id DESC LIMIT 1").fetchone()
    if ultima and ultima["colunas_chave"] != detalhes["colunas_chave"]:
        raise LoteRejeitado("As colunas que formam a chave do título mudaram em relação à última importação "
                            f"({ultima['colunas_chave']} → {detalhes['colunas_chave']}). Importar assim poderia "
                            "duplicar títulos; confira o layout da exportação.", detalhes)
    filiais = {t.filial for t in leitura.titulos}
    if len(filiais) == 1 and len(cadastro) > 1 and not aceitar_filial_unica:
        raise LoteRejeitado("O arquivo tem títulos de uma única filial; provavelmente a consulta está restrita à "
                            "filial logada. Ajuste o filtro de filiais e exporte de novo (ou confirme com "
                            "--aceitar-filial-unica se for intencional).", detalhes)

    regras = regras_restricao(config)
    avisos = leitura.avisos + validar_regras(cadastro, regras)
    tem_saldo = "saldo" in leitura.colunas
    tem_baixa = "baixa" in leitura.colunas
    agora_iso = db.agora_iso()
    linhas, chaves = [], []
    restritos = publicos = valor_restrito = valor_publico = 0
    vistos: dict[str, int] = {}
    for t in leitura.titulos:
        chave = t.chave(leitura.colunas_chave)
        if chave in vistos:
            raise LoteRejeitado(f"Chave de título repetida no próprio arquivo (linhas {vistos[chave]} e {t.linha}); "
                                "a exportação pode estar duplicada.", detalhes)
        vistos[chave] = t.linha
        restrito, motivo = classificar(t, cadastro, regras)
        if restrito:
            restritos += 1
            valor_restrito += t.valor_centavos
        else:
            publicos += 1
            valor_publico += t.valor_centavos
        chaves.append(chave)
        linhas.append((chave, t.filial, t.prefixo, t.numero, t.parcela, t.tipo, t.natureza, t.fornecedor, t.loja,
                       t.nome_fornecedor, t.emissao, t.vencimento, t.vencimento_real, t.valor_centavos,
                       t.saldo_centavos, t.baixa, t.historico, situacao_titulo(t, hoje, tem_saldo, tem_baixa),
                       int(restrito), motivo or None, int(t.filial in cadastro),
                       json.dumps(t.campos_vazios)))

    existentes = set()
    for parte in range(0, len(chaves), 500):
        lote = chaves[parte:parte + 500]
        existentes |= {r[0] for r in conexao.execute(
            f"SELECT chave FROM titulos_pagar WHERE chave IN ({', '.join('?' * len(lote))})", lote)}
    with db.transacao(conexao):
        id_ = _registrar(conexao, {**resumo_arquivo, "situacao": "importada", **detalhes,
                                   "novos": len(chaves) - len(existentes), "atualizados": len(existentes),
                                   "publicos": publicos, "restritos": restritos,
                                   "valor_publico_centavos": valor_publico, "valor_restrito_centavos": valor_restrito,
                                   "filiais_arquivo": len(filiais),
                                   "filiais_sem_cadastro": len([f for f in filiais if f not in cadastro]),
                                   "avisos": json.dumps(avisos, ensure_ascii=False)})
        conexao.executemany(
            "INSERT INTO titulos_pagar (chave, filial, prefixo, numero, parcela, tipo, natureza, fornecedor, loja, "
            "nome_fornecedor, emissao, vencimento, vencimento_real, valor_centavos, saldo_centavos, baixa, historico, "
            "situacao_titulo, restrito, motivo_restricao, filial_cadastrada, campos_vazios, primeira_importacao, "
            "ultima_importacao, atualizado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(chave) DO UPDATE SET filial = excluded.filial, prefixo = excluded.prefixo, "
            "numero = excluded.numero, parcela = excluded.parcela, tipo = excluded.tipo, natureza = excluded.natureza, "
            "fornecedor = excluded.fornecedor, loja = excluded.loja, nome_fornecedor = excluded.nome_fornecedor, "
            "emissao = excluded.emissao, vencimento = excluded.vencimento, vencimento_real = excluded.vencimento_real, "
            "valor_centavos = excluded.valor_centavos, saldo_centavos = excluded.saldo_centavos, "
            "baixa = excluded.baixa, historico = excluded.historico, situacao_titulo = excluded.situacao_titulo, "
            "restrito = excluded.restrito, motivo_restricao = excluded.motivo_restricao, "
            "filial_cadastrada = excluded.filial_cadastrada, campos_vazios = excluded.campos_vazios, "
            "ultima_importacao = excluded.ultima_importacao, atualizado_em = excluded.atualizado_em",
            [linha + (id_, id_, agora_iso) for linha in linhas])
        conexao.executemany("INSERT INTO importacao_rejeicoes (importacao_id, linha, motivo) VALUES (?, ?, ?)",
                            [(id_, linha, motivo) for linha, motivo in leitura.rejeitadas])
        conexao.execute("UPDATE importacoes SET finalizada_em = ? WHERE id = ?", (db.agora_iso(), id_))
    log.info("Importação %s: %d títulos (%d novos, %d atualizados, %d rejeitadas, %d restritos).", id_,
             len(chaves), len(chaves) - len(existentes), len(existentes), len(leitura.rejeitadas), restritos)
    return {"situacao": "importada", "importacao_id": id_, "titulos": len(chaves),
            "novos": len(chaves) - len(existentes), "atualizados": len(existentes),
            "rejeitadas": len(leitura.rejeitadas), "publicos": publicos, "restritos": restritos,
            "valor_publico_centavos": valor_publico, "valor_restrito_centavos": valor_restrito,
            "periodo": [inicio.isoformat(), fim.isoformat()], "avisos": avisos}


def _arquivar(caminho: Path, pasta_arquivo: Path | None, destino: str, hash_: str) -> None:
    """Move (ou copia, se o arquivo estiver fora da pasta do agente) para processados/rejeitados."""
    if pasta_arquivo is None:
        return
    alvo_dir = pasta_arquivo / destino / datetime.now().strftime("%Y-%m")
    alvo_dir.mkdir(parents=True, exist_ok=True)
    alvo = alvo_dir / f"{datetime.now():%Y%m%d-%H%M%S}_{hash_[:12]}_{caminho.name}"
    try:
        if pasta_arquivo in caminho.resolve().parents:
            shutil.move(str(caminho), alvo)
        else:
            shutil.copy2(caminho, alvo)
    except OSError:
        log.exception("Não foi possível arquivar %s.", caminho.name)
