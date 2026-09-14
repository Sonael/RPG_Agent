"""
test_xp_nao_repete.py

Ao reabrir a campanha, o grupo ganhou de novo o XP de um monstro que já tinha
derrotado e pelo qual já tinha recebido XP.

Duas causas somadas:
  • o resumo de retomada (_build_recap) repassava ao mestre o recap inteiro
    da tela tática, com "conceda XP a cada membro do grupo com grant_xp()",
    e o modelo obedecia de novo;
  • grant_xp somava qualquer valor, sem saber se aquele personagem já tinha
    sido recompensado por aquele inimigo.
"""
import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha


@pytest.fixture
def depois_da_luta(campanha, povoar):
    povoar(
        criar_ficha("Alden", grupo=True, nivel=1, vida=12),
        criar_ficha("Lyra", grupo=True, nivel=1, vida=9),
        criar_ficha("Espreitador das Sombras", vida=11),
        criar_ficha("Goblin 1", vida=7),
        criar_ficha("Goblin 2", vida=7),
    )
    chars = memory.campaign["characters"]
    for c in chars.values():
        c["sheet"]["xp"] = 0
    chars["espreitador das sombras"]["status"] = "morto"
    return chars


def _xp(chars, chave):
    return chars[chave]["sheet"]["xp"]


# ---------------------------------------------------------------------------
# 1. O motor não concede duas vezes pela mesma derrota
# ---------------------------------------------------------------------------

def test_mesma_derrota_nao_da_xp_duas_vezes(depois_da_luta):
    chars = depois_da_luta
    td.grant_xp("Alden", 100, "Derrota do Espreitador das Sombras")

    saida = td.grant_xp("Alden", 100, "Derrota do Espreitador das Sombras")

    assert saida.startswith("Aviso:") and "já recebeu XP" in saida
    assert _xp(chars, "alden") == 100


def test_motivo_escrito_de_outro_jeito_tambem_e_barrado(depois_da_luta):
    chars = depois_da_luta
    td.grant_xp("Alden", 100, "Derrota do Espreitador das Sombras")
    assert td.grant_xp("Alden", 100, "vitória sobre o espreitador").startswith("Aviso:")
    assert _xp(chars, "alden") == 100


def test_cada_membro_do_grupo_recebe_uma_vez(depois_da_luta):
    chars = depois_da_luta
    td.grant_xp("Alden", 100, "Derrota do Espreitador das Sombras")
    td.grant_xp("Lyra", 100, "Derrota do Espreitador das Sombras")
    assert _xp(chars, "alden") == 100 and _xp(chars, "lyra") == 100


def test_inimigo_ainda_de_pe_nao_trava(depois_da_luta):
    """Citar quem ainda luta não é recompensa por derrota: fica sem trava."""
    chars = depois_da_luta
    td.grant_xp("Alden", 25, "golpe no Goblin 1")
    td.grant_xp("Alden", 25, "golpe no Goblin 1")
    assert _xp(chars, "alden") == 50


def test_xp_sem_inimigo_citado_nao_tem_trava(depois_da_luta):
    chars = depois_da_luta
    td.grant_xp("Alden", 150, "missão da aldeia completada")
    td.grant_xp("Alden", 150, "missão da aldeia completada")
    assert _xp(chars, "alden") == 300


def test_derrota_nova_de_mesmo_nome_ainda_rende(depois_da_luta):
    """Goblin 1 já pago, Goblin 2 recém-derrotado: 'goblins derrotados' rende."""
    chars = depois_da_luta
    chars["goblin 1"]["status"] = "morto"
    td.grant_xp("Alden", 50, "Goblin 1 derrotado")
    chars["goblin 2"]["status"] = "morto"

    saida = td.grant_xp("Alden", 50, "goblins derrotados")

    assert not saida.startswith("Aviso:"), saida
    assert _xp(chars, "alden") == 100
    assert td.grant_xp("Alden", 50, "goblins derrotados").startswith("Aviso:")


# ---------------------------------------------------------------------------
# 2. A retomada não repassa as instruções do recap
# ---------------------------------------------------------------------------

_RECAP = (
    "[COMBATE RESOLVIDO NA TELA TÁTICA]\n"
    "Desfecho: VITÓRIA. Narre a luta INTEIRA de forma cinematográfica e contínua "
    "(não turno a turno), com base no log abaixo. Gere o SAQUE dos inimigos "
    "derrotados (use add_item/modify_currency se houver) e conceda XP a cada "
    "membro do grupo com grant_xp(). Depois siga a história.\n\n"
    "— Eventos —\n[R1] Combate iniciado"
)


def test_retomada_manda_so_o_registro_do_recap(depois_da_luta):
    import server
    memory.campaign["conversation_history"] = [
        {"role": "user", "text": "Ataco com a espada."},
        {"role": "user", "text": _RECAP},
        {"role": "assistant", "text": "A lâmina de Alden encontra a sombra."},
    ]

    texto = server._build_recap()

    assert "grant_xp()" not in texto, "a instrução de conceder XP voltou ao mestre"
    assert "Gere o SAQUE" not in texto
    assert "[Sistema]: [COMBATE RESOLVIDO NA TELA TÁTICA] Desfecho: VITÓRIA. (já resolvido e narrado)" in texto
    assert "[Jogador]: Ataco com a espada." in texto
    assert "NÃO conceda XP, saque, itens ou moedas de novo" in texto


def test_linha_de_dado_e_comando_no_recap():
    import server
    dado = {"role": "user", "interno": "dado",
            "text": "[DADO DO JOGADOR — rolado pelo sistema, não editável] 1d20: rolei 3, total 3"}
    comando = {"role": "user", "interno": "comando",
               "text": "Salve o local \"Clareira\" usando save_location com todos os detalhes."}
    assert server._linha_do_recap(dado).endswith("(já resolvido)")
    assert server._linha_do_recap(comando).startswith("[Sistema]: Salve o local")
