// Gráficos simples em HTML/SVG, sem bibliotecas externas (funciona offline).
// Uma única série por gráfico (dourado); valores sempre em texto neutro.

import { esc, numero, reais, reaisCompacto } from "./formato.js";

const dica = () => document.getElementById("dica");

export function mostrarDica(evento, html) {
  const el = dica();
  el.innerHTML = html;
  el.classList.remove("oculto");
  const margem = 14;
  const { innerWidth: w, innerHeight: h } = window;
  const r = el.getBoundingClientRect();
  let x = evento.clientX + margem;
  let y = evento.clientY + margem;
  if (x + r.width > w - 8) x = evento.clientX - r.width - margem;
  if (y + r.height > h - 8) y = evento.clientY - r.height - margem;
  el.style.left = `${Math.max(8, x)}px`;
  el.style.top = `${Math.max(8, y)}px`;
}

export function esconderDica() {
  dica().classList.add("oculto");
}

function htmlDica(item) {
  return `<strong>${esc(item.rotulo)}</strong>
    <span>${numero(item.ocorrencias)} ocorrência(s) · ${numero(item.lancamentos)} lançamento(s)</span><br>
    <span>Valor associado: ${reais(item.valor_centavos)}</span>`;
}

const valorDe = (item, metrica) => (metrica === "valor" ? item.valor_centavos : item.ocorrencias);
const textoDe = (item, metrica) =>
  metrica === "valor" ? reaisCompacto(item.valor_centavos) : numero(item.ocorrencias);

/** Barras horizontais: rótulo | barra | valor. */
export function barras(container, itens, { metrica, maximo = 8, selecionado, aoClicar }) {
  if (!itens.length) {
    container.innerHTML = `<div class="estado"><strong>Sem ocorrências</strong>para os filtros atuais</div>`;
    return;
  }
  let lista = [...itens].sort((a, b) => valorDe(b, metrica) - valorDe(a, metrica));
  if (lista.length > maximo) {
    const resto = lista.slice(maximo - 1);
    lista = lista.slice(0, maximo - 1);
    lista.push({
      rotulo: `Outras (${resto.length})`,
      outras: true,
      ocorrencias: resto.reduce((s, i) => s + i.ocorrencias, 0),
      lancamentos: resto.reduce((s, i) => s + i.lancamentos, 0),
      valor_centavos: resto.reduce((s, i) => s + i.valor_centavos, 0),
    });
  }
  const topo = Math.max(1, ...lista.map((i) => valorDe(i, metrica)));
  container.innerHTML = lista
    .map((item, indice) => `
      <div class="barra-linha${item.rotulo === selecionado ? " selecionada" : ""}" data-indice="${indice}"
           tabindex="0" role="button" aria-label="${esc(item.rotulo)}: ${esc(textoDe(item, metrica))}">
        <span class="nome">${esc(item.rotulo)}</span>
        <span class="trilho"><span class="preenchimento" data-largura="${(valorDe(item, metrica) / topo) * 100}"></span></span>
        <span class="quanto num">${esc(textoDe(item, metrica))}</span>
      </div>`)
    .join("");
  container.querySelectorAll(".preenchimento").forEach((el) => {
    el.style.width = `${el.dataset.largura}%`;
  });
  container.querySelectorAll(".barra-linha").forEach((linha) => {
    const item = lista[Number(linha.dataset.indice)];
    linha.addEventListener("mousemove", (e) => mostrarDica(e, htmlDica(item)));
    linha.addEventListener("mouseleave", esconderDica);
    const clicar = () => !item.outras && aoClicar && aoClicar(item.rotulo);
    linha.addEventListener("click", clicar);
    linha.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), clicar()));
  });
}

/** Colunas verticais por período (SVG). */
export function colunas(container, serie, { metrica, aoClicar }) {
  const total = serie.reduce((s, i) => s + i.ocorrencias, 0);
  if (!serie.length || total === 0) {
    container.innerHTML = `<div class="estado"><strong>Sem ocorrências</strong>no período selecionado</div>`;
    return;
  }
  const largura = Math.max(320, container.clientWidth);
  const altura = Math.max(160, container.clientHeight);
  const escala = parseFloat(getComputedStyle(document.documentElement).fontSize) / 15;
  const fonte = Math.round(13 * escala);
  const margem = { esq: Math.round(54 * escala), dir: 6, topo: 8, base: Math.round(22 * escala) };
  const w = largura - margem.esq - margem.dir;
  const h = altura - margem.topo - margem.base;
  const topo = Math.max(1, ...serie.map((i) => valorDe(i, metrica)));
  const passo = w / serie.length;
  const lacuna = Math.min(6, passo * 0.25);
  const larguraColuna = Math.max(2, passo - lacuna);
  const marcas = [0, 0.5, 1].map((f) => ({ y: margem.topo + h - f * h, v: f * topo }));
  const rotuloEixo = (v) => (metrica === "valor" ? reaisCompacto(v) : numero(Math.round(v)));
  const cadaN = Math.ceil(serie.length / Math.max(1, Math.floor(w / (fonte * 4.2))));
  const r = Math.min(4, larguraColuna / 2);

  const partes = [];
  marcas.forEach((m) => {
    partes.push(`<line class="grade" x1="${margem.esq}" x2="${largura - margem.dir}" y1="${m.y}" y2="${m.y}"/>`);
    partes.push(`<text class="eixo-texto" x="${margem.esq - 6}" y="${m.y + fonte * 0.35}" text-anchor="end" font-size="${fonte}">${esc(rotuloEixo(m.v))}</text>`);
  });
  serie.forEach((item, i) => {
    const valor = valorDe(item, metrica);
    const alturaColuna = (valor / topo) * h;
    const x = margem.esq + i * passo + lacuna / 2;
    const y = margem.topo + h - alturaColuna;
    // Topo arredondado, base reta apoiada no eixo.
    const caminho = alturaColuna <= 0 ? "" : alturaColuna < r
      ? `<rect class="coluna" x="${x}" y="${y}" width="${larguraColuna}" height="${alturaColuna}"/>`
      : `<path class="coluna" d="M${x},${y + alturaColuna} V${y + r} Q${x},${y} ${x + r},${y} H${x + larguraColuna - r} Q${x + larguraColuna},${y} ${x + larguraColuna},${y + r} V${y + alturaColuna} Z"/>`;
    partes.push(`<g data-indice="${i}"><rect class="coluna-alvo" x="${margem.esq + i * passo}" y="${margem.topo}" width="${passo}" height="${h}"/>${caminho}</g>`);
    if (i % cadaN === 0) {
      partes.push(`<text class="eixo-texto" x="${x + larguraColuna / 2}" y="${altura - 6}" text-anchor="middle" font-size="${fonte}">${esc(item.rotulo)}</text>`);
    }
  });
  container.innerHTML = `<svg class="colunas" viewBox="0 0 ${largura} ${altura}" width="${largura}" height="${altura}" role="img"
      aria-label="Ocorrências por período">${partes.join("")}</svg>`;
  container.querySelectorAll("g[data-indice]").forEach((g) => {
    const item = serie[Number(g.dataset.indice)];
    const titulo = item.inicio === item.fim ? item.rotulo : `${item.rotulo} a ${item.fim.slice(8, 10)}/${item.fim.slice(5, 7)}`;
    g.addEventListener("mousemove", (e) => mostrarDica(e, htmlDica({ ...item, rotulo: titulo })));
    g.addEventListener("mouseleave", esconderDica);
    g.addEventListener("click", () => aoClicar && aoClicar(item));
  });
}
