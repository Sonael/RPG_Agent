"""
test_encontros.py

Os encontros marcados do romance, pelo relógio do mundo.

"Jantar na sexta às 20h" era uma frase da narração que ninguém lembrava: o
mestre não sabia que a hora tinha chegado, e o jogador não tinha onde ver o
que havia marcado. Agora o encontro tem dia e hora no relógio, aparece na
barra e no bloco de cena, e faltar tem consequência.
"""
import pytest

from rpg import agent, encontros, memory, relacoes, tools


@pytest.fixture
def romance(campanha):
    campanha["campaign_type"] = "romance"
    campanha["dnd_mode"] = False
    campanha["protagonist"] = "Clara"
    campanha["chapter"] = 2
    campanha["relogio"] = {"dia": 3, "hora": 14}
    campanha["characters"] = {
        "clara": {"name": "Clara", "description": "A protagonista."},
        "lucas": {"name": "Lucas", "description": "O vizinho."},
        "marina": {"name": "Marina", "description": "Amiga de infância."},
    }
    campanha["party"] = [{"name": "Lucas", "role": "interesse romântico"}]
    campanha.pop("encontros", None)
    return campanha


def _avancar(romance, horas):
    from rpg import tools_dnd
    tools_dnd.advance_time(horas)


def test_marcar_um_encontro(romance):
    saida = tools.marcar_encontro("Lucas", 3, 20, "Café Aurora", "jantar")
    assert "Encontro marcado com Lucas: jantar — Dia 3, 20h, Café Aurora (em 6h)" in saida
    e = encontros.proximo()
    assert (e["com"], e["o_que"], e["quando"], e["onde"], e["horas"], e["falta"]) == \
        ("Lucas", "jantar", "Dia 3, 20h", "Café Aurora", 6, "em 6h")
    assert e["em_breve"] is True and e["atrasado"] is False


def test_marcar_valida(romance):
    assert "não encontrado" in tools.marcar_encontro("Fulano", 4, 20)
    assert "não encontrado" in tools.marcar_encontro("Clara", 4, 20)
    assert "números" in tools.marcar_encontro("Lucas", "sexta", 20)
    assert "0 a 23" in tools.marcar_encontro("Lucas", 4, 25)
    assert "já passou" in tools.marcar_encontro("Lucas", 3, 10)


def test_o_mais_cedo_primeiro_e_quanto_falta(romance):
    tools.marcar_encontro("Marina", 5, 9, o_que="café")
    tools.marcar_encontro("Lucas", 4, 20, o_que="cinema")
    lista = encontros.marcados()
    assert [e["com"] for e in lista] == ["Lucas", "Marina"]
    assert lista[0]["falta"] == "em 1d 6h" and lista[0]["em_breve"] is False


def test_passar_da_hora_vira_atrasado_e_o_mestre_e_cobrado(romance):
    tools.marcar_encontro("Lucas", 3, 20, "Café Aurora", "jantar")
    _avancar(romance, 8)
    e = encontros.proximo()
    assert e["atrasado"] is True and e["falta"] == "passou há 2h"
    bloco = relacoes.bloco_de_cena()
    assert "ENCONTROS MARCADOS" in bloco
    assert "Lucas: jantar — Dia 3, 20h, Café Aurora (passou há 2h) — PASSOU DA HORA" in bloco


def test_aconteceu_vira_momento(romance):
    tools.marcar_encontro("Lucas", 3, 20, "Café Aurora", "jantar")
    tools.resolver_encontro("Lucas", "aconteceu", "Ele pediu o mesmo prato que você")
    assert encontros.marcados() == []
    m = romance["characters"]["lucas"]["momentos"][-1]
    assert (m["titulo"], m["descricao"], m["tipo"]) == ("Encontro: jantar", "Ele pediu o mesmo prato que você", "encontro")
    assert relacoes.confianca_de(romance["characters"]["lucas"]) == 0


def test_faltar_custa_confianca_e_afeto(romance):
    tools.marcar_encontro("Lucas", 3, 20, "Café Aurora", "jantar")
    tools.resolver_encontro("Lucas", "faltou", "Ficou presa no trabalho e não avisou")
    lucas = romance["characters"]["lucas"]
    assert relacoes.confianca_de(lucas) == -15
    assert relacoes.afeto_de(lucas) == -5
    assert lucas["momentos"][-1]["titulo"] == "Você faltou: jantar"


def test_cancelar_nao_tem_efeito(romance):
    tools.marcar_encontro("Lucas", 3, 20, o_que="jantar")
    tools.resolver_encontro("Lucas", "cancelado", "Avisou de manhã")
    lucas = romance["characters"]["lucas"]
    assert relacoes.confianca_de(lucas) == 0 and not lucas.get("momentos")
    assert encontros.marcados() == []


def test_resolver_fecha_o_mais_cedo_e_valida(romance):
    tools.marcar_encontro("Lucas", 5, 20, o_que="cinema")
    tools.marcar_encontro("Lucas", 3, 20, o_que="jantar")
    tools.resolver_encontro("Lucas", "aconteceu")
    assert [e["o_que"] for e in encontros.marcados()] == ["cinema"]
    assert "Estado desconhecido" in tools.resolver_encontro("Lucas", "adiado")
    assert "Nenhum encontro" in tools.resolver_encontro("Marina", "aconteceu")


def test_encontro_aparece_na_pessoa_e_a_poe_na_lista(romance):
    tools.marcar_encontro("Marina", 4, 10, o_que="café")
    pessoas = {p["nome"]: p for p in relacoes.lista()["pessoas"]}
    assert "Marina" in pessoas
    assert pessoas["Marina"]["encontros"][0]["o_que"] == "café"


def test_a_barra_recebe_o_proximo_so_no_romance(romance):
    import server

    tools.marcar_encontro("Lucas", 3, 20, o_que="jantar")
    assert server._encontro_da_barra(romance)["com"] == "Lucas"
    romance["campaign_type"] = "horror"
    assert server._encontro_da_barra(romance) is None


def test_ferramentas_de_encontro_so_no_romance(romance):
    import asyncio
    from rpg import toolsets

    conjunto = toolsets.FerramentasDoTurno(tools.ALL_TOOLS)
    nomes = lambda: {t.name for t in asyncio.run(conjunto.get_tools())}  # noqa: E731
    assert {"marcar_encontro", "resolver_encontro"} <= nomes()
    romance["campaign_type"] = "faroeste"
    assert not ({"marcar_encontro", "resolver_encontro"} & nomes())


def test_instrucao_do_romance_ensina_gestos_e_encontros():
    texto = agent.instrucao_da_campanha("romance", False)
    assert "marcar_encontro(com, dia, hora, onde,\n  o_que)" in texto
    assert "Nem todo convite é aceito" in texto



def test_importar_mantem_o_numero_e_o_que_foi_resolvido():
    """
    O editor manda de volta os encontros que carregou: o número de cada um
    fica (antes todos eram renumerados, e apagar um mudava os seguintes), e o
    motivo e o capítulo de um encontro resolvido também.
    """
    from rpg import encontros
    saida = encontros.importar([
        {"id": 2, "com": "Lucas", "dia": 3, "hora": 20, "estado": "aconteceu", "motivo": "  beijo  ", "cap_resolvido": 4},
        {"id": 5, "com": "Helena", "dia": 4, "hora": 18},
        {"id": 5, "com": "Rafa", "dia": 5, "hora": 19},                  # repetido: ganha outro
        {"com": "Bia", "dia": 6, "hora": 9},                              # sem número
        {"id": True, "com": "Caio", "dia": 7, "hora": 9},                 # booleano não é número
        {"id": 9, "com": "Duda", "dia": 8, "hora": 9, "motivo": "x"},     # marcado: sem motivo
    ])
    assert [(e["com"], e["id"]) for e in saida] == [("Lucas", 2), ("Helena", 5), ("Rafa", 10), ("Bia", 11),
                                                    ("Caio", 12), ("Duda", 9)]
    assert (saida[0]["motivo"], saida[0]["cap_resolvido"]) == ("beijo", 4)
    assert "motivo" not in saida[-1]
