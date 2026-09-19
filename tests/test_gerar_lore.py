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
    # O limite de gerações por usuário (12 em 15 min) é do servidor, não do
    # teste: sem zerar, o 13º teste do arquivo recebe 429.
    server._rate_buckets.clear()
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


# --- O gênero no prompt ------------------------------------------------------
# Antes o prompt só dizia o id do gênero ("romance"): não pedia quem é o
# protagonista, quem está com ele (no romance, só "jogador" entrava no grupo),
# os campos do gênero que o wizard mostra, nem as mecânicas do gênero — as
# telas de Relações e do Mundo nasciam vazias.

CAMPOS_ROMANCE = [
    {"id": "papel", "label": "Papel na Dinâmica", "type": "select",
     "options": ["Protagonista", "Interesse Romântico", "Rival Amoroso"]},
    {"id": "segredo", "label": "Segredo Guardado", "type": "text", "hint": "O que esconde, e de quem?"},
]


def _prompt(rota, **corpo):
    gerar, resposta = rota
    assert gerar(**corpo).status_code == 200
    return resposta["pedido"]["contents"]


def test_romance_pede_protagonista_proximos_campos_e_relacao(rota):
    p = _prompt(rota, campaign_type="romance", dnd_mode=False, campos=CAMPOS_ROMANCE)
    for trecho in ('"protagonista":<true|false>', '"grupo":<true|false>',
                   '"papel":"<Protagonista|Interesse Romântico|Rival Amoroso>"',
                   '"segredo":"<Segredo Guardado (O que esconde, e de quem?)>"',
                   '"afeto":<-100 a 100>', '"confianca":<-100 a 100>',
                   '"estagio":"<conhecidos|amizade|flerte|namoro|compromisso|rompimento>"',
                   '"segredos":[', '"tensoes":[', "O campo 'role' é 'Relacionamento'",
                   "Gênero (tom do mundo): Romance / Drama"):
        assert trecho in p, trecho
    for de_outro in ('"lealdade"', '"faccoes"', '"lendas"', '"renome"', '"classe"', "com base na classe"):
        assert de_outro not in p, de_outro


def test_fantasia_com_dnd_pede_o_laco_e_o_mundo(rota):
    # Com D&D a ficha continua (classe e raça); os campos do gênero não, que
    # o wizard não os mostra com regras.
    p = _prompt(rota, campaign_type="fantasia", dnd_mode=True, campos=CAMPOS_ROMANCE)
    for trecho in ('"protagonista":<true|false>', '"lealdade":<-100 a 100>', '"objetivo":""', '"arco":""',
                   '"renome":<0 a 100>', '"faccoes":[', '"lendas":[', '"classe"', '"raca"',
                   "Fantasia / Aventura · D&D"):
        assert trecho in p, trecho
    for de_outro in ('"extras"', '"grupo"', '"afeto"', '"segredos"', '"tensoes"'):
        assert de_outro not in p, de_outro


def test_dark_fantasy_sem_regras_tem_o_mundo_e_os_campos(rota):
    p = _prompt(rota, campaign_type="dark_fantasy", dnd_mode=False,
                campos=[{"id": "raca", "label": "Raça", "type": "select", "options": ["Humano", "Elfo"]}])
    for trecho in ('"grupo":<true|false>', '"extras":{"raca":"<Humano|Elfo>"}', '"lealdade"', '"faccoes":[',
                   "(Companhia)"):
        assert trecho in p, trecho


def test_horror_nao_ganha_mecanica_de_outro_genero(rota):
    p = _prompt(rota, campaign_type="horror", dnd_mode=False,
                campos=[{"id": "sanidade", "label": "Sanidade Atual (0–10)", "type": "number", "min": 0, "max": 10}])
    assert '"extras":{"sanidade":<0 a 10: Sanidade Atual (0–10)>}' in p
    for de_outro in ('"afeto"', '"segredos"', '"lealdade"', '"faccoes"'):
        assert de_outro not in p, de_outro


def test_campos_do_menu_sao_filtrados():
    import server
    campos = server._campos_do_genero([
        {"id": "creditos", "label": "Créditos", "type": "number", "min": 0},
        {"id": "Fora Do Padrao", "label": "x"},
        {"id": "papel", "type": "select", "options": ["A", 3, " ", "B"]},
        "lixo",
    ] + [{"id": f"c{'x' * i}", "label": "y"} for i in range(10)])
    assert [c["id"] for c in campos][:2] == ["creditos", "papel"]
    assert len(campos) <= 8
    assert campos[1]["opcoes"] == ["A", "B"]
    assert server._campo_no_schema(campos[0]) == '"creditos":<número, mínimo 0: Créditos>'
    assert server._campos_do_genero("lixo") == []
