"""
test_diario.py

O diário como livro (rpg/diario.py): capítulos com as entradas, os eventos,
os personagens e locais citados e as missões que começaram ou terminaram.
"""
import pytest

from rpg import diario, memory, tools as tl

from conftest import criar_ficha


@pytest.fixture
def cronica(campanha, povoar):
    povoar(criar_ficha("Thorn", grupo=True), criar_ficha("Lyra", grupo=True))
    c = memory.campaign
    c["diary"] = []
    c["events"] = []
    tl.save_character("Brom", "Ferreiro.", local="Forja de Cliviate")
    tl.save_character("Guarda Tiel", "Guarda da praça.")
    tl.save_location("Cliviate", "Cidade.")
    tl.save_location("Floresta das Brumas", "Neblina.")

    c["chapter"] = 1
    tl.add_diary_entry("A chegada a Cliviate", "Thorn e Lyra chegaram a Cliviate. Brom recebeu o grupo "
                                               "na forja; Brom desconfia de forasteiros.")
    tl.save_event("O martelo devolvido", "Brom, Thorn", "Forja de Cliviate", "Brom confia no grupo")
    tl.add_quest("O filho do ferreiro", "Achar o filho de Brom.", giver="Brom")

    c["chapter"] = 2
    tl.add_diary_entry("A floresta", "A neblina da Floresta das Brumas engoliu a trilha. Lyra seguiu na frente.")
    tl.save_event("Emboscada", "Lyra; Thorn e Guarda Tiel", "Floresta das Brumas", "")
    tl.complete_quest("O filho do ferreiro", "concluida")
    return c


def _cap(snap, n):
    return next(x for x in snap["capitulos"] if x["numero"] == n)


def test_capitulos_em_ordem_com_as_entradas(cronica):
    snap = diario.diary_snapshot()
    assert [c["numero"] for c in snap["capitulos"]] == [1, 2]
    assert snap["capitulo_atual"] == 2
    assert _cap(snap, 2)["atual"] is True and _cap(snap, 1)["atual"] is False
    um = _cap(snap, 1)
    assert um["titulo"] == "A chegada a Cliviate"
    assert [e["indice"] for e in um["entradas"]] == [0]
    assert um["entradas"][0]["conteudo"].startswith("Thorn e Lyra")


def test_save_event_grava_o_capitulo(cronica):
    assert [e["chapter"] for e in memory.campaign["events"]] == [1, 2]
    snap = diario.diary_snapshot()
    assert [e["resumo"] for e in _cap(snap, 1)["eventos"]] == ["O martelo devolvido"]
    assert [e["resumo"] for e in _cap(snap, 2)["eventos"]] == ["Emboscada"]


def test_personagens_do_evento_com_ficha_ou_sem(cronica):
    memory.campaign["events"][1]["characters_involved"] = "Lyra; Guarda Tiel e Mercador Sem Nome"
    ev = _cap(diario.diary_snapshot(), 2)["eventos"][0]
    assert ev["personagens"] == [{"nome": "Lyra", "tem_ficha": True},
                                 {"nome": "Guarda Tiel", "tem_ficha": True},
                                 {"nome": "Mercador Sem Nome", "tem_ficha": False}]


def test_personagens_ligados_mais_citados_primeiro(cronica):
    um = _cap(diario.diary_snapshot(), 1)
    nomes = [p["nome"] for p in um["personagens"]]
    # Brom: 1 no evento + 2 no texto; Thorn: 1 no evento + 1 no texto; Lyra: 1 no texto.
    assert nomes == ["Brom", "Thorn", "Lyra"]
    assert um["personagens"][0]["citacoes"] == 3
    assert um["personagens"][1]["do_grupo"] is True


def test_nome_citado_so_como_palavra_inteira(cronica, povoar):
    povoar(criar_ficha("Ana", grupo=True))
    memory.campaign["diary"][1]["content"] = "Uma semana e uma banana depois, Ana chegou."
    nomes = [p["nome"] for p in _cap(diario.diary_snapshot(), 2)["personagens"]]
    assert nomes.count("Ana") == 1
    assert next(p for p in _cap(diario.diary_snapshot(), 2)["personagens"] if p["nome"] == "Ana")["citacoes"] == 1


def test_locais_do_evento_e_do_texto(cronica):
    snap = diario.diary_snapshot()
    assert _cap(snap, 1)["locais"] == ["Forja de Cliviate", "Cliviate"]
    assert _cap(snap, 2)["locais"] == ["Floresta das Brumas"]


def test_missao_que_comecou_e_que_terminou(cronica):
    snap = diario.diary_snapshot()
    assert _cap(snap, 1)["missoes"] == [{"titulo": "O filho do ferreiro", "status": "concluida",
                                         "marco": "começou"}]
    assert _cap(snap, 2)["missoes"] == [{"titulo": "O filho do ferreiro", "status": "concluida",
                                         "marco": "concluída"}]


def test_capitulo_gravado_como_texto(cronica):
    memory.campaign["diary"][0]["chapter"] = "1"
    memory.campaign["events"][0]["chapter"] = "1"
    memory.campaign["chapter"] = "2"
    snap = diario.diary_snapshot()
    assert [c["numero"] for c in snap["capitulos"]] == [1, 2]
    assert len(_cap(snap, 1)["eventos"]) == 1


def test_evento_antigo_sem_capitulo_e_mover(cronica):
    memory.campaign["events"].append({"index": "3", "summary": "O duelo das pétalas",
                                      "characters_involved": "Thorn", "location": "", "consequence": ""})
    snap = diario.diary_snapshot()
    assert [e["resumo"] for e in snap["eventos_sem_capitulo"]] == ["O duelo das pétalas"]
    assert snap["eventos_sem_capitulo"][0]["index"] == 3

    r = diario.mover_evento(3, "1")
    assert r["ok"] is True
    snap = diario.diary_snapshot()
    assert snap["eventos_sem_capitulo"] == []
    assert "O duelo das pétalas" in [e["resumo"] for e in _cap(snap, 1)["eventos"]]
    assert diario.mover_evento(99, 1)["ok"] is False
    assert diario.mover_evento(3, 0)["message"].startswith("Erro:")


def test_capitulo_atual_sem_nada_aparece(cronica):
    memory.campaign["chapter"] = 4
    snap = diario.diary_snapshot()
    assert [c["numero"] for c in snap["capitulos"]] == [1, 2, 4]
    quatro = _cap(snap, 4)
    assert quatro["atual"] and quatro["entradas"] == [] and quatro["titulo"] == ""


def test_diario_vazio(campanha):
    memory.campaign["chapter"] = 1
    memory.campaign["diary"] = []
    memory.campaign["events"] = []
    snap = diario.diary_snapshot()
    assert [c["numero"] for c in snap["capitulos"]] == [1]
    assert snap["total_entradas"] == 0 and snap["eventos_sem_capitulo"] == []


def test_rotas(cronica):
    import server
    regras = {r.rule for r in server.app.url_map.iter_rules()}
    assert {"/api/diary/book", "/api/diary/move-event"} <= regras
    with server.app.test_request_context("/api/diary/book"):
        corpo = server.diary_book_route.__wrapped__().get_json()
    assert [c["numero"] for c in corpo["capitulos"]] == [1, 2]
    memory.campaign["events"][0].pop("chapter")
    with server.app.test_request_context("/api/diary/move-event", method="POST",
                                         json={"index": 1, "chapter": 2}):
        resposta = server.diary_move_event_route.__wrapped__()
    assert resposta[1] == 200 and resposta[0].get_json()["ok"] is True
    assert memory.campaign["events"][0]["chapter"] == 2


def test_mais_entrada_pelo_editor_cria_a_entrada(cronica):
    """O "+ Entrada" grava na posição logo depois da última; dava 404."""
    import server
    n = len(memory.campaign["diary"])
    with server.app.test_request_context(f"/api/memory/diary/{n}", method="PUT",
                                         json={"title": "Nova", "chapter": 2, "content": "Texto."}):
        resposta = server.update_diary.__wrapped__(n)
    assert resposta.get_json() == {"ok": True}
    assert memory.campaign["diary"][-1] == {"chapter": 2, "title": "Nova", "content": "Texto."}
    with server.app.test_request_context(f"/api/memory/diary/{n + 5}", method="PUT", json={"title": "x"}):
        assert server.update_diary.__wrapped__(n + 5)[1] == 404


def test_editar_evento_com_numero_gravado_como_texto(cronica):
    import server
    memory.campaign["events"][0]["index"] = "1"
    with server.app.test_request_context("/api/memory/events/1", method="PUT",
                                         json={"summary": "O martelo do avô devolvido"}):
        assert server.update_event.__wrapped__(1).get_json() == {"ok": True}
    assert memory.campaign["events"][0]["summary"] == "O martelo do avô devolvido"
