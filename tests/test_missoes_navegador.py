"""
test_missoes_navegador.py

A tela de missões no navegador: abre pelo "Ver todas" e pela missão na barra
lateral, separa ativas, concluídas e falhadas, marca objetivo, abre a ficha de
quem deu, avisa o mestre uma vez ao fechar, abandona com confirmação e fala
com quem deu a missão pronta.

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
    estado = copy.deepcopy(cap.MISSOES)
    estado["missoes_mudadas_na_tela"] = []
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
        pg.wait_for_timeout(800)
        pg.evaluate("() => { window.__enviados = [];"
                    " window.sendToAgent = async (t) => { window.__enviados.push(t); }; }")
        yield pg, erros
        nav.close()


def _cartao(titulo):
    return f"#missoes-overlay .msn-cartao[data-titulo='{titulo}']"


def _esperar_lista(pg):
    pg.wait_for_selector("#missoes-overlay:not(.hidden) .msn-cartao, #missoes-overlay:not(.hidden) .msn-vazio",
                         timeout=5000)


def test_atalho_abre_nas_ativas(pagina):
    pg, erros = pagina
    pg.click("#sb-atalho-missoes")
    _esperar_lista(pg)
    assert pg.inner_text("#sb-atalho-missoes .sb-atalho-conta") == "3", "o contador são as ativas"
    abas = pg.inner_text("#msn-abas")
    assert "Ativas 3" in abas and "Concluídas 1" in abas and "Falhadas e abandonadas 1" in abas
    assert pg.locator("#msn-lista .msn-cartao").count() == 3
    princesa = pg.inner_text(_cartao("Escoltar a Princesa Elara"))
    assert "2/3" in princesa and "200 po" in princesa and "Elara" in princesa
    assert not erros, erros[:3]


def test_missao_principal_da_barra_lateral_abre_a_tela_nela(pagina):
    pg, _ = pagina
    # A principal é a ativa do capítulo mais recente: a dívida de Torbin.
    assert pg.get_attribute("#sb-missao", "data-titulo") == "A dívida de Torbin"
    pg.click("#sb-missao")
    pg.wait_for_selector(f"{_cartao('A dívida de Torbin')}.msn-destaque", timeout=5000)


def test_abrir_uma_encerrada_vai_para_a_aba_dela(pagina):
    pg, _ = pagina
    pg.evaluate("() => window.Missoes._abrir('Ratos no porão')")
    pg.wait_for_selector(_cartao("Ratos no porão"), timeout=5000)
    cartao = pg.inner_text(_cartao("Ratos no porão"))
    assert "Eram só três ratos e um gato." in cartao
    assert pg.is_disabled(f"{_cartao('Ratos no porão')} input[type=checkbox]")
    assert pg.locator(f"{_cartao('Ratos no porão')} .msn-abandonar").count() == 0


def test_marcar_objetivo_e_avisar_o_mestre_ao_fechar(pagina):
    pg, erros = pagina
    pg.evaluate("() => window.Missoes._abrir('')")
    _esperar_lista(pg)
    caixa = f"{_cartao('A dívida de Torbin')} input[type=checkbox]"
    pg.check(caixa)
    pg.wait_for_function("() => document.getElementById('msn-msg').textContent.includes('feito (1/1)')",
                         timeout=5000)
    assert "pronta para entregar" in pg.inner_text(_cartao("A dívida de Torbin"))
    # A missão principal no relance acompanha.
    pg.wait_for_function(
        "() => /1\\/1/.test(document.getElementById('sb-missao').textContent)", timeout=5000)

    pg.click("#missoes-overlay .lcl-fechar")
    pg.wait_for_function("() => window.__enviados.length === 1", timeout=5000)
    aviso = pg.evaluate("() => window.__enviados[0]")
    assert aviso.startswith("[MISSÕES ATUALIZADAS NA TELA]")
    assert "Descobrir quem cobra a dívida" in aviso

    # Reabrir e fechar sem mexer não manda nada.
    pg.evaluate("() => window.Missoes._abrir('')")
    _esperar_lista(pg)
    pg.click("#missoes-overlay .lcl-fechar")
    pg.wait_for_timeout(600)
    assert pg.evaluate("() => window.__enviados.length") == 1
    assert not erros, erros[:3]


def test_falar_com_quem_deu_a_missao_pronta(pagina):
    pg, _ = pagina
    pg.evaluate("() => window.Missoes._abrir('O mapa de Kaelen')")
    pg.wait_for_selector(_cartao("O mapa de Kaelen"), timeout=5000)
    pg.click(f"{_cartao('O mapa de Kaelen')} button:has-text('Falar com Kaelen')")
    pg.wait_for_function("() => window.__enviados.length === 1", timeout=5000)
    assert pg.evaluate("() => window.__enviados[0]") == 'Quero falar com Kaelen sobre a missão "O mapa de Kaelen".'
    assert pg.is_hidden("#missoes-overlay")


def test_nome_de_quem_deu_abre_a_ficha_do_personagem(pagina):
    pg, _ = pagina
    pg.evaluate("() => window.Missoes._abrir('Escoltar a Princesa Elara')")
    pg.wait_for_selector(_cartao("Escoltar a Princesa Elara"), timeout=5000)
    pg.click(f"{_cartao('Escoltar a Princesa Elara')} a:has-text('Elara')")
    pg.wait_for_selector("#pessoa-overlay:not(.hidden)", timeout=5000)
    assert pg.is_hidden("#missoes-overlay")


def test_abandonar_pede_confirmacao(pagina):
    pg, _ = pagina
    pg.evaluate("() => window.Missoes._abrir('')")
    _esperar_lista(pg)
    botao = f"{_cartao('A dívida de Torbin')} .msn-abandonar"
    pg.click(botao)
    assert "Confirmar abandono" in pg.inner_text(botao)
    assert pg.locator("#msn-lista .msn-cartao").count() == 3, "abandonou no primeiro clique"
    pg.click(botao)
    pg.wait_for_function("() => document.querySelectorAll('#msn-lista .msn-cartao').length === 2",
                         timeout=5000)
    assert "Falhadas e abandonadas 2" in pg.inner_text("#msn-abas")


# ---------------------------------------------------------------------------
# O caderno do jogador: editar a missão na tela e criar a sua
# ---------------------------------------------------------------------------

def _editar(pg, titulo):
    pg.evaluate("() => window.Missoes._abrir('')")
    _esperar_lista(pg)
    pg.click(f"{_cartao(titulo)} .msn-editar")
    pg.wait_for_selector("#msn-ed-titulo", timeout=5000)


def test_editar_missao_muda_os_campos_e_os_objetivos(pagina):
    pg, erros = pagina
    _editar(pg, "A dívida de Torbin")
    pg.fill("#msn-ed-titulo", "A dívida do velho Torbin")
    pg.fill("#msn-ed-recompensa", "O anel de sinete")
    # Um objetivo novo, e o de cima reescrito.
    pg.fill("#msn-obj-novo", "Falar com o agiota")
    pg.click("#missoes-overlay .msn-obj-novo .lcl-btn")
    pg.wait_for_selector("#missoes-overlay .msn-objetivo-edit:nth-child(2)", timeout=5000)
    pg.fill("#missoes-overlay .msn-obj-texto >> nth=0", "Descobrir quem cobra a dívida do pai")
    pg.click("#missoes-overlay .lcl-btn-ir:has-text('Salvar')")

    cartao = _cartao("A dívida do velho Torbin")
    pg.wait_for_selector(cartao, timeout=5000)
    texto = pg.inner_text(cartao)
    assert "O anel de sinete" in texto
    assert "Descobrir quem cobra a dívida do pai" in texto
    assert "Falar com o agiota" in texto
    assert pg.locator(f"{cartao} .msn-objetivo").count() == 2
    assert not erros, erros[:3]


def test_remover_e_reordenar_objetivo(pagina):
    pg, erros = pagina
    _editar(pg, "Escoltar a Princesa Elara")
    antes = pg.eval_on_selector_all("#missoes-overlay .msn-obj-texto", "els => els.map(e => e.value)")
    assert len(antes) == 3
    # Sobe o último e apaga o primeiro da nova ordem.
    pg.click("#missoes-overlay .msn-objetivo-edit >> nth=2 >> .msn-obj-btn >> nth=0")
    pg.wait_for_function(
        """(esperado) => [...document.querySelectorAll('#missoes-overlay .msn-obj-texto')]
             .map(e => e.value)[1] === esperado""", arg=antes[2], timeout=5000)
    pg.click("#missoes-overlay .msn-objetivo-edit >> nth=0 >> .msn-obj-tirar")
    pg.wait_for_function(
        "() => document.querySelectorAll('#missoes-overlay .msn-obj-texto').length === 2", timeout=5000)
    depois = pg.eval_on_selector_all("#missoes-overlay .msn-obj-texto", "els => els.map(e => e.value)")
    assert depois == [antes[2], antes[1]], (antes, depois)
    assert not erros, erros[:3]


def test_criar_missao_propria_e_avisar_o_mestre_ao_fechar(pagina):
    pg, erros = pagina
    pg.evaluate("() => window.Missoes._abrir('')")
    _esperar_lista(pg)
    pg.click("#msn-nova-btn")
    pg.wait_for_selector("#msn-nv-titulo", timeout=5000)
    pg.fill("#msn-nv-titulo", "Achar um mestre de armas")
    pg.fill("#msn-nv-descricao", "Alguém que treine o grupo.")
    pg.fill("#msn-nv-objetivos", "Perguntar na taverna\nVisitar o quartel")
    pg.click("#missoes-overlay .lcl-btn-ir:has-text('Criar missão')")

    cartao = _cartao("Achar um mestre de armas")
    pg.wait_for_selector(cartao, timeout=5000)
    assert "Perguntar na taverna" in pg.inner_text(cartao)
    assert pg.locator(f"{cartao} .msn-objetivo").count() == 2
    assert "Ativas 4" in pg.inner_text("#msn-abas")

    pg.click("#missoes-overlay .lcl-fechar")
    pg.wait_for_function("() => window.__enviados.length === 1", timeout=5000)
    aviso = pg.evaluate("() => window.__enviados[0]")
    assert "criou a missão 'Achar um mestre de armas'" in aviso, aviso
    assert not erros, erros[:3]


def test_titulo_repetido_avisa_e_nao_grava(pagina):
    pg, erros = pagina
    _editar(pg, "A dívida de Torbin")
    pg.fill("#msn-ed-titulo", "escoltar a princesa elara")
    pg.click("#missoes-overlay .lcl-btn-ir:has-text('Salvar')")
    pg.wait_for_function(
        "() => document.getElementById('msn-msg').textContent.includes('Já existe')", timeout=5000)
    # Continua em edição, com o que foi digitado, e nada foi gravado.
    assert pg.input_value("#msn-ed-titulo") == "escoltar a princesa elara"
    pg.click("#missoes-overlay .lcl-btn-sec:has-text('Cancelar')")
    pg.wait_for_selector(_cartao("A dívida de Torbin"), timeout=5000)
    assert not erros, erros[:3]


def test_missao_encerrada_nao_tem_editar(pagina):
    pg, _ = pagina
    pg.evaluate("() => window.Missoes._abrir('Ratos no porão')")
    pg.wait_for_selector(_cartao("Ratos no porão"), timeout=5000)
    assert pg.locator(f"{_cartao('Ratos no porão')} .msn-editar").count() == 0


def test_nova_missao_nao_bate_no_fechar_nem_nas_abas(pagina):
    """O botão nasceu no alto à direita e ficava por baixo do X de fechar."""
    pg, _ = pagina
    pg.evaluate("() => window.Missoes._abrir('')")
    _esperar_lista(pg)
    # As abas de verdade, não a faixa delas: a faixa ocupa a largura toda.
    caixas = pg.evaluate("""() => [document.getElementById('msn-nova-btn'),
                                   document.querySelector('#msn-frame .lcl-close'),
                                   ...document.querySelectorAll('#msn-abas .msn-aba')]
        .map(e => e.getBoundingClientRect())
        .map(r => ({l: r.left, r: r.right, t: r.top, b: r.bottom}))""")
    nova = caixas[0]

    def encostam(a, b):
        return a["l"] < b["r"] - 1 and b["l"] < a["r"] - 1 and a["t"] < b["b"] - 1 and b["t"] < a["b"] - 1

    for outro in caixas[1:]:
        assert not encostam(nova, outro), (nova, outro)
    # E está dentro do cabeçalho.
    cab = pg.evaluate("""() => { const r = document.querySelector('#msn-frame .lcl-header')
        .getBoundingClientRect(); return {l: r.left, r: r.right, t: r.top, b: r.bottom}; }""")
    assert cab["l"] <= nova["l"] and nova["r"] <= cab["r"] + 1, (nova, cab)
    assert cab["t"] <= nova["t"] and nova["b"] <= cab["b"] + 1, (nova, cab)


def test_recusa_no_formulario_novo_nao_apaga_o_que_foi_escrito(pagina):
    """Redesenhar no erro limpava o formulário inteiro e o jogador perdia o
    que tinha digitado."""
    pg, erros = pagina
    pg.evaluate("() => window.Missoes._abrir('')")
    _esperar_lista(pg)
    pg.click("#msn-nova-btn")
    pg.wait_for_selector("#msn-nv-titulo", timeout=5000)
    pg.fill("#msn-nv-titulo", "escoltar a princesa elara")
    pg.fill("#msn-nv-descricao", "Levar a princesa por outro caminho.")
    pg.fill("#msn-nv-objetivos", "Achar um barqueiro")
    pg.click("#missoes-overlay .lcl-btn-ir:has-text('Criar missão')")
    pg.wait_for_function(
        "() => document.getElementById('msn-msg').textContent.includes('Já existe')", timeout=5000)
    assert pg.input_value("#msn-nv-descricao") == "Levar a princesa por outro caminho."
    assert pg.input_value("#msn-nv-objetivos") == "Achar um barqueiro"
    assert pg.locator("#msn-lista .msn-cartao").count() == 4    # os 3 + o formulário
    assert not erros, erros[:3]
