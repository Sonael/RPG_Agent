"""
test_mochila.py

A Mochila junta equipamento, carga e identificação numa tela. Construí-la
passou por equip_item, remove_item e sell_item, e os três tinham defeitos que
nenhum teste via. Medidos no commit anterior, com uma guerreira de DES 10:

    vestiu Cota de Malha                   CA 16
    vendeu a Cota de Malha na loja         CA 16, inventário vazio,
                                           slot armadura: "Cota de Malha"
    equip_item("Corda de Cânhamo") sem slot
                                           foi para [armadura], tirou a cota,
                                           CA 10
    1 Adaga em arma_principal e arma_secundaria
                                           aceitou: um item, dois ataques
    equip_item de item que não existe      "'Espada Inexistente' não está..."
                                           sem prefixo: a tela leria sucesso

Depois das correções, a tela só despacha para essas mesmas ferramentas.
"""
import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha


@pytest.fixture
def aria(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True, destreza=10, forca=14))
    ch = memory.campaign["characters"]["aria"]
    ch["inventario"] = []
    ch["sheet"]["equipamentos"] = {s: None for s in td._SLOTS}
    td._recalculate_ca(ch)
    return ch


@pytest.fixture
def forja(campanha):
    memory.campaign["lojas"] = {"forja": {"nome": "Forja", "local": "", "estoque": []}}


def _vestir_cota(aria):
    td.add_item("Aria", "Cota de Malha", 1)
    td.equip_item("Aria", "Cota de Malha", "armadura")
    assert aria["sheet"]["ca"] == 16


# ---------------------------------------------------------------------------
# 1. O que sai da mochila sai do corpo
# ---------------------------------------------------------------------------

def test_vender_a_armadura_vestida_tira_do_corpo(aria, forja):
    """O caso medido: CA 16 de uma armadura que já era da loja."""
    _vestir_cota(aria)
    saida = td.sell_item("Aria", "Forja", "Cota de Malha", 1)
    assert aria["sheet"]["equipamentos"]["armadura"] is None
    assert aria["sheet"]["ca"] == 10
    assert "CA 16 → 10" in saida


def test_remover_a_armadura_vestida_tira_do_corpo(aria):
    _vestir_cota(aria)
    td.remove_item("Aria", "Cota de Malha", 1)
    assert aria["sheet"]["equipamentos"]["armadura"] is None
    assert aria["sheet"]["ca"] == 10


def test_remover_uma_de_duas_adagas_solta_a_mao_secundaria(aria):
    td.add_item("Aria", "Adaga", 2)
    td.equip_item("Aria", "Adaga", "arma_principal")
    td.equip_item("Aria", "Adaga", "arma_secundaria")
    td.remove_item("Aria", "Adaga", 1)
    eq = aria["sheet"]["equipamentos"]
    assert eq["arma_principal"] == "Adaga" and eq["arma_secundaria"] is None


def test_remover_item_nao_equipado_nao_mexe_nos_slots(aria):
    _vestir_cota(aria)
    td.add_item("Aria", "Tocha", 3)
    td.remove_item("Aria", "Tocha", 3)
    assert aria["sheet"]["equipamentos"]["armadura"] == "Cota de Malha"


def test_equipado_que_nunca_esteve_na_mochila_nao_e_tirado(aria):
    """Ficha antiga equipava sem pôr no inventário; remover outra coisa não pode apagar isso."""
    aria["sheet"]["equipamentos"]["arma_principal"] = "Espada Longa"
    td.add_item("Aria", "Tocha", 1)
    td.remove_item("Aria", "Tocha", 1)
    assert aria["sheet"]["equipamentos"]["arma_principal"] == "Espada Longa"


# ---------------------------------------------------------------------------
# 2. equip_item
# ---------------------------------------------------------------------------

def test_item_desconhecido_sem_slot_nao_vira_armadura(aria):
    """O caso medido: a corda tirava a cota de malha do corpo."""
    _vestir_cota(aria)
    td.add_item("Aria", "Corda de Cânhamo", 1)
    saida = td.equip_item("Aria", "Corda de Cânhamo")
    assert saida.startswith("Erro:")
    assert aria["sheet"]["equipamentos"]["armadura"] == "Cota de Malha"
    assert aria["sheet"]["ca"] == 16


def test_uma_unidade_nao_ocupa_dois_slots(aria):
    td.add_item("Aria", "Adaga", 1)
    td.equip_item("Aria", "Adaga", "arma_principal")
    saida = td.equip_item("Aria", "Adaga", "arma_secundaria")
    assert saida.startswith("Erro:")
    assert aria["sheet"]["equipamentos"]["arma_secundaria"] is None


def test_duas_unidades_ocupam_as_duas_maos(aria):
    td.add_item("Aria", "Adaga", 2)
    td.equip_item("Aria", "Adaga", "arma_principal")
    assert "equipou" in td.equip_item("Aria", "Adaga", "arma_secundaria")


def test_arma_sem_slot_vai_para_a_mao_livre(aria):
    td.add_item("Aria", "Espada Longa", 1)
    td.add_item("Aria", "Adaga", 1)
    td.equip_item("Aria", "Espada Longa")
    td.equip_item("Aria", "Adaga")
    eq = aria["sheet"]["equipamentos"]
    assert eq["arma_principal"] == "Espada Longa" and eq["arma_secundaria"] == "Adaga"


def test_armadura_no_slot_de_arma_e_recusada(aria):
    td.add_item("Aria", "Cota de Malha", 1)
    assert td.equip_item("Aria", "Cota de Malha", "arma_principal").startswith("Erro:")


def test_coisa_qualquer_no_slot_de_armadura_e_recusada(aria):
    td.add_item("Aria", "Bugiganga do Vhar", 1)
    assert td.equip_item("Aria", "Bugiganga do Vhar", "armadura").startswith("Erro:")
    assert aria["sheet"]["equipamentos"]["armadura"] is None


def test_escudo_no_slot_de_armadura_e_recusado(aria):
    td.add_item("Aria", "Escudo", 1)
    assert td.equip_item("Aria", "Escudo", "armadura").startswith("Erro:")


def test_recusas_tem_prefixo(aria):
    assert td.equip_item("Aria", "Espada Inexistente").startswith("Erro:")
    assert td.equip_item("Aria", "Espada Inexistente", "slot_magico").startswith("Erro:")
    assert td.unequip_item("Aria", "slot_magico").startswith("Erro:")
    assert td.unequip_item("Aria", "escudo").startswith("Nota:")
    assert td.remove_item("Aria", "Nada").startswith("Erro:")


def test_equipar_de_novo_no_mesmo_slot_e_nota(aria):
    _vestir_cota(aria)
    assert td.equip_item("Aria", "Cota de Malha", "armadura").startswith("Nota:")


def test_nome_sem_acento_acha_o_item(aria):
    td.add_item("Aria", "Camisão de Malha", 1)
    assert "equipou" in td.equip_item("Aria", "Camisao de Malha", "armadura")


# ---------------------------------------------------------------------------
# 3. Identificação
# ---------------------------------------------------------------------------

def test_item_magico_nunca_conferido_esta_a_identificar(aria):
    aria["inventario"].append({"nome": "Manto Élfico", "qtd": 1, "descricao": ""})
    assert td._a_identificar(aria["inventario"][-1])


def test_item_comum_nao_esta_a_identificar(aria):
    aria["inventario"].append({"nome": "Corda de Cânhamo", "qtd": 1, "descricao": ""})
    assert not td._a_identificar(aria["inventario"][-1])


def test_item_conferido_na_entrada_nao_esta_a_identificar(aria):
    td.add_item("Aria", "Lâmina Rúnica de Vhar", 1, "só sabor")
    item = next(i for i in aria["inventario"] if i["nome"] == "Lâmina Rúnica de Vhar")
    assert "custom" in item and not td._a_identificar(item)


def test_identificar_fora_do_srd_marca_e_nao_oferece_de_novo(aria, monkeypatch):
    srd_falso(monkeypatch, {})                       # o Open5e responde 404
    aria["inventario"].append({"nome": "Lâmina Rúnica de Vhar", "qtd": 1, "descricao": ""})
    saida = td.identify_item("Aria", "Lâmina Rúnica de Vhar")
    assert saida.startswith("Aviso:")
    item = aria["inventario"][-1]
    assert item["custom"] is True and item["identificado"] is True
    assert not td._a_identificar(item)


def test_identificar_sem_personagem_tem_prefixo(campanha):
    assert td.identify_item("Ninguém", "Manto").startswith("Erro:")


# ---- identificação: nome em português e casamento exato ---------------------
#
# Dois defeitos. O SRD é em inglês e a busca ia com o nome em português:
# "Manto Élfico" nunca achava "Cloak of Elvenkind" e virava homebrew. E a busca
# textual do Open5e procura também nas descrições; o código ficava com o
# resultado de mais palavras em comum mesmo quando nenhuma coincidia, e
# gravava a descrição de outro item.

_CLOAK = {"name": "Cloak of Elvenkind", "type": "Wondrous item", "rarity": "uncommon",
          "requires_attunement": "requires attunement", "document__slug": "wotc-srd",
          "desc": "While you wear this cloak with its hood up, Wisdom (Perception) checks..."}
_SRD = {
    "cloak-of-elvenkind": _CLOAK,
    "ring-of-protection": {"name": "Ring of Protection", "type": "Ring", "rarity": "rare",
                           "requires_attunement": "requires attunement",
                           "document__slug": "wotc-srd", "desc": "You gain a +1 bonus to AC..."},
    "weapon-1-2-or-3": {"name": "Weapon, +1, +2, or +3", "type": "Weapon (any)",
                        "rarity": "uncommon (+1), rare (+2), or very rare (+3)",
                        "requires_attunement": "", "document__slug": "wotc-srd",
                        "desc": "You have a bonus to attack and damage rolls..."},
}
_EXCALIBUR = {"name": "Excalibur's Scabbard", "type": "Wondrous item", "rarity": "legendary",
              "document__slug": "a5e", "desc": "A longsword sheath..."}


def srd_falso(monkeypatch, itens=None, busca=None, chamadas=None):
    """Open5e simulado: slug devolve o item ou 404; busca devolve `busca`."""
    from rpg import open5e
    itens = _SRD if itens is None else itens

    def falso(url, params=None, timeout=5.0):
        if chamadas is not None:
            chamadas.append((url, dict(params or {})))
        if params and "search" in params:
            return open5e.Response(True, {"results": list(busca or [])}, 200)
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        dados = itens.get(slug)
        return open5e.Response(bool(dados), dados, 200 if dados else 404)

    monkeypatch.setattr(open5e, "get", falso)


def test_manto_elfico_e_o_cloak_of_elvenkind(aria, monkeypatch):
    srd_falso(monkeypatch)
    aria["inventario"].append({"nome": "Manto Élfico", "qtd": 1, "descricao": ""})

    saida = td.identify_item("Aria", "Manto Élfico")

    item = aria["inventario"][-1]
    assert "Cloak of Elvenkind" in saida and not saida.startswith(("Aviso:", "Erro:"))
    assert item["nome_srd"] == "Cloak of Elvenkind" and item["custom"] is False
    assert item["srd"] == {"tipo": "item maravilhoso", "raridade": "incomum", "sintonizacao": True}
    assert item["descricao"].startswith("[uncommon]")
    assert not td._a_identificar(item)


@pytest.mark.parametrize("nome, esperado", [
    ("Anel de Proteção", "Ring of Protection"),        # cabeça "de" complemento
    ("Espada Longa +1", "Weapon, +1, +2, or +3"),       # arma com bônus
    ("Cloak of Elvenkind", "Cloak of Elvenkind"),       # quem já escreveu em inglês
    ("Capa Élfica", "Cloak of Elvenkind"),
])
def test_nomes_que_chegam_ao_srd(nome, esperado, monkeypatch, campanha):
    srd_falso(monkeypatch)
    assert (td._search_open5e_item(nome) or {}).get("name") == esperado


def test_busca_que_devolve_outro_item_nao_e_aceita(aria, monkeypatch):
    """O caso da Excalibur: resultado da busca sem o nome pedido."""
    srd_falso(monkeypatch, itens={}, busca=[_EXCALIBUR, {**_CLOAK, "name": "Cloak of the Bat"}])
    aria["inventario"].append({"nome": "Espada Rúnica", "qtd": 1, "descricao": "a original"})

    saida = td.identify_item("Aria", "Espada Rúnica")

    item = aria["inventario"][-1]
    assert saida.startswith("Aviso:")
    assert item["descricao"] == "a original", "a descrição foi trocada pela de outro item"
    assert "nome_srd" not in item


def test_busca_fica_no_srd_oficial(campanha, monkeypatch):
    chamadas = []
    srd_falso(monkeypatch, itens={}, chamadas=chamadas)
    td._search_open5e_item("Manto Élfico")
    buscas = [p for _, p in chamadas if "search" in p]
    assert buscas and all(p.get("document__slug") == "wotc-srd" for p in buscas)


def test_item_de_terceiros_com_o_mesmo_slug_nao_conta(campanha, monkeypatch):
    srd_falso(monkeypatch, itens={"cloak-of-elvenkind": {**_CLOAK, "document__slug": "a5e"}})
    assert td._search_open5e_item("Manto Élfico") is None


def test_parentese_do_srd_casa_com_os_dois_nomes():
    assert td._mesmo_item("Stone of Good Luck (Luckstone)", "Luckstone")
    assert td._mesmo_item("Stone of Good Luck (Luckstone)", "stone of good luck")
    assert not td._mesmo_item("Cloak of the Bat", "Cloak of Elvenkind")


def test_sem_resposta_do_open5e_nao_marca_como_homebrew(aria):
    """Offline (padrão dos testes): não se sabe se existe, então nada é marcado."""
    aria["inventario"].append({"nome": "Manto Élfico", "qtd": 1, "descricao": ""})

    saida = td.identify_item("Aria", "Manto Élfico")

    item = aria["inventario"][-1]
    assert saida.startswith("Erro:") and "tente de novo" in saida
    assert "custom" not in item and td._a_identificar(item), "o botão sumiu por uma queda de rede"


# ---------------------------------------------------------------------------
# 4. Snapshot e ação da tela
# ---------------------------------------------------------------------------

def test_snapshot_mostra_slots_carga_e_ca(aria):
    _vestir_cota(aria)
    p = td.inventory_snapshot("Aria")["personagem"]
    slots = {e["slot"]: e for e in p["equipados"]}
    assert slots["armadura"]["item"] == "Cota de Malha"
    assert "pesada" in slots["armadura"]["detalhe"]
    assert p["ca"] == 16
    assert p["carga"]["capacidade"] > 0 and p["carga"]["kg"] >= 20


def test_snapshot_da_previa_de_ca_para_armadura(aria):
    td.add_item("Aria", "Cota de Malha", 1)
    td.add_item("Aria", "Escudo", 1)
    itens = {i["nome"]: i for i in td.inventory_snapshot("Aria")["personagem"]["itens"]}
    cota = itens["Cota de Malha"]["opcoes_de_equipar"]
    assert cota == [{"slot": "armadura", "rotulo": "Armadura", "ca_previa": 16, "substitui": ""}]
    assert itens["Escudo"]["opcoes_de_equipar"][0]["ca_previa"] == 12


def test_snapshot_nao_oferece_slot_sem_unidade_livre(aria):
    td.add_item("Aria", "Adaga", 1)
    td.equip_item("Aria", "Adaga", "arma_principal")
    adaga = next(i for i in td.inventory_snapshot("Aria")["personagem"]["itens"]
                 if i["nome"] == "Adaga")
    assert adaga["opcoes_de_equipar"] == []
    assert adaga["equipado_em"] == ["Mão principal"]


def test_snapshot_marca_equipado_fora_da_mochila(aria):
    aria["sheet"]["equipamentos"]["arma_principal"] = "Espada Longa"
    slots = {e["slot"]: e for e in td.inventory_snapshot("Aria")["personagem"]["equipados"]}
    assert slots["arma_principal"]["fora_da_mochila"] is True


def test_acao_passa_pelas_mesmas_ferramentas(aria, monkeypatch):
    vistas = []

    def espiar(nome, real):
        def _wrap(*a, _n=nome, _r=real, **k):
            vistas.append(_n)
            return _r(*a, **k)
        return _wrap

    for nome in ("equip_item", "unequip_item", "remove_item", "identify_item"):
        monkeypatch.setattr(td, nome, espiar(nome, getattr(td, nome)))

    td.add_item("Aria", "Cota de Malha", 1)
    aria["inventario"].append({"nome": "Manto Élfico", "qtd": 1, "descricao": ""})
    td.inventory_action("equipar", char="Aria", item="Cota de Malha", slot="armadura")
    td.inventory_action("desequipar", char="Aria", slot="armadura")
    td.inventory_action("identificar", char="Aria", item="Manto Élfico")
    td.inventory_action("largar", char="Aria", item="Cota de Malha")
    assert vistas == ["equip_item", "unequip_item", "identify_item", "remove_item"]


def test_acao_recusada_e_ok_falso(aria):
    r = td.inventory_action("equipar", char="Aria", item="Nada", slot="armadura")
    assert r["ok"] is False and r["snapshot"]["personagem"]["nome"] == "Aria"


def test_identificar_fora_do_srd_nao_e_recusa_na_tela(aria, monkeypatch):
    srd_falso(monkeypatch, {})
    aria["inventario"].append({"nome": "Lâmina Rúnica de Vhar", "qtd": 1, "descricao": ""})
    r = td.inventory_action("identificar", char="Aria", item="Lâmina Rúnica de Vhar")
    assert r["ok"] is True
    assert r["resultado"]["consultou"] is True and r["resultado"]["encontrado"] is False


def test_acao_de_identificar_traz_o_resultado_em_dados(aria, monkeypatch):
    srd_falso(monkeypatch)
    aria["inventario"].append({"nome": "Manto Élfico", "qtd": 1, "descricao": ""})

    r = td.inventory_action("identificar", char="Aria", item="Manto Élfico")

    assert r["resultado"] == {"item": "Manto Élfico", "consultou": True, "encontrado": True,
                              "nome_srd": "Cloak of Elvenkind", "tipo": "item maravilhoso",
                              "raridade": "incomum", "sintonizacao": True}
    manto = next(i for i in r["snapshot"]["personagem"]["itens"] if i["nome"] == "Manto Élfico")
    assert manto["nome_srd"] == "Cloak of Elvenkind" and manto["a_identificar"] is False


def test_identificar_sem_conexao_e_ok_falso_na_tela(aria):
    aria["inventario"].append({"nome": "Manto Élfico", "qtd": 1, "descricao": ""})
    r = td.inventory_action("identificar", char="Aria", item="Manto Élfico")
    assert r["ok"] is False and r["resultado"]["consultou"] is False


def test_largar_uma_unidade(aria):
    td.add_item("Aria", "Tocha", 3)
    td.inventory_action("largar", char="Aria", item="Tocha")
    assert next(i for i in aria["inventario"] if i["nome"] == "Tocha")["qtd"] == 2


def test_acao_desconhecida(aria):
    assert td.inventory_action("jogar_fora_tudo", char="Aria")["ok"] is False


def test_grupo_vazio(campanha):
    snap = td.inventory_snapshot()
    assert snap["tem_personagem"] is False


def test_as_rotas_da_mochila_estao_registradas():
    import server
    rotas = {r.rule for r in server.app.url_map.iter_rules()}
    assert "/api/inventory/state" in rotas and "/api/inventory/action" in rotas
