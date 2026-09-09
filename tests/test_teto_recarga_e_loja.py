"""
test_teto_recarga_e_loja.py

Três buracos achados numa auditoria de "função definida que ninguém chama".
Os três eram do mesmo feitio: a regra existia, estava escrita, e não estava
ligada em nenhum caminho que o jogo realmente percorre.

1. EXAUSTÃO 4 corta o PV máximo pela metade. `_hp_max_efetivo` só era usada
   dentro de `add_exhaustion` — um clamp de uma vez só. Todo caminho de cura
   fechava em `vida_max` cru, então o corte durava até a primeira poção:

       depois de exaustão 4   vida 20/40  | teto 20
       depois da cura         vida 40/40  | teto 20   ← teto virou mentira

   E o descanso longo restaurava a vida ANTES de baixar a exaustão, deixando
   o personagem na metade por uma exaustão que ele já não tinha.

2. RECARGA 5–6 nunca era gasta por `use_ability`. `_recarga_pronta` não era
   chamada por ninguém e `_gastar_recarga` só existia no braço da IA de NPC.
   Quando o MESTRE conduzia o chefe — o caso normal neste app — o dragão
   soprava toda rodada.

3. A LOJA era desvio da conferência de item inventado. `buy_item` chamava
   `add_item` sem descrição, então `_tem_efeito_mecanico` não tinha o que ler
   e a "Lâmina Rúnica de Vhar" era arquivada como "só sabor".
"""
import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha


# ---------------------------------------------------------------------------
# 1. O teto de PV da exaustão
# ---------------------------------------------------------------------------

@pytest.fixture
def aria(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True, vida=40, vida_max=40, nivel=5,
                       constituicao=14, mana=20))
    ch = memory.campaign["characters"]["aria"]
    ch["sheet"]["hit_dice_remaining"] = 5
    return ch


def _exausta(ch, niveis=4):
    td.add_exhaustion(ch["name"], niveis, "noites em claro")
    return ch["sheet"]


def test_exaustao_4_corta_o_maximo_pela_metade(aria):
    s = _exausta(aria)
    assert td._hp_max_efetivo(s) == 20
    assert s["vida_atual"] == 20


def test_cura_nao_passa_do_teto(aria):
    """O caso medido: 20/40, cura de 30, e continuava 40/40."""
    s = _exausta(aria)
    td.modify_hp("Aria", 30, "poção")
    assert s["vida_atual"] == 20


def test_descanso_curto_nao_passa_do_teto(aria):
    s = _exausta(aria)
    s["vida_atual"] = 5
    td.short_rest("Aria")
    assert s["vida_atual"] <= 20


def test_dado_de_vida_nao_passa_do_teto(aria):
    s = _exausta(aria)
    s["vida_atual"] = 5
    td.use_hit_die("Aria", 5)
    assert s["vida_atual"] <= 20


def test_descanso_longo_baixa_a_exaustao_ANTES_de_curar(aria):
    """
    Ordem importa. Quem dorme com exaustão 4 acorda com 3, e em 3 não há
    corte: tem que acordar com 40, não com 20. Restaurar antes de baixar a
    exaustão deixava metade da vida presa a uma exaustão que já passou.
    """
    s = _exausta(aria)
    s["vida_atual"] = 1

    td.long_rest("Aria")

    assert td._exaustao(s) == 3
    assert s["vida_atual"] == 40


def test_descanso_longo_com_exaustao_5_ainda_fica_no_teto(aria):
    """5 → 4 no descanso, e 4 ainda corta. Acorda com 20, não com 40."""
    s = _exausta(aria, 5)
    s["vida_atual"] = 1

    td.long_rest("Aria")

    assert td._exaustao(s) == 4
    assert s["vida_atual"] == 20


def test_o_texto_explica_por_que_a_cura_parou(aria):
    """Sem a nota, a ficha mostra 20/40 e ninguém entende o que houve."""
    s = _exausta(aria)
    s["vida_atual"] = 1
    saida = td.short_rest("Aria")
    assert "teto 20" in saida
    assert "exaustão 4" in saida


def test_sem_exaustao_a_nota_nao_aparece(aria):
    aria["sheet"]["vida_atual"] = 10
    assert td._nota_teto(aria["sheet"]) == ""
    assert "teto" not in td.short_rest("Aria")


# ---------------------------------------------------------------------------
# 2. Recarga 5–6 no caminho do mestre
# ---------------------------------------------------------------------------

SOPRO = {"nome": "Sopro de Fogo", "descricao": "Cone de fogo.",
         "custo_mana": 5, "dado": "6d6"}


@pytest.fixture
def chefe(campanha, povoar):
    povoar(criar_ficha("Vhar", vida=120, mana=50, habilidades=[dict(SOPRO)]),
           criar_ficha("Aria", grupo=True, vida=60))
    td.set_recharge_ability("Vhar", "Sopro de Fogo", 5)
    return memory.campaign["characters"]["vhar"]


def _cfg(chefe):
    return chefe["sheet"]["recargas"]["Sopro de Fogo"]


def test_usar_gasta_a_recarga(chefe):
    assert _cfg(chefe)["pronto"] is True
    td.use_ability("Vhar", "Sopro de Fogo", "Aria")
    assert _cfg(chefe)["pronto"] is False


def test_segundo_uso_e_recusado(chefe):
    td.use_ability("Vhar", "Sopro de Fogo", "Aria")
    saida = td.use_ability("Vhar", "Sopro de Fogo", "Aria")
    assert "GASTO" in saida
    assert "5+" in saida


def test_recusa_nao_cobra_a_mana(chefe):
    """Recusar depois de descontar deixaria o custo pago por nada."""
    td.use_ability("Vhar", "Sopro de Fogo", "Aria")
    mana = chefe["sheet"]["mana_atual"]

    td.use_ability("Vhar", "Sopro de Fogo", "Aria")

    assert chefe["sheet"]["mana_atual"] == mana


def test_o_d6_devolve_o_poder(chefe, monkeypatch):
    td.use_ability("Vhar", "Sopro de Fogo", "Aria")
    assert _cfg(chefe)["pronto"] is False

    monkeypatch.setattr(td.random, "randint", lambda a, b: 6)
    voltaram = td._rolar_recargas(chefe)

    assert _cfg(chefe)["pronto"] is True
    assert voltaram and "Sopro de Fogo" in voltaram[0]
    assert "GASTO" not in td.use_ability("Vhar", "Sopro de Fogo", "Aria")


def test_d6_baixo_nao_devolve(chefe, monkeypatch):
    td.use_ability("Vhar", "Sopro de Fogo", "Aria")
    monkeypatch.setattr(td.random, "randint", lambda a, b: 4)
    td._rolar_recargas(chefe)
    assert _cfg(chefe)["pronto"] is False


def test_poder_sem_recarga_nao_e_afetado(campanha, povoar):
    """A grande maioria das habilidades não tem recarga e não pode travar."""
    povoar(criar_ficha("Aria", grupo=True, vida=60, mana=50,
                       habilidades=[{"nome": "Golpe Firme", "descricao": "",
                                     "custo_mana": 2, "dado": "1d8"}]),
           criar_ficha("Goblin", vida=20))
    for _ in range(3):
        assert "GASTO" not in td.use_ability("Aria", "Golpe Firme", "Goblin")


def test_recarga_em_portugues_com_habilidade_em_ingles(campanha, povoar):
    """
    A ficha guarda a habilidade em inglês e o mestre registra a recarga com o
    nome que ele narra. Procurar só por um dos dois deixava a recarga solta.
    """
    povoar(criar_ficha("Vhar", vida=120, mana=50,
                       habilidades=[{"nome": "Fire Breath", "descricao": "",
                                     "custo_mana": 0, "dado": "6d6"}]),
           criar_ficha("Aria", grupo=True, vida=60))
    td.set_recharge_ability("Vhar", "Fire Breath", 5)

    td.use_ability("Vhar", "Fire Breath", "Aria")

    assert "GASTO" in td.use_ability("Vhar", "Fire Breath", "Aria")


# ---------------------------------------------------------------------------
# 3. A loja leva a descrição até o inventário
# ---------------------------------------------------------------------------

@pytest.fixture
def compradora(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True))
    ch = memory.campaign["characters"]["aria"]
    ch["sheet"]["ouro"] = 1000
    return ch


def _item(ch, nome):
    return next(i for i in ch["inventario"] if i["nome"] == nome)


@pytest.fixture
def verificador():
    import server
    return server


def test_descricao_atravessa_a_loja(compradora):
    td.open_shop("Bazar", "Amuleto do Corvo:75|dá vantagem em Furtividade")
    td.buy_item("Aria", "Bazar", "Amuleto do Corvo", 1)

    it = _item(compradora, "Amuleto do Corvo")
    assert "Furtividade" in it["descricao"]
    assert it["efeito_mecanico"] is True


def test_item_de_regra_comprado_e_cobrado(compradora, verificador):
    """Antes o verificador ficava calado: a loja não passava descrição."""
    memory.campaign["dnd_mode"] = True
    td.open_shop("Bazar", "Lâmina Rúnica de Vhar:200|+3 em ataque e dano")
    td.buy_item("Aria", "Bazar", "Lâmina Rúnica de Vhar", 1)

    v = verificador._verify_agent_response(
        "Aria compra a lâmina.", {"buy_item"},
        combat_was_active=False, dead_before=set())

    assert any("Lâmina Rúnica de Vhar" in x for x in v)


def test_item_magico_sem_descricao_e_cobrado(compradora, verificador):
    """
    Nome mágico e nenhuma descrição não é 'sabor', é lacuna — e era por ela
    que a loja passava, porque buy_item chamava add_item sem descrição.
    """
    memory.campaign["dnd_mode"] = True
    td.open_shop("Bazar", "Lâmina Rúnica de Vhar:200")
    td.buy_item("Aria", "Bazar", "Lâmina Rúnica de Vhar", 1)

    it = _item(compradora, "Lâmina Rúnica de Vhar")
    assert it["custom"] is True
    assert it["efeito_desconhecido"] is True

    v = verificador._verify_agent_response(
        "Aria compra a lâmina.", {"buy_item"},
        combat_was_active=False, dead_before=set())
    assert any("não disse o que ele FAZ" in x for x in v)


def test_sabor_declarado_na_loja_nao_e_cobrado(compradora, verificador):
    """'Não faz nada' é resposta válida e encerra a cobrança."""
    memory.campaign["dnd_mode"] = True
    td.open_shop("Bazar", "Amuleto Sagrado de Vhar:20|herança da família, "
                          "não faz nada")
    td.buy_item("Aria", "Bazar", "Amuleto Sagrado de Vhar", 1)

    assert verificador._check_itens_inventados({"buy_item"}) == []


def test_item_do_srd_comprado_nao_vira_alarme(compradora, verificador):
    td.open_shop("Forja", "Espada Longa; Escudo")
    td.buy_item("Aria", "Forja", "Espada Longa", 1)
    assert verificador._check_itens_inventados({"buy_item"}) == []


def test_a_descricao_sobrevive_a_reabertura_da_loja(campanha):
    td.open_shop("Bazar", "Amuleto do Corvo:75|dá vantagem em Furtividade")
    td.open_shop("Bazar", "Corda:10")

    linha = next(i for i in td._lojas()["bazar"]["estoque"]
                 if i["nome"] == "Amuleto do Corvo")
    assert "Furtividade" in linha["descricao"]


def test_dois_pontos_na_descricao_nao_comem_o_preco(campanha):
    """Texto livre tem ':', e o preço vem antes do '|' justamente por isso."""
    td.open_shop("Bazar", "Talismã:40|efeito: +1 em testes de Sabedoria")
    linha = td._lojas()["bazar"]["estoque"][0]
    assert linha["preco"] == 40
    assert linha["descricao"] == "efeito: +1 em testes de Sabedoria"


def test_buy_item_nao_pode_ser_rechamado_na_correcao(verificador):
    """
    buy_item agora dispara rodada de correção. Se o agente o chamasse de novo,
    o jogador pagaria o mesmo item duas vezes.
    """
    prompt = verificador._build_correction_prompt(
        ["item inventado"], already_called={"buy_item", "add_item"})
    proibidas = prompt.split("NÃO devem ser chamadas novamente:")[-1]
    assert "buy_item" in proibidas
    assert "add_item" not in proibidas
