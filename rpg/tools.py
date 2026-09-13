"""
tools.py
Todas as ferramentas expostas ao agente de RPG.
Inclui as ferramentas base de narrativa e as ferramentas D&D (tools_dnd.py).
"""

from rpg import memory
from rpg.tools_dnd import DND_TOOLS


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
    key = memory.char_key(name)
    existing = memory.campaign["characters"].get(key, {})
    memory.campaign["characters"][key] = {
        "name":        existing.get("name", name),  # preserva capitalização original
        "description": description,
        "traits":      traits,
        "status":      status,
        "notes":       notes,
        # Preserva campos D&D se já existirem (evita sobrescrever ficha com save_character)
        "sheet":       existing.get("sheet"),
        "inventario":  existing.get("inventario", []),
        "habilidades": existing.get("habilidades", []),
    }
    memory.save_campaign()
    return f"Personagem '{name}' salvo na memória."


def get_character(name: str) -> str:
    """
    Recupera os detalhes de um personagem pelo nome.
    Se o personagem tiver ficha D&D, exibe também os atributos e recursos.

    Args:
        name: Nome do personagem a consultar.
    """
    data = memory.campaign["characters"].get(memory.char_key(name))
    if not data:
        return f"Nenhum personagem chamado '{name}' encontrado na memória."

    base = (
        f"[{data['name']}]\n"
        f"Descrição: {data['description']}\n"
        f"Traços: {data['traits']}\n"
        f"Status: {data['status']}\n"
        f"Notas: {data['notes']}"
    )

    sheet = data.get("sheet")
    if not sheet:
        return base

    # Resumo compacto da ficha D&D para consulta rápida durante o jogo
    s = sheet
    def _mod(v): return (v - 10) // 2
    def _ms(v):
        m = _mod(v)
        return f"{v}({'+' if m >= 0 else ''}{m})"

    sheet_summary = (
        f"\n── Ficha D&D ──────────────────────\n"
        f"  {s['classe']} {s['raca']} Nível {s['nivel']} | XP {s['xp']}/{s.get('xp_proximo', '?')}\n"
        f"  PV {s['vida_atual']}/{s['vida_max']}  Mana {s['mana_atual']}/{s['mana_max']}  CA {s['ca']}\n"
        f"  FOR {_ms(s['forca'])}  DES {_ms(s['destreza'])}  CON {_ms(s['constituicao'])}\n"
        f"  INT {_ms(s['inteligencia'])}  SAB {_ms(s['sabedoria'])}  CAR {_ms(s['carisma'])}\n"
        f"  Prof: +{s['proficiencia']}"
    )
    habs = data.get("habilidades", [])
    if habs:
        sheet_summary += "\n  Habilidades: " + ", ".join(h["nome"] for h in habs)
    inv = data.get("inventario", [])
    if inv:
        sheet_summary += "\n  Inventário: " + ", ".join(f"{i['nome']} x{i['qtd']}" for i in inv)

    return base + sheet_summary


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
    data = memory.campaign["characters"].get(memory.char_key(name))
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
    party    = memory.campaign["party"]
    name_key = memory.char_key(name)
    if any(memory.char_key(m["name"]) == name_key for m in party):
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
    party    = memory.campaign["party"]
    name_key = memory.char_key(name)
    original = len(party)
    memory.campaign["party"] = [m for m in party if memory.char_key(m["name"]) != name_key]
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
    if current_location or current_scene:
        memory.marcar_upkeep("mundo")
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
    memory.marcar_upkeep("resumo")
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
    memory.marcar_upkeep("diario")
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
# Missões como objetos
# ---------------------------------------------------------------------------
#
# Missão era `quest_flags`: um dicionário plano de string para string. Cabia
# "escoltar_princesa = aceito" e mais nada — sem objetivos, sem quem mandou,
# sem recompensa combinada, sem saber o que já foi feito. Na prática o jogador
# perguntava "o que a gente tinha que fazer mesmo?" e a resposta dependia do
# LLM lembrar de uma conversa de vinte cenas atrás.
#
# As flags CONTINUAM existindo e não foram tocadas: elas são boas no que
# fazem, que é guardar um fato do mundo ("a ponte caiu"). Missão é outra
# coisa — tem estado, partes e um fim.

_STATUS_MISSAO = ("ativa", "concluida", "falhou", "abandonada")


def _missoes() -> dict:
    return memory.campaign.setdefault("quests", {})


def _chave_missao(titulo: str) -> str:
    return (titulo or "").lower().strip().replace("_", " ")


def add_quest(title: str, description: str, objectives: str = "",
              giver: str = "", reward: str = "") -> str:
    """
    Registra uma missão. Chame no momento em que o grupo ACEITA a tarefa —
    não quando alguém apenas menciona um problema no mundo.

    Args:
        title:       Nome curto e reconhecível ('Escoltar a Princesa Elara').
        description: O que é a missão, em uma ou duas frases.
        objectives:  Passos separados por ';'. Ex: "Chegar a Luminas; Entregar
                     a carta ao regente". Deixe vazio se for um passo só.
        giver:       Quem encomendou (nome do NPC).
        reward:      O que foi combinado ('200 po e a espada do pai dela').
    """
    titulo = (title or "").strip()
    if not titulo:
        return "A missão precisa de um título."

    chave = _chave_missao(titulo)
    if chave in _missoes():
        return (f"Aviso: Já existe a missão '{titulo}'. Use update_quest_objective() "
                f"para marcar progresso ou complete_quest() para encerrá-la.")

    passos = [o.strip() for o in (objectives or "").split(";") if o.strip()]
    _missoes()[chave] = {
        "titulo":     titulo,
        "descricao":  description,
        "status":     "ativa",
        "objetivos":  [{"texto": o, "feito": False} for o in passos],
        "quem_deu":   giver,
        "recompensa": reward,
        "cap_inicio": memory.campaign.get("chapter", 1),
    }
    memory.save_campaign()

    linhas = [f"Missão aceita: **{titulo}**"]
    if giver:
        linhas.append(f"   De: {giver}")
    for o in passos:
        linhas.append(f"   [ ] {o}")
    if reward:
        linhas.append(f"   Recompensa combinada: {reward}")
    return "\n".join(linhas)


def update_quest_objective(title: str, objective: str, done: bool = True) -> str:
    """
    Marca (ou desmarca) um objetivo de uma missão.

    Args:
        title:     Título da missão.
        objective: Texto do objetivo, ou parte dele — casa por trecho.
        done:      True para concluir, False para reabrir.
    """
    missao = _missoes().get(_chave_missao(title))
    if not missao:
        return f"Aviso: Missão '{title}' não encontrada. Veja list_quests()."

    alvo = (objective or "").lower().strip()
    achou = None
    for o in missao["objetivos"]:
        if alvo and alvo in o["texto"].lower():
            achou = o
            break
    if not achou:
        # Objetivo novo descoberto no meio da missão: registra em vez de
        # recusar. Missão que só aceita o plano original não sobrevive à mesa.
        achou = {"texto": objective, "feito": False}
        missao["objetivos"].append(achou)

    achou["feito"] = bool(done)
    memory.save_campaign()

    feitos = sum(1 for o in missao["objetivos"] if o["feito"])
    total  = len(missao["objetivos"])
    marca  = "[x]" if done else "[ ]"
    fim = ""
    if feitos == total and total > 0 and missao["status"] == "ativa":
        fim = ("\n   Todos os objetivos concluídos — encerre com "
               "complete_quest() e entregue a recompensa.")
    return (f"{marca} {missao['titulo']}: {achou['texto']}  "
            f"({feitos}/{total}){fim}")


def complete_quest(title: str, outcome: str = "concluida", notes: str = "") -> str:
    """
    Encerra uma missão.

    Args:
        title:   Título da missão.
        outcome: 'concluida', 'falhou' ou 'abandonada'.
        notes:   Como terminou (uma linha) — fica no registro.
    """
    missao = _missoes().get(_chave_missao(title))
    if not missao:
        return f"Aviso: Missão '{title}' não encontrada. Veja list_quests()."

    fim = (outcome or "concluida").lower().strip()
    if fim not in _STATUS_MISSAO or fim == "ativa":
        return (f"Aviso: Desfecho '{outcome}' inválido. Use: concluida, falhou "
                f"ou abandonada.")

    missao["status"]   = fim
    missao["cap_fim"]  = memory.campaign.get("chapter", 1)
    if notes:
        missao["desfecho"] = notes
    memory.save_campaign()

    linha = f"Missão **{missao['titulo']}** — {fim}."
    if fim == "concluida" and missao.get("recompensa"):
        linha += (f"\n   Recompensa combinada: {missao['recompensa']} "
                  f"— entregue com add_item()/modify_currency().")
    if notes:
        linha += f"\n   {notes}"
    return linha


def list_quests(include_closed: bool = False) -> str:
    """
    Lista as missões. Por padrão só as ativas — é o que o jogador quer saber
    quando pergunta "o que a gente tinha que fazer mesmo?".

    Args:
        include_closed: True para incluir concluídas, falhadas e abandonadas.
    """
    todas = _missoes()
    if not todas:
        return "Nenhuma missão registrada."

    ativas  = [m for m in todas.values() if m["status"] == "ativa"]
    fechadas = [m for m in todas.values() if m["status"] != "ativa"]

    linhas = []
    if ativas:
        linhas.append("Missões ativas:")
        for m in ativas:
            feitos = sum(1 for o in m["objetivos"] if o["feito"])
            total  = len(m["objetivos"])
            cabeca = f"  • **{m['titulo']}**"
            if total:
                cabeca += f"  ({feitos}/{total})"
            if m.get("quem_deu"):
                cabeca += f" — de {m['quem_deu']}"
            linhas.append(cabeca)
            for o in m["objetivos"]:
                linhas.append(f"      {'[x]' if o['feito'] else '[ ]'} {o['texto']}")
    else:
        linhas.append("Nenhuma missão ativa.")

    if include_closed and fechadas:
        linhas.append("\nEncerradas:")
        for m in fechadas:
            linhas.append(f"  - {m['titulo']} — {m['status']}")
    elif fechadas:
        linhas.append(f"\n({len(fechadas)} encerrada(s) — "
                      f"list_quests(include_closed=True) para ver)")
    return "\n".join(linhas)


def get_quest(title: str) -> str:
    """
    Detalhe de uma missão: objetivos, quem encomendou, recompensa, desfecho.

    Args:
        title: Título da missão.
    """
    missao = _missoes().get(_chave_missao(title))
    if not missao:
        return f"Aviso: Missão '{title}' não encontrada. Veja list_quests()."
    linhas = [f"**{missao['titulo']}** ({missao['status']})",
              f"   {missao.get('descricao', '')}"]
    if missao.get("quem_deu"):
        linhas.append(f"   Encomendada por: {missao['quem_deu']}")
    for o in missao["objetivos"]:
        linhas.append(f"   {'[x]' if o['feito'] else '[ ]'} {o['texto']}")
    if missao.get("recompensa"):
        linhas.append(f"   Recompensa: {missao['recompensa']}")
    if missao.get("desfecho"):
        linhas.append(f"   Desfecho: {missao['desfecho']}")
    linhas.append(f"   Começou no capítulo {missao.get('cap_inicio', '?')}"
                  + (f", terminou no {missao['cap_fim']}" if missao.get("cap_fim") else ""))
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Atitude de NPC — a memória social da campanha
# ---------------------------------------------------------------------------
#
# O que um NPC achava do grupo não existia em lugar nenhum. Ficava no texto
# livre de `notes` (se o mestre escrevesse) ou na cabeça dele — ou seja, na
# prática se perdia. Salvar o ferreiro depois virava um "obrigado" e nada mais;
# roubar dele também não custava nada dez cenas depois.
#
# Aqui vira NÚMERO, de -100 a +100, com um rótulo derivado. O número é o que
# sobrevive à conversa; o rótulo é o que o mestre lê.
#
# Vale em QUALQUER campanha, não só D&D: atitude é matéria de romance, de
# mistério e de faroeste tanto quanto de masmorra.

_FAIXAS_ATITUDE = (
    (-100, -60, "hostil",       "Ataca, denuncia ou sabota se puder"),
    ( -59, -20, "desconfiado",  "Recusa favores, cobra caro, vigia"),
    ( -19,  19, "neutro",       "Trata como estranho"),
    (  20,  59, "amistoso",     "Ajuda quando é barato, dá desconto"),
    (  60, 100, "leal",         "Arrisca-se pelo grupo"),
)


def _faixa_atitude(valor: int):
    for baixo, alto, rotulo, conduta in _FAIXAS_ATITUDE:
        if baixo <= valor <= alto:
            return rotulo, conduta
    return "neutro", "Trata como estranho"


def atitude_de(char: dict) -> int:
    """Atitude atual de um personagem (0 quando nunca foi mexida)."""
    try:
        return max(-100, min(100, int(char.get("atitude", 0) or 0)))
    except (TypeError, ValueError):
        return 0


def adjust_attitude(name: str, delta: int, reason: str = "") -> str:
    """
    Move a atitude de um NPC em relação ao grupo. Chame quando o grupo fizer
    algo que um NPC notaria: cumprir a palavra, trair, salvar, roubar, humilhar.

    A escala vai de -100 (hostil) a +100 (leal). Sugestão de peso:
      ±5   cortesia, uma piada boa, uma grosseria
      ±15  um favor pequeno cumprido, uma promessa quebrada
      ±30  salvar a vida, roubar, entregar às autoridades
      ±50  traição grave ou sacrifício pelo NPC

    Args:
        name:   Nome do NPC.
        delta:  Quanto somar (negativo para piorar).
        reason: O que causou a mudança — fica registrado na ficha.
    """
    key  = memory.char_key(name)
    char = memory.campaign["characters"].get(key)
    if not char:
        return (f"Personagem '{name}' não encontrado. "
                f"Use save_character primeiro — atitude é memória, e memória "
                f"precisa de alguém para lembrar.")
    try:
        d = int(delta)
    except (TypeError, ValueError):
        return "Informe delta como número inteiro (ex: -15, 30)."

    antes  = atitude_de(char)
    depois = max(-100, min(100, antes + d))
    char["atitude"] = depois

    # Histórico curto: o mestre precisa saber POR QUE alguém odeia o grupo,
    # não só que odeia. Cinco entradas bastam para a cena; mais que isso é
    # peso morto no contexto.
    if reason:
        hist = char.setdefault("atitude_historico", [])
        hist.append({"delta": d, "motivo": reason,
                     "cap": memory.campaign.get("chapter", 1)})
        del hist[:-5]

    r_antes, _        = _faixa_atitude(antes)
    r_depois, conduta = _faixa_atitude(depois)
    motivo = f" — {reason}" if reason else ""
    linha  = (f"{char['name']}: atitude {antes:+d} → **{depois:+d}** "
              f"({r_depois}){motivo}")
    if r_antes != r_depois:
        linha += f"\n   Mudou de faixa: {r_antes} → **{r_depois}**. {conduta}."
    memory.save_campaign()
    return linha


def get_attitude(name: str) -> str:
    """
    Mostra a atitude de um NPC e o que a construiu.

    Args:
        name: Nome do NPC.
    """
    char = memory.campaign["characters"].get(memory.char_key(name))
    if not char:
        return f"Personagem '{name}' não encontrado."
    valor           = atitude_de(char)
    rotulo, conduta = _faixa_atitude(valor)
    linhas = [f"{char['name']}: **{valor:+d}** ({rotulo}) — {conduta}."]
    hist = char.get("atitude_historico") or []
    if hist:
        linhas.append("   Como chegou aí:")
        for h in hist:
            linhas.append(f"     {h.get('delta', 0):+d}  {h.get('motivo', '')} "
                          f"(cap. {h.get('cap', '?')})")
    return "\n".join(linhas)


def list_attitudes() -> str:
    """Todos os NPCs que já formaram opinião sobre o grupo, do pior ao melhor."""
    com_opiniao = [
        (atitude_de(c), c) for c in memory.campaign["characters"].values()
        if c.get("atitude") not in (None, 0)
    ]
    if not com_opiniao:
        return "Nenhum NPC formou opinião sobre o grupo ainda."
    com_opiniao.sort(key=lambda par: par[0])
    linhas = []
    for valor, c in com_opiniao:
        rotulo, _ = _faixa_atitude(valor)
        linhas.append(f"  {valor:+4d}  {c['name']} ({rotulo})")
    return "Atitude dos NPCs em relação ao grupo:\n" + "\n".join(linhas)


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

    # Relógio: sem ele na cena o agente não tem como saber que anoiteceu nem
    # há quanto tempo ninguém dorme — e voltaria a tratar descanso como grátis.
    rel = c.get("relogio")
    if rel:
        from rpg.tools_dnd import _periodo
        h = int(rel.get("hora", 8) or 8)
        parts.append(f"Tempo: Dia {rel.get('dia', 1)}, {h:02d}h ({_periodo(h)})")

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

    # ATENÇÃO ao que esta lista é e ao que ela NÃO é. Não existe registro de
    # quem está fisicamente na cena. O que dá para inferir é "é do grupo"
    # (confiável) e "o local atual aparece na descrição/notas do personagem"
    # (indício fraco: o texto de um NPC menciona o lugar para sempre, mesmo
    # depois de ele ter saído dali).
    #
    # O bloco era rotulado só "Personagens:" e a instrução mandava confiar nele
    # para saber QUEM ESTÁ PRESENTE. O agente então tratava a lista como elenco
    # da cena — e chegou a rolar iniciativa para NPC que estava em outro ponto
    # da história. O rótulo agora diz exatamente o que a lista significa.
    no_grupo = set()
    relevant_chars = []
    for key, ch in c["characters"].items():
        in_location = current_loc_norm and current_loc_norm in (ch.get("notes", "") + ch.get("description", "")).lower()
        explicitly_requested = key in extra_names or ch["name"].lower() in extra_names
        in_party = any(m["name"].lower().strip() == key for m in c["party"])
        if in_location or explicitly_requested or in_party:
            relevant_chars.append(ch)
            if in_party:
                no_grupo.add(id(ch))

    # Sem ninguém selecionado, cai na campanha inteira — útil no começo, quando
    # ainda não há grupo nem local. Mas aí a lista é ainda MENOS um elenco de
    # cena, e o rótulo tem de avisar.
    campanha_inteira = False
    if not relevant_chars:
        relevant_chars = list(c["characters"].values())
        campanha_inteira = True

    if relevant_chars:
        lines = []
        for ch in relevant_chars:
            marca = " [grupo]" if id(ch) in no_grupo else ""
            lines.append(f"• {ch['name']}{marca} ({ch['status']}): {ch['description'][:80]}")
            if ch.get("traits"):
                lines.append(f"  Traços: {ch['traits'][:60]}")
        titulo = (
            "Personagens conhecidos (a campanha INTEIRA — ainda não há grupo "
            "nem local para filtrar; quem está na cena quem decide é você)"
            if campanha_inteira else
            "Personagens conhecidos — os marcados [grupo] estão com o jogador; "
            "os demais apenas têm LIGAÇÃO com este local e podem não estar "
            "presentes agora"
        )
        parts.append(titulo + ":\n" + "\n".join(lines))

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

    # Missões ativas — o jogador pergunta "o que a gente tinha que fazer?" e a
    # resposta não pode depender de o agente lembrar de vinte cenas atrás.
    ativas = [m for m in (c.get("quests") or {}).values()
              if m.get("status") == "ativa"]
    if ativas:
        linhas = []
        for m in ativas[:5]:
            feitos = sum(1 for o in m.get("objetivos", []) if o.get("feito"))
            total  = len(m.get("objetivos", []))
            passo  = next((o["texto"] for o in m.get("objetivos", [])
                           if not o.get("feito")), "")
            linhas.append(f"• {m['titulo']} ({feitos}/{total})"
                          + (f" → falta: {passo}" if passo else ""))
        parts.append("Missões ativas:\n" + "\n".join(linhas))

    # Quem já formou opinião sobre o grupo. Só os que saíram do neutro — o
    # resto seria ruído.
    opinioes = [
        (atitude_de(ch), ch) for ch in c["characters"].values()
        if ch.get("atitude") not in (None, 0)
    ]
    if opinioes:
        opinioes.sort(key=lambda par: par[0])
        parts.append("Atitude dos NPCs: " + " | ".join(
            f"{ch['name']} {valor:+d} ({_faixa_atitude(valor)[0]})"
            for valor, ch in opinioes[:8]))

    # Flags ativas
    if c["quest_flags"]:
        flags_str = " | ".join(f"{k}={v}" for k, v in c["quest_flags"].items())
        parts.append(f"Flags: {flags_str}")

    # Últimos 3 eventos
    if c["events"]:
        recent = c["events"][-3:]
        lines  = [f"• #{e['index']}: {e['summary']} → {e['consequence']}" for e in recent]
        parts.append("Eventos recentes:\n" + "\n".join(lines))

    # ── Status D&D e combate ────────────────────────────────────────────
    party_names   = {m["name"].lower() for m in c["party"]}
    cs            = c.get("combat_state", {})
    combat_active = cs.get("is_active", False)

    def _bar(cur, mx, w=8):
        pct    = cur / mx if mx > 0 else 0
        filled = int(pct * w)
        return "▓" * filled + "░" * (w - filled)

    def _warn(ch, s):
        st = (ch.get("status") or "").lower()
        if st == "morto":                          return ""
        if s["vida_atual"] == 0:                   return " INCONSCIENTE"
        if s["vida_atual"] <= s["vida_max"] // 4:  return " CRÍTICO"
        return ""

    def _conds(ch):
        cds = [cd.get("nome", "") for cd in (ch.get("sheet") or {}).get("condicoes", []) if cd.get("nome")]
        return "  [" + ", ".join(cds) + "]" if cds else ""

    if combat_active:
        # COMBATE: mostra TODOS os combatentes (grupo E inimigos) com HP/CA/
        # condições — é a informação que o agente precisa para narrar e decidir.
        order   = cs.get("initiative_order", [])
        idx     = cs.get("current_turn_index", 0)
        round_n = cs.get("round", 1)
        current = order[idx] if order and 0 <= idx < len(order) else "?"
        lines = []
        for i, nome in enumerate(order):
            mark = "->" if i == idx else "  "
            ch   = c["characters"].get(memory.char_key(nome))
            if not ch or not ch.get("sheet"):
                lines.append(f"  {mark} {nome}")
                continue
            s    = ch["sheet"]
            icon = "" if memory.is_party_member(ch) else "[inimigo] "
            mana = f"  Mana {s['mana_atual']}/{s['mana_max']}" if s.get("mana_max", 0) else ""
            lines.append(
                f"  {mark} {icon}{ch['name']} Nv.{s['nivel']} {s['classe']}"
                f"  PV[{_bar(s['vida_atual'], s['vida_max'])}]{s['vida_atual']}/{s['vida_max']}"
                f"{mana}  CA {s['ca']}{_warn(ch, s)}{_conds(ch)}"
            )
        order_str = " → ".join(f"[{n}]" if i == idx else n for i, n in enumerate(order))
        parts.append(
            f"COMBATE ATIVO — Rodada {round_n} | Vez de: {current}\n"
            + "\n".join(lines)
            + f"\n   Ordem: {order_str}"
        )
    else:
        # FORA DE COMBATE: status do grupo (membros com ficha).
        dnd_chars = [
            ch for key, ch in c["characters"].items()
            if ch.get("sheet") and (key in party_names or ch["name"] == c.get("protagonist", ""))
        ]
        if dnd_chars:
            status_lines = []
            for ch in dnd_chars:
                s = ch["sheet"]
                status_lines.append(
                    f"  {ch['name']} Nv.{s['nivel']} {s['classe']}{_warn(ch, s)}"
                    f"  PV[{_bar(s['vida_atual'], s['vida_max'])}]{s['vida_atual']}/{s['vida_max']}"
                    f"  Mana {s['mana_atual']}/{s['mana_max']}  CA {s['ca']}{_conds(ch)}"
                )
            parts.append("Status D&D:\n" + "\n".join(status_lines))

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
    # Onda 4 — missões como objetos (qualquer estilo de campanha)
    add_quest,
    update_quest_objective,
    complete_quest,
    list_quests,
    get_quest,
    # Onda 4 — atitude de NPC (idem)
    adjust_attitude,
    get_attitude,
    list_attitudes,
    # Contexto (dinâmico e completo)
    get_scene_context,
    get_full_context,
    # Ferramentas D&D (motor de regras)
    *DND_TOOLS,
]