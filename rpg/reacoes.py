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
travaria a luta numa fila de perguntas. Por padrão o motor usa a reação
sozinho, no momento em que ela faz diferença — o Escudo só quando os +5
transformam o acerto em erro, a Contramágica só contra magia de inimigo ao
alcance. Cada reação tem três modos na tela: "auto" (o motor usa), "perguntar"
e "desligada".

PERGUNTAR
─────────
No modo "perguntar", quando a reação faria diferença, o turno do inimigo para
e o jogador decide. O motor não tem como suspender uma função no meio, então
faz o seguinte: guarda a campanha e o estado do sorteio antes do turno; quando
chega a pergunta, desfaz tudo e grava a pergunta pendente; com a resposta, roda
o turno de novo do mesmo ponto, com o mesmo sorteio — os mesmos dados caem, a
mesma pergunta chega, e agora ela tem resposta. Uma segunda pergunta no mesmo
turno funciona igual, com as duas respostas.

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
    # Subclasses (rpg/subclasses.py).
    "golpe magico": {"nome": "Golpe Mágico", "nomes": ("golpe magico",),
                     "texto": "Reação: depois de acertar com arma, o motor conjura o seu melhor truque de dano no alvo."},
    "marca da vinganca": {"nome": "Marca da Vingança", "nomes": ("marca da vinganca", "soul of vengeance"),
                          "texto": "Reação: quando um inimigo ataca um aliado na sua zona, o motor ataca o inimigo."},
    "oportunista": {"nome": "Oportunista", "nomes": ("oportunista", "opportunist"),
                    "texto": "Reação: quando um aliado acerta um inimigo na sua zona, o motor ataca esse inimigo."},
    "recuperacao bestial": {"nome": "Recuperação Bestial", "nomes": ("recuperacao bestial",),
                            "texto": "Reação: o dano destinado à sua fera ou invocação vem para você."},
    "mudanca imediata": {"nome": "Mudança Imediata", "nomes": ("mudanca imediata",),
                         "texto": "Reação: ao levar um golpe na forma normal, o motor gasta a Forma Selvagem e vira a "
                                  "fera de mais vida antes do dano."},
    "resistencia magica projetada": {"nome": "Resistência Mágica Projetada",
                                     "nomes": ("resistencia magica projetada",),
                                     "texto": "Reação: um aliado perto faz a salvaguarda com o seu bônus, quando o seu é maior."},
    "refugio feerico": {"nome": "Refúgio Feérico", "nomes": ("refugio feerico", "misty escape"),
                        "texto": "Reação: ao ser ferido, o motor o leva para a zona vizinha e o deixa Invisível até o "
                                 "seu próximo turno."},
    "vinganca do grande antigo": {"nome": "Vingança do Grande Antigo", "nomes": ("vinganca do grande antigo",),
                                  "texto": "Reação: quando alguém ataca você, ele leva 1 + CAR de dano psíquico."},
    "lampejos": {"nome": "Lampejos de Adivinhação", "nomes": ("lampejos de adivinhacao", "portent"),
                 "texto": "O motor guarda os d20 do descanso longo e troca o dado de um ataque inimigo que "
                          "acertaria um aliado (o menor) ou de um ataque ou salvaguarda do grupo que falharia "
                          "(o maior), quando a troca vira o resultado."},
    # Não são reações, mas reagem sozinhos e podem ser desligados na mesma lista.
    "indomavel": {"nome": "Indomável", "nomes": ("indomavel", "indomitable"), "recurso": True,
                  "texto": ""},
    "alma do diamante": {"nome": "Alma do Diamante", "nomes": ("alma do diamante", "diamond soul"),
                         "recurso": True, "texto": ""},
}

_POR_SRD = {cfg["srd"]: chave for chave, cfg in REACOES.items() if cfg.get("srd")}

# Reações que podem perguntar: as que são escolha de verdade. Os Lampejos e os
# recursos que refazem salvaguarda continuam no liga/desliga.
PODEM_PERGUNTAR = frozenset(k for k, cfg in REACOES.items() if not cfg.get("recurso") and k != "lampejos")


class PerguntaDeReacao(BaseException):
    """
    O turno do inimigo para aqui: o jogador decide a reação. BaseException de
    propósito — um `except Exception` no caminho não pode engolir a pausa.
    """
    def __init__(self, quem: str, chave: str, texto: str):
        super().__init__(texto)
        self.quem, self.chave, self.texto = quem, chave, texto


# Durante o turno do inimigo (tools_dnd._turno_com_perguntas): as respostas já
# dadas, em ordem. None fora dele — aí a reação em "perguntar" age como "auto".
_respostas: list | None = None
_indice = 0


def modo_da_reacao(char: dict, chave: str) -> str:
    """'auto' | 'perguntar' | 'desligada'."""
    s = (char or {}).get("sheet") or {}
    if _norm(chave) in {_norm(x) for x in s.get("reacoes_desligadas") or []}:
        return "desligada"
    if _norm(chave) in {_norm(x) for x in s.get("reacoes_perguntar") or []}:
        return "perguntar"
    return "auto"


def alguem_pergunta() -> bool:
    """Algum personagem do grupo tem reação em 'perguntar'? Sem isso, o turno corre sem guardar nada."""
    return any(isinstance(c, dict) and ((c.get("sheet") or {}).get("reacoes_perguntar"))
               and memory.is_party_member(c)
               for c in (memory.campaign.get("characters") or {}).values())


def _confirmar(char: dict, chave: str, texto: str) -> bool:
    """
    O jogador quer esta reação agora? Sempre sim no modo "auto" e fora do
    turno do inimigo. No "perguntar", a resposta já dada ou a pausa.
    """
    global _indice
    if (_respostas is None or not memory.is_party_member(char)
            or modo_da_reacao(char, chave) != "perguntar"):
        return True
    if _indice < len(_respostas):
        resposta = _respostas[_indice]
        _indice += 1
        return bool(resposta)
    raise PerguntaDeReacao(char.get("name", ""), chave, texto)


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
    """As reações (e recursos que reagem) da ficha, com o modo (auto, perguntar, desligada)."""
    from rpg import tools_dnd as td
    saida = []
    for chave, cfg in REACOES.items():
        if habilidade_da_reacao(char, chave):
            saida.append({"chave": chave, "nome": cfg["nome"],
                          "ligada": td.reacao_automatica(char, chave),
                          "modo": modo_da_reacao(char, chave),
                          "pode_perguntar": chave in PODEM_PERGUNTAR})
    return saida


def alternar(nome: str, chave: str, ligada: bool, modo: str = "") -> str:
    """
    Muda o modo da reação. `modo` ("auto", "perguntar", "desligada") manda;
    sem ele, `ligada` escolhe entre "auto" e "desligada" (a tela antiga).
    """
    ch = memory.campaign.get("characters", {}).get(memory.char_key(nome or ""))
    if not ch:
        return f"Erro: '{nome}' não encontrado."
    if chave not in REACOES:
        return f"Erro: reação desconhecida: {chave}."
    modo = (modo or ("auto" if ligada else "desligada")).strip().lower()
    if modo not in ("auto", "perguntar", "desligada"):
        return f"Erro: modo desconhecido: {modo}. Use auto, perguntar ou desligada."
    if modo == "perguntar" and chave not in PODEM_PERGUNTAR:
        return f"Erro: {REACOES[chave]['nome']} não pergunta: só liga ou desliga."
    s = ch.setdefault("sheet", {})
    desligadas = [x for x in (s.get("reacoes_desligadas") or []) if _norm(x) != _norm(chave)]
    perguntar = [x for x in (s.get("reacoes_perguntar") or []) if _norm(x) != _norm(chave)]
    if modo == "desligada":
        desligadas.append(chave)
    elif modo == "perguntar":
        perguntar.append(chave)
    s["reacoes_desligadas"] = desligadas
    s["reacoes_perguntar"] = perguntar
    memory.save_campaign()
    return (f"{REACOES[chave]['nome']} de {ch['name']}: "
            + {"auto": "o motor usa sozinho.",
               "perguntar": "o turno do inimigo para e pergunta quando ela faria diferença.",
               "desligada": "desligada — o motor não usa."}[modo])


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
    if chave != "lampejos" and not td._reaction_available(char):
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
        if not _confirmar(guarda, "protecao", f"{atacante['name']} vai atacar {alvo['name']}. {guarda['name']} "
                                              f"ergue o escudo (Proteção) e impõe desvantagem?"):
            continue
        msg = (f"{guarda['name']} ergue o escudo (Proteção): o ataque de {atacante['name']} contra "
               f"{alvo['name']} tem desvantagem.")
        _registrar(guarda, "Proteção", atacante.get("name", ""), msg)
        return True, [msg]
    hab = _pode_reagir(alvo, "bandeira de aviso")
    if not hab or (td.usos_restantes(alvo, "Bandeira de Aviso") or 0) <= 0:
        return False, []
    if not _confirmar(alvo, "bandeira de aviso", f"{atacante['name']} vai atacar {alvo['name']}. Usar Bandeira "
                                                 f"de Aviso (desvantagem no ataque, gasta um uso)?"):
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
    if (hab and not critico and total < ca + 5
            and int(alvo["sheet"].get("mana_atual", 0) or 0) >= _custo_de_mana(hab)
            and _confirmar(alvo, "escudo arcano",
                           f"{atacante['name']} acerta {alvo['name']} ({total} contra CA {ca}). Conjurar Escudo "
                           f"Arcano ({_custo_de_mana(hab)} mana)? Com +5 de CA ({ca + 5}) o ataque erra.")
            and _pagar_mana(alvo, hab)):
        td.dar_efeito_de_combate(alvo, {"nome": "Escudo Arcano", "ca": 5,
                                        "ate_turno_de": memory.char_key(alvo.get("name", ""))})
        msg = (f"{alvo['name']} conjura Escudo Arcano ({_custo_de_mana(hab)} mana): CA {ca} → {ca + 5} "
               f"até o próximo turno dele — o ataque ({total}) erra.")
        _registrar(alvo, "Escudo Arcano", atacante.get("name", ""), msg)
        return True, [msg]
    hab = _pode_reagir(alvo, "eu ilusorio")
    if (hab and (td.usos_restantes(alvo, "Eu Ilusório") or 0) > 0
            and _confirmar(alvo, "eu ilusorio", f"{atacante['name']} acerta {alvo['name']}. Usar Eu Ilusório "
                                                f"(o ataque erra; uma vez por descanso curto)?")):
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
    # Recuperação Bestial: o dono da fera (ou invocação) leva o golpe por ela.
    inv = alvo.get("invocacao") if isinstance(alvo.get("invocacao"), dict) else None
    dono = memory.campaign["characters"].get(inv.get("por", "")) if inv else None
    if (dono and _pode_reagir(dono, "recuperacao bestial")
            and _confirmar(dono, "recuperacao bestial", f"{atacante['name']} acerta {alvo['name']} ({total} de "
                                                         f"dano). {dono['name']} leva o golpe no lugar dela?")):
        res = td._apply_damage(dono, total, componentes[0][1] if componentes else "",
                               source_name=atacante.get("name", ""))
        msg = (f"{dono['name']} se põe na frente de {alvo['name']} (Recuperação Bestial) e leva {res['dano']} "
               f"({res['hp_antes']} → {res['hp_depois']}).")
        _registrar(dono, "Recuperação Bestial", atacante.get("name", ""), msg)
        if res["hp_depois"] == 0 and res["hp_antes"] > 0:
            msg += td._mark_at_zero_hp(dono, atacante.get("name", ""))
        return [(0, t) for _, t in componentes], [msg]
    # Mudança Imediata: o druida vira fera antes do golpe.
    if (not (alvo.get("sheet") or {}).get("_forma_selvagem") and _pode_reagir(alvo, "mudanca imediata")
            and (td.usos_restantes(alvo, "Forma Selvagem") or 0) > 0):
        from rpg import criaturas, resolucao
        formas = criaturas.formas_permitidas(int(alvo["sheet"].get("nivel", 1) or 1),
                                             resolucao._circulo_da_lua(alvo))
        melhor = max(formas, key=lambda k: criaturas.FICHAS[k]["pv"]) if formas else ""
        if formas and _confirmar(alvo, "mudanca imediata",
                                 f"{atacante['name']} acerta {alvo['name']} ({total} de dano). Virar "
                                 f"{criaturas.FICHAS[melhor]['nome']} antes do dano (Mudança Imediata, gasta "
                                 f"uma Forma Selvagem)?"):
            td._gastar_uso(alvo, "Forma Selvagem")
            linha = criaturas.transformar(alvo, melhor)
            _registrar(alvo, "Mudança Imediata", atacante.get("name", ""), linha)
            return componentes, [f"Mudança Imediata: {linha}"]
    hab = _pode_reagir(alvo, "defletir projeteis") if (a_distancia and com_arma) else None
    if hab and _confirmar(alvo, "defletir projeteis", f"{atacante['name']} acerta {alvo['name']} à distância "
                                                      f"({total} de dano). Usar Defletir Projéteis?"):
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
        if superioridade.restantes(alvo) > 0 and _confirmar(
                alvo, "aparar", f"{atacante['name']} acerta {alvo['name']} ({total} de dano). Aparar (gasta um "
                                f"dado de superioridade)?"):
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
    if hab and _confirmar(alvo, "esquiva sobrenatural", f"{atacante['name']} acerta {alvo['name']} ({total} de "
                                                        f"dano). Usar Esquiva Sobrenatural (metade do dano)?"):
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
    if (_pode_reagir(alvo, "refugio feerico") and (td.usos_restantes(alvo, "Refúgio Feérico") or 0) > 0
            and _confirmar(alvo, "refugio feerico", f"{atacante['name']} feriu {alvo['name']} ({dano}). Usar "
                                                    f"Refúgio Feérico (some e fica Invisível)?")):
        td._gastar_uso(alvo, "Refúgio Feérico")
        destino = resolucao._empurrar_para_longe(alvo, atacante) if td._zonas_ativas() else ""
        resolucao._tirar_condicoes(alvo, ("invisivel",))
        alvo["sheet"].setdefault("condicoes", []).append(
            {"nome": "Invisível", "duracao": None, "ate_turno_de": memory.char_key(alvo["name"])})
        msg = (f"{alvo['name']} some num lampejo feérico (Refúgio Feérico)"
               + (f" e reaparece em {destino}" if destino else "") + ", Invisível até o próximo turno.")
        _registrar(alvo, "Refúgio Feérico", atacante.get("name", ""), msg)
        return [msg]
    hab = _pode_reagir(alvo, "repreensao infernal")
    if (hab and int(alvo["sheet"].get("mana_atual", 0) or 0) >= _custo_de_mana(hab)
            and _confirmar(alvo, "repreensao infernal",
                           f"{atacante['name']} feriu {alvo['name']} ({dano}). Conjurar Repreensão Infernal "
                           f"({_custo_de_mana(hab)} mana, 2d10 de fogo)?")
            and _pagar_mana(alvo, hab)):
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
    if (hab and not td._distancia(alvo.get("name", ""), atacante.get("name", ""))
            and _confirmar(alvo, "retaliacao", f"{atacante['name']} feriu {alvo['name']} ({dano}). "
                                               f"Atacar de volta (Retaliação)?")):
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


def _atacar_de_reacao(quem: dict, alvo: dict, rotulo: str) -> str:
    from rpg import tools_dnd as td
    td._consume_reaction(quem)
    arma = ((quem["sheet"].get("equipamentos") or {}).get("arma_principal")
            or td._melee_weapon_of(quem) or "ataque desarmado")
    golpe = td.attack_roll(quem["name"], alvo["name"], arma, 6, end_turn=False, _skip_turn_check=True)
    td._log_combat_event("reaction", quem["name"], alvo["name"], msg=f"{quem['name']} usa {rotulo}", reacao=rotulo)
    return f"{quem['name']} usa {rotulo}:\n" + golpe.replace(td._BONUS_ACTION_HINT, "")


def depois_do_ataque(atacante: dict, alvo: dict, acertou: bool, a_distancia: bool, arma: str) -> list[str]:
    """Golpe Mágico, Marca da Vingança, Oportunista, Vingança do Grande Antigo."""
    from rpg import resolucao, tools_dnd as td
    linhas = []
    vivo = lambda c: int((c.get("sheet") or {}).get("vida_atual", 0) or 0) > 0  # noqa: E731
    lado_atk = memory.luta_com_o_grupo(atacante)
    if lado_atk == memory.luta_com_o_grupo(alvo):
        return []
    # Vingança do Grande Antigo: quem ataca o bruxo leva psíquico.
    if (vivo(alvo) and vivo(atacante) and _pode_reagir(alvo, "vinganca do grande antigo")
            and _confirmar(alvo, "vinganca do grande antigo",
                           f"{atacante['name']} atacou {alvo['name']}. Usar Vingança do Grande Antigo?")):
        dano = 1 + max(0, td._modifier(int(alvo["sheet"].get("carisma", 10) or 10)))
        res = td._apply_damage(atacante, dano, "psychic", source_name=alvo["name"])
        msg = (f"Vingança do Grande Antigo: {atacante['name']} leva {res['dano']} de dano psíquico "
               f"({res['hp_antes']} → {res['hp_depois']}).")
        _registrar(alvo, "Vingança do Grande Antigo", atacante.get("name", ""), msg)
        linhas.append(msg)
    # Golpe Mágico: quem acertou conjura o truque no mesmo alvo.
    if acertou and vivo(alvo) and _pode_reagir(atacante, "golpe magico"):
        truques = []
        for h in atacante.get("habilidades") or []:
            m = resolucao._magia_srd(h) if isinstance(h, dict) else None
            if m and int(m.get("nivel", 0) or 0) == 0 and m.get("efeito") == "dano":
                truques.append((td._media_da_formula(td.dado_efetivo(h, atacante)), h))
        if truques:
            _, h = max(truques, key=lambda x: x[0])
            td._consume_reaction(atacante)
            saida = td.use_ability(atacante["name"], h["nome"], alvo["name"], end_turn=False,
                                   _skip_turn_check=True, _sem_custo=True)
            linhas.append(f"{atacante['name']} usa Golpe Mágico:\n" + saida.replace(td._BONUS_ACTION_HINT, ""))
    cs = memory.campaign.get("combat_state") or {}
    for nm in list(cs.get("initiative_order") or []):
        c = memory.campaign["characters"].get(memory.char_key(nm))
        if not c or c is atacante or c is alvo or not vivo(c):
            continue
        # Marca da Vingança: inimigo atacou um aliado na zona do paladino.
        if (memory.luta_com_o_grupo(c) == memory.luta_com_o_grupo(alvo) and vivo(atacante)
                and not td._distancia(c["name"], alvo["name"]) and not td._distancia(c["name"], atacante["name"])
                and _pode_reagir(c, "marca da vinganca")
                and _confirmar(c, "marca da vinganca", f"{atacante['name']} atacou {alvo['name']}. {c['name']} "
                                                       f"ataca {atacante['name']} (Marca da Vingança)?")):
            linhas.append(_atacar_de_reacao(c, atacante, "Marca da Vingança"))
        # Oportunista: um aliado acertou o inimigo na zona do monge.
        elif (acertou and memory.luta_com_o_grupo(c) == lado_atk and vivo(alvo)
              and not td._distancia(c["name"], alvo["name"]) and _pode_reagir(c, "oportunista")
              and _confirmar(c, "oportunista", f"{atacante['name']} acertou {alvo['name']}. {c['name']} ataca "
                                               f"{alvo['name']} (Oportunista)?")):
            linhas.append(_atacar_de_reacao(c, alvo, "Oportunista"))
    return linhas


# ── Lampejos de Adivinhação ─────────────────────────────────────────────────

def _lampejos(char: dict) -> list[int]:
    """Os d20 guardados (rolados no descanso longo; na primeira vez, agora)."""
    from rpg import tools_dnd as td
    s = char.setdefault("sheet", {})
    if "lampejos" not in s:
        n = 4 if td._tem_habilidade(char, "lampejos aprimorados") else (
            3 if td._tem_habilidade(char, "visao aprofundada") else 2)
        s["lampejos"] = [random.randint(1, 20) for _ in range(n)]
    return s["lampejos"]


def _adivinho_do_lado(quem: dict) -> dict | None:
    for c in (memory.campaign.get("characters") or {}).values():
        if (isinstance(c, dict) and c.get("sheet") and memory.luta_com_o_grupo(c) == memory.luta_com_o_grupo(quem)
                and memory.is_party_member(c) and _pode_reagir(c, "lampejos") and _lampejos(c)):
            return c
    return None


def lampejo_no_ataque(atacante: dict, alvo: dict, d20: int, total: int, ca: int) -> tuple[int, str]:
    """(novo d20, linha) quando um Lampejo vira o ataque; (d20, '') quando não."""
    acerta = d20 != 1 and (d20 == 20 or total >= ca)
    adivinho = _adivinho_do_lado(alvo) if acerta else _adivinho_do_lado(atacante)
    if not adivinho or memory.luta_com_o_grupo(atacante) == memory.luta_com_o_grupo(alvo):
        return d20, ""
    guardados = _lampejos(adivinho)
    resto = total - d20
    if acerta and not memory.luta_com_o_grupo(atacante):
        v = min(guardados)
        if v == 20 or v + resto >= ca:
            return d20, ""
    elif not acerta and memory.luta_com_o_grupo(atacante):
        v = max(guardados)
        if v == 1 or (v != 20 and v + resto < ca):
            return d20, ""
    else:
        return d20, ""
    guardados.remove(v)
    return v, f"{adivinho['name']} usa um Lampejo de Adivinhação: o d20 de {atacante['name']} vira {v}."


def lampejo_na_salvaguarda(alvo: dict, mod: int, cd: int) -> tuple[bool, str]:
    """A salvaguarda do grupo que falhou passa com o maior Lampejo, se ele basta."""
    if not memory.luta_com_o_grupo(alvo):
        return False, ""
    adivinho = _adivinho_do_lado(alvo)
    if not adivinho:
        return False, ""
    guardados = _lampejos(adivinho)
    v = max(guardados)
    if v + mod < cd:
        return False, ""
    guardados.remove(v)
    return True, f"{adivinho['name']} usa um Lampejo de Adivinhação: o d20 vira {v} ({v}{mod:+d} = {v + mod} vs CD {cd})"


def bonus_projetado(alvo: dict, atributo: str, mod: int) -> tuple[int, str]:
    """Resistência Mágica Projetada: o aliado perto empresta o bônus de salvaguarda, se for maior."""
    from rpg import tools_dnd as td
    cs = memory.campaign.get("combat_state") or {}
    if not cs.get("is_active") or not memory.luta_com_o_grupo(alvo):
        return mod, ""
    for c in (memory.campaign.get("characters") or {}).values():
        if not isinstance(c, dict) or c is alvo or not c.get("sheet"):
            continue
        if memory.luta_com_o_grupo(c) != memory.luta_com_o_grupo(alvo):
            continue
        d = td._distancia(c.get("name", ""), alvo.get("name", ""))
        if d is not None and d > 1:
            continue
        if not _pode_reagir(c, "resistencia magica projetada"):
            continue
        s = c["sheet"]
        dele = td._modifier(int(s.get(atributo, 10) or 10))
        if atributo in td.CLASS_DATA.get((s.get("classe") or "").lower(), {}).get("saves", []):
            dele += int(s.get("proficiencia", 2) or 2)
        if dele > mod and _confirmar(c, "resistencia magica projetada",
                                     f"{alvo['name']} faz salvaguarda de {atributo} ({mod:+d}). {c['name']} "
                                     f"empresta o bônus dele ({dele:+d})?"):
            td._consume_reaction(c)
            return dele, f"Resistência Mágica Projetada de {c['name']}: usa {dele:+d}"
    return mod, ""


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
    if not _confirmar(alvo, "contra ataque", f"{atacante['name']} errou {alvo['name']}. Contra-Atacar (gasta um "
                                             f"dado de superioridade)?"):
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
        nivel = int(m.get("nivel", 0) or 0)
        if not cm or int(ch["sheet"].get("mana_atual", 0) or 0) < _custo_de_mana(cm):
            continue
        if not _confirmar(ch, "contramagica",
                          f"{conjurador['name']} conjura {m.get('nome', hab.get('nome'))} ({nivel}º círculo). "
                          f"{ch['name']} conjura Contramágica ({_custo_de_mana(cm)} mana)?"
                          + ("" if nivel <= 3 else f" Acima do 3º círculo é um teste contra CD {10 + nivel}.")):
            continue
        if not _pagar_mana(ch, cm):
            continue
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
