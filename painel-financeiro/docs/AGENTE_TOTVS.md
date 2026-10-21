# Agente operacional TOTVS — Contas a Pagar (SE2)

Coleta o relatório de Contas a Pagar do TOTVS (Protheus WebApp, módulo
SIGAFIN) operando a tela no Chrome, valida, importa e atualiza o painel. No
TOTVS, o agente só faz **consulta e exportação**: nunca inclui, altera, baixa,
paga ou estorna.

> **Situação desta versão:** o executor foi testado contra um **simulador
> local** das telas (`tests/simulador_totvs.py`), não contra o TOTVS real. O
> ambiente de desenvolvimento não alcança o computador do financeiro nem o
> TOTVS. A primeira execução real deve ser feita com `--diagnostico` (ver
> "Calibração").

## Fluxo de uma execução (`python -m sorria agente executar`)

1. **Trava e histórico**: registra a execução em `execucoes_agente`; duas
   execuções nunca rodam juntas.
2. **Chrome do agente** (`sorria/totvs/navegador.py`): conecta ao Chrome
   dedicado (perfil próprio em `dados/navegador/perfil`, porta de controle
   `navegador.porta_controle`, aberta só neste computador). Se estiver fechado,
   abre. Localiza a aba do `totvs.endereco_webapp` (ou abre).
3. **Sessão**: se o TOTVS não está autenticado, a execução fica em
   `aguardando_login` e o painel mostra **"Ação necessária: entrar no TOTVS"**.
   Uma pessoa entra na janela do Chrome do agente; o agente detecta o menu e
   continua sozinho. O agente nunca digita usuário ou senha. Sem login em
   `navegador.tempo_login_minutos`, termina como falha e o painel fica como
   estava.
4. **Roteiro na tela** (cada passo espera uma condição visível, sem
   coordenadas nem esperas fixas):
   - campo **Pesquisar** do menu → "Consulta Genérica" → abre a rotina;
   - tabela **SE2 — Contas a Pagar** → Confirmar → grade da consulta;
   - **gerenciador de filtros**: campo **Vencimento**, operador **Mês Atual**,
     Aplicar; o filtro precisa aparecer aplicado na tela;
   - conferência: outros filtros ativos (textos em
     `navegador.textos.outros_filtros`) param a coleta; abrangência de filiais
     confirmada pelo texto em `navegador.textos.filiais_todas`;
   - **Exp. CSV** (e a confirmação "Sim/OK", se aparecer).
5. **Captura**: o download é recebido pelo próprio Chrome numa **pasta nova da
   execução** (`dados/totvs/execucoes/<data>_<id>/`). Só vale o download que
   começou depois do clique em Exp. CSV e que o Chrome deu como concluído, com
   tamanho igual ao informado. Arquivos antigos (Downloads, pasta de entrada)
   nunca são usados.
6. **Validação e importação** (abaixo). Falha = lote rejeitado, painel mantém a
   última versão válida.
7. **Atualização do painel** e **confirmação**: o agente consulta
   `/api/situacao` do painel em execução e registra se ele já mostra a nova
   importação e o horário (`painel_confirmado`).

Tentativas: falhas temporárias numa etapa da tela (elemento que não apareceu a
tempo) repetem o roteiro até `agente.tentativas` vezes, voltando ao menu com
Esc. Login ausente, ação proibida e tempo máximo não são repetidos. Tempo
máximo da execução: `agente.tempo_maximo_execucao_minutos`.

## Proteção contra alterações no TOTVS

- O agente só clica em elementos cujo texto está em `navegador.textos`.
- Antes de cada clique, o texto do elemento é conferido contra uma lista de
  ações de alteração (incluir, alterar, excluir, baixar, pagar, estornar,
  borderô, liberar, aprovar, cancelar, gravar, salvar…). Se bater, a execução
  para sem clicar, mesmo que o texto tenha sido configurado por engano.
- Teclado: apenas digitação nos campos de pesquisa/tabela, Enter e Esc.

## Validação do lote

Rejeitam o lote inteiro (nada muda no painel):

- cabeçalho que não é de Contas a Pagar; colunas obrigatórias ausentes;
- arquivo anterior ao início da execução (ou já importado: ignorado);
- título com **Vencimento** fora do mês atual;
- proporção de linhas inválidas acima de `max_percentual_linhas_rejeitadas`;
- chave do título com composição diferente da última importação; chave
  repetida no próprio arquivo;
- **linha de total** do arquivo que não confere com a soma das linhas (quando
  existe e todas as linhas descartadas têm valor legível).

Importam, mas **não publicam como completa** (pendências):

- linhas descartadas sem reconciliação;
- total do arquivo não conferido (linha ilegível/ambígua ou linhas sem valor);
- filtro ou abrangência de filiais não confirmados na tela (importação manual
  nunca é completa);
- uma única filial no arquivo quando se esperam várias — não é rejeitado
  automaticamente; várias filiais também não bastam para considerar completo;
- filiais fora de `agente.filiais_esperadas` (quando a lista é informada).

Filiais esperadas sem títulos são registradas como informativas (pode ser
normal no mês). O painel mostra "Coleta TOTVS válida e completa" só sem
pendências; caso contrário, "não confirmada como completa" com os motivos.

Reimportar atualiza pela chave `filial|prefixo|número|parcela|tipo|fornecedor|loja`;
títulos ausentes do arquivo **não** são apagados (a conferência mostra quantos
ficaram fora da última exportação).

## Área restrita (escritório)

- Classificação explícita: filial em `acesso_restrito.filiais` (031801),
  naturezas e prefixos listados e **filial fora do cadastro** (incerta →
  restrita). Linhas descartadas também são classificadas pela filial,
  natureza e prefixo legíveis; sem filial legível, contam como restritas.
- Pendências, contagens de linhas descartadas, totais do arquivo e filiais
  ausentes que envolvem a área restrita só aparecem para a conta proprietária.
  Mensagens do histórico não têm contagens nem valores.
- As capturas de diagnóstico mostram a tela do TOTVS e podem conter dados
  confidenciais: ficam só em `dados/totvs/diagnostico` (fora do repositório) e
  são apagadas após `navegador.dias_diagnostico`.

## Instalação no computador do financeiro (Windows)

1. `scripts\instalar-navegador.bat` (instala o Playwright; usa o Google Chrome
   já instalado, não baixa outro navegador).
2. `config.json`: `"modo": "real"`; conferir `totvs.endereco_webapp`.
3. `scripts\abrir-totvs.bat`: abre o Chrome do agente; entre no TOTVS
   (ambiente e módulo Financeiro) e deixe a janela aberta. Use essa janela só
   para o TOTVS.
4. `python -m sorria agente verificar`.

## Calibração (primeira execução real)

Os textos e o comportamento exatos das telas do seu ambiente ainda não foram
vistos. Rode com a pessoa acompanhando:

```
py -3 -m sorria agente executar --diagnostico
```

Cada etapa grava a tela e o texto visível em `dados/totvs/diagnostico/`. Se uma
etapa falhar, a mensagem diz qual; ajuste o texto correspondente em
`navegador.textos` (ex.: o nome do botão que aplica o filtro) e rode de novo.
Depois de ver na tela como a consulta indica que abrange todas as filiais,
informe esse texto em `navegador.textos.filiais_todas`; até lá as importações
ficam "não confirmadas como completas".

## Agendamento — preparado, NÃO ativado

`agente.agendamento = {"ativo": false, "horarios": []}`. Com os horários
definidos e `ativo: true`, `agente agendamento` mostra os comandos `schtasks`
(`/IT`: só roda com o usuário conectado, necessário para o Chrome visível). O
agendador inicia a cadeia inteira: Chrome → TOTVS → exportação → captura →
validação → importação → painel.

**Condições:** computador ligado e sem suspensão; sessão do Windows aberta; o
Chrome do agente aberto com o TOTVS autenticado. **Não testado:** tela
bloqueada, sessão do TOTVS expirando entre execuções e o comportamento do
WebApp com a janela minimizada. Confirme no primeiro dia com execuções
acompanhadas.

## Comandos

| Ação | Comando (Windows: `py -3` no lugar de `python3`) |
|---|---|
| Conferir pré-requisitos | `python3 -m sorria agente verificar` |
| Abrir o Chrome do agente (login) | `python3 -m sorria agente abrir-navegador` |
| Coletar agora pelo navegador | `python3 -m sorria agente executar` |
| Coletar com capturas de cada etapa | `python3 -m sorria agente executar --diagnostico` |
| Aguardar CSV na pasta (sem navegador) | `python3 -m sorria agente executar --modo pasta` |
| Importar um arquivo já exportado | `python3 -m sorria agente importar caminho\\arquivo.csv` |
| Histórico de execuções | `python3 -m sorria agente historico` |
| Agendamento (Windows) | `python3 -m sorria agente agendamento` |

Saída: 0 sucesso · 2 falha ou lote rejeitado · 3 nenhuma exportação nova
(modo pasta) · 4 outra execução em andamento · 5 pré-requisito ausente.

## Persistência, travas e retomada

- Tabelas `execucoes_agente` (início, término, modo, etapa, tentativas,
  etapas da tela, diagnóstico, confirmação do painel), `importacoes`
  (arquivo, hash, período, contagens, completude, pendências, total) e
  `importacao_rejeicoes` (linha e motivo, sem o conteúdo).
- Trava no banco com validade: execuções não se sobrepõem entre processos.
- Execução interrompida depois de capturar o arquivo: a próxima retoma a
  partir dele (revalidando tudo, com o mesmo escopo conferido).
