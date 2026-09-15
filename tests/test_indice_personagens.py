"""
test_indice_personagens.py

O índice de personagens (rpg/personagens.py, indice): todos os personagens
da campanha, com a categoria de cada um, se está aqui com o grupo e a
contagem por filtro. É a lista que substitui a Enciclopédia da barra lateral.
"""
import pytest

from rpg import memory, personagens, tools as tl

from conftest import criar_ficha


@pytest.fixture
def elenco(campanha, povoar):
    povoar(criar_ficha("Thorn", grupo=True), criar_ficha("Lyra", grupo=True))
    c = memory.campaign
    tl.save_location("Cliviate", "Cidade.")
    tl.save_location("Praça de Cliviate", "Praça.", dentro_de="Cliviate")
    tl.save_location("Floresta das Brumas", "Neblina.")
    c["current_location"] = "Praça de Cliviate"
    tl.save_character("Guarda Tiel", "Guarda da praça, entediado e atento a forasteiros.",
                      local="Praça de Cliviate")
    tl.save_character("Brom", "Ferreiro.", local="Cliviate")
    tl.adjust_attitude("Brom", 40, "o martelo devolvido")
    tl.save_character("Eremita", "Vive na neblina.", local="Floresta das Brumas")
    tl.save_character("Velho Osric", "Contrabandista.", status="morto", local="Praça de Cliviate")
    povoar(criar_ficha("Goblin Batedor 1"))
    return c


def _p(snap, nome):
    return next(x for x in snap["personagens"] if x["nome"] == nome)


def test_ordem_grupo_aqui_e_depois_por_categoria(elenco):
    nomes = [p["nome"] for p in personagens.indice()["personagens"]]
    assert nomes == ["Lyra", "Thorn", "Guarda Tiel", "Brom", "Eremita", "Goblin Batedor 1", "Velho Osric"]


def test_categorias(elenco):
    snap = personagens.indice()
    assert _p(snap, "Thorn")["categoria"] == "grupo" and _p(snap, "Thorn")["do_grupo"]
    assert _p(snap, "Brom")["categoria"] == "conhecido"
    assert _p(snap, "Goblin Batedor 1")["categoria"] == "inimigo"
    assert _p(snap, "Velho Osric")["categoria"] == "morto"


def test_aqui_e_so_quem_esta_no_mesmo_lugar_do_grupo(elenco):
    snap = personagens.indice()
    assert _p(snap, "Guarda Tiel")["aqui"] is True
    assert _p(snap, "Thorn")["aqui"] is True, "o grupo está onde o grupo está"
    assert _p(snap, "Brom")["aqui"] is False, "Cliviate é onde a praça fica, não a praça"
    assert _p(snap, "Velho Osric")["aqui"] is False, "morto não conta como presente"
    assert _p(snap, "Thorn")["local"] == "Praça de Cliviate"


def test_contagem_por_filtro(elenco):
    assert personagens.indice()["contagem"] == {
        "todos": 7, "aqui": 3, "grupo": 2, "conhecidos": 3, "inimigos": 1, "mortos": 1}


def test_atitude_so_para_quem_o_mestre_mexeu(elenco):
    snap = personagens.indice()
    assert _p(snap, "Brom")["atitude"] != ""
    assert _p(snap, "Eremita")["atitude"] == ""
    assert _p(snap, "Thorn")["atitude"] == ""


def test_descricao_curta_e_ficha(elenco):
    memory.campaign["characters"]["eremita"]["description"] = "palavra " * 40
    snap = personagens.indice()
    assert len(_p(snap, "Eremita")["descricao"]) <= 141 and _p(snap, "Eremita")["descricao"].endswith("…")
    assert _p(snap, "Thorn")["tem_ficha"] is True and _p(snap, "Brom")["tem_ficha"] is False


def test_membro_do_grupo_morto_fica_nos_mortos(elenco):
    memory.campaign["characters"]["lyra"]["status"] = "morto"
    assert _p(personagens.indice(), "Lyra")["categoria"] == "morto"


def test_campanha_sem_personagens(campanha):
    snap = personagens.indice()
    assert snap["personagens"] == [] and snap["contagem"]["todos"] == 0


def test_rota(elenco):
    import server
    assert "/api/characters/index" in {r.rule for r in server.app.url_map.iter_rules()}
    with server.app.test_request_context("/api/characters/index"):
        corpo = server.characters_index_route.__wrapped__().get_json()
    assert corpo["contagem"]["todos"] == 7
