"""
test_animacoes_navegador.py

As animações do livro e a escolha de animações.

A aparência se confere nas capturas; aqui se prova o que não pode quebrar:
  • a escolha nas configurações ("Seguir o sistema", "Ligadas", "Desligadas")
    fica guardada, e "Seguir o sistema" obedece ao reduzir movimento do
    aparelho; o CSS desliga as animações e o JS pergunta animacoesLigadas();
  • virar a página troca o conteúdo na hora (a animação é uma cópia por
    cima), a cópia some no fim e não rouba o botão de rádio do original;
  • menu e jogo são páginas do mesmo livro: a passagem vira a folha e a
    página seguinte chega sem abrir a capa de novo;
  • capítulo novo vira a página, e só quando o capítulo sobe durante o jogo.

As capturas e os outros testes rodam com as animações desligadas
(capturar_telas._script_de_semente); aqui elas são ligadas de propósito.

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
    import requests

    campanha = json.loads((RAIZ / "scripts" / "temp.json").read_text(encoding="utf-8"))
    nome = campanha.get("name") or "Crônicas de Oakhaven"
    campanha["name"] = nome
    url, parar = cap._subir_servidor(campanha, nome)
    try:
        requests.post(f"{url}/__estado", json=copy.deepcopy(cap.DIARIO), timeout=10)
        yield url, nome, cap
    finally:
        parar()


@pytest.fixture
def abrir(app_no_ar):
    """abrir(caminho, animacoes='ligadas', movimento='no-preference') -> (pg, erros)"""
    from playwright.sync_api import sync_playwright

    url, nome, cap = app_no_ar
    pw = sync_playwright().start()
    nav = pw.chromium.launch()

    def _abrir(caminho, animacoes="ligadas", movimento="no-preference"):
        ctx = nav.new_context(viewport={"width": 1440, "height": 900}, reduced_motion=movimento)
        ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO))
        ctx.add_init_script(f"localStorage.setItem('rpg_animacoes', {json.dumps(animacoes)});")
        ctx.add_init_script(CONTA_CAPITULOS)
        pg = ctx.new_page()
        erros = []
        pg.on("pageerror", lambda e: erros.append(str(e)))
        pg.goto(f"{url}{caminho}", wait_until="networkidle")
        return pg, erros

    try:
        yield _abrir
    finally:
        nav.close()
        pw.stop()


# Conta os cartões de capítulo criados desde a carga: sem animações ele dura
# um centésimo de milissegundo e sumiria antes de qualquer verificação.
CONTA_CAPITULOS = """
  window.__capitulos = 0;
  new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => {
    if (n.classList && n.classList.contains('capitulo-novo')) window.__capitulos++;
  }))).observe(document, {childList: true, subtree: true});
"""


def _terminar(pg):
    pg.evaluate("() => document.getAnimations().forEach(a => { try { a.finish(); } catch (_) {} })")


# --- A escolha ---------------------------------------------------------------

@pytest.mark.parametrize("escolha, movimento, ligadas", [
    ("sistema", "no-preference", True),
    ("sistema", "reduce", False),
    ("ligadas", "reduce", True),                  # quem escolheu vence o aparelho
    ("desligadas", "no-preference", False),
])
def test_escolha_e_o_reduzir_movimento_do_aparelho(abrir, escolha, movimento, ligadas):
    pg, erros = abrir("/menu.html", escolha, movimento)
    assert pg.evaluate("() => animacoesLigadas()") is ligadas
    duracao = pg.evaluate("() => getComputedStyle(document.querySelector('.tome-cover')).animationDuration")
    assert (duracao == "1.25s") is ligadas, duracao
    assert not erros, erros[:3]


def test_escolha_fica_guardada(abrir):
    pg, erros = abrir("/menu.html", "sistema")
    opcoes = pg.locator("#settings-panel .settings-anim-option")
    assert opcoes.count() == 3
    assert pg.evaluate("() => document.querySelector('.settings-anim-option.active').dataset.anim") == "sistema"
    pg.evaluate("() => applyAnimacoes('desligadas')")
    assert pg.evaluate("() => [document.documentElement.dataset.animacoes, localStorage.getItem('rpg_animacoes')]") \
        == ["desligadas", "desligadas"]
    assert pg.evaluate("() => document.querySelector('.settings-anim-option.active').dataset.anim") == "desligadas"
    # Uma página nova lê a escolha guardada (aqui sem a semente, que a
    # sobrescreveria na carga).
    pg.evaluate("() => { document.documentElement.dataset.animacoes = ''; loadAnimacoes(); }")
    assert pg.evaluate("() => [document.documentElement.dataset.animacoes, animacoesLigadas()]") \
        == ["desligadas", False]
    assert not erros, erros[:3]


# --- Virar a página ----------------------------------------------------------

def _diario(pg):
    _terminar(pg)
    pg.evaluate("() => window.Diario._abrir(1)")
    pg.wait_for_selector("#diario-overlay:not(.hidden) #dia-pagina", timeout=8000)
    pg.wait_for_timeout(300)
    _terminar(pg)


def test_diario_vira_e_o_conteudo_troca_na_hora(abrir):
    pg, erros = abrir("/game.html")
    _diario(pg)
    antes = pg.inner_text("#dia-pagina")
    pg.evaluate("() => window.Diario._virar(1)")
    assert pg.locator("#diario-overlay .folha-virando").count() == 1, "a folha não virou"
    depois = pg.inner_text("#dia-pagina")
    assert depois != antes, "o conteúdo esperou a animação para trocar"
    assert pg.evaluate("() => document.querySelectorAll('#dia-pagina').length") == 2   # a cópia, por cima
    pg.wait_for_function("() => !document.querySelector('.folha-virando')", timeout=3000)
    assert pg.evaluate("() => document.querySelectorAll('#dia-pagina').length") == 1
    pg.evaluate("() => window.Diario._virar(-1)")
    assert pg.inner_text("#dia-pagina") == antes
    pg.wait_for_function("() => !document.querySelector('.folha-virando')", timeout=3000)
    assert not erros, erros[:3]


def test_sem_animacoes_nao_ha_folha(abrir):
    pg, erros = abrir("/game.html", "desligadas")
    _diario(pg)
    pg.evaluate("() => window.Diario._virar(1)")
    assert pg.locator(".folha-virando").count() == 0
    assert not erros, erros[:3]


def test_passos_do_wizard_viram_sem_roubar_o_radio(abrir):
    pg, erros = abrir("/menu.html")
    _terminar(pg)
    pg.evaluate("() => { openWizard(); document.getElementById('wz-name').value = 'Teste'; wizardGoTo(2); }")
    pg.wait_for_function("() => !document.querySelector('.folha-virando')", timeout=3000)
    pg.evaluate("() => { addWzChar(); addWzChar(); wzMarcarProtagonista(1); }")
    pg.evaluate("() => wizardGoTo(1)")
    assert pg.evaluate("() => wzStep") == 1
    # Para trás são duas: a de agora parada e a anterior virando por cima.
    assert pg.locator("#wizard-overlay .folha-virando").count() == 2
    # A cópia do passo 2 tem os rádios; o original continua marcado.
    assert pg.evaluate("() => [...document.querySelectorAll('#wz-panel-2 .wz-protagonista')]"
                       ".filter(r => !r.closest('.folha-virando')).map(r => r.checked)") == [False, True]
    pg.wait_for_function("() => !document.querySelector('.folha-virando')", timeout=3000)
    assert pg.evaluate("() => wzChars.map(c => c.protagonista)") == [False, True]
    assert not erros, erros[:3]


# --- Menu e jogo: a mesma história, páginas diferentes ------------------------

def test_menu_para_o_jogo_vira_e_chega_sem_abrir_a_capa(abrir):
    pg, erros = abrir("/menu.html")
    _terminar(pg)
    pg.evaluate("() => { virarParaOutraPagina('/game.html', 1); }")
    assert pg.locator(".tome .folha-do-livro").count() == 1
    assert pg.evaluate("() => document.querySelector('.tome > .page-right').classList.contains('pagina-em-branco')")
    pg.wait_for_url("**/game.html", timeout=5000)
    pg.wait_for_load_state("networkidle")
    assert pg.evaluate("() => document.documentElement.classList.contains('chegou-virando')")
    assert pg.evaluate("() => getComputedStyle(document.querySelector('.tome-cover')).display") == "none"
    assert pg.evaluate("() => sessionStorage.getItem('rpg_chegou_virando')") is None
    assert not erros, erros[:3]


def test_jogo_para_o_menu_vira_para_tras(abrir):
    pg, erros = abrir("/game.html")
    _terminar(pg)
    pg.evaluate("() => { virarParaOutraPagina('/menu.html', -1); }")
    folha = pg.evaluate("() => { const f = document.querySelector('.tome .folha-do-livro');"
                        " return f && f.style.transformOrigin; }")
    assert folha and folha.startswith("right"), folha         # a esquerda vira pela lombada
    pg.wait_for_url("**/menu.html", timeout=5000)
    assert pg.evaluate("() => document.documentElement.classList.contains('chegou-virando')")
    assert not erros, erros[:3]


def test_entrar_sem_virar_abre_a_capa(abrir):
    pg, erros = abrir("/menu.html")
    assert not pg.evaluate("() => document.documentElement.classList.contains('chegou-virando')")
    assert pg.evaluate("() => getComputedStyle(document.querySelector('.tome-cover')).display") != "none"
    assert not erros, erros[:3]


# --- Capítulo novo ------------------------------------------------------------

def test_capitulo_novo_vira_a_pagina(abrir):
    pg, erros = abrir("/game.html")
    _terminar(pg)
    assert pg.evaluate("() => window.__capitulos") == 0, "anunciou o capítulo na primeira carga"
    pg.evaluate("""() => renderMemory({...window._lastMem, chapter: (window._lastMem.chapter || 1) + 2,
                  diary: [...(window._lastMem.diary || []), {chapter: (window._lastMem.chapter || 1) + 2,
                          title: 'A Ponte Caída', content: ''}]})""")
    cartao = pg.locator("#chat-area .capitulo-novo")
    assert cartao.count() == 1
    texto = cartao.text_content()
    assert "A Ponte Caída" in texto and "Capítulo" in texto
    assert pg.evaluate("() => document.querySelector('.capitulo-novo-num').textContent") == "IV"
    pg.wait_for_function("() => !document.querySelector('.capitulo-novo')", timeout=6000)
    # O mesmo capítulo de novo não anuncia.
    pg.evaluate("() => renderMemory({...window._lastMem})")
    assert pg.locator(".capitulo-novo").count() == 0
    assert not erros, erros[:3]


def test_capitulo_novo_sem_animacoes_nao_cobre_a_narracao(abrir):
    pg, erros = abrir("/game.html", "desligadas")
    pg.evaluate("() => renderMemory({...window._lastMem, chapter: (window._lastMem.chapter || 1) + 1})")
    pg.wait_for_timeout(200)
    assert pg.evaluate("() => window.__capitulos") == 0
    assert not erros, erros[:3]
