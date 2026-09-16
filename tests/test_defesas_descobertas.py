"""
test_defesas_descobertas.py

Resistência, imunidade e vulnerabilidade do inimigo como informação
conquistada.

O card da tela tática listava as três desde o primeiro round: o jogador abria
a luta contra um zumbi já sabendo que ele resiste a corte e é vulnerável a
radiante. Nada no jogo tinha sido feito para merecer isso — nem um golpe, nem
um teste de conhecimento.

Regra: do inimigo, a tela mostra só o que o grupo descobriu. Descobre-se
batendo (o golpe que dá metade, zero ou o dobro mostra a defesa na prática)
ou por reveal_defenses(), que o mestre chama depois de um teste de
conhecimento. Dos personagens do grupo, a tela mostra tudo — a ficha é do
jogador.
"""
import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


@pytest.fixture
def campo(povoar):
    zumbi = criar_ficha("Zumbi", vida=30, vida_max=30,
                        resistencias=["necrotic"], vulnerabilidades=["radiant"],
                        imunidades=["poison"])
    heroi = criar_ficha("Alden", grupo=True, vida=30, vida_max=30,
                        resistencias=["fire"], imunidades=["poison"])
    povoar(heroi, zumbi)
    iniciar_combate(["Alden", "Zumbi"])
    return memory.campaign


def _card(nome):
    return next(c for c in td.combat_snapshot()["combatants"] if c["name"] == nome)


def _zumbi():
    return memory.campaign["characters"]["zumbi"]


def test_card_do_inimigo_comeca_mudo(campo):
    card = _card("Zumbi")
    assert card["resistencias"] == []
    assert card["imunidades"] == []
    assert card["vulnerabilidades"] == []


def test_a_ficha_do_grupo_continua_aberta(campo):
    """O jogador não precisa descobrir o próprio herói."""
    card = _card("Alden")
    assert card["resistencias"] == ["fire"]
    assert card["imunidades"] == ["poison"]


def test_golpe_que_da_metade_revela_a_resistencia(campo):
    td._apply_damage(_zumbi(), 10, "necrotic", source_name="Alden")
    card = _card("Zumbi")
    assert card["resistencias"] == ["necrotic"]
    # Só a que apareceu: o resto continua escondido.
    assert card["vulnerabilidades"] == [] and card["imunidades"] == []


def test_o_golpe_anota_so_a_defesa_que_ele_mostrou(campo):
    """
    O que fica anotado é o tipo e o campo daquele golpe. Anotar o tipo nos
    três campos não muda o card de hoje (a tela cruza com o que a criatura
    realmente tem), mas entrega a defesa errada assim que uma criatura
    resistir e for vulnerável ao mesmo tipo.
    """
    td._apply_damage(_zumbi(), 10, "necrotic", source_name="Alden")
    assert _zumbi()["sheet"]["descobertas"] == {"resistencias": ["necrotic"]}


def test_resistencia_e_vulnerabilidade_ao_mesmo_tipo_saem_juntas(campo):
    """Elas se cancelam no dano, e o jogador vê as duas ao mesmo tempo."""
    _zumbi()["sheet"]["vulnerabilidades"] = ["radiant", "necrotic"]
    td._apply_damage(_zumbi(), 10, "necrotic", source_name="Alden")
    card = _card("Zumbi")
    assert card["resistencias"] == ["necrotic"]
    assert card["vulnerabilidades"] == ["necrotic"]


def test_golpe_que_dobra_revela_a_vulnerabilidade(campo):
    td._apply_damage(_zumbi(), 6, "radiant", source_name="Alden")
    assert _card("Zumbi")["vulnerabilidades"] == ["radiant"]


def test_golpe_sem_efeito_revela_a_imunidade(campo):
    td._apply_damage(_zumbi(), 8, "poison", source_name="Alden")
    assert _card("Zumbi")["imunidades"] == ["poison"]


def test_tipo_sem_defesa_nao_revela_nada(campo):
    td._apply_damage(_zumbi(), 7, "slashing", source_name="Alden")
    card = _card("Zumbi")
    assert (card["resistencias"], card["imunidades"], card["vulnerabilidades"]) == ([], [], [])


def test_o_que_foi_descoberto_nao_se_perde(campo):
    td._apply_damage(_zumbi(), 10, "necrotic", source_name="Alden")
    td._apply_damage(_zumbi(), 5, "slashing", source_name="Alden")
    assert _card("Zumbi")["resistencias"] == ["necrotic"]


def test_ferramenta_revela_o_que_o_mestre_quiser(campo):
    saida = td.reveal_defenses("Zumbi", "radiante")
    assert "Vulnerável a radiant" in saida
    card = _card("Zumbi")
    assert card["vulnerabilidades"] == ["radiant"]
    # Pediu um tipo: os outros continuam escondidos.
    assert card["resistencias"] == [] and card["imunidades"] == []


def test_ferramenta_sem_tipo_revela_tudo(campo):
    td.reveal_defenses("Zumbi")
    card = _card("Zumbi")
    assert card["resistencias"] == ["necrotic"]
    assert card["imunidades"] == ["poison"]
    assert card["vulnerabilidades"] == ["radiant"]


def test_ferramenta_avisa_quando_ja_sabiam(campo):
    td.reveal_defenses("Zumbi", "necrótico")
    saida = td.reveal_defenses("Zumbi", "necrótico")
    assert "já sabia" in saida and "Resistente a necrotic" in saida


def test_ferramenta_diz_quando_nao_ha_o_que_revelar(campo):
    saida = td.reveal_defenses("Zumbi", "fogo")
    assert saida.startswith("Nota:") and "não há fraqueza" in saida
    assert _card("Zumbi")["resistencias"] == []


def test_ferramenta_com_personagem_inexistente_nao_quebra(campo):
    saida = td.reveal_defenses("Ninguém Existe")
    assert saida.startswith(("Erro:", "Personagem"))
