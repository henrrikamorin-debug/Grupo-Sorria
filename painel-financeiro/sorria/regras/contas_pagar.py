"""Verificações objetivas de Contas a Pagar (SE2) — EM VALIDAÇÃO.

Comparam apenas campos que a exportação trouxe; nenhuma conclusão depende de
suposição. Ficam marcadas como "em validação" (não aprovadas) até o
financeiro conferir os resultados com exemplos reais (docs/REGRAS.md).
Podem ser desligadas em ``agente.verificacoes_se2``.
"""

from __future__ import annotations

from ..conectores.base import Lancamento
from ..totvs.contratos import NAO_DISPONIBILIZADO, contrato_do_titulo, divergencias
from .base import Achado, ItemEvidencia, Regra, formatar_data, formatar_reais

AVISO = "Verificação objetiva em validação; ainda não aprovada pelo financeiro."


def _itens(l: Lancamento, contratos: list) -> list[ItemEvidencia]:
    e = l.extras
    contrato = contrato_do_titulo(contratos, e.get("fornecedor", ""), e.get("loja", ""), l.data) if contratos else None
    return [
        ItemEvidencia("Filial", f"{l.clinica} ({l.filial})"),
        ItemEvidencia("Prefixo / Nº / Parcela / Tipo",
                      f"{l.prefixo or '—'} / {l.titulo} / {e.get('parcela') or '—'} / {e.get('tipo') or '—'}"),
        ItemEvidencia("Natureza", e.get("natureza") or "vazia"),
        ItemEvidencia("Fornecedor / Loja", f"{e.get('fornecedor')} / {e.get('loja') or '—'}"),
        ItemEvidencia("Nome do fornecedor", l.favorecido or "vazio", sensivel=True),
        ItemEvidencia("Emissão", formatar_data(e.get("emissao"))),
        ItemEvidencia("Vencimento", formatar_data(e.get("vencimento"))),
        ItemEvidencia("Vencimento real", formatar_data(e.get("vencimento_real"))),
        ItemEvidencia("Valor do título", formatar_reais(l.valor_centavos)),
        ItemEvidencia("Saldo", formatar_reais(e["saldo_centavos"]) if e.get("saldo_centavos") is not None
                      else "não exportado"),
        ItemEvidencia("Baixa", formatar_data(e.get("baixa")) if e.get("baixa") else "sem data de baixa"),
        ItemEvidencia("Situação do título", e.get("situacao_titulo") or "não determinada"),
        ItemEvidencia("Contrato", f"{contrato['documento']}" if contrato else NAO_DISPONIBILIZADO),
        ItemEvidencia("Origem", f"importação nº {e.get('importacao')} — {e.get('arquivo') or 'arquivo'}"),
    ]


def _vencido(lancamentos, ref):
    return [Achado(l.referencia, f"Vencido em {formatar_data(l.extras.get('vencimento_real') or l.data)} "
                                 f"com saldo {formatar_reais(l.extras.get('saldo_centavos'))}",
                   "Saldo maior que zero e vencimento real anterior a hoje.", _itens(l, ref.get("contratos", [])))
            for l in lancamentos if l.extras.get("situacao_titulo") == "vencido"]


def _duplicidade(lancamentos, ref):
    grupos: dict[tuple, list[Lancamento]] = {}
    for l in lancamentos:
        e = l.extras
        if "fornecedor" in e:
            grupos.setdefault((l.filial, e["fornecedor"], e.get("loja"), l.valor_centavos, l.data), []).append(l)
    achados = []
    for grupo in grupos.values():
        if len(grupo) > 1:
            grupo.sort(key=lambda l: l.referencia)
            for l in grupo[1:]:
                achados.append(Achado(
                    l.referencia, f"Mesmo fornecedor, valor e vencimento do título {grupo[0].titulo}",
                    "Títulos distintos com mesmo fornecedor/loja, valor e vencimento na mesma filial.",
                    _itens(l, ref.get("contratos", [])) + [ItemEvidencia("Título semelhante", grupo[0].titulo)],
                    relacionados=[grupo[0].titulo]))
    return achados


ESSENCIAIS = {"natureza": "natureza", "nome_fornecedor": "nome do fornecedor", "emissao": "emissão",
              "vencimento_real": "vencimento real"}


def _campos(lancamentos, ref):
    achados = []
    for l in lancamentos:
        vazios = [ESSENCIAIS[c] for c in l.extras.get("campos_vazios", []) if c in ESSENCIAIS]
        if vazios:
            achados.append(Achado(l.referencia, "Campos vazios: " + ", ".join(vazios),
                                  "Campos essenciais vieram vazios na exportação.", _itens(l, ref.get("contratos", []))))
    return achados


def _sem_cadastro(lancamentos, ref):
    return [Achado(l.referencia, f"Filial {l.filial} não está no cadastro de filiais",
                   "Título pendente de classificação; fica restrito até a filial ser cadastrada.",
                   _itens(l, ref.get("contratos", [])))
            for l in lancamentos if "filial_cadastrada" in l.extras and not l.extras["filial_cadastrada"]]


def _contrato(lancamentos, ref):
    contratos = ref.get("contratos", [])
    achados = []
    for l in lancamentos:
        e = l.extras
        contrato = contrato_do_titulo(contratos, e.get("fornecedor", ""), e.get("loja", ""), l.data) if contratos else None
        if not contrato:
            continue
        for conclusao, campo, trecho in divergencias(contrato, l.valor_centavos or 0, l.data):
            achados.append(Achado(
                l.referencia, conclusao, f"Conferência com {contrato['documento']} ({campo}).",
                _itens(l, contratos) + [ItemEvidencia("Documento", contrato["documento"]),
                                        ItemEvidencia(f"Trecho ({campo})", trecho)]))
    return achados


REGRAS_SE2 = [
    Regra("SE2-01", "Título vencido em aberto", "Saldo > 0 e vencimento real anterior a hoje.",
          ["saldo", "vencimento_real"], "Só avaliada quando a exportação traz o saldo.", "", _vencido),
    Regra("SE2-02", "Possível duplicidade", "Mesma filial, fornecedor/loja, valor e vencimento em títulos distintos.",
          ["filial", "fornecedor", "loja", "valor", "vencimento"], AVISO, "", _duplicidade),
    Regra("SE2-03", "Campos essenciais vazios", "Natureza, nome do fornecedor, emissão ou vencimento real vazios.",
          ["natureza", "nome_fornecedor", "emissao", "vencimento_real"], AVISO, "", _campos),
    Regra("SE2-04", "Filial sem cadastro", "Código de filial ausente da planilha de filiais.",
          ["filial"], "O título fica restrito e pendente de classificação.", "", _sem_cadastro),
    Regra("SE2-05", "Divergência contratual", "Vigência, valor ou dia de vencimento diferente do contrato cadastrado.",
          ["fornecedor", "loja", "valor", "vencimento"], "Só com contrato cadastrado; sem ele: " + NAO_DISPONIBILIZADO,
          "", _contrato),
]
