"""
main.py
Ponto de entrada do agente de RPG.
"""

import asyncio

import memory
import tools
from agent import create_agent
from menus import selecionar_campanha, selecionar_modelo
from session import (
    APP_NAME, USER_ID, SESSION_ID,
    create_runner, enviar_mensagem, prompt_abertura,
)

SEP = "=" * 60

AJUDA = """
Comandos disponíveis:
  /personagens   — lista personagens na memória
  /grupo         — lista membros do grupo
  /locais        — lista locais na memória
  /eventos       — últimos 5 eventos
  /flags         — variáveis de estado da campanha
  /contexto      — dump completo da memória
  /diario        — exibe o diário de campanha
  /resumo        — pede ao Mestre um recap da história atual
  /exportar      — exporta o diário como arquivo .md
  /ajuda         — exibe este menu
  sair           — encerra a sessão e salva
"""


async def main() -> None:
    # 1. Selecionar campanha
    selecionar_campanha()
    campanha_existente = memory.load_campaign()

    # 2. Selecionar modelo
    print()
    model, model_label = selecionar_modelo()

    # 3. Criar agente e runner
    agent   = create_agent(model)
    runner, session_service = create_runner(agent)

    await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=SESSION_ID,
    )

    # 4. Cabeçalho
    print()
    print(SEP)
    print(f"  Campanha : {memory.SAVE_FILE.stem}")
    print(f"  Modelo   : {model_label}")
    print(SEP)
    print(AJUDA)

    # 5. Mensagem de abertura
    abertura = prompt_abertura(campanha_nova=not campanha_existente)
    await enviar_mensagem(runner, abertura, registrar=False)

    # 6. Loop principal
    while True:
        texto = input("\nVocê: ").strip()

        if not texto:
            continue

        # --- Encerrar ---
        if texto.lower() == "sair":
            memory.save_campaign()
            print("Sessão encerrada. Memória salva.")
            break

        # --- Comandos locais (não passam pelo agente) ---
        if texto.lower() == "/ajuda":
            print(AJUDA)
            continue

        if texto.lower() == "/personagens":
            print(tools.list_characters())
            continue

        if texto.lower() == "/grupo":
            print(tools.list_party())
            continue

        if texto.lower() == "/locais":
            print(tools.list_locations())
            continue

        if texto.lower() == "/eventos":
            print(tools.get_recent_events())
            continue

        if texto.lower() == "/flags":
            print(tools.list_flags())
            continue

        if texto.lower() == "/contexto":
            print(tools.get_full_context())
            continue

        if texto.lower() == "/diario":
            print(tools.get_diary(last=10))
            continue

        if texto.lower() == "/exportar":
            caminho = memory.export_diary_md()
            print(f"Diário exportado: {caminho}")
            continue

        # --- /resumo: pede recap ao agente ---
        if texto.lower() == "/resumo":
            await enviar_mensagem(
                runner,
                "Faça um resumo de tudo o que aconteceu na campanha até agora, "
                "consultando get_full_context antes de responder.",
                registrar=False,
            )
            continue

        # --- Mensagem normal ---
        await enviar_mensagem(runner, texto)


if __name__ == "__main__":
    asyncio.run(main())