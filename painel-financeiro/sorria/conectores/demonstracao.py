"""Conector de DEMONSTRAÇÃO — gera dados 100% fictícios.

Nada aqui vem do TOTVS. Clínicas, fornecedores, profissionais, documentos e
contas bancárias são inventados. As anomalias inseridas existem apenas para
ilustrar o layout do painel e não correspondem a regras aprovadas.

A geração é determinística (semente fixa) e ancorada na data de hoje, para que
o painel sempre tenha um período recente para exibir.
"""

from __future__ import annotations

import hashlib
import random
from datetime import date, timedelta

from .base import Conector, Lancamento, ResultadoColeta

SEMENTE = 20261020

CLINICAS = [
    "Unidade Centro", "Unidade Norte", "Unidade Sul",
    "Unidade Leste", "Unidade Oeste", "Unidade Parque",
]

# categoria -> (faixa de valor em reais, exige nota fiscal, peso de frequência)
CATEGORIAS = {
    "Materiais odontológicos": ((350, 4800), True, 6),
    "Laboratório de prótese": ((600, 7500), True, 5),
    "Repasse a profissionais": ((1800, 14000), False, 4),
    "Manutenção de equipamentos": ((250, 6200), True, 2),
    "Marketing": ((400, 5200), True, 2),
    "Energia e água": ((700, 3900), False, 2),
    "Aluguel e condomínio": ((6000, 18000), False, 1),
    "Serviços de limpeza": ((900, 3200), True, 1),
}

FORNECEDORES = {
    "Materiais odontológicos": ["Dental Exemplo Ltda", "OdontoSuprimentos Fictícia S.A."],
    "Laboratório de prótese": ["Laboratório Modelo Ltda", "ProtéticaDemo Ltda"],
    "Manutenção de equipamentos": ["TecManutenção Exemplo ME"],
    "Marketing": ["Agência Fictícia Comunicação"],
    "Energia e água": ["Concessionária Exemplo"],
    "Aluguel e condomínio": ["Imobiliária Demonstração"],
    "Serviços de limpeza": ["LimpaBem Fictícia Ltda"],
}

PROFISSIONAIS = [
    "Dra. Profissional Exemplo A", "Dr. Profissional Exemplo B",
    "Dra. Profissional Exemplo C", "Dr. Profissional Exemplo D",
    "Dra. Profissional Exemplo E",
]


def _cnpj_ficticio(i: int) -> str:
    return f"00.{100 + i:03d}.{200 + i:03d}/0001-{(i * 7) % 100:02d}"


def _cpf_ficticio(i: int) -> str:
    return f"000.{100 + i:03d}.{300 + i:03d}-{(i * 11) % 100:02d}"


def _conta_ficticia(i: int, variante: int = 0) -> str:
    return f"Banco 999 · Ag. {1000 + i:04d} · CC {20000 + i * 37 + variante * 911:05d}-{(i + variante) % 10}"


def _cadastro() -> dict:
    """Cadastro fictício de favorecidos: documento e conta 'oficial'."""
    cadastro = {}
    indice = 1
    for categoria, nomes in FORNECEDORES.items():
        for nome in nomes:
            cadastro[f"F{indice:03d}"] = {
                "nome": nome, "pessoa_fisica": False, "categoria": categoria,
                "documento": _cnpj_ficticio(indice), "dados_bancarios": _conta_ficticia(indice),
            }
            indice += 1
    for nome in PROFISSIONAIS:
        cadastro[f"P{indice:03d}"] = {
            "nome": nome, "pessoa_fisica": True, "categoria": "Repasse a profissionais",
            "documento": _cpf_ficticio(indice), "dados_bancarios": _conta_ficticia(indice),
        }
        indice += 1
    return cadastro


def gerar(hoje: date, dias: int = 120) -> ResultadoColeta:
    aleatorio = random.Random(SEMENTE)
    cadastro = _cadastro()
    por_categoria: dict[str, list[str]] = {}
    for codigo, dados in cadastro.items():
        por_categoria.setdefault(dados["categoria"], []).append(codigo)

    nomes_categorias = list(CATEGORIAS)
    pesos = [CATEGORIAS[c][2] for c in nomes_categorias]
    lancamentos: list[Lancamento] = []
    sequencia = 0

    def novo(dia: date, clinica: str, categoria: str, codigo: str) -> Lancamento:
        nonlocal sequencia
        sequencia += 1
        favorecido = cadastro[codigo]
        (minimo, maximo), exige_nf, _ = CATEGORIAS[categoria]
        valor = aleatorio.randint(minimo * 100, maximo * 100)
        emissao = dia - timedelta(days=aleatorio.randint(0, 6))
        vencimento = emissao + timedelta(days=aleatorio.choice([10, 15, 20, 28, 30]))
        return Lancamento(
            referencia=f"DEMO-{dia:%y%m}-{sequencia:05d}",
            clinica=clinica,
            categoria=categoria,
            data=dia.isoformat(),
            valor_centavos=valor,
            descricao=f"{categoria} — {favorecido['nome']}" if not favorecido["pessoa_fisica"]
            else f"{categoria} — repasse de produção",
            favorecido=favorecido["nome"],
            pessoa_fisica=favorecido["pessoa_fisica"],
            documento=favorecido["documento"],
            dados_bancarios=favorecido["dados_bancarios"],
            extras={
                "codigo_favorecido": codigo,
                "centro_custo": f"CC-{CLINICAS.index(clinica) + 1:02d}",
                "numero_nf": f"{aleatorio.randint(1000, 99999)}" if exige_nf else "",
                "exige_nf": exige_nf,
                "emissao": emissao.isoformat(),
                "vencimento": vencimento.isoformat(),
                "origem": "gerador de demonstração",
            },
        )

    inicio = hoje - timedelta(days=dias - 1)
    for deslocamento in range(dias):
        dia = inicio + timedelta(days=deslocamento)
        if dia.weekday() == 6:  # domingo sem lançamentos
            continue
        for clinica in CLINICAS:
            for _ in range(aleatorio.choice([0, 1, 1, 1, 2, 2])):
                categoria = aleatorio.choices(nomes_categorias, pesos)[0]
                codigo = aleatorio.choice(por_categoria[categoria])
                lancamentos.append(novo(dia, clinica, categoria, codigo))

    # Anomalias ilustrativas (somente para demonstrar o layout).
    extras_duplicados = []
    for lanc in lancamentos:
        sorteio = aleatorio.random()
        if sorteio < 0.018:
            copia = Lancamento(**{**lanc.__dict__, "extras": dict(lanc.extras)})
            sequencia += 1
            dia = date.fromisoformat(lanc.data) + timedelta(days=aleatorio.randint(0, 2))
            if dia > hoje:
                dia = hoje
            copia.referencia = f"DEMO-{dia:%y%m}-{sequencia:05d}"
            copia.data = dia.isoformat()
            if aleatorio.random() < 0.4 and copia.extras["exige_nf"]:
                copia.extras["numero_nf"] = ""  # duplicidade + NF ausente
            extras_duplicados.append(copia)
        elif sorteio < 0.035 and lanc.extras["exige_nf"]:
            lanc.extras["numero_nf"] = ""
        elif sorteio < 0.047:
            lanc.extras["centro_custo"] = ""
        elif sorteio < 0.057:
            lanc.valor_centavos = (lanc.valor_centavos or 0) * aleatorio.randint(5, 8)
            if aleatorio.random() < 0.3:
                lanc.dados_bancarios = _conta_ficticia(3, variante=7)
        elif sorteio < 0.066:
            emissao = date.fromisoformat(lanc.extras["emissao"])
            lanc.extras["vencimento"] = (emissao - timedelta(days=aleatorio.randint(3, 20))).isoformat()
        elif sorteio < 0.074:
            lanc.dados_bancarios = _conta_ficticia(5, variante=3)
        elif sorteio < 0.079:
            lanc.valor_centavos = None
    lancamentos.extend(extras_duplicados)
    lancamentos.sort(key=lambda l: (l.data, l.referencia))

    return ResultadoColeta(
        lancamentos=lancamentos,
        simulada=True,
        referencias={"cadastro_favorecidos": cadastro},
        observacao="Dados fictícios gerados localmente para demonstração.",
    )


class ConectorDemonstracao(Conector):
    nome = "demonstração (dados fictícios)"
    simulado = True

    def __init__(self, hoje: date | None = None):
        self._hoje = hoje

    def coletar(self, inicio: date, fim: date) -> ResultadoColeta:
        hoje = self._hoje or date.today()
        resultado = gerar(hoje, dias=max(1, (fim - inicio).days + 1))
        resultado.lancamentos = [
            l for l in resultado.lancamentos if inicio.isoformat() <= l.data <= fim.isoformat()
        ]
        return resultado

    @staticmethod
    def situacao_inicial(id_ocorrencia: str, data_ocorrencia: str, hoje: date | None = None) -> str:
        """Distribui situações fictícias para ilustrar o acompanhamento."""
        hoje = hoje or date.today()
        sorteio = int(hashlib.sha1(id_ocorrencia.encode()).hexdigest()[:6], 16) % 100
        idade = (hoje - date.fromisoformat(data_ocorrencia)).days
        if idade > 30:
            return "resolvida" if sorteio < 65 else "em_analise" if sorteio < 80 else "pendente"
        return "pendente" if sorteio < 65 else "em_analise" if sorteio < 88 else "resolvida"
