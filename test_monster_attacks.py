"""
test_monster_attacks.py
Regressão do dano de monstro e do Ataque Múltiplo.

O BUG QUE ESTES TESTES TRANCAM
──────────────────────────────
spawn_monster lia o dado de dano do Open5e, gravava em sheet["arma_dado"]…
e nada nunca lia esse campo. attack_roll ia buscar "bite"/"claw" em /weapons/,
tomava 404 e caía no fallback de 1d6 — então TODO monstro do jogo batia 1d6,
independente do stat block, e o CR do encontro não significava nada. O
Multiattack, por sua vez, era simplesmente descartado na extração de ações.
"""

import random

import pytest

import memory
import tools_dnd as T


# ---------------------------------------------------------------------------
# Blocos de monstro no formato do Open5e
# ---------------------------------------------------------------------------

URSO_CORUJA = {
    "name": "Owlbear",
    "type": "monstrosity",
    "size": "Large",
    "hit_points": 59,
    "armor_class": 13,
    "strength": 20, "dexterity": 12, "constitution": 17,
    "intelligence": 3, "wisdom": 12, "charisma": 7,
    "challenge_rating": "3",
    "actions": [
        {"name": "Multiattack",
         "desc": "The owlbear makes two attacks: one with its beak and one "
                 "with its claws."},
        {"name": "Beak",
         "desc": "Melee Weapon Attack: +7 to hit, reach 5 ft., one creature. "
                 "Hit: 10 (1d10 + 5) piercing damage.",
         "damage_dice": "1d10"},
        {"name": "Claws",
         "desc": "Melee Weapon Attack: +7 to hit, reach 5 ft., one target. "
                 "Hit: 14 (2d8 + 5) slashing damage.",
         "damage_dice": "2d8"},
    ],
}

ARQUEIRO = {
    "name": "Scout",
    "actions": [
        {"name": "Longbow",
         "desc": "Ranged Weapon Attack: +4 to hit, range 150/600 ft. "
                 "Hit: 6 (1d8 + 2) piercing damage.",
         "damage_dice": "1d8"},
    ],
}

# Bloco real do Open5e. A armadilha está na descrição do Multiattack: ela
# contém "melee attacks:", que casa com a checagem ingênua por "melee attack"
# — e fazia a PRÓPRIA ação Multiattack virar a arma principal, sem dado.
CAPITAO_BANDIDO = {
    "name": "Bandit Captain",
    "challenge_rating": "2",
    "actions": [
        {"name": "Multiattack",
         "desc": "The captain makes three melee attacks: two with its scimitar "
                 "and one with its dagger. Or the captain makes two ranged "
                 "attacks with its daggers."},
        {"name": "Scimitar",
         "desc": "Melee Weapon Attack: +5 to hit, reach 5 ft., one target. "
                 "Hit: 6 (1d6 + 3) slashing damage.",
         "damage_dice": "1d6"},
        {"name": "Dagger",
         "desc": "Melee or Ranged Weapon Attack: +5 to hit, reach 5 ft. or "
                 "range 20/60 ft., one target. Hit: 5 (1d4 + 3) piercing damage.",
         "damage_dice": "1d4"},
    ],
}


# ---------------------------------------------------------------------------
# _parse_multiattack
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("desc, esperado", [
    ("The owlbear makes two attacks: one with its beak and one with its claws.", 2),
    ("The bandit captain makes three attacks: two with its scimitar and one "
     "with its dagger.", 3),
    ("The mage makes 2 ranged attacks.", 2),
    ("The knight makes two melee weapon attacks.", 2),
    ("The wolf makes one attack with its bite.", 1),     # singular → sem multi
    ("The dragon uses its Frightful Presence.", 1),      # sem contagem → 1
])
def test_parse_multiattack(desc, esperado):
    acoes = [{"name": "Multiattack", "desc": desc}]
    assert T._parse_multiattack(acoes) == esperado


def test_parse_multiattack_sem_a_acao():
    assert T._parse_multiattack([{"name": "Bite", "desc": "Melee Weapon Attack..."}]) == 1


def test_parse_multiattack_tem_teto():
    """Descrição estranha não pode virar um monstro com 40 ataques por turno."""
    acoes = [{"name": "Multiattack", "desc": "The thing makes 99 attacks."}]
    assert T._parse_multiattack(acoes) == T._MULTIATTACK_MAX


# ---------------------------------------------------------------------------
# _extract_monster_attacks
# ---------------------------------------------------------------------------

def test_extrai_todos_os_ataques_com_seus_dados():
    info = T._extract_monster_attacks(URSO_CORUJA)
    por_nome = {a["nome"]: a["dado"] for a in info["ataques"]}
    assert por_nome == {"beak": "1d10", "claws": "2d8"}
    assert info["arma_principal"] == "beak"
    assert info["arma_dado"] == "1d10"
    assert info["multiattack"] == 2


def test_multiattack_nao_e_tratado_como_ataque():
    """A ação 'Multiattack' não tem 'Melee Weapon Attack' — não vira golpe."""
    nomes = [a["nome"] for a in T._extract_monster_attacks(URSO_CORUJA)["ataques"]]
    assert "multiattack" not in nomes


def test_multiattack_com_melee_attacks_na_descricao_nao_vira_arma():
    """
    Regressão do Bandit Captain: 'makes three melee attacks:' casava com a
    checagem por 'melee attack' e a ação Multiattack era promovida a arma
    principal — sem dado, e portanto de volta ao 1d6 genérico.
    """
    info = T._extract_monster_attacks(CAPITAO_BANDIDO)
    nomes = [a["nome"] for a in info["ataques"]]

    assert "multiattack" not in nomes
    assert info["arma_principal"] == "scimitar"
    assert info["arma_dado"] == "1d6"
    assert info["multiattack"] == 3


def test_arma_principal_nunca_fica_sem_dado_havendo_alternativa():
    """
    Uma arma principal sem dado é o caminho de volta ao fallback. Havendo
    qualquer ataque com dado, ele tem preferência.
    """
    monstro = {"actions": [
        {"name": "Gore",
         "desc": "Melee Weapon Attack: +5 to hit, reach 5 ft. Hit: bludgeoning damage."},
        {"name": "Bite",
         "desc": "Melee Weapon Attack: +5 to hit, reach 5 ft. Hit: 9 (2d6 + 2) piercing.",
         "damage_dice": "2d6"},
    ]}
    info = T._extract_monster_attacks(monstro)
    assert info["arma_principal"] == "bite"
    assert info["arma_dado"] == "2d6"


def test_acao_sem_bonus_de_acerto_nao_e_ataque():
    """Sopro de dragão e afins usam salvaguarda, não d20 de acerto."""
    monstro = {"actions": [
        {"name": "Fire Breath",
         "desc": "The dragon exhales fire in a 15-foot cone. Each creature in "
                 "that area must make a DC 13 Dexterity saving throw.",
         "damage_dice": "7d6"},
    ]}
    assert T._extract_monster_attacks(monstro)["ataques"] == []


def test_monstro_so_a_distancia_usa_o_arco_como_principal():
    info = T._extract_monster_attacks(ARQUEIRO)
    assert info["arma_principal"] == "longbow"
    assert info["arma_dado"] == "1d8"
    assert info["ataques"][0]["ranged"] is True


def test_dado_vem_da_descricao_quando_falta_damage_dice():
    monstro = {"actions": [{
        "name": "Slam",
        "desc": "Melee Weapon Attack: +4 to hit. Hit: 7 (2d4 + 2) bludgeoning damage.",
    }]}
    assert T._extract_monster_attacks(monstro)["arma_dado"] == "2d4"


def test_monstro_sem_acoes_nao_quebra():
    info = T._extract_monster_attacks({})
    assert info["ataques"] == []
    assert info["arma_principal"] == ""
    assert info["multiattack"] == 1


# ---------------------------------------------------------------------------
# _npc_attack_dice
# ---------------------------------------------------------------------------

def test_dado_resolvido_pela_lista_de_ataques():
    sheet = {"ataques": [{"nome": "claws", "dado": "2d8", "ranged": False}]}
    assert T._npc_attack_dice(sheet, "Claws") == (2, 8)


def test_dado_resolvido_em_ficha_antiga_sem_lista_de_ataques():
    """Fichas salvas antes do campo 'ataques' continuam funcionando."""
    sheet = {
        "equipamentos": {"arma_principal": "bite"},
        "arma_dado": "1d12",
    }
    assert T._npc_attack_dice(sheet, "bite") == (1, 12)


def test_dado_da_arma_secundaria():
    sheet = {"arma_secundaria": "longbow", "arma_dado_secundaria": "1d8"}
    assert T._npc_attack_dice(sheet, "longbow") == (1, 8)


def test_ataque_desconhecido_devolve_none():
    """None faz attack_roll seguir para a busca normal de arma do SRD."""
    sheet = {"ataques": [{"nome": "claws", "dado": "2d8"}]}
    assert T._npc_attack_dice(sheet, "espada longa") is None


# ---------------------------------------------------------------------------
# Integração: o dano que o motor realmente rola
# ---------------------------------------------------------------------------

def _monta_campanha():
    """Uma campanha limpa com um urso-coruja e um herói resistente."""
    memory.campaign["characters"] = {}
    memory.campaign["party"] = [{"name": "Heroína", "role": "guerreira", "notes": ""}]
    memory.campaign["protagonist"] = "Heroína"
    memory.campaign["combat_state"] = {
        "is_active": False, "initiative_order": [], "current_turn_index": 0,
        "round": 1, "turn_resolved": False, "npc_strategies": {},
        "turn_auto_advanced": False, "turn_token": 0, "log": [], "result": None,
        "turn_economy": {"acao_usada": False, "bonus_usada": False},
    }

    info = T._extract_monster_attacks(URSO_CORUJA)
    memory.campaign["characters"]["urso-coruja"] = {
        "name": "Urso-Coruja", "status": "inimigo", "description": "", "traits": "",
        "notes": "", "habilidades": [], "inventario": [],
        "sheet": {
            "classe": "npc", "raca": "owlbear", "nivel": 3, "xp": 0, "xp_proximo": 100,
            "forca": 20, "destreza": 12, "constituicao": 17,
            "inteligencia": 3, "sabedoria": 12, "carisma": 7,
            "vida_atual": 59, "vida_max": 59, "mana_atual": 0, "mana_max": 0,
            "ca": 13, "proficiencia": 2, "hit_die": 10,
            "ouro": 0, "prata": 0, "cobre": 0,
            "equipamentos": {"armadura": None, "escudo": None,
                             "arma_principal": info["arma_principal"], "amuleto": None},
            "ataques": info["ataques"],
            "arma_dado": info["arma_dado"],
            "arma_secundaria": info["arma_secundaria"] or None,
            "arma_dado_secundaria": info["arma_dado_secundaria"],
            "multiattack": info["multiattack"],
            "condicoes": [], "death_saves_sucessos": 0, "death_saves_falhas": 0,
        },
    }
    memory.campaign["characters"]["heroína"] = {
        "name": "Heroína", "status": "vivo", "party_member": True,
        "description": "", "traits": "", "notes": "",
        "habilidades": [], "inventario": [],
        "sheet": {
            "classe": "guerreiro", "raca": "humano", "nivel": 5, "xp": 0,
            "xp_proximo": 14000, "forca": 16, "destreza": 12, "constituicao": 16,
            "inteligencia": 10, "sabedoria": 10, "carisma": 10,
            "vida_atual": 400, "vida_max": 400, "mana_atual": 0, "mana_max": 0,
            "ca": 5, "proficiencia": 3, "hit_die": 10,
            "ouro": 0, "prata": 0, "cobre": 0,
            "equipamentos": {"armadura": None, "escudo": None,
                             "arma_principal": "espada longa", "amuleto": None},
            "condicoes": [], "death_saves_sucessos": 0, "death_saves_falhas": 0,
        },
    }


@pytest.fixture
def campanha():
    _monta_campanha()
    yield memory.campaign


@pytest.fixture
def dados_registrados(monkeypatch):
    """
    Substitui o gerador de dados por um que REGISTRA cada rolagem e devolve o
    máximo — menos no d20, fixado em 15 para acertar sem virar crítico (o
    crítico dobra os dados e embaralharia a contagem).
    """
    chamadas: list[tuple[int, int]] = []

    def fake_randint(a, b):
        chamadas.append((a, b))
        return 15 if (a, b) == (1, 20) else b

    monkeypatch.setattr(T.random, "randint", fake_randint)
    return chamadas


def test_monstro_rola_o_dado_do_stat_block_e_nao_1d6(campanha, dados_registrados):
    """
    A regressão central: o urso-coruja ataca com as garras (2d8) e o motor
    precisa rolar DOIS d8 — nunca o 1d6 genérico do fallback.
    """
    T.attack_roll("Urso-Coruja", "Heroína", "claws", damage_dice_sides=6,
                  damage_dice_count=1, end_turn=False, _skip_turn_check=True)

    dados_de_dano = [c for c in dados_registrados if c != (1, 20)]
    assert dados_de_dano == [(1, 8), (1, 8)], "esperado 2d8 do stat block"
    assert (1, 6) not in dados_registrados, "caiu no fallback genérico de 1d6"


def test_dano_do_bico_usa_1d10(campanha, dados_registrados):
    T.attack_roll("Urso-Coruja", "Heroína", "beak", damage_dice_sides=6,
                  damage_dice_count=1, end_turn=False, _skip_turn_check=True)
    dados_de_dano = [c for c in dados_registrados if c != (1, 20)]
    assert dados_de_dano == [(1, 10)]


def test_arma_do_srd_continua_pelo_caminho_antigo(campanha, monkeypatch):
    """
    Personagem com arma real do SRD não passa pela tabela de monstro: segue
    consultando /weapons/. Aqui o Open5e está offline, então o motor mantém
    os dados que recebeu — o importante é não quebrar esse caminho.
    """
    chamou = {"srd": False}

    def fake_fetch(nome):
        chamou["srd"] = True
        return None

    monkeypatch.setattr(T, "_fetch_weapon_data", fake_fetch)
    T.attack_roll("Heroína", "Urso-Coruja", "espada longa", damage_dice_sides=8,
                  end_turn=False, _skip_turn_check=True)
    assert chamou["srd"], "arma do SRD deveria consultar _fetch_weapon_data"


# ---------------------------------------------------------------------------
# Integração: Ataque Múltiplo
# ---------------------------------------------------------------------------

def _inicia_combate(ordem, indice=0):
    cs = memory.campaign["combat_state"]
    cs.update({
        "is_active": True, "initiative_order": list(ordem),
        "current_turn_index": indice, "round": 1, "turn_resolved": False,
        "turn_auto_advanced": False,
    })
    return cs


def test_multiattack_executa_dois_golpes_e_avança_o_turno_uma_vez(campanha):
    cs = _inicia_combate(["Urso-Coruja", "Heroína"])
    token_antes = cs["turn_token"]

    random.seed(7)
    saida = T.execute_npc_turn()

    assert saida.count("ataca") == 2, f"esperados 2 ataques:\n{saida}"
    assert "Ataque Múltiplo (2 ataques)" in saida
    # O turno avança UMA vez, no último golpe — não uma vez por golpe.
    assert cs["turn_token"] == token_antes + 1
    assert cs["initiative_order"][cs["current_turn_index"]] == "Heroína"


def test_multiattack_alterna_entre_os_ataques_do_stat_block(campanha):
    """
    "one with its beak and one with its claws": repetir o bico duas vezes
    erraria o dado (1d10 no lugar de 2d8) e a narrativa.
    """
    _inicia_combate(["Urso-Coruja", "Heroína"])
    random.seed(13)
    saida = T.execute_npc_turn()

    assert "com beak" in saida
    assert "com claws" in saida


def test_golpes_intermediarios_nao_anunciam_acao_bonus(campanha):
    """
    attack_roll(end_turn=False) avisa "ação bônus disponível". No meio de um
    Ataque Múltiplo isso é mentira — o turno não avançou porque faltam golpes.
    """
    _inicia_combate(["Urso-Coruja", "Heroína"])
    random.seed(11)
    saida = T.execute_npc_turn()
    assert "Ação bônus disponível" not in saida


def test_monstro_sem_multiattack_da_um_golpe_so(campanha):
    memory.campaign["characters"]["urso-coruja"]["sheet"]["multiattack"] = 1
    cs = _inicia_combate(["Urso-Coruja", "Heroína"])
    token_antes = cs["turn_token"]

    random.seed(3)
    saida = T.execute_npc_turn()

    assert saida.count("ataca") == 1
    assert "Ataque Múltiplo" not in saida
    assert cs["turn_token"] == token_antes + 1


def test_turno_avança_mesmo_se_o_ultimo_alvo_cair_no_primeiro_golpe(campanha):
    """
    Se o alvo cai no golpe 1 de 2 e não sobra ninguém de pé, a investida é
    interrompida — mas o turno PRECISA avançar, ou o combate trava.
    """
    heroina = memory.campaign["characters"]["heroína"]["sheet"]
    heroina["vida_atual"] = 1
    heroina["ca"] = 1                      # garante o acerto no primeiro golpe

    cs = _inicia_combate(["Urso-Coruja", "Heroína"])
    token_antes = cs["turn_token"]

    random.seed(5)
    saida = T.execute_npc_turn()

    assert heroina["vida_atual"] == 0
    assert cs["turn_token"] == token_antes + 1, f"turno não avançou:\n{saida}"
