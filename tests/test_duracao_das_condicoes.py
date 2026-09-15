"""
test_duracao_das_condicoes.py

apply_condition(..., duration_turns=N) gravava {"duracao": N} e nada contava:
"Envenenado (2 turnos)" ficava para sempre no card, na ficha e na régua.

Regra: a duração é em turnos do PRÓPRIO afetado e desconta no fim de cada
turno dele. Aplicada na vez do próprio afetado, aquele turno não conta. Com o
combate, as condições com duração acabam; as indefinidas ficam.
"""
import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


@pytest.fixture
def luta(povoar):
    povoar(criar_ficha("Alden", grupo=True), criar_ficha("Lyra", grupo=True),
           criar_ficha("Goblin", vida=40))
    iniciar_combate(["Alden", "Goblin", "Lyra"])
    cs = memory.campaign["combat_state"]
    cs["turn_token"] = 1
    return cs


def _conds(quem):
    return {c["nome"]: c.get("duracao")
            for c in memory.campaign["characters"][quem]["sheet"]["condicoes"]}


def _vez():
    return td._combat_current_actor()


def test_desconta_no_fim_do_turno_do_afetado_e_acaba(luta):
    td.apply_condition("Goblin", "envenenado", 2)       # na vez do Alden
    td.next_turn()                                       # fim do Alden: não mexe no Goblin
    assert _vez() == "Goblin" and _conds("goblin") == {"Envenenado": 2}
    td.next_turn()                                       # fim do Goblin
    assert _conds("goblin") == {"Envenenado": 1}
    td.next_turn(); td.next_turn()                       # Lyra, Alden
    assert _conds("goblin") == {"Envenenado": 1}
    saida = td.next_turn()                               # fim do Goblin de novo
    assert _conds("goblin") == {}
    assert "Envenenado de Goblin acabou" in saida
    assert any(e.get("type") == "condition_end" for e in luta["log"])


def test_aplicada_na_propria_vez_nao_conta_aquele_turno(luta):
    assert _vez() == "Alden"
    td.apply_condition("Alden", "amedrontado", 1)
    td.next_turn()                                       # fim do turno em que foi aplicada
    assert _conds("alden") == {"Amedrontado": 1}, "sumiu antes de o Alden jogar um turno com ela"
    td.next_turn(); td.next_turn()                       # Goblin, Lyra
    td.next_turn()                                       # fim do próximo turno do Alden
    assert _conds("alden") == {}


def test_indefinida_nao_desconta(luta):
    td.apply_condition("Goblin", "cego")
    for _ in range(6):
        td.next_turn()
    assert _conds("goblin") == {"Cego": None}


def test_tela_tatica_desconta_ao_encerrar_o_turno(luta):
    luta["turn_economy"] = {"acao_usada": False, "bonus_usada": False, "movimento_usado": False}
    luta["current_turn_index"] = 1                       # vez do Goblin
    td.apply_condition("Alden", "envenenado", 1)
    luta["current_turn_index"] = 0                       # vez do Alden
    luta["turn_token"] += 1
    r = td.combat_action("end_turn", actor="Alden")
    assert r["ok"] is True
    assert _conds("alden") == {}, r["message"]
    assert "Envenenado de Alden acabou" in r["message"]


def test_quem_esta_fora_de_combate_nao_desconta(luta):
    lyra = memory.campaign["characters"]["lyra"]
    td.apply_condition("Lyra", "envenenado", 1)
    lyra["status"] = "inconsciente"
    for _ in range(5):
        td.next_turn()
    assert _conds("lyra") == {"Envenenado": 1}


def test_fim_do_combate_leva_as_com_duracao_e_deixa_as_indefinidas(luta):
    td.apply_condition("Goblin", "envenenado", 3)
    td.apply_condition("Goblin", "cego")
    td.end_combat()
    assert _conds("goblin") == {"Cego": None}


def test_telas_mostram_os_turnos_restantes(luta):
    td.apply_condition("Goblin", "envenenado", 2)
    goblin = next(c for c in td.combat_snapshot()["combatants"] if c["name"] == "Goblin")
    assert goblin["condicoes_turnos"] == {"Envenenado": 2}
    assert "Envenenado (2 turnos)" in td.get_combat_status()
    td.next_turn(); td.next_turn()
    assert "Envenenado (1 turno)" in td.get_combat_status()


def test_turnos_do_afetado_no_texto_da_ferramenta(luta):
    assert "por 2 turno(s) de Goblin" in td.apply_condition("Goblin", "envenenado", 2)


def test_descanso_longo_nao_cura_doenca_nem_maldicao(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True))
    s = memory.campaign["characters"]["aria"]["sheet"]
    s["condicoes"] = [{"nome": "Doença", "duracao": None},
                      {"nome": "Maldição", "duracao": 5},
                      {"nome": "Envenenado", "duracao": 3},
                      {"nome": "Cego", "duracao": None}]
    td.long_rest("Aria")
    nomes = [c["nome"] for c in s["condicoes"]]
    assert "Doença" in nomes and "Maldição" in nomes, "o descanso curou doença e maldição"
    assert "Envenenado" not in nomes
    assert "Cego" in nomes
