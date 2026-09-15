"""
test_mochila_navegador.py

`test_mochila.py` prova as regras de equipamento no motor. Isto aqui prova o
que só o navegador vê: que a Mochila abre pelo atalho do cartão (e não
sozinha), que o botão de vestir mostra a prévia de CA e a CA do cabeçalho
muda de verdade, que tirar e largar liberam o slot, que identificar some com
o botão, e que com a Mochila aberta nenhuma outra tela se empilha por cima.

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


@pytest.fixture
def navegador(app_no_ar):
    from playwright.sync_api import sync_playwright

    url, nome, cap = app_no_ar
    with sync_playwright() as pw:
        nav = pw.chromium.launch()

        def abrir(estado, viewport=None, abrir_mochila=True):
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
            pg.wait_for_timeout(800)
            if abrir_mochila:
                pg.evaluate("window.Inventory._abrir('Stelar')")
                pg.wait_for_selector(".inv-item", timeout=10000)
            pg.url_base = url
            return pg, erros

        yield abrir
        nav.close()


@pytest.fixture
def pagina(navegador):
    import capturar_telas as cap
    return navegador(cap.MOCHILA)


def _item(nome):
    return f".inv-item[data-nome='{nome}']"


def _slot(slot):
    return f".inv-slot[data-slot='{slot}']"


def _clicar(pg, seletor, espera=900):
    pg.click(seletor)
    pg.wait_for_timeout(espera)


def _ca(pg):
    return int(pg.inner_text("#inv-ca-num"))


def _estado(pg, nome="Stelar"):
    return pg.evaluate(
        "async (n) => (await (await authFetch((window.API || '') + "
        "'/api/inventory/state?personagem=' + encodeURIComponent(n))).json())", nome)


# ---- abrir -----------------------------------------------------------------

def test_nao_abre_sozinha(navegador):
    import capturar_telas as cap
    pg, _ = navegador(cap.MOCHILA, abrir_mochila=False)
    pg.wait_for_timeout(800)
    assert not pg.is_visible("#inventory-overlay")


def test_atalho_no_cartao_abre_sem_o_modal(navegador):
    import capturar_telas as cap
    pg, _ = navegador(cap.MOCHILA, abrir_mochila=False)
    _clicar(pg, ".tab-btn[data-tab='enciclopedia']", 400)
    atalho = "xpath=//div[contains(@class,'char-card')][.//text()[contains(.,'Stelar')]]//span[contains(@class,'mochila-link')]"
    pg.wait_for_selector(atalho, state="visible", timeout=5000)
    _clicar(pg, atalho, 1000)
    assert pg.is_visible("#inventory-overlay")
    assert "Stelar" in pg.inner_text(".inv-title")
    assert not pg.is_visible("#edit-overlay"), "o clique abriu também o modal de edição"


# ---- vestir e tirar --------------------------------------------------------

def test_botao_mostra_a_previa_de_ca(pagina):
    pg, _ = pagina
    botao = f"{_item('Cota de Malha')} .inv-btn-equipar[data-slot='armadura']"
    assert "CA 14 → 16" in pg.inner_text(botao)


def test_vestir_a_cota_troca_a_armadura_e_sobe_a_ca(pagina):
    pg, _ = pagina
    assert _ca(pg) == 14
    _clicar(pg, f"{_item('Cota de Malha')} .inv-btn-equipar[data-slot='armadura']")

    assert _ca(pg) == 16
    assert "Cota de Malha" in pg.inner_text(_slot("armadura"))
    assert "CA: 14 → 16" in pg.inner_text("#inv-msg")
    armadura = next(e for e in _estado(pg)["personagem"]["equipados"] if e["slot"] == "armadura")
    assert armadura["item"] == "Cota de Malha", "a tela mudou e a ficha não"
    # O camisão voltou para a mochila e ganhou o botão de vestir de novo.
    assert pg.is_visible(f"{_item('Camisão de Malha')} .inv-btn-equipar[data-slot='armadura']")


def test_tirar_a_armadura(pagina):
    pg, _ = pagina
    _clicar(pg, f"{_slot('armadura')} .inv-btn-tirar")
    assert _ca(pg) == 11          # 10 + DES 12
    assert "vazio" in pg.inner_text(_slot("armadura"))


def test_escudo_soma_dois(pagina):
    pg, _ = pagina
    _clicar(pg, f"{_item('Escudo')} .inv-btn-equipar[data-slot='escudo']")
    assert _ca(pg) == 16


def test_adaga_unica_nao_oferece_a_segunda_mao(pagina):
    pg, _ = pagina
    _clicar(pg, f"{_item('Adaga')} .inv-btn-equipar[data-slot='arma_secundaria']")
    assert "Adaga" in pg.inner_text(_slot("arma_secundaria"))
    assert pg.locator(f"{_item('Adaga')} .inv-btn-equipar").count() == 0, \
        "uma adaga só e o botão de pô-la na outra mão continua lá"


# ---- largar e identificar --------------------------------------------------

def test_largar_a_espada_empunhada_esvazia_a_mao(pagina):
    pg, _ = pagina
    _clicar(pg, f"{_item('Espada Longa')} .inv-btn-largar")
    assert "vazio" in pg.inner_text(_slot("arma_principal"))
    assert pg.locator(_item("Espada Longa")).count() == 0


def test_largar_uma_tocha_de_cinco(pagina):
    pg, _ = pagina
    _clicar(pg, f"{_item('Tocha')} .inv-btn-largar")
    assert "×4" in pg.inner_text(f"{_item('Tocha')} .inv-item-nome")


def _open5e_falso(monkeypatch, itens, atraso=0.0):
    """O servidor roda neste processo: simular o Open5e aqui vale para a tela."""
    import time
    from rpg import open5e

    def falso(url, params=None, timeout=5.0):
        if atraso:
            time.sleep(atraso)
        if params and "search" in params:
            return open5e.Response(True, {"results": []}, 200)
        dados = itens.get(url.rstrip("/").rsplit("/", 1)[-1])
        return open5e.Response(bool(dados), dados, 200 if dados else 404)

    monkeypatch.setattr(open5e, "get", falso)


_CLOAK = {"name": "Cloak of Elvenkind", "type": "Wondrous item", "rarity": "uncommon",
          "requires_attunement": "requires attunement", "document__slug": "wotc-srd",
          "desc": "While you wear this cloak with its hood up..."}


def test_identificar_mostra_que_esta_consultando(pagina, monkeypatch):
    """O defeito relatado: o clique não dava sinal nenhum até a resposta."""
    _open5e_falso(monkeypatch, {"cloak-of-elvenkind": _CLOAK}, atraso=0.6)
    pg, _ = pagina
    botao = f"{_item('Manto Élfico')} .inv-btn-identificar"

    pg.click(botao)

    pg.wait_for_selector(f"{botao}.inv-btn-consultando", timeout=2000)
    assert "Consultando" in pg.inner_text(botao)
    assert "Consultando o SRD" in pg.inner_text("#inv-msg")
    assert pg.is_disabled(f"{_item('Tocha')} .inv-btn-largar"), "os outros botões seguiam clicáveis"
    pg.wait_for_selector(f"{_item('Manto Élfico')} .inv-marca-srd", timeout=15000)
    assert pg.is_enabled(f"{_item('Tocha')} .inv-btn-largar")


def test_identificar_diz_o_que_achou(pagina, monkeypatch):
    _open5e_falso(monkeypatch, {"cloak-of-elvenkind": _CLOAK})
    pg, _ = pagina

    _clicar(pg, f"{_item('Manto Élfico')} .inv-btn-identificar", 1200)

    assert pg.locator(f"{_item('Manto Élfico')} .inv-btn-identificar").count() == 0
    assert "SRD: Cloak of Elvenkind" in pg.inner_text(_item("Manto Élfico"))
    msg = pg.inner_text("#inv-msg")
    assert "Manto Élfico é Cloak of Elvenkind no SRD" in msg
    assert "item maravilhoso, incomum, requer sintonização" in msg
    assert "inv-msg-erro" not in (pg.get_attribute("#inv-msg", "class") or "")


def test_identificar_fora_do_srd_marca_como_proprio(pagina, monkeypatch):
    _open5e_falso(monkeypatch, {})
    pg, _ = pagina
    _clicar(pg, f"{_item('Manto Élfico')} .inv-btn-identificar", 1200)
    assert pg.locator(f"{_item('Manto Élfico')} .inv-btn-identificar").count() == 0
    assert "próprio da campanha" in pg.inner_text(_item("Manto Élfico"))
    assert "não está no SRD" in pg.inner_text("#inv-msg")


def test_identificar_sem_conexao_mantem_o_botao(pagina):
    """Sem Open5e (padrão dos testes): erro visível, e o botão continua lá."""
    pg, _ = pagina
    _clicar(pg, f"{_item('Manto Élfico')} .inv-btn-identificar", 1200)
    assert pg.is_visible(f"{_item('Manto Élfico')} .inv-btn-identificar")
    assert "Identificar" == pg.inner_text(f"{_item('Manto Élfico')} .inv-btn-identificar").strip()
    assert "inv-msg-erro" in (pg.get_attribute("#inv-msg", "class") or "")
    assert "tente de novo" in pg.inner_text("#inv-msg")


def test_item_comum_nao_tem_identificar(pagina):
    pg, _ = pagina
    assert pg.locator(f"{_item('Corda de Cânhamo')} .inv-btn-identificar").count() == 0


# ---- usar fora do combate ----------------------------------------------------

def _mochila_com_consumiveis():
    import copy
    import capturar_telas as cap
    estado = copy.deepcopy(cap.MOCHILA)
    estado["characters"]["stelar"]["inventario"] += [
        {"nome": "Frasco de Ácido", "qtd": 1, "descricao": ""},
        {"nome": "Poção de Força de Gigante", "qtd": 1, "descricao": ""},
    ]
    estado["characters"]["helena"] = {"sheet": {"vida_atual": 5}, "status": "vivo"}
    estado["combat_state"] = {"is_active": False, "initiative_order": []}
    return estado


def test_pocao_tem_beber_e_dar_a_cada_um_do_grupo(navegador):
    pg, _ = navegador(_mochila_com_consumiveis())
    acoes = pg.inner_text(f"{_item('Poção de Cura')} .inv-item-acoes")
    assert "Beber" in acoes and "Dar a Helena" in acoes and "Dar a Natasha" in acoes


def test_dar_a_pocao_cura_quem_recebe_e_gasta_uma(navegador):
    pg, erros = navegador(_mochila_com_consumiveis())
    _clicar(pg, f"{_item('Poção de Cura')} .inv-btn-dar:has-text('Helena')", 1200)

    assert "Stelar deu a Helena Poção de Cura" in pg.inner_text("#inv-msg")
    assert "×" not in pg.inner_text(f"{_item('Poção de Cura')} .inv-item-nome"), "a poção não foi gasta"
    helena = pg.evaluate(
        "async () => (await (await authFetch((window.API || '') + "
        "'/api/heroes/sheet?personagem=Helena')).json()).personagem")
    assert helena["vida"]["atual"] > 5
    assert not erros, erros[:3]


def test_o_que_nao_da_para_usar_fica_travado_com_o_motivo_escrito(navegador):
    pg, _ = navegador(_mochila_com_consumiveis())
    acido = _item("Frasco de Ácido")
    assert pg.is_disabled(f"{acido} .inv-btn-usar")
    assert "só em combate" in pg.inner_text(f"{acido} .inv-uso-motivo")
    assert "mestre" in pg.inner_text(f"{_item('Poção de Força de Gigante')} .inv-uso-motivo")
    # Outra ação na tela reabilita os botões ao terminar; o travado não pode voltar.
    _clicar(pg, f"{_item('Tocha')} .inv-btn-largar")
    assert pg.is_disabled(f"{acido} .inv-btn-usar"), "o botão travado voltou a funcionar"


def test_em_combate_a_mochila_manda_para_a_tela_tatica(navegador):
    estado = _mochila_com_consumiveis()
    estado["combat_state"] = {"is_active": True, "initiative_order": ["Stelar"],
                              "current_turn_index": 0, "round": 1}
    pg, _ = navegador(estado)
    pocao = _item("Poção de Cura")
    assert pg.is_disabled(f"{pocao} .inv-btn-usar")
    assert "tela tática" in pg.inner_text(f"{pocao} .inv-uso-motivo")


# ---- carga, grupo, outras telas --------------------------------------------

def test_sobrecarregada_pinta_a_barra(navegador):
    import capturar_telas as cap
    pg, _ = navegador(cap.MOCHILA_PESADA)
    assert pg.is_visible(".inv-carga-cheia")
    assert "sobrecarregado" in pg.inner_text(".inv-carga-topo")


def test_trocar_de_personagem(pagina):
    pg, _ = pagina
    pg.select_option(".inv-quem-sel", "Helena")
    pg.wait_for_timeout(900)
    assert "Helena" in pg.inner_text(".inv-title")


def test_com_a_mochila_aberta_o_descanso_espera(pagina):
    """Nenhuma tela se empilha sobre outra aberta — a Mochila entrou na lista."""
    pg, _ = pagina
    import capturar_telas as cap
    _semear(pg.url_base, cap.DESCANSO_CURTO)
    pg.evaluate("window.sincronizarTelas()")
    pg.wait_for_timeout(1200)
    assert not pg.is_visible("#rest-overlay"), "o descanso abriu por cima da Mochila"

    _clicar(pg, ".inv-fechar", 300)
    pg.wait_for_selector("#rest-overlay:not(.hidden)", timeout=5000)


def test_sem_erro_no_console(pagina):
    pg, erros = pagina
    _clicar(pg, f"{_item('Escudo')} .inv-btn-equipar[data-slot='escudo']")
    _clicar(pg, f"{_slot('escudo')} .inv-btn-tirar")
    _clicar(pg, f"{_item('Tocha')} .inv-btn-largar")
    pg.select_option(".inv-quem-sel", "Helena")
    pg.wait_for_timeout(700)
    assert not erros, f"erros no console: {erros[:3]}"


def test_mobile_fechar_fica_na_tela(navegador):
    import capturar_telas as cap
    pg, _ = navegador(cap.MOCHILA, viewport={"width": 375, "height": 812})
    caixa = pg.locator(".inv-fechar").bounding_box()
    assert caixa and caixa["y"] + caixa["height"] <= pg.evaluate("window.innerHeight")
