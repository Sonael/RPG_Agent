"""
test_persistencia_estado.py

`load_campaign()` percorre `memory._defaults()` e copia SÓ as chaves que
encontra nele. Chave que não estiver lá é gravada no banco e DESCARTADA na
leitura seguinte — silenciosamente, sem erro nenhum.

Foi o que aconteceu com a onda 4: missões, relógio e lojas eram salvos
corretamente e sumiam no próximo carregamento da campanha. O jogador perdia o
diário de missões inteiro ao voltar ao menu e entrar de novo.

O mesmo vale para `server._payload_de_campanha`, a lista branca por onde passa
toda campanha criada pelo wizard ou importada de arquivo.

Estes testes são a trava: quem acrescentar estado de campanha no futuro
descobre aqui, não em produção.
"""
import pytest

from rpg import memory, tools, tools_dnd as td


# Estado que o jogo grava e que PRECISA sobreviver a um ciclo de save/load.
ESTADO_QUE_PRECISA_PERSISTIR = [
    "relogio",      # onda 4 — hora do mundo
    "quests",       # onda 4 — missões
    "lojas",        # onda 4 — estoques abertos
    "_turno",       # onda 4 — contador de manutenção
    "_upkeep",      # onda 4 — quando cada tarefa foi feita
    "combat_state", # ondas 1–3 — inclui zonas e posições
]


@pytest.mark.parametrize("chave", ESTADO_QUE_PRECISA_PERSISTIR)
def test_chave_esta_nos_defaults(chave):
    assert chave in memory._defaults(), (
        f"'{chave}' não está em memory._defaults(): load_campaign() vai "
        f"descartá-la na próxima leitura."
    )


def test_payload_de_importacao_carrega_o_estado(campanha):
    """
    O que o jogo grava tem de atravessar a importação. Sem isso, exportar e
    reimportar uma campanha jogava fora tudo o que o grupo construiu.
    """
    import server

    dados = {
        "campaign_type": "dnd",
        "relogio": {"dia": 4, "hora": 19},
        "quests": {"escoltar": {"titulo": "Escoltar", "status": "ativa",
                                "objetivos": []}},
        "lojas": {"forja": {"nome": "Forja", "local": "", "estoque": []}},
        "_turno": 12,
        "_upkeep": {"resumo": 9},
    }
    payload = server._payload_de_campanha("Teste", dados, {})

    for chave in ("relogio", "quests", "lojas", "_turno", "_upkeep"):
        assert payload.get(chave) == dados[chave], (
            f"_payload_de_campanha perdeu '{chave}' — a campanha importada "
            f"nasce sem ele."
        )


def test_payload_espelha_os_defaults(campanha):
    """
    As duas listas brancas precisam contar a mesma história. Se uma conhece
    uma chave e a outra não, campanha importada e campanha jogada divergem.
    """
    import server

    payload = server._payload_de_campanha("Teste", {}, {})
    defaults = memory._defaults()

    # `_pendencias` é a única exceção: são os avisos do validador sobre a
    # ÚLTIMA resposta. Não faz sentido importar de outra campanha.
    #
    # A comparação é só da RAIZ. As sub-chaves de combat_state (zonas,
    # posicoes, turn_economy…) viajam dentro do próprio dict.
    esperado = set(defaults) - {"_pendencias"}
    faltando = esperado - set(payload)
    assert not faltando, (
        f"_payload_de_campanha não conhece {sorted(faltando)} — quem importar "
        f"uma campanha com esses dados vai perdê-los."
    )


def test_o_ciclo_completo_preserva_missao_e_relogio(campanha, monkeypatch):
    """
    Teste de ponta a ponta do que quebrou: grava, recarrega, confere.
    O banco é um dict em memória — o que interessa aqui é o filtro do load,
    não o Supabase.
    """
    banco = {}
    from rpg import database

    monkeypatch.setattr(database, "save_campaign",
                        lambda uid, nome, dados: banco.__setitem__((uid, nome), dados))
    monkeypatch.setattr(database, "get_campaign",
                        lambda uid, nome: banco.get((uid, nome)))
    memory.bind("u1", "Ciclo")
    memory.campaign["name"] = "Ciclo"
    # save_campaign RECUSA gravar por cima de uma campanha existente quando a
    # memória está vazia (trava contra apagar dados por acidente). Sem um
    # personagem aqui, a segunda gravação seria bloqueada e o teste mediria a
    # trava, não o filtro do load.
    memory.campaign["characters"]["aria"] = {
        "name": "Aria", "status": "vivo", "description": "", "traits": "",
        "notes": "", "sheet": None,
    }

    tools.add_quest("Escoltar Elara", "…", objectives="Sair; Chegar")
    td.advance_time(9, "viagem")
    memory.avancar_turno()
    memory.save_campaign()

    memory.load_campaign()

    assert "escoltar elara" in memory.campaign["quests"], "a missão sumiu"
    assert memory.campaign["relogio"] == {"dia": 1, "hora": 17}, "o relógio voltou"
    assert memory.campaign["_turno"] == 1, "o contador de turnos zerou"
