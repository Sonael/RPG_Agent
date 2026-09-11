"""
test_tela_de_loja.py

A tela de loja é o SEGUNDO cliente do motor, depois da tela de combate. Essa
é a parte perigosa: todo caminho paralelo até uma regra é uma chance de os
dois discordarem, e isso já aconteceu duas vezes neste motor —

  • o braço da IA de NPC cobrava a recarga do chefe e o do mestre não;
  • a loja marcava item inventado e o verificador não enxergava.

Por isso `shop_action` é só despacho: ela CHAMA `buy_item`/`sell_item`, as
mesmas funções que o mestre usa. O combate precisou de um dispatcher próprio
(`combat_action`) porque a economia de turno não tem equivalente nas
ferramentas; comprar não tem nada disso.

O teste que mais importa aqui é
`test_a_tela_passa_pela_MESMA_funcao_do_mestre`: ele é o que fica vermelho no
dia em que alguém "otimizar" a rota reimplementando a compra.
"""
import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha


@pytest.fixture
def forja(campanha, povoar):
    povoar(criar_ficha("Helena", grupo=True, forca=12),
           criar_ficha("Stelar", grupo=True, forca=16))
    memory.campaign["current_location"] = "Oakhaven"
    h = memory.campaign["characters"]["helena"]
    h["sheet"].update({"ouro": 96, "prata": 8, "cobre": 0})
    h["inventario"] = [
        {"nome": "Espada Curta", "qtd": 2, "descricao": ""},
        {"nome": "Corda de Cânhamo", "qtd": 1, "descricao": "15 metros"},
    ]
    td.open_shop("Forja do Torbin",
                 "Espada Longa; Escudo:10:2; Cota de Malha; Meia Armadura",
                 location="Oakhaven")
    return h


# ---------------------------------------------------------------------------
# 1. O snapshot
# ---------------------------------------------------------------------------

def test_snapshot_traz_estoque_com_preco_e_peso(forja):
    snap = td.shop_snapshot()

    assert snap["tem_loja"] is True
    assert snap["loja"]["nome"] == "Forja do Torbin"

    cota = next(i for i in snap["estoque"] if i["nome"] == "Cota de Malha")
    assert cota["preco"] == 75
    assert cota["peso"] == pytest.approx(24.95, abs=0.05)


def test_snapshot_traz_a_bolsa_e_a_carga(forja):
    c = td.shop_snapshot()["comprador"]

    assert c["nome"] == "Helena"
    assert (c["ouro"], c["prata"]) == (96, 8)
    assert c["capacidade"] == pytest.approx(81.6, abs=0.1)
    assert c["meia_capacidade"] == pytest.approx(40.8, abs=0.1)
    assert c["estado_carga"] == "livre"


def test_a_tela_so_abre_sozinha_onde_a_loja_esta(forja):
    """
    Loja é estado que PERSISTE. Se o gatilho fosse "existe alguma loja", a
    tela apareceria em toda cena do resto da campanha por causa de uma
    ferraria visitada no capítulo 2.
    """
    assert td.shop_snapshot()["loja_aqui"] is True

    memory.campaign["current_location"] = "Luminas"
    assert td.shop_snapshot()["loja_aqui"] is False


def test_sem_loja_nenhuma_o_snapshot_nao_quebra(campanha, povoar):
    povoar(criar_ficha("Helena", grupo=True))
    snap = td.shop_snapshot()
    assert snap["tem_loja"] is False
    assert snap["estoque"] == [] and snap["inventario"] == []


def test_troca_de_comprador(forja):
    assert td.shop_snapshot(buyer="Stelar")["comprador"]["nome"] == "Stelar"
    assert td.shop_snapshot()["grupo"] == ["Helena", "Stelar"]


# ---------------------------------------------------------------------------
# 2. A lista de venda
# ---------------------------------------------------------------------------

def test_so_lista_o_que_a_loja_sabe_avaliar(forja):
    """
    Corda de Cânhamo não tem preço de tabela. Mostrá-la com um botão que
    sempre recusa seria pior que não mostrar.
    """
    nomes = [i["nome"] for i in td.shop_snapshot()["inventario"]]
    assert "Espada Curta" in nomes
    assert "Corda de Cânhamo" not in nomes


def test_a_loja_paga_metade_da_tabela(forja):
    linha = next(i for i in td.shop_snapshot()["inventario"]
                 if i["nome"] == "Espada Curta")
    assert linha["tabela"] == 10
    assert linha["ganho"] == 5
    assert linha["qtd"] == 2


# ---------------------------------------------------------------------------
# 3. Comprar e vender pela tela
# ---------------------------------------------------------------------------

def test_comprar_desconta_e_entrega(forja):
    res = td.shop_action("buy", shop="Forja do Torbin", char="Helena",
                         item="Escudo", quantity=1)

    assert res["ok"] is True
    assert forja["sheet"]["ouro"] == 86
    assert any(i["nome"] == "Escudo" for i in forja["inventario"])
    # O snapshot volta junto: a tela nunca precisa de uma segunda viagem.
    assert res["snapshot"]["comprador"]["ouro"] == 86


def test_compra_sem_ouro_e_recusada_e_nao_mexe_em_nada(forja):
    res = td.shop_action("buy", shop="Forja do Torbin", char="Helena",
                         item="Meia Armadura", quantity=1)

    assert res["ok"] is False
    assert forja["sheet"]["ouro"] == 96
    assert not any(i["nome"] == "Meia Armadura" for i in forja["inventario"])
    estoque = {i["nome"]: i["qtd"] for i in res["snapshot"]["estoque"]}
    assert "Meia Armadura" in estoque


def test_vender_paga_e_tira_do_inventario(forja):
    res = td.shop_action("sell", shop="Forja do Torbin", char="Helena",
                         item="Espada Curta", quantity=1)

    assert res["ok"] is True
    assert forja["sheet"]["ouro"] == 101          # 96 + metade de 10
    assert next(i for i in forja["inventario"]
                if i["nome"] == "Espada Curta")["qtd"] == 1


def test_acao_desconhecida_nao_faz_nada(forja):
    res = td.shop_action("roubar", shop="Forja do Torbin", char="Helena",
                         item="Escudo")
    assert res["ok"] is False
    assert forja["sheet"]["ouro"] == 96


def test_a_carga_do_snapshot_acompanha_a_compra(forja):
    antes = td.shop_snapshot()["comprador"]["carga"]
    res = td.shop_action("buy", shop="Forja do Torbin", char="Helena",
                         item="Cota de Malha", quantity=1)
    # 96 po não pagam 75? pagam. E 25 kg têm que aparecer na barra.
    assert res["ok"] is True
    assert res["snapshot"]["comprador"]["carga"] > antes + 20


# ---------------------------------------------------------------------------
# 4. A costura: a tela NÃO pode ter regra própria
# ---------------------------------------------------------------------------

def test_a_tela_passa_pela_MESMA_funcao_do_mestre(forja, monkeypatch):
    """
    Este é o teste que importa. `shop_action` não pode ter uma segunda
    implementação de compra: se alguém reescrever a cobrança da bolsa aqui
    "para a tela ficar mais rápida", a regra passa a existir em dois lugares
    e um dos dois vai ficar para trás — foi exatamente assim que a recarga
    do chefe funcionou na IA de NPC e não no caminho do mestre.
    """
    chamadas = []
    real = td.buy_item
    monkeypatch.setattr(td, "buy_item",
                        lambda *a, **k: (chamadas.append((a, k)), real(*a, **k))[1])

    td.shop_action("buy", shop="Forja do Torbin", char="Helena",
                   item="Escudo", quantity=2)

    assert chamadas, "shop_action não passou por buy_item"
    assert chamadas[0][0] == ("Helena", "Forja do Torbin", "Escudo", 2)


def test_a_venda_tambem_passa_por_sell_item(forja, monkeypatch):
    chamadas = []
    real = td.sell_item
    monkeypatch.setattr(td, "sell_item",
                        lambda *a, **k: (chamadas.append(a), real(*a, **k))[1])

    td.shop_action("sell", shop="Forja do Torbin", char="Helena",
                   item="Espada Curta", quantity=1)

    assert chamadas and chamadas[0] == ("Helena", "Forja do Torbin",
                                        "Espada Curta", 1)


def test_item_inventado_comprado_pela_tela_continua_sendo_cobrado(forja):
    """
    A tela não pode ser um terceiro buraco na conferência de item inventado —
    a loja já foi um. Como ela passa por buy_item, a marca é gravada igual.
    """
    td.open_shop("Forja do Torbin", "Lâmina Rúnica de Vhar:20")
    td.shop_action("buy", shop="Forja do Torbin", char="Helena",
                   item="Lâmina Rúnica de Vhar", quantity=1)

    it = next(i for i in forja["inventario"]
              if i["nome"] == "Lâmina Rúnica de Vhar")
    assert it["custom"] is True
    assert it["efeito_desconhecido"] is True


# ---------------------------------------------------------------------------
# 5. As rotas existem e são passagem
# ---------------------------------------------------------------------------

def test_as_rotas_da_loja_estao_registradas():
    import server
    rotas = {r.rule for r in server.app.url_map.iter_rules()}
    assert "/api/shop/state" in rotas
    assert "/api/shop/action" in rotas
