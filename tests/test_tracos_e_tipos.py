"""
test_tracos_e_tipos.py

As regras que o motor ainda não cobrava:

1. Tipo de criatura: Imobilizar Pessoa paralisava o lobo; Curar Ferimentos
   curava o zumbi; o Sono derrubava o morto-vivo e o elfo.
2. Traços das criaturas: Táticas de Matilha, Resistência à Magia, Fortitude
   Morta-Viva, Forma de Fogo, Armas Mágicas, imunidades a condição; e o que o
   golpe natural carrega (derrubar, veneno, agarrar, incendiar, investida),
   também no bloco do Open5e. Os poderes de recarga dos elementais.
3. Conjurar Fada e Conjurar Celestial num círculo acima.
4. A reação em "perguntar" também na jogada do jogador (Oportunista, Golpe
   Mágico), e no attack_roll do Mestre.
"""
import pytest

from rpg import criaturas, memory, reacoes, resolucao, tools_dnd as td, tracos

from conftest import criar_ficha, iniciar_combate


def _ch(nome):
    return memory.campaign["characters"].get(memory.char_key(nome))


def _hab(nome, custo=2):
    return {"nome": nome, "custo_mana": custo, "dado": "", "descricao": "",
            "nivel_magia": (resolucao._magia_srd({"nome": nome}) or {}).get("nivel", 1)}


def _criatura(chave, nome, lado="inimigo"):
    return {"name": nome, "status": "vivo" if lado != "inimigo" else "inimigo", "lado": lado,
            "party_member": False, "description": "", "traits": "", "notes": "",
            "habilidades": [], "inventario": [], "sheet": criaturas.montar_sheet(chave)}


def _conds(nome):
    return [c.get("nome") if isinstance(c, dict) else c for c in _ch(nome)["sheet"].get("condicoes") or []]


def _d20(monkeypatch, valor, registro=None):
    def rolar(vantagem=False, desvantagem=False, *a, **k):
        if registro is not None:
            registro.append((vantagem, desvantagem))
        return valor, f"d20={valor}"
    monkeypatch.setattr(td, "_roll_d20_with_adv", rolar)


def _salvaguarda(monkeypatch, passa):
    monkeypatch.setattr(td, "_rolar_salvaguarda", lambda alvo, *a, **k: (passa, "salvaguarda"))


# ---------------------------------------------------------------------------
# 1. Tipo de criatura
# ---------------------------------------------------------------------------

@pytest.fixture
def clerigo(campanha, povoar):
    povoar(criar_ficha("Ayla", grupo=True, classe="clérigo", nivel=9, sabedoria=18, mana=80,
                       habilidades=[_hab("Hold Person", 3), _hab("Cure Wounds"), _hab("Hold Monster", 7),
                                    _hab("Sleep"), _hab("Dominate Person", 7)]),
           criar_ficha("Orc", vida=30, raca="orc"),
           _criatura("lobo", "Lobo"), _criatura("zumbi", "Zumbi"), _criatura("diabrete", "Diabrete"),
           _criatura("elemental do ar", "Elemental"))
    iniciar_combate(["Ayla", "Orc", "Lobo", "Zumbi", "Diabrete", "Elemental"])
    return memory.campaign


def test_tipo_de_criatura_de_cada_fonte(clerigo):
    assert tracos.tipo_de_criatura(_ch("Orc")) == "humanoide"
    assert tracos.tipo_de_criatura(_ch("Lobo")) == "fera"
    assert tracos.tipo_de_criatura(_ch("Zumbi")) == "morto-vivo"
    assert tracos.tipo_de_criatura(_ch("Ayla")) == "humanoide"
    goblin = {"name": "Goblin", "description": "Small humanoid (goblinoid) — CR 1/4.", "sheet": {"raca": "goblin"}}
    assert tracos.tipo_de_criatura(goblin) == "humanoide"
    owlbear = {"name": "Corujurso", "description": "Large monstrosity — CR 3.", "sheet": {"raca": "corujurso"}}
    assert tracos.tipo_de_criatura(owlbear) == "monstruosidade"
    assert tracos.tipo_de_criatura({"name": "Vulto", "sheet": {"raca": "vulto"}}) == ""
    criaturas.transformar(_ch("Ayla"), "urso pardo")
    assert tracos.tipo_de_criatura(_ch("Ayla")) == "fera"


def test_imobilizar_pessoa_recusa_o_lobo_sem_gastar(clerigo):
    r = td.use_ability("Ayla", "Hold Person", "Lobo", end_turn=False)
    assert r.startswith("Aviso:") and "só afeta humanoides" in r and "Lobo é fera" in r, r
    assert _ch("Ayla")["sheet"]["mana_atual"] == 80


def test_imobilizar_pessoa_deixa_o_lobo_de_fora_e_pega_o_orc(clerigo, monkeypatch):
    _salvaguarda(monkeypatch, False)
    r = td.use_ability("Ayla", "Hold Person", "Orc, Lobo", end_turn=False, modo="c3")
    assert "Lobo é fera — fica de fora" in r, r
    assert "Paralisado" in _conds("Orc") and not _conds("Lobo")


def test_curar_ferimentos_nao_cura_morto_vivo(clerigo):
    _ch("Zumbi")["sheet"]["vida_atual"] = 5
    r = td.use_ability("Ayla", "Cure Wounds", "Zumbi", end_turn=False)
    assert r.startswith("Aviso:") and "mortos-vivos" in r, r
    assert _ch("Zumbi")["sheet"]["vida_atual"] == 5


def test_imobilizar_monstro_nao_pega_morto_vivo(clerigo):
    assert td.use_ability("Ayla", "Hold Monster", "Zumbi", end_turn=False).startswith("Aviso:")


def test_dominar_pessoa_so_humanoide(clerigo):
    assert td.use_ability("Ayla", "Dominate Person", "Lobo", end_turn=False).startswith("Aviso:")


def test_sono_nao_pega_morto_vivo_nem_elfo(clerigo, monkeypatch):
    for nome in ("Orc", "Lobo", "Zumbi", "Diabrete", "Elemental"):
        _ch(nome)["sheet"]["vida_atual"] = 3
    memory.campaign["characters"]["elfa"] = criar_ficha("Elfa", vida=3, raca="elfo")
    memory.campaign["combat_state"]["initiative_order"].append("Elfa")
    monkeypatch.setattr(td.random, "randint", lambda a, b: b)          # pool cheio
    td.use_ability("Ayla", "Sleep", "", end_turn=False)
    assert "Dormindo" in _conds("Orc") and "Dormindo" in _conds("Lobo")
    assert "Dormindo" not in _conds("Zumbi") and "Dormindo" not in _conds("Elfa")


# ---------------------------------------------------------------------------
# 2. Traços
# ---------------------------------------------------------------------------

@pytest.fixture
def matilha(campanha, povoar):
    povoar(criar_ficha("Brann", grupo=True, vida=60, ca=10),
           _criatura("lobo", "Lobo 1"), _criatura("lobo", "Lobo 2"))
    iniciar_combate(["Brann", "Lobo 1", "Lobo 2"], indice=1)
    return memory.campaign


def test_taticas_de_matilha_dao_vantagem(matilha, monkeypatch):
    vezes = []
    _d20(monkeypatch, 15, vezes)
    _salvaguarda(monkeypatch, True)
    r = td.attack_roll("Lobo 1", "Brann", "mordida", 6, end_turn=False, _skip_turn_check=True)
    assert "Táticas de Matilha: Lobo 2" in r and vezes[-1][0] is True, r


def test_sem_aliado_ao_lado_sem_vantagem(matilha, monkeypatch):
    vezes = []
    _d20(monkeypatch, 15, vezes)
    _salvaguarda(monkeypatch, True)
    cs = memory.campaign["combat_state"]
    cs["zonas"] = ["Portão", "Pátio"]
    cs["posicoes"] = {"brann": "Pátio", "lobo 1": "Pátio", "lobo 2": "Portão"}
    r = td.attack_roll("Lobo 1", "Brann", "mordida", 6, end_turn=False, _skip_turn_check=True)
    assert "Táticas de Matilha" not in r and vezes[-1][0] is False, r


def test_mordida_do_lobo_derruba(matilha, monkeypatch):
    _d20(monkeypatch, 15)
    _salvaguarda(monkeypatch, False)
    r = td.attack_roll("Lobo 1", "Brann", "mordida", 6, end_turn=False, _skip_turn_check=True)
    assert "CAÍDO" in r and "Caído" in _conds("Brann"), r


@pytest.fixture
def bicho(campanha, povoar):
    def _f(chave, nome, alvo=None):
        alvo = alvo or criar_ficha("Brann", grupo=True, vida=80, ca=10)
        povoar(alvo, _criatura(chave, nome))
        iniciar_combate([alvo["name"], nome], indice=1)
        return memory.campaign
    return _f


def test_veneno_da_aranha_dano_cheio_ou_metade(bicho, monkeypatch):
    bicho("aranha gigante", "Aranha")
    _d20(monkeypatch, 15)
    monkeypatch.setattr(td.random, "randint", lambda a, b: 4)
    _salvaguarda(monkeypatch, False)
    r = td.attack_roll("Aranha", "Brann", "mordida", 6, end_turn=False, _skip_turn_check=True)
    assert "8 de veneno" in r, r                         # 2d8 = 4 + 4
    _salvaguarda(monkeypatch, True)
    r = td.attack_roll("Aranha", "Brann", "mordida", 6, end_turn=False, _skip_turn_check=True)
    assert "metade: 4 de veneno" in r, r


def test_crocodilo_agarra_e_prende_e_escapar_solta_os_dois(bicho, monkeypatch):
    bicho("crocodilo", "Crocodilo")
    _d20(monkeypatch, 15)
    td.attack_roll("Crocodilo", "Brann", "mordida", 6, end_turn=False, _skip_turn_check=True)
    assert "Agarrado" in _conds("Brann") and "Contido" in _conds("Brann")
    from rpg import manobras
    monkeypatch.setattr(manobras, "_pericia", lambda *a, **k: (20, "20"))
    r = manobras.escapar("Brann")
    assert "contra CD 12 — livre" in r, r
    assert "Agarrado" not in _conds("Brann") and "Contido" not in _conds("Brann")


def test_carnical_paralisa_mas_nao_o_elfo(bicho, monkeypatch):
    bicho("carnical", "Carniçal")
    _d20(monkeypatch, 15)
    _salvaguarda(monkeypatch, False)
    td.attack_roll("Carniçal", "Brann", "garras", 6, end_turn=False, _skip_turn_check=True)
    c = next(c for c in _ch("Brann")["sheet"]["condicoes"] if c.get("nome") == "Paralisado")
    assert c["duracao"] == 10 and c["salvaguarda_fim"]["cd"] == 10
    _ch("Brann")["sheet"]["condicoes"] = []
    _ch("Brann")["sheet"]["raca"] = "elfo"
    r = td.attack_roll("Carniçal", "Brann", "garras", 6, end_turn=False, _skip_turn_check=True)
    assert "é elfo" in r and not _conds("Brann"), r


def test_elemental_do_fogo_incendeia_e_queima_quem_o_soca(bicho, monkeypatch):
    bicho("elemental do fogo", "Fogo")
    _d20(monkeypatch, 15)
    td.attack_roll("Fogo", "Brann", "toque", 6, end_turn=False, _skip_turn_check=True)
    queima = next(c for c in _ch("Brann")["sheet"]["condicoes"] if c.get("nome") == "Queimando")
    assert queima["dado"] == "1d10"
    monkeypatch.setattr(td.random, "randint", lambda a, b: b)
    vida = _ch("Brann")["sheet"]["vida_atual"]
    linhas = td._queimar_no_inicio_do_turno(_ch("Brann"))
    assert _ch("Brann")["sheet"]["vida_atual"] == vida - 10, linhas
    vida = _ch("Brann")["sheet"]["vida_atual"]
    r = td.attack_roll("Brann", "Fogo", "espada longa", 6, end_turn=False, _skip_turn_check=True)
    assert "Forma de Fogo de Fogo: Brann leva 10 de fogo" in r, r
    assert _ch("Brann")["sheet"]["vida_atual"] == vida - 10


def test_fortitude_morta_viva(bicho, monkeypatch):
    bicho("zumbi", "Zumbi")
    _ch("Zumbi")["sheet"]["vida_atual"] = 3
    _salvaguarda(monkeypatch, True)
    res = td._apply_damage(_ch("Zumbi"), 8, "slashing")
    assert res["hp_depois"] == 1 and any("Fortitude" in n for n in res["notas"])
    _ch("Zumbi")["sheet"]["vida_atual"] = 3
    assert td._apply_damage(_ch("Zumbi"), 8, "radiant")["hp_depois"] == 0
    _ch("Zumbi")["sheet"]["vida_atual"] = 3
    assert td._apply_damage(_ch("Zumbi"), 8, "slashing", critico=True)["hp_depois"] == 0
    _salvaguarda(monkeypatch, False)
    _ch("Zumbi")["sheet"]["vida_atual"] = 3
    assert td._apply_damage(_ch("Zumbi"), 8, "slashing")["hp_depois"] == 0


def test_critico_do_ataque_nao_deixa_o_zumbi_levantar(bicho, monkeypatch):
    bicho("zumbi", "Zumbi")
    _ch("Zumbi")["sheet"]["vida_atual"] = 3
    _d20(monkeypatch, 20)
    _salvaguarda(monkeypatch, True)
    r = td.attack_roll("Brann", "Zumbi", "espada longa", 6, end_turn=False, _skip_turn_check=True)
    assert "CRÍTICO" in r and _ch("Zumbi")["sheet"]["vida_atual"] == 0, r
    _ch("Zumbi")["sheet"]["vida_atual"] = 3
    _ch("Zumbi")["status"] = "inimigo"
    _d20(monkeypatch, 15)
    td.attack_roll("Brann", "Zumbi", "espada longa", 6, end_turn=False, _skip_turn_check=True)
    assert _ch("Zumbi")["sheet"]["vida_atual"] == 1


def test_fortitude_rola_contra_cinco_mais_o_dano(bicho, monkeypatch):
    bicho("zumbi", "Zumbi")
    _ch("Zumbi")["sheet"]["vida_atual"] = 3
    pedidos = []
    monkeypatch.setattr(td, "_rolar_salvaguarda", lambda alvo, atr, cd, *a, **k: (pedidos.append((atr, cd)) or True, "s"))
    td._apply_damage(_ch("Zumbi"), 8, "slashing")
    assert pedidos == [("constituicao", 13)]


def test_resistencia_a_magia_so_contra_magia(campanha, povoar):
    povoar(criar_ficha("Ayla", grupo=True, classe="clérigo", nivel=9, sabedoria=18, mana=80,
                       habilidades=[_hab("Hold Monster", 7)]),
           _criatura("diabrete", "Diabrete"))
    iniciar_combate(["Ayla", "Diabrete"])
    r = td.use_ability("Ayla", "Hold Monster", "Diabrete", end_turn=False)
    assert "vantagem: Resistência à Magia" in r, r
    _, linha = td._rolar_salvaguarda(_ch("Diabrete"), "constituicao", 10)
    assert "Resistência à Magia" not in linha
    assert tracos._magias_em_curso == 0


def test_elemental_imune_a_paralisia(campanha, povoar, monkeypatch):
    povoar(criar_ficha("Ayla", grupo=True, classe="clérigo", nivel=9, sabedoria=18, mana=80,
                       habilidades=[_hab("Hold Monster", 7)]),
           _criatura("elemental do ar", "Elemental"))
    iniciar_combate(["Ayla", "Elemental"])
    _salvaguarda(monkeypatch, False)
    r = td.use_ability("Ayla", "Hold Monster", "Elemental", end_turn=False)
    assert "imune a Paralisado" in r and "Paralisado" not in _conds("Elemental"), r


def test_armas_magicas_passam_da_resistencia(bicho, monkeypatch):
    bicho("couatl", "Couatl", alvo=_criatura("elemental da terra", "Terra", lado="grupo") | {"party_member": True})
    _d20(monkeypatch, 18)
    _salvaguarda(monkeypatch, True)
    r = td.attack_roll("Couatl", "Terra", "constrição", 6, end_turn=False, _skip_turn_check=True)
    assert "resist" not in r.lower(), r


def test_investida_so_depois_de_andar(bicho, monkeypatch):
    bicho("cavalo de guerra", "Cavalo")
    _d20(monkeypatch, 15)
    _salvaguarda(monkeypatch, False)
    td.attack_roll("Cavalo", "Brann", "cascos", 6, end_turn=False, _skip_turn_check=True)
    assert "Caído" not in _conds("Brann")
    memory.campaign["combat_state"]["turn_economy"]["movimento_usado"] = True
    r = td.attack_roll("Cavalo", "Brann", "cascos", 6, end_turn=False, _skip_turn_check=True)
    assert "Investida" in r and "Caído" in _conds("Brann"), r


def test_poder_de_recarga_do_elemental_invocado(campanha, povoar, monkeypatch):
    povoar(criar_ficha("Kaelen", grupo=True, classe="druida", nivel=9, mana=60),
           criar_ficha("Orc", vida=80, raca="orc"))
    iniciar_combate(["Kaelen", "Orc"])
    criaturas.invocar(_ch("Kaelen"), "elemental do ar", 1, "Conjure Elemental", concentracao=False,
                      persistente=False)
    ar = _ch("Elemental do Ar de Kaelen")
    assert [h["nome"] for h in ar["habilidades"]] == ["Redemoinho"]
    assert ar["sheet"]["recargas"]["Redemoinho"]["min"] == 4
    _salvaguarda(monkeypatch, False)
    r = td.use_ability("Elemental do Ar de Kaelen", "Redemoinho", "Orc", end_turn=False, _skip_turn_check=True)
    assert "CAÍDO" in r and "Caído" in _conds("Orc") and _ch("Orc")["sheet"]["vida_atual"] < 80, r
    r = td.use_ability("Elemental do Ar de Kaelen", "Redemoinho", "Orc", end_turn=False, _skip_turn_check=True)
    assert r.startswith("Erro:") and "GASTO" in r, r


def test_poder_usa_a_cd_dele(campanha, povoar, monkeypatch):
    povoar(criar_ficha("Kaelen", grupo=True, classe="druida", nivel=9, mana=60),
           criar_ficha("Orc", vida=80, raca="orc"))
    iniciar_combate(["Kaelen", "Orc"])
    criaturas.invocar(_ch("Kaelen"), "elemental da agua", 1, "Conjure Elemental", concentracao=False,
                      persistente=False)
    pedidos = []
    monkeypatch.setattr(td, "_rolar_salvaguarda",
                        lambda alvo, atr, cd, *a, **k: (pedidos.append((atr, cd)) or False, "falhou"))
    r = td.use_ability("Elemental da Água de Kaelen", "Engolfar", "Orc", end_turn=False, _skip_turn_check=True)
    assert pedidos[0] == ("forca", 15) and "Contido" in _conds("Orc"), r


def test_toque_curativo_do_unicornio_tres_vezes(campanha, povoar):
    povoar(criar_ficha("Ayla", grupo=True, classe="clérigo", nivel=17, mana=120, vida=50, vida_max=100))
    iniciar_combate(["Ayla"])
    criaturas.invocar(_ch("Ayla"), "unicornio", 1, "Conjure Celestial", concentracao=False, persistente=False)
    for _ in range(3):
        r = td.use_ability("Unicórnio de Ayla", "Toque Curativo", "Ayla", end_turn=False, _skip_turn_check=True)
        assert not r.startswith("Erro:"), r
    assert _ch("Ayla")["sheet"]["vida_atual"] > 50
    assert td.use_ability("Unicórnio de Ayla", "Toque Curativo", "Ayla", end_turn=False,
                          _skip_turn_check=True).startswith("Erro:")


def test_fichas_novas_com_os_traços():
    assert criaturas.montar_sheet("lobo")["tracos"] == ["matilha"]
    assert "Agarrado" in criaturas.montar_sheet("elemental do ar")["imunidades_condicao"]
    assert criaturas.montar_sheet("aranha gigante")["ataques"][0]["rider"]["dado"] == "2d8"
    assert criaturas.montar_sheet("unicornio")["tracos"] == ["resistencia magica", "armas magicas"]
    s = criaturas.montar_sheet("perseguidor invisivel")
    assert "Contido" in s["imunidades_condicao"]


def test_forma_selvagem_leva_os_tracos_e_devolve(campanha, povoar):
    povoar(criar_ficha("Kaelen", grupo=True, classe="druida", nivel=4))
    criaturas.transformar(_ch("Kaelen"), "lobo")
    assert "matilha" in tracos.tracos_de(_ch("Kaelen"))
    criaturas.voltar(_ch("Kaelen"))
    assert "matilha" not in tracos.tracos_de(_ch("Kaelen"))


# ── O bloco do Open5e ──

def test_texto_do_ataque_do_open5e():
    lobo = ("Melee Weapon Attack: +4 to hit, reach 5 ft., one target. Hit: 7 (2d4 + 2) piercing damage. If the "
            "target is a creature, it must succeed on a DC 11 Strength saving throw or be knocked prone.")
    assert tracos.efeitos_do_texto(lobo) == {"derruba": {"salvaguarda": "forca", "cd": 11}}
    aranha = ("Melee Weapon Attack: +5 to hit. Hit: 7 (1d8 + 3) piercing damage, and the target must make a DC 11 "
              "Constitution saving throw, taking 9 (2d8) poison damage on a failed save, or half as much damage "
              "on a successful one.")
    r = tracos.efeitos_do_texto(aranha)["rider"]
    assert r == {"salvaguarda": "constituicao", "cd": 11, "dado": "2d8", "tipo": "poison", "metade": True}
    carnical = ("Melee Weapon Attack: +4 to hit. Hit: 7 (2d4 + 2) slashing damage. If the target is a creature "
                "other than an elf or undead, it must succeed on a DC 10 Constitution saving throw or be "
                "paralyzed for 1 minute. The target can repeat the saving throw at the end of each of its turns.")
    r = tracos.efeitos_do_texto(carnical)["rider"]
    assert r["condicao"] == "Paralisado" and r["duracao"] == 10 and r["repete"] is True
    croc = "Melee Weapon Attack: +4 to hit. Hit: 7 (1d10 + 2) piercing damage, and the target is grappled (escape DC 12). Until this grapple ends, the target is restrained."
    assert tracos.efeitos_do_texto(croc)["agarra"] == {"cd": 12, "contido": True}
    assert tracos.imunidades_de_condicao("poisoned, exhaustion, prone") == ["Envenenado", "Exausto", "Caído"]


def test_extrai_o_que_o_ataque_carrega():
    m = {"actions": [{"name": "Bite", "desc": "Melee Weapon Attack: +4 to hit, reach 5 ft., one target. Hit: 7 "
                      "(2d4 + 2) piercing damage. If the target is a creature, it must succeed on a DC 11 Strength "
                      "saving throw or be knocked prone.", "damage_dice": "2d4"}]}
    atk = td._extract_monster_attacks(m)["ataques"][0]
    assert atk["derruba"] == {"salvaguarda": "forca", "cd": 11}


def test_traço_pelo_nome_do_open5e():
    lobo = {"name": "Wolf", "sheet": {}, "habilidades": [{"nome": "Pack Tactics"}, {"nome": "Keen Hearing"}]}
    assert tracos.tracos_de(lobo) == {"matilha"}


# ---------------------------------------------------------------------------
# 3. Conjurar Fada e Conjurar Celestial num círculo acima
# ---------------------------------------------------------------------------

def test_conjurar_fada_e_celestial_escalam(campanha, povoar):
    povoar(criar_ficha("Kaelen", grupo=True, classe="druida", nivel=17, mana=150,
                       habilidades=[_hab("Conjure Fey", 9), _hab("Conjure Celestial", 10)]))
    k = _ch("Kaelen")
    fada = resolucao.como_resolve(_hab("Conjure Fey", 9), k)["modos"]
    assert "gorila gigante:1@c7" in fada and "tiranossauro:1@c8" in fada
    celestial = resolucao.como_resolve(_hab("Conjure Celestial", 10), k)["modos"]
    assert "unicornio:1@c9" in celestial
    r = td.conjurar_fora_de_combate("Kaelen", "Conjure Fey", "", "tiranossauro:1@c8")
    assert r["ok"], r["message"]
    assert _ch("Tiranossauro de Kaelen")["sheet"]["vida_max"] == 136
    assert _ch("Kaelen")["sheet"]["mana_atual"] == 150 - td.SPELL_MANA_COST[8]


# ---------------------------------------------------------------------------
# 4. Reação que pergunta também na jogada do jogador
# ---------------------------------------------------------------------------

@pytest.fixture
def dupla(campanha, povoar, monkeypatch):
    povoar(criar_ficha("Brann", grupo=True, vida=40, forca=18),
           criar_ficha("Lin", grupo=True, classe="monge", nivel=6, destreza=18, arma="ataque desarmado",
                       habilidades=[{"nome": "Oportunista", "custo_mana": 0, "dado": "", "descricao": ""}]),
           criar_ficha("Orc", vida=200, ca=10))
    iniciar_combate(["Brann", "Lin", "Orc"])
    _d20(monkeypatch, 15)
    return memory.campaign


def test_o_ataque_do_jogador_para_na_pergunta(dupla):
    reacoes.alternar("Lin", "oportunista", True, "perguntar")
    r = td.combat_action("attack", actor="Brann", target="Orc", weapon="espada longa")
    assert r["ok"] and "REAÇÃO — Lin decide" in r["message"] and "Oportunista" in r["message"], r["message"]
    assert _ch("Orc")["sheet"]["vida_atual"] == 200
    assert not memory.campaign["combat_state"]["turn_economy"].get("acao_usada")
    assert r["snapshot"]["reacao_pendente"]["quem"] == "Lin"


def test_responder_sim_refaz_o_ataque_e_o_monge_bate(dupla):
    reacoes.alternar("Lin", "oportunista", True, "perguntar")
    td.combat_action("attack", actor="Brann", target="Orc", weapon="espada longa")
    r = td.combat_action("reagir", weapon="sim")
    assert r["ok"] and "Lin usa Oportunista" in r["message"], r["message"]
    assert memory.campaign["combat_state"]["turn_economy"]["acao_usada"]
    assert r["snapshot"]["reacao_pendente"] is None


def test_responder_nao_so_o_ataque(dupla):
    reacoes.alternar("Lin", "oportunista", True, "perguntar")
    td.combat_action("attack", actor="Brann", target="Orc", weapon="espada longa")
    r = td.combat_action("reagir", weapon="nao")
    assert "Oportunista:" not in r["message"] and _ch("Orc")["sheet"]["vida_atual"] < 200, r["message"]


def test_com_pergunta_pendente_nada_mais_anda(dupla):
    reacoes.alternar("Lin", "oportunista", True, "perguntar")
    td.combat_action("attack", actor="Brann", target="Orc", weapon="espada longa")
    r = td.combat_action("end_turn", actor="Brann")
    assert not r["ok"] and "parada esperando" in r["message"]
    assert td._combat_current_actor() == "Brann"


def test_o_ataque_do_mestre_tambem_pergunta(dupla):
    reacoes.alternar("Lin", "oportunista", True, "perguntar")
    r = td.attack_roll("Brann", "Orc", "espada longa", 6, end_turn=False)
    assert "REAÇÃO — Lin decide" in r, r
    assert td.attack_roll("Brann", "Orc", "espada longa", 6, end_turn=False).startswith("Aviso:")
    r = td.responder_reacao(True)
    assert "Lin usa Oportunista" in r, r


def test_golpe_magico_pergunta_a_quem_ataca(campanha, povoar, monkeypatch):
    povoar(criar_ficha("Ela", grupo=True, classe="guerreiro", nivel=7, inteligencia=16, mana=10,
                       habilidades=[{"nome": "Golpe Mágico", "custo_mana": 0, "dado": "", "descricao": ""},
                                    _hab("Fire Bolt", 0)]),
           criar_ficha("Orc", vida=200, ca=10))
    iniciar_combate(["Ela", "Orc"])
    _d20(monkeypatch, 15)
    reacoes.alternar("Ela", "golpe magico", True, "perguntar")
    r = td.combat_action("attack", actor="Ela", target="Orc", weapon="espada longa")
    assert "REAÇÃO — Ela decide" in r["message"] and "Fire Bolt" in r["message"], r["message"]
    assert r["snapshot"]["reacao_pendente"]["chave"] == "golpe magico"
    r = td.combat_action("reagir", weapon="nao")
    assert "usa Golpe Mágico:" not in r["message"], r["message"]


def test_sem_ninguem_perguntando_nada_muda(dupla):
    r = td.combat_action("attack", actor="Brann", target="Orc", weapon="espada longa")
    assert "REAÇÃO" not in r["message"] and "Lin usa Oportunista" in r["message"], r["message"]
