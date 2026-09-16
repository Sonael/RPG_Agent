"""
test_atitude_no_preco_navegador.py

As duas telas que mostram o que a relação com o lojista faz: o balcão, com o
preço que ele vai cobrar deste grupo, e a ficha dele, com o estoque e o que a
atitude vale em número.

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


def _estado(cap, atitude=None):
    """A forja do Torbin, agora com dono — e com a relação que o teste pedir."""
    estado = copy.deepcopy(cap.LOJA)
    estado["lojas"]["forja do torbin"]["dono"] = "Torbin"
    estado.setdefault("characters", {})["torbin"] = {
        "name": "Torbin", "sheet": None, "status": "vivo",
        "local": "Oakhaven", "description": "Ferreiro de Oakhaven.",
        "atitude": atitude if atitude is not None else 0,
        "atitude_historico": ([{"delta": atitude, "motivo": "o grupo salvou a filha dele", "cap": 2}]
                              if atitude else []),
    }
    return estado


@pytest.fixture
def abrir(app_no_ar):
    from playwright.sync_api import sync_playwright
    import requests

    url, nome, cap = app_no_ar
    with sync_playwright() as pw:
        nav = pw.chromium.launch()

        def _abrir(estado):
            requests.post(f"{url}/__estado", json=estado, timeout=10)
            ctx = nav.new_context(viewport={"width": 1440, "height": 980})
            ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO))
            pg = ctx.new_page()
            erros = []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
            pg.goto(f"{url}/game.html", wait_until="networkidle")
            cap._sanear(pg)
            pg.wait_for_timeout(600)
            return pg, erros

        yield _abrir, cap
        nav.close()


def _abrir_loja(pg):
    pg.evaluate("() => window.Shop._abrir()")
    pg.wait_for_selector("#shop-overlay:not(.hidden) .shp-item", timeout=5000)


def _abrir_ficha(pg, nome):
    pg.evaluate("(n) => window.Personagens._abrir(n)", nome)
    pg.wait_for_selector("#pessoa-overlay:not(.hidden)", timeout=5000)
    pg.wait_for_function(
        f"() => document.getElementById('psn-nome').textContent === {nome!r}", timeout=5000)


def _linha(pg, item):
    return pg.text_content(
        f"#shop-overlay .shp-item:has(.shp-item-nome:text-is('{item}')) .shp-preco")


def test_balcao_sem_relacao_mostra_so_a_tabela(abrir):
    _abrir, cap = abrir
    pg, erros = _abrir(_estado(cap))
    _abrir_loja(pg)
    assert "15 po" in _linha(pg, "Espada Longa")
    assert "de 15" not in _linha(pg, "Espada Longa")
    assert pg.is_hidden("#shp-atitude")
    assert not erros, erros[:3]


def test_balcao_mostra_o_desconto_e_de_onde_ele_vem(abrir):
    _abrir, cap = abrir
    pg, erros = _abrir(_estado(cap, atitude=80))
    _abrir_loja(pg)
    preco = _linha(pg, "Espada Longa")
    assert "12 po" in preco and "de 15" in preco       # 15 com 20% de desconto
    assert pg.is_visible("#shp-atitude"), "o aviso da relação não apareceu"
    aviso = pg.text_content("#shp-atitude")
    assert "Torbin" in aviso and "-20%" in aviso
    assert not erros, erros[:3]


def test_balcao_marca_o_preco_salgado_do_lojista_hostil(abrir):
    _abrir, cap = abrir
    pg, erros = _abrir(_estado(cap, atitude=-60))
    _abrir_loja(pg)
    assert "17 po" in _linha(pg, "Espada Longa")       # 15 com 15% a mais
    assert "shp-atitude-cara" in (pg.get_attribute("#shp-atitude", "class") or "")
    assert not erros, erros[:3]


def test_ficha_do_lojista_traz_o_estoque_e_os_efeitos(abrir):
    _abrir, cap = abrir
    pg, erros = _abrir(_estado(cap, atitude=80))
    _abrir_ficha(pg, "Torbin")
    ligacoes = pg.text_content("#psn-ligacoes")
    assert "Atende em Forja do Torbin" in ligacoes
    assert "Espada Longa" in ligacoes and "12 po" in ligacoes and "tabela 15" in ligacoes

    relacao = pg.text_content("#psn-relacao")
    assert "-4 na CD de testes sociais com ele" in relacao
    assert "-20% no preço da loja dele" in relacao
    assert not erros, erros[:3]


def test_ficha_sem_relacao_nao_promete_efeito(abrir):
    _abrir, cap = abrir
    pg, erros = _abrir(_estado(cap))
    _abrir_ficha(pg, "Torbin")
    assert pg.locator("#psn-relacao .psn-efeitos").count() == 0
    assert not erros, erros[:3]
