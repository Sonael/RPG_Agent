"""
test_varredura_de_ferramentas.py

Chama TODAS as ferramentas do mestre, uma a uma e com a campanha refeita
antes de cada chamada, nos estados em que uma campanha nova costuma estar, e
exige que nenhuma levante exceção.

Recusar ("Erro: ...", "Personagem não encontrado") é resposta; levantar
exceção é bug. Foi assim que "'NoneType' object has no attribute 'get'"
apareceu numa campanha nova: recruit_character e add_item num NPC salvo só
com save_character, que fica com "sheet": None. Os argumentos são genéricos
de propósito (o nome do personagem do cenário, 1 para números, "teste" para
texto): o que se procura é o tropeço na forma do dado, não a regra.

A campanha é refeita antes de CADA ferramenta porque uma ferramenta muda o
estado da seguinte: roll_initiative dá ficha padrão a quem não tem, e
escondia a quebra do recruit_character que viesse depois.
"""
import inspect
import traceback

import pytest

from rpg import memory, tools as tl, tools_dnd as td

from conftest import criar_ficha

# Parâmetros que recebem o nome do personagem do cenário.
_PARAMETROS_DE_NOME = {
    "name", "char_name", "npc_name", "character", "char", "target", "target_name",
    "attacker", "attacker_name", "defender", "caster", "healer", "buyer", "seller",
    "character_name", "names", "characters_names", "who", "receiver", "giver",
}

# cenário → (personagem que recebe as chamadas, prepara a campanha)
CENARIOS = {
    "npc salvo sem ficha": "Helena",
    "membro do grupo sem ficha": "Borin",
    "personagem que não existe": "Ninguém",
    "herói com ficha": "Thorn",
    "npc sem ficha em combate": "Helena",
    "ficha com campos null": "Thorn",
    "ficha com campos null em combate": "Thorn",
}


def _argumento(nome, parametro, alvo):
    if parametro.default is not inspect.Parameter.empty and nome not in _PARAMETROS_DE_NOME:
        return parametro.default
    if nome in _PARAMETROS_DE_NOME or "name" in nome or nome in ("npc", "actor"):
        return alvo
    if parametro.annotation in (int, "int") or nome in (
            "amount", "quantity", "count", "dc", "hours", "level", "nivel", "points"):
        return 1
    if parametro.annotation in (bool, "bool"):
        return False
    return "teste"


def _ferramentas():
    return {f.__name__: f for f in list(tl.ALL_TOOLS) + list(td.DND_TOOLS)}


def _preparar(cenario):
    memory.campaign["characters"] = {}
    memory.campaign["party"] = []
    memory.campaign["name"] = "Varredura"
    memory.campaign["characters"]["thorn"] = criar_ficha("Thorn", grupo=True)
    memory.campaign["party"].append({"name": "Thorn", "role": "", "notes": ""})
    tl.save_character("Helena", "Sacerdotisa do templo.")
    tl.add_party_member("Borin", "anão")

    cs = memory.campaign["combat_state"]
    cs.update({"is_active": False, "initiative_order": [], "current_turn_index": 0, "round": 1})
    cs.pop("zonas", None)
    cs.pop("posicoes", None)

    if "null" in cenario:
        th = memory.campaign["characters"]["thorn"]
        th["inventario"] = None
        th["habilidades"] = None
        for campo in ("equipamentos", "condicoes", "recargas", "efeitos", "feature_choices"):
            th["sheet"][campo] = None
        # É o que a carga da campanha e os editores fazem com um JSON assim.
        memory._migrate_sheet_fields(th)

    if "combate" in cenario:
        cs.update({"is_active": True, "initiative_order": ["Thorn", "Helena"],
                   "zonas": ["Trilha", "Encosta"],
                   "posicoes": {"thorn": "Trilha", "helena": "Encosta"}})


@pytest.mark.parametrize("cenario", list(CENARIOS))
def test_nenhuma_ferramenta_levanta_excecao(campanha, cenario):
    alvo = CENARIOS[cenario]
    quebras = []
    for nome, ferramenta in sorted(_ferramentas().items()):
        _preparar(cenario)
        kwargs = {}
        for pn, p in inspect.signature(ferramenta).parameters.items():
            if p.kind in (p.VAR_KEYWORD, p.VAR_POSITIONAL):
                continue
            kwargs[pn] = _argumento(pn, p, alvo)
        try:
            ferramenta(**kwargs)
        except Exception as e:
            onde = traceback.extract_tb(e.__traceback__)[-1]
            quebras.append(f"{nome}: {type(e).__name__}: {e} "
                           f"({onde.filename.rsplit('/', 1)[-1]}:{onde.lineno})")
    assert not quebras, "\n".join(quebras)
