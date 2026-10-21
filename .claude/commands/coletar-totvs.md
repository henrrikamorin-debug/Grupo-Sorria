---
description: Coletar Contas a Pagar (SE2) do mês atual no TOTVS WebApp e atualizar o painel financeiro
---

Você vai coletar o relatório de Contas a Pagar no TOTVS WebApp e alimentar o
painel financeiro do Grupo Sorria. Trabalhe na pasta `painel-financeiro`.

## Regras que não podem ser quebradas

- No TOTVS, apenas CONSULTA e EXPORTAÇÃO. Nunca incluir, alterar, excluir,
  baixar, aprovar, pagar ou estornar títulos. Não clique em botões de
  manutenção (Incluir, Alterar, Excluir, Baixar, Borderô etc.).
- O período é o MÊS ATUAL pelo campo Vencimento. A regra de "amanhã" é do
  Ecuro e não se aplica aqui.
- Nunca digite, copie ou registre senhas. Se o TOTVS pedir login, pare e peça
  para a pessoa entrar.
- Não copie conteúdo do relatório para o chat, logs ou arquivos fora de
  `painel-financeiro/dados/`.
- Antes de cada ação, confirme pela tela (leitura da página) que está no lugar
  esperado. Não dependa de coordenadas fixas nem de esperas cegas: aguarde o
  elemento ou a mensagem esperada aparecer. Se a tela não for a esperada, pare
  e relate o que viu.

## Passos

1. Rode `py -3 -m sorria agente verificar` e resolva o que estiver marcado com `!!`
   (exceto o que depende de decisão da pessoa; nesse caso, relate).
2. Inicie a execução em segundo plano, ANTES de exportar (ela registra o
   horário de início e só aceita arquivo gerado depois dele):
   `py -3 -m sorria agente executar --origem claude_code`
3. No Chrome, use a extensão Claude in Chrome. Abra o endereço configurado em
   `totvs.endereco_webapp` (config.json). Confirme na tela:
   - título "TOTVS Webapp" e módulo **SIGAFIN** (Financeiro);
   - ambiente **TOTVS Serviços MSSQL Producao**;
   - usuário logado (não registre o nome em lugar nenhum);
   - **filial ativa** mostrada no topo. Anote só o código/nome da filial para
     o passo 6.
4. Menu: **Consultas › Consulta Genérica** (pesquise "Consulta Genérica" no
   campo Pesquisar se não estiver visível). Aguarde a tela de seleção abrir.
5. Selecione a tabela **SE2 — Contas a Pagar**. Aguarde a grade carregar.
6. Filtros (verifique os JÁ ATIVOS antes de criar o novo):
   - remova filtros que não sejam o de vencimento;
   - **filial**: a consulta precisa trazer TODAS as filiais. Se só a filial
     logada aparecer (ex.: a coluna Filial mostra um único código), procure a
     opção de considerar todas as filiais/empresas; se não existir, PARE e
     relate (o agente rejeita arquivo de filial única);
   - crie o filtro: campo **Vencimento**, operador **Mês Atual**. Aplique e
     aguarde o resultado.
7. Confira o resultado: a grade tem registros, as datas de vencimento estão no
   mês atual e há mais de uma filial. Se a grade estiver vazia, pare e relate.
8. Clique em **Exp. CSV**. Aguarde o TOTVS terminar (barra/mensagem de
   processamento desaparece e o download é concluído no Chrome). Não clique de
   novo enquanto processa.
9. Localize o arquivo baixado (pasta de Downloads do Chrome): deve ser o `.csv`
   mais recente, com horário posterior ao passo 2. Copie-o para
   `painel-financeiro/dados/totvs/entrada/` (ou a pasta em
   `agente.pasta_entrada`). Não renomeie para nome de arquivo antigo.
10. Acompanhe a execução do passo 2 até terminar e informe o resultado:
    `py -3 -m sorria agente historico` (primeira linha). Relate: situação,
    período, títulos novos/atualizados, linhas rejeitadas e avisos. Se o lote
    for rejeitado, explique o motivo indicado e NÃO tente contornar a validação.

## Se algo bloquear

Sessão expirada, tela inesperada, erro do TOTVS, exportação que não termina,
arquivo não aparece: pare, não repita ações às cegas, e relate exatamente onde
parou. O painel continua com a última importação válida.
