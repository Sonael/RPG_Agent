"""
lendas.py
Lendas e profecias: o livro do mundo, descoberto em pedaços.

Profecias, artefatos perdidos, ruínas, histórias de taverna. O mundo de
fantasia tem segredos antigos, e eles só apareciam quando o mestre lembrava
de contar. Agora cada lenda é registrada com a VERDADE que só o mestre sabe,
e o jogador vai juntando FRAGMENTOS — o que ouviu, leu, viu — até as peças se
encaixarem. Uma lenda que o grupo nunca ouviu não aparece na tela; quando a
história a resolve, fica o desfecho.
"""
from rpg import locais, memory

TIPOS = ("lenda", "profecia", "artefato perdido", "mistério", "ruína")
MAX_LENDAS = 40
MAX_FRAGMENTOS = 12


def _texto(s) -> str:
    return " ".join(str(s or "").split())


def _todas() -> dict:
    return memory.campaign.setdefault("lendas", {})


def registrar(titulo: str, tipo: str = "lenda", verdade: str = "", conhecida=False) -> str:
    titulo = _texto(titulo)
    if not titulo:
        return "Dê um título à lenda (ex: \"A Coroa Afogada\")."
    if locais.norm(titulo) in _todas():
        return f"A lenda '{titulo}' já existe. Use revelar_fragmento para o grupo saber mais."
    tipo_n = locais.norm(tipo or "lenda")
    tipo_ok = next((t for t in TIPOS if locais.norm(t) == tipo_n), None)
    if not tipo_ok:
        return f"Tipo desconhecido: use um de {', '.join(TIPOS)}."
    if len(_todas()) >= MAX_LENDAS:
        return f"Já são {MAX_LENDAS} lendas."
    _todas()[locais.norm(titulo)] = {"titulo": titulo, "tipo": tipo_ok, "verdade": _texto(verdade),
                                    "fragmentos": [], "conhecida": bool(conhecida), "desfecho": "",
                                    "cap": memory.campaign.get("chapter", 1)}
    memory.save_campaign()
    return (f"Lenda registrada: **{titulo}** ({tipo_ok}). "
            + ("O grupo já ouviu falar dela." if conhecida else
               "O grupo ainda não ouviu falar: aparece quando você revelar o primeiro fragmento."))


def revelar_fragmento(titulo: str, fragmento: str, fonte: str = "") -> str:
    l = _todas().get(locais.norm(titulo or ""))
    if not l:
        return f"Lenda '{titulo}' não encontrada. Use registrar_lenda primeiro."
    fragmento = _texto(fragmento)
    if not fragmento:
        return "Escreva o fragmento: o que o grupo ouviu, leu ou viu."
    if any(locais.norm(f.get("texto", "")) == locais.norm(fragmento) for f in l["fragmentos"]):
        return "Esse fragmento já foi revelado."
    l["fragmentos"].append({"texto": fragmento, "fonte": _texto(fonte), "cap": memory.campaign.get("chapter", 1)})
    del l["fragmentos"][:-MAX_FRAGMENTOS]
    l["conhecida"] = True
    memory.save_campaign()
    return f"Novo fragmento de **{l['titulo']}**" + (f" (de {fonte})" if fonte else "") + f": {fragmento}"


def resolver(titulo: str, desfecho: str) -> str:
    l = _todas().get(locais.norm(titulo or ""))
    if not l:
        return f"Lenda '{titulo}' não encontrada."
    if not _texto(desfecho):
        return "Conte o desfecho: o que a história revelou."
    l["desfecho"], l["conhecida"] = _texto(desfecho), True
    l["cap_desfecho"] = memory.campaign.get("chapter", 1)
    memory.save_campaign()
    return f"**{l['titulo']}** se resolveu: {l['desfecho']}"


def visiveis() -> list[dict]:
    """As lendas que o grupo conhece, as em aberto primeiro. A verdade nunca vem."""
    lista = [{"titulo": l["titulo"], "tipo": l.get("tipo", "lenda"),
              "fragmentos": [{"texto": f.get("texto", ""), "fonte": f.get("fonte", ""), "capitulo": f.get("cap")}
                             for f in l.get("fragmentos") or [] if isinstance(f, dict)],
              "desfecho": l.get("desfecho", ""), "capitulo_desfecho": l.get("cap_desfecho")}
             for l in _todas().values() if isinstance(l, dict) and l.get("conhecida")]
    return sorted(lista, key=lambda l: (bool(l["desfecho"]), locais.norm(l["titulo"])))


def resumo_para_o_mestre() -> str:
    linhas = []
    for l in _todas().values():
        if not isinstance(l, dict) or l.get("desfecho"):
            continue
        estado = f"{len(l.get('fragmentos') or [])} fragmento(s) revelado(s)" if l.get("conhecida") \
            else "o grupo NÃO ouviu falar"
        linhas.append(f"• {l['titulo']} ({l.get('tipo')}; {estado})"
                      + (f" — verdade: {l['verdade']}" if l.get("verdade") else ""))
    return "\n".join(linhas)


def importar(valor) -> dict:
    """
    As lendas de um JSON importado: lista ou dicionário, chave pelo título, tipo
    válido, fragmentos em texto ou em lista. Sem "conhecida", vale o que os
    fragmentos dizem: quem já tem fragmento o grupo conhece.
    """
    itens = valor.values() if isinstance(valor, dict) else (valor or [])
    saida = {}
    for l in itens:
        if not isinstance(l, dict) or not _texto(l.get("titulo")) or locais.norm(l["titulo"]) in saida:
            continue
        tipo = next((t for t in TIPOS if locais.norm(t) == locais.norm(l.get("tipo") or "lenda")), "lenda")
        frags = []
        for f in l.get("fragmentos") or []:
            if isinstance(f, str) and _texto(f):
                frags.append({"texto": _texto(f), "fonte": "", "cap": 1})
            elif isinstance(f, dict) and _texto(f.get("texto")):
                frags.append({"texto": _texto(f["texto"]), "fonte": _texto(f.get("fonte")), "cap": f.get("cap") or 1})
        conhecida = l.get("conhecida")
        saida[locais.norm(l["titulo"])] = {
            "titulo": _texto(l["titulo"]), "tipo": tipo, "verdade": _texto(l.get("verdade")),
            "fragmentos": frags[-MAX_FRAGMENTOS:],
            "conhecida": bool(frags) if conhecida is None else bool(conhecida) or bool(frags),
            "desfecho": _texto(l.get("desfecho")), "cap": l.get("cap") or 1,
        }
        if len(saida) >= MAX_LENDAS:
            break
    return saida
