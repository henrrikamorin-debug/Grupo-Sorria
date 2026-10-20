# Regras de conferência

## Situação atual

- `sorria/regras/demonstracao.py`: 7 regras **ilustrativas** (DEMO-01 a
  DEMO-07), usadas apenas no modo demonstração para exibir o layout. Não são
  regras aprovadas e nunca rodam no modo real.
- `sorria/regras/aprovadas.py`: lista vazia. As regras reais entram aqui.

## Modelo para cada inconsistência descrita nos materiais

Para cada inconsistência citada nas gravações/áudios, preencher:

| Item | Conteúdo |
|---|---|
| Código | `FIN-01`, `FIN-02`… |
| Nome | curto, como aparece no painel |
| Condição | regra objetiva, verificável por código |
| Campos necessários | quais campos do TOTVS e de quais telas/relatórios |
| Exceções | casos que parecem inconsistência mas não são |
| Exemplo positivo | lançamento conferido manualmente que deve gerar ocorrência |
| Exemplo negativo | lançamento parecido que não deve gerar |
| Evidência exibida | quais campos mostrar no detalhe; quais são sensíveis |
| Dúvidas | só ambiguidades que mudam o resultado |

## Processo de aprovação

1. Escrever a regra em `aprovadas.py` com `aprovada=True` e marcar como
   `sensivel=True` os itens de evidência com dados pessoais ou bancários.
2. Criar teste com os exemplos positivo e negativo conferidos manualmente.
3. Rodar contra um período real já conferido e comparar o resultado.
4. Só depois ativar o modo real.

Regras são sempre código determinístico: não usam IA.
