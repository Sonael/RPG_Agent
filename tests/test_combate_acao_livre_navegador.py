"""
test_combate_acao_livre_navegador.py

A Ação Livre acontece dentro da tela de combate.

O botão fechava a tela tática e mandava o jogador escrever no chat: para
pedir uma manobra que o motor não tem botão — empurrar uma mesa, cortar a
corda do lustre —, ele perdia o campo de batalha de vista. Agora o pedido e a
arbitragem do Mestre ficam no próprio painel de ações, e o chat continua
recebendo os dois, que é onde a crônica mora.

O Mestre é o agente, que não roda nos testes: aqui `window.sendToAgent` é
trocada por uma dublê que devolve uma fala. O que se testa é a tela.

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


# A dublê do Mestre: guarda o que recebeu e devolve a fala pelo callback,
# do mesmo jeito que o stream faz com o evento de texto.
DUBLE = """(fala) => {
  window.__mestre = [];
  window.sendToAgent = async (texto, registrar, interno, aoTexto) => {
    window.__mestre.push({texto, registrar, interno});
    await new Promise(r => setTimeout(r, 50));
    if (typeof aoTexto === 'function') aoTexto(fala);
  };
}"""


@pytest.fixture
def abrir_jogo(app_no_ar):
    from playwright.sync_api import sync_playwright
    import requests

    url, nome, cap = app_no_ar
    with sync_playwright() as pw:
        nav = pw.chromium.launch()

        def abrir(estado, fala="**O goblin cai de costas** com a mesa em cima."):
            requests.post(f"{url}/__estado", json=estado, timeout=10)
            ctx = nav.new_context(viewport={"width": 1440, "height": 980})
            ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO))
            pg = ctx.new_page()
            erros = []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
            pg.goto(f"{url}/game.html", wait_until="networkidle")
            pg.wait_for_selector("#combat-overlay:not(.hidden)", timeout=8000)
            pg.wait_for_selector("#cbt-buttons button:has-text('Ação Livre')", timeout=8000)
            pg.evaluate(DUBLE, fala)
            return pg, erros

        yield abrir, cap
        nav.close()


def _abrir_painel(pg):
    pg.click("#cbt-buttons button:has-text('Ação Livre')")
    pg.wait_for_selector("#cbt-livre:not(.hidden) #cbt-livre-texto", timeout=3000)


def test_pedido_e_resposta_sem_fechar_a_tela(abrir_jogo):
    abrir, cap = abrir_jogo
    pg, erros = abrir(copy.deepcopy(cap.COMBATE_ZONAS))

    _abrir_painel(pg)
    pg.fill("#cbt-livre-texto", "empurro a mesa contra o goblin")
    pg.click("#cbt-livre-enviar")

    pg.wait_for_function(
        "() => /cai de costas/.test(document.getElementById('cbt-livre-resposta').textContent)",
        timeout=5000)
    # A tela continua aberta e o campo de batalha, à vista.
    assert pg.is_visible("#combat-overlay #cbt-frame")
    assert not pg.evaluate("() => document.getElementById('combat-overlay').classList.contains('hidden')")
    # O negrito do Mestre chega formatado, não como asteriscos.
    assert "**" not in pg.inner_text("#cbt-livre-resposta")
    assert pg.locator("#cbt-livre-resposta strong").count() >= 1

    # O Mestre recebeu o texto do jogador, e ele foi registrado na crônica.
    recado = pg.evaluate("() => window.__mestre")
    assert len(recado) == 1
    assert recado[0]["texto"] == "empurro a mesa contra o goblin"
    assert recado[0]["registrar"] is True
    # Interno vazio: a ação livre É fala do jogador, e reaparece no histórico.
    assert not recado[0]["interno"]
    assert "empurro a mesa" in pg.inner_text("#chat-history")
    assert not erros, erros[:3]


def test_enter_envia_e_escape_fecha(abrir_jogo):
    abrir, cap = abrir_jogo
    pg, erros = abrir(copy.deepcopy(cap.COMBATE_ZONAS))

    _abrir_painel(pg)
    pg.fill("#cbt-livre-texto", "chuto o braseiro na direção deles")
    pg.press("#cbt-livre-texto", "Enter")
    pg.wait_for_function("() => (window.__mestre || []).length === 1", timeout=5000)

    _abrir_painel(pg)
    pg.press("#cbt-livre-texto", "Escape")
    pg.wait_for_function(
        "() => document.getElementById('cbt-livre').classList.contains('hidden')",
        timeout=3000)
    assert not erros, erros[:3]


def test_pedido_vazio_nao_incomoda_o_mestre(abrir_jogo):
    abrir, cap = abrir_jogo
    pg, erros = abrir(copy.deepcopy(cap.COMBATE_ZONAS))

    _abrir_painel(pg)
    pg.fill("#cbt-livre-texto", "   ")
    pg.click("#cbt-livre-enviar")
    pg.wait_for_timeout(300)
    assert pg.evaluate("() => (window.__mestre || []).length") == 0
    assert pg.is_hidden("#cbt-livre-resposta")
    assert not erros, erros[:3]


def test_escolher_alvo_fecha_o_painel_da_acao_livre(abrir_jogo):
    """Os dois painéis dividem o mesmo espaço: um abre, o outro sai."""
    abrir, cap = abrir_jogo
    pg, erros = abrir(copy.deepcopy(cap.COMBATE_ZONAS))

    _abrir_painel(pg)
    pg.click("#cbt-buttons button:has-text('Atacar')")
    pg.wait_for_selector("#cbt-targets:not(.hidden)", timeout=3000)
    assert pg.is_hidden("#cbt-livre-texto")
    assert not erros, erros[:3]


def test_fala_do_mestre_chega_pelo_stream_de_verdade(abrir_jogo):
    """
    Sem dublê: /api/chat é interceptada e devolve o mesmo SSE que o servidor
    manda. Prova o caminho inteiro — o `game.js` entrega a fala a quem pediu,
    e ela aparece no painel e no chat.
    """
    abrir, cap = abrir_jogo
    pg, erros = abrir(copy.deepcopy(cap.COMBATE_ZONAS))
    pg.evaluate("() => { delete window.sendToAgent; }")
    pg.reload(wait_until="networkidle")
    pg.wait_for_selector("#cbt-buttons button:has-text('Ação Livre')", timeout=8000)

    corpo = ('data: {"type": "text", "content": "A corda **estala** e o lustre desaba."}\n\n'
             'data: {"type": "done"}\n\n')
    pg.route("**/api/chat", lambda rota: rota.fulfill(
        status=200, headers={"Content-Type": "text/event-stream"}, body=corpo))

    _abrir_painel(pg)
    pg.fill("#cbt-livre-texto", "corto a corda do lustre")
    pg.click("#cbt-livre-enviar")

    pg.wait_for_function(
        "() => /lustre desaba/.test(document.getElementById('cbt-livre-resposta').textContent)",
        timeout=5000)
    assert "lustre desaba" in pg.inner_text("#chat-history")
    assert not erros, erros[:3]


def test_a_tela_volta_do_motor_depois_da_arbitragem(abrir_jogo):
    """
    O Mestre pode ter aplicado dano ou condição: a tela não pode ficar com a
    foto velha. Depois da resposta, o combate é relido do servidor.
    """
    abrir, cap = abrir_jogo
    pg, erros = abrir(copy.deepcopy(cap.COMBATE_ZONAS))
    pg.evaluate("""() => {
        window.__leituras = 0;
        const antigo = window.fetch;
        window.fetch = (...args) => {
            if (String(args[0]).includes('/api/combat/state')) window.__leituras++;
            return antigo(...args);
        };
    }""")

    _abrir_painel(pg)
    pg.fill("#cbt-livre-texto", "grito para assustar os goblins")
    pg.click("#cbt-livre-enviar")
    pg.wait_for_function("() => (window.__leituras || 0) >= 1", timeout=5000)
    assert not erros, erros[:3]
