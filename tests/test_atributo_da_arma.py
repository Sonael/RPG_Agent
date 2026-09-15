"""
test_atributo_da_arma.py

Arma de acuidade usa a Destreza quando ela é maior; arma à distância usa
sempre a Destreza. Os nomes precisam valer em português e em inglês.

Numa luta contra goblins o motor mostrou "d20=10 +-1(mod) +2(prof) = 11": o
goblin (FOR 8, DES 14) atacava de cimitarra com a Força. As listas do motor
só tinham nomes em português, e a arma do monstro chega do stat block em
inglês ("scimitar", "shortbow"). A rapieira do kit do ladino e do bardo caía
no mesmo buraco: a lista tinha "rapier", não "rapieira".
"""
import pytest

from rpg import memory, tools_dnd as td

GOBLIN = {"forca": 8, "destreza": 14}
BRUTAMONTES = {"forca": 18, "destreza": 10}


@pytest.mark.parametrize("arma", ["scimitar", "Cimitarra", "shortsword", "dagger",
                                  "Rapieira", "rapier", "Adaga", "whip"])
def test_acuidade_usa_a_destreza_quando_e_maior(arma):
    assert td._weapon_attr(arma, GOBLIN) == ("destreza", 2)
    assert td._weapon_attr(arma, BRUTAMONTES) == ("forca", 4)


@pytest.mark.parametrize("arma", ["shortbow", "Longbow", "Light Crossbow", "sling",
                                  "Arco Curto", "Besta Leve", "Dardos"])
def test_distancia_usa_sempre_a_destreza(arma):
    assert td._weapon_attr(arma, BRUTAMONTES) == ("destreza", 0)


@pytest.mark.parametrize("arma", ["Espada Longa", "Machado Grande", "Maça", "greataxe", "Javelin"])
def test_corpo_a_corpo_comum_usa_a_forca(arma):
    assert td._weapon_attr(arma, GOBLIN) == ("forca", -1)


def test_ladino_de_rapieira_acerta_com_a_destreza(campanha):
    td.create_character_sheet("Lyra", "ladino", "humano", 10, 16, 12, 12, 10, 8)
    memory.campaign["characters"]["lyra"]["party_member"] = True
    ataque = td.hero_snapshot("Lyra")["personagem"]["ataques"][0]
    assert ataque["arma"] == "Rapieira"
    assert ataque["atributo"] == "DES"
    assert ataque["acerto"] == "+5"
