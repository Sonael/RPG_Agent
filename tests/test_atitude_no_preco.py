"""
test_atitude_no_preco.py

A atitude do lojista vale no balcão, e a ficha dele mostra o que ele vende.

A atitude já valia 1 de CD a cada 20 pontos nos testes sociais, e nada no
preço: o ferreiro que devia a vida ao grupo cobrava igual ao que tinha sido
roubado por ele. E a ficha do personagem dizia só "Trabalha em X" — para
saber o que havia à venda o jogador tinha de ir até a tela da loja, que só
abre quando o grupo está no local dela.

Regra: mesma escala do teste social — 5% a cada 20 pontos de atitude, teto de
25% para os dois lados. Desconto na compra, ágio na venda.
"""
import pytest

from rpg import memory, personagens, tools, tools_dnd as td

from conftest import criar_ficha


@pytest.fixture
def forja(campanha, povoar):
    torbin = {"name": "Torbin", "sheet": None, "description": "Ferreiro corpulento.",
              "status": "vivo", "local": "Forja de Cliviate"}
    memory.campaign["characters"]["torbin"] = torbin
    povoar(criar_ficha("Thorn", grupo=True, forca=16))
    memory.campaign["characters"]["thorn"]["sheet"]["ouro"] = 500
    memory.campaign["current_location"] = "Forja de Cliviate"
    td.open_shop("Forja do Torbin", "Espada Longa:20:3; Escudo:10:2",
                 location="Forja de Cliviate", owner="Torbin")
    return torbin


def _loja():
    return memory.campaign["lojas"]["forja do torbin"]


def _preco_na_tela(nome="Espada Longa"):
    snap = td.shop_snapshot("Forja do Torbin", "Thorn")
    return next(i for i in snap["estoque"] if i["nome"] == nome)


# ---------------------------------------------------------------------------
# O preço
# ---------------------------------------------------------------------------

def test_sem_atitude_o_preco_e_o_da_tabela(forja):
    assert _preco_na_tela()["preco"] == 20
    assert td.shop_snapshot("Forja do Torbin", "Thorn")["atitude"] is None


def test_lojista_leal_cobra_menos(forja):
    tools.adjust_attitude("Torbin", 80, "o grupo salvou a filha dele")
    item = _preco_na_tela()
    # 80 pontos = 4 degraus = 20% de desconto.
    assert (item["preco"], item["tabela"]) == (16, 20)
    saida = td.buy_item("Thorn", "Forja do Torbin", "Espada Longa")
    assert "16 po" in saida and "-20%" in saida
    assert memory.campaign["characters"]["thorn"]["sheet"]["ouro"] == 484


def test_lojista_hostil_cobra_mais(forja):
    tools.adjust_attitude("Torbin", -60, "o grupo roubou a forja")
    assert _preco_na_tela()["preco"] == 23        # +15%
    td.buy_item("Thorn", "Forja do Torbin", "Espada Longa")
    assert memory.campaign["characters"]["thorn"]["sheet"]["ouro"] == 477


def test_o_desconto_tem_teto(forja):
    tools.adjust_attitude("Torbin", 100, "parceiro de vida")
    # 100 pontos seriam 5 degraus: o teto é justamente 5, ou seja, 25%.
    assert _preco_na_tela()["preco"] == 15
    snap = td.shop_snapshot("Forja do Torbin", "Thorn")
    assert snap["atitude"]["pct"] == -25


def test_o_teto_e_o_mesmo_do_teste_social(forja):
    """
    A escala vai de -100 a +100, então 5 degraus é o máximo que uma campanha
    alcança. O teto no helper é a mesma guarda que o social_check tem, para
    uma ficha editada à mão não virar 90% de desconto.
    """
    assert td._passos_de_atitude(400) == 5
    assert td._passos_de_atitude(-400) == -5


def test_atitude_tambem_muda_o_que_a_loja_paga(forja):
    td.add_item("Thorn", "Espada Longa", 1)
    tools.adjust_attitude("Torbin", 80, "o grupo salvou a filha dele")
    # Metade da tabela (10) com +20% de ágio.
    saida = td.sell_item("Thorn", "Forja do Torbin", "Espada Longa")
    assert "12 po" in saida and "+20%" in saida


def test_loja_sem_dono_nao_muda_de_preco(forja):
    _loja()["dono"] = ""
    tools.adjust_attitude("Torbin", 100, "parceiro de vida")
    assert _preco_na_tela()["preco"] == 20


def test_dono_que_nao_existe_mais_nao_quebra(forja):
    _loja()["dono"] = "Fantasma de Ninguém"
    assert _preco_na_tela()["preco"] == 20
    assert td.buy_item("Thorn", "Forja do Torbin", "Escudo").startswith("Thorn comprou")


def test_open_shop_de_novo_mantem_o_dono(forja):
    td.open_shop("Forja do Torbin", "Adaga:2:5", location="Forja de Cliviate")
    assert _loja()["dono"] == "Torbin"


# ---------------------------------------------------------------------------
# A ficha do personagem
# ---------------------------------------------------------------------------

def test_ficha_do_lojista_traz_o_estoque(forja):
    f = personagens.ficha("Torbin")
    assert f["loja"]["nome"] == "Forja do Torbin" and f["loja"]["dono"] is True
    assert [i["nome"] for i in f["loja"]["estoque"]] == ["Espada Longa", "Escudo"]
    assert f["loja"]["estoque"][0]["preco"] == 20


def test_estoque_da_ficha_usa_o_preco_da_relacao(forja):
    tools.adjust_attitude("Torbin", 80, "o grupo salvou a filha dele")
    item = personagens.ficha("Torbin")["loja"]["estoque"][0]
    assert (item["preco"], item["tabela"]) == (16, 20)


def test_ficha_mostra_o_que_a_atitude_faz(forja):
    tools.adjust_attitude("Torbin", 80, "o grupo salvou a filha dele")
    efeitos = personagens.ficha("Torbin")["atitude"]["efeitos"]
    assert efeitos == ["-4 na CD de testes sociais com ele",
                       "-20% no preço da loja dele"]


def test_atitude_neutra_nao_promete_efeito(forja):
    assert personagens.ficha("Torbin")["atitude"]["efeitos"] == []


def test_quem_nao_tem_loja_continua_sem_loja(forja, povoar):
    memory.campaign["characters"]["ivo"] = {
        "name": "Pescador Ivo", "sheet": None, "status": "vivo", "local": "Cliviate"}
    assert personagens.ficha("Pescador Ivo")["loja"] is None
