"""
tracos.py
O tipo das criaturas, os traços delas e o que cada ataque natural carrega.

POR QUE EXISTE
──────────────
As fichas das criaturas tinham ataque, vida e resistência, e mais nada. O
lobo tinha "Táticas de Matilha" escrito numa nota que ninguém lia; a mordida
da aranha gigante não envenenava; o elemental do fogo podia ser socado sem
queimar a mão; o zumbi caía como qualquer outro. E Imobilizar Pessoa
paralisava o lobo, o elemental e o dragão: a regra "só humanoides" não
existia para o motor.

O QUE TEM AQUI
──────────────
• tipo_de_criatura: humanoide, fera, morto-vivo... da ficha, do bloco do
  Open5e ou da raça. Vazio quando não dá para saber — aí o Mestre decide.
• recusa_de_tipo: a magia que exige um tipo (Imobilizar Pessoa) ou que não
  vale em outro (Curar Ferimentos em morto-vivo).
• Traços de criatura (sheet["tracos"], ou o nome do traço do Open5e entre as
  habilidades): Táticas de Matilha, Resistência à Magia, Fortitude
  Morta-Viva, Forma de Fogo, Armas Mágicas. As imunidades a condição ficam em
  sheet["imunidades_condicao"].
• O que o ataque natural carrega, na entrada de sheet["ataques"]:
    derruba    {"salvaguarda", "cd"}               salvaguarda ou Caído
    rider      {"salvaguarda", "cd", "dado", "tipo", "metade", "condicao",
                "duracao", "repete"}               veneno, paralisia
    agarra     {"cd", "contido"}                   Agarrado (e Contido)
    incendeia  {"dado"}                            o alvo fica Queimando
    investida  {"dado", "tipo", "derruba"}         depois de andar no turno
  O bloco do Open5e vira esses campos em efeitos_do_texto (spawn_monster).
"""
from __future__ import annotations

import random
import re

from rpg import memory

# ── Tipo de criatura ─────────────────────────────────────────────────────────

# tipo do SRD (inglês ou português) → nome canônico
_TIPOS = {
    "humanoid": "humanoide", "humanoide": "humanoide",
    "beast": "fera", "fera": "fera", "besta": "fera",
    "undead": "morto-vivo", "morto-vivo": "morto-vivo", "morto vivo": "morto-vivo",
    "construct": "constructo", "constructo": "constructo",
    "elemental": "elemental",
    "fey": "fada", "fada": "fada", "feerico": "fada",
    "fiend": "corruptor", "corruptor": "corruptor", "infernal": "corruptor",
    "celestial": "celestial",
    "dragon": "dragao", "dragao": "dragao",
    "monstrosity": "monstruosidade", "monstruosidade": "monstruosidade",
    "giant": "gigante", "gigante": "gigante",
    "aberration": "aberracao", "aberracao": "aberracao",
    "ooze": "limo", "limo": "limo",
    "plant": "planta", "planta": "planta",
}

# Raças de personagem: humanoides.
_RACAS_HUMANOIDES = ("humano", "human", "elfo", "elf", "anao", "dwarf", "halfling", "gnomo", "gnome",
                     "meio-elfo", "meio-orc", "half-elf", "half-orc", "tiefling", "draconato", "dragonborn",
                     "orc", "goblin", "hobgoblin", "bugbear", "kobold", "gnoll", "bandido", "bandit",
                     "guarda", "guard", "cultista", "cultist", "acolito", "acolyte", "mago", "mage",
                     "soldado", "soldier", "nobre", "noble", "plebeu", "commoner", "assassino", "assassin",
                     "cavaleiro", "knight", "sacerdote", "priest", "veterano", "veteran", "batedor", "scout")


def _norm(s: str) -> str:
    from rpg import resolucao
    return resolucao.norm(s or "")


def tipo_de_criatura(ch: dict | None) -> str:
    """O tipo canônico da criatura, ou '' quando a ficha não diz."""
    if not ch:
        return ""
    s = ch.get("sheet") or {}
    # Na Forma Selvagem (ou Polimorfia), o tipo é o da forma.
    if s.get("_forma_selvagem"):
        from rpg import criaturas
        forma = criaturas.FICHAS.get((s["_forma_selvagem"] or {}).get("chave", "")) or {}
        return _TIPOS.get(_norm(forma.get("tipo", "")), "fera")
    tipo = _norm(str(s.get("tipo") or ""))
    if tipo:
        primeiro = tipo.split("(")[0].strip()
        if primeiro in _TIPOS:
            return _TIPOS[primeiro]
        for chave, canon in _TIPOS.items():
            if primeiro.startswith(chave):
                return canon
    # O bloco do Open5e: "Medium humanoid (goblinoid) — CR 1/4."
    achado = re.search(r"\b(?:tiny|small|medium|large|huge|gargantuan)\s+([a-z\-]+)",
                       _norm(ch.get("description", "")))
    if achado and achado.group(1) in _TIPOS:
        return _TIPOS[achado.group(1)]
    raca = _norm(str(s.get("raca") or ""))
    if raca and any(re.search(rf"\b{re.escape(p)}\b", raca) for p in _RACAS_HUMANOIDES):
        return "humanoide"
    if memory.is_party_member(ch):
        return "humanoide"
    return ""


_NOME_DO_TIPO = {"humanoide": "humanoides", "fera": "feras", "morto-vivo": "mortos-vivos",
                 "constructo": "constructos", "elemental": "elementais", "fada": "fadas",
                 "corruptor": "corruptores", "celestial": "celestiais", "dragao": "dragões"}

# Magia (nome no SRD) → só estes tipos, ou todos menos estes.
RESTRICOES = {
    "Hold Person": {"so": ("humanoide",)},
    "Dominate Person": {"so": ("humanoide",)},
    "Dominate Beast": {"so": ("fera",)},
    "Hold Monster": {"exceto": ("morto-vivo",)},
    "Sleep": {"exceto": ("morto-vivo",), "feerico": True},
    "Cure Wounds": {"exceto": ("morto-vivo", "constructo")},
    "Healing Word": {"exceto": ("morto-vivo", "constructo")},
    "Mass Cure Wounds": {"exceto": ("morto-vivo", "constructo")},
    "Mass Healing Word": {"exceto": ("morto-vivo", "constructo")},
    "Prayer of Healing": {"exceto": ("morto-vivo", "constructo")},
    "Heal": {"exceto": ("morto-vivo", "constructo")},
    "Revivify": {"exceto": ("morto-vivo", "constructo")},
    "Raise Dead": {"exceto": ("morto-vivo",)},
}


def _ancestralidade_feerica(ch: dict) -> bool:
    """Elfo e meio-elfo: magia não os põe para dormir."""
    from rpg import tools_dnd as td
    raca = _norm(str((ch.get("sheet") or {}).get("raca") or ""))
    return bool(re.search(r"\belf|\belfo|meio-elfo", raca)) or td._tem_habilidade(
        ch, "ancestralidade feerica", "fey ancestry")


def recusa_de_tipo(hab: dict, alvo: dict | None) -> str:
    """
    Por que esta magia não afeta este alvo ('' quando afeta, ou quando a
    ficha não diz o tipo — o Mestre decide).
    """
    from rpg import resolucao
    m = resolucao._magia_srd(hab) or {}
    regra = RESTRICOES.get(m.get("nome_srd", ""))
    if not regra or not alvo:
        return ""
    nome_pt = m.get("nome") or hab.get("nome", "")
    if regra.get("feerico") and _ancestralidade_feerica(alvo):
        return f"{nome_pt} não põe {alvo.get('name')} para dormir (ancestralidade feérica)"
    tipo = tipo_de_criatura(alvo)
    if not tipo:
        return ""
    if regra.get("so") and tipo not in regra["so"]:
        quais = " e ".join(_NOME_DO_TIPO.get(t, t) for t in regra["so"])
        return f"{nome_pt} só afeta {quais}: {alvo.get('name')} é {tipo}"
    if tipo in (regra.get("exceto") or ()):
        return f"{nome_pt} não tem efeito em {_NOME_DO_TIPO.get(tipo, tipo)}: {alvo.get('name')} é {tipo}"
    return ""


# ── Traços ───────────────────────────────────────────────────────────────────

# Nome do traço no Open5e (ou em português) → chave
_TRACOS_POR_NOME = {
    "pack tactics": "matilha", "taticas de matilha": "matilha",
    "magic resistance": "resistencia magica", "resistencia a magia": "resistencia magica",
    "resistencia magica": "resistencia magica",
    "undead fortitude": "fortitude", "fortitude morta-viva": "fortitude", "fortitude morta viva": "fortitude",
    "fire form": "forma de fogo", "forma de fogo": "forma de fogo",
    "magic weapons": "armas magicas", "armas magicas": "armas magicas",
}


def tracos_de(ch: dict | None) -> set[str]:
    if not ch:
        return set()
    s = ch.get("sheet") or {}
    saida = {_norm(t) for t in s.get("tracos") or []}
    for h in ch.get("habilidades") or []:
        if isinstance(h, dict):
            chave = _TRACOS_POR_NOME.get(_norm(h.get("nome", "")))
            if chave:
                saida.add(chave)
    return saida


# Magia em curso (use_ability com magia do SRD): a Resistência à Magia vale.
_magias_em_curso = 0


def contra_magia(alvo: dict) -> bool:
    """A salvaguarda que se rola agora é contra magia, e o alvo tem Resistência à Magia."""
    return _magias_em_curso > 0 and "resistencia magica" in tracos_de(alvo)


def armas_magicas(ch: dict) -> bool:
    return "armas magicas" in tracos_de(ch)


def _de_pe(c: dict) -> bool:
    from rpg import tools_dnd as td
    return (bool(c and c.get("sheet")) and int(c["sheet"].get("vida_atual", 0) or 0) > 0
            and (c.get("status") or "").lower() not in td.OUT_OF_COMBAT_STATUSES
            and not td._impedido_de_agir(c))


def matilha(atacante: dict, alvo: dict) -> str:
    """Táticas de Matilha: vantagem quando um aliado de quem ataca está ao lado do alvo."""
    from rpg import tools_dnd as td
    if "matilha" not in tracos_de(atacante):
        return ""
    cs = memory.campaign.get("combat_state") or {}
    lado = memory.luta_com_o_grupo(atacante)
    for nm in cs.get("initiative_order") or []:
        c = memory.campaign["characters"].get(memory.char_key(nm))
        if not c or c is atacante or c is alvo or not _de_pe(c) or memory.luta_com_o_grupo(c) != lado:
            continue
        if td._zonas_ativas() and td._zona_de(c.get("name", "")) != td._zona_de(alvo.get("name", "")):
            continue
        return f"Táticas de Matilha: {c['name']} está ao lado de {alvo['name']} — vantagem"
    return ""


def fortitude_morta_viva(alvo: dict, dano: int, tipos: set[str], critico: bool) -> str:
    """
    Fortitude Morta-Viva (zumbi): o golpe que o derrubaria pede CON contra
    5 + dano; passou, fica com 1 PV. Não vale contra radiante nem crítico.
    """
    from rpg import tools_dnd as td
    if "fortitude" not in tracos_de(alvo) or critico or "radiant" in tipos or dano <= 0:
        return ""
    cd = 5 + dano
    passou, linha = td._rolar_salvaguarda(alvo, "constituicao", cd)
    if passou:
        return f"Fortitude Morta-Viva: {linha} — {alvo.get('name')} fica de pé com 1 PV"
    return f"Fortitude Morta-Viva: {linha} — cai"


# ── O que o ataque natural carrega ───────────────────────────────────────────

def _tem_condicao(ch: dict, nome: str) -> bool:
    return any(_norm(c.get("nome", "") if isinstance(c, dict) else str(c)) == _norm(nome)
               for c in (ch.get("sheet") or {}).get("condicoes") or [])


def _por_condicao(atacante: dict, alvo: dict, nome: str, extra: dict | None = None) -> str:
    """Põe a condição (se o alvo não for imune nem já a tiver). Devolve a linha."""
    from rpg import tools_dnd as td
    if td._imune_a_condicao(alvo, nome):
        return f"{alvo['name']} é imune a {nome}."
    if not _tem_condicao(alvo, nome):
        c = {"nome": nome, "duracao": None, "por": atacante.get("name", "")}
        c.update(extra or {})
        alvo["sheet"].setdefault("condicoes", []).append(c)
        td._log_combat_event("condition", atacante.get("name", ""), alvo.get("name", ""),
                             msg=f"{alvo['name']} ficou {nome} ({atacante.get('name', '')})")
    if _norm(nome) == "caido":
        from rpg import manobras
        if manobras.cavaleiro_de(alvo):
            return f"{alvo['name']}: **{nome.upper()}** — " + manobras.queda_da_montaria(alvo, "a montaria caiu")
        if manobras.montaria_de(alvo):
            manobras.desmontar(alvo["name"], "derrubado da sela")
    return f"{alvo['name']}: **{nome.upper()}**"


def _derrubar(atacante: dict, alvo: dict, cfg: dict) -> str:
    from rpg import tools_dnd as td
    if _tem_condicao(alvo, "Caído"):
        return ""
    passou, linha = td._rolar_salvaguarda(alvo, cfg.get("salvaguarda", "forca"), int(cfg.get("cd", 10)))
    if passou:
        return f"{alvo['name']}: {linha} — continua de pé."
    return f"{alvo['name']}: {linha} — " + _por_condicao(atacante, alvo, "Caído")


def _rider(atacante: dict, alvo: dict, cfg: dict, critico: bool) -> list[str]:
    """Veneno, paralisia: salvaguarda; dano (metade se passar, quando a regra diz) e a condição."""
    from rpg import tools_dnd as td
    if cfg.get("exceto_tipos") and tipo_de_criatura(alvo) in cfg["exceto_tipos"]:
        return []
    if cfg.get("exceto_elfos") and _ancestralidade_feerica(alvo):
        return [f"{alvo['name']} é elfo: a paralisia do carniçal não o pega."]
    cd = int(cfg.get("cd", 10))
    passou, linha = td._rolar_salvaguarda(alvo, cfg.get("salvaguarda", "constituicao"), cd,
                                          contra=cfg.get("condicao", ""))
    linhas = []
    dado = cfg.get("dado") or ""
    if dado and (not passou or cfg.get("metade")):
        n, faces, bonus = td._parse_dice(dado)
        rolls = [random.randint(1, faces) for _ in range(n)]
        total = max(0, sum(rolls) + bonus)
        if passou:
            total //= 2
        res = td._apply_damage(alvo, total, cfg.get("tipo", "poison"), source_name=atacante.get("name", ""))
        linhas.append(f"{alvo['name']}: {linha} — {'metade: ' if passou else ''}{res['dano']} de "
                      f"{td._TIPO_DE_DANO_PT.get(res['tipo'], res['tipo'] or 'dano')}"
                      f" [{' + '.join(map(str, rolls))}] ({res['hp_antes']} → {res['hp_depois']})"
                      + td._fmt_notas(res["notas"]).replace("\n", " "))
        if res["hp_depois"] == 0:
            return linhas                   # quem chamou marca a queda
    elif passou:
        linhas.append(f"{alvo['name']}: {linha} — resistiu.")
    if cfg.get("condicao") and not passou and int((alvo.get("sheet") or {}).get("vida_atual", 0) or 0) > 0:
        extra = {}
        if cfg.get("duracao"):
            extra["duracao"] = int(cfg["duracao"])
        if cfg.get("repete"):
            extra["salvaguarda_fim"] = {"atributo": cfg.get("salvaguarda", "constituicao"), "cd": cd}
        texto = _por_condicao(atacante, alvo, cfg["condicao"], extra)
        linhas.append(texto if dado else f"{alvo['name']}: {linha} — {texto}")
    return linhas


def _agarrar(atacante: dict, alvo: dict, cfg: dict) -> list[str]:
    from rpg import tools_dnd as td
    if td._imune_a_condicao(alvo, "Agarrado"):
        return [f"{alvo['name']} é imune a Agarrado."]
    if any(isinstance(c, dict) and _norm(c.get("nome", "")) == "agarrado"
           for c in alvo["sheet"].get("condicoes") or []):
        return []
    linhas = [_por_condicao(atacante, alvo, "Agarrado", {"escapa_cd": int(cfg.get("cd", 10))})
              + f" (escapa com CD {int(cfg.get('cd', 10))})"]
    if cfg.get("contido") and not td._imune_a_condicao(alvo, "Contido"):
        linhas.append(_por_condicao(atacante, alvo, "Contido", {"da_pegada": True}))
    return linhas


def _incendiar(atacante: dict, alvo: dict, cfg: dict) -> str:
    if _tem_condicao(alvo, "Queimando"):
        return ""
    return _por_condicao(atacante, alvo, "Queimando", {"dado": (cfg or {}).get("dado", "1d10")}) \
        + " (fogo no início de cada turno até apagar)"


def _moveu_neste_turno(atacante: dict) -> bool:
    from rpg import tools_dnd as td
    cs = memory.campaign.get("combat_state") or {}
    eco = cs.get("turn_economy") or {}
    return (memory.char_key(td._combat_current_actor()) == memory.char_key(atacante.get("name", ""))
            and bool(eco.get("movimento_usado")))


def depois_do_acerto(atacante: dict, alvo: dict, arma: str, critico: bool, a_distancia: bool) -> list[str]:
    """O que o golpe natural carrega, e a Forma de Fogo de quem foi tocado."""
    from rpg import tools_dnd as td
    entrada = td._npc_attack_entry(atacante.get("sheet") or {}, arma) or {}
    linhas: list[str] = []
    vivo = lambda c: int((c.get("sheet") or {}).get("vida_atual", 0) or 0) > 0  # noqa: E731
    inv = entrada.get("investida")
    cs = memory.campaign.get("combat_state") or {}
    token = cs.get("turn_token")
    if inv and vivo(alvo) and _moveu_neste_turno(atacante) and atacante["sheet"].get("_investida") != token:
        atacante["sheet"]["_investida"] = token
        if inv.get("dado"):
            n, faces, bonus = td._parse_dice(inv["dado"])
            rolls = [random.randint(1, faces) for _ in range(n * (2 if critico else 1))]
            res = td._apply_damage(alvo, max(0, sum(rolls) + bonus), inv.get("tipo", ""),
                                   source_name=atacante.get("name", ""),
                                   arma_magica=armas_magicas(atacante))
            linhas.append(f"Investida de {atacante['name']}: +[{' + '.join(map(str, rolls))}] = {res['dano']} "
                          f"({res['hp_antes']} → {res['hp_depois']})")
        if inv.get("derruba") and vivo(alvo):
            linha = _derrubar(atacante, alvo, inv["derruba"])
            if linha:
                linhas.append("Investida: " + linha)
    if entrada.get("derruba") and vivo(alvo):
        linha = _derrubar(atacante, alvo, entrada["derruba"])
        if linha:
            linhas.append(linha)
    if entrada.get("rider") and vivo(alvo):
        linhas.extend(_rider(atacante, alvo, entrada["rider"], critico))
    if entrada.get("agarra") and vivo(alvo):
        linhas.extend(_agarrar(atacante, alvo, entrada["agarra"]))
    if entrada.get("incendeia") and vivo(alvo):
        linha = _incendiar(atacante, alvo, entrada["incendeia"])
        if linha:
            linhas.append(linha)
    # Forma de Fogo: quem acerta o elemental do fogo de perto se queima.
    if not a_distancia and "forma de fogo" in tracos_de(alvo) and vivo(atacante):
        d10 = random.randint(1, 10)
        res = td._apply_damage(atacante, d10, "fire", source_name=alvo.get("name", ""), arma_magica=True)
        linhas.append(f"Forma de Fogo de {alvo['name']}: {atacante['name']} leva {res['dano']} de fogo "
                      f"(1d10={d10}; {res['hp_antes']} → {res['hp_depois']})")
        if res["hp_depois"] == 0 and res["hp_antes"] > 0:
            linhas.append(td._mark_at_zero_hp(atacante, alvo.get("name", "")).strip())
    return linhas


# ── O bloco do Open5e ────────────────────────────────────────────────────────

_CONDICAO_EN = {"poisoned": "Envenenado", "paralyzed": "Paralisado", "frightened": "Amedrontado",
                "blinded": "Cego", "stunned": "Atordoado", "charmed": "Enfeitiçado",
                "restrained": "Contido", "unconscious": "Inconsciente", "incapacitated": "Incapacitado"}
_SAVE_EN = {"strength": "forca", "dexterity": "destreza", "constitution": "constituicao",
            "intelligence": "inteligencia", "wisdom": "sabedoria", "charisma": "carisma"}


def efeitos_do_texto(desc: str) -> dict:
    """
    O que a descrição de um ataque do Open5e carrega: "DC 11 Strength saving
    throw or be knocked prone", "grappled (escape DC 12)", "DC 11
    Constitution saving throw, taking 9 (2d8) poison damage on a failed save,
    or half as much".
    """
    d = (desc or "").lower()
    saida: dict = {}
    sv = re.search(r"dc (\d+) (strength|dexterity|constitution|intelligence|wisdom|charisma) saving throw", d)
    if "knocked prone" in d and sv:
        saida["derruba"] = {"salvaguarda": _SAVE_EN[sv.group(2)], "cd": int(sv.group(1))}
    g = re.search(r"grappled \(escape dc (\d+)\)", d)
    if g:
        saida["agarra"] = {"cd": int(g.group(1)), "contido": "restrained" in d}
    if sv and "knocked prone" not in d:
        rider: dict = {"salvaguarda": _SAVE_EN[sv.group(2)], "cd": int(sv.group(1))}
        dano = re.search(r"saving throw[^.]*?\((\d+d\d+(?:\s*[+-]\s*\d+)?)\)\s+(\w+) damage", d)
        if dano:
            rider["dado"] = dano.group(1).replace(" ", "")
            from rpg import tools_dnd as td
            rider["tipo"] = td._norm_damage_type(dano.group(2)) or dano.group(2)
            rider["metade"] = "half as much" in d
        cond = re.search(r"or be (poisoned|paralyzed|frightened|blinded|stunned|charmed|restrained)", d) \
            or re.search(r"(?:is|be|become) (poisoned|paralyzed|frightened|blinded|stunned)", d)
        if cond:
            rider["condicao"] = _CONDICAO_EN[cond.group(1)]
            if "end of each of its turns" in d:
                rider["repete"] = True
            if "for 1 minute" in d:
                rider["duracao"] = 10
        if rider.get("dado") or rider.get("condicao"):
            saida["rider"] = rider
    return saida


def imunidades_de_condicao(texto) -> list[str]:
    """O campo condition_immunities do Open5e ("poisoned, exhaustion") em português."""
    if isinstance(texto, list):
        texto = ", ".join(str(x.get("name", x) if isinstance(x, dict) else x) for x in texto)
    saida = []
    for parte in re.split(r"[,;]", str(texto or "").lower()):
        p = parte.strip()
        nome = {**_CONDICAO_EN, "grappled": "Agarrado", "prone": "Caído", "exhaustion": "Exausto",
                "petrified": "Petrificado", "deafened": "Surdo"}.get(p)
        if nome:
            saida.append(nome)
    return saida
