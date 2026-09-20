"""
test_animacoes_navegador.py

As animações do livro e a escolha de animações.

A aparência se confere nas capturas; aqui se prova o que não pode quebrar:
  • a escolha nas configurações ("Seguir o sistema", "Ligadas", "Desligadas")
    fica guardada, e "Seguir o sistema" obedece ao reduzir movimento do
    aparelho; o CSS desliga as animações e o JS pergunta animacoesLigadas();
  • virar a página troca o conteúdo na hora (a animação é uma cópia por
    cima), a cópia some no fim e não rouba o botão de rádio do original;
  • menu e jogo são páginas do mesmo livro: a passagem vira a folha e a
    página seguinte chega sem abrir a capa de novo;
  • capítulo novo vira a página, e só quando o capítulo sobe durante o jogo.

As capturas e os outros testes rodam com as animações desligadas
(capturar_telas._script_de_semente); aqui elas são ligadas de propósito.

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
    import requests

    campanha = json.loads((RAIZ / "scripts" / "temp.json").read_text(encoding="utf-8"))
    nome = campanha.get("name") or "Crônicas de Oakhaven"
    campanha["name"] = nome
    url, parar = cap._subir_servidor(campanha, nome)
    try:
        requests.post(f"{url}/__estado", json=copy.deepcopy(cap.DIARIO), timeout=10)
        yield url, nome, cap
    finally:
        parar()


@pytest.fixture
def abrir(app_no_ar):
    """abrir(caminho, animacoes='ligadas', movimento='no-preference') -> (pg, erros)"""
    from playwright.sync_api import sync_playwright

    url, nome, cap = app_no_ar
    pw = sync_playwright().start()
    nav = pw.chromium.launch()

    def _abrir(caminho, animacoes="ligadas", movimento="no-preference"):
        ctx = nav.new_context(viewport={"width": 1440, "height": 900}, reduced_motion=movimento)
        ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO))
        ctx.add_init_script(f"localStorage.setItem('rpg_animacoes', {json.dumps(animacoes)});")
        ctx.add_init_script(CONTA_CAPITULOS)
        pg = ctx.new_page()
        erros = []
        pg.on("pageerror", lambda e: erros.append(str(e)))
        pg.goto(f"{url}{caminho}", wait_until="networkidle")
        return pg, erros

    try:
        yield _abrir
    finally:
        nav.close()
        pw.stop()


# Conta os cartões de capítulo criados desde a carga: sem animações ele dura
# um centésimo de milissegundo e sumiria antes de qualquer verificação.
CONTA_CAPITULOS = """
  window.__capitulos = 0;
  new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => {
    if (n.classList && n.classList.contains('capitulo-novo')) window.__capitulos++;
  }))).observe(document, {childList: true, subtree: true});
"""


def _terminar(pg):
    pg.evaluate("() => document.getAnimations().forEach(a => { try { a.finish(); } catch (_) {} })")


# --- A escolha ---------------------------------------------------------------

@pytest.mark.parametrize("escolha, movimento, ligadas", [
    ("sistema", "no-preference", True),
    ("sistema", "reduce", False),
    ("ligadas", "reduce", True),                  # quem escolheu vence o aparelho
    ("desligadas", "no-preference", False),
])
def test_escolha_e_o_reduzir_movimento_do_aparelho(abrir, escolha, movimento, ligadas):
    pg, erros = abrir("/menu.html", escolha, movimento)
    assert pg.evaluate("() => animacoesLigadas()") is ligadas
    duracao = pg.evaluate("() => getComputedStyle(document.querySelector('.tome-cover')).animationDuration")
    assert (duracao == "1.25s") is ligadas, duracao
    assert not erros, erros[:3]


def test_escolha_fica_guardada(abrir):
    pg, erros = abrir("/menu.html", "sistema")
    opcoes = pg.locator("#settings-panel .settings-anim-option")
    assert opcoes.count() == 3
    assert pg.evaluate("() => document.querySelector('.settings-anim-option.active').dataset.anim") == "sistema"
    pg.evaluate("() => applyAnimacoes('desligadas')")
    assert pg.evaluate("() => [document.documentElement.dataset.animacoes, localStorage.getItem('rpg_animacoes')]") \
        == ["desligadas", "desligadas"]
    assert pg.evaluate("() => document.querySelector('.settings-anim-option.active').dataset.anim") == "desligadas"
    # Uma página nova lê a escolha guardada (aqui sem a semente, que a
    # sobrescreveria na carga).
    pg.evaluate("() => { document.documentElement.dataset.animacoes = ''; loadAnimacoes(); }")
    assert pg.evaluate("() => [document.documentElement.dataset.animacoes, animacoesLigadas()]") \
        == ["desligadas", False]
    assert not erros, erros[:3]


# --- Virar a página ----------------------------------------------------------

def _diario(pg):
    _terminar(pg)
    pg.evaluate("() => window.Diario._abrir(1)")
    pg.wait_for_selector("#diario-overlay:not(.hidden) #dia-pagina", timeout=8000)
    pg.wait_for_timeout(300)
    _terminar(pg)


def test_diario_vira_e_o_conteudo_troca_na_hora(abrir):
    pg, erros = abrir("/game.html")
    _diario(pg)
    antes = pg.inner_text("#dia-pagina")
    pg.evaluate("() => window.Diario._virar(1)")
    assert pg.locator("#diario-overlay .folha-virando").count() == 1, "a folha não virou"
    depois = pg.inner_text("#dia-pagina")
    assert depois != antes, "o conteúdo esperou a animação para trocar"
    assert pg.evaluate("() => document.querySelectorAll('#dia-pagina').length") == 2   # a cópia, por cima
    pg.wait_for_function("() => !document.querySelector('.folha-virando')", timeout=3000)
    assert pg.evaluate("() => document.querySelectorAll('#dia-pagina').length") == 1
    pg.evaluate("() => window.Diario._virar(-1)")
    assert pg.inner_text("#dia-pagina") == antes
    pg.wait_for_function("() => !document.querySelector('.folha-virando')", timeout=3000)
    assert not erros, erros[:3]


def test_sem_animacoes_nao_ha_folha(abrir):
    pg, erros = abrir("/game.html", "desligadas")
    _diario(pg)
    pg.evaluate("() => window.Diario._virar(1)")
    assert pg.locator(".folha-virando").count() == 0
    assert not erros, erros[:3]


def test_passos_do_wizard_viram_sem_roubar_o_radio(abrir):
    pg, erros = abrir("/menu.html")
    _terminar(pg)
    pg.evaluate("() => { openWizard(); document.getElementById('wz-name').value = 'Teste'; wizardGoTo(2); }")
    pg.wait_for_function("() => !document.querySelector('.folha-virando')", timeout=3000)
    pg.evaluate("() => { addWzChar(); addWzChar(); wzMarcarProtagonista(1); }")
    pg.evaluate("() => wizardGoTo(1)")
    assert pg.evaluate("() => wzStep") == 1
    # Para trás são duas: a de agora parada e a anterior virando por cima.
    assert pg.locator("#wizard-overlay .folha-virando").count() == 2
    # A cópia do passo 2 tem os rádios; o original continua marcado.
    assert pg.evaluate("() => [...document.querySelectorAll('#wz-panel-2 .wz-protagonista')]"
                       ".filter(r => !r.closest('.folha-virando')).map(r => r.checked)") == [False, True]
    pg.wait_for_function("() => !document.querySelector('.folha-virando')", timeout=3000)
    assert pg.evaluate("() => wzChars.map(c => c.protagonista)") == [False, True]
    assert not erros, erros[:3]


# --- Menu e jogo: a mesma história, páginas diferentes ------------------------

def test_menu_para_o_jogo_vira_e_chega_sem_abrir_a_capa(abrir):
    pg, erros = abrir("/menu.html")
    _terminar(pg)
    pg.evaluate("() => { virarParaOutraPagina('/game.html', 1); }")
    assert pg.locator(".tome .folha-do-livro").count() == 1
    assert pg.evaluate("() => document.querySelector('.tome > .page-right').classList.contains('pagina-em-branco')")
    pg.wait_for_url("**/game.html", timeout=5000)
    pg.wait_for_load_state("networkidle")
    assert pg.evaluate("() => document.documentElement.classList.contains('chegou-virando')")
    assert pg.evaluate("() => getComputedStyle(document.querySelector('.tome-cover')).display") == "none"
    assert pg.evaluate("() => sessionStorage.getItem('rpg_chegou_virando')") is None
    assert not erros, erros[:3]


def test_jogo_para_o_menu_vira_para_tras(abrir):
    pg, erros = abrir("/game.html")
    _terminar(pg)
    pg.evaluate("() => { virarParaOutraPagina('/menu.html', -1); }")
    folha = pg.evaluate("() => { const f = document.querySelector('.tome .folha-do-livro');"
                        " return f && f.style.transformOrigin; }")
    assert folha and folha.startswith("right"), folha         # a esquerda vira pela lombada
    pg.wait_for_url("**/menu.html", timeout=5000)
    assert pg.evaluate("() => document.documentElement.classList.contains('chegou-virando')")
    assert not erros, erros[:3]


def test_entrar_sem_virar_abre_a_capa(abrir):
    pg, erros = abrir("/menu.html")
    assert not pg.evaluate("() => document.documentElement.classList.contains('chegou-virando')")
    assert pg.evaluate("() => getComputedStyle(document.querySelector('.tome-cover')).display") != "none"
    assert not erros, erros[:3]


# --- Capítulo novo ------------------------------------------------------------

def test_capitulo_novo_vira_a_pagina(abrir):
    pg, erros = abrir("/game.html")
    _terminar(pg)
    assert pg.evaluate("() => window.__capitulos") == 0, "anunciou o capítulo na primeira carga"
    pg.evaluate("""() => renderMemory({...window._lastMem, chapter: (window._lastMem.chapter || 1) + 2,
                  diary: [...(window._lastMem.diary || []), {chapter: (window._lastMem.chapter || 1) + 2,
                          title: 'A Ponte Caída', content: ''}]})""")
    cartao = pg.locator("#chat-area .capitulo-novo")
    assert cartao.count() == 1
    texto = cartao.text_content()
    assert "A Ponte Caída" in texto and "Capítulo" in texto
    assert pg.evaluate("() => document.querySelector('.capitulo-novo-num').textContent") == "IV"
    pg.wait_for_function("() => !document.querySelector('.capitulo-novo')", timeout=6000)
    # O mesmo capítulo de novo não anuncia.
    pg.evaluate("() => renderMemory({...window._lastMem})")
    assert pg.locator(".capitulo-novo").count() == 0
    assert not erros, erros[:3]


def test_capitulo_novo_sem_animacoes_nao_cobre_a_narracao(abrir):
    pg, erros = abrir("/game.html", "desligadas")
    pg.evaluate("() => renderMemory({...window._lastMem, chapter: (window._lastMem.chapter || 1) + 1})")
    pg.wait_for_timeout(200)
    assert pg.evaluate("() => window.__capitulos") == 0
    assert not erros, erros[:3]


# --- Telas por cima: abrir e fechar ------------------------------------------
# Abrir: o papel pousa (CSS, telaPousa). Fechar: a tela de verdade some na
# hora e uma cópia sai por cima (utils.js, _vigiarTelasPorCima).

def _animacoes_de(pg, seletor):
    return pg.evaluate("(s) => { const e = document.querySelector(s);"
                       " return e ? e.getAnimations().map(a => a.animationName || '') : null; }", seletor)


def test_tela_pousa_ao_abrir(abrir):
    pg, erros = abrir("/game.html")
    _terminar(pg)
    pg.evaluate("() => window.Mapa._abrir('')")
    pg.wait_for_selector("#mapa-overlay:not(.hidden)", timeout=8000)
    assert "telaPousa" in _animacoes_de(pg, "#map-frame")
    assert "veuEntra" in _animacoes_de(pg, "#mapa-overlay")
    assert not erros, erros[:3]


def test_fechar_some_na_hora_e_a_copia_sai_por_cima(abrir):
    pg, erros = abrir("/game.html")
    _terminar(pg)
    pg.evaluate("() => window.Mapa._abrir('')")
    pg.wait_for_selector("#mapa-overlay:not(.hidden)", timeout=8000)
    _terminar(pg)
    estado = pg.evaluate("""async () => {
        window.Mapa._fechar();
        await new Promise(r => setTimeout(r, 30));
        const todas = [...document.querySelectorAll('#mapa-overlay')];
        const copia = todas.find(e => e.classList.contains('tela-saindo'));
        return { de_verdade_escondida: todas[0].classList.contains('hidden'),
                 copias: todas.length - 1,
                 clicavel: copia ? getComputedStyle(copia).pointerEvents : null };
    }""")
    assert estado == {"de_verdade_escondida": True, "copias": 1, "clicavel": "none"}, estado
    pg.wait_for_function("() => !document.querySelector('.tela-saindo')", timeout=3000)
    # Reabrir logo depois abre a de verdade.
    pg.evaluate("() => window.Mapa._abrir('')")
    pg.wait_for_selector("#mapa-overlay:not(.hidden):not(.tela-saindo)", timeout=8000)
    assert not erros, erros[:3]


def test_a_copia_guarda_a_rolagem(abrir):
    pg, erros = abrir("/game.html")
    _terminar(pg)
    pg.evaluate("() => window.Diario._abrir(1)")
    pg.wait_for_selector("#diario-overlay:not(.hidden) #dia-pagina", timeout=8000)
    _terminar(pg)
    rolado = pg.evaluate("""async () => {
        const p = document.querySelector('#dia-pagina');
        p.scrollTop = 120; p.dispatchEvent(new Event('scroll'));
        await new Promise(r => setTimeout(r, 30));
        return p.scrollTop;
    }""")
    assert rolado > 0, "a página do diário não rola nesta campanha"
    na_copia = pg.evaluate("""async () => {
        window.Diario._fechar();
        await new Promise(r => setTimeout(r, 30));
        const c = document.querySelector('.tela-saindo #dia-pagina');
        return c ? c.scrollTop : null;
    }""")
    assert na_copia == rolado, "a cópia saiu pulando para o topo"
    assert not erros, erros[:3]


def test_sem_animacoes_fecha_sem_copia(abrir):
    pg, erros = abrir("/game.html", "desligadas")
    pg.evaluate("() => window.Mapa._abrir('')")
    pg.wait_for_selector("#mapa-overlay:not(.hidden)", timeout=8000)
    assert pg.evaluate("""async () => { window.Mapa._fechar(); await new Promise(r => setTimeout(r, 30));
                           return document.querySelectorAll('.tela-saindo').length; }""") == 0
    assert not erros, erros[:3]


def test_aviso_e_janela_do_menu_pousam(abrir):
    pg, erros = abrir("/menu.html")
    _terminar(pg)
    pg.evaluate("() => { showAlert('Teste', 'Uma mensagem'); }")
    pg.wait_for_selector("#dialog-overlay:not(.hidden)", timeout=5000)
    assert "telaPousa" in _animacoes_de(pg, "#dialog-overlay .dialog-box")
    pg.evaluate("() => document.querySelector('#dialog-overlay button').click()")
    pg.evaluate("() => openWizard()")
    assert "telaPousa" in _animacoes_de(pg, "#wizard-overlay .wizard-box")
    assert not erros, erros[:3]


@pytest.mark.parametrize("escolha, movimento", [("desligadas", "no-preference"), ("sistema", "reduce")])
def test_sem_animacoes_a_tela_aparece_ja_no_lugar(abrir, escolha, movimento):
    """
    Encurtar a duração não bastava: no quadro em que a tela aparece, a
    animação de entrada ainda está no começo, e a pílula da loja era medida
    16px abaixo do lugar. Sem animações, as de entrada não existem.
    """
    pg, erros = abrir("/game.html", escolha, movimento)
    assert not pg.evaluate("() => document.documentElement.classList.contains('anim-on')")
    estado = pg.evaluate("""() => { window.Mapa._abrir('');
        const f = document.querySelector('#map-frame');
        return [f.getAnimations().length, getComputedStyle(f).transform]; }""")
    assert estado == [0, "none"], estado
    assert not erros, erros[:3]


def test_escolher_ligadas_liga_as_de_entrada_na_hora(abrir):
    pg, erros = abrir("/game.html", "desligadas")
    pg.evaluate("() => applyAnimacoes('ligadas')")
    assert pg.evaluate("() => document.documentElement.classList.contains('anim-on')")
    pg.evaluate("() => applyAnimacoes('desligadas')")
    assert not pg.evaluate("() => document.documentElement.classList.contains('anim-on')")
    assert not erros, erros[:3]


# --- Chat e dados ----------------------------------------------------------------
# Só o que chega agora anima; o histórico carregado ao abrir, não.

def test_resposta_do_mestre_surge_paragrafo_a_paragrafo(abrir):
    pg, erros = abrir("/game.html")
    _terminar(pg)
    r = pg.evaluate("""() => { const row = appendMaster(['Primeiro.', 'Segundo.', 'Terceiro.'].join(String.fromCharCode(10, 10)));
        const b = row.querySelector('.msg-bubble');
        return [b.classList.contains('tinta-nova'), [...b.children].map(c => c.style.getPropertyValue('--i')),
                getComputedStyle(b.children[2]).animationName, b.style.opacity]; }""")
    assert r == [True, ["0", "1", "2"], "tintaSeca", ""], r
    assert not erros, erros[:3]


def test_fala_do_jogador_e_escrita_a_mao_e_o_historico_nao_anima(abrir):
    pg, erros = abrir("/game.html")
    _terminar(pg)
    nova = pg.evaluate("() => { const b = appendUser('Pergunto o preço.').querySelector('.msg-bubble');"
                       " return [b.classList.contains('escrita-nova'), b.style.getPropertyValue('--escrita')]; }")
    assert nova[0] and nova[1].endswith("ms"), nova
    antigas = pg.evaluate("""() => { const h = document.getElementById('chat-history');
        const antes = h.children.length;
        renderHistory([{role: 'user', text: 'antiga'}, {role: 'assistant', text: 'Resposta antiga.'},
                       {role: 'user', interno: 'dado', text: '[DADO] rolei 5'}]);
        return [...h.children].slice(antes).map(r => r.querySelector('.escrita-nova, .tinta-nova')
                                                   || r.classList.contains('msg-nova')); }""")
    assert antigas == [False, False, False], antigas
    assert not erros, erros[:3]


def test_pena_no_lugar_dos_tres_pontos(abrir):
    pg, erros = abrir("/game.html")
    _terminar(pg)
    r = pg.evaluate("""() => { const id = appendTyping(); const el = document.getElementById(id);
        const antes = [!!el.querySelector('.pena-escrevendo .pena-svg'), !!el.querySelector('.linha-de-tinta'),
                       getComputedStyle(el.querySelector('.pena-svg')).animationName];
        updateTyping(id, 'rolando dado');
        const depois = [!!el.querySelector('.pena-svg'), el.querySelector('.pena-msg')?.textContent];
        removeTyping(id); return [antes, depois]; }""")
    assert r == [[True, True, "penaEscreve"], [True, "rolando dado"]], r
    assert not erros, erros[:3]


def test_mensagem_do_sistema_entra_deslizando(abrir):
    pg, erros = abrir("/game.html")
    _terminar(pg)
    r = pg.evaluate("() => { const row = appendSystem('<p>Aviso.</p>');"
                    " return [row.classList.contains('msg-nova'), getComputedStyle(row).animationName]; }")
    assert r == [True, "sistemaEntra"], r
    assert not erros, erros[:3]


def _rolar(pg, aleatorio):
    pg.evaluate(f"() => {{ window.sendToAgent = () => {{}}; Math.random = () => {aleatorio}; rollPlayerDie(20); }}")
    return pg.locator("#chat-history .msg-row.system .sys-card").last


def test_dado_rola_e_cai_no_critico(abrir):
    pg, erros = abrir("/game.html")
    _terminar(pg)
    cartao = _rolar(pg, 0.999)                     # 20 natural
    assert "dado-rolando" in cartao.get_attribute("class")
    assert not cartao.locator(".dado-resto").is_visible(), "o total apareceu antes de o dado cair"
    pg.wait_for_function("() => [...document.querySelectorAll('.sys-card')].pop().classList.contains('dado-caiu')",
                         timeout=3000)
    classes = cartao.get_attribute("class")
    assert "dado-critico" in classes and "dado-rolando" not in classes
    assert cartao.locator(".dado-numero").inner_text() == "20"
    assert cartao.locator(".dado-resto").is_visible()
    assert not erros, erros[:3]


def test_dado_treme_na_falha(abrir):
    pg, erros = abrir("/game.html")
    _terminar(pg)
    cartao = _rolar(pg, 0.0)                       # 1 natural
    pg.wait_for_function("() => [...document.querySelectorAll('.sys-card')].pop().classList.contains('dado-caiu')",
                         timeout=3000)
    assert "dado-falha" in cartao.get_attribute("class")
    assert cartao.locator(".dado-numero").inner_text() == "1"
    assert not erros, erros[:3]


def test_sem_animacoes_o_chat_aparece_direto(abrir):
    pg, erros = abrir("/game.html", "desligadas")
    r = pg.evaluate("""() => { window.sendToAgent = () => {}; Math.random = () => 0.5;
        const m = appendMaster('Texto.').querySelector('.msg-bubble');
        const u = appendUser('Oi').querySelector('.msg-bubble');
        const s = appendSystem('<p>Aviso.</p>');
        rollPlayerDie(20);
        const d = [...document.querySelectorAll('.sys-card')].pop();
        return [m.classList.contains('tinta-nova'), u.classList.contains('escrita-nova'),
                s.classList.contains('msg-nova'), d.classList.contains('dado-rolando'),
                d.classList.contains('dado-caiu'), d.querySelector('.dado-numero').textContent]; }""")
    assert r == [False, False, False, False, True, "11"], r
    assert not erros, erros[:3]


# --- Combate ---------------------------------------------------------------------
# O render redesenha os cartões; quem mudou vem da comparação com o anterior.
# O estado muda no servidor (/__estado) e a tela relê (Combat.sync).

VIGIA_CLASSES = """
  window.__classesVistas = new Set();
  new MutationObserver(ms => ms.forEach(m => {
    if (m.target.classList) m.target.classList.forEach(c => window.__classesVistas.add(c));
    m.addedNodes && m.addedNodes.forEach(n => n.classList && n.classList.forEach(c => window.__classesVistas.add(c)));
  })).observe(document, {attributes: true, attributeFilter: ['class'], childList: true, subtree: true});
"""


def _combate(app_no_ar, abrir, animacoes="ligadas", **mudar):
    import requests
    url, _, cap = app_no_ar
    estado = copy.deepcopy(cap.COMBATE_ATIVO)
    requests.post(f"{url}/__estado", json=estado, timeout=10)
    pg, erros = abrir("/game.html", animacoes)
    pg.wait_for_selector("#combat-overlay:not(.hidden) .cbt-card[data-nome='Stelar']", timeout=10000)
    return pg, erros, url, cap


def _mudar_combate(url, cap, pg, personagens=None, turno=None):
    import requests
    estado = copy.deepcopy(cap.COMBATE_ATIVO)
    for nome, vida in (personagens or {}).items():
        estado["characters"][nome] = {"sheet": {"vida_atual": vida}}
    if turno is not None:
        estado["combat_state"]["current_turn_index"] = turno
    requests.post(f"{url}/__estado", json=estado, timeout=10)
    pg.evaluate("() => window.Combat.sync()")
    pg.wait_for_timeout(250)


def test_dano_flutua_e_o_cartao_treme(app_no_ar, abrir):
    pg, erros, url, cap = _combate(app_no_ar, abrir)
    try:
        _mudar_combate(url, cap, pg, {"stelar": 12})
        cartao = pg.locator("#combat-overlay .cbt-card[data-nome='Stelar']")
        assert "cbt-levou-dano" in cartao.get_attribute("class")
        assert cartao.locator(".cbt-flutua.dano").inner_text() == "-7"
        _terminar(pg)
        pg.wait_for_timeout(200)
        assert cartao.locator(".cbt-flutua").count() == 0, "o número ficou na tela"
        # Curar: número verde.
        _mudar_combate(url, cap, pg, {"stelar": 19})
        assert pg.locator("#combat-overlay .cbt-card[data-nome='Stelar'] .cbt-flutua.cura").inner_text() == "+7"
        assert not erros, erros[:3]
    finally:
        import requests
        requests.post(f"{url}/__estado", json=copy.deepcopy(cap.DIARIO), timeout=10)


def test_primeiro_desenho_nao_anima_nada(app_no_ar, abrir):
    pg, erros, url, cap = _combate(app_no_ar, abrir)
    try:
        assert pg.locator("#combat-overlay .cbt-flutua, #combat-overlay .cbt-levou-dano").count() == 0
        assert not erros, erros[:3]
    finally:
        import requests
        requests.post(f"{url}/__estado", json=copy.deepcopy(cap.DIARIO), timeout=10)


def test_vez_nova_pulsa(app_no_ar, abrir):
    pg, erros, url, cap = _combate(app_no_ar, abrir)
    try:
        _mudar_combate(url, cap, pg, turno=2)          # Helena
        assert "cbt-vez-nova" in pg.locator("#combat-overlay .cbt-card[data-nome='Helena']").get_attribute("class")
        assert "cbt-vez-nova" not in pg.locator("#combat-overlay .cbt-card[data-nome='Stelar']").get_attribute("class")
        assert not erros, erros[:3]
    finally:
        import requests
        requests.post(f"{url}/__estado", json=copy.deepcopy(cap.DIARIO), timeout=10)


def test_combate_novo_da_um_tranco(app_no_ar):
    import requests
    url, _, cap = app_no_ar
    requests.post(f"{url}/__estado", json=copy.deepcopy(cap.COMBATE_ATIVO), timeout=10)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            nav = pw.chromium.launch()
            ctx = nav.new_context(viewport={"width": 1440, "height": 900})
            ctx.add_init_script(cap._script_de_semente(app_no_ar[1], "pergaminho", cap.HISTORICO))
            ctx.add_init_script("localStorage.setItem('rpg_animacoes', 'ligadas');")
            ctx.add_init_script(VIGIA_CLASSES)
            pg = ctx.new_page()
            pg.goto(f"{url}/game.html", wait_until="networkidle")
            pg.wait_for_selector("#combat-overlay:not(.hidden)", timeout=10000)
            assert pg.evaluate("() => window.__classesVistas.has('cbt-inicio')"), "abrir o combate não deu o tranco"
            pg.wait_for_function("() => !document.getElementById('cbt-frame').classList.contains('cbt-inicio')",
                                 timeout=3000)
            nav.close()
    finally:
        requests.post(f"{url}/__estado", json=copy.deepcopy(cap.DIARIO), timeout=10)


def test_fim_do_combate_cai_como_selo(abrir):
    pg, erros = abrir("/game.html")
    r = pg.evaluate("""() => { const ov = document.createElement('div');
        ov.className = 'cbt-end-overlay'; ov.innerHTML = '<div class="cbt-end-modal"><svg class="cbt-crista"></svg></div>';
        document.body.appendChild(ov);
        return [getComputedStyle(ov.querySelector('.cbt-end-modal')).animationName,
                getComputedStyle(ov.querySelector('.cbt-crista')).animationName]; }""")
    assert r == ["seloCai", "cristaAparece"], r
    assert not erros, erros[:3]


def test_sem_animacoes_o_combate_so_redesenha(app_no_ar, abrir):
    pg, erros, url, cap = _combate(app_no_ar, abrir, "desligadas")
    try:
        _mudar_combate(url, cap, pg, {"stelar": 12}, turno=2)
        assert pg.locator("#combat-overlay .cbt-flutua, #combat-overlay .cbt-levou-dano, "
                          "#combat-overlay .cbt-vez-nova").count() == 0
        assert pg.locator("#combat-overlay .cbt-card[data-nome='Stelar'] .cbt-bar-num").first.inner_text().startswith("12/")
        assert not erros, erros[:3]
    finally:
        import requests
        requests.post(f"{url}/__estado", json=copy.deepcopy(cap.DIARIO), timeout=10)


# --- Progressão e recompensas -------------------------------------------------
# utils.js, animarNumeros: o que mudou entre dois desenhos conta e pulsa, e a
# barra desliza. Cada tela marca os seus números; aqui, a ação de verdade.

def test_numero_conta_pulsa_e_a_barra_desliza(abrir):
    pg, erros = abrir("/game.html")
    r = pg.evaluate("""async () => {
        const d = document.createElement('div');
        d.innerHTML = '<span data-num="t:ca">10</span><div data-barra="t:carga" style="width:20%"></div>';
        document.body.appendChild(d);
        animarNumeros(d);
        d.innerHTML = '<span data-num="t:ca">15</span><div data-barra="t:carga" style="width:60%"></div>';
        animarNumeros(d);
        const num = d.querySelector('[data-num]'), barra = d.querySelector('[data-barra]');
        const logo = [num.classList.contains('num-subiu'), barra.style.width];
        // No caminho, o texto passa pelos números entre um e outro.
        const vistos = new Set();
        const fim = performance.now() + 900;
        while (performance.now() < fim) {
            vistos.add(num.textContent);
            await new Promise(r => requestAnimationFrame(r));
        }
        const meio = [...vistos].some(v => Number(v) > 10 && Number(v) < 15);
        return [...logo, meio, num.textContent, barra.style.width];
    }""")
    assert r == [True, "20%", True, "15", "60%"], r
    assert not erros, erros[:3]


def test_outra_chave_nao_conta_e_sem_animacoes_so_guarda(abrir):
    pg, erros = abrir("/game.html", "desligadas")
    r = pg.evaluate("""() => {
        const d = document.createElement('div'); document.body.appendChild(d);
        d.innerHTML = '<span data-num="t:a">10</span><div data-barra="t:b" style="width:20%"></div>';
        animarNumeros(d);
        d.innerHTML = '<span data-num="t:a">15</span><div data-barra="t:b" style="width:60%"></div>';
        animarNumeros(d);
        destacar(d.querySelector('div'), 'brilho-teste');
        const sem = [d.querySelector('span').className, d.querySelector('div').style.width,
                     d.querySelector('div').className];
        applyAnimacoes('ligadas');
        d.innerHTML = '<span data-num="t:outra">99</span>';
        animarNumeros(d);
        return [...sem, d.querySelector('span').className];
    }""")
    assert r == ["", "60%", "", ""], r
    assert not erros, erros[:3]


def _na_tela(app_no_ar, abrir, estado):
    import requests
    url, _, cap = app_no_ar
    requests.post(f"{url}/__estado", json=copy.deepcopy(getattr(cap, estado)), timeout=10)
    pg, erros = abrir("/game.html")
    return pg, erros, lambda: requests.post(f"{url}/__estado", json=copy.deepcopy(cap.DIARIO), timeout=10)


def test_mochila_a_ca_conta_ao_vestir(app_no_ar, abrir):
    pg, erros, voltar = _na_tela(app_no_ar, abrir, "MOCHILA")
    try:
        pg.evaluate("() => window.Inventory._abrir('Stelar')")
        pg.wait_for_selector("#inventory-overlay:not(.hidden) .inv-item", timeout=8000)
        pg.evaluate("() => window.Inventory._equipar('Cota de Malha', 'armadura')")
        pg.wait_for_selector("#inv-msg:not(:empty)", timeout=8000)
        assert "num-subiu" in pg.get_attribute("#inv-ca-num", "class")
        assert not erros, erros[:3]
    finally:
        voltar()


def test_descanso_a_vida_sobe_e_o_dado_se_esvazia(app_no_ar, abrir):
    pg, erros, voltar = _na_tela(app_no_ar, abrir, "DESCANSO_CURTO")
    try:
        pg.wait_for_selector("#rest-overlay:not(.hidden) .rst-card[data-nome='Helena']", timeout=8000)
        assert pg.locator("#rest-overlay .rst-brasas i").count() == 6
        pg.evaluate("() => window.Rest._dado('Helena')")
        pg.wait_for_selector(".rst-card[data-nome='Helena'] .rst-gastos:not(:empty)", timeout=8000)
        cartao = pg.locator(".rst-card[data-nome='Helena']")
        assert "num-subiu" in cartao.locator("[data-num$=':vida']").get_attribute("class")
        assert "num-desceu" in cartao.locator(".rst-pips").get_attribute("class")
        assert not erros, erros[:3]
    finally:
        voltar()


def test_saque_o_cartao_de_quem_leva_pulsa(app_no_ar, abrir):
    pg, erros, voltar = _na_tela(app_no_ar, abrir, "SAQUE")
    try:
        pg.wait_for_selector("#loot-overlay:not(.hidden) .lot-item:not(.lot-item-dado)", timeout=8000)
        item = pg.get_attribute("#loot-overlay .lot-item:not(.lot-item-dado)", "data-id")
        pg.evaluate("(i) => window.Loot._dar(i, 'Natasha')", item)
        pg.wait_for_function("() => document.querySelector(\".lot-cartao[data-nome='Natasha'] .lot-recebe\")",
                             timeout=8000)
        assert "num-subiu" in pg.get_attribute(".lot-cartao[data-nome='Natasha']", "class")
        assert not erros, erros[:3]
    finally:
        voltar()


def test_nivel_escolha_feita_brilha(app_no_ar, abrir):
    pg, erros, voltar = _na_tela(app_no_ar, abrir, "NIVEL")
    try:
        pg.wait_for_selector("#levelup-overlay:not(.hidden) .lvl-opcao", timeout=8000)
        pg.click("#levelup-overlay .lvl-opcao >> nth=0")
        pg.wait_for_function("() => document.getElementById('lvl-frame').classList.contains('lvl-escolha-feita')",
                             timeout=5000)
        assert not erros, erros[:3]
    finally:
        voltar()


def test_grimorio_a_magia_aprendida_brilha(app_no_ar, abrir):
    pg, erros, voltar = _na_tela(app_no_ar, abrir, "GRIMORIO")
    try:
        pg.evaluate("() => window.Grimoire._abrir()")
        pg.wait_for_selector("#grimoire-overlay .grm-aprender-btn:not([disabled])", timeout=8000)
        pg.click("#grimoire-overlay .grm-aprender-btn:not([disabled]) >> nth=0")
        pg.wait_for_function("() => document.querySelector('#grimoire-overlay .grm-conhecida.grm-aprendeu')",
                             timeout=5000)
        assert not erros, erros[:3]
    finally:
        voltar()


def test_loja_as_moedas_descem_ao_comprar(app_no_ar, abrir):
    pg, erros, voltar = _na_tela(app_no_ar, abrir, "LOJA")
    try:
        pg.wait_for_selector("#shop-overlay:not(.hidden) .shp-btn:not([disabled])", timeout=8000)
        pg.click("#shop-overlay .shp-btn:not([disabled]) >> nth=0")
        pg.wait_for_function("() => document.querySelector('#shp-bolsa [data-num].num-desceu')", timeout=5000)
        assert not erros, erros[:3]
    finally:
        voltar()



# --- Romance e fantasia -------------------------------------------------------
# utils.js, marcarNovos: o que chegou desde o último desenho de uma lista ganha
# item-novo (o segredo quebra o selo, o título cai como selo, o fragmento se
# encaixa). Relações e Mundo marcam; aqui, a mudança de verdade entre dois turnos.

def test_novos_so_depois_do_primeiro_desenho_e_sem_animacoes_nada(abrir):
    pg, erros = abrir("/game.html")
    r = pg.evaluate("""() => {
        const d = document.createElement('div'); document.body.appendChild(d);
        const lista = (...k) => { d.innerHTML = k.map(x => `<p data-novo="${x}">${x}</p>`).join(''); };
        lista();
        marcarNovos(d, 't:vazia');
        lista('a');
        marcarNovos(d, 't:vazia');
        const primeiro = d.querySelector('p').className;
        lista('a', 'b');
        marcarNovos(d, 't:vazia');
        const segundo = [...d.querySelectorAll('p')].map(p => p.className);
        lista('x');
        marcarNovos(d, 't:outra');
        const outra = d.querySelector('p').className;
        applyAnimacoes('desligadas');
        lista('a', 'b', 'c');
        marcarNovos(d, 't:vazia');
        return [primeiro, ...segundo, outra, d.querySelector('p:last-child').className];
    }""")
    assert r == ["item-novo", "", "item-novo", "", ""], r
    assert not erros, erros[:3]


def _romance(app_no_ar, abrir, estado, pagina="/game.html"):
    import requests
    url, _, cap = app_no_ar
    requests.post(f"{url}/__estado", json=copy.deepcopy(estado), timeout=10)
    pg, erros = abrir(pagina)

    def trocar(novo):
        requests.post(f"{url}/__estado", json=copy.deepcopy(novo), timeout=10)

    return pg, erros, trocar, lambda: trocar(cap.DIARIO)


def _romance_depois():
    from test_relacoes_navegador import ROMANCE
    antes = copy.deepcopy(ROMANCE)
    depois = copy.deepcopy(ROMANCE)
    lucas = depois["characters"]["lucas"]
    lucas["atitude"] = 65
    lucas["confianca"] = -40
    lucas["estagio"] = "namoro"
    lucas["momentos"].append({"titulo": "O primeiro beijo", "descricao": "Na escada", "tipo": "momento", "cap": 3})
    depois["segredos"]["o anel guardado"].update(revelado=True, como="descobriu", dono_sabe=False, cap_revelado=3)
    return antes, depois


def test_relacao_afeto_desliza_com_seta_estagio_acende_e_momento_novo(app_no_ar, abrir):
    antes, depois = _romance_depois()
    pg, erros, trocar, voltar = _romance(app_no_ar, abrir, antes)
    try:
        pg.evaluate("() => window.Relacoes._abrir('pessoas')")
        pg.wait_for_selector("#relacoes-overlay .rel-cartao[data-nome='Lucas']", timeout=8000)
        trocar(depois)
        marca = pg.evaluate("""async () => {
            await window.Relacoes.sync();
            const c = document.querySelector(".rel-cartao[data-nome='Lucas']");
            const m = c.querySelector('.rel-afeto .psn-barra-marca');
            return [m.style.left, c.querySelector('.rel-afeto .rel-valor').className,
                    c.querySelector('.rel-confianca .rel-valor').className,
                    c.querySelector('.rel-segmentos').className,
                    !!c.querySelector('.rel-segmento-atual'),
                    c.querySelector('.rel-ultimo .rel-momento').className];
        }""")
        # A marca parte de onde estava (45 -> 72,5%) e desliza até 82,5%.
        assert marca[0] == "72.5%", marca
        assert "num-subiu" in marca[1] and "num-desceu" in marca[2], marca
        assert "num-subiu" in marca[3] and marca[4], marca
        assert "item-novo" in marca[5], marca
        # Conta com o sinal ("+49") e termina no texto de verdade.
        vistos = pg.evaluate("""async () => {
            const el = document.querySelector(".rel-cartao[data-nome='Lucas'] .rel-afeto .rel-valor");
            const v = new Set(); const fim = performance.now() + 900;
            while (performance.now() < fim) { v.add(el.textContent.trim()); await new Promise(r => requestAnimationFrame(r)); }
            return [...v];
        }""")
        assert len(vistos) > 2 and all(t.startswith("+") for t in vistos), vistos
        pg.wait_for_function("""() => document.querySelector(".rel-cartao[data-nome='Lucas'] .rel-afeto .psn-barra-marca")
                                   .style.left === '82.5%'""", timeout=3000)
        seta = pg.evaluate("""() => getComputedStyle(document.querySelector(
            ".rel-cartao[data-nome='Lucas'] .rel-afeto .rel-valor"), '::after').content""")
        assert "2191" in seta or "↑" in seta, seta
        pg.wait_for_function("""() => document.querySelector(".rel-cartao[data-nome='Lucas'] .rel-afeto .rel-valor")
                                   .textContent.trim() === '+65'""", timeout=3000)
        assert not erros, erros[:3]
    finally:
        voltar()


def test_segredo_revelado_quebra_o_selo_e_a_aba_pulsa(app_no_ar, abrir):
    antes, depois = _romance_depois()
    pg, erros, trocar, voltar = _romance(app_no_ar, abrir, antes)
    try:
        pg.evaluate("() => window.Relacoes._abrir('segredos')")
        pg.wait_for_selector("#relacoes-overlay .rel-segredo", timeout=8000)
        trocar(depois)
        r = pg.evaluate("""async () => {
            await window.Relacoes.sync();
            const novos = [...document.querySelectorAll('#rel-lista .rel-segredo.item-novo')].map(e => e.dataset.titulo);
            const velhos = [...document.querySelectorAll('#rel-lista .rel-segredo:not(.item-novo)')].map(e => e.dataset.titulo);
            const aba = document.querySelector("#rel-abas [data-aba='segredos'] .elc-filtro-conta").className;
            const selo = document.querySelector('#rel-lista .rel-segredo.item-novo');
            const anims = selo.getAnimations({subtree: true}).map(a => a.animationName);
            return [novos, velhos, aba, anims];
        }""")
        assert r[0] == ["O anel guardado"], r
        assert "O irmão na prisão" in r[1], r
        assert "num-subiu" in r[2], r
        assert "seloQuebraEsq" in r[3] and "seloQuebraDir" in r[3], r
        assert not erros, erros[:3]
    finally:
        voltar()


def test_encontro_proximo_faz_a_barra_pulsar(app_no_ar, abrir):
    from test_relacoes_navegador import ROMANCE
    longe = copy.deepcopy(ROMANCE)
    longe["relogio"] = {"dia": 2, "hora": 8}
    perto = copy.deepcopy(ROMANCE)
    perto["relogio"] = {"dia": 3, "hora": 17}
    pg, erros, trocar, voltar = _romance(app_no_ar, abrir, longe)
    try:
        pg.wait_for_selector("#sb-encontro:not(.hidden)", timeout=8000)
        assert "sb-encontro-chegando" not in pg.get_attribute("#sb-encontro", "class")
        trocar(perto)
        pg.evaluate("() => refreshMemory()")
        pg.wait_for_function("() => document.getElementById('sb-encontro').classList.contains('sb-encontro-chegando')",
                             timeout=5000)
        assert not erros, erros[:3]
    finally:
        voltar()


def _fantasia_depois():
    from test_mundo_navegador import FANTASIA
    antes = copy.deepcopy(FANTASIA)
    depois = copy.deepcopy(FANTASIA)
    depois["renome"] = {"valor": 50, "historico": depois["renome"]["historico"]
                        + [{"delta": 15, "motivo": "Salvaram a caravana", "cap": 4}]}
    depois["faccoes"]["casa vael"]["reputacao"] = 20
    depois["titulos"].append({"titulo": "Matadora de Wyrms", "quem": "Aria", "motivo": "O wyrm de Cinza", "cap": 4})
    depois["lendas"]["a coroa afogada"]["fragmentos"].append(
        {"texto": "A coroa brilha nas noites sem lua", "fonte": "uma criança", "cap": 4})
    return antes, depois


def test_renome_sobe_reputacao_desce_titulo_cai_como_selo(app_no_ar, abrir):
    antes, depois = _fantasia_depois()
    pg, erros, trocar, voltar = _romance(app_no_ar, abrir, antes)
    try:
        pg.evaluate("() => window.Mundo._abrir('renome')")
        pg.wait_for_selector("#mundo-overlay .mnd-renome", timeout=8000)
        trocar(depois)
        r = pg.evaluate("""async () => {
            await window.Mundo.sync();
            const fac = document.querySelector(".mnd-faccao[data-nome='Casa Vael']");
            return [document.querySelector('.mnd-renome .rel-valor').className,
                    document.querySelector('.mnd-fama > span').style.width,
                    fac.querySelector('.rel-valor').className,
                    fac.querySelector('.psn-barra-marca').style.left,
                    [...document.querySelectorAll('.mnd-titulo-item.item-novo')].map(e => e.dataset.titulo)];
        }""")
        assert "num-subiu" in r[0] and r[1] == "35%", r
        assert "num-desceu" in r[2] and r[3] == "70%", r
        assert r[4] == ["Matadora de Wyrms"], r
        assert not erros, erros[:3]
    finally:
        voltar()


def test_fragmento_novo_de_lenda_se_encaixa(app_no_ar, abrir):
    antes, depois = _fantasia_depois()
    pg, erros, trocar, voltar = _romance(app_no_ar, abrir, antes)
    try:
        pg.evaluate("() => window.Mundo._abrir('lendas')")
        pg.wait_for_selector("#mundo-overlay .mnd-lenda", timeout=8000)
        trocar(depois)
        r = pg.evaluate("""async () => {
            await window.Mundo.sync();
            return [...document.querySelectorAll('.mnd-lenda .rel-momento')].map(e => e.classList.contains('item-novo'));
        }""")
        assert r == [False, True], r
        assert not erros, erros[:3]
    finally:
        voltar()


# --- Barra lateral e menu -----------------------------------------------------
# barra.js: a hora nova sobe no lugar da velha e, quando vira o dia, um sol (ou
# uma lua) cruza o relógio; o que muda na barra ganha um destaque breve.
# menu.js: a lista de campanhas entra em sequência; "Gerar com IA" escreve com
# a pena enquanto espera, e os campos preenchidos aparecem um a um.

def _com_relogio(cap, dia, hora, local="Villa Ravenhurst"):
    e = copy.deepcopy(cap.DIARIO)
    e["relogio"] = {"dia": dia, "hora": hora}
    e["current_location"] = local
    return e


def test_relogio_a_hora_sobe_e_o_dia_novo_traz_o_sol(app_no_ar, abrir):
    _, _, cap = app_no_ar
    pg, erros, trocar, voltar = _romance(app_no_ar, abrir, _com_relogio(cap, 4, 16))
    try:
        pg.wait_for_selector("#sb-tempo:not(.hidden)", timeout=8000)
        _terminar(pg)
        assert pg.locator("#sb-tempo .sb-astro").count() == 0
        trocar(_com_relogio(cap, 4, 18))
        pg.evaluate("() => refreshMemory()")
        pg.wait_for_function("() => document.getElementById('sb-tempo-texto').classList.contains('sb-hora-mudou')",
                             timeout=5000)
        assert pg.locator("#sb-tempo .sb-astro").count() == 0, "a hora andou, mas o dia é o mesmo"
        trocar(_com_relogio(cap, 5, 7))
        pg.evaluate("() => refreshMemory()")
        pg.wait_for_selector("#sb-tempo .sb-astro.sb-astro-sol", timeout=5000)
        # O arco tem de caber na linha do relógio: a barra rola e corta o que
        # sobe acima dela — com o arco alto, o sol sumia pela metade.
        # Tudo numa leitura só: soltar a animação antes de medir deixava o
        # astro sumir no meio do caminho (ele se remove no fim).
        medida = pg.evaluate("""() => {
            const a = document.querySelector('#sb-tempo .sb-astro');
            const cont = a.closest('.sidebar-content').getBoundingClientRect();
            const fora = [];
            for (let ms = 0; ms <= 2000; ms += 100) {
                a.getAnimations().forEach(an => { an.pause(); an.currentTime = ms; });
                const r = a.getBoundingClientRect();
                if (r.top < cont.top - 0.5 || r.bottom > cont.bottom + 0.5) fora.push(ms);
            }
            return {fora, largura: parseFloat(getComputedStyle(a).width)};
        }""")
        assert medida["fora"] == [], medida
        # E é grande o bastante para se ver: 16px sumia na linha.
        assert medida["largura"] >= 20, medida
        pg.evaluate("() => document.querySelectorAll('#sb-tempo .sb-astro')"
                    ".forEach(a => a.getAnimations().forEach(an => an.finish()))")
        # O astro some no fim da animação.
        pg.wait_for_function("() => !document.querySelector('#sb-tempo .sb-astro')", timeout=4000)
        trocar(_com_relogio(cap, 6, 22))
        pg.evaluate("() => refreshMemory()")
        pg.wait_for_selector("#sb-tempo .sb-astro.sb-astro-lua", timeout=5000)
        assert not erros, erros[:3]
    finally:
        voltar()


def test_barra_o_lugar_novo_destaca_e_sem_animacoes_nada(app_no_ar, abrir):
    _, _, cap = app_no_ar
    for animacoes in ("ligadas", "desligadas"):
        import requests
        url = app_no_ar[0]
        requests.post(f"{url}/__estado", json=_com_relogio(cap, 4, 16), timeout=10)
        pg, erros = abrir("/game.html", animacoes)
        pg.wait_for_selector("#sb-tempo:not(.hidden)", timeout=8000)
        requests.post(f"{url}/__estado", json=_com_relogio(cap, 5, 9, "Avenida dos Mil Sóis"), timeout=10)
        pg.evaluate("""() => { window.__marcas = [];
            new MutationObserver(ms => ms.forEach(m => { if (m.target.classList)
                window.__marcas.push(...m.target.classList); }))
              .observe(document.getElementById('sidebar'), {attributes: true, subtree: true, attributeFilter: ['class']}); }""")
        pg.evaluate("() => refreshMemory()")
        pg.wait_for_function("() => document.getElementById('sb-location-nome').textContent.includes('Mil')",
                             timeout=5000)
        pg.wait_for_timeout(300)
        marcas = set(pg.evaluate("() => window.__marcas"))
        if animacoes == "ligadas":
            assert {"sb-mudou", "sb-hora-mudou"} <= marcas, marcas
            assert pg.locator("#sb-tempo .sb-astro").count() == 1
        else:
            assert not ({"sb-mudou", "sb-hora-mudou"} & marcas), marcas
            assert pg.locator("#sb-tempo .sb-astro").count() == 0
        assert not erros, erros[:3]
    import requests
    requests.post(f"{app_no_ar[0]}/__estado", json=copy.deepcopy(cap.DIARIO), timeout=10)


def test_lista_de_campanhas_entra_em_sequencia(abrir):
    pg, erros = abrir("/menu.html")
    pg.wait_for_selector("#campaign-list .campaign-item", timeout=8000)
    r = pg.evaluate("""() => [...document.querySelectorAll('#campaign-list .campaign-item')].map(e =>
        [e.style.getPropertyValue('--i'), e.getAnimations().map(a => a.animationName)])""")
    assert r and r[0][0] == "0" and "campanhaEntra" in r[0][1], r
    # Recarregar a lista (depois de apagar ou salvar) não repete a entrada.
    pg.evaluate("async () => { await loadCampaigns(); }")
    assert pg.evaluate("""() => document.querySelector('#campaign-list .campaign-item')
                              .getAnimations().length""") == 0
    assert not erros, erros[:3]


def test_gerar_com_ia_escreve_com_a_pena_e_os_campos_chegam_um_a_um(abrir):
    pg, erros = abrir("/menu.html")
    _terminar(pg)
    liberar = []
    pg.route("**/api/campaigns/generate-lore", lambda rota: liberar.append(rota))
    pg.evaluate("""() => { openWizard(); document.getElementById('wz-name').value = 'Teste';
        toggleAiCreate(true); document.getElementById('wz-ai-prompt').value = 'um farol assombrado';
        window.__gerando = generateLore(); }""")
    pg.wait_for_function("() => document.querySelector('#wz-ai-btn .pena-gerando')", timeout=3000)
    assert pg.is_disabled("#wz-ai-btn")
    pg.wait_for_timeout(200)
    assert liberar, "o pedido não saiu"
    liberar[0].fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "lore": {
        "story_summary": "Um farol que acende sozinho.", "current_scene": "A tempestade chega.",
        "current_location": "O Farol", "locations": [{"name": "O Farol", "description": "Na ponta"}]}}))
    pg.evaluate("async () => { await window.__gerando; }")
    r = pg.evaluate("""() => ['wz-summary', 'wz-scene', 'wz-location'].map(id => {
        const el = document.getElementById(id);
        return [el.value, el.classList.contains('campo-preenchido'), el.style.getPropertyValue('--i')]; })""")
    assert [x[1] for x in r] == [True, True, True], r
    assert [x[2] for x in r] == ["0", "1", "2"], r
    assert pg.text_content("#wz-ai-btn").strip() == "Gerar com IA"
    assert pg.locator("#wz-ai-btn .pena-gerando").count() == 0
    assert not erros, erros[:3]


def test_barra_a_contagem_do_atalho_pulsa_e_o_progresso_da_missao_desliza(app_no_ar, abrir):
    _, _, cap = app_no_ar
    antes = _com_relogio(cap, 4, 16)
    antes["quests"]["a audiencia real"]["objetivos"] = [
        {"texto": "Chegar ao palácio", "feito": False}, {"texto": "Falar com Elara", "feito": False}]
    depois = copy.deepcopy(antes)
    depois["quests"]["a audiencia real"]["objetivos"][0]["feito"] = True
    depois["quests"]["o ladrao de reliquias"] = {
        "titulo": "O ladrão de relíquias", "status": "ativa", "descricao": "", "objetivos": [],
        "quem_deu": "", "recompensa": "", "cap_inicio": 1}
    pg, erros, trocar, voltar = _romance(app_no_ar, abrir, antes)
    try:
        pg.wait_for_selector("#sb-atalho-missoes .sb-atalho-conta", timeout=8000)
        trocar(depois)
        r = pg.evaluate("""async () => {
            await refreshMemory();
            const conta = document.querySelector('#sb-atalho-missoes .sb-atalho-conta');
            const trilho = document.querySelector('#sb-missao .sb-missao-trilho > span');
            return [conta.className, trilho.style.width,
                    document.querySelector('#sb-missao .sb-missao-conta').className];
        }""")
        assert "num-subiu" in r[0], r
        assert r[1] == "0%", r              # parte de onde estava...
        assert "num-subiu" in r[2], r
        pg.wait_for_function("() => document.querySelector('#sb-missao .sb-missao-trilho > span').style.width === '50%'",
                             timeout=3000)       # ...e chega à metade
        assert not erros, erros[:3]
    finally:
        voltar()
