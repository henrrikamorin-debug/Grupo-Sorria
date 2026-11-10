// Animações discretas para o painel (principalmente na TV): números que sobem até o
// valor, barras e colunas que crescem, linhas da tabela que entram, um brilho que
// passa pelos indicadores e, de vez em quando, algumas notas de dinheiro subindo.
//
// Só usa transform e opacity (leve para a TV). Desligadas com ?animacoes=0 ou
// quando o sistema pede menos movimento (prefers-reduced-motion).
// Nenhuma animação altera ou esconde um valor: o número final é sempre o real.

const reduzido = window.matchMedia?.("(prefers-reduced-motion: reduce)");

export function animacoesLigadas() {
  if (new URL(location.href).searchParams.get("animacoes") === "0") return false;
  return !(reduzido && reduzido.matches);
}

// ------------------------------------------------------------------ números
const facilitar = (t) => 1 - Math.pow(1 - t, 3);

/**
 * Mostra ``valor`` em ``el`` contando a partir do último valor exibido (ou de zero).
 * ``formatar(n)`` devolve o HTML do número. Sem animação, escreve direto.
 */
export function contar(el, valor, formatar, { duracao = 1400 } = {}) {
  const anterior = el.dataset.valor === undefined ? null : Number(el.dataset.valor);
  el.dataset.valor = String(valor);
  cancelAnimationFrame(Number(el.dataset.quadro || 0));
  if (!animacoesLigadas() || anterior === valor || !Number.isFinite(valor)) {
    el.innerHTML = formatar(valor);
    return;
  }
  const inicio = anterior ?? 0;
  const t0 = performance.now();
  const passo = (agora) => {
    const t = Math.min(1, (agora - t0) / duracao);
    el.innerHTML = formatar(t < 1 ? Math.round(inicio + (valor - inicio) * facilitar(t)) : valor);
    if (t < 1) el.dataset.quadro = String(requestAnimationFrame(passo));
  };
  el.dataset.quadro = String(requestAnimationFrame(passo));
  if (anterior !== null) destacar(el.closest(".indicador"));
}

/** Pulso dourado curto num cartão cujo valor mudou. */
export function destacar(el) {
  if (!el || !animacoesLigadas()) return;
  el.classList.remove("mudou");
  void el.offsetWidth; // reinicia a animação
  el.classList.add("mudou");
}

// ------------------------------------------------------------------ entradas
/** Reinicia a animação de entrada (barras, colunas, linhas) de um contêiner. */
export function entrar(container) {
  if (!container || !animacoesLigadas()) return;
  container.classList.remove("animar-entrada");
  void container.offsetWidth;
  container.classList.add("animar-entrada");
}

// ------------------------------------------------------------------ brilho
let brilhoTimer = null;
/** Faixa de luz que atravessa os indicadores e as barras a cada ``segundos``. */
export function iniciarBrilho(segundos = 25) {
  clearInterval(brilhoTimer);
  if (!animacoesLigadas()) return;
  brilhoTimer = setInterval(() => {
    if (document.hidden) return;
    document.querySelectorAll(".indicador, .barras").forEach((el, i) => {
      setTimeout(() => {
        el.classList.remove("brilho");
        void el.offsetWidth;
        el.classList.add("brilho");
      }, i * 180);
    });
  }, segundos * 1000);
}

// ------------------------------------------------------------------ dinheiro voando
const NOTA = `<svg viewBox="0 0 64 34" aria-hidden="true"><rect x="1" y="1" width="62" height="32" rx="4"
  fill="#1d2a1f" stroke="#d4b56c" stroke-width="1.5"/><rect x="5" y="5" width="54" height="24" rx="2" fill="none"
  stroke="#b08d40" stroke-width="0.8" opacity=".7"/><circle cx="32" cy="17" r="8" fill="none" stroke="#d4b56c"
  stroke-width="1.2"/><text x="32" y="21" text-anchor="middle" font-size="10" font-weight="700" fill="#d4b56c"
  font-family="Segoe UI, Arial, sans-serif">R$</text></svg>`;
const MOEDA = `<svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="14.5" fill="#b08d40"
  stroke="#f1d58e" stroke-width="1.5"/><circle cx="16" cy="16" r="10.5" fill="none" stroke="#f1d58e" stroke-width=".8"
  opacity=".8"/><text x="16" y="21" text-anchor="middle" font-size="13" font-weight="700" fill="#1a1406"
  font-family="Segoe UI, Arial, sans-serif">$</text></svg>`;

let chuvaAtiva = false;
/**
 * Algumas notas e moedas sobem pela tela por alguns segundos, por cima do painel
 * (sem bloquear cliques). Discreto: poucas peças, transparência parcial.
 */
export function dinheiroVoando({ quantidade = 14, duracao = 6000 } = {}) {
  if (!animacoesLigadas() || chuvaAtiva || document.hidden) return;
  chuvaAtiva = true;
  const camada = document.createElement("div");
  camada.className = "dinheiro-voando";
  camada.setAttribute("aria-hidden", "true");
  for (let i = 0; i < quantidade; i++) {
    const peca = document.createElement("span");
    const nota = Math.random() < 0.6;
    peca.className = nota ? "peca nota" : "peca moeda";
    peca.innerHTML = nota ? NOTA : MOEDA;
    const atraso = Math.random() * (duracao * 0.45);
    const tempo = duracao * (0.55 + Math.random() * 0.35);
    peca.style.left = `${4 + Math.random() * 92}%`;
    peca.style.setProperty("--deriva", `${(Math.random() - 0.5) * 18}vw`);
    peca.style.setProperty("--giro", `${(Math.random() - 0.5) * 70}deg`);
    peca.style.setProperty("--escala", (0.7 + Math.random() * 0.6).toFixed(2));
    peca.style.animationDuration = `${tempo}ms`;
    peca.style.animationDelay = `${atraso}ms`;
    camada.appendChild(peca);
  }
  document.body.appendChild(camada);
  setTimeout(() => { camada.remove(); chuvaAtiva = false; }, duracao + 200);
}

let chuvaTimer = null;
/** Na TV, repete o dinheiro voando a cada ``minutos``. */
export function agendarDinheiro(minutos = 4) {
  clearInterval(chuvaTimer);
  if (!animacoesLigadas()) return;
  chuvaTimer = setInterval(() => dinheiroVoando(), minutos * 60_000);
}

export function pararDinheiro() {
  clearInterval(chuvaTimer);
  chuvaTimer = null;
}

// ------------------------------------------------------------------ gráfico subindo
let linhaTimer = null;
/** Na TV, redesenha a linha do acumulado (subindo dia a dia) a cada ``segundos``. */
export function agendarLinha(segundos = 90) {
  clearInterval(linhaTimer);
  if (!animacoesLigadas()) return;
  linhaTimer = setInterval(() => {
    if (document.hidden || !document.documentElement.classList.contains("tv")) return;
    document.querySelectorAll(".colunas").forEach((svg) => {
      svg.classList.remove("redesenhar");
      void svg.getBoundingClientRect();
      svg.classList.add("redesenhar");
    });
  }, segundos * 1000);
}
