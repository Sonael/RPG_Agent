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
import copy

import pytest

from rpg import entre, epilogo, memory


@pytest.fixture
def campanha(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "save_campaign", lambda *a, **k: None)
    # A campanha ativa é global: montar uma aqui e ir embora deixava o teste
    # seguinte sem as chaves que ele espera ("quests", "lojas", "relogio"), e
    # a falha saía longe da causa. Guarda e devolve.
    guardado = copy.deepcopy({k: v for k, v in memory.campaign.items()})
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
    yield memory.campaign
    memory.campaign.clear()
    memory.campaign.update(guardado)


# ---------------------------------------------------------------------------
# O modelo
# ---------------------------------------------------------------------------

def test_o_armazenamento_e_direcional(campanha):
    """O módulo guarda um lado por vez; quem espelha é quem escreve (o
    fechamento do turno e a tela). É o que deixa o lado avesso possível."""
    entre.ajustar("Helena", "Selene", -20, "o controle velado")
    assert entre.de_quem("Helena")[0]["valor"] == -20
    assert entre.de_quem("Selene") == []


def test_existe_e_valor_entre(campanha):
    assert entre.existe("Helena", "Selene") is False
    assert entre.valor_entre("Helena", "Selene") == 0
    entre.ajustar("Helena", "Selene", 0, "se conheceram")
    assert entre.existe("Helena", "Selene") is True
    assert entre.valor_entre("Helena", "Selene") == 0
    assert entre.existe("Selene", "Helena") is False


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
    # O segundo passo já não vale inteiro: de -20, afastar-se mais custa 20%
    # a mais (ver entre.passo_efetivo). -20 + int(-15 × 0,8) = -32.
    assert r["valor"] == -32
    assert r["rotulo"] == "atrito"
    assert [h["delta"] for h in r["historico"]] == [-12, -20]
    assert "na frente de todos" in r["historico"][0]["motivo"]
    assert r["historico"][0]["capitulo"] == 2


# ---------------------------------------------------------------------------
# Custa mais quanto mais longe já se está
# ---------------------------------------------------------------------------
# Medido numa partida: um elogio e uma conversa sincera levaram Selene → Helena
# de +30 a +45 e Helena → Selene de +5 a +20, no mesmo turno. Nesse ritmo,
# "inseparáveis" (+60) chega em quatro cenas e +100 em sete. "Está muito fácil
# subir as relações, qualquer coisinha já sobe."

@pytest.mark.parametrize("atual, delta, esperado", [
    (0,   20,  20),    # do meio, o passo vale inteiro
    (50,  20,  10),    # na metade do caminho, metade
    (90,  20,   2),    # quase no fim, quase nada
    (-50, -20, -10),   # o mesmo do lado do ódio
    (0,  -20, -20),
    (95,  10,   1),    # nunca trava: sempre anda ao menos 1
    (-95, -2,  -1),
    (0,    0,   0),
])
def test_o_passo_custa_mais_quanto_mais_longe(atual, delta, esperado):
    assert entre.passo_efetivo(atual, delta) == esperado


@pytest.mark.parametrize("atual, delta", [(80, -20), (-80, 20), (45, -10)])
def test_voltar_para_o_meio_nao_tem_freio(atual, delta):
    """Uma traição desfaz anos numa cena — e é assim que tem de ser."""
    assert entre.passo_efetivo(atual, delta) == delta


def test_chegar_ao_topo_e_obra_de_campanha(campanha):
    """
    Antes, sete passos de +15 bastavam para cravar +100. Agora o mesmo
    esforço encosta em "inseparáveis" e para ali.
    """
    for _ in range(7):
        entre.ajustar("Helena", "Selene", 15, "mais uma gentileza")
    valor = entre.valor_entre("Helena", "Selene")
    assert 55 <= valor <= 75, valor


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


def test_uma_linha_mexe_nos_dois_lados(campanha):
    """
    "a relação de helena para selene não atualizou, eu acho que só está
    atualizando em um personagem quando na verdade era para atualizar nos 2,
    afinal é a relação das duas." A ficha de Selene tinha +25 com Helena e a
    de Helena não tinha nada com Selene.
    """
    epilogo.processar(_bloco("relação: Selene → Helena +25 — se elogiaram depois da luta"))
    assert entre.valor_entre("Selene", "Helena") == 25
    assert entre.valor_entre("Helena", "Selene") == 25
    assert entre.de_quem("Helena")[0]["motivo"] == "se elogiaram depois da luta"


def test_seta_dos_dois_lados(campanha):
    epilogo.processar(_bloco("relação: Selene ↔ Sonael +30 — amigos de infância"))
    assert entre.de_quem("Selene")[0]["valor"] == 30
    assert entre.de_quem("Sonael")[0]["valor"] == 30


def test_a_volta_escrita_a_mao_nao_e_sobrescrita(campanha):
    """O caso que deu origem às relações: ela se ofendeu, ele nem percebeu."""
    epilogo.processar(_bloco(
        "relação: Helena → Selene -20 — odiou o controle velado",
        "relação: Selene → Helena 0 — não notou nada"))
    assert entre.valor_entre("Helena", "Selene") == -20
    assert entre.valor_entre("Selene", "Helena") == 0


def test_o_espelho_nao_gasta_o_teto_do_turno(campanha):
    """Duas linhas continuam sendo duas linhas, mesmo virando quatro escritas."""
    epilogo.processar(_bloco(
        "relação: Helena → Selene -10 — a sugestão",
        "relação: Sonael → Helena +10 — achou graça"))
    assert entre.valor_entre("Selene", "Helena") == -10
    assert entre.valor_entre("Helena", "Sonael") == 10


# ---------------------------------------------------------------------------
# O mesmo par não muda de novo tão cedo
# ---------------------------------------------------------------------------
# Aconteceu numa partida: o jogador pediu OPÇÕES do que fazer. A resposta
# resumiu a sessão ("a reaproximação sincera entre Helena e Selene") e fechou o
# turno registrando a relação de novo, por um acontecimento de dois turnos
# antes. Ao reabrir a campanha, o recap contou a mesma história e ela subiu uma
# terceira vez.

def test_o_resumo_nao_registra_de_novo_o_que_ja_aconteceu(campanha):
    epilogo.processar(_bloco("relação: Helena → Selene +20 — a conversa sincera"))
    memory.avancar_turno()

    _, relatorio = epilogo.processar(
        _bloco("relação: Helena → Selene +20 — a conversa sincera"))

    assert entre.valor_entre("Helena", "Selene") == 20, "subiu duas vezes"
    assert any("relacao" in r for r in relatorio["recusados"]), relatorio
    assert not relatorio["feitos"]


def test_a_recusa_diz_quantos_turnos_faltam(campanha):
    epilogo.processar(_bloco("relação: Helena → Selene +20 — a conversa"))
    memory.avancar_turno()
    _, relatorio = epilogo.processar(_bloco("relação: Helena → Selene +20 — a conversa"))
    texto = " ".join(relatorio["recusados"])
    assert "2" in texto and "resumindo" in texto, texto


def test_a_trava_vale_para_os_dois_sentidos(campanha):
    """A relação é das duas pessoas: o espelho também fica em espera."""
    epilogo.processar(_bloco("relação: Helena → Selene +20 — a conversa"))
    memory.avancar_turno()
    _, relatorio = epilogo.processar(_bloco("relação: Selene → Helena +20 — a conversa"))
    assert not relatorio["feitos"], relatorio


def test_passados_os_turnos_a_relacao_volta_a_mudar(campanha):
    epilogo.processar(_bloco("relação: Helena → Selene +20 — a conversa"))
    for _ in range(epilogo.TURNOS_ENTRE_MUDANCAS):
        memory.avancar_turno()

    _, relatorio = epilogo.processar(_bloco("relação: Helena → Selene +10 — outra cena"))

    assert relatorio["feitos"], relatorio["recusados"]
    assert entre.valor_entre("Helena", "Selene") > 20


def test_a_ficha_continua_editando_livremente(campanha):
    """A trava é do fechamento automático; a mão do jogador não espera."""
    epilogo.processar(_bloco("relação: Helena → Selene +20 — a conversa"))
    entre.definir("Helena", "Selene", 80, "corrigido pelo jogador")
    assert entre.valor_entre("Helena", "Selene") == 80


def test_a_trava_sobrevive_a_reabrir_a_campanha():
    """
    É justamente ao reabrir que o recap repete a cena. Se a marca não for
    gravada, a trava não existe no turno em que ela mais importa.
    """
    assert "_relacao_turno" in memory._defaults()

    import server
    payload = server._payload_de_campanha("Teste", {}, {})
    assert "_relacao_turno" in payload


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


# ---------------------------------------------------------------------------
# O jogador precisa VER que a relação mudou
# ---------------------------------------------------------------------------
# "eu fiz Helena e Selene se elogiarem para subir a relação delas, porém o
# sistema não avisou no chat que ela ganhou pontos na relação." O registro
# acontecia (o +25 estava na ficha), mas em silêncio — enquanto a mudança de
# atitude sempre saiu como linha no chat.

def test_a_mudanca_de_relacao_vira_aviso_para_o_jogador(campanha):
    _, relatorio = epilogo.processar(
        _bloco("relação: Helena → Selene +25 — admiração e respeito mútuo"))
    aviso = "\n".join(relatorio["avisos"])
    assert "Helena e Selene" in aviso        # das duas, não de uma para a outra
    assert "+25" in aviso
    assert "amizade" in aviso
    assert "admiração e respeito mútuo" in aviso


def test_relacao_dos_dois_lados_avisa_uma_vez(campanha):
    """Uma relação, uma linha no chat — não a mesma coisa dita duas vezes."""
    _, relatorio = epilogo.processar(_bloco("relação: Selene ↔ Sonael +20 — se entenderam"))
    assert len(relatorio["avisos"]) == 1


def test_quando_os_lados_diferem_o_aviso_mostra_a_direcao(campanha):
    _, relatorio = epilogo.processar(_bloco(
        "relação: Helena → Selene -20 — odiou o controle velado",
        "relação: Selene → Helena 0 — não notou nada"))
    assert len(relatorio["avisos"]) == 2
    assert "Helena → Selene" in relatorio["avisos"][0]
    assert " e " not in relatorio["avisos"][0].split(":")[0]


def test_turno_sem_relacao_nao_avisa_nada(campanha):
    _, relatorio = epilogo.processar(_bloco("lugar: Residência de Selene — sala clara"))
    assert relatorio["avisos"] == []


def test_relacao_recusada_nao_avisa(campanha):
    campanha["characters"]["brom"] = {"name": "Brom", "status": "vivo"}
    _, relatorio = epilogo.processar(_bloco("relação: Helena → Brom +20 — do nada"))
    assert relatorio["avisos"] == []
    assert relatorio["recusados"]


def test_sem_bloco_nenhum_o_relatorio_ainda_tem_avisos(campanha):
    _, relatorio = epilogo.processar("Só a narração, sem fechamento.")
    assert relatorio["avisos"] == []


def test_o_servidor_manda_o_aviso_para_a_tela():
    import inspect
    import server
    fonte = inspect.getsource(server.chat)
    assert "registro.get(\"avisos\")" in fonte
    assert "'tool_name': \"relacao\"" in fonte or '"tool_name": "relacao"' in fonte
    # Depois da cena: o cartão confirma o que acabou de ser narrado.
    assert fonte.index("'type': 'text'") < fonte.index('"tool_name": "relacao"')


def test_o_prompt_ensina_a_linha():
    from rpg import agent
    texto = agent._EPILOGO_OBRIGATORIO
    assert "relação:" in texto
    # Que a relação é das duas, e como fazer os lados diferirem.
    assert "DAS DUAS" in texto
    assert "as duas direções" in texto
    # E que isto NÃO é a atitude com o grupo.
    assert "adjust_attitude" in texto
