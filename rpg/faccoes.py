"""
faccoes.py
Renome, facções e títulos: o mundo reage ao que os heróis fazem.

Numa aventura de fantasia o jogo media muito bem o herói (a ficha, com D&D) e
quase nada do mundo em volta dele. A reputação existia só pessoa a pessoa
(a atitude). Agora:

  • RENOME (0 a 100): o quanto o grupo é conhecido — desconhecidos, falados
    na região, conhecidos no reino, famosos, lendários. A fama chega antes
    dos heróis.
  • FACÇÕES: reinos, guildas, ordens, cidades, cultos — cada uma com uma
    reputação de -100 a +100 (inimigos declarados, hostis, desconfiados,
    neutros, respeitados, aliados, heróis da causa) e o porquê de cada
    mudança. A facção que o grupo ainda não conhece fica só com o mestre.
  • TÍTULOS: "Matadora do Wyrm de Cinza". O mundo passa a chamar alguém pelo
    que fez, e o título diz o que muda (abre portas, atrai inimigos).

Vale para a fantasia e o dark fantasy, com e sem as regras de D&D: é o mundo
que se mede, não o combate.
"""
from rpg import locais, memory

GENEROS = ("fantasia", "dark_fantasy")
RENOME = (
    (0, 9, "desconhecidos"),
    (10, 29, "falados na região"),
    (30, 54, "conhecidos no reino"),
    (55, 79, "famosos"),
    (80, 100, "lendários"),
)
REPUTACAO = (
    (-100, -60, "inimigos declarados"),
    (-59, -30, "hostis"),
    (-29, -10, "desconfiados"),
    (-9, 9, "neutros"),
    (10, 29, "respeitados"),
    (30, 59, "aliados"),
    (60, 100, "heróis da causa"),
)
MAX_HISTORICO = 8
MAX_TITULOS = 30


def _faixa(tabela, valor: int) -> str:
    for baixo, alto, rotulo in tabela:
        if baixo <= valor <= alto:
            return rotulo
    return tabela[0][2]


def _num(valor, baixo=-100, alto=100) -> int:
    try:
        return max(baixo, min(alto, int(valor or 0)))
    except (TypeError, ValueError):
        return 0


def _texto(s) -> str:
    return " ".join(str(s or "").split())


def _todas() -> dict:
    return memory.campaign.setdefault("faccoes", {})


def _historico(lista: list, delta: int, motivo: str) -> None:
    lista.append({"delta": int(delta), "motivo": _texto(motivo), "cap": memory.campaign.get("chapter", 1)})
    del lista[:-MAX_HISTORICO]


# ---------------------------------------------------------------------------
# Renome
# ---------------------------------------------------------------------------

def renome() -> dict:
    r = memory.campaign.get("renome") or {}
    valor = _num(r.get("valor"), 0, 100)
    return {"valor": valor, "faixa": _faixa(RENOME, valor),
            "historico": [{"delta": h.get("delta", 0), "motivo": h.get("motivo", ""), "capitulo": h.get("cap")}
                          for h in reversed(r.get("historico") or []) if isinstance(h, dict)][:5]}


def ajustar_renome(delta, motivo: str = "") -> str:
    try:
        d = int(delta)
    except (TypeError, ValueError):
        return "Informe delta como número inteiro (ex: 10, -5)."
    if not d:
        return "Informe um delta diferente de zero."
    r = memory.campaign.setdefault("renome", {"valor": 0, "historico": []})
    antes = _num(r.get("valor"), 0, 100)
    r["valor"] = _num(antes + d, 0, 100)
    _historico(r.setdefault("historico", []), d, motivo)
    memory.save_campaign()
    linha = f"Renome do grupo: {antes} → **{r['valor']}** ({_faixa(RENOME, r['valor'])})"
    if _faixa(RENOME, antes) != _faixa(RENOME, r["valor"]):
        linha += f"\n   Agora são {_faixa(RENOME, r['valor'])}: estranhos reagem a isso."
    return linha + (f" — {motivo}" if motivo else "")


# ---------------------------------------------------------------------------
# Facções
# ---------------------------------------------------------------------------

def _faccao(nome: str):
    return _todas().get(locais.norm(nome or ""))


def ajustar_reputacao(faccao: str, delta=0, motivo: str = "", tipo: str = "", descricao: str = "",
                      conhecida=None) -> str:
    nome = _texto(faccao)
    if not nome:
        return "Informe o nome da facção."
    try:
        d = int(delta or 0)
    except (TypeError, ValueError):
        return "Informe delta como número inteiro (ex: 15, -30)."
    f = _faccao(nome)
    if not f:
        f = _todas()[locais.norm(nome)] = {"nome": nome, "tipo": _texto(tipo) or "facção",
                                           "descricao": _texto(descricao), "reputacao": 0,
                                           "conhecida": True, "historico": [],
                                           "cap": memory.campaign.get("chapter", 1)}
    antes = _num(f.get("reputacao"))
    if tipo:
        f["tipo"] = _texto(tipo)
    if descricao:
        f["descricao"] = _texto(descricao)
    if conhecida is not None:
        f["conhecida"] = bool(conhecida)
    if d:
        f["reputacao"] = _num(antes + d)
        _historico(f.setdefault("historico", []), d, motivo)
    memory.save_campaign()
    depois = _num(f["reputacao"])
    linha = f"{f['nome']} ({f['tipo']}): {antes:+d} → **{depois:+d}** ({_faixa(REPUTACAO, depois)})"
    if motivo:
        linha += f" — {motivo}"
    if _faixa(REPUTACAO, antes) != _faixa(REPUTACAO, depois):
        linha += f"\n   Mudou de faixa: {_faixa(REPUTACAO, antes)} → **{_faixa(REPUTACAO, depois)}**."
    if not f["conhecida"]:
        linha += "\n   O grupo ainda NÃO conhece esta facção: o jogador não vê."
    return linha


def faccoes_visiveis() -> list[dict]:
    lista = []
    for f in _todas().values():
        if not isinstance(f, dict) or not f.get("conhecida", True):
            continue
        valor = _num(f.get("reputacao"))
        lista.append({"nome": f.get("nome", ""), "tipo": f.get("tipo", "facção"), "descricao": f.get("descricao", ""),
                      "reputacao": valor, "faixa": _faixa(REPUTACAO, valor),
                      "historico": [{"delta": h.get("delta", 0), "motivo": h.get("motivo", ""),
                                     "capitulo": h.get("cap")}
                                    for h in reversed(f.get("historico") or []) if isinstance(h, dict)][:4]})
    # As que mais pesam (para o bem ou para o mal) primeiro.
    return sorted(lista, key=lambda f: (-abs(f["reputacao"]), locais.norm(f["nome"])))


# ---------------------------------------------------------------------------
# Títulos
# ---------------------------------------------------------------------------

def conceder_titulo(quem: str, titulo: str, motivo: str = "", efeito: str = "") -> str:
    titulo, quem = _texto(titulo), _texto(quem) or "o grupo"
    if not titulo:
        return "Dê o título (ex: \"Matadora do Wyrm de Cinza\")."
    lista = memory.campaign.setdefault("titulos", [])
    if any(locais.norm(t.get("titulo", "")) == locais.norm(titulo) for t in lista if isinstance(t, dict)):
        return f"O título '{titulo}' já foi dado."
    if len(lista) >= MAX_TITULOS:
        return f"Já são {MAX_TITULOS} títulos."
    if locais.norm(quem) not in ("o grupo", "grupo", "todos"):
        chars = memory.campaign.get("characters") or {}
        ch = chars.get(memory.char_key(quem)) or next(
            (c for c in chars.values() if isinstance(c, dict) and locais.norm(c.get("name", "")) == locais.norm(quem)),
            None)
        if not ch:
            return f"Personagem '{quem}' não encontrado. Use quem=\"o grupo\" para um título coletivo."
        quem = ch["name"]
    else:
        quem = "o grupo"
    lista.append({"titulo": titulo, "quem": quem, "motivo": _texto(motivo), "efeito": _texto(efeito),
                  "cap": memory.campaign.get("chapter", 1)})
    memory.save_campaign()
    return f"{quem} agora é chamado de **{titulo}**" + (f" — {motivo}" if motivo else "") + "."


def titulos(quem: str = "") -> list[dict]:
    lista = [{"titulo": t.get("titulo", ""), "quem": t.get("quem", ""), "motivo": t.get("motivo", ""),
              "efeito": t.get("efeito", ""), "capitulo": t.get("cap")}
             for t in (memory.campaign.get("titulos") or []) if isinstance(t, dict)]
    if quem:
        lista = [t for t in lista if locais.norm(t["quem"]) == locais.norm(quem)]
    return list(reversed(lista))


# ---------------------------------------------------------------------------
# Para o mestre e para a importação
# ---------------------------------------------------------------------------

def resumo_para_o_mestre() -> str:
    r = renome()
    linhas = [f"• Renome do grupo: {r['valor']} ({r['faixa']})"]
    for f in sorted(_todas().values(), key=lambda f: -abs(_num(f.get("reputacao")))):
        if not isinstance(f, dict):
            continue
        v = _num(f.get("reputacao"))
        oculto = "" if f.get("conhecida", True) else " — o grupo NÃO conhece"
        linhas.append(f"• {f.get('nome')} ({f.get('tipo')}): {v:+d} ({_faixa(REPUTACAO, v)}){oculto}")
    for t in titulos()[:6]:
        linhas.append(f"• Título: {t['quem']} é \"{t['titulo']}\"" + (f" ({t['efeito']})" if t["efeito"] else ""))
    return "\n".join(linhas)


def importar(dados: dict) -> dict:
    """renome, facções e títulos de um JSON importado, no formato do jogo."""
    r = dados.get("renome") if isinstance(dados.get("renome"), dict) else {"valor": dados.get("renome")}
    fac = {}
    itens = dados.get("faccoes")
    for f in (itens.values() if isinstance(itens, dict) else (itens or [])):
        if isinstance(f, dict) and _texto(f.get("nome")):
            fac[locais.norm(f["nome"])] = {"nome": _texto(f["nome"]), "tipo": _texto(f.get("tipo")) or "facção",
                                          "descricao": _texto(f.get("descricao")),
                                          "reputacao": _num(f.get("reputacao")),
                                          "conhecida": f.get("conhecida", True) is not False,
                                          "historico": [h for h in (f.get("historico") or []) if isinstance(h, dict)],
                                          "cap": f.get("cap") or 1}
    tit = [{"titulo": _texto(t.get("titulo")), "quem": _texto(t.get("quem")) or "o grupo",
            "motivo": _texto(t.get("motivo")), "efeito": _texto(t.get("efeito")), "cap": t.get("cap") or 1}
           for t in (dados.get("titulos") or []) if isinstance(t, dict) and _texto(t.get("titulo"))]
    return {"renome": {"valor": _num(r.get("valor"), 0, 100),
                       "historico": [h for h in (r.get("historico") or []) if isinstance(h, dict)]},
            "faccoes": fac, "titulos": tit[:MAX_TITULOS]}
