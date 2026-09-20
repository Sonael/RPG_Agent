"""
test_combate_aliado.py
O terceiro lado do combate: o aliado.

O combate tinha dois lados — quem estava no grupo do jogador e todo o resto.
Escoltar um mercador virava luta contra ele: o NPC entrava na iniciativa, caía
na zona dos inimigos e o motor o mandava atacar o grupo. Com os inimigos todos
no chão, a luta nem terminava, porque o aliado contava como inimigo vivo.

Agora existe o lado "aliado" (memory.lado_no_combate). Quem luta com o grupo
sem ser dele é declarado — roll_initiative(allies="Pip") — ou marcado depois
com set_combat_side, que também vira a traição no meio da luta. Sem
declaração o lado é o inimigo, o de antes: na ficha, o mercador escoltado e a
rival que veio duelar são idênticos, e chutar "aliado" deixaria todo duelo
sem inimigo.

O aliado luta ao lado do grupo mas NÃO é do grupo: sem XP, sem nível, sem
saque, e quem joga por ele é o motor.
"""
import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _npc_da_historia(nome, **kw):
    """NPC que a campanha já conhecia: sem party_member e sem status inimigo."""
    ch = criar_ficha(nome, grupo=False, **kw)
    ch["status"] = "vivo"
    ch["party_member"] = False
    return ch


def _escolta(povoar, *, zonas=None):
    """Aria escolta Pip; dois goblins atacam."""
    chars = povoar(
        criar_ficha("Aria",     grupo=True,  vida=30, ca=14),
        _npc_da_historia("Pip",              vida=12, ca=12),
        criar_ficha("Goblin 1", grupo=False, vida=7,  ca=15),
        criar_ficha("Goblin 2", grupo=False, vida=7,  ca=15),
    )
    # Pela porta de entrada de verdade: o mestre declara quem luta com o grupo,
    # e roll_initiative congela o lado de cada um (depois o status do inimigo
    # vira "morto" e a pista se perderia).
    td.roll_initiative("Aria, Pip, Goblin 1, Goblin 2", allies="Pip")
    iniciar_combate(["Aria", "Pip", "Goblin 1", "Goblin 2"])
    if zonas:
        td.set_battlefield(zonas)
    return chars


# ---------------------------------------------------------------------------
# 1. A dedução
# ---------------------------------------------------------------------------

def test_o_grupo_o_inimigo_e_o_npc_da_historia(povoar):
    chars = _escolta(povoar)
    assert memory.lado_no_combate(chars["Aria"]) == "grupo"
    assert memory.lado_no_combate(chars["Goblin 1"]) == "inimigo"
    assert memory.lado_no_combate(chars["Pip"]) == "aliado"
    assert memory.luta_com_o_grupo(chars["Pip"]) is True


def test_npc_nao_declarado_entra_como_inimigo(povoar):
    """A rival que vem duelar e o mercador escoltado são iguais na ficha: sem
    declaração, o motor fica com o lado seguro — o de antes."""
    rival = _npc_da_historia("Victoria", vida=20, ca=16)
    chars = povoar(criar_ficha("Aria", grupo=True), rival)
    saida = td.roll_initiative("Aria, Victoria")
    assert memory.lado_no_combate(chars["Victoria"]) == "inimigo"
    # E a resposta diz de que lado cada um entrou, com como corrigir.
    assert "grupo: Aria" in saida and "contra: Victoria" in saida, saida
    assert "set_combat_side" in saida, saida


def test_npc_de_quem_a_campanha_gosta_entra_como_aliado(povoar):
    amigo = _npc_da_historia("Pip", vida=12, ca=12)
    amigo["atitude"] = 60
    chars = povoar(criar_ficha("Aria", grupo=True), amigo)
    saida = td.roll_initiative("Aria, Pip")
    assert memory.lado_no_combate(chars["Pip"]) == "aliado"
    assert "aliados: Pip" in saida, saida


def test_npc_hostil_ao_grupo_entra_como_inimigo(povoar):
    hostil = _npc_da_historia("Bandido Raso", vida=12, ca=12)
    hostil["atitude"] = -60
    chars = povoar(criar_ficha("Aria", grupo=True), hostil)
    td.roll_initiative("Aria, Bandido Raso")
    assert memory.lado_no_combate(chars["Bandido Raso"]) == "inimigo"


def test_a_marca_do_mestre_vence_a_deducao(povoar):
    chars = _escolta(povoar)
    chars["Goblin 1"]["lado"] = "aliado"
    chars["Pip"]["lado"] = "inimigo"
    assert memory.lado_no_combate(chars["Goblin 1"]) == "aliado"
    assert memory.lado_no_combate(chars["Pip"]) == "inimigo"


def test_nome_novo_na_luta_e_inimigo(campanha):
    iniciar_combate([])
    char, criado = td._combatente_para_a_luta("Coisa Sem Nome")
    assert criado and memory.lado_no_combate(char) == "inimigo"


# ---------------------------------------------------------------------------
# 2. O campo de batalha
# ---------------------------------------------------------------------------

def test_o_aliado_fica_na_zona_do_grupo(povoar):
    _escolta(povoar, zonas="Trilha, Mata")
    assert td._zona_de("Pip") == "Trilha"
    assert td._zona_de("Aria") == "Trilha"
    assert td._zona_de("Goblin 1") == "Mata"
    campo = td.describe_battlefield()
    assert "[aliado] Pip" in campo
    assert "[grupo] Aria" in campo
    assert "[inimigo] Goblin 1" in campo


def test_o_aliado_nao_tranca_o_grupo_e_o_inimigo_tranca(povoar):
    _escolta(povoar, zonas="Trilha, Mata")
    assert td._inimigos_na_zona("Aria") == []          # Pip está do lado dela
    td.move_combatant("Goblin 1", "Trilha")
    assert td._inimigos_na_zona("Aria") == ["Goblin 1"]
    assert td._inimigos_na_zona("Pip") == ["Goblin 1"]


# ---------------------------------------------------------------------------
# 3. O turno do aliado
# ---------------------------------------------------------------------------

def test_o_aliado_ataca_o_inimigo_e_nao_o_grupo(povoar, monkeypatch):
    _escolta(povoar)
    memory.campaign["combat_state"]["current_turn_index"] = 1   # vez do Pip
    monkeypatch.setattr(td.random, "randint", lambda a, b: b)   # sempre acerta
    saida = td.execute_npc_turn()
    # O alvo é um goblin, nunca quem ele escolta.
    assert "Pip ataca Goblin" in saida, saida
    assert "Pip ataca Aria" not in saida, saida


def test_o_inimigo_ataca_o_aliado_tambem(povoar, monkeypatch):
    _escolta(povoar)
    memory.campaign["combat_state"]["current_turn_index"] = 2   # vez do goblin
    monkeypatch.setattr(td.random, "randint", lambda a, b: b)
    saida = td.execute_npc_turn()
    assert ("Goblin 1 ataca Aria" in saida) or ("Goblin 1 ataca Pip" in saida), saida


# ---------------------------------------------------------------------------
# 4. O fim da luta
# ---------------------------------------------------------------------------

def test_com_os_inimigos_no_chao_a_luta_acaba_mesmo_com_o_aliado_de_pe(povoar):
    chars = _escolta(povoar)
    for nome in ("Goblin 1", "Goblin 2"):
        chars[nome]["status"] = "morto"
        chars[nome]["sheet"]["vida_atual"] = 0
    memory.campaign["combat_state"]["current_turn_index"] = 0
    r = td.combat_action("pass", actor="Aria")
    resultado = (r.get("snapshot") or {}).get("result") or {}
    assert resultado.get("outcome") == "vitoria", r.get("message")
    lados = {c["name"]: c.get("lado") for c in resultado.get("sobreviventes", [])}
    assert lados.get("Pip") == "aliado", resultado


def test_aliado_caido_nao_vale_xp_de_inimigo_derrotado(povoar):
    chars = _escolta(povoar)
    chars["Pip"]["status"] = "morto"
    assert td._derrotados_citados("o grupo derrotou Pip") == []


# ---------------------------------------------------------------------------
# 5. A marca do mestre
# ---------------------------------------------------------------------------

def test_set_combat_side_vira_a_traicao_e_muda_de_zona(povoar):
    chars = _escolta(povoar, zonas="Trilha, Mata")
    saida = td.set_combat_side("Pip", "inimigo")
    assert "inimigo" in saida
    assert memory.lado_no_combate(chars["Pip"]) == "inimigo"
    assert td._zona_de("Pip") == "Mata"
    assert "[inimigo] Pip" in td.describe_battlefield()


def test_set_combat_side_traz_o_inimigo_rendido_para_o_seu_lado(povoar):
    chars = _escolta(povoar, zonas="Trilha, Mata")
    td.set_combat_side("Goblin 2", "aliado")
    assert memory.lado_no_combate(chars["Goblin 2"]) == "aliado"
    assert chars["Goblin 2"]["status"] == "vivo"
    assert td._zona_de("Goblin 2") == "Trilha"


@pytest.mark.parametrize("lado", ["companheiro", "", "NPC"])
def test_set_combat_side_recusa_lado_invalido(povoar, lado):
    _escolta(povoar)
    assert td.set_combat_side("Pip", lado).startswith("Erro:")


def test_grupo_e_so_para_quem_esta_no_grupo(povoar):
    chars = _escolta(povoar)
    saida = td.set_combat_side("Pip", "grupo")
    assert saida.startswith("Erro:") and "recruit_character" in saida
    assert memory.lado_no_combate(chars["Pip"]) == "aliado"


# ---------------------------------------------------------------------------
# 6. O que a tela recebe
# ---------------------------------------------------------------------------

def test_a_tela_recebe_o_lado_de_cada_um(povoar):
    _escolta(povoar)
    snap = td.combat_snapshot()
    lados = {c["name"]: c["lado"] for c in snap["combatants"]}
    assert lados == {"Aria": "grupo", "Pip": "aliado",
                     "Goblin 1": "inimigo", "Goblin 2": "inimigo"}
    # O aliado não é do grupo: o jogador não joga por ele.
    do_grupo = {c["name"]: c["is_party"] for c in snap["combatants"]}
    assert do_grupo["Pip"] is False and do_grupo["Aria"] is True


def test_o_inimigo_derrotado_continua_inimigo(povoar):
    chars = _escolta(povoar)
    chars["Goblin 1"]["status"] = "morto"        # o status deixa de dizer o lado
    chars["Goblin 1"]["sheet"]["vida_atual"] = 0
    assert memory.lado_no_combate(chars["Goblin 1"]) == "inimigo"


def test_o_aliado_so_mira_em_quem_esta_na_luta(povoar, monkeypatch):
    """A lista de alvos varria a campanha inteira: o aliado chegou a atacar
    um NPC que nem estava no combate."""
    chars = _escolta(povoar)
    de_fora = _npc_da_historia("Elowen", vida=20, ca=18)
    memory.campaign["characters"][memory.char_key("Elowen")] = de_fora
    memory.campaign["combat_state"]["current_turn_index"] = 1   # vez do Pip
    monkeypatch.setattr(td.random, "randint", lambda a, b: b)
    saida = td.execute_npc_turn()
    assert "Elowen" not in saida, saida
    assert "Pip ataca Goblin" in saida, saida


def test_o_lado_fica_congelado_ao_entrar_na_luta(povoar):
    """A atitude muda durante a luta (o aliado leva um golpe do grupo, o mestre
    registra a mágoa). O lado de quem já está lutando não muda por isso."""
    amigo = _npc_da_historia("Pip", vida=12, ca=12)
    amigo["atitude"] = 60
    chars = povoar(criar_ficha("Aria", grupo=True), amigo,
                   criar_ficha("Goblin 1", grupo=False, vida=7, ca=15))
    td.roll_initiative("Aria, Pip, Goblin 1")
    assert memory.lado_no_combate(chars["Pip"]) == "aliado"
    chars["Pip"]["atitude"] = -80
    assert memory.lado_no_combate(chars["Pip"]) == "aliado"
    # Trocar de lado no meio da luta é decisão do mestre, não da atitude.
    td.set_combat_side("Pip", "inimigo")
    assert memory.lado_no_combate(chars["Pip"]) == "inimigo"


def test_quem_e_do_grupo_nao_carrega_lado_gravado(povoar):
    """Entrar e sair do grupo é decisão do jogo. Se o lado do herói ficasse
    gravado na primeira luta, quem saísse do grupo continuaria contando como
    grupo para sempre."""
    chars = povoar(criar_ficha("Aria", grupo=True),
                   criar_ficha("Goblin 1", grupo=False, vida=7, ca=15))
    td.roll_initiative("Aria, Goblin 1")
    assert "lado" not in chars["Aria"]
    assert memory.lado_no_combate(chars["Aria"]) == "grupo"
