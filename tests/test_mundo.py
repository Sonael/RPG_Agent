"""
test_mundo.py

O mundo da fantasia: o que o D&D não mede.

Renome, facções e títulos; mudanças nos lugares; laços dos companheiros;
lendas e profecias; o bestiário. Valem para a fantasia e o dark fantasy, com e
sem as regras de D&D. Na tela, só o que o grupo sabe; para o mestre, tudo.
"""
import asyncio

import pytest

from rpg import agent, bestiario, faccoes, lacos, lendas, memory, mudancas, mundo, tools, toolsets


@pytest.fixture
def fantasia(campanha):
    campanha["campaign_type"] = "fantasia"
    campanha["dnd_mode"] = False
    campanha["protagonist"] = "Aria"
    campanha["chapter"] = 3
    campanha["current_location"] = "Vaelmoor"
    campanha["characters"] = {
        "aria": {"name": "Aria", "description": "A protagonista."},
        "kael": {"name": "Kael", "description": "Paladino caído."},
        "mira": {"name": "Mira", "description": "Ladra."},
        "barao": {"name": "Barão Vael", "description": "Senhor de Vaelmoor."},
    }
    campanha["party"] = [{"name": "Kael", "role": "paladino"}, {"name": "Mira", "role": "ladra"}]
    campanha["locations"] = {"vaelmoor": {"name": "Vaelmoor", "description": "Vila no vale."},
                             "ponte velha": {"name": "Ponte Velha", "description": "Caída."}}
    for chave in ("renome", "faccoes", "titulos", "lendas", "bestiario"):
        campanha.pop(chave, None)
    return campanha


# ---------------------------------------------------------------------------
# 1. Renome e facções
# ---------------------------------------------------------------------------

def test_renome_sobe_com_faixas(fantasia):
    saida = tools.ajustar_renome(35, "Mataram o wyrm de Cinza")
    assert "Renome do grupo: 0 → **35** (conhecidos no reino)" in saida
    assert "estranhos reagem" in saida
    r = faccoes.renome()
    assert (r["valor"], r["faixa"]) == (35, "conhecidos no reino")
    assert r["historico"][0] == {"delta": 35, "motivo": "Mataram o wyrm de Cinza", "capitulo": 3}
    tools.ajustar_renome(200)
    assert faccoes.renome()["valor"] == 100 and faccoes.renome()["faixa"] == "lendários"


def test_reputacao_com_faccoes(fantasia):
    saida = tools.ajustar_reputacao("Casa Vael", 25, "Salvaram a filha do barão", tipo="casa nobre",
                                   descricao="Senhores do vale")
    assert "Casa Vael (casa nobre): +0 → **+25** (respeitados)" in saida
    tools.ajustar_reputacao("Guilda das Sombras", -40, "Entregaram o contrabando", tipo="guilda")
    lista = faccoes.faccoes_visiveis()
    # As que mais pesam primeiro, para o bem ou para o mal.
    assert [f["nome"] for f in lista] == ["Guilda das Sombras", "Casa Vael"]
    assert lista[0]["faixa"] == "hostis"


def test_faccao_desconhecida_fica_com_o_mestre(fantasia):
    saida = tools.ajustar_reputacao("O Olho Cinzento", -20, "Os vigiam", tipo="culto", conhecida=False)
    assert "NÃO conhece" in saida
    assert faccoes.faccoes_visiveis() == []
    assert "O Olho Cinzento" in faccoes.resumo_para_o_mestre()
    assert "o grupo NÃO conhece" in faccoes.resumo_para_o_mestre()


# ---------------------------------------------------------------------------
# 2. Títulos
# ---------------------------------------------------------------------------

def test_titulos(fantasia):
    assert "Kael agora é chamado de **O Juramentado**" in tools.conceder_titulo(
        "Kael", "O Juramentado", "Cumpriu o voto", "abre as portas da ordem")
    tools.conceder_titulo("o grupo", "Os Sem-Bandeira", "Recusaram servir ao rei")
    assert [t["titulo"] for t in faccoes.titulos()] == ["Os Sem-Bandeira", "O Juramentado"]
    assert faccoes.titulos("Kael")[0]["efeito"] == "abre as portas da ordem"
    assert "já foi dado" in tools.conceder_titulo("Mira", "o juramentado")
    assert "não encontrado" in tools.conceder_titulo("Fulano", "Qualquer")
    assert "Dê o título" in tools.conceder_titulo("Kael", "  ")


# ---------------------------------------------------------------------------
# 3. Mudanças no mundo
# ---------------------------------------------------------------------------

def test_mudancas_nos_lugares(fantasia):
    assert "Ponte Velha mudou: **A ponte foi reconstruída**" in tools.registrar_mudanca(
        "Ponte Velha", "A ponte foi reconstruída", "o grupo pagou os pedreiros")
    tools.registrar_mudanca("Vaelmoor", "A vila prosperou", "os bandidos foram expulsos")
    assert mudancas.do_lugar("Ponte Velha")[0]["causa"] == "o grupo pagou os pedreiros"
    assert {m["lugar"] for m in mudancas.todas()} == {"Ponte Velha", "Vaelmoor"}
    assert "já está registrada" in tools.registrar_mudanca("Vaelmoor", "a vila  prosperou")
    assert "não encontrado" in tools.registrar_mudanca("Atlântida", "Afundou")


def test_ficha_do_local_e_mapa_mostram_a_mudanca(fantasia):
    from rpg import locais, mapa

    tools.registrar_mudanca("Ponte Velha", "A ponte foi reconstruída")
    assert locais.ficha("Ponte Velha")["mudancas"][0]["texto"] == "A ponte foi reconstruída"
    nos = {n["nome"]: n for n in mapa.mapa_snapshot()["arvore"]}
    assert nos["Ponte Velha"]["mudancas"] == 1
    assert nos["Vaelmoor"]["mudancas"] == 0


# ---------------------------------------------------------------------------
# 4. Laços e lealdade
# ---------------------------------------------------------------------------

def test_lealdade_e_arco(fantasia):
    assert "lealdade +0 → **+30** (leal)" in tools.ajustar_lealdade("Kael", 30, "O grupo poupou o prisioneiro")
    tools.definir_arco("Kael", "limpar o nome do pai", "A redenção de Kael")
    tools.avancar_arco("Kael", "Encontrou o selo do pai")
    c = lacos.companheiros()[0]
    assert (c["nome"], c["lealdade"]["faixa"], c["objetivo"]) == ("Kael", "leal", "limpar o nome do pai")
    assert c["arco"]["titulo"] == "A redenção de Kael" and c["arco"]["passos"][0]["texto"] == "Encontrou o selo do pai"
    tools.avancar_arco("Kael", "Provou a inocência do pai", estado="cumprido")
    assert lacos.companheiros()[0]["arco"]["estado"] == "cumprido"


def test_lealdade_baixa_avisa_e_vem_primeiro(fantasia):
    tools.ajustar_lealdade("Kael", 40)
    saida = tools.ajustar_lealdade("Mira", -60, "O grupo a entregou à guarda")
    assert "à beira de partir" in saida and "abandono ou traição" in saida
    assert [c["nome"] for c in lacos.companheiros()] == ["Mira", "Kael"]


def test_lacos_validam(fantasia):
    assert "companheiros, não do protagonista" in tools.ajustar_lealdade("Aria", 10)
    assert "definir_arco primeiro" in tools.avancar_arco("Mira", "Algo")
    assert "Estado desconhecido" in (tools.definir_arco("Mira", arco="A dívida") and
                                     tools.avancar_arco("Mira", "", estado="talvez"))
    assert "diferente de zero" in tools.ajustar_lealdade("Mira", 0)


def test_ficha_do_personagem_traz_laco_e_titulos(fantasia):
    from rpg import personagens

    tools.ajustar_lealdade("Kael", 20)
    tools.conceder_titulo("Kael", "O Juramentado")
    ficha = personagens.ficha("Kael")
    assert ficha["laco"]["lealdade"]["valor"] == 20
    assert ficha["titulos"][0]["titulo"] == "O Juramentado"
    fantasia["campaign_type"] = "romance"
    assert personagens.ficha("Kael")["laco"] is None


# ---------------------------------------------------------------------------
# 6. Lendas e profecias
# ---------------------------------------------------------------------------

def test_lenda_escondida_ate_o_primeiro_fragmento(fantasia):
    tools.registrar_lenda("A Coroa Afogada", "artefato perdido", verdade="Está no fundo do lago de Vaelmoor")
    assert lendas.visiveis() == []
    assert "verdade: Está no fundo do lago" in lendas.resumo_para_o_mestre()
    tools.revelar_fragmento("A Coroa Afogada", "Um rei jogou a coroa na água para não entregá-la", "um velho pescador")
    l = lendas.visiveis()[0]
    assert l["titulo"] == "A Coroa Afogada" and l["fragmentos"][0]["fonte"] == "um velho pescador"
    # A verdade nunca vai para a tela.
    assert "fundo do lago" not in str(lendas.visiveis())


def test_lenda_resolvida_vai_para_o_fim(fantasia):
    tools.registrar_lenda("A Profecia do Sétimo Filho", "profecia", conhecida=True)
    tools.registrar_lenda("A Coroa Afogada", "artefato perdido", conhecida=True)
    tools.resolver_lenda("A Coroa Afogada", "Aria achou a coroa no lago")
    assert [l["titulo"] for l in lendas.visiveis()] == ["A Profecia do Sétimo Filho", "A Coroa Afogada"]
    assert lendas.visiveis()[1]["desfecho"] == "Aria achou a coroa no lago"
    assert "A Coroa Afogada" not in lendas.resumo_para_o_mestre()


def test_lendas_validam(fantasia):
    assert "Tipo desconhecido" in tools.registrar_lenda("X", "boato")
    tools.registrar_lenda("X", "lenda")
    assert "já existe" in tools.registrar_lenda("x", "lenda")
    assert "não encontrada" in tools.revelar_fragmento("Y", "algo")
    tools.revelar_fragmento("X", "algo")
    assert "já foi revelado" in tools.revelar_fragmento("X", "algo")


# ---------------------------------------------------------------------------
# 8. Bestiário
# ---------------------------------------------------------------------------

def test_bestiario(fantasia):
    assert "Nova página no bestiário: **Carniçal**" in tools.registrar_criatura("Carniçal", "Morto faminto", "morto-vivo")
    tools.registrar_criatura("Carniçal", derrotada=True)
    tools.anotar_criatura("Carniçal", "Caça em bando à noite")
    tools.anotar_criatura("Carniçal", "A luz do sol o queima", tipo="fraqueza")
    c = bestiario.visiveis()[0]
    assert (c["encontros"], c["derrotadas"]) == (2, 1)
    assert c["fatos"] == ["Caça em bando à noite"] and c["fraquezas"] == ["A luz do sol o queima"]
    assert "já sabe disso" in tools.anotar_criatura("Carniçal", "caça em bando à noite")
    assert "registrar_criatura primeiro" in tools.anotar_criatura("Dragão", "voa")


# ---------------------------------------------------------------------------
# O mestre, as ferramentas e o gênero
# ---------------------------------------------------------------------------

def test_bloco_de_cena_da_fantasia(fantasia):
    tools.ajustar_renome(20, "Salvaram Vaelmoor")
    tools.registrar_mudanca("Vaelmoor", "A vila prosperou")
    tools.definir_arco("Kael", "limpar o nome do pai", "A redenção de Kael")
    tools.registrar_lenda("A Coroa Afogada", verdade="No lago")
    tools.registrar_criatura("Carniçal")
    tools.anotar_criatura("Carniçal", "Sol o queima", tipo="fraqueza")
    bloco = mundo.bloco_de_cena()
    for trecho in ("O MUNDO", "Renome do grupo: 20 (falados na região)", "COMO ESTE LUGAR MUDOU",
                   "Vaelmoor — A vila prosperou", "Kael: lealdade +0", "arco \"A redenção de Kael\"",
                   "A Coroa Afogada", "verdade: No lago", "Carniçal: o grupo sabe das fraquezas — Sol o queima"):
        assert trecho in bloco, trecho


def test_instrucao_de_cada_turno_leva_o_mundo(fantasia):
    tools.ajustar_renome(10)
    agente = agent.create_agent("gemini-2.5-flash", "fantasia", False)
    assert "O MUNDO (o que o grupo construiu" in agente.instruction(None)


def test_dark_fantasy_tambem_e_fora_da_fantasia_nao(fantasia):
    tools.ajustar_renome(10)
    fantasia["campaign_type"] = "dark_fantasy"
    assert "O MUNDO" in mundo.bloco_de_cena()
    fantasia["campaign_type"] = "horror"
    assert mundo.bloco_de_cena() == ""


def test_ferramentas_so_na_fantasia_e_no_dark_fantasy(fantasia):
    conjunto = toolsets.FerramentasDoTurno(tools.ALL_TOOLS)
    nomes = lambda: {t.name for t in asyncio.run(conjunto.get_tools())}  # noqa: E731
    assert toolsets.FERRAMENTAS_SO_DA_FANTASIA <= nomes()
    fantasia["campaign_type"] = "dark_fantasy"
    fantasia["dnd_mode"] = True
    assert toolsets.FERRAMENTAS_SO_DA_FANTASIA <= nomes()
    fantasia["campaign_type"] = "romance"
    fantasia["dnd_mode"] = False
    assert not (toolsets.FERRAMENTAS_SO_DA_FANTASIA & nomes())


def test_instrucao_da_fantasia_ensina_o_mundo():
    for genero in ("fantasia", "dark_fantasy"):
        for dnd in (True, False):
            texto = agent.instrucao_da_campanha(genero, dnd)
            assert "O MUNDO REAGE, E OS COMPANHEIROS SÃO GENTE" in texto, (genero, dnd)
    assert "O MUNDO REAGE" not in agent.instrucao_da_campanha("horror", True)


def test_a_barra_da_fantasia_tem_o_mundo():
    assert agent.get_campaign_config("fantasia")["telas"]["mundo"] == "Mundo"
    assert agent.get_campaign_config("dark_fantasy", True)["telas"]["mundo"] == "Mundo"
    assert "mundo" not in agent.get_campaign_config("horror")["telas"]


def test_importar_o_mundo_da_fantasia():
    import server

    dados = {"campaign_type": "fantasia", "renome": {"valor": 250},
             "faccoes": [{"nome": "Casa Vael", "tipo": "casa nobre", "reputacao": 40},
                         {"nome": "O Olho Cinzento", "reputacao": -300, "conhecida": False}],
             "titulos": [{"titulo": "O Juramentado", "quem": "Kael"}, {"quem": "sem título"}],
             "lendas": {"a coroa": {"titulo": "A Coroa", "tipo": "lenda", "fragmentos": [], "conhecida": True}},
             "bestiario": {"carnical": {"nome": "Carniçal", "fatos": [], "fraquezas": []}}}
    p = server._payload_de_campanha("Vale", dados, {})
    assert p["renome"]["valor"] == 100
    assert p["faccoes"]["o olho cinzento"]["reputacao"] == -100
    assert p["faccoes"]["o olho cinzento"]["conhecida"] is False
    assert [t["titulo"] for t in p["titulos"]] == ["O Juramentado"]
    assert "a coroa" in p["lendas"] and "carnical" in p["bestiario"]
