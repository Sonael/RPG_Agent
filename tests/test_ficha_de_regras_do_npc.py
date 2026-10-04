"""
test_ficha_de_regras_do_npc.py

Na campanha Teste3 o guerreiro Kaelen Vane desafiou o grupo para um duelo, e
o golpe não letal o derrubou: 0 PV, nocauteado e estável, acordando com 1
PV em 1d4 horas (é a regra). Mas o jogador só via isso abrindo "Editar
personagem": a ficha do personagem dizia "— estabilizado" no título e mais
nada, e o Estradivarius, arquimago com ficha D&D, também não mostrava PV,
CA ou condição em lugar nenhum fora do editor.

Agora a ficha do personagem tem a seção "Ficha" para quem tem ficha D&D
(rpg/personagens._ficha_de_regras), e o título fala "nocauteado (estável)".
"""
import pytest

from rpg import memory, personagens, tools_dnd as td

from conftest import criar_ficha


@pytest.fixture
def mesa(campanha, povoar):
    memory.campaign["dnd_mode"] = True
    memory.campaign["relogio"] = {"dia": 3, "hora": 9}
    povoar(criar_ficha("Alden", grupo=True),
           criar_ficha("Kaelen Vane", vida=12, ca=18, forca=16, destreza=12, arma="espada longa"),
           criar_ficha("Estradivarius", classe="mago", nivel=20, vida=139, ca=12, inteligencia=20))
    memory.campaign["characters"]["bram"] = {"name": "Bram", "description": "Estalajadeiro.",
                                             "status": "vivo", "sheet": None}
    return memory.campaign


def _nocautear(horas_para_acordar=1):
    k = memory.campaign["characters"]["kaelen vane"]
    k["status"] = "estabilizado"
    k["sheet"]["vida_atual"] = 0
    k["sheet"]["acorda_hora"] = td._agora_em_horas() + horas_para_acordar
    return k


def test_o_nocauteado_mostra_o_estado_e_quando_acorda(mesa):
    _nocautear(1)
    f = personagens.ficha("Kaelen Vane")
    r = f["regras"]
    assert f["status_texto"] == "nocauteado (estável)"
    assert r["vida"] == {"atual": 0, "max": 12, "temp": 0} and r["ca"] == 18
    assert "Nocauteado e estável" in r["estado"] and "em cerca de 1 h" in r["estado"]
    assert "Espada Longa" in " ".join(r["ataques"]).title()


@pytest.mark.parametrize("status", ["estabilizado", "inconsciente", "dormindo"])
def test_desacordado_nao_tem_falar_com(mesa, status):
    """O botão ficava ativo para o nocauteado: o mestre recebia 'Quero falar com' um desmaiado."""
    from rpg import locais
    k = memory.campaign["characters"]["kaelen vane"]
    k["status"], k["local"] = status, "Praça"
    memory.campaign["current_location"] = "Praça"
    memory.campaign.setdefault("locations", {})["praça"] = {"name": "Praça", "description": ""}
    assert personagens.ficha("Kaelen Vane")["pode_falar"] is False
    pessoa = next(p for p in locais.ficha("Praça")["pessoas"] if p["nome"] == "Kaelen Vane")
    assert pessoa["pode_falar"] is False
    k["status"] = "inimigo"
    assert personagens.ficha("Kaelen Vane")["pode_falar"] is True


def test_passou_da_hora_acorda_a_qualquer_momento(mesa):
    _nocautear(0)
    assert "a qualquer momento" in personagens.ficha("Kaelen Vane")["regras"]["estado"]


def test_o_motor_acorda_e_a_ficha_acompanha(mesa):
    _nocautear(1)
    td.advance_time(2)
    f = personagens.ficha("Kaelen Vane")
    assert f["regras"]["vida"]["atual"] == 1 and f["regras"]["estado"] == ""


def test_atributos_condicoes_e_titulo(mesa):
    e = memory.campaign["characters"]["estradivarius"]
    e["sheet"]["condicoes"] = [{"nome": "Invisível", "duracao": 10}]
    r = personagens.ficha("Estradivarius")["regras"]
    assert r["titulo"] == "Mago nível 20"
    atributos = {a["sigla"]: (a["valor"], a["mod"]) for a in r["atributos"]}
    assert atributos["INT"] == (20, 5) and len(atributos) == 6
    assert r["condicoes"] == [{"nome": "Invisível", "duracao": 10}]


def test_quem_e_do_grupo_ganha_o_atalho_para_a_ficha_completa(mesa):
    assert personagens.ficha("Alden")["regras"] == {"ficha_completa": True}


def test_sem_ficha_nao_tem_secao(mesa):
    assert personagens.ficha("Bram")["regras"] is None


def test_campanha_narrativa_nao_tem_secao(campanha):
    """Sem as regras (e sem ficha nenhuma, que as ligaria), não há o que mostrar."""
    memory.campaign["dnd_mode"] = False
    memory.campaign["campaign_type"] = "fantasia"
    memory.campaign["characters"]["bram"] = {"name": "Bram", "status": "vivo", "sheet": None}
    assert personagens.ficha("Bram")["regras"] is None
