"""
test_manobras_navegador.py

O botão Manobras abre Ajudar, Esconder-se, Agarrar, Derrubar, Empurrar e
Preparar (e Escapar, quando o personagem está agarrado); escolher uma pede o
alvo e gasta a Ação no motor.

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
def abrir(app_no_ar):
    from playwright.sync_api import sync_playwright
    import requests

    url, nome, cap = app_no_ar
    with sync_playwright() as pw:
        nav = pw.chromium.launch()

        def _abrir(agarrado=False, viewport=None, mudar=None):
            estado = copy.deepcopy(cap.COMBATE_ZONAS)
            estado["combat_state"]["posicoes"]["victoria"] = "Pátio"
            if mudar:
                mudar(estado)
            if agarrado:
                estado["characters"]["stelar"]["sheet"]["condicoes"] = [
                    {"nome": "Agarrado", "duracao": None, "por": "Victoria"}]
            requests.post(f"{url}/__estado", json=estado, timeout=10)
            ctx = nav.new_context(viewport=viewport or {"width": 1440, "height": 980})
            ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO))
            pg = ctx.new_page()
            erros = []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.goto(f"{url}/game.html", wait_until="networkidle")
            pg.wait_for_selector("#cbt-buttons button:has-text('Manobras')", timeout=8000)
            return pg, erros

        yield _abrir
        nav.close()


def test_menu_de_manobras(abrir):
    pg, erros = abrir()
    pg.click("#cbt-buttons button:has-text('Manobras')")
    texto = pg.inner_text("#cbt-targets")
    for rotulo in ("Defender", "Ajudar", "Esconder-se", "Agarrar", "Derrubar", "Empurrar",
                   "Preparar ataque", "Fugir"):
        assert rotulo in texto, rotulo
    assert "Escapar" not in texto
    # A barra não ganhou fileira: Defender e Fugir moram aqui dentro.
    assert pg.locator("#cbt-buttons button:has-text('Defender')").count() == 0
    assert not erros, erros[:3]


def test_defender_pelo_menu(abrir):
    pg, erros = abrir()
    pg.click("#cbt-buttons button:has-text('Manobras')")
    pg.click("#cbt-targets [data-manobra='defend']")
    pg.wait_for_function(
        "() => /esquiva-se|Esquiva/.test(document.getElementById('cbt-log').textContent)", timeout=8000)
    assert not erros, erros[:3]


def test_derrubar_pede_alvo_e_gasta_a_acao(abrir):
    pg, erros = abrir()
    pg.click("#cbt-buttons button:has-text('Manobras')")
    pg.click("#cbt-targets [data-manobra='shove:derrubar']")
    pg.wait_for_selector("#cbt-targets .cbt-tgt-title:has-text('Derrubar')")
    pg.click("#cbt-targets button:has-text('Victoria')")
    pg.wait_for_function(
        "() => [...document.querySelectorAll('#cbt-buttons button')]"
        ".some(b => b.textContent.trim() === 'Manobras' && b.disabled)", timeout=8000)
    assert not erros, erros[:3]


def test_agarrado_ve_escapar(abrir):
    pg, _ = abrir(agarrado=True)
    pg.click("#cbt-buttons button:has-text('Manobras')")
    assert "Escapar" in pg.inner_text("#cbt-targets")


def test_zona_coberta_mostra_a_magia(abrir):
    """Escuridão na Sacada: a faixa de zonas diz o que cobre a zona."""
    def escuridao(estado):
        estado["characters"]["helena"]["sheet"]["concentracao"] = {"magia": "Darkness", "rodada": 3}
        estado["combat_state"]["efeitos_de_zona"] = [
            {"zona": "Sacada", "tipo": "escuridao", "nome": "Escuridão",
             "concentracao_de": "helena", "magia": "Darkness"}]
    pg, erros = abrir(mudar=escuridao)
    pg.wait_for_selector(".cbt-zona.cbt-zona-coberta", timeout=8000)
    assert "Escuridão" in pg.inner_text(".cbt-zona.cbt-zona-coberta")
    assert pg.locator(".cbt-zona-coberta").count() == 1
    assert not erros, erros[:3]


def test_sem_zonas_a_area_aparece_no_cartao(abrir):
    """Sem zonas, o Silêncio fica centrado numa criatura e aparece no cartão dela."""
    def silencio(estado):
        estado["combat_state"].pop("zonas", None)
        estado["combat_state"].pop("posicoes", None)
        estado["characters"]["helena"]["sheet"]["concentracao"] = {"magia": "Silence", "rodada": 3}
        estado["combat_state"]["efeitos_de_zona"] = [
            {"criatura": "victoria", "tipo": "silencio", "nome": "Silêncio",
             "concentracao_de": "helena", "magia": "Silence"}]
    pg, erros = abrir(mudar=silencio)
    pg.wait_for_selector(".cbt-card[data-nome='Victoria']", timeout=8000)
    # O selo de condição sai em caixa alta pelo CSS.
    assert "silêncio" in pg.inner_text(".cbt-card[data-nome='Victoria']").lower()
    assert "silêncio" not in pg.inner_text(".cbt-card[data-nome='Stelar']").lower()
    assert not erros, erros[:3]


def test_celular_sem_rolagem_lateral(abrir):
    pg, _ = abrir(viewport={"width": 375, "height": 812})
    largura = pg.evaluate("document.documentElement.scrollWidth")
    assert largura <= 375, largura
