"""
test_encantos_e_condicoes.py

"Como funciona Enfeitiçar Pessoa no combate? E fora dele?" Medido numa
partida: o clérigo enfeitiçou o orc, o motor marcou "Enfeitiçado" — e no
turno seguinte o orc atacou o clérigo e o derrubou. A condição não fazia
nada, não acabava em 1 hora (nem com o fim da luta), e fora do combate o
guarda enfeitiçado só existia se o Mestre lembrasse.

A varredura achou o mesmo em outras condições: o orc Paralisado pelo
Imobilizar Pessoa atacava normalmente, o Banido continuava na luta, o Confuso
agia como qualquer um, e "contido" (Teia) nem existia na tabela do motor.
"""
import random

import pytest

from rpg import encantos, memory, resolucao, tools, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _ch(nome):
    return memory.campaign["characters"][memory.char_key(nome)]


def _hab(nome, custo=2, nivel=1):
    return {"nome": nome, "custo_mana": custo, "dado": "", "descricao": "", "nivel_magia": nivel}


def _falha(monkeypatch):
    """Toda salvaguarda falha (e registra se pediram vantagem)."""
    pedidos = []

    def falhar(alvo, atributo, cd, vantagem=False, desvantagem=False, contra=""):
        pedidos.append({"alvo": alvo.get("name"), "vantagem": vantagem})
        return False, f"salvaguarda de {atributo[:3].upper()}: 1 vs CD {cd}"
    monkeypatch.setattr(td, "_rolar_salvaguarda", falhar)
    return pedidos


def _vez(nome):
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index(nome)
    td._reset_turn_economy(cs)


@pytest.fixture
def luta(campanha, povoar):
    povoar(criar_ficha("Kaelen", grupo=True, classe="clérigo", nivel=3, sabedoria=16, vida=30,
                       habilidades=[_hab("Charm Person"), _hab("Hold Person", nivel=2),
                                    _hab("Banishment", nivel=4), _hab("Confusion", nivel=4),
                                    _hab("Suggestion", nivel=2)]),
           criar_ficha("Alden", grupo=True, vida=40),
           criar_ficha("Orc", vida=40, raca="orc", arma="machado grande"))
    _ch("Kaelen")["sheet"]["mana_atual"] = _ch("Kaelen")["sheet"]["mana_max"] = 40
    iniciar_combate(["Kaelen", "Orc", "Alden"])
    td._reset_turn_economy(memory.campaign["combat_state"])
    return memory.campaign


# ---------------------------------------------------------------------------
# 1. Enfeitiçar Pessoa no combate
# ---------------------------------------------------------------------------

def test_enfeiticado_nao_ataca_quem_o_enfeiticou(luta, monkeypatch):
    _falha(monkeypatch)
    r = td.combat_action("ability", actor="Kaelen", ability="Charm Person", target="Orc")
    assert r["ok"] and "ENFEITIÇADO" in r["message"], r["message"]
    monkeypatch.undo()
    td.combat_action("end_turn", actor="Kaelen")
    vida_kaelen = _ch("Kaelen")["sheet"]["vida_atual"]
    random.seed(4)
    turno = td.combat_action("enemy")["message"]
    assert "Kaelen" not in turno.split("\n")[0], turno
    assert _ch("Kaelen")["sheet"]["vida_atual"] == vida_kaelen


def test_sem_outro_alvo_o_enfeiticado_passa_a_vez(campanha, povoar, monkeypatch):
    povoar(criar_ficha("Kaelen", grupo=True, classe="clérigo", sabedoria=16,
                       habilidades=[_hab("Charm Person")]),
           criar_ficha("Orc", vida=40, raca="orc"))
    iniciar_combate(["Kaelen", "Orc"])
    _falha(monkeypatch)
    td.combat_action("ability", actor="Kaelen", ability="Charm Person", target="Orc")
    monkeypatch.undo()
    td.combat_action("end_turn", actor="Kaelen")
    turno = td.combat_action("enemy")["message"]
    assert "não ataca" in turno, turno


def test_o_motor_recusa_o_ataque_do_enfeiticado(luta, monkeypatch):
    _falha(monkeypatch)
    td.combat_action("ability", actor="Kaelen", ability="Charm Person", target="Orc")
    assert td.attack_roll("Orc", "Kaelen", "machado", 12, _skip_turn_check=True).startswith("Erro:")


def test_o_encanto_quebra_quando_o_grupo_fere(luta, monkeypatch):
    _falha(monkeypatch)
    td.combat_action("ability", actor="Kaelen", ability="Charm Person", target="Orc")
    monkeypatch.undo()
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda a, d: (18, "d20=18"))
    _vez("Alden")
    saida = td.combat_action("attack", actor="Alden", target="Orc")["message"]
    assert "acabou" in saida and encantos.ativo(_ch("Orc")) is None


def test_lutando_contra_o_grupo_a_salvaguarda_tem_vantagem(luta, monkeypatch):
    pedidos = _falha(monkeypatch)
    td.combat_action("ability", actor="Kaelen", ability="Charm Person", target="Orc")
    assert pedidos and pedidos[-1]["vantagem"] is True


def test_o_encanto_dura_uma_hora_e_sobrevive_a_luta(luta, monkeypatch):
    _falha(monkeypatch)
    td.combat_action("ability", actor="Kaelen", ability="Charm Person", target="Orc")
    td.end_combat()
    assert encantos.ativo(_ch("Orc"))
    td.advance_time(2, "espera")
    assert encantos.ativo(_ch("Orc")) is None
    assert not [c for c in _ch("Orc")["sheet"]["condicoes"] if c.get("encanto")]


# ---------------------------------------------------------------------------
# 2. Fora do combate
# ---------------------------------------------------------------------------

@pytest.fixture
def cidade(campanha, povoar):
    povoar(criar_ficha("Kaelen", grupo=True, classe="clérigo", nivel=3, sabedoria=16,
                       habilidades=[_hab("Charm Person"), _hab("Suggestion", nivel=2)]))
    _ch("Kaelen")["sheet"]["mana_atual"] = _ch("Kaelen")["sheet"]["mana_max"] = 20
    # O guarda do portão não tem ficha de regras.
    campanha["characters"]["guarda"] = {"name": "Guarda", "status": "vivo", "description": "guarda",
                                        "traits": "", "notes": "", "atitude": 0}
    return campanha


def test_enfeiticar_o_guarda_sem_ficha(cidade, monkeypatch):
    monkeypatch.setattr(random, "randint", lambda a, b: a)       # d20 = 1: falha
    r = td.conjurar_fora_de_combate("Kaelen", "Charm Person", "Guarda")
    assert r["ok"] and "ENFEITIÇADO" in r["message"], r
    assert "Não chame use_ability de novo" in r["para_o_mestre"]
    g = _ch("Guarda")
    assert tools.atitude_de(g) == encantos.ATITUDE_ENFEITICADO
    assert "Enfeitiçado por Kaelen" in tools.get_character("Guarda")
    assert _ch("Kaelen")["sheet"]["mana_atual"] == 18


def test_quando_acaba_o_guarda_sabe(cidade, monkeypatch):
    monkeypatch.setattr(random, "randint", lambda a, b: a)
    td.conjurar_fora_de_combate("Kaelen", "Charm Person", "Guarda")
    monkeypatch.undo()
    saida = td.advance_time(2, "conversa")
    assert "sabe que foi enfeitiçado" in saida
    assert tools.atitude_de(_ch("Guarda")) == encantos.PERCEBEU


def test_vantagem_no_teste_social(cidade, monkeypatch):
    monkeypatch.setattr(random, "randint", lambda a, b: a)
    td.conjurar_fora_de_combate("Kaelen", "Charm Person", "Guarda")
    monkeypatch.setattr(random, "randint", lambda a, b: 19)      # o segundo d20
    saida = td.social_check("Kaelen", "persuasão", 15, 3, "Guarda")
    assert "Vantagem" in saida and "d20=19" in saida


def test_enfeiticar_pessoa_nao_pega_em_besta(cidade):
    cidade["characters"]["lobo"] = criar_ficha("Lobo", tipo="beast", raca="lobo")
    r = td.conjurar_fora_de_combate("Kaelen", "Charm Person", "Lobo")
    assert not r["ok"] and "humanoides" in r["message"]
    assert _ch("Kaelen")["sheet"]["mana_atual"] == 20


def test_em_combate_conjurar_fora_e_recusado(luta):
    r = td.conjurar_fora_de_combate("Kaelen", "Charm Person", "Orc")
    assert not r["ok"] and "tela de combate" in r["message"]


def test_sugestao_rola_o_teste_e_o_mestre_narra(cidade, monkeypatch):
    monkeypatch.setattr(random, "randint", lambda a, b: a)
    r = td.conjurar_fora_de_combate("Kaelen", "Suggestion", "Guarda")
    assert r["ok"] and "falhou: o efeito vale" in r["message"]
    assert "o Mestre narra" in r["message"]


def test_alvos_aqui_primeiro(cidade):
    from rpg import locais  # noqa: F401
    cidade["current_location"] = "Portão Norte"
    cidade["characters"]["guarda"]["local"] = "Portão Norte"
    cidade["characters"]["ferreiro"] = {"name": "Ferreiro", "status": "vivo", "local": "Forja"}
    alvos = td.alvos_fora_de_combate("Kaelen")
    assert "Guarda" in alvos["aqui"] and "Kaelen" in alvos["aqui"]
    assert "Ferreiro" in alvos["outros"]


# ---------------------------------------------------------------------------
# 3. As outras condições que não faziam nada
# ---------------------------------------------------------------------------

def test_paralisado_nao_age_e_e_atacado_com_vantagem(luta, monkeypatch):
    _falha(monkeypatch)
    td.combat_action("ability", actor="Kaelen", ability="Hold Person", target="Orc")
    monkeypatch.undo()
    assert td._impedido_de_agir(_ch("Orc")) == "Paralisado"
    td.combat_action("end_turn", actor="Kaelen")
    vida = _ch("Alden")["sheet"]["vida_atual"], _ch("Kaelen")["sheet"]["vida_atual"]
    monkeypatch.setattr(td, "_rolar_salvaguarda", lambda *a, **k: (False, "falhou"))
    turno = td.combat_action("enemy")["message"]
    assert "Paralisado" in turno and "não age" in turno
    assert (_ch("Alden")["sheet"]["vida_atual"], _ch("Kaelen")["sheet"]["vida_atual"]) == vida
    mods = td._has_condition_effect(_ch("Orc"), "defense_disadvantage")
    assert mods, "ataques contra o paralisado têm vantagem"


def test_paralisia_acaba_com_a_salvaguarda_de_fim_de_turno(luta, monkeypatch):
    _falha(monkeypatch)
    td.combat_action("ability", actor="Kaelen", ability="Hold Person", target="Orc")
    monkeypatch.setattr(td, "_rolar_salvaguarda", lambda *a, **k: (True, "passou"))
    linhas = td._fim_do_turno("Orc", 999)
    assert any("se livra de Paralisado" in l for l in linhas)
    assert not td._impedido_de_agir(_ch("Orc"))


def test_paralisia_cai_com_a_concentracao(luta, monkeypatch):
    _falha(monkeypatch)
    td.combat_action("ability", actor="Kaelen", ability="Hold Person", target="Orc")
    td._break_concentration(_ch("Kaelen"), "dano")
    assert not td._impedido_de_agir(_ch("Orc"))


def test_personagem_paralisado_so_encerra_o_turno(luta):
    _ch("Alden")["sheet"]["condicoes"] = [{"nome": "Paralisado", "duracao": None}]
    _vez("Alden")
    r = td.combat_action("attack", actor="Alden", target="Orc")
    assert not r["ok"] and "Paralisado" in r["message"]
    assert td.combat_action("end_turn", actor="Alden")["ok"]
    assert td._combatant_snapshot("Alden")["impedido"] == "Paralisado"


def test_banido_some_da_luta(luta, monkeypatch):
    _falha(monkeypatch)
    r = td.combat_action("ability", actor="Kaelen", ability="Banishment", target="Orc")
    assert r["ok"], r["message"]
    assert td.attack_roll("Alden", "Orc", "espada", 8, _skip_turn_check=True).startswith("Erro:")


def test_confuso_sorteia_o_turno(luta, monkeypatch):
    _ch("Orc")["sheet"]["condicoes"] = [{"nome": "Confuso", "duracao": None}]
    _vez("Orc")
    monkeypatch.setattr(random, "randint", lambda a, b: 4 if b == 10 else a)
    turno = td.combat_action("enemy")["message"]
    assert "Confuso" in turno and "não faz nada" in turno


def test_contido_nao_sai_da_zona(luta):
    td.set_battlefield("Portão, Pátio")
    for n, z in (("Kaelen", "Portão"), ("Alden", "Portão"), ("Orc", "Pátio")):
        td._por_zona(n, z)
    _ch("Alden")["sheet"]["condicoes"] = [{"nome": "Contido", "duracao": None}]
    _vez("Alden")
    r = td.combat_action("move", actor="Alden", target="Pátio")
    assert not r["ok"] and "Contido" in r["message"]


# ---------------------------------------------------------------------------
# 4. O cartão diz a verdade
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nome, tipo, trecho", [
    ("Charm Person", "efeito", "Enfeitiçado por 1h"),
    ("Hold Person", "motor", "Paralisado"),
    ("Web", "motor", "não sai da zona"),
    ("Suggestion", "narrativa", "salvaguarda"),
    ("Polymorph", "efeito", "fera"),
    ("True Polymorph", "narrativa", "Mestre"),
])
def test_o_cartao_diz_o_que_a_magia_faz(nome, tipo, trecho):
    r = resolucao.como_resolve({"nome": nome, "custo_mana": 2})
    assert r["tipo"] == tipo and trecho in r["texto"], r
