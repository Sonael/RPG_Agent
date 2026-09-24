"""
eco.py
O que é do motor não vai para a tela do jogador.

POR QUE EXISTE
──────────────
Duas coisas internas estavam aparecendo no chat, e a campanha jogada tem as
duas gravadas:

1. O RESULTADO DAS FERRAMENTAS DE CONTEXTO. get_scene_context() devolve o
   retrato do mundo ("[Cap.1 | Colinas Cinzentas] / Cena: … / Status D&D: …")
   para o mestre se situar. Como todo resultado de ferramenta é transmitido
   para o chat, o jogador recebia o retrato inteiro a cada turno. Isso se
   resolve no servidor, que simplesmente não manda esses dois resultados.

2. O ECO. O próprio mestre copiava para dentro da narração o bloco que ele
   tinha acabado de ler:

       *(O combate prossegue na tela tática. Faça sua jogada, Selene!)*

       COMBATE ATIVO — ESTADO ATUAL (NÃO RE-EXECUTE TURNOS ANTERIORES):
          Rodada: 1
          Ordem: Selene → Helena → Mineiro Corrompido 2 → …
          INSTRUÇÃO CRÍTICA: o histórico acima já contém ações processadas.

   Isso não dá para resolver só pedindo — a instrução já pede. Resolve-se
   aqui, cortando o eco antes de o texto chegar à tela e ao histórico.

COMO O CORTE FUNCIONA
─────────────────────
Por linha, não por bloco inteiro: uma MARCA abre o corte (são cabeçalhos que
não existem em narração — "COMBATE ATIVO", "[Cap.3 | …]", "Status D&D:"), e o
corte segue enquanto as linhas forem continuação (vazias, itens de lista,
linhas indentadas, campos "Cena:", "Ordem:", "Traços:"). A primeira linha de
prosa de verdade fecha o corte e volta a valer.

Assim, eco no fim da resposta some inteiro, e eco no MEIO não leva a narração
que vem depois junto.
"""

from __future__ import annotations

import re

# Cabeçalhos que só existem no que o motor escreve para o mestre.
MARCAS = (
    re.compile(r"^\s*\[Cap\.?\s*\d+\s*\|", re.IGNORECASE),
    re.compile(r"^\s*COMBATE ATIVO\b", re.IGNORECASE),
    re.compile(r"^\s*INSTRU[ÇC][ÃA]O CR[ÍI]TICA\b", re.IGNORECASE),
    re.compile(r"^\s*Personagens conhecidos\b", re.IGNORECASE),
    re.compile(r"^\s*Atitude dos NPCs\s*:", re.IGNORECASE),
    re.compile(r"^\s*Status D&D\s*:", re.IGNORECASE),
    re.compile(r"^\s*Mapa do local atual\s*:", re.IGNORECASE),
    re.compile(r"^\s*===\s*ESTADO DO MUNDO\s*===", re.IGNORECASE),
    re.compile(r"^\s*Campo de batalha\s*:", re.IGNORECASE),
    re.compile(r"^\s*Lados\s*—", re.IGNORECASE),
)

# Linhas que fazem parte do bloco depois de ele ter começado.
_CAMPOS = (
    "cena", "tempo", "resumo", "grupo", "locais", "local", "mapa",
    "missões ativas", "missoes ativas", "eventos recentes", "ordem",
    "rodada", "turno atual", "traços", "tracos", "detalhes", "fica em",
    "dentro daqui", "grupo sabe", "lados", "dificuldade", "orçamento",
    "orcamento", "xp do encontro",
)
_CONTINUA = re.compile(
    r"^\s*(?:[•\-\*→]|\d+\.\s|\[|" + "|".join(re.escape(c) for c in _CAMPOS) + r")\s*[:\s]",
    re.IGNORECASE,
)


# A linha de ficha que vem depois de "Status D&D:" e dentro de "COMBATE ATIVO":
# "Helena Nv.2 guerreiro PV[▓▓▓▓]22/22 Mana 0/0 CA 19". Não começa com marca
# nenhuma, mas ninguém narra assim.
_STATUS = re.compile(r"(Nv\.\s*\d|PV\[|\bCA\s+\d+\b|\bMana\s+\d)")


def _continua(linha: str) -> bool:
    if not linha.strip():
        return True
    if linha.startswith(("  ", "\t")):        # tudo que o motor indenta
        return True
    return bool(_CONTINUA.match(linha) or _STATUS.search(linha))


def _marca(linha: str) -> str:
    for rx in MARCAS:
        if rx.match(linha):
            return linha.strip()[:60]
    return ""


def tirar_ecos(texto: str) -> tuple[str, list[str]]:
    """
    Devolve (texto sem os blocos internos, lista do que foi cortado).

    Sem marca nenhuma, devolve o texto como veio — o caminho normal não paga
    nada além de uma varredura de linhas.
    """
    if not texto:
        return "", []

    linhas = texto.splitlines()
    saida: list[str] = []
    cortados: list[str] = []
    cortando = False

    for linha in linhas:
        marca = _marca(linha)
        if marca:
            cortando = True
            cortados.append(marca)
            continue
        if cortando:
            if _continua(linha):
                continue
            cortando = False
        saida.append(linha)

    limpo = "\n".join(saida).strip()
    # Cortar não pode apagar o turno: se a resposta era SÓ o bloco interno, o
    # texto original volta inteiro. Antes um eco na tela do que o jogador
    # ficar sem resposta nenhuma.
    if cortados and not limpo:
        return texto.strip(), []
    return limpo, cortados
