"""
auth.py
Autenticação via Supabase Auth (email + senha) usando gotrue diretamente.
Expõe o decorator require_auth para proteger rotas do Flask.
"""

import os
from functools import wraps
from typing import Optional

from flask import request, g, jsonify
from gotrue import SyncClient as AuthClient


def _client() -> AuthClient:
    return AuthClient(
        url=f"{os.environ['SUPABASE_URL']}/auth/v1",
        headers={"apikey": os.environ["SUPABASE_ANON_KEY"]}
    )


# ---------------------------------------------------------------------------
# Operações de autenticação
# ---------------------------------------------------------------------------

def register(email: str, password: str) -> dict:
    """
    Registra um novo usuário via Supabase Auth.
    """
    sb = _client()
    # Correto: em gotrue o método é direto no client
    result = sb.sign_up(email=email, password=password)
    if not result.user:
        raise ValueError("Não foi possível criar a conta.")
    return {
        "user_id":       result.user.id,
        "email":         result.user.email,
        "access_token":  result.session.access_token  if result.session else None,
        "refresh_token": result.session.refresh_token if result.session else None,
    }


def login(email: str, password: str) -> dict:
    """
    Autentica um usuário existente.
    """
    sb = _client()
    # AJUSTADO: removido o '.auth' pois sb já é o cliente de autenticação
    result = sb.sign_in_with_password({"email": email, "password": password})
    if not result.user:
        raise ValueError("Email ou senha incorretos.")
    return {
        "user_id":       result.user.id,
        "email":         result.user.email,
        "access_token":  result.session.access_token,
        "refresh_token": result.session.refresh_token,
    }


def get_user_id(token: str) -> Optional[str]:
    """
    Valida o JWT e retorna o user_id correspondente.
    """
    try:
        sb = _client()
        # AJUSTADO: removido o '.auth'
        user = sb.get_user(token)
        return user.user.id if user.user else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Decorator de proteção de rota
# ---------------------------------------------------------------------------

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "").strip()

        if not token:
            return jsonify({"error": "Não autenticado. Faça login para continuar."}), 401

        user_id = get_user_id(token)
        if not user_id:
            return jsonify({"error": "Token inválido ou expirado. Faça login novamente."}), 401

        g.user_id = user_id
        g.token   = token
        return f(*args, **kwargs)

    return decorated