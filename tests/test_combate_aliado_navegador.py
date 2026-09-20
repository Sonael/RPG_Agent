"""
test_combate_aliado_navegador.py

O aliado na tela tática: o NPC que luta com o grupo sem ser do grupo aparece
na SUA coluna, com o selo dizendo que quem joga por ele é o motor — e, na vez
dele, ataca o inimigo.

Antes a tela só conhecia dois lados (is_party): o mercador que o grupo
escoltava aparecia entre os inimigos, em vermelho, e o motor o mandava atacar
o jogador.

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


def _com_o_pip(cap, vez=0):
    """O combate da captura, com Pip escoltado entrando na luta como aliado."""
    estado = copy.deepcopy(cap.COMBATE_ATIVO)
    estado["characters"]["pip"] = {
        "name": "Pip", "description": "Mestre comerciante da caravana.",
        "status": "vivo", "lado": "aliado", "traits": "", "notes": "",
        "inventario": [], "habilidades": [],
        "sheet": {"classe": "npc", "raca": "gnomo", "nivel": 2, "xp": 0, "xp_proximo": 300,
                  "forca": 8, "destreza": 14, "constituicao": 10, "inteligencia": 12,
                  "sabedoria": 10, "carisma": 14, "vida_atual": 12, "vida_max": 12,
                  "mana_atual": 0, "mana_max": 0, "ca": 12, "proficiencia": 2,
                  "hit_die": 8, "ouro": 0, "prata": 0, "cobre": 0,
                  "equipamentos": {"armadura": None, "escudo": None,
                                   "arma_principal": "adaga", "amuleto": None},
                  "condicoes": [], "death_saves_sucessos": 0, "death_saves_falhas": 0,
                  "vida_temp": 0, "concentracao": None,
                  "resistencias": [], "imunidades": [], "vulnerabilidades": []},
    }
    cs = estado["combat_state"]
    cs["initiative_order"] = ["Stelar", "Pip", "Victoria", "Helena", "Natasha"]
    cs["current_turn_index"] = vez
    return estado


def _coluna(pg, nome):
    return pg.evaluate(
        """(nome) => {
             const c = [...document.querySelectorAll('.cbt-card')]
               .find(el => el.dataset.nome === nome);
             if (!c) return null;
             return {coluna: c.parentElement.id, classes: c.className,
                     selo: !!c.querySelector('.cbt-selo-aliado')};
           }""", nome)


def test_o_aliado_fica_na_coluna_do_grupo_com_selo(abrir_jogo):
    abrir, cap = abrir_jogo
    pg, erros = abrir(_com_o_pip(cap))
    pip = _coluna(pg, "Pip")
    assert pip["coluna"] == "cbt-party", pip
    assert "cbt-aliado" in pip["classes"] and "cbt-npc-aliado" in pip["classes"], pip
    assert pip["selo"] is True, pip
    # O inimigo continua do outro lado, sem selo.
    victoria = _coluna(pg, "Victoria")
    assert victoria["coluna"] == "cbt-enemies" and victoria["selo"] is False, victoria
    # E o jogador continua jogando só pelo grupo.
    assert "O que fará Stelar" in pg.inner_text("#cbt-action-title")
    assert not erros, erros[:3]


def test_na_vez_dele_o_aliado_ataca_o_inimigo(abrir_jogo):
    abrir, cap = abrir_jogo
    pg, erros = abrir(_com_o_pip(cap, vez=1))
    # O motor joga por ele (turno automático de NPC) e o alvo é o inimigo.
    pg.wait_for_function(
        "() => /Pip → Victoria/.test(document.getElementById('cbt-log').textContent)",
        timeout=10000)
    texto = pg.inner_text("#cbt-log")
    for do_grupo in ("Stelar", "Helena", "Natasha"):
        assert f"Pip → {do_grupo}" not in texto, texto
    assert not erros, erros[:3]
