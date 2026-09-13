"""
test_tela_de_descanso.py

Duas coisas, que são a mesma coisa vista de lados diferentes.

1. A CURA INFINITA. short_rest() rolava nível/2 dados de vida e curava, mas
   não tirava nada da reserva que use_hit_die() controlava. Medido no commit
   anterior, guerreira de nível 5 (d10, CON +2, dados rolando o máximo), 5
   dados na reserva:

       descanso curto 1   vida  5 → 29   reserva 5/5   0 horas
       descanso curto 2   vida 29 → 53   reserva 5/5   0 horas
       descanso curto 3   vida 53 → 60   reserva 5/5   0 horas  ← nada gasto

   Nem a reserva descia, nem o relógio andava. O descanso longo tinha ganhado o limite de 24h para
   acabar exatamente com isso; o curto continuava sendo a porta dos fundos.

2. A TELA DE DESCANSO. No 5e quem decide quantos dados gastar é o jogador, um
   de cada vez. O mestre só abre o descanso (offer_rest); a tela gasta pelas
   mesmas funções do mestre (use_hit_die, short_rest, long_rest).
"""
import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


@pytest.fixture
def dados_maximos(monkeypatch):
    """Todo dado rola o máximo: as contas do teste ficam exatas."""
    monkeypatch.setattr(td.random, "randint", lambda a, b: b)


@pytest.fixture
def aria(campanha, povoar):
    # Guerreira de nível 5: d10, CON 14 (+2) → cada dado máximo cura 12.
    povoar(criar_ficha("Aria", grupo=True, vida=5, vida_max=60, nivel=5,
                       constituicao=14))
    ch = memory.campaign["characters"]["aria"]
    ch["sheet"]["hit_dice_remaining"] = 5
    return ch


@pytest.fixture
def grupo(aria, povoar):
    povoar(criar_ficha("Bram", grupo=True, vida=10, vida_max=30, nivel=3,
                       constituicao=10))
    memory.campaign["characters"]["bram"]["sheet"]["hit_dice_remaining"] = 3
    return memory.campaign["characters"]


def _reserva(ch):
    return td._reserva_de_dados(ch["sheet"])[0]


# ---------------------------------------------------------------------------
# 1. A cura infinita
# ---------------------------------------------------------------------------

def test_descanso_curto_gasta_da_reserva(aria, dados_maximos):
    td.short_rest("Aria")                    # nível 5 → até 2 dados
    assert _reserva(aria) == 3
    assert aria["sheet"]["vida_atual"] == 5 + 12 + 12


def test_descanso_curto_em_serie_para_de_curar_quando_a_reserva_esvazia(aria, dados_maximos):
    """O caso medido: três descansos seguidos não podem curar de graça."""
    aria["sheet"]["vida_max"] = 200           # teto alto: só a reserva limita
    for _ in range(3):
        td.short_rest("Aria")
    assert _reserva(aria) == 0
    vida = aria["sheet"]["vida_atual"]
    assert vida == 5 + 5 * 12, "curou mais do que os 5 dados permitem"

    saida = td.short_rest("Aria")
    assert aria["sheet"]["vida_atual"] == vida, "curou com a reserva vazia"
    assert "Sem dados de vida" in saida


def test_short_rest_e_use_hit_die_usam_a_MESMA_reserva(aria, dados_maximos):
    td.use_hit_die("Aria", 2)
    td.short_rest("Aria")
    assert _reserva(aria) == 1


def test_descanso_curto_para_quando_a_vida_enche(aria, dados_maximos):
    """Dado rolado com vida cheia é dado jogado fora — e é do jogador."""
    aria["sheet"]["vida_atual"] = 55          # falta 5: um dado basta
    td.short_rest("Aria")
    assert aria["sheet"]["vida_atual"] == 60
    assert _reserva(aria) == 4


def test_descanso_curto_com_zero_dados_so_passa_a_hora(aria):
    antes = td._agora_em_horas()
    td.short_rest("Aria", hit_dice=0)
    assert aria["sheet"]["vida_atual"] == 5
    assert _reserva(aria) == 5
    assert td._agora_em_horas() == antes + 1


def test_descanso_curto_passa_uma_hora_para_o_grupo_e_nao_por_pessoa(grupo):
    antes = td._agora_em_horas()
    td.short_rest("Aria", hit_dice=0)
    td.short_rest("Bram", hit_dice=0)
    assert td._agora_em_horas() == antes + 1


def test_descanso_curto_recusa_morto(aria):
    aria["status"] = "morto"
    assert td.short_rest("Aria").startswith("Erro:")
    assert _reserva(aria) == 5


def test_descanso_curto_recusa_em_combate(aria, povoar):
    povoar(criar_ficha("Goblin"))
    iniciar_combate(["Aria", "Goblin"])
    assert td.short_rest("Aria").startswith("Erro:")
    assert aria["sheet"]["vida_atual"] == 5


def test_dado_de_vida_recusa_em_combate(aria, povoar):
    povoar(criar_ficha("Goblin"))
    iniciar_combate(["Aria", "Goblin"])
    assert td.use_hit_die("Aria").startswith("Erro:")
    assert _reserva(aria) == 5


def test_dado_de_vida_com_vida_cheia_nao_gasta(aria):
    aria["sheet"]["vida_atual"] = 60
    assert td.use_hit_die("Aria").startswith("Nota:")
    assert _reserva(aria) == 5


def test_dado_de_vida_com_reserva_vazia_recusa(aria):
    aria["sheet"]["hit_dice_remaining"] = 0
    assert td.use_hit_die("Aria").startswith("Erro:")


def test_descanso_longo_devolve_so_metade_da_reserva(aria):
    """PHB: até metade do total de dados. Nível 5 → 2, não os 5."""
    aria["sheet"]["hit_dice_remaining"] = 0
    saida = td.long_rest("Aria")
    assert _reserva(aria) == 2
    assert "Dados de vida: 0 → 2/5" in saida


def test_descanso_longo_nao_passa_do_maximo(aria):
    """Com 4 de 5, metade seria 2 — mas só falta 1."""
    aria["sheet"]["hit_dice_remaining"] = 4
    td.long_rest("Aria")
    assert _reserva(aria) == 5


def test_descanso_longo_devolve_pelo_menos_um_dado(campanha, povoar):
    """Nível 1: metade de 1 arredonda para 0, e o mínimo é 1."""
    povoar(criar_ficha("Novato", grupo=True, vida=3, vida_max=12, nivel=1))
    ch = memory.campaign["characters"]["novato"]
    ch["sheet"]["hit_dice_remaining"] = 0
    td.long_rest("Novato")
    assert _reserva(ch) == 1


def test_duas_noites_para_encher_a_reserva(aria):
    """O custo de torrar a reserva aparece no dia seguinte."""
    aria["sheet"]["hit_dice_remaining"] = 0
    td.long_rest("Aria")
    assert _reserva(aria) == 2
    td.advance_time(24, "um dia de estrada")
    td.long_rest("Aria")
    assert _reserva(aria) == 4


def test_subir_de_nivel_da_um_dado_a_mais(aria):
    """Quem subia do 5 para o 6 continuava com 5 dados até dormir."""
    aria["sheet"].update({"xp": 14000, "hit_dice_remaining": 5})
    td.grant_xp("Aria", 0)
    assert aria["sheet"]["nivel"] == 6
    assert _reserva(aria) == 6


def test_reserva_gravada_acima_do_nivel_e_lida_como_o_maximo(aria):
    aria["sheet"]["hit_dice_remaining"] = 99
    assert td._reserva_de_dados(aria["sheet"]) == (5, 5)


def test_ficha_sem_contador_comeca_com_a_reserva_cheia(aria):
    aria["sheet"].pop("hit_dice_remaining")
    assert td._reserva_de_dados(aria["sheet"]) == (5, 5)


# ---------------------------------------------------------------------------
# 2. offer_rest — o mestre abre, o jogador decide
# ---------------------------------------------------------------------------

def test_offer_rest_abre_a_proposta(aria):
    saida = td.offer_rest("curto", "clareira")
    assert not saida.startswith(("Erro:", "Aviso:"))
    snap = td.rest_snapshot()
    assert snap["tem_descanso"] is True
    assert snap["descanso"]["tipo"] == "curto"
    assert "Não chame short_rest" in saida


def test_offer_rest_aceita_o_nome_em_ingles(aria):
    td.offer_rest("long")
    assert td.rest_snapshot()["descanso"]["tipo"] == "longo"


def test_offer_rest_tipo_invalido(aria):
    assert td.offer_rest("soneca").startswith("Erro:")
    assert td.rest_snapshot()["tem_descanso"] is False


def test_offer_rest_recusa_em_combate(aria, povoar):
    povoar(criar_ficha("Goblin"))
    iniciar_combate(["Aria", "Goblin"])
    assert td.offer_rest("curto").startswith("Erro:")


def test_offer_rest_repetido_nao_reabre(aria):
    td.offer_rest("curto")
    id1 = td.rest_snapshot()["descanso"]["id"]
    assert td.offer_rest("curto").startswith("Nota:")
    assert td.rest_snapshot()["descanso"]["id"] == id1


def test_o_id_nao_se_repete_depois_de_concluir(aria):
    """
    O id diz à tela se ela já abriu por esta proposta. Se viesse da proposta
    (apagada ao concluir), o próximo descanso teria o mesmo id e a tela nunca
    mais abriria sozinha.
    """
    td.offer_rest("curto")
    id1 = td.rest_snapshot()["descanso"]["id"]
    td.rest_action("concluir")
    td.offer_rest("curto")
    assert td.rest_snapshot()["descanso"]["id"] != id1


def test_offer_rest_longo_avisa_quem_ainda_nao_pode(aria):
    aria["sheet"]["ultimo_descanso_longo"] = td._agora_em_horas() - 10
    saida = td.offer_rest("longo")
    assert "Aria (faltam 14h)" in saida


def test_iniciativa_interrompe_o_descanso(aria, povoar):
    """Emboscada no acampamento: a tela não pode reabrir depois da luta."""
    povoar(criar_ficha("Goblin"))
    td.offer_rest("curto")
    td.roll_initiative("Aria, Goblin")
    assert td.rest_snapshot()["tem_descanso"] is False


def test_offer_rest_esta_no_catalogo_do_agente():
    assert "offer_rest" in {f.__name__ for f in td.DND_TOOLS}


# ---------------------------------------------------------------------------
# 3. rest_action — o que a tela chama
# ---------------------------------------------------------------------------

def test_dado_na_tela_gasta_um_e_anota(aria, dados_maximos):
    td.offer_rest("curto")
    r = td.rest_action("dado", char="Aria")
    assert r["ok"] is True
    assert _reserva(aria) == 4
    p = next(x for x in r["snapshot"]["grupo"] if x["nome"] == "Aria")
    assert p["gastos_agora"] == 1
    assert p["vida_atual"] == 17


def test_dado_sem_descanso_aberto_e_recusado(aria):
    r = td.rest_action("dado", char="Aria")
    assert r["ok"] is False
    assert _reserva(aria) == 5


def test_dado_no_descanso_longo_e_recusado(aria):
    td.offer_rest("longo")
    r = td.rest_action("dado", char="Aria")
    assert r["ok"] is False
    assert _reserva(aria) == 5


def test_dado_recusado_nao_conta_como_gasto(aria):
    aria["sheet"]["vida_atual"] = 60
    td.offer_rest("curto")
    r = td.rest_action("dado", char="Aria")
    assert r["ok"] is False
    assert r["snapshot"]["descanso"]["com_gastos"] is False


def test_cancelar_sem_gasto_fecha_o_descanso(aria):
    antes = td._agora_em_horas()
    td.offer_rest("curto")
    r = td.rest_action("cancelar")
    assert r["ok"] is True
    assert r["snapshot"]["tem_descanso"] is False
    assert td._agora_em_horas() == antes, "cancelar não descansa"


def test_cancelar_depois_de_gastar_dado_e_recusado(aria):
    """Cancelar apagaria a hora que pagou pela cura: a cura infinita pela tela."""
    td.offer_rest("curto")
    td.rest_action("dado", char="Aria")
    r = td.rest_action("cancelar")
    assert r["ok"] is False
    assert r["snapshot"]["tem_descanso"] is True


def test_concluir_curto_passa_a_hora_uma_vez_e_nao_gasta_de_novo(grupo, dados_maximos):
    antes = td._agora_em_horas()
    td.offer_rest("curto")
    td.rest_action("dado", char="Aria")
    r = td.rest_action("concluir")

    assert r["ok"] is True
    assert td._agora_em_horas() == antes + 1
    assert _reserva(grupo["aria"]) == 4, "concluir gastou dado que o jogador não pediu"
    assert _reserva(grupo["bram"]) == 3
    assert r["snapshot"]["tem_descanso"] is False
    assert "Aria: 1 dado" in r["message"]


def test_concluir_longo_descansa_quem_pode_e_diz_quem_nao(grupo):
    grupo["bram"]["sheet"]["ultimo_descanso_longo"] = td._agora_em_horas() - 20
    grupo["aria"]["sheet"]["hit_dice_remaining"] = 0
    td.offer_rest("longo")
    r = td.rest_action("concluir")

    assert r["ok"] is True
    assert grupo["aria"]["sheet"]["vida_atual"] == 60
    assert grupo["bram"]["sheet"]["vida_atual"] == 10
    assert "Não puderam: Bram" in r["message"]


def test_concluir_longo_sem_ninguem_apto_mantem_a_tela(aria):
    aria["sheet"]["ultimo_descanso_longo"] = td._agora_em_horas() - 2
    td.offer_rest("longo")
    r = td.rest_action("concluir")
    assert r["ok"] is False
    assert r["snapshot"]["tem_descanso"] is True, "sumiu sem ninguém ter descansado"


def test_acao_desconhecida(aria):
    td.offer_rest("curto")
    r = td.rest_action("dormir_de_graca", char="Aria")
    assert r["ok"] is False
    assert _reserva(aria) == 5


def test_a_tela_passa_pelas_MESMAS_funcoes_do_mestre(grupo, monkeypatch):
    """Mesmo contrato das telas de loja e nível: nenhuma regra própria."""
    vistas = []

    def espiar(nome, real):
        def _wrap(*a, _n=nome, _r=real, **k):
            vistas.append(_n)
            return _r(*a, **k)
        return _wrap

    for nome in ("use_hit_die", "short_rest", "long_rest"):
        monkeypatch.setattr(td, nome, espiar(nome, getattr(td, nome)))

    td.offer_rest("curto")
    td.rest_action("dado", char="Aria")
    td.rest_action("concluir")
    td.offer_rest("longo")
    td.rest_action("concluir")

    assert "use_hit_die" in vistas
    assert "short_rest" in vistas
    assert "long_rest" in vistas


# ---------------------------------------------------------------------------
# 4. O snapshot
# ---------------------------------------------------------------------------

def test_snapshot_explica_por_que_o_dado_esta_travado(grupo):
    grupo["aria"]["sheet"]["hit_dice_remaining"] = 0
    grupo["bram"]["sheet"]["vida_atual"] = 30
    snap = {p["nome"]: p for p in td.rest_snapshot()["grupo"]}
    assert snap["Aria"]["bloqueio_dado"] == "sem dados na reserva"
    assert snap["Bram"]["bloqueio_dado"] == "vida no máximo"


def test_snapshot_diz_quantos_dados_o_longo_devolve(aria):
    """A conta da metade fica no motor; o cartão só mostra."""
    aria["sheet"]["hit_dice_remaining"] = 1
    p = td.rest_snapshot()["grupo"][0]
    assert p["dados_no_longo"] == 2
    aria["sheet"]["hit_dice_remaining"] = 5
    assert td.rest_snapshot()["grupo"][0]["dados_no_longo"] == 0


def test_snapshot_usa_o_teto_da_exaustao(aria):
    aria["sheet"]["exaustao"] = 4
    p = td.rest_snapshot()["grupo"][0]
    assert p["teto"] == 30
    assert "metade" in p["exaustao_efeito"]


def test_snapshot_mostra_quantas_horas_faltam_para_o_longo(aria):
    aria["sheet"]["ultimo_descanso_longo"] = td._agora_em_horas() - 18
    p = td.rest_snapshot()["grupo"][0]
    assert p["pode_longo"] is False and p["faltam_horas"] == 6


def test_grupo_vazio_nao_quebra(campanha):
    snap = td.rest_snapshot()
    assert snap["grupo"] == [] and snap["tem_descanso"] is False
    assert td.offer_rest("curto").startswith("Erro:")


def test_as_rotas_do_descanso_estao_registradas():
    import server
    rotas = {r.rule for r in server.app.url_map.iter_rules()}
    assert "/api/rest/state" in rotas
    assert "/api/rest/action" in rotas
