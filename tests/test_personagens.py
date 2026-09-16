"""
test_personagens.py

A ficha do personagem que a tela mostra (rpg/personagens.py) e o "o que o
grupo sabe" que o mestre registra com add_character_knowledge.

Antes: a atitude, o histórico do porquê, as missões que o NPC deu e os
eventos em que ele aparece existiam na campanha e não apareciam em lugar
nenhum. O cartão da Enciclopédia mostrava as `notes`, que o editor sugeria
para "objetivos secretos": spoiler na cara do jogador.
"""
import pytest

from rpg import memory, personagens, tools as tl, tools_dnd as td

from conftest import criar_ficha


@pytest.fixture
def cliviate(campanha, povoar):
    povoar(criar_ficha("Alden", grupo=True), criar_ficha("Lyra", grupo=True))
    c = memory.campaign
    c["events"] = []
    c["current_location"] = "Praça de Cliviate"
    tl.save_location("Cliviate", "Cidade de muralhas baixas na borda da floresta.")
    tl.save_location("Praça de Cliviate", "Uma praça com um poço antigo.", dentro_de="Cliviate")
    tl.save_location("Floresta das Brumas", "Neblina que não se desfaz.")
    td.open_shop("Forja de Cliviate", "Espada Longa", location="Cliviate")
    c["current_location"] = "Praça de Cliviate"
    tl.save_character("Brom", "Ferreiro corpulento.", traits="Desconfiado",
                      notes="SEGREDO: forja para os bandidos", local="Forja de Cliviate")
    tl.save_character("Eremita", "Vive na neblina.", local="Floresta das Brumas")
    tl.save_character("Velho Morto", "Descansa em paz.", status="morto", local="Praça de Cliviate")
    return c


# ---------------------------------------------------------------------------
# 1. Quem é e onde está
# ---------------------------------------------------------------------------

def test_ficha_basica(cliviate):
    f = personagens.ficha("brom")
    assert f["existe"] and f["nome"] == "Brom"
    assert f["descricao"] == "Ferreiro corpulento."
    assert f["tracos"] == "Desconfiado"
    assert f["do_grupo"] is False
    assert f["local"] == {"nome": "Forja de Cliviate", "alcance": "vizinho"}
    assert f["loja"]["nome"] == "Forja de Cliviate" and f["loja"]["dono"] is False


def test_notas_do_mestre_nao_entram_na_ficha(cliviate):
    f = personagens.ficha("Brom")
    assert "SEGREDO" not in repr(f), "as notas do mestre vazavam para o jogador"


def test_personagem_desconhecido(cliviate):
    assert personagens.ficha("Ninguém") == {"existe": False, "nome": "Ninguém"}


def test_acha_pelo_nome_sem_acento_e_caixa(cliviate):
    tl.save_character("Érica", "Tecelã.")
    assert personagens.ficha("ERICA")["nome"] == "Érica"


def test_pode_falar_so_quem_esta_perto_e_vivo(cliviate):
    assert personagens.ficha("Brom")["pode_falar"] is True
    longe = personagens.ficha("Eremita")
    assert longe["pode_falar"] is False and longe["local"]["alcance"] == ""
    morto = personagens.ficha("Velho Morto")
    assert morto["local"]["alcance"] == "aqui" and morto["pode_falar"] is False


def test_membro_do_grupo_esta_no_local_atual_e_sem_atitude(cliviate):
    f = personagens.ficha("Alden")
    assert f["do_grupo"] is True
    assert f["local"]["nome"] == "Praça de Cliviate"
    assert f["atitude"] is None
    assert f["pode_falar"] is False


# ---------------------------------------------------------------------------
# 2. Relação com o grupo
# ---------------------------------------------------------------------------

def test_atitude_com_faixa_e_historico_mais_recente_primeiro(cliviate):
    tl.adjust_attitude("Brom", -10, "Lyra pechinchou demais")
    tl.adjust_attitude("Brom", 40, "Devolveram o martelo do avô")
    a = personagens.ficha("Brom")["atitude"]
    assert a["valor"] == 30
    rotulo, conduta = tl._faixa_atitude(30)
    assert (a["rotulo"], a["conduta"]) == (rotulo, conduta)
    assert [h["delta"] for h in a["historico"]] == [40, -10]
    assert a["historico"][0]["motivo"] == "Devolveram o martelo do avô"


# ---------------------------------------------------------------------------
# 3. Ligações
# ---------------------------------------------------------------------------

def test_missoes_que_ele_deu(cliviate):
    tl.add_quest("O filho do ferreiro", "Achar o filho.", giver="brom")
    tl.add_quest("Outra coisa", "Nada a ver.", giver="Mira")
    missoes = personagens.ficha("Brom")["missoes"]
    assert missoes == [{"titulo": "O filho do ferreiro", "status": "ativa"}]


def test_eventos_em_que_aparece_sem_confundir_nomes_parecidos(cliviate):
    tl.save_event("Devolveram o martelo.", "Brom, Lyra", "Forja de Cliviate")
    tl.save_event("Guardas na forja.", "Guarda Tiel; brom")
    tl.save_event("Outro ferreiro chegou.", "Bromwell")
    eventos = personagens.ficha("Brom")["eventos"]
    assert [e["resumo"] for e in eventos] == ["Devolveram o martelo.", "Guardas na forja."]
    assert eventos[0]["local"] == "Forja de Cliviate"


# ---------------------------------------------------------------------------
# 4. O que o grupo sabe
# ---------------------------------------------------------------------------

def test_add_character_knowledge_registra_e_nao_repete(cliviate):
    assert tl.add_character_knowledge("Brom", "O filho dele sumiu").startswith("Registrado")
    assert tl.add_character_knowledge("brom", "o  filho dele SUMIU").startswith("Nota:")
    assert tl.add_character_knowledge("Brom", "  ").startswith("Aviso:")
    assert tl.add_character_knowledge("Ninguém", "x").startswith("Erro:")
    assert personagens.ficha("Brom")["conhecido"] == ["O filho dele sumiu"]


def test_add_character_knowledge_guarda_os_mais_recentes(cliviate):
    for i in range(35):
        tl.add_character_knowledge("Brom", f"Fato {i}")
    conhecido = cliviate["characters"]["brom"]["conhecido"]
    assert len(conhecido) == personagens.MAX_CONHECIDO
    assert conhecido[-1] == "Fato 34"


def test_limpar_conhecido(cliviate):
    assert personagens.limpar_conhecido("a\n\n b \nA\nc") == ["a", "b", "c"]
    assert personagens.limpar_conhecido(["x", "", None, {"y": 1}, "x"]) == ["x"]
    assert personagens.limpar_conhecido(None) == []


def test_contexto_da_cena_lembra_o_que_o_grupo_sabe(cliviate):
    tl.add_character_knowledge("Brom", "O filho dele sumiu")
    tl.set_character_location("Brom", "Praça de Cliviate")
    assert "Grupo sabe: O filho dele sumiu" in tl.get_scene_context()


def test_ferramenta_registrada(cliviate):
    assert tl.add_character_knowledge in tl.ALL_TOOLS


# ---------------------------------------------------------------------------
# 5. Rotas e editores
# ---------------------------------------------------------------------------

# As rotas passam por require_auth (Supabase); aqui chamamos a função por
# baixo do decorador, no mesmo contexto da campanha do teste.

def test_rota_da_ficha(cliviate):
    import server
    assert "/api/characters/sheet" in {r.rule for r in server.app.url_map.iter_rules()}
    with server.app.test_request_context("/api/characters/sheet?nome=Brom"):
        corpo = server.character_sheet_route.__wrapped__().get_json()
    assert corpo["local"]["nome"] == "Forja de Cliviate"


def test_editor_do_jogo_grava_o_que_o_grupo_sabe(cliviate, monkeypatch):
    import server
    monkeypatch.setattr(memory, "save_campaign", lambda *a, **k: None)
    corpo = {"name": "Brom", "conhecido": ["Tem um filho", " ", "tem um filho", "Veio de Oakhaven"]}
    with server.app.test_request_context("/api/memory/characters/brom", method="PUT", json=corpo):
        r = server.update_character.__wrapped__("brom")
    assert r.get_json()["ok"] is True
    assert cliviate["characters"]["brom"]["conhecido"] == ["Tem um filho", "Veio de Oakhaven"]
    assert cliviate["characters"]["brom"]["notes"] == "SEGREDO: forja para os bandidos"


def test_editor_da_campanha_limpa_e_preserva_o_que_o_grupo_sabe(cliviate):
    from rpg import locais
    antigos = {"brom": {**cliviate["characters"]["brom"], "conhecido": ["Tem um filho"]},
               "eremita": {"name": "Eremita", "conhecido": ["Odeia visitas"]}}
    novos = {"brom": {"name": "Brom", "description": "x", "conhecido": ["a", "A", ""]},
             "eremita": {"name": "Eremita", "description": "y"}}
    _, erro = locais.normalizar_campanha_editada({}, cliviate["locations"], novos, antigos,
                                                 cliviate["lojas"])
    assert not erro
    assert novos["brom"]["conhecido"] == ["a"]
    assert novos["eremita"]["conhecido"] == ["Odeia visitas"]
