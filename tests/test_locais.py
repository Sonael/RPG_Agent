"""
test_locais.py

Locais com "fica dentro de", personagens com "onde está", e a ficha do local
que a tela mostra.

Antes: os locais eram uma lista plana (Cliviate, a Forja e o Boticário não se
conheciam), personagem nenhum tinha paradeiro, e save_character recriava o
personagem só com os campos dele, apagando o resto (a atitude, por exemplo).
"""
import pytest

from rpg import locais, memory, tools as tl, tools_dnd as td

from conftest import criar_ficha


@pytest.fixture
def cliviate(campanha, povoar):
    povoar(criar_ficha("Alden", grupo=True), criar_ficha("Lyra", grupo=True))
    c = memory.campaign
    c["current_location"] = "Cliviate"
    tl.save_location("Cliviate", "Cidade de muralhas baixas na borda da floresta.")
    tl.save_location("Praça de Cliviate", "Uma praça com um poço antigo.", dentro_de="cliviate")
    tl.save_location("Floresta das Brumas", "Neblina que não se desfaz.")
    td.open_shop("Forja de Cliviate", "Espada Longa", location="Cliviate")
    td.open_shop("Boticário da Mira", "Poção de Cura:50:3", location="Cliviate")
    tl.save_character("Brom", "Ferreiro corpulento.", local="forja de cliviate")
    tl.save_character("Mira", "Boticária de óculos redondos.", local="Boticário da Mira")
    tl.save_character("Guarda Tiel", "Guarda da praça.", local="Praça de Cliviate")
    tl.save_character("Eremita", "Vive na neblina.", local="Floresta das Brumas")
    return c


# ---------------------------------------------------------------------------
# 1. Dados
# ---------------------------------------------------------------------------

def test_dentro_de_grava_o_nome_como_esta_salvo(cliviate):
    assert cliviate["locations"]["praça de cliviate"]["dentro_de"] == "Cliviate"


def test_salvar_de_novo_sem_dentro_de_mantem(cliviate):
    tl.save_location("Praça de Cliviate", "A praça, agora com feira.")
    assert cliviate["locations"]["praça de cliviate"]["dentro_de"] == "Cliviate"


def test_local_nao_fica_dentro_de_si_nem_em_ciclo(cliviate):
    assert tl.save_location("Cliviate", "x" * 20, dentro_de="Cliviate").startswith("Erro:")
    assert tl.save_location("Cliviate", "x" * 20, dentro_de="Praça de Cliviate").startswith("Erro:")
    assert "dentro_de" not in cliviate["locations"]["cliviate"]


def test_personagem_ganha_local_com_nome_canonico(cliviate):
    assert cliviate["characters"]["brom"]["local"] == "Forja de Cliviate"


def test_salvar_personagem_de_novo_nao_apaga_o_que_ja_tinha(cliviate):
    cliviate["characters"]["brom"]["atitude"] = 30
    tl.save_character("Brom", "Ferreiro corpulento, agora de avental novo.")
    brom = cliviate["characters"]["brom"]
    assert brom["atitude"] == 30, "a atitude sumia a cada save_character"
    assert brom["local"] == "Forja de Cliviate"


def test_set_character_location_move_e_apaga(cliviate):
    assert "está em Praça de Cliviate" in tl.set_character_location("Brom", "praça de cliviate")
    assert cliviate["characters"]["brom"]["local"] == "Praça de Cliviate"
    tl.set_character_location("Brom", "")
    assert "local" not in cliviate["characters"]["brom"]


def test_set_character_location_recusa_grupo_e_desconhecido(cliviate):
    assert tl.set_character_location("Alden", "Forja de Cliviate").startswith("Aviso:")
    assert tl.set_character_location("Ninguém", "Forja de Cliviate").startswith("Erro:")


# ---------------------------------------------------------------------------
# 2. Hierarquia e alcance
# ---------------------------------------------------------------------------

def test_filhos_trazem_locais_e_lojas(cliviate):
    dentro = {f["nome"]: f["tipo"] for f in locais.filhos("Cliviate")}
    assert dentro == {"Praça de Cliviate": "local", "Forja de Cliviate": "loja",
                      "Boticário da Mira": "loja"}


def test_loja_salva_tambem_como_local_nao_repete(cliviate):
    tl.save_location("Forja de Cliviate", "Calor e cheiro de carvão.", dentro_de="Cliviate")
    nomes = [f["nome"] for f in locais.filhos("Cliviate")]
    assert nomes.count("Forja de Cliviate") == 1


def test_caminho_da_loja(cliviate):
    assert locais.caminho("forja de cliviate") == ["Cliviate", "Forja de Cliviate"]


def test_alcance_a_partir_da_cidade(cliviate):
    assert locais.alcance("Cliviate") == "aqui"
    assert locais.alcance("Forja de Cliviate") == "dentro"
    assert locais.alcance("Floresta das Brumas") == ""


def test_alcance_a_partir_da_forja(cliviate):
    cliviate["current_location"] = "Forja de Cliviate"
    assert locais.alcance("Cliviate") == "acima"
    assert locais.alcance("Boticário da Mira") == "vizinho"
    assert locais.alcance("Praça de Cliviate") == "vizinho"
    assert locais.alcance("Floresta das Brumas") == ""


# ---------------------------------------------------------------------------
# 3. Ficha
# ---------------------------------------------------------------------------

def test_ficha_da_cidade_onde_o_grupo_esta(cliviate):
    f = locais.ficha("")

    assert f["nome"] == "Cliviate" and f["e_o_local_atual"] is True
    assert f["grupo_aqui"] == ["Alden", "Lyra"]
    dentro = {d["nome"]: d for d in f["dentro"]}
    assert dentro["Forja de Cliviate"]["alcance"] == "dentro"
    assert dentro["Forja de Cliviate"]["pessoas"] == 1
    assert f["pessoas"] == []


def test_ficha_da_loja_mostra_quem_esta_e_deixa_falar(cliviate):
    f = locais.ficha("Forja de Cliviate")

    assert f["tipo"] == "loja" and f["caminho"] == ["Cliviate", "Forja de Cliviate"]
    assert f["alcance"] == "dentro" and f["e_o_local_atual"] is False
    assert [p["nome"] for p in f["pessoas"]] == ["Brom"]
    assert f["pessoas"][0]["pode_falar"] is True
    assert f["grupo_aqui"] == []


def test_longe_nao_deixa_falar(cliviate):
    f = locais.ficha("Floresta das Brumas")
    assert f["alcance"] == ""
    assert f["pessoas"][0]["nome"] == "Eremita" and f["pessoas"][0]["pode_falar"] is False


def test_morto_nao_deixa_falar(cliviate):
    cliviate["characters"]["brom"]["status"] = "morto"
    assert locais.ficha("Forja de Cliviate")["pessoas"][0]["pode_falar"] is False


def test_ficha_de_lugar_desconhecido_nao_quebra(cliviate):
    f = locais.ficha("Castelo que ninguém salvou")
    assert f["existe"] is False and f["dentro"] == [] and f["pessoas"] == []


def test_contexto_do_mestre_mostra_o_mapa(cliviate):
    texto = tl.get_scene_context()
    assert "Dentro daqui: Praça de Cliviate, Forja de Cliviate (loja), Boticário da Mira (loja)" in texto


def test_contexto_mostra_quem_esta_no_local_atual(cliviate):
    cliviate["current_location"] = "Forja de Cliviate"
    texto = tl.get_scene_context()
    assert "Fica em: Cliviate" in texto
    assert "Estão aqui: Brom" in texto


# ---------------------------------------------------------------------------
# 4. Loja com hierarquia
# ---------------------------------------------------------------------------

def test_na_cidade_as_duas_lojas_sao_daqui(cliviate):
    snap = td.shop_snapshot()
    assert {l["nome"] for l in snap["lojas_aqui"]} == {"Forja de Cliviate", "Boticário da Mira"}
    assert set(snap["filhos_chaves"]) >= {"forja de cliviate", "boticario da mira"}


def test_dentro_da_forja_so_a_forja_e_daqui(cliviate):
    cliviate["current_location"] = "Forja de Cliviate"
    snap = td.shop_snapshot()
    assert snap["loja_aqui"] is True
    assert [l["nome"] for l in snap["lojas_aqui"]] == ["Forja de Cliviate"]


def test_reabastecer_com_a_cidade_estando_na_forja_nao_tira_o_grupo_da_loja(cliviate):
    cliviate["current_location"] = "Forja de Cliviate"
    saida = td.open_shop("Forja de Cliviate", "Escudo", location="Cliviate")
    assert cliviate["current_location"] == "Forja de Cliviate"
    assert "Nota:" not in saida


# ---------------------------------------------------------------------------
# 5. Rotas
# ---------------------------------------------------------------------------

def test_rota_da_ficha_registrada():
    import server
    assert "/api/locations/state" in {r.rule for r in server.app.url_map.iter_rules()}


def test_renomear_local_leva_quem_aponta_para_ele(cliviate):
    import server
    server._renomear_referencias_de_local("Cliviate", "Cliviate Velha")
    assert cliviate["locations"]["praça de cliviate"]["dentro_de"] == "Cliviate Velha"
    assert cliviate["lojas"]["forja de cliviate"]["local"] == "Cliviate Velha"
    assert cliviate["current_location"] == "Cliviate Velha"
