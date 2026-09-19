"""
mudancas.py
Mudanças no mundo: as consequências das escolhas, lugar por lugar.

"A ponte foi reconstruída", "a vila prosperou depois que o grupo expulsou os
bandidos", "o castelo caiu". Isso acontecia na narração e se perdia: o lugar
continuava descrito como antes, e o jogador não via o mundo mudar pelo que
fez. Agora cada mudança fica registrada no lugar, com a causa e o capítulo,
aparece na ficha do local e no mapa, e o mestre a recebe ao voltar lá.
"""
from rpg import locais, memory

MAX_POR_LUGAR = 12


def _texto(s) -> str:
    return " ".join(str(s or "").split())


def _lugar(nome: str):
    locs = memory.campaign.get("locations") or {}
    achado = locs.get(locais.norm(nome or "")) or locs.get((nome or "").lower().strip())
    if achado:
        return achado
    alvo = locais.norm(nome)
    return next((l for l in locs.values() if isinstance(l, dict) and locais.norm(l.get("name", "")) == alvo), None)


def registrar(local: str, mudanca: str, causa: str = "") -> str:
    mudanca = _texto(mudanca)
    if not mudanca:
        return "Descreva a mudança (ex: \"A ponte foi reconstruída\")."
    lugar = _lugar(local)
    if not lugar:
        return f"Local '{local}' não encontrado. Use save_location primeiro."
    lista = lugar.setdefault("mudancas", [])
    if any(locais.norm(m.get("texto", "")) == locais.norm(mudanca) for m in lista if isinstance(m, dict)):
        return f"Essa mudança em {lugar.get('name')} já está registrada."
    lista.append({"texto": mudanca, "causa": _texto(causa), "cap": memory.campaign.get("chapter", 1)})
    del lista[:-MAX_POR_LUGAR]
    memory.save_campaign()
    return f"{lugar.get('name')} mudou: **{mudanca}**" + (f" (porque {causa})" if causa else "") + "."


def do_lugar(nome: str) -> list[dict]:
    lugar = _lugar(nome)
    if not lugar:
        return []
    return [{"texto": m.get("texto", ""), "causa": m.get("causa", ""), "capitulo": m.get("cap")}
            for m in reversed(lugar.get("mudancas") or []) if isinstance(m, dict)]


def todas() -> list[dict]:
    """Todas as mudanças, do capítulo mais recente para trás, com o lugar."""
    saida = []
    for l in (memory.campaign.get("locations") or {}).values():
        if not isinstance(l, dict):
            continue
        for m in l.get("mudancas") or []:
            if isinstance(m, dict):
                saida.append({"lugar": l.get("name", ""), "texto": m.get("texto", ""),
                              "causa": m.get("causa", ""), "capitulo": m.get("cap")})
    return sorted(saida, key=lambda m: (-(m["capitulo"] or 0), locais.norm(m["lugar"])))


def resumo_para_o_mestre(local_atual: str = "") -> str:
    """As mudanças do lugar onde o grupo está: é quando elas importam."""
    lista = do_lugar(local_atual) if local_atual else []
    if not lista:
        return ""
    return "\n".join(f"• {local_atual} — {m['texto']}" + (f" (porque {m['causa']})" if m["causa"] else "")
                     for m in lista[:5])
