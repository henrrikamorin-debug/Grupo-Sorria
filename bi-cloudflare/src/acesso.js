// Controle de acesso do painel online. Regra de ouro: NEGAR por padrão.
//
// * Pessoas: só entram com um JWT válido do Cloudflare Access (cabeçalho Cf-Access-Jwt-Assertion), emitido
//   para ESTE aplicativo (aud) e para um e-mail da lista ALLOWED_EMAILS. Sem Access configurado ou sem lista
//   de e-mails, nada é servido (503) — não existe acesso anônimo nem "modo aberto".
// * Sincronização do coletor local: só com o token secreto SYNC_TOKEN (comparação em tempo constante).
//   Esse caminho (/sync/*) só aceita gravar o retrato; não lê dados.

const TOLERANCIA_RELOGIO = 60; // segundos
let cacheChaves = { team: null, ate: 0, chaves: null };

const decodificarB64Url = (s) => {
  const b = atob(s.replaceAll("-", "+").replaceAll("_", "/").padEnd(Math.ceil(s.length / 4) * 4, "="));
  return Uint8Array.from(b, (c) => c.charCodeAt(0));
};
const lerJson = (s) => JSON.parse(new TextDecoder().decode(decodificarB64Url(s)));

export function listaDeEmails(env) {
  return String(env.ALLOWED_EMAILS || "").split(/[,;\s]+/).map((e) => e.trim().toLowerCase()).filter(Boolean);
}

export function emailPermitido(email, lista) {
  const e = String(email || "").toLowerCase();
  // Entrada "@dominio.com" só vale se foi escrita explicitamente na lista; e-mail exato é o padrão.
  return !!e && lista.some((p) => (p.startsWith("@") ? e.endsWith(p) && e.indexOf("@") === e.lastIndexOf("@") : e === p));
}

async function chavesDoTime(team, buscar = fetch) {
  const agora = Date.now();
  if (cacheChaves.team === team && cacheChaves.ate > agora && cacheChaves.chaves) return cacheChaves.chaves;
  const r = await buscar(`https://${team}/cdn-cgi/access/certs`);
  if (!r.ok) throw new Error("chaves do Access indisponíveis");
  const { keys } = await r.json();
  cacheChaves = { team, ate: agora + 10 * 60_000, chaves: keys };
  return keys;
}

export function limparCacheDeChaves() { cacheChaves = { team: null, ate: 0, chaves: null }; }

/** Valida o JWT do Access. Devolve { email } ou lança Error (qualquer falha = negar). */
export async function validarJwtAccess(token, env, agoraMs = Date.now(), buscar = fetch) {
  const partes = String(token || "").split(".");
  if (partes.length !== 3) throw new Error("token ausente ou malformado");
  const cabecalho = lerJson(partes[0]);
  const corpo = lerJson(partes[1]);
  if (cabecalho.alg !== "RS256") throw new Error("algoritmo não aceito");
  const team = String(env.ACCESS_TEAM_DOMAIN).toLowerCase();
  const chave = (await chavesDoTime(team, buscar)).find((k) => k.kid === cabecalho.kid);
  if (!chave) throw new Error("chave desconhecida");
  const publica = await crypto.subtle.importKey("jwk", chave, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
  const ok = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", publica, decodificarB64Url(partes[2]),
    new TextEncoder().encode(`${partes[0]}.${partes[1]}`));
  if (!ok) throw new Error("assinatura inválida");
  const agora = Math.floor(agoraMs / 1000);
  if (corpo.iss !== `https://${team}`) throw new Error("emissor inválido");
  const aud = Array.isArray(corpo.aud) ? corpo.aud : [corpo.aud];
  if (!aud.includes(env.ACCESS_AUD)) throw new Error("aplicativo inválido");
  if (!corpo.exp || corpo.exp + TOLERANCIA_RELOGIO < agora) throw new Error("token expirado");
  if (corpo.nbf && corpo.nbf - TOLERANCIA_RELOGIO > agora) throw new Error("token ainda não válido");
  if (!corpo.email) throw new Error("token sem e-mail (service token não entra no painel)");
  return { email: String(corpo.email).toLowerCase() };
}

/** Decide o acesso de uma pessoa. { ok:true, email } ou { ok:false, status, motivo }. */
export async function autorizarPessoa(request, env, agoraMs = Date.now(), buscar = fetch) {
  if (!env.ACCESS_TEAM_DOMAIN || !env.ACCESS_AUD) {
    return { ok: false, status: 503, motivo: "Acesso ainda não configurado. O painel está bloqueado." };
  }
  const lista = listaDeEmails(env);
  if (!lista.length) {
    return { ok: false, status: 503, motivo: "Nenhum usuário autorizado foi cadastrado. O painel está bloqueado." };
  }
  const token = request.headers.get("Cf-Access-Jwt-Assertion");
  if (!token) return { ok: false, status: 401, motivo: "Autenticação necessária." };
  try {
    const { email } = await validarJwtAccess(token, env, agoraMs, buscar);
    if (!emailPermitido(email, lista)) return { ok: false, status: 403, motivo: "Usuário sem autorização para este painel." };
    return { ok: true, email };
  } catch {
    return { ok: false, status: 403, motivo: "Credencial inválida." };
  }
}

async function digest(texto) {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(texto)));
}

/** Token de sincronização do coletor local, em tempo constante. */
export async function autorizarSync(request, env) {
  if (!env.SYNC_TOKEN || String(env.SYNC_TOKEN).length < 32) {
    return { ok: false, status: 503, motivo: "Sincronização não configurada." };
  }
  const m = /^Bearer (.+)$/.exec(request.headers.get("Authorization") || "");
  if (!m) return { ok: false, status: 401, motivo: "Credencial ausente." };
  const [a, b] = await Promise.all([digest(m[1]), digest(String(env.SYNC_TOKEN))]);
  let diferenca = 0;
  for (let i = 0; i < a.length; i++) diferenca |= a[i] ^ b[i];
  return diferenca === 0 ? { ok: true } : { ok: false, status: 403, motivo: "Credencial inválida." };
}
