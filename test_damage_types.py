"""
test_damage_types.py
Tipos de dano, resistência/imunidade/vulnerabilidade e PV temporários.

O QUE ESTES TESTES TRANCAM
──────────────────────────
Antes, o dano era subtraído cru do HP: `vida_atual -= dmg`. Sem tipo de dano
não existe resistência, imunidade nem vulnerabilidade — o esqueleto morria de
veneno, o elemental do fogo se queimava, e a escolha de arma contra um alvo
específico não tinha efeito nenhum. Todo dano passa agora por _apply_damage().
"""

import pytest

import tools_dnd as T
from conftest import criar_ficha


# ---------------------------------------------------------------------------
# Reconhecimento de tipo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("entrada, esperado", [
    ("fogo", "fire"), ("Fogo", "fire"), ("fire", "fire"),
    ("frio", "cold"), ("gelo", "cold"),
    ("veneno", "poison"), ("poison", "poison"),
    ("cortante", "slashing"), ("perfurante", "piercing"),
    ("concussão", "bludgeoning"), ("concussao", "bludgeoning"),
    ("radiante", "radiant"), ("necrótico", "necrotic"),
    ("elétrico", "lightning"), ("raio", "lightning"),
    ("psíquico", "psychic"), ("trovejante", "thunder"),
    ("banana", ""), ("", ""),
])
def test_normaliza_tipo_pt_e_en(entrada, esperado):
    assert T._norm_damage_type(entrada) == esperado


@pytest.mark.parametrize("texto, esperado", [
    ("Hit: 14 (2d8 + 5) slashing damage.", "slashing"),
    ("Melee Weapon Attack: +7 to hit. Hit: 10 (1d10 + 5) piercing damage.", "piercing"),
    ("[Evocação] Cone de 4,5m, 3d6 dano de fogo. DEX salva metade.", "fire"),
    ("[Necromancia] 3d6 dano necrótico ao toque.", "necrotic"),
    ("[Abjuração] Alvo ganha +2 de CA.", ""),          # sem dano → sem tipo
])
def test_descobre_tipo_no_texto(texto, esperado):
    assert T._damage_type_from_text(texto) == esperado


@pytest.mark.parametrize("arma, esperado", [
    ("espada longa", "slashing"), ("machado grande", "slashing"),
    ("adaga", "piercing"), ("arco longo", "piercing"), ("bite", "piercing"),
    ("maça", "bludgeoning"), ("cajado", "bludgeoning"), ("slam", "bludgeoning"),
    ("ataque desarmado", "bludgeoning"),
    ("objeto estranho", ""),
])
def test_tipo_pela_arma(arma, esperado):
    assert T._weapon_damage_type(arma) == esperado


# ---------------------------------------------------------------------------
# Leitura dos campos do Open5e
# ---------------------------------------------------------------------------

def test_le_imunidade_simples():
    traits = T._parse_damage_traits("poison")
    assert traits[0]["tipos"] == ["poison"]
    assert traits[0]["requer_magica"] is False


def test_le_lista_de_tipos():
    traits = T._parse_damage_traits("fire, cold")
    assert set(traits[0]["tipos"]) == {"fire", "cold"}


def test_preserva_a_qualificacao_de_arma_nao_magica():
    """
    "bludgeoning, piercing, and slashing from nonmagical attacks" é a
    armadilha: aplicar isso sem modelar armas mágicas deixaria o lobisomem
    praticamente imune ao grupo.
    """
    traits = T._parse_damage_traits(
        "bludgeoning, piercing, and slashing from nonmagical attacks")
    assert set(traits[0]["tipos"]) == {"bludgeoning", "piercing", "slashing"}
    assert traits[0]["requer_magica"] is True


def test_campo_vazio_nao_vira_resistencia():
    assert T._parse_damage_traits("") == []
    assert T._parse_damage_traits(None) == []
    assert T._parse_damage_traits("nenhuma") == []


# ---------------------------------------------------------------------------
# Multiplicadores
# ---------------------------------------------------------------------------

def _sheet(**kw):
    return criar_ficha("X", **kw)["sheet"]


def test_imunidade_zera():
    s = _sheet(imunidades=T._parse_damage_traits("poison"))
    mult, nota = T._damage_multiplier(s, "poison")
    assert mult == 0.0
    assert "IMUNE" in nota


def test_resistencia_corta_pela_metade():
    s = _sheet(resistencias=T._parse_damage_traits("fire"))
    assert T._damage_multiplier(s, "fire")[0] == 0.5


def test_vulnerabilidade_dobra():
    s = _sheet(vulnerabilidades=T._parse_damage_traits("fire"))
    assert T._damage_multiplier(s, "fire")[0] == 2.0


def test_resistencia_e_vulnerabilidade_se_cancelam():
    s = _sheet(resistencias=T._parse_damage_traits("fire"),
               vulnerabilidades=T._parse_damage_traits("fire"))
    assert T._damage_multiplier(s, "fire")[0] == 1.0


def test_imunidade_vence_vulnerabilidade():
    s = _sheet(imunidades=T._parse_damage_traits("fire"),
               vulnerabilidades=T._parse_damage_traits("fire"))
    assert T._damage_multiplier(s, "fire")[0] == 0.0


def test_dano_sem_tipo_nunca_e_modificado():
    s = _sheet(imunidades=T._parse_damage_traits("poison"))
    assert T._damage_multiplier(s, "")[0] == 1.0


def test_tipo_diferente_nao_e_afetado():
    s = _sheet(resistencias=T._parse_damage_traits("fire"))
    assert T._damage_multiplier(s, "cold")[0] == 1.0


def test_arma_magica_fura_resistencia_qualificada():
    s = _sheet(resistencias=T._parse_damage_traits(
        "bludgeoning, piercing, and slashing from nonmagical attacks"))
    assert T._damage_multiplier(s, "slashing", arma_magica=False)[0] == 0.5
    assert T._damage_multiplier(s, "slashing", arma_magica=True)[0] == 1.0


def test_arma_magica_nao_fura_resistencia_incondicional():
    s = _sheet(resistencias=T._parse_damage_traits("fire"))
    assert T._damage_multiplier(s, "fire", arma_magica=True)[0] == 0.5


@pytest.mark.parametrize("arma, fura", [
    ("Espada Longa +1", True),          # mágica
    ("espada prateada", True),          # o SRD diz "that aren't silvered"
    ("adaga de prata", True),
    ("machado adamantino", True),
    ("espada longa", False),
    ("porrete", False),
])
def test_arma_que_fura_resistencia_qualificada(arma, fura):
    """
    A espada prateada existe justamente para caçar lobisomem; sem reconhecer
    o material, ela faria zero dano igual a um pedaço de pau.
    """
    assert T._bypasses_material_resistance(arma) is fura


# ---------------------------------------------------------------------------
# _apply_damage
# ---------------------------------------------------------------------------

def test_imune_nao_perde_nenhum_pv():
    alvo = criar_ficha("Esqueleto", vida=20,
                       imunidades=T._parse_damage_traits("poison"))
    res = T._apply_damage(alvo, 12, "poison")
    assert res["dano"] == 0
    assert alvo["sheet"]["vida_atual"] == 20


def test_resistente_perde_metade_arredondada_para_baixo():
    alvo = criar_ficha("Golem", vida=40,
                       resistencias=T._parse_damage_traits("fire"))
    res = T._apply_damage(alvo, 9, "fogo")
    assert res["dano"] == 4                       # 9 // 2
    assert alvo["sheet"]["vida_atual"] == 36


def test_vulneravel_perde_o_dobro():
    alvo = criar_ficha("Múmia", vida=40,
                       vulnerabilidades=T._parse_damage_traits("fire"))
    res = T._apply_damage(alvo, 7, "fogo")
    assert res["dano"] == 14
    assert alvo["sheet"]["vida_atual"] == 26


def test_resistencia_nunca_zera_um_golpe_que_acertou():
    """1 de dano com resistência daria 0; um acerto tem que doer pelo menos 1."""
    alvo = criar_ficha("Golem", vida=10,
                       resistencias=T._parse_damage_traits("fire"))
    assert T._apply_damage(alvo, 1, "fogo")["dano"] == 1


def test_hp_nunca_fica_negativo():
    alvo = criar_ficha("Frágil", vida=3)
    res = T._apply_damage(alvo, 50, "fogo")
    assert alvo["sheet"]["vida_atual"] == 0
    assert res["hp_depois"] == 0


def test_componentes_com_tipos_distintos():
    """
    Golpe Divino soma 1d8 radiante ao corte da arma. Um alvo pode resistir
    a um tipo e não ao outro DENTRO do mesmo golpe.
    """
    alvo = criar_ficha("Sombra", vida=60,
                       resistencias=T._parse_damage_traits("slashing"),
                       vulnerabilidades=T._parse_damage_traits("radiant"))
    res = T._apply_damage(alvo, components=[(10, "slashing"), (8, "radiant")])
    assert res["dano"] == 5 + 16
    assert alvo["sheet"]["vida_atual"] == 60 - 21


# ---------------------------------------------------------------------------
# PV temporários
# ---------------------------------------------------------------------------

def test_pv_temporarios_absorvem_primeiro():
    alvo = criar_ficha("Clériga", vida=30, vida_temp=8)
    res = T._apply_damage(alvo, 5)
    assert res["temp_absorvido"] == 5
    assert alvo["sheet"]["vida_temp"] == 3
    assert alvo["sheet"]["vida_atual"] == 30        # PV reais intactos


def test_dano_maior_que_os_temporarios_transborda():
    alvo = criar_ficha("Clériga", vida=30, vida_temp=5)
    res = T._apply_damage(alvo, 12)
    assert res["temp_absorvido"] == 5
    assert alvo["sheet"]["vida_temp"] == 0
    assert alvo["sheet"]["vida_atual"] == 23


def test_temporarios_aplicados_depois_da_resistencia():
    """A ordem do PHB é: modificador de tipo primeiro, PV temporários depois."""
    alvo = criar_ficha("Golem", vida=30, vida_temp=10,
                       resistencias=T._parse_damage_traits("fire"))
    T._apply_damage(alvo, 10, "fogo")               # 10 → 5 pela resistência
    assert alvo["sheet"]["vida_temp"] == 5
    assert alvo["sheet"]["vida_atual"] == 30


def test_grant_temp_hp_nao_acumula(campanha, povoar):
    povoar(criar_ficha("Bardo", grupo=True, vida=25))
    T.grant_temp_hp("Bardo", 8, "Ajuda")
    saida = T.grant_temp_hp("Bardo", 5, "Falsa Vida")

    ficha = campanha["characters"]["bardo"]["sheet"]
    assert ficha["vida_temp"] == 8, "o menor valor não pode somar nem substituir"
    assert "não se acumulam" in saida


def test_grant_temp_hp_substitui_pelo_maior(campanha, povoar):
    povoar(criar_ficha("Bardo", grupo=True, vida=25))
    T.grant_temp_hp("Bardo", 5)
    T.grant_temp_hp("Bardo", 12)
    assert campanha["characters"]["bardo"]["sheet"]["vida_temp"] == 12


def test_cura_nao_restaura_pv_temporarios(campanha, povoar):
    povoar(criar_ficha("Bardo", grupo=True, vida=10, vida_max=25, vida_temp=0))
    T.modify_hp("Bardo", 10, "poção")
    assert campanha["characters"]["bardo"]["sheet"]["vida_temp"] == 0


def test_descanso_longo_expira_os_temporarios(campanha, povoar):
    povoar(criar_ficha("Bardo", grupo=True, vida=25, vida_temp=9))
    saida = T.long_rest("Bardo")
    assert campanha["characters"]["bardo"]["sheet"]["vida_temp"] == 0
    assert "temporários expiraram" in saida


# ---------------------------------------------------------------------------
# Integração com o combate
# ---------------------------------------------------------------------------

def test_esqueleto_nao_morre_de_veneno(campanha, povoar):
    """O caso emblemático do bug: dano cru ignorava a imunidade do esqueleto."""
    povoar(criar_ficha("Esqueleto", vida=13,
                       imunidades=T._parse_damage_traits("poison")))
    saida = T.modify_hp("Esqueleto", -8, "nuvem de veneno", damage_type="veneno")

    assert campanha["characters"]["esqueleto"]["sheet"]["vida_atual"] == 13
    assert "IMUNE" in saida


def test_attack_roll_aplica_resistencia_do_alvo(campanha, povoar, monkeypatch):
    """Golem resistente a cortante leva metade do dano da espada."""
    povoar(
        criar_ficha("Heroína", grupo=True, vida=50, forca=16),
        criar_ficha("Golem", vida=100, ca=1,
                    resistencias=T._parse_damage_traits("slashing")),
    )
    # Dado de dano máximo e d20 fixo em 15 (acerta, não critica).
    monkeypatch.setattr(T.random, "randint",
                        lambda a, b: 15 if (a, b) == (1, 20) else b)
    monkeypatch.setattr(T, "_fetch_weapon_data", lambda *a, **k: (1, 8))

    saida = T.attack_roll("Heroína", "Golem", "espada longa", 8,
                          end_turn=False, _skip_turn_check=True)

    # 1d8 máximo (8) + 3 (FOR 16) = 11 bruto → 5 com resistência.
    assert campanha["characters"]["golem"]["sheet"]["vida_atual"] == 95
    assert "Resistente a dano slashing" in saida


def test_attack_roll_anota_o_tipo_na_saida(campanha, povoar, monkeypatch):
    povoar(
        criar_ficha("Heroína", grupo=True, vida=50),
        criar_ficha("Alvo", vida=60, ca=1),
    )
    monkeypatch.setattr(T.random, "randint",
                        lambda a, b: 15 if (a, b) == (1, 20) else b)
    monkeypatch.setattr(T, "_fetch_weapon_data", lambda *a, **k: (1, 8))

    saida = T.attack_roll("Heroína", "Alvo", "espada longa", 8,
                          end_turn=False, _skip_turn_check=True)
    assert "Dano (slashing)" in saida
