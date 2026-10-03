"""
test_lojas_geradas.py

As lojas do lote 4. Antes, o mestre digitava o estoque inteiro de cabeça, uma
aldeia podia vender espada +3, o lojista tinha ouro infinito para comprar o
saque, a loja nunca se repunha, o que o grupo vendia sumia, item mágico não
tinha preço, e buy_item vendia de uma loja de outra cidade.
"""
import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha


@pytest.fixture
def vila(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True))
    memory.campaign["current_location"] = "Oakhaven"
    memory.campaign["relogio"] = {"dia": 1, "hora": 8}
    memory.campaign["characters"]["aria"]["sheet"].update({"ouro": 5000, "prata": 0, "cobre": 0})
    return memory.campaign["characters"]["aria"]


def _loja(nome):
    return td._lojas()[td._norm_txt(nome)]


def _nomes(nome):
    return [i["nome"] for i in _loja(nome)["estoque"]]


# ---------------------------------------------------------------------------
# Estoque pelo tipo e pelo porte
# ---------------------------------------------------------------------------

def test_forja_de_cidade_tem_armas_e_armaduras_do_srd(vila):
    td.open_shop("Forja do Torbin", kind="forja", size="cidade", location="Oakhaven")
    nomes = _nomes("Forja do Torbin")
    assert {"Espada Longa", "Cota de Malha", "Escudo", "Flecha"} <= set(nomes)
    assert "Armadura de Placas" not in nomes                     # placas só na metrópole


def test_vilarejo_vende_so_armas_simples_e_nada_acima_de_comum(vila):
    td.open_shop("Ferreiro da Aldeia", kind="ferreiro", size="aldeia", location="Oakhaven")
    nomes = _nomes("Ferreiro da Aldeia")
    assert "Adaga" in nomes and "Espada Longa" not in nomes
    for nome in nomes:
        raridade = td._raridade_do_item(nome)
        assert not raridade or raridade == "comum", nome


def test_metropole_tem_magia_ate_raro(vila):
    td.open_shop("Torre Arcana", kind="arcana", size="metropole", location="Oakhaven")
    raridades = {td._raridade_do_item(n) for n in _nomes("Torre Arcana")} - {""}
    assert raridades and raridades <= {"comum", "incomum", "raro"}


def test_boticario_tem_pocao_de_cura(vila):
    td.open_shop("Boticário", kind="boticario", size="vila", location="Oakhaven")
    assert "Poção de Cura" in _nomes("Boticário")


def test_o_mesmo_sorteio_para_a_mesma_loja(vila):
    td.open_shop("Torre", kind="arcana", size="cidade", location="Oakhaven")
    primeira = _nomes("Torre")
    assert td._gerar_estoque("arcana", "cidade", "torre:0") and \
        [l["nome"] for l in td._gerar_estoque("arcana", "cidade", "torre:0")] == primeira


def test_itens_a_mais_entram_junto(vila):
    td.open_shop("Forja", "Martelo do Velho Torbin:40:1|um martelo de família",
                 kind="forja", size="vila", location="Oakhaven")
    assert "Martelo do Velho Torbin" in _nomes("Forja") and "Espada Longa" in _nomes("Forja")


def test_tipo_e_porte_desconhecidos(vila):
    assert td.open_shop("X", kind="padaria").startswith("Erro:")
    assert td.open_shop("X", kind="forja", size="planeta").startswith("Erro:")


# ---------------------------------------------------------------------------
# Preço de item mágico
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nome, pc", [
    ("Varinha de Teia", 30000),                 # incomum: 300 po
    ("Anel de Proteção", 250000),               # raro: 2.500 po
    ("Poção de Cura Maior", 15000),             # incomum, consumível: metade
    ("Pergaminho de Bola de Fogo", 15000),      # 3º círculo: incomum, metade
    ("Pergaminho de Enfeitiçar Pessoa", 3750),  # 1º círculo: comum, metade
    ("Espada Longa +1", 31500),                 # incomum + a espada
    ("Poção de Cura", 5000),                    # o preço do Livro do Jogador
])
def test_preco_pela_raridade(nome, pc):
    assert td._preco_pc_do_srd(nome) == pc


def test_open_shop_poe_preco_no_item_magico(vila):
    saida = td.open_shop("Arcana", "Varinha de Teia", location="Oakhaven")
    assert "Varinha de Teia — 300 po" in saida


# ---------------------------------------------------------------------------
# Bolsa do lojista, recompra, reposição
# ---------------------------------------------------------------------------

def test_lojista_de_vilarejo_nao_compra_o_tesouro_do_dragao(vila):
    td.open_shop("Armazém", kind="armazem", size="vilarejo", location="Oakhaven")
    vila["inventario"] = [{"nome": "Rubi (500 po)", "qtd": 1, "descricao": ""}]
    saida = td.sell_item("Aria", "Armazém", "Rubi (500 po)")
    assert saida.startswith("Aviso:") and "50 po" in saida
    assert _qtd(vila, "Rubi (500 po)") == 1


def _qtd(ch, nome):
    return next((i["qtd"] for i in ch["inventario"] if i["nome"] == nome), 0)


def test_comprar_enche_e_vender_esvazia_a_bolsa(vila):
    td.open_shop("Armazém", kind="armazem", size="vila", location="Oakhaven")
    loja = _loja("Armazém")
    antes = loja["bolsa_pc"]
    td.buy_item("Aria", "Armazém", "Corda de Cânhamo (15 m)")
    assert loja["bolsa_pc"] == antes + 100
    vila["inventario"].append({"nome": "Adaga", "qtd": 1, "descricao": ""})
    td.sell_item("Aria", "Armazém", "Adaga")
    assert loja["bolsa_pc"] == antes + 100 - 100


def test_o_que_o_grupo_vende_fica_na_prateleira(vila):
    td.open_shop("Armazém", kind="armazem", size="vila", location="Oakhaven")
    vila["inventario"].append({"nome": "Adaga", "qtd": 1, "descricao": ""})
    td.sell_item("Aria", "Armazém", "Adaga")
    linha = next(i for i in _loja("Armazém")["estoque"] if i["nome"] == "Adaga")
    assert linha["preco_pc"] == 200 and linha["qtd"] == 1
    assert "comprou" in td.buy_item("Aria", "Armazém", "Adaga")


def test_esgotado_volta_na_semana(vila):
    td.open_shop("Forja", "Escudo:10:1", location="Oakhaven")
    td.buy_item("Aria", "Forja", "Escudo")
    assert "esgotou" in td.buy_item("Aria", "Forja", "Escudo")
    assert all(i["nome"] != "Escudo" for i in td.shop_snapshot("Forja", "Aria")["estoque"])
    td.advance_time(24 * 7)
    assert next(i for i in _loja("Forja")["estoque"] if i["nome"] == "Escudo")["qtd"] == 1


def test_a_loja_gerada_sorteia_de_novo_na_semana(vila):
    td.open_shop("Torre", kind="arcana", size="metropole", location="Oakhaven")
    loja = _loja("Torre")
    loja["bolsa_pc"] = 0
    td.advance_time(24 * 7)
    loja = _loja("Torre")                       # a reposição acontece na leitura
    assert loja["semana"] == 1 and loja["bolsa_pc"] == loja["bolsa_base_pc"]


# ---------------------------------------------------------------------------
# Só na loja onde o grupo está
# ---------------------------------------------------------------------------

def test_nao_compra_de_loja_de_outra_cidade(vila):
    td.open_shop("Forja de Cliviate", "Espada Longa", location="Cliviate")
    memory.campaign["current_location"] = "Oakhaven"
    saida = td.buy_item("Aria", "Forja de Cliviate", "Espada Longa")
    assert saida.startswith("Aviso:") and "Cliviate" in saida
    vila["inventario"].append({"nome": "Adaga", "qtd": 1, "descricao": ""})
    assert td.sell_item("Aria", "Forja de Cliviate", "Adaga").startswith("Aviso:")
    assert td.haggle("Aria", "Forja de Cliviate").startswith("Aviso:")


def test_compra_de_dentro_da_cidade(vila):
    td.open_shop("Forja de Cliviate", "Espada Longa", location="Cliviate")
    memory.campaign.setdefault("locations", {})["taverna do porco"] = {
        "name": "Taverna do Porco", "dentro_de": "Cliviate"}
    memory.campaign["current_location"] = "Taverna do Porco"
    assert "comprou" in td.buy_item("Aria", "Forja de Cliviate", "Espada Longa")


def test_tela_mostra_a_bolsa_do_lojista(vila):
    td.open_shop("Armazém", kind="armazem", size="vila", location="Oakhaven", owner="Bram")
    snap = td.shop_snapshot("Armazém", "Aria")
    assert snap["bolsa_loja_texto"] == "200 po" and snap["tipo"] == "armazem"
