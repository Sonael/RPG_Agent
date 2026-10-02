"""
test_luz_preparar_componentes_montaria.py

1. Visão e luz: o lugar pode estar claro, na penumbra ou no escuro; quem não
   tem visão no escuro não vê ali (desvantagem ao atacar, vantagem contra
   ele, magia que exige ver recusada, esconder-se automático). Tocha, Luz e
   Luzes Dançantes iluminam.
2. Preparar magia: conjura agora (mana e concentração) e solta como reação.
3. Componente material caro: precisa estar na mochila e some quando a magia
   o consome.
4. Combate montado: montar, andar junto, cair quando a montaria cai.
"""
import pytest

from rpg import criaturas, manobras, memory, resolucao, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _ch(nome):
    return memory.campaign["characters"].get(memory.char_key(nome))


def _hab(nome, custo=2):
    return {"nome": nome, "custo_mana": custo, "dado": "", "descricao": "",
            "nivel_magia": (resolucao._magia_srd({"nome": nome}) or {}).get("nivel", 1)}


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
def noite(campanha, povoar):
    povoar(criar_ficha("Brann", grupo=True, vida=40, raca="humano",
                       habilidades=[_hab("Hold Person", 3), _hab("Light", 0), _hab("Magic Missile")]),
           criar_ficha("Elara", grupo=True, vida=30, raca="elfo"),
           criar_ficha("Orc", vida=40, raca="orc"),
           criar_ficha("Bandido", vida=30, raca="humano"))
    _ch("Brann")["sheet"]["classe"] = "mago"
    iniciar_combate(["Brann", "Elara", "Orc", "Bandido"])
    return memory.campaign


# ---------------------------------------------------------------------------
# 1. Visão e luz
# ---------------------------------------------------------------------------

def test_visao_no_escuro_pela_raca_e_pela_ficha(noite):
    assert td._visao_no_escuro(_ch("Elara")) == 18 and td._visao_no_escuro(_ch("Orc")) == 18
    assert td._visao_no_escuro(_ch("Brann")) == 0
    assert criaturas.montar_sheet("esqueleto")["visao_no_escuro"] == 18


def test_no_escuro_quem_nao_ve_ataca_com_desvantagem(noite, monkeypatch):
    td.set_light("", "escuridao")
    vezes = []
    _d20(monkeypatch, 10, vezes)
    r = td.attack_roll("Brann", "Orc", "espada longa", 6, end_turn=False, _skip_turn_check=True)
    assert "Brann não vê Orc — desvantagem" in r and vezes[-1] == (False, True), r
    r = td.attack_roll("Orc", "Brann", "espada longa", 6, end_turn=False, _skip_turn_check=True)
    assert "Brann não vê Orc — vantagem" in r and vezes[-1] == (True, False), r
    r = td.attack_roll("Elara", "Orc", "espada longa", 6, end_turn=False, _skip_turn_check=True)
    assert "no escuro" not in r and vezes[-1] == (False, False), r


def test_penumbra_e_luz_clara_nao_mudam_o_ataque(noite, monkeypatch):
    vezes = []
    _d20(monkeypatch, 10, vezes)
    td.set_light("", "penumbra")
    td.attack_roll("Brann", "Orc", "espada longa", 6, end_turn=False, _skip_turn_check=True)
    assert vezes[-1] == (False, False)


def test_tocha_acesa_ilumina(noite, monkeypatch):
    td.set_light("", "escuridao")
    _ch("Brann")["inventario"].append({"nome": "Tocha", "qtd": 3})
    _vez("Brann")
    r = td.combat_action("light", actor="Brann")
    assert r["ok"] and "acende" in r["message"]
    assert not memory.campaign["combat_state"]["turn_economy"]["acao_usada"]
    assert td._luz_no_lugar("Orc") == "clara"
    vezes = []
    _d20(monkeypatch, 10, vezes)
    td.attack_roll("Brann", "Orc", "espada longa", 6, end_turn=False, _skip_turn_check=True)
    assert vezes[-1] == (False, False)


def test_sem_tocha_nao_acende(noite):
    _vez("Brann")
    assert not td.combat_action("light", actor="Brann")["ok"]


def test_truque_luz_ilumina(noite):
    td.set_light("", "escuridao")
    _vez("Brann")
    r = td.combat_action("ability", actor="Brann", ability="Light")
    assert r["ok"], r["message"]
    assert td._luz_no_lugar("Orc") == "clara"


def test_truque_luz_ilumina_a_zona_de_quem_conjura(noite):
    cs = memory.campaign["combat_state"]
    cs["zonas"] = ["Rua", "Beco"]
    cs["posicoes"] = {"brann": "Beco", "elara": "Rua", "orc": "Beco", "bandido": "Rua"}
    td.set_light("", "escuridao")
    _vez("Brann")
    assert td.combat_action("ability", actor="Brann", ability="Light")["ok"]
    assert td._luz_no_lugar("Orc") == "clara" and td._luz_no_lugar("Bandido") == "escuridao"


def test_com_zonas_a_luz_e_da_zona(noite):
    cs = memory.campaign["combat_state"]
    cs["zonas"] = ["Rua", "Beco"]
    cs["posicoes"] = {"brann": "Rua", "elara": "Rua", "orc": "Beco", "bandido": "Beco"}
    assert td.set_light("Beco", "escuridao") == "Luz em Beco: escuridao."
    assert td._luz_no_lugar("Orc") == "escuridao" and td._luz_no_lugar("Brann") == "clara"
    assert td.set_light("Sótão", "escuridao").startswith("Erro:")
    assert td.set_light("Beco", "breu").startswith("Erro:")


def test_magia_que_exige_ver_e_recusada_no_escuro(noite):
    td.set_light("", "escuridao")
    _vez("Brann")
    r = td.combat_action("ability", actor="Brann", ability="Hold Person", target="Bandido")
    assert not r["ok"] and "exige ver o alvo" in r["message"], r["message"]
    assert _ch("Brann")["sheet"]["mana_atual"] == 20


def test_esconder_no_escuro_de_quem_nao_ve(noite):
    td.set_light("", "escuridao")
    _ch("Orc")["status"] = "morto"
    r = resolucao._acao_de_movimento(_ch("Elara"), "esconder", "Esconder-se")
    assert "nenhum inimigo o vê" in r and "Escondido" in _conds("Elara"), r


def test_penumbra_tira_cinco_da_percepcao(noite, monkeypatch):
    td.set_light("", "penumbra")
    _ch("Orc")["status"] = "morto"
    monkeypatch.setattr(resolucao.random, "randint", lambda a, b: 1)
    r = resolucao._acao_de_movimento(_ch("Elara"), "esconder", "Esconder-se")
    assert "Percepção passiva 5" in r, r                      # 10 + SAB 0 - 5


def test_cartao_mostra_o_escuro(noite):
    td.set_light("", "escuridao")
    cartao = next(c for c in td.combat_snapshot()["combatants"] if c["name"] == "Brann")
    assert "Na escuridão" in cartao["condicoes"] and cartao["visao_no_escuro"] == 0


def test_visao_no_escuro_do_open5e(campanha, monkeypatch):
    from rpg import open5e

    class _R:
        ok = True

        def json(self):
            return {"name": "Goblin", "hit_points": 7, "armor_class": 15, "strength": 8, "dexterity": 14,
                    "constitution": 10, "intelligence": 10, "wisdom": 8, "charisma": 8,
                    "challenge_rating": "1/4", "type": "humanoid", "size": "Small", "actions": [],
                    "senses": "darkvision 60 ft., passive Perception 9"}
    monkeypatch.setattr(open5e.http, "get", lambda *a, **k: _R())
    td.spawn_monster("goblin", "Goblin")
    assert _ch("Goblin")["sheet"]["visao_no_escuro"] == 18


# ---------------------------------------------------------------------------
# 2. Preparar magia
# ---------------------------------------------------------------------------

def test_magia_preparada_gasta_agora_e_solta_quando_o_alvo_age(noite, monkeypatch):
    _vez("Brann")
    r = td.combat_action("ready", actor="Brann", target="Orc", weapon="magia:Magic Missile")
    assert r["ok"] and "2 mana gastos agora" in r["message"], r["message"]
    assert _ch("Brann")["sheet"]["mana_atual"] == 18
    assert _ch("Brann")["sheet"]["concentracao"]["magia"] == "Magic Missile"
    linhas = manobras.disparar_preparadas("Orc")
    assert linhas and "solta Magic Missile preparada" in linhas[0], linhas
    assert _ch("Orc")["sheet"]["vida_atual"] < 40
    assert _ch("Brann")["sheet"]["mana_atual"] == 18                     # não paga de novo
    assert not td._reaction_available(_ch("Brann"))


def test_concentracao_perdida_desfaz_a_magia_preparada(noite):
    _vez("Brann")
    td.combat_action("ready", actor="Brann", target="Orc", weapon="magia:Magic Missile")
    _ch("Brann")["sheet"]["concentracao"] = None
    linhas = manobras.disparar_preparadas("Orc")
    assert "se desfaz" in linhas[0] and _ch("Orc")["sheet"]["vida_atual"] == 40


def test_magia_preparada_expira_no_turno_seguinte(noite):
    _vez("Brann")
    td.combat_action("ready", actor="Brann", target="Orc", weapon="magia:Magic Missile")
    manobras.expirar_preparadas("Brann")
    assert _ch("Brann")["sheet"]["concentracao"] is None
    assert not memory.campaign["combat_state"].get("preparadas")


def test_preparar_magia_sem_mana_ou_que_nao_e_acao(noite):
    _ch("Brann")["habilidades"].append(_hab("Healing Word"))
    _vez("Brann")
    r = td.combat_action("ready", actor="Brann", target="Orc", weapon="magia:Healing Word")
    assert not r["ok"] and "uma Ação" in r["message"]
    _ch("Brann")["sheet"]["mana_atual"] = 0
    r = td.combat_action("ready", actor="Brann", target="Orc", weapon="magia:Magic Missile")
    assert not r["ok"] and "mana" in r["message"]


# ---------------------------------------------------------------------------
# 3. Componentes caros
# ---------------------------------------------------------------------------

@pytest.fixture
def mago(campanha, povoar):
    povoar(criar_ficha("Mira", grupo=True, classe="mago", nivel=9, mana=60,
                       habilidades=[_hab("Stoneskin", 5), _hab("Identify"), _hab("Find Familiar")]),
           criar_ficha("Necromante", vida=30, habilidades=[_hab("Stoneskin", 5)]))
    return memory.campaign


def test_le_o_componente_do_compendio():
    c = td.componente_caro(_hab("Stoneskin", 5))
    assert c["custo"] == 100 and c["consome"] and "diamante" in c["palavras"]
    c = td.componente_caro(_hab("Identify"))
    assert c["custo"] == 100 and not c["consome"] and "perola" in c["palavras"]
    c = td.componente_caro(_hab("Find Familiar"))
    assert c["custo"] == 10 and c["consome"]
    assert td.componente_caro(_hab("Magic Missile")) is None


def test_sem_o_componente_nada_e_gasto(mago):
    r = td.use_ability("Mira", "Stoneskin", "Mira", end_turn=False)
    assert r.startswith("Aviso:") and "100 po" in r and "diamante" in r, r
    assert _ch("Mira")["sheet"]["mana_atual"] == 60


def test_componente_consumido_some(mago):
    _ch("Mira")["inventario"].append({"nome": "Pó de diamante", "qtd": 2})
    r = td.use_ability("Mira", "Stoneskin", "Mira", end_turn=False)
    assert not r.startswith(("Aviso:", "Erro:")), r
    assert next(i for i in _ch("Mira")["inventario"] if i["nome"] == "Pó de diamante")["qtd"] == 1


def test_componente_que_nao_some(mago):
    _ch("Mira")["inventario"] += [{"nome": "Pérola", "qtd": 1, "identificado": True},
                                  {"nome": "Anel", "qtd": 1}]
    r = td.conjurar_fora_de_combate("Mira", "Identify", modo="Anel")
    assert r["ok"], r["message"]
    assert any(i["nome"] == "Pérola" for i in _ch("Mira")["inventario"])


def test_item_barato_demais_nao_serve(mago):
    _ch("Mira")["inventario"].append({"nome": "Pó de diamante", "qtd": 1, "valor_po": 20})
    assert td.use_ability("Mira", "Stoneskin", "Mira", end_turn=False).startswith("Aviso:")


def test_npc_nao_e_cobrado(mago):
    _ch("Necromante")["sheet"]["mana_atual"] = 20
    r = td.use_ability("Necromante", "Stoneskin", "Necromante", end_turn=False)
    assert not r.startswith("Aviso:"), r


# ---------------------------------------------------------------------------
# 4. Combate montado
# ---------------------------------------------------------------------------

@pytest.fixture
def cavaleiro(campanha, povoar):
    povoar(criar_ficha("Brann", grupo=True, classe="paladino", nivel=5, vida=40),
           criar_ficha("Orc", vida=40, raca="orc"))
    iniciar_combate(["Brann", "Orc"])
    cs = memory.campaign["combat_state"]
    cs["zonas"] = ["Portão", "Pátio", "Torre"]
    cs["posicoes"] = {"brann": "Portão", "orc": "Pátio"}
    criaturas.invocar(_ch("Brann"), "cavalo de guerra", 1, "Find Steed", concentracao=False, persistente=True)
    return memory.campaign


def _cavalo():
    return _ch("Cavalo de Guerra de Brann")


def test_montar_gasta_o_movimento_e_anda_junto(cavaleiro):
    _vez("Brann")
    assert next(c for c in td.combat_snapshot()["combatants"] if c["name"] == "Brann")["pode_montar"]
    r = td.combat_action("mount", actor="Brann", target="Cavalo de Guerra de Brann")
    assert r["ok"] and "monta" in r["message"], r["message"]
    assert memory.campaign["combat_state"]["turn_economy"]["movimento_usado"]
    cartao = next(c for c in r["snapshot"]["combatants"] if c["name"] == "Brann")
    assert cartao["montado_em"] == "Cavalo de Guerra de Brann"
    assert "Montado em Cavalo de Guerra de Brann" in cartao["condicoes"]
    td._por_zona("Brann", "Pátio")
    assert td._zona_de("Cavalo de Guerra de Brann") == "Pátio"
    td._por_zona("Cavalo de Guerra de Brann", "Torre")
    assert td._zona_de("Brann") == "Torre"


def test_montar_recusado(cavaleiro):
    _vez("Brann")
    memory.campaign["combat_state"]["posicoes"]["orc"] = "Portão"
    _ch("Orc")["sheet"]["montaria"] = True                 # montaria, mas do outro lado
    r = td.combat_action("mount", actor="Brann", target="Orc")
    assert not r["ok"] and "não é montaria de Brann" in r["message"], r["message"]
    memory.campaign["combat_state"]["posicoes"][memory.char_key("Cavalo de Guerra de Brann")] = "Torre"
    assert not td.combat_action("mount", actor="Brann", target="Cavalo de Guerra de Brann")["ok"]


def test_montaria_que_cai_derruba_quem_monta(cavaleiro, monkeypatch):
    manobras.montar("Brann", "Cavalo de Guerra de Brann")
    monkeypatch.setattr(td, "_rolar_salvaguarda", lambda *a, **k: (False, "salvaguarda"))
    _cavalo()["sheet"]["vida_atual"] = 1
    td._apply_damage(_cavalo(), 10, "slashing")
    r = td._mark_at_zero_hp(_cavalo(), "Orc")
    assert "CAÍDO" in r and "Caído" in _conds("Brann"), r
    assert not manobras.montaria_de(_ch("Brann"))


def test_montaria_derrubada_tambem(cavaleiro, monkeypatch):
    from rpg import tracos
    manobras.montar("Brann", "Cavalo de Guerra de Brann")
    monkeypatch.setattr(td, "_rolar_salvaguarda", lambda *a, **k: (True, "salvaguarda"))
    linha = tracos._por_condicao(_ch("Orc"), _cavalo(), "Caído")
    assert "cai de pé" in linha and "Caído" not in _conds("Brann"), linha
    assert not manobras.montaria_de(_ch("Brann"))


def test_cavaleiro_que_cai_sai_da_sela(cavaleiro):
    manobras.montar("Brann", "Cavalo de Guerra de Brann")
    _ch("Brann")["sheet"]["vida_atual"] = 0
    td._mark_at_zero_hp(_ch("Brann"), "Orc")
    assert not manobras.montaria_de(_ch("Brann")) and not manobras.cavaleiro_de(_cavalo())


def test_desmontar(cavaleiro):
    manobras.montar("Brann", "Cavalo de Guerra de Brann")
    _vez("Brann")
    r = td.combat_action("dismount", actor="Brann")
    assert r["ok"] and "desmonta" in r["message"]
    assert not td.combat_action("dismount", actor="Brann")["ok"]
