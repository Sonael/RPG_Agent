"""
test_loja_resumo_da_visita.py

O grupo entrou no boticário, não comprou nada e encerrou. O mestre narrou:
"Alden e Lyra concluem suas aquisições no balcão e guardam cuidadosamente os
novos suprimentos em suas mochilas."

A tela mandava sempre o mesmo texto ao encerrar — "O grupo terminou de
negociar em X. Narre a saída da loja" — sem dizer se houve negócio. Agora cada
compra e venda fica registrada com um número de sequência, a tela guarda o
número de quando abriu, e o motor resume só o que veio depois dele.
"""
import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha


@pytest.fixture
def boticario(campanha, povoar):
    povoar(criar_ficha("Alden", grupo=True), criar_ficha("Lyra", grupo=True))
    memory.campaign["current_location"] = "Cliviate"
    for chave in ("alden", "lyra"):
        memory.campaign["characters"][chave]["sheet"].update({"ouro": 200, "prata": 0, "cobre": 0})
    memory.campaign["characters"]["lyra"]["inventario"] = [
        {"nome": "Adaga", "qtd": 1, "descricao": ""}]
    td.open_shop("Boticário da Mira", "Poção de Cura:50:5; Adaga", location="Cliviate")
    return memory.campaign


def test_sem_negocio_o_resumo_diz_que_nada_foi_comprado(boticario):
    desde = td.shop_snapshot()["negocios_seq"]

    texto = td.shop_recap_payload(desde, "Boticário da Mira")

    assert "SEM comprar nem vender nada" in texto
    assert "Negócios feitos" not in texto
    assert "Boticário da Mira" in texto


def test_compra_pela_tela_entra_no_resumo(boticario):
    desde = td.shop_snapshot()["negocios_seq"]
    td.shop_action("buy", shop="Boticário da Mira", char="Alden", item="Poção de Cura", quantity=2)

    texto = td.shop_recap_payload(desde, "Boticário da Mira")

    assert "Negócios feitos: Alden comprou 2x Poção de Cura." in texto
    assert "SEM comprar" not in texto
    assert "não chame buy_item" in texto


def test_venda_entra_no_resumo(boticario):
    desde = td.shop_snapshot()["negocios_seq"]
    td.shop_action("sell", shop="Boticário da Mira", char="Lyra", item="Adaga")
    assert "Lyra vendeu 1x Adaga" in td.shop_recap_payload(desde)


def test_compra_recusada_nao_conta(boticario):
    memory.campaign["characters"]["alden"]["sheet"]["ouro"] = 0
    desde = td.shop_snapshot()["negocios_seq"]
    r = td.shop_action("buy", shop="Boticário da Mira", char="Alden", item="Poção de Cura")
    assert r["ok"] is False
    assert "SEM comprar" in td.shop_recap_payload(desde)


def test_visita_anterior_nao_entra(boticario):
    td.buy_item("Alden", "Boticário da Mira", "Poção de Cura")      # visita de ontem
    desde = td.shop_snapshot()["negocios_seq"]                       # a tela abre hoje

    assert "SEM comprar" in td.shop_recap_payload(desde)


def test_compra_feita_pelo_mestre_tambem_conta(boticario):
    desde = td.shop_snapshot()["negocios_seq"]
    td.buy_item("Lyra", "Boticário da Mira", "Poção de Cura")
    assert "Lyra comprou 1x Poção de Cura" in td.shop_recap_payload(desde)


def test_negocios_em_duas_lojas_dizem_onde(boticario):
    td.open_shop("Forja de Cliviate", "Escudo", location="Cliviate")
    desde = td.shop_snapshot()["negocios_seq"]
    td.buy_item("Alden", "Boticário da Mira", "Poção de Cura")
    td.buy_item("Alden", "Forja de Cliviate", "Escudo")

    texto = td.shop_recap_payload(desde)

    assert "Alden comprou 1x Poção de Cura em Boticário da Mira" in texto
    assert "Alden comprou 1x Escudo em Forja de Cliviate" in texto


def test_rota_do_resumo_registrada():
    import server
    assert "/api/shop/recap" in {r.rule for r in server.app.url_map.iter_rules()}
