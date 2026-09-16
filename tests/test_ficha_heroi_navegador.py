"""
test_ficha_heroi_navegador.py

A ficha de leitura do herói no navegador: abre pelo cartão do grupo (antes
abria o editor), mostra os números que o motor calcula, troca de herói, leva
à Mochila, ao Grimório e à tela de nível, e não tem campo de edição.

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
    requests.post(f"{url}/__estado", json=copy.deepcopy(cap.HEROI), timeout=10)
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
        yield pg, erros
        nav.close()


def _esperar(pg, nome):
    pg.wait_for_selector("#heroi-overlay:not(.hidden)", timeout=5000)
    pg.wait_for_function(
        f"() => document.getElementById('hro-nome').textContent === {nome!r}"
        " && !document.getElementById('hro-msg').textContent", timeout=8000)


def _abrir_pelo_cartao(pg, nome):
    # O nome do herói no relance da barra lateral abre a ficha; o selo de
    # nível fica numa linha própria e não atrapalha o clique.
    nome_no_relance = f"#sb-herois .sb-heroi[data-nome='{nome}'] .sb-heroi-nome"
    pg.wait_for_selector(nome_no_relance, state="visible", timeout=5000)
    pg.click(nome_no_relance)
    _esperar(pg, nome)


def test_cartao_do_grupo_abre_a_ficha_e_nao_o_editor(pagina):
    pg, erros = pagina
    _abrir_pelo_cartao(pg, "Stelar")
    assert not pg.is_visible("#edit-overlay"), "o cartão do grupo abriu o editor"
    assert pg.locator("#heroi-overlay input:not(.hro-quem-sel), #heroi-overlay textarea").count() == 0
    assert not erros, erros[:3]


def test_numeros_vem_do_motor(pagina):
    pg, _ = pagina
    _abrir_pelo_cartao(pg, "Stelar")
    motor = pg.evaluate("() => window.Herois._estado().personagem")

    recursos = pg.inner_text("#hro-recursos")
    assert f"{motor['vida']['atual']}/{motor['vida']['max']}" in recursos
    assert motor["iniciativa"] in recursos and str(motor["percepcao_passiva"]) in recursos

    forca = next(a for a in motor["atributos"] if a["sigla"] == "FOR")
    cartao = pg.inner_text("#hro-atributos .hro-atributo[data-sigla='FOR']")
    assert forca["mod"] in cartao and f"salv. {forca['salvaguarda']}" in cartao
    assert pg.locator("#hro-atributos .hro-atributo[data-sigla='FOR'] .hro-prof").count() == 1, \
        "salvaguarda de FOR é da classe do guerreiro"

    atletismo = pg.locator("#hro-pericias .hro-pericia[data-pericia='atletismo']")
    assert "hro-prof" in atletismo.get_attribute("class")
    assert next(x for x in motor["pericias"] if x["nome"] == "atletismo")["bonus"] in atletismo.inner_text()

    ataques = pg.inner_text("#hro-ataques")
    assert motor["ataques"][0]["acerto"] in ataques
    assert "Grande Arma: rola de novo 1 e 2 no dano" in ataques
    assert "crítico com 19 ou mais" in ataques


def test_conjuracao_e_deslocamento_na_tela(pagina):
    """
    A CD de magia e o ataque mágico saem do atributo de conjuração da classe
    — SAB na clériga, FOR no guerreiro, que nesta variante gasta mana em
    manobras. O deslocamento aparece em metros para todo mundo.
    """
    pg, erros = pagina
    _abrir_pelo_cartao(pg, "Helena")
    motor = pg.evaluate("() => window.Herois._estado().personagem")
    # text_content, não inner_text: o rótulo é maiúsculo por CSS.
    recursos = pg.text_content("#hro-recursos")
    assert "CD de magia" in recursos and str(motor["conjuracao"]["cd"]) in recursos
    assert "Ataque mágico" in recursos and motor["conjuracao"]["ataque"] in recursos
    assert motor["conjuracao"]["sigla"] == "SAB"
    assert "Deslocamento" in recursos and "9 m" in recursos

    pg.select_option("#hro-sub .hro-quem-sel", "Stelar")
    _esperar(pg, "Stelar")
    outro = pg.evaluate("() => window.Herois._estado().personagem")
    assert outro["conjuracao"]["sigla"] == "FOR"
    assert str(outro["conjuracao"]["cd"]) in pg.text_content("#hro-recursos")
    assert not erros, erros[:3]


def test_estado_condicoes_e_habilidades(pagina):
    pg, _ = pagina
    _abrir_pelo_cartao(pg, "Helena")
    estado = pg.inner_text("#hro-estado")
    assert "Envenenado (2 turnos)" in estado
    assert "Concentrado em Bênção" in estado
    assert not pg.is_hidden("#hro-grimorio"), "clériga conjura: o Grimório aparece"
    primeira = pg.locator("#hro-habilidades details").first
    primeira.locator("summary").click()
    assert primeira.get_attribute("open") is not None


def test_troca_de_heroi_pelo_seletor(pagina):
    pg, _ = pagina
    _abrir_pelo_cartao(pg, "Helena")
    pg.select_option("#hro-sub .hro-quem-sel", "Natasha")
    _esperar(pg, "Natasha")
    assert "Ladino" in pg.inner_text("#hro-sub")
    conjura = pg.evaluate("() => window.Herois._estado().personagem.conjura")
    assert pg.is_visible("#hro-grimorio") == conjura


def test_botoes_levam_as_telas(pagina):
    pg, _ = pagina
    _abrir_pelo_cartao(pg, "Stelar")
    pg.click("#hro-mochila")
    pg.wait_for_selector("#inventory-overlay:not(.hidden)", timeout=5000)
    assert not pg.is_visible("#heroi-overlay")
    pg.wait_for_function("() => (document.getElementById('inv-quem').textContent || '').includes('Stelar')",
                         timeout=5000)
    pg.evaluate("() => window.Inventory._close()")

    _abrir_pelo_cartao(pg, "Stelar")
    assert pg.is_visible("#hro-nivel"), "Stelar tem XP para subir"
    pg.click("#hro-nivel")
    pg.wait_for_selector("#levelup-overlay:not(.hidden)", timeout=5000)


def test_corrigir_ficha_abre_o_editor(pagina):
    pg, _ = pagina
    _abrir_pelo_cartao(pg, "Natasha")
    pg.click("#hro-corrigir")
    pg.wait_for_selector("#edit-overlay:not(.hidden)", timeout=5000)
    assert not pg.is_visible("#heroi-overlay")


def test_tela_automatica_nao_abre_por_cima_da_ficha(pagina, app_no_ar):
    """O descanso (e as outras telas que abrem sozinhas) não conheciam as fichas."""
    import requests
    pg, _ = pagina
    url, _, cap = app_no_ar
    _abrir_pelo_cartao(pg, "Natasha")
    requests.post(f"{url}/__estado", json=copy.deepcopy(cap.DESCANSO_CURTO), timeout=10)
    pg.evaluate("() => window.sincronizarTelas()")
    pg.wait_for_timeout(1000)
    assert pg.is_hidden("#rest-overlay"), "o descanso abriu por cima da ficha do herói"
    pg.click("#heroi-overlay .lcl-fechar")
    pg.wait_for_selector("#rest-overlay:not(.hidden)", timeout=5000)
    requests.post(f"{url}/__estado", json={"descanso_proposto": None}, timeout=10)


def test_redesenha_quando_o_mestre_muda_a_ficha(pagina, app_no_ar):
    import requests
    pg, _ = pagina
    url, _, _ = app_no_ar
    _abrir_pelo_cartao(pg, "Natasha")
    requests.post(f"{url}/__estado", json={"characters": {"natasha": {"sheet": {"vida_atual": 3}}}}, timeout=10)
    pg.evaluate("() => window.Herois.sync()")
    pg.wait_for_function("() => document.getElementById('hro-recursos').textContent.includes('3/')", timeout=5000)
