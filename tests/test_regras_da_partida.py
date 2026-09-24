"""
test_regras_da_partida.py

Três regras que estavam erradas na mesa, achadas jogando:

  1. "surto de ação no guerreiro não da uma ação extra" — ele era tratado como
     Ação Bônus e não devolvia nada. Usar Surto de Ação era literalmente pior
     do que não usar: gastava o Bônus e dava nada em troca.
  2. "burning hands pode ser usado em inimigos distantes" — o cone sai das
     mãos do conjurador, mas só o ataque com arma conferia alcance.
  3. "[R3] Sonael usou Tradição Arcana em Mineiro Corrompido 2" — traço de
     ficha entrando como ação com alvo, gastando o turno.
"""
import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _hab(nome, *, dado="", custo=0, alcance="", descricao="Efeito."):
    h = {"nome": nome, "descricao": descricao, "custo_mana": custo, "dado": dado}
    if alcance:
        h["alcance"] = alcance
    return h


@pytest.fixture
def campo(povoar):
    guerreiro = criar_ficha("Helena", grupo=True, nivel=3, habilidades=[
        _hab("Surto de Ação", descricao="Ganha uma Ação adicional neste turno."),
        _hab("Segunda Fôlego", dado="1d10+3"),
    ])
    mago = criar_ficha("Sonael", grupo=True, nivel=3, mana=10, habilidades=[
        _hab("Burning Hands", dado="3d6", custo=2, alcance="Self (15-foot cone)"),
        _hab("Mãos Flamejantes", dado="3d6", custo=2),          # legado: sem alcance
        _hab("Magic Missile", dado="3d4+3", custo=2, alcance="120 feet"),
        _hab("Tradição Arcana", descricao="Escolhe uma tradição."),
        _hab("Cure Wounds", dado="1d8+3", custo=2, alcance="Touch"),
    ])
    povoar(guerreiro, mago,
           criar_ficha("Cultista", vida=20),
           criar_ficha("Fanático", vida=27))
    iniciar_combate(["Helena", "Sonael", "Cultista", "Fanático"])
    memory.campaign["combat_state"]["turn_economy"] = {
        "acao_usada": False, "bonus_usada": False, "movimento_usado": False}
    return memory.campaign


def _eco():
    return memory.campaign["combat_state"]["turn_economy"]


def _vez_de(nome):
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index(nome)


def _mana(quem="sonael"):
    return memory.campaign["characters"][quem]["sheet"]["mana_atual"]


# ---------------------------------------------------------------------------
# 1. Surto de Ação
# ---------------------------------------------------------------------------

def test_surto_de_acao_devolve_a_acao(campo):
    _vez_de("Helena")
    td.combat_action("attack", "Helena", "Cultista")
    assert _eco()["acao_usada"] is True

    r = td.combat_action("ability", "Helena", ability="Surto de Ação")
    assert r["ok"], r["message"]
    assert _eco()["acao_usada"] is False, "a Ação tinha de voltar"
    assert "Ação deste turno volta" in r["message"]


def test_surto_de_acao_nao_gasta_o_bonus(campo):
    _vez_de("Helena")
    td.combat_action("ability", "Helena", ability="Surto de Ação")
    # Pela regra ele não custa ação nenhuma: o Bônus continua livre para a
    # Segunda Fôlego do mesmo turno.
    assert _eco()["bonus_usada"] is False
    assert td.combat_action("ability", "Helena", ability="Segunda Fôlego")["ok"]


def test_a_acao_devolvida_da_para_atacar_de_novo(campo):
    _vez_de("Helena")
    td.combat_action("attack", "Helena", "Cultista")
    td.combat_action("ability", "Helena", ability="Surto de Ação")
    r = td.combat_action("attack", "Helena", "Cultista")
    assert r["ok"], r["message"]


def test_surto_de_acao_uma_vez_por_turno(campo):
    _vez_de("Helena")
    td.combat_action("ability", "Helena", ability="Surto de Ação")
    r = td.combat_action("ability", "Helena", ability="Surto de Ação")
    assert not r["ok"]
    assert "já usou Surto de Ação neste turno" in r["message"]


def test_turno_novo_libera_o_surto_de_novo(campo):
    _vez_de("Helena")
    td.combat_action("ability", "Helena", ability="Surto de Ação")
    td._reset_turn_economy(memory.campaign["combat_state"])
    assert _eco().get("surto_usado") in (None, False)


# ---------------------------------------------------------------------------
# 2. Alcance da habilidade
# ---------------------------------------------------------------------------

def test_cone_nao_alcanca_outra_zona(campo):
    td.set_battlefield("Fenda, Altar, Fundo")      # grupo na Fenda, inimigos no Fundo
    _vez_de("Sonael")
    antes = _mana()
    r = td.combat_action("ability", "Sonael", "Cultista", ability="Burning Hands")
    assert not r["ok"]
    assert "FORA DE ALCANCE" in r["message"]
    assert _mana() == antes, "recusa não pode cobrar mana"
    assert _eco()["acao_usada"] is False, "recusa não pode gastar a Ação"


def test_cone_funciona_na_mesma_zona(campo):
    td.set_battlefield("Fenda, Fundo")             # grupo na Fenda, inimigos no Fundo
    _vez_de("Sonael")
    assert not td.move_combatant("Sonael", "Fundo").startswith(("Erro:", "Aviso:"))
    memory.campaign["combat_state"]["turn_economy"] = {
        "acao_usada": False, "bonus_usada": False, "movimento_usado": False}
    r = td.combat_action("ability", "Sonael", "Cultista", ability="Burning Hands")
    assert r["ok"], r["message"]


def test_legado_sem_campo_de_alcance_e_reconhecido_pelo_nome(campo):
    """Magias gravadas antes de o alcance existir na ficha."""
    td.set_battlefield("Fenda, Altar, Fundo")
    _vez_de("Sonael")
    r = td.combat_action("ability", "Sonael", "Cultista", ability="Mãos Flamejantes")
    assert not r["ok"] and "FORA DE ALCANCE" in r["message"]


def test_magia_de_alcance_longo_atravessa_o_campo(campo):
    td.set_battlefield("Fenda, Altar, Fundo")
    _vez_de("Sonael")
    r = td.combat_action("ability", "Sonael", "Cultista", ability="Magic Missile")
    assert r["ok"], r["message"]


def test_toque_tambem_exige_a_mesma_zona(campo):
    td.set_battlefield("Fenda, Altar, Fundo")
    td.move_combatant("Helena", "Altar")
    _vez_de("Sonael")
    memory.campaign["combat_state"]["turn_economy"] = {
        "acao_usada": False, "bonus_usada": False, "movimento_usado": False}
    r = td.combat_action("ability", "Sonael", "Helena", ability="Cure Wounds")
    assert not r["ok"] and "FORA DE ALCANCE" in r["message"]


def test_sem_campo_de_batalha_nada_muda(campo):
    """Campanha que não usa zonas continua jogando como antes."""
    _vez_de("Sonael")
    r = td.combat_action("ability", "Sonael", "Cultista", ability="Burning Hands")
    assert r["ok"], r["message"]


def test_de_onde_sai_a_habilidade():
    assert td._habilidade_nasce_no_conjurador({"alcance": "Self (15-foot cone)"}, "x")
    assert td._habilidade_nasce_no_conjurador({"alcance": "Touch"}, "x")
    assert td._habilidade_nasce_no_conjurador({}, "Burning Hands")
    assert td._habilidade_nasce_no_conjurador({"alcance": "60 feet"}, "Fireball") == ""
    assert td._habilidade_nasce_no_conjurador({"alcance": "120 feet"}, "Magic Missile") == ""


# ---------------------------------------------------------------------------
# 3. Traço não é ação
# ---------------------------------------------------------------------------

def test_traco_de_ficha_nao_e_acao(campo):
    _vez_de("Sonael")
    r = td.combat_action("ability", "Sonael", "Cultista", ability="Tradição Arcana")
    assert not r["ok"]
    assert "traço da ficha" in r["message"]
    assert _eco()["acao_usada"] is False, "traço não gasta o turno"


def test_a_ferramenta_direta_tambem_recusa(campo):
    """O mestre chamando use_ability por fora da tela tática."""
    _vez_de("Sonael")
    msg = td.use_ability("Sonael", "Tradição Arcana", "Cultista")
    assert msg.startswith("Erro:") and "traço da ficha" in msg


@pytest.mark.parametrize("nome", [
    "Tradição Arcana", "Arquétipo de Patrulheiro", "Aumento de Atributo",
    "Estilo de Luta", "Juramento Sagrado", "Círculo Druídico", "Domínio Divino",
])
def test_lista_dos_tracos(nome):
    assert td._e_traco_passivo(nome)


@pytest.mark.parametrize("nome", [
    "Surto de Ação", "Segunda Fôlego", "Fúria", "Canalizar Divindade",
    "Burning Hands", "Ataque Furtivo",
])
def test_o_que_se_usa_continua_sendo_acao(nome):
    assert not td._e_traco_passivo(nome)
