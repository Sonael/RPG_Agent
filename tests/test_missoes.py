"""
test_missoes.py

A tela de missões (rpg/missoes.py): todas as missões com objetivos marcáveis,
quem deu e o desfecho. Marcar é a lista de tarefas do jogador; o mestre recebe
um aviso só, ao fechar, com o que mudou.
"""
import pytest

from rpg import memory, missoes, tools as tl

from conftest import criar_ficha


@pytest.fixture
def livro(campanha, povoar):
    povoar(criar_ficha("Alden", grupo=True))
    tl.save_character("Brom", "Ferreiro.")
    memory.campaign["missoes_mudadas_na_tela"] = []
    tl.add_quest("O filho do ferreiro", "Achar o filho de Brom.",
                 "Chegar à estrada do norte; Chegar ao acampamento; Trazer o filho", giver="brom",
                 reward="Uma espada sob medida")
    tl.add_quest("Entregar a carta", "Levar a carta ao regente.", giver="Regente Oric")
    tl.add_quest("Limpar o porão", "Ratos no porão da taverna.", "Matar os ratos")
    tl.complete_quest("Limpar o porão", "concluida", "Os ratos eram só três.")
    tl.add_quest("Salvar a vila", "A vila pediu socorro.")
    tl.complete_quest("Salvar a vila", "falhou", "Chegamos tarde.")
    return memory.campaign


def _m(titulo):
    return next(m for m in missoes.quest_snapshot()["missoes"] if m["titulo"] == titulo)


def test_snapshot_com_todas_as_missoes(livro):
    snap = missoes.quest_snapshot()
    assert snap["contagem"] == {"ativa": 2, "concluida": 1, "falhou": 1, "abandonada": 0}
    assert [m["status"] for m in snap["missoes"]][:2] == ["ativa", "ativa"]
    filho = _m("O filho do ferreiro")
    assert filho["quem_deu"] == {"nome": "Brom", "existe": True, "status": "vivo"}
    assert filho["recompensa"] == "Uma espada sob medida"
    assert (filho["feitos"], filho["total"]) == (0, 3)
    assert _m("Entregar a carta")["quem_deu"]["existe"] is False
    assert _m("Limpar o porão")["desfecho"] == "Os ratos eram só três."


def test_marcar_pelo_indice_e_nao_por_trecho(livro):
    r = missoes.quest_action("marcar", "O filho do ferreiro", 1)
    assert r["ok"] is True
    objs = _m("O filho do ferreiro")["objetivos"]
    assert [o["feito"] for o in objs] == [False, True, False], \
        "por trecho, 'Chegar' marcaria o primeiro objetivo"


def test_pronta_para_entregar(livro):
    for i in range(3):
        missoes.quest_action("marcar", "O filho do ferreiro", i)
    assert _m("O filho do ferreiro")["pronta_para_entregar"] is True
    assert _m("O filho do ferreiro")["status"] == "ativa", "a tela não conclui a missão"


def test_fechar_manda_um_aviso_so_com_o_que_mudou(livro):
    missoes.quest_action("marcar", "O filho do ferreiro", 0)
    missoes.quest_action("marcar", "O filho do ferreiro", 2)
    missoes.quest_action("desmarcar", "O filho do ferreiro", 2)     # cancela a de cima
    assert missoes.quest_snapshot()["mudancas_pendentes"] == 1
    r = missoes.quest_action("fechar")
    assert r["recap"].startswith("[MISSÕES ATUALIZADAS NA TELA]")
    assert "marcou como feito 'Chegar à estrada do norte'" in r["recap"]
    assert "Trazer o filho" not in r["recap"]
    assert "update_quest_objective" in r["recap"]
    assert missoes.quest_action("fechar")["recap"] == "", "o aviso repetiu"


def test_fechar_sem_mudancas_nao_avisa(livro):
    assert missoes.quest_action("fechar")["recap"] == ""


def test_abandonar(livro):
    r = missoes.quest_action("abandonar", "Entregar a carta")
    assert r["ok"] is True
    assert _m("Entregar a carta")["status"] == "abandonada"
    assert "abandonou a missão 'Entregar a carta'" in missoes.quest_action("fechar")["recap"]


def test_encerrada_nao_se_mexe(livro):
    assert missoes.quest_action("marcar", "Limpar o porão", 0)["ok"] is False
    assert missoes.quest_action("abandonar", "Salvar a vila")["ok"] is False


def test_acha_pelo_titulo_quando_a_chave_nao_tem_acento(livro):
    """Campanha antiga: chave "a divida de torbin", título "A dívida de Torbin"."""
    livro["quests"]["a divida de torbin"] = {
        "titulo": "A dívida de Torbin", "descricao": "", "status": "ativa",
        "objetivos": [{"texto": "Descobrir quem cobra", "feito": False}]}
    r = missoes.quest_action("marcar", "A dívida de Torbin", 0)
    assert r["ok"] is True, r["message"]
    assert livro["quests"]["a divida de torbin"]["objetivos"][0]["feito"] is True
    assert missoes.quest_action("abandonar", "A dívida de Torbin")["ok"] is True
    assert livro["quests"]["a divida de torbin"]["status"] == "abandonada"


def test_ferramentas_do_mestre_acham_a_missao_com_chave_sem_acento(livro):
    livro["quests"]["a divida de torbin"] = {
        "titulo": "A dívida de Torbin", "descricao": "", "status": "ativa",
        "objetivos": [{"texto": "Descobrir quem cobra", "feito": False}]}
    assert not tl.update_quest_objective("A dívida de Torbin", "Descobrir").startswith("Aviso:")
    assert "A dívida de Torbin" in tl.get_quest("A dívida de Torbin")
    assert not tl.complete_quest("A dívida de Torbin", "concluida").startswith("Aviso:")
    assert livro["quests"]["a divida de torbin"]["status"] == "concluida"


def test_recusas(livro):
    assert missoes.quest_action("marcar", "Não existe", 0)["message"].startswith("Erro:")
    assert missoes.quest_action("marcar", "O filho do ferreiro", 9)["message"].startswith("Erro:")
    assert missoes.quest_action("voar", "O filho do ferreiro")["ok"] is False


def test_rotas(livro):
    import server
    regras = {r.rule for r in server.app.url_map.iter_rules()}
    assert {"/api/quests/state", "/api/quests/action"} <= regras
    with server.app.test_request_context("/api/quests/action", method="POST",
                                         json={"action": "marcar", "quest": "O filho do ferreiro",
                                               "objective": 0}):
        corpo = server.quests_action_route.__wrapped__().get_json()
    assert corpo["ok"] is True
