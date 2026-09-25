"""
test_gravacao_do_turno.py

Quanto custava salvar um turno, medido na campanha real (219 KB, 82% dela
histórico de conversa):

    um turno com cinco ações do motor  →  7 LEITURAS + 7 GRAVAÇÕES, 1,15 MB

Cada ferramenta chama save_campaign() ao terminar, e cada save_campaign lia a
campanha do banco antes de gravar (a trava contra sobrescrever com memória
vazia). Catorze idas à rede dentro do tempo de resposta do jogador, todas para
o mesmo documento, do qual só a última versão importa.

Agora: 0 leituras e 1 gravação.

  • gravacao_adiada() junta as gravações do turno numa só;
  • a trava da memória vazia pergunta à MEMÓRIA, não ao banco: campanha sem
    histórico, sem resumo e sem personagem não tem o que salvar — exista linha
    gravada ou não. Quem cria a linha da campanha nova é a rota de criação,
    que chama database.save_campaign direto.
"""
import threading

import pytest

from rpg import database, memory


@pytest.fixture
def banco(monkeypatch):
    """Conta o que sai para o banco, sem sair para o banco."""
    conta = {"gravacoes": 0, "leituras": 0, "ultimo": None}

    def _save(uid, name, data):
        conta["gravacoes"] += 1
        conta["ultimo"] = data

    def _get(uid, name):
        conta["leituras"] += 1
        return {"name": name}

    monkeypatch.setattr(database, "save_campaign", _save)
    monkeypatch.setattr(database, "get_campaign", _get)

    memory.bind("u-teste", "Campanha de Teste")
    memory.campaign.update({
        "name": "Campanha de Teste",
        "conversation_history": [{"role": "user", "text": "olá"}],
        "characters": {"a": {"name": "A"}},
    })
    yield conta
    memory.unbind("u-teste")


# ---------------------------------------------------------------------------
# Uma gravação por turno
# ---------------------------------------------------------------------------

def test_sem_escopo_cada_save_grava(banco):
    memory.save_campaign()
    memory.save_campaign()
    assert banco["gravacoes"] == 2


def test_dentro_do_escopo_grava_uma_vez_so(banco):
    with memory.gravacao_adiada():
        for _ in range(8):
            memory.save_campaign()
        assert banco["gravacoes"] == 0, "não pode gravar no meio do turno"
    assert banco["gravacoes"] == 1


def test_o_que_grava_e_o_estado_FINAL(banco):
    with memory.gravacao_adiada():
        memory.campaign["chapter"] = 1
        memory.save_campaign()
        memory.campaign["chapter"] = 2
        memory.save_campaign()
    assert banco["ultimo"]["chapter"] == 2


def test_turno_sem_mudanca_nao_grava(banco):
    with memory.gravacao_adiada():
        pass
    assert banco["gravacoes"] == 0


def test_escopos_aninhados_so_o_de_fora_grava(banco):
    with memory.gravacao_adiada():
        with memory.gravacao_adiada():
            memory.save_campaign()
        assert banco["gravacoes"] == 0, "o escopo de dentro não pode fechar a conta"
    assert banco["gravacoes"] == 1


def test_erro_no_meio_do_turno_ainda_grava(banco):
    """O jogador fechou a aba, a IA caiu, o motor levantou exceção: o que já
    aconteceu na ficha não pode evaporar."""
    with pytest.raises(RuntimeError):
        with memory.gravacao_adiada():
            memory.save_campaign()
            raise RuntimeError("a IA caiu")
    assert banco["gravacoes"] == 1


def test_depois_do_escopo_volta_a_gravar_na_hora(banco):
    with memory.gravacao_adiada():
        memory.save_campaign()
    memory.save_campaign()
    assert banco["gravacoes"] == 2


def test_a_marca_atravessa_a_thread_do_agente(banco):
    """
    As ferramentas rodam na thread do agente, que se vincula à mesma sessão.
    A marca de "tem coisa para gravar" mora no módulo, por chave de sessão —
    num ContextVar ela não voltaria para quem fecha o escopo.
    """
    def na_thread():
        memory.bind_request("u-teste")
        memory.campaign["chapter"] = 7
        memory.save_campaign()

    with memory.gravacao_adiada():
        t = threading.Thread(target=na_thread)
        t.start()
        t.join()
        assert banco["gravacoes"] == 0
    assert banco["gravacoes"] == 1
    assert banco["ultimo"]["chapter"] == 7


# ---------------------------------------------------------------------------
# A trava que não lê mais o banco
# ---------------------------------------------------------------------------

def test_salvar_nao_le_o_banco(banco):
    memory.save_campaign()
    assert banco["leituras"] == 0


def test_um_turno_inteiro_nao_le_o_banco(banco):
    with memory.gravacao_adiada():
        for _ in range(8):
            memory.save_campaign()
    assert banco["leituras"] == 0
    assert banco["gravacoes"] == 1


def test_memoria_vazia_nao_sobrescreve(banco):
    memory.campaign.update({"conversation_history": [], "story_summary": "",
                            "characters": {}})
    memory.save_campaign()
    assert banco["gravacoes"] == 0


@pytest.mark.parametrize("campo,valor", [
    ("conversation_history", [{"role": "user", "text": "oi"}]),
    ("story_summary", "A história começou."),
    ("characters", {"a": {"name": "A"}}),
])
def test_qualquer_conteudo_de_verdade_libera_a_gravacao(banco, campo, valor):
    memory.campaign.update({"conversation_history": [], "story_summary": "",
                            "characters": {}})
    memory.campaign[campo] = valor
    memory.save_campaign()
    assert banco["gravacoes"] == 1


def test_sem_nome_nao_grava(banco):
    memory.campaign["name"] = ""
    memory.save_campaign()
    assert banco["gravacoes"] == 0


def test_o_historico_continua_limitado(banco):
    memory.campaign["conversation_history"] = [
        {"role": "user", "text": str(i)} for i in range(memory.MAX_HISTORY_SAVED + 50)]
    memory.save_campaign()
    assert len(banco["ultimo"]["conversation_history"]) == memory.MAX_HISTORY_SAVED


# ---------------------------------------------------------------------------
# O turno do chat usa isso
# ---------------------------------------------------------------------------

def test_o_chat_abre_o_escopo_no_turno():
    import inspect
    import server
    fonte = inspect.getsource(server.chat)
    assert "memory.gravacao_adiada()" in fonte
    # O escopo tem de envolver o turno INTEIRO, não um pedaço.
    assert "yield from _turno()" in fonte
