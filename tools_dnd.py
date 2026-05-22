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
# Mapeamento de nomes de magias/habilidades PT-BR → EN (para tolerar o AI
# chamando use_ability com nomes traduzidos em vez do nome armazenado)
# ---------------------------------------------------------------------------
_SPELL_PT_TO_EN: dict[str, str] = {
    # Cantrips
    "prestidigitação": "prestidigitation",
    "luz": "light",
    "raio de gelo": "ray of frost",
    "raio de frio": "ray of frost",
    "choque do trovão": "thunderclap",
    "choque elétrico": "shocking grasp",
    "toque gélido": "chill touch",
    "explosão eldrica": "eldritch blast",
    "chama sagrada": "sacred flame",
    "orientação": "guidance",
    "resistência": "resistance",
    "palavra de cura": "spare the dying",
    "produzir chama": "produce flame",
    "druidcraft": "druidcraft",
    "veneno aspergido": "poison spray",
    "amigos": "friends",
    "mensagem": "message",
    "ilusão menor": "minor illusion",
    "mão de mago": "mage hand",
    "dança das luzes": "dancing lights",
    "truque": "thaumaturgy",
    # Nível 1
    "míssil mágico": "magic missile",
    "missil magico": "magic missile",
    "mãos flamejantes": "burning hands",
    "maos flamejantes": "burning hands",
    "sono": "sleep",
    "escudo": "shield",
    "armadura de mago": "mage armor",
    "identificar": "identify",
    "graxa": "grease",
    "cor em spray": "color spray",
    "encantamento": "charm person",
    "enfeitiçar pessoa": "charm person",
    "emaranhar": "entangle",
    "criar ou destruir água": "create or destroy water",
    "cura de ferimentos": "cure wounds",
    "detectar magia": "detect magic",
    "disfarçar-se": "disguise self",
    "falar com animais": "speak with animals",
    "guia espiritual": "guiding bolt",
    "raio guia": "guiding bolt",
    "cura": "healing word",
    "palavra curativa": "healing word",
    "inflict wounds": "inflict wounds",
    "infligir ferimentos": "inflict wounds",
    "saltar": "jump",
    "longa passada": "longstrider",
    "proteção contra o mal e o bem": "protection from evil and good",
    "punição vingativa": "wrathful smite",
    "onda trovejante": "thunderwave",
    "mergulho de bruxa": "witch bolt",
    "raio de bruxa": "witch bolt",
    # Nível 2
    "invisibilidade": "invisibility",
    "sugestão": "suggestion",
    "web": "web",
    "teia": "web",
    "porta dimensional": "misty step",
    "passo nebuloso": "misty step",
    "trevas": "darkness",
    "bola de fogo": "fireball",
    "relâmpago": "lightning bolt",
    "raio de enfraquecimento": "ray of enfeeblement",
    "segurar pessoa": "hold person",
    "levitação": "levitate",
    "imagem espelhada": "mirror image",
    "nuvem de adormecimento": "sleep",
    "blindagem": "blur",
    "flecha ácida de melf": "melf's acid arrow",
    "toque de aranha": "spider climb",
    "escuridão": "darkness",
    # Nível 3
    "contrafeitiço": "counterspell",
    "dissipar magia": "dispel magic",
    "voo": "fly",
    "bola de fogo": "fireball",
    "raio relampejante": "lightning bolt",
    "pressa": "haste",
    "lentidão": "slow",
    "hipnose": "hypnotic pattern",
    "padrão hipnótico": "hypnotic pattern",
    "animar mortos": "animate dead",
    # Nível 4+
    "banimento": "banishment",
    "muralha de fogo": "wall of fire",
    "polimorfismo": "polymorph",
    "mudar forma": "polymorph",
    "porta dimensional": "dimension door",
    "teleporte": "teleport",
    "desejo": "wish",
    # Habilidades de classe comuns
    "recuperação arcana": "recuperação arcana",
    "tradição arcana": "tradição arcana",
    "segundo fôlego": "second wind",
    "surto de ação": "action surge",
    "esquiva astuta": "cunning action",
    "ataque furtivo": "sneak attack",
    "cura das mãos": "lay on hands",
    "sentido divino": "divine sense",
    "combate com duas armas": "two-weapon fighting",
    "fúria": "rage",
}


# ---------------------------------------------------------------------------
# Helpers de controle de turno
# ---------------------------------------------------------------------------

# Status que ENCERRAM a participação no combate — o combatente está
# definitivamente fora (morto, caído a 0 HP, fugiu). Usado para decidir
# QUANDO O COMBATE ACABA e para classificar caídos × sobreviventes.
DEFEATED_STATUSES = {
    "morto", "inconsciente", "estabilizado", "fugiu", "exilado",
}
# Status que fazem o combatente PULAR A VEZ na ordem de turno. Inclui
# "dormindo" (Sleep): a criatura está incapacitada (não age), mas continua
# VIVA e no combate — por isso "dormindo" NÃO entra em DEFEATED_STATUSES
# (dormir um inimigo não encerra a luta; é preciso derrotá-lo de fato).
OUT_OF_COMBAT_STATUSES = DEFEATED_STATUSES | {"dormindo"}

_MAX_COMBAT_LOG = 300


def _log_combat_event(etype: str, actor: str = "", target: str = "",
                      msg: str = "", **extra) -> None:
    """
    Acrescenta um evento estruturado ao log do combate.
    Usado pela tela tática (feed) e pela narração final da LLM.
    Falha de forma silenciosa fora de combate — nunca quebra uma ação.
    """
    cs = memory.campaign.get("combat_state")
    if not isinstance(cs, dict):
        return
    log = cs.setdefault("log", [])
    ev = {
        "round":  cs.get("round", 1),
        "type":   etype,
        "actor":  actor,
        "target": target,
        "msg":    msg,
    }
    if extra:
        ev.update(extra)
    log.append(ev)
    if len(log) > _MAX_COMBAT_LOG:
        del log[:-_MAX_COMBAT_LOG]


def _is_out_of_combat(name: str) -> bool:
    ch = memory.campaign["characters"].get(memory.char_key(name))
    return (ch.get("status", "") if ch else "").lower() in OUT_OF_COMBAT_STATUSES


def _wake_sleeper(char: dict) -> None:
    """
    Acorda uma criatura que está DORMINDO (efeito de Sleep): restaura o
    status para vivo/inimigo e remove a condição 'Dormindo'. Idempotente —
    não faz nada se a criatura não estiver dormindo.
    """
    if not isinstance(char, dict):
        return
    if (char.get("status", "") or "").lower() == "dormindo":
        char["status"] = "vivo" if memory.is_party_member(char) else "inimigo"
    sh = char.get("sheet") or {}
    conds = sh.get("condicoes")
    if isinstance(conds, list):
        sh["condicoes"] = [
            c for c in conds
            if not (isinstance(c, dict)
                    and (c.get("nome", "") or "").lower() == "dormindo")
        ]


def _normalize_for_new_combat(char: dict) -> None:
    """
    Sanitiza estados transitórios herdados ao INICIAR uma luta nova:
    ninguém entra dormindo, e quem está com HP > 0 não pode estar
    inconsciente/estabilizado. Remove as condições incapacitantes
    transitórias (Dormindo / Inconsciente) que jamais devem vazar entre
    combates. Não mexe em personagens genuinamente mortos.
    """
    if not isinstance(char, dict):
        return
    sh = char.get("sheet") or {}
    st = (char.get("status", "") or "").lower()
    hp = int(sh.get("vida_atual", 0) or 0)
    if st == "dormindo" or (hp > 0 and st in ("inconsciente", "estabilizado")):
        char["status"] = "vivo" if memory.is_party_member(char) else "inimigo"
    conds = sh.get("condicoes")
    if isinstance(conds, list):
        sh["condicoes"] = [
            c for c in conds
            if not (isinstance(c, dict)
                    and (c.get("nome", "") or "").lower() in ("dormindo", "inconsciente"))
        ]


def _heal_current_turn() -> None:
    """
    AUTO-CURA do ponteiro de turno: se o combatente do turno atual estiver
    fora de combate (morto/inconsciente/fugiu/etc.), avança para o próximo
    combatente válido — incrementando rodada no wrap e o token. Encerra o
    combate se ninguém restar. Idempotente se o atual já for válido.

    Chamada no INÍCIO de toda tool de turno → nenhuma ferramenta opera
    com o ponteiro preso num combatente fora de combate.
    """
    cs = memory.campaign.get("combat_state")
    if not cs or not cs.get("is_active"):
        return
    order = cs.get("initiative_order", [])
    if not order:
        return

    idx = cs.get("current_turn_index", 0)
    if not isinstance(idx, int) or not (0 <= idx < len(order)):
        idx = 0
        cs["current_turn_index"] = 0

    if not _is_out_of_combat(order[idx]):
        return  # atual já é válido

    round_num = cs.get("round", 1)
    for _ in range(len(order) + 1):
        idx += 1
        if idx >= len(order):
            idx = 0
            round_num += 1
        if not _is_out_of_combat(order[idx]):
            cs["current_turn_index"] = idx
            cs["round"]              = round_num
            cs["turn_resolved"]      = False
            cs["turn_token"]         = cs.get("turn_token", 0) + 1
            _reset_turn_economy(cs)
            memory.save_campaign()
            return

    # Ninguém em combate — encerra
    cs["is_active"]          = False
    cs["initiative_order"]   = []
    cs["current_turn_index"] = 0
    cs["round"]              = 1
    memory.save_campaign()


def _mark_turn_resolved() -> None:
    """Marca o turno como mecanicamente resolvido."""
    cs = memory.campaign.get("combat_state")
    if cs and cs.get("is_active"):
        cs["turn_resolved"] = True


def _auto_advance_turn(actor_name: str = "") -> str:
    """
    Avança o turno e retorna o anúncio do próximo como string.
    Injetado no final de attack_roll(), use_ability() e roll_death_save().
    Pula automaticamente personagens mortos/inconscientes/fugidos.
    Marca turn_auto_advanced=True para que next_turn() não duplique o avanço.
    Retorna string vazia fora do combate.

    actor_name: quem REALMENTE agiu. O avanço é ancorado na posição do ator
      na ordem de iniciativa — não no ponteiro global. Isso impede que ações
      fora de ordem (jogador agindo na vez de um NPC) corrompam o ponteiro e
      inflem o número da rodada (ex.: pular de Rodada 3 para 5).
    """
    cs = memory.campaign.get("combat_state")
    if not cs or not cs.get("is_active"):
        return ""
    order = cs.get("initiative_order", [])
    if not order:
        return ""

    OUT_OF_COMBAT = OUT_OF_COMBAT_STATUSES   # inclui "dormindo" → pula a vez

    round_num     = cs.get("round", 1)
    initial_round = round_num

    # Âncora: posição de quem agiu (se estiver na ordem). Senão, o ponteiro atual.
    idx = cs.get("current_turn_index", 0)
    if actor_name:
        akey = memory.char_key(actor_name)
        for i, n in enumerate(order):
            if memory.char_key(n) == akey:
                idx = i
                break

    skipped = []

    for _ in range(len(order) + 1):
        idx += 1
        if idx >= len(order):
            idx        = 0
            round_num += 1

        current_name = order[idx]
        char         = memory.campaign["characters"].get(memory.char_key(current_name))
        status       = (char.get("status", "") if char else "").lower()

        if status in OUT_OF_COMBAT:
            skipped.append(f"{current_name} ({status})")
            continue

        cs["current_turn_index"] = idx
        cs["round"]              = round_num
        cs["turn_resolved"]      = False
        cs["turn_auto_advanced"] = True   # impede next_turn() de avançar de novo
        cs["turn_token"]         = cs.get("turn_token", 0) + 1  # avanço real
        _reset_turn_economy(cs)
        memory.save_campaign()

        skip_msg      = f"\n   ⏩ Pulados: {', '.join(skipped)}" if skipped else ""
        new_round_msg = f"\n   🔔 Nova rodada! Rodada {round_num} começa." if round_num > initial_round else ""
        order_str     = " → ".join(f"[{n}]" if i == idx else n for i, n in enumerate(order))
        return (
            f"\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏭️  TURNO AVANÇADO — Rodada {round_num}{new_round_msg}{skip_msg}\n"
            f"🎯 Próxima vez: **{current_name}**\n"
            f"   Ordem: {order_str}"
        )

    # Todos fora de combate — encerra
    cs["is_active"]          = False
    cs["initiative_order"]   = []
    cs["current_turn_index"] = 0
    cs["round"]              = 1
    memory.save_campaign()
    return "\n\n🏳️  Todos os personagens estão fora de combate. Combate encerrado automaticamente."


def _combat_current_actor() -> str:
    """Nome do combatente cujo turno é AGORA (string vazia se não houver)."""
    cs = memory.campaign.get("combat_state", {})
    if not cs.get("is_active"):
        return ""
    order = cs.get("initiative_order", [])
    if not order:
        return ""
    idx = cs.get("current_turn_index", 0)
    if not isinstance(idx, int) or not (0 <= idx < len(order)):
        return ""
    return order[idx]


def _combat_turn_violation(actor_name: str) -> str | None:
    """
    Retorna mensagem de erro se `actor_name` tentar agir FORA do seu turno,
    ou None se a ação é permitida.

    Regras (a tool é a AUTORIDADE — não confia no LLM seguir a ordem):
      • Fora de combate ativo → permitido (sem ordem a impor).
      • Ator não está na iniciativa → permitido (ex.: invocação não listada;
        não dá pra impor ordem a quem não está na lista).
      • Ator está na iniciativa mas NÃO é o atual → BLOQUEADO.
    """
    cs = memory.campaign.get("combat_state", {})
    if not cs.get("is_active"):
        return None
    order = cs.get("initiative_order", [])
    if not order:
        return None
    akey = memory.char_key(actor_name)
    if not any(memory.char_key(n) == akey for n in order):
        return None
    cur = _combat_current_actor()
    if not cur or memory.char_key(cur) == akey:
        return None
    return (
        f"❌ FORA DE ORDEM: não é o turno de {actor_name}. "
        f"É a vez de **{cur}**.\n"
        f"   • Se {cur} é um NPC inimigo → chame execute_npc_turn().\n"
        f"   • Se o jogador tentou agir adiantado → diga 'ainda não é sua vez' "
        f"e resolva o turno de {cur} primeiro.\n"
        f"   Nenhum dado foi rolado e nada mudou."
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
# ── Sistema de mana: variante oficial Spell Points do D&D 5e (DMG p.288) ────
# Custo de cada magia em Pontos de Magia (mana), por nível da magia.
# Truques (nível 0) são gratuitos. Substitui o antigo custo homebrew (nível×4).
SPELL_MANA_COST = {0: 0, 1: 2, 2: 3, 3: 5, 4: 6, 5: 7, 6: 9, 7: 10, 8: 11, 9: 13}

# Pool de mana por NÍVEL DE CONJURADOR — tabela oficial da variante Spell
# Points (DMG p.288). O pool depende SÓ do nível: todo conjurador de um dado
# nível tem o mesmo pool, independentemente do atributo de conjuração.
SPELL_POINTS_BY_LEVEL = {
    1: 4,    2: 6,    3: 14,   4: 17,   5: 27,
    6: 32,   7: 38,   8: 44,   9: 57,   10: 64,
    11: 73,  12: 73,  13: 83,  14: 83,  15: 94,
    16: 94,  17: 107, 18: 114, 19: 123, 20: 133,
}

# Fração de conjuração por classe → define o nível de conjurador efetivo.
# Chaves SEM acento — a comparação normaliza acentos (ver _max_mana_for).
_FULL_CASTERS  = {"mago", "feiticeiro", "clerigo", "druida", "bardo",
                  "bruxo", "arcanista"}
_HALF_CASTERS  = {"paladino", "patrulheiro"}             # metade do progresso
_THIRD_CASTERS = {"guerreiro", "ladino"}                 # Cav. Élditch / Trapaceiro Arcano


def _max_mana_for(classe: str, char_level: int) -> int:
    """
    Pool máximo de mana de um personagem pela tabela oficial de Pontos de
    Magia (DMG p.288). NÃO depende do atributo de conjuração, depende só do
    nível de conjurador efetivo:

      • Conjurador pleno  → nível de conjurador = nível do personagem.
      • Meio-conjurador   → ceil(nível / 2); nada antes do nível 2.
      • Terço-conjurador  → ceil(nível / 3); nada antes do nível 3.
      • Monge             → Ki = 1 ponto por nível (regra real do monge).
      • Bárbaro / demais  → 0.
    """
    c   = _norm_txt(classe)   # minúsculas, sem acento (clérigo → clerigo)
    lvl = max(1, min(20, int(char_level or 1)))
    if c in _FULL_CASTERS:
        cl = lvl
    elif c in _HALF_CASTERS:
        cl = (lvl + 1) // 2 if lvl >= 2 else 0          # ceil(lvl/2)
    elif c in _THIRD_CASTERS:
        cl = (lvl + 2) // 3 if lvl >= 3 else 0          # ceil(lvl/3)
    elif c == "monge":
        return lvl                                       # pool de Ki = nível
    else:
        return 0                                         # bárbaro / não-conjuradores
    return SPELL_POINTS_BY_LEVEL.get(cl, 0)

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
# Cobertura: TODAS as entradas de CLASS_LEVEL_FEATURES devem estar aqui.
# Se faltar uma, o backend cai num fallback genérico ("Habilidade de classe —
# X") que é inútil para o jogador. Mantenha sincronizado ao adicionar novas
# features. Estilo: 1 frase curta (~100-180 chars) baseada no SRD 5e em PT-BR.
CLASS_FEATURE_DESCS: dict[str, dict] = {
    # ── Genéricas / compartilhadas ─────────────────────────────────────────
    "Ataque Extra":              {"descricao": "Pode atacar duas vezes em vez de uma ao usar a ação Atacar.", "custo_mana": 0, "dado": ""},
    "Ataque Extra Adicional":    {"descricao": "Pode atacar três vezes em vez de duas ao usar a ação Atacar (nv. 11+).", "custo_mana": 0, "dado": ""},
    "Defesa Sem Armadura":       {"descricao": "Sem armadura, CA = 10 + mod. DES + mod. CON (Bárbaro) ou + mod. SAB (Monge). Pode usar escudo (Bárbaro).", "custo_mana": 0, "dado": ""},
    "Estilo de Combate":         {"descricao": "Escolhe um estilo (Arquearia, Defesa, Duelo, Combate com Duas Armas, Proteção, Grande Arma) com bônus passivo permanente.", "custo_mana": 0, "dado": ""},
    "Especialização":            {"descricao": "Dobra o bônus de proficiência em 2 perícias ou ferramentas escolhidas em que já tem proficiência.", "custo_mana": 0, "dado": ""},
    "Evasão":                    {"descricao": "Em saves de DES bem-sucedidos contra efeitos de área: nenhum dano. Em falhas: metade do dano.", "custo_mana": 0, "dado": ""},
    "Conjuração":                {"descricao": "Ganha acesso a magias da classe. Usa o atributo de conjuração próprio (CAR/SAB/INT) para CD e ataques mágicos.", "custo_mana": 0, "dado": ""},

    # ── Bárbaro ───────────────────────────────────────────────────────────
    "Fúria":                     {"descricao": "Ação bônus: +2 dano com armas FOR, vantagem em testes/saves de FOR, resistência a dano físico. Dura 1 minuto. Usos = 2 + nível (até 6 no 17º).", "custo_mana": 0, "dado": ""},
    "Movimento Imprudente":      {"descricao": "Ao atacar com FOR no 1º ataque do turno: ganha vantagem, mas ataques contra você também ganham vantagem até o próximo turno.", "custo_mana": 0, "dado": ""},
    "Senso de Perigo":           {"descricao": "Vantagem em saves de DES contra efeitos visíveis (armadilhas, magias) — desde que não esteja cego, surdo ou incapacitado.", "custo_mana": 0, "dado": ""},
    "Caminho Primitivo":         {"descricao": "Escolhe uma trilha (Berserker, Guerreiro Totêmico, etc.) que define habilidades temáticas do 3º nível em diante.", "custo_mana": 0, "dado": ""},
    "Movimento Rápido":          {"descricao": "Deslocamento +3m enquanto não estiver usando armadura pesada.", "custo_mana": 0, "dado": ""},
    "Instinto Selvagem":         {"descricao": "Vantagem em testes de iniciativa. Não é considerado surpreso se entrar em fúria no primeiro turno.", "custo_mana": 0, "dado": ""},
    "Resistência Brutal":        {"descricao": "Pode reduzir qualquer dano físico recebido em 3 + nível de bárbaro, uma vez por turno.", "custo_mana": 0, "dado": ""},
    "Fúria Implacável":          {"descricao": "Se for reduzido a 0 PV durante a fúria (sem morrer na hora), fica com 1 PV. 1 uso por descanso longo.", "custo_mana": 0, "dado": ""},
    "Ira Persistente":           {"descricao": "Sua fúria só termina cedo se você ficar inconsciente ou escolher terminá-la — não mais pela falta de ações ou dano.", "custo_mana": 0, "dado": ""},
    "Fúria Devastadora":         {"descricao": "Ao acertar um crítico com arma corpo a corpo, role um dado extra de dano da arma.", "custo_mana": 0, "dado": ""},
    "Força Indômita":            {"descricao": "Sua FOR e CON sobem para 24 e o limite máximo das duas vai para 24 (nv. 20).", "custo_mana": 0, "dado": ""},
    "Guerreiro Primordial":      {"descricao": "Ganha +4 em FOR e CON (nv. 20), com limite máximo 24 nesses dois atributos.", "custo_mana": 0, "dado": ""},

    # ── Guerreiro ─────────────────────────────────────────────────────────
    "Segunda Fôlego":            {"descricao": "Ação bônus: recupera 1d10 + nível de guerreiro de PV. 1 uso por descanso curto ou longo.", "custo_mana": 0, "dado": "1d10"},
    "Surto de Ação":             {"descricao": "1 uso por descanso curto: ganha uma Ação adicional neste turno (além da Ação e Bônus normais).", "custo_mana": 0, "dado": ""},
    "Surto de Ação Adicional":   {"descricao": "Pode usar Surto de Ação 2 vezes entre descansos curtos (nv. 17+).", "custo_mana": 0, "dado": ""},
    "Arquétipo Marcial":         {"descricao": "Escolhe um arquétipo (Campeão, Mestre de Batalha, Cavaleiro Élditch, etc.) — define habilidades temáticas a partir do 3º nível.", "custo_mana": 0, "dado": ""},
    "Indomável":                 {"descricao": "1 vez por descanso longo: pode refazer um teste de resistência que falhou (2 usos no 13º, 3 no 17º).", "custo_mana": 0, "dado": ""},
    "Campeão Eterno":            {"descricao": "Sua FOR ou CON aumenta em 4 (limite máximo 24). Ganha resistência adicional contra ataques (nv. 20).", "custo_mana": 0, "dado": ""},

    # ── Paladino ──────────────────────────────────────────────────────────
    "Sentido Divino":            {"descricao": "Ação: detecta criaturas celestiais, infernais e mortos-vivos em até 18m. Usos = 1 + mod. CAR por descanso longo.", "custo_mana": 0, "dado": ""},
    "Imposição de Mãos":         {"descricao": "Pool de cura = nível × 5 PV. Pode dividir entre cura ou gastar 5 PV para neutralizar um veneno/doença em um toque.", "custo_mana": 0, "dado": ""},
    "Combate Divino":            {"descricao": "Pode gastar slots de magia ao acertar com arma corpo a corpo para causar +2d8 (slot 1) até +5d8 radiante extra (Smite Divino).", "custo_mana": 0, "dado": "2d8"},
    "Saúde Divina":              {"descricao": "Imune a doenças mágicas e naturais (nv. 3+).", "custo_mana": 0, "dado": ""},
    "Juramento Sagrado":         {"descricao": "Escolhe um juramento (Devoção, Antigos, Vingança, etc.) que define preceitos, magias bônus e usos de Canalizar Divindade.", "custo_mana": 0, "dado": ""},
    "Aura de Proteção":          {"descricao": "Você e aliados em 3m (6m no 18º) ganham +mod. CAR em todos os saves enquanto você estiver consciente.", "custo_mana": 0, "dado": ""},
    "Aura de Coragem":           {"descricao": "Você e aliados em 3m (6m no 18º) são imunes à condição Amedrontado enquanto você estiver consciente.", "custo_mana": 0, "dado": ""},
    "Golpe Divino Aprimorado":   {"descricao": "Seus ataques com arma corpo a corpo causam +1d8 radiante extra automático (nv. 11+).", "custo_mana": 0, "dado": "1d8"},
    "Pureza do Espírito":        {"descricao": "Permanentemente sob efeito da magia Proteção contra o Mal e Bem (nv. 14+).", "custo_mana": 0, "dado": ""},
    "Aura Aprimorada":           {"descricao": "Suas auras de Proteção e Coragem têm alcance ampliado para 9m (nv. 18+).", "custo_mana": 0, "dado": ""},
    "Campeão Sagrado":           {"descricao": "+4 em FOR ou CAR (limite máximo 24). Recupera 10 PV no início de cada turno se estiver com ≥ 1 PV (nv. 20).", "custo_mana": 0, "dado": ""},

    # ── Patrulheiro ───────────────────────────────────────────────────────
    "Inimigo Favorecido":        {"descricao": "Escolhe um tipo de criatura — vantagem em testes para rastreá-la, +PROF de info, +2 dano em armas contra ela.", "custo_mana": 0, "dado": ""},
    "Inimigo Favorecido Adicional":{"descricao": "Escolhe um 2º tipo de inimigo favorecido (nv. 6+).", "custo_mana": 0, "dado": ""},
    "Explorador Natural":        {"descricao": "Escolhe um terreno: viaja em ritmo normal mesmo em terreno difícil, sempre alerta, +PROF na busca por suprimentos.", "custo_mana": 0, "dado": ""},
    "Explorador Natural Adicional":{"descricao": "Escolhe um 2º terreno favorável (nv. 6+).", "custo_mana": 0, "dado": ""},
    "Arquétipo do Patrulheiro":  {"descricao": "Escolhe um arquétipo (Caçador, Senhor das Feras, etc.) — define habilidades temáticas a partir do 3º nível.", "custo_mana": 0, "dado": ""},
    "Consciência Primitiva":     {"descricao": "Ação: detecta tipos de criaturas (feéricos, mortos-vivos, celestiais…) em até 1,5km — varia conforme o terreno (3º+).", "custo_mana": 0, "dado": ""},
    "Passagem pela Terra":       {"descricao": "Move-se em terreno difícil natural sem penalidade. Imune a magias que manipulam plantas vivas. Não deixa rastros (nv. 8+).", "custo_mana": 0, "dado": ""},
    "Escondes-te à Vista":       {"descricao": "1 minuto de preparo em cobertura natural → camuflagem perfeita; pode se esconder mesmo apenas levemente obscurecido (nv. 10+).", "custo_mana": 0, "dado": ""},
    "Desaparecer":               {"descricao": "Pode usar Esconder como ação bônus em seu turno. Não pode ser rastreado magicamente (nv. 14+).", "custo_mana": 0, "dado": ""},
    "Inimigo do Inimigo":        {"descricao": "Uma vez por turno: usa Inimigo Favorecido contra QUALQUER criatura sem gastar slot — escolha o tipo na hora (nv. 20).", "custo_mana": 0, "dado": ""},

    # ── Bardo ─────────────────────────────────────────────────────────────
    "Inspiração Bárdica":        {"descricao": "Ação bônus: aliado em 18m ganha 1d6 (1d8 no 5º, 1d10 no 10º, 1d12 no 15º) para somar a 1 teste/save em 10 min.", "custo_mana": 0, "dado": "1d6"},
    "Inspiração Bárdica Aprimorada":{"descricao": "Seu dado de Inspiração Bárdica sobe (1d8 no 5º; 1d10 no 10º; 1d12 no 15º).", "custo_mana": 0, "dado": "1d8"},
    "Inspiração Superior":       {"descricao": "Em iniciativa, se nenhum uso de Inspiração Bárdica estiver disponível, ganha 1 de volta (nv. 10+).", "custo_mana": 0, "dado": ""},
    "Inspiração Superior Aprimorada":{"descricao": "Recupera todos os usos de Inspiração Bárdica ao rolar iniciativa (nv. 20).", "custo_mana": 0, "dado": ""},
    "Canção de Repouso":         {"descricao": "No descanso curto, aliados que ouvirem você recuperam +1d6 PV extra (escala: 1d8 no 9º, 1d10 no 13º, 1d12 no 17º).", "custo_mana": 0, "dado": "1d6"},
    "Versatilidade":             {"descricao": "Ganha proficiência em qualquer perícia/ferramenta com bônus = metade do PROF (Bardic Jack of All Trades).", "custo_mana": 0, "dado": ""},
    "Colégio Bárdico":           {"descricao": "Escolhe um colégio (Saber, Coragem, etc.) — define habilidades temáticas a partir do 3º nível.", "custo_mana": 0, "dado": ""},
    "Fonte de Inspiração":       {"descricao": "Recupera todos os usos de Inspiração Bárdica em descansos curtos (não apenas longos) (nv. 5+).", "custo_mana": 0, "dado": ""},
    "Segredo da Magia":          {"descricao": "Aprende 2 magias de qualquer classe e as adiciona à sua lista permanentemente (nv. 6+).", "custo_mana": 0, "dado": ""},
    "Segredos Mágicos":          {"descricao": "Aprende mais 2 magias de qualquer classe e as adiciona à sua lista (nv. 10+).", "custo_mana": 0, "dado": ""},
    "Segredos Mágicos Adicionais":{"descricao": "Aprende mais 2 magias de qualquer classe (nv. 14+).", "custo_mana": 0, "dado": ""},
    "Sapiência":                 {"descricao": "+4 em INT ou CAR, limite máximo 24 (nv. 18+).", "custo_mana": 0, "dado": ""},

    # ── Clérigo ───────────────────────────────────────────────────────────
    "Domínio Divino":            {"descricao": "Escolhe um domínio (Vida, Guerra, Conhecimento, Tempestade, etc.) — concede magias bônus e habilidades temáticas.", "custo_mana": 0, "dado": ""},
    "Canalizar Divindade":       {"descricao": "Ação: usa Expulsar Mortos-Vivos ou um efeito do seu domínio. 1 uso por descanso curto (2 no 6º, 3 no 18º).", "custo_mana": 0, "dado": ""},
    "Destruição de Mortos-Vivos":{"descricao": "Ao Expulsar Mortos-Vivos, criaturas com CR ≤ 1/2 (escala com nível) que falharem no save são destruídas (nv. 5+).", "custo_mana": 0, "dado": ""},
    "Destruição de Mortos-Vivos Aprimorada":{"descricao": "O CR máximo destruído por Expulsar sobe (1 no 8º, 2 no 11º, 3 no 14º, 4 no 17º).", "custo_mana": 0, "dado": ""},
    "Intervenção Divina Inicial":{"descricao": "1 vez por descanso longo: implora ajuda divina — 1% × nível de chance de sucesso (nv. 8+).", "custo_mana": 0, "dado": ""},
    "Intervenção Divina":        {"descricao": "Suas chances de Intervenção Divina aumentam (até 30% no 17º) (nv. 10+).", "custo_mana": 0, "dado": ""},
    "Intervenção Divina Superior":{"descricao": "Sua Intervenção Divina tem sucesso automático, sem rolagem (nv. 20).", "custo_mana": 0, "dado": ""},

    # ── Druida ────────────────────────────────────────────────────────────
    "Druídico":                  {"descricao": "Aprende Druídico — idioma secreto dos druidas, falado e escrito (cifras em marcações naturais).", "custo_mana": 0, "dado": ""},
    "Forma Selvagem":            {"descricao": "Ação: transforma-se em besta com CR ≤ ¼ do seu nível (½ no 4º, 1 no 8º). 2 usos por descanso curto ou longo.", "custo_mana": 0, "dado": ""},
    "Círculo Druídico":          {"descricao": "Escolhe um círculo (Terra, Lua, Sonhos, etc.) — define habilidades temáticas a partir do 2º nível.", "custo_mana": 0, "dado": ""},
    "Forma Selvagem Aprimorada": {"descricao": "Sua Forma Selvagem pode adotar bestas com CR maior e formas aquáticas/voadoras (4º: aquática; 8º: voadora).", "custo_mana": 0, "dado": ""},
    "Uso de Forma Selvagem Adicional":{"descricao": "Forma Selvagem agora tem 3 usos por descanso (nv. 6+).", "custo_mana": 0, "dado": ""},
    "Forma Selvagem do Druida de Besta":{"descricao": "Pode usar Forma Selvagem com criaturas mais poderosas e mantê-la por mais tempo (nv. 18+).", "custo_mana": 0, "dado": ""},
    "Arquidruida":               {"descricao": "Forma Selvagem com usos ilimitados. Conjura magias druídicas sem componente material ou verbal (nv. 20).", "custo_mana": 0, "dado": ""},

    # ── Monge ─────────────────────────────────────────────────────────────
    "Artes Marciais":            {"descricao": "Sem armadura/escudo: usa DES no lugar de FOR em ataques desarmados/marciais. Dado marcial 1d4 (sobe até 1d10 no 17º). Bônus: ataque desarmado extra.", "custo_mana": 0, "dado": "1d4"},
    "Ki":                        {"descricao": "Pool de pontos de Ki = seu nível de monge. Gasta em Rajada de Golpes, Defesa Paciente, Passo do Vento, Atordoamento, etc.", "custo_mana": 0, "dado": ""},
    "Movimento Sem Armadura":    {"descricao": "Deslocamento aumenta sem armadura/escudo: +3m no 2º, escalando até +9m no 18º.", "custo_mana": 0, "dado": ""},
    "Desviar Projéteis":         {"descricao": "Reação: reduz dano de ataque à distância em 1d10 + DES + nível de monge. Se zerar, pode arremessar a munição de volta gastando 1 Ki.", "custo_mana": 0, "dado": "1d10"},
    "Tradição Monástica":        {"descricao": "Escolhe uma tradição (Mão Aberta, Sombras, Quatro Elementos, etc.) — define habilidades temáticas a partir do 3º nível.", "custo_mana": 0, "dado": ""},
    "Queda Lenta":               {"descricao": "Reação: reduz dano de queda em 5 × nível de monge.", "custo_mana": 0, "dado": ""},
    "Atordoamento":              {"descricao": "Após acertar um golpe marcial, gasta 1 Ki: alvo faz save de CON; se falhar, fica Atordoado até o fim do próximo turno.", "custo_mana": 0, "dado": ""},
    "Golpes Ki-Aprimorados":     {"descricao": "Ataques desarmados contam como mágicos para resistência/imunidade a dano (nv. 6+).", "custo_mana": 0, "dado": ""},
    "Tranquilidade":             {"descricao": "Ao fim do descanso longo, recebe efeito de Santuário gratuito até o próximo descanso longo (nv. 7+).", "custo_mana": 0, "dado": ""},
    "Correr Pelas Paredes":      {"descricao": "Pode correr em paredes verticais e na água (sem cair) durante o seu turno (nv. 9+).", "custo_mana": 0, "dado": ""},
    "Pureza de Corpo":           {"descricao": "Imune a doenças e venenos (nv. 10+).", "custo_mana": 0, "dado": ""},
    "Língua do Sol e da Lua":    {"descricao": "Compreende todas as línguas faladas (nv. 13+).", "custo_mana": 0, "dado": ""},
    "Alma do Diamante":          {"descricao": "Proficiência em todos os saves. Pode gastar 1 Ki para refazer um save que falhou (nv. 14+).", "custo_mana": 0, "dado": ""},
    "Alma Sem Idade":            {"descricao": "Não envelhece e não precisa de comida ou água (nv. 15+).", "custo_mana": 0, "dado": ""},
    "Mente Vazia":               {"descricao": "Imune a Enfeitiçado e Amedrontado (nv. 15+).", "custo_mana": 0, "dado": ""},
    "Corpo Vazio":               {"descricao": "Ação: gasta 4 Ki — fica invisível por 1 minuto e ganha resistência a todo dano exceto força (nv. 18+).", "custo_mana": 0, "dado": ""},
    "Ser Perfeito":              {"descricao": "Recupera 4 Ki ao rolar iniciativa se estiver com 0. SAB e DES máximos sobem para 24 (nv. 20).", "custo_mana": 0, "dado": ""},

    # ── Ladino ────────────────────────────────────────────────────────────
    "Ataque Furtivo":            {"descricao": "1 vez por turno: +1d6 dano (escala até 10d6 no 19º) em ataque com vantagem OU aliado adjacente ao alvo.", "custo_mana": 0, "dado": "1d6"},
    "Linguagem dos Ladrões":     {"descricao": "Aprende cifra secreta usada por ladinos — mensagens ocultas em conversas, gírias e marcações.", "custo_mana": 0, "dado": ""},
    "Ação Ardilosa":             {"descricao": "Ação bônus: pode Disparar (Disengage), Esconder, ou Correr (Dash) no seu turno.", "custo_mana": 0, "dado": ""},
    "Arquétipo de Ladrão":       {"descricao": "Escolhe um arquétipo (Ladrão, Assassino, Trapaceiro Arcano) — define habilidades temáticas a partir do 3º nível.", "custo_mana": 0, "dado": ""},
    "Especialização Adicional":  {"descricao": "Dobra o bônus de proficiência em 2 perícias/ferramentas extras (nv. 6+).", "custo_mana": 0, "dado": ""},
    "Esquiva Incrivelmente Baixa":{"descricao": "Reação: ao ser atingido por ataque visível, reduz o dano pela metade.", "custo_mana": 0, "dado": ""},
    "Talento Confiável":         {"descricao": "Em testes de perícia com proficiência, qualquer rolagem ≤ 9 é tratada como 10 (nv. 11+).", "custo_mana": 0, "dado": ""},
    "Visão às Cegas":            {"descricao": "Visão às cegas em raio de 3m — percebe ao redor sem usar a visão (nv. 14+).", "custo_mana": 0, "dado": ""},
    "Mente Escorregadia":        {"descricao": "Ganha proficiência em saves de SAB (nv. 15+).", "custo_mana": 0, "dado": ""},
    "Elusivo":                   {"descricao": "Nenhum ataque tem vantagem contra você enquanto estiver consciente (nv. 18+).", "custo_mana": 0, "dado": ""},
    "Assassino Reflexivo":       {"descricao": "Pode refazer uma rolagem de ataque, teste de atributo ou save por turno (nv. 20).", "custo_mana": 0, "dado": ""},

    # ── Mago ──────────────────────────────────────────────────────────────
    "Recuperação Arcana":        {"descricao": "1 vez por dia, em descanso curto: recupera slots de magia totalizando ≤ metade do seu nível (arredondado para cima, nenhum slot > nv. 5).", "custo_mana": 0, "dado": ""},
    "Tradição Arcana":           {"descricao": "Escolhe uma tradição (Evocação, Abjuração, Necromancia, Ilusão, Encantamento, Transmutação, Adivinhação, Conjuração) — define habilidades temáticas.", "custo_mana": 0, "dado": ""},
    "Feitiço de Tradição":       {"descricao": "Habilidade temática da Tradição Arcana no 2º nível — varia conforme a escola escolhida.", "custo_mana": 0, "dado": ""},
    "Habilidade de Tradição":    {"descricao": "Habilidade adicional da Tradição Arcana no 6º nível — varia conforme a escola escolhida.", "custo_mana": 0, "dado": ""},
    "Habilidade de Tradição Adicional":{"descricao": "Habilidade adicional da Tradição Arcana no 10º nível.", "custo_mana": 0, "dado": ""},
    "Habilidade de Tradição Superior":{"descricao": "Habilidade culminante da Tradição Arcana no 14º nível.", "custo_mana": 0, "dado": ""},
    "Maestria de Feitiço":       {"descricao": "Escolhe 1 magia de nível 1 e 1 de nível 2 do seu livro — pode conjurá-las à vontade sem gastar slot (nv. 18+).", "custo_mana": 0, "dado": ""},
    "Assinatura de Feitiço":     {"descricao": "Escolhe 2 magias de nível 3 do livro — cada uma pode ser conjurada uma vez por descanso curto sem gastar slot (nv. 20).", "custo_mana": 0, "dado": ""},

    # ── Feiticeiro ────────────────────────────────────────────────────────
    "Origem de Feiticeiro":      {"descricao": "Escolhe a origem do seu poder (Linhagem Dracônica, Magia Selvagem, etc.) — define habilidades temáticas e atributos passivos.", "custo_mana": 0, "dado": ""},
    "Pontos de Feitiçaria":      {"descricao": "Pool de pontos = seu nível de feiticeiro. Use para criar slots de magia, alimentar Metamagia ou trocar slot ↔ ponto.", "custo_mana": 0, "dado": ""},
    "Metamagia":                 {"descricao": "Escolhe 2 efeitos (Sutil, Empoderada, Distante, Gêmea, Cuidadosa, Estendida, etc.) que alteram magias gastando pontos de feitiçaria.", "custo_mana": 0, "dado": ""},
    "Metamagia Adicional":       {"descricao": "Aprende mais 1 efeito de Metamagia (no 10º e no 17º nível).", "custo_mana": 0, "dado": ""},
    "Habilidade de Origem":      {"descricao": "Habilidade temática da sua Origem de Feiticeiro no 6º nível.", "custo_mana": 0, "dado": ""},
    "Habilidade de Origem Adicional":{"descricao": "Habilidade adicional da Origem de Feiticeiro no 14º nível.", "custo_mana": 0, "dado": ""},
    "Habilidade de Origem Superior":{"descricao": "Habilidade culminante da Origem de Feiticeiro no 18º nível.", "custo_mana": 0, "dado": ""},
    "Restauração de Feitiçaria": {"descricao": "1 vez por descanso curto: recupera 4 Pontos de Feitiçaria (nv. 20).", "custo_mana": 0, "dado": ""},

    # ── Bruxo ─────────────────────────────────────────────────────────────
    "Patrono Sobrenatural":      {"descricao": "Faz um pacto com um patrono (Senhor Lich, Arquifada, Senhor das Sombras, Grande Antigo, etc.) — define habilidades temáticas.", "custo_mana": 0, "dado": ""},
    "Magia do Pacto":             {"descricao": "Conjuração via pacto: poucos slots, mas todos sobem juntos para o nível máximo. Recuperados em descanso CURTO (não longo).", "custo_mana": 0, "dado": ""},
    "Invocações Sobrenaturais":  {"descricao": "Aprende invocações (Eldritch Invocations) — habilidades passivas/at-will que modificam magias e perícias.", "custo_mana": 0, "dado": ""},
    "Invocações Sobrenaturais Adicionais":{"descricao": "Aprende mais 1 Invocação Sobrenatural.", "custo_mana": 0, "dado": ""},
    "Bênção do Pacto":           {"descricao": "Escolhe um pacto: Lâmina (arma mágica), Tomo (livro com 3 truques extras) ou Corrente (familiar especial).", "custo_mana": 0, "dado": ""},
    "Habilidade do Patrono":     {"descricao": "Habilidade temática do seu Patrono no 6º nível — varia conforme o patrono escolhido.", "custo_mana": 0, "dado": ""},
    "Habilidade do Patrono Adicional":{"descricao": "Habilidade adicional do Patrono no 10º nível.", "custo_mana": 0, "dado": ""},
    "Habilidade do Patrono Superior":{"descricao": "Habilidade culminante do Patrono no 14º nível.", "custo_mana": 0, "dado": ""},
    "Magia Mística":             {"descricao": "Aprende 1 magia de QUALQUER lista de classe, conjurada com slot separado recuperado a cada descanso longo (nv. 11+).", "custo_mana": 0, "dado": ""},
    "Mestre Sobrenatural":       {"descricao": "Pode recuperar 1 slot de pacto como ação no combate, 1 vez por descanso longo (nv. 20).", "custo_mana": 0, "dado": ""},
}


# ────────────────────────────────────────────────────────────────────────────
# FEATURE_VARIANTS — subescolhas mecânicas de habilidades de classe.
# (Fase 1: features "escolha 1/N de uma lista finita" com efeito bem definido.)
#
# Estrutura:
#   FEATURE_VARIANTS[<nome da feature em PT-BR>] = {
#     "pick":        int        # quantas opções escolher
#     "pick_label":  str        # rótulo da unidade (ex.: "estilo", "tipo")
#     "options": {
#         <nome>: {"descricao": str, "narrative_hint": "passive"|"reaction"|"active"}
#     },
#   }
#
# Storage por personagem: char["sheet"]["feature_choices"][feature_name].
#   • pick=1 → string única ("Arquearia")
#   • pick>1 → lista ([..])
#
# Para LIGAR o efeito mecânico, ver _combat_style_bonus / _recalculate_ca /
# attack_roll. Variantes sem hook engine valem como nota narrativa que a
# IA-mestre lê na descrição da ficha.
# ────────────────────────────────────────────────────────────────────────────
FEATURE_VARIANTS: dict[str, dict] = {
    # Guerreiro / Patrulheiro / Paladino — 1º nível (e Bardo de Coragem no 3º)
    "Estilo de Combate": {
        "pick": 1,
        "pick_label": "estilo",
        "options": {
            "Arquearia":               {"descricao": "+2 nos rolls de ataque com armas à distância.", "narrative_hint": "passive"},
            "Defesa":                  {"descricao": "+1 CA enquanto estiver usando qualquer armadura.", "narrative_hint": "passive"},
            "Duelo":                   {"descricao": "+2 dano com arma corpo a corpo de uma mão, desde que não esteja empunhando outra arma.", "narrative_hint": "passive"},
            "Combate com Duas Armas":  {"descricao": "Adiciona o modificador de atributo ao dano do ataque com a 2ª arma (off-hand).", "narrative_hint": "passive"},
            "Proteção":                {"descricao": "Reação (precisa estar com escudo): impõe desvantagem em um ataque contra aliado adjacente.", "narrative_hint": "reaction"},
            "Grande Arma":             {"descricao": "Quando rola 1 ou 2 nos dados de dano de arma de duas mãos, pode re-rolar uma vez por dado.", "narrative_hint": "passive"},
        },
    },
    # Patrulheiro — 1º nível (segundo tipo no 6º via "Inimigo Favorecido Adicional")
    "Inimigo Favorecido": {
        "pick": 1,
        "pick_label": "tipo",
        "options": {
            "Aberrações":     {"descricao": "Especialista em aberrações: vantagem para rastreá-las e +PROF info; +2 dano contra esse tipo.", "narrative_hint": "passive"},
            "Bestas":         {"descricao": "Especialista em bestas (animais): vantagem para rastrear, +PROF info, +2 dano.",                  "narrative_hint": "passive"},
            "Celestiais":     {"descricao": "Especialista em celestiais: vantagem para rastrear, +PROF info, +2 dano.",                       "narrative_hint": "passive"},
            "Constructos":    {"descricao": "Especialista em constructos: vantagem para rastrear, +PROF info, +2 dano.",                      "narrative_hint": "passive"},
            "Dragões":        {"descricao": "Especialista em dragões: vantagem para rastrear, +PROF info, +2 dano.",                          "narrative_hint": "passive"},
            "Elementais":     {"descricao": "Especialista em elementais: vantagem para rastrear, +PROF info, +2 dano.",                       "narrative_hint": "passive"},
            "Feéricos":       {"descricao": "Especialista em feéricos: vantagem para rastrear, +PROF info, +2 dano.",                         "narrative_hint": "passive"},
            "Infernais":      {"descricao": "Especialista em infernais (demônios/diabos): vantagem para rastrear, +PROF info, +2 dano.",      "narrative_hint": "passive"},
            "Gigantes":       {"descricao": "Especialista em gigantes: vantagem para rastrear, +PROF info, +2 dano.",                         "narrative_hint": "passive"},
            "Humanoides":     {"descricao": "Especialista em humanoides: vantagem para rastrear, +PROF info, +2 dano.",                       "narrative_hint": "passive"},
            "Mortos-vivos":   {"descricao": "Especialista em mortos-vivos: vantagem para rastrear, +PROF info, +2 dano.",                     "narrative_hint": "passive"},
            "Monstruosidades":{"descricao": "Especialista em monstruosidades: vantagem para rastrear, +PROF info, +2 dano.",                  "narrative_hint": "passive"},
            "Plantas":        {"descricao": "Especialista em plantas: vantagem para rastrear, +PROF info, +2 dano.",                          "narrative_hint": "passive"},
            "Limos":          {"descricao": "Especialista em limos: vantagem para rastrear, +PROF info, +2 dano.",                            "narrative_hint": "passive"},
        },
    },
    "Inimigo Favorecido Adicional": {  # 6º nível — herda mesmas opções
        "pick": 1,
        "pick_label": "tipo",
        "options": "ref:Inimigo Favorecido",  # resolvido em _get_variants()
    },
    # Patrulheiro — 1º nível (segundo terreno no 6º via "Explorador Natural Adicional")
    "Explorador Natural": {
        "pick": 1,
        "pick_label": "terreno",
        "options": {
            "Ártico":       {"descricao": "Em ambiente ártico: viagem normal em terreno difícil, sempre alerta, +PROF na busca por suprimentos.",     "narrative_hint": "passive"},
            "Costa":        {"descricao": "Em ambiente costeiro: viagem normal em terreno difícil, sempre alerta, +PROF na busca por suprimentos.",  "narrative_hint": "passive"},
            "Deserto":      {"descricao": "Em ambiente desértico: viagem normal em terreno difícil, sempre alerta, +PROF na busca por suprimentos.", "narrative_hint": "passive"},
            "Floresta":     {"descricao": "Em florestas: viagem normal em terreno difícil, sempre alerta, +PROF na busca por suprimentos.",          "narrative_hint": "passive"},
            "Pântano":      {"descricao": "Em pântanos: viagem normal em terreno difícil, sempre alerta, +PROF na busca por suprimentos.",           "narrative_hint": "passive"},
            "Montanha":     {"descricao": "Em montanhas: viagem normal em terreno difícil, sempre alerta, +PROF na busca por suprimentos.",          "narrative_hint": "passive"},
            "Planície":     {"descricao": "Em planícies: viagem normal em terreno difícil, sempre alerta, +PROF na busca por suprimentos.",          "narrative_hint": "passive"},
            "Subterrâneo":  {"descricao": "No subterrâneo: viagem normal em terreno difícil, sempre alerta, +PROF na busca por suprimentos.",        "narrative_hint": "passive"},
        },
    },
    "Explorador Natural Adicional": {  # 6º nível
        "pick": 1,
        "pick_label": "terreno",
        "options": "ref:Explorador Natural",
    },
    # Feiticeiro — 3º nível, escolhe 2 (+1 no 10º, +1 no 17º via "Metamagia Adicional")
    "Metamagia": {
        "pick": 2,
        "pick_label": "efeitos",
        "options": {
            "Sutil":       {"descricao": "1 ponto: conjura sem componente verbal nem somático (ignora silêncio/restrição de mãos).",                "narrative_hint": "active"},
            "Empoderada":  {"descricao": "1 ponto: re-rola até CAR (mín. 1) dados de dano de uma magia, usando o novo resultado.",                  "narrative_hint": "active"},
            "Distante":    {"descricao": "1 ponto: dobra o alcance da magia; ou em magias de Toque, vira alcance de 9m.",                            "narrative_hint": "active"},
            "Estendida":   {"descricao": "1 ponto: dobra a duração de magias com duração ≥ 1 min (máx. 24h).",                                       "narrative_hint": "active"},
            "Gêmea":       {"descricao": "Custo = nível da magia: alveja 1 criatura adicional (somente magias de alvo único).",                      "narrative_hint": "active"},
            "Cuidadosa":   {"descricao": "1 ponto: ao conjurar magia com save em área, até CAR aliados passam automaticamente.",                     "narrative_hint": "active"},
            "Acelerada":   {"descricao": "2 pontos: uma magia que normalmente tem tempo de conjuração 1 Ação vira 1 Ação Bônus.",                    "narrative_hint": "active"},
            "Intensificada":{"descricao": "3 pontos: 1 alvo da magia tem desvantagem no 1º save de resistência.",                                   "narrative_hint": "active"},
        },
    },
    "Metamagia Adicional": {
        "pick": 1,
        "pick_label": "efeito",
        "options": "ref:Metamagia",
    },
    # Bruxo — 2º nível, escolhe N (escala com nível)
    "Invocações Sobrenaturais": {
        "pick": 2,
        "pick_at_level": {2: 2, 5: 3, 7: 4, 9: 5, 12: 6, 15: 7, 18: 8},
        "pick_label": "invocações",
        "options": {
            "Agonizing Blast":     {"descricao": "Quando conjura Eldritch Blast, soma o mod. de CAR ao dano de cada raio.",            "narrative_hint": "passive"},
            "Repelling Blast":     {"descricao": "Eldritch Blast empurra criatura Grande ou menor em 3m.",                              "narrative_hint": "passive"},
            "Devil's Sight":       {"descricao": "Enxerga normalmente em escuridão mágica em raio de 36m.",                              "narrative_hint": "passive"},
            "Armor of Shadows":    {"descricao": "Conjura Mage Armor (em si) à vontade, sem gastar slot.",                              "narrative_hint": "active"},
            "Eldritch Sight":      {"descricao": "Conjura Detect Magic à vontade, sem gastar slot.",                                    "narrative_hint": "active"},
            "Fiendish Vigor":      {"descricao": "Conjura False Life (nv. 1) em si à vontade.",                                          "narrative_hint": "active"},
            "Mask of Many Faces":  {"descricao": "Conjura Disguise Self à vontade.",                                                     "narrative_hint": "active"},
            "Misty Visions":       {"descricao": "Conjura Silent Image à vontade.",                                                      "narrative_hint": "active"},
            "Beast Speech":        {"descricao": "Pode falar com bestas como na magia Speak with Animals, à vontade.",                  "narrative_hint": "active"},
            "Book of Ancient Secrets":{"descricao": "Pacto do Tomo: escreve magias de ritual (qualquer classe) no livro.",              "narrative_hint": "passive"},
            "Thirsting Blade":     {"descricao": "Pacto da Lâmina (nv.5+): ataca duas vezes com a arma do pacto ao usar Atacar.",       "narrative_hint": "passive"},
            "Lifedrinker":         {"descricao": "Pacto da Lâmina (nv.12+): arma causa +CAR dano necrótico extra.",                     "narrative_hint": "passive"},
            "Voice of the Chain Master":{"descricao": "Pacto da Corrente: comunica telepaticamente com o familiar.",                    "narrative_hint": "passive"},
            "Eldritch Mind":       {"descricao": "Vantagem em saves de CON para manter concentração em magias.",                         "narrative_hint": "passive"},
            "Gaze of Two Minds":   {"descricao": "Toca um humanoide consciente: vê pelos olhos dele por até 1h.",                       "narrative_hint": "active"},
        },
    },
}


def _get_variants(feature_name: str) -> dict | None:
    """Retorna metadata da feature com 'options' resolvido (se for ref:)."""
    v = FEATURE_VARIANTS.get(feature_name)
    if not v:
        return None
    opts = v.get("options")
    if isinstance(opts, str) and opts.startswith("ref:"):
        target = opts.split(":", 1)[1]
        ref = FEATURE_VARIANTS.get(target, {})
        return {**v, "options": ref.get("options", {})}
    return v


def _get_feature_choice(char: dict, feature_name: str):
    """Retorna a(s) escolha(s) atual(is) ou None."""
    fc = ((char or {}).get("sheet") or {}).get("feature_choices") or {}
    return fc.get(feature_name)


def _has_combat_style(char: dict, style: str) -> bool:
    """True se o personagem escolheu o estilo de combate informado."""
    return _get_feature_choice(char, "Estilo de Combate") == style


def _favored_enemy_types(char: dict) -> set[str]:
    """Conjunto normalizado de tipos de criatura favorecidos (em PT-BR)."""
    result = set()
    for feat in ("Inimigo Favorecido", "Inimigo Favorecido Adicional"):
        v = _get_feature_choice(char, feat)
        if isinstance(v, str) and v:
            result.add(_norm_txt(v))
        elif isinstance(v, list):
            for x in v:
                if x: result.add(_norm_txt(x))
    return result


# ── Fase 3: hooks mecânicos de sub-features de arquétipo ──────────────────
def _char_has_feature(char: dict, feature_name: str) -> bool:
    """True se o personagem tem a habilidade/feature pelo nome exato (case-insensitive)."""
    target = (feature_name or "").lower().strip()
    return any((h.get("nome", "") or "").lower().strip() == target
               for h in (char.get("habilidades") or []))


def _crit_threshold(char: dict) -> int:
    """
    Menor resultado de d20 que conta como acerto crítico.
    Campeão: Crítico Aprimorado (nv.3) → 19; Crítico Superior (nv.15) → 18.
    Padrão: 20.
    """
    if _char_has_feature(char, "Crítico Superior"):
        return 18
    if _char_has_feature(char, "Crítico Aprimorado"):
        return 19
    return 20


def _golpe_divino_info(char: dict) -> tuple[int, str] | None:
    """
    Detecta Golpe Divino (domínio de clérigo) ou Golpe Divino Aprimorado
    (paladino). Retorna (n_dados_d8, rótulo_do_tipo) ou None.

    • Clérigo: +1d8 (sobe a 2d8 a partir do nv. 14).
    • Paladino "Golpe Divino Aprimorado": +1d8 fixo, sempre radiante.
    """
    nivel = int((char.get("sheet") or {}).get("nivel", 1) or 1)
    for h in (char.get("habilidades") or []):
        nome = (h.get("nome", "") or "")
        if nome == "Golpe Divino Aprimorado":
            return (1, "radiante")
        if nome.startswith("Golpe Divino"):
            # Extrai o tipo de dano entre parênteses, se houver.
            tipo = "radiante"
            if "(" in nome and ")" in nome:
                inside = nome[nome.find("(") + 1:nome.find(")")].strip().lower()
                _TIPO_MAP = {
                    "vida": "radiante", "guerra": "do tipo escolhido",
                    "luz": "radiante", "conhecimento": "psíquico",
                    "natureza": "elemental", "tempestade": "trovão",
                    "ardil": "veneno",
                }
                tipo = _TIPO_MAP.get(inside, "radiante")
            return (2 if nivel >= 14 else 1, tipo)
    return None


# ── Armas pesadas (two-handed) — usado por Estilo de Combate ──────────────
TWO_HANDED_WEAPONS = {
    "espada grande", "espada de duas mãos", "greatsword",
    "machado grande", "greataxe",
    "maul", "marreta", "alabarda", "halberd",
    "lança", "pike", "pica",
    "glaive", "lança serrilhada",
    "arco longo", "longbow", "besta pesada", "heavy crossbow",
    "cajado quarterstaff",  # quando empunhado a duas mãos
    "maça grande", "maul de guerra",
}


# ────────────────────────────────────────────────────────────────────────────
# ARCHETYPE_FEATURES — arquétipos de classe e suas sub-features por nível.
#
# Cada feature de arquétipo (ex.: "Arquétipo Marcial") é uma escolha entre
# arquétipos (ex.: Campeão, Mestre de Batalha, Cavaleiro Élditch). Cada
# arquétipo concede sub-features automáticas em níveis específicos.
#
# Estrutura:
#   ARCHETYPE_FEATURES[<feature pai>][<nome do arquétipo>] = {
#     "descricao": str,         # 1 linha que descreve a temática
#     "features": {
#         <nível>: [
#             {"nome": str, "descricao": str, "dado": str, "custo_mana": int},
#             ...
#         ],
#         ...
#     },
#   }
#
# Ao module-load, _register_archetypes() flat-mapeia isso em:
#   • FEATURE_VARIANTS[<feature pai>]   — picker reusa o sistema da Fase 1.
#   • CLASS_FEATURE_DESCS[<sub-feat>]   — descrição visível em todo lugar.
#
# Para CONCEDER as sub-features quando o jogador escolhe (ou sobe de nível),
# ver _apply_archetype_features().
# ────────────────────────────────────────────────────────────────────────────
ARCHETYPE_FEATURES: dict[str, dict[str, dict]] = {
    # ── Guerreiro (Arquétipo Marcial — nv. 3) ──────────────────────────────
    "Arquétipo Marcial": {
        "Campeão": {
            "descricao": "Foco em força bruta, atletismo e críticos.",
            "features": {
                3:  [{"nome": "Crítico Aprimorado", "descricao": "Seus acertos críticos com armas ocorrem em 19 ou 20 no d20.", "dado": "", "custo_mana": 0}],
                7:  [{"nome": "Atleta Notável", "descricao": "Vantagem em testes de FOR (Atletismo). Pode saltar +mod. FOR metros e correr enquanto se levanta sem gastar deslocamento.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Estilo de Combate Adicional", "descricao": "Aprende um 2º Estilo de Combate da lista do Guerreiro.", "dado": "", "custo_mana": 0}],
                15: [{"nome": "Crítico Superior", "descricao": "Seus acertos críticos com armas ocorrem em 18, 19 ou 20 no d20.", "dado": "", "custo_mana": 0}],
                18: [{"nome": "Sobrevivente", "descricao": "No início do seu turno, recupera 5 + mod. CON de PV se estiver com ≤ metade dos PV (e ≥ 1).", "dado": "", "custo_mana": 0}],
            },
        },
        "Mestre de Batalha": {
            "descricao": "Manobras táticas, dados de superioridade.",
            "features": {
                3:  [
                    {"nome": "Manobras de Combate", "descricao": "Aprende 3 manobras da lista do Mestre de Batalha (Aparar, Desarmar, Empurrar, Investida, etc.).", "dado": "", "custo_mana": 0},
                    {"nome": "Dado de Superioridade", "descricao": "Pool de 4 dados d8 (sobe a d10 no 10º, d12 no 18º). Gasta-os para alimentar manobras. Recupera no descanso curto/longo.", "dado": "1d8", "custo_mana": 0},
                    {"nome": "Saber Estudante", "descricao": "Ganha proficiência em uma perícia OU ferramenta de artesão.", "dado": "", "custo_mana": 0},
                ],
                7:  [{"nome": "Resposta Tática", "descricao": "Vantagem em testes de iniciativa. Aliados adjacentes (1,5m) ganham +PROF em rolagens contra criaturas que você golpeou no turno.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Manobras Aprimoradas", "descricao": "Aprende mais 2 manobras. Dado de Superioridade sobe para d10.", "dado": "1d10", "custo_mana": 0}],
                15: [{"nome": "Manobras Relâmpago", "descricao": "Aprende mais 2 manobras. Mais 1 Dado de Superioridade no pool (total 6).", "dado": "", "custo_mana": 0}],
                18: [{"nome": "Manobra Suprema", "descricao": "Quando rola iniciativa sem Dados de Superioridade, recupera 1. Dado sobe para d12.", "dado": "1d12", "custo_mana": 0}],
            },
        },
        "Cavaleiro Élditch": {
            "descricao": "Combatente que mistura magia arcana com armas.",
            "features": {
                3:  [
                    {"nome": "Conjuração (Cavaleiro Élditch)", "descricao": "Conjura magias da lista de mago (foco em Abjuração e Evocação). Atributo de conjuração: INT.", "dado": "", "custo_mana": 0},
                    {"nome": "Vínculo com Arma", "descricao": "Ritual de 1h: vincula-se a até 2 armas. Pode invocá-las à mão como ação bônus.", "dado": "", "custo_mana": 0},
                ],
                7:  [{"nome": "Golpe Mágico", "descricao": "Ao acertar um ataque com arma, gasta uma reação para conjurar uma magia de truque contra o mesmo alvo.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Disparo Mágico", "descricao": "Conjura uma magia como ação e faz 1 ataque como ação bônus.", "dado": "", "custo_mana": 0}],
                15: [{"nome": "Vínculo Aprimorado", "descricao": "Quando acerta um crítico, pode rolar mais 1 dado de dano. Suas armas vinculadas contam como mágicas.", "dado": "", "custo_mana": 0}],
                18: [{"nome": "Vínculo Superior", "descricao": "Pode fazer 2 ataques no lugar de 1 ao usar Conjuração na mesma ação.", "dado": "", "custo_mana": 0}],
            },
        },
    },

    # ── Bárbaro (Caminho Primitivo — nv. 3) ────────────────────────────────
    "Caminho Primitivo": {
        "Berserker": {
            "descricao": "Caminho da fúria descontrolada e da carnificina.",
            "features": {
                3:  [{"nome": "Frenesi", "descricao": "Durante a fúria, pode entrar em Frenesi: ataque bônus corpo-a-corpo a cada turno, mas exaustão (1 nível) após a fúria.", "dado": "", "custo_mana": 0}],
                6:  [{"nome": "Furioso Implacável", "descricao": "Imune a Enfeitiçado e Amedrontado durante a fúria. Se já estava, o efeito é suspenso.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Presença Intimidadora", "descricao": "Ação: criatura em 9m faz save de SAB ou fica Amedrontada por 1 minuto.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Retaliação", "descricao": "Reação ao receber dano de criatura adjacente: faz um ataque corpo-a-corpo contra ela.", "dado": "", "custo_mana": 0}],
            },
        },
        "Guerreiro Totêmico": {
            "descricao": "Caminho da conexão com espíritos animais.",
            "features": {
                3:  [
                    {"nome": "Espírito Selvagem (Totem)", "descricao": "Escolhe um totem animal (Urso, Águia, Lobo, etc.) que concede um benefício passivo na fúria.", "dado": "", "custo_mana": 0},
                    {"nome": "Aspecto do Totem", "descricao": "Benefício passivo permanente baseado no totem (visão de Águia, rastreio de Lobo, etc.).", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Caminho do Andarilho", "descricao": "Comer/beber metade do normal. Resistência a clima extremo. Andar sobre superfícies não-sólidas (totem da Águia).", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Andarilho Espiritual", "descricao": "Conjura Sentir Inferior e Comungar com Natureza como rituais sem gastar slot.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Sintonia Totem", "descricao": "Outro benefício do totem escolhido, mais poderoso (ex.: Urso = aliados adjacentes têm vantagem em saves).", "dado": "", "custo_mana": 0}],
            },
        },
    },

    # ── Paladino (Juramento Sagrado — nv. 3) ───────────────────────────────
    "Juramento Sagrado": {
        "Devoção": {
            "descricao": "Juramento clássico do paladino justo.",
            "features": {
                3:  [
                    {"nome": "Canalizar Divindade (Arma Sagrada)", "descricao": "Ação: arma corpo-a-corpo brilha; +CAR atk e dano por 1 min ou até soltar.", "dado": "", "custo_mana": 0},
                    {"nome": "Canalizar Divindade (Repelir Mortos-Vivos)", "descricao": "Ação: mortos-vivos em 9m fazem save de SAB ou fogem amedrontados por 1 min.", "dado": "", "custo_mana": 0},
                ],
                7:  [{"nome": "Aura de Devoção", "descricao": "Você e aliados em 3m (6m no 18º) imunes a Enfeitiçado enquanto consciente.", "dado": "", "custo_mana": 0}],
                15: [{"nome": "Pureza de Espírito (Devoção)", "descricao": "Permanentemente sob Proteção contra o Mal e Bem.", "dado": "", "custo_mana": 0}],
                20: [{"nome": "Avatar Sagrado", "descricao": "Ação: 1 hora aura sagrada (vantagem em ataques contra você e aliados próximos resistem a dano).", "dado": "", "custo_mana": 0}],
            },
        },
        "Antigos": {
            "descricao": "Juramento da luz contra a corrupção e treva.",
            "features": {
                3:  [
                    {"nome": "Natureza Selvagem", "descricao": "Aprende Falar com Animais como magia de paladino.", "dado": "", "custo_mana": 0},
                    {"nome": "Canalizar Divindade (Tornado de Folhas)", "descricao": "Ação: criatura em 3m faz save de SAB ou fica Amedrontada de você por 1 min.", "dado": "", "custo_mana": 0},
                ],
                7:  [{"nome": "Aura de Combate", "descricao": "Você e aliados em 3m (6m no 18º) ganham resistência a dano de magias.", "dado": "", "custo_mana": 0}],
                15: [{"nome": "Inalterável", "descricao": "Imune a doença. Veneno sofre desvantagem e você resiste.", "dado": "", "custo_mana": 0}],
                20: [{"nome": "Campeão da Natureza", "descricao": "Ação: 1 min forma feérica (vantagem em saves de magia, cura 10 PV/turno, ataques causam +1d10 radiante).", "dado": "1d10", "custo_mana": 0}],
            },
        },
        "Vingança": {
            "descricao": "Juramento de retribuição contra a injustiça.",
            "features": {
                3:  [
                    {"nome": "Marca da Vingança", "descricao": "Reação ao ver criatura atacar aliado em 3m: ataque corpo-a-corpo contra ela.", "dado": "", "custo_mana": 0},
                    {"nome": "Canalizar Divindade (Voto de Inimizade)", "descricao": "Ação bônus: até 1 min, vantagem em todos os ataques contra a criatura marcada.", "dado": "", "custo_mana": 0},
                ],
                7:  [{"nome": "Implacável", "descricao": "Velocidade aumenta em 3m quando se move em direção a inimigo. Imune a Amedrontado.", "dado": "", "custo_mana": 0}],
                15: [{"nome": "Alma de Vingança", "descricao": "Ao usar Marca da Vingança, faz 2 ataques em vez de 1.", "dado": "", "custo_mana": 0}],
                20: [{"nome": "Anjo Vingador", "descricao": "Ação: 1h forma com asas voadora (18m), criaturas próximas amedrontadas, +CAR dano em ataques.", "dado": "", "custo_mana": 0}],
            },
        },
    },

    # ── Patrulheiro (Arquétipo do Patrulheiro — nv. 3) ─────────────────────
    "Arquétipo do Patrulheiro": {
        "Caçador": {
            "descricao": "Patrulheiro especialista em matar monstros perigosos.",
            "features": {
                3:  [{"nome": "Presa do Caçador", "descricao": "Escolhe uma das técnicas: Colossal (mais dano em alvos Grandes+), Massa (+atk vs grupos), Furtivo (+atk vs alvos isolados).", "dado": "", "custo_mana": 0}],
                7:  [{"nome": "Tática Defensiva", "descricao": "Escolhe Esquiva (não há vantagem contra você de criaturas a +1,5m), Coberta (escudo +1 CA contra projéteis) ou Bestial (CA +2 vs uma criatura Grande).", "dado": "", "custo_mana": 0}],
                11: [{"nome": "Ataque Múltiplo", "descricao": "Escolhe Volley (ataque ranged contra área 3m de raio) ou Tempestade Giratória (corpo-a-corpo contra todos os adjacentes).", "dado": "", "custo_mana": 0}],
                15: [{"nome": "Defesa Superior do Caçador", "descricao": "Escolhe Evasivo (+1 reação por turno), Inalterável (vantagem em saves de medo) ou Vingança Selvagem (+1d8 dano ao ser atingido).", "dado": "1d8", "custo_mana": 0}],
            },
        },
        "Senhor das Feras": {
            "descricao": "Patrulheiro com um companheiro animal devotado.",
            "features": {
                3:  [{"nome": "Companheiro Animal", "descricao": "Adquire uma besta CR ≤ 1/4 como aliado leal. Você compartilha iniciativa e ela age sob seu comando.", "dado": "", "custo_mana": 0}],
                7:  [{"nome": "Comunicação Exemplar", "descricao": "Pode dar 2 ordens à fera por turno e ela age automaticamente. Telepatia em 30m.", "dado": "", "custo_mana": 0}],
                11: [{"nome": "Defesa de Mestre", "descricao": "Atributos da fera escalam com seu nível. Ataques dela causam dano extra.", "dado": "", "custo_mana": 0}],
                15: [{"nome": "Recuperação Bestial", "descricao": "Pode usar uma reação para receber o dano destinado à sua fera.", "dado": "", "custo_mana": 0}],
            },
        },
    },

    # ── Bardo (Colégio Bárdico — nv. 3) ────────────────────────────────────
    "Colégio Bárdico": {
        "Saber": {
            "descricao": "Bardo erudito de magias secretas e perícias.",
            "features": {
                3:  [
                    {"nome": "Saber Estudante (Bardo)", "descricao": "Ganha proficiência em 3 perícias quaisquer.", "dado": "", "custo_mana": 0},
                    {"nome": "Especialização Cortês", "descricao": "Como reação ao ser alvo de atk/teste/save de habilidade visível, gasta Inspiração para diminuir o resultado.", "dado": "1d6", "custo_mana": 0},
                ],
                6:  [{"nome": "Segredos Adicionais (Saber)", "descricao": "Aprende 2 magias de qualquer classe (sem precisar esperar nv. 10).", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Inspiração Cortês", "descricao": "Aliado com seu d6 de inspiração pode reutilizá-lo após o efeito original.", "dado": "", "custo_mana": 0}],
            },
        },
        "Coragem": {
            "descricao": "Bardo guerreiro inspirador de combate.",
            "features": {
                3:  [
                    {"nome": "Inspiração de Combate", "descricao": "Aliado com seu dado de inspiração pode usá-lo como dado de dano OU para reagir e ganhar +CA.", "dado": "", "custo_mana": 0},
                    {"nome": "Estilo de Combate (Bardo)", "descricao": "Ganha proficiência em armaduras médias, escudo e armas marciais.", "dado": "", "custo_mana": 0},
                ],
                6:  [
                    {"nome": "Talento de Combate", "descricao": "Pode fazer 2 ataques em vez de 1 ao usar Atacar.", "dado": "", "custo_mana": 0},
                    {"nome": "Conjuração em Armadura", "descricao": "Pode conjurar magias usando armadura de combate.", "dado": "", "custo_mana": 0},
                ],
                14: [{"nome": "Batalha Inspiradora", "descricao": "Inicia o combate concedendo Inspiração a todos os aliados em 9m.", "dado": "", "custo_mana": 0}],
            },
        },
    },

    # ── Clérigo (Domínio Divino — nv. 1) ────────────────────────────────────
    "Domínio Divino": {
        "Vida": {
            "descricao": "Clérigo curandeiro consagrado à preservação.",
            "features": {
                1:  [
                    {"nome": "Treinamento em Armadura Pesada", "descricao": "Ganha proficiência em armaduras pesadas.", "dado": "", "custo_mana": 0},
                    {"nome": "Discípulo da Vida", "descricao": "Magias de cura curam +2 + nível da magia PV adicionais.", "dado": "", "custo_mana": 0},
                ],
                2:  [{"nome": "Canalizar Divindade (Preservar Vida)", "descricao": "Ação: divide nv. × 5 PV de cura entre aliados em 9m (cada um até metade do HP máx).", "dado": "", "custo_mana": 0}],
                6:  [{"nome": "Bênção do Cura", "descricao": "Quando cura, alvo ganha PV temporários iguais a 2× nv. clérigo.", "dado": "", "custo_mana": 0}],
                8:  [{"nome": "Golpe Divino (Vida)", "descricao": "1×/turno: ataque corpo-a-corpo causa +1d8 dano radiante (sobe a 2d8 no 14º).", "dado": "1d8", "custo_mana": 0}],
                17: [{"nome": "Renovação Suprema", "descricao": "Cura máxima rolada sempre (sem rolar dados de cura).", "dado": "", "custo_mana": 0}],
            },
        },
        "Guerra": {
            "descricao": "Clérigo de batalha, marcial e direto.",
            "features": {
                1:  [
                    {"nome": "Treinamento em Armadura Pesada", "descricao": "Ganha proficiência em armaduras pesadas e armas marciais.", "dado": "", "custo_mana": 0},
                    {"nome": "Sacerdote de Guerra", "descricao": "Ação bônus: faz 1 ataque adicional. Usos = mod. SAB por descanso longo.", "dado": "", "custo_mana": 0},
                ],
                2:  [{"nome": "Canalizar Divindade (Guiar Ataque)", "descricao": "Reação após errar atk: +10 no resultado (suficiente para acertar?).", "dado": "", "custo_mana": 0}],
                6:  [{"nome": "Ataque Vindouro", "descricao": "Quando crítica com arma, próximo ataque tem vantagem.", "dado": "", "custo_mana": 0}],
                8:  [{"nome": "Golpe Divino (Guerra)", "descricao": "1×/turno: ataque corpo-a-corpo causa +1d8 dano do tipo de sua escolha (sobe a 2d8 no 14º).", "dado": "1d8", "custo_mana": 0}],
                17: [{"nome": "Avatar da Batalha", "descricao": "1 min de resistência a todo dano físico não-mágico.", "dado": "", "custo_mana": 0}],
            },
        },
        "Conhecimento": {
            "descricao": "Clérigo erudito, buscador de segredos.",
            "features": {
                1:  [{"nome": "Bênção do Conhecimento", "descricao": "2 idiomas extras. Proficiência em 2 perícias (Arcana/Religião/História/Natureza) — dobradas.", "dado": "", "custo_mana": 0}],
                2:  [{"nome": "Canalizar Divindade (Ler Pensamentos)", "descricao": "Ação: criatura em 18m, save de SAB; falha = lê pensamentos por 1 min.", "dado": "", "custo_mana": 0}],
                6:  [{"nome": "Ler Pensamentos Aprimorado", "descricao": "Após ler pensamentos, pode lançar Sugestão sem gastar slot.", "dado": "", "custo_mana": 0}],
                8:  [{"nome": "Dano Potencializado (Conhecimento)", "descricao": "1×/turno: truque de dano causa +1d8 (sobe a 2d8 no 14º).", "dado": "1d8", "custo_mana": 0}],
                17: [{"nome": "Visões do Passado", "descricao": "1 min de meditação: ganha visões sobre criatura ou objeto.", "dado": "", "custo_mana": 0}],
            },
        },
        "Luz": {
            "descricao": "Clérigo de divindades solares e radiantes.",
            "features": {
                1:  [
                    {"nome": "Truque Bônus (Chamas Sagradas)", "descricao": "Aprende Chamas Sagradas (sacred flame) sem ocupar slot de truque.", "dado": "1d8", "custo_mana": 0},
                    {"nome": "Bandeira de Aviso", "descricao": "Reação ao ser atingido: impõe desvantagem no ataque. Usos = mod. SAB por descanso longo.", "dado": "", "custo_mana": 0},
                ],
                2:  [{"nome": "Canalizar Divindade (Radiância do Amanhecer)", "descricao": "Ação: esfera de luz 9m raio; criaturas hostis fazem save de CON ou 2d10+nv. dano radiante.", "dado": "2d10", "custo_mana": 0}],
                6:  [{"nome": "Bandeira de Aviso Aprimorada", "descricao": "Bandeira de Aviso também protege aliados em 9m.", "dado": "", "custo_mana": 0}],
                8:  [{"nome": "Golpe Divino (Luz)", "descricao": "1×/turno: truque/atk causa +1d8 radiante (sobe a 2d8 no 14º).", "dado": "1d8", "custo_mana": 0}],
                17: [{"nome": "Coroa da Luz", "descricao": "Ação: 1 min de coroa luminosa; magias hostis com save sofrem desvantagem perto.", "dado": "", "custo_mana": 0}],
            },
        },
        "Natureza": {
            "descricao": "Clérigo druídico, ponte entre fé e natureza.",
            "features": {
                1:  [
                    {"nome": "Acólito da Natureza", "descricao": "Truque de druida bônus + proficiência em uma perícia (Natureza, Sobrevivência, Adestramento).", "dado": "", "custo_mana": 0},
                    {"nome": "Treinamento em Armadura Pesada", "descricao": "Proficiência em armaduras pesadas.", "dado": "", "custo_mana": 0},
                ],
                2:  [{"nome": "Canalizar Divindade (Encantar Animais e Plantas)", "descricao": "Ação: animais/plantas em 9m, save de SAB; falha = Enfeitiçado por 1 min.", "dado": "", "custo_mana": 0}],
                6:  [{"nome": "Servidor da Natureza", "descricao": "Tropeça e mata animais menores com facilidade. Vantagem em saves contra magias de Encantamento.", "dado": "", "custo_mana": 0}],
                8:  [{"nome": "Golpe Divino (Natureza)", "descricao": "1×/turno: ataque com arma causa +1d8 elemental (escolha) (sobe a 2d8 no 14º).", "dado": "1d8", "custo_mana": 0}],
                17: [{"nome": "Mestre da Natureza", "descricao": "Comanda criaturas Enfeitiçadas por Encantar Animais e Plantas com mais precisão.", "dado": "", "custo_mana": 0}],
            },
        },
        "Tempestade": {
            "descricao": "Clérigo de deuses do raio e do trovão.",
            "features": {
                1:  [
                    {"nome": "Treinamento em Armadura Pesada e Marciais (Tempestade)", "descricao": "Proficiência em armaduras pesadas e armas marciais.", "dado": "", "custo_mana": 0},
                    {"nome": "Cólera Temporal", "descricao": "Reação ao ser atingido por inimigo em 1,5m: +2d8 dano de trovão a ele. Usos = mod. SAB por descanso longo.", "dado": "2d8", "custo_mana": 0},
                ],
                2:  [{"nome": "Canalizar Divindade (Trovão Destrutivo)", "descricao": "Ação: criaturas em 9m fazem save de CON; falha = 2d6 + nv. dano trovão (sucesso = metade).", "dado": "2d6", "custo_mana": 0}],
                6:  [{"nome": "Resistência da Tempestade", "descricao": "Resistência a dano de relâmpago e trovão.", "dado": "", "custo_mana": 0}],
                8:  [{"nome": "Golpe Divino (Tempestade)", "descricao": "1×/turno: ataque com arma causa +1d8 trovão (sobe a 2d8 no 14º).", "dado": "1d8", "custo_mana": 0}],
                17: [{"nome": "Trovão Estrondoso", "descricao": "Quando crítica, dano de trovão/relâmpago é maximizado.", "dado": "", "custo_mana": 0}],
            },
        },
        "Ardil": {
            "descricao": "Clérigo de deuses trapaceiros e ladinos.",
            "features": {
                1:  [{"nome": "Bênção do Trapaceiro", "descricao": "Ação: toca um aliado, dá vantagem em testes de DES (Furtividade) por 1 hora.", "dado": "", "custo_mana": 0}],
                2:  [{"nome": "Canalizar Divindade (Invocar Duplicação)", "descricao": "Ação: cria uma ilusão sua até 9m que pode falar e mover por 1 min.", "dado": "", "custo_mana": 0}],
                6:  [{"nome": "Bênção do Trapaceiro Aprimorada", "descricao": "Pode usar Bênção do Trapaceiro como ação bônus em 9m. Múltiplos alvos.", "dado": "", "custo_mana": 0}],
                8:  [{"nome": "Golpe Divino (Ardil)", "descricao": "1×/turno: ataque com arma causa +1d8 veneno (sobe a 2d8 no 14º).", "dado": "1d8", "custo_mana": 0}],
                17: [{"nome": "Trapaça Improvisada", "descricao": "Pode usar Canalizar Divindade duas vezes seguidas se inspirado.", "dado": "", "custo_mana": 0}],
            },
        },
    },

    # ── Druida (Círculo Druídico — nv. 2) ──────────────────────────────────
    "Círculo Druídico": {
        "Terra": {
            "descricao": "Druida do círculo dos sábios e dos lugares sagrados.",
            "features": {
                2:  [
                    {"nome": "Recuperação Natural", "descricao": "Em descanso curto: recupera slots de magia até metade do nível (1x/dia).", "dado": "", "custo_mana": 0},
                    {"nome": "Magias do Círculo (Terra)", "descricao": "Ganha magias adicionais ligadas ao terreno escolhido (Ártico, Costa, Deserto, etc.).", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Passos da Terra", "descricao": "Move-se em terreno difícil mágico sem penalidade. Imune a magias que retardam.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Refúgio da Natureza", "descricao": "Imune a doenças, venenos e proteção contra envelhecimento.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Santuário da Natureza", "descricao": "Bestas e plantas não atacam você a menos que provocadas.", "dado": "", "custo_mana": 0}],
            },
        },
        "Lua": {
            "descricao": "Druida especializado em Forma Selvagem de combate.",
            "features": {
                2:  [
                    {"nome": "Forma Selvagem do Combate", "descricao": "Pode adotar Forma Selvagem com CR ≤ 1 já no 2º nível. Forma Selvagem como ação bônus.", "dado": "", "custo_mana": 0},
                    {"nome": "Magias Lunares", "descricao": "Pode lançar Cura Ferimentos como ação bônus enquanto em Forma Selvagem.", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Forma Selvagem Primal", "descricao": "Suas formas selvagens contam como mágicas para resistência a dano.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Golpes Elementais", "descricao": "Ataques em Forma Selvagem causam +1d6 dano elemental escolhido.", "dado": "1d6", "custo_mana": 0}],
                14: [{"nome": "Mudança Imediata", "descricao": "Forma Selvagem como reação ao receber dano.", "dado": "", "custo_mana": 0}],
            },
        },
    },

    # ── Monge (Tradição Monástica — nv. 3) ──────────────────────────────────
    "Tradição Monástica": {
        "Mão Aberta": {
            "descricao": "Tradição clássica do monge artista marcial puro.",
            "features": {
                3:  [{"nome": "Técnicas da Mão Aberta", "descricao": "Ao usar Rajada de Golpes: pode derrubar, empurrar 4,5m, ou impedir reações do alvo.", "dado": "", "custo_mana": 0}],
                6:  [{"nome": "Corpo Curativo", "descricao": "Ação: cura nv. monge × 3 PV em si.", "dado": "", "custo_mana": 0}],
                11: [{"nome": "Trinta Anos de Tranquilidade", "descricao": "Ao fim do descanso longo, recebe efeito de Santuário gratuito.", "dado": "", "custo_mana": 0}],
                17: [{"nome": "Palma Vibrante Trêmula", "descricao": "1 Ki: atinge criatura com vibração; até 23 dias depois, ação para detonar e causar 10d10 necrótico (save CON metade).", "dado": "10d10", "custo_mana": 0}],
            },
        },
        "Sombras": {
            "descricao": "Tradição do monge furtivo, manipulador de sombras.",
            "features": {
                3:  [{"nome": "Artes Sombrias", "descricao": "Conjura Mãos Mágicas, Escuridão, Silêncio, Visão no Escuro, Passar sem Deixar Rastro com Ki.", "dado": "", "custo_mana": 0}],
                6:  [{"nome": "Salto Sombrio", "descricao": "Em áreas de escuridão: teletransporta-se até 18m para outra área sombra como ação bônus.", "dado": "", "custo_mana": 0}],
                11: [{"nome": "Manto Sombrio", "descricao": "Em luz fraca/escuridão: torna-se invisível como ação.", "dado": "", "custo_mana": 0}],
                17: [{"nome": "Oportunista", "descricao": "Reação: faz um ataque corpo-a-corpo contra criatura adjacente que foi atingida por um aliado.", "dado": "", "custo_mana": 0}],
            },
        },
        "Quatro Elementos": {
            "descricao": "Tradição do monge que canaliza elementais via Ki.",
            "features": {
                3:  [
                    {"nome": "Discípulo dos Elementos", "descricao": "Aprende uma Disciplina Elemental + a básica (Elemental Attunement).", "dado": "", "custo_mana": 0},
                    {"nome": "Conjuração Elemental", "descricao": "Gasta Ki para conjurar efeitos elementais (Sopro de Fogo, Punho de Pedra, etc.).", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Disciplina Elemental Adicional", "descricao": "Aprende mais 1 Disciplina Elemental.", "dado": "", "custo_mana": 0}],
                11: [{"nome": "Disciplina Elemental Avançada", "descricao": "Aprende mais 1 Disciplina (até nv. 5 de magia equivalente).", "dado": "", "custo_mana": 0}],
                17: [{"nome": "Mestre dos Elementos", "descricao": "Aprende todas as Disciplinas Elementais restantes.", "dado": "", "custo_mana": 0}],
            },
        },
    },

    # ── Ladino (Arquétipo de Ladrão — nv. 3) ───────────────────────────────
    "Arquétipo de Ladrão": {
        "Ladrão": {
            "descricao": "Arquétipo clássico de ladrão ágil e versátil.",
            "features": {
                3:  [
                    {"nome": "Mãos Rápidas", "descricao": "Ação Ardilosa pode incluir Prestidigitação, Roubar (Sleight of Hand), ou usar item.", "dado": "", "custo_mana": 0},
                    {"nome": "Acrobata de Combate", "descricao": "Subir e descer não custa deslocamento extra. Salto melhorado.", "dado": "", "custo_mana": 0},
                ],
                9:  [{"nome": "Ladrão Supremo", "descricao": "Vantagem em testes contra armadilhas e portas trancadas.", "dado": "", "custo_mana": 0}],
                13: [{"nome": "Uso Mágico de Itens", "descricao": "Pode usar itens mágicos como pergaminhos e varinhas mesmo de outras classes.", "dado": "", "custo_mana": 0}],
                17: [{"nome": "Reflexos do Ladrão", "descricao": "Tem 2 turnos no primeiro round (1 turno de iniciativa real, outro de iniciativa-PROF).", "dado": "", "custo_mana": 0}],
            },
        },
        "Assassino": {
            "descricao": "Ladrão letal especializado em mortes súbitas.",
            "features": {
                3:  [
                    {"nome": "Maestria do Disfarce", "descricao": "Proficiência em Kit de Envenenamento e Kit de Disfarce.", "dado": "", "custo_mana": 0},
                    {"nome": "Assassinato", "descricao": "Vantagem em atk contra alvo que ainda não agiu. Acerto contra surpreso = crítico.", "dado": "", "custo_mana": 0},
                ],
                9:  [{"nome": "Identidade Falsa", "descricao": "Pode criar identidades falsas críveis (1 semana para preparar).", "dado": "", "custo_mana": 0}],
                13: [{"nome": "Impostor", "descricao": "Pode imitar voz, modo de falar e comportamento de outra pessoa com perícia.", "dado": "", "custo_mana": 0}],
                17: [{"nome": "Golpe da Morte", "descricao": "Ao acertar atk com surpresa, save de CON ou dano dobrado.", "dado": "", "custo_mana": 0}],
            },
        },
        "Trapaceiro Arcano": {
            "descricao": "Ladrão que combina furtividade com magia arcana.",
            "features": {
                3:  [
                    {"nome": "Conjuração (Trapaceiro Arcano)", "descricao": "Conjura magias da lista de mago (foco em Encantamento/Ilusão). Atributo: INT.", "dado": "", "custo_mana": 0},
                    {"nome": "Mão Mística (Trapaceiro)", "descricao": "Aprende Mãos Mágicas (Mage Hand) que é invisível e usa Furtividade.", "dado": "", "custo_mana": 0},
                ],
                9:  [{"nome": "Truques da Mão Mística", "descricao": "Pode usar Mãos Mágicas para roubar bolsos, abrir trancas, sabotar à distância.", "dado": "", "custo_mana": 0}],
                13: [{"nome": "Versátil (Trapaceiro)", "descricao": "Pode trocar 1 magia conhecida quando sobe de nível.", "dado": "", "custo_mana": 0}],
                17: [{"nome": "Ladrão Élditch", "descricao": "Mãos Mágicas pode entregar magias de truque à distância.", "dado": "", "custo_mana": 0}],
            },
        },
    },

    # ── Mago (Tradição Arcana — nv. 2) — 8 escolas ─────────────────────────
    "Tradição Arcana": {
        "Abjuração": {
            "descricao": "Escola da proteção e bloqueio mágico.",
            "features": {
                2:  [
                    {"nome": "Salvaguarda do Abjurador", "descricao": "Ao conjurar magia de Abjuração: ganha pool de PV temporários = 2× nv. magia + INT.", "dado": "", "custo_mana": 0},
                    {"nome": "Recuperação Arcana (Abjuração)", "descricao": "Aprende a copiar magias de Abjuração no livro por metade do tempo/custo.", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Resistência Mágica Projetada", "descricao": "Reação: aliado em 9m alvo de magia pode usar SEU bônus de save em vez do dele.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Quebra de Magia Aprimorada", "descricao": "Dispelar magia tem +PROF e funciona automaticamente contra magias até nv. 3.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Resistência a Magia", "descricao": "Vantagem em saves contra magias.", "dado": "", "custo_mana": 0}],
            },
        },
        "Adivinhação": {
            "descricao": "Escola da clarividência e leitura do destino.",
            "features": {
                2:  [
                    {"nome": "Lampejos de Adivinhação", "descricao": "Após descanso longo: rola 2d20 e guarda. Pode substituir QUALQUER d20 (atk/teste/save) por um dos guardados.", "dado": "2d20", "custo_mana": 0},
                    {"nome": "Reservas de Adivinhação", "descricao": "Aprende a copiar magias de Adivinhação por metade do custo/tempo.", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Visão Aprofundada", "descricao": "Lampejos guardados sobem para 3d20 por descanso longo.", "dado": "3d20", "custo_mana": 0}],
                10: [{"nome": "Terceiro Olho", "descricao": "Visão Verdadeira por 1 min sem gastar slot. 1×/descanso curto.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Lampejos Aprimorados", "descricao": "Lampejos sobem para 4d20 por descanso longo.", "dado": "4d20", "custo_mana": 0}],
            },
        },
        "Conjuração": {
            "descricao": "Escola de invocação e manipulação de seres.",
            "features": {
                2:  [
                    {"nome": "Conjurador Minucioso", "descricao": "Aprende a copiar magias de Conjuração por metade do custo/tempo.", "dado": "", "custo_mana": 0},
                    {"nome": "Conjurar Item Menor", "descricao": "Ação: invoca item não-mágico pesando até 5kg na mão por 1 hora.", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Conjuração Veloz", "descricao": "Magias de Conjuração de 1 ação viram 1 ação bônus, 1×/descanso curto.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Teletransporte Pequeno", "descricao": "Ação bônus: teleporta-se até 9m a um local visível, 1×/turno.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Aliado Convocado Aprimorado", "descricao": "Criaturas convocadas por suas magias ganham +CD AC e +AC dano.", "dado": "", "custo_mana": 0}],
            },
        },
        "Encantamento": {
            "descricao": "Escola da manipulação mental e charme.",
            "features": {
                2:  [
                    {"nome": "Sussurros Encantadores", "descricao": "Aprende a copiar magias de Encantamento por metade do custo/tempo.", "dado": "", "custo_mana": 0},
                    {"nome": "Lapso de Memória", "descricao": "Quando enfeitiça humanoide, sua vítima esquece o evento depois.", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Mente Dividida", "descricao": "Mantém concentração em 2 magias de Encantamento simultaneamente.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Mago Encantador", "descricao": "Vantagem em saves contra Encantamento. Pode lançar uma cópia da magia recebida no atacante.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Encantamento Alterado", "descricao": "Quando enfeitiça humanoide, pode alterar sua personalidade durante a duração.", "dado": "", "custo_mana": 0}],
            },
        },
        "Evocação": {
            "descricao": "Escola do dano elemental direto.",
            "features": {
                2:  [
                    {"nome": "Esculpir Magias", "descricao": "Em magias de Evocação com save de DEX: até 1+nv. magia aliados na área passam automaticamente sem sofrer dano.", "dado": "", "custo_mana": 0},
                    {"nome": "Recuperação Arcana (Evocação)", "descricao": "Aprende a copiar magias de Evocação por metade do custo/tempo.", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Truque Potente", "descricao": "Magias de truque de Evocação causam dano + INT mesmo em falha (se aplicável).", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Truque Empoderado", "descricao": "Soma INT ao dano de TODOS os truques de Evocação.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Sobrecarga", "descricao": "1×/descanso longo: maximiza o dano da próxima magia de Evocação de nv. 1-5.", "dado": "", "custo_mana": 0}],
            },
        },
        "Ilusão": {
            "descricao": "Escola da falsidade e do engano.",
            "features": {
                2:  [
                    {"nome": "Ilusionista Melhorado", "descricao": "Aprende a copiar magias de Ilusão por metade do custo/tempo.", "dado": "", "custo_mana": 0},
                    {"nome": "Ilusão Menor Aprimorada", "descricao": "Pode lançar Ilusão Menor (Minor Illusion) com ambos os componentes (som E imagem).", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Ilusão Maleável", "descricao": "Pode alterar a forma/conteúdo de ilusões em andamento como ação.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Auto-Ilusão", "descricao": "Reação ao ser atingido: cria duplicata ilusória que assume o dano.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Realidade Ilusória", "descricao": "Suas ilusões podem se tornar reais por 1 min (objetos não-mágicos).", "dado": "", "custo_mana": 0}],
            },
        },
        "Necromancia": {
            "descricao": "Escola da morte, dos mortos e da vida drenada.",
            "features": {
                2:  [
                    {"nome": "Macabro", "descricao": "Aprende a copiar magias de Necromancia por metade do custo/tempo.", "dado": "", "custo_mana": 0},
                    {"nome": "Colhedor de Ceifa", "descricao": "Quando mata criatura com magia de Necromancia: ganha PV temporários = 2× nv. magia + INT.", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Comando dos Mortos-Vivos", "descricao": "Aprende Animar Mortos. Pode controlar mais esqueletos/zumbis que o normal.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Resiliência Insidiosa", "descricao": "Resistência a dano necrótico. Limite máximo de PV não pode ser reduzido.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Senhor dos Mortos-Vivos", "descricao": "Esqueletos e zumbis sob seu comando têm +PV e +dano.", "dado": "", "custo_mana": 0}],
            },
        },
        "Transmutação": {
            "descricao": "Escola da mudança de forma e propriedades.",
            "features": {
                2:  [
                    {"nome": "Aluno da Transmutação", "descricao": "Aprende a copiar magias de Transmutação por metade do custo/tempo.", "dado": "", "custo_mana": 0},
                    {"nome": "Pedra Transmutadora", "descricao": "Cria pedra mágica: dá um benefício escolhido (visão escuro/cativeiro/CON/resistência) por 8h.", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Recuperação do Transmutador", "descricao": "Pode usar Pedra Transmutadora para conjurar Cura Ferimentos nv. 5.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Mestre Transmutador", "descricao": "Usa Pedra Transmutadora para conjurar Polimorfismo (em si) sem slot.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Transmutação Suprema", "descricao": "Pedra Transmutadora ganha efeitos extras: rejuvenescimento, restaurar atributo, etc.", "dado": "", "custo_mana": 0}],
            },
        },
    },

    # ── Feiticeiro (Origem de Feiticeiro — nv. 1) ──────────────────────────
    "Origem de Feiticeiro": {
        "Linhagem Dracônica": {
            "descricao": "Poder vem de ancestral dragão.",
            "features": {
                1:  [
                    {"nome": "Ancestral Dracônico", "descricao": "Escolhe a cor do ancestral (vermelho/azul/verde/branco/preto/ouro/prata/etc) — define o tipo de dano resistido.", "dado": "", "custo_mana": 0},
                    {"nome": "Resistência Dracônica", "descricao": "+1 PV/nível. CA = 13 + DES quando sem armadura.", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Magia Elemental Afim", "descricao": "Magias do tipo de dano do ancestral causam +CAR de dano. Custo de mana reduzido em 1.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Asas Dracônicas", "descricao": "Ação bônus: faz crescer asas (mov. voo 18m) por 1 min.", "dado": "", "custo_mana": 0}],
                18: [{"nome": "Presença Dracônica", "descricao": "Ação: 1 min de aura de medo/admiração (3 pontos de feitiçaria).", "dado": "", "custo_mana": 0}],
            },
        },
        "Magia Selvagem": {
            "descricao": "Poder caótico e imprevisível das tempestades arcanas.",
            "features": {
                1:  [
                    {"nome": "Surto de Magia Selvagem", "descricao": "Quando conjura magia de nv. 1+: rola d20; em 1, mestre rola na tabela de Surto Selvagem (efeito aleatório).", "dado": "1d20", "custo_mana": 0},
                    {"nome": "Marés do Caos", "descricao": "1×/descanso longo: vantagem em 1 atk/teste/save. Mestre pode acionar Surto Selvagem depois.", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Esculpir o Caos", "descricao": "Gasta 2 PF para rolar na tabela de Surto Selvagem manualmente.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Recuperação Mágica (Selvagem)", "descricao": "Após Surto Selvagem, recupera 2d4 de Pontos de Feitiçaria.", "dado": "2d4", "custo_mana": 0}],
                18: [{"nome": "Magia Espontânea", "descricao": "Quando rola Surto Selvagem: pode escolher qualquer resultado da tabela.", "dado": "", "custo_mana": 0}],
            },
        },
    },

    # ── Bruxo (Patrono Sobrenatural — nv. 1) ───────────────────────────────
    "Patrono Sobrenatural": {
        "Arquifada": {
            "descricao": "Patrono é um senhor/senhora do reino feérico.",
            "features": {
                1:  [{"nome": "Presença Feérica", "descricao": "Ação: criaturas em cone 3m fazem save de SAB; falha = Enfeitiçado OU Amedrontado por 1 turno.", "dado": "", "custo_mana": 0}],
                6:  [{"nome": "Refúgio Feérico", "descricao": "Reação ao receber dano: teleporta-se 18m para outra área visível. Usos = PROF/descanso curto.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Visão Feérica", "descricao": "Imune a Enfeitiçado. Magias e itens não afetam sua mente.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Apenas Para Mim", "descricao": "Ação: criatura humanoide alvo, save SAB; falha = Enfeitiçada e fica entorpecida em transe.", "dado": "", "custo_mana": 0}],
            },
        },
        "Senhor Lich": {
            "descricao": "Patrono é um senhor lich, demônio ou diabo.",
            "features": {
                1:  [{"nome": "Resistência Sombria", "descricao": "Quando reduz humanoide a 0 PV, ganha PV temporários = nv. bruxo + CAR.", "dado": "", "custo_mana": 0}],
                6:  [{"nome": "Maldição do Patrono Sombrio", "descricao": "Ao errar atk contra criatura, próximo atk dela contra você falha.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Resistência Aprimorada", "descricao": "Resistência a 1 tipo de dano de sua escolha (entre fogo/frio/elétrico/necrótico).", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Hurl Through Hell", "descricao": "Ao acertar atk: alvo passa 1 turno no inferno; 10d10 dano psíquico ao voltar.", "dado": "10d10", "custo_mana": 0}],
            },
        },
        "Grande Antigo": {
            "descricao": "Patrono é uma entidade alienígena/cósmica.",
            "features": {
                1:  [{"nome": "Telepatia Tenebrosa", "descricao": "Comunicação telepática com qualquer criatura em 9m.", "dado": "", "custo_mana": 0}],
                6:  [{"nome": "Vingança do Grande Antigo", "descricao": "Quando alguém te ataca: dano psíquico = 1+CAR ao atacante (reação).", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Pensamento Inquebrantável", "descricao": "Imune a Enfeitiçado e Amedrontado. Vantagem em saves contra outras magias mentais.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Mestrado do Grande Antigo", "descricao": "Ação: força criatura visível em 18m a fazer atk/save por você (CAR vs INT/CAR).", "dado": "", "custo_mana": 0}],
            },
        },
    },

    # ── Bruxo (Bênção do Pacto — nv. 3) ────────────────────────────────────
    "Bênção do Pacto": {
        "Pacto da Lâmina": {
            "descricao": "Pacto que dá uma arma mágica vinculada.",
            "features": {
                3: [{"nome": "Arma do Pacto", "descricao": "Cria arma mágica em 1 hora ritual. Atk usa CAR. Pode invocar/dispensar como ação.", "dado": "", "custo_mana": 0}],
            },
        },
        "Pacto do Tomo": {
            "descricao": "Pacto que dá um livro com truques mágicos extras.",
            "features": {
                3: [{"nome": "Livro das Sombras", "descricao": "Recebe um livro com 3 truques de qualquer classe. Pode lançá-los à vontade enquanto o livro está em mãos.", "dado": "", "custo_mana": 0}],
            },
        },
        "Pacto da Corrente": {
            "descricao": "Pacto que dá um familiar único.",
            "features": {
                3: [{"nome": "Encontrar Familiar Aprimorado", "descricao": "Aprende Encontrar Familiar; pode invocar criaturas como imp, pseudodragão, quasit, sprite. Familiar pode atacar com sua reação.", "dado": "", "custo_mana": 0}],
            },
        },
    },
}


def _register_archetypes() -> None:
    """
    Module-load: popula FEATURE_VARIANTS e CLASS_FEATURE_DESCS a partir de
    ARCHETYPE_FEATURES. Mantém uma única fonte de verdade pros arquétipos.
    """
    for feat_name, archetypes in ARCHETYPE_FEATURES.items():
        # Registra a feature-pai como subescolha de arquétipo.
        if feat_name not in FEATURE_VARIANTS:
            FEATURE_VARIANTS[feat_name] = {
                "pick": 1,
                "pick_label": "arquétipo",
                "options": {
                    arch_name: {
                        "descricao": data.get("descricao", ""),
                        "narrative_hint": "passive",
                    }
                    for arch_name, data in archetypes.items()
                },
            }
        # Registra as descrições de cada sub-feature.
        for arch_name, data in archetypes.items():
            for lvl, sub_feats in (data.get("features") or {}).items():
                for sf in sub_feats:
                    name = sf.get("nome")
                    if not name:
                        continue
                    # Só registra se ainda não existir (não sobrescreve descrições
                    # personalizadas já em CLASS_FEATURE_DESCS).
                    if name not in CLASS_FEATURE_DESCS:
                        CLASS_FEATURE_DESCS[name] = {
                            "descricao":  sf.get("descricao", ""),
                            "custo_mana": int(sf.get("custo_mana", 0) or 0),
                            "dado":       sf.get("dado", ""),
                        }


_register_archetypes()


def _apply_archetype_features(char: dict, archetype_feature: str) -> list[str]:
    """
    Concede ao personagem todas as sub-features do arquétipo escolhido cujo
    nível de desbloqueio ≤ nível atual do char. Não duplica. Retorna lista
    de nomes recém-adicionados.

    Chamado de set_feature_choice (logo após escolher um arquétipo) e de
    _apply_class_features (quando o char sobe e novas sub-features liberam).
    """
    archetype = _get_feature_choice(char, archetype_feature)
    if not isinstance(archetype, str) or not archetype:
        return []
    arch_table = ARCHETYPE_FEATURES.get(archetype_feature, {}).get(archetype)
    if not arch_table:
        return []

    nivel    = int((char.get("sheet") or {}).get("nivel", 1) or 1)
    existing = {h.get("nome", "").lower() for h in char.get("habilidades", [])}
    added: list[str] = []
    for lvl_unlock, sub_feats in (arch_table.get("features") or {}).items():
        if lvl_unlock > nivel:
            continue
        for sf in sub_feats:
            name = sf.get("nome", "")
            if not name or name.lower() in existing:
                continue
            char.setdefault("habilidades", []).append({
                "nome":       name,
                "descricao":  sf.get("descricao", ""),
                "custo_mana": int(sf.get("custo_mana", 0) or 0),
                "dado":       sf.get("dado", ""),
            })
            existing.add(name.lower())
            added.append(name)
    return added


def reconcile_character_archetypes(char: dict) -> list[str]:
    """
    Garante que um personagem tenha TODAS as sub-features de arquétipo
    correspondentes às suas escolhas (sheet.feature_choices) e ao nível
    atual. Idempotente — seguro chamar várias vezes.

    Usado no save da campanha pelo editor: o picker do editor grava só a
    escolha localmente; esta função materializa as sub-features no backend
    antes de persistir. NÃO chama save_campaign (só muta o dict).

    Retorna lista de nomes de sub-features adicionadas.
    """
    if not isinstance(char, dict) or not char.get("sheet"):
        return []
    added: list[str] = []
    for arch_feat in ARCHETYPE_FEATURES.keys():
        if _get_feature_choice(char, arch_feat):
            added.extend(_apply_archetype_features(char, arch_feat))
    # Sub-features podem mexer na CA (ex.: Resistência Dracônica). Recalcula
    # se algo foi concedido.
    if added:
        try:
            _recalculate_ca(char)
        except Exception:
            pass
    return added


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

# ---------------------------------------------------------------------------
# Magias de controle/condição — NÃO causam dano, aplicam condições.
# "pool": True → o resultado do dado é um pool de HP (ex: Sleep):
#     o alvo dorme se HP_atual ≤ pool; pool é decrementado pelo HP do alvo.
# "pool": False → aplica a condição diretamente (Hold Person, Charm, etc.)
# ---------------------------------------------------------------------------
CONTROL_SPELL_EFFECTS: dict[str, dict] = {
    # Nível 1
    "sleep":                 {"condition": "Dormindo",     "pool": True},
    "color spray":           {"condition": "Cego",         "pool": True},
    # Nível 2
    "hold person":           {"condition": "Paralisado",   "pool": False},
    "blindness/deafness":    {"condition": "Cego",         "pool": False},
    "blindness deafness":    {"condition": "Cego",         "pool": False},
    "silence":               {"condition": "Silenciado",   "pool": False},
    "entangle":              {"condition": "Imobilizado",  "pool": False},
    # Nível 2–3
    "web":                   {"condition": "Imobilizado",  "pool": False},
    "hypnotic pattern":      {"condition": "Incapacitado", "pool": False},
    "fear":                  {"condition": "Amedrontado",  "pool": False},
    "slow":                  {"condition": "Lentidão",     "pool": False},
    "stinking cloud":        {"condition": "Envenenado",   "pool": False},
    # Encantamento
    "charm person":          {"condition": "Enfeitiçado",  "pool": False},
    "charm monster":         {"condition": "Enfeitiçado",  "pool": False},
    # Nível 4+
    "hold monster":          {"condition": "Paralisado",   "pool": False},
    "confusion":             {"condition": "Confuso",      "pool": False},
    "dominate person":       {"condition": "Dominado",     "pool": False},
    "dominate monster":      {"condition": "Dominado",     "pool": False},
    "banishment":            {"condition": "Banido",       "pool": False},
    "polymorph":             {"condition": "Transformado", "pool": False},
    "contagion":             {"condition": "Envenenado",   "pool": False},
    # Nível 5+
    "hold person (level 5)": {"condition": "Paralisado",   "pool": False},
    "wall of force":         {"condition": "Imobilizado",  "pool": False},
    "feeblemind":            {"condition": "Incapacitado", "pool": False},
    "power word stun":       {"condition": "Atordoado",    "pool": False},
    "power word kill":       {"condition": "Morto",        "pool": False},
}


def _get_control_effect(hab: dict) -> dict | None:
    """
    Retorna o efeito de controle se a habilidade for uma magia de condição, ou None.
    Aceita o nome em inglês (como armazenado) OU em português (magias do kit
    padrão / aprendidas com nome PT, ex: "Sono" → "sleep").
    """
    name_lower = hab.get("nome", "").lower().strip()
    eff = CONTROL_SPELL_EFFECTS.get(name_lower)
    if eff is None:
        en = _SPELL_PT_TO_EN.get(name_lower)
        if en:
            eff = CONTROL_SPELL_EFFECTS.get(en)
    return eff

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


def _fetch_armor_data(armor_name: str) -> dict | None:
    """
    Busca dados de armadura no Open5e como fallback quando o item não está em ARMOR_TABLE.
    Retorna dict no mesmo formato de ARMOR_TABLE ou None se não encontrado.
    """
    import requests as _req
    slug = armor_name.lower().strip().replace(" ", "-").replace("'", "")
    for attempt in [
        lambda: _req.get(f"https://api.open5e.com/v1/armor/{slug}/", timeout=4),
        lambda: _req.get("https://api.open5e.com/v1/armor/", params={"search": armor_name, "limit": 5}, timeout=4),
    ]:
        try:
            r = attempt()
            if not r.ok:
                continue
            data = r.json()
            # Endpoint de lista retorna {"results": [...]}
            if "results" in data:
                results = data["results"]
                if not results:
                    continue
                data = results[0]
            ac_data   = data.get("armor_class", {})
            ca_base   = int(ac_data.get("base", 10) or 10)
            dex_bonus = ac_data.get("dex_bonus", True)
            max_bonus = ac_data.get("max_bonus", None)
            if not dex_bonus:
                dex_rule = "none"
            elif max_bonus is not None and int(max_bonus or 0) == 2:
                dex_rule = "cap2"
            else:
                dex_rule = "full"
            return {"ca_base": ca_base, "dex_bonus": dex_rule, "slot": "armadura"}
        except Exception:
            continue
    return None


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
    # Inconsciente (Sleep, 0 HP): não age; ataques contra ele têm vantagem e
    # acertos corpo-a-corpo a até 1,5m são CRÍTICOS automáticos (regra 5e).
    "inconsciente":{"attack_disadvantage": True, "defense_disadvantage": True, "auto_crit": True},
    "imobilizado": {"attack_disadvantage": True, "defense_disadvantage": True},
    "lentidão":    {"attack_disadvantage": True},
    "silenciado":  {},
    "confuso":     {},
    "dominado":    {},
    "banido":      {},
    "transformado":{},
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


def _normalize_sheet(sheet: dict) -> None:
    """
    Garante que todos os campos numéricos da ficha sejam int.
    JSON importado pode trazer valores como strings — isso corrige silenciosamente.
    Chamado em _get_char toda vez que uma ficha é acessada.
    """
    INT_FIELDS = (
        "nivel", "xp", "xp_proximo", "proficiencia", "hit_die",
        "vida_atual", "vida_max", "mana_atual", "mana_max", "ca",
        "forca", "destreza", "constituicao", "inteligencia", "sabedoria", "carisma",
        "ouro", "prata", "cobre",
        "death_saves_sucessos", "death_saves_falhas",
    )
    for field in INT_FIELDS:
        if field in sheet and not isinstance(sheet[field], int):
            try:
                sheet[field] = int(sheet[field])
            except (ValueError, TypeError):
                sheet[field] = 0


def _get_char(name: str, allow_dead: bool = False) -> tuple[dict | None, str]:
    """Retorna (char_dict, erro). char é None se não encontrado, sem ficha ou morto."""
    char = memory.campaign["characters"].get(memory.char_key(name))
    if not char:
        return None, f"Personagem '{name}' não encontrado."
    if not char.get("sheet"):
        return None, f"'{name}' não tem ficha D&D. Use create_character_sheet primeiro."
    if not allow_dead and char.get("status") == "morto":
        return None, f"❌ {char['name']} está morto e não pode realizar ações."
    _normalize_sheet(char["sheet"])
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

    armor_data  = ARMOR_TABLE.get(armor_name) or _fetch_armor_data(armor_name)
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
        # Sem armadura: CA padrão 10 + DES.
        # Resistência Dracônica (Feiticeiro de Linhagem Dracônica): 13 + DES.
        if _char_has_feature(char, "Resistência Dracônica"):
            new_ca = 13 + dex
        else:
            new_ca = 10 + dex

    if shield_data and shield_data["dex_bonus"] == "shield":
        new_ca += shield_data["ca_base"]

    # ── Estilo de Combate: Defesa → +1 CA enquanto usando QUALQUER armadura.
    if armor_data and _has_combat_style(char, "Defesa"):
        new_ca += 1

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
            if not isinstance(bonus_entry, dict):
                continue
            attr_name = bonus_entry.get("ability_score", {}).get("name", "").lower()                         if isinstance(bonus_entry.get("ability_score"), dict)                         else bonus_entry.get("attribute", "")
            bonus_val = bonus_entry.get("bonus", 0)
            stat = _ATTR_MAP.get(attr_name.lower(), "")
            if stat and bonus_val:
                bonuses[stat] = bonuses.get(stat, 0) + bonus_val

        # Traços raciais — a API v1 retorna "traits" como STRING (texto markdown),
        # mas outras coleções podem trazer lista de dicts ou de strings.
        raw_traits = race_data.get("traits", [])
        if isinstance(raw_traits, list):
            for trait in raw_traits:
                if isinstance(trait, dict):
                    t_name = trait.get("name", "")
                    t_desc = " ".join((trait.get("desc") or "").split())[:200]
                    if t_name:
                        traits.append({"nome": t_name, "descricao": t_desc,
                                        "custo_mana": 0, "dado": ""})
                elif isinstance(trait, str) and trait.strip():
                    traits.append({"nome": trait.strip()[:60], "descricao": "",
                                    "custo_mana": 0, "dado": ""})

        # Se a API não trouxe bônus de atributo, usa a tabela offline canônica
        # (sem isso, raças como anão perdem o +CON racial e o HP fica errado).
        if not bonuses:
            bonuses = dict(_RACE_BONUS_FALLBACK.get(en_key, {}))
    else:
        # Fallback offline
        bonuses = dict(_RACE_BONUS_FALLBACK.get(en_key, {}))

    # Captura o modificador de CON ANTES dos bônus raciais para ajustar o HP
    # pelo delta sem destruir o HP acumulado nível-a-nível.
    con_before = _modifier(sheet.get("constituicao", 10))

    # Aplica bônus aos atributos da ficha
    for stat, bonus in bonuses.items():
        if stat in sheet:
            sheet[stat] += bonus

    # Ajusta stats derivados pelo DELTA do bônus racial.
    # CRÍTICO: NÃO recalcular vida_max pela fórmula de nível 1 — isso apagaria
    # todo o HP acumulado de personagens/NPCs de nível alto. Em D&D, cada nível
    # soma o modificador de CON ao HP, então um +1 de CON racial = +nivel de HP.
    con_after = _modifier(sheet.get("constituicao", 10))
    con_delta = con_after - con_before
    if con_delta:
        nivel     = sheet.get("nivel", 1)
        hp_adjust = con_delta * nivel
        sheet["vida_max"]   = max(1, sheet.get("vida_max", 1) + hp_adjust)
        sheet["vida_atual"] = sheet["vida_max"]
    # CA base (ainda sem equipamento na criação) — usa DES já com bônus racial
    sheet["ca"] = 10 + _modifier(sheet["destreza"])

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
    nivel: int = 1,
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
        nivel:         Nível inicial (1–20). Para NPCs de nível alto, passe o valor
                       correto aqui — HP, mana, proficiência e habilidades de classe
                       são calculados automaticamente para todos os níveis até este.
    """
    nivel        = max(1, min(20, int(nivel)))
    classe_lower = classe.lower()
    info         = CLASS_DATA.get(classe_lower, {"hit_die": 8, "mana_per_level": 4, "mana_stat": "inteligencia", "saves": []})

    con_mod  = _modifier(constituicao)
    dex_mod  = _modifier(destreza)
    hit_die  = info["hit_die"]

    # Nível 1: dado máximo + CON (regra do Player's Handbook para personagens de nível 1)
    hp_max = max(1, hit_die + con_mod)
    # Níveis 2+: rola hit die para cada nível adicional
    for _ in range(nivel - 1):
        hp_max += max(1, random.randint(1, hit_die) + con_mod)

    # Pool de mana pela tabela oficial de Pontos de Magia (DMG p.288):
    # depende só do nível de conjurador, nunca do atributo de conjuração.
    mana_max = _max_mana_for(classe_lower, nivel)

    prof = _proficiency_bonus(nivel)
    xp_threshold = XP_THRESHOLDS[nivel] if nivel < 20 else XP_THRESHOLDS[19]
    xp_start     = XP_THRESHOLDS[nivel - 1] if nivel > 1 else 0

    sheet = {
        "classe":       classe,
        "raca":         raca,
        "nivel":        nivel,
        "xp":           xp_start,
        "xp_proximo":   xp_threshold,
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
        "proficiencia": prof,
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

    # (O pool de mana NÃO é recalculado por bônus racial: na variante de
    # Pontos de Magia o pool depende só do nível, não do atributo.)

    # Aplica habilidades de classe para TODOS os níveis até o nível inicial
    all_feats: list[str] = []
    for lv in range(1, nivel + 1):
        all_feats.extend(_apply_class_features(char_obj, sheet, lv))

    # Aplica magias iniciais para classes conjuradoras (usa chosen_spells se fornecida)
    chosen = kwargs.get("initial_spells")  # lista opcional de nomes escolhidos pelo wizard
    spells_added = _apply_initial_spells(char_obj, classe, chosen_spells=chosen)
    spells_str = f"\n   ✨ Magias iniciais: {', '.join(spells_added)}" if spells_added else ""
    feats_str  = f"\n   📖 Habilidades de classe: {', '.join(all_feats)}" if all_feats else ""

    if not memory.campaign.get("protagonist"):
        memory.campaign["protagonist"] = name

    memory.save_campaign()
    return (
        f"✅ Ficha criada para {name}!\n"
        f"   Classe: {classe} | Raça: {raca} | Nível: {nivel} | Prof: +{prof}\n"
        f"   Bônus racial: {bonus_str}{spells_str}{feats_str}\n"
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
    char, err = _get_char(name, allow_dead=True)
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

# Mapa de perícias D&D 5e → atributo correspondente
SKILL_ATTR_MAP: dict[str, str] = {
    "atletismo":          "forca",
    "acrobacia":          "destreza",
    "furtividade":        "destreza",
    "prestidigitação":    "destreza",
    "manusear animais":   "sabedoria",
    "arcana":             "inteligencia",
    "história":           "inteligencia",
    "investigação":       "inteligencia",
    "natureza":           "inteligencia",
    "religião":           "inteligencia",
    "percepção":          "sabedoria",
    "intuição":           "sabedoria",
    "medicina":           "sabedoria",
    "sobrevivência":      "sabedoria",
    "enganação":          "carisma",
    "intimidação":        "carisma",
    "atuação":            "carisma",
    "persuasão":          "carisma",
    "lidar com animais":  "sabedoria",
}


def make_skill_check(
    char_name: str,
    attribute: str,
    difficulty: int,
    advantage: bool = False,
    disadvantage: bool = False,
    skill: str = "",
    player_roll: int = 0,
) -> str:
    """
    Realiza um teste de atributo: 1d20 + modificador vs Classe de Dificuldade.
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
        skill:        Nome da perícia (ex: 'atletismo', 'furtividade'). Resolve o atributo automaticamente.
        player_roll:  Resultado do d20 JÁ ROLADO pelo jogador (1–20). Quando o
                      teste é de um PERSONAGEM JOGÁVEL e o jogador rolou pela
                      bandeja de dados ("[DADO DO JOGADOR …] rolei X"), passe X
                      aqui — NUNCA role um d20 novo nem invente o valor. Deixe
                      0 para o mestre rolar (testes de NPC). Com player_roll,
                      vantagem/desvantagem são ignoradas (o jogador rolou uma
                      vez só).
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    # Se skill informada, resolve o atributo automaticamente
    if skill:
        resolved = SKILL_ATTR_MAP.get(skill.lower().strip())
        if resolved:
            attribute = resolved

    s        = char["sheet"]
    attr_key = attribute.lower()
    if attr_key not in STAT_NAMES:
        return f"Atributo '{attribute}' inválido. Use: {', '.join(sorted(STAT_NAMES))}."

    # Condições forçam desvantagem nos testes
    if _has_condition_effect(char, "check_disadvantage"):
        disadvantage = True

    attr_val = s[attr_key]
    mod      = _modifier(attr_val)
    # Usa a rolagem do JOGADOR quando fornecida e válida (1–20); senão o
    # mestre/sistema rola (com vantagem/desvantagem se aplicável).
    if isinstance(player_roll, int) and 1 <= player_roll <= 20:
        d20      = player_roll
        roll_log = f"d20={d20} (rolado pelo jogador)"
    else:
        d20, roll_log = _roll_d20_with_adv(advantage, disadvantage)
    total    = d20 + mod
    sign     = "+" if mod >= 0 else ""

    critico       = d20 == 20
    falha_critica = d20 == 1
    sucesso       = critico or (not falha_critica and total >= difficulty)

    skill_label = f"{skill.capitalize()} ({attribute.capitalize()})" if skill else attribute.capitalize()
    result = (
        f"🎲 Teste de {skill_label} — CD {difficulty}\n"
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


def social_check(
    char_name: str,
    skill: str,
    dc: int,
    player_roll: int,
    target_name: str = "",
) -> str:
    """
    Resolve um teste de interação social (Persuasão, Intimidação, Enganação, etc.)
    após o jogador informar o resultado do dado.

    FLUXO CORRETO:
      1. Mestre narra a situação e diz: "Role Persuasão (Carisma) — CD X"
      2. Jogador informa o resultado do d20 (ex: "tirei 14")
      3. Mestre chama social_check(char_name, 'persuasão', dc, player_roll=14)
      4. A ferramenta aplica o modificador e retorna sucesso/falha

    Use para: convencer NPCs, intimidar guardas, enganar vilões, barganhar preços,
    reunir informações, recrutar aliados.

    Args:
        char_name:   Nome do personagem que está fazendo a ação social.
        skill:       Perícia: 'persuasão', 'intimidação', 'enganação', 'atuação',
                     'intuição', 'percepção', 'investigação', 'história', 'arcana'.
        dc:          Classe de Dificuldade do teste.
        player_roll: Resultado do dado d20 informado pelo jogador (1–20).
        target_name: Nome do NPC alvo (opcional — usado para contextualizar o resultado).
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    skill_lower  = skill.lower().strip()
    attr_key     = SKILL_ATTR_MAP.get(skill_lower, "carisma")
    s            = char["sheet"]
    mod          = _modifier(s.get(attr_key, 10))
    prof         = s.get("proficiencia", 2)

    # Verifica proficiência na perícia (simplificado: guerreiros têm atletismo/intimidação,
    # bardos/ladinos têm persuasão/enganação, etc.)
    PROF_BY_CLASS = {
        "guerreiro": {"atletismo", "intimidação", "percepção", "sobrevivência", "história", "acrobacia"},
        "bárbaro":   {"atletismo", "intimidação", "percepção", "sobrevivência", "natureza", "manusear animais"},
        "ladino":    {"acrobacia", "atletismo", "enganação", "furtividade", "intimidação", "investigação",
                      "percepção", "atuação", "persuasão", "prestidigitação"},
        "bardo":     {"acrobacia", "enganação", "história", "intuição", "atuação", "persuasão"},
        "mago":      {"arcana", "história", "intuição", "investigação", "medicina", "religião"},
        "clérigo":   {"história", "intuição", "medicina", "persuasão", "religião"},
        "druida":    {"arcana", "intuição", "manusear animais", "medicina", "natureza", "percepção", "religião", "sobrevivência"},
        "paladino":  {"atletismo", "intuição", "intimidação", "medicina", "persuasão", "religião"},
        "patrulheiro": {"atletismo", "furtividade", "investigação", "natureza", "percepção", "sobrevivência"},
        "monge":     {"acrobacia", "atletismo", "história", "intuição", "religião", "furtividade"},
        "feiticeiro": {"arcana", "enganação", "intuição", "intimidação", "persuasão", "religião"},
        "bruxo":     {"arcana", "enganação", "história", "intimidação", "investigação", "natureza"},
    }
    classe       = s.get("classe", "").lower()
    is_proficient = skill_lower in PROF_BY_CLASS.get(classe, set())
    total_mod    = mod + (prof if is_proficient else 0)

    d20          = max(1, min(20, int(player_roll)))
    total        = d20 + total_mod
    sign         = "+" if total_mod >= 0 else ""

    critico      = d20 == 20
    falha_critica= d20 == 1
    sucesso      = critico or (not falha_critica and total >= dc)

    target_str   = f" com {target_name}" if target_name else ""
    prof_tag     = " (com prof.)" if is_proficient else ""
    skill_cap    = skill.capitalize()

    result = (
        f"🎭 Teste de {skill_cap}{prof_tag} — CD {dc}\n"
        f"   {char['name']}{target_str}: d20={d20} {sign}{total_mod}(mod) = **{total}**\n"
    )
    if critico:
        result += "   🌟 CRÍTICO NATURAL! Sucesso total — reação excepcionalmente positiva."
    elif falha_critica:
        result += "   💀 FALHA CRÍTICA! Falha total — reação negativa ou hostil."
    elif sucesso:
        result += f"   ✅ SUCESSO! ({total} ≥ CD {dc})"
    else:
        result += f"   ❌ FALHA. ({total} < CD {dc})"

    memory.save_campaign()
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
    _skip_turn_check: bool = False,
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
    if attacker.get("status") == "morto":
        return f"❌ {attacker_name} está morto e não pode atacar."
    if not target or not target.get("sheet"):
        return f"Alvo '{target_name}' não encontrado ou sem ficha D&D."

    # Auto-cura: nunca operar com o ponteiro preso num combatente fora de combate.
    _heal_current_turn()

    # AUTORIDADE DE TURNO: recusa ação fora de ordem antes de qualquer
    # mutação/dado. (_skip_turn_check=True só para chamadas internas do motor.)
    if not _skip_turn_check:
        _viol = _combat_turn_violation(attacker_name)
        if _viol:
            return _viol

    sa = attacker["sheet"]
    st = target["sheet"]

    # Se "weapon" é nome de uma habilidade da ficha do atacante, usa seus dados
    matched_hab = _match_ability(attacker, weapon)
    if matched_hab:
        hab_dado = matched_hab.get("dado", "")
        hab_mana = matched_hab.get("custo_mana", 0)
        if hab_mana > 0:
            return use_ability(attacker_name, weapon, target_name,
                               _skip_turn_check=_skip_turn_check)
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

    prof = sa.get("proficiencia", _proficiency_bonus(sa.get("nivel", 1))) if is_proficient else 0

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

    # ── Bônus por Estilo de Combate / Inimigo Favorecido ────────────────────
    # Calcula UMA vez e reusa para a linha de log e para o cálculo final.
    weapon_l   = (weapon or "").lower()
    is_ranged  = any(r in weapon_l for r in RANGED_WEAPONS)
    is_2h_wpn  = any(w in weapon_l for w in TWO_HANDED_WEAPONS)
    has_off    = bool(sa.get("equipamentos", {}).get("arma_secundaria"))
    style      = _get_feature_choice(attacker, "Estilo de Combate")
    style_atk_bonus = 0   # +2 atk (Arquearia)
    style_dmg_bonus = 0   # +2 dmg (Duelo / Combate Duas Armas via mod off-hand)
    style_reroll_low = False  # Grande Arma re-rola 1s e 2s no dado de dano
    style_note     = ""
    if style == "Arquearia" and is_ranged:
        style_atk_bonus = 2
        style_note     = "🏹 Estilo: Arquearia → +2 atk à distância"
    elif style == "Duelo" and not is_ranged and not is_2h_wpn and not has_off:
        style_dmg_bonus = 2
        style_note      = "🗡️ Estilo: Duelo → +2 dano (arma 1h, sem off-hand)"
    elif style == "Grande Arma" and not is_ranged and is_2h_wpn:
        style_reroll_low = True
        style_note       = "🪓 Estilo: Grande Arma → re-rola 1s/2s no dado"
    # "Combate com Duas Armas" → o bônus se aplica APENAS no ataque off-hand;
    # como esse fluxo é orquestrado pela LLM com 2 chamadas separadas, ela já
    # informa quando é o off-hand passando attack_attribute manualmente. Por
    # enquanto deixamos como instrução narrativa.

    # Inimigo Favorecido: +2 dano contra criatura cujo tipo de monstro
    # bate com o tipo escolhido. Usa o campo sheet["tipo"] (preenchido por
    # spawn_monster / create_npcs_with_real_stats via Open5e) ou cai no
    # raca como fallback.
    favored = _favored_enemy_types(attacker)
    favored_bonus = 0
    if favored:
        target_type = _norm_txt(
            st.get("tipo", "") or st.get("raca", "")
        )
        # Match por substring — "humanoid (orc)" casa com "humanoides"
        if target_type and any(t.rstrip("s") in target_type for t in favored):
            favored_bonus = 2
            style_note = (style_note + " · " if style_note else "") + "🎯 Inimigo Favorecido → +2 dano"

    # ── Golpe Divino (Domínio de Clérigo / Paladino) ────────────────────────
    # +1d8 (2d8 a partir do nv. 14) de dano elemental UMA vez por turno, ao
    # acertar com arma corpo-a-corpo. Gating 1×/turno via turn_token quando
    # há combate ativo; fora de combate, aplica a cada ataque.
    gd_info = None          # (n_dados, tipo) ou None
    if not is_ranged and not matched_hab:
        _gd = _golpe_divino_info(attacker)
        if _gd:
            _cs_gd   = memory.campaign.get("combat_state", {}) or {}
            _tk_now  = int(_cs_gd.get("turn_token", 0) or 0)
            _gd_used = sa.get("_gd_turn_token")
            if (not _cs_gd.get("is_active")) or _gd_used != _tk_now:
                gd_info = _gd

    # ── Crítico Aprimorado / Superior (Campeão) ─────────────────────────────
    crit_min = _crit_threshold(attacker)

    # ── Rolagem do ataque ───────────────────────────────────────────────────
    d20, roll_log = _roll_d20_with_adv(advantage, disadvantage)
    attack_total  = d20 + mod + prof + style_atk_bonus
    target_ca     = st["ca"]
    critico       = force_crit or (d20 >= crit_min)
    falha_critica = (not force_crit) and (d20 == 1)
    if critico and crit_min < 20 and not force_crit and d20 < 20:
        style_note = (style_note + " · " if style_note else "") + \
                     f"🌟 Crítico ampliado ({crit_min}-20)"

    result = f"⚔️  {attacker['name']} ataca {target['name']} com {weapon}!\n"
    if cond_notes:
        result += "   " + "\n   ".join(cond_notes) + "\n"
    if style_note:
        result += f"   {style_note}\n"
    _atk_style_str = f" +{style_atk_bonus}(estilo)" if style_atk_bonus else ""
    result += f"   {roll_log} +{mod}(mod) +{prof}(prof){_atk_style_str} = **{attack_total}** vs CA {target_ca}\n"

    if falha_critica:
        result += "   💀 ERRO CRÍTICO! O ataque falha miseravelmente."
        _log_combat_event("attack_fumble", attacker["name"], target["name"],
                          msg=(f"{attacker['name']} → {target['name']} ({weapon}): "
                               f"🎲 d20=1 → ERRO CRÍTICO"),
                          weapon=weapon, d20=1, atk_total=attack_total,
                          ca=target_ca)
        if end_turn:
            result += _auto_advance_turn(attacker_name)
        memory.save_campaign()
        return result

    if critico or attack_total >= target_ca:
        n_dice = damage_dice_count * (2 if critico else 1)
        rolls  = [random.randint(1, damage_dice_sides) for _ in range(n_dice)]
        # Grande Arma: re-rola UMA VEZ cada 1 ou 2 inicial (mantém o novo
        # resultado mesmo que seja 1/2 de novo). Marca o que foi re-rolado.
        rerolled = []
        if style_reroll_low:
            for i, r in enumerate(rolls):
                if r <= 2:
                    new_r = random.randint(1, damage_dice_sides)
                    rerolled.append((i, r, new_r))
                    rolls[i] = new_r
        # Golpe Divino: dados extras d8 (dobram no crítico, como smite).
        gd_rolls: list[int] = []
        gd_total = 0
        if gd_info:
            gd_n, gd_tipo = gd_info
            gd_count = gd_n * (2 if critico else 1)
            gd_rolls = [random.randint(1, 8) for _ in range(gd_count)]
            gd_total = sum(gd_rolls)
            # Consome o uso do turno (1×/turno via turn_token).
            sa["_gd_turn_token"] = int(
                (memory.campaign.get("combat_state", {}) or {}).get("turn_token", 0) or 0
            )

        extra_dmg = style_dmg_bonus + favored_bonus
        dmg    = max(1, sum(rolls) + mod + _hab_bonus + extra_dmg + gd_total)
        detail = " + ".join(str(r) for r in rolls)
        bonus_str = f" +{_hab_bonus}" if _hab_bonus > 0 else (f" {_hab_bonus}" if _hab_bonus < 0 else "")
        if extra_dmg:
            bonus_str += f" +{extra_dmg}(estilo/favor)"
        if gd_total:
            bonus_str += f" +{gd_total}(golpe divino)"

        result += f"   {'🌟 CRÍTICO! ' if critico else ''}✅ ACERTO!\n"
        if rerolled:
            _rr = ", ".join(f"{old}→{new}" for _, old, new in rerolled)
            result += f"   🪓 Grande Arma re-rolou: {_rr}\n"
        if gd_rolls:
            result += (f"   ⚡ Golpe Divino: {len(gd_rolls)}d8 "
                       f"[{' + '.join(str(r) for r in gd_rolls)}] = {gd_total} "
                       f"dano {gd_tipo}\n")
        result += f"   Dano: [{detail}] +{mod}(mod){bonus_str} = **{dmg}**\n"

        hp_antes       = st["vida_atual"]
        st["vida_atual"] = max(0, st["vida_atual"] - dmg)
        hp_depois      = st["vida_atual"]
        pct            = hp_depois / st["vida_max"] if st["vida_max"] > 0 else 0

        result += f"   {target['name']}: ❤️  {hp_antes} → {hp_depois}/{st['vida_max']}"
        _dmg_expr = f"[{detail}] +{mod}(mod){bonus_str} = {dmg}"
        _log_combat_event(
            "attack_crit" if critico else "attack_hit",
            attacker["name"], target["name"],
            msg=(f"{attacker['name']} → {target['name']} ({weapon}): "
                 f"🎲 d20={d20} +{mod}+{prof} = {attack_total} vs CA {target_ca} • "
                 f"{'🌟 CRÍTICO ' if critico else ''}ACERTO • "
                 f"💥 dano {_dmg_expr} → HP {hp_antes}→{hp_depois}/{st['vida_max']}"),
            weapon=weapon, d20=d20, atk_total=attack_total, ca=target_ca,
            dmg=dmg, dmg_dice=detail, hp=hp_depois, hp_max=st["vida_max"],
            crit=bool(critico),
        )
        _was_asleep = (target.get("status", "") or "").lower() == "dormindo"
        if hp_depois == 0:
            target["status"] = "inconsciente"
            result += " ⚠️  INCONSCIENTE!"
            _log_combat_event("down", attacker["name"], target["name"],
                              msg=f"{target['name']} caiu inconsciente")
        elif _was_asleep:
            # 5e: uma criatura dormindo (Sleep) acorda ao sofrer dano.
            _wake_sleeper(target)
            result += f" ⏰ {target['name']} acordou com o golpe!"
            _log_combat_event("wake", attacker["name"], target["name"],
                              msg=f"{target['name']} acordou ao sofrer dano")
        elif pct <= 0.25:
            result += " ⚠️  Estado crítico!"

        memory.save_campaign()
    else:
        result += f"   ❌ ERROU! ({attack_total} < CA {target_ca})"
        _log_combat_event("attack_miss", attacker["name"], target["name"],
                          msg=(f"{attacker['name']} → {target['name']} ({weapon}): "
                               f"🎲 d20={d20} +{mod}+{prof} = {attack_total} "
                               f"vs CA {target_ca} • ERROU"),
                          weapon=weapon, d20=d20, atk_total=attack_total,
                          ca=target_ca)

    if end_turn:
        result += _auto_advance_turn(attacker_name)
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
    char = memory.campaign["characters"].get(memory.char_key(char_name))
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
    _skip_turn_check: bool = False,
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
        ability_name:      Nome exato da habilidade (sempre em inglês, como armazenado na ficha).
        target_name:       Alvo(s). Para magias de área com pool (Sleep, Color Spray):
                           passe nomes separados por vírgula ("Goblin A, Goblin B, Goblin C").
                           A magia ordena automaticamente por HP crescente e drena o pool.
                           Para dano/cura/condição direta: apenas um nome.
                           Se vazio em magias de pool, auto-detecta inimigos do combate.
        saving_throw_stat: Atributo do alvo para resistência (ex: 'destreza', 'constituicao').
        saving_throw_dc:   CD do saving throw (ex: 14). Ignorado se saving_throw_stat vazio.
        end_turn:          Se True (padrão), avança o turno ao final.
                           Passe False para habilidades de ação bônus.
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    # Auto-cura do ponteiro de turno antes de validar/gastar mana.
    _heal_current_turn()

    # AUTORIDADE DE TURNO: recusa uso fora de ordem antes de gastar mana/dado.
    if not _skip_turn_check:
        _viol = _combat_turn_violation(char_name)
        if _viol:
            return _viol

    habs = char.get("habilidades", [])
    # Exact match (case-insensitive)
    hab  = next((h for h in habs if h["nome"].lower() == ability_name.lower()), None)
    # Fallback: try PT-BR → EN translation
    if not hab:
        en_name = _SPELL_PT_TO_EN.get(ability_name.lower())
        if en_name:
            hab = next((h for h in habs if h["nome"].lower() == en_name.lower()), None)
    if not hab:
        available = ", ".join(h["nome"] for h in habs) if habs else "nenhuma"
        return f"'{char_name}' não conhece '{ability_name}'. Habilidades disponíveis: {available}."

    # ── Coerção de alvo por modo da habilidade ────────────────────────────
    # Self-only (Segunda Fôlego, Fúria, Surto de Ação…) sempre afeta o
    # próprio conjurador, ignorando o que a UI/LLM passou como target.
    if _is_self_only_ability(hab.get("nome", "")) or _is_self_only_ability(ability_name):
        target_name = char["name"]

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
    ctrl_effect = _get_control_effect(hab)
    # Inicializa lista de afetados por pool spell — usada no log mesmo
    # quando o branch pool não roda (mantém escopo seguro).
    slept: list[str] = []

    # ══════════════════════════════════════════════════════════════════════════
    # POOL SPELLS (Sleep, Color Spray, …)
    # Mechanic D&D 5e: rola dado → pool de HP.
    # Ordena alvos por HP crescente; vai "gastando" o pool do menor para o maior.
    # Nenhum dano é aplicado — criaturas apenas adormecem/ficam cegas.
    # target_name: nomes separados por vírgula OU vazio (auto-detecta inimigos).
    # ══════════════════════════════════════════════════════════════════════════
    if ctrl_effect is not None and ctrl_effect["pool"]:
        pool = total_dano
        cond = ctrl_effect["condition"]
        caster_key = memory.char_key(char_name)

        # Pool spells (Sleep, Color Spray) são SEMPRE área: ignoram o
        # target_name passado pela UI e afetam TODOS os inimigos vivos da
        # ordem de iniciativa, ordenados por HP crescente. O target_name
        # serve apenas como hint visual no log.
        cs = memory.campaign.get("combat_state", {})
        raw_names = [
            k for k in cs.get("initiative_order", [])
            if memory.char_key(k) != caster_key
            and not memory.campaign["characters"]
                       .get(memory.char_key(k), {}).get("party_member")
        ]
        # Se ainda assim a UI passou nomes explícitos (uso narrado pela LLM),
        # mescla — preserva intenção sem perder a natureza de área.
        if target_name:
            for t in target_name.split(","):
                t = t.strip()
                if t and t not in raw_names:
                    raw_names.append(t)

        # Resolve personagens válidos (vivos, com sheet)
        candidates: list[dict] = []
        for raw in raw_names:
            key   = memory.char_key(raw)
            tchar = memory.campaign["characters"].get(key) \
                    or memory.campaign["characters"].get(raw)
            if (tchar and tchar.get("sheet")
                    and memory.char_key(tchar.get("name", "")) != caster_key
                    and (tchar.get("status") or "").lower()
                        not in ("morto", "inconsciente", "fugiu", "dormindo")):
                candidates.append(tchar)

        # Ordena por HP atual crescente (mais fraco dorme primeiro)
        candidates.sort(key=lambda c: c["sheet"]["vida_atual"])

        remaining = pool
        for tchar in candidates:
            if remaining <= 0:
                break
            hp = tchar["sheet"]["vida_atual"]
            if hp <= remaining:
                remaining -= hp
                tconds = tchar["sheet"].setdefault("condicoes", [])
                if not any(c["nome"].lower() == cond.lower() for c in tconds):
                    tconds.append({"nome": cond.capitalize(), "duracao": None})
                # Sleep → status "dormindo": a criatura fica incapacitada
                # (pula a vez), mas continua VIVA — o combate NÃO acaba só
                # por isso. Color Spray apenas cega (a criatura ainda age),
                # então não mexe no status.
                if cond.lower() in ("dormindo", "inconsciente"):
                    tchar["status"] = "dormindo"
                slept.append(f"{tchar['name']} ({hp} HP)")

        # Monta linha de resultado do pool
        result += f"\n   🎯 Pool: **{pool} HP**"
        if slept:
            result += f"\n   💤 Dormindo: {', '.join(slept)}"
            result += f"\n   Pool usado: {pool - remaining} HP | Restante: {remaining} HP"
        else:
            result += "\n   ⚪ Nenhum alvo foi afetado — todos têm HP alto demais."

    # ══════════════════════════════════════════════════════════════════════════
    # EFEITOS DE ALVO ÚNICO (cura / condição direta / dano)
    # ══════════════════════════════════════════════════════════════════════════
    elif target_name:
        # Para condições diretas e dano, pega o primeiro nome (ignora vírgulas extras)
        primary_target = target_name.split(",")[0].strip()
        target = memory.campaign["characters"].get(memory.char_key(primary_target))
        if target and target.get("sheet"):
            st = target["sheet"]

            # ── MODO INTERATIVO: saving throw → PAUSA, não aplica efeito ──────
            if saving_throw_stat and saving_throw_dc > 0:
                memory.save_campaign()
                if ctrl_effect is not None:
                    cond_nome = ctrl_effect["condition"]
                    efeito_falha   = f"{cond_nome.upper()} aplicado"
                    efeito_sucesso = "sem efeito"
                    return (
                        result +
                        f"\n\n⏸️  **AGUARDANDO TESTE DE RESISTÊNCIA**\n"
                        f"   Alvo: {target['name']}\n"
                        f"   Atributo: {saving_throw_stat.capitalize()} | CD: {saving_throw_dc}\n"
                        f"   Efeito (falha): **{efeito_falha}** | Efeito (sucesso): **{efeito_sucesso}**\n"
                        f"\n💬 Mestre: Role {saving_throw_stat.capitalize()} CD {saving_throw_dc}!\n"
                        f"   Se falhar: use apply_condition('{target['name']}', '{cond_nome}')."
                    )
                else:
                    return (
                        result +
                        f"\n\n⏸️  **AGUARDANDO TESTE DE RESISTÊNCIA**\n"
                        f"   Alvo: {target['name']}\n"
                        f"   Atributo: {saving_throw_stat.capitalize()} | CD: {saving_throw_dc}\n"
                        f"   Dano (falha): **{total_dano}** | Dano reduzido (sucesso): **{total_dano // 2}**\n"
                        f"\n💬 Mestre: Role {saving_throw_stat.capitalize()} CD {saving_throw_dc}!\n"
                        f"   Após resultado, use modify_hp para aplicar o dano correto."
                    )

            # ── MODO AUTOMÁTICO: aplica efeito imediatamente ─────────────────
            hp_antes = st["vida_atual"]

            if _is_healing_ability(hab):
                st["vida_atual"] = min(st["vida_max"], st["vida_atual"] + total_dano)
                result += f"\n   {target['name']}: ❤️  {hp_antes} → {st['vida_atual']}/{st['vida_max']}"
                if hp_antes == 0:
                    target["status"] = "vivo"
                    st["death_saves_sucessos"] = 0
                    st["death_saves_falhas"]   = 0
                    result += " ✨ Estabilizado!"
                elif st["vida_atual"] == st["vida_max"]:
                    result += " ✨ Vida plena!"

            elif ctrl_effect is not None:
                # Condição direta (Hold Person, Charm, Web, etc.) — sem dano
                cond  = ctrl_effect["condition"]
                conds = st.setdefault("condicoes", [])
                if not any(c["nome"].lower() == cond.lower() for c in conds):
                    conds.append({"nome": cond.capitalize(), "duracao": None})
                result += f"\n   🔴 {target['name']}: {cond.upper()}! (sem dano)"

            else:
                # Dano direto
                st["vida_atual"] = max(0, st["vida_atual"] - total_dano)
                result += f"\n   {target['name']}: ❤️  {hp_antes} → {st['vida_atual']}/{st['vida_max']}"
                if st["vida_atual"] == 0:
                    target["status"] = "inconsciente"
                    result += " ⚠️  INCONSCIENTE!"
                    _log_combat_event("down", char["name"], target["name"],
                                      msg=f"{target['name']} caiu inconsciente")

    # ── Linha do log da habilidade ────────────────────────────────────────
    # Para pool spells (Sleep, Color Spray) o dado representa um POOL de HP,
    # NÃO dano. Mostra explicitamente quem foi afetado para não parecer dano.
    _abil_dice = ""
    if hab.get("dado"):
        _abil_dice = (f" • 🎲 {n_dice}d{sides}: [{detail}]{bonus_str} "
                      f"= {total_dano}")
    if ctrl_effect is not None and ctrl_effect.get("pool"):
        cond_emoji = "💤" if ctrl_effect.get("condition", "").lower() in ("inconsciente", "dormindo") else "🔴"
        if hab.get("dado"):
            _abil_dice = (f" • 🎲 {n_dice}d{sides} (pool): [{detail}]{bonus_str} "
                          f"= {total_dano} HP")
        if slept:
            _abil_dice += f" • {cond_emoji} {', '.join(slept)}"
        else:
            _abil_dice += " • ⚪ ninguém foi afetado (HP alto demais)"

    _log_combat_event(
        "ability", char["name"], target_name,
        msg=(f"{char['name']} usou {hab['nome']}"
             + (f" em {target_name}" if target_name and not (ctrl_effect and ctrl_effect.get('pool')) else "")
             + _abil_dice),
        ability=hab["nome"], dado=hab.get("dado", ""),
        rolls=list(rolls), total=total_dano,
    )
    memory.save_campaign()
    if end_turn:
        result += _auto_advance_turn(char_name)
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
    char, err = _get_char(char_name, allow_dead=True)
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

def roll_death_save(char_name: str, player_roll: int = 0) -> str:
    """
    Realiza um Teste de Morte para um personagem com HP = 0 (inconsciente).
    Avalia 1d20 limpo:
    • Natural 20: recupera 1 ponto de vida e estabiliza (testes zerados).
    • 10 ou mais: 1 sucesso (3 sucessos = estabilizado).
    • 9 ou menos: 1 falha (3 falhas = morto).
    • Natural 1: conta como 2 falhas.

    Chame esta ferramenta a cada turno enquanto o personagem estiver inconsciente
    e sem aliados para estabilizá-lo.

    Args:
        char_name:   Nome do personagem inconsciente.
        player_roll: Resultado do d20 JÁ ROLADO pelo jogador (1–20). Quando o
                     teste de morte é de um PERSONAGEM JOGÁVEL, peça o dado ao
                     jogador, espere a resposta ("[DADO DO JOGADOR …] rolei X")
                     e passe esse X aqui. NUNCA role um d20 novo nem invente o
                     valor — isso descartaria a rolagem real do jogador. Deixe
                     0 apenas para NPCs, quando o sistema deve rolar sozinho.
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    s = char["sheet"]

    if s["vida_atual"] > 0:
        return f"⚠️  {char['name']} não está inconsciente (HP: {s['vida_atual']}). Teste de Morte não aplicável."

    # Usa a rolagem do JOGADOR quando fornecida e válida (1–20). Só rola
    # internamente quando nenhum valor veio (teste de morte de NPC).
    if isinstance(player_roll, int) and 1 <= player_roll <= 20:
        roll = player_roll
    else:
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
        char["status"]            = "estabilizado"
        result += (f"\n   🏥 {char['name']} ESTABILIZOU! Permanece inconsciente (0 HP) "
                   f"mas não morrerá. Precisa de cura para voltar a agir.")

        _log_combat_event("stabilize", char["name"], "",
                          msg=f"{char['name']} estabilizou (🎲 d20={roll}, inconsciente)",
                          d20=roll)
    elif s.get("death_saves_falhas", 0) >= 3:
        s["death_saves_sucessos"] = 0
        s["death_saves_falhas"]   = 0
        char["status"]            = "morto"
        result += f"\n   ☠️  {char['name']} MORREU. Narre a cena de forma dramática e definitiva."
        _log_combat_event("death", char["name"], "",
                          msg=f"{char['name']} morreu (🎲 d20={roll})", d20=roll)

    memory.save_campaign()
    result += _auto_advance_turn(char_name)
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
    char, err = _get_char(char_name, allow_dead=True)
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

        # Mana recalculada pela tabela oficial (DMG p.288). É um lookup por
        # nível, não um acumulador — isso corrige a inconsistência antiga em
        # que o modificador de atributo era perdido a cada level-up.
        mana_antes    = s.get("mana_max", 0)
        novo_mana_max = _max_mana_for(s.get("classe", ""), s["nivel"])
        mana_gain     = novo_mana_max - mana_antes
        if novo_mana_max != mana_antes:
            s["mana_max"]   = novo_mana_max
            s["mana_atual"] = novo_mana_max

        s["xp_proximo"] = XP_THRESHOLDS[s["nivel"]] if s["nivel"] < 20 else s["xp"]

        result += (
            f"\n🎉 LEVEL UP! {char['name']} agora é Nível {s['nivel']}!"
            f"\n   ❤️  Vida máxima: +{hp_gain} → {s['vida_max']}"
            f"\n   🛡️  Proficiência: +{s['proficiencia']}"
        )
        if mana_gain > 0:
            result += f"\n   ✨ Mana máxima: +{mana_gain} → {s['mana_max']}"

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
    char, err = _get_char(char_name, allow_dead=True)
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


def use_hit_die(char_name: str, count: int = 1) -> str:
    """
    Usa dados de vida para recuperar HP durante um descanso curto.
    Cada dado de vida: 1d[hit_die] + modificador de CON por dado.
    Os dados gastos se renovam no descanso longo.
    Rastreia dados disponíveis na ficha (máximo = nível do personagem).

    Use quando o jogador escolhe gastar dados de vida específicos.
    Prefira short_rest() para descanso curto completo.

    Args:
        char_name: Nome do personagem.
        count:     Número de dados de vida a usar (padrão: 1).
    """
    char, err = _get_char(char_name, allow_dead=True)
    if not char:
        return err

    s       = char["sheet"]
    hit_die = CLASS_DATA.get(s.get("classe", "").lower(), {}).get("hit_die", 8)
    nivel   = s.get("nivel", 1)

    hd_max       = nivel
    hd_restantes = s.setdefault("hit_dice_remaining", hd_max)

    if hd_restantes <= 0:
        return (
            f"❌ {char['name']} não tem dados de vida disponíveis.\n"
            f"   Faça um descanso longo para recuperar todos os {hd_max} dados."
        )

    count = max(1, min(int(count), hd_restantes))
    con_mod   = _modifier(s["constituicao"])
    rolls     = [random.randint(1, hit_die) for _ in range(count)]
    total_heal = max(count, sum(rolls) + con_mod * count)

    hp_antes        = s["vida_atual"]
    s["vida_atual"] = min(s["vida_max"], s["vida_atual"] + total_heal)
    s["hit_dice_remaining"] = hd_restantes - count
    hp_ganho        = s["vida_atual"] - hp_antes

    memory.save_campaign()

    con_str    = f" {'+' if con_mod >= 0 else ''}{con_mod * count}(CON×{count})" if con_mod != 0 else ""
    detail_str = " + ".join(str(r) for r in rolls) if count > 1 else str(rolls[0])
    return (
        f"🎲 {char['name']} usa {count}d{hit_die}: [{detail_str}]{con_str} = +{hp_ganho} PV\n"
        f"   ❤️  {hp_antes} → {s['vida_atual']}/{s['vida_max']}\n"
        f"   Dados de vida restantes: {s['hit_dice_remaining']}/{hd_max}"
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

    # Bloqueia descanso longo durante combate ativo
    cs = memory.campaign.get("combat_state", {})
    if cs.get("is_active"):
        return (
            f"❌ Impossível descansar — {char_name} está em combate!\n"
            f"   Encerre o combate com end_combat() antes de descansar."
        )

    s = char["sheet"]
    s["vida_atual"] = s["vida_max"]
    s["mana_atual"] = s["mana_max"]
    s["hit_dice_remaining"] = s.get("nivel", 1)  # Renova dados de vida no descanso longo
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
    char, err = _get_char(char_name, allow_dead=True)
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

    key     = stat_name.lower()
    old_val = s.get(key, "?")

    # Se for um atributo (ability score), recalcula os derivados:
    # CON → HP por nível | DES → CA | atributo de conjuração → mana.
    extra = ""
    if key in STAT_NAMES and isinstance(old_val, int):
        old_mod = _modifier(old_val)
        s[key]  = value
        new_mod = _modifier(value)
        delta   = new_mod - old_mod
        nivel   = s.get("nivel", 1)

        if key == "constituicao" and delta:
            hp_adj          = delta * nivel
            s["vida_max"]   = max(1, s.get("vida_max", 1) + hp_adj)
            s["vida_atual"] = max(0, min(s["vida_max"], s.get("vida_atual", 0) + hp_adj))
            extra += f"\n   ❤️  Vida máx: {hp_adj:+d} → {s['vida_max']}"

        if key == "destreza":
            ca_antes = s.get("ca", 10)
            _recalculate_ca(char)
            if s.get("ca", ca_antes) != ca_antes:
                extra += f"\n   🛡️  CA: {ca_antes} → {s['ca']}"

        # O pool de mana NÃO muda ao alterar o atributo de conjuração — na
        # variante de Pontos de Magia ele depende só do nível. O atributo
        # segue afetando CD de magia e ataques mágicos, não o tamanho do pool.
    else:
        s[key] = value

    memory.save_campaign()
    return f"✅ {char['name']}: {stat_name} {old_val} → {value}.{extra}"


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
    names = (
        characters_names if isinstance(characters_names, list)
        else [n.strip() for n in characters_names.split(",") if n.strip()]
    )
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

        # Combate NOVO: limpa estados transitórios herdados da luta anterior
        # — ninguém entra dormindo nem "inconsciente" com a vida cheia.
        _normalize_for_new_combat(char)

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
    # Combate NOVO: zera o rastreamento de turno (não herdar do anterior).
    cs["turn_resolved"]      = False
    cs["turn_auto_advanced"] = False
    cs["turn_token"]         = cs.get("turn_token", 0) + 1
    cs["log"]                = []     # log limpo a cada combate
    cs["result"]             = None   # resultado do combate anterior limpo
    _log_combat_event("combat_start", msg="Combate iniciado",
                      order=[r["name"] for r in results])

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

    # Auto-cura: se o atual morreu/fugiu "no lugar", desencalha o ponteiro
    # ANTES da trava de idempotência (senão ela reportaria um morto).
    _tk_before_heal = cs.get("turn_token", 0)
    _heal_current_turn()
    cs = memory.campaign.get("combat_state", {})
    if not cs.get("is_active"):
        return "🏳️  Combate encerrado — nenhum combatente restante."
    order = cs.get("initiative_order", [])
    if not order:
        return "🏳️  Combate encerrado."

    # Se a auto-cura JÁ avançou o ponteiro (o atual havia saído de combate),
    # ESSE foi o avanço deste next_turn() — não avançar de novo (senão pula
    # um combatente vivo). Apenas reporta.
    if cs.get("turn_token", 0) != _tk_before_heal:
        cs["turn_auto_advanced"] = False
        memory.save_campaign()
        idx = cs.get("current_turn_index", 0)
        cur = order[idx] if 0 <= idx < len(order) else "?"
        round_n = cs.get("round", 1)
        order_str = " → ".join(f"[{n}]" if i == idx else n for i, n in enumerate(order))
        return (
            f"⏭️  Turno avançado (combatente anterior saiu de combate) — "
            f"Rodada {round_n}\n🎯 Vez de: **{cur}**\n   Ordem: {order_str}"
        )

    # Trava de idempotência: se a ferramenta de ação (attack_roll / use_ability /
    # roll_death_save) já avançou o turno automaticamente, next_turn() não avança
    # de novo — apenas confirma quem é a vez atual e limpa a flag.
    if cs.get("turn_auto_advanced", False):
        cs["turn_auto_advanced"] = False
        memory.save_campaign()
        idx      = cs.get("current_turn_index", 0)
        current  = order[idx] if idx < len(order) else "?"
        round_n  = cs.get("round", 1)
        order_str = " → ".join(f"[{n}]" if i == idx else n for i, n in enumerate(order))
        return (
            f"ℹ️  Turno já avançado pela ferramenta de ação.\n"
            f"⏭️  Rodada {round_n} — vez de: **{current}**\n"
            f"   Ordem: {order_str}"
        )

    OUT_OF_COMBAT = OUT_OF_COMBAT_STATUSES   # inclui "dormindo" → pula a vez

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
        cs["turn_resolved"]      = False
        cs["turn_token"]         = cs.get("turn_token", 0) + 1  # avanço real
        _reset_turn_economy(cs)
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
    _log_combat_event("combat_end", msg="Combate encerrado")
    cs["is_active"]           = False
    cs["initiative_order"]    = []
    cs["current_turn_index"]  = 0
    cs["round"]               = 1
    # Acorda quem ficou DORMINDO — o efeito de Sleep não persiste após a
    # luta (jamais deve vazar para o próximo combate ou para a ficha).
    for _ch in memory.campaign.get("characters", {}).values():
        _wake_sleeper(_ch)
    memory.save_campaign()
    return "🏳️  Combate encerrado. Iniciativa e rastreador de turnos limpos."


# ---------------------------------------------------------------------------
# Recrutamento de NPC para o grupo
# ---------------------------------------------------------------------------

def recruit_character(npc_name: str, role: str = "aliado") -> str:
    """
    Recruta um NPC para o grupo do jogador, transformando-o em aliado ativo.
    Use quando um NPC convencido, salvo ou contratado passa a acompanhar o grupo.

    O personagem é marcado como 'aliado' e passa a:
    • Receber XP junto com o grupo após combates
    • Aparecer no painel de personagens como membro do grupo
    • Participar de combates como aliado (não inimigo)
    • Ganhar turnos automáticos via execute_npc_turn() se o mestre quiser

    Se o NPC ainda não tem uma ficha D&D completa (tem apenas ficha padrão
    com classe='npc'), o sistema preserva a ficha genérica mas muda o status.
    Para um aliado importante, crie a ficha completa antes com
    create_character_sheet() se quiser regras de classe reais.

    Args:
        npc_name: Nome exato do NPC a recrutar.
        role:     'aliado' (padrão) — membro do grupo.
                  'neutro' — acompanha mas não é aliado de combate.
    """
    key  = memory.char_key(npc_name)
    char = memory.campaign["characters"].get(key)

    if not char:
        return (
            f"❌ '{npc_name}' não encontrado na campanha. "
            f"Crie a ficha primeiro com create_character_sheet() ou roll_initiative()."
        )

    # ── Verificação de disparidade de nível ─────────────────────────────────
    npc_sheet   = char.get("sheet", {})
    npc_nivel   = npc_sheet.get("nivel", 1)

    # Calcula nível médio do grupo usando a definição canônica de grupo
    # (memory.is_party_member: party_member, protagonista ou campaign["party"]).
    # Exclui NPCs soltos, mortos/inimigos/fugidos e o próprio NPC sendo recrutado.
    party_chars = [
        c for c in memory.campaign.get("characters", {}).values()
        if memory.is_party_member(c)
        and c.get("status") not in ("morto", "inimigo", "fugiu")
        and memory.char_key(c["name"]) != key
    ]
    if party_chars:
        avg_nivel = sum(c.get("sheet", {}).get("nivel", 1) for c in party_chars) / len(party_chars)
    else:
        avg_nivel = 1

    level_gap = npc_nivel - avg_nivel

    # Bloqueia recrutamento de NPCs muito mais poderosos — narrativamente impossível
    if level_gap >= 10:
        return (
            f"🚫 RECRUTAMENTO BLOQUEADO — disparidade de poder extrema.\n"
            f"   {char['name']} é Nível {npc_nivel}; grupo em torno de Nível {avg_nivel:.0f}.\n"
            f"   Um personagem {int(level_gap)} níveis acima não tem motivo narrativo para "
            f"se juntar como subordinado a um grupo iniciante.\n"
            f"   ALTERNATIVAS VÁLIDAS:\n"
            f"   • Mentor: {char['name']} oferece treinamento ou informação ao grupo.\n"
            f"   • Missão: aceita ajudar SE o grupo completar uma tarefa para ele.\n"
            f"   • Aliança temporária: coopera em uma situação específica sem sair com o grupo.\n"
            f"   • Promessa futura: 'Quando forem dignos, voltem me ver.'\n"
            f"   Não chame recruit_character() — narre uma dessas alternativas."
        )

    # Aviso para disparidade moderada (5-9 níveis) — possível com justificativa forte
    if level_gap >= 5:
        warning = (
            f"⚠️  AVISO: {char['name']} é Nível {npc_nivel}, "
            f"{int(level_gap)} níveis acima do grupo (Nível ~{avg_nivel:.0f}).\n"
            f"   Recrutamento só faz sentido com justificativa narrativa muito forte\n"
            f"   (dívida de vida, missão pessoal urgente, único capaz de ajudar, etc.).\n"
        )
    else:
        warning = ""
    # ────────────────────────────────────────────────────────────────────────

    old_status   = char.get("status", "desconhecido")
    valid_roles  = {"aliado", "neutro"}
    role_clean   = role.strip().lower() if role.strip().lower() in valid_roles else "aliado"

    char["status"] = role_clean

    # Garante que o personagem apareça na lista do grupo (campo party_member)
    char["party_member"] = True

    sheet  = char.get("sheet", {})
    classe = sheet.get("classe", "npc")
    nivel  = sheet.get("nivel", 1)
    hp     = sheet.get("vida_atual", "?")
    hp_max = sheet.get("vida_max", "?")

    memory.save_campaign()

    role_label = "membro do grupo" if role_clean == "aliado" else "acompanhante neutro"
    classe_note = (
        " (ficha genérica — use create_character_sheet() para dar classe real)"
        if classe.lower() == "npc" else f" | Classe: {classe} | Nível: {nivel}"
    )
    return (
        f"{warning}"
        f"🤝 {char['name']} agora é {role_label}!\n"
        f"   Status anterior: {old_status} → {role_clean}\n"
        f"   ❤️  Vida: {hp}/{hp_max} | CA: {sheet.get('ca', '?')}{classe_note}\n"
        f"   {char['name']} passará a receber XP junto com o grupo e participará "
        f"de combates como aliado."
    )


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

    # O save ocorre durante o turno do CONJURADOR (use_ability pausou sem
    # avançar). O ponteiro ainda aponta para ele → avança a partir do atual.
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
    Também concede sub-features de arquétipos já escolhidos cujo nível
    de desbloqueio bate com o novo nível (ex.: Crítico Superior do
    Campeão libera no 15º). Não duplica habilidades já existentes.

    Retorna lista de nomes adicionados (incluindo sub-features de arquétipo).
    """
    classe   = sheet.get("classe", "").lower()
    features = CLASS_LEVEL_FEATURES.get(classe, {}).get(new_level, [])
    existing = {h.get("nome", "").lower() for h in char.get("habilidades", [])}
    added: list[str] = []

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
        existing.add(feat_name.lower())
        added.append(feat_name)

    # Sub-features de arquétipos: para cada feature de arquétipo já escolhida,
    # concede o que o novo nível desbloqueou. Idempotente (não duplica).
    for arch_feat in ARCHETYPE_FEATURES.keys():
        if _get_feature_choice(char, arch_feat):
            sub_added = _apply_archetype_features(char, arch_feat)
            for s in sub_added:
                if s.lower() not in {a.lower() for a in added}:
                    added.append(s)

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

    # Valida se a magia pertence à lista da classe do personagem
    char_class = sheet.get("classe", "").lower()
    en_class   = _CLASS_SLUG_MAP.get(char_class, "")
    if en_class and spell:
        spell_classes = spell.get("dnd_class", "").lower()
        if spell_classes and en_class not in spell_classes:
            return (
                f"❌ **{spell_name}** não está na lista de magias de {char_class.capitalize()}.\n"
                f"   Disponível para: {spell.get('dnd_class', 'desconhecido')}\n"
                f"   Use learn_spell() com uma magia adequada para {char_class}."
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
        # Alcance vindo direto do Open5e — fonte de verdade para target_mode.
        # Ex.: "Self" (Mage Armor), "Self (15-foot cone)" (Burning Hands),
        # "60 feet" (Magic Missile), "Touch" (Cure Wounds).
        "alcance":    (spell.get("range", "") or "").strip(),
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

    # Instrução interna à LLM — filtrada antes de exibir na UI (server.py).
    lines += ["", "[[llm]]💡 Use os stats em create_character_sheet ANTES de roll_initiative.",
              "   Adapte os nomes ao tema da campanha.[[/llm]]"]
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


def set_feature_choice(char_name: str, feature_name: str, choice: str) -> str:
    """
    Define a subescolha de uma feature de classe que tem variantes — por
    exemplo, qual estilo de combate (Arquearia/Defesa/Duelo/...), qual tipo
    de Inimigo Favorecido, qual terreno de Explorador Natural, qual efeito
    de Metamagia, qual Invocação Sobrenatural.

    Use sempre que o jogador escolher (ou trocar) uma variante. O efeito
    mecânico (bônus de ataque/CA/dano) passa a valer imediatamente nas
    rolagens seguintes.

    Para features com múltiplas escolhas (Metamagia: 2; Invocações: N),
    chame uma vez por escolha — a função acumula numa lista e RECUSA se
    passar do limite, instruindo a remover a antiga primeiro.

    Args:
        char_name:    Nome do personagem.
        feature_name: Nome exato da feature (ex.: "Estilo de Combate",
                      "Inimigo Favorecido", "Metamagia").
        choice:       Nome da variante (ex.: "Arquearia", "Dragões",
                      "Sutil"). Para REMOVER uma escolha, passe "remove:X".
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    meta = _get_variants(feature_name)
    if not meta:
        avail = ", ".join(sorted(FEATURE_VARIANTS.keys()))
        return (
            f"❌ Feature '{feature_name}' não tem variantes registradas.\n"
            f"   Features com subescolha: {avail}."
        )

    # Personagem precisa de fato ter a feature na ficha (concedida pela classe).
    has_feat = any(
        h.get("nome", "").lower() == feature_name.lower()
        for h in (char.get("habilidades") or [])
    )
    if not has_feat:
        return (
            f"❌ {char['name']} ainda não tem a habilidade '{feature_name}'. "
            f"Suba de nível ou conceda a feature antes de escolher variante."
        )

    options = meta.get("options", {}) or {}
    pick    = int(meta.get("pick", 1) or 1)

    sheet  = char.setdefault("sheet", {})
    fc     = sheet.setdefault("feature_choices", {})
    cur    = fc.get(feature_name)

    # Remoção explícita: "remove:Sutil"
    if choice.lower().startswith("remove:"):
        target = choice.split(":", 1)[1].strip()
        if pick == 1:
            if cur == target:
                fc.pop(feature_name, None)
                memory.save_campaign()
                return f"🗑️ Removida a escolha '{target}' de {feature_name}."
            return f"ℹ️ {target!r} não estava marcado em {feature_name}."
        cur_list = list(cur or [])
        if target in cur_list:
            cur_list.remove(target)
            fc[feature_name] = cur_list
            memory.save_campaign()
            return f"🗑️ Removido {target!r} de {feature_name}."
        return f"ℹ️ {target!r} não estava marcado em {feature_name}."

    # Validação
    if choice not in options:
        opts_str = ", ".join(sorted(options.keys()))
        return (
            f"❌ '{choice}' não é uma opção de {feature_name}.\n"
            f"   Opções disponíveis: {opts_str}."
        )

    if pick == 1:
        fc[feature_name] = choice
        # Se for um arquétipo, concede as sub-features do nível atual.
        archetype_granted: list[str] = []
        if feature_name in ARCHETYPE_FEATURES:
            archetype_granted = _apply_archetype_features(char, feature_name)
        # Recalcula CA: Estilo de Combate (Defesa) ou sub-feature de
        # arquétipo que mexe na CA (Resistência Dracônica).
        if feature_name == "Estilo de Combate" or archetype_granted:
            _recalculate_ca(char)
        memory.save_campaign()
        desc = options[choice].get("descricao", "")
        granted_str = ""
        if archetype_granted:
            granted_str = (
                f"\n   🎁 Sub-features concedidas neste nível: "
                f"{', '.join(archetype_granted)}."
            )
        return (
            f"✅ {char['name']} agora tem {feature_name}: **{choice}**.\n"
            f"   {desc}{granted_str}"
        )

    # Multi-pick
    cur_list = list(cur or [])
    if choice in cur_list:
        return f"ℹ️ {choice!r} já está marcado em {feature_name}."
    if len(cur_list) >= pick:
        atual = ", ".join(cur_list)
        return (
            f"❌ {char['name']} já escolheu {len(cur_list)}/{pick} em {feature_name}: {atual}.\n"
            f"   Remova uma antes: set_feature_choice('{char['name']}', "
            f"'{feature_name}', 'remove:<nome>')."
        )
    cur_list.append(choice)
    fc[feature_name] = cur_list
    memory.save_campaign()
    desc = options[choice].get("descricao", "")
    return (
        f"✅ {char['name']} aprendeu {feature_name}: **{choice}** "
        f"({len(cur_list)}/{pick}).\n   {desc}"
    )


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


# ---------------------------------------------------------------------------
# Spawn de monstro com dados reais do Open5e
# ---------------------------------------------------------------------------

def spawn_monster(
    monster_name: str,
    display_name: str = "",
    quantity: int = 1,
) -> str:
    """
    Busca um monstro no Open5e e cria a ficha com os stats reais (HP, CA, atributos,
    ataques). Use SEMPRE que um monstro conhecido aparecer durante o jogo — assim
    o goblin tem HP 7 e CA 15 reais, não os valores genéricos do roll_initiative().

    Para múltiplos exemplares (ex: 3 goblins), passe quantity=3. Os personagens
    serão criados como "Goblin 1", "Goblin 2", "Goblin 3".

    Após spawn_monster(), chame roll_initiative() com os nomes gerados.

    Args:
        monster_name:  Nome do monstro em inglês (ex: 'goblin', 'orc', 'zombie',
                       'bandit', 'wolf', 'skeleton', 'hobgoblin', 'bugbear').
        display_name:  Nome de exibição no jogo (ex: 'Goblin Batedouro'). Se vazio,
                       usa o nome do Open5e.
        quantity:      Quantos exemplares criar (1–10). Se > 1, cria "Nome 1", "Nome 2"…
    """
    import requests as _req
    import re as _re

    quantity = max(1, min(10, int(quantity)))

    # Busca no Open5e pelo nome
    slug = monster_name.strip().lower().replace(" ", "-").replace("'", "")
    monster_data = None

    # Tentativa 1: slug direto
    try:
        r = _req.get(f"https://api.open5e.com/v1/monsters/{slug}/", timeout=5)
        if r.ok:
            monster_data = r.json()
    except Exception:
        pass

    # Tentativa 2: busca por texto
    if not monster_data:
        try:
            r = _req.get(
                "https://api.open5e.com/v1/monsters/",
                params={"search": monster_name.strip(), "limit": 5},
                timeout=5,
            )
            if r.ok:
                results = r.json().get("results", [])
                # Preferência: nome exato, depois nome que começa com a busca
                exact = [m for m in results if m.get("name", "").lower() == monster_name.lower()]
                monster_data = exact[0] if exact else (results[0] if results else None)
        except Exception:
            pass

    if not monster_data:
        return (
            f"⚠️ Monstro '{monster_name}' não encontrado no Open5e. "
            f"Usando ficha padrão via roll_initiative() ou crie manualmente com "
            f"create_character_sheet(). Verifique o nome em inglês "
            f"(ex: 'goblin', 'orc', 'zombie', 'bandit', 'wolf')."
        )

    # Extrai stats
    m          = monster_data
    base_name  = display_name.strip() if display_name.strip() else m.get("name", monster_name)
    hp_max     = int(m.get("hit_points", 10))
    ac         = int(m.get("armor_class", 12))
    str_       = int(m.get("strength",    10))
    dex        = int(m.get("dexterity",   10))
    con        = int(m.get("constitution",10))
    int_       = int(m.get("intelligence",10))
    wis        = int(m.get("wisdom",      10))
    cha        = int(m.get("charisma",    10))
    cr_raw     = m.get("challenge_rating", "?")
    cr_label   = str(cr_raw)
    monster_type = m.get("type", "").lower()
    prof       = 2  # CR 0–4; ajusta para CRs maiores
    cr_float   = _cr_str_to_float(cr_raw)
    if cr_float >= 17: prof = 6
    elif cr_float >= 13: prof = 5
    elif cr_float >= 9: prof = 4
    elif cr_float >= 5: prof = 3

    # Extrai arma principal das ações
    arma_principal = ""
    arma_dado      = ""
    arma_secundaria = ""
    for action in (m.get("actions") or []):
        desc  = (action.get("desc") or "").lower()
        aname = action.get("name") or ""
        is_melee  = "melee weapon attack" in desc or "melee attack" in desc
        is_ranged = "ranged weapon attack" in desc or "ranged attack" in desc
        dado  = action.get("damage_dice", "")
        if not dado:
            _m = _re.search(r'(\d+d\d+)', desc)
            dado = _m.group(1) if _m else ""
        if is_melee and not arma_principal:
            arma_principal  = aname.lower()
            arma_dado       = dado
        elif is_ranged and not arma_secundaria:
            arma_secundaria = aname.lower()
        if arma_principal and arma_secundaria:
            break

    created_names = []
    for i in range(quantity):
        name = base_name if quantity == 1 else f"{base_name} {i + 1}"
        key  = memory.char_key(name)

        sheet = {
            "classe":               "npc",
            "raca":                 base_name.lower(),
            "nivel":                max(1, int(cr_float)) if cr_float >= 1 else 1,
            "xp":                   0,
            "xp_proximo":           100,
            "forca":                str_,
            "destreza":             dex,
            "constituicao":         con,
            "inteligencia":         int_,
            "sabedoria":            wis,
            "carisma":              cha,
            "vida_atual":           hp_max,
            "vida_max":             hp_max,
            "mana_atual":           0,
            "mana_max":             0,
            "ca":                   ac,
            "proficiencia":         prof,
            "hit_die":              8,
            "ouro":                 0,
            "prata":                0,
            "cobre":                0,
            "equipamentos":         {
                "armadura":      None,
                "escudo":        None,
                "arma_principal": arma_principal or None,
                "amuleto":       None,
            },
            "arma_dado":            arma_dado,
            "arma_secundaria":      arma_secundaria or None,
            "condicoes":            [],
            "death_saves_sucessos": 0,
            "death_saves_falhas":   0,
            "cr":                   cr_label,
        }

        # Extrai habilidades especiais (special abilities) do Open5e
        habilidades = []
        for sa in (m.get("special_abilities") or [])[:3]:
            sa_name = sa.get("name", "")
            sa_desc = (sa.get("desc", "") or "")[:200]
            if sa_name:
                habilidades.append({
                    "nome":       sa_name,
                    "descricao":  sa_desc,
                    "custo_mana": 0,
                    "dado":       "",
                })

        memory.campaign["characters"][key] = {
            "name":        name,
            "description": f"{m.get('size','')} {monster_type} — CR {cr_label}.",
            "traits":      "",
            "status":      "inimigo",
            "notes":       "",
            "sheet":       sheet,
            "inventario":  [],
            "habilidades": habilidades,
        }
        created_names.append(name)

    memory.save_campaign()

    names_str  = ", ".join(created_names)
    atk_info   = f" | ⚔️ {arma_principal} ({arma_dado})" if arma_principal else ""
    sec_info   = f" + {arma_secundaria}" if arma_secundaria else ""
    qty_label  = f"{quantity}×" if quantity > 1 else ""

    return (
        f"👹 {qty_label}{base_name} criado(s) com stats reais (Open5e)!\n"
        f"   CR {cr_label} | ❤️ HP {hp_max} | 🛡️ CA {ac}{atk_info}{sec_info}\n"
        f"   FOR {str_}  DES {dex}  CON {con}  INT {int_}  SAB {wis}  CAR {cha}\n"
        f"   Personagens: {names_str}"
        # Instrução interna à LLM — filtrada antes de exibir na UI (server.py).
        f"\n[[llm]]→ Agora chame roll_initiative() incluindo: {names_str}[[/llm]]"
    )


# ---------------------------------------------------------------------------
# Estratégia de NPC — sistema determinístico de combate
# ---------------------------------------------------------------------------

NPC_STRATEGIES = {
    "agressivo":  "Ataca o alvo com mais HP (mais ameaçador).",
    "tático":     "Ataca o alvo com menos HP (terminar logo).",
    "covarde":    "Foge quando HP < 25%; senão ataca o mais fraco.",
    "aleatório":  "Escolhe alvo e ação aleatoriamente.",
    "suporte":    "Cura aliados com HP < 50% se possível; senão ataca.",
}


def set_npc_strategy(npc_name: str, strategy: str) -> str:
    """
    Define a estratégia de combate de um NPC para o sistema de turno automático.
    A estratégia determina como execute_npc_turn() escolhe o alvo.

    Estratégias disponíveis:
    • agressivo  — ataca o alvo com mais HP (mais ameaçador)
    • tático     — ataca o alvo com menos HP (eliminar o mais fraco)
    • covarde    — foge quando HP < 25%; senão ataca o mais fraco
    • aleatório  — escolhe alvo aleatoriamente
    • suporte    — cura aliados com HP < 50%; senão ataca

    Args:
        npc_name: Nome do NPC.
        strategy: Nome da estratégia (agressivo, tático, covarde, aleatório, suporte).
    """
    cs = memory.campaign.get("combat_state", {})
    if not cs.get("is_active"):
        return "⚠️ Nenhum combate ativo."
    strategy = strategy.lower().strip()
    if strategy not in NPC_STRATEGIES:
        opts = ", ".join(NPC_STRATEGIES.keys())
        return f"⚠️ Estratégia '{strategy}' inválida. Opções: {opts}"
    cs.setdefault("npc_strategies", {})[npc_name.lower()] = strategy
    memory.save_campaign()
    return f"🎯 Estratégia de {npc_name} definida: **{strategy}** — {NPC_STRATEGIES[strategy]}"


def execute_npc_turn(npc_name: str = "") -> str:
    """
    Executa o turno do NPC atual (ou do NPC especificado) de forma totalmente
    determinística: escolhe alvo com base na estratégia configurada e chama
    attack_roll() automaticamente. A IA só precisa narrar o resultado.

    Se nenhuma estratégia foi configurada, usa 'agressivo' por padrão.
    Se o NPC for covarde e estiver com HP < 25%, foge do combate.

    Args:
        npc_name: Nome do NPC (opcional — se omitido, usa o NPC do turno atual).
    """
    cs = memory.campaign.get("combat_state", {})
    if not cs.get("is_active"):
        return "⚠️ Nenhum combate ativo."

    # Auto-cura: desencalha o ponteiro se o atual saiu de combate.
    _heal_current_turn()
    cs = memory.campaign.get("combat_state", {})
    if not cs.get("is_active"):
        return "🏳️  Combate encerrado — nenhum combatente restante."

    order = cs.get("initiative_order", [])
    if not order:
        return "⚠️ Ordem de iniciativa vazia."

    # O motor é a autoridade: age SEMPRE pelo combatente do turno atual,
    # ignorando um npc_name divergente que o LLM possa ter passado.
    idx      = cs.get("current_turn_index", 0)
    npc_name = order[idx] if 0 <= idx < len(order) else ""
    if not npc_name:
        return "⚠️ Não foi possível determinar o NPC atual."

    npc, err = _get_char(npc_name)
    if not npc:
        return f"⚠️ NPC '{npc_name}' não encontrado: {err}"

    # Definição canônica de grupo (memory.is_party_member): party_member,
    # protagonista ou campaign["party"].
    chars = memory.campaign.get("characters", {})

    if memory.is_party_member(npc):
        return (
            f"⚠️ {npc_name} é um personagem do grupo — use attack_roll() "
            f"conforme instrução do jogador."
        )

    strategy = cs.get("npc_strategies", {}).get(npc_name.lower(), "agressivo")
    npc_sheet = npc.get("sheet", {}) or {}

    # Lógica de fuga (covarde)
    if strategy == "covarde":
        hp_pct = (npc_sheet.get("vida_atual", 1) /
                  max(1, npc_sheet.get("vida_max", 1)))
        if hp_pct <= 0.25:
            npc["status"] = "fugiu"
            _log_combat_event("flee", npc_name, "",
                              msg=f"{npc_name} fugiu do combate")
            memory.save_campaign()
            advance = _auto_advance_turn(npc_name)
            return (
                f"💨 {npc_name} está com {int(hp_pct * 100)}% de HP e FOGE do combate!"
                f"{advance}"
            )

    # Monta lista de alvos válidos: membros do grupo vivos e em pé.
    OUT = ("morto", "estabilizado", "inconsciente", "fugiu", "exilado")
    targets = []
    for p_char in chars.values():
        if not memory.is_party_member(p_char):
            continue
        if p_char.get("status", "vivo").lower() in OUT:
            continue
        p_sheet = p_char.get("sheet", {}) or {}
        if p_sheet.get("vida_atual", 0) <= 0:
            continue
        targets.append({
            "name":   p_char.get("name", ""),
            "hp":     p_sheet.get("vida_atual", 0),
            "hp_max": p_sheet.get("vida_max", 1),
        })

    if not targets:
        return f"⚔️ {npc_name} não encontra alvos válidos. Verifique se o combate deve encerrar com end_combat()."

    # Seleção de alvo por estratégia
    if strategy == "agressivo":
        target = max(targets, key=lambda t: t["hp"])
    elif strategy in ("tático", "covarde"):
        target = min(targets, key=lambda t: t["hp"])
    elif strategy == "aleatório":
        target = random.choice(targets)
    else:  # suporte ou padrão
        target = min(targets, key=lambda t: t["hp"])

    # Determina arma equipada
    npc_equip = npc_sheet.get("equipamentos", {}) or {}
    weapon    = npc_equip.get("arma_principal") or "shortsword"

    # Determina atributo de ataque (força por padrão para NPCs)
    atk_attr = "forca"
    if any(k in weapon.lower() for k in ("arco", "besta", "dardo", "funda")):
        atk_attr = "destreza"

    # Executa o ataque (inclui _auto_advance_turn() internamente).
    # _skip_turn_check=True: o motor já garante que está agindo pelo NPC
    # correto do turno — a checagem de ordem não se aplica aqui.
    return attack_roll(
        attacker_name    = npc_name,
        target_name      = target["name"],
        weapon           = weapon,
        damage_dice_sides= 6,   # fallback; attack_roll busca via Open5e
        damage_dice_count= 1,
        attack_attribute = atk_attr,
        is_proficient    = True,
        end_turn         = True,
        _skip_turn_check = True,
    )


# ===========================================================================
# API de COMBATE NA TELA (sem LLM)
# ---------------------------------------------------------------------------
# Funções puras sobre memory.campaign. O server.py só faz wrapper JSON.
# TODA a mecânica continua no motor já fuzzado (attack_roll/use_ability/
# execute_npc_turn/next_turn/roll_death_save) — estas funções NÃO recalculam
# nada: só orquestram intents e fotografam o estado para a tela.
# ===========================================================================

# ── Economia de ações 5e: o que é Ação Bônus por nome ──────────────────────
# Heurística por substring (case/acento-insensível). Default = Ação.
# Regras combinam SRD 2014 + revisão 2024 (poção como Bônus).
_ABILITY_BONUS_PATTERNS = (
    "healing word", "palavra curativa", "palavra de cura",
    "misty step", "passo brumoso",
    "second wind", "segunda folego", "segundo folego",
    "action surge", "surto de acao",
    "cunning action", "acao astuta",
    "bardic inspiration", "inspiracao de bardo",
    "spiritual weapon", "arma espiritual",
    "shillelagh", "shillelah",
    "healing spirit", "espirito curativo",
    "hex",  # cast inicial é Bônus
    "mass healing word",
)


def _ability_action_type(name: str) -> str:
    """'bonus' se a habilidade é Ação Bônus pela regra 5e; senão 'acao'."""
    n = _norm_txt(name)
    if not n:
        return "acao"
    for p in _ABILITY_BONUS_PATTERNS:
        if _norm_txt(p) in n:
            return "bonus"
    return "acao"


# ── Habilidades que afetam SOMENTE o conjurador (sem picker de alvo) ──────
# Match por substring no nome normalizado.
_ABILITY_SELF_ONLY_PATTERNS = (
    "second wind", "segunda folego", "segundo folego",
    "rage", "furia",
    "wild shape", "forma selvagem",
    "action surge", "surto de acao",
    "patient defense", "defesa paciente",
    "step of the wind", "passo do vento",
    "shield of faith",  # cast in self (concentração; alvo único = self)
)


def _is_self_only_ability(name: str) -> bool:
    n = _norm_txt(name)
    return bool(n) and any(p in n for p in _ABILITY_SELF_ONLY_PATTERNS)


def _ability_target_mode(name: str, hab: dict | None = None) -> str:
    """
    Modo de alvo para a UI tática decidir se mostra picker.

    Fonte primária de verdade: o campo `alcance` do habilidade (vem do
    Open5e — "Self", "Self (15-foot cone)", "60 feet", "Touch"…). Não
    mantemos lista hardcoded de magias.

    Fallbacks (para dados que NÃO vêm do Open5e):
      • Class features SRD (Segunda Fôlego, Fúria…): lista pequena fixa.
      • Pool spells (Sleep, Color Spray): tabela CONTROL_SPELL_EFFECTS
        — são 2 itens no SRD, e a mecânica "pool de HP" é única do 5e.
      • Heurística por nome para legados sem `alcance`.

    Retornos:
      "self"   → afeta só o conjurador (sem picker).
      "pool"   → área com pool de HP, múltiplos alvos (Sleep). Sem picker.
      "area"   → AoE genuíno centrado no conjurador (Burning Hands, etc.).
                 Hoje o engine ainda trata como single — UI cai em "single"
                 até existir engine de dano em área. TODO marcado.
      "single" → alvo único.
    """
    # 1. Class features SRD — sempre self-only (lista fixa pequena).
    if _is_self_only_ability(name):
        return "self"

    # 2. Pool spells — só Sleep e Color Spray no SRD, mecânica peculiar.
    if hab is not None:
        eff = _get_control_effect(hab)
        if eff is not None and eff.get("pool"):
            return "pool"

    # 3. Fonte primária: campo `alcance` (do Open5e via learn_spell/wizard).
    alcance = ((hab or {}).get("alcance") or "").strip().lower()
    if alcance == "self":
        return "self"
    if alcance.startswith("self (") or alcance.startswith("self("):
        # AoE centrado no conjurador (cone/sphere/cube/line). Engine ainda
        # não distribui dano em área, então caímos em "single" por ora.
        # TODO: quando houver _area_damage no use_ability, retornar "area".
        return "single"
    if alcance in ("", "n/a", "none"):
        # Sem dado de alcance — pode ser feature de classe ou legado.
        # Heurística por nome só para esses casos.
        n = _norm_txt(name)
        if any(k in n for k in ("sleep", "sono", "color spray")):
            return "pool"

    # Default: alvo único (Touch, X feet, …).
    return "single"


def _item_action_type(name: str) -> str:
    """
    'bonus' para itens que custam Ação Bônus pela regra (2024).
    Atualmente: Poção de Cura e variantes. Outros consumíveis → 'acao'.
    """
    n = _norm_txt(name)
    if not n:
        return "acao"
    if ("pocao de cura" in n or "potion of healing" in n or
            "healing potion" in n or "pocao de vida" in n):
        return "bonus"
    return "acao"


def _reset_turn_economy(cs: dict) -> None:
    """Zera Ação/Bônus do novo combatente que entra em seu turno."""
    if isinstance(cs, dict):
        cs["turn_economy"] = {"acao_usada": False, "bonus_usada": False}


# Marcadores de habilidade PASSIVA (não aparecem como botão de ação na tela).
_ABILITY_PASSIVE_NAME_PREFIX = (
    "proficiencia", "proficiência", "idioma", "resistencia a", "resistência a",
    "imunidade", "visao no escuro", "visão no escuro", "sentido", "tamanho",
    "deslocamento", "estilo de combate",
)
_ABILITY_PASSIVE_DESC_MARKERS = (
    "proficiencia de pericia", "proficiência de perícia",
    "concedida pelo antecedente", "proficiência concedida",
    "habilidade de classe —", "habilidade de classe -",
    "passiv",  # "passiva", "passivo"
)


def _norm_txt(t: str) -> str:
    import unicodedata
    t = (t or "").lower().strip()
    return "".join(c for c in unicodedata.normalize("NFD", t)
                   if unicodedata.category(c) != "Mn")


def _ability_is_passive(hab: dict) -> bool:
    """
    True quando a 'habilidade' é passiva/proficiência e NÃO deve virar botão
    de ação na tela tática (ex: 'Proficiência: Atletismo', 'Estilo de Combate').
    Conservador: na dúvida, considera USÁVEL (mantém magias/ataques/curas).
    """
    nome = _norm_txt(hab.get("nome", ""))
    if not nome:
        return True
    for p in _ABILITY_PASSIVE_NAME_PREFIX:
        if nome.startswith(_norm_txt(p)):
            return True
    # Tem efeito ativo claro → usável (dado de dano/cura ou custo de mana).
    if hab.get("dado") or int(hab.get("custo_mana", 0) or 0) > 0:
        return False
    desc = _norm_txt(hab.get("descricao", ""))
    for m in _ABILITY_PASSIVE_DESC_MARKERS:
        if _norm_txt(m) in desc:
            return True
    return False


# Itens consumíveis usáveis EM COMBATE (palavras no nome).
_CONSUMABLE_KEYWORDS = (
    "poção", "pocao", "potion", "elixir", "frasco", "ampola",
    "pergaminho", "scroll", "óleo", "oleo",
    "ácido", "acido", "fogo alquímico", "fogo alquimico", "água benta",
    "agua benta", "bomba", "granada", "explosivo", "tônico", "tonico",
    "veneno", "antídoto", "antidoto", "remédio", "remedio",
)
# Itens que claramente NÃO são consumíveis (filtro extra para evitar falso positivo).
_NON_CONSUMABLE_KEYWORDS = (
    "espada", "arco", "besta", "adaga", "lança", "lanca", "machado",
    "armadura", "escudo", "capa", "amuleto", "anel", "elmo", "bota",
    "luva", "gibão", "gibao", "cota", "calça", "calca", "túnica", "tunica",
    "manopla", "virote", "flecha", "munição", "municao", "tocha", "corda",
    "pacote", "saco", "mochila",
)

# Padrões de poções de cura conhecidos → (n_dice, sides, bonus). 5e SRD.
_HEAL_POTIONS = [
    ("suprema",    (10, 4, 20)),   # 10d4+20
    ("superior",   (8,  4,  8)),   # 8d4+8
    ("greater",    (4,  4,  4)),   # 4d4+4
    ("maior",      (4,  4,  4)),
]
_HEAL_BASE = (2, 4, 2)             # poção de cura básica → 2d4+2


def _item_combat_kind(item_name: str):
    """
    Classifica um item para uso em combate.
    Retorna: ("heal", n_dice, sides, bonus)  |  ("generic", 0, 0, 0)  |  None.
    None = item não é consumível de combate (não vira botão).
    """
    if not item_name:
        return None
    n = _norm_txt(item_name)
    if not n:
        return None
    if any(kw in n for kw in (_norm_txt(k) for k in _NON_CONSUMABLE_KEYWORDS)):
        return None
    if not any(kw in n for kw in (_norm_txt(k) for k in _CONSUMABLE_KEYWORDS)):
        return None
    # Poções de cura: detecta nível pelo qualificador.
    if "pocao de cura" in n or "potion of healing" in n or "healing potion" in n \
            or "pocao de vida" in n:
        for tag, dice in _HEAL_POTIONS:
            if _norm_txt(tag) in n:
                return ("heal",) + dice
        return ("heal",) + _HEAL_BASE
    return ("generic", 0, 0, 0)


_WEAPON_KEYWORDS = (
    "espada", "arco", "besta", "adaga", "lança", "lanca", "machado", "maça",
    "maca", "martelo", "cajado", "bordão", "bordao", "clava", "porrete",
    "rapieira", "florete", "sabre", "cimitarra", "foice", "chicote", "funda",
    "tridente", "alabarda", "azagaia", "dardo", "zarabatana", "varinha",
)


def _combatant_weapons(ch: dict) -> list[dict]:
    """Armas que o combatente pode usar: equipadas + inventário + desarmado."""
    s = ch.get("sheet") or {}
    eq = s.get("equipamentos", {}) or {}
    out, seen = [], set()

    def _add(nm, origem):
        n = (nm or "").strip()
        k = n.lower()
        if not n or k in seen:
            return
        seen.add(k)
        out.append({"nome": n, "origem": origem})

    _add(eq.get("arma_principal"), "equipada")
    _add(eq.get("arma_secundaria"), "equipada")
    for it in (ch.get("inventario") or []):
        if not isinstance(it, dict):
            continue
        inm = (it.get("nome") or "")
        if any(kw in inm.lower() for kw in _WEAPON_KEYWORDS):
            _add(inm, "inventário")
    _add("Ataque desarmado", "desarmado")
    return out


def _combatant_snapshot(name: str) -> dict | None:
    ch = memory.campaign["characters"].get(memory.char_key(name))
    if not ch:
        return None
    s = ch.get("sheet") or {}
    conds = []
    _seen_cond = set()
    for c in (s.get("condicoes") or []):
        nm  = (c.get("nome", "") if isinstance(c, dict) else str(c)) or ""
        key = nm.lower().strip()
        if key and key not in _seen_cond:        # dedup por nome
            _seen_cond.add(key)
            conds.append(nm)
    habs = []        # só ATIVAS (viram botão)
    passivas = []    # exibição informativa
    for h in (ch.get("habilidades") or []):
        if not isinstance(h, dict):
            continue
        entry = {
            "nome":       h.get("nome", ""),
            "custo_mana": int(h.get("custo_mana", 0) or 0),
            "dado":       h.get("dado", ""),
            "descricao":  h.get("descricao", ""),
            "tipo_acao":  _ability_action_type(h.get("nome", "")),
            # Modo de alvo: "self" | "pool" | "single". A UI usa para decidir
            # se mostra o picker ou despacha direto (self/pool não pedem alvo).
            "target_mode": _ability_target_mode(h.get("nome", ""), h),
        }
        if _ability_is_passive(h):
            passivas.append(entry["nome"])
        else:
            habs.append(entry)
    itens = []
    itens_combate = []   # subconjunto consumível (usável na tela tática)
    for it in (ch.get("inventario") or []):
        if not isinstance(it, dict):
            continue
        entry = {
            "nome": it.get("nome", ""),
            "qtd":  int(it.get("qtd", 1) or 1),
            "descricao": it.get("descricao", ""),
        }
        itens.append(entry)
        kind = _item_combat_kind(entry["nome"])
        if kind and entry["qtd"] > 0:
            itens_combate.append({
                **entry,
                "kind": kind[0],
                "tipo_acao": _item_action_type(entry["nome"]),
                "dice": f"{kind[1]}d{kind[2]}+{kind[3]}" if kind[0] == "heal" else "",
            })
    # Anota a subescolha de cada habilidade de classe (Estilo de Combate,
    # Inimigo Favorecido, Metamagia…) na entrada correspondente — assim a UI
    # mostra "Estilo de Combate: Arquearia" no card sem buscar de novo.
    _choices = (s.get("feature_choices") or {})
    for h in habs:
        v = _choices.get(h["nome"])
        if v is not None:
            h["choice"] = v
    return {
        "name":       ch.get("name", name),
        "status":     (ch.get("status", "vivo") or "vivo"),
        "is_party":   bool(memory.is_party_member(ch)),
        "hp":         int(s.get("vida_atual", 0) or 0),
        "hp_max":     int(s.get("vida_max", 0) or 0),
        "mp":         int(s.get("mana_atual", 0) or 0),
        "mp_max":     int(s.get("mana_max", 0) or 0),
        "ca":         int(s.get("ca", 10) or 10),
        "nivel":      int(s.get("nivel", 1) or 1),
        "classe":     s.get("classe", ""),
        "arma":       (s.get("equipamentos", {}) or {}).get("arma_principal") or "",
        "armas":      _combatant_weapons(ch),
        "condicoes":  conds,
        "habilidades": habs,
        "passivas":   passivas,
        "inventario": itens,
        "itens_combate": itens_combate,
    }


def combat_snapshot() -> dict:
    """Estado completo do combate para a tela tática (JSON-serializável)."""
    camp = memory.campaign
    cs   = camp.get("combat_state", {}) or {}
    order = list(cs.get("initiative_order", []) or [])
    idx   = cs.get("current_turn_index", 0)
    if not isinstance(idx, int) or not (0 <= idx < len(order)):
        idx = 0
    combatants = []
    for nm in order:
        snap = _combatant_snapshot(nm)
        if snap:
            snap["is_current"] = (order.index(nm) == idx) if nm in order else False
            combatants.append(snap)
    current = order[idx] if order else ""
    return {
        "combat_mode": camp.get("combat_mode", "narrado"),
        "is_active":   bool(cs.get("is_active")),
        "round":       int(cs.get("round", 1) or 1),
        "turn_index":  idx,
        "turn_token":  int(cs.get("turn_token", 0) or 0),
        "current":     current,
        "current_is_party": bool(
            memory.is_party_member(
                memory.campaign["characters"].get(memory.char_key(current), {})
            )
        ) if current else False,
        "order":       order,
        "combatants":  combatants,
        "log":         list(cs.get("log", []) or [])[-60:],
        "result":      cs.get("result"),   # painel de fim (None até acabar)
        "turn_economy": dict(cs.get("turn_economy") or
                             {"acao_usada": False, "bonus_usada": False}),
    }


def combat_action(action: str, actor: str = "", target: str = "",
                  weapon: str = "", ability: str = "", item: str = "") -> dict:
    """
    Aplica UMA intenção de combate vinda da tela, delegando ao motor
    determinístico já fuzzado. Retorna {ok, message, snapshot}.

    actions: attack | ability | enemy | pass | defend | flee | death_save | end
    """
    cs = memory.campaign.get("combat_state", {}) or {}
    if action not in ("end",) and not cs.get("is_active"):
        return {"ok": False, "message": "Nenhum combate ativo.",
                "snapshot": combat_snapshot()}

    msg = ""
    a = (action or "").lower().strip()

    # Helper local: tenta marcar slot ("acao"|"bonus") na economia do turno.
    # Retorna mensagem de erro (string) ou None se ok.
    def _use_slot(eco: dict, slot: str) -> str | None:
        key = slot + "_usada"
        if eco.get(key):
            rotulo = "Ação" if slot == "acao" else "Ação Bônus"
            return (f"❌ {actor} já usou sua {rotulo} neste turno. "
                    f"Use 'Encerrar Turno' ou a outra parte da economia.")
        eco[key] = True
        return None

    # Caminhos que NÃO usam a economia do jogador (o motor cuida do avanço):
    if a == "enemy":
        msg = execute_npc_turn()

    elif a == "death_save":
        if not actor:
            return {"ok": False, "message": "Teste de morte exige actor.",
                    "snapshot": combat_snapshot()}
        msg = roll_death_save(actor)

    elif a == "end":
        msg = end_combat()

    else:
        # Daqui pra baixo: ações DE JOGADOR. Aplicam a economia 5e (Ação,
        # Bônus). Engine NÃO avança turno por conta própria (end_turn=False)
        # — esta função decide o avanço com base na economia.
        if not actor:
            return {"ok": False, "message": f"Ação '{a}' exige actor.",
                    "snapshot": combat_snapshot()}
        v = _combat_turn_violation(actor)
        if v:
            return {"ok": False, "message": v, "snapshot": combat_snapshot()}
        eco = cs.setdefault("turn_economy",
                            {"acao_usada": False, "bonus_usada": False})
        force_end = False  # se True ao final, encerra o turno (flee/pass)

        if a == "attack":
            if not target:
                return {"ok": False, "message": "Ataque exige target.",
                        "snapshot": combat_snapshot()}
            err = _use_slot(eco, "acao")
            if err:
                return {"ok": False, "message": err, "snapshot": combat_snapshot()}
            if not weapon:
                ch = memory.campaign["characters"].get(memory.char_key(actor), {})
                weapon = ((ch.get("sheet", {}) or {}).get("equipamentos", {}) or {}
                          ).get("arma_principal") or "ataque desarmado"
            msg = attack_roll(actor, target, weapon, 6, end_turn=False)

        elif a == "ability":
            if not ability:
                return {"ok": False, "message": "Habilidade exige ability.",
                        "snapshot": combat_snapshot()}
            # Pré-checa mana ANTES de consumir slot — sem isso, uma magia
            # recusada por falta de mana ainda gastaria a Ação/Bônus do turno.
            ch_pre = memory.campaign["characters"].get(memory.char_key(actor)) or {}
            habs_pre = ch_pre.get("habilidades") or []
            hab_pre = next((h for h in habs_pre
                            if isinstance(h, dict)
                            and (h.get("nome") or "").lower() == ability.lower()), None)
            if hab_pre is None:
                # Tenta tradução PT→EN
                en_alt = _SPELL_PT_TO_EN.get(ability.lower())
                if en_alt:
                    hab_pre = next((h for h in habs_pre
                                    if isinstance(h, dict)
                                    and (h.get("nome") or "").lower() == en_alt.lower()), None)
            if hab_pre is not None:
                custo_pre = int(hab_pre.get("custo_mana", 0) or 0)
                sheet_pre = ch_pre.get("sheet") or {}
                mp_atual  = int(sheet_pre.get("mana_atual", 0) or 0)
                if custo_pre > mp_atual:
                    mp_max = int(sheet_pre.get("mana_max", 0) or 0)
                    return {
                        "ok": False,
                        "message": (f"❌ {actor} não tem mana suficiente para "
                                    f"'{hab_pre.get('nome', ability)}' "
                                    f"(precisa {custo_pre}, tem {mp_atual}/{mp_max}). "
                                    f"A Ação/Bônus deste turno NÃO foi gasta."),
                        "snapshot": combat_snapshot(),
                    }
            slot = "bonus" if _ability_action_type(ability) == "bonus" else "acao"
            err = _use_slot(eco, slot)
            if err:
                return {"ok": False, "message": err, "snapshot": combat_snapshot()}
            msg = use_ability(actor, ability, target, end_turn=False)

        elif a == "item":
            item_name = (item or weapon or "").strip()
            if not item_name:
                return {"ok": False, "message": "Especifique o item.",
                        "snapshot": combat_snapshot()}
            ch = memory.campaign["characters"].get(memory.char_key(actor))
            if not ch:
                return {"ok": False, "message": f"'{actor}' não encontrado.",
                        "snapshot": combat_snapshot()}
            inv = ch.get("inventario") or []
            slot_inv = next((it for it in inv
                             if isinstance(it, dict)
                             and (it.get("nome") or "").strip().lower() == item_name.lower()
                             and int(it.get("qtd", 1) or 1) > 0), None)
            if not slot_inv:
                return {"ok": False,
                        "message": f"'{actor}' não tem '{item_name}' utilizável.",
                        "snapshot": combat_snapshot()}
            kind = _item_combat_kind(slot_inv.get("nome", ""))
            if not kind:
                return {"ok": False,
                        "message": f"'{item_name}' não é consumível de combate.",
                        "snapshot": combat_snapshot()}
            # Custo de ação do ITEM (poção de cura = Bônus pela 5e 2024).
            slot = ("bonus" if _item_action_type(slot_inv["nome"]) == "bonus"
                    else "acao")
            err = _use_slot(eco, slot)
            if err:
                return {"ok": False, "message": err, "snapshot": combat_snapshot()}
            # Aplica efeito
            if kind[0] == "heal":
                _, n_d, sides, bonus = kind
                rolls = [random.randint(1, sides) for _ in range(n_d)]
                heal  = sum(rolls) + bonus
                recv_name = (target or actor).strip() or actor
                recv = memory.campaign["characters"].get(memory.char_key(recv_name))
                if not recv or not recv.get("sheet"):
                    # devolve o slot consumido (alvo inválido) — segurança extra
                    eco[slot + "_usada"] = False
                    return {"ok": False, "message": f"Alvo '{recv_name}' inválido.",
                            "snapshot": combat_snapshot()}
                st = recv["sheet"]
                hp_antes = int(st.get("vida_atual", 0) or 0)
                hp_max   = int(st.get("vida_max", 0) or 0)
                st["vida_atual"] = max(0, min(hp_max, hp_antes + heal))
                hp_depois = st["vida_atual"]
                if hp_antes == 0 and hp_depois > 0 and (recv.get("status", "") or "").lower() in ("inconsciente", "estabilizado"):
                    recv["status"] = "vivo"
                    st["death_saves_sucessos"] = 0
                    st["death_saves_falhas"]   = 0
                detail = " + ".join(str(r) for r in rolls)
                tag_eco = "Bônus" if slot == "bonus" else "Ação"
                _log_combat_event(
                    "item_heal", actor, recv["name"],
                    msg=(f"{actor} usou {slot_inv['nome']} em {recv['name']} "
                         f"[{tag_eco}]: 🎲 {n_d}d{sides}: [{detail}] +{bonus} = "
                         f"{heal} cura • HP {hp_antes}→{hp_depois}/{hp_max}"),
                    item=slot_inv["nome"], rolls=list(rolls), heal=heal,
                    hp=hp_depois, hp_max=hp_max, slot=slot,
                )
                msg = (f"🧪 {actor} usou {slot_inv['nome']} em {recv['name']} "
                       f"[{tag_eco}]: +{heal} HP ({hp_antes}→{hp_depois}/{hp_max}).")
            else:
                _log_combat_event("item_use", actor, target,
                                  msg=f"{actor} usou {slot_inv['nome']}",
                                  item=slot_inv["nome"], slot=slot)
                msg = f"🧪 {actor} usou {slot_inv['nome']}."
            slot_inv["qtd"] = int(slot_inv.get("qtd", 1) or 1) - 1
            if slot_inv["qtd"] <= 0:
                try: inv.remove(slot_inv)
                except ValueError: pass
            memory.save_campaign()

        elif a == "defend":
            err = _use_slot(eco, "acao")  # Dodge = Ação
            if err:
                return {"ok": False, "message": err, "snapshot": combat_snapshot()}
            _log_combat_event("defend", actor, "",
                              msg=f"{actor} defendeu-se (Esquivar — Ação)")
            msg = f"🛡️ {actor} esquiva-se (Dodge)."

        elif a == "flee":
            err = _use_slot(eco, "acao")
            if err:
                return {"ok": False, "message": err, "snapshot": combat_snapshot()}
            ch = memory.campaign["characters"].get(memory.char_key(actor))
            if not ch:
                return {"ok": False, "message": f"'{actor}' não encontrado.",
                        "snapshot": combat_snapshot()}
            ch["status"] = "fugiu"
            _log_combat_event("flee", actor, "", msg=f"{actor} fugiu do combate")
            memory.save_campaign()
            msg = f"💨 {actor} fugiu do combate!"
            force_end = True

        elif a in ("pass", "end_turn"):
            # Encerrar o turno explicitamente (sem ação especial).
            _log_combat_event("pass", actor, "",
                              msg=f"{actor} encerrou o turno")
            msg = ""
            force_end = True

        else:
            return {"ok": False, "message": f"Ação '{action}' desconhecida.",
                    "snapshot": combat_snapshot()}

        # ── Decisão de AVANÇO de turno (regra 5e) ────────────────────────
        cs_now  = memory.campaign.get("combat_state", {}) or {}
        eco_now = cs_now.get("turn_economy", {}) or {}
        if force_end or (eco_now.get("acao_usada") and eco_now.get("bonus_usada")):
            msg += _auto_advance_turn(actor)

    # FIM AUTOMÁTICO: na tela tática, se um lado foi todo derrotado/fugiu,
    # encerra o combate (o motor só encerrava se TODOS estavam fora).
    cs2 = memory.campaign.get("combat_state", {}) or {}
    if a != "end" and cs2.get("is_active"):
        order = cs2.get("initiative_order", []) or []
        party_alive = enemy_alive = party_seen = enemy_seen = False
        for nm in order:
            ch = memory.campaign["characters"].get(memory.char_key(nm))
            if not ch:
                continue
            is_p = bool(memory.is_party_member(ch))
            # DEFEATED (não OUT): uma criatura DORMINDO está incapacitada mas
            # ainda viva — não conta como derrotada, então não encerra a luta.
            out  = (ch.get("status", "") or "").lower() in DEFEATED_STATUSES
            if is_p:
                party_seen = True
                party_alive = party_alive or (not out)
            else:
                enemy_seen = True
                enemy_alive = enemy_alive or (not out)
        if (enemy_seen and not enemy_alive) or (party_seen and not party_alive):
            party_win = enemy_seen and not enemy_alive
            quem = "inimigos" if party_win else "o grupo"
            # Captura o RESULTADO antes de end_combat() limpar a ordem,
            # para a tela mostrar um painel de fim (sem fechar bruscamente).
            sobrev, caidos = [], []
            for nm in order:
                snp = _combatant_snapshot(nm)
                if not snp:
                    continue
                linha = {"name": snp["name"], "is_party": snp["is_party"],
                         "hp": snp["hp"], "hp_max": snp["hp_max"],
                         "status": snp["status"]}
                if snp["status"].lower() in DEFEATED_STATUSES:
                    caidos.append(linha)
                else:
                    sobrev.append(linha)
            cs2["result"] = {
                "outcome":      "vitoria" if party_win else "derrota",
                "title":        "Vitória!" if party_win else "Derrota…",
                "sobreviventes": sobrev,
                "caidos":        caidos,
            }
            _log_combat_event("side_wiped", msg=f"Combate decidido — {quem} fora de ação")
            msg += "\n" + end_combat()

    # Se chegou até aqui, a ação foi aceita pelo motor. "❌" pode aparecer
    # na narrativa de um ataque que ERROU — ainda é sucesso da ação.
    # Recusas reais retornam ok=False mais cedo (early returns).
    return {"ok": True, "message": msg, "snapshot": combat_snapshot()}


def combat_recap_payload() -> str:
    """
    Texto compacto do combate (do log estruturado) para a LLM narrar a luta
    inteira de uma vez e gerar o saque. Usado quando o combate acaba na tela.
    """
    cs  = memory.campaign.get("combat_state", {}) or {}
    log = cs.get("log", []) or []
    linhas = []
    for ev in log:
        r = ev.get("round", "?")
        linhas.append(f"[R{r}] {ev.get('msg', ev.get('type',''))}")

    # Estado final vem do RESULTADO capturado (a ordem já foi limpa por
    # end_combat). Inclui quem caiu (alvos de saque) e quem sobreviveu.
    res = cs.get("result") or {}
    desfecho = res.get("outcome", "fim")
    finais = []
    for c in (res.get("sobreviventes", []) + res.get("caidos", [])):
        lado = "grupo" if c.get("is_party") else "inimigo"
        finais.append(f"{c.get('name')} [{lado}]: {c.get('status')} "
                      f"({c.get('hp')}/{c.get('hp_max')} HP)")

    if str(desfecho).lower() == "derrota":
        instrucao = (
            "Desfecho: DERROTA. Narre a queda do grupo de forma cinematográfica "
            "e contínua, com base no log abaixo. NÃO gere saque e NÃO conceda "
            "XP — perder a luta não dá recompensa nenhuma. Conduza as "
            "consequências (captura, resgate, quase-morte, fuga…) e siga a história."
        )
    else:
        instrucao = (
            "Desfecho: VITÓRIA. Narre a luta INTEIRA de forma cinematográfica e "
            "contínua (não turno a turno), com base no log abaixo. Gere o SAQUE "
            "dos inimigos derrotados (use add_item/modify_currency se houver) e "
            "conceda XP a cada membro do grupo com grant_xp(). Depois siga a história."
        )
    payload = (
        "[COMBATE RESOLVIDO NA TELA TÁTICA]\n"
        + instrucao + "\n\n"
        + "— Eventos —\n" + "\n".join(linhas)
        + "\n\n— Estado final —\n" + "\n".join(finais)
    )
    # Acknowledged: limpa o resultado para não reabrir o painel de fim.
    if isinstance(cs, dict):
        cs["result"] = None
    return payload


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
    social_check,
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
    set_feature_choice,
    grant_xp,
    short_rest,
    long_rest,
    use_hit_die,
    set_stat,
    # Sistema de Iniciativa (v3)
    roll_initiative,
    next_turn,
    end_combat,
    # Recrutamento de NPC
    recruit_character,
    # Spawn de monstro com stats reais
    spawn_monster,
    # NPC strategy system
    set_npc_strategy,
    execute_npc_turn,
    # Macro-tools (v4)
    resolve_saving_throw,
]