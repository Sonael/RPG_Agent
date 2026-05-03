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
        "name":                 "",    # nome da campanha (preenchido ao carregar)
        "campaign_type":        "fantasia",
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
    }


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