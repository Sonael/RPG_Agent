"""
app — código da aplicação RPG Agent.

Mantido DELIBERADAMENTE vazio de imports: os testes legados substituem
submódulos inteiros (um `memory` falso, um `database` que não fala com o
Supabase) registrando-os antes do primeiro uso. Se este arquivo importasse
os submódulos na carga do pacote, os verdadeiros venceriam a corrida e a
substituição não teria efeito.

Para trocar um submódulo por um dublê, use `registrar_dublê` — só mexer em
sys.modules não basta, porque `from app import memory` resolve pelo
ATRIBUTO do pacote quando ele já existe.
"""

import sys


def registrar_duble(nome: str, modulo) -> None:
    """
    Instala `modulo` no lugar de `app.<nome>`, para testes.

    Precisa fazer as duas coisas:
      • sys.modules["app.<nome>"] — para `import app.<nome>`;
      • setattr(app, nome)        — para `from app import <nome>`.
    """
    sys.modules[f"{__name__}.{nome}"] = modulo
    setattr(sys.modules[__name__], nome, modulo)


# Alias com acento, para combinar com o resto do código em português.
registrar_dublê = registrar_duble
