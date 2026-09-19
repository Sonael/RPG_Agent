"""
test_editor_genero_navegador.py

O editor da campanha (menu) com as mudanças de gênero:

  • as mecânicas de cada personagem aparecem e se editam: afeto, confiança e
    estágio no romance; lealdade, objetivo e arco na fantasia. Antes eram
    guardadas mas invisíveis;
  • o protagonista é marcado no cartão, como no wizard. Era um campo de texto
    livre, que aceitava um nome que não existe;
  • no romance, "O que você sabe" e "fica com você", não "o grupo";
  • quem foi recrutado no jogo (party_member) aparece no grupo. Antes
    aparecia desmarcado, e salvar sem mexer em nada o tirava do grupo;
  • sem as regras de D&D, salvar não apaga mochila e habilidades (iam vazias);
  • as notas do local aparecem e se editam.

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

ROMANCE = {
    "campaign_type": "romance", "dnd_mode": False, "protagonist": "Clara",
    "current_location": "Café Aurora",
    "characters": {
        "clara":  {"name": "Clara", "description": "Fotógrafa.", "status": "vivo"},
        "lucas":  {"name": "Lucas", "description": "O vizinho.", "status": "vivo", "role": "vizinho",
                   "vinculo": "interesse romântico", "atitude": 45, "confianca": -20, "estagio": "flerte",
                   "inventario": [{"nome": "Carta de amor", "qtd": 1, "descricao": ""}],
                   "habilidades": [{"nome": "Tocar violão", "descricao": ""}]},
        "helena": {"name": "Helena", "description": "A ex.", "status": "vivo", "atitude": -30},
        "rafa":   {"name": "Rafa", "description": "O amigo.", "status": "vivo", "party_member": True},
    },
    "party": [{"name": "Clara", "role": ""}, {"name": "Lucas", "role": "vizinho"}],
    "locations": {"café aurora": {"name": "Café Aurora", "description": "Pequeno.", "details": "",
                                  "notes": "O dono vende o café em março"}},
    "events": [],
}

FANTASIA = {
    "campaign_type": "fantasia", "dnd_mode": False, "protagonist": "Alden",
    "current_location": "Cliviate",
    "characters": {
        "alden": {"name": "Alden", "description": "Guerreiro.", "status": "vivo"},
        "lyra":  {"name": "Lyra", "description": "Patrulheira.", "status": "vivo", "lealdade": 70,
                  "objetivo": "Achar a mãe",
                  "arco": {"titulo": "Voltar à floresta", "estado": "em curso",
                           "passos": [{"texto": "Achou o mapa", "cap": 2}]}},
        "brom":  {"name": "Brom", "description": "Ferreiro.", "status": "vivo"},
    },
    "party": [{"name": "Alden", "role": ""}, {"name": "Lyra", "role": "batedora"}],
    "locations": {"cliviate": {"name": "Cliviate", "description": "Cidade.", "details": "", "notes": ""}},
    "events": [],
}


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
def editor(app_no_ar, monkeypatch):
    """Abre o editor com a campanha pedida no lugar da do servidor."""
    from playwright.sync_api import sync_playwright
    from rpg import database

    url, nome, cap = app_no_ar
    gravado = {}
    monkeypatch.setattr(database, "save_campaign", lambda uid, n, dados: gravado.update(dados))
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        ctx = nav.new_context(viewport={"width": 1440, "height": 980})
        ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO))
        pg = ctx.new_page()
        erros = []
        pg.on("pageerror", lambda e: erros.append(str(e)))

        def abrir(campanha):
            original = database.get_campaign

            def trocada(uid, n):
                base = original(uid, n)
                if base is None:
                    return None
                return {**base, **copy.deepcopy(campanha), "name": base.get("name", n)}

            monkeypatch.setattr(database, "get_campaign", trocada)
            pg.goto(f"{url}/menu.html", wait_until="networkidle")
            cap._sanear(pg)
            pg.evaluate("(n) => openEditCampaign({stopPropagation(){}}, n)", nome)
            pg.wait_for_function("() => typeof edChars !== 'undefined' && edChars.length > 0", timeout=8000)
            pg.evaluate("() => { editGoTo(2); edChars.forEach(c => c._open = true); edRenderChars(); }")
            pg.wait_for_timeout(300)
            return pg

        yield abrir, erros, gravado
        nav.close()


def _cartao(pg, nome):
    i = pg.evaluate("(n) => edChars.findIndex(c => c.name === n)", nome)
    assert i >= 0, nome
    return pg.locator(f"#ed-cc-{i}"), i


def _salvar(pg):
    pg.evaluate("() => { saveEditedCampaign(); }")
    pg.wait_for_selector("#dialog-overlay:not(.hidden)", timeout=10000)
    assert "salva com sucesso" in pg.inner_text("#dialog-overlay")


def _mudar(campo, valor):
    if campo.evaluate("e => e.tagName") == "SELECT":
        campo.select_option(valor)
    else:
        campo.fill(str(valor))
        campo.dispatch_event("change")


def test_romance_mostra_protagonista_relacao_e_frases(editor):
    abrir, erros, _ = editor
    pg = abrir(ROMANCE)
    assert pg.locator("#ed-protagonist").count() == 0

    clara, _ = _cartao(pg, "Clara")
    assert clara.locator(".ed-protagonista").is_checked()
    assert clara.locator(".cwc-voce").count() == 1
    assert clara.locator(".wz-campos-mec").count() == 0          # você não tem relação com você

    lucas, i = _cartao(pg, "Lucas")
    assert lucas.locator(".wz-campos-mec [data-campo='afeto'] input").input_value() == "45"
    assert lucas.locator(".wz-campos-mec [data-campo='confianca'] input").input_value() == "-20"
    assert lucas.locator(".wz-campos-mec [data-campo='estagio'] select").input_value() == "Flerte"
    # O "Relacionamento" é o vínculo que as Relações mostram.
    assert pg.evaluate("(i) => edChars[i].role", i) == "interesse romântico"
    assert "O que você sabe" in lucas.inner_text() and "grupo sabe" not in lucas.inner_text()
    assert lucas.locator(".ed-onde-esta").get_attribute("placeholder") == "fica com você no Local Atual"

    rafa, _ = _cartao(pg, "Rafa")
    assert rafa.locator(".ed-no-grupo").is_checked(), "recrutado no jogo aparecia fora do grupo"
    assert not erros, erros[:3]


def test_romance_salva_relacao_grupo_e_protagonista(editor):
    abrir, erros, gravado = editor
    pg = abrir(ROMANCE)
    lucas, i = _cartao(pg, "Lucas")
    _mudar(lucas.locator(".wz-campos-mec [data-campo='afeto'] input"), 60)
    _mudar(lucas.locator(".wz-campos-mec [data-campo='estagio'] select"), "Namoro")
    pg.evaluate("(i) => { edChars[i].role = 'namorado'; }", i)
    rafa, _ = _cartao(pg, "Rafa")
    rafa.locator(".ed-no-grupo").uncheck()
    _salvar(pg)

    chars = gravado["characters"]
    assert (chars["lucas"]["atitude"], chars["lucas"]["confianca"], chars["lucas"]["estagio"]) == (60, -20, "namoro")
    assert chars["lucas"]["vinculo"] == "namorado"
    assert chars["helena"]["atitude"] == -30
    assert chars["rafa"]["party_member"] is False, "desmarcar não tirou do grupo quem foi recrutado"
    assert {p["name"] for p in gravado["party"]} == {"Clara", "Lucas"}
    assert gravado["protagonist"] == "Clara"
    assert not erros, erros[:3]


def test_salvar_sem_mexer_nao_perde_nada(editor):
    """
    Dois defeitos do editor que salvar sem tocar em nada mostrava:
      • quem foi recrutado no jogo aparecia desmarcado e saía do grupo;
      • sem as regras de D&D, mochila e habilidades iam vazias e apagavam o
        que havia.
    """
    abrir, erros, gravado = editor
    pg = abrir(ROMANCE)
    _salvar(pg)
    chars = gravado["characters"]
    assert chars["rafa"]["party_member"] is True, "salvar tirou do grupo quem foi recrutado"
    assert {p["name"] for p in gravado["party"]} == {"Clara", "Lucas", "Rafa"}
    assert chars["lucas"]["inventario"] == [{"nome": "Carta de amor", "qtd": 1, "descricao": ""}]
    assert chars["lucas"]["habilidades"] == [{"nome": "Tocar violão", "descricao": ""}]
    assert (chars["lucas"]["atitude"], chars["lucas"]["estagio"]) == (45, "flerte")
    assert not erros, erros[:3]


def test_trocar_o_protagonista_no_cartao(editor):
    abrir, erros, gravado = editor
    pg = abrir(ROMANCE)
    lucas, _ = _cartao(pg, "Lucas")
    lucas.locator(".ed-protagonista").check()
    assert pg.evaluate("() => edChars.filter(c => c.protagonista).map(c => c.name)") == ["Lucas"]
    lucas, _ = _cartao(pg, "Lucas")
    assert lucas.locator(".wz-campos-mec").count() == 0
    clara, _ = _cartao(pg, "Clara")
    assert clara.locator(".wz-campos-mec").count() == 1
    _salvar(pg)
    assert gravado["protagonist"] == "Lucas"
    # O afeto do Lucas não foi mandado (agora ele é você) e continua gravado.
    assert gravado["characters"]["lucas"]["atitude"] == 45
    assert not erros, erros[:3]


def test_fantasia_edita_o_laco_sem_perder_o_arco(editor):
    abrir, erros, gravado = editor
    pg = abrir(FANTASIA)
    lyra, _ = _cartao(pg, "Lyra")
    assert lyra.locator(".wz-campos-mec [data-campo='lealdade'] input").input_value() == "70"
    assert lyra.locator(".wz-campos-mec [data-campo='arco'] input").input_value() == "Voltar à floresta"
    assert "O que o grupo sabe" in lyra.inner_text()
    brom, _ = _cartao(pg, "Brom")
    assert brom.locator(".wz-campos-mec").count() == 0             # não é do grupo
    alden, _ = _cartao(pg, "Alden")
    assert alden.locator(".wz-campos-mec").count() == 0            # é você

    _mudar(lyra.locator(".wz-campos-mec [data-campo='lealdade'] input"), 40)
    _mudar(lyra.locator(".wz-campos-mec [data-campo='arco'] input"), "Voltar para casa")
    _salvar(pg)
    lyra_g = gravado["characters"]["lyra"]
    assert lyra_g["lealdade"] == 40 and lyra_g["objetivo"] == "Achar a mãe"
    assert lyra_g["arco"] == {"titulo": "Voltar para casa", "estado": "em curso",
                              "passos": [{"texto": "Achou o mapa", "cap": 2}]}, "o arco perdeu os passos"
    assert not erros, erros[:3]


def test_notas_do_local_aparecem_e_se_editam(editor):
    abrir, erros, gravado = editor
    pg = abrir(ROMANCE)
    pg.evaluate("() => editGoTo(3)")
    pg.wait_for_timeout(300)
    campo = pg.locator("#ed-locs-list .wz-loc-card >> nth=0 >> .ed-loc-notas")
    assert campo.input_value() == "O dono vende o café em março"
    _mudar(campo, "O dono vende o café em abril")
    _salvar(pg)
    assert gravado["locations"]["café aurora"]["notes"] == "O dono vende o café em abril"
    assert not erros, erros[:3]
