"""
tools_dnd.py
Ferramentas do motor de regras D&D para o modo de jogo estruturado.

Todas as funções aqui seguem a lógica de D&D 5e simplificado com um
sistema de mana em lugar de slots de magia (mais amigável para videogame).

Novidades (v2):
  • Vantagem / Desvantagem em attack_roll e make_skill_check
  • Saving Throws em use_ability (dano pela metade se passar)
  • equip_item / unequip_item com recálculo dinâmico de CA
  • apply_condition / remove_condition com efeitos mecânicos automáticos
  • Campos separados de moedas (ouro / prata / cobre) + modify_currency
  • roll_death_save estruturado
"""

import random
import re
import memory


# ---------------------------------------------------------------------------
# Helpers de controle de turno
# ---------------------------------------------------------------------------

def _mark_turn_resolved() -> None:
    """Marca o turno como mecanicamente resolvido."""
    cs = memory.campaign.get("combat_state")
    if cs and cs.get("is_active"):
        cs["turn_resolved"] = True


def _auto_advance_turn() -> str:
    """
    Avança o turno e retorna o anúncio do próximo como string.
    Injetado no final de attack_roll(), use_ability() e roll_death_save().
    Retorna string vazia fora do combate.
    """
    cs = memory.campaign.get("combat_state")
    if not cs or not cs.get("is_active"):
        return ""
    order = cs.get("initiative_order", [])
    if not order:
        return ""

    idx       = cs.get("current_turn_index", 0) + 1
    round_num = cs.get("round", 1)
    if idx >= len(order):
        idx        = 0
        round_num += 1
        cs["round"] = round_num

    cs["current_turn_index"] = idx
    cs["turn_resolved"]      = False
    next_name = order[idx]
    new_round = f"\n   🔔 Nova rodada! Rodada {round_num} começa." if idx == 0 else ""
    order_str = " → ".join(f"[{n}]" if i == idx else n for i, n in enumerate(order))
    return (
        f"\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏭️  TURNO AVANÇADO — Rodada {round_num}{new_round}\n"
        f"🎯 Próxima vez: **{next_name}**\n"
        f"   Ordem: {order_str}"
    )


# ---------------------------------------------------------------------------
# Tabelas e constantes do sistema
# ---------------------------------------------------------------------------

XP_THRESHOLDS = [
    0,      # Nível 1
    300,    # Nível 2
    900,    # Nível 3
    2700,   # Nível 4
    6500,   # Nível 5
    14000,  # Nível 6
    23000,  # Nível 7
    34000,  # Nível 8
    48000,  # Nível 9
    64000,  # Nível 10
    85000,  # Nível 11
    100000, # Nível 12
    120000, # Nível 13
    140000, # Nível 14
    165000, # Nível 15
    195000, # Nível 16
    225000, # Nível 17
    265000, # Nível 18
    305000, # Nível 19
    355000, # Nível 20
]

CLASS_DATA: dict[str, dict] = {
    "bárbaro":     {"hit_die": 12, "mana_per_level": 0,  "mana_stat": None,          "saves": ["forca", "constituicao"]},
    "guerreiro":   {"hit_die": 10, "mana_per_level": 2,  "mana_stat": "forca",       "saves": ["forca", "constituicao"]},
    "paladino":    {"hit_die": 10, "mana_per_level": 5,  "mana_stat": "carisma",     "saves": ["sabedoria", "carisma"]},
    "patrulheiro": {"hit_die": 8,  "mana_per_level": 4,  "mana_stat": "sabedoria",   "saves": ["forca", "destreza"]},
    "bardo":       {"hit_die": 8,  "mana_per_level": 6,  "mana_stat": "carisma",     "saves": ["destreza", "carisma"]},
    "clérigo":     {"hit_die": 8,  "mana_per_level": 8,  "mana_stat": "sabedoria",   "saves": ["sabedoria", "carisma"]},
    "druida":      {"hit_die": 8,  "mana_per_level": 8,  "mana_stat": "sabedoria",   "saves": ["inteligencia", "sabedoria"]},
    "monge":       {"hit_die": 8,  "mana_per_level": 4,  "mana_stat": "sabedoria",   "saves": ["forca", "destreza"]},
    "ladino":      {"hit_die": 8,  "mana_per_level": 2,  "mana_stat": "destreza",    "saves": ["destreza", "inteligencia"]},
    "mago":        {"hit_die": 6,  "mana_per_level": 10, "mana_stat": "inteligencia","saves": ["inteligencia", "sabedoria"]},
    "feiticeiro":  {"hit_die": 6,  "mana_per_level": 10, "mana_stat": "carisma",     "saves": ["constituicao", "carisma"]},
    "bruxo":       {"hit_die": 8,  "mana_per_level": 8,  "mana_stat": "carisma",     "saves": ["sabedoria", "carisma"]},
    "arcanista":   {"hit_die": 6,  "mana_per_level": 12, "mana_stat": "inteligencia","saves": ["inteligencia", "sabedoria"]},
}

STAT_NAMES = {"forca", "destreza", "constituicao", "inteligencia", "sabedoria", "carisma"}
# ── Custo de mana por nível de magia ────────────────────────────────────────
SPELL_MANA_COST = {0: 0, 1: 4, 2: 8, 3: 12, 4: 16, 5: 20, 6: 24, 7: 28, 8: 32, 9: 36}

# ── Tradução PT → EN para busca no Open5e ───────────────────────────────────
# ── Níveis reais de magias comuns para validar/corrigir respostas da API ────
# Evita que a busca fuzzy do Open5e retorne nível errado
SPELL_LEVEL_OVERRIDE: dict[str, int] = {
    # Cantrips (0)
    "prestidigitation": 0, "ray of frost": 0, "light": 0, "sacred flame": 0,
    "eldritch blast": 0, "toll the dead": 0, "mage hand": 0, "fire bolt": 0,
    "chill touch": 0, "minor illusion": 0, "shocking grasp": 0, "guidance": 0,
    "produce flame": 0, "vicious mockery": 0, "friends": 0,
    # Nível 1
    "magic missile": 1, "cure wounds": 1, "healing word": 1, "bless": 1,
    "shield of faith": 1, "fog cloud": 1, "sleep": 1, "burning hands": 1,
    "mage armor": 1, "shield": 1, "hex": 1, "charm person": 1,
    "feather fall": 1, "detect magic": 1, "identify": 1, "thunderwave": 1,
    "entangle": 1, "speak with animals": 1, "divine favor": 1, "hunters mark": 1,
    "hunter's mark": 1, "inflict wounds": 1, "guiding bolt": 1,
    # Nível 2
    "misty step": 2, "invisibility": 2, "mirror image": 2, "suggestion": 2,
    "spider climb": 2, "hold person": 2, "spiritual weapon": 2, "aid": 2,
    "enhance ability": 2, "pass without trace": 2, "silence": 2, "web": 2,
    "darkness": 2, "blur": 2, "locate object": 2, "lesser restoration": 2,
    # Nível 3
    "fireball": 3, "lightning bolt": 3, "counterspell": 3, "fly": 3,
    "dispel magic": 3, "slow": 3, "haste": 3, "fear": 3, "hypnotic pattern": 3,
    "mass healing word": 3, "call lightning": 3, "erupting earth": 3,
    "bestow curse": 3, "vampiric touch": 3, "animate dead": 3,
    # Nível 4
    "greater invisibility": 4, "polymorph": 4, "banishment": 4,
    "dimension door": 4, "stone shape": 4, "confusion": 4,
    "ice storm": 4, "wall of fire": 4, "blight": 4,
    # Nível 5
    "cloudkill": 5, "cone of cold": 5, "hold monster": 5, "telekinesis": 5,
    "wall of force": 5, "animate objects": 5, "mass cure wounds": 5,
    "raise dead": 5, "planar binding": 5, "conjure elemental": 5,
    # Nível 6+
    "disintegrate": 6, "chain lightning": 6, "flesh to stone": 6,
    "heal": 6, "true seeing": 6, "word of recall": 6,
    "teleport": 7, "plane shift": 7, "regenerate": 7, "reverse gravity": 7,
    "abi-dalzim's horrid wilting": 8, "mind blank": 8, "power word stun": 8,
    "true resurrection": 9, "wish": 9, "power word kill": 9, "foresight": 9,
}

# ── Tradução PT→EN para busca de armas no Open5e ────────────────────────────
WEAPON_PT_TO_EN: dict[str, str] = {
    "espada longa":        "longsword",
    "espada curta":        "shortsword",
    "espada grande":       "greatsword",
    "machado":             "handaxe",
    "machado de mão":      "handaxe",
    "machado grande":      "greataxe",
    "machado de batalha":  "battleaxe",
    "adaga":               "dagger",
    "arco curto":          "shortbow",
    "arco longo":          "longbow",
    "besta leve":          "light crossbow",
    "besta de mão":        "hand crossbow",
    "besta pesada":        "heavy crossbow",
    "lança":               "spear",
    "alabarda":            "halberd",
    "maça":                "mace",
    "martelo de guerra":   "warhammer",
    "martelo de mão":      "light hammer",
    "cajado":              "quarterstaff",
    "bastão":              "quarterstaff",
    "bastão druídico":     "quarterstaff",
    "funda":               "sling",
    "javelin":             "javelin",
    "lança curta":         "javelin",
    "tridente":            "trident",
    "cimitarra":           "scimitar",
    "foice":               "sickle",
    "chicote":             "whip",
    "rapieira":            "rapier",
    "florete":             "rapier",
    "clava":               "club",
    "porrete":             "club",
    "bordão":              "quarterstaff",
    "dardos":              "dart",
    "faca":                "dagger",
}

# ── Tradução PT→EN para busca de raças no Open5e ─────────────────────────────
RACE_PT_TO_EN: dict[str, str] = {
    "humano":    "human",
    "elfo":      "elf",
    "anão":      "dwarf",
    "halfling":  "halfling",
    "draconato": "dragonborn",
    "gnomo":     "gnome",
    "meio-elfo": "half-elf",
    "meio-orc":  "half-orc",
    "tiferino":  "tiefling",
    "tiefling":  "tiefling",
    "orc":       "orc",
    "goblin":    "goblin",
}


SPELL_PT_TO_EN: dict[str, str] = {
    "bola de fogo":          "fireball",
    "míssil mágico":         "magic missile",
    "cura ferimentos":       "cure wounds",
    "palavra curativa":      "healing word",
    "bênção":                "bless",
    "escudo da fé":          "shield of faith",
    "sono":                  "sleep",
    "mãos ardentes":         "burning hands",
    "relâmpago":             "lightning bolt",
    "raio":                  "lightning bolt",
    "dissipar magia":        "dispel magic",
    "bola de fogo da magia": "fireball",
    "nuvem mortífera":       "cloudkill",
    "muralha de fogo":       "wall of fire",
    "invocar raio":          "call lightning",
    "raio de gelo":          "ray of frost",
    "chamas sagradas":       "sacred flame",
    "luz":                   "light",
    "escuridão":             "darkness",
    "voo":                   "fly",
    "invisibilidade":        "invisibility",
    "teia":                  "web",
    "névoa":                 "fog cloud",
    "emaranhar":             "entangle",
    "queda suave":           "feather fall",
    "escudo":                "shield",
    "armadura de mago":      "mage armor",
    "raio enfraquecedor":    "ray of enfeeblement",
    "encantamento":          "charm person",
    "enfeitiçar pessoa":     "charm person",
    "detectar magia":        "detect magic",
    "identificar":           "identify",
    "hex":                   "hex",
    "sentinela espiritual":  "spiritual weapon",
    "arma espiritual":       "spiritual weapon",
    "cura em massa":         "mass cure wounds",
    "reviver":               "revivify",
    "ressuscitar":           "raise dead",
    "palavra de cura em massa": "mass healing word",
    "fúria divina":          "divine smite",
    "punição divina":        "divine smite",
    "tempestade de espadas": "conjure barrage",
    "atirar múltiplo":       "conjure barrage",
    "passo da tempestade":   "thunder step",
    "portal dimensional":    "dimension door",
    "transporte via plantas":"transport via plants",
    "metamorfose":           "polymorph",
    "petrificar":            "flesh to stone",
    "nuvem de adormecimento":"sleep",
    "silêncio":              "silence",
    "auxílio":               "aid",
    "proteção contra o mal": "protection from evil and good",
    "localizar objeto":      "locate object",
}

# ── Habilidades de classe por nível (progressão automática) ─────────────────
# Apenas habilidades mecânicas significativas — o LLM narra o fluff.
CLASS_LEVEL_FEATURES: dict[str, dict[int, list[str]]] = {
    "bárbaro": {
        1:  ["Fúria", "Defesa Sem Armadura"],
        2:  ["Movimento Imprudente", "Senso de Perigo"],
        3:  ["Caminho Primitivo"],
        5:  ["Ataque Extra", "Movimento Rápido"],
        7:  ["Instinto Selvagem"],
        9:  ["Resistência Brutal"],
        11: ["Fúria Implacável"],
        15: ["Ira Persistente"],
        17: ["Fúria Devastadora"],
        18: ["Força Indômita"],
        20: ["Guerreiro Primordial"],
    },
    "guerreiro": {
        1:  ["Estilo de Combate", "Segunda Fôlego"],
        2:  ["Surto de Ação"],
        3:  ["Arquétipo Marcial"],
        5:  ["Ataque Extra"],
        9:  ["Indomável"],
        11: ["Ataque Extra Adicional"],
        17: ["Surto de Ação Adicional"],
        20: ["Campeão Eterno"],
    },
    "paladino": {
        1:  ["Sentido Divino", "Imposição de Mãos"],
        2:  ["Combate Divino", "Conjuração"],
        3:  ["Saúde Divina", "Juramento Sagrado"],
        5:  ["Ataque Extra"],
        6:  ["Aura de Proteção"],
        10: ["Aura de Coragem"],
        11: ["Golpe Divino Aprimorado"],
        14: ["Pureza do Espírito"],
        18: ["Aura Aprimorada"],
        20: ["Campeão Sagrado"],
    },
    "patrulheiro": {
        1:  ["Inimigo Favorecido", "Explorador Natural"],
        2:  ["Estilo de Combate", "Conjuração"],
        3:  ["Arquétipo do Patrulheiro", "Consciência Primitiva"],
        5:  ["Ataque Extra"],
        6:  ["Inimigo Favorecido Adicional", "Explorador Natural Adicional"],
        8:  ["Passagem pela Terra"],
        10: ["Escondes-te à Vista"],
        14: ["Desaparecer"],
        20: ["Inimigo do Inimigo"],
    },
    "bardo": {
        1:  ["Conjuração", "Inspiração Bárdica"],
        2:  ["Canção de Repouso", "Versatilidade"],
        3:  ["Colégio Bárdico", "Especialização"],
        5:  ["Inspiração Bárdica Aprimorada", "Fonte de Inspiração"],
        6:  ["Segredo da Magia"],
        10: ["Segredos Mágicos", "Inspiração Superior"],
        14: ["Segredos Mágicos Adicionais"],
        18: ["Sapiência"],
        20: ["Inspiração Superior Aprimorada"],
    },
    "clérigo": {
        1:  ["Conjuração", "Domínio Divino"],
        2:  ["Canalizar Divindade"],
        5:  ["Destruição de Mortos-Vivos"],
        8:  ["Intervenção Divina Inicial"],
        10: ["Intervenção Divina"],
        14: ["Destruição de Mortos-Vivos Aprimorada"],
        20: ["Intervenção Divina Superior"],
    },
    "druida": {
        1:  ["Druídico", "Conjuração"],
        2:  ["Forma Selvagem", "Círculo Druídico"],
        4:  ["Forma Selvagem Aprimorada"],
        6:  ["Uso de Forma Selvagem Adicional"],
        18: ["Forma Selvagem do Druida de Besta"],
        20: ["Arquidruida"],
    },
    "monge": {
        1:  ["Artes Marciais", "Defesa Sem Armadura"],
        2:  ["Ki", "Movimento Sem Armadura"],
        3:  ["Desviar Projéteis", "Tradição Monástica"],
        4:  ["Queda Lenta"],
        5:  ["Ataque Extra", "Atordoamento"],
        6:  ["Golpes Ki-Aprimorados"],
        7:  ["Evasão", "Tranquilidade"],
        9:  ["Correr Pelas Paredes"],
        10: ["Pureza de Corpo"],
        11: ["Língua do Sol e da Lua"],
        12: ["Alma do Diamante"],
        14: ["Alma Sem Idade"],
        15: ["Mente Vazia"],
        18: ["Corpo Vazio"],
        20: ["Ser Perfeito"],
    },
    "ladino": {
        1:  ["Ataque Furtivo", "Linguagem dos Ladrões", "Especialização"],
        2:  ["Ação Ardilosa"],
        3:  ["Arquétipo de Ladrão"],
        5:  ["Esquiva Incrivelmente Baixa"],
        6:  ["Especialização Adicional"],
        7:  ["Evasão"],
        11: ["Talento Confiável"],
        14: ["Visão às Cegas"],
        15: ["Mente Escorregadia"],
        18: ["Elusivo"],
        20: ["Assassino Reflexivo"],
    },
    "mago": {
        1:  ["Recuperação Arcana", "Tradição Arcana"],
        2:  ["Feitiço de Tradição"],
        6:  ["Habilidade de Tradição"],
        10: ["Habilidade de Tradição Adicional"],
        14: ["Habilidade de Tradição Superior"],
        18: ["Maestria de Feitiço"],
        20: ["Assinatura de Feitiço"],
    },
    "feiticeiro": {
        1:  ["Origem de Feiticeiro", "Conjuração"],
        2:  ["Pontos de Feitiçaria", "Metamagia"],
        3:  ["Metamagia Adicional"],
        6:  ["Habilidade de Origem"],
        14: ["Habilidade de Origem Adicional"],
        17: ["Metamagia Adicional"],
        18: ["Habilidade de Origem Superior"],
        20: ["Restauração de Feitiçaria"],
    },
    "bruxo": {
        1:  ["Patrono Sobrenatural", "Magia do Pacto"],
        2:  ["Invocações Sobrenaturais"],
        3:  ["Bênção do Pacto"],
        5:  ["Invocações Sobrenaturais Adicionais"],
        6:  ["Habilidade do Patrono"],
        7:  ["Invocações Sobrenaturais Adicionais"],
        9:  ["Invocações Sobrenaturais Adicionais"],
        10: ["Habilidade do Patrono Adicional"],
        11: ["Magia Mística"],
        14: ["Habilidade do Patrono Superior"],
        15: ["Invocações Sobrenaturais Adicionais"],
        18: ["Invocações Sobrenaturais Adicionais"],
        20: ["Mestre Sobrenatural"],
    },
    "npc": {},
}

# ── Descrições básicas para habilidades de classe automáticas ────────────────
CLASS_FEATURE_DESCS: dict[str, dict] = {
    "Ataque Extra":              {"descricao": "Pode atacar duas vezes em vez de uma quando usa a ação Atacar.", "custo_mana": 0, "dado": ""},
    "Ataque Extra Adicional":    {"descricao": "Pode atacar três vezes quando usa a ação Atacar.", "custo_mana": 0, "dado": ""},
    "Surto de Ação":             {"descricao": "Uma vez por descanso curto: toma uma ação adicional neste turno.", "custo_mana": 0, "dado": ""},
    "Surto de Ação Adicional":   {"descricao": "Pode usar Surto de Ação duas vezes por descanso curto.", "custo_mana": 0, "dado": ""},
    "Segunda Fôlego":            {"descricao": "Ação bônus: recupera 1d10 + nível de PV. 1 uso por descanso curto.", "custo_mana": 0, "dado": "1d10"},
    "Forma Selvagem":            {"descricao": "Transforma-se em besta cujo CR é até metade do nível do druida. 2 usos por descanso curto.", "custo_mana": 0, "dado": ""},
    "Fúria":                     {"descricao": "Ação bônus: +2 dano, vantagem em FOR, resistência a dano físico. Usos = 2 + nível após 3º.", "custo_mana": 0, "dado": ""},
    "Canalizar Divindade":       {"descricao": "Usa Expulsar Mortos-Vivos ou poder de domínio. 1 uso por descanso curto.", "custo_mana": 0, "dado": ""},
    "Ki":                        {"descricao": "Pool de Ki = nível do monge. Usa para Flurry of Blows, Defesa Patient, Step of the Wind.", "custo_mana": 0, "dado": ""},
    "Esquiva Incrivelmente Baixa":{"descricao": "Não pode ser surpreendido enquanto consciente. Visão dos aliados ocultos.", "custo_mana": 0, "dado": ""},
    "Evasão":                    {"descricao": "Em saving throws de DEX bem-sucedidos: nenhum dano. Em falhas: metade.", "custo_mana": 0, "dado": ""},
    "Ataque Furtivo":            {"descricao": "Dano extra 1d6 por 2 níveis ao atacar com vantagem ou aliado adjacente. 1× por turno.", "custo_mana": 0, "dado": ""},
    "Inspiração Bárdica":        {"descricao": "Ação bônus: aliado em 18m ganha 1d6 de inspiração. Escala com nível.", "custo_mana": 0, "dado": ""},
    "Imposição de Mãos":         {"descricao": "Pool de cura = nível × 5 PV. Gasta 5 PV para curar ou neutralizar veneno.", "custo_mana": 0, "dado": ""},
    "Pontos de Feitiçaria":      {"descricao": "Pool = nível do feiticeiro. Usado para Metamagia e recuperar slots.", "custo_mana": 0, "dado": ""},
    "Invocações Sobrenaturais":  {"descricao": "Aprende invocações que concedem habilidades passivas ou magias.", "custo_mana": 0, "dado": ""},
    "Magia Mística":             {"descricao": "Ganha 1 magia de qualquer lista. Slot separado recuperado a cada descanso longo.", "custo_mana": 0, "dado": ""},
    "Restauração de Feitiçaria": {"descricao": "1 vez por descanso longo: recupera 4 pontos de feitiçaria.", "custo_mana": 0, "dado": ""},
    "Recuperação Arcana":        {"descricada": "Descanso curto: recupera slots totalizando ≤ metade do nível. 1 uso/descanso longo.", "custo_mana": 0, "dado": ""},
    "Especialização":            {"descricao": "Dobra o bônus de proficiência em 2 perícias ou ferramentas.", "custo_mana": 0, "dado": ""},
    "Ação Ardilosa":             {"descricao": "Ação bônus: Esconder ou Disparar (recuar sem ataque de oportunidade).", "custo_mana": 0, "dado": ""},
}


RANGED_WEAPONS = {
    "arco", "arco curto", "arco longo", "besta", "besta leve", "besta de mão",
    "besta pesada", "funda", "zarabatana", "dardo", "virote", "flecha", "shuriken",
}
FINESSE_WEAPONS = {
    "adaga", "espada curta", "rapier", "florete", "chicote", "sabre", "espada de duelo",
}
HEALING_KEYWORDS = {
    "cura", "cura ferimentos", "curar", "restaura", "restaurar",
    "palavra curativa", "imposição de mãos", "healing", "heal",
    "bênção vital", "toque do curandeiro", "word of healing",
}

def _weapon_attr(weapon_name: str, sheet: dict) -> tuple[str, int]:
    """Ranged→DEX. Finesse→max(FOR,DEX). Melee→FOR."""
    w = weapon_name.lower().strip()
    is_ranged  = any(r in w for r in RANGED_WEAPONS)
    is_finesse = any(f in w for f in FINESSE_WEAPONS)
    str_mod = _modifier(sheet.get("forca", 10))
    dex_mod = _modifier(sheet.get("destreza", 10))
    if is_ranged:
        return "destreza", dex_mod
    if is_finesse:
        return ("destreza", dex_mod) if dex_mod >= str_mod else ("forca", str_mod)
    return "forca", str_mod

def _match_ability(char: dict, name: str) -> dict | None:
    """Retorna a habilidade cujo nome bate (case-insensitive) ou None."""
    nl = name.lower().strip()
    for hab in char.get("habilidades", []):
        if hab.get("nome", "").lower().strip() == nl:
            return hab
    return None

def _is_healing_ability(hab: dict) -> bool:
    """True se a habilidade restaura vida em vez de causar dano."""
    name = hab.get("nome", "").lower()
    desc = hab.get("descricao", "").lower()
    return (
        any(k in name for k in HEALING_KEYWORDS)
        or "restaura" in desc or "cura" in desc
        or "recupera" in desc or "heal" in desc
    )

# ---------------------------------------------------------------------------
# Tabela de armaduras — usada por equip_item para recalcular CA
# dex_bonus: "full" = add all DEX mod | "cap2" = max +2 | "none" = ignore DEX
# ---------------------------------------------------------------------------

ARMOR_TABLE: dict[str, dict] = {
    # Armadura leve
    "roupa de couro":            {"ca_base": 11, "dex_bonus": "full",   "slot": "armadura"},
    "armadura de couro":         {"ca_base": 11, "dex_bonus": "full",   "slot": "armadura"},
    "armadura de couro batido":  {"ca_base": 12, "dex_bonus": "full",   "slot": "armadura"},
    "gibão de peles":            {"ca_base": 11, "dex_bonus": "full",   "slot": "armadura"},
    # Armadura média
    "corselete":                 {"ca_base": 13, "dex_bonus": "cap2",   "slot": "armadura"},
    "armadura de osso":          {"ca_base": 13, "dex_bonus": "cap2",   "slot": "armadura"},
    "armadura de escamas":       {"ca_base": 14, "dex_bonus": "cap2",   "slot": "armadura"},
    "cota de malha":             {"ca_base": 14, "dex_bonus": "cap2",   "slot": "armadura"},
    "meia armadura":             {"ca_base": 15, "dex_bonus": "cap2",   "slot": "armadura"},
    # Armadura pesada
    "armadura de aros":          {"ca_base": 14, "dex_bonus": "none",   "slot": "armadura"},
    "cota de placas":            {"ca_base": 16, "dex_bonus": "none",   "slot": "armadura"},
    "armadura de cota de malha": {"ca_base": 16, "dex_bonus": "none",   "slot": "armadura"},
    "armadura completa":         {"ca_base": 18, "dex_bonus": "none",   "slot": "armadura"},
    "armadura de placas":        {"ca_base": 18, "dex_bonus": "none",   "slot": "armadura"},
    # Escudo (bônus +2 fixo — empilha com armadura)
    "escudo":                    {"ca_base": 2,  "dex_bonus": "shield", "slot": "escudo"},
    "escudo de madeira":         {"ca_base": 2,  "dex_bonus": "shield", "slot": "escudo"},
    "escudo de metal":           {"ca_base": 2,  "dex_bonus": "shield", "slot": "escudo"},
    "escudo reforçado":          {"ca_base": 2,  "dex_bonus": "shield", "slot": "escudo"},
}

# ---------------------------------------------------------------------------
# Condições D&D 5e com efeitos mecânicos
# ---------------------------------------------------------------------------

# Efeitos suportados mecanicamente:
#   attack_disadvantage  → atacante rola com desvantagem
#   attack_advantage     → atacante rola com vantagem
#   defense_disadvantage → defensores rolam com vantagem contra este alvo
#                          (i.e. ataques CONTRA ele ganham vantagem)
#   auto_crit            → qualquer ataque corpo-a-corpo acerta automaticamente como crítico
#   check_disadvantage   → testes de atributo rolam com desvantagem

# ── Tradução PT→EN para busca de condições no Open5e ─────────────────────────
CONDITION_PT_TO_EN: dict[str, str] = {
    "cego":        "blinded",
    "enfeitiçado": "charmed",
    "surdo":       "deafened",
    "exausto":     "exhaustion",
    "assustado":   "frightened",
    "agarrado":    "grappled",
    "incapacitado":"incapacitated",
    "invisível":   "invisible",
    "paralisado":  "paralyzed",
    "petrificado": "petrified",
    "envenenado":  "poisoned",
    "caído":       "prone",
    "amedrontado": "restrained",
    "atordoado":   "stunned",
    "inconsciente":"unconscious",
}


CONDITION_EFFECTS: dict[str, dict] = {
    "cego":        {"attack_disadvantage": True, "defense_disadvantage": True},
    "envenenado":  {"attack_disadvantage": True, "check_disadvantage": True},
    "amedrontado": {"attack_disadvantage": True},
    "caído":       {"attack_disadvantage": True, "defense_disadvantage": True},
    "paralisado":  {"attack_disadvantage": True, "auto_crit": True},
    "atordoado":   {"attack_disadvantage": True, "defense_disadvantage": True},
    "invisível":   {"attack_advantage": True},
    "enfeitiçado": {},
    "agarrado":    {},
    "incapacitado":{"attack_disadvantage": True},
    "petrificado": {"attack_disadvantage": True, "defense_disadvantage": True, "auto_crit": True},
    "surdo":       {},
    "assustado":   {"attack_disadvantage": True, "check_disadvantage": True},
    "exausto":     {"attack_disadvantage": True, "check_disadvantage": True},
}


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _modifier(score: int) -> int:
    return (score - 10) // 2


def _proficiency_bonus(level: int) -> int:
    return 2 + (level - 1) // 4


def _mod_str(score: int) -> str:
    mod = _modifier(score)
    sign = "+" if mod >= 0 else ""
    return f"{score} ({sign}{mod})"


def _parse_dice(formula: str) -> tuple[int, int, int]:
    """
    Parseia fórmulas de dado com bonus opcional.
    '2d6'    → (2, 6, 0)
    '1d12+3' → (1, 12, 3)
    '2d8-1'  → (2, 8, -1)
    Fallback para (1, 6, 0) em caso de erro.
    """
    try:
        f     = formula.lower().strip().replace(" ", "")
        bonus = 0
        if "d" in f:
            d_idx = f.index("d")
            rest  = f[d_idx + 1:]       # ex: "12+3", "8-1", "6"
            if "+" in rest:
                sides_str, bonus_str = rest.split("+", 1)
                bonus = int(bonus_str)
            elif "-" in rest:
                sides_str, bonus_str = rest.split("-", 1)
                bonus = -int(bonus_str)
            else:
                sides_str = rest
            n_str = f[:d_idx]
            n     = int(n_str) if n_str else 1
            s     = int(sides_str)
            return max(1, n), max(2, s), bonus
        return 1, 6, 0
    except (ValueError, IndexError, AttributeError):
        return 1, 6, 0


def _get_char(name: str) -> tuple[dict | None, str]:
    """Retorna (char_dict, erro). char é None se não encontrado ou sem ficha."""
    char = memory.campaign["characters"].get(memory.char_key(name))
    if not char:
        return None, f"Personagem '{name}' não encontrado."
    if not char.get("sheet"):
        return None, f"'{name}' não tem ficha D&D. Use create_character_sheet primeiro."
    return char, ""


def _hp_bar(current: int, maximum: int, width: int = 10) -> str:
    pct    = current / maximum if maximum > 0 else 0
    filled = int(pct * width)
    return "▓" * filled + "░" * (width - filled)


def _get_conditions(char: dict) -> list[dict]:
    """Retorna a lista de condições ativas do personagem."""
    return char.get("sheet", {}).get("condicoes", [])


def _has_condition_effect(char: dict, effect_key: str) -> bool:
    """Verifica se alguma condição ativa possui o efeito mecânico indicado."""
    for cond in _get_conditions(char):
        name = cond.get("nome", "").lower()
        effects = CONDITION_EFFECTS.get(name, {})
        if effects.get(effect_key):
            return True
    return False


def _roll_d20_with_adv(advantage: bool, disadvantage: bool) -> tuple[int, str]:
    """
    Rola 1d20 ou 2d20 conforme vantagem/desvantagem.
    Retorna (resultado_final, texto_log).
    Se ambos estiverem ativos, cancelam-se (rola 1d20 normal).
    """
    if advantage and disadvantage:
        # Cancelam-se
        roll = random.randint(1, 20)
        return roll, f"d20={roll} (vantagem e desvantagem se cancelam)"

    if advantage:
        r1, r2 = random.randint(1, 20), random.randint(1, 20)
        best   = max(r1, r2)
        return best, f"d20 com VANTAGEM: [{r1}, {r2}] → usa **{best}**"

    if disadvantage:
        r1, r2 = random.randint(1, 20), random.randint(1, 20)
        worst  = min(r1, r2)
        return worst, f"d20 com DESVANTAGEM: [{r1}, {r2}] → usa **{worst}**"

    roll = random.randint(1, 20)
    return roll, f"d20={roll}"


def _recalculate_ca(char: dict) -> None:
    """
    Recalcula a CA do personagem com base nos equipamentos ativos.
    Hierarquia: armadura equipada > CA base (10 + DES).
    Escudo sempre soma +2.
    """
    s    = char["sheet"]
    dex  = _modifier(s["destreza"])
    equip = s.get("equipamentos", {})

    armor_name  = (equip.get("armadura") or "").lower()
    shield_name = (equip.get("escudo")   or "").lower()

    armor_data  = ARMOR_TABLE.get(armor_name)
    shield_data = ARMOR_TABLE.get(shield_name)

    if armor_data:
        dex_rule = armor_data["dex_bonus"]
        ca_base  = armor_data["ca_base"]
        if dex_rule == "full":
            new_ca = ca_base + dex
        elif dex_rule == "cap2":
            new_ca = ca_base + min(2, dex)
        else:  # "none"
            new_ca = ca_base
    else:
        # Sem armadura: CA padrão (ou Monge/Bárbaro usam regras especiais — aqui simplificado)
        new_ca = 10 + dex

    if shield_data and shield_data["dex_bonus"] == "shield":
        new_ca += shield_data["ca_base"]

    s["ca"] = new_ca


# ---------------------------------------------------------------------------
# 1. Dado
# ---------------------------------------------------------------------------

def roll_dice(sides: int, count: int = 1, modifier: int = 0) -> str:
    """
    Rola dados e retorna o resultado detalhado.
    Use para qualquer teste, ataque ou dano quando não houver ferramenta mais específica.

    Args:
        sides:    Faces do dado (2, 4, 6, 8, 10, 12, 20 ou 100).
        count:    Quantidade de dados (padrão: 1).
        modifier: Modificador fixo somado ao total (pode ser negativo).
    """
    if sides < 2:
        return "Erro: sides deve ser >= 2."
    if count < 1:
        return "Erro: count deve ser >= 1."

    rolls   = [random.randint(1, sides) for _ in range(count)]
    total   = sum(rolls) + modifier
    mod_str = (f" {'+' if modifier >= 0 else ''}{modifier}") if modifier != 0 else ""
    detail  = " + ".join(str(r) for r in rolls) if count > 1 else str(rolls[0])

    return f"🎲 {count}d{sides}{mod_str}: [{detail}]{mod_str} = **{total}**"


# ---------------------------------------------------------------------------
# 2. Criação de personagem
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Bônus de raça e dados de arma — Open5e helpers
# ---------------------------------------------------------------------------

# Bônus canônicos do SRD para fallback offline
_RACE_BONUS_FALLBACK: dict[str, dict[str, int]] = {
    "human":      {"forca":1,"destreza":1,"constituicao":1,"inteligencia":1,"sabedoria":1,"carisma":1},
    "elf":        {"destreza":2},
    "dwarf":      {"constituicao":2},
    "halfling":   {"destreza":2},
    "dragonborn": {"forca":2,"carisma":1},
    "gnome":      {"inteligencia":2},
    "half-elf":   {"carisma":2},
    "half-orc":   {"forca":2,"constituicao":1},
    "tiefling":   {"inteligencia":1,"carisma":2},
}

# Atributo D&D 5e → chave do sistema
_ATTR_MAP = {
    "strength":     "forca",
    "dexterity":    "destreza",
    "constitution": "constituicao",
    "intelligence": "inteligencia",
    "wisdom":       "sabedoria",
    "charisma":     "carisma",
}


def _fetch_race_data(race_name: str) -> dict | None:
    """Busca dados da raça no Open5e. Retorna dict com ability_bonuses e traits, ou None."""
    import requests as _req
    en_name = RACE_PT_TO_EN.get(race_name.lower(), race_name.lower())
    slug    = en_name.replace(" ", "-").replace("'", "")
    try:
        r = _req.get(f"https://api.open5e.com/v1/races/{slug}/", timeout=5)
        if r.ok and r.json().get("name"):
            return r.json()
    except Exception:
        pass
    try:
        r = _req.get("https://api.open5e.com/v1/races/",
                     params={"search": en_name, "limit": 3}, timeout=5)
        if r.ok:
            results = r.json().get("results", [])
            for res in results:
                if en_name.lower() in res.get("name","").lower():
                    return res
            if results:
                return results[0]
    except Exception:
        pass
    return None


def _apply_race_bonuses(char: dict, sheet: dict, race_name: str) -> dict[str, int]:
    """
    Aplica bônus de atributo e traços raciais ao personagem.
    Tenta Open5e primeiro; usa tabela offline como fallback.
    Retorna dict {stat: bonus} com os bônus aplicados.
    """
    en_key  = RACE_PT_TO_EN.get(race_name.lower(), race_name.lower())
    bonuses: dict[str, int] = {}
    traits:  list[str]      = []

    race_data = _fetch_race_data(race_name)

    if race_data:
        # Bônus de atributo da API
        for bonus_entry in race_data.get("ability_bonuses", []):
            attr_name = bonus_entry.get("ability_score", {}).get("name", "").lower()                         if isinstance(bonus_entry.get("ability_score"), dict)                         else bonus_entry.get("attribute", "")
            bonus_val = bonus_entry.get("bonus", 0)
            stat = _ATTR_MAP.get(attr_name.lower(), "")
            if stat and bonus_val:
                bonuses[stat] = bonuses.get(stat, 0) + bonus_val

        # Traços raciais como habilidades
        for trait in race_data.get("traits", []):
            t_name = trait.get("name", "")
            t_desc = " ".join(trait.get("desc", "").split())[:200] if trait.get("desc") else ""
            if t_name:
                traits.append({"nome": t_name, "descricao": t_desc, "custo_mana": 0, "dado": ""})
    else:
        # Fallback offline
        bonuses = _RACE_BONUS_FALLBACK.get(en_key, {})

    # Aplica bônus aos atributos da ficha
    for stat, bonus in bonuses.items():
        if stat in sheet:
            sheet[stat] += bonus

    # Recalcula stats derivados após os bônus
    sheet["vida_max"] = max(1, sheet["hit_die"] + _modifier(sheet["constituicao"]))
    sheet["vida_atual"] = sheet["vida_max"]
    sheet["ca"]        = 10 + _modifier(sheet["destreza"])

    # Adiciona traços raciais como habilidades (sem duplicar)
    existing_names = {h.get("nome","").lower() for h in char.get("habilidades", [])}
    for trait in traits:
        if trait["nome"].lower() not in existing_names:
            char.setdefault("habilidades", []).append(trait)

    return bonuses


def _fetch_weapon_data(weapon_name: str) -> tuple[int, int] | None:
    """
    Busca o dado de dano real de uma arma no Open5e.
    Retorna (n_dice, sides) ou None se não encontrar.
    Ex: "espada longa" → (1, 8)  |  "arco longo" → (1, 8)
    """
    import requests as _req
    en_name = WEAPON_PT_TO_EN.get(weapon_name.lower().strip(), weapon_name.lower().strip())
    slug    = en_name.replace(" ", "-").replace("'", "")
    try:
        r = _req.get(f"https://api.open5e.com/v1/weapons/{slug}/", timeout=4)
        if r.ok and r.json().get("damage_dice"):
            n, s, _ = _parse_dice(r.json()["damage_dice"])
            return n, s
    except Exception:
        pass
    try:
        r = _req.get("https://api.open5e.com/v1/weapons/",
                     params={"search": en_name, "limit": 3}, timeout=4)
        if r.ok:
            results = r.json().get("results", [])
            for res in results:
                if en_name.lower() in res.get("name","").lower():
                    dice = res.get("damage_dice", "")
                    if dice:
                        n, s, _ = _parse_dice(dice)
                        return n, s
    except Exception:
        pass
    return None


# ── Magias iniciais padrão por classe (fallback offline) ─────────────────────
# Cantrips (nível 0) + magias de nível 1 mais representativas do SRD.
# Usado quando Open5e não responde E o wizard não mandou lista customizada.
DEFAULT_SPELLS_BY_CLASS: dict[str, list[dict]] = {
    "mago": [
        {"nome": "Míssil Mágico",  "descricao": "[Evocação] 3 dardos de força, 1d4+1 dano cada. Automático.", "custo_mana": 4,  "dado": "1d4"},
        {"nome": "Mãos Ardentes",  "descricao": "[Evocação] Cone de 4,5m, 3d6 dano de fogo. DEX salva metade.", "custo_mana": 4,  "dado": "3d6"},
        {"nome": "Sono",           "descricao": "[Encantamento] Afeta 5d8 PV de criaturas, começando pelas mais fracas.", "custo_mana": 4, "dado": "5d8"},
        {"nome": "Prestidigitação","descricao": "[Truque] Efeitos mágicos menores: acender velas, limpar objetos, criar sons.", "custo_mana": 0,  "dado": ""},
        {"nome": "Luz",            "descricao": "[Truque de evocação] Objeto toca emite luz como tocha por 1 hora.", "custo_mana": 0,  "dado": ""},
        {"nome": "Raio de Gelo",   "descricao": "[Truque] Ataque mágico à distância: 1d8 dano de frio + velocidade -3m.", "custo_mana": 0,  "dado": "1d8"},
    ],
    "feiticeiro": [
        {"nome": "Míssil Mágico",  "descricao": "[Evocação] 3 dardos de força, 1d4+1 dano cada. Automático.", "custo_mana": 4,  "dado": "1d4"},
        {"nome": "Mãos Ardentes",  "descricao": "[Evocação] Cone de 4,5m, 3d6 dano de fogo. DEX salva metade.", "custo_mana": 4,  "dado": "3d6"},
        {"nome": "Bola de Fogo",   "descricao": "[Evocação] Esfera de 6m de raio, 8d6 dano de fogo. DEX salva metade.", "custo_mana": 12, "dado": "8d6"},
        {"nome": "Chamas Sagradas","descricao": "[Truque] Ataque de magia: 1d8 dano radiante (DEX não conta para CA).", "custo_mana": 0,  "dado": "1d8"},
        {"nome": "Luz",            "descricao": "[Truque] Objeto emite luz como tocha por 1 hora.", "custo_mana": 0,  "dado": ""},
        {"nome": "Raio de Gelo",   "descricao": "[Truque] Ataque mágico à distância: 1d8 dano de frio.", "custo_mana": 0,  "dado": "1d8"},
    ],
    "bruxo": [
        {"nome": "Golpe Místico",  "descricao": "[Truque] Ataque mágico à distância: 1d10 dano de força.", "custo_mana": 0,  "dado": "1d10"},
        {"nome": "Hex",            "descricao": "[Encantamento] Amaldiçoa alvo: +1d6 dano necrótico nos ataques. Concentração.", "custo_mana": 4,  "dado": "1d6"},
        {"nome": "Armadura do Agathys","descricao": "[Abjuração] Ganha 5 PV temporários; atacante leva 5 dano de frio.", "custo_mana": 4, "dado": ""},
        {"nome": "Ilusão Menor",   "descricao": "[Truque] Cria som ou imagem ilusória por 1 minuto.", "custo_mana": 0,  "dado": ""},
    ],
    "clérigo": [
        {"nome": "Cura Ferimentos","descricao": "[Evocação] Cura 1d8 + modificador de SAB de PV.", "custo_mana": 4,  "dado": "1d8"},
        {"nome": "Bênção",         "descricao": "[Encantamento] Até 3 criaturas ganham +1d4 em ataques e salvaguardas. Concentração.", "custo_mana": 4, "dado": "1d4"},
        {"nome": "Guia Divino",    "descricao": "[Evocação] Ataque mágico à distância: 4d6 dano radiante. Vantagem contra alvos.", "custo_mana": 4, "dado": "4d6"},
        {"nome": "Chamas Sagradas","descricao": "[Truque] Ataque de magia: 1d8 dano radiante (DEX não conta para CA).", "custo_mana": 0,  "dado": "1d8"},
        {"nome": "Orientação",     "descricao": "[Truque] Toque: criatira ganha +1d4 em um teste de atributo.", "custo_mana": 0,  "dado": "1d4"},
    ],
    "druida": [
        {"nome": "Emaranhar",      "descricao": "[Conjuração] Área de 6m quadrada emaranha criaturas. Concentração 1 min.", "custo_mana": 4,  "dado": ""},
        {"nome": "Cura Ferimentos","descricao": "[Evocação] Cura 1d8 + modificador de SAB de PV.", "custo_mana": 4,  "dado": "1d8"},
        {"nome": "Névoa",          "descricao": "[Conjuração] Nuvem de névoa 6m de raio, bloqueia visão. Concentração.", "custo_mana": 4,  "dado": ""},
        {"nome": "Produzir Chama", "descricao": "[Truque] Chama na mão: ilumina 3m ou ataca à distância por 1d8 dano de fogo.", "custo_mana": 0,  "dado": "1d8"},
        {"nome": "Orientação",     "descricao": "[Truque] Toque: criatura ganha +1d4 em um teste de atributo.", "custo_mana": 0,  "dado": "1d4"},
    ],
    "bardo": [
        {"nome": "Palavra Curativa","descricao": "[Evocação] Ação bônus: cura 1d4 + modificador de CAR de PV.", "custo_mana": 4,  "dado": "1d4"},
        {"nome": "Encantamento",   "descricao": "[Encantamento] Enfeitiça uma criatura humanóide por 1 hora. Concentração.", "custo_mana": 4, "dado": ""},
        {"nome": "Sono",           "descricao": "[Encantamento] Afeta 5d8 PV de criaturas, começando pelas mais fracas.", "custo_mana": 4,  "dado": "5d8"},
        {"nome": "Insulto Cruel",  "descricao": "[Truque] Ataque psíquico verbal: 1d4 dano psíquico + desvantagem no próximo ataque.", "custo_mana": 0, "dado": "1d4"},
        {"nome": "Luz",            "descricao": "[Truque] Objeto emite luz como tocha por 1 hora.", "custo_mana": 0,  "dado": ""},
    ],
    "paladino": [
        {"nome": "Punição Divina", "descricao": "[Evocação] Quando acerta: +2d8 dano radiante. Ação bônus. Concentração.", "custo_mana": 4,  "dado": "2d8"},
        {"nome": "Escudo da Fé",   "descricao": "[Abjuração] Alvo ganha +2 de CA. Concentração, 10 min.", "custo_mana": 4,  "dado": ""},
        {"nome": "Cura Ferimentos","descricao": "[Evocação] Cura 1d8 + modificador de CAR de PV.", "custo_mana": 4,  "dado": "1d8"},
    ],
    "patrulheiro": [
        {"nome": "Marca do Caçador","descricao": "[Adivinhação] Designa inimigo: +1d6 dano nos ataques contra ele. Concentração.", "custo_mana": 4, "dado": "1d6"},
        {"nome": "Névoa",          "descricao": "[Conjuração] Nuvem de névoa 6m de raio, bloqueia visão. Concentração.", "custo_mana": 4,  "dado": ""},
        {"nome": "Cura Ferimentos","descricao": "[Evocação] Cura 1d8 + modificador de SAB de PV.", "custo_mana": 4,  "dado": "1d8"},
    ],
}

# Classes que têm magias (para exibir o painel no wizard e aplicar defaults)
CASTER_CLASSES = {
    "mago", "feiticeiro", "bruxo", "clérigo", "druida",
    "bardo", "paladino", "patrulheiro",
}

# Mapa classe PT → slug Open5e para /v1/spelllist/
_CLASS_SLUG_MAP = {
    "mago":        "wizard",
    "feiticeiro":  "sorcerer",
    "bruxo":       "warlock",
    "clérigo":     "cleric",
    "druida":      "druid",
    "bardo":       "bard",
    "paladino":    "paladin",
    "patrulheiro": "ranger",
}


def _fetch_class_spells(classe: str, max_spell_level: int = 1) -> list[dict]:
    """
    Busca as magias de nível 0 e 1 da classe no Open5e (/v1/spells/).
    Retorna lista de dicts {nome, descricao, custo_mana, dado}.
    Usa DEFAULT_SPELLS_BY_CLASS como fallback.
    """
    import requests as _req

    en_class = _CLASS_SLUG_MAP.get(classe.lower(), "")
    if not en_class:
        return DEFAULT_SPELLS_BY_CLASS.get(classe.lower(), [])

    try:
        r = _req.get(
            "https://api.open5e.com/v1/spells/",
            params={
                "dnd_class": en_class.capitalize(),
                "spell_level__lte": max_spell_level,
                "limit": 30,
            },
            timeout=6,
        )
        if not r.ok:
            raise ValueError("API error")

        results = r.json().get("results", [])
        if not results:
            raise ValueError("Empty results")

        spells = []
        for s in results:
            lvl      = int(s.get("spell_level", 0) or 0)
            escola   = s.get("school", "")
            ritual   = " (ritual)" if s.get("ritual") else ""
            concentr = " (concentração)" if s.get("concentration") else ""
            desc_raw = s.get("desc", "")
            desc     = " ".join(desc_raw.split())[:200]

            dado = ""
            dmg  = s.get("damage", {})
            if isinstance(dmg, dict):
                dado = dmg.get("damage_dice", "") or ""

            mana = SPELL_MANA_COST.get(lvl, 4)

            spells.append({
                "nome":       s.get("name", ""),
                "descricao":  f"[{escola}{ritual}{concentr}] {desc}",
                "custo_mana": mana,
                "dado":       dado,
            })
        return spells

    except Exception:
        return DEFAULT_SPELLS_BY_CLASS.get(classe.lower(), [])


def _apply_initial_spells(
    char_obj: dict,
    classe: str,
    chosen_spells: list[str] | None = None,
) -> list[str]:
    """
    Adiciona as magias iniciais ao personagem.
    Se chosen_spells for fornecida (lista de nomes), aplica apenas essas.
    Caso contrário, aplica o conjunto padrão de DEFAULT_SPELLS_BY_CLASS.
    Não duplica magias já existentes.
    Retorna lista de nomes adicionados.
    """
    if classe.lower() not in CASTER_CLASSES:
        return []

    pool    = DEFAULT_SPELLS_BY_CLASS.get(classe.lower(), [])
    existing = {h.get("nome", "").lower() for h in char_obj.get("habilidades", [])}
    added   = []

    if chosen_spells:
        # Filtra do pool as magias escolhidas pelo jogador
        selected = {s.lower() for s in chosen_spells}
        to_add   = [s for s in pool if s["nome"].lower() in selected]
    else:
        to_add = pool  # Aplica tudo do default

    for spell in to_add:
        if spell["nome"].lower() not in existing:
            char_obj["habilidades"].append({**spell})
            added.append(spell["nome"])

    return added


def create_character_sheet(
    name: str,
    classe: str,
    raca: str,
    forca: int,
    destreza: int,
    constituicao: int,
    inteligencia: int,
    sabedoria: int,
    carisma: int,
    description: str = "",
    **kwargs,
) -> str:
    """
    Cria a ficha D&D completa de um personagem. Use ao iniciar uma campanha D&D
    ou ao criar um NPC importante com regras mecânicas.

    Args:
        name:          Nome do personagem.
        classe:        Classe (bárbaro, guerreiro, mago, clérigo, ladino, paladino, etc.)
        raca:          Raça (humano, elfo, anão, halfling, tiefling, draconato, etc.)
        forca:         Valor de Força (3–20 para personagem inicial).
        destreza:      Valor de Destreza.
        constituicao:  Valor de Constituição.
        inteligencia:  Valor de Inteligência.
        sabedoria:     Valor de Sabedoria.
        carisma:       Valor de Carisma.
        description:   Descrição narrativa (aparência, história, personalidade).
    """
    classe_lower = classe.lower()
    info         = CLASS_DATA.get(classe_lower, {"hit_die": 8, "mana_per_level": 4, "mana_stat": "inteligencia", "saves": []})

    con_mod  = _modifier(constituicao)
    dex_mod  = _modifier(destreza)
    hit_die  = info["hit_die"]
    hp_max   = max(1, hit_die + con_mod)

    stat_map = {
        "forca": forca, "destreza": destreza, "constituicao": constituicao,
        "inteligencia": inteligencia, "sabedoria": sabedoria, "carisma": carisma,
    }
    mana_stat      = info.get("mana_stat")
    mana_per_level = info.get("mana_per_level", 0)
    if mana_stat and mana_per_level > 0:
        mana_mod = _modifier(stat_map.get(mana_stat, 10))
        mana_max = max(0, mana_per_level + mana_mod)
    else:
        mana_max = 0

    sheet = {
        "classe":       classe,
        "raca":         raca,
        "nivel":        1,
        "xp":           0,
        "xp_proximo":   XP_THRESHOLDS[1],
        "forca":        forca,
        "destreza":     destreza,
        "constituicao": constituicao,
        "inteligencia": inteligencia,
        "sabedoria":    sabedoria,
        "carisma":      carisma,
        "vida_atual":   hp_max,
        "vida_max":     hp_max,
        "mana_atual":   mana_max,
        "mana_max":     mana_max,
        "ca":           10 + dex_mod,
        "proficiencia": 2,
        "hit_die":      hit_die,
        # ── Novos campos v2 ──────────────────────────────
        "ouro":                  0,
        "prata":                 0,
        "cobre":                 0,
        "equipamentos":          {"armadura": None, "escudo": None, "arma_principal": None, "amuleto": None},
        "condicoes":             [],          # lista de {"nome": str, "duracao": int|None}
        "death_saves_sucessos":  0,
        "death_saves_falhas":    0,
        # ─────────────────────────────────────────────────
    }

    char_key_val = memory.char_key(name)
    existing = memory.campaign["characters"].get(char_key_val, {})
    char_obj = {
        "name":        name,
        "description": description,
        "traits":      existing.get("traits", ""),
        "status":      "vivo",
        "notes":       existing.get("notes", ""),
        "sheet":       sheet,
        "inventario":  existing.get("inventario", []),
        "habilidades": existing.get("habilidades", []),
    }
    memory.campaign["characters"][char_key_val] = char_obj

    # Aplica bônus de raça (Open5e) — modifica sheet e adiciona traços raciais
    race_bonuses = _apply_race_bonuses(char_obj, sheet, raca)
    bonus_str = ", ".join(f"{k.upper()[:3]} +{v}" for k, v in race_bonuses.items()) if race_bonuses else "nenhum"

    # Aplica magias iniciais para classes conjuradoras (usa chosen_spells se fornecida)
    chosen = kwargs.get("initial_spells")  # lista opcional de nomes escolhidos pelo wizard
    spells_added = _apply_initial_spells(char_obj, classe, chosen_spells=chosen)
    spells_str = f"\n   ✨ Magias iniciais: {', '.join(spells_added)}" if spells_added else ""

    if not memory.campaign.get("protagonist"):
        memory.campaign["protagonist"] = name

    memory.save_campaign()
    return (
        f"✅ Ficha criada para {name}!\n"
        f"   Classe: {classe} | Raça: {raca} | Nível: 1\n"
        f"   Bônus racial: {bonus_str}{spells_str}\n"
        f"   ❤️  Vida: {sheet['vida_max']}/{sheet['vida_max']} | ✨ Mana: {sheet['mana_max']}/{sheet['mana_max']} | 🛡️  CA: {sheet['ca']}\n"
        f"   FOR {_mod_str(sheet['forca'])}  DES {_mod_str(sheet['destreza'])}  CON {_mod_str(sheet['constituicao'])}\n"
        f"   INT {_mod_str(sheet['inteligencia'])}  SAB {_mod_str(sheet['sabedoria'])}  CAR {_mod_str(sheet['carisma'])}\n"
        f"   💰 Ouro: 0 | Prata: 0 | Cobre: 0"
    )


# ---------------------------------------------------------------------------
# 3. Consulta de ficha
# ---------------------------------------------------------------------------

def get_character_sheet(name: str) -> str:
    """
    Retorna a ficha D&D completa de um personagem: atributos, vida, mana,
    habilidades, inventário, moedas, equipamentos e condições ativas.
    Use antes de qualquer teste ou ação mecânica para checar os valores corretos.

    Args:
        name: Nome do personagem.
    """
    char, err = _get_char(name)
    if not char:
        return err

    s     = char["sheet"]
    nivel = s["nivel"]
    xp    = s["xp"]
    xp_p  = s.get("xp_proximo", 300)

    habs = char.get("habilidades", [])
    hab_lines = (
        [f"  • {h['nome']} ({h['dado']}, {h['custo_mana']} mana): {h['descricao']}" for h in habs]
        if habs else ["  Nenhuma"]
    )

    inv = char.get("inventario", [])
    inv_lines = (
        [f"  • {i['nome']} x{i['qtd']}" + (f" — {i['descricao']}" if i.get("descricao") else "") for i in inv]
        if inv else ["  Vazio"]
    )

    bar = _hp_bar(s["vida_atual"], s["vida_max"])

    # Equipamentos
    equip = s.get("equipamentos", {})
    equip_parts = []
    for slot, item in equip.items():
        if item:
            equip_parts.append(f"{slot.capitalize()}: {item}")
    equip_str = ", ".join(equip_parts) if equip_parts else "Nenhum"

    # Condições
    conds = s.get("condicoes", [])
    cond_str = (
        ", ".join(
            f"{c['nome']}" + (f" ({c['duracao']} turnos)" if c.get("duracao") else "")
            for c in conds
        )
        if conds else "Nenhuma"
    )

    # Moedas
    moedas = f"💰 Ouro: {s.get('ouro', 0)} | Prata: {s.get('prata', 0)} | Cobre: {s.get('cobre', 0)}"

    # Death saves (só relevante se HP = 0)
    death_str = ""
    if s["vida_atual"] == 0:
        death_str = (
            f"\n  ☠️  Testes de Morte — ✅ Sucessos: {s.get('death_saves_sucessos', 0)}/3"
            f" | ❌ Falhas: {s.get('death_saves_falhas', 0)}/3"
        )

    return (
        f"╔══ {char['name']} — {s['classe']} {s['raca']} Nível {nivel} ══╗\n"
        f"  XP: {xp}/{xp_p}\n"
        f"  ❤️  Vida [{bar}] {s['vida_atual']}/{s['vida_max']}{death_str}\n"
        f"  ✨ Mana: {s['mana_atual']}/{s['mana_max']}   🛡️  CA: {s['ca']}   Prof: +{s['proficiencia']}\n"
        f"  ───────────────────────────────────\n"
        f"  FOR {_mod_str(s['forca'])}  DES {_mod_str(s['destreza'])}  CON {_mod_str(s['constituicao'])}\n"
        f"  INT {_mod_str(s['inteligencia'])}  SAB {_mod_str(s['sabedoria'])}  CAR {_mod_str(s['carisma'])}\n"
        f"  ───────────────────────────────────\n"
        f"  Equipamentos: {equip_str}\n"
        f"  Condições: {cond_str}\n"
        f"  {moedas}\n"
        f"  ───────────────────────────────────\n"
        f"  Habilidades:\n" + "\n".join(hab_lines) + "\n"
        f"  Inventário:\n" + "\n".join(inv_lines) + "\n"
        f"╚{'═' * 43}╝"
    )


def get_combat_status() -> str:
    """
    Mostra o status de combate de todos os personagens com ficha D&D (vivos ou inconscientes).
    Inclui condições ativas. Chame SEMPRE no início de um turno de combate para se situar.
    """
    chars_with_sheet = [
        ch for ch in memory.campaign["characters"].values()
        if ch.get("sheet") and ch.get("status") != "morto"
    ]
    if not chars_with_sheet:
        return "Nenhum personagem com ficha D&D em campo."

    lines = ["⚔️  Status de Combate:"]
    for ch in chars_with_sheet:
        s    = ch["sheet"]
        bar  = _hp_bar(s["vida_atual"], s["vida_max"])
        pct  = s["vida_atual"] / s["vida_max"] if s["vida_max"] > 0 else 0
        warn = " ⚠️ INCONSCIENTE" if s["vida_atual"] == 0 else (" ⚠️ CRÍTICO" if pct <= 0.25 else "")

        conds = s.get("condicoes", [])
        cond_tag = ""
        if conds:
            names    = ", ".join(c["nome"].capitalize() for c in conds)
            cond_tag = f"\n    🔴 Condições: {names}"

        lines.append(
            f"  {ch['name']} (Nv.{s['nivel']} {s['classe']}){warn}\n"
            f"    ❤️  [{bar}] {s['vida_atual']}/{s['vida_max']}"
            f"   ✨ {s['mana_atual']}/{s['mana_max']}"
            f"   🛡️  CA {s['ca']}{cond_tag}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. Vida e Mana
# ---------------------------------------------------------------------------

def modify_hp(char_name: str, amount: int, reason: str = "") -> str:
    """
    Modifica os pontos de vida de um personagem.
    Valor NEGATIVO = dano. Valor POSITIVO = cura.
    Atualiza o status automaticamente (vivo / inconsciente).
    Se curar alguém com HP=0, zera os contadores de testes de morte.

    Args:
        char_name: Nome do personagem.
        amount:    Quantidade (negativo = dano, positivo = cura).
        reason:    Causa (ex: 'golpe de espada', 'poção de cura', 'queda').
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    s        = char["sheet"]
    hp_antes = s["vida_atual"]
    s["vida_atual"] = max(0, min(s["vida_max"], s["vida_atual"] + amount))
    delta    = s["vida_atual"] - hp_antes

    acao       = "curou" if delta > 0 else "sofreu"
    reason_str = f" ({reason})" if reason else ""
    pct        = s["vida_atual"] / s["vida_max"] if s["vida_max"] > 0 else 0

    extra = ""
    if s["vida_atual"] == 0:
        char["status"] = "inconsciente"
        warn = " ⚠️  CAIU INCONSCIENTE!"
    elif pct <= 0.25:
        warn = " ⚠️  Estado crítico!"
    elif pct <= 0.5:
        warn = " Ferido."
    else:
        warn = ""
        if hp_antes == 0 and delta > 0:
            # Ressuscitou — zera testes de morte
            s["death_saves_sucessos"] = 0
            s["death_saves_falhas"]   = 0
            char["status"]            = "vivo"
            extra = "\n   ✅ Testes de morte resetados. Personagem estabilizado!"

    memory.save_campaign()
    return (
        f"{char['name']} {acao} {abs(delta)} pv{reason_str}.\n"
        f"❤️  Vida: {hp_antes} → {s['vida_atual']}/{s['vida_max']}{warn}{extra}"
    )


def modify_mana(char_name: str, amount: int, reason: str = "") -> str:
    """
    Modifica os pontos de mana de um personagem.
    Valor NEGATIVO = gasta. Valor POSITIVO = restaura.

    Args:
        char_name: Nome do personagem.
        amount:    Quantidade (negativo = gasta, positivo = restaura).
        reason:    Motivo (ex: 'Bola de Fogo', 'descanso curto').
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    s = char["sheet"]
    if amount < 0 and s["mana_atual"] < abs(amount):
        return (
            f"❌ {char['name']} não tem mana suficiente!\n"
            f"✨ Mana atual: {s['mana_atual']}/{s['mana_max']} (necessário: {abs(amount)})"
        )

    mana_antes    = s["mana_atual"]
    s["mana_atual"] = max(0, min(s["mana_max"], s["mana_atual"] + amount))
    acao          = "restaurou" if amount > 0 else "gastou"
    reason_str    = f" ({reason})" if reason else ""

    memory.save_campaign()
    return (
        f"{char['name']} {acao} {abs(amount)} de mana{reason_str}.\n"
        f"✨ Mana: {mana_antes} → {s['mana_atual']}/{s['mana_max']}"
    )


# ---------------------------------------------------------------------------
# 5. Testes e combate
# ---------------------------------------------------------------------------

def make_skill_check(
    char_name: str,
    attribute: str,
    difficulty: int,
    advantage: bool = False,
    disadvantage: bool = False,
) -> str:
    """
    Realiza um teste de atributo: rola 1d20 + modificador vs Classe de Dificuldade.
    Suporta Vantagem (rola 2d20, usa o maior) e Desvantagem (rola 2d20, usa o menor).
    Condições ativas (ex: Envenenado) podem forçar desvantagem automaticamente.

    Classes de Dificuldade sugeridas:
    • 5  = Trivial   • 10 = Fácil   • 15 = Médio
    • 20 = Difícil   • 25 = Muito difícil   • 30 = Quase impossível

    Args:
        char_name:    Nome do personagem.
        attribute:    Atributo: forca, destreza, constituicao, inteligencia, sabedoria ou carisma.
        difficulty:   Classe de Dificuldade (CD) a superar.
        advantage:    Se True, rola 2d20 e usa o maior.
        disadvantage: Se True, rola 2d20 e usa o menor.
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    s        = char["sheet"]
    attr_key = attribute.lower()
    if attr_key not in STAT_NAMES:
        return f"Atributo '{attribute}' inválido. Use: {', '.join(sorted(STAT_NAMES))}."

    # Condições forçam desvantagem nos testes
    if _has_condition_effect(char, "check_disadvantage"):
        disadvantage = True

    attr_val = s[attr_key]
    mod      = _modifier(attr_val)
    d20, roll_log = _roll_d20_with_adv(advantage, disadvantage)
    total    = d20 + mod
    sign     = "+" if mod >= 0 else ""

    critico       = d20 == 20
    falha_critica = d20 == 1
    sucesso       = critico or (not falha_critica and total >= difficulty)

    result = (
        f"🎲 Teste de {attribute.capitalize()} — CD {difficulty}\n"
        f"   {char['name']}: {roll_log} {sign}{mod}(mod) = **{total}**\n"
    )
    if critico:
        result += "   🌟 CRÍTICO NATURAL! Sucesso automático."
    elif falha_critica:
        result += "   💀 FALHA CRÍTICA! Falha automática."
    elif sucesso:
        result += f"   ✅ SUCESSO! ({total} ≥ CD {difficulty})"
    else:
        result += f"   ❌ FALHA. ({total} < CD {difficulty})"

    return result


def attack_roll(
    attacker_name: str,
    target_name: str,
    weapon: str,
    damage_dice_sides: int,
    damage_dice_count: int = 1,
    attack_attribute: str = "forca",
    is_proficient: bool = True,
    advantage: bool = False,
    disadvantage: bool = False,
    end_turn: bool = True,
) -> str:
    """
    Realiza um ataque completo: testa d20 contra a CA do alvo e, se acertar,
    rola o dano e aplica automaticamente ao alvo. Avança o turno ao final
    (a menos que end_turn=False para ataques extras/ações bônus).

    Suporta Vantagem/Desvantagem e aplica condições ativas automaticamente.

    Condições verificadas automaticamente:
    • Atacante Cego/Envenenado/Atordoado/etc. → desvantagem automática
    • Alvo Paralisado → ataque com vantagem + crítico automático em corpo-a-corpo
    • Alvo Cego/Caído → atacante ganha vantagem

    Args:
        attacker_name:     Nome do atacante.
        target_name:       Nome do alvo.
        weapon:            Nome da arma (ex: 'espada longa', 'arco curto', 'adaga').
        damage_dice_sides: Faces do dado de dano (ex: 8 para 1d8).
        damage_dice_count: Quantidade de dados de dano (padrão: 1).
        attack_attribute:  Atributo de ataque: 'forca' (corpo a corpo) ou 'destreza' (à distância/finesse).
        is_proficient:     Se o atacante é proficiente com a arma (padrão: True).
        advantage:         Se True, rola 2d20 e usa o maior.
        disadvantage:      Se True, rola 2d20 e usa o menor.
        end_turn:          Se True (padrão), avança o turno automaticamente.
                           Passe False para ataques extras/ações bônus na mesma rodada.
    """
    attacker = memory.campaign["characters"].get(memory.char_key(attacker_name))
    target   = memory.campaign["characters"].get(memory.char_key(target_name))

    if not attacker or not attacker.get("sheet"):
        return f"Atacante '{attacker_name}' não encontrado ou sem ficha D&D."
    if not target or not target.get("sheet"):
        return f"Alvo '{target_name}' não encontrado ou sem ficha D&D."

    sa = attacker["sheet"]
    st = target["sheet"]

    # Se "weapon" é nome de uma habilidade da ficha do atacante, usa seus dados
    matched_hab = _match_ability(attacker, weapon)
    if matched_hab:
        hab_dado = matched_hab.get("dado", "")
        hab_mana = matched_hab.get("custo_mana", 0)
        if hab_mana > 0:
            return use_ability(attacker_name, weapon, target_name)
        if hab_dado:
            n_dice_hab, sides_hab, bonus_hab = _parse_dice(hab_dado)
            damage_dice_count = n_dice_hab
            damage_dice_sides = sides_hab
            _hab_bonus = bonus_hab
        else:
            _hab_bonus = 0
    else:
        _hab_bonus = 0

    # Auto-detecção de atributo: usa arma equipada quando weapon é nome de habilidade
    if attack_attribute.lower() == "forca":
        weapon_for_attr = weapon
        if matched_hab:
            weapon_for_attr = sa.get("equipamentos", {}).get("arma_principal", weapon) or weapon
        attack_attribute, mod = _weapon_attr(weapon_for_attr, sa)
    else:
        mod = _modifier(sa.get(attack_attribute.lower(), sa["forca"]))

    # Busca dado real da arma no Open5e (só se não veio de uma habilidade com dado próprio)
    if not matched_hab or not matched_hab.get("dado"):
        weapon_data = _fetch_weapon_data(weapon)
        if weapon_data:
            damage_dice_count, damage_dice_sides = weapon_data

    prof = sa["proficiencia"] if is_proficient else 0

    # ── Verificação automática de condições ─────────────────────────────────
    cond_notes = []

    # Atacante tem condição que força desvantagem?
    if _has_condition_effect(attacker, "attack_disadvantage"):
        active_conds = [c["nome"] for c in _get_conditions(attacker)
                        if CONDITION_EFFECTS.get(c["nome"].lower(), {}).get("attack_disadvantage")]
        disadvantage = True
        cond_notes.append(f"🔴 {attacker['name']} está {', '.join(active_conds)} → desvantagem automática")

    # Atacante tem condição que concede vantagem (ex: invisível)?
    if _has_condition_effect(attacker, "attack_advantage"):
        active_conds = [c["nome"] for c in _get_conditions(attacker)
                        if CONDITION_EFFECTS.get(c["nome"].lower(), {}).get("attack_advantage")]
        advantage = True
        cond_notes.append(f"🟢 {attacker['name']} está {', '.join(active_conds)} → vantagem automática")

    # Alvo tem condição que concede vantagem ao atacante (Cego, Paralisado, etc.)?
    if _has_condition_effect(target, "defense_disadvantage"):
        active_conds = [c["nome"] for c in _get_conditions(target)
                        if CONDITION_EFFECTS.get(c["nome"].lower(), {}).get("defense_disadvantage")]
        advantage = True
        cond_notes.append(f"🟢 {target['name']} está {', '.join(active_conds)} → atacante ganha vantagem")

    # Alvo paralisado / petrificado → crítico automático (melee implícito)
    force_crit = _has_condition_effect(target, "auto_crit")
    if force_crit:
        cond_notes.append(f"⚡ {target['name']} está paralisado/petrificado → crítico automático!")

    # ── Rolagem do ataque ───────────────────────────────────────────────────
    d20, roll_log = _roll_d20_with_adv(advantage, disadvantage)
    attack_total  = d20 + mod + prof
    target_ca     = st["ca"]
    critico       = force_crit or (d20 == 20)
    falha_critica = (not force_crit) and (d20 == 1)

    result = f"⚔️  {attacker['name']} ataca {target['name']} com {weapon}!\n"
    if cond_notes:
        result += "   " + "\n   ".join(cond_notes) + "\n"
    result += f"   {roll_log} +{mod}(mod) +{prof}(prof) = **{attack_total}** vs CA {target_ca}\n"

    if falha_critica:
        result += "   💀 ERRO CRÍTICO! O ataque falha miseravelmente."
        return result

    if critico or attack_total >= target_ca:
        n_dice = damage_dice_count * (2 if critico else 1)
        rolls  = [random.randint(1, damage_dice_sides) for _ in range(n_dice)]
        dmg    = max(1, sum(rolls) + mod + _hab_bonus)
        detail = " + ".join(str(r) for r in rolls)
        bonus_str = f" +{_hab_bonus}" if _hab_bonus > 0 else (f" {_hab_bonus}" if _hab_bonus < 0 else "")

        result += f"   {'🌟 CRÍTICO! ' if critico else ''}✅ ACERTO!\n"
        result += f"   Dano: [{detail}] +{mod}(mod){bonus_str} = **{dmg}**\n"

        hp_antes       = st["vida_atual"]
        st["vida_atual"] = max(0, st["vida_atual"] - dmg)
        hp_depois      = st["vida_atual"]
        pct            = hp_depois / st["vida_max"] if st["vida_max"] > 0 else 0

        result += f"   {target['name']}: ❤️  {hp_antes} → {hp_depois}/{st['vida_max']}"
        if hp_depois == 0:
            target["status"] = "inconsciente"
            result += " ⚠️  INCONSCIENTE!"
        elif pct <= 0.25:
            result += " ⚠️  Estado crítico!"

        memory.save_campaign()
    else:
        result += f"   ❌ ERROU! ({attack_total} < CA {target_ca})"

    if end_turn:
        result += _auto_advance_turn()
    else:
        result += "\n   ↩️  Ação bônus disponível — ataque extra pendente neste turno."
    memory.save_campaign()
    return result


# ---------------------------------------------------------------------------
# 6. Habilidades
# ---------------------------------------------------------------------------

def learn_ability(
    char_name: str,
    ability_name: str,
    description: str,
    mana_cost: int = 0,
    damage_dice: str = "1d6",
) -> str:
    """
    Ensina uma nova habilidade ao personagem (ataque especial, magia, técnica, etc.)
    Use ao criar o personagem, ao subir de nível ou ao encontrar um mentor/grimório.

    Args:
        char_name:    Nome do personagem.
        ability_name: Nome da habilidade (ex: 'Bola de Fogo', 'Golpe Poderoso').
        description:  Efeito narrativo e mecânico da habilidade.
        mana_cost:    Custo em mana por uso (0 = sem custo, usável à vontade).
        damage_dice:  Dado de efeito (ex: '2d6', '3d8', '1d4'). Padrão: '1d6'.
    """
    char = memory.campaign["characters"].get(char_name.lower())
    if not char:
        return f"Personagem '{char_name}' não encontrado."

    if "habilidades" not in char:
        char["habilidades"] = []

    existing = next((h for h in char["habilidades"] if h["nome"].lower() == ability_name.lower()), None)
    if existing:
        existing.update({"descricao": description, "custo_mana": mana_cost, "dado": damage_dice})
        memory.save_campaign()
        return f"Habilidade '{ability_name}' de {char['name']} atualizada."

    char["habilidades"].append({
        "nome":       ability_name,
        "descricao":  description,
        "custo_mana": mana_cost,
        "dado":       damage_dice,
    })
    memory.save_campaign()
    return (
        f"⚡ {char['name']} aprendeu '{ability_name}'!\n"
        f"   Dado: {damage_dice} | Custo: {mana_cost} mana\n"
        f"   Efeito: {description}"
    )


def use_ability(
    char_name: str,
    ability_name: str,
    target_name: str = "",
    saving_throw_stat: str = "",
    saving_throw_dc: int = 0,
    end_turn: bool = True,
) -> str:
    """
    Usa uma habilidade do personagem: verifica mana, desconta o custo,
    rola o dado de efeito e retorna o resultado para narrar.
    Avança o turno ao final (a menos que end_turn=False para ações bônus).

    Saving Throw (opcional): se saving_throw_stat e saving_throw_dc forem fornecidos,
    pausa o combate e aguarda o jogador rolar o teste — use resolve_saving_throw()
    depois para aplicar o dano e avançar o turno.

    Args:
        char_name:         Nome do personagem usando a habilidade.
        ability_name:      Nome exato da habilidade.
        target_name:       Nome do alvo (opcional). Se houver, aplica dano automaticamente.
        saving_throw_stat: Atributo do alvo para resistência (ex: 'destreza', 'constituicao').
        saving_throw_dc:   CD do saving throw (ex: 14). Ignorado se saving_throw_stat vazio.
        end_turn:          Se True (padrão), avança o turno ao final.
                           Passe False para habilidades de ação bônus.
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    habs = char.get("habilidades", [])
    hab  = next((h for h in habs if h["nome"].lower() == ability_name.lower()), None)
    if not hab:
        available = ", ".join(h["nome"] for h in habs) if habs else "nenhuma"
        return f"'{char_name}' não conhece '{ability_name}'. Habilidades disponíveis: {available}."

    s     = char["sheet"]
    custo = hab.get("custo_mana", 0)

    if custo > 0:
        if s["mana_atual"] < custo:
            return (
                f"❌ {char['name']} não tem mana suficiente para '{ability_name}'!\n"
                f"✨ Mana: {s['mana_atual']}/{s['mana_max']} (necessário: {custo})"
            )
        s["mana_atual"] -= custo

    n_dice, sides, bonus = _parse_dice(hab.get("dado", "1d6"))
    rolls      = [random.randint(1, sides) for _ in range(n_dice)]
    total_dano = sum(rolls) + bonus

    target_str = f" em {target_name}" if target_name else ""
    detail     = " + ".join(str(r) for r in rolls)
    bonus_str  = f" + {bonus}" if bonus > 0 else (f" - {abs(bonus)}" if bonus < 0 else "")

    result = (
        f"✨ {char['name']} usa {hab['nome']}{target_str}!\n"
        f"   Custo: {custo} mana | ✨ Mana restante: {s['mana_atual']}/{s['mana_max']}\n"
        f"   🎲 {n_dice}d{sides}: [{detail}]{bonus_str} = **{total_dano}**\n"
        f"   Efeito: {hab['descricao']}"
    )

    # ── Aplica efeito ao alvo ────────────────────────────────────────────────
    if target_name:
        target = memory.campaign["characters"].get(memory.char_key(target_name))
        if target and target.get("sheet"):
            st = target["sheet"]

            # ── MODO INTERATIVO: saving throw exigido → PAUSA, não aplica dano ──
            if saving_throw_stat and saving_throw_dc > 0:
                memory.save_campaign()
                return (
                    result +
                    f"\n\n⏸️  **AGUARDANDO TESTE DE RESISTÊNCIA**\n"
                    f"   Alvo: {target['name']}\n"
                    f"   Atributo: {saving_throw_stat.capitalize()} | CD: {saving_throw_dc}\n"
                    f"   Dano potencial (falha): **{total_dano}** | Dano reduzido (sucesso): **{total_dano // 2}**\n"
                    f"\n💬 Mestre: Role um teste de {saving_throw_stat.capitalize()} CD {saving_throw_dc}!\n"
                    f"   Após o resultado, use make_skill_check para validar e modify_hp para aplicar o dano."
                )

            # ── MODO AUTOMÁTICO: sem saving throw → aplica cura ou dano ────────
            hp_antes = st["vida_atual"]
            if _is_healing_ability(hab):
                # Habilidade de cura: soma HP sem ultrapassar o máximo
                st["vida_atual"] = min(st["vida_max"], st["vida_atual"] + total_dano)
                result += f"\n   {target['name']}: ❤️  {hp_antes} → {st['vida_atual']}/{st['vida_max']}"
                if hp_antes == 0:
                    # Estava inconsciente — estabiliza
                    target["status"] = "vivo"
                    st["death_saves_sucessos"] = 0
                    st["death_saves_falhas"]   = 0
                    result += " ✨ Estabilizado!"
                elif st["vida_atual"] == st["vida_max"]:
                    result += " ✨ Vida plena!"
            else:
                # Habilidade de dano: subtrai HP
                st["vida_atual"] = max(0, st["vida_atual"] - total_dano)
                result += f"\n   {target['name']}: ❤️  {hp_antes} → {st['vida_atual']}/{st['vida_max']}"
                if st["vida_atual"] == 0:
                    target["status"] = "inconsciente"
                    result += " ⚠️  INCONSCIENTE!"

    memory.save_campaign()
    if end_turn:
        result += _auto_advance_turn()
    else:
        result += "\n   ↩️  Ação bônus disponível — próxima habilidade/ataque neste turno."
    memory.save_campaign()
    return result


# ---------------------------------------------------------------------------
# 7. Equipamentos e CA Dinâmica  (NOVO)
# ---------------------------------------------------------------------------

def equip_item(char_name: str, item_name: str, slot: str = "") -> str:
    """
    Equipa um item de um personagem, recalculando a CA automaticamente.
    O item deve estar no inventário do personagem.

    Slots válidos: armadura, escudo, arma_principal, amuleto.
    Se o slot não for informado, a ferramenta tenta inferir pelo tipo de item.

    Armaduras pesadas ignoram o modificador de Destreza na CA.
    Armaduras médias limitam o bônus de Destreza a +2.
    Armaduras leves somam o modificador completo de Destreza.
    Escudo sempre acrescenta +2 à CA independentemente da armadura.

    Args:
        char_name: Nome do personagem.
        item_name: Nome exato do item no inventário.
        slot:      Slot de equipamento: armadura, escudo, arma_principal, amuleto.
                   Pode ser deixado vazio se óbvio pelo nome do item.
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    # Verificar se item está no inventário
    inv  = char.get("inventario", [])
    item = next((i for i in inv if i["nome"].lower() == item_name.lower()), None)
    if not item:
        return f"'{item_name}' não está no inventário de {char['name']}. Adicione com add_item primeiro."

    s     = char["sheet"]
    equip = s.setdefault("equipamentos", {"armadura": None, "escudo": None, "arma_principal": None, "amuleto": None})

    # Inferir slot se não fornecido
    item_lower  = item_name.lower()
    armor_entry = ARMOR_TABLE.get(item_lower)
    if not slot:
        if armor_entry:
            slot = armor_entry["slot"]
        elif any(w in item_lower for w in ("espada", "arco", "adaga", "lança", "maça", "machado", "cajado", "varinha")):
            slot = "arma_principal"
        elif any(w in item_lower for w in ("amuleto", "colar", "pingente")):
            slot = "amuleto"
        else:
            slot = "armadura"

    slot = slot.lower()
    valid_slots = set(equip.keys())
    if slot not in valid_slots:
        return f"Slot '{slot}' inválido. Use: {', '.join(sorted(valid_slots))}."

    ca_antes     = s["ca"]
    old_item     = equip.get(slot)
    equip[slot]  = item["nome"]

    _recalculate_ca(char)
    ca_depois = s["ca"]

    memory.save_campaign()
    swap_msg = f"(substituiu {old_item})" if old_item else ""
    return (
        f"🛡️  {char['name']} equipou '{item['nome']}' no slot [{slot}]. {swap_msg}\n"
        f"   CA: {ca_antes} → {ca_depois}"
        + (f"\n   (Armadura {'pesada — DES ignorada' if armor_entry and armor_entry.get('dex_bonus') == 'none' else 'média — DES limitada a +2' if armor_entry and armor_entry.get('dex_bonus') == 'cap2' else 'leve — DES completa' if armor_entry else ''})"
           if armor_entry and slot == "armadura" else "")
    )


def unequip_item(char_name: str, slot: str) -> str:
    """
    Remove o item equipado de um slot, recalculando a CA.

    Args:
        char_name: Nome do personagem.
        slot:      Slot a desocupar: armadura, escudo, arma_principal, amuleto.
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    s     = char["sheet"]
    equip = s.get("equipamentos", {})
    slot  = slot.lower()

    if slot not in equip:
        return f"Slot '{slot}' inválido. Use: {', '.join(sorted(equip.keys()))}."

    item_removido = equip.get(slot)
    if not item_removido:
        return f"{char['name']} não tem nada equipado no slot [{slot}]."

    ca_antes   = s["ca"]
    equip[slot] = None
    _recalculate_ca(char)
    ca_depois  = s["ca"]

    memory.save_campaign()
    return (
        f"🛡️  {char['name']} desequipou '{item_removido}' do slot [{slot}].\n"
        f"   CA: {ca_antes} → {ca_depois}"
    )


# ---------------------------------------------------------------------------
# 8. Condições e Status Temporários  (NOVO)
# ---------------------------------------------------------------------------

def apply_condition(char_name: str, condition: str, duration_turns: int = 0) -> str:
    """
    Aplica uma condição D&D a um personagem. Condições afetam rolagens automaticamente:
    Cego → desvantagem em ataques e testes; Paralisado → crítico automático para atacantes;
    Envenenado → desvantagem em ataques e testes; Invisível → vantagem em ataques.

    Busca a descrição oficial da condição no Open5e (SRD). Usa texto interno como fallback.

    Args:
        char_name:      Nome do personagem.
        condition:      Nome da condição (ex: 'Cego', 'Envenenado', 'Paralisado').
        duration_turns: Duração em turnos (0 = indefinida, até ser removida manualmente).
    """
    import requests as _req

    char, err = _get_char(char_name)
    if not char:
        return err

    s     = char["sheet"]
    conds = s.setdefault("condicoes", [])
    c_low = condition.lower()

    if any(c["nome"].lower() == c_low for c in conds):
        return f"⚠️  {char['name']} já possui a condição '{condition}'."

    conds.append({
        "nome":    condition.capitalize(),
        "duracao": duration_turns if duration_turns > 0 else None,
    })

    # Busca descrição oficial no Open5e
    srd_desc = ""
    en_slug  = CONDITION_PT_TO_EN.get(c_low, c_low)
    try:
        r = _req.get(f"https://api.open5e.com/v1/conditions/{en_slug}/", timeout=4)
        if r.ok:
            raw = r.json().get("desc", "")
            srd_desc = " ".join(raw.split())[:300] if raw else ""
    except Exception:
        pass

    effects    = CONDITION_EFFECTS.get(c_low, {})
    efeito_str = []
    if effects.get("attack_disadvantage"):  efeito_str.append("desvantagem em ataques")
    if effects.get("attack_advantage"):     efeito_str.append("vantagem em ataques")
    if effects.get("defense_disadvantage"): efeito_str.append("atacantes ganham vantagem")
    if effects.get("check_disadvantage"):   efeito_str.append("desvantagem em testes")
    if effects.get("auto_crit"):            efeito_str.append("crítico automático em corpo-a-corpo")

    dur_str        = f" por {duration_turns} turno(s)" if duration_turns > 0 else " (indefinidamente)"
    efeito_mecanico = f"\n   Mecânica: {', '.join(efeito_str)}." if efeito_str \
                      else "\n   (Condição narrativa — sem efeito mecânico automático.)"
    desc_oficial   = f"\n   📖 {srd_desc}" if srd_desc else ""

    memory.save_campaign()
    return (
        f"🔴 {char['name']} recebeu a condição **{condition.capitalize()}**{dur_str}."
        f"{efeito_mecanico}{desc_oficial}"
    )


def remove_condition(char_name: str, condition: str) -> str:
    """
    Remove uma condição ativa de um personagem.

    Args:
        char_name: Nome do personagem.
        condition: Nome da condição a remover (ex: 'Cego', 'Envenenado').
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    s     = char["sheet"]
    conds = s.get("condicoes", [])
    c_low = condition.lower()

    before = len(conds)
    s["condicoes"] = [c for c in conds if c["nome"].lower() != c_low]

    if len(s["condicoes"]) == before:
        return f"⚠️  {char['name']} não possui a condição '{condition}'."

    memory.save_campaign()
    return f"✅ Condição **{condition.capitalize()}** removida de {char['name']}."


# ---------------------------------------------------------------------------
# 9. Moedas  (NOVO)
# ---------------------------------------------------------------------------

def modify_currency(char_name: str, currency_type: str, amount: int) -> str:
    """
    Adiciona ou remove moedas da bolsa do personagem.
    Valor POSITIVO = recebe moedas. Valor NEGATIVO = gasta moedas.
    Use para cobrar estadias, compras de itens, recompensas de missão ou saque de baús.

    Args:
        char_name:     Nome do personagem.
        currency_type: Tipo de moeda: 'ouro', 'prata' ou 'cobre'.
        amount:        Quantidade (positivo = recebe, negativo = gasta).
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    s    = char["sheet"]
    tipo = currency_type.lower()

    if tipo not in ("ouro", "prata", "cobre"):
        return "Tipo de moeda inválido. Use: 'ouro', 'prata' ou 'cobre'."

    atual = s.get(tipo, 0)

    if amount < 0 and atual < abs(amount):
        return (
            f"❌ {char['name']} não tem {currency_type} suficiente!\n"
            f"   {currency_type.capitalize()} atual: {atual} (necessário: {abs(amount)})"
        )

    s[tipo] = max(0, atual + amount)
    acao    = "recebeu" if amount > 0 else "gastou"
    symbol  = {"ouro": "🪙", "prata": "🥈", "cobre": "🟤"}[tipo]

    memory.save_campaign()
    return (
        f"{symbol} {char['name']} {acao} {abs(amount)} {currency_type}.\n"
        f"   💰 Ouro: {s.get('ouro', 0)} | Prata: {s.get('prata', 0)} | Cobre: {s.get('cobre', 0)}"
    )


# ---------------------------------------------------------------------------
# 10. Teste de Morte  (NOVO)
# ---------------------------------------------------------------------------

def roll_death_save(char_name: str) -> str:
    """
    Realiza um Teste de Morte para um personagem com HP = 0 (inconsciente).
    Rola 1d20 limpo:
    • Natural 20: recupera 1 ponto de vida e estabiliza (testes zerados).
    • 10 ou mais: 1 sucesso (3 sucessos = estabilizado).
    • 9 ou menos: 1 falha (3 falhas = morto).
    • Natural 1: conta como 2 falhas.

    Chame esta ferramenta a cada turno enquanto o personagem estiver inconsciente
    e sem aliados para estabilizá-lo.

    Args:
        char_name: Nome do personagem inconsciente.
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    s = char["sheet"]

    if s["vida_atual"] > 0:
        return f"⚠️  {char['name']} não está inconsciente (HP: {s['vida_atual']}). Teste de Morte não aplicável."

    roll = random.randint(1, 20)

    # Natural 20: milagre — recupera 1 pv
    if roll == 20:
        s["vida_atual"]          = 1
        s["death_saves_sucessos"] = 0
        s["death_saves_falhas"]   = 0
        char["status"]            = "vivo"
        memory.save_campaign()
        return (
            f"🌟 CRÍTICO NATURAL! {char['name']} se recupera milagrosamente!\n"
            f"   d20={roll} → Recupera 1 ponto de vida e estabiliza.\n"
            f"   ❤️  Vida: 1/{s['vida_max']}"
        )

    # Natural 1: conta como 2 falhas
    if roll == 1:
        s["death_saves_falhas"] = min(3, s.get("death_saves_falhas", 0) + 2)
        falhas = s["death_saves_falhas"]
        result = (
            f"💀 FALHA CRÍTICA nos Testes de Morte! {char['name']} sofre 2 falhas!\n"
            f"   d20={roll}\n"
            f"   ✅ Sucessos: {s.get('death_saves_sucessos', 0)}/3 | ❌ Falhas: {falhas}/3"
        )
    elif roll >= 10:
        s["death_saves_sucessos"] = min(3, s.get("death_saves_sucessos", 0) + 1)
        sucessos = s["death_saves_sucessos"]
        result = (
            f"✅ Teste de Morte bem-sucedido! ({char['name']})\n"
            f"   d20={roll} ≥ 10 → 1 sucesso.\n"
            f"   ✅ Sucessos: {sucessos}/3 | ❌ Falhas: {s.get('death_saves_falhas', 0)}/3"
        )
    else:
        s["death_saves_falhas"] = min(3, s.get("death_saves_falhas", 0) + 1)
        falhas = s["death_saves_falhas"]
        result = (
            f"❌ Teste de Morte falhou. ({char['name']})\n"
            f"   d20={roll} < 10 → 1 falha.\n"
            f"   ✅ Sucessos: {s.get('death_saves_sucessos', 0)}/3 | ❌ Falhas: {falhas}/3"
        )

    # Resolução final
    if s.get("death_saves_sucessos", 0) >= 3:
        s["death_saves_sucessos"] = 0
        s["death_saves_falhas"]   = 0
        char["status"]            = "vivo"
        result += f"\n   🏥 {char['name']} ESTABILIZOU! Permanece inconsciente mas não morrerá."

    elif s.get("death_saves_falhas", 0) >= 3:
        s["death_saves_sucessos"] = 0
        s["death_saves_falhas"]   = 0
        char["status"]            = "morto"
        result += f"\n   ☠️  {char['name']} MORREU. Narre a cena de forma dramática e definitiva."

    memory.save_campaign()
    result += _auto_advance_turn()
    memory.save_campaign()
    return result


# ---------------------------------------------------------------------------
# 11. Inventário
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Detecção e identificação de itens mágicos (Open5e)
# ---------------------------------------------------------------------------

# Palavras que sugerem que um item pode ser mágico
_MAGIC_ITEM_KEYWORDS = {
    "mágico", "encantado", "amaldiçoado", "sagrado", "profano", "divino",
    "arcano", "rúnico", "élfico", "amaldiçoada", "bendito", "abençoado",
    "ancient", "legendary", "of the", "da tempestade", "do fogo", "do caos",
    "da sombra", "da luz", "da escuridão", "da morte", "da vida",
}
_MAGIC_BONUS_RE = re.compile(r'\+[1-5]\b')
_MAGIC_OF_RE    = re.compile(
    r'\b(?:espada|machado|arco|adaga|cajado|anel|amuleto|manto|armadura|elmo|luvas|botas|cinto|varinha|orbe)\s+'
    r'(?:d[aeo]|do|da|dos|das)\s+\w+',
    re.IGNORECASE,
)

def _looks_magic(item_name: str, description: str = "") -> bool:
    """True se o item parece mágico pelo nome ou descrição."""
    combined = (item_name + " " + description).lower()
    if _MAGIC_BONUS_RE.search(item_name):
        return True
    if any(kw in combined for kw in _MAGIC_ITEM_KEYWORDS):
        return True
    if _MAGIC_OF_RE.search(item_name):
        return True
    return False


def _search_open5e_item(item_name: str) -> dict | None:
    """
    Busca o item mágico no Open5e. Tenta slug exato primeiro, depois search.
    Retorna o dict do item ou None se não encontrado / API offline.
    """
    import requests as _req

    slug = item_name.lower().strip().replace(" ", "-").replace("'", "")

    try:
        # Tentativa 1: slug exato
        r = _req.get(f"https://api.open5e.com/v1/magicitems/{slug}/", timeout=5)
        if r.ok and r.json().get("name"):
            return r.json()
    except Exception:
        pass

    try:
        # Tentativa 2: busca textual
        r = _req.get(
            "https://api.open5e.com/v1/magicitems/",
            params={"search": item_name, "limit": 5},
            timeout=5,
        )
        if r.ok:
            results = r.json().get("results", [])
            if results:
                # Prioriza resultado com nome mais próximo
                item_words = set(item_name.lower().split())
                best = max(results, key=lambda x: len(item_words & set(x.get("name","").lower().split())))
                return best
    except Exception:
        pass

    return None


def identify_item(char_name: str, item_name: str) -> str:
    """
    Identifica um item mágico buscando seus dados reais no Open5e (SRD D&D 5e).
    Use quando o grupo encontrar um item desconhecido ou após usar a magia Identificar.

    Retorna raridade, tipo, propriedades, attunement e descrição completa.
    Se o item não existir no SRD, informa que é customizado/homebrew.

    Args:
        char_name: Nome do personagem que possui o item.
        item_name: Nome do item a identificar.
    """
    char = memory.campaign["characters"].get(memory.char_key(char_name))
    if not char:
        return f"Personagem '{char_name}' não encontrado."

    result = _search_open5e_item(item_name)

    if result:
        name     = result.get("name", item_name)
        rarity   = result.get("rarity", "Desconhecida")
        type_    = result.get("type", "")
        attune   = result.get("requires_attunement", "")
        desc_raw = result.get("desc", "Sem descrição disponível.")
        desc     = " ".join(desc_raw.split())[:400]

        attune_str = ""
        if attune and attune not in ("", "no", "false", False):
            attune_str = " · ⚠️ Requer sintonização"

        # Atualiza a descrição do item no inventário se já existir
        inv = char.get("inventario", [])
        for item in inv:
            if item["nome"].lower() == item_name.lower():
                item["descricao"] = f"[{rarity}] {desc[:200]}"
                item.pop("custom", None)  # Remove flag custom se era do SRD
                memory.save_campaign()
                break

        return (
            f"🔮 **{name}**\n"
            f"   Tipo: {type_} · Raridade: {rarity}{attune_str}\n"
            f"   {desc}"
        )
    else:
        nivel = char.get("sheet", {}).get("nivel", 1)
        return (
            f"⚠️ '{item_name}' não encontrado no banco D&D 5e (SRD).\n"
            f"   Este parece ser um item customizado/homebrew.\n"
            f"   Certifique-se de que seus efeitos são balanceados para "
            f"um grupo nível {nivel}. Ajuste a descrição se necessário."
        )


def add_item(char_name: str, item_name: str, quantity: int = 1, description: str = "") -> str:
    """
    Adiciona um item ao inventário do personagem (empilha se já existir).
    Se o item parecer mágico, busca automaticamente no Open5e:
    • Encontrado no SRD → usa dados reais (raridade, propriedades).
    • Não encontrado → aceita como customizado e emite aviso de balanço.

    Args:
        char_name:   Nome do personagem.
        item_name:   Nome do item (ex: 'Poção de Cura', 'Espada Longa +1').
        quantity:    Quantidade a adicionar (padrão: 1).
        description: Descrição das propriedades do item (opcional).
    """
    char = memory.campaign["characters"].get(memory.char_key(char_name))
    if not char:
        return f"Personagem '{char_name}' não encontrado."

    char.setdefault("inventario", [])
    inv = char["inventario"]

    # Verifica se o item já existe (empilha)
    existing = next((i for i in inv if i["nome"].lower() == item_name.lower()), None)
    if existing:
        existing["qtd"] += quantity
        if description:
            existing["descricao"] = description
        memory.save_campaign()
        return f"📦 {char['name']} agora tem {existing['qtd']}x {item_name}."

    # Novo item — verifica se parece mágico
    item_dict: dict = {"nome": item_name, "qtd": quantity, "descricao": description}
    warning = ""

    if _looks_magic(item_name, description):
        srd_data = _search_open5e_item(item_name)
        if srd_data:
            # Item canônico do SRD — enriquece com dados reais
            rarity   = srd_data.get("rarity", "")
            desc_raw = srd_data.get("desc", "")
            desc_srd = " ".join(desc_raw.split())[:200] if desc_raw else ""
            attune   = srd_data.get("requires_attunement", "")
            attune_s = " (requer sintonização)" if attune not in ("", "no", "false", False) else ""
            item_dict["descricao"] = f"[{rarity}{attune_s}] {desc_srd or description}"
            item_dict["custom"]    = False
        else:
            # Não encontrado no SRD — marca como customizado
            item_dict["custom"] = True
            nivel = char.get("sheet", {}).get("nivel", 1)
            warning = (
                f"\n⚠️  '{item_name}' não encontrado no banco D&D 5e (SRD). "
                f"Item adicionado como **customizado**. "
                f"Certifique-se de que seus efeitos são balanceados para um grupo nível {nivel}."
            )

    inv.append(item_dict)
    memory.save_campaign()
    return f"📦 {item_name} (×{quantity}) adicionado ao inventário de {char['name']}.{warning}"


def remove_item(char_name: str, item_name: str, quantity: int = 1) -> str:
    """
    Remove um item do inventário do personagem.

    Args:
        char_name: Nome do personagem.
        item_name: Nome do item.
        quantity:  Quantidade a remover (padrão: 1).
    """
    char = memory.campaign["characters"].get(memory.char_key(char_name))
    if not char:
        return f"Personagem '{char_name}' não encontrado."

    inv  = char.get("inventario", [])
    item = next((i for i in inv if i["nome"].lower() == item_name.lower()), None)
    if not item:
        return f"'{item_name}' não está no inventário de {char['name']}."

    if item["qtd"] <= quantity:
        inv.remove(item)
        memory.save_campaign()
        return f"🗑️  {item_name} removido do inventário de {char['name']}."

    item["qtd"] -= quantity
    memory.save_campaign()
    return f"{char['name']} agora tem {item['qtd']}x {item_name}."


def list_inventory(char_name: str) -> str:
    """
    Lista o inventário completo de um personagem, incluindo moedas e equipamentos.
    Itens customizados (não encontrados no SRD D&D 5e) são marcados com ⚠️.

    Args:
        char_name: Nome do personagem.
    """
    char = memory.campaign["characters"].get(memory.char_key(char_name))
    if not char:
        return f"Personagem '{char_name}' não encontrado."

    s   = char.get("sheet", {})
    inv = char.get("inventario", [])

    lines = [f"📦 Inventário de {char['name']}:"]

    # Moedas
    lines.append(
        f"  💰 Ouro: {s.get('ouro', 0)} | Prata: {s.get('prata', 0)} | Cobre: {s.get('cobre', 0)}"
    )

    # Equipamentos ativos
    equip   = s.get("equipamentos", {})
    equipped = [(slot, item) for slot, item in equip.items() if item]
    if equipped:
        lines.append("  ── Equipados ──")
        for slot, item in equipped:
            lines.append(f"  [⚔️  {slot}] {item}")

    # Inventário geral
    if inv:
        lines.append("  ── Itens ──")
        for item in inv:
            custom_tag = " ⚠️ [CUSTOMIZADO]" if item.get("custom") else ""
            desc = f" — {item['descricao']}" if item.get("descricao") else ""
            lines.append(f"  • {item['nome']} ×{item['qtd']}{custom_tag}{desc}")
    else:
        lines.append("  (Bolsa vazia)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 12. XP e nível
# ---------------------------------------------------------------------------

def grant_xp(char_name: str, amount: int, reason: str = "") -> str:
    """
    Concede XP ao personagem e verifica automaticamente se houve aumento de nível.
    Chame após derrotar inimigos, completar missões ou marcos narrativos importantes.

    XP sugerido por encontro:
    • Inimigo fraco (goblin, rato gigante): 25–50 XP
    • Inimigo médio (orc, guarda): 100–200 XP
    • Inimigo forte (líder, mago): 300–500 XP
    • Chefão: 800–2000 XP
    • Missão completada: 150–500 XP

    Args:
        char_name: Nome do personagem.
        amount:    Quantidade de XP a conceder.
        reason:    Motivo (ex: 'goblin derrotado', 'missão da aldeia completada').
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    s            = char["sheet"]
    s["xp"]     += amount
    reason_str   = f" ({reason})" if reason else ""
    result       = f"⭐ {char['name']} ganhou {amount} XP{reason_str}. Total: {s['xp']}"

    while s["nivel"] < 20 and s["xp"] >= XP_THRESHOLDS[s["nivel"]]:
        s["nivel"]        += 1
        s["proficiencia"]  = _proficiency_bonus(s["nivel"])

        info    = CLASS_DATA.get(s.get("classe", "").lower(), {"hit_die": 8, "mana_per_level": 0, "mana_stat": None})
        hit_die = info["hit_die"]
        con_mod = _modifier(s["constituicao"])
        hp_gain = max(1, random.randint(1, hit_die) + con_mod)
        s["vida_max"]   += hp_gain
        s["vida_atual"] += hp_gain

        mana_stat      = info.get("mana_stat")
        mana_per_level = info.get("mana_per_level", 0)
        if mana_stat and mana_per_level > 0:
            s["mana_max"]  += mana_per_level
            s["mana_atual"] = s["mana_max"]

        s["xp_proximo"] = XP_THRESHOLDS[s["nivel"]] if s["nivel"] < 20 else s["xp"]

        result += (
            f"\n🎉 LEVEL UP! {char['name']} agora é Nível {s['nivel']}!"
            f"\n   ❤️  Vida máxima: +{hp_gain} → {s['vida_max']}"
            f"\n   🛡️  Proficiência: +{s['proficiencia']}"
        )
        if mana_stat and mana_per_level > 0:
            result += f"\n   ✨ Mana máxima: +{mana_per_level} → {s['mana_max']}"

        # Aplica habilidades de classe do novo nível automaticamente
        new_feats = _apply_class_features(char, s, s["nivel"])
        if new_feats:
            result += f"\n   📖 Novas habilidades: {', '.join(new_feats)}"
        else:
            result += "\n   📖 Escolha uma nova habilidade ou magia com learn_spell() ou learn_ability()."

    if s["nivel"] < 20:
        result += f" / {s['xp_proximo']} para o próximo nível."

    memory.save_campaign()
    return result


# ---------------------------------------------------------------------------
# 13. Descanso
# ---------------------------------------------------------------------------

def short_rest(char_name: str) -> str:
    """
    Descanso curto (~1 hora): recupera metade dos hit dice em vida.
    Não restaura mana. Use após um combate que não foi devastador.

    Args:
        char_name: Nome do personagem.
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    s        = char["sheet"]
    info     = CLASS_DATA.get(s.get("classe", "").lower(), {"hit_die": 8})
    hit_die  = info.get("hit_die", 8)
    n_dice   = max(1, s["nivel"] // 2)
    con_mod  = _modifier(s["constituicao"])

    rolls      = [random.randint(1, hit_die) for _ in range(n_dice)]
    total_heal = max(n_dice, sum(rolls) + con_mod * n_dice)
    hp_antes   = s["vida_atual"]
    s["vida_atual"] = min(s["vida_max"], s["vida_atual"] + total_heal)
    hp_ganho   = s["vida_atual"] - hp_antes

    memory.save_campaign()
    return (
        f"🛌 {char['name']} faz um descanso curto.\n"
        f"   Rola {n_dice}d{hit_die}: [{' + '.join(str(r) for r in rolls)}]\n"
        f"   Cura: +{hp_ganho} pv | ❤️  Vida: {hp_antes} → {s['vida_atual']}/{s['vida_max']}"
    )


def long_rest(char_name: str) -> str:
    """
    Descanso longo (~8 horas): restaura toda a vida e toda a mana.
    Remove condições temporárias (exceto Doença e Maldição).
    Reseta os contadores de Testes de Morte.
    Use quando o grupo encontra um local seguro para dormir.

    Args:
        char_name: Nome do personagem.
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    s = char["sheet"]
    s["vida_atual"] = s["vida_max"]
    s["mana_atual"] = s["mana_max"]
    s["death_saves_sucessos"] = 0
    s["death_saves_falhas"]   = 0

    if char.get("status") in ("inconsciente", "ferido"):
        char["status"] = "vivo"

    # Remove condições temporárias (com duração definida)
    conds_antes = s.get("condicoes", [])
    # Condições sem duração (indefinidas) são mantidas; com duração são removidas
    # Exceção: "doença" e "maldição" não são curadas por descanso
    persistentes = {"doença", "maldição", "amaldiçoado"}
    s["condicoes"] = [c for c in conds_antes if c.get("duracao") is None and c["nome"].lower() not in persistentes]
    # Remover também as que tinham duração (foram expiradas pelo descanso)
    s["condicoes"] = [c for c in s["condicoes"] if c.get("duracao") is None]

    removidas = len(conds_antes) - len(s["condicoes"])
    cond_msg  = f"\n   ✅ {removidas} condição(ões) temporária(s) removida(s)." if removidas else ""

    memory.save_campaign()
    return (
        f"🌙 {char['name']} faz um descanso longo.\n"
        f"   ❤️  Vida restaurada: {s['vida_max']}/{s['vida_max']}\n"
        f"   ✨ Mana restaurada: {s['mana_max']}/{s['mana_max']}"
        f"{cond_msg}"
    )


# ---------------------------------------------------------------------------
# 14. Ajuste manual de atributos
# ---------------------------------------------------------------------------

def set_stat(char_name: str, stat_name: str, value: int) -> str:
    """
    Define manualmente um valor numérico na ficha do personagem.
    Use para ajustes de balanceamento, efeitos de magia ou equipamentos.
    Para moedas, prefira modify_currency. Para CA via armadura, prefira equip_item.

    Args:
        char_name: Nome do personagem.
        stat_name: Atributo a alterar: forca, destreza, constituicao, inteligencia,
                   sabedoria, carisma, ca, vida_max, mana_max, nivel, xp,
                   vida_atual, mana_atual, proficiencia, ouro, prata, cobre.
        value:     Novo valor inteiro.
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    VALID = {
        "forca", "destreza", "constituicao", "inteligencia", "sabedoria", "carisma",
        "ca", "vida_max", "mana_max", "nivel", "xp", "vida_atual", "mana_atual",
        "proficiencia", "ouro", "prata", "cobre",
    }
    s = char["sheet"]
    if stat_name.lower() not in VALID:
        return f"Atributo '{stat_name}' inválido. Válidos: {', '.join(sorted(VALID))}."

    old_val             = s.get(stat_name.lower(), "?")
    s[stat_name.lower()] = value
    memory.save_campaign()
    return f"✅ {char['name']}: {stat_name} {old_val} → {value}."


# ---------------------------------------------------------------------------
# 15. Sistema de Iniciativa
# ---------------------------------------------------------------------------

def _default_npc_sheet() -> dict:
    """
    Ficha mínima razoável para NPCs sem stats específicos.
    Aproxima CR 1/4 — suficiente para combate funcionar imediatamente.
    Para chefes, use create_character_sheet() ANTES de roll_initiative().
    """
    return {
        "classe":               "npc",
        "raca":                 "humano",
        "nivel":                1,
        "xp":                   0,
        "xp_proximo":           100,
        "forca":                12,
        "destreza":             12,
        "constituicao":         12,
        "inteligencia":         10,
        "sabedoria":            10,
        "carisma":              10,
        "vida_atual":           12,
        "vida_max":             12,
        "mana_atual":           0,
        "mana_max":             0,
        "ca":                   12,
        "proficiencia":         2,
        "hit_die":              8,
        "ouro":                 0,
        "prata":                0,
        "cobre":                0,
        "equipamentos":         {"armadura": None, "escudo": None, "arma_principal": None, "amuleto": None},
        "condicoes":            [],
        "death_saves_sucessos": 0,
        "death_saves_falhas":   0,
    }


def roll_initiative(characters_names: str) -> str:
    """
    Rola iniciativa para todos os participantes do combate (aliados e inimigos).
    Ordena do maior para o menor resultado e salva no combat_state.
    DEVE ser chamada no INÍCIO de todo combate.

    Para inimigos GENÉRICOS desconhecidos, cria fichas padrão automaticamente
    (HP 12, CA 12). Para CHEFES importantes, chame create_character_sheet()
    ANTES desta ferramenta para definir stats específicos.

    Args:
        characters_names: Nomes separados por vírgula. Ex: "Aria, Goblin, Orc Líder"
    """
    names = [n.strip() for n in characters_names.split(",") if n.strip()]
    if not names:
        return "⚠️ Informe ao menos um personagem."

    results      = []
    auto_created = []

    for name in names:
        key  = memory.char_key(name)
        char = memory.campaign["characters"].get(key)

        if not char:
            memory.campaign["characters"][key] = {
                "name":        name,
                "description": "NPC — registrado ao iniciar combate (ficha padrão).",
                "traits":      "",
                "status":      "inimigo",
                "notes":       "",
                "sheet":       _default_npc_sheet(),
                "inventario":  [],
                "habilidades": [],
            }
            char = memory.campaign["characters"][key]
            auto_created.append(name)
        elif char.get("sheet") is None:
            char["sheet"]       = _default_npc_sheet()
            char["inventario"]  = char.get("inventario") or []
            char["habilidades"] = char.get("habilidades") or []
            auto_created.append(name)

        dex_mod = _modifier(char["sheet"]["destreza"])
        roll    = random.randint(1, 20)
        total   = roll + dex_mod
        sign    = "+" if dex_mod >= 0 else ""
        results.append({
            "name":       name,
            "initiative": total,
            "roll":       roll,
            "mod":        dex_mod,
            "log":        f"d20={roll} {sign}{dex_mod} = **{total}**",
        })

    results.sort(key=lambda x: x["initiative"], reverse=True)

    cs = memory.campaign.setdefault("combat_state", {})
    cs["is_active"]          = True
    cs["initiative_order"]   = [r["name"] for r in results]
    cs["current_turn_index"] = 0
    cs["round"]              = 1

    memory.save_campaign()

    lines = ["⚔️  Iniciativa rolada! Ordem de combate:"]
    for i, r in enumerate(results):
        marker = " ◀ PRIMEIRO" if i == 0 else ""
        lines.append(f"  {i + 1}. {r['name']}: {r['log']}{marker}")
    lines.append(f"\n🎯 Rodada 1 — vez de: **{results[0]['name']}**")

    if auto_created:
        lines.append(
            f"\nℹ️  Ficha padrão criada para: {', '.join(auto_created)} "
            "(HP 12, CA 12). Use create_character_sheet para customizar."
        )

    return "\n".join(lines)


def next_turn() -> str:
    """
    Avança para o próximo turno na ordem de iniciativa.
    Pula AUTOMATICAMENTE personagens mortos, inconscientes ou que fugiram.
    Se todos estiverem fora de combate, encerra automaticamente.
    Chame UMA vez quando a ação de um personagem terminar — nunca duas vezes seguidas.
    """
    cs = memory.campaign.get("combat_state", {})
    if not cs.get("is_active"):
        return "⚠️ Nenhum combate ativo. Use roll_initiative para iniciar."

    order = cs.get("initiative_order", [])
    if not order:
        return "⚠️ Ordem de iniciativa vazia. Rode roll_initiative primeiro."

    OUT_OF_COMBAT = {"morto", "inconsciente", "estabilizado", "fugiu", "exilado"}

    idx       = cs.get("current_turn_index", 0)
    round_num = cs.get("round", 1)
    new_round = False
    skipped   = []

    for _ in range(len(order) + 1):
        idx += 1
        if idx >= len(order):
            idx        = 0
            round_num += 1
            new_round  = True

        current_name = order[idx]
        char         = memory.campaign["characters"].get(memory.char_key(current_name))
        status       = (char.get("status", "") if char else "").lower()

        if status in OUT_OF_COMBAT:
            skipped.append(f"{current_name} ({status})")
            continue

        cs["current_turn_index"] = idx
        cs["round"]              = round_num
        memory.save_campaign()

        skip_msg  = f"\n⏩ Pulados: {', '.join(skipped)}" if skipped else ""
        round_msg = f"\n🔔 Nova rodada! Rodada {round_num} começa." if new_round else ""
        return (
            f"⏭️  Turno avançado — Rodada {round_num}{round_msg}{skip_msg}\n"
            f"🎯 Vez de: **{current_name}**\n"
            f"   Ordem: {' → '.join(f'[{n}]' if i == idx else n for i, n in enumerate(order))}"
        )

    cs["is_active"]          = False
    cs["initiative_order"]   = []
    cs["current_turn_index"] = 0
    cs["round"]              = 1
    memory.save_campaign()
    return "🏳️  Todos os personagens estão fora de combate.\nCombate encerrado automaticamente."


def end_combat() -> str:
    """
    Encerra o combate atual, limpa a ordem de iniciativa e desativa o rastreador de turnos.
    Chame após a derrota de todos os inimigos ou fuga do combate.
    """
    cs = memory.campaign.get("combat_state", {})
    cs["is_active"]           = False
    cs["initiative_order"]    = []
    cs["current_turn_index"]  = 0
    cs["round"]               = 1
    memory.save_campaign()
    return "🏳️  Combate encerrado. Iniciativa e rastreador de turnos limpos."


# ---------------------------------------------------------------------------
# Macro-tool: Resolução de Saving Throw Interativo
# ---------------------------------------------------------------------------

def resolve_saving_throw(
    target_name: str,
    attribute: str,
    dc: int,
    player_roll: int,
    damage_if_fail: int,
) -> str:
    """
    Resolve um Saving Throw interativo após o jogador informar o resultado do dado.
    Aplica o dano correto (total se falhar, metade se passar) e avança o turno.

    Use esta ferramenta APÓS o jogador responder à pergunta "Role um teste de X CD Y!".
    Ela substitui a sequência make_skill_check + modify_hp + next_turn().

    Args:
        target_name:     Nome do personagem que está resistindo (geralmente o jogador).
        attribute:       Atributo do saving throw (ex: 'destreza', 'constituicao').
        dc:              Classe de Dificuldade do efeito (ex: 14).
        player_roll:     Valor TOTAL informado pelo jogador (dado + modificador já somados).
        damage_if_fail:  Dano total caso o saving throw falhe.
    """
    char, err = _get_char(target_name)
    if not char:
        return err

    s          = char["sheet"]
    attr_key   = attribute.lower()
    mod        = _modifier(s.get(attr_key, 10))
    passou     = player_roll >= dc
    dano_real  = damage_if_fail // 2 if passou else damage_if_fail

    sign       = "+" if mod >= 0 else ""
    resultado  = "✅ PASSOU" if passou else "❌ FALHOU"
    reducao    = " (metade do dano)" if passou else " (dano completo)"

    result = (
        f"🎲 Saving Throw — {char['name']} ({attribute.capitalize()} CD {dc})\n"
        f"   Resultado informado: **{player_roll}** {sign}{mod}(mod) vs CD {dc} → {resultado}\n"
        f"   Dano aplicado: **{dano_real}**{reducao}\n"
    )

    hp_antes        = s["vida_atual"]
    s["vida_atual"] = max(0, s["vida_atual"] - dano_real)
    hp_depois       = s["vida_atual"]
    pct             = hp_depois / s["vida_max"] if s["vida_max"] > 0 else 0

    result += f"   {char['name']}: ❤️  {hp_antes} → {hp_depois}/{s['vida_max']}"
    if hp_depois == 0:
        char["status"] = "inconsciente"
        result += " ⚠️  CAIU INCONSCIENTE!"
    elif pct <= 0.25:
        result += " ⚠️  Estado crítico!"

    memory.save_campaign()
    result += _auto_advance_turn()
    memory.save_campaign()
    return result


# ---------------------------------------------------------------------------
# Lista exportável para tools.py
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Balanceamento de encontros — D&D 5e (DMG p.82 e p.274)
# ---------------------------------------------------------------------------

_XP_THRESHOLDS = {
    1:  (25,50,75,100),      2:  (50,100,150,200),
    3:  (75,150,225,400),    4:  (125,250,375,500),
    5:  (250,500,750,1100),  6:  (300,600,900,1400),
    7:  (350,750,1100,1700), 8:  (450,900,1400,2100),
    9:  (550,1100,1600,2400),10: (600,1200,1900,2800),
    11: (800,1600,2400,3600),12: (1000,2000,3000,4500),
    13: (1100,2200,3400,5100),14:(1250,2500,3800,5700),
    15: (1400,2800,4300,6400),16:(1600,3200,4800,7200),
    17: (2000,3900,5900,8800),18:(2100,4200,6300,9500),
    19: (2400,4900,7300,10900),20:(2800,5700,8500,12700),
}

_CR_XP = {
    0:10, 0.125:25, 0.25:50, 0.5:100,
    1:200, 2:450, 3:700, 4:1100, 5:1800,
    6:2300, 7:2900, 8:3900, 9:5000, 10:5900,
    11:7200, 12:8400, 13:10000, 14:11500, 15:13000,
    16:15000, 17:18000, 18:20000, 19:22000, 20:25000,
}

_CR_STATS = {
    0:    {"hp":4,  "ca":12,"atk":2,"dmg":"1d4",    "f":8, "d":10,"c":10,"i":6, "w":10,"ch":6},
    0.125:{"hp":11, "ca":13,"atk":3,"dmg":"1d6+1",  "f":10,"d":12,"c":10,"i":8, "w":10,"ch":8},
    0.25: {"hp":18, "ca":13,"atk":3,"dmg":"1d6+2",  "f":12,"d":14,"c":12,"i":8, "w":11,"ch":8},
    0.5:  {"hp":30, "ca":13,"atk":3,"dmg":"1d8+2",  "f":13,"d":13,"c":13,"i":10,"w":10,"ch":10},
    1:    {"hp":45, "ca":13,"atk":4,"dmg":"2d6+2",  "f":14,"d":12,"c":14,"i":10,"w":12,"ch":10},
    2:    {"hp":65, "ca":13,"atk":4,"dmg":"2d6+3",  "f":16,"d":12,"c":14,"i":10,"w":12,"ch":11},
    3:    {"hp":85, "ca":13,"atk":4,"dmg":"2d8+3",  "f":16,"d":14,"c":15,"i":12,"w":12,"ch":12},
    4:    {"hp":105,"ca":14,"atk":5,"dmg":"2d10+3", "f":17,"d":14,"c":16,"i":12,"w":13,"ch":12},
    5:    {"hp":130,"ca":15,"atk":6,"dmg":"3d8+4",  "f":18,"d":14,"c":17,"i":12,"w":14,"ch":13},
    6:    {"hp":155,"ca":15,"atk":6,"dmg":"3d10+4", "f":18,"d":14,"c":18,"i":12,"w":14,"ch":14},
    7:    {"hp":180,"ca":15,"atk":6,"dmg":"4d8+4",  "f":19,"d":14,"c":18,"i":14,"w":14,"ch":14},
    8:    {"hp":205,"ca":16,"atk":7,"dmg":"4d10+5", "f":20,"d":14,"c":19,"i":14,"w":15,"ch":15},
    9:    {"hp":230,"ca":16,"atk":7,"dmg":"5d8+5",  "f":20,"d":14,"c":19,"i":14,"w":15,"ch":16},
    10:   {"hp":255,"ca":17,"atk":7,"dmg":"5d10+5", "f":21,"d":14,"c":20,"i":14,"w":16,"ch":16},
    11:   {"hp":280,"ca":17,"atk":8,"dmg":"6d8+5",  "f":22,"d":14,"c":20,"i":16,"w":16,"ch":17},
    12:   {"hp":305,"ca":17,"atk":8,"dmg":"6d10+6", "f":22,"d":14,"c":21,"i":16,"w":17,"ch":17},
    13:   {"hp":330,"ca":18,"atk":8,"dmg":"7d8+6",  "f":23,"d":14,"c":21,"i":16,"w":17,"ch":18},
    14:   {"hp":355,"ca":18,"atk":8,"dmg":"7d10+6", "f":23,"d":14,"c":22,"i":16,"w":18,"ch":18},
    15:   {"hp":380,"ca":18,"atk":8,"dmg":"8d8+7",  "f":24,"d":14,"c":22,"i":16,"w":18,"ch":19},
    16:   {"hp":400,"ca":18,"atk":9,"dmg":"8d10+7", "f":24,"d":14,"c":23,"i":18,"w":18,"ch":19},
    17:   {"hp":445,"ca":19,"atk":10,"dmg":"9d10+7","f":25,"d":14,"c":23,"i":18,"w":19,"ch":20},
    18:   {"hp":478,"ca":19,"atk":10,"dmg":"10d10+8","f":26,"d":14,"c":24,"i":18,"w":19,"ch":20},
    19:   {"hp":511,"ca":19,"atk":11,"dmg":"11d10+8","f":27,"d":14,"c":24,"i":18,"w":20,"ch":21},
    20:   {"hp":544,"ca":19,"atk":11,"dmg":"12d10+8","f":28,"d":14,"c":25,"i":18,"w":20,"ch":22},
}

_MONSTER_FLAVORS = {
    0:    ["rato comum","morcego","vagabundo"],
    0.125:["bandido raso","kobold","cultista novato"],
    0.25: ["goblin","esqueleto","lobo","zumbi","acólito"],
    0.5:  ["orc","hobgoblin","gnoll","espadachim","lobo enorme"],
    1:    ["bugbear","ogro pequeno","espião","cultista de elite"],
    2:    ["ogro","sahuagin","cavaleiro","mago aprendiz","centauro"],
    3:    ["manticora","mago","líder bandido","minotauro","wyvern jovem"],
    4:    ["assassino","draco-tartaruga","gigante das colinas"],
    5:    ["troll","gigante de pedra","mago veterano"],
    6:    ["ciclope","dragão jovem branco","lich aprendiz"],
    7:    ["gigante das nuvens","dragão prata jovem"],
    8:    ["hidra","archmago","gigante do gelo"],
    9:    ["lich menor","gigante de fogo","dragão adulto branco"],
    10:   ["deva","dragão adulto rubro","demônio chefe"],
    11:   ["djinn","dragão adulto bronze","beholder"],
    12:   ["arcimago veterano","dragão adulto verde","marilith"],
    13:   ["beholder antigo","dragão adulto azul","rakshasa"],
    14:   ["dragão adulto vermelho","lich poderoso"],
    15:   ["mestre lich","dragão anciente jovem","demônio supremo"],
    16:   ["dragão anciente bronze","anjo solar"],
    17:   ["dragão anciente azul","leviatã"],
    18:   ["dragão anciente vermelho","guardião de plano"],
    19:   ["semideus caído","lich-rei"],
    20:   ["tarrasque","deus encarnado","rei demônio"],
}


def _enc_multiplier(count: int) -> float:
    if count <= 1:  return 1.0
    if count == 2:  return 1.5
    if count <= 6:  return 2.0
    if count <= 10: return 2.5
    if count <= 14: return 3.0
    return 4.0


def _xp_to_cr(target: float):
    return min(_CR_XP.keys(), key=lambda cr: abs(_CR_XP[cr] - target))


def _cr_label(cr) -> str:
    return {0.125:"1/8", 0.25:"1/4", 0.5:"1/2"}.get(cr, str(int(cr)))


def _enc_block(label: str, count: int, cr, budget: int) -> str:
    s  = _CR_STATS.get(cr, _CR_STATS[1])
    fl = (_MONSTER_FLAVORS.get(cr) or ["criatura genérica"])[0]
    total = int(_CR_XP[cr] * count * _enc_multiplier(count))
    diff  = total - budget
    diff_str = f"({'+' if diff>=0 else ''}{diff} XP)" if diff else "(no orçamento)"
    return (
        f"━━━ {label} ━━━\n"
        f"  {count}× **{fl.title()}** — CR {_cr_label(cr)}\n"
        f"  HP {s['hp']}  |  CA {s['ca']}  |  Ataque +{s['atk']}  |  Dano {s['dmg']}\n"
        f"  FOR {s['f']} DES {s['d']} CON {s['c']} INT {s['i']} SAB {s['w']} CAR {s['ch']}\n"
        f"  XP do encontro: {total} {diff_str}"
    )


# ---------------------------------------------------------------------------
# Progressão automática de classe — chamada pelo grant_xp
# ---------------------------------------------------------------------------

def _apply_class_features(char: dict, sheet: dict, new_level: int) -> list[str]:
    """
    Adiciona automaticamente as habilidades de classe do novo nível.
    Não duplica habilidades já existentes.
    Retorna lista de nomes adicionados.
    """
    classe   = sheet.get("classe", "").lower()
    features = CLASS_LEVEL_FEATURES.get(classe, {}).get(new_level, [])
    if not features:
        return []
    existing = {h.get("nome", "").lower() for h in char.get("habilidades", [])}
    added = []
    for feat_name in features:
        if feat_name.lower() in existing:
            continue
        desc_data = CLASS_FEATURE_DESCS.get(feat_name, {
            "descricao": f"Habilidade de {classe.capitalize()} adquirida no nível {new_level}.",
            "custo_mana": 0, "dado": "",
        })
        char.setdefault("habilidades", []).append({
            "nome":       feat_name,
            "descricao":  desc_data.get("descricao", ""),
            "custo_mana": desc_data.get("custo_mana", 0),
            "dado":       desc_data.get("dado", ""),
        })
        added.append(feat_name)
    return added


def learn_spell(char_name: str, spell_name: str) -> str:
    """
    Busca a magia no Open5e e adiciona à ficha do personagem.
    Valida classe, nível mínimo e evita duplicatas.

    Use quando o personagem sobe de nível e escolhe uma nova magia,
    ou quando aprende por item mágico, pacto ou dom narrativo.

    Args:
        char_name:  Nome do personagem.
        spell_name: Nome da magia (português ou inglês).
    """
    import requests as _req

    char, err = _get_char(char_name)
    if not char:
        return err

    sheet  = char["sheet"]
    nivel  = sheet.get("nivel", 1)

    en_query = SPELL_PT_TO_EN.get(spell_name.lower().strip(), spell_name.lower().strip())
    # Slug: "magic missile" → "magic-missile"
    slug     = en_query.lower().strip().replace(" ", "-").replace("'", "")

    try:
        # Tentativa 1: busca por slug exato (mais precisa)
        r_slug = _req.get(
            f"https://api.open5e.com/v1/spells/{slug}/",
            timeout=5,
        )
        if r_slug.ok and r_slug.json().get("name"):
            results = [r_slug.json()]
        else:
            raise ValueError("slug not found")
    except Exception:
        try:
            # Tentativa 2: busca por nome exato
            r_name = _req.get(
                "https://api.open5e.com/v1/spells/",
                params={"name": en_query.title(), "limit": 5},
                timeout=5,
            )
            results = r_name.json().get("results", []) if r_name.ok else []
            if not results:
                raise ValueError("name not found")
        except Exception:
            try:
                # Tentativa 3: busca fuzzy como fallback
                r_search = _req.get(
                    "https://api.open5e.com/v1/spells/",
                    params={"search": en_query, "limit": 10},
                    timeout=6,
                )
                if not r_search.ok:
                    raise Exception("API error")
                all_results = r_search.json().get("results", [])
                # Filtra pelo nome mais próximo para evitar resultados errados
                en_words = set(en_query.lower().split())
                results = sorted(
                    all_results,
                    key=lambda s: len(en_words & set(s.get("name","").lower().split())),
                    reverse=True,
                )[:1]
            except Exception:
                # Fallback offline
                existing = [h["nome"].lower() for h in char.get("habilidades", [])]
                if spell_name.lower() in existing:
                    return f"ℹ️ {char['name']} já conhece {spell_name}."
                char.setdefault("habilidades", []).append({
                    "nome": spell_name, "descricao": "Magia aprendida (API offline).",
                    "custo_mana": 4, "dado": "",
                })
                memory.save_campaign()
                return f"✨ {char['name']} aprendeu {spell_name}. (dados simplificados — API indisponível)"

    if not results:
        return f"❌ Magia '{spell_name}' não encontrada. Verifique o nome ou use learn_ability()."

    spell       = results[0]
    # Corrige nível com banco local quando a API retorna valor incorreto
    spell_level = SPELL_LEVEL_OVERRIDE.get(en_query.lower()) \
               or SPELL_LEVEL_OVERRIDE.get(spell.get("name","").lower()) \
               or int(spell.get("spell_level", 0) or 0)
    min_char_lv = 1 if spell_level == 0 else max(1, spell_level * 2 - 1)

    if nivel < min_char_lv:
        return (
            f"❌ {char['name']} (nv {nivel}) não pode aprender {spell_name} ainda. "
            f"Requer personagem nível {min_char_lv} (magia nível {spell_level})."
        )

    existing = [h["nome"].lower() for h in char.get("habilidades", [])]
    if spell_name.lower() in existing:
        return f"ℹ️ {char['name']} já conhece {spell_name}."

    dado  = ""
    dmg   = spell.get("damage", {})
    if isinstance(dmg, dict):
        dado = dmg.get("damage_dice", "") or ""

    desc_raw   = spell.get("desc", "Sem descrição disponível.")
    desc_clean = " ".join(desc_raw.split())[:300]
    escola     = spell.get("school", "")
    ritual     = " (ritual)"       if spell.get("ritual")        else ""
    concentr   = " (concentração)" if spell.get("concentration") else ""
    mana       = SPELL_MANA_COST.get(spell_level, 4)

    char.setdefault("habilidades", []).append({
        "nome":       spell_name,
        "descricao":  f"[{escola}{ritual}{concentr}] {desc_clean}",
        "custo_mana": mana,
        "dado":       dado,
    })
    memory.save_campaign()

    return (
        f"✨ {char['name']} aprendeu **{spell_name}** "
        f"(nível {spell_level}, {mana} mana{ritual}{concentr})!\n"
        f"   {escola} · Dado: {dado or 'sem dano direto'}"
    )


def _cr_to_open5e_str(cr: float) -> str:
    """Converte CR numérico para o formato string do Open5e (1/8, 1/4, 1/2, 1, 2...)."""
    if cr <= 0.1:    return "0"
    elif cr <= 0.15: return "1/8"
    elif cr <= 0.3:  return "1/4"
    elif cr <= 0.6:  return "1/2"
    else:            return str(max(1, int(round(cr))))


def _extract_damage_from_action(action: dict) -> str:
    """Extrai dado de dano de uma action Open5e. Tenta damage_dice, depois regex no desc."""
    import re
    # Campo direto
    dd = action.get("damage_dice") or action.get("damage_bonus") or ""
    if dd and dd != "0":
        return str(dd)
    # Extrai do texto da descrição: "Hit: 11 (2d6 + 4) bludgeoning damage"
    desc = action.get("desc", "")
    m = re.search(r'\(([0-9]+d[0-9]+(?:\s*[+\-]\s*[0-9]+)?)\)', desc)
    if m:
        return m.group(1).replace(" ", "")
    return ""


def _cr_str_to_float(cr) -> float:
    """Converte CR do Open5e (string ou número) para float."""
    FRAC = {"0": 0.0, "1/8": 0.125, "1/4": 0.25, "1/2": 0.5}
    s = str(cr).strip()
    if s in FRAC:
        return FRAC[s]
    try:
        return float(s)
    except ValueError:
        return 0.0


def _fetch_open5e_monsters(cr: float, limit: int = 15) -> list[dict]:
    """Busca monstros do Open5e com CR correto. Retorna lista vazia se falhar."""
    import requests as _req
    cr_str = _cr_to_open5e_str(cr)
    try:
        r = _req.get(
            "https://api.open5e.com/v1/monsters/",
            params={"challenge_rating": cr_str, "limit": limit},
            timeout=5,
        )
        if not r.ok:
            return []
        results = r.json().get("results", [])
        # Filtra monstros cujo CR real está próximo do solicitado
        # Tolerância: ±0.5 para CRs baixos, ±50% para CRs altos
        target = _cr_str_to_float(cr_str)
        tol    = max(0.5, target * 0.5)
        return [m for m in results if abs(_cr_str_to_float(m.get("challenge_rating", 0)) - target) <= tol]
    except Exception:
        return []


def _open5e_monster_to_block(m: dict, label: str) -> str:
    """Converte um monstro Open5e para bloco de encontro."""
    name  = m.get("name", "Monstro")
    hp    = m.get("hit_points", 10)
    ac    = m.get("armor_class", 12)
    cr    = m.get("challenge_rating", "?")
    size  = m.get("size", "")
    type_ = m.get("type", "")
    spd   = m.get("speed", {})
    spd_str = f"{spd.get('walk', 9)}m" if isinstance(spd, dict) else str(spd)
    stats = {
        "FOR": m.get("strength", 10), "DES": m.get("dexterity", 10),
        "CON": m.get("constitution", 10), "INT": m.get("intelligence", 10),
        "SAB": m.get("wisdom", 10), "CAR": m.get("charisma", 10),
    }
    stats_line = "  ".join(f"{k} {v}({_modifier(v):+d})" for k, v in stats.items())
    actions = m.get("actions", [])
    atk_line = ""
    if actions:
        atk  = actions[0]
        dado = _extract_damage_from_action(atk)
        atk_line = f"\n   ⚔️ {atk.get('name', 'Ataque')}: {dado or 'ver descrição'} dano"
    return (
        f"── {label}: **{name}** (CR {cr}) ──\n"
        f"   {size} {type_} | ❤️ {hp} HP | 🛡️ CA {ac} | 💨 {spd_str}\n"
        f"   {stats_line}{atk_line}\n"
        f"   → create_character_sheet('{name}', hp_max={hp}, ca={ac})"
    )


def suggest_encounter(party_level: int, party_size: int = 4, difficulty: str = "medium") -> str:
    """
    Sugere encontros balanceados. Busca monstros reais do Open5e (CR correto)
    e cai para tabelas internas se a API estiver indisponível.

    Use ANTES de criar inimigos para garantir desafio justo para o grupo.

    Args:
        party_level: Nível médio do grupo (1-20).
        party_size:  Quantidade de aventureiros (padrão: 4).
        difficulty:  'easy', 'medium', 'hard' ou 'deadly'.
    """
    import random as _rnd
    party_level = max(1, min(20, party_level))
    party_size  = max(1, min(8,  party_size))

    diff_map  = {"easy":0,"medium":1,"hard":2,"deadly":3}
    diff_idx  = diff_map.get(difficulty.lower(), 1)
    diff_name = ["FÁCIL","MÉDIO","DIFÍCIL","MORTAL"][diff_idx]

    per_char  = _XP_THRESHOLDS[party_level][diff_idx]
    budget    = per_char * party_size
    boss_cr   = _xp_to_cr(budget)
    mid_cr    = _xp_to_cr(budget / 2.0 / 3)
    horde_cnt = max(5, party_size + 2)
    horde_cr  = _xp_to_cr(budget / _enc_multiplier(horde_cnt) / horde_cnt)

    header = (
        f"⚔️  ENCONTRO BALANCEADO — Grupo Nv.{party_level} × {party_size}\n"
        f"Dificuldade: **{diff_name}**  |  Orçamento: {budget} XP ({per_char}/personagem)\n"
    )

    boss_list  = _fetch_open5e_monsters(boss_cr)
    mid_list   = _fetch_open5e_monsters(mid_cr)
    horde_list = _fetch_open5e_monsters(horde_cr)

    lines = [header]

    if boss_list:
        lines.append(_open5e_monster_to_block(_rnd.choice(boss_list), "OPÇÃO A — Chefão Solitário"))
    else:
        lines.append(_enc_block("OPÇÃO A — Chefão Solitário", 1, boss_cr, budget))

    lines.append("")

    if mid_list:
        m = _rnd.choice(mid_list)
        lines.append(_open5e_monster_to_block(m, f"OPÇÃO B — Bando ×3: {m.get('name','?')}"))
    else:
        lines.append(_enc_block("OPÇÃO B — Bando Médio", 3, mid_cr, budget))

    lines.append("")

    if horde_list:
        h = _rnd.choice(horde_list)
        lines.append(_open5e_monster_to_block(h, f"OPÇÃO C — Horda ×{horde_cnt}: {h.get('name','?')}"))
    else:
        lines.append(_enc_block(f"OPÇÃO C — Horda ×{horde_cnt}", horde_cnt, horde_cr, budget))

    lines += ["", "💡 Use os stats em create_character_sheet ANTES de roll_initiative.",
              "   Adapte os nomes ao tema da campanha."]
    return "\n".join(lines)


# ── Bônus de pré-requisito de nível para talentos ───────────────────────────
_FEAT_LEVEL_REQUIREMENTS: dict[str, int] = {
    "great weapon master": 4, "sharpshooter": 4, "polearm master": 4,
    "sentinel": 4, "war caster": 4, "resilient": 4, "lucky": 1,
    "alert": 1, "tough": 1, "mobile": 1, "observant": 1,
}

# ── Antecedentes do SRD com fallback offline ─────────────────────────────────
_BACKGROUND_FALLBACK: dict[str, dict] = {
    "acolyte":     {"skills": ["Insight","Religion"],       "languages": 2, "equipment": ["Holy symbol","Prayer book","5 candles"]},
    "criminal":    {"skills": ["Deception","Stealth"],      "tools": ["Thieves tools","Gaming set"], "equipment": ["Crowbar","Dark clothes"]},
    "folk hero":   {"skills": ["Animal Handling","Survival"],"tools": ["Artisan tools","Vehicles (land)"], "equipment": ["Artisan tools","Shovel"]},
    "noble":       {"skills": ["History","Persuasion"],     "languages": 1, "equipment": ["Fine clothes","Signet ring","Scroll of pedigree"]},
    "sage":        {"skills": ["Arcana","History"],         "languages": 2, "equipment": ["Bottle of ink","Quill","Small knife"]},
    "soldier":     {"skills": ["Athletics","Intimidation"], "tools": ["Gaming set","Vehicles (land)"], "equipment": ["Insignia of rank","Trophy"]},
    "charlatan":   {"skills": ["Deception","Sleight of Hand"],"tools": ["Disguise kit","Forgery kit"], "equipment": ["Fine clothes","Disguise kit"]},
    "entertainer": {"skills": ["Acrobatics","Performance"], "tools": ["Disguise kit","Musical instrument"], "equipment": ["Musical instrument","Costume"]},
    "guild artisan":{"skills": ["Insight","Persuasion"],   "tools": ["Artisan tools"], "languages": 1, "equipment": ["Artisan tools","Letter of introduction"]},
    "hermit":      {"skills": ["Medicine","Religion"],      "tools": ["Herbalism kit"], "languages": 1, "equipment": ["Scroll case","Winter blanket"]},
    "outlander":   {"skills": ["Athletics","Survival"],     "tools": ["Musical instrument"], "languages": 1, "equipment": ["Staff","Hunting trap"]},
    "sailor":      {"skills": ["Athletics","Perception"],   "tools": ["Navigators tools","Vehicles (water)"], "equipment": ["Belaying pin","50ft silk rope"]},
    "urchin":      {"skills": ["Sleight of Hand","Stealth"],"tools": ["Disguise kit","Thieves tools"], "equipment": ["Small knife","City map"]},
    # Traduções PT
    "acólito":     {"skills": ["Percepção","Religião"],     "languages": 2, "equipment": ["Símbolo sagrado","Livro de orações"]},
    "criminoso":   {"skills": ["Enganação","Furtividade"],  "tools": ["Ferramentas de ladrão"], "equipment": ["Pé-de-cabra","Roupas escuras"]},
    "herói do povo":{"skills": ["Adestrar Animais","Sobrevivência"],"equipment": ["Ferramentas de artesão","Pá"]},
    "nobre":       {"skills": ["História","Persuasão"],     "languages": 1, "equipment": ["Roupas finas","Anel de sinete"]},
    "sábio":       {"skills": ["Arcanismo","História"],     "languages": 2, "equipment": ["Tinta","Pena","Canivete"]},
    "soldado":     {"skills": ["Atletismo","Intimidação"],  "equipment": ["Insígnia de patente","Troféu de inimigo"]},
    "charlatão":   {"skills": ["Enganação","Prestidigitação"],"equipment": ["Roupas finas","Kit de disfarce"]},
    "artesão de guilda":{"skills": ["Perspicácia","Persuasão"],"languages": 1, "equipment": ["Ferramentas de artesão"]},
    "eremita":     {"skills": ["Medicina","Religião"],      "equipment": ["Estojo de pergaminhos","Cobertor de inverno"]},
    "forasteiro":  {"skills": ["Atletismo","Sobrevivência"],"languages": 1, "equipment": ["Cajado","Armadilha de caça"]},
    "marinheiro":  {"skills": ["Atletismo","Percepção"],    "equipment": ["Belaying pin","Corda 15m"]},
    "pivete":      {"skills": ["Prestidigitação","Furtividade"],"equipment": ["Canivete","Mapa da cidade"]},
}


def _fetch_background(bg_name: str) -> dict | None:
    """
    Busca um antecedente no Open5e. Retorna o dict ou None se falhar.
    Usa fallback offline automaticamente.
    """
    import requests as _req
    en_name = bg_name.lower().strip()
    slug    = en_name.replace(" ", "-").replace("'", "")
    try:
        r = _req.get(f"https://api.open5e.com/v1/backgrounds/{slug}/", timeout=5)
        if r.ok and r.json().get("name"):
            return r.json()
        r2 = _req.get("https://api.open5e.com/v1/backgrounds/",
                      params={"search": en_name, "limit": 3}, timeout=5)
        if r2.ok:
            results = r2.json().get("results", [])
            if results:
                return results[0]
    except Exception:
        pass
    return _BACKGROUND_FALLBACK.get(en_name)


def choose_feat(char_name: str, feat_name: str) -> str:
    """
    Permite ao personagem escolher um talento nos níveis 4, 8, 12, 16 ou 19,
    em vez de uma Melhoria de Atributo (+2).

    Busca o talento no Open5e, valida pré-requisitos e aplica os bônus à ficha.

    Use quando o jogador chegar em um nível de Melhoria de Atributo e escolher
    explicitamente um talento em vez do +2.

    Args:
        char_name: Nome do personagem.
        feat_name: Nome do talento em inglês (como aparece no SRD).
    """
    import requests as _req

    char, err = _get_char(char_name)
    if not char:
        return err

    sheet = char["sheet"]
    nivel = sheet.get("nivel", 1)

    # Verifica se está num nível de melhoria de atributo
    FEAT_LEVELS = {4, 8, 12, 16, 19}
    if nivel not in FEAT_LEVELS:
        return (
            f"❌ {char['name']} está no nível {nivel}. "
            f"Talentos só podem ser escolhidos nos níveis {sorted(FEAT_LEVELS)}."
        )

    # Verifica se já tem esse talento
    existing_names = {h.get("nome", "").lower() for h in char.get("habilidades", [])}
    if feat_name.lower() in existing_names:
        return f"ℹ️ {char['name']} já possui o talento '{feat_name}'."

    # Busca no Open5e
    feat_data = None
    slug      = feat_name.lower().strip().replace(" ", "-").replace("'", "")
    try:
        r = _req.get(f"https://api.open5e.com/v1/feats/{slug}/", timeout=5)
        if r.ok and r.json().get("name"):
            feat_data = r.json()
        else:
            r2 = _req.get("https://api.open5e.com/v1/feats/",
                          params={"search": feat_name, "limit": 5}, timeout=5)
            if r2.ok:
                results = r2.json().get("results", [])
                feat_words = set(feat_name.lower().split())
                best = max(results, key=lambda f: len(feat_words & set(f.get("name","").lower().split())), default=None)
                if best:
                    feat_data = best
    except Exception:
        pass

    if not feat_data:
        return (
            f"❌ Talento '{feat_name}' não encontrado no Open5e (SRD).\n"
            f"   Verifique o nome em inglês ou use learn_ability() para habilidades customizadas."
        )

    name_en  = feat_data.get("name", feat_name)
    desc_raw = feat_data.get("desc", "Sem descrição disponível.")
    desc     = " ".join(desc_raw.split())[:350]

    # Aplica bônus de atributo se o talento conceder (+1 em atributo)
    bonus_applied = []
    prereq_str    = feat_data.get("prerequisite", "")

    # Tenta extrair bônus de atributo da descrição (+1 a FOR, DEX, etc.)
    attr_map_en = {
        "strength": "forca", "dexterity": "destreza", "constitution": "constituicao",
        "intelligence": "inteligencia", "wisdom": "sabedoria", "charisma": "carisma",
    }
    import re as _re
    for en_attr, pt_attr in attr_map_en.items():
        if _re.search(rf"increase your {en_attr}.*by 1|{en_attr}.*increases? by 1", desc_raw, _re.IGNORECASE):
            if pt_attr in sheet:
                sheet[pt_attr] = min(30, sheet[pt_attr] + 1)
                bonus_applied.append(f"{pt_attr.upper()[:3]} +1")

    char.setdefault("habilidades", []).append({
        "nome":       feat_name,
        "descricao":  desc,
        "custo_mana": 0,
        "dado":       "",
    })
    memory.save_campaign()

    prereq_info = f"\n   Pré-requisito: {prereq_str}" if prereq_str else ""
    bonus_info  = f"\n   Bônus aplicado: {', '.join(bonus_applied)}" if bonus_applied else ""

    return (
        f"🌟 {char['name']} aprendeu o talento **{name_en}**!{prereq_info}{bonus_info}\n"
        f"   {desc}"
    )


DND_TOOLS = [
    suggest_encounter,
    learn_spell,
    roll_dice,
    create_character_sheet,
    get_character_sheet,
    get_combat_status,
    modify_hp,
    modify_mana,
    make_skill_check,
    attack_roll,
    learn_ability,
    use_ability,
    equip_item,
    unequip_item,
    apply_condition,
    remove_condition,
    modify_currency,
    roll_death_save,
    add_item,
    remove_item,
    list_inventory,
    identify_item,
    choose_feat,
    grant_xp,
    short_rest,
    long_rest,
    set_stat,
    # Sistema de Iniciativa (v3)
    roll_initiative,
    next_turn,
    end_combat,
    # Macro-tools (v4)
    resolve_saving_throw,
]