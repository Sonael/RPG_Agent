"""
test_combate_repetido.py

A mesma emboscada não reinicia a luta.

Numa campanha o mestre, num único turno, chamou spawn_monster, roll_initiative,
set_battlefield, roll_initiative, spawn_monster, roll_initiative e
set_battlefield para os mesmos dois goblins. Cada roll_initiative zerava a
ordem, a rodada e o log; o segundo spawn_monster devolvia a vida cheia aos
goblins; o segundo set_battlefield desfazia os movimentos. A tela mostrou
três ordens de iniciativa diferentes.
"""
import json

import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha

GOBLIN = {"name": "Goblin", "hit_points": 7, "armor_class": 15, "strength": 8, "dexterity": 14,
          "constitution": 10, "intelligence": 10, "wisdom": 8, "charisma": 8,
          "challenge_rating": "1/4", "type": "humanoid", "size": "Small",
          "actions": [{"name": "Scimitar", "desc": "Melee Weapon Attack: +4 to hit, reach 5 ft., "
                                                   "one target. Hit: 5 (1d6 + 2) slashing damage."}]}

NOMES = "Thorn, Lyra, Helena, Goblin Batedor 1, Goblin Batedor 2"


class _Resposta:
    ok = True

    def json(self):
        return GOBLIN


@pytest.fixture
def emboscada(campanha, povoar, monkeypatch):
    from rpg import open5e
    monkeypatch.setattr(open5e.http, "get", lambda *a, **k: _Resposta())
    povoar(criar_ficha("Thorn", grupo=True), criar_ficha("Lyra", grupo=True),
           criar_ficha("Helena", grupo=True))
    memory.campaign["name"] = "Emboscada"
    return campanha


def _cs():
    return memory.campaign["combat_state"]


def _goblin(n):
    return memory.campaign["characters"][f"goblin batedor {n}"]


def test_a_sequencia_da_campanha_vira_uma_luta_so(emboscada):
    td.spawn_monster("Goblin Batedor", "Goblin Batedor", 2)
    td.roll_initiative(NOMES)
    td.set_battlefield("Trilha, Encosta, Ruínas", "lama; arbustos; ruínas")
    ordem = list(_cs()["initiative_order"])

    # O jogo anda: Thorn avança e um goblin se fere.
    td.move_combatant("Thorn", "Encosta")
    _goblin(1)["sheet"]["vida_atual"] = 2
    log_antes = len(_cs()["log"])

    r1 = td.roll_initiative(NOMES)
    r2 = td.spawn_monster("goblin", "Goblin Batedor", 2)
    r3 = td.roll_initiative(NOMES)
    r4 = td.set_battlefield("Trilha, Encosta, Ruínas", "lama; arbustos; ruínas")

    assert r1.startswith("Nota: o combate já está em andamento") and r3.startswith("Nota:")
    assert r2.startswith("Nota: Goblin Batedor 1, Goblin Batedor 2 já estão neste combate")
    assert r4.startswith("Nota: o campo já está dividido assim")
    cs = _cs()
    assert cs["initiative_order"] == ordem
    assert cs["round"] == 1 and cs["current_turn_index"] == 0
    assert len(cs["log"]) >= log_antes, "o log da luta não pode ser apagado"
    assert _goblin(1)["sheet"]["vida_atual"] == 2, "o goblin ferido não pode voltar com a vida cheia"
    assert td._zona_de("Thorn") == "Encosta", "o movimento não pode ser desfeito"


def test_reforco_entra_no_lugar_da_iniciativa_sem_mexer_na_vez(emboscada, monkeypatch):
    dados = iter([20, 15, 10, 5, 1])       # Thorn 21, Lyra 16, Helena 11, G1 7, G2 3
    monkeypatch.setattr(td.random, "randint", lambda a, b: next(dados))
    td.spawn_monster("Goblin Batedor", "Goblin Batedor", 2)
    td.roll_initiative(NOMES)
    td.set_battlefield("Trilha, Ruínas")
    assert _cs()["initiative_order"] == ["Thorn", "Lyra", "Helena", "Goblin Batedor 1", "Goblin Batedor 2"]
    _cs()["current_turn_index"] = 2         # vez da Helena

    td.spawn_monster("Goblin Batedor", "Goblin Chefe", 1)
    monkeypatch.setattr(td.random, "randint", lambda a, b: 12)     # 12 + 2 = 14
    r = td.roll_initiative("Thorn, Goblin Chefe")

    cs = _cs()
    assert cs["initiative_order"] == ["Thorn", "Lyra", "Goblin Chefe", "Helena",
                                      "Goblin Batedor 1", "Goblin Batedor 2"]
    assert cs["initiative_order"][cs["current_turn_index"]] == "Helena", "a vez continua da Helena"
    assert "age a partir da próxima rodada" in r
    assert td._zona_de("Goblin Chefe") == "Ruínas"
    assert any(e.get("type") == "combat_join" for e in cs["log"])


def test_reforco_depois_da_vez_age_ainda_nesta_rodada(emboscada, monkeypatch):
    dados = iter([20, 15, 10, 5, 1])
    monkeypatch.setattr(td.random, "randint", lambda a, b: next(dados))
    td.spawn_monster("Goblin Batedor", "Goblin Batedor", 2)
    td.roll_initiative(NOMES)
    td.spawn_monster("Goblin Batedor", "Goblin Retardatário", 1)
    monkeypatch.setattr(td.random, "randint", lambda a, b: 2)      # 2 + 2 = 4
    r = td.roll_initiative("Goblin Retardatário")
    assert _cs()["initiative_order"][-2:] == ["Goblin Retardatário", "Goblin Batedor 2"]
    assert _cs()["current_turn_index"] == 0
    assert "age ainda nesta rodada" in r


def test_combate_antigo_sem_os_totais_poe_o_reforco_no_fim(emboscada):
    td.roll_initiative("Thorn, Lyra")
    _cs().pop("iniciativas")
    td.roll_initiative("Helena")
    assert _cs()["initiative_order"][-1] == "Helena"


def test_reforco_com_outro_nome_e_criado(emboscada):
    td.spawn_monster("Goblin Batedor", "Goblin Batedor", 2)
    td.roll_initiative(NOMES)
    r = td.spawn_monster("Goblin Batedor", "Goblin Reforço", 2)
    assert "Goblin Reforço 1, Goblin Reforço 2" in r


def test_fora_de_combate_recriar_monstro_continua_valendo(emboscada):
    td.spawn_monster("Goblin Batedor", "Goblin Batedor", 1)
    _goblin_unico = memory.campaign["characters"]["goblin batedor"]
    _goblin_unico["sheet"]["vida_atual"] = 1
    r = td.spawn_monster("Goblin Batedor", "Goblin Batedor", 1)
    assert "criado(s)" in r
    assert memory.campaign["characters"]["goblin batedor"]["sheet"]["vida_atual"] == 7


def test_campo_diferente_no_meio_da_luta_redefine(emboscada):
    td.roll_initiative("Thorn, Lyra")
    td.set_battlefield("Trilha, Ruínas")
    td.move_combatant("Thorn", "Ruínas")
    r = td.set_battlefield("Ponte, Rio, Margem")
    assert not r.startswith("Nota:")
    assert td._zona_de("Thorn") == "Ponte"


def test_mesmo_campo_posiciona_quem_entrou_depois(emboscada):
    td.roll_initiative("Thorn, Lyra")
    td.set_battlefield("Trilha, Ruínas")
    td.move_combatant("Thorn", "Ruínas")
    td.roll_initiative("Helena")
    memory.campaign["combat_state"]["posicoes"].pop("helena", None)
    td.set_battlefield("Trilha, Ruínas")
    assert td._zona_de("Helena") == "Trilha" and td._zona_de("Thorn") == "Ruínas"


def test_nova_luta_depois_de_encerrar_rola_normalmente(emboscada):
    td.roll_initiative("Thorn, Lyra")
    td.end_combat()
    r = td.roll_initiative("Thorn, Helena")
    assert r.startswith("Iniciativa rolada!")
    assert set(_cs()["initiative_order"]) == {"Thorn", "Helena"}


# ---------------------------------------------------------------------------
# A retomada do servidor depois de o modelo cair no meio do turno
# ---------------------------------------------------------------------------

def test_retomada_nao_manda_refazer_o_que_ja_foi_feito():
    import server
    texto = server._mensagem_de_retomada("vamos para as ruínas",
                                         {"spawn_monster", "roll_initiative"})
    assert texto.startswith("[TURNO INTERROMPIDO]")
    assert "roll_initiative, spawn_monster" in texto
    assert "NÃO chame essas ferramentas de novo" in texto
    assert texto.endswith("A fala do jogador era: vamos para as ruínas")


def test_consulta_nao_conta_como_algo_ja_feito():
    import server
    assert server._so_le("get_character_sheet") and server._so_le("list_inventory")
    assert not server._so_le("roll_initiative") and not server._so_le("spawn_monster")


def test_modelo_que_cai_depois_de_rolar_iniciativa_nao_recebe_a_fala_de_novo(campanha):
    """
    Pela rota /api/chat: a primeira tentativa chama roll_initiative e cai com
    503; a segunda tem que receber o [TURNO INTERROMPIDO], não a fala crua.
    """
    import server
    from flask import g
    from google.genai import types

    memory.bind("u-retomada", "Retomada")
    memory.campaign["name"] = "Retomada"
    recebidas = []

    class _Evento:
        def __init__(self, parte, final=False):
            self.content = types.Content(role="model", parts=[parte])
            self.usage_metadata = None
            self._final = final

        def is_final_response(self):
            return self._final

    class _Runner:
        async def run_async(self, user_id, session_id, new_message):
            recebidas.append(new_message.parts[0].text)
            if len(recebidas) == 1:
                yield _Evento(types.Part(function_call=types.FunctionCall(
                    name="roll_initiative", args={"characters_names": "Thorn, Goblin"})))
                yield _Evento(types.Part(function_call=types.FunctionCall(
                    name="get_combat_status", args={})))
                raise RuntimeError("503 UNAVAILABLE: the model is overloaded")
            yield _Evento(types.Part(text="Os goblins avançam."), final=True)

    server.get_loop()
    server._sessions["u-retomada"] = {"runner": _Runner(), "is_ollama": False, "model_id": "x",
                                      "adk_user": "u-retomada", "adk_session": "s"}
    try:
        with server.app.test_request_context("/api/chat", method="POST",
                                             json={"message": "vamos para as ruínas",
                                                   "registrar": False}):
            g.user_id = "u-retomada"
            resposta = server.chat.__wrapped__()
            corpo = "".join(resposta.response)
    finally:
        server._sessions.pop("u-retomada", None)

    assert len(recebidas) == 2, corpo[-500:]
    assert recebidas[0] == "vamos para as ruínas"
    assert recebidas[1].startswith("[TURNO INTERROMPIDO]")
    assert "roll_initiative" in recebidas[1] and "get_combat_status" not in recebidas[1]
    assert json.dumps({"type": "text", "content": "Os goblins avançam."}) in corpo
