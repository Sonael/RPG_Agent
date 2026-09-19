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

O ESTÁGIO é onde a relação está numa escada — conhecidos, amizade, flerte,
namoro, compromisso — ou fora dela, no rompimento (que guarda até onde ela
chegou). Uma amizade pode parar na amizade para sempre: a escada não obriga
ninguém a virar romance. Quem muda o estágio é o mestre, com mudar_estagio();
afeto e confiança só dizem a ELE quando o próximo passo está maduro (a tela
não mostra isso, para não virar placar).

Os MOMENTOS são a memória da relação: o primeiro beijo, a briga na chuva, a
noite em que ela contou do pai. Uma linha do tempo por pessoa, que o mestre
marca com marcar_momento() e que volta para ele no bloco de cena, para poder
lembrar ("ele ainda guarda o guarda-chuva"). Toda mudança de estágio vira um
momento sozinha.

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
MAX_MOMENTOS = 20

# A escada, em ordem, e o que costuma sustentar cada degrau: (afeto, confiança)
# mínimos. É sugestão para o mestre, não trava — amor à primeira vista existe,
# e a ferramenta só avisa quando o degrau parece cedo demais.
ESCADA = ("conhecidos", "amizade", "flerte", "namoro", "compromisso")
ROMPIMENTO = "rompimento"
ESTAGIOS = ESCADA + (ROMPIMENTO,)
MADURO = {
    "amizade":     (20, 0),
    "flerte":      (35, 0),
    "namoro":      (55, 20),
    "compromisso": (75, 50),
}


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


def estagio_de(ch: dict) -> str:
    """Onde a relação está. Sem registro: amizade para quem é próximo, conhecidos para o resto."""
    e = locais.norm(ch.get("estagio", "") or "")
    if e in ESTAGIOS:
        return e
    return "amizade" if _membro_do_grupo(ch) else "conhecidos"


def _proximo_degrau(ch: dict) -> str:
    atual = estagio_de(ch)
    if atual == ROMPIMENTO or atual == ESCADA[-1]:
        return ""
    return ESCADA[ESCADA.index(atual) + 1]


def madura_para(ch: dict) -> str:
    """O próximo degrau, se afeto e confiança já o sustentam. Só para o mestre."""
    prox = _proximo_degrau(ch)
    if not prox:
        return ""
    afeto_min, conf_min = MADURO[prox]
    return prox if afeto_de(ch) >= afeto_min and confianca_de(ch) >= conf_min else ""


def _anotar_momento(ch: dict, titulo: str, descricao: str = "", tipo: str = "momento") -> dict:
    m = {"titulo": " ".join(str(titulo).split()), "descricao": " ".join(str(descricao or "").split()),
         "tipo": tipo, "cap": memory.campaign.get("chapter", 1)}
    lista = ch.setdefault("momentos", [])
    lista.append(m)
    del lista[:-MAX_MOMENTOS]
    return m


def _personagem(nome: str):
    return (memory.campaign.get("characters") or {}).get(memory.char_key(nome or ""))


_MARCO = {
    "conhecidos": "Voltaram a ser só conhecidos",
    "amizade": "Viraram amigos",
    "flerte": "Começou o flerte",
    "namoro": "Começaram a namorar",
    "compromisso": "Assumiram um compromisso",
    ROMPIMENTO: "Romperam",
}


def mudar_estagio(nome: str, estagio: str, motivo: str = "") -> str:
    ch = _personagem(nome)
    if not ch:
        return f"Personagem '{nome}' não encontrado. Use save_character primeiro."
    novo = locais.norm(estagio or "")
    if novo not in ESTAGIOS:
        return f"Estágio desconhecido: '{estagio}'. Use um de: {', '.join(ESTAGIOS)}."
    antes = estagio_de(ch)
    if novo == antes:
        return f"{ch['name']} já está em {antes}."
    if novo == ROMPIMENTO:
        # Guarda até onde a relação chegou: é o que torna uma reconciliação
        # diferente de começar do zero.
        ch["estagio_antes"] = antes
    ch["estagio"] = novo
    titulo = _MARCO[novo]
    if antes == ROMPIMENTO and novo != ROMPIMENTO:
        titulo = f"Reconciliação: {_MARCO[novo][0].lower()}{_MARCO[novo][1:]}"
    _anotar_momento(ch, titulo, motivo, tipo="estagio")

    linhas = [f"{ch['name']}: {antes} → **{novo}**" + (f" — {motivo}" if motivo else "")]
    if novo in MADURO:
        afeto_min, conf_min = MADURO[novo]
        if afeto_de(ch) < afeto_min or confianca_de(ch) < conf_min:
            linhas.append(f"   Aviso: afeto {afeto_de(ch):+d} e confiança {confianca_de(ch):+d} ainda são baixos "
                          f"para {novo} (costuma pedir {afeto_min:+d} e {conf_min:+d}). Se a cena justifica, siga; "
                          f"senão, volte com mudar_estagio.")
    memory.save_campaign()
    return "\n".join(linhas)


def marcar_momento(nome: str, titulo: str, descricao: str = "") -> str:
    ch = _personagem(nome)
    if not ch:
        return f"Personagem '{nome}' não encontrado. Use save_character primeiro."
    if not " ".join(str(titulo or "").split()):
        return "Dê um título ao momento (ex: \"O primeiro beijo\")."
    ja = [locais.norm(m.get("titulo", "")) for m in ch.get("momentos") or []]
    if locais.norm(titulo) in ja:
        return f"Esse momento com {ch['name']} já está registrado."
    m = _anotar_momento(ch, titulo, descricao)
    memory.save_campaign()
    return f"Momento com {ch['name']} registrado: **{m['titulo']}** (cap. {m['cap']})."


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
    from rpg import encontros, segredos
    if locais.norm(ch.get("name", "")) in segredos.envolvidos():
        return True
    if encontros.da_pessoa(ch.get("name", "")):
        return True
    return (bool(_membro_do_grupo(ch)) or "atitude" in ch or "confianca" in ch
            or bool(ch.get("vinculo")) or bool(ch.get("relacao_historico"))
            or bool(ch.get("estagio")) or bool(ch.get("momentos")))


def _encontros_da_pessoa(nome: str) -> list:
    from rpg import encontros
    return encontros.da_pessoa(nome)


def _segredos_da_pessoa(nome: str) -> dict:
    from rpg import segredos
    return segredos.da_pessoa(nome)


def _pessoa(ch: dict) -> dict:
    afeto, conf = afeto_de(ch), confianca_de(ch)
    hist = [{"eixo": h.get("eixo", "afeto"), "delta": int(h.get("delta", 0) or 0),
             "motivo": h.get("motivo", ""), "capitulo": h.get("cap")}
            for h in reversed(ch.get("relacao_historico") or []) if isinstance(h, dict)]
    estagio = estagio_de(ch)
    antes = locais.norm(ch.get("estagio_antes", "") or "")
    momentos = [{"titulo": m.get("titulo", ""), "descricao": m.get("descricao", ""),
                 "tipo": m.get("tipo", "momento"), "capitulo": m.get("cap")}
                for m in reversed(ch.get("momentos") or []) if isinstance(m, dict)]
    return {
        "nome": ch.get("name", ""),
        "vinculo": vinculo_de(ch),
        # A escada e onde a relação está nela. No rompimento, `chegou_a` é o
        # degrau em que ela estava antes de romper.
        "estagio": {"atual": estagio, "escada": list(ESCADA),
                    "chegou_a": (antes if antes in ESCADA else "") if estagio == ROMPIMENTO else ""},
        "momentos": momentos,
        "segredos": _segredos_da_pessoa(ch.get("name", "")),
        "encontros": _encontros_da_pessoa(ch.get("name", "")),
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
    from rpg import segredos
    return {"pessoas": pessoas, "protagonista": memory.campaign.get("protagonist", "") or "",
            "segredos": segredos.visiveis()}


def resumo_para_o_mestre() -> str:
    """Todas as relações numa linha cada, para o mestre se situar."""
    pessoas = lista()["pessoas"]
    if not pessoas:
        return "Nenhuma relação registrada ainda."
    linhas = []
    for p in pessoas:
        vinculo = f" ({p['vinculo']})" if p["vinculo"] else ""
        ch = _personagem(p["nome"]) or {}
        madura = madura_para(ch)
        linhas.append(f"• {p['nome']}{vinculo} — {p['estagio']['atual']}: "
                      f"afeto {p['afeto']['valor']:+d} ({p['afeto']['rotulo']}), "
                      f"confiança {p['confianca']['valor']:+d} ({p['confianca']['rotulo']})"
                      + (f" · madura para {madura}" if madura else ""))
        for m in p["momentos"][:2]:
            linhas.append(f"    lembram: {m['titulo']}" + (f" — {m['descricao']}" if m["descricao"] else "")
                          + (f" (cap. {m['capitulo']})" if m["capitulo"] else ""))
    return "\n".join(linhas)


def bloco_de_cena() -> str:
    """
    As relações no bloco de cena do romance, a cada turno. Sem isto o mestre só
    sabia do afeto e dos momentos se chamasse ver_relacoes(), e não chamava: o
    primeiro beijo do capítulo 2 não voltava na conversa do capítulo 5.
    """
    from rpg import encontros, segredos
    if (memory.campaign.get("campaign_type") or "") != "romance":
        return ""
    tem_segredos = bool(memory.campaign.get("segredos"))
    agenda = encontros.resumo_para_o_mestre()
    if not lista()["pessoas"] and not tem_segredos and not agenda:
        return ""
    bloco = ("\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
             "RELAÇÕES (estágio, afeto, confiança e o que lembram juntos)\n"
             "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
             "Use os momentos na narração: as pessoas lembram. \"Madura para\" é só "
             "para você: o passo acontece quando a cena pedir, com mudar_estagio().\n"
             + resumo_para_o_mestre())
    if tem_segredos:
        bloco += ("\n\nSEGREDOS (você vê todos; o jogador só vê os dele e os que já descobriu)\n"
                  "Um segredo escondido é tensão: deixe-o pesar nas cenas, dê pistas, "
                  "e revele só quando a história revelar, com revelar_segredo().\n"
                  + segredos.resumo_para_o_mestre())
    if agenda:
        bloco += ("\n\nENCONTROS MARCADOS (pelo relógio do mundo)\n"
                  "Quando chegar a hora, narre o encontro — ou a falta — e feche com "
                  "resolver_encontro(). O jogador vê o próximo na barra.\n" + agenda)
    return bloco
