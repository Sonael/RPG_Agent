"""
segredos.py
Os segredos do romance: os do protagonista e os dos outros.

No romance a tensão mora no que não se diz. Até aqui um segredo era uma flag
(segredo_revelado=sim) ou uma nota do mestre, e contar ou ser descoberto não
mudava nada entre as pessoas. Agora:

  • OS SEUS: o que o protagonista esconde, de quem esconde e quem já sabe.
    Contar a quem se escondia é honestidade (+10 de confiança); contar a
    outro é cumplicidade (+5); quem descobre sozinho aquilo que você escondia
    dele perde confiança (-25). Os dois primeiros casos e a descoberta viram
    momentos na linha do tempo da pessoa.
  • OS DOS OUTROS: o mestre registra desde o começo, mas o jogador só os vê
    depois de revelados — nada de spoiler. Quem conta confia (+10); o que
    você descobre sozinho fica marcado como "não sabe que você sabe".

A tela (a aba Segredos das Relações, o cartão e a ficha) só recebe o que o
protagonista sabe; o mestre recebe tudo, no bloco de cena e em ver_segredos().
"""
from rpg import locais, memory, relacoes

CONTOU_A_QUEM_SE_ESCONDIA = 10
CONTOU_A_OUTRO = 5
DESCOBRIU_O_QUE_SE_ESCONDIA = -25
OUTRO_CONFIOU = 10
MAX_SEGREDOS = 30


def _todos() -> dict:
    return memory.campaign.setdefault("segredos", {})


def _protagonista() -> str:
    return memory.campaign.get("protagonist", "") or ""


def _eh_protagonista(nome: str) -> bool:
    n = locais.norm(nome or "")
    return n in ("", "voce", "eu", "protagonista") or n == locais.norm(_protagonista())


def _personagem(nome: str) -> dict | None:
    chars = memory.campaign.get("characters") or {}
    achado = chars.get(memory.char_key(nome or ""))
    if achado:
        return achado
    alvo = locais.norm(nome)
    return next((c for c in chars.values()
                 if isinstance(c, dict) and locais.norm(c.get("name", "")) == alvo), None)


def _lista_de_nomes(valor) -> list[str]:
    if isinstance(valor, str):
        valor = valor.replace(";", ",").split(",")
    return [" ".join(str(v).split()) for v in (valor or []) if str(v).strip()]


def _achar(titulo: str) -> dict | None:
    return _todos().get(locais.norm(titulo or ""))


def guardar(dono: str, titulo: str, descricao: str = "", escondido_de="", sabem="") -> str:
    titulo = " ".join(str(titulo or "").split())
    if not titulo:
        return "Dê um título ao segredo (ex: \"A bolsa em Lisboa\")."
    if _achar(titulo):
        return f"Já existe um segredo chamado '{titulo}'. Use revelar_segredo para mudar quem sabe."
    if len(_todos()) >= MAX_SEGREDOS:
        return f"Já são {MAX_SEGREDOS} segredos. Resolva algum antes de guardar outro."
    do_protagonista = _eh_protagonista(dono)
    if not do_protagonista and not _personagem(dono):
        return f"Personagem '{dono}' não encontrado. Use save_character primeiro."

    nomes, faltam = {}, []
    for campo, valor in (("escondido_de", escondido_de), ("sabem", sabem)):
        nomes[campo] = []
        for n in _lista_de_nomes(valor):
            ch = _personagem(n)
            if not ch:
                faltam.append(n)
            elif not _eh_protagonista(ch.get("name", "")):
                nomes[campo].append(ch["name"])
    if faltam:
        return f"Personagens não encontrados: {', '.join(faltam)}. Use save_character primeiro."
    if not do_protagonista and nomes["escondido_de"]:
        return ("O segredo de outra pessoa é escondido do protagonista por definição: "
                "use sabem= para quem mais sabe.")

    _todos()[locais.norm(titulo)] = {
        "titulo": titulo,
        "descricao": " ".join(str(descricao or "").split()),
        "dono": "" if do_protagonista else _personagem(dono)["name"],
        "escondido_de": nomes["escondido_de"],
        "sabem": nomes["sabem"],
        # Só para o segredo de outra pessoa: o protagonista já sabe? E o dono
        # sabe que ele sabe?
        "revelado": False, "como": "", "dono_sabe": True,
        "cap": memory.campaign.get("chapter", 1),
        "historico": [],
    }
    memory.save_campaign()
    de_quem = "seu" if do_protagonista else f"de {_personagem(dono)['name']}"
    extra = f"; escondido de {', '.join(nomes['escondido_de'])}" if nomes["escondido_de"] else ""
    return f"Segredo {de_quem} guardado: **{titulo}**{extra}."


def _momento(nome: str, titulo: str, descricao: str = "") -> None:
    ch = _personagem(nome)
    if ch:
        relacoes._anotar_momento(ch, titulo, descricao, tipo="segredo")


def revelar(titulo: str, a_quem: str = "", como: str = "contou") -> str:
    s = _achar(titulo)
    if not s:
        return f"Segredo '{titulo}' não encontrado. ver_segredos() lista todos."
    como = locais.norm(como or "contou")
    if como not in ("contou", "descobriu"):
        return "Use como=\"contou\" (alguém contou) ou como=\"descobriu\" (descobriu sozinho)."
    cap = memory.campaign.get("chapter", 1)

    if not s["dono"]:
        # Segredo do protagonista chegando a alguém.
        ch = _personagem(a_quem)
        if not ch or _eh_protagonista(ch.get("name", "")):
            return f"Personagem '{a_quem}' não encontrado."
        nome = ch["name"]
        if nome in s["sabem"]:
            return f"{nome} já sabe de '{s['titulo']}'."
        escondia = nome in s["escondido_de"]
        s["escondido_de"] = [n for n in s["escondido_de"] if n != nome]
        s["sabem"].append(nome)
        s["historico"].append({"acao": como, "quem": nome, "cap": cap})
        if como == "contou":
            delta = CONTOU_A_QUEM_SE_ESCONDIA if escondia else CONTOU_A_OUTRO
            motivo = f"Você contou: {s['titulo']}"
            if escondia:
                _momento(nome, motivo, s["descricao"])
        else:
            delta = DESCOBRIU_O_QUE_SE_ESCONDIA if escondia else 0
            motivo = f"Descobriu o que você escondia: {s['titulo']}"
            if escondia:
                _momento(nome, motivo, s["descricao"])
        linhas = [f"{nome} agora sabe de **{s['titulo']}** ({como})."]
        if delta:
            linhas.append(relacoes.ajustar(nome, confianca=delta, motivo=motivo))
        if not s["escondido_de"] and escondia:
            linhas.append("   Ninguém de quem você escondia está mais no escuro.")
        memory.save_campaign()
        return "\n".join(linhas)

    # Segredo de outra pessoa chegando ao protagonista.
    if a_quem and not _eh_protagonista(a_quem):
        return ("Por enquanto só o protagonista descobre o segredo de outra pessoa. "
                "Para outro personagem saber, guarde isso nas notas dele.")
    if s["revelado"]:
        return f"O protagonista já sabe de '{s['titulo']}'."
    s["revelado"], s["como"], s["dono_sabe"] = True, como, como == "contou"
    s["cap_revelado"] = cap
    s["historico"].append({"acao": como, "quem": _protagonista() or "protagonista", "cap": cap})
    dono = s["dono"]
    linhas = [f"O protagonista agora sabe de **{s['titulo']}**, segredo de {dono} ({como})."]
    if como == "contou":
        _momento(dono, f"Contou a você: {s['titulo']}", s["descricao"])
        linhas.append(relacoes.ajustar(dono, confianca=OUTRO_CONFIOU, motivo=f"Confiou a você: {s['titulo']}"))
    else:
        _momento(dono, f"Você descobriu: {s['titulo']}", s["descricao"])
        linhas.append(f"   {dono} NÃO sabe que o protagonista sabe. Use isso.")
    memory.save_campaign()
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# O que o jogador vê (só o que o protagonista sabe)
# ---------------------------------------------------------------------------

def visiveis() -> dict:
    seus, dos_outros = [], []
    for s in _todos().values():
        if not isinstance(s, dict):
            continue
        hist = [{"acao": h.get("acao", ""), "quem": h.get("quem", ""), "capitulo": h.get("cap")}
                for h in reversed(s.get("historico") or []) if isinstance(h, dict)]
        if not s.get("dono"):
            seus.append({"titulo": s["titulo"], "descricao": s.get("descricao", ""),
                         "escondido_de": list(s.get("escondido_de") or []),
                         "sabem": list(s.get("sabem") or []), "historico": hist,
                         "capitulo": s.get("cap")})
        elif s.get("revelado"):
            dos_outros.append({"dono": s["dono"], "titulo": s["titulo"], "descricao": s.get("descricao", ""),
                               "como": s.get("como", ""), "dono_sabe": bool(s.get("dono_sabe")),
                               "capitulo": s.get("cap_revelado")})
    # Os que ainda escondem de alguém primeiro: é onde está a tensão.
    seus.sort(key=lambda s: (not s["escondido_de"], locais.norm(s["titulo"])))
    dos_outros.sort(key=lambda s: (locais.norm(s["dono"]), locais.norm(s["titulo"])))
    return {"seus": seus, "dos_outros": dos_outros}


def da_pessoa(nome: str) -> dict:
    """Os segredos que tocam uma pessoa, do jeito que o protagonista os vê."""
    n = locais.norm(nome)
    v = visiveis()
    return {
        "voce_esconde": [s["titulo"] for s in v["seus"] if n in {locais.norm(x) for x in s["escondido_de"]}],
        "sabe_dos_seus": [s["titulo"] for s in v["seus"] if n in {locais.norm(x) for x in s["sabem"]}],
        "voce_sabe_dele": [{"titulo": s["titulo"], "dono_sabe": s["dono_sabe"]}
                           for s in v["dos_outros"] if locais.norm(s["dono"]) == n],
    }


def envolvidos() -> set[str]:
    """Quem aparece em algum segredo visível (entra na lista de Relações)."""
    v = visiveis()
    nomes = {locais.norm(x) for s in v["seus"] for x in s["escondido_de"] + s["sabem"]}
    return nomes | {locais.norm(s["dono"]) for s in v["dos_outros"]}


# ---------------------------------------------------------------------------
# O que o mestre vê (tudo)
# ---------------------------------------------------------------------------

def resumo_para_o_mestre() -> str:
    linhas = []
    for s in _todos().values():
        if not isinstance(s, dict):
            continue
        if not s.get("dono"):
            partes = []
            if s.get("escondido_de"):
                partes.append(f"escondido de {', '.join(s['escondido_de'])}")
            if s.get("sabem"):
                partes.append(f"sabem: {', '.join(s['sabem'])}")
            linhas.append(f"• Do protagonista — {s['titulo']}"
                          + (f": {s['descricao']}" if s.get("descricao") else "")
                          + (f" ({'; '.join(partes)})" if partes else ""))
        else:
            if not s.get("revelado"):
                estado = "o protagonista NÃO sabe — não revele antes da história"
            elif s.get("dono_sabe"):
                estado = f"contou ao protagonista"
            else:
                estado = f"o protagonista descobriu, e {s['dono']} não sabe que ele sabe"
            linhas.append(f"• De {s['dono']} — {s['titulo']}"
                          + (f": {s['descricao']}" if s.get("descricao") else "") + f" ({estado})")
    return "\n".join(linhas) if linhas else "Nenhum segredo guardado ainda."


# ---------------------------------------------------------------------------
# Importação (JSON de outro chat ou do editor)
# ---------------------------------------------------------------------------

def importar(valor, protagonista: str = "") -> dict:
    """
    Os segredos de um JSON importado, no formato do jogo: chave pelo título,
    listas de nomes, o dono vazio quando é o protagonista e os campos que
    faltarem com o padrão. Aceita dict (como o jogo grava) ou lista.
    """
    itens = valor.values() if isinstance(valor, dict) else (valor or [])
    prot = locais.norm(protagonista or "")
    saida = {}
    for s in itens:
        if not isinstance(s, dict):
            continue
        titulo = " ".join(str(s.get("titulo") or "").split())
        if not titulo or locais.norm(titulo) in saida:
            continue
        dono = " ".join(str(s.get("dono") or "").split())
        if locais.norm(dono) in ("", "voce", "eu", "protagonista", prot):
            dono = ""
        revelado = bool(s.get("revelado")) and bool(dono)
        como = locais.norm(s.get("como") or "")
        como = como if como in ("contou", "descobriu") else ("contou" if revelado else "")
        saida[locais.norm(titulo)] = {
            "titulo": titulo,
            "descricao": " ".join(str(s.get("descricao") or "").split()),
            "dono": dono,
            "escondido_de": [] if dono else _lista_de_nomes(s.get("escondido_de")),
            "sabem": _lista_de_nomes(s.get("sabem")),
            "revelado": revelado, "como": como if revelado else "",
            "dono_sabe": como != "descobriu" if revelado else True,
            "cap": s.get("cap") or 1,
            "historico": [h for h in (s.get("historico") or []) if isinstance(h, dict)],
        }
        if revelado:
            saida[locais.norm(titulo)]["cap_revelado"] = s.get("cap_revelado") or s.get("cap") or 1
        if len(saida) >= MAX_SEGREDOS:
            break
    return saida
