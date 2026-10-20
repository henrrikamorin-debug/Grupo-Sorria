# Arquitetura

```
           ┌──────────────── serviço local (python -m sorria iniciar) ────────────────┐
           │                                                                            │
 TOTVS ──▶ │ Conector ──▶ Consolidação ──▶ Regras ──▶ Gravação atômica ──▶ SQLite        │
 (futuro)  │ (somente     (valida, remove  (código     (substitui retrato   (dados/<modo>)│
           │  leitura)    repetidos)       determin.)  só se tudo deu certo)              │
           │      ▲                                                     │               │
           │  Agendador (10 min, sem sobreposição)                      ▼               │
           │                                         API HTTP (somente leitura + ações   │
           │                                         locais) ──▶ Interface web / TV      │
           │                                                  └▶ Agente IA (desativado)  │
           └────────────────────────────────────────────────────────────────────────────┘
```

## Decisões

- **Python + biblioteca padrão + SQLite**: nada para instalar além do Python,
  fácil de manter e de rodar no computador do financeiro. O SQLite fica em
  modo WAL, o que permite leitura pelo painel durante a gravação da coleta.
- **Interface sem dependências** (HTML/CSS/JS puro, gráficos em SVG/HTML):
  funciona offline e não depende de CDN.
- **Contrato único de dados** (`sorria/conectores/base.py`): o painel, as
  regras e a exportação conhecem apenas `Lancamento`. Trocar ou evoluir a
  integração TOTVS não exige mexer na apresentação.
- **Retrato atômico**: cada coleta bem-sucedida substitui lançamentos e
  ocorrências em uma única transação. Falha = nada muda + registro da falha.
- **Ocorrência = (lançamento, regra)** com identificação estável. Isso
  permite manter a situação (pendente/em análise/resolvida) entre coletas e
  impede duplicação.
- **Valor sem repetição**: indicadores e gráficos somam cada lançamento uma
  vez por grupo (`analise._soma_unica`).
- **Travas**: `threading.Lock` no processo + registro com validade na tabela
  `trava_coleta` (protege contra dois serviços iniciados por engano). A
  validade é `coleta.tempo_maximo_minutos`.
- **Coleta interrompida** (serviço encerrado no meio) é marcada como falha na
  próxima inicialização.
- **Modo TV mascarado no servidor**: campos marcados como sensíveis e padrões
  de CPF/CNPJ/conta/e-mail/telefone são removidos antes da resposta.
- **IA fora do caminho crítico**: nenhuma coleta, filtro ou cálculo chama IA.

## API local

| Método | Caminho | Descrição |
|---|---|---|
| GET | `/api/saude` | serviço no ar |
| GET | `/api/situacao` | situação da integração e histórico |
| GET | `/api/painel?inicio&fim&clinica&categoria&situacao&tv` | indicadores, gráficos e ocorrências |
| GET | `/api/ocorrencias.csv?...` | exportação filtrada |
| GET | `/api/regras` | regras em uso e seus metadados |
| GET | `/api/agente/estado` | configuração e consumo do agente |
| GET | `/api/agente/contexto?...` | contexto mínimo para o agente (503 se desativado) |
| POST | `/api/coleta` | coleta manual (`{"simular_falha": true}` só na demonstração) |
| POST | `/api/ocorrencias/<id>/situacao` | altera situação local |
| POST | `/api/agente/perguntar` | pergunta ao agente (503 se desativado) |
| POST | `/api/encerrar` | encerra o serviço |

Requisições POST só são aceitas a partir do próprio computador e com o
cabeçalho `X-Painel-Sorria: 1` (impede que outra página do navegador dispare
ações).
