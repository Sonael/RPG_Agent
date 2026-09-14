"""
test_historico_e_grimorio_vazio.py

Dois defeitos vistos ao reabrir uma campanha:

1. O chat mostrava o fechamento da tela tática como fala do jogador. A tela
   manda ao mestre "[COMBATE RESOLVIDO NA TELA TÁTICA]" com o log inteiro,
   e sendToAgent(txt, true) gravava isso no histórico como mensagem do
   jogador. Ao reabrir, renderHistory desenhava tudo no chat. O mesmo valia
   para loja, descanso, nível, Grimório, rolagem de dado e os pedidos de
   /local, /personagem e /evento.

2. O Grimório dizia "A lista da classe não respondeu" para qualquer lista
   vazia. Um patrulheiro de nível 1 ainda não tem truque nem magia: a lista
   vem vazia por regra, com o SRD respondendo. E "clerigo" sem acento perdia
   o filtro de classe e trazia magias de todas as classes.
"""
import pytest

from rpg import memory, open5e, tools_dnd as td

from conftest import criar_ficha


# ---------------------------------------------------------------------------
# 1. Histórico
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("texto, tipo", [
    ("[COMBATE RESOLVIDO NA TELA TÁTICA]\nDesfecho: VITÓRIA...", "tela"),
    ("[COMPRAS RESOLVIDAS NA TELA] O grupo terminou de negociar", "tela"),
    ("[DESCANSO RESOLVIDO NA TELA] Descanso curto concluído", "tela"),
    ("[NÍVEL RESOLVIDO NA TELA] Aria chegou ao nível 4", "tela"),
    ("[GRIMÓRIO RESOLVIDO NA TELA] Magias aprendidas: Sono", "tela"),
    ("[DADO DO JOGADOR — rolado pelo sistema, não editável] 1d20: rolei 14, total 14", "dado"),
    ("Eu abro a porta com cuidado.", ""),
    ("Quero comprar [uma corda]", ""),
])
def test_mensagem_interna_reconhecida_pelo_prefixo(texto, tipo):
    import server
    assert server._tipo_de_mensagem_interna(texto) == tipo


def test_tipo_declarado_pelo_cliente_vale_e_lixo_nao():
    import server
    assert server._tipo_de_mensagem_interna("Salve o local X", "comando") == "comando"
    assert server._tipo_de_mensagem_interna("oi", "<script>") == ""


def test_historico_antigo_ganha_a_marca_sem_perder_o_texto():
    import server
    antigo = [
        {"role": "user", "text": "Ataco o goblin."},
        {"role": "user", "text": "[COMBATE RESOLVIDO NA TELA TÁTICA]\n— Eventos —"},
        {"role": "assistant", "text": "A lâmina desce..."},
    ]
    saida = server._historico_para_a_tela(antigo)
    assert [e.get("interno", "") for e in saida] == ["", "tela", ""]
    assert saida[1]["text"].startswith("[COMBATE RESOLVIDO")
    assert "interno" not in antigo[1], "a marca não pode mudar o histórico gravado"


def test_sessao_e_memoria_entregam_o_historico_marcado():
    """As duas rotas que devolvem o histórico passam pela marcação."""
    from pathlib import Path
    import server
    fonte = Path(server.__file__).read_text(encoding="utf-8")
    assert 'entrada["interno"] = interno' in fonte
    assert fonte.count("_historico_para_a_tela(") >= 3     # definição + sessão + memória


@pytest.mark.parametrize("arquivo", ["combat.js", "shop.js", "rest.js", "levelup.js", "grimoire.js"])
def test_telas_mandam_o_fechamento_como_interno(arquivo):
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / "static" / "js" / arquivo).read_text(encoding="utf-8")
    assert "sendToAgent(txt, true, 'tela')" in js


# ---------------------------------------------------------------------------
# 2. Grimório com lista vazia
# ---------------------------------------------------------------------------

@pytest.fixture
def lyra(campanha, povoar):
    povoar(criar_ficha("Lyra", grupo=True, nivel=1, classe="patrulheiro", sabedoria=14))
    return memory.campaign["characters"]["lyra"]


def _srd_respondendo(monkeypatch, resultados=()):
    chamadas = []

    def falso(url, params=None, timeout=5.0):
        chamadas.append(dict(params or {}))
        return open5e.Response(True, {"results": list(resultados)}, 200)

    monkeypatch.setattr(open5e, "get", falso)
    return chamadas


def test_patrulheiro_nivel_1_explica_por_que_nao_ha_lista(lyra, monkeypatch):
    chamadas = _srd_respondendo(monkeypatch)

    snap = td.grimoire_snapshot("Lyra")

    assert snap["catalogo"] == []
    assert snap["catalogo_motivo"] == ("Patrulheiro ainda não aprende magias no nível 1. "
                                       "As primeiras chegam no nível 2.")
    assert "não respondeu" not in snap["catalogo_motivo"]
    assert chamadas == [], "não há o que buscar no SRD para quem ainda não aprende magia"


def test_sem_resposta_do_srd_ainda_diz_que_nao_respondeu(lyra, monkeypatch):
    lyra["sheet"]["nivel"] = 2                       # agora tem vaga; os testes rodam offline
    monkeypatch.setattr(td, "DEFAULT_SPELLS_BY_CLASS", {})
    snap = td.grimoire_snapshot("Lyra")
    assert snap["catalogo"] == []
    assert snap["catalogo_motivo"] == "A lista da classe não respondeu. Tente de novo em instantes."


def test_srd_respondendo_vazio_nao_e_falha_de_rede(lyra, monkeypatch):
    lyra["sheet"]["nivel"] = 2
    monkeypatch.setattr(td, "DEFAULT_SPELLS_BY_CLASS", {})
    _srd_respondendo(monkeypatch)
    snap = td.grimoire_snapshot("Lyra")
    assert snap["catalogo"] == [] and "não respondeu" not in snap["catalogo_motivo"]


def test_busca_sem_resultado_tem_a_propria_mensagem(lyra, monkeypatch):
    lyra["sheet"]["nivel"] = 2
    monkeypatch.setattr(td, "DEFAULT_SPELLS_BY_CLASS", {})
    _srd_respondendo(monkeypatch)
    assert td.grimoire_snapshot("Lyra", query="bola de fogo")["catalogo_motivo"] == \
        "Nenhuma magia da lista da classe com esse nome."


def test_primeiro_nivel_com_magia():
    assert td._primeiro_nivel_com_magia("patrulheiro") == 2
    assert td._primeiro_nivel_com_magia("paladino") == 2
    assert td._primeiro_nivel_com_magia("mago") == 1
    assert td._primeiro_nivel_com_magia("guerreiro") is None


@pytest.mark.parametrize("classe", ["clérigo", "clerigo", "Clerigo", "CLÉRIGO"])
def test_classe_sem_acento_mantem_o_filtro(classe, monkeypatch, campanha):
    chamadas = _srd_respondendo(monkeypatch)
    td.class_spell_catalog(classe, 1)
    assert chamadas and chamadas[0].get("dnd_class__icontains") == "cleric"


def test_classe_desconhecida_nao_consulta_sem_filtro(monkeypatch, campanha):
    chamadas = _srd_respondendo(monkeypatch)
    td.class_spell_catalog("guerreiro", 1)
    assert chamadas == [], "sem filtro de classe a consulta traria as magias de todas as classes"
