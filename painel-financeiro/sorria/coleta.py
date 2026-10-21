"""Serviço de coleta e agendador.

* Execuções nunca se sobrepõem: há uma trava no processo e outra no banco
  (vale também se, por engano, dois serviços forem iniciados).
* O retrato de dados só é substituído numa transação, após sucesso completo.
  Em caso de falha, a falha é registrada e a última coleta válida permanece.
* Lançamentos repetidos na origem (mesma referência) são consolidados, e cada
  ocorrência é única por (lançamento, regra).
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

from . import db
from .cadastros import carregar_filiais, classificar_categoria
from .conectores.base import Conector, ConectorNaoConfigurado, Lancamento, ResultadoColeta
from .regras import analisar
from .regras.base import Regra

log = logging.getLogger(__name__)

HISTORICO_MAXIMO = 5000


class ServicoColeta:
    def __init__(self, config: dict, caminho_banco: Path, conector: Conector, regras: list[Regra],
                 caminho_filiais: Path | None = None):
        self.config = config
        self.caminho_filiais = caminho_filiais
        self.ao_concluir: list = []  # funções chamadas após cada coleta bem-sucedida
        self.caminho_banco = caminho_banco
        self.conector = conector
        self.regras = regras
        self.dono = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self._trava_local = threading.Lock()
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self._ultimo_inicio: float | None = None
        self.proxima_execucao: float | None = None
        self._marcar_interrompidas()

    # ------------------------------------------------------------------ agendador
    @property
    def agendador_ativo(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def em_andamento(self) -> bool:
        return self._trava_local.locked()

    def iniciar_agendador(self) -> None:
        if not self.config["coleta"]["habilitada"] or self.agendador_ativo:
            return
        self._parar.clear()
        self._thread = threading.Thread(target=self._laco, name="agendador-coleta", daemon=True)
        self._thread.start()

    def parar_agendador(self) -> None:
        self._parar.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _laco(self) -> None:
        intervalo = float(self.config["coleta"]["intervalo_minutos"]) * 60
        log.info("Agendador iniciado: coleta a cada %.0f minuto(s).", intervalo / 60)
        if self.config["coleta"]["executar_ao_iniciar"]:
            self.executar("inicial")
        while not self._parar.is_set():
            base = self._ultimo_inicio or time.time()
            self.proxima_execucao = base + intervalo
            if self._parar.wait(max(0.0, self.proxima_execucao - time.time())):
                break
            self.executar("agendada")
        log.info("Agendador encerrado.")

    # ------------------------------------------------------------------ execução
    def executar(self, origem: str = "manual", simular_falha: bool = False) -> dict:
        if simular_falha and not self.conector.simulado:
            raise ValueError("Falha simulada só é permitida no modo demonstração.")
        if not self._trava_local.acquire(blocking=False):
            log.info("Coleta %s ignorada: outra coleta já está em andamento.", origem)
            return {"situacao": "ignorada", "mensagem": "Já existe uma coleta em andamento."}
        try:
            self._ultimo_inicio = time.time()
            with db.fechando(db.conectar(self.caminho_banco)) as conexao:
                if not self._adquirir_trava(conexao):
                    log.warning("Coleta %s ignorada: trava ocupada por outro processo.", origem)
                    return {"situacao": "ignorada",
                            "mensagem": "Outra instância do serviço está coletando."}
                try:
                    return self._executar(conexao, origem, simular_falha)
                finally:
                    self._liberar_trava(conexao)
        finally:
            self._trava_local.release()

    def _adquirir_trava(self, conexao) -> bool:
        agora = db.agora()
        expira = agora + timedelta(minutes=self.config["coleta"]["tempo_maximo_minutos"])
        with db.transacao(conexao):
            cursor = conexao.execute(
                "UPDATE trava_coleta SET dono = ?, expira_em = ? "
                "WHERE id = 1 AND (dono IS NULL OR expira_em < ?)",
                (self.dono, expira.isoformat(timespec="seconds"), agora.isoformat(timespec="seconds")),
            )
        return cursor.rowcount == 1

    def _liberar_trava(self, conexao) -> None:
        conexao.execute("UPDATE trava_coleta SET dono = NULL, expira_em = NULL WHERE id = 1 AND dono = ?",
                        (self.dono,))

    def _marcar_interrompidas(self) -> None:
        with db.fechando(db.conectar(self.caminho_banco)) as conexao:
            conexao.execute(
                "UPDATE coletas SET situacao = 'falha', finalizada_em = ?, "
                "mensagem = 'Interrompida: o serviço foi encerrado durante a coleta.' "
                "WHERE situacao = 'em_andamento'", (db.agora_iso(),))

    def _executar(self, conexao, origem: str, simular_falha: bool = False) -> dict:
        cursor = conexao.execute(
            "INSERT INTO coletas (iniciada_em, situacao, origem, simulada, conector) "
            "VALUES (?, 'em_andamento', ?, ?, ?)",
            (db.agora_iso(), origem, int(self.conector.simulado), self.conector.nome),
        )
        coleta_id = cursor.lastrowid
        inicio_relogio = time.monotonic()
        try:
            if simular_falha:
                raise RuntimeError("Falha simulada de coleta (modo demonstração).")
            hoje = date.today()
            janela = int(self.config["coleta"]["janela_dias"])
            resultado = self.conector.coletar(hoje - timedelta(days=janela - 1), hoje)
            filiais = carregar_filiais(self.caminho_filiais) if self.caminho_filiais else {}
            lancamentos = _consolidar(resultado, self.config, filiais)
            if not lancamentos and not self.config["coleta"]["aceitar_coleta_vazia"]:
                anteriores = conexao.execute("SELECT COUNT(*) FROM lancamentos").fetchone()[0]
                if anteriores:
                    raise ValueError("A origem não retornou lançamentos; retrato anterior preservado.")
            ocorrencias = analisar(lancamentos, resultado.referencias, self.regras)
            limite = self.config["coleta"]["tempo_maximo_minutos"] * 60
            if time.monotonic() - inicio_relogio > limite:
                raise TimeoutError("A coleta excedeu o tempo máximo configurado; resultado descartado.")
            self._gravar(conexao, coleta_id, resultado, lancamentos, ocorrencias)
        except Exception as erro:  # noqa: BLE001 — toda falha precisa ser registrada
            if isinstance(erro, ConectorNaoConfigurado):
                log.error("Coleta %s (nº %s) não executada: %s", origem, coleta_id, erro)
            else:
                log.exception("Coleta %s (nº %s) falhou.", origem, coleta_id)
            conexao.execute(
                "UPDATE coletas SET situacao = 'falha', finalizada_em = ?, mensagem = ? WHERE id = ?",
                (db.agora_iso(), _mensagem(erro)[:500], coleta_id),
            )
            return {"situacao": "falha", "coleta_id": coleta_id, "mensagem": str(erro)}
        log.info("Coleta %s (nº %s) concluída: %d registros, %d ocorrências%s.", origem, coleta_id,
                 len(lancamentos), len(ocorrencias), " [SIMULADA]" if resultado.simulada else "")
        for funcao in self.ao_concluir:
            try:
                funcao()
            except Exception:  # noqa: BLE001 — uma tarefa posterior não invalida a coleta
                log.exception("Tarefa após a coleta nº %s falhou.", coleta_id)
        return {"situacao": "sucesso", "coleta_id": coleta_id, "registros": len(lancamentos),
                "ocorrencias": len(ocorrencias), "simulada": resultado.simulada}

    def _gravar(self, conexao, coleta_id: int, resultado: ResultadoColeta,
                lancamentos: list[Lancamento], ocorrencias: list[dict]) -> None:
        agora = db.agora_iso()
        situacao_inicial = getattr(self.conector, "situacao_inicial", None)
        with db.transacao(conexao):
            conexao.execute("DELETE FROM ocorrencias")
            conexao.execute("DELETE FROM lancamentos")
            conexao.executemany(
                "INSERT INTO lancamentos (referencia, clinica, categoria, data, valor_centavos, descricao, "
                "favorecido, pessoa_fisica, documento, dados_bancarios, filial, titulo, prefixo, extras, "
                "coleta_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(l.referencia, l.clinica, l.categoria, l.data, l.valor_centavos, l.descricao,
                  l.favorecido, int(l.pessoa_fisica), l.documento, l.dados_bancarios,
                  l.filial, l.titulo, l.prefixo, db.json_dump(l.extras), coleta_id) for l in lancamentos],
            )
            conexao.executemany(
                "INSERT INTO ocorrencias (id, referencia, regra_codigo, regra_nome, descricao, evidencia, "
                "clinica, categoria, data, valor_centavos, filial, titulo, detectada_em, coleta_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(o["id"], o["referencia"], o["regra_codigo"], o["regra_nome"], o["descricao"],
                  db.json_dump(o["evidencia"]), o["clinica"], o["categoria"], o["data"],
                  o["valor_centavos"], o["filial"], o["titulo"], agora, coleta_id) for o in ocorrencias],
            )
            conexao.executemany(
                "INSERT OR IGNORE INTO situacao_ocorrencias (id, situacao, primeira_deteccao, atualizada_em) "
                "VALUES (?, ?, ?, ?)",
                [(o["id"], situacao_inicial(o["id"], o["data"]) if situacao_inicial else "pendente",
                  agora, agora) for o in ocorrencias],
            )
            conexao.execute(
                "UPDATE coletas SET situacao = 'sucesso', finalizada_em = ?, registros = ?, "
                "ocorrencias = ?, mensagem = ? WHERE id = ?",
                (db.agora_iso(), len(lancamentos), len(ocorrencias), resultado.observacao or None, coleta_id),
            )
            conexao.execute(
                "DELETE FROM coletas WHERE id <= (SELECT MAX(id) FROM coletas) - ?", (HISTORICO_MAXIMO,))


def _mensagem(erro: Exception) -> str:
    if isinstance(erro, (ConectorNaoConfigurado, ValueError, TimeoutError)) or str(erro).startswith("Falha simulada"):
        return str(erro)
    return f"{type(erro).__name__}: {erro}"


def _consolidar(resultado: ResultadoColeta, config: dict | None = None,
                filiais: dict | None = None) -> list[Lancamento]:
    """Completa clínica e categoria, valida o mínimo e remove referências repetidas.

    * Clínica vazia: nome da filial no cadastro (ou "Filial <código>").
    * Categoria vazia: definida pelo prefixo do título; sem prefixo = "Diversos".
    """
    config_categorias = (config or {}).get("categorias", {})
    mapa = {**resultado.referencias.get("categorias_por_prefixo", {}),
            **config_categorias.get("por_prefixo", {})}
    sem_prefixo = config_categorias.get("sem_prefixo", "Diversos")
    filiais = {**resultado.referencias.get("filiais", {}), **(filiais or {})}
    unicos: dict[str, Lancamento] = {}
    for l in resultado.lancamentos:
        if not l.clinica and l.filial:
            l.clinica = filiais.get(l.filial, {}).get("nome") or f"Filial {l.filial}"
        if not l.categoria:
            l.categoria = classificar_categoria(l.prefixo, mapa, sem_prefixo)
        if not l.referencia or not l.clinica or not l.categoria:
            raise ValueError(f"Lançamento incompleto recebido da origem: {l.referencia!r}")
        date.fromisoformat(l.data)  # levanta ValueError se a data for inválida
        if l.referencia in unicos:
            log.warning("Referência %s repetida na origem; mantida a última versão.", l.referencia)
        unicos[l.referencia] = l
    return list(unicos.values())
