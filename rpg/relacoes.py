"""
relacoes.py
As relações do romance: como cada pessoa se sente em relação ao protagonista.

No romance o coração do jogo é a relação, e ela só existia como flag solta
(confianca_lucas=alta) e como a atitude das fichas, pensada para a loja e os
testes sociais do D&D. Aqui ela vira dois eixos, com o histórico do porquê:

  • AFETO (-100 a +100): o quanto a pessoa gosta do protagonista. É o mesmo
    campo `atitude` das fichas, então o que o mestre já registrou com
    adjust_attitude continua valendo.
  • CONFIANÇA (-100 a +100): o quanto ela acredita nele. Separada do afeto
    porque o drama mora na diferença: dá para amar quem não se confia.

E o VÍNCULO, a natureza da relação ("interesse romântico", "amizade", "ex",
"rival"), que começa pelo papel da pessoa no grupo e muda quando o mestre diz.

A tela (static/js/relacoes.js) só desenha o que sai de lista(); a ferramenta do
mestre é ajustar_relacao().
"""
from rpg import locais, memory

AFETO = (
    (-100, -60, "aversão"),
    (-59, -20, "atrito"),
    (-19, 19, "neutro"),
    (20, 59, "afeição"),
    (60, 100, "devoção"),
)
CONFIANCA = (
    (-100, -60, "desconfia de você"),
    (-59, -20, "com um pé atrás"),
    (-19, 19, "ainda não sabe"),
    (20, 59, "confia em você"),
    (60, 100, "confia de olhos fechados"),
)
MAX_HISTORICO = 12
HISTORICO_NA_TELA = 4


def _faixa(tabela, valor: int) -> str:
    for baixo, alto, rotulo in tabela:
        if baixo <= valor <= alto:
            return rotulo
    return tabela[2][2]


def _num(valor) -> int:
    try:
        return max(-100, min(100, int(valor or 0)))
    except (TypeError, ValueError):
        return 0


def afeto_de(ch: dict) -> int:
    return _num(ch.get("atitude"))


def confianca_de(ch: dict) -> int:
    return _num(ch.get("confianca"))


def _membro_do_grupo(ch: dict) -> dict | None:
    alvo = locais.norm(ch.get("name", ""))
    return next((p for p in (memory.campaign.get("party") or [])
                 if isinstance(p, dict) and locais.norm(p.get("name", "")) == alvo), None)


def vinculo_de(ch: dict) -> str:
    if ch.get("vinculo"):
        return str(ch["vinculo"])
    membro = _membro_do_grupo(ch)
    return str((membro or {}).get("role") or ch.get("role") or "")


def registrar(ch: dict, eixo: str, delta: int, motivo: str) -> None:
    """Uma linha no histórico da relação (o porquê de cada mudança)."""
    if not delta:
        return
    hist = ch.setdefault("relacao_historico", [])
    hist.append({"eixo": eixo, "delta": int(delta), "motivo": motivo or "",
                 "cap": memory.campaign.get("chapter", 1)})
    del hist[:-MAX_HISTORICO]


def ajustar(nome: str, afeto=0, confianca=0, motivo: str = "", vinculo: str = "") -> str:
    key = memory.char_key(nome or "")
    ch = (memory.campaign.get("characters") or {}).get(key)
    if not ch:
        return (f"Personagem '{nome}' não encontrado. Use save_character primeiro: "
                f"a relação precisa de alguém para lembrar.")
    try:
        d_afeto, d_conf = int(afeto or 0), int(confianca or 0)
    except (TypeError, ValueError):
        return "Informe afeto e confianca como números inteiros (ex: 15, -30)."
    if not (d_afeto or d_conf or vinculo):
        return "Nada a mudar: informe afeto, confianca ou vinculo."

    antes = (afeto_de(ch), confianca_de(ch), vinculo_de(ch))
    if d_afeto:
        ch["atitude"] = _num(antes[0] + d_afeto)
        registrar(ch, "afeto", d_afeto, motivo)
    if d_conf:
        ch["confianca"] = _num(antes[1] + d_conf)
        registrar(ch, "confianca", d_conf, motivo)
    if vinculo:
        ch["vinculo"] = " ".join(str(vinculo).split())

    linhas = [f"{ch['name']}:"]
    if d_afeto:
        linhas.append(f"   afeto {antes[0]:+d} → **{afeto_de(ch):+d}** ({_faixa(AFETO, afeto_de(ch))})")
    if d_conf:
        linhas.append(f"   confiança {antes[1]:+d} → **{confianca_de(ch):+d}** "
                      f"({_faixa(CONFIANCA, confianca_de(ch))})")
    if vinculo and vinculo_de(ch) != antes[2]:
        linhas.append(f"   vínculo: {antes[2] or '—'} → **{vinculo_de(ch)}**")
    if motivo:
        linhas.append(f"   porque: {motivo}")
    memory.save_campaign()
    return "\n".join(linhas)


def _tem_relacao(ch: dict) -> bool:
    return (bool(_membro_do_grupo(ch)) or "atitude" in ch or "confianca" in ch
            or bool(ch.get("vinculo")) or bool(ch.get("relacao_historico")))


def _pessoa(ch: dict) -> dict:
    afeto, conf = afeto_de(ch), confianca_de(ch)
    hist = [{"eixo": h.get("eixo", "afeto"), "delta": int(h.get("delta", 0) or 0),
             "motivo": h.get("motivo", ""), "capitulo": h.get("cap")}
            for h in reversed(ch.get("relacao_historico") or []) if isinstance(h, dict)]
    return {
        "nome": ch.get("name", ""),
        "vinculo": vinculo_de(ch),
        "proximo": bool(_membro_do_grupo(ch)),
        "status": ch.get("status", "") or "vivo",
        "afeto": {"valor": afeto, "rotulo": _faixa(AFETO, afeto)},
        "confianca": {"valor": conf, "rotulo": _faixa(CONFIANCA, conf)},
        "historico": hist[:HISTORICO_NA_TELA],
        "mudancas": len(hist),
    }


def lista() -> dict:
    """
    Quem tem relação com o protagonista, para a tela: as pessoas próximas
    (o grupo) sempre, e quem mais o mestre já mexeu. Próximos primeiro; dentro
    de cada lado, do afeto maior para o menor.
    """
    protagonista = locais.norm(memory.campaign.get("protagonist", "") or "")
    pessoas = [_pessoa(ch) for ch in (memory.campaign.get("characters") or {}).values()
               if isinstance(ch, dict) and ch.get("name")
               and locais.norm(ch["name"]) != protagonista and _tem_relacao(ch)]
    pessoas.sort(key=lambda p: (not p["proximo"], -p["afeto"]["valor"], locais.norm(p["nome"])))
    return {"pessoas": pessoas, "protagonista": memory.campaign.get("protagonist", "") or ""}


def resumo_para_o_mestre() -> str:
    """Todas as relações numa linha cada, para o mestre se situar."""
    pessoas = lista()["pessoas"]
    if not pessoas:
        return "Nenhuma relação registrada ainda."
    linhas = []
    for p in pessoas:
        vinculo = f" ({p['vinculo']})" if p["vinculo"] else ""
        linhas.append(f"• {p['nome']}{vinculo}: "
                      f"afeto {p['afeto']['valor']:+d} ({p['afeto']['rotulo']}), "
                      f"confiança {p['confianca']['valor']:+d} ({p['confianca']['rotulo']})")
    return "\n".join(linhas)
