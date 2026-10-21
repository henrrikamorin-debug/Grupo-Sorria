"""Senha da área restrita (filial do escritório: folha e pagamentos a PJ).

* A senha é definida no computador do serviço (``python -m sorria
  definir-senha``) e só o hash PBKDF2 é gravado em ``dados/acesso.json``.
* Sem senha definida, a área restrita fica bloqueada para todos.
* Desbloquear cria uma sessão temporária (cookie HttpOnly), que expira sozinha.
* O modo televisão nunca mostra a área restrita, mesmo desbloqueada.
* Tentativas erradas são limitadas para dificultar adivinhação.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from pathlib import Path

ITERACOES = 310_000
TAMANHO_MINIMO = 8
MAX_TENTATIVAS = 5
JANELA_TENTATIVAS_S = 300


class AcessoNegado(Exception):
    pass


class MuitasTentativas(Exception):
    pass


def _hash(senha: str, sal: bytes, iteracoes: int) -> str:
    return hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), sal, iteracoes).hex()


def definir_senha(caminho: Path, senha: str) -> None:
    if len(senha) < TAMANHO_MINIMO:
        raise ValueError(f"A senha precisa ter pelo menos {TAMANHO_MINIMO} caracteres.")
    sal = secrets.token_bytes(16)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(json.dumps({
        "algoritmo": "pbkdf2_sha256", "iteracoes": ITERACOES, "sal": sal.hex(),
        "hash": _hash(senha, sal, ITERACOES),
    }), encoding="utf-8")
    temporario.replace(caminho)


def senha_definida(caminho: Path) -> bool:
    return caminho.exists()


def conferir_senha(caminho: Path, senha: str) -> bool:
    if not caminho.exists():
        return False
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    calculado = _hash(senha, bytes.fromhex(dados["sal"]), int(dados["iteracoes"]))
    return hmac.compare_digest(calculado, dados["hash"])


class Sessoes:
    """Sessões de desbloqueio em memória (somem se o serviço reiniciar)."""

    def __init__(self, caminho_senha: Path, minutos: float):
        self.caminho_senha = caminho_senha
        self.duracao = minutos * 60
        self._sessoes: dict[str, float] = {}
        self._falhas: list[float] = []
        self._trava = threading.Lock()

    def desbloquear(self, senha: str) -> tuple[str, float]:
        agora = time.time()
        with self._trava:
            self._falhas = [t for t in self._falhas if agora - t < JANELA_TENTATIVAS_S]
            if len(self._falhas) >= MAX_TENTATIVAS:
                raise MuitasTentativas("Muitas tentativas erradas. Aguarde alguns minutos.")
        if not senha_definida(self.caminho_senha):
            raise AcessoNegado("Nenhuma senha foi definida para a área restrita.")
        if not conferir_senha(self.caminho_senha, senha or ""):
            with self._trava:
                self._falhas.append(agora)
            raise AcessoNegado("Senha incorreta.")
        token = secrets.token_urlsafe(32)
        expira = agora + self.duracao
        with self._trava:
            self._sessoes = {t: e for t, e in self._sessoes.items() if e > agora}
            self._sessoes[token] = expira
        return token, expira

    def valida(self, token: str | None) -> float | None:
        """Devolve o horário de expiração da sessão, ou None."""
        if not token:
            return None
        with self._trava:
            expira = self._sessoes.get(token)
            if expira and expira > time.time():
                return expira
            self._sessoes.pop(token, None)
        return None

    def encerrar(self, token: str | None) -> None:
        with self._trava:
            self._sessoes.pop(token or "", None)
