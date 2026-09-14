"""
test_historico_navegador.py

Ao reabrir a campanha, o chat não pode mostrar o que o jogo mandou ao mestre
no lugar do jogador (fechamento de tela, pedido de comando). A rolagem de dado
volta como uma linha curta, não como o texto técnico enviado ao mestre. E o
Grimório de um patrulheiro de nível 1 explica por que a lista está vazia.

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

_HISTORICO = [
    {"role": "user", "text": "Ataco o espreitador com a espada."},
    {"role": "user", "text": "[COMBATE RESOLVIDO NA TELA TÁTICA]\nDesfecho: VITÓRIA. Narre a luta INTEIRA\n— Eventos —\n[R1] Combate iniciado"},
    {"role": "assistant", "text": "A lâmina de Alden encontra a sombra."},
    {"role": "user", "text": "[DADO DO JOGADOR — rolado pelo sistema, não editável] 1d20: rolei 14, total 14"},
    {"role": "user", "text": "Salve o local \"Clareira\" usando save_location com todos os detalhes.", "interno": "comando"},
]


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


def test_reabrir_nao_mostra_mensagens_internas(app_no_ar):
    from playwright.sync_api import sync_playwright
    import server

    url, nome, cap = app_no_ar
    # O histórico chega à tela pela sessão, já marcado pelo servidor — é o
    # mesmo caminho da campanha gravada antes da marca existir.
    historico = server._historico_para_a_tela(_HISTORICO)
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        ctx = nav.new_context(viewport={"width": 1440, "height": 980})
        ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", historico))
        pg = ctx.new_page()
        erros = []
        pg.on("pageerror", lambda e: erros.append(str(e)))
        pg.goto(f"{url}/game.html", wait_until="networkidle")
        pg.wait_for_timeout(800)
        chat = pg.inner_text("#chat-history")
        nav.close()

    assert "Ataco o espreitador" in chat
    assert "lâmina de Alden" in chat      # a capitular do Mestre cola o "A" na palavra
    assert "COMBATE RESOLVIDO" not in chat and "Narre a luta" not in chat
    assert "save_location" not in chat
    assert "DADO DO JOGADOR" not in chat
    assert "Sua rolagem: 1d20: rolei 14, total 14" in chat
    assert not erros, erros[:3]
