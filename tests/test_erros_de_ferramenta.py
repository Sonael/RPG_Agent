"""
test_erros_de_ferramenta.py

Falha numa chamada de ferramenta do mestre não derruba mais o turno.

Numa campanha nova apareceram dois "O RPG AGENT silenciou":
• "'NoneType' object has no attribute 'get'": recruit_character e add_item
  num NPC salvo só com save_character, que fica com "sheet": None;
• "Tool 'modify_amount' not found": nome inventado pela LLM.

Em ambos o ADK desistia do turno inteiro. Agora a falha volta ao mestre como
"Erro: ...", e o turno segue.
"""
import asyncio

import pytest

from rpg import erros_de_ferramenta as ef, memory, tools as tl, tools_dnd as td

from conftest import criar_ficha


class _Ferramenta:
    def __init__(self, nome):
        self.name = nome


def _erro_do_adk(nome):
    return ValueError(f"Tool '{nome}' not found.\nAvailable tools: add_item, modify_hp")


# ---------------------------------------------------------------------------
# A causa do NoneType: NPC sem ficha
# ---------------------------------------------------------------------------

def test_recrutar_npc_salvo_sem_ficha(campanha, povoar):
    povoar(criar_ficha("Thorn", grupo=True, nivel=1))
    tl.save_character("Helena", "Sacerdotisa do templo.")
    assert memory.campaign["characters"]["helena"]["sheet"] is None

    resposta = td.recruit_character("Helena")
    assert "Helena agora é membro do grupo" in resposta
    assert "ficha genérica" in resposta


def test_dar_item_a_npc_salvo_sem_ficha(campanha, povoar):
    tl.save_character("Helena", "Sacerdotisa do templo.")
    resposta = td.add_item("Helena", "Símbolo Sagrado")
    assert "adicionado ao inventário de Helena" in resposta


def test_campos_gravados_como_null_viram_o_padrao(campanha, povoar):
    ch = criar_ficha("Thorn", grupo=True)
    ch["inventario"] = None
    ch["habilidades"] = None
    for campo in ("equipamentos", "condicoes", "recargas", "efeitos", "feature_choices"):
        ch["sheet"][campo] = None
    povoar(ch)

    memory._migrate_sheet_fields(ch)

    assert ch["inventario"] == [] and ch["habilidades"] == []
    assert ch["sheet"]["condicoes"] == [] and isinstance(ch["sheet"]["equipamentos"], dict)
    assert "recargas" not in ch["sheet"]
    assert ch["sheet"]["concentracao"] is None, "None é o valor normal da concentração"
    # As ferramentas que quebravam com esses nulls agora respondem.
    assert "Thorn" in td.get_character_sheet("Thorn")
    assert "adicionado" in td.add_item("Thorn", "Corda")
    assert "Poder de Teste" in td.set_recharge_ability("Thorn", "Poder de Teste", 5)


def test_editor_que_grava_null_tambem_e_normalizado(campanha):
    novo = criar_ficha("Lyra", grupo=True)
    novo["inventario"] = None
    novo["sheet"]["condicoes"] = None
    td.normalize_edited_character(novo, None)
    assert novo["inventario"] == [] and novo["sheet"]["condicoes"] == []


# ---------------------------------------------------------------------------
# O callback
# ---------------------------------------------------------------------------

def test_ferramenta_inventada_sugere_as_parecidas(campanha):
    memory.campaign["dnd_mode"] = True
    r = ef.ao_falhar_ferramenta(_Ferramenta("modify_amount"), {"amount": 5}, None,
                                _erro_do_adk("modify_amount"))
    texto = r["result"]
    assert texto.startswith("Erro: a ferramenta modify_amount não existe.")
    for nome in ("modify_currency", "modify_hp", "modify_mana"):
        assert nome in texto


def test_ferramenta_do_modo_narrado_no_combate_da_tela(campanha):
    memory.campaign["dnd_mode"] = True
    memory.campaign["combat_mode"] = "tela"
    texto = ef.ao_falhar_ferramenta(_Ferramenta("attack_roll"), {}, None,
                                    _erro_do_adk("attack_roll"))["result"]
    assert "tela tática" in texto and texto.startswith("Erro:")


def test_ferramenta_de_dnd_numa_campanha_sem_regras(campanha):
    memory.campaign["dnd_mode"] = False
    memory.campaign["campaign_type"] = "romance"
    texto = ef.ao_falhar_ferramenta(_Ferramenta("roll_initiative"), {}, None,
                                    _erro_do_adk("roll_initiative"))["result"]
    assert "não usa as regras de D&D" in texto


def test_excecao_dentro_da_ferramenta_vira_erro_e_vai_para_o_log(campanha, capsys):
    try:
        {}["nivel"]
    except KeyError as e:
        erro = e
    r = ef.ao_falhar_ferramenta(_Ferramenta("get_character_sheet"), {"name": "Ogro"}, None, erro)
    assert r["result"].startswith("Erro: get_character_sheet falhou por um problema interno (KeyError")
    assert "Não repita a mesma chamada" in r["result"]
    log = capsys.readouterr().out
    assert "[FERRAMENTA] get_character_sheet(name=Ogro) falhou" in log
    assert "Traceback" in log


def test_agente_criado_com_o_callback():
    from rpg.agent import create_agent
    agente = create_agent("gemini-2.5-flash", "dnd")
    assert agente.on_tool_error_callback is ef.ao_falhar_ferramenta


# ---------------------------------------------------------------------------
# De ponta a ponta, pelo ADK: o turno termina
# ---------------------------------------------------------------------------

def test_turno_segue_depois_de_ferramenta_inventada_e_de_excecao(campanha):
    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_response import LlmResponse
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    from rpg.agent import create_agent

    memory.campaign["name"] = "Teste"
    memory.campaign["dnd_mode"] = True
    memory.campaign["campaign_type"] = "dnd"
    # Ficha quebrada que a migração não conserta: get_character_sheet levanta.
    memory.campaign["characters"]["ogro"] = {"name": "Ogro", "status": "inimigo",
                                             "sheet": {"classe": "npc"}, "inventario": [],
                                             "habilidades": []}

    roteiro = [
        types.Part(function_call=types.FunctionCall(name="modify_amount", args={"amount": 5})),
        types.Part(function_call=types.FunctionCall(name="get_character_sheet", args={"name": "Ogro"})),
        types.Part(text="O mestre segue a cena."),
    ]
    recebidas = []

    class MestreDeMentira(BaseLlm):
        model: str = "mentira"

        async def generate_content_async(self, llm_request, stream=False):
            for c in llm_request.contents or []:
                for p in c.parts or []:
                    if p.function_response:
                        recebidas.append((p.function_response.name,
                                          dict(p.function_response.response or {})))
            passo = min(len(recebidas), len(roteiro) - 1)
            yield LlmResponse(content=types.Content(role="model", parts=[roteiro[passo]]))

    agente = create_agent(MestreDeMentira(), "dnd")
    sessoes = InMemorySessionService()

    async def rodar():
        await sessoes.create_session(app_name="t", user_id="u", session_id="s")
        runner = Runner(agent=agente, app_name="t", session_service=sessoes)
        final = ""
        async for ev in runner.run_async(user_id="u", session_id="s",
                                         new_message=types.Content(role="user",
                                                                   parts=[types.Part(text="oi")])):
            if ev.is_final_response() and ev.content and ev.content.parts:
                final += "".join(p.text or "" for p in ev.content.parts)
        return final

    final = asyncio.run(rodar())
    assert final == "O mestre segue a cena."
    nomes = [n for n, _ in recebidas]
    assert "modify_amount" in nomes and "get_character_sheet" in nomes
    respostas = {n: r.get("result", "") for n, r in recebidas}
    assert respostas["modify_amount"].startswith("Erro: a ferramenta modify_amount não existe.")
    assert respostas["get_character_sheet"].startswith("Erro: get_character_sheet falhou")
