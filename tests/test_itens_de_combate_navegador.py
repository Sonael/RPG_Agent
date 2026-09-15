"""
test_itens_de_combate_navegador.py

Itens na tela tática, no navegador: o item que o motor não conhece aparece
travado com o motivo, a poção só oferece quem está na mesma zona, o
arremesso oferece a zona vizinha (aliados inclusive) e marca "sem efeito"
onde não faria nada, e usar de verdade muda a vida e o diário.

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
    requests.post(f"{url}/__estado", json=copy.deepcopy(cap.COMBATE_ITENS), timeout=10)
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        ctx = nav.new_context(viewport={"width": 1440, "height": 980})
        ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO))
        pg = ctx.new_page()
        erros = []
        pg.on("pageerror", lambda e: erros.append(str(e)))
        pg.goto(f"{url}/game.html", wait_until="networkidle")
        pg.wait_for_selector("#combat-overlay:not(.hidden)", timeout=8000)
        yield pg, erros
        nav.close()


def _botao(pg, texto):
    return pg.locator("#cbt-targets .cbt-btn", has_text=texto).first


def _abrir_itens(pg):
    pg.click("#cbt-buttons .cbt-btn:has-text('Item')")
    pg.wait_for_selector("#cbt-targets:not(.hidden)")


def test_item_desconhecido_fica_travado_com_o_motivo(pagina):
    pg, erros = pagina
    _abrir_itens(pg)
    forca = _botao(pg, "Poção de Força de Gigante")
    assert forca.is_disabled()
    assert "efeito desconhecido" in forca.inner_text()
    assert "Ação Livre" in forca.get_attribute("title")
    assert not _botao(pg, "Frasco de Ácido").is_disabled()
    assert not erros, erros[:3]


def test_pocao_so_alcanca_a_mesma_zona_e_cura_de_verdade(pagina):
    pg, erros = pagina
    _abrir_itens(pg)
    _botao(pg, "Poção de Cura").click()
    pg.wait_for_selector("#cbt-targets .cbt-tgt-title:has-text('Curar quem')")

    helena = _botao(pg, "Helena")
    assert helena.is_disabled() and "fora de alcance" in helena.inner_text()
    stelar = _botao(pg, "Stelar")
    assert "(em si)" in stelar.inner_text()

    stelar.click()
    pg.wait_for_function(
        "() => [...document.querySelectorAll('#cbt-log .cbt-logline')]"
        ".some(l => /usou Poção de Cura em Stelar/.test(l.textContent))", timeout=5000)
    assert not erros, erros[:3]


def test_acido_alcanca_a_zona_vizinha_aliados_inclusive(pagina):
    pg, _ = pagina
    _abrir_itens(pg)
    _botao(pg, "Frasco de Ácido").click()
    pg.wait_for_selector("#cbt-targets .cbt-tgt-title:has-text('Alvo de Frasco de Ácido')")
    for nome in ("Victoria", "Helena", "Natasha"):
        assert not _botao(pg, nome).is_disabled(), f"{nome} está na zona vizinha"

    _botao(pg, "Victoria").click()
    pg.wait_for_function(
        "() => [...document.querySelectorAll('#cbt-log .cbt-logline')]"
        ".some(l => /arremessou Frasco de Ácido em Victoria/.test(l.textContent))", timeout=5000)


def test_agua_benta_sem_efeito_em_quem_nao_e_morto_vivo(pagina):
    pg, _ = pagina
    _abrir_itens(pg)
    _botao(pg, "Água Benta").click()
    pg.wait_for_selector("#cbt-targets .cbt-tgt-title:has-text('Alvo de Água Benta')")
    victoria = _botao(pg, "Victoria")
    assert victoria.is_disabled() and "sem efeito" in victoria.inner_text()
