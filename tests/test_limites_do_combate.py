"""
test_limites_do_combate.py

Os limites que ficaram dos lotes anteriores:

1. Redemoinho e Engolfar pegavam uma criatura só: pegam a área (cubo de 3 m).
2. A salvaguarda do jogador pela bandeja de dados não aplicava a condição do
   poder ou da magia, e dava metade a quem devia levar nada.
3. No modo narrado, as salvaguardas do grupo em magia de área e de vários
   alvos eram roladas pelo motor; agora esperam o dado do jogador.
4. Sem zonas, a área confiava só na escolha: agora pega também quem está
   colado (trocou golpes) no alvo escolhido.
5. Indomável, Alma do Diamante e Lampejos também perguntam.
6. A paralisia do carniçal poupa o elfo, não o meio-elfo.
7. O inimigo pode querer o grupo vivo (estratégia "capturar"); e atacar quem
   se rendeu tem consequência.
8. A tela encerra a luta e foge em grupo.
"""
import pytest

from rpg import criaturas, manobras, memory, reacoes, resolucao, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _ch(nome):
    return memory.campaign["characters"].get(memory.char_key(nome))


def _hab(nome, custo=2):
    return {"nome": nome, "custo_mana": custo, "dado": "", "descricao": "",
            "nivel_magia": (resolucao._magia_srd({"nome": nome}) or {}).get("nivel", 1)}


def _conds(nome):
    return [c.get("nome") if isinstance(c, dict) else c for c in _ch(nome)["sheet"].get("condicoes") or []]


def _vez(nome):
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index(nome)
    cs["turn_token"] = int(cs.get("turn_token", 0) or 0) + 1
    td._reset_turn_economy(cs)


def _d20(monkeypatch, valor):
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda *a, **k: (valor, f"d20={valor}"))


def _falha(monkeypatch):
    monkeypatch.setattr(td, "_rolar_salvaguarda", lambda *a, **k: (False, "salvaguarda: falhou"))


# ---------------------------------------------------------------------------
# 1. O Redemoinho pega a área
# ---------------------------------------------------------------------------

@pytest.fixture
def tempestade(campanha, povoar):
    povoar(criar_ficha("Kaelen", grupo=True, classe="druida", nivel=9, mana=60, vida=40),
           criar_ficha("Orc A", vida=60, raca="orc"), criar_ficha("Orc B", vida=60, raca="orc"),
           criar_ficha("Orc C", vida=60, raca="orc"))
    iniciar_combate(["Kaelen", "Orc A", "Orc B", "Orc C"])
    criaturas.invocar(_ch("Kaelen"), "elemental do ar", 1, "Conjure Elemental", concentracao=False, persistente=False)
    return memory.campaign


def test_redemoinho_pega_a_zona(tempestade, monkeypatch):
    _falha(monkeypatch)
    cs = memory.campaign["combat_state"]
    cs["zonas"] = ["Portão", "Pátio"]
    cs["posicoes"] = {"kaelen": "Pátio", "orc a": "Pátio", "orc b": "Pátio", "orc c": "Portão",
                      memory.char_key("Elemental do Ar de Kaelen"): "Pátio"}
    r = td.use_ability("Elemental do Ar de Kaelen", "Redemoinho", "", end_turn=False, _skip_turn_check=True)
    assert "Área: cubo de 3 m" in r, r
    assert "Caído" in _conds("Orc A") and "Caído" in _conds("Orc B") and "Caído" not in _conds("Orc C")
    assert _ch("Kaelen")["sheet"]["vida_atual"] == 40          # criaturas hostis: o druida fica de fora


def test_redemoinho_sem_zonas_ate_duas(tempestade, monkeypatch):
    _falha(monkeypatch)
    assert td.max_alvos_da_area({"nome": "Redemoinho", "descricao": criaturas.FICHAS["elemental do ar"]["poderes"][0]["descricao"]}) == 2
    td.use_ability("Elemental do Ar de Kaelen", "Redemoinho", "Orc A, Orc B, Orc C", end_turn=False,
                   _skip_turn_check=True)
    caidos = [n for n in ("Orc A", "Orc B", "Orc C") if "Caído" in _conds(n)]
    assert caidos == ["Orc A", "Orc B"]


# ---------------------------------------------------------------------------
# 2 e 3. O dado do jogador
# ---------------------------------------------------------------------------

@pytest.fixture
def bruxa(campanha, povoar):
    povoar(criar_ficha("Brann", grupo=True, vida=40, sabedoria=10),
           criar_ficha("Lia", grupo=True, vida=40),
           criar_ficha("Bruxa", vida=40, sabedoria=16, carisma=16,
                       habilidades=[_hab("Hold Person", 3), _hab("Sacred Flame", 0), _hab("Fireball", 5)]),
           criar_ficha("Orc", vida=60, raca="orc"))
    _ch("Bruxa")["sheet"].update(classe="clérigo", mana_atual=40, mana_max=40)
    iniciar_combate(["Bruxa", "Brann", "Lia", "Orc"])
    return memory.campaign


def test_condicao_da_magia_aplicada_com_o_dado_do_jogador(bruxa):
    r = td.use_ability("Bruxa", "Hold Person", "Brann", end_turn=True, _skip_turn_check=True)
    assert "AGUARDANDO TESTE DE RESISTÊNCIA" in r and "resolve_saving_throw('Brann'" in r, r
    pend = memory.campaign["combat_state"]["salvaguardas_pendentes"][0]
    cd = pend["cd"]
    r = td.resolve_saving_throw("Brann", "sabedoria", cd, cd - 5, 0)
    assert "PARALISADO" in r and "Paralisado" in _conds("Brann"), r
    c = next(c for c in _ch("Brann")["sheet"]["condicoes"] if c.get("nome") == "Paralisado")
    assert c["salvaguarda_fim"]["cd"] == cd
    assert not memory.campaign["combat_state"]["salvaguardas_pendentes"]


def test_quem_passa_nao_leva_a_condicao(bruxa):
    td.use_ability("Bruxa", "Hold Person", "Brann", end_turn=True, _skip_turn_check=True)
    cd = memory.campaign["combat_state"]["salvaguardas_pendentes"][0]["cd"]
    td.resolve_saving_throw("Brann", "sabedoria", cd, cd + 5, 0)
    assert "Paralisado" not in _conds("Brann")


def test_truque_sem_metade_nao_fere_quem_passa(bruxa):
    r = td.use_ability("Bruxa", "Sacred Flame", "Brann", end_turn=True, _skip_turn_check=True)
    assert "Sucesso: **0**" in r, r
    pend = memory.campaign["combat_state"]["salvaguardas_pendentes"][0]
    r = td.resolve_saving_throw("Brann", "destreza", pend["cd"], 30, 99)
    assert "(nenhum dano)" in r and _ch("Brann")["sheet"]["vida_atual"] == 40, r


def test_narrado_area_espera_o_dado_do_grupo(bruxa, monkeypatch):
    memory.campaign["combat_mode"] = "narrado"
    r = td.use_ability("Bruxa", "Fireball", "Brann, Orc", end_turn=True, _skip_turn_check=True)
    assert "Brann: espera o dado do jogador" in r and "AGUARDANDO TESTES DE RESISTÊNCIA" in r, r
    assert _ch("Brann")["sheet"]["vida_atual"] == 40 and _ch("Orc")["sheet"]["vida_atual"] < 60
    assert td._combat_current_actor() == "Bruxa"                  # o turno espera
    pend = memory.campaign["combat_state"]["salvaguardas_pendentes"][0]
    r = td.resolve_saving_throw("Brann", "destreza", pend["cd"], 1, 0)
    assert _ch("Brann")["sheet"]["vida_atual"] == 40 - pend["dano"], r
    assert td._combat_current_actor() != "Bruxa"


def test_dois_dados_do_grupo_o_turno_passa_no_ultimo(bruxa):
    memory.campaign["combat_mode"] = "narrado"
    td.use_ability("Bruxa", "Fireball", "Brann, Lia", end_turn=True, _skip_turn_check=True)
    pend = memory.campaign["combat_state"]["salvaguardas_pendentes"]
    assert [p["alvo"] for p in pend] == ["Brann", "Lia"]
    r = td.resolve_saving_throw("Brann", "destreza", pend[0]["cd"], 30, 0)
    assert "Ainda esperam o dado: Lia" in r and td._combat_current_actor() == "Bruxa", r
    td.resolve_saving_throw("Lia", "destreza", pend[0]["cd"], 30, 0)
    assert td._combat_current_actor() != "Bruxa"


def test_na_tela_o_motor_rola(bruxa):
    r = td.use_ability("Bruxa", "Fireball", "Brann, Orc", end_turn=False, _skip_turn_check=True)
    assert "espera o dado" not in r and _ch("Brann")["sheet"]["vida_atual"] < 40, r


# ---------------------------------------------------------------------------
# 4. Sem zonas: quem está colado no alvo
# ---------------------------------------------------------------------------

@pytest.fixture
def melee(campanha, povoar, monkeypatch):
    povoar(criar_ficha("Mira", grupo=True, classe="mago", nivel=9, mana=60,
                       habilidades=[_hab("Fireball", 5)]),
           criar_ficha("Brann", grupo=True, vida=60),
           criar_ficha("Orc A", vida=60, raca="orc"), criar_ficha("Orc B", vida=60, raca="orc"))
    iniciar_combate(["Mira", "Brann", "Orc A", "Orc B"])
    _d20(monkeypatch, 15)
    return memory.campaign


def test_area_pega_quem_esta_colado_no_alvo(melee):
    td.attack_roll("Brann", "Orc A", "espada longa", 6, end_turn=False, _skip_turn_check=True)
    p = td.prever_area("Mira", "Fireball", "Orc A, Orc B")
    assert p["aliados_atingidos"] == ["Brann"], p
    vida = _ch("Brann")["sheet"]["vida_atual"]
    td.use_ability("Mira", "Fireball", "Orc A, Orc B", end_turn=False)
    assert _ch("Brann")["sheet"]["vida_atual"] < vida


def test_quem_nao_trocou_golpes_nao_entra(melee):
    p = td.prever_area("Mira", "Fireball", "Orc A, Orc B")
    assert p["aliados_atingidos"] == []


def test_engajamento_antigo_expira(melee):
    td.attack_roll("Brann", "Orc A", "espada longa", 6, end_turn=False, _skip_turn_check=True)
    memory.campaign["combat_state"]["round"] = 3
    assert td.prever_area("Mira", "Fireball", "Orc A, Orc B")["aliados_atingidos"] == []


def test_area_so_de_hostis_poupa_o_colado(melee):
    _ch("Mira")["habilidades"].append(
        {"nome": "Chuva Sagrada", "custo_mana": 2, "dado": "2d6",
         "descricao": "Uma esfera de 6 m de raio: as criaturas hostis sofrem 2d6 de dano de fogo."})
    td.attack_roll("Brann", "Orc A", "espada longa", 6, end_turn=False, _skip_turn_check=True)
    vida = _ch("Brann")["sheet"]["vida_atual"]
    td.use_ability("Mira", "Chuva Sagrada", "Orc A, Orc B", end_turn=False)
    assert _ch("Brann")["sheet"]["vida_atual"] == vida


# ---------------------------------------------------------------------------
# 5. Indomável, Alma do Diamante e Lampejos perguntam
# ---------------------------------------------------------------------------

@pytest.fixture
def guerreiro(campanha, povoar):
    povoar(criar_ficha("Brann", grupo=True, classe="guerreiro", nivel=9, vida=60,
                       habilidades=[{"nome": "Indomável", "custo_mana": 0, "dado": "", "descricao": ""}]),
           criar_ficha("Orc", vida=60))
    iniciar_combate(["Brann", "Orc"], indice=1)
    reacoes.alternar("Brann", "indomavel", True, "perguntar")
    yield memory.campaign
    reacoes._respostas, reacoes._indice = None, 0


def test_indomavel_pergunta(guerreiro):
    reacoes._respostas, reacoes._indice = [], 0
    with pytest.raises(reacoes.PerguntaDeReacao) as e:
        td._rolar_salvaguarda(_ch("Brann"), "sabedoria", 99)
    assert e.value.chave == "indomavel" and "Indomável" in e.value.texto
    usos = td.usos_restantes(_ch("Brann"), "Indomável")
    reacoes._respostas, reacoes._indice = [False], 0
    passou, linha = td._rolar_salvaguarda(_ch("Brann"), "sabedoria", 99)
    assert not passou and "Indomável" not in linha
    assert td.usos_restantes(_ch("Brann"), "Indomável") == usos
    reacoes._respostas, reacoes._indice = [True], 0
    _, linha = td._rolar_salvaguarda(_ch("Brann"), "sabedoria", 99)
    assert "Indomável, de novo" in linha
    assert td.usos_restantes(_ch("Brann"), "Indomável") == usos - 1


def test_lampejo_pergunta(campanha, povoar):
    povoar(criar_ficha("Mira", grupo=True, classe="mago", nivel=6,
                       habilidades=[{"nome": "Lampejos de Adivinhação", "custo_mana": 0, "dado": "", "descricao": ""}]),
           criar_ficha("Brann", grupo=True, vida=40))
    _ch("Mira")["sheet"]["lampejos"] = [20, 19]
    reacoes.alternar("Mira", "lampejos", True, "perguntar")
    try:
        reacoes._respostas, reacoes._indice = [], 0
        with pytest.raises(reacoes.PerguntaDeReacao):
            reacoes.lampejo_na_salvaguarda(_ch("Brann"), 0, 15)
        reacoes._respostas, reacoes._indice = [False], 0
        assert reacoes.lampejo_na_salvaguarda(_ch("Brann"), 0, 15) == (False, "")
        assert _ch("Mira")["sheet"]["lampejos"] == [20, 19]
    finally:
        reacoes._respostas, reacoes._indice = None, 0


# ---------------------------------------------------------------------------
# 6. O carniçal poupa o elfo, não o meio-elfo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raca,paralisa", [("elfo", False), ("meio-elfo", True), ("humano", True)])
def test_carnical_e_os_elfos(campanha, povoar, monkeypatch, raca, paralisa):
    povoar(criar_ficha("Brann", grupo=True, vida=60, raca=raca),
           {"name": "Carniçal", "status": "inimigo", "lado": "inimigo", "party_member": False, "description": "",
            "traits": "", "notes": "", "habilidades": [], "inventario": [], "sheet": criaturas.montar_sheet("carnical")})
    iniciar_combate(["Brann", "Carniçal"], indice=1)
    _d20(monkeypatch, 15)
    _falha(monkeypatch)
    td.attack_roll("Carniçal", "Brann", "garras", 6, end_turn=False, _skip_turn_check=True)
    assert ("Paralisado" in _conds("Brann")) is paralisa


def test_sono_continua_poupando_meio_elfo():
    from rpg import tracos
    meio = {"name": "Lia", "sheet": {"raca": "meio-elfo"}}
    assert "ancestralidade feérica" in tracos.recusa_de_tipo(_hab("Sleep"), meio)


# ---------------------------------------------------------------------------
# 7. Capturar e quem se rendeu
# ---------------------------------------------------------------------------

def test_estrategia_capturar_nocauteia(campanha, povoar, monkeypatch):
    povoar(criar_ficha("Brann", grupo=True, vida=1),
           criar_ficha("Caçador", vida=40, arma="clava"))
    iniciar_combate(["Brann", "Caçador"], indice=1)
    _d20(monkeypatch, 18)
    assert "capturar" in td.set_npc_strategy("Caçador", "capturar")
    td.execute_npc_turn()
    assert _ch("Brann")["status"] == "estabilizado", _ch("Brann")["status"]


def test_atacar_quem_se_rendeu_tem_consequencia(campanha, povoar, monkeypatch):
    povoar(criar_ficha("Brann", grupo=True, vida=40, carisma=18),
           criar_ficha("Orc", vida=40, raca="orc"), criar_ficha("Goblin", vida=20, raca="goblin"))
    iniciar_combate(["Brann", "Orc", "Goblin"])
    _d20(monkeypatch, 15)
    td.set_combat_side("Orc", "rendido")
    r = td.attack_roll("Brann", "Orc", "espada longa", 6, end_turn=False, _skip_turn_check=True)
    assert "tinha se rendido" in r and _ch("Orc")["status"] == "inimigo", r
    assert _ch("Goblin")["sheet"]["recusa_rendicao"]
    r = manobras.pedir_rendicao("Brann", "Goblin", "intimidar")
    assert "viu o que fizeram" in r and _ch("Goblin")["status"] != "rendido"


# ---------------------------------------------------------------------------
# 8. Encerrar a luta e fugir em grupo
# ---------------------------------------------------------------------------

@pytest.fixture
def emboscada(campanha, povoar):
    povoar(criar_ficha("Brann", grupo=True, vida=40), criar_ficha("Lia", grupo=True, vida=30),
           criar_ficha("Orc", vida=40, raca="orc"))
    iniciar_combate(["Brann", "Lia", "Orc"])
    return memory.campaign


def test_encerrar_com_inimigo_de_pe_e_luta_interrompida(emboscada):
    r = td.combat_action("end", actor="Brann")
    res = memory.campaign["combat_state"]["result"]
    assert res["outcome"] == "interrompido" and res["de_pe"] == ["Orc"], res
    texto = td.combat_recap_payload()
    assert "LUTA ENCERRADA PELO JOGADOR" in texto and "Orc" in texto


def test_fugir_em_grupo(emboscada, monkeypatch):
    _d20(monkeypatch, 18)
    r = td.combat_action("flee_all", actor="Brann")
    assert r["ok"] and "O grupo foge" in r["message"], r["message"]
    assert "ATAQUE(S) DE OPORTUNIDADE" in r["message"]
    assert not memory.campaign["combat_state"]["is_active"]
    res = memory.campaign["combat_state"]["result"]
    assert res["outcome"] == "fuga" and {c["name"] for c in res["sobreviventes"]} <= {"Brann", "Lia"}
    texto = td.combat_recap_payload()
    assert "FUGA" in texto and "NÃO conceda XP" in texto
    assert (_ch("Brann").get("status") or "vivo") != "fugiu"
