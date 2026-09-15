"""
test_mapa.py

O mapa do mundo (rpg/mapa.py): a árvore de lugares, onde o grupo está, o que
está a um passo e quem está em cada lugar.
"""
import pytest

from rpg import mapa, memory, tools as tl, tools_dnd as td

from conftest import criar_ficha


@pytest.fixture
def mundo(campanha, povoar):
    povoar(criar_ficha("Alden", grupo=True))
    c = memory.campaign
    tl.save_location("Cliviate", "Cidade de muralhas baixas.")
    tl.save_location("Praça de Cliviate", "Uma praça.", dentro_de="Cliviate")
    tl.save_location("Taverna do Caldeirão", "Mesas compridas.", dentro_de="Cliviate")
    tl.save_location("Porão da Taverna", "Escuro.", dentro_de="Taverna do Caldeirão")
    tl.save_location("Floresta das Brumas", "Neblina.")
    td.open_shop("Forja de Cliviate", "Espada Longa", location="Cliviate")
    c["current_location"] = "Praça de Cliviate"
    tl.save_character("Brom", "Ferreiro.", local="Forja de Cliviate")
    tl.save_character("Tiel", "Guarda.", local="Praça de Cliviate")
    tl.save_character("Eremita", "Vive na neblina.", local="Floresta das Brumas")
    tl.save_character("Velho", "Morto há dias.", status="morto", local="Porão da Taverna")
    tl.save_character("Andarilho", "Ninguém sabe onde.")
    tl.save_character("Pescador", "Mora no porto.", local="Porto de Vhar")
    return c


def _no(arvore, nome):
    for n in arvore:
        if n["nome"] == nome:
            return n
        achado = _no(n["filhos"], nome)
        if achado:
            return achado
    return None


def test_arvore_com_lojas_dentro_da_cidade(mundo):
    snap = mapa.mapa_snapshot()
    cliviate = _no(snap["arvore"], "Cliviate")
    assert [f["nome"] for f in cliviate["filhos"]] == [
        "Forja de Cliviate", "Praça de Cliviate", "Taverna do Caldeirão"]
    assert _no(snap["arvore"], "Forja de Cliviate")["tipo"] == "loja"
    assert [f["nome"] for f in _no(snap["arvore"], "Taverna do Caldeirão")["filhos"]] == ["Porão da Taverna"]


def test_onde_o_grupo_esta_e_o_caminho_aberto(mundo):
    snap = mapa.mapa_snapshot()
    assert snap["local_atual"] == "Praça de Cliviate"
    assert snap["caminho_atual"] == ["Cliviate", "Praça de Cliviate"]
    assert snap["grupo"] == ["Alden"]
    assert snap["arvore"][0]["nome"] == "Cliviate", "a raiz de onde o grupo está vem primeiro"
    assert _no(snap["arvore"], "Praça de Cliviate")["grupo_aqui"] is True
    assert _no(snap["arvore"], "Cliviate")["no_caminho_do_grupo"] is True
    assert _no(snap["arvore"], "Floresta das Brumas")["no_caminho_do_grupo"] is False


def test_ao_alcance(mundo):
    snap = mapa.mapa_snapshot()
    assert [(x["nome"], x["alcance"]) for x in snap["ao_alcance"]] == [
        ("Forja de Cliviate", "vizinho"), ("Taverna do Caldeirão", "vizinho"), ("Cliviate", "acima")]
    assert _no(snap["arvore"], "Porão da Taverna")["alcance"] == ""


def test_quem_esta_em_cada_lugar_e_a_soma_por_ramo(mundo):
    snap = mapa.mapa_snapshot()
    assert [p["nome"] for p in _no(snap["arvore"], "Forja de Cliviate")["pessoas"]] == ["Brom"]
    porao = _no(snap["arvore"], "Porão da Taverna")["pessoas"]
    assert porao == [{"nome": "Velho", "status": "morto", "fora": True}]
    assert _no(snap["arvore"], "Cliviate")["pessoas_total"] == 3        # Brom, Tiel, Velho
    assert "Alden" not in [p["nome"] for p in _no(snap["arvore"], "Praça de Cliviate")["pessoas"]]


def test_sem_paradeiro_e_lugar_sem_registro(mundo):
    snap = mapa.mapa_snapshot()
    assert [p["nome"] for p in snap["sem_paradeiro"]] == ["Andarilho"]
    porto = _no(snap["arvore"], "Porto de Vhar")
    assert porto["tipo"] == "sem_registro" and [p["nome"] for p in porto["pessoas"]] == ["Pescador"]


def test_local_atual_sem_registro_aparece(campanha, povoar):
    povoar(criar_ficha("Alden", grupo=True))
    memory.campaign["current_location"] = "Estrada do Norte"
    snap = mapa.mapa_snapshot()
    assert snap["arvore"][0]["nome"] == "Estrada do Norte"
    assert snap["arvore"][0]["grupo_aqui"] is True and snap["arvore"][0]["tipo"] == "sem_registro"


def test_ciclo_nao_some_nem_trava(mundo):
    mundo["locations"]["cliviate"]["dentro_de"] = "Praça de Cliviate"   # editado à mão
    snap = mapa.mapa_snapshot()
    assert _no(snap["arvore"], "Cliviate") is not None
    assert _no(snap["arvore"], "Praça de Cliviate") is not None


def test_campanha_vazia(campanha):
    snap = mapa.mapa_snapshot()
    assert snap["arvore"] == [] and snap["local_atual"] == "" and snap["total_lugares"] == 0


def test_rota(mundo):
    import server
    assert "/api/map/state" in {r.rule for r in server.app.url_map.iter_rules()}
    with server.app.test_request_context("/api/map/state"):
        corpo = server.map_state_route.__wrapped__().get_json()
    assert corpo["local_atual"] == "Praça de Cliviate"
