"""
database.py
Camada de acesso ao Supabase para persistência de campanhas.
Toda operação de banco passa por aqui — o resto do sistema não conhece Supabase.
"""

import os
import json
from typing import Optional
from supabase import create_client, Client


def _client() -> Client:
    """Cria e retorna um cliente Supabase usando as variáveis de ambiente."""
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]   # service key bypassa RLS — seguro no backend
    return create_client(url, key)


# ---------------------------------------------------------------------------
# Campanhas
# ---------------------------------------------------------------------------

def list_campaigns(user_id: str) -> list[dict]:
    """
    Lista todas as campanhas de um usuário com metadados resumidos.
    Retorna lista de dicts com: name, chapter, characters, events, diary, has_history.
    """
    sb = _client()
    result = (
        sb.table("campaigns")
        .select("name, data")
        .eq("user_id", user_id)
        .order("updated_at", desc=True)
        .execute()
    )
    rows = result.data or []
    out  = []
    for row in rows:
        d = row.get("data", {})
        out.append({
            "name":        row["name"],
            "chapter":     d.get("chapter", 1),
            "location":    d.get("current_location", ""),
            "characters":  len(d.get("characters", {})),
            "events":      len(d.get("events", [])),
            "diary":       len(d.get("diary", [])),
            "has_history": len(d.get("conversation_history", [])) > 0,
        })
    return out


def get_campaign(user_id: str, name: str) -> Optional[dict]:
    """
    Carrega os dados completos de uma campanha.
    Retorna o dict de dados ou None se não existir.
    """
    sb = _client()
    result = (
        sb.table("campaigns")
        .select("data")
        .eq("user_id", user_id)
        .eq("name", name)
        .limit(1)
        .execute()
    )
    if result.data:
        return result.data[0]["data"]
    return None


def save_campaign(user_id: str, name: str, data: dict) -> None:
    """
    Salva (insert ou update) os dados de uma campanha.
    Usa upsert com conflito em (user_id, name).
    """
    sb = _client()
    sb.table("campaigns").upsert(
        {"user_id": user_id, "name": name, "data": data},
        on_conflict="user_id,name",
    ).execute()


def delete_campaign(user_id: str, name: str) -> None:
    """Remove uma campanha do banco."""
    sb = _client()
    sb.table("campaigns").delete().eq("user_id", user_id).eq("name", name).execute()


def rename_campaign(user_id: str, old_name: str, new_name: str) -> None:
    """Renomeia uma campanha."""
    sb = _client()
    sb.table("campaigns").update({"name": new_name}).eq("user_id", user_id).eq("name", old_name).execute()


def campaign_exists(user_id: str, name: str) -> bool:
    """Verifica se uma campanha com esse nome já existe para o usuário."""
    sb = _client()
    result = (
        sb.table("campaigns")
        .select("name")
        .eq("user_id", user_id)
        .eq("name", name)
        .limit(1)
        .execute()
    )
    return bool(result.data)