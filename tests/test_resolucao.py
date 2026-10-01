"""
test_resolucao.py

"Isso faz alguma coisa no combate?" — a pergunta do jogador sobre a
Taumaturgia, o Sacerdote de Guerra e a Ação Ardilosa. Medido com as fichas da
campanha dele, a resposta era não para quase metade das habilidades: gastavam
a Ação e o motor respondia "usa X no Orc!". A Bênção rolava 1d4 e o número
não entrava em ataque nenhum; o Ataque Furtivo não existia; magia de ataque
nunca errava; o primeiro da iniciativa começava a luta sem Ação.

Cada teste abaixo prende uma dessas respostas.
"""
import random

import pytest

from rpg import memory, resolucao, tools_dnd as td, tools

from conftest import criar_ficha, iniciar_combate

TIPOS = {"motor", "efeito", "acao_de_classe", "passiva", "narrativa"}


def _hab(nome, **kw):
    return {"nome": nome, "descricao": kw.pop("descricao", ""), "custo_mana": kw.pop("custo", 0),
            "dado": kw.pop("dado", ""), **kw}


def _ch(nome):
    return memory.campaign["characters"][memory.char_key(nome)]


def _vida(nome):
    return _ch(nome)["sheet"]["vida_atual"]


def _d20(monkeypatch, valor):
    monkeypatch.setattr(td, "_roll_d20_with_adv",
                        lambda a, d: (valor, f"d20={valor}{' (vant)' if a and not d else ''}"
                                      f"{' (desv)' if d and not a else ''}"))


@pytest.fixture
def luta(campanha, povoar):
    povoar(criar_ficha("Kaelen", grupo=True, classe="clérigo", nivel=3, sabedoria=16, vida=30),
           criar_ficha("Lyra", grupo=True, classe="ladino", nivel=3, destreza=18, vida=25,
                       arma="adaga"),
           criar_ficha("Alden", grupo=True, classe="guerreiro", nivel=5, vida=40),
           criar_ficha("Orc", vida=60, ca=13),
           criar_ficha("Orc B", vida=60, ca=13))
    iniciar_combate(["Kaelen", "Lyra", "Alden", "Orc", "Orc B"])
    td._reset_turn_economy(memory.campaign["combat_state"])
    return memory.campaign


def _vez(nome):
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index(nome)
    td._reset_turn_economy(cs)


def _dar(nome, *habs):
    _ch(nome)["habilidades"] = list(habs)


# ---------------------------------------------------------------------------
# 1. Toda habilidade tem resposta
# ---------------------------------------------------------------------------

def _nomes_de_jogo():
    return sorted(n for n in td.CLASS_FEATURE_DESCS if n)


def test_toda_caracteristica_do_jogo_tem_resposta():
    """As 326 que as fichas do jogo usam: nenhuma fica sem tratamento."""
    sem = [n for n in _nomes_de_jogo() if resolucao.tipo_de_caracteristica(n)[0] not in TIPOS]
    assert not sem, sem
    assert len(_nomes_de_jogo()) >= 300


def test_toda_magia_do_srd_tem_resposta():
    from rpg import compendio
    tipos = {}
    for m in compendio.magias().values():
        r = resolucao.como_resolve({"nome": m["nome_srd"], "custo_mana": 1, "dado": ""})
        assert r["tipo"] in TIPOS, m["nome_srd"]
        tipos.setdefault(r["tipo"], []).append(m["nome_srd"])
    # Nenhuma magia vira "passiva": magia se conjura.
    assert "passiva" not in tipos
    assert "Bless" in tipos["efeito"] and "Fireball" in tipos["motor"]
    assert "Thaumaturgy" in tipos["narrativa"]


@pytest.mark.parametrize("nome, tipo", [
    ("Thaumaturgy", "narrativa"),
    ("Taumaturgia", "narrativa"),
    ("Sacerdote de Guerra", "acao_de_classe"),
    ("Ação Ardilosa", "acao_de_classe"),
    ("Canalizar Divindade", "acao_de_classe"),
    ("Canalizar Divindade (Guiar Ataque)", "acao_de_classe"),
    ("Fúria", "acao_de_classe"),
    ("Bless", "efeito"),
    ("Conjuração", "passiva"),
    ("Ataque Furtivo", "passiva"),
    ("Estilo de Combate", "passiva"),
    ("Linguagem dos Ladrões", "passiva"),
    ("Segunda Fôlego", "motor"),
    ("Guiding Bolt", "motor"),
])
def test_cada_habilidade_da_partida(nome, tipo):
    """As habilidades das fichas da campanha em que o problema apareceu."""
    hab = _hab(nome, descricao="Aprende cifra secreta usada por ladinos."
               if nome == "Linguagem dos Ladrões" else "")
    assert resolucao.como_resolve(hab)["tipo"] == tipo


# ---------------------------------------------------------------------------
# 2. Passiva não se usa; narrativa gasta e chama o Mestre
# ---------------------------------------------------------------------------

def test_ataque_furtivo_nao_e_mais_um_golpe_solto(luta):
    """A tela deixava "usar" o Ataque Furtivo, e ele rolava 1d6 de dano solto."""
    _dar("Lyra", _hab("Ataque Furtivo", dado="1d6"))
    _vez("Lyra")
    r = td.combat_action("ability", actor="Lyra", ability="Ataque Furtivo", target="Orc")
    assert not r["ok"] and _vida("Orc") == 60
    assert not memory.campaign["combat_state"]["turn_economy"]["acao_usada"]


def test_taumaturgia_gasta_a_acao_e_chama_o_mestre(luta):
    _dar("Kaelen", _hab("Thaumaturgy", descricao="[Truque] Manifesta um prodígio menor."))
    _vez("Kaelen")
    r = td.combat_action("ability", actor="Kaelen", ability="Thaumaturgy", target="")
    assert r["ok"] and r.get("narrar") is True
    assert "o Mestre narra" in r["message"]
    assert memory.campaign["combat_state"]["turn_economy"]["acao_usada"]


# ---------------------------------------------------------------------------
# 3. Efeitos: o número entra no ataque, na CA, na salvaguarda
# ---------------------------------------------------------------------------

def test_bencao_soma_no_ataque(luta, monkeypatch):
    _dar("Kaelen", _hab("Bless", custo=2, descricao="Concentração."))
    _vez("Kaelen")
    td.use_ability("Kaelen", "Bless", "Alden", end_turn=False)
    bencao = [e for e in td._efeitos(_ch("Alden")["sheet"]) if e["nome"] == "Bênção"]
    assert bencao
    _d20(monkeypatch, 10)
    monkeypatch.setattr(td, "_rolar_expr", lambda e: (4, "1d4=+4") if "d4" in str(e) else (0, ""))
    _vez("Alden")
    saida = td.attack_roll("Alden", "Orc", "espada longa", 8, end_turn=False)
    # d20 10 + FOR 3 + proficiência 2 + Bênção 4: o 4 entra na SOMA.
    assert "+4(efeitos)" in saida and "Bênção" in saida
    assert "= **19**" in saida, saida


def test_bencao_cai_com_a_concentracao(luta):
    _dar("Kaelen", _hab("Bless", custo=2, descricao="Concentração."))
    _vez("Kaelen")
    td.use_ability("Kaelen", "Bless", "Alden", end_turn=False)
    td._break_concentration(_ch("Kaelen"), "dano")
    assert not [e for e in td._efeitos(_ch("Alden")["sheet"]) if e["nome"] == "Bênção"]


def test_escudo_da_fe_sobe_a_ca(luta):
    _dar("Kaelen", _hab("Shield of Faith", custo=2, descricao="Concentração."))
    _vez("Kaelen")
    antes = td._ca_efetiva(_ch("Alden"))
    td.use_ability("Kaelen", "Shield of Faith", "Alden", end_turn=False)
    assert td._ca_efetiva(_ch("Alden")) == antes + 2


def test_esquivar_impoe_desvantagem_ate_o_proximo_turno(luta, monkeypatch):
    _vez("Alden")
    r = td.combat_action("defend", actor="Alden")
    assert "desvantagem" in r["message"]
    mods = td._mods_de_ataque(_ch("Orc"), _ch("Alden"), True)
    assert mods["desvantagem"]
    # No próximo turno de Alden a Esquiva acaba.
    _vez("Alden")
    assert not td._mods_de_ataque(_ch("Orc"), _ch("Alden"), True)["desvantagem"]


def test_furia_soma_dano_e_resiste(luta, monkeypatch):
    _ch("Alden")["sheet"]["classe"] = "bárbaro"
    _dar("Alden", _hab("Fúria"))
    _vez("Alden")
    td.combat_action("ability", actor="Alden", ability="Fúria")
    tipos = {t for r in td._traits_lookup(_ch("Alden")["sheet"], "resistencias") for t in r["tipos"]}
    assert {"bludgeoning", "piercing", "slashing"} <= tipos
    _d20(monkeypatch, 18)
    saida = td.attack_roll("Alden", "Orc", "espada longa", 8, end_turn=False)
    assert "Fúria: +2" in saida


# ---------------------------------------------------------------------------
# 4. Ações de classe
# ---------------------------------------------------------------------------

def test_sacerdote_de_guerra_so_depois_de_atacar(luta, monkeypatch):
    _dar("Kaelen", _hab("Sacerdote de Guerra",
                        descricao="Ação bônus: faz 1 ataque adicional. Usos = mod. SAB por descanso longo."))
    _vez("Kaelen")
    r = td.combat_action("ability", actor="Kaelen", ability="Sacerdote de Guerra", target="Orc")
    assert not r["ok"] and "Atacar" in r["message"]
    assert not memory.campaign["combat_state"]["turn_economy"]["bonus_usada"]
    _d20(monkeypatch, 15)
    td.combat_action("attack", actor="Kaelen", target="Orc")
    antes = _vida("Orc")
    r = td.combat_action("ability", actor="Kaelen", ability="Sacerdote de Guerra", target="Orc")
    assert r["ok"], r["message"]
    assert _vida("Orc") < antes
    assert td.usos_restantes(_ch("Kaelen"), "Sacerdote de Guerra") == td.usos_maximos(_ch("Kaelen"), "Sacerdote de Guerra") - 1


def test_acao_ardilosa_esconder_da_vantagem_e_revela(luta, monkeypatch):
    _dar("Lyra", _hab("Ação Ardilosa"))
    _vez("Lyra")
    monkeypatch.setattr(random, "randint", lambda a, b: b)   # Furtividade máxima
    r = td.combat_action("ability", actor="Lyra", ability="Ação Ardilosa", weapon="esconder")
    assert r["ok"] and "ESCONDIDO" in r["message"]
    saida = td.attack_roll("Lyra", "Orc", "adaga", 4, end_turn=False)
    assert "vantagem" in saida.lower()
    assert not any((c.get("nome") or "").lower() == "escondido" for c in _ch("Lyra")["sheet"]["condicoes"])


def test_acao_ardilosa_pede_a_escolha(luta):
    _dar("Lyra", _hab("Ação Ardilosa"))
    _vez("Lyra")
    r = td.combat_action("ability", actor="Lyra", ability="Ação Ardilosa")
    assert not r["ok"] and "disparada" in r["message"]
    assert not memory.campaign["combat_state"]["turn_economy"]["bonus_usada"]


def test_acao_ardilosa_disparada_e_desengajar_no_campo(luta):
    td.set_battlefield("Portão, Pátio, Sacada")
    for n, z in (("Lyra", "Portão"), ("Orc", "Portão"), ("Orc B", "Sacada"),
                 ("Kaelen", "Pátio"), ("Alden", "Pátio")):
        td._por_zona(n, z)
    _dar("Lyra", _hab("Ação Ardilosa"))
    _vez("Lyra")
    td.combat_action("ability", actor="Lyra", ability="Ação Ardilosa", weapon="desengajar")
    vida = _vida("Lyra")
    # Sem a Disparada de bônus, duas zonas exigiriam a Ação; agora não.
    r = td.combat_action("move", actor="Lyra", target="Pátio")
    assert r["ok"] and "Desengajou" in r["message"] and _vida("Lyra") == vida


def test_expulsar_mortos_vivos(luta, povoar):
    povoar(criar_ficha("Esqueleto", vida=13, sabedoria=1, tipo="undead"))
    memory.campaign["combat_state"]["initiative_order"].append("Esqueleto")
    _dar("Kaelen", _hab("Canalizar Divindade"))
    _vez("Kaelen")
    random.seed(2)
    r = td.combat_action("ability", actor="Kaelen", ability="Canalizar Divindade")
    assert r["ok"], r["message"]
    conds = [c["nome"] for c in _ch("Esqueleto")["sheet"]["condicoes"]]
    assert "Amedrontado" in conds
    assert not [c for c in _ch("Orc")["sheet"]["condicoes"]], "o orc não é morto-vivo"


def test_expulsar_sem_morto_vivo_nao_gasta(luta):
    _dar("Kaelen", _hab("Canalizar Divindade"))
    _vez("Kaelen")
    r = td.combat_action("ability", actor="Kaelen", ability="Canalizar Divindade")
    assert not r["ok"]
    assert td.usos_restantes(_ch("Kaelen"), "Canalizar Divindade") == td.usos_maximos(_ch("Kaelen"), "Canalizar Divindade")


def test_guiar_ataque_soma_dez_uma_vez_e_nao_gasta_acao(luta, monkeypatch):
    _dar("Kaelen", _hab("Canalizar Divindade (Guiar Ataque)"))
    _vez("Kaelen")
    r = td.combat_action("ability", actor="Kaelen", ability="Canalizar Divindade (Guiar Ataque)")
    eco = memory.campaign["combat_state"]["turn_economy"]
    assert r["ok"] and not eco["acao_usada"] and not eco["bonus_usada"]
    _d20(monkeypatch, 5)
    assert "+10(efeitos)" in td.attack_roll("Kaelen", "Orc", "maça", 6, end_turn=False)
    assert "efeitos" not in td.attack_roll("Kaelen", "Orc", "maça", 6, end_turn=False)


# ---------------------------------------------------------------------------
# 5. Regras que faltavam no ataque
# ---------------------------------------------------------------------------

def test_ataque_furtivo_com_aliado_ao_lado_uma_vez_por_turno(luta, monkeypatch):
    _dar("Lyra", _hab("Ataque Furtivo", dado="1d6"))
    _vez("Lyra")
    _d20(monkeypatch, 18)
    primeira = td.attack_roll("Lyra", "Orc", "adaga", 4, end_turn=False)
    segunda = td.attack_roll("Lyra", "Orc", "adaga", 4, end_turn=False)
    assert "Ataque Furtivo" in primeira and "2d6" in primeira    # ladina de nível 3
    assert "Ataque Furtivo" not in segunda


def test_ataque_extra_libera_o_segundo_golpe(luta, monkeypatch):
    _vez("Alden")
    _d20(monkeypatch, 15)
    r1 = td.combat_action("attack", actor="Alden", target="Orc")
    assert r1["ok"] and "mais 1 ataque" in r1["message"]
    r2 = td.combat_action("attack", actor="Alden", target="Orc")
    assert r2["ok"], r2["message"]
    r3 = td.combat_action("attack", actor="Alden", target="Orc")
    assert not r3["ok"]


def test_magia_de_ataque_pode_errar(luta, monkeypatch):
    _dar("Kaelen", _hab("Guiding Bolt", custo=2))
    _vez("Kaelen")
    _d20(monkeypatch, 2)
    saida = td.use_ability("Kaelen", "Guiding Bolt", "Orc", end_turn=False)
    assert "ERROU" in saida and _vida("Orc") == 60


def test_raio_guia_marca_o_alvo(luta, monkeypatch):
    _dar("Kaelen", _hab("Guiding Bolt", custo=2))
    _vez("Kaelen")
    _d20(monkeypatch, 15)
    td.use_ability("Kaelen", "Guiding Bolt", "Orc", end_turn=False)
    assert td._mods_de_ataque(_ch("Alden"), _ch("Orc"), True)["vantagem"]


def test_chama_sagrada_nao_fere_quem_passa(luta, monkeypatch):
    _dar("Kaelen", _hab("Sacred Flame"))
    _vez("Kaelen")
    monkeypatch.setattr(td, "_rolar_salvaguarda", lambda a, attr, cd, **k: (True, "salvaguarda de DES: passou"))
    saida = td.use_ability("Kaelen", "Sacred Flame", "Orc", end_turn=False)
    assert _vida("Orc") == 60, saida
    assert "nenhum dano" in saida


# ---------------------------------------------------------------------------
# 6. O primeiro da iniciativa começa com a Ação
# ---------------------------------------------------------------------------

def test_combate_novo_nao_herda_a_acao_usada(campanha, povoar):
    """
    Relatado: "várias vezes o primeiro personagem na vez fica sem ação". O
    combate novo zerava ordem, rodada e log, mas não a economia do turno.
    """
    povoar(criar_ficha("Alden", grupo=True, vida=40), criar_ficha("Goblin", vida=7))
    cs = memory.campaign["combat_state"]
    cs["turn_economy"] = {"acao_usada": True, "bonus_usada": True, "movimento_usado": True}
    _ch("Alden")["sheet"]["reacao_rodada"] = 1
    td.roll_initiative("Alden, Goblin")
    eco = memory.campaign["combat_state"]["turn_economy"]
    assert not eco["acao_usada"] and not eco["bonus_usada"] and not eco["movimento_usado"]
    assert td._reaction_available(_ch("Alden"))


# ---------------------------------------------------------------------------
# 7. O diário: uma página por cena
# ---------------------------------------------------------------------------

def test_cena_seguida_continua_a_pagina(campanha):
    campanha["diary"] = []
    campanha["_turno"] = 10
    tools.add_diary_entry("Emboscada na Trilha", "Um goblin surge das sombras.")
    campanha["_turno"] = 11
    tools.add_diary_entry("A Queda do Batedor", "Alden abate o goblin com um golpe.")
    campanha["_turno"] = 12
    tools.add_diary_entry("O Espólio", "O grupo recolhe o que o goblin levava.")
    assert len(campanha["diary"]) == 1
    assert "Alden abate" in campanha["diary"][0]["content"]
    campanha["_turno"] = 16
    tools.add_diary_entry("As Ruínas", "O trio chega ao templo élfico.")
    assert len(campanha["diary"]) == 2


def test_pagina_repetida_nao_entra(campanha):
    campanha["diary"] = []
    campanha["_turno"] = 1
    tools.add_diary_entry("A Queda dos Guardiões", "O trio neutraliza dois orcs.")
    campanha["_turno"] = 9
    saida = tools.add_diary_entry("A Queda dos Guardiões", "O trio neutraliza dois orcs.")
    assert len(campanha["diary"]) == 1 and "Nada foi gravado" in saida


def test_capitulo_novo_abre_pagina_nova(campanha):
    campanha["diary"] = []
    campanha["_turno"] = 1
    tools.add_diary_entry("Fim de um caminho", "A estrada termina na ponte.")
    campanha["chapter"] = int(campanha.get("chapter", 1)) + 1
    campanha["_turno"] = 2
    tools.add_diary_entry("Começo", "Do outro lado, a cidade.")
    assert len(campanha["diary"]) == 2


def test_quem_aparece_nao_cita_todo_goblin(campanha, povoar):
    from rpg import epilogo
    povoar(criar_ficha("Alden Corvo de Ferro", grupo=True),
           *[criar_ficha(f"Goblin Batedor {i}") for i in range(1, 4)],
           criar_ficha("Chefe Goblin Grkrog"))
    quem = epilogo._quem_aparece("Alden recolhe o espólio dos goblins e encara Grkrog.")
    assert quem == ["Alden Corvo de Ferro", "Chefe Goblin Grkrog"]
