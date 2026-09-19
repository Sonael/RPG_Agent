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


def test_regras_de_d_e_d_so_nos_generos_em_que_fazem_sentido():
    """
    O D&D 5e é fantasia medieval: loja de espadas, grimório, peça de ouro.
    Serve a fantasia, dark fantasy, horror e mistério; romance, sci-fi e
    faroeste são sempre narrativos.
    """
    for genero in ("fantasia", "dark_fantasy", "horror", "misterio"):
        assert memory.regras_e_genero(genero, True) == (genero, True), genero
    for genero in ("romance", "scifi", "faroeste"):
        assert memory.regras_e_genero(genero, True) == (genero, False), genero
    assert set(memory.GENEROS_COM_REGRAS) <= set(memory.GENEROS)


def test_campanha_criada_com_regras_num_genero_narrativo_fica_sem_regras():
    import server

    romance = server._payload_de_campanha("Cartas", {"campaign_type": "romance",
                                                     "dnd_mode": True}, {})
    assert (romance["campaign_type"], romance["dnd_mode"]) == ("romance", False)


def test_campanha_carregada_num_genero_narrativo_perde_as_regras(campanha):
    memory.campaign["campaign_type"] = "scifi"
    memory.campaign["dnd_mode"] = True
    memory.normalizar_campanha()
    assert memory.campaign["dnd_mode"] is False
    assert "REGRAS DE D&D 5e" not in agent.instrucao_da_campanha("scifi", True)


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


def test_todo_genero_sabe_narrar_todo_tipo_de_cena():
    for genero in memory.GENEROS:
        cenas = agent._CENAS_POR_GENERO[genero]
        assert set(cenas) == set(agent.TIPOS_DE_CENA), genero
        for tipo, texto in cenas.items():
            assert len(texto) > 60, (genero, tipo)


def test_a_mesma_cena_e_narrada_diferente_em_cada_genero():
    """O romance do horror não é o romance do gênero romance."""
    for tipo in agent.TIPOS_DE_CENA:
        textos = [agent._CENAS_POR_GENERO[g][tipo] for g in memory.GENEROS]
        assert len(set(textos)) == len(textos), tipo


def test_romance_no_horror_tem_o_medo_na_sala():
    texto = agent.instrucao_da_campanha("horror", False)
    assert "COMO NARRAR CADA TIPO DE CENA NESTE GÊNERO" in texto
    assert "ROMANCE E INTIMIDADE: Amor sob ameaça" in texto
    # Só a tabela do gênero da campanha: a do romance não vaza.
    assert agent._CENAS_POR_GENERO["romance"]["romance"] not in texto


def test_cada_genero_leva_so_a_propria_tabela_de_cenas():
    for genero in memory.GENEROS:
        for dnd in (True, False):
            texto = agent.instrucao_da_campanha(genero, dnd)
            for outro in memory.GENEROS:
                romance = agent._CENAS_POR_GENERO[outro]["romance"]
                assert (romance in texto) == (outro == genero), (genero, outro, dnd)


def test_ordem_genero_tom_cenas_regras():
    """As cenas vêm depois do tom do mundo e antes das regras, que não mudam o tom."""
    texto = agent.instrucao_da_campanha("dark_fantasy", True)
    i_genero = texto.index("Você é um mestre de dark fantasy")
    i_tom = texto.index("VALE PARA TODA CENA")
    i_cenas = texto.index("COMO NARRAR CADA TIPO DE CENA")
    i_regras = texto.index("REGRAS DE D&D 5e")
    assert i_genero < i_tom < i_cenas < i_regras


def test_mestre_identifica_e_combina_os_tipos_de_cena():
    texto = agent.instrucao_da_campanha("fantasia", False)
    assert "identifique que tipo de cena é" in texto
    assert "combine as orientações" in texto
    for rotulo in agent.TIPOS_DE_CENA.values():
        assert f"• {rotulo}:" in texto, rotulo


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


def test_cada_genero_da_nome_as_proprias_telas():
    """A barra lateral dizia "Grupo" e "Missões" num romance."""
    nomes = {}
    for genero in memory.GENEROS:
        telas = agent.get_campaign_config(genero)["telas"]
        for chave in ("grupo", "missoes", "titulo_missoes", "mapa", "titulo_mapa"):
            assert telas.get(chave), (genero, chave)
        nomes[genero] = telas
    assert nomes["romance"]["missoes"] == "Tramas"
    assert nomes["horror"]["grupo"] == "Sobreviventes"
    # No romance, o atalho do grupo abre as Relações.
    assert nomes["romance"].get("tela_do_grupo") == "relacoes"
    assert not any(nomes[g].get("tela_do_grupo") for g in memory.GENEROS if g != "romance")


def test_memoria_manda_a_configuracao_com_as_regras():
    """/api/memory montava a configuração sem as regras: o rótulo perdia o "· D&D"."""
    import server

    cfg = server._config_da_campanha({"campaign_type": "horror", "dnd_mode": True})
    assert cfg["label"] == "Horror / Suspense · D&D"
    assert cfg["telas"]["grupo"] == "Sobreviventes"


def test_configuracao_aceita_o_dnd_antigo():
    cfg = agent.get_campaign_config("dnd")
    assert cfg["label"] == "Fantasia / Aventura · D&D"
