"""
test_upcast_invocacoes_reacoes.py

O que ainda limitava o sistema de magias e habilidades:

1. Conjurar num círculo acima cobrava a mana a mais e não dava nada a mais:
   Imobilizar Pessoa no 3º círculo paralisava um só; Mísseis Mágicos soltava
   UM dardo de 1d4+1 em qualquer círculo; Conjurar Animais e Conjurar
   Elemental não escalavam.
2. As criaturas invocadas eram jogadas pelo motor, como aliados quaisquer —
   os lobos do druida atacavam quem a IA escolhia.
3. Sem zonas, a magia de área pegava só a primeira criatura.
4. O ritual "somava dez minutos" só no texto: o relógio contava horas.
5. As reações eram só automáticas: o jogador não decidia o Escudo Arcano na
   hora em que o golpe vinha.
"""
import random

import pytest

from rpg import criaturas, memory, reacoes, resolucao, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _ch(nome):
    return memory.campaign["characters"].get(memory.char_key(nome))


def _hab(nome, custo=2, **extra):
    return {"nome": nome, "custo_mana": custo, "dado": "", "descricao": "",
            "nivel_magia": (resolucao._magia_srd({"nome": nome}) or {}).get("nivel", 1), **extra}


def _vez(nome):
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index(nome)
    cs["turn_token"] = int(cs.get("turn_token", 0) or 0) + 1
    td._reset_turn_economy(cs)


def _falha_sempre(monkeypatch):
    monkeypatch.setattr(td, "_rolar_salvaguarda", lambda alvo, *a, **k: (False, "salvaguarda: 2 — falhou"))


@pytest.fixture
def mago(campanha, povoar):
    povoar(criar_ficha("Mira", grupo=True, classe="mago", nivel=9, inteligencia=18, mana=80, vida=40,
                       habilidades=[_hab("Magic Missile"), _hab("Hold Person", 3), _hab("Fireball", 5),
                                    _hab("Scorching Ray", 3), _hab("Burning Hands", 2),
                                    _hab("Lightning Bolt", 5), _hab("Thunderwave", 2)]),
           criar_ficha("Brann", grupo=True, vida=40),
           *[criar_ficha(f"Orc {l}", vida=60, ca=10, sabedoria=1) for l in "ABCDE"])
    iniciar_combate(["Mira", "Brann", "Orc A", "Orc B", "Orc C", "Orc D", "Orc E"])
    return memory.campaign


# ---------------------------------------------------------------------------
# 1. Upcast: alvos, dardos, raios
# ---------------------------------------------------------------------------

def test_misseis_magicos_tres_dardos_no_primeiro_circulo(mago):
    r = td.use_ability("Mira", "Magic Missile", "Orc A", end_turn=False)
    assert "3 dardos de 1d4+1" in r, r
    assert r.count("Dardo ") == 3
    assert 60 - 3 * 5 <= _ch("Orc A")["sheet"]["vida_atual"] <= 60 - 3 * 2


def test_misseis_magicos_um_dardo_a_mais_por_circulo_e_repartidos(mago):
    r = td.use_ability("Mira", "Magic Missile", "Orc A, Orc B", end_turn=False, modo="c3")
    assert "5 dardos" in r and r.count("Dardo ") == 5, r
    # Rodízio: três no primeiro nome, dois no segundo.
    assert r.count("→ Orc A") == 3 and r.count("→ Orc B") == 2
    assert 60 - 15 <= _ch("Orc A")["sheet"]["vida_atual"] <= 60 - 6
    assert 60 - 10 <= _ch("Orc B")["sheet"]["vida_atual"] <= 60 - 4
    assert _ch("Mira")["sheet"]["mana_atual"] == 80 - td.SPELL_MANA_COST[3]


def test_dardo_nao_passa_pelo_escudo_arcano(mago):
    td.dar_efeito_de_combate(_ch("Orc A"), {"nome": "Escudo Arcano", "ca": 5})
    r = td.use_ability("Mira", "Magic Missile", "Orc A", end_turn=False)
    assert r.count("absorve o dardo") == 3, r
    assert _ch("Orc A")["sheet"]["vida_atual"] == 60


def test_raio_ardente_rola_acerto_por_raio(mago, monkeypatch):
    dados = iter([18, 1, 18, 18])
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda *a, **k: (v := next(dados), f"d20={v}"))
    monkeypatch.setattr(td.random, "randint", lambda a, b: 3)
    r = td.use_ability("Mira", "Scorching Ray", "Orc A", end_turn=False, modo="c3")
    assert "4 raios de 2d6" in r and r.count("Ataque mágico") == 4, r
    # Três raios acertam, 2d6 = 6 cada; o que errou não fere.
    assert _ch("Orc A")["sheet"]["vida_atual"] == 60 - 18


def test_imobilizar_pessoa_no_terceiro_circulo_pega_dois(mago, monkeypatch):
    _falha_sempre(monkeypatch)
    r = td.use_ability("Mira", "Hold Person", "Orc A, Orc B, Orc C", end_turn=False, modo="c3")
    assert "no máximo 2 neste círculo" in r, r
    paralisados = [n for n in ("Orc A", "Orc B", "Orc C")
                   if any(c.get("nome", "").lower() == "paralisado" for c in _ch(n)["sheet"]["condicoes"])]
    assert paralisados == ["Orc A", "Orc B"]


def test_imobilizar_pessoa_no_segundo_circulo_continua_um(mago, monkeypatch):
    _falha_sempre(monkeypatch)
    td.use_ability("Mira", "Hold Person", "Orc A, Orc B", end_turn=False)
    assert any(c.get("nome", "").lower() == "paralisado" for c in _ch("Orc A")["sheet"]["condicoes"])
    assert not _ch("Orc B")["sheet"]["condicoes"]


def test_imobilizar_pessoa_cada_um_faz_a_sua_salvaguarda(mago, monkeypatch):
    monkeypatch.setattr(td, "_rolar_salvaguarda",
                        lambda alvo, *a, **k: (alvo["name"] == "Orc B", "salvaguarda"))
    r = td.use_ability("Mira", "Hold Person", "Orc A, Orc B", end_turn=False, modo="c3")
    assert "Orc B: salvaguarda — resistiu" in r, r
    assert _ch("Orc A")["sheet"]["condicoes"] and not _ch("Orc B")["sheet"]["condicoes"]


def test_os_circulos_dizem_quantos_dardos_e_alvos(mago):
    mira = _ch("Mira")
    mm = resolucao.como_resolve(_hab("Magic Missile"), mira)["modos_texto"]
    assert "4 dardos de 1d4+1" in mm["c2"]
    hp = resolucao.como_resolve(_hab("Hold Person", 3), mira)
    assert hp["modos"][:2] == ["c2", "c3"] and "2 alvos" in hp["modos_texto"]["c3"]
    assert resolucao.alvos_por_modo(_hab("Hold Person", 3), mira)["c4"] == 3
    assert resolucao.alvos_por_modo(_hab("Magic Missile"), mira)["c1"] == 3
    # Bola de Fogo tem um alvo (a área); a Bênção escolhe sozinha; o Sono é pool.
    assert resolucao.alvos_por_modo(_hab("Fireball", 5), mira) == {}
    assert resolucao.alvos_por_modo(_hab("Sleep"), mira) == {}


def test_a_tela_recebe_quantos_alvos(mago):
    snap = td._combatant_snapshot("Mira")
    por_nome = {h["nome"]: h for h in snap["habilidades"]}
    assert por_nome["Hold Person"]["alvos_por_modo"]["c3"] == 2
    assert por_nome["Fireball"]["max_alvos"] == 4      # sem zonas


# ---------------------------------------------------------------------------
# 1b. Invocações num círculo acima
# ---------------------------------------------------------------------------

@pytest.fixture
def druida(campanha, povoar):
    povoar(criar_ficha("Kaelen", grupo=True, classe="druida", nivel=17, sabedoria=18, mana=120, vida=60,
                       habilidades=[_hab("Conjure Animals", 5), _hab("Conjure Elemental", 7),
                                    _hab("Animate Objects", 7), _hab("Create Undead", 9),
                                    _hab("Find Familiar", 2), _hab("Conjure Woodland Beings", 6)]),
           criar_ficha("Orc", vida=300, ca=10))
    return memory.campaign


def test_conjurar_animais_dobra_no_quinto_circulo(druida):
    iniciar_combate(["Kaelen", "Orc"])
    modos = resolucao.como_resolve(_hab("Conjure Animals", 5), _ch("Kaelen"))["modos_texto"]
    assert "lobo:8" in modos and "lobo:16@c5" in modos and "lobo:24@c7" in modos and "lobo:32@c9" in modos
    r = td.combat_action("ability", actor="Kaelen", ability="Conjure Animals", weapon="lobo:16@c5")
    assert r["ok"], r["message"]
    lobos = [c for c in memory.campaign["characters"].values() if c.get("name", "").startswith("Lobo de Kaelen")]
    assert len(lobos) == 16
    assert _ch("Kaelen")["sheet"]["mana_atual"] == 120 - td.SPELL_MANA_COST[5]


def test_conjurar_animais_no_circulo_base_continua_igual(druida):
    iniciar_combate(["Kaelen", "Orc"])
    td.combat_action("ability", actor="Kaelen", ability="Conjure Animals", weapon="lobo:8")
    assert sum(c.get("name", "").startswith("Lobo de Kaelen") for c in memory.campaign["characters"].values()) == 8
    assert _ch("Kaelen")["sheet"]["mana_atual"] == 115


def test_circulo_que_a_mana_nao_paga_some_dos_modos(druida):
    _ch("Kaelen")["sheet"]["mana_atual"] = 8
    modos = resolucao.como_resolve(_hab("Conjure Animals", 5), _ch("Kaelen"))["modos_texto"]
    assert "lobo:16@c5" in modos and "lobo:24@c7" not in modos
    iniciar_combate(["Kaelen", "Orc"])
    r = td.combat_action("ability", actor="Kaelen", ability="Conjure Animals", weapon="lobo:24@c7")
    assert not r["ok"] and _ch("Kaelen")["sheet"]["mana_atual"] == 8


def test_animar_objetos_e_criar_mortos_vivos_crescem_por_circulo(druida):
    k = _ch("Kaelen")
    objetos = resolucao.como_resolve(_hab("Animate Objects", 7), k)["modos"]
    assert "objeto miudo:12@c6" in objetos and "objeto medio:6@c6" in objetos and "objeto miudo:18@c9" in objetos
    mortos = resolucao.como_resolve(_hab("Create Undead", 9), k)["modos"]
    assert "carnical:4@c7" in mortos and "carnical:6@c9" in mortos
    madeira = resolucao.como_resolve(_hab("Conjure Woodland Beings", 6), k)["modos"]
    assert "satiro:8@c6" in madeira and "satiro:12@c8" in madeira


def test_conjurar_elemental_no_sexto_circulo_chama_o_perseguidor_invisivel(druida):
    k = _ch("Kaelen")
    modos = resolucao.como_resolve(_hab("Conjure Elemental", 7), k)["modos"]
    assert "perseguidor invisivel:1@c6" in modos
    r = td.conjurar_fora_de_combate("Kaelen", "Conjure Elemental", "", "perseguidor invisivel:1@c6")
    assert r["ok"], r["message"]
    p = _ch("Perseguidor Invisível de Kaelen")
    assert p and p["sheet"]["vida_max"] == 104
    assert any(c.get("nome") == "Invisível" for c in p["sheet"]["condicoes"])
    assert _ch("Kaelen")["sheet"]["mana_atual"] == 120 - td.SPELL_MANA_COST[6]


# ---------------------------------------------------------------------------
# 2. A invocação do grupo é jogada pelo jogador
# ---------------------------------------------------------------------------

@pytest.fixture
def com_lobos(druida):
    iniciar_combate(["Kaelen", "Orc"])
    td.combat_action("ability", actor="Kaelen", ability="Conjure Animals", weapon="lobo atroz:2")
    cs = memory.campaign["combat_state"]
    assert "Lobo Atroz de Kaelen 1" in cs["initiative_order"]
    return memory.campaign


def test_a_vez_do_lobo_e_do_jogador(com_lobos):
    _vez("Lobo Atroz de Kaelen 1")
    lobo = _ch("Lobo Atroz de Kaelen 1")
    assert criaturas.controlada_pelo_jogador(lobo)
    snap = td.combat_snapshot()
    assert snap["current_is_party"] is True
    cartao = next(c for c in snap["combatants"] if c["name"] == "Lobo Atroz de Kaelen 1")
    assert cartao["controlada"] and cartao["invocacao_de"] == "Kaelen"
    assert [a["nome"] for a in cartao["armas"]] == ["mordida"]


def test_o_turno_automatico_nao_joga_pelo_lobo(com_lobos):
    _vez("Lobo Atroz de Kaelen 1")
    vida = _ch("Orc")["sheet"]["vida_atual"]
    r = td.execute_npc_turn()
    assert r.startswith("Aviso:") and "o turno é do jogador" in r, r
    assert td._combat_current_actor() == "Lobo Atroz de Kaelen 1"
    assert _ch("Orc")["sheet"]["vida_atual"] == vida


def test_o_jogador_ataca_com_o_lobo(com_lobos, monkeypatch):
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda *a, **k: (18, "d20=18"))
    _vez("Lobo Atroz de Kaelen 1")
    r = td.combat_action("attack", actor="Lobo Atroz de Kaelen 1", target="Orc", weapon="mordida")
    assert r["ok"], r["message"]
    assert _ch("Orc")["sheet"]["vida_atual"] < 300


def test_motor_joga_quando_o_jogador_pede(com_lobos, monkeypatch):
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda *a, **k: (18, "d20=18"))
    _vez("Lobo Atroz de Kaelen 1")
    r = td.combat_action("auto", actor="Lobo Atroz de Kaelen 1")
    assert r["ok"], r["message"]
    assert td._combat_current_actor() != "Lobo Atroz de Kaelen 1"
    assert _ch("Orc")["sheet"]["vida_atual"] < 300


def test_auto_so_vale_para_invocacao_do_grupo(com_lobos):
    _vez("Orc")
    r = td.combat_action("auto", actor="Orc")
    assert not r["ok"] and r["message"].startswith("Erro:")


def test_elemental_que_se_voltou_contra_o_grupo_e_do_motor(com_lobos):
    lobo = _ch("Lobo Atroz de Kaelen 1")
    lobo["lado"] = "inimigo"
    assert not criaturas.controlada_pelo_jogador(lobo)


def test_multiataque_da_invocacao_e_da_forma_selvagem(druida):
    iniciar_combate(["Kaelen", "Orc"])
    criaturas.invocar(_ch("Kaelen"), "elemental da terra", 1, "Conjure Elemental", concentracao=False,
                      persistente=False)
    assert td._numero_de_ataques(_ch("Elemental da Terra de Kaelen")) == 2
    criaturas.transformar(_ch("Kaelen"), "urso pardo")
    assert td._numero_de_ataques(_ch("Kaelen")) == criaturas.FICHAS["urso pardo"].get("multiataque", 1)


def test_familiar_nao_ataca_nem_pelo_jogador(druida):
    td.conjurar_fora_de_combate("Kaelen", "Find Familiar", "", "coruja:1")
    iniciar_combate(["Coruja de Kaelen", "Orc"])
    r = td.attack_roll("Coruja de Kaelen", "Orc", "garras", 6, end_turn=False)
    assert r.startswith("Erro:") and "Ajudar" in r, r


# ---------------------------------------------------------------------------
# 3. Área sem zonas
# ---------------------------------------------------------------------------

def test_bola_de_fogo_sem_zonas_pega_os_escolhidos(mago):
    r = td.use_ability("Mira", "Fireball", "Orc A, Orc B, Orc C", end_turn=False)
    assert "sem zonas: até 4 criaturas" in r and "3 criaturas" in r, r
    for n in ("Orc A", "Orc B", "Orc C"):
        assert _ch(n)["sheet"]["vida_atual"] < 60, n
    assert _ch("Orc D")["sheet"]["vida_atual"] == 60


def test_area_sem_zonas_respeita_o_tamanho(mago):
    td.use_ability("Mira", "Fireball", "Orc A, Orc B, Orc C, Orc D, Orc E", end_turn=False)
    atingidos = [n for n in ("Orc A", "Orc B", "Orc C", "Orc D", "Orc E") if _ch(n)["sheet"]["vida_atual"] < 60]
    assert atingidos == ["Orc A", "Orc B", "Orc C", "Orc D"]


def test_area_que_pega_todos_queima_o_aliado_escolhido(mago):
    td.use_ability("Mira", "Fireball", "Orc A, Brann", end_turn=False)
    assert _ch("Brann")["sheet"]["vida_atual"] < 40


def test_area_so_de_hostis_poupa_o_aliado(mago):
    _ch("Mira")["habilidades"].append(
        {"nome": "Chuva Sagrada", "custo_mana": 2, "dado": "2d6",
         "descricao": "Uma esfera de 6 m de raio: as criaturas hostis sofrem 2d6 de dano de fogo."})
    td.use_ability("Mira", "Chuva Sagrada", "Orc A, Brann, Orc B", end_turn=False)
    assert _ch("Brann")["sheet"]["vida_atual"] == 40
    assert _ch("Orc A")["sheet"]["vida_atual"] < 60 and _ch("Orc B")["sheet"]["vida_atual"] < 60


def test_um_nome_so_segue_o_alvo_unico(mago):
    r = td.use_ability("Mira", "Fireball", "Orc A", end_turn=False)
    assert "Área:" not in r
    assert _ch("Orc A")["sheet"]["vida_atual"] < 60


@pytest.mark.parametrize("magia,esperado", [("Fireball", 4), ("Burning Hands", 2), ("Lightning Bolt", 4),
                                            ("Thunderwave", 3)])
def test_tamanho_da_area_pela_tabela_do_guia(magia, esperado):
    assert td.max_alvos_da_area(_hab(magia)) == esperado


def test_previa_da_area_diz_quantos(mago):
    p = td.prever_area("Mira", "Fireball", "Orc A, Orc B")
    assert p["max_alvos"] == 4 and [a["nome"] for a in p["atingidos"]] == ["Orc A", "Orc B"]
    cs = memory.campaign["combat_state"]
    cs["zonas"] = ["Portão", "Pátio"]
    cs["posicoes"] = {"mira": "Portão", "orc a": "Pátio", "orc b": "Pátio"}
    assert td.prever_area("Mira", "Fireball", "Orc A")["max_alvos"] is None


# ---------------------------------------------------------------------------
# 4. Minutos no relógio
# ---------------------------------------------------------------------------

def test_minutos_se_acumulam_e_viram_hora(campanha):
    memory.campaign["relogio"] = {"dia": 1, "hora": 8}
    td.avancar_minutos(50)
    assert td._hora_legivel().startswith("Dia 1, 08h50")
    td.avancar_minutos(20)
    assert td._hora_legivel().startswith("Dia 1, 09h10")
    assert memory.campaign["relogio"] == {"dia": 1, "hora": 9, "minuto": 10}


@pytest.mark.parametrize("tempo,minutos", [("1 minuto", 1), ("10 minutos", 10), ("1 hora", 60),
                                           ("1 ação", 0), ("1 reação", 0), ("8 horas", 480)])
def test_tempo_de_conjuracao_em_minutos(tempo, minutos):
    assert td.minutos_de_conjuracao(tempo) == minutos


def test_ritual_poe_dez_minutos_no_relogio(campanha, povoar):
    povoar(criar_ficha("Mira", grupo=True, classe="mago", nivel=5, mana=27,
                       habilidades=[_hab("Detect Magic"), _hab("Find Familiar")]))
    memory.campaign["relogio"] = {"dia": 2, "hora": 14}
    r = td.conjurar_fora_de_combate("Mira", "Detect Magic", ritual=True)
    assert r["ok"], r["message"]
    assert memory.campaign["relogio"]["minuto"] == 10 and memory.campaign["relogio"]["hora"] == 14
    assert _ch("Mira")["sheet"]["mana_atual"] == 27
    # Convocar Familiar como ritual: uma hora e dez minutos.
    td.conjurar_fora_de_combate("Mira", "Find Familiar", "", "coruja:1", ritual=True)
    assert (memory.campaign["relogio"]["hora"], memory.campaign["relogio"]["minuto"]) == (15, 20)


def test_conjurar_elemental_leva_um_minuto(druida):
    memory.campaign["relogio"] = {"dia": 1, "hora": 10}
    td.conjurar_fora_de_combate("Kaelen", "Conjure Elemental", "", "elemental do ar:1")
    assert memory.campaign["relogio"].get("minuto") == 1


# ---------------------------------------------------------------------------
# 5. Reação que pergunta
# ---------------------------------------------------------------------------

@pytest.fixture
def emboscada(campanha, povoar, monkeypatch):
    povoar(criar_ficha("Mira", grupo=True, classe="mago", nivel=5, inteligencia=18, mana=30, vida=30, ca=12,
                       habilidades=[_hab("Shield"), {"nome": "Esquiva Sobrenatural", "custo_mana": 0,
                                                     "dado": "", "descricao": ""}]),
           criar_ficha("Orc", vida=40, arma="machado grande", forca=16))
    iniciar_combate(["Mira", "Orc"], indice=1)
    # 8 + 3 + 2 = 13: acerta a CA 12, e o Escudo (17) faria errar.
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda *a, **k: (8, "d20=8"))
    return memory.campaign


def test_tres_modos_por_reacao(emboscada):
    assert reacoes.modo_da_reacao(_ch("Mira"), "escudo arcano") == "auto"
    reacoes.alternar("Mira", "escudo arcano", True, "perguntar")
    assert reacoes.modo_da_reacao(_ch("Mira"), "escudo arcano") == "perguntar"
    d = {r["chave"]: r for r in reacoes.disponiveis(_ch("Mira"))}
    assert d["escudo arcano"]["modo"] == "perguntar" and d["escudo arcano"]["ligada"] is True
    reacoes.alternar("Mira", "escudo arcano", False, "desligada")
    assert reacoes.modo_da_reacao(_ch("Mira"), "escudo arcano") == "desligada"
    reacoes.alternar("Mira", "escudo arcano", True)
    assert reacoes.modo_da_reacao(_ch("Mira"), "escudo arcano") == "auto"


def test_recurso_e_lampejo_nao_perguntam(emboscada):
    assert "indomavel" not in reacoes.PODEM_PERGUNTAR and "lampejos" not in reacoes.PODEM_PERGUNTAR
    assert reacoes.alternar("Mira", "indomavel", True, "perguntar").startswith("Erro:")


def test_o_turno_do_inimigo_para_e_nada_acontece(emboscada):
    reacoes.alternar("Mira", "escudo arcano", True, "perguntar")
    r = td.execute_npc_turn()
    assert "REAÇÃO — Mira decide" in r and "Escudo Arcano" in r, r
    assert _ch("Mira")["sheet"]["vida_atual"] == 30
    assert _ch("Mira")["sheet"]["mana_atual"] == 30
    assert td._combat_current_actor() == "Orc"
    pend = td.combat_snapshot()["reacao_pendente"]
    assert pend["quem"] == "Mira" and pend["chave"] == "escudo arcano" and "13 contra CA 12" in pend["texto"]
    # O turno não roda de novo por cima da pergunta.
    assert td.execute_npc_turn().startswith("Aviso:")


def test_usar_o_escudo_faz_o_mesmo_golpe_errar(emboscada):
    reacoes.alternar("Mira", "escudo arcano", True, "perguntar")
    td.execute_npc_turn()
    r = td.responder_reacao(True)
    assert "usa Escudo Arcano" in r and "d20=8" in r and "erra" in r, r
    assert _ch("Mira")["sheet"]["vida_atual"] == 30
    assert _ch("Mira")["sheet"]["mana_atual"] == 28
    assert td.combat_snapshot()["reacao_pendente"] is None
    assert td._combat_current_actor() == "Mira"


def test_nao_usar_deixa_o_golpe_entrar(emboscada):
    reacoes.alternar("Mira", "escudo arcano", True, "perguntar")
    td.execute_npc_turn()
    r = td.responder_reacao(False)
    assert "não usa Escudo Arcano" in r, r
    assert _ch("Mira")["sheet"]["vida_atual"] < 30
    assert _ch("Mira")["sheet"]["mana_atual"] == 30


def test_o_mesmo_sorteio_depois_da_resposta(emboscada, monkeypatch):
    """Sem fixar o d20: o golpe refeito rola os mesmos dados que pararam o turno."""
    monkeypatch.undo()
    reacoes.alternar("Mira", "escudo arcano", True, "perguntar")
    for semente in range(200):
        random.seed(semente)
        if "REAÇÃO" in td.execute_npc_turn():
            break
        memory.campaign["combat_state"]["current_turn_index"] = 1
        _ch("Mira")["sheet"].update(vida_atual=30, mana_atual=30)
    texto = td.combat_snapshot()["reacao_pendente"]["texto"]
    total = texto.split("(")[1].split(" ")[0]
    random.seed(999)                       # o sorteio de fora não importa
    r = td.responder_reacao(True)
    assert f"= **{total}**" in r, (texto, r)


def test_escudo_que_nao_muda_nada_nao_pergunta(emboscada, monkeypatch):
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda *a, **k: (15, "d20=15"))   # 20: acerta mesmo com +5
    reacoes.alternar("Mira", "escudo arcano", True, "perguntar")
    r = td.execute_npc_turn()
    assert "REAÇÃO" not in r and _ch("Mira")["sheet"]["vida_atual"] < 30, r


def test_a_pergunta_desfaz_o_que_o_turno_ja_tinha_feito(emboscada):
    """O orc anda até a zona da maga e ataca: parado o turno, ele volta para onde estava."""
    cs = memory.campaign["combat_state"]
    cs["zonas"] = ["Portão", "Pátio"]
    cs["posicoes"] = {"mira": "Pátio", "orc": "Portão"}
    reacoes.alternar("Mira", "escudo arcano", True, "perguntar")
    r = td.execute_npc_turn()
    assert "REAÇÃO" in r, r
    assert td._zona_de("Orc") == "Portão"
    assert not any("Orc" in (e.get("msg") or "") for e in memory.campaign["combat_state"]["log"])
    r = td.responder_reacao(True)
    assert td._zona_de("Orc") == "Pátio" and "erra" in r, r


def test_duas_perguntas_no_mesmo_golpe(emboscada):
    reacoes.alternar("Mira", "escudo arcano", True, "perguntar")
    reacoes.alternar("Mira", "esquiva sobrenatural", True, "perguntar")
    td.execute_npc_turn()
    r = td.responder_reacao(False)
    assert "REAÇÃO — Mira decide" in r and "Esquiva Sobrenatural" in r, r
    pend = memory.campaign["combat_state"]["reacao_pendente"]
    assert pend["respostas"] == [False] and pend["chave"] == "esquiva sobrenatural"
    r = td.responder_reacao(True)
    assert "Esquiva Sobrenatural: o dano cai pela metade" in r, r


def test_modo_automatico_nao_para(emboscada):
    reacoes.alternar("Mira", "esquiva sobrenatural", True, "perguntar")   # alguém pergunta...
    r = td.execute_npc_turn()                                              # ...mas o Escudo é automático
    assert "REAÇÃO" not in r and "conjura Escudo Arcano" in r, r


def test_pergunta_que_caducou(emboscada):
    reacoes.alternar("Mira", "escudo arcano", True, "perguntar")
    td.execute_npc_turn()
    memory.campaign["combat_state"]["current_turn_index"] = 0
    assert td.responder_reacao(True).startswith("Aviso:")
    assert memory.campaign["combat_state"].get("reacao_pendente") is None


def test_a_tela_responde_pela_acao_reagir(emboscada):
    reacoes.alternar("Mira", "escudo arcano", True, "perguntar")
    r = td.combat_action("enemy")
    assert r["snapshot"]["reacao_pendente"]["quem"] == "Mira"
    r = td.combat_action("reagir", weapon="sim")
    assert r["ok"] and r["snapshot"]["reacao_pendente"] is None
    assert _ch("Mira")["sheet"]["mana_atual"] == 28


def test_fora_do_turno_do_inimigo_a_reacao_nao_pergunta(emboscada):
    reacoes.alternar("Mira", "escudo arcano", True, "perguntar")
    assert reacoes._respostas is None
    assert reacoes._confirmar(_ch("Mira"), "escudo arcano", "?") is True


def test_a_pausa_nao_e_engolida_por_except_exception():
    assert issubclass(reacoes.PerguntaDeReacao, BaseException)
    assert not issubclass(reacoes.PerguntaDeReacao, Exception)


def test_contramagica_pergunta_e_respeita_a_resposta(campanha, povoar):
    povoar(criar_ficha("Mira", grupo=True, classe="mago", nivel=7, inteligencia=18, mana=30,
                       habilidades=[_hab("Counterspell", 5)]),
           criar_ficha("Bruxo", vida=30, habilidades=[_hab("Magic Missile")]))
    iniciar_combate(["Mira", "Bruxo"], indice=1)
    reacoes.alternar("Mira", "contramagica", True, "perguntar")
    hab = _ch("Bruxo")["habilidades"][0]
    try:
        reacoes._respostas, reacoes._indice = [], 0
        with pytest.raises(reacoes.PerguntaDeReacao) as e:
            reacoes.contramagica(_ch("Bruxo"), hab)
        assert e.value.chave == "contramagica" and "Mísseis Mágicos" in e.value.texto
        assert _ch("Mira")["sheet"]["mana_atual"] == 30
        reacoes._respostas, reacoes._indice = [False], 0
        assert reacoes.contramagica(_ch("Bruxo"), hab) == ""
        assert _ch("Mira")["sheet"]["mana_atual"] == 30
        reacoes._respostas, reacoes._indice = [True], 0
        assert "anulada" in reacoes.contramagica(_ch("Bruxo"), hab)
    finally:
        reacoes._respostas, reacoes._indice = None, 0
