"""
test_genero_e_regras.py

Gênero e regras deixaram de ser o mesmo campo.

"dnd" era um valor de campaign_type, no mesmo seletor de fantasia, romance e
horror: quem queria fichas e combate tático recebia uma instrução quase toda
mecânica, sem direção de atmosfera nenhuma; quem queria um tom perdia o
motor. Era impossível jogar D&D em dark fantasy, horror com fichas, faroeste
com combate tático.

Agora campaign_type é só o GÊNERO (o tom do mundo) e dnd_mode é só a REGRA.
A instrução do mestre é composta pelos dois, e o tom do gênero vale para
toda cena — um romance numa campanha sombria sai sombrio.
"""
import pytest

from rpg import agent, memory, toolsets


# ---------------------------------------------------------------------------
# A migração
# ---------------------------------------------------------------------------

def test_dnd_antigo_vira_fantasia_com_as_regras():
    assert memory.regras_e_genero("dnd", False) == ("fantasia", True)


def test_genero_e_regras_se_combinam_livremente():
    assert memory.regras_e_genero("dark_fantasy", True) == ("dark_fantasy", True)
    assert memory.regras_e_genero("horror", True) == ("horror", True)
    assert memory.regras_e_genero("romance", False) == ("romance", False)


def test_genero_desconhecido_vira_fantasia_sem_mexer_nas_regras():
    assert memory.regras_e_genero("steampunk", True) == ("fantasia", True)
    assert memory.regras_e_genero(None, None) == ("fantasia", False)


def test_campanha_antiga_e_migrada_ao_carregar(campanha):
    memory.campaign["campaign_type"] = "dnd"
    memory.campaign["dnd_mode"] = False
    memory.normalizar_campanha()
    assert (memory.campaign["campaign_type"], memory.campaign["dnd_mode"]) == ("fantasia", True)


def test_campanha_nova_nao_e_mexida(campanha):
    memory.campaign["campaign_type"] = "horror"
    memory.campaign["dnd_mode"] = True
    memory.normalizar_campanha()
    assert (memory.campaign["campaign_type"], memory.campaign["dnd_mode"]) == ("horror", True)


def test_campanha_criada_pelo_menu_passa_pela_mesma_regra():
    import server

    velha = server._payload_de_campanha("Velha", {"campaign_type": "dnd"}, {})
    assert (velha["campaign_type"], velha["dnd_mode"]) == ("fantasia", True)
    nova = server._payload_de_campanha("Nova", {"campaign_type": "dark_fantasy",
                                                "dnd_mode": True}, {})
    assert (nova["campaign_type"], nova["dnd_mode"]) == ("dark_fantasy", True)


# ---------------------------------------------------------------------------
# A instrução do mestre
# ---------------------------------------------------------------------------

def test_todo_genero_tem_instrucao_de_tom():
    for genero in memory.GENEROS:
        assert genero in agent._STYLE_INSTRUCTIONS, genero
    assert "dnd" not in memory.GENEROS


def test_dark_fantasy_com_regras_tem_o_tom_e_o_motor():
    texto = agent.instrucao_da_campanha("dark_fantasy", True)
    assert "dark fantasy" in texto.lower()
    assert "REGRAS DE D&D 5e" in texto
    # O tom vem antes das regras, e as regras avisam que não mudam o tom.
    assert texto.index("dark fantasy") < texto.index("REGRAS DE D&D 5e")
    assert "O TOM continua sendo o do gênero" in texto


def test_sem_regras_nao_ha_bloco_de_d_e_d():
    texto = agent.instrucao_da_campanha("dark_fantasy", False)
    assert "REGRAS DE D&D 5e" not in texto


def test_o_tom_vale_para_toda_cena_em_qualquer_genero():
    """É o que faz o romance numa campanha sombria sair sombrio."""
    for genero in memory.GENEROS:
        for dnd in (True, False):
            texto = agent.instrucao_da_campanha(genero, dnd)
            assert "VALE PARA TODA CENA" in texto, (genero, dnd)
            assert "íntima E sombria" in texto


def test_campanha_dnd_antiga_ganha_tom_de_fantasia():
    """Antes a instrução de "dnd" não tinha atmosfera nenhuma."""
    texto = agent.instrucao_da_campanha("dnd", False)
    assert "Você é um mestre de RPG de fantasia" in texto
    assert "REGRAS DE D&D 5e" in texto


def test_create_agent_nao_desliga_as_regras_de_um_genero(campanha):
    """
    create_agent fazia dnd_mode = (campaign_type == "dnd"): abrir uma
    campanha de horror com fichas desligava o motor dela.
    """
    agent.create_agent("gemini-2.5-flash", "horror", True)
    assert memory.campaign["dnd_mode"] is True
    assert memory.campaign["campaign_type"] == "horror"


def test_create_agent_sem_regras_informadas_usa_as_da_campanha(campanha):
    memory.campaign["dnd_mode"] = True
    agent.create_agent("gemini-2.5-flash", "dark_fantasy")
    assert memory.campaign["dnd_mode"] is True


# ---------------------------------------------------------------------------
# O motor segue as regras, não o gênero
# ---------------------------------------------------------------------------

def test_ferramentas_de_d_e_d_em_qualquer_genero(campanha):
    memory.campaign["campaign_type"] = "horror"
    memory.campaign["dnd_mode"] = True
    assert toolsets._campanha_usa_dnd(memory.campaign) is True

    memory.campaign["dnd_mode"] = False
    memory.campaign["characters"] = {}
    assert toolsets._campanha_usa_dnd(memory.campaign) is False


# ---------------------------------------------------------------------------
# A configuração de tela
# ---------------------------------------------------------------------------

def test_configuracao_de_tela_junta_genero_e_regras():
    cfg = agent.get_campaign_config("dark_fantasy", True)
    assert cfg["label"] == "Dark Fantasy · D&D"
    assert cfg["role_label"] == "Classe"
    assert cfg["party_label"] == "Companhia"

    livre = agent.get_campaign_config("dark_fantasy", False)
    assert livre["label"] == "Dark Fantasy" and livre["role_label"] != "Classe"


def test_configuracao_aceita_o_dnd_antigo():
    cfg = agent.get_campaign_config("dnd")
    assert cfg["label"] == "Fantasia / Aventura · D&D"
