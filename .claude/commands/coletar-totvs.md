---
description: Coletar Contas a Pagar (SE2) do mês atual no TOTVS WebApp e atualizar o painel financeiro
---

A coleta é feita pelo próprio agente do painel, que opera o TOTVS WebApp no
Chrome dedicado (Consulta Genérica › SE2 › Vencimento = Mês Atual › Exp. CSV),
captura o download, valida, importa e confere o painel. Seu papel aqui é
iniciar, acompanhar e relatar. Trabalhe na pasta `painel-financeiro`.

## Regras que não podem ser quebradas

- No TOTVS, apenas CONSULTA e EXPORTAÇÃO. Não clique em nada na janela do
  TOTVS; não altere `navegador.textos` para incluir ações de manutenção.
- Nunca digite, copie ou registre senhas. Se a execução pedir login, peça para
  a pessoa entrar na janela do Chrome do agente.
- Não copie conteúdo do relatório, das capturas de diagnóstico
  (`dados/totvs/diagnostico`) ou do banco para o chat ou logs.
- Não contorne validações (lote rejeitado, importação "não completa").

## Passos

1. `py -3 -m sorria agente verificar` — relate o que estiver com `!!`.
2. Se o Chrome do agente estiver fechado: `py -3 -m sorria agente abrir-navegador`
   e peça para a pessoa entrar no TOTVS nessa janela.
3. `py -3 -m sorria agente executar --origem claude_code` (em segundo plano).
   Se a etapa ficar em `aguardando_login`, avise a pessoa; a execução continua
   sozinha depois do login.
4. Ao terminar, `py -3 -m sorria agente historico` (primeira linha) e relate:
   situação, etapa (se falhou), se a importação é completa, pendências e se o
   painel foi confirmado. Em falha, informe a pasta de diagnóstico registrada,
   sem abrir nem copiar o conteúdo para o chat.
