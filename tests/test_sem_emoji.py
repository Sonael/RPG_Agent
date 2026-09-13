"""O repositório não usa emoji.

Nem na interface, nem nas mensagens do motor, nem na instrução da IA, nem na
documentação. Emoji era usado como ícone e, pior, como SINAL: o servidor e a
interface decidiam sucesso/recusa pelo primeiro caractere da mensagem. Agora a
recusa é "Erro:"/"Aviso:" em texto, os ícones são SVG ou CSS, e este teste
impede que um emoji volte por descuido.

Ficam permitidos só sinais tipográficos que não viram emoji colorido quando
aparecem sem o seletor de variação (U+FE0F): fechar, lápis, check, estrela,
menu, ornamento e setas/triângulos simples.
"""
import pathlib
import re
import subprocess

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent

# As faixas vão em escape \u de propósito: escritas como caractere, este
# arquivo — que também é versionado — reprovaria a si mesmo. Foi o que
# aconteceu na primeira versão, que passou só porque ainda não estava no git
# quando a suíte rodou.
_BASE = ("\U0001F000-\U0001FAFF"   # pictogramas, rostos, objetos
         "\u2600-\u27bf"           # símbolos diversos e dingbats
         "\u2b00-\u2bff"           # setas e estrelas coloridas
         "\u231a\u231b\u23e9-\u23fa"   # relógio, ampulheta, botões de mídia
         "\u2139\u2328\u25b6\u25c0\u21a9")   # informação, teclado, triângulos, volta
EMOJI = re.compile(f"[{_BASE}]\ufe0f?")
# fechar, lápis, check, x, estrela, menu, ornamento, triângulos e seta de volta
PERMITIDOS = set("\u2715\u270e\u2713\u2717\u2605\u2630\u2766\u25b6\u25c0\u21a9")
BINARIOS = (".png", ".jpg", ".jpeg", ".ico", ".gif", ".webp", ".woff", ".woff2", ".pdf")


def _arquivos():
    try:
        saida = subprocess.run(["git", "ls-files"], cwd=RAIZ, capture_output=True,
                               text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("precisa do git para listar os arquivos versionados")
    return [RAIZ / rel for rel in saida.split() if not rel.endswith(BINARIOS)]


def test_nenhum_arquivo_versionado_tem_emoji():
    achados = []
    for caminho in _arquivos():
        try:
            texto = caminho.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for n, linha in enumerate(texto.splitlines(), 1):
            for m in EMOJI.finditer(linha):
                if m.group(0) in PERMITIDOS:
                    continue
                achados.append(f"{caminho.relative_to(RAIZ)}:{n}: {m.group(0)!r} em {linha.strip()[:80]!r}")
    assert not achados, "emoji no repositório:\n" + "\n".join(achados[:30])


def test_personagem_inexistente_e_recusa_com_prefixo():
    """As telas decidem ok/recusa pelo prefixo. Personagem que não existe era
    devolvido sem prefixo nenhum e passava por sucesso; agora é "Erro:"."""
    from rpg import tools_dnd
    saida = tools_dnd.apply_asi("Ninguém Existe", "forca", 1)
    assert saida.startswith("Erro:"), saida
