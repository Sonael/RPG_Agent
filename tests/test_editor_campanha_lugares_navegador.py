"""
test_editor_campanha_lugares_navegador.py

O editor da campanha (menu) mostra "Onde está" no personagem e "Fica dentro
de" no local, com sugestões dos lugares conhecidos, e o que se salva ali
chega ao servidor com o nome do lugar e sem apagar o que o editor não
conhece.

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
    cap._mesclar(campanha, copy.deepcopy(cap.CIDADE))
    campanha["characters"]["brom"]["atitude"] = 25          # o editor não conhece
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
    monkeypatch.setattr(database, "save_campaign", lambda uid, n, dados: gravado.update(dados))
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
        pg.wait_for_function("() => typeof edLocs !== 'undefined' && edLocs.length > 0", timeout=8000)
        yield pg, erros, gravado
        nav.close()


def _abrir_personagem(pg, nome):
    i = pg.evaluate("(n) => edChars.findIndex(c => c.name === n)", nome)
    pg.evaluate("(i) => { editGoTo(2); edChars[i]._open = true; edRenderChars(); }", i)
    pg.wait_for_timeout(300)
    return f"#ed-cb-{i} .ed-onde-esta"


def test_personagem_mostra_onde_esta(editor):
    pg, erros, _ = editor
    campo = _abrir_personagem(pg, "Brom")
    assert pg.input_value(campo) == "Forja de Cliviate"
    assert pg.get_attribute(campo, "list") == "ed-lugares"
    assert not erros, erros[:3]


def test_local_mostra_fica_dentro_de_e_sugestoes(editor):
    pg, _, _ = editor
    pg.evaluate("() => editGoTo(3)")
    pg.wait_for_timeout(300)
    i = pg.evaluate("() => edLocs.findIndex(l => l.name === 'Praça de Cliviate')")
    assert pg.input_value(f"#ed-locs-list .wz-loc-card >> nth={i} >> .ed-dentro-de") == "Cliviate"
    sugestoes = pg.evaluate("() => [...document.querySelectorAll('#ed-lugares option')].map(o => o.value)")
    assert "Taverna do Caldeirão" in sugestoes and "Forja de Cliviate" in sugestoes


def test_salvar_grava_lugares_com_o_nome_e_mantem_a_atitude(editor):
    pg, _, gravado = editor
    campo = _abrir_personagem(pg, "Guarda Tiel")
    pg.fill(campo, "taverna do caldeirão")
    pg.dispatch_event(campo, "change")

    pg.evaluate("() => editGoTo(3)")
    pg.wait_for_timeout(300)
    i = pg.evaluate("() => edLocs.findIndex(l => l.name === 'Floresta das Brumas')")
    dentro = f"#ed-locs-list .wz-loc-card >> nth={i} >> .ed-dentro-de"
    pg.fill(dentro, "")
    pg.dispatch_event(dentro, "change")

    # Sem aguardar a promessa: depois de salvar ela espera o diálogo
    # "Campanha atualizada" ser fechado.
    pg.evaluate("() => { saveEditedCampaign(); }")
    pg.wait_for_selector("#dialog-overlay:not(.hidden)", timeout=10000)
    assert "salva com sucesso" in pg.inner_text("#dialog-overlay")

    assert gravado["characters"]["guarda tiel"]["local"] == "Taverna do Caldeirão"
    assert gravado["characters"]["brom"]["atitude"] == 25, "salvar pelo menu apagou a atitude"
    assert "praça de cliviate" in gravado["locations"], "a chave voltou a usar sublinhado"
    assert gravado["locations"]["praça de cliviate"]["dentro_de"] == "Cliviate"
    assert "dentro_de" not in gravado["locations"]["floresta das brumas"]
