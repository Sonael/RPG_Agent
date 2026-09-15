"""
test_kit_inicial.py

create_character_sheet entrega o kit da classe.

Numa campanha, o mestre criou a ficha da Helena (clériga) quando ela entrou
no grupo, e ela veio com a mochila vazia: CA 10, sem armadura, sem maça, sem
poção e 0 de ouro. A instrução pedia add_item e modify_currency logo depois,
e o mestre não chamou.
"""
import pytest

from rpg import memory, tools as tl, tools_dnd as td


ATRIBUTOS = dict(forca=13, destreza=12, constituicao=15, inteligencia=11, sabedoria=17, carisma=13)


def _ficha(nome, classe, **extra):
    return td.create_character_sheet(nome, classe, "humano", **{**ATRIBUTOS, **extra})


def _itens(nome):
    ch = memory.campaign["characters"][memory.char_key(nome)]
    return {i["nome"]: i["qtd"] for i in ch["inventario"]}


def test_cleriga_recrutada_vem_equipada(campanha):
    resposta = _ficha("Helena", "clérigo")
    ch = memory.campaign["characters"]["helena"]
    s = ch["sheet"]

    itens = _itens("Helena")
    for nome in ("Cota de Malha", "Escudo", "Maça", "Símbolo Sagrado"):
        assert nome in itens
    assert itens["Poção de Cura"] == 2
    assert s["equipamentos"]["armadura"] == "Cota de Malha"
    assert s["equipamentos"]["escudo"] == "Escudo"
    assert s["equipamentos"]["arma_principal"] == "Maça"
    # Cota de malha (16, ignora DES) + escudo (+2): a CA sai da tabela do motor.
    assert s["ca"] == 18
    assert (s["ouro"], s["prata"]) == (10, 5)
    assert "CA: 18" in resposta and "Kit inicial:" in resposta and "Ouro: 10" in resposta


@pytest.mark.parametrize("classe", sorted(td.KIT_INICIAL))
def test_todo_kit_veste_sem_erro(campanha, classe):
    """Nome de armadura ou arma que o motor não reconhece ficaria na mochila
    sem ir para o corpo, e a CA não mudaria: todo item de 'vestir' tem que
    terminar num slot."""
    _ficha("Teste", classe)
    ch = memory.campaign["characters"]["teste"]
    equip = ch["sheet"]["equipamentos"]
    for nome, slot in td.KIT_INICIAL[classe]["vestir"]:
        assert equip.get(slot) == nome, (classe, slot, equip)
    nomes = {n for n, _, _ in td.KIT_INICIAL[classe]["itens"]}
    for nome, _ in td.KIT_INICIAL[classe]["vestir"]:
        assert nome in nomes, f"{classe}: {nome} é vestido mas não está na mochila"


def test_ca_de_quem_usa_armadura_leve_soma_a_destreza(campanha):
    _ficha("Lyra", "ladino", destreza=16)
    assert memory.campaign["characters"]["lyra"]["sheet"]["ca"] == 11 + 3


def test_classe_sem_acento_e_em_maiuscula(campanha):
    _ficha("Borin", "Clerigo")
    assert memory.campaign["characters"]["borin"]["sheet"]["equipamentos"]["armadura"] == "Cota de Malha"


def test_classe_fora_da_tabela_ganha_o_basico(campanha):
    _ficha("Pip", "artífice")
    assert set(_itens("Pip")) == {"Adaga", "Pacote de Explorador", "Poção de Cura"}
    assert memory.campaign["characters"]["pip"]["sheet"]["equipamentos"]["arma_principal"] == "Adaga"


def test_npc_de_combate_nao_ganha_kit(campanha):
    _ficha("Capanga", "npc")
    assert _itens("Capanga") == {}


def test_quem_ja_carregava_coisas_fica_com_o_que_tem(campanha):
    tl.save_character("Helena", "Sacerdotisa do templo.", local="Templo de Lathander")
    td.add_item("Helena", "Rosário de Contas")
    _ficha("Helena", "clérigo")
    assert _itens("Helena") == {"Rosário de Contas": 1}


def test_npc_que_ja_existia_mantem_local_e_o_que_o_grupo_sabe(campanha):
    tl.save_character("Helena", "Sacerdotisa do templo.", local="Templo de Lathander")
    ch = memory.campaign["characters"]["helena"]
    ch["atitude"] = 40
    ch["conhecido"] = ["Cuida dos órfãos do templo"]
    ch["party_member"] = True

    _ficha("Helena", "clérigo")

    ch = memory.campaign["characters"]["helena"]
    assert ch["local"] == "Templo de Lathander"
    assert ch["atitude"] == 40 and ch["conhecido"] == ["Cuida dos órfãos do templo"]
    assert ch["party_member"] is True
    assert ch["description"] == "Sacerdotisa do templo."
    assert ch["sheet"]["classe"] == "clérigo"


def test_criar_de_novo_nao_da_o_kit_outra_vez(campanha):
    _ficha("Helena", "clérigo")
    s = memory.campaign["characters"]["helena"]["sheet"]
    s["ouro"] = 3
    antes = _itens("Helena")
    assert "JÁ possui ficha" in _ficha("Helena", "clérigo")
    assert s["ouro"] == 3 and _itens("Helena") == antes
