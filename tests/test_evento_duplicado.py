"""
test_evento_duplicado.py

O mesmo acontecimento, duas vezes.

O mestre narrava a emboscada, chamava save_event e, no turno seguinte,
chamava de novo com o mesmo resumo e outra consequência. A ficha do local e a
do personagem passaram a mostrar o que aconteceu — e mostravam a cena
duplicada, com dois textos que se contradiziam.

Regra: resumo igual (sem caixa, acento nem pontuação) COMPLETA o evento que
já existe em vez de virar linha nova.
"""
from rpg import memory, tools as tl


def _eventos():
    return memory.campaign["events"]


def test_segundo_registro_igual_nao_duplica(campanha):
    tl.save_event("Emboscada de goblins derrotada.", "Thorn", "Trilha da Montanha")
    saida = tl.save_event("Emboscada de goblins derrotada.", "Thorn", "Trilha da Montanha")
    assert len(_eventos()) == 1
    assert saida.startswith("Nota:") and "#1" in saida


def test_resumo_igual_com_outra_pontuacao_ou_caixa_tambem_e_o_mesmo(campanha):
    tl.save_event("Emboscada de goblins derrotada.", "Thorn")
    tl.save_event("emboscada de goblins derrotada", "Thorn")
    tl.save_event("EMBOSCADA DE GOBLINS DERROTADA!", "Thorn")
    assert len(_eventos()) == 1


def test_o_segundo_completa_os_campos_vazios_do_primeiro(campanha):
    tl.save_event("Emboscada de goblins derrotada.", "Thorn")
    saida = tl.save_event("Emboscada de goblins derrotada.", "Thorn",
                          "Trilha da Montanha", "O caminho às ruínas ficou livre.")
    e = _eventos()[0]
    assert e["location"] == "Trilha da Montanha"
    assert e["consequence"] == "O caminho às ruínas ficou livre."
    assert "preenchidos" in saida


def test_o_que_ja_estava_escrito_nao_e_trocado(campanha):
    tl.save_event("Emboscada de goblins derrotada.", "Thorn", "Trilha da Montanha",
                  "O grupo seguiu para as ruínas.")
    tl.save_event("Emboscada de goblins derrotada.", "Lyra", "Outro Lugar",
                  "Outra coisa qualquer.")
    e = _eventos()[0]
    assert e["characters_involved"] == "Thorn"
    assert e["location"] == "Trilha da Montanha"
    assert e["consequence"] == "O grupo seguiu para as ruínas."


def test_acontecimento_diferente_continua_entrando(campanha):
    tl.save_event("Emboscada de goblins derrotada.", "Thorn")
    tl.save_event("Emboscada de goblins na ponte derrotada.", "Thorn")
    assert len(_eventos()) == 2
    assert [e["index"] for e in _eventos()] == [1, 2]


def test_a_ficha_do_local_deixa_de_mostrar_a_cena_em_dobro(campanha):
    from rpg import locais

    memory.campaign["locations"] = {
        "trilha da montanha": {"name": "Trilha da Montanha", "description": "", "dentro_de": ""}}
    tl.save_event("Emboscada de goblins derrotada.", "Thorn", "Trilha da Montanha",
                  "O grupo derrotou dois batedores.")
    tl.save_event("Emboscada de goblins derrotada.", "Thorn", "Trilha da Montanha",
                  "Os heróis recolheram os espólios.")
    f = locais.ficha("Trilha da Montanha")
    assert len(f["eventos"]) == 1 and f["acontecimentos"] == 1
