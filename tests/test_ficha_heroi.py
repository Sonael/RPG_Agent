"""
test_ficha_heroi.py

A ficha de leitura de um herói do grupo (tools_dnd.hero_snapshot): tudo o que
o jogador precisa para decidir e rolar, com as contas das mesmas funções que
o motor usa para resolver. A tela não soma nada.
"""
import re

import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha


@pytest.fixture
def grupo(campanha, povoar, monkeypatch):
    # Espada longa 1d8, sem ir à rede.
    monkeypatch.setattr(td, "_fetch_weapon_data",
                        lambda arma: {"espada longa": (1, 8), "arco longo": (1, 8)}.get(arma.lower()))
    return povoar(
        criar_ficha("Alden", grupo=True, nivel=5, forca=16, destreza=14, sabedoria=12,
                    proficiencia=3, xp=6600, xp_proximo=14000),
        criar_ficha("Lyra", grupo=True, classe="ladino", destreza=18, arma="arco longo"),
        criar_ficha("Goblin", arma="cimitarra"),
    )


def _p(nome):
    return td.hero_snapshot(nome)["personagem"]


def test_so_membro_do_grupo_com_ficha(grupo):
    assert td.hero_snapshot("Goblin") == {"tem_personagem": False,
                                          "grupo": ["Alden", "Lyra"], "personagem": None}
    assert td.hero_snapshot("")["personagem"] is None
    assert _p("alden")["nome"] == "Alden"


def test_cabecalho_e_recursos(grupo):
    p = _p("Alden")
    assert (p["classe"], p["nivel"], p["proficiencia"]) == ("guerreiro", 5, "+3")
    assert p["iniciativa"] == "+2"
    assert p["dados_de_vida"] == {"restantes": 5, "max": 5, "dado": "d10"}
    assert p["vida"] == {"atual": 30, "max": 30, "teto": 30, "temp": 0}
    assert p["pode_subir"] is False
    assert 0 <= p["xp_pct"] <= 100


def test_salvaguardas_somam_proficiencia_so_nas_da_classe(grupo):
    atributos = {a["sigla"]: a for a in _p("Alden")["atributos"]}
    assert atributos["FOR"]["mod"] == "+3"
    assert atributos["FOR"]["salvaguarda"] == "+6" and atributos["FOR"]["salvaguarda_proficiente"]
    assert atributos["DES"]["salvaguarda"] == "+2" and not atributos["DES"]["salvaguarda_proficiente"]


def test_pericias_e_percepcao_passiva(grupo):
    pericias = {x["nome"]: x for x in _p("Alden")["pericias"]}
    assert "lidar com animais" not in pericias, "o apelido aparecia duplicado"
    assert pericias["atletismo"]["bonus"] == "+6" and pericias["atletismo"]["proficiente"]
    assert pericias["arcana"]["bonus"] == "+0" and not pericias["arcana"]["proficiente"]
    # Percepção é da lista do guerreiro: SAB +1, proficiência +3.
    assert pericias["percepção"]["bonus"] == "+4"
    assert _p("Alden")["percepcao_passiva"] == 14


def test_bonus_da_pericia_e_o_do_make_skill_check(grupo, monkeypatch):
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda a, d: (10, "d20=10"))
    saida = td.make_skill_check("Alden", "sabedoria", 30, skill="percepção")
    bonus = int(next(x for x in _p("Alden")["pericias"] if x["nome"] == "percepção")["bonus"])
    assert f"**{10 + bonus}**" in saida, saida
    assert "+3(prof)" in saida
    # Sem perícia, só o atributo.
    assert "**11**" in td.make_skill_check("Alden", "sabedoria", 30)


def test_ataque_com_as_contas_do_attack_roll(grupo):
    ataque = _p("Alden")["ataques"][0]
    assert ataque["arma"] == "espada longa"
    assert (ataque["atributo"], ataque["acerto"], ataque["dano"]) == ("FOR", "+6", "1d8+3")
    assert ataque["tipo"] == "cortante" and ataque["alcance"] == "corpo a corpo"


def test_arquearia_e_critico_aprimorado_aparecem(grupo):
    lyra = memory.campaign["characters"]["lyra"]
    lyra["sheet"]["feature_choices"] = {"Estilo de Combate": "Arquearia"}
    ataque = _p("Lyra")["ataques"][0]
    assert ataque["atributo"] == "DES" and ataque["alcance"] == "à distância"
    assert ataque["acerto"] == "+8"          # DES +4, prof +2, Arquearia +2
    assert ataque["dano"] == "1d8+4"
    assert "Arquearia: +2 no acerto" in ataque["notas"]


def test_estado_exaustao_condicoes_defesas(grupo):
    s = memory.campaign["characters"]["alden"]["sheet"]
    s.update({"exaustao": 4, "vida_atual": 0, "death_saves_falhas": 1, "vida_temp": 5,
              "condicoes": [{"nome": "envenenado", "duracao": 3}, "caído"],
              "resistencias": ["fogo"], "concentracao": {"magia": "Bênção"}})
    p = _p("Alden")
    assert p["vida"]["teto"] == 15 and p["vida"]["temp"] == 5
    assert p["testes_de_morte"] == {"sucessos": 0, "falhas": 1}
    assert p["condicoes"] == [{"nome": "envenenado", "duracao": 3}, {"nome": "caído", "duracao": 0}]
    assert p["defesas"]["resistencias"] == ["fogo"]
    assert p["concentracao"] == "Bênção"


def test_pode_subir_e_escolhas(grupo):
    s = memory.campaign["characters"]["alden"]["sheet"]
    s["xp"] = 14000
    assert _p("Alden")["pode_subir"] is True


def test_nao_muda_a_ficha(grupo):
    import copy
    antes = copy.deepcopy(memory.campaign["characters"])
    td.hero_snapshot("Alden")
    assert memory.campaign["characters"] == antes


def test_rota_registrada(grupo):
    import server
    assert "/api/heroes/sheet" in {r.rule for r in server.app.url_map.iter_rules()}
    with server.app.test_request_context("/api/heroes/sheet?personagem=Lyra"):
        corpo = server.hero_sheet_route.__wrapped__().get_json()
    assert corpo["personagem"]["nome"] == "Lyra"


def test_sem_emoji_nos_rotulos(grupo):
    texto = repr(td.hero_snapshot("Alden"))
    assert not re.search("[\U0001F300-\U0001FAFF☀-➿]", texto)
