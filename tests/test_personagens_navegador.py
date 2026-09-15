"""
test_personagens_navegador.py

A ficha do personagem no navegador: abre pelo cartão da Enciclopédia e pelo
"Ver ficha" da ficha do local, mostra a relação com o grupo e o porquê, o que
o grupo sabe e as ligações, esconde as notas do mestre, e "Falar com" / "Ir
até onde está" mandam a fala do jogador ao mestre.

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
        pg.evaluate("() => { window.__enviado = null;"
                    " window.sendToAgent = async (t) => { window.__enviado = t; }; }")
        yield pg, erros, url
        nav.close()


def _esperar_ficha(pg, nome):
    pg.wait_for_selector("#pessoa-overlay:not(.hidden)", timeout=5000)
    pg.wait_for_function(
        f"() => document.getElementById('psn-nome').textContent === {nome!r}"
        " && !document.getElementById('psn-msg').textContent", timeout=5000)


def _abrir_pela_enciclopedia(pg, nome):
    pg.click(".tab-btn[data-tab='enciclopedia']")
    cartao = pg.locator("#sb-chars .char-card", has_text=nome).first
    cartao.wait_for(state="visible", timeout=5000)
    cartao.locator(".char-name").click()
    _esperar_ficha(pg, nome)


def test_cartao_da_enciclopedia_abre_a_ficha_completa(pagina):
    pg, erros, _ = pagina
    _abrir_pela_enciclopedia(pg, "Brom")

    assert not pg.is_visible("#edit-overlay"), "o cartão abriu o editor em vez da ficha"
    assert "Forja de Cliviate" in pg.inner_text("#psn-onde")
    assert "Desconfiado com forasteiros" in pg.inner_text("#psn-tracos")

    relacao = pg.inner_text("#psn-relacao")
    assert "+35" in relacao
    assert "O grupo trouxe o martelo do avô de volta" in relacao
    assert "-10" in relacao
    # O mais recente primeiro.
    assert relacao.index("Alden defendeu a forja") < relacao.index("Lyra pechinchou")

    assert "O filho dele sumiu na estrada do norte" in pg.inner_text("#psn-sabe")
    ligacoes = pg.inner_text("#psn-ligacoes")
    assert "O filho do ferreiro" in ligacoes
    assert "devolveu o martelo do avô" in ligacoes
    assert "Guardas tentaram fechar a forja" in ligacoes
    assert "Trabalha em Forja de Cliviate" in ligacoes
    assert not erros, erros[:3]


def test_notas_do_mestre_nao_aparecem(pagina):
    pg, _, _ = pagina
    _abrir_pela_enciclopedia(pg, "Brom")
    assert "SEGREDO" not in pg.inner_text("#pessoa-overlay")
    pg.keyboard.press("Escape")
    assert "SEGREDO" not in pg.inner_text("#sb-chars"), "o cartão mostrava as notas do mestre"


def test_falar_com_manda_a_fala_do_jogador(pagina):
    pg, _, _ = pagina
    _abrir_pela_enciclopedia(pg, "Brom")
    pg.click("#psn-onde button:has-text('Falar com')")
    pg.wait_for_function("() => window.__enviado !== null", timeout=3000)
    assert pg.evaluate("() => window.__enviado") == "Quero falar com Brom."
    assert not pg.is_visible("#pessoa-overlay")
    assert "Quero falar com Brom." in pg.inner_text("#chat-history")


def test_ir_ate_onde_ele_esta(pagina):
    pg, _, _ = pagina
    _abrir_pela_enciclopedia(pg, "Brom")
    pg.click("#psn-onde button:has-text('Ir até onde está')")
    pg.wait_for_function("() => window.__enviado !== null", timeout=3000)
    assert pg.evaluate("() => window.__enviado") == "Vamos até Forja de Cliviate."


def test_longe_e_sem_historico(pagina):
    pg, erros, _ = pagina
    pg.evaluate("() => window.Personagens._abrir('Eremita')")
    _esperar_ficha(pg, "Eremita")
    assert pg.is_disabled("#psn-onde button:has-text('Falar com')")
    assert pg.locator("#psn-onde button:has-text('Ir até')").count() == 0
    assert "Nenhuma mudança registrada" in pg.inner_text("#psn-relacao")
    assert "Nada registrado" in pg.inner_text("#psn-sabe")
    assert "Nenhuma ligação" in pg.inner_text("#psn-ligacoes")
    assert not erros, erros[:3]


def test_ver_ficha_a_partir_da_ficha_do_local_e_voltar(pagina):
    pg, _, _ = pagina
    pg.evaluate("() => window.Locais._abrir('Forja de Cliviate')")
    item = "#local-overlay .lcl-item[data-nome='Brom']"
    pg.wait_for_selector(item, timeout=5000)
    pg.click(f"{item} button:has-text('Ver ficha')")
    _esperar_ficha(pg, "Brom")
    assert not pg.is_visible("#local-overlay")

    pg.click("#psn-onde a:has-text('Forja de Cliviate')")
    pg.wait_for_function("() => document.getElementById('lcl-nome').textContent === 'Forja de Cliviate'",
                         timeout=5000)
    assert not pg.is_visible("#pessoa-overlay")


def test_editor_grava_o_que_o_grupo_sabe_e_a_ficha_mostra(pagina):
    pg, erros, _ = pagina
    _abrir_pela_enciclopedia(pg, "Brom")
    pg.click("#psn-editar")
    pg.wait_for_selector("#edit-overlay:not(.hidden) #ef-conhecido", timeout=5000)

    rotulos = pg.inner_text("#edit-body")
    assert "Notas do mestre" in rotulos and "não aparecem na ficha" in rotulos
    assert "O filho dele sumiu" in pg.input_value("#ef-conhecido")

    pg.fill("#ef-conhecido", "O filho dele sumiu na estrada do norte\nDeve dinheiro à guarda")
    pg.evaluate("() => { saveCurrentItem(); }")
    pg.wait_for_selector("#edit-overlay", state="hidden", timeout=5000)

    pg.evaluate("() => window.Personagens._abrir('Brom')")
    _esperar_ficha(pg, "Brom")
    sabe = pg.inner_text("#psn-sabe")
    assert "Deve dinheiro à guarda" in sabe
    assert "Aprendeu o ofício" not in sabe
    assert not erros, erros[:3]
