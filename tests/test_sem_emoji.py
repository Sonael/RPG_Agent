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

_BASE = ("\U0001F000-\U0001FAFF"   # pictogramas, rostos, objetos
         "☀-➿"           # símbolos diversos e dingbats
         "⬀-⯿"           # setas e estrelas coloridas
         "⌚⌛⏩-⏺"
         "ℹ⌨▶◀↩")
EMOJI = re.compile(f"[{_BASE}]️?")
PERMITIDOS = set("✕✎✓✗★☰❦▶◀↩")
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
