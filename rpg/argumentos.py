"""
argumentos.py
O tipo que a LLM manda nem sempre é o tipo da assinatura.

POR QUE EXISTE
──────────────
As ferramentas declaram tipos (difficulty: int, hours: int, done: bool), mas
o que chega numa chamada de função do modelo é JSON — e o modelo às vezes
manda o número como texto: difficulty="12", hours="2", amount="-5". O ADK
não converte: entrega a string e a ferramenta quebra no meio da conta.

Numa partida, isto derrubou um teste de perícia:

    make_skill_check(skill=sobrevivencia, difficulty=12, char_name=Sonael)
    TypeError: '>=' not supported between instances of 'int' and 'str'

O turno não caía (erros_de_ferramenta segura), mas a rolagem se perdia e o
mestre tinha de improvisar sem o dado.

O conserto é num lugar só: cada ferramenta entregue ao agente passa por um
invólucro que converte os argumentos para o tipo declarado antes de chamar a
função. Assim vale para as 117, e não para a que quebrou hoje.

O QUE É CONVERTIDO
  • int e float: "12", " 12 ", "+12", "12.0" e também "CD 12" ou
    "12 (média)" — um número só na frase. Float com casa quebrada não vira
    int em silêncio: 12.7 continua como está e a ferramenta recusa.
  • bool: "true"/"false", "sim"/"não", "1"/"0", 1/0.
  • str: número vira texto (char_name=123 → "123").
O que NÃO dá para converter não chega à ferramenta: o invólucro recusa com
uma frase que diz o argumento, o que veio e o que era esperado. Antes isso
virava TypeError no meio da conta — e, com sorte, uma falha crítica por
acidente, porque o d20 tinha saído 1 e a comparação nem aconteceu.
"""

from __future__ import annotations

import functools
import inspect
import re

# Um número só na frase inteira: "CD 12", "12 (média)", "+12".
# "1d20" não casa (tem dois grupos de dígitos), e é isso que se quer.
_SO_UM_NUMERO = re.compile(r"^[^\d-]*(-?\d+(?:[.,]\d+)?)[^\d]*$")

_VERDADE = {"true", "1", "sim", "s", "yes", "y", "verdadeiro", "on"}
_FALSIDADE = {"false", "0", "nao", "não", "n", "no", "falso", "off"}


def _numero_do_texto(valor):
    achado = _SO_UM_NUMERO.match(str(valor).strip())
    return achado.group(1).replace(",", ".") if achado else None


def para_int(valor):
    if isinstance(valor, bool) or isinstance(valor, int):
        return int(valor)
    if isinstance(valor, float):
        return int(valor) if valor.is_integer() else valor
    texto = _numero_do_texto(valor)
    if texto is None:
        return valor
    try:
        numero = float(texto)
    except ValueError:
        return valor
    return int(numero) if numero.is_integer() else valor


def para_float(valor):
    if isinstance(valor, bool):
        return float(valor)
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = _numero_do_texto(valor)
    if texto is None:
        return valor
    try:
        return float(texto)
    except ValueError:
        return valor


def para_bool(valor):
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return bool(valor)
    texto = str(valor).strip().lower()
    if texto in _VERDADE:
        return True
    if texto in _FALSIDADE:
        return False
    return valor


def para_str(valor):
    if isinstance(valor, str) or valor is None:
        return valor
    if isinstance(valor, (int, float, bool)):
        return str(valor)
    return valor


_CONVERSORES = {int: para_int, float: para_float, bool: para_bool, str: para_str}


def converter(nome_do_tipo, valor):
    """Converte um valor para o tipo pedido; devolve o original se não der."""
    return _CONVERSORES.get(nome_do_tipo, lambda v: v)(valor)


def com_tipos(func):
    """
    A mesma função, com os argumentos convertidos para o tipo da assinatura.

    `functools.wraps` guarda a original em `__wrapped__`, e é dela que o ADK
    lê a assinatura para montar o schema: o que o modelo vê não muda.
    """
    try:
        assinatura = inspect.signature(func)
    except (TypeError, ValueError):
        return func

    tipos = {nome: p.annotation for nome, p in assinatura.parameters.items()
             if p.annotation in _CONVERSORES}
    if not tipos:
        return func

    @functools.wraps(func)
    def invólucro(*args, **kwargs):
        for nome, valor in list(kwargs.items()):
            tipo = tipos.get(nome)
            if tipo is None or valor is None:
                continue
            convertido = converter(tipo, valor)
            if not isinstance(convertido, tipo) or (tipo is int and isinstance(convertido, bool)):
                return (f"Erro: {func.__name__} recebeu {nome}={valor!r}, e {nome} "
                        f"precisa ser {_ARTIGO[tipo]}. Chame de novo com o valor certo.")
            kwargs[nome] = convertido
        return func(*args, **kwargs)

    return invólucro


_ARTIGO = {int: "um número inteiro", float: "um número",
           bool: "verdadeiro ou falso", str: "um texto"}
