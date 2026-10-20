"""Armazenamento local (SQLite).

Tabelas principais:

* ``coletas``      histórico de execuções (sucesso, falha, simulada ou não);
* ``lancamentos``  último retrato válido dos lançamentos coletados;
* ``ocorrencias``  inconsistências detectadas no último retrato válido;
* ``situacao_ocorrencias`` situação de acompanhamento (pendente, em análise,
  resolvida), mantida entre coletas pela identificação estável da ocorrência;
* ``trava_coleta`` impede coletas simultâneas, inclusive entre processos;
* ``uso_ia`` / ``cache_ia`` consumo e reaproveitamento de respostas do agente.

O retrato só é substituído dentro de uma transação, ao final de uma coleta
bem-sucedida. Se a coleta falhar, o retrato anterior permanece intacto.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS meta (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS coletas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    iniciada_em TEXT NOT NULL,
    finalizada_em TEXT,
    situacao TEXT NOT NULL CHECK (situacao IN ('em_andamento', 'sucesso', 'falha')),
    origem TEXT NOT NULL,
    simulada INTEGER NOT NULL,
    conector TEXT NOT NULL,
    registros INTEGER,
    ocorrencias INTEGER,
    mensagem TEXT
);
CREATE TABLE IF NOT EXISTS lancamentos (
    referencia TEXT PRIMARY KEY,
    clinica TEXT NOT NULL,
    categoria TEXT NOT NULL,
    data TEXT NOT NULL,
    valor_centavos INTEGER,
    descricao TEXT NOT NULL DEFAULT '',
    favorecido TEXT,
    pessoa_fisica INTEGER NOT NULL DEFAULT 0,
    documento TEXT,
    dados_bancarios TEXT,
    extras TEXT NOT NULL DEFAULT '{}',
    coleta_id INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_lancamentos_data ON lancamentos (data);
CREATE TABLE IF NOT EXISTS ocorrencias (
    id TEXT PRIMARY KEY,
    referencia TEXT NOT NULL,
    regra_codigo TEXT NOT NULL,
    regra_nome TEXT NOT NULL,
    descricao TEXT NOT NULL,
    evidencia TEXT NOT NULL,
    clinica TEXT NOT NULL,
    categoria TEXT NOT NULL,
    data TEXT NOT NULL,
    valor_centavos INTEGER,
    detectada_em TEXT NOT NULL,
    coleta_id INTEGER NOT NULL,
    UNIQUE (referencia, regra_codigo)
);
CREATE INDEX IF NOT EXISTS ix_ocorrencias_data ON ocorrencias (data);
CREATE TABLE IF NOT EXISTS situacao_ocorrencias (
    id TEXT PRIMARY KEY,
    situacao TEXT NOT NULL CHECK (situacao IN ('pendente', 'em_analise', 'resolvida')),
    primeira_deteccao TEXT NOT NULL,
    atualizada_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trava_coleta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    dono TEXT,
    expira_em TEXT
);
INSERT OR IGNORE INTO trava_coleta (id, dono, expira_em) VALUES (1, NULL, NULL);
CREATE TABLE IF NOT EXISTS uso_ia (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    em TEXT NOT NULL,
    finalidade TEXT NOT NULL,
    modelo TEXT,
    tokens_entrada INTEGER,
    tokens_saida INTEGER,
    reaproveitado INTEGER NOT NULL DEFAULT 0,
    hash_entrada TEXT,
    observacao TEXT
);
CREATE TABLE IF NOT EXISTS cache_ia (
    hash TEXT PRIMARY KEY,
    modelo TEXT NOT NULL,
    resposta TEXT NOT NULL,
    criado_em TEXT NOT NULL
);
"""

SITUACOES = ("pendente", "em_analise", "resolvida")


def agora() -> datetime:
    return datetime.now(timezone.utc)


def agora_iso() -> str:
    return agora().isoformat(timespec="seconds")


class ModoIncompativel(RuntimeError):
    pass


def conectar(caminho: Path) -> sqlite3.Connection:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    conexao = sqlite3.connect(caminho, timeout=30, isolation_level=None,
                              check_same_thread=False)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA journal_mode=WAL")
    conexao.execute("PRAGMA foreign_keys=ON")
    return conexao


def inicializar(caminho: Path, modo: str) -> None:
    """Cria o esquema e grava o modo do banco.

    Um banco criado em modo demonstração nunca é aberto em modo real (e
    vice-versa): isso evita que dados fictícios apareçam como reais.
    """
    with fechando(conectar(caminho)) as conexao:
        conexao.executescript(ESQUEMA)
        linha = conexao.execute("SELECT valor FROM meta WHERE chave = 'modo'").fetchone()
        if linha is None:
            conexao.execute("INSERT INTO meta (chave, valor) VALUES ('modo', ?)", (modo,))
        elif linha["valor"] != modo:
            raise ModoIncompativel(
                f"O banco {caminho} pertence ao modo {linha['valor']!r}, "
                f"mas o sistema está configurado para {modo!r}."
            )


@contextmanager
def fechando(conexao: sqlite3.Connection):
    try:
        yield conexao
    finally:
        conexao.close()


@contextmanager
def transacao(conexao: sqlite3.Connection):
    conexao.execute("BEGIN IMMEDIATE")
    try:
        yield conexao
    except BaseException:
        conexao.execute("ROLLBACK")
        raise
    else:
        conexao.execute("COMMIT")


def json_dump(valor) -> str:
    return json.dumps(valor, ensure_ascii=False, sort_keys=True)
