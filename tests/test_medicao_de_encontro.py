"""
test_medicao_de_encontro.py
O encontro sugerido e o encontro que aconteceu.

Na partida de 91 turnos o sistema calculou o orçamento e ofereceu três opções
balanceadas (Bugbear CR 1, 3 Goblins, 5 Bandidos) — e o mestre criou os
próprios Cultistas do Minério por fora. Antes de obrigar alguma coisa, medir:
foi uma vez ou é a regra?

A medição não muda o jogo: ela anota, falha em silêncio e sai do caminho com
MEDICAO_DESLIGADA=1.
"""
import copy
import json

import pytest

from rpg import medicao, memory


@pytest.fixture
def arquivo(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "save_campaign", lambda *a, **k: None)
    # Guarda e devolve a campanha ativa: ela é global, e deixá-la pela metade
    # derruba outro arquivo de teste, longe da causa.
    guardado = copy.deepcopy({k: v for k, v in memory.campaign.items()})
    memory.campaign.clear()
    memory.campaign.update({"name": "Teste", "chapter": 1, "turno": 1,
                            "conversation_history": []})
    alvo = tmp_path / "medicao.jsonl"
    monkeypatch.setattr(medicao, "ARQUIVO", alvo)
    # A suíte nasce com a medição desligada (conftest); quem a testa liga de
    # volta, apontando para o tmp_path acima.
    monkeypatch.delenv("MEDICAO_DESLIGADA", raising=False)
    yield alvo
    memory.campaign.clear()
    memory.campaign.update(guardado)


def _linhas(arquivo):
    return [json.loads(l) for l in arquivo.read_text(encoding="utf-8").splitlines()]


def _turno(mensagem="Ataco o cultista.", ferramentas=()):
    medicao.registrar_turno(mensagem, set(ferramentas), {"tinha_bloco": True, "campos": {}})


def test_seguiu_a_sugestao(arquivo):
    medicao.registrar_sugestao(["Bugbear", "Goblin", "Bandit"], 300)
    medicao.registrar_inimigo("Goblin")
    _turno()
    encontro = _linhas(arquivo)[0]["encontro"]
    assert encontro["seguiu"] is True
    assert encontro["criados"] == ["Goblin"]


def test_ignorou_a_sugestao(arquivo):
    """O caso real: pediu o encontro balanceado e criou outra coisa."""
    medicao.registrar_sugestao(["Bugbear", "Goblin", "Bandit"], 300)
    medicao.registrar_inimigo("Cultist")
    _turno()
    assert _linhas(arquivo)[0]["encontro"]["seguiu"] is False


def test_sem_sugestao_nao_ha_julgamento(arquivo):
    medicao.registrar_inimigo("Cultist")
    _turno()
    assert _linhas(arquivo)[0]["encontro"]["seguiu"] is None


def test_turno_sem_encontro_nao_ganha_a_secao(arquivo):
    _turno()
    assert "encontro" not in _linhas(arquivo)[0]


def test_o_que_foi_criado_conta_uma_vez_so(arquivo):
    medicao.registrar_sugestao(["Goblin"], 100)
    medicao.registrar_inimigo("Goblin")
    _turno()
    _turno()
    linhas = _linhas(arquivo)
    assert linhas[0]["encontro"]["criados"] == ["Goblin"]
    assert "encontro" not in linhas[1] or linhas[1]["encontro"]["criados"] == []


def test_a_sugestao_vale_para_o_turno_seguinte(arquivo):
    """Sugerir e criar costumam ser turnos diferentes."""
    medicao.registrar_sugestao(["Goblin"], 100)
    _turno()
    medicao.registrar_inimigo("Goblin")
    _turno()
    assert _linhas(arquivo)[1]["encontro"]["seguiu"] is True


def test_nome_parecido_conta_como_seguido(arquivo):
    medicao.registrar_sugestao(["Goblin"], 100)
    medicao.registrar_inimigo("Goblin Boss")
    _turno()
    assert _linhas(arquivo)[0]["encontro"]["seguiu"] is True


def test_resumo_conta_as_duas_coisas(arquivo):
    medicao.registrar_sugestao(["Goblin"], 100)
    medicao.registrar_inimigo("Goblin")
    _turno()
    medicao.registrar_sugestao(["Bugbear"], 200)
    medicao.registrar_inimigo("Cultist")
    _turno()
    r = medicao.resumo(arquivo)
    assert r["turnos_com_inimigo_novo"] == 2
    assert r["turnos_com_sugestao_na_mesa"] == 2
    assert r["seguiram_a_sugestao"] == 1
    assert r["porcentagem_que_seguiu"] == 50.0


def test_resumo_sem_encontro_nenhum(arquivo):
    _turno()
    r = medicao.resumo(arquivo)
    assert r["turnos_com_inimigo_novo"] == 0
    assert r["porcentagem_que_seguiu"] == 0.0


def test_medir_nunca_derruba_o_turno(arquivo, monkeypatch):
    monkeypatch.setattr(medicao, "_caderno", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    medicao.registrar_sugestao(["Goblin"], 100)      # não levanta
    medicao.registrar_inimigo("Goblin")              # não levanta
    _turno()
    assert _linhas(arquivo)


def test_desligada_nao_escreve(arquivo, monkeypatch):
    monkeypatch.setenv("MEDICAO_DESLIGADA", "1")
    medicao.registrar_sugestao(["Goblin"], 100)
    medicao.registrar_inimigo("Goblin")
    _turno()
    assert not arquivo.exists()


def test_as_ferramentas_anotam_sozinhas():
    """Sem estas chamadas, a medição fica cega."""
    import inspect
    from rpg import tools_dnd as td
    assert "medicao.registrar_sugestao" in inspect.getsource(td.suggest_encounter)
    assert "medicao.registrar_inimigo" in inspect.getsource(td.spawn_monster)
