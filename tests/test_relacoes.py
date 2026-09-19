"""
test_relacoes.py

As relações do romance: afeto e confiança de cada pessoa com o protagonista,
o vínculo e o porquê de cada mudança.

No romance a relação só existia como flag solta (confianca_lucas=alta) e como
a atitude das fichas, pensada para a loja e os testes sociais do D&D. Agora
ela tem dois eixos separados, porque o drama mora na diferença: dá para amar
quem não se confia.
"""
import asyncio

import pytest

from rpg import agent, memory, personagens, relacoes, tools, toolsets


@pytest.fixture
def romance(campanha):
    campanha["campaign_type"] = "romance"
    campanha["dnd_mode"] = False
    campanha["protagonist"] = "Clara"
    campanha["chapter"] = 3
    campanha["characters"] = {
        "clara": {"name": "Clara", "description": "A protagonista."},
        "lucas": {"name": "Lucas", "description": "O vizinho."},
        "marina": {"name": "Marina", "description": "Amiga de infância."},
        memory.char_key("Sr. Otávio"): {"name": "Sr. Otávio", "description": "O dono da livraria."},
    }
    campanha["party"] = [{"name": "Lucas", "role": "interesse romântico"},
                         {"name": "Marina", "role": "melhor amiga"}]
    return campanha


def test_afeto_e_confianca_sao_eixos_separados(romance):
    tools.ajustar_relacao("Lucas", afeto=30, confianca=-15,
                          motivo="Ele guardou o segredo, mas mentiu sobre a carta")
    lucas = romance["characters"]["lucas"]
    assert relacoes.afeto_de(lucas) == 30
    assert relacoes.confianca_de(lucas) == -15
    # Uma linha por eixo, com o capítulo.
    assert [(h["eixo"], h["delta"], h["cap"]) for h in lucas["relacao_historico"]] == \
        [("afeto", 30, 3), ("confianca", -15, 3)]


def test_afeto_e_a_atitude_das_fichas(romance):
    """O que o mestre já registrou com adjust_attitude continua valendo."""
    tools.adjust_attitude("Marina", 25, "Ficou do seu lado na briga")
    assert relacoes.afeto_de(romance["characters"]["marina"]) == 25
    # E conta a história na tela de Relações também.
    assert romance["characters"]["marina"]["relacao_historico"][-1]["motivo"] == "Ficou do seu lado na briga"


def test_limites_e_entrada_invalida(romance):
    tools.ajustar_relacao("Lucas", afeto=90)
    tools.ajustar_relacao("Lucas", afeto=90)
    assert relacoes.afeto_de(romance["characters"]["lucas"]) == 100
    assert "números inteiros" in tools.ajustar_relacao("Lucas", afeto="muito")
    assert "Nada a mudar" in tools.ajustar_relacao("Lucas")
    assert "não encontrado" in tools.ajustar_relacao("Fulano", afeto=5)


def test_historico_curto(romance):
    for i in range(relacoes.MAX_HISTORICO + 5):
        tools.ajustar_relacao("Lucas", afeto=1, motivo=f"gesto {i}")
    hist = romance["characters"]["lucas"]["relacao_historico"]
    assert len(hist) == relacoes.MAX_HISTORICO
    assert hist[-1]["motivo"] == f"gesto {relacoes.MAX_HISTORICO + 4}"


def test_vinculo_comeca_pelo_papel_e_muda_quando_o_mestre_diz(romance):
    lucas = romance["characters"]["lucas"]
    assert relacoes.vinculo_de(lucas) == "interesse romântico"
    saida = tools.ajustar_relacao("Lucas", vinculo="namoro", afeto=15, motivo="O primeiro beijo")
    assert relacoes.vinculo_de(lucas) == "namoro"
    assert "interesse romântico → **namoro**" in saida


def test_faixas_com_nomes_de_romance(romance):
    tools.ajustar_relacao("Lucas", afeto=70, confianca=-65, motivo="Ama, mas não acredita")
    p = next(x for x in relacoes.lista()["pessoas"] if x["nome"] == "Lucas")
    assert p["afeto"]["rotulo"] == "devoção"
    assert p["confianca"]["rotulo"] == "desconfia de você"


def test_lista_proximos_primeiro_e_sem_o_protagonista(romance):
    tools.ajustar_relacao("Sr. Otávio", afeto=80, motivo="Emprestou o livro raro")
    tools.ajustar_relacao("Marina", afeto=40)
    tools.ajustar_relacao("Lucas", afeto=10)
    nomes = [p["nome"] for p in relacoes.lista()["pessoas"]]
    # Próximos (o grupo) antes, do afeto maior ao menor; depois os outros.
    assert nomes == ["Marina", "Lucas", "Sr. Otávio"]
    assert "Clara" not in nomes


def test_quem_nunca_foi_tocado_e_nao_e_proximo_fica_de_fora(romance):
    nomes = [p["nome"] for p in relacoes.lista()["pessoas"]]
    assert "Sr. Otávio" not in nomes
    assert {"Lucas", "Marina"} <= set(nomes)


def test_ficha_do_personagem_mostra_a_relacao_no_romance(romance):
    tools.ajustar_relacao("Lucas", afeto=20, confianca=10, motivo="Café na chuva")
    ficha = personagens.ficha("Lucas")
    # Mesmo sendo do grupo: é justamente de quem se quer saber.
    assert ficha["do_grupo"] is True
    assert ficha["relacao"]["afeto"]["valor"] == 20
    assert ficha["relacao"]["historico"][0]["motivo"] == "Café na chuva"
    assert ficha["atitude"] is None


def test_fora_do_romance_a_ficha_mantem_a_atitude(campanha):
    campanha["campaign_type"] = "horror"
    campanha["characters"] = {"velho": {"name": "Velho", "atitude": 30}}
    campanha["party"] = []
    ficha = personagens.ficha("Velho")
    assert ficha["relacao"] is None
    assert ficha["atitude"]["valor"] == 30
    # Sem regras de D&D, a atitude não mexe em CD nem em preço.
    assert ficha["atitude"]["efeitos"] == []


def test_mestre_ve_todas_as_relacoes(romance):
    tools.ajustar_relacao("Lucas", afeto=30, confianca=-20)
    texto = tools.ver_relacoes()
    assert "Lucas (interesse romântico) — amizade: afeto +30 (afeição), confiança -20 (com um pé atrás)" in texto


def test_ferramentas_de_relacao_so_no_romance(romance):
    conjunto = toolsets.FerramentasDoTurno(tools.ALL_TOOLS)

    def nomes():
        return {t.name for t in asyncio.run(conjunto.get_tools())}

    do_romance = {"ajustar_relacao", "mudar_estagio", "marcar_momento", "ver_relacoes"}
    assert do_romance <= nomes()
    romance["campaign_type"] = "horror"
    assert not (do_romance & nomes())


def test_instrucao_do_romance_manda_usar_a_ferramenta():
    texto = agent.instrucao_da_campanha("romance", False)
    assert "ajustar_relacao(nome, afeto, confianca" in texto
    assert "confianca_lucas=alta" not in texto


# ---------------------------------------------------------------------------
# Estágio da relação
# ---------------------------------------------------------------------------

def test_estagio_comeca_na_amizade_para_proximos_e_conhecidos_para_o_resto(romance):
    chars = romance["characters"]
    assert relacoes.estagio_de(chars["lucas"]) == "amizade"
    assert relacoes.estagio_de(chars[memory.char_key("Sr. Otávio")]) == "conhecidos"


def test_mudar_estagio_vira_um_momento(romance):
    tools.ajustar_relacao("Lucas", afeto=60, confianca=30)
    saida = tools.mudar_estagio("Lucas", "namoro", "Ele pediu na ponte, sob a chuva")
    lucas = romance["characters"]["lucas"]
    assert relacoes.estagio_de(lucas) == "namoro"
    assert "amizade → **namoro**" in saida and "Aviso" not in saida
    marco = lucas["momentos"][-1]
    assert (marco["titulo"], marco["descricao"], marco["tipo"], marco["cap"]) == \
        ("Começaram a namorar", "Ele pediu na ponte, sob a chuva", "estagio", 3)


def test_passo_cedo_demais_avisa_mas_nao_trava(romance):
    """Amor à primeira vista existe: a ferramenta avisa, quem decide é a cena."""
    saida = tools.mudar_estagio("Lucas", "namoro", "Paixão fulminante")
    assert relacoes.estagio_de(romance["characters"]["lucas"]) == "namoro"
    assert "Aviso" in saida and "baixos para namoro" in saida


def test_estagio_invalido_ou_repetido(romance):
    assert "desconhecido" in tools.mudar_estagio("Lucas", "casamento")
    assert "já está em amizade" in tools.mudar_estagio("Lucas", "amizade")
    assert "não encontrado" in tools.mudar_estagio("Fulano", "flerte")


def test_rompimento_guarda_ate_onde_chegou_e_a_volta_e_reconciliacao(romance):
    tools.mudar_estagio("Lucas", "namoro")
    tools.mudar_estagio("Lucas", "rompimento", "A carta que ele escondeu")
    p = next(x for x in relacoes.lista()["pessoas"] if x["nome"] == "Lucas")
    assert p["estagio"]["atual"] == "rompimento"
    assert p["estagio"]["chegou_a"] == "namoro"
    tools.mudar_estagio("Lucas", "amizade", "Um café, meses depois")
    assert romance["characters"]["lucas"]["momentos"][-1]["titulo"] == "Reconciliação: viraram amigos"


def test_madura_so_para_o_mestre(romance):
    tools.ajustar_relacao("Lucas", afeto=40)
    assert relacoes.madura_para(romance["characters"]["lucas"]) == "flerte"
    assert "madura para flerte" in tools.ver_relacoes()
    # A tela não recebe: seria um placar.
    assert "madura" not in str(relacoes.lista())


def test_compromisso_pede_confianca_tambem(romance):
    lucas = romance["characters"]["lucas"]
    lucas["estagio"] = "namoro"
    tools.ajustar_relacao("Lucas", afeto=90, confianca=10)
    assert relacoes.madura_para(lucas) == ""
    tools.ajustar_relacao("Lucas", confianca=50)
    assert relacoes.madura_para(lucas) == "compromisso"


# ---------------------------------------------------------------------------
# Momentos marcantes
# ---------------------------------------------------------------------------

def test_marcar_momento(romance):
    saida = tools.marcar_momento("Lucas", "O guarda-chuva dividido", "Ele molhou o ombro inteiro")
    assert "O guarda-chuva dividido" in saida and "cap. 3" in saida
    p = next(x for x in relacoes.lista()["pessoas"] if x["nome"] == "Lucas")
    assert p["momentos"][0] == {"titulo": "O guarda-chuva dividido", "descricao": "Ele molhou o ombro inteiro",
                                "tipo": "momento", "capitulo": 3}


def test_momento_repetido_ou_sem_titulo(romance):
    tools.marcar_momento("Lucas", "O guarda-chuva dividido")
    assert "já está registrado" in tools.marcar_momento("Lucas", "o guarda-chuva  dividido")
    assert "título" in tools.marcar_momento("Lucas", "  ")
    assert len(romance["characters"]["lucas"]["momentos"]) == 1


def test_momentos_mais_recentes_primeiro_e_limite(romance):
    for i in range(relacoes.MAX_MOMENTOS + 3):
        tools.marcar_momento("Marina", f"Momento {i}")
    p = next(x for x in relacoes.lista()["pessoas"] if x["nome"] == "Marina")
    assert len(p["momentos"]) == relacoes.MAX_MOMENTOS
    assert p["momentos"][0]["titulo"] == f"Momento {relacoes.MAX_MOMENTOS + 2}"


def test_quem_so_tem_momento_entra_na_lista(romance):
    tools.marcar_momento("Sr. Otávio", "O livro emprestado")
    assert "Sr. Otávio" in [p["nome"] for p in relacoes.lista()["pessoas"]]


# ---------------------------------------------------------------------------
# O mestre lembra
# ---------------------------------------------------------------------------

def test_bloco_de_cena_traz_estagio_e_momentos(romance):
    tools.ajustar_relacao("Lucas", afeto=40)
    tools.marcar_momento("Lucas", "O guarda-chuva dividido", "Ele molhou o ombro inteiro")
    bloco = agent._relacoes_block()
    assert "RELAÇÕES" in bloco
    assert "Lucas (interesse romântico) — amizade" in bloco
    assert "madura para flerte" in bloco
    assert "lembram: O guarda-chuva dividido — Ele molhou o ombro inteiro (cap. 3)" in bloco


def test_instrucao_de_cada_turno_leva_as_relacoes(romance):
    """O bloco precisa entrar na instrução que o ADK recomputa a cada turno."""
    tools.marcar_momento("Lucas", "O guarda-chuva dividido")
    agente = agent.create_agent("gemini-2.5-flash", "romance", False)
    texto = agente.instruction(None)
    assert "RELAÇÕES (estágio" in texto and "lembram: O guarda-chuva dividido" in texto


def test_bloco_de_cena_so_no_romance(romance):
    tools.marcar_momento("Lucas", "O guarda-chuva dividido")
    romance["campaign_type"] = "horror"
    assert agent._relacoes_block() == ""


def test_instrucao_do_romance_ensina_estagio_e_momentos():
    texto = agent.instrucao_da_campanha("romance", False)
    assert "mudar_estagio(nome, estagio, motivo)" in texto
    assert "marcar_momento(nome, titulo, descricao)" in texto
