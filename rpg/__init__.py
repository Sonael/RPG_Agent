"""
rpg — código da aplicação RPG Agent.

O pacote se chama `rpg` (e não `app`) de propósito: `server.py` precisa expor
uma variável chamada `app` — é a instância do Flask que o Render sobe com
`gunicorn server:app` — e ter as duas coisas com o mesmo nome no mesmo arquivo
é armadilha de leitura garantida.

Mantido DELIBERADAMENTE vazio de imports: os testes legados substituem
submódulos inteiros (um `memory` falso, um `database` que não fala com o
Supabase) registrando-os antes do primeiro uso. Se este arquivo importasse
os submódulos na carga do pacote, os verdadeiros venceriam a corrida e a
substituição não teria efeito.

Para trocar um submódulo por um dublê, use `registrar_duble` — só mexer em
sys.modules não basta, porque `from rpg import memory` resolve pelo
ATRIBUTO do pacote quando ele já existe.
"""

import sys


def registrar_duble(nome: str, modulo) -> None:
    """
    Instala `modulo` no lugar de `rpg.<nome>`, para testes.

    Precisa fazer as duas coisas:
      • sys.modules["rpg.<nome>"] — para `import rpg.<nome>`;
      • setattr(rpg, nome)        — para `from rpg import <nome>`.
    """
    sys.modules[f"{__name__}.{nome}"] = modulo
    setattr(sys.modules[__name__], nome, modulo)


# Alias com acento, para combinar com o resto do código em português.
registrar_dublê = registrar_duble
