# Painel Financeiro — Grupo Sorria

Sistema local de acompanhamento financeiro: coleta periódica de lançamentos,
regras de conferência determinísticas e um painel para a televisão do
financeiro.

> **Estado atual: MODO DEMONSTRAÇÃO — DADOS FICTÍCIOS.**
> A integração com o TOTVS ainda não existe. Todos os números, clínicas,
> fornecedores e ocorrências exibidos são inventados, e as regras são apenas
> ilustrativas (não aprovadas). Nada é lido nem alterado no TOTVS.

## Requisitos

- Python 3.10 ou superior (testado com 3.13). Nenhuma dependência externa.
- Navegador atual (Chrome, Edge ou Firefox) no computador ligado à TV.
- Não precisa de internet: o painel não usa CDN nem serviços externos.

## Como iniciar e parar

| Ação | Windows | Linux/macOS |
|---|---|---|
| Iniciar | `scripts\iniciar.bat` (abre o modo TV no navegador) | `./scripts/iniciar.sh` |
| Parar | `scripts\parar.bat` | `./scripts/parar.sh` |
| Situação das coletas | `py -3 -m sorria situacao` | `python3 -m sorria situacao` |
| Coleta avulsa (sem servidor) | `py -3 -m sorria coletar` | `python3 -m sorria coletar` |
| Importar a planilha de filiais | `py -3 -m sorria importar-filiais CONTROLE_FILIAL_TOTVS.xlsx` | `python3 -m sorria importar-filiais CONTROLE_FILIAL_TOTVS.xlsx` |
| Definir a conta proprietária (escritório) | `py -3 -m sorria definir-proprietario` | `python3 -m sorria definir-proprietario` |
| Gerar relatório mensal | `py -3 -m sorria relatorio 2026-10` | `python3 -m sorria relatorio 2026-10` |

Também é possível rodar em primeiro plano: `python3 -m sorria iniciar`
(Ctrl+C encerra). Execute os comandos dentro da pasta `painel-financeiro`.

Endereços (padrão):

- Painel: <http://127.0.0.1:8750>
- Modo televisão: <http://127.0.0.1:8750/?tv=1>

## Agente TOTVS (Contas a Pagar)

O modo real é alimentado pelo **agente TOTVS**: a exportação SE2 da Consulta
Genérica (Vencimento = Mês Atual, Exp. CSV) é validada, importada sem
duplicar e exibida no painel com período, origem, última coleta válida,
pendências e conferência de totais. Veja `docs/AGENTE_TOTVS.md`.

- Conferir: `py -3 -m sorria agente verificar`
- Executar e aguardar a exportação: `scripts\agente.bat`, ou pelo Claude Code: `/coletar-totvs`
- Importar um arquivo já exportado: `py -3 -m sorria agente importar arquivo.csv`
- Conta proprietária da área restrita: `py -3 -m sorria definir-proprietario`

## Uso

- **Filtros**: período (atalhos ou personalizado), clínica, categoria e
  situação. Clicar em uma barra de clínica/categoria filtra por ela; clicar em
  uma coluna do gráfico de período filtra aquele intervalo.
- **Ocorrências**: clique em uma linha para ver a evidência (regra, condição
  verificada e os dados que originaram a ocorrência). Ali também é possível
  marcar a situação (pendente, em análise, resolvida) — isso fica registrado
  só no painel, **não altera o TOTVS**.
- **Exportar CSV**: exporta exatamente as ocorrências filtradas, separador `;`,
  pronto para Excel. A coluna “Valor sem repetição” traz o valor apenas na
  primeira ocorrência de cada lançamento, para a soma não contar o mesmo
  lançamento duas vezes.
- **Modo TV**: botão “Modo TV” ou `?tv=1`. Letras maiores, tabela paginada com
  troca automática a cada 20 s, cursor e botões escondidos até o mouse mexer,
  e **CPF/CNPJ, nomes de pessoas físicas e dados bancários ocultados no
  servidor** (não chegam ao navegador). “Tela cheia” usa o modo de tela cheia
  do navegador (F11 também funciona).
- **Situação da integração** (canto superior): horário da última coleta
  bem-sucedida, aviso de dados desatualizados, histórico das últimas execuções
  e botões para coleta manual. No modo demonstração há também “Simular falha”,
  para ver como o painel se comporta quando a coleta falha.

### Filiais, número do título e categorias

- **Filiais**: o conector informa só o código TOTVS da filial (ex.: `016501`).
  O nome exibido vem do cadastro importado da planilha de controle
  (`importar-filiais`), salvo em `dados/filiais.json`, fora do repositório. A
  importação avisa sobre CNPJs fora do padrão e filiais sem código TOTVS.
- **Referência = número do título no TOTVS** (com a parcela, quando houver:
  `000045731/2`). Internamente o lançamento é identificado por filial + prefixo
  + número + parcela, porque o mesmo número pode se repetir entre filiais.
- **Categoria pelo prefixo do título**: título **sem prefixo** no TOTVS entra
  em **"Diversos"**. A tabela prefixo → categoria fica em
  `categorias.por_prefixo` no `config.json`; um prefixo ainda não cadastrado
  aparece como "Prefixo XXX" até ser incluído.

### Ticket (responsável por filial)

O filtro **Ticket** fica ao lado de Clínica. Os tickets vêm da coluna
**DIVISÃO** da planilha de filiais (TICKET 1 a TICKET 6). Ao escolher um
ticket, o painel mostra só as filiais dele (indicadores, inconsistências,
pendências, gráficos, tabela e exportação), e a lista de clínicas passa a ter
apenas essas filiais. No gráfico da esquerda, o botão **Ticket** mostra o
total por ticket; clicar em um ticket aplica o filtro.

O ticket também aparece abaixo da clínica na tabela, no detalhe da ocorrência,
no CSV e no relatório mensal (com a tabela "Pendências por ticket").

Para mostrar o nome de quem cuida de cada ticket ("TICKET 1 — Nome"), preencha
`responsaveis.por_divisao` no `config.json`: `{"TICKET 1": "Nome"}`. Exceções
por filial vão em `responsaveis.por_filial` ou numa coluna RESPONSÁVEL da
planilha.

Na demonstração, com a planilha importada, os dados fictícios são distribuídos
pelas filiais e tickets reais da planilha.

### Área restrita do escritório (conta proprietária)

A filial do escritório (`031801`) concentra a folha dos colaboradores e os
pagamentos a PJ. Também são restritos os títulos de filial fora do cadastro,
cuja classificação é incerta. Esses dados ficam **fora** de indicadores,
gráficos, tabela, filtros, CSV, relatórios, situação e agente de IA. A
restrição é aplicada no servidor, e só a **conta proprietária** libera.

- A conta é criada **no computador do serviço**:
  `py -3 -m sorria definir-proprietario` (usuário e senha, com mínimo de 8
  caracteres). Só o hash é gravado em `dados/acesso.json`. Sem essa conta,
  a área fica bloqueada para todos.
- O desbloqueio exige usuário e senha da conta proprietária, vale só neste
  computador, por 30 minutos, e nunca no modo TV. Após 5 erros, novas
  tentativas esperam 5 minutos.
- Detalhes em `docs/AGENTE_TOTVS.md`.

### Relatório mensal (filiais com mais dificuldade)

No dia 1º de cada mês, após a primeira coleta bem-sucedida, o serviço gera o
relatório do mês anterior em `dados/relatorios/<modo>/relatorio-AAAA-MM.html`
(e `.csv`). Também dá para gerar a qualquer momento em **Relatórios** no
painel ou pela linha de comando.

- Ranking das filiais pelo **percentual de lançamentos do mês com
  inconsistência** (empate: pendências, depois número de ocorrências), com
  comparação com o mês anterior. Filiais com menos de 5 lançamentos no mês
  ficam fora do ranking e aparecem à parte.
- Detalhamento das 5 filiais em destaque: regras mais frequentes e a lista de
  ocorrências (pendentes primeiro), com número do título, para enviar a quem
  precisa de mais apoio.
- Nunca inclui a área restrita e omite dados pessoais e bancários.
- Depende de o computador e o serviço estarem ligados no dia 1º; se não
  estiverem, é gerado na primeira coleta seguinte.

### Indicadores

| Indicador | Cálculo |
|---|---|
| Registros analisados | lançamentos no período/clínica/categoria filtrados |
| Inconsistências | ocorrências (lançamento × regra) nos filtros; mostra também quantos lançamentos distintos |
| Valor associado | soma do valor de cada lançamento com ocorrência, **contado uma única vez** mesmo com várias ocorrências |
| Pendências | ocorrências pendentes + em análise |

## Atualização dos dados — leia antes de usar

- A coleta é feita pelo **serviço local** a cada 10 minutos (configurável).
  Ela só acontece **enquanto o computador e o serviço estiverem ligados**. Se
  o computador desligar, hibernar ou o serviço for encerrado, não há coleta.
- **Atualizar a página não coleta nada do TOTVS.** O navegador relê os dados
  locais a cada 60 s; o horário “Painel relido às…” no rodapé é diferente do
  horário da “última coleta bem-sucedida” no topo.
- Execuções nunca se sobrepõem (trava no processo e no banco). Uma falha é
  registrada no histórico e em `logs/painel.log`, e o painel continua exibindo
  a **última coleta válida**. Após 25 min sem coleta bem-sucedida, o painel
  indica “Dados desatualizados”.
- Uma coleta que volte vazia logo após um retrato com dados é tratada como
  falha (proteção contra problema na origem). Ajustável em
  `coleta.aceitar_coleta_vazia`.
- Para iniciar automaticamente com o Windows: Agendador de Tarefas → Criar
  tarefa → “Ao fazer logon” → ação `scripts\iniciar.bat`. Desative a
  suspensão/hibernação do computador nas opções de energia.

## Prévia publicada (dados fictícios)

Uma prévia estática do painel está publicada no Claude:
<https://claude.ai/artifact/YRNuLF66Y4m6eHcFkrMR6K> (acesso controlado pelo
menu Compartilhar da página). Ela usa sempre dados fictícios, simula a API no
navegador e não faz coleta. Para regenerar:
`python3 scripts/previa/gerar_previa.py . painel-publicado.html scripts/previa/mock.js publicar`.

**Dados reais não devem ser publicados dessa forma**: com o modo real, o painel
deve ficar no serviço local do financeiro.

## Configuração

Copie `config.example.json` para `config.json` e ajuste. Principais chaves:

| Chave | Padrão | Observação |
|---|---|---|
| `modo` | `demonstracao` | `real` usa somente o conector TOTVS e regras aprovadas |
| `servidor.host` / `porta` | `127.0.0.1` / `8750` | veja Segurança |
| `coleta.intervalo_minutos` | `10` | mínimo 1 |
| `coleta.tolerancia_desatualizacao_minutos` | `25` | quando avisar dados desatualizados |
| `coleta.tempo_maximo_minutos` | `8` | coleta mais longa é descartada |
| `televisao.rotacao_tabela_segundos` | `20` | troca de página da tabela na TV |
| `agente_ia.habilitado` | `false` | ver `docs/AGENTE_IA.md` |
| `categorias.por_prefixo` | `{}` | prefixo do título → categoria; sem prefixo = `Diversos` |
| `acesso_restrito.filiais` | `["031801"]` | filiais que exigem senha (escritório) |
| `relatorio_mensal.minimo_lancamentos` | `5` | mínimo para entrar no ranking |

Dados de demonstração e reais ficam em arquivos separados
(`dados/demonstracao.sqlite3` e `dados/real.sqlite3`); um banco criado em um
modo é recusado no outro. Trocar `modo` exige reiniciar o serviço.

## Segurança

- Por padrão o painel só é acessível neste computador (`127.0.0.1`). O ideal
  é ligar a TV ao próprio computador (HDMI).
- Se precisar abrir na rede (`"host": "0.0.0.0"`), saiba que não há login.
  Por isso, acessos vindos de outra máquina **sempre** recebem a versão
  mascarada (como no modo TV), e ações (coleta manual, mudar situação) só são
  aceitas a partir deste computador. Ainda assim, use apenas em rede interna
  confiável e libere a porta só para a TV no firewall.
- `dados/`, `logs/` e `config.json` estão no `.gitignore`: não versione dados
  reais nem credenciais. Credenciais (TOTVS, IA) devem ficar em variáveis de
  ambiente, nunca em arquivos do projeto.

## Testes

```
python3 -m unittest discover -s tests -v
```

Cobrem: soma sem repetição, filtros, granularidade do período, preservação da
última coleta após falha, coleta vazia, travas contra execução simultânea
(no processo e entre processos), agendador, situação mantida entre coletas,
separação demo/real, mascaramento do modo TV, CSV e a API HTTP.

## Estrutura

```
painel-financeiro/
  sorria/
    conectores/      origem dos dados (demonstração, TOTVS pendente)
    regras/          regras determinísticas (ilustrativas e aprovadas)
    coleta.py        serviço de coleta + agendador + travas
    analise.py       filtros, indicadores e agregações
    situacao.py      situação da integração
    privacidade.py   ocultação de dados no modo TV
    exportacao.py    CSV
    agente.py        interface com agente de IA (desativada)
    servidor.py      HTTP local (interface + API)
  web/               interface (HTML/CSS/JS sem dependências)
  scripts/           iniciar/parar
  tests/
  docs/              arquitetura, TOTVS, regras, agente de IA
```

## O que funciona e o que depende dos seus materiais

Funciona agora (com dados fictícios): painel completo com filtros, gráficos,
tabela, evidências, exportação, modo TV, situação da integração, coleta
agendada simulada com travas e preservação da última coleta válida, e os
estados de carregamento, ausência de dados e falha.

Depende das gravações, áudios e definições do financeiro:

1. Conector TOTVS (produto, forma de acesso, campos) — `docs/INTEGRACAO_TOTVS.md`.
2. Regras reais de inconsistência, com exemplos conferidos — `docs/REGRAS.md`.
3. Validação contra conferências manuais antes de ativar `modo: real`.
4. Agente de IA (opcional): conta e chave de API — `docs/AGENTE_IA.md`.
