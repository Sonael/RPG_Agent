"""
test_invocacoes.py

As invocações eram narrativas: a Arma Espiritual do clérigo não atacava, os
lobos do Conjurar Animais não entravam na luta, o familiar e a montaria não
existiam para o motor. E nenhuma magia podia ser conjurada como ritual — a
Detectar Magia e o Convocar Familiar custavam mana sempre.
"""
import random

import pytest

from rpg import criaturas, memory, resolucao, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _ch(nome):
    return memory.campaign["characters"].get(memory.char_key(nome))


def _hab(nome, custo=2):
    # Como o jogo grava: a descrição de magia começa pela escola.
    return {"nome": nome, "custo_mana": custo, "dado": "", "descricao": "[Conjuração] ",
            "nivel_magia": (resolucao._magia_srd({"nome": nome}) or {}).get("nivel", 1)}


def _vez(nome):
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index(nome)
    cs["turn_token"] = int(cs.get("turn_token", 0) or 0) + 1
    td._reset_turn_economy(cs)


def _usar(ator, hab, alvo="", modo=""):
    _vez(ator)
    return td.combat_action("ability", actor=ator, ability=hab, target=alvo, weapon=modo)


MAGIAS = [_hab("Spiritual Weapon", 3), _hab("Conjure Animals", 5), _hab("Find Familiar", 2),
          _hab("Find Steed", 3), _hab("Animate Dead", 5), _hab("Bless", 2),
          _hab("Detect Magic", 2), _hab("Cure Wounds", 2)]


@pytest.fixture
def luta(campanha, povoar):
    povoar(criar_ficha("Kaelen", grupo=True, classe="clérigo", nivel=9, sabedoria=16, mana=60, vida=40,
                       habilidades=[dict(h) for h in MAGIAS]),
           criar_ficha("Orc", vida=200, raca="orc", arma="machado grande", ca=10))
    # Componentes de preço (a bolsa de componentes não cobre): o motor cobra.
    _ch("Kaelen")["inventario"].append({"nome": "Incenso e ervas", "qtd": 5})
    iniciar_combate(["Kaelen", "Orc"])
    cs = memory.campaign["combat_state"]
    cs["zonas"] = ["Portão", "Pátio"]
    cs["posicoes"] = {"kaelen": "Pátio", "orc": "Pátio"}
    _vez("Kaelen")
    return memory.campaign


@pytest.fixture
def cidade(campanha, povoar):
    povoar(criar_ficha("Mira", grupo=True, classe="mago", nivel=5, mana=27, vida=30,
                       habilidades=[dict(h) for h in MAGIAS]),
           criar_ficha("Brann", grupo=True, classe="paladino", nivel=5, mana=10,
                       habilidades=[_hab("Find Steed", 3), _hab("Detect Magic", 2)]),
           criar_ficha("Orc", vida=60, raca="orc", arma="machado grande", ca=10))
    # Componentes de preço (a bolsa de componentes não cobre): o motor cobra.
    _ch("Mira")["inventario"].append({"nome": "Incenso e ervas", "qtd": 5})
    return memory.campaign


# ---------------------------------------------------------------------------
# Arma Espiritual
# ---------------------------------------------------------------------------

def test_arma_espiritual_ataca_e_depois_reataca_sem_mana(luta, monkeypatch):
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda *a, **k: (18, "d20=18"))
    r = _usar("Kaelen", "Spiritual Weapon", "Orc")
    assert r["ok"] and "arma espectral surge" in r["message"], r["message"]
    assert _ch("Kaelen")["sheet"]["mana_atual"] == 57
    assert _ch("Orc")["sheet"]["vida_atual"] < 200
    assert "já está em campo" in resolucao.como_resolve(_hab("Spiritual Weapon", 3), _ch("Kaelen"))["texto"]
    vida = _ch("Orc")["sheet"]["vida_atual"]
    r = _usar("Kaelen", "Spiritual Weapon", "Orc")
    assert r["ok"] and "ataca de novo" in r["message"], r["message"]
    assert _ch("Kaelen")["sheet"]["mana_atual"] == 57
    assert _ch("Orc")["sheet"]["vida_atual"] < vida


def test_arma_espiritual_no_quarto_circulo(luta, monkeypatch):
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda *a, **k: (18, "d20=18"))
    _usar("Kaelen", "Spiritual Weapon", "Orc", "c4")
    assert any(e.get("arma_espiritual") == "2d8" for e in td._efeitos_de(_ch("Kaelen")))


def test_arma_espiritual_acaba_com_o_combate(luta, monkeypatch):
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda *a, **k: (18, "d20=18"))
    _usar("Kaelen", "Spiritual Weapon", "Orc")
    td.end_combat()
    assert not any(e.get("arma_espiritual") for e in td._efeitos_de(_ch("Kaelen")))


# ---------------------------------------------------------------------------
# Conjurar Animais
# ---------------------------------------------------------------------------

def test_conjurar_animais_poe_os_lobos_na_luta(luta):
    assert not _usar("Kaelen", "Conjure Animals")["ok"]               # sem escolha
    r = _usar("Kaelen", "Conjure Animals", modo="lobo:8")
    assert r["ok"], r["message"]
    ordem = memory.campaign["combat_state"]["initiative_order"]
    lobos = [n for n in ordem if n.startswith("Lobo de Kaelen")]
    assert len(lobos) == 8
    assert all(memory.lado_no_combate(_ch(n)) == "aliado" for n in lobos)
    assert td._zona_de(lobos[0]) == "Pátio"


def test_lobos_somem_quando_a_concentracao_cai(luta):
    _usar("Kaelen", "Conjure Animals", modo="lobo atroz:2")
    td._break_concentration(_ch("Kaelen"), "teste")
    ordem = memory.campaign["combat_state"]["initiative_order"]
    assert not [n for n in ordem if "Lobo Atroz" in n]
    assert _ch("Lobo Atroz de Kaelen 1") is None


def test_outra_concentracao_dispensa_os_lobos(luta):
    _usar("Kaelen", "Conjure Animals", modo="urso polar:1")
    assert _ch("Urso-Polar de Kaelen")
    _usar("Kaelen", "Bless", "Kaelen")
    assert _ch("Urso-Polar de Kaelen") is None


def test_fim_do_combate_dispensa_os_lobos(luta):
    _usar("Kaelen", "Conjure Animals", modo="lobo:8")
    td.end_combat()
    assert not [c for c in memory.campaign["characters"] if c.startswith("lobo de kaelen")]


def test_lobo_que_cai_sai_da_ordem(luta):
    _usar("Kaelen", "Conjure Animals", modo="urso pardo:2")
    td._mark_at_zero_hp(_ch("Urso-Pardo de Kaelen 1"), "Orc")
    td.combat_snapshot()
    assert "Urso-Pardo de Kaelen 1" not in memory.campaign["combat_state"]["initiative_order"]
    assert "Urso-Pardo de Kaelen 2" in memory.campaign["combat_state"]["initiative_order"]


def test_lobo_age_como_aliado(luta, monkeypatch):
    _usar("Kaelen", "Conjure Animals", modo="lobo:8")
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda *a, **k: (18, "d20=18"))
    _vez("Lobo de Kaelen 1")
    saida = td._executar_turno_npc("Lobo de Kaelen 1")
    assert "Orc" in saida and "mordida" in saida.lower(), saida


# ---------------------------------------------------------------------------
# Familiar, montaria, mortos animados
# ---------------------------------------------------------------------------

def test_familiar_leva_uma_hora_e_nao_se_conjura_na_luta(luta):
    r = _usar("Kaelen", "Find Familiar", modo="coruja:1")
    assert not r["ok"] and "1 hora" in r["message"]


def test_familiar_fora_do_combate_e_o_relogio(cidade):
    hora = td._agora_em_horas()
    r = td.conjurar_fora_de_combate("Mira", "Find Familiar", modo="coruja:1")
    assert r["ok"], r["message"]
    assert _ch("Coruja de Mira")["invocacao"]["persistente"]
    assert td._agora_em_horas() == hora + 1
    # Um familiar só: o novo substitui.
    td.conjurar_fora_de_combate("Mira", "Find Familiar", modo="gato:1")
    assert _ch("Coruja de Mira") is None and _ch("Gato de Mira")


def test_familiar_como_ritual_nao_gasta_mana(cidade):
    r = td.conjurar_fora_de_combate("Mira", "Find Familiar", modo="corvo:1", ritual=True)
    assert r["ok"] and "ritual" in r["message"].lower()
    assert _ch("Mira")["sheet"]["mana_atual"] == 27


def test_ritual_exige_classe_e_magia_ritual(cidade):
    r = td.conjurar_fora_de_combate("Brann", "Detect Magic", ritual=True)
    assert not r["ok"] and "ritual" in r["message"]
    r = td.conjurar_fora_de_combate("Mira", "Cure Wounds", "Mira", ritual=True)
    assert not r["ok"]


def test_familiar_entra_na_luta_com_o_dono_e_ajuda(cidade):
    td.conjurar_fora_de_combate("Mira", "Find Familiar", modo="coruja:1")
    td.roll_initiative("Mira, Orc")
    ordem = memory.campaign["combat_state"]["initiative_order"]
    assert "Coruja de Mira" in ordem
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = ordem.index("Coruja de Mira")
    saida = td._executar_turno_npc("Coruja de Mira")
    assert "ajuda" in saida, saida
    assert td._mods_de_ataque(_ch("Mira"), _ch("Orc"), True)["vantagem"]


def test_montaria(cidade):
    r = td.conjurar_fora_de_combate("Brann", "Find Steed", modo="cavalo de guerra:1")
    assert r["ok"], r["message"]
    assert _ch("Cavalo de Guerra de Brann")["sheet"]["ataques"][0]["nome"] == "cascos"


def test_animar_mortos_dura_24_horas(cidade):
    td.conjurar_fora_de_combate("Mira", "Animate Dead", modo="esqueleto:1")
    assert _ch("Esqueleto de Mira")
    td.advance_time(23, "espera")
    assert _ch("Esqueleto de Mira")
    saida = td.advance_time(2, "espera")
    assert _ch("Esqueleto de Mira") is None and "desaparece" in saida


def test_grimorio_mostra_formas_e_ritual(cidade):
    snap = td.grimoire_snapshot("Mira")
    fam = next(m for m in snap["personagem"]["conhecidas"] if m["nome"] == "Find Familiar")
    assert fam["ritual"] and fam["pode_ritual"]
    assert {m["id"] for m in fam["modos"]} >= {"coruja:1", "gato:1"}
    snap = td.grimoire_snapshot("Brann")
    dm = next(m for m in snap["personagem"]["conhecidas"] if m["nome"] == "Detect Magic")
    assert dm["ritual"] and not dm["pode_ritual"]
