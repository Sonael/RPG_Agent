"""
test_editor_campanha_lugares.py

"Fica dentro de" e "Onde está" no editor da campanha (menu), e o salvamento
dele não apagando o que não conhece.

O PUT /api/campaigns/<nome> recebia personagens e locais remontados pelo
editor só com os campos dele: salvar pelo menu apagava a atitude, a marca de
XP por derrota, o "onde está" e o "fica dentro de". E o editor gravava a
chave do local com sublinhado ("praça_de_cliviate"), enquanto save_location
usa o nome em minúsculas: o mestre depois criava o mesmo lugar ao lado.
"""
import copy
import sys
from pathlib import Path

import pytest

from rpg import locais

from conftest import criar_ficha

RAIZ = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 1. A normalização
# ---------------------------------------------------------------------------

def _antigos():
    locs = {
        "cliviate": {"name": "Cliviate", "description": "Cidade.", "details": "", "notes": "",
                     "segredo_do_mestre": "o poço leva ao subterrâneo"},
        "praça de cliviate": {"name": "Praça de Cliviate", "dentro_de": "Cliviate",
                              "description": "Praça.", "details": "", "notes": ""},
    }
    chars = {"brom": {"name": "Brom", "description": "Ferreiro.", "status": "vivo",
                      "atitude": 25, "xp_concedido_a": ["alden"], "local": "Forja de Cliviate"}}
    lojas = {"forja de cliviate": {"nome": "Forja de Cliviate", "local": "Cliviate", "estoque": []}}
    return locs, chars, lojas


def test_chave_do_local_vira_o_nome_em_minusculas():
    locs, chars, lojas = _antigos()
    novos = {"praça_de_cliviate": {"name": "Praça de Cliviate", "description": "Praça."}}
    saida, erro = locais.normalizar_campanha_editada(novos, locs, {}, chars, lojas)
    assert not erro and list(saida) == ["praça de cliviate"]


def test_campo_que_o_editor_nao_manda_fica_no_local():
    locs, chars, lojas = _antigos()
    novos = {"cliviate": {"name": "Cliviate", "description": "Cidade murada."}}
    saida, _ = locais.normalizar_campanha_editada(novos, locs, {}, chars, lojas)
    assert saida["cliviate"]["segredo_do_mestre"] == "o poço leva ao subterrâneo"
    assert saida["cliviate"]["description"] == "Cidade murada."


def test_dentro_de_com_nome_canonico_e_vazio_apaga():
    locs, chars, lojas = _antigos()
    novos = {"praça de cliviate": {"name": "Praça de Cliviate", "dentro_de": "CLIVIATE"},
             "cliviate": {"name": "Cliviate", "dentro_de": ""}}
    saida, _ = locais.normalizar_campanha_editada(novos, locs, {}, chars, lojas)
    assert saida["praça de cliviate"]["dentro_de"] == "Cliviate"
    assert "dentro_de" not in saida["cliviate"]


def test_ciclo_e_erro():
    locs, chars, lojas = _antigos()
    novos = {"praça de cliviate": {"name": "Praça de Cliviate", "dentro_de": "Cliviate"},
             "cliviate": {"name": "Cliviate", "dentro_de": "Praça de Cliviate"}}
    _, erro = locais.normalizar_campanha_editada(novos, locs, {}, chars, lojas)
    assert erro and "já fica dentro" in erro


def test_personagem_mantem_atitude_e_marca_de_xp():
    locs, chars, lojas = _antigos()
    novos_chars = {"brom": {"name": "Brom", "description": "Ferreiro de avental."}}
    locais.normalizar_campanha_editada(locs, locs, novos_chars, chars, lojas)
    brom = novos_chars["brom"]
    assert brom["atitude"] == 25 and brom["xp_concedido_a"] == ["alden"]
    assert brom["local"] == "Forja de Cliviate"


def test_onde_esta_canonico_inclusive_loja_e_vazio_apaga():
    locs, chars, lojas = _antigos()
    novos_chars = {"brom": {"name": "Brom", "local": "forja de cliviate"},
                   "tiel": {"name": "Tiel", "local": "praça de cliviate"},
                   "nana": {"name": "Nana", "local": ""}}
    locais.normalizar_campanha_editada(locs, locs, novos_chars, {"nana": {"name": "Nana", "local": "Cliviate"}}, lojas)
    assert novos_chars["brom"]["local"] == "Forja de Cliviate"
    assert novos_chars["tiel"]["local"] == "Praça de Cliviate"
    assert "local" not in novos_chars["nana"]


# ---------------------------------------------------------------------------
# 2. A rota
# ---------------------------------------------------------------------------

@pytest.fixture
def rota(monkeypatch):
    sys.path.insert(0, str(RAIZ / "scripts"))
    import capturar_telas as cap
    import server
    from rpg import database

    locs, chars, lojas = _antigos()
    antiga = {"name": "Teste", "locations": locs, "lojas": lojas,
              "characters": {"brom": {**chars["brom"]},
                             "alden": {**criar_ficha("Alden", grupo=True), "party_member": True}},
              "party": [{"name": "Alden", "role": "", "notes": ""}]}
    cap._instalar_dubles(antiga, "Teste")
    gravado = {}
    monkeypatch.setattr(database, "save_campaign", lambda uid, nome, dados: gravado.update(dados))

    def put(campanha):
        return server.app.test_client().put(
            "/api/campaigns/Teste", json={"campaign": campanha},
            headers={"Authorization": f"Bearer {cap.TOKEN}"})

    try:
        yield antiga, put, gravado
    finally:
        cap._remover_dubles()


def test_rota_grava_lugares_e_nao_apaga_campos(rota):
    antiga, put, gravado = rota
    editada = copy.deepcopy(antiga)
    editada["locations"] = {
        "cliviate": {"name": "Cliviate", "dentro_de": "", "description": "Cidade."},
        "praça_de_cliviate": {"name": "Praça de Cliviate", "dentro_de": "cliviate",
                              "description": "Praça."},
    }
    editada["characters"]["brom"] = {"name": "Brom", "description": "Ferreiro.",
                                     "status": "vivo", "local": "praça de cliviate"}

    r = put(editada)

    assert r.status_code == 200, r.get_json()
    assert set(gravado["locations"]) == {"cliviate", "praça de cliviate"}
    assert gravado["locations"]["praça de cliviate"]["dentro_de"] == "Cliviate"
    assert gravado["locations"]["cliviate"]["segredo_do_mestre"] == "o poço leva ao subterrâneo"
    brom = gravado["characters"]["brom"]
    assert brom["local"] == "Praça de Cliviate" and brom["atitude"] == 25


def test_rota_recusa_ciclo(rota):
    antiga, put, gravado = rota
    editada = copy.deepcopy(antiga)
    editada["locations"]["cliviate"]["dentro_de"] = "Praça de Cliviate"
    r = put(editada)
    assert r.status_code == 400 and "já fica dentro" in r.get_json()["error"]
    assert gravado == {}


def test_desmarcar_do_grupo_no_editor_vale(rota):
    antiga, put, gravado = rota
    editada = copy.deepcopy(antiga)
    editada["party"] = []
    editada["characters"]["alden"].pop("party_member")    # o editor não manda esse campo
    put(editada)
    assert gravado["characters"]["alden"]["party_member"] is False


def test_rota_grava_observacoes_e_cliente_antigo_nao_apaga(rota):
    antiga, put, gravado = rota
    antiga["quest_flags"] = {"ponte_caiu": "sim"}

    editada = copy.deepcopy(antiga)
    editada["quest_flags"] = {"ponte_caiu": "não", "selo_real": "entregue"}
    assert put(editada).status_code == 200
    assert gravado["quest_flags"] == {"ponte_caiu": "não", "selo_real": "entregue"}

    gravado.clear()
    sem_campo = copy.deepcopy(antiga)
    sem_campo.pop("quest_flags")
    assert put(sem_campo).status_code == 200
    assert gravado["quest_flags"] == {"ponte_caiu": "sim"}


def test_ficha_mochila_e_habilidades_que_o_editor_nao_manda_ficam(rota):
    """
    Sem as regras de D&D o editor não manda ficha, mochila nem habilidades.
    A normalização punha listas vazias no lugar das ausentes, e salvar uma
    campanha narrativa apagava a mochila de todos (os créditos do sci-fi, a
    habilidade especial da fantasia, o que o mestre deu no jogo).
    """
    antiga, put, gravado = rota
    antiga["characters"]["brom"]["inventario"] = [{"nome": "Martelo", "qtd": 1, "descricao": ""}]
    antiga["characters"]["brom"]["habilidades"] = [{"nome": "Forjar", "descricao": ""}]
    editada = copy.deepcopy(antiga)
    for campo in ("inventario", "habilidades", "sheet"):
        editada["characters"]["brom"].pop(campo, None)
        editada["characters"]["alden"].pop(campo, None)

    assert put(editada).status_code == 200
    brom, alden = gravado["characters"]["brom"], gravado["characters"]["alden"]
    assert brom["inventario"] == [{"nome": "Martelo", "qtd": 1, "descricao": ""}]
    assert brom["habilidades"] == [{"nome": "Forjar", "descricao": ""}]
    ficha = antiga["characters"]["alden"]["sheet"]
    assert {k: alden["sheet"][k] for k in ficha} == ficha      # a normalização só acrescenta padrões

    # Mandados, valem: é o editor com as regras, que mostra os três.
    gravado.clear()
    editada["characters"]["brom"]["inventario"] = []
    assert put(editada).status_code == 200
    assert gravado["characters"]["brom"]["inventario"] == []
