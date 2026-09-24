"""
test_sessao_navegador.py

A renovação da sessão numa página de verdade.

O authfetch_refresh.mjs prova a LÓGICA num contexto isolado; aqui se prova a
FIAÇÃO, que é o que falhou na partida real: a tela ficou uma hora aberta, o
access token venceu parado, e o primeiro clique do jogador encontrou um
refresh token já gasto — login no meio da cena.

Três coisas só a página mostra:
  • o token perto do vencimento é renovado ANTES de a primeira chamada sair;
  • voltar para a aba dispara a renovação (o ouvinte do visibilitychange
    existe e está ligado);
  • o navegador tem navigator.locks, ou seja, a trava entre abas é a de
    verdade e não o remendo para navegador velho.

Depende do Playwright, que não está em requirements-dev.txt. Sem ele o arquivo
é pulado:

    pip install playwright && playwright install chromium
"""
import base64
import json
import sys
import time
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

pytest.importorskip("playwright.sync_api",
                    reason="Playwright não instalado — veja o docstring")

sys.path.insert(0, str(RAIZ / "scripts"))

pytestmark = pytest.mark.slow


def _jwt(segundos_restantes: int) -> str:
    """Um JWT de mentira com o exp que o utils.js lê. A assinatura não importa
    aqui: quem confere de verdade é o Supabase."""
    corpo = base64.urlsafe_b64encode(
        json.dumps({"exp": int(time.time()) + segundos_restantes}).encode()
    ).decode().rstrip("=")
    return f"cabeca.{corpo}.assinatura"


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
def abrir(app_no_ar):
    from playwright.sync_api import sync_playwright

    url, nome, cap = app_no_ar
    with sync_playwright() as pw:
        nav = pw.chromium.launch()

        def _abrir(segundos_do_token):
            ctx = nav.new_context(viewport={"width": 1440, "height": 980})
            ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO))
            # Depois da semente, de propósito: ela grava um token que não é
            # JWT (e que portanto nunca "vence"). Aqui o token passa a ter
            # prazo, que é o caso do jogo de verdade.
            ctx.add_init_script(
                "try { localStorage.setItem('rpg_access_token', "
                f"{json.dumps(_jwt(segundos_do_token))}); "
                "localStorage.setItem('rpg_refresh_token', 'R1'); } catch (e) {}")

            pg = ctx.new_page()
            erros = []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)

            renovacoes = []

            def _responder(rota):
                renovacoes.append(rota.request.post_data)
                rota.fulfill(status=200, content_type="application/json",
                             body=json.dumps({"ok": True,
                                              "access_token": _jwt(3600),
                                              "refresh_token": "R2"}))

            pg.route("**/api/auth/refresh", _responder)
            pg.goto(f"{url}/game.html", wait_until="networkidle")
            cap._sanear(pg)
            pg.wait_for_selector("#sidebar", state="attached", timeout=8000)
            pg.wait_for_timeout(300)
            return pg, erros, renovacoes

        yield _abrir
        nav.close()


def test_o_navegador_tem_a_trava_entre_abas(abrir):
    """Sem navigator.locks a segunda aba volta a poder gastar o mesmo papel.
    Se um dia isto falhar, o remendo assume — e o bug volta a ser possível."""
    pg, erros, _ = abrir(3600)
    assert pg.evaluate("() => !!(navigator.locks && navigator.locks.request)")
    # O prazo da espera depende do AbortSignal.timeout: sem ele, uma aba
    # congelada segurando a trava penduraria as outras.
    assert pg.evaluate("() => typeof AbortSignal !== 'undefined'"
                       " && typeof AbortSignal.timeout === 'function'")
    assert not erros, erros[:3]


def test_token_perto_de_vencer_renova_antes_de_a_chamada_sair(abrir):
    pg, erros, renovacoes = abrir(30)          # dentro da margem de 120s
    assert len(renovacoes) >= 1, "a página não renovou sozinha"
    # Uma renovação só, mesmo com a tela abrindo várias chamadas de uma vez.
    assert len(renovacoes) == 1, renovacoes
    assert json.loads(renovacoes[0])["refresh_token"] == "R1"
    # E o token novo ficou guardado no lugar do velho.
    assert pg.evaluate("() => localStorage.getItem('rpg_access_token')") != "R1"
    assert pg.evaluate("() => localStorage.getItem('rpg_refresh_token')") == "R2"
    assert not erros, erros[:3]


def test_token_longe_do_fim_nao_gasta_renovacao(abrir):
    pg, erros, renovacoes = abrir(3600)
    assert renovacoes == [], renovacoes
    assert not erros, erros[:3]


def test_voltar_para_a_aba_renova_a_sessao(abrir):
    """O caso exato da partida: a tela fica aberta, o token vence parado, e o
    jogador volta. A renovação tem de acontecer no VOLTAR, não no clique."""
    pg, erros, renovacoes = abrir(3600)
    assert renovacoes == []

    # O tempo passou: o que está guardado agora está a segundos de vencer.
    pg.evaluate("() => localStorage.setItem('rpg_access_token', "
                f"{json.dumps(_jwt(10))})")
    pg.evaluate("() => document.dispatchEvent(new Event('visibilitychange'))")
    pg.wait_for_timeout(500)

    assert len(renovacoes) == 1, renovacoes
    assert pg.evaluate("() => localStorage.getItem('rpg_refresh_token')") == "R2"
    assert not erros, erros[:3]
