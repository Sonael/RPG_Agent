"""
test_ficha_relacao.py
A ficha mostrando — e deixando corrigir — a relação.

Três coisas anotadas jogando:
  • "seria bom ver na ficha dos personagens do meu grupo a relação dele
     comigo, só dá pra ver no mundo": a ficha escondia a atitude de quem é do
     grupo, justamente de quem convive com o jogador o tempo todo;
  • "Helena: atitude +5 → -5 (neutro) ... porém helena tem 90 de lealdade":
     os dois números existem e precisam aparecer juntos, senão um desmente o
     outro na cara do jogador;
  • "desse pra editar isso": quem sabe o que aconteceu na mesa é quem jogou.
"""
import pytest

from rpg import entre, memory, personagens


@pytest.fixture
def campanha(monkeypatch):
    monkeypatch.setattr(memory, "save_campaign", lambda *a, **k: None)
    memory.campaign.clear()
    memory.campaign.update({
        "name": "Teste", "chapter": 2, "protagonist": "Sonael",
        "current_location": "Valenport", "campaign_type": "fantasia",
        "party": [{"name": "Sonael", "role": "mago", "notes": ""},
                  {"name": "Helena", "role": "guerreira", "notes": ""},
                  {"name": "Selene", "role": "clériga", "notes": ""}],
        "characters": {
            "sonael": {"name": "Sonael", "status": "vivo", "party_member": True},
            "helena": {"name": "Helena", "status": "vivo", "party_member": True,
                       "atitude": 20, "lealdade": 90},
            "selene": {"name": "Selene", "status": "vivo", "party_member": True},
            "brom": {"name": "Brom", "status": "vivo", "atitude": -30},
        },
        "locations": {}, "events": [], "quests": {}, "flags": {},
        "conversation_history": [],
    })
    return memory.campaign


# ---------------------------------------------------------------------------
# Ver
# ---------------------------------------------------------------------------

def test_companheiro_mostra_a_atitude(campanha):
    f = personagens.ficha("Helena")
    assert f["atitude"]["valor"] == 20
    assert f["atitude"]["rotulo"]


def test_companheiro_mostra_atitude_e_lealdade_juntas(campanha):
    """O caso que gerou a dúvida: +20 com o grupo e 90 de lealdade."""
    f = personagens.ficha("Helena")
    assert f["atitude"]["valor"] == 20
    assert f["laco"]["lealdade"]["valor"] == 90
    assert f["laco"]["lealdade"]["faixa"] == "até o fim"


def test_companheiro_nao_recebe_efeitos_de_regra(campanha):
    """Preço de loja e CD de teste social são para quem NÃO é do grupo."""
    assert personagens.ficha("Helena")["atitude"]["efeitos"] == []


def test_quem_nao_e_do_grupo_continua_com_os_efeitos(campanha):
    assert personagens.ficha("Brom")["atitude"]["valor"] == -30


def test_o_proprio_jogador_nao_tem_atitude_consigo(campanha):
    assert personagens.ficha("Sonael")["atitude"] is None


def test_a_ficha_traz_as_relacoes_com_os_outros(campanha):
    entre.ajustar("Helena", "Selene", -25, "o controle velado")
    f = personagens.ficha("Helena")
    assert [r["nome"] for r in f["entre"]] == ["Selene"]
    assert f["entre"][0]["valor"] == -25
    assert f["entre"][0]["motivo"] == "o controle velado"


# ---------------------------------------------------------------------------
# Editar
# ---------------------------------------------------------------------------

def test_editar_a_atitude(campanha):
    f = personagens.editar_relacao("Helena", {"atitude": 35, "motivo": "salvou o grupo na mina"})
    assert f["atitude"]["valor"] == 35
    assert f["atitude"]["historico"][0]["motivo"] == "salvou o grupo na mina"
    assert f["atitude"]["historico"][0]["delta"] == 15


def test_editar_a_lealdade(campanha):
    f = personagens.editar_relacao("Helena", {"lealdade": 40, "motivo": "a briga na mina"})
    assert f["laco"]["lealdade"]["valor"] == 40
    assert f["laco"]["historico"][0]["delta"] == -50


def test_editar_sem_motivo_ainda_registra(campanha):
    f = personagens.editar_relacao("Helena", {"atitude": 30})
    assert f["atitude"]["historico"][0]["motivo"] == "ajustado pelo jogador"


def test_o_mesmo_valor_nao_inventa_historico(campanha):
    f = personagens.editar_relacao("Helena", {"lealdade": 90})
    assert f["laco"]["lealdade"]["valor"] == 90
    assert f["laco"]["historico"] == []


def test_criar_uma_relacao_entre_dois(campanha):
    f = personagens.editar_relacao(
        "Selene", {"para": "Sonael", "valor": 60, "motivo": "amigos de infância"})
    assert f["entre"][0]["nome"] == "Sonael"
    assert f["entre"][0]["valor"] == 60
    # É direcional: Sonael ainda não disse nada.
    assert personagens.ficha("Sonael")["entre"] == []


def test_apagar_uma_relacao(campanha):
    personagens.editar_relacao("Helena", {"para": "Selene", "valor": -20})
    f = personagens.editar_relacao("Helena", {"para": "Selene", "apagar": True})
    assert f["entre"] == []


def test_valor_que_nao_e_numero_e_recusado(campanha):
    assert "erro" in personagens.editar_relacao("Helena", {"atitude": "muito"})
    assert "erro" in personagens.editar_relacao("Helena", {"para": "Selene", "valor": ""})


def test_personagem_que_nao_existe(campanha):
    assert "erro" in personagens.editar_relacao("Ninguém", {"atitude": 10})
    assert "erro" in personagens.editar_relacao("Helena", {"para": "Ninguém", "valor": 10})


def test_lealdade_do_protagonista_e_recusada(campanha):
    """Lealdade é dos companheiros: o protagonista não é leal a si mesmo."""
    assert "erro" in personagens.editar_relacao("Sonael", {"lealdade": 50})


def test_pedido_vazio(campanha):
    assert "erro" in personagens.editar_relacao("Helena", {})


def test_a_rota_existe_e_usa_a_mesma_porta():
    import inspect
    import server
    fonte = inspect.getsource(server.character_relation_route)
    assert "personagens.editar_relacao" in fonte
    assert "400" in fonte
