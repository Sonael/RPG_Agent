"""
test_tela_de_descanso_navegador.py

`test_tela_de_descanso.py` prova que o motor gasta a reserva direito. Isto aqui
prova o que só o navegador vê: que a tela abre sozinha pela proposta do mestre,
que o botão de dado trava pelo motivo certo, que "Não descansar" some depois do
primeiro dado, e que a tela se fecha sozinha se o descanso for interrompido.

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


def _semear(url, estado):
    import requests
    requests.post(f"{url}/__estado", json=estado, timeout=10)


def _fundir(a, b):
    r = copy.deepcopy(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(r.get(k), dict):
            r[k] = _fundir(r[k], v)
        else:
            r[k] = copy.deepcopy(v)
    return r


@pytest.fixture
def navegador(app_no_ar):
    """Contexto novo por abertura: as telas lembram "já abri" no localStorage."""
    from playwright.sync_api import sync_playwright

    url, nome, cap = app_no_ar
    with sync_playwright() as pw:
        nav = pw.chromium.launch()

        def abrir(estado, esperar="#rest-overlay:not(.hidden)", viewport=None):
            _semear(url, estado)
            ctx = nav.new_context(viewport=viewport or {"width": 1440, "height": 980})
            ctx.add_init_script(cap._script_de_semente(
                nome, "pergaminho", cap.HISTORICO, limpar_memoria_de_telas=False))
            pg = ctx.new_page()
            erros = []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
            pg.goto(f"{url}/game.html", wait_until="networkidle")
            cap._sanear(pg)
            # A conclusão manda um aviso ao mestre; aqui não há LLM. O dublê
            # guarda o texto para o teste conferir.
            # Só textos de verdade: o carregamento da página também chama
            # sendToAgent com a abertura da sessão, que aqui vem vazia.
            pg.evaluate("window.__enviado = []; "
                        "window.sendToAgent = async (t) => { if (t) window.__enviado.push(t); }")
            if esperar:
                pg.wait_for_selector(esperar, timeout=10000)
            else:
                pg.wait_for_timeout(1500)
            pg.url_base = url
            return pg, erros

        yield abrir
        nav.close()


@pytest.fixture
def curto(navegador):
    import capturar_telas as cap
    return navegador(cap.DESCANSO_CURTO)


def _cartao(nome):
    return f".rst-card[data-nome='{nome}']"


def _clicar(pg, seletor, espera=600):
    pg.click(seletor)
    pg.wait_for_timeout(espera)


def _estado_servidor(pg):
    return pg.evaluate(
        "async () => (await (await authFetch((window.API || '') + '/api/rest/state')).json())")


def _pessoa(pg, nome):
    return next(p for p in _estado_servidor(pg)["grupo"] if p["nome"] == nome)


# ---- abre ------------------------------------------------------------------

def test_a_tela_abre_sozinha_pela_proposta_do_mestre(curto):
    pg, _ = curto
    assert "descanso curto" in pg.inner_text(".rst-title")
    assert "emboscada" in pg.inner_text("#rst-sub")
    assert pg.locator(".rst-card").count() == 3


def test_sem_proposta_a_tela_nao_abre(navegador):
    pg, _ = navegador({}, esperar=None)
    assert not pg.is_visible("#rest-overlay")
    assert not pg.is_visible("#rst-reopen")


# ---- o dado ----------------------------------------------------------------

def test_gastar_dado_cura_e_esvazia_um_marcador(curto):
    pg, _ = curto
    antes = _pessoa(pg, "Helena")
    cheios = pg.locator(f"{_cartao('Helena')} .rst-pip-cheio").count()

    _clicar(pg, f"{_cartao('Helena')} .rst-dado")

    depois = _pessoa(pg, "Helena")
    assert depois["dados_restantes"] == antes["dados_restantes"] - 1
    assert depois["vida_atual"] > antes["vida_atual"]
    assert pg.locator(f"{_cartao('Helena')} .rst-pip-cheio").count() == cheios - 1
    assert "Helena usa 1d8" in pg.inner_text("#rst-msg")
    assert "1 gasto agora" in pg.inner_text(f"{_cartao('Helena')} .rst-gastos")


def test_vida_cheia_trava_o_dado_e_diz_por_que(curto):
    pg, _ = curto
    botao = f"{_cartao('Natasha')} .rst-dado"
    assert pg.is_disabled(botao)
    assert "Vida cheia" in pg.inner_text(botao)


def test_reserva_vazia_trava_o_dado(curto):
    pg, _ = curto
    _clicar(pg, f"{_cartao('Stelar')} .rst-dado")      # o último dado dele
    botao = f"{_cartao('Stelar')} .rst-dado"
    assert pg.is_disabled(botao), "reserva zerada e o botão continua ativo"
    # Reserva vazia vence "vida cheia" quando as duas valem: é o que o
    # jogador precisa saber — nem dormindo de novo agora ele cura.
    assert "Reserva vazia" in pg.inner_text(botao)


def test_nao_descansar_trava_depois_do_primeiro_dado(navegador):
    """Cancelar apagaria a hora que pagou pela cura já recebida."""
    import capturar_telas as cap
    estado = copy.deepcopy(cap.DESCANSO_CURTO)
    estado["descanso_proposto"]["gastos"] = {}
    pg, _ = navegador(estado)

    assert not pg.is_disabled("#rst-cancelar")
    _clicar(pg, f"{_cartao('Helena')} .rst-dado")
    assert pg.is_disabled("#rst-cancelar")


# ---- concluir / cancelar ---------------------------------------------------

def test_concluir_curto_fecha_passa_a_hora_e_avisa_o_mestre(curto):
    pg, _ = curto
    hora_antes = _estado_servidor(pg)["hora"]
    _clicar(pg, "#rst-concluir", 900)

    assert not pg.is_visible("#rest-overlay")
    assert not pg.is_visible("#rst-reopen"), "pílula ficou depois de concluir"
    snap = _estado_servidor(pg)
    assert snap["tem_descanso"] is False
    assert snap["hora"] != hora_antes, "o descanso curto não passou a hora"

    enviado = pg.evaluate("window.__enviado")
    assert any("[DESCANSO RESOLVIDO NA TELA]" in e for e in enviado), enviado


def test_cancelar_sem_gasto_fecha_sem_descansar(navegador):
    import capturar_telas as cap
    estado = copy.deepcopy(cap.DESCANSO_CURTO)
    estado["descanso_proposto"]["gastos"] = {}
    pg, _ = navegador(estado)
    hora_antes = _estado_servidor(pg)["hora"]

    _clicar(pg, "#rst-cancelar", 900)

    assert not pg.is_visible("#rest-overlay")
    snap = _estado_servidor(pg)
    assert snap["tem_descanso"] is False
    assert snap["hora"] == hora_antes
    assert any("[DESCANSO CANCELADO NA TELA]" in e for e in pg.evaluate("window.__enviado"))


# ---- descanso longo --------------------------------------------------------

def test_longo_mostra_quem_nao_pode_dormir(navegador):
    import capturar_telas as cap
    pg, _ = navegador(cap.DESCANSO_LONGO)

    assert "descanso longo" in pg.inner_text(".rst-title")
    stelar = pg.inner_text(_cartao("Stelar"))
    assert "Faltam 9h" in stelar
    assert "rst-card-fora" in pg.get_attribute(_cartao("Stelar"), "class")
    assert "Exaustão 2 → 1" in pg.inner_text(_cartao("Helena"))
    # Reserva vazia de nível 3: o cartão promete +1, não "todos de volta".
    assert "Dados de vida: +1 (1 / 3)" in pg.inner_text(_cartao("Helena"))
    assert pg.locator(".rst-dado").count() == 0, "botão de dado no descanso longo"
    assert not pg.is_disabled("#rst-concluir")


def test_longo_sem_ninguem_apto_trava_o_dormir(navegador):
    import capturar_telas as cap
    estado = copy.deepcopy(cap.DESCANSO_LONGO)
    for nome in ("helena", "natasha"):
        estado["characters"][nome]["sheet"]["ultimo_descanso_longo"] = 4 * 24 + 20
    pg, _ = navegador(estado)

    assert pg.is_disabled("#rst-concluir")
    assert "Ninguém pode dormir" in pg.inner_text("#rst-concluir")


def test_dormir_restaura_quem_pode(navegador):
    import capturar_telas as cap
    pg, _ = navegador(cap.DESCANSO_LONGO)
    _clicar(pg, "#rst-concluir", 1000)

    assert not pg.is_visible("#rest-overlay")
    helena = _pessoa(pg, "Helena")
    stelar = _pessoa(pg, "Stelar")
    assert helena["vida_atual"] == helena["vida_max"]
    # Nível 3 com a reserva vazia: metade de 3 é 1. Não os 3.
    assert helena["dados_restantes"] == 1
    assert stelar["vida_atual"] == 25, "Stelar dormiu sem poder"


# ---- quando abre, quando fecha ---------------------------------------------

def test_fechar_e_recarregar_nao_reabre(curto):
    pg, _ = curto
    _clicar(pg, ".rst-close", 400)
    pg.reload(wait_until="networkidle")
    pg.wait_for_timeout(1500)

    assert not pg.is_visible("#rest-overlay"), "reabriu depois do F5"
    assert pg.is_visible("#rst-reopen")
    assert "Descanso curto aberto" in pg.inner_text("#rst-reopen")


def test_pilula_reabre_a_tela(curto):
    pg, _ = curto
    _clicar(pg, ".rst-close", 400)
    _clicar(pg, "#rst-reopen", 700)
    assert pg.is_visible("#rest-overlay")


def test_descanso_interrompido_fecha_a_tela(curto):
    """Emboscada: a iniciativa apaga a proposta, e a tela não pode ficar aberta."""
    pg, _ = curto
    _semear(pg.url_base, {"descanso_proposto": None})
    pg.evaluate("window.sincronizarTelas()")
    pg.wait_for_timeout(900)

    assert not pg.is_visible("#rest-overlay")
    assert not pg.is_visible("#rst-reopen")


def test_loja_espera_o_descanso_fechar(navegador):
    import capturar_telas as cap
    pg, _ = navegador(_fundir(cap.LOJA, cap.DESCANSO_CURTO))
    pg.wait_for_timeout(1200)

    assert pg.is_visible("#rest-overlay")
    assert not pg.is_visible("#shop-overlay"), "a loja abriu por cima do descanso"

    _clicar(pg, ".rst-close", 300)
    pg.wait_for_selector("#shop-overlay:not(.hidden)", timeout=5000)


def test_pilulas_de_loja_e_descanso_nao_se_sobrepoem(navegador):
    """
    O empilhamento era CSS de irmão, uma regra por combinação. Com a quarta
    pílula ele passou para o game.js; aqui se mede que as duas visíveis ficam
    uma acima da outra, sem se cobrir.
    """
    import capturar_telas as cap
    pg, _ = navegador(_fundir(cap.LOJA, cap.DESCANSO_CURTO))
    _clicar(pg, ".rst-close", 300)
    pg.wait_for_selector("#shop-overlay:not(.hidden)", timeout=5000)
    _clicar(pg, ".shp-close", 500)

    assert pg.is_visible("#shp-reopen") and pg.is_visible("#rst-reopen")
    loja = pg.locator("#shp-reopen").bounding_box()
    desc = pg.locator("#rst-reopen").bounding_box()
    separadas = (loja["y"] + loja["height"] <= desc["y"]
                 or desc["y"] + desc["height"] <= loja["y"])
    assert separadas, f"pílulas sobrepostas: loja {loja}, descanso {desc}"


def test_a_tela_nao_solta_erro_no_console(curto):
    pg, erros = curto
    _clicar(pg, f"{_cartao('Helena')} .rst-dado")
    _clicar(pg, ".rst-close", 300)
    _clicar(pg, "#rst-reopen", 500)
    assert not erros, f"erros no console: {erros[:3]}"


def test_mobile_os_botoes_do_rodape_cabem(navegador):
    import capturar_telas as cap
    pg, _ = navegador(cap.DESCANSO_CURTO, viewport={"width": 375, "height": 812})
    largura = pg.evaluate("window.innerWidth")
    for sel in ("#rst-cancelar", "#rst-concluir"):
        caixa = pg.locator(sel).bounding_box()
        assert caixa["x"] >= 0 and caixa["x"] + caixa["width"] <= largura, f"{sel} fora da tela: {caixa}"
