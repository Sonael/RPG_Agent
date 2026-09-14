"""
test_gerar_lore.py

A rota de "Gerar com IA" do wizard (POST /api/campaigns/generate-lore) com o
modelo simulado, porque os testes não têm chave de API.

Defeitos que isto cobre:
  • resposta com uma frase antes do JSON ("Aqui está o mundo da sua
    campanha:"), comum em modelo que conversa, virava erro 500 — só as cercas
    de markdown no começo e no fim eram tiradas;
  • resposta cortada chegava ao jogador como "IA retornou JSON inválido:
    Unterminated string starting at: line 1 column 111";
  • o DeepSeek limitava a resposta a 1500 tokens, e no deepseek-reasoner o
    raciocínio conta no mesmo limite: o JSON saía cortado.
"""
import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

LORE = {
    "story_summary": "Cliviate sofre com desaparecimentos.",
    "current_scene": "Chuva fina na praça.",
    "current_location": "Praça de Cliviate",
    "locations": [{"name": "Cliviate", "description": "Cidade.", "details": "", "notes": "", "dentro_de": ""}],
    "events": [{"summary": "Lenhadores sumiram.", "location": "Cliviate",
                "characters_involved": "Brom", "consequence": "Portão fechado."}],
    "characters": [{"name": "Brom", "description": "Ferreiro.", "traits": "", "notes": "",
                    "role": "", "tipo": "aliado", "classe": "npc", "raca": "commoner",
                    "local": "Cliviate"}],
}
TXT = json.dumps(LORE, ensure_ascii=False)


@pytest.fixture
def rota(monkeypatch):
    sys.path.insert(0, str(RAIZ / "scripts"))
    import capturar_telas as cap
    import server
    from google import genai

    resposta = {"texto": TXT, "pedido": None}

    class _Resp:
        @property
        def text(self):
            return resposta["texto"]

    class _Modelos:
        def generate_content(self, **kw):
            resposta["pedido"] = kw
            return _Resp()

    class _Cliente:
        def __init__(self, api_key=None):
            self.models = _Modelos()

    cap._instalar_dubles({"name": "Base"}, "Base")
    monkeypatch.setattr(genai, "Client", _Cliente)
    cliente = server.app.test_client()

    def gerar(texto=TXT, **extra):
        resposta["texto"] = texto
        corpo = {"prompt": "Desaparecimentos em Cliviate", "model": "gemini-3-flash",
                 "campaign_type": "dnd", "google_api_key": "chave-de-teste", **extra}
        return cliente.post("/api/campaigns/generate-lore", json=corpo,
                            headers={"Authorization": f"Bearer {cap.TOKEN}"})

    try:
        yield gerar, resposta
    finally:
        cap._remover_dubles()


@pytest.mark.parametrize("texto", [
    TXT,
    "```json\n" + TXT + "\n```",
    "Aqui está o mundo da sua campanha:\n" + TXT,
    "Claro! Segue:\n```json\n" + TXT + "\n```\nBoa aventura!",
], ids=["limpo", "cercas", "frase-antes", "frase-e-cercas"])
def test_resposta_com_texto_em_volta_ainda_gera(rota, texto):
    gerar, _ = rota
    r = gerar(texto)
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["lore"] == LORE


def test_resposta_cortada_tem_mensagem_para_o_jogador(rota):
    gerar, _ = rota
    r = gerar(TXT[: len(TXT) // 2])
    assert r.status_code == 502
    erro = r.get_json()["error"]
    assert "incompleta" in erro and "Tente gerar de novo" in erro
    assert "Unterminated" not in erro


def test_resposta_sem_json_tem_mensagem_para_o_jogador(rota):
    gerar, _ = rota
    r = gerar("Desculpe, não posso ajudar com isso.")
    assert r.status_code == 502 and "formato esperado" in r.get_json()["error"]


def test_prompt_pede_todos_os_campos_que_o_wizard_preenche(rota):
    gerar, resposta = rota
    gerar()
    prompt = resposta["pedido"]["contents"]
    for campo in ('"story_summary"', '"current_scene"', '"current_location"', '"dentro_de"',
                  '"characters_involved"', '"consequence"', '"tipo"', '"classe"', '"raca"',
                  '"local"', '"traits"', '"notes"', '"role"'):
        assert campo in prompt, campo
    assert resposta["pedido"]["model"] == "gemini-3-flash"


def test_sem_chave_avisa(rota):
    gerar, _ = rota
    import os
    if os.environ.get("GOOGLE_API_KEY"):
        pytest.skip("há GOOGLE_API_KEY no ambiente")
    r = gerar(google_api_key="")
    assert r.status_code == 400 and "Chave Google" in r.get_json()["error"]


def test_deepseek_tem_espaco_para_a_resposta(rota, monkeypatch):
    gerar, _ = rota
    import requests
    enviado = {}

    class _RespDS:
        def json(self):
            return {"choices": [{"message": {"content": TXT}}]}

    monkeypatch.setattr(requests, "post",
                        lambda url, headers=None, json=None, timeout=None: (enviado.update(json or {}), _RespDS())[1])
    r = gerar(model="deepseek:deepseek-reasoner", deepseek_api_key="chave-de-teste")
    assert r.status_code == 200
    assert enviado["max_tokens"] >= 8000


def test_extrair_json_da_ia_pega_o_primeiro_objeto_valido():
    import server
    assert server._extrair_json_da_ia('lixo {"a": 1} mais lixo') == {"a": 1}
    with pytest.raises(ValueError):
        server._extrair_json_da_ia('[1, 2, 3]')
