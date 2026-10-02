"""
test_padrao_de_combate.py

O combate é jogado SÓ na tela tática.

Era "narrado" desde o começo — de quando a tela tática ainda não existia.
Depois a tela virou o padrão, com o narrado a um clique na engrenagem. Agora
o modo narrado deixou de existir: a tela rola o dado, conta o dano, gasta
munição, cobra alcance, move na zona e pergunta as reações; o narrado pedia
à IA que fizesse tudo isso de cabeça, que é justamente onde ela erra.

O que estes testes trancam: toda campanha carrega na tela (inclusive as
gravadas com "narrado"), a importação chega na tela, a rota não aceita outro
modo, a engrenagem não oferece escolha, e a ajuda e o README contam isso.
"""
import pytest

from rpg import memory


def test_o_padrao_do_jogo_e_a_tela():
    assert memory.PADRAO_COMBATE == "tela"
    assert memory._defaults()["combat_mode"] == "tela"


def test_campanha_sem_o_campo_carrega_na_tela(campanha):
    campanha.pop("combat_mode", None)
    memory.normalizar_campanha()
    assert campanha["combat_mode"] == "tela"


@pytest.mark.parametrize("marca", [True, False, None])
def test_campanha_gravada_narrada_carrega_na_tela(campanha, marca):
    """A antiga, e também a que o jogador pôs no narrado pela engrenagem."""
    campanha["combat_mode"] = "narrado"
    if marca is None:
        campanha.pop("_padrao_combate_migrado", None)
    else:
        campanha["_padrao_combate_migrado"] = marca
    memory.normalizar_campanha()
    assert campanha["combat_mode"] == "tela"


def test_importacao_chega_na_tela():
    import server

    assert server._payload_de_campanha("Nova", {}, {})["combat_mode"] == "tela"
    vinda = server._payload_de_campanha("Vinda", {"combat_mode": "narrado", "_padrao_combate_migrado": True}, {})
    assert vinda["combat_mode"] == "tela"


def test_a_rota_so_aceita_a_tela():
    from pathlib import Path

    fonte = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
    assert 'if mode != "tela":' in fonte
    assert 'mode not in ("narrado", "tela")' not in fonte


def test_o_snapshot_diz_tela(campanha):
    from rpg import tools_dnd as td

    campanha["combat_mode"] = "narrado"
    assert td.combat_snapshot()["combat_mode"] == "tela"


# ---------------------------------------------------------------------------
# A tela, a ajuda e o README contam a mesma história
# ---------------------------------------------------------------------------

def test_a_engrenagem_nao_oferece_modo():
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1] / "static" / "js"
    barra = (raiz / "barra.js").read_text(encoding="utf-8")
    combate = (raiz / "combat.js").read_text(encoding="utf-8")
    assert "combat-mode-toggle" not in barra and "Narrado pela IA" not in barra
    assert "setCombatMode" not in combate


def test_a_ajuda_diz_que_o_combate_e_na_tela():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "static" / "js" / "utils.js"
          ).read_text(encoding="utf-8")
    assert "O combate: a tela tática" in js
    assert "Narrado pela IA" not in js


def test_o_readme_diz_que_so_existe_a_tela():
    from pathlib import Path

    doc = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert "### O combate é só na tela tática" in doc
    assert '"tela" | "narrado"' not in doc


@pytest.mark.parametrize("gravado", ["tela", "narrado", None])
def test_o_mestre_sempre_recebe_a_tela_e_nunca_o_turno_a_turno(campanha, gravado):
    """
    A instrução do Mestre diz que a luta é da tela, mesmo numa campanha antiga
    com "narrado" gravado — e não ensina mais a jogar o turno no chat.
    """
    from rpg.agent import create_agent

    if gravado is None:
        campanha.pop("combat_mode", None)
    else:
        campanha["combat_mode"] = gravado
    agente = create_agent("gemini-2.5-flash", "fantasia", dnd_mode=True)
    instrucao = agente.instruction() if callable(agente.instruction) else agente.instruction
    assert "MODO DE COMBATE: TELA TÁTICA" in instrucao
    assert "COMBATE — SEMPRE NA TELA TÁTICA" in instrucao
    for velho in ("attack_roll(", "use_ability(", "execute_npc_turn(", "next_turn(", "Digite continuar"):
        assert velho not in instrucao, velho
