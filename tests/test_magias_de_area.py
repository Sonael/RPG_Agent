"""
test_magias_de_area.py

Escuridão, Névoa Obscurecente, Silêncio e Polimorfia eram "o Mestre decide".
As três primeiras cobrem uma área, e a área do jogo é a zona: a magia cobre a
zona escolhida enquanto durar a concentração. A Polimorfia transforma a ficha
como a Forma Selvagem faz, mas troca também a mente e acaba com a
concentração de quem conjurou.
"""
import random

import pytest

from rpg import criaturas, memory, resolucao, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _ch(nome):
    return memory.campaign["characters"].get(memory.char_key(nome))


def _hab(nome, custo=3):
    return {"nome": nome, "custo_mana": custo, "dado": "", "descricao": ""}


def _vez(nome):
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index(nome)
    cs["turn_token"] = int(cs.get("turn_token", 0) or 0) + 1
    td._reset_turn_economy(cs)


def _usar(ator, hab, alvo="", modo=""):
    _vez(ator)
    return td.combat_action("ability", actor=ator, ability=hab, target=alvo, weapon=modo)


@pytest.fixture
def luta(campanha, povoar):
    povoar(criar_ficha("Mira", grupo=True, classe="mago", nivel=9, inteligencia=18, mana=60, vida=40,
                       habilidades=[_hab("Darkness"), _hab("Fog Cloud", 2), _hab("Silence"),
                                    _hab("Polymorph", 6), _hab("Hold Person"), _hab("Thunderwave", 2),
                                    _hab("Fire Bolt", 0), _hab("Bless", 2)]),
           criar_ficha("Alden", grupo=True, vida=40, nivel=5, ca=10),
           criar_ficha("Orc", vida=60, raca="orc", arma="machado grande", ca=10, nivel=1, cr="1/2"),
           criar_ficha("Ogro", vida=60, raca="ogro", arma="clava grande", ca=10, nivel=2, cr="2"))
    iniciar_combate(["Mira", "Alden", "Orc", "Ogro"])
    cs = memory.campaign["combat_state"]
    cs["zonas"] = ["Portão", "Pátio", "Sacada"]
    cs["posicoes"] = {"mira": "Portão", "alden": "Pátio", "orc": "Pátio", "ogro": "Sacada"}
    _vez("Mira")
    return memory.campaign


@pytest.mark.parametrize("nome, trecho", [("Darkness", "escuridão"), ("Fog Cloud", "névoa"),
                                          ("Silence", "som"), ("Polymorph", "fera")])
def test_cartao(nome, trecho):
    r = resolucao.como_resolve(_hab(nome))
    assert r["tipo"] == "efeito" and trecho in r["texto"], r


# ---------------------------------------------------------------------------
# Escuridão e Névoa
# ---------------------------------------------------------------------------

def test_escuridao_cobre_a_zona_escolhida(luta):
    assert not _usar("Mira", "Darkness")["ok"]                       # sem zona
    r = _usar("Mira", "Darkness", modo="Pátio")
    assert r["ok"], r["message"]
    assert td._zona_obscurecida("Orc") and td._zona_obscurecida("Alden")
    assert not td._zona_obscurecida("Mira")
    assert td.combat_snapshot()["zonas_efeito"]["Pátio"] == ["Escuridão"]


def test_na_escuridao_vantagem_e_desvantagem_se_anulam(luta, monkeypatch):
    _usar("Mira", "Fog Cloud", modo="Pátio")
    pedidos = []
    monkeypatch.setattr(td, "_roll_d20_with_adv",
                        lambda v, d: (pedidos.append((v, d)), (10, "d20=10"))[1])
    saida = td.attack_roll("Orc", "Alden", "machado grande", 12, end_turn=False, _skip_turn_check=True)
    assert pedidos == [(True, True)] and "se anulam" in saida, saida


def test_magia_que_exige_ver_nao_passa(luta):
    _usar("Mira", "Darkness", modo="Pátio")
    r = _usar("Mira", "Hold Person", "Orc")
    assert not r["ok"] and "exige ver o alvo" in r["message"]
    assert _ch("Mira")["sheet"]["mana_atual"] == 60 - 3      # só a Escuridão foi paga


def test_esconder_na_nevoa_e_automatico(luta, monkeypatch):
    _usar("Mira", "Fog Cloud", modo="Pátio")
    _vez("Alden")
    monkeypatch.setattr(random, "randint", lambda a, b: 1)     # no dado, falharia
    r = td.combat_action("hide", actor="Alden")
    assert r["ok"] and "ESCONDIDO" in r["message"]


def test_a_area_cai_com_a_concentracao_e_com_o_combate(luta):
    _usar("Mira", "Darkness", modo="Pátio")
    _usar("Mira", "Bless", "Alden")                      # outra concentração
    assert not td._zona_obscurecida("Orc")
    _usar("Mira", "Fog Cloud", modo="Sacada")
    td.end_combat()
    assert "efeitos_de_zona" not in memory.campaign["combat_state"]


# ---------------------------------------------------------------------------
# Sem zonas: a área fica centrada numa criatura
# ---------------------------------------------------------------------------

@pytest.fixture
def sem_zonas(luta):
    cs = memory.campaign["combat_state"]
    cs.pop("zonas")
    cs.pop("posicoes")
    return luta


def test_sem_zonas_pede_a_criatura_do_centro(sem_zonas):
    r = _usar("Mira", "Darkness")
    assert not r["ok"] and "centrada numa criatura" in r["message"]
    assert _ch("Mira")["sheet"]["mana_atual"] == 60
    texto = resolucao.como_resolve(_hab("Darkness"), _ch("Mira"))["texto"]
    assert "centrada na criatura" in texto and "zona" not in texto


def test_silencio_no_mago_inimigo_o_cala(sem_zonas):
    _ch("Ogro")["habilidades"] = [_hab("Fire Bolt", 0)]
    r = _usar("Mira", "Silence", "Ogro")
    assert r["ok"] and "centrada em Ogro" in r["message"], r["message"]
    _vez("Ogro")
    assert td.use_ability("Ogro", "Fire Bolt", "Mira", _skip_turn_check=True).startswith("Erro")
    # Só ele: Mira, fora da área, conjura.
    assert _usar("Mira", "Fire Bolt", "Orc")["ok"]
    assert td._zona_silenciada("Ogro") and not td._zona_silenciada("Mira")


def test_escuridao_em_si_esconde_e_anula(sem_zonas, monkeypatch):
    assert _usar("Mira", "Darkness", "Mira")["ok"]
    pedidos = []
    monkeypatch.setattr(td, "_roll_d20_with_adv",
                        lambda v, d: (pedidos.append((v, d)), (10, "d20=10"))[1])
    td.attack_roll("Orc", "Mira", "machado grande", 12, end_turn=False, _skip_turn_check=True)
    # O primeiro d20 é o do ataque (o segundo, se houver, é o teste de
    # concentração de Mira, que tomou dano mantendo a Escuridão).
    assert pedidos[0] == (True, True)
    # Outro alvo, fora da área: ataque normal.
    pedidos.clear()
    td.attack_roll("Orc", "Alden", "machado grande", 12, end_turn=False, _skip_turn_check=True)
    assert pedidos == [(False, False)]
    monkeypatch.setattr(random, "randint", lambda a, b: 1)
    _vez("Mira")
    assert "ESCONDIDO" in td.combat_action("hide", actor="Mira")["message"]


def test_nevoa_no_alvo_bloqueia_magia_que_exige_ver(sem_zonas):
    _usar("Mira", "Fog Cloud", "Orc")
    r = _usar("Mira", "Hold Person", "Orc")
    assert not r["ok"] and "exige ver o alvo" in r["message"]


def test_sem_zonas_a_area_aparece_no_cartao(sem_zonas):
    _usar("Mira", "Silence", "Ogro")
    assert "Silêncio" in td._combatant_snapshot("Ogro")["condicoes"]
    assert "Silêncio" not in td._combatant_snapshot("Mira")["condicoes"]


def test_sem_zonas_a_area_cai_com_a_concentracao(sem_zonas):
    _usar("Mira", "Silence", "Ogro")
    _usar("Mira", "Bless", "Alden")
    assert not td._zona_silenciada("Ogro")


def test_tela_pede_alvo_sem_zonas(sem_zonas):
    from rpg import habilidade
    assert habilidade.resolver(_hab("Darkness"), _ch("Mira"))["alvo_modo"] == "aliado"
    memory.campaign["combat_state"]["zonas"] = ["Portão", "Pátio"]
    assert habilidade.resolver(_hab("Darkness"), _ch("Mira"))["alvo_modo"] == "nenhum"


def test_fora_do_combate_o_mestre_narra(campanha, povoar):
    povoar(criar_ficha("Mira", grupo=True, classe="mago", nivel=9, mana=60,
                       habilidades=[_hab("Darkness")]))
    r = td.conjurar_fora_de_combate("Mira", "Darkness", "Mira")
    assert r["ok"] and "Mestre" in r["message"]


# ---------------------------------------------------------------------------
# Silêncio
# ---------------------------------------------------------------------------

def test_silencio_impede_componente_verbal(luta):
    _usar("Mira", "Silence", modo="Portão")
    r = _usar("Mira", "Fire Bolt", "Orc")
    assert not r["ok"] and "componente verbal" in r["message"]


def test_silencio_anula_trovao(luta):
    _usar("Mira", "Silence", modo="Pátio")
    res = td._apply_damage(_ch("Orc"), 9, "thunder", source_name="Mira")
    assert res["dano"] == 0 and "imune a trovão" in " ".join(res["notas"])
    assert not (_ch("Orc")["sheet"].get("imunidades") or [])        # não vira traço da ficha
    res = td._apply_damage(_ch("Orc"), 9, "fire", source_name="Mira")
    assert res["dano"] == 9


# ---------------------------------------------------------------------------
# Polimorfia
# ---------------------------------------------------------------------------

def test_polimorfia_no_inimigo_vira_rato_e_volta_com_a_concentracao(luta, monkeypatch):
    monkeypatch.setattr(td, "_rolar_salvaguarda", lambda *a, **k: (False, "salvaguarda: falhou"))
    r = _usar("Mira", "Polymorph", "Ogro", "rato")
    assert r["ok"], r["message"]
    s = _ch("Ogro")["sheet"]
    assert s["vida_atual"] == 1 and s["inteligencia"] == 2
    assert [a["nome"] for a in s["ataques"]] == ["mordida"]
    td._break_concentration(_ch("Mira"), "teste")
    assert not criaturas.em_forma_selvagem(_ch("Ogro"))
    assert _ch("Ogro")["sheet"]["vida_atual"] == 60


def test_polimorfia_que_falha_na_salvaguarda_nao_pega(luta, monkeypatch):
    monkeypatch.setattr(td, "_rolar_salvaguarda", lambda *a, **k: (True, "salvaguarda: passou"))
    r = _usar("Mira", "Polymorph", "Ogro", "rato")
    assert r["ok"] and "resistiu" in r["message"]
    assert not criaturas.em_forma_selvagem(_ch("Ogro"))


def test_polimorfia_no_aliado_respeita_o_nivel(luta):
    r = _usar("Mira", "Polymorph", "Alden", "urso polar")
    assert r["ok"], r["message"]
    assert _ch("Alden")["sheet"]["vida_atual"] == 42
    # Fera forte demais para o orc (ND 1/2): recusa sem gastar.
    _vez("Mira")
    mana = _ch("Mira")["sheet"]["mana_atual"]
    r = _usar("Mira", "Polymorph", "Orc", "urso pardo")
    assert not r["ok"] and "forte demais" in r["message"]
    assert _ch("Mira")["sheet"]["mana_atual"] == mana


def test_rato_polimorfado_ataca_por_um(luta, monkeypatch):
    monkeypatch.setattr(td, "_rolar_salvaguarda", lambda *a, **k: (False, "salvaguarda: falhou"))
    _usar("Mira", "Polymorph", "Orc", "rato")
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda *a, **k: (19, "d20=19"))
    monkeypatch.setattr(random, "randint", lambda a, b: b)            # dano máximo
    vida = _ch("Alden")["sheet"]["vida_atual"]
    _vez("Orc")
    saida = td._executar_turno_npc("Orc")
    # A mordida do rato (1d1), não a arma de antes nem um golpe genérico.
    assert "mordida" in saida.lower() and "machado" not in saida.lower(), saida
    assert vida - _ch("Alden")["sheet"]["vida_atual"] == 1


def test_fera_que_cai_volta_ao_ogro(luta, monkeypatch):
    monkeypatch.setattr(td, "_rolar_salvaguarda", lambda *a, **k: (False, "salvaguarda: falhou"))
    _usar("Mira", "Polymorph", "Ogro", "gato")
    td._apply_damage(_ch("Ogro"), 5, "fire", source_name="Alden")
    assert not criaturas.em_forma_selvagem(_ch("Ogro"))
    assert _ch("Ogro")["sheet"]["vida_atual"] == 60 - 3
