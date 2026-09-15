"""
test_elenco_navegador.py

O índice de personagens no navegador: lista todos com a contagem do motor,
filtra (aqui, grupo, conhecidos, inimigos, mortos), busca sem acento pelo
nome, pelo lugar e pela descrição, abre a ficha certa (a do herói para quem é
do grupo com ficha, a do personagem para os outros) e cria personagem ou
membro pelo editor de sempre. As telas que abrem sozinhas esperam ele fechar.

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
    estado = copy.deepcopy(cap.MAPA)
    estado["saque_proposto"] = None
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
        yield pg, erros, url
        nav.close()


def _abrir(pg, filtro="todos"):
    pg.evaluate(f"() => window.Elenco._abrir('{filtro}')")
    pg.wait_for_selector("#elenco-overlay:not(.hidden) .elc-cartao", timeout=5000)


def _nomes(pg):
    return [el.get_attribute("data-nome") for el in pg.query_selector_all("#elc-lista .elc-cartao")]


def _filtrar(pg, filtro):
    pg.click(f"#elc-filtros .elc-filtro[data-filtro='{filtro}']")
    pg.wait_for_selector(f"#elc-filtros .elc-filtro-ativo[data-filtro='{filtro}']", timeout=3000)


def test_lista_todos_com_a_contagem_do_motor(pagina):
    pg, erros, _ = pagina
    _abrir(pg)
    motor = pg.evaluate("() => window.Elenco._estado()")
    assert len(_nomes(pg)) == motor["contagem"]["todos"] == len(motor["personagens"])
    for filtro, quantos in motor["contagem"].items():
        assert str(quantos) in pg.inner_text(f"#elc-filtros .elc-filtro[data-filtro='{filtro}']")
    # O grupo vem primeiro, depois quem está na praça.
    nomes = _nomes(pg)
    grupo = [p["nome"] for p in motor["personagens"] if p["do_grupo"]]
    assert set(nomes[:len(grupo)]) == set(grupo)
    assert nomes.index("Guarda Tiel") < nomes.index("Brom")
    assert not erros, erros[:3]


def test_filtros(pagina):
    pg, _, _ = pagina
    _abrir(pg)
    _filtrar(pg, "aqui")
    aqui = _nomes(pg)
    assert "Guarda Tiel" in aqui and "Velha Nana" in aqui and "Brom" not in aqui
    _filtrar(pg, "mortos")
    assert _nomes(pg) == ["Velho Osric"]
    _filtrar(pg, "grupo")
    assert "Guarda Tiel" not in _nomes(pg) and _nomes(pg)
    _filtrar(pg, "conhecidos")
    assert "Brom" in _nomes(pg) and "Velho Osric" not in _nomes(pg)


def test_busca_sem_acento_por_nome_lugar_e_descricao(pagina):
    pg, _, _ = pagina
    _abrir(pg)
    pg.fill("#elc-busca", "ferreiro")
    pg.wait_for_function("() => document.querySelectorAll('#elc-lista .elc-cartao').length === 1", timeout=3000)
    assert _nomes(pg) == ["Brom"]
    pg.fill("#elc-busca", "boticario")
    pg.wait_for_function("() => [...document.querySelectorAll('#elc-lista .elc-cartao')]"
                         ".some(c => c.dataset.nome === 'Mira')", timeout=3000)
    pg.fill("#elc-busca", "floresta das brumas")
    pg.wait_for_function("() => [...document.querySelectorAll('#elc-lista .elc-cartao')]"
                         ".map(c => c.dataset.nome).join() === 'Eremita'", timeout=3000)
    pg.fill("#elc-busca", "ninguém se chama assim")
    pg.wait_for_selector("#elc-lista .lcl-vazio", timeout=3000)


def test_clicar_abre_a_ficha_certa(pagina):
    pg, erros, _ = pagina
    _abrir(pg)
    pg.click("#elc-lista .elc-cartao[data-nome='Brom']")
    pg.wait_for_function("() => document.getElementById('psn-nome').textContent === 'Brom'", timeout=5000)
    assert pg.is_hidden("#elenco-overlay")
    pg.evaluate("() => window.Personagens._fechar()")

    _abrir(pg, "grupo")
    heroi = _nomes(pg)[0]
    pg.click(f"#elc-lista .elc-cartao[data-nome='{heroi}']")
    pg.wait_for_function(f"() => document.getElementById('hro-nome').textContent === {heroi!r}", timeout=5000)
    assert not erros, erros[:3]


def test_novo_personagem_e_novo_membro_abrem_o_editor(pagina):
    pg, _, _ = pagina
    _abrir(pg)
    pg.click("#elenco-overlay button:has-text('Novo personagem')")
    pg.wait_for_selector("#edit-overlay:not(.hidden)", timeout=5000)
    assert "Personagem" in pg.text_content("#edit-type")
    assert pg.is_hidden("#elenco-overlay")
    pg.evaluate("() => closeEditModal()")

    _abrir(pg)
    pg.click("#elenco-overlay button:has-text('Novo membro do grupo')")
    pg.wait_for_selector("#edit-overlay:not(.hidden)", timeout=5000)
    assert "Grupo" in pg.text_content("#edit-type")


def test_aberto_redesenha_quando_o_mestre_registra_alguem(pagina):
    import requests
    pg, _, url = pagina
    _abrir(pg)
    requests.post(f"{url}/__estado", json={"characters": {"mercador ruivo": {
        "name": "Mercador Ruivo", "description": "Chegou com a caravana.", "status": "vivo",
        "local": "Porto de Vhar", "sheet": None, "inventario": [], "habilidades": []}}}, timeout=10)
    pg.evaluate("() => window.sincronizarTelas()")
    pg.wait_for_function("() => [...document.querySelectorAll('#elc-lista .elc-cartao')]"
                         ".some(c => c.dataset.nome === 'Mercador Ruivo')", timeout=5000)


def test_saque_nao_abre_por_cima_do_indice(pagina):
    import capturar_telas as cap
    import requests
    pg, _, url = pagina
    _abrir(pg)
    requests.post(f"{url}/__estado", json=copy.deepcopy(cap.SAQUE), timeout=10)
    pg.evaluate("() => window.sincronizarTelas()")
    pg.wait_for_timeout(1000)
    assert pg.is_hidden("#loot-overlay"), "o saque abriu por cima do índice"
    pg.evaluate("() => window.Elenco._fechar()")
    pg.wait_for_selector("#loot-overlay:not(.hidden)", timeout=5000)
