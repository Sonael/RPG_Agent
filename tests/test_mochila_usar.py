"""
test_mochila_usar.py

A Mochila só equipava, tirava, largava e identificava: beber uma poção depois
da luta exigia pedir ao mestre. Agora o botão de usar sai da mesma ficha de
item da tela tática (_efeito_de_item), com as diferenças de estar fora do
combate: sem economia de ações e sem zonas.
"""
import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _item(nome, qtd=1):
    return {"nome": nome, "qtd": qtd, "descricao": ""}


@pytest.fixture
def grupo(campanha, povoar):
    aria = criar_ficha("Aria", grupo=True, vida=10, vida_max=30)
    aria["inventario"] = [_item("Poção de Cura", 2), _item("Poção de Resistência ao Fogo"),
                          _item("Antitoxina"), _item("Frasco de Ácido"),
                          _item("Poção de Força de Gigante"), _item("Corda")]
    povoar(aria, criar_ficha("Bran", grupo=True, vida=4, vida_max=20),
           criar_ficha("Goblin", vida=7))
    memory.campaign["relogio"] = {"dia": 3, "hora": 10}
    return memory.campaign


def _itens(quem="Aria"):
    return {i["nome"]: i for i in td.inventory_snapshot(quem)["personagem"]["itens"]}


def _hp(quem):
    return memory.campaign["characters"][quem]["sheet"]["vida_atual"]


def _qtd(nome, quem="aria"):
    return next((i["qtd"] for i in memory.campaign["characters"][quem]["inventario"]
                 if i["nome"] == nome), 0)


def _usar(item, alvo="", quem="Aria"):
    return td.inventory_action("usar", char=quem, item=item, alvo=alvo)


def test_snapshot_diz_o_que_da_para_usar_e_por_que_nao(grupo):
    itens = _itens()
    assert itens["Poção de Cura"]["uso"]["pode"] is True
    assert itens["Poção de Cura"]["uso"]["rotulo"] == "Beber"
    assert itens["Poção de Cura"]["uso"]["alvos"] == ["Aria", "Bran"]
    assert itens["Antitoxina"]["uso"]["pode"] is True
    assert itens["Frasco de Ácido"]["uso"]["pode"] is False
    assert "só em combate" in itens["Frasco de Ácido"]["uso"]["motivo"]
    assert itens["Poção de Força de Gigante"]["uso"]["pode"] is False
    assert "mestre" in itens["Poção de Força de Gigante"]["uso"]["motivo"]
    assert itens["Corda"]["uso"] is None


def test_beber_pocao_cura_e_gasta_uma(grupo, monkeypatch):
    monkeypatch.setattr(td.random, "randint", lambda a, b: b)     # 2d4+2 = 10
    r = _usar("Poção de Cura")
    assert r["ok"] is True, r["message"]
    assert _hp("aria") == 20 and _qtd("Poção de Cura") == 1
    assert "Aria bebeu Poção de Cura" in r["message"]
    assert r["snapshot"]["personagem"]["itens"]


def test_dar_pocao_a_outro_do_grupo_e_levantar_caido(grupo):
    bran = grupo["characters"]["bran"]
    bran["status"] = "inconsciente"
    bran["sheet"]["vida_atual"] = 0
    r = _usar("Poção de Cura", alvo="Bran")
    assert r["ok"] is True, r["message"]
    assert bran["status"] == "vivo" and _hp("bran") > 0
    assert "deu a Bran" in r["message"]


def test_caido_nao_bebe_sozinho(grupo):
    grupo["characters"]["aria"]["status"] = "inconsciente"
    assert _itens()["Poção de Cura"]["uso"]["pode"] is False
    r = _usar("Poção de Cura")
    assert r["ok"] is False and r["message"].startswith("Aviso:")
    assert _qtd("Poção de Cura") == 2


def test_pocao_respeita_o_teto_da_exaustao(grupo, monkeypatch):
    s = grupo["characters"]["aria"]["sheet"]
    s.update({"exaustao": 4, "vida_atual": 14})              # teto 15
    monkeypatch.setattr(td.random, "randint", lambda a, b: b)
    r = _usar("Poção de Cura")
    assert _hp("aria") == 15 and "teto 15" in r["message"]


def test_nao_da_pocao_a_inimigo_nem_a_desconhecido(grupo):
    r = _usar("Poção de Cura", alvo="Goblin")
    assert r["ok"] is False and _qtd("Poção de Cura") == 2


def test_arremesso_e_desconhecido_nao_gastam(grupo):
    for nome in ("Frasco de Ácido", "Poção de Força de Gigante"):
        r = _usar(nome)
        assert r["ok"] is False and r["message"].startswith("Aviso:"), r["message"]
        assert "não foi gasto" in r["message"]
        assert _qtd(nome) == 1


def test_em_combate_manda_para_a_tela_tatica(grupo):
    iniciar_combate(["Aria", "Goblin"])
    assert "tela tática" in _itens()["Poção de Cura"]["uso"]["motivo"]
    r = _usar("Poção de Cura")
    assert r["ok"] is False and _qtd("Poção de Cura") == 2


def test_resistencia_bebida_fora_do_combate_dura_uma_hora(grupo):
    r = _usar("Poção de Resistência ao Fogo")
    assert r["ok"] is True and "1 hora" in r["message"]
    sheet = grupo["characters"]["aria"]["sheet"]
    assert td._damage_multiplier(sheet, "fire")[0] == 0.5
    # Um combate no meio não apaga um efeito de 1 hora.
    iniciar_combate(["Aria", "Goblin"])
    td.end_combat()
    assert td._damage_multiplier(sheet, "fire")[0] == 0.5
    td.advance_time(1, "a hora passou")
    assert td._damage_multiplier(sheet, "fire")[0] == 1.0
    assert "Resistência a fogo" not in td.hero_snapshot("Aria")["personagem"]["efeitos"]


def test_antitoxina_fora_do_combate(grupo):
    r = _usar("Antitoxina")
    assert r["ok"] is True
    assert "Antitoxina" in td.hero_snapshot("Aria")["personagem"]["efeitos"]
    assert "Antitoxina" in td.apply_condition("Aria", "envenenado")
