"""
test_saque_navegador.py

A tela de saque no navegador: abre sozinha quando o mestre põe o saque no
chão, dá item a cada um mostrando a carga prevista, devolve, divide as
moedas, conclui pondo tudo nas fichas e avisando o mestre, vira pílula ao
fechar, e não abre por cima de outra tela.

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
def navegador(app_no_ar):
    from playwright.sync_api import sync_playwright
    import requests

    url, nome, cap = app_no_ar
    with sync_playwright() as pw:
        nav = pw.chromium.launch()

        def abrir(estado=None, esperar_tela=True):
            requests.post(f"{url}/__estado", json=copy.deepcopy(estado or cap.SAQUE), timeout=10)
            ctx = nav.new_context(viewport={"width": 1440, "height": 980})
            ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO))
            pg = ctx.new_page()
            erros = []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
            pg.goto(f"{url}/game.html", wait_until="networkidle")
            cap._sanear(pg)
            pg.evaluate("() => { window.__enviado = null;"
                        " window.sendToAgent = async (t) => { window.__enviado = t; }; }")
            if esperar_tela:
                pg.wait_for_selector("#loot-overlay:not(.hidden) .lot-item", timeout=8000)
            return pg, erros

        yield abrir
        nav.close()


def _item(nome):
    return f"#loot-overlay .lot-item[data-nome='{nome}']"


def _cartao(nome):
    return f"#loot-overlay .lot-cartao[data-nome='{nome}']"


def _esperar_msg(pg, trecho):
    pg.wait_for_function(
        "(t) => (document.getElementById('lot-msg').textContent || '').includes(t)", arg=trecho,
        timeout=5000)


def test_abre_sozinha_com_o_que_esta_no_chao(navegador):
    pg, erros = navegador()
    assert "os bandidos da estrada" in pg.inner_text("#lot-origem")
    assert "1 de 1 no chão" in pg.inner_text(_item("Cota de Malha"))
    assert "2 de 2 no chão" in pg.inner_text(_item("Poção de Cura"))
    assert "25" in pg.inner_text("#lot-moedas") and "8" in pg.inner_text("#lot-moedas")
    for nome in ("Helena", "Stelar", "Natasha"):
        assert pg.locator(_cartao(nome)).count() == 1
    assert "4 ficam para trás" in pg.inner_text("#lot-concluir")
    assert not erros, erros[:3]


def test_dar_mostra_a_carga_prevista_e_devolver_desfaz(navegador):
    pg, _ = navegador()
    pg.click(f"{_item('Cota de Malha')} .lot-btn-dar[data-para='Helena']")
    _esperar_msg(pg, "Cota de Malha ×1 para Helena")

    helena = pg.inner_text(_cartao("Helena"))
    assert "Cota de Malha" in helena
    assert "→" in helena, "a carga prevista não apareceu"
    assert "tudo distribuído" in pg.inner_text(_item("Cota de Malha"))
    assert "3 ficam para trás" in pg.inner_text("#lot-concluir")

    pg.click(f"{_cartao('Helena')} .lot-btn-devolver")
    _esperar_msg(pg, "voltou para o chão")
    assert "Não leva nada" in pg.inner_text(_cartao("Helena"))
    assert "1 de 1 no chão" in pg.inner_text(_item("Cota de Malha"))


def test_moedas_tudo_para_uma_pessoa(navegador):
    pg, _ = navegador()
    pg.select_option("#lot-moedas-sel", "Natasha")
    _esperar_msg(pg, "Todas as moedas para Natasha")
    assert "25 po" in pg.inner_text(_cartao("Natasha"))
    assert "po" not in pg.inner_text(_cartao("Helena"))


def test_concluir_poe_nas_fichas_e_avisa_o_mestre(navegador):
    pg, erros = navegador()
    pg.click(f"{_item('Poção de Cura')} .lot-btn-dar[data-para='Stelar']")
    _esperar_msg(pg, "para Stelar")
    pg.click("#lot-concluir")
    pg.wait_for_selector("#loot-overlay", state="hidden", timeout=5000)
    pg.wait_for_function("() => window.__enviado !== null", timeout=5000)

    enviado = pg.evaluate("() => window.__enviado")
    assert enviado.startswith("[SAQUE RESOLVIDO NA TELA]")
    assert "Stelar: Poção de Cura" in enviado and "Ficaram para trás" in enviado
    mochila = pg.evaluate(
        "async () => (await (await authFetch((window.API || '') + "
        "'/api/inventory/state?personagem=Stelar')).json()).personagem.itens.map(i => i.nome)")
    assert "Poção de Cura" in mochila
    assert pg.is_hidden("#lot-reopen"), "a pílula ficou depois de concluir"
    assert not erros, erros[:3]


def test_fechar_vira_pilula_e_reabre(navegador):
    pg, _ = navegador()
    pg.click("#loot-overlay .lot-close")
    pg.wait_for_selector("#lot-reopen:not(.hidden)", timeout=3000)
    assert "Saque para dividir" in pg.inner_text("#lot-reopen")
    pg.evaluate("() => window.sincronizarTelas()")
    pg.wait_for_timeout(800)
    assert pg.is_hidden("#loot-overlay"), "reabriu sozinha depois de fechada"
    pg.click("#lot-reopen")
    pg.wait_for_selector("#loot-overlay:not(.hidden) .lot-item", timeout=3000)


def test_nao_abre_por_cima_da_ficha_do_heroi(navegador):
    import capturar_telas as cap
    pg, _ = navegador({"saque_proposto": None, "combat_state": {"is_active": False}},
                      esperar_tela=False)
    pg.evaluate("() => window.Herois._abrir('Stelar')")
    pg.wait_for_selector("#heroi-overlay:not(.hidden)", timeout=5000)

    import requests
    requests.post(f"{pg.url.split('/game.html')[0]}/__estado",
                  json=copy.deepcopy(cap.SAQUE), timeout=10)
    pg.evaluate("() => window.sincronizarTelas()")
    pg.wait_for_timeout(1000)
    assert pg.is_hidden("#loot-overlay"), "o saque abriu por cima da ficha do herói"

    pg.evaluate("() => window.Herois._fechar()")
    pg.wait_for_selector("#loot-overlay:not(.hidden)", timeout=5000)
