"""
test_wizard_lugares.py

"Fica dentro de" e "Onde está" no wizard de criação de campanha, e a criação
(POST /api/campaigns) e a importação (POST /api/campaigns/import) aplicando
as mesmas regras de lugar do editor: chave do local pelo nome, nomes
canônicos, ciclo recusado.

O wizard também gravava a chave do local com sublinhado
("taverna_do_caldeirão"), e o mestre depois criava "taverna do caldeirão" ao
lado.
"""
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture
def rotas(monkeypatch):
    sys.path.insert(0, str(RAIZ / "scripts"))
    import capturar_telas as cap
    import server
    from rpg import database

    cap._instalar_dubles({"name": "Base"}, "Base")
    gravado = {}
    monkeypatch.setattr(database, "save_campaign", lambda uid, nome, dados: gravado.update(dados))
    monkeypatch.setattr(database, "campaign_exists", lambda uid, nome: False)
    cliente = server.app.test_client()
    cabecalho = {"Authorization": f"Bearer {cap.TOKEN}"}
    try:
        yield cliente, cabecalho, gravado
    finally:
        cap._remover_dubles()


def _campanha(**extra):
    base = {
        "campaign_type": "fantasia",
        "current_location": "Praça de Cliviate",
        "locations": {
            "cliviate": {"name": "Cliviate", "dentro_de": "", "description": "Cidade."},
            "taverna_do_caldeirão": {"name": "Taverna do Caldeirão", "dentro_de": "cliviate",
                                     "description": "Ensopado."},
        },
        "characters": {
            "nana": {"name": "Nana", "description": "Taverneira.", "status": "vivo",
                     "local": "taverna do caldeirão"},
        },
        "party": [],
    }
    base.update(extra)
    return base


def test_criar_pelo_wizard_grava_lugares(rotas):
    cliente, cabecalho, gravado = rotas
    r = cliente.post("/api/campaigns", json={"name": "Nova", "campaign": _campanha()}, headers=cabecalho)

    assert r.status_code == 200, r.get_json()
    assert set(gravado["locations"]) == {"cliviate", "taverna do caldeirão"}
    assert gravado["locations"]["taverna do caldeirão"]["dentro_de"] == "Cliviate"
    assert "dentro_de" not in gravado["locations"]["cliviate"]
    assert gravado["characters"]["nana"]["local"] == "Taverna do Caldeirão"


def test_criar_com_ciclo_e_recusado(rotas):
    cliente, cabecalho, gravado = rotas
    camp = _campanha()
    camp["locations"]["cliviate"]["dentro_de"] = "Taverna do Caldeirão"

    r = cliente.post("/api/campaigns", json={"name": "Nova", "campaign": camp}, headers=cabecalho)

    assert r.status_code == 400 and "já fica dentro" in r.get_json()["error"]
    assert gravado == {}


def test_importar_arquivo_aplica_as_mesmas_regras(rotas):
    cliente, cabecalho, gravado = rotas
    r = cliente.post("/api/campaigns/import", json={"name": "Importada", "campaign": _campanha()},
                     headers=cabecalho)
    assert r.status_code == 200, r.get_json()
    assert gravado["locations"]["taverna do caldeirão"]["dentro_de"] == "Cliviate"


def test_prompt_de_lore_pede_dentro_de_e_local():
    fonte = (RAIZ / "server.py").read_text(encoding="utf-8")
    assert '"dentro_de":""' in fonte
    assert "preencha 'local' com o nome exato do local gerado" in fonte


def test_wizard_manda_os_campos_e_a_chave_com_espaco():
    js = (RAIZ / "static" / "js" / "menu.js").read_text(encoding="utf-8")
    bloco = js.split("async function createCampaignFromWizard()")[1].split("\n}\n")[0]
    assert "local:       (char.local || '').trim()" in bloco
    assert "dentro_de: (loc.dentro_de || '').trim()" in bloco
    assert "replace(/\\s+/g, '_')" not in bloco, "a chave do local voltou a usar sublinhado"
