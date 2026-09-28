"""
test_fechamento_medido.py

Cinco consertos, todos tirados da medição de 34 turnos de uma campanha real.

O bloco chegou a 91% dos turnos (era 50%), mas HOUVE 15 RECUSAS EM 34 TURNOS —
quase uma a cada dois. Elas caíam em três padrões, e nenhum era falta de campo:

    fato='A Casa Vane contrabandeava substâncias arcanas...'  → use chave=valor
    fato='Nyx possui cicatrizes de queimaduras químicas...'   → use chave=valor
    tempo='30m — debate diante do mural'      → não dá para ler as horas
    local='Salão da Guilda dos Aventureiros'  → não aparece na narração

E, em paralelo, o jogador cobrou o relógio no chat SEIS vezes: o mestre
tentava fazer o tempo andar, o motor recusava, o relógio congelava.

  1. `tempo:` aceita minutos, e os que não fecham uma hora se acumulam.
  2. `sabe:` nasce: fato sobre PESSOA tem onde morar (add_character_knowledge
     era uma das ferramentas que o mestre esquecia).
  3. `fato:` recusa dizendo PARA ONDE ir.
  4. A evidência aceita nome composto citado pela parte que importa.
  5. As recusas VOLTAM para o mestre no turno seguinte — era por isso que ele
     repetia a mesma prosa em cinco turnos: nada nunca lhe disse.
"""
import pytest

from rpg import epilogo, memory

from conftest import criar_ficha


@pytest.fixture
def mesa(campanha, povoar):
    povoar(criar_ficha("Sonael", grupo=True))
    memory.campaign["current_location"] = "Valenport"
    memory.campaign["locations"] = {"valenport": {"name": "Valenport"}}
    memory.campaign["relogio"] = {"dia": 1, "hora": 8}
    return memory.campaign


def _bloco(narracao, *linhas):
    return narracao + "\n\n[[registro]]\n" + "\n".join(linhas) + "\n[[/registro]]"


# ---------------------------------------------------------------------------
# 1. O relógio aceita minutos
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("linha, minutos", [
    ("2h — viagem pela trilha", 120),
    ("30m — o debate diante do mural", 30),
    ("45 min de conversa", 45),
    ("1h30 — a subida", 90),
    ("3 horas: pesquisa", 180),
    ("2 — sem unidade nenhuma", 120),
])
def test_o_tempo_e_lido_em_horas_e_em_minutos(linha, minutos):
    m = epilogo._TEMPO_RE.match(linha)
    assert m, linha
    assert epilogo._minutos_da_linha(m) == minutos


def test_meia_hora_nao_e_mais_recusada(mesa):
    _, r = epilogo.processar(_bloco(
        "O debate diante do mural se estende.",
        "tempo: 30m — o debate diante do mural"))
    assert not r["recusados"], r["recusados"]


def test_os_minutos_se_acumulam_ate_virar_hora(mesa):
    """Duas cenas de meia hora fazem o relógio andar uma vez."""
    epilogo.processar(_bloco("A conversa se estende.", "tempo: 30m — a conversa"))
    assert mesa["relogio"]["hora"] == 8, "meia hora não vira hora sozinha"

    epilogo.processar(_bloco("A conversa se estende de novo.", "tempo: 30m — mais"))
    assert mesa["relogio"]["hora"] == 9, "as duas metades não fecharam uma hora"


def test_hora_e_minuto_juntos(mesa):
    epilogo.processar(_bloco("A subida leva a tarde.", "tempo: 1h30 — a subida"))
    assert mesa["relogio"]["hora"] == 9
    assert mesa["relogio"]["minutos"] == 30


def test_o_que_sobra_fica_guardado_e_nao_some(mesa):
    epilogo.processar(_bloco("A conversa.", "tempo: 40m — a conversa"))
    assert mesa["relogio"]["minutos"] == 40


def test_mais_de_um_dia_continua_recusado(mesa):
    _, r = epilogo.processar(_bloco("A viagem.", "tempo: 30h — a viagem inteira"))
    assert any("24 horas" in x for x in r["recusados"]), r


def test_zero_continua_sem_ser_erro(mesa):
    _, r = epilogo.processar(_bloco("Só um ajuste de laços.", "tempo: 0h — nada"))
    assert not r["recusados"], r["recusados"]


# ---------------------------------------------------------------------------
# 2. `sabe:` — o que o grupo descobriu sobre alguém
# ---------------------------------------------------------------------------

def test_o_que_o_grupo_descobriu_entra_na_ficha(mesa, povoar):
    povoar(criar_ficha("Nyx"))
    narracao = ("Nyx puxa a manga e mostra o braço: a pele repuxada de quem "
                "pegou alguma coisa que não devia.")

    _, r = epilogo.processar(_bloco(
        narracao, "sabe: Nyx — tem cicatrizes de queimadura química"))

    assert r["feitos"], r["recusados"]
    conhecido = memory.campaign["characters"]["nyx"].get("conhecido") or []
    assert any("queimadura" in f for f in conhecido), conhecido


def test_o_que_a_cena_nao_citou_e_recusado(mesa, povoar):
    povoar(criar_ficha("Nyx"))
    _, r = epilogo.processar(_bloco(
        "A praça está vazia.", "sabe: Nyx — tem cicatrizes"))
    assert not r["feitos"]
    assert any("sabe" in x for x in r["recusados"])


def test_sem_o_fato_a_linha_e_recusada_com_o_formato(mesa, povoar):
    povoar(criar_ficha("Nyx"))
    _, r = epilogo.processar(_bloco("Nyx atravessa a praça.", "sabe: Nyx"))
    assert any("Nome —" in x for x in r["recusados"]), r["recusados"]


def test_o_grupo_e_avisado_do_que_descobriu(mesa, povoar):
    povoar(criar_ficha("Nyx"))
    _, r = epilogo.processar(_bloco(
        "Nyx mostra o braço queimado.",
        "sabe: Nyx — tem cicatrizes de queimadura química"))
    assert any("Nyx" in a for a in r["avisos"]), r["avisos"]


# ---------------------------------------------------------------------------
# 3. `fato:` diz para onde ir
# ---------------------------------------------------------------------------

def test_fato_em_prosa_e_recusado_apontando_o_caminho(mesa):
    """
    O caso real, cinco vezes no mesmo mês. A recusa antiga ("use chave=valor")
    dizia o que estava errado e não dizia onde era o certo.
    """
    _, r = epilogo.processar(_bloco(
        "A Casa Vane some do porto sem explicar.",
        "fato: A Casa Vane contrabandeava substâncias arcanas nos comboios."))
    texto = " ".join(r["recusados"])
    assert "sabe:" in texto and "cena:" in texto, texto


def test_bandeira_de_verdade_continua_passando(mesa):
    _, r = epilogo.processar(_bloco(
        "A ponte fica para trás.", "fato: ponte_atravessada=sim"))
    assert memory.campaign["quest_flags"].get("ponte_atravessada") == "sim"
    assert not r["recusados"]


# ---------------------------------------------------------------------------
# 4. A evidência continua como estava — e o porquê
# ---------------------------------------------------------------------------
# A medição trouxe quatro recusas que pareciam injustas ("Salão da Guilda dos
# Aventureiros: não aparece na narração"). Escrevi uma regra de maioria para
# salvá-las e ela não derrubou injeção nenhuma: as narrações que MONTEI para o
# teste já passavam pela regra existente. Ou seja, eu não sabia o que as
# narrações REAIS tinham — só que não tinham o nome.
#
# Afrouxar a trava que impede inventar lugar sem um caso que falhe é trocar a
# fechadura porque a chave sumiu. A mudança foi revertida. Estes testes ficam
# como guarda do que a regra JÁ aceita, para ninguém apertar por engano
# enquanto o dado de verdade não chega.

@pytest.mark.parametrize("nome, narracao", [
    ("Salão da Guilda dos Aventureiros", "O calor do salão da guilda envolve vocês."),
    ("Botica de Alquimia de Valenport", "A porta da botica de alquimia range."),
    ("Portão Leste de Valenport", "Passam pelo portão leste ao amanhecer."),
    ("Floresta Sussurrante", "A floresta sussurrante engole a trilha."),
])
def test_a_cena_cita_o_lugar_pela_parte_que_importa(nome, narracao):
    assert epilogo._tem_evidencia(nome, narracao), nome


@pytest.mark.parametrize("nome, narracao", [
    ("Torre do Mago Sombrio", "Um mago atravessa a praça."),
    ("Ponte Quebrada", "A caravana descansa na estrada."),
    ("Salão da Guilda dos Aventureiros", "A taverna está cheia."),
])
def test_inventar_continua_sem_passar(nome, narracao):
    assert not epilogo._tem_evidencia(nome, narracao), nome


# ---------------------------------------------------------------------------
# 5. A recusa volta para o mestre
# ---------------------------------------------------------------------------

def test_o_servidor_devolve_a_recusa_ao_mestre():
    """
    Era o buraco por trás dos cinco `fato:` repetidos: a recusa ia para o log
    e para a medição, e nunca chegava a quem a cometeu.
    """
    import inspect

    import server
    fonte = inspect.getsource(server.chat)
    assert 'registro.get("recusados")' in fonte
    assert "_pendencias" in fonte
    assert fonte.index('registro.get("recusados")') < fonte.index(
        'if v["rule"] in ("unsaved_character"')


# ---------------------------------------------------------------------------
# 6. O prompt ensina o que o motor passou a aceitar
# ---------------------------------------------------------------------------

def test_o_prompt_ensina_o_campo_novo_e_os_minutos(campanha):
    from rpg.agent import create_agent

    agente = create_agent("gemini-2.5-flash", "fantasia", dnd_mode=True)
    instrucao = agente.instruction() if callable(agente.instruction) else agente.instruction

    assert "sabe:" in instrucao
    assert '"30m"' in instrucao or "30m" in instrucao
    # E continua ensinando TODO campo que o motor sabe aplicar.
    for campo in epilogo.CAMPOS:
        assert f"{epilogo.ESCRITO.get(campo, campo)}:" in instrucao, campo


def test_a_ficha_nova_avisa_no_chat(mesa):
    """Era a reclamação: "o mestre adicionou a Nyx e não apareceu nada no chat"."""
    _, r = epilogo.processar(_bloco(
        "Nyx atravessa a praça e para diante do mural.",
        "gente: Nyx — contrabandista de olhos claros"))
    assert any("Nyx" in a and "ficha" in a for a in r["avisos"]), r["avisos"]
