"""Ponto de integração com o TOTVS — ainda não implementado.

O produto TOTVS utilizado (Protheus, RM, Datasul, outro), a forma de acesso e
as opções disponíveis (API REST oficial, relatório exportado, banco de leitura,
automação de interface) ainda serão levantados a partir das gravações e áudios.
Nenhum endpoint foi presumido aqui.

Para implementar, crie uma subclasse de ``Conector`` que:

1. leia credenciais apenas de variáveis de ambiente (nunca de config.json);
2. faça somente leitura — o sistema não altera lançamentos no TOTVS;
3. converta cada registro em ``Lancamento`` (valores em centavos, datas ISO);
4. lance exceção em qualquer falha, para que a última coleta válida seja
   preservada e a falha fique registrada.

Depois, registre a classe em ``sorria/conectores/__init__.py`` e defina
``totvs.conector`` no config.json.
"""

from __future__ import annotations

from datetime import date

from .base import Conector, ConectorNaoConfigurado, ResultadoColeta


class ConectorTotvsPendente(Conector):
    nome = "totvs (não configurado)"
    simulado = False

    def coletar(self, inicio: date, fim: date) -> ResultadoColeta:
        raise ConectorNaoConfigurado(
            "Integração TOTVS ainda não configurada. Defina o produto, a forma de "
            "acesso e implemente o conector (ver docs/INTEGRACAO_TOTVS.md)."
        )

    def descricao(self) -> dict:
        return {"nome": self.nome, "simulado": False, "configurado": False}
