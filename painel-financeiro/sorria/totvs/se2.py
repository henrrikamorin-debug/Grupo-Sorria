"""Leitura do arquivo exportado do TOTVS: Consulta Genérica › SE2 (Contas a Pagar) › Exp. CSV.

O formato exato do Exp. CSV depende da versão e da configuração do ambiente,
por isso as colunas são reconhecidas por nome técnico (E2_FILIAL, E2_NUM…)
ou pelo título exibido (Filial, No. Titulo…). Nada é presumido:

* códigos (filial, prefixo, número, parcela, tipo, fornecedor, loja,
  natureza) ficam como TEXTO, preservando zeros à esquerda;
* datas e valores no padrão brasileiro; valores em ``Decimal`` e gravados em
  centavos inteiros;
* vencimento e vencimento real são campos distintos;
* o valor do título NÃO é tratado como saldo em aberto; a situação (pago,
  aberto, vencido, parcialmente pago) só é calculada quando as colunas de
  saldo/baixa existem no arquivo;
* linhas inválidas são rejeitadas com o motivo (sem copiar o conteúdo da
  linha, que pode ser sensível).
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

# campo -> (nome técnico Protheus, títulos aceitos já normalizados)
COLUNAS = {
    "filial": ("E2_FILIAL", {"FILIAL", "FIL", "COD FILIAL", "CODIGO FILIAL"}),
    "prefixo": ("E2_PREFIXO", {"PREFIXO", "PREF"}),
    "numero": ("E2_NUM", {"NO TITULO", "NUM TITULO", "NUMERO TITULO", "N TITULO", "NUMERO", "TITULO", "NUM"}),
    "parcela": ("E2_PARCELA", {"PARCELA", "PARC"}),
    "tipo": ("E2_TIPO", {"TIPO", "TIPO TITULO"}),
    "natureza": ("E2_NATUREZ", {"NATUREZA", "NATUREZ", "COD NATUREZA"}),
    "fornecedor": ("E2_FORNECE", {"FORNECEDOR", "FORNECE", "COD FORNECEDOR", "CODIGO FORNECEDOR"}),
    "loja": ("E2_LOJA", {"LOJA", "LOJA FORNECEDOR"}),
    "nome_fornecedor": ("E2_NOMFOR", {"NOME FORNECE", "NOME FORNECEDOR", "NOME FORN", "NOME FOR", "RAZAO SOCIAL"}),
    "emissao": ("E2_EMISSAO", {"EMISSAO", "DT EMISSAO", "DATA EMISSAO", "DT EMIS"}),
    "vencimento": ("E2_VENCTO", {"VENCIMENTO", "VENCTO", "DT VENCIMENTO", "DATA VENCIMENTO"}),
    "vencimento_real": ("E2_VENCREA", {"VENCTO REAL", "VENCIMENTO REAL", "VENC REAL", "VENCTO REA", "DT VENC REAL"}),
    "valor": ("E2_VALOR", {"VLR TITULO", "VALOR TITULO", "VALOR", "VLR TIT", "VLR"}),
    "saldo": ("E2_SALDO", {"SALDO", "SALDO TITULO", "VLR SALDO"}),
    "baixa": ("E2_BAIXA", {"DT BAIXA", "DATA BAIXA", "BAIXA"}),
    "historico": ("E2_HIST", {"HISTORICO", "HIST"}),
}
OBRIGATORIAS = ("filial", "numero", "fornecedor", "vencimento", "valor")
CHAVE = ("filial", "prefixo", "numero", "parcela", "tipo", "fornecedor", "loja")
CODIGOS = ("filial", "prefixo", "numero", "parcela", "tipo", "natureza", "fornecedor", "loja")
DATAS = ("emissao", "vencimento", "vencimento_real", "baixa")


class ArquivoInvalido(ValueError):
    """O arquivo não é uma exportação SE2 utilizável (motivo na mensagem)."""


@dataclass
class TituloSE2:
    filial: str
    prefixo: str
    numero: str
    parcela: str
    tipo: str
    natureza: str
    fornecedor: str
    loja: str
    nome_fornecedor: str
    emissao: str | None
    vencimento: str
    vencimento_real: str | None
    valor_centavos: int
    saldo_centavos: int | None
    baixa: str | None
    historico: str
    linha: int
    campos_vazios: list[str] = field(default_factory=list)

    def chave(self, colunas_chave: tuple[str, ...]) -> str:
        return "|".join(getattr(self, c) for c in colunas_chave)


@dataclass
class LeituraSE2:
    titulos: list[TituloSE2]
    rejeitadas: list[tuple[int, str]]
    colunas: dict[str, str]          # campo -> cabeçalho encontrado
    colunas_ausentes: list[str]
    colunas_chave: tuple[str, ...]
    avisos: list[str]
    linhas_lidas: int
    codificacao: str
    delimitador: str


# ---------------------------------------------------------------- utilidades
def _normalizar_cabecalho(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto or "")
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn").upper()
    return re.sub(r"[^A-Z0-9_]+", " ", texto).strip()


def identificar_coluna(cabecalho: str) -> str | None:
    tecnico = re.search(r"\bE2_[A-Z0-9]+\b", (cabecalho or "").upper())
    if tecnico:
        for campo, (nome, _) in COLUNAS.items():
            if tecnico.group(0) == nome:
                return campo
        return None
    normalizado = _normalizar_cabecalho(cabecalho)
    for campo, (_, titulos) in COLUNAS.items():
        if normalizado in titulos:
            return campo
    return None


def converter_data(texto: str | None) -> date | None:
    """dd/mm/aaaa, dd/mm/aa, aaaammdd ou aaaa-mm-dd. Vazio (ou '  /  /  ') = None."""
    bruto = (texto or "").strip()
    if not bruto or re.fullmatch(r"[\s/.-]*", bruto):
        return None
    try:
        if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})", bruto):
            dia, mes, ano = int(m[1]), int(m[2]), int(m[3])
            return date(ano + 2000 if ano < 100 else ano, mes, dia)
        if re.fullmatch(r"\d{8}", bruto):
            return date(int(bruto[:4]), int(bruto[4:6]), int(bruto[6:]))
        if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?:[ T].*)?", bruto):
            return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError as erro:
        raise ValueError(f"data inexistente: {bruto}") from erro
    raise ValueError(f"data em formato não reconhecido: {bruto}")


def converter_valor(texto: str | None) -> Decimal | None:
    """'1.234,56', '1234,56', '-1.234,56', '(1.234,56)', 'R$ 1.234,56' ou '1234.56'."""
    bruto = (texto or "").replace("\xa0", " ").replace("R$", "").strip()
    if not bruto:
        return None
    negativo = bruto.startswith("(") and bruto.endswith(")")
    bruto = bruto.strip("()").replace(" ", "")
    if "," in bruto:
        bruto = bruto.replace(".", "").replace(",", ".")
    elif bruto.count(".") > 1 or re.fullmatch(r"-?\d{1,3}(\.\d{3})+", bruto):
        bruto = bruto.replace(".", "")  # só separadores de milhar
    try:
        valor = Decimal(bruto)
    except InvalidOperation as erro:
        raise ValueError(f"valor não numérico: {texto}") from erro
    return -valor if negativo else valor


def para_centavos(valor: Decimal) -> int:
    centavos = (valor * 100).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
    return int(centavos)


def _decodificar(conteudo: bytes) -> tuple[str, str]:
    for codificacao in ("utf-8-sig", "cp1252"):
        try:
            return conteudo.decode(codificacao), codificacao
        except UnicodeDecodeError:
            continue
    raise ArquivoInvalido("Não foi possível decodificar o arquivo (nem UTF-8 nem Windows-1252).")


# ---------------------------------------------------------------- leitura
def ler_exportacao(conteudo: bytes, tamanho_filial: int = 6) -> LeituraSE2:
    texto, codificacao = _decodificar(conteudo)
    linhas_texto = texto.splitlines()
    if not linhas_texto:
        raise ArquivoInvalido("Arquivo vazio.")

    # Cabeçalho: a primeira linha (entre as 15 primeiras) com colunas SE2 reconhecidas.
    escolhido = None
    for indice, linha in enumerate(linhas_texto[:15]):
        for delimitador in (";", "\t", ","):
            celulas = next(csv.reader([linha], delimiter=delimitador))
            campos = [identificar_coluna(c) for c in celulas]
            reconhecidas = {c for c in campos if c}
            if len(reconhecidas) >= 4 and (escolhido is None or len(reconhecidas) > escolhido[3]):
                escolhido = (indice, delimitador, campos, len(reconhecidas), celulas)
        if escolhido and escolhido[0] == indice:
            break
    if not escolhido:
        raise ArquivoInvalido("Cabeçalho de Contas a Pagar (SE2) não encontrado nas primeiras linhas.")
    inicio, delimitador, campos, _, cabecalhos = escolhido

    colunas: dict[str, int] = {}
    avisos: list[str] = []
    for posicao, campo in enumerate(campos):
        if campo and campo in colunas:
            avisos.append(f"Coluna '{cabecalhos[posicao].strip()}' repetida; usada a primeira ocorrência.")
        elif campo:
            colunas[campo] = posicao
    faltando = [c for c in OBRIGATORIAS if c not in colunas]
    if faltando:
        raise ArquivoInvalido("Colunas obrigatórias ausentes: " + ", ".join(faltando)
                              + ". Confira o layout da Consulta Genérica antes de exportar.")
    ausentes = [c for c in COLUNAS if c not in colunas]
    colunas_chave = tuple(c for c in CHAVE if c in colunas)

    titulos: list[TituloSE2] = []
    rejeitadas: list[tuple[int, str]] = []
    filiais_corrigidas = 0
    leitor = csv.reader(io.StringIO("\n".join(linhas_texto[inicio + 1:])), delimiter=delimitador)
    lidas = 0
    for deslocamento, celulas in enumerate(leitor, start=inicio + 2):
        if not any(c.strip() for c in celulas):
            continue
        primeira = celulas[0].strip().upper() if celulas else ""
        if primeira.startswith("TOTAL"):
            avisos.append(f"Linha {deslocamento}: linha de total ignorada.")
            continue
        lidas += 1

        def valor_de(campo):
            posicao = colunas.get(campo)
            return celulas[posicao].strip() if posicao is not None and posicao < len(celulas) else ""

        try:
            dados = {c: valor_de(c) for c in CODIGOS + ("nome_fornecedor", "historico")}
            for campo in ("filial", "numero", "fornecedor"):
                if not dados[campo]:
                    raise ValueError(f"{campo} vazio")
            if dados["filial"].isdigit() and len(dados["filial"]) < tamanho_filial:
                dados["filial"] = dados["filial"].zfill(tamanho_filial)
                filiais_corrigidas += 1
            datas = {}
            for campo in DATAS:
                try:
                    convertido = converter_data(valor_de(campo))
                except ValueError as erro:
                    if campo == "vencimento":
                        raise
                    raise ValueError(f"{campo}: {erro}") from erro
                datas[campo] = convertido.isoformat() if convertido else None
            if not datas["vencimento"]:
                raise ValueError("vencimento vazio")
            valor = converter_valor(valor_de("valor"))
            if valor is None:
                raise ValueError("valor do título vazio")
            saldo = converter_valor(valor_de("saldo")) if "saldo" in colunas else None
        except ValueError as erro:
            rejeitadas.append((deslocamento, str(erro)))
            continue

        vazios = [c for c in ("prefixo", "parcela", "tipo", "natureza", "loja", "nome_fornecedor")
                  if c in colunas and not dados[c]]
        vazios += [c for c in ("emissao", "vencimento_real") if c in colunas and not datas[c]]
        titulos.append(TituloSE2(
            filial=dados["filial"], prefixo=dados["prefixo"], numero=dados["numero"], parcela=dados["parcela"],
            tipo=dados["tipo"], natureza=dados["natureza"], fornecedor=dados["fornecedor"], loja=dados["loja"],
            nome_fornecedor=dados["nome_fornecedor"], emissao=datas["emissao"], vencimento=datas["vencimento"],
            vencimento_real=datas["vencimento_real"], valor_centavos=para_centavos(valor),
            saldo_centavos=para_centavos(saldo) if saldo is not None else None, baixa=datas["baixa"],
            historico=dados["historico"], linha=deslocamento, campos_vazios=vazios,
        ))
    if filiais_corrigidas:
        avisos.append(f"{filiais_corrigidas} código(s) de filial sem zeros à esquerda foram completados "
                      f"para {tamanho_filial} dígitos (provável conversão do Excel).")
    return LeituraSE2(
        titulos=titulos, rejeitadas=rejeitadas,
        colunas={c: cabecalhos[p].strip() for c, p in colunas.items()}, colunas_ausentes=ausentes,
        colunas_chave=colunas_chave, avisos=avisos, linhas_lidas=lidas,
        codificacao=codificacao, delimitador=delimitador,
    )


# ---------------------------------------------------------------- situação do título
def situacao_titulo(titulo: TituloSE2, hoje: date, tem_saldo: bool, tem_baixa: bool) -> str:
    """Só afirma o que as colunas sustentam.

    Com saldo: pago (saldo 0), parcialmente pago, vencido ou aberto (pelo
    vencimento real; na falta dele, pelo vencimento). Sem saldo: "baixa
    registrada (saldo não informado)" quando há data de baixa; senão "não
    determinada".
    """
    if tem_saldo and titulo.saldo_centavos is not None:
        if titulo.saldo_centavos <= 0:
            return "pago"
        if titulo.saldo_centavos < titulo.valor_centavos:
            return "parcialmente pago"
        referencia = titulo.vencimento_real or titulo.vencimento
        return "vencido" if referencia < hoje.isoformat() else "aberto"
    if tem_baixa and titulo.baixa:
        return "baixa registrada (saldo não informado)"
    return "não determinada"
