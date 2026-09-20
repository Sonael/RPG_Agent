"""
test_barra_navegador.py

A barra lateral nova, no navegador.

Desktop: o relance (local, capítulo e hora numa linha; uma linha por herói
com a vida e as marcas; a missão principal; os avisos do verificador só
quando há algum), os atalhos com contador, a engrenagem com o que saiu da
barra, a coluna recolhível que lembra a escolha, e tudo cabendo sem rolagem.

Celular: a faixa sob o título, a barra de baixo com Grupo, Missões, Mapa,
Diário e Mais, e a gaveta do "Mais" com o relance e todos os atalhos.

Depende do Playwright, que não está em requirements-dev.txt. Sem ele o arquivo
é pulado:

    pip install playwright && playwright install chromium
"""
import copy
import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

pytest.importorskip("playwright.sync_api",
                    reason="Playwright não instalado — veja o docstring")

sys.path.insert(0, str(RAIZ / "scripts"))

pytestmark = pytest.mark.slow

CELULAR = {"largura": 390, "altura": 844}


@pytest.fixture(scope="module")
def app_no_ar():
    import capturar_telas as cap

    campanha = json.loads((RAIZ / "scripts" / "temp.json").read_text(encoding="utf-8"))
    nome = campanha.get("name") or "Crônicas de Oakhaven"
    campanha["name"] = nome
    url, parar = cap._subir_servidor(campanha, nome)
    try:
        yield url, nome, cap
    finally:
        parar()


@pytest.fixture
def estado(app_no_ar):
    _, _, cap = app_no_ar
    e = copy.deepcopy(cap.MUNDO_ONDA4)
    cap._mesclar(e, copy.deepcopy(cap.GRUPO))
    e.update({"saque_proposto": None, "descanso_proposto": None,
              "combat_state": {"is_active": False, "initiative_order": []},
              "current_location": "Palácio Real de Luminas", "chapter": 2,
              "dnd_mode": True, "campaign_type": "dnd"})
    return e


@pytest.fixture
def abrir(app_no_ar, estado):
    from playwright.sync_api import sync_playwright
    import requests

    url, nome, cap = app_no_ar
    with sync_playwright() as pw:
        nav = pw.chromium.launch()

        def _abrir(dados=None, largura=1440, altura=980, esperar="#sb-herois .sb-heroi-vida",
                   limpar_memoria=True):
            # A semente das capturas apaga a memória das telas e a da barra
            # recolhida a cada carregamento, porque ali um navegador só tira
            # todas as capturas. O teste que prova que a barra lembra precisa
            # dela desligada.
            requests.post(f"{url}/__estado", json=dados or estado, timeout=10)
            ctx = nav.new_context(viewport={"width": largura, "height": altura})
            ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO,
                                                       limpar_memoria_de_telas=limpar_memoria))
            pg = ctx.new_page()
            erros = []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
            pg.goto(f"{url}/game.html", wait_until="networkidle")
            cap._sanear(pg)
            if esperar:
                pg.wait_for_selector(esperar, state="attached", timeout=8000)
            pg.wait_for_timeout(300)
            return pg, erros

        yield _abrir
        nav.close()


def _heroi(nome):
    return f"#sb-herois .sb-heroi[data-nome='{nome}']"


# ---------------------------------------------------------------------------
# Desktop: relance
# ---------------------------------------------------------------------------

def test_relance_onde_capitulo_e_hora_numa_linha(abrir):
    pg, erros = abrir()
    assert pg.inner_text("#sb-location-nome") == "Palácio Real de Luminas"
    assert pg.inner_text("#ws-chapter-num") == "2"
    assert pg.inner_text("#sb-tempo-texto") == "Dia 4, 20h"
    assert "noite" in pg.get_attribute("#sb-tempo", "title")
    caixas = pg.evaluate("() => ['sb-location', 'ws-chapter', 'sb-tempo']"
                         ".map(id => document.getElementById(id).getBoundingClientRect())"
                         ".map(r => ({top: Math.round(r.top), left: r.left, right: r.right}))")
    assert len({c["top"] for c in caixas}) == 1, caixas
    # Lado a lado, sem um passar por cima do outro, e dentro da barra.
    assert caixas[0]["right"] <= caixas[1]["left"] + 1 and caixas[1]["right"] <= caixas[2]["left"] + 1, caixas
    limite = pg.evaluate("() => document.querySelector('#sidebar .sidebar-content').getBoundingClientRect().right")
    assert caixas[2]["right"] <= limite + 1, (caixas, limite)
    # E o texto do capítulo e da hora aparece inteiro.
    cortados = pg.evaluate("() => ['ws-chapter', 'sb-tempo'].map(id => document.getElementById(id))"
                           ".filter(e => e.scrollWidth > e.clientWidth + 1).map(e => e.id)")
    assert cortados == [], cortados
    assert not erros, erros[:3]


# Campanha recém-criada: o mestre ainda não avançou o tempo nenhuma vez, e a
# hora precisa aparecer assim mesmo (memory.RELOGIO_INICIAL).

def test_campanha_nova_ja_mostra_a_hora(abrir, estado):
    sem_relogio = copy.deepcopy(estado)
    sem_relogio["relogio"] = {}
    pg, erros = abrir(sem_relogio)
    assert "hidden" not in (pg.get_attribute("#sb-tempo", "class") or "")
    assert pg.inner_text("#sb-tempo-texto") == "Dia 1, 08h"
    assert "manhã" in pg.get_attribute("#sb-tempo", "title")
    assert not erros, erros[:3]


def test_local_capitulo_e_hora_abrem_as_telas(abrir):
    pg, _ = abrir()
    pg.click("#sb-location")
    pg.wait_for_function("() => document.getElementById('lcl-nome').textContent === 'Palácio Real de Luminas'",
                         timeout=5000)
    pg.evaluate("() => window.Locais._fechar()")
    pg.click("#ws-chapter")
    pg.wait_for_function(
        "() => (document.querySelector('#diario-overlay:not(.hidden) .dia-pagina-titulo') || {}).textContent"
        " === 'Capítulo 2'", timeout=5000)
    pg.evaluate("() => window.Diario._fechar()")
    pg.click("#sb-tempo")
    pg.wait_for_selector("#grupo-overlay:not(.hidden) .grp-cartao", timeout=5000)


def test_uma_linha_por_heroi_com_a_vida_do_motor(abrir):
    pg, erros = abrir()
    motor = {h["nome"]: h for h in pg.evaluate("() => window.Barra._estado().grupo.herois")}
    nomes = [el.get_attribute("data-nome") for el in pg.query_selector_all("#sb-herois .sb-heroi")]
    assert nomes == list(motor)
    helena = pg.inner_text(_heroi("Helena"))
    assert f"{motor['Helena']['vida']['atual']}/{motor['Helena']['vida']['max']}" in helena
    assert "Envenenado" in helena
    assert "sb-vida-alerta" in pg.get_attribute(f"{_heroi('Helena')} .sb-heroi-vida", "class")
    assert pg.locator(f"{_heroi('Stelar')} .levelup-badge").count() == 1
    assert pg.locator(f"{_heroi('Natasha')} .sb-marca").count() == 0
    assert not erros, erros[:3]


def test_nome_abre_a_ficha_e_selo_de_nivel_abre_o_aviso(abrir):
    pg, _ = abrir()
    pg.click(f"{_heroi('Natasha')} .sb-heroi-nome")
    pg.wait_for_function("() => document.getElementById('hro-nome').textContent === 'Natasha'", timeout=5000)
    pg.evaluate("() => window.Herois._fechar()")
    pg.click(f"{_heroi('Stelar')} .levelup-badge")
    pg.wait_for_selector("#levelup-popup", timeout=5000)


def test_carga_pesada_aparece_como_marca(abrir, estado):
    estado["characters"]["natasha"]["inventario"][0]["peso"] = 40
    pg, _ = abrir(estado)
    pg.wait_for_selector(f"{_heroi('Natasha')} .sb-marca:has-text('sobrecarregado')", timeout=5000)


def test_missao_principal_com_progresso(abrir):
    pg, _ = abrir()
    # A ativa do capítulo mais recente: a dívida de Torbin (capítulo 3).
    assert pg.get_attribute("#sb-missao", "data-titulo") == "A dívida de Torbin"
    assert "0/1" in pg.inner_text("#sb-missao")
    pg.click("#sb-missao")
    pg.wait_for_selector("#missoes-overlay:not(.hidden) .msn-cartao[data-titulo='A dívida de Torbin'].msn-destaque",
                         timeout=5000)


def test_sem_missao_ativa_o_bloco_some(abrir, estado):
    for m in estado["quests"].values():
        m["status"] = "concluida"
    pg, _ = abrir(estado)
    assert pg.is_hidden("#sb-missao")
    assert pg.locator("#sb-atalho-missoes .sb-atalho-conta").count() == 0


# ---------------------------------------------------------------------------
# Desktop: atalhos, avisos, engrenagem, recolher
# ---------------------------------------------------------------------------

def test_atalhos_abrem_as_telas(abrir):
    pg, erros = abrir()
    telas = {
        "grupo": "#grupo-overlay", "missoes": "#missoes-overlay", "mapa": "#mapa-overlay",
        "diario": "#diario-overlay", "personagens": "#elenco-overlay", "mochila": "#inventory-overlay",
    }
    for tela, overlay in telas.items():
        pg.click(f"#sb-atalho-{tela}")
        pg.wait_for_selector(f"{overlay}:not(.hidden)", timeout=5000)
        # A Mochila não fecha com Esc; as outras telas sim.
        if tela == "mochila":
            pg.evaluate("() => window.Inventory._close()")
        else:
            pg.keyboard.press("Escape")
        pg.wait_for_selector(overlay, state="hidden", timeout=5000)
    assert not erros, erros[:3]


def test_contadores(abrir):
    pg, _ = abrir()
    assert pg.inner_text("#sb-atalho-missoes .sb-atalho-conta") == "2"
    assert pg.inner_text("#sb-atalho-grupo .sb-atalho-conta") == "1", "Stelar com nível pendente"
    assert "sb-atalho-alerta" in pg.get_attribute("#sb-atalho-grupo .sb-atalho-conta", "class")
    outros = pg.evaluate("() => window._lastMem.characters.length")
    assert pg.inner_text("#sb-atalho-personagens .sb-atalho-conta") == str(outros)
    assert pg.locator("#sb-atalho-mapa .sb-atalho-conta").count() == 0


def test_avisos_so_quando_ha_algum(abrir):
    pg, erros = abrir()
    assert pg.is_hidden("#sb-avisos")
    # O que chega do servidor é o texto do jogador, com um título curto.
    pg.evaluate("""() => renderViolations([
        {severity: 'erro', rule: 'dead_character_active', titulo: 'Alguém que já morreu aparece em cena',
         message: 'A campanha registra Bruna como morta, mas ela age agora.', detail: 'Bruna ergue a espada'},
        {severity: 'aviso', rule: 'unknown_location', titulo: 'Lugar novo ainda fora do mapa',
         message: '“Ponte Quebrada” ainda não está no mapa da campanha.', detail: 'a Ponte Quebrada'}])""")
    pg.wait_for_selector("#sb-avisos-botao", timeout=3000)
    assert "2 avisos sobre a história" in pg.inner_text("#sb-avisos-botao")
    assert "sb-avisos-erro" in pg.get_attribute("#sb-avisos-botao", "class")
    assert pg.locator("#sb-avisos .violation-item").count() == 0, "a lista começa fechada"
    pg.click("#sb-avisos-botao")
    assert pg.locator("#sb-avisos .violation-item").count() == 2
    pg.click("#sb-avisos .sb-aviso-fechar >> nth=0")
    assert "1 aviso sobre a história" in pg.inner_text("#sb-avisos-botao")
    # O painel mostra o título e o texto do jogador, nunca o nome da regra.
    lista = pg.inner_text("#sb-avisos .violation-item")
    assert "Lugar novo ainda fora do mapa" in lista
    assert "unknown_location" not in lista, lista
    pg.click("#sb-avisos button:has-text('Limpar todos')")
    assert pg.is_hidden("#sb-avisos")
    assert not erros, erros[:3]


def test_engrenagem_tem_o_que_saiu_da_barra(abrir):
    pg, erros = abrir()
    pg.evaluate("() => toggleSettingsPanel()")
    pg.wait_for_selector("#settings-panel.open #settings-campanha", timeout=5000)
    secao = pg.inner_text("#settings-campanha")
    assert "Modo de combate" in secao and "Uso do modelo" in secao and "Requisições" in secao
    assert pg.is_visible("#settings-menu-principal") and pg.is_visible("#settings-sair")
    pg.click("#combat-mode-toggle .cm-opt[data-mode='tela']")
    pg.wait_for_selector("#combat-mode-toggle .cm-opt.active[data-mode='tela']", timeout=5000)
    assert "tela tática" in pg.inner_text("#combat-mode-hint")
    pg.click("#combat-mode-toggle .cm-opt[data-mode='narrado']")
    pg.wait_for_selector("#combat-mode-toggle .cm-opt.active[data-mode='narrado']", timeout=5000)
    assert not erros, erros[:3]


def test_o_que_saiu_nao_esta_mais_na_pagina_e_a_barra_nao_rola(abrir):
    pg, _ = abrir()
    for velho in ("#tab-mundo", "#tab-enciclopedia", "#tab-diario", ".tab-btn", "#sb-flags",
                  "#sb-summary", "#sb-violations", ".bottom-actions", "#mobile-menu-btn"):
        assert pg.locator(velho).count() == 0, f"{velho} ainda está na página"
    rolagem = pg.evaluate("() => { const c = document.querySelector('#sidebar .sidebar-content');"
                          " return [c.scrollHeight, c.clientHeight]; }")
    assert rolagem[0] <= rolagem[1] + 1, f"a barra precisa de rolagem: {rolagem}"
    cortados = pg.evaluate("() => [...document.querySelectorAll('.sb-atalho-rotulo')]"
                           ".filter(e => e.scrollWidth > e.clientWidth + 1).map(e => e.textContent)")
    assert cortados == [], f"rótulos cortados: {cortados}"


def test_recolher_e_lembrar(abrir):
    pg, erros = abrir(limpar_memoria=False)
    largura = pg.evaluate("() => document.getElementById('sidebar').getBoundingClientRect().width")
    pg.click("#sb-recolher")
    pg.wait_for_function("() => document.body.classList.contains('barra-recolhida')", timeout=3000)
    pg.wait_for_timeout(400)
    estreita = pg.evaluate("() => document.getElementById('sidebar').getBoundingClientRect().width")
    assert estreita < largura / 3, (largura, estreita)
    assert pg.is_hidden("#sb-relance") and pg.is_hidden("#sb-atalho-mapa .sb-atalho-rotulo")
    assert pg.get_attribute("#sb-recolher", "aria-expanded") == "false"
    pg.click("#sb-atalho-mapa")
    pg.wait_for_selector("#mapa-overlay:not(.hidden)", timeout=5000)
    pg.keyboard.press("Escape")

    pg.reload(wait_until="networkidle")
    pg.wait_for_function("() => document.body.classList.contains('barra-recolhida')", timeout=5000)
    pg.click("#sb-recolher")
    pg.wait_for_function("() => !document.body.classList.contains('barra-recolhida')", timeout=3000)
    assert pg.evaluate("() => localStorage.getItem('rpg_barra_recolhida')") == "0"
    assert not erros, erros[:3]


def test_campanha_sem_regras_sem_mochila_e_grupo_no_indice(abrir, estado):
    estado.update({"dnd_mode": False, "campaign_type": "fantasia"})
    pg, erros = abrir(estado, esperar="#sb-herois .sb-heroi")
    assert pg.locator("#sb-atalho-mochila").count() == 0
    assert pg.locator("#sb-herois .sb-heroi-vida").count() == 0
    assert pg.locator("#sb-herois .sb-heroi").count() == 3
    pg.click("#sb-atalho-grupo")
    pg.wait_for_selector("#elenco-overlay:not(.hidden) .elc-filtro-ativo[data-filtro='grupo']", timeout=5000)
    assert not erros, erros[:3]


# ---------------------------------------------------------------------------
# Celular
# ---------------------------------------------------------------------------

def test_celular_faixa_e_barra_de_baixo(abrir, estado):
    # Nome longo de propósito: é com ele que a hora sumia nas reticências.
    estado["current_location"] = "Palácio Real de Luminas - Ante-sala de Prata"
    pg, erros = abrir(estado, **CELULAR)
    assert pg.is_hidden("#sidebar") or not pg.evaluate(
        "() => document.getElementById('sidebar').classList.contains('active')")
    assert pg.locator("#mobile-menu-btn").count() == 0
    faixa = pg.inner_text("#faixa-relance")
    assert "Palácio Real de Luminas" in faixa and "Dia 4, 20h" in faixa
    # A hora aparece inteira, mesmo com o nome do local cortado: o que está
    # na tela no fim do texto da hora é a própria hora, não um corte por cima.
    hora = pg.evaluate("""() => {
        const h = document.querySelector('#faixa-relance .faixa-hora');
        const r = h.getBoundingClientRect();
        const pontos = [[r.left + 2, r.top + r.height / 2], [r.right - 2, r.top + r.height / 2]];
        return pontos.map(([x, y]) => { const e = document.elementFromPoint(x, y); return !!e && h.contains(e); });
    }""")
    assert hora == [True, True], "a hora da faixa está cortada ou coberta"
    assert pg.locator("#faixa-relance .faixa-heroi").count() == 3
    botoes = [el.get_attribute("data-tela") for el in pg.query_selector_all("#barra-inferior .bi-botao")]
    assert botoes == ["grupo", "missoes", "mapa", "diario", "mais"]
    assert pg.inner_text("#barra-inferior .bi-botao[data-tela='missoes'] .bi-conta") == "2"
    # A barra de baixo fica dentro da tela, abaixo do campo de texto.
    caixas = pg.evaluate("() => ({barra: document.getElementById('barra-inferior').getBoundingClientRect().bottom,"
                         " campo: document.getElementById('chat-input').getBoundingClientRect().bottom,"
                         " altura: window.innerHeight})")
    assert caixas["campo"] < caixas["barra"] <= caixas["altura"] + 1, caixas

    pg.click("#barra-inferior .bi-botao[data-tela='missoes']")
    pg.wait_for_selector("#missoes-overlay:not(.hidden)", timeout=5000)
    assert not erros, erros[:3]



# O Playwright não desenha as barras do celular; simulamos as duas coisas que
# elas fazem com a página. A barra de gestos ou de botões do sistema, quando o
# navegador desenha por baixo dela, vira uma margem segura (safe-area) que o
# Chromium deixa emular. A barra de endereço do navegador e a de sistema
# encolhem a área visível sem mudar o 100vh: aqui, visualViewport.height
# menor que a janela, que é o que o navegador informa nesse caso.

TELAS_CHEIAS = ["cbt-frame", "shp-frame", "lvl-frame", "inv-frame", "grm-frame", "rst-frame",
                "lcl-frame", "psn-frame", "hro-frame", "msn-frame", "map-frame", "grp-frame",
                "dia-frame", "elc-frame", "lot-frame"]


def _encolher_area_visivel(pg, altura):
    pg.evaluate("""(h) => {
        Object.defineProperty(window.visualViewport, 'height', {get: () => h, configurable: true});
        window.visualViewport.dispatchEvent(new Event('resize'));
    }""", altura)
    pg.wait_for_timeout(200)


def test_celular_barra_de_baixo_fora_da_margem_do_sistema(abrir):
    pg, erros = abrir(**CELULAR)
    cdp = pg.context.new_cdp_session(pg)
    cdp.send("Emulation.setSafeAreaInsetsOverride", {"insets": {"bottom": 34}})
    pg.wait_for_timeout(200)
    medida = pg.evaluate("""() => {
        const barra = document.getElementById('barra-inferior');
        return {fundo: barra.getBoundingClientRect().bottom, altura: innerHeight,
                botoes: [...barra.querySelectorAll('.bi-botao')].map(b => b.getBoundingClientRect().bottom)};
    }""")
    # O fundo da barra vai até a borda, mas os botões ficam acima da margem.
    assert medida["fundo"] >= medida["altura"] - 1, medida
    assert max(medida["botoes"]) <= medida["altura"] - 34, medida
    assert not erros, erros[:3]


def test_celular_nada_fica_atras_das_barras_do_navegador_e_do_sistema(abrir, estado):
    pg, erros = abrir(estado, **CELULAR)
    visivel = CELULAR["altura"] - 90
    _encolher_area_visivel(pg, visivel)
    caixas = pg.evaluate("""() => ({
        barra: document.getElementById('barra-inferior').getBoundingClientRect(),
        campo: document.getElementById('chat-input').getBoundingClientRect().bottom})""")
    assert caixas["barra"]["bottom"] <= visivel + 1, (caixas, visivel)
    assert caixas["campo"] <= caixas["barra"]["top"] + 1, caixas

    # As telas da barra de baixo: o rodapé com os botões dentro da área visível.
    for tela, (overlay, fechar) in {"grupo": ("grupo-overlay", "Grupo"), "missoes": ("missoes-overlay", "Missoes"),
                                    "mapa": ("mapa-overlay", "Mapa"), "diario": ("diario-overlay", "Diario")}.items():
        pg.click(f"#barra-inferior .bi-botao[data-tela='{tela}']")
        pg.wait_for_selector(f"#{overlay}:not(.hidden) .lcl-rodape button", timeout=5000)
        pg.wait_for_timeout(300)
        fundo = pg.evaluate("""(id) => {
            const o = document.getElementById(id);
            const botoes = [...o.querySelectorAll('.lcl-rodape button')].filter(b => b.offsetParent);
            return Math.max(...botoes.map(b => b.getBoundingClientRect().bottom));
        }""", overlay)
        assert fundo <= visivel + 1, f"os botões do rodapé de {tela} ficam atrás da barra ({fundo} > {visivel})"
        pg.evaluate(f"() => window.{fechar}._fechar()")
        pg.wait_for_selector(f"#{overlay}.hidden", state="attached", timeout=3000)

    # Todas as telas cheias do celular têm a altura da área visível.
    alturas = pg.evaluate("""(ids) => ids.map(id => {
        let el = document.getElementById(id), criado = false;
        if (!el) { el = document.createElement('div'); el.id = id; document.body.appendChild(el); criado = true; }
        const h = parseFloat(getComputedStyle(el).height);
        if (criado) el.remove();
        return [id, h];
    })""", TELAS_CHEIAS)
    altas = [(i, h) for i, h in alturas if h > visivel + 1]
    assert altas == [], altas

    # A gaveta do "Mais" e a engrenagem, com o Sair alcançável.
    pg.click("#bi-mais")
    pg.wait_for_function("() => document.getElementById('sidebar').classList.contains('active')", timeout=3000)
    pg.wait_for_timeout(400)
    gaveta = pg.evaluate("() => document.getElementById('sidebar').getBoundingClientRect().bottom")
    assert gaveta <= visivel + 1, (gaveta, visivel)
    pg.evaluate("() => window.toggleSidebar(true)")
    pg.evaluate("() => toggleSettingsPanel()")
    pg.wait_for_selector("#settings-panel.open #settings-sair", timeout=5000)
    pg.wait_for_timeout(400)
    pg.locator("#settings-sair").scroll_into_view_if_needed()
    sair = pg.evaluate("""() => ({painel: document.getElementById('settings-panel').getBoundingClientRect().bottom,
                                 sair: document.getElementById('settings-sair').getBoundingClientRect().bottom})""")
    assert sair["painel"] <= visivel + 1 and sair["sair"] <= visivel + 1, (sair, visivel)
    assert not erros, erros[:3]


def test_celular_teclado_aberto_esconde_a_barra_de_baixo(abrir):
    pg, erros = abrir(**CELULAR)
    # O jogo já dá foco ao campo ao abrir; sem teclado, a barra continua.
    pg.focus("#chat-input")
    pg.wait_for_timeout(100)
    assert pg.is_visible("#barra-inferior")
    # A barra de endereço aparecendo encolhe pouco a área: a barra fica.
    _encolher_area_visivel(pg, CELULAR["altura"] - 56)
    assert pg.is_visible("#barra-inferior")
    # O teclado encolhe muito: a barra sai e o campo fica no fim da área visível.
    visivel = CELULAR["altura"] - 330
    _encolher_area_visivel(pg, visivel)
    assert pg.is_hidden("#barra-inferior")
    campo = pg.evaluate("() => document.getElementById('input-area').getBoundingClientRect().bottom")
    assert visivel - 40 <= campo <= visivel + 1, (campo, visivel)
    # Fechou o teclado (tirou o foco e a área voltou): a barra volta.
    pg.evaluate("() => document.getElementById('chat-input').blur()")
    _encolher_area_visivel(pg, CELULAR["altura"])
    assert pg.is_visible("#barra-inferior")
    assert not erros, erros[:3]


def test_celular_a_pilula_fica_acima_do_campo_de_texto(abrir, estado, app_no_ar):
    # A pílula é medida pelo topo do campo de texto, e a barra de baixo mexe
    # nesse topo: ela nasce vazia e ganha altura quando a barra desenha os
    # botões, e some quando o teclado abre. Sem refazer a conta, a pílula fica
    # com a medida velha e cai por cima do campo.
    _, _, cap = app_no_ar
    cap._mesclar(estado, copy.deepcopy(cap.DESCANSO_CURTO))
    pg, erros = abrir(estado, **CELULAR)
    pg.wait_for_selector("#rest-overlay:not(.hidden)", timeout=5000)
    pg.evaluate("() => window.Rest._close()")
    pg.wait_for_selector("#rst-reopen:not(.hidden)", timeout=5000)
    pg.wait_for_timeout(300)

    def medir():
        return pg.evaluate("""() => ({
            pilula: document.getElementById('rst-reopen').getBoundingClientRect().bottom,
            campo: document.getElementById('input-area').getBoundingClientRect().top})""")

    com_barra = medir()
    assert com_barra["campo"] - 40 <= com_barra["pilula"] <= com_barra["campo"] + 1, com_barra
    # Teclado aberto: a barra de baixo sai e o campo desce; a pílula desce junto.
    pg.evaluate("() => document.documentElement.classList.add('teclado-aberto')")
    pg.wait_for_timeout(300)
    sem_barra = medir()
    assert sem_barra["campo"] > com_barra["campo"], (com_barra, sem_barra)
    assert sem_barra["campo"] - 40 <= sem_barra["pilula"] <= sem_barra["campo"] + 1, sem_barra
    assert not erros, erros[:3]


def test_celular_mais_abre_a_gaveta_com_o_relance_e_os_atalhos(abrir):
    pg, erros = abrir(**CELULAR)
    pg.click("#bi-mais")
    pg.wait_for_function("() => document.getElementById('sidebar').classList.contains('active')", timeout=3000)
    pg.wait_for_timeout(400)
    assert pg.is_visible("#sb-herois .sb-heroi[data-nome='Helena']")
    assert pg.is_visible("#sb-missao")
    # Os seis de sempre e, numa fantasia, "Mundo" (renome, companheiros, lendas).
    assert pg.locator("#sb-atalhos .sb-atalho").count() == 7
    assert pg.is_visible("#sb-atalho-mundo")
    assert pg.is_hidden("#sb-recolher")
    pg.click("#sb-atalho-personagens")
    pg.wait_for_selector("#elenco-overlay:not(.hidden)", timeout=5000)
    assert not pg.evaluate("() => document.getElementById('sidebar').classList.contains('active')"), \
        "a gaveta ficou aberta atrás da tela"
    assert not erros, erros[:3]


def test_celular_tocar_na_faixa_abre_a_gaveta(abrir):
    pg, _ = abrir(**CELULAR)
    pg.click("#faixa-relance")
    pg.wait_for_function("() => document.getElementById('sidebar').classList.contains('active')", timeout=3000)


def test_o_contador_nao_cobre_o_icone_nem_corta_o_rotulo(abrir):
    """
    O contador nasceu sobre o ícone (top 3px, left 20px): cobria metade do
    desenho e encostava no rótulo. Na direita, ele precisa do espaço dele —
    sem isso, "Personagens" fica cortado.
    """
    pg, erros = abrir()
    medidas = pg.evaluate("""() => [...document.querySelectorAll('.sb-atalho')].map(b => {
        const c = b.querySelector('.sb-atalho-conta');
        if (!c) return null;
        const rot = b.querySelector('.sb-atalho-rotulo');
        const cr = c.getBoundingClientRect();
        const bate = (x, y) => x.left < y.right - 1 && y.left < x.right - 1
                            && x.top < y.bottom - 1 && y.top < x.bottom - 1;
        return {tela: b.dataset.tela,
                sobre_icone: bate(cr, b.querySelector('svg').getBoundingClientRect()),
                sobre_rotulo: bate(cr, rot.getBoundingClientRect()),
                cortado: rot.scrollWidth > rot.clientWidth + 1,
                dentro: cr.right <= b.getBoundingClientRect().right - 1};
    }).filter(Boolean)""")
    assert medidas, "nenhum atalho com contador no estado de teste"
    for m in medidas:
        assert not m["sobre_icone"], m
        assert not m["sobre_rotulo"], m
        assert not m["cortado"], m
        assert m["dentro"], m
    assert not erros, erros[:3]


def test_recolhida_o_contador_vai_para_o_canto(abrir):
    pg, _ = abrir(limpar_memoria=False)
    pg.evaluate("() => window.Barra.alternar()")
    pg.wait_for_function("() => document.body.classList.contains('barra-recolhida')", timeout=3000)
    r = pg.evaluate("""() => { const b = document.getElementById('sb-atalho-missoes');
        const c = b.querySelector('.sb-atalho-conta').getBoundingClientRect();
        const cb = b.getBoundingClientRect();
        return {acima_do_meio: c.top < cb.top + cb.height / 2, dentro: c.right <= cb.right + 1}; }""")
    assert r == {"acima_do_meio": True, "dentro": True}, r
    pg.evaluate("() => window.Barra.alternar()")
