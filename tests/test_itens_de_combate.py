"""
test_itens_de_combate.py

Itens na tela tática. Antes só a Poção de Cura fazia alguma coisa, e mesmo ela:
  • chegava a um aliado em outra zona do campo;
  • curava acima do teto da exaustão.
Todo o resto que parecia consumível (ácido, fogo alquímico, antídoto, poção de
resistência) gastava a Ação e a unidade sem efeito nenhum.
"""
import random

import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _item(nome, qtd=1):
    return {"nome": nome, "qtd": qtd, "descricao": ""}


@pytest.fixture
def campo(povoar):
    alden = criar_ficha("Alden", grupo=True, vida=10, vida_max=30, destreza=14, nivel=3)
    alden["inventario"] = [_item("Poção de Cura", 2), _item("Frasco de Ácido", 2),
                           _item("Fogo Alquímico"), _item("Água Benta"),
                           _item("Antitoxina"), _item("Poção de Resistência ao Fogo"),
                           _item("Poção de Força de Gigante"), _item("Pergaminho Misterioso")]
    povoar(alden,
           criar_ficha("Lyra", grupo=True, vida=5, vida_max=20),
           criar_ficha("Goblin", vida=30, destreza=10),
           criar_ficha("Zumbi", vida=30, destreza=6, description="Medium undead — CR 1/4."))
    iniciar_combate(["Alden", "Lyra", "Goblin", "Zumbi"])
    memory.campaign["combat_state"]["turn_economy"] = {
        "acao_usada": False, "bonus_usada": False, "movimento_usado": False}
    return memory.campaign


def _com_zonas():
    td.set_battlefield("Portão, Pátio, Sacada")     # grupo no Portão, inimigos na Sacada


def _eco():
    return memory.campaign["combat_state"]["turn_economy"]


def _qtd(nome, quem="alden"):
    return next((i["qtd"] for i in memory.campaign["characters"][quem]["inventario"]
                 if i["nome"] == nome), 0)


def _hp(quem):
    return memory.campaign["characters"][quem]["sheet"]["vida_atual"]


# ---------------------------------------------------------------------------
# Fichas
# ---------------------------------------------------------------------------

def test_fichas_dos_itens():
    assert td._efeito_de_item("Poção de Cura Maior")["dado"] == (4, 4, 4)
    assert td._efeito_de_item("Frasco de Ácido")["efeito"] == "arremesso"
    assert td._efeito_de_item("Fogo Alquímico")["queimando"] is True
    assert td._efeito_de_item("Água Benta")["so_profanos"] is True
    assert td._efeito_de_item("Antídoto")["efeito"] == "antitoxina"
    assert td._efeito_de_item("Poção de Resistência ao Fogo")["tipo_dano"] == "fire"
    assert td._efeito_de_item("Poção de Resistência")["efeito"] == "desconhecido"
    assert td._efeito_de_item("Poção de Força de Gigante")["efeito"] == "desconhecido"
    assert td._efeito_de_item("Espada Longa") is None
    assert td._efeito_de_item("Corda") is None


def test_snapshot_lista_os_desconhecidos_travados(campo):
    alden = next(c for c in td.combat_snapshot()["combatants"] if c["name"] == "Alden")
    por_nome = {i["nome"]: i for i in alden["itens_combate"]}
    assert por_nome["Poção de Força de Gigante"]["usavel"] is False
    assert "Ação Livre" in por_nome["Poção de Força de Gigante"]["motivo"]
    assert por_nome["Frasco de Ácido"]["kind"] == "arremesso"
    assert por_nome["Antitoxina"]["kind"] == "si"
    assert por_nome["Poção de Cura"]["tipo_acao"] == "bonus"
    assert set(por_nome["Poção de Cura"]["alvos"]) == {"Alden", "Lyra"}
    assert set(por_nome["Frasco de Ácido"]["alvos"]) == {"Lyra", "Goblin", "Zumbi"}, "fogo amigo vale"
    assert por_nome["Água Benta"]["alvos"]["Goblin"] == "sem_efeito"
    assert por_nome["Água Benta"]["alvos"]["Zumbi"] == "ok"


# ---------------------------------------------------------------------------
# Item desconhecido não some mais em silêncio
# ---------------------------------------------------------------------------

def test_item_desconhecido_e_recusado_sem_gastar(campo):
    r = td.combat_action("item", actor="Alden", item="Poção de Força de Gigante")
    assert r["ok"] is False and r["message"].startswith("Aviso:")
    assert "não foi gasto" in r["message"]
    assert _qtd("Poção de Força de Gigante") == 1
    assert _eco()["acao_usada"] is False


# ---------------------------------------------------------------------------
# Poção de Cura: alcance e teto
# ---------------------------------------------------------------------------

def test_pocao_em_aliado_de_outra_zona_e_recusada_sem_gastar(campo):
    _com_zonas()
    td._por_zona("Lyra", "Pátio")
    r = td.combat_action("item", actor="Alden", item="Poção de Cura", target="Lyra")
    assert r["ok"] is False and "FORA DE ALCANCE" in r["message"]
    assert _qtd("Poção de Cura") == 2 and _eco()["bonus_usada"] is False
    assert _hp("lyra") == 5


def test_pocao_em_aliado_da_mesma_zona_e_em_si_funciona(campo):
    _com_zonas()
    r = td.combat_action("item", actor="Alden", item="Poção de Cura", target="Lyra")
    assert r["ok"] is True, r["message"]
    assert _hp("lyra") > 5 and _qtd("Poção de Cura") == 1
    assert _eco()["bonus_usada"] is True


def test_pocao_respeita_o_teto_da_exaustao(campo, monkeypatch):
    s = campo["characters"]["alden"]["sheet"]
    s.update({"exaustao": 4, "vida_atual": 14})      # teto 15 de 30
    monkeypatch.setattr(td.random, "randint", lambda a, b: b)
    r = td.combat_action("item", actor="Alden", item="Poção de Cura", target="Alden")
    assert r["ok"] is True
    assert _hp("alden") == 15, "a poção passou do teto da exaustão"
    assert "teto 15" in r["message"]


def test_pocao_levanta_aliado_caido(campo):
    lyra = campo["characters"]["lyra"]
    lyra["status"] = "inconsciente"
    lyra["sheet"]["vida_atual"] = 0
    r = td.combat_action("item", actor="Alden", item="Poção de Cura", target="Lyra")
    assert r["ok"] is True and lyra["status"] == "vivo" and _hp("lyra") > 0


# ---------------------------------------------------------------------------
# Arremessos
# ---------------------------------------------------------------------------

def _dados(monkeypatch, d20, dano):
    """d20 da salvaguarda e o valor de cada dado de dano."""
    def falso(a, b):
        return d20 if b == 20 else dano
    monkeypatch.setattr(td.random, "randint", falso)


def test_acido_falha_na_salvaguarda_causa_2d6(campo, monkeypatch):
    _dados(monkeypatch, d20=2, dano=5)
    r = td.combat_action("item", actor="Alden", item="Frasco de Ácido", target="Goblin")
    assert r["ok"] is True, r["message"]
    assert _hp("goblin") == 20, r["message"]               # 30 - (5 + 5)
    # CD 8 + DES +2 + proficiência +2
    assert "salvaguarda de DES" in r["message"] and "CD 12" in r["message"]
    assert _qtd("Frasco de Ácido") == 1 and _eco()["acao_usada"] is True


def test_acido_com_salvaguarda_bem_sucedida_nao_causa_dano(campo, monkeypatch):
    _dados(monkeypatch, d20=20, dano=6)
    r = td.combat_action("item", actor="Alden", item="Frasco de Ácido", target="Goblin")
    assert r["ok"] is True and _hp("goblin") == 30
    assert "passou" in r["message"] and _qtd("Frasco de Ácido") == 1


def test_arremesso_alcanca_a_zona_vizinha_mas_nao_duas(campo, monkeypatch):
    _com_zonas()
    _dados(monkeypatch, d20=1, dano=1)
    r = td.combat_action("item", actor="Alden", item="Frasco de Ácido", target="Goblin")
    assert r["ok"] is False and "FORA DE ALCANCE" in r["message"]
    assert _qtd("Frasco de Ácido") == 2 and _eco()["acao_usada"] is False
    td._por_zona("Goblin", "Pátio")
    assert td.combat_action("item", actor="Alden", item="Frasco de Ácido", target="Goblin")["ok"] is True


def test_fogo_amigo_com_arremesso(campo, monkeypatch):
    _dados(monkeypatch, d20=1, dano=1)
    r = td.combat_action("item", actor="Alden", item="Frasco de Ácido", target="Lyra")
    assert r["ok"] is True and _hp("lyra") == 3


def test_resistencia_do_alvo_vale_para_o_arremesso(campo, monkeypatch):
    campo["characters"]["goblin"]["sheet"]["resistencias"] = ["acid"]
    _dados(monkeypatch, d20=1, dano=5)
    td.combat_action("item", actor="Alden", item="Frasco de Ácido", target="Goblin")
    assert _hp("goblin") == 25


def test_agua_benta_so_em_morto_vivo(campo, monkeypatch):
    _dados(monkeypatch, d20=1, dano=4)
    r = td.combat_action("item", actor="Alden", item="Água Benta", target="Goblin")
    assert r["ok"] is False and r["message"].startswith("Aviso:")
    assert _qtd("Água Benta") == 1 and _eco()["acao_usada"] is False
    r = td.combat_action("item", actor="Alden", item="Água Benta", target="Zumbi")
    assert r["ok"] is True and _hp("zumbi") == 22


def test_arremesso_que_derruba_o_inimigo(campo, monkeypatch):
    campo["characters"]["goblin"]["sheet"]["vida_atual"] = 3
    _dados(monkeypatch, d20=1, dano=6)
    r = td.combat_action("item", actor="Alden", item="Frasco de Ácido", target="Goblin")
    assert campo["characters"]["goblin"]["status"] == "morto", r["message"]


# ---------------------------------------------------------------------------
# Fogo alquímico e Queimando
# ---------------------------------------------------------------------------

def _condicoes(quem):
    return [c["nome"] for c in memory.campaign["characters"][quem]["sheet"]["condicoes"]]


def test_fogo_alquimico_deixa_queimando_e_queima_no_inicio_do_turno(campo, monkeypatch):
    _dados(monkeypatch, d20=1, dano=3)
    td.combat_action("item", actor="Alden", item="Fogo Alquímico", target="Goblin")
    assert _hp("goblin") == 27 and "Queimando" in _condicoes("goblin")

    # Início do turno do Goblin: 1d4 de fogo e o teste de DES CD 10 (falha com 1).
    cs = campo["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index("Goblin")
    td._reset_turn_economy(cs)
    assert _hp("goblin") == 24
    assert "Queimando" in _condicoes("goblin")
    assert any(e.get("type") == "burning" for e in cs["log"])

    # Tira 20 no teste: apaga.
    _dados(monkeypatch, d20=20, dano=2)
    td._reset_turn_economy(cs)
    assert _hp("goblin") == 22 and "Queimando" not in _condicoes("goblin")


def test_queimando_acaba_com_o_combate(campo, monkeypatch):
    _dados(monkeypatch, d20=1, dano=1)
    td.combat_action("item", actor="Alden", item="Fogo Alquímico", target="Goblin")
    td.end_combat()
    assert "Queimando" not in _condicoes("goblin")


# ---------------------------------------------------------------------------
# Efeitos em si: resistência e antitoxina
# ---------------------------------------------------------------------------

def test_pocao_de_resistencia_corta_o_dano_do_tipo(campo):
    r = td.combat_action("item", actor="Alden", item="Poção de Resistência ao Fogo")
    assert r["ok"] is True and _eco()["bonus_usada"] is True
    alden = campo["characters"]["alden"]
    mult, _ = td._damage_multiplier(alden["sheet"], "fire")
    assert mult == 0.5
    assert "fire" in next(c for c in td.combat_snapshot()["combatants"]
                          if c["name"] == "Alden")["resistencias"]
    assert "Resistência a fogo" in td.hero_snapshot("Alden")["personagem"]["efeitos"]
    td.end_combat()
    assert td._damage_multiplier(alden["sheet"], "fire")[0] == 1.0, "o efeito passou do combate"


def test_antitoxina_marca_o_efeito_e_avisa_ao_envenenar(campo):
    r = td.combat_action("item", actor="Alden", item="Antitoxina")
    assert r["ok"] is True
    assert "Antitoxina" in next(c for c in td.combat_snapshot()["combatants"]
                                if c["name"] == "Alden")["efeitos"]
    saida = td.apply_condition("Alden", "envenenado")
    assert "Antitoxina" in saida and "vantagem" in saida


def test_bonus_e_acao_se_somam_no_turno(campo, monkeypatch):
    _dados(monkeypatch, d20=1, dano=1)
    assert td.combat_action("item", actor="Alden", item="Antitoxina")["ok"] is True
    assert td.combat_action("item", actor="Alden", item="Frasco de Ácido", target="Goblin")["ok"] is True
    r = td.combat_action("item", actor="Alden", item="Poção de Cura", target="Alden")
    assert r["ok"] is False, "a Ação Bônus já tinha sido gasta"
