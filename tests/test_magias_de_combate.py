"""
test_magias_de_combate.py

Duzentas das 319 magias do compêndio caíam em "o Mestre decide". Muitas com
razão (Alarme, Compreender Idiomas), mas outras decidem uma luta: Santuário,
Imagem Espelhada, Piscar, Bordão Místico, Arma Mágica, Raio do
Enfraquecimento, Vínculo Protetor, Sinal de Esperança, Poupar os
Moribundos, Revivificar, as Restaurações, Passo Nebuloso, Voo. E não havia
como conjurar uma magia num círculo acima do dela: Curar Ferimentos curava
1d8 com qualquer mana.
"""
import random

import pytest

from rpg import memory, resolucao, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _ch(nome):
    return memory.campaign["characters"][memory.char_key(nome)]


def _hab(nome, custo=2):
    return {"nome": nome, "custo_mana": custo, "dado": "", "descricao": ""}


def _vez(nome):
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index(nome)
    cs["turn_token"] = int(cs.get("turn_token", 0) or 0) + 1
    td._reset_turn_economy(cs)


def _d20(monkeypatch, valor):
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda *a, **k: (valor, f"d20={valor}"))


def _salvaguardas(monkeypatch, passa):
    monkeypatch.setattr(td, "_rolar_salvaguarda",
                        lambda *a, **k: (passa, "salvaguarda: " + ("passou" if passa else "falhou")))


def _usar(ator, hab, alvo="", modo=""):
    _vez(ator)
    return td.combat_action("ability", actor=ator, ability=hab, target=alvo, weapon=modo)


MAGIAS = [_hab("Sanctuary"), _hab("Mirror Image", 3), _hab("Blink", 5), _hab("Shillelagh", 0),
          _hab("True Strike", 0), _hab("Magic Weapon", 3), _hab("Ray of Enfeeblement", 3),
          _hab("Enlarge/Reduce", 3), _hab("Branding Smite", 3), _hab("Warding Bond", 3),
          _hab("Beacon of Hope", 5), _hab("Spare the Dying", 0), _hab("Revivify", 5),
          _hab("Lesser Restoration", 3), _hab("Greater Restoration", 7), _hab("Remove Curse", 5),
          _hab("Protection from Poison", 3), _hab("Protection from Evil and Good"),
          _hab("Misty Step", 3), _hab("Fly", 5), _hab("Expeditious Retreat"),
          {"nome": "Cure Wounds", "custo_mana": 2, "dado": "1d8", "descricao": ""},
          {"nome": "Fireball", "custo_mana": 5, "dado": "8d6", "descricao": ""}]


@pytest.fixture
def luta(campanha, povoar):
    povoar(criar_ficha("Kaelen", grupo=True, classe="clérigo", nivel=9, sabedoria=16, forca=8,
                       mana=60, vida=40, arma="clava", habilidades=[dict(h) for h in MAGIAS]),
           criar_ficha("Alden", grupo=True, vida=40, ca=10),
           criar_ficha("Orc", vida=60, raca="orc", arma="machado grande", ca=10),
           criar_ficha("Zumbi", vida=60, raca="zumbi", tipo="undead", arma="pancada"))
    iniciar_combate(["Kaelen", "Alden", "Orc", "Zumbi"])
    _vez("Kaelen")
    return memory.campaign


@pytest.mark.parametrize("nome", [h["nome"] for h in MAGIAS[:21]])
def test_cartao_diz_que_o_motor_aplica(nome):
    r = resolucao.como_resolve(_hab(nome))
    assert r["tipo"] == "efeito" and r["texto"].startswith("O motor aplica"), r


# ---------------------------------------------------------------------------
# Defesa
# ---------------------------------------------------------------------------

def test_santuario_faz_o_atacante_perder_o_ataque(luta, monkeypatch):
    assert _usar("Kaelen", "Sanctuary", "Alden")["ok"]
    _salvaguardas(monkeypatch, False)
    saida = td.attack_roll("Orc", "Alden", "machado grande", 12, end_turn=False, _skip_turn_check=True)
    assert "Santuário o detém" in saida and _ch("Alden")["sheet"]["vida_atual"] == 40


def test_santuario_acaba_quando_o_protegido_ataca(luta, monkeypatch):
    _usar("Kaelen", "Sanctuary", "Alden")
    _d20(monkeypatch, 15)
    saida = td.attack_roll("Alden", "Orc", "espada longa", 8, end_turn=False, _skip_turn_check=True)
    assert "perde o Santuário" in saida
    assert not any(e.get("santuario") for e in td._efeitos_de(_ch("Alden")))


def test_imagem_espelhada_desvia_para_uma_copia(luta, monkeypatch):
    _usar("Kaelen", "Mirror Image")
    _d20(monkeypatch, 15)
    monkeypatch.setattr(random, "randint", lambda a, b: b)      # d20 da cópia = 20
    saida = td.attack_roll("Orc", "Kaelen", "machado grande", 12, end_turn=False, _skip_turn_check=True)
    assert "acerta uma cópia" in saida and "restam 2" in saida, saida
    assert _ch("Kaelen")["sheet"]["vida_atual"] == 40


def test_piscar_some_no_fim_do_turno_e_volta_no_inicio(luta, monkeypatch):
    _usar("Kaelen", "Blink")
    monkeypatch.setattr(random, "randint", lambda a, b: 15)
    td._fim_do_turno("Kaelen", 999)
    assert td._condicao_com(_ch("Kaelen"), "untargetable") == "Etéreo"
    assert td.attack_roll("Orc", "Kaelen", "machado grande", 12, end_turn=False,
                          _skip_turn_check=True).startswith("Erro")
    _vez("Kaelen")
    assert not td._condicao_com(_ch("Kaelen"), "untargetable")


def test_protecao_contra_o_mal_da_desvantagem_ao_morto_vivo(luta):
    _usar("Kaelen", "Protection from Evil and Good", "Alden")
    assert td._mods_de_ataque(_ch("Zumbi"), _ch("Alden"), True)["desvantagem"]
    assert not td._mods_de_ataque(_ch("Orc"), _ch("Alden"), True)["desvantagem"]


def test_vinculo_protetor_divide_o_dano(luta):
    _usar("Kaelen", "Warding Bond", "Alden")
    td._apply_damage(_ch("Alden"), 10, "slashing", source_name="Orc")
    assert _ch("Alden")["sheet"]["vida_atual"] == 35          # resistência: 5
    assert _ch("Kaelen")["sheet"]["vida_atual"] == 35         # o mesmo dano


# ---------------------------------------------------------------------------
# Ataque
# ---------------------------------------------------------------------------

def test_bordao_mistico_usa_sabedoria_e_d8(luta, monkeypatch):
    _usar("Kaelen", "Shillelagh")
    _d20(monkeypatch, 15)
    saida = td.attack_roll("Kaelen", "Orc", "clava", 4, end_turn=False, _skip_turn_check=True)
    assert "+3(mod)" in saida, saida


def test_golpe_certeiro_vantagem_so_no_alvo_e_uma_vez(luta):
    _usar("Kaelen", "True Strike", "Orc")
    assert not td._mods_de_ataque(_ch("Kaelen"), _ch("Zumbi"), True)["vantagem"]
    mods = td._mods_de_ataque(_ch("Kaelen"), _ch("Orc"), True)
    assert mods["vantagem"]
    for sh, e in mods["gastar"]:
        td._gastar_efeito(sh, e)
    assert not td._mods_de_ataque(_ch("Kaelen"), _ch("Orc"), True)["vantagem"]


def test_arma_magica_no_quarto_circulo_da_mais_dois(luta):
    r = _usar("Kaelen", "Magic Weapon", "Alden", "c4")
    assert r["ok"], r["message"]
    assert _ch("Kaelen")["sheet"]["mana_atual"] == 60 - td.SPELL_MANA_COST[4]
    assert td._mods_de_ataque(_ch("Alden"), _ch("Orc"), True)["bonus"] == 2
    # Só arma: o ataque mágico não ganha o bônus.
    assert td._mods_de_ataque(_ch("Alden"), _ch("Orc"), False, com_arma=False)["bonus"] == 0


def test_reduzir_inimigo_corta_o_dano_dele(luta, monkeypatch):
    _salvaguardas(monkeypatch, False)
    assert _usar("Kaelen", "Enlarge/Reduce", "Orc", "reduzir")["ok"]
    assert any(e.get("dano_dado") == "-1d4" for e in td._efeitos_de(_ch("Orc")))
    assert not _usar("Kaelen", "Enlarge/Reduce", "Orc")["ok"]          # sem escolha


def test_raio_do_enfraquecimento_corta_o_dano_de_forca(luta, monkeypatch):
    _d20(monkeypatch, 18)
    saida = _usar("Kaelen", "Ray of Enfeeblement", "Orc")["message"]
    assert "ENFRAQUECIDO" in saida, saida
    saida = td.attack_roll("Orc", "Alden", "machado grande", 12, end_turn=False, _skip_turn_check=True)
    assert "metade do dano da arma" in saida, saida


def test_destruicao_marcante_no_terceiro_circulo(luta, monkeypatch):
    _usar("Kaelen", "Branding Smite", modo="c3")
    _d20(monkeypatch, 15)
    saida = td.attack_roll("Kaelen", "Orc", "clava", 4, end_turn=False, _skip_turn_check=True)
    assert "Destruição Marcante: 3d6" in saida, saida


# ---------------------------------------------------------------------------
# Cura, morte e restauração
# ---------------------------------------------------------------------------

def test_sinal_de_esperanca_cura_no_maximo(luta):
    _usar("Kaelen", "Beacon of Hope")
    _ch("Alden")["sheet"]["vida_atual"] = 10
    saida = _usar("Kaelen", "Cure Wounds", "Alden")["message"]
    assert "a cura rola o máximo" in saida, saida
    assert _ch("Alden")["sheet"]["vida_atual"] == 10 + 8 + 3


def test_poupar_os_moribundos_estabiliza(luta):
    assert not _usar("Kaelen", "Spare the Dying", "Alden")["ok"]
    _ch("Alden")["sheet"]["vida_atual"] = 0
    _ch("Alden")["status"] = "inconsciente"
    assert _usar("Kaelen", "Spare the Dying", "Alden")["ok"]
    assert _ch("Alden")["status"] == "estabilizado"


def test_revivificar_exige_diamante_e_morte_recente(luta):
    alden = _ch("Alden")
    alden["sheet"]["vida_atual"] = 0
    alden["status"] = "morto"
    alden["sheet"]["morreu_hora"] = td._agora_em_horas()
    r = _usar("Kaelen", "Revivify", "Alden")
    assert not r["ok"] and "diamante" in r["message"]
    _ch("Kaelen")["inventario"] = [{"nome": "Diamante", "qtd": 1}]
    alden["sheet"]["morreu_hora"] = td._agora_em_horas() - 3
    assert "tempo demais" in _usar("Kaelen", "Revivify", "Alden")["message"]
    alden["sheet"]["morreu_hora"] = td._agora_em_horas()
    assert _usar("Kaelen", "Revivify", "Alden")["ok"]
    assert alden["status"] == "vivo" and alden["sheet"]["vida_atual"] == 1
    assert not _ch("Kaelen")["inventario"]


def test_monstro_derrotado_guarda_a_hora_da_morte(luta):
    td._mark_at_zero_hp(_ch("Orc"), "Alden")
    assert _ch("Orc")["sheet"]["morreu_hora"] == td._agora_em_horas()


@pytest.mark.parametrize("magia, condicao", [
    ("Lesser Restoration", "Paralisado"),
    ("Greater Restoration", "Petrificado"),
    ("Remove Curse", "Amaldiçoado"),
    ("Protection from Poison", "Envenenado"),
])
def test_restauracoes_tiram_a_condicao(luta, magia, condicao):
    _ch("Alden")["sheet"]["condicoes"] = [{"nome": condicao, "duracao": None}]
    assert _usar("Kaelen", magia, "Alden")["ok"]
    assert not _ch("Alden")["sheet"]["condicoes"]


def test_restauracao_maior_tira_exaustao(luta):
    _ch("Alden")["sheet"]["exaustao"] = 2
    _usar("Kaelen", "Greater Restoration", "Alden")
    assert _ch("Alden")["sheet"]["exaustao"] == 1


# ---------------------------------------------------------------------------
# Movimento
# ---------------------------------------------------------------------------

def _zonas(luta):
    cs = memory.campaign["combat_state"]
    cs["zonas"] = ["Portão", "Pátio", "Sacada"]
    cs["posicoes"] = {"kaelen": "Portão", "alden": "Portão", "orc": "Portão", "zumbi": "Sacada"}


def test_passo_nebuloso_vai_para_a_zona_vizinha(luta):
    _zonas(luta)
    assert not _usar("Kaelen", "Misty Step", modo="Sacada")["ok"]
    assert _usar("Kaelen", "Misty Step", modo="Pátio")["ok"]
    assert td._zona_de("Kaelen") == "Pátio"


def test_voo_da_mais_uma_zona_a_cada_turno(luta):
    _usar("Kaelen", "Fly", "Alden")
    _vez("Alden")
    assert memory.campaign["combat_state"]["turn_economy"]["movimento_extra"] == 1


def test_recuo_acelerado_vale_ja(luta):
    _usar("Kaelen", "Expeditious Retreat")
    assert memory.campaign["combat_state"]["turn_economy"]["movimento_extra"] == 1


# ---------------------------------------------------------------------------
# Conjurar com mais mana
# ---------------------------------------------------------------------------

def test_circulos_respeitam_nivel_e_mana(luta):
    ops = resolucao.circulos_da_magia(_hab("Cure Wounds"), _ch("Kaelen"))
    assert list(ops) == ["c1", "c2", "c3", "c4", "c5"]       # clérigo 9: até o 5º
    assert "2d8" in ops["c2"]
    _ch("Kaelen")["sheet"]["mana_atual"] = 4
    assert list(resolucao.circulos_da_magia(_hab("Cure Wounds"), _ch("Kaelen"))) == ["c1", "c2"]


def test_curar_ferimentos_no_segundo_circulo(luta, monkeypatch):
    monkeypatch.setattr(random, "randint", lambda a, b: b)
    _ch("Alden")["sheet"]["vida_atual"] = 1
    r = _usar("Kaelen", "Cure Wounds", "Alden", "c2")
    assert r["ok"], r["message"]
    assert _ch("Alden")["sheet"]["vida_atual"] == 1 + 16 + 3
    assert _ch("Kaelen")["sheet"]["mana_atual"] == 60 - td.SPELL_MANA_COST[2]


def test_bola_de_fogo_no_quarto_circulo(luta):
    assert resolucao.dado_no_circulo(_hab("Fireball"), "8d6", 4) == "9d6"


def test_circulo_alem_do_nivel_e_recusado(luta):
    r = _usar("Kaelen", "Cure Wounds", "Alden", "c9")
    assert not r["ok"] and "círculo" in r["message"]
    assert _ch("Kaelen")["sheet"]["mana_atual"] == 60
