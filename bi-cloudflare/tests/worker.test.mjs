// Testes do Worker do BI com KV e ASSETS simulados em memória. Dados FICTÍCIOS.
import assert from "node:assert/strict";
import { test } from "node:test";
import worker, { saude } from "../src/worker.js";

const TOKEN = "t".repeat(40);

function kv(inicial = {}) {
  const m = new Map(Object.entries(inicial));
  return {
    async get(chave, tipo = "text") {
      if (!m.has(chave)) return null;
      const v = m.get(chave);
      if (tipo === "json") return JSON.parse(typeof v === "string" ? v : new TextDecoder().decode(v));
      if (tipo === "arrayBuffer") return typeof v === "string" ? new TextEncoder().encode(v).buffer : v;
      return typeof v === "string" ? v : new TextDecoder().decode(v);
    },
    async put(chave, valor) { m.set(chave, valor); },
    mapa: m,
  };
}

const ambiente = (dados = kv()) => ({
  DADOS: dados, MODO_PUBLICO: "true", SYNC_TOKEN: TOKEN,
  ASSETS: { fetch: async () => new Response("<html></html>", { status: 200 }) },
});

function retrato(coletaIso, extra = {}) {
  return {
    versao: 1, ambiente: "publico", modo: "real", gerado_em: new Date().toISOString(),
    ocorrencias: [], lancamentos: [], opcoes: {}, televisao: {},
    situacao: { ultima_coleta_sucesso: coletaIso ? { finalizada_em: coletaIso } : null, desatualizado: false, ...extra },
  };
}

const sincronizar = (env, corpo) => worker.fetch(new Request("https://bi.teste/sync/retrato", {
  method: "PUT", headers: { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" }, body: JSON.stringify(corpo),
}), env);

const saudeJson = async (env, agora) => (await saude(env, agora)).json();

test("saúde sem sincronização: não está ok", async () => {
  const s = await saudeJson(ambiente());
  assert.equal(s.ok, false);
  assert.match(s.motivo, /primeira sincroniza/);
});

test("saúde com coleta recente: ok; coleta velha: não ok com o motivo", async () => {
  const env = ambiente();
  const coleta = "2026-11-12T12:00:00.000Z";
  const r = await sincronizar(env, retrato(coleta));
  assert.equal(r.status, 200);
  const agora = Date.parse(coleta);
  assert.equal((await saudeJson(env, agora + 30 * 60000)).ok, true);
  const velha = await saudeJson(env, agora + 27 * 3600000);
  assert.equal(velha.ok, false);
  assert.match(velha.motivo, /Sem coleta válida do TOTVS há 27 h/);
  assert.equal(velha.ultima_coleta_sucesso, coleta);
});

test("saúde respeita 'desatualizado' do painel local", async () => {
  const env = ambiente();
  const coleta = "2026-11-12T12:00:00.000Z";
  await sincronizar(env, retrato(coleta, { desatualizado: true }));
  const s = await saudeJson(env, Date.parse(coleta) + 60000);
  assert.equal(s.ok, false);
  assert.match(s.motivo, /desatualizados/);
});

test("metadados antigos (sem a última coleta) não contam como ok", async () => {
  const env = ambiente(kv({ meta: JSON.stringify({ gerado_em: "2026-11-11T20:35:04+00:00", ocorrencias: 1, lancamentos: 1 }) }));
  const s = await saudeJson(env);
  assert.equal(s.ok, false);
  assert.match(s.motivo, /desconhecida/);
});

test("erro interno é registrado no log e responde 500 genérico", async () => {
  const dados = kv({ meta: "{}" });
  dados.get = async (chave) => { if (chave === "snapshot") throw new Error("falha simulada do KV"); return null; };
  const registros = [];
  const original = console.error;
  console.error = (...a) => registros.push(a.join(" "));
  try {
    const r = await worker.fetch(new Request("https://bi.teste/api/painel"), ambiente(dados));
    assert.equal(r.status, 500);
    assert.deepEqual(await r.json(), { erro: "erro interno" });
  } finally {
    console.error = original;
  }
  assert.equal(registros.length, 1);
  assert.match(registros[0], /erro interno GET \/api\/painel .*falha simulada do KV/);
});

test("comportamentos já existentes continuam: público só leitura e sync exige token", async () => {
  const env = ambiente();
  assert.equal((await worker.fetch(new Request("https://bi.teste/api/painel", { method: "POST" }), env)).status, 403);
  assert.equal((await worker.fetch(new Request("https://bi.teste/sync/status"), env)).status, 401);
  const restrito = retrato("2026-11-12T12:00:00.000Z");
  restrito.ocorrencias = [{ restrito: 1 }];
  assert.equal((await sincronizar(env, restrito)).status, 400);
});
