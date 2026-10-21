"""Cadastros auxiliares: filiais do TOTVS e categorias por prefixo do título.

Filiais
    Importadas da planilha de controle (``python -m sorria importar-filiais
    arquivo.xlsx``) para ``dados/filiais.json``. Esse arquivo fica fora do
    repositório. O conector só precisa informar o código da filial TOTVS
    (ex.: ``016501``); o nome exibido no painel vem do cadastro.

Categorias
    A categoria é definida pelo PREFIXO do título no TOTVS. Título sem prefixo
    vai para "Diversos". Prefixo sem categoria cadastrada aparece como
    "Prefixo XXX" até ser incluído em ``categorias.por_prefixo`` no config.json.
"""

from __future__ import annotations

import json
import re
import unicodedata
import zipfile
from pathlib import Path
from xml.etree import ElementTree

SEM_PREFIXO = "Diversos"
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


# ---------------------------------------------------------------- categorias
def normalizar_prefixo(prefixo: str | None) -> str:
    return (prefixo or "").strip().upper()


def classificar_categoria(prefixo: str | None, mapa: dict[str, str], sem_prefixo: str = SEM_PREFIXO) -> str:
    codigo = normalizar_prefixo(prefixo)
    if not codigo:
        return sem_prefixo
    mapa_normalizado = {normalizar_prefixo(k): v for k, v in mapa.items()}
    return mapa_normalizado.get(codigo, f"Prefixo {codigo}")


# ---------------------------------------------------------------- filiais
def responsavel_da_filial(codigo: str | None, cadastro: dict, config: dict) -> str:
    """Quem cuida da filial: config por filial > planilha > config por divisão."""
    regras = config.get("responsaveis", {})
    registro = cadastro.get(codigo or "", {})
    return (regras.get("por_filial", {}).get(codigo or "")
            or registro.get("responsavel")
            or regras.get("por_divisao", {}).get(registro.get("divisao", ""))
            or regras.get("sem_responsavel", "Sem responsável definido"))


def carregar_filiais(caminho: Path) -> dict[str, dict]:
    if not caminho.exists():
        return {}
    with open(caminho, encoding="utf-8") as arquivo:
        return json.load(arquivo)


def _texto(valor) -> str:
    texto = "" if valor is None else str(valor)
    return re.sub(r"\s+", " ", texto.replace("\xa0", " ")).strip()


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn").upper()


def _ler_xlsx(caminho: Path) -> list[list[str]]:
    """Lê a primeira aba de um .xlsx usando só a biblioteca padrão."""
    with zipfile.ZipFile(caminho) as pacote:
        compartilhadas = []
        if "xl/sharedStrings.xml" in pacote.namelist():
            raiz = ElementTree.fromstring(pacote.read("xl/sharedStrings.xml"))
            for item in raiz.findall("m:si", _NS):
                compartilhadas.append("".join(t.text or "" for t in item.iter(f"{{{_NS['m']}}}t")))
        livro = ElementTree.fromstring(pacote.read("xl/workbook.xml"))
        primeira = livro.find("m:sheets/m:sheet", _NS)
        rels = ElementTree.fromstring(pacote.read("xl/_rels/workbook.xml.rels"))
        alvo = next(r.get("Target") for r in rels if r.get("Id") == primeira.get(_REL))
        alvo = alvo.lstrip("/")
        planilha = ElementTree.fromstring(pacote.read(alvo if alvo.startswith("xl/") else f"xl/{alvo}"))
    linhas = []
    for linha in planilha.iter(f"{{{_NS['m']}}}row"):
        valores: dict[int, str] = {}
        for celula in linha.findall("m:c", _NS):
            coluna = 0
            for letra in re.match(r"[A-Z]+", celula.get("r")).group(0):
                coluna = coluna * 26 + ord(letra) - 64
            tipo = celula.get("t")
            if tipo == "inlineStr":
                valor = "".join(t.text or "" for t in celula.iter(f"{{{_NS['m']}}}t"))
            else:
                bruto = celula.find("m:v", _NS)
                valor = "" if bruto is None else bruto.text or ""
                if tipo == "s" and valor:
                    valor = compartilhadas[int(valor)]
            valores[coluna - 1] = valor
        if valores:
            linhas.append([valores.get(i, "") for i in range(max(valores) + 1)])
    return linhas


def importar_filiais_xlsx(caminho: Path) -> tuple[dict[str, dict], list[str]]:
    """Lê a planilha de controle de filiais. Devolve (cadastro, avisos).

    Colunas esperadas no cabeçalho: DIVISÃO, NOME FILIAL, FILIAL, FILIAL TOTVS,
    CNPJ, UF (nomes comparados sem acento e sem espaços extras).
    """
    linhas = _ler_xlsx(caminho)
    esperadas = {"DIVISAO": "divisao", "NOME FILIAL": "razao_social", "FILIAL": "nome",
                 "FILIAL TOTVS": "codigo", "CNPJ": "cnpj", "UF": "uf", "RESPONSAVEL": "responsavel"}
    cabecalho, inicio = None, 0
    for indice, linha in enumerate(linhas):
        nomes = [_sem_acento(_texto(c)) for c in linha]
        if "FILIAL TOTVS" in nomes:
            cabecalho = {i: esperadas[n] for i, n in enumerate(nomes) if n in esperadas}
            inicio = indice + 1
            break
    if not cabecalho:
        raise ValueError("Cabeçalho com a coluna 'FILIAL TOTVS' não encontrado na primeira aba.")

    cadastro: dict[str, dict] = {}
    avisos: list[str] = []
    for linha in linhas[inicio:]:
        registro = {campo: _texto(linha[i]) if i < len(linha) else "" for i, campo in cabecalho.items()}
        if not any(registro.values()):
            continue
        codigo = registro.get("codigo", "")
        nome = registro.get("nome", "")
        if not codigo:
            avisos.append(f"Filial '{nome or '?'}' sem código TOTVS: não importada.")
            continue
        if re.fullmatch(r"\d+(\.0)?", codigo):
            codigo = codigo.split(".")[0].zfill(6)  # Excel pode ter salvo como número
        cnpj = registro.get("cnpj", "")
        if cnpj and not re.fullmatch(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", cnpj):
            avisos.append(f"Filial {codigo} ({nome}): CNPJ fora do padrão: {cnpj}")
        if codigo in cadastro:
            avisos.append(f"Código TOTVS {codigo} repetido; mantida a primeira linha.")
            continue
        cadastro[codigo] = {"codigo": codigo, "nome": nome, "razao_social": registro.get("razao_social", ""),
                            "cnpj": cnpj, "uf": registro.get("uf", ""), "divisao": registro.get("divisao", "")}
        if registro.get("responsavel"):
            cadastro[codigo]["responsavel"] = registro["responsavel"]
    return cadastro, avisos


def salvar_filiais(cadastro: dict[str, dict], caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as arquivo:
        json.dump(cadastro, arquivo, ensure_ascii=False, indent=2, sort_keys=True)
