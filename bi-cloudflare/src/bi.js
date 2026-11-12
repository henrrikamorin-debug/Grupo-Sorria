// BI financeiro do painel online: porte fiel de sorria/bi.py. Trabalha SOMENTE sobre o retrato público e
// mascarado (ocorrencias + bi_lancamentos). Definições e regras: docs/BI.md.
//
//  * Inconsistência = ocorrência de regra que aponta problema nos DADOS. "Título vencido" (SE2-01) não é.
//  * Pendência = ocorrência ainda não resolvida (pendente + em_analise).
//  * Título vencido = título em aberto (saldo) com vencimento real anterior a hoje.
//  * Pendência crítica = título vencido com inconsistência não resolvida.

export class FiltroInvalido extends Error {}

const SITUACOES = ["pendente", "em_analise", "resolvida"];
const ABERTAS = ["pendente", "em_analise"];
const ROTULO_STATUS = { pendente: "Não tratada", em_analise: "Em tratamento", resolvida: "Resolvida" };
const ROTULO_SIT_TITULO = { aberto: "Em aberto (a vencer)", vencido: "Vencido em aberto",
  pendente_baixa: "Pendente de baixa (a verificar)", pago: "Pago", ausente: "Não consta mais em aberto no TOTVS" };
const PERIODOS = ["ultimas_24h", "hoje", "ontem", "ultimos_7", "ultimos_15", "ultimos_30", "ultimos_90", "mes_atual", "mes_anterior", "personalizado"];
const CAMPOS_DATA = { vencimento: "Vencimento do título", identificacao: "Data em que a ocorrência foi identificada" };
export const PRIORIDADE_PADRAO = {
  dias_vencido: [[30, 3], [15, 2], [1, 1]], valor_centavos: [[1_000_000, 3], [200_000, 2], [1, 1]],
  ocorrencias: [[3, 3], [2, 2], [1, 1]], alta_a_partir_de: 7, media_a_partir_de: 5,
};
const DIA = 864e5;
const OFFSET_MS = -3 * 3600e3; // America/Sao_Paulo (sem horário de verão desde 2019)
const FUSO = "UTC-03:00";

const dUTC = (iso) => new Date(iso + "T00:00:00Z");
const isoUTC = (d) => d.toISOString().slice(0, 10);
const dataValida = (t) => /^\d{4}-\d{2}-\d{2}$/.test(t) && !Number.isNaN(dUTC(t).getTime()) && isoUTC(dUTC(t)) === t;

// ------------------------------------------------------------------ filtros e períodos
const CHAVES = ["periodo", "inicio", "fim", "campo_data", "clinica", "ticket", "situacao", "tipo_ocorrencia",
  "tipo_inconsistencia", "situacao_financeira"];

export function lerFiltros(params) {
  const valor = (n) => (params.get(n) || "").trim() || null;
  const f = Object.fromEntries(CHAVES.map((c) => [c, valor(c)]));
  f.campo_data = f.campo_data || "vencimento";
  if (!(f.campo_data in CAMPOS_DATA)) throw new FiltroInvalido("campo de data desconhecido");
  if (f.periodo && !PERIODOS.includes(f.periodo)) throw new FiltroInvalido(`período desconhecido: ${f.periodo}`);
  if (f.situacao && !SITUACOES.includes(f.situacao)) throw new FiltroInvalido(`situação desconhecida: ${f.situacao}`);
  if (f.situacao_financeira && !(f.situacao_financeira in ROTULO_SIT_TITULO)) {
    throw new FiltroInvalido(`situação financeira desconhecida: ${f.situacao_financeira}`);
  }
  for (const n of ["inicio", "fim"]) if (f[n] && !dataValida(f[n])) throw new FiltroInvalido(`data inválida em '${n}': ${f[n]}`);
  if (f.inicio && f.fim && f.inicio > f.fim) throw new FiltroInvalido("a data inicial é posterior à final");
  if (f.periodo === "personalizado" && !(f.inicio || f.fim)) throw new FiltroInvalido("informe a data inicial e/ou final do período personalizado");
  return f;
}

const local = (ms) => new Date(ms + OFFSET_MS); // ler com getters UTC = relógio local
const isoLocal = (ms) => local(ms).toISOString().slice(0, 19) + "-03:00";
const dataLocal = (iso) => {
  if (!iso) return null;
  const ms = Date.parse(/[zZ]|[+-]\d{2}:\d{2}$/.test(iso) ? iso : iso + "Z");
  return Number.isNaN(ms) ? String(iso).slice(0, 10) : local(ms).toISOString().slice(0, 10);
};

export function resolverPeriodo(f, agoraMs = Date.now()) {
  const hoje = local(agoraMs).toISOString().slice(0, 10);
  const soma = (n) => isoUTC(new Date(dUTC(hoje).getTime() + n * DIA));
  let { inicio, fim } = f, desde = null;
  const p = f.periodo;
  if (p === "ultimas_24h") { desde = agoraMs - DIA; inicio = local(desde).toISOString().slice(0, 10); fim = hoje; }
  else if (p === "hoje") { inicio = fim = hoje; }
  else if (p === "ontem") { inicio = fim = soma(-1); }
  else if (["ultimos_7", "ultimos_15", "ultimos_30", "ultimos_90"].includes(p)) { inicio = soma(-(Number(p.split("_")[1]) - 1)); fim = hoje; }
  else if (p === "mes_atual") { // mês corrente INTEIRO (inclui vencimentos futuros do mês), como o filtro do TOTVS
    inicio = hoje.slice(0, 8) + "01";
    const proximo = new Date(Date.UTC(Number(hoje.slice(0, 4)), Number(hoje.slice(5, 7)), 1));
    fim = isoUTC(new Date(proximo.getTime() - DIA));
  }
  else if (p === "mes_anterior") {
    const ultimo = new Date(dUTC(hoje.slice(0, 8) + "01").getTime() - DIA);
    inicio = isoUTC(ultimo).slice(0, 8) + "01"; fim = isoUTC(ultimo);
  }
  return { periodo: p, inicio, fim, campo_data: f.campo_data, campo_rotulo: CAMPOS_DATA[f.campo_data],
    desde: desde == null ? null : isoLocal(desde), desde_ms: desde, agora: isoLocal(agoraMs), fuso: FUSO };
}

// ------------------------------------------------------------------ carga a partir do retrato
// Título em aberto com ocorrência "pendente de baixa" (SE2-06) não resolvida: situação própria, sem contar também
// como vencido/a vencer (partição sem sobreposição).
const situacaoPainel = (l) => {
  const sit = l.situacao_titulo;
  if ((sit === "aberto" || sit === "vencido") && l.ocorrencias.some((o) => o.regra_codigo === "SE2-06" && o.situacao !== "resolvida")) return "pendente_baixa";
  return sit;
};

// A base (lançamentos com suas ocorrências) só depende do retrato: no navegador ela é montada uma vez e
// reaproveitada a cada filtro (o retrato é tratado como imutável).
const BASES = new WeakMap();
export function carregar(snapshot) {
  let base = BASES.get(snapshot);
  if (!base) BASES.set(snapshot, (base = construirBase(snapshot)));
  return base;
}

function construirBase(snapshot) {
  const lancamentos = new Map();
  for (const l of snapshot.bi_lancamentos || []) lancamentos.set(l.referencia, { ...l, ocorrencias: [] });
  const ocs = [];
  for (const o0 of snapshot.ocorrencias) {
    const l = lancamentos.get(o0.referencia);
    if (!l) continue; // ocorrência sem lançamento correspondente: ignora em vez de inventar
    const o = { ...o0,
      identificada_em: o0.primeira_deteccao ?? null, identificada_data: dataLocal(o0.primeira_deteccao),
      ticket: l.ticket, documento_titulo: l.documento_titulo, numero_titulo: l.numero_titulo,
      situacao_titulo: l.situacao_titulo, vencimento: l.data };
    l.ocorrencias.push(o);
    ocs.push(o);
  }
  for (const l of lancamentos.values()) l.situacao_painel = situacaoPainel(l);
  return { lancamentos, ocorrencias: ocs, prioridade: { ...PRIORIDADE_PADRAO, ...(snapshot.bi_prioridade || {}) } };
}

const noPeriodo = (d, per) => !!d && (!per.inicio || d >= per.inicio) && (!per.fim || d <= per.fim);

export function filtrar(base, f, per) {
  const porVenc = f.campo_data === "vencimento";
  const filtraPeriodo = !!(per.inicio || per.fim);
  const lancOk = (l) => {
    if (f.clinica && l.clinica !== f.clinica) return false;
    if (f.ticket && l.ticket !== f.ticket) return false;
    if (f.situacao_financeira && l.situacao_painel !== f.situacao_financeira) return false;
    if (porVenc && filtraPeriodo && !noPeriodo(l.data, per)) return false;
    return true;
  };
  const ocOk = (o) => {
    if (f.situacao && o.situacao !== f.situacao) return false;
    if (f.tipo_ocorrencia && o.regra_codigo !== f.tipo_ocorrencia) return false;
    if (f.tipo_inconsistencia && !(o.classe === "inconsistencia" && o.tipo === f.tipo_inconsistencia)) return false;
    if (!porVenc && filtraPeriodo) {
      if (per.desde_ms != null) {
        if (!o.identificada_em || Date.parse(o.identificada_em) < per.desde_ms) return false;
      } else if (!noPeriodo(o.identificada_data, per)) return false;
    }
    return true;
  };
  const filtroOc = !!(f.situacao || f.tipo_ocorrencia || f.tipo_inconsistencia || (!porVenc && filtraPeriodo));
  const lancs = [], ocs = [];
  for (const l of base.lancamentos.values()) {
    if (!lancOk(l)) continue;
    const aprovadas = l.ocorrencias.filter(ocOk);
    if (filtroOc && !aprovadas.length) continue;
    lancs.push(l);
    ocs.push(...aprovadas);
  }
  return [lancs, ocs];
}

// ------------------------------------------------------------------ derivados
const diasEntre = (inicioIso, fimIso) => {
  if (!inicioIso) return null;
  const a = dUTC(inicioIso.slice(0, 10)).getTime();
  if (Number.isNaN(a)) return null;
  return Math.max(Math.round((dUTC(fimIso).getTime() - a) / DIA), 0);
};

export function enriquecer(lancs, ocs, agoraMs) {
  const hoje = local(agoraMs).toISOString().slice(0, 10);
  for (const o of ocs) {
    const fim = ABERTAS.includes(o.situacao) ? hoje
      : (dataLocal(o.situacao_atualizada_em) || o.identificada_data || hoje).slice(0, 10);
    o.dias_em_aberto = diasEntre(o.identificada_data, fim);
    o.status_rotulo = ROTULO_STATUS[o.situacao];
  }
  for (const l of lancs) {
    const abertas = l.ocorrencias.filter((o) => ABERTAS.includes(o.situacao));
    l.n_ocorrencias = l.ocorrencias.length;
    l.tem_inconsistencia = l.ocorrencias.some((o) => o.classe === "inconsistencia");
    l.inconsistencia_aberta = l.ocorrencias.some((o) => o.classe === "inconsistencia" && ABERTAS.includes(o.situacao));
    l.tem_pendencia = abertas.length > 0;
    l.dias_vencido = l.situacao_painel === "vencido" ? diasEntre(l.vencimento_real || l.data, hoje) : null;
    l.em_aberto = ["aberto", "vencido", "pendente_baixa"].includes(l.situacao_painel);
    l.saldo_ou_valor = l.saldo_centavos != null ? l.saldo_centavos : l.valor_centavos;
  }
}

const pontos = (valor, faixas) => {
  for (const [limite, pts] of [...faixas].sort((a, b) => b[0] - a[0])) if (valor != null && valor >= limite) return pts;
  return 0;
};

export function criticas(lancs, prio) {
  const r = [];
  for (const l of lancs) {
    if (l.situacao_painel !== "vencido" || !l.inconsistencia_aberta) continue;
    const pd = pontos(l.dias_vencido, prio.dias_vencido), pv = pontos(l.saldo_ou_valor, prio.valor_centavos);
    const po = pontos(l.ocorrencias.filter((o) => ABERTAS.includes(o.situacao)).length, prio.ocorrencias);
    const total = pd + pv + po;
    r.push({ ...l, prioridade: total >= prio.alta_a_partir_de ? "Alta" : total >= prio.media_a_partir_de ? "Média" : "Baixa",
      pontos: total, pontos_detalhe: `tempo vencido ${pd} + valor ${pv} + ocorrências abertas ${po}` });
  }
  r.sort((a, b) => b.pontos - a.pontos || (b.saldo_ou_valor || 0) - (a.saldo_ou_valor || 0));
  return r;
}

export const INDICADORES = [
  ["lancamentos", "Lançamentos", "lancamentos", "Registros financeiros identificados (títulos) dentro dos filtros."],
  ["ocorrencias", "Ocorrências", "ocorrencias", "Achados das regras sobre os lançamentos. Um lançamento pode ter várias ocorrências (uma por regra) ou nenhuma."],
  ["inconsistencias", "Inconsistências", "ocorrencias", "Ocorrências que apontam problema nos dados (duplicidade, campos vazios, filial sem cadastro, divergência). Título vencido NÃO é inconsistência."],
  ["pendencias_nao_tratadas", "Pendências não tratadas", "ocorrencias", "Ocorrências com situação 'Pendente' (de qualquer tipo, inclusive título vencido)."],
  ["pendencias_em_tratamento", "Pendências em tratamento", "ocorrencias", "Ocorrências com situação 'Em análise'."],
  ["pendencias_resolvidas", "Pendências resolvidas", "ocorrencias", "Ocorrências com situação 'Resolvida'."],
  ["titulos_em_aberto", "Títulos em aberto", "titulos", "Títulos da SE2 com saldo: a vencer ou vencidos. Pagos não entram."],
  ["titulos_vencidos", "Títulos vencidos em aberto", "titulos", "Títulos em aberto cujo vencimento real já passou e que NÃO têm indício de pagamento. Não são, por si só, inconsistência."],
  ["titulos_pendentes_baixa", "Títulos pendentes de baixa", "titulos", "Títulos em aberto cujo histórico indica pagamento/baixa (indício, não prova): a verificar. Não entram também em 'vencidos'."],
  ["titulos_sem_movimentacao", "Títulos sem movimentação", "titulos", "INDISPONÍVEL: a exportação do TOTVS não traz histórico de movimentação nem data da última movimentação; sem esse critério real, nenhum número é apresentado."],
  ["pendencias_criticas", "Pendências críticas", "titulos", "Títulos vencidos que também têm inconsistência não resolvida (vínculo pela referência do título)."],
];
const EXTRAS = [["pendencias", "Pendências em aberto", "ocorrencias", "Ocorrências ainda não resolvidas: não tratadas + em tratamento."]];

const titulosDe = (lancs) => lancs.filter((l) => l.situacao_titulo != null);

export function conjuntos(lancs, ocs, prio) {
  const tit = titulosDe(lancs);
  return {
    lancamentos: lancs, ocorrencias: ocs,
    inconsistencias: ocs.filter((o) => o.classe === "inconsistencia"),
    pendencias_nao_tratadas: ocs.filter((o) => o.situacao === "pendente"),
    pendencias_em_tratamento: ocs.filter((o) => o.situacao === "em_analise"),
    pendencias_resolvidas: ocs.filter((o) => o.situacao === "resolvida"),
    pendencias: ocs.filter((o) => ABERTAS.includes(o.situacao)),
    titulos_em_aberto: tit.filter((l) => l.em_aberto),
    titulos_vencidos: tit.filter((l) => l.situacao_painel === "vencido"),
    titulos_pendentes_baixa: tit.filter((l) => l.situacao_painel === "pendente_baixa"),
    titulos_sem_movimentacao: null,
    pendencias_criticas: criticas(tit, prio),
  };
}

export function montarIndicadores(conj, temTitulos) {
  return INDICADORES.map(([id, rotulo, tipo, regra]) => {
    const itens = conj[id];
    const disponivel = itens != null && (tipo !== "titulos" || temTitulos);
    const item = { id, rotulo, tipo_registro: tipo, regra, disponivel };
    if (disponivel) {
      item.valor = itens.length;
      if (tipo === "ocorrencias") item.lancamentos_distintos = new Set(itens.map((o) => o.referencia)).size;
      if (tipo !== "ocorrencias" && id !== "lancamentos") item.valor_centavos = itens.reduce((s, l) => s + (l.saldo_ou_valor || 0), 0);
    } else {
      item.valor = null;
      item.motivo = itens == null ? regra : "Sem títulos do TOTVS neste modo de dados.";
    }
    return item;
  });
}

export function relacoes(conj) {
  const comparar = (ra, a, rb, b, chave, nota) => {
    const ca = new Set(a.map(chave)), cb = new Set(b.map(chave));
    const ambos = [...ca].filter((x) => cb.has(x)).length;
    return { a: ra, b: rb, total_a: ca.size, total_b: cb.size, em_ambos: ambos, so_a: ca.size - ambos, so_b: cb.size - ambos,
      mesmos_registros: ca.size === cb.size && ambos === ca.size, nota };
  };
  return [
    comparar("Inconsistências", conj.inconsistencias, "Pendências em aberto (não tratadas + em tratamento)", conj.pendencias,
      (o) => o.id, "Mede se as ocorrências que são inconsistência são as mesmas que seguem pendentes."),
    comparar("Títulos vencidos", conj.titulos_vencidos || [], "Lançamentos com inconsistência",
      (conj.lancamentos || []).filter((l) => l.tem_inconsistencia), (l) => l.referencia,
      "Interseção = títulos vencidos que também têm inconsistência (base das pendências críticas)."),
  ];
}

// ------------------------------------------------------------------ gráficos
const ordenarPt = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

export function graficos(lancs, ocs, conj, temTitulos) {
  const contar = (itens, chave) => {
    const c = new Map();
    for (const x of itens) c.set(chave(x), (c.get(chave(x)) || 0) + 1);
    return [...c].map(([rotulo, valor]) => ({ rotulo, valor })).sort((a, b) => b.valor - a.valor || ordenarPt(a.rotulo, b.rotulo));
  };
  const serie = (m) => [...m].filter(([k]) => k).sort((a, b) => ordenarPt(a[0], b[0])).map(([rotulo, valor]) => ({ rotulo, valor }));
  const inc = (m, k) => m.set(k, (m.get(k) || 0) + 1);
  const mes = (iso) => (iso ? iso.slice(0, 7) : null);
  const porMesVenc = new Map(), porMesIdent = new Map(), pendDia = new Map(), resolvDia = new Map();
  for (const o of conj.inconsistencias) { inc(porMesVenc, mes(o.vencimento)); inc(porMesIdent, mes(o.identificada_data)); }
  for (const o of ocs) {
    if (ABERTAS.includes(o.situacao)) inc(pendDia, o.identificada_data);
    else if (o.situacao === "resolvida") inc(resolvDia, dataLocal(o.situacao_atualizada_em));
  }
  const clin = new Map();
  for (const l of lancs) {
    if (!clin.has(l.clinica)) clin.set(l.clinica, { rotulo: l.clinica, lancamentos: 0, ocorrencias: 0, pendencias: 0, valor_centavos: 0, em_aberto_centavos: 0, vencido_centavos: 0 });
    const c = clin.get(l.clinica);
    c.lancamentos += 1;
    c.valor_centavos += l.valor_centavos || 0;
    if (l.em_aberto) c.em_aberto_centavos += l.saldo_ou_valor || 0;
    if (l.situacao_painel === "vencido") c.vencido_centavos += l.saldo_ou_valor || 0;
  }
  for (const o of ocs) {
    const c = clin.get(o.clinica);
    if (!c) continue;
    c.ocorrencias += 1;
    if (ABERTAS.includes(o.situacao)) c.pendencias += 1;
  }
  const tickets = new Map();
  for (const o of conj.pendencias) inc(tickets, o.ticket);
  const comparativo = [...clin.values()].sort((a, b) => b.ocorrencias - a.ocorrencias); // estável, como no Python
  const sitTitulos = new Map();
  for (const l of titulosDe(lancs)) inc(sitTitulos, l.situacao_painel);
  return {
    inconsistencias_mensal_vencimento: serie(porMesVenc),
    inconsistencias_mensal_identificacao: serie(porMesIdent),
    pendencias_por_clinica: [...clin.values()].filter((c) => c.pendencias).map((c) => ({ rotulo: c.rotulo, valor: c.pendencias }))
      .sort((a, b) => b.valor - a.valor || ordenarPt(a.rotulo, b.rotulo)),
    ranking_tickets: [...tickets].sort((a, b) => b[1] - a[1] || ordenarPt(a[0], b[0])).map(([rotulo, valor]) => ({ rotulo, valor })),
    tipos_inconsistencia: contar(conj.inconsistencias, (o) => o.tipo),
    ocorrencias_x_lancamentos: comparativo,
    pendencias_evolucao: serie(pendDia),
    resolvidas_evolucao: serie(resolvDia),
    titulos_por_situacao: temTitulos ? [...sitTitulos].sort((a, b) => ordenarPt(a[0], b[0]))
      .map(([k, valor]) => ({ rotulo: ROTULO_SIT_TITULO[k] || k, chave: k, valor })) : [],
    comparativo_unidades: comparativo.filter((c) => c.valor_centavos),
  };
}

// ------------------------------------------------------------------ pendências
const FAIXAS_IDADE = [["Até 7 dias", 0, 7], ["8 a 30 dias", 8, 30], ["31 a 60 dias", 31, 60], ["Mais de 60 dias", 61, null]];

export function painelPendencias(lancs, ocs) {
  const abertas = ocs.filter((o) => ABERTAS.includes(o.situacao));
  const resolvidas = ocs.filter((o) => o.situacao === "resolvida");
  const valorDe = new Map(lancs.map((l) => [l.referencia, l.saldo_ou_valor || 0]));
  const agrupar = (itens, chave) => {
    const g = new Map();
    for (const o of itens) {
      if (!g.has(chave(o))) g.set(chave(o), { rotulo: chave(o), abertas: 0, tratadas: 0, refs: new Set() });
      const x = g.get(chave(o));
      if (ABERTAS.includes(o.situacao)) { x.abertas += 1; x.refs.add(o.referencia); } else x.tratadas += 1;
    }
    return [...g.values()].map((x) => ({ rotulo: x.rotulo, abertas: x.abertas, tratadas: x.tratadas,
      valor_centavos: [...x.refs].reduce((s, r) => s + (valorDe.get(r) || 0), 0) }))
      .sort((a, b) => b.abertas - a.abertas || b.valor_centavos - a.valor_centavos || ordenarPt(a.rotulo, b.rotulo));
  };
  const resumo = (o) => ({ id: o.id, referencia: o.referencia, clinica: o.clinica, ticket: o.ticket,
    documento_titulo: o.documento_titulo, tipo: o.tipo, motivo: o.descricao, status_rotulo: o.status_rotulo,
    dias_em_aberto: o.dias_em_aberto, valor_centavos: o.valor_centavos, confirmacao_rotulo: o.confirmacao_rotulo });
  const idade = FAIXAS_IDADE.map(([rotulo, de, ate]) => ({ rotulo,
    valor: abertas.filter((o) => o.dias_em_aberto != null && o.dias_em_aberto >= de && (ate == null || o.dias_em_aberto <= ate)).length }));
  const ordId = (a, b) => ordenarPt(a.id, b.id);
  const antigas = [...abertas].sort((a, b) => (b.dias_em_aberto || 0) - (a.dias_em_aberto || 0)
    || (b.valor_centavos || 0) - (a.valor_centavos || 0) || ordId(a, b));
  const atencao = [...abertas].sort((a, b) => (valorDe.get(b.referencia) || 0) - (valorDe.get(a.referencia) || 0) || ordId(a, b));
  const tratadas = resolvidas.length, total = abertas.length + tratadas;
  return {
    abertas: abertas.length, nao_tratadas: abertas.filter((o) => o.situacao === "pendente").length,
    em_tratamento: abertas.filter((o) => o.situacao === "em_analise").length, tratadas, total,
    percentual_tratado: total ? Math.round(tratadas * 100 / total) : null,
    mais_antiga_dias: abertas.length ? Math.max(...abertas.map((o) => o.dias_em_aberto || 0)) : null,
    idade, por_tipo: agrupar(ocs, (o) => o.tipo),
    por_clinica: agrupar(ocs, (o) => o.clinica).filter((r) => r.abertas),
    por_ticket: agrupar(ocs, (o) => o.ticket).filter((r) => r.abertas),
    mais_antigas: antigas.slice(0, 10).map(resumo), titulos_atencao: atencao.slice(0, 10).map(resumo),
    responsavel: "O ticket (divisão TICKET 1–6 da planilha de filiais) é o único responsável identificável nos dados; não há responsável individual por pendência.",
  };
}

// ------------------------------------------------------------------ tabelas
export const COLUNAS = {
  ocorrencias: [["clinica", "Clínica"], ["ticket", "Ticket"], ["documento_titulo", "Título"], ["tipo", "Tipo"], ["classe_rotulo", "Natureza"], ["confirmacao_rotulo", "Confirmação"], ["fonte", "Origem"],
    ["descricao", "Motivo"], ["identificada_data", "Identificada em"], ["status_rotulo", "Status"], ["atualizada_data", "Última atualização"],
    ["dias_em_aberto", "Dias em aberto"], ["valor_centavos", "Valor"]],
  lancamentos: [["clinica", "Clínica"], ["ticket", "Ticket"], ["documento_titulo", "Título"], ["categoria", "Categoria"], ["data", "Vencimento"],
    ["valor_centavos", "Valor"], ["sit_rotulo", "Situação do título"], ["n_ocorrencias", "Ocorrências"],
    ["tem_inconsistencia", "Tem inconsistência"], ["tem_pendencia", "Tem pendência"]],
  titulos: [["clinica", "Clínica"], ["ticket", "Ticket"], ["documento_titulo", "Título"], ["data", "Vencimento"], ["valor_centavos", "Valor"],
    ["saldo_centavos", "Saldo"], ["sit_rotulo", "Situação"], ["dias_vencido", "Dias de atraso"], ["n_ocorrencias", "Ocorrências"]],
  criticas: [["prioridade", "Prioridade"], ["pontos", "Pontos"], ["clinica", "Clínica"], ["ticket", "Ticket"], ["documento_titulo", "Título"],
    ["data", "Vencimento"], ["saldo_ou_valor", "Saldo"], ["dias_vencido", "Dias de atraso"], ["n_ocorrencias", "Ocorrências"],
    ["pontos_detalhe", "Como foi pontuada"]],
};

function linha(item, tipo) {
  const l = { ...item };
  if (tipo === "ocorrencias") {
    l.atualizada_data = dataLocal(l.situacao_atualizada_em) || l.identificada_data;
  } else {
    l.sit_rotulo = ROTULO_SIT_TITULO[l.situacao_painel] || "—";
  }
  return l;
}

export function tabela(conj, indicador, { busca = "", pagina = 1, porPagina = 25, limitar = true } = {}) {
  const meta = [...INDICADORES, ...EXTRAS].find((i) => i[0] === indicador);
  if (!meta) throw new FiltroInvalido("indicador desconhecido");
  const itens = conj[indicador];
  if (itens == null) return { indicador, disponivel: false, motivo: meta[3], colunas: [], linhas: [], total: 0 };
  const tipo = indicador === "pendencias_criticas" ? "criticas" : meta[2];
  let linhas = itens.map((i) => linha(i, tipo === "criticas" ? "titulos" : tipo));
  const campos = COLUNAS[tipo].map(([c]) => c);
  if (busca) {
    const b = busca.toLocaleLowerCase("pt-BR");
    linhas = linhas.filter((l) => campos.some((c) => String(l[c] ?? "").toLocaleLowerCase("pt-BR").includes(b)));
  }
  const total = linhas.length;
  porPagina = limitar ? Math.max(1, Math.min(porPagina, 200)) : Math.max(1, porPagina);
  pagina = Math.max(pagina, 1);
  const corte = linhas.slice((pagina - 1) * porPagina, pagina * porPagina)
    .map((l) => ({ ...Object.fromEntries(campos.map((c) => [c, l[c] ?? null])), referencia: l.referencia ?? null, id: l.id ?? null }));
  return { indicador, disponivel: true, rotulo: meta[1], regra: meta[3], tipo,
    colunas: COLUNAS[tipo].map(([campo, rotulo]) => ({ campo, rotulo })), linhas: corte, total, pagina, por_pagina: porPagina };
}

// ------------------------------------------------------------------ composição
export function montar(snapshot, f, agoraMs = Date.now()) {
  const per = resolverPeriodo(f, agoraMs);
  const base = carregar(snapshot);
  const [lancs, ocs] = filtrar(base, f, per);
  enriquecer(lancs, ocs, agoraMs);
  const temTitulos = [...base.lancamentos.values()].some((l) => l.situacao_titulo != null);
  const conj = conjuntos(lancs, ocs, base.prioridade);
  const unicos = (xs) => [...new Set(xs)].sort(ordenarPt);
  const tiposOc = new Map(base.ocorrencias.map((o) => [o.regra_codigo + "\u0000" + o.regra_nome, [o.regra_codigo, o.regra_nome]]));
  const presentes = new Set(base.ocorrencias.map((o) => o.regra_codigo));
  const opcoes = {
    clinicas: unicos([...base.lancamentos.values()].map((l) => l.clinica)),
    tickets: unicos([...base.lancamentos.values()].map((l) => l.ticket)),
    situacoes: SITUACOES.map((s) => ({ valor: s, rotulo: ROTULO_STATUS[s] })),
    tipos_catalogo: (snapshot.bi_tipos || []).map((t) => ({ ...t, com_ocorrencias: presentes.has(t.codigo) })),
    tipos_ocorrencia: [...tiposOc.values()].sort((a, b) => ordenarPt(a[0], b[0]) || ordenarPt(a[1], b[1])),
    tipos_inconsistencia: unicos(base.ocorrencias.filter((o) => o.classe === "inconsistencia").map((o) => o.tipo)),
    situacoes_financeiras: temTitulos ? Object.entries(ROTULO_SIT_TITULO).map(([valor, rotulo]) => ({ valor, rotulo })) : [],
    periodos: PERIODOS, campos_data: CAMPOS_DATA,
  };
  const { desde_ms, ...periodo } = per;
  const res = { periodo, filtros: f, indicadores: montarIndicadores(conj, temTitulos), relacoes: relacoes(conj),
    graficos: graficos(lancs, ocs, conj, temTitulos), pendencias_painel: painelPendencias(lancs, ocs), opcoes, prioridade: base.prioridade };
  Object.defineProperties(res, { _conj: { value: conj }, _lancs: { value: lancs }, _ocs: { value: ocs } });
  return res;
}

export function detalheClinica(lancs, ocs, clinica) {
  const ls = lancs.filter((l) => l.clinica === clinica), os = ocs.filter((o) => o.clinica === clinica);
  const por = new Map();
  for (const o of os) por.set(o.referencia, (por.get(o.referencia) || 0) + 1);
  const varias = [...por.values()].filter((n) => n > 1).length;
  const sem = ls.filter((l) => !por.has(l.referencia)).length;
  const explicacao = `${os.length} ocorrência(s) para ${ls.length} lançamento(s). Cada ocorrência é um achado de uma regra sobre um lançamento: `
    + `${por.size} lançamento(s) têm ao menos uma ocorrência, ${varias} têm mais de uma (regras diferentes sobre o mesmo título) e ${sem} não têm nenhuma. `
    + "A diferença NÃO indica duplicidade por si só; duplicidade é a ocorrência do tipo 'Possível lançamento duplicado'.";
  return { clinica, lancamentos: ls.length, ocorrencias: os.length, lancamentos_com_ocorrencia: por.size,
    lancamentos_com_mais_de_uma: varias, lancamentos_sem_ocorrencia: sem, explicacao,
    inconsistencias: os.filter((o) => o.classe === "inconsistencia").length,
    pendencias: os.filter((o) => ABERTAS.includes(o.situacao)).length, tickets: unicos2(ls.map((l) => l.ticket)) };
}
const unicos2 = (xs) => [...new Set(xs)].sort(ordenarPt);

export function analiseAutomatica(res) {
  const g = res.graficos, ind = Object.fromEntries(res.indicadores.map((i) => [i.id, i]));
  const achados = [];
  const totalPend = g.pendencias_por_clinica.reduce((s, p) => s + p.valor, 0);
  if (g.pendencias_por_clinica.length && totalPend) {
    const top = g.pendencias_por_clinica[0];
    achados.push(`A clínica com mais pendências em aberto é ${top.rotulo}: ${top.valor} de ${totalPend} (${Math.floor(top.valor * 100 / totalPend)}%).`);
  }
  if (g.ranking_tickets.length) achados.push(`O ${g.ranking_tickets[0].rotulo} concentra o maior número de pendências em aberto (${g.ranking_tickets[0].valor}).`);
  const antigas = res._ocs.filter((o) => ABERTAS.includes(o.situacao) && (o.dias_em_aberto || 0) >= 30);
  if (antigas.length) achados.push(`${antigas.length} pendência(s) estão em aberto há 30 dias ou mais.`);
  const crit = ind.pendencias_criticas;
  if (crit.disponivel && crit.valor) achados.push(`${crit.valor} título(s) vencido(s) também têm inconsistência não resolvida (pendência crítica).`);
  const mensal = g.inconsistencias_mensal_vencimento;
  if (mensal.length >= 2) {
    const [a, b] = mensal.slice(-2);
    achados.push(`Inconsistências por mês de vencimento: ${a.rotulo} = ${a.valor}, ${b.rotulo} = ${b.valor}.`);
  } else if (mensal.length) achados.push("Há dados de apenas um mês: ainda não dá para comparar a evolução entre períodos.");
  if (!achados.length) achados.push("Nada relevante nos filtros atuais.");
  return achados;
}
