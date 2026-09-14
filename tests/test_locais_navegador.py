"""
test_locais_navegador.py

A ficha do local no navegador: abre pelo cartão da Enciclopédia e pelo
"Local:" da barra lateral, mostra o que fica dentro e quem está lá, e os
botões "Ir até lá" e "Falar com" mandam a fala do jogador ao mestre.

Depende do Playwright, que não está em requirements-dev.txt. Sem ele o arquivo
é pulado:

    pip install playwright && playwright install chromium
"""
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
    requests.post(f"{url}/__estado", json=cap.CIDADE, timeout=10)
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
        # O mestre não responde nos testes: guarda o que seria enviado.
        pg.evaluate("() => { window.__enviado = null;"
                    " window.sendToAgent = async (t) => { window.__enviado = t; }; }")
        yield pg, erros
        nav.close()


def _abrir_pela_enciclopedia(pg, nome):
    pg.click(".tab-btn[data-tab='enciclopedia']")
    cartao = f".local-card[data-local='{nome}']"
    pg.wait_for_selector(cartao, state="visible", timeout=5000)
    pg.click(cartao)
    pg.wait_for_selector("#local-overlay:not(.hidden) #lcl-nome", timeout=5000)
    pg.wait_for_function(f"() => document.getElementById('lcl-nome').textContent === {nome!r}")


def _item(nome):
    return f"#local-overlay .lcl-item[data-nome='{nome}']"


def test_cartao_do_local_abre_a_ficha_com_o_que_fica_dentro(pagina):
    pg, erros = pagina
    _abrir_pela_enciclopedia(pg, "Cliviate")

    dentro = pg.inner_text("#lcl-dentro")
    assert "Forja de Cliviate" in dentro and "Boticário da Mira" in dentro
    assert "Praça de Cliviate" in dentro and "Taverna do Caldeirão" in dentro
    assert "loja" in pg.inner_text(_item("Forja de Cliviate"))
    assert "1 pessoa" in pg.inner_text(_item("Forja de Cliviate"))
    assert not pg.is_visible("#edit-overlay"), "o cartão abriu o editor em vez da ficha"
    assert not erros, erros[:3]


def test_ir_ate_la_manda_a_fala_do_jogador(pagina):
    pg, _ = pagina
    _abrir_pela_enciclopedia(pg, "Cliviate")

    pg.click(f"{_item('Forja de Cliviate')} .lcl-btn-ir")

    pg.wait_for_function("() => window.__enviado !== null", timeout=3000)
    assert pg.evaluate("() => window.__enviado") == "Vamos até Forja de Cliviate."
    assert not pg.is_visible("#local-overlay")
    assert "Vamos até Forja de Cliviate." in pg.inner_text("#chat-history")


def test_falar_com_quem_esta_na_forja(pagina):
    pg, _ = pagina
    pg.evaluate("() => window.Locais._abrir('Forja de Cliviate')")
    pg.wait_for_selector(_item("Brom"), timeout=5000)

    pg.click(f"{_item('Brom')} .lcl-btn-ir")

    pg.wait_for_function("() => window.__enviado !== null", timeout=3000)
    assert pg.evaluate("() => window.__enviado") == "Quero falar com Brom."


def test_lugar_longe_nao_tem_ir_nem_falar(pagina):
    pg, _ = pagina
    _abrir_pela_enciclopedia(pg, "Floresta das Brumas")

    assert "Longe do grupo" in pg.inner_text("#lcl-selo")
    assert pg.locator("#local-overlay .lcl-btn-ir").count() == 0
    assert pg.is_disabled(f"{_item('Eremita')} button")


def test_local_da_barra_lateral_abre_onde_o_grupo_esta(pagina):
    pg, _ = pagina
    pg.click("#sb-location")
    pg.wait_for_function("() => document.getElementById('lcl-nome').textContent === 'Praça de Cliviate'",
                         timeout=5000)

    assert "O grupo está aqui" in pg.inner_text("#lcl-selo")
    assert pg.locator("#lcl-grupo .lcl-grupo-nome").count() >= 1
    assert "Guarda Tiel" in pg.inner_text("#lcl-pessoas")
    assert "Cliviate" in pg.inner_text("#lcl-caminho")
    assert "Sair para Cliviate" in pg.inner_text("#lcl-selo")


def test_cartao_do_personagem_diz_onde_ele_esta(pagina):
    pg, _ = pagina
    pg.click(".tab-btn[data-tab='enciclopedia']")
    pg.wait_for_selector("text=Em Forja de Cliviate", timeout=5000)
    pg.click("text=Forja de Cliviate >> nth=0")
    pg.wait_for_selector("#local-overlay:not(.hidden)", timeout=5000)


def test_mestre_ocupado_nao_manda_nada(pagina):
    pg, _ = pagina
    pg.evaluate("() => { waiting = true; }")
    _abrir_pela_enciclopedia(pg, "Cliviate")
    pg.click(f"{_item('Forja de Cliviate')} .lcl-btn-ir")
    pg.wait_for_timeout(300)
    assert pg.evaluate("() => window.__enviado") is None
    assert "Aguarde" in pg.inner_text("#lcl-msg")
    pg.evaluate("() => { waiting = false; }")
