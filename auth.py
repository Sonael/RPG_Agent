import os
from functools import wraps
from typing import Optional

from flask import request, g, jsonify
# IMPORTAÇÃO DIRETA: Busca o cliente síncrono no submódulo específico
from gotrue import SyncGoTrueClient as AuthClient 

def _client() -> AuthClient:
    """Instancia o cliente de autenticação usando a URL do projeto."""
    return AuthClient(
        url=f"{os.environ['SUPABASE_URL']}/auth/v1",
        headers={"apikey": os.environ["SUPABASE_ANON_KEY"]}
    )

def register(email: str, password: str) -> dict:
    sb = _client()
    result = sb.sign_up({"email": email, "password": password})
    if not result.user:
        raise ValueError("Não foi possível criar a conta.")
    return {
        "user_id":       result.user.id,
        "email":         result.user.email,
        "access_token":  result.session.access_token  if result.session else None,
        "refresh_token": result.session.refresh_token if result.session else None,
    }

def login(email: str, password: str) -> dict:
    sb = _client()
    result = sb.sign_in_with_password({"email": email, "password": password})
    if not result.user:
        raise ValueError("Email ou senha incorretos.")
    return {
        "user_id":       result.user.id,
        "email":         result.user.email,
        "access_token":  result.session.access_token,
        "refresh_token": result.session.refresh_token,
    }

def refresh_session(refresh_token: str) -> dict:
    """
    Renova a sessão do usuário usando o refresh_token.
    """
    try:
        sb = _client()
        # O cliente GoTrue possui um método nativo para renovar a sessão
        result = sb.refresh_session(refresh_token)
        
        if not result or not result.session:
            raise ValueError("Não foi possível renovar a sessão.")
            
        return {
            "access_token":  result.session.access_token,
            "refresh_token": result.session.refresh_token,
        }
    except Exception as e:
        raise ValueError(f"Sessão expirada ou token inválido: {str(e)}")

def get_user_id(token: str) -> Optional[str]:
    try:
        sb = _client()
        user = sb.get_user(token)
        return user.user.id if user.user else None
    except Exception:
        return None

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # 1. Extração do Token
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Formato de autorização inválido. Use 'Bearer <token>'."}), 401

        token = auth_header.replace("Bearer ", "").strip()
        if not token:
            return jsonify({"error": "Token não fornecido."}), 401

        try:
            # 2. Busca o usuário no Supabase usando o token
            # Isso valida se o token é real e recupera os metadados
            sb = _client() 
            response = sb.get_user(token)

            if not response or not response.user:
                return jsonify({"error": "Token inválido ou sessão expirada."}), 401

            user = response.user

            # 3. TRAVA DE SEGURANÇA: Verificação de E-mail
            # O campo 'email_confirmed_at' fica nulo até o clique no link do e-mail
            if not user.email_confirmed_at:
                return jsonify({
                    "error": "E-mail pendente.",
                    "message": "Você precisa confirmar seu e-mail antes de criar sessões."
                }), 403  # Usamos 403 (Forbidden) porque ele está autenticado, mas não tem permissão

            # 4. Armazena os dados no contexto global 'g' para uso nas rotas
            g.user_id = user.id
            g.email   = user.email
            g.token   = token

            # 5. Vincula o contexto de memória À CAMPANHA DESTE USUÁRIO.
            # Centralizado aqui → todo endpoint autenticado opera no
            # estado do seu próprio usuário (isolamento multiusuário).
            import memory
            memory.bind_request(user.id)

        except Exception as e:
            # Log interno para debug; resposta genérica ao cliente (não
            # vaza stack/detalhes de implementação para um atacante).
            try:
                import logging
                logging.getLogger(__name__).warning(
                    "Falha na verificação de token: %s", e)
            except Exception:
                pass
            return jsonify({"error": "Sessão inválida ou expirada."}), 401

        return f(*args, **kwargs)
    return decorated