"""
test_consumiveis.py

Os consumíveis do lote 3. Antes, só a Poção de Cura (e a de resistência)
fazia alguma coisa: a Poção de Força do Gigante, o pergaminho de Bola de Fogo
e a Varinha de Mísseis Mágicos eram "efeito desconhecido — descreva em Ação
Livre", a flecha gasta nunca voltava, e a azagaia arremessada voltava sozinha
para a mão.
"""
import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _item(nome, qtd=1, **extra):
    return {"nome": nome, "qtd": qtd, "descricao": "", "identificado": True, **extra}


@pytest.fixture
def mesa(campanha, povoar):
    alden = criar_ficha("Alden", grupo=True, vida=30, forca=10, destreza=14, nivel=5, arma=None)
    lyra = criar_ficha("Lyra", grupo=True, vida=20, vida_max=20, nivel=5, inteligencia=16,
                       classe="mago", mana=40)
    povoar(alden, lyra, criar_ficha("Goblin", vida=200, destreza=10, ca=5),
           criar_ficha("Orc", vida=200, destreza=10, ca=5))
    return memory.campaign


def _luta(*ordem):
    iniciar_combate(list(ordem) or ["Alden", "Lyra", "Goblin", "Orc"])
    memory.campaign["combat_state"]["turn_economy"] = {
        "acao_usada": False, "bonus_usada": False, "movimento_usado": False}


def _ch(nome):
    return memory.campaign["characters"][nome]


def _qtd(quem, nome):
    return next((int(i.get("qtd", 1)) for i in _ch(quem)["inventario"] if i["nome"] == nome), 0)


# ---------------------------------------------------------------------------
# Poções
# ---------------------------------------------------------------------------

def test_forca_do_gigante_por_uma_hora(mesa):
    _ch("alden")["inventario"].append(_item("Poção de Força do Gigante de Pedra"))
    r = td.inventory_action("usar", char="Alden", item="Poção de Força do Gigante de Pedra")
    assert r["ok"] is True and _ch("alden")["sheet"]["forca"] == 23
    td.advance_time(2)
    assert _ch("alden")["sheet"]["forca"] == 10


def test_velocidade_so_na_luta(mesa):
    _ch("alden")["inventario"].append(_item("Poção de Velocidade"))
    r = td.inventory_action("usar", char="Alden", item="Poção de Velocidade")
    assert r["ok"] is False and _qtd("alden", "Poção de Velocidade") == 1
    _luta()
    ca = td._ca_efetiva(_ch("alden"))
    res = td.combat_action("item", actor="Alden", item="Poção de Velocidade", target="Alden")
    assert res["ok"] is True
    assert td._ca_efetiva(_ch("alden")) == ca + 2
    td.end_combat()
    assert td._ca_efetiva(_ch("alden")) == ca


def test_heroismo(mesa):
    _ch("alden")["inventario"].append(_item("Poção de Heroísmo"))
    td.inventory_action("usar", char="Alden", item="Poção de Heroísmo")
    s = _ch("alden")["sheet"]
    assert s["vida_temp"] == 10
    assert any(e.get("atk_dado") == "1d4" for e in td._efeitos(s))


def test_invisibilidade(mesa):
    _ch("alden")["inventario"].append(_item("Poção de Invisibilidade"))
    td.inventory_action("usar", char="Alden", item="Poção de Invisibilidade")
    assert any(c.get("nome") == "Invisível" for c in _ch("alden")["sheet"]["condicoes"])


def test_pocao_de_veneno_engana(mesa, monkeypatch):
    _ch("alden")["inventario"].append(_item("Poção de Veneno"))
    monkeypatch.setattr(td.random, "randint", lambda a, b: 1 if (a, b) == (1, 20) else b)
    td.inventory_action("usar", char="Alden", item="Poção de Veneno")
    s = _ch("alden")["sheet"]
    assert s["vida_atual"] == 30 - 18
    assert any(c.get("nome") == "Envenenado" for c in s["condicoes"])


# ---------------------------------------------------------------------------
# Varinhas e cajados
# ---------------------------------------------------------------------------

def _cartao(quem, nome):
    snap = td.combat_snapshot()
    eu = next(c for c in snap["combatants"] if c["name"] == quem)
    return next((h for h in eu["habilidades"] if h["nome"] == nome), None)


def test_varinha_de_misseis_na_tela(mesa):
    _ch("alden")["inventario"].append(_item("Varinha de Mísseis Mágicos"))
    _luta()
    cartao = _cartao("Alden", "Mísseis Mágicos [Varinha de Mísseis Mágicos]")
    assert cartao and cartao["usos"] == 7 and cartao["tipo_acao"] == "acao"
    assert [m["id"] for m in cartao["modos"]][:3] == ["c1", "c2", "c3"]
    hp = _ch("goblin")["sheet"]["vida_atual"]
    res = td.combat_action("ability", actor="Alden",
                           ability="Mísseis Mágicos [Varinha de Mísseis Mágicos]",
                           target="Goblin, Goblin, Goblin, Goblin, Goblin", weapon="c3")
    assert res["ok"] is True, res["message"]
    assert _ch("goblin")["sheet"]["vida_atual"] < hp
    item = next(i for i in _ch("alden")["inventario"] if i["nome"] == "Varinha de Mísseis Mágicos")
    assert item["cargas"] == 4                                   # 1 + 2 a mais pelo 3º círculo
    assert memory.campaign["combat_state"]["turn_economy"]["acao_usada"] is True


def test_sem_cargas_nao_gasta_o_turno(mesa):
    _ch("alden")["inventario"].append(_item("Varinha de Mísseis Mágicos", cargas=0))
    _luta()
    res = td.combat_action("ability", actor="Alden",
                           ability="Mísseis Mágicos [Varinha de Mísseis Mágicos]", target="Goblin")
    assert res["ok"] is False
    assert memory.campaign["combat_state"]["turn_economy"]["acao_usada"] is False


def test_varinha_que_pede_sintonia(mesa):
    _ch("lyra")["inventario"].append(_item("Varinha de Bolas de Fogo"))
    _luta("Lyra", "Goblin")
    assert _cartao("Lyra", "Bola de Fogo [Varinha de Bolas de Fogo]") is None
    td.end_combat()
    td.attune_item("Lyra", "Varinha de Bolas de Fogo")
    _luta("Lyra", "Goblin")
    assert _cartao("Lyra", "Bola de Fogo [Varinha de Bolas de Fogo]")
    saida = td._conjurar_do_item("Lyra", "Varinha de Bolas de Fogo", "Bola de Fogo", "Goblin")
    assert "CD 15" in saida


def test_a_ultima_carga_pode_desfazer_a_varinha(mesa, monkeypatch):
    _ch("alden")["inventario"].append(_item("Varinha de Mísseis Mágicos", cargas=1))
    monkeypatch.setattr(td.random, "randint", lambda a, b: 1)
    saida = td._conjurar_do_item("Alden", "Varinha de Mísseis Mágicos", "Mísseis Mágicos", "Goblin")
    assert "se desfaz em pó" in saida and _qtd("alden", "Varinha de Mísseis Mágicos") == 0


def test_recarga_ao_amanhecer(mesa, monkeypatch):
    _ch("alden")["inventario"].append(_item("Varinha de Teia", cargas=1))
    memory.campaign["relogio"] = {"dia": 1, "hora": 20}
    monkeypatch.setattr(td.random, "randint", lambda a, b: b)          # 1d6+1 = 7
    td.advance_time(4)                                                 # 0h: ainda não amanheceu
    item = next(i for i in _ch("alden")["inventario"] if i["nome"] == "Varinha de Teia")
    assert item["cargas"] == 1
    saida = td.advance_time(8)                                         # passa das 6h
    assert item["cargas"] == 7 and "recupera cargas" in saida


def test_cajado_da_cura_fora_da_luta(mesa):
    clerigo = _ch("lyra")
    clerigo["sheet"]["classe"] = "clérigo"
    clerigo["sheet"]["sabedoria"] = 16
    clerigo["inventario"].append(_item("Cajado da Cura"))
    td.attune_item("Lyra", "Cajado da Cura")
    _ch("alden")["sheet"]["vida_atual"] = 5
    saida = td.use_magic_item("Lyra", "Cajado da Cura", "Curar Ferimentos", "Alden", charges=2)
    assert not saida.startswith(("Erro:", "Aviso:")), saida
    assert _ch("alden")["sheet"]["vida_atual"] > 5
    item = next(i for i in clerigo["inventario"] if i["nome"] == "Cajado da Cura")
    assert item["cargas"] == 8


# ---------------------------------------------------------------------------
# Pergaminhos
# ---------------------------------------------------------------------------

def test_mago_le_o_pergaminho_com_a_cd_dele(mesa):
    _ch("lyra")["inventario"].append(_item("Pergaminho de Bola de Fogo"))
    mana = _ch("lyra")["sheet"]["mana_atual"]
    saida = td._conjurar_do_item("Lyra", "Pergaminho de Bola de Fogo", "Bola de Fogo", "Goblin")
    assert "CD 15" in saida and "O pergaminho se desfaz" in saida
    assert _qtd("lyra", "Pergaminho de Bola de Fogo") == 0
    assert _ch("lyra")["sheet"]["mana_atual"] == mana                 # o pergaminho paga


def test_guerreiro_nao_le_pergaminho(mesa):
    _ch("alden")["inventario"].append(_item("Pergaminho de Bola de Fogo"))
    saida = td._conjurar_do_item("Alden", "Pergaminho de Bola de Fogo", "Bola de Fogo", "Goblin")
    assert saida.startswith("Erro:") and _qtd("alden", "Pergaminho de Bola de Fogo") == 1


def test_pergaminho_acima_do_circulo_pede_arcanismo(mesa, monkeypatch):
    lyra = _ch("lyra")
    lyra["sheet"]["nivel"] = 1                                        # só 1º círculo
    lyra["inventario"].append(_item("Pergaminho de Bola de Fogo", qtd=2))
    monkeypatch.setattr(td.random, "randint", lambda a, b: 1 if (a, b) == (1, 20) else b)
    saida = td._conjurar_do_item("Lyra", "Pergaminho de Bola de Fogo", "Bola de Fogo", "Goblin")
    assert "se desfaz sem efeito" in saida and _qtd("lyra", "Pergaminho de Bola de Fogo") == 1
    monkeypatch.setattr(td.random, "randint", lambda a, b: 20 if (a, b) == (1, 20) else b)
    saida = td._conjurar_do_item("Lyra", "Pergaminho de Bola de Fogo", "Bola de Fogo", "Goblin")
    assert "teste de Arcanismo" in saida and "O pergaminho se desfaz" in saida


def test_pergaminho_de_ataque_usa_o_bonus_dele(mesa, monkeypatch):
    # O ataque dela seria +8 (INT 20, proficiência 3); o do pergaminho é +5.
    _ch("lyra")["sheet"].update({"inteligencia": 20, "proficiencia": 3})
    _ch("lyra")["inventario"].append(_item("Pergaminho de Raio de Fogo"))
    monkeypatch.setattr(td.random, "randint", lambda a, b: 10)
    saida = td._conjurar_do_item("Lyra", "Pergaminho de Raio de Fogo", "Raio de Fogo", "Goblin")
    assert "Ataque mágico: d20=10 +5" in saida


# ---------------------------------------------------------------------------
# Munição, arremesso, kit, óleo
# ---------------------------------------------------------------------------

def test_metade_das_flechas_volta(mesa, monkeypatch):
    alden = _ch("alden")
    alden["inventario"] += [_item("Arco Longo"), _item("Flecha", qtd=10)]
    _luta()
    monkeypatch.setattr(td.random, "randint", lambda a, b: 15 if (a, b) == (1, 20) else 1)
    for _ in range(5):
        td.attack_roll("Alden", "Goblin", "Arco Longo", 8, end_turn=False, _skip_turn_check=True)
    assert _qtd("alden", "Flecha") == 5
    assert "recolhe 2x Flecha" in td.end_combat()
    assert _qtd("alden", "Flecha") == 7


def test_azagaia_arremessada_fica_no_chao(mesa, monkeypatch):
    _ch("alden")["inventario"].append(_item("Azagaia", qtd=2))
    _luta()
    td.set_battlefield("Portão, Pátio")
    td.move_combatant("Goblin", "Pátio")
    monkeypatch.setattr(td.random, "randint", lambda a, b: 15 if (a, b) == (1, 20) else 1)
    saida = td.attack_roll("Alden", "Goblin", "Azagaia", 6, end_turn=False, _skip_turn_check=True)
    assert "fica no chão" in saida and _qtd("alden", "Azagaia") == 1
    td.end_combat()
    assert _qtd("alden", "Azagaia") == 2


def test_kit_de_curandeiro_estabiliza(mesa):
    _ch("alden")["inventario"].append(_item("Kit de Curandeiro"))
    lyra = _ch("lyra")
    lyra["sheet"]["vida_atual"] = 0
    lyra["status"] = "inconsciente"
    _luta()
    res = td.combat_action("item", actor="Alden", item="Kit de Curandeiro", target="Lyra")
    assert res["ok"] is True and lyra["status"] == "estabilizado"
    kit = next(i for i in _ch("alden")["inventario"] if i["nome"] == "Kit de Curandeiro")
    assert kit["usos"] == 9 and kit["qtd"] == 1


def test_kit_em_quem_esta_de_pe_nao_gasta(mesa):
    _ch("alden")["inventario"].append(_item("Kit de Curandeiro"))
    _luta()
    res = td.combat_action("item", actor="Alden", item="Kit de Curandeiro", target="Lyra")
    assert res["ok"] is False and memory.campaign["combat_state"]["turn_economy"]["acao_usada"] is False


def test_frasco_de_oleo_queima(mesa, monkeypatch):
    _ch("alden")["inventario"].append(_item("Frasco de Óleo"))
    _luta()
    monkeypatch.setattr(td.random, "randint", lambda a, b: 1)          # o goblin falha
    hp = _ch("goblin")["sheet"]["vida_atual"]
    res = td.combat_action("item", actor="Alden", item="Frasco de Óleo", target="Goblin")
    assert res["ok"] is True and hp - _ch("goblin")["sheet"]["vida_atual"] == 5
    assert "falhou: 5 = 5" in res["message"]


# ---------------------------------------------------------------------------
# O fim da luta não grava o efeito dos itens na ficha (defeito do lote 2)
# ---------------------------------------------------------------------------

def test_fim_da_luta_nao_grava_o_anel(mesa):
    alden = _ch("alden")
    alden["inventario"].append(_item("Anel de Proteção"))
    td.equip_item("Alden", "Anel de Proteção", "anel_1")
    td.attune_item("Alden", "Anel de Proteção")
    alden["sheet"].setdefault("efeitos", []).append({"nome": "Bênção", "atk_dado": "1d4", "ate_hora": 9999})
    _luta()
    td.end_combat()
    assert not any(e.get("de_item") for e in alden["sheet"].get("efeitos") or [])
    td.unequip_item("Alden", "anel_1")
    assert not any(e.get("save_fixo") for e in td._efeitos(alden["sheet"]))
