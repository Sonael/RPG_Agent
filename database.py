"""
database.py
Camada de acesso ao Supabase para persistência de campanhas.
Toda operação de banco passa por aqui — o resto do sistema não conhece Supabase.
"""

import os
import json
from typing import Optional
from postgrest import SyncPostgrestClient


def _client() -> SyncPostgrestClient:
    """Cria e retorna um cliente Postgrest direto."""
    url = f"{os.environ['SUPABASE_URL']}/rest/v1"
    headers = {
        "apikey": os.environ["SUPABASE_SERVICE_KEY"],
        "Authorization": f"Bearer {os.environ['SUPABASE_SERVICE_KEY']}"
    }
    return SyncPostgrestClient(url, headers=headers)


# ---------------------------------------------------------------------------
# Campanhas
# ---------------------------------------------------------------------------

def list_campaigns(user_id: str) -> list[dict]:
    """
    Lista todas as campanhas de um usuário com metadados resumidos.
    """
    sb = _client()
    # Correto: usa .from_()
    result = (
        sb.from_("campaigns") 
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
    """
    sb = _client()
    # Ajustado: .table() -> .from_()
    result = (
        sb.from_("campaigns")
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
    Salva (insert ou update) os dados de uma campanha via upsert.
    """
    sb = _client()
    # Ajustado: .table() -> .from_()
    sb.from_("campaigns").upsert(
        {"user_id": user_id, "name": name, "data": data},
        on_conflict="user_id,name",
    ).execute()


def delete_campaign(user_id: str, name: str) -> None:
    """Remove uma campanha do banco."""
    sb = _client()
    # Ajustado: .table() -> .from_()
    sb.from_("campaigns").delete().eq("user_id", user_id).eq("name", name).execute()


def rename_campaign(user_id: str, old_name: str, new_name: str) -> None:
    """Renomeia uma campanha."""
    sb = _client()
    # Ajustado: .table() -> .from_()
    sb.from_("campaigns").update({"name": new_name}).eq("user_id", user_id).eq("name", old_name).execute()


def campaign_exists(user_id: str, name: str) -> bool:
    """Verifica se uma campanha com esse nome já existe."""
    sb = _client()
    # Ajustado: .table() -> .from_()
    result = (
        sb.from_("campaigns")
        .select("name")
        .eq("user_id", user_id)
        .eq("name", name)
        .limit(1)
        .execute()
    )
    return bool(result.data)