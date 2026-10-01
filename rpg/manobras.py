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


def escapar(ator: str) -> str:
    a = _ch(ator)
    pegada = next((c for c in (a.get("sheet") or {}).get("condicoes") or []
                   if isinstance(c, dict) and c.get("nome") == "Agarrado"), None)
    if not pegada:
        return f"Erro: {a['name']} não está agarrado."
    quem = _ch(pegada.get("por", ""))
    if not quem:
        a["sheet"]["condicoes"].remove(pegada)
        return f"{a['name']} se solta."
    atl, _ = _pericia(a, "atletismo", "forca")
    acr, _ = _pericia(a, "acrobacia", "destreza")
    contra, _ = _pericia(quem, "atletismo", "forca")
    if max(atl, acr) > contra:
        a["sheet"]["condicoes"].remove(pegada)
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

def preparar(ator: str, alvo: str = "") -> str:
    a = _ch(ator)
    cs = memory.campaign["combat_state"]
    lista = [p for p in cs.get("preparadas") or [] if memory.char_key(p.get("ator", "")) != memory.char_key(ator)]
    b = _ch(alvo) if alvo else None
    lista.append({"ator": a["name"], "alvo": b["name"] if b else ""})
    cs["preparadas"] = lista
    gatilho = (f"quando {b['name']} for agir" if b
               else "contra o primeiro inimigo que agir ou chegar na sua zona")
    return (f"{a['name']} prepara um ataque {gatilho}, até o próximo turno dele "
            f"(usa a reação).")


def expirar_preparadas(nome: str) -> None:
    cs = memory.campaign.get("combat_state") or {}
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
        arma = ((quem.get("sheet") or {}).get("equipamentos") or {}).get("arma_principal") or "ataque desarmado"
        golpe = td.attack_roll(quem["name"], npc["name"], arma, 6, end_turn=False, _skip_turn_check=True)
        if golpe.startswith("Erro"):
            ficam.append(p)
            continue
        td._consume_reaction(quem)
        linhas.append(f"{quem['name']} dispara o ataque preparado:\n" + golpe.replace(td._BONUS_ACTION_HINT, ""))
    cs["preparadas"] = ficam
    return linhas
