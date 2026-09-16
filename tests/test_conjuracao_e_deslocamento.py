"""
test_conjuracao_e_deslocamento.py

CD de magia, ataque mágico e deslocamento saem do motor.

A CD de magia não existia em lugar nenhum: o mestre pedia "role Destreza CD
14" de cabeça, e o jogador não tinha como saber a CD das próprias magias. O
deslocamento também não — a ficha do herói mostrava vida, mana, CA,
iniciativa e percepção, e nada sobre quanto o personagem anda.

Regra: CD = 8 + proficiência + atributo de conjuração da classe; ataque
mágico = proficiência + o mesmo atributo. Deslocamento vem da raça, soma o
que monge e bárbaro ganham e desconta o que o motor já modela (exaustão e
carga).
"""
import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha


def _ficha(nome, **extras):
    ch = criar_ficha(nome, grupo=True, **extras)
    memory.campaign["characters"][memory.char_key(nome)] = ch
    memory.campaign["party"].append({"name": nome, "role": "", "notes": ""})
    return ch


def _heroi(nome):
    return td.hero_snapshot(nome)["personagem"]


# ---------------------------------------------------------------------------
# CD de magia e ataque mágico
# ---------------------------------------------------------------------------

def test_cd_e_ataque_do_conjurador(campanha):
    # Clériga nível 3 (prof +2) com SAB 17 (+3): CD 13, ataque +5.
    _ficha("Helena", classe="clerigo", nivel=3, sabedoria=17, proficiencia=2)
    conj = _heroi("Helena")["conjuracao"]
    assert (conj["cd"], conj["ataque"], conj["sigla"]) == (13, "+5", "SAB")


def test_cada_classe_usa_o_proprio_atributo(campanha):
    _ficha("Vhara", classe="mago", nivel=5, inteligencia=18, carisma=8, proficiencia=3)
    conj = _heroi("Vhara")["conjuracao"]
    # INT 18 (+4) e proficiência +3.
    assert (conj["cd"], conj["ataque"], conj["sigla"]) == (15, "+7", "INT")


def test_quem_nao_conjura_nao_tem_cd(campanha):
    _ficha("Grok", classe="barbaro", nivel=3)
    assert _heroi("Grok")["conjuracao"] is None


def test_a_ficha_do_mestre_traz_os_dois_numeros(campanha):
    _ficha("Helena", classe="clerigo", nivel=3, sabedoria=17, proficiencia=2)
    saida = td.get_character_sheet("Helena")
    assert "CD de magia: 13" in saida and "Ataque mágico: +5" in saida


# ---------------------------------------------------------------------------
# Deslocamento
# ---------------------------------------------------------------------------

def test_deslocamento_padrao_e_o_da_raca(campanha):
    _ficha("Stelar", classe="guerreiro", raca="humano")
    assert _heroi("Stelar")["deslocamento"]["metros"] == 9.0


def test_anao_halfling_e_gnomo_andam_menos(campanha):
    for nome, raca in (("Thorn", "anão"), ("Pip", "halfling"), ("Fizz", "gnomo")):
        ch = _ficha(nome, classe="guerreiro")
        ch["sheet"]["raca"] = raca
        assert _heroi(nome)["deslocamento"]["metros"] == 7.5, raca


def test_monge_sem_armadura_anda_mais(campanha):
    ch = _ficha("Kaelis", classe="monge", nivel=6,
                habilidades=[{"nome": "Movimento Sem Armadura", "descricao": "",
                              "custo_mana": 0, "dado": ""}])
    ch["sheet"]["equipamentos"] = {"armadura": None, "escudo": None,
                                   "arma_principal": "Espada Curta", "amuleto": None}
    d = _heroi("Kaelis")["deslocamento"]
    assert d["metros"] == 13.5          # 9 + 4,5 do nível 6
    assert any("Movimento Sem Armadura" in n for n in d["notas"])

    # De armadura, a habilidade não vale.
    ch["sheet"]["equipamentos"]["armadura"] = "Armadura de Peles"
    assert _heroi("Kaelis")["deslocamento"]["metros"] == 9.0


def test_barbaro_perde_o_bonus_com_armadura_pesada(campanha):
    ch = _ficha("Grok", classe="barbaro", nivel=5,
                habilidades=[{"nome": "Movimento Rápido", "descricao": "",
                              "custo_mana": 0, "dado": ""}])
    ch["sheet"]["equipamentos"] = {"armadura": "Armadura de Peles", "escudo": None,
                                   "arma_principal": "Machado Grande", "amuleto": None}
    assert _heroi("Grok")["deslocamento"]["metros"] == 12.0

    ch["sheet"]["equipamentos"]["armadura"] = "Cota de Malha"   # pesada
    assert _heroi("Grok")["deslocamento"]["metros"] == 9.0


def test_exaustao_e_carga_cortam_o_deslocamento(campanha):
    ch = _ficha("Stelar", classe="guerreiro", forca=16)
    ch["sheet"]["exaustao"] = 2
    d = _heroi("Stelar")["deslocamento"]
    assert d["metros"] == 4.5 and any("exaustão" in n for n in d["notas"])

    ch["sheet"]["exaustao"] = 5
    assert _heroi("Stelar")["deslocamento"]["metros"] == 0.0

    # FOR 16: capacidade 120 kg, sobrecarregado acima de 60.
    ch["sheet"]["exaustao"] = 0
    ch["inventario"] = [{"nome": "Bigorna", "qtd": 1, "descricao": "", "peso": 100}]
    d = _heroi("Stelar")["deslocamento"]
    assert d["metros"] == 6.0 and any("sobrecarga" in n for n in d["notas"])

    ch["inventario"] = [{"nome": "Bigorna", "qtd": 2, "descricao": "", "peso": 100}]
    d = _heroi("Stelar")["deslocamento"]
    assert d["metros"] == 0.0 and any("carga" in n for n in d["notas"])


def test_deslocamento_na_ficha_do_mestre(campanha):
    ch = _ficha("Thorn", classe="guerreiro")
    ch["sheet"]["raca"] = "anão"
    assert "Deslocamento: 7,5 m" in td.get_character_sheet("Thorn")
