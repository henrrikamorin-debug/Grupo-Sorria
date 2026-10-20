"""Regras ILUSTRATIVAS usadas apenas no modo demonstração.

Elas existem para exercitar o motor de regras e o layout do painel. Não foram
aprovadas pelo financeiro e não são usadas no modo real. As regras reais serão
escritas em ``aprovadas.py`` a partir das gravações e áudios.
"""

from __future__ import annotations

from datetime import date
from statistics import median

from ..conectores.base import Lancamento
from .base import Achado, ItemEvidencia, Regra, formatar_data, formatar_reais


def _itens_basicos(l: Lancamento) -> list[ItemEvidencia]:
    return [
        ItemEvidencia("Referência", l.referencia),
        ItemEvidencia("Clínica", l.clinica),
        ItemEvidencia("Categoria", l.categoria),
        ItemEvidencia("Data", formatar_data(l.data)),
        ItemEvidencia("Valor", formatar_reais(l.valor_centavos)),
        ItemEvidencia("Favorecido", l.favorecido or "não informado", sensivel=l.pessoa_fisica),
        ItemEvidencia("CPF/CNPJ", l.documento or "não informado", sensivel=True),
    ]


def _duplicidade(lancamentos: list[Lancamento], _ref: dict) -> list[Achado]:
    grupos: dict[tuple, list[Lancamento]] = {}
    for l in lancamentos:
        if l.valor_centavos is None:
            continue
        grupos.setdefault((l.extras.get("codigo_favorecido"), l.valor_centavos), []).append(l)
    achados = []
    for grupo in grupos.values():
        if len(grupo) < 2:
            continue
        grupo.sort(key=lambda l: (l.data, l.referencia))
        for anterior, atual in zip(grupo, grupo[1:]):
            distancia = (date.fromisoformat(atual.data) - date.fromisoformat(anterior.data)).days
            if distancia <= 3:
                achados.append(Achado(
                    referencia=atual.referencia,
                    descricao=f"Mesmo favorecido e valor de {anterior.referencia}, "
                              + ("no mesmo dia" if distancia == 0 else f"{distancia} dia(s) depois"),
                    resumo_evidencia="Dois lançamentos com favorecido e valor idênticos em até 3 dias.",
                    itens=_itens_basicos(atual) + [
                        ItemEvidencia("Lançamento semelhante", anterior.referencia),
                        ItemEvidencia("Data do semelhante", formatar_data(anterior.data)),
                        ItemEvidencia("Valor do semelhante", formatar_reais(anterior.valor_centavos)),
                        ItemEvidencia("Diferença de dias", str(distancia)),
                    ],
                    relacionados=[anterior.referencia],
                ))
    return achados


def _centro_custo(lancamentos: list[Lancamento], _ref: dict) -> list[Achado]:
    return [
        Achado(
            referencia=l.referencia,
            descricao="Lançamento sem centro de custo",
            resumo_evidencia="O campo centro de custo está vazio.",
            itens=_itens_basicos(l) + [ItemEvidencia("Centro de custo", "vazio")],
        )
        for l in lancamentos if not l.extras.get("centro_custo")
    ]


def _valor_atipico(lancamentos: list[Lancamento], _ref: dict) -> list[Achado]:
    valores: dict[str, list[int]] = {}
    for l in lancamentos:
        if l.valor_centavos is not None:
            valores.setdefault(l.categoria, []).append(l.valor_centavos)
    medianas = {c: median(v) for c, v in valores.items() if len(v) >= 8}
    achados = []
    for l in lancamentos:
        mediana = medianas.get(l.categoria)
        if mediana and l.valor_centavos is not None and l.valor_centavos > 4 * mediana:
            achados.append(Achado(
                referencia=l.referencia,
                descricao=f"Valor {l.valor_centavos / mediana:.1f}× a mediana da categoria",
                resumo_evidencia="Valor acima de 4 vezes a mediana da categoria no período coletado.",
                itens=_itens_basicos(l) + [
                    ItemEvidencia("Mediana da categoria", formatar_reais(int(mediana))),
                    ItemEvidencia("Limite usado", "4 × mediana"),
                ],
            ))
    return achados


def _vencimento(lancamentos: list[Lancamento], _ref: dict) -> list[Achado]:
    achados = []
    for l in lancamentos:
        emissao, vencimento = l.extras.get("emissao"), l.extras.get("vencimento")
        if emissao and vencimento and vencimento < emissao:
            achados.append(Achado(
                referencia=l.referencia,
                descricao="Vencimento anterior à data de emissão",
                resumo_evidencia="A data de vencimento é anterior à de emissão.",
                itens=_itens_basicos(l) + [
                    ItemEvidencia("Emissão", formatar_data(emissao)),
                    ItemEvidencia("Vencimento", formatar_data(vencimento)),
                ],
            ))
    return achados


def _dados_bancarios(lancamentos: list[Lancamento], ref: dict) -> list[Achado]:
    cadastro = ref.get("cadastro_favorecidos", {})
    achados = []
    for l in lancamentos:
        registro = cadastro.get(l.extras.get("codigo_favorecido"))
        if registro and l.dados_bancarios and l.dados_bancarios != registro["dados_bancarios"]:
            achados.append(Achado(
                referencia=l.referencia,
                descricao="Conta de pagamento diferente da cadastrada",
                resumo_evidencia="Os dados bancários do lançamento não conferem com o cadastro do favorecido.",
                itens=_itens_basicos(l) + [
                    ItemEvidencia("Conta no lançamento", l.dados_bancarios, sensivel=True),
                    ItemEvidencia("Conta no cadastro", registro["dados_bancarios"], sensivel=True),
                ],
            ))
    return achados


def _nota_fiscal(lancamentos: list[Lancamento], _ref: dict) -> list[Achado]:
    return [
        Achado(
            referencia=l.referencia,
            descricao="Nota fiscal não informada",
            resumo_evidencia="Categoria exige nota fiscal e o número está vazio.",
            itens=_itens_basicos(l) + [ItemEvidencia("Número da NF", "vazio")],
        )
        for l in lancamentos if l.extras.get("exige_nf") and not l.extras.get("numero_nf")
    ]


def _valor_ausente(lancamentos: list[Lancamento], _ref: dict) -> list[Achado]:
    return [
        Achado(
            referencia=l.referencia,
            descricao="Lançamento sem valor informado",
            resumo_evidencia="O campo valor veio vazio da origem.",
            itens=_itens_basicos(l),
        )
        for l in lancamentos if l.valor_centavos is None
    ]


AVISO = "Exemplo ilustrativo para demonstração — não é regra aprovada."

REGRAS_DEMONSTRACAO = [
    Regra("DEMO-01", "Possível duplicidade (exemplo)",
          "Mesmo favorecido e mesmo valor em até 3 dias.",
          ["favorecido", "valor", "data"], AVISO,
          "Dois pagamentos de R$ 1.200,00 ao mesmo laboratório em 02/10 e 03/10.",
          _duplicidade, ilustrativa=True),
    Regra("DEMO-02", "Centro de custo ausente (exemplo)",
          "Campo centro de custo vazio.", ["centro_custo"], AVISO,
          "Lançamento de marketing sem centro de custo.", _centro_custo, ilustrativa=True),
    Regra("DEMO-03", "Valor atípico (exemplo)",
          "Valor acima de 4× a mediana da categoria.", ["categoria", "valor"], AVISO,
          "Material odontológico de R$ 18.000,00 quando a mediana é R$ 2.500,00.",
          _valor_atipico, ilustrativa=True),
    Regra("DEMO-04", "Datas inconsistentes (exemplo)",
          "Vencimento anterior à emissão.", ["emissao", "vencimento"], AVISO,
          "Emitido em 10/09 com vencimento em 01/09.", _vencimento, ilustrativa=True),
    Regra("DEMO-05", "Conta bancária divergente (exemplo)",
          "Conta do lançamento diferente da conta cadastrada do favorecido.",
          ["favorecido", "dados_bancarios", "cadastro"], AVISO,
          "Pagamento a fornecedor para conta não cadastrada.", _dados_bancarios, ilustrativa=True),
    Regra("DEMO-06", "Nota fiscal ausente (exemplo)",
          "Categoria exige NF e o número está vazio.", ["categoria", "numero_nf"], AVISO,
          "Compra de material sem número de NF.", _nota_fiscal, ilustrativa=True),
    Regra("DEMO-07", "Valor não informado (exemplo)",
          "Campo valor vazio.", ["valor"], AVISO,
          "Lançamento importado sem valor.", _valor_ausente, ilustrativa=True),
]
