"""
test_reactions.py
Reação e ataque de oportunidade.

O QUE ESTES TESTES TRANCAM
──────────────────────────
A economia do turno rastreava só Ação e Ação Bônus. Faltava a Reação — a
única coisa que acontece FORA do próprio turno. Sem ataque de oportunidade,
sair do combate era grátis, que é exatamente o que a regra existe para
impedir.

Sem posicionamento no jogo, o gatilho honesto é a FUGA. Quando houver
zonas/alcance, _provoke_opportunity_attacks passa a ser chamado também no
movimento — os testes de reação abaixo continuam valendo.
"""

from rpg import tools_dnd as T
from conftest import criar_ficha, iniciar_combate


def _sempre_acerta(monkeypatch):
    """d20 = 19 (acerta, sem crítico); dados de dano no máximo."""
    monkeypatch.setattr(T.random, "randint",
                        lambda a, b: 19 if (a, b) == (1, 20) else b)


# ---------------------------------------------------------------------------
# Orçamento de reação
# ---------------------------------------------------------------------------

def test_reacao_comeca_disponivel(campanha, povoar):
    ch = criar_ficha("Guarda", vida=20)
    povoar(ch)
    iniciar_combate(["Guarda"])
    assert T._reaction_available(ch) is True


def test_reacao_usada_fica_indisponivel_na_mesma_rodada(campanha, povoar):
    ch = criar_ficha("Guarda", vida=20)
    povoar(ch)
    iniciar_combate(["Guarda"], rodada=2)
    T._consume_reaction(ch)
    assert T._reaction_available(ch) is False


def test_reacao_recarrega_na_rodada_seguinte(campanha, povoar):
    ch = criar_ficha("Guarda", vida=20)
    povoar(ch)
    cs = iniciar_combate(["Guarda"], rodada=2)
    T._consume_reaction(ch)
    cs["round"] = 3
    assert T._reaction_available(ch) is True


# ---------------------------------------------------------------------------
# Ataque de oportunidade ao fugir
# ---------------------------------------------------------------------------

def test_fugir_provoca_ataque_de_oportunidade(campanha, povoar, monkeypatch):
    chars = povoar(
        criar_ficha("Heroína", grupo=True, vida=50, forca=16),
        criar_ficha("Goblin", vida=30, ca=1),
    )
    iniciar_combate(["Heroína", "Goblin"])
    _sempre_acerta(monkeypatch)
    monkeypatch.setattr(T, "_fetch_weapon_data", lambda *a, **k: (1, 8))

    hp_antes = chars["Goblin"]["sheet"]["vida_atual"]
    saida = T._provoke_opportunity_attacks("Goblin", "fugir")

    assert "ATAQUE(S) DE OPORTUNIDADE" in saida
    assert chars["Goblin"]["sheet"]["vida_atual"] < hp_antes


def test_aliado_nao_ataca_aliado_em_fuga(campanha, povoar, monkeypatch):
    chars = povoar(
        criar_ficha("Heroína", grupo=True, vida=50, ca=1),
        criar_ficha("Escudeiro", grupo=True, vida=40, forca=16),
    )
    iniciar_combate(["Heroína", "Escudeiro"])
    _sempre_acerta(monkeypatch)

    hp_antes = chars["Heroína"]["sheet"]["vida_atual"]
    saida = T._provoke_opportunity_attacks("Heroína", "fugir")

    assert saida == ""
    assert chars["Heroína"]["sheet"]["vida_atual"] == hp_antes


def test_quem_ja_gastou_a_reacao_nao_ataca(campanha, povoar, monkeypatch):
    chars = povoar(
        criar_ficha("Heroína", grupo=True, vida=50, forca=16),
        criar_ficha("Goblin", vida=30, ca=1),
    )
    iniciar_combate(["Heroína", "Goblin"])
    _sempre_acerta(monkeypatch)
    T._consume_reaction(chars["Heroína"])

    hp_antes = chars["Goblin"]["sheet"]["vida_atual"]
    assert T._provoke_opportunity_attacks("Goblin") == ""
    assert chars["Goblin"]["sheet"]["vida_atual"] == hp_antes


def test_inconsciente_nao_reage(campanha, povoar, monkeypatch):
    chars = povoar(
        criar_ficha("Heroína", grupo=True, vida=0, forca=16),
        criar_ficha("Goblin", vida=30, ca=1),
    )
    chars["Heroína"]["status"] = "inconsciente"
    iniciar_combate(["Heroína", "Goblin"])
    _sempre_acerta(monkeypatch)

    assert T._provoke_opportunity_attacks("Goblin") == ""


def test_o_ataque_consome_a_reacao(campanha, povoar, monkeypatch):
    chars = povoar(
        criar_ficha("Heroína", grupo=True, vida=50, forca=16),
        criar_ficha("Goblin", vida=30, ca=1),
    )
    iniciar_combate(["Heroína", "Goblin"])
    _sempre_acerta(monkeypatch)
    monkeypatch.setattr(T, "_fetch_weapon_data", lambda *a, **k: (1, 8))

    T._provoke_opportunity_attacks("Goblin")
    assert T._reaction_available(chars["Heroína"]) is False


def test_varios_inimigos_reagem_uma_vez_cada(campanha, povoar, monkeypatch):
    povoar(
        criar_ficha("Heroína", grupo=True, vida=50, forca=16),
        criar_ficha("Escudeiro", grupo=True, vida=50, forca=16),
        criar_ficha("Goblin", vida=200, ca=1),
    )
    iniciar_combate(["Heroína", "Escudeiro", "Goblin"])
    _sempre_acerta(monkeypatch)
    monkeypatch.setattr(T, "_fetch_weapon_data", lambda *a, **k: (1, 8))

    saida = T._provoke_opportunity_attacks("Goblin")
    assert saida.count("ataca") == 2


def test_nao_ataca_alvo_que_ja_caiu(campanha, povoar, monkeypatch):
    """Se o primeiro ataque de oportunidade derruba o fugitivo, o resto para."""
    chars = povoar(
        criar_ficha("Heroína", grupo=True, vida=50, forca=16),
        criar_ficha("Escudeiro", grupo=True, vida=50, forca=16),
        criar_ficha("Goblin", vida=3, ca=1),
    )
    iniciar_combate(["Heroína", "Escudeiro", "Goblin"])
    _sempre_acerta(monkeypatch)
    monkeypatch.setattr(T, "_fetch_weapon_data", lambda *a, **k: (1, 8))

    saida = T._provoke_opportunity_attacks("Goblin")

    assert chars["Goblin"]["sheet"]["vida_atual"] == 0
    assert saida.count("ataca") == 1


def test_sem_combate_ativo_nao_ha_oportunidade(campanha, povoar):
    povoar(criar_ficha("Heroína", grupo=True, vida=50),
           criar_ficha("Goblin", vida=30))
    assert T._provoke_opportunity_attacks("Goblin") == ""


# ---------------------------------------------------------------------------
# Integração com os dois caminhos de fuga
# ---------------------------------------------------------------------------

def test_npc_covarde_leva_o_bote_ao_fugir(campanha, povoar, monkeypatch):
    chars = povoar(
        criar_ficha("Heroína", grupo=True, vida=50, forca=16),
        criar_ficha("Goblin", vida=3, vida_max=30, ca=1),
    )
    cs = iniciar_combate(["Goblin", "Heroína"])
    cs["npc_strategies"] = {"goblin": "covarde"}
    _sempre_acerta(monkeypatch)
    monkeypatch.setattr(T, "_fetch_weapon_data", lambda *a, **k: (1, 8))

    saida = T.execute_npc_turn()

    assert "FOGE do combate" in saida
    assert "ATAQUE(S) DE OPORTUNIDADE" in saida
    assert chars["Goblin"]["sheet"]["vida_atual"] < 3
    # A fuga ainda encerra o turno do NPC.
    assert chars["Goblin"]["status"] == "fugiu"


def test_jogador_que_foge_pela_tela_tambem_provoca(campanha, povoar, monkeypatch):
    chars = povoar(
        criar_ficha("Heroína", grupo=True, vida=50, ca=1),
        criar_ficha("Goblin", vida=30, forca=16),
    )
    iniciar_combate(["Heroína", "Goblin"])
    _sempre_acerta(monkeypatch)
    monkeypatch.setattr(T, "_fetch_weapon_data", lambda *a, **k: (1, 8))

    hp_antes = chars["Heroína"]["sheet"]["vida_atual"]
    res = T.combat_action("flee", actor="Heroína")

    assert res["ok"] is True
    assert "ATAQUE(S) DE OPORTUNIDADE" in res["message"]
    assert chars["Heroína"]["sheet"]["vida_atual"] < hp_antes
    assert chars["Heroína"]["status"] == "fugiu"


def test_snapshot_expoe_reacao_e_defesas(campanha, povoar):
    povoar(
        criar_ficha("Heroína", grupo=True, vida=50),
        criar_ficha("Golem", vida=60,
                    resistencias=T._parse_damage_traits("fire"),
                    imunidades=T._parse_damage_traits("poison"),
                    vida_temp=5),
    )
    iniciar_combate(["Heroína", "Golem"])

    snap = T.combat_snapshot()
    golem = next(c for c in snap["combatants"] if c["name"] == "Golem")

    assert golem["resistencias"] == ["fire"]
    assert golem["imunidades"] == ["poison"]
    assert golem["hp_temp"] == 5
    assert golem["reacao_disponivel"] is True
