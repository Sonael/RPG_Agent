"""
test_relacao_no_romance.py

O romance já tinha relação: afeto e confiança com o PROTAGONISTA, com vínculo,
estágio e momentos (rpg/relacoes.py). Depois entrou a relação entre duas
pessoas quaisquer (rpg/entre.py) e a linha "relação:" no fechamento do turno,
que valem para todos os gêneros.

A costura entre as duas é o que este arquivo cuida: uma linha de fechamento
que envolva o protagonista, num romance, tem de cair no AFETO — e não criar um
segundo número para a mesma relação, em outra caixa, que a tela de Relações
não lê.
"""
import copy

import pytest

from rpg import agent, entre, epilogo, memory, personagens, relacoes


@pytest.fixture
def romance(monkeypatch):
    monkeypatch.setattr(memory, "save_campaign", lambda *a, **k: None)
    guardado = copy.deepcopy({k: v for k, v in memory.campaign.items()})
    memory.campaign.clear()
    memory.campaign.update({
        "name": "Teste", "chapter": 1, "turno": 5,
        "campaign_type": "romance", "dnd_mode": False,
        "protagonist": "Sonael", "current_location": "Café da esquina",
        "party": [{"name": "Sonael", "role": "", "notes": ""}],
        "characters": {
            "sonael": {"name": "Sonael", "status": "vivo", "party_member": True},
            "lucas": {"name": "Lucas", "status": "vivo", "atitude": 10, "confianca": 5},
            "clara": {"name": "Clara", "status": "vivo"},
        },
        "locations": {}, "events": [], "quests": {}, "flags": {},
        "conversation_history": [],
    })
    yield memory.campaign
    memory.campaign.clear()
    memory.campaign.update(guardado)


def _bloco(narracao, *linhas):
    return narracao + "\n\n[[registro]]\n" + "\n".join(linhas) + "\n[[/registro]]"


CENA = ("Lucas encosta a xícara na mesa e diz que esperou a tarde toda. Clara "
        "observa os dois da outra ponta do balcão.")


# ---------------------------------------------------------------------------
# Com o protagonista: cai no afeto, não numa segunda caixa
# ---------------------------------------------------------------------------

def test_relacao_com_o_protagonista_vira_afeto(romance):
    _, relatorio = epilogo.processar(_bloco(
        CENA, "relação: Lucas → Sonael +15 — esperou a tarde toda"))
    assert relacoes.afeto_de(romance["characters"]["lucas"]) == 25
    assert any("ajustar_relacao" in f for f in relatorio["feitos"])
    # E NÃO criou o número paralelo.
    assert entre.de_quem("Lucas") == []
    assert entre.de_quem("Sonael") == []


def test_a_confianca_nao_e_tocada(romance):
    """A linha move um eixo só; o outro é decisão do mestre (ajustar_relacao)."""
    epilogo.processar(_bloco(CENA, "relação: Lucas → Sonael +15 — esperou"))
    assert relacoes.confianca_de(romance["characters"]["lucas"]) == 5


def test_o_aviso_fala_a_lingua_do_romance(romance):
    _, relatorio = epilogo.processar(_bloco(
        CENA, "relação: Lucas → Sonael +15 — esperou a tarde toda"))
    aviso = "\n".join(relatorio["avisos"])
    assert "afeto" in aviso
    assert "afeição" in aviso          # a faixa do romance, não "amistoso"
    assert "esperou a tarde toda" in aviso


def test_a_direcao_nao_importa_com_o_protagonista(romance):
    epilogo.processar(_bloco(CENA, "relação: Sonael → Lucas +20 — o alívio de vê-lo"))
    assert relacoes.afeto_de(romance["characters"]["lucas"]) == 30


def test_o_nome_do_protagonista_nao_precisa_estar_na_cena(romance):
    """O mestre escreve "você" no lugar do nome dele metade do tempo."""
    cena = "Lucas encosta a xícara na mesa e diz que esperou você a tarde toda."
    _, relatorio = epilogo.processar(_bloco(cena, "relação: Lucas → Sonael +15 — esperou"))
    assert relacoes.afeto_de(romance["characters"]["lucas"]) == 25
    assert relatorio["recusados"] == []


def test_quem_nao_esta_na_cena_continua_recusado(romance):
    romance["characters"]["bruno"] = {"name": "Bruno", "status": "vivo"}
    _, relatorio = epilogo.processar(_bloco(CENA, "relação: Bruno → Sonael +15 — do nada"))
    assert relatorio["recusados"]
    assert relacoes.afeto_de(romance["characters"]["bruno"]) == 0


def test_passo_zero_com_o_protagonista_nao_e_erro(romance):
    _, relatorio = epilogo.processar(_bloco(CENA, "relação: Lucas → Sonael 0 — nada mudou"))
    assert relatorio["recusados"] == []
    assert relacoes.afeto_de(romance["characters"]["lucas"]) == 10


# ---------------------------------------------------------------------------
# Entre duas outras pessoas: vale como em qualquer gênero
# ---------------------------------------------------------------------------

def test_entre_duas_outras_pessoas_continua_valendo(romance):
    epilogo.processar(_bloco(CENA, "relação: Clara → Lucas -20 — o ciúme da tarde"))
    assert entre.valor_entre("Clara", "Lucas") == -20
    assert entre.valor_entre("Lucas", "Clara") == -20      # espelho
    # E o afeto de ninguém com o protagonista foi mexido.
    assert relacoes.afeto_de(romance["characters"]["lucas"]) == 10


# ---------------------------------------------------------------------------
# A ficha não mostra a mesma relação em duas caixas
# ---------------------------------------------------------------------------

def test_a_ficha_nao_duplica_a_relacao_com_o_protagonista(romance):
    # Dado antigo, de antes do roteamento: o par com o protagonista em entre.
    entre.ajustar("Lucas", "Sonael", 40, "de antes")
    f = personagens.ficha("Lucas")
    assert f["relacao"] is not None                     # a caixa do romance
    assert [r["nome"] for r in f["entre"]] == []        # e só ela


def test_a_ficha_mostra_as_outras_relacoes(romance):
    entre.ajustar("Lucas", "Clara", -30, "o ciúme")
    assert [r["nome"] for r in personagens.ficha("Lucas")["entre"]] == ["Clara"]


def test_editar_pela_ficha_cai_no_afeto(romance):
    """Senão o jogador mexeria num número que nenhuma tela mostra."""
    f = personagens.editar_relacao(
        "Lucas", {"para": "Sonael", "valor": 60, "motivo": "a noite da chuva"})
    assert relacoes.afeto_de(romance["characters"]["lucas"]) == 60
    assert f["relacao"]["afeto"]["valor"] == 60
    assert f["entre"] == []


def test_editar_pela_ficha_do_protagonista_tambem(romance):
    personagens.editar_relacao("Sonael", {"para": "Lucas", "valor": 45})
    assert relacoes.afeto_de(romance["characters"]["lucas"]) == 45


def test_editar_entre_outras_duas_continua_em_entre(romance):
    personagens.editar_relacao("Clara", {"para": "Lucas", "valor": -40})
    assert entre.valor_entre("Clara", "Lucas") == -40
    assert relacoes.afeto_de(romance["characters"]["lucas"]) == 10


def test_no_romance_a_atitude_continua_escondida(romance):
    """Ela É o afeto: mostrar as duas seria o mesmo número com dois nomes."""
    assert personagens.ficha("Lucas")["atitude"] is None


# ---------------------------------------------------------------------------
# O prompt
# ---------------------------------------------------------------------------

def test_o_prompt_do_romance_explica_os_dois_eixos(romance):
    from rpg.agent import create_agent
    agente = create_agent("gemini-2.5-flash", "romance", dnd_mode=False)
    instrucao = agente.instruction() if callable(agente.instruction) else agente.instruction
    assert "ajustar_relacao" in instrucao
    assert "AFETO" in instrucao
    assert "CONFIANÇA" in instrucao


def test_fora_do_romance_esse_bloco_nao_aparece(campanha):
    from rpg.agent import create_agent
    campanha["campaign_type"] = "fantasia"
    agente = create_agent("gemini-2.5-flash", "fantasia", dnd_mode=True)
    instrucao = agente.instruction() if callable(agente.instruction) else agente.instruction
    assert "A LINHA DE RELAÇÃO NESTE GÊNERO" not in instrucao
