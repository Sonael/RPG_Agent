"""
test_inimigo_usa_itens.py

A vez do inimigo passa pela mochila dele.

O turno do NPC sabia atacar, usar poder de recarga, curar aliado (suporte),
recuar e fugir — mas nunca abria o próprio inventário. Um bandido com poção
de cura no cinto morria com ela na mão, enquanto o jogador ao lado bebia a
dele pela tela.

Regra: ferido pela metade ou menos, o inimigo bebe a poção como Ação Bônus,
pelo mesmo caminho do motor que a tela do jogador usa — e ainda ataca no
mesmo turno, porque beber é bônus e atacar é ação.
"""
import random

import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _item(nome, qtd=1):
    return {"nome": nome, "qtd": qtd, "descricao": ""}


@pytest.fixture
def campo(povoar):
    """Bandido ferido (8/40) com poção, contra um herói de pé."""
    bandido = criar_ficha("Bandido", vida=8, vida_max=40, destreza=12)
    bandido["inventario"] = [_item("Poção de Cura", 2)]
    povoar(criar_ficha("Alden", grupo=True, vida=30, vida_max=30),
           bandido)
    iniciar_combate(["Bandido", "Alden"])
    td._reset_turn_economy(memory.campaign["combat_state"])
    return memory.campaign


def _bandido():
    return memory.campaign["characters"]["bandido"]


def _pocoes():
    return sum(int(i.get("qtd", 0) or 0) for i in _bandido()["inventario"]
               if i["nome"] == "Poção de Cura")


def test_inimigo_ferido_bebe_e_ainda_ataca(campo):
    random.seed(7)
    saida = td.execute_npc_turn()

    s = _bandido()["sheet"]
    assert s["vida_atual"] > 8, saida
    assert _pocoes() == 1
    assert "Poção de Cura" in saida
    # Beber é Ação Bônus: o ataque do turno continua acontecendo.
    assert "[Bônus]" in saida
    assert "Bandido" in saida and "Alden" in saida
    tipos = [e.get("type") for e in memory.campaign["combat_state"]["log"]]
    assert "item_heal" in tipos and any(t.startswith("attack") for t in tipos)


def test_inimigo_inteiro_nao_gasta_pocao(campo):
    _bandido()["sheet"]["vida_atual"] = 40
    td.execute_npc_turn()
    assert _pocoes() == 2


def test_inimigo_na_metade_exata_ainda_bebe(campo):
    _bandido()["sheet"]["vida_atual"] = 20
    td.execute_npc_turn()
    assert _pocoes() == 1


def test_uma_pocao_por_turno(campo):
    random.seed(3)
    td.execute_npc_turn()
    assert _pocoes() == 1


def test_inimigo_sem_pocao_ataca_normalmente(campo):
    _bandido()["inventario"] = []
    saida = td.execute_npc_turn()
    assert "Poção" not in saida
    assert any((e.get("type") or "").startswith("attack")
               for e in memory.campaign["combat_state"]["log"])


def test_consumivel_que_nao_cura_nao_e_gasto_sozinho(campo):
    """
    O turno automático só bebe cura. Antitoxina e frasco de ácido são jogadas
    de leitura do campo — o mestre as usa pela narração, e gastá-las sozinho
    queimaria o item numa hora que ninguém escolheu.
    """
    _bandido()["inventario"] = [_item("Antitoxina"), _item("Frasco de Ácido", 2)]
    saida = td.execute_npc_turn()
    assert "Antitoxina" not in saida and "Ácido" not in saida
    qtds = {i["nome"]: i["qtd"] for i in _bandido()["inventario"]}
    assert qtds == {"Antitoxina": 1, "Frasco de Ácido": 2}


def test_item_que_nao_e_consumivel_fica_na_mochila(campo):
    _bandido()["inventario"] = [_item("Corda de Cânhamo"), _item("Algemas")]
    saida = td.execute_npc_turn()
    assert "Corda" not in saida and "Algemas" not in saida
    assert len(_bandido()["inventario"]) == 2


def test_inimigo_caido_nao_bebe(campo):
    """A 0 PV o inimigo está fora: o turno dele não é hora de poção."""
    _bandido()["sheet"]["vida_atual"] = 0
    _bandido()["status"] = "morto"
    td.execute_npc_turn()
    assert _pocoes() == 2


def test_heroi_do_grupo_nao_e_tocado_pelo_turno_do_npc(campo):
    """A ferramenta continua recusando agir por um personagem do grupo."""
    memory.campaign["combat_state"]["current_turn_index"] = 1
    saida = td.execute_npc_turn()
    assert saida.startswith("Aviso:") and "Alden" in saida
