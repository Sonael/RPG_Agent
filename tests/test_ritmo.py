"""
test_ritmo.py

Numa partida longa o Gemini respondia "limite de tokens por minuto" (326 mil
de 250 mil) no meio do turno. Cada chamada leva uns 35 mil tokens fixos, a
sessão do ADK reenviava a partida inteira (toda chamada e resposta de
ferramenta) a cada chamada, e o retry esperava 2, 4, 8 e 16 segundos, menos
que o minuto da janela. Ver rpg/ritmo.py.
"""
import asyncio

import pytest
from google.genai import types

from rpg import memory, ritmo


@pytest.fixture(autouse=True)
def limpo():
    ritmo.esquecer()
    yield
    ritmo.esquecer()


def _fala(t):
    return types.Content(role="user", parts=[types.Part(text=t)])


def _chamada(nome):
    return types.Content(role="model", parts=[types.Part(
        function_call=types.FunctionCall(name=nome, args={"x": 1}))])


def _volta(nome, texto="resultado grande " * 50):
    return types.Content(role="user", parts=[types.Part(
        function_response=types.FunctionResponse(name=nome, response={"result": texto}))])


def _narra(t):
    return types.Content(role="model", parts=[types.Part(text=t)])


def _turno(n):
    return [_fala(f"fala {n}"), _chamada("get_scene_context"), _volta("get_scene_context"),
            _chamada("apply_condition"), _volta("apply_condition"), _narra(f"narração {n}")]


# ---------------------------------------------------------------------------
# O histórico que vai ao modelo
# ---------------------------------------------------------------------------

def test_turnos_anteriores_vao_so_com_o_texto_e_o_atual_inteiro():
    atual = [_fala("fala 3"), _chamada("apply_condition"), _volta("apply_condition")]
    saida = ritmo.enxugar_historico(_turno(1) + _turno(2) + atual)
    textos = [p.text for c in saida for p in c.parts if p.text]
    assert textos[:4] == ["fala 1", "narração 1", "fala 2", "narração 2"]
    # Dos anteriores, nenhuma ferramenta; do atual, tudo.
    antigos, agora = saida[:4], saida[4:]
    assert not any(p.function_call or p.function_response for c in antigos for p in c.parts)
    assert [c.parts[0].function_call.name if c.parts[0].function_call else None
            for c in agora[1:2]] == ["apply_condition"]
    assert agora[2].parts[0].function_response.name == "apply_condition"
    # Os papéis alternam.
    assert all(a.role != b.role for a, b in zip(saida, saida[1:]))


def test_so_os_ultimos_turnos_ficam():
    contents = []
    for n in range(1, 16):
        contents += _turno(n)
    contents += [_fala("agora")]
    saida = ritmo.enxugar_historico(contents, turnos=10)
    textos = [p.text for c in saida for p in c.parts if p.text]
    assert "fala 5" not in textos and "fala 6" in textos and textos[-1] == "agora"


def test_fala_sem_resposta_junta_com_a_de_agora():
    """O turno que caiu deixa uma fala sem narração: duas falas seguidas viram uma."""
    saida = ritmo.enxugar_historico(_turno(1) + [_fala("a que caiu"), _fala("de novo")])
    assert saida[-1].role == "user"
    assert [p.text for p in saida[-1].parts] == ["a que caiu", "de novo"]
    assert all(a.role != b.role for a, b in zip(saida, saida[1:]))


def test_texto_antigo_enorme_vira_trecho():
    longo = "x" * (ritmo.TEXTO_ANTIGO_MAX + 500)
    saida = ritmo.enxugar_historico([_fala("f"), _narra(longo), _fala("agora")])
    assert saida[1].parts[0].text.endswith("[...]")
    assert len(saida[1].parts[0].text) < len(longo)


def test_primeiro_turno_passa_igual():
    contents = [_fala("oi"), _chamada("get_scene_context"), _volta("get_scene_context")]
    assert ritmo.enxugar_historico(contents) == contents


# ---------------------------------------------------------------------------
# A janela de um minuto
# ---------------------------------------------------------------------------

def test_cabe_nao_espera_e_estourar_espera_o_mais_antigo_sair():
    ritmo.registrar("k", 100_000, agora=0)
    ritmo.registrar("k", 100_000, agora=20)
    assert ritmo.espera_necessaria("k", 20_000, 250_000, agora=30) == 0
    # 200 mil + 50 mil passa de 90% de 250 mil: espera o de t=0 sair (t=60).
    espera = ritmo.espera_necessaria("k", 50_000, 250_000, agora=30)
    assert 30 <= espera <= 31
    # Passado o minuto, o antigo saiu.
    assert ritmo.usados("k", agora=61) == 100_000


def test_chave_diferente_tem_janela_propria():
    ritmo.registrar("a", 240_000, agora=0)
    assert ritmo.espera_necessaria("b", 50_000, 250_000, agora=1) == 0


def test_chamada_maior_que_o_limite_espera_a_janela_esvaziar():
    ritmo.registrar("k", 10_000, agora=0)
    espera = ritmo.espera_necessaria("k", 300_000, 250_000, agora=10)
    assert 50 <= espera <= 51


def test_limite_padrao():
    assert ritmo.limite_padrao("gemini-2.5-flash") == 250_000
    assert ritmo.limite_padrao("gemini-2.5-pro") == 125_000
    assert ritmo.limite_padrao("ollama:llama3") is None
    assert ritmo.limite_padrao("deepseek:deepseek-chat") is None


# ---------------------------------------------------------------------------
# O erro 429
# ---------------------------------------------------------------------------

ERRO_POR_MINUTO = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your "
    "current quota. * Quota exceeded for metric: generativelanguage.googleapis.com/"
    "generate_content_free_tier_input_token_count, limit: 250000, model: gemini-2.5-flash\\n"
    "Please retry in 23.4s.', 'status': 'RESOURCE_EXHAUSTED', 'details': [{'@type': "
    "'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaId': "
    "'GenerateContentInputTokensPerModelPerMinute-FreeTier'}]}, {'@type': "
    "'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '23s'}]}}")

ERRO_DIARIO = (
    "429 RESOURCE_EXHAUSTED. {'error': {'message': 'Quota exceeded for metric: "
    "generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 250', "
    "'details': [{'violations': [{'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}]}]}}")


def test_le_o_tempo_e_o_limite_do_erro():
    assert ritmo.espera_do_erro(ERRO_POR_MINUTO) == 23.0
    assert ritmo.e_limite_por_minuto(ERRO_POR_MINUTO)
    assert ritmo.aprender_do_erro("k", ERRO_POR_MINUTO) == 250_000
    assert ritmo.limite("k", "gemini-2.5-pro") == 250_000     # o aprendido vence o padrão


def test_espera_o_que_o_gemini_pede_nao_dois_segundos():
    espera = ritmo.espera_para_tentar_de_novo(ERRO_POR_MINUTO, 0, "k", "gemini-2.5-flash")
    assert espera == 24.0


def test_cota_diaria_nao_repete():
    assert ritmo.e_limite_diario(ERRO_DIARIO)
    assert ritmo.espera_para_tentar_de_novo(ERRO_DIARIO, 0, "k") is None


def test_limite_por_minuto_sem_tempo_no_erro_espera_a_janela():
    ritmo.registrar("k", 240_000, agora=None)
    espera = ritmo.espera_para_tentar_de_novo(
        "429 quota exceeded input_token_count, limit: 250000", 0, "k", "gemini-2.5-flash")
    assert espera >= 20


def test_sobrecarga_comum_continua_rapida():
    assert ritmo.espera_para_tentar_de_novo("503 model is overloaded", 0) == 2.0
    assert ritmo.espera_para_tentar_de_novo("503 model is overloaded", 2) == 8.0


# ---------------------------------------------------------------------------
# De ponta a ponta, pelo ADK
# ---------------------------------------------------------------------------

def _mestre(roteiro_por_chamada, vistos, uso=1234):
    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_response import LlmResponse

    class MestreDeMentira(BaseLlm):
        model: str = "gemini-2.5-flash"

        async def generate_content_async(self, llm_request, stream=False):
            vistos.append(list(llm_request.contents or []))
            parte = roteiro_por_chamada(len(vistos))
            yield LlmResponse(content=types.Content(role="model", parts=[parte]),
                              usage_metadata=types.GenerateContentResponseUsageMetadata(
                                  prompt_token_count=uso))

    return MestreDeMentira()


def _rodar(agente, falas, antes=None):
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService

    sessoes = InMemorySessionService()

    async def rodar():
        await sessoes.create_session(app_name="t", user_id="u", session_id="s")
        runner = Runner(agent=agente, app_name="t", session_service=sessoes)
        for fala in falas:
            if antes:
                antes()
            async for _ in runner.run_async(user_id="u", session_id="s",
                                            new_message=_fala(fala)):
                pass

    asyncio.run(rodar())


def test_o_modelo_nao_recebe_as_ferramentas_dos_turnos_anteriores(campanha):
    from rpg.agent import create_agent
    memory.campaign["name"] = "Teste"

    # Em cada turno: uma ferramenta de leitura, depois a narração.
    def roteiro(n):
        if n % 2 == 1:
            return types.Part(function_call=types.FunctionCall(name="get_scene_context", args={}))
        return types.Part(text=f"narração {n // 2}")

    vistos = []
    agente = create_agent(_mestre(roteiro, vistos), "fantasia")
    _rodar(agente, ["fala 1", "fala 2", "fala 3"])

    # A última chamada (narração do terceiro turno) vê a ferramenta do turno
    # atual, mas não as dos dois anteriores.
    ultimo = vistos[-1]
    respostas = [p.function_response.name for c in ultimo for p in c.parts if p.function_response]
    assert respostas == ["get_scene_context"]
    textos = [p.text for c in ultimo for p in c.parts if p.text]
    assert "fala 1" in textos and "narração 1" in textos and "fala 3" in textos


def test_janela_cheia_o_mestre_espera_e_a_tela_sabe(campanha, monkeypatch):
    from rpg.agent import create_agent
    memory.campaign["name"] = "Teste"

    esperas, avisos = [], []

    async def dormir(s):
        esperas.append(s)
    monkeypatch.setattr(ritmo.asyncio, "sleep", dormir)

    vistos = []
    agente = create_agent(_mestre(lambda n: types.Part(text="ok"), vistos, uso=5000), "fantasia")
    ritmo.registrar("chave", 240_000)          # o minuto já quase cheio

    _rodar(agente, ["fala"], antes=lambda: ritmo.vincular("chave", "gemini-2.5-flash", avisos.append))
    assert esperas and esperas[0] > 0
    assert avisos and "limite de tokens por minuto" in avisos[0]
    # A chamada entrou na janela com o número que o provedor contou.
    assert ritmo.usados("chave") == 240_000 + 5000


def test_sem_chave_vinculada_nao_espera(campanha, monkeypatch):
    """Ollama, e as chamadas fora de um turno de chat, não têm janela."""
    from rpg.agent import create_agent
    memory.campaign["name"] = "Teste"
    esperas = []

    async def dormir(s):
        esperas.append(s)
    monkeypatch.setattr(ritmo.asyncio, "sleep", dormir)
    agente = create_agent(_mestre(lambda n: types.Part(text="ok"), []), "fantasia")
    _rodar(agente, ["fala"], antes=lambda: ritmo.vincular("", "ollama:llama3"))
    assert esperas == []


# ---------------------------------------------------------------------------
# O retry da rota /api/chat
# ---------------------------------------------------------------------------

def _chat_com(runner, monkeypatch, usuario):
    import json as _json
    import server
    from flask import g

    esperas = []

    async def dormir(s):
        esperas.append(s)
    monkeypatch.setattr(server.asyncio, "sleep", dormir)
    memory.bind(usuario, "Ritmo")
    memory.campaign["name"] = "Ritmo"
    server.get_loop()
    server._sessions[usuario] = {"runner": runner, "is_ollama": False,
                                 "model_id": "gemini-2.5-flash", "cota": "chave-teste",
                                 "adk_user": usuario, "adk_session": "s"}
    try:
        with server.app.test_request_context("/api/chat", method="POST",
                                             json={"message": "lanço Sono", "registrar": False}):
            g.user_id = usuario
            corpo = "".join(server.chat.__wrapped__().response)
    finally:
        server._sessions.pop(usuario, None)
    eventos = [_json.loads(l[6:]) for l in corpo.splitlines() if l.startswith("data: ")]
    return eventos, esperas


class _Evento:
    def __init__(self, texto):
        self.content = types.Content(role="model", parts=[types.Part(text=texto)])
        self.usage_metadata = None

    def is_final_response(self):
        return True


def test_limite_por_minuto_espera_o_que_o_gemini_pede_e_avisa(campanha, monkeypatch):
    tentativas = []

    class _Runner:
        async def run_async(self, user_id, session_id, new_message):
            tentativas.append(1)
            if len(tentativas) == 1:
                raise RuntimeError(ERRO_POR_MINUTO)
            yield _Evento("Lyra cai no sono.")

    eventos, esperas = _chat_com(_Runner(), monkeypatch, "u-ritmo-1")
    assert len(tentativas) == 2
    assert esperas and 24 <= esperas[0] <= 25          # não 2 segundos
    aviso = next(e["content"] for e in eventos if e["type"] == "retrying")
    assert "Limite de tokens por minuto" in aviso
    assert any(e["type"] == "text" and "Lyra cai no sono." in e["content"] for e in eventos)
    assert ritmo.limite("chave-teste") == 250_000     # aprendeu o limite da chave


def test_cota_diaria_para_na_hora_e_explica(campanha, monkeypatch):
    tentativas = []

    class _Runner:
        async def run_async(self, user_id, session_id, new_message):
            tentativas.append(1)
            raise RuntimeError(ERRO_DIARIO)
            yield  # pragma: no cover

    eventos, esperas = _chat_com(_Runner(), monkeypatch, "u-ritmo-2")
    assert len(tentativas) == 1 and esperas == []
    erro = next(e["content"] for e in eventos if e["type"] == "error")
    assert "limite DIÁRIO" in erro
