"""
test_combate_alcance_na_tela.py

Dois defeitos do combate com zonas, vistos na tela tática:

1. O inimigo corpo-a-corpo que começa longe travava a luta. set_battlefield
   põe o grupo na primeira zona e os inimigos na última; execute_npc_turn
   escolhia o alvo e chamava attack_roll direto, o motor recusava por
   alcance ("Erro: FORA DE ALCANCE") e o turno não avançava. A tela chamava
   de novo, 80 vezes, e parava em "Turno do Inimigo" para sempre.

2. O jogador perdia a Ação num ataque que nem aconteceu. combat_action
   marcava a Ação como gasta ANTES de attack_roll, e a recusa de alcance
   voltava com ok=True: nenhum aviso, a Ação queimada, e só restava
   encerrar o turno. A tela também oferecia como alvo quem estava fora do
   alcance da arma escolhida.
"""
import random

import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _campo(povoar, ordem, *, arma_inimigo="espada curta", ataques=None):
    extras = {"ataques": ataques} if ataques else {}
    povoar(
        criar_ficha("Alden",  grupo=True,  vida=30, ca=14, arma="espada longa"),
        criar_ficha("Lyra",   grupo=True,  vida=20, ca=14, arma="arco longo"),
        criar_ficha("Espreitador", grupo=False, vida=25, ca=12, arma=arma_inimigo, **extras),
    )
    iniciar_combate(ordem)
    td.set_battlefield("Franja, Centro, Paredão")
    memory.campaign["combat_state"]["turn_economy"] = {
        "acao_usada": False, "bonus_usada": False, "movimento_usado": False}


def _vez():
    return td._combat_current_actor()


# ---------------------------------------------------------------------------
# 1. O inimigo que começa longe
# ---------------------------------------------------------------------------

def test_inimigo_a_duas_zonas_dispara_ate_o_grupo_e_passa_a_vez(povoar):
    _campo(povoar, ["Espreitador", "Alden", "Lyra"])
    assert td._distancia("Espreitador", "Alden") == 2

    r = td.combat_action("enemy")

    assert "FORA DE ALCANCE" not in r["message"], r["message"]
    assert td._zona_de("Espreitador") == "Franja", r["message"]
    assert _vez() != "Espreitador", "o turno do inimigo não avançou"


def test_inimigo_a_uma_zona_avanca_e_ataca_no_mesmo_turno(povoar):
    _campo(povoar, ["Espreitador", "Alden", "Lyra"])
    td._por_zona("Espreitador", "Centro")
    random.seed(3)

    r = td.combat_action("enemy")

    assert td._zona_de("Espreitador") == "Franja", r["message"]
    log = [e.get("type") for e in memory.campaign["combat_state"].get("log", [])]
    assert "attack" in log or "Espreitador" in r["message"] and "d20" in r["message"], r["message"]
    assert _vez() != "Espreitador"


def test_inimigo_na_mesma_zona_ataca_sem_se_mover(povoar):
    _campo(povoar, ["Espreitador", "Alden", "Lyra"])
    td._por_zona("Espreitador", "Franja")

    r = td.combat_action("enemy")

    assert "move-se" not in r["message"] and "dispara de" not in r["message"]
    assert _vez() != "Espreitador"


def test_inimigo_com_ataque_a_distancia_atira_de_longe(povoar):
    _campo(povoar, ["Espreitador", "Alden", "Lyra"], arma_inimigo="arco curto")

    r = td.combat_action("enemy")

    assert td._zona_de("Espreitador") == "Paredão", "atirador não precisava sair do lugar"
    assert "FORA DE ALCANCE" not in r["message"]
    assert _vez() != "Espreitador"


def test_turno_do_inimigo_nunca_fica_preso_numa_recusa(povoar, monkeypatch):
    """Qualquer recusa que sobre (alvo inalcançável por outro motivo) passa a vez."""
    _campo(povoar, ["Espreitador", "Alden", "Lyra"])
    td._por_zona("Espreitador", "Franja")
    monkeypatch.setattr(td, "attack_roll",
                        lambda *a, **k: "Erro: FORA DE ALCANCE: simulado.")

    td.combat_action("enemy")

    assert _vez() != "Espreitador"


# ---------------------------------------------------------------------------
# 2. O jogador não perde a Ação numa recusa
# ---------------------------------------------------------------------------

def test_espada_contra_inimigo_em_outra_zona_nao_gasta_a_acao(povoar):
    _campo(povoar, ["Alden", "Lyra", "Espreitador"])

    r = td.combat_action("attack", actor="Alden", target="Espreitador",
                         weapon="espada longa")

    assert r["ok"] is False, "a recusa voltou como sucesso e a tela não avisou"
    assert "fora de alcance" in r["message"].lower()
    assert "Ação não foi gasta" in r["message"]
    eco = memory.campaign["combat_state"]["turn_economy"]
    assert eco["acao_usada"] is False, "a Ação foi gasta num ataque que não aconteceu"
    assert _vez() == "Alden"


def test_depois_da_recusa_ainda_da_para_atirar(povoar):
    _campo(povoar, ["Lyra", "Alden", "Espreitador"])
    td.combat_action("attack", actor="Lyra", target="Espreitador", weapon="espada longa")

    r = td.combat_action("attack", actor="Lyra", target="Espreitador", weapon="arco longo")

    assert r["ok"] is True, r["message"]
    assert "FORA DE ALCANCE" not in r["message"]


def test_snapshot_diz_o_alcance_de_cada_arma_para_cada_alvo(povoar):
    _campo(povoar, ["Alden", "Lyra", "Espreitador"])

    alcance = td.combat_snapshot()["alcance"]

    assert alcance["espada longa"]["Espreitador"] == "fora"
    assert alcance["Ataque desarmado"]["Espreitador"] == "fora"


def test_snapshot_marca_desvantagem_do_tiro_longo(povoar):
    _campo(povoar, ["Lyra", "Alden", "Espreitador"])
    ch = memory.campaign["characters"]["lyra"]

    alcance = td.combat_snapshot()["alcance"]

    assert alcance["arco longo"]["Espreitador"] == "desvantagem"
    assert ch["sheet"]["equipamentos"]["arma_principal"] == "arco longo"


def test_snapshot_sem_zonas_nao_traz_alcance(povoar):
    povoar(criar_ficha("Alden", grupo=True), criar_ficha("Goblin"))
    iniciar_combate(["Alden", "Goblin"])

    assert td.combat_snapshot()["alcance"] == {}
