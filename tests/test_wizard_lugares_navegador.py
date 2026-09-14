"""
test_wizard_lugares_navegador.py

O wizard de criação mostra "Fica dentro de" no local e "Onde está" no
personagem, com sugestões dos locais digitados, e manda os dois ao criar a
campanha, com a chave do local pelo nome.

O POST de criação é interceptado: o teste confere o que o wizard enviou e
responde com erro, para o fluxo não seguir para o início da sessão. O que o
servidor faz com isso está em test_wizard_lugares.py.

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
def wizard(app_no_ar):
    from playwright.sync_api import sync_playwright

    url, nome, cap = app_no_ar
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        ctx = nav.new_context(viewport={"width": 1440, "height": 980})
        ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO))
        pg = ctx.new_page()
        erros = []
        pg.on("pageerror", lambda e: erros.append(str(e)))
        enviado = {}

        def interceptar(route, request):
            if request.method == "POST":
                enviado.update(json.loads(request.post_data or "{}"))
                route.fulfill(status=400, content_type="application/json",
                              body=json.dumps({"error": "interceptado pelo teste"}))
            else:
                route.continue_()

        pg.route("**/api/campaigns", interceptar)
        pg.goto(f"{url}/menu.html", wait_until="networkidle")
        cap._sanear(pg)
        pg.evaluate("() => openWizard()")
        pg.wait_for_selector("#wizard-overlay:not(.hidden)", timeout=5000)
        pg.fill("#wz-name", "Teste de Lugares")
        pg.select_option("#wz-type", "fantasia")
        pg.evaluate("() => { onWizardTypeChange(); wizardValidate(); }")
        yield pg, erros, enviado
        nav.close()


def _preencher(pg, seletor, valor):
    pg.fill(seletor, valor)
    pg.dispatch_event(seletor, "change")


def test_local_tem_fica_dentro_de_e_as_sugestoes_seguem_os_nomes(wizard):
    pg, erros, _ = wizard
    pg.click("text=+ Local")
    pg.click("text=+ Local")
    cartoes = pg.locator("#wz-locations-list .wz-loc-card")
    _preencher(pg, "#wz-locations-list .wz-loc-card >> nth=0 >> input >> nth=0", "Cliviate")
    _preencher(pg, "#wz-locations-list .wz-loc-card >> nth=1 >> input >> nth=0", "Taverna do Caldeirão")

    assert cartoes.nth(1).locator(".wz-dentro-de").get_attribute("list") == "wz-lugares"
    sugestoes = pg.evaluate("() => [...document.querySelectorAll('#wz-lugares option')].map(o => o.value)")
    assert sugestoes == ["Cliviate", "Taverna do Caldeirão"]
    assert pg.get_attribute("#wz-location", "list") == "wz-lugares"
    assert not erros, erros[:3]


def test_criar_manda_dentro_de_onde_esta_e_chave_pelo_nome(wizard):
    pg, _, enviado = wizard
    pg.click("text=+ Local")
    pg.click("text=+ Local")
    _preencher(pg, "#wz-locations-list .wz-loc-card >> nth=0 >> input >> nth=0", "Cliviate")
    _preencher(pg, "#wz-locations-list .wz-loc-card >> nth=1 >> input >> nth=0", "Taverna do Caldeirão")
    _preencher(pg, "#wz-locations-list .wz-loc-card >> nth=1 >> .wz-dentro-de", "Cliviate")

    pg.evaluate("() => wizardGoTo(2)")
    pg.evaluate("() => addWzChar()")
    pg.wait_for_selector(".wz-onde-esta", timeout=5000)
    _preencher(pg, "#wz-chars-list .cwc >> nth=0 >> input >> nth=0", "Nana")
    _preencher(pg, "#wz-chars-list .cwc >> nth=0 >> .wz-onde-esta", "Taverna do Caldeirão")

    pg.evaluate("() => { createCampaignFromWizard(); }")
    pg.wait_for_function("() => document.getElementById('wz-err').textContent.length > 0", timeout=8000)

    camp = enviado["campaign"]
    assert set(camp["locations"]) == {"cliviate", "taverna do caldeirão"}
    assert camp["locations"]["taverna do caldeirão"]["dentro_de"] == "Cliviate"
    assert camp["characters"]["nana"]["local"] == "Taverna do Caldeirão"
