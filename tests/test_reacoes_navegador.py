"""
test_reacoes_navegador.py

As reações (Escudo Arcano, Indomável...) o motor usa sozinho no turno do
inimigo. A tela de combate mostra quais o personagem tem e deixa desligar:
aqui se prova que a linha aparece, que o toque desliga no motor e que o botão
mostra o estado novo.

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


def _estado(cap):
    estado = copy.deepcopy(cap.COMBATE_ZONAS)
    estado["characters"]["stelar"]["habilidades"] = [
        {"nome": "Shield", "custo_mana": 2, "dado": "", "descricao": "", "nivel_magia": 1},
        {"nome": "Indomável", "custo_mana": 0, "dado": "", "descricao": ""},
    ]
    return estado


@pytest.fixture
def pagina(app_no_ar):
    from playwright.sync_api import sync_playwright
    import requests

    url, nome, cap = app_no_ar
    requests.post(f"{url}/__estado", json=_estado(cap), timeout=10)
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        ctx = nav.new_context(viewport={"width": 1440, "height": 980})
        ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO))
        pg = ctx.new_page()
        erros = []
        pg.on("pageerror", lambda e: erros.append(str(e)))
        pg.goto(f"{url}/game.html", wait_until="networkidle")
        pg.wait_for_selector("#combat-overlay:not(.hidden)", timeout=8000)
        pg.wait_for_selector(".cbt-reacoes", timeout=8000)
        yield pg, erros
        nav.close()


def _estado_no_motor(pg):
    return pg.evaluate("""async () => {
      const s = await (await authFetch((window.API || '') + '/api/combat/state')).json();
      const c = s.combatants.find(x => x.name === 'Stelar');
      return Object.fromEntries((c.reacoes || []).map(r => [r.chave, r.ligada]));
    }""")


def test_linha_de_reacoes_aparece_ligada(pagina):
    pg, erros = pagina
    texto = pg.inner_text(".cbt-reacoes")
    assert "Escudo Arcano" in texto and "Indomável" in texto
    assert pg.locator(".cbt-reacao-chip.ligada").count() == 2
    assert not erros, erros[:3]


def test_tocar_desliga_no_motor_e_na_tela(pagina):
    pg, _ = pagina
    pg.click(".cbt-reacao-chip:has-text('Escudo Arcano')")
    pg.wait_for_selector(".cbt-reacao-chip.desligada:has-text('Escudo Arcano')", timeout=5000)
    assert _estado_no_motor(pg)["escudo arcano"] is False
    pg.click(".cbt-reacao-chip:has-text('Escudo Arcano')")
    pg.wait_for_selector(".cbt-reacao-chip.ligada:has-text('Escudo Arcano')", timeout=5000)
    assert _estado_no_motor(pg)["escudo arcano"] is True
