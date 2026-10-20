# Agente financeiro de IA — interface preparada, desativada

## Como está

- `agente_ia.habilitado = false`. Com isso, `/api/agente/contexto` e
  `/api/agente/perguntar` respondem 503 e **nenhuma chamada de IA é feita**.
- Coleta, filtros, cálculos e regras são código determinístico. A rotina de
  10 minutos nunca chama IA.

## Como funciona quando ativado (`sorria/agente.py`)

- Só chamado sob demanda (`POST /api/agente/perguntar` com `pergunta` e
  `filtros`).
- Envia contexto mínimo: indicadores, totais por clínica/categoria e até 40
  ocorrências resumidas, **sempre mascaradas** (sem CPF/CNPJ, nomes de pessoas
  físicas, contas ou evidências completas).
- Reaproveita a resposta quando a mesma pergunta é feita sobre os mesmos dados
  (tabela `cache_ia`).
- Registra tokens de entrada/saída informados pela API em `uso_ia`, e conta
  reaproveitamentos. `/api/agente/estado` mostra o consumo do dia.
- Limite diário de chamadas (`limite_chamadas_dia`, padrão 20).
- Modelo padrão `claude-opus-5-5`, com fallback do lado do servidor
  habilitado para o caso de recusa do modelo.

## O que ainda precisa ser configurado (não vem da assinatura do Claude Code)

A sessão ou assinatura do Claude Code **não** fornece uma API para este
sistema. Para ativar:

1. Conta na Claude Platform (console da Anthropic) com faturamento de API.
2. Criar uma chave de API e defini-la como variável de ambiente no computador
   do serviço — por exemplo, no Windows: Painel de Controle → Sistema →
   Variáveis de ambiente → `ANTHROPIC_API_KEY`. Não coloque a chave no
   `config.json`, no repositório nem em mensagens.
3. Instalar o SDK: `py -3 -m pip install anthropic`.
4. Em `config.json`: `"agente_ia": {"habilitado": true}` e reiniciar.
5. Conferir em `/api/agente/estado`: `variavel_definida: true`,
   `sdk_instalado: true`.

A implementação da chamada ainda não foi executada contra a API real (não há
chave neste ambiente); valide com uma pergunta simples após configurar.

## Integração com um agente externo

Um agente externo (por exemplo, um agente do Claude com ferramentas) pode
consumir `GET /api/agente/contexto?inicio=...&fim=...` para obter o mesmo
contexto mínimo, sem precisar acessar o banco. Esse endpoint também fica
desativado enquanto `habilitado = false`.
