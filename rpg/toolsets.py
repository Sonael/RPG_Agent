"""
toolsets.py
Conjunto de ferramentas entregue ao agente — resolvido A CADA TURNO.

POR QUE EXISTE
──────────────
As 61 ferramentas custam ~11.100 tokens de schema em TODA requisição. Como
cada chamada de ferramenta é um novo round-trip, um turno de combate com três
chamadas manda ~33 mil tokens só de definição.

São dois filtros, com motivações diferentes.

1. MODO DE COMBATE "TELA" — motivo é CORREÇÃO, não custo.
   A luta é resolvida pela interface tática via combat_action(), e a
   instrução do sistema PROÍBE a LLM de chamar attack_roll, use_ability,
   next_turn, execute_npc_turn e roll_death_save. Proibir por prompt é uma
   esperança; retirar a ferramenta do conjunto é uma garantia — o mesmo
   princípio já aplicado ao snapshot de cena ("tirou a decisão do LLM →
   virou garantia de código"). Sem isso, uma LLM que resolvesse chamar
   attack_roll no meio de um combate da tela produziria turno duplicado: o
   motor avançaria por fora da economia que a tela controla.

2. CAMPANHA NÃO-D&D — motivo é custo, e é o maior dos dois.
   Fantasia, romance, horror, mistério, scifi e faroeste não têm regras: a
   contagem de menções a attack_roll, create_character_sheet,
   roll_initiative e afins nas instruções desses seis estilos é ZERO, e
   quase toda ferramenta do motor exige char["sheet"], que nem existe ali.
   Eram 39 ferramentas de peso morto — 80% do schema.

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


# Ferramentas do motor D&D que uma campanha de outro estilo nunca usa.
# As instruções de fantasia, romance, horror, mistério, scifi e faroeste têm
# ZERO menções a attack_roll, create_character_sheet, roll_initiative e afins
# — e quase todas essas ferramentas exigem char["sheet"], que só existe no
# modo D&D. Numa campanha de romance elas são 39 ferramentas de peso morto.
#
# Exceção deliberada: roll_dice fica em TODA campanha. É o único primitivo de
# aleatoriedade do sistema, não depende de ficha nenhuma e é genérico de
# gênero — um mistério ou um faroeste podem querer um dado sem ter regras.
_CARVE_OUT_GENERICAS = frozenset({"roll_dice"})


def _nomes_das_ferramentas_dnd() -> frozenset:
    from rpg.tools_dnd import DND_TOOLS
    return frozenset(f.__name__ for f in DND_TOOLS) - _CARVE_OUT_GENERICAS


FERRAMENTAS_SO_DO_MODO_DND = _nomes_das_ferramentas_dnd()


def _campanha_usa_dnd(camp) -> bool:
    """
    A campanha roda o motor de D&D?

    Além da flag, checa se ALGUM personagem tem ficha. É a salvaguarda que
    importa: uma campanha importada de JSON sem `dnd_mode`, mas com fichas
    salvas, continua precisando das ferramentas — e perder o motor no meio de
    uma campanha em andamento seria bem pior que carregar schema a mais.
    """
    if camp.get("dnd_mode"):
        return True
    if (camp.get("campaign_type") or "") == "dnd":
        return True
    for personagem in (camp.get("characters") or {}).values():
        if isinstance(personagem, dict) and personagem.get("sheet"):
            return True
    return False

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
            camp = memory.campaign
            modo = (camp.get("combat_mode") or "narrado")
            usa_dnd = _campanha_usa_dnd(camp)
        except Exception:
            # Falha de forma segura: sem contexto de campanha, entrega tudo.
            return list(self._todas)

        # Os dois filtros se compõem: uma campanha D&D no modo tela perde só
        # as ferramentas de turno; uma campanha de romance perde o motor D&D
        # inteiro (e nunca chega a estar no modo tela).
        excluir = set()
        if modo == "tela":
            excluir |= FERRAMENTAS_SO_DO_MODO_NARRADO
        if not usa_dnd:
            excluir |= FERRAMENTAS_SO_DO_MODO_DND

        if not excluir:
            self._log(modo, usa_dnd, self._todas)
            return list(self._todas)

        entregues = [t for t in self._todas if t.name not in excluir]
        self._log(modo, usa_dnd, entregues)
        return entregues

    _ultimo_log = None

    def _log(self, modo: str, usa_dnd: bool, entregues: list) -> None:
        """Mostra o conjunto no terminal quando ele MUDA (não a cada turno)."""
        if not _DEBUG:
            return
        chave = (modo, usa_dnd, len(entregues))
        if chave == FerramentasDoTurno._ultimo_log:
            return
        FerramentasDoTurno._ultimo_log = chave
        removidas = len(self._todas) - len(entregues)
        motivos = []
        if not usa_dnd:
            motivos.append("campanha não-D&D")
        if modo == "tela":
            motivos.append("combate na tela")
        extra = f" (−{removidas}: {', '.join(motivos)})" if removidas else ""
        print(f"  🧰 [FERRAMENTAS] modo={modo} dnd={usa_dnd} → "
              f"{len(entregues)}/{len(self._todas)} entregues{extra}", flush=True)

    async def close(self) -> None:
        """Nada a liberar — as ferramentas são funções locais."""
        return None
