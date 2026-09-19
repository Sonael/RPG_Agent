"""
encontros.py
Os encontros marcados do romance: com quem, quando, onde e o quê.

"Jantar na sexta às 20h" era uma frase da narração que ninguém lembrava: o
mestre não sabia que a hora tinha chegado, e o jogador não tinha onde ver o
que havia marcado. Agora o encontro usa o relógio do mundo (o mesmo do
descanso e de advance_time):

  • a barra lateral mostra o próximo, com quanto falta, e avisa quando está
    perto ou passou da hora;
  • o bloco de cena do mestre diz o mesmo, e cobra o encontro atrasado;
  • resolver_encontro fecha: aconteceu (vira momento), faltou (o
    protagonista não foi: -15 de confiança, -5 de afeto e um momento) ou
    cancelado (sem efeito — cancelar avisando é outra coisa que faltar).
"""
from rpg import locais, memory, relacoes

EM_BREVE = 6            # horas: a partir daqui a barra avisa
FALTOU_CONFIANCA = -15
FALTOU_AFETO = -5
MAX_ENCONTROS = 40
ESTADOS = ("aconteceu", "faltou", "cancelado")


def _lista() -> list:
    return memory.campaign.setdefault("encontros", [])


def _agora() -> int:
    from rpg import tools_dnd as td
    return td._agora_em_horas()


def _instante(dia: int, hora: int) -> int:
    return int(dia) * 24 + int(hora)


def _quando_legivel(dia: int, hora: int) -> str:
    return f"Dia {int(dia)}, {int(hora):02d}h"


def _falta(horas: int) -> str:
    if horas < 0:
        h = -horas
        return f"passou há {h}h" if h < 24 else f"passou há {h // 24}d {h % 24}h"
    if horas == 0:
        return "agora"
    return f"em {horas}h" if horas < 24 else f"em {horas // 24}d {horas % 24}h"


def _personagem(nome: str):
    chars = memory.campaign.get("characters") or {}
    achado = chars.get(memory.char_key(nome or ""))
    if achado:
        return achado
    alvo = locais.norm(nome)
    return next((c for c in chars.values()
                 if isinstance(c, dict) and locais.norm(c.get("name", "")) == alvo), None)


def marcar(com: str, dia: int, hora: int, onde: str = "", o_que: str = "") -> str:
    ch = _personagem(com)
    protagonista = locais.norm(memory.campaign.get("protagonist", "") or "")
    if not ch or locais.norm(ch.get("name", "")) == protagonista:
        return f"Personagem '{com}' não encontrado. Use save_character primeiro."
    try:
        dia, hora = int(dia), int(hora)
    except (TypeError, ValueError):
        return "Informe dia e hora como números (ex: dia=4, hora=20). get_world_time() diz o dia de hoje."
    if not 0 <= hora <= 23:
        return "A hora vai de 0 a 23."
    if _instante(dia, hora) < _agora():
        return (f"{_quando_legivel(dia, hora)} já passou (agora é "
                f"{_quando_legivel(_agora() // 24, _agora() % 24)}).")
    if len([e for e in _lista() if e.get("estado") == "marcado"]) >= MAX_ENCONTROS:
        return "Encontros demais marcados. Resolva algum antes."
    e = {"id": max([x.get("id", 0) for x in _lista()] + [0]) + 1, "com": ch["name"],
         "dia": dia, "hora": hora, "onde": " ".join(str(onde or "").split()),
         "o_que": " ".join(str(o_que or "").split()) or "encontro",
         "estado": "marcado", "cap": memory.campaign.get("chapter", 1)}
    _lista().append(e)
    memory.save_campaign()
    onde_txt = f", {e['onde']}" if e["onde"] else ""
    return (f"Encontro marcado com {ch['name']}: {e['o_que']} — {_quando_legivel(dia, hora)}{onde_txt} "
            f"({_falta(_instante(dia, hora) - _agora())}). A barra do jogador mostra.")


def resolver(com: str, estado: str, motivo: str = "") -> str:
    estado = locais.norm(estado or "")
    if estado not in ESTADOS:
        return f"Estado desconhecido: use um de {', '.join(ESTADOS)}."
    alvo = locais.norm(com or "")
    marcados = sorted((e for e in _lista() if e.get("estado") == "marcado"
                       and locais.norm(e.get("com", "")) == alvo),
                      key=lambda e: _instante(e["dia"], e["hora"]))
    if not marcados:
        return f"Nenhum encontro marcado com '{com}'."
    e = marcados[0]
    e["estado"] = estado
    e["motivo"] = " ".join(str(motivo or "").split())
    e["cap_resolvido"] = memory.campaign.get("chapter", 1)
    ch = _personagem(e["com"])
    linhas = [f"Encontro com {e['com']} ({e['o_que']}, {_quando_legivel(e['dia'], e['hora'])}): **{estado}**."]
    if ch and estado == "aconteceu":
        relacoes._anotar_momento(ch, f"Encontro: {e['o_que']}", e["motivo"] or e["onde"], tipo="encontro")
    elif ch and estado == "faltou":
        relacoes._anotar_momento(ch, f"Você faltou: {e['o_que']}", e["motivo"], tipo="encontro")
        linhas.append(relacoes.ajustar(e["com"], afeto=FALTOU_AFETO, confianca=FALTOU_CONFIANCA,
                                       motivo=f"Você faltou ao encontro: {e['o_que']}"))
    memory.save_campaign()
    return "\n".join(linhas)


def _visivel(e: dict, agora: int) -> dict:
    horas = _instante(e["dia"], e["hora"]) - agora
    return {"id": e.get("id"), "com": e.get("com", ""), "o_que": e.get("o_que", ""), "onde": e.get("onde", ""),
            "quando": _quando_legivel(e["dia"], e["hora"]), "falta": _falta(horas),
            "horas": horas, "em_breve": 0 <= horas <= EM_BREVE, "atrasado": horas < 0,
            "estado": e.get("estado", "marcado")}


def marcados() -> list[dict]:
    """Os que ainda vão acontecer (ou passaram da hora sem resolução), do mais cedo ao mais tarde."""
    agora = _agora()
    lista = [_visivel(e, agora) for e in _lista() if isinstance(e, dict) and e.get("estado") == "marcado"]
    return sorted(lista, key=lambda e: e["horas"])


def da_pessoa(nome: str) -> list[dict]:
    alvo = locais.norm(nome)
    return [e for e in marcados() if locais.norm(e["com"]) == alvo]


def proximo() -> dict | None:
    lista = marcados()
    return lista[0] if lista else None


def resumo_para_o_mestre() -> str:
    lista = marcados()
    if not lista:
        return ""
    linhas = []
    for e in lista:
        onde = f", {e['onde']}" if e["onde"] else ""
        cobra = (" — PASSOU DA HORA: narre o encontro ou a falta e feche com resolver_encontro()"
                 if e["atrasado"] else "")
        linhas.append(f"• {e['com']}: {e['o_que']} — {e['quando']}{onde} ({e['falta']}){cobra}")
    return "\n".join(linhas)
