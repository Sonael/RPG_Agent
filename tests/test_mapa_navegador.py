"""
test_mapa_navegador.py

O mapa do mundo no navegador: abre pelo atalho Mapa da barra lateral e pela
ficha do local, mostra o caminho até o grupo aberto, abre e fecha ramos,
busca por lugar e por pessoa, manda "Vamos até X." ao mestre e leva às
fichas do local e do personagem. As telas que abrem sozinhas esperam o mapa
fechar.

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
def pagina(app_no_ar):
    from playwright.sync_api import sync_playwright
    import requests

    url, nome, cap = app_no_ar
    estado = copy.deepcopy(cap.MAPA)
    estado["saque_proposto"] = None
    requests.post(f"{url}/__estado", json=estado, timeout=10)
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        ctx = nav.new_context(viewport={"width": 1440, "height": 980})
        ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO))
        pg = ctx.new_page()
        erros = []
        pg.on("pageerror", lambda e: erros.append(str(e)))
        pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
        pg.goto(f"{url}/game.html", wait_until="networkidle")
        cap._sanear(pg)
        pg.wait_for_timeout(800)
        pg.evaluate("() => { window.__enviados = [];"
                    " window.sendToAgent = async (t) => { window.__enviados.push(t); }; }")
        yield pg, erros, url
        nav.close()


def _no(nome):
    return f"#map-arvore {_so_no(nome)}"


def _so_no(nome):
    return f".map-no[data-nome='{nome}']"


def _abrir(pg):
    pg.evaluate("() => window.Mapa._abrir('')")
    pg.wait_for_selector("#mapa-overlay:not(.hidden) .map-no-grupo", timeout=5000)


def test_ver_o_mapa_abre_com_o_caminho_do_grupo_aberto(pagina):
    pg, erros, _ = pagina
    pg.click("#sb-atalho-mapa")
    pg.wait_for_selector("#mapa-overlay:not(.hidden) .map-no-grupo", timeout=5000)
    assert pg.get_attribute(".map-no-grupo", "data-nome") == "Praça de Cliviate"
    assert "Cliviate" in pg.inner_text("#map-onde") and "Praça de Cliviate" in pg.inner_text("#map-onde")
    # Cliviate aberta: os lugares de dentro aparecem, com as lojas.
    assert pg.locator(f"{_no('Cliviate')} > .map-filhos > .map-no").count() == 4
    assert "loja" in pg.inner_text(f"{_no('Forja de Cliviate')} > .map-linha")
    # Quem está na praça, e o grupo marcado.
    praca = pg.inner_text(f"{_no('Praça de Cliviate')}")
    assert "grupo aqui" in praca.lower() and "Guarda Tiel" in praca and "Velha Nana" in praca
    # A um passo: lojas e taverna ao lado, a cidade como saída.
    alcance = [el.get_attribute("data-nome") for el in
               pg.query_selector_all("#map-alcance .lcl-item")]
    assert set(alcance) == {"Forja de Cliviate", "Boticário da Mira", "Taverna do Caldeirão", "Cliviate"}
    assert pg.locator(f"{_no('Floresta das Brumas')} .map-ir").count() == 0, "longe não tem Ir até lá"
    # Paradeiro desconhecido e lugar citado sem registro.
    assert "Andarilho" in pg.inner_text("#map-sem")
    assert "sem registro" in pg.inner_text(f"{_no('Porto de Vhar')} > .map-linha").lower()
    assert not erros, erros[:3]


def test_abrir_e_fechar_um_ramo(pagina):
    pg, _, _ = pagina
    _abrir(pg)
    taverna = _no("Taverna do Caldeirão")
    assert pg.locator(f"{taverna} > .map-filhos").count() == 0, "fora do caminho do grupo começa fechada"
    pg.click(f"{taverna} > .map-linha .map-seta")
    pg.wait_for_selector(f"{taverna} > .map-filhos {_so_no('Porão da Taverna')}", timeout=3000)
    # O porão tem gente, mas só abre com o próprio clique.
    assert "Velho Osric" not in pg.inner_text(_no("Porão da Taverna"))
    assert "1 pessoa" in pg.inner_text(f"{_no('Porão da Taverna')} > .map-linha")
    pg.click(f"{taverna} > .map-linha .map-seta")
    pg.wait_for_function(
        f"() => !document.querySelector(\"{taverna} > .map-filhos\")", timeout=3000)


def test_busca_por_pessoa_mostra_so_o_ramo_dela(pagina):
    pg, _, _ = pagina
    _abrir(pg)
    pg.fill("#map-busca", "osric")
    pg.wait_for_selector(".map-pessoa.map-casou", timeout=3000)
    assert "Velho Osric" in pg.inner_text(".map-pessoa.map-casou")
    # O porão aparece aberto dentro da taverna; a floresta some.
    assert pg.locator(f"{_no('Taverna do Caldeirão')} {_so_no('Porão da Taverna')}").count() == 1
    assert pg.locator(_no("Floresta das Brumas")).count() == 0
    # Busca por lugar, sem acento.
    pg.fill("#map-busca", "boticario")
    pg.wait_for_selector(f"{_no('Boticário da Mira')} .map-nome.map-casou", timeout=3000)
    pg.fill("#map-busca", "nada disso existe")
    pg.wait_for_function("() => document.getElementById('map-arvore').textContent.includes('Nada encontrado')",
                         timeout=3000)


def test_ir_ate_la_manda_a_fala_do_jogador(pagina):
    pg, erros, _ = pagina
    _abrir(pg)
    pg.click(f"{_no('Taverna do Caldeirão')} > .map-linha .map-ir")
    pg.wait_for_function("() => window.__enviados.length === 1", timeout=3000)
    assert pg.evaluate("() => window.__enviados[0]") == "Vamos até Taverna do Caldeirão."
    assert pg.is_hidden("#mapa-overlay")
    assert not erros, erros[:3]


def test_mestre_ocupado_nao_manda_nada(pagina):
    pg, _, _ = pagina
    _abrir(pg)
    pg.evaluate("() => { waiting = true; }")
    pg.click("#map-alcance .lcl-item[data-nome='Forja de Cliviate'] .lcl-btn-ir")
    pg.wait_for_timeout(300)
    assert pg.evaluate("() => window.__enviados.length") == 0
    assert "Aguarde" in pg.inner_text("#map-msg")
    pg.evaluate("() => { waiting = false; }")


def test_lugar_abre_a_ficha_do_local_e_pessoa_a_do_personagem(pagina):
    pg, _, _ = pagina
    _abrir(pg)
    pg.click(f"{_no('Forja de Cliviate')} > .map-linha .map-nome")
    pg.wait_for_function("() => document.getElementById('lcl-nome').textContent === 'Forja de Cliviate'",
                         timeout=5000)
    assert pg.is_hidden("#mapa-overlay")

    # E a ficha do local volta ao mapa, com o lugar em foco.
    pg.click("#lcl-mapa")
    pg.wait_for_selector(f"#mapa-overlay:not(.hidden) {_no('Forja de Cliviate')}.map-foco", timeout=5000)
    assert pg.is_hidden("#local-overlay")

    pg.click(f"{_no('Praça de Cliviate')} .map-pessoa:has-text('Guarda Tiel')")
    pg.wait_for_function("() => document.getElementById('psn-nome').textContent === 'Guarda Tiel'",
                         timeout=5000)
    assert pg.is_visible("#pessoa-overlay")
    assert pg.is_hidden("#mapa-overlay")


def test_ver_no_mapa_de_um_lugar_fechado_abre_ate_ele(pagina):
    pg, _, _ = pagina
    pg.evaluate("() => window.Locais._abrir('Porão da Taverna')")
    pg.wait_for_function("() => document.getElementById('lcl-nome').textContent === 'Porão da Taverna'",
                         timeout=5000)
    pg.click("#lcl-mapa")
    pg.wait_for_selector(f"#mapa-overlay:not(.hidden) {_no('Porão da Taverna')}.map-foco", timeout=5000)


def test_saque_nao_abre_por_cima_do_mapa(pagina):
    import capturar_telas as cap
    import requests
    pg, _, url = pagina
    _abrir(pg)
    requests.post(f"{url}/__estado", json=copy.deepcopy(cap.SAQUE), timeout=10)
    pg.evaluate("() => window.sincronizarTelas()")
    pg.wait_for_timeout(1000)
    assert pg.is_hidden("#loot-overlay"), "o saque abriu por cima do mapa"
    pg.evaluate("() => window.Mapa._fechar()")
    pg.wait_for_selector("#loot-overlay:not(.hidden)", timeout=5000)


def test_novo_local_abre_o_editor(pagina):
    pg, _, _ = pagina
    _abrir(pg)
    pg.click("#map-novo")
    pg.wait_for_selector("#edit-overlay:not(.hidden)", timeout=5000)
    assert "Local" in pg.text_content("#edit-type")
    assert pg.is_hidden("#mapa-overlay")
