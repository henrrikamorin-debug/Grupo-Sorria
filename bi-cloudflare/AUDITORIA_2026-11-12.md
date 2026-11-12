# Auditoria — BI Contas a Pagar (12/11/2026)

Feita pela API do Cloudflare (token da conta, só leitura e `SELECT`), pelas URLs públicas dos Workers e pelo
retrato publicado. Nada foi publicado, alterado ou apagado na conta, no KV, no D1 ou no TOTVS.

## Situação geral

| Item | Situação |
|---|---|
| Worker `painel-financeiro-sorria` (público) | No ar, HTTP 200, 0 erros registrados em 24 h, cabeçalhos de segurança corretos |
| Worker `painel-financeiro-sorria-privado` | Bloqueado de propósito: Cloudflare Access não configurado (`ACCESS_TEAM_DOMAIN`/`ACCESS_AUD` ausentes) e KV vazio |
| Banco do BI | KV `DADOS` (3 chaves: `snapshot`, `retrato_gz`, `meta`). O BI **não usa D1** |
| Execuções agendadas | Nenhum cron no Cloudflare; o agendamento roda no computador do escritório e publica no KV |
| Coleta TOTVS | **Parada**: última coleta válida 10/11/2026 18:26 UTC (26 h sem importação na hora da auditoria) |
| Indicadores | Funcionando; batem com o retrato (9.343 lançamentos, 911 ocorrências) |

## Erros e causas

1. **Coleta do TOTVS sem sucesso desde 10/11 18:26 UTC.** Últimas execuções: falha na etapa `filtro`
   (`Locator.evaluate: Timeout 30000ms`) e `aguardando_login` (sessão do TOTVS não autenticada). Causa: a tela de
   filtro mudou para a janela "Criar Filtro" (Vencimento · operador · data) e o agente procura outra tela; quando a
   sessão cai, ninguém entra de novo. O painel mostra corretamente "Dados desatualizados". Correção: no código do
   computador do escritório (não está neste repositório).
2. **Nexera: última exportação com erro** em 11/11 17:17 (BRT): "a pesquisa não devolveu a quantidade filtrada";
   cobertura marcada como incompleta.
3. **Saúde enganosa:** `/api/saude` respondia sempre `ok: true`, mesmo com a coleta parada. Corrigido nesta branch.
4. **Erros engolidos:** o Worker devolvia 500 sem registrar nada no log, então "0 erros" não era garantia.
   Corrigido nesta branch.

## Integridade e duplicidades (retrato publicado)

- 0 referências de título duplicadas, 0 ocorrências com id duplicado.
- 0 valores negativos ou vazios, 0 saldos maiores que o valor.
- 0 lançamentos sem ticket ou sem clínica.
- **2 títulos com vencimento no ano 2202** (NOVO GAMA, 25/03/2202; FORMOSA, 29/11/2202): provável erro de
  digitação no TOTVS. Recomenda-se corrigir na origem; não foi alterado aqui.

## Segurança e exposição

- O painel público é aberto na internet (workers.dev, sem login), por decisão anterior. Serve o retrato completo
  (`/api/retrato`) e o CSV de ocorrências: clínica, ticket, nº do título, valores, datas e códigos de fornecedor.
- **Não há** CPF, CNPJ, dados bancários, código de barras, filial do escritório (031801) ou ocorrência restrita no
  retrato público. O nome do fornecedor já sai mascarado ("oculto no modo TV").
- Escrita bloqueada no público (POST → 403); sincronização exige token (sem token → 401; comparação em tempo
  constante); retrato restrito é recusado na sincronização.
- Recomendação: colocar o painel público atrás do Cloudflare Access (o código do Worker privado já suporta), já
  que valores por clínica ficam abertos a quem tiver o endereço.

## Outro sistema na mesma conta: Central de Faturas (`central-faturas`, D1)

Fora do BI, mas é o único Worker com D1. Em 24 h: 30 erros.

- "Worker exceeded CPU time limit" em `/api/login` e na leitura de arquivos. Causa: conta no plano gratuito
  (10 ms de CPU por requisição) e login com PBKDF2 de 100 mil iterações.
- Erros do D1 em `/api/envios` (gravação das partes dos arquivos) e nas rotas do agente, num mesmo instante.
- Banco íntegro: 20 tabelas, 0 partes de arquivo órfãs, 1 arquivo repetido (mesmo SHA-256), 11 tentativas de login
  sem sucesso no dia (normal).
- Recomendação: Workers Paid (limite de CPU maior), em vez de reduzir a segurança do hash.

## Correção preparada (sem deploy)

- `src/worker.js`: `/api/saude` passa a informar `ok: false` com o motivo quando não há coleta válida há mais de
  26 h ou o painel local marcou os dados como desatualizados; o meta da sincronização guarda a última coleta
  válida; erros 500 passam a ser registrados no Workers Logs (método, caminho e pilha, sem dados).
- `tests/worker.test.mjs`: 6 testes (`npm test`), todos passando; falham no código de produção.
- Regressão: com o retrato real, os indicadores e gráficos do painel e do BI saem idênticos aos da produção.

Para publicar: levar `src/worker.js` ao projeto do escritório (`painel-financeiro/cloudflare/src/worker.js`),
rodar os testes de lá e `wrangler deploy`. A melhoria de saúde só aparece depois da próxima sincronização.
