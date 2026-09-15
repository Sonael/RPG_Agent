"""
test_grupo_navegador.py

A visão geral do grupo no navegador: abre pelo "Visão geral" da barra
lateral, mostra os heróis lado a lado com os números do motor, leva à ficha,
à Mochila e à tela de nível, pede descanso ao mestre e se redesenha quando o
mestre muda algo com ela aberta. As telas que abrem sozinhas esperam ela
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
    estado = copy.deepcopy(cap.GRUPO)
    estado["saque_proposto"] = None
    estado["descanso_proposto"] = None
    estado["combat_state"] = {"is_active": False, "initiative_order": []}
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


def _cartao(nome):
    return f"#grupo-overlay .grp-cartao[data-nome='{nome}']"


def _abrir(pg):
    pg.evaluate("() => window.Grupo._abrir()")
    pg.wait_for_selector("#grupo-overlay:not(.hidden) .grp-cartao", timeout=5000)


def test_visao_geral_abre_pela_barra_lateral(pagina):
    pg, erros, _ = pagina
    pg.click(".tab-btn[data-tab='enciclopedia']")
    pg.click("#sb-grupo-abrir")
    pg.wait_for_selector("#grupo-overlay:not(.hidden) .grp-cartao", timeout=5000)
    nomes = [el.get_attribute("data-nome") for el in pg.query_selector_all("#grp-cartoes .grp-cartao")]
    assert set(nomes) == {"Helena", "Stelar", "Natasha"}
    assert "Dia 4, 20h" in pg.inner_text("#grp-hora")
    assert not erros, erros[:3]


def test_cartoes_com_os_numeros_do_motor(pagina):
    pg, _, _ = pagina
    _abrir(pg)
    motor = {h["nome"]: h for h in pg.evaluate("() => window.Grupo._estado().herois")}

    helena = pg.inner_text(_cartao("Helena"))
    h = motor["Helena"]
    assert f"{h['vida']['atual']}/{h['vida']['max']}" in helena
    assert f"{h['mana']['atual']}/{h['mana']['max']}" in helena
    assert "0/3" in helena, "dados de vida"
    assert "Envenenado (2t)" in helena
    assert "longo em" not in helena and "pode dormir" in helena
    assert "Precisa: vida" in helena

    stelar = pg.inner_text(_cartao("Stelar"))
    assert "curto ajuda" in stelar and "longo em 14h" in stelar
    assert pg.locator(f"{_cartao('Stelar')} .grp-nivel").count() == 1
    assert pg.locator(f"{_cartao('Helena')} .grp-nivel").count() == 0

    natasha = pg.locator(_cartao("Natasha"))
    assert "perto do limite" in natasha.inner_text()
    assert "grp-barra-alerta" in natasha.locator(".grp-barra").last.get_attribute("class")
    assert pg.locator(f"{_cartao('Natasha')} .grp-barra-marca").count() == 1


def test_resumo_para_decidir(pagina):
    pg, _, _ = pagina
    _abrir(pg)
    resumo = pg.inner_text("#grp-resumo")
    motor = pg.evaluate("() => window.Grupo._estado().resumo")
    assert motor["descanso"] in resumo
    assert "Mais folga para carregar:" in resumo and "Perto do limite: Natasha." in resumo
    assert "Stelar com escolha pendente" in resumo
    assert pg.is_enabled("#grp-curto") and pg.is_enabled("#grp-longo")


def test_pedir_descanso_manda_a_fala_do_jogador(pagina):
    pg, erros, _ = pagina
    _abrir(pg)
    pg.click("#grp-curto")
    pg.wait_for_function("() => window.__enviados.length === 1", timeout=3000)
    assert pg.evaluate("() => window.__enviados[0]") == "Vamos fazer um descanso curto."
    assert pg.is_hidden("#grupo-overlay")
    assert not erros, erros[:3]


def test_mestre_ocupado_nao_manda_nada(pagina):
    pg, _, _ = pagina
    _abrir(pg)
    pg.evaluate("() => { waiting = true; }")
    pg.click("#grp-longo")
    pg.wait_for_timeout(300)
    assert pg.evaluate("() => window.__enviados.length") == 0
    assert "Aguarde" in pg.inner_text("#grp-msg")
    pg.evaluate("() => { waiting = false; }")


def test_sem_ninguem_ferido_os_botoes_travam(pagina):
    import requests
    pg, _, url = pagina
    requests.post(f"{url}/__estado", json={"characters": {
        "helena": {"sheet": {"vida_atual": 21, "mana_atual": 28, "condicoes": []}},
        "stelar": {"sheet": {"vida_atual": 31}},
    }}, timeout=10)
    _abrir(pg)
    assert "Ninguém precisa de descanso agora." in pg.inner_text("#grp-resumo")
    assert pg.is_disabled("#grp-curto") and pg.is_disabled("#grp-longo")


def test_cartao_leva_a_ficha_mochila_e_nivel(pagina):
    pg, _, _ = pagina
    _abrir(pg)
    pg.click(f"{_cartao('Helena')} .grp-nome")
    pg.wait_for_function("() => document.getElementById('hro-nome').textContent === 'Helena'", timeout=5000)
    assert pg.is_hidden("#grupo-overlay")
    pg.evaluate("() => window.Herois._fechar()")

    _abrir(pg)
    pg.click(f"{_cartao('Natasha')} button:has-text('Mochila')")
    pg.wait_for_selector("#inventory-overlay:not(.hidden)", timeout=5000)
    assert pg.is_hidden("#grupo-overlay")
    pg.evaluate("() => window.Inventory._fechar ? window.Inventory._fechar() : window.Inventory._close()")

    _abrir(pg)
    pg.click(f"{_cartao('Stelar')} .grp-nivel")
    pg.wait_for_selector("#levelup-overlay:not(.hidden)", timeout=5000)


def test_aberta_redesenha_quando_o_mestre_muda_a_vida(pagina):
    import requests
    pg, _, url = pagina
    _abrir(pg)
    requests.post(f"{url}/__estado", json={"characters": {"helena": {"sheet": {"vida_atual": 2}}}},
                  timeout=10)
    pg.evaluate("() => window.sincronizarTelas()")
    pg.wait_for_function(
        "() => document.querySelector(\"#grupo-overlay .grp-cartao[data-nome='Helena']\")"
        ".textContent.includes('2/21')", timeout=5000)


def test_saque_nao_abre_por_cima_da_visao_geral(pagina):
    import capturar_telas as cap
    import requests
    pg, _, url = pagina
    _abrir(pg)
    requests.post(f"{url}/__estado", json=copy.deepcopy(cap.SAQUE), timeout=10)
    pg.evaluate("() => window.sincronizarTelas()")
    pg.wait_for_timeout(1000)
    assert pg.is_hidden("#loot-overlay"), "o saque abriu por cima da visão geral"
    pg.evaluate("() => window.Grupo._fechar()")
    pg.wait_for_selector("#loot-overlay:not(.hidden)", timeout=5000)
