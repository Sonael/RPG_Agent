"""
lacos.py
Laços e lealdade: os companheiros como pessoas, não como fichas.

Na fantasia o companheiro era uma ficha (com D&D) ou um nome no grupo. Não
tinha vontade própria que o jogo lembrasse. Agora cada companheiro tem:

  • LEALDADE (-100 a +100): de "à beira de partir" a "até o fim", com o porquê
    de cada mudança. Lealdade baixa é aviso ao mestre: abandono ou traição
    são possíveis.
  • OBJETIVO: o que ele quer da vida ("limpar o nome do pai").
  • ARCO: a história pessoal dele em passos (redenção, vingança, uma dívida),
    que o mestre avança; o jogador vê em que ponto está e o que já passou.

A lealdade é o campo `lealdade`, separado da `atitude`: a atitude é o que
alguém sente pelo grupo; a lealdade é se ele fica quando custar caro.
"""
from rpg import locais, memory

LEALDADE = (
    (-100, -50, "à beira de partir"),
    (-49, -15, "em dúvida"),
    (-14, 14, "hesitante"),
    (15, 49, "leal"),
    (50, 79, "fiel"),
    (80, 100, "até o fim"),
)
MAX_HISTORICO = 8
MAX_PASSOS = 8
ESTADOS_DO_ARCO = ("em curso", "cumprido", "falhou", "abandonado")


def _texto(s) -> str:
    return " ".join(str(s or "").split())


def _faixa(valor: int) -> str:
    for baixo, alto, rotulo in LEALDADE:
        if baixo <= valor <= alto:
            return rotulo
    return "hesitante"


def _num(valor) -> int:
    try:
        return max(-100, min(100, int(valor or 0)))
    except (TypeError, ValueError):
        return 0


def _personagem(nome: str):
    chars = memory.campaign.get("characters") or {}
    achado = chars.get(memory.char_key(nome or ""))
    if achado:
        return achado
    alvo = locais.norm(nome)
    return next((c for c in chars.values()
                 if isinstance(c, dict) and locais.norm(c.get("name", "")) == alvo), None)


def _companheiro(nome: str):
    ch = _personagem(nome)
    if not ch:
        return None, f"Personagem '{nome}' não encontrado. Use save_character primeiro."
    protagonista = locais.norm(memory.campaign.get("protagonist", "") or "")
    if protagonista and locais.norm(ch.get("name", "")) == protagonista:
        return None, "Lealdade e arco são dos companheiros, não do protagonista."
    return ch, ""


def ajustar_lealdade(nome: str, delta, motivo: str = "") -> str:
    ch, erro = _companheiro(nome)
    if erro:
        return erro
    try:
        d = int(delta)
    except (TypeError, ValueError):
        return "Informe delta como número inteiro (ex: 15, -20)."
    if not d:
        return "Informe um delta diferente de zero."
    antes = _num(ch.get("lealdade"))
    ch["lealdade"] = _num(antes + d)
    hist = ch.setdefault("lealdade_historico", [])
    hist.append({"delta": d, "motivo": _texto(motivo), "cap": memory.campaign.get("chapter", 1)})
    del hist[:-MAX_HISTORICO]
    memory.save_campaign()
    depois = ch["lealdade"]
    linha = f"{ch['name']}: lealdade {antes:+d} → **{depois:+d}** ({_faixa(depois)})" + (f" — {motivo}" if motivo else "")
    if depois <= -50 < antes:
        linha += f"\n   {ch['name']} está à beira de partir: abandono ou traição são possíveis."
    return linha


def definir_arco(nome: str, objetivo: str = "", arco: str = "") -> str:
    ch, erro = _companheiro(nome)
    if erro:
        return erro
    if not _texto(objetivo) and not _texto(arco):
        return "Informe o objetivo, o arco, ou os dois."
    if _texto(objetivo):
        ch["objetivo"] = _texto(objetivo)
    if _texto(arco):
        ch["arco"] = {"titulo": _texto(arco), "passos": [], "estado": "em curso",
                      "cap": memory.campaign.get("chapter", 1)}
    memory.save_campaign()
    partes = []
    if _texto(objetivo):
        partes.append(f"quer {ch['objetivo']}")
    if _texto(arco):
        partes.append(f"arco: **{ch['arco']['titulo']}**")
    return f"{ch['name']}: " + "; ".join(partes) + "."


def avancar_arco(nome: str, passo: str, estado: str = "") -> str:
    ch, erro = _companheiro(nome)
    if erro:
        return erro
    arco = ch.get("arco")
    if not isinstance(arco, dict):
        return f"{ch['name']} ainda não tem arco: use definir_arco primeiro."
    estado = locais.norm(estado or "")
    if estado and estado not in [locais.norm(e) for e in ESTADOS_DO_ARCO]:
        return f"Estado desconhecido: use um de {', '.join(ESTADOS_DO_ARCO)}."
    if _texto(passo):
        arco.setdefault("passos", []).append({"texto": _texto(passo), "cap": memory.campaign.get("chapter", 1)})
        del arco["passos"][:-MAX_PASSOS]
    if estado:
        arco["estado"] = next(e for e in ESTADOS_DO_ARCO if locais.norm(e) == estado)
    memory.save_campaign()
    return (f"{ch['name']} — {arco['titulo']}: " + (f"**{_texto(passo)}**" if _texto(passo) else "")
            + (f" ({arco['estado']})" if estado else "") + ".")


def do_companheiro(ch: dict) -> dict | None:
    """O laço de alguém, para a tela; None se ninguém nunca mexeu nele."""
    if not any(k in ch for k in ("lealdade", "objetivo", "arco")):
        return None
    valor = _num(ch.get("lealdade"))
    arco = ch.get("arco") if isinstance(ch.get("arco"), dict) else None
    return {
        "lealdade": {"valor": valor, "faixa": _faixa(valor)},
        "objetivo": ch.get("objetivo", "") or "",
        "arco": {"titulo": arco.get("titulo", ""), "estado": arco.get("estado", "em curso"),
                 "passos": [{"texto": p.get("texto", ""), "capitulo": p.get("cap")}
                            for p in (arco.get("passos") or []) if isinstance(p, dict)]} if arco else None,
        "historico": [{"delta": h.get("delta", 0), "motivo": h.get("motivo", ""), "capitulo": h.get("cap")}
                      for h in reversed(ch.get("lealdade_historico") or []) if isinstance(h, dict)][:4],
    }


def companheiros() -> list[dict]:
    """Os do grupo com laço, da lealdade mais baixa (a que pede atenção) para a mais alta."""
    saida = []
    for ch in (memory.campaign.get("characters") or {}).values():
        if isinstance(ch, dict) and ch.get("name") and memory.is_party_member(ch):
            laco = do_companheiro(ch)
            if laco:
                saida.append({"nome": ch["name"], **laco})
    return sorted(saida, key=lambda c: (c["lealdade"]["valor"], locais.norm(c["nome"])))


def resumo_para_o_mestre() -> str:
    linhas = []
    for c in companheiros():
        arco = c["arco"]
        ultimo = arco["passos"][-1]["texto"] if arco and arco["passos"] else ""
        linhas.append(f"• {c['nome']}: lealdade {c['lealdade']['valor']:+d} ({c['lealdade']['faixa']})"
                      + (f"; quer {c['objetivo']}" if c["objetivo"] else "")
                      + (f"; arco \"{arco['titulo']}\" ({arco['estado']})" if arco else "")
                      + (f", último passo: {ultimo}" if ultimo else ""))
    return "\n".join(linhas)
