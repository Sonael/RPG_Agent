"""
test_relacao_navegador.py

O que mudou na tela depois de uma jogatina inteira anotando o que incomodava:

  • "eu não consigo ver a mana dos meu personagens facilmente" — a barra
    lateral mostrava só a vida;
  • "seria bom ver na ficha dos personagens do meu grupo a relação dele
    comigo, só dá pra ver no mundo";
  • "seria bom se cada personagem tivesse uma relação separada com cada um e
    desse pra editar isso";
  • "quando os inimigos morrem eu quero deletar eles, mas para isso eu
    preciso ir em editar a ficha".

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
    estado = copy.deepcopy(cap.MUNDO_ONDA4)
    cap._mesclar(estado, copy.deepcopy(cap.GRUPO))
    cap._mesclar(estado, {
        "current_location": "Palácio Real de Luminas",
        "chapter": 2, "dnd_mode": True, "campaign_type": "dnd",
        "combat_state": {"is_active": False, "initiative_order": []},
        "characters": {
            # Helena já sente alguma coisa por Stelar: é o que o fechamento do
            # turno escreve quando a cena muda a relação entre duas pessoas.
            "helena": {"atitude": 20, "lealdade": 90,
                       "entre": {"stelar": {"nome": "Stelar", "valor": -25,
                                            "motivo": "o controle velado",
                                            "historico": [{"delta": -25,
                                                           "motivo": "o controle velado",
                                                           "cap": 2}]}}},
            # Um inimigo morto, do tipo que fica na lista depois do combate.
            "cultista do minério 1": {
                "name": "Cultista do Minério 1", "status": "morto",
                "description": "Medium humanoid — CR 1/8.", "traits": "",
                "notes": "", "local": "Palácio Real de Luminas",
                "sheet": None, "inventario": [], "habilidades": []},
        },
    })
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
        pg.wait_for_selector("#sb-herois .sb-heroi-vida", state="attached", timeout=8000)
        pg.wait_for_timeout(400)
        yield pg, erros, url
        nav.close()


def _pelo_indice(pg, nome):
    """Abre pelo índice de personagens, como o jogador faz."""
    pg.click("#sb-atalho-personagens")
    cartao = f"#elenco-overlay .elc-cartao[data-nome='{nome}']"
    pg.wait_for_selector(cartao, state="visible", timeout=5000)
    pg.click(cartao)


def _abrir_ficha_de_heroi(pg, nome):
    """Quem é do grupo e tem ficha abre na ficha do herói (herois.js)."""
    _pelo_indice(pg, nome)
    pg.wait_for_selector("#heroi-overlay:not(.hidden)", timeout=5000)
    pg.wait_for_function(
        f"() => document.getElementById('hro-nome').textContent === {nome!r}", timeout=5000)
    pg.wait_for_timeout(300)          # a relação vem numa segunda chamada


def _abrir_ficha_de_personagem(pg, nome):
    pg.wait_for_selector("#pessoa-overlay:not(.hidden)", timeout=5000)
    pg.wait_for_function(
        f"() => document.getElementById('psn-nome').textContent === {nome!r}"
        " && !document.getElementById('psn-msg').textContent", timeout=5000)


def _abrir_relacao_do_heroi(pg, nome):
    """Da ficha do herói para a de relação, que é onde se ajusta."""
    _abrir_ficha_de_heroi(pg, nome)
    pg.click("#hro-relacao .lcl-btn-sec")
    _abrir_ficha_de_personagem(pg, nome)


# ---------------------------------------------------------------------------
# Mana na barra lateral
# ---------------------------------------------------------------------------

def test_quem_conjura_mostra_a_mana_na_barra(pagina):
    pg, erros, _ = pagina
    dados = pg.evaluate("""() => Array.from(document.querySelectorAll('#sb-herois .sb-heroi'))
        .map(h => ({
          nome: h.getAttribute('data-nome'),
          temMana: !!h.querySelector('.sb-heroi-mana'),
          numero: (h.querySelector('.sb-heroi-num-mana') || {}).textContent || '',
        }))""")
    com_mana = [d for d in dados if d["temMana"]]
    assert com_mana, "nenhum herói mostrou mana na barra"
    assert all("/" in d["numero"] for d in com_mana)
    assert not erros, erros[:3]


def test_a_vida_continua_na_barra(pagina):
    pg, _, _ = pagina
    assert pg.evaluate("() => document.querySelectorAll('#sb-herois .sb-heroi-vida').length") > 0


def test_mana_e_vida_cabem_na_largura_da_barra(pagina):
    """Duas barras empilhadas não podem empurrar a linha para fora."""
    pg, _, _ = pagina
    estouros = pg.evaluate("""() => {
      const barra = document.querySelector('#sidebar .sidebar-content').getBoundingClientRect();
      return Array.from(document.querySelectorAll('#sb-herois .sb-heroi'))
        .filter(h => h.getBoundingClientRect().right > barra.right + 1)
        .map(h => h.getAttribute('data-nome'));
    }""")
    assert estouros == [], estouros


# ---------------------------------------------------------------------------
# A relação na ficha de quem é do grupo
# ---------------------------------------------------------------------------

def test_ficha_do_heroi_mostra_a_relacao(pagina):
    """O índice manda quem é do grupo para a ficha do herói: é lá que o
    jogador procurava a relação e não achava."""
    pg, erros, _ = pagina
    _abrir_ficha_de_heroi(pg, "Helena")
    texto = pg.inner_text("#hro-relacao")
    assert "Com o grupo" in texto and "+20" in texto
    assert "Lealdade" in texto and "90" in texto
    assert "Com Stelar" in texto and "-25" in texto
    assert not erros, erros[:3]


def test_ficha_de_relacao_mostra_atitude_e_lealdade(pagina):
    pg, erros, _ = pagina
    _abrir_relacao_do_heroi(pg, "Helena")
    assert not pg.is_hidden("#psn-relacao-bloco")
    assert "+20" in pg.inner_text("#psn-relacao")
    assert "Lealdade" in pg.inner_text("#psn-laco")
    assert "90" in pg.inner_text("#psn-laco")
    assert not erros, erros[:3]


def test_ficha_mostra_a_relacao_com_cada_um(pagina):
    pg, _, _ = pagina
    _abrir_relacao_do_heroi(pg, "Helena")
    texto = pg.inner_text("#psn-entre")
    assert "Stelar" in texto
    assert "-25" in texto
    assert "o controle velado" in texto


def test_ajustar_a_relacao_salva_e_redesenha(pagina):
    pg, erros, _ = pagina
    _abrir_relacao_do_heroi(pg, "Helena")
    pg.click("#psn-entre .psn-entre-item[data-com='Stelar'] .psn-ajustar")
    pg.fill("#psn-entre .psn-ajuste-valor", "40")
    pg.fill("#psn-entre .psn-ajuste-motivo", "fizeram as pazes na estrada")
    pg.click("#psn-entre .psn-ajuste-botoes .lcl-btn-sec")
    pg.wait_for_function(
        "() => document.querySelector('#psn-entre').textContent.includes('+40')",
        timeout=5000)
    assert "fizeram as pazes" in pg.inner_text("#psn-entre")
    assert not erros, erros[:3]


def test_ajustar_a_atitude_pela_ficha(pagina):
    pg, _, _ = pagina
    _abrir_relacao_do_heroi(pg, "Helena")
    pg.click("#psn-relacao .psn-ajustar")
    pg.fill("#psn-relacao .psn-ajuste-valor", "45")
    pg.fill("#psn-relacao .psn-ajuste-motivo", "defendeu o grupo na ponte")
    pg.click("#psn-relacao .psn-ajuste-botoes .lcl-btn-sec")
    pg.wait_for_function(
        "() => document.querySelector('#psn-relacao').textContent.includes('+45')",
        timeout=5000)
    assert "defendeu o grupo na ponte" in pg.inner_text("#psn-relacao")


# ---------------------------------------------------------------------------
# Apagar quem o combate deixou para trás
# ---------------------------------------------------------------------------

def test_inimigo_morto_tem_botao_de_apagar(pagina):
    pg, _, _ = pagina
    _pelo_indice(pg, "Cultista do Minério 1")
    _abrir_ficha_de_personagem(pg, "Cultista do Minério 1")
    assert pg.is_visible("#psn-apagar")


def test_quem_e_do_grupo_nao_tem_botao_de_apagar(pagina):
    pg, _, _ = pagina
    _abrir_relacao_do_heroi(pg, "Helena")
    assert pg.is_hidden("#psn-apagar")


def test_apagar_tira_o_personagem_da_lista(pagina):
    pg, erros, url = pagina
    _pelo_indice(pg, "Cultista do Minério 1")
    _abrir_ficha_de_personagem(pg, "Cultista do Minério 1")
    pg.click("#psn-apagar")
    pg.wait_for_selector("#dialog-overlay:not(.hidden)", timeout=5000)
    pg.click("#dialog-buttons button:last-child")          # "Apagar"
    pg.wait_for_selector("#pessoa-overlay.hidden", state="attached", timeout=5000)

    pg.click("#sb-atalho-personagens")
    pg.wait_for_selector("#elenco-overlay:not(.hidden)", timeout=5000)
    pg.wait_for_function(
        "() => !document.querySelector(\"#elenco-overlay .elc-cartao[data-nome='Cultista do Minério 1']\")",
        timeout=5000)
    assert not erros, erros[:3]
