// Painel Financeiro — Grupo Sorria: painel ONLINE (Cloudflare Worker), somente leitura.
//
// O coletor do TOTVS e o banco ficam no computador do escritório. Este Worker só guarda o último retrato
// PÚBLICO e MASCARADO enviado por esse computador (PUT /sync/snapshot) e o exibe a quem o Cloudflare Access
// autorizar. A área restrita do escritório nunca chega aqui. Ver docs/NUVEM.md.

import { autorizarPessoa, autorizarSync } from "./acesso.js";
import * as BI from "./bi.js";
import { FiltroInvalido, gerarCsv, montarPainel } from "./painel.js";
import { gerarRelatorio } from "./xlsx.js";

const CHAVE_SNAPSHOT = "snapshot";
// Cópia compactada (gzip) do mesmo retrato e um resumo mínimo: o navegador baixa o retrato e faz os filtros
// localmente, então a hora da última atualização vem de um valor pequeno e barato de ler.
const CHAVE_RETRATO_GZ = "retrato_gz";
const CHAVE_META = "meta";
const LIMITE_CORPO = 20 * 1024 * 1024;
const POLITICA_CONTEUDO = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
  + "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'";

const CABECALHOS_SEGUROS = {
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "Content-Security-Policy": POLITICA_CONTEUDO,
  "X-Robots-Tag": "noindex, nofollow",
  "Strict-Transport-Security": "max-age=31536000",
};

function resposta(corpo, status = 200, tipo = "application/json; charset=utf-8", extras = {}) {
  return new Response(typeof corpo === "string" || corpo instanceof ArrayBuffer ? corpo : JSON.stringify(corpo), {
    status, headers: { "Content-Type": tipo, ...CABECALHOS_SEGUROS, ...extras },
  });
}
const erro = (status, mensagem) => resposta({ erro: mensagem }, status);

function paginaBloqueada(status, motivo) {
  const html = `<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">`
    + `<title>Acesso bloqueado</title><body style="font-family:system-ui;margin:3rem auto;max-width:34rem;padding:0 1rem">`
    + `<h1>Acesso bloqueado</h1><p>${motivo}</p></body></html>`;
  return resposta(html, status, "text/html; charset=utf-8");
}

/** Corpo bruto como foi enviado (para guardar o gzip sem recompactar) e o texto JSON descompactado. */
async function lerCorpo(request) {
  const tamanho = Number(request.headers.get("Content-Length") || 0);
  if (tamanho > LIMITE_CORPO) throw new Error("corpo muito grande");
  if (!request.body) throw new Error("corpo ausente");
  const bruto = await request.arrayBuffer();
  if (bruto.byteLength > LIMITE_CORPO) throw new Error("corpo muito grande");
  const gzip = (request.headers.get("Content-Encoding") || "").toLowerCase() === "gzip";
  const texto = gzip
    ? await new Response(new Blob([bruto]).stream().pipeThrough(new DecompressionStream("gzip"))).text()
    : new TextDecoder().decode(bruto);
  if (texto.length > LIMITE_CORPO) throw new Error("corpo muito grande");
  return { bruto, gzip, texto };
}

async function compactar(texto) {
  return new Response(new Blob([texto]).stream().pipeThrough(new CompressionStream("gzip"))).arrayBuffer();
}

/** Forma mínima do retrato e defesa extra: ocorrência marcada como restrita nunca é guardada. */
export function validarSnapshot(s, ambiente = "publico") {
  if (!s || s.versao !== 1) throw new Error("versão de retrato desconhecida");
  // Cada ambiente só aceita o retrato que lhe pertence: o público nunca recebe o privado e vice-versa.
  if ((s.ambiente ?? "publico") !== ambiente) throw new Error(`retrato não pertence ao ambiente ${ambiente}`);
  for (const c of ["ocorrencias", "lancamentos"]) if (!Array.isArray(s[c])) throw new Error(`campo ${c} ausente`);
  for (const c of ["opcoes", "situacao", "televisao"]) if (!s[c] || typeof s[c] !== "object") throw new Error(`campo ${c} ausente`);
  if (ambiente === "privado") {
    if (s.ocorrencias.some((o) => o.restrito === 0)) throw new Error("retrato privado contém ocorrência pública");
  } else if (s.ocorrencias.some((o) => o.restrito)) throw new Error("retrato contém ocorrência restrita");
  if (s.modo !== "real") throw new Error("somente retratos do modo real são aceitos");
}

const ambienteDe = (env) => (String(env.AMBIENTE) === "privado" ? "privado" : "publico");

async function sincronizar(request, env) {
  const auth = await autorizarSync(request, env);
  if (!auth.ok) return erro(auth.status, auth.motivo);
  if (request.method === "GET" && new URL(request.url).pathname === "/sync/status") {
    const meta = JSON.parse((await env.DADOS.get(CHAVE_META, "text")) || "null")
      ?? (await env.DADOS.get(CHAVE_SNAPSHOT, "json")); // antes da primeira sincronização com o resumo
    return resposta({ ok: true, gerado_em: meta?.gerado_em ?? null, ocorrencias: meta?.ocorrencias?.length ?? meta?.ocorrencias ?? 0,
      lancamentos: meta?.lancamentos?.length ?? meta?.lancamentos ?? 0 });
  }
  if (request.method !== "PUT") return erro(405, "método não permitido");
  let snapshot, corpo;
  try {
    corpo = await lerCorpo(request);
    snapshot = JSON.parse(corpo.texto);
    validarSnapshot(snapshot, ambienteDe(env));
  } catch (e) {
    return erro(400, `retrato recusado: ${e.message}`);
  }
  // O JSON validado é guardado como veio (sem reserializar) e em gzip para o navegador.
  await env.DADOS.put(CHAVE_SNAPSHOT, corpo.texto);
  await env.DADOS.put(CHAVE_RETRATO_GZ, corpo.gzip ? corpo.bruto : await compactar(corpo.texto));
  await env.DADOS.put(CHAVE_META, JSON.stringify({ gerado_em: snapshot.gerado_em, ocorrencias: snapshot.ocorrencias.length,
    lancamentos: snapshot.lancamentos.length,
    // Para /api/saude: "gerado_em" muda a cada publicação, mesmo quando a coleta do TOTVS falhou; o que importa é a última coleta válida.
    ultima_coleta_sucesso: snapshot.situacao?.ultima_coleta_sucesso?.finalizada_em ?? null,
    desatualizado: snapshot.situacao?.desatualizado ?? null }));
  return resposta({ ok: true, gerado_em: snapshot.gerado_em, ocorrencias: snapshot.ocorrencias.length,
    lancamentos: snapshot.lancamentos.length });
}

async function servirArquivo(request, env, caminhoAsset) {
  const url = new URL(request.url);
  url.pathname = caminhoAsset;
  const r = await env.ASSETS.fetch(new Request(url, { method: "GET" }));
  if (!r.ok) return erro(404, "não encontrado");
  const cabecalhos = new Headers(r.headers);
  for (const [k, v] of Object.entries(CABECALHOS_SEGUROS)) cabecalhos.set(k, v);
  return new Response(r.body, { status: 200, headers: cabecalhos });
}

const TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

/** BI: mesmas rotas do painel local, calculadas sobre o retrato guardado. */
async function apiBi(caminho, url, env) {
  const snapshot = await env.DADOS.get(CHAVE_SNAPSHOT, "json");
  if (!snapshot) return erro(503, "Aguardando a primeira sincronização com o computador do escritório.");
  if (!Array.isArray(snapshot.bi_lancamentos)) return erro(503, "O retrato guardado ainda não tem os dados do BI. Aguarde a próxima sincronização.");
  const p = url.searchParams;
  try {
    const res = BI.montar(snapshot, BI.lerFiltros(p));
    const inteiro = (n, padrao) => (/^\d+$/.test(p.get(n) || "") ? Number(p.get(n)) : padrao);
    if (caminho === "/api/bi/resumo") return resposta({ ...res, analise: BI.analiseAutomatica(res), modo: snapshot.modo });
    if (caminho === "/api/bi/registros") {
      return resposta(BI.tabela(res._conj, p.get("indicador") || "", { busca: (p.get("q") || "").trim(), pagina: inteiro("pagina", 1), porPagina: inteiro("por_pagina", 25) }));
    }
    if (caminho === "/api/bi/clinica") {
      const clinica = p.get("detalhe") || "";
      if (!clinica || !res._lancs.some((l) => l.clinica === clinica)) return erro(404, "clínica não encontrada nos filtros atuais");
      const lanc = BI.tabela({ lancamentos: res._lancs.filter((l) => l.clinica === clinica) }, "lancamentos", { porPagina: 200 });
      const ocs = BI.tabela({ ocorrencias: res._ocs.filter((o) => o.clinica === clinica) }, "ocorrencias", { porPagina: 200 });
      return resposta({ ...BI.detalheClinica(res._lancs, res._ocs, clinica), tabela_lancamentos: lanc, tabela_ocorrencias: ocs });
    }
    if (caminho === "/api/bi/relatorio.xlsx") {
      const { conteudo, nome } = gerarRelatorio(res, p.get("tipo") || "");
      return new Response(conteudo, { status: 200, headers: { "Content-Type": TIPO_XLSX, ...CABECALHOS_SEGUROS,
        "Content-Disposition": `attachment; filename="${nome}"` } });
    }
  } catch (e) {
    if (e instanceof BI.FiltroInvalido) return erro(400, e.message);
    throw e;
  }
  return erro(404, "não encontrado");
}

/** Retrato público e mascarado, compactado, para o navegador calcular filtros, tabelas e relatórios sem novas chamadas. */
async function servirRetrato(caminho, env) {
  if (caminho === "/api/retrato/meta") {
    const meta = await env.DADOS.get(CHAVE_META, "text");
    return resposta(meta || JSON.stringify({ gerado_em: null }));
  }
  const gz = await env.DADOS.get(CHAVE_RETRATO_GZ, "arrayBuffer");
  if (gz) {
    // O corpo já está em gzip: "manual" impede o runtime de compactar de novo (viraria gzip duplo e ilegível).
    return new Response(gz, { status: 200, encodeBody: "manual", headers: { "Content-Type": "application/json; charset=utf-8",
      "Content-Encoding": "gzip", ...CABECALHOS_SEGUROS } });
  }
  const texto = await env.DADOS.get(CHAVE_SNAPSHOT, "text"); // antes da primeira sincronização com a cópia compactada
  return texto ? resposta(texto) : erro(503, "Aguardando a primeira sincronização com o computador do escritório.");
}

// Mesmo limite do painel local (agente.tolerancia_desatualizacao_horas).
const LIMITE_DESATUALIZACAO_MIN = 26 * 60;

/** Saúde real para monitoramento: dados sincronizados e coleta do TOTVS recente. Responde 200 sempre; "ok" diz se está em dia. */
export async function saude(env, agoraMs = Date.now()) {
  const base = { online: true, modo: "real", calculo_no_navegador: true };
  const meta = JSON.parse((await env.DADOS.get(CHAVE_META, "text")) || "null");
  if (!meta?.gerado_em) return resposta({ ...base, ok: false, motivo: "Aguardando a primeira sincronização." });
  const coleta = meta.ultima_coleta_sucesso ?? null;
  const minutos = coleta ? Math.round((agoraMs - Date.parse(coleta)) / 60000) : null;
  const motivo = !coleta ? "Última coleta válida desconhecida (aguarde a próxima sincronização)."
    : minutos > LIMITE_DESATUALIZACAO_MIN ? `Sem coleta válida do TOTVS há ${Math.floor(minutos / 60)} h.`
    : meta.desatualizado === true ? "O painel local marcou os dados como desatualizados." : null;
  return resposta({ ...base, ok: !motivo, ...(motivo ? { motivo } : {}), gerado_em: meta.gerado_em,
    ultima_coleta_sucesso: coleta, minutos_desde_coleta: minutos });
}

async function api(caminho, url, env) {
  if (caminho === "/api/retrato" || caminho === "/api/retrato/meta") return servirRetrato(caminho, env);
  if (caminho.startsWith("/api/bi/")) return apiBi(caminho, url, env);
  if (caminho === "/api/saude") return saude(env);
  if (caminho === "/api/acesso") {
    return resposta({ configurada: false, filiais: [], nomes: [], senha_definida: false, desbloqueado: false, expira_em: null });
  }
  if (caminho === "/api/relatorios") return resposta({ relatorios: [], mes_anterior: null, automatico: false });
  if (caminho === "/api/regras") return resposta({ modo: "real", regras: [] });
  const snapshot = await env.DADOS.get(CHAVE_SNAPSHOT, "json");
  if (!snapshot) return erro(503, "Aguardando a primeira sincronização com o computador do escritório.");
  try {
    if (caminho === "/api/painel") return resposta(montarPainel(snapshot, url.searchParams));
    if (caminho === "/api/situacao") return resposta(snapshot.situacao);
    if (caminho === "/api/ocorrencias.csv") {
      const nome = `ocorrencias_${new Date().toISOString().slice(0, 10)}.csv`;
      return resposta(gerarCsv(snapshot, url.searchParams), 200, "text/csv; charset=utf-8",
        { "Content-Disposition": `attachment; filename="${nome}"` });
    }
  } catch (e) {
    if (e instanceof FiltroInvalido) return erro(400, e.message);
    throw e;
  }
  return erro(404, "não encontrado");
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const caminho = url.pathname;

    // Coletor local: caminho próprio, token próprio; não lê dados.
    if (caminho.startsWith("/sync/")) return sincronizar(request, env);

    // Modo público (MODO_PUBLICO = "true"): só LEITURA (GET/HEAD) de rotas conhecidas, sem login. O retrato
    // guardado já é público e mascarado. Qualquer outro método vai para a negação padrão abaixo.
    const leitura = request.method === "GET" || request.method === "HEAD";
    const modoPublico = String(env.MODO_PUBLICO) === "true" && ambienteDe(env) !== "privado";
    const publico = modoPublico && leitura;
    if (modoPublico && !leitura) {
      return erro(403, "Painel online somente leitura: ações (coleta, situação, desbloqueio) só no computador do escritório.");
    }

    // Fora do modo público, exige uma pessoa autorizada pelo Cloudflare Access (e confirmada aqui). Negar por padrão.
    const acesso = publico ? { ok: true } : await autorizarPessoa(request, env);
    if (!acesso.ok) {
      return caminho.startsWith("/api/") ? erro(acesso.status, acesso.motivo) : paginaBloqueada(acesso.status, acesso.motivo);
    }

    if (!leitura) {
      return erro(403, "Painel online somente leitura: ações (coleta, situação, desbloqueio) só no computador do escritório.");
    }
    try {
      if (caminho === "/" || caminho === "/index.html") return await servirArquivo(request, env, "/index.html");
      if (caminho === "/bi" || caminho === "/bi.html") return await servirArquivo(request, env, "/bi.html");
      // Demonstração: as mesmas páginas, alimentadas por um retrato fictício estático (nunca pelo retrato real).
      if (caminho === "/demo") return await servirArquivo(request, env, "/index.html");
      if (caminho === "/demo/bi") return await servirArquivo(request, env, "/bi.html");
      if (caminho.startsWith("/static/")) {
        const relativo = caminho.slice("/static".length);
        if (!/^[\w\-./]+$/.test(relativo) || relativo.includes("..")) return erro(404, "não encontrado");
        return await servirArquivo(request, env, relativo);
      }
      if (caminho.startsWith("/api/")) return await api(caminho, url, env);
      return erro(404, "não encontrado");
    } catch (e) {
      // Registra no Workers Logs (só método, caminho e pilha, sem dados); antes o erro sumia e o painel não acusava nada.
      console.error("erro interno", request.method, caminho, e?.stack || String(e));
      return erro(500, "erro interno");
    }
  },
};
