# Integração TOTVS — pendente

Nenhum endpoint, tabela ou tela do TOTVS foi presumido. O conector atual
(`sorria/conectores/totvs.py`) apenas informa “não configurado”, e o modo real
mostra isso no painel.

## O que precisa ser levantado (a partir das gravações e áudios)

1. **Produto e versão**: Protheus, RM, Datasul, Backoffice Linha Protheus em
   nuvem (TOTVS Cloud) ou outro; versão/release.
2. **Forma de acesso** usada hoje: aplicativo instalado (SmartClient),
   navegador (WebApp/TOTVS Web), acesso remoto, VPN.
3. **Opções de extração disponíveis**, em ordem de preferência:
   - API REST oficial habilitada no ambiente (o cliente/TI precisa confirmar
     quais serviços estão publicados e emitir um usuário técnico);
   - relatório ou consulta exportável (CSV/XLSX) que possa ser gerado de forma
     agendada ou salvo em pasta;
   - acesso somente leitura ao banco de dados (normalmente restrito pelo
     contrato/TI; exige autorização formal);
   - automação de interface (último recurso: frágil e sensível a mudanças de
     tela).
4. **Telas, filtros e períodos** usados na conferência; clínicas (filiais/
   empresas) e como cada uma é identificada.
5. **Campos** necessários para cada regra (ver `docs/REGRAS.md`).
6. Volume aproximado de lançamentos por mês e por clínica.

## Requisitos para qualquer conector

- **Somente leitura.** O sistema não cria, altera nem estorna lançamentos.
- Credenciais apenas em variáveis de ambiente do computador do serviço;
  nunca em `config.json`, no repositório ou no chat.
- Converter para `Lancamento` (valores em centavos, datas `AAAA-MM-DD`,
  referência única por lançamento).
- Lançar exceção em qualquer falha (rede, autenticação, dado incompleto): o
  serviço registra a falha e preserva a última coleta válida.
- Respeitar `coleta.tempo_maximo_minutos`.

## Validação antes de ativar `modo: real`

1. Rodar `python -m sorria coletar` com o conector e comparar a quantidade e
   a soma dos lançamentos com o próprio TOTVS para o mesmo período/clínica.
2. Para cada regra aprovada, comparar as ocorrências com uma conferência
   manual já feita (casos positivos e negativos).
3. Só então definir `"modo": "real"` e reiniciar o serviço.
