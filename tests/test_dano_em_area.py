"""
test_dano_em_area.py

Bola de Fogo em UM goblin.

O motor lia o dado certo (8d6, do texto do SRD, porque o Open5e não traz campo
de dano), rolava a salvaguarda certa, aplicava resistência e tipo de dano — e
tudo isso numa criatura só. A magia que existe para pegar o grupo inteiro
custava o mesmo que um Raio de Fogo e valia um terço dele. Mãos Flamejantes,
Sopro do Dragão e Onda Trovejante tinham o mesmo destino.

O tabuleiro já tinha zonas (set_battlefield): "quem está no Pátio" é pergunta
que o motor sabe responder, e é essa a unidade de área aqui.

O que estes testes prendem:
  • a leitura da área a partir do SRD, em pés e em metros;
  • a zona atingida: a do conjurador no cone, a do alvo na esfera;
  • um dado só para a área inteira e uma salvaguarda por criatura;
  • aliado na zona também leva — é o que torna a magia uma escolha;
  • SEM zonas, nada muda: a magia volta a ser de alvo único, como era.
"""
import random

import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


FOGO = {
    "nome": "Fireball", "custo_mana": 4, "dado": "8d6",
    "alcance": "150 feet",
    "descricao": ("[evocação] A bright streak flashes to a point you choose "
                  "within range and blossoms into flame. Each creature in a "
                  "20-foot-radius sphere centered on that point must make a "
                  "Dexterity saving throw. A target takes 8d6 fire damage on "
                  "a failed save, or half as much damage on a successful one."),
}
MAOS = {
    "nome": "Burning Hands", "custo_mana": 2, "dado": "3d6",
    "alcance": "Self (15-foot cone)",
    "descricao": ("[evocação] Each creature in a 15-foot cone must make a "
                  "Dexterity saving throw, taking 3d6 fire damage on a failed "
                  "save, or half as much damage on a successful one."),
}
RAIO = {
    "nome": "Fire Bolt", "custo_mana": 0, "dado": "1d10",
    "alcance": "120 feet",
    "descricao": "[evocação] Make a ranged spell attack. On a hit it takes 1d10 fire damage.",
}


@pytest.fixture
def mesa(campanha, povoar):
    """Mago e clérigo contra dois goblins, com o campo dividido em duas zonas."""
    povoar(criar_ficha("Vex", grupo=True, nivel=5, classe="mago"))
    povoar(criar_ficha("Helena", grupo=True, nivel=5, vida=40))
    povoar(criar_ficha("Goblin A", vida=20, ca=13))
    povoar(criar_ficha("Goblin B", vida=20, ca=13))
    vex = memory.campaign["characters"]["vex"]
    vex["sheet"]["mana_atual"] = vex["sheet"]["mana_max"] = 30
    vex["habilidades"] = [dict(FOGO), dict(MAOS), dict(RAIO)]
    iniciar_combate(["Vex", "Helena", "Goblin A", "Goblin B"])
    td.set_battlefield("Pátio, Sacada")
    return memory.campaign


def _zonas(**quem):
    for nome, zona in quem.items():
        td._por_zona(nome.replace("_", " "), zona)


def _vida(nome):
    return memory.campaign["characters"][memory.char_key(nome)]["sheet"]["vida_atual"]


# ---------------------------------------------------------------------------
# 1. Ler a área do texto do SRD
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hab, esperado", [
    (FOGO, "raio de 6 m"),            # "20-foot-radius sphere"
    (MAOS, "cone de 4,5 m"),          # 15 pés
    (RAIO, ""),                       # ataque, não área
    ({"descricao": "cone de 4,5 m de fogo"}, "cone de 4,5 m"),
    ({"descricao": "Cura 2d8 de vida."}, ""),
])
def test_a_area_sai_do_texto(hab, esperado):
    assert td.area_da_habilidade(hab) == esperado


def test_de_onde_a_area_nasce():
    assert td.origem_da_area(MAOS) == "self"      # Self (15-foot cone)
    assert td.origem_da_area(FOGO) == "alvo"      # 150 feet


# ---------------------------------------------------------------------------
# 2. Que zona a magia pega
# ---------------------------------------------------------------------------

def test_o_cone_pega_a_zona_de_quem_conjura(mesa):
    _zonas(Vex="Pátio", Helena="Sacada", Goblin_A="Pátio", Goblin_B="Sacada")
    zona, alvos = td._alvos_em_area("Vex", MAOS, "")
    assert zona == "Pátio"
    assert [a["name"] for a in alvos] == ["Goblin A"]   # o conjurador fica fora


def test_a_esfera_pega_a_zona_do_alvo(mesa):
    _zonas(Vex="Pátio", Helena="Pátio", Goblin_A="Sacada", Goblin_B="Sacada")
    zona, alvos = td._alvos_em_area("Vex", FOGO, "Goblin B")
    assert zona == "Sacada"
    assert sorted(a["name"] for a in alvos) == ["Goblin A", "Goblin B"]


def test_aliado_na_zona_tambem_entra(mesa):
    """A escolha é essa: a esfera não pergunta de que lado a criatura está."""
    _zonas(Vex="Pátio", Helena="Sacada", Goblin_A="Sacada", Goblin_B="Sacada")
    _, alvos = td._alvos_em_area("Vex", FOGO, "Goblin A")
    assert "Helena" in [a["name"] for a in alvos]


def test_quem_ja_caiu_nao_entra_na_conta(mesa):
    _zonas(Vex="Pátio", Helena="Pátio", Goblin_A="Sacada", Goblin_B="Sacada")
    memory.campaign["characters"]["goblin b"]["sheet"]["vida_atual"] = 0
    _, alvos = td._alvos_em_area("Vex", FOGO, "Goblin A")
    assert [a["name"] for a in alvos] == ["Goblin A"]


def test_sem_zonas_nao_ha_area(campanha, povoar):
    """Campanha antiga e modo narrado não mudam de regra no meio do combate."""
    povoar(criar_ficha("Vex", grupo=True, nivel=5, classe="mago"))
    povoar(criar_ficha("Goblin A", vida=20))
    iniciar_combate(["Vex", "Goblin A"])
    assert td._alvos_em_area("Vex", FOGO, "Goblin A") == ("", [])


def test_habilidade_que_nao_e_de_area_nao_vira_area(mesa):
    _zonas(Vex="Pátio", Helena="Pátio", Goblin_A="Pátio", Goblin_B="Pátio")
    assert td._alvos_em_area("Vex", RAIO, "Goblin A") == ("", [])


# ---------------------------------------------------------------------------
# 3. O dano de verdade
# ---------------------------------------------------------------------------

def test_a_bola_de_fogo_pega_os_dois_goblins(mesa):
    _zonas(Vex="Pátio", Helena="Pátio", Goblin_A="Sacada", Goblin_B="Sacada")
    random.seed(7)
    r = td.use_ability("Vex", "Fireball", target_name="Goblin A", end_turn=False)
    assert _vida("Goblin A") < 20, r
    assert _vida("Goblin B") < 20, "o segundo goblin saiu ileso da Bola de Fogo"
    assert "Sacada" in r and "raio de 6 m" in r


def test_cada_criatura_rola_a_propria_salvaguarda(mesa):
    """
    Um dado de dano para a área inteira (é o que o SRD manda) e uma
    salvaguarda por criatura — quem passa leva metade.
    """
    _zonas(Vex="Pátio", Helena="Pátio", Goblin_A="Sacada", Goblin_B="Sacada")
    random.seed(3)
    r = td.use_ability("Vex", "Fireball", target_name="Goblin A", end_turn=False)
    assert r.count("salvaguarda de DES") == 2, r
    perdas = {20 - _vida("Goblin A"), 20 - _vida("Goblin B")}
    assert len(perdas) <= 2 and all(p > 0 for p in perdas), r


def test_o_cone_nao_encosta_em_quem_esta_em_outra_zona(mesa):
    _zonas(Vex="Pátio", Helena="Sacada", Goblin_A="Pátio", Goblin_B="Sacada")
    random.seed(11)
    td.use_ability("Vex", "Burning Hands", target_name="", end_turn=False)
    assert _vida("Goblin A") < 20
    assert _vida("Goblin B") == 20, "o cone atravessou o campo"
    assert _vida("Helena") == 40


def test_o_conjurador_nao_se_queima(mesa):
    _zonas(Vex="Pátio", Helena="Pátio", Goblin_A="Pátio", Goblin_B="Sacada")
    random.seed(5)
    antes = _vida("Vex")
    td.use_ability("Vex", "Burning Hands", target_name="", end_turn=False)
    assert _vida("Vex") == antes


def test_sem_zonas_a_magia_continua_de_alvo_unico(campanha, povoar):
    povoar(criar_ficha("Vex", grupo=True, nivel=5, classe="mago"))
    povoar(criar_ficha("Goblin A", vida=30))
    povoar(criar_ficha("Goblin B", vida=30))
    vex = memory.campaign["characters"]["vex"]
    vex["sheet"]["mana_atual"] = vex["sheet"]["mana_max"] = 30
    vex["habilidades"] = [dict(FOGO)]
    iniciar_combate(["Vex", "Goblin A", "Goblin B"])

    random.seed(9)
    td.use_ability("Vex", "Fireball", target_name="Goblin A", end_turn=False)
    assert _vida("Goblin A") < 30
    assert _vida("Goblin B") == 30


# ---------------------------------------------------------------------------
# 4. O que a tela tática precisa saber
# ---------------------------------------------------------------------------

def test_o_modo_de_alvo_diz_a_verdade_para_a_tela(mesa):
    _zonas(Vex="Pátio", Helena="Pátio", Goblin_A="Sacada", Goblin_B="Sacada")
    assert td._ability_target_mode("Burning Hands", MAOS) == "area_self"
    assert td._ability_target_mode("Fireball", FOGO) == "area"
    assert td._ability_target_mode("Fire Bolt", RAIO) == "single"


def test_sem_zonas_a_tela_nao_promete_area(campanha, povoar):
    povoar(criar_ficha("Vex", grupo=True, nivel=5, classe="mago"))
    iniciar_combate(["Vex"])
    assert td._ability_target_mode("Fireball", FOGO) == "single"
    assert td._ability_target_mode("Burning Hands", MAOS) == "single"


def test_a_tela_tatica_sabe_o_que_fazer_com_os_modos_novos():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "static" / "js" / "combat.js"
          ).read_text(encoding="utf-8")
    # area_self não abre picker (a zona é a de quem conjura); area abre.
    assert "'area_self'" in js and "'area'" in js
