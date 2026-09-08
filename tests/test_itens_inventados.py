"""
test_itens_inventados.py

O mestre inventa itens que não existem no D&D. O motor tinha uma defesa para
isso — marcar como "customizado" e avisar — mas ela só enxergava o MASCULINO:

    "mágico", "encantado", "rúnico", "sagrado", "arcano", "divino", "abençoado"

Em português metade do vocabulário de item mágico é feminino (espada, lâmina,
adaga, armadura, coroa, varinha, relíquia), então "Espada Mágica" e "Lâmina
Rúnica" passavam sem conferência nenhuma. Medido antes da correção: 7 de 8
pares só detectavam a forma masculina. "amaldiçoada" era a única exceção,
acrescentada à mão — sinal de que alguém tropeçou nela e corrigiu só aquele
caso.

Além disso a conferência dependia SÓ do nome. Um item de nome comum com
efeito na descrição ("dá vantagem em Sobrevivência") passava batido.
"""
import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha


# ---------------------------------------------------------------------------
# 1. Gênero e plural
# ---------------------------------------------------------------------------

PARES = [
    ("Escudo Mágico",      "Espada Mágica"),
    ("Elmo Encantado",     "Armadura Encantada"),
    ("Cajado Rúnico",      "Lâmina Rúnica"),
    ("Manto Sagrado",      "Coroa Sagrada"),
    ("Anel Arcano",        "Varinha Arcana"),
    ("Amuleto Divino",     "Relíquia Divina"),
    ("Machado Abençoado",  "Adaga Abençoada"),
    ("Punhal Amaldiçoado", "Corrente Amaldiçoada"),
]


@pytest.mark.parametrize("masculino,feminino", PARES)
def test_detecta_os_dois_generos(masculino, feminino):
    assert td._looks_magic(masculino), masculino
    assert td._looks_magic(feminino), feminino


def test_detecta_plural():
    assert td._looks_magic("Botas Encantadas")
    assert td._looks_magic("Flechas Mágicas")


def test_nao_marca_item_comum():
    """Corda e tocha não podem virar alarme falso a cada saque."""
    for comum in ("Corda de Cânhamo", "Tocha", "Ração de Viagem",
                  "Odre de Água", "Saco de Estopa"):
        assert not td._looks_magic(comum), comum
        assert not td._precisa_de_conferencia(comum, "item comum de viagem"), comum


# ---------------------------------------------------------------------------
# 2. Efeito mecânico na descrição
# ---------------------------------------------------------------------------

def test_efeito_na_descricao_dispara_conferencia():
    """Nome comum, efeito de regra: é o caso que passava batido."""
    assert td._precisa_de_conferencia(
        "Bússola de Osso", "dá vantagem em testes de Sobrevivência")
    assert td._precisa_de_conferencia(
        "Lenço da Vovó", "cura 2d4 pontos de vida uma vez por dia")
    assert td._precisa_de_conferencia(
        "Botina Velha", "+2 no deslocamento")


def test_sabor_puro_nao_dispara():
    """Sabor não muda conta nenhuma e não precisa de balanceamento."""
    assert not td._tem_efeito_mecanico(
        "Bússola de Osso", "aponta para a pessoa amada")
    assert not td._tem_efeito_mecanico(
        "Punhal com o brasão da casa Vhar", "pertenceu ao pai dele")


# ---------------------------------------------------------------------------
# 3. add_item: marca, separa sabor de regra
# ---------------------------------------------------------------------------

@pytest.fixture
def aria(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True, nivel=3))
    return memory.campaign["characters"]["aria"]


def _item(char, nome):
    return next(i for i in char["inventario"] if i["nome"] == nome)


def test_inventado_com_regra_e_marcado_e_cobrado(aria):
    saida = td.add_item("Aria", "Lâmina Rúnica de Vhar", 1,
                        "concede +3 em ataque e dano")

    it = _item(aria, "Lâmina Rúnica de Vhar")
    assert it["custom"] is True
    assert it["efeito_mecanico"] is True
    assert "NÃO EXISTE no SRD" in saida
    assert "nível 3" in saida


def test_inventado_so_de_sabor_e_marcado_sem_alarme(aria):
    """Nome mágico, efeito nenhum: fica registrado, mas sem cobrança."""
    saida = td.add_item("Aria", "Amuleto Sagrado de Vhar", 1,
                        "pertenceu ao pai dela; não faz nada")

    it = _item(aria, "Amuleto Sagrado de Vhar")
    assert it.get("custom") is True
    assert not it.get("efeito_mecanico")
    assert "é sabor" in saida
    assert "NÃO EXISTE" not in saida


def test_o_que_o_motor_NAO_consegue_detectar(aria):
    """
    Limite honesto: um item inventado de nome comum e sem efeito é
    indistinguível de equipamento real. "Bússola de Osso" e "Corda de
    Cânhamo" são a mesma coisa para o motor — nome mundano, zero regra.

    Marcar a bússola exigiria uma lista de todo equipamento comum de D&D, e
    errar essa lista daria alarme falso em cada saque. Fingir que detecta
    seria pior que admitir que não detecta.
    """
    td.add_item("Aria", "Bússola de Osso", 1, "aponta para a pessoa amada")
    assert not _item(aria, "Bússola de Osso").get("custom")


def test_item_comum_nao_vira_customizado(aria):
    td.add_item("Aria", "Corda de Cânhamo", 1, "15 metros")
    it = _item(aria, "Corda de Cânhamo")
    assert not it.get("custom")


# ---------------------------------------------------------------------------
# 4. O auditor
# ---------------------------------------------------------------------------

def test_auditor_separa_regra_de_sabor(aria):
    td.add_item("Aria", "Lâmina Rúnica", 1, "+2 de dano")
    td.add_item("Aria", "Coroa Sagrada de Vhar", 1, "herança da família")
    td.add_item("Aria", "Corda", 1, "15 metros")

    saida = td.list_custom_items()

    assert "COM EFEITO MECÂNICO (1)" in saida
    assert "Lâmina Rúnica" in saida
    assert "Só sabor (1)" in saida
    assert "Coroa Sagrada de Vhar" in saida
    assert "Corda" not in saida          # comum: nem entra na lista


def test_auditor_em_campanha_limpa(campanha):
    assert "Nenhum item fora do SRD" in td.list_custom_items()


# ---------------------------------------------------------------------------
# 5. A justificativa encerra a cobrança
# ---------------------------------------------------------------------------

def test_justificar_registra_o_criterio(aria):
    td.add_item("Aria", "Lâmina Rúnica", 1, "+1 de dano contra mortos-vivos")

    saida = td.justify_custom_item(
        "Aria", "Lâmina Rúnica",
        "+1 só contra mortos-vivos, equivalente a arma +1 no nível 3")

    assert "registrado" in saida
    assert _item(aria, "Lâmina Rúnica")["balanco_justificado"]


def test_justificativa_vazia_e_recusada(aria):
    td.add_item("Aria", "Lâmina Rúnica", 1, "+2 de dano")
    assert "Informe a justificativa" in td.justify_custom_item("Aria", "Lâmina Rúnica", "  ")
    assert not _item(aria, "Lâmina Rúnica").get("balanco_justificado")


def test_item_canonico_nao_precisa_de_justificativa(aria):
    aria["inventario"] = [{"nome": "Espada Longa", "qtd": 1, "descricao": ""}]
    assert "canônico" in td.justify_custom_item("Aria", "Espada Longa", "qualquer")


# ---------------------------------------------------------------------------
# 6. O verificador cobra — e para de cobrar quando justificado
# ---------------------------------------------------------------------------

@pytest.fixture
def verificador():
    import server
    return server


def test_verificador_cobra_item_inventado_com_regra(aria, verificador):
    td.add_item("Aria", "Lâmina Rúnica de Vhar", 1, "+3 em ataque e dano")

    v = verificador._check_itens_inventados({"add_item"})

    assert len(v) == 1
    assert "Lâmina Rúnica de Vhar" in v[0]
    assert "SRD" in v[0]


def test_verificador_ignora_item_de_sabor(aria, verificador):
    td.add_item("Aria", "Punhal Sagrado do brasão", 1, "lembrança do pai")
    assert verificador._check_itens_inventados({"add_item"}) == []


def test_verificador_cala_depois_da_justificativa(aria, verificador):
    td.add_item("Aria", "Lâmina Rúnica", 1, "+1 de dano")
    assert verificador._check_itens_inventados({"add_item"}) != []

    td.justify_custom_item("Aria", "Lâmina Rúnica", "+1 condicional, nível 3")
    assert verificador._check_itens_inventados({"add_item"}) == []


def test_verificador_so_olha_no_turno_que_deu_item(aria, verificador):
    """Sem add_item no turno, não fica repetindo a cobrança para sempre."""
    td.add_item("Aria", "Lâmina Rúnica", 1, "+1 de dano")
    assert verificador._check_itens_inventados({"attack_roll"}) == []


def test_a_cobranca_chega_pelo_verificador_de_verdade(aria, verificador):
    """
    Os testes acima chamam _check_itens_inventados DIRETO. Isso não prova que
    ela está LIGADA: dá para apagar a chamada de dentro de
    _verify_agent_response e eles continuam verdes — foi o que aconteceu na
    primeira injeção de regressão que rodei.

    Este entra pela porta que o servidor usa.
    """
    memory.campaign["dnd_mode"] = True
    td.add_item("Aria", "Lâmina Rúnica de Vhar", 1, "+3 em ataque e dano")

    violacoes = verificador._verify_agent_response(
        "Aria encontra a lâmina entre os escombros.",
        {"add_item"}, combat_was_active=False, dead_before=set())

    assert any("SRD" in v and "Lâmina Rúnica de Vhar" in v for v in violacoes), \
        f"a checagem não está ligada em _verify_agent_response: {violacoes}"


def test_add_item_pode_ser_rechamado_na_correcao(verificador):
    """O conserto de um item inventado passa por trocar o item."""
    prompt = verificador._build_correction_prompt(
        ["item inventado"], already_called={"add_item", "attack_roll"})
    proibidas = prompt.split("NÃO devem ser chamadas novamente:")[-1]
    assert "add_item" not in proibidas
    assert "attack_roll" in proibidas
