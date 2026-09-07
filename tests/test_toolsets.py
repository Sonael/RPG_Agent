"""
test_toolsets.py
Conjunto de ferramentas entregue por turno.

O QUE ESTES TESTES TRANCAM
──────────────────────────
Dois filtros, com motivações diferentes:

• Modo "tela" — correção. A luta é resolvida pela interface via
  combat_action(); a instrução já proibia a LLM de chamar
  attack_roll/use_ability/next_turn/execute_npc_turn/roll_death_save ali, mas
  proibição por prompt é esperança. Aqui a ferramenta some do conjunto, e o
  turno duplicado deixa de ser possível em vez de ser desencorajado.

• Campanha não-D&D — custo. Romance e horror não têm regras; carregavam 39
  ferramentas que nunca chamam.
"""

import asyncio

import pytest

from rpg.tools import ALL_TOOLS
from rpg.tools_dnd import DND_TOOLS
from rpg.toolsets import (
    FerramentasDoTurno,
    FERRAMENTAS_SO_DO_MODO_NARRADO,
    FERRAMENTAS_SO_DO_MODO_DND,
)

TOTAL = len(ALL_TOOLS)
N_DND = len(FERRAMENTAS_SO_DO_MODO_DND)


def nomes(tools):
    return {t.name for t in tools}


def entregues(conjunto):
    return asyncio.run(conjunto.get_tools())


@pytest.fixture
def conjunto():
    return FerramentasDoTurno(ALL_TOOLS)


@pytest.fixture
def dnd(campanha):
    """Campanha D&D em modo narrado — o cenário de conjunto completo."""
    campanha["dnd_mode"] = True
    campanha["campaign_type"] = "dnd"
    campanha["combat_mode"] = "narrado"
    return campanha


@pytest.fixture
def romance(campanha):
    """Campanha sem regras: nenhuma ferramenta do motor D&D faz sentido."""
    campanha["dnd_mode"] = False
    campanha["campaign_type"] = "romance"
    campanha["combat_mode"] = "narrado"
    return campanha


# ---------------------------------------------------------------------------
# Campanha D&D, modo narrado: nada é retirado
# ---------------------------------------------------------------------------

def test_dnd_narrado_entrega_todas(dnd, conjunto):
    assert len(entregues(conjunto)) == TOTAL


def test_campo_de_modo_ausente_nao_filtra_nada(dnd, conjunto):
    """Campanha antiga, sem combat_mode: o padrão é o modo narrado."""
    dnd.pop("combat_mode", None)
    assert len(entregues(conjunto)) == TOTAL


# ---------------------------------------------------------------------------
# Modo tela: some o que a instrução já proibia
# ---------------------------------------------------------------------------

def test_modo_tela_retira_as_ferramentas_de_turno(dnd, conjunto):
    dnd["combat_mode"] = "tela"
    disponiveis = nomes(entregues(conjunto))

    assert not (disponiveis & FERRAMENTAS_SO_DO_MODO_NARRADO), (
        "a tela tática resolve o combate pelo motor; a LLM não pode ter "
        "estas ferramentas ou produz turno duplicado"
    )
    assert len(disponiveis) == TOTAL - len(FERRAMENTAS_SO_DO_MODO_NARRADO)


@pytest.mark.parametrize("ferramenta", sorted(FERRAMENTAS_SO_DO_MODO_NARRADO))
def test_cada_ferramenta_proibida_some(dnd, conjunto, ferramenta):
    dnd["combat_mode"] = "tela"
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
def test_ferramentas_que_devem_sobreviver_ao_modo_tela(dnd, conjunto, ferramenta):
    dnd["combat_mode"] = "tela"
    assert ferramenta in nomes(entregues(conjunto))


# ---------------------------------------------------------------------------
# Campanha não-D&D: o motor de regras inteiro sai
# ---------------------------------------------------------------------------

def test_campanha_sem_regras_perde_o_motor_dnd(romance, conjunto):
    disponiveis = nomes(entregues(conjunto))
    assert not (disponiveis & FERRAMENTAS_SO_DO_MODO_DND)
    assert len(disponiveis) == TOTAL - N_DND


@pytest.mark.parametrize("estilo", ["fantasia", "romance", "horror",
                                    "misterio", "scifi", "faroeste"])
def test_todos_os_estilos_sem_regras_filtram(campanha, conjunto, estilo):
    campanha["dnd_mode"] = False
    campanha["campaign_type"] = estilo
    campanha["combat_mode"] = "narrado"
    assert len(entregues(conjunto)) == TOTAL - N_DND


@pytest.mark.parametrize("ferramenta", [
    "save_character", "get_character", "save_location", "save_event",
    "set_flag", "add_diary_entry", "update_world_state", "get_scene_context",
    "add_party_member", "update_story_summary",
])
def test_ferramentas_narrativas_sobrevivem(romance, conjunto, ferramenta):
    assert ferramenta in nomes(entregues(conjunto))


def test_roll_dice_fica_em_toda_campanha(romance, conjunto):
    """
    Carve-out deliberado: é o único primitivo de aleatoriedade do sistema,
    não depende de ficha e é genérico de gênero — um mistério pode querer
    um dado sem ter regras.
    """
    assert "roll_dice" in nomes(entregues(conjunto))
    assert "roll_dice" not in FERRAMENTAS_SO_DO_MODO_DND


def test_o_filtro_cobre_o_motor_inteiro():
    """FERRAMENTAS_SO_DO_MODO_DND deve ser DND_TOOLS menos o carve-out."""
    todas_dnd = {f.__name__ for f in DND_TOOLS}
    assert FERRAMENTAS_SO_DO_MODO_DND == todas_dnd - {"roll_dice"}


# ---------------------------------------------------------------------------
# Salvaguarda: ficha na campanha vence a flag
# ---------------------------------------------------------------------------

def test_campanha_com_ficha_mantem_o_motor_mesmo_sem_a_flag(campanha, conjunto):
    """
    Uma campanha importada de JSON sem `dnd_mode`, mas com fichas salvas,
    continua precisando do motor. Perder as ferramentas no meio de uma
    campanha em andamento seria bem pior que carregar schema a mais.
    """
    from conftest import criar_ficha

    campanha["dnd_mode"] = False
    campanha["campaign_type"] = "fantasia"
    campanha["characters"]["heroína"] = criar_ficha("Heroína", grupo=True)

    disponiveis = nomes(entregues(conjunto))
    assert "attack_roll" in disponiveis
    assert len(disponiveis) == TOTAL


def test_campanha_sem_ficha_nenhuma_filtra(campanha, conjunto):
    campanha["dnd_mode"] = False
    campanha["campaign_type"] = "fantasia"
    campanha["characters"] = {
        "ana": {"name": "Ana", "description": "", "habilidades": []},   # sem sheet
    }
    assert len(entregues(conjunto)) == TOTAL - N_DND


def test_campaign_type_dnd_basta_mesmo_sem_a_flag(campanha, conjunto):
    campanha["dnd_mode"] = False
    campanha["campaign_type"] = "dnd"
    assert len(entregues(conjunto)) == TOTAL


# ---------------------------------------------------------------------------
# Os dois filtros se compõem
# ---------------------------------------------------------------------------

def test_filtros_se_compoem(dnd, conjunto):
    """D&D + tela retira só as de turno; não-D&D + tela retiraria os dois."""
    dnd["combat_mode"] = "tela"
    so_tela = len(entregues(conjunto))

    dnd["dnd_mode"] = False
    dnd["campaign_type"] = "romance"
    ambos = len(entregues(conjunto))

    assert ambos < so_tela < TOTAL


# ---------------------------------------------------------------------------
# Estabilidade do schema (cache de prompt)
# ---------------------------------------------------------------------------

def test_mesmos_objetos_entre_turnos(dnd, conjunto):
    """
    Os schemas ficam no início da requisição e são o bloco mais cacheável que
    existe. Reconstruir os FunctionTool a cada turno mudaria o prefixo e
    jogaria o cache fora.
    """
    primeira = entregues(conjunto)
    segunda = entregues(conjunto)
    assert all(a is b for a, b in zip(primeira, segunda))


def test_conjunto_muda_quando_o_modo_muda(dnd, conjunto):
    antes = len(entregues(conjunto))
    dnd["combat_mode"] = "tela"
    assert len(entregues(conjunto)) < antes


def test_voltar_para_narrado_devolve_as_ferramentas(dnd, conjunto):
    dnd["combat_mode"] = "tela"
    entregues(conjunto)
    dnd["combat_mode"] = "narrado"
    assert len(entregues(conjunto)) == TOTAL


# ---------------------------------------------------------------------------
# Falha segura
# ---------------------------------------------------------------------------

def test_erro_ao_ler_a_campanha_entrega_tudo(conjunto, monkeypatch):
    """
    Sem contexto de campanha, o conjunto completo é o padrão seguro: uma
    ferramenta faltando faz a LLM narrar a mecânica sozinha, que é a falha
    exata que o verificador de resposta existe para pegar.
    """
    class _CampanhaQuebrada:
        def get(self, *a, **k):
            raise RuntimeError("sem contexto")

    class _MemoriaFalsa:
        campaign = _CampanhaQuebrada()

    monkeypatch.setitem(__import__("sys").modules, "rpg.memory", _MemoriaFalsa)
    assert len(entregues(conjunto)) == TOTAL


def test_o_agente_recebe_o_conjunto_e_nao_a_lista(campanha):
    """
    create_agent precisa passar o toolset, senão o ADK congela as ferramentas
    na criação do Agent e o filtro nunca roda.
    """
    from rpg.agent import create_agent

    agente = create_agent("gemini-2.0-flash", "dnd")
    assert len(agente.tools) == 1
    assert isinstance(agente.tools[0], FerramentasDoTurno)
