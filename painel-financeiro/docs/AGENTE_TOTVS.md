# Agente operacional TOTVS — Contas a Pagar (SE2)

Coleta o relatório de Contas a Pagar do TOTVS (Protheus WebApp, módulo
SIGAFIN), valida, importa e atualiza o painel. No TOTVS, o agente só faz
**consulta e exportação**: nunca inclui, altera, baixa, paga ou estorna.

## Fluxo

1. **Exportação no TOTVS** (Consulta Genérica › SE2 — Contas a Pagar ›
   filtro Vencimento = Mês Atual › Exp. CSV). Feita pelo Claude Code no
   computador do financeiro, usando a extensão Claude in Chrome, conforme
   `/.claude/commands/coletar-totvs.md`, ou por uma pessoa.
2. **Agente** (`python -m sorria agente executar`): registra o início, aguarda
   na pasta de entrada um CSV **gerado depois do início**, com tamanho estável,
   e importa.
3. **Validação do lote** (qualquer falha rejeita o lote inteiro e o painel
   continua com a última versão válida):
   - cabeçalho de Contas a Pagar (origem);
   - arquivo novo: o mesmo conteúdo já importado é ignorado; arquivo anterior
     ao início da execução é recusado;
   - período: todos os títulos com **Vencimento** no mês atual;
   - linhas inválidas dentro do limite (padrão 5%), registradas com o motivo;
   - mais de uma filial (uma só costuma indicar filtro de filial ativo);
   - mesma composição de chave das importações anteriores; sem chave repetida.
4. **Gravação** em `titulos_pagar` pela chave
   `filial|prefixo|número|parcela|tipo|fornecedor|loja`. Reimportar atualiza;
   títulos que não vieram na exportação **não** são apagados (a conferência
   mostra quantos ficaram fora da última exportação).
5. **Atualização do painel**: regras, indicadores e situação são recalculados
   a partir dos títulos importados. A tela "Situação da integração" mostra o
   período consultado, a última coleta válida, a origem, o arquivo, as
   pendências e divergências, e a conferência de totais com o arquivo.

## Normalização

- Colunas reconhecidas pelo nome técnico (`E2_FILIAL`, `E2_NUM`…) ou pelo
  título exibido (Filial, No. Titulo, Vencto Real, Vlr.Titulo…).
- Códigos como texto, com zeros à esquerda. Filial com menos de 6 dígitos (por
  conversão do Excel) é completada e registrada como aviso.
- Datas `dd/mm/aaaa`, `dd/mm/aa`, `aaaammdd` ou ISO. Valores brasileiros
  (`1.234,56`, `(10,00)`) com `Decimal`, gravados em centavos.
- **Vencimento** e **vencimento real** são campos separados; o período usa o
  vencimento, que é o campo do filtro.
- Situação do título só quando sustentada: com coluna **Saldo**, pago,
  parcialmente pago, vencido ou aberto; sem saldo, "baixa registrada (saldo
  não informado)" ou "não determinada". O valor do título nunca é tratado
  como saldo.

## Verificações (em validação)

`SE2-01` título vencido em aberto · `SE2-02` possível duplicidade ·
`SE2-03` campos essenciais vazios · `SE2-04` filial sem cadastro ·
`SE2-05` divergência contratual. São objetivas, mas ficam marcadas como **não
aprovadas** até o financeiro conferir com casos reais. Para desligá-las, use
`agente.verificacoes_se2: false`.

**Contratos:** só são comparados os contratos cadastrados em
`dados/contratos/contratos.json`, com documento e trecho de cada condição
(modelo em `sorria/totvs/contratos.py`). Sem contrato, o título mostra
"Contrato não disponibilizado". Nenhuma condição é deduzida dos lançamentos.

## Área restrita (escritório)

- **Regras de classificação, explícitas:** filial em `acesso_restrito.filiais`
  (031801), naturezas e prefixos listados (vazios até serem informados) e
  **filial fora do cadastro**. Na dúvida, o título fica restrito e pendente.
  O nome do fornecedor e o histórico não são usados.
- **Conta proprietária:** criada com `python -m sorria definir-proprietario`
  (usuário e senha; só o hash é gravado). Sem ela, ninguém acessa.
- **Aplicação no servidor**, pela marca `restrito`, em todo lugar:
  indicadores, gráficos, tabela, opções de filtro, CSV, relatório mensal,
  contexto do agente de IA, situação e histórico. Sem autorização, os totais
  da situação não contam os restritos, e uma ocorrência restrita responde
  como inexistente. O modo TV e o acesso de outras máquinas nunca mostram a
  área restrita.
- Logs e histórico guardam só contagens e nomes de arquivo, nunca o conteúdo
  das linhas. Os arquivos ficam em `dados/totvs/` (fora do repositório).

## Comandos

| Ação | Comando (Windows: `py -3` no lugar de `python3`) |
|---|---|
| Conferir pré-requisitos | `python3 -m sorria agente verificar` |
| Executar (aguarda a exportação) | `python3 -m sorria agente executar --origem manual` |
| Importar um arquivo já exportado | `python3 -m sorria agente importar caminho\\arquivo.csv` |
| Histórico de execuções | `python3 -m sorria agente historico` |
| Agendamento (Windows) | `python3 -m sorria agente agendamento` |
| Pelo Claude Code | `/coletar-totvs` |

Saída: 0 sucesso · 2 falha ou lote rejeitado · 3 nenhuma exportação nova ·
4 outra execução em andamento · 5 pré-requisito ausente.

## Persistência, travas e retomada

- Tabelas `execucoes_agente` (início, término, etapa, tentativas, resultado),
  `importacoes` (arquivo, hash, período, contagens, avisos) e
  `importacao_rejeicoes` (linha e motivo).
- Trava no banco com validade (`agente.tempo_maximo_execucao_minutos`): duas
  execuções nunca rodam juntas, mesmo vindas de processos diferentes.
- Tentativas limitadas (`agente.tentativas`) para falhas temporárias, como
  arquivo ainda em uso pelo navegador ou banco ocupado.
- Execução interrompida vira "interrompida". Se ela já tinha recebido o
  arquivo, a próxima retoma a partir dele (revalidando tudo).

## Agendamento — preparado, NÃO ativado

`agente.agendamento = {"ativo": false, "horarios": []}`. Com os horários
definidos e `ativo: true`, `agente agendamento` mostra os comandos `schtasks`
(execução só com o usuário conectado, `/IT`).

**Condições para rodar sem ninguém presente:** computador ligado e sem
suspensão; sessão do Windows aberta e desbloqueada; Chrome aberto com a
extensão Claude ativa; sessão do TOTVS WebApp autenticada. O agendador só
inicia o agente: a exportação na tela do TOTVS depende do Claude Code com a
extensão (ou de uma pessoa). Sem a exportação, a execução termina como
"sem exportação nova" e o painel avisa.

## Limitações conhecidas

- O layout exato do Exp. CSV do ambiente ainda não foi visto. O leitor aceita
  nomes técnicos e títulos usuais, mas precisa ser validado com o primeiro
  arquivo real (ver "Validação com dados reais").
- A operação da tela do TOTVS não foi executada daqui: o ambiente de
  desenvolvimento não alcança o computador do financeiro.

## Validação com dados reais (antes de confiar no painel)

1. Exportar o SE2 do mês e rodar `agente importar`.
2. Comparar a quantidade e o valor total da conferência com a soma feita
   no próprio TOTVS ou no Excel.
3. Conferir à mão cinco ocorrências de cada verificação.
4. Só então ativar o modo real na TV e definir os horários.
