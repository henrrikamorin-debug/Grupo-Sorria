"""Executor do TOTVS WebApp no Chrome: o agente opera a tela como um operador.

Roteiro (Contas a Pagar, só consulta e exportação):

1. conecta ao Chrome dedicado do agente (perfil próprio em ``dados/navegador``,
   porta de controle aberta só neste computador); se ele estiver fechado, abre;
2. localiza a aba do TOTVS WebApp (ou abre o endereço configurado);
3. sessão: se o TOTVS não estiver autenticado, PAUSA e espera uma pessoa entrar
   na janela do Chrome (o agente nunca digita usuário nem senha); quando o menu
   aparece, continua sozinho;
4. pesquisa "Consulta Genérica" no campo Pesquisar do menu e abre a rotina;
5. escolhe a tabela SE2 — Contas a Pagar;
6. gerenciamento de filtros: campo Vencimento, operador Mês Atual, aplicar;
7. confere o filtro aplicado e outros filtros/abrangência configurados;
8. clica em Exp. CSV e captura o download pelo próprio Chrome, numa pasta nova
   desta execução (nenhum arquivo antigo é aproveitado).

Cada etapa espera uma condição na tela (texto, campo, botão), nunca um tempo
fixo nem coordenadas. Os textos de cada etapa ficam em
``config["navegador"]["textos"]`` e só podem ser clicados elementos cujo texto
esteja nessa lista; ações de alteração (incluir, alterar, excluir, baixar,
pagar, estornar…) são bloqueadas mesmo que apareçam na lista.

Em falha (ou sempre, com ``diagnostico: "sempre"``) a tela e o texto visível da
etapa são gravados em ``dados/totvs/diagnostico`` (área local, pode conter dados
confidenciais; apagada depois de ``dias_diagnostico``). Nada da tela vai para o
log.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

# Verbos de alteração: nenhum elemento com esses textos é clicado.
ACOES_PROIBIDAS = re.compile(
    r"\b(incluir|inclus[aã]o|alterar|altera[cç][aã]o|excluir|exclus[aã]o|apagar|deletar|baixar|baixa manual|"
    r"baixas|estornar|estorno|pagar|pagamento|efetuar|liberar|aprovar|cancelar|compensar|compensa[cç][aã]o|"
    r"gravar|salvar|efetivar|transferir|substituir|renegociar|liquidar|border[oô]|bordero|gerar t[ií]tulo)\b",
    re.IGNORECASE)
# Nomes de tabela que contêm um desses verbos sem serem ações.
TEXTOS_NEUTROS = re.compile(r"contas a pagar|t[ií]tulos? a pagar", re.IGNORECASE)


class ErroNavegador(Exception):
    """Falha numa etapa do roteiro. ``temporaria`` = vale nova tentativa."""

    def __init__(self, etapa: str, mensagem: str, temporaria: bool = False):
        super().__init__(f"{etapa}: {mensagem}")
        self.etapa = etapa
        self.mensagem = mensagem
        self.temporaria = temporaria


class LoginNecessario(ErroNavegador):
    pass


class AcaoProibida(ErroNavegador):
    pass


class PlaywrightAusente(ErroNavegador):
    pass


@dataclass
class ResultadoNavegador:
    arquivo: Path
    nome_original: str
    escopo: dict
    etapas: list[dict] = field(default_factory=list)
    diagnostico: str | None = None


def acao_proibida(texto: str) -> bool:
    return bool(ACOES_PROIBIDAS.search(TEXTOS_NEUTROS.sub(" ", texto or "")))


def localizar_chrome() -> str | None:
    candidatos = []
    if sys.platform.startswith("win"):
        for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"),
                     os.environ.get("LOCALAPPDATA")):
            if base:
                candidatos.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    elif sys.platform == "darwin":
        candidatos.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    for nome in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if achado := shutil.which(nome):
            candidatos.append(Path(achado))
    return next((str(c) for c in candidatos if c.exists()), None)


def _sem_proxy():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def chrome_respondendo(porta: int) -> bool:
    try:
        with _sem_proxy().open(f"http://127.0.0.1:{porta}/json/version", timeout=2) as resposta:
            return resposta.status == 200
    except OSError:
        return False


def abrir_chrome(config: dict, perfil: Path, endereco: str | None = None) -> subprocess.Popen:
    """Abre o Chrome dedicado do agente (fica aberto depois que o agente termina)."""
    nav = config["navegador"]
    executavel = nav.get("executavel") or localizar_chrome()
    if not executavel:
        raise ErroNavegador("navegador", "Google Chrome não encontrado; informe navegador.executavel no config.json.")
    perfil.mkdir(parents=True, exist_ok=True)
    argumentos = [executavel, f"--remote-debugging-port={int(nav['porta_controle'])}", f"--user-data-dir={perfil}",
                  "--no-first-run", "--no-default-browser-check",
                  # Mantém a página ativa com a janela minimizada ou coberta.
                  "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
                  "--disable-background-timer-throttling", *nav.get("argumentos_extras", [])]
    if endereco:
        argumentos.append(endereco)
    opcoes: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}
    if sys.platform.startswith("win"):
        opcoes["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        opcoes["start_new_session"] = True
    log.info("Abrindo o Chrome do agente (perfil dedicado).")
    return subprocess.Popen(argumentos, **opcoes)


class ExecutorTotvs:
    """Uma coleta pelo navegador. ``ao_mudar_etapa(etapa, mensagem)`` registra o andamento."""

    INTERVALO_MS = 250

    def __init__(self, config: dict, perfil: Path, pasta_execucao: Path, pasta_diagnostico: Path, *,
                 prazo: float | None = None, ao_mudar_etapa=None, recuperar: bool = False):
        self.config = config
        self.nav = config["navegador"]
        self.textos = self.nav["textos"]
        self.endereco = (config["totvs"].get("endereco_webapp") or "").strip()
        self.perfil = perfil
        self.pasta = pasta_execucao
        self.pasta_diagnostico = pasta_diagnostico
        self.prazo = prazo  # time.monotonic() limite da execução inteira
        self.ao_mudar_etapa = ao_mudar_etapa or (lambda etapa, mensagem=None: None)
        self.recuperar = recuperar
        self.etapas: list[dict] = []
        self.pagina = None
        self.navegador = None
        self._diagnostico_usado = False

    # ------------------------------------------------------------ esperas
    def _restante(self, segundos: float) -> float:
        if self.prazo is None:
            return segundos
        restante = self.prazo - time.monotonic()
        if restante <= 0:
            raise ErroNavegador("tempo_maximo", "tempo máximo da execução esgotado.")
        return min(segundos, restante)

    def _esperar(self, condicao, segundos: float, etapa: str, descricao: str, temporaria: bool = True):
        """Repete ``condicao`` até ela devolver algo verdadeiro (sem espera fixa)."""
        limite = time.monotonic() + self._restante(segundos)
        while True:
            resultado = condicao()
            if resultado:
                return resultado
            if time.monotonic() >= limite:
                if self.prazo is not None and time.monotonic() >= self.prazo:
                    raise ErroNavegador("tempo_maximo", "tempo máximo da execução esgotado.")
                raise ErroNavegador(etapa, f"{descricao} não apareceu em {int(segundos)} s.", temporaria)
            self.pagina.wait_for_timeout(self.INTERVALO_MS)

    @property
    def _passo(self) -> float:
        return float(self.nav["tempo_passo_segundos"])

    # ------------------------------------------------------------ tela
    def _visiveis(self, localizador, limite: int = 30) -> list:
        try:
            total = min(localizador.count(), limite)
            return [localizador.nth(i) for i in range(total) if localizador.nth(i).is_visible()]
        except Exception:  # noqa: BLE001 — quadro recarregando durante a leitura
            return []

    def _texto_visivel(self, texto: str | re.Pattern, exato: bool = False) -> bool:
        return any(self._visiveis(q.get_by_text(texto, exact=exato) if isinstance(texto, str)
                                  else q.get_by_text(texto), 5) for q in self.pagina.frames)

    def _algum_visivel(self, textos, exato: bool = False) -> str | None:
        return next((t for t in textos if t and self._texto_visivel(t, exato)), None)

    def _tela_login(self) -> bool:
        return any(self._visiveis(q.locator("input[type=password]"), 5) for q in self.pagina.frames)

    def _menu_pronto(self) -> bool:
        return not self._tela_login() and bool(self._campo(self.textos["pesquisa"]) or
                                               self._algum_visivel(self.textos["menu_pronto"], exato=True))

    def _rotulo(self, elemento) -> str:
        try:
            return elemento.evaluate(
                "e => (e.innerText || e.value || e.getAttribute('aria-label') || e.getAttribute('title') || '')"
                ".trim().slice(0, 200)")
        except Exception:  # noqa: BLE001
            return ""

    def _candidatos(self, texto: str | re.Pattern) -> list:
        """Elementos visíveis com o texto, do mais específico (botão) ao genérico."""
        for quadro in reversed(self.pagina.frames):
            tipos = []
            for papel in ("button", "menuitem", "option", "link", "treeitem", "tab", "row", "gridcell"):
                tipos.append(quadro.get_by_role(papel, name=texto, exact=isinstance(texto, str)))
            tipos.append(quadro.get_by_text(texto, exact=True) if isinstance(texto, str) else quadro.get_by_text(texto))
            if isinstance(texto, str):
                tipos += [quadro.locator(f'[title="{texto}"]'), quadro.locator(f'[aria-label="{texto}"]')]
            for localizador in tipos:
                visiveis = [e for e in self._visiveis(localizador) if not self._antigo(e)]
                if visiveis:
                    return visiveis
        return []

    MARCA = "data-sorria-anterior"

    def _antigo(self, elemento) -> bool:
        try:
            return elemento.get_attribute(self.MARCA) is not None
        except Exception:  # noqa: BLE001
            return False

    def _marcar_anteriores(self, textos) -> None:
        """Marca (só no navegador) os elementos já visíveis com esses textos: telas deixadas abertas por
        uma execução anterior não são confundidas com a tela nova. Não altera nada no TOTVS."""
        for texto in textos:
            for elemento in self._candidatos(texto):
                try:
                    elemento.evaluate(f"e => e.setAttribute('{self.MARCA}', '1')")
                except Exception:  # noqa: BLE001
                    pass

    def _botao_novo(self, textos) -> bool:
        return any(self._candidatos(t) for t in textos if t)

    def _clicar(self, textos, etapa: str, obrigatorio: bool = True) -> str | None:
        """Clica no primeiro texto permitido encontrado (o mais recente na tela, ex.: diálogo do topo)."""
        for texto in ([textos] if isinstance(textos, (str, re.Pattern)) else textos):
            if not texto:
                continue
            candidatos = self._candidatos(texto)
            if not candidatos:
                continue
            elemento = candidatos[-1]
            rotulo = self._rotulo(elemento)
            if acao_proibida(rotulo) or (isinstance(texto, str) and acao_proibida(texto)):
                raise AcaoProibida(etapa, f"o elemento \"{rotulo[:60]}\" é uma ação de alteração; "
                                          "o agente só consulta e exporta.")
            elemento.click(timeout=self._restante(self._passo) * 1000)
            nome = texto if isinstance(texto, str) else texto.pattern
            self.etapas.append({"etapa": etapa, "clique": nome})
            return nome
        if obrigatorio:
            raise ErroNavegador(etapa, "nenhum destes elementos apareceu: " + ", ".join(
                t if isinstance(t, str) else t.pattern for t in ([textos] if isinstance(textos, (str, re.Pattern))
                                                                   else textos) if t), temporaria=True)
        return None

    def _campo(self, rotulos) -> object | None:
        for quadro in reversed(self.pagina.frames):
            for rotulo in rotulos:
                for localizador in (quadro.get_by_placeholder(rotulo, exact=True),
                                    quadro.get_by_role("textbox", name=rotulo, exact=True),
                                    quadro.get_by_role("searchbox", name=rotulo, exact=True),
                                    quadro.locator(f'input[title="{rotulo}"]')):
                    visiveis = self._visiveis(localizador, 5)
                    if visiveis:
                        return visiveis[-1]
        return None

    def _escolher(self, valor: str, etapa: str) -> None:
        """Escolhe ``valor`` numa lista (select) ou clicando no item com esse texto."""
        for quadro in reversed(self.pagina.frames):
            for lista in reversed(self._visiveis(quadro.locator("select"), 10)):
                opcoes = lista.evaluate("s => Array.from(s.options).map(o => o.label || o.text)")
                if valor in opcoes:
                    lista.select_option(label=valor)
                    self.etapas.append({"etapa": etapa, "selecao": valor})
                    return
        self._clicar([valor], etapa)

    # ------------------------------------------------------------ diagnóstico
    def _diagnostico(self, etapa: str, motivo: str) -> None:
        if self.nav["diagnostico"] == "nunca" or self.pagina is None:
            return
        try:
            self.pasta_diagnostico.mkdir(parents=True, exist_ok=True)
            numero = len(list(self.pasta_diagnostico.glob("*.png"))) + 1
            base = self.pasta_diagnostico / f"{numero:02d}_{etapa}"
            self.pagina.screenshot(path=str(base.with_suffix(".png")), full_page=True, timeout=10000)
            partes = [f"etapa: {etapa}\nmotivo: {motivo}\nendereço: {self.pagina.url.split('?')[0]}\n"]
            for indice, quadro in enumerate(self.pagina.frames):
                try:
                    partes.append(f"\n--- quadro {indice}: {quadro.url.split('?')[0]}\n"
                                  + quadro.locator("body").inner_text(timeout=3000))
                    botoes = quadro.get_by_role("button")
                    nomes = [self._rotulo(botoes.nth(i)) for i in range(min(botoes.count(), 80))]
                    partes.append("\n[botões] " + " | ".join(n for n in nomes if n))
                except Exception:  # noqa: BLE001
                    continue
            base.with_suffix(".txt").write_text("\n".join(partes), encoding="utf-8")
            for arquivo in (base.with_suffix(".png"), base.with_suffix(".txt")):
                try:
                    os.chmod(arquivo, 0o600)
                except OSError:
                    pass
            self._diagnostico_usado = True
        except Exception:  # noqa: BLE001 — o diagnóstico nunca derruba a coleta
            log.warning("Não foi possível gravar o diagnóstico da etapa %s.", etapa)

    def _etapa(self, nome: str, funcao, mensagem: str | None = None):
        self.ao_mudar_etapa(f"navegador:{nome}", mensagem)
        inicio = time.monotonic()
        try:
            resultado = funcao()
        except ErroNavegador as erro:
            self._diagnostico(nome, erro.mensagem)
            raise
        except Exception as erro:  # noqa: BLE001 — erro do Playwright vira falha da etapa
            self._diagnostico(nome, type(erro).__name__)
            raise ErroNavegador(nome, f"{type(erro).__name__}: {str(erro).splitlines()[0][:200]}",
                                temporaria=True) from erro
        self.etapas.append({"etapa": nome, "segundos": round(time.monotonic() - inicio, 1)})
        if self.nav["diagnostico"] == "sempre":
            self._diagnostico(nome, "concluída")
        return resultado

    # ------------------------------------------------------------ roteiro
    def coletar(self) -> ResultadoNavegador:
        if not self.endereco:
            raise ErroNavegador("configuracao", "endereço do TOTVS WebApp não configurado (totvs.endereco_webapp).")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as erro:
            raise PlaywrightAusente("configuracao", "biblioteca Playwright não instalada "
                                    "(py -3 -m pip install -r requirements-navegador.txt).") from erro
        self.pasta.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            self.ao_mudar_etapa("navegador:conectar", None)
            self.navegador = self._conectar(playwright)
            try:
                self.pagina = self._aba_totvs(self.navegador.contexts[0])
                self._etapa("sessao", self._garantir_sessao)
                if self.recuperar:
                    self._etapa("recuperar", self._voltar_ao_menu)
                self._etapa("abrir_rotina", self._abrir_consulta_generica)
                self._etapa("selecionar_tabela", self._selecionar_tabela)
                self._etapa("filtro", self._aplicar_filtro)
                escopo = self._etapa("conferir_filtros", self._conferir_filtros)
                arquivo, nome = self._etapa("exportar", self._exportar)
            finally:
                try:
                    self.navegador.close()  # só desconecta: o Chrome e a sessão do TOTVS continuam abertos
                except Exception:  # noqa: BLE001
                    pass
        return ResultadoNavegador(arquivo=arquivo, nome_original=nome, escopo=escopo, etapas=self.etapas,
                                  diagnostico=str(self.pasta_diagnostico) if self._diagnostico_usado else None)

    def _conectar(self, playwright):
        porta = int(self.nav["porta_controle"])
        if not chrome_respondendo(porta):
            abrir_chrome(self.config, self.perfil, self.endereco)
            limite = time.monotonic() + self._restante(45)
            while not chrome_respondendo(porta):
                if time.monotonic() > limite:
                    raise ErroNavegador("navegador", "o Chrome do agente não respondeu ao abrir.", temporaria=True)
                time.sleep(0.3)
        return playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{porta}", timeout=30000)

    def _aba_totvs(self, contexto):
        alvo = self.endereco.rstrip("/")
        for pagina in contexto.pages:
            if pagina.url.rstrip("/").startswith(alvo):
                pagina.bring_to_front()
                return pagina
        pagina = contexto.new_page()
        pagina.goto(self.endereco, wait_until="domcontentloaded", timeout=self._restante(90) * 1000)
        return pagina

    def _garantir_sessao(self) -> None:
        if self._algum_visivel(self.textos.get("sessao_encerrada", [])):
            log.info("Sessão do TOTVS encerrada na aba; recarregando a página (nova autenticação).")
            self.pagina.reload(wait_until="domcontentloaded", timeout=self._restante(90) * 1000)
        # Página carregada = menu (sessão ativa) ou tela de login/parâmetros.
        try:
            self._esperar(lambda: self._menu_pronto() or self._tela_login(), self._passo, "sessao", "menu do TOTVS")
        except ErroNavegador as erro:
            if erro.etapa == "tempo_maximo":
                raise
        if self._menu_pronto():
            return
        minutos = float(self.nav["tempo_login_minutos"])
        self.ao_mudar_etapa("aguardando_login",
                            f"Ação necessária: entre no TOTVS na janela do Chrome do agente (até {minutos:g} min). "
                            "A coleta continua sozinha depois do login.")
        log.warning("TOTVS sem sessão autenticada: aguardando login na janela do Chrome do agente.")
        self.pagina.bring_to_front()
        try:
            self._esperar(self._menu_pronto, minutos * 60, "sessao", "login no TOTVS", temporaria=False)
        except ErroNavegador as erro:
            if erro.etapa == "tempo_maximo":
                raise
            raise LoginNecessario("aguardando_login", f"ninguém entrou no TOTVS em {minutos:g} min; a sessão "
                                  "precisa estar autenticada na janela do Chrome do agente.") from erro
        self.ao_mudar_etapa("navegador:sessao", "Login detectado; coleta retomada.")

    def _voltar_ao_menu(self) -> None:
        """Nova tentativa: fecha diálogos/rotina abertos pela tentativa anterior (Esc não grava nada)."""
        for _ in range(4):
            if self._campo(self.textos["pesquisa"]):
                return
            self.pagina.keyboard.press("Escape")
            self.pagina.wait_for_timeout(self.INTERVALO_MS)
        self._esperar(lambda: self._campo(self.textos["pesquisa"]), self._passo, "recuperar", "menu do TOTVS")

    def _abrir_consulta_generica(self) -> None:
        self._marcar_anteriores(self.textos["exportar"] + self.textos["filtro_abrir"] + self.textos["confirmar"]
                                + self.textos["confirmar_exportacao"])
        campo = self._esperar(lambda: self._campo(self.textos["pesquisa"]), self._passo, "abrir_rotina",
                              "campo Pesquisar do menu")
        rotina = self.textos["rotina"][0]
        campo.fill(rotina)
        campo.press("Enter")
        self._esperar(lambda: self._candidatos(rotina), self._passo, "abrir_rotina", f"item \"{rotina}\"")
        self._clicar(self.textos["rotina"], "abrir_rotina")
        tabela, descricao = self.textos["tabela"], self.textos["tabela_descricao"]
        self._esperar(lambda: self._algum_visivel([tabela, descricao]) or self._caixa_tabela(), self._passo,
                      "abrir_rotina", "tela da Consulta Genérica")

    def _caixa_tabela(self):
        """Campo livre da tela da rotina (não o Pesquisar do menu) para informar a tabela."""
        pesquisa = set(self.textos["pesquisa"])
        for quadro in reversed(self.pagina.frames):
            for caixa in reversed(self._visiveis(quadro.get_by_role("textbox"), 20)):
                rotulos = {caixa.get_attribute("placeholder") or "", caixa.get_attribute("title") or "",
                           caixa.get_attribute("aria-label") or ""}
                if not rotulos & pesquisa:
                    return caixa
        return None

    def _item_tabela(self):
        tabela, descricao = re.escape(self.textos["tabela"]), re.escape(self.textos["tabela_descricao"])
        padrao = re.compile(rf"\b{tabela}\b.*{descricao}|{descricao}.*\b{tabela}\b", re.IGNORECASE)
        return self._candidatos(padrao)

    def _selecionar_tabela(self) -> None:
        if not self._item_tabela():
            caixa = self._esperar(self._caixa_tabela, self._passo, "selecionar_tabela", "campo da tabela")
            caixa.fill(self.textos["tabela"])
            caixa.press("Enter")
        self._esperar(self._item_tabela, self._passo, "selecionar_tabela",
                      f"tabela {self.textos['tabela']} — {self.textos['tabela_descricao']}")
        tabela, descricao = re.escape(self.textos["tabela"]), re.escape(self.textos["tabela_descricao"])
        self._clicar(re.compile(rf"\b{tabela}\b.*{descricao}|{descricao}.*\b{tabela}\b", re.IGNORECASE),
                     "selecionar_tabela")
        consulta_aberta = lambda: self._botao_novo(self.textos["exportar"] + self.textos["filtro_abrir"])
        self._esperar(lambda: consulta_aberta() or self._botao_novo(self.textos["confirmar"]), self._passo,
                      "selecionar_tabela", "confirmação da tabela ou grade da consulta")
        if not consulta_aberta():
            self._clicar(self.textos["confirmar"], "selecionar_tabela")
        self._esperar(consulta_aberta, self._passo, "selecionar_tabela", "grade da consulta SE2 (Filtrar/Exp. CSV)")

    def _aplicar_filtro(self) -> None:
        campo, operador = self.textos["filtro_campo"], self.textos["filtro_operador"]
        self._marcar_anteriores([t for t in self.textos["filtro_aplicar"] if t not in self.textos["filtro_abrir"]])
        self._clicar(self.textos["filtro_abrir"], "filtro")
        self._esperar(lambda: self._algum_visivel([campo], True) or self._opcao_em_lista(campo), self._passo,
                      "filtro", f"campo {campo} no gerenciador de filtros")
        self._escolher(campo, "filtro")
        self._esperar(lambda: self._algum_visivel([operador], True) or self._opcao_em_lista(operador), self._passo,
                      "filtro", f"operador {operador}")
        self._escolher(operador, "filtro")
        self._clicar(self.textos["filtro_aplicar"], "filtro")
        # Filtro aplicado = gerenciador fechado, grade de volta e o filtro visível na tela.
        self._esperar(lambda: self._botao_novo(self.textos["exportar"]) and self._algum_visivel([operador])
                      and not self._lista_aberta(), self._passo, "filtro", f"filtro \"{campo} = {operador}\" aplicado")

    def _opcao_em_lista(self, valor: str) -> bool:
        for quadro in self.pagina.frames:
            for lista in self._visiveis(quadro.locator("select"), 10):
                if valor in lista.evaluate("s => Array.from(s.options).map(o => o.label || o.text)"):
                    return True
        return False

    def _lista_aberta(self) -> bool:
        return any(self._visiveis(q.locator("select"), 5) for q in self.pagina.frames)

    def _conferir_filtros(self) -> dict:
        outros = [t for t in self.textos.get("outros_filtros", []) if t and self._texto_visivel(t)]
        if outros:
            raise ErroNavegador("conferir_filtros", "outros filtros ativos na consulta: " + ", ".join(outros)
                                + ". Remova-os no TOTVS; a coleta não exporta um recorte diferente do combinado.")
        filiais = self.textos.get("filiais_todas", [])
        return {
            "filtro": f"{self.textos['filtro_campo']} = {self.textos['filtro_operador']}",
            "filtro_confirmado": True,
            "outros_filtros_verificados": bool(self.textos.get("outros_filtros")),
            "filiais_confirmadas": bool(self._algum_visivel(filiais)) if filiais else None,
        }

    def _exportar(self) -> tuple[Path, str]:
        """Clica em Exp. CSV e captura o download desta execução pelo próprio Chrome."""
        destino = self.pasta / "download"
        destino.mkdir(parents=True, exist_ok=True)
        cdp = self.navegador.new_browser_cdp_session()
        eventos: dict[str, dict] = {}
        cdp.on("Browser.downloadWillBegin", lambda e: eventos.setdefault(e["guid"], {}).update(
            nome=e.get("suggestedFilename") or "exportacao.csv", estado="inicio"))
        cdp.on("Browser.downloadProgress", lambda e: eventos.setdefault(e["guid"], {}).update(
            estado=e["state"], total=e.get("totalBytes"), recebido=e.get("receivedBytes")))
        cdp.send("Browser.setDownloadBehavior", {"behavior": "allowAndName", "downloadPath": str(destino),
                                                 "eventsEnabled": True})
        try:
            # Só valem confirmações que aparecerem depois do clique em Exp. CSV.
            self._marcar_anteriores(self.textos["confirmar_exportacao"])
            self._clicar(self.textos["exportar"], "exportar")
            confirmados: set[str] = set()

            def concluido():
                for guid, dados in eventos.items():
                    if dados.get("estado") == "completed":
                        return guid
                    if dados.get("estado") == "canceled":
                        raise ErroNavegador("exportar", "o download foi cancelado pelo navegador.", temporaria=True)
                if not eventos:  # diálogo de confirmação da exportação, se houver
                    for texto in self.textos["confirmar_exportacao"]:
                        if texto not in confirmados and self._candidatos(texto):
                            confirmados.add(texto)
                            self._clicar([texto], "exportar")
                            break
                return None

            guid = self._esperar(concluido, float(self.nav["tempo_exportacao_minutos"]) * 60, "exportar",
                                 "download da exportação")
        finally:
            try:
                cdp.send("Browser.setDownloadBehavior", {"behavior": "default"})
                cdp.detach()
            except Exception:  # noqa: BLE001
                pass
        dados = eventos[guid]
        bruto = destino / guid
        if not bruto.is_file():
            raise ErroNavegador("exportar", "o navegador concluiu o download, mas o arquivo não está na pasta "
                                            "desta execução.", temporaria=True)
        tamanho = bruto.stat().st_size
        if tamanho == 0 or (dados.get("total") and tamanho != dados["total"]):
            raise ErroNavegador("exportar", f"arquivo incompleto ({tamanho} de {dados.get('total')} bytes).",
                                temporaria=True)
        nome = re.sub(r"[^\w.\- ]+", "_", Path(dados["nome"]).name)[:120] or "exportacao.csv"
        final = self.pasta / f"{datetime.now():%Y%m%d-%H%M%S}_{nome}"
        bruto.replace(final)
        self.etapas.append({"etapa": "exportar", "arquivo": final.name, "bytes": tamanho})
        return final, nome


def resumo_etapas(etapas: list[dict]) -> str:
    return json.dumps(etapas, ensure_ascii=False)[:2000]


def limpar_diagnosticos(pasta: Path, dias: float) -> None:
    if not pasta.exists():
        return
    limite = time.time() - dias * 86400
    for item in pasta.iterdir():
        try:
            if item.is_dir() and item.stat().st_mtime < limite:
                shutil.rmtree(item)
        except OSError:
            log.warning("Não foi possível apagar o diagnóstico antigo %s.", item.name)
