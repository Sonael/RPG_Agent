"""
session.py
Configuração do runner do agente ADK.

Nota: o sistema roda exclusivamente via servidor web (server.py).
O fluxo de envio de mensagens, recap e abertura vive em server.py.
"""

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

APP_NAME = "rpg_app"
# Identidade ADK (user_id / session_id) agora é POR USUÁRIO/CAMPANHA,
# definida em server.py. Não há mais constantes globais fixas.


def create_runner(agent) -> tuple[Runner, InMemorySessionService]:
    """Cria e retorna (runner, session_service) para o agente."""
    session_service = InMemorySessionService()
    runner = Runner(agent=agent, app_name=APP_NAME, session_service=session_service)
    return runner, session_service
