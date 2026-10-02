"""
test_magias_e_sistemas.py

Magias fora de combate que se ligam aos sistemas do jogo: Identificação (o
item da mochila), Bom Fruto (frutas de cura que perdem a magia), Aprimorar
Habilidade e Passos sem Pegadas (testes de perícia), Ver o Invisível (o
ataque) e Luz do Dia (acaba com a Escuridão).

E dois defeitos achados no caminho: a Orientação nunca entrava num teste de
perícia (_bonus_de_teste existia e ninguém o chamava), e atacar quem está
Invisível não tinha desvantagem.
"""
import random

import pytest

from rpg import memory, resolucao, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _ch(nome):
    return memory.campaign["characters"].get(memory.char_key(nome))


def _hab(nome, custo=3):
    return {"nome": nome, "custo_mana": custo, "dado": "", "descricao": "[Magia] ",
            "nivel_magia": (resolucao._magia_srd({"nome": nome}) or {}).get("nivel", 1)}


MAGIAS = ["Identify", "Goodberry", "Enhance Ability", "Pass without Trace", "See Invisibility",
          "True Seeing", "Daylight", "Darkness", "Guidance"]


@pytest.fixture
def grupo(campanha, povoar):
    povoar(criar_ficha("Mira", grupo=True, classe="mago", nivel=11, mana=80, vida=40, destreza=12,
                       habilidades=[_hab(n) for n in MAGIAS]),
           criar_ficha("Alden", grupo=True, vida=40, destreza=12, forca=12),
           criar_ficha("Orc", vida=60, ca=10))
    return memory.campaign


@pytest.mark.parametrize("nome", MAGIAS[:7])
def test_cartao(nome):
    assert resolucao.como_resolve(_hab(nome))["tipo"] == "efeito", nome


def _d20(monkeypatch, seq):
    it = iter(seq)
    monkeypatch.setattr(random, "randint", lambda a, b: next(it, 10))


# ---------------------------------------------------------------------------
# Testes de perícia
# ---------------------------------------------------------------------------

def test_orientacao_entra_no_teste_e_acaba(grupo, monkeypatch):
    td.dar_efeito_de_combate(_ch("Alden"), {"nome": "Orientação", "teste_dado": "1d4", "usos": 1})
    _d20(monkeypatch, [4, 10])           # o 1d4 da Orientação sai antes do d20
    saida = td.make_skill_check("Alden", "sabedoria", 13, skill="percepção")
    assert "Orientação" in saida and "= **16**" in saida, saida          # 10 + 0 + 2(prof) + 4
    _d20(monkeypatch, [10])
    assert "Orientação" not in td.make_skill_check("Alden", "sabedoria", 13, skill="percepção")


def test_aprimorar_habilidade_da_vantagem(grupo, monkeypatch):
    r = td.conjurar_fora_de_combate("Mira", "Enhance Ability", "Alden", modo="touro")
    assert r["ok"], r["message"]
    pedidos = []
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda v, d: (pedidos.append(v), (10, "d20=10"))[1])
    td.make_skill_check("Alden", "forca", 15, skill="atletismo")
    td.make_skill_check("Alden", "destreza", 15, skill="acrobacia")
    assert pedidos == [True, False]


def test_vantagem_tambem_com_o_dado_do_jogador(grupo, monkeypatch):
    td.conjurar_fora_de_combate("Mira", "Enhance Ability", "Alden", modo="aguia")
    _d20(monkeypatch, [18])
    saida = td.make_skill_check("Alden", "carisma", 15, skill="persuasão", player_roll=3)
    assert "segundo d20 = 18" in saida and "SUCESSO" in saida, saida
    _d20(monkeypatch, [18])
    saida = td.social_check("Alden", "persuasão", 15, 3)
    assert "segundo d20 = 18" in saida, saida


def test_vigor_do_urso_da_pv_temporarios(grupo, monkeypatch):
    _d20(monkeypatch, [6, 6])
    td.conjurar_fora_de_combate("Mira", "Enhance Ability", "Alden", modo="urso")
    assert _ch("Alden")["sheet"]["vida_temp"] == 12


def test_passos_sem_pegadas_soma_dez_na_furtividade(grupo, monkeypatch):
    td.conjurar_fora_de_combate("Mira", "Pass without Trace")
    _d20(monkeypatch, [5])
    saida = td.make_skill_check("Alden", "destreza", 15, skill="furtividade")
    assert "+10(efeitos)" in saida and "= **16**" in saida, saida


# ---------------------------------------------------------------------------
# Itens
# ---------------------------------------------------------------------------

def test_identificacao_escolhe_o_item_da_mochila(grupo, monkeypatch):
    _ch("Mira")["inventario"] = [{"nome": "Anel Estranho", "qtd": 1, "descricao": "brilha"},
                                 {"nome": "Pérola", "qtd": 1, "identificado": True}]
    chamado = []
    monkeypatch.setattr(td, "identify_item", lambda quem, item: (chamado.append(item), f"**{item}** é um Anel de Proteção")[1])
    modos = resolucao.como_resolve(_hab("Identify"), _ch("Mira"))["modos"]
    assert modos == ["Anel Estranho"]
    assert not td.conjurar_fora_de_combate("Mira", "Identify")["ok"]          # sem item
    r = td.conjurar_fora_de_combate("Mira", "Identify", modo="Anel Estranho", ritual=True)
    assert r["ok"] and chamado == ["Anel Estranho"] and "Anel de Proteção" in r["message"]
    assert _ch("Mira")["sheet"]["mana_atual"] == 80                          # ritual: sem mana


def test_identificacao_nao_se_conjura_na_luta(grupo):
    _ch("Mira")["inventario"] = [{"nome": "Anel", "qtd": 1, "descricao": ""},
                                 {"nome": "Pérola", "qtd": 1, "identificado": True}]
    iniciar_combate(["Mira", "Orc"])
    r = td.combat_action("ability", actor="Mira", ability="Identify", weapon="Anel")
    assert not r["ok"] and "não dá no meio da luta" in r["message"], r["message"]


def test_orientacao_entra_no_teste_social(grupo, monkeypatch):
    td.dar_efeito_de_combate(_ch("Alden"), {"nome": "Orientação", "teste_dado": "1d4", "usos": 1})
    _d20(monkeypatch, [4])
    saida = td.social_check("Alden", "persuasão", 30, 10)
    assert "Orientação" in saida and "= **14**" in saida, saida          # 10 + 0 + 4


def test_bom_fruto_cura_e_perde_a_magia(grupo):
    td.conjurar_fora_de_combate("Mira", "Goodberry")
    fruto = next(i for i in _ch("Mira")["inventario"] if i["nome"] == "Bom Fruto")
    assert fruto["qtd"] == 10
    assert td._efeito_de_item("Bom Fruto")["dado"] == (1, 1, 0)
    td.advance_time(25, "a noite passa")
    assert not [i for i in _ch("Mira")["inventario"] if i["nome"] == "Bom Fruto"]


# ---------------------------------------------------------------------------
# Invisibilidade
# ---------------------------------------------------------------------------

def _pedidos(monkeypatch):
    pedidos = []
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda v, d: (pedidos.append((v, d)), (10, "d20=10"))[1])
    return pedidos


def test_atacar_invisivel_tem_desvantagem(grupo, monkeypatch):
    iniciar_combate(["Mira", "Orc"])
    _ch("Mira")["sheet"]["condicoes"].append({"nome": "Invisível", "duracao": None})
    p = _pedidos(monkeypatch)
    td.attack_roll("Orc", "Mira", "machado grande", 12, end_turn=False, _skip_turn_check=True)
    assert p[0] == (False, True)


def test_ver_o_invisivel_anula(grupo, monkeypatch):
    iniciar_combate(["Mira", "Alden", "Orc"])
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = 0
    td._reset_turn_economy(cs)
    assert td.combat_action("ability", actor="Mira", ability="See Invisibility", target="Mira")["ok"]
    _ch("Orc")["sheet"]["condicoes"].append({"nome": "Invisível", "duracao": None})
    p = _pedidos(monkeypatch)
    td.attack_roll("Mira", "Orc", "adaga", 4, end_turn=False, _skip_turn_check=True)
    td.attack_roll("Orc", "Mira", "machado grande", 12, end_turn=False, _skip_turn_check=True)
    assert p[0] == (False, False) and p[1] == (False, False)
    # Quem não vê o invisível: o orc ainda tem vantagem contra Alden.
    p.clear()
    td.attack_roll("Orc", "Alden", "machado grande", 12, end_turn=False, _skip_turn_check=True)
    assert p[0] == (True, False)


# ---------------------------------------------------------------------------
# Luz do Dia
# ---------------------------------------------------------------------------

def test_luz_do_dia_acaba_com_a_escuridao(grupo):
    iniciar_combate(["Mira", "Alden", "Orc"])
    cs = memory.campaign["combat_state"]
    cs["zonas"] = ["Portão", "Pátio"]
    cs["posicoes"] = {"mira": "Portão", "alden": "Pátio", "orc": "Pátio"}
    _ch("Alden")["habilidades"] = [_hab("Darkness")]
    cs["current_turn_index"] = 1
    td._reset_turn_economy(cs)
    assert td.combat_action("ability", actor="Alden", ability="Darkness", weapon="Pátio")["ok"]
    assert td._zona_obscurecida("Orc")
    cs["current_turn_index"] = 0
    td._reset_turn_economy(cs)
    assert td.combat_action("ability", actor="Mira", ability="Daylight", weapon="Pátio")["ok"]
    assert not td._zona_obscurecida("Orc")
