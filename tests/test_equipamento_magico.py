"""
test_equipamento_magico.py

O equipamento do lote 2: slots para item mágico, sintonização, o efeito dos
itens do SRD, proficiência com armadura e arma, e as regras de armadura e de
mãos. Antes, o Anel de Proteção, o Manto Élfico e as Manoplas de Força de
Ogro eram nomes na mochila; o mago vestia placas e brandia um machado grande
com a proficiência inteira; e um espadão dividia as mãos com um escudo.
"""
import pytest

from rpg import memory, tools_dnd as td, tracos

from conftest import criar_ficha


@pytest.fixture
def heroi(campanha, povoar):
    povoar(criar_ficha("Brynn", grupo=True, forca=8, destreza=14, constituicao=10, arma=None),
           criar_ficha("Alvo", vida=200, ca=5))
    ch = memory.campaign["characters"]["brynn"]
    td._recalculate_ca(ch)
    return ch


def _dar(ch, *nomes):
    for nome in nomes:
        ch["inventario"].append({"nome": nome, "qtd": 1, "descricao": "", "identificado": True})


def _vestir(ch, nome, slot=""):
    _dar(ch, nome)
    saida = td.equip_item(ch["name"], nome, slot)
    assert "equipou" in saida, saida
    return saida


# ---------------------------------------------------------------------------
# Slots
# ---------------------------------------------------------------------------

def test_anel_vai_num_dedo_livre(heroi):
    _vestir(heroi, "Anel de Proteção")
    _vestir(heroi, "Anel de Natação")
    eq = heroi["sheet"]["equipamentos"]
    assert (eq["anel_1"], eq["anel_2"]) == ("Anel de Proteção", "Anel de Natação")


@pytest.mark.parametrize("item, slot", [
    ("Manto Élfico", "capa"), ("Botas Élficas", "botas"), ("Braçadeiras de Defesa", "luvas"),
    ("Elmo da Telepatia", "cabeca"), ("Cinto dos Anões", "cinto"), ("Periapto da Saúde", "amuleto"),
    ("Capa de Viagem do Vhar", "capa"),          # fora do SRD: pela primeira palavra
])
def test_cada_item_no_seu_slot(heroi, item, slot):
    assert td._slots_para_item(item)[0] == slot


def test_mochila_mostra_so_os_slots_novos_ocupados(heroi):
    _vestir(heroi, "Anel de Proteção")
    equipados = td.inventory_snapshot("Brynn")["personagem"]["equipados"]
    visiveis = [e["slot"] for e in equipados if e["basico"] or e["item"]]
    assert "anel_1" in visiveis and "botas" not in visiveis and "armadura" in visiveis


# ---------------------------------------------------------------------------
# Mãos
# ---------------------------------------------------------------------------

def test_arma_de_duas_maos_nao_divide_com_escudo(heroi):
    _vestir(heroi, "Escudo")
    _dar(heroi, "Espada Grande")
    assert td.equip_item("Brynn", "Espada Grande", "arma_principal").startswith("Erro:")


def test_escudo_nao_entra_com_espadao_na_mao(heroi):
    _vestir(heroi, "Espada Grande", "arma_principal")
    _dar(heroi, "Escudo")
    assert td.equip_item("Brynn", "Escudo").startswith("Erro:")


def test_duas_armas_e_escudo_nao_cabem(heroi):
    _vestir(heroi, "Adaga", "arma_principal")
    _vestir(heroi, "Machadinha", "arma_secundaria")
    _dar(heroi, "Escudo")
    assert td.equip_item("Brynn", "Escudo").startswith("Erro:")


def test_espada_longa_e_escudo_cabem(heroi):
    _vestir(heroi, "Espada Longa", "arma_principal")
    _vestir(heroi, "Escudo")


# ---------------------------------------------------------------------------
# Sintonização
# ---------------------------------------------------------------------------

def test_anel_de_protecao_so_vale_sintonizado(heroi):
    ca = heroi["sheet"]["ca"]
    _vestir(heroi, "Anel de Proteção")
    assert heroi["sheet"]["ca"] == ca
    assert "1/3" in td.attune_item("Brynn", "Anel de Proteção")
    assert heroi["sheet"]["ca"] == ca + 1
    td.end_attunement("Brynn", "Anel de Proteção")
    assert heroi["sheet"]["ca"] == ca


def test_anel_de_protecao_soma_na_salvaguarda(heroi, monkeypatch):
    _vestir(heroi, "Anel de Proteção")
    td.attune_item("Brynn", "Anel de Proteção")
    monkeypatch.setattr(td.random, "randint", lambda a, b: 10)
    _passou, linha = td._rolar_salvaguarda(heroi, "sabedoria", 30)
    assert "+1" in linha and "Anel de Proteção" in linha


def test_dois_aneis_iguais_nao_somam(heroi):
    ca = heroi["sheet"]["ca"]
    heroi["inventario"].append({"nome": "Anel de Proteção", "qtd": 2, "descricao": ""})
    td.equip_item("Brynn", "Anel de Proteção", "anel_1")
    td.equip_item("Brynn", "Anel de Proteção", "anel_2")
    td.attune_item("Brynn", "Anel de Proteção")
    assert heroi["sheet"]["ca"] == ca + 1


def test_tres_sintonias_no_maximo(heroi):
    _dar(heroi, "Anel de Proteção", "Manto de Proteção", "Manto Élfico", "Botas Élficas")
    for nome in ("Anel de Proteção", "Manto de Proteção", "Manto Élfico"):
        assert not td.attune_item("Brynn", nome).startswith(("Erro:", "Aviso:"))
    assert td.attune_item("Brynn", "Botas Élficas").startswith("Nota:")   # não pede sintonia
    _dar(heroi, "Pedra da Sorte")
    assert td.attune_item("Brynn", "Pedra da Sorte").startswith("Erro:")


def test_item_que_pede_classe(heroi):
    _dar(heroi, "Cajado do Mago")
    assert "mago" in td.attune_item("Brynn", "Cajado do Mago")
    heroi["sheet"]["classe"] = "mago"
    assert not td.attune_item("Brynn", "Cajado do Mago").startswith("Erro:")


def test_sintonizar_em_combate_e_recusado(heroi):
    _dar(heroi, "Anel de Proteção")
    memory.campaign["combat_state"] = {"is_active": True, "initiative_order": ["Brynn"],
                                       "current_turn_index": 0, "round": 1}
    assert td.attune_item("Brynn", "Anel de Proteção").startswith("Aviso:")


def test_largar_o_item_desfaz_a_sintonia(heroi):
    _vestir(heroi, "Anel de Proteção")
    td.attune_item("Brynn", "Anel de Proteção")
    td.remove_item("Brynn", "Anel de Proteção")
    assert not heroi["sheet"].get("sintonizados")


def test_sintonizar_pela_mochila_leva_uma_hora_e_identifica(heroi):
    heroi["inventario"].append({"nome": "Anel de Proteção", "qtd": 1, "descricao": "",
                                "srd": {"tipo": "anel"}, "identificado": False})
    antes = td._agora_em_horas()
    r = td.inventory_action("sintonizar", char="Brynn", item="Anel de Proteção")
    assert r["ok"] is True
    assert td._agora_em_horas() == antes + 1
    item = next(i for i in r["snapshot"]["personagem"]["itens"] if i["nome"] == "Anel de Proteção")
    assert item["sintonia"]["sintonizado"] is True and item["a_identificar"] is False
    assert item["sintonia"]["efeito"] == "+1 na CA e nas salvaguardas."
    assert r["snapshot"]["personagem"]["sintonizados"] == {"usados": 1, "limite": 3}


def test_bonus_da_arma_magica_pede_sintonia(heroi):
    _dar(heroi, "Defensora")
    assert td._bonus_magico_da_arma(heroi, "Defensora") == 0
    td.attune_item("Brynn", "Defensora")
    assert td._bonus_magico_da_arma(heroi, "Defensora") == 3


def test_armadura_demoniaca_so_da_o_bonus_sintonizada(heroi):
    _vestir(heroi, "Armadura Demoníaca")
    assert heroi["sheet"]["ca"] == 18
    td.attune_item("Brynn", "Armadura Demoníaca")
    assert heroi["sheet"]["ca"] == 19


# ---------------------------------------------------------------------------
# Efeitos
# ---------------------------------------------------------------------------

def _sintonizado(ch, nome, slot=""):
    _vestir(ch, nome, slot)
    td.attune_item(ch["name"], nome)


def test_manoplas_de_forca_de_ogro(heroi):
    _sintonizado(heroi, "Manoplas de Força de Ogro")
    assert heroi["sheet"]["forca"] == 19
    td.unequip_item("Brynn", "luvas")
    assert heroi["sheet"]["forca"] == 8


def test_atributo_mudado_por_fora_vira_a_base(heroi):
    _sintonizado(heroi, "Manoplas de Força de Ogro")
    heroi["sheet"]["forca"] = 10          # o aumento de nível escreveu por cima
    td._recalculate_ca(heroi)
    assert heroi["sheet"]["forca"] == 19
    td.unequip_item("Brynn", "luvas")
    assert heroi["sheet"]["forca"] == 10


def test_amuleto_da_saude_mexe_na_vida_maxima(heroi):
    heroi["sheet"].update({"vida_max": 30, "vida_atual": 30, "nivel": 3})
    _sintonizado(heroi, "Amuleto da Saúde")
    assert heroi["sheet"]["constituicao"] == 19
    assert heroi["sheet"]["vida_max"] == 30 + 4 * 3          # mod 0 → +4, nível 3
    td.unequip_item("Brynn", "amuleto")
    assert heroi["sheet"]["vida_max"] == 30


def test_bracadeiras_de_defesa_so_sem_armadura(heroi):
    ca = heroi["sheet"]["ca"]
    _sintonizado(heroi, "Braçadeiras de Defesa")
    assert heroi["sheet"]["ca"] == ca + 2
    _vestir(heroi, "Armadura de Couro")
    assert heroi["sheet"]["ca"] == 11 + 2                    # couro + DES, sem as braçadeiras


def test_periapto_contra_veneno(heroi):
    _vestir(heroi, "Periapto contra Veneno")
    res = td._apply_damage(heroi, 10, "poison", source_name="armadilha")
    assert res["dano"] == 0


def test_anel_de_resistencia_ao_fogo(heroi):
    _sintonizado(heroi, "Anel de Resistência ao Fogo")
    assert td._apply_damage(heroi, 10, "fire", source_name="dragão")["dano"] == 5


def test_manto_elfico_da_vantagem_em_furtividade(heroi):
    _sintonizado(heroi, "Manto Élfico")
    assert "Manto Élfico: vantagem" in td.make_skill_check("Brynn", "destreza", 10, skill="furtividade")


def test_oculos_da_noite(heroi):
    assert td._visao_no_escuro(heroi) == 0
    _vestir(heroi, "Óculos da Noite")
    assert td._visao_no_escuro(heroi) == 18


def test_botas_de_passos_largos_ignoram_a_carga(heroi):
    heroi["inventario"].append({"nome": "Bigorna", "qtd": 1, "descricao": "", "peso": 30})
    assert td._deslocamento(heroi)["metros"] == 6.0
    _sintonizado(heroi, "Botas de Passos Largos e Saltos")
    assert td._deslocamento(heroi)["metros"] == 9.0


def test_manto_de_resistencia_a_magia(heroi):
    _sintonizado(heroi, "Manto de Resistência à Magia")
    tracos._magias_em_curso += 1
    try:
        assert tracos.contra_magia(heroi)
    finally:
        tracos._magias_em_curso -= 1


def _ataque(monkeypatch, atacante, alvo, arma, d20=15):
    monkeypatch.setattr(td.random, "randint", lambda a, b: d20 if (a, b) == (1, 20) else b)
    return td.attack_roll(atacante, alvo, arma, 8, end_turn=False, _skip_turn_check=True)


def test_lingua_de_fogo_queima_sintonizada(heroi, monkeypatch):
    _vestir(heroi, "Língua de Fogo", "arma_principal")
    assert "fire" not in _ataque(monkeypatch, "Brynn", "Alvo", "Língua de Fogo")
    td.attune_item("Brynn", "Língua de Fogo")
    assert "2d6 de Língua de Fogo" in _ataque(monkeypatch, "Brynn", "Alvo", "Língua de Fogo")


def test_matadora_de_dragoes_so_contra_dragao(heroi, monkeypatch, povoar):
    povoar(criar_ficha("Wyrm", vida=200, ca=5, tipo="dragon"))
    _vestir(heroi, "Matadora de Dragões", "arma_principal")
    assert "3d6" not in _ataque(monkeypatch, "Brynn", "Alvo", "Matadora de Dragões")
    assert "3d6" in _ataque(monkeypatch, "Brynn", "Wyrm", "Matadora de Dragões")


def test_bracadeiras_de_arquearia(heroi, monkeypatch):
    _vestir(heroi, "Arco Longo", "arma_principal")
    alvo = memory.campaign["characters"]["alvo"]["sheet"]
    _ataque(monkeypatch, "Brynn", "Alvo", "Arco Longo")
    sem = 200 - alvo["vida_atual"]
    alvo["vida_atual"] = 200
    _sintonizado(heroi, "Braçadeiras de Arquearia")
    assert "+2(braçadeiras)" in _ataque(monkeypatch, "Brynn", "Alvo", "Arco Longo")
    assert 200 - alvo["vida_atual"] == sem + 2


def test_adamante_desfaz_o_critico(heroi, monkeypatch, povoar):
    povoar(criar_ficha("Bandido", vida=50, ca=12))
    _vestir(heroi, "Peitoral de Adamante")
    saida = _ataque(monkeypatch, "Bandido", "Brynn", "espada longa", d20=20)
    assert "desfaz o crítico" in saida and "CRÍTICO" not in saida and "ACERTO" in saida


# ---------------------------------------------------------------------------
# Proficiência e regras de armadura
# ---------------------------------------------------------------------------

@pytest.fixture
def mago(heroi):
    heroi["sheet"]["classe"] = "mago"
    return heroi


def test_mago_com_espada_longa_nao_soma_proficiencia(mago, monkeypatch):
    assert "sem o bônus de proficiência" in _ataque(monkeypatch, "Brynn", "Alvo", "Espada Longa")
    assert "sem o bônus" not in _ataque(monkeypatch, "Brynn", "Alvo", "Adaga")


def test_elfo_e_proficiente_com_espada_longa(mago, monkeypatch):
    mago["sheet"]["raca"] = "elfo"
    assert "sem o bônus" not in _ataque(monkeypatch, "Brynn", "Alvo", "Espada Longa")


def test_armadura_sem_proficiencia(mago, monkeypatch):
    _vestir(mago, "Cota de Malha")
    assert "sem proficiência → desvantagem" in _ataque(monkeypatch, "Brynn", "Alvo", "Adaga")
    assert "desvantagem: Cota de Malha sem proficiência" in td.make_skill_check(
        "Brynn", "destreza", 10, skill="acrobacia")
    mago["habilidades"] = [{"nome": "Mísseis Mágicos", "descricao": "", "custo_mana": 4, "dado": "1d4"}]
    saida = td.use_ability("Brynn", "Mísseis Mágicos", "Alvo", _skip_turn_check=True)
    assert saida.startswith("Erro:") and "não consegue conjurar" in saida


def test_clerigo_com_treinamento_veste_armadura_pesada(heroi):
    heroi["sheet"]["classe"] = "clérigo"
    assert not td._proficiente_com_armadura(heroi, "Cota de Malha")
    heroi["habilidades"] = [{"nome": "Treinamento em Armadura Pesada", "descricao": ""}]
    assert td._proficiente_com_armadura(heroi, "Cota de Malha")


def test_cota_elfica_e_proficiente_para_qualquer_um(mago):
    assert td._proficiente_com_armadura(mago, "Cota Élfica")


def test_furtividade_com_armadura_que_pesa(heroi):
    _vestir(heroi, "Cota de Malha")
    assert "desvantagem em Furtividade" in td.make_skill_check("Brynn", "destreza", 10, skill="furtividade")


def test_mithral_nao_atrapalha_a_furtividade_nem_pede_forca(heroi):
    heroi["sheet"]["forca"] = 12           # aguenta o peso (25 kg) sem sobrecarga
    _vestir(heroi, "Cota de Malha de Mithral")
    assert "Furtividade" not in td.make_skill_check("Brynn", "destreza", 10, skill="furtividade").split("\n")[1]
    assert td._deslocamento(heroi)["metros"] == 9.0


def test_forca_minima_da_armadura_pesada(heroi):
    heroi["sheet"]["forca"] = 14           # aguenta o peso (29,5 kg), não a armadura (FOR 15)
    _vestir(heroi, "Armadura de Placas")
    desl = td._deslocamento(heroi)
    assert desl["metros"] == 6.0 and any("FOR 15" in n for n in desl["notas"])
    heroi["sheet"]["raca"] = "anão"
    assert td._deslocamento(heroi)["metros"] == 7.5            # anão: 7,5 m sem o -3


def test_monstro_nao_passa_pela_proficiencia(campanha, povoar):
    povoar(criar_ficha("Ogro", vida=50, classe="mago"))
    ogro = memory.campaign["characters"]["ogro"]
    assert td._proficiente_com_arma(ogro, "Espada Grande")
