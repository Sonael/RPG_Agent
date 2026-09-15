"""
personagens.py
A ficha de um personagem para a tela: quem é, onde está, a relação com o
grupo e as ligações com a história.

Quase tudo já existia e não aparecia em lugar nenhum do jogo:
  • a atitude (-100 a +100) e o histórico do porquê, de adjust_attitude;
  • as missões que ele encomendou (quests[...]["quem_deu"]);
  • os eventos em que aparece (events[...]["characters_involved"]);
  • o lugar onde está (local) e, se é uma loja, onde trabalha.

O que é novo: "o que o grupo sabe" (`conhecido`, lista de fatos que o
mestre registra com add_character_knowledge). As `notes` ficam como caderno
do mestre e NÃO entram na ficha: o editor sugeria "objetivos secretos" ali,
e mostrar isso ao jogador era spoiler.
"""
from rpg import locais, memory

_FORA_DE_ALCANCE = ("morto", "desaparecido", "preso", "exilado", "fugiu")
MAX_CONHECIDO = 30


def limpar_conhecido(fatos) -> list[str]:
    """
    O que o grupo sabe, como vem dos editores ou da ferramenta: uma lista (ou
    um texto com um fato por linha) sem vazios nem repetidos, os mais recentes
    no fim e no máximo MAX_CONHECIDO.
    """
    if isinstance(fatos, str):
        fatos = fatos.splitlines()
    vistos, saida = set(), []
    for f in fatos or []:
        texto = " ".join(str(f).split()) if isinstance(f, (str, int, float)) else ""
        if texto and locais.norm(texto) not in vistos:
            vistos.add(locais.norm(texto))
            saida.append(texto)
    return saida[-MAX_CONHECIDO:]


def _personagem(nome: str) -> dict | None:
    chars = memory.campaign.get("characters") or {}
    achado = chars.get(memory.char_key(nome or ""))
    if achado:
        return achado
    alvo = locais.norm(nome)
    return next((c for c in chars.values()
                 if isinstance(c, dict) and locais.norm(c.get("name", "")) == alvo), None)


def _cita(texto: str, nome: str) -> bool:
    """O nome aparece como item de uma lista "Brom, Lyra" ou no texto?"""
    alvo = locais.norm(nome)
    if not alvo:
        return False
    partes = [locais.norm(p) for p in (texto or "").replace(";", ",").split(",")]
    return alvo in partes or f" {alvo} " in f" {locais.norm(texto)} "


def ficha(nome: str) -> dict:
    from rpg.tools import _faixa_atitude, atitude_de

    ch = _personagem(nome)
    if not ch:
        return {"existe": False, "nome": (nome or "").strip()}

    nome_real = ch.get("name", nome)
    status = ch.get("status", "") or "vivo"
    do_grupo = bool(memory.is_party_member(ch))

    valor = atitude_de(ch)
    rotulo, conduta = _faixa_atitude(valor)
    historico = [{"delta": int(h.get("delta", 0) or 0), "motivo": h.get("motivo", ""),
                  "capitulo": h.get("cap")}
                 for h in reversed(ch.get("atitude_historico") or []) if isinstance(h, dict)]

    local = ch.get("local", "") or ""
    if do_grupo:
        local = memory.campaign.get("current_location", "") or ""
    alcance = locais.alcance(local) if local else ""

    missoes = []
    for q in (memory.campaign.get("quests") or {}).values():
        if isinstance(q, dict) and q.get("quem_deu") and locais.norm(q["quem_deu"]) == locais.norm(nome_real):
            missoes.append({"titulo": q.get("titulo", ""), "status": q.get("status", "")})

    eventos = [{"resumo": e.get("summary", ""), "local": e.get("location", "")}
               for e in (memory.campaign.get("events") or [])
               if isinstance(e, dict) and _cita(e.get("characters_involved", ""), nome_real)]

    loja = ""
    lugar = locais.lugar(local) if local else None
    if lugar and lugar.get("tipo") == "loja":
        loja = lugar["name"]

    return {
        "existe": True,
        "nome": nome_real,
        "status": status,
        "do_grupo": do_grupo,
        "descricao": ch.get("description", "") or "",
        "tracos": ch.get("traits", "") or "",
        "conhecido": [f for f in (ch.get("conhecido") or []) if isinstance(f, str) and f.strip()],
        "local": {"nome": locais.nome_canonico(local), "alcance": alcance} if local else None,
        # Relação só faz sentido para quem não é do grupo.
        "atitude": None if do_grupo else {
            "valor": valor, "rotulo": rotulo, "conduta": conduta,
            "historico": historico,
        },
        "missoes": missoes,
        "eventos": eventos[-8:],
        "loja": loja,
        "pode_falar": (not do_grupo and bool(alcance)
                       and status.lower() not in _FORA_DE_ALCANCE),
    }
