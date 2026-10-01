"""
test_conjuracao_e_manobras.py

1. O inimigo não conjurava: no turno dele o motor só atacava, usava poder de
   recarga ou curava. O mago do Open5e trazia "Spellcasting" como texto
   cortado em 200 letras, nenhuma magia virava habilidade, e ele morria de
   adaga na mão com a Bola de Fogo na ficha.
2. As Manobras do Mestre de Batalha eram passivas: nenhuma manobra existia,
   nenhum Dado de Superioridade era gasto. O estilo Proteção também era texto.
3. A Contramágica gastava 5 de mana para anular um truque.
4. Com pontos de magia, do 6º círculo em diante é uma magia de cada por
   descanso longo — e o motor não cobrava.
"""
import random

import pytest

from rpg import memory, reacoes, resolucao, superioridade, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _ch(nome):
    return memory.campaign["characters"].get(memory.char_key(nome))


def _hab(nome, custo=2):
    return {"nome": nome, "custo_mana": custo, "dado": "", "descricao": ""}


def _vez(nome):
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index(nome)
    cs["turn_token"] = int(cs.get("turn_token", 0) or 0) + 1
    td._reset_turn_economy(cs)


def _d20(monkeypatch, valor):
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda *a, **k: (valor, f"d20={valor}"))


# ---------------------------------------------------------------------------
# 1. O bloco de conjuração do Open5e e o inimigo que conjura
# ---------------------------------------------------------------------------

BLOCO_MAGO = (
    "The mage is a 9th-level spellcaster. Its spellcasting ability is Intelligence (spell save DC 14, "
    "+6 to hit with spell attacks). The mage has the following wizard spells prepared:\n\n"
    "• Cantrips (at will): fire bolt, light, mage hand, prestidigitation\n"
    "• 1st level (4 slots): detect magic, mage armor, magic missile, shield\n"
    "• 2nd level (3 slots): misty step, suggestion\n"
    "• 3rd level (3 slots): counterspell, fireball, fly\n"
    "• 4th level (3 slots): greater invisibility, ice storm\n"
    "• 5th level (1 slot): cone of cold")

BLOCO_INATO = ("The drow's spellcasting ability is Charisma (spell save DC 11). It can innately cast the "
               "following spells, requiring no material components:\nAt will: dancing lights\n"
               "1/day each: darkness, faerie fire")


def test_le_o_bloco_do_mago():
    bloco = td._magias_do_bloco(BLOCO_MAGO)
    assert bloco["nivel_conjurador"] == 9 and bloco["atributo"] == "inteligencia"
    nomes = {n for n, _, _ in bloco["magias"]}
    assert {"Fire Bolt", "Magic Missile", "Fireball", "Cone of Cold", "Counterspell"} <= nomes


def test_poe_as_magias_na_ficha_com_mana():
    sheet, habs = {"mana_max": 0, "mana_atual": 0}, []
    td._dar_magias_do_bloco(sheet, habs, BLOCO_MAGO)
    assert sheet["mana_max"] == td.SPELL_POINTS_BY_LEVEL[9]
    assert sheet["atributo_conjuracao"] == "inteligencia"
    bola = next(h for h in habs if h["nome"] == "Fireball")
    assert bola["custo_mana"] == td.SPELL_MANA_COST[3] and bola["nivel_magia"] == 3
    assert next(h for h in habs if h["nome"] == "Fire Bolt")["custo_mana"] == 0


def test_conjuracao_inata():
    sheet, habs = {}, []
    td._dar_magias_do_bloco(sheet, habs, BLOCO_INATO)
    assert {h["nome"] for h in habs} == {"Dancing Lights", "Darkness", "Faerie Fire"}
    assert sheet["atributo_conjuracao"] == "carisma" and sheet["mana_max"] > 0


class _Resposta:
    ok = True

    def __init__(self, dados):
        self._dados = dados

    def json(self):
        return self._dados


def test_spawn_monster_le_o_bloco_inteiro(campanha, monkeypatch):
    """O Open5e manda o bloco com mais de 200 letras: o motor lê inteiro, não a descrição cortada."""
    from rpg import open5e
    mago = {"name": "Mage", "hit_points": 40, "armor_class": 12, "strength": 9, "dexterity": 14,
            "constitution": 11, "intelligence": 17, "wisdom": 12, "charisma": 11,
            "challenge_rating": "6", "type": "humanoid", "size": "Medium",
            "actions": [{"name": "Dagger", "desc": "Melee Weapon Attack: +5 to hit. Hit: 4 (1d4 + 2) piercing damage.",
                         "attack_bonus": 5, "damage_dice": "1d4"}],
            "special_abilities": [{"name": "Spellcasting", "desc": BLOCO_MAGO}]}
    monkeypatch.setattr(open5e.http, "get", lambda *a, **k: _Resposta(mago))
    td.spawn_monster("mage", "Mago Sombrio")
    ficha = _ch("Mago Sombrio")
    nomes = {h["nome"] for h in ficha["habilidades"]}
    assert {"Fireball", "Magic Missile", "Cone of Cold"} <= nomes
    assert ficha["sheet"]["mana_max"] == td.SPELL_POINTS_BY_LEVEL[9]
    assert td._conjuracao(ficha["sheet"])["cd"] == 8 + 3 + 3          # prof 3 (ND 6) + INT 17


@pytest.fixture
def mago_inimigo(campanha, povoar):
    habs = []
    sheet_extra = {}
    povoar(criar_ficha("Alden", grupo=True, vida=60, ca=12),
           criar_ficha("Kaelen", grupo=True, vida=60, ca=12),
           criar_ficha("Necromante", vida=40, inteligencia=17, nivel=9, mana=0, arma="adaga",
                       ataques=[{"nome": "adaga", "dado": "1d4", "tipo": "piercing"}]))
    nec = _ch("Necromante")
    td._dar_magias_do_bloco(nec["sheet"], habs, BLOCO_MAGO)
    nec["habilidades"] = habs
    iniciar_combate(["Necromante", "Alden", "Kaelen"])
    cs = memory.campaign["combat_state"]
    cs["zonas"] = ["Torre", "Pátio"]
    cs["posicoes"] = {"necromante": "Torre", "alden": "Pátio", "kaelen": "Pátio"}
    _vez("Necromante")
    return memory.campaign


def test_inimigo_conjura_area_no_grupo_reunido(mago_inimigo, monkeypatch):
    monkeypatch.setattr(td, "_rolar_salvaguarda", lambda *a, **k: (False, "salvaguarda: falhou"))
    saida = td._executar_turno_npc("Necromante")
    assert "conjura" in saida and ("Bola de Fogo" in saida or "Cone" in saida or "Tempestade" in saida), saida
    assert _ch("Alden")["sheet"]["vida_atual"] < 60 and _ch("Kaelen")["sheet"]["vida_atual"] < 60
    assert _ch("Necromante")["sheet"]["mana_atual"] < td.SPELL_POINTS_BY_LEVEL[9]


def test_inimigo_nao_poe_aliado_na_area(mago_inimigo, monkeypatch):
    monkeypatch.setattr(td, "_rolar_salvaguarda", lambda *a, **k: (False, "salvaguarda: falhou"))
    povo = criar_ficha("Esqueleto", vida=20)
    memory.campaign["characters"]["esqueleto"] = povo
    cs = memory.campaign["combat_state"]
    cs["initiative_order"].append("Esqueleto")
    cs["posicoes"]["esqueleto"] = "Pátio"
    saida = td._executar_turno_npc("Necromante")
    assert _ch("Esqueleto")["sheet"]["vida_atual"] == 20, saida


def test_sem_mana_o_inimigo_ataca(mago_inimigo, monkeypatch):
    _ch("Necromante")["sheet"]["mana_atual"] = 0
    _ch("Necromante")["habilidades"] = [h for h in _ch("Necromante")["habilidades"] if h["custo_mana"] > 0]
    _d20(monkeypatch, 15)
    memory.campaign["combat_state"]["posicoes"]["necromante"] = "Pátio"
    saida = td._executar_turno_npc("Necromante")
    assert "conjura" not in saida and "adaga" in saida.lower(), saida


# ---------------------------------------------------------------------------
# 2. Manobras do Mestre de Batalha
# ---------------------------------------------------------------------------

@pytest.fixture
def batalha(campanha, povoar):
    povoar(criar_ficha("Tor", grupo=True, classe="guerreiro", nivel=7, forca=18, vida=60,
                       habilidades=[_hab("Manobras de Combate", 0), _hab("Dado de Superioridade", 0)],
                       feature_choices={"Manobras de Combate": ["Ataque Derrubador", "Finta", "Contra-Ataque",
                                                                "Aparar", "Ataque Preciso"]}),
           criar_ficha("Alden", grupo=True, vida=40, ca=10),
           criar_ficha("Orc", vida=80, raca="orc", arma="machado grande", ca=12))
    iniciar_combate(["Tor", "Alden", "Orc"])
    _vez("Tor")
    return memory.campaign


def _usar(ator, hab, alvo="", modo=""):
    return td.combat_action("ability", actor=ator, ability=hab, target=alvo, weapon=modo)


def test_so_as_manobras_aprendidas_e_o_pool(batalha):
    modos = resolucao.modos_de("manobras de combate", _ch("Tor"))
    assert set(modos) == {"ataque derrubador", "finta", "ataque preciso"}     # reações ficam com o motor
    assert superioridade.restantes(_ch("Tor")) == 5 and superioridade.dado(_ch("Tor")) == 8
    assert resolucao.como_resolve(_hab("Dado de Superioridade", 0))["tipo"] == "passiva"


def test_ataque_derrubador_gasta_o_dado_so_no_acerto(batalha, monkeypatch):
    monkeypatch.setattr(td, "_rolar_salvaguarda", lambda *a, **k: (False, "salvaguarda: falhou"))
    r = _usar("Tor", "Manobras de Combate", modo="ataque derrubador")
    assert r["ok"] and not memory.campaign["combat_state"]["turn_economy"]["acao_usada"], r["message"]
    _d20(monkeypatch, 2)
    td.combat_action("attack", actor="Tor", target="Orc", weapon="espada longa")
    assert superioridade.restantes(_ch("Tor")) == 5                 # errou: nada gasto
    _d20(monkeypatch, 18)
    saida = td.attack_roll("Tor", "Orc", "espada longa", 8, end_turn=False, _skip_turn_check=True)
    assert "Ataque Derrubador: 1d8" in saida and "CAÍDO" in saida, saida
    assert superioridade.restantes(_ch("Tor")) == 4


def test_finta_e_acao_bonus_com_alvo(batalha):
    r = _usar("Tor", "Manobras de Combate", "Orc", "finta")
    assert r["ok"], r["message"]
    eco = memory.campaign["combat_state"]["turn_economy"]
    assert eco["bonus_usada"] and not eco["acao_usada"]
    assert td._mods_de_ataque(_ch("Tor"), _ch("Orc"), True)["vantagem"]
    assert superioridade.restantes(_ch("Tor")) == 4


def test_finta_sem_alvo_recusa(batalha):
    assert not _usar("Tor", "Manobras de Combate", modo="finta")["ok"]


def test_ataque_preciso_salva_o_erro(batalha, monkeypatch):
    _usar("Tor", "Manobras de Combate", modo="ataque preciso")
    _d20(monkeypatch, 7)                 # 7 + 4 + 2 = 13 vs CA 12 → já acerta: não gasta
    td.attack_roll("Tor", "Orc", "espada longa", 8, end_turn=False, _skip_turn_check=True)
    assert superioridade.restantes(_ch("Tor")) == 5
    _d20(monkeypatch, 4)                 # 10 vs 12: erra; +d8 máximo
    monkeypatch.setattr(random, "randint", lambda a, b: b)
    saida = td.attack_roll("Tor", "Orc", "espada longa", 8, end_turn=False, _skip_turn_check=True)
    assert "Ataque Preciso" in saida and "ACERTO" in saida, saida
    assert superioridade.restantes(_ch("Tor")) == 4


def test_contra_ataque_quando_o_inimigo_erra(batalha, monkeypatch):
    _d20(monkeypatch, 2)
    saida = td.attack_roll("Orc", "Tor", "machado grande", 12, end_turn=False, _skip_turn_check=True)
    assert "Tor usa Contra-Ataque" in saida and "Tor ataca Orc" in saida, saida
    assert superioridade.restantes(_ch("Tor")) == 4


def test_aparar_reduz_o_dano(batalha, monkeypatch):
    _d20(monkeypatch, 18)
    monkeypatch.setattr(random, "randint", lambda a, b: b)
    saida = td.attack_roll("Orc", "Tor", "machado grande", 12, end_turn=False, _skip_turn_check=True)
    assert "apara o golpe" in saida, saida
    # 1d12+3 máximo = 15; aparar = 8 + 0 (DES 12 → +1) = 9 → 6.
    assert _ch("Tor")["sheet"]["vida_atual"] == 60 - (15 - 9)


def test_reacoes_do_mestre_de_batalha_aparecem_e_desligam(batalha):
    chaves = {r["chave"] for r in reacoes.disponiveis(_ch("Tor"))}
    assert {"contra ataque", "aparar"} <= chaves
    reacoes.alternar("Tor", "aparar", False)
    assert not reacoes._pode_reagir(_ch("Tor"), "aparar")


def test_estilo_protecao_da_desvantagem(campanha, povoar, monkeypatch):
    povoar(criar_ficha("Guarda", grupo=True, feature_choices={"Estilo de Combate": "Proteção"},
                       equipamentos={"armadura": None, "escudo": "Escudo", "arma_principal": "espada longa",
                                     "amuleto": None}),
           criar_ficha("Mira", grupo=True, vida=20),
           criar_ficha("Orc"))
    iniciar_combate(["Guarda", "Mira", "Orc"])
    pedidos = []
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda v, d: (pedidos.append(d), (10, "d20=10"))[1])
    saida = td.attack_roll("Orc", "Mira", "machado grande", 12, end_turn=False, _skip_turn_check=True)
    assert "Proteção" in saida and pedidos[0] is True, saida


# ---------------------------------------------------------------------------
# 4. Do 6º círculo em diante, uma de cada por descanso longo
# ---------------------------------------------------------------------------

def test_sexto_circulo_uma_vez_por_descanso(campanha, povoar):
    povoar(criar_ficha("Mira", grupo=True, classe="mago", nivel=17, mana=133,
                       habilidades=[_hab("Chain Lightning", 9), _hab("Disintegrate", 9)]),
           criar_ficha("Orc", vida=300))
    iniciar_combate(["Mira", "Orc"])
    _vez("Mira")
    assert not td.use_ability("Mira", "Chain Lightning", "Orc", end_turn=False).startswith(("Erro", "Aviso"))
    r = td.use_ability("Mira", "Disintegrate", "Orc", end_turn=False)
    assert r.startswith("Aviso") and "6º círculo" in r
    td.end_combat()
    td.long_rest("Mira")
    iniciar_combate(["Mira", "Orc"])
    _vez("Mira")
    assert not td.use_ability("Mira", "Disintegrate", "Orc", end_turn=False).startswith(("Erro", "Aviso"))
