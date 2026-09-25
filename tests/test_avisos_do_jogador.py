"""
test_avisos_do_jogador.py

O painel de avisos fala com o JOGADOR.

O verificador é uma heurística que compara a narração com a memória da
campanha. Os textos dele nasceram para o mestre — "o agente deveria ter
chamado save_character automaticamente" — e apareciam assim no painel do
jogo, que é onde o jogador lê. Recado de ferramenta não é assunto de quem
está jogando: ele não chama ferramenta nenhuma.

Agora cada aviso tem dois textos: `message`, que continua indo ao mestre nas
pendências do turno seguinte, e `jogador`, escrito na língua da história, que
é o que a tela mostra. Aviso sem texto de jogador não aparece para ele.
"""
import pytest

from rpg import memory, validator

from conftest import criar_ficha


FERRAMENTAS = ("save_character", "save_location", "advance_time", "modify_hp",
               "update_quest_objective", "o agente", "flag", "memória")


@pytest.fixture
def campanha_com_gente(campanha, povoar):
    povoar(criar_ficha("Alden", grupo=True))
    memory.campaign["characters"]["bruna"] = {
        "name": "Bruna", "status": "morta", "description": "", "traits": "", "notes": "",
    }
    memory.campaign["characters"]["caio"] = {
        "name": "Caio", "status": "preso", "description": "", "traits": "", "notes": "",
    }
    memory.campaign["locations"] = {"taverna do corvo": {"name": "Taverna do Corvo"}}
    memory.campaign["quest_flags"] = {"portao_do_castelo": "fechado"}
    return memory.campaign


def _por_regra(texto):
    return {v.rule: v for v in validator.validate(texto).violations}


# As duas regras de heurística pura — lugar fora do mapa e gente sem ficha —
# só cobram na REPETIÇÃO. Nome que aparece uma vez é cenário: "a estrada sobe
# rumo ao Passo de Vhar" não pede um verbete de mapa. Nome que volta em outro
# turno é lugar (ou gente) de verdade que o mestre esqueceu de registrar.
#
# `_voltando` é o que o jogo faz: a mesma cena aparece em dois turnos.

def _voltando_lista(texto):
    memory.campaign["_turno"] = (memory.campaign.get("_turno") or 0) + 1
    validator.validate(texto)
    memory.campaign["_turno"] = memory.campaign["_turno"] + 1
    return validator.validate(texto).violations


def _voltando(texto):
    return {v.rule: v for v in _voltando_lista(texto)}


def test_morto_em_cena_fala_de_historia_e_nao_de_ferramenta(campanha_com_gente):
    v = _por_regra("Bruna ergue a espada e avança contra vocês.")["dead_character_active"]
    assert v.severity == "erro"
    assert v.titulo == "Alguém que já morreu aparece em cena"
    assert "Bruna" in v.jogador and "morta" in v.jogador
    assert "lembrança" in v.jogador                      # diz quando ignorar
    assert not any(t in v.jogador for t in FERRAMENTAS), v.jogador
    # O trecho da narração vai junto, para o jogador ver de onde veio.
    assert "Bruna" in v.detail


def test_a_primeira_mencao_nao_vira_aviso(campanha_com_gente):
    """
    Cena nova cita nome próprio o tempo todo. Cobrar ficha e verbete de mapa
    na primeira aparição enchia o painel de aviso falso — o jogador aprende a
    ignorar o painel, e o mestre registra figurante que nunca mais volta.
    """
    achados = _por_regra("Aldric, o ferreiro, aponta para a Ponte Quebrada.")
    assert "unsaved_character" not in achados
    assert "unknown_location" not in achados


def test_gente_e_lugar_que_voltam_nao_pedem_nada_ao_jogador(campanha_com_gente):
    achados = _voltando("Aldric, o ferreiro, aponta para a Ponte Quebrada.")
    novo = achados["unsaved_character"]
    assert novo.titulo == "Gente que voltou e ainda não tem ficha"
    assert "Aldric" in novo.jogador
    # Sem promessa: prometer registro faria o jogador cobrar do mestre coisa
    # que não vai (nem deve) acontecer por conta de um aviso.
    assert "já foi avisado" not in novo.jogador
    assert not any(t in novo.jogador for t in FERRAMENTAS), novo.jogador
    # O texto do mestre continua dizendo o que ele tem de fazer.
    assert "save_character" in novo.message

    lugar = achados["unknown_location"]
    assert lugar.titulo == "Lugar que voltou e ainda não está no mapa"
    assert "Ponte Quebrada" in lugar.jogador
    assert not any(t in lugar.jogador for t in FERRAMENTAS), lugar.jogador
    assert "save_location" in lugar.message
    assert lugar.detail and "save_location" not in lugar.detail


def test_preso_em_cena_e_contradicao_de_anotacao(campanha_com_gente):
    v = _por_regra("Caio entra na sala e diz que trouxe o pão.")["gone_character_present"]
    assert v.titulo == "Alguém que não deveria estar aqui"
    assert "Caio" in v.jogador and "preso" in v.jogador
    assert not any(t in v.jogador for t in FERRAMENTAS), v.jogador

    flag = _por_regra("O portao do castelo está aberto de par em par.")["flag_contradiction"]
    assert flag.titulo == "A cena contradiz o que está anotado"
    # Sem nome de flag com underline na cara do jogador.
    assert "portao do castelo" in flag.jogador and "portao_do_castelo" not in flag.jogador
    assert "portao_do_castelo" in flag.message


def test_relogio_parado_continua_so_para_o_mestre(campanha_com_gente):
    memory.campaign["relogio"] = {"dia": 1, "hora": 8}
    memory.campaign["_upkeep"] = {}
    memory.campaign["_turno"] = 5
    v = _por_regra("No dia seguinte, a caravana parte ao amanhecer.").get("time_not_advanced")
    assert v is not None
    assert v.jogador == "", "o jogador não tem como fazer o relógio andar"
    assert "advance_time" in v.message


def test_todo_aviso_do_jogador_tem_titulo_e_nenhum_cita_ferramenta(campanha_com_gente):
    texto = ("Bruna ergue a espada. Caio entra na sala e diz que trouxe o pão. "
             "Aldric, o ferreiro, aponta para a Ponte Quebrada. "
             "O portao do castelo está aberto de par em par.")
    memory.campaign["_turno"] = (memory.campaign.get("_turno") or 0) + 1
    validator.validate(texto)                    # a cena volta no turno seguinte
    memory.campaign["_turno"] += 1
    for v in validator.validate(texto).violations:
        if not v.jogador:
            continue
        assert v.titulo, v.rule
        assert not any(t in v.jogador for t in FERRAMENTAS), (v.rule, v.jogador)
        assert "(" not in v.titulo, v.titulo


# A heurística lia o status por pedaço de palavra: procurava "morto" e deixava
# passar "morta", "desaparecida", "presa" — metade dos personagens.

@pytest.mark.parametrize("status, regra", [
    ("morta", "dead_character_active"),
    ("morto em combate", "dead_character_active"),
    ("Falecida", "dead_character_active"),
    ("desaparecida", "gone_character_present"),
    ("presa", "gone_character_present"),
])
def test_o_status_conta_no_feminino_e_com_complemento(campanha_com_gente, status, regra):
    memory.campaign["characters"]["dara"] = {
        "name": "Dara", "status": status, "description": "", "traits": "", "notes": "",
    }
    achados = _por_regra("Dara entra na sala e diz que o caminho está livre.")
    assert regra in achados, (status, list(achados))
    assert "Dara" in achados[regra].jogador


@pytest.mark.parametrize("status", ["vivo", "viva", "impressionado", "ferida", "apresentada"])
def test_status_comum_nao_vira_aviso(campanha_com_gente, status):
    memory.campaign["characters"]["dara"] = {
        "name": "Dara", "status": status, "description": "", "traits": "", "notes": "",
    }
    achados = _por_regra("Dara entra na sala e diz que o caminho está livre.")
    assert "dead_character_active" not in achados and "gone_character_present" not in achados, status


# O que o servidor manda para a tela (validator.para_o_jogador): é aqui que o
# texto de mestre deixa de vazar para o painel do jogo.

def _payload(texto, voltando=False):
    if voltando:
        memory.campaign["_turno"] = (memory.campaign.get("_turno") or 0) + 1
        validator.validate(texto)
        memory.campaign["_turno"] += 1
    brutos = [
        {"severity": v.severity, "rule": v.rule, "message": v.message,
         "detail": v.detail, "titulo": v.titulo, "jogador": v.jogador}
        for v in validator.validate(texto).violations
    ]
    return brutos, validator.para_o_jogador(brutos)


def test_a_tela_recebe_o_texto_do_jogador_e_nao_o_do_mestre(campanha_com_gente):
    brutos, tela = _payload("Aldric, o ferreiro, aponta para a Ponte Quebrada.",
                            voltando=True)
    assert tela, brutos
    for aviso in tela:
        assert aviso["titulo"]
        assert not any(t in aviso["message"] for t in FERRAMENTAS), aviso
        assert "jogador" not in aviso, "o texto do mestre não vai junto"
    # E o texto do mestre continua existindo, para as pendências.
    assert any("save_character" in v["message"] for v in brutos)


def test_o_que_nao_tem_texto_de_jogador_fica_fora_da_tela(campanha_com_gente):
    """A regra é uma só: sem texto de jogador, o aviso não aparece no painel."""
    brutos = [{"severity": "aviso", "rule": "qualquer_coisa", "message": "chame uma_ferramenta()",
               "detail": "", "titulo": "", "jogador": ""}]
    assert validator.para_o_jogador(brutos) == []


def test_aviso_so_do_mestre_nao_chega_a_tela(campanha_com_gente):
    memory.campaign["relogio"] = {"dia": 1, "hora": 8}
    memory.campaign["_upkeep"] = {}
    memory.campaign["_turno"] = 5
    brutos, tela = _payload("No dia seguinte, a caravana parte ao amanhecer.")
    assert any(v["rule"] == "time_not_advanced" for v in brutos)
    assert [v["rule"] for v in tela if v["rule"] == "time_not_advanced"] == []


# A regra do lugar novo aceitava artigo solto ("o", "a"): qualquer nome
# próprio virava lugar, inclusive gente — "o Mestre de Guilda Brom".

def test_lugar_novo_so_com_preposicao_de_lugar(campanha_com_gente):
    achados = _voltando("O Mestre de Guilda Brom carimba o contrato e resmunga.")
    assert "unknown_location" not in achados, achados.get("unknown_location")

    achados = _voltando("O grupo entra na Ponte Quebrada ao amanhecer.")
    assert "unknown_location" in achados
    assert "Ponte Quebrada" in achados["unknown_location"].jogador


@pytest.mark.parametrize("frase, esperado", [
    ("Vocês seguem para a Torre de Vidro.", True),
    ("A caravana vai até o Porto Velho.", True),
    ("Ela sai do Salão de Alistamento sem olhar para trás.", True),
    ("Rumo ao Passo de Vhar, a estrada sobe.", True),
    ("A Lâmina Carmesim ergue a espada.", False),
    ("O Conselho decidiu pela guerra.", False),
])
def test_o_que_conta_como_lugar_e_o_que_nao(campanha_com_gente, frase, esperado):
    achou = "unknown_location" in _voltando(frase)
    assert achou is esperado, frase


def test_o_texto_do_jogador_nao_promete_registro(campanha_com_gente):
    """
    O aviso conta um fato ("voltou e continua fora do mapa") e para aí. Se
    prometesse registro, o jogador ficaria cobrando do mestre um efeito que
    aviso nenhum produz.
    """
    achados = _voltando("O grupo entra na Ponte Quebrada e encontra Aldric, o ferreiro.")
    for regra in ("unknown_location", "unsaved_character"):
        jogador = achados[regra].jogador
        assert "já apareceu mais de uma vez" in jogador, jogador
        assert "já foi avisado" not in jogador and "no próximo turno" not in jogador, jogador
        assert "será" not in jogador and "vai ser" not in jogador, jogador


def test_uma_cena_de_verdade_gera_um_aviso_e_nao_seis(campanha_com_gente):
    """
    Trecho real de uma partida. Com o artigo solto, a regra marcava seis
    "lugares": um pedaço do nome de uma personagem ("Sunwhisper"), uma pessoa
    ("Mestre de Guilda Brom"), um fragmento ("Guilda") e mais três. Seis
    avisos falsos por turno ensinam o jogador a ignorar o painel — e empurram
    o mestre a registrar o que não existe.
    """
    memory.campaign["characters"]["lyra sunwhisper"] = {
        "name": "Lyra Sunwhisper", "status": "vivo", "description": "", "traits": "", "notes": "",
    }
    memory.campaign["locations"]["guilda dos aventureiros"] = {"name": "Guilda dos Aventureiros"}
    cena = (
        "O calor úmido do Salão de Alistamento da Guilda dos Aventureiros envolve você. "
        "Ao seu lado, Lyra Sunwhisper mantém os olhos estreitados. Mais ao fundo, o "
        "Mestre de Guilda Brom carimba um último contrato, resmungando sobre a patrulha "
        "que voltou da Floresta Sombria. Vocês seguem para a Ponte Quebrada ao amanhecer."
    )
    lugares = [v for v in _voltando_lista(cena) if v.rule == "unknown_location"]
    assert len(lugares) == 1, [v.jogador for v in lugares]
    assert "Ponte Quebrada" in lugares[0].jogador
