"""
test_manobras.py

A tela tinha Atacar, Habilidade, Item, Mover, Defender e Fugir. Ajudar,
Esconder-se, Agarrar, Empurrar e Preparar iam pela Ação Livre e o Mestre
arbitrava sem a regra: "ajudo o guerreiro" virava frase, não vantagem; o
goblin agarrado seguia andando. E a IA do inimigo ignorava "não sai da zona":
o orc preso na Teia avançava normalmente.
"""
import random

import pytest

from rpg import manobras, memory, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _ch(nome):
    return memory.campaign["characters"][memory.char_key(nome)]


def _vez(nome):
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index(nome)
    cs["turn_token"] = int(cs.get("turn_token", 0) or 0) + 1
    td._reset_turn_economy(cs)


def _sequencia(monkeypatch, valores):
    it = iter(valores)
    monkeypatch.setattr(random, "randint", lambda a, b: next(it, 10))


def _acao(acao, ator, alvo="", modo=""):
    _vez(ator)
    return td.combat_action(acao, actor=ator, target=alvo, weapon=modo)


def _conds(nome):
    return [c.get("nome") if isinstance(c, dict) else c for c in _ch(nome)["sheet"]["condicoes"]]


@pytest.fixture
def luta(campanha, povoar):
    povoar(criar_ficha("Alden", grupo=True, vida=40, forca=18),
           criar_ficha("Kaelen", grupo=True, vida=40),
           criar_ficha("Orc", vida=60, raca="orc", arma="machado grande", ca=10))
    iniciar_combate(["Alden", "Kaelen", "Orc"])
    cs = memory.campaign["combat_state"]
    cs["zonas"] = ["Portão", "Pátio", "Sacada"]
    cs["posicoes"] = {"alden": "Pátio", "kaelen": "Pátio", "orc": "Pátio"}
    _vez("Alden")
    return memory.campaign


def test_ajudar_da_vantagem_ao_proximo_ataque_do_aliado(luta):
    r = _acao("help", "Alden", "Orc")
    assert r["ok"], r["message"]
    assert memory.campaign["combat_state"]["turn_economy"]["acao_usada"]
    mods = td._mods_de_ataque(_ch("Kaelen"), _ch("Orc"), True)
    assert mods["vantagem"]
    for sh, e in mods["gastar"]:
        td._gastar_efeito(sh, e)
    assert not td._mods_de_ataque(_ch("Kaelen"), _ch("Orc"), True)["vantagem"]


def test_ajudar_recusa_aliado_e_outra_zona_sem_gastar(luta):
    r = _acao("help", "Alden", "Kaelen")
    assert not r["ok"]
    assert not memory.campaign["combat_state"]["turn_economy"]["acao_usada"]
    memory.campaign["combat_state"]["posicoes"]["orc"] = "Sacada"
    assert not _acao("help", "Alden", "Orc")["ok"]


def test_esconder_se(luta, monkeypatch):
    monkeypatch.setattr(random, "randint", lambda a, b: 20)
    r = _acao("hide", "Alden")
    assert r["ok"] and "ESCONDIDO" in r["message"]
    assert "Escondido" in _conds("Alden")


def test_agarrar_prende_e_solta_quando_quem_agarra_sai(luta, monkeypatch):
    _sequencia(monkeypatch, [18, 2, 3])
    r = _acao("grapple", "Alden", "Orc")
    assert r["ok"] and "AGARRADO" in r["message"], r["message"]
    assert "Agarrado" in _conds("Orc")
    # O orc agarrado não anda atrás de Kaelen.
    memory.campaign["combat_state"]["posicoes"]["kaelen"] = "Sacada"
    texto, pode = td._npc_aproximar("Orc", "Kaelen")
    assert not pode and td._zona_de("Orc") == "Pátio"
    # Alden sai da zona: o orc fica livre.
    _vez("Alden")
    monkeypatch.setattr(random, "randint", lambda a, b: 1)
    td.combat_action("move", actor="Alden", target="Portão")
    assert "Agarrado" not in _conds("Orc")


def test_agarrar_que_falha_nao_prende(luta, monkeypatch):
    _sequencia(monkeypatch, [2, 18, 3])
    r = _acao("grapple", "Alden", "Orc")
    assert r["ok"] and "escapa" in r["message"]
    assert "Agarrado" not in _conds("Orc")


def test_escapar(luta, monkeypatch):
    _ch("Kaelen")["sheet"]["condicoes"] = [{"nome": "Agarrado", "duracao": None, "por": "Orc"}]
    _sequencia(monkeypatch, [19, 5, 4])
    r = _acao("escape", "Kaelen")
    assert r["ok"] and "livre" in r["message"]
    assert not _conds("Kaelen")


def test_derrubar_e_afastar(luta, monkeypatch):
    _sequencia(monkeypatch, [18, 2, 3])
    assert "CAÍDO" in _acao("shove", "Alden", "Orc", "derrubar")["message"]
    assert "Caído" in _conds("Orc")
    _sequencia(monkeypatch, [18, 2, 3])
    r = _acao("shove", "Alden", "Orc", "afastar")
    assert r["ok"] and td._zona_de("Orc") in ("Portão", "Sacada")


def test_afastar_sem_zonas_e_recusado_sem_gastar(luta):
    memory.campaign["combat_state"].pop("zonas")
    r = _acao("shove", "Alden", "Orc", "afastar")
    assert not r["ok"] and not memory.campaign["combat_state"]["turn_economy"]["acao_usada"]


def test_ataque_preparado_dispara_quando_o_alvo_age(luta, monkeypatch):
    assert _acao("ready", "Alden", "Orc")["ok"]
    _vez("Orc")
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda *a, **k: (15, "d20=15"))
    saida = td._executar_turno_npc("Orc")
    assert "dispara o ataque preparado" in saida, saida
    # A reação da rodada 1 foi gasta (o turno do orc fecha a rodada).
    assert _ch("Alden")["sheet"]["reacao_rodada"] == 1
    assert not memory.campaign["combat_state"]["preparadas"]


def test_preparado_contra_o_primeiro_que_chega(luta, monkeypatch):
    cs = memory.campaign["combat_state"]
    cs["posicoes"]["orc"] = "Sacada"
    assert _acao("ready", "Alden")["ok"]
    _vez("Orc")
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda *a, **k: (15, "d20=15"))
    saida = td._executar_turno_npc("Orc")
    assert "dispara o ataque preparado" in saida, saida


def test_preparado_acaba_no_proximo_turno_de_quem_preparou(luta):
    _acao("ready", "Alden", "Orc")
    _vez("Alden")
    assert not memory.campaign["combat_state"]["preparadas"]


def test_contido_nao_avanca_na_ia(luta):
    cs = memory.campaign["combat_state"]
    cs["posicoes"]["kaelen"] = "Sacada"
    _ch("Orc")["sheet"]["condicoes"] = [{"nome": "Contido", "duracao": None}]
    texto, pode = td._npc_aproximar("Orc", "Kaelen")
    assert not pode and "não sai da zona" in texto and td._zona_de("Orc") == "Pátio"
