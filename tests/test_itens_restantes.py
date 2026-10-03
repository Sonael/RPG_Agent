"""
test_itens_restantes.py

O lote 6, o que faltava do sistema de itens: a regra variante de carga do 5e,
a Bolsa de Contenção, a Rede, a munição mágica, os óleos, o Cajado do Poder,
o Cajado do Mago, o Colar de Bolas de Fogo, a Varinha das Maravilhas e as
rações no descanso longo.
"""
import pytest

from rpg import manobras, memory, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


@pytest.fixture
def mesa(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True, forca=10, destreza=14, nivel=5, arma=None),
           criar_ficha("Bram", grupo=True, forca=16),
           criar_ficha("Goblin", vida=200, ca=5, destreza=10))
    return memory.campaign


def _ch(nome):
    return memory.campaign["characters"][nome]


def _item(quem, nome):
    return next((i for i in _ch(quem)["inventario"] if i["nome"] == nome), None)


def _pesa(quem, kg):
    _ch(quem)["inventario"] = [{"nome": "Bigorna", "qtd": 1, "descricao": "", "peso": kg}]


# ---------------------------------------------------------------------------
# Carga: a regra variante (FOR 10: capacidade 68 kg; 22,7 e 45,4)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kg, estado, metros", [
    (20, "livre", 9.0), (30, "sobrecarregado", 6.0), (50, "muito_sobrecarregado", 3.0), (70, "imovel", 0.0)])
def test_os_tres_degraus(mesa, kg, estado, metros):
    _pesa("aria", kg)
    assert td._estado_de_carga(_ch("aria"))[0] == estado
    assert td._deslocamento(_ch("aria"))["metros"] == metros


def test_desvantagem_so_muito_sobrecarregado(mesa, monkeypatch):
    vistas = []
    real = td._roll_d20_with_adv
    monkeypatch.setattr(td, "_roll_d20_with_adv",
                        lambda v, d: (vistas.append(d), real(v, d))[1])
    _pesa("aria", 30)
    td.make_skill_check("Aria", "forca", 10)
    _pesa("aria", 50)
    td.make_skill_check("Aria", "forca", 10)
    assert vistas == [False, True]
    linha = td._rolar_salvaguarda(_ch("aria"), "destreza", 10)[1]
    assert "muito sobrecarregado" in linha


def test_a_mochila_traz_os_dois_limites(mesa):
    c = td.inventory_snapshot("Aria")["personagem"]["carga"]
    assert (c["leve"], c["pesado"]) == (22.7, 45.3)


# ---------------------------------------------------------------------------
# Bolsa de Contenção
# ---------------------------------------------------------------------------

def test_o_que_vai_na_bolsa_nao_pesa(mesa):
    aria = _ch("aria")
    aria["inventario"] = [{"nome": "Bolsa de Contenção", "qtd": 1, "descricao": ""},
                          {"nome": "Bigorna", "qtd": 1, "descricao": "", "peso": 40}]
    antes = td._carga_atual(aria)
    r = td.inventory_action("guardar", char="Aria", item="Bigorna")
    assert r["ok"] is True and td._carga_atual(aria) == pytest.approx(antes - 40)
    item = next(i for i in r["snapshot"]["personagem"]["itens"] if i["nome"] == "Bigorna")
    assert item["bolsa"]["na_bolsa"] is True
    td.inventory_action("tirar", char="Aria", item="Bigorna")
    assert td._carga_atual(aria) == pytest.approx(antes)


def test_a_bolsa_tem_limite_e_nao_guarda_o_equipado(mesa):
    aria = _ch("aria")
    aria["inventario"] = [{"nome": "Mochila Prática", "qtd": 1, "descricao": ""},
                          {"nome": "Bigorna", "qtd": 1, "descricao": "", "peso": 60},
                          {"nome": "Escudo", "qtd": 1, "descricao": ""}]
    assert td.inventory_action("guardar", char="Aria", item="Bigorna")["ok"] is False
    td.equip_item("Aria", "Escudo", "escudo")
    assert td.inventory_action("guardar", char="Aria", item="Escudo")["ok"] is False


def test_sem_a_bolsa_tudo_volta_a_pesar(mesa):
    aria = _ch("aria")
    aria["inventario"] = [{"nome": "Bolsa de Contenção", "qtd": 1, "descricao": ""},
                          {"nome": "Bigorna", "qtd": 1, "descricao": "", "peso": 40}]
    td.inventory_action("guardar", char="Aria", item="Bigorna")
    td.give_item("Aria", "Bram", "Bolsa de Contenção")
    assert td._carga_atual(aria) == 40


# ---------------------------------------------------------------------------
# Rede
# ---------------------------------------------------------------------------

def test_a_rede_prende_sem_ferir(mesa, monkeypatch):
    _ch("aria")["inventario"].append({"nome": "Rede", "qtd": 1, "descricao": ""})
    monkeypatch.setattr(td.random, "randint", lambda a, b: 15 if (a, b) == (1, 20) else b)
    hp = _ch("goblin")["sheet"]["vida_atual"]
    saida = td.attack_roll("Aria", "Goblin", "Rede", 6, end_turn=False, _skip_turn_check=True)
    assert "preso na rede" in saida and _ch("goblin")["sheet"]["vida_atual"] == hp
    assert any(c.get("da_rede") for c in _ch("goblin")["sheet"]["condicoes"])
    iniciar_combate(["Aria", "Goblin"])
    eu = next(c for c in td.combat_snapshot()["combatants"] if c["name"] == "Goblin")
    assert "Preso na rede" in eu["condicoes"]


def test_escapar_da_rede(mesa, monkeypatch):
    _ch("goblin")["sheet"]["condicoes"] = [{"nome": "Contido", "da_rede": True, "escapa_cd": 10}]
    monkeypatch.setattr(td.random, "randint", lambda a, b: 2)
    assert "continua preso" in manobras.escapar("Goblin")
    monkeypatch.setattr(td.random, "randint", lambda a, b: 18)
    assert "livre" in manobras.escapar("Goblin")
    assert not _ch("goblin")["sheet"]["condicoes"]


# ---------------------------------------------------------------------------
# Munição mágica
# ---------------------------------------------------------------------------

def test_flecha_mais_um_e_uma_opcao_da_arma(mesa, monkeypatch):
    aria = _ch("aria")
    # A +1 vem antes na mochila: sem escolha, ainda assim sai a comum.
    aria["inventario"] += [{"nome": "Arco Longo", "qtd": 1, "descricao": ""},
                           {"nome": "Flecha +1", "qtd": 2, "descricao": ""},
                           {"nome": "Flecha", "qtd": 10, "descricao": ""}]
    opcoes = [w["nome"] for w in td._combatant_weapons(aria)]
    assert "Arco Longo (Flecha +1)" in opcoes
    monkeypatch.setattr(td.random, "randint", lambda a, b: 10)
    comum = td.attack_roll("Aria", "Goblin", "Arco Longo", 8, end_turn=False, _skip_turn_check=True)
    assert _item("aria", "Flecha +1")["qtd"] == 2 and "+1(mágica)" not in comum
    magica = td.attack_roll("Aria", "Goblin", "Arco Longo (Flecha +1)", 8, end_turn=False,
                            _skip_turn_check=True)
    assert "+1(mágica)" in magica and _item("aria", "Flecha +1")["qtd"] == 1
    assert _item("aria", "Flecha")["qtd"] == 9


# ---------------------------------------------------------------------------
# Óleos
# ---------------------------------------------------------------------------

def test_oleo_da_afiacao(mesa):
    _ch("aria")["inventario"].append({"nome": "Óleo da Afiação", "qtd": 1, "descricao": "", "identificado": True})
    uso = next(i for i in td.inventory_snapshot("Aria")["personagem"]["itens"]
               if i["nome"] == "Óleo da Afiação")["uso"]
    assert uso["rotulo"] == "Aplicar"
    msg = td.inventory_action("usar", char="Aria", item="Óleo da Afiação")["message"]
    assert "aplicou" in msg
    assert any(e.get("atk_bonus") == 3 for e in td._efeitos(_ch("aria")["sheet"]))


def test_oleo_escorregadio_solta_e_protege(mesa):
    aria = _ch("aria")
    aria["sheet"]["condicoes"] = [{"nome": "Contido", "duracao": None}]
    aria["inventario"].append({"nome": "Óleo Escorregadio", "qtd": 1, "descricao": "", "identificado": True})
    td.inventory_action("usar", char="Aria", item="Óleo Escorregadio")
    assert not aria["sheet"]["condicoes"]
    td.advance_time(2)                          # dura oito horas, não uma
    assert td._imune_a_condicao(aria, "agarrado")
    td.advance_time(7)
    assert not td._imune_a_condicao(aria, "agarrado")


# ---------------------------------------------------------------------------
# Cajados, colar, maravilha
# ---------------------------------------------------------------------------

@pytest.fixture
def maga(mesa):
    aria = _ch("aria")
    aria["sheet"].update({"classe": "mago", "inteligencia": 16})
    return aria


def test_cajado_do_poder_lanca_bola_de_fogo_no_quinto(maga):
    maga["inventario"].append({"nome": "Cajado do Poder", "qtd": 1, "descricao": ""})
    td.attune_item("Aria", "Cajado do Poder")
    saida = td._conjurar_do_item("Aria", "Cajado do Poder", "Bola de Fogo", "Goblin")
    assert not saida.startswith(("Erro:", "Aviso:")), saida
    assert _item("aria", "Cajado do Poder")["cargas"] == 15
    assert "10d6" in saida                   # 8d6 no 3º, +1d6 por círculo: 10d6 no 5º


def test_cajado_do_poder_protege_vestido(maga):
    td._recalculate_ca(maga)
    ca = maga["sheet"]["ca"]
    maga["inventario"].append({"nome": "Cajado do Poder", "qtd": 1, "descricao": ""})
    td.equip_item("Aria", "Cajado do Poder", "arma_principal")
    td.attune_item("Aria", "Cajado do Poder")
    assert maga["sheet"]["ca"] == ca + 2


def test_colar_de_bolas_de_fogo(maga, monkeypatch):
    maga["inventario"].append({"nome": "Colar de Bolas de Fogo", "qtd": 1, "descricao": ""})
    monkeypatch.setattr(td.random, "randint", lambda a, b: b)          # 1d6+3 = 9 contas
    item = _item("aria", "Colar de Bolas de Fogo")
    assert td._cargas_do_item(item, td._uso_do_item(item["nome"])) == 9
    item["cargas"] = 1
    monkeypatch.setattr(td.random, "randint", lambda a, b: 1)          # o 1 que desfaz varinha
    td._conjurar_do_item("Aria", "Colar de Bolas de Fogo", "Bola de Fogo", "Goblin")
    assert _item("aria", "Colar de Bolas de Fogo")["cargas"] == 0       # o colar fica


@pytest.mark.parametrize("d100, espera", [(75, "bola de fogo"), (12, "atordoa"), (31, "chover")])
def test_varinha_das_maravilhas(maga, monkeypatch, d100, espera):
    maga["inventario"].append({"nome": "Varinha das Maravilhas", "qtd": 1, "descricao": ""})
    td.attune_item("Aria", "Varinha das Maravilhas")
    monkeypatch.setattr(td.random, "randint", lambda a, b: d100 if (a, b) == (1, 100) else 10)
    saida = td._conjurar_do_item("Aria", "Varinha das Maravilhas", "Maravilha", "Goblin")
    assert f"d100 = {d100}" in saida and espera in saida.lower()
    assert _item("aria", "Varinha das Maravilhas")["cargas"] == 6
    if d100 == 12:
        assert any(c.get("nome") == "Atordoado" for c in maga["sheet"]["condicoes"])
    if d100 == 75:
        assert _ch("goblin")["sheet"]["vida_atual"] < 200       # a Bola de Fogo pelo motor


def test_a_maravilha_aparece_na_tela(maga):
    maga["inventario"].append({"nome": "Varinha das Maravilhas", "qtd": 1, "descricao": ""})
    td.attune_item("Aria", "Varinha das Maravilhas")
    iniciar_combate(["Aria", "Goblin"])
    eu = next(c for c in td.combat_snapshot()["combatants"] if c["name"] == "Aria")
    assert any(h["nome"] == "Maravilha [Varinha das Maravilhas]" for h in eu["habilidades"])


# ---------------------------------------------------------------------------
# Rações
# ---------------------------------------------------------------------------

def test_a_racao_se_come_no_descanso(mesa):
    aria = _ch("aria")
    aria["inventario"] = [{"nome": "Ração (1 dia)", "qtd": 2, "descricao": ""}]
    assert "Come uma ração (restam 1)" in td.long_rest("Aria")
    assert aria["sheet"]["come_racoes"] is True


def test_sem_racao_conta_os_dias_e_cansa(mesa):
    aria = _ch("aria")
    aria["sheet"].update({"come_racoes": True, "dias_sem_comer": 3, "exaustao": 0})
    aria["inventario"] = []
    saida = td.long_rest("Aria")                                     # CON 14: aguenta 5 dias
    assert "4º dia sem comer" in saida and aria["sheet"].get("exaustao", 0) == 0
    aria["sheet"]["dias_sem_comer"] = 5
    td.advance_time(24)                        # um descanso longo por dia
    saida = td.long_rest("Aria")
    assert "um nível de exaustão" in saida and aria["sheet"]["exaustao"] == 1


def test_mesa_que_nao_conta_comida_nao_e_cobrada(mesa):
    aria = _ch("aria")
    aria["inventario"] = []
    assert "sem comer" not in td.long_rest("Aria")
    assert not aria["sheet"].get("dias_sem_comer")
