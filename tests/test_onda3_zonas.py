"""
test_onda3_zonas.py
Onda 3 — profundidade tática: zonas, repertório de NPC e ações lendárias.

TUDO É OPCIONAL POR DESIGN. Sem set_battlefield() chamado, o combate se
comporta exatamente como na onda 2 — campanhas em andamento não mudam de regra
no meio do caminho. O primeiro teste da suíte é justamente essa garantia.
"""
import random

import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _montar(povoar, *, zonas=None):
    """Grupo (Aria, Bran) contra inimigos (Goblin, Arqueiro), combate ligado."""
    chars = povoar(
        criar_ficha("Aria",     grupo=True,  vida=30, ca=14),
        criar_ficha("Bran",     grupo=True,  vida=30, ca=14),
        criar_ficha("Goblin",   grupo=False, vida=20, ca=12),
        criar_ficha("Arqueiro", grupo=False, vida=20, ca=12, arma="arco curto"),
    )
    iniciar_combate(["Aria", "Bran", "Goblin", "Arqueiro"])
    if zonas:
        td.set_battlefield(zonas)
    return chars


# ---------------------------------------------------------------------------
# 1. Sem zonas, nada muda
# ---------------------------------------------------------------------------

def test_sem_zonas_o_alcance_nao_existe(povoar):
    _montar(povoar)                       # nenhuma zona definida

    assert td._distancia("Aria", "Goblin") is None
    assert td._checar_alcance("Aria", "Goblin", "espada longa") == ("", False)
    assert td._inimigos_na_zona("Aria") == []

    # E o ataque acontece normalmente, sem recusa de alcance.
    saida = td.attack_roll("Aria", "Goblin", "espada longa", 8, _skip_turn_check=True)
    assert "FORA DE ALCANCE" not in saida


def test_mover_sem_campo_definido_avisa(povoar):
    _montar(povoar)
    assert "set_battlefield" in td.move_combatant("Aria", "Pátio")


# ---------------------------------------------------------------------------
# 2. Montagem do campo
# ---------------------------------------------------------------------------

def test_grupo_na_frente_inimigos_no_fundo(povoar):
    _montar(povoar, zonas="Portão, Pátio, Sacada")

    assert td._zona_de("Aria")     == "Portão"
    assert td._zona_de("Bran")     == "Portão"
    assert td._zona_de("Goblin")   == "Sacada"
    assert td._zona_de("Arqueiro") == "Sacada"
    assert td._distancia("Aria", "Goblin") == 2


def test_campo_exige_pelo_menos_duas_zonas(povoar):
    _montar(povoar)
    assert "DUAS zonas" in td.set_battlefield("Pátio")


def test_campo_recusa_zonas_repetidas(povoar):
    _montar(povoar)
    assert "mesmo nome" in td.set_battlefield("Pátio, pátio")


def test_descricao_do_campo_mostra_quem_esta_onde(povoar):
    _montar(povoar, zonas="Portão, Pátio, Sacada")
    texto = td.describe_battlefield()

    assert "Portão" in texto and "Aria" in texto
    assert "Sacada" in texto and "Goblin" in texto
    assert "Pátio" in texto and "vazia" in texto


# ---------------------------------------------------------------------------
# 3. Alcance
# ---------------------------------------------------------------------------

def test_corpo_a_corpo_entre_zonas_e_recusado(povoar):
    _montar(povoar, zonas="Portão, Sacada")

    saida = td.attack_roll("Aria", "Goblin", "espada longa", 8, _skip_turn_check=True)
    assert "FORA DE ALCANCE" in saida
    assert "move_combatant" in saida
    # Recusa ANTES de qualquer dado: o goblin não perdeu PV.
    assert memory.campaign["characters"]["goblin"]["sheet"]["vida_atual"] == 20


def test_corpo_a_corpo_na_mesma_zona_passa(povoar):
    _montar(povoar, zonas="Portão, Sacada")
    td._por_zona("Goblin", "Portão")

    assert td._checar_alcance("Aria", "Goblin", "espada longa") == ("", False)


def test_tiro_de_duas_zonas_sai_com_desvantagem(povoar):
    _montar(povoar, zonas="Portão, Pátio, Sacada")

    recusa, desvantagem = td._checar_alcance("Arqueiro", "Aria", "arco curto")
    assert recusa == ""
    assert desvantagem is True


def test_tiro_de_uma_zona_e_limpo(povoar):
    _montar(povoar, zonas="Portão, Sacada")

    recusa, desvantagem = td._checar_alcance("Arqueiro", "Aria", "arco curto")
    assert (recusa, desvantagem) == ("", False)


def test_atirar_com_inimigo_colado_da_desvantagem(povoar):
    _montar(povoar, zonas="Portão, Sacada")
    td._por_zona("Arqueiro", "Portão")     # trancado junto com Aria e Bran

    recusa, desvantagem = td._checar_alcance("Arqueiro", "Aria", "arco curto")
    assert recusa == ""
    assert desvantagem is True


def test_quem_nao_foi_posicionado_nao_sofre_regra_de_alcance(povoar):
    """
    Distância desconhecida não pode virar penalidade inventada — o motor
    devolve None e o ataque corre como antes.
    """
    _montar(povoar, zonas="Portão, Sacada")
    memory.campaign["combat_state"]["posicoes"].pop("goblin")

    assert td._distancia("Aria", "Goblin") is None
    assert td._checar_alcance("Aria", "Goblin", "espada longa") == ("", False)


# ---------------------------------------------------------------------------
# 4. Movimento
# ---------------------------------------------------------------------------

def test_move_uma_zona(povoar):
    _montar(povoar, zonas="Portão, Pátio, Sacada")

    saida = td.move_combatant("Aria", "Pátio")
    assert "Pátio" in saida
    assert td._zona_de("Aria") == "Pátio"


def test_duas_zonas_exigem_disparada(povoar):
    _montar(povoar, zonas="Portão, Pátio, Sacada")

    saida = td.move_combatant("Aria", "Sacada")
    assert "2 zonas" in saida and "dash=True" in saida
    assert td._zona_de("Aria") == "Portão"          # não se moveu

    assert "Sacada" in td.move_combatant("Aria", "Sacada", dash=True)
    assert td._zona_de("Aria") == "Sacada"


def test_zona_inexistente_lista_as_validas(povoar):
    _montar(povoar, zonas="Portão, Sacada")
    saida = td.move_combatant("Aria", "Cozinha")
    assert "não existe" in saida and "Portão" in saida


def test_sair_de_zona_com_inimigo_provoca_oportunidade(povoar):
    _montar(povoar, zonas="Portão, Pátio, Sacada")
    td._por_zona("Goblin", "Portão")        # trancado com Aria
    random.seed(7)

    saida = td.move_combatant("Aria", "Pátio")

    assert "oportunidade" in saida.lower()
    assert td._zona_de("Aria") == "Pátio"


def test_sair_de_zona_livre_nao_provoca(povoar):
    _montar(povoar, zonas="Portão, Pátio, Sacada")   # inimigos na Sacada

    saida = td.move_combatant("Aria", "Pátio")
    assert "oportunidade" not in saida.lower()


def test_so_reage_quem_esta_na_mesma_zona(povoar):
    """
    O arqueiro do outro lado do pátio não pode dar bote em quem nunca esteve
    ao alcance dele.
    """
    chars = _montar(povoar, zonas="Portão, Pátio, Sacada")
    td._por_zona("Goblin", "Portão")        # este reage
    td._por_zona("Arqueiro", "Sacada")      # este não
    random.seed(3)

    td.move_combatant("Aria", "Pátio")

    # Quem reagiu gastou a reação da rodada — é o registro que não mente.
    # (O log usa attack_hit/attack_miss/attack_crit, nunca "attack": olhar o
    # tipo exato deixaria a asserção sempre verdadeira.)
    assert td._reaction_available(chars["Goblin"])   is False
    assert td._reaction_available(chars["Arqueiro"]) is True


# ---------------------------------------------------------------------------
# 5. Recarga
# ---------------------------------------------------------------------------

def test_recarga_e_registrada_na_ficha(povoar):
    _montar(povoar)
    saida = td.set_recharge_ability("Goblin", "Sopro de Fogo", 5)

    assert "recarga 5–6" in saida
    cfg = memory.campaign["characters"]["goblin"]["sheet"]["recargas"]["Sopro de Fogo"]
    assert cfg == {"min": 5, "pronto": True}


def test_poder_gasto_fica_indisponivel_ate_recarregar(povoar):
    chars = _montar(povoar)
    td.set_recharge_ability("Goblin", "Sopro de Fogo", 5)
    goblin = chars["Goblin"]

    td._gastar_recarga(goblin, "Sopro de Fogo")
    assert td._recarga_pronta(goblin, "Sopro de Fogo") is False

    # d6 baixo: continua descarregado.
    random.seed(1)
    goblin["sheet"]["recargas"]["Sopro de Fogo"]["min"] = 6
    for _ in range(3):
        td._rolar_recargas(goblin)
        if td._recarga_pronta(goblin, "Sopro de Fogo"):
            break

    # Com mínimo 2, recarrega na primeira rolagem possível.
    goblin["sheet"]["recargas"]["Sopro de Fogo"] = {"min": 2, "pronto": False}
    voltaram = td._rolar_recargas(goblin)
    assert td._recarga_pronta(goblin, "Sopro de Fogo") is True
    assert voltaram and "recarregou" in voltaram[0]


def test_poder_sem_recarga_configurada_esta_sempre_pronto(povoar):
    chars = _montar(povoar)
    assert td._recarga_pronta(chars["Goblin"], "Qualquer Coisa") is True


def test_recarga_rola_no_inicio_do_turno(povoar):
    _montar(povoar, zonas=None)
    td.set_recharge_ability("Goblin", "Sopro", 2)
    goblin = memory.campaign["characters"]["goblin"]
    goblin["sheet"]["recargas"]["Sopro"]["pronto"] = False

    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index("Goblin")
    random.seed(5)
    td._reset_turn_economy(cs)

    assert goblin["sheet"]["recargas"]["Sopro"]["pronto"] is True


# ---------------------------------------------------------------------------
# 6. Ações lendárias
# ---------------------------------------------------------------------------

def test_criatura_vira_lendaria(povoar):
    _montar(povoar)
    saida = td.set_legendary_actions("Goblin", "Ataque de Cauda, Investida Alada:2", count=3)

    assert "LENDÁRIA" in saida
    lend = memory.campaign["characters"]["goblin"]["sheet"]["lendarias"]
    assert lend["total"] == 3 and lend["restantes"] == 3
    assert lend["opcoes"] == [{"nome": "Ataque de Cauda", "custo": 1},
                              {"nome": "Investida Alada", "custo": 2}]


def test_lendaria_nao_age_no_proprio_turno(povoar):
    _montar(povoar)
    td.set_legendary_actions("Goblin", "Ataque de Cauda")
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index("Goblin")

    saida = td.legendary_action("Goblin", "Ataque de Cauda", "Aria")
    assert "É o turno de" in saida
    assert memory.campaign["characters"]["goblin"]["sheet"]["lendarias"]["restantes"] == 3


def test_custo_e_debitado_e_o_limite_respeitado(povoar):
    _montar(povoar)
    td.set_legendary_actions("Goblin", "Investida Alada:2", count=3)
    lend = memory.campaign["characters"]["goblin"]["sheet"]["lendarias"]
    random.seed(11)

    td.legendary_action("Goblin", "Investida Alada", "Aria")     # turno da Aria
    assert lend["restantes"] == 1

    saida = td.legendary_action("Goblin", "Investida Alada", "Aria")
    assert "custa 2" in saida
    assert lend["restantes"] == 1                                # nada foi gasto


def test_opcao_desconhecida_lista_as_validas(povoar):
    _montar(povoar)
    td.set_legendary_actions("Goblin", "Ataque de Cauda")
    saida = td.legendary_action("Goblin", "Bafo Gelado", "Aria")
    assert "não existe" in saida and "Ataque de Cauda" in saida


def test_criatura_comum_nao_tem_acao_lendaria(povoar):
    _montar(povoar)
    assert "não é uma criatura lendária" in td.legendary_action("Goblin", "Qualquer", "Aria")


def test_contador_volta_ao_cheio_no_turno_do_chefe(povoar):
    _montar(povoar)
    td.set_legendary_actions("Goblin", "Ataque de Cauda", count=3)
    lend = memory.campaign["characters"]["goblin"]["sheet"]["lendarias"]
    lend["restantes"] = 0

    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index("Goblin")
    td._reset_turn_economy(cs)

    assert lend["restantes"] == 3


def test_lendaria_caida_nao_age(povoar):
    chars = _montar(povoar)
    td.set_legendary_actions("Goblin", "Ataque de Cauda")
    chars["Goblin"]["sheet"]["vida_atual"] = 0

    assert "caído" in td.legendary_action("Goblin", "Ataque de Cauda", "Aria")


# ---------------------------------------------------------------------------
# 7. Repertório do NPC
# ---------------------------------------------------------------------------

def test_suporte_cura_o_aliado_mais_ferido(povoar):
    """
    A estratégia 'suporte' prometia curar desde sempre e caía no ramo de
    ataque. Agora cumpre.
    """
    povoar(
        criar_ficha("Aria",    grupo=True,  vida=30, ca=14),
        criar_ficha("Clerigo", grupo=False, vida=20, ca=12, mana=20,
                    habilidades=[{"nome": "Curar Ferimentos",
                                  "descricao": "cura", "dado": "1d8",
                                  "custo_mana": 2}]),
        criar_ficha("Bruto",   grupo=False, vida=6, vida_max=40, ca=12),
    )
    iniciar_combate(["Clerigo", "Aria", "Bruto"])
    td.set_npc_strategy("Clerigo", "suporte")
    random.seed(2)

    antes = memory.campaign["characters"]["bruto"]["sheet"]["vida_atual"]
    saida = td.execute_npc_turn()
    depois = memory.campaign["characters"]["bruto"]["sheet"]["vida_atual"]

    assert depois > antes, saida
    assert "Curar Ferimentos" in saida


def test_suporte_ataca_quando_nao_ha_ferido(povoar):
    povoar(
        criar_ficha("Aria",    grupo=True,  vida=30, ca=14),
        criar_ficha("Clerigo", grupo=False, vida=20, ca=12, mana=20,
                    habilidades=[{"nome": "Curar Ferimentos",
                                  "descricao": "cura", "dado": "1d8",
                                  "custo_mana": 2}]),
        criar_ficha("Bruto",   grupo=False, vida=40, vida_max=40, ca=12),
    )
    iniciar_combate(["Clerigo", "Aria", "Bruto"])
    td.set_npc_strategy("Clerigo", "suporte")
    random.seed(4)

    saida = td.execute_npc_turn()
    assert "Curar Ferimentos" not in saida


def test_poder_de_recarga_e_disparado_quando_carregado(povoar):
    povoar(
        criar_ficha("Aria",   grupo=True,  vida=40, ca=14),
        criar_ficha("Dragao", grupo=False, vida=60, ca=15, mana=30,
                    habilidades=[{"nome": "Sopro de Fogo",
                                  "descricao": "baforada", "dado": "4d6",
                                  "custo_mana": 0}]),
    )
    iniciar_combate(["Dragao", "Aria"])
    td.set_recharge_ability("Dragao", "Sopro de Fogo", 5)
    random.seed(9)

    saida = td.execute_npc_turn()

    assert "Sopro de Fogo" in saida
    cfg = memory.campaign["characters"]["dragao"]["sheet"]["recargas"]["Sopro de Fogo"]
    assert cfg["pronto"] is False        # gastou


def test_poder_descarregado_nao_e_usado(povoar):
    povoar(
        criar_ficha("Aria",   grupo=True,  vida=40, ca=14),
        criar_ficha("Dragao", grupo=False, vida=60, ca=15, mana=30,
                    habilidades=[{"nome": "Sopro de Fogo",
                                  "descricao": "baforada", "dado": "4d6",
                                  "custo_mana": 0}]),
    )
    iniciar_combate(["Dragao", "Aria"])
    td.set_recharge_ability("Dragao", "Sopro de Fogo", 5)
    memory.campaign["characters"]["dragao"]["sheet"]["recargas"]["Sopro de Fogo"]["pronto"] = False
    random.seed(9)

    saida = td.execute_npc_turn()
    assert "descarrega" not in saida


def test_atirador_recua_antes_de_atirar(povoar):
    _montar(povoar, zonas="Portão, Pátio, Sacada")
    td._por_zona("Arqueiro", "Portão")       # trancado com Aria e Bran
    td.set_npc_strategy("Arqueiro", "atirador")
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index("Arqueiro")
    random.seed(6)

    saida = td.execute_npc_turn()

    assert td._zona_de("Arqueiro") != "Portão", saida
    assert "Recua para atirar" in saida


def test_atirador_livre_nao_recua(povoar):
    _montar(povoar, zonas="Portão, Pátio, Sacada")
    td.set_npc_strategy("Arqueiro", "atirador")     # já está na Sacada, sozinho
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index("Arqueiro")
    random.seed(6)

    td.execute_npc_turn()
    assert td._zona_de("Arqueiro") == "Sacada"


# ---------------------------------------------------------------------------
# 8. A tela tática recebe o campo
# ---------------------------------------------------------------------------

def test_snapshot_leva_zonas_e_posicoes(povoar):
    _montar(povoar, zonas="Portão, Pátio, Sacada")
    td.set_legendary_actions("Goblin", "Ataque de Cauda", count=2)
    td.set_recharge_ability("Goblin", "Sopro", 5)

    snap = td.combat_snapshot()

    assert snap["zonas"] == ["Portão", "Pátio", "Sacada"]
    por_nome = {c["name"]: c for c in snap["combatants"]}
    assert por_nome["Aria"]["zona"] == "Portão"
    assert por_nome["Goblin"]["zona"] == "Sacada"
    assert por_nome["Goblin"]["lendarias"] == 2
    assert por_nome["Goblin"]["recargas"] == {"Sopro": True}


def test_snapshot_sem_zonas_vem_vazio(povoar):
    _montar(povoar)
    snap = td.combat_snapshot()

    assert snap["zonas"] == []
    assert all(c["zona"] == "" for c in snap["combatants"])


# ---------------------------------------------------------------------------
# 9. O chefe age sozinho na virada de turno
# ---------------------------------------------------------------------------

def test_chefe_gasta_lendaria_na_virada(povoar):
    _montar(povoar)
    td.set_legendary_actions("Goblin", "Ataque de Cauda", count=3)
    lend = memory.campaign["characters"]["goblin"]["sheet"]["lendarias"]
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index("Aria")
    random.seed(13)

    saida = td.next_turn()          # começa o turno do Bran

    assert lend["restantes"] == 2, saida
    assert "lendária" in saida.lower()


def test_chefe_nao_gasta_lendaria_no_proprio_turno(povoar):
    _montar(povoar)
    td.set_legendary_actions("Goblin", "Ataque de Cauda", count=3)
    lend = memory.campaign["characters"]["goblin"]["sheet"]["lendarias"]
    cs = memory.campaign["combat_state"]
    # Bran age; o próximo da ordem é o Goblin.
    cs["current_turn_index"] = cs["initiative_order"].index("Bran")
    random.seed(13)

    td.next_turn()

    # Entrou no próprio turno: repôs ao cheio e não gastou nada.
    assert lend["restantes"] == 3


def test_lendaria_do_grupo_nao_e_jogada_pelo_motor(povoar):
    """Um personagem lendário do jogador continua sendo dele."""
    _montar(povoar)
    td.set_legendary_actions("Bran", "Ataque de Cauda", count=3)
    lend = memory.campaign["characters"]["bran"]["sheet"]["lendarias"]
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index("Aria")
    random.seed(13)

    td.next_turn()
    assert lend["restantes"] == 3


# ---------------------------------------------------------------------------
# 10. Movimento pela tela tática
# ---------------------------------------------------------------------------

def test_intent_move_nao_gasta_a_acao(povoar):
    _montar(povoar, zonas="Portão, Pátio, Sacada")
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index("Aria")
    cs["turn_economy"] = {"acao_usada": False, "bonus_usada": False,
                          "movimento_usado": False}

    r = td.combat_action("move", actor="Aria", target="Pátio")

    assert r["ok"] is not False
    assert td._zona_de("Aria") == "Pátio"
    eco = memory.campaign["combat_state"]["turn_economy"]
    assert eco["movimento_usado"] is True
    assert eco["acao_usada"] is False        # movimento não é Ação


def test_intent_move_so_uma_vez_por_turno(povoar):
    _montar(povoar, zonas="Portão, Pátio, Sacada")
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index("Aria")
    cs["turn_economy"] = {"acao_usada": False, "bonus_usada": False,
                          "movimento_usado": False}

    td.combat_action("move", actor="Aria", target="Pátio")
    r = td.combat_action("move", actor="Aria", target="Portão")

    assert r["ok"] is False and "já se moveu" in r["message"]


def test_disparada_custa_a_acao(povoar):
    _montar(povoar, zonas="Portão, Pátio, Sacada")
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index("Aria")
    cs["turn_economy"] = {"acao_usada": False, "bonus_usada": False,
                          "movimento_usado": False}

    td.combat_action("move", actor="Aria", target="Sacada", weapon="dash")

    assert td._zona_de("Aria") == "Sacada"
    assert memory.campaign["combat_state"]["turn_economy"]["acao_usada"] is True


def test_movimento_recusado_nao_queima_o_turno(povoar):
    """Zona inexistente não pode custar o movimento nem a Ação do jogador."""
    _montar(povoar, zonas="Portão, Pátio, Sacada")
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index("Aria")
    cs["turn_economy"] = {"acao_usada": False, "bonus_usada": False,
                          "movimento_usado": False}

    td.combat_action("move", actor="Aria", target="Cozinha", weapon="dash")

    eco = memory.campaign["combat_state"]["turn_economy"]
    assert eco["movimento_usado"] is False
    assert eco["acao_usada"] is False


def test_movimento_zera_a_cada_turno(povoar):
    _montar(povoar, zonas="Portão, Pátio, Sacada")
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index("Aria")
    cs["turn_economy"] = {"acao_usada": False, "bonus_usada": False,
                          "movimento_usado": True}

    td._reset_turn_economy(cs)
    assert cs["turn_economy"]["movimento_usado"] is False
