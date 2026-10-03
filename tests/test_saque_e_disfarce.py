"""
test_saque_e_disfarce.py

O lote 5: saque sugerido pelo motor, item mágico disfarçado até identificar,
"Dar a..." entre o grupo, e platina e electro. Antes o mestre inventava o
saque do zero (o bandido de besta caía sem deixar a besta), o item mágico
chegava com o nome que dizia tudo, passar a poção para o colega pedia ao
mestre remover e adicionar, e o tesouro do mago virava ouro na conta.
"""
import json

import pytest

from rpg import memory, saque, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


@pytest.fixture
def mesa(campanha, povoar):
    bandido = criar_ficha("Bandido", vida=0, tipo="humanoid", cr="1/8",
                          ataques=[{"nome": "Scimitar"}, {"nome": "Light Crossbow"}],
                          armadura_desc="leather armor")
    bandido["status"] = "morto"
    bandido["inventario"] = [{"nome": "Mapa rasgado", "qtd": 1, "descricao": ""}]
    lobo = criar_ficha("Lobo", vida=0, tipo="beast", cr="1/4", ataques=[{"nome": "Bite"}], arma=None)
    lobo["status"] = "morto"
    povoar(criar_ficha("Aria", grupo=True), criar_ficha("Bram", grupo=True), bandido, lobo)
    return memory.campaign


def _ch(nome):
    return memory.campaign["characters"][nome]


def _item(quem, nome):
    return next((i for i in _ch(quem)["inventario"] if i["nome"] == nome), None)


# ---------------------------------------------------------------------------
# Saque sugerido
# ---------------------------------------------------------------------------

def test_o_bandido_deixa_o_que_carregava(mesa):
    s = saque.sugerir_saque(["Bandido"])
    itens = dict(s["itens"])
    assert {"Cimitarra", "Besta Leve", "Armadura de Couro", "Mapa rasgado"} <= set(itens)
    assert itens["Virote"] >= 1                                 # a munição da besta
    assert s["moedas"] and "offer_loot(" in s["chamada"]


def test_o_lobo_nao_carrega_moeda_nem_arma(mesa):
    assert saque.sugerir_saque(["Lobo"]) == {"itens": [], "moedas": {}, "chamada": 'offer_loot("")'}


def test_o_resumo_da_vitoria_traz_a_sugestao(mesa):
    memory.campaign["combat_state"]["result"] = {
        "outcome": "vitoria", "sobreviventes": [],
        "caidos": [{"name": "Bandido", "is_party": False, "status": "morto", "hp": 0, "hp_max": 11},
                   {"name": "Lobo", "is_party": False, "status": "morto", "hp": 0, "hp_max": 11}],
        "poupados": []}
    texto = td.combat_recap_payload()
    assert "SAQUE SUGERIDO PELO MOTOR" in texto and "Cimitarra" in texto


def test_suggest_loot_pega_os_caidos(mesa):
    texto = td.suggest_loot()
    assert "Bandido" in texto and "Besta Leve" in texto and "Nada foi entregue" in texto


def test_moedas_crescem_com_o_nd(mesa, monkeypatch):
    monkeypatch.setattr(td.random, "randint", lambda a, b: b)
    _ch("bandido")["sheet"]["cr"] = "12"
    m = saque.sugerir_saque(["Bandido"])["moedas"]
    assert m["ouro"] == 1200 and m["platina"] == 60


# ---------------------------------------------------------------------------
# Disfarce
# ---------------------------------------------------------------------------

def test_o_grupo_so_ve_o_que_ve(mesa):
    saida = td.add_item("Aria", "Anel de prata com runas = Anel de Proteção")
    assert "disfarçado" in saida and "Proteção" not in saida
    item = _item("aria", "Anel de prata com runas")
    assert item["nome_verdadeiro"] == "Anel de Proteção" and td._a_identificar(item)
    snap = td.inventory_snapshot("Aria")
    assert "Proteção" not in json.dumps(snap, ensure_ascii=False)


def test_identificar_revela(mesa):
    td.add_item("Aria", "Anel de prata com runas = Anel de Proteção")
    saida = td.identify_item("Aria", "Anel de prata com runas")
    assert "Anel de prata com runas é, na verdade, Anel de Proteção" in saida
    assert _item("aria", "Anel de Proteção") and not _item("aria", "Anel de prata com runas")


def test_sintonizar_revela_e_acerta_o_slot(mesa):
    aria = _ch("aria")
    td._recalculate_ca(aria)
    ca = aria["sheet"]["ca"]
    td.add_item("Aria", "Anel de prata com runas = Anel de Proteção")
    td.equip_item("Aria", "Anel de prata com runas", "anel_1")
    saida = td.attune_item("Aria", "Anel de prata com runas")
    assert "é, na verdade, Anel de Proteção" in saida
    assert aria["sheet"]["equipamentos"]["anel_1"] == "Anel de Proteção"
    assert aria["sheet"]["sintonizados"] == ["Anel de Proteção"]
    assert aria["sheet"]["ca"] == ca + 1


def test_pocao_disfarcada_se_prova_com_um_gole(mesa):
    td.add_item("Aria", "Frasco de vidro azul = Poção de Invisibilidade")
    r = td.inventory_action("identificar", char="Aria", item="Frasco de vidro azul")
    assert r["resultado"]["como"] == "Aria provou um gole."
    assert r["resultado"]["revelado_de"] == "Frasco de vidro azul"
    assert r["resultado"]["item"] == "Poção de Invisibilidade"


def test_disfarce_fora_do_srd(mesa):
    td.add_item("Aria", "Pedra lisa = Pedra do Vhar", description="aquece no frio")
    assert td._a_identificar(_item("aria", "Pedra lisa"))
    saida = td.identify_item("Aria", "Pedra lisa")
    assert "na verdade, Pedra do Vhar" in saida and _item("aria", "Pedra do Vhar")["custom"] is True


def test_o_mesmo_disfarce_empilha(mesa):
    td.add_item("Aria", "Frasco azul = Poção de Invisibilidade")
    td.add_item("Aria", "Frasco azul = Poção de Invisibilidade")
    assert _item("aria", "Frasco azul")["qtd"] == 2
    td.offer_loot("Adaga curva = Adaga Venenosa")
    td.offer_loot("Adaga curva = Adaga Venenosa")
    pilhas = memory.campaign["saque_proposto"]["itens"]
    assert len(pilhas) == 1 and pilhas[0]["qtd"] == 2


def test_disfarce_pelo_saque(mesa):
    td.offer_loot("Adaga curva = Adaga Venenosa")
    pilha = memory.campaign["saque_proposto"]["itens"][0]
    assert pilha["nome"] == "Adaga curva"
    vis = saque.loot_snapshot()
    assert "Venenosa" not in json.dumps(vis, ensure_ascii=False)
    saque.loot_action("dar", item=str(pilha["id"]), char="Aria")
    saque.loot_action("concluir")
    assert _item("aria", "Adaga curva")["nome_verdadeiro"] == "Adaga Venenosa"


# ---------------------------------------------------------------------------
# Dar a…
# ---------------------------------------------------------------------------

def test_dar_a_pocao(mesa):
    td.add_item("Aria", "Poção de Cura", 2)
    saida = td.give_item("Aria", "Bram", "Poção de Cura")
    assert "deu 1x Poção de Cura a Bram" in saida
    assert _item("aria", "Poção de Cura")["qtd"] == 1 and _item("bram", "Poção de Cura")["qtd"] == 1


def test_dar_o_que_esta_equipado_tira_do_corpo(mesa):
    td.add_item("Aria", "Escudo")
    td.equip_item("Aria", "Escudo", "escudo")
    td.give_item("Aria", "Bram", "Escudo")
    assert _ch("aria")["sheet"]["equipamentos"]["escudo"] is None


def test_a_varinha_vai_com_as_cargas(mesa):
    _ch("aria")["inventario"].append({"nome": "Varinha de Teia", "qtd": 1, "descricao": "", "cargas": 3})
    td.give_item("Aria", "Bram", "Varinha de Teia")
    assert _item("bram", "Varinha de Teia")["cargas"] == 3


def test_dar_recusa_npc_luta_e_a_si_mesmo(mesa):
    td.add_item("Aria", "Tocha", 2)
    assert td.give_item("Aria", "Aria", "Tocha").startswith("Aviso:")
    assert td.give_item("Aria", "Bandido", "Tocha").startswith(("Aviso:", "Erro:"))
    iniciar_combate(["Aria", "Bram"])
    assert td.give_item("Aria", "Bram", "Tocha").startswith("Aviso:")


def test_mochila_oferece_e_da(mesa):
    td.add_item("Aria", "Corda de Cânhamo (15 m)")
    item = next(i for i in td.inventory_snapshot("Aria")["personagem"]["itens"]
                if i["nome"] == "Corda de Cânhamo (15 m)")
    assert item["dar_a"] == ["Bram"]
    r = td.inventory_action("dar", char="Aria", item="Corda de Cânhamo (15 m)", alvo="Bram")
    assert r["ok"] is True and _item("bram", "Corda de Cânhamo (15 m)")


# ---------------------------------------------------------------------------
# Platina e electro
# ---------------------------------------------------------------------------

def test_saque_com_platina_e_electro(mesa):
    td.offer_loot("", gold=10, platinum=2, electrum=3)
    saque.loot_action("moedas", coins_to="Aria")
    saque.loot_action("concluir")
    s = _ch("aria")["sheet"]
    assert (s["platina"], s["electro"], s["ouro"]) == (2, 3, 10)


def test_modify_currency_aceita_platina(mesa):
    td.modify_currency("Aria", "platina", 5)
    assert _ch("aria")["sheet"]["platina"] == 5
    assert td.modify_currency("Aria", "pe", 2).startswith("Aria recebeu")


def test_pagar_quebra_a_platina_so_quando_falta(mesa):
    s = _ch("aria")["sheet"]
    s.update({"ouro": 10, "prata": 0, "cobre": 0, "platina": 1, "electro": 0})
    assert td._pagar(s, 500)
    assert (s["platina"], s["ouro"]) == (1, 5)              # a platina ficou
    assert td._pagar(s, 1000)
    assert (s["platina"], s["ouro"]) == (0, 5)              # agora quebrou: 15 po - 10 po


def test_a_mochila_mostra_a_platina(mesa):
    _ch("aria")["sheet"]["platina"] = 3
    assert td.inventory_snapshot("Aria")["personagem"]["moedas"]["platina"] == 3
