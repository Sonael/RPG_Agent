"""
test_polimorfia_verdadeira_e_elemental.py

Polimorfia Verdadeira e Conjurar Elemental eram "o Mestre decide".

Polimorfia Verdadeira: a mesma troca de ficha da Polimorfia, mas para
qualquer criatura (não só fera) ou para um objeto, que sai da luta; com uma
hora de concentração, fica permanente.

Conjurar Elemental: um minuto de conjuração, então só fora do combate (SRD).
O elemental acompanha o dono na próxima luta e, se a concentração cair, não
some — vira inimigo do grupo.
"""
import pytest

from rpg import criaturas, memory, resolucao, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _ch(nome):
    return memory.campaign["characters"].get(memory.char_key(nome))


def _hab(nome, custo=13):
    return {"nome": nome, "custo_mana": custo, "dado": "", "descricao": "[Transmutação] ",
            "nivel_magia": (resolucao._magia_srd({"nome": nome}) or {}).get("nivel", 1)}


def _vez(nome):
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index(nome)
    cs["turn_token"] = int(cs.get("turn_token", 0) or 0) + 1
    td._reset_turn_economy(cs)


def _usar(ator, hab, alvo="", modo=""):
    _vez(ator)
    return td.combat_action("ability", actor=ator, ability=hab, target=alvo, weapon=modo)


def _falha(monkeypatch, passa=False):
    monkeypatch.setattr(td, "_rolar_salvaguarda", lambda *a, **k: (passa, "salvaguarda: " + ("passou" if passa else "falhou")))


@pytest.fixture
def mago(campanha, povoar):
    povoar(criar_ficha("Mira", grupo=True, classe="mago", nivel=17, inteligencia=20, mana=133, vida=80,
                       habilidades=[_hab("True Polymorph"), _hab("Conjure Elemental", 7), _hab("Bless", 2)]),
           criar_ficha("Alden", grupo=True, vida=60, nivel=6),
           criar_ficha("Dragão", vida=150, raca="dragão", arma="mordida", nivel=10, cr="10"),
           criar_ficha("Orc", vida=30, raca="orc", arma="machado grande", nivel=1, cr="1/2"))
    return memory.campaign


@pytest.fixture
def luta(mago):
    iniciar_combate(["Mira", "Alden", "Dragão", "Orc"])
    _vez("Mira")
    return mago


def test_cartoes():
    assert resolucao.como_resolve(_hab("True Polymorph"))["tipo"] == "efeito"
    assert resolucao.como_resolve(_hab("Conjure Elemental"))["tipo"] == "efeito"


# ---------------------------------------------------------------------------
# Polimorfia Verdadeira
# ---------------------------------------------------------------------------

def test_formas_incluem_elemental_e_objeto(mago):
    modos = resolucao.como_resolve(_hab("True Polymorph"), _ch("Mira"))["modos"]
    assert "elemental do fogo" in modos and "objeto" in modos and "urso polar" in modos
    assert "elemental do fogo" not in resolucao.como_resolve(_hab("Polymorph", 6), _ch("Mira"))["modos"]


def test_aliado_vira_elemental(luta):
    r = _usar("Mira", "True Polymorph", "Alden", "elemental da terra")
    assert r["ok"], r["message"]
    s = _ch("Alden")["sheet"]
    assert s["vida_atual"] == 126 and s["ca"] == 17


def test_respeita_o_nd_do_alvo(luta):
    r = _usar("Mira", "True Polymorph", "Orc", "elemental do ar")
    assert not r["ok"] and "forte demais" in r["message"]


def test_inimigo_vira_objeto_e_sai_da_luta(luta, monkeypatch):
    _falha(monkeypatch)
    r = _usar("Mira", "True Polymorph", "Dragão", "objeto")
    assert r["ok"] and "objeto" in r["message"], r["message"]
    assert td._impedido_de_agir(_ch("Dragão"))
    assert td.attack_roll("Alden", "Dragão", "espada longa", 8, end_turn=False,
                          _skip_turn_check=True).startswith("Erro")
    # A concentração cai: volta a ser dragão.
    td._break_concentration(_ch("Mira"), "teste")
    assert not td._impedido_de_agir(_ch("Dragão"))


def test_inimigo_que_passa_na_salvaguarda(luta, monkeypatch):
    _falha(monkeypatch, passa=True)
    r = _usar("Mira", "True Polymorph", "Dragão", "objeto")
    assert r["ok"] and "resistiu" in r["message"]
    assert not td._impedido_de_agir(_ch("Dragão"))


def test_uma_hora_de_concentracao_torna_permanente(mago, monkeypatch):
    _falha(monkeypatch)
    r = td.conjurar_fora_de_combate("Mira", "True Polymorph", "Orc", modo="rato")
    assert r["ok"], r["message"]
    saida = td.advance_time(1, "a hora passa")
    assert "permanente" in saida, saida
    td._break_concentration(_ch("Mira"), "teste")
    assert criaturas.em_forma_selvagem(_ch("Orc"))["forma"] == "Rato"
    # Nem o fim de um combate desfaz.
    iniciar_combate(["Mira", "Orc"])
    td.end_combat()
    assert criaturas.em_forma_selvagem(_ch("Orc"))


def test_objeto_permanente_sobrevive_ao_combate(mago, monkeypatch):
    _falha(monkeypatch)
    td.conjurar_fora_de_combate("Mira", "True Polymorph", "Dragão", modo="objeto")
    td.advance_time(1, "a hora passa")
    td._break_concentration(_ch("Mira"), "teste")
    iniciar_combate(["Mira", "Dragão"])
    assert td._impedido_de_agir(_ch("Dragão"))
    td.end_combat()
    assert any(c.get("nome") == "Objeto" for c in _ch("Dragão")["sheet"]["condicoes"])


def test_sem_a_hora_inteira_volta(mago, monkeypatch):
    _falha(monkeypatch)
    td.conjurar_fora_de_combate("Mira", "True Polymorph", "Orc", modo="rato")
    td._break_concentration(_ch("Mira"), "teste")
    assert not criaturas.em_forma_selvagem(_ch("Orc"))


# ---------------------------------------------------------------------------
# Conjurar Elemental
# ---------------------------------------------------------------------------

def test_elemental_nao_se_conjura_na_luta(luta):
    r = _usar("Mira", "Conjure Elemental", modo="elemental do fogo:1")
    assert not r["ok"] and "1 minuto" in r["message"]


def test_elemental_entra_na_proxima_luta(mago):
    r = td.conjurar_fora_de_combate("Mira", "Conjure Elemental", modo="elemental do fogo:1")
    assert r["ok"], r["message"]
    fogo = _ch("Elemental do Fogo de Mira")
    assert fogo and fogo["sheet"]["vida_max"] == 102
    td.roll_initiative("Mira, Alden, Orc")
    assert "Elemental do Fogo de Mira" in memory.campaign["combat_state"]["initiative_order"]
    assert memory.lado_no_combate(fogo) == "aliado"


def test_concentracao_perdida_o_elemental_vira_inimigo(mago):
    td.conjurar_fora_de_combate("Mira", "Conjure Elemental", modo="elemental da terra:1")
    td.roll_initiative("Mira, Alden, Orc")
    td._break_concentration(_ch("Mira"), "dano")
    terra = _ch("Elemental da Terra de Mira")
    assert terra is not None, "o elemental não some"
    assert memory.lado_no_combate(terra) == "inimigo"


def test_resistencia_so_contra_arma_comum(mago):
    td.conjurar_fora_de_combate("Mira", "Conjure Elemental", modo="elemental da agua:1")
    agua = _ch("Elemental da Água de Mira")
    comum = td._apply_damage(agua, 10, "slashing", source_name="Orc", arma_magica=False)
    magica = td._apply_damage(agua, 10, "slashing", source_name="Orc", arma_magica=True)
    assert comum["dano"] == 5 and magica["dano"] == 10


def test_elemental_some_em_uma_hora(mago):
    td.conjurar_fora_de_combate("Mira", "Conjure Elemental", modo="elemental do ar:1")
    td.advance_time(2, "espera")
    assert _ch("Elemental do Ar de Mira") is None
