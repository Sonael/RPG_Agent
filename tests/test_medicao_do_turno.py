"""
test_medicao_do_turno.py

A conta que diz se o esquecimento diminuiu.

Sem número, "melhorou" é opinião. Cada turno deixa uma linha com o que foi
chamado, o que o fechamento registrou e se o jogador precisou cobrar —
usando as frases reais que ele escreveu na campanha medida.
"""
import json

import pytest

from rpg import medicao, memory


@pytest.fixture
def arquivo(tmp_path, monkeypatch, campanha):
    alvo = tmp_path / "medicao.jsonl"
    monkeypatch.setattr(medicao, "ARQUIVO", alvo)
    monkeypatch.delenv("MEDICAO_DESLIGADA", raising=False)
    memory.campaign["name"] = "Teste Inicio"
    return alvo


# ---------------------------------------------------------------------------
# 1. Reconhecer a cobrança — as frases são as da partida de verdade
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("texto, tipo", [
    ("salve o personagem torbin", "personagem"),
    ("adicione Ravenrust ao mapa", "local"),
    ("perguntamos a Barnaby onde fica as colinas cizentas (adicione no mapa)", "local"),
    ("atualize a hora vamos para a praça sentar em uma mesa", "hora"),
    ("mestre atualize os eventos do diario Inscrição na Guilda", "missao_diario"),
    ("não é para rolar os dados, faça um teste de destreza", "teste"),
    ("você esqueceu de salvar o local", "generica"),
])
def test_a_cobranca_do_jogador_e_reconhecida(texto, tipo):
    assert tipo in medicao.cobrancas_do_jogador(texto), medicao.cobrancas_do_jogador(texto)


@pytest.mark.parametrize("texto", [
    "vamos ao estabulo devolver os cavalos que usamos para chegar até a mina",
    "eu vou elogiar helena por ter se saído tão bem na batalha",
    "aceitamos a oferta",
    "[DESCANSO RESOLVIDO NA TELA] Descanso longo concluído — Dia 4, 20h.",
])
def test_jogar_normalmente_nao_e_cobranca(texto):
    assert medicao.cobrancas_do_jogador(texto) == []


def test_mensagem_de_tela_nunca_conta_como_cobranca():
    assert medicao.cobrancas_do_jogador("[SAQUE RESOLVIDO NA TELA] atualize a hora") == []


# ---------------------------------------------------------------------------
# 2. A linha do turno
# ---------------------------------------------------------------------------

def test_cada_turno_deixa_uma_linha(arquivo):
    medicao.registrar_turno("adicione Ravenrust ao mapa", {"save_location"},
                            {"tinha_bloco": True, "campos": {"lugar": ["Ravenrust"]},
                             "feitos": ["save_location('Ravenrust')"], "recusados": []})
    linha = json.loads(arquivo.read_text(encoding="utf-8").strip())
    assert linha["campanha"] == "Teste Inicio"
    assert linha["cobrancas"] == ["local"]
    assert linha["ferramentas"] == ["save_location"]
    assert linha["fechamento"]["tinha_bloco"] is True
    assert linha["fechamento"]["campos"] == {"lugar": 1}


def test_desligada_por_variavel_de_ambiente(arquivo, monkeypatch):
    monkeypatch.setenv("MEDICAO_DESLIGADA", "1")
    medicao.registrar_turno("qualquer coisa", set(), {"tinha_bloco": False})
    assert not arquivo.exists()


def test_medir_nunca_derruba_o_turno(arquivo, monkeypatch):
    """Arquivo impossível de escrever: o turno segue como se nada fosse."""
    monkeypatch.setattr(medicao, "ARQUIVO", arquivo / "impossivel" / "x.jsonl")
    medicao.registrar_turno("texto", set(), {"tinha_bloco": True})   # não levanta


# ---------------------------------------------------------------------------
# 3. O resumo, que é o número da comparação
# ---------------------------------------------------------------------------

def test_o_resumo_conta_cobranca_e_bloco(arquivo):
    turnos = [
        ("adicione Ravenrust ao mapa", True, ["save_location('Ravenrust')"]),
        ("vamos até a forja", True, []),
        ("salve o personagem torbin", False, []),
        ("[SAQUE RESOLVIDO NA TELA] itens divididos", True, []),
    ]
    for texto, bloco, feitos in turnos:
        medicao.registrar_turno(texto, set(), {"tinha_bloco": bloco, "campos": {},
                                               "feitos": feitos, "recusados": []})
    r = medicao.resumo(arquivo)
    assert r["turnos"] == 4 and r["digitados"] == 3
    assert r["turnos_com_cobranca"] == 2
    assert r["porcentagem_de_cobranca"] == pytest.approx(66.7, abs=0.1)
    assert r["turnos_com_bloco"] == 3
    assert r["registros_feitos"] == 1


def test_resumo_sem_arquivo_e_tudo_zero(tmp_path):
    r = medicao.resumo(tmp_path / "nao-existe.jsonl")
    assert r["turnos"] == 0 and r["porcentagem_de_cobranca"] == 0.0
