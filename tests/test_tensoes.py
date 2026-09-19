"""
test_tensoes.py

Ciúme e triângulos do romance: a tensão entre duas OUTRAS pessoas.

Toda relação era entre o protagonista e alguém; o que acontecia entre os
outros (a ex que não suporta o novo namoro, dois pretendentes que se medem)
não existia. Agora tem tipo, intensidade e o porquê, pode estar escondida do
jogador como um segredo, e o triângulo é detectado pelo estágio das relações.
"""
import pytest

from rpg import agent, memory, relacoes, tensoes, tools


@pytest.fixture
def romance(campanha):
    campanha["campaign_type"] = "romance"
    campanha["dnd_mode"] = False
    campanha["protagonist"] = "Clara"
    campanha["chapter"] = 5
    campanha["characters"] = {
        "clara": {"name": "Clara", "description": "A protagonista."},
        "lucas": {"name": "Lucas", "description": "O vizinho.", "estagio": "flerte"},
        "rafael": {"name": "Rafael", "description": "O colega de faculdade."},
        "helena": {"name": "Helena", "description": "A ex de Lucas."},
        "marina": {"name": "Marina", "description": "Amiga de infância."},
    }
    campanha["party"] = [{"name": "Lucas", "role": "interesse romântico"},
                         {"name": "Marina", "role": "melhor amiga"}]
    campanha.pop("tensoes", None)
    return campanha


def test_criar_uma_tensao(romance):
    saida = tools.ajustar_tensao("Helena", "Lucas", 30, "Viu os dois no café", tipo="ciúme")
    assert "Helena × Lucas (ciúme): 0 → **30** (incômodo)" in saida
    assert "Mudou de faixa" not in saida  # criar não é mudar de faixa
    t = tensoes.percebidas()[0]
    assert (t["a"], t["b"], t["tipo"], t["intensidade"], t["faixa"]) == ("Helena", "Lucas", "ciúme", 30, "incômodo")
    assert t["historico"][0] == {"delta": 30, "motivo": "Viu os dois no café", "capitulo": 5}


def test_a_ordem_do_par_nao_importa(romance):
    tools.ajustar_tensao("Helena", "Lucas", 30, tipo="ciúme")
    saida = tools.ajustar_tensao("Lucas", "Helena", 25, "Discutiram na festa")
    assert "30 → **55** (tensão aberta)" in saida and "Mudou de faixa: incômodo → **tensão aberta**" in saida
    assert len(romance["tensoes"]) == 1


def test_limites_e_resolucao(romance):
    tools.ajustar_tensao("Helena", "Lucas", 90, tipo="rivalidade")
    tools.ajustar_tensao("Helena", "Lucas", 40)
    assert tensoes.percebidas()[0]["intensidade"] == 100
    assert tensoes.percebidas()[0]["faixa"] == "à beira da ruptura"
    tools.ajustar_tensao("Helena", "Lucas", -150, "Fizeram as pazes")
    # Resolvida: sai da lista.
    assert tensoes.percebidas() == []


def test_validacoes(romance):
    assert "não encontrados: Fulano" in tools.ajustar_tensao("Fulano", "Lucas", 10)
    assert "OUTRAS pessoas" in tools.ajustar_tensao("Clara", "Lucas", 10)
    assert "diferentes" in tools.ajustar_tensao("Lucas", "lucas", 10)
    assert "número inteiro" in tools.ajustar_tensao("Helena", "Lucas", "muito")
    assert "Tipo desconhecido" in tools.ajustar_tensao("Helena", "Lucas", 10, tipo="inveja")
    assert "ainda não existe" in tools.ajustar_tensao("Helena", "Lucas", 0)


def test_ciume_escondido_nao_aparece_para_o_jogador(romance):
    saida = tools.ajustar_tensao("Helena", "Lucas", 40, "Guarda as fotos dos dois", tipo="ciúme", percebida=False)
    assert "NÃO percebeu" in saida
    assert tensoes.percebidas() == []
    assert "Helena" not in [p["nome"] for p in relacoes.lista()["pessoas"]]
    # O mestre sabe.
    assert "Helena × Lucas: ciúme 40 (incômodo)" in tensoes.resumo_para_o_mestre()
    assert "o protagonista NÃO percebeu" in tensoes.resumo_para_o_mestre()
    # Quando a história mostrar:
    tools.ajustar_tensao("Helena", "Lucas", 10, "A cena no corredor", percebida=True)
    assert tensoes.percebidas()[0]["intensidade"] == 50


def test_cada_pessoa_mostra_as_tensoes_com_a_outra_ponta(romance):
    tools.ajustar_tensao("Helena", "Lucas", 30, tipo="ciúme")
    pessoas = {p["nome"]: p for p in relacoes.lista()["pessoas"]}
    assert pessoas["Lucas"]["tensoes"][0]["com"] == "Helena"
    # Quem só aparece numa tensão percebida entra na lista.
    assert pessoas["Helena"]["tensoes"][0]["com"] == "Lucas"


def test_da_mais_forte_para_a_mais_fraca(romance):
    tools.ajustar_tensao("Marina", "Lucas", 15, tipo="desconfiança")
    tools.ajustar_tensao("Helena", "Lucas", 60, tipo="ciúme")
    assert [t["a"] for t in tensoes.percebidas()] == ["Helena", "Marina"]


def test_triangulo_e_detectado_pelo_estagio(romance):
    assert tensoes.triangulos() == []
    romance["characters"]["rafael"]["estagio"] = "flerte"
    tri = tensoes.triangulos()
    assert len(tri) == 1 and {tri[0]["a"], tri[0]["b"]} == {"Lucas", "Rafael"}
    assert tri[0]["tensao"] is None
    tools.ajustar_tensao("Rafael", "Lucas", 25, tipo="rivalidade")
    assert tensoes.triangulos()[0]["tensao"]["tipo"] == "rivalidade"


def test_amizade_ou_rompimento_nao_fazem_triangulo(romance):
    romance["characters"]["rafael"]["estagio"] = "rompimento"
    romance["characters"]["marina"]["estagio"] = "amizade"
    assert tensoes.triangulos() == []


def test_bloco_de_cena_traz_tensoes_e_triangulos(romance):
    romance["characters"]["rafael"]["estagio"] = "namoro"
    tools.ajustar_tensao("Helena", "Lucas", 40, "Guarda as fotos", tipo="ciúme", percebida=False)
    bloco = relacoes.bloco_de_cena()
    assert "TENSÕES ENTRE OS OUTROS" in bloco
    assert "Helena × Lucas: ciúme 40 (incômodo); último: Guarda as fotos — o protagonista NÃO percebeu" in bloco
    assert "TRIÂNGULO: o protagonista está em flerte com Lucas e em namoro com Rafael" in bloco


def test_lista_de_relacoes_traz_tensoes_e_triangulos(romance):
    romance["characters"]["rafael"]["estagio"] = "flerte"
    tools.ajustar_tensao("Rafael", "Lucas", 25, tipo="rivalidade")
    dados = relacoes.lista()
    assert dados["tensoes"][0]["tipo"] == "rivalidade"
    assert len(dados["triangulos"]) == 1


def test_ferramenta_so_no_romance(romance):
    import asyncio
    from rpg import toolsets

    conjunto = toolsets.FerramentasDoTurno(tools.ALL_TOOLS)
    nomes = lambda: {t.name for t in asyncio.run(conjunto.get_tools())}  # noqa: E731
    assert "ajustar_tensao" in nomes()
    romance["campaign_type"] = "scifi"
    assert "ajustar_tensao" not in nomes()


def test_instrucao_do_romance_ensina_ciume_e_triangulos():
    texto = agent.instrucao_da_campanha("romance", False)
    assert "ajustar_tensao(pessoa_a, pessoa_b, delta, motivo, tipo)" in texto
    assert "percebida=False" in texto and "TRIÂNGULO" in texto
