"""
test_epilogo_do_turno.py

O mestre narra e, no fim, anota o que mudou.

A medição de uma campanha de 91 turnos mostrou o problema: 10 das 72
mensagens digitadas pelo jogador eram cobrança de registro — "adicione
Ravenrust ao mapa", "salve o personagem torbin", "atualize a hora". Um de
cada sete turnos dele. A causa é a ordem: a ferramenta era chamada ANTES da
narração, quando o fato ainda não existe e o mestre teria de prever o próprio
texto.

Agora a resposta termina com um bloco escondido e o servidor faz as chamadas.
Aqui se prova o que não pode quebrar: o bloco sai do texto do jogador, só
registra o que a narração diz, não regrava o que já existe e nunca derruba o
turno.
"""
import pytest

from rpg import epilogo, memory

from conftest import criar_ficha


@pytest.fixture
def mesa(campanha, povoar):
    povoar(criar_ficha("Sonael", grupo=True))
    memory.campaign["dnd_mode"] = True
    memory.campaign["current_location"] = "Valenport"
    memory.campaign["locations"] = {"valenport": {"name": "Valenport", "description": "A vila."}}
    memory.campaign["relogio"] = {"dia": 1, "hora": 8}
    return memory.campaign


# ---------------------------------------------------------------------------
# 1. O bloco sai do texto
# ---------------------------------------------------------------------------

def test_o_bloco_nao_chega_ao_jogador():
    texto = ("A caravana cruza a ponte antes do anoitecer.\n\n"
             "[[registro]]\nlocal: Ponte Quebrada\ntempo: 2h — viagem\n[[/registro]]")
    limpo, campos = epilogo.extrair(texto)
    assert limpo == "A caravana cruza a ponte antes do anoitecer."
    assert campos == {"local": ["Ponte Quebrada"], "tempo": ["2h — viagem"]}


@pytest.mark.parametrize("bloco", [
    "[[registro]]\nlocal: Ponte Quebrada\n[[/registro]]",
    "```\n[[registro]]\nlocal: Ponte Quebrada\n[[/registro]]\n```",
    "[[ REGISTRO ]]\n- Local: Ponte Quebrada\n[[ /registro ]]",
    "[[registro]]\nlocal:   Ponte Quebrada   \nfato: -\n[[/registro]]",
])
def test_formatos_tortos_ainda_sao_lidos(bloco):
    limpo, campos = epilogo.extrair("A ponte range.\n" + bloco)
    assert limpo == "A ponte range."
    assert campos["local"] == ["Ponte Quebrada"]
    assert "fato" not in campos


def test_sem_bloco_nada_muda():
    limpo, campos = epilogo.extrair("Só narração, sem bloco nenhum.")
    assert limpo == "Só narração, sem bloco nenhum."
    assert campos == {}


def test_campo_desconhecido_e_ignorado():
    _, campos = epilogo.extrair("x\n[[registro]]\nlocal: Vale\ncor: azul\n[[/registro]]")
    assert campos == {"local": ["Vale"]}


# ---------------------------------------------------------------------------
# 2. Local atual
# ---------------------------------------------------------------------------

def test_local_muda_quando_a_narracao_diz(mesa):
    narracao = "Vocês deixam a vila e chegam à Ponte Quebrada ao anoitecer."
    r = epilogo.aplicar({"local": ["Ponte Quebrada"]}, narracao)
    assert memory.campaign["current_location"] == "Ponte Quebrada"
    assert any("update_world_state" in f for f in r["feitos"])


def test_local_sem_evidencia_e_recusado(mesa):
    r = epilogo.aplicar({"local": ["Cidade de Vhar"]}, "A caravana descansa na estrada.")
    assert memory.campaign["current_location"] == "Valenport"
    assert r["feitos"] == [] and "não aparece na narração" in r["recusados"][0]


def test_local_igual_ao_atual_nao_regrava(mesa):
    r = epilogo.aplicar({"local": ["Valenport"]}, "De volta a Valenport, tudo segue igual.")
    assert r["feitos"] == [] and r["recusados"] == []


# ---------------------------------------------------------------------------
# 3. Tempo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("valor, horas", [
    ("2h — viagem pela trilha", 2), ("3 horas: caminhada", 3),
    ("1h", 1), ("6 h de espera", 6), ("8", 8),
])
def test_tempo_em_varias_formas(mesa, valor, horas):
    epilogo.aplicar({"tempo": [valor]}, "O sol atravessa o céu enquanto vocês seguem.")
    assert memory.campaign["relogio"]["hora"] == (8 + horas) % 24


@pytest.mark.parametrize("valor", ["um tempo", "", "48h", "0h"])
def test_tempo_ilegivel_ou_absurdo_e_recusado(mesa, valor):
    r = epilogo.aplicar({"tempo": [valor]}, "A cena segue.")
    assert memory.campaign["relogio"] == {"dia": 1, "hora": 8}
    assert r["feitos"] == []


# ---------------------------------------------------------------------------
# 4. Lugar e gente
# ---------------------------------------------------------------------------

def test_lugar_novo_entra_no_mapa_com_o_de_dentro(mesa):
    narracao = "A Ponte Quebrada range sobre o rio, tábuas podres à mostra."
    epilogo.aplicar({"lugar": ["Ponte Quebrada (dentro de: Valenport) — tábuas podres"]}, narracao)
    lugar = memory.campaign["locations"].get("ponte quebrada")
    assert lugar and "tábuas podres" in lugar["description"]
    assert lugar.get("dentro_de") == "Valenport"


def test_lugar_que_ja_existe_nao_e_regravado(mesa):
    memory.campaign["locations"]["valenport"]["description"] = "A vila."
    epilogo.aplicar({"lugar": ["Valenport — outra descrição"]}, "Valenport dorme sob a chuva.")
    assert memory.campaign["locations"]["valenport"]["description"] == "A vila."


def test_gente_nova_ganha_ficha_no_local_atual(mesa):
    narracao = "Aldric, o ferreiro, larga o martelo e cumprimenta vocês."
    epilogo.aplicar({"gente": ["Aldric — ferreiro da vila"]}, narracao)
    ficha = memory.campaign["characters"].get("aldric")
    assert ficha and ficha["description"] == "ferreiro da vila"
    assert ficha.get("local") == "Valenport"


def test_gente_que_a_narracao_nao_cita_e_recusada(mesa):
    r = epilogo.aplicar({"gente": ["Barão Corvo — o vilão"]}, "A praça está vazia.")
    assert "barao corvo" not in memory.campaign["characters"]
    assert r["recusados"]


def test_teto_por_turno(mesa):
    narracao = ("Na estrada vocês passam por Casa Um, Casa Dois, Casa Três e Casa Quatro, "
                "onde moram Ana, Bruno, Caio e Dora.")
    epilogo.aplicar({
        "lugar": ["Casa Um", "Casa Dois", "Casa Três", "Casa Quatro"],
        "gente": ["Ana", "Bruno", "Caio", "Dora"],
    }, narracao)
    assert len(memory.campaign["locations"]) == 1 + 3      # Valenport + o teto
    assert len(memory.campaign["characters"]) == 1 + 3     # Sonael + o teto


def test_fato_vira_flag(mesa):
    epilogo.aplicar({"fato": ["ponte atravessada=sim"]},
                    "A ponte fica para trás; ninguém caiu no rio.")
    assert memory.campaign["quest_flags"].get("ponte_atravessada") == "sim"


# ---------------------------------------------------------------------------
# 4b. A página do diário
#
# Medido na campanha real: 4 entradas em 91 turnos, e as poucas que existiam
# falavam de personagens com nome antigo. O diário é o que o jogador abre para
# lembrar a própria história, e nascia vazio porque add_diary_entry era mais
# uma ferramenta para lembrar NO MEIO da cena. Escrever a página depois de
# narrar é a ordem natural — é o que o bloco faz.
# ---------------------------------------------------------------------------

def test_a_linha_do_diario_e_lida_no_bloco(mesa):
    """
    A leitura só conhece os campos de `CAMPOS`. Tirar `diario` de lá faria a
    linha 'diário:' ser ignorada em silêncio — o mestre escreveria a página e
    ela não chegaria a lugar nenhum.
    """
    texto = ("A ponte cede sob a carroça.\n\n"
             "[[registro]]\ndiário: A travessia — as tábuas cederam\n[[/registro]]")
    _, campos = epilogo.extrair(texto)
    assert campos["diario"] == ["A travessia — as tábuas cederam"]


def test_pagina_de_diario_entra_pelo_fechamento(mesa):
    memory.campaign["diary"] = []
    r = epilogo.aplicar(
        {"diario": ["A travessia da ponte — as tábuas cederam e a carroça "
                    "ficou no rio; o grupo seguiu a pé até o anoitecer"]},
        "A ponte cede sob a carroça.")
    assert r["recusados"] == []
    entrada = memory.campaign["diary"][-1]
    assert entrada["title"] == "A travessia da ponte"
    assert "carroça" in entrada["content"]
    assert entrada["chapter"] == memory.campaign["chapter"]


def test_pagina_sem_titulo_ainda_vira_entrada(mesa):
    """Sem o travessão, o próprio texto vira título curto — nada se perde."""
    memory.campaign["diary"] = []
    texto = "O grupo perdeu a carroça na travessia e chegou a pé ao anoitecer"
    epilogo.aplicar({"diario": [texto]}, "A ponte cede sob a carroça.")
    entrada = memory.campaign["diary"][-1]
    assert entrada["content"] == texto
    assert entrada["title"] and entrada["title"] in texto


def test_pagina_curta_demais_e_recusada(mesa):
    """
    "Fomos à ponte" não é memória: é legenda. Página curta enche o diário de
    linha que não ajuda o jogador a lembrar de nada.
    """
    memory.campaign["diary"] = []
    r = epilogo.aplicar({"diario": ["A ponte — caiu"]}, "A ponte cede.")
    assert memory.campaign["diary"] == []
    assert any("diario" in x for x in r["recusados"]), r["recusados"]


def test_uma_pagina_de_diario_por_turno(mesa):
    memory.campaign["diary"] = []
    epilogo.aplicar({"diario": [
        "A travessia — as tábuas cederam e a carroça ficou no rio para sempre",
        "O acampamento — a noite passou em silêncio e ninguém dormiu direito",
    ]}, "A ponte cede; à noite, o acampamento fica em silêncio.")
    assert len(memory.campaign["diary"]) == 1


# ---------------------------------------------------------------------------
# 5. O caminho inteiro, e a promessa de não derrubar o turno
# ---------------------------------------------------------------------------

def test_processar_limpa_o_texto_e_registra(mesa):
    texto = (
        "Aldric aponta para a Ponte Quebrada enquanto o sol desce.\n\n"
        "[[registro]]\n"
        "local: Ponte Quebrada\n"
        "tempo: 2h — viagem pela trilha\n"
        "lugar: Ponte Quebrada — tábuas podres sobre o rio\n"
        "gente: Aldric — ferreiro da vila\n"
        "[[/registro]]\n"
    )
    limpo, registro = epilogo.processar(texto)
    assert "[[registro]]" not in limpo and "Ponte Quebrada" in limpo
    assert registro["tinha_bloco"] is True
    assert len(registro["feitos"]) == 4
    assert memory.campaign["current_location"] == "Ponte Quebrada"
    assert memory.campaign["relogio"]["hora"] == 10
    assert "ponte quebrada" in memory.campaign["locations"]
    assert "aldric" in memory.campaign["characters"]


def test_bloco_torto_nao_derruba_o_turno(mesa):
    texto = "A cena segue.\n[[registro]]\nlocal:\ntempo: banana\nfato: sem igual\n[[/registro]]"
    limpo, registro = epilogo.processar(texto)
    assert limpo == "A cena segue."
    assert registro["feitos"] == []


# ---------------------------------------------------------------------------
# 6. Está ligado: no prompt do mestre e no caminho do servidor
# ---------------------------------------------------------------------------

def test_o_prompt_manda_fechar_todo_turno(campanha):
    from rpg.agent import create_agent

    agente = create_agent("gemini-2.5-flash", "fantasia", dnd_mode=True)
    # A instrução é recomputada a cada turno (provider): é o texto dela que
    # vale, não o da criação.
    instrucao = agente.instruction() if callable(agente.instruction) else agente.instruction
    assert "[[registro]]" in instrucao and "[[/registro]]" in instrucao
    # Todo campo que o servidor sabe aplicar tem de estar ensinado no prompt —
    # pelo nome como ele é ESCRITO, com acento ("relação:").
    for campo in epilogo.CAMPOS:
        assert f"{epilogo.ESCRITO.get(campo, campo)}:" in instrucao, campo
    # É a última coisa que ele lê antes de escrever.
    assert instrucao.rstrip().endswith("você vai escrever.")
    # E diz o que NÃO entra no bloco.
    assert "ANTES da narração" in instrucao


def test_o_servidor_fecha_o_turno_de_verdade():
    """
    Dá para apagar a chamada do servidor e os testes acima continuam verdes:
    eles exercitam o módulo, não o caminho. Este olha o caminho.
    """
    import inspect

    import server

    fonte = inspect.getsource(server.chat)
    assert "epilogo.processar(response_text)" in fonte
    assert "medicao.registrar_turno" in fonte
    # O texto que segue para a tela e para o histórico é o limpo.
    assert fonte.index("epilogo.processar(response_text)") < fonte.index("'type': 'text'")
