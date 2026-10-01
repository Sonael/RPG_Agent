"""
test_caracteristicas_de_classe.py

"Falta fazer alguma coisa no combate?" A varredura das características com os
nomes que o jogo grava nas fichas achou 82 que caíam em "o Mestre decide".
Entre elas, as que definem a classe na luta: a Destruição Divina do paladino,
o Ataque Atordoante e o ki do monge, a Forma Selvagem do druida, o Indomável
do guerreiro. E duas que o motor já sabia resolver, mas com outro nome:
Imposição de Mãos (= Cura pelas Mãos) e Inspiração Bárdica (= Inspiração de
Bardo).
"""
import random

import pytest

from rpg import criaturas, habilidade, memory, resolucao, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _ch(nome):
    return memory.campaign["characters"][memory.char_key(nome)]


def _hab(nome, custo=0):
    return {"nome": nome, "custo_mana": custo, "dado": "", "descricao": ""}


def _vez(nome):
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index(nome)
    cs["turn_token"] = int(cs.get("turn_token", 0) or 0) + 1
    td._reset_turn_economy(cs)


def _acertar(monkeypatch, d20=15):
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda *a, **k: (d20, f"d20={d20}"))


def _falhar_salvaguardas(monkeypatch):
    monkeypatch.setattr(td, "_rolar_salvaguarda",
                        lambda *a, **k: (False, "salvaguarda: 1 vs CD 13"))


def _usar(ator, hab, alvo="", modo=""):
    return td.combat_action("ability", actor=ator, ability=hab, target=alvo, weapon=modo)


def _atacar(ator, alvo, arma=""):
    return td.combat_action("attack", actor=ator, target=alvo,
                            weapon=arma or _ch(ator)["sheet"]["equipamentos"]["arma_principal"])


@pytest.fixture
def luta(campanha, povoar):
    povoar(
        criar_ficha("Brann", grupo=True, classe="paladino", nivel=5, carisma=16, mana=10,
                    habilidades=[_hab("Destruição Divina"), _hab("Canalizar Divindade (Arma Sagrada)"),
                                 _hab("Canalizar Divindade (Voto de Inimizade)")]),
        criar_ficha("Lin", grupo=True, classe="monge", nivel=5, destreza=16, sabedoria=14,
                    arma="ataque desarmado",
                    habilidades=[_hab("Artes Marciais"), _hab("Ki"), _hab("Ataque Atordoante"),
                                 _hab("Corpo Vazio"), _hab("Mente Vazia")]),
        criar_ficha("Orc", vida=60, raca="orc", arma="machado grande"),
        criar_ficha("Esqueleto", vida=60, raca="esqueleto", tipo="undead", arma="espada curta"),
    )
    iniciar_combate(["Brann", "Lin", "Orc", "Esqueleto"])
    _vez("Brann")
    return memory.campaign


# ---------------------------------------------------------------------------
# Nomes que o jogo grava e que caíam como narrativa
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nome, chave", [
    ("Imposição de Mãos", "cura pelas maos"),
    ("Inspiração Bárdica", "inspiracao de bardo"),
    ("Ataque Descuidado", "ataque imprudente"),
    ("Combate Divino", "destruicao divina"),
    ("Atordoamento", "ataque atordoante"),
    ("Canalizar Divindade (Repelir Mortos-Vivos)", "expulsar mortos vivos"),
    ("Contra-Encanto", "contra encanto"),
    ("Intervenção Divina Inicial", "intervencao divina"),
])
def test_nomes_do_jogo_caem_na_regra(nome, chave):
    r = resolucao.como_resolve({"nome": nome})
    assert r["tipo"] == "acao_de_classe" and r["chave"] == chave, r


@pytest.mark.parametrize("nome", ["Ki", "Indomável", "Alma do Diamante", "Mente Vazia",
                                  "Golpe Divino Aprimorado"])
def test_passivas_que_o_motor_aplica(nome):
    r = resolucao.como_resolve({"nome": nome, "descricao": "1 vez por descanso longo: algo"})
    assert r["tipo"] == "passiva" and "motor" in r["texto"], r


# ---------------------------------------------------------------------------
# Destruição Divina
# ---------------------------------------------------------------------------

def test_destruicao_divina_soma_no_acerto_e_gasta_a_mana(luta, monkeypatch):
    _acertar(monkeypatch)
    r = _usar("Brann", "Destruição Divina", modo="1")
    assert r["ok"], r["message"]
    assert _ch("Brann")["sheet"]["mana_atual"] == 10   # nada gasto ainda
    saida = _atacar("Brann", "Orc")["message"]
    assert "Destruição Divina: 2d8" in saida and "gasta 2 mana" in saida, saida
    assert _ch("Brann")["sheet"]["mana_atual"] == 8
    assert not any(e.get("nome") == "Destruição Divina" for e in td._efeitos_de(_ch("Brann")))


def test_destruicao_divina_contra_morto_vivo_soma_mais_um_dado(luta, monkeypatch):
    _acertar(monkeypatch)
    _usar("Brann", "Destruição Divina", modo="2")
    saida = _atacar("Brann", "Esqueleto")["message"]
    assert "Destruição Divina: 4d8" in saida and "morto-vivo" in saida, saida
    assert _ch("Brann")["sheet"]["mana_atual"] == 7


def test_destruicao_divina_que_erra_nao_gasta_e_acaba_no_turno(luta, monkeypatch):
    _acertar(monkeypatch, d20=2)
    _usar("Brann", "Destruição Divina", modo="1")
    saida = _atacar("Brann", "Orc")["message"]
    assert "ERROU" in saida
    assert _ch("Brann")["sheet"]["mana_atual"] == 10
    td.combat_action("end_turn", actor="Brann")
    assert not any(e.get("nome") == "Destruição Divina" for e in td._efeitos_de(_ch("Brann")))


def test_destruicao_divina_sem_mana_recusa(luta):
    _ch("Brann")["sheet"]["mana_atual"] = 1
    r = _usar("Brann", "Destruição Divina", modo="1")
    assert not r["ok"] and "mana" in r["message"]


def test_cartao_da_destruicao_oferece_os_circulos(luta):
    r = habilidade.resolver(_hab("Destruição Divina"), _ch("Brann"))
    assert [m["id"] for m in r["modos"]] == ["1", "2"]
    assert "3 mana" in r["modos"][1]["texto"]


# ---------------------------------------------------------------------------
# Monge: Artes Marciais, Ataque Atordoante, Corpo Vazio, Mente Vazia
# ---------------------------------------------------------------------------

def test_artes_marciais_usa_des_e_o_dado_do_monge(luta):
    assert td._artes_marciais_no_golpe(_ch("Lin"), "ataque desarmado", None) == ("destreza", 6)
    _ch("Lin")["sheet"]["equipamentos"]["armadura"] = "Cota de Malha"
    assert td._artes_marciais_no_golpe(_ch("Lin"), "ataque desarmado", None) is None


def test_ataque_atordoante_atordoa_ate_o_fim_do_proximo_turno_do_monge(luta, monkeypatch):
    _acertar(monkeypatch)
    _falhar_salvaguardas(monkeypatch)
    _vez("Lin")
    assert _usar("Lin", "Ataque Atordoante")["ok"]
    assert td.usos_restantes(_ch("Lin"), "Ki") == 5      # só gasta no acerto
    saida = _atacar("Lin", "Orc")["message"]
    assert "ATORDOADO" in saida, saida
    assert td.usos_restantes(_ch("Lin"), "Ki") == 4
    # Fim do turno do monge: continua; o orc não age no turno dele.
    td.combat_action("end_turn", actor="Lin")
    assert td._impedido_de_agir(_ch("Orc"))
    # Fim do PRÓXIMO turno do monge: acaba.
    _vez("Lin")
    td.combat_action("end_turn", actor="Lin")
    assert not td._impedido_de_agir(_ch("Orc"))


def test_ataque_atordoante_que_erra_nao_gasta_ki(luta, monkeypatch):
    _acertar(monkeypatch, d20=2)
    _vez("Lin")
    _usar("Lin", "Ataque Atordoante")
    _atacar("Lin", "Orc")
    assert td.usos_restantes(_ch("Lin"), "Ki") == 5


def test_corpo_vazio_custa_quatro_de_ki(luta):
    _vez("Lin")
    _ch("Lin")["sheet"]["usos"] = {"ki": 3}
    r = _usar("Lin", "Corpo Vazio")
    assert not r["ok"] and "precisa de 4" in r["message"]
    _ch("Lin")["sheet"]["usos"] = {"ki": 5}
    assert _usar("Lin", "Corpo Vazio")["ok"]
    assert td.usos_restantes(_ch("Lin"), "Ki") == 1
    assert td._has_condition_effect(_ch("Lin"), "attack_advantage")   # Invisível


def test_mente_vazia_e_imune_a_amedrontado(luta, monkeypatch):
    _falhar_salvaguardas(monkeypatch)
    povo = _ch("Orc")
    povo["habilidades"] = [_hab("Presença Intimidadora")]
    _vez("Orc")
    saida = td.use_ability("Orc", "Presença Intimidadora", "Lin", end_turn=False)
    assert "imune a Amedrontado" in saida
    assert not any(c.get("nome") == "Amedrontado" for c in _ch("Lin")["sheet"]["condicoes"])


# ---------------------------------------------------------------------------
# Indomável, Contra-Encanto, Golpe de Sorte, Intervenção Divina
# ---------------------------------------------------------------------------

def _sequencia(monkeypatch, valores):
    it = iter(valores)
    monkeypatch.setattr(random, "randint", lambda a, b: next(it))


def test_indomavel_refaz_a_salvaguarda_que_falhou(campanha, povoar, monkeypatch):
    povoar(criar_ficha("Tor", grupo=True, nivel=9, habilidades=[_hab("Indomável")]))
    _sequencia(monkeypatch, [1, 20])
    passou, linha = td._rolar_salvaguarda(_ch("Tor"), "sabedoria", 15)
    assert passou and "Indomável" in linha
    assert td.usos_restantes(_ch("Tor"), "Indomável") == 0


def test_indomavel_desligado_nao_e_usado(campanha, povoar, monkeypatch):
    povoar(criar_ficha("Tor", grupo=True, nivel=9, habilidades=[_hab("Indomável")],
                       reacoes_desligadas=["indomavel"]))
    _sequencia(monkeypatch, [1, 20])
    passou, _ = td._rolar_salvaguarda(_ch("Tor"), "sabedoria", 15)
    assert not passou


def test_contra_encanto_da_vantagem_so_contra_medo_e_encanto(campanha, povoar, monkeypatch):
    povoar(criar_ficha("Bia", grupo=True, classe="bardo", nivel=6, habilidades=[_hab("Contra-Encanto")]),
           criar_ficha("Tor", grupo=True), criar_ficha("Orc"))
    iniciar_combate(["Bia", "Tor", "Orc"])
    _vez("Bia")
    assert _usar("Bia", "Contra-Encanto")["ok"]
    # d20 5 e 18, CD 15: com vantagem passa (18), sem vantagem falha (5).
    _sequencia(monkeypatch, [5, 18])
    passou, linha = td._rolar_salvaguarda(_ch("Tor"), "sabedoria", 15, contra="amedrontado")
    assert passou and "Contra-Encanto" in linha
    _sequencia(monkeypatch, [5, 18])
    assert not td._rolar_salvaguarda(_ch("Tor"), "sabedoria", 15)[0]


def test_golpe_de_sorte_transforma_o_erro_em_acerto(campanha, povoar, monkeypatch):
    povoar(criar_ficha("Ina", grupo=True, classe="ladino", nivel=20, habilidades=[_hab("Golpe de Sorte")]),
           criar_ficha("Orc", vida=200))
    iniciar_combate(["Ina", "Orc"])
    _vez("Ina")
    _acertar(monkeypatch, d20=1)
    assert _usar("Ina", "Golpe de Sorte")["ok"]
    saida = _atacar("Ina", "Orc")["message"]
    assert "o erro vira acerto" in saida and "ACERTO" in saida
    assert _ch("Orc")["sheet"]["vida_atual"] < 200


def test_intervencao_divina_rola_o_d100(campanha, povoar, monkeypatch):
    povoar(criar_ficha("Kae", grupo=True, classe="clérigo", nivel=10,
                       habilidades=[_hab("Intervenção Divina")]), criar_ficha("Orc"))
    iniciar_combate(["Kae", "Orc"])
    _vez("Kae")
    monkeypatch.setattr(random, "randint", lambda a, b: 7)
    r = _usar("Kae", "Intervenção Divina")
    assert r["ok"] and "INTERVÉM" in r["message"]
    _vez("Kae")
    assert not _usar("Kae", "Intervenção Divina")["ok"]     # 1 por descanso longo


# ---------------------------------------------------------------------------
# Canalizar Divindade do paladino de Devoção e Vingança
# ---------------------------------------------------------------------------

def test_arma_sagrada_soma_carisma_e_voto_da_vantagem_so_no_alvo(luta):
    assert _usar("Brann", "Canalizar Divindade (Arma Sagrada)")["ok"]
    mods = td._mods_de_ataque(_ch("Brann"), _ch("Orc"), True)
    assert mods["bonus"] == 3
    _vez("Brann")
    _ch("Brann")["sheet"]["usos"] = {}
    assert _usar("Brann", "Canalizar Divindade (Voto de Inimizade)", alvo="Orc")["ok"]
    assert td._mods_de_ataque(_ch("Brann"), _ch("Orc"), True)["vantagem"]
    assert not td._mods_de_ataque(_ch("Brann"), _ch("Esqueleto"), True)["vantagem"]


# ---------------------------------------------------------------------------
# Forma Selvagem
# ---------------------------------------------------------------------------

@pytest.fixture
def druida(campanha, povoar):
    povoar(criar_ficha("Ravi", grupo=True, classe="druida", nivel=4, vida=20,
                       habilidades=[_hab("Forma Selvagem"), _hab("Fire Bolt")]),
           criar_ficha("Orc", vida=60))
    iniciar_combate(["Ravi", "Orc"])
    _vez("Ravi")
    return memory.campaign


def test_forma_selvagem_respeita_o_nd_do_nivel(druida):
    modos = resolucao.modos_de("forma selvagem", _ch("Ravi"))
    assert "lobo" in modos and "urso negro" in modos
    assert "urso pardo" not in modos and "aguia gigante" not in modos


def test_forma_selvagem_troca_a_ficha_e_volta_com_o_dano_que_sobra(druida):
    r = _usar("Ravi", "Forma Selvagem", modo="lobo")
    assert r["ok"], r["message"]
    s = _ch("Ravi")["sheet"]
    assert (s["vida_atual"], s["ca"]) == (11, 13)
    assert [a["nome"] for a in td._combatant_weapons(_ch("Ravi"))] == ["mordida"]
    assert td.usos_restantes(_ch("Ravi"), "Forma Selvagem") == 1
    # A fera não conjura.
    _vez("Ravi")
    assert td.use_ability("Ravi", "Fire Bolt", "Orc").startswith("Erro")
    # 15 de dano na fera de 11: volta com 20 - 4 = 16.
    res = td._apply_damage(_ch("Ravi"), 15, "slashing", source_name="Orc")
    assert s["vida_atual"] == 16 and "volta à forma normal" in " ".join(res["notas"])
    assert not criaturas.em_forma_selvagem(_ch("Ravi"))


def test_voltar_nao_gasta_uso_e_o_fim_do_combate_desfaz(druida):
    _usar("Ravi", "Forma Selvagem", modo="urso negro")
    _vez("Ravi")
    assert _usar("Ravi", "Forma Selvagem", modo="voltar")["ok"]
    assert td.usos_restantes(_ch("Ravi"), "Forma Selvagem") == 1
    _vez("Ravi")
    _usar("Ravi", "Forma Selvagem", modo="lobo")
    td.end_combat()
    assert not criaturas.em_forma_selvagem(_ch("Ravi"))
    assert _ch("Ravi")["sheet"]["vida_atual"] == 20


# ---------------------------------------------------------------------------
# Fonte de Magia, Frenesi, Golpe Divino Aprimorado, Toque Purificador
# ---------------------------------------------------------------------------

def test_fonte_de_magia_troca_pontos_e_mana(campanha, povoar):
    povoar(criar_ficha("Sol", grupo=True, classe="feiticeiro", nivel=5, mana=27,
                       habilidades=[_hab("Fonte de Magia")]))
    s = _ch("Sol")["sheet"]
    s["mana_atual"] = 10
    assert "mana:2" in resolucao.modos_de("fonte de magia", _ch("Sol"))
    saida = td.use_ability("Sol", "Fonte de Magia", modo="mana:2", end_turn=False)
    assert s["mana_atual"] == 12 and td.usos_restantes(_ch("Sol"), "Fonte de Magia") == 3, saida
    td.use_ability("Sol", "Fonte de Magia", modo="pontos:3", end_turn=False)
    assert s["mana_atual"] == 9 and td.usos_restantes(_ch("Sol"), "Fonte de Magia") == 5


def test_frenesi_exige_furia_e_cobra_exaustao(campanha, povoar, monkeypatch):
    povoar(criar_ficha("Ulf", grupo=True, classe="bárbaro", nivel=3,
                       habilidades=[_hab("Fúria"), _hab("Frenesi")]),
           criar_ficha("Orc", vida=200))
    iniciar_combate(["Ulf", "Orc"])
    _vez("Ulf")
    assert not _usar("Ulf", "Frenesi", alvo="Orc")["ok"]
    _acertar(monkeypatch)
    assert _usar("Ulf", "Fúria")["ok"]
    _vez("Ulf")
    assert _usar("Ulf", "Frenesi", alvo="Orc")["ok"]
    td.end_combat()
    assert _ch("Ulf")["sheet"]["exaustao"] == 1


def test_golpe_divino_aprimorado_soma_em_todo_acerto(campanha, povoar, monkeypatch):
    povoar(criar_ficha("Brann", grupo=True, classe="paladino", nivel=11,
                       habilidades=[_hab("Golpe Divino Aprimorado")]),
           criar_ficha("Orc", vida=200))
    iniciar_combate(["Brann", "Orc"])
    _vez("Brann")
    _acertar(monkeypatch)
    assert "Golpe Divino Aprimorado: 1d8" in _atacar("Brann", "Orc")["message"]


def test_toque_purificador_encerra_a_magia(luta):
    _ch("Brann")["habilidades"].append(_hab("Toque Purificador"))
    _ch("Lin")["sheet"]["condicoes"].append({"nome": "Paralisado", "magia": "Hold Person", "duracao": None})
    r = _usar("Brann", "Toque Purificador", alvo="Lin")
    assert r["ok"] and "Paralisado" in r["message"]
    assert not _ch("Lin")["sheet"]["condicoes"]
