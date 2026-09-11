"""
test_tela_de_nivel_navegador.py

O segundo teste de navegador do projeto, pelo mesmo motivo do primeiro: as
capturas provam que a tela DESENHA e `test_tela_de_nivel.py` prova que o motor
por trás dela funciona, mas nenhum dos dois prova que CLICAR funciona.

Aqui há um detalhe a mais que só o navegador pega. A tela de nível tem um
botão de rodapé que muda de FUNÇÃO conforme o estado: fica desabilitado
enquanto o personagem deve algo, vira atalho para o próximo do grupo quando
outro deve, e só conclui quando ninguém deve. Um rótulo que diz "Agora
Helena →" e conclui a cena seria mentira — e nenhum teste de motor veria isso.

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
def pagina(app_no_ar):
    from playwright.sync_api import sync_playwright
    import requests

    url, nome, cap = app_no_ar
    # Semeado por TESTE: o servidor é de módulo porque subir é caro, mas a
    # campanha não pode ser — um ponto de atributo gasto num teste faria o
    # seguinte começar com a conta errada.
    requests.post(f"{url}/__estado", json=cap.NIVEL, timeout=10)
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
        pg.wait_for_selector("#levelup-overlay:not(.hidden)", timeout=10000)
        yield pg, erros
        nav.close()


def _opcao(nome):
    return ("xpath=//button[contains(@class,'lvl-opcao')]"
            f"[.//span[text()={nome!r}]]")


def _attr_btn(nome):
    return ("xpath=//button[contains(@class,'lvl-attr-btn')]"
            f"[.//span[text()={nome!r}]]")


def _titulos(pg):
    return pg.eval_on_selector_all(
        ".lvl-bloco-titulo",
        "els => els.map(e => e.textContent.trim().split('\\n')[0].trim())")


def test_a_tela_abre_sozinha_quando_alguem_deve_escolha(pagina):
    """Sem `js` que a abra: o gatilho automático é a feature."""
    pg, _ = pagina
    assert pg.is_visible("#levelup-overlay")
    assert "Helena" in pg.inner_text(".lvl-title")


def test_as_tres_pendencias_aparecem(pagina):
    pg, _ = pagina
    titulos = " | ".join(_titulos(pg))
    assert "Estilo de Combate" in titulos
    assert "Arquétipo Marcial" in titulos
    assert "Incremento de Atributo" in titulos


def test_escolher_o_estilo_tira_o_bloco_da_tela(pagina):
    pg, _ = pagina
    pg.click(_opcao("Defesa"))
    pg.wait_for_timeout(700)

    assert "Estilo de Combate" not in " | ".join(_titulos(pg))
    assert "Defesa" in pg.inner_text("#lvl-msg")


def test_arquetipo_concede_a_sub_feature_e_some_da_lista(pagina):
    pg, _ = pagina
    pg.click(_opcao("Campeão"))
    pg.wait_for_timeout(700)

    assert "Arquétipo Marcial" not in " | ".join(_titulos(pg))
    assert "Campeão" in pg.inner_text("#lvl-msg")


def test_ponto_de_atributo_sobe_a_regua_do_topo(pagina):
    """
    A régua fica FORA do corpo que rola, de propósito: é a referência que o
    jogador consulta enquanto decide. Se ela não acompanhar o clique, a tela
    mente sobre o estado da ficha.
    """
    pg, _ = pagina
    regua = lambda: pg.inner_text(".lvl-atributos")     # noqa: E731
    assert "16" in regua()

    pg.click(_attr_btn("Força"))
    pg.wait_for_timeout(700)

    assert "17" in regua()
    assert "1 ponto" in pg.inner_text(".lvl-bloco-asi")


def test_gastar_os_dois_pontos_encerra_o_bloco(pagina):
    pg, _ = pagina
    pg.click(_attr_btn("Força"))
    pg.wait_for_timeout(500)
    pg.click(_attr_btn("Constituição"))
    pg.wait_for_timeout(700)

    assert "Incremento de Atributo" not in " | ".join(_titulos(pg))


def test_concluir_so_libera_quando_nada_esta_pendente(pagina):
    """
    Sair da tela devendo escolha é exatamente o que ela existe para impedir.
    O ✕ continua fechando — o que não pode é o botão de concluir fingir que
    está tudo resolvido.
    """
    pg, _ = pagina
    assert pg.is_disabled("#lvl-concluir")

    pg.click(_opcao("Defesa"));        pg.wait_for_timeout(400)
    pg.click(_opcao("Campeão"));       pg.wait_for_timeout(400)
    pg.click(_attr_btn("Força"));      pg.wait_for_timeout(400)
    assert pg.is_disabled("#lvl-concluir"), "ainda falta 1 ponto"

    pg.click(_attr_btn("Força"));      pg.wait_for_timeout(600)
    assert not pg.is_disabled("#lvl-concluir")


def test_o_rodape_leva_ao_proximo_em_vez_de_concluir_mentindo(pagina):
    """
    Com a Helena devendo, abrir a Stelar (que não deve nada) deixava um botão
    escrito "Falta escolher: Helena" que, clicado, CONCLUÍA a cena. Agora ele
    troca de personagem.
    """
    pg, _ = pagina
    pg.select_option(".lvl-quem-sel", "Stelar")
    pg.wait_for_timeout(700)

    assert pg.is_visible(".lvl-ok"), "Stelar não deveria ter pendência"
    botao = pg.inner_text("#lvl-concluir")
    assert "Helena" in botao and "Agora" in botao

    pg.click("#lvl-concluir")
    pg.wait_for_timeout(700)
    assert "Helena" in pg.inner_text(".lvl-title")
    assert pg.is_visible("#levelup-overlay"), "não podia ter concluído"


def test_atributo_no_teto_fica_desabilitado(pagina):
    """`opacity` é cosmética; o que vale é o atributo `disabled`."""
    pg, _ = pagina
    for _ in range(2):
        pg.click(_attr_btn("Força"))
        pg.wait_for_timeout(400)
    # Força foi a 18; nada no teto ainda, então nenhum botão desabilitado.
    assert pg.eval_on_selector_all(
        ".lvl-attr-btn[disabled]", "els => els.length") == 0


def test_a_tela_nao_solta_erro_no_console(pagina):
    pg, erros = pagina
    pg.click(_opcao("Duelo"))
    pg.wait_for_timeout(500)
    pg.select_option(".lvl-quem-sel", "Stelar")
    pg.wait_for_timeout(500)
    assert not erros, f"erros no console: {erros[:3]}"
