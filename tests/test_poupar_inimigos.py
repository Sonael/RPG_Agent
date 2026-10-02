"""
test_poupar_inimigos.py

"Se em combate eu enfeitiçar um inimigo e não quiser matar ele, o combate é
encerrado ou eu sou obrigado a matar todos?" — era obrigado: a luta só
acabava com todo inimigo caído, o enfeitiçado contava como de pé, a tela não
tinha como pedir rendição e todo golpe que derrubava um NPC matava.

1. A luta acaba quando os inimigos que restam estão enfeitiçados ou
   dominados pelo grupo, ou rendidos. Eles vão para "Poupados": vivos, sem
   saque, e a vitória conta.
2. Pedir rendição (Manobras): Intimidação ou Persuasão contra a Sabedoria.
3. Golpe não letal: o corpo a corpo que derruba nocauteia (estável), e o NPC
   acorda com 1 PV depois de 1d4 horas.
"""
import pytest

from rpg import encantos, manobras, memory, resolucao, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _ch(nome):
    return memory.campaign["characters"].get(memory.char_key(nome))


def _hab(nome, custo=2):
    return {"nome": nome, "custo_mana": custo, "dado": "", "descricao": "",
            "nivel_magia": (resolucao._magia_srd({"nome": nome}) or {}).get("nivel", 1)}


def _vez(nome):
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index(nome)
    cs["turn_token"] = int(cs.get("turn_token", 0) or 0) + 1
    td._reset_turn_economy(cs)


def _encantar(quem, alvo, magia="Charm Person"):
    if magia.startswith("Dominate"):          # o domínio dura a concentração
        _ch(quem)["sheet"]["concentracao"] = {"magia": magia}
    encantos.encantar(_ch(quem), _ch(alvo), magia, magia, magia)


@pytest.fixture
def luta(campanha, povoar):
    povoar(criar_ficha("Kaelen", grupo=True, classe="clérigo", nivel=9, sabedoria=16, carisma=16, vida=40,
                       habilidades=[_hab("Charm Person")]),
           criar_ficha("Brann", grupo=True, vida=40, forca=18),
           criar_ficha("Orc", vida=30, raca="orc", sabedoria=10),
           criar_ficha("Goblin", vida=8, raca="goblin"))
    iniciar_combate(["Kaelen", "Brann", "Orc", "Goblin"])
    return memory.campaign


def _fim(r):
    return memory.campaign["combat_state"].get("result") or (r.get("snapshot") or {}).get("result")


# ---------------------------------------------------------------------------
# 1. A luta acaba com inimigos poupados
# ---------------------------------------------------------------------------

def test_enfeiticar_o_ultimo_inimigo_encerra_a_luta(luta):
    _ch("Goblin")["status"] = "morto"
    _encantar("Kaelen", "Orc")
    r = td.combat_action("end_turn", actor="Kaelen")
    res = _fim(r)
    assert res and res["outcome"] == "vitoria", r["message"]
    assert [(c["name"], c["status"]) for c in res["poupados"]] == [("Orc", "enfeitiçado")]
    assert "Orc" not in [c["name"] for c in res["caidos"]]
    assert _ch("Orc")["sheet"]["vida_atual"] == 30
    assert not memory.campaign["combat_state"]["is_active"]


def test_com_outro_inimigo_de_pe_a_luta_continua(luta):
    _encantar("Kaelen", "Orc")
    td.combat_action("end_turn", actor="Kaelen")
    assert memory.campaign["combat_state"]["is_active"]


def test_dominado_e_rendido_tambem_poupam(luta):
    _encantar("Kaelen", "Orc", "Dominate Person")
    assert td.poupado(_ch("Orc")) == "dominado"
    td.set_combat_side("Goblin", "rendido")
    assert td.poupado(_ch("Goblin")) == "rendido"
    r = td.combat_action("end_turn", actor="Kaelen")
    res = _fim(r)
    assert res and sorted(c["status"] for c in res["poupados"]) == ["dominado", "rendido"]


def test_encantado_por_inimigo_nao_e_poupado(luta):
    _encantar("Goblin", "Orc")
    assert td.poupado(_ch("Orc")) == ""


def test_relato_manda_narrar_os_poupados(luta):
    _ch("Goblin")["status"] = "morto"
    _encantar("Kaelen", "Orc")
    td.combat_action("end_turn", actor="Kaelen")
    texto = td.combat_recap_payload()
    assert "POUPADOS (Orc: enfeitiçado)" in texto and "não são saque" in texto


def test_rendido_nao_age_nem_e_alvo(luta):
    td.set_combat_side("Orc", "rendido")
    assert "Orc" not in [n for n in memory.campaign["combat_state"]["initiative_order"]
                         if not td._is_out_of_combat(n)]


# ---------------------------------------------------------------------------
# 2. Pedir rendição
# ---------------------------------------------------------------------------

def _dados(monkeypatch, *valores):
    fila = list(valores)
    monkeypatch.setattr(manobras.random, "randint", lambda a, b: fila.pop(0) if fila else 10)


def test_rendicao_por_intimidacao(luta, monkeypatch):
    _ch("Orc")["sheet"]["vida_atual"] = 10                 # ferido: desvantagem
    _dados(monkeypatch, 15, 3, 5)                          # Brann 15; Orc min(3, 5)
    _vez("Brann")
    r = td.combat_action("surrender", actor="Brann", target="Orc", weapon="intimidar")
    assert r["ok"] and "RENDIDO" in r["message"] and "desvantagem: ferido" in r["message"], r["message"]
    assert _ch("Orc")["status"] == "rendido"
    assert memory.campaign["combat_state"]["turn_economy"]["acao_usada"]


def test_recusa_continua_lutando_e_gasta_a_acao(luta, monkeypatch):
    _dados(monkeypatch, 2, 18, 15)
    _vez("Brann")
    r = td.combat_action("surrender", actor="Brann", target="Orc", weapon="intimidar")
    assert r["ok"] and "recusa e continua lutando" in r["message"], r["message"]
    assert _ch("Orc")["status"] != "rendido"
    assert memory.campaign["combat_state"]["turn_economy"]["acao_usada"]


def test_inteiro_e_em_numero_resiste_com_vantagem(luta, monkeypatch):
    memory.campaign["characters"]["bugbear"] = criar_ficha("Bugbear", vida=30)
    memory.campaign["characters"]["hob"] = criar_ficha("Hob", vida=30)
    memory.campaign["combat_state"]["initiative_order"] += ["Bugbear", "Hob"]
    _dados(monkeypatch, 12, 4, 17)                         # Orc max(4, 17)
    _vez("Brann")
    r = td.combat_action("surrender", actor="Brann", target="Orc", weapon="intimidar")
    assert "vantagem: inteiro e em número" in r["message"] and "recusa" in r["message"], r["message"]


def test_enfeiticado_por_voces_da_vantagem_a_quem_pede(luta, monkeypatch):
    _encantar("Kaelen", "Orc")
    _dados(monkeypatch, 2, 16, 10)                         # Kaelen max(2, 16)
    _vez("Kaelen")
    r = td.combat_action("surrender", actor="Kaelen", target="Orc", weapon="persuadir")
    assert "Persuasão de Kaelen" in r["message"] and "vantagem: enfeitiçado" in r["message"], r["message"]


def test_dominado_se_rende_sem_teste(luta):
    _encantar("Kaelen", "Orc", "Dominate Person")
    _vez("Kaelen")
    r = td.combat_action("surrender", actor="Kaelen", target="Orc")
    assert "o dominado obedece" in r["message"] and _ch("Orc")["status"] == "rendido"


def test_fera_nao_entende_e_nao_gasta(luta):
    memory.campaign["characters"]["lobo"] = criar_ficha("Lobo", vida=11, inteligencia=3)
    memory.campaign["combat_state"]["initiative_order"].append("Lobo")
    _vez("Brann")
    r = td.combat_action("surrender", actor="Brann", target="Lobo")
    assert not r["ok"] and "não tem como entender" in r["message"]
    assert not memory.campaign["combat_state"]["turn_economy"]["acao_usada"]


@pytest.mark.parametrize("como", ["aliado", "longe", "silencio"])
def test_pedido_recusado_sem_gastar(luta, como):
    cs = memory.campaign["combat_state"]
    alvo = "Orc"
    if como == "aliado":
        alvo = "Kaelen"
    elif como == "longe":
        cs["zonas"] = ["Portão", "Pátio", "Torre"]
        cs["posicoes"] = {"brann": "Portão", "orc": "Torre", "kaelen": "Portão", "goblin": "Torre"}
    else:
        cs.setdefault("efeitos_de_zona", []).append({"nome": "Silêncio", "criatura": "orc", "silencio": True,
                                                     "tipo": "silencio"})
    _vez("Brann")
    r = td.combat_action("surrender", actor="Brann", target=alvo)
    assert not r["ok"], r["message"]
    assert not cs["turn_economy"]["acao_usada"]


def test_rendicao_do_ultimo_inimigo_encerra(luta, monkeypatch):
    _ch("Goblin")["status"] = "morto"
    _dados(monkeypatch, 20, 1, 1)
    _vez("Brann")
    r = td.combat_action("surrender", actor="Brann", target="Orc", weapon="intimidar")
    res = _fim(r)
    assert res and res["poupados"][0]["status"] == "rendido", r["message"]


# ---------------------------------------------------------------------------
# 3. Golpe não letal
# ---------------------------------------------------------------------------

def test_ligar_o_golpe_nao_letal_nao_gasta_o_turno(luta):
    _vez("Brann")
    r = td.combat_action("nao_letal", actor="Brann", weapon="sim")
    assert r["ok"] and "NOCAUTEAR" in r["message"]
    cartao = next(c for c in r["snapshot"]["combatants"] if c["name"] == "Brann")
    assert cartao["nao_letal"] is True
    assert not memory.campaign["combat_state"]["turn_economy"]["acao_usada"]


def test_corpo_a_corpo_nao_letal_nocauteia(luta, monkeypatch):
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda *a, **k: (18, "d20=18"))
    _ch("Orc")["sheet"]["vida_atual"] = 1
    _vez("Brann")
    td.combat_action("nao_letal", actor="Brann", weapon="sim")
    r = td.combat_action("attack", actor="Brann", target="Orc", weapon="espada longa")
    assert "NOCAUTEADO" in r["message"], r["message"]
    assert _ch("Orc")["status"] == "estabilizado" and _ch("Orc")["sheet"]["acorda_hora"]


def test_sem_o_golpe_nao_letal_o_npc_morre(luta, monkeypatch):
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda *a, **k: (18, "d20=18"))
    _ch("Orc")["sheet"]["vida_atual"] = 1
    _vez("Brann")
    td.combat_action("attack", actor="Brann", target="Orc", weapon="espada longa")
    assert _ch("Orc")["status"] == "morto"


def test_a_distancia_nao_nocauteia(luta, monkeypatch):
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda *a, **k: (18, "d20=18"))
    _ch("Orc")["sheet"]["vida_atual"] = 1
    _ch("Brann")["inventario"].append({"nome": "Arco Curto", "qtd": 1})
    _ch("Brann")["inventario"].append({"nome": "Flechas", "qtd": 20})
    _ch("Brann")["sheet"]["nao_letal"] = True
    td.attack_roll("Brann", "Orc", "arco curto", 6, end_turn=False, _skip_turn_check=True)
    assert _ch("Orc")["status"] == "morto"


def test_parametro_do_mestre(luta, monkeypatch):
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda *a, **k: (18, "d20=18"))
    _ch("Orc")["sheet"]["vida_atual"] = 1
    td.attack_roll("Brann", "Orc", "espada longa", 6, end_turn=False, nao_letal=True, _skip_turn_check=True)
    assert _ch("Orc")["status"] == "estabilizado"


def test_npc_nocauteado_acorda_com_1_pv(luta, monkeypatch):
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda *a, **k: (18, "d20=18"))
    monkeypatch.setattr(td.random, "randint", lambda a, b: b)          # 1d4 = 4 horas
    _ch("Orc")["sheet"]["vida_atual"] = 1
    td.attack_roll("Brann", "Orc", "espada longa", 6, end_turn=False, nao_letal=True, _skip_turn_check=True)
    td.end_combat()
    monkeypatch.undo()
    td.advance_time(3)
    assert _ch("Orc")["status"] == "estabilizado"
    r = td.advance_time(1)
    assert "Orc acorda do nocaute" in r, r
    assert _ch("Orc")["status"] == "inimigo" and _ch("Orc")["sheet"]["vida_atual"] == 1


def test_personagem_do_grupo_nocauteado_fica_estavel(luta, monkeypatch):
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda *a, **k: (18, "d20=18"))
    _ch("Brann")["sheet"]["vida_atual"] = 1
    _ch("Brann")["sheet"]["death_saves_falhas"] = 2
    td.attack_roll("Orc", "Brann", "espada longa", 6, end_turn=False, nao_letal=True, _skip_turn_check=True)
    assert _ch("Brann")["status"] == "estabilizado" and _ch("Brann")["sheet"]["death_saves_falhas"] == 0
    assert "acorda_hora" not in _ch("Brann")["sheet"]
