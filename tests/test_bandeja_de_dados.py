"""
test_bandeja_de_dados.py

A bandeja de dados existe desde sempre atrás de um ícone ao lado do campo de
texto — e foi usada ZERO vezes numa campanha de 91 turnos. Isso era só uma
curiosidade até a regra "teste citado é teste rolado" passar a OBRIGAR o
mestre a pedir o d20 ao jogador em vez de inventar o resultado: esconder a
bandeja virou trocar um problema por um atrito.

Agora, quando o mestre pede o dado, a bandeja abre sozinha e diz a CD.
"""
import pytest

import server


PEDIDOS = [
    "Role um d20 de Percepção (CD 13) e me diga o resultado.",
    "Faça um teste de Furtividade: role o dado, CD 15.",
    "Role os dados, Sonael — preciso saber se você ouviu o barulho.",
    "Qual foi o resultado? Use a bandeja de dados.",
    "d20 para acertar a fechadura — role aí.",
]

NAO_PEDIDOS = [
    "A porta range e cede. Vocês entram na sala escura.",
    "Helena avança com o escudo erguido e apara o golpe.",
    "O mercador sorri: — Cinquenta peças, nem uma a menos.",
]


@pytest.mark.parametrize("texto", PEDIDOS)
def test_o_pedido_do_dado_e_reconhecido(texto):
    assert server._PEDIU_O_DADO_RE.search(texto)


@pytest.mark.parametrize("texto", NAO_PEDIDOS)
def test_narracao_comum_nao_abre_a_bandeja(texto):
    assert not server._PEDIU_O_DADO_RE.search(texto)


def test_a_cd_sai_do_texto():
    import re
    achado = re.search(r"\bCD\s*(\d{1,2})\b", PEDIDOS[0], re.IGNORECASE)
    assert achado and int(achado.group(1)) == 13


def test_o_chat_manda_o_pedido_para_a_tela():
    import inspect
    fonte = inspect.getsource(server.chat)
    assert "_PEDIU_O_DADO_RE.search(response_text" in fonte
    assert "'pede_dado'" in fonte or '"pede_dado"' in fonte
    # Depois da cena: a bandeja abre com o pedido já lido pelo jogador.
    assert fonte.index("'type': 'text'") < fonte.index("pede_dado")


def test_a_tela_sabe_abrir_a_bandeja():
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / "static" / "js" / "game.js").read_text(encoding="utf-8")
    assert "ev.type === 'pede_dado'" in js
    assert "function abrirBandejaDeDados" in js
    # Não pode passar pelo toggle: ele desiste enquanto o turno está chegando.
    trecho = js.split("function abrirBandejaDeDados")[1].split("function limparPedidoDeDado")[0]
    assert "if (waiting) return" not in trecho
    # E a campanha sem regras não ganha bandeja nenhuma.
    assert "semDnd" in trecho


def test_rolar_limpa_o_pedido():
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / "static" / "js" / "game.js").read_text(encoding="utf-8")
    trecho = js.split("function rollPlayerDie")[1][:1200]
    assert "limparPedidoDeDado()" in trecho
