"""
memory.py
Estado global da campanha e funções de persistência via Supabase.
"""

import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Estado global de sessão (definido pelo server.py ao iniciar uma sessão)
# ---------------------------------------------------------------------------

CURRENT_USER_ID: str = None   # type: ignore  — user_id do Supabase Auth
CAMPAIGN_NAME:   str = None   # type: ignore  — nome da campanha ativa

# Dict de trabalho em memória — todos os módulos (tools.py, etc.) operam aqui.
campaign: dict = {}


def _defaults() -> dict:
    return {
        "name":                 "",
        "campaign_type":        "fantasia",
        "dnd_mode":             False,   # True quando o estilo for "dnd"
        "protagonist":          "",      # Nome do personagem principal do jogador
        "characters":           {},
        "locations":            {},
        "events":               [],
        "conversation_history": [],
        "story_summary":        "",
        "current_scene":        "",
        "current_location":     "",
        "chapter":              1,
        "quest_flags":          {},
        "party":                [],
        "diary":                [],
        "combat_state": {
            "is_active":           False,
            "initiative_order":    [],
            "current_turn_index":  0,
            "round":               1,
            "turn_resolved":       False,  # True após attack_roll/use_ability; False ao chamar next_turn
            "npc_strategies":      {},
            "turn_auto_advanced":  False,
        },
    }


def _migrate_sheet_fields(char: dict) -> None:
    """
    Garante que fichas antigas (salvas antes da v2) tenham todos os campos
    novos com valores padrão. Chamado automaticamente após load_campaign.
    Nunca sobrescreve valores já existentes.
    """
    sheet = char.get("sheet")
    if sheet is None:
        return

    defaults_v2 = {
        "ouro":                 0,
        "prata":                0,
        "cobre":                0,
        "equipamentos":         {"armadura": None, "escudo": None, "arma_principal": None, "amuleto": None},
        "condicoes":            [],
        "death_saves_sucessos": 0,
        "death_saves_falhas":   0,
    }

    for key, default_val in defaults_v2.items():
        if key not in sheet:
            # Copiar para evitar objetos mutáveis compartilhados
            import copy
            sheet[key] = copy.deepcopy(default_val)


def _migrate_combat_state() -> None:
    """
    Garante que campanhas antigas tenham o campo combat_state com estrutura completa.
    """
    defaults = {
        "is_active":          False,
        "initiative_order":   [],
        "current_turn_index": 0,
        "round":              1,
        "turn_resolved":      False,
        "npc_strategies":     {},
        "turn_auto_advanced": False,
    }
    cs = campaign.setdefault("combat_state", {})
    for key, val in defaults.items():
        if key not in cs:
            cs[key] = val


_SPELL_PLACEHOLDER = "Magia inicial da classe. Use learn_spell() para enriquecer com dados do Open5e."

def _migrate_spell_descriptions() -> None:
    """
    Substitui descrições placeholder de magias iniciais pelos dados reais de
    DEFAULT_SPELLS_BY_CLASS. Roda automaticamente ao carregar a campanha,
    corrigindo personagens criados antes da correção do wizard.
    """
    try:
        from tools_dnd import DEFAULT_SPELLS_BY_CLASS
    except ImportError:
        return  # ferramentas não disponíveis ainda

    for char in campaign.get("characters", {}).values():
        sheet = char.get("sheet")
        if not sheet:
            continue
        classe = sheet.get("classe", "").lower()
        spell_pool = DEFAULT_SPELLS_BY_CLASS.get(classe, [])
        if not spell_pool:
            continue
        # Índice nome→dados para lookup rápido
        spell_map = {s["nome"].lower(): s for s in spell_pool}

        for hab in char.get("habilidades", []):
            if hab.get("descricao") != _SPELL_PLACEHOLDER:
                continue
            data = spell_map.get(hab.get("nome", "").lower())
            if data:
                hab["descricao"]  = data["descricao"]
                hab["custo_mana"] = data["custo_mana"]
                hab["dado"]       = data.get("dado", hab.get("dado", ""))


def char_key(name: str) -> str:
    """
    Normaliza o nome de um personagem para uso como chave no dict `characters`.
    Garante que 'Bandido Raso', 'bandido raso', 'Bandido_Raso' e '  Bandido Raso  '
    sejam sempre tratados como a mesma chave — eliminando duplicatas e KeyErrors.
    """
    return name.lower().strip().replace("_", " ")


def reset_campaign() -> None:
    """Reseta o estado para os valores padrão."""
    campaign.clear()
    campaign.update(_defaults())


def load_campaign() -> bool:
    """
    Carrega a campanha ativa do Supabase para o dict em memória.
    Usa CURRENT_USER_ID e CAMPAIGN_NAME definidos pelo server.py.
    Retorna True se a campanha contém dados (não é nova).
    """
    import database

    if not CURRENT_USER_ID or not CAMPAIGN_NAME:
        reset_campaign()
        return False

    try:
        data = database.get_campaign(CURRENT_USER_ID, CAMPAIGN_NAME)

        if data is None:
            # Campanha nova — ainda não existe no banco
            reset_campaign()
            campaign["name"] = CAMPAIGN_NAME
            return False

        defaults = _defaults()
        reset_campaign()

        for key, default_val in defaults.items():
            loaded = data.get(key, default_val)
            if isinstance(default_val, dict):
                campaign[key].update(loaded)
            elif isinstance(default_val, list):
                campaign[key].extend(loaded)
            else:
                campaign[key] = loaded

        # Garante que o nome está sempre preenchido
        campaign["name"] = CAMPAIGN_NAME

        chars = len(campaign["characters"])
        locs  = len(campaign["locations"])
        evts  = len(campaign["events"])
        diary = len(campaign["diary"])
        hist  = len(campaign["conversation_history"])

        # Migra fichas antigas para incluir campos da v2 (ouro, condições, etc.)
        for char in campaign["characters"].values():
            _migrate_sheet_fields(char)

        # Migra estrutura de estado de combate para campanhas antigas
        _migrate_combat_state()

        # Substitui descrições placeholder de magias pelos dados reais
        _migrate_spell_descriptions()

        print(
            f"Campanha carregada: {chars} personagens, {locs} locais, "
            f"{evts} eventos, {diary} entradas no diário, {hist} falas no histórico."
        )

        return hist > 0 or chars > 0 or locs > 0 or evts > 0

    except Exception as e:
        print(f"Aviso: erro ao carregar campanha ({e}). Iniciando do zero.")
        reset_campaign()
        campaign["name"] = CAMPAIGN_NAME or ""
        return False


MAX_HISTORY_SAVED = 200

def save_campaign() -> None:
    """
    Persiste o estado da campanha no Supabase com as travas de segurança originais.
    """
    import database

    # TRAVA 1: Só salva se tiver nome definido
    if not campaign or not campaign.get("name"):
        print("⚠️ [ALERTA] Tentativa de salvar abortada: Memória sem nome de campanha.")
        return

    # TRAVA 2: Protege contra sobrescrever dados existentes com memória vazia
    if CURRENT_USER_ID and CAMPAIGN_NAME:
        try:
            existing = database.get_campaign(CURRENT_USER_ID, CAMPAIGN_NAME)
            if existing:
                has_history = len(campaign.get("conversation_history", [])) > 0
                has_summary = len(campaign.get("story_summary", "")) > 0
                has_chars   = len(campaign.get("characters", {})) > 0
                if not has_history and not has_summary and not has_chars:
                    print(f"⚠️ [PROTEÇÃO] Bloqueado sobrescrever '{campaign['name']}' com dados vazios.")
                    return
        except Exception:
            pass  # Se não conseguir checar, deixa salvar

    # Limita o histórico
    hist = campaign.get("conversation_history", [])
    if len(hist) > MAX_HISTORY_SAVED:
        campaign["conversation_history"] = hist[-MAX_HISTORY_SAVED:]

    try:
        database.save_campaign(CURRENT_USER_ID, CAMPAIGN_NAME, dict(campaign))
        print(f"✅ Campanha '{campaign['name']}' persistida no Supabase.")
    except Exception as e:
        print(f"❌ Erro crítico ao salvar no Supabase: {e}")


def export_diary_md() -> str:
    """
    Exporta o diário como string Markdown.
    Retorna o conteúdo (não salva em disco — o server.py envia como download).
    """
    lines = [f"# Diário de Campanha — {campaign.get('name', 'Sem título')}\n"]
    if not campaign.get("diary"):
        lines.append("_Nenhuma entrada no diário ainda._")
    else:
        for entry in campaign["diary"]:
            lines.append(
                f"## Capítulo {entry.get('chapter', '?')} — {entry.get('title', 'Sem título')}"
            )
            lines.append(entry.get("content", ""))
            lines.append("")
    return "\n".join(lines)