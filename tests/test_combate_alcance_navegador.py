"""
test_combate_alcance_navegador.py

`test_combate_alcance_na_tela.py` prova no motor. Isto prova o que só a tela
tática mostra:

  • o inimigo corpo-a-corpo que começa duas zonas longe, na vez dele, não
    deixa a tela presa em "Turno do Inimigo" — ela anda sozinha até a vez
    de alguém do grupo;
  • ao escolher uma arma de corpo-a-corpo, o alvo de outra zona aparece
    desabilitado e marcado "fora de alcance".

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
def abrir_jogo(app_no_ar):
    from playwright.sync_api import sync_playwright
    import requests

    url, nome, cap = app_no_ar
    with sync_playwright() as pw:
        nav = pw.chromium.launch()

        def abrir(estado):
            requests.post(f"{url}/__estado", json=estado, timeout=10)
            ctx = nav.new_context(viewport={"width": 1440, "height": 980})
            ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO))
            pg = ctx.new_page()
            erros = []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.goto(f"{url}/game.html", wait_until="networkidle")
            pg.wait_for_selector("#combat-overlay:not(.hidden)", timeout=8000)
            return pg, erros

        yield abrir, cap
        nav.close()


def test_inimigo_longe_nao_prende_a_tela_no_turno_dele(abrir_jogo):
    abrir, cap = abrir_jogo
    estado = copy.deepcopy(cap.COMBATE_ZONAS)
    cs = estado["combat_state"]
    # A vez é da Victoria, sozinha na Sacada; o grupo inteiro no Portão.
    cs["current_turn_index"] = cs["initiative_order"].index("Victoria")
    cs["posicoes"] = {"stelar": "Portão", "helena": "Portão",
                      "natasha": "Portão", "victoria": "Sacada"}

    pg, erros = abrir(estado)

    pg.wait_for_function(
        "() => !/Turno do Inimigo/.test(document.getElementById('cbt-action-title').textContent)",
        timeout=10000)
    assert "O que fará" in pg.inner_text("#cbt-action-title")
    assert not erros, erros[:3]


def test_alvo_de_outra_zona_aparece_fora_de_alcance(abrir_jogo):
    abrir, cap = abrir_jogo
    pg, erros = abrir(copy.deepcopy(cap.COMBATE_ZONAS))   # Stelar no Pátio, Victoria na Sacada

    pg.evaluate("() => window.Combat._sel('attack')")
    pg.wait_for_selector("#cbt-targets:not(.hidden)")
    armas = pg.locator("#cbt-targets .cbt-btn").all_inner_texts()
    corpo_a_corpo = next(i for i, t in enumerate(armas)
                         if "arco" not in t.lower() and "besta" not in t.lower())
    pg.locator("#cbt-targets .cbt-btn").nth(corpo_a_corpo).click()

    victoria = pg.locator("#cbt-targets .cbt-btn", has_text="Victoria")
    assert victoria.is_disabled()
    assert "fora de alcance" in victoria.inner_text()
    assert not erros, erros[:3]


def test_seletor_aberto_nao_corta_o_titulo_do_turno(abrir_jogo):
    """
    O seletor de alvo não cabe no painel de ação e ele rola por dentro. O
    título "O que fará Stelar?" saía de vista cortado ao meio; agora fica
    grudado no topo do painel, inteiro e por cima dos botões.
    """
    abrir, cap = abrir_jogo
    pg, erros = abrir(copy.deepcopy(cap.COMBATE_ZONAS))

    pg.evaluate("() => window.Combat._sel('attack')")
    pg.wait_for_selector("#cbt-targets:not(.hidden)")
    pg.locator("#cbt-targets .cbt-btn").first.click()
    pg.wait_for_selector("#cbt-targets .cbt-fora")
    pg.wait_for_timeout(600)          # o scrollIntoView é suave

    medidas = pg.evaluate("""() => {
        const painel = document.getElementById('cbt-actionbar');
        const titulo = document.getElementById('cbt-action-title');
        const p = painel.getBoundingClientRect(), t = titulo.getBoundingClientRect();
        const noMeio = document.elementFromPoint(t.left + 20, t.top + t.height / 2);
        return {rolou: painel.scrollTop, painelTopo: p.top, tituloTopo: t.top,
                tituloBase: t.bottom, painelBase: p.bottom,
                visivel: titulo.contains(noMeio), sombra: painel.classList.contains('cbt-rolado')};
    }""")
    assert medidas["rolou"] > 0, f"o painel não rolou: o teste não exercita o corte ({medidas})"
    assert medidas["tituloTopo"] >= medidas["painelTopo"] - 1, medidas
    assert medidas["tituloBase"] <= medidas["painelBase"], medidas
    assert medidas["visivel"], f"o título ficou coberto ({medidas})"
    assert medidas["sombra"], medidas
    assert "O que fará Stelar?" in pg.inner_text("#cbt-action-title")
    assert not erros, erros[:3]


def test_diario_do_estado_de_exemplo_cita_a_arma_equipada():
    """O diário das capturas dizia "Espada Longa" com o Montante Rúnico na mão."""
    import capturar_telas as cap
    campanha = json.loads((RAIZ / "scripts" / "temp.json").read_text(encoding="utf-8"))
    arma = campanha["characters"]["stelar"]["sheet"]["equipamentos"]["arma_principal"]
    ataques = [e["msg"] for e in cap.COMBATE_ATIVO["combat_state"]["log"]
               if e.get("actor") == "Stelar" and e.get("type") == "attack"]
    assert ataques and all(arma in m for m in ataques), ataques
