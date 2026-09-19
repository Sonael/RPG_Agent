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
    assert "Lucas (interesse romântico): afeto +30 (afeição), confiança -20 (com um pé atrás)" in texto


def test_ferramentas_de_relacao_so_no_romance(romance):
    conjunto = toolsets.FerramentasDoTurno(tools.ALL_TOOLS)

    def nomes():
        return {t.name for t in asyncio.run(conjunto.get_tools())}

    assert {"ajustar_relacao", "ver_relacoes"} <= nomes()
    romance["campaign_type"] = "horror"
    assert not ({"ajustar_relacao", "ver_relacoes"} & nomes())


def test_instrucao_do_romance_manda_usar_a_ferramenta():
    texto = agent.instrucao_da_campanha("romance", False)
    assert "ajustar_relacao(nome, afeto, confianca" in texto
    assert "confianca_lucas=alta" not in texto
