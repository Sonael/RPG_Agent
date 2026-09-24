"""
entre.py
A relação de cada um com cada um, e não só com o grupo.

POR QUE EXISTE
──────────────
Havia um número só por pessoa: a `atitude`, que é o que ela sente pelo GRUPO.
Isso deixava a mesa sem resposta para o que acontece o tempo todo numa cena:

    "Helena: atitude +5 → -5 (neutro) — Helena odiou a sugestão e o controle
     velado de Selene"

Helena não ficou mais fria com o grupo: ela ficou mais fria com SELENE. Sem um
lugar para guardar isso, o motor descontava do único número que existia — e o
jogador via a companheira de lealdade 90 virar "neutro" por causa de uma briga
com outra pessoa.

Aqui cada personagem guarda o que sente por CADA outro, com o porquê de cada
mudança. O armazenamento é direcional: Helena pode desgostar de Selene sem que
Selene desgoste de Helena — é aí que mora o drama.

Mas uma relação é DAS DUAS pessoas, e quem escreve nela (o fechamento do turno
e a tela) muda os dois lados por padrão. Meia relação registrada é o que fazia
a ficha de uma parecer vazia enquanto a da outra tinha tudo. O lado avesso
continua possível: quem escreve a volta com outro número tem a sua vontade
respeitada, e o espelho não passa por cima.

QUEM ESCREVE
────────────
  • o mestre, pelo fechamento do turno (o campo `relação:` do bloco), sem
    ferramenta nova: a mesa de ferramentas já é grande demais e a lição
    medida foi que ferramenta a mais é ferramenta esquecida;
  • o jogador, pela ficha do personagem, que é o pedido de "dar para editar".

A `atitude` continua existindo e continua sendo o sentimento pelo grupo. Uma
não substitui a outra: quem é do grupo tem as duas, e agora as duas aparecem.
"""

from __future__ import annotations

from rpg import locais, memory

FAIXAS = (
    (-100, -60, "ódio"),
    (-59, -20, "atrito"),
    (-19, 19, "indiferença"),
    (20, 59, "amizade"),
    (60, 100, "inseparáveis"),
)
MAX_HISTORICO = 6
MAX_RELACOES = 40          # teto por pessoa, para o retrato não virar romance


def faixa(valor: int) -> str:
    for baixo, alto, rotulo in FAIXAS:
        if baixo <= valor <= alto:
            return rotulo
    return "indiferença"


def _num(valor) -> int:
    try:
        return max(-100, min(100, int(valor)))
    except (TypeError, ValueError):
        return 0


def _texto(s) -> str:
    return " ".join(str(s or "").split())


def _pessoa(nome: str):
    chars = memory.campaign.get("characters") or {}
    achado = chars.get(memory.char_key(nome or ""))
    if achado:
        return achado
    alvo = locais.norm(nome)
    return next((c for c in chars.values()
                 if isinstance(c, dict) and locais.norm(c.get("name", "")) == alvo), None)


def _nome_real(nome: str) -> str:
    ch = _pessoa(nome)
    return ch.get("name", nome) if ch else _texto(nome)


def _capitulo():
    return memory.campaign.get("chapter")


def _mapa(ch: dict) -> dict:
    entre = ch.get("entre")
    if not isinstance(entre, dict):
        entre = {}
        ch["entre"] = entre
    return entre


def ajustar(de: str, para: str, delta, motivo: str = "") -> str:
    """Muda o quanto `de` sente por `para`. Devolve a frase para o log."""
    return _escrever(de, para, delta=delta, motivo=motivo)


def definir(de: str, para: str, valor, motivo: str = "") -> str:
    """Põe o valor exato (é o que a tela de edição faz)."""
    return _escrever(de, para, valor=valor, motivo=motivo)


def _escrever(de: str, para: str, valor=None, delta=None, motivo: str = "") -> str:
    ch = _pessoa(de)
    if not ch:
        return f"Erro: personagem '{de}' não encontrado. Use save_character primeiro."
    outro = _pessoa(para)
    if not outro:
        return f"Erro: personagem '{para}' não encontrado. Use save_character primeiro."
    if locais.norm(ch.get("name", "")) == locais.norm(outro.get("name", "")):
        return "Erro: ninguém tem relação consigo mesmo."

    mapa = _mapa(ch)
    chave = memory.char_key(outro.get("name", para))
    atual = mapa.get(chave) if isinstance(mapa.get(chave), dict) else {}
    antes = _num(atual.get("valor"))

    if valor is not None:
        novo = _num(valor)
    else:
        try:
            novo = _num(antes + int(delta))
        except (TypeError, ValueError):
            return "Erro: a mudança precisa ser um número."

    if chave not in mapa and len(mapa) >= MAX_RELACOES:
        return f"Erro: {ch.get('name')} já tem {MAX_RELACOES} relações registradas."

    registro = atual if atual else {}
    registro["nome"] = outro.get("name", para)
    registro["valor"] = novo
    if _texto(motivo):
        registro["motivo"] = _texto(motivo)
    if novo != antes:
        hist = registro.setdefault("historico", [])
        hist.append({"delta": novo - antes, "motivo": _texto(motivo), "cap": _capitulo()})
        del hist[:-MAX_HISTORICO]
    mapa[chave] = registro
    memory.save_campaign()

    sinal = "+" if novo >= 0 else ""
    return (f"{ch.get('name')} → {outro.get('name')}: {antes} → {sinal}{novo} "
            f"({faixa(novo)}){f' — {_texto(motivo)}' if motivo else ''}")


def remover(de: str, para: str) -> str:
    ch = _pessoa(de)
    if not ch:
        return f"Erro: personagem '{de}' não encontrado."
    mapa = _mapa(ch)
    chave = memory.char_key(_nome_real(para))
    if chave not in mapa:
        return f"Erro: {ch.get('name')} não tem relação registrada com '{para}'."
    mapa.pop(chave)
    memory.save_campaign()
    return f"Relação de {ch.get('name')} com {_nome_real(para)} apagada."


def existe(de: str, para: str) -> bool:
    """Se `de` já tem alguma coisa registrada sobre `para` (mesmo que zero)."""
    ch = _pessoa(de)
    outro = _pessoa(para)
    if not ch or not outro:
        return False
    return memory.char_key(outro.get("name", para)) in (ch.get("entre") or {})


def valor_entre(de: str, para: str) -> int:
    """O quanto `de` sente por `para` agora (0 quando nunca houve nada)."""
    ch = _pessoa(de)
    outro = _pessoa(para)
    if not ch or not outro:
        return 0
    dados = (ch.get("entre") or {}).get(memory.char_key(outro.get("name", para)))
    return _num(dados.get("valor")) if isinstance(dados, dict) else 0


def de_quem(nome: str) -> list[dict]:
    """
    As relações de alguém, para a tela: da mais forte (em módulo) para a mais
    morna, porque é a que pesa na cena. Nomes de gente que já foi apagada da
    campanha não aparecem.
    """
    ch = _pessoa(nome)
    if not ch:
        return []
    saida = []
    for chave, dados in (ch.get("entre") or {}).items():
        if not isinstance(dados, dict):
            continue
        outro = _pessoa(dados.get("nome") or chave)
        if not outro:
            continue
        valor = _num(dados.get("valor"))
        saida.append({
            "nome": outro.get("name", dados.get("nome", "")),
            "valor": valor,
            "rotulo": faixa(valor),
            "motivo": dados.get("motivo", "") or "",
            "historico": [{"delta": int(h.get("delta", 0) or 0),
                           "motivo": h.get("motivo", ""), "capitulo": h.get("cap")}
                          for h in reversed(dados.get("historico") or [])
                          if isinstance(h, dict)][:MAX_HISTORICO],
        })
    return sorted(saida, key=lambda r: (-abs(r["valor"]), locais.norm(r["nome"])))


def para_o_mestre(nome: str, limite: int = 4) -> str:
    """
    Uma linha para o bloco de cena: "Helena sente por Selene: atrito (-25)".
    Só as que pesam — indiferença não muda a cena e só gasta prompt.
    """
    fortes = [r for r in de_quem(nome) if abs(r["valor"]) >= 20][:limite]
    if not fortes:
        return ""
    partes = [f"{r['nome']}: {r['rotulo']} ({r['valor']:+d})" for r in fortes]
    return f"{_nome_real(nome)} sente — " + " | ".join(partes)
