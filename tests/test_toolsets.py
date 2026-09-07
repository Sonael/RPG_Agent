"""
test_toolsets.py
Conjunto de ferramentas entregue por turno.

O QUE ESTES TESTES TRANCAM
──────────────────────────
No modo de combate "tela" a luta é resolvida pela interface via
combat_action(). A instrução do sistema já proibia a LLM de chamar
attack_roll/use_ability/next_turn/execute_npc_turn/roll_death_save ali — mas
proibição por prompt é esperança. Aqui a ferramenta some do conjunto, e o
turno duplicado deixa de ser possível em vez de ser desencorajado.
"""

import asyncio

import pytest

from rpg.tools import ALL_TOOLS
from rpg.toolsets import FerramentasDoTurno, FERRAMENTAS_SO_DO_MODO_NARRADO


def nomes(tools):
    return {t.name for t in tools}


def entregues(conjunto):
    return asyncio.run(conjunto.get_tools())


@pytest.fixture
def conjunto():
    return FerramentasDoTurno(ALL_TOOLS)


# ---------------------------------------------------------------------------
# Modo narrado: nada é retirado
# ---------------------------------------------------------------------------

def test_modo_narrado_entrega_todas(campanha, conjunto):
    campanha["combat_mode"] = "narrado"
    assert len(entregues(conjunto)) == len(ALL_TOOLS)


def test_modo_ausente_entrega_todas(campanha, conjunto):
    """Campanha antiga, sem o campo: o padrão seguro é entregar tudo."""
    campanha.pop("combat_mode", None)
    assert len(entregues(conjunto)) == len(ALL_TOOLS)


# ---------------------------------------------------------------------------
# Modo tela: some o que a instrução já proibia
# ---------------------------------------------------------------------------

def test_modo_tela_retira_as_ferramentas_de_turno(campanha, conjunto):
    campanha["combat_mode"] = "tela"
    disponiveis = nomes(entregues(conjunto))

    assert not (disponiveis & FERRAMENTAS_SO_DO_MODO_NARRADO), (
        "a tela tática resolve o combate pelo motor; a LLM não pode ter "
        "estas ferramentas ou produz turno duplicado"
    )
    assert len(disponiveis) == len(ALL_TOOLS) - len(FERRAMENTAS_SO_DO_MODO_NARRADO)


@pytest.mark.parametrize("ferramenta", sorted(FERRAMENTAS_SO_DO_MODO_NARRADO))
def test_cada_ferramenta_proibida_some(campanha, conjunto, ferramenta):
    campanha["combat_mode"] = "tela"
    assert ferramenta not in nomes(entregues(conjunto))


@pytest.mark.parametrize("ferramenta", [
    "roll_initiative",    # a LLM ainda abre o combate — é o gatilho da tela
    "end_combat",         # escape se a tela não concluir
    "spawn_monster",      # usada ANTES da luta
    "set_npc_strategy",
    "make_skill_check",   # improviso no meio da luta chega como texto
    "modify_hp",          # dano fora de combate segue na narração
    "apply_condition",
    "grant_xp",
    "add_item",
])
def test_ferramentas_que_devem_sobreviver_ao_modo_tela(campanha, conjunto, ferramenta):
    campanha["combat_mode"] = "tela"
    assert ferramenta in nomes(entregues(conjunto))


# ---------------------------------------------------------------------------
# Estabilidade do schema (cache de prompt)
# ---------------------------------------------------------------------------

def test_mesmos_objetos_entre_turnos(campanha, conjunto):
    """
    Os schemas ficam no início da requisição e são o bloco mais cacheável que
    existe. Reconstruir os FunctionTool a cada turno mudaria o prefixo e
    jogaria o cache fora.
    """
    campanha["combat_mode"] = "narrado"
    primeira = entregues(conjunto)
    segunda = entregues(conjunto)
    assert all(a is b for a, b in zip(primeira, segunda))


def test_conjunto_muda_quando_o_modo_muda(campanha, conjunto):
    campanha["combat_mode"] = "narrado"
    antes = len(entregues(conjunto))
    campanha["combat_mode"] = "tela"
    depois = len(entregues(conjunto))
    assert depois < antes


def test_voltar_para_narrado_devolve_as_ferramentas(campanha, conjunto):
    campanha["combat_mode"] = "tela"
    entregues(conjunto)
    campanha["combat_mode"] = "narrado"
    assert len(entregues(conjunto)) == len(ALL_TOOLS)


# ---------------------------------------------------------------------------
# Falha segura
# ---------------------------------------------------------------------------

def test_erro_ao_ler_a_campanha_entrega_tudo(conjunto, monkeypatch):
    """
    Sem contexto de campanha, o conjunto completo é o padrão seguro: uma
    ferramenta faltando faz a LLM narrar a mecânica sozinha, que é a falha
    exata que o verificador de resposta existe para pegar.
    """
    import rpg.toolsets as mod

    class _CampanhaQuebrada:
        def get(self, *a, **k):
            raise RuntimeError("sem contexto")

    class _MemoriaFalsa:
        campaign = _CampanhaQuebrada()

    monkeypatch.setitem(__import__("sys").modules, "rpg.memory", _MemoriaFalsa)
    assert len(entregues(conjunto)) == len(ALL_TOOLS)


def test_o_agente_recebe_o_conjunto_e_nao_a_lista(campanha):
    """
    create_agent precisa passar o toolset, senão o ADK congela as ferramentas
    na criação do Agent e o filtro nunca roda.
    """
    from rpg.agent import create_agent

    agente = create_agent("gemini-2.0-flash", "dnd")
    assert len(agente.tools) == 1
    assert isinstance(agente.tools[0], FerramentasDoTurno)
