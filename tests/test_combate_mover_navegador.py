"""
test_combate_mover_navegador.py

O botão Mover da tela de combate no navegador: escolher a zona move de
verdade, gasta o movimento e, com a Disparada, a Ação.

O clique na zona chamava `_act`, que só existe em window.Combat; dentro do
módulo a função é `act`. O ReferenceError sumia no console e o personagem
ficava parado, sem aviso nenhum.

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
            pg.wait_for_function(
                "() => /O que fará Stelar/.test(document.getElementById('cbt-action-title').textContent)",
                timeout=8000)
            return pg, erros

        yield abrir, cap
        nav.close()


def _zona_de(pg, nome):
    return pg.evaluate(
        """(nome) => {
             const z = [...document.querySelectorAll('#cbt-zonas .cbt-zona')]
               .find(el => el.querySelector('.cbt-zona-pins').textContent.includes(nome));
             return z ? z.querySelector('.cbt-zona-nome').textContent : null;
           }""", nome)


def _mover(pg, zona):
    pg.click("#cbt-buttons button:has-text('Mover')")
    pg.wait_for_selector("#cbt-targets:not(.hidden) .cbt-btn", timeout=3000)
    pg.locator("#cbt-targets .cbt-btn", has_text=zona).first.click()


def test_mover_para_a_zona_vizinha(abrir_jogo):
    abrir, cap = abrir_jogo
    pg, erros = abrir(copy.deepcopy(cap.COMBATE_ZONAS))
    assert _zona_de(pg, "Stelar") == "Pátio"

    _mover(pg, "Portão")
    pg.wait_for_function(
        "() => [...document.querySelectorAll('#cbt-zonas .cbt-zona')].some(z =>"
        " z.querySelector('.cbt-zona-nome').textContent === 'Portão'"
        " && z.textContent.includes('Stelar'))", timeout=5000)
    # O movimento foi gasto; a Ação continua livre.
    pg.wait_for_selector("#cbt-buttons button:has-text('Mover')[disabled]", timeout=3000)
    assert pg.is_enabled("#cbt-buttons button:has-text('Atacar')")
    assert "move-se de Pátio para Portão" in pg.inner_text("#cbt-log")
    assert not erros, erros[:3]


def test_zona_com_apostrofo(abrir_jogo):
    abrir, cap = abrir_jogo
    estado = copy.deepcopy(cap.COMBATE_ZONAS)
    cs = estado["combat_state"]
    cs["zonas"] = ["Portão", "Covil d'Ogro", "Sacada"]
    cs["zona_desc"] = {"Portão": "", "Covil d'Ogro": "", "Sacada": ""}
    cs["posicoes"] = {"stelar": "Portão", "helena": "Portão",
                      "natasha": "Sacada", "victoria": "Sacada"}
    pg, erros = abrir(estado)

    _mover(pg, "Covil d'Ogro")
    pg.wait_for_function(
        "() => [...document.querySelectorAll('#cbt-zonas .cbt-zona')].some(z =>"
        " z.querySelector('.cbt-zona-nome').textContent === \"Covil d'Ogro\""
        " && z.textContent.includes('Stelar'))", timeout=5000)
    assert not erros, erros[:3]


def test_disparada_cruza_duas_zonas_e_gasta_a_acao(abrir_jogo):
    abrir, cap = abrir_jogo
    estado = copy.deepcopy(cap.COMBATE_ZONAS)
    estado["combat_state"]["posicoes"] = {"stelar": "Portão", "helena": "Portão",
                                          "natasha": "Pátio", "victoria": "Sacada"}
    estado["combat_state"]["current_turn_index"] = 0
    # Ninguém inimigo trancando o Portão: sem ataque de oportunidade na saída.
    pg, erros = abrir(estado)

    pg.click("#cbt-buttons button:has-text('Mover')")
    pg.wait_for_selector("#cbt-targets:not(.hidden) .cbt-btn", timeout=3000)
    botao = pg.locator("#cbt-targets .cbt-btn", has_text="Sacada").first
    assert "Disparada" in botao.text_content()
    botao.click()
    pg.wait_for_function(
        "() => [...document.querySelectorAll('#cbt-zonas .cbt-zona')].some(z =>"
        " z.querySelector('.cbt-zona-nome').textContent === 'Sacada'"
        " && z.textContent.includes('Stelar'))", timeout=5000)
    pg.wait_for_selector("#cbt-buttons button:has-text('Atacar')[disabled]", timeout=3000)
    assert not erros, erros[:3]
