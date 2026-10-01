"""
test_combate_habilidades_navegador.py

A tela de combate refeita, vista num celular (375x812), no combate da
partida que motivou a mudança: vez da clériga, quatro contra quatro, a ficha
cheia de magias — uma delas repetida, algumas sem dado — e Stelar na mesma
zona do inimigo que ela quer queimar.

O que o jogador relatou, e o que cada teste prende:
  • "as informações ficam espremidas e eu tenho que rolar para ver cada
    coisa" → os oito combatentes cabem acima da barra de ação, sem rolar;
  • "as magias vinham repetidas e algumas nem tinham dados" → um cartão por
    magia, com o dado que o motor rola;
  • "no mobile não dá nem pra ver a descrição" → o "Detalhes" abre no toque;
  • "sem querer eu ataquei os meus companheiros" → magia que pega todos na
    área pede confirmação mostrando o aliado; a que só fere hostis, não.

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
def celular(app_no_ar):
    from playwright.sync_api import sync_playwright
    import requests

    url, nome, cap = app_no_ar
    with sync_playwright() as pw:
        nav = pw.chromium.launch()

        def abrir(estado=None):
            requests.post(f"{url}/__estado", json=estado or copy.deepcopy(cap.COMBATE_MAGIAS),
                          timeout=10)
            ctx = nav.new_context(viewport={"width": 375, "height": 812},
                                  device_scale_factor=2, is_mobile=True, has_touch=True)
            ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO))
            pg = ctx.new_page()
            erros = []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.goto(f"{url}/game.html", wait_until="networkidle")
            pg.wait_for_selector("#combat-overlay:not(.hidden) .cbt-card", timeout=8000)
            pg.wait_for_function(
                "() => /O que fará Helena/.test(document.getElementById('cbt-action-title').textContent)",
                timeout=8000)
            return pg, erros

        yield abrir
        nav.close()


def _cartao(pg, nome):
    return pg.locator("#cbt-targets .cbt-hab", has=pg.locator(".cbt-hab-nome", has_text=nome)).first


def _vida(pg, nome):
    return pg.evaluate(
        """(n) => { const c = [...document.querySelectorAll('.cbt-card')].find(e => e.dataset.nome === n);
                    return c.querySelector('.cbt-bar-num').textContent.trim(); }""", nome)


# ---------------------------------------------------------------------------
# 1. Quatro contra quatro, sem rolar
# ---------------------------------------------------------------------------

def test_quatro_contra_quatro_cabem_acima_da_barra(celular):
    pg, erros = celular()
    medidas = pg.evaluate("""() => {
        const barra = document.getElementById('cbt-actionbar').getBoundingClientRect();
        const linhas = [...document.querySelectorAll('.cbt-card')].map(e => {
            const r = e.getBoundingClientRect();
            return {nome: e.dataset.nome, base: r.bottom, altura: r.height};
        });
        return {barraTopo: barra.top, linhas,
                rolou: document.getElementById('cbt-frame').scrollTop};
    }""")
    assert len(medidas["linhas"]) == 8, medidas["linhas"]
    assert medidas["rolou"] == 0
    for l in medidas["linhas"]:
        assert l["base"] <= medidas["barraTopo"], f"{l['nome']} ficou atrás da barra ({medidas})"
        assert l["altura"] <= 72, f"linha alta demais: {l}"
    # Os botões de ação inteiros, no rodapé.
    for rotulo in ("Atacar", "Habilidade", "Encerrar Turno"):
        assert pg.locator(f"#cbt-buttons button:has-text('{rotulo}')").is_visible()
    assert not erros, erros[:3]


def test_agora_e_proximo_no_cabecalho(celular):
    pg, erros = celular()
    texto = pg.inner_text("#cbt-vez")
    assert "Agora: Helena" in texto and "Próximo: Stelar" in texto, texto
    assert not erros, erros[:3]


def test_tocar_na_linha_abre_os_detalhes(celular):
    pg, erros = celular()
    linha = pg.locator(".cbt-card[data-nome='Helena']")
    assert not linha.locator(".cbt-detalhes").is_visible()
    linha.click()
    assert linha.locator(".cbt-detalhes").is_visible()
    assert "clérigo" in linha.locator(".cbt-detalhes").inner_text()
    assert linha.get_attribute("aria-expanded") == "true"
    assert not erros, erros[:3]


# ---------------------------------------------------------------------------
# 2. Os cartões de habilidade
# ---------------------------------------------------------------------------

def test_cada_magia_uma_vez_com_o_dado_que_o_motor_rola(celular):
    pg, erros = celular()
    pg.click("#cbt-buttons button:has-text('Habilidade')")
    pg.wait_for_selector("#cbt-targets .cbt-hab")
    nomes = pg.locator("#cbt-targets .cbt-hab-nome").all_inner_texts()
    assert nomes.count("Chama Sagrada") == 1, nomes
    # Sem dado na ficha; o motor rola 3d10.
    assert "3d10" in _cartao(pg, "Infligir Ferimentos").inner_text()
    # Truque de clériga de nível 9: 2d8, não o 1d8 da ficha.
    assert "2d8" in _cartao(pg, "Chama Sagrada").inner_text()
    # O efeito escrito, não só a cor.
    assert _cartao(pg, "Palavra Curativa").locator(".cbt-hab-efeito").inner_text().lower() == "cura"
    assert _cartao(pg, "Coluna de Chamas").locator(".cbt-hab-aviso").is_visible()
    assert not erros, erros[:3]


def test_palavra_curativa_fica_no_grupo_da_acao_bonus(celular):
    pg, erros = celular()
    pg.click("#cbt-buttons button:has-text('Habilidade')")
    grupo = pg.locator("#cbt-targets .cbt-hab-grupo", has_text="Ação bônus")
    assert grupo.locator(".cbt-hab-nome", has_text="Palavra Curativa").count() == 1
    assert not erros, erros[:3]


def test_detalhes_mostra_a_descricao_no_toque(celular):
    pg, erros = celular()
    pg.click("#cbt-buttons button:has-text('Habilidade')")
    cartao = _cartao(pg, "Coluna de Chamas")
    desc = cartao.locator(".cbt-hab-desc")
    assert not desc.is_visible()
    cartao.locator(".cbt-hab-info").click()
    desc.scroll_into_view_if_needed()
    assert desc.is_visible()
    texto = desc.inner_text()
    assert "cilindro de 3 m" in texto and "Alcance" in texto, texto
    # E a descrição em si, que era o que faltava no celular.
    prosa = desc.locator("p").first.inner_text()
    assert len(prosa) > 30 and "Sem descrição" not in prosa, prosa
    assert cartao.locator(".cbt-hab-info").inner_text() == "Fechar"
    assert not erros, erros[:3]


def test_o_cartao_diz_o_que_acontece_ao_usar(celular):
    """
    "Isso faz alguma coisa no combate?" — a pergunta sobre a Taumaturgia. A
    resposta aparece no cartão, antes de gastar o turno.
    """
    pg, erros = celular()
    pg.click("#cbt-buttons button:has-text('Habilidade')")
    taumaturgia = _cartao(pg, "Taumaturgia")
    assert taumaturgia.get_attribute("data-resolucao") == "narrativa"
    assert "o Mestre decide" in taumaturgia.inner_text()
    bencao = _cartao(pg, "Bênção")
    assert bencao.get_attribute("data-resolucao") == "efeito"
    assert "O motor aplica" in bencao.inner_text()
    # Sacerdote de Guerra: só depois de atacar, e o cartão diz por quê.
    sacerdote = _cartao(pg, "Sacerdote de Guerra")
    assert "ataque primeiro" in sacerdote.inner_text()
    assert sacerdote.locator(".cbt-hab-usar").is_disabled()
    assert not erros, erros[:3]


def test_habilidade_narrativa_abre_o_pedido_ao_mestre(celular):
    pg, erros = celular()
    pg.click("#cbt-buttons button:has-text('Habilidade')")
    _cartao(pg, "Taumaturgia").locator(".cbt-hab-usar").click()
    pg.wait_for_selector("#cbt-livre:not(.hidden) #cbt-livre-texto")
    assert pg.input_value("#cbt-livre-texto").startswith("Uso Taumaturgia")
    assert "Usar e pedir ao Mestre" in pg.inner_text("#cbt-livre-enviar")
    assert "o Mestre decide" in pg.inner_text("#cbt-livre")
    # Abrir o pedido não gasta nada: a Ação continua livre até enviar.
    assert pg.is_enabled("#cbt-buttons button:has-text('Atacar')")
    assert not erros, erros[:3]


# ---------------------------------------------------------------------------
# 3. Fogo amigo: regra do jogo, nunca sem aviso
# ---------------------------------------------------------------------------

def _escolher(pg, nome):
    pg.click("#cbt-buttons button:has-text('Habilidade')")
    _cartao(pg, nome).locator(".cbt-hab-usar").click()


def test_area_com_aliado_pede_confirmacao_e_destaca_quem(celular):
    pg, erros = celular()
    _escolher(pg, "Coluna de Chamas")
    # O alvo é escolhido tocando a LINHA do inimigo.
    pg.wait_for_selector(".cbt-card.cbt-alvejavel[data-nome='Victoria']")
    pg.locator(".cbt-card[data-nome='Victoria']").click()
    pg.wait_for_selector("#cbt-targets .cbt-area-aviso")
    aviso = pg.inner_text("#cbt-targets .cbt-area-aviso")
    assert "Stelar" in aviso, aviso
    assert "cbt-na-area-aliado" in pg.locator(".cbt-card[data-nome='Stelar']").get_attribute("class")
    assert "cbt-na-area-aliado" not in pg.locator(".cbt-card[data-nome='Victoria']").get_attribute("class")
    assert not erros, erros[:3]


def test_cancelar_a_confirmacao_nao_gasta_nada(celular):
    pg, erros = celular()
    antes = _vida(pg, "Stelar")
    _escolher(pg, "Coluna de Chamas")
    pg.locator(".cbt-card[data-nome='Victoria']").click()
    pg.wait_for_selector("#cbt-targets .cbt-area-aviso")
    pg.click("#cbt-targets .cbt-cancel")
    assert pg.is_hidden("#cbt-targets")
    assert _vida(pg, "Stelar") == antes
    assert "cbt-na-area-aliado" not in pg.locator(".cbt-card[data-nome='Stelar']").get_attribute("class")
    assert pg.is_enabled("#cbt-buttons button:has-text('Atacar')"), "a ação foi gasta"
    assert not erros, erros[:3]


def test_confirmar_queima_o_aliado_porque_a_regra_manda(celular):
    pg, erros = celular()
    antes = int(_vida(pg, "Stelar").split("/")[0])
    _escolher(pg, "Coluna de Chamas")
    pg.locator(".cbt-card[data-nome='Victoria']").click()
    pg.click("#cbt-targets button:has-text('Conjurar mesmo assim')")
    pg.wait_for_function(
        "(a) => { const c = [...document.querySelectorAll('.cbt-card')].find(e => e.dataset.nome === 'Stelar');"
        " return parseInt(c.querySelector('.cbt-bar-num').textContent) < a; }",
        arg=antes, timeout=8000)
    assert not erros, erros[:3]


def test_magia_que_so_fere_hostis_nao_pede_confirmacao(celular):
    """
    O caso da partida: a Radiância só fere criaturas hostis. Mirada em
    Victoria, pega a Sacada inteira — onde está Stelar — e ele é poupado,
    sem confirmação nenhuma no caminho.
    """
    pg, erros = celular()
    stelar = _vida(pg, "Stelar")
    _escolher(pg, "Canalizar Divindade (Radiância do Amanhecer)")
    pg.wait_for_selector(".cbt-card.cbt-alvejavel[data-nome='Victoria']")
    pg.locator(".cbt-card[data-nome='Victoria']").click()
    pg.wait_for_function(
        "() => document.querySelector('#cbt-buttons button') &&"
        " [...document.querySelectorAll('#cbt-buttons button')]"
        "   .some(b => b.textContent === 'Atacar' && b.disabled)",
        timeout=8000)
    assert pg.locator("#cbt-targets .cbt-area-aviso").count() == 0
    assert _vida(pg, "Stelar") == stelar
    assert "Radiância" in pg.inner_text("#cbt-log")
    assert not erros, erros[:3]
