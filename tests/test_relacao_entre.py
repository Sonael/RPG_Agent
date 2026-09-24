"""
test_relacao_entre.py
A relação de cada um com cada um (rpg/entre.py) e a linha que a escreve no
fechamento do turno.

O caso que deu origem a isto veio da partida:

    "Helena: atitude +5 → -5 (neutro) — Helena odiou a sugestão e o controle
     velado de Selene"

Helena não esfriou com o grupo; esfriou com SELENE. E a mesma partida tinha o
contrário: uma amizade de infância narrada em cena que continuou valendo zero,
porque não havia onde escrevê-la.
"""
import pytest

from rpg import entre, epilogo, memory


@pytest.fixture
def campanha(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "save_campaign", lambda *a, **k: None)
    memory.campaign.clear()
    memory.campaign.update({
        "name": "Teste",
        "chapter": 2,
        "protagonist": "Sonael",
        "current_location": "Valenport",
        "party": [{"name": "Sonael", "role": "mago", "notes": ""},
                  {"name": "Helena", "role": "guerreira", "notes": ""},
                  {"name": "Selene", "role": "clériga", "notes": ""}],
        "characters": {
            "sonael": {"name": "Sonael", "status": "vivo"},
            "helena": {"name": "Helena", "status": "vivo"},
            "selene": {"name": "Selene", "status": "vivo"},
        },
        "locations": {}, "events": [], "quests": {}, "flags": {},
        "conversation_history": [],
    })
    return memory.campaign


# ---------------------------------------------------------------------------
# O modelo
# ---------------------------------------------------------------------------

def test_relacao_e_direcional(campanha):
    entre.ajustar("Helena", "Selene", -20, "o controle velado")
    assert entre.de_quem("Helena")[0]["valor"] == -20
    # Selene não sentiu nada: quem se incomodou foi Helena.
    assert entre.de_quem("Selene") == []


def test_o_que_sente_nao_mexe_na_atitude_com_o_grupo(campanha):
    campanha["characters"]["helena"]["atitude"] = 5
    campanha["characters"]["helena"]["lealdade"] = 90
    entre.ajustar("Helena", "Selene", -30, "briga")
    assert campanha["characters"]["helena"]["atitude"] == 5
    assert campanha["characters"]["helena"]["lealdade"] == 90


def test_o_valor_acumula_e_guarda_o_porque(campanha):
    entre.ajustar("Helena", "Selene", -20, "o controle velado")
    entre.ajustar("Helena", "Selene", -15, "de novo, na frente de todos")
    r = entre.de_quem("Helena")[0]
    assert r["valor"] == -35
    assert r["rotulo"] == "atrito"
    assert [h["delta"] for h in r["historico"]] == [-15, -20]
    assert "na frente de todos" in r["historico"][0]["motivo"]
    assert r["historico"][0]["capitulo"] == 2


def test_definir_poe_o_valor_exato(campanha):
    entre.ajustar("Selene", "Sonael", 30, "amigos de infância")
    entre.definir("Selene", "Sonael", 75, "corrigido pelo jogador")
    assert entre.de_quem("Selene")[0]["valor"] == 75


def test_faixas(campanha):
    assert entre.faixa(-80) == "ódio"
    assert entre.faixa(-25) == "atrito"
    assert entre.faixa(0) == "indiferença"
    assert entre.faixa(35) == "amizade"
    assert entre.faixa(90) == "inseparáveis"


def test_nao_passa_de_cem(campanha):
    entre.ajustar("Helena", "Selene", 100, "")
    entre.ajustar("Helena", "Selene", 100, "")
    assert entre.de_quem("Helena")[0]["valor"] == 100


def test_ninguem_tem_relacao_consigo_mesmo(campanha):
    assert entre.ajustar("Helena", "Helena", 10, "").startswith("Erro:")


def test_desconhecido_nao_entra(campanha):
    assert entre.ajustar("Helena", "Fantasma", 10, "").startswith("Erro:")
    assert entre.ajustar("Fantasma", "Helena", 10, "").startswith("Erro:")


def test_apagar_a_pessoa_tira_a_relacao_da_tela(campanha):
    entre.ajustar("Helena", "Selene", 40, "")
    del campanha["characters"]["selene"]
    assert entre.de_quem("Helena") == []


def test_remover(campanha):
    entre.ajustar("Helena", "Selene", 40, "")
    assert not entre.remover("Helena", "Selene").startswith("Erro:")
    assert entre.de_quem("Helena") == []
    assert entre.remover("Helena", "Selene").startswith("Erro:")


def test_ordem_pela_forca_da_relacao(campanha):
    entre.ajustar("Sonael", "Helena", 15, "")
    entre.ajustar("Sonael", "Selene", -60, "")
    assert [r["nome"] for r in entre.de_quem("Sonael")] == ["Selene", "Helena"]


def test_linha_para_o_mestre_so_traz_o_que_pesa(campanha):
    entre.ajustar("Helena", "Selene", -35, "")
    entre.ajustar("Helena", "Sonael", 5, "")      # indiferença: não entra
    linha = entre.para_o_mestre("Helena")
    assert "Selene: atrito (-35)" in linha
    assert "Sonael" not in linha


def test_sem_relacao_forte_nao_gasta_linha(campanha):
    entre.ajustar("Helena", "Sonael", 5, "")
    assert entre.para_o_mestre("Helena") == ""


# ---------------------------------------------------------------------------
# A linha no fechamento do turno
# ---------------------------------------------------------------------------

NARRACAO = ("Selene sugere que todos durmam na casa dela, e Helena cruza os braços "
            "sem esconder o desagrado. Sonael observa as duas em silêncio.")


def _bloco(*linhas):
    return NARRACAO + "\n\n[[registro]]\n" + "\n".join(linhas) + "\n[[/registro]]"


def test_a_linha_muda_a_relacao(campanha):
    _, relatorio = epilogo.processar(
        _bloco("relação: Helena → Selene -20 — odiou o controle velado"))
    assert entre.de_quem("Helena")[0]["valor"] == -20
    assert entre.de_quem("Helena")[0]["motivo"] == "odiou o controle velado"
    assert any("relacao" in f for f in relatorio["feitos"])


def test_seta_dos_dois_lados(campanha):
    epilogo.processar(_bloco("relação: Selene ↔ Sonael +30 — amigos de infância"))
    assert entre.de_quem("Selene")[0]["valor"] == 30
    assert entre.de_quem("Sonael")[0]["valor"] == 30


@pytest.mark.parametrize("seta", ["->", "→", "<->"])
def test_setas_aceitas(campanha, seta):
    _, relatorio = epilogo.processar(_bloco(f"relação: Helena {seta} Selene -10 — atrito"))
    assert relatorio["feitos"], relatorio["recusados"]


def test_nome_que_nao_aparece_na_cena_e_recusado(campanha):
    campanha["characters"]["brom"] = {"name": "Brom", "status": "vivo"}
    _, relatorio = epilogo.processar(_bloco("relação: Helena → Brom -20 — ciúme"))
    assert entre.de_quem("Helena") == []
    assert any("narração" in r for r in relatorio["recusados"])


def test_passo_grande_demais_e_recusado(campanha):
    _, relatorio = epilogo.processar(_bloco("relação: Helena → Selene -90 — ódio instantâneo"))
    assert entre.de_quem("Helena") == []
    assert any("passo maior" in r for r in relatorio["recusados"])


def test_linha_torta_nao_derruba_o_turno(campanha):
    limpo, relatorio = epilogo.processar(_bloco("relação: Helena gosta menos de Selene"))
    assert "Selene sugere" in limpo
    assert relatorio["recusados"]


def test_teto_de_duas_relacoes_por_turno(campanha):
    limpo, relatorio = epilogo.processar(_bloco(
        "relação: Helena → Selene -10 — a sugestão",
        "relação: Selene → Helena -5 — a cara fechada",
        "relação: Sonael → Helena +10 — achou graça"))
    assert entre.de_quem("Sonael") == []
    assert len([f for f in relatorio["feitos"] if "relacao" in f]) == 2


def test_o_bloco_sai_da_tela(campanha):
    limpo, _ = epilogo.processar(_bloco("relação: Helena → Selene -20 — o controle"))
    assert "registro" not in limpo
    assert "Helena → Selene" not in limpo


def test_o_prompt_ensina_a_linha():
    from rpg import agent
    assert "relação:" in agent._EPILOGO_OBRIGATORIO
    assert "↔" in agent._EPILOGO_OBRIGATORIO
    # O mestre precisa saber que isto NÃO é a atitude com o grupo.
    assert "adjust_attitude" in agent._EPILOGO_OBRIGATORIO
