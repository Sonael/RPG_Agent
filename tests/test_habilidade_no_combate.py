"""
test_habilidade_no_combate.py

O que o jogador viu numa partida, e o que mudou no motor.

  "na tela de combate as magias vinham repetidas e algumas nem tinham dados;
   no mobile não dá nem pra ver se ela dá dano, cura… usei uma magia que não
   tinha descrição e sem querer ataquei os meus companheiros."

As causas, todas confirmadas com as habilidades reais de uma clériga:
  • a tela mostrava o `dado` cru da ficha; o motor rolava outro;
  • "Truque Bônus (Chamas Sagradas)" é a mesma Chama Sagrada;
  • uma magia que só fere criaturas HOSTIS era tratada como indiscriminada.

O fogo amigo continua sendo regra do jogo: a Bola de Fogo pega quem estiver
na esfera. O que mudou é que ele só acontece nas magias em que a regra manda,
e nunca sem aviso.
"""
import random

import pytest

from rpg import habilidade, memory, tools_dnd as td

from conftest import criar_ficha, iniciar_combate

RADIANCIA = {
    "nome": "Canalizar Divindade (Radiância do Amanhecer)", "dado": "2d10",
    "custo_mana": 0,
    "descricao": "Ação: esfera de luz 9m raio; criaturas hostis fazem save de CON "
                 "ou 2d10+nv. dano radiante.",
}
FOGO = {"nome": "Fireball", "dado": "8d6", "custo_mana": 4, "alcance": "150 feet",
        "descricao": "Each creature in a 20-foot-radius sphere ... dexterity saving throw."}
GUARDIOES = {"nome": "Spirit Guardians", "custo_mana": 5, "alcance": "Self",
             "descricao": "You call forth spirits to protect you."}


@pytest.fixture
def mesa(campanha, povoar):
    povoar(criar_ficha("Selene", grupo=True, nivel=5, classe="clérigo", vida=40))
    povoar(criar_ficha("Helena", grupo=True, nivel=5, vida=40))
    povoar(criar_ficha("Goblin A", vida=30))
    povoar(criar_ficha("Goblin B", vida=30))
    sel = memory.campaign["characters"]["selene"]
    sel["sheet"]["mana_atual"] = sel["sheet"]["mana_max"] = 40
    sel["habilidades"] = [dict(RADIANCIA), dict(FOGO), dict(GUARDIOES)]
    iniciar_combate(["Selene", "Helena", "Goblin A", "Goblin B"])
    td.set_battlefield("Pátio, Sacada")
    return memory.campaign


def _zonas(**quem):
    for nome, zona in quem.items():
        td._por_zona(nome.replace("_", " "), zona)


def _vida(nome):
    return memory.campaign["characters"][memory.char_key(nome)]["sheet"]["vida_atual"]


# ---------------------------------------------------------------------------
# 1. Fogo amigo só onde a regra manda
# ---------------------------------------------------------------------------

def test_magia_que_so_fere_hostis_poupa_a_aliada(mesa):
    """O caso da partida: aliada e inimigos na mesma zona."""
    _zonas(Selene="Pátio", Helena="Sacada", Goblin_A="Sacada", Goblin_B="Sacada")
    random.seed(4)
    td.use_ability("Selene", RADIANCIA["nome"], target_name="Goblin A", end_turn=False)
    assert _vida("Helena") == 40, "a aliada foi atingida por magia que só fere hostis"
    assert _vida("Goblin A") < 30 and _vida("Goblin B") < 30


def test_a_bola_de_fogo_continua_queimando_aliado(mesa):
    """O fogo amigo é regra do jogo e NÃO pode ter sumido junto com o defeito."""
    _zonas(Selene="Pátio", Helena="Sacada", Goblin_A="Sacada", Goblin_B="Sacada")
    random.seed(4)
    td.use_ability("Selene", "Fireball", target_name="Goblin A", end_turn=False)
    assert _vida("Helena") < 40, "a Bola de Fogo deixou de pegar quem estava na esfera"


def test_espiritos_guardioes_poupam_os_aliados_da_zona(mesa):
    """Você designa quem fica de fora — e ninguém deixaria a aliada dentro."""
    _zonas(Selene="Pátio", Helena="Pátio", Goblin_A="Pátio", Goblin_B="Sacada")
    random.seed(4)
    td.use_ability("Selene", "Spirit Guardians", target_name="", end_turn=False)
    assert _vida("Helena") == 40
    assert _vida("Goblin A") < 30
    assert _vida("Goblin B") == 30, "atravessou para a outra zona"


# ---------------------------------------------------------------------------
# 2. O aviso antes de confirmar
# ---------------------------------------------------------------------------

def test_a_previa_aponta_a_aliada_na_bola_de_fogo(mesa):
    _zonas(Selene="Pátio", Helena="Sacada", Goblin_A="Sacada", Goblin_B="Sacada")
    p = td.prever_area("Selene", "Fireball", "Goblin A")
    assert p["ok"] and p["alvos"] == "todos"
    assert p["aliados_atingidos"] == ["Helena"]
    assert sorted(a["nome"] for a in p["atingidos"]) == ["Goblin A", "Goblin B", "Helena"]


def test_a_previa_da_radiancia_nao_aponta_aliado(mesa):
    _zonas(Selene="Pátio", Helena="Sacada", Goblin_A="Sacada", Goblin_B="Sacada")
    p = td.prever_area("Selene", RADIANCIA["nome"], "Goblin A")
    assert p["alvos"] == "hostis" and p["aliados_atingidos"] == []


def test_a_previa_nao_gasta_nada(mesa):
    _zonas(Selene="Pátio", Helena="Sacada", Goblin_A="Sacada", Goblin_B="Sacada")
    mana = memory.campaign["characters"]["selene"]["sheet"]["mana_atual"]
    td.prever_area("Selene", "Fireball", "Goblin A")
    assert memory.campaign["characters"]["selene"]["sheet"]["mana_atual"] == mana
    assert _vida("Goblin A") == 30


def test_o_servidor_abre_a_rota_da_previa():
    import server
    assert "/api/combat/preview" in {str(r) for r in server.app.url_map.iter_rules()}


# ---------------------------------------------------------------------------
# 3. O que a tela recebe é o que o motor faz
# ---------------------------------------------------------------------------

def _botao(nome_exibido):
    estado = td.combat_snapshot()
    sel = next(c for c in estado["combatants"] if c["name"] == "Selene")
    return next(h for h in sel["habilidades"] if h["nome_exibido"] == nome_exibido)


def test_a_tela_mostra_o_dado_que_o_motor_rola(mesa):
    """Infligir Ferimentos aparecia SEM DADO na tela e rolava 3d10 no motor."""
    memory.campaign["characters"]["selene"]["habilidades"].append(
        {"nome": "Inflict Wounds", "dado": "", "custo_mana": 2, "alcance": "Touch",
         "descricao": "[Necromancy] Make a melee spell attack. 3d10 necrotic damage."})
    b = _botao("Infligir Ferimentos")
    assert b["dado"] == "3d10"
    assert b["dado"] == td.dado_efetivo(
        memory.campaign["characters"]["selene"]["habilidades"][-1],
        memory.campaign["characters"]["selene"])


def test_a_tela_recebe_o_que_a_magia_faz(mesa):
    """No celular não havia como saber se a magia causava dano ou curava."""
    b = _botao("Bola de Fogo")
    assert b["rotulo"] == "Dano"
    assert "8d6" in b["resumo"] and "TODOS na área, aliados inclusive" in b["resumo"]
    assert b["alvos"] == "todos" and b["area"]


def test_a_tela_chama_a_habilidade_pelo_nome_da_ficha(mesa):
    """O motor procura pelo nome da ficha; o nome oficial é só o que aparece."""
    b = _botao("Bola de Fogo")
    assert b["nome"] == "Fireball"


def test_a_mesma_magia_nao_aparece_duas_vezes(mesa):
    memory.campaign["characters"]["selene"]["habilidades"] += [
        {"nome": "Chamas Sagradas", "dado": "1d8", "custo_mana": 0, "descricao": "Truque."},
        {"nome": "Truque Bônus (Chamas Sagradas)", "dado": "1d8", "custo_mana": 0,
         "descricao": "Aprende Chamas Sagradas."},
    ]
    estado = td.combat_snapshot()
    sel = next(c for c in estado["combatants"] if c["name"] == "Selene")
    nomes = [h["nome_exibido"] for h in sel["habilidades"]]
    assert nomes.count("Chama Sagrada") == 1, nomes


def test_efeitos_diferentes_do_mesmo_recurso_nao_sao_duplicata(mesa):
    """A Radiância é um efeito do Canalizar Divindade, não uma cópia dele."""
    memory.campaign["characters"]["selene"]["habilidades"].append(
        {"nome": "Canalizar Divindade", "dado": "", "custo_mana": 0,
         "descricao": "Ação: usa Expulsar Mortos-Vivos ou um efeito do seu domínio."})
    estado = td.combat_snapshot()
    sel = next(c for c in estado["combatants"] if c["name"] == "Selene")
    nomes = [h["nome_exibido"] for h in sel["habilidades"]]
    assert RADIANCIA["nome"] in nomes and "Canalizar Divindade" in nomes


def test_a_radiancia_fora_do_srd_diz_o_que_faz(mesa):
    r = habilidade.resolver(dict(RADIANCIA), memory.campaign["characters"]["selene"])
    assert r["resumo"] == "Dano 2d10 radiante · CON · raio de 9 m · só inimigos"


# ---------------------------------------------------------------------------
# 4. Regras que o compêndio corrigiu no motor
# ---------------------------------------------------------------------------

def test_palavra_curativa_gasta_a_acao_bonus():
    """A lista de nomes não a conhecia, e a tela tática gastava a ação inteira."""
    assert td._ability_action_type("Healing Word", {"nome": "Healing Word"}) == "bonus"
    assert td._ability_action_type("Palavra Curativa", {"nome": "Palavra Curativa"}) == "bonus"


def test_o_truque_cresce_com_o_nivel(campanha, povoar):
    povoar(criar_ficha("Vex", grupo=True, nivel=5, classe="mago"))
    vex = memory.campaign["characters"]["vex"]
    hab = {"nome": "Fire Bolt", "dado": "1d10"}
    assert td.dado_efetivo(hab, vex) == "2d10"
    vex["sheet"]["nivel"] = 1
    assert td.dado_efetivo(hab, vex) == "1d10"


def test_magia_de_condicao_fora_da_tabela_antiga_aplica_a_condicao(mesa):
    """
    CONTROL_SPELL_EFFECTS tem 30 magias; o SRD tem 47 de condição. As outras
    caíam no ramo de DANO, com dado vazio, e a condição nunca era aplicada.
    """
    memory.campaign["characters"]["selene"]["habilidades"].append(
        {"nome": "Hideous Laughter", "custo_mana": 2, "dado": "",
         "descricao": "A creature of your choice falls prone."})
    _zonas(Selene="Pátio", Helena="Pátio", Goblin_A="Pátio", Goblin_B="Sacada")
    alvo = memory.campaign["characters"]["goblin a"]
    alvo["sheet"]["sabedoria"] = 1          # garante que falhe a salvaguarda
    random.seed(1)
    saida = td.use_ability("Selene", "Hideous Laughter", target_name="Goblin A", end_turn=False)
    assert _vida("Goblin A") == 30, saida
    conds = [c["nome"].lower() for c in alvo["sheet"].get("condicoes") or []]
    assert "caído" in conds, (conds, saida)


def test_canalizar_divindade_do_paladino_tem_um_uso(campanha, povoar):
    povoar(criar_ficha("Arthur", grupo=True, nivel=6, classe="paladino"))
    arthur = memory.campaign["characters"]["arthur"]
    assert td.usos_maximos(arthur, "Canalizar Divindade") == 1
    povoar(criar_ficha("Mira", grupo=True, nivel=6, classe="clérigo"))
    assert td.usos_maximos(memory.campaign["characters"]["mira"], "Canalizar Divindade") == 2
