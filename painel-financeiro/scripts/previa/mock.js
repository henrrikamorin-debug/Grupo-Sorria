// PRÉVIA ESTÁTICA: simula a API local no navegador, com os mesmos cálculos do servidor.
const PREVIA = __DADOS__;
// Dados fictícios: as datas são deslocadas para hoje, para os atalhos de período continuarem úteis.
(function deslocarDatas() {
  const gerado = PREVIA.opcoes.periodo_disponivel.fim;
  const hoje = new Date(); const hojeIso = `${hoje.getFullYear()}-${String(hoje.getMonth() + 1).padStart(2, "0")}-${String(hoje.getDate()).padStart(2, "0")}`;
  const delta = Math.round((new Date(hojeIso + "T00:00:00Z") - new Date(gerado + "T00:00:00Z")) / 864e5);
  if (!delta) return;
  const mover = (iso) => new Date(new Date(iso + "T00:00:00Z").getTime() + delta * 864e5).toISOString().slice(0, 10);
  const moverBr = (t) => t.replace(/\b(\d{2})\/(\d{2})\/(\d{4})\b/g, (_, d, m, a) => { const n = mover(`${a}-${m}-${d}`); return `${n.slice(8)}/${n.slice(5, 7)}/${n.slice(0, 4)}`; });
  for (const lista of [PREVIA.normal, PREVIA.tv]) for (const o of lista) {
    o.data = mover(o.data);
    (o.evidencia.itens || []).forEach((i) => { i.valor = moverBr(String(i.valor)); });
  }
  PREVIA.lancamentos.forEach((l) => { l[2] = mover(l[2]); });
  PREVIA.opcoes.periodo_disponivel = { inicio: mover(PREVIA.opcoes.periodo_disponivel.inicio), fim: hojeIso };
})();
PREVIA.situacao.titulo = "Prévia publicada — demonstração";
PREVIA.situacao.detalhe = "Página estática com dados fictícios. Não há coleta: nenhum dado vem do TOTVS.";
PREVIA.situacao.agendador_ativo = false;
PREVIA.situacao.proxima_coleta_prevista = null;
function somaUnica(lista) {
  const m = new Map();
  lista.forEach((o) => { if (!m.has(o.referencia)) m.set(o.referencia, o.valor_centavos); });
  let s = 0; m.forEach((v) => { if (v != null) s += v; });
  return [s, m.size];
}
function agrupar(lista, chave) {
  const g = new Map();
  lista.forEach((o) => { const k = chave(o); if (!g.has(k)) g.set(k, []); g.get(k).push(o); });
  return [...g.entries()].map(([rotulo, itens]) => {
    const [soma, lanc] = somaUnica(itens);
    return { rotulo, ocorrencias: itens.length, lancamentos: lanc, valor_centavos: soma };
  }).sort((a, b) => b.ocorrencias - a.ocorrencias || b.valor_centavos - a.valor_centavos || a.rotulo.localeCompare(b.rotulo));
}
const dUTC = (iso) => new Date(iso + "T00:00:00Z");
const isoUTC = (d) => d.toISOString().slice(0, 10);
const somaDias = (d, n) => new Date(d.getTime() + n * 864e5);
const MESES = ["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"];
const dm = (d) => `${String(d.getUTCDate()).padStart(2, "0")}/${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
function seriePeriodo(lista, inicioIso, fimIso) {
  const inicio = dUTC(inicioIso), fim = dUTC(fimIso);
  const dias = Math.round((fim - inicio) / 864e5) + 1;
  let gran, bucket, proximo, rotulo;
  if (dias <= 31) { gran = "dia"; bucket = (d) => d; proximo = (d) => somaDias(d, 1); rotulo = dm; }
  else if (dias <= 140) { gran = "semana"; bucket = (d) => somaDias(d, -((d.getUTCDay() + 6) % 7)); proximo = (d) => somaDias(d, 7); rotulo = dm; }
  else { gran = "mes"; bucket = (d) => new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1));
    proximo = (d) => new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1));
    rotulo = (d) => `${MESES[d.getUTCMonth()]}/${String(d.getUTCFullYear()).slice(2)}`; }
  const por = new Map();
  lista.forEach((o) => { const k = isoUTC(bucket(dUTC(o.data))); if (!por.has(k)) por.set(k, []); por.get(k).push(o); });
  const serie = []; let atual = bucket(inicio);
  while (atual <= fim) {
    const itens = por.get(isoUTC(atual)) || []; const [soma, lanc] = somaUnica(itens);
    const fimB = new Date(Math.min(somaDias(proximo(atual), -1), fim));
    serie.push({ rotulo: rotulo(atual), inicio: isoUTC(new Date(Math.max(atual, inicio))), fim: isoUTC(fimB),
      ocorrencias: itens.length, lancamentos: lanc, valor_centavos: soma });
    atual = proximo(atual);
  }
  return { granularidade: gran, serie };
}
function painelPrevia(p) {
  const f = { inicio: p.get("inicio") || null, fim: p.get("fim") || null, clinica: p.get("clinica") || null,
    categoria: p.get("categoria") || null, situacao: p.get("situacao") || null };
  const tv = p.get("tv") === "1";
  const passa = (data, clinica, categoria) => (!f.inicio || data >= f.inicio) && (!f.fim || data <= f.fim) &&
    (!f.clinica || clinica === f.clinica) && (!f.categoria || categoria === f.categoria);
  const registros = PREVIA.lancamentos.filter(([c, cat, d]) => passa(d, c, cat)).length;
  const lista = (tv ? PREVIA.tv : PREVIA.normal).filter((o) => passa(o.data, o.clinica, o.categoria) && (!f.situacao || o.situacao === f.situacao));
  const [soma, afetados] = somaUnica(lista);
  const cont = { pendente: 0, em_analise: 0, resolvida: 0 }; lista.forEach((o) => cont[o.situacao]++);
  const per = PREVIA.opcoes.periodo_disponivel;
  return {
    filtros: f, modo: "demonstracao", tv, televisao: PREVIA.televisao, situacao: PREVIA.situacao, opcoes: PREVIA.opcoes,
    indicadores: { registros_analisados: registros, ocorrencias: lista.length, lancamentos_afetados: afetados,
      valor_associado_centavos: soma, lancamentos_sem_valor: new Set(lista.filter((o) => o.valor_centavos == null).map((o) => o.referencia)).size,
      pendencias: cont.pendente + cont.em_analise, por_situacao: cont },
    graficos: { por_clinica: agrupar(lista, (o) => o.clinica), por_categoria: agrupar(lista, (o) => o.categoria),
      por_periodo: seriePeriodo(lista, f.inicio || per.inicio, f.fim || per.fim) },
    ocorrencias: lista,
  };
}
const respostaJson = (corpo, status = 200) => new Response(JSON.stringify(corpo), { status, headers: { "Content-Type": "application/json" } });
window.fetch = async (endereco) => {
  const u = new URL(endereco, "http://previa.local");
  if (u.pathname === "/api/painel") return respostaJson(painelPrevia(u.searchParams));
  return respostaJson({ erro: "indisponível na prévia estática — rode o serviço local para usar esta ação" }, 503);
};
function baixarCsvPrevia() {
  alert("Na prévia estática a exportação CSV não está disponível. Rode o serviço local (scripts/iniciar) para exportar.");
}
