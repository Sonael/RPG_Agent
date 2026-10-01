"""
reacoes.py
As reações que acontecem no turno do inimigo: Escudo Arcano, Esquiva
Sobrenatural, Defletir Projéteis, Repreensão Infernal, Contramágica,
Retaliação, Bandeira de Aviso, Eu Ilusório.

POR QUE EXISTE
──────────────
O turno do inimigo se resolve sozinho, sem parar para perguntar nada ao
jogador. Por isso só o ataque de oportunidade existia como reação: Escudo
Arcano e Contramágica apareciam na lista como "o Mestre decide", e a Esquiva
Sobrenatural do ladino nunca reduziu um ponto de dano.

Pausar o turno do inimigo a cada golpe para perguntar "quer usar o Escudo?"
travaria a luta numa fila de perguntas. Aqui o motor usa a reação sozinho, no
momento em que ela faz diferença — o Escudo só quando os +5 transformam o
acerto em erro, a Contramágica só contra magia de inimigo ao alcance — e o
jogador desliga na tela a que não quiser que o motor use.

Cada reação gasta a reação da rodada (e a mana ou o uso, quando tem).
"""
from __future__ import annotations

import random

from rpg import memory

# chave → como reconhecer na ficha e o que o cartão diz.
#   srd:   nome da magia no SRD (a ficha pode ter o nome em português)
#   nomes: nomes normalizados da característica
REACOES: dict[str, dict] = {
    "escudo arcano": {
        "nome": "Escudo Arcano", "srd": "Shield",
        "texto": "Reação: quando um ataque acertaria você e os +5 de CA o fariam errar, o motor conjura "
                 "sozinho (+5 de CA até o seu próximo turno).",
    },
    "repreensao infernal": {
        "nome": "Repreensão Infernal", "srd": "Hellish Rebuke",
        "texto": "Reação: quando uma criatura fere você, o motor conjura sozinho: 2d10 de fogo nela "
                 "(DES, metade se passar).",
    },
    "contramagica": {
        "nome": "Contramágica", "srd": "Counterspell",
        "texto": "Reação: quando um inimigo ao alcance conjura uma magia, o motor conjura sozinho; até o "
                 "3º círculo ela é anulada, acima disso é um teste de conjuração contra 10 + círculo.",
    },
    "esquiva sobrenatural": {
        "nome": "Esquiva Sobrenatural",
        "nomes": ("esquiva sobrenatural", "uncanny dodge", "esquiva incrivelmente baixa"),
        "texto": "Reação: quando um ataque acerta você, o motor corta o dano pela metade sozinho.",
    },
    "defletir projeteis": {
        "nome": "Defletir Projéteis",
        "nomes": ("defletir projeteis", "desviar projeteis", "deflect missiles"),
        "texto": "Reação: quando um ataque à distância com arma acerta você, o motor reduz o dano em "
                 "1d10 + DES + nível de monge sozinho.",
    },
    "retaliacao": {
        "nome": "Retaliação", "nomes": ("retaliacao", "retaliation"),
        "texto": "Reação: quando uma criatura na sua zona fere você, o motor faz um ataque corpo a corpo "
                 "contra ela sozinho.",
    },
    "bandeira de aviso": {
        "nome": "Bandeira de Aviso", "nomes": ("bandeira de aviso", "warding flare", "labareda protetora"),
        "texto": "Reação: no primeiro ataque contra você em cada rodada, o motor impõe desvantagem sozinho "
                 "(usos = mod. de SAB por descanso longo).",
    },
    "eu ilusorio": {
        "nome": "Eu Ilusório", "nomes": ("eu ilusorio", "auto ilusao", "illusory self"),
        "texto": "Reação: quando um ataque acertaria você, uma cópia ilusória o recebe e ele erra "
                 "(uma vez por descanso curto).",
    },
    # Mestre de Batalha (rpg/superioridade.py): gastam um Dado de Superioridade.
    "contra ataque": {"nome": "Contra-Ataque", "manobra": "Contra-Ataque",
                      "texto": "Reação: quando um inimigo erra você corpo a corpo, o motor ataca de volta (+dado de superioridade)."},
    "aparar": {"nome": "Aparar", "manobra": "Aparar",
               "texto": "Reação: quando um ataque corpo a corpo acerta você, o motor reduz o dano em dado de superioridade + DES."},
    # Estilo de Combate Proteção: com escudo, desvantagem no ataque contra o aliado ao lado.
    "protecao": {"nome": "Proteção (estilo)", "estilo": "Proteção",
                 "texto": "Reação, com escudo: o primeiro ataque contra um aliado na sua zona em cada rodada tem desvantagem."},
    # Não são reações, mas reagem sozinhos e podem ser desligados na mesma lista.
    "indomavel": {"nome": "Indomável", "nomes": ("indomavel", "indomitable"), "recurso": True,
                  "texto": ""},
    "alma do diamante": {"nome": "Alma do Diamante", "nomes": ("alma do diamante", "diamond soul"),
                         "recurso": True, "texto": ""},
}

_POR_SRD = {cfg["srd"]: chave for chave, cfg in REACOES.items() if cfg.get("srd")}


def _norm(s: str) -> str:
    from rpg import resolucao
    return resolucao.norm(s)


def chave_da_magia(nome_srd: str) -> str:
    return _POR_SRD.get(nome_srd or "", "")


def chave_do_nome(nome: str) -> str:
    """A reação (característica) com este nome, ou ''."""
    from rpg import resolucao
    for parte in resolucao._partes_do_nome(nome):
        for chave, cfg in REACOES.items():
            if parte in (cfg.get("nomes") or ()):
                return chave
    return ""


def habilidade_da_reacao(char: dict, chave: str) -> dict | None:
    """A habilidade da ficha que dá esta reação, ou None."""
    from rpg import resolucao, tools_dnd as td
    cfg = REACOES[chave]
    if cfg.get("manobra"):
        from rpg import superioridade
        if superioridade.tem(char) and cfg["manobra"] in superioridade.conhecidas(char):
            return {"nome": cfg["manobra"]}
        return None
    if cfg.get("estilo"):
        eq = ((char or {}).get("sheet") or {}).get("equipamentos") or {}
        if td._get_feature_choice(char, "Estilo de Combate") == cfg["estilo"] and eq.get("escudo"):
            return {"nome": cfg["nome"]}
        return None
    for h in (char or {}).get("habilidades") or []:
        if not isinstance(h, dict):
            continue
        if cfg.get("srd"):
            m = resolucao._magia_srd(h)
            if m and m.get("nome_srd") == cfg["srd"]:
                return h
        elif chave_do_nome(h.get("nome", "")) == chave:
            return h
    return None


def disponiveis(char: dict) -> list[dict]:
    """As reações (e recursos que reagem) da ficha, com o estado ligado/desligado."""
    from rpg import tools_dnd as td
    saida = []
    for chave, cfg in REACOES.items():
        if habilidade_da_reacao(char, chave):
            saida.append({"chave": chave, "nome": cfg["nome"],
                          "ligada": td.reacao_automatica(char, chave)})
    return saida


def alternar(nome: str, chave: str, ligada: bool) -> str:
    ch = memory.campaign.get("characters", {}).get(memory.char_key(nome or ""))
    if not ch:
        return f"Erro: '{nome}' não encontrado."
    if chave not in REACOES:
        return f"Erro: reação desconhecida: {chave}."
    s = ch.setdefault("sheet", {})
    lista = [x for x in (s.get("reacoes_desligadas") or []) if _norm(x) != _norm(chave)]
    if not ligada:
        lista.append(chave)
    s["reacoes_desligadas"] = lista
    memory.save_campaign()
    return (f"{REACOES[chave]['nome']} de {ch['name']}: "
            + ("o motor usa sozinho." if ligada else "desligada — o motor não usa."))


# ---------------------------------------------------------------------------
# Quem pode reagir agora
# ---------------------------------------------------------------------------

def _pode_reagir(char: dict, chave: str) -> dict | None:
    """A habilidade, se `char` pode usar esta reação agora; senão None."""
    from rpg import tools_dnd as td
    if not char or not char.get("sheet"):
        return None
    if (char.get("status") or "").lower() in td.OUT_OF_COMBAT_STATUSES:
        return None
    if int(char["sheet"].get("vida_atual", 0) or 0) <= 0:
        return None
    if td._impedido_de_agir(char):
        return None
    if not td.reacao_automatica(char, chave):
        return None
    if not td._reaction_available(char):
        return None
    return habilidade_da_reacao(char, chave)


def _custo_de_mana(hab: dict) -> int:
    from rpg import resolucao, tools_dnd as td
    custo = int(hab.get("custo_mana", 0) or 0)
    if custo:
        return custo
    m = resolucao._magia_srd(hab) or {}
    return td.SPELL_MANA_COST.get(int(m.get("nivel", 1) or 1), 2)


def _pagar_mana(char: dict, hab: dict) -> bool:
    s = char["sheet"]
    custo = _custo_de_mana(hab)
    if int(s.get("mana_atual", 0) or 0) < custo:
        return False
    s["mana_atual"] = int(s.get("mana_atual", 0) or 0) - custo
    return True


def _registrar(char: dict, nome: str, alvo: str, msg: str) -> None:
    from rpg import tools_dnd as td
    td._consume_reaction(char)
    td._log_combat_event("reaction", char.get("name", ""), alvo, msg=msg, reacao=nome)


# ---------------------------------------------------------------------------
# Ganchos chamados pelo motor
# ---------------------------------------------------------------------------

def antes_do_ataque(atacante: dict, alvo: dict, ja_tem_desvantagem: bool) -> tuple[bool, list[str]]:
    """Bandeira de Aviso ou o estilo Proteção: desvantagem no ataque. (desvantagem?, linhas)"""
    from rpg import tools_dnd as td
    if ja_tem_desvantagem or memory.luta_com_o_grupo(atacante) == memory.luta_com_o_grupo(alvo):
        return False, []
    cs = memory.campaign.get("combat_state") or {}
    for nm in cs.get("initiative_order") or []:
        guarda = memory.campaign["characters"].get(memory.char_key(nm))
        if (not guarda or guarda is alvo or memory.luta_com_o_grupo(guarda) != memory.luta_com_o_grupo(alvo)):
            continue
        d = td._distancia(guarda.get("name", ""), alvo.get("name", ""))
        if d not in (None, 0) or not _pode_reagir(guarda, "protecao"):
            continue
        msg = (f"{guarda['name']} ergue o escudo (Proteção): o ataque de {atacante['name']} contra "
               f"{alvo['name']} tem desvantagem.")
        _registrar(guarda, "Proteção", atacante.get("name", ""), msg)
        return True, [msg]
    hab = _pode_reagir(alvo, "bandeira de aviso")
    if not hab or (td.usos_restantes(alvo, "Bandeira de Aviso") or 0) <= 0:
        return False, []
    td._gastar_uso(alvo, "Bandeira de Aviso")
    msg = f"{alvo['name']} usa Bandeira de Aviso: o ataque de {atacante['name']} tem desvantagem."
    _registrar(alvo, "Bandeira de Aviso", atacante.get("name", ""), msg)
    return True, [msg]


def ao_ser_atingido(atacante: dict, alvo: dict, total: int, ca: int, critico: bool) -> tuple[bool, list[str]]:
    """
    O ataque vai acertar: Escudo Arcano (só se os +5 o fazem errar) ou Eu
    Ilusório. (vira erro?, linhas)
    """
    from rpg import tools_dnd as td
    if memory.luta_com_o_grupo(atacante) == memory.luta_com_o_grupo(alvo):
        return False, []
    hab = _pode_reagir(alvo, "escudo arcano")
    if hab and not critico and total < ca + 5 and _pagar_mana(alvo, hab):
        td.dar_efeito_de_combate(alvo, {"nome": "Escudo Arcano", "ca": 5,
                                        "ate_turno_de": memory.char_key(alvo.get("name", ""))})
        msg = (f"{alvo['name']} conjura Escudo Arcano ({_custo_de_mana(hab)} mana): CA {ca} → {ca + 5} "
               f"até o próximo turno dele — o ataque ({total}) erra.")
        _registrar(alvo, "Escudo Arcano", atacante.get("name", ""), msg)
        return True, [msg]
    hab = _pode_reagir(alvo, "eu ilusorio")
    if hab and (td.usos_restantes(alvo, "Eu Ilusório") or 0) > 0:
        td._gastar_uso(alvo, "Eu Ilusório")
        msg = f"{alvo['name']} usa Eu Ilusório: uma cópia ilusória recebe o golpe e o ataque erra."
        _registrar(alvo, "Eu Ilusório", atacante.get("name", ""), msg)
        return True, [msg]
    return False, []


def reduzir_dano(atacante: dict, alvo: dict, componentes: list, a_distancia: bool,
                 com_arma: bool) -> tuple[list, list[str]]:
    """Defletir Projéteis (à distância) ou Esquiva Sobrenatural. (componentes, linhas)"""
    from rpg import tools_dnd as td
    if memory.luta_com_o_grupo(atacante) == memory.luta_com_o_grupo(alvo):
        return componentes, []
    total = sum(max(0, int(v or 0)) for v, _ in componentes)
    if total <= 0:
        return componentes, []
    hab = _pode_reagir(alvo, "defletir projeteis") if (a_distancia and com_arma) else None
    if hab:
        s = alvo["sheet"]
        d10 = random.randint(1, 10)
        reducao = d10 + td._modifier(int(s.get("destreza", 10) or 10)) + int(s.get("nivel", 1) or 1)
        resto, novos = reducao, []
        for v, t in componentes:
            corte = min(max(0, int(v or 0)), resto)
            resto -= corte
            novos.append((int(v or 0) - corte, t))
        msg = (f"{alvo['name']} usa Defletir Projéteis: reduz {min(reducao, total)} do dano "
               f"(1d10={d10} + DES + nível = {reducao}).")
        _registrar(alvo, "Defletir Projéteis", atacante.get("name", ""), msg)
        return novos, [msg]
    if not a_distancia and _pode_reagir(alvo, "aparar"):
        from rpg import superioridade
        if superioridade.restantes(alvo) > 0:
            superioridade.gastar(alvo)
            d = random.randint(1, superioridade.dado(alvo))
            reducao = d + td._modifier(int(alvo["sheet"].get("destreza", 10) or 10))
            resto, novos = max(0, reducao), []
            for v, t in componentes:
                corte = min(max(0, int(v or 0)), resto)
                resto -= corte
                novos.append((int(v or 0) - corte, t))
            msg = (f"{alvo['name']} apara o golpe: reduz {min(max(0, reducao), total)} do dano "
                   f"(d{superioridade.dado(alvo)}={d} + DES).")
            _registrar(alvo, "Aparar", atacante.get("name", ""), msg)
            return novos, [msg]
    hab = _pode_reagir(alvo, "esquiva sobrenatural")
    if hab:
        novos = [(int(v or 0) // 2, t) for v, t in componentes]
        msg = (f"{alvo['name']} usa Esquiva Sobrenatural: o dano cai pela metade "
               f"({total} → {sum(v for v, _ in novos)}).")
        _registrar(alvo, "Esquiva Sobrenatural", atacante.get("name", ""), msg)
        return novos, [msg]
    return componentes, []


def depois_do_dano(atacante: dict, alvo: dict, dano: int) -> list[str]:
    """Repreensão Infernal e Retaliação, quando o alvo ferido ainda está de pé."""
    from rpg import resolucao, tools_dnd as td
    if dano <= 0 or memory.luta_com_o_grupo(atacante) == memory.luta_com_o_grupo(alvo):
        return []
    if int((atacante.get("sheet") or {}).get("vida_atual", 0) or 0) <= 0:
        return []
    linhas = []
    hab = _pode_reagir(alvo, "repreensao infernal")
    if hab and _pagar_mana(alvo, hab):
        cd = resolucao._cd(alvo)
        rolls = [random.randint(1, 10) for _ in range(2)]
        dano_fogo = sum(rolls)
        passou, linha = td._rolar_salvaguarda(atacante, "destreza", cd)
        if passou:
            dano_fogo //= 2
        res = td._apply_damage(atacante, dano_fogo, "fire", source_name=alvo["name"], arma_magica=True)
        msg = (f"{alvo['name']} conjura Repreensão Infernal em {atacante['name']}: 2d10 "
               f"[{' + '.join(map(str, rolls))}] — {linha} — {res['dano']} de fogo "
               f"({res['hp_antes']} → {res['hp_depois']}).")
        _registrar(alvo, "Repreensão Infernal", atacante.get("name", ""), msg)
        linhas.append(msg + td._fmt_notas(res["notas"]).replace("\n", " "))
        if res["hp_depois"] == 0 and res["hp_antes"] > 0:
            linhas.append(td._mark_at_zero_hp(atacante, alvo["name"]).strip())
        return linhas
    hab = _pode_reagir(alvo, "retaliacao")
    if hab and not td._distancia(alvo.get("name", ""), atacante.get("name", "")):
        td._consume_reaction(alvo)
        arma = ((alvo["sheet"].get("equipamentos") or {}).get("arma_principal")
                or td._melee_weapon_of(alvo) or "ataque desarmado")
        golpe = td.attack_roll(alvo["name"], atacante["name"], arma, 6,
                               end_turn=False, _skip_turn_check=True)
        golpe = golpe.replace(td._BONUS_ACTION_HINT, "")
        td._log_combat_event("reaction", alvo["name"], atacante["name"],
                             msg=f"{alvo['name']} usa Retaliação contra {atacante['name']}",
                             reacao="Retaliação")
        linhas.append(f"{alvo['name']} usa Retaliação:\n" + golpe)
    return linhas


def ao_errar(atacante: dict, alvo: dict, a_distancia: bool) -> list[str]:
    """Contra-Ataque: quem errou o Mestre de Batalha corpo a corpo leva o troco."""
    from rpg import superioridade, tools_dnd as td
    if a_distancia or memory.luta_com_o_grupo(atacante) == memory.luta_com_o_grupo(alvo):
        return []
    if int((atacante.get("sheet") or {}).get("vida_atual", 0) or 0) <= 0:
        return []
    if not _pode_reagir(alvo, "contra ataque") or superioridade.restantes(alvo) <= 0:
        return []
    if td._distancia(alvo.get("name", ""), atacante.get("name", "")):
        return []
    superioridade.gastar(alvo)
    td._consume_reaction(alvo)
    face = superioridade.dado(alvo)
    td.dar_efeito_de_combate(alvo, {"nome": "Contra-Ataque", "golpe_dado": f"1d{face}",
                                    "golpe_tipo_da_arma": True, "golpe_so_corpo": True,
                                    "ate_fim_turno_de": memory.char_key(atacante.get("name", ""))})
    arma = ((alvo["sheet"].get("equipamentos") or {}).get("arma_principal")
            or td._melee_weapon_of(alvo) or "ataque desarmado")
    golpe = td.attack_roll(alvo["name"], atacante["name"], arma, 6, end_turn=False, _skip_turn_check=True)
    # Errou: o dado já foi; o efeito armado não fica para depois.
    alvo["sheet"]["efeitos"] = [e for e in alvo["sheet"].get("efeitos") or [] if e.get("nome") != "Contra-Ataque"]
    td._log_combat_event("reaction", alvo["name"], atacante["name"],
                         msg=f"{alvo['name']} usa Contra-Ataque contra {atacante['name']}", reacao="Contra-Ataque")
    return [f"{alvo['name']} usa Contra-Ataque:\n" + golpe.replace(td._BONUS_ACTION_HINT, "")]


def contramagica(conjurador: dict, hab: dict) -> str:
    """
    Alguém do outro lado, ao alcance, anula a magia? Devolve a linha do que
    aconteceu ('' quando ninguém reage ou a magia passa).
    """
    from rpg import resolucao, tools_dnd as td
    cs = memory.campaign.get("combat_state") or {}
    if not cs.get("is_active"):
        return ""
    m = resolucao._magia_srd(hab)
    if not m or m.get("nome_srd") == "Counterspell":
        return ""
    # Truque não vale um espaço de 3º círculo: o motor deixa passar.
    if int(m.get("nivel", 0) or 0) < 1:
        return ""
    lado = memory.luta_com_o_grupo(conjurador)
    for nm in cs.get("initiative_order") or []:
        ch = memory.campaign["characters"].get(memory.char_key(nm))
        if not ch or ch is conjurador or memory.luta_com_o_grupo(ch) == lado:
            continue
        dist = td._distancia(ch.get("name", ""), conjurador.get("name", ""))
        if dist is not None and dist > 2:
            continue
        cm = _pode_reagir(ch, "contramagica")
        if not cm or not _pagar_mana(ch, cm):
            continue
        nivel = int(m.get("nivel", 0) or 0)
        if nivel <= 3:
            msg = (f"{ch['name']} conjura Contramágica ({_custo_de_mana(cm)} mana): "
                   f"{m.get('nome', hab.get('nome'))} de {conjurador['name']} é anulada.")
            _registrar(ch, "Contramágica", conjurador.get("name", ""), msg)
            return msg
        s = ch["sheet"]
        attr = td._atributo_de_conjuracao(s) or "inteligencia"
        d20 = random.randint(1, 20)
        total = d20 + td._modifier(int(s.get(attr, 10) or 10))
        cd = 10 + nivel
        passou = total >= cd
        msg = (f"{ch['name']} conjura Contramágica ({_custo_de_mana(cm)} mana) contra "
               f"{m.get('nome', hab.get('nome'))} ({nivel}º círculo): teste {d20} + mod = {total} vs CD {cd} — "
               + ("ANULADA." if passou else "a magia passa."))
        _registrar(ch, "Contramágica", conjurador.get("name", ""), msg)
        return msg if passou else ("(" + msg + ")")
    return ""
