"""
test_pechincha.py

Barganhar virou jogada: um teste de Persuasão contra o lojista, uma vez por
visita, com o resultado no preço.

Antes o jogador pedia desconto no chat e o mestre decidia de cabeça — a
perícia social do personagem não entrava na conta, e o desconto não existia
em número nenhum.
"""
import pytest

from rpg import memory, tools, tools_dnd as td

from conftest import criar_ficha


@pytest.fixture
def forja(campanha, povoar):
    memory.campaign["characters"]["torbin"] = {
        "name": "Torbin", "sheet": None, "status": "vivo", "local": "Oakhaven",
        "description": "Ferreiro corpulento."}
    lyra = criar_ficha("Lyra", grupo=True, carisma=16, nivel=3)
    lyra["sheet"]["classe"] = "bardo"          # Persuasão é perícia da classe
    povoar(lyra)
    memory.campaign["characters"]["lyra"]["sheet"]["ouro"] = 300
    memory.campaign["current_location"] = "Oakhaven"
    td.open_shop("Forja do Torbin", "Espada Longa:20:3", location="Oakhaven", owner="Torbin")
    return memory.campaign


def _loja():
    return memory.campaign["lojas"]["forja do torbin"]


def _preco():
    snap = td.shop_snapshot("Forja do Torbin", "Lyra")
    return next(i for i in snap["estoque"] if i["nome"] == "Espada Longa")["preco"]


def test_sucesso_derruba_o_preco_da_visita(forja, monkeypatch):
    monkeypatch.setattr(td.random, "randint", lambda a, b: 15)
    saida = td.haggle("Lyra", "Forja do Torbin")
    assert "SUCESSO" in saida and "desconto" in saida
    assert _preco() == 18               # 20 com 10% de desconto
    assert td.buy_item("Lyra", "Forja do Torbin", "Espada Longa").count("18 po") == 1


def test_falha_deixa_o_preco_como_estava(forja, monkeypatch):
    monkeypatch.setattr(td.random, "randint", lambda a, b: 3)
    saida = td.haggle("Lyra", "Forja do Torbin")
    assert "FALHA" in saida
    assert _preco() == 20


def test_uma_pechincha_por_visita(forja):
    td.haggle("Lyra", "Forja do Torbin")
    segunda = td.haggle("Lyra", "Forja do Torbin")
    assert segunda.startswith("Nota:") and "nesta visita" in segunda


def test_sair_do_local_encerra_a_conversa(forja, monkeypatch):
    monkeypatch.setattr(td.random, "randint", lambda a, b: 15)
    td.haggle("Lyra", "Forja do Torbin")
    assert _preco() == 18
    memory.campaign["current_location"] = "Estrada do Norte"
    # Longe da loja o desconto não vale, e voltando dá para tentar de novo.
    assert _preco() == 20
    memory.campaign["current_location"] = "Oakhaven"
    assert not td.haggle("Lyra", "Forja do Torbin").startswith("Nota:")


def test_um_no_dado_ofende_o_lojista(forja, monkeypatch):
    monkeypatch.setattr(td.random, "randint", lambda a, b: 1)
    saida = td.haggle("Lyra", "Forja do Torbin")
    assert "ofende" in saida
    # 20 com os 5% da ofensa e mais 5% da atitude, que acabou de cair: o
    # lojista ofendido cobra pelas duas coisas.
    assert _preco() == 22
    assert tools.atitude_de(memory.campaign["characters"]["torbin"]) == -5


def test_a_atitude_do_dono_mexe_na_cd(forja, monkeypatch):
    monkeypatch.setattr(td.random, "randint", lambda a, b: 10)
    tools.adjust_attitude("Torbin", 80, "o grupo salvou a filha dele")
    saida = td.haggle("Lyra", "Forja do Torbin")
    # CD 13 - 4 degraus de atitude = 9; leal também desconta 20% antes.
    assert "vs CD 9" in saida and "leal" in saida
    assert "SUCESSO" in saida


def test_persuasao_da_classe_soma_a_proficiencia(forja, monkeypatch):
    """Barda: Persuasão é da classe, então a proficiência entra na rolagem."""
    monkeypatch.setattr(td.random, "randint", lambda a, b: 8)
    saida = td.haggle("Lyra", "Forja do Torbin")
    assert "+5 +2(prof)" in saida       # CAR +3 e proficiência +2

    memory.campaign["characters"]["lyra"]["sheet"]["classe"] = "guerreiro"
    memory.campaign["lojas"]["forja do torbin"].pop("pechincha", None)
    assert "+3" in td.haggle("Lyra", "Forja do Torbin")


def test_loja_de_outro_lugar_nao_e_pechinchada_por_engano(forja):
    td.open_shop("Boticário de Vharn", "Poção de Cura:50:2", location="Vharn")
    memory.campaign["current_location"] = "Oakhaven"
    saida = td.haggle("Lyra")
    assert "Forja do Torbin" in saida


def test_sem_loja_nenhuma_o_motor_recusa(campanha, povoar):
    povoar(criar_ficha("Lyra", grupo=True))
    assert td.haggle("Lyra", "Forja que não existe").startswith("Aviso:")
