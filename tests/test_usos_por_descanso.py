"""
test_usos_por_descanso.py

O guerreiro usava Surto de Ação em todo turno.

Mana já era recurso: `custo_mana` era descontado e o descanso longo devolvia.
As habilidades de classe do SRD que NÃO custam mana — Surto de Ação, Fúria,
Segunda Fôlego, Canalizar Divindade — ficavam de fora, e são justamente as
que definem o ritmo do dia de aventura. A descrição dizia "1 uso por descanso
curto"; isso era texto para o mestre ler, e nada no motor cobrava.

Agora o que sobra de cada uma mora em sheet["usos"]. Ausente = cheio: ficha
antiga entra neste mundo com tudo disponível e sem migração nenhuma.
"""
import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _guerreiro(nivel=5):
    ch = criar_ficha("Bran", grupo=True, nivel=nivel, classe="guerreiro", vida=40)
    ch["habilidades"] = [
        {"nome": "Surto de Ação", "descricao": "1 uso por descanso curto.",
         "custo_mana": 0, "dado": ""},
        {"nome": "Segunda Fôlego", "descricao": "Recupera 1d10 + nível de PV.",
         "custo_mana": 0, "dado": "1d10"},
    ]
    return ch


@pytest.fixture
def bran(campanha, povoar):
    povoar(_guerreiro())
    return memory.campaign["characters"]["bran"]


# ---------------------------------------------------------------------------
# 1. Quantos usos cada habilidade tem
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nome, nivel, esperado", [
    ("Surto de Ação", 5, 1),
    ("Surto de Ação", 17, 2),          # Surto de Ação Adicional
    ("Segunda Fôlego", 5, 1),
    ("Fúria", 1, 2),
    ("Fúria", 3, 3),
    ("Fúria", 6, 4),
    ("Fúria", 12, 5),
    ("Fúria", 17, 6),
    ("Canalizar Divindade", 2, 1),
    ("Canalizar Divindade", 6, 2),
    ("Canalizar Divindade", 18, 3),
])
def test_a_tabela_do_srd(nome, nivel, esperado):
    char = {"sheet": {"nivel": nivel}}
    assert td.usos_maximos(char, nome) == esperado


def test_habilidade_livre_nao_tem_contador():
    """Magia é cobrada em mana; ataque não é cobrado em nada. Só a tabela conta."""
    char = {"sheet": {"nivel": 5}}
    assert td.usos_maximos(char, "Fireball") is None
    assert td.usos_restantes(char, "Fireball") is None


def test_os_efeitos_de_canalizar_dividem_o_mesmo_recurso():
    """
    "Canalizar Divindade (Arma Sagrada)" e "(Preservar Vida)" são efeitos do
    MESMO poder: conhecer dois não dá dois usos.
    """
    assert td._chave_de_uso("Canalizar Divindade (Arma Sagrada)") == "canalizar divindade"
    assert td._chave_de_uso("Canalizar Divindade (Preservar Vida)") == "canalizar divindade"


def test_ficha_antiga_nasce_cheia(bran):
    assert "usos" not in bran["sheet"]
    assert td.usos_restantes(bran, "Surto de Ação") == 1


# ---------------------------------------------------------------------------
# 2. Gastar e acabar
# ---------------------------------------------------------------------------

def test_o_surto_acaba_depois_de_um_uso(bran):
    iniciar_combate(["Bran"])
    r = td.use_ability("Bran", "Surto de Ação", end_turn=False)
    assert "Erro" not in r, r
    assert td.usos_restantes(bran, "Surto de Ação") == 0
    assert "Usos: 0/1" in r


def test_usar_de_novo_e_recusado_e_diz_qual_descanso(bran):
    iniciar_combate(["Bran"])
    td.use_ability("Bran", "Surto de Ação", end_turn=False)
    r = td.use_ability("Bran", "Surto de Ação", end_turn=False)
    assert r.startswith("Erro:")
    assert "descanso curto" in r and "short_rest" in r


def test_a_recusa_nao_cobra_nada(campanha, povoar):
    """Recusar depois de descontar deixaria o custo pago por ação que não houve."""
    ch = _guerreiro()
    ch["habilidades"].append({"nome": "Fúria", "descricao": "Ação bônus.",
                              "custo_mana": 3, "dado": ""})
    ch["sheet"]["classe"] = "barbaro"
    ch["sheet"]["mana_atual"] = ch["sheet"]["mana_max"] = 20
    ch["sheet"]["usos"] = {"furia": 0}
    povoar(ch)
    iniciar_combate(["Bran"])

    r = td.use_ability("Bran", "Fúria", end_turn=False)
    assert r.startswith("Erro:")
    assert memory.campaign["characters"]["bran"]["sheet"]["mana_atual"] == 20


def test_a_furia_do_barbaro_conta_pelo_nivel(campanha, povoar):
    ch = criar_ficha("Ulf", grupo=True, nivel=6, classe="barbaro", vida=60)
    ch["habilidades"] = [{"nome": "Fúria", "descricao": "Ação bônus.",
                          "custo_mana": 0, "dado": ""}]
    povoar(ch)
    iniciar_combate(["Ulf"])
    ulf = memory.campaign["characters"]["ulf"]
    for esperado in (3, 2, 1, 0):
        r = td.use_ability("Ulf", "Fúria", end_turn=False)
        assert "Erro" not in r, r
        assert td.usos_restantes(ulf, "Fúria") == esperado
    assert td.use_ability("Ulf", "Fúria", end_turn=False).startswith("Erro:")


# ---------------------------------------------------------------------------
# 3. O descanso devolve
# ---------------------------------------------------------------------------

def test_o_descanso_curto_devolve_o_surto(bran):
    iniciar_combate(["Bran"])
    td.use_ability("Bran", "Surto de Ação", end_turn=False)
    memory.campaign["combat_state"]["is_active"] = False

    r = td.short_rest("Bran", hit_dice=0)

    assert td.usos_restantes(bran, "Surto de Ação") == 1
    assert "Recuperado" in r


def test_o_descanso_curto_nao_devolve_a_furia(campanha, povoar):
    """A Fúria volta só no descanso LONGO — é o que segura o dia de aventura."""
    ch = criar_ficha("Ulf", grupo=True, nivel=5, classe="barbaro", vida=60)
    ch["habilidades"] = [{"nome": "Fúria", "descricao": "Ação bônus.",
                          "custo_mana": 0, "dado": ""}]
    ch["sheet"]["usos"] = {"furia": 0}
    povoar(ch)

    td.short_rest("Ulf", hit_dice=0)

    assert td.usos_restantes(memory.campaign["characters"]["ulf"], "Fúria") == 0


def test_o_descanso_longo_devolve_tudo(campanha, povoar):
    ch = criar_ficha("Ulf", grupo=True, nivel=5, classe="barbaro", vida=60)
    ch["habilidades"] = [{"nome": "Fúria", "descricao": "Ação bônus.",
                          "custo_mana": 0, "dado": ""}]
    ch["sheet"]["usos"] = {"furia": 0, "surto de acao": 0}
    povoar(ch)

    td.long_rest("Ulf")

    ulf = memory.campaign["characters"]["ulf"]
    assert ulf["sheet"].get("usos") in ({}, None)
    assert td.usos_restantes(ulf, "Fúria") == 3


# ---------------------------------------------------------------------------
# 4. A tela tática
# ---------------------------------------------------------------------------

def test_a_tela_recebe_o_contador(bran):
    iniciar_combate(["Bran"])
    td.use_ability("Bran", "Surto de Ação", end_turn=False)
    estado = td.combat_snapshot()
    alvo = next(c for c in estado["combatants"] if c["name"] == "Bran")
    surto = next(h for h in alvo["habilidades"] if h["nome"] == "Surto de Ação")
    assert surto["usos"] == 0 and surto["usos_max"] == 1


def test_a_tela_tatica_desenha_o_contador():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "static" / "js" / "combat.js"
          ).read_text(encoding="utf-8")
    assert "usos_max" in js, "a tela não sabe que existe contador"
    assert "h.usos <= 0" in js, "o botão continua clicável com o poder gasto"
