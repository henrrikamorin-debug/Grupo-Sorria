// Cálculos do painel online: porte de sorria/analise.py e sorria/exportacao.py.
// Trabalha SOMENTE sobre o retrato público e mascarado enviado pelo coletor local.
// Regra central: o valor de um lançamento é somado UMA única vez, mesmo com várias ocorrências.

export class FiltroInvalido extends Error {}

const SITUACOES = ["pendente", "em_analise", "resolvida"];
const ROTULOS_SITUACAO = { pendente: "Pendente", em_analise: "Em análise", resolvida: "Resolvida" };
const CLASSES = ["inconsistencia", "situacao_financeira", "pendencia_operacional"];
const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const DIA = 864e5;

const dUTC = (iso) => new Date(iso + "T00:00:00Z");
const isoUTC = (d) => d.toISOString().slice(0, 10);
const somaDias = (d, n) => new Date(d.getTime() + n * DIA);
const dm = (d) => `${String(d.getUTCDate()).padStart(2, "0")}/${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
const dataValida = (t) => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(t)) return false;
  const d = dUTC(t);
  return !Number.isNaN(d.getTime()) && isoUTC(d) === t; // 2026-02-30 e 2026-13-40 não passam
};

export function lerFiltros(params) {
  const valor = (n) => (params.get(n) || "").trim() || null;
  const f = { inicio: valor("inicio"), fim: valor("fim"), clinica: valor("clinica"), categoria: valor("categoria"),
    situacao: valor("situacao"), responsavel: valor("responsavel"), tipo: valor("tipo"), classe: valor("classe") };
  for (const n of ["inicio", "fim"]) {
    if (f[n] && !dataValida(f[n])) throw new FiltroInvalido(`data inválida em '${n}': ${f[n]}`);
  }
  if (f.inicio && f.fim && f.inicio > f.fim) throw new FiltroInvalido("a data inicial é posterior à final");
  if (f.situacao && !SITUACOES.includes(f.situacao) && f.situacao !== "abertas") throw new FiltroInvalido(`situação desconhecida: ${f.situacao}`);
  if (f.classe && !CLASSES.includes(f.classe)) throw new FiltroInvalido(`classe desconhecida: ${f.classe}`);
  return f;
}

function somaUnica(lista) {
  const m = new Map();
  for (const o of lista) if (!m.has(o.referencia)) m.set(o.referencia, o.valor_centavos);
  let s = 0;
  for (const v of m.values()) if (v != null) s += v;
  return [s, m.size];
}

function agrupar(lista, chave) {
  const g = new Map();
  for (const o of lista) { const k = chave(o); if (!g.has(k)) g.set(k, []); g.get(k).push(o); }
  return [...g.entries()].map(([rotulo, itens]) => {
    const [soma, lanc] = somaUnica(itens);
    return { rotulo, ocorrencias: itens.length, lancamentos: lanc, valor_centavos: soma };
  }).sort((a, b) => b.ocorrencias - a.ocorrencias || b.valor_centavos - a.valor_centavos
    || (a.rotulo < b.rotulo ? -1 : a.rotulo > b.rotulo ? 1 : 0));
}

function seriePeriodo(lista, inicioIso, fimIso) {
  const inicio = dUTC(inicioIso), fim = dUTC(fimIso);
  const dias = Math.round((fim - inicio) / DIA) + 1;
  let gran, bucket, proximo, rotulo;
  if (dias <= 31) { gran = "dia"; bucket = (d) => d; proximo = (d) => somaDias(d, 1); rotulo = dm; }
  else if (dias <= 140) { gran = "semana"; bucket = (d) => somaDias(d, -((d.getUTCDay() + 6) % 7)); proximo = (d) => somaDias(d, 7); rotulo = dm; }
  else {
    gran = "mes"; bucket = (d) => new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1));
    proximo = (d) => new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1));
    rotulo = (d) => `${MESES[d.getUTCMonth()]}/${String(d.getUTCFullYear()).slice(2)}`;
  }
  const por = new Map();
  for (const o of lista) { const k = isoUTC(bucket(dUTC(o.data))); if (!por.has(k)) por.set(k, []); por.get(k).push(o); }
  const serie = [];
  for (let atual = bucket(inicio); atual <= fim; atual = proximo(atual)) {
    const itens = por.get(isoUTC(atual)) || [];
    const [soma, lanc] = somaUnica(itens);
    const fimB = new Date(Math.min(somaDias(proximo(atual), -1), fim));
    serie.push({ rotulo: rotulo(atual), inicio: isoUTC(new Date(Math.max(atual, inicio))), fim: isoUTC(fimB),
      ocorrencias: itens.length, lancamentos: lanc, valor_centavos: soma });
  }
  return { granularidade: gran, serie };
}

function passa(f, data, clinica, categoria, responsavel) {
  return (!f.inicio || data >= f.inicio) && (!f.fim || data <= f.fim) && (!f.clinica || clinica === f.clinica)
    && (!f.categoria || categoria === f.categoria) && (!f.responsavel || responsavel === f.responsavel);
}

function filtrarOcorrencias(snapshot, f) {
  return snapshot.ocorrencias.filter((o) => passa(f, o.data, o.clinica, o.categoria, o.responsavel)
    && (!f.situacao || (f.situacao === "abertas" ? o.situacao !== "resolvida" : o.situacao === f.situacao)) && (!f.tipo || o.regra_codigo === f.tipo) && (!f.classe || o.classe === f.classe));
}

export function montarPainel(snapshot, params) {
  const f = lerFiltros(params);
  const lista = filtrarOcorrencias(snapshot, f);
  const registros = snapshot.lancamentos.filter(([c, cat, d, r]) => passa(f, d, c, cat, r)).length;
  const [soma, afetados] = somaUnica(lista);
  const contagem = { pendente: 0, em_analise: 0, resolvida: 0 };
  const porClasse = { inconsistencia: 0, situacao_financeira: 0, pendencia_operacional: 0 };
  for (const o of lista) { contagem[o.situacao]++; porClasse[o.classe]++; }
  const per = snapshot.opcoes.periodo_disponivel || {};
  const inicio = f.inicio || per.inicio, fim = f.fim || per.fim;
  return {
    filtros: f, modo: snapshot.modo, tv: true, televisao: snapshot.televisao, situacao: snapshot.situacao,
    opcoes: snapshot.opcoes,
    // Painel online: nunca há área restrita nem desbloqueio (isso só existe no computador do escritório).
    acesso: { configurada: false, filiais: [], nomes: [], senha_definida: false, desbloqueado: false, expira_em: null },
    indicadores: {
      registros_analisados: registros, ocorrencias: lista.length, lancamentos_afetados: afetados,
      valor_associado_centavos: soma,
      lancamentos_sem_valor: new Set(lista.filter((o) => o.valor_centavos == null).map((o) => o.referencia)).size,
      pendencias: contagem.pendente + contagem.em_analise, por_situacao: contagem,
      inconsistencias: porClasse.inconsistencia, situacao_financeira: porClasse.situacao_financeira,
      pendencias_operacionais: porClasse.pendencia_operacional, resolvidas: contagem.resolvida,
      inconsistencias_pendentes: lista.filter((o) => o.classe === "inconsistencia" && o.pendencia_aberta).length,
    },
    graficos: {
      por_clinica: agrupar(lista, (o) => o.clinica),
      por_responsavel: agrupar(lista, (o) => o.responsavel || "Sem responsável definido"),
      por_categoria: agrupar(lista, (o) => o.categoria),
      por_periodo: inicio && fim ? seriePeriodo(lista, inicio, fim) : { granularidade: "dia", serie: [] },
    },
    ocorrencias: lista,
  };
}

// ------------------------------------------------------------------ CSV (Excel em português)
const CABECALHO = ["Origem dos dados", "Responsável", "Clínica", "Código da filial", "Nº do título TOTVS", "Regra",
  "Descrição", "Valor (R$)", "Valor sem repetição (R$)", "Data", "Situação", "Primeira detecção", "Tipo", "Classificação",
  "Confirmação", "Origem da informação"];

const reais = (c) => (c == null ? "" : `${c < 0 ? "-" : ""}${Math.floor(Math.abs(c) / 100)},${String(Math.abs(c) % 100).padStart(2, "0")}`);
// Evita que o Excel interprete o conteúdo como fórmula.
const seguro = (t) => { const s = t == null ? "" : String(t); return s && "=+-@\t\r".includes(s[0]) ? "'" + s : s; };
const celula = (t) => { const s = String(t); return /[;"\r\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s; };
const dataBr = (iso) => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}` : "");
function horaLocal(iso) {
  if (!iso) return "";
  const partes = Object.fromEntries(new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", day: "2-digit",
    month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(new Date(iso))
    .map((p) => [p.type, p.value]));
  return `${partes.day}/${partes.month}/${partes.year} ${partes.hour}:${partes.minute}`;
}

export function gerarCsv(snapshot, params) {
  const lista = filtrarOcorrencias(snapshot, lerFiltros(params));
  const linhas = [CABECALHO.map(celula).join(";")];
  const vistos = new Set();
  for (const o of lista) {
    const primeira = !vistos.has(o.referencia);
    vistos.add(o.referencia);
    linhas.push([
      "Coleta TOTVS", seguro(o.responsavel || ""), seguro(o.clinica), seguro(o.filial || ""),
      seguro(o.titulo || o.referencia), seguro(`${o.regra_codigo} — ${o.regra_nome}`), seguro(o.descricao),
      reais(o.valor_centavos), primeira ? reais(o.valor_centavos) : "", dataBr(o.data),
      o.situacao_rotulo || ROTULOS_SITUACAO[o.situacao] || "", horaLocal(o.primeira_deteccao),
      seguro(o.tipo), seguro((o.classificacoes || []).join(" + ")), seguro(o.confirmacao_rotulo), seguro(o.fonte),
    ].map(celula).join(";"));
  }
  return "﻿" + linhas.join("\r\n") + "\r\n";
}
