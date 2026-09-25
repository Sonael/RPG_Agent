"""
test_fechamento_cobrado.py

O que a PRIMEIRA medição real do fechamento de turno mostrou, e o que foi
feito com cada coisa.

Seis respostas do mestre medidas numa partida de verdade:
  • o bloco [[registro]] veio em 3 delas — metade dos turnos sem fechamento;
  • 9 registros feitos e 5 RECUSADOS, e as recusas eram quase todas injustas:
      local='Botica de Alquimia de Valenport': não aparece na narração
      lugar='Botica de Alquimia de Valenport': não aparece na narração
      gente='Mestre Alquimista Faelar': não aparece na narração
      tempo='0h — ajuste de laços': fora de 1 a 24 horas

O nome completo escrito no bloco contra a forma curta da cena ("a botica de
alquimia") era recusa de registro LEGÍTIMO — o oposto do que a trava serve. E
"0h" era o mestre dizendo que a cena não gastou tempo, o que não é erro.

Este arquivo cobre:
  1. a cobrança do bloco que não veio (rpg/agent.py);
  2. a evidência por parte do nome e o tempo zero (rpg/epilogo.py);
  5. os campos cena: e capítulo: (a linha do tempo estava com 3 eventos em 91
     turnos, e o capítulo travado em 1).
"""
import copy

import pytest

from rpg import agent, epilogo, memory


@pytest.fixture
def campanha(monkeypatch):
    monkeypatch.setattr(memory, "save_campaign", lambda *a, **k: None)
    guardado = copy.deepcopy({k: v for k, v in memory.campaign.items()})
    memory.campaign.clear()
    memory.campaign.update({
        "name": "Teste", "chapter": 1, "turno": 12, "protagonist": "Sonael",
        "current_location": "Valenport", "current_scene": "", "story_summary": "",
        "party": [{"name": "Sonael", "role": "mago", "notes": ""}],
        "characters": {
            "sonael": {"name": "Sonael", "status": "vivo", "party_member": True},
            "helena": {"name": "Helena", "status": "vivo", "party_member": True},
        },
        "locations": {}, "events": [], "quests": {}, "flags": {}, "diary": [],
        "relogio": {"dia": 1, "hora": 8},
        "conversation_history": [],
    })
    yield memory.campaign
    memory.campaign.clear()
    memory.campaign.update(guardado)


def _bloco(narracao, *linhas):
    return narracao + "\n\n[[registro]]\n" + "\n".join(linhas) + "\n[[/registro]]"


# ---------------------------------------------------------------------------
# 1. Cobrar o bloco que não veio
# ---------------------------------------------------------------------------

def test_sem_fechamento_o_mestre_e_cobrado_no_turno_seguinte(campanha):
    campanha["_sem_fechamento"] = 1
    bloco = agent._pendencias_block()
    assert "[[registro]]" in bloco
    assert "anterior" in bloco


def test_a_cobranca_conta_as_vezes_seguidas(campanha):
    campanha["_sem_fechamento"] = 4
    bloco = agent._pendencias_block()
    assert "4 respostas" in bloco


def test_com_fechamento_em_dia_nao_ha_cobranca(campanha):
    campanha["_sem_fechamento"] = 0
    assert "[[registro]]" not in agent._pendencias_block()


def test_a_cobranca_e_fato_e_nao_suspeita(campanha):
    """As suspeitas do verificador erram muito e são anunciadas assim; esta
    é contada pelo sistema e não pode ir para o mesmo balaio."""
    campanha["_sem_fechamento"] = 2
    bloco = agent._pendencias_block()
    antes_das_suspeitas = bloco.split("O QUE JÁ VOLTOU")[0]
    assert "[[registro]]" in antes_das_suspeitas


def test_o_servidor_conta_as_faltas():
    import inspect
    import server
    fonte = inspect.getsource(server.chat)
    assert '_sem_fechamento' in fonte
    # Zera quando o bloco vem, soma quando não vem.
    assert 'registro.get("tinha_bloco")' in fonte


# ---------------------------------------------------------------------------
# 2. A evidência que estava apertada demais
# ---------------------------------------------------------------------------

NARRACAO_BOTICA = (
    "O grupo empurra a porta da botica de alquimia, e o cheiro de enxofre "
    "toma o corredor. Atrás do balcão, o velho Faelar ergue os olhos dos "
    "frascos."
)


def test_nome_completo_contra_forma_curta_da_cena(campanha):
    """O caso real: o bloco escreve o nome inteiro, a cena usa o apelido."""
    assert epilogo._tem_evidencia("Botica de Alquimia de Valenport", NARRACAO_BOTICA)
    assert epilogo._tem_evidencia("Mestre Alquimista Faelar", NARRACAO_BOTICA)


def test_o_que_a_cena_nao_citou_continua_recusado(campanha):
    assert not epilogo._tem_evidencia("Torre do Mago Sombrio", NARRACAO_BOTICA)
    assert not epilogo._tem_evidencia("Capitã Mirala", NARRACAO_BOTICA)


def test_palavra_pequena_e_comum_nao_basta(campanha):
    """A cena tinha um mago; isso não batiza uma torre que ela nunca citou."""
    assert not epilogo._tem_evidencia(
        "Torre do Mago Sombrio", "O mago ergue a mão e a porta se fecha sozinha.")


def test_o_nome_inflado_passa_de_proposito(campanha):
    """
    "Guarda da Cidade Baixa" passa numa cena que disse só "a guarda": o mestre
    está batizando quem acabou de narrar. Perder o registro é pior do que
    ganhar um nome comprido.
    """
    assert epilogo._tem_evidencia(
        "Guarda da Cidade Baixa", "A guarda passou pela rua sem olhar para eles.")


def test_nome_curto_vale_inteiro(campanha):
    assert epilogo._tem_evidencia("Pip", "Pip range os dentes e avança.")
    assert not epilogo._tem_evidencia("Pip", "A pipa some atrás do telhado.")


def test_o_registro_deixa_de_ser_recusado_a_toa(campanha):
    _, relatorio = epilogo.processar(_bloco(
        NARRACAO_BOTICA,
        "local: Botica de Alquimia de Valenport",
        "gente: Mestre Alquimista Faelar — o velho boticário"))
    assert relatorio["recusados"] == []
    assert any("update_world_state" in f for f in relatorio["feitos"])
    assert any("save_character" in f for f in relatorio["feitos"])


def test_tempo_zero_nao_e_erro(campanha):
    _, relatorio = epilogo.processar(_bloco(
        "Helena e Sonael trocam duas palavras junto à porta.",
        "tempo: 0h — ajuste de laços"))
    assert relatorio["recusados"] == []
    assert not any("advance_time" in f for f in relatorio["feitos"])


def test_tempo_grande_demais_continua_recusado(campanha):
    _, relatorio = epilogo.processar(_bloco(
        "A viagem atravessa o continente.", "tempo: 90h — a travessia"))
    assert any("24 horas" in r for r in relatorio["recusados"])


# ---------------------------------------------------------------------------
# 5. cena: e capítulo:
# ---------------------------------------------------------------------------

NARRACAO_RESGATE = (
    "Sonael arrasta o herbologista para fora da fenda enquanto Helena segura "
    "a passagem. Lá fora, a luz da manhã encontra os três inteiros."
)


def test_cena_vira_acontecimento_na_linha_do_tempo(campanha):
    _, relatorio = epilogo.processar(_bloco(
        NARRACAO_RESGATE,
        "cena: Resgataram o herbologista na fenda — a guilda passou a confiar neles"))
    eventos = campanha["events"]
    assert len(eventos) == 1
    assert "herbologista" in eventos[0]["summary"]
    assert eventos[0]["consequence"] == "a guilda passou a confiar neles"
    assert eventos[0]["location"] == "Valenport"
    assert any("save_event" in f for f in relatorio["feitos"])


def test_o_acontecimento_guarda_quem_estava_na_cena(campanha):
    epilogo.processar(_bloco(
        NARRACAO_RESGATE, "cena: Resgataram o herbologista na fenda"))
    envolvidos = campanha["events"][0]["characters_involved"]
    assert "Sonael" in envolvidos and "Helena" in envolvidos


def test_cena_curta_demais_nao_vira_acontecimento(campanha):
    _, relatorio = epilogo.processar(_bloco(NARRACAO_RESGATE, "cena: conversaram"))
    assert campanha["events"] == []
    assert relatorio["recusados"]


def test_um_acontecimento_por_turno(campanha):
    epilogo.processar(_bloco(
        NARRACAO_RESGATE,
        "cena: Resgataram o herbologista na fenda de pedra",
        "cena: Voltaram à guilda para receber a recompensa"))
    assert len(campanha["events"]) == 1


def test_capitulo_vira_o_proximo(campanha):
    _, relatorio = epilogo.processar(_bloco(
        NARRACAO_RESGATE, "capítulo: 2"))
    assert campanha["chapter"] == 2
    assert any("chapter=2" in f for f in relatorio["feitos"])


def test_capitulo_nao_pula(campanha):
    _, relatorio = epilogo.processar(_bloco(NARRACAO_RESGATE, "capítulo: 7"))
    assert campanha["chapter"] == 1
    assert any("um de cada vez" in r for r in relatorio["recusados"])


def test_capitulo_igual_ao_atual_nao_faz_nada(campanha):
    _, relatorio = epilogo.processar(_bloco(NARRACAO_RESGATE, "capítulo: 1"))
    assert campanha["chapter"] == 1
    assert relatorio["recusados"] == []


def test_capitulo_sem_numero(campanha):
    _, relatorio = epilogo.processar(_bloco(NARRACAO_RESGATE, "capítulo: o da mina"))
    assert relatorio["recusados"]


def test_o_prompt_ensina_os_campos_novos():
    texto = agent._EPILOGO_OBRIGATORIO
    assert "cena:" in texto and "capítulo:" in texto
    assert "save_event" in texto          # o mestre não precisa mais chamar


# ---------------------------------------------------------------------------
# 6. Uma ordem só para cada coisa
#
# O fechamento nasceu por cima de um prompt que já mandava chamar ferramenta
# para as MESMAS oito coisas, e a cobrança de manutenção também cobrava pelo
# nome da ferramenta ("8 turnos sem add_diary_entry()"). Duas ordens para o
# mesmo registro: a resposta vinha com as duas (registro duplicado) ou com
# nenhuma — que foi o que a medição mostrou, metade dos turnos sem bloco.
# ---------------------------------------------------------------------------

FERRAMENTAS_QUE_O_BLOCO_FAZ = ("add_diary_entry", "advance_time",
                               "update_world_state", "save_location",
                               "save_event", "set_flag")


def test_a_cobranca_manda_escrever_a_linha_e_nao_chamar_a_ferramenta(campanha):
    """
    A cobrança é o texto que o mestre lê no topo do turno. Se ela pede a
    ferramenta, ganha dela — é a mais específica e a que traz número.
    """
    campanha["_turno"] = 30
    campanha["_upkeep"] = {"diario": 1, "relogio": 1, "mundo": 1, "resumo": 1}
    bloco = agent._pendencias_block()
    assert "'diário:'" in bloco and "'tempo:'" in bloco and "'local:'" in bloco
    for ferramenta in FERRAMENTAS_QUE_O_BLOCO_FAZ:
        assert ferramenta not in bloco, ferramenta
    # O resumo NÃO sai do bloco: continua sendo ferramenta, e cobrado assim.
    assert "update_story_summary" in bloco


def test_a_instrucao_diz_de_onde_sai_cada_campo(campanha):
    from rpg.agent import create_agent

    agente = create_agent("gemini-2.5-flash", "fantasia", dnd_mode=True)
    instrucao = agente.instruction() if callable(agente.instruction) else agente.instruction
    salvar = instrucao.split("SALVAR")[1].split("MAPA")[0]
    # Os oito campos do fechamento aparecem como campo, juntos, na seção que
    # antes mandava chamar ferramenta para cada um.
    for campo in epilogo.CAMPOS:
        assert epilogo.ESCRITO.get(campo, campo) in salvar, campo
    # E a seção diz o que continua sendo ferramenta, para não sobrar dúvida.
    for ferramenta in ("add_party_member", "update_story_summary",
                       "set_character_location", "add_character_knowledge"):
        assert ferramenta in salvar, ferramenta
