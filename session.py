"""
session.py
Envio de mensagens ao agente, gestão do histórico e reancoragem.
"""

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

import memory
from validator import validate_and_log

APP_NAME   = "rpg_app"
USER_ID    = "jogador1"
SESSION_ID = "sessao1"

# Número máximo de falas reinjetadas ao retomar uma campanha.
# Cada par user+assistant = 1 turno. 40 entradas ≈ 20 turnos.
MAX_HISTORY_INJECT = 40


def create_runner(agent) -> tuple[Runner, InMemorySessionService]:
    """Cria e retorna (runner, session_service) para o agente."""
    session_service = InMemorySessionService()
    runner = Runner(agent=agent, app_name=APP_NAME, session_service=session_service)
    return runner, session_service


def build_recap() -> str:
    """
    Monta a mensagem de reancoragem com o contexto completo do mundo
    e o histórico recente de conversa.
    """
    from tools import get_full_context

    contexto = get_full_context()
    historico = memory.campaign["conversation_history"][-MAX_HISTORY_INJECT:]

    dialogo_lines = []
    for entrada in historico:
        role = "Jogador" if entrada["role"] == "user" else "Mestre"
        dialogo_lines.append(f"[{role}]: {entrada['text']}")
    dialogo = "\n".join(dialogo_lines)

    return (
        "Estamos retomando uma aventura em andamento. "
        "Abaixo está o estado completo do mundo e o histórico recente.\n\n"
        f"{contexto}\n\n"
        "--- HISTÓRICO RECENTE ---\n"
        f"{dialogo}\n\n"
        "Faça um breve recap ao jogador do ponto em que estávamos "
        "e aguarde a próxima ação dele para continuar a narrativa."
    )


async def enviar_mensagem(
    runner: Runner,
    texto: str,
    registrar: bool = True,
) -> str:
    """
    Envia uma mensagem ao agente, imprime a resposta e retorna o texto.
    Se registrar=True, salva user+assistant no histórico e persiste.
    """
    if registrar:
        memory.campaign["conversation_history"].append({"role": "user", "text": texto})

    mensagem = types.Content(
        role="user",
        parts=[types.Part(text=texto)],
    )

    resposta_texto = ""
    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=SESSION_ID,
        new_message=mensagem,
    ):
        if event.is_final_response() and event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    resposta_texto += part.text
                    print(f"\nMestre: {part.text}")

    if registrar and resposta_texto:
        validate_and_log(resposta_texto)
        memory.campaign["conversation_history"].append(
            {"role": "assistant", "text": resposta_texto}
        )
        memory.save_campaign()

    return resposta_texto


def prompt_abertura(campanha_nova: bool) -> str:
    """
    Para campanhas novas: pergunta ao jogador se quer fornecer a história
    ou deixar o agente criar uma aleatória. Retorna a mensagem de abertura
    a ser enviada ao agente.
    """
    if not campanha_nova:
        return build_recap()

    print("\nComo você quer começar a campanha?")
    print("  1  — Eu descrevo o cenário e a história inicial")
    print("  2  — O Mestre cria uma história aleatória para mim")
    print()

    while True:
        escolha = input("Escolha [1/2]: ").strip()
        if escolha == "1":
            print("\nDescreva o cenário, personagem, contexto — o quanto quiser:")
            descricao = input("> ").strip()
            if descricao:
                return (
                    f"O jogador quer começar uma campanha com o seguinte cenário:\n\n"
                    f"{descricao}\n\n"
                    "Use essa descrição como ponto de partida. Apresente o mundo, "
                    "introduza o personagem do jogador e inicie a narrativa."
                )
            else:
                return "O jogador quer começar uma campanha. Pergunte o tema ou cenário desejado."

        if escolha == "2":
            print("\nQual gênero você prefere? (deixe em branco para surpresa total)")
            print("Exemplos: fantasia medieval, cyberpunk, horror, space opera, western...")
            genero = input("> ").strip()
            if genero:
                return (
                    f"Crie uma campanha aleatória de {genero}. "
                    "Apresente o mundo, o personagem do jogador e a situação inicial "
                    "de forma imersiva, sem perguntar nada — comece narrando."
                )
            return (
                "Crie uma campanha completamente aleatória, surpreendente e original. "
                "Escolha o gênero, o cenário e o personagem do jogador. "
                "Comece narrando diretamente, sem perguntar nada."
            )

        print("Digite 1 ou 2.")