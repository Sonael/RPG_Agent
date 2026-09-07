"""
database.py
Camada de acesso ao Supabase para persistência de campanhas.
Toda operação de banco passa por aqui — o resto do sistema não conhece Supabase.

SEGURANÇA — escopo de usuário estrutural:
  O backend usa a SERVICE KEY (service role), que ignora Row-Level Security.
  Portanto o isolamento entre usuários depende de TODA query ser filtrada por
  `user_id`. Para tornar isso impossível de esquecer, NENHUMA função acessa a
  tabela `campaigns` diretamente: todo acesso passa pelos helpers
  `_scoped_select` / `_scoped_delete` / `_scoped_update` / `_scoped_upsert`,
  que (1) exigem um `user_id` válido — levantam erro se vier vazio — e
  (2) já embutem o filtro `.eq("user_id", user_id)`. A RLS habilitada no
  Supabase é a camada extra de defesa em profundidade.
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
# Guard de escopo de usuário — único caminho de acesso à tabela `campaigns`
# ---------------------------------------------------------------------------

_TABLE = "campaigns"


def _require_uid(user_id: str) -> str:
    """
    Valida o user_id. Levanta PermissionError se vier vazio/None/tipo
    errado — torna estruturalmente impossível rodar uma query sem escopo
    de usuário (que vazaria ou apagaria dados de terceiros).
    """
    if not isinstance(user_id, str) or not user_id.strip():
        raise PermissionError(
            "Operação no banco sem user_id válido — bloqueada por segurança."
        )
    return user_id


def _scoped_select(user_id: str, columns: str):
    """SELECT na tabela campaigns JÁ filtrado por user_id."""
    _require_uid(user_id)
    return _client().from_(_TABLE).select(columns).eq("user_id", user_id)


def _scoped_delete(user_id: str):
    """DELETE na tabela campaigns JÁ filtrado por user_id."""
    _require_uid(user_id)
    return _client().from_(_TABLE).delete().eq("user_id", user_id)


def _scoped_update(user_id: str, patch: dict):
    """UPDATE na tabela campaigns JÁ filtrado por user_id."""
    _require_uid(user_id)
    return _client().from_(_TABLE).update(patch).eq("user_id", user_id)


def _scoped_upsert(user_id: str, name: str, data: dict):
    """UPSERT garantindo user_id no payload e na chave de conflito."""
    _require_uid(user_id)
    return _client().from_(_TABLE).upsert(
        {"user_id": user_id, "name": name, "data": data},
        on_conflict="user_id,name",
    )


# ---------------------------------------------------------------------------
# Campanhas
# ---------------------------------------------------------------------------

def list_campaigns(user_id: str) -> list[dict]:
    """
    Lista todas as campanhas de um usuário com metadados resumidos.
    """
    result = (
        _scoped_select(user_id, "name, data")
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
    result = (
        _scoped_select(user_id, "data")
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
    _scoped_upsert(user_id, name, data).execute()


def delete_campaign(user_id: str, name: str) -> None:
    """Remove uma campanha do banco."""
    _scoped_delete(user_id).eq("name", name).execute()


def rename_campaign(user_id: str, old_name: str, new_name: str) -> None:
    """Renomeia uma campanha."""
    _scoped_update(user_id, {"name": new_name}).eq("name", old_name).execute()


def campaign_exists(user_id: str, name: str) -> bool:
    """Verifica se uma campanha com esse nome já existe."""
    result = (
        _scoped_select(user_id, "name")
        .eq("name", name)
        .limit(1)
        .execute()
    )
    return bool(result.data)
