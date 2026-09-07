"""
test_concentration.py
Concentração em magias.

O QUE ESTES TESTES TRANCAM
──────────────────────────
"Concentração" era só texto decorativo nas descrições: nada rastreava. Um
clérigo sustentava Bênção, Escudo da Fé e Arma Espiritual ao mesmo tempo, e
nunca fazia teste de CON ao levar dano. Agora só se concentra numa magia por
vez, e o dano ameaça essa concentração.
"""

import pytest

import tools_dnd as T
from conftest import criar_ficha, iniciar_combate


BENCAO = {"nome": "Bênção", "custo_mana": 4, "dado": "1d4",
          "descricao": "[Encantamento] +1d4 em ataques e salvaguardas. Concentração."}
ESCUDO_FE = {"nome": "Escudo da Fé", "custo_mana": 4, "dado": "",
             "descricao": "[Abjuração] Alvo ganha +2 de CA. Concentração, 10 min."}
CURAR = {"nome": "Curar Ferimentos", "custo_mana": 4, "dado": "1d8",
         "descricao": "[Evocação] Cura 1d8+mod de vida ao toque."}


# ---------------------------------------------------------------------------
# Detecção
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hab, esperado", [
    (BENCAO, True),
    (ESCUDO_FE, True),
    (CURAR, False),
    ({"nome": "Hex", "descricao": "[Encantamento] +1d6 necrótico. Concentration."}, True),
    ({"nome": "Golpe", "descricao": ""}, False),
])
def test_detecta_concentracao_na_descricao(hab, esperado):
    assert T._requires_concentration(hab) is esperado


def test_campo_explicito_vence_a_descricao():
    hab = {"nome": "X", "descricao": "Concentração.", "concentracao": False}
    assert T._requires_concentration(hab) is False


# ---------------------------------------------------------------------------
# Início e troca
# ---------------------------------------------------------------------------

def test_conjurar_magia_de_concentracao_registra_na_ficha(campanha, povoar):
    povoar(criar_ficha("Clériga", grupo=True, habilidades=[BENCAO]),
           criar_ficha("Alvo", vida=40))

    saida = T.use_ability("Clériga", "Bênção", "Alvo",
                          end_turn=False, _skip_turn_check=True)

    conc = campanha["characters"]["clériga"]["sheet"]["concentracao"]
    assert conc and conc["magia"] == "Bênção"
    assert "concentrado em Bênção" in saida


def test_segunda_magia_de_concentracao_derruba_a_primeira(campanha, povoar):
    """
    O ponto central: em 5e só se concentra numa magia por vez. Sem isso, o
    clérigo empilhava buffs indefinidamente.
    """
    povoar(criar_ficha("Clériga", grupo=True, habilidades=[BENCAO, ESCUDO_FE]),
           criar_ficha("Alvo", vida=40))

    T.use_ability("Clériga", "Bênção", "Alvo", end_turn=False, _skip_turn_check=True)
    saida = T.use_ability("Clériga", "Escudo da Fé", "Alvo",
                          end_turn=False, _skip_turn_check=True)

    conc = campanha["characters"]["clériga"]["sheet"]["concentracao"]
    assert conc["magia"] == "Escudo da Fé"
    assert "solta a concentração em Bênção" in saida


def test_magia_sem_concentracao_nao_derruba_a_ativa(campanha, povoar):
    povoar(criar_ficha("Clériga", grupo=True, habilidades=[BENCAO, CURAR]),
           criar_ficha("Alvo", vida=40, vida_max=40))

    T.use_ability("Clériga", "Bênção", "Alvo", end_turn=False, _skip_turn_check=True)
    T.use_ability("Clériga", "Curar Ferimentos", "Alvo",
                  end_turn=False, _skip_turn_check=True)

    conc = campanha["characters"]["clériga"]["sheet"]["concentracao"]
    assert conc["magia"] == "Bênção"


# ---------------------------------------------------------------------------
# Teste de CON ao sofrer dano
# ---------------------------------------------------------------------------

def test_dano_com_save_bem_sucedido_mantem_a_concentracao(campanha, povoar, monkeypatch):
    alvo = criar_ficha("Clériga", grupo=True, vida=40, constituicao=14,
                       concentracao={"magia": "Bênção", "rodada": 1})
    povoar(alvo)
    monkeypatch.setattr(T.random, "randint", lambda a, b: 20)   # save passa

    res = T._apply_damage(alvo, 10)

    assert alvo["sheet"]["concentracao"] is not None
    assert any("mantida" in n for n in res["notas"])


def test_dano_com_save_falho_derruba_a_concentracao(campanha, povoar, monkeypatch):
    alvo = criar_ficha("Clériga", grupo=True, vida=40, constituicao=8,
                       concentracao={"magia": "Bênção", "rodada": 1})
    povoar(alvo)
    monkeypatch.setattr(T.random, "randint", lambda a, b: 1)    # save falha

    res = T._apply_damage(alvo, 10)

    assert alvo["sheet"]["concentracao"] is None
    assert any("PERDEU a concentração" in n for n in res["notas"])


def test_cd_do_save_e_metade_do_dano_com_piso_10(campanha, povoar, monkeypatch):
    """CD = max(10, dano // 2). Com 30 de dano a CD é 15, não 10."""
    alvo = criar_ficha("Mago", grupo=True, vida=90, constituicao=10,
                       concentracao={"magia": "Voo", "rodada": 1})
    povoar(alvo)
    monkeypatch.setattr(T.random, "randint", lambda a, b: 12)   # 12 + 0 = 12

    res = T._apply_damage(alvo, 30)                              # CD 15 → falha

    assert alvo["sheet"]["concentracao"] is None
    assert any("CD 15" in n for n in res["notas"])


def test_dano_pequeno_usa_o_piso_de_cd_10(campanha, povoar, monkeypatch):
    alvo = criar_ficha("Mago", grupo=True, vida=90, constituicao=10,
                       concentracao={"magia": "Voo", "rodada": 1})
    povoar(alvo)
    monkeypatch.setattr(T.random, "randint", lambda a, b: 12)

    res = T._apply_damage(alvo, 4)                               # CD 10 → passa

    assert alvo["sheet"]["concentracao"] is not None
    assert any("CD 10" in n for n in res["notas"])


def test_cair_a_zero_pv_derruba_sem_teste(campanha, povoar, monkeypatch):
    alvo = criar_ficha("Mago", grupo=True, vida=6, constituicao=20,
                       concentracao={"magia": "Voo", "rodada": 1})
    povoar(alvo)
    monkeypatch.setattr(T.random, "randint", lambda a, b: 20)    # passaria fácil

    res = T._apply_damage(alvo, 30)

    assert alvo["sheet"]["concentracao"] is None
    assert any("caiu a 0 PV" in n for n in res["notas"])


def test_dano_totalmente_absorvido_nao_ameaca_a_concentracao(campanha, povoar):
    """Se os PV temporários comeram o golpe inteiro, não houve perda de PV."""
    alvo = criar_ficha("Mago", grupo=True, vida=40, vida_temp=20,
                       concentracao={"magia": "Voo", "rodada": 1})
    povoar(alvo)

    T._apply_damage(alvo, 10)

    assert alvo["sheet"]["concentracao"] is not None


def test_imunidade_ao_tipo_nao_ameaca_a_concentracao(campanha, povoar):
    alvo = criar_ficha("Mago", grupo=True, vida=40,
                       imunidades=T._parse_damage_traits("fire"),
                       concentracao={"magia": "Voo", "rodada": 1})
    povoar(alvo)

    T._apply_damage(alvo, 30, "fogo")

    assert alvo["sheet"]["concentracao"] is not None


# ---------------------------------------------------------------------------
# Limpeza
# ---------------------------------------------------------------------------

def test_descanso_longo_derruba_a_concentracao(campanha, povoar):
    povoar(criar_ficha("Mago", grupo=True, vida=40,
                       concentracao={"magia": "Voo", "rodada": 1}))
    saida = T.long_rest("Mago")
    assert campanha["characters"]["mago"]["sheet"]["concentracao"] is None
    assert "PERDEU a concentração" in saida


def test_fim_de_combate_limpa_concentracao_de_todos(campanha, povoar):
    """A concentração não pode vazar para a próxima luta."""
    povoar(
        criar_ficha("Mago", grupo=True, vida=40,
                    concentracao={"magia": "Voo", "rodada": 1}),
        criar_ficha("Bruxo", vida=40,
                    concentracao={"magia": "Hex", "rodada": 1}),
    )
    iniciar_combate(["Mago", "Bruxo"])
    T.end_combat()

    assert campanha["characters"]["mago"]["sheet"]["concentracao"] is None
    assert campanha["characters"]["bruxo"]["sheet"]["concentracao"] is None


def test_quem_nao_concentra_nao_faz_teste(campanha, povoar):
    alvo = criar_ficha("Guerreiro", grupo=True, vida=40)
    povoar(alvo)
    res = T._apply_damage(alvo, 20)
    assert not any("Concentração" in n for n in res["notas"])
