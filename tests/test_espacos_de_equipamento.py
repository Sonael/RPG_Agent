"""
test_espacos_de_equipamento.py

O lote 3 dos itens trouxe sete espaços de item mágico de vestir (dois anéis,
capa, botas, luvas, cabeça e cinto), mas só o motor e a Mochila ficaram
sabendo. A ficha do herói e a Mochila só mostravam esses espaços quando
ocupados; o editor da ficha no jogo, o editor da campanha, o assistente, a
importação e toda ficha nova (personagem, NPC, monstro, criatura) seguiam
com os cinco de antes, escritos à mão em cada lugar.

Agora a lista é uma só: rpg/itens.py (SLOTS) no motor e utils.js
(SLOTS_DE_EQUIPAMENTO) nas telas, e este arquivo confere que as duas batem.
"""
import re
from pathlib import Path

import pytest

from rpg import criaturas, itens, memory, tools_dnd as td

from conftest import criar_ficha

RAIZ = Path(__file__).resolve().parent.parent
DOZE = set(itens.SLOTS)


def test_sao_doze_e_o_motor_usa_a_mesma_lista():
    assert len(itens.SLOTS) == 12
    assert td._SLOTS == itens.SLOTS
    assert set(td._ROTULO_DO_SLOT) == DOZE


def test_as_telas_tem_a_mesma_lista_na_mesma_ordem():
    utils = (RAIZ / "static" / "js" / "utils.js").read_text(encoding="utf-8")
    bloco = utils.split("const SLOTS_DE_EQUIPAMENTO = [", 1)[1].split("];", 1)[0]
    assert tuple(re.findall(r"slot: '(\w+)'", bloco)) == itens.SLOTS


@pytest.mark.parametrize("arquivo", ["game.js", "menu.js", "inventory.js", "herois.js"])
def test_nenhuma_tela_escreve_os_espacos_a_mao(arquivo):
    """O dicionário de cinco escrito à mão era o que deixava os novos de fora."""
    js = (RAIZ / "static" / "js" / arquivo).read_text(encoding="utf-8")
    assert not re.search(r"amuleto['\"]?\s*:\s*(null|'')", js), arquivo
    assert "sheet_eq_amuleto','Amuleto'" not in js


# ---------------------------------------------------------------------------
# Fichas novas e fichas gravadas antes
# ---------------------------------------------------------------------------

def test_ficha_criada_pelo_mestre_tem_os_doze(campanha):
    td.create_character_sheet("Mira", "mago", "elfo", 8, 14, 12, 16, 12, 10)
    assert set(memory.campaign["characters"]["mira"]["sheet"]["equipamentos"]) == DOZE


def test_ficha_de_npc_e_de_criatura_tem_os_doze():
    assert set(td._default_npc_sheet()["equipamentos"]) == DOZE
    chave = next(iter(criaturas.FICHAS))
    eq = criaturas.montar_sheet(chave)["equipamentos"]
    assert set(eq) == DOZE and eq["arma_principal"]


def test_editor_com_os_doze_nao_parece_equipamento_mexido(campanha, povoar):
    """A ficha gravada com cinco espaços e a do editor com doze: nada foi vestido."""
    import copy
    povoar(criar_ficha("Aria", grupo=True))
    antiga = memory.campaign["characters"]["aria"]
    antiga["sheet"]["equipamentos"] = {"armadura": None, "escudo": None,
                                       "arma_principal": "espada longa", "amuleto": None}
    novo = copy.deepcopy(antiga)
    novo["sheet"]["equipamentos"] = itens.equipamentos_vazios(arma_principal="espada longa",
                                                              anel_1="")
    assert td.normalize_edited_character(novo, antiga) == []
    # Vestir pelo editor, sem correção, continua barrado.
    novo["sheet"]["equipamentos"]["anel_1"] = "Anel de Proteção"
    assert td.normalize_edited_character(novo, antiga) == ["equipamentos"]
    assert set(novo["sheet"]["equipamentos"]) == DOZE
    assert novo["sheet"]["equipamentos"]["anel_1"] is None


def test_ficha_antiga_ganha_os_que_faltam_sem_perder_o_que_veste():
    char = {"name": "Velho", "sheet": {"equipamentos": {"armadura": "Cota de Malha",
                                                        "arma_principal": "Espada Longa"}}}
    memory._migrate_sheet_fields(char)
    eq = char["sheet"]["equipamentos"]
    assert set(eq) == DOZE
    assert eq["armadura"] == "Cota de Malha" and eq["arma_principal"] == "Espada Longa"
    assert eq["anel_1"] is None and eq["cinto"] is None


@pytest.mark.parametrize("nome, espaco", [
    ("Anel de Ferro com Rubi", "anel_1"),      # fora do SRD: pela primeira palavra
    ("Anel de Proteção", "anel_1"),            # do SRD: pelo compêndio
    ("Manto Élfico", "capa"),
    ("Botas Élficas", "botas"),
])
def test_o_que_o_editor_antigo_pos_no_amuleto_vai_para_o_espaco_dele(nome, espaco):
    char = {"name": "Velho", "sheet": {"equipamentos": {"amuleto": nome}}}
    memory._migrate_sheet_fields(char)
    eq = char["sheet"]["equipamentos"]
    assert eq[espaco] == nome and eq["amuleto"] is None


@pytest.mark.parametrize("equip", [
    {"amuleto": "Amuleto de Saúde"},                          # é de pescoço mesmo
    {"amuleto": "Pingente de Cristal da Alvorada"},
    {"amuleto": "Lembrança da Mãe"},                          # não se sabe onde vai
    {"amuleto": "Anel de Ferro", "anel_1": "Anel A", "anel_2": "Anel B"},   # sem vaga
])
def test_o_que_e_do_pescoco_ou_nao_tem_vaga_fica(equip):
    char = {"name": "Velho", "sheet": {"equipamentos": dict(equip)}}
    memory._migrate_sheet_fields(char)
    assert char["sheet"]["equipamentos"]["amuleto"] == equip["amuleto"]


# ---------------------------------------------------------------------------
# A ficha do herói e a Mochila mostram os doze
# ---------------------------------------------------------------------------

@pytest.fixture
def stelar(campanha, povoar):
    povoar(criar_ficha("Stelar", grupo=True))
    s = memory.campaign["characters"]["stelar"]
    s["inventario"].append({"nome": "Anel de Proteção", "qtd": 1, "descricao": ""})
    s["sheet"]["equipamentos"]["anel_1"] = "Anel de Proteção"
    return s


def test_ficha_do_heroi_mostra_os_doze_vazios_inclusive(stelar):
    eq = td.hero_snapshot("Stelar")["personagem"]["equipados"]
    assert [e["slot"] for e in eq] == list(itens.SLOTS)
    por_slot = {e["slot"]: e for e in eq}
    assert por_slot["anel_1"]["item"] == "Anel de Proteção"
    assert por_slot["botas"]["item"] == "" and por_slot["botas"]["rotulo"] == "Pés"


def test_mochila_manda_os_doze(stelar):
    eq = td.inventory_snapshot("Stelar")["personagem"]["equipados"]
    assert [e["slot"] for e in eq] == list(itens.SLOTS)
    inv = (RAIZ / "static" / "js" / "inventory.js").read_text(encoding="utf-8")
    assert "p.equipados.filter(e => e.basico || e.item)" not in inv
