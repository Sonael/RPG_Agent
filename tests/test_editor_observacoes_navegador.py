"""
test_editor_observacoes_navegador.py

As observações do mestre (quest_flags) saíram da barra lateral do jogo e
foram para o editor da campanha, no menu: aparecem no primeiro passo, dá para
adicionar, mudar e remover, e o salvar grava. O mesmo salvar também deixou
de apagar o capítulo de cada evento.

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
    campanha["quest_flags"] = {"ponte_caiu": "sim", "guarda_subornado": "Tiel, 5 po"}
    for i, ev in enumerate(campanha["events"]):
        ev["chapter"] = 1 if i < 2 else 2
    url, parar = cap._subir_servidor(campanha, nome)
    try:
        yield url, nome, cap
    finally:
        parar()


@pytest.fixture
def editor(app_no_ar, monkeypatch):
    from playwright.sync_api import sync_playwright
    from rpg import database

    url, nome, cap = app_no_ar
    gravado = {}
    monkeypatch.setattr(database, "save_campaign", lambda uid, n, dados: gravado.update(copy.deepcopy(dados)))
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        ctx = nav.new_context(viewport={"width": 1440, "height": 980})
        ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO))
        pg = ctx.new_page()
        erros = []
        pg.on("pageerror", lambda e: erros.append(str(e)))
        pg.goto(f"{url}/menu.html", wait_until="networkidle")
        cap._sanear(pg)
        pg.evaluate("(n) => openEditCampaign({stopPropagation(){}}, n)", nome)
        pg.wait_for_function("() => typeof edFlags !== 'undefined' && edFlags.length > 0", timeout=8000)
        yield pg, erros, gravado
        nav.close()


def _salvar(pg):
    pg.evaluate("() => { saveEditedCampaign(); }")
    pg.wait_for_selector("#dialog-overlay:not(.hidden)", timeout=10000)
    assert "salva com sucesso" in pg.inner_text("#dialog-overlay")


def _linhas(pg):
    return {el.query_selector(".ed-flag-chave").input_value(): el.query_selector(".ed-flag-valor").input_value()
            for el in pg.query_selector_all("#ed-flags-list .ed-flag")}


def _linha(pg, chave):
    i = pg.evaluate("(c) => edFlags.findIndex(f => f.chave === c)", chave)
    return f"#ed-flags-list .ed-flag[data-indice='{i}']"


def test_observacoes_aparecem_no_primeiro_passo(editor):
    pg, erros, _ = editor
    assert pg.is_visible("#ed-panel-1 #ed-flags-list")
    assert _linhas(pg) == {"ponte_caiu": "sim", "guarda_subornado": "Tiel, 5 po"}
    assert not erros, erros[:3]


def test_adicionar_mudar_e_remover_e_salvar(editor):
    pg, erros, gravado = editor
    valor = f"{_linha(pg, 'ponte_caiu')} .ed-flag-valor"
    pg.fill(valor, "não, foi consertada")
    pg.dispatch_event(valor, "change")
    pg.click(f"{_linha(pg, 'guarda_subornado')} .ed-flag-remover")
    pg.click("#ed-flag-add")
    nova = _linha(pg, "")
    pg.fill(f"{nova} .ed-flag-chave", "  selo_real  ")
    pg.dispatch_event(f"{nova} .ed-flag-chave", "change")
    pg.fill(f"{_linha(pg, '  selo_real  ')} .ed-flag-valor", "entregue")
    pg.dispatch_event(f"{_linha(pg, '  selo_real  ')} .ed-flag-valor", "change")
    # Linha sem nome não vai para a campanha.
    pg.click("#ed-flag-add")

    _salvar(pg)
    assert gravado["quest_flags"] == {"ponte_caiu": "não, foi consertada", "selo_real": "entregue"}
    assert not erros, erros[:3]


def test_salvar_mantem_o_capitulo_dos_eventos(editor):
    pg, _, gravado = editor
    _salvar(pg)
    assert [e.get("chapter") for e in gravado["events"]] == [1, 1, 2, 2]
