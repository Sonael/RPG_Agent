"""
test_relogio_do_mestre.py

O relógio do mundo só anda quando o mestre chama advance_time(). Três
reforços para ele não ficar parado, e um defeito:

  • meia-noite virava 8h da manhã: a hora era lida com `or 8`, e 0 é falso.
    O relógio pulava 8 horas a cada dia que virava à meia-noite, e os
    encontros marcados depois dela chegavam 8 horas atrasados;
  • o bloco de cena só mostrava a hora depois do primeiro advance_time: antes
    disso o mestre não via que o mundo estava parado às 8h do dia 1;
  • relógio parado há muitos turnos entra nas pendências, como o resumo;
  • narração que faz o tempo passar ("no dia seguinte") sem o relógio andar
    vira aviso para o mestre no turno seguinte — e não para o jogador, que não
    tem como fazer o relógio andar.
"""
import json

import pytest

from rpg import memory
from rpg import tools_dnd as td


@pytest.fixture
def relogio(campanha):
    campanha["_turno"] = 0
    campanha.pop("_upkeep", None)
    campanha.pop("_pendencias", None)
    campanha["relogio"] = {"dia": 1, "hora": 20}
    return campanha


# --- Meia-noite ---------------------------------------------------------------

def test_meia_noite_e_meia_noite(relogio):
    saida = td.advance_time(4, "até a meia-noite")
    assert relogio["relogio"] == {"dia": 2, "hora": 0}
    assert "Dia 2, 00h (madrugada)" in saida
    assert td._agora_em_horas() == 48

    td.advance_time(1)
    assert relogio["relogio"] == {"dia": 2, "hora": 1}, "o relógio pulou da meia-noite para as 9h"


def test_sem_hora_gravada_continua_sendo_8h():
    assert td.hora_do_relogio({}) == 8
    assert td.hora_do_relogio({"hora": None}) == 8
    assert td.hora_do_relogio({"hora": "lixo"}) == 8
    assert td.hora_do_relogio({"hora": 0}) == 0
    assert td.hora_do_relogio({"hora": "23"}) == 23


def test_encontro_depois_da_meia_noite_chega_na_hora(relogio):
    from rpg import encontros
    relogio["relogio"] = {"dia": 2, "hora": 0}
    assert encontros._agora() == 48


def test_cena_mostra_a_meia_noite(relogio):
    from rpg.tools import get_scene_context
    relogio["relogio"] = {"dia": 3, "hora": 0}
    assert "Tempo: Dia 3, 00h (madrugada)" in get_scene_context()


# --- A hora sempre no bloco de cena -------------------------------------------

def test_cena_mostra_a_hora_antes_do_primeiro_avanco(relogio):
    from rpg.tools import get_scene_context
    relogio["relogio"] = {}
    ctx = get_scene_context()
    assert "Tempo: Dia 1, 08h (manhã)" in ctx
    assert "ainda não andou" in ctx and "advance_time()" in ctx
    assert relogio["relogio"] == {}, "ler a cena não pode dar partida no relógio (a barra esconde a linha)"


# --- Relógio parado nas pendências --------------------------------------------

def test_relogio_parado_entra_nas_pendencias(relogio):
    from rpg.agent import _pendencias_block
    for chave in ("resumo", "diario", "mundo"):
        memory.marcar_upkeep(chave)
    td.advance_time(1)
    for _ in range(10):
        memory.avancar_turno()
        for chave in ("resumo", "diario", "mundo"):
            memory.marcar_upkeep(chave)
    bloco = _pendencias_block()
    assert "10 turnos sem advance_time()" in bloco
    assert "parado em Dia 1, 21h" in bloco


def test_relogio_em_dia_nao_e_cobrado(relogio):
    from rpg.agent import _pendencias_block
    for _ in range(9):
        memory.avancar_turno()
    for chave in ("resumo", "diario", "mundo"):
        memory.marcar_upkeep(chave)
    td.advance_time(2)
    assert _pendencias_block() == ""


def test_relogio_que_nunca_andou_e_cobrado_depois_de_um_tempo(relogio):
    from rpg.agent import _pendencias_block
    relogio["_turno"] = 11
    for chave in ("resumo", "diario", "mundo"):
        memory.marcar_upkeep(chave)
    assert "NUNCA foi chamado nesta campanha: advance_time()" in _pendencias_block()


# --- Narração que faz o tempo passar -------------------------------------------

@pytest.mark.parametrize("texto", [
    "No dia seguinte, a caravana parte.",
    "Horas depois, vocês chegam à ponte.",
    "Três dias de viagem pelas colinas.",
    "Uma hora depois, ela volta com o chá.",
    "Amanheceu quando vocês chegaram.",
    "O sol se pôs atrás da muralha.",
    "Vocês passam a noite na estalagem.",
    "Semanas se passaram desde o baile.",
])
def test_narracao_que_faz_o_tempo_passar_avisa(relogio, texto):
    from rpg.validator import validate
    avisos = [v for v in validate(texto).violations if v.rule == "time_not_advanced"]
    assert len(avisos) == 1, texto
    assert "advance_time(horas, motivo)" in avisos[0].message


@pytest.mark.parametrize("texto", [
    "Ele promete voltar amanhã.",
    "Encontre-me ao anoitecer, na praça.",
    "Vocês conversam por alguns minutos.",
    "A noite é fria e o vento sopra.",
])
def test_fala_sobre_o_tempo_nao_avisa(relogio, texto):
    from rpg.validator import validate
    assert not [v for v in validate(texto).violations if v.rule == "time_not_advanced"], texto


def test_relogio_que_andou_no_turno_nao_avisa(relogio):
    from rpg.validator import validate
    td.advance_time(12, "viagem")
    assert not [v for v in validate("No dia seguinte, a caravana parte.").violations
                if v.rule == "time_not_advanced"]


def test_aviso_vai_para_o_mestre_e_nao_para_o_jogador(relogio):
    """Pela rota /api/chat, com um turno que narra o dia seguinte sem o relógio."""
    import server
    from flask import g
    from google.genai import types

    memory.bind("u-relogio", "Relogio")
    memory.campaign["name"] = "Relogio"
    memory.campaign["relogio"] = {"dia": 1, "hora": 20}
    memory.campaign["_pendencias"] = []

    class _Evento:
        def __init__(self, parte):
            self.content = types.Content(role="model", parts=[parte])
            self.usage_metadata = None

        def is_final_response(self):
            return True

    class _Runner:
        async def run_async(self, user_id, session_id, new_message):
            yield _Evento(types.Part(text="No dia seguinte, a caravana parte para o norte."))

    server.get_loop()
    server._sessions["u-relogio"] = {"runner": _Runner(), "is_ollama": False, "model_id": "x",
                                     "adk_user": "u-relogio", "adk_session": "s"}
    try:
        with server.app.test_request_context("/api/chat", method="POST",
                                             json={"message": "seguimos viagem"}):
            g.user_id = "u-relogio"
            corpo = "".join(server.chat.__wrapped__().response)
    finally:
        server._sessions.pop("u-relogio", None)

    assert json.dumps({"type": "text", "content": "No dia seguinte, a caravana parte para o norte."}) in corpo
    assert "time_not_advanced" not in corpo, "o aviso do relógio chegou ao jogador"
    assert any("advance_time" in p for p in memory.campaign["_pendencias"]), memory.campaign["_pendencias"]
