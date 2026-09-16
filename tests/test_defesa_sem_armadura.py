"""
test_defesa_sem_armadura.py

A habilidade de nível 1 do bárbaro e do monge entra na CA.

O motor calculava a CA sem armadura sempre como 10 + DES. O monge nasce sem
armadura nenhuma no kit: um monge de SAB 17 andava com CA 11 em vez de 14, e
o bárbaro que tirava a armadura de peles para lutar à vontade — o jeito de
jogar a classe — perdia CA em vez de ganhar.

Regra: sem armadura, bárbaro usa 10 + DES + CON e pode carregar escudo;
monge usa 10 + DES + SAB e perde a habilidade se pegar um escudo.
"""
from rpg import memory, tools_dnd as td


# Com o +1 em tudo do humano, a ficha sai com DES 17 (+3), CON 17 (+3) e
# SAB 15 (+2): a sabedoria difere dos outros dois, então trocar CON por SAB
# na conta muda o número e o teste vê.
ATRIBUTOS = dict(forca=15, destreza=16, constituicao=16, inteligencia=10,
                 sabedoria=14, carisma=8)


def _ficha(nome, classe, **extra):
    return td.create_character_sheet(nome, classe, "humano", **{**ATRIBUTOS, **extra})


def _sheet(nome):
    return memory.campaign["characters"][memory.char_key(nome)]["sheet"]


def test_monge_nasce_com_a_defesa_na_ca(campanha):
    resposta = _ficha("Kaelis", "monge")
    # 10 + DES 3 + SAB 2. Antes era 13, só com a destreza.
    assert _sheet("Kaelis")["ca"] == 15
    assert "CA: 15" in resposta


def test_barbaro_sem_armadura_troca_peles_por_constituicao(campanha):
    _ficha("Grok", "bárbaro")
    s = _sheet("Grok")
    # O kit veste armadura de peles: 12 + DES (máx. +2).
    assert s["equipamentos"]["armadura"] == "Armadura de Peles"
    assert s["ca"] == 14

    resposta = td.unequip_item("Grok", "armadura")
    # Sem armadura: 10 + DES 3 + CON 3.
    assert _sheet("Grok")["ca"] == 16
    assert "CA: 14 → 16" in resposta


def test_barbaro_sem_armadura_ainda_soma_o_escudo(campanha):
    _ficha("Grok", "bárbaro")
    td.unequip_item("Grok", "armadura")
    td.add_item("Grok", "Escudo", 1)
    td.equip_item("Grok", "Escudo", "escudo")
    assert _sheet("Grok")["ca"] == 18


def test_monge_com_escudo_perde_a_defesa(campanha):
    _ficha("Kaelis", "monge")
    td.add_item("Kaelis", "Escudo", 1)
    td.equip_item("Kaelis", "Escudo", "escudo")
    # Sem a habilidade: 10 + DES 3 + escudo 2. A SAB sai da conta.
    assert _sheet("Kaelis")["ca"] == 15

    td.unequip_item("Kaelis", "escudo")
    assert _sheet("Kaelis")["ca"] == 15


def test_armadura_vestida_manda_na_ca(campanha):
    """Vestindo armadura, a habilidade não vale — nem para melhorar a CA."""
    _ficha("Grok", "bárbaro")
    td.unequip_item("Grok", "armadura")
    assert _sheet("Grok")["ca"] == 16
    td.equip_item("Grok", "Armadura de Peles", "armadura")
    assert _sheet("Grok")["ca"] == 14


def test_classe_sem_a_habilidade_fica_no_dez_mais_destreza(campanha):
    _ficha("Helena", "clérigo")
    td.unequip_item("Helena", "armadura")
    td.unequip_item("Helena", "escudo")
    assert _sheet("Helena")["ca"] == 13


def test_constituicao_e_sabedoria_recalculam_a_ca(campanha):
    _ficha("Grok", "bárbaro")
    td.unequip_item("Grok", "armadura")
    resposta = td.set_stat("Grok", "constituicao", 18)
    assert _sheet("Grok")["ca"] == 17
    assert "CA: 16 → 17" in resposta

    _ficha("Kaelis", "monge")
    td.set_stat("Kaelis", "sabedoria", 16)
    assert _sheet("Kaelis")["ca"] == 16

    # Num guerreiro a sabedoria não mexe na CA.
    _ficha("Stelar", "guerreiro")
    ca_antes = _sheet("Stelar")["ca"]
    td.set_stat("Stelar", "sabedoria", 18)
    assert _sheet("Stelar")["ca"] == ca_antes


def test_incremento_de_atributo_no_nivel_atualiza_a_ca(campanha):
    # Nível 4, com o incremento ainda por gastar: a ficha criada já nasce com
    # o passado quitado, então o contador volta a zero como faz a tela de nível.
    _ficha("Kaelis", "monge", nivel=4)
    _sheet("Kaelis")["asi_pontos_gastos"] = 0
    resposta = td.apply_asi("Kaelis", "sabedoria", 2)
    # SAB 15 → 17 (o humano já somou +1 na criação): o modificador vai a +3.
    assert _sheet("Kaelis")["ca"] == 16
    assert "CA agora: 16" in resposta


def test_resistencia_draconica_continua_valendo(campanha):
    """A outra habilidade que troca a CA sem armadura não pode ter se perdido."""
    _ficha("Vhara", "feiticeiro")
    ch = memory.campaign["characters"][memory.char_key("Vhara")]
    ch["habilidades"].append({"nome": "Resistência Dracônica",
                              "descricao": "CA = 13 + DES quando sem armadura.",
                              "custo_mana": 0, "dado": ""})
    td._recalculate_ca(ch)
    assert _sheet("Vhara")["ca"] == 16


def test_habilidade_concedida_pelo_mestre_muda_a_ca_na_hora(campanha):
    """Sem isso, a CA só mudaria quando o personagem vestisse ou tirasse algo."""
    _ficha("Vhara", "feiticeiro")
    assert _sheet("Vhara")["ca"] == 13
    resposta = td.learn_ability("Vhara", "Resistência Dracônica",
                                "CA = 13 + DES quando sem armadura.", 0, "")
    assert _sheet("Vhara")["ca"] == 16
    assert "CA: 13 → 16" in resposta

    _ficha("Bruma", "ladino")
    td.unequip_item("Bruma", "armadura")
    ca_antes = _sheet("Bruma")["ca"]
    td.learn_ability("Bruma", "Defesa Sem Armadura", "10 + DES + CON sem armadura.", 0, "")
    assert _sheet("Bruma")["ca"] == ca_antes + 3
