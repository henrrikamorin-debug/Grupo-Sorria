"""Execução do agente TOTVS: coleta (arquivo exportado) → importação → atualização do painel.

Cada execução fica registrada em ``execucoes_agente`` com início, término,
etapa, tentativas, arquivo (hash) e resultado.

* Execuções nunca se sobrepõem (trava com validade no banco, vale entre
  processos: Claude Code, agendador e linha de comando).
* Execução interrompida (computador desligado, processo encerrado) é marcada
  como "interrompida" na próxima vez; se ela já tinha recebido o arquivo e
  ainda não o importou, a próxima execução retoma desse ponto, revalidando o
  arquivo (mesmo mês, não importado antes).
* Falhas temporárias (arquivo ainda travado pelo navegador, banco ocupado)
  têm tentativas limitadas; falhas de validação não são repetidas.
* Se a importação ou a atualização do painel falhar, o painel continua com a
  última versão válida, e a situação mostra a falha.

A exportação em si (abrir o TOTVS, Consulta Genérica, SE2, filtro, Exp. CSV)
é feita na interface do TOTVS: pelo Claude Code com a extensão Claude in
Chrome no computador do financeiro (procedimento em
``.claude/commands/coletar-totvs.md``) ou por uma pessoa. O agente aguarda o
arquivo NOVO na pasta de entrada e só aceita arquivos gerados depois do
início da execução.
"""

from __future__ import annotations

import logging
import os
import socket
import sqlite3
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .. import db
from ..cadastros import carregar_filiais
from ..coleta import ServicoColeta
from ..config import caminho_banco, caminho_contratos, pasta_agente, pasta_entrada_agente
from ..conectores.totvs_se2 import ConectorTotvsSE2
from ..regras import regras_do_modo
from .contratos import carregar as carregar_contratos
from .importacao import importar_arquivo, periodo_mes_atual

log = logging.getLogger(__name__)

TEMPORARIAS = (OSError, sqlite3.OperationalError)


class AgenteTotvs:
    def __init__(self, config: dict, caminho_filiais: Path, *, dormir=time.sleep, relogio=None):
        self.config = config
        self.cfg = config["agente"]
        self.config_real = {**config, "modo": "real"}  # o agente grava sempre no banco real
        self.caminho_banco = caminho_banco(self.config_real)
        self.caminho_filiais = caminho_filiais
        self.pasta = pasta_agente(config)
        self.entrada = pasta_entrada_agente(config)
        self.dono = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self._dormir = dormir
        self._relogio = relogio or (lambda: datetime.now(timezone.utc))
        db.inicializar(self.caminho_banco, "real")

    # ---------------------------------------------------------------- trava
    def _adquirir(self, conexao, execucao_id: int) -> bool:
        agora = self._relogio()
        expira = agora + timedelta(minutes=float(self.cfg["tempo_maximo_execucao_minutos"]))
        with db.transacao(conexao):
            cursor = conexao.execute(
                "UPDATE trava_agente SET dono = ?, expira_em = ? WHERE id = 1 AND (dono IS NULL OR expira_em < ?)",
                (self.dono, expira.isoformat(timespec="seconds"), agora.isoformat(timespec="seconds")))
            if cursor.rowcount == 1:
                # Quem estava em andamento sem trava válida foi interrompido.
                conexao.execute("UPDATE execucoes_agente SET situacao = 'interrompida', finalizada_em = ?, "
                                "mensagem = COALESCE(mensagem, 'Interrompida antes de terminar.') "
                                "WHERE situacao = 'em_andamento' AND id != ?",
                                (agora.isoformat(timespec="seconds"), execucao_id))
        return cursor.rowcount == 1

    def _liberar(self, conexao) -> None:
        conexao.execute("UPDATE trava_agente SET dono = NULL, expira_em = NULL WHERE id = 1 AND dono = ?",
                        (self.dono,))

    # ---------------------------------------------------------------- registro
    def _atualizar(self, conexao, execucao_id: int, **campos) -> None:
        sets = ", ".join(f"{k} = ?" for k in campos)
        conexao.execute(f"UPDATE execucoes_agente SET {sets} WHERE id = ?", [*campos.values(), execucao_id])

    def _com_tentativas(self, conexao, execucao_id: int, descricao: str, funcao):
        tentativas = max(1, int(self.cfg["tentativas"]))
        for tentativa in range(1, tentativas + 1):
            self._atualizar(conexao, execucao_id, tentativas=tentativa)
            try:
                return funcao()
            except TEMPORARIAS as erro:
                if tentativa == tentativas:
                    raise
                log.warning("%s: falha temporária (%s); nova tentativa %d/%d.", descricao,
                            type(erro).__name__, tentativa + 1, tentativas)
                self._dormir(float(self.cfg["espera_entre_tentativas_segundos"]))

    # ---------------------------------------------------------------- arquivo
    def _arquivo_pendente(self, conexao) -> tuple[Path, datetime] | None:
        """Arquivo recebido por execução interrompida e ainda não importado (retomada)."""
        linha = conexao.execute(
            "SELECT iniciada_em, arquivo_caminho, periodo_inicio FROM execucoes_agente WHERE situacao = 'interrompida' "
            "AND arquivo_caminho IS NOT NULL AND importacao_id IS NULL ORDER BY id DESC LIMIT 1").fetchone()
        if not linha:
            return None
        caminho = Path(linha["arquivo_caminho"])
        inicio, _ = periodo_mes_atual(self._relogio().astimezone().date())
        if not caminho.exists() or linha["periodo_inicio"] != inicio.isoformat():
            return None
        return caminho, datetime.fromisoformat(linha["iniciada_em"])

    def aguardar_arquivo(self, inicio: datetime, espera_minutos: float | None = None) -> Path | None:
        """Espera um CSV novo (gerado após ``inicio``) e com tamanho estável na pasta de entrada."""
        self.entrada.mkdir(parents=True, exist_ok=True)
        limite = self._relogio() + timedelta(minutes=float(
            self.cfg["tempo_espera_minutos"] if espera_minutos is None else espera_minutos))
        tolerancia = timedelta(seconds=int(self.cfg["tolerancia_relogio_segundos"]))
        intervalo = float(self.cfg["intervalo_verificacao_segundos"])
        estabilidade = float(self.cfg["segundos_tamanho_estavel"])
        while True:
            candidatos = []
            for arquivo in self.entrada.glob(self.cfg["padrao_arquivo"]):
                modificado = datetime.fromtimestamp(arquivo.stat().st_mtime, timezone.utc)
                if arquivo.is_file() and modificado >= inicio - tolerancia:
                    candidatos.append((modificado, arquivo))
            if candidatos:
                candidatos.sort()
                arquivo = candidatos[-1][1]
                if len(candidatos) > 1:
                    log.warning("%d arquivos novos na entrada; usado o mais recente.", len(candidatos))
                tamanho = arquivo.stat().st_size
                self._dormir(estabilidade)
                if arquivo.exists() and arquivo.stat().st_size == tamanho and tamanho > 0:
                    try:
                        with open(arquivo, "rb") as teste:
                            teste.read(1)
                        return arquivo
                    except OSError:
                        pass  # ainda em uso pelo navegador
            if self._relogio() >= limite:
                return None
            self._dormir(intervalo)

    # ---------------------------------------------------------------- execução
    def executar(self, origem: str = "manual", arquivo: Path | None = None, espera_minutos: float | None = None,
                 confirmar_arquivo_antigo: bool = False, aceitar_filial_unica: bool = False) -> dict:
        """Uma execução completa. ``arquivo`` informado = importação manual daquele arquivo."""
        inicio = self._relogio()
        hoje = inicio.astimezone().date()
        periodo = periodo_mes_atual(hoje)
        with db.fechando(db.conectar(self.caminho_banco)) as conexao:
            execucao_id = conexao.execute(
                "INSERT INTO execucoes_agente (iniciada_em, situacao, origem, etapa, periodo_inicio, periodo_fim) "
                "VALUES (?, 'em_andamento', ?, 'iniciando', ?, ?)",
                (inicio.isoformat(timespec="seconds"), origem, periodo[0].isoformat(), periodo[1].isoformat()),
            ).lastrowid
            if not self._adquirir(conexao, execucao_id):
                mensagem = "Outra execução do agente está em andamento; esta foi encerrada sem alterar nada."
                self._atualizar(conexao, execucao_id, situacao="bloqueada", etapa="trava", mensagem=mensagem,
                                finalizada_em=db.agora_iso())
                log.warning(mensagem)
                return {"situacao": "bloqueada", "execucao_id": execucao_id, "mensagem": mensagem}
            try:
                return self._executar(conexao, execucao_id, origem, inicio, hoje, arquivo, espera_minutos,
                                      confirmar_arquivo_antigo, aceitar_filial_unica)
            except Exception as erro:  # noqa: BLE001 — toda falha fica registrada
                log.exception("Execução %s do agente falhou.", execucao_id)
                mensagem = f"{type(erro).__name__}: {erro}"[:500]
                self._atualizar(conexao, execucao_id, situacao="falha", mensagem=mensagem, finalizada_em=db.agora_iso())
                return {"situacao": "falha", "execucao_id": execucao_id, "mensagem": mensagem}
            finally:
                self._liberar(conexao)

    def _executar(self, conexao, execucao_id, origem, inicio, hoje, arquivo, espera_minutos,
                  confirmar_arquivo_antigo, aceitar_filial_unica) -> dict:
        inicio_validacao: datetime | None = inicio
        if arquivo is not None:
            inicio_validacao = None  # importação manual: vale o limite de idade do arquivo
            arquivo = Path(arquivo)
        else:
            pendente = self._arquivo_pendente(conexao)
            if pendente:
                arquivo, inicio_validacao = pendente
                log.info("Retomando execução interrompida com o arquivo %s.", arquivo.name)
                self._atualizar(conexao, execucao_id, mensagem="Retomada de execução interrompida.")
            else:
                self._atualizar(conexao, execucao_id, etapa="aguardando_exportacao")
                arquivo = self.aguardar_arquivo(inicio, espera_minutos)
                if arquivo is None:
                    mensagem = (f"Nenhuma exportação nova apareceu em {self.entrada} no tempo de espera. "
                                "O painel continua com a última importação válida.")
                    self._atualizar(conexao, execucao_id, situacao="sem_arquivo", etapa="aguardando_exportacao",
                                    mensagem=mensagem, finalizada_em=db.agora_iso())
                    return {"situacao": "sem_arquivo", "execucao_id": execucao_id, "mensagem": mensagem}
        self._atualizar(conexao, execucao_id, etapa="importando", arquivo_caminho=str(arquivo))

        cadastro = carregar_filiais(self.caminho_filiais)
        resultado = self._com_tentativas(conexao, execucao_id, "Importação", lambda: importar_arquivo(
            conexao, arquivo, self.config, cadastro, hoje=hoje, inicio_execucao=inicio_validacao,
            execucao_id=execucao_id, confirmar_arquivo_antigo=confirmar_arquivo_antigo,
            aceitar_filial_unica=aceitar_filial_unica, pasta_arquivo=self.pasta))
        self._atualizar(conexao, execucao_id, importacao_id=resultado["importacao_id"])
        if resultado["situacao"] == "rejeitada":
            self._atualizar(conexao, execucao_id, situacao="falha", etapa="importando",
                            mensagem=f"Lote rejeitado: {resultado['mensagem']}"[:500], finalizada_em=db.agora_iso())
            return {**resultado, "execucao_id": execucao_id, "situacao_execucao": "falha"}

        self._atualizar(conexao, execucao_id, etapa="atualizando_painel")
        painel = self._com_tentativas(conexao, execucao_id, "Atualização do painel", self._atualizar_painel)
        self._atualizar(conexao, execucao_id, coleta_id=painel.get("coleta_id"))
        if painel["situacao"] != "sucesso":
            mensagem = f"Importação {resultado['situacao']}, mas o painel não foi atualizado: {painel.get('mensagem')}"
            self._atualizar(conexao, execucao_id, situacao="falha", mensagem=mensagem[:500],
                            finalizada_em=db.agora_iso())
            return {**resultado, "execucao_id": execucao_id, "situacao_execucao": "falha", "painel": painel}
        # Mensagem sem totais: o histórico é visto por quem não tem acesso à área restrita.
        mensagem = (resultado.get("mensagem") or
                    f"Importação nº {resultado['importacao_id']} concluída; "
                    f"{resultado['rejeitadas']} linha(s) rejeitada(s).")
        self._atualizar(conexao, execucao_id, situacao="sucesso", etapa="concluida", mensagem=mensagem,
                        finalizada_em=db.agora_iso())
        return {**resultado, "execucao_id": execucao_id, "situacao_execucao": "sucesso", "painel": painel}

    def _atualizar_painel(self) -> dict:
        conector = ConectorTotvsSE2(self.caminho_banco, carregar_contratos(caminho_contratos()))
        servico = ServicoColeta(self.config_real, self.caminho_banco, conector,
                                regras_do_modo("real", self.config_real), caminho_filiais=self.caminho_filiais)
        resultado = servico.executar("agente TOTVS")
        if resultado["situacao"] == "ignorada":
            raise sqlite3.OperationalError("painel ocupado por outra atualização")  # temporária: tenta de novo
        return resultado

    # ---------------------------------------------------------------- consultas
    def historico(self, limite: int = 15) -> list[dict]:
        with db.fechando(db.conectar(self.caminho_banco)) as conexao:
            return [dict(r) for r in conexao.execute(
                "SELECT e.id, e.iniciada_em, e.finalizada_em, e.situacao, e.origem, e.etapa, e.tentativas, "
                "e.mensagem, i.arquivo_nome, i.situacao AS importacao, i.publicos, i.rejeitadas "
                "FROM execucoes_agente e LEFT JOIN importacoes i ON i.id = e.importacao_id "
                "ORDER BY e.id DESC LIMIT ?", (limite,))]
