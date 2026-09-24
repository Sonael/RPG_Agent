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

• As ferramentas das relações (afeto, confiança, estágio, momentos) são do
  romance, e as do mundo (renome, facções, laços, lendas, bestiário) são da
  fantasia e do dark fantasy. esperado() diz quantas cada campanha recebe.
"""

import asyncio

import pytest

from rpg.tools import ALL_TOOLS
from rpg.tools_dnd import DND_TOOLS
from rpg.toolsets import (
    FerramentasDoTurno,
    FERRAMENTAS_SO_DO_MODO_NARRADO,
    FERRAMENTAS_SO_DO_MODO_DND,
    FERRAMENTAS_SO_DO_ROMANCE,
    FERRAMENTAS_SO_DA_FANTASIA,
    FERRAMENTAS_SO_EM_COMBATE,
    FERRAMENTAS_SO_COM_LOJA,
)

TOTAL = len(ALL_TOOLS)
N_DND = len(FERRAMENTAS_SO_DO_MODO_DND)
N_ROMANCE = len(FERRAMENTAS_SO_DO_ROMANCE)
N_FANTASIA = len(FERRAMENTAS_SO_DA_FANTASIA)


def esperado(genero: str, dnd: bool = True, tela: bool = False,
             em_combate: bool = False, com_loja: bool = False) -> int:
    """
    Quantas ferramentas uma campanha recebe: o total menos o que não é dela.

    A cena parada, sem luta e sem loja por perto, é o caso NORMAL — por isso
    os dois filtros de momento entram como padrão aqui.
    """
    n = TOTAL
    if not dnd:
        n -= N_DND
    if genero != "romance":
        n -= N_ROMANCE
    if genero not in ("fantasia", "dark_fantasy"):
        n -= N_FANTASIA
    if tela:
        n -= len(FERRAMENTAS_SO_DO_MODO_NARRADO)
    if not em_combate:
        n -= len(FERRAMENTAS_SO_EM_COMBATE - (FERRAMENTAS_SO_DO_MODO_NARRADO if tela else frozenset())
                 - (FERRAMENTAS_SO_DO_MODO_DND if not dnd else frozenset()))
    if not com_loja:
        n -= len(FERRAMENTAS_SO_COM_LOJA - (FERRAMENTAS_SO_DO_MODO_DND if not dnd else frozenset()))
    return n


# A campanha D&D das fixtures é fantasia ("dnd" é a fantasia de antes).
FORA_DO_ROMANCE = esperado("fantasia")


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
    assert len(entregues(conjunto)) == FORA_DO_ROMANCE


def test_campo_de_modo_ausente_nao_filtra_nada(dnd, conjunto):
    """Campanha antiga, sem combat_mode: o padrão é o modo narrado."""
    dnd.pop("combat_mode", None)
    assert len(entregues(conjunto)) == FORA_DO_ROMANCE


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
    assert len(disponiveis) == esperado("fantasia", tela=True)


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
    assert len(disponiveis) == esperado("romance", dnd=False)


@pytest.mark.parametrize("estilo", ["fantasia", "romance", "horror",
                                    "misterio", "scifi", "faroeste"])
def test_todos_os_estilos_sem_regras_filtram(campanha, conjunto, estilo):
    campanha["dnd_mode"] = False
    campanha["campaign_type"] = estilo
    campanha["combat_mode"] = "narrado"
    assert len(entregues(conjunto)) == esperado(estilo, dnd=False)


def test_ferramentas_de_relacao_so_no_romance(romance, conjunto):
    assert FERRAMENTAS_SO_DO_ROMANCE <= nomes(entregues(conjunto))
    romance["campaign_type"] = "horror"
    assert not (FERRAMENTAS_SO_DO_ROMANCE & nomes(entregues(conjunto)))


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
    """
    FERRAMENTAS_SO_DO_MODO_DND deve ser DND_TOOLS menos o carve-out.

    O carve-out é escrito à mão AQUI de propósito, em vez de importado de
    _CARVE_OUT_GENERICAS: importar tornaria o teste tautológico, e a graça
    dele é justamente obrigar quem mexer no carve-out a passar por este
    ponto e justificar a exceção.

    Quem está de fora, e por quê:
      roll_dice      único primitivo de aleatoriedade do sistema; não depende
                     de ficha e serve a qualquer gênero.
      advance_time   relógio de mundo não é regra de D&D — um horror precisa
      get_world_time que anoiteça e um mistério precisa que o prazo corra.
    """
    todas_dnd = {f.__name__ for f in DND_TOOLS}
    carve_out = {"roll_dice", "advance_time", "get_world_time"}
    assert FERRAMENTAS_SO_DO_MODO_DND == todas_dnd - carve_out


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
    assert len(disponiveis) == FORA_DO_ROMANCE


def test_campanha_sem_ficha_nenhuma_filtra(campanha, conjunto):
    campanha["dnd_mode"] = False
    campanha["campaign_type"] = "fantasia"
    campanha["characters"] = {
        "ana": {"name": "Ana", "description": "", "habilidades": []},   # sem sheet
    }
    assert len(entregues(conjunto)) == esperado("fantasia", dnd=False)


def test_campaign_type_dnd_basta_mesmo_sem_a_flag(campanha, conjunto):
    campanha["dnd_mode"] = False
    campanha["campaign_type"] = "dnd"
    assert len(entregues(conjunto)) == FORA_DO_ROMANCE


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

    assert ambos < so_tela < FORA_DO_ROMANCE


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
    assert len(entregues(conjunto)) == FORA_DO_ROMANCE


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

    # O filtro faz `from rpg import memory`, que lê o atributo do pacote, não
    # sys.modules: trocar só sys.modules deixava a memória de verdade no lugar,
    # e o teste passava sem nunca chegar ao caminho de erro.
    import rpg
    monkeypatch.setitem(__import__("sys").modules, "rpg.memory", _MemoriaFalsa)
    monkeypatch.setattr(rpg, "memory", _MemoriaFalsa)
    assert len(entregues(conjunto)) == TOTAL


# ---------------------------------------------------------------------------
# O momento da cena: luta em andamento e loja por perto
# ---------------------------------------------------------------------------
# A mesa tem 117 ferramentas. Fora de combate, as de turno não são só peso de
# schema: são porta para erro — o mestre que chama next_turn sem luta recebe
# recusa e gasta o turno com isso.

@pytest.fixture
def em_luta(dnd):
    dnd["combat_state"] = {"is_active": True, "initiative_order": ["Alden", "Goblin"],
                           "current_turn_index": 0, "round": 1}
    return dnd


@pytest.mark.parametrize("ferramenta", sorted(FERRAMENTAS_SO_EM_COMBATE))
def test_fora_de_combate_a_ferramenta_de_turno_some(dnd, conjunto, ferramenta):
    assert ferramenta not in nomes(entregues(conjunto))


@pytest.mark.parametrize("ferramenta", sorted(FERRAMENTAS_SO_EM_COMBATE))
def test_com_a_luta_em_andamento_ela_volta(em_luta, conjunto, ferramenta):
    assert ferramenta in nomes(entregues(conjunto))


@pytest.mark.parametrize("ferramenta", [
    "roll_initiative",        # é ela que ABRE a luta
    "set_battlefield",        # montagem do encontro
    "spawn_monster",
    "set_combat_side",
    "end_combat",             # escape de uma luta que não fechou direito
    "roll_death_save",        # uma queda fora de combate derruba alguém
    "resolve_saving_throw",
    "modify_hp",
])
def test_o_que_precisa_existir_fora_da_luta(dnd, conjunto, ferramenta):
    assert ferramenta in nomes(entregues(conjunto))


def test_combate_ativo_e_o_que_manda(dnd, conjunto):
    """initiative_order cheia com is_active falso é luta acabada."""
    dnd["combat_state"] = {"is_active": False, "initiative_order": ["Alden"]}
    assert "next_turn" not in nomes(entregues(conjunto))


def test_sem_loja_por_perto_nao_se_compra(dnd, conjunto):
    dnd["lojas"] = {}
    disponiveis = nomes(entregues(conjunto))
    assert "buy_item" not in disponiveis and "sell_item" not in disponiveis
    # Abrir a loja continua possível: é assim que a cena de mercado começa.
    assert "open_shop" in disponiveis


def test_loja_no_local_do_grupo_libera_a_compra(dnd, conjunto):
    dnd["current_location"] = "Cliviate"
    dnd["lojas"] = {"forja": {"nome": "Forja", "local": "Cliviate", "estoque": []}}
    assert "buy_item" in nomes(entregues(conjunto))


def test_loja_em_outro_lugar_nao_libera(dnd, conjunto):
    dnd["current_location"] = "Floresta das Brumas"
    dnd["lojas"] = {"forja": {"nome": "Forja", "local": "Cliviate", "estoque": []}}
    assert "buy_item" not in nomes(entregues(conjunto))


def test_loja_sem_local_conta_como_aqui(dnd, conjunto):
    """Loja gravada sem lugar é de campanha antiga: na dúvida, não corta."""
    dnd["current_location"] = "Cliviate"
    dnd["lojas"] = {"forja": {"nome": "Forja", "estoque": []}}
    assert "buy_item" in nomes(entregues(conjunto))


def test_a_fase_muda_o_conjunto_e_volta(dnd, conjunto):
    """O conjunto precisa ser estável DENTRO da fase — é o que salva o cache."""
    fora = nomes(entregues(conjunto))
    assert fora == nomes(entregues(conjunto))
    dnd["combat_state"] = {"is_active": True, "initiative_order": ["Alden"]}
    dentro = nomes(entregues(conjunto))
    assert dentro > fora
    dnd["combat_state"] = {"is_active": False, "initiative_order": []}
    assert nomes(entregues(conjunto)) == fora


def test_o_agente_recebe_o_conjunto_e_nao_a_lista(campanha):
    """
    create_agent precisa passar o toolset, senão o ADK congela as ferramentas
    na criação do Agent e o filtro nunca roda.
    """
    from rpg.agent import create_agent

    agente = create_agent("gemini-2.0-flash", "dnd")
    assert len(agente.tools) == 1
    assert isinstance(agente.tools[0], FerramentasDoTurno)
