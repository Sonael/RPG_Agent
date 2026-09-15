"""
test_grimorio_navegador.py

`test_grimorio.py` prova as regras de magia no motor. Isto aqui prova o que só
o navegador vê: que o Grimório abre sozinho quando há vaga, que o botão
"Aprender" chama o motor e a vaga desce na hora, que o botão travado diz o
motivo, que filtro e busca funcionam, e que o atalho no cartão do grupo abre a
tela sem abrir junto o modal de edição.

A suíte roda com o SRD offline: o catálogo aqui é a lista local da classe.

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
    from playwright.sync_api import sync_playwright

    url, nome, cap = app_no_ar
    with sync_playwright() as pw:
        nav = pw.chromium.launch()

        def abrir(estado, esperar=".grm-magia", viewport=None, visitado=True):
            _semear(url, estado)
            ctx = nav.new_context(viewport=viewport or {"width": 1440, "height": 980})
            ctx.add_init_script(cap._script_de_semente(
                nome, "pergaminho", cap.HISTORICO, limpar_memoria_de_telas=False))
            if visitado:
                # O Grimório não abre sozinho na PRIMEIRA visita a uma campanha
                # (só pílula). Os testes do gatilho precisam de um navegador que
                # já esteve aqui e não viu nenhuma vaga: memória vazia, não
                # ausente.
                ctx.add_init_script(
                    "(() => { const k = 'rpg_telas::' + %s + '::grimorio_visto';"
                    " if (localStorage.getItem(k) === null) localStorage.setItem(k, '[]'); })()"
                    % json.dumps(nome))
            pg = ctx.new_page()
            erros = []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
            pg.goto(f"{url}/game.html", wait_until="networkidle")
            cap._sanear(pg)
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
def pagina(navegador):
    import capturar_telas as cap
    return navegador(cap.GRIMORIO)


def _magia(nome):
    return f".grm-magia[data-nome='{nome}']"


def _clicar(pg, seletor, espera=700):
    pg.click(seletor)
    pg.wait_for_timeout(espera)


def _vagas(pg):
    return pg.inner_text("#grm-vagas")


def _estado(pg):
    return pg.evaluate(
        "async () => (await (await authFetch((window.API || '') + '/api/grimoire/state?personagem=Helena')).json())")


# ---- abre ------------------------------------------------------------------

def test_abre_sozinho_quando_ha_vaga(pagina):
    pg, _ = pagina
    assert "Helena" in pg.inner_text(".grm-title")
    vagas = _vagas(pg)
    assert "1 a aprender" in vagas and "2 a aprender" in vagas


def test_primeira_visita_nao_abre_so_mostra_a_pilula(navegador):
    """
    Quase todo conjurador de campanha antiga tem vaga sobrando. Abrir na
    primeira visita faria o Grimório pular no carregamento de todo mundo, por
    uma vaga que ninguém acabou de ganhar.
    """
    import capturar_telas as cap
    pg, _ = navegador(cap.GRIMORIO, esperar=None, visitado=False)
    assert not pg.is_visible("#grimoire-overlay")
    assert pg.is_visible("#grm-reopen")


def test_subir_de_nivel_abre_de_novo(navegador):
    """A vaga que vem com o nível novo é nova: "Helena:4" nunca foi vista."""
    import capturar_telas as cap
    pg, _ = navegador(cap.GRIMORIO)
    _clicar(pg, ".grm-close", 900)
    assert not pg.is_visible("#grimoire-overlay")

    estado = copy.deepcopy(cap.GRIMORIO)
    estado["characters"]["helena"]["sheet"]["nivel"] = 4
    _semear(pg.url_base, estado)
    pg.evaluate("window.sincronizarTelas()")
    pg.wait_for_selector("#grimoire-overlay:not(.hidden)", timeout=5000)


def test_magia_aprendida_pelo_chat_nao_reabre(navegador):
    """Vaga que diminui (o mestre ensinou uma magia) não é vaga nova."""
    import capturar_telas as cap
    pg, _ = navegador(cap.GRIMORIO)
    _clicar(pg, ".grm-close", 900)

    estado = copy.deepcopy(cap.GRIMORIO)
    estado["characters"]["helena"]["habilidades"].append(
        {"nome": "Orientação", "descricao": "[Adivinhação] x", "custo_mana": 0, "nivel_magia": 0})
    _semear(pg.url_base, estado)
    pg.evaluate("window.sincronizarTelas()")
    pg.wait_for_timeout(1200)
    assert not pg.is_visible("#grimoire-overlay")


def test_sem_vaga_nao_abre(navegador):
    import capturar_telas as cap
    estado = copy.deepcopy(cap.GRIMORIO_CHEIO)
    estado["characters"]["helena"]["habilidades"].append(
        {"nome": "Orientação", "descricao": "[Adivinhação] x", "custo_mana": 0, "nivel_magia": 0})
    pg, _ = navegador(estado, esperar=None)
    assert not pg.is_visible("#grimoire-overlay")
    assert not pg.is_visible("#grm-reopen")


def test_conhecidas_agrupadas_por_circulo(pagina):
    pg, _ = pagina
    # inner_text devolve o texto já em caixa alta pelo CSS dos títulos.
    texto = pg.inner_text(".grm-conhecidas").lower()
    assert "truques" in texto and "1º círculo" in texto and "2º círculo" in texto
    texto = pg.inner_text(".grm-conhecidas")
    assert "Arma Espiritual" in texto


def test_ja_conhece_trava_o_botao(pagina):
    pg, _ = pagina
    botao = f"{_magia('Cura Ferimentos')} .grm-aprender-btn"
    assert pg.is_disabled(botao)
    assert "Já conhece" in pg.inner_text(botao)


# ---- aprender --------------------------------------------------------------

def test_aprender_chama_o_motor_e_a_vaga_desce(pagina):
    pg, _ = pagina
    _clicar(pg, f"{_magia('Orientação')} .grm-aprender-btn", 1000)

    assert "aprendeu" in pg.inner_text("#grm-msg")
    truques = pg.inner_text(".grm-vaga:first-child")
    assert "3 / 3" in truques and "a aprender" not in truques, truques
    nomes = [m["nome"] for m in _estado(pg)["personagem"]["conhecidas"]]
    assert "Orientação" in nomes, "a tela disse que aprendeu e a ficha não tem"
    assert "Orientação" in pg.inner_text(".grm-conhecidas")


def test_sem_vaga_de_magia_diz_por_que(navegador):
    import capturar_telas as cap
    pg, _ = navegador(cap.GRIMORIO_CHEIO)
    botoes = pg.eval_on_selector_all(
        ".grm-magia", "els => els.map(e => [e.dataset.nome, e.querySelector('.grm-aprender-btn').disabled,"
                      " e.querySelector('.grm-aprender-btn').textContent.trim()])")
    circulo = {n: (d, t) for n, d, t in botoes}
    assert circulo["Guia Divino"] == (True, "Sem vaga de magia")
    assert circulo["Orientação"][0] is False, "o truque ainda cabe"


def test_clique_forcado_no_botao_travado_nao_aprende(navegador):
    """O disabled é o que impede; o motor recusa também."""
    import capturar_telas as cap
    pg, _ = navegador(cap.GRIMORIO_CHEIO)
    pg.evaluate("window.Grimoire._aprender('Guia Divino')")
    pg.wait_for_timeout(900)
    assert "Erro" in pg.inner_text("#grm-msg")
    nomes = [m["nome"] for m in _estado(pg)["personagem"]["conhecidas"]]
    assert "Guia Divino" not in nomes


# ---- filtro e busca --------------------------------------------------------

def test_filtro_de_truques(pagina):
    pg, _ = pagina
    _clicar(pg, ".grm-filtro[data-nivel='0']", 900)
    circulos = pg.eval_on_selector_all(".grm-circulo", "els => els.map(e => e.textContent.trim())")
    assert circulos and set(circulos) == {"Truque"}, circulos
    assert "grm-filtro-on" in pg.get_attribute(".grm-filtro[data-nivel='0']", "class")


def test_busca_pelo_nome(pagina):
    pg, _ = pagina
    pg.fill("#grm-busca", "guia")
    pg.wait_for_timeout(1200)
    nomes = pg.eval_on_selector_all(".grm-magia", "els => els.map(e => e.dataset.nome)")
    assert nomes == ["Guia Divino"], nomes


# ---- concluir, pílula, atalho ----------------------------------------------

def test_concluir_depois_de_aprender_avisa_o_mestre(pagina):
    pg, _ = pagina
    _clicar(pg, f"{_magia('Orientação')} .grm-aprender-btn", 1000)
    _clicar(pg, "#grm-concluir", 700)
    assert not pg.is_visible("#grimoire-overlay")
    enviado = pg.evaluate("window.__enviado")
    assert any("[GRIMÓRIO RESOLVIDO NA TELA]" in e and "Orientação" in e for e in enviado), enviado


def test_aprender_e_fechar_nao_reabre_sozinho(pagina):
    """
    Na primeira versão a assinatura levava a quantidade de vagas: aprender a
    mudava, fechar disparava a fila e a fila reabria o Grimório na cara do
    jogador. Hoje duas coisas impedem isso — a assinatura só tem "Nome:nível"
    (test_assinatura_nao_muda_quando_a_vaga_so_diminui, no motor) e a tela
    aberta marca como visto o que mostra. Este teste é o comportamento que as
    duas garantem juntas.
    """
    pg, _ = pagina
    _clicar(pg, f"{_magia('Orientação')} .grm-aprender-btn", 1000)
    _clicar(pg, ".grm-close", 1200)
    assert not pg.is_visible("#grimoire-overlay"), "reabriu ao fechar"
    assert pg.is_visible("#grm-reopen"), "ainda há 2 magias a aprender: a pílula fica"


def test_concluir_sem_aprender_nao_manda_nada(pagina):
    pg, _ = pagina
    _clicar(pg, "#grm-concluir", 700)
    assert not pg.is_visible("#grimoire-overlay")
    assert not any("GRIMÓRIO" in e for e in pg.evaluate("window.__enviado"))


def test_fechar_e_recarregar_nao_reabre(pagina):
    pg, _ = pagina
    _clicar(pg, ".grm-close", 400)
    pg.reload(wait_until="networkidle")
    pg.wait_for_timeout(1500)
    assert not pg.is_visible("#grimoire-overlay"), "reabriu depois do F5"
    assert pg.is_visible("#grm-reopen")
    assert "Helena: magias a aprender" in pg.inner_text("#grm-reopen")


def test_atalho_da_visao_geral_abre_sem_o_modal(navegador):
    import capturar_telas as cap
    pg, _ = navegador(cap.GRIMORIO)
    _clicar(pg, ".grm-close", 400)
    _clicar(pg, "#sb-atalho-grupo", 400)
    atalho = "#grupo-overlay .grp-cartao[data-nome='Helena'] button:has-text('Grimório')"
    pg.wait_for_selector(atalho, state="visible", timeout=5000)
    _clicar(pg, atalho, 1000)
    assert pg.is_visible("#grimoire-overlay")
    assert not pg.is_visible("#edit-overlay"), "o clique abriu também o modal de edição"


def test_loja_espera_o_grimorio_fechar(navegador):
    import capturar_telas as cap
    pg, _ = navegador(_fundir(cap.LOJA, cap.GRIMORIO))
    pg.wait_for_timeout(1200)
    assert pg.is_visible("#grimoire-overlay")
    assert not pg.is_visible("#shop-overlay"), "a loja abriu por cima do grimório"
    _clicar(pg, ".grm-close", 300)
    pg.wait_for_selector("#shop-overlay:not(.hidden)", timeout=5000)


def test_sem_erro_no_console(pagina):
    pg, erros = pagina
    _clicar(pg, ".grm-filtro[data-nivel='1']", 700)
    _clicar(pg, ".grm-filtro[data-nivel='']", 700)
    _clicar(pg, f"{_magia('Orientação')} .grm-aprender-btn", 900)
    _clicar(pg, ".grm-close", 300)
    _clicar(pg, "#grm-reopen", 900)
    assert not erros, f"erros no console: {erros[:3]}"


def test_mobile_concluir_fica_na_tela(navegador):
    import capturar_telas as cap
    pg, _ = navegador(cap.GRIMORIO, viewport={"width": 375, "height": 812})
    caixa = pg.locator("#grm-concluir").bounding_box()
    altura = pg.evaluate("window.innerHeight")
    assert caixa and caixa["y"] + caixa["height"] <= altura, f"Concluir fora da tela: {caixa}"
