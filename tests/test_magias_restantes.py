"""
test_magias_restantes.py

A segunda leva das magias de combate que caíam em "o Mestre decide":
Dissipar Magia, Proteção contra a Morte, Proteção contra Energia,
Movimentação Livre, Porta Dimensional, Palavra de Poder: Matar, Dança
Irresistível, Esfera Resiliente, Labirinto, Reviver os Mortos, Ressurreição,
Escudo de Fogo, Forma Gasosa, Levitação, Lufada de Vento, Palavra Divina,
Telecinésia, Aura Sagrada, Presciência, Globo de Invulnerabilidade, Campo
Antimagia — e as invocações que faltavam.
"""
import random

import pytest

from rpg import criaturas, memory, resolucao, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _ch(nome):
    return memory.campaign["characters"].get(memory.char_key(nome))


def _hab(nome, custo=5):
    return {"nome": nome, "custo_mana": custo, "dado": "", "descricao": "[Magia] ",
            "nivel_magia": (resolucao._magia_srd({"nome": nome}) or {}).get("nivel", 1)}


def _vez(nome):
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index(nome)
    cs["turn_token"] = int(cs.get("turn_token", 0) or 0) + 1
    td._reset_turn_economy(cs)


def _usar(ator, hab, alvo="", modo=""):
    _vez(ator)
    return td.combat_action("ability", actor=ator, ability=hab, target=alvo, weapon=modo)


def _salva(monkeypatch, passa):
    monkeypatch.setattr(td, "_rolar_salvaguarda", lambda *a, **k: (passa, "salvaguarda: " + ("passou" if passa else "falhou")))


MAGIAS = ["Dispel Magic", "Death Ward", "Protection from Energy", "Freedom of Movement", "Dimension Door",
          "Power Word Kill", "Irresistible Dance", "Resilient Sphere", "Maze", "Raise Dead", "Resurrection",
          "True Resurrection", "Fire Shield", "Gaseous Form", "Levitate", "Gust of Wind", "Divine Word",
          "Telekinesis", "Holy Aura", "Foresight", "Globe of Invulnerability", "Antimagic Field",
          "Conjure Minor Elementals", "Conjure Woodland Beings", "Conjure Fey", "Conjure Celestial",
          "Giant Insect", "Animate Objects", "Create Undead", "Planar Ally", "Hold Person", "Fire Bolt",
          "Bless", "Fireball", "Cure Wounds"]


@pytest.mark.parametrize("nome", MAGIAS[:30])
def test_cartao_diz_que_o_motor_aplica(nome):
    assert resolucao.como_resolve(_hab(nome))["tipo"] == "efeito", nome


@pytest.fixture
def luta(campanha, povoar):
    povoar(criar_ficha("Mira", grupo=True, classe="mago", nivel=20, inteligencia=20, mana=200, vida=60,
                       habilidades=[_hab(n) for n in MAGIAS]),
           criar_ficha("Alden", grupo=True, vida=60, ca=10),
           criar_ficha("Orc", vida=80, raca="orc", arma="machado grande", ca=10),
           criar_ficha("Ogro", vida=150, raca="ogro", arma="clava grande", ca=10))
    _ch("Mira")["sheet"]["mana_atual"] = _ch("Mira")["sheet"]["mana_max"] = 200
    # Componentes de preço (a bolsa de componentes não cobre): o motor cobra.
    _ch("Mira")["inventario"] += [{"nome": "Relicário sagrado", "qtd": 1}, {"nome": "Pó de diamante", "qtd": 3}]
    iniciar_combate(["Mira", "Alden", "Orc", "Ogro"])
    cs = memory.campaign["combat_state"]
    cs["zonas"] = ["Portão", "Pátio", "Sacada"]
    cs["posicoes"] = {"mira": "Portão", "alden": "Pátio", "orc": "Pátio", "ogro": "Pátio"}
    _vez("Mira")
    return memory.campaign


# ---------------------------------------------------------------------------
# Dissipar Magia
# ---------------------------------------------------------------------------

def test_dissipar_tira_imobilizar_e_bencao(luta, monkeypatch):
    _salva(monkeypatch, False)
    _usar("Mira", "Hold Person", "Orc")
    assert td._impedido_de_agir(_ch("Orc"))
    _usar("Mira", "Bless", "Alden")
    _usar("Mira", "Dispel Magic", "Orc")
    assert not td._impedido_de_agir(_ch("Orc"))


def test_dissipar_acima_do_circulo_e_teste(luta, monkeypatch):
    _salva(monkeypatch, False)
    _ch("Alden")["sheet"]["condicoes"].append({"nome": "No Labirinto", "magia": "Maze", "duracao": None})
    monkeypatch.setattr(random, "randint", lambda a, b: 1)
    r = _usar("Mira", "Dispel Magic", "Alden")
    assert "resiste" in r["message"] and td._impedido_de_agir(_ch("Alden"))
    _ch("Mira")["sheet"]["mana_atual"] = 200
    r = _usar("Mira", "Dispel Magic", "Alden", "c8")
    assert not td._impedido_de_agir(_ch("Alden")), r["message"]


def test_dissipar_dispensa_invocacao(luta):
    _usar("Mira", "Giant Insect", modo="vespa gigante:5")
    vespa = _ch("Vespa Gigante de Mira 1")
    # Inseto Gigante é do 4º círculo: no 4º, sem teste.
    _usar("Mira", "Dispel Magic", "Vespa Gigante de Mira 1", "c4")
    assert _ch("Vespa Gigante de Mira 1") is None and vespa


# ---------------------------------------------------------------------------
# Defesa
# ---------------------------------------------------------------------------

def test_protecao_contra_a_morte_segura_em_1_e_atravessa_o_combate(luta):
    _usar("Mira", "Death Ward", "Alden")
    td.end_combat()
    assert any(e.get("protecao_morte") for e in td._efeitos_de(_ch("Alden")))
    res = td._apply_damage(_ch("Alden"), 500, "fire", source_name="Orc")
    assert res["hp_depois"] == 1 and _ch("Alden")["sheet"]["vida_atual"] == 1
    assert not any(e.get("protecao_morte") for e in td._efeitos_de(_ch("Alden")))


def test_protecao_contra_energia(luta):
    assert not _usar("Mira", "Protection from Energy", "Alden")["ok"]
    _usar("Mira", "Protection from Energy", "Alden", "fire")
    assert td._apply_damage(_ch("Alden"), 20, "fire", source_name="Orc")["dano"] == 10


def test_movimentacao_livre(luta, monkeypatch):
    _ch("Alden")["sheet"]["condicoes"].append({"nome": "Agarrado", "duracao": None, "por": "Orc"})
    _usar("Mira", "Freedom of Movement", "Alden")
    assert not _ch("Alden")["sheet"]["condicoes"]
    # Imobilizar num aliado abre a bandeja de dados do jogador; num NPC o
    # motor rola. A imunidade vale para quem estiver com a magia.
    _salva(monkeypatch, False)
    _usar("Mira", "Freedom of Movement", "Ogro")
    r = _usar("Mira", "Hold Person", "Ogro")
    assert "imune" in r["message"] and not td._impedido_de_agir(_ch("Ogro")), r["message"]


def test_escudo_de_fogo_queima_quem_acerta(luta, monkeypatch):
    _usar("Mira", "Fire Shield", modo="quente")
    memory.campaign["combat_state"]["posicoes"]["mira"] = "Pátio"
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda *a, **k: (18, "d20=18"))
    saida = td.attack_roll("Orc", "Mira", "machado grande", 12, end_turn=False, _skip_turn_check=True)
    assert "Escudo de Fogo" in saida and _ch("Orc")["sheet"]["vida_atual"] < 80, saida
    assert td._apply_damage(_ch("Mira"), 10, "cold", source_name="Orc")["dano"] == 5


def test_esfera_resiliente_tira_da_luta(luta, monkeypatch):
    _salva(monkeypatch, False)
    _usar("Mira", "Resilient Sphere", "Orc")
    assert td._impedido_de_agir(_ch("Orc"))
    assert td.attack_roll("Alden", "Orc", "espada longa", 8, end_turn=False,
                          _skip_turn_check=True).startswith("Erro")


def test_aura_sagrada_e_presciencia(luta):
    _usar("Mira", "Holy Aura")
    assert td._mods_de_ataque(_ch("Orc"), _ch("Alden"), True)["desvantagem"]
    td.end_combat()
    r = td.conjurar_fora_de_combate("Mira", "Foresight", "Alden")
    assert r["ok"], r["message"]
    iniciar_combate(["Mira", "Alden", "Orc"])
    assert td._mods_de_ataque(_ch("Alden"), _ch("Orc"), True)["vantagem"]


def test_globo_barra_magia_de_fora(luta, monkeypatch):
    memory.campaign["combat_state"]["posicoes"]["alden"] = "Portão"
    _usar("Mira", "Globe of Invulnerability")
    _ch("Orc")["habilidades"] = [_hab("Fire Bolt", 0), _hab("Hold Person", 3)]
    _ch("Orc")["sheet"]["mana_atual"] = 20
    _vez("Orc")
    r = td.use_ability("Orc", "Hold Person", "Alden", _skip_turn_check=True)
    assert r.startswith("Erro") and "Globo" in r


def test_campo_antimagia_impede_conjurar_ali(luta):
    _usar("Mira", "Antimagic Field")
    _ch("Orc")["habilidades"] = [_hab("Fire Bolt", 0)]
    _vez("Orc")
    assert "Antimagia" in td.use_ability("Orc", "Fire Bolt", "Mira", _skip_turn_check=True)
    # O campo acompanha Mira: ela vai para o Pátio, e lá ninguém conjura.
    memory.campaign["combat_state"]["posicoes"]["mira"] = "Pátio"
    assert td._area_do_tipo("Orc", "antimagia")


# ---------------------------------------------------------------------------
# Controle
# ---------------------------------------------------------------------------

def test_palavra_de_poder_matar(luta):
    _ch("Orc")["sheet"]["vida_atual"] = 90
    _usar("Mira", "Power Word Kill", "Orc")
    assert _ch("Orc")["status"] == "morto"
    _ch("Mira")["sheet"]["circulos_altos_usados"] = []
    r = _usar("Mira", "Power Word Kill", "Ogro")
    assert "mais de 100" in r["message"] and _ch("Ogro")["status"] != "morto"


def test_danca_irresistivel(luta):
    _usar("Mira", "Irresistible Dance", "Orc")
    assert td._has_condition_effect(_ch("Orc"), "defense_disadvantage")
    assert td._has_condition_effect(_ch("Orc"), "attack_disadvantage")


def test_labirinto(luta):
    _usar("Mira", "Maze", "Ogro")
    assert td._impedido_de_agir(_ch("Ogro"))
    c = next(c for c in _ch("Ogro")["sheet"]["condicoes"] if c["nome"] == "No Labirinto")
    assert c["salvaguarda_fim"]["cd"] == 20


def test_levitacao_fora_do_corpo_a_corpo(luta, monkeypatch):
    _salva(monkeypatch, False)
    _usar("Mira", "Levitate", "Orc")
    r = td.attack_roll("Alden", "Orc", "espada longa", 8, end_turn=False, _skip_turn_check=True)
    assert r.startswith("Erro") and "Levitando" in r
    r = td.attack_roll("Orc", "Alden", "machado grande", 12, end_turn=False, _skip_turn_check=True)
    assert r.startswith("Erro")


def test_forma_gasosa(luta):
    _usar("Mira", "Gaseous Form", "Alden")
    assert td._impedido_de_agir(_ch("Alden"))
    assert td._apply_damage(_ch("Alden"), 10, "slashing", source_name="Orc")["dano"] == 5


def test_lufada_empurra_para_longe(luta, monkeypatch):
    _salva(monkeypatch, False)
    _usar("Mira", "Gust of Wind", "Orc")
    assert td._zona_de("Orc") == "Sacada" and td._zona_de("Ogro") == "Sacada"


def test_palavra_divina_pela_vida(luta, monkeypatch):
    _salva(monkeypatch, False)
    memory.campaign["combat_state"]["posicoes"]["mira"] = "Pátio"
    _ch("Orc")["sheet"]["vida_atual"] = 15
    _ch("Ogro")["sheet"]["vida_atual"] = 35
    _usar("Mira", "Divine Word")
    assert _ch("Orc")["status"] == "morto"
    nomes = {c["nome"] for c in _ch("Ogro")["sheet"]["condicoes"]}
    assert nomes == {"Surdo", "Cego"}


def test_telecinesia_segura_e_reusa_sem_mana(luta, monkeypatch):
    monkeypatch.setattr(random, "randint", lambda a, b: 15)
    r = _usar("Mira", "Telekinesis", "Orc", "afastar")
    assert r["ok"] and "CONTIDO" in r["message"], r["message"]
    assert td._zona_de("Orc") == "Sacada"
    mana = _ch("Mira")["sheet"]["mana_atual"]
    r = _usar("Mira", "Telekinesis", "Ogro", "segurar")
    assert r["ok"] and _ch("Mira")["sheet"]["mana_atual"] == mana


# ---------------------------------------------------------------------------
# Movimento, morte
# ---------------------------------------------------------------------------

def test_porta_dimensional_vai_a_qualquer_zona(luta):
    assert _usar("Mira", "Dimension Door", modo="Sacada")["ok"]
    assert td._zona_de("Mira") == "Sacada"


def test_reviver_os_mortos_e_ressurreicao(luta):
    td.end_combat()
    alden = _ch("Alden")
    alden["status"] = "morto"
    alden["sheet"]["vida_atual"] = 0
    alden["sheet"]["morreu_hora"] = td._agora_em_horas() - 100        # há quatro dias
    _ch("Mira")["inventario"] = [{"nome": "Diamante", "qtd": 2}]
    r = td.conjurar_fora_de_combate("Mira", "Raise Dead", "Alden")
    assert r["ok"] and alden["sheet"]["vida_atual"] == 1, r["message"]
    alden["status"] = "morto"
    alden["sheet"]["vida_atual"] = 0
    alden["sheet"]["morreu_hora"] = td._agora_em_horas() - 1000       # há mais de 10 dias
    assert not td.conjurar_fora_de_combate("Mira", "Raise Dead", "Alden")["ok"]
    r = td.conjurar_fora_de_combate("Mira", "Resurrection", "Alden")
    assert r["ok"] and alden["sheet"]["vida_atual"] == alden["sheet"]["vida_max"], r["message"]


# ---------------------------------------------------------------------------
# Invocações
# ---------------------------------------------------------------------------

def test_invocacoes_na_luta(luta):
    _usar("Mira", "Conjure Woodland Beings", modo="satiro:4")
    assert len([n for n in memory.campaign["combat_state"]["initiative_order"] if n.startswith("Sátiro")]) == 4
    _usar("Mira", "Animate Objects", modo="objeto grande:2")
    # Outra concentração: os sátiros vão embora.
    assert not [n for n in memory.campaign["combat_state"]["initiative_order"] if n.startswith("Sátiro")]
    assert _ch("Objeto Animado Grande de Mira 1")["sheet"]["vida_max"] == 50


def test_invocacoes_de_um_minuto_so_fora_da_luta(luta):
    for nome, modo in (("Conjure Minor Elementals", "gargula:1"), ("Conjure Fey", "mamute:1"),
                       ("Conjure Celestial", "couatl:1"), ("Create Undead", "carnical:3"),
                       ("Planar Ally", "couatl:1")):
        r = _usar("Mira", nome, modo=modo)
        assert not r["ok"] and "não dá no meio da luta" in r["message"], nome
    td.end_combat()
    assert td.conjurar_fora_de_combate("Mira", "Conjure Fey", modo="mamute:1")["ok"]
    assert _ch("Mamute de Mira")["sheet"]["vida_max"] == 126
    # Conjurar Fada e Criar Mortos-Vivos são do 6º: um por descanso longo.
    r = td.conjurar_fora_de_combate("Mira", "Create Undead", modo="carnical:3")
    assert not r["ok"] and "6º círculo" in r["message"]
    _ch("Mira")["sheet"]["circulos_altos_usados"] = []
    assert td.conjurar_fora_de_combate("Mira", "Create Undead", modo="carnical:3")["ok"]
    assert _ch("Carniçal de Mira 3")
