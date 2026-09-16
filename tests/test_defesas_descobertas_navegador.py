"""
test_defesas_descobertas_navegador.py

O card do inimigo, na tela, mostra só a defesa que o grupo já descobriu.

O motor decide (ver test_defesas_descobertas.py); aqui se confere a outra
ponta: com a defesa ainda secreta o card não tem selo nenhum, e com ela
descoberta o selo aparece com o marcador certo.

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
            pg.wait_for_selector("#combat-overlay:not(.hidden) #cbt-enemies .cbt-card", timeout=8000)
            return pg, erros

        yield abrir, cap
        nav.close()


def _estado_com_defesas(cap, descobertas=None):
    """Victoria, a inimiga do cenário, com defesas na ficha."""
    estado = copy.deepcopy(cap.COMBATE_ZONAS)
    ficha = estado["characters"]["victoria"].setdefault("sheet", {})
    ficha.update({"resistencias": ["slashing"], "vulnerabilidades": ["fire"],
                  "imunidades": ["poison"]})
    if descobertas is not None:
        ficha["descobertas"] = descobertas
    return estado


def _selos(pg, nome):
    return pg.evaluate(
        """(nome) => {
             const card = [...document.querySelectorAll('.cbt-card')]
               .find(c => (c.querySelector('.cbt-name') || {}).textContent === nome);
             if (!card) return null;
             return [...card.querySelectorAll('.cbt-def')].map(s => s.textContent.trim());
           }""", nome)


def test_defesa_secreta_nao_aparece_no_card(abrir_jogo):
    abrir, cap = abrir_jogo
    pg, erros = abrir(_estado_com_defesas(cap))
    assert _selos(pg, "Victoria") == []
    assert not erros, erros[:3]


def test_defesa_descoberta_aparece_com_o_marcador(abrir_jogo):
    abrir, cap = abrir_jogo
    pg, erros = abrir(_estado_com_defesas(cap, {"vulnerabilidades": ["fire"]}))
    selos = _selos(pg, "Victoria")
    assert selos == ["×2 fogo"], selos
    assert not erros, erros[:3]


def test_o_resto_continua_escondido(abrir_jogo):
    """Descobrir a vulnerabilidade não entrega a resistência nem a imunidade."""
    abrir, cap = abrir_jogo
    pg, erros = abrir(_estado_com_defesas(cap, {"vulnerabilidades": ["fire"]}))
    selos = " ".join(_selos(pg, "Victoria"))
    assert "corte" not in selos and "veneno" not in selos
    assert not erros, erros[:3]
