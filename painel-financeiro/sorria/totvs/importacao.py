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
* linha de total do arquivo (quando existe): a soma das linhas precisa conferir.

Completude (o lote é importado, mas só é "completo" sem pendências):

* linhas descartadas sem reconciliação deixam a importação incompleta;
* abrangência conferida contra as filiais esperadas para a execução
  (``agente.filiais_esperadas`` ou o cadastro): uma filial só não é rejeitada
  automaticamente, e várias filiais não bastam para considerar completo; a
  abrangência só é confirmada pelo filtro verificado na tela pelo executor;
* cada pendência é marcada como restrita quando envolve dados da área
  restrita, para não revelar sua existência a quem não tem acesso.

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
from types import SimpleNamespace

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
                     confirmar_arquivo_antigo: bool = False, escopo: dict | None = None,
                     pasta_arquivo: Path | None = None) -> dict:
    """Valida e importa um arquivo. Devolve o resumo (situacao: importada | ignorada | rejeitada).

    ``escopo``: o que o executor do navegador conferiu na tela (filtro, filiais). Sem ele
    (arquivo importado à mão ou pela pasta), a abrangência fica como não verificada.
    """
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
                                      inicio, fim, agora, inicio_execucao, confirmar_arquivo_antigo, escopo)
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
                      inicio_execucao, confirmar_arquivo_antigo, escopo) -> dict:
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
        # Sem contagens na mensagem: ela aparece no histórico para quem não vê a área restrita.
        raise LoteRejeitado(f"Proporção de linhas inválidas acima do limite ({limite:g}%). Confira o layout "
                            "exportado.", detalhes)
    fora = [t for t in leitura.titulos if not inicio.isoformat() <= t.vencimento <= fim.isoformat()]
    if fora:
        raise LoteRejeitado(
            f"Há título(s) com vencimento fora de {inicio:%m/%Y}. "
            "O filtro da Consulta Genérica deve ser Vencimento = Mês Atual.", detalhes)
    ultima = conexao.execute("SELECT colunas_chave FROM importacoes WHERE situacao = 'importada' "
                             "ORDER BY id DESC LIMIT 1").fetchone()
    if ultima and ultima["colunas_chave"] != detalhes["colunas_chave"]:
        raise LoteRejeitado("As colunas que formam a chave do título mudaram em relação à última importação "
                            f"({ultima['colunas_chave']} → {detalhes['colunas_chave']}). Importar assim poderia "
                            "duplicar títulos; confira o layout da exportação.", detalhes)
    regras = regras_restricao(config)
    avisos = leitura.avisos + validar_regras(cadastro, regras)
    filiais = {t.filial for t in leitura.titulos}
    conferencia = conferir_lote(leitura, config, cadastro, regras, filiais, escopo, detalhes)
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
                                   "avisos": json.dumps(avisos, ensure_ascii=False), **conferencia["colunas"]})
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
            "periodo": [inicio.isoformat(), fim.isoformat()], "avisos": avisos,
            "completa": conferencia["completa"], "completa_publica": conferencia["completa_publica"],
            "rejeitadas_publicas": conferencia["colunas"]["rejeitadas_publicas"],
            "pendencias": conferencia["pendencias"]}


def conferir_lote(leitura, config: dict, cadastro: dict, regras: dict, filiais: set[str], escopo: dict | None,
                  detalhes: dict) -> dict:
    """Reconciliação com o total do arquivo, linhas descartadas e abrangência de filiais.

    Divergência de total sem explicação rejeita o lote (LoteRejeitado). O resto vira
    pendência: o lote é gravado, mas não é publicado como completo.
    """
    tamanho = int(config["agente"]["tamanho_codigo_filial"])
    pendencias: list[dict] = []

    def pendencia(codigo, texto, restrita, bloqueia=True):
        pendencias.append({"codigo": codigo, "texto": texto, "restrita": bool(restrita), "bloqueia": bloqueia})

    # Linhas descartadas: restritas quando a filial/natureza/prefixo indicam a área restrita ou
    # quando não dá para saber (filial ilegível ou fora do cadastro).
    rejeitadas_restritas = rejeitadas_publicas = sem_valor = 0
    sem_valor_restrita = False
    valor_rejeitado = 0
    for linha in leitura.rejeitadas_detalhe:
        ref = SimpleNamespace(filial=linha["filial"], natureza=linha["natureza"], prefixo=linha["prefixo"])
        restrita = not linha["filial"] or classificar(ref, cadastro, regras)[0]
        rejeitadas_restritas += restrita
        rejeitadas_publicas += not restrita
        if linha["valor_centavos"] is None:
            sem_valor += 1
            sem_valor_restrita |= restrita
        else:
            valor_rejeitado += linha["valor_centavos"]
    if rejeitadas_publicas:
        pendencia("linhas_descartadas", f"{rejeitadas_publicas} linha(s) descartada(s) sem reconciliação "
                  "(motivos em importacao_rejeicoes).", False)
    if rejeitadas_restritas:
        pendencia("linhas_descartadas_restritas", f"{rejeitadas_restritas} linha(s) descartada(s) da área restrita "
                  "ou de classificação incerta, sem reconciliação.", True)

    # Total do arquivo.
    soma = sum(t.valor_centavos for t in leitura.titulos)
    total_arquivo, total_conferido = None, None
    legiveis = [v for _, v in leitura.totais if v is not None]
    if leitura.totais:
        geral = [v for rotulo, v in leitura.totais if "GERAL" in rotulo and v is not None]
        total_arquivo = geral[-1] if geral else (legiveis[-1] if len(leitura.totais) == 1 and legiveis else None)
        if total_arquivo is None:
            pendencia("total_nao_conferido", "Linha de total do arquivo ilegível ou ambígua; total não conferido.",
                      False)
        elif sem_valor:
            total_conferido = False
            pendencia("total_nao_conferido", "Total do arquivo não conferido: há linhas descartadas sem valor "
                      "legível.", sem_valor_restrita)
        elif soma + valor_rejeitado != total_arquivo:
            detalhes.update({"total_arquivo_centavos": total_arquivo, "valor_rejeitado_centavos": valor_rejeitado})
            raise LoteRejeitado("A soma das linhas não confere com a linha de total do próprio arquivo; a "
                                "exportação pode estar truncada. O painel continua com a última versão válida.",
                                detalhes)
        else:
            total_conferido = True

    # Abrangência de filiais.
    configuradas = [str(f).zfill(tamanho) if str(f).isdigit() else str(f)
                    for f in config["agente"].get("filiais_esperadas") or []]
    esperadas = set(configuradas) or set(cadastro)
    restrita_filial = lambda f: classificar(SimpleNamespace(filial=f, natureza="", prefixo=""), cadastro, regras)[0]
    if escopo is None:
        pendencia("escopo_nao_verificado", "Filtro e abrangência da consulta não verificados na tela do TOTVS "
                  "(arquivo importado sem o executor do navegador).", False)
    else:
        if not escopo.get("filtro_confirmado"):
            pendencia("filtro_nao_confirmado", "Filtro Vencimento = Mês Atual não confirmado na tela.", False)
        if not escopo.get("filiais_confirmadas"):
            pendencia("filiais_nao_confirmadas", "Abrangência de filiais não confirmada na tela do TOTVS "
                      "(configure navegador.textos.filiais_todas após a calibração).", False)
    if len(esperadas) > 1 and len(filiais) == 1:
        pendencia("filial_unica", "O arquivo tem títulos de uma única filial; a abrangência esperada é maior. "
                  "Confira se há filtro de filial ativo.", restrita_filial(next(iter(filiais))))
    fora = filiais - esperadas
    if fora and configuradas:
        publicas = [f for f in fora if not restrita_filial(f)]
        if publicas:
            pendencia("filiais_fora_escopo", f"{len(publicas)} filial(is) fora das filiais esperadas.", False)
        if len(fora) > len(publicas):
            pendencia("filiais_fora_escopo_restritas", "Filial(is) da área restrita fora das esperadas.", True)
    ausentes = esperadas - filiais
    if ausentes:
        publicas = [f for f in ausentes if not restrita_filial(f)]
        if publicas:
            pendencia("filiais_sem_titulos", f"{len(publicas)} filial(is) esperada(s) sem títulos no arquivo "
                      "(pode ser normal no mês).", False, bloqueia=False)
        if len(ausentes) > len(publicas):
            pendencia("filiais_sem_titulos_restritas", "Filial(is) da área restrita sem títulos no arquivo.", True,
                      bloqueia=False)

    completa = not any(p["bloqueia"] for p in pendencias)
    completa_publica = not any(p["bloqueia"] and not p["restrita"] for p in pendencias)
    return {
        "completa": completa, "completa_publica": completa_publica, "pendencias": pendencias,
        "colunas": {"completa": int(completa), "completa_publica": int(completa_publica),
                    "pendencias": json.dumps(pendencias, ensure_ascii=False),
                    "rejeitadas_publicas": rejeitadas_publicas, "total_arquivo_centavos": total_arquivo,
                    "valor_rejeitado_centavos": valor_rejeitado,
                    "total_conferido": None if total_conferido is None else int(total_conferido),
                    "escopo": json.dumps(escopo, ensure_ascii=False) if escopo is not None else None,
                    "filiais_esperadas": len(esperadas)},
    }


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
