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


def _parse_dice(formula: str) -> tuple[int, int]:
    """Parseia '2d6' → (2, 6). Fallback para (1, 6)."""
    try:
        parts = formula.lower().strip().split("d")
        n = int(parts[0]) if parts[0] else 1
        s = int(parts[1]) if len(parts) > 1 else 6
        return max(1, n), max(2, s)
    except (ValueError, IndexError):
        return 1, 6


def _get_char(name: str) -> tuple[dict | None, str]:
    """Retorna (char_dict, erro). char é None se não encontrado ou sem ficha."""
    char = memory.campaign["characters"].get(name.lower())
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

    char_key = name.lower()
    existing = memory.campaign["characters"].get(char_key, {})
    memory.campaign["characters"][char_key] = {
        "name":        name,
        "description": description,
        "traits":      existing.get("traits", ""),
        "status":      "vivo",
        "notes":       existing.get("notes", ""),
        "sheet":       sheet,
        "inventario":  existing.get("inventario", []),
        "habilidades": existing.get("habilidades", []),
    }

    if not memory.campaign.get("protagonist"):
        memory.campaign["protagonist"] = name

    memory.save_campaign()
    return (
        f"✅ Ficha criada para {name}!\n"
        f"   Classe: {classe} | Raça: {raca} | Nível: 1\n"
        f"   ❤️  Vida: {hp_max}/{hp_max} | ✨ Mana: {mana_max}/{mana_max} | 🛡️  CA: {10 + dex_mod}\n"
        f"   FOR {_mod_str(forca)}  DES {_mod_str(destreza)}  CON {_mod_str(constituicao)}\n"
        f"   INT {_mod_str(inteligencia)}  SAB {_mod_str(sabedoria)}  CAR {_mod_str(carisma)}\n"
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
    attacker = memory.campaign["characters"].get(attacker_name.lower())
    target   = memory.campaign["characters"].get(target_name.lower())

    if not attacker or not attacker.get("sheet"):
        return f"Atacante '{attacker_name}' não encontrado ou sem ficha D&D."
    if not target or not target.get("sheet"):
        return f"Alvo '{target_name}' não encontrado ou sem ficha D&D."

    sa   = attacker["sheet"]
    st   = target["sheet"]
    mod  = _modifier(sa.get(attack_attribute.lower(), sa["forca"]))
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
        dmg    = max(1, sum(rolls) + mod)
        detail = " + ".join(str(r) for r in rolls)

        result += f"   {'🌟 CRÍTICO! ' if critico else ''}✅ ACERTO!\n"
        result += f"   Dano: [{detail}] +{mod}(mod) = **{dmg}**\n"

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

    n_dice, sides = _parse_dice(hab.get("dado", "1d6"))
    rolls         = [random.randint(1, sides) for _ in range(n_dice)]
    total_dano    = sum(rolls)

    target_str = f" em {target_name}" if target_name else ""
    detail     = " + ".join(str(r) for r in rolls)

    result = (
        f"✨ {char['name']} usa {hab['nome']}{target_str}!\n"
        f"   Custo: {custo} mana | ✨ Mana restante: {s['mana_atual']}/{s['mana_max']}\n"
        f"   🎲 {n_dice}d{sides}: [{detail}] = **{total_dano}**\n"
        f"   Efeito: {hab['descricao']}"
    )

    # ── Aplica efeito ao alvo ────────────────────────────────────────────────
    if target_name:
        target = memory.campaign["characters"].get(target_name.lower())
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

            # ── MODO AUTOMÁTICO: sem saving throw → aplica dano direto ──────────
            hp_antes        = st["vida_atual"]
            st["vida_atual"] = max(0, st["vida_atual"] - total_dano)
            result         += f"\n   {target['name']}: ❤️  {hp_antes} → {st['vida_atual']}/{st['vida_max']}"
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

    Condições reconhecidas mecanicamente:
    cego, envenenado, amedrontado, caído, paralisado, atordoado, invisível,
    enfeitiçado, agarrado, incapacitado, petrificado, surdo, assustado, exausto.

    Args:
        char_name:      Nome do personagem.
        condition:      Nome da condição (ex: 'Cego', 'Envenenado', 'Paralisado').
        duration_turns: Duração em turnos (0 = indefinida, até ser removida manualmente).
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    s      = char["sheet"]
    conds  = s.setdefault("condicoes", [])
    c_low  = condition.lower()

    # Evitar duplicatas
    if any(c["nome"].lower() == c_low for c in conds):
        return f"⚠️  {char['name']} já possui a condição '{condition}'."

    conds.append({
        "nome":    condition.capitalize(),
        "duracao": duration_turns if duration_turns > 0 else None,
    })

    effects = CONDITION_EFFECTS.get(c_low, {})
    efeito_str = []
    if effects.get("attack_disadvantage"):
        efeito_str.append("desvantagem em ataques")
    if effects.get("attack_advantage"):
        efeito_str.append("vantagem em ataques")
    if effects.get("defense_disadvantage"):
        efeito_str.append("atacantes ganham vantagem contra ele")
    if effects.get("check_disadvantage"):
        efeito_str.append("desvantagem em testes de atributo")
    if effects.get("auto_crit"):
        efeito_str.append("ataques corpo-a-corpo são críticos automáticos")

    dur_str = f" por {duration_turns} turno(s)" if duration_turns > 0 else " (indefinidamente)"
    efeito_mecanico = (
        f"\n   Efeito mecânico: {', '.join(efeito_str)}." if efeito_str
        else "\n   (Condição narrativa — sem efeito mecânico automático.)"
    )

    memory.save_campaign()
    return (
        f"🔴 {char['name']} recebeu a condição **{condition.capitalize()}**{dur_str}.{efeito_mecanico}"
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

def add_item(char_name: str, item_name: str, quantity: int = 1, description: str = "") -> str:
    """
    Adiciona um item ao inventário do personagem (empilha se já existir).

    Args:
        char_name:   Nome do personagem.
        item_name:   Nome do item (ex: 'Poção de Cura', 'Espada Longa +1').
        quantity:    Quantidade a adicionar (padrão: 1).
        description: Descrição das propriedades do item (opcional).
    """
    char = memory.campaign["characters"].get(char_name.lower())
    if not char:
        return f"Personagem '{char_name}' não encontrado."

    if "inventario" not in char:
        char["inventario"] = []

    existing = next((i for i in char["inventario"] if i["nome"].lower() == item_name.lower()), None)
    if existing:
        existing["qtd"] += quantity
        if description:
            existing["descricao"] = description
        memory.save_campaign()
        return f"📦 {char['name']} agora tem {existing['qtd']}x {item_name}."

    char["inventario"].append({"nome": item_name, "qtd": quantity, "descricao": description})
    memory.save_campaign()
    return f"📦 {item_name} (x{quantity}) adicionado ao inventário de {char['name']}."


def remove_item(char_name: str, item_name: str, quantity: int = 1) -> str:
    """
    Remove um item do inventário do personagem.

    Args:
        char_name: Nome do personagem.
        item_name: Nome do item.
        quantity:  Quantidade a remover (padrão: 1).
    """
    char = memory.campaign["characters"].get(char_name.lower())
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

    Args:
        char_name: Nome do personagem.
    """
    char = memory.campaign["characters"].get(char_name.lower())
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
    equip = s.get("equipamentos", {})
    equipped = [(slot, item) for slot, item in equip.items() if item]
    if equipped:
        lines.append("  ── Equipados ──")
        for slot, item in equipped:
            lines.append(f"  [⚔️  {slot}] {item}")

    # Inventário geral
    if inv:
        lines.append("  ── Itens ──")
        for item in inv:
            desc = f" — {item['descricao']}" if item.get("descricao") else ""
            lines.append(f"  • {item['nome']} x{item['qtd']}{desc}")
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
        result += "\n   📖 O personagem pode aprender uma nova habilidade!"

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

def roll_initiative(characters_names: str) -> str:
    """
    Rola iniciativa para todos os participantes do combate (aliados e inimigos).
    Ordena do maior para o menor resultado e salva no combat_state.
    DEVE ser chamada no INÍCIO de todo combate — nunca narre o início sem chamar esta ferramenta.

    Para inimigos sem ficha prévia, registra automaticamente uma entrada mínima
    para evitar duplicação futura. NÃO chame create_character_sheet durante a iniciativa.

    Args:
        characters_names: Nomes separados por vírgula. Ex: "Aria, Goblin, Orc Líder"
    """
    names = [n.strip() for n in characters_names.split(",") if n.strip()]
    if not names:
        return "⚠️ Informe ao menos um personagem."

    results = []
    for name in names:
        key  = memory.char_key(name)
        char = memory.campaign["characters"].get(key)

        # NPC desconhecido: registra entrada mínima sem criar ficha completa.
        # Isso evita que a IA receba um aviso pedindo create_character_sheet
        # e acabe chamando a ferramenta com valores de iniciativa como nome.
        if not char:
            memory.campaign["characters"][key] = {
                "name":        name,
                "description": "NPC — registrado ao iniciar combate.",
                "traits":      "",
                "status":      "inimigo",
                "notes":       "",
                "sheet":       None,
                "inventario":  [],
                "habilidades": [],
            }
            char = memory.campaign["characters"][key]

        dex_mod = 0
        if char.get("sheet"):
            dex_mod = _modifier(char["sheet"]["destreza"])

        roll  = random.randint(1, 20)
        total = roll + dex_mod
        sign  = "+" if dex_mod >= 0 else ""
        results.append({
            "name":       name,
            "initiative": total,
            "roll":       roll,
            "mod":        dex_mod,
            "log":        f"d20={roll} {sign}{dex_mod} = **{total}**",
        })

    results.sort(key=lambda x: x["initiative"], reverse=True)

    cs = memory.campaign.setdefault("combat_state", {})
    cs["is_active"]           = True
    cs["initiative_order"]    = [r["name"] for r in results]
    cs["current_turn_index"]  = 0
    cs["round"]               = 1

    memory.save_campaign()

    lines = ["⚔️  Iniciativa rolada! Ordem de combate:"]
    for i, r in enumerate(results):
        marker = " ◀ PRIMEIRO" if i == 0 else ""
        lines.append(f"  {i + 1}. {r['name']}: {r['log']}{marker}")
    lines.append(f"\n🎯 Rodada 1 — vez de: **{results[0]['name']}**")
    return "\n".join(lines)


def next_turn() -> str:
    """
    Avança para o próximo turno na ordem de iniciativa.
    Se o último personagem agiu, inicia uma nova rodada.
    Chame sempre que a ação de um personagem terminar.
    """
    cs = memory.campaign.get("combat_state", {})
    if not cs.get("is_active"):
        return "⚠️ Nenhum combate ativo. Use roll_initiative para iniciar."

    order = cs.get("initiative_order", [])
    if not order:
        return "⚠️ Ordem de iniciativa vazia. Rode roll_initiative primeiro."

    idx       = cs.get("current_turn_index", 0) + 1
    round_num = cs.get("round", 1)

    if idx >= len(order):
        idx        = 0
        round_num += 1
        cs["round"] = round_num

    cs["current_turn_index"] = idx
    current = order[idx]

    memory.save_campaign()

    new_round_msg = f"\n🔔 Nova rodada! Rodada {round_num} começa." if idx == 0 else ""
    return (
        f"⏭️  Turno avançado — Rodada {round_num}{new_round_msg}\n"
        f"🎯 Vez de: **{current}**\n"
        f"   Ordem: {' → '.join(f'[{n}]' if i == idx else n for i, n in enumerate(order))}"
    )


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

DND_TOOLS = [
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