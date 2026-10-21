"""Classificação dos títulos que pertencem à área restrita (escritório).

Regras explícitas, em ordem (a primeira que se aplica decide):

1. filial listada em ``acesso_restrito.filiais`` (validada contra o cadastro);
2. natureza listada em ``acesso_restrito.naturezas``;
3. prefixo listado em ``acesso_restrito.prefixos``;
4. filial ausente do cadastro de filiais: a classificação é incerta, então o
   título fica restrito e pendente de classificação
   (``acesso_restrito.restringir_sem_cadastro``, ligado por padrão).

Nenhuma regra usa o nome do fornecedor ou o histórico (por exemplo, a palavra
"escritório"), porque texto livre não identifica a filial de forma confiável.
"""

from __future__ import annotations

from .se2 import TituloSE2


def regras_restricao(config: dict) -> dict:
    regras = config["acesso_restrito"]
    return {
        "filiais": {str(f) for f in regras.get("filiais", [])},
        "naturezas": {str(n).strip().upper() for n in regras.get("naturezas", [])},
        "prefixos": {str(p).strip().upper() for p in regras.get("prefixos", [])},
        "sem_cadastro": bool(regras.get("restringir_sem_cadastro", True)),
    }


def classificar(titulo: TituloSE2, cadastro: dict, regras: dict) -> tuple[bool, str]:
    if titulo.filial in regras["filiais"]:
        return True, "filial restrita (escritório)"
    if titulo.natureza and titulo.natureza.strip().upper() in regras["naturezas"]:
        return True, "natureza restrita"
    if titulo.prefixo and titulo.prefixo.strip().upper() in regras["prefixos"]:
        return True, "prefixo restrito"
    if titulo.filial not in cadastro and regras["sem_cadastro"]:
        return True, "filial sem cadastro: classificação incerta (pendente)"
    return False, ""


def validar_regras(cadastro: dict, regras: dict) -> list[str]:
    """Confere se as filiais restritas configuradas existem no cadastro."""
    avisos = []
    if not cadastro:
        avisos.append("Cadastro de filiais não importado: todos os títulos ficam restritos e pendentes "
                      "de classificação até rodar 'python -m sorria importar-filiais'.")
    for codigo in sorted(regras["filiais"]):
        if cadastro and codigo not in cadastro:
            avisos.append(f"Filial restrita {codigo} não existe no cadastro de filiais; confira o código.")
    return avisos
