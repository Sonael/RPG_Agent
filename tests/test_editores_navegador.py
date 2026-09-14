"""
test_editores_navegador.py

`test_regras_e_editores.py` prova no motor que as tabelas saem de um lugar só
e que o salvamento protege a ficha. Isto aqui prova o que só o navegador vê:

  • o menu e o jogo leem as regras do motor (paladino de nível 3 com círculo
    máximo 1, guerreiro de nível 6 com 2 incrementos — a tabela fixa dava 1);
  • no editor da campanha e no "Editar Ficha Completa", uma ficha em jogo
    mostra nível, atributos, CA e equipamento travados, com o aviso das telas;
  • vida atual continua editável, e o Modo de correção destrava;
  • salvar sem correção não muda o nível mesmo que o campo seja forçado, e com
    correção muda;
  • os atalhos abrem a Mochila e o Grimório.

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
def navegador(app_no_ar):
    from playwright.sync_api import sync_playwright
    import requests

    url, nome, cap = app_no_ar
    with sync_playwright() as pw:
        nav = pw.chromium.launch()

        def abrir(pagina, estado=None):
            requests.post(f"{url}/__estado", json=estado or {}, timeout=10)
            ctx = nav.new_context(viewport={"width": 1440, "height": 980})
            ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO))
            pg = ctx.new_page()
            erros = []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
            pg.goto(f"{url}{pagina}", wait_until="networkidle")
            cap._sanear(pg)
            pg.wait_for_timeout(700)
            pg.nome_campanha = nome
            return pg, erros

        yield abrir
        nav.close()


def _personagem_da_memoria(pg, nome):
    return pg.evaluate(
        """async (n) => {
            const m = await (await authFetch((window.API || '') + '/api/memory')).json();
            return [...(m.party || []), ...(m.characters || [])]
              .find(c => (c.name || '').toLowerCase() === n.toLowerCase());
        }""", nome)


def _abrir_ficha_no_jogo(pg, nome="Helena"):
    pg.evaluate(
        """async (n) => {
            const c = [...(window._lastMem.characters || []), ...(window._lastMem.party || [])]
              .find(x => (x.name || '').toLowerCase() === n.toLowerCase() && x.sheet);
            await openEditModal('character', n.toLowerCase(), c);
        }""", nome)
    pg.wait_for_selector("#edit-overlay:not(.hidden)", timeout=5000)
    pg.wait_for_timeout(300)


# ---- as regras vêm do motor ------------------------------------------------

def test_menu_le_as_regras_do_motor(navegador):
    pg, erros = navegador("/menu.html")
    r = pg.evaluate("""async () => {
        await Regras.carregar();
        return {
          paladino3: edMaxSpellLevel(3, 'paladino'),
          guerreiro6: edAsiCount(6, 'guerreiro'),
          mago6: edAsiCount(6, 'mago'),
          prof5: edProfForLevel(5),
          limite: getSpellLimit('clérigo', 1),
          circuloCusto5: Regras.nivelPorCusto(5),
        };
    }""")
    assert r["paladino3"] == 1
    # Guerreiro: 4 e 6 até o nível 6; a tabela fixa do navegador dava só o 4.
    assert r["guerreiro6"] == 2 and r["mago6"] == 1
    assert r["prof5"] == 3
    assert r["limite"] == {"maxCantrips": 3, "maxSpells": 3}
    assert r["circuloCusto5"] == 3
    assert not erros, erros[:3]


def test_jogo_le_as_regras_do_motor(navegador):
    pg, erros = navegador("/game.html")
    r = pg.evaluate("""async () => {
        await Regras.carregar();
        return { paladino3: gameMaxSpellLevel(3, 'paladino'), xp4: gameXpForNextLevel(4) };
    }""")
    assert r == {"paladino3": 1, "xp4": 6500}
    assert not erros, erros[:3]


# ---- editor da campanha (menu) ---------------------------------------------

def _abrir_editor_da_campanha(pg, nome_personagem="Helena"):
    pg.evaluate("(n) => openEditCampaign({stopPropagation(){}}, n)", pg.nome_campanha)
    pg.wait_for_function("() => (window.edChars || []).length > 0 || typeof edChars !== 'undefined' && edChars.length > 0",
                         timeout=8000)
    i = pg.evaluate("(n) => edChars.findIndex(c => c.name.toLowerCase() === n.toLowerCase())",
                    nome_personagem)
    # Os personagens ficam no passo 2 do editor.
    pg.evaluate("(i) => { editGoTo(2); edChars[i]._open = true; edRenderChars(); }", i)
    pg.wait_for_timeout(400)
    return i


def test_editor_da_campanha_trava_a_ficha_em_jogo(navegador):
    pg, erros = navegador("/menu.html")
    i = _abrir_editor_da_campanha(pg)
    secao = f"#ed-dnd-sections-{i}"
    assert pg.is_visible(f"{secao} .ed-aviso-regras")
    assert "Ficha em jogo" in pg.inner_text(f"{secao} .ed-aviso-regras")
    nivel = pg.locator(f"{secao} fieldset.ed-trava input[type='number']").first
    assert nivel.is_disabled(), "campo de construção editável numa ficha em jogo"
    # Vida atual fora da trava.
    vida_atual = pg.locator(f"{secao} input[onchange*=\"'vida_atual'\"]")
    assert vida_atual.is_enabled()
    assert not erros, erros[:3]


def test_modo_de_correcao_destrava_no_menu(navegador):
    pg, _ = navegador("/menu.html")
    i = _abrir_editor_da_campanha(pg)
    pg.click(f"#ed-dnd-sections-{i} input.ed-correcao")
    pg.wait_for_timeout(300)
    assert pg.locator(f"#ed-dnd-sections-{i} fieldset.ed-trava").count() == 0
    assert "Modo de correção" in pg.inner_text(f"#ed-dnd-sections-{i} .ed-aviso-correcao")


def test_personagem_novo_no_menu_nao_e_travado(navegador):
    pg, _ = navegador("/menu.html")
    _abrir_editor_da_campanha(pg)
    pg.evaluate("() => { addEditChar(); const j = edChars.length - 1; edChars[j]._open = true; edRenderChars(); }")
    pg.wait_for_timeout(300)
    j = pg.evaluate("() => edChars.length - 1")
    assert pg.locator(f"#ed-dnd-sections-{j} fieldset.ed-trava").count() == 0


# ---- Editar Ficha Completa (jogo) ------------------------------------------

def test_ficha_completa_trava_e_mostra_os_atalhos(navegador):
    pg, erros = navegador("/game.html")
    _abrir_ficha_no_jogo(pg)
    assert pg.is_visible("#edit-body .ed-aviso-regras")
    assert pg.is_disabled("#ef-sheet_nivel")
    assert pg.is_disabled("#ef-sheet_ca")
    assert pg.is_disabled("#ef-sheet_forca")
    assert pg.is_disabled("#ef-sheet_eq_armadura")
    assert pg.is_enabled("#ef-sheet_vida_atual")
    assert pg.is_visible("text=Abrir Mochila")
    assert pg.is_visible("text=Abrir Grimório")
    assert not erros, erros[:3]


def test_salvar_sem_correcao_nao_muda_o_nivel_mesmo_forcado(navegador):
    pg, _ = navegador("/game.html")
    antes = _personagem_da_memoria(pg, "Helena")["sheet"]
    _abrir_ficha_no_jogo(pg)
    # Força o campo travado por JS, como faria um cliente antigo em cache.
    pg.evaluate("() => { document.getElementById('ef-sheet_nivel').value = '12';"
                " document.getElementById('ef-sheet_vida_atual').value = '5'; }")
    pg.evaluate("() => saveCurrentItem()")
    pg.wait_for_timeout(1200)
    depois = _personagem_da_memoria(pg, "Helena")["sheet"]
    assert depois["nivel"] == antes["nivel"], "o nível forçado passou"
    assert depois["vida_atual"] == 5, "a vida atual, que é livre, não foi gravada"


def test_salvar_com_correcao_grava(navegador):
    pg, _ = navegador("/game.html")
    _abrir_ficha_no_jogo(pg)
    pg.click("#edit-body input.ed-correcao")
    pg.wait_for_timeout(300)
    assert pg.is_enabled("#ef-sheet_ca")
    pg.fill("#ef-sheet_ca", "19")
    pg.evaluate("() => saveCurrentItem()")
    pg.wait_for_timeout(1200)
    assert _personagem_da_memoria(pg, "Helena")["sheet"]["ca"] == 19


def test_ligar_correcao_nao_perde_o_que_foi_digitado(navegador):
    pg, _ = navegador("/game.html")
    _abrir_ficha_no_jogo(pg)
    pg.fill("#ef-notes", "deve favor ao ferreiro")
    pg.click("#edit-body input.ed-correcao")
    pg.wait_for_timeout(300)
    assert pg.input_value("#ef-notes") == "deve favor ao ferreiro"


def test_atalho_abre_a_mochila(navegador):
    pg, _ = navegador("/game.html")
    _abrir_ficha_no_jogo(pg)
    pg.click("text=Abrir Mochila")
    pg.wait_for_selector("#inventory-overlay:not(.hidden)", timeout=5000)
    assert not pg.is_visible("#edit-overlay")
    # O overlay aparece antes de o estado chegar: o nome entra no título depois.
    pg.wait_for_function("() => document.querySelector('.inv-title').textContent.includes('Helena')",
                         timeout=5000)


# ---- mesma moldura das telas -----------------------------------------------

_PAPEL = "rgb(255, 251, 240)"      # --tl-paper, o mesmo #fffbf0 das telas
_VERMELHO = "rgb(139, 35, 21)"     # --tl-red, o do botão Concluir da Ascensão


def _estilo(pg, seletor, *props):
    return pg.evaluate(
        """([s, props]) => { const cs = getComputedStyle(document.querySelector(s));
                             return props.map(p => cs.getPropertyValue(p)); }""",
        [seletor, list(props)])


def test_wizard_usa_a_moldura_das_telas_mesmo_com_tema_escuro(navegador):
    pg, erros = navegador("/menu.html")
    pg.evaluate("() => { document.documentElement.setAttribute('data-theme', 'noite-tinta'); openWizard(); }")
    pg.wait_for_selector("#wizard-overlay:not(.hidden)", timeout=5000)
    fundo, borda = _estilo(pg, "#wizard-box", "background-color", "border-top-color")
    assert fundo == _PAPEL, "o wizard seguiu o tema em vez da paleta das telas"
    assert borda == "rgb(184, 153, 71)"
    assert _estilo(pg, "#wz-next-btn", "background-color") == [_VERMELHO]
    assert "Caveat" not in _estilo(pg, "#wz-name", "font-family")[0]
    assert not erros, erros[:3]


def test_editor_da_campanha_e_do_jogo_usam_a_moldura(navegador):
    pg, _ = navegador("/menu.html")
    _abrir_editor_da_campanha(pg)
    assert _estilo(pg, ".edit-campaign-box", "background-color") == [_PAPEL]
    assert _estilo(pg, "#ed-save-btn, #ed-next-btn", "background-color") == [_VERMELHO]

    pg, _ = navegador("/game.html")
    _abrir_ficha_no_jogo(pg)
    assert _estilo(pg, "#edit-overlay .edit-box", "background-color") == [_PAPEL]
    assert _estilo(pg, "#edit-overlay .btn-salvar-item", "background-color") == [_VERMELHO]
    assert _estilo(pg, "#edit-name", "color") == [_VERMELHO]


def test_npc_continua_editavel(navegador):
    pg, _ = navegador("/game.html")
    pg.evaluate("""async () => {
        const c = { name: 'Goblin Teste', description: '', traits: '', status: 'inimigo', notes: '',
                    sheet: { classe: 'npc', raca: 'goblin', nivel: 1, ca: 13, vida_atual: 7, vida_max: 7,
                             mana_atual: 0, mana_max: 0, forca: 8, destreza: 14, constituicao: 10,
                             inteligencia: 10, sabedoria: 8, carisma: 8, equipamentos: {} } };
        await openEditModal('character', 'goblin teste', c);
    }""")
    pg.wait_for_timeout(300)
    assert pg.locator("#edit-body fieldset.ed-trava").count() == 0
    assert pg.is_enabled("#ef-sheet_ca")
