"""
test_historia_do_local.py

A ficha do local passa a ter passado: o que aconteceu ali e as missões que
passam pelo lugar.

Ela dizia quem está lá AGORA, o que fica dentro e o caminho até lá. Tudo o
que o lugar já viu — a emboscada na estrada, o acordo na taverna — estava
gravado nos eventos e não aparecia em lugar nenhum da tela; e a missão que o
ferreiro daquela cidade encomendou só se via na ficha dele.

Missão não guarda local: a ligação é achada, e a ficha diz por quê —
encomendada por quem está no lugar, ou o lugar citado no que ela pede.
"""
import pytest

from rpg import locais, memory, tools as tl


@pytest.fixture
def cliviate(campanha):
    memory.campaign["locations"] = {
        "cliviate": {"name": "Cliviate", "description": "Cidade de pedra.", "dentro_de": ""},
        "forja de cliviate": {"name": "Forja de Cliviate", "description": "", "dentro_de": "Cliviate"},
        "estrada do norte": {"name": "Estrada do Norte", "description": "", "dentro_de": ""},
    }
    memory.campaign["characters"] = {
        "brom": {"name": "Brom", "sheet": None, "status": "vivo", "local": "Forja de Cliviate"},
        "ivo": {"name": "Pescador Ivo", "sheet": None, "status": "vivo", "local": "Estrada do Norte"},
    }
    memory.campaign["current_location"] = "Cliviate"
    memory.campaign["chapter"] = 2
    return campanha


def _resumos(nome):
    return [e["resumo"] for e in locais.ficha(nome)["eventos"]]


# ---------------------------------------------------------------------------
# O que aconteceu aqui
# ---------------------------------------------------------------------------

def test_evento_do_lugar_entra_na_ficha(cliviate):
    tl.save_event("O grupo chegou a Cliviate.", "Thorn", "Cliviate", "A guarda ficou de olho.")
    f = locais.ficha("Cliviate")
    assert f["eventos"][0]["resumo"] == "O grupo chegou a Cliviate."
    assert f["eventos"][0]["capitulo"] == 2
    assert f["eventos"][0]["consequencia"] == "A guarda ficou de olho."
    assert f["acontecimentos"] == 1


def test_a_cidade_conta_o_que_aconteceu_dentro_dela(cliviate):
    tl.save_event("Briga na forja.", "Brom", "Forja de Cliviate")
    assert _resumos("Cliviate") == ["Briga na forja."]
    # E a ficha da forja não herda o que aconteceu na cidade em volta.
    tl.save_event("Feira na praça.", "", "Cliviate")
    assert _resumos("Forja de Cliviate") == ["Briga na forja."]


def test_evento_de_outro_lugar_fica_de_fora(cliviate):
    tl.save_event("Emboscada na estrada.", "", "Estrada do Norte")
    assert _resumos("Cliviate") == []


def test_do_mais_recente_para_tras_e_no_maximo_cinco(cliviate):
    for i in range(1, 8):
        tl.save_event(f"Cena {i}.", "", "Cliviate")
    f = locais.ficha("Cliviate")
    assert [e["resumo"] for e in f["eventos"]] == [f"Cena {i}." for i in (7, 6, 5, 4, 3)]
    assert f["acontecimentos"] == 7


def test_lugar_sem_passado_nao_inventa(cliviate):
    f = locais.ficha("Estrada do Norte")
    assert f["eventos"] == [] and f["acontecimentos"] == 0


# ---------------------------------------------------------------------------
# Missões daqui
# ---------------------------------------------------------------------------

def test_missao_de_quem_esta_aqui(cliviate):
    tl.add_quest("O filho do ferreiro", "Achar o rapaz.", "Procurar na mata", giver="Brom")
    m = locais.ficha("Cliviate")["missoes"]
    assert m == [{"titulo": "O filho do ferreiro", "status": "ativa",
                  "quem_deu": "Brom", "motivo": "encomendada"}]


def test_missao_que_cita_o_lugar(cliviate):
    tl.add_quest("A carta selada", "Levar a carta até Cliviate.", "Entregar ao regente")
    m = locais.ficha("Cliviate")["missoes"]
    assert m[0]["motivo"] == "citada"


def test_missao_que_cita_o_lugar_num_objetivo(cliviate):
    tl.add_quest("A rota do sal", "Abrir caminho ao norte.", "Cruzar a Estrada do Norte")
    assert locais.ficha("Estrada do Norte")["missoes"][0]["motivo"] == "citada"
    assert locais.ficha("Cliviate")["missoes"] == []


def test_missao_sem_ligacao_nao_entra(cliviate):
    tl.add_quest("O silêncio de Vharn", "Descobrir o que houve na torre.", giver="Pescador Ivo")
    assert locais.ficha("Cliviate")["missoes"] == []


def test_missao_encerrada_continua_na_lista_com_o_status(cliviate):
    """O que já foi feito aqui faz parte da história do lugar."""
    tl.add_quest("O filho do ferreiro", "Achar o rapaz.", giver="Brom")
    tl.complete_quest("O filho do ferreiro", "concluida")
    m = locais.ficha("Cliviate")["missoes"]
    assert m[0]["status"] == "concluida"
