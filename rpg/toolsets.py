"""
toolsets.py
Conjunto de ferramentas entregue ao agente — resolvido A CADA TURNO.

POR QUE EXISTE
──────────────
As 61 ferramentas custam ~11.100 tokens de schema em TODA requisição. Como
cada chamada de ferramenta é um novo round-trip, um turno de combate com três
chamadas manda ~33 mil tokens só de definição.

Mas o motivo principal deste arquivo não é custo, é CORREÇÃO.

No modo de combate "tela", a luta é resolvida pela interface tática via
combat_action(), e a instrução do sistema PROÍBE a LLM de chamar attack_roll,
use_ability, next_turn, execute_npc_turn e roll_death_save. Proibir por
prompt é uma esperança; retirar a ferramenta do conjunto é uma garantia — o
mesmo princípio já aplicado ao snapshot de cena ("tirou a decisão do LLM →
virou garantia de código"). Sem isso, uma LLM que resolvesse chamar
attack_roll no meio de um combate da tela produziria turno duplicado: o
motor avançaria por fora da economia que a tela controla.

COMO O ADK CHAMA ISTO
─────────────────────
`Agent(tools=...)` aceita um BaseToolset, e o ADK invoca `get_tools()` a cada
invocação (com cache por invocation_id). Ou seja: o conjunto é reavaliado por
turno, sem recriar o Agent nem o Runner — e portanto sem perder o histórico
da conversa, que vive no session_service do Runner.

CACHE DE PROMPT
───────────────
Os schemas ficam no INÍCIO da requisição, o bloco mais cacheável que existe.
Por isso o filtro é por MODO (muda poucas vezes por sessão) e não por turno:
dentro de uma mesma fase o conjunto é idêntico e o prefixo continua válido.
Filtrar com sinais de granularidade fina destruiria o cache e sairia mais
caro do que não filtrar.
"""

import os

from google.adk.tools.base_toolset import BaseToolset
from google.adk.tools.function_tool import FunctionTool

# Mesma flag do resto do projeto (RPG_DEBUG=1 mostra o que o agente recebe).
_DEBUG = os.environ.get("RPG_DEBUG", "0").strip().lower() in ("1", "true", "yes", "on")


# Ferramentas que a LLM não deve tocar quando o combate é resolvido na tela
# tática. A tela chama o mesmo motor por dentro, via combat_action().
FERRAMENTAS_SO_DO_MODO_NARRADO = frozenset({
    "attack_roll",
    "use_ability",
    "next_turn",
    "execute_npc_turn",
    "roll_death_save",
    "resolve_saving_throw",
})

# Deliberadamente NÃO removidas no modo tela:
#   • roll_initiative — a LLM ainda abre o combate com ela; é o gatilho que
#     faz a tela assumir.
#   • end_combat      — barata (204 chars) e serve de escape se a tela não
#     concluir a luta por algum motivo.
#   • spawn_monster / set_npc_strategy — usadas ANTES da luta começar.
#   • modify_hp / apply_condition — dano e condições fora de combate
#     continuam sendo responsabilidade da narração.


class FerramentasDoTurno(BaseToolset):
    """
    Entrega as ferramentas que fazem sentido no momento atual da campanha.

    Os FunctionTool são construídos UMA vez e reusados: schema idêntico entre
    turnos é o que mantém o prefixo da requisição cacheável.
    """

    def __init__(self, funcoes):
        super().__init__()
        self._todas = [FunctionTool(f) for f in funcoes]
        self._por_nome = {t.name: t for t in self._todas}

    async def get_tools(self, readonly_context=None):
        # Import tardio: `memory` é um proxy resolvido por ContextVar, e no
        # momento desta chamada já estamos dentro da task do agente, com a
        # campanha do usuário certo vinculada.
        from rpg import memory

        try:
            modo = (memory.campaign.get("combat_mode") or "narrado")
        except Exception:
            # Falha de forma segura: sem contexto de campanha, entrega tudo.
            return list(self._todas)

        if modo != "tela":
            self._log(modo, self._todas)
            return list(self._todas)

        entregues = [t for t in self._todas
                     if t.name not in FERRAMENTAS_SO_DO_MODO_NARRADO]
        self._log(modo, entregues)
        return entregues

    _ultimo_log = None

    def _log(self, modo: str, entregues: list) -> None:
        """Mostra o conjunto no terminal quando ele MUDA (não a cada turno)."""
        if not _DEBUG:
            return
        chave = (modo, len(entregues))
        if chave == FerramentasDoTurno._ultimo_log:
            return
        FerramentasDoTurno._ultimo_log = chave
        removidas = len(self._todas) - len(entregues)
        extra = f" (−{removidas} retiradas do modo narrado)" if removidas else ""
        print(f"  🧰 [FERRAMENTAS] modo={modo} → {len(entregues)}/"
              f"{len(self._todas)} entregues ao agente{extra}", flush=True)

    async def close(self) -> None:
        """Nada a liberar — as ferramentas são funções locais."""
        return None

    # ── Observabilidade ────────────────────────────────────────────────────

    def resumo(self, modo: str) -> str:
        """Quantas ferramentas cada modo entrega (usado no log de depuração)."""
        if modo == "tela":
            n = len(self._todas) - len(
                [t for t in self._todas if t.name in FERRAMENTAS_SO_DO_MODO_NARRADO])
            return f"{n}/{len(self._todas)} (modo tela)"
        return f"{len(self._todas)}/{len(self._todas)} (modo narrado)"
