"""
manobras.py
As ações de combate que não tinham botão nem regra: Ajudar, Esconder-se,
Agarrar, Escapar, Empurrar e Preparar.

POR QUE EXISTE
──────────────
A tela tinha Atacar, Habilidade, Item, Mover, Defender e Fugir. O resto ia
pela Ação Livre, e o Mestre arbitrava sem a regra: "ajudo o guerreiro" virava
uma frase, não a vantagem do SRD; "agarro o goblin" não era o teste de
Atletismo contra Atletismo ou Acrobacia, e o goblin agarrado seguia andando.

Todas gastam a Ação. Agarrar e Empurrar exigem a mesma zona (sem zonas, todos
estão perto).
"""
from __future__ import annotations

import random

from rpg import memory


def _td():
    from rpg import tools_dnd
    return tools_dnd


def _ch(nome: str) -> dict | None:
    return memory.campaign.get("characters", {}).get(memory.char_key(nome or ""))


def _perto(a: str, b: str) -> bool:
    d = _td()._distancia(a, b)
    return d is None or d == 0


def _pericia(ch: dict, pericia: str, atributo: str) -> tuple[int, int]:
    """(total do teste, bônus) de Atletismo ou Acrobacia."""
    td = _td()
    s = ch.get("sheet") or {}
    bonus = td._modifier(int(s.get(atributo, 10) or 10))
    if td._proficiente_na_pericia(s, pericia):
        bonus += int(s.get("proficiencia", 2) or 2)
    d20 = random.randint(1, 20)
    return d20 + bonus, bonus


def _disputa(atacante: dict, alvo: dict) -> tuple[bool, str]:
    """Atletismo de quem ataca contra o melhor de Atletismo e Acrobacia do alvo."""
    atk, b_atk = _pericia(atacante, "atletismo", "forca")
    atl, _ = _pericia(alvo, "atletismo", "forca")
    acr, _ = _pericia(alvo, "acrobacia", "destreza")
    defesa = max(atl, acr)
    venceu = atk > defesa
    return venceu, (f"Atletismo de {atacante['name']} {atk} contra "
                    f"{'Atletismo' if atl >= acr else 'Acrobacia'} de {alvo['name']} {defesa}")


def _validar_alvo(ator: str, alvo: str, verbo: str) -> tuple[dict | None, dict | None, str]:
    a, b = _ch(ator), _ch(alvo)
    if not a or not b or not b.get("sheet"):
        return None, None, f"Erro: escolha quem {verbo}."
    if (b.get("status") or "").lower() in _td().OUT_OF_COMBAT_STATUSES:
        return None, None, f"Erro: {b['name']} está fora de combate."
    if not _perto(ator, alvo):
        return None, None, (f"Erro: {b['name']} está em outra zona — {verbo} só alcança quem "
                            f"está na sua zona.")
    return a, b, ""


def ajudar(ator: str, alvo: str) -> str:
    """O próximo ataque de um aliado contra o alvo tem vantagem (até o seu próximo turno)."""
    a, b, erro = _validar_alvo(ator, alvo, "ajudar contra")
    if erro:
        return erro
    if memory.luta_com_o_grupo(a) == memory.luta_com_o_grupo(b):
        return f"Erro: Ajudar distrai um INIMIGO para o próximo ataque de um aliado. {b['name']} é aliado."
    _td().dar_efeito_de_combate(b, {"nome": f"Ajuda de {a['name']}", "vantagem_contra_mim": True,
                                    "usos": 1, "ate_turno_de": memory.char_key(a["name"])})
    return (f"{a['name']} ajuda: distrai {b['name']} — o próximo ataque de um aliado contra "
            f"{b['name']} tem vantagem (até o próximo turno de {a['name']}).")


def pedir_rendicao(ator: str, alvo: str, modo: str = "") -> str:
    """
    Pedir rendição (gasta a Ação): Intimidação ou Persuasão de quem pede
    contra a Sabedoria do inimigo. Rendido, ele larga as armas e sai da luta,
    vivo — e só com inimigos rendidos, enfeitiçados ou dominados sobrando, a
    luta acaba.

    • Dominado por alguém do grupo: rende-se sem teste.
    • Enfeitiçado por alguém do grupo: quem pede tem vantagem (o encantado
      trata o grupo como amigo).
    • O inimigo inteiro (mais da metade da vida) e com o lado dele ainda em
      número tem vantagem: ainda acha que vence. Ferido (metade ou menos), ele
      rola com desvantagem.
    • Sem mente para entender (INT 3 ou menos; constructo ou morto-vivo sem
      vontade própria) não se rende.
    """
    td = _td()
    a, b = _ch(ator), _ch(alvo)
    if not a or not b or not b.get("sheet"):
        return "Erro: escolha quem deve se render."
    if memory.luta_com_o_grupo(a) == memory.luta_com_o_grupo(b):
        return f"Erro: {b['name']} não luta contra {a['name']}."
    if (b.get("status") or "").lower() in td.OUT_OF_COMBAT_STATUSES:
        return f"Erro: {b['name']} já está fora da luta."
    if td._zonas_ativas() and (td._distancia(ator, alvo) or 0) > 1:
        return f"Erro: {b['name']} está longe demais para ouvir — chegue a uma zona vizinha."
    calado = td._zona_silenciada(ator) or td._zona_silenciada(alvo)
    if calado:
        return f"Erro: o {calado} engole a voz: ninguém ouve o pedido."
    s_b = b["sheet"]
    from rpg import tracos
    tipo = tracos.tipo_de_criatura(b)
    if int(s_b.get("inteligencia", 10) or 10) <= 3 or (
            tipo in ("constructo", "morto-vivo") and int(s_b.get("inteligencia", 10) or 10) <= 6):
        return (f"Aviso: {b['name']} não tem como entender um pedido de rendição — luta até cair "
                f"(ou foge). A Ação não foi gasta.")
    if (b.get("sheet") or {}).get("recusa_rendicao"):
        return (f"{a['name']} pede a rendição de {b['name']}, que recusa: viu o que fizeram com quem largou "
                f"as armas. Continua lutando.")
    pou = td.poupado(b)
    if pou == "dominado":
        b["status"] = "rendido"
        _td()._log_combat_event("surrender", b["name"], a["name"], msg=f"{b['name']} se rende a {a['name']}")
        return f"{a['name']} manda {b['name']} largar as armas, e o dominado obedece: **RENDIDO**."
    pericia, atributo = (("persuasao", "carisma") if (modo or "").startswith("persu")
                         else ("intimidacao", "carisma"))
    rotulo = "Persuasão" if pericia == "persuasao" else "Intimidação"
    vant_a = pou == "enfeiticado" or pou == "enfeitiçado"
    s_a = a.get("sheet") or {}
    bonus_a = td._modifier(int(s_a.get(atributo, 10) or 10))
    if td._proficiente_na_pericia(s_a, pericia):
        bonus_a += int(s_a.get("proficiencia", 2) or 2)
    d_a = [random.randint(1, 20) for _ in range(2 if vant_a else 1)]
    total_a = max(d_a) + bonus_a
    # O lado do inimigo ainda em número? Ele inteiro acha que vence.
    cs = memory.campaign.get("combat_state") or {}
    de_pe = lambda c: (c and (c.get("status") or "").lower() not in td.OUT_OF_COMBAT_STATUSES  # noqa: E731
                       and int((c.get("sheet") or {}).get("vida_atual", 0) or 0) > 0 and not td.poupado(c))
    lados = [memory.campaign["characters"].get(memory.char_key(n)) for n in cs.get("initiative_order") or []]
    deles = sum(1 for c in lados if de_pe(c) and memory.luta_com_o_grupo(c) == memory.luta_com_o_grupo(b))
    nossos = sum(1 for c in lados if de_pe(c) and memory.luta_com_o_grupo(c) == memory.luta_com_o_grupo(a))
    vida, vida_max = int(s_b.get("vida_atual", 0) or 0), max(1, int(s_b.get("vida_max", 1) or 1))
    ferido = vida * 2 <= vida_max
    vant_b = (not ferido) and deles >= nossos
    desv_b = ferido
    mod_b = td._modifier(int(s_b.get("sabedoria", 10) or 10))
    d_b = [random.randint(1, 20) for _ in range(2 if (vant_b != desv_b) else 1)]
    d20_b = (max(d_b) if vant_b and not desv_b else min(d_b) if desv_b and not vant_b else d_b[0])
    total_b = d20_b + mod_b
    nota_b = ("vantagem: inteiro e em número" if vant_b and not desv_b
              else "desvantagem: ferido" if desv_b and not vant_b else "")
    linha = (f"{rotulo} de {a['name']} {total_a}" + (" (vantagem: enfeitiçado)" if vant_a else "")
             + f" contra Sabedoria de {b['name']} {total_b}" + (f" ({nota_b})" if nota_b else ""))
    if total_a > total_b:
        b["status"] = "rendido"
        s_b["concentracao"] = None
        soltar_quem_agarrou(b["name"])
        _td()._log_combat_event("surrender", b["name"], a["name"], msg=f"{b['name']} se rende a {a['name']}")
        return f"{a['name']} pede a rendição de {b['name']}: {linha} — {b['name']} larga as armas: **RENDIDO**."
    return f"{a['name']} pede a rendição de {b['name']}: {linha} — {b['name']} recusa e continua lutando."


# ---------------------------------------------------------------------------
# Montaria
# ---------------------------------------------------------------------------

def montaria_de(ch: dict | None) -> dict | None:
    """A criatura em que `ch` está montado."""
    chave = ((ch or {}).get("sheet") or {}).get("montado_em")
    return memory.campaign.get("characters", {}).get(chave) if chave else None


def cavaleiro_de(ch: dict | None) -> dict | None:
    chave = ((ch or {}).get("sheet") or {}).get("montaria_de")
    return memory.campaign.get("characters", {}).get(chave) if chave else None


def _pode_ser_montaria(c: dict) -> bool:
    from rpg import criaturas
    s = c.get("sheet") or {}
    if s.get("montaria"):
        return True
    inv = c.get("invocacao") or {}
    if _td()._norm_txt(inv.get("magia", "")) in ("find steed", "encontrar montaria"):
        return True
    for chave, f in criaturas.FICHAS.items():
        if f.get("montaria") and _td()._norm_txt(f["nome"]) in _td()._norm_txt(c.get("name", "")):
            return True
    return False


def montarias_livres(ch: dict | None) -> list[str]:
    """As montarias do lado de `ch`, de pé, na zona dele, sem cavaleiro."""
    td = _td()
    if not ch:
        return []
    cs = memory.campaign.get("combat_state") or {}
    saida = []
    for n in cs.get("initiative_order") or []:
        c = _ch(n)
        if (not c or c is ch or memory.luta_com_o_grupo(c) != memory.luta_com_o_grupo(ch)
                or not _pode_ser_montaria(c) or cavaleiro_de(c)
                or (c.get("status") or "").lower() in td.OUT_OF_COMBAT_STATUSES
                or int((c.get("sheet") or {}).get("vida_atual", 0) or 0) <= 0):
            continue
        if td._zonas_ativas() and td._zona_de(c["name"]) != td._zona_de(ch.get("name", "")):
            continue
        saida.append(c["name"])
    return saida


def montar(ator: str, alvo: str) -> str:
    """Montar (gasta o movimento): numa montaria do seu lado, de pé, na sua zona, que ninguém monta."""
    td = _td()
    a, b = _ch(ator), _ch(alvo)
    if not a or not b or not b.get("sheet"):
        return "Erro: escolha a montaria."
    if montaria_de(a):
        return f"Erro: {a['name']} já está montado em {montaria_de(a)['name']}."
    if memory.luta_com_o_grupo(a) != memory.luta_com_o_grupo(b) or not _pode_ser_montaria(b):
        return f"Erro: {b['name']} não é montaria de {a['name']}."
    if cavaleiro_de(b):
        return f"Erro: {cavaleiro_de(b)['name']} já monta {b['name']}."
    if (b.get("status") or "").lower() in td.OUT_OF_COMBAT_STATUSES or int(b["sheet"].get("vida_atual", 0) or 0) <= 0:
        return f"Erro: {b['name']} está fora de combate."
    if td._zonas_ativas() and td._zona_de(a["name"]) != td._zona_de(b["name"]):
        return f"Erro: {b['name']} está em outra zona."
    if any(td._norm_txt(c.get("nome", "") if isinstance(c, dict) else str(c)) == "caido"
           for c in b["sheet"].get("condicoes") or []):
        return f"Erro: {b['name']} está Caído."
    a["sheet"]["montado_em"] = memory.char_key(b["name"])
    b["sheet"]["montaria_de"] = memory.char_key(a["name"])
    td._log_combat_event("mount", a["name"], b["name"], msg=f"{a['name']} monta {b['name']}")
    return (f"{a['name']} monta {b['name']}: os dois se movem juntos; se {b['name']} cair, {a['name']} "
            f"faz DES CD 10 ou cai Caído.")


def desmontar(ator: str, motivo: str = "") -> str:
    a = _ch(ator)
    m = montaria_de(a)
    if not a or not m:
        return f"Erro: {ator} não está montado."
    a["sheet"].pop("montado_em", None)
    m["sheet"].pop("montaria_de", None)
    _td()._log_combat_event("dismount", a["name"], m["name"], msg=f"{a['name']} desmonta de {m['name']}")
    return f"{a['name']} desmonta de {m['name']}" + (f" ({motivo})" if motivo else "") + "."


def queda_da_montaria(montaria: dict, motivo: str) -> str:
    """A montaria caiu (Caída ou a 0 PV): quem monta faz DES CD 10 ou cai Caído."""
    td = _td()
    quem = cavaleiro_de(montaria)
    if not quem:
        return ""
    desmontar(quem["name"], motivo)
    passou, linha = td._rolar_salvaguarda(quem, "destreza", 10)
    if passou:
        return f"{quem['name']} salta de {montaria['name']} ({motivo}): {linha} — cai de pé."
    conds = quem["sheet"].setdefault("condicoes", [])
    if not any(td._norm_txt(c.get("nome", "") if isinstance(c, dict) else str(c)) == "caido" for c in conds):
        conds.append({"nome": "Caído", "duracao": None})
    return f"{quem['name']} é jogado de {montaria['name']} ({motivo}): {linha} — CAÍDO."


def esconder(ator: str) -> str:
    from rpg import resolucao
    a = _ch(ator)
    return f"{a['name']} tenta se esconder." + resolucao._acao_de_movimento(a, "esconder", "Esconder-se")


def agarrar(ator: str, alvo: str) -> str:
    a, b, erro = _validar_alvo(ator, alvo, "agarrar")
    if erro:
        return erro
    venceu, linha = _disputa(a, b)
    if not venceu:
        return f"{a['name']} tenta agarrar {b['name']}: {linha} — escapa."
    conds = b["sheet"].setdefault("condicoes", [])
    conds[:] = [c for c in conds if not (isinstance(c, dict) and c.get("nome") == "Agarrado")]
    conds.append({"nome": "Agarrado", "duracao": None, "por": a["name"]})
    _td()._log_combat_event("condition", a["name"], b["name"], msg=f"{b['name']} foi agarrado por {a['name']}")
    return (f"{a['name']} agarra {b['name']}: {linha} — **AGARRADO** (não sai da zona; "
            f"solta se {a['name']} sair da zona ou cair, ou se {b['name']} escapar).")


def _soltar_contido(ch: dict, nome_de_quem: str) -> None:
    """A mordida que agarra também prende (Contido): solta junto com a pegada."""
    conds = ((ch or {}).get("sheet") or {}).get("condicoes")
    if isinstance(conds, list):
        ch["sheet"]["condicoes"] = [c for c in conds if not (
            isinstance(c, dict) and c.get("da_pegada")
            and memory.char_key(c.get("por", "")) == memory.char_key(nome_de_quem))]


def escapar(ator: str) -> str:
    a = _ch(ator)
    pegada = next((c for c in (a.get("sheet") or {}).get("condicoes") or []
                   if isinstance(c, dict) and c.get("nome") == "Agarrado"), None)
    if not pegada:
        return f"Erro: {a['name']} não está agarrado."
    quem = _ch(pegada.get("por", ""))
    if not quem:
        a["sheet"]["condicoes"].remove(pegada)
        _soltar_contido(a, pegada.get("por", ""))
        return f"{a['name']} se solta."
    atl, _ = _pericia(a, "atletismo", "forca")
    acr, _ = _pericia(a, "acrobacia", "destreza")
    # A pegada da criatura tem CD fixa (a mordida do crocodilo: CD 12).
    if pegada.get("escapa_cd"):
        cd = int(pegada["escapa_cd"])
        if max(atl, acr) >= cd:
            a["sheet"]["condicoes"].remove(pegada)
            _soltar_contido(a, pegada.get("por", ""))
            return f"{a['name']} escapa de {quem['name']}: {max(atl, acr)} contra CD {cd} — livre."
        return f"{a['name']} tenta escapar de {quem['name']}: {max(atl, acr)} contra CD {cd} — continua agarrado."
    contra, _ = _pericia(quem, "atletismo", "forca")
    if max(atl, acr) > contra:
        a["sheet"]["condicoes"].remove(pegada)
        _soltar_contido(a, pegada.get("por", ""))
        return (f"{a['name']} escapa de {quem['name']}: {max(atl, acr)} contra Atletismo {contra} — livre.")
    return f"{a['name']} tenta escapar de {quem['name']}: {max(atl, acr)} contra Atletismo {contra} — continua agarrado."


def soltar_quem_agarrou(nome: str) -> list[str]:
    """Quem agarra saiu da zona ou caiu: solta todos que segurava."""
    linhas = []
    for ch in (memory.campaign.get("characters") or {}).values():
        conds = ((ch or {}).get("sheet") or {}).get("condicoes")
        if not isinstance(conds, list):
            continue
        ficam = [c for c in conds if not (isinstance(c, dict) and c.get("nome") == "Agarrado"
                                         and memory.char_key(c.get("por", "")) == memory.char_key(nome))]
        if len(ficam) != len(conds):
            ch["sheet"]["condicoes"] = ficam
            _soltar_contido(ch, nome)
            linhas.append(f"{ch.get('name')} fica livre de {nome}")
    return linhas


def empurrar(ator: str, alvo: str, modo: str) -> str:
    td = _td()
    a, b, erro = _validar_alvo(ator, alvo, "empurrar")
    if erro:
        return erro
    if modo not in ("derrubar", "afastar"):
        return "Erro: empurrar pede uma escolha: derrubar ou afastar."
    if modo == "afastar" and not td._zonas_ativas():
        return "Erro: sem zonas neste combate não há para onde afastar. Escolha derrubar."
    venceu, linha = _disputa(a, b)
    if not venceu:
        return f"{a['name']} tenta empurrar {b['name']}: {linha} — não sai do lugar."
    if modo == "derrubar":
        conds = b["sheet"].setdefault("condicoes", [])
        if not any(td._norm_txt(c.get("nome", "") if isinstance(c, dict) else str(c)) == "caido" for c in conds):
            conds.append({"nome": "Caído", "duracao": None})
        return f"{a['name']} derruba {b['name']}: {linha} — **CAÍDO**."
    zonas = td._zonas()
    aqui = td._zona_de(b["name"])
    i = zonas.index(aqui) if aqui in zonas else 0
    destino = zonas[i + 1] if i + 1 < len(zonas) else zonas[i - 1]
    memory.campaign["combat_state"].setdefault("posicoes", {})[memory.char_key(b["name"])] = destino
    soltos = soltar_quem_agarrou(b["name"])
    return (f"{a['name']} empurra {b['name']} de {aqui} para {destino}: {linha}."
            + (f" ({'; '.join(soltos)})" if soltos else ""))


# ---------------------------------------------------------------------------
# Preparar
# ---------------------------------------------------------------------------

def preparar(ator: str, alvo: str = "", modo: str = "") -> str:
    """
    Preparar (gasta a Ação): um ataque, ou uma magia ("magia:<nome>"). A magia
    preparada é conjurada AGORA — gasta a mana e prende a concentração — e
    solta como reação quando o gatilho vem; se a concentração cair antes, ela
    se perde (SRD).
    """
    a = _ch(ator)
    cs = memory.campaign["combat_state"]
    lista = [p for p in cs.get("preparadas") or [] if memory.char_key(p.get("ator", "")) != memory.char_key(ator)]
    b = _ch(alvo) if alvo else None
    if (modo or "").startswith("magia:"):
        return _preparar_magia(a, b, modo.split(":", 1)[1].strip(), lista, cs)
    lista.append({"ator": a["name"], "alvo": b["name"] if b else ""})
    cs["preparadas"] = lista
    gatilho = (f"quando {b['name']} for agir" if b
               else "contra o primeiro inimigo que agir ou chegar na sua zona")
    return (f"{a['name']} prepara um ataque {gatilho}, até o próximo turno dele "
            f"(usa a reação).")


def _preparar_magia(a: dict, b: dict | None, magia: str, lista: list, cs: dict) -> str:
    td = _td()
    from rpg import resolucao
    hab = next((h for h in a.get("habilidades") or [] if isinstance(h, dict)
                and td._norm_txt(h.get("nome", "")) == td._norm_txt(magia)), None)
    if not hab or not resolucao._magia_srd(hab):
        return f"Erro: {a['name']} não conhece a magia '{magia}'."
    if td._slot_da_habilidade(hab.get("nome", ""), hab, a) != "acao":
        return f"Erro: só se prepara magia de uma Ação; {hab['nome']} não é."
    s = a["sheet"]
    custo = int(hab.get("custo_mana", 0) or 0)
    if int(s.get("mana_atual", 0) or 0) < custo:
        return f"Erro: {a['name']} não tem mana para preparar {hab['nome']} ({custo})."
    s["mana_atual"] = int(s.get("mana_atual", 0) or 0) - custo
    linha_conc = td._start_concentration(a, hab["nome"])
    lista.append({"ator": a["name"], "alvo": b["name"] if b else "", "magia": hab["nome"]})
    cs["preparadas"] = lista
    gatilho = (f"quando {b['name']} for agir" if b
               else "contra o primeiro inimigo que agir ou chegar na sua zona")
    return (f"{a['name']} prepara {hab['nome']} ({custo} mana gastos agora), {gatilho}, até o próximo "
            f"turno dele (usa a reação; segura a magia na concentração).{linha_conc}")


def expirar_preparadas(nome: str) -> None:
    cs = memory.campaign.get("combat_state") or {}
    for p in cs.get("preparadas") or []:
        if p.get("magia") and memory.char_key(p.get("ator", "")) == memory.char_key(nome):
            quem = _ch(p["ator"])
            conc = ((quem or {}).get("sheet") or {}).get("concentracao") or {}
            if quem and _td()._norm_txt(conc.get("magia", "")) == _td()._norm_txt(p["magia"]):
                quem["sheet"]["concentracao"] = None
            _td()._log_combat_event("ready_lost", p["ator"], "", msg=f"{p['magia']} preparada de {p['ator']} se perde")
    if cs.get("preparadas"):
        cs["preparadas"] = [p for p in cs["preparadas"]
                            if memory.char_key(p.get("ator", "")) != memory.char_key(nome)]


def disparar_preparadas(npc_nome: str) -> list[str]:
    """
    O inimigo vai agir (ou acabou de chegar na zona): quem preparou ataque
    contra ele ataca agora, com a reação.
    """
    td = _td()
    cs = memory.campaign.get("combat_state") or {}
    npc = _ch(npc_nome)
    if not npc or not cs.get("preparadas"):
        return []
    linhas, ficam = [], []
    for p in cs["preparadas"]:
        quem = _ch(p.get("ator", ""))
        alvo_ok = (memory.char_key(p.get("alvo", "")) == memory.char_key(npc_nome)
                   or (not p.get("alvo") and _perto(p.get("ator", ""), npc_nome)))
        vivo = int(((npc.get("sheet") or {}).get("vida_atual", 0)) or 0) > 0
        if (not quem or not alvo_ok or not vivo or memory.luta_com_o_grupo(quem) == memory.luta_com_o_grupo(npc)
                or td._impedido_de_agir(quem) or not td._reaction_available(quem)
                or (quem.get("status") or "").lower() in td.OUT_OF_COMBAT_STATUSES):
            ficam.append(p)
            continue
        if p.get("magia"):
            conc = ((quem.get("sheet") or {}).get("concentracao") or {})
            if td._norm_txt(conc.get("magia", "")) != td._norm_txt(p["magia"]):
                linhas.append(f"{quem['name']} perdeu a concentração: {p['magia']} preparada se desfaz.")
                continue
            quem["sheet"]["concentracao"] = None       # solta a magia; a dela mesma começa ao conjurar
            td._consume_reaction(quem)
            saida = td.use_ability(quem["name"], p["magia"], npc["name"], end_turn=False,
                                   _skip_turn_check=True, _sem_custo=True)
            linhas.append(f"{quem['name']} solta {p['magia']} preparada:\n"
                          + saida.replace(td._BONUS_ACTION_HINT, "").replace(
                              "\n   Ação bônus disponível — próxima habilidade/ataque neste turno.", ""))
            continue
        arma = ((quem.get("sheet") or {}).get("equipamentos") or {}).get("arma_principal") or "ataque desarmado"
        golpe = td.attack_roll(quem["name"], npc["name"], arma, 6, end_turn=False, _skip_turn_check=True)
        if golpe.startswith("Erro"):
            ficam.append(p)
            continue
        td._consume_reaction(quem)
        linhas.append(f"{quem['name']} dispara o ataque preparado:\n" + golpe.replace(td._BONUS_ACTION_HINT, ""))
    cs["preparadas"] = ficam
    return linhas
