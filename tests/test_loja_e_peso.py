"""
test_loja_e_peso.py

Três defeitos que só apareceram quando simulei um grupo entrando numa forja.

1. O SRD é EM INGLÊS. `_preco_do_srd` e `_peso_do_srd` consultavam a Open5e
   com o nome em português, então "Espada Longa" devolvia zero resultados e
   `open_shop` recusava o estoque inteiro:

       ⚠️ Nenhum item com preço. O SRD não conhece: Espada Longa,
          Machado de Batalha, Cota de Malha, Escudo, Adaga.

   `WEAPON_PT_TO_EN` já existia no arquivo e nenhuma das duas funções usava.

2. Armadura não pesava. `_peso_do_srd` era código MORTO — definido, nunca
   chamado — e a rota /armor/ do Open5e devolve 'weight' vazio nas 13
   armaduras, então nem chamando resolveria. Uma Cota de Malha caía no
   fallback de 0,5 kg. O sistema de carga foi feito para que armadura pesada
   seja uma escolha, e armadura era justamente o que ele não via.

3. `open_shop` SUBSTITUÍA o estoque. Chamar de novo para acrescentar um item
   apagava a loja: uma forja de 5 itens virava uma forja de 1.
"""
import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha


# ---------------------------------------------------------------------------
# 1. Tradução PT->EN
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pt,en", [
    ("Espada Longa",       "longsword"),
    ("espada curta",       "shortsword"),
    ("Machado de Batalha", "battleaxe"),
    ("ADAGA",              "dagger"),
    ("Lança",              "spear"),          # com acento
    ("Lanca",              "spear"),          # sem acento: o mestre digita assim
    ("Maça",               "mace"),
    ("Cota de Malha",      "scale mail"),     # armadura entra pela ARMOR_TABLE
    ("Escudo",             "shield"),
    ("Armadura de Placas", "plate"),
])
def test_traduz_para_o_srd(pt, en):
    assert td._traduzir_para_srd(pt) == en


def test_quem_ja_escreveu_em_ingles_continua_funcionando():
    assert td._traduzir_para_srd("longsword") == "longsword"
    assert td._traduzir_para_srd("Poção de Cura") == "Poção de Cura"


def test_toda_armadura_da_tabela_aponta_para_um_srd_existente():
    """Um 'srd' com erro de digitação viraria preço None silenciosamente."""
    for nome, dados in td.ARMOR_TABLE.items():
        chave = dados.get("srd")
        assert chave, f"{nome} está sem 'srd'"
        assert chave in td._ARMADURAS_SRD, \
            f"{nome} aponta para '{chave}', que não existe"


# ---------------------------------------------------------------------------
# 2. Preço de armadura sai da tabela local, sem rede
# ---------------------------------------------------------------------------
# A suíte roda offline (conftest). Se estes passarem, o preço não veio da API.

@pytest.mark.parametrize("nome,po", [
    ("Escudo",                   10),
    ("Cota de Malha",            50),
    ("Meia Armadura",           750),
    ("Armadura de Placas",     1500),
    ("Armadura de Couro Batido", 45),
    ("Corselete",                50),
    ("Espada Longa",             15),
    ("Espada Grande",            50),
    ("Machado de Batalha",       10),
    ("Adaga",                     2),
    ("Rapieira",                 25),
    ("Besta Pesada",             50),
    ("Clava",                     1),   # 1 pp no SRD: arredonda para 1 po
])
def test_preco_offline_sem_rede(nome, po):
    assert td._preco_do_srd(nome) == po


def test_item_desconhecido_nao_inventa_preco():
    assert td._preco_do_srd("Lâmina Rúnica de Vhar") is None


def test_a_loja_abre_sem_o_mestre_informar_um_preco(campanha):
    """
    O caso que quebrava: com nome em português e sem preço, open_shop recusava
    tudo. Este é o teste que fica vermelho se a tradução sair.
    """
    saida = td.open_shop(
        "Forja do Torbin",
        "Espada Longa; Machado de Batalha; Cota de Malha; Escudo; Adaga",
        location="Oakhaven")

    assert "Nenhum item com preço" not in saida
    assert _nomes("Forja do Torbin") == [
        "Espada Longa", "Machado de Batalha", "Cota de Malha", "Escudo", "Adaga"]
    assert "Espada Longa — 15 po" in saida
    assert "Cota de Malha — 50 po" in saida


# ---------------------------------------------------------------------------
# 3. Peso de armadura
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nome,kg", [
    ("Cota de Malha",       20.41),   # 45 lb  - antes pesava 0,5
    ("Armadura de Placas",  29.48),   # 65 lb
    ("Escudo",               2.72),   # 6 lb
    ("Meia Armadura",       18.14),   # 40 lb
    ("Armadura de Couro",    4.54),   # 10 lb
    ("Espada Longa",         1.36),   # 3 lb
    ("Besta Pesada",         8.16),   # 18 lb
    ("Espada Grande",        2.72),   # 6 lb
])
def test_equipamento_pesa_o_que_pesa(nome, kg):
    assert td._peso_do_item({"nome": nome}) == pytest.approx(kg, abs=0.05)


def test_o_que_o_mestre_gravou_no_item_manda():
    """Armadura mágica leve continua possível: peso explícito vence a tabela."""
    assert td._peso_do_item({"nome": "Cota de Malha", "peso": 2}) == 2.0


def test_item_comum_ainda_usa_a_aproximacao():
    assert td._peso_do_item({"nome": "Corda de Cânhamo"}) == 4.5
    assert td._peso_do_item({"nome": "Poção de Cura"}) == 0.25


def test_desconhecido_cai_no_ultimo_recurso():
    assert td._peso_do_item({"nome": "Bugiganga do Vhar"}) == 0.5


# ---------------------------------------------------------------------------
# 4. A carga passa a enxergar armadura
# ---------------------------------------------------------------------------

@pytest.fixture
def aria(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True, forca=8))
    ch = memory.campaign["characters"]["aria"]
    ch["sheet"]["ouro"] = 3000
    return ch


def test_armadura_pesada_sobrecarrega(aria):
    """
    FOR 8 -> capacidade 54,4 kg, metade 27,2. Só a armadura de placas (29,5)
    já passa disso. Antes ela pesava 0,5 kg e não mudava nada.
    """
    assert td._estado_de_carga(aria)[0] == "livre"

    td.add_item("Aria", "Armadura de Placas", 1)

    estado, carga, _ = td._estado_de_carga(aria)
    assert carga > 27.2
    assert estado != "livre", "armadura de placas não pesou nada"


# ---------------------------------------------------------------------------
# 5. open_shop acrescenta em vez de substituir
# ---------------------------------------------------------------------------

def _nomes(loja):
    return [i["nome"] for i in td._lojas()[td._norm_txt(loja)]["estoque"]]


def test_segunda_chamada_nao_apaga_a_loja(campanha):
    td.open_shop("Forja do Torbin",
                 "Espada Longa; Escudo; Adaga; Cota de Malha",
                 location="Oakhaven")
    assert len(_nomes("Forja do Torbin")) == 4

    saida = td.open_shop("Forja do Torbin", "Machado de Batalha:10")

    assert _nomes("Forja do Torbin") == [
        "Espada Longa", "Escudo", "Adaga", "Cota de Malha", "Machado de Batalha"]
    assert "atualizada" in saida


def test_reabrir_atualiza_preco_do_item_que_ja_existe(campanha):
    td.open_shop("Bazar", "Corda:10")
    td.open_shop("Bazar", "Corda:25")

    estoque = td._lojas()["bazar"]["estoque"]
    assert len(estoque) == 1
    assert estoque[0]["preco"] == 25


def test_o_que_o_grupo_comprou_continua_comprado(campanha, povoar):
    """
    O caso que mais dói: o mestre acrescenta um item e o estoque que o grupo
    já esvaziou volta cheio.
    """
    povoar(criar_ficha("Aria", grupo=True))
    memory.campaign["characters"]["aria"]["sheet"]["ouro"] = 500
    td.open_shop("Forja", "Escudo:10:2; Adaga:2")
    td.buy_item("Aria", "Forja", "Escudo", 2)          # esvazia o escudo

    td.open_shop("Forja", "Espada Longa:15")

    assert "Escudo" not in _nomes("Forja")             # esgotado continua esgotado
    assert _nomes("Forja") == ["Adaga", "Espada Longa"]


def test_local_da_loja_nao_se_perde_ao_reabrir(campanha):
    td.open_shop("Forja", "Adaga:2", location="Oakhaven")
    td.open_shop("Forja", "Escudo:10")
    assert td._lojas()["forja"]["local"] == "Oakhaven"


# ---------------------------------------------------------------------------
# 6. O motor NÃO confere se o estoque combina com a loja
# ---------------------------------------------------------------------------

def test_forja_pode_vender_pocao(campanha):
    """
    Documenta um limite, não um acerto. `open_shop` não tem categoria: uma
    forja vendendo poção passa. Quem mantém a coerência é o mestre, na
    narrativa — o motor só cuida de preço, estoque e bolsa.

    O SRD até traz 'category' ('Martial Melee Weapons', 'Medium Armor'), então
    dava para conferir; se um dia isso mudar, este teste é o que avisa.
    """
    saida = td.open_shop("Forja do Torbin", "Espada Longa:15; Poção de Cura:50:3")
    assert "Poção de Cura" in saida
    assert "⚠️" not in saida
