"""
test_regras_e_editores.py

O wizard de criação e os dois editores de ficha (o da campanha, no menu, e o
"Editar Ficha Completa", no jogo) foram escritos antes das telas. Tinham
tabelas de regra próprias no navegador, e elas já discordavam do motor:

    círculo máximo de magia   ceil(nível/2) para toda classe — um paladino de
                              nível 3 recebia magia de 2º círculo
    incremento de atributo    só nos níveis 4, 8, 12, 16 e 19 — o guerreiro
                              também ganha no 6 e no 14, o ladino no 10
    nível da magia inicial    Math.round(custo_mana / 4) — pela tabela atual,
                              3º círculo custa 5 e virava 1º círculo

E gravavam por cima do que as telas controlam: nível, atributos, CA,
equipamento e magias eram campos livres.

Duas mudanças: `rules_catalog` (rota /api/dnd/regras) entrega as tabelas
geradas pelas funções do motor, e o navegador não tem mais as suas; e
`normalize_edited_character` protege a ficha no salvamento.
"""
import copy
import re
from pathlib import Path

import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha

RAIZ = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 1. As tabelas saem do motor
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def regras():
    return td.rules_catalog()


def test_circulo_maximo_do_paladino_e_de_meio_conjurador(regras):
    paladino = regras["classes"]["paladino"]["nivel_max_magia"]
    assert paladino[0] == 0 and paladino[2] == 1 and paladino[4] == 2   # níveis 1, 3, 5


def test_incremento_do_guerreiro_inclui_6_e_14(regras):
    assert {6, 14} <= set(regras["classes"]["guerreiro"]["niveis_asi"])
    assert 10 in regras["classes"]["ladino"]["niveis_asi"]
    assert regras["classes"]["mago"]["niveis_asi"] == [4, 8, 12, 16, 19]


def test_limites_de_magia_batem_com_o_learn_spell(regras):
    for classe, dados in regras["classes"].items():
        for nivel in (1, 5, 20):
            limite = td._limite_de_magias({"classe": classe, "nivel": nivel})
            if limite is None:
                assert dados["magias"] is None, classe
            else:
                assert dados["magias"][nivel - 1] == limite["magias"], (classe, nivel)
                assert dados["truques"][nivel - 1] == limite["truques"], (classe, nivel)


def test_mana_xp_e_proficiencia(regras):
    assert regras["classes"]["mago"]["mana"][4] == td._max_mana_for("mago", 5)
    assert regras["xp_por_nivel"][1] == 300
    assert regras["proficiencia_por_nivel"][4] == 3
    assert regras["custo_mana_por_nivel"]["3"] == 5


def test_rota_das_regras_registrada():
    import server
    assert "/api/dnd/regras" in {r.rule for r in server.app.url_map.iter_rules()}


# ---------------------------------------------------------------------------
# 2. O navegador não tem mais as suas tabelas
# ---------------------------------------------------------------------------

_TABELAS_DO_NAVEGADOR = (
    "SPELL_CANTRIPS_TABLE", "SPELL_KNOWN_TABLE", "SPELL_POINTS_BY_LEVEL_WZ",
    "ED_XP_THRESHOLDS", "ED_PROF_BY_LEVEL", "GAME_XP_THRESHOLDS",
    "GAME_PROF_BY_LEVEL", "GAME_ASI_LEVELS", "FULL_CASTERS_WZ", "HALF_CASTERS_WZ",
)


@pytest.mark.parametrize("arquivo", ["static/js/menu.js", "static/js/game.js"])
def test_js_nao_define_tabela_de_regra(arquivo):
    js = (RAIZ / arquivo).read_text(encoding="utf-8")
    achadas = [t for t in _TABELAS_DO_NAVEGADOR if re.search(rf"\bconst\s+{t}\b", js)]
    assert not achadas, f"{arquivo} voltou a ter tabela de regra própria: {achadas}"


@pytest.mark.parametrize("arquivo", ["static/js/menu.js", "static/js/game.js"])
def test_js_nao_deduz_nivel_da_magia_pelo_custo_dividido_por_quatro(arquivo):
    js = (RAIZ / arquivo).read_text(encoding="utf-8")
    assert not re.search(r"custo_mana\s*\|\|\s*4\)\s*/\s*4", js)


def test_magias_iniciais_do_wizard_tem_nivel_e_custo_do_motor():
    js = (RAIZ / "static/js/menu.js").read_text(encoding="utf-8")
    bloco = js.split("const INITIAL_SPELLS_WZ = {")[1].split("\n};")[0]
    magias = re.findall(r"\{nome:'([^']+)'.*?custo_mana:(\d+).*?nivel_magia:(\d+)", bloco)
    assert len(magias) >= 25, "não achei nivel_magia nas magias iniciais"
    for nome, custo, nivel in magias:
        esperado = td.SPELL_LEVEL_OVERRIDE.get(nome.lower())
        if esperado is not None:
            assert int(nivel) == esperado, (nome, nivel, esperado)
        assert int(custo) == td.SPELL_MANA_COST[int(nivel)], (nome, custo)


# ---------------------------------------------------------------------------
# 3. Proteção no salvamento
# ---------------------------------------------------------------------------

@pytest.fixture
def aria(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True, nivel=4, vida=30, vida_max=30, destreza=12))
    ch = memory.campaign["characters"]["aria"]
    ch["inventario"] = [{"nome": "Cota de Malha", "qtd": 1, "descricao": ""},
                        {"nome": "Tocha", "qtd": 2, "descricao": ""}]
    ch["sheet"]["equipamentos"] = {"armadura": "Cota de Malha", "escudo": None,
                                   "arma_principal": None, "arma_secundaria": None, "amuleto": None}
    td._recalculate_ca(ch)
    ch["habilidades"] = [{"nome": "Segunda Fôlego", "descricao": "", "custo_mana": 0, "dado": ""}]
    return ch


def _editado(ch, **sheet):
    novo = copy.deepcopy(ch)
    novo["sheet"].update(sheet)
    return novo


def test_campos_de_construcao_voltam_ao_gravado(aria):
    novo = _editado(aria, nivel=12, forca=20, ca=25, vida_max=200,
                    equipamentos={"armadura": "Placas"})
    novo["habilidades"].append({"nome": "Bola de Fogo", "descricao": "[Evocação] x", "custo_mana": 5})
    mantidos = td.normalize_edited_character(novo, aria)
    s = novo["sheet"]
    assert (s["nivel"], s["forca"], s["ca"], s["vida_max"]) == (4, 16, 16, 30)
    assert s["equipamentos"]["armadura"] == "Cota de Malha"
    assert [h["nome"] for h in novo["habilidades"]] == ["Segunda Fôlego"]
    assert {"nivel", "forca", "ca", "vida_max", "equipamentos", "habilidades"} <= set(mantidos)


def test_estado_do_momento_continua_editavel(aria):
    novo = _editado(aria, vida_atual=12, ouro=50, mana_atual=3)
    novo["name"] = "Aria, a Rubra"
    novo["notes"] = "deve favor ao ferreiro"
    assert td.normalize_edited_character(novo, aria) == []
    assert novo["sheet"]["vida_atual"] == 12 and novo["sheet"]["ouro"] == 50
    assert novo["name"] == "Aria, a Rubra"


def test_modo_de_correcao_aceita(aria):
    novo = _editado(aria, nivel=12, ca=25)
    assert td.normalize_edited_character(novo, aria, correcao_manual=True) == []
    assert novo["sheet"]["nivel"] == 12 and novo["sheet"]["ca"] == 25


def test_personagem_novo_aceita_a_construcao(campanha):
    novo = criar_ficha("Bram", grupo=True, nivel=7, forca=18)
    assert td.normalize_edited_character(novo, None) == []
    assert novo["sheet"]["nivel"] == 7


def test_npc_nao_e_protegido(campanha, povoar):
    povoar(criar_ficha("Goblin"))
    antigo = memory.campaign["characters"]["goblin"]
    novo = _editado(antigo, ca=15)
    novo["sheet"]["classe"] = "npc"
    antigo["sheet"]["classe"] = "npc"
    assert td.normalize_edited_character(novo, antigo) == []
    assert novo["sheet"]["ca"] == 15


def test_tirar_da_mochila_o_item_vestido_tira_do_corpo(aria):
    novo = copy.deepcopy(aria)
    novo["inventario"] = [i for i in novo["inventario"] if i["nome"] != "Cota de Malha"]
    td.normalize_edited_character(novo, aria)
    assert novo["sheet"]["equipamentos"]["armadura"] is None
    assert novo["sheet"]["ca"] == 11


def test_tirar_da_mochila_tira_do_corpo_tambem_na_correcao(aria):
    novo = copy.deepcopy(aria)
    novo["inventario"] = [i for i in novo["inventario"] if i["nome"] != "Cota de Malha"]
    td.normalize_edited_character(novo, aria, correcao_manual=True)
    assert novo["sheet"]["equipamentos"]["armadura"] is None
    assert novo["sheet"]["ca"] == 11


def test_ca_do_mestre_nao_e_recalculada_sem_motivo(aria):
    """Armadura Arcana posta pelo mestre com set_stat não pode sumir num salvamento."""
    aria["sheet"]["ca"] = 19
    novo = copy.deepcopy(aria)
    novo["notes"] = "só a nota mudou"
    td.normalize_edited_character(novo, aria)
    assert novo["sheet"]["ca"] == 19


def test_coerencia_vale_mesmo_na_correcao(aria):
    novo = _editado(aria, vida_atual=999, mana_atual=999, mana_max=10, hit_dice_remaining=50)
    novo["habilidades"] = [{"nome": "Bola de Fogo", "descricao": "[Evocação] x", "custo_mana": 5}]
    td.normalize_edited_character(novo, aria, correcao_manual=True)
    s = novo["sheet"]
    assert s["vida_atual"] == 30 and s["mana_atual"] == 10 and s["hit_dice_remaining"] == 4
    assert novo["habilidades"][0]["nivel_magia"] == 3


def test_rota_do_editor_da_campanha_protege_e_avisa(monkeypatch):
    """O PUT do editor do menu passa pela proteção e devolve o que manteve."""
    import sys
    sys.path.insert(0, str(RAIZ / "scripts"))
    import capturar_telas as cap
    import server
    from rpg import database

    antiga = {"name": "Teste", "characters": {"aria": criar_ficha("Aria", grupo=True, nivel=4)}}
    cap._instalar_dubles(antiga, "Teste")
    gravado = {}
    monkeypatch.setattr(database, "save_campaign",
                        lambda uid, nome, dados: gravado.update(dados))
    try:
        editada = copy.deepcopy(antiga)
        editada["characters"]["aria"]["sheet"]["nivel"] = 15
        editada["characters"]["aria"]["sheet"]["vida_atual"] = 3
        r = server.app.test_client().put(
            "/api/campaigns/Teste", json={"campaign": editada},
            headers={"Authorization": f"Bearer {cap.TOKEN}"})
        corpo = r.get_json()
        assert r.status_code == 200, corpo
        assert corpo["mantidos"] == {"Aria": ["nivel"]}
        assert gravado["characters"]["aria"]["sheet"]["nivel"] == 4
        assert gravado["characters"]["aria"]["sheet"]["vida_atual"] == 3

        editada["characters"]["aria"]["correcao_manual"] = True
        server.app.test_client().put(
            "/api/campaigns/Teste", json={"campaign": editada},
            headers={"Authorization": f"Bearer {cap.TOKEN}"})
        assert gravado["characters"]["aria"]["sheet"]["nivel"] == 15
        assert "correcao_manual" not in gravado["characters"]["aria"]
    finally:
        cap._remover_dubles()


def test_flag_de_correcao_nao_e_gravada(aria):
    novo = copy.deepcopy(aria)
    novo["correcao_manual"] = True
    td.normalize_edited_character(novo, aria, correcao_manual=True)
    assert "correcao_manual" not in novo
