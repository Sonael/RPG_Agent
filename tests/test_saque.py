"""
test_saque.py

O saque ia direto para a ficha de quem o mestre escolhesse (add_item e
modify_currency). Agora vai para o chão com offer_loot, e o jogador divide na
tela de saque vendo a carga de cada um.
"""
import pytest

from rpg import memory, saque, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


@pytest.fixture
def grupo(campanha, povoar, monkeypatch):
    # Sem rede: nada de SRD na conferência de item.
    monkeypatch.setattr(td, "_search_open5e_item", lambda nome: None)
    alden = criar_ficha("Alden", grupo=True, forca=10)       # capacidade 68 kg
    alden["inventario"] = [{"nome": "Adaga", "qtd": 1, "descricao": ""}]
    # Lyra de FOR 4: metade da capacidade em 13,6 kg, a cota (25 kg) pesa.
    povoar(alden, criar_ficha("Lyra", grupo=True, forca=4),
           criar_ficha("Bran", grupo=True), criar_ficha("Goblin"))
    memory.campaign.pop("saque_proposto", None)
    return memory.campaign


def _snap():
    return saque.loot_snapshot()


def _item(nome):
    return next(i for i in _snap()["saque"]["itens"] if i["nome"] == nome)


def _membro(nome):
    return next(p for p in _snap()["grupo"] if p["nome"] == nome)


def _inv(quem):
    return {i["nome"]: i["qtd"] for i in memory.campaign["characters"][quem]["inventario"]}


def test_offer_loot_poe_no_chao_sem_tocar_nas_fichas(grupo):
    saida = saque.offer_loot("Cota de Malha; Poção de Cura:3", gold=10, silver=5,
                             source="os bandidos da estrada")
    assert "TELA DE SAQUE" in saida and "Não chame add_item" in saida
    s = _snap()["saque"]
    assert s["origem"] == "os bandidos da estrada"
    assert [(i["nome"], i["qtd"], i["sobra"]) for i in s["itens"]] == [
        ("Cota de Malha", 1, 1), ("Poção de Cura", 3, 3)]
    assert s["moedas"] == {"ouro": 10, "prata": 5, "cobre": 0}
    assert _item("Cota de Malha")["peso"] > 15
    assert _inv("alden") == {"Adaga": 1}, "o saque foi para a ficha antes da divisão"


def test_chamar_de_novo_acrescenta(grupo):
    saque.offer_loot("Poção de Cura", gold=5)
    saque.offer_loot("Poção de Cura:2; Adaga", gold=5)
    assert _item("Poção de Cura")["qtd"] == 3
    assert _snap()["saque"]["moedas"]["ouro"] == 10


def test_recusas(grupo):
    assert saque.offer_loot("").startswith("Aviso:")
    iniciar_combate(["Alden", "Goblin"])
    assert saque.offer_loot("Adaga").startswith("Erro:")


def test_dar_devolver_e_carga_prevista(grupo):
    saque.offer_loot("Cota de Malha; Poção de Cura:3")
    cota = _item("Cota de Malha")
    r = saque.loot_action("dar", item=str(cota["id"]), char="Lyra")
    assert r["ok"] is True
    lyra = _membro("Lyra")
    assert lyra["carga"]["kg_previsto"] > lyra["carga"]["kg"]
    assert lyra["carga"]["estado_previsto"] in ("sobrecarregado", "imovel")
    assert lyra["recebe"] == [{"id": cota["id"], "nome": "Cota de Malha", "qtd": 1}]
    assert _item("Cota de Malha")["sobra"] == 0

    r = saque.loot_action("dar", item="Cota de Malha", char="Alden")
    assert r["ok"] is False, "deu uma cota que já não estava no chão"

    assert saque.loot_action("devolver", item="Cota de Malha", char="Lyra")["ok"] is True
    assert _item("Cota de Malha")["sobra"] == 1 and _membro("Lyra")["recebe"] == []


def test_unidades_se_dividem(grupo):
    saque.offer_loot("Poção de Cura:3")
    saque.loot_action("dar", item="Poção de Cura", char="Alden")
    saque.loot_action("dar", item="Poção de Cura", char="Alden")
    saque.loot_action("dar", item="Poção de Cura", char="Bran")
    assert _item("Poção de Cura")["divisao"] == {"Alden": 2, "Bran": 1}


def test_morto_nao_leva_e_nome_invalido(grupo):
    grupo["characters"]["bran"]["status"] = "morto"
    saque.offer_loot("Adaga")
    assert saque.loot_action("dar", item="Adaga", char="Bran")["ok"] is False
    assert saque.loot_action("dar", item="Adaga", char="Goblin")["ok"] is False


def test_moedas_por_igual_com_resto_e_tudo_para_um(grupo):
    saque.offer_loot("", gold=10, copper=2)
    div = {p["nome"]: p["moedas_recebe"] for p in _snap()["grupo"]}
    assert [div[n]["ouro"] for n in ("Alden", "Lyra", "Bran")] == [4, 3, 3]
    assert [div[n]["cobre"] for n in ("Alden", "Lyra", "Bran")] == [1, 1, 0]
    saque.loot_action("moedas", coins_to="Lyra")
    div = {p["nome"]: p["moedas_recebe"] for p in _snap()["grupo"]}
    assert div["Lyra"]["ouro"] == 10 and div["Alden"]["ouro"] == 0


def test_concluir_poe_nas_fichas_e_deixa_o_resto(grupo):
    ouro_antes = grupo["characters"]["alden"]["sheet"]["ouro"]
    saque.offer_loot("Adaga; Escudo; Poção de Cura:2", gold=3)
    saque.loot_action("dar", item="Adaga", char="Alden")
    saque.loot_action("dar", item="Poção de Cura", char="Lyra")
    saque.loot_action("moedas", coins_to="Alden")
    r = saque.loot_action("concluir")
    assert r["ok"] is True
    assert _inv("alden") == {"Adaga": 2}, "não empilhou com a adaga que ele já tinha"
    assert _inv("lyra") == {"Poção de Cura": 1}
    assert grupo["characters"]["alden"]["sheet"]["ouro"] == ouro_antes + 3
    assert "Alden: Adaga, 3 po" in r["message"]
    assert "Ficaram para trás: Escudo, Poção de Cura" in r["message"]
    assert _snap()["tem_saque"] is False
    peso = next(i for i in grupo["characters"]["lyra"]["inventario"] if i["nome"] == "Poção de Cura")
    assert "id" not in peso and "divisao" not in peso


def test_deixar_tudo(grupo):
    saque.offer_loot("Adaga", gold=5)
    r = saque.loot_action("deixar")
    assert r["ok"] is True and _snap()["tem_saque"] is False
    assert _inv("alden") == {"Adaga": 1}


def test_concluir_em_combate_e_recusado(grupo):
    saque.offer_loot("Adaga")
    iniciar_combate(["Alden", "Goblin"])
    assert saque.loot_action("concluir")["ok"] is False
    assert _snap()["tem_saque"] is True


def test_item_inventado_e_cobrado_ao_por_no_chao(grupo):
    saida = saque.offer_loot("Anel do Poder Supremo:1:+3 em todos os ataques e 2d6 de dano extra")
    assert "NÃO EXISTE no SRD" in saida
    item = grupo["saque_proposto"]["itens"][0]
    assert item["custom"] is True and item.get("efeito_mecanico") is True

    import server
    assert server._check_itens_inventados({"offer_loot"}), "o verificador não olhou o saque"
    saida = td.justify_custom_item("Alden", "Anel do Poder Supremo", "é uma farsa, o bônus é mentira")
    assert "(no saque)" in saida
    assert not server._check_itens_inventados({"offer_loot"})


def test_ferramenta_registrada_e_resumo_do_combate(grupo):
    assert "offer_loot" in {f.__name__ for f in td.DND_TOOLS}
    grupo["combat_state"]["result"] = {"outcome": "vitoria", "sobreviventes": [], "caidos": []}
    assert "offer_loot" in td.combat_recap_payload()


def test_rotas(grupo):
    import server
    regras = {r.rule for r in server.app.url_map.iter_rules()}
    assert {"/api/loot/state", "/api/loot/action"} <= regras
    saque.offer_loot("Adaga")
    with server.app.test_request_context("/api/loot/action", method="POST",
                                         json={"action": "dar", "item": "Adaga", "char": "Lyra"}):
        corpo = server.loot_action_route.__wrapped__().get_json()
    assert corpo["ok"] is True
