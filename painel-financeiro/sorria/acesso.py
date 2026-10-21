"""Acesso exclusivo da conta proprietária à área restrita (escritório).

* A conta proprietária (usuário + senha) é definida no computador do serviço
  com ``python -m sorria definir-proprietario``. Só o hash PBKDF2 da senha e o
  identificador do usuário são gravados em ``dados/acesso.json``.
* Enquanto a conta proprietária não for definida, a área restrita fica
  bloqueada para todos. Um arquivo antigo (só senha, sem usuário) também não
  libera nada: a conta precisa ser identificada.
* Desbloquear exige usuário E senha da conta proprietária e cria uma sessão
  temporária (cookie HttpOnly) vinculada a esse usuário; só vale neste
  computador e nunca no modo TV.
* Tentativas erradas são limitadas para dificultar adivinhação.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
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


def normalizar_usuario(usuario: str) -> str:
    return (usuario or "").strip().lower()


def definir_proprietario(caminho: Path, usuario: str, senha: str) -> None:
    usuario = normalizar_usuario(usuario)
    if not re.fullmatch(r"[a-z0-9._@-]{3,64}", usuario):
        raise ValueError("Usuário inválido: use de 3 a 64 caracteres (letras, números, . _ @ -).")
    if len(senha) < TAMANHO_MINIMO:
        raise ValueError(f"A senha precisa ter pelo menos {TAMANHO_MINIMO} caracteres.")
    sal = secrets.token_bytes(16)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(json.dumps({
        "usuario": usuario, "algoritmo": "pbkdf2_sha256", "iteracoes": ITERACOES, "sal": sal.hex(),
        "hash": _hash(senha, sal, ITERACOES),
    }), encoding="utf-8")
    temporario.replace(caminho)


def proprietario(caminho: Path) -> str | None:
    """Usuário da conta proprietária, ou None se ainda não identificada."""
    if not caminho.exists():
        return None
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return dados.get("usuario") or None


def senha_definida(caminho: Path) -> bool:
    return proprietario(caminho) is not None


def conferir(caminho: Path, usuario: str, senha: str) -> bool:
    dono = proprietario(caminho)
    if not dono:
        return False
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    calculado = _hash(senha or "", bytes.fromhex(dados["sal"]), int(dados["iteracoes"]))
    usuario_ok = hmac.compare_digest(normalizar_usuario(usuario), dono)
    senha_ok = hmac.compare_digest(calculado, dados["hash"])
    return usuario_ok and senha_ok


class Sessoes:
    """Sessões de desbloqueio em memória (somem se o serviço reiniciar)."""

    def __init__(self, caminho_senha: Path, minutos: float):
        self.caminho_senha = caminho_senha
        self.duracao = minutos * 60
        self._sessoes: dict[str, tuple[float, str]] = {}
        self._falhas: list[float] = []
        self._trava = threading.Lock()

    def desbloquear(self, usuario: str, senha: str) -> tuple[str, float]:
        agora = time.time()
        with self._trava:
            self._falhas = [t for t in self._falhas if agora - t < JANELA_TENTATIVAS_S]
            if len(self._falhas) >= MAX_TENTATIVAS:
                raise MuitasTentativas("Muitas tentativas erradas. Aguarde alguns minutos.")
        if not senha_definida(self.caminho_senha):
            raise AcessoNegado("A conta proprietária ainda não foi definida; a área restrita está bloqueada.")
        if not conferir(self.caminho_senha, usuario, senha):
            with self._trava:
                self._falhas.append(agora)
            raise AcessoNegado("Usuário ou senha incorretos.")
        token = secrets.token_urlsafe(32)
        expira = agora + self.duracao
        with self._trava:
            self._sessoes = {t: v for t, v in self._sessoes.items() if v[0] > agora}
            self._sessoes[token] = (expira, normalizar_usuario(usuario))
        return token, expira

    def valida(self, token: str | None) -> float | None:
        """Horário de expiração da sessão, se válida e ainda do proprietário atual."""
        if not token:
            return None
        dono = proprietario(self.caminho_senha)
        with self._trava:
            sessao = self._sessoes.get(token)
            if sessao and sessao[0] > time.time() and dono and hmac.compare_digest(sessao[1], dono):
                return sessao[0]
            self._sessoes.pop(token, None)
        return None

    def encerrar(self, token: str | None) -> None:
        with self._trava:
            self._sessoes.pop(token or "", None)
