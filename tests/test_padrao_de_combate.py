"""
test_padrao_de_combate.py

O padrão do jogo passou a ser a TELA TÁTICA.

Era "narrado" desde o começo — de quando a tela tática ainda não existia. Hoje
é ela quem rola o dado, conta o dano, gasta munição, cobra alcance e move na
zona; o modo narrado pede à IA que faça tudo isso de cabeça, que é justamente
onde ela erra. Quem preferir a narração continua a um clique na engrenagem.

A parte que não é óbvia é a VIRADA. Mudar a constante sozinha não alcançaria
nenhuma campanha que já existe: todas têm "narrado" gravado no documento,
porque o padrão antigo era escrito na criação. Elas ficariam narradas para
sempre, e quem pediu a troca não veria diferença nenhuma no próprio jogo.

A marca `_padrao_combate_migrado` faz a virada acontecer uma vez por campanha.
Depois dela a escolha é do jogador e fica.
"""
import pytest

from rpg import memory


def test_o_padrao_do_jogo_e_a_tela():
    assert memory.PADRAO_COMBATE == "tela"
    assert memory._defaults()["combat_mode"] == "tela"


def test_campanha_nova_nasce_na_tela(campanha):
    assert memory._defaults()["combat_mode"] == memory.PADRAO_COMBATE


def test_campanha_sem_o_campo_ganha_o_padrao(campanha):
    campanha.pop("combat_mode", None)
    campanha.pop("_padrao_combate_migrado", None)
    memory.normalizar_campanha()
    assert campanha["combat_mode"] == "tela"


# ---------------------------------------------------------------------------
# A virada, uma vez por campanha
# ---------------------------------------------------------------------------

def test_campanha_antiga_narrada_vira_tela_uma_vez(campanha):
    """O caso real: toda campanha já criada tem "narrado" GRAVADO."""
    campanha["combat_mode"] = "narrado"
    campanha.pop("_padrao_combate_migrado", None)

    memory.normalizar_campanha()

    assert campanha["combat_mode"] == "tela"
    assert campanha["_padrao_combate_migrado"] is True


def test_quem_escolhe_narrado_depois_continua_narrado(campanha):
    """
    Sem isto, a engrenagem viraria um botão que não funciona: o jogador
    escolhe "narrado" e o carregamento seguinte o joga de volta na tela.
    """
    campanha["combat_mode"] = "narrado"
    campanha.pop("_padrao_combate_migrado", None)
    memory.normalizar_campanha()          # a virada acontece aqui

    campanha["combat_mode"] = "narrado"   # o jogador escolhe, de propósito
    memory.normalizar_campanha()

    assert campanha["combat_mode"] == "narrado"


def test_a_marca_sobrevive_ao_save_load():
    """Sem persistir a marca, a virada se repete a cada carregamento."""
    import server

    assert "_padrao_combate_migrado" in memory._defaults()
    assert "_padrao_combate_migrado" in server._payload_de_campanha("Nova", {}, {})


def test_campanha_importada_do_modo_narrado_e_respeitada():
    """
    Importar não é carregar uma campanha antiga: quem exportou em "narrado"
    exportou uma escolha, e ela chega já migrada.
    """
    import server

    vinda = server._payload_de_campanha(
        "Vinda", {"combat_mode": "narrado", "_padrao_combate_migrado": True}, {})
    assert vinda["combat_mode"] == "narrado"


def test_importacao_sem_o_campo_nasce_na_tela():
    import server

    nova = server._payload_de_campanha("Nova", {}, {})
    assert nova["combat_mode"] == "tela"


# ---------------------------------------------------------------------------
# O padrão vale para o motor inteiro, não só para a tela
# ---------------------------------------------------------------------------

def test_o_padrao_tem_um_lugar_so():
    """
    Estava escrito em cinco arquivos. Mudar significava achar os cinco — e
    quem esquecesse um deixaria o motor discordando da tela sobre qual é o
    modo da campanha.
    """
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1]
    for arquivo in ("server.py", "rpg/toolsets.py", "rpg/tools_dnd.py"):
        fonte = (raiz / arquivo).read_text(encoding="utf-8")
        assert '"combat_mode", "narrado"' not in fonte, arquivo
        assert '"combat_mode") or "narrado"' not in fonte, arquivo


# O efeito do padrão sobre as ferramentas entregues à LLM (com a tela, ela não
# pode ter as de turno, ou o combate acontece duas vezes) é medido onde está a
# bancada para isso: test_toolsets.py, em
# test_campo_de_modo_ausente_usa_o_padrao_do_jogo.


# ---------------------------------------------------------------------------
# A tela e a ajuda contam a mesma história
# ---------------------------------------------------------------------------

def test_a_engrenagem_abre_marcando_a_tela():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "static" / "js" / "barra.js"
          ).read_text(encoding="utf-8")
    assert 'data-mode="tela" class="cm-opt active"' in js
    assert 'data-mode="narrado" class="cm-opt active"' not in js


def test_a_ajuda_diz_qual_e_o_padrao():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "static" / "js" / "utils.js"
          ).read_text(encoding="utf-8")
    assert "<b>Tela tática</b> (padrão)" in js


def test_o_readme_diz_qual_e_o_padrao():
    from pathlib import Path

    doc = (Path(__file__).resolve().parents[1] / "README.md"
           ).read_text(encoding="utf-8")
    assert '**`"tela"`** (default' in doc
    assert '**`"narrado"`** (default' not in doc
    assert "_padrao_combate_migrado" in doc, "a virada precisa estar documentada"
