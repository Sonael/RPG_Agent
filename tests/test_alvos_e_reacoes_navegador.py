"""
test_alvos_e_reacoes_navegador.py

A tela de combate nas quatro mudanças do lote de limitações:
  • magia de vários alvos: o seletor marca até N (Imobilizar Pessoa no 3º
    círculo: 2; Coluna de Chamas sem zonas: 2) e confirma;
  • reação em "pergunta": o turno do inimigo para, a tela mostra a pergunta
    com Usar / Não usar, e não roda o inimigo por cima;
  • a vez da invocação do grupo é do jogador, com o botão "Motor joga".

Depende do Playwright, que não está em requirements-dev.txt. Sem ele o arquivo
é pulado:

    pip install playwright && playwright install chromium
"""
import copy
import json
import random
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
def tela(app_no_ar):
    from playwright.sync_api import sync_playwright
    import requests

    url, nome, cap = app_no_ar
    with sync_playwright() as pw:
        nav = pw.chromium.launch()

        def abrir(estado, titulo):
            requests.post(f"{url}/__estado", json=estado, timeout=10)
            ctx = nav.new_context(viewport={"width": 1440, "height": 980})
            ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO))
            pg = ctx.new_page()
            erros = []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.goto(f"{url}/game.html", wait_until="networkidle")
            pg.wait_for_selector("#combat-overlay:not(.hidden) .cbt-card", timeout=8000)
            pg.wait_for_function(
                "(t) => document.getElementById('cbt-action-title').textContent.includes(t)",
                arg=titulo, timeout=8000)
            return pg, erros

        yield abrir, cap
        nav.close()


def _sem_zonas(cap):
    estado = copy.deepcopy(cap.COMBATE_MAGIAS)
    estado["combat_state"]["zonas"] = []
    estado["combat_state"]["posicoes"] = {}
    return estado


def _motor(pg):
    return pg.evaluate("""async () =>
      await (await authFetch((window.API || '') + '/api/combat/state')).json()""")


def _vida(pg, nome):
    return int(pg.evaluate(
        """(n) => { const c = [...document.querySelectorAll('.cbt-card')].find(e => e.dataset.nome === n);
                    return c.querySelector('.cbt-bar-num').textContent.trim(); }""", nome).split("/")[0])


def _escolher(pg, nome):
    pg.click("#cbt-buttons button:has-text('Habilidade')")
    pg.locator("#cbt-targets .cbt-hab", has=pg.locator(".cbt-hab-nome", has_text=nome)).first \
        .locator(".cbt-hab-usar").click()


# ---------------------------------------------------------------------------
# Vários alvos
# ---------------------------------------------------------------------------

def test_area_sem_zonas_marca_ate_o_tamanho_e_confirma(tela):
    abrir, cap = tela
    pg, erros = abrir(_sem_zonas(cap), "O que fará Helena")
    antes = {n: _vida(pg, n) for n in ("Cultista", "Acólito", "Lobo Sombrio")}
    _escolher(pg, "Coluna de Chamas")
    pg.wait_for_selector("#cbt-targets .cbt-tgt-title:has-text('até 2 alvos')")
    confirmar = pg.locator("#cbt-targets button:has-text('Confirmar')")
    assert confirmar.is_disabled()
    pg.click("#cbt-targets button.cbt-btn:has-text('Cultista')")
    pg.click("#cbt-targets button.cbt-btn:has-text('Acólito')")
    # O terceiro não cabe: a área de 3 m pega duas criaturas.
    pg.click("#cbt-targets button.cbt-btn:has-text('Lobo Sombrio')")
    assert "2/2" in confirmar.inner_text()
    assert pg.locator("#cbt-targets .cbt-selecionado").count() == 2
    confirmar.click()
    pg.wait_for_function(
        "(v) => { const c = [...document.querySelectorAll('.cbt-card')].find(e => e.dataset.nome === 'Cultista');"
        " return parseInt(c.querySelector('.cbt-bar-num').textContent) < v; }",
        arg=antes["Cultista"], timeout=8000)
    assert _vida(pg, "Acólito") < antes["Acólito"] or _vida(pg, "Acólito") == 0
    assert _vida(pg, "Lobo Sombrio") == antes["Lobo Sombrio"]
    assert not erros, erros[:3]


def test_circulo_maior_abre_mais_alvos(tela):
    abrir, cap = tela
    estado = _sem_zonas(cap)
    estado["characters"]["helena"]["habilidades"].append(
        {"nome": "Hold Person", "dado": "", "custo_mana": 3, "descricao": "", "nivel_magia": 2})
    pg, erros = abrir(estado, "O que fará Helena")
    _escolher(pg, "Imobilizar Pessoa")
    pg.wait_for_selector("#cbt-targets .cbt-circulo")
    # No 2º círculo, um alvo só: nada de "Confirmar".
    assert pg.locator("#cbt-targets button:has-text('Confirmar')").count() == 0
    pg.click("#cbt-targets .cbt-circulo[data-modo='c3']")
    pg.wait_for_selector("#cbt-targets .cbt-tgt-title:has-text('até 2 alvos')")
    pg.click("#cbt-targets button.cbt-btn:has-text('Cultista')")
    pg.click("#cbt-targets button.cbt-btn:has-text('Acólito')")
    pg.click("#cbt-targets button:has-text('Confirmar')")
    pg.wait_for_function("() => !document.querySelector('#cbt-targets .cbt-circulo')", timeout=8000)
    log = " | ".join(e.get("msg", "") for e in _motor(pg)["log"])
    assert "Hold Person em Cultista, Acólito" in log, log[-400:]
    assert not erros, erros[:3]


# ---------------------------------------------------------------------------
# Reação que pergunta
# ---------------------------------------------------------------------------

def _com_pergunta(cap):
    estado = copy.deepcopy(cap.COMBATE_MAGIAS)
    estado["combat_state"]["current_turn_index"] = 0          # vez de Victoria
    estado["characters"]["stelar"]["habilidades"] = [
        {"nome": "Shield", "custo_mana": 2, "dado": "", "descricao": "", "nivel_magia": 1}]
    estado["characters"]["stelar"]["sheet"].update(
        {"reacoes_perguntar": ["escudo arcano"], "mana_atual": 10, "mana_max": 10})
    sorteio = random.Random(7).getstate()
    estado["combat_state"]["reacao_pendente"] = {
        "npc": "Victoria", "quem": "Stelar", "chave": "escudo arcano", "nome": "Escudo Arcano",
        "texto": "Victoria acerta Stelar (15 contra CA 14). Conjurar Escudo Arcano (2 mana)?",
        "respostas": [], "forcar": False, "rng": [sorteio[0], list(sorteio[1]), sorteio[2]]}
    return estado


def test_a_pergunta_aparece_e_o_inimigo_espera(tela):
    abrir, cap = tela
    pg, erros = abrir(_com_pergunta(cap), "Reação de Stelar")
    assert "Conjurar Escudo Arcano" in pg.inner_text("#cbt-prompt")
    assert pg.locator("#cbt-buttons button:has-text('Usar Escudo Arcano')").is_visible()
    assert pg.locator("#cbt-buttons button:has-text('Não usar')").is_visible()
    pg.wait_for_timeout(1500)                # a tela não roda o inimigo por cima
    assert _motor(pg)["reacao_pendente"]["quem"] == "Stelar"
    assert not erros, erros[:3]


def test_responder_continua_o_turno(tela):
    abrir, cap = tela
    pg, erros = abrir(_com_pergunta(cap), "Reação de Stelar")
    pg.click("#cbt-buttons button:has-text('Não usar')")
    pg.wait_for_function(
        "() => !document.getElementById('cbt-action-title').textContent.includes('Reação de')", timeout=8000)
    estado = _motor(pg)
    assert estado["reacao_pendente"] is None
    assert any("Victoria" in (e.get("msg") or "") for e in estado["log"][-6:])
    assert not erros, erros[:3]


def test_pergunta_na_jogada_do_jogador(tela):
    """O ataque de Helena parou no Oportunista de Stelar; Não usar refaz o ataque sem ele."""
    abrir, cap = tela
    estado = copy.deepcopy(cap.COMBATE_MAGIAS)
    estado["characters"]["stelar"]["habilidades"] = [
        {"nome": "Oportunista", "custo_mana": 0, "dado": "", "descricao": ""}]
    estado["characters"]["stelar"]["sheet"]["reacoes_perguntar"] = ["oportunista"]
    sorteio = random.Random(3).getstate()
    estado["combat_state"]["reacao_pendente"] = {
        "npc": "Helena", "quem": "Stelar", "chave": "oportunista", "nome": "Oportunista",
        "texto": "Helena acertou Victoria. Stelar ataca Victoria (Oportunista)?", "respostas": [],
        "chamada": {"fn": "combat_action", "kw": {"action": "attack", "actor": "Helena",
                                                    "target": "Victoria", "weapon": "", "ability": "",
                                                    "item": ""}},
        "rng": [sorteio[0], list(sorteio[1]), sorteio[2]]}
    pg, erros = abrir(estado, "Reação de Stelar")
    assert "Oportunista" in pg.inner_text("#cbt-prompt")
    pg.click("#cbt-buttons button:has-text('Não usar')")
    pg.wait_for_function(
        "() => !document.getElementById('cbt-action-title').textContent.includes('Reação de')", timeout=8000)
    assert _motor(pg)["reacao_pendente"] is None
    assert not erros, erros[:3]


# ---------------------------------------------------------------------------
# A invocação do grupo
# ---------------------------------------------------------------------------

def _com_lobo(cap):
    from rpg import criaturas
    estado = copy.deepcopy(cap.COMBATE_MAGIAS)
    estado["characters"]["lobo de helena"] = {
        "name": "Lobo de Helena", "status": "vivo", "lado": "aliado", "party_member": False,
        "description": "", "traits": "", "notes": "", "habilidades": [], "inventario": [],
        "sheet": criaturas.montar_sheet("lobo"),
        "invocacao": {"por": "helena", "magia": "Conjure Animals", "concentracao": False,
                      "persistente": False, "ate_hora": None, "acompanha": False, "hostil_ao_perder": False},
    }
    ordem = estado["combat_state"]["initiative_order"]
    ordem.insert(2, "Lobo de Helena")
    estado["combat_state"]["current_turn_index"] = 2
    estado["combat_state"]["posicoes"]["lobo de helena"] = "Portão"
    return estado


def test_a_vez_do_lobo_tem_a_barra_do_jogador(tela):
    abrir, cap = tela
    pg, erros = abrir(_com_lobo(cap), "O que fará Lobo de Helena")
    assert pg.is_enabled("#cbt-buttons button:has-text('Atacar')")
    assert pg.locator("#cbt-buttons button:has-text('Motor joga')").is_visible()
    pg.click("#cbt-buttons button:has-text('Atacar')")
    pg.wait_for_selector("#cbt-targets button:has-text('mordida')", timeout=5000)
    assert not erros, erros[:3]


def test_motor_joga_passa_a_vez(tela):
    abrir, cap = tela
    pg, erros = abrir(_com_lobo(cap), "O que fará Lobo de Helena")
    pg.click("#cbt-buttons button:has-text('Motor joga')")
    pg.wait_for_function(
        "() => !document.getElementById('cbt-action-title').textContent.includes('Lobo de Helena')",
        timeout=8000)
    assert any("Lobo de Helena" in (e.get("actor") or e.get("msg") or "") for e in _motor(pg)["log"])
    assert not erros, erros[:3]


# ---------------------------------------------------------------------------
# Ninguém é obrigado a matar
# ---------------------------------------------------------------------------

def test_golpe_nao_letal_liga_na_tela(tela):
    abrir, cap = tela
    pg, erros = abrir(copy.deepcopy(cap.COMBATE_MAGIAS), "O que fará Helena")
    assert pg.locator("#cbt-actionbar #cbt-buttons .cbt-nao-letal").count() == 0   # a barra não cresce
    pg.click("#cbt-buttons button:has-text('Atacar')")
    chip = pg.locator("#cbt-targets .cbt-nao-letal")
    assert "desligado" in chip.inner_text()
    chip.click()
    pg.wait_for_selector("#cbt-targets .cbt-nao-letal.ligada", timeout=5000)
    helena = next(c for c in _motor(pg)["combatants"] if c["name"] == "Helena")
    assert helena["nao_letal"] is True
    assert pg.is_enabled("#cbt-buttons button:has-text('Atacar')"), "ligar gastou a Ação"
    assert not erros, erros[:3]


def test_pedir_rendicao_pelo_menu(tela):
    abrir, cap = tela
    pg, erros = abrir(copy.deepcopy(cap.COMBATE_MAGIAS), "O que fará Helena")
    pg.click("#cbt-buttons button:has-text('Manobras')")
    pg.click("#cbt-targets button:has-text('Pedir rendição (Intimidação)')")
    pg.click("#cbt-targets button.cbt-btn:has-text('Acólito')")
    pg.wait_for_function("() => !document.querySelector('#cbt-targets:not(.hidden) .cbt-tgt-title')", timeout=8000)
    log = " | ".join(e.get("msg", "") for e in _motor(pg)["log"])
    assert "Helena pede a rendição de Acólito" in log, log[-300:]
    assert not erros, erros[:3]


def test_inimigo_enfeiticado_que_sobra_vai_para_poupados(tela):
    abrir, cap = tela
    estado = copy.deepcopy(cap.COMBATE_MAGIAS)
    for nome in ("victoria", "lobo sombrio", "acólito"):
        estado["characters"].setdefault(nome, {}).setdefault("sheet", {})["vida_atual"] = 0
        estado["characters"][nome]["status"] = "morto"
    estado["encantos"] = [{"alvo": "cultista", "alvo_nome": "Cultista", "por": "helena",
                          "por_nome": "Helena", "magia": "Enfeitiçar Pessoa",
                          "magia_srd": "Charm Person", "magia_ficha": "Charm Person",
                          "tipo": "enfeitiçado", "percebe": True, "atitude_antes": 0, "ate_hora": 999999}]
    pg, erros = abrir(estado, "O que fará Helena")
    pg.click("#cbt-buttons button:has-text('Encerrar Turno')")
    pg.wait_for_selector("#cbt-end-overlay:not(.hidden) .cbt-end-col-poupados", timeout=8000)
    texto = pg.inner_text("#cbt-end-overlay .cbt-end-col-poupados")
    assert "Cultista" in texto and "enfeitiçado" in texto, texto
    assert "Cultista" not in pg.inner_text("#cbt-end-overlay .cbt-end-col-foe")
    assert not erros, erros[:3]


# ---------------------------------------------------------------------------
# Cobertura
# ---------------------------------------------------------------------------

def test_buscar_cobertura_aparece_no_cartao(tela):
    abrir, cap = tela
    pg, erros = abrir(copy.deepcopy(cap.COMBATE_MAGIAS), "O que fará Helena")
    pg.click("#cbt-buttons button:has-text('Manobras')")
    assert pg.locator("#cbt-targets button:has-text('Ataque com a outra mão')").count() == 0
    pg.click("#cbt-targets button:has-text('Buscar cobertura')")
    pg.wait_for_function(
        "() => { const c = [...document.querySelectorAll('.cbt-card')].find(e => e.dataset.nome === 'Helena');"
        " return c && /cobertura/i.test(c.textContent); }", timeout=8000)
    helena = next(c for c in _motor(pg)["combatants"] if c["name"] == "Helena")
    assert helena["cobertura"] == "meia"
    assert not erros, erros[:3]


# ---------------------------------------------------------------------------
# Preparar magia
# ---------------------------------------------------------------------------

def test_preparar_magia_pelo_menu(tela):
    abrir, cap = tela
    pg, erros = abrir(copy.deepcopy(cap.COMBATE_MAGIAS), "O que fará Helena")
    pg.click("#cbt-buttons button:has-text('Manobras')")
    assert pg.locator("#cbt-targets button:has-text('Montar')").count() == 0      # sem montaria
    pg.click("#cbt-targets button:has-text('Preparar magia')")
    pg.click("#cbt-targets button.cbt-btn:has-text('Raio Guia')")
    pg.click("#cbt-targets button.cbt-btn:has-text('Cultista')")
    pg.wait_for_function("() => !document.querySelector('#cbt-targets:not(.hidden) .cbt-tgt-title')", timeout=8000)
    log = " | ".join(e.get("msg", "") for e in _motor(pg)["log"])
    assert "prepara Raio Guia" in log, log[-300:]
    assert not erros, erros[:3]


# ---------------------------------------------------------------------------
# Dardos no mesmo alvo; encerrar a luta
# ---------------------------------------------------------------------------

def test_misseis_magicos_dois_dardos_no_mesmo_alvo(tela):
    abrir, cap = tela
    estado = copy.deepcopy(cap.COMBATE_MAGIAS)
    estado["characters"]["helena"]["habilidades"].append(
        {"nome": "Magic Missile", "dado": "", "custo_mana": 2, "descricao": "", "nivel_magia": 1})
    pg, erros = abrir(estado, "O que fará Helena")
    _escolher(pg, "Mísseis Mágicos")
    pg.wait_for_selector("#cbt-targets .cbt-tgt-title:has-text('até 3 alvos')")
    pg.click("#cbt-targets button.cbt-btn:has-text('Cultista')")
    pg.click("#cbt-targets button.cbt-btn:has-text('Cultista')")
    assert "×2" in pg.inner_text("#cbt-targets button.cbt-btn:has-text('Cultista')")
    pg.click("#cbt-targets button:has-text('Desfazer o último')")
    pg.click("#cbt-targets button.cbt-btn:has-text('Cultista')")
    pg.click("#cbt-targets button.cbt-btn:has-text('Acólito')")
    assert "3/3 dardos" in pg.inner_text("#cbt-targets button:has-text('Confirmar')")
    pg.click("#cbt-targets button:has-text('Confirmar')")
    pg.wait_for_function("() => !document.querySelector('#cbt-targets:not(.hidden) .cbt-tgt-title')", timeout=8000)
    log = " | ".join(e.get("msg", "") for e in _motor(pg)["log"])
    assert "Magic Missile em Cultista, Cultista, Acólito" in log, log[-300:]
    assert not erros, erros[:3]


def test_encerrar_a_luta_pelo_menu(tela):
    abrir, cap = tela
    pg, erros = abrir(copy.deepcopy(cap.COMBATE_MAGIAS), "O que fará Helena")
    pg.click("#cbt-buttons button:has-text('Manobras')")
    pg.click("#cbt-targets button:has-text('Encerrar a luta')")
    assert "o Mestre decide" in pg.inner_text("#cbt-targets")
    pg.click("#cbt-targets button.cbt-perigo:has-text('Encerrar')")
    pg.wait_for_selector("#cbt-end-overlay:not(.hidden)", timeout=8000)
    assert "Luta encerrada" in pg.inner_text("#cbt-end-overlay .cbt-result-title")
    assert not erros, erros[:3]
