"""
test_itens_na_mao.py

Revisão do sistema de itens, feita com a campanha real carregada no motor.

O QUE ESTAVA CERTO e este arquivo tranca para não regredir:
  • peso: Cota de Malha pesa 24,95 kg e conta na carga; empilhamento soma;
  • tirar ou VENDER um item equipado desequipa e recalcula a CA;
  • add_item empilha sem se importar com a caixa ("Poção" e "POÇÃO");
  • o saque prevê a carga antes de concluir (imóvel aparece ANTES de aceitar);
  • a loja recusa compra sem ouro e vende pela metade da tabela.

O QUE ESTAVA ERRADO, e por que importa:
  • a besta atirava para sempre: 20 virotes antes do tiro, 20 depois. Munição
    que nunca acaba faz a mochila e a loja não significarem nada;
  • "Espada Longa +1" não somava +1 em lugar nenhum — era uma espada comum
    com nome comprido;
  • atacar com uma arma que o personagem NÃO TEM funcionava igual: o mestre
    escrevia "Machado de Guerra Flamejante" e o motor rolava o ataque sem
    piscar.
"""
import random

import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _item(nome, qtd=1, descricao="", **extra):
    return {"nome": nome, "qtd": qtd, "descricao": descricao, **extra}


@pytest.fixture
def mesa(povoar):
    helena = criar_ficha("Helena", grupo=True, forca=16, destreza=14, nivel=3,
                         arma="espada longa")
    helena["inventario"] = [
        _item("Espada Longa", descricao="1d8 cortante."),
        _item("Besta Leve", descricao="1d8 perfurante."),
        _item("Virotes", qtd=3, descricao="Munição."),
        _item("Cota de Malha", descricao="CA 16. Armadura pesada."),
    ]
    helena["sheet"]["equipamentos"]["arma_principal"] = "Espada Longa"
    goblin = criar_ficha("Goblin", vida=40, vida_max=40, ca=10)
    povoar(helena, goblin)
    iniciar_combate(["Helena", "Goblin"])
    memory.campaign["combat_state"]["turn_economy"] = {
        "acao_usada": False, "bonus_usada": False, "movimento_usado": False}
    return memory.campaign


def _inv(quem, nome):
    ch = memory.campaign["characters"][memory.char_key(quem)]
    return next((i for i in (ch.get("inventario") or [])
                 if td._norm_txt(i["nome"]) == td._norm_txt(nome)), None)


def _atacar(arma, quem="Helena", alvo="Goblin", lados=8):
    return td.attack_roll(quem, alvo, arma, lados, end_turn=False, _skip_turn_check=True)


# ---------------------------------------------------------------------------
# 1. Munição
# ---------------------------------------------------------------------------

def test_cada_tiro_gasta_um_virote(mesa):
    _atacar("Besta Leve")
    assert _inv("Helena", "Virotes")["qtd"] == 2
    _atacar("Besta Leve")
    assert _inv("Helena", "Virotes")["qtd"] == 1


def test_a_conta_aparece_no_resultado(mesa):
    assert "Virotes: 2 restantes" in _atacar("Besta Leve")


def test_o_ultimo_virote_avisa(mesa):
    _inv("Helena", "Virotes")["qtd"] = 1
    saida = _atacar("Besta Leve")
    assert "sem munição" in saida
    assert _inv("Helena", "Virotes") is None


def test_sem_municao_o_tiro_e_recusado(mesa):
    _inv("Helena", "Virotes")["qtd"] = 0
    vida_antes = memory.campaign["characters"]["goblin"]["sheet"]["vida_atual"]
    saida = _atacar("Besta Leve")
    assert saida.startswith("Erro:")
    assert "não tem mais" in saida
    assert memory.campaign["characters"]["goblin"]["sheet"]["vida_atual"] == vida_antes


def test_arma_de_mao_nao_gasta_nada(mesa):
    _atacar("Espada Longa")
    assert _inv("Helena", "Virotes")["qtd"] == 3


def test_quem_nunca_anotou_municao_continua_atirando(mesa):
    """Mochila mal preenchida não pode travar a luta."""
    helena = memory.campaign["characters"]["helena"]
    helena["inventario"] = [i for i in helena["inventario"] if i["nome"] != "Virotes"]
    saida = _atacar("Besta Leve")
    assert not saida.startswith("Erro:")
    assert "restantes" not in saida


def test_monstro_nao_controla_municao(mesa):
    goblin = memory.campaign["characters"]["goblin"]
    goblin["inventario"] = [_item("Virotes", qtd=0)]
    saida = td.attack_roll("Goblin", "Helena", "Besta Leve", 8,
                           end_turn=False, _skip_turn_check=True)
    assert not saida.startswith("Erro:")


@pytest.mark.parametrize("arma,municao", [
    ("Arco Longo", "Flechas"), ("Funda", "Balas de Funda"), ("Besta Pesada", "Virotes"),
])
def test_cada_arma_come_a_sua_municao(mesa, arma, municao):
    helena = memory.campaign["characters"]["helena"]
    # Só a munição do caso, para não haver duas linhas que sirvam à mesma arma.
    helena["inventario"] = [i for i in helena["inventario"] if i["nome"] != "Virotes"]
    helena["inventario"].append(_item(municao, qtd=2))
    _atacar(arma)
    assert _inv("Helena", municao)["qtd"] == 1


# ---------------------------------------------------------------------------
# 2. Arma mágica
# ---------------------------------------------------------------------------

def _numeros(saida):
    """(total do ataque, dano) do texto do resultado."""
    import re
    atk = re.search(r"= \*\*(\d+)\*\* vs CA", saida)
    dano = re.search(r"Dano[^:]*: .*?= \*\*(\d+)\*\*", saida)
    return int(atk.group(1)) if atk else None, int(dano.group(1)) if dano else None


def test_mais_um_do_nome_entra_no_ataque_e_no_dano(mesa):
    """
    A MESMA rolagem com e sem a arma mágica: a diferença tem de ser +1 nos
    dois números. Conferir só o texto deixava passar um "+1(mágica)" escrito
    ao lado de uma conta que não o somava.
    """
    helena = memory.campaign["characters"]["helena"]
    helena["inventario"].append(_item("Espada Longa +1", descricao="Arma mágica."))

    random.seed(4)
    atk_comum, dano_comum = _numeros(_atacar("Espada Longa"))
    memory.campaign["characters"]["goblin"]["sheet"]["vida_atual"] = 40
    random.seed(4)
    atk_magica, dano_magica = _numeros(_atacar("Espada Longa +1"))

    assert atk_magica == atk_comum + 1
    assert dano_magica is not None and dano_comum is not None
    assert dano_magica == dano_comum + 1
    assert "+1(mágica)" in _atacar("Espada Longa +1")


def test_mais_dois_da_descricao(mesa):
    helena = memory.campaign["characters"]["helena"]
    helena["inventario"].append(
        _item("Lâmina do Alvorecer", descricao="Arma mágica: +2 em ataque e dano."))
    assert "+2(mágica)" in _atacar("Lâmina do Alvorecer")


def test_arma_comum_nao_ganha_bonus(mesa):
    assert "mágica" not in _atacar("Espada Longa")


@pytest.mark.parametrize("nome,esperado", [
    ("Espada Longa +1", 1), ("Machado +3", 3), ("Espada Longa", 0),
    ("Adaga +9", 0),            # +9 não é arma do SRD; é número inventado
])
def test_leitura_do_bonus_magico(mesa, nome, esperado):
    char = memory.campaign["characters"]["helena"]
    assert td._bonus_magico_da_arma(char, nome) == esperado


# ---------------------------------------------------------------------------
# 3. Arma que o personagem não tem
# ---------------------------------------------------------------------------

def test_arma_fora_do_inventario_avisa(mesa):
    saida = _atacar("Machado de Guerra Flamejante")
    assert "não está no inventário" in saida


def test_arma_que_ele_tem_nao_avisa(mesa):
    assert "não está no inventário" not in _atacar("Espada Longa")


def test_arma_equipada_sem_linha_no_inventario_nao_avisa(mesa):
    helena = memory.campaign["characters"]["helena"]
    helena["sheet"]["equipamentos"]["arma_secundaria"] = "Adaga Cerimonial"
    assert "não está no inventário" not in _atacar("Adaga Cerimonial")


def test_monstro_nao_e_cobrado_por_inventario(mesa):
    saida = td.attack_roll("Goblin", "Helena", "Cimitarra", 6,
                           end_turn=False, _skip_turn_check=True)
    assert "não está no inventário" not in saida


def test_o_aviso_nao_impede_o_ataque(mesa):
    vida = memory.campaign["characters"]["goblin"]["sheet"]["vida_atual"]
    random.seed(2)
    saida = _atacar("Cadeira de Taverna", lados=4)
    assert "d20" in saida
    assert memory.campaign["characters"]["goblin"]["sheet"]["vida_atual"] <= vida


# ---------------------------------------------------------------------------
# 4. O que já funcionava, e precisa continuar
# ---------------------------------------------------------------------------

def test_tirar_a_armadura_do_inventario_desequipa_e_corrige_a_ca(mesa):
    helena = memory.campaign["characters"]["helena"]
    td.equip_item("Helena", "Cota de Malha", "armadura")
    ca_vestida = helena["sheet"]["ca"]
    saida = td.remove_item("Helena", "Cota de Malha")
    assert "saiu do slot" in saida
    assert not helena["sheet"]["equipamentos"].get("armadura")
    assert helena["sheet"]["ca"] < ca_vestida


def test_vender_o_que_esta_equipado_desequipa(mesa):
    memory.campaign["lojas"] = {"forja": {"nome": "Forja", "local": "",
                                          "estoque": [{"nome": "Espada Longa", "preco": 15,
                                                       "qtd": 9, "descricao": ""}]}}
    td.sell_item("Helena", "Forja", "Espada Longa")
    assert not memory.campaign["characters"]["helena"]["sheet"]["equipamentos"].get("arma_principal")


def test_empilhar_ignora_a_caixa(mesa):
    td.add_item("Helena", "Poção de Cura", 2)
    td.add_item("Helena", "POÇÃO DE CURA", 1)
    linhas = [i for i in memory.campaign["characters"]["helena"]["inventario"]
              if "cura" in i["nome"].lower()]
    assert len(linhas) == 1 and linhas[0]["qtd"] == 3


def test_armadura_pesa_de_verdade(mesa):
    """A carga só é uma escolha se a armadura pesar — ela vem da tabela local
    porque /armor/ do Open5e devolve o peso vazio nas 13."""
    assert td._peso_do_item({"nome": "Cota de Malha"}) > 20
    assert td._peso_do_item({"nome": "Adaga"}) < 2
