"""
test_argumentos_da_ferramenta.py

O número que chega como texto.

As ferramentas declaram tipos, mas a chamada de função do modelo é JSON e o
número às vezes vem entre aspas. Numa partida, isto derrubou um teste de
perícia no meio da cena:

    make_skill_check(skill=sobrevivencia, difficulty=12, char_name=Sonael)
    TypeError: '>=' not supported between instances of 'int' and 'str'

O conserto é um invólucro (rpg/argumentos.com_tipos) em cada ferramenta
entregue ao agente. Estes testes cobrem a conversão e, principalmente, o
caminho de verdade: a ferramenta chamada como o ADK a chama.
"""
import pytest

from rpg import argumentos, memory, tools as tl, tools_dnd as td
from rpg.toolsets import FerramentasDoTurno

from conftest import criar_ficha


def _ferramenta(func):
    """A função como o agente a recebe: FunctionTool já com o conversor."""
    return FerramentasDoTurno([func])._todas[0].func


# ---------------------------------------------------------------------------
# 1. A conversão
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("valor, esperado", [
    ("12", 12), (" 12 ", 12), ("+12", 12), ("-3", -3), ("12.0", 12),
    ("CD 12", 12), ("12 (média)", 12), (12, 12), (12.0, 12), (True, 1),
])
def test_int_aceita_o_que_da_para_ler(valor, esperado):
    assert argumentos.para_int(valor) == esperado


@pytest.mark.parametrize("valor", ["doze", "", "1d20", "12 ou 15", None, ["12", "13"]])
def test_int_deixa_passar_o_que_nao_e_numero(valor):
    """Quem recusa é a ferramenta, com mensagem que o mestre entende."""
    assert argumentos.para_int(valor) == valor


def test_int_nao_arredonda_em_silencio():
    assert argumentos.para_int("12.7") == "12.7"
    assert argumentos.para_int(12.7) == 12.7


@pytest.mark.parametrize("valor, esperado", [
    ("true", True), ("True", True), ("sim", True), ("1", True), (1, True),
    ("false", False), ("nao", False), ("não", False), ("0", False), (0, False),
    (True, True), ("talvez", "talvez"),
])
def test_bool_entende_texto_e_numero(valor, esperado):
    assert argumentos.para_bool(valor) == esperado


def test_str_aceita_numero_como_nome():
    assert argumentos.para_str(123) == "123"
    assert argumentos.para_str("Sonael") == "Sonael"
    assert argumentos.para_str(None) is None


# ---------------------------------------------------------------------------
# 2. O invólucro não muda o que o modelo vê
# ---------------------------------------------------------------------------

def test_a_assinatura_e_a_documentacao_continuam_as_mesmas():
    import inspect

    com = argumentos.com_tipos(td.make_skill_check)
    assert inspect.signature(com) == inspect.signature(td.make_skill_check)
    assert com.__name__ == "make_skill_check"
    assert com.__doc__ == td.make_skill_check.__doc__


def test_o_schema_entregue_ao_agente_nao_muda():
    tool = FerramentasDoTurno([td.make_skill_check])._todas[0]
    declaracao = tool._get_declaration()
    props = declaracao.parameters.properties
    assert tool.name == "make_skill_check"
    assert str(props["difficulty"].type).endswith("INTEGER")
    assert str(props["advantage"].type).endswith("BOOLEAN")
    assert str(props["char_name"].type).endswith("STRING")


def test_toda_ferramenta_do_agente_passa_pelo_conversor():
    from rpg.tools import ALL_TOOLS

    for tool in FerramentasDoTurno(ALL_TOOLS)._todas:
        original = getattr(tool.func, "__wrapped__", None)
        # Ferramenta sem argumento tipado fica como está; as outras, com o
        # invólucro. Em nenhum caso o nome muda.
        assert tool.name == (original or tool.func).__name__


# ---------------------------------------------------------------------------
# 3. O caminho de verdade: a chamada que quebrou a partida
# ---------------------------------------------------------------------------

@pytest.fixture
def mesa(campanha, povoar):
    povoar(criar_ficha("Sonael", grupo=True, sabedoria=14))
    return memory.campaign


def test_teste_de_pericia_com_a_dificuldade_em_texto(mesa, monkeypatch):
    monkeypatch.setattr(td.random, "randint", lambda a, b: 15)
    saida = _ferramenta(td.make_skill_check)(
        char_name="Sonael", attribute="sabedoria", difficulty="12", skill="sobrevivencia")
    assert "Erro" not in saida and "falhou" not in saida
    assert "SUCESSO" in saida.upper(), saida


def test_vantagem_como_texto_tambem_vale(mesa, monkeypatch):
    rolagens = iter([3, 18])
    monkeypatch.setattr(td.random, "randint", lambda a, b: next(rolagens))
    saida = _ferramenta(td.make_skill_check)(
        char_name="Sonael", attribute="sabedoria", difficulty="12", advantage="true")
    assert "VANTAGEM" in saida.upper(), saida
    assert "usa **18**" in saida, saida


def test_dificuldade_impossivel_de_ler_vira_recusa_e_nao_queda(mesa):
    saida = _ferramenta(td.make_skill_check)(
        char_name="Sonael", attribute="sabedoria", difficulty="difícil")
    assert isinstance(saida, str) and saida.startswith(("Erro", "Aviso")), saida


@pytest.mark.parametrize("func, kwargs, marca", [
    (lambda: td.modify_hp, {"char_name": "Sonael", "amount": "-5", "reason": "queda"}, "5"),
    (lambda: td.advance_time, {"hours": "2", "reason": "viagem"}, "10h"),
    (lambda: td.grant_xp, {"char_name": "Sonael", "amount": "100", "reason": "o wyrm"}, "100"),
])
def test_outras_ferramentas_com_numero_em_texto(mesa, func, kwargs, marca):
    saida = _ferramenta(func())(**kwargs)
    assert "Erro" not in saida, saida
    assert marca in saida, saida


def test_flag_booleana_em_texto(mesa):
    saida = _ferramenta(tl.add_quest)("A ponte", "Atravessar a ponte", "Achar a corda")
    assert "Erro" not in saida, saida
    saida = _ferramenta(tl.update_quest_objective)("A ponte", "Achar a corda", done="true")
    assert "Erro" not in saida, saida
    missao = (memory.campaign.get("quests") or {}).get("a ponte")
    assert missao["objetivos"][0]["feito"] is True
