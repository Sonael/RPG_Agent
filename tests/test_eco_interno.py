"""
test_eco_interno.py
O que é do motor não aparece no chat do jogador.

Os textos daqui são REAIS: saíram da campanha jogada (campaigns_rows.json),
onde o retrato da cena e o bloco de combate estavam gravados no histórico,
visíveis para o jogador.

Duas portas, testadas separadamente:
  • o resultado das ferramentas de contexto não é transmitido para a tela
    (server._resultado_para_a_tela);
  • o eco que o próprio mestre copia para dentro da narração é cortado
    (rpg/eco.py).
"""
import re

import pytest

import server
from rpg import eco


# O fim de get_scene_context(), como o jogador o recebeu.
RETRATO = """[Cap.1 | Colinas Cinzentas]
Cena: Sonael, Helena e Selene cavalgam em direção às Colinas Cinzentas.

Tempo: Dia 4, 10h (manhã)

Personagens conhecidos — os marcados [grupo] estão com o jogador:
• Helena [grupo] (vivo): Uma guerreira de postura inabalável
Traços: Protetora, direta, impaciente

Mapa do local atual:
• Fica em: Valenport
• Dentro daqui: Mina do Corvo de Pedra

Atitude dos NPCs: Selene -5 (neutro) | Helena +20 (amistoso)

Status D&D:
Helena Nv.2 guerreiro PV[▓▓▓▓▓▓▓▓]22/22 Mana 0/0 CA 19"""

# O eco que o mestre copiou para o fim da narração.
COMBATE = """COMBATE ATIVO — ESTADO ATUAL (NÃO RE-EXECUTE TURNOS ANTERIORES):
   Rodada: 1
   Ordem: Selene → Helena → Mineiro Corrompido 2 → Sonael
   Turno atual: Selene
   INSTRUÇÃO CRÍTICA: o histórico acima já contém ações processadas. Aguarde a ação do jogador — é a vez de Selene."""

NARRACAO = ("Os mineiros corrompidos os encaram fixamente e avançam para o ataque!\n\n"
            "*(O combate prossegue na tela tática. Faça sua jogada, Selene!)*")


# ---------------------------------------------------------------------------
# A porta 1: o resultado da ferramenta de contexto não vai para a tela
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ferramenta", ["get_scene_context", "get_full_context"])
def test_contexto_nao_vai_para_a_tela(ferramenta):
    assert server._resultado_para_a_tela(ferramenta, RETRATO) == ""


def test_as_outras_ferramentas_continuam_aparecendo():
    texto = "Cultista do Minério 1 criado(s) com stats reais (Open5e)!"
    assert server._resultado_para_a_tela("spawn_monster", texto) == texto


def test_instrucao_ao_modelo_sai_do_resultado():
    visivel = server._resultado_para_a_tela(
        "attack_roll", "Acertou por 3 de dano.[[llm]]Lembre de gastar a Ação.[[/llm]]")
    assert "Acertou" in visivel and "Ação" not in visivel


def test_o_chat_usa_esta_porta():
    """Sem esta linha no servidor, o resultado volta a ir cru para a tela."""
    import inspect
    fonte = inspect.getsource(server.chat)
    assert "_resultado_para_a_tela(fr.name, conteudo)" in fonte


# ---------------------------------------------------------------------------
# A porta 2: o eco dentro da narração
# ---------------------------------------------------------------------------

def test_bloco_de_combate_sai_e_a_narracao_fica():
    limpo, cortados = eco.tirar_ecos(f"{NARRACAO}\n\n{COMBATE}")
    assert "COMBATE ATIVO" not in limpo
    assert "INSTRUÇÃO CRÍTICA" not in limpo
    assert "Rodada: 1" not in limpo
    assert "avançam para o ataque" in limpo
    assert "tela tática" in limpo
    assert cortados


def test_retrato_da_cena_sai_inteiro():
    limpo, cortados = eco.tirar_ecos(f"{RETRATO}\n\nA estrada sobe entre pedras soltas.")
    assert "Cap.1" not in limpo
    assert "Status D&D" not in limpo
    assert "Atitude dos NPCs" not in limpo
    assert "Mapa do local atual" not in limpo
    assert "Traços:" not in limpo
    assert limpo.strip() == "A estrada sobe entre pedras soltas."
    assert len(cortados) >= 2


def test_eco_no_meio_nao_leva_a_narracao_de_depois():
    texto = (f"Helena avança com o escudo erguido.\n\n{COMBATE}\n\n"
             "Selene ergue o símbolo sagrado e a luz se espalha pela câmara.")
    limpo, _ = eco.tirar_ecos(texto)
    assert "Helena avança" in limpo
    assert "Selene ergue o símbolo" in limpo
    assert "COMBATE ATIVO" not in limpo


def test_campo_de_batalha_e_lados_saem():
    texto = ("A câmara se abre diante do grupo.\n\n"
             "Campo de batalha: Fenda de Acesso → Altar Ritualístico\n"
             "• Fenda de Acesso — fenda recém-aberta: [grupo] Sonael\n"
             "Lados — grupo: Sonael, Helena · contra: Cultista do Minério 1")
    limpo, cortados = eco.tirar_ecos(texto)
    assert limpo.strip() == "A câmara se abre diante do grupo."
    assert cortados


def test_narracao_normal_passa_intacta():
    texto = ("A chuva bate no telhado da taverna.\n\n"
             "— O bastante para que vocês não precisem perguntar de novo.\n\n"
             "Stelar cruza os braços. A decisão é de vocês.")
    limpo, cortados = eco.tirar_ecos(texto)
    assert limpo == texto
    assert cortados == []


def test_texto_que_so_fala_de_capitulo_nao_e_cortado():
    """"Capítulo" em prosa não é marca: a marca é o cabeçalho [Cap.N | local]."""
    texto = "O capítulo 2 começa com o grupo diante dos portões de Valenport."
    limpo, cortados = eco.tirar_ecos(texto)
    assert limpo == texto and cortados == []


def test_corte_que_apagaria_o_turno_devolve_o_texto():
    """Um turno sem resposta é pior do que um turno com eco."""
    limpo, cortados = eco.tirar_ecos(RETRATO)
    assert limpo == RETRATO.strip()
    assert cortados == []


def test_vazio_nao_quebra():
    assert eco.tirar_ecos("") == ("", [])
    assert eco.tirar_ecos(None) == ("", [])


def test_o_chat_corta_o_eco_antes_de_guardar():
    import inspect
    fonte = inspect.getsource(server.chat)
    assert "eco.tirar_ecos(response_text)" in fonte
    # Antes do fechamento do turno: nome que só aparece no eco não pode valer
    # como prova de que a cena o citou.
    assert fonte.index("eco.tirar_ecos") < fonte.index("epilogo.processar")


def test_retomada_antiga_nao_volta_como_fala_do_jogador():
    """Campanhas antigas têm a mensagem de retomada gravada no histórico."""
    recap = ("Estamos retomando uma aventura em andamento. Abaixo está o estado "
             "completo do mundo e o histórico recente.")
    assert server._tipo_de_mensagem_interna(recap) == "comando"
