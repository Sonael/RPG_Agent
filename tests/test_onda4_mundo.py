"""
test_onda4_mundo.py
Onda 4 — os outros dois pilares: mundo e economia.

  1. Relógio + descanso diário + exaustão
  2. Atitude de NPC (memória social)
  3. Carga e loja
  4. Missões como objetos

Como nas ondas anteriores, tudo é aditivo: uma campanha que nunca chamar
advance_time(), open_shop() ou add_quest() continua se comportando como antes.
"""
import random

import pytest

from rpg import memory, tools, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


# ---------------------------------------------------------------------------
# 1. Relógio
# ---------------------------------------------------------------------------

def test_relogio_comeca_no_dia_1_de_manha(campanha):
    campanha.pop("relogio", None)
    assert td._relogio() == {"dia": 1, "hora": 8}
    assert "Dia 1, 08h (manhã)" in td.get_world_time()


def test_avancar_horas_vira_o_dia(campanha):
    campanha["relogio"] = {"dia": 1, "hora": 20}

    saida = td.advance_time(10, "viagem noturna")

    assert campanha["relogio"] == {"dia": 2, "hora": 6}
    assert "viagem noturna" in saida
    assert "O dia virou" in saida


def test_periodos_do_dia(campanha):
    for hora, esperado in ((2, "madrugada"), (9, "manhã"),
                           (15, "tarde"), (21, "noite")):
        assert td._periodo(hora) == esperado


def test_avanco_invalido_e_recusado(campanha):
    campanha["relogio"] = {"dia": 1, "hora": 8}
    assert "pelo menos 1 hora" in td.advance_time(0)
    assert "720 horas" in td.advance_time(1000)
    assert campanha["relogio"] == {"dia": 1, "hora": 8}   # nada mudou


# ---------------------------------------------------------------------------
# 2. Descanso longo: um por 24 horas, e custa 8
# ---------------------------------------------------------------------------

def test_descanso_longo_consome_oito_horas(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True, vida=10, vida_max=30))
    campanha["relogio"] = {"dia": 1, "hora": 22}

    td.long_rest("Aria")

    assert campanha["relogio"] == {"dia": 2, "hora": 6}
    assert campanha["characters"]["aria"]["sheet"]["vida_atual"] == 30


def test_segundo_descanso_no_mesmo_dia_e_recusado(campanha, povoar):
    """
    Sem isto long_rest() era um botão de vida cheia — o 'dia de aventura' do
    5e, que faz mana e poderes diários serem recurso, não existia.
    """
    povoar(criar_ficha("Aria", grupo=True, vida=10, vida_max=30))
    campanha["relogio"] = {"dia": 1, "hora": 8}
    td.long_rest("Aria")

    campanha["characters"]["aria"]["sheet"]["vida_atual"] = 5
    saida = td.long_rest("Aria")

    assert "já descansou nas últimas 24 horas" in saida
    assert "Faltam" in saida
    assert campanha["characters"]["aria"]["sheet"]["vida_atual"] == 5   # não curou


def test_descanso_volta_a_valer_depois_de_24h(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True, vida=10, vida_max=30))
    campanha["relogio"] = {"dia": 1, "hora": 8}
    td.long_rest("Aria")

    td.advance_time(24, "um dia inteiro de estrada")
    campanha["characters"]["aria"]["sheet"]["vida_atual"] = 5
    saida = td.long_rest("Aria")

    assert "já descansou" not in saida
    assert campanha["characters"]["aria"]["sheet"]["vida_atual"] == 30


def test_o_grupo_dorme_na_mesma_noite(campanha, povoar):
    """Dois personagens descansando não podem consumir 16 horas."""
    povoar(criar_ficha("Aria", grupo=True, vida=10, vida_max=30),
           criar_ficha("Bran", grupo=True, vida=10, vida_max=30))
    campanha["relogio"] = {"dia": 1, "hora": 20}

    td.long_rest("Aria")
    td.long_rest("Bran")

    assert campanha["relogio"] == {"dia": 2, "hora": 4}


# ---------------------------------------------------------------------------
# 3. Exaustão
# ---------------------------------------------------------------------------

def test_exaustao_sobe_e_lista_os_efeitos(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True))
    saida = td.add_exhaustion("Aria", 2, "marcha forçada")

    assert "0 → **2**" in saida
    assert "marcha forçada" in saida
    assert "Desvantagem em testes de perícia" in saida
    assert campanha["characters"]["aria"]["sheet"]["exaustao"] == 2


def test_exaustao_1_da_desvantagem_em_pericia(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True, forca=16))
    random.seed(4)
    limpo = td.make_skill_check("Aria", "forca", 10)
    assert "desvantagem" not in limpo.lower()

    td.add_exhaustion("Aria", 1)
    random.seed(4)
    exausto = td.make_skill_check("Aria", "forca", 10)
    assert "desvantagem" in exausto.lower()


def test_exaustao_3_da_desvantagem_em_ataque(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True, forca=16),
           criar_ficha("Goblin", grupo=False, vida=30, ca=12))
    iniciar_combate(["Aria", "Goblin"])

    td.add_exhaustion("Aria", 2)
    random.seed(8)
    sem = td.attack_roll("Aria", "Goblin", "espada longa", 8,
                         end_turn=False, _skip_turn_check=True)
    assert "desvantagem" not in sem.lower()

    td.add_exhaustion("Aria", 1)          # agora 3
    random.seed(8)
    com = td.attack_roll("Aria", "Goblin", "espada longa", 8,
                         end_turn=False, _skip_turn_check=True)
    assert "desvantagem" in com.lower()


def test_exaustao_4_corta_o_pv_maximo_sem_apagar_a_ficha(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True, vida=40, vida_max=40))
    s = campanha["characters"]["aria"]["sheet"]

    td.add_exhaustion("Aria", 4)

    assert td._hp_max_efetivo(s) == 20
    assert s["vida_max"] == 40        # o valor REAL da ficha fica intacto
    assert s["vida_atual"] == 20      # a vida atual desce até o teto

    td.remove_exhaustion("Aria", 1)   # volta a 3
    assert td._hp_max_efetivo(s) == 40


def test_exaustao_6_mata(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True, vida=30))
    saida = td.add_exhaustion("Aria", 6, "sem água há dias")

    assert "MORRE" in saida
    assert campanha["characters"]["aria"]["status"] == "morto"
    assert campanha["characters"]["aria"]["sheet"]["vida_atual"] == 0


def test_exaustao_nao_passa_de_6(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True))
    td.add_exhaustion("Aria", 99)
    assert campanha["characters"]["aria"]["sheet"]["exaustao"] == 6


def test_descanso_longo_remove_um_nivel(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True, vida=10, vida_max=30))
    td.add_exhaustion("Aria", 3)
    campanha["relogio"] = {"dia": 1, "hora": 20}

    td.long_rest("Aria")

    assert campanha["characters"]["aria"]["sheet"]["exaustao"] == 2


def test_remover_exaustao_de_quem_nao_tem(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True))
    assert "não está exausto" in td.remove_exhaustion("Aria")


# ---------------------------------------------------------------------------
# 4. Atitude de NPC
# ---------------------------------------------------------------------------

def test_atitude_move_e_muda_de_faixa(campanha, povoar):
    povoar(criar_ficha("Torbin", grupo=False))

    saida = tools.adjust_attitude("Torbin", 30, "o grupo salvou a filha dele")

    assert "+0 → **+30**" in saida
    assert "amistoso" in saida
    assert "Mudou de faixa" in saida
    assert campanha["characters"]["torbin"]["atitude"] == 30


def test_atitude_guarda_o_porque(campanha, povoar):
    povoar(criar_ficha("Torbin", grupo=False))
    tools.adjust_attitude("Torbin", 30, "salvaram a filha")
    tools.adjust_attitude("Torbin", -15, "quebraram a promessa do pagamento")

    detalhe = tools.get_attitude("Torbin")
    assert "+15" in detalhe
    assert "salvaram a filha" in detalhe
    assert "quebraram a promessa" in detalhe


def test_historico_de_atitude_nao_cresce_sem_fim(campanha, povoar):
    povoar(criar_ficha("Torbin", grupo=False))
    for i in range(9):
        tools.adjust_attitude("Torbin", 1, f"motivo {i}")
    assert len(campanha["characters"]["torbin"]["atitude_historico"]) == 5


def test_atitude_tem_teto_e_piso(campanha, povoar):
    povoar(criar_ficha("Torbin", grupo=False))
    tools.adjust_attitude("Torbin", 500)
    assert campanha["characters"]["torbin"]["atitude"] == 100
    tools.adjust_attitude("Torbin", -500)
    assert campanha["characters"]["torbin"]["atitude"] == -100


def test_atitude_de_quem_nao_existe(campanha):
    assert "não encontrado" in tools.adjust_attitude("Ninguém", 10)


def test_atitude_mexe_na_cd_do_teste_social(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True, carisma=16),
           criar_ficha("Torbin", grupo=False))

    tools.adjust_attitude("Torbin", 60, "deve a vida ao grupo")
    facil = td.social_check("Aria", "persuasão", 15, 10, target_name="Torbin")
    assert "CD 12" in facil          # 15 - 3

    tools.adjust_attitude("Torbin", -120, "descobriu a traição")
    dificil = td.social_check("Aria", "persuasão", 15, 10, target_name="Torbin")
    assert "CD 18" in dificil        # 15 + 3


def test_sem_alvo_a_cd_nao_muda(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True, carisma=16))
    saida = td.social_check("Aria", "persuasão", 15, 10)
    assert "CD 15" in saida


def test_lista_de_atitudes_ordena_do_pior_ao_melhor(campanha, povoar):
    povoar(criar_ficha("Torbin", grupo=False), criar_ficha("Elara", grupo=False))
    tools.adjust_attitude("Torbin", -40)
    tools.adjust_attitude("Elara", 50)

    lista = tools.list_attitudes()
    assert lista.index("Torbin") < lista.index("Elara")


# ---------------------------------------------------------------------------
# 5. Carga
# ---------------------------------------------------------------------------

def test_capacidade_vem_da_forca(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True, forca=16))
    s = campanha["characters"]["aria"]["sheet"]
    assert td._capacidade_kg(s) == pytest.approx(108.9, abs=0.2)


def test_carga_soma_peso_por_quantidade(campanha, povoar):
    chars = povoar(criar_ficha("Aria", grupo=True, forca=10))
    chars["Aria"]["inventario"] = [
        {"nome": "Poção de Cura", "qtd": 4, "peso": 0.25},
        {"nome": "Corda", "qtd": 1, "peso": 4.5},
    ]
    assert td._carga_atual(chars["Aria"]) == pytest.approx(5.5)


def test_sobrecarga_da_desvantagem_em_ataque(campanha, povoar):
    chars = povoar(criar_ficha("Aria", grupo=True, forca=10),
                   criar_ficha("Goblin", grupo=False, vida=30, ca=12))
    iniciar_combate(["Aria", "Goblin"])
    random.seed(2)
    leve = td.attack_roll("Aria", "Goblin", "espada longa", 8,
                          end_turn=False, _skip_turn_check=True)
    assert "desvantagem" not in leve.lower()

    # Capacidade com FOR 10 = 68 kg; metade = 34.
    chars["Aria"]["inventario"] = [{"nome": "Bigorna", "qtd": 1, "peso": 50}]
    random.seed(2)
    pesado = td.attack_roll("Aria", "Goblin", "espada longa", 8,
                            end_turn=False, _skip_turn_check=True)
    assert "desvantagem" in pesado.lower()


def test_sobrecarga_pesa_no_corpo_nao_na_cabeca(campanha, povoar):
    chars = povoar(criar_ficha("Aria", grupo=True, forca=10, inteligencia=14))
    chars["Aria"]["inventario"] = [{"nome": "Bigorna", "qtd": 1, "peso": 50}]

    random.seed(3)
    corpo = td.make_skill_check("Aria", "destreza", 10)
    random.seed(3)
    cabeca = td.make_skill_check("Aria", "inteligencia", 10)

    assert "desvantagem" in corpo.lower()
    assert "desvantagem" not in cabeca.lower()


def test_relatorio_de_carga(campanha, povoar):
    chars = povoar(criar_ficha("Aria", grupo=True, forca=10))
    chars["Aria"]["inventario"] = [{"nome": "Bigorna", "qtd": 1, "peso": 50}]

    saida = td.check_encumbrance("Aria")
    assert "sobrecarregado" in saida
    assert "Bigorna" in saida


def test_inventario_vazio_esta_livre(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True, forca=10))
    assert td._estado_de_carga(campanha["characters"]["aria"])[0] == "livre"


# ---------------------------------------------------------------------------
# 6. Loja
# ---------------------------------------------------------------------------

def test_loja_com_precos_informados(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True))
    saida = td.open_shop("Forja do Torbin",
                         "Espada Curta:10:2; Poção de Cura:50:3",
                         location="Oakhaven")

    assert "Forja do Torbin" in saida
    loja = campanha["lojas"]["forja do torbin"]
    assert len(loja["estoque"]) == 2
    assert loja["local"] == "Oakhaven"


def test_compra_debita_a_bolsa_e_entrega(campanha, povoar):
    chars = povoar(criar_ficha("Aria", grupo=True))
    chars["Aria"]["sheet"]["ouro"] = 100
    td.open_shop("Loja", "Poção de Cura:50:2")

    saida = td.buy_item("Aria", "Loja", "Poção de Cura", 1)

    assert "comprou" in saida
    assert chars["Aria"]["sheet"]["ouro"] == 50
    inv = {i["nome"]: i["qtd"] for i in chars["Aria"]["inventario"]}
    assert inv["Poção de Cura"] == 1
    assert campanha["lojas"]["loja"]["estoque"][0]["qtd"] == 1


def test_compra_sem_dinheiro_nao_tira_do_estoque(campanha, povoar):
    chars = povoar(criar_ficha("Aria", grupo=True))
    chars["Aria"]["sheet"].update({"ouro": 10, "prata": 0, "cobre": 0})
    td.open_shop("Loja", "Poção de Cura:50:2")

    saida = td.buy_item("Aria", "Loja", "Poção de Cura", 1)

    assert "não tem como pagar" in saida
    assert chars["Aria"]["sheet"]["ouro"] == 10
    assert campanha["lojas"]["loja"]["estoque"][0]["qtd"] == 2
    assert not chars["Aria"].get("inventario")


def test_compra_troca_prata_e_cobre(campanha, povoar):
    """Bolsa com trocado tem de conseguir pagar — 5 po = 50 pp."""
    chars = povoar(criar_ficha("Aria", grupo=True))
    chars["Aria"]["sheet"].update({"ouro": 0, "prata": 50, "cobre": 0})
    td.open_shop("Loja", "Adaga:5:1")

    td.buy_item("Aria", "Loja", "Adaga", 1)

    s = chars["Aria"]["sheet"]
    assert (s["ouro"], s["prata"], s["cobre"]) == (0, 0, 0)


def test_estoque_esgotado(campanha, povoar):
    chars = povoar(criar_ficha("Aria", grupo=True))
    chars["Aria"]["sheet"]["ouro"] = 500
    td.open_shop("Loja", "Adaga:5:1")

    assert "comprou" in td.buy_item("Aria", "Loja", "Adaga", 1)
    assert "não está à venda" in td.buy_item("Aria", "Loja", "Adaga", 1)


def test_venda_paga_metade(campanha, povoar):
    """
    Comprar e revender pelo mesmo preço seria uma torneira de ouro. A metade
    é o que fecha esse buraco.
    """
    chars = povoar(criar_ficha("Aria", grupo=True))
    chars["Aria"]["sheet"]["ouro"] = 0
    chars["Aria"]["inventario"] = [{"nome": "Adaga", "qtd": 2, "descricao": ""}]
    td.open_shop("Loja", "Adaga:10:1")

    saida = td.sell_item("Aria", "Loja", "Adaga", 2)

    assert "5 po" in saida or "10 po" in saida
    assert chars["Aria"]["sheet"]["ouro"] == 10        # 2 × (10 // 2)
    assert chars["Aria"]["inventario"] == []


def test_compra_avisa_sobrecarga(campanha, povoar):
    chars = povoar(criar_ficha("Aria", grupo=True, forca=10))
    chars["Aria"]["sheet"]["ouro"] = 1000
    chars["Aria"]["inventario"] = [{"nome": "Lastro", "qtd": 1, "peso": 33}]
    td.open_shop("Loja", "Armadura de Placas:1:1")

    saida = td.buy_item("Aria", "Loja", "Armadura de Placas", 1)
    assert "sobrecarregado" in saida


def test_loja_inexistente(campanha, povoar):
    povoar(criar_ficha("Aria", grupo=True))
    assert "não encontrada" in td.buy_item("Aria", "Fantasma", "Adaga")


# ---------------------------------------------------------------------------
# 7. Missões
# ---------------------------------------------------------------------------

def test_missao_nasce_com_objetivos(campanha):
    saida = tools.add_quest(
        "Escoltar a Princesa Elara",
        "Levar Elara a Luminas em segurança.",
        objectives="Sair de Oakhaven; Atravessar o Passo; Entregar em Luminas",
        giver="Princesa Elara", reward="200 po")

    assert "Missão aceita" in saida
    m = campanha["quests"]["escoltar a princesa elara"]
    assert m["status"] == "ativa"
    assert len(m["objetivos"]) == 3
    assert all(o["feito"] is False for o in m["objetivos"])
    assert m["quem_deu"] == "Princesa Elara"


def test_missao_repetida_e_recusada(campanha):
    tools.add_quest("Caçar o Lobo", "…")
    assert "Já existe" in tools.add_quest("Caçar o Lobo", "…")


def test_objetivo_marcado_por_trecho(campanha):
    tools.add_quest("Caçar o Lobo", "…", objectives="Achar o rastro; Matar o lobo")

    saida = tools.update_quest_objective("Caçar o Lobo", "rastro")

    assert "(1/2)" in saida
    objetivos = campanha["quests"]["caçar o lobo"]["objetivos"]
    assert objetivos[0]["feito"] is True
    assert objetivos[1]["feito"] is False


def test_objetivo_novo_e_registrado_em_vez_de_recusado(campanha):
    """Missão que só aceita o plano original não sobrevive à mesa."""
    tools.add_quest("Caçar o Lobo", "…", objectives="Achar o rastro")

    tools.update_quest_objective("Caçar o Lobo", "Descobrir quem soltou o lobo")

    textos = [o["texto"] for o in campanha["quests"]["caçar o lobo"]["objetivos"]]
    assert "Descobrir quem soltou o lobo" in textos


def test_ultimo_objetivo_avisa_para_encerrar(campanha):
    tools.add_quest("Caçar o Lobo", "…", objectives="Matar o lobo")
    saida = tools.update_quest_objective("Caçar o Lobo", "Matar")
    assert "complete_quest" in saida


def test_encerrar_missao(campanha):
    tools.add_quest("Caçar o Lobo", "…", reward="50 po")
    saida = tools.complete_quest("Caçar o Lobo", "concluida", "O lobo era um lobisomem.")

    assert "🏆" in saida and "50 po" in saida
    m = campanha["quests"]["caçar o lobo"]
    assert m["status"] == "concluida"
    assert m["desfecho"] == "O lobo era um lobisomem."


def test_desfecho_invalido(campanha):
    tools.add_quest("Caçar o Lobo", "…")
    assert "inválido" in tools.complete_quest("Caçar o Lobo", "meio-concluida")
    assert campanha["quests"]["caçar o lobo"]["status"] == "ativa"


def test_lista_separa_ativas_de_encerradas(campanha):
    tools.add_quest("Ativa", "…")
    tools.add_quest("Fechada", "…")
    tools.complete_quest("Fechada", "falhou")

    curta = tools.list_quests()
    assert "Ativa" in curta
    assert "Fechada" not in curta
    assert "1 encerrada" in curta

    longa = tools.list_quests(include_closed=True)
    assert "Fechada" in longa


def test_missoes_ativas_entram_no_contexto_da_cena(campanha):
    tools.add_quest("Escoltar Elara", "…",
                    objectives="Sair de Oakhaven; Chegar a Luminas")
    tools.update_quest_objective("Escoltar Elara", "Sair")

    ctx = tools.get_scene_context()

    assert "Missões ativas" in ctx
    assert "Escoltar Elara (1/2)" in ctx
    assert "falta: Chegar a Luminas" in ctx


def test_relogio_entra_no_contexto_da_cena(campanha):
    campanha["relogio"] = {"dia": 3, "hora": 21}
    assert "Dia 3, 21h (noite)" in tools.get_scene_context()


def test_atitudes_entram_no_contexto_da_cena(campanha, povoar):
    povoar(criar_ficha("Torbin", grupo=False))
    tools.adjust_attitude("Torbin", -45, "roubaram a forja")

    ctx = tools.get_scene_context()
    assert "Atitude dos NPCs" in ctx
    assert "Torbin -45 (desconfiado)" in ctx


def test_campanha_sem_onda4_nao_ganha_ruido_no_contexto(campanha):
    """Sem missão, sem relógio e sem atitude, o bloco de cena não muda."""
    campanha.pop("relogio", None)
    campanha.pop("quests", None)
    ctx = tools.get_scene_context()

    assert "Missões ativas" not in ctx
    assert "Atitude dos NPCs" not in ctx
    assert "Tempo:" not in ctx
