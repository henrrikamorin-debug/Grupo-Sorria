// Gerador mínimo de .xlsx (Open XML) para o Worker: porte de sorria/xlsx.py + relatórios de sorria/bi_relatorios.py.
// O ZIP é gravado sem compressão (método "store"), o que o Excel aceita e dispensa bibliotecas.

import { FiltroInvalido, tabela } from "./bi.js";

const enc = new TextEncoder();
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const ILEGAIS = /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g;

const TABELA_CRC = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; }
  return t;
})();
const crc32 = (bytes) => { let c = 0xffffffff; for (const b of bytes) c = TABELA_CRC[(c ^ b) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };

function zip(arquivos) {
  const partes = [], central = [];
  let deslocamento = 0;
  const u16 = (v) => [v & 255, (v >>> 8) & 255];
  const u32 = (v) => [v & 255, (v >>> 8) & 255, (v >>> 16) & 255, (v >>> 24) & 255];
  for (const [nome, texto] of arquivos) {
    const n = enc.encode(nome), dados = enc.encode(texto), crc = crc32(dados);
    const cab = [0x50, 0x4b, 3, 4, ...u16(20), ...u16(0x0800), ...u16(0), ...u16(0), ...u16(0x21), ...u32(crc), ...u32(dados.length), ...u32(dados.length), ...u16(n.length), ...u16(0)];
    partes.push(new Uint8Array(cab), n, dados);
    central.push(new Uint8Array([0x50, 0x4b, 1, 2, ...u16(20), ...u16(20), ...u16(0x0800), ...u16(0), ...u16(0), ...u16(0x21), ...u32(crc), ...u32(dados.length), ...u32(dados.length),
      ...u16(n.length), ...u16(0), ...u16(0), ...u16(0), ...u16(0), ...u32(0), ...u32(deslocamento)]), n);
    deslocamento += cab.length + n.length + dados.length;
  }
  const tamCentral = central.reduce((s, p) => s + p.length, 0);
  const fim = new Uint8Array([0x50, 0x4b, 5, 6, ...u16(0), ...u16(0), ...u16(arquivos.length), ...u16(arquivos.length), ...u32(tamCentral), ...u32(deslocamento), ...u16(0)]);
  const todos = [...partes, ...central, fim];
  const saida = new Uint8Array(todos.reduce((s, p) => s + p.length, 0));
  let pos = 0;
  for (const p of todos) { saida.set(p, pos); pos += p.length; }
  return saida;
}

const col = (n) => { let s = ""; n += 1; while (n) { const r = (n - 1) % 26; s = String.fromCharCode(65 + r) + s; n = Math.floor((n - 1) / 26); } return s; };
const ehNumero = (t) => t.trim() !== "" && Number.isFinite(Number(t));
const texto = (v) => { const t = String(v).replace(ILEGAIS, ""); return /^[=+\-@]/.test(t) && !ehNumero(t) ? "'" + t : t; };

function celula(ref, valor, estilo) {
  if (valor == null || valor === "") return "";
  const s = estilo ? ` s="${estilo}"` : "";
  if (typeof valor === "boolean") return `<c r="${ref}" t="inlineStr"${s}><is><t>${valor ? "Sim" : "Não"}</t></is></c>`;
  if (typeof valor === "number") return `<c r="${ref}"${s}><v>${valor}</v></c>`;
  return `<c r="${ref}" t="inlineStr"${s}><is><t xml:space="preserve">${esc(texto(valor))}</t></is></c>`;
}

function planilha(linhas, cabecalhos, moeda) {
  const larguras = [];
  for (const l of linhas) l.forEach((v, i) => { larguras[i] = Math.min(Math.max(larguras[i] || 8, String(v ?? "").length + 2), 60); });
  const cols = larguras.map((w, i) => `<col min="${i + 1}" max="${i + 1}" width="${w}" customWidth="1"/>`).join("");
  const linhasXml = linhas.map((l, r) => `<row r="${r + 1}">${l.map((v, i) => celula(`${col(i)}${r + 1}`, v, r < cabecalhos ? 1 : moeda.includes(i) ? 2 : 0)).join("")}</row>`).join("");
  const painel = cabecalhos ? `<sheetViews><sheetView workbookViewId="0"><pane ySplit="${cabecalhos}" topLeftCell="A${cabecalhos + 1}" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>` : "";
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">${painel}<cols>${cols}</cols><sheetData>${linhasXml}</sheetData></worksheet>`;
}

export function gerarXlsx(planilhas) {
  const nomes = planilhas.map((p, i) => (p.nome.replace(/[\\/?*[\]:]/g, " ").slice(0, 31) || `Planilha${i + 1}`));
  const arquivos = planilhas.map((p, i) => [`xl/worksheets/sheet${i + 1}.xml`, planilha(p.linhas, p.cabecalhos ?? 1, p.moeda || [])]);
  const H = '<?xml version="1.0" encoding="UTF-8"?>';
  const ns = "http://schemas.openxmlformats.org/";
  arquivos.push(["[Content_Types].xml", `${H}<Types xmlns="${ns}package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>${nomes.map((_, i) => `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join("")}</Types>`]);
  arquivos.push(["_rels/.rels", `${H}<Relationships xmlns="${ns}package/2006/relationships"><Relationship Id="rId1" Type="${ns}officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>`]);
  arquivos.push(["xl/workbook.xml", `${H}<workbook xmlns="${ns}spreadsheetml/2006/main" xmlns:r="${ns}officeDocument/2006/relationships"><sheets>${nomes.map((n, i) => `<sheet name="${esc(n)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join("")}</sheets></workbook>`]);
  arquivos.push(["xl/_rels/workbook.xml.rels", `${H}<Relationships xmlns="${ns}package/2006/relationships">${nomes.map((_, i) => `<Relationship Id="rId${i + 1}" Type="${ns}officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`).join("")}<Relationship Id="rId${nomes.length + 1}" Type="${ns}officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>`]);
  arquivos.push(["xl/styles.xml", `${H}<styleSheet xmlns="${ns}spreadsheetml/2006/main"><numFmts count="1"><numFmt numFmtId="164" formatCode="&quot;R$&quot; #,##0.00"/></numFmts><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/><xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>`]);
  return zip(arquivos);
}

// ------------------------------------------------------------------ relatórios (porte de bi_relatorios.py)
export const RELATORIOS = {
  geral: "Relatório geral financeiro", por_clinica: "Relatório por clínica", ocorrencias: "Relatório de ocorrências",
  inconsistencias: "Relatório de inconsistências", pendencias: "Relatório de pendências",
  titulos_em_aberto: "Relatório de títulos em aberto", titulos_vencidos: "Relatório de títulos vencidos", titulos_pendentes_baixa: "Relatório de títulos pendentes de baixa",
  titulos_sem_movimentacao: "Relatório de títulos sem movimentação", pendencias_por_ticket: "Relatório de pendências por ticket",
};
const INDICADOR = { ocorrencias: "ocorrencias", inconsistencias: "inconsistencias", pendencias: "pendencias", titulos_em_aberto: "titulos_em_aberto",
  titulos_vencidos: "titulos_vencidos", titulos_pendentes_baixa: "titulos_pendentes_baixa", titulos_sem_movimentacao: "titulos_sem_movimentacao" };
const CAMPOS_MOEDA = ["valor_centavos", "saldo_centavos", "saldo_ou_valor"];
const reais = (c) => (c == null ? null : c / 100);

const ROTULO_PERIODO = { ultimas_24h: "Últimas 24 horas", hoje: "Hoje", ontem: "Ontem", ultimos_7: "Últimos 7 dias", ultimos_15: "Últimos 15 dias",
  ultimos_30: "Últimos 30 dias", ultimos_90: "Últimos 90 dias", mes_atual: "Mês atual", mes_anterior: "Mês anterior", personalizado: "Período personalizado" };
const br = (d) => (d ? `${d.slice(8, 10)}/${d.slice(5, 7)}/${d.slice(0, 4)}` : null);

// Aba "Filtros": deixa claro o período, a data filtrada e TODOS os filtros (livres aparecem como "Todos").
function filtrosTexto(res) {
  const p = res.periodo, f = res.filtros, o = res.opcoes;
  const faixa = p.inicio || p.fim ? `${br(p.inicio) || "início"} a ${br(p.fim) || "hoje"}` : "sem período definido";
  const nome = ROTULO_PERIODO[p.periodo];
  const periodo = nome ? `${nome} (${faixa})` : faixa;
  const rotulos = { situacao: Object.fromEntries(o.situacoes.map((s) => [s.valor, s.rotulo])),
    situacao_financeira: Object.fromEntries(o.situacoes_financeiras.map((s) => [s.valor, s.rotulo])),
    tipo_ocorrencia: Object.fromEntries(o.tipos_ocorrencia.map(([c, n]) => [c, `${n} (${c})`])) };
  const valor = Object.fromEntries(res.indicadores.map((i) => [i.id, i.valor]));
  const l = [["Gerado em", p.agora], ["Fuso", p.fuso], ["Período", periodo], ["Data filtrada", p.campo_rotulo]];
  for (const [rotulo, chave, vazio] of [["Clínica", "clinica", "Todas"], ["Ticket", "ticket", "Todos"], ["Status da pendência", "situacao", "Todos"],
    ["Tipo de ocorrência", "tipo_ocorrencia", "Todos"], ["Tipo de inconsistência", "tipo_inconsistencia", "Todos"], ["Situação financeira", "situacao_financeira", "Todas"]]) {
    l.push([rotulo, f[chave] ? (rotulos[chave]?.[f[chave]] ?? f[chave]) : vazio]);
  }
  l.push(["Lançamentos na seleção", valor.lancamentos ?? null], ["Ocorrências na seleção", valor.ocorrencias ?? null]);
  return l;
}

function detalhe(conj, indicador, nome) {
  const t = tabela(conj, indicador, { porPagina: 1e9, limitar: false });
  if (!t.disponivel) return { nome, cabecalhos: 1, linhas: [["Indisponível"], [t.motivo]] };
  const moeda = t.colunas.map((c, i) => (CAMPOS_MOEDA.includes(c.campo) ? i : -1)).filter((i) => i >= 0);
  const linhas = [t.colunas.map((c) => c.rotulo)];
  for (const l of t.linhas) linhas.push(t.colunas.map((c, i) => (moeda.includes(i) ? reais(l[c.campo]) : l[c.campo])));
  return { nome, cabecalhos: 1, linhas, moeda };
}

export function gerarRelatorio(res, tipo) {
  if (!(tipo in RELATORIOS)) throw new FiltroInvalido("relatório desconhecido");
  const conj = res._conj;
  const planilhas = [{ nome: "Filtros", cabecalhos: 0, linhas: [[RELATORIOS[tipo]], ...filtrosTexto(res)] }];
  if (tipo === "geral") {
    const ind = [["Indicador", "Quantidade", "Valor (R$)", "Regra"], ...res.indicadores.map((i) => [i.rotulo, i.disponivel ? i.valor : "indisponível", reais(i.valor_centavos), i.regra])];
    planilhas.push({ nome: "Indicadores", cabecalhos: 1, linhas: ind, moeda: [2] });
    const rel = [["Comparação", "Total A", "Total B", "Em ambos", "Só em A", "Só em B", "Mesmos registros?", "Nota"],
      ...res.relacoes.map((r) => [`${r.a} × ${r.b}`, r.total_a, r.total_b, r.em_ambos, r.so_a, r.so_b, r.mesmos_registros, r.nota])];
    planilhas.push({ nome: "Relações", cabecalhos: 1, linhas: rel });
    for (const [id, nome] of [["lancamentos", "Lançamentos"], ["ocorrencias", "Ocorrências"], ["pendencias_criticas", "Críticas"]]) planilhas.push(detalhe(conj, id, nome));
  } else if (tipo === "por_clinica") {
    const linhas = [["Clínica", "Lançamentos", "Ocorrências", "Pendências em aberto", "Valor dos lançamentos (R$)", "Em aberto (R$)", "Vencido (R$)"],
      ...res.graficos.ocorrencias_x_lancamentos.map((c) => [c.rotulo, c.lancamentos, c.ocorrencias, c.pendencias, reais(c.valor_centavos), reais(c.em_aberto_centavos), reais(c.vencido_centavos)])];
    planilhas.push({ nome: "Por clínica", cabecalhos: 1, linhas, moeda: [4, 5, 6] });
    planilhas.push(detalhe(conj, "ocorrencias", "Ocorrências"));
  } else if (tipo === "pendencias_por_ticket") {
    const tickets = new Map();
    for (const o of conj.pendencias) {
      if (!tickets.has(o.ticket)) tickets.set(o.ticket, { n: 0, clinicas: new Set(), antiga: 0 });
      const t = tickets.get(o.ticket);
      t.n += 1; t.clinicas.add(o.clinica); t.antiga = Math.max(t.antiga, o.dias_em_aberto || 0);
    }
    const ordenados = [...tickets].sort((a, b) => b[1].n - a[1].n || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
    planilhas.push({ nome: "Ranking de tickets", cabecalhos: 1, linhas: [["Ticket", "Pendências em aberto", "Clínicas afetadas", "Maior tempo em aberto (dias)"],
      ...ordenados.map(([k, v]) => [k, v.n, v.clinicas.size, v.antiga])] });
    planilhas.push(detalhe(conj, "pendencias", "Pendências"));
  } else {
    planilhas.push(detalhe(conj, INDICADOR[tipo], RELATORIOS[tipo]));
    if (tipo === "titulos_vencidos") planilhas.push(detalhe(conj, "pendencias_criticas", "Críticas"));
  }
  return { conteudo: gerarXlsx(planilhas), nome: `${tipo}_${res.periodo.agora.slice(0, 10)}.xlsx` };
}
