"""
test_mana_e_nomes_do_grimorio.py

Duas coisas que o Grimório mostrava diferente do resto do jogo.

1. A MANA divergia entre telas: a mesma clériga aparecia com 28 na ficha do
   herói e 14 no Grimório. O motor corrige o pool pela tabela oficial de
   Pontos de Magia ao carregar a campanha, mas quem semeia estado por outro
   caminho (o harness de capturas, os testes de tela) pulava a correção —
   e a tela mostrava um número que o jogo nunca mostraria.

2. Os NOMES vinham do SRD, em inglês: o jogador escolhia "Cure Wounds" e
   depois lia "Cura Ferimentos" na ficha. O nome traduz pela mesma tabela que
   o learn_spell usa para achar a magia; a escola também; a descrição fica
   como veio e se identifica, menos a das magias que o motor já descreve.
"""
import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha


# ---------------------------------------------------------------------------
# A mana
# ---------------------------------------------------------------------------

def test_normalizar_corrige_o_pool_fora_da_tabela(campanha, povoar):
    helena = criar_ficha("Helena", grupo=True, nivel=3, mana=28)
    helena["sheet"]["classe"] = "clérigo"
    helena["sheet"]["mana_max"] = 28
    povoar(helena)

    memory.normalizar_campanha()
    s = memory.campaign["characters"]["helena"]["sheet"]
    assert s["mana_max"] == td._max_mana_for("clérigo", 3) == 14
    assert s["mana_atual"] == 14                  # limitada ao novo máximo


def test_as_duas_telas_passam_a_dizer_o_mesmo(campanha, povoar):
    helena = criar_ficha("Helena", grupo=True, nivel=3, mana=28)
    helena["sheet"]["classe"] = "clérigo"
    helena["sheet"]["mana_max"] = 28
    povoar(helena)
    memory.normalizar_campanha()

    heroi = td.hero_snapshot("Helena")["personagem"]["mana"]
    grimorio = td.grimoire_snapshot("Helena", "", None)["personagem"]
    assert (heroi["atual"], heroi["max"]) == (grimorio["mana_atual"], grimorio["mana_max"])


def test_npc_sem_classe_de_pc_nao_e_mexido(campanha, povoar):
    povoar(criar_ficha("Goblin", mana=7))
    memory.campaign["characters"]["goblin"]["sheet"]["classe"] = "npc"
    memory.normalizar_campanha()
    assert memory.campaign["characters"]["goblin"]["sheet"]["mana_max"] == 7


# ---------------------------------------------------------------------------
# Os nomes
# ---------------------------------------------------------------------------

def test_nome_e_escola_em_portugues():
    assert td._nome_de_magia_pt("Cure Wounds") == "Cura Ferimentos"
    assert td._nome_de_magia_pt("Bless") == "Bênção"
    assert td._escola_pt("Evocation") == "Evocação"
    assert td._escola_pt("Necromancy") == "Necromancia"


def test_magia_sem_traducao_fica_como_no_srd():
    assert td._nome_de_magia_pt("Fire Bolt") == ""
    assert td._escola_pt("Bardic Magic") == "Bardic Magic"


def test_descricao_em_portugues_quando_o_motor_tem(monkeypatch):
    pt = td._descricao_pt_da_magia("Cura Ferimentos")
    assert pt and "[" not in pt          # sem a etiqueta de escola
    assert td._descricao_pt_da_magia("Fire Bolt") == ""
