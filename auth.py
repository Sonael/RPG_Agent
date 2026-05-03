"""
auth.py
Autenticação via Supabase Auth (email + senha).
Expõe o decorator require_auth para proteger rotas do Flask.
"""

import os
from functools import wraps
from typing import Optional

from supabase import create_client, Client
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
    Retorna dict com 'user' e 'session' em caso de sucesso,
    ou lança exceção em caso de erro.
    """
    sb = _client()
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
    Retorna dict com tokens de acesso.
    """
    sb = _client()
    result = sb.auth.sign_in_with_password({"email": email, "password": password})
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
    Retorna None se o token for inválido ou expirado.
    """
    try:
        sb = _client()
        user = sb.auth.get_user(token)
        return user.user.id if user.user else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Decorator de proteção de rota
# ---------------------------------------------------------------------------

def require_auth(f):
    """
    Decorator Flask que extrai e valida o JWT do header Authorization.
    Em caso de sucesso, injeta g.user_id e g.token na requisição.
    """
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