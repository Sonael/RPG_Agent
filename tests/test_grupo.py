"""
test_grupo.py

Visão geral do grupo (rpg/grupo.py): os heróis lado a lado, com o que pesa
para decidir descanso e divisão de itens.
"""
import pytest

from rpg import grupo, memory, tools_dnd as td

from conftest import criar_ficha


@pytest.fixture
def trio(campanha, povoar):
    memory.campaign["relogio"] = {"dia": 4, "hora": 20}
    thorn = criar_ficha("Thorn", grupo=True, vida=12, vida_max=30, forca=16, nivel=3,
                        hit_dice_remaining=2)
    lyra = criar_ficha("Lyra", grupo=True, vida=21, vida_max=21, forca=8, nivel=3,
                       hit_dice_remaining=3)
    helena = criar_ficha("Helena", grupo=True, vida=9, vida_max=20, nivel=3, mana=4, forca=10,
                         hit_dice_remaining=0, exaustao=1)
    helena["sheet"]["mana_max"] = 12
    # Helena dormiu há 10 horas: o descanso longo só volta daqui a 14.
    helena["sheet"]["ultimo_descanso_longo"] = 4 * 24 + 10
    # Lyra (FOR 8, capacidade 54,4 kg, sobrecarregada acima de 27,2) leva 24 kg.
    lyra["inventario"] = [{"nome": "Baú de Ferramentas", "qtd": 1, "descricao": "", "peso": 24}]
    thorn["inventario"] = [{"nome": "Corda", "qtd": 1, "descricao": "", "peso": 4.5}]
    thorn["sheet"]["xp"] = 900
    thorn["sheet"]["xp_proximo"] = 900
    povoar(thorn, lyra, helena)
    return campanha


def _heroi(snap, nome):
    return next(h for h in snap["herois"] if h["nome"] == nome)


def test_um_cartao_por_membro_do_grupo_com_ficha(trio, povoar):
    povoar(criar_ficha("Goblin"))                     # inimigo não entra
    memory.campaign["characters"]["brom"] = {"name": "Brom", "sheet": None}
    snap = grupo.group_snapshot()
    assert [h["nome"] for h in snap["herois"]] == ["Thorn", "Lyra", "Helena"]
    assert snap["hora"] == "Dia 4, 20h (noite)"
    assert snap["em_combate"] is False


def test_companheiro_sem_ficha_aparece_numa_lista_propria(trio, povoar):
    """
    O companheiro que o mestre recrutou pela narrativa e nunca ficou com
    atributos sumia da visão geral e da barra lateral, como se não estivesse
    no grupo. Ele volta numa lista separada, com o que existe dele.
    """
    memory.campaign["characters"]["brom"] = {
        "name": "Brom", "sheet": None, "party_member": True,
        "description": "Ferreiro de Oakhaven, veio pela dívida com Thorn.",
        "status": "vivo",
    }
    memory.campaign["party"].append({"name": "Brom", "role": "Ferreiro", "notes": ""})
    povoar(criar_ficha("Goblin"))                     # inimigo não entra
    # NPC salvo só com save_character: sem ficha, mas também sem ser do grupo.
    memory.campaign["characters"]["ivo"] = {
        "name": "Pescador Ivo", "sheet": None, "description": "Conhece a foz."}

    snap = grupo.group_snapshot()
    assert [h["nome"] for h in snap["herois"]] == ["Thorn", "Lyra", "Helena"]
    assert snap["sem_ficha"] == [{
        "nome": "Brom", "papel": "Ferreiro", "morto": False,
        "descricao": "Ferreiro de Oakhaven, veio pela dívida com Thorn.",
    }]


def test_sem_ficha_nao_entra_no_resumo_de_descanso(trio):
    """Quem não tem ficha não tem vida nem dado de vida para entrar na conta."""
    memory.campaign["characters"]["brom"] = {
        "name": "Brom", "sheet": None, "party_member": True, "status": "vivo"}
    snap = grupo.group_snapshot()
    assert "Brom" not in snap["resumo"]["descanso"]
    assert "Brom" not in (snap["resumo"]["carga"] or "")


def test_quem_tem_ficha_nunca_cai_na_lista_sem_ficha(trio):
    snap = grupo.group_snapshot()
    assert snap["sem_ficha"] == []


def test_vida_mana_e_dados_de_vida(trio):
    helena = _heroi(grupo.group_snapshot(), "Helena")
    assert helena["vida"]["atual"] == 9 and helena["vida"]["max"] == 20
    assert helena["vida"]["pct"] == 45
    assert helena["mana"] == {"atual": 4, "max": 12, "pct": 33}
    assert helena["dados_de_vida"]["restantes"] == 0 and helena["dados_de_vida"]["max"] == 3
    assert helena["dados_de_vida"]["no_longo"] == 1
    assert helena["precisa"] == ["vida 9/20", "mana 4/12", "exaustão 1"]


def test_teto_da_exaustao_conta_como_vida_cheia(trio):
    """Exaustão 4 corta o máximo pela metade: 10/20 é a vida cheia possível."""
    s = memory.campaign["characters"]["lyra"]["sheet"]
    s["exaustao"] = 4
    s["vida_atual"] = 10
    s["vida_max"] = 20
    lyra = _heroi(grupo.group_snapshot(), "Lyra")
    assert lyra["vida"]["teto"] == 10
    assert "vida 10/20" not in lyra["precisa"]
    assert lyra["descanso"]["curto_ajuda"] is False


def test_descanso_de_cada_um(trio):
    snap = grupo.group_snapshot()
    thorn, lyra, helena = (_heroi(snap, n) for n in ("Thorn", "Lyra", "Helena"))
    assert thorn["descanso"] == {"pode_longo": True, "faltam_horas": 0, "curto_ajuda": True}
    assert lyra["descanso"]["curto_ajuda"] is False, "vida cheia: o curto não adianta"
    assert helena["descanso"]["pode_longo"] is False and helena["descanso"]["faltam_horas"] == 14
    assert helena["descanso"]["curto_ajuda"] is False, "sem dado de vida: o curto não cura"


def test_resumo_do_descanso(trio):
    texto = grupo.group_snapshot()["resumo"]["descanso"]
    assert texto == ("O descanso curto ajuda Thorn. Helena sem dado de vida: só o longo cura. "
                     "Descanso longo: Thorn e Lyra já podem; Helena só daqui a 14h.")


def test_resumo_sem_feridos_e_em_combate(trio):
    for nome in ("thorn", "helena"):
        s = memory.campaign["characters"][nome]["sheet"]
        s["vida_atual"] = s["vida_max"]
        s["mana_atual"] = s["mana_max"]
        s["exaustao"] = 0
    assert grupo.group_snapshot()["resumo"]["descanso"] == "Ninguém precisa de descanso agora."
    memory.campaign["combat_state"]["is_active"] = True
    assert grupo.group_snapshot()["resumo"]["descanso"].startswith("Em combate")


def test_carga_folga_e_perto_do_limite(trio):
    snap = grupo.group_snapshot()
    lyra = _heroi(snap, "Lyra")
    assert lyra["carga"]["capacidade"] == 54.4
    assert lyra["carga"]["limite_sobrecarga"] == 27.2
    assert lyra["carga"]["folga_kg"] == 3.2
    assert lyra["carga"]["perto_do_limite"] is True and lyra["carga"]["estado"] == "livre"
    thorn = _heroi(snap, "Thorn")
    assert thorn["carga"]["folga_kg"] == 50.0 and thorn["carga"]["perto_do_limite"] is False
    resumo = snap["resumo"]
    assert resumo["mais_folga"] == "Thorn"
    assert resumo["carga"].startswith("Mais folga para carregar: Thorn (50 kg), Helena (34 kg), Lyra (3.2 kg).")
    assert "Perto do limite: Lyra." in resumo["carga"]


def test_sobrecarregado_aparece_no_resumo(trio):
    memory.campaign["characters"]["lyra"]["inventario"][0]["peso"] = 30
    snap = grupo.group_snapshot()
    assert _heroi(snap, "Lyra")["carga"]["estado"] == "sobrecarregado"
    assert _heroi(snap, "Lyra")["carga"]["folga_kg"] == 0
    assert "Sobrecarregado: Lyra." in snap["resumo"]["carga"]


def test_nivel_pendente(trio):
    snap = grupo.group_snapshot()
    assert _heroi(snap, "Thorn")["nivel_pendente"] is True
    assert _heroi(snap, "Thorn")["pode_subir"] is True
    assert snap["resumo"]["nivel_pendente"] == ["Thorn"]


def test_condicoes_concentracao_e_caido(trio):
    s = memory.campaign["characters"]["thorn"]["sheet"]
    s["condicoes"] = [{"nome": "envenenado", "duracao": 2}]
    s["concentracao"] = {"magia": "Bênção"}
    memory.campaign["characters"]["lyra"]["sheet"]["vida_atual"] = 0
    snap = grupo.group_snapshot()
    thorn = _heroi(snap, "Thorn")
    assert thorn["condicoes"] == [{"nome": "envenenado", "duracao": 2}]
    assert thorn["concentracao"] == "Bênção"
    lyra = _heroi(snap, "Lyra")
    assert lyra["precisa"][0] == "caído" and lyra["testes_de_morte"] is not None
    assert lyra["descanso"]["curto_ajuda"] is False


def test_morto_nao_entra_nas_contas(trio):
    memory.campaign["characters"]["helena"]["status"] = "morto"
    snap = grupo.group_snapshot()
    helena = _heroi(snap, "Helena")
    assert helena["morto"] is True and helena["precisa"] == []
    assert "Helena" not in snap["resumo"]["descanso"]
    assert "Helena" not in snap["resumo"]["carga"]


def test_grupo_vazio(campanha):
    snap = grupo.group_snapshot()
    assert snap["herois"] == []
    assert snap["resumo"]["descanso"] == "Ninguém precisa de descanso agora."
    assert snap["resumo"]["carga"] == ""


def test_rota(trio):
    import server
    assert "/api/party/overview" in {r.rule for r in server.app.url_map.iter_rules()}
    with server.app.test_request_context("/api/party/overview"):
        corpo = server.party_overview_route.__wrapped__().get_json()
    assert [h["nome"] for h in corpo["herois"]] == ["Thorn", "Lyra", "Helena"]
