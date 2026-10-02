"""
test_surpresa_cobertura_chefes.py

Regras do D&D que o motor não tinha:

1. Surpresa: quem é pego na emboscada não age, não se move e não reage no
   primeiro turno; o Assassinato tem vantagem contra quem ainda não agiu e
   crítico contra quem está Surpreso; o Golpe da Morte dobra o dano.
2. Cobertura: meia (+2 de CA e nas salvaguardas de DES), três quartos (+5),
   total (ninguém mira); manobra "Buscar cobertura"; sair do lugar tira.
3. Combate com duas armas: depois de atacar com arma leve, a ação bônus ataca
   com a outra arma leve, sem o modificador positivo no dano (o estilo soma).
4. Resistência Lendária (a falha vira sucesso, N por dia) e ações de covil
   (uma por rodada, nunca a mesma duas vezes seguidas).
"""
import pytest

from rpg import memory, resolucao, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _ch(nome):
    return memory.campaign["characters"].get(memory.char_key(nome))


def _conds(nome):
    return [c.get("nome") if isinstance(c, dict) else c for c in _ch(nome)["sheet"].get("condicoes") or []]


def _vez(nome):
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index(nome)
    cs["turn_token"] = int(cs.get("turn_token", 0) or 0) + 1
    td._reset_turn_economy(cs)


def _d20(monkeypatch, valor, registro=None):
    def rolar(vantagem=False, desvantagem=False, *a, **k):
        if registro is not None:
            registro.append((vantagem, desvantagem))
        return valor, f"d20={valor}"
    monkeypatch.setattr(td, "_roll_d20_with_adv", rolar)


@pytest.fixture
def emboscada(campanha, povoar):
    povoar(criar_ficha("Brann", grupo=True, vida=40, destreza=10),
           criar_ficha("Lia", grupo=True, vida=30),
           criar_ficha("Orc", vida=40, raca="orc", destreza=10),
           criar_ficha("Goblin", vida=20, raca="goblin", destreza=10))
    return memory.campaign


# ---------------------------------------------------------------------------
# 1. Surpresa
# ---------------------------------------------------------------------------

def test_surpresa_marca_so_o_lado_pego(emboscada):
    r = td.roll_initiative("Brann, Lia, Orc, Goblin", surprised="inimigos")
    assert "Surpresos" in r and "Orc" in r.split("Surpresos")[1], r
    assert "Surpreso" in _conds("Orc") and "Surpreso" in _conds("Goblin")
    assert "Surpreso" not in _conds("Brann")


def test_surpreso_nao_age_nem_reage_e_depois_volta(emboscada, monkeypatch):
    td.roll_initiative("Brann, Lia, Orc, Goblin", surprised="Orc")
    assert not td._reaction_available(_ch("Orc"))
    _vez("Orc")
    vida = _ch("Brann")["sheet"]["vida_atual"] + _ch("Lia")["sheet"]["vida_atual"]
    r = td.execute_npc_turn()
    assert "Surpreso" in r and "não age" in r, r
    assert _ch("Brann")["sheet"]["vida_atual"] + _ch("Lia")["sheet"]["vida_atual"] == vida
    assert "Surpreso" not in _conds("Orc") and td._reaction_available(_ch("Orc"))


def test_personagem_surpreso_so_encerra_o_turno(emboscada):
    td.roll_initiative("Brann, Lia, Orc, Goblin", surprised="grupo")
    _vez("Brann")
    r = td.combat_action("attack", actor="Brann", target="Orc")
    assert not r["ok"] and "Surpreso" in r["message"]
    assert td.combat_action("end_turn", actor="Brann")["ok"]
    assert "Surpreso" not in _conds("Brann")


def test_alerta_nao_e_surpreendido(emboscada):
    _ch("Orc")["habilidades"].append({"nome": "Alerta", "custo_mana": 0, "dado": "", "descricao": ""})
    td.roll_initiative("Brann, Lia, Orc, Goblin", surprised="inimigos")
    assert "Surpreso" not in _conds("Orc") and "Surpreso" in _conds("Goblin")


def _assassino(nome="Brann"):
    _ch(nome)["habilidades"].append({"nome": "Assassinato", "custo_mana": 0, "dado": "", "descricao": ""})


def test_assassinato_vantagem_contra_quem_nao_agiu(emboscada, monkeypatch):
    iniciar_combate(["Brann", "Orc", "Lia", "Goblin"])
    memory.campaign["combat_state"]["agiram"] = ["goblin"]
    _assassino()
    vezes = []
    _d20(monkeypatch, 5, vezes)
    r = td.attack_roll("Brann", "Orc", "adaga", 6, end_turn=False, _skip_turn_check=True)
    assert "ainda não agiu" in r and vezes[-1][0] is True, r
    td.attack_roll("Brann", "Goblin", "adaga", 6, end_turn=False, _skip_turn_check=True)
    assert vezes[-1][0] is False


def test_turno_que_acaba_conta_como_agiu(emboscada):
    iniciar_combate(["Brann", "Orc", "Lia", "Goblin"])
    td._auto_advance_turn("Brann")
    assert "brann" in memory.campaign["combat_state"]["agiram"]


def test_assassinato_critico_contra_surpreso(emboscada, monkeypatch):
    td.roll_initiative("Brann, Lia, Orc, Goblin", surprised="inimigos")
    _assassino()
    _d20(monkeypatch, 15)
    r = td.attack_roll("Brann", "Orc", "adaga", 6, end_turn=False, _skip_turn_check=True)
    assert "o acerto é crítico" in r and "CRÍTICO" in r, r


def test_golpe_da_morte_dobra(emboscada, monkeypatch):
    td.roll_initiative("Brann, Lia, Orc, Goblin", surprised="inimigos")
    _ch("Brann")["habilidades"].append({"nome": "Golpe da Morte", "custo_mana": 0, "dado": "", "descricao": ""})
    _d20(monkeypatch, 15)
    monkeypatch.setattr(td, "_rolar_salvaguarda", lambda *a, **k: (False, "salvaguarda"))
    monkeypatch.setattr(td.random, "randint", lambda a, b: 2)
    _ch("Orc")["sheet"]["vida_atual"] = 100
    _ch("Orc")["sheet"]["vida_max"] = 100
    r = td.attack_roll("Brann", "Orc", "adaga", 6, end_turn=False, _skip_turn_check=True)
    assert "o dano DOBRA" in r, r
    # adaga 1d4 = 2, + FOR 3 = 5, dobrado = 10.
    assert _ch("Orc")["sheet"]["vida_atual"] == 90


# ---------------------------------------------------------------------------
# 2. Cobertura
# ---------------------------------------------------------------------------

@pytest.fixture
def tiroteio(emboscada):
    for nome in ("Brann", "Orc"):
        _ch(nome)["inventario"] += [{"nome": "Arco Curto", "qtd": 1}, {"nome": "Flechas", "qtd": 20}]
    iniciar_combate(["Brann", "Orc", "Lia", "Goblin"])
    return memory.campaign


def test_meia_cobertura_soma_dois_contra_tiro(tiroteio, monkeypatch):
    _d20(monkeypatch, 10)
    assert "meia" in td.set_cover("Orc", "meia")
    r = td.attack_roll("Brann", "Orc", "arco curto", 6, end_turn=False, _skip_turn_check=True)
    assert "meia cobertura: +2 de CA" in r and "vs CA 14" in r, r


def test_sem_zonas_corpo_a_corpo_ignora_cobertura(tiroteio, monkeypatch):
    _d20(monkeypatch, 10)
    td.set_cover("Orc", "tres_quartos")
    r = td.attack_roll("Brann", "Orc", "espada longa", 6, end_turn=False, _skip_turn_check=True)
    assert "cobertura" not in r and "vs CA 12" in r, r


def test_com_zonas_vale_contra_quem_esta_em_outra_zona(tiroteio, monkeypatch):
    _d20(monkeypatch, 10)
    cs = memory.campaign["combat_state"]
    cs["zonas"] = ["Portão", "Pátio"]
    cs["posicoes"] = {"brann": "Portão", "orc": "Pátio", "lia": "Pátio", "goblin": "Pátio"}
    td.set_cover("Orc", "tres_quartos")
    r = td.attack_roll("Brann", "Orc", "arco curto", 6, end_turn=False, _skip_turn_check=True)
    assert "+5 de CA" in r, r
    r = td.attack_roll("Lia", "Orc", "espada longa", 6, end_turn=False, _skip_turn_check=True)
    assert "cobertura" not in r, r


def test_cobertura_total_ninguem_mira(tiroteio):
    td.set_cover("Orc", "total")
    r = td.attack_roll("Brann", "Orc", "arco curto", 6, end_turn=False, _skip_turn_check=True)
    assert r.startswith("Erro:") and "cobertura total" in r
    assert next(i for i in _ch("Brann")["inventario"] if i["nome"] == "Flechas")["qtd"] == 20


def test_cobertura_na_salvaguarda_de_destreza(tiroteio):
    td.set_cover("Orc", "meia")
    _, linha = td._rolar_salvaguarda(_ch("Orc"), "destreza", 30)
    assert "meia cobertura: +2" in linha
    _, linha = td._rolar_salvaguarda(_ch("Orc"), "sabedoria", 30)
    assert "cobertura" not in linha


def test_cobertura_contra_magia_de_ataque(tiroteio, monkeypatch):
    _d20(monkeypatch, 10)
    _ch("Brann")["habilidades"].append({"nome": "Fire Bolt", "custo_mana": 0, "dado": "", "descricao": ""})
    _ch("Brann")["sheet"]["classe"] = "mago"
    td.set_cover("Orc", "tres_quartos")
    r = td.use_ability("Brann", "Fire Bolt", "Orc", end_turn=False, _skip_turn_check=True)
    assert "+5 de CA" in r and "vs CA 17" in r, r


def test_buscar_cobertura_usa_o_movimento_e_o_nivel_da_zona(tiroteio):
    cs = memory.campaign["combat_state"]
    cs["zonas"] = ["Portão", "Pátio"]
    cs["posicoes"] = {"brann": "Portão", "orc": "Pátio", "lia": "Pátio", "goblin": "Pátio"}
    td.set_cover("Portão", "tres_quartos")
    _vez("Brann")
    r = td.combat_action("cover", actor="Brann")
    assert r["ok"] and "três quartos de cobertura" in r["message"], r["message"]
    assert cs["turn_economy"]["movimento_usado"] and not cs["turn_economy"]["acao_usada"]
    assert next(c for c in r["snapshot"]["combatants"] if c["name"] == "Brann")["cobertura"] == "tres_quartos"
    assert not td.combat_action("cover", actor="Brann")["ok"]


def test_sair_do_lugar_tira_a_cobertura(tiroteio):
    cs = memory.campaign["combat_state"]
    cs["zonas"] = ["Portão", "Pátio"]
    cs["posicoes"] = {"brann": "Portão", "orc": "Pátio", "lia": "Pátio", "goblin": "Pátio"}
    td.set_cover("Brann", "meia")
    _vez("Brann")
    td.move_combatant("Brann", "Pátio")
    assert td._cobertura_de(_ch("Brann")) == ""


def test_nivel_invalido(tiroteio):
    assert td.set_cover("Orc", "muita").startswith("Erro:")


# ---------------------------------------------------------------------------
# 3. Duas armas
# ---------------------------------------------------------------------------

@pytest.fixture
def ladino(emboscada):
    _ch("Brann")["sheet"]["equipamentos"]["arma_principal"] = "adaga"
    _ch("Brann")["inventario"].append({"nome": "Adaga", "qtd": 2})
    iniciar_combate(["Brann", "Orc", "Lia", "Goblin"])
    return memory.campaign


def test_outra_mao_depois_de_atacar_com_arma_leve(ladino, monkeypatch):
    _d20(monkeypatch, 18)
    monkeypatch.setattr(td.random, "randint", lambda a, b: 2)
    _vez("Brann")
    assert td.combat_action("attack", actor="Brann", target="Orc", weapon="adaga")["ok"]
    vida = _ch("Orc")["sheet"]["vida_atual"]
    r = td.combat_action("offhand", actor="Brann", target="Orc")
    assert r["ok"] and "outra mão" in r["message"] and "+0(mod, outra mão)" in r["message"], r["message"]
    assert _ch("Orc")["sheet"]["vida_atual"] == vida - 2           # 1d4 = 2, sem o +3
    # Ação e ação bônus gastas: o turno passa.
    assert td._combat_current_actor() != "Brann"


def test_estilo_duas_armas_soma_o_modificador(ladino, monkeypatch):
    _d20(monkeypatch, 18)
    monkeypatch.setattr(td.random, "randint", lambda a, b: 2)
    _ch("Brann")["sheet"].setdefault("feature_choices", {})["Estilo de Combate"] = "Combate com Duas Armas"
    _vez("Brann")
    td.combat_action("attack", actor="Brann", target="Orc", weapon="adaga")
    vida = _ch("Orc")["sheet"]["vida_atual"]
    r = td.combat_action("offhand", actor="Brann", target="Orc")
    assert _ch("Orc")["sheet"]["vida_atual"] == vida - 5, r["message"]


def test_sem_atacar_com_arma_leve_nao_ha_outra_mao(ladino, monkeypatch):
    _d20(monkeypatch, 18)
    _vez("Brann")
    r = td.combat_action("offhand", actor="Brann", target="Orc")
    assert not r["ok"] and "arma leve" in r["message"]
    td.combat_action("attack", actor="Brann", target="Orc", weapon="espada longa")
    assert not td.combat_action("offhand", actor="Brann", target="Orc")["ok"]


def test_sem_segunda_arma_leve(emboscada, monkeypatch):
    _d20(monkeypatch, 18)
    _ch("Brann")["sheet"]["equipamentos"]["arma_principal"] = "adaga"
    iniciar_combate(["Brann", "Orc", "Lia", "Goblin"])
    _vez("Brann")
    td.combat_action("attack", actor="Brann", target="Orc", weapon="adaga")
    r = td.combat_action("offhand", actor="Brann", target="Orc")
    assert not r["ok"] and "outra arma leve" in r["message"]
    assert next(c for c in td.combat_snapshot()["combatants"] if c["name"] == "Brann")["outra_mao"] is False


# ---------------------------------------------------------------------------
# 4. Resistência Lendária e ações de covil
# ---------------------------------------------------------------------------

@pytest.fixture
def chefe(campanha, povoar):
    povoar(criar_ficha("Brann", grupo=True, vida=60),
           criar_ficha("Dragão", vida=200, habilidades=[
               {"nome": "Estalactites", "dado": "3d6", "custo_mana": 0, "salvaguarda": "destreza", "cd": 15,
                "descricao": "Estalactites caem: salvaguarda de Destreza CD 15; 3d6 de dano de concussão."},
               {"nome": "Gás Venenoso", "dado": "2d6", "custo_mana": 0, "salvaguarda": "constituicao", "cd": 15,
                "descricao": "Gás sobe do chão: salvaguarda de Constituição CD 15; 2d6 de dano de veneno."}]))
    iniciar_combate(["Brann", "Dragão"])
    return memory.campaign


def test_resistencia_lendaria_troca_a_falha(chefe):
    assert "2/dia" in td.set_legendary_resistance("Dragão", 2)
    for restam in (1, 0):
        passou, linha = td._rolar_salvaguarda(_ch("Dragão"), "sabedoria", 99)
        assert passou and f"restam {restam}/2" in linha, linha
    passou, _ = td._rolar_salvaguarda(_ch("Dragão"), "sabedoria", 99)
    assert not passou


def test_resistencia_lendaria_volta_com_o_dia(chefe):
    td.set_legendary_resistance("Dragão", 1)
    td._rolar_salvaguarda(_ch("Dragão"), "sabedoria", 99)
    td.advance_time(24)
    assert _ch("Dragão")["sheet"]["resistencia_lendaria"]["restantes"] == 1


def test_resistencia_lendaria_do_bloco_do_open5e(campanha, monkeypatch):
    from rpg import open5e

    class _R:
        ok = True

        def json(self):
            return {"name": "Lich", "hit_points": 135, "armor_class": 17, "strength": 11, "dexterity": 16,
                    "constitution": 16, "intelligence": 20, "wisdom": 14, "charisma": 16,
                    "challenge_rating": "21", "type": "undead", "size": "Medium", "actions": [],
                    "special_abilities": [{"name": "Legendary Resistance (3/Day)", "desc": "..."}]}
    monkeypatch.setattr(open5e.http, "get", lambda *a, **k: _R())
    td.spawn_monster("lich", "Lich")
    assert _ch("Lich")["sheet"]["resistencia_lendaria"] == {"max": 3, "restantes": 3}


def test_acao_de_covil_uma_por_rodada_alternando(chefe, monkeypatch):
    monkeypatch.setattr(td, "_rolar_salvaguarda", lambda *a, **k: (False, "salvaguarda"))
    assert "uma por rodada" in td.set_lair_actions("Dragão", "Estalactites, Gás Venenoso")
    feitas = []
    for _ in range(4):
        saida = td._auto_advance_turn(td._combat_current_actor())
        feitas += [l for l in saida.split("AÇÃO DE COVIL")[1:]]
    assert len(feitas) == 2, feitas                         # duas viradas de rodada em quatro turnos
    assert ("Estalactites" in feitas[0]) != ("Estalactites" in feitas[1])
    assert _ch("Brann")["sheet"]["vida_atual"] < 60


def test_acao_de_covil_precisa_da_habilidade(chefe):
    assert td.set_lair_actions("Dragão", "Terremoto").startswith("Erro:")
