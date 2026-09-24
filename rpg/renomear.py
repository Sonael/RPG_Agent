"""
renomear.py
Trocar o nome de alguém em TUDO o que já foi escrito sobre essa pessoa.

POR QUE EXISTE
──────────────
"quando eu criei a campanha, pedi para a IA gerar, ela gerou personagens com
nomes que eu não gostei, eu troquei os nomes dos meus personagens e quando eu
iniciei a campanha os eventos no diário ainda estavam com os nomes antigos."

O wizard gera o mundo INTEIRO de uma vez: resumo, cena, locais, eventos e
personagens, todos falando uns dos outros pelo nome. Trocar o nome no campo do
personagem trocava só ali — a linha do tempo continuava contando a história de
alguém que não existe mais, e o mestre lia isso como verdade no primeiro turno.

O QUE ELE FAZ
Percorre TODO texto do que vai ser gravado e troca nome velho por nome novo,
como palavra inteira. Numa campanha que está NASCENDO isso é seguro: tudo ali
foi escrito há um minuto, pela IA, sobre esse elenco. Não serve para campanha
em andamento — lá um nome velho pode ser de outra pessoa, de um lugar ou de
uma lembrança que o jogador quer manter.
"""

from __future__ import annotations

import re

MAX_RENOMES = 20


def _regex(antigo: str):
    # Palavra inteira, respeitando acento: \b do Python já trata "é" como
    # letra, mas o nome pode vir com pontuação em volta ("— Selene?").
    return re.compile(rf"(?<!\w){re.escape(antigo)}(?!\w)", re.IGNORECASE)


def _limpar(renomes) -> list[tuple[str, str]]:
    """Pares (antigo, novo) que valem a pena: nome de gente, os dois lados
    preenchidos, e realmente diferentes."""
    saida = []
    vistos = set()
    for par in (renomes or [])[:MAX_RENOMES]:
        try:
            antigo, novo = (str(par[0] or "").strip(), str(par[1] or "").strip())
        except (TypeError, IndexError, KeyError):
            continue
        # Nome de uma letra viraria troca em qualquer palavra do texto.
        if len(antigo) < 2 or not novo or antigo.lower() == novo.lower():
            continue
        if antigo.lower() in vistos:
            continue
        vistos.add(antigo.lower())
        saida.append((antigo, novo))
    return saida


def em_texto(texto: str, renomes) -> str:
    for antigo, novo in _limpar(renomes):
        texto = _regex(antigo).sub(novo, texto)
    return texto


def aplicar(dados, renomes):
    """
    Devolve os mesmos dados com os nomes trocados em todo texto, em qualquer
    profundidade. As CHAVES dos dicionários ficam como estão: quem cuida delas
    é quem monta a campanha (a chave do personagem sai do nome novo).
    """
    pares = _limpar(renomes)
    if not pares:
        return dados
    return _andar(dados, pares)


def _andar(valor, pares):
    if isinstance(valor, str):
        for antigo, novo in pares:
            valor = _regex(antigo).sub(novo, valor)
        return valor
    if isinstance(valor, dict):
        return {k: _andar(v, pares) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_andar(v, pares) for v in valor]
    return valor
