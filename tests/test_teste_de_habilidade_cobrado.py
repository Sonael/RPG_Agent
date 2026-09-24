"""
test_teste_de_habilidade_cobrado.py

Teste citado é teste rolado.

Numa campanha real de 91 turnos, medida em 21/09/2026, o mestre citou teste
de habilidade três vezes e não rolou nenhuma. Duas falas dele, literais:

    "O Desafio do Martelo de Aço (Teste de Força): um feirante musculoso
     desafia os participantes a erguerem um martelo pesado..."

    "Como Helena se sai no teste de pontaria? Deseja rolar para ela ou narrar
     o resultado?"

A bandeja de dados do jogador não foi usada uma única vez nesses 91 turnos.

O verificador do servidor já reinjetava o agente quando ele narrava dano sem
rolar; agora cobra o mesmo do teste de habilidade. O cuidado está no fluxo
certo: para personagem do jogador, o mestre PEDE o d20 e espera — isso não
pode virar violação.
"""
import pytest

from rpg import memory


@pytest.fixture
def verificador():
    import server
    return server


@pytest.fixture
def mesa(campanha):
    memory.campaign["dnd_mode"] = True
    return memory.campaign


def _checar(verificador, texto, ferramentas=frozenset()):
    return verificador._verify_agent_response(
        texto, set(ferramentas), combat_was_active=False, dead_before=set())


def _sobre_teste(violacoes):
    return [v for v in violacoes if "teste" in v.lower() or "dado" in v.lower()]


# ---------------------------------------------------------------------------
# 1. Teste narrado e nunca rolado
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("texto", [
    "O Desafio do Martelo de Aço (Teste de Força): o feirante sorri e aponta a base.",
    "A porta range. Um teste de Percepção revela passos do outro lado, e vocês seguem.",
    "Sonael consegue convencê-lo — CD 14 vencida com folga — e o homem abre caminho.",
    "Helena se sai bem no teste de pontaria e a flecha crava no centro.",
])
def test_citou_o_teste_sem_rolar_nada(mesa, verificador, texto):
    violacoes = _sobre_teste(_checar(verificador, texto))
    assert violacoes, texto
    assert "make_skill_check" in violacoes[0]


@pytest.mark.parametrize("ferramenta", ["make_skill_check", "social_check",
                                        "resolve_saving_throw", "roll_dice"])
def test_com_o_dado_rolado_nao_ha_cobranca(mesa, verificador, ferramenta):
    texto = "Sonael passa no teste de Furtividade e cruza o pátio sem ser visto."
    assert _sobre_teste(_checar(verificador, texto, {ferramenta})) == []


# ---------------------------------------------------------------------------
# 2. O fluxo certo do personagem do jogador não pode ser punido
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("texto", [
    "O martelo é pesado. Faça um teste de Força — role o d20 e me diga o resultado.",
    "Teste de Percepção, Sonael. Role na bandeja de dados quando quiser.",
    "É um teste de Atletismo (CD 13). Qual foi o resultado do seu d20?",
])
def test_pedir_o_dado_ao_jogador_e_esperar_e_o_certo(mesa, verificador, texto):
    assert _sobre_teste(_checar(verificador, texto)) == [], texto


# ---------------------------------------------------------------------------
# 3. Devolver a decisão ao jogador
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("texto", [
    "Como Helena se sai no teste de pontaria? Deseja rolar para ela ou narrar o resultado?",
    "Você prefere que eu narre o resultado, ou quer rolar?",
    "Quer rolar o d20 ou prefere que eu narre como termina?",
])
def test_oferecer_narrar_no_lugar_de_rolar_e_violacao(mesa, verificador, texto):
    violacoes = _sobre_teste(_checar(verificador, texto))
    assert violacoes, texto
    assert any("não existe" in v or "narrar" in v for v in violacoes), violacoes


def test_a_frase_da_partida_de_verdade(mesa, verificador):
    """A fala do turno 80, palavra por palavra."""
    texto = ("— Mostre se a patrulha militar ensinou alguma coisa além de marchar em "
             "linha reta. Como Helena se sai no teste de pontaria? Deseja rolar para "
             "ela ou narrar o resultado?")
    violacoes = _sobre_teste(_checar(verificador, texto))
    assert len(violacoes) == 2, violacoes      # citou o teste E devolveu a escolha


# ---------------------------------------------------------------------------
# 4. Sem regras de D&D, nada disso vale
# ---------------------------------------------------------------------------

def test_campanha_sem_regras_nao_e_cobrada(campanha, verificador):
    memory.campaign["dnd_mode"] = False
    memory.campaign["campaign_type"] = "romance"
    texto = "Clara encara o teste de coragem e bate na porta. Deseja rolar ou narrar o resultado?"
    assert _sobre_teste(_checar(verificador, texto)) == []


# ---------------------------------------------------------------------------
# 5. Nada de falso positivo em narração comum
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("texto", [
    "A caravana segue pela estrada e chega ao entardecer.",
    "Torbin martela o aço em silêncio; o calor da forja encosta no rosto de vocês.",
    "Selene guarda o amuleto na bolsa e faz que sim com a cabeça.",
    "O teste do tempo desgastou a ponte de pedra.",
])
def test_narracao_comum_nao_vira_violacao(mesa, verificador, texto):
    assert _sobre_teste(_checar(verificador, texto)) == [], texto
