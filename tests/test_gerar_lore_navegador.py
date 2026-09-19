"""
test_gerar_lore_navegador.py

Clica em "Gerar com IA" no wizard com uma resposta realista (a rota é
interceptada: os testes não têm chave de API) e confere que cada campo que a
IA manda aparece no wizard e segue para a criação.

Defeitos que isto cobre:
  • "Personagens envolvidos" do evento era descartado, e a criação gravava o
    grupo inteiro em todos os eventos;
  • as notas dos locais iam para a campanha sem aparecer para revisar;
  • "4 personagems".

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

LORE = {
    "story_summary": "Cliviate, cidade de muralhas baixas na borda da Floresta das Brumas, sofre com "
                     "desaparecimentos.",
    "current_scene": "Chuva fina na praça; o sino da capela toca fora de hora.",
    "current_location": "Praça de Cliviate",
    "locations": [
        {"name": "Cliviate", "description": "Cidade murada.", "details": "Portão norte",
         "notes": "Prefeito esconde algo", "dentro_de": ""},
        {"name": "Praça de Cliviate", "description": "Poço antigo.", "details": "Feira às quintas",
         "notes": "", "dentro_de": "Cliviate"},
        {"name": "Floresta das Brumas", "description": "Neblina constante.", "details": "Trilhas somem",
         "notes": "Covil dos lobos", "dentro_de": ""},
    ],
    "events": [
        {"summary": "Três lenhadores sumiram na floresta.", "location": "Floresta das Brumas",
         "characters_involved": "Brom", "consequence": "A cidade fechou o portão à noite."},
        {"summary": "Uivos perto da muralha.", "location": "Cliviate",
         "characters_involved": "", "consequence": "Guardas dobraram a vigília."},
    ],
    "characters": [
        {"name": "Alden", "description": "Guerreiro de cicatriz.", "traits": "Protetor",
         "notes": "Busca o irmão", "role": "Tanque", "tipo": "jogador",
         "classe": "guerreiro", "raca": "humano", "local": ""},
        {"name": "Lyra", "description": "Patrulheira silenciosa.", "traits": "Observadora",
         "notes": "Cresceu na floresta", "role": "Batedora", "tipo": "jogador",
         "classe": "patrulheiro", "raca": "elfo", "local": ""},
        {"name": "Brom", "description": "Ferreiro corpulento.", "traits": "Rabugento",
         "notes": "O filho sumiu", "role": "Contratante", "tipo": "aliado",
         "classe": "npc", "raca": "commoner", "local": "Praça de Cliviate"},
        {"name": "Lobo das Brumas", "description": "Lobo enorme.", "traits": "Faminto",
         "notes": "Guia a matilha", "role": "Ameaça", "tipo": "inimigo",
         "classe": "npc", "raca": "dire-wolf", "local": "Floresta das Brumas"},
    ],
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
def wizard(app_no_ar):
    from playwright.sync_api import sync_playwright

    url, nome, cap = app_no_ar
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        pg = nav.new_page(viewport={"width": 1440, "height": 980})
        pg.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO))
        erros = []
        pg.on("pageerror", lambda e: erros.append(str(e)))
        estado = {"lore": {"ok": True, "lore": LORE}, "status": 200, "criacao": {}}

        pg.route("**/api/campaigns/generate-lore",
                 lambda r: r.fulfill(status=estado["status"], content_type="application/json",
                                     body=json.dumps(estado["lore"])))

        def criar(route, request):
            if request.method == "POST":
                estado["criacao"].update(json.loads(request.post_data or "{}"))
                route.fulfill(status=400, content_type="application/json",
                              body=json.dumps({"error": "interceptado pelo teste"}))
            else:
                route.continue_()

        pg.route("**/api/campaigns", criar)
        pg.goto(f"{url}/menu.html", wait_until="networkidle")
        cap._sanear(pg)
        pg.evaluate("() => openWizard()")
        pg.fill("#wz-name", "Desaparecimentos")
        # Regras e gênero são dois seletores: D&D é regra, não gênero.
        pg.select_option("#wz-type", "fantasia")
        pg.select_option("#wz-regras", "dnd")
        pg.evaluate("() => { onWizardTypeChange(); wizardValidate(); }")
        pg.check("#wz-ai-toggle")
        pg.fill("#wz-ai-prompt", "Desaparecimentos em Cliviate")
        yield pg, erros, estado
        nav.close()


def _gerar(pg):
    pg.click("#wz-ai-btn")
    pg.wait_for_function("() => document.getElementById('wz-ai-btn').textContent === 'Gerar com IA'"
                         " && document.getElementById('wz-ai-status').textContent.length > 0",
                         timeout=15000)


def _valores(pg, cartao):
    return pg.evaluate(f"""() => [...document.querySelectorAll('{cartao}')].map(c =>
        [...c.querySelectorAll('input,textarea')].map(i => i.value))""")


def test_gerar_preenche_o_passo_1_inteiro(wizard):
    pg, erros, _ = wizard
    _gerar(pg)

    assert pg.inner_text("#wz-ai-status") == "✓ Lore gerado com 4 personagens! Revise os campos."
    assert pg.input_value("#wz-summary") == LORE["story_summary"]
    assert pg.input_value("#wz-scene") == LORE["current_scene"]
    assert pg.input_value("#wz-location") == "Praça de Cliviate"

    # nome, fica dentro de, detalhes, notas, descrição
    assert _valores(pg, "#wz-locations-list .wz-loc-card") == [
        ["Cliviate", "", "Portão norte", "Prefeito esconde algo", "Cidade murada."],
        ["Praça de Cliviate", "Cliviate", "Feira às quintas", "", "Poço antigo."],
        ["Floresta das Brumas", "", "Trilhas somem", "Covil dos lobos", "Neblina constante."],
    ]
    # resumo, local, envolvidos, consequência
    assert _valores(pg, "#wz-events-list .wz-evt-card") == [
        ["Três lenhadores sumiram na floresta.", "Floresta das Brumas", "Brom",
         "A cidade fechou o portão à noite."],
        ["Uivos perto da muralha.", "Cliviate", "", "Guardas dobraram a vigília."],
    ]
    assert not erros, erros[:3]


def test_gerar_preenche_os_personagens(wizard):
    pg, _, _ = wizard
    _gerar(pg)
    pg.evaluate("() => wizardGoTo(2)")
    pg.wait_for_selector("#wz-chars-list .cwc", timeout=5000)

    chars = pg.evaluate("""() => wzChars.map(c => [c.name, c.role, c.isParty, c.description,
        c.traits, c.notes, c.local, c.classe, c.raca])""")
    assert chars == [
        ["Alden", "Tanque", True, "Guerreiro de cicatriz.", "Protetor", "Busca o irmão", "", "guerreiro", "humano"],
        ["Lyra", "Batedora", True, "Patrulheira silenciosa.", "Observadora", "Cresceu na floresta", "", "patrulheiro", "elfo"],
        ["Brom", "Contratante", False, "Ferreiro corpulento.", "Rabugento", "O filho sumiu", "Praça de Cliviate", "npc", "commoner"],
        ["Lobo das Brumas", "Ameaça", False, "Lobo enorme.", "Faminto", "Guia a matilha", "Floresta das Brumas", "npc", "dire-wolf"],
    ]
    nomes = pg.locator("#wz-chars-list .cwc-nome").all_inner_texts()
    assert [n.strip() for n in nomes] == ["Alden", "Lyra", "Brom", "Lobo das Brumas"]
    assert pg.input_value("#wz-chars-list .cwc >> nth=2 >> .wz-onde-esta") == "Praça de Cliviate"


def test_o_que_foi_gerado_segue_para_a_criacao(wizard):
    pg, _, estado = wizard
    _gerar(pg)
    pg.evaluate("() => { wizardGoTo(2); createCampaignFromWizard(); }")
    pg.wait_for_function("() => document.getElementById('wz-err').textContent.length > 0", timeout=10000)

    camp = estado["criacao"]["campaign"]
    assert camp["story_summary"] == LORE["story_summary"]
    assert camp["current_location"] == "Praça de Cliviate"
    assert camp["locations"]["cliviate"]["notes"] == "Prefeito esconde algo"
    assert camp["locations"]["praça de cliviate"]["dentro_de"] == "Cliviate"
    eventos = {e["summary"]: e["characters_involved"] for e in camp["events"]}
    assert eventos["Três lenhadores sumiram na floresta."] == "Brom", \
        "o grupo inteiro foi gravado no lugar de quem a IA disse que estava lá"
    assert eventos["Uivos perto da muralha."] == "Alden, Lyra"      # vazio vira o grupo
    assert camp["characters"]["brom"]["local"] == "Praça de Cliviate"
    assert {p["name"] for p in camp["party"]} == {"Alden", "Lyra"}


def test_erro_da_ia_aparece_e_nao_apaga_o_que_ja_estava(wizard):
    pg, _, estado = wizard
    pg.fill("#wz-summary", "Meu resumo escrito à mão")
    estado["status"] = 502
    estado["lore"] = {"error": "A IA devolveu uma resposta incompleta (cortada antes do fim). Tente gerar de novo."}

    _gerar(pg)

    assert "incompleta" in pg.inner_text("#wz-ai-status")
    assert pg.input_value("#wz-summary") == "Meu resumo escrito à mão"


# --- O gênero: protagonista, próximos, campos e mecânicas ---------------------
# Antes o wizard não gravava protagonista, só "jogador" entrava no grupo (no
# romance ninguém era próximo), os campos do gênero ficavam vazios e nada das
# mecânicas do gênero (relação, segredos, laço, facções) chegava à campanha.

LORE_ROMANCE = {
    "story_summary": "Clara volta à cidade natal.", "current_scene": "O café abre.",
    "current_location": "Café Aurora",
    "locations": [{"name": "Café Aurora", "description": "Pequeno.", "details": "", "notes": "", "dentro_de": ""}],
    "events": [],
    "characters": [
        {"name": "Clara", "description": "Fotógrafa.", "traits": "", "notes": "Voltou sem avisar",
         "role": "", "tipo": "jogador", "protagonista": True, "grupo": True,
         "extras": {"papel": "Protagonista", "estado_emocional": "esperancoso", "segredo": "Vai embora em março"},
         "local": ""},
        {"name": "Lucas", "description": "O vizinho.", "traits": "", "notes": "", "role": "",
         "tipo": "aliado", "protagonista": False, "grupo": True,
         "extras": {"papel": "interesse romantico"}, "afeto": 45, "confianca": "-20", "estagio": "Flerte",
         "local": "Café Aurora"},
        {"name": "Helena", "description": "A ex de Lucas.", "traits": "", "notes": "", "role": "",
         "tipo": "inimigo", "protagonista": False, "grupo": False,
         "extras": {"papel": "Rival Amoroso", "estado_emocional": "Furiosa"}, "afeto": -300,
         "local": "Café Aurora"},
    ],
    "segredos": [{"titulo": "A bolsa em Lisboa", "dono": "", "escondido_de": ["Lucas"]},
                 {"titulo": "O irmão na prisão", "dono": "Lucas"}],
    "tensoes": [{"a": "Helena", "b": "Lucas", "tipo": "ciume", "intensidade": 60, "percebida": False}],
    "faccoes": [{"nome": "A Guilda", "reputacao": 10}],   # de outro gênero: fica de fora
}

LORE_FANTASIA = json.loads(json.dumps(LORE))
LORE_FANTASIA["characters"][0]["protagonista"] = True
LORE_FANTASIA["characters"][0]["lealdade"] = 90                 # é você: não tem laço
LORE_FANTASIA["characters"][1].update({"lealdade": 70, "objetivo": "Achar a mãe",
                                       "arco": {"titulo": "Voltar à floresta"}})
LORE_FANTASIA["characters"][2]["lealdade"] = 50                 # não é do grupo: não tem laço
LORE_FANTASIA.update({"renome": 5, "faccoes": [{"nome": "Guarda de Cliviate", "reputacao": 20}],
                      "lendas": [{"titulo": "O Lobo Branco", "verdade": "É o prefeito"}],
                      "segredos": [{"titulo": "de outro gênero"}]})


def _genero(pg, genero, regras="livre"):
    pg.select_option("#wz-type", genero)
    if regras == "dnd":
        pg.select_option("#wz-regras", "dnd")
    pg.evaluate("() => onWizardTypeChange()")


def _criar(pg, estado):
    pg.evaluate("() => { wizardGoTo(2); createCampaignFromWizard(); }")
    pg.wait_for_function("() => document.getElementById('wz-err').textContent.length > 0", timeout=10000)
    return estado["criacao"]["campaign"]


def test_romance_gerado_preenche_protagonista_proximos_e_campos(wizard):
    pg, erros, estado = wizard
    _genero(pg, "romance")
    estado["lore"] = {"ok": True, "lore": LORE_ROMANCE}
    _gerar(pg)
    assert pg.inner_text("#wz-ai-status").endswith("Também preparou 2 segredos e 1 tensão.")

    pg.evaluate("() => wizardGoTo(2)")
    pg.wait_for_selector("#wz-chars-list .cwc", timeout=5000)
    chars = pg.evaluate("() => wzChars.map(c => [c.name, c.protagonista, c.isParty, c.local, c.extras, c.mec])")
    assert chars == [
        ["Clara", True, True, "", {"papel": "Protagonista", "estado_emocional": "Esperançoso",
                                   "segredo": "Vai embora em março"}, {}],
        ["Lucas", False, True, "", {"papel": "Interesse Romântico"},
         {"afeto": 45, "confianca": -20, "estagio": "Flerte"}],
        ["Helena", False, False, "Café Aurora", {"papel": "Rival Amoroso"}, {"afeto": -100}],
    ]
    cartoes = pg.locator("#wz-chars-list .cwc")
    assert cartoes.nth(0).locator(".cwc-voce").count() == 1
    assert cartoes.nth(0).locator(".wz-protagonista").is_checked()
    assert cartoes.nth(0).locator(".wz-campos-mec").count() == 0       # você não tem relação com você
    assert cartoes.nth(1).locator(".wz-campos-mec [data-campo='afeto'] input").input_value() == "45"
    assert cartoes.nth(1).locator(".wz-campos-mec [data-campo='estagio'] select").input_value() == "Flerte"
    assert cartoes.nth(2).locator(".wz-campos-extras [data-campo='estado_emocional'] select").input_value() == ""
    assert not erros, erros[:3]


def test_romance_gerado_chega_inteiro_na_campanha(wizard):
    pg, _, estado = wizard
    _genero(pg, "romance")
    estado["lore"] = {"ok": True, "lore": LORE_ROMANCE}
    _gerar(pg)
    camp = _criar(pg, estado)

    assert camp["protagonist"] == "Clara"
    assert {p["name"] for p in camp["party"]} == {"Clara", "Lucas"}
    lucas, helena, clara = (camp["characters"][k] for k in ("lucas", "helena", "clara"))
    assert (lucas["atitude"], lucas["confianca"], lucas["estagio"], lucas["role"]) == \
        (45, -20, "flerte", "Interesse Romântico")
    assert helena["atitude"] == -100 and "estagio" not in helena
    assert "atitude" not in clara and "Segredo: Vai embora em março" in clara["notes"]
    assert [s["titulo"] for s in camp["segredos"]] == ["A bolsa em Lisboa", "O irmão na prisão"]
    assert camp["tensoes"][0]["percebida"] is False
    assert "faccoes" not in camp


def test_trocar_de_genero_depois_de_gerar_nao_leva_o_romance(wizard):
    pg, _, estado = wizard
    _genero(pg, "romance")
    estado["lore"] = {"ok": True, "lore": LORE_ROMANCE}
    _gerar(pg)
    _genero(pg, "horror")
    camp = _criar(pg, estado)
    assert "segredos" not in camp and "tensoes" not in camp
    assert "atitude" not in camp["characters"]["lucas"]
    assert camp["protagonist"] == "Clara"


def test_fantasia_gerada_leva_o_laco_dos_companheiros_e_o_mundo(wizard):
    pg, erros, estado = wizard          # fantasia com D&D, como o fixture deixa
    estado["lore"] = {"ok": True, "lore": LORE_FANTASIA}
    _gerar(pg)
    assert pg.inner_text("#wz-ai-status").endswith("Também preparou 1 facção e 1 lenda.")
    pg.evaluate("() => wizardGoTo(2)")
    pg.wait_for_selector("#wz-chars-list .cwc", timeout=5000)
    mec = [pg.locator("#wz-chars-list .cwc").nth(i).locator(".wz-campos-mec").count() for i in range(4)]
    assert mec == [0, 1, 0, 0], "só a companheira tem o laço (nem você, nem quem não é do grupo)"

    camp = _criar(pg, estado)
    assert camp["protagonist"] == "Alden"
    lyra = camp["characters"]["lyra"]
    assert (lyra["lealdade"], lyra["objetivo"], lyra["arco"]) == \
        (70, "Achar a mãe", {"titulo": "Voltar à floresta", "estado": "em curso", "passos": []})
    assert "lealdade" not in camp["characters"]["alden"]
    assert "lealdade" not in camp["characters"]["brom"]
    assert (camp["renome"], camp["faccoes"][0]["nome"], camp["lendas"][0]["verdade"]) == \
        (5, "Guarda de Cliviate", "É o prefeito")
    assert "segredos" not in camp
    assert not erros, erros[:3]


def test_sem_protagonista_da_ia_o_primeiro_jogador_e_voce(wizard):
    pg, _, estado = wizard
    _gerar(pg)                          # LORE não marca protagonista
    assert pg.evaluate("() => wzChars.map(c => c.protagonista)") == [True, False, False, False]
    assert _criar(pg, estado)["protagonist"] == "Alden"


def test_protagonista_a_mao_e_um_so(wizard):
    pg, erros, estado = wizard
    _genero(pg, "romance")
    pg.evaluate("() => wizardGoTo(2)")
    pg.evaluate("() => { addWzChar(); addWzChar(); wzChars[0].name = 'Ana'; wzChars[1].name = 'Beto'; wzRenderChars(); }")
    assert pg.evaluate("() => wzChars.map(c => c.protagonista)") == [True, False]
    pg.locator("#wz-chars-list .cwc").nth(1).locator(".wz-protagonista").check()
    assert pg.evaluate("() => wzChars.map(c => c.protagonista)") == [False, True]
    # A relação é de quem não é você: o cartão da Ana ganhou os campos.
    assert pg.locator("#wz-chars-list .cwc").nth(0).locator(".wz-campos-mec").count() == 1
    assert _criar(pg, estado)["protagonist"] == "Beto"
    pg.evaluate("() => removeWzChar(1)")
    assert pg.evaluate("() => wzChars.map(c => c.protagonista)") == [True]
    assert not erros, erros[:3]
