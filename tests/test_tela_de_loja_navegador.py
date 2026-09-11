"""
test_tela_de_loja_navegador.py

O único teste do projeto que roda o JAVASCRIPT de verdade.

`test_tela_de_loja.py` cobre o motor por trás da tela, e as capturas em
`scripts/capturar_telas.py` provam que ela DESENHA. Nenhum dos dois prova que
CLICAR funciona — e a tela de loja existe inteira por causa do clique. Um
`onclick` com nome errado passaria pelos dois: a captura sairia idêntica e a
suíte continuaria verde.

Aqui o Chromium abre a página real, clica nos botões reais e confere o que
mudou na bolsa e na carga.

Depende do Playwright, que NÃO está em requirements-dev.txt (só o script de
captura usa). Sem ele o teste é pulado em vez de quebrar a suíte de quem
instalou só o básico:

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

pytestmark = pytest.mark.slow          # abre um navegador: não é teste de loop


@pytest.fixture(scope="module")
def loja_no_ar():
    """App real numa thread, com os dublês da captura e a loja semeada."""
    import capturar_telas as cap
    import requests

    campanha = json.loads((RAIZ / "scripts" / "temp.json").read_text(encoding="utf-8"))
    nome = campanha.get("name") or "Crônicas de Oakhaven"
    campanha["name"] = nome

    url, parar = cap._subir_servidor(campanha, nome)
    try:
        yield url, nome, cap
    finally:
        parar()


@pytest.fixture
def pagina(loja_no_ar):
    from playwright.sync_api import sync_playwright
    import requests

    url, nome, cap = loja_no_ar
    # Semeia a cada teste, não uma vez por módulo. O servidor é de módulo (é
    # caro subir), mas a CAMPANHA não pode ser: a primeira versão deste
    # arquivo comprava a cota de malha num teste e os seguintes começavam com
    # 21 po e a prateleira já vazia — duas falhas que não eram da tela.
    requests.post(f"{url}/__estado", json=cap.LOJA, timeout=10)
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        ctx = nav.new_context(viewport={"width": 1440, "height": 900})
        # Sem token no localStorage o game.html manda para o login, e lá o
        # shop.js nem chega a ser carregado — foi assim que a primeira versão
        # deste teste "falhou" sem haver defeito nenhum na tela.
        ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO))
        pg = ctx.new_page()

        erros = []
        pg.on("pageerror", lambda e: erros.append(str(e)))
        pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)

        pg.goto(f"{url}/game.html", wait_until="networkidle")
        cap._sanear(pg)
        pg.wait_for_selector("#shop-overlay:not(.hidden)", timeout=10000)
        yield pg, erros
        nav.close()


def _bolsa(pg):
    return pg.inner_text(".shp-bolsa-moedas")


def _carga(pg):
    return float(pg.inner_text(".shp-carga-num").split("/")[0].strip())


def _botao(pg, item):
    return ("xpath=//div[contains(@class,'shp-item')]"
            f"[.//span[text()={item!r}]]//button")


def test_a_tela_abre_sozinha_ao_chegar_na_loja(pagina):
    """
    Sem `js` para abri-la de propósito: o gatilho automático É a feature. Se
    precisasse de um empurrão, este teste é o que denuncia.
    """
    pg, _ = pagina
    assert pg.is_visible("#shop-overlay")
    assert "Forja do Torbin" in pg.inner_text(".shp-title")


def test_comprar_mexe_na_bolsa_e_na_carga(pagina):
    pg, _ = pagina
    assert "96 po" in _bolsa(pg)
    peso_antes = _carga(pg)

    pg.click(_botao(pg, "Cota de Malha"))       # 75 po, 25 kg
    pg.wait_for_timeout(600)

    assert "21 po" in _bolsa(pg)
    assert _carga(pg) > peso_antes + 20, "a carga não acompanhou a compra"
    assert "comprou" in pg.inner_text("#shp-msg")


def test_o_item_comprado_aparece_na_aba_vender(pagina):
    pg, _ = pagina
    pg.click(_botao(pg, "Cota de Malha"))
    pg.wait_for_timeout(600)

    pg.click("#shp-aba-vender")
    pg.wait_for_timeout(400)

    nomes = pg.eval_on_selector_all(
        ".shp-item-nome", "els => els.map(e => e.textContent.trim())")
    assert "Cota de Malha" in nomes


def test_vender_paga_metade(pagina):
    pg, _ = pagina
    pg.click("#shp-aba-vender")
    pg.wait_for_timeout(400)

    pg.click(_botao(pg, "Espada Curta"))        # tabela 10 → paga 5
    pg.wait_for_timeout(600)

    assert "101 po" in _bolsa(pg)
    assert "metade da tabela" in pg.inner_text("#shp-msg")


def test_item_fora_do_alcance_fica_mesmo_desabilitado(pagina):
    """
    `opacity` é cosmética: um botão só apagado continua clicando. O que vale
    é o atributo `disabled` — e, mesmo forçando o clique, a bolsa não pode
    se mexer.
    """
    pg, _ = pagina
    caros = pg.eval_on_selector_all(
        ".shp-item-caro .shp-btn", "els => els.map(e => e.disabled)")
    assert caros and all(caros), f"item caro com botão ativo: {caros}"

    antes = _bolsa(pg)
    pg.eval_on_selector(".shp-item-caro .shp-btn", "el => el.click()")
    pg.wait_for_timeout(500)
    assert _bolsa(pg) == antes


def test_fechar_deixa_a_pilula_de_voltar(pagina):
    pg, _ = pagina
    pg.click(".shp-close")
    pg.wait_for_timeout(400)

    assert not pg.is_visible("#shop-overlay")
    assert pg.is_visible("#shp-reopen")
    assert "Forja do Torbin" in pg.inner_text("#shp-reopen")

    pg.click("#shp-reopen")
    pg.wait_for_timeout(400)
    assert pg.is_visible("#shop-overlay")


def test_a_tela_nao_solta_erro_no_console(pagina):
    pg, erros = pagina
    pg.click(_botao(pg, "Escudo"))
    pg.wait_for_timeout(500)
    pg.click("#shp-aba-vender")
    pg.wait_for_timeout(400)
    pg.click("#shp-aba-comprar")
    pg.wait_for_timeout(400)
    assert not erros, f"erros no console: {erros[:3]}"
