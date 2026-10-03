"""
test_compendio_de_itens.py

O compêndio local de itens do SRD 5.1 (rpg/itens.py, rpg/dados/srd_itens.json)
e os defeitos que ele corrige. Antes dele o motor sabia de itens por quinze
tabelas à mão e completava o resto no Open5e, em tempo de jogo:

  1. "Espada Longa +1" causava 1d6+1 (o "+1" quebrava a busca do dano), e sem
     rede TODA arma causava 1d6;
  2. Mangual, Maça-Estrela, Azagaia, Machadinha e Rede não tinham tradução;
  3. "Lança" e "Lança Curta" contavam como armas de duas mãos, e nenhuma arma
     versátil usava o dado maior com as duas mãos;
  4. armadura e escudo mágicos não equipavam, e o +N nunca entrava na CA;
  5. "Chain Mail" com o slot informado equipava como CA 10 + DES inteira;
  6. preço só em ouro inteiro: tocha, ração e clava custavam 1 po;
  7. equipamento de aventura, a Poção de Cura e o tesouro não tinham preço;
  8. a Mochila gravava a descrição do SRD em inglês;
  9. o item mágico entrava identificado, e identificar era de graça;
 10. "Poção de Cura" e "Pocao de cura" viravam duas pilhas;
 11. a Mochila e a Loja iam à rede item por item.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from rpg import itens, memory, open5e, tools_dnd as td

from conftest import criar_ficha

RAIZ = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# O compêndio
# ---------------------------------------------------------------------------

def test_o_compendio_tem_o_srd_inteiro():
    comuns, magicos = itens.comuns(), itens.magicos()
    por_categoria = {}
    for e in comuns.values():
        por_categoria[e["categoria"]] = por_categoria.get(e["categoria"], 0) + 1
    assert por_categoria["arma"] == 37
    assert por_categoria["armadura"] == 12 and por_categoria["escudo"] == 1
    assert len(magicos) > 240


def test_todo_item_tem_nome_em_portugues_e_licenca():
    dados = json.loads((RAIZ / "rpg" / "dados" / "srd_itens.json").read_text(encoding="utf-8"))
    assert "Creative Commons" in dados["_licenca"]
    for e in list(dados["itens"].values()) + list(dados["magicos"].values()):
        assert e["nome"].strip() and e["nome_srd"].strip(), e["chave"]


def test_nenhum_nome_aponta_para_dois_itens():
    relatorio = (RAIZ / "scripts" / "srd_itens_relatorio.txt").read_text(encoding="utf-8")
    assert "NOME AMBÍGUO" not in relatorio
    assert "SEM NOME EM PORTUGUÊS" not in relatorio


def test_o_gerador_reproduz_o_compendio(tmp_path):
    """O JSON versionado é exatamente o que o gerador produz dos dados brutos."""
    r = subprocess.run([sys.executable, str(RAIZ / "scripts" / "gerar_itens.py"),
                        "--destino", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    gerado = (tmp_path / "srd_itens.json").read_text(encoding="utf-8")
    assert gerado == (RAIZ / "rpg" / "dados" / "srd_itens.json").read_text(encoding="utf-8")


@pytest.mark.parametrize("nome, chave", [
    ("Espada Longa", "longsword"), ("longsword", "longsword"), ("ESPADA LONGA", "longsword"),
    ("Tocha", "torch"), ("Tochas", "torch"), ("Rações", "rations-1-day"),
    ("Ração (1 dia)", "rations-1-day"), ("Flechas (20)", "arrow-bow"), ("20 Flechas", "arrow-bow"),
    ("Corda", "rope-hempen-50-feet"), ("Kit de Curandeiro", "healers-kit"),
])
def test_nome_vira_item(nome, chave):
    assert itens.comum(nome)["chave"] == chave


# ---------------------------------------------------------------------------
# 1 a 3. Armas
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("arma, dado", [
    ("Espada Longa", (1, 8)), ("Espada Longa +1", (1, 8)), ("Espada Longa (+2)", (1, 8)),
    ("Defensora", (1, 8)), ("Mangual", (1, 8)), ("Maça-Estrela", (1, 8)),
    ("Estrela da Manhã", (1, 8)), ("Malho", (2, 6)), ("Picareta de Guerra", (1, 8)),
    ("Azagaia", (1, 6)), ("Machadinha", (1, 6)), ("Dardo", (1, 4)), ("Arco do Juramento", (1, 8)),
    ("Espada Curta de Prata", (1, 6)), ("Scimitar", (1, 6)), ("Light crossbow", (1, 8)),
])
def test_o_dado_da_arma_sai_do_compendio_sem_rede(arma, dado):
    assert td._fetch_weapon_data(arma) == dado


def test_o_que_nao_e_arma_nao_tem_dado():
    for nome in ("Garra", "Ataque desarmado", "Bastão Imóvel", "Bolsa de Contenção", "Rede"):
        assert td._fetch_weapon_data(nome) is None, nome


@pytest.mark.parametrize("nome, bonus", [("Espada Longa +2", 2), ("Espada Longa (+1)", 1),
                                         ("Espada +3 Longa", 3), ("Espada Longa", 0)])
def test_o_compendio_le_o_bonus_do_nome(nome, bonus):
    a = itens.arma(nome)
    assert a["chave"] == "longsword" and a["bonus"] == bonus and a["magica"] is bool(bonus)


def test_bonus_proprio_do_item_magico():
    # A Defensora pede sintonização: sem ela, é uma espada longa.
    assert td._bonus_magico_da_arma({}, "Defensora") == 0
    assert td._bonus_magico_da_arma({"sheet": {"sintonizados": ["Defensora"]}}, "Defensora") == 3
    assert td._bonus_magico_da_arma({}, "Espada Longa +2") == 2
    assert td._bonus_magico_da_arma({}, "Espada Longa") == 0


@pytest.mark.parametrize("arma, duas_maos", [
    ("Lança", False), ("Lança Curta", False), ("Tridente", False), ("Espada Longa", False),
    ("Espada Grande", True), ("Malho", True), ("Arco Longo", True), ("Besta Leve", True),
])
def test_duas_maos_pelo_srd(arma, duas_maos):
    assert td._arma_de_duas_maos(arma) is duas_maos


@pytest.mark.parametrize("arma, atributo", [
    ("whip", "destreza"), ("Chicote", "destreza"), ("Rapieira", "destreza"),
    ("Espada Longa", "forca"), ("Dardo", "destreza"), ("Besta Pesada", "destreza"),
])
def test_atributo_pelas_propriedades_do_srd(arma, atributo):
    assert td._weapon_attr(arma, {"forca": 8, "destreza": 14})[0] == atributo


def test_espada_curta_e_perfurante():
    """O Open5e v2 dá cortante; a revisão à mão segue o SRD 5.1."""
    assert itens.arma("Espada Curta")["tipo_dano"] == "piercing"


@pytest.fixture
def guerreira(campanha, povoar):
    povoar(criar_ficha("Brynn", grupo=True, forca=16),
           criar_ficha("Alvo", vida=200, ca=1))
    ch = memory.campaign["characters"]["brynn"]
    # As mãos livres: a ficha de teste já vem com uma espada longa na principal.
    ch["sheet"].setdefault("equipamentos", {})["arma_principal"] = None
    return ch


def _dano(monkeypatch, arma):
    monkeypatch.setattr(td.random, "randint", lambda a, b: 15 if (a, b) == (1, 20) else b)
    antes = memory.campaign["characters"]["alvo"]["sheet"]["vida_atual"]
    td.attack_roll("Brynn", "Alvo", arma, 8, end_turn=False, _skip_turn_check=True)
    return antes - memory.campaign["characters"]["alvo"]["sheet"]["vida_atual"]


def test_versatil_nas_duas_maos_usa_o_dado_maior(guerreira, monkeypatch):
    # Dado no máximo: d10 + 3 de FOR.
    assert _dano(monkeypatch, "Espada Longa") == 13


def test_versatil_com_escudo_fica_numa_mao(guerreira, monkeypatch):
    guerreira["sheet"].setdefault("equipamentos", {})["escudo"] = "Escudo"
    assert _dano(monkeypatch, "Espada Longa") == 11


def test_versatil_com_duelo_fica_numa_mao(guerreira, monkeypatch):
    """O +2 do Duelo rende mais que o d10: o motor escolhe uma mão."""
    guerreira["sheet"]["feature_choices"] = {"Estilo de Combate": "Duelo"}
    assert td._versatil_a_duas_maos(guerreira, "Espada Longa") is None


def test_outra_arma_na_mao_tira_as_duas_maos(guerreira, monkeypatch):
    guerreira["sheet"]["equipamentos"]["arma_principal"] = "Adaga"
    assert _dano(monkeypatch, "Espada Longa") == 11


def test_arma_magica_bate_mais_que_a_comum(guerreira, monkeypatch):
    comum = _dano(monkeypatch, "Espada Longa")
    memory.campaign["characters"]["alvo"]["sheet"]["vida_atual"] = 200
    assert _dano(monkeypatch, "Espada Longa +1") == comum + 1


# ---------------------------------------------------------------------------
# 4 e 5. Armaduras
# ---------------------------------------------------------------------------

def _ca(guerreira, armadura, escudo=""):
    guerreira["sheet"]["destreza"] = 14
    for nome in (armadura, escudo):
        if nome:
            td.add_item("Brynn", nome, 1)
    if armadura:
        assert "equipou" in td.equip_item("Brynn", armadura, "armadura")
    if escudo:
        assert "equipou" in td.equip_item("Brynn", escudo, "escudo")
    return guerreira["sheet"]["ca"]


def test_armadura_magica_equipa_e_soma_o_bonus(guerreira):
    assert _ca(guerreira, "Cota de Malha +1") == 17


def test_escudo_magico_soma_o_bonus(guerreira):
    assert _ca(guerreira, "Cota de Malha", "Escudo +1") == 19


def test_armadura_de_item_magico_usa_a_base_e_o_bonus(guerreira):
    assert _ca(guerreira, "Placas Anãs") == 20


def test_nome_em_ingles_tem_a_ca_certa(guerreira):
    """Antes ia ao Open5e e voltava com CA 10 + DES inteira."""
    assert _ca(guerreira, "Chain Mail") == 16


def test_armadura_que_nao_e_do_srd_continua_recusada(guerreira):
    td.add_item("Brynn", "Armadura de Mithral", 1)
    assert td.equip_item("Brynn", "Armadura de Mithral", "armadura").startswith("Erro:")


# ---------------------------------------------------------------------------
# 6 e 7. Preço em cobre e o que a loja sabe avaliar
# ---------------------------------------------------------------------------

def test_preco_em_cobre_na_compra(campanha, povoar):
    povoar(criar_ficha("Brynn", grupo=True))
    sheet = memory.campaign["characters"]["brynn"]["sheet"]
    sheet.update({"ouro": 1, "prata": 0, "cobre": 0})
    td.open_shop("Armazém", "Tocha; Ração", location="Vila")
    saida = td.buy_item("Brynn", "Armazém", "Tocha", 20)
    assert "por 2 pp" in saida
    assert (sheet["ouro"], sheet["prata"], sheet["cobre"]) == (0, 8, 0)


@pytest.mark.parametrize("texto, pc", [("50", 5000), ("5 pp", 50), ("2pc", 2), ("0.5", 50),
                                       ("1,5 po", 150), ("abc", None)])
def test_preco_escrito_pelo_mestre(texto, pc):
    assert td._ler_preco_pc(texto) == pc


@pytest.mark.parametrize("pc, texto", [(1550, "15 po 5 pp"), (5, "5 pc"), (0, "0 pc"), (100, "1 po")])
def test_preco_por_extenso(pc, texto):
    assert td._fmt_pc(pc) == texto


def test_loja_antiga_em_ouro_e_convertida(campanha):
    memory.campaign["lojas"] = {"bazar": {"nome": "Bazar", "local": "", "dono": "",
                                          "estoque": [{"nome": "Corda", "preco": 3, "qtd": 99}]}}
    linha = td._lojas()["bazar"]["estoque"][0]
    assert linha["preco_pc"] == 300 and "preco" not in linha


def test_venda_paga_nas_moedas_certas(campanha, povoar):
    povoar(criar_ficha("Brynn", grupo=True))
    ch = memory.campaign["characters"]["brynn"]
    ch["sheet"].update({"ouro": 0, "prata": 0, "cobre": 0})
    ch["inventario"] = [{"nome": "Clava", "qtd": 1, "descricao": ""}]
    td.open_shop("Armazém", "Tocha", location="Vila")
    saida = td.sell_item("Brynn", "Armazém", "Clava")
    assert "5 pc" in saida
    assert (ch["sheet"]["ouro"], ch["sheet"]["prata"], ch["sheet"]["cobre"]) == (0, 0, 5)


def test_tesouro_vende_pelo_valor_cheio(campanha, povoar):
    povoar(criar_ficha("Brynn", grupo=True))
    ch = memory.campaign["characters"]["brynn"]
    ch["sheet"].update({"ouro": 0, "prata": 0, "cobre": 0})
    ch["inventario"] = [{"nome": "Rubi (50 po)", "qtd": 1, "descricao": ""},
                        {"nome": "Poção de Cura", "qtd": 1, "descricao": ""}]
    td.open_shop("Joalheiro", "Tocha", location="Vila")
    assert "tesouro: valor cheio" in td.sell_item("Brynn", "Joalheiro", "Rubi (50 po)")
    assert ch["sheet"]["ouro"] == 50
    # A poção achada no saque também vende, pela metade dos 50 po.
    td.sell_item("Brynn", "Joalheiro", "Poção de Cura")
    assert ch["sheet"]["ouro"] == 75


# ---------------------------------------------------------------------------
# 8 a 10. Item mágico na entrada
# ---------------------------------------------------------------------------

@pytest.fixture
def aria(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True))
    return memory.campaign["characters"]["aria"]


def test_item_magico_entra_por_identificar_e_em_portugues(aria):
    td.add_item("Aria", "Manto Élfico", 1)
    item = aria["inventario"][-1]
    assert item["custom"] is False and item["identificado"] is False
    assert item["srd"]["raridade"] == "incomum"
    assert item["descricao"] == ""                     # nada de texto em inglês
    assert td._a_identificar(item)
    snap = next(i for i in td.inventory_snapshot("Aria")["personagem"]["itens"]
                if i["nome"] == "Manto Élfico")
    assert snap["nome_srd"] == "" and snap["a_identificar"] is True


def test_bolsa_de_contencao_e_conferida_sem_palavra_magica(aria):
    """A conferência só disparava para nome mágico; agora todo item passa."""
    td.add_item("Aria", "Bolsa de Contenção", 1)
    assert aria["inventario"][-1]["nome_srd"] == "Bag of Holding"


def test_item_magico_comum_ja_entra_identificado(aria):
    td.add_item("Aria", "Poção de Cura", 2)
    item = aria["inventario"][-1]
    assert item["identificado"] is True and not td._a_identificar(item)
    assert item["descricao"] == "Poção — comum."


def test_o_que_sai_da_loja_ja_vem_identificado(aria):
    aria["sheet"]["ouro"] = 1000
    td.open_shop("Arcana", "Poção de Cura Maior:150", location="Vila")
    td.buy_item("Aria", "Arcana", "Poção de Cura Maior")
    assert aria["inventario"][-1]["identificado"] is True


def test_mesma_pilha_com_ou_sem_acento(aria):
    td.add_item("Aria", "Poção de Cura", 1)
    td.add_item("Aria", "Pocao de cura", 2)
    pilhas = [i for i in aria["inventario"] if td._norm_txt(i["nome"]) == "pocao de cura"]
    assert len(pilhas) == 1 and pilhas[0]["qtd"] == 3


def test_quantidade_negativa_e_recusada(aria):
    td.add_item("Aria", "Tocha", 2)
    assert td.add_item("Aria", "Tocha", -5).startswith("Erro:")
    assert td.add_item("Aria", "Corda", 0).startswith("Erro:")
    assert next(i for i in aria["inventario"] if i["nome"] == "Tocha")["qtd"] == 2


# ---------------------------------------------------------------------------
# 11. Nada de rede
# ---------------------------------------------------------------------------

def test_mochila_loja_e_ataque_nao_vao_a_rede(aria, monkeypatch, povoar):
    def proibido(*a, **k):
        raise AssertionError("foi à rede")
    monkeypatch.setattr(open5e, "get", proibido)
    aria["sheet"]["ouro"] = 1000
    for nome in ("Espada Longa +1", "Cota de Malha", "Manto Élfico", "Kit de Curandeiro",
                 "Bugiganga do Vhar", "Chain Mail"):
        td.add_item("Aria", nome, 1)
    td.equip_item("Aria", "Chain Mail", "armadura")
    td.inventory_snapshot("Aria")
    td.open_shop("Forja", "Espada Longa; Tocha; Bugiganga do Vhar:3", location="Vila")
    td.shop_snapshot("Forja", "Aria")
    td.check_encumbrance("Aria")
    povoar(criar_ficha("Alvo", vida=50))
    td.attack_roll("Aria", "Alvo", "Espada Longa +1", 8, end_turn=False, _skip_turn_check=True)
