"""
test_importacao_romance.py

Importar (ou criar) uma campanha de romance não pode perder o que o romance
tem: a relação em cada personagem (afeto, confiança, vínculo, estágio,
momentos) e, no nível da campanha, os segredos, os encontros marcados e as
tensões entre os outros.

_payload_de_campanha só copiava os campos que conhecia: o que ficava em cada
personagem sobrevivia, mas segredos, encontros e tensões eram jogados fora.
E o que vem de outra IA não vem no formato do jogo — listas no lugar de
dicionários, chaves sem normalizar, o nome do protagonista como dono.
"""
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

# Como uma IA devolveria, seguindo o prompt de importação do romance.
JSON_DE_OUTRA_IA = {
    "campaign_type": "romance",
    "dnd_mode": True,  # romance é sempre narrativo
    "protagonist": "Clara",
    "chapter": 4,
    "current_location": "Café Aurora",
    "story_summary": "Clara voltou para a cidade natal.",
    "relogio": {"dia": 6, "hora": 15},
    "characters": {
        "Clara": {"name": "Clara", "description": "A protagonista."},
        "Lucas": {"name": "Lucas", "description": "O vizinho.", "atitude": 45, "confianca": -20,
                  "vinculo": "interesse romântico", "estagio": "flerte",
                  "momentos": [{"titulo": "O guarda-chuva dividido", "descricao": "Na chuva", "cap": 2}]},
        "Helena": {"name": "Helena", "description": "A ex de Lucas.", "atitude": -30},
    },
    "locations": {}, "events": [],
    "party": [{"name": "Lucas", "role": "interesse romântico"}],
    "segredos": [
        {"titulo": "A bolsa em Lisboa", "descricao": "Vai embora em março", "dono": "Clara",
         "escondido_de": "Lucas", "sabem": ["Helena"]},
        {"titulo": "O irmão na prisão", "dono": "Lucas", "revelado": True, "como": "descobriu"},
        {"titulo": "O anel guardado", "dono": "Lucas"},
        {"titulo": "a bolsa em lisboa", "dono": ""},  # repetido: fica o primeiro
        {"descricao": "sem título"},
    ],
    "encontros": [
        {"com": "Lucas", "dia": 7, "hora": 20, "onde": "Aurora", "o_que": "jantar"},
        {"com": "Lucas", "dia": "amanhã", "hora": 20},  # sem dia de verdade: fica de fora
    ],
    "tensoes": [
        {"a": "Helena", "b": "Lucas", "tipo": "ciume", "intensidade": 140, "percebida": False},
        {"a": "Lucas", "b": "Lucas", "tipo": "ciume", "intensidade": 10},
    ],
}


@pytest.fixture
def payload():
    import copy
    import server

    dados = copy.deepcopy(JSON_DE_OUTRA_IA)
    personagens = {k.lower(): v for k, v in dados["characters"].items()}
    return server._payload_de_campanha("Cartas", dados, personagens)


def test_romance_importado_fica_sem_regras(payload):
    assert (payload["campaign_type"], payload["dnd_mode"]) == ("romance", False)


def test_a_relacao_em_cada_personagem_sobrevive(payload):
    lucas = payload["characters"]["lucas"]
    assert (lucas["atitude"], lucas["confianca"], lucas["vinculo"], lucas["estagio"]) == \
        (45, -20, "interesse romântico", "flerte")
    assert lucas["momentos"][0]["titulo"] == "O guarda-chuva dividido"
    assert payload["relogio"] == {"dia": 6, "hora": 15}


def test_segredos_sao_normalizados(payload):
    s = payload["segredos"]
    assert list(s) == ["a bolsa em lisboa", "o irmao na prisao", "o anel guardado"]
    bolsa = s["a bolsa em lisboa"]
    # O nome do protagonista como dono vira o dono vazio; texto vira lista.
    assert (bolsa["dono"], bolsa["escondido_de"], bolsa["sabem"]) == ("", ["Lucas"], ["Helena"])
    irmao = s["o irmao na prisao"]
    assert (irmao["revelado"], irmao["como"], irmao["dono_sabe"]) == (True, "descobriu", False)
    anel = s["o anel guardado"]
    assert (anel["revelado"], anel["dono_sabe"]) == (False, True)


def test_encontros_e_tensoes_sao_normalizados(payload):
    assert [(e["com"], e["dia"], e["hora"], e["estado"]) for e in payload["encontros"]] == \
        [("Lucas", 7, 20, "marcado")]
    assert list(payload["tensoes"]) == ["helena|lucas"]
    t = payload["tensoes"]["helena|lucas"]
    assert (t["intensidade"], t["percebida"], t["tipo"]) == (100, False, "ciume")


def test_a_campanha_importada_funciona_no_jogo(payload, campanha):
    """Depois de carregada, as telas enxergam tudo, e o que é escondido continua escondido."""
    from rpg import encontros, memory, relacoes, segredos, tensoes

    for chave in ("campaign_type", "dnd_mode", "protagonist", "chapter", "relogio", "characters", "party",
                  "segredos", "encontros", "tensoes"):
        campanha[chave] = payload[chave]
    memory.normalizar_campanha()
    v = segredos.visiveis()
    assert [s["titulo"] for s in v["seus"]] == ["A bolsa em Lisboa"]
    assert [s["titulo"] for s in v["dos_outros"]] == ["O irmão na prisão"]
    assert encontros.proximo()["falta"] == "em 1d 5h"
    assert tensoes.percebidas() == []
    assert "Helena × Lucas: ciúme 100" in tensoes.resumo_para_o_mestre()
    nomes = [p["nome"] for p in relacoes.lista()["pessoas"]]
    assert "Lucas" in nomes and "Clara" not in nomes


def test_campanha_sem_nada_disso_continua_igual():
    import server

    p = server._payload_de_campanha("Velha", {"campaign_type": "fantasia", "dnd_mode": True}, {})
    assert (p["segredos"], p["encontros"], p["tensoes"]) == ({}, [], {})


def test_a_rota_de_importacao_grava_o_romance(monkeypatch):
    import copy

    sys.path.insert(0, str(RAIZ / "scripts"))
    import capturar_telas as cap
    import server
    from rpg import database

    cap._instalar_dubles({"name": "Base"}, "Base")
    gravado = {}
    monkeypatch.setattr(database, "save_campaign", lambda uid, nome, dados: gravado.update(dados))
    monkeypatch.setattr(database, "campaign_exists", lambda uid, nome: False)
    try:
        r = server.app.test_client().post(
            "/api/campaigns/import", json={"name": "Cartas", "campaign": copy.deepcopy(JSON_DE_OUTRA_IA)},
            headers={"Authorization": f"Bearer {cap.TOKEN}"})
    finally:
        cap._remover_dubles()
    assert r.status_code == 200, r.get_json()
    assert len(gravado["segredos"]) == 3 and len(gravado["encontros"]) == 1 and len(gravado["tensoes"]) == 1
    assert gravado["characters"]["lucas"]["estagio"] == "flerte"


def test_o_editor_da_campanha_nao_apaga_a_relacao(monkeypatch):
    """
    O editor do menu monta cada personagem só com os campos do formulário, e
    quem devolve o resto é locais.normalizar_campanha_editada ("campo que o
    editor não manda fica como estava"). Este teste tranca isso para o
    romance: afeto, confiança, vínculo, estágio, momentos e o porquê.
    """
    import copy

    sys.path.insert(0, str(RAIZ / "scripts"))
    import capturar_telas as cap
    import server
    from rpg import database

    gravada = {"name": "Cartas", "campaign_type": "romance", "dnd_mode": False, "protagonist": "Clara",
               "characters": {"lucas": {"name": "Lucas", "description": "O vizinho.", "atitude": 45,
                                        "atitude_historico": [{"delta": 45, "motivo": "O café"}],
                                        "confianca": -20, "vinculo": "interesse romântico",
                                        "estagio": "flerte", "momentos": [{"titulo": "O café"}]}},
               "party": [], "locations": {}, "events": []}
    cap._instalar_dubles(gravada, "Cartas")
    salvo = {}
    monkeypatch.setattr(database, "save_campaign", lambda uid, nome, dados: salvo.update(dados))
    # Como o editor manda: só os campos do formulário, com a descrição mudada.
    do_editor = {"name": "Cartas", "campaign_type": "romance", "protagonist": "Clara",
                 "characters": {"lucas": {"name": "Lucas", "description": "O vizinho do 302.", "traits": "",
                                          "status": "vivo", "notes": "", "role": "", "local": "",
                                          "conhecido": [], "sheet": None, "inventario": [], "habilidades": [],
                                          "correcao_manual": False}},
                 "party": [], "locations": {}, "events": []}
    try:
        r = server.app.test_client().put("/api/campaigns/Cartas", json={"campaign": copy.deepcopy(do_editor)},
                                         headers={"Authorization": f"Bearer {cap.TOKEN}"})
    finally:
        cap._remover_dubles()
    assert r.status_code == 200, r.get_json()
    lucas = salvo["characters"]["lucas"]
    assert lucas["description"] == "O vizinho do 302."  # o que o editor mudou, mudou
    assert (lucas["atitude"], lucas["confianca"], lucas["vinculo"], lucas["estagio"]) == \
        (45, -20, "interesse romântico", "flerte")
    assert lucas["momentos"] == [{"titulo": "O café"}]
    assert lucas["atitude_historico"][0]["motivo"] == "O café"
