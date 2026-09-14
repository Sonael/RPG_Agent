"""
test_loja_ao_chegar.py

O grupo seguiu da Clareira das Brumas Eternas para Cliviate e entrou na forja.
O mestre salvou o local (save_location) e abriu a loja com
open_shop("Forja de Cliviate", ..., location="Cliviate") — mas não chamou
update_world_state. O local atual do grupo continuou "Clareira das Brumas
Eternas"; a tela de loja só mostra lojas do local atual; nem abriu sozinha nem
mostrou a pílula.

A instrução do mestre já dizia que `location` é ONDE O GRUPO ESTÁ. Agora o
motor honra isso.

Junto, o cartão de Cliviate na Enciclopédia: a descrição salva era "Salva ou
atualiza um local na memória da campanha." — o texto de ajuda da própria
ferramenta, copiado pelo modelo para o campo.
"""
import pytest

from rpg import memory, tools as tl, tools_dnd as td

from conftest import criar_ficha


@pytest.fixture
def na_clareira(campanha, povoar):
    povoar(criar_ficha("Alden", grupo=True), criar_ficha("Lyra", grupo=True))
    memory.campaign["current_location"] = "Clareira das Brumas Eternas"
    return memory.campaign


def test_abrir_a_loja_em_outra_cidade_leva_o_grupo_ate_la(na_clareira):
    saida = td.open_shop("Forja de Cliviate", "Espada Longa; Escudo", location="Cliviate")

    assert memory.campaign["current_location"] == "Cliviate"
    snap = td.shop_snapshot()
    assert snap["loja_aqui"] is True, "a tela não abriria nem mostraria a pílula"
    assert [l["nome"] for l in snap["lojas_aqui"]] == ["Forja de Cliviate"]
    assert "Nota:" in saida and "Clareira das Brumas Eternas" in saida


def test_usa_o_nome_do_local_salvo(na_clareira):
    tl.save_location("Cliviate", "Cidade de muralhas baixas de pedra na borda da floresta.")
    td.open_shop("Forja de Cliviate", "Espada Longa", location="cliviate")
    assert memory.campaign["current_location"] == "Cliviate"


def test_mesmo_local_escrito_diferente_nao_mexe(na_clareira):
    saida = td.open_shop("Tenda da Clareira", "Adaga", location="clareira das brumas eternas")
    assert memory.campaign["current_location"] == "Clareira das Brumas Eternas"
    assert "Nota:" not in saida


def test_sem_location_a_loja_fica_onde_o_grupo_esta(na_clareira):
    saida = td.open_shop("Tenda da Clareira", "Adaga")
    assert memory.campaign["current_location"] == "Clareira das Brumas Eternas"
    assert memory.campaign["lojas"]["tenda da clareira"]["local"] == "Clareira das Brumas Eternas"
    assert "Nota:" not in saida


def test_reabastecer_sem_location_nao_move_o_grupo(na_clareira):
    td.open_shop("Forja de Cliviate", "Espada Longa", location="Cliviate")
    memory.campaign["current_location"] = "Estrada Real"

    td.open_shop("Forja de Cliviate", "Cota de Malha")

    assert memory.campaign["current_location"] == "Estrada Real"
    assert memory.campaign["lojas"]["forja de cliviate"]["local"] == "Cliviate"


# ---- save_location com o texto da ferramenta -------------------------------

def test_descricao_copiada_da_ajuda_usa_os_detalhes(campanha):
    saida = tl.save_location("Cliviate", "Salva ou atualiza um local na memória da campanha.",
                             details="Cidade mencionada pelo jogador como o próximo destino.")
    loc = memory.campaign["locations"]["cliviate"]
    assert not saida.startswith("Erro:")
    assert loc["description"] == "Cidade mencionada pelo jogador como o próximo destino."
    assert loc["details"] == ""


def test_descricao_copiada_sem_detalhes_e_recusada(campanha):
    saida = tl.save_location("Porto do Sul", "Descrição sensorial e atmosférica do ambiente.")
    assert saida.startswith("Erro:")
    assert "porto do sul" not in memory.campaign["locations"]


def test_descricao_de_verdade_passa(campanha):
    tl.save_location("Cliviate", "Muralhas baixas de pedra e cheiro de fumaça de chaminé.")
    assert memory.campaign["locations"]["cliviate"]["description"].startswith("Muralhas")
