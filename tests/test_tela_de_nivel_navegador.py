"""
test_tela_de_nivel_navegador.py

O segundo teste de navegador do projeto, pelo mesmo motivo do primeiro: as
capturas provam que a tela DESENHA e `test_tela_de_nivel.py` prova que o motor
por trás dela funciona, mas nenhum dos dois prova que CLICAR funciona.

Aqui há mais comportamento que só o navegador vê do que em qualquer outra
tela, porque o incremento de atributo funciona como o wizard de criação:

  • + e − mexem num RASCUNHO local; nada vai ao servidor até "Confirmar";
  • o − só retira ponto posto AGORA — nunca desce abaixo do que a ficha tinha;
  • o + trava quando o pool acaba ou o atributo chega a 20;
  • o rascunho não pode sobreviver a uma confirmação e reaparecer no próximo
    incremento do mesmo personagem.

Nenhuma dessas quatro coisas passa pelo motor antes do clique final, então
nenhum teste de motor as enxerga.

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
    """Merge recursivo, o mesmo que /__estado faz: dicts se fundem."""
    r = copy.deepcopy(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(r.get(k), dict):
            r[k] = _fundir(r[k], v)
        else:
            r[k] = copy.deepcopy(v)
    return r


@pytest.fixture
def navegador(app_no_ar):
    """
    Abre o jogo num estado qualquer, SEMPRE em contexto novo do navegador.

    Contexto novo porque as telas agora lembram "já abri" no localStorage: um
    teste que abrisse a tela de nível deixaria a memória para o seguinte, e o
    seguinte veria a tela não abrir sem motivo nenhum na tela.
    """
    from playwright.sync_api import sync_playwright

    url, nome, cap = app_no_ar
    with sync_playwright() as pw:
        nav = pw.chromium.launch()

        def abrir(estado, esperar="#levelup-overlay:not(.hidden)"):
            # Semeado por abertura: o servidor é de módulo porque subir é caro,
            # mas a campanha não pode ser.
            _semear(url, estado)
            ctx = nav.new_context(viewport={"width": 1440, "height": 980})
            # SEM limpar a memória de telas: é justamente ela que alguns testes
            # daqui provam (recarregar não reabre).
            ctx.add_init_script(cap._script_de_semente(
                nome, "pergaminho", cap.HISTORICO, limpar_memoria_de_telas=False))
            pg = ctx.new_page()
            erros = []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
            pg.goto(f"{url}/game.html", wait_until="networkidle")
            cap._sanear(pg)
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
    return navegador(cap.NIVEL)


# ---- seletores -------------------------------------------------------------

def _opcao(nome):
    return ("xpath=//button[contains(@class,'lvl-opcao')]"
            f"[.//span[text()={nome!r}]]")


def _mais(attr):
    return f".lvl-step[data-attr='{attr}'] .lvl-step-mais"


def _menos(attr):
    return f".lvl-step[data-attr='{attr}'] .lvl-step-menos"


def _valor_step(pg, attr):
    return int(pg.inner_text(f".lvl-step[data-attr='{attr}'] .lvl-step-valor"))


def _regua(pg, sigla_ou_nome):
    """Valor na régua do topo, que é a FICHA — não o rascunho."""
    return pg.evaluate(
        """(alvo) => {
            for (const el of document.querySelectorAll('.lvl-attr')) {
              const nome = el.querySelector('.lvl-attr-nome').textContent.trim();
              if (nome.toLowerCase() === alvo.toLowerCase())
                return parseInt(el.querySelector('.lvl-attr-valor').textContent, 10);
            }
            return null;
        }""", sigla_ou_nome)


def _titulos(pg):
    return " | ".join(pg.eval_on_selector_all(
        ".lvl-bloco-titulo",
        "els => els.map(e => e.textContent.trim().split('\\n')[0].trim())"))


def _clicar(pg, seletor, espera=250):
    pg.click(seletor)
    pg.wait_for_timeout(espera)


# ---- a tela ----------------------------------------------------------------

def test_a_tela_abre_sozinha_quando_alguem_deve_escolha(pagina):
    """Sem `js` que a abra: o gatilho automático é a feature."""
    pg, _ = pagina
    assert pg.is_visible("#levelup-overlay")
    assert "Helena" in pg.inner_text(".lvl-title")


def test_as_tres_pendencias_aparecem(pagina):
    pg, _ = pagina
    t = _titulos(pg)
    assert "Estilo de Combate" in t
    assert "Arquétipo Marcial" in t
    assert "Incremento de Atributo" in t


def test_escolher_o_estilo_tira_o_bloco_da_tela(pagina):
    pg, _ = pagina
    _clicar(pg, _opcao("Defesa"), 700)
    assert "Estilo de Combate" not in _titulos(pg)
    assert "Defesa" in pg.inner_text("#lvl-msg")


def test_arquetipo_concede_a_sub_feature_e_some_da_lista(pagina):
    pg, _ = pagina
    _clicar(pg, _opcao("Campeão"), 700)
    assert "Arquétipo Marcial" not in _titulos(pg)
    assert "Campeão" in pg.inner_text("#lvl-msg")


# ---- incremento: o stepper -------------------------------------------------

def test_o_menos_nasce_desabilitado_em_todos(pagina):
    """Sem ponto posto, não há o que retirar: o piso é a ficha."""
    pg, _ = pagina
    estados = pg.eval_on_selector_all(".lvl-step-menos", "els => els.map(e => e.disabled)")
    assert len(estados) == 6 and all(estados), estados


def test_o_mais_mexe_so_no_rascunho(pagina):
    """
    O clique no + NÃO grava: o stepper mostra 17, mas a régua do topo — que é a
    ficha — continua em 16. Só o Confirmar leva ao servidor.
    """
    pg, _ = pagina
    _clicar(pg, _mais("forca"))

    assert _valor_step(pg, "forca") == 17
    assert _regua(pg, "Força") == 16, "o + gravou na ficha sem confirmar"
    assert "16 +1" in pg.inner_text(".lvl-step[data-attr='forca'] .lvl-step-extra")
    assert "1 / 2" in pg.inner_text("#lvl-asi-contagem")


def test_o_menos_retira_e_para_no_valor_da_ficha(pagina):
    pg, _ = pagina
    _clicar(pg, _mais("forca"))
    _clicar(pg, _mais("forca"))
    assert _valor_step(pg, "forca") == 18

    _clicar(pg, _menos("forca"))
    _clicar(pg, _menos("forca"))

    assert _valor_step(pg, "forca") == 16
    assert pg.is_disabled(_menos("forca")), "− deixou descer abaixo do que a ficha tinha"

    # Forçar o clique no − desabilitado também não pode descer.
    pg.eval_on_selector(_menos("forca"), "el => el.click()")
    pg.wait_for_timeout(250)
    assert _valor_step(pg, "forca") == 16


def test_o_mais_trava_quando_o_pool_acaba(pagina):
    pg, _ = pagina
    _clicar(pg, _mais("forca"))
    _clicar(pg, _mais("constituicao"))

    estados = pg.eval_on_selector_all(".lvl-step-mais", "els => els.map(e => e.disabled)")
    assert all(estados), f"+ ativo com o pool zerado: {estados}"


def test_o_mais_trava_no_teto_de_20(pagina):
    pg, _ = pagina
    import capturar_telas as cap
    estado = copy.deepcopy(cap.NIVEL)
    estado["characters"]["helena"]["sheet"]["forca"] = 19
    _semear(pg.url_base, estado)
    pg.evaluate("window.LevelUp.sync()")
    pg.wait_for_timeout(700)

    _clicar(pg, _mais("forca"))
    assert _valor_step(pg, "forca") == 20
    assert pg.is_disabled(_mais("forca")), "+ ativo com o atributo em 20"
    assert not pg.is_disabled(_mais("destreza")), "o teto de um travou os outros"


def test_confirmar_so_libera_com_todos_os_pontos(pagina):
    """Um ponto esquecido viraria pendência que o jogador não entenderia."""
    pg, _ = pagina
    assert pg.is_disabled(".lvl-asi-confirmar")
    _clicar(pg, _mais("forca"))
    assert pg.is_disabled(".lvl-asi-confirmar")
    assert "mais 1 ponto" in pg.inner_text(".lvl-asi-confirmar")
    _clicar(pg, _mais("carisma"))
    assert not pg.is_disabled(".lvl-asi-confirmar")


def test_confirmar_grava_e_a_regua_sobe(pagina):
    pg, _ = pagina
    _clicar(pg, _mais("forca"))
    _clicar(pg, _mais("constituicao"))
    _clicar(pg, ".lvl-asi-confirmar", 900)

    assert _regua(pg, "Força") == 17
    assert _regua(pg, "Constituição") == 16
    assert "Incremento de Atributo" not in _titulos(pg)


def test_desfazer_zera_o_rascunho(pagina):
    pg, _ = pagina
    _clicar(pg, _mais("forca"))
    _clicar(pg, _mais("destreza"))
    _clicar(pg, ".lvl-asi-desfazer")

    assert _valor_step(pg, "forca") == 16
    assert _valor_step(pg, "destreza") == 14
    assert "0 / 2" in pg.inner_text("#lvl-asi-contagem")


def test_talento_bloqueado_enquanto_ha_ponto_no_rascunho(pagina):
    """Com +1 distribuído, 'trocar por talento' seria ambíguo sobre esse ponto."""
    pg, _ = pagina
    assert not pg.is_disabled(".lvl-talento-btn")
    _clicar(pg, _mais("sabedoria"))
    assert pg.is_disabled(".lvl-talento-btn")
    assert pg.is_disabled("#lvl-talento-nome")


def test_o_rascunho_nao_reaparece_no_proximo_incremento(pagina):
    """
    Depois de confirmar, o bloco some. A primeira versão guardava o rascunho
    velho e, no próximo incremento do mesmo personagem (também de 2 pontos),
    ele voltava com os pontos já postos.
    """
    pg, _ = pagina
    import capturar_telas as cap
    _clicar(pg, _mais("forca"))
    _clicar(pg, _mais("forca"))
    _clicar(pg, ".lvl-asi-confirmar", 900)
    assert "Incremento de Atributo" not in _titulos(pg)

    # Um novo incremento de 2 pontos para a mesma Helena.
    _semear(pg.url_base, cap.NIVEL)
    pg.evaluate("window.LevelUp.sync()")
    pg.wait_for_timeout(800)

    assert "Incremento de Atributo" in _titulos(pg)
    assert "0 / 2" in pg.inner_text("#lvl-asi-contagem"), "rascunho antigo voltou"
    assert _valor_step(pg, "forca") == 16


# ---- rodapé ----------------------------------------------------------------

def test_concluir_so_libera_quando_nada_esta_pendente(pagina):
    """
    Sair da tela devendo escolha é exatamente o que ela existe para impedir.
    O ✕ continua fechando — o que não pode é o botão de concluir fingir que
    está tudo resolvido.
    """
    pg, _ = pagina
    assert pg.is_disabled("#lvl-concluir")

    _clicar(pg, _opcao("Defesa"), 500)
    _clicar(pg, _opcao("Campeão"), 500)
    _clicar(pg, _mais("forca"))
    assert pg.is_disabled("#lvl-concluir"), "ainda falta 1 ponto"

    _clicar(pg, _mais("forca"))
    assert pg.is_disabled("#lvl-concluir"), "ponto no rascunho não é ponto gasto"

    _clicar(pg, ".lvl-asi-confirmar", 900)
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

    _clicar(pg, "#lvl-concluir", 700)
    assert "Helena" in pg.inner_text(".lvl-title")
    assert pg.is_visible("#levelup-overlay"), "não podia ter concluído"


def test_a_tela_nao_solta_erro_no_console(pagina):
    pg, erros = pagina
    _clicar(pg, _opcao("Duelo"), 500)
    _clicar(pg, _mais("forca"))
    _clicar(pg, _menos("forca"))
    _clicar(pg, _mais("destreza"))
    _clicar(pg, ".lvl-asi-desfazer")
    pg.select_option(".lvl-quem-sel", "Stelar")
    pg.wait_for_timeout(500)
    assert not erros, f"erros no console: {erros[:3]}"


# ---- quando a tela abre ----------------------------------------------------

def test_fechar_e_recarregar_nao_reabre(pagina):
    """
    A memória de "já abri por estas pendências" vivia numa variável: fechar no
    ✕ e dar F5 reabria a tela. Agora fica no localStorage, por campanha.
    """
    pg, _ = pagina
    _clicar(pg, ".lvl-close", 400)
    pg.reload(wait_until="networkidle")
    pg.wait_for_timeout(1500)

    assert not pg.is_visible("#levelup-overlay"), "reabriu depois do F5"
    assert pg.is_visible("#lvl-reopen"), "a pílula tinha que continuar lá"


def test_pendencia_igual_volta_a_abrir_depois_de_resolvida(pagina):
    """
    Defeito latente da versão anterior: resolvida a pendência, a memória
    guardava a assinatura antiga. Se a próxima pendência saísse IGUAL — o
    incremento de 2 pontos do nível 8 depois do do nível 4 —, a tela nunca
    mais abria sozinha.
    """
    pg, _ = pagina
    import capturar_telas as cap
    _clicar(pg, _opcao("Defesa"), 500)
    _clicar(pg, _opcao("Campeão"), 500)
    _clicar(pg, _mais("forca"))
    _clicar(pg, _mais("forca"))
    _clicar(pg, ".lvl-asi-confirmar", 900)
    _clicar(pg, ".lvl-close", 900)          # dispara a fila: nada pendente, esquece

    _semear(pg.url_base, cap.NIVEL)         # as MESMAS pendências de novo
    pg.evaluate("window.sincronizarTelas()")
    pg.wait_for_selector("#levelup-overlay:not(.hidden)", timeout=5000)


def test_loja_espera_a_tela_de_nivel_fechar(navegador):
    """
    Na forja, com escolha de nível pendente, as duas telas abriam juntas, uma
    empilhada na outra. Agora a fila abre a de nível primeiro — a escolha muda
    a compra — e a loja só quando ela fecha.
    """
    import capturar_telas as cap
    pg, _ = navegador(_fundir(cap.NIVEL, cap.LOJA))
    pg.wait_for_timeout(1200)

    assert pg.is_visible("#levelup-overlay")
    assert not pg.is_visible("#shop-overlay"), "a loja abriu por cima da tela de nível"

    _clicar(pg, ".lvl-close", 300)
    pg.wait_for_selector("#shop-overlay:not(.hidden)", timeout=5000)
    assert not pg.is_visible("#levelup-overlay")


def test_selo_de_nivel_sobe_pelo_motor_e_abre_a_tela(navegador):
    """
    O selo "⬆️ NÍVEL!" da ficha gravava o nível direto, com PV calculados no
    navegador, sem as habilidades da classe nem o contador de incremento — e
    abria o modal de edição. Agora sobe pelo grant_xp e abre a tela de nível.
    """
    import capturar_telas as cap
    estado = copy.deepcopy(cap.NIVEL)
    sh = estado["characters"]["helena"]["sheet"]
    sh.update({"nivel": 3, "xp": 2800, "xp_proximo": 2700, "asi_pontos_gastos": 0,
               "feature_choices": {"Estilo de Combate": "Defesa",
                                   "Arquétipo Marcial": "Campeão"}})

    pg, _ = navegador(estado, esperar=None)
    assert not pg.is_visible("#levelup-overlay"), "nada pendente antes de subir"

    # O selo mora no cartão do grupo, na aba Enciclopédia — o caminho do jogador.
    _clicar(pg, ".tab-btn[data-tab='enciclopedia']", 300)
    pg.wait_for_selector(".levelup-badge", state="visible", timeout=5000)
    _clicar(pg, ".levelup-badge", 400)
    popup = pg.inner_text("#levelup-popup")
    assert "rolado" in popup, "o popup ainda promete PV calculado no navegador"

    _clicar(pg, "#levelup-popup-confirmar", 300)
    pg.wait_for_selector("#levelup-overlay:not(.hidden)", timeout=5000)
    pg.wait_for_timeout(500)

    assert "nível 4" in pg.inner_text(".lvl-classe").lower()
    assert "Incremento de Atributo" in _titulos(pg), "contador de incremento não começou"
    assert not pg.is_visible("#edit-overlay"), "o modal de edição abriu junto"


def test_seletor_de_personagem_mostra_o_nome(pagina):
    """Mesma classe de defeito do seletor da loja: medir, não só clicar."""
    pg, _ = pagina
    caixa = pg.locator(".lvl-quem-sel").bounding_box()
    assert caixa and caixa["width"] >= 90, f"seletor espremido: {caixa}"


def test_popup_do_selo_e_opaco(navegador):
    """
    O popup usava background: var(--page-bg), variável que não existe no CSS —
    o cartão ficava transparente e o texto da página atravessava o conteúdo.
    """
    import capturar_telas as cap
    estado = copy.deepcopy(cap.NIVEL)
    estado["characters"]["helena"]["sheet"].update(
        {"nivel": 3, "xp": 2800, "xp_proximo": 2700,
         "feature_choices": {"Estilo de Combate": "Defesa", "Arquétipo Marcial": "Campeão"}})
    pg, _ = navegador(estado, esperar=None)
    _clicar(pg, ".tab-btn[data-tab='enciclopedia']", 300)
    pg.wait_for_selector(".levelup-badge", state="visible", timeout=5000)
    _clicar(pg, ".levelup-badge", 400)

    fundo = pg.evaluate(
        "() => getComputedStyle(document.querySelector('#levelup-popup > div')).backgroundColor")
    assert fundo not in ("rgba(0, 0, 0, 0)", "transparent"), f"popup transparente: {fundo}"
