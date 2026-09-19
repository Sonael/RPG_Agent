"""
test_mundo_navegador.py

A tela "O Mundo" da fantasia: renome, facções e títulos; companheiros;
lendas; bestiário; mudanças. E o que ela mostra fora dela: o laço na ficha do
companheiro, a mudança na ficha do local e no mapa.

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

FANTASIA = {
    "campaign_type": "fantasia",
    "dnd_mode": False,
    "protagonist": "Aria",
    "chapter": 4,
    "current_location": "Vaelmoor",
    "characters": {
        "aria": {"name": "Aria", "description": "A protagonista.", "status": "vivo"},
        "kael": {"name": "Kael", "description": "Paladino caído.", "status": "vivo",
                 "lealdade": 35, "objetivo": "limpar o nome do pai",
                 "arco": {"titulo": "A redenção de Kael", "estado": "em curso", "cap": 2,
                          "passos": [{"texto": "Encontrou o selo do pai", "cap": 3}]},
                 "lealdade_historico": [{"delta": 35, "motivo": "O grupo poupou o prisioneiro", "cap": 3}]},
        "mira": {"name": "Mira", "description": "Ladra.", "status": "vivo", "lealdade": -55,
                 "objetivo": "pagar a dívida com a guilda"},
    },
    "party": [{"name": "Kael", "role": "paladino"}, {"name": "Mira", "role": "ladra"}],
    "locations": {
        "vaelmoor": {"name": "Vaelmoor", "description": "Vila no vale.",
                     "mudancas": [{"texto": "A vila prosperou", "causa": "os bandidos foram expulsos", "cap": 3}]},
        "ponte velha": {"name": "Ponte Velha", "description": "Sobre o rio.", "dentro_de": "Vaelmoor"},
    },
    "renome": {"valor": 35, "historico": [{"delta": 35, "motivo": "Mataram o wyrm de Cinza", "cap": 3}]},
    "faccoes": {
        "casa vael": {"nome": "Casa Vael", "tipo": "casa nobre", "descricao": "Senhores do vale",
                      "reputacao": 40, "conhecida": True,
                      "historico": [{"delta": 40, "motivo": "Salvaram a filha do barão", "cap": 3}]},
        "guilda das sombras": {"nome": "Guilda das Sombras", "tipo": "guilda", "reputacao": -35,
                               "conhecida": True, "historico": []},
        # Desconhecida: nunca pode aparecer na tela.
        "o olho cinzento": {"nome": "O Olho Cinzento", "tipo": "culto", "reputacao": -20,
                            "conhecida": False, "historico": []},
    },
    "titulos": [{"titulo": "O Juramentado", "quem": "Kael", "motivo": "Cumpriu o voto",
                 "efeito": "abre as portas da ordem", "cap": 3}],
    "lendas": {
        "a coroa afogada": {"titulo": "A Coroa Afogada", "tipo": "artefato perdido",
                            "verdade": "Está no fundo do lago de Vaelmoor", "conhecida": True, "desfecho": "",
                            "fragmentos": [{"texto": "Um rei jogou a coroa na água", "fonte": "um velho pescador",
                                            "cap": 3}]},
        # Nunca ouvida: nunca pode aparecer.
        "a profecia do setimo": {"titulo": "A Profecia do Sétimo Filho", "tipo": "profecia",
                                 "verdade": "Kael é o sétimo filho", "conhecida": False,
                                 "desfecho": "", "fragmentos": []},
    },
    "bestiario": {"carnical": {"nome": "Carniçal", "tipo": "morto-vivo", "descricao": "Morto faminto",
                               "fatos": [{"texto": "Caça em bando à noite"}],
                               "fraquezas": [{"texto": "A luz do sol o queima"}],
                               "encontros": 2, "derrotadas": 1}},
}


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
def jogo(app_no_ar):
    from playwright.sync_api import sync_playwright
    import requests

    url, nome, cap = app_no_ar
    with sync_playwright() as pw:
        nav = pw.chromium.launch()

        def abrir(estado, viewport=None):
            requests.post(f"{url}/__estado", json=copy.deepcopy(estado), timeout=10)
            ctx = nav.new_context(viewport=viewport or {"width": 1440, "height": 980})
            ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO))
            pg = ctx.new_page()
            erros = []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
            pg.goto(f"{url}/game.html", wait_until="networkidle")
            cap._sanear(pg)
            pg.wait_for_selector("#sb-atalhos .sb-atalho", timeout=8000)
            pg.wait_for_timeout(500)
            return pg, erros

        yield abrir
        nav.close()


def _atalhos(pg):
    return pg.eval_on_selector_all("#sb-atalhos .sb-atalho .sb-atalho-rotulo",
                                   "els => els.map(e => e.textContent.trim())")


def test_fantasia_tem_o_atalho_do_mundo_e_o_horror_nao(jogo, app_no_ar):
    pg, erros = jogo(FANTASIA)
    assert "Mundo" in _atalhos(pg)
    pg.click("#sb-atalho-mundo")
    pg.wait_for_selector("#mundo-overlay:not(.hidden) .mnd-renome", timeout=8000)
    estado = copy.deepcopy(FANTASIA)
    estado["campaign_type"] = "horror"
    pg2, erros2 = jogo(estado)
    assert "Mundo" not in _atalhos(pg2)
    assert not erros and not erros2, (erros + erros2)[:3]


def test_renome_faccoes_e_titulos(jogo):
    pg, erros = jogo(FANTASIA)
    pg.evaluate("() => window.Mundo._abrir('renome')")
    pg.wait_for_selector(".mnd-faccao", timeout=8000)
    fama = " ".join(pg.text_content(".mnd-renome").split())
    assert "conhecidos no reino" in fama and "35" in fama and "Mataram o wyrm de Cinza" in fama
    assert pg.eval_on_selector_all(".mnd-faccao", "els => els.map(e => e.dataset.nome)") == \
        ["Casa Vael", "Guilda das Sombras"]
    assert "aliados" in pg.text_content(".mnd-faccao[data-nome='Casa Vael']")
    assert "mnd-negativa" in pg.get_attribute(".mnd-faccao[data-nome='Guilda das Sombras']", "class")
    titulo = " ".join(pg.text_content(".mnd-titulo-item").split())
    assert "O Juramentado" in titulo and "Kael" in titulo and "abre as portas da ordem" in titulo
    # A facção que o grupo não conhece não chega à tela.
    assert "O Olho Cinzento" not in pg.content()
    assert not erros, erros[:3]


def test_companheiros_lendas_bestiario_e_mudancas(jogo):
    pg, erros = jogo(FANTASIA)
    pg.evaluate("() => window.Mundo._abrir('companheiros')")
    pg.wait_for_selector(".mnd-companheiro", timeout=8000)
    # A lealdade mais baixa primeiro: é a que pede atenção.
    assert pg.eval_on_selector_all(".mnd-companheiro", "els => els.map(e => e.dataset.nome)") == ["Mira", "Kael"]
    kael = " ".join(pg.text_content(".mnd-companheiro[data-nome='Kael']").split())
    assert "leal" in kael and "limpar o nome do pai" in kael and "A redenção de Kael" in kael
    assert "Encontrou o selo do pai" in kael
    assert "à beira de partir" in pg.text_content(".mnd-companheiro[data-nome='Mira']")

    pg.click("#mnd-abas .elc-filtro[data-aba='lendas']")
    pg.wait_for_selector(".mnd-lenda", timeout=5000)
    lenda = " ".join(pg.text_content(".mnd-lenda").split())
    assert "A Coroa Afogada" in lenda and "Um rei jogou a coroa na água" in lenda and "um velho pescador" in lenda
    # A verdade e a lenda nunca ouvida ficam com o mestre.
    assert "fundo do lago" not in pg.content() and "Sétimo Filho" not in pg.content()

    pg.click("#mnd-abas .elc-filtro[data-aba='bestiario']")
    pg.wait_for_selector(".mnd-criatura", timeout=5000)
    bicho = " ".join(pg.text_content(".mnd-criatura").split())
    assert "Carniçal" in bicho and "A luz do sol o queima" in bicho and "Caça em bando à noite" in bicho

    pg.click("#mnd-abas .elc-filtro[data-aba='mudancas']")
    pg.wait_for_selector(".mnd-mudanca", timeout=5000)
    assert "A vila prosperou" in pg.text_content(".mnd-mudanca")
    assert not erros, erros[:3]


def test_laco_na_ficha_e_mudanca_no_local_e_no_mapa(jogo):
    pg, erros = jogo(FANTASIA)
    pg.evaluate("() => window.Personagens._abrir('Kael')")
    pg.wait_for_selector("#psn-laco .psn-barra", timeout=8000)
    laco = " ".join(pg.text_content("#psn-laco").split())
    assert "Lealdade: leal" in laco and "A redenção de Kael" in laco and "O Juramentado" in laco
    pg.evaluate("() => window.Personagens._fechar()")
    pg.evaluate("() => window.Locais._abrir('Vaelmoor')")
    pg.wait_for_selector("#lcl-mudancas-bloco:not(.hidden)", timeout=8000)
    assert "A vila prosperou" in pg.text_content("#lcl-mudancas")
    pg.evaluate("() => window.Locais._fechar()")
    pg.evaluate("() => window.Mapa._abrir('')")
    pg.wait_for_selector("#map-arvore .map-no[data-nome='Vaelmoor'] .map-marca-mudou", timeout=8000)
    assert pg.locator("#map-arvore .map-no[data-nome='Ponte Velha'] > .map-linha .map-marca-mudou").count() == 0
    assert not erros, erros[:3]
