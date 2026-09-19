"""
test_segredos.py

Os segredos do romance: os do protagonista e os dos outros.

A tensão do romance mora no que não se diz, e até aqui um segredo era uma
flag ou uma nota do mestre: contar ou ser descoberto não mudava nada entre as
pessoas. Agora muda sozinho a confiança e vira momento — e o segredo de
outra pessoa só chega à tela depois de revelado.
"""
import pytest

from rpg import agent, memory, relacoes, segredos, tools


@pytest.fixture
def romance(campanha):
    campanha["campaign_type"] = "romance"
    campanha["dnd_mode"] = False
    campanha["protagonist"] = "Clara"
    campanha["chapter"] = 4
    campanha["characters"] = {
        "clara": {"name": "Clara", "description": "A protagonista."},
        "lucas": {"name": "Lucas", "description": "O vizinho."},
        "marina": {"name": "Marina", "description": "Amiga de infância."},
        "helena": {"name": "Helena", "description": "A ex de Lucas."},
    }
    campanha["party"] = [{"name": "Lucas", "role": "interesse romântico"},
                         {"name": "Marina", "role": "melhor amiga"}]
    campanha.pop("segredos", None)
    return campanha


def _conf(romance, chave):
    return relacoes.confianca_de(romance["characters"][chave])


# ---------------------------------------------------------------------------
# Guardar
# ---------------------------------------------------------------------------

def test_guardar_um_segredo_seu(romance):
    saida = tools.guardar_segredo("", "A bolsa em Lisboa", "Aceitou a bolsa e vai embora em março",
                                  escondido_de="Lucas", sabem="Marina")
    assert "Segredo seu guardado" in saida and "escondido de Lucas" in saida
    s = segredos.visiveis()["seus"][0]
    assert (s["titulo"], s["escondido_de"], s["sabem"], s["capitulo"]) == \
        ("A bolsa em Lisboa", ["Lucas"], ["Marina"], 4)


def test_o_nome_da_protagonista_tambem_serve_de_dono(romance):
    tools.guardar_segredo("Clara", "A carta nunca enviada")
    assert segredos.visiveis()["seus"][0]["titulo"] == "A carta nunca enviada"


def test_guardar_recusa_o_que_nao_faz_sentido(romance):
    assert "título" in tools.guardar_segredo("", "  ")
    assert "não encontrado" in tools.guardar_segredo("Fulano", "Algo")
    assert "Fulano" in tools.guardar_segredo("", "Algo", escondido_de="Fulano")
    tools.guardar_segredo("", "A bolsa em Lisboa")
    assert "Já existe" in tools.guardar_segredo("", "a bolsa em  Lisboa")
    # O segredo de outra pessoa já é escondido do protagonista.
    assert "por definição" in tools.guardar_segredo("Lucas", "O irmão", escondido_de="Marina")


# ---------------------------------------------------------------------------
# Revelar: o segredo do protagonista
# ---------------------------------------------------------------------------

def test_contar_a_quem_se_escondia_e_honestidade(romance):
    tools.guardar_segredo("", "A bolsa em Lisboa", escondido_de="Lucas")
    saida = tools.revelar_segredo("A bolsa em Lisboa", "Lucas", "contou")
    assert _conf(romance, "lucas") == 10  # honestidade
    assert "Ninguém de quem você escondia" in saida
    s = segredos.visiveis()["seus"][0]
    assert s["escondido_de"] == [] and s["sabem"] == ["Lucas"]
    assert s["historico"][0] == {"acao": "contou", "quem": "Lucas", "capitulo": 4}
    momento = romance["characters"]["lucas"]["momentos"][-1]
    assert (momento["titulo"], momento["tipo"]) == ("Você contou: A bolsa em Lisboa", "segredo")


def test_descobrir_o_que_se_escondia_custa_confianca(romance):
    tools.guardar_segredo("", "A bolsa em Lisboa", escondido_de="Lucas")
    tools.revelar_segredo("A bolsa em Lisboa", "Lucas", "descobriu")
    assert _conf(romance, "lucas") == -25
    assert romance["characters"]["lucas"]["momentos"][-1]["titulo"] == \
        "Descobriu o que você escondia: A bolsa em Lisboa"


def test_contar_a_outro_e_cumplicidade(romance):
    tools.guardar_segredo("", "A bolsa em Lisboa", escondido_de="Lucas")
    tools.revelar_segredo("A bolsa em Lisboa", "Marina", "contou")
    assert _conf(romance, "marina") == 5  # cumplicidade
    # Não era dela que se escondia: não vira momento, e o Lucas segue no escuro.
    assert not romance["characters"]["marina"].get("momentos")
    assert segredos.visiveis()["seus"][0]["escondido_de"] == ["Lucas"]


def test_quem_ja_sabe_nao_fica_sabendo_de_novo(romance):
    tools.guardar_segredo("", "A bolsa em Lisboa", sabem="Marina")
    assert "já sabe" in tools.revelar_segredo("A bolsa em Lisboa", "Marina", "contou")
    assert _conf(romance, "marina") == 0


def test_revelar_valida_o_segredo_e_o_modo(romance):
    assert "não encontrado" in tools.revelar_segredo("Nada", "Lucas")
    tools.guardar_segredo("", "A bolsa em Lisboa")
    assert "como=" in tools.revelar_segredo("A bolsa em Lisboa", "Lucas", "gritou")
    assert "não encontrado" in tools.revelar_segredo("A bolsa em Lisboa", "Fulano")


# ---------------------------------------------------------------------------
# Revelar: o segredo de outra pessoa
# ---------------------------------------------------------------------------

def test_segredo_dos_outros_nao_aparece_antes_de_revelado(romance):
    tools.guardar_segredo("Lucas", "O irmão na prisão", "Visita o irmão todo domingo")
    v = segredos.visiveis()
    assert v["dos_outros"] == []
    assert "O irmão" not in str(relacoes.lista())
    # Mas o mestre sabe, e é avisado para não revelar.
    assert "O irmão na prisão" in tools.ver_segredos()
    assert "NÃO sabe — não revele antes da história" in tools.ver_segredos()


def test_quando_a_pessoa_conta_ela_confia(romance):
    tools.guardar_segredo("Lucas", "O irmão na prisão", "Visita o irmão todo domingo")
    tools.revelar_segredo("O irmão na prisão", como="contou")
    assert _conf(romance, "lucas") == 10
    s = segredos.visiveis()["dos_outros"][0]
    assert (s["dono"], s["como"], s["dono_sabe"], s["capitulo"]) == ("Lucas", "contou", True, 4)
    assert romance["characters"]["lucas"]["momentos"][-1]["titulo"] == "Contou a você: O irmão na prisão"


def test_descobrir_sozinho_e_ele_nao_sabe_que_voce_sabe(romance):
    tools.guardar_segredo("Lucas", "O irmão na prisão")
    saida = tools.revelar_segredo("O irmão na prisão", como="descobriu")
    assert "NÃO sabe que o protagonista sabe" in saida
    assert _conf(romance, "lucas") == 0
    s = segredos.visiveis()["dos_outros"][0]
    assert s["dono_sabe"] is False
    assert "não sabe que ele sabe" in tools.ver_segredos()
    assert "já sabe" in tools.revelar_segredo("O irmão na prisão", como="contou")


# ---------------------------------------------------------------------------
# Na tela e no bloco de cena
# ---------------------------------------------------------------------------

def test_cada_pessoa_mostra_os_segredos_que_a_tocam(romance):
    tools.guardar_segredo("", "A bolsa em Lisboa", escondido_de="Lucas", sabem="Marina")
    tools.guardar_segredo("Lucas", "O irmão na prisão")
    tools.guardar_segredo("Lucas", "O anel guardado")
    tools.revelar_segredo("O irmão na prisão", como="descobriu")
    pessoas = {p["nome"]: p for p in relacoes.lista()["pessoas"]}
    assert pessoas["Lucas"]["segredos"] == {
        "voce_esconde": ["A bolsa em Lisboa"], "sabe_dos_seus": [],
        "voce_sabe_dele": [{"titulo": "O irmão na prisão", "dono_sabe": False}]}
    assert pessoas["Marina"]["segredos"]["sabe_dos_seus"] == ["A bolsa em Lisboa"]


def test_quem_so_aparece_num_segredo_entra_na_lista(romance):
    tools.guardar_segredo("", "O beijo na festa", escondido_de="Helena")
    assert "Helena" in [p["nome"] for p in relacoes.lista()["pessoas"]]


def test_seus_escondidos_vem_primeiro(romance):
    tools.guardar_segredo("", "A carta nunca enviada")
    tools.guardar_segredo("", "Zzz a bolsa", escondido_de="Lucas")
    assert [s["titulo"] for s in segredos.visiveis()["seus"]] == ["Zzz a bolsa", "A carta nunca enviada"]


def test_ficha_do_personagem_traz_os_segredos(romance):
    from rpg import personagens

    tools.guardar_segredo("", "A bolsa em Lisboa", escondido_de="Lucas")
    assert personagens.ficha("Lucas")["relacao"]["segredos"]["voce_esconde"] == ["A bolsa em Lisboa"]


def test_bloco_de_cena_traz_os_segredos_para_o_mestre(romance):
    tools.guardar_segredo("", "A bolsa em Lisboa", "Vai embora em março", escondido_de="Lucas")
    tools.guardar_segredo("Lucas", "O irmão na prisão")
    bloco = relacoes.bloco_de_cena()
    assert "SEGREDOS" in bloco
    assert "Do protagonista — A bolsa em Lisboa: Vai embora em março (escondido de Lucas)" in bloco
    assert "De Lucas — O irmão na prisão (o protagonista NÃO sabe" in bloco


def test_ferramentas_de_segredo_so_no_romance(romance):
    import asyncio
    from rpg import toolsets

    conjunto = toolsets.FerramentasDoTurno(tools.ALL_TOOLS)
    nomes = lambda: {t.name for t in asyncio.run(conjunto.get_tools())}  # noqa: E731
    trio = {"guardar_segredo", "revelar_segredo", "ver_segredos"}
    assert trio <= nomes()
    romance["campaign_type"] = "misterio"
    assert not (trio & nomes())


def test_instrucao_do_romance_ensina_os_segredos():
    texto = agent.instrucao_da_campanha("romance", False)
    assert "guardar_segredo(dono, titulo, descricao, escondido_de, sabem)" in texto
    assert "Nunca\n  revele um segredo antes de a história revelar" in texto
