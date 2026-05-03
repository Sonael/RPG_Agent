"""
tools.py
Todas as ferramentas expostas ao agente de RPG.
"""

import memory


# ---------------------------------------------------------------------------
# Personagens
# ---------------------------------------------------------------------------

def save_character(
    name: str,
    description: str,
    traits: str = "",
    status: str = "vivo",
    notes: str = "",
) -> str:
    """
    Salva ou atualiza um personagem (NPC ou membro do grupo) na memória.

    Args:
        name:        Nome do personagem.
        description: Aparência, origem ou papel na história.
        traits:      Personalidade, maneirismos, falas típicas.
        status:      Estado atual (ex: vivo, morto, desaparecido, aliado, inimigo).
        notes:       Qualquer detalhe adicional relevante para a narrativa.
    """
    memory.campaign["characters"][name.lower()] = {
        "name":        name,
        "description": description,
        "traits":      traits,
        "status":      status,
        "notes":       notes,
    }
    memory.save_campaign()
    return f"Personagem '{name}' salvo na memória."


def get_character(name: str) -> str:
    """
    Recupera os detalhes de um personagem pelo nome.

    Args:
        name: Nome do personagem a consultar.
    """
    data = memory.campaign["characters"].get(name.lower())
    if not data:
        return f"Nenhum personagem chamado '{name}' encontrado na memória."
    return (
        f"[{data['name']}]\n"
        f"Descrição: {data['description']}\n"
        f"Traços: {data['traits']}\n"
        f"Status: {data['status']}\n"
        f"Notas: {data['notes']}"
    )


def list_characters() -> str:
    """Lista todos os personagens registrados na memória da campanha."""
    chars = memory.campaign["characters"]
    if not chars:
        return "Nenhum personagem registrado ainda."
    return "\n".join(
        f"- {c['name']} ({c['status']}): {c['description'][:70]}..."
        for c in chars.values()
    )


def update_character_status(name: str, new_status: str, notes: str = "") -> str:
    """
    Atualiza o status e/ou notas de um personagem existente.

    Args:
        name:       Nome do personagem.
        new_status: Novo estado (ex: ferido, morto, aliado confirmado).
        notes:      Notas adicionais a acrescentar (acumula, não substitui).
    """
    data = memory.campaign["characters"].get(name.lower())
    if not data:
        return f"Personagem '{name}' não encontrado. Use save_character primeiro."
    data["status"] = new_status
    if notes:
        data["notes"] = (data["notes"] + " | " + notes).strip(" | ")
    memory.save_campaign()
    return f"Status de '{name}' atualizado para '{new_status}'."


# ---------------------------------------------------------------------------
# Grupo (party)
# ---------------------------------------------------------------------------

def add_party_member(name: str, role: str = "", notes: str = "") -> str:
    """
    Adiciona um personagem ao grupo ativo do jogador.

    Args:
        name:  Nome do personagem.
        role:  Função no grupo (ex: guerreira, mago, ladino).
        notes: Detalhes adicionais sobre o membro.
    """
    party = memory.campaign["party"]
    if any(m["name"].lower() == name.lower() for m in party):
        return f"'{name}' já está no grupo."
    party.append({"name": name, "role": role, "notes": notes})
    memory.save_campaign()
    return f"'{name}' adicionado ao grupo."


def remove_party_member(name: str) -> str:
    """
    Remove um personagem do grupo ativo.

    Args:
        name: Nome do personagem a remover.
    """
    party = memory.campaign["party"]
    original = len(party)
    memory.campaign["party"] = [m for m in party if m["name"].lower() != name.lower()]
    if len(memory.campaign["party"]) < original:
        memory.save_campaign()
        return f"'{name}' removido do grupo."
    return f"'{name}' não está no grupo."


def list_party() -> str:
    """Lista os membros atuais do grupo."""
    party = memory.campaign["party"]
    if not party:
        return "Nenhum membro no grupo ainda."
    return "\n".join(
        f"- {m['name']} ({m['role']}): {m['notes']}" for m in party
    )


# ---------------------------------------------------------------------------
# Locais
# ---------------------------------------------------------------------------

def save_location(
    name: str,
    description: str,
    details: str = "",
    notes: str = "",
) -> str:
    """
    Salva ou atualiza um local na memória da campanha.

    Args:
        name:        Nome do local (ex: Taverna do Corvo, Floresta de Mirwen).
        description: Descrição sensorial e atmosférica do ambiente.
        details:     Detalhes: NPCs presentes, objetos notáveis, saídas.
        notes:       Eventos passados ou segredos ligados ao local.
    """
    memory.campaign["locations"][name.lower()] = {
        "name":        name,
        "description": description,
        "details":     details,
        "notes":       notes,
    }
    memory.save_campaign()
    return f"Local '{name}' salvo na memória."


def get_location(name: str) -> str:
    """
    Recupera os detalhes de um local pelo nome.

    Args:
        name: Nome do local a consultar.
    """
    data = memory.campaign["locations"].get(name.lower())
    if not data:
        return f"Nenhum local chamado '{name}' encontrado na memória."
    return (
        f"[{data['name']}]\n"
        f"Descrição: {data['description']}\n"
        f"Detalhes: {data['details']}\n"
        f"Notas: {data['notes']}"
    )


def list_locations() -> str:
    """Lista todos os locais registrados na memória da campanha."""
    locs = memory.campaign["locations"]
    if not locs:
        return "Nenhum local registrado ainda."
    return "\n".join(
        f"- {loc['name']}: {loc['description'][:70]}..."
        for loc in locs.values()
    )


# ---------------------------------------------------------------------------
# Eventos
# ---------------------------------------------------------------------------

def save_event(
    summary: str,
    characters_involved: str = "",
    location: str = "",
    consequence: str = "",
) -> str:
    """
    Registra um acontecimento importante na linha do tempo.

    Args:
        summary:             Resumo do que aconteceu.
        characters_involved: Personagens envolvidos (nomes separados por vírgula).
        location:            Local onde ocorreu.
        consequence:         Consequência ou mudança no mundo.
    """
    events = memory.campaign["events"]
    event = {
        "index":               len(events) + 1,
        "summary":             summary,
        "characters_involved": characters_involved,
        "location":            location,
        "consequence":         consequence,
    }
    events.append(event)
    memory.save_campaign()
    return f"Evento #{event['index']} registrado: {summary[:60]}"


def get_recent_events(count: int = 5) -> str:
    """
    Retorna os eventos mais recentes da campanha.

    Args:
        count: Quantidade de eventos a retornar (padrão: 5).
    """
    events = memory.campaign["events"]
    if not events:
        return "Nenhum evento registrado ainda."
    lines = []
    for e in events[-count:]:
        lines.append(
            f"[Evento #{e['index']}] {e['summary']}\n"
            f"  Personagens: {e['characters_involved']}\n"
            f"  Local: {e['location']}\n"
            f"  Consequência: {e['consequence']}"
        )
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Estado do mundo
# ---------------------------------------------------------------------------

def update_world_state(
    current_scene: str = "",
    current_location: str = "",
    chapter: int = 0,
) -> str:
    """
    Atualiza o estado atual do mundo: cena, local e capítulo.
    Passe apenas os campos que mudaram.

    Args:
        current_scene:    Descrição breve da cena em curso.
        current_location: Nome do local onde o grupo está agora.
        chapter:          Número do capítulo atual (0 = não alterar).
    """
    if current_scene:
        memory.campaign["current_scene"] = current_scene
    if current_location:
        memory.campaign["current_location"] = current_location
    if chapter > 0:
        memory.campaign["chapter"] = chapter
    memory.save_campaign()
    return (
        f"Estado do mundo atualizado — "
        f"Capítulo: {memory.campaign['chapter']}, "
        f"Local: {memory.campaign['current_location']}, "
        f"Cena: {memory.campaign['current_scene']}"
    )


def update_story_summary(summary: str) -> str:
    """
    Substitui o resumo vivo da história por uma versão atualizada.
    Mantenha o resumo conciso (10–20 linhas), cobrindo os pontos
    mais importantes da narrativa até agora.

    Args:
        summary: Novo resumo da história.
    """
    memory.campaign["story_summary"] = summary
    memory.save_campaign()
    return "Resumo da história atualizado."


# ---------------------------------------------------------------------------
# Flags / variáveis de estado
# ---------------------------------------------------------------------------

def set_flag(name: str, value: str) -> str:
    """
    Define ou atualiza uma flag de estado da campanha.
    Flags marcam decisões importantes que influenciam eventos futuros.

    Exemplos: set_flag('ajudou_elara', 'sim'), set_flag('portão_aberto', 'não')

    Args:
        name:  Nome da flag (sem espaços, use underscore).
        value: Valor da flag (string).
    """
    memory.campaign["quest_flags"][name] = value
    memory.save_campaign()
    return f"Flag '{name}' definida como '{value}'."


def get_flag(name: str) -> str:
    """
    Retorna o valor de uma flag de estado.

    Args:
        name: Nome da flag.
    """
    value = memory.campaign["quest_flags"].get(name)
    if value is None:
        return f"Flag '{name}' não definida."
    return f"{name} = {value}"


def list_flags() -> str:
    """Lista todas as flags de estado da campanha."""
    flags = memory.campaign["quest_flags"]
    if not flags:
        return "Nenhuma flag definida ainda."
    return "\n".join(f"  {k} = {v}" for k, v in flags.items())


def clear_flag(name: str) -> str:
    """
    Remove uma flag de estado.

    Args:
        name: Nome da flag a remover.
    """
    if name in memory.campaign["quest_flags"]:
        del memory.campaign["quest_flags"][name]
        memory.save_campaign()
        return f"Flag '{name}' removida."
    return f"Flag '{name}' não encontrada."


# ---------------------------------------------------------------------------
# Diário de campanha
# ---------------------------------------------------------------------------

def add_diary_entry(title: str, content: str) -> str:
    """
    Adiciona uma entrada ao diário da campanha.
    Use para registrar acontecimentos importantes, decisões dos jogadores
    e mudanças significativas no mundo.

    Args:
        title:   Título da entrada (ex: 'O encontro na taverna').
        content: Texto detalhado do acontecimento (narrado em terceira pessoa).
    """
    entry = {
        "chapter": memory.campaign["chapter"],
        "title":   title,
        "content": content,
    }
    memory.campaign["diary"].append(entry)
    memory.save_campaign()
    return f"Entrada '{title}' adicionada ao diário (Capítulo {entry['chapter']})."


def get_diary(last: int = 5) -> str:
    """
    Retorna as últimas entradas do diário de campanha.

    Args:
        last: Número de entradas a retornar (padrão: 5).
    """
    diary = memory.campaign["diary"]
    if not diary:
        return "O diário está vazio."
    lines = []
    for entry in diary[-last:]:
        lines.append(
            f"[Cap. {entry.get('chapter', '?')}] {entry.get('title', '')}\n"
            f"{entry.get('content', '')}"
        )
    return "\n\n---\n\n".join(lines)


# ---------------------------------------------------------------------------
# Contexto dinâmico por cena (mais barato que get_full_context)
# ---------------------------------------------------------------------------

def get_scene_context(extra_characters: str = "", extra_locations: str = "") -> str:
    """
    Retorna apenas o contexto relevante para a cena atual:
    estado do mundo, grupo, personagens e local presentes agora,
    flags ativas e os 3 eventos mais recentes.

    Use este em vez de get_full_context() durante o jogo normal.
    Reserve get_full_context() apenas para reancoragem após retomada.

    Args:
        extra_characters: Nomes adicionais (vírgula) a incluir além do local atual.
        extra_locations:  Nomes adicionais de locais a incluir.
    """
    c    = memory.campaign
    parts = []

    # Estado do mundo
    parts.append(
        f"[Cap.{c['chapter']} | {c['current_location'] or 'local desconhecido'}]\n"
        f"Cena: {c['current_scene'] or 'não definida'}"
    )

    # Resumo (só as primeiras 3 linhas para economizar tokens)
    summary = c.get("story_summary", "")
    if summary:
        short = "\n".join(summary.splitlines()[:3])
        parts.append(f"Resumo: {short}")

    # Grupo
    if c["party"]:
        party_str = ", ".join(f"{m['name']} ({m['role']})" for m in c["party"])
        parts.append(f"Grupo: {party_str}")

    # Personagens relevantes: os do local atual + extras solicitados
    current_loc_norm = (c.get("current_location") or "").lower()
    extra_names = {n.strip().lower() for n in extra_characters.split(",") if n.strip()}

    relevant_chars = []
    for key, ch in c["characters"].items():
        in_location = current_loc_norm and current_loc_norm in (ch.get("notes", "") + ch.get("description", "")).lower()
        explicitly_requested = key in extra_names or ch["name"].lower() in extra_names
        in_party = any(m["name"].lower() == key for m in c["party"])
        if in_location or explicitly_requested or in_party:
            relevant_chars.append(ch)

    # Se nenhum foi selecionado, inclui todos (campanha pequena ainda)
    if not relevant_chars:
        relevant_chars = list(c["characters"].values())

    if relevant_chars:
        lines = []
        for ch in relevant_chars:
            lines.append(f"• {ch['name']} ({ch['status']}): {ch['description'][:80]}")
            if ch.get("traits"):
                lines.append(f"  Traços: {ch['traits'][:60]}")
        parts.append("Personagens:\n" + "\n".join(lines))

    # Local atual
    loc_data = c["locations"].get(current_loc_norm)
    extra_loc_names = {n.strip().lower() for n in extra_locations.split(",") if n.strip()}

    locs_to_show = []
    if loc_data:
        locs_to_show.append(loc_data)
    for key, loc in c["locations"].items():
        if key in extra_loc_names and loc not in locs_to_show:
            locs_to_show.append(loc)

    if locs_to_show:
        lines = []
        for loc in locs_to_show:
            lines.append(f"• {loc['name']}: {loc['description'][:100]}")
            if loc.get("details"):
                lines.append(f"  Detalhes: {loc['details'][:80]}")
        parts.append("Locais:\n" + "\n".join(lines))

    # Flags ativas
    if c["quest_flags"]:
        flags_str = " | ".join(f"{k}={v}" for k, v in c["quest_flags"].items())
        parts.append(f"Flags: {flags_str}")

    # Últimos 3 eventos
    if c["events"]:
        recent = c["events"][-3:]
        lines  = [f"• #{e['index']}: {e['summary']} → {e['consequence']}" for e in recent]
        parts.append("Eventos recentes:\n" + "\n".join(lines))

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Contexto geral
# ---------------------------------------------------------------------------

def get_full_context() -> str:
    """
    Retorna um dump completo da memória da campanha: estado do mundo,
    grupo, personagens, locais, flags, eventos e resumo da história.
    Útil para reancoragem narrativa.
    """
    c = memory.campaign
    parts = []

    parts.append("=== ESTADO DO MUNDO ===")
    parts.append(
        f"Capítulo: {c['chapter']}  |  "
        f"Local atual: {c['current_location'] or 'desconhecido'}  |  "
        f"Cena atual: {c['current_scene'] or 'não definida'}"
    )

    parts.append("\n=== RESUMO DA HISTÓRIA ===")
    parts.append(c["story_summary"] or "Nenhum resumo registrado ainda.")

    parts.append("\n=== GRUPO ===")
    if c["party"]:
        parts.append("\n".join(f"• {m['name']} ({m['role']}): {m['notes']}" for m in c["party"]))
    else:
        parts.append("Nenhum membro no grupo.")

    parts.append("\n=== PERSONAGENS ===")
    if c["characters"]:
        for ch in c["characters"].values():
            parts.append(
                f"• {ch['name']} ({ch['status']})\n"
                f"  {ch['description']}\n"
                f"  Traços: {ch['traits']}\n"
                f"  Notas: {ch['notes']}"
            )
    else:
        parts.append("Nenhum.")

    parts.append("\n=== LOCAIS ===")
    if c["locations"]:
        for loc in c["locations"].values():
            parts.append(
                f"• {loc['name']}\n"
                f"  {loc['description']}\n"
                f"  Detalhes: {loc['details']}\n"
                f"  Notas: {loc['notes']}"
            )
    else:
        parts.append("Nenhum.")

    parts.append("\n=== FLAGS ===")
    if c["quest_flags"]:
        parts.append("\n".join(f"  {k} = {v}" for k, v in c["quest_flags"].items()))
    else:
        parts.append("Nenhuma.")

    parts.append("\n=== LINHA DO TEMPO ===")
    if c["events"]:
        for e in c["events"]:
            parts.append(
                f"#{e['index']}: {e['summary']} "
                f"(Local: {e['location']}, "
                f"Personagens: {e['characters_involved']}, "
                f"Consequência: {e['consequence']})"
            )
    else:
        parts.append("Nenhum evento registrado.")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Lista exportável de todas as ferramentas
# ---------------------------------------------------------------------------

ALL_TOOLS = [
    # Personagens
    save_character,
    get_character,
    list_characters,
    update_character_status,
    # Grupo
    add_party_member,
    remove_party_member,
    list_party,
    # Locais
    save_location,
    get_location,
    list_locations,
    # Eventos
    save_event,
    get_recent_events,
    # Estado do mundo
    update_world_state,
    update_story_summary,
    # Flags
    set_flag,
    get_flag,
    list_flags,
    clear_flag,
    # Diário
    add_diary_entry,
    get_diary,
    # Contexto (dinâmico e completo)
    get_scene_context,
    get_full_context,
]