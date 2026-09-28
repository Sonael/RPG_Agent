"""
test_lista_de_modelos.py

A lista de modelos parou de carregar quando a chave de API saiu do navegador.

O menu pede a lista no arranque, e loadGeminiModels() começa perguntando
"existe chave?". Enquanto a chave morava no localStorage, a resposta era
síncrona e estava lá. Depois que ela passou a viver no servidor, a resposta
virou uma ida à rede — e no instante do arranque ainda não chegou. A lista
caía na de reserva do HTML com "Salve a chave do Google para carregar a lista
de modelos atualizada", mesmo com a chave guardada.

Quem sabe a resposta é loadApiKeys(), e é de lá que a lista passa a ser
pedida.

Depende do Playwright, que não está em requirements-dev.txt. Sem ele o arquivo
é pulado:

    pip install playwright && playwright install chromium
"""
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
def menu(app_no_ar):
    """
    O menu com uma chave JÁ guardada na conta — o cenário do defeito. A rota
    das chaves é respondida aqui porque a bancada não tem a tabela.
    """
    from playwright.sync_api import sync_playwright

    url, nome, cap = app_no_ar
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        ctx = nav.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO))

        def responder_chaves(rota):
            rota.fulfill(status=200, content_type="application/json",
                         body=json.dumps({"ok": True, "chaves": {
                             "google": {"definida": True, "fim": "6ivg"},
                             "deepseek": {"definida": False, "fim": ""}}}))

        ctx.route("**/api/user/keys", responder_chaves)

        pedidos = []
        ctx.on("request", lambda r: pedidos.append(r.url))

        pg = ctx.new_page()
        erros = []
        pg.on("pageerror", lambda e: erros.append(str(e)))
        pg.goto(f"{url}/menu.html", wait_until="networkidle")
        yield pg, pedidos, erros
        nav.close()


def test_com_a_chave_guardada_a_lista_e_pedida(menu):
    """
    O defeito em uma linha: a chave estava guardada e o pedido nunca saía.
    """
    pg, pedidos, erros = menu
    pg.wait_for_timeout(600)
    assert any("/api/gemini/models" in u for u in pedidos), (
        "a lista de modelos não foi pedida mesmo com a chave guardada"
    )
    assert not erros, erros[:3]


def test_o_menu_nao_pede_a_lista_antes_de_saber_da_chave(menu):
    """
    A ordem é o defeito inteiro: perguntar "existe chave?" antes de a resposta
    chegar dá sempre "não". O pedido das chaves vem primeiro.
    """
    pg, pedidos, _ = menu
    pg.wait_for_timeout(600)
    chaves = next(i for i, u in enumerate(pedidos) if "/api/user/keys" in u)
    modelos = [i for i, u in enumerate(pedidos) if "/api/gemini/models" in u]
    assert modelos, "a lista nunca foi pedida"
    assert modelos[-1] > chaves, "a lista foi pedida antes de saber da chave"


def test_a_tela_nao_pede_para_salvar_uma_chave_que_ja_existe(menu):
    """O texto que aparecia na tela quando o defeito estava presente."""
    pg, _, _ = menu
    pg.wait_for_timeout(600)
    status = pg.text_content("#apikeys-status") or ""
    assert "Salve a chave do Google" not in status, status


def test_o_arranque_delega_o_pedido_a_quem_sabe_da_chave():
    """
    Trava de ordem no fonte: se alguém voltar a pedir a lista só no arranque,
    o defeito volta em silêncio — a tela apenas mostra a lista de reserva.
    """
    html = (RAIZ / "static" / "menu.html").read_text(encoding="utf-8")
    assert "loadGeminiModels()" in html, (
        "loadApiKeys precisa disparar a lista depois de saber da chave"
    )
    i_resumo = html.index("_pintarStatusDaChave('deepseek'")
    i_lista = html.index("if (typeof loadGeminiModels === 'function') loadGeminiModels();")
    assert i_resumo < i_lista, "a lista foi pedida antes de o estado ser aplicado"
