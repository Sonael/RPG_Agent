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


# --- Passo 4: o mundo do gênero ------------------------------------------------
# Segredos, tensões e encontros (romance); renome, facções, títulos, lendas e
# bestiário (fantasia). Antes só o jogo mexia nisso: o editor preservava, mas
# não mostrava.

ROMANCE_MUNDO = copy.deepcopy(ROMANCE)
ROMANCE_MUNDO.update({
    "relogio": {"dia": 6, "hora": 15},
    "segredos": {
        "a bolsa em lisboa": {"titulo": "A bolsa em Lisboa", "descricao": "Vai embora em março", "dono": "",
                              "escondido_de": ["Lucas"], "sabem": ["Helena"], "revelado": False, "como": "",
                              "dono_sabe": True, "cap": 2, "historico": [{"delta": -5, "motivo": "quase contou"}]},
        "o irmão na prisão": {"titulo": "O irmão na prisão", "descricao": "", "dono": "Lucas", "escondido_de": [],
                              "sabem": [], "revelado": True, "como": "descobriu", "dono_sabe": False,
                              "cap": 3, "cap_revelado": 4, "historico": []},
    },
    "tensoes": {"helena|lucas": {"a": "Helena", "b": "Lucas", "tipo": "ciume", "intensidade": 60,
                                 "percebida": False, "historico": [{"delta": 20, "motivo": "o baile"}], "cap": 2}},
    "encontros": [{"id": 1, "com": "Lucas", "dia": 7, "hora": 20, "onde": "Café Aurora", "o_que": "jantar",
                   "estado": "marcado", "cap": 3}],
})

FANTASIA_MUNDO = copy.deepcopy(FANTASIA)
FANTASIA_MUNDO.update({
    "renome": {"valor": 12, "historico": [{"delta": 12, "motivo": "a emboscada"}]},
    "faccoes": {"guarda de cliviate": {"nome": "Guarda de Cliviate", "tipo": "cidade", "descricao": "A milícia.",
                                       "reputacao": 20, "conhecida": True,
                                       "historico": [{"delta": 20, "motivo": "salvaram o portão"}], "cap": 1}},
    "titulos": [{"titulo": "Os do Portão", "quem": "o grupo", "motivo": "salvaram o portão", "efeito": "", "cap": 1}],
    "lendas": {"o lobo branco": {"titulo": "O Lobo Branco", "tipo": "lenda", "verdade": "É o prefeito",
                                 "fragmentos": [{"texto": "Caça na lua nova", "fonte": "o ferreiro", "cap": 2}],
                                 "conhecida": True, "desfecho": "", "cap": 1}},
    "bestiario": {"lobo das brumas": {"nome": "Lobo das Brumas", "tipo": "fera", "descricao": "Enorme.",
                                      "fatos": [{"texto": "Anda em matilha", "cap": 2}], "fraquezas": [],
                                      "encontros": 2, "derrotadas": 1, "cap": 1}},
})


def _genero(pg, genero):
    pg.evaluate("() => editGoTo(1)")
    pg.select_option("#ed-type", genero)


def _passo_4(pg):
    pg.evaluate("() => editGoTo(4)")
    pg.wait_for_selector("#ed-panel-4:not(.hidden) .ed-mundo-colecao", timeout=5000)


def _item(pg, colecao, i):
    return pg.locator(f".ed-mundo-colecao[data-colecao='{colecao}'] .ed-mundo-item").nth(i)


def _campo(item, campo):
    return item.locator(f"[data-campo='{campo}'] :is(input, select, textarea)")


def test_passo_4_so_no_romance_e_na_fantasia(editor):
    abrir, erros, _ = editor
    pg = abrir(ROMANCE_MUNDO)
    assert pg.is_visible("#ed-dot-4") and pg.inner_text("#ed-dot-4-nome") == "Relações"
    _genero(pg, "horror")
    pg.evaluate("() => editGoTo(3)")
    assert not pg.is_visible("#ed-dot-4")
    assert pg.is_visible("#ed-save-btn") and not pg.is_visible("#ed-next-btn")
    _genero(pg, "fantasia")
    assert pg.inner_text("#ed-dot-4-nome") == "Mundo"
    assert pg.is_visible("#ed-next-btn") and not pg.is_visible("#ed-save-btn")
    assert not erros, erros[:3]


def test_romance_edita_segredos_tensoes_e_encontros(editor):
    abrir, erros, gravado = editor
    pg = abrir(ROMANCE_MUNDO)
    _passo_4(pg)

    bolsa, irmao = _item(pg, "segredos", 0), _item(pg, "segredos", 1)
    assert _campo(bolsa, "titulo").input_value() == "A bolsa em Lisboa"
    assert _campo(bolsa, "escondido_de").input_value() == "Lucas"
    assert _campo(irmao, "dono").input_value() == "Lucas"
    assert _campo(irmao, "como").input_value() == "descobriu"
    tensao = _item(pg, "tensoes", 0)
    assert _campo(tensao, "intensidade").input_value() == "60"
    assert not _campo(tensao, "percebida").is_checked()
    assert _campo(_item(pg, "encontros", 0), "dia").input_value() == "7"

    _mudar(_campo(bolsa, "sabem"), "Helena, Rafa")
    _mudar(_campo(irmao, "como"), "")
    _mudar(_campo(tensao, "intensidade"), 150)                  # passa do teto
    assert _campo(tensao, "intensidade").input_value() == "100"
    _campo(tensao, "percebida").check()
    pg.click(".ed-mundo-colecao[data-colecao='encontros'] button:has-text('+ Encontro')")
    novo = _item(pg, "encontros", 1)
    for campo, valor in (("com", "Rafa"), ("o_que", "cinema"), ("dia", 8), ("hora", 19)):
        _mudar(_campo(novo, campo), valor)
    _salvar(pg)

    seg = gravado["segredos"]
    assert seg["a bolsa em lisboa"]["sabem"] == ["Helena", "Rafa"]
    assert seg["a bolsa em lisboa"]["historico"] == [{"delta": -5, "motivo": "quase contou"}], "perdeu o histórico"
    assert seg["o irmao na prisao"]["revelado"] is False             # chave como o jogo grava: sem acento
    t = gravado["tensoes"]["helena|lucas"]
    assert (t["intensidade"], t["percebida"], t["historico"]) == (100, True, [{"delta": 20, "motivo": "o baile"}])
    assert [(e["com"], e["o_que"], e["dia"], e["hora"]) for e in gravado["encontros"]] == \
        [("Lucas", "jantar", 7, 20), ("Rafa", "cinema", 8, 19)]
    assert not erros, erros[:3]


def test_remover_um_segredo(editor):
    abrir, erros, gravado = editor
    pg = abrir(ROMANCE_MUNDO)
    _passo_4(pg)
    _item(pg, "segredos", 0).locator("button[aria-label='Remover']").click()
    assert pg.locator(".ed-mundo-colecao[data-colecao='segredos'] .ed-mundo-item").count() == 1
    _salvar(pg)
    assert list(gravado["segredos"]) == ["o irmao na prisao"]
    assert not erros, erros[:3]


def test_fantasia_edita_renome_faccoes_lendas_e_bestiario(editor):
    abrir, erros, gravado = editor
    pg = abrir(FANTASIA_MUNDO)
    _passo_4(pg)
    renome = pg.locator(".ed-mundo-colecao[data-colecao='renome'] [data-campo='valor'] input")
    assert renome.input_value() == "12"
    lenda = _item(pg, "lendas", 0)
    assert _campo(lenda, "fragmentos").input_value() == "Caça na lua nova | o ferreiro"
    assert _campo(lenda, "verdade").input_value() == "É o prefeito"

    _mudar(renome, 30)
    _mudar(_campo(_item(pg, "faccoes", 0), "reputacao"), -10)
    _mudar(_campo(lenda, "fragmentos"), "Caça na lua nova | o ferreiro\nUivos no norte | o guarda")
    _mudar(_campo(_item(pg, "bestiario", 0), "fraquezas"), "Prata\nFogo")
    _mudar(_campo(_item(pg, "titulos", 0), "efeito"), "A guarda abre o portão à noite")
    _salvar(pg)

    assert gravado["renome"]["valor"] == 30
    assert gravado["renome"]["historico"] == [{"delta": 12, "motivo": "a emboscada"}]
    guarda = gravado["faccoes"]["guarda de cliviate"]
    assert guarda["reputacao"] == -10 and guarda["historico"][0]["motivo"] == "salvaram o portão"
    frags = gravado["lendas"]["o lobo branco"]["fragmentos"]
    assert frags == [{"texto": "Caça na lua nova", "fonte": "o ferreiro", "cap": 2},
                     {"texto": "Uivos no norte", "fonte": "o guarda", "cap": 1}]
    assert [n["texto"] for n in gravado["bestiario"]["lobo das brumas"]["fraquezas"]] == ["Prata", "Fogo"]
    assert gravado["bestiario"]["lobo das brumas"]["fatos"] == [{"texto": "Anda em matilha", "cap": 2}]
    assert gravado["titulos"][0]["efeito"] == "A guarda abre o portão à noite"
    assert not erros, erros[:3]


def test_trocar_de_genero_nao_apaga_o_mundo_do_outro(editor):
    abrir, erros, gravado = editor
    pg = abrir(ROMANCE_MUNDO)
    _genero(pg, "fantasia")
    _salvar(pg)
    assert list(gravado["segredos"]) == ["a bolsa em lisboa", "o irmão na prisão"]
    assert gravado["tensoes"]["helena|lucas"]["intensidade"] == 60
    assert not erros, erros[:3]


def test_numero_vazio_nao_apaga_o_encontro(editor):
    abrir, erros, gravado = editor
    pg = abrir(ROMANCE_MUNDO)
    _passo_4(pg)
    dia = _campo(_item(pg, "encontros", 0), "dia")
    _mudar(dia, "")
    assert dia.input_value() == "7"
    _salvar(pg)
    assert gravado["encontros"][0]["dia"] == 7
    assert not erros, erros[:3]
