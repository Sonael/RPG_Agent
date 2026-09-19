"""
test_genero_e_regras_navegador.py

No wizard e no editor, gênero e regras são dois seletores.

O seletor "Estilo de RPG" misturava D&D com fantasia, romance e horror; quem
escolhia D&D perdia o tom, quem escolhia um tom perdia as fichas. Agora dá
para criar uma campanha de dark fantasy com as regras de D&D, e a ficha de
cada personagem segue a REGRA, não o gênero.

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
def menu(app_no_ar):
    """O menu com a criação de campanha interceptada: guarda o que seria enviado."""
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
        yield pg, erros, enviado
        nav.close()


def _wizard(pg, genero, regras):
    pg.evaluate("() => openWizard()")
    pg.wait_for_selector("#wizard-overlay:not(.hidden)", timeout=5000)
    pg.fill("#wz-name", "A Coroa de Cinzas")
    pg.select_option("#wz-type", genero)
    pg.select_option("#wz-regras", regras)
    pg.evaluate("() => { onWizardTypeChange(); wizardValidate(); wizardGoTo(2); addWzChar(); }")
    pg.wait_for_selector("#wz-chars-list .cwc", timeout=5000)


def _nome(pg, nome):
    # O nome entra no wzChars pelo onchange, que o fill sozinho não dispara.
    sel = "#wz-chars-list .cwc >> nth=0 >> input >> nth=0"
    pg.fill(sel, nome)
    pg.dispatch_event(sel, "change")


def test_seletores_separados_e_d_e_d_nao_e_genero(menu):
    pg, erros, _ = menu
    pg.evaluate("() => openWizard()")
    generos = pg.eval_on_selector_all("#wz-type option", "os => os.map(o => o.value)")
    assert "dnd" not in generos and "dark_fantasy" in generos
    assert pg.eval_on_selector_all("#wz-regras option", "os => os.map(o => o.value)") == ["dnd", "livre"]
    assert not erros, erros[:3]


def test_dark_fantasy_com_d_e_d_tem_ficha_e_vai_com_os_dois_campos(menu):
    pg, erros, enviado = menu
    _wizard(pg, "dark_fantasy", "dnd")
    # A ficha segue a regra: com D&D, classe e raça de ficha.
    assert "Modo D&D" in pg.inner_text("#wz-char-mode-hint")
    _nome(pg, "Vesna")
    pg.evaluate("() => { createCampaignFromWizard(); }")
    pg.wait_for_function("() => document.getElementById('wz-err').textContent.length > 0", timeout=8000)
    camp = enviado["campaign"]
    assert (camp["campaign_type"], camp["dnd_mode"]) == ("dark_fantasy", True)
    assert camp["characters"]["vesna"]["sheet"], "com as regras de D&D o personagem tem ficha"
    assert not erros, erros[:3]


def test_dark_fantasy_sem_regras_tem_os_campos_do_genero(menu):
    pg, erros, enviado = menu
    _wizard(pg, "dark_fantasy", "livre")
    assert "Modo narrativo" in pg.inner_text("#wz-char-mode-hint")
    # text_content: o rótulo da seção é maiúsculo por CSS.
    assert "Dark Fantasy — Arquétipo" in pg.text_content("#wz-chars-list")
    _nome(pg, "Vesna")
    pg.evaluate("() => { createCampaignFromWizard(); }")
    pg.wait_for_function("() => document.getElementById('wz-err').textContent.length > 0", timeout=8000)
    camp = enviado["campaign"]
    assert (camp["campaign_type"], camp["dnd_mode"]) == ("dark_fantasy", False)
    assert not camp["characters"]["vesna"].get("sheet")
    assert not erros, erros[:3]


def test_romance_scifi_e_faroeste_travam_as_regras(menu):
    """O D&D 5e é fantasia medieval: nesses gêneros o seletor trava em narrativa."""
    pg, erros, _ = menu
    pg.evaluate("() => openWizard()")
    pg.wait_for_selector("#wizard-overlay:not(.hidden)", timeout=5000)
    for genero in ("romance", "scifi", "faroeste"):
        pg.select_option("#wz-type", genero)
        assert pg.input_value("#wz-regras") == "livre", genero
        assert pg.is_disabled("#wz-regras"), genero
        assert pg.is_visible("#wz-regras-dica"), genero
    for genero in ("fantasia", "dark_fantasy", "horror", "misterio"):
        pg.select_option("#wz-type", genero)
        assert not pg.is_disabled("#wz-regras"), genero
        assert not pg.is_visible("#wz-regras-dica"), genero
    # Reabrir o assistente depois de um romance volta à fantasia destravada.
    pg.select_option("#wz-type", "romance")
    pg.evaluate("() => openWizard()")
    assert pg.input_value("#wz-type") == "fantasia"
    assert not pg.is_disabled("#wz-regras") and pg.input_value("#wz-regras") == "dnd"
    assert not erros, erros[:3]


def test_romance_criado_vai_sem_regras_mesmo_com_d_e_d_escolhido_antes(menu):
    pg, erros, enviado = menu
    # Escolhe D&D numa fantasia e depois troca o gênero para romance.
    _wizard(pg, "fantasia", "dnd")
    pg.evaluate("() => wizardGoTo(1)")
    pg.select_option("#wz-type", "romance")
    pg.evaluate("() => { wizardGoTo(2); }")
    pg.wait_for_selector("#wz-chars-list .cwc", timeout=5000)
    assert "Modo narrativo" in pg.inner_text("#wz-char-mode-hint")
    _nome(pg, "Lucas")
    pg.evaluate("() => { createCampaignFromWizard(); }")
    pg.wait_for_function("() => document.getElementById('wz-err').textContent.length > 0", timeout=8000)
    camp = enviado["campaign"]
    assert (camp["campaign_type"], camp["dnd_mode"]) == ("romance", False)
    assert not camp["characters"]["lucas"].get("sheet")
    assert not erros, erros[:3]


def test_importar_romance_desliga_a_caixa_e_volta_na_fantasia(menu):
    pg, erros, _ = menu
    pg.evaluate("() => openImportModal()")
    pg.wait_for_selector("#import-overlay:not(.hidden)", timeout=5000)
    assert pg.is_checked("#import-dnd")
    pg.click(".import-tab[data-theme='romance']")
    assert pg.is_disabled("#import-dnd") and not pg.is_checked("#import-dnd")
    assert '"dnd_mode": false' in pg.inner_text("#import-prompt-text")
    # Ver o prompt do romance não desliga as regras da fantasia.
    pg.click(".import-tab[data-theme='fantasia']")
    assert not pg.is_disabled("#import-dnd") and pg.is_checked("#import-dnd")
    assert not erros, erros[:3]


def test_gerar_com_ia_manda_genero_e_regras(menu):
    pg, erros, _ = menu
    pedido = {}

    def lore(route, request):
        pedido.update(json.loads(request.post_data or "{}"))
        route.fulfill(status=400, content_type="application/json",
                      body=json.dumps({"error": "interceptado pelo teste"}))

    pg.route("**/api/campaigns/generate-lore", lore)
    pg.evaluate("() => openWizard()")
    pg.select_option("#wz-type", "horror")
    pg.select_option("#wz-regras", "dnd")
    pg.check("#wz-ai-toggle")
    pg.fill("#wz-ai-prompt", "Uma aldeia que some a cada lua nova")
    pg.click("#wz-ai-btn")
    pg.wait_for_function("() => document.getElementById('wz-ai-status').textContent.length > 0",
                         timeout=8000)
    assert (pedido["campaign_type"], pedido["dnd_mode"]) == ("horror", True)
    assert not erros, erros[:3]


def test_editor_abre_campanha_antiga_como_fantasia_com_regras(menu, app_no_ar):
    """
    Campanha salva quando "dnd" era gênero. O servidor migra ao carregar,
    mas o editor não pode depender disso: a rota devolve aqui o JSON cru,
    como ele está gravado.
    """
    pg, erros, _ = menu
    import requests

    url = app_no_ar[0]
    cru = None

    def antiga(route, request):
        nonlocal cru
        if request.method != "GET":
            return route.continue_()
        corpo = requests.get(request.url, headers=request.headers, timeout=10).json()
        corpo_camp = corpo.get("campaign", corpo)
        corpo_camp["campaign_type"] = "dnd"
        corpo_camp["dnd_mode"] = False
        cru = corpo_camp
        route.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))

    pg.route("**/api/campaigns/*", antiga)
    pg.evaluate("() => openEditCampaign(new Event('click'), window.__campanha)")
    pg.wait_for_selector("#edit-overlay:not(.hidden)", timeout=8000)
    pg.wait_for_timeout(500)
    assert cru is not None, "o editor não buscou a campanha"
    assert pg.input_value("#ed-regras") == "dnd"
    assert pg.input_value("#ed-type") == "fantasia"
    assert not erros, erros[:3]


def test_importar_tem_regras_numa_caixa_a_parte(menu):
    pg, erros, _ = menu
    pg.evaluate("() => openImportModal()")
    pg.wait_for_selector("#import-overlay:not(.hidden)", timeout=5000)
    pg.click(".import-tab[data-theme='dark_fantasy']")
    texto = pg.inner_text("#import-prompt-text")
    assert '"campaign_type": "dark_fantasy"' in texto and '"dnd_mode": true' in texto
    pg.uncheck("#import-dnd")
    texto = pg.inner_text("#import-prompt-text")
    assert '"dnd_mode": false' in texto and '"sheet"' not in texto
    assert not erros, erros[:3]
