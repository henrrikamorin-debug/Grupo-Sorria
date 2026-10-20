// Formatação e utilidades de interface (pt-BR).

const moeda = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const inteiro = new Intl.NumberFormat("pt-BR");
const compacto = new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 });

export function esc(texto) {
  return String(texto ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

export const reais = (centavos) => (centavos == null ? "—" : moeda.format(centavos / 100));
export const reaisCompacto = (centavos) => "R$ " + compacto.format((centavos || 0) / 100);
export const numero = (n) => inteiro.format(n ?? 0);

export function reaisPartes(centavos) {
  const texto = reais(centavos);
  const i = texto.lastIndexOf(",");
  return i < 0 ? [texto, ""] : [texto.slice(0, i), texto.slice(i)];
}

export function dataCurta(iso) {
  if (!iso) return "—";
  const [a, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${a}`;
}

export function horaLocal(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("pt-BR", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

export function haQuanto(iso) {
  if (!iso) return "";
  const minutos = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutos < 1) return "agora há pouco";
  if (minutos < 60) return `há ${minutos} min`;
  const horas = Math.floor(minutos / 60);
  if (horas < 48) return `há ${horas} h ${minutos % 60} min`;
  return `há ${Math.floor(horas / 24)} dias`;
}

export function isoLocal(data) {
  const p = (n) => String(n).padStart(2, "0");
  return `${data.getFullYear()}-${p(data.getMonth() + 1)}-${p(data.getDate())}`;
}

export function lerPreferencia(chave, padrao) {
  try {
    const valor = localStorage.getItem("painel-sorria:" + chave);
    return valor == null ? padrao : JSON.parse(valor);
  } catch {
    return padrao;
  }
}

export function gravarPreferencia(chave, valor) {
  try {
    localStorage.setItem("painel-sorria:" + chave, JSON.stringify(valor));
  } catch {
    /* armazenamento indisponível: apenas não lembra a preferência */
  }
}
