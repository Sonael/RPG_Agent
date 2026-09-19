"""
tensoes.py
Ciúme e triângulos do romance: a tensão entre duas OUTRAS pessoas.

Até aqui toda relação era entre o protagonista e alguém. Mas o romance vive
também do que acontece entre os outros: a ex que não suporta o novo namoro,
a melhor amiga e o interesse romântico que se estranham, dois pretendentes
que se medem. Agora:

  • TENSÃO entre duas pessoas: um tipo (ciúme, rivalidade, mágoa,
    desconfiança), uma intensidade de 0 a 100 com faixas (latente, incômodo,
    tensão aberta, à beira da ruptura) e o porquê de cada mudança. Voltando a
    zero, a tensão fica resolvida.
  • Como os segredos, a tensão pode ser ESCONDIDA: o mestre registra o ciúme
    que o protagonista ainda não percebeu, e o jogador só a vê quando a
    história mostrar (ajustar_tensao(..., percebida=True)).
  • TRIÂNGULO: duas pessoas ao mesmo tempo em flerte ou mais com o
    protagonista. É detectado sozinho, a partir do estágio das relações —
    o jogador sabe com quem está flertando —, e o mestre é avisado de que o
    ciúme vai aparecer.
"""
from rpg import locais, memory, relacoes

TIPOS = ("ciume", "rivalidade", "magoa", "desconfianca")
ROTULO_DO_TIPO = {"ciume": "ciúme", "rivalidade": "rivalidade", "magoa": "mágoa", "desconfianca": "desconfiança"}
FAIXAS = (
    (0, 0, "resolvida"),
    (1, 19, "latente"),
    (20, 49, "incômodo"),
    (50, 79, "tensão aberta"),
    (80, 100, "à beira da ruptura"),
)
MAX_HISTORICO = 8
ROMANTICOS = ("flerte", "namoro", "compromisso")


def _todas() -> dict:
    return memory.campaign.setdefault("tensoes", {})


def _faixa(valor: int) -> str:
    for baixo, alto, rotulo in FAIXAS:
        if baixo <= valor <= alto:
            return rotulo
    return "latente"


def _personagem(nome: str):
    chars = memory.campaign.get("characters") or {}
    achado = chars.get(memory.char_key(nome or ""))
    if achado:
        return achado
    alvo = locais.norm(nome)
    return next((c for c in chars.values()
                 if isinstance(c, dict) and locais.norm(c.get("name", "")) == alvo), None)


def _chave(a: str, b: str) -> str:
    return "|".join(sorted((locais.norm(a), locais.norm(b))))


def ajustar(a: str, b: str, delta: int = 0, motivo: str = "", tipo: str = "", percebida=None) -> str:
    ca, cb = _personagem(a), _personagem(b)
    faltam = [n for n, c in ((a, ca), (b, cb)) if not c]
    if faltam:
        return f"Personagens não encontrados: {', '.join(faltam)}. Use save_character primeiro."
    protagonista = locais.norm(memory.campaign.get("protagonist", "") or "")
    if protagonista in (locais.norm(ca["name"]), locais.norm(cb["name"])):
        return "A tensão é entre duas OUTRAS pessoas; a do protagonista é ajustar_relacao."
    if locais.norm(ca["name"]) == locais.norm(cb["name"]):
        return "Informe duas pessoas diferentes."
    try:
        d = int(delta or 0)
    except (TypeError, ValueError):
        return "Informe delta como número inteiro (ex: 20, -15)."
    tipo_n = locais.norm(tipo or "")
    if tipo_n and tipo_n not in TIPOS:
        return f"Tipo desconhecido: '{tipo}'. Use um de: {', '.join(ROTULO_DO_TIPO.values())}."

    chave = _chave(ca["name"], cb["name"])
    t = _todas().get(chave)
    if not t:
        if not d:
            return "A tensão ainda não existe: informe delta para criá-la."
        t = _todas()[chave] = {"a": ca["name"], "b": cb["name"], "tipo": tipo_n or "ciume",
                               "intensidade": 0, "percebida": True, "historico": [],
                               "cap": memory.campaign.get("chapter", 1)}
    antes = int(t.get("intensidade", 0) or 0)
    if tipo_n:
        t["tipo"] = tipo_n
    if percebida is not None:
        t["percebida"] = bool(percebida)
    if d:
        t["intensidade"] = max(0, min(100, antes + d))
        t["historico"].append({"delta": d, "motivo": " ".join(str(motivo or "").split()),
                               "cap": memory.campaign.get("chapter", 1)})
        del t["historico"][:-MAX_HISTORICO]
    depois = t["intensidade"]
    memory.save_campaign()

    linha = (f"{t['a']} × {t['b']} ({ROTULO_DO_TIPO[t['tipo']]}): {antes} → **{depois}** "
             f"({_faixa(depois)})" + (f" — {motivo}" if motivo else ""))
    if antes and _faixa(antes) != _faixa(depois):
        linha += f"\n   Mudou de faixa: {_faixa(antes)} → **{_faixa(depois)}**."
    if not t["percebida"]:
        linha += "\n   O protagonista ainda NÃO percebeu: o jogador não vê. Mostre aos poucos."
    return linha


def _visivel(t: dict) -> dict:
    valor = int(t.get("intensidade", 0) or 0)
    return {"a": t["a"], "b": t["b"], "tipo": ROTULO_DO_TIPO.get(t.get("tipo"), "ciúme"),
            "intensidade": valor, "faixa": _faixa(valor),
            "historico": [{"delta": h.get("delta", 0), "motivo": h.get("motivo", ""), "capitulo": h.get("cap")}
                          for h in reversed(t.get("historico") or []) if isinstance(h, dict)][:4]}


def percebidas() -> list[dict]:
    """As tensões que o protagonista já percebeu e que não se resolveram, da mais forte à mais fraca."""
    lista = [_visivel(t) for t in _todas().values()
             if isinstance(t, dict) and t.get("percebida") and int(t.get("intensidade", 0) or 0) > 0]
    return sorted(lista, key=lambda t: (-t["intensidade"], locais.norm(t["a"])))


def da_pessoa(nome: str) -> list[dict]:
    """As tensões percebidas de alguém, com quem é a outra ponta."""
    n = locais.norm(nome)
    saida = []
    for t in percebidas():
        if n == locais.norm(t["a"]):
            saida.append({**t, "com": t["b"]})
        elif n == locais.norm(t["b"]):
            saida.append({**t, "com": t["a"]})
    return saida


def triangulos() -> list[dict]:
    """Pares de pessoas ao mesmo tempo em flerte ou mais com o protagonista."""
    protagonista = locais.norm(memory.campaign.get("protagonist", "") or "")
    chars = [c for c in (memory.campaign.get("characters") or {}).values()
             if isinstance(c, dict) and c.get("name") and locais.norm(c["name"]) != protagonista
             and (c.get("status") or "vivo").lower() != "morto"]
    romanticos = sorted((c for c in chars if relacoes.estagio_de(c) in ROMANTICOS),
                        key=lambda c: locais.norm(c["name"]))
    saida = []
    for i, x in enumerate(romanticos):
        for y in romanticos[i + 1:]:
            t = _todas().get(_chave(x["name"], y["name"]))
            saida.append({"a": x["name"], "b": y["name"],
                          "estagios": [relacoes.estagio_de(x), relacoes.estagio_de(y)],
                          "tensao": _visivel(t) if t and t.get("percebida") and t.get("intensidade") else None})
    return saida


def resumo_para_o_mestre() -> str:
    linhas = []
    for t in sorted(_todas().values(), key=lambda t: -int(t.get("intensidade", 0) or 0)):
        if not isinstance(t, dict) or not t.get("intensidade"):
            continue
        v = _visivel(t)
        oculto = "" if t.get("percebida") else " — o protagonista NÃO percebeu"
        ultimo = f"; último: {v['historico'][0]['motivo']}" if v["historico"] and v["historico"][0]["motivo"] else ""
        linhas.append(f"• {v['a']} × {v['b']}: {v['tipo']} {v['intensidade']} ({v['faixa']}){ultimo}{oculto}")
    for tri in triangulos():
        linhas.append(f"• TRIÂNGULO: o protagonista está em {tri['estagios'][0]} com {tri['a']} e em "
                      f"{tri['estagios'][1]} com {tri['b']}. O ciúme vai aparecer: decida quem percebe e "
                      f"registre com ajustar_tensao.")
    return "\n".join(linhas)
