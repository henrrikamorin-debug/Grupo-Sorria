// Painel financeiro — Grupo Sorria
// A interface apenas lê o último retrato válido do serviço local.
// Recarregar o painel NÃO coleta dados do TOTVS.

import { barras, colunas, esconderDica } from "./graficos.js";
import {
  dataCurta, esc, gravarPreferencia, haQuanto, horaLocal, isoLocal, lerPreferencia,
  numero, reais, reaisPartes,
} from "./formato.js";

const RELEITURA_MS = 60_000;
const PAGINA_NORMAL = 25;
const $ = (id) => document.getElementById(id);
const url = new URL(location.href);

const estado = {
  tv: url.searchParams.get("tv") === "1",
  filtros: {
    periodo: url.searchParams.get("periodo") || lerPreferencia("periodo", "30d"),
    inicio: url.searchParams.get("inicio") || lerPreferencia("inicio", ""),
    fim: url.searchParams.get("fim") || lerPreferencia("fim", ""),
    clinica: url.searchParams.get("clinica") || "",
    categoria: url.searchParams.get("categoria") || "",
    situacao: url.searchParams.get("situacao") || "",
  },
  metrica: lerPreferencia("metrica", "ocorrencias"),
  pagina: 0,
  linhasPorPagina: PAGINA_NORMAL,
  dados: null,
  ultimaLeitura: null,
  falhaDesde: null,
  requisicao: 0,
  rotacao: null,
};

// ------------------------------------------------------------------ período
function intervaloDoPeriodo() {
  const f = estado.filtros;
  const hoje = new Date();
  const menos = (dias) => { const d = new Date(hoje); d.setDate(d.getDate() - dias); return d; };
  switch (f.periodo) {
    case "7d": return [isoLocal(menos(6)), isoLocal(hoje)];
    case "30d": return [isoLocal(menos(29)), isoLocal(hoje)];
    case "90d": return [isoLocal(menos(89)), isoLocal(hoje)];
    case "mes": return [isoLocal(new Date(hoje.getFullYear(), hoje.getMonth(), 1)), isoLocal(hoje)];
    case "mes-anterior":
      return [isoLocal(new Date(hoje.getFullYear(), hoje.getMonth() - 1, 1)),
              isoLocal(new Date(hoje.getFullYear(), hoje.getMonth(), 0))];
    case "personalizado": return [f.inicio, f.fim];
    default: return ["", ""];
  }
}

function parametros(extra = {}) {
  const [inicio, fim] = intervaloDoPeriodo();
  const p = new URLSearchParams();
  if (inicio) p.set("inicio", inicio);
  if (fim) p.set("fim", fim);
  for (const chave of ["clinica", "categoria", "situacao"]) {
    if (estado.filtros[chave]) p.set(chave, estado.filtros[chave]);
  }
  for (const [k, v] of Object.entries(extra)) p.set(k, v);
  return p;
}

function descricaoFiltros() {
  const [inicio, fim] = intervaloDoPeriodo();
  const partes = [inicio || fim ? `${dataCurta(inicio)} a ${dataCurta(fim)}` : "Todo o período coletado"];
  partes.push(estado.filtros.clinica || "Todas as clínicas");
  if (estado.filtros.categoria) partes.push(estado.filtros.categoria);
  if (estado.filtros.situacao) {
    const s = estado.dados?.opcoes.situacoes.find((x) => x.valor === estado.filtros.situacao);
    partes.push(s ? s.rotulo : estado.filtros.situacao);
  }
  return partes.join(" · ");
}

// ------------------------------------------------------------------ leitura
async function carregar({ silencioso = false } = {}) {
  const numeroRequisicao = ++estado.requisicao;
  if (!estado.dados && !silencioso) mostrarCarregando();
  $("rodape-painel").textContent = "lendo dados locais…";
  try {
    const resposta = await fetch(`/api/painel?${parametros(estado.tv ? { tv: "1" } : {})}`, { cache: "no-store" });
    const corpo = await resposta.json().catch(() => ({}));
    if (!resposta.ok) throw new Error(corpo.erro || `HTTP ${resposta.status}`);
    if (numeroRequisicao !== estado.requisicao) return; // resposta antiga
    estado.dados = corpo;
    estado.ultimaLeitura = new Date();
    estado.filtrosExibidos = descricaoFiltros();
    estado.falhaDesde = null;
    $("faixa-erro").classList.add("oculto");
    renderizar();
  } catch (erro) {
    if (numeroRequisicao !== estado.requisicao) return;
    estado.falhaDesde = estado.falhaDesde || new Date();
    mostrarFalha(erro);
  }
}

function mostrarCarregando() {
  ["k-registros", "k-ocorrencias", "k-valor", "k-pendencias"].forEach((id) => ($(id).textContent = "…"));
  const html = `<div class="estado carregando"><strong>Carregando</strong>lendo o último retrato local</div>`;
  ["g-clinica", "g-categoria", "g-periodo"].forEach((id) => ($(id).innerHTML = html));
  $("tabela-corpo").innerHTML = "";
  $("tabela-estado").innerHTML = html;
}

function mostrarFalha(erro) {
  const faixa = $("faixa-erro");
  const desde = estado.falhaDesde.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  faixa.textContent = estado.dados
    ? `Sem comunicação com o serviço local desde ${desde}. Exibindo os últimos dados recebidos (${horaLocal(estado.ultimaLeitura.toISOString())} · ${estado.filtrosExibidos}). Detalhe: ${erro.message}`
    : `Não foi possível ler os dados do serviço local (${erro.message}). Verifique se o serviço está ligado.`;
  faixa.classList.remove("oculto");
  $("rodape-painel").textContent = `falha na leitura às ${desde}`;
  const integ = $("integracao");
  integ.dataset.nivel = "sem_comunicacao";
  $("integracao-titulo").textContent = "Sem comunicação com o serviço";
  $("integracao-sub").textContent = "o painel não está recebendo dados";
  if (!estado.dados) {
    const html = `<div class="estado falha"><strong>Falha ao carregar</strong>
      Inicie o serviço (scripts/iniciar) e aguarde — o painel tenta novamente sozinho.</div>`;
    ["g-clinica", "g-categoria", "g-periodo"].forEach((id) => ($(id).innerHTML = html));
    $("tabela-estado").innerHTML = html;
    ["k-registros", "k-ocorrencias", "k-valor", "k-pendencias"].forEach((id) => ($(id).textContent = "—"));
  }
}

// ------------------------------------------------------------------ renderização
function renderizar() {
  const d = estado.dados;
  // A faixa de demonstração só some quando o servidor confirma o modo real.
  $("faixa-demo").classList.toggle("oculto", d.modo === "real");
  document.title = (d.modo === "real" ? "" : "[DEMONSTRAÇÃO] ") + "Painel Financeiro — Grupo Sorria";
  renderizarIntegracao(d.situacao);
  renderizarOpcoes(d.opcoes);
  $("resumo-filtros").textContent = "";
  $("resumo-tv").textContent = descricaoFiltros();

  const semColeta = !d.situacao.ultima_coleta_sucesso;
  if (semColeta) return renderizarSemColeta(d.situacao);

  const k = d.indicadores;
  $("k-registros").textContent = numero(k.registros_analisados);
  $("k-ocorrencias").textContent = numero(k.ocorrencias);
  $("k-ocorrencias-d").textContent = `em ${numero(k.lancamentos_afetados)} lançamento(s)`;
  const [inteiroValor, centavos] = reaisPartes(k.valor_associado_centavos);
  $("k-valor").innerHTML = `${esc(inteiroValor)}<span class="centavos">${esc(centavos)}</span>`;
  $("k-valor-d").textContent = k.lancamentos_sem_valor
    ? `cada lançamento somado uma vez · ${numero(k.lancamentos_sem_valor)} sem valor`
    : "cada lançamento somado uma vez";
  $("k-pendencias").textContent = numero(k.pendencias);
  $("k-pendencias-d").textContent =
    `${numero(k.por_situacao.pendente)} pendente(s) · ${numero(k.por_situacao.em_analise)} em análise`;

  renderizarGraficos();
  renderizarTabela();

  const s = d.situacao;
  $("rodape-coleta").textContent = s.demonstracao
    ? "Demonstração: coleta simulada a cada " + s.intervalo_minutos + " min pelo serviço local. Atualizar o painel não coleta dados."
    : `Coleta automática a cada ${s.intervalo_minutos} min pelo serviço local, somente enquanto o computador e o serviço estiverem ligados. Atualizar o painel não coleta dados do TOTVS.`;
  $("rodape-painel").textContent =
    `Painel relido às ${estado.ultimaLeitura.toLocaleTimeString("pt-BR")}`;
}

function renderizarSemColeta(s) {
  ["k-registros", "k-ocorrencias", "k-valor", "k-pendencias"].forEach((id) => ($(id).textContent = "—"));
  const motivo = s.ultima_tentativa_falhou ? `Última tentativa falhou: ${s.ultima_tentativa.mensagem}` :
    s.coleta_em_andamento ? "Primeira coleta em andamento…" : "Aguardando a primeira coleta do serviço.";
  const html = `<div class="estado${s.ultima_tentativa_falhou ? " falha" : ""}">
    <strong>Nenhuma coleta concluída ainda</strong>${esc(motivo)}</div>`;
  ["g-clinica", "g-categoria", "g-periodo"].forEach((id) => ($(id).innerHTML = html));
  $("tabela-corpo").innerHTML = "";
  $("tabela-estado").innerHTML = html;
  $("pagina-info").textContent = "";
  $("contagem-tabela").textContent = "";
  $("rodape-painel").textContent = `Painel relido às ${estado.ultimaLeitura.toLocaleTimeString("pt-BR")}`;
}

function renderizarIntegracao(s) {
  const integ = $("integracao");
  integ.dataset.nivel = s.nivel;
  $("integracao-titulo").textContent = s.titulo + (s.coleta_em_andamento ? " · coletando…" : "");
  const sucesso = s.ultima_coleta_sucesso;
  const rotulo = s.demonstracao ? "Última coleta simulada" : "Última coleta bem-sucedida";
  $("integracao-sub").textContent = sucesso
    ? `${rotulo}: ${horaLocal(sucesso.finalizada_em)} (${haQuanto(sucesso.finalizada_em)})` +
      (s.ultima_tentativa_falhou ? " · última tentativa falhou" : "")
    : s.detalhe || "nenhuma coleta concluída";
}

function preencherSelect(id, valores, selecionado, rotulos = null) {
  const select = $(id);
  const atual = [...select.options].slice(1).map((o) => o.value).join("|");
  const novo = valores.join("|");
  if (atual !== novo) {
    select.innerHTML = `<option value="">Todas</option>` + valores
      .map((v, i) => `<option value="${esc(v)}">${esc(rotulos ? rotulos[i] : v)}</option>`).join("");
  }
  // Mantém o filtro escolhido mesmo que ele não exista no retrato atual.
  if (selecionado && !valores.includes(selecionado)) {
    select.insertAdjacentHTML("beforeend", `<option value="${esc(selecionado)}">${esc(selecionado)} (sem dados)</option>`);
  }
  select.value = selecionado || "";
}

function renderizarOpcoes(opcoes) {
  preencherSelect("f-clinica", opcoes.clinicas, estado.filtros.clinica);
  preencherSelect("f-categoria", opcoes.categorias, estado.filtros.categoria);
  preencherSelect("f-situacao", opcoes.situacoes.map((s) => s.valor), estado.filtros.situacao,
    opcoes.situacoes.map((s) => s.rotulo));
  $("f-periodo").value = estado.filtros.periodo;
  const personalizado = estado.filtros.periodo === "personalizado";
  $("campo-inicio").classList.toggle("oculto", !personalizado);
  $("campo-fim").classList.toggle("oculto", !personalizado);
  $("f-inicio").value = estado.filtros.inicio;
  $("f-fim").value = estado.filtros.fim;
}

function renderizarGraficos() {
  const g = estado.dados.graficos;
  const metrica = estado.metrica;
  document.querySelectorAll("[data-metrica]").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.metrica === metrica)));
  document.querySelectorAll("[data-metrica-rotulo]").forEach((el) =>
    (el.textContent = metrica === "valor" ? "· valor associado" : "· nº de ocorrências"));
  const maximo = estado.tv ? 6 : 8;
  barras($("g-clinica"), g.por_clinica, {
    metrica, maximo, selecionado: estado.filtros.clinica,
    aoClicar: (v) => alterarFiltro("clinica", estado.filtros.clinica === v ? "" : v),
  });
  barras($("g-categoria"), g.por_categoria, {
    metrica, maximo, selecionado: estado.filtros.categoria,
    aoClicar: (v) => alterarFiltro("categoria", estado.filtros.categoria === v ? "" : v),
  });
  const gran = { dia: "por dia", semana: "por semana", mes: "por mês" }[g.por_periodo.granularidade];
  $("g-periodo-gran").textContent = `· ${gran}`;
  colunas($("g-periodo"), g.por_periodo.serie, {
    metrica,
    aoClicar: (item) => {
      if (estado.tv) return;
      estado.filtros.periodo = "personalizado";
      estado.filtros.inicio = item.inicio;
      estado.filtros.fim = item.fim;
      aplicarFiltros();
    },
  });
}

function calcularLinhasTv() {
  const area = $("tabela-area");
  const cabecalho = area.querySelector("thead").getBoundingClientRect().height || 30;
  const primeira = $("tabela-corpo").querySelector("tr");
  const linha = primeira ? primeira.getBoundingClientRect().height
    : parseFloat(getComputedStyle(document.documentElement).fontSize) * 2.2;
  return Math.max(3, Math.floor((area.clientHeight - cabecalho - 2) / linha));
}

function renderizarTabela() {
  desenharTabela(estado.tv ? calcularLinhasTv() : PAGINA_NORMAL);
  // Na TV, a página deve caber inteira na tela: ajusta pela altura real das linhas.
  if (estado.tv) {
    const ajustado = calcularLinhasTv();
    if (ajustado !== estado.linhasPorPagina) desenharTabela(ajustado);
  }
}

function desenharTabela(linhasPorPagina) {
  const lista = estado.dados.ocorrencias;
  const total = lista.length;
  estado.linhasPorPagina = linhasPorPagina;
  const paginas = Math.max(1, Math.ceil(total / estado.linhasPorPagina));
  if (estado.pagina >= paginas) estado.pagina = 0;
  const inicio = estado.pagina * estado.linhasPorPagina;
  const pagina = lista.slice(inicio, inicio + estado.linhasPorPagina);

  const porReferencia = {};
  lista.forEach((o) => (porReferencia[o.referencia] = (porReferencia[o.referencia] || 0) + 1));

  $("contagem-tabela").textContent = total ? `${numero(total)} no filtro` : "";
  $("tabela-estado").innerHTML = total ? "" :
    `<div class="estado"><strong>Nenhuma ocorrência</strong>para os filtros selecionados</div>`;
  $("tabela-corpo").innerHTML = pagina.map((o) => {
    const repetido = porReferencia[o.referencia] > 1
      ? `<span class="repetido">${porReferencia[o.referencia]} ocorrências neste lançamento</span>` : "";
    return `<tr class="linha" tabindex="0" data-id="${esc(o.id)}">
      <td class="data num">${dataCurta(o.data)}</td>
      <td>${esc(o.clinica)}</td>
      <td class="ref num">${esc(o.referencia)}</td>
      <td class="regra"><span class="codigo">${esc(o.regra_codigo)}</span>${esc(o.regra_nome)}</td>
      <td class="descricao">${esc(o.descricao)}</td>
      <td class="valor num">${reais(o.valor_centavos)}${repetido}</td>
      <td><span class="situacao ${esc(o.situacao)}">${esc(o.situacao_rotulo)}</span></td>
    </tr>`;
  }).join("");
  $("tabela-corpo").querySelectorAll("tr.linha").forEach((tr) => {
    const abrir = () => abrirOcorrencia(tr.dataset.id);
    tr.addEventListener("click", abrir);
    tr.addEventListener("keydown", (e) => e.key === "Enter" && abrir());
  });
  $("pagina-info").textContent = total
    ? `Exibindo ${numero(inicio + 1)}–${numero(inicio + pagina.length)} de ${numero(total)} · página ${estado.pagina + 1} de ${paginas}` +
      (estado.tv && paginas > 1 ? ` · troca a cada ${estado.dados.televisao.rotacao_tabela_segundos} s` : "")
    : "";
  $("btn-anterior").disabled = estado.pagina === 0;
  $("btn-proxima").disabled = estado.pagina >= paginas - 1;
}

// ------------------------------------------------------------------ gaveta de detalhe
function abrirGaveta(sobre, titulo, html) {
  $("gaveta-sobre").textContent = sobre;
  $("gaveta-titulo").textContent = titulo;
  $("gaveta-corpo").innerHTML = html;
  $("gaveta").classList.remove("oculto");
  $("fundo-modal").classList.remove("oculto");
  $("gaveta-fechar").focus();
}

function fecharGaveta() {
  $("gaveta").classList.add("oculto");
  $("fundo-modal").classList.add("oculto");
}

function abrirOcorrencia(id) {
  const o = estado.dados.ocorrencias.find((x) => x.id === id);
  if (!o) return;
  const ev = o.evidencia || {};
  const aviso = ev.regra_ilustrativa
    ? `<div class="aviso-regra">Regra ilustrativa da demonstração — não é regra aprovada pelo financeiro. Dados fictícios.</div>`
    : ev.regra_aprovada ? "" : `<div class="aviso-regra">Regra ainda não aprovada.</div>`;
  const itens = (ev.itens || []).map((i) =>
    `<dt>${esc(i.campo)}</dt><dd class="${i.valor === "oculto no modo TV" ? "oculto-tv" : ""}">${esc(i.valor)}</dd>`).join("");
  const relacionados = (ev.relacionados || []).length
    ? `<div><h4>Lançamentos relacionados</h4>${ev.relacionados.map(esc).join(", ")}</div>` : "";
  const botoes = ["pendente", "em_analise", "resolvida"].map((s) => {
    const rotulo = { pendente: "Pendente", em_analise: "Em análise", resolvida: "Resolvida" }[s];
    return `<button class="botao${o.situacao === s ? " primario" : ""}" type="button" data-situacao="${s}">${rotulo}</button>`;
  }).join("");
  abrirGaveta(`${o.regra_codigo} · ${o.clinica}`, o.regra_nome, `
    ${aviso}
    <dl>
      <dt>Descrição</dt><dd>${esc(o.descricao)}</dd>
      <dt>Lançamento</dt><dd class="num">${esc(o.referencia)}</dd>
      <dt>Data</dt><dd class="num">${dataCurta(o.data)}</dd>
      <dt>Valor</dt><dd class="num">${reais(o.valor_centavos)}</dd>
      <dt>Situação</dt><dd><span class="situacao ${esc(o.situacao)}">${esc(o.situacao_rotulo)}</span></dd>
      <dt>Primeira detecção</dt><dd class="num">${horaLocal(o.primeira_deteccao)}</dd>
      <dt>Coleta de origem</dt><dd class="num">nº ${esc(o.coleta_id)}${estado.dados.modo === "real" ? "" : " (simulada)"}</dd>
    </dl>
    <div><h4>Evidência</h4><div class="resumo-evidencia">${esc(ev.resumo)}<br><span class="atualizando">Condição verificada: ${esc(ev.condicao)}</span></div></div>
    <div><h4>Dados que originaram a ocorrência</h4><dl>${itens}</dl></div>
    ${relacionados}
    <div class="so-normal"><h4>Acompanhamento (registrado apenas neste painel, não altera o TOTVS)</h4>
      <div class="acoes-situacao">${botoes}</div><div class="atualizando" id="situacao-msg"></div></div>`);
  $("gaveta-corpo").querySelectorAll("[data-situacao]").forEach((b) =>
    b.addEventListener("click", () => alterarSituacao(o.id, b.dataset.situacao)));
}

async function postar(caminho, corpo) {
  const resposta = await fetch(caminho, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Painel-Sorria": "1" },
    body: JSON.stringify(corpo || {}),
  });
  const dados = await resposta.json().catch(() => ({}));
  if (!resposta.ok) throw new Error(dados.erro || `HTTP ${resposta.status}`);
  return dados;
}

async function alterarSituacao(id, situacao) {
  try {
    await postar(`/api/ocorrencias/${id}/situacao`, { situacao });
    await carregar({ silencioso: true });
    abrirOcorrencia(id);
  } catch (erro) {
    const msg = $("situacao-msg");
    if (msg) msg.textContent = `Não foi possível alterar: ${erro.message}`;
  }
}

function abrirIntegracao() {
  const s = estado.dados?.situacao;
  if (!s) return;
  const linhas = s.historico.map((c) => `<tr>
      <td class="num">${horaLocal(c.iniciada_em)}</td>
      <td class="${esc(c.situacao)}">${esc({ sucesso: "Sucesso", falha: "Falha", em_andamento: "Em andamento" }[c.situacao] || c.situacao)}${c.simulada ? " (simulada)" : ""}</td>
      <td>${esc(c.origem)}</td>
      <td class="num">${c.registros == null ? "—" : numero(c.registros)}</td>
      <td>${esc(c.situacao === "falha" ? c.mensagem : "")}</td></tr>`).join("");
  const proxima = s.proxima_coleta_prevista ? horaLocal(s.proxima_coleta_prevista) : "—";
  abrirGaveta("Situação da integração", s.titulo, `
    ${s.demonstracao ? `<div class="aviso-regra">Modo demonstração: as coletas são simuladas e os dados são fictícios. Nenhuma conexão com o TOTVS é feita.</div>` : ""}
    <dl>
      <dt>Origem dos dados</dt><dd>${esc(s.conector.nome)}</dd>
      <dt>Detalhe</dt><dd>${esc(s.detalhe || "—")}</dd>
      <dt>Última coleta válida</dt><dd class="num">${s.ultima_coleta_sucesso ? horaLocal(s.ultima_coleta_sucesso.finalizada_em) + " · " + haQuanto(s.ultima_coleta_sucesso.finalizada_em) : "nenhuma"}</dd>
      <dt>Dados desatualizados?</dt><dd>${s.desatualizado ? `Sim (tolerância ${s.tolerancia_minutos} min)` : "Não"}</dd>
      <dt>Rotina automática</dt><dd>${s.agendador_ativo ? `ativa, a cada ${s.intervalo_minutos} min` : "parada"}</dd>
      <dt>Próxima coleta prevista</dt><dd class="num">${proxima}</dd>
    </dl>
    <div class="nota">
      <p>A coleta é feita pelo serviço local deste computador. Se o computador desligar, hibernar ou o serviço for encerrado, não há coleta — o painel continua exibindo a última coleta válida e indica quando ela fica desatualizada.</p>
      <p>Atualizar ou recarregar esta tela apenas relê os dados locais; não busca nada no TOTVS.</p>
    </div>
    <div><h4>Últimas execuções</h4>
      <table class="historico"><thead><tr><th>Início</th><th>Resultado</th><th>Origem</th><th>Registros</th><th>Mensagem</th></tr></thead>
      <tbody>${linhas || `<tr><td colspan="5">Nenhuma execução registrada.</td></tr>`}</tbody></table></div>
    <div class="so-normal"><h4>Ações</h4><div class="acoes-situacao">
      <button class="botao" type="button" id="btn-coletar">${s.demonstracao ? "Executar coleta simulada agora" : "Executar coleta agora"}</button>
      ${s.demonstracao ? `<button class="botao" type="button" id="btn-falha">Simular falha de coleta</button>` : ""}
      </div><div class="atualizando" id="coleta-msg"></div></div>`);
  const executar = async (simularFalha) => {
    $("coleta-msg").textContent = "Executando…";
    try {
      const r = await postar("/api/coleta", { simular_falha: simularFalha });
      $("coleta-msg").textContent = r.situacao === "sucesso"
        ? `Concluída: ${numero(r.registros)} registros, ${numero(r.ocorrencias)} ocorrências.`
        : r.situacao === "ignorada" ? r.mensagem : `Falhou: ${r.mensagem}. A última coleta válida foi preservada.`;
      await carregar({ silencioso: true });
    } catch (erro) {
      $("coleta-msg").textContent = `Não foi possível executar: ${erro.message}`;
    }
  };
  $("btn-coletar").addEventListener("click", () => executar(false));
  $("btn-falha")?.addEventListener("click", () => executar(true));
}

// ------------------------------------------------------------------ filtros e modos
function alterarFiltro(chave, valor) {
  estado.filtros[chave] = valor;
  aplicarFiltros();
}

function aplicarFiltros() {
  estado.pagina = 0;
  gravarPreferencia("periodo", estado.filtros.periodo);
  gravarPreferencia("inicio", estado.filtros.inicio);
  gravarPreferencia("fim", estado.filtros.fim);
  if (estado.filtros.periodo === "personalizado" && (!estado.filtros.inicio || !estado.filtros.fim)) {
    renderizarOpcoes(estado.dados?.opcoes || { clinicas: [], categorias: [], situacoes: [] });
    return; // aguarda as duas datas
  }
  if (estado.filtros.inicio && estado.filtros.fim && estado.filtros.inicio > estado.filtros.fim) {
    $("resumo-filtros").textContent = "A data inicial é posterior à final.";
    return;
  }
  carregar();
}

function definirTv(ativo) {
  estado.tv = ativo;
  document.documentElement.classList.toggle("tv", ativo);
  $("btn-tv").textContent = ativo ? "Sair do modo TV" : "Modo TV";
  if (ativo) url.searchParams.set("tv", "1"); else url.searchParams.delete("tv");
  history.replaceState(null, "", url);
  clearInterval(estado.rotacao);
  estado.rotacao = null;
  fecharGaveta();
  estado.pagina = 0;
  // Os dados sensíveis são removidos no servidor; por isso a releitura.
  carregar();
}

function rotacionarTabela() {
  if (!estado.tv || !estado.dados) return;
  const paginas = Math.ceil(estado.dados.ocorrencias.length / estado.linhasPorPagina);
  if (paginas <= 1) return;
  estado.pagina = (estado.pagina + 1) % paginas;
  renderizarTabela();
}

function iniciarRelogio() {
  const atualizar = () => {
    const agora = new Date();
    $("relogio-hora").textContent = agora.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
    $("relogio-data").textContent = agora.toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long" });
  };
  atualizar();
  setInterval(atualizar, 1000);
}

function ligarEventos() {
  $("f-periodo").addEventListener("change", (e) => {
    estado.filtros.periodo = e.target.value;
    if (e.target.value === "personalizado" && !estado.filtros.inicio) {
      const [i, f] = [isoLocal(new Date(Date.now() - 29 * 864e5)), isoLocal(new Date())];
      estado.filtros.inicio = i;
      estado.filtros.fim = f;
    }
    aplicarFiltros();
  });
  $("f-inicio").addEventListener("change", (e) => alterarFiltro("inicio", e.target.value));
  $("f-fim").addEventListener("change", (e) => alterarFiltro("fim", e.target.value));
  $("f-clinica").addEventListener("change", (e) => alterarFiltro("clinica", e.target.value));
  $("f-categoria").addEventListener("change", (e) => alterarFiltro("categoria", e.target.value));
  $("f-situacao").addEventListener("change", (e) => alterarFiltro("situacao", e.target.value));
  $("btn-limpar").addEventListener("click", () => {
    estado.filtros = { periodo: "30d", inicio: "", fim: "", clinica: "", categoria: "", situacao: "" };
    aplicarFiltros();
  });
  document.querySelectorAll("[data-metrica]").forEach((b) => b.addEventListener("click", () => {
    estado.metrica = b.dataset.metrica;
    gravarPreferencia("metrica", estado.metrica);
    if (estado.dados?.situacao.ultima_coleta_sucesso) renderizarGraficos();
  }));
  $("btn-exportar").addEventListener("click", () => {
    location.href = `/api/ocorrencias.csv?${parametros(estado.tv ? { tv: "1" } : {})}`;
  });
  $("btn-tv").addEventListener("click", () => definirTv(!estado.tv));
  $("btn-tela-cheia").addEventListener("click", () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else document.documentElement.requestFullscreen?.().catch(() => {});
  });
  $("btn-anterior").addEventListener("click", () => { estado.pagina--; renderizarTabela(); });
  $("btn-proxima").addEventListener("click", () => { estado.pagina++; renderizarTabela(); });
  $("integracao").addEventListener("click", abrirIntegracao);
  $("gaveta-fechar").addEventListener("click", fecharGaveta);
  $("fundo-modal").addEventListener("click", fecharGaveta);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") fecharGaveta();
  });

  // Modo TV: cursor e botões aparecem só quando o mouse se move.
  let temporizador;
  document.addEventListener("mousemove", () => {
    document.documentElement.classList.add("cursor-visivel");
    clearTimeout(temporizador);
    temporizador = setTimeout(() => document.documentElement.classList.remove("cursor-visivel"), 3000);
  });

  let redimensionar;
  window.addEventListener("resize", () => {
    clearTimeout(redimensionar);
    redimensionar = setTimeout(() => estado.dados?.situacao.ultima_coleta_sucesso && (renderizarGraficos(), renderizarTabela()), 150);
  });
  window.addEventListener("scroll", esconderDica, { passive: true });
}

function iniciar() {
  document.documentElement.classList.toggle("tv", estado.tv);
  $("btn-tv").textContent = estado.tv ? "Sair do modo TV" : "Modo TV";
  ligarEventos();
  iniciarRelogio();
  carregar();
  setInterval(() => carregar({ silencioso: true }), RELEITURA_MS);
  setInterval(() => {
    if (!estado.tv || !estado.dados) return;
    const segundos = estado.dados.televisao.rotacao_tabela_segundos;
    const agora = Date.now();
    if (!estado.ultimaRotacao || agora - estado.ultimaRotacao >= segundos * 1000) {
      if (estado.ultimaRotacao) rotacionarTabela();
      estado.ultimaRotacao = agora;
    }
  }, 1000);
}

iniciar();
