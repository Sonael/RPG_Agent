"""
test_uso_de_habilidades.py

Revisão do uso de habilidades, conferida contra a API do SRD (Open5e).

O QUE A API MOSTROU
O endpoint de magias do Open5e NÃO tem campo de dano: `damage` vem nulo em
todas elas, Bola de Fogo inclusive. O dado está no TEXTO ("8d6 fire damage",
"regains a number of hit points equal to 1d8"), e o mesmo vale para o teste de
resistência ("must make a dexterity saving throw").

O QUE ISSO CAUSAVA
  • toda magia aprendida chegava com dado VAZIO, e _parse_dice cai em 1d6
    quando não entende a fórmula: Bola de Fogo causava 1d6, Inflict Wounds
    causava 1d6;
  • habilidade sem dado nenhum (Segunda Fôlego, Mending, Canalizar
    Divindade — 25 delas na campanha medida) também rolava 1d6 e TIRAVA VIDA
    de quem fosse o alvo: benzer um aliado o machucava;
  • Bênção guardava "1d4", que é o bônus que ela dá aos ataques, e o motor
    tratava como dano: lançá-la no companheiro tirava 1d4 dele;
  • a salvaguarda só existia se o mestre passasse o atributo e a CD na
    chamada. Esquecendo — e esquecer é o problema medido deste projeto —,
    a Bola de Fogo causava dano cheio em todos, sem teste nenhum.
"""
import random

import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


# Descrições como o Open5e as entrega (conferidas na API de verdade).
SRD = {
    "Fireball": "[Evocation] Each creature in a 20-foot-radius sphere must make a dexterity "
                "saving throw. A target takes 8d6 fire damage on a failed save, or half as "
                "much damage on a successful one.",
    "Magic Missile": "[Evocation] A dart deals 1d4 + 1 force damage to its target.",
    "Cure Wounds": "[Evocation] A creature you touch regains a number of hit points equal to "
                   "1d8 + your spellcasting ability modifier.",
    "Inflict Wounds": "[Necromancy] Make a melee spell attack. On a hit, the target takes "
                      "3d10 necrotic damage.",
    "Hold Person": "[Enchantment] The target must succeed on a wisdom saving throw or be "
                   "paralyzed for the duration.",
    "Sleep": "[Enchantment] This spell sends creatures into a magical slumber. Roll 5d8; the "
             "total is how many hit points of creatures this spell can affect.",
    "Bless": "[Enchantment] Whenever a target makes an attack roll or a saving throw before "
             "the spell ends, the target can roll a 1d4 and add the number rolled.",
    "Mage Armor": "[Abjuration] The target's base AC becomes 13 + its Dexterity modifier.",
    "Segunda Fôlego": "Recupera 1d10 + nível de pontos de vida como ação bônus.",
    "Canalizar Divindade": "Usa a fé para um efeito do domínio.",
}


def _hab(nome, dado="", custo=2):
    return {"nome": nome, "descricao": SRD.get(nome, ""), "custo_mana": custo, "dado": dado}


@pytest.fixture
def mesa(povoar):
    mago = criar_ficha("Sonael", grupo=True, nivel=5, mana=20, inteligencia=16)
    mago["sheet"]["classe"] = "mago"
    aliado = criar_ficha("Helena", grupo=True, vida=20, vida_max=30)
    povoar(mago, aliado, criar_ficha("Goblin", vida=25, destreza=12, sabedoria=10))
    iniciar_combate(["Sonael", "Helena", "Goblin"])
    memory.campaign["combat_state"]["turn_economy"] = {
        "acao_usada": False, "bonus_usada": False, "movimento_usado": False}
    return memory.campaign


def _vida(quem):
    return memory.campaign["characters"][memory.char_key(quem)]["sheet"]["vida_atual"]


def _habilidades(quem, *habs):
    memory.campaign["characters"][memory.char_key(quem)]["habilidades"] = list(habs)


# ---------------------------------------------------------------------------
# 1. O dado fantasma
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nome", ["Mage Armor", "Canalizar Divindade"])
def test_habilidade_sem_dado_nao_tira_vida(mesa, nome):
    _habilidades("Sonael", _hab(nome))
    antes = _vida("Helena")
    saida = td.use_ability("Sonael", nome, "Helena", end_turn=False)
    assert _vida("Helena") == antes, saida
    assert "1d6" not in saida


def test_sem_dado_a_linha_do_dado_nem_aparece(mesa):
    _habilidades("Sonael", _hab("Mage Armor"))
    saida = td.use_ability("Sonael", "Mage Armor", "Helena", end_turn=False)
    assert "d6:" not in saida and "d6: [" not in saida
    assert "sem mudança na vida" in saida


def test_o_parse_ainda_cai_em_1d6_de_proposito(mesa):
    """A fórmula ilegível continua tendo um padrão — o que mudou é que
    habilidade sem dado não chega mais a ser rolada."""
    assert td._parse_dice("") == (1, 6, 0)


# ---------------------------------------------------------------------------
# 2. Dado que não é dano: o 1d4 da Bênção
# ---------------------------------------------------------------------------

def test_bencao_nao_machuca_quem_recebe(mesa):
    _habilidades("Sonael", _hab("Bless", dado="1d4"))
    antes = _vida("Helena")
    saida = td.use_ability("Sonael", "Bless", "Helena", end_turn=False)
    assert _vida("Helena") == antes
    assert "bônus" in saida          # o dado é rolado e mostrado
    assert "1d4" in saida


def test_o_tipo_do_dado(mesa):
    assert td.efeito_do_dado(_hab("Bless", dado="1d4")) == "bonus"
    assert td.efeito_do_dado(_hab("Fireball")) == "dano"
    assert td.efeito_do_dado(_hab("Cure Wounds")) == "cura"
    assert td.efeito_do_dado(_hab("Canalizar Divindade")) == "nenhum"
    assert td.efeito_do_dado(_hab("Sleep")) == "pool"
    assert td.efeito_do_dado(_hab("Hold Person")) == "condicao"


# ---------------------------------------------------------------------------
# 3. O dado que estava no texto do SRD
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nome,esperado", [
    ("Fireball", "8d6"),
    ("Magic Missile", "1d4+1"),
    ("Inflict Wounds", "3d10"),
    ("Cure Wounds", "1d8"),
    ("Segunda Fôlego", "1d10"),
    ("Sleep", "5d8"),              # o pool vem da tabela do motor
])
def test_dado_lido_do_texto(nome, esperado):
    assert td.dado_efetivo(_hab(nome)) == esperado


def test_bonus_de_ataque_nao_e_dado_de_dano():
    """"add 1d4 to the attack roll" não é dano — é o erro que fazia a Bênção
    ferir o aliado."""
    assert td.dado_de_dano_no_texto(SRD["Bless"]) == ""
    assert td.dado_de_dano_no_texto(SRD["Fireball"]) == "8d6"


def test_cura_lida_em_ingles():
    """O SRD escreve "regains a number of hit points", sem "cura" nem "heal"."""
    assert td._is_healing_ability(_hab("Cure Wounds"))
    assert td.dado_de_cura_no_texto(SRD["Cure Wounds"]) == "1d8"


def test_inflict_wounds_causa_o_dano_do_srd(mesa):
    _habilidades("Sonael", _hab("Inflict Wounds"))
    antes = _vida("Goblin")
    td.use_ability("Sonael", "Inflict Wounds", "Goblin", end_turn=False)
    assert antes - _vida("Goblin") >= 3        # 3d10, nunca 1d6 de 1


def test_segundo_folego_cura_em_vez_de_ferir(mesa):
    _habilidades("Helena", _hab("Segunda Fôlego", custo=0))
    mesa["combat_state"]["current_turn_index"] = 1          # a vez é dela
    antes = _vida("Helena")
    saida = td.use_ability("Helena", "Segunda Fôlego", "Helena", end_turn=False)
    assert _vida("Helena") > antes, saida


# ---------------------------------------------------------------------------
# 4. A salvaguarda que o mestre não pediu
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nome,atributo", [
    ("Fireball", "destreza"), ("Hold Person", "sabedoria"), ("Bless", ""),
])
def test_salvaguarda_lida_do_texto(nome, atributo):
    assert td.salvaguarda_da_habilidade(_hab(nome)) == atributo


def test_npc_faz_o_teste_sozinho(mesa):
    _habilidades("Sonael", _hab("Fireball", custo=6))
    random.seed(11)
    saida = td.use_ability("Sonael", "Fireball", "Goblin", end_turn=False)
    assert "salvaguarda de DES" in saida
    assert "CD" in saida


def test_passar_no_teste_da_metade_do_dano(mesa):
    """A conta tem de CHEGAR na vida, não só no texto."""
    import re
    _habilidades("Sonael", _hab("Fireball", custo=6))
    metades, cheios = [], []
    for semente in range(40):
        goblin = memory.campaign["characters"]["goblin"]
        goblin["sheet"]["vida_atual"] = goblin["sheet"]["vida_max"] = 300
        memory.campaign["characters"]["sonael"]["sheet"]["mana_atual"] = 20
        random.seed(semente)
        saida = td.use_ability("Sonael", "Fireball", "Goblin", end_turn=False)
        perdeu = 300 - _vida("Goblin")
        rolado = int(re.search(r"= \*\*(\d+)\*\*", saida).group(1))
        if "metade do dano" in saida:
            metades.append((rolado, perdeu))
        elif "dano cheio" in saida:
            cheios.append((rolado, perdeu))
    assert metades and cheios, f"metades={len(metades)} cheios={len(cheios)}"
    for rolado, perdeu in metades:
        assert perdeu == rolado // 2, f"passou na salvaguarda e perdeu {perdeu} de {rolado}"
    for rolado, perdeu in cheios:
        assert perdeu == rolado, f"falhou na salvaguarda e perdeu {perdeu} de {rolado}"


def test_condicao_so_pega_quem_falha(mesa):
    _habilidades("Sonael", _hab("Hold Person", custo=4))
    resistiu = False
    for semente in range(30):
        goblin = memory.campaign["characters"]["goblin"]
        goblin["sheet"]["condicoes"] = []
        memory.campaign["characters"]["sonael"]["sheet"]["mana_atual"] = 20
        random.seed(semente)
        saida = td.use_ability("Sonael", "Hold Person", "Goblin", end_turn=False)
        if "resistiu" in saida:
            resistiu = True
            assert goblin["sheet"]["condicoes"] == []
    assert resistiu, "ninguém resistiu em 30 tentativas"


def test_alvo_do_grupo_e_quem_rola(mesa):
    """Contra personagem do jogador o dado é dele: o motor PARA e pede."""
    _habilidades("Sonael", _hab("Fireball", custo=6))
    antes = _vida("Helena")
    saida = td.use_ability("Sonael", "Fireball", "Helena", end_turn=False)
    assert _vida("Helena") == antes
    assert "AGUARDANDO TESTE DE RESISTÊNCIA" in saida
    assert "Destreza" in saida


def test_o_mestre_que_pede_o_teste_continua_mandando(mesa):
    _habilidades("Sonael", _hab("Fireball", custo=6))
    antes = _vida("Goblin")
    saida = td.use_ability("Sonael", "Fireball", "Goblin",
                           saving_throw_stat="destreza", saving_throw_dc=15,
                           end_turn=False)
    assert "AGUARDANDO TESTE DE RESISTÊNCIA" in saida
    assert "CD: 15" in saida
    assert _vida("Goblin") == antes          # nada aplicado: ele vai resolver


def test_magia_sem_salvaguarda_nao_inventa_teste(mesa):
    _habilidades("Sonael", _hab("Magic Missile"))
    saida = td.use_ability("Sonael", "Magic Missile", "Goblin", end_turn=False)
    assert "salvaguarda" not in saida
    assert _vida("Goblin") < 25              # dardos não erram


# ---------------------------------------------------------------------------
# 5. O que learn_spell passa a gravar (a API não entrega pronto)
# ---------------------------------------------------------------------------

class _RespostaFalsa:
    """O que a API do Open5e devolve de verdade para uma magia — conferido
    contra api.open5e.com: `damage` é nulo em TODAS elas."""

    def __init__(self, corpo):
        self._corpo = corpo
        self.ok = True

    def json(self):
        return self._corpo


FIREBALL_SRD = {
    "name": "Fireball", "spell_level": 3, "level_int": 3, "school": "Evocation",
    "range": "150 feet", "duration": "Instantaneous", "concentration": "no",
    "requires_concentration": False, "ritual": "no", "damage": None,
    "dnd_class": "Sorcerer, Wizard",
    "desc": ("A bright streak flashes from your pointing finger. Each creature in a "
             "20-foot-radius sphere centered on that point must make a dexterity saving "
             "throw. A target takes 8d6 fire damage on a failed save, or half as much "
             "damage on a successful one."),
    "higher_level": "When you cast this spell using a spell slot of 4th level or higher, "
                    "the damage increases by 1d6 for each slot level above 3rd.",
}


def test_learn_spell_le_o_dado_e_a_salvaguarda_do_texto(mesa, monkeypatch):
    """A API não entrega dado nem salvaguarda; eles estão no texto."""
    from rpg import open5e
    monkeypatch.setattr(open5e.http, "get",
                        lambda *a, **k: _RespostaFalsa(FIREBALL_SRD))
    memory.campaign["characters"]["sonael"]["sheet"]["nivel"] = 9
    memory.campaign["characters"]["sonael"]["habilidades"] = []

    saida = td.learn_spell("Sonael", "fireball")
    assert "8d6" in saida

    magia = memory.campaign["characters"]["sonael"]["habilidades"][-1]
    assert magia["dado"] == "8d6"
    assert magia["salvaguarda"] == "destreza"
    assert magia["concentracao"] is False
    assert magia["alcance"] == "150 feet"
    assert magia["nivel_magia"] == 3


def test_learn_spell_le_a_cura_do_texto(mesa, monkeypatch):
    from rpg import open5e
    cura = dict(FIREBALL_SRD, name="Cure Wounds", spell_level=1, school="Evocation",
                range="Touch", dnd_class="Cleric, Druid, Paladin, Ranger, Bard",
                desc="A creature you touch regains a number of hit points equal to 1d8 + "
                     "your spellcasting ability modifier.",
                higher_level="")
    monkeypatch.setattr(open5e.http, "get", lambda *a, **k: _RespostaFalsa(cura))
    memory.campaign["characters"]["sonael"]["sheet"]["classe"] = "clerigo"
    memory.campaign["characters"]["sonael"]["habilidades"] = []

    td.learn_spell("Sonael", "cure wounds")
    magia = memory.campaign["characters"]["sonael"]["habilidades"][-1]
    assert magia["dado"] == "1d8"
    assert "salvaguarda" not in magia       # cura não tem teste de resistência


def test_concentracao_vira_campo_e_nao_so_palavra():
    import inspect
    assert '"concentracao": bool(' in inspect.getsource(td.learn_spell)
