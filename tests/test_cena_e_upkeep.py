"""
test_cena_e_upkeep.py

Dois defeitos relatados em jogo:

  1. Combate entrava com NPC que não estava na cena — de um lado ou do outro.
     A raiz: não existe registro de quem está presente. O que havia era o bloco
     "ESTADO ATUAL DA CENA", rotulado só "Personagens:", que o agente lia como
     elenco da cena — e a instrução mandava confiar nele "para saber quem está
     presente". Ele então rolava iniciativa para gente de outro ponto da
     história.

  2. O mestre esquecia de salvar personagem, trocar o local, escrever no diário
     e atualizar o resumo.

Os testes cobrem os três consertos: o rótulo honesto da lista, a trava
mecânica sobre a iniciativa, e os contadores de manutenção.
"""
import pytest

from rpg import memory


# ---------------------------------------------------------------------------
# 1. A lista de personagens da cena não pode se passar por elenco
# ---------------------------------------------------------------------------

def test_lista_de_personagens_avisa_que_nao_e_elenco(campanha):
    from rpg.tools import get_scene_context

    campanha["current_location"] = "Câmara Funerária"
    campanha["party"] = [{"name": "Valen", "role": "mago", "notes": ""}]
    campanha["characters"] = {
        "valen":  {"name": "Valen", "status": "vivo", "description": "Mago",
                   "traits": "", "notes": ""},
        "dayene": {"name": "Dayene", "status": "vivo",
                   "description": "Curandeira da Câmara Funerária",
                   "traits": "", "notes": ""},
    }

    ctx = get_scene_context()

    # Quem é do grupo está marcado; ninguém mais é declarado presente.
    assert "Valen [grupo]" in ctx
    assert "Dayene [grupo]" not in ctx
    assert "podem não estar presentes agora" in ctx
    # O rótulo antigo prometia elenco de cena.
    assert "\nPersonagens:\n" not in ctx


def test_sem_grupo_nem_local_o_rotulo_avisa_que_e_a_campanha_inteira(campanha):
    from rpg.tools import get_scene_context

    campanha["current_location"] = ""
    campanha["party"] = []
    campanha["characters"] = {
        "brida": {"name": "Brida", "status": "vivo", "description": "Guerreira",
                  "traits": "", "notes": ""},
    }

    ctx = get_scene_context()
    assert "campanha INTEIRA" in ctx


# ---------------------------------------------------------------------------
# 2. Iniciativa com quem não foi narrado na cena
# ---------------------------------------------------------------------------

@pytest.fixture
def verificador():
    """
    _check_combatants_offscene vive em server.py, que puxa Flask e o resto do
    app. Importado sob demanda para não pesar na coleta dos testes do motor.
    """
    import server
    return server


def _montar_combate(campanha, nomes, grupo=()):
    campanha["characters"] = {}
    for n in nomes:
        campanha["characters"][memory.char_key(n)] = {
            "name": n, "status": "vivo", "description": "", "traits": "",
            "notes": "", "party_member": n in grupo, "sheet": None,
        }
    campanha["party"] = [{"name": n, "role": "", "notes": ""} for n in grupo]
    campanha["combat_state"]["is_active"] = True
    campanha["combat_state"]["initiative_order"] = list(nomes)


def test_npc_fora_da_narracao_e_barrado(campanha, verificador):
    _montar_combate(campanha, ["Valen", "Bandido 1", "Dayene"], grupo=["Valen"])
    texto = "Um bandido salta da moita e ataca Valen na entrada da câmara."

    v = verificador._check_combatants_offscene(texto)

    assert len(v) == 1
    assert "Dayene" in v[0]
    assert "Bandido" not in v[0]      # o plural "bandido" está na narração


def test_mob_numerado_casa_pelo_plural(campanha, verificador):
    _montar_combate(campanha,
                    ["Valen", "Bandido 1", "Bandido 2", "Bandido 3"],
                    grupo=["Valen"])
    texto = "Três bandidos cercam o grupo."

    assert verificador._check_combatants_offscene(texto) == []


def test_grupo_nao_precisa_ser_nomeado(campanha, verificador):
    # A narração trata o grupo por "vocês" — comum, e não é erro.
    _montar_combate(campanha, ["Valen", "Soraya", "Lobisomem"],
                    grupo=["Valen", "Soraya"])
    texto = "O lobisomem avança sobre vocês."

    assert verificador._check_combatants_offscene(texto) == []


def test_acento_e_caixa_nao_atrapalham(campanha, verificador):
    _montar_combate(campanha, ["Valen", "Acólito Fanático"], grupo=["Valen"])
    texto = "Um acolito fanatico ergue o punhal."

    assert verificador._check_combatants_offscene(texto) == []


def test_fora_de_combate_nao_verifica(campanha, verificador):
    _montar_combate(campanha, ["Valen", "Dayene"], grupo=["Valen"])
    campanha["combat_state"]["is_active"] = False

    assert verificador._check_combatants_offscene("nada aqui") == []


def test_roll_initiative_pode_ser_refeita_na_correcao(verificador):
    """
    O conserto de uma iniciativa errada é refazê-la. Ela SUBSTITUI o estado de
    combate inteiro em vez de somar efeito, então não pode estar na lista de
    ferramentas proibidas na correção — senão o prompt manda consertar e
    proíbe o conserto na mesma mensagem.
    """
    prompt = verificador._build_correction_prompt(
        ["iniciativa com gente fora da cena"],
        already_called={"roll_initiative", "attack_roll"},
    )
    assert "roll_initiative" not in prompt.split("NÃO devem ser chamadas novamente:")[-1]
    assert "attack_roll" in prompt


# ---------------------------------------------------------------------------
# 3. Contadores de manutenção
# ---------------------------------------------------------------------------

def test_turnos_sem_conta_desde_a_ultima_marcacao(campanha):
    campanha["_turno"] = 0
    campanha.pop("_upkeep", None)

    assert memory.turnos_sem("resumo") == -1        # nunca feito

    memory.marcar_upkeep("resumo")
    assert memory.turnos_sem("resumo") == 0

    for _ in range(4):
        memory.avancar_turno()
    assert memory.turnos_sem("resumo") == 4


def test_ferramentas_marcam_a_manutencao(campanha):
    from rpg import tools

    campanha["_turno"] = 0
    campanha.pop("_upkeep", None)
    campanha["diary"] = []

    tools.update_story_summary("O grupo desceu à cripta.")
    tools.add_diary_entry("A cripta", "Desceram pelas escadas de pedra.")
    tools.update_world_state(current_location="Cripta")

    for chave in ("resumo", "diario", "mundo"):
        assert memory.turnos_sem(chave) == 0, chave


def test_update_world_state_sem_local_nem_cena_nao_marca(campanha):
    from rpg import tools

    campanha["_turno"] = 0
    campanha.pop("_upkeep", None)

    tools.update_world_state(chapter=2)     # só o capítulo
    assert memory.turnos_sem("mundo") == -1


# ---------------------------------------------------------------------------
# 4. As pendências chegam ao mestre
# ---------------------------------------------------------------------------

def test_bloco_de_pendencias_cobra_com_numero(campanha):
    from rpg.agent import _pendencias_block

    campanha["_turno"] = 0
    campanha.pop("_upkeep", None)
    campanha.pop("_pendencias", None)

    memory.marcar_upkeep("resumo")
    memory.marcar_upkeep("diario")
    memory.marcar_upkeep("mundo")
    for _ in range(7):
        memory.avancar_turno()

    bloco = _pendencias_block()
    assert "PENDÊNCIAS DE MEMÓRIA" in bloco
    # O resumo continua sendo ferramenta e é cobrado pelo nome dela. Local,
    # cena e diário saem do fechamento, e a cobrança pede a LINHA — pedir a
    # ferramenta aqui e o bloco lá em cima eram duas ordens para a mesma coisa.
    assert "7 turnos sem update_story_summary()" in bloco    # limite 5
    assert "7 turnos sem o local e a cena atuais" in bloco   # limite 6
    assert "'local:'" in bloco and "'cena:'" in bloco
    assert "update_world_state()" not in bloco
    assert "diário" not in bloco                             # limite 8, ainda não


def test_bloco_vazio_quando_esta_tudo_em_dia(campanha):
    from rpg.agent import _pendencias_block

    campanha["_turno"] = 0
    campanha.pop("_upkeep", None)
    campanha.pop("_pendencias", None)
    for chave in ("resumo", "diario", "mundo"):
        memory.marcar_upkeep(chave)

    assert _pendencias_block() == ""


def test_avisos_do_validador_voltam_como_suspeita(campanha):
    """
    São heurística de texto, e erram: nome de passagem vira "lugar novo",
    figurante vira "personagem sem ficha". Chegavam ao mestre sob o carimbo
    "verificado pelo sistema, não é opinião" — convite a registrar lugar e
    gente que a história nunca teve.
    """
    from rpg.agent import _pendencias_block

    campanha["_turno"] = 0
    campanha.pop("_upkeep", None)
    campanha["_pendencias"] = ["'Dayene' parece ser um personagem novo mas não foi salvo."]

    bloco = _pendencias_block()
    # O cabeçalho deixou de ser "SUSPEITAS DO VERIFICADOR": as duas regras que
    # alimentam esta lista passaram a só falar de nome que VOLTOU (apareceu em
    # dois turnos). Continua sendo heurística sobre prosa, mas de um sinal
    # melhor — e o texto agora diz o que é, em vez de pedir desconfiança.
    assert "O QUE JÁ VOLTOU E CONTINUA FORA DA MEMÓRIA" in bloco
    assert "Dayene" in bloco
    assert "NÃO invente detalhe" in bloco
    # E não entra no bloco dos contadores, que é fato.
    assert "PENDÊNCIAS DE MEMÓRIA" not in bloco


def test_o_que_e_contado_e_o_que_e_suspeita_ficam_separados(campanha):
    from rpg.agent import _pendencias_block

    campanha["_turno"] = 0
    campanha.pop("_upkeep", None)
    memory.marcar_upkeep("resumo")
    memory.marcar_upkeep("diario")
    memory.marcar_upkeep("mundo")
    for _ in range(7):
        memory.avancar_turno()
    campanha["_pendencias"] = ["Local 'Ponte Quebrada' mencionado mas não registrado na memória."]

    bloco = _pendencias_block()
    contado, _, suspeito = bloco.partition("O QUE JÁ VOLTOU E CONTINUA FORA")
    assert "PENDÊNCIAS DE MEMÓRIA (contado pelo sistema" in contado
    assert "7 turnos sem update_story_summary()" in contado
    assert "Ponte Quebrada" not in contado, "suspeita não pode virar contagem"
    assert "Ponte Quebrada" in suspeito


def test_campanha_nova_nao_e_cobrada(campanha):
    from rpg.agent import _pendencias_block

    campanha["_turno"] = 2          # acabou de começar
    campanha.pop("_upkeep", None)
    campanha.pop("_pendencias", None)

    assert _pendencias_block() == ""
