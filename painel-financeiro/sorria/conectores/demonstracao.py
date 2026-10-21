"""Conector de DEMONSTRAÇÃO — gera dados 100% fictícios.

Nada aqui vem do TOTVS. Unidades, fornecedores, profissionais, colaboradores,
documentos, contas bancárias, números de título e prefixos são inventados. As
anomalias inseridas existem apenas para ilustrar o layout do painel e não
correspondem a regras aprovadas.

Como um conector real deve fazer, este conector informa apenas o código da
filial e o prefixo do título; o nome da filial e a categoria são resolvidos
na consolidação (cadastro de filiais e tabela de prefixos). Títulos sem
prefixo caem em "Diversos".

A geração é determinística (semente fixa) e ancorada na data de hoje, para que
o painel sempre tenha um período recente para exibir.
"""

from __future__ import annotations

import hashlib
import random
from datetime import date, timedelta

from .base import Conector, Lancamento, ResultadoColeta

SEMENTE = 20261020

# Códigos fictícios; o escritório usa o código configurado como área restrita.
FILIAIS = {
    "900101": "Unidade Centro", "900201": "Unidade Norte", "900301": "Unidade Sul",
    "900401": "Unidade Leste", "900501": "Unidade Oeste", "900601": "Unidade Parque",
}
ESCRITORIO = ("031801", "Escritório (demonstração)")
# Quem cuida de cada unidade (nomes fictícios).
RESPONSAVEIS = {
    "900101": "Responsável Exemplo Ana", "900201": "Responsável Exemplo Ana",
    "900301": "Responsável Exemplo Bruno", "900401": "Responsável Exemplo Bruno",
    "900501": "Responsável Exemplo Carla", "900601": "Responsável Exemplo Carla",
    ESCRITORIO[0]: "Responsável Exemplo Diretoria",
}

# prefixo -> (categoria, faixa de valor em reais, exige nota fiscal, peso de frequência)
PREFIXOS = {
    "MAT": ("Materiais odontológicos", (350, 4800), True, 6),
    "LAB": ("Laboratório de prótese", (600, 7500), True, 5),
    "RPA": ("Repasse a profissionais", (1800, 14000), False, 4),
    "MAN": ("Manutenção de equipamentos", (250, 6200), True, 2),
    "MKT": ("Marketing", (400, 5200), True, 2),
    "CON": ("Energia e água", (700, 3900), False, 2),
    "ALU": ("Aluguel e condomínio", (6000, 18000), False, 1),
    "LIM": ("Serviços de limpeza", (900, 3200), True, 1),
    "": ("Diversos", (80, 2600), False, 1),  # título sem prefixo no TOTVS
}
PREFIXOS_ESCRITORIO = {
    "FOL": ("Folha de pagamento", (2200, 9800), False),
    "PJ": ("Prestadores PJ", (3500, 16000), True),
}

FORNECEDORES = {
    "MAT": ["Dental Exemplo Ltda", "OdontoSuprimentos Fictícia S.A."],
    "LAB": ["Laboratório Modelo Ltda", "ProtéticaDemo Ltda"],
    "MAN": ["TecManutenção Exemplo ME"],
    "MKT": ["Agência Fictícia Comunicação"],
    "CON": ["Concessionária Exemplo"],
    "ALU": ["Imobiliária Demonstração"],
    "LIM": ["LimpaBem Fictícia Ltda"],
    "": ["Papelaria Exemplo ME", "Cartório Fictício"],
}
PROFISSIONAIS = [f"{t} Profissional Exemplo {l}" for t, l in
                 [("Dra.", "A"), ("Dr.", "B"), ("Dra.", "C"), ("Dr.", "D"), ("Dra.", "E")]]
COLABORADORES = [f"Colaborador(a) Exemplo {n:02d}" for n in range(1, 9)]
PRESTADORES_PJ = [f"Prestador PJ Exemplo {l}" for l in "ABCD"]


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

    def incluir(prefixo: str, nome: str, pessoa_fisica: bool):
        nonlocal indice
        cadastro[f"F{indice:03d}"] = {
            "nome": nome, "pessoa_fisica": pessoa_fisica, "prefixo": prefixo,
            "documento": _cpf_ficticio(indice) if pessoa_fisica else _cnpj_ficticio(indice),
            "dados_bancarios": _conta_ficticia(indice),
        }
        indice += 1

    for prefixo, nomes in FORNECEDORES.items():
        for nome in nomes:
            incluir(prefixo, nome, False)
    for nome in PROFISSIONAIS:
        incluir("RPA", nome, True)
    for nome in COLABORADORES:
        incluir("FOL", nome, True)
    for nome in PRESTADORES_PJ:
        incluir("PJ", nome, False)
    return cadastro


def gerar(hoje: date, dias: int = 120) -> ResultadoColeta:
    aleatorio = random.Random(SEMENTE)
    cadastro = _cadastro()
    por_prefixo: dict[str, list[str]] = {}
    for codigo, dados in cadastro.items():
        por_prefixo.setdefault(dados["prefixo"], []).append(codigo)

    prefixos = list(PREFIXOS)
    pesos = [PREFIXOS[p][3] for p in prefixos]
    lancamentos: list[Lancamento] = []
    numero = 45000

    def novo(dia: date, filial: str, prefixo: str, codigo: str, faixa, exige_nf: bool,
             categoria: str, valor: int | None = None) -> Lancamento:
        nonlocal numero
        numero += 1
        favorecido = cadastro[codigo]
        parcela = aleatorio.choice(["", "", "", "", "", "", "1", "2"])
        titulo = f"{numero:09d}" + (f"/{parcela}" if parcela else "")
        emissao = dia - timedelta(days=aleatorio.randint(0, 6))
        vencimento = emissao + timedelta(days=aleatorio.choice([10, 15, 20, 28, 30]))
        return Lancamento(
            referencia=f"{filial}|{prefixo}|{numero:09d}|{parcela}",
            clinica="",      # resolvido pelo cadastro de filiais
            categoria="",    # resolvida pelo prefixo do título
            data=dia.isoformat(),
            valor_centavos=valor if valor is not None else aleatorio.randint(faixa[0] * 100, faixa[1] * 100),
            descricao=f"{categoria} — {favorecido['nome']}" if not favorecido["pessoa_fisica"]
            else f"{categoria} — pagamento a pessoa física",
            favorecido=favorecido["nome"],
            pessoa_fisica=favorecido["pessoa_fisica"],
            documento=favorecido["documento"],
            dados_bancarios=favorecido["dados_bancarios"],
            filial=filial,
            titulo=titulo,
            prefixo=prefixo,
            extras={
                "codigo_favorecido": codigo,
                "centro_custo": f"CC-{filial[2:4]}",
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
        for filial in FILIAIS:
            for _ in range(aleatorio.choice([0, 1, 1, 1, 2, 2])):
                prefixo = aleatorio.choices(prefixos, pesos)[0]
                categoria, faixa, exige_nf, _peso = PREFIXOS[prefixo]
                codigo = aleatorio.choice(por_prefixo[prefixo])
                lancamentos.append(novo(dia, filial, prefixo, codigo, faixa, exige_nf, categoria))
        # Escritório: folha no 5º dia útil aproximado e PJ no dia 10 de cada mês.
        if dia.day == 5:
            for codigo in por_prefixo["FOL"]:
                categoria, faixa, exige_nf = PREFIXOS_ESCRITORIO["FOL"]
                salario = 2200_00 + (int(codigo[1:]) * 61_317) % 760_000
                lancamentos.append(novo(dia, ESCRITORIO[0], "FOL", codigo, faixa, exige_nf, categoria, salario))
        if dia.day == 10:
            for codigo in por_prefixo["PJ"]:
                categoria, faixa, exige_nf = PREFIXOS_ESCRITORIO["PJ"]
                lancamentos.append(novo(dia, ESCRITORIO[0], "PJ", codigo, faixa, exige_nf, categoria))

    # Anomalias ilustrativas (somente para demonstrar o layout).
    copias = []
    for lanc in lancamentos:
        sorteio = aleatorio.random()
        if sorteio < 0.018:
            copia = Lancamento(**{**lanc.__dict__, "extras": dict(lanc.extras)})
            numero += 1
            dia = min(date.fromisoformat(lanc.data) + timedelta(days=aleatorio.randint(0, 2)), hoje)
            copia.referencia = f"{lanc.filial}|{lanc.prefixo}|{numero:09d}|"
            copia.titulo = f"{numero:09d}"
            copia.data = dia.isoformat()
            if aleatorio.random() < 0.4 and copia.extras["exige_nf"]:
                copia.extras["numero_nf"] = ""  # duplicidade + NF ausente
            copias.append(copia)
        elif sorteio < 0.035 and lanc.extras["exige_nf"]:
            lanc.extras["numero_nf"] = ""
        elif sorteio < 0.047:
            lanc.extras["centro_custo"] = ""
        elif sorteio < 0.057 and lanc.prefixo != "FOL":
            lanc.valor_centavos = (lanc.valor_centavos or 0) * aleatorio.randint(5, 8)
            if aleatorio.random() < 0.3:
                lanc.dados_bancarios = _conta_ficticia(3, variante=7)
        elif sorteio < 0.066:
            emissao = date.fromisoformat(lanc.extras["emissao"])
            lanc.extras["vencimento"] = (emissao - timedelta(days=aleatorio.randint(3, 20))).isoformat()
        elif sorteio < 0.074 or (lanc.prefixo == "FOL" and sorteio < 0.12):
            lanc.dados_bancarios = _conta_ficticia(5, variante=3)
        elif sorteio < 0.079:
            lanc.valor_centavos = None
    lancamentos.extend(copias)
    lancamentos.sort(key=lambda l: (l.data, l.referencia))

    filiais = {codigo: {"nome": nome, "responsavel": RESPONSAVEIS[codigo]} for codigo, nome in FILIAIS.items()}
    filiais[ESCRITORIO[0]] = {"nome": ESCRITORIO[1], "responsavel": RESPONSAVEIS[ESCRITORIO[0]]}
    categorias = {p: dados[0] for p, dados in PREFIXOS.items() if p}
    categorias.update({p: dados[0] for p, dados in PREFIXOS_ESCRITORIO.items()})
    return ResultadoColeta(
        lancamentos=lancamentos,
        simulada=True,
        referencias={"cadastro_favorecidos": cadastro, "filiais": filiais,
                     "categorias_por_prefixo": categorias},
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
