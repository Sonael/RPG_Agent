"""
test_arma_com_efeito.py

"O que acontece se eu pegar uma adaga envenenada e atacar um inimigo, ele fica
envenenado? E se eu for no ferreiro e ele aplicar algum efeito na minha arma ou
aprimorar ela, essas coisas funcionam?"

Não funcionavam. A descrição do item era enfeite: a adaga besuntada de veneno
causava dano perfurante e mais nada, e a lâmina que o ferreiro temperou saía
igualzinha à do dia anterior.

Agora o que está ESCRITO no item acontece — um dado extra com o tipo dele e,
se a descrição disser, uma condição com teste de resistência. Sem ferramenta
nova para o mestre decorar: ele já escreve a descrição.
"""
import random

import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


@pytest.fixture
def mesa(povoar):
    heroi = criar_ficha("Sonael", grupo=True, nivel=3, destreza=16, forca=16)
    heroi["inventario"] = [{"nome": "Adaga", "qtd": 1, "descricao": "Uma adaga comum."}]
    alvo = criar_ficha("Goblin", vida=60, vida_max=60, ca=8, constituicao=10)
    povoar(heroi, alvo)
    iniciar_combate(["Sonael", "Goblin"])
    memory.campaign["combat_state"]["turn_economy"] = {
        "acao_usada": False, "bonus_usada": False, "movimento_usado": False}
    return memory.campaign


def _descricao(texto, item="Adaga"):
    for it in memory.campaign["characters"]["sonael"]["inventario"]:
        if it["nome"] == item:
            it["descricao"] = texto
            return it
    novo = {"nome": item, "qtd": 1, "descricao": texto}
    memory.campaign["characters"]["sonael"]["inventario"].append(novo)
    return novo


def _atacar(arma="Adaga", lados=4, semente=9):
    random.seed(semente)
    return td.attack_roll("Sonael", "Goblin", arma, lados,
                          end_turn=False, _skip_turn_check=True)


def _condicoes():
    return [c["nome"] for c in
            memory.campaign["characters"]["goblin"]["sheet"]["condicoes"]]


# ---------------------------------------------------------------------------
# A adaga envenenada
# ---------------------------------------------------------------------------

def test_a_adaga_envenenada_envenena(mesa):
    _descricao("Adaga besuntada com veneno: +1d4 de dano de veneno e o alvo "
               "fica Envenenado (CD 12 CON).")
    saida = _atacar()
    assert "1d4 de Adaga" in saida
    assert "poison" in saida
    assert "Envenenado" in _condicoes() or "resistiu" in saida


def test_quem_passa_no_teste_nao_e_envenenado(mesa):
    _descricao("Lâmina envenenada: o alvo fica Envenenado (CD 8 CON).")
    passou, falhou = False, False
    for semente in range(40):
        memory.campaign["characters"]["goblin"]["sheet"]["condicoes"] = []
        saida = _atacar(semente=semente)
        if "ERROU" in saida:
            continue
        if "resistiu" in saida:
            passou = True
            assert _condicoes() == []
        elif "**Envenenado**" in saida:
            falhou = True
            assert _condicoes() == ["Envenenado"]
    assert passou and falhou, f"passou={passou} falhou={falhou}"


def test_a_adaga_sem_promessa_nao_faz_nada(mesa):
    _descricao("Uma adaga velha, com o cabo lascado.")
    saida = _atacar()
    assert "de Adaga:" not in saida
    assert _condicoes() == []


def test_o_dano_extra_tem_o_tipo_dele(mesa):
    """Um alvo imune ao veneno resiste a essa parte, e não ao corte."""
    _descricao("Adaga besuntada: +2d4 de dano de veneno.")
    goblin = memory.campaign["characters"]["goblin"]
    goblin["sheet"]["imunidades"] = ["poison"]
    vida = goblin["sheet"]["vida_atual"]
    saida = _atacar()
    assert "2d4 de Adaga" in saida
    # O corte entrou; o veneno não.
    perdeu = vida - goblin["sheet"]["vida_atual"]
    assert 0 < perdeu <= 4 + 3, saida


# ---------------------------------------------------------------------------
# O ferreiro
# ---------------------------------------------------------------------------

def test_o_ferreiro_tempera_a_lamina(mesa):
    """Ele mexe no item que o personagem JÁ tem: add_item com descrição nova."""
    td.add_item("Sonael", "Adaga", 0, "Temperada pelo ferreiro: +1d6 de dano de fogo.")
    item = next(i for i in memory.campaign["characters"]["sonael"]["inventario"]
                if i["nome"] == "Adaga")
    assert "ferreiro" in item["descricao"]
    assert item["qtd"] == 1                      # não virou duas adagas
    saida = _atacar()
    assert "1d6 de Adaga" in saida and "fire" in saida


def test_o_ferreiro_pode_encantar_para_mais_um(mesa):
    td.add_item("Sonael", "Adaga", 0, "Rúnica: +1 em ataque e dano.")
    assert "+1(mágica)" in _atacar()


# ---------------------------------------------------------------------------
# O teto
# ---------------------------------------------------------------------------

def test_dano_exagerado_e_cortado(mesa):
    _descricao("Lâmina amaldiçoada: +5d10 de dano necrótico.")
    saida = _atacar()
    assert "2d8 de Adaga" in saida
    assert "limitado a 2d8" in saida


def test_a_leitura_da_descricao(mesa):
    char = memory.campaign["characters"]["sonael"]
    _descricao("+1d6 de dano de fogo e o alvo fica Queimando (CD 13 DES).")
    efeito = td.efeito_extra_da_arma(char, "Adaga")
    assert efeito["dados"] == (1, 6)
    assert efeito["tipo"] == "fire"
    assert efeito["condicao"] == "Queimando"
    assert efeito["salvaguarda"] == "destreza"
    assert efeito["cd"] == 13


def test_sem_cd_escrita_usa_a_do_atacante(mesa):
    _descricao("Lâmina gélida: o alvo fica Imobilizado.")
    saida = _atacar()
    assert "salvaguarda" in saida


def test_item_que_nao_esta_no_inventario_nao_tem_efeito(mesa):
    char = memory.campaign["characters"]["sonael"]
    assert td.efeito_extra_da_arma(char, "Espada Fantasma") is None


def test_condicao_nao_pega_quem_ja_caiu(mesa):
    """Alvo a zero não ganha condição nova — ele já está fora da luta."""
    _descricao("Adaga besuntada: o alvo fica Envenenado (CD 30 CON).")
    memory.campaign["characters"]["goblin"]["sheet"]["vida_atual"] = 1
    _atacar()
    assert _condicoes() == []


def test_o_prompt_conta_ao_mestre():
    from rpg import agent
    agente = agent.create_agent("gemini-2.5-flash", "dnd", dnd_mode=True)
    instrucao = agente.instruction() if callable(agente.instruction) else agente.instruction
    assert "DESCRIÇÃO DA ARMA É MECÂNICA" in instrucao
    assert "Envenenado (CD 12 CON)" in instrucao
    assert "2d8" in instrucao
