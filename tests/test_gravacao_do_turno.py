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

    def _save(uid, name, data, versao_esperada=None):
        conta["gravacoes"] += 1
        conta["ultimo"] = data
        conta["versao_pedida"] = versao_esperada
        return (versao_esperada or 0) + 1

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


# ---------------------------------------------------------------------------
# Escrita perdida: o conflito deixa de ser invisível
# ---------------------------------------------------------------------------

def test_a_sessao_devolve_a_versao_que_leu(banco):
    memory.save_campaign()
    assert banco["versao_pedida"] is None       # primeira gravação da sessão
    memory.save_campaign()
    assert banco["versao_pedida"] == 1          # agora sabe em que versão está


def test_fechar_a_sessao_esquece_a_versao(banco):
    """
    Sem isto, a sessão seguinte começaria achando estar numa versão que não
    leu — e a primeira gravação dela pareceria um conflito que não houve.
    """
    memory.save_campaign()
    memory.save_campaign()
    assert banco["versao_pedida"] == 1
    memory.unbind("u-teste")
    memory.bind("u-teste", "Campanha de Teste")
    memory.campaign.update({"name": "Campanha de Teste",
                            "characters": {"a": {"name": "A"}}})
    memory.save_campaign()
    assert banco["versao_pedida"] is None


def test_conflito_e_anotado_e_o_turno_nao_se_perde(banco, monkeypatch, tmp_path):
    """
    Duas abas se atropelaram. O turno do jogador é gravado assim mesmo — ele
    já leu a cena na tela, e recusar aqui jogaria fora o que ele acabou de
    jogar. O que muda é que o atropelo passa a EXISTIR: no log e na medição.
    """
    import json

    from rpg import database, medicao

    monkeypatch.setattr(medicao, "ARQUIVO", tmp_path / "medicao.jsonl")
    monkeypatch.delenv("MEDICAO_DESLIGADA", raising=False)

    tentativas = {"n": 0}

    def _save(uid, name, data, versao_esperada=None):
        tentativas["n"] += 1
        if versao_esperada is not None and tentativas["n"] == 1:
            raise database.ConflitoDeGravacao(versao_esperada, 99)
        banco["gravacoes"] += 1
        banco["ultimo"] = data
        return 100

    memory.save_campaign()          # fixa a versão desta sessão
    banco["gravacoes"] = 0
    monkeypatch.setattr(database, "save_campaign", _save)
    memory.save_campaign()

    assert banco["gravacoes"] == 1, "o turno do jogador não pode evaporar"
    linhas = [json.loads(l) for l in
              (tmp_path / "medicao.jsonl").read_text(encoding="utf-8").splitlines()]
    assert linhas[-1]["conflito"] == {"esperada": 1, "encontrada": 99}
