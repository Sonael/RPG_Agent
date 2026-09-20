"""
test_chat_sem_jargao_navegador.py

O chat fala português, não nome de função.

Cada turno mostra o que o mestre fez com as ferramentas. Os nomes vinham em
inglês, crus, quando não havia rótulo — `spawn_monster`, `roll_initiative`,
`set_battlefield` — e o argumento era o PRIMEIRO da chamada, cortado no
caractere 40, o que dava `"Alistair Vane, Lyra Sunwhisper, Pip, Gob"` e
`"trilha de terra batida; margem com arbus"`. Junto disso, recusa de
ferramenta chegava inteira ao jogador, escrita para a IA.

Depende do Playwright, que não está em requirements-dev.txt. Sem ele o arquivo
é pulado:

    pip install playwright && playwright install chromium
"""
import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

pytest.importorskip("playwright.sync_api",
                    reason="Playwright não instalado — veja o docstring")

sys.path.insert(0, str(RAIZ / "scripts"))

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def pagina():
    import capturar_telas as cap
    from playwright.sync_api import sync_playwright

    campanha = json.loads((RAIZ / "scripts" / "temp.json").read_text(encoding="utf-8"))
    nome = campanha.get("name") or "Crônicas de Oakhaven"
    campanha["name"] = nome
    url, parar = cap._subir_servidor(campanha, nome)
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        ctx = nav.new_context(viewport={"width": 1440, "height": 980})
        ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO))
        pg = ctx.new_page()
        erros = []
        pg.on("pageerror", lambda e: erros.append(str(e)))
        pg.goto(f"{url}/game.html", wait_until="networkidle")
        cap._sanear(pg)
        try:
            yield pg, erros
        finally:
            nav.close()
            parar()


def test_toda_ferramenta_tem_nome_em_portugues(pagina):
    """O rótulo vem de TOOL_LABEL; sem ele, o jogador lê o nome da função."""
    pg, erros = pagina
    from rpg import tools, tools_dnd

    nomes = sorted({f.__name__ for f in list(tools.ALL_TOOLS) + list(tools_dnd.DND_TOOLS)})
    sem_rotulo = pg.evaluate("(nomes) => nomes.filter(n => !TOOL_LABEL[n])", nomes)
    assert sem_rotulo == [], sem_rotulo
    # E nenhum rótulo é o próprio nome da função disfarçado.
    iguais = pg.evaluate("(nomes) => nomes.filter(n => TOOL_LABEL[n] === n)", nomes)
    assert iguais == [], iguais
    assert not erros, erros[:3]


@pytest.mark.parametrize("args, esperado", [
    ({"characters_names": "Alistair Vane, Lyra Sunwhisper, Pip, Goblin 1"},
     "Alistair Vane, Lyra Sunwhisper…"),
    ({"quantity": 3}, ""),                       # número solto não diz nada
    ({"monster_name": "goblin", "quantity": 3}, "goblin"),
    ({"zones": "trilha de terra batida, margem com arbustos densos"},
     "trilha de terra batida, margem…"),
    ({"name": "Pip", "side": "aliado"}, "Pip"),
    ({}, ""),
    ({"done": True}, ""),
])
def test_o_argumento_mostrado_e_o_que_interessa(pagina, args, esperado):
    pg, _ = pagina
    assert pg.evaluate("(a) => window._argDaFerramenta(a)", args) == esperado


def test_o_corte_nao_parte_palavra_ao_meio(pagina):
    pg, _ = pagina
    texto = pg.evaluate("() => window._argDaFerramenta({reason: 'a patrulha que voltou da Floresta Sombria'})")
    assert texto.endswith("…")
    assert not texto.rstrip("…").endswith(" ")
    for pedaco in texto.rstrip("…").split():
        assert pedaco in "a patrulha que voltou da Floresta Sombria".split(), pedaco


def test_o_log_do_turno_sai_em_portugues(pagina):
    """As chamadas são as do log de uma partida de verdade, na mesma ordem em
    que os argumentos chegam: quantity antes do nome do monstro, a lista
    inteira de iniciativa, as zonas com a descrição junto."""
    pg, erros = pagina
    pg.evaluate("""() => appendToolLog([
        {name: 'spawn_monster', args: {quantity: 3, monster_name: 'goblin'}, kind: 'write'},
        {name: 'roll_initiative', args: {characters_names: 'Alistair Vane, Lyra Sunwhisper, Pip, Goblin 1, Goblin 2, Goblin 3'}, kind: 'write'},
        {name: 'set_battlefield', args: {zones: 'Trilha Principal, Margem Esquerda, Bosque Denso', description: 'trilha de terra batida; margem com arbustos densos'}, kind: 'write'}])""")
    texto = pg.inner_text("#chat-history .tool-log >> nth=-1")
    assert "trazendo criatura" in texto and "rolando iniciativa" in texto and "montando o campo" in texto
    assert "spawn_monster" not in texto and "roll_initiative" not in texto
    # O que aparecia antes: o primeiro argumento, cortado no meio da palavra.
    assert '"3"' not in texto, texto
    assert "goblin" in texto
    assert "Gob\"" not in texto and "Gob…" not in texto, texto
    assert "arbus" not in texto, texto
    assert not erros, erros[:3]


# ---- Recusa e falha de ferramenta ------------------------------------------

def _sistema(pg, tool, content):
    return pg.evaluate("([t, c]) => { const row = appendDiceResultLog(t, c);"
                       " return row ? row.innerText : null; }", [tool, content])


def test_recado_de_motor_nao_vira_cartao_no_chat(pagina):
    pg, erros = pagina
    antes = pg.locator("#chat-history .msg-row.system").count()
    saida = _sistema(pg, "move_combatant",
                     "Erro: move_combatant não está disponível agora: o combate é resolvido "
                     "na tela tática, e o jogador age por lá. Não tente de novo; espere "
                     "[COMBATE RESOLVIDO NA TELA TÁTICA] para narrar.")
    assert saida is None, saida
    assert pg.locator("#chat-history .msg-row.system").count() == antes
    assert not erros, erros[:3]


def test_o_que_sobra_da_recusa_e_a_parte_da_historia(pagina):
    pg, _ = pagina
    saida = _sistema(pg, "update_quest_objective",
                     "Erro: Objetivo inválido. Use update_quest_objective(missão, objetivo) "
                     "com o texto exato do passo.")
    assert saida is not None
    assert "Objetivo inválido" in saida
    assert "update_quest_objective" not in saida


def test_resultado_normal_passa_inteiro(pagina):
    pg, _ = pagina
    saida = _sistema(pg, "attack_roll",
                     "Stelar ataca Goblin 1 com Montante: d20=17 +5 = 22 vs CA 15 — ACERTO! "
                     "Dano: 8. Goblin 1: 7 → 0/7 DERROTADO!")
    assert "DERROTADO" in saida and "Goblin 1: 7 → 0/7" in saida
