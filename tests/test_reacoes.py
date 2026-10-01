"""
test_reacoes.py

O turno do inimigo se resolve sozinho, e por isso só o ataque de oportunidade
existia como reação: o Escudo Arcano e a Contramágica apareciam como "o
Mestre decide", e a Esquiva Sobrenatural do ladino nunca reduziu um ponto de
dano. Agora o motor usa cada reação sozinho, no momento em que ela faz
diferença, e o jogador desliga a que não quiser (rpg/reacoes.py).
"""
import random

import pytest

from rpg import habilidade, memory, reacoes, resolucao, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _ch(nome):
    return memory.campaign["characters"][memory.char_key(nome)]


def _hab(nome, custo=0):
    return {"nome": nome, "custo_mana": custo, "dado": "", "descricao": ""}


def _d20(monkeypatch, valor):
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda *a, **k: (valor, f"d20={valor}"))


def _orc_ataca(alvo, arma="machado grande"):
    return td.attack_roll("Orc", alvo, arma, 12, end_turn=False, _skip_turn_check=True)


@pytest.fixture
def luta(campanha, povoar):
    def _montar(heroi):
        povoar(heroi, criar_ficha("Orc", vida=80, raca="orc", arma="machado grande"))
        iniciar_combate([heroi["name"], "Orc"], indice=1)
        td._reset_turn_economy(memory.campaign["combat_state"])
        return _ch(heroi["name"])
    return _montar


# ---------------------------------------------------------------------------
# Escudo Arcano
# ---------------------------------------------------------------------------

def _mago(**extra):
    return criar_ficha("Mira", grupo=True, classe="mago", nivel=5, ca=12, mana=10, vida=30,
                       habilidades=[_hab("Shield", 2), _hab("Counterspell", 5)], **extra)


def test_escudo_so_quando_os_cinco_fazem_errar(luta, monkeypatch):
    mira = luta(_mago())
    _d20(monkeypatch, 10)                       # 10 + 3 + 2 = 15 vs CA 12
    saida = _orc_ataca("Mira")
    assert "Escudo Arcano" in saida and "ERROU" in saida, saida
    assert mira["sheet"]["vida_atual"] == 30
    assert mira["sheet"]["mana_atual"] == 8
    assert td._ca_efetiva(mira) == 17
    assert not td._reaction_available(mira)


def test_escudo_nao_e_gasto_quando_nao_salva(luta, monkeypatch):
    mira = luta(_mago())
    _d20(monkeypatch, 15)                       # 20: acerta mesmo com +5
    saida = _orc_ataca("Mira")
    assert "Escudo Arcano" not in saida and "ACERTO" in saida
    assert mira["sheet"]["mana_atual"] == 10 and td._reaction_available(mira)


def test_escudo_nao_para_critico(luta, monkeypatch):
    # CA 22: o 20 natural soma 25, que os +5 (27) fariam errar — mas crítico
    # acerta sempre, e o motor não gasta o Escudo à toa.
    mira = luta(_mago())
    mira["sheet"]["ca"] = 22
    _d20(monkeypatch, 20)
    assert "Escudo Arcano" not in _orc_ataca("Mira")
    assert mira["sheet"]["mana_atual"] == 10


def test_escudo_desligado_nao_e_usado(luta, monkeypatch):
    mira = luta(_mago())
    reacoes.alternar("Mira", "escudo arcano", False)
    _d20(monkeypatch, 10)
    assert "Escudo Arcano" not in _orc_ataca("Mira")
    assert mira["sheet"]["vida_atual"] < 30


def test_escudo_sem_mana_nao_sai(luta, monkeypatch):
    mira = luta(_mago())
    mira["sheet"]["mana_atual"] = 1
    _d20(monkeypatch, 10)
    assert "Escudo Arcano" not in _orc_ataca("Mira")


# ---------------------------------------------------------------------------
# Esquiva Sobrenatural, Defletir Projéteis
# ---------------------------------------------------------------------------

def test_esquiva_sobrenatural_corta_o_dano_e_vale_uma_vez_por_rodada(luta, monkeypatch):
    ina = luta(criar_ficha("Ina", grupo=True, classe="ladino", nivel=5, vida=100, ca=10,
                           habilidades=[_hab("Esquiva Incrivelmente Baixa")]))
    _d20(monkeypatch, 15)
    monkeypatch.setattr(random, "randint", lambda a, b: b)     # dano máximo
    saida = _orc_ataca("Ina")
    assert "Esquiva Sobrenatural" in saida, saida
    # 1d12 máximo = 12 + 3 = 15 → 7.
    assert ina["sheet"]["vida_atual"] == 93
    _orc_ataca("Ina")                            # reação já gasta: dano cheio
    assert ina["sheet"]["vida_atual"] == 78


def test_defletir_projeteis_so_contra_arma_a_distancia(luta, monkeypatch):
    lin = luta(criar_ficha("Lin", grupo=True, classe="monge", nivel=5, vida=100, ca=10, destreza=16,
                           habilidades=[_hab("Desviar Projéteis")]))
    _d20(monkeypatch, 15)
    assert "Defletir" not in _orc_ataca("Lin")
    saida = _orc_ataca("Lin", "arco curto")
    assert "Defletir Projéteis" in saida, saida


# ---------------------------------------------------------------------------
# Repreensão Infernal, Retaliação, Bandeira de Aviso, Eu Ilusório
# ---------------------------------------------------------------------------

def test_repreensao_infernal_queima_quem_feriu(luta, monkeypatch):
    bruxo = luta(criar_ficha("Zed", grupo=True, classe="bruxo", nivel=3, vida=60, ca=10, mana=10,
                             habilidades=[_hab("Hellish Rebuke", 2)]))
    _d20(monkeypatch, 15)
    saida = _orc_ataca("Zed")
    assert "Repreensão Infernal" in saida, saida
    assert _ch("Orc")["sheet"]["vida_atual"] < 80
    assert bruxo["sheet"]["mana_atual"] == 8


def test_retaliacao_devolve_o_golpe(luta, monkeypatch):
    luta(criar_ficha("Ulf", grupo=True, classe="bárbaro", nivel=14, vida=100, ca=10,
                     habilidades=[_hab("Retaliação")]))
    _d20(monkeypatch, 15)
    saida = _orc_ataca("Ulf")
    assert "Ulf usa Retaliação" in saida and "Ulf ataca Orc" in saida, saida


def test_bandeira_de_aviso_da_desvantagem_e_gasta_uso(luta, monkeypatch):
    kae = luta(criar_ficha("Kae", grupo=True, classe="clérigo", nivel=1, sabedoria=16, vida=60,
                           habilidades=[_hab("Bandeira de Aviso")]))
    pedidos = []

    def rolar(vant, desv):
        pedidos.append(desv)
        return 15, "d20=15"
    monkeypatch.setattr(td, "_roll_d20_with_adv", rolar)
    assert "Bandeira de Aviso" in _orc_ataca("Kae")
    assert pedidos == [True]
    assert td.usos_restantes(kae, "Bandeira de Aviso") == 2


def test_eu_ilusorio_faz_o_golpe_errar_uma_vez(luta, monkeypatch):
    luta(criar_ficha("Ilo", grupo=True, classe="mago", nivel=10, vida=60, ca=10,
                     habilidades=[_hab("Eu Ilusório")]))
    _d20(monkeypatch, 15)
    assert "Eu Ilusório" in _orc_ataca("Ilo")
    assert _ch("Ilo")["sheet"]["vida_atual"] == 60
    memory.campaign["combat_state"]["round"] = 2
    assert "Eu Ilusório" not in _orc_ataca("Ilo")          # uma vez por descanso curto


# ---------------------------------------------------------------------------
# Contramágica
# ---------------------------------------------------------------------------

@pytest.fixture
def magos(campanha, povoar):
    povoar(_mago(),
           criar_ficha("Necro", vida=40, inteligencia=16, mana=30,
                       habilidades=[_hab("Fire Bolt"), _hab("Cone of Cold", 7)]))
    iniciar_combate(["Mira", "Necro"], indice=1)
    td._reset_turn_economy(memory.campaign["combat_state"])
    return memory.campaign


def test_contramagica_anula_magia_ate_o_terceiro_circulo(magos, monkeypatch):
    _d20(monkeypatch, 19)
    saida = td.use_ability("Necro", "Fire Bolt", "Mira", end_turn=False, _skip_turn_check=True)
    assert "Contramágica" in saida and "anulada" in saida, saida
    assert _ch("Mira")["sheet"]["vida_atual"] == 30
    assert _ch("Mira")["sheet"]["mana_atual"] == 5


def test_contramagica_acima_do_terceiro_e_teste(magos, monkeypatch):
    monkeypatch.setattr(random, "randint", lambda a, b: 1)
    saida = td.use_ability("Necro", "Cone of Cold", "Mira", end_turn=False, _skip_turn_check=True)
    assert "a magia passa" in saida, saida
    assert _ch("Necro")["sheet"]["mana_atual"] == 23     # a mana do inimigo foi
    assert _ch("Mira")["sheet"]["mana_atual"] == 5


def test_contramagica_nao_anula_aliado(magos):
    _ch("Necro")["lado"] = "aliado"
    saida = td.use_ability("Necro", "Fire Bolt", "Mira", end_turn=False, _skip_turn_check=True)
    assert "Contramágica" not in saida


# ---------------------------------------------------------------------------
# O cartão, a recusa e a tela
# ---------------------------------------------------------------------------

def test_magia_de_reacao_nao_se_conjura_no_turno(magos):
    r = resolucao.como_resolve(_hab("Shield", 2))
    assert r["tipo"] == "reacao" and "sozinho" in r["texto"]
    saida = td.use_ability("Mira", "Shield", "", _skip_turn_check=True)
    assert saida.startswith("Erro") and "reação" in saida
    assert _ch("Mira")["sheet"]["mana_atual"] == 10


def test_snapshot_lista_as_reacoes_e_o_estado(magos):
    snap = td._combatant_snapshot("Mira")
    assert {r["chave"]: r["ligada"] for r in snap["reacoes"]} == {"escudo arcano": True, "contramagica": True}
    reacoes.alternar("Mira", "contramagica", False)
    snap = td._combatant_snapshot("Mira")
    assert {r["chave"]: r["ligada"] for r in snap["reacoes"]}["contramagica"] is False
    assert "Escudo Arcano" in snap["passivas"] or any(
        h["nome"] == "Shield" for h in habilidade.sem_duplicatas(_ch("Mira")["habilidades"]))


def test_rota_liga_e_desliga(magos, monkeypatch):
    import server
    monkeypatch.setattr(memory, "save_campaign", lambda *a, **k: None)
    rota = server.combat_reacao_route.__wrapped__
    with server.app.test_request_context(json={"actor": "Mira", "reacao": "escudo arcano",
                                               "ligada": False}):
        corpo = rota().get_json()
    assert corpo["ok"] and "desligada" in corpo["message"]
    assert not td.reacao_automatica(_ch("Mira"), "escudo arcano")
    mira = next(c for c in corpo["snapshot"]["combatants"] if c["name"] == "Mira")
    assert {r["chave"]: r["ligada"] for r in mira["reacoes"]}["escudo arcano"] is False
    with server.app.test_request_context(json={"actor": "Mira", "reacao": "escudo arcano",
                                               "ligada": True}):
        assert "o motor usa" in rota().get_json()["message"]
