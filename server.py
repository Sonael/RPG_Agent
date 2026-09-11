"""
server.py
Backend Flask do RPG Agent.
Execute com: python server.py
Acesse em:  http://localhost:5000
"""

import asyncio
import collections
import json
import queue
import re
import threading
import time
import os

from flask import Flask, Response, g, jsonify, request, send_from_directory, stream_with_context
from google.genai import types as gtypes

# O pacote da aplicação se chama `rpg` — e não `app` — justamente para não
# disputar o nome com `app = Flask(...)` mais abaixo, que precisa ser `app`
# porque o Render sobe com `gunicorn server:app`. Neste arquivo, `app` é
# sempre o Flask; o código da aplicação vem sempre de `rpg.*`.
from rpg import memory
from rpg import database
from rpg.auth import require_auth, register as auth_register, login as auth_login, refresh_session
from rpg.agent import create_agent, get_campaign_config
from rpg.session import APP_NAME, create_runner
from rpg.validator import validate


# ---------------------------------------------------------------------------
# Debug do loop do agente (para demonstração ao vivo)
# Imprime no terminal cada passo do ciclo ReAct do agente: percepção,
# chamada de ferramenta (ação), resultado observado e resposta final.
# DESLIGADO por padrão. Para ver o debug ao vivo, rode com RPG_DEBUG=1
# (ex.: RPG_DEBUG=1 python server.py). Aceita: 1/true/yes/on.
# ---------------------------------------------------------------------------

DEBUG_AGENT = os.environ.get("RPG_DEBUG", "0").strip().lower() in ("1", "true", "yes", "on")


def _dbg(msg: str = "") -> None:
    """Imprime uma linha de debug do agente se RPG_DEBUG estiver ligado."""
    if DEBUG_AGENT:
        print(msg, flush=True)


def _short(value, limit: int = 220) -> str:
    """Encolhe um valor para caber numa linha de log sem poluir o terminal."""
    text = str(value).replace("\n", " ⏎ ").strip()
    return text if len(text) <= limit else text[:limit] + " …"


def _dbg_block(value, title: str = "") -> None:
    """Imprime um texto multi-linha emoldurado (para inspecionar o que é
    injetado no agente: contexto do mundo, recap, percepção da cena)."""
    if not DEBUG_AGENT:
        return
    if title:
        print(f"  ┌─ {title} " + "─" * max(0, 64 - len(title)), flush=True)
    else:
        print("  ┌" + "─" * 66, flush=True)
    for line in str(value).splitlines() or [""]:
        print("  │ " + line, flush=True)
    print("  └" + "─" * 66, flush=True)


# Ferramentas de PERCEPÇÃO: o que informa o agente sobre personagens, local,
# eventos e flags. No log mostramos o resultado COMPLETO (não truncado), pois
# é exatamente "como o agente sabe o que está acontecendo".
_CONTEXT_TOOLS = {"get_scene_context", "get_full_context"}


# ---------------------------------------------------------------------------
# Loop de verificação pós-resposta (D&D mode)
# Detecta quando o agente narrou ações mecânicas sem chamar as ferramentas.
# ---------------------------------------------------------------------------

# Ferramentas que resolvem cada categoria mecânica
# use_ability está em _HP_TOOLS e _ATCK_TOOLS porque habilidades de dano (ex: Punho Sagrado)
# modificam HP sem passar por attack_roll. Isso cria um falso negativo teórico: se
# use_ability for chamada para habilidade não-danosa E o agente narrar mudança de HP,
# a violação não é detectada. Aceito como trade-off — o cenário é muito improvável e
# a alternativa (remover use_ability) causa dano duplo, que é pior.
_HP_TOOLS    = {"modify_hp", "attack_roll", "use_ability"}
_MANA_TOOLS  = {"use_ability", "modify_mana"}
_INIT_TOOLS  = {"roll_initiative"}
_ATCK_TOOLS  = {"attack_roll", "use_ability"}
_LEARN_TOOLS = {"learn_spell", "learn_ability"}  # Ferramentas que ensinam magias/habilidades
_CONDITION_TOOLS = {"apply_condition"}
_XP_TOOLS        = {"grant_xp"}
_CONDITION_APPLIED_RE = re.compile(
    r'\b(?:'
    # Apenas verbos de mudança de estado (nova aplicação).
    # "está"/"fica" são omitidos: descrevem estado já existente e causam falso positivo.
    # "caído" é omitido: usado para descrever inconscientes, não a condição Prone.
    r'(?:ficou|foi|torna.?se|tornou.?se|recebeu|sofreu)\s+'
    r'(?:a\s+condição\s+(?:de\s+)?)?'
    r'(?:cego|enfeitiçado|paralisado|envenenado|atordoado|amedrontado|'
    r'petrificado|invisív[ei]l|incapacitado|surdo|exausto|agarrado)'
    r')',
    re.IGNORECASE,
)

# Padrões que indicam que o agente narrou mecânicas sem ferramentas
_COMBAT_START_RE = re.compile(
    r'\b(rodada\s+1|iniciativa\s+(?:foi\s+)?rolada?|o\s+combate\s+come[çc]a|'
    r'ordem\s+de\s+combate|combate\s+iniciado)\b',
    re.IGNORECASE,
)
_HP_CHANGE_RE = re.compile(
    # Seta com contexto HP explícito: "vida: 15 → 9", "HP 12 → 7"
    r'(?:(?:vida|hp|pv)\b.{0,20}\d+\s*[→➜▶]\s*-?\d+)'
    # Seta com max HP: "15 → 9/12" — formato das ferramentas copiado na narrativa
    r'|(?:\d+\s*[→➜▶]\s*-?\d+\s*/\s*\d+)'
    # Forma narrativa explícita: "perdeu 6 PV", "tomou 4 pontos de vida"
    r'|(?:(?:perdeu|sofreu|tomou|curou)\s+\d+\s*(?:pontos?\s+de\s+vida|pv\b))',
    re.IGNORECASE,
)
_ATTACK_RESULT_RE = re.compile(
    r'(?:✅\s*acerto|❌\s*errou?'
    r'|o\s+(?:ataque|golpe|disparo|virote|flecha)\s+(?:acerta|erra|conecta|atinge|perfura)'
    r'|\bacertou?\b|\berrou?\b\s+o\s+ataque)',
    re.IGNORECASE,
)
_MANA_CHANGE_RE = re.compile(
    r'mana[:\s]+\d+\s*[→➜]\s*\d+',
    re.IGNORECASE,
)
# Detecta quando o agente narra que um personagem aprendeu uma magia/habilidade
# sem ter chamado learn_spell() ou learn_ability()
_SPELL_LEARNED_RE = re.compile(
    r'\b(?:'
    r'aprendeu?\s+(?:a\s+magia|o\s+feitiço|a\s+habilidade|o\s+poder)\b'
    r'|(?:a\s+magia|o\s+feitiço|a\s+habilidade)\s+.{2,40}\s+(?:foi\s+)?aprendid[ao]'
    r'|agora\s+(?:conhece|sabe\s+usar|domina)\s+a\s+magia'
    r'|adicionad[ao]\s+(?:à|ao|as)\s+(?:sua\s+)?(?:lista\s+de\s+)?(?:magias|habilidades|feitiços)'
    r')',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Trava de coerência de verdade: personagem MORTO não pode agir como vivo.
# Vale para QUALQUER estilo de campanha (não só D&D).
# ---------------------------------------------------------------------------

# Verbos de ação/fala que indicam um personagem agindo como ser vivo.
_LIVING_VERBS = (
    "diz|disse|fala|falou|responde|respondeu|pergunta|perguntou|grita|gritou|"
    "sussurra|sussurrou|murmura|murmurou|exclama|exclamou|ri|riu|sorri|sorriu|"
    "ataca|atacou|golpeia|golpeou|avança|avançou|corre|correu|caminha|caminhou|"
    "anda|andou|ergue|ergueu|levanta|levantou|senta|sentou|pega|pegou|puxa|puxou|"
    "saca|sacou|empunha|empunhou|olha|olhou|encara|encarou|vira|virou|acena|acenou|"
    "aproxima|aproximou|afasta|afastou|aponta|apontou|salta|saltou|lança|lançou|"
    "respira|respirou|pisca|piscou|assente|assentiu|balança|balançou|"
    "investe|investiu|recua|recuou|esquiva|esquivou|defende|defendeu"
)

# Indícios de exceção legítima (a narração deixa claro que é sobrenatural/onírico).
# Nesses casos um personagem morto PODE aparecer — não é incoerência.
_UNDEAD_CONTEXT_RE = re.compile(
    r"\b(flashback|sonh[oa]|pesadelo|lembran[çc]a[s]?|mem[óo]ria[s]?|vis[ãa]o|"
    r"fantasma|esp[íi]rito|esp[ée]ctro|alma|apari[çc][ãa]o|al[ée]m-?t[úu]mulo|"
    r"reviv\w*|ressuscit\w*|necroman\w*|morto-?vivo|zumbi|esqueleto)\b",
    re.IGNORECASE,
)


def _check_dead_characters_alive(text: str, dead_before: set) -> list[str]:
    """
    Detecta quando a narração faz um personagem MORTO agir/falar como vivo.

    Só considera personagens que JÁ estavam mortos ANTES deste turno
    (dead_before) — assim o turno em que o inimigo morre, descrevendo sua
    última ação, não gera falso-positivo. Ignora menções neutras ('o corpo
    de X jazia ali') e exceções legítimas (flashback, sonho, fantasma...)
    sinalizadas no próprio texto.
    """
    if not text or not dead_before:
        return []
    if _UNDEAD_CONTEXT_RE.search(text):
        return []

    chars = memory.campaign.get("characters", {})
    violations = []
    for ch in chars.values():
        name = (ch.get("name") or "").strip()
        if not name:
            continue
        if name.lower().strip() not in dead_before:
            continue
        if (ch.get("status") or "").lower() != "morto":
            continue  # ressuscitou legitimamente durante o turno
        # Nome seguido (até 2 palavras depois) de um verbo de ação/fala.
        pat = re.compile(
            r"\b" + re.escape(name) + r"\b(?:\s+\w+){0,2}\s+(?:" + _LIVING_VERBS + r")\b",
            re.IGNORECASE,
        )
        if pat.search(text):
            violations.append(
                f"Coerência quebrada: '{name}' está MORTO na memória, mas a "
                f"narração o faz agir ou falar como vivo. Personagens mortos não "
                f"agem nem falam (exceto em flashback, sonho ou como fantasma — e "
                f"nesse caso deixe explícito no texto). Reescreva sem ressuscitar "
                f"'{name}'; trate-o como corpo/lembrança, ou — se ele realmente "
                f"voltou — registre com update_character_status antes de narrar."
            )
    return violations


# Sufixo de mob numerado: spawn_monster cria "Goblin 1", "Goblin 2"… e a
# narração fala "três goblins". Compara-se pela raiz do nome.
_NUMERO_FINAL_RE = re.compile(r"\s+\d+$")


def _mencionado(nome: str, texto: str) -> bool:
    """
    O nome (ou sua raiz, ou o plural dela) aparece no texto?
    Sem acentos e sem caixa, com fronteira de palavra e plural opcional —
    'Bandido' casa com 'bandidos', 'Acólito' com 'acolitos'.
    """
    def _sem_acento(t: str) -> str:
        return t.lower().translate(str.maketrans(
            "áàãâäéèêëíìîïóòõôöúùûüçñ", "aaaaaeeeeiiiiooooouuuucn"))

    alvo = _sem_acento(texto)
    raiz = _NUMERO_FINAL_RE.sub("", nome).strip()
    for termo in {nome.strip(), raiz}:
        if not termo:
            continue
        # Casa a expressão inteira e aceita plural na última palavra.
        pat = r"\b" + r"\s+".join(re.escape(p) for p in _sem_acento(termo).split()) \
              + r"(?:e?s)?\b"
        if re.search(pat, alvo):
            return True
    return False


def _check_combatants_offscene(text: str) -> list[str]:
    """
    Combatentes fora do grupo cujo nome não aparece na narração do encontro.

    Só olha quem NÃO é do grupo: o grupo está presente por definição, e a
    narração costuma tratá-lo por "vocês" em vez de nomear cada um.
    """
    cs = memory.campaign.get("combat_state", {}) or {}
    if not cs.get("is_active"):
        return []

    chars = memory.campaign.get("characters", {})
    fora  = []
    for nome in cs.get("initiative_order", []) or []:
        ch = chars.get(memory.char_key(nome))
        if ch and memory.is_party_member(ch):
            continue
        if not _mencionado(nome, text):
            fora.append(nome)

    if not fora:
        return []
    return [
        "Rolou iniciativa para " + ", ".join(f"'{n}'" for n in fora)
        + ", mas a narração não põe " + ("esse NPC" if len(fora) == 1 else "esses NPCs")
        + " na cena. Só entra em combate quem você narrou como presente — "
        "a lista de personagens conhecidos NÃO é o elenco da cena. "
        "Reescreva: ou descreva a chegada " + ("dele" if len(fora) == 1 else "deles")
        + " no encontro, ou refaça roll_initiative() apenas com quem está ali."
    ]


# buy_item entra porque ele chama add_item por dentro: sem isso, comprar
# numa loja era desvio da conferência — a marca ia para a ficha e
# ninguém olhava naquele turno.
_ITEM_TOOLS = {"add_item", "buy_item"}


def _check_itens_inventados(tools_called: set) -> list[str]:
    """
    Item que NÃO existe no SRD e ainda por cima promete efeito mecânico.

    Um item de sabor inventado é bom: é assim que uma campanha ganha cara
    própria. O problema é o inventado que mexe na CONTA — "+3 em tudo", "cura
    5d8 por dia" — porque desequilibra a mesa sem ninguém perceber, e o
    jogador só descobre quando o combate já não oferece risco.

    A marca vem do add_item, que a grava na ficha. Aqui ela vira cobrança:
    ou o mestre troca por um item real do SRD, ou declara por que o dele é
    equilibrado.
    """
    if not _ITEM_TOOLS.intersection(tools_called):
        return []

    achados, sem_descricao = [], []
    for ch in memory.campaign.get("characters", {}).values():
        for it in (ch.get("inventario") or []):
            if not isinstance(it, dict) or not it.get("custom"):
                continue
            if it.get("balanco_justificado"):
                continue
            if it.get("efeito_mecanico"):
                achados.append((ch.get("name", "?"), it))
            elif it.get("efeito_desconhecido"):
                sem_descricao.append((ch.get("name", "?"), it))

    if not achados and not sem_descricao:
        return []

    nivel = max((int(((c.get("sheet") or {}).get("nivel", 1)) or 1)
                 for c in memory.campaign.get("characters", {}).values()
                 if memory.is_party_member(c)), default=1)

    violacoes = []
    if sem_descricao:
        soltos = ", ".join(f"'{it.get('nome')}' ({dono})"
                           for dono, it in sem_descricao[:4])
        violacoes.append(
            f"Deu item de nome mágico que não existe no SRD e não disse o que "
            f"ele FAZ: {soltos}. Sem descrição não dá para saber se é "
            f"lembrança de família ou espada +3, e é assim que um item entra "
            f"na campanha sem ninguém pesar. Narre de novo declarando o "
            f"efeito — inclusive 'não faz nada, é sentimental', que é resposta "
            f"válida e encerra o assunto."
        )

    if not achados:
        return violacoes

    nomes = ", ".join(f"'{it.get('nome')}' ({dono})" for dono, it in achados[:4])
    return violacoes + [
        f"Criou item que NÃO existe no SRD de D&D 5e e promete efeito "
        f"mecânico: {nomes}. Item inventado com regra desequilibra a mesa em "
        f"silêncio. Faça UMA das duas coisas e narre de novo: (a) troque por "
        f"um item real do SRD com efeito equivalente, ou (b) mantenha o item "
        f"e declare no texto por que ele é equilibrado para o nível "
        f"{nivel} — efeitos pequenos (+1, 1d4, uma vez por descanso longo) "
        f"em vez de números grandes e sempre ativos."
    ]


def _verify_agent_response(
    text: str,
    tools_called: set,
    combat_was_active: bool,
    dead_before: set | None = None,
) -> list[str]:
    """
    Verifica violações na resposta do agente e retorna uma lista de descrições.

    • Coerência de verdade (personagem morto agindo como vivo): vale para
      QUALQUER estilo de campanha.
    • Checagens mecânicas (HP, dados, combate, XP): só em dnd_mode=True.
    """
    violations = []

    # Trava de coerência — independe de dnd_mode.
    violations.extend(_check_dead_characters_alive(text, dead_before or set()))

    if not memory.campaign.get("dnd_mode", False):
        return violations

    # 1. Início de combate sem roll_initiative
    if (not combat_was_active
            and not _INIT_TOOLS.intersection(tools_called)
            and _COMBAT_START_RE.search(text)):
        violations.append(
            "Narrou início de combate ('rodada 1', 'iniciativa rolada', etc.) "
            "sem chamar roll_initiative(). Chame a ferramenta com TODOS os participantes."
        )

    # 1b. Combatente que a narração nunca mencionou.
    #     Não existe registro de quem está fisicamente na cena, então o único
    #     sinal disponível é a própria narração: se o mestre pôs alguém na
    #     iniciativa sem tê-lo colocado na cena, ele veio da lista de
    #     personagens conhecidos, não do encontro. Foi assim que NPCs de outros
    #     pontos da história apareceram no meio da luta.
    if _INIT_TOOLS.intersection(tools_called):
        violations.extend(_check_combatants_offscene(text))

    # 1c. Item inventado que mexe na regra.
    violations.extend(_check_itens_inventados(tools_called))

    # 2. HP modificado narrativamente
    if (not _HP_TOOLS.intersection(tools_called)
            and _HP_CHANGE_RE.search(text)):
        violations.append(
            "Modificou HP narrativamente (ex: '15 → 9', 'perdeu 6 PV') "
            "sem chamar modify_hp() ou attack_roll(). "
            "NUNCA escreva variações de HP — deixe a ferramenta calcular."
        )

    # 3. Resultado de ataque sem attack_roll (só durante combate ativo)
    # Fora de combate, "acertou" pode descrever ações não-mecânicas (ex: abrir fechadura).
    if (combat_was_active
            and not _ATCK_TOOLS.intersection(tools_called)
            and _ATTACK_RESULT_RE.search(text)):
        violations.append(
            "Narrou resultado de ataque ('acertou', 'errou o golpe') "
            "sem chamar attack_roll(). O dado decide — não a narrativa."
        )

    # 4. Mana modificada narrativamente
    if (not _MANA_TOOLS.intersection(tools_called)
            and _MANA_CHANGE_RE.search(text)):
        violations.append(
            "Modificou mana narrativamente sem chamar use_ability() ou modify_mana()."
        )

    # 5. Magia/habilidade narrada como aprendida sem learn_spell() ou learn_ability()
    if (not _LEARN_TOOLS.intersection(tools_called)
            and _SPELL_LEARNED_RE.search(text)):
        violations.append(
            "Narrou que um personagem aprendeu uma magia ou habilidade "
            "sem chamar learn_spell() ou learn_ability(). "
            "A magia NÃO foi adicionada à ficha. "
            "Chame learn_spell(char_name, spell_name) agora para registrar corretamente."
        )

    # 6. Condição aplicada narrativamente sem apply_condition()
    if (not _CONDITION_TOOLS.intersection(tools_called)
            and _CONDITION_APPLIED_RE.search(text)):
        violations.append(
            "Narrou aplicação de condição (cego, paralisado, envenenado, etc.) "
            "sem chamar apply_condition(). A condição NÃO foi salva na ficha. "
            "Chame apply_condition(char_name, 'condição') para registrar o efeito mecânico."
        )

    # 7. end_combat() sem grant_xp() — SÓ é violação numa VITÓRIA.
    #    Numa DERROTA (grupo todo caído/inconsciente/fugiu) não há XP a
    #    conceder — perder uma luta não dá XP. Vitória = alguém do grupo
    #    ainda de pé quando o combate terminou.
    if ("end_combat" in tools_called and not _XP_TOOLS.intersection(tools_called)):
        _DOWNED = {"morto", "inconsciente", "estabilizado", "fugiu",
                   "exilado", "dormindo"}
        party_members = [
            c for c in memory.campaign.get("characters", {}).values()
            if memory.is_party_member(c)
        ]
        party_standing = [
            c["name"] for c in party_members
            if (c.get("status") or "").lower() not in _DOWNED
        ]
        if party_standing:
            # Vitória: cobra XP para todo o grupo que não morreu/fugiu.
            recv = [
                c["name"] for c in party_members
                if (c.get("status") or "").lower() not in ("morto", "fugiu")
            ]
            names = ", ".join(recv or party_standing)
            violations.append(
                f"Encerrou o combate (vitória) com end_combat() mas não chamou "
                f"grant_xp() para o grupo. "
                f"Chame grant_xp() para CADA personagem jogável: {names}. "
                f"Use o XP adequado ao inimigo derrotado (25–2000 XP conforme a tabela)."
            )

    # 8. Vitória não encerrada: combate ATIVO, nenhum inimigo vivo restante,
    #    mas o agente não chamou end_combat() neste turno.
    if "end_combat" not in tools_called:
        cs = memory.campaign.get("combat_state", {})
        if cs.get("is_active") and cs.get("initiative_order"):
            _DEFEATED = {"morto", "inconsciente", "estabilizado", "fugiu", "exilado"}
            chars = memory.campaign.get("characters", {})
            enemies_alive, allies_alive = [], []
            for nome in cs.get("initiative_order", []):
                ch = chars.get(memory.char_key(nome))
                if not ch:
                    continue
                status = (ch.get("status") or "").lower()
                if status in _DEFEATED:
                    continue
                if memory.is_party_member(ch):
                    allies_alive.append(ch.get("name", nome))
                else:
                    enemies_alive.append(ch.get("name", nome))
            # Vitória = nenhum inimigo vivo, mas o grupo ainda de pé.
            if not enemies_alive and allies_alive:
                violations.append(
                    "O combate ainda está ATIVO, mas TODOS os inimigos foram "
                    "derrotados. Encerre a luta agora: chame end_combat() e, em "
                    "seguida, grant_xp() para CADA personagem do grupo "
                    f"({', '.join(allies_alive)}) com o XP do(s) inimigo(s) vencido(s)."
                )

    return violations


def _check_all_level_ups() -> list[str]:
    """
    Safety net: verifica TODOS os personagens do grupo após cada resposta.
    Se algum tiver XP >= threshold mas o LLM não chamou grant_xp,
    aplica o level up programaticamente e retorna lista de nomes que subiram.

    Chamado no handler 'done' do SSE loop, antes de salvar.
    Não duplica work — grant_xp() já aplica level up internamente.
    Esta função garante que nenhum level up seja perdido por falha do LLM.
    """
    from rpg.tools_dnd import XP_THRESHOLDS, _proficiency_bonus, _apply_class_features, CLASS_DATA, _max_mana_for
    import random

    if not memory.campaign.get("dnd_mode", False):
        return []

    leveled = []

    for key, char in memory.campaign.get("characters", {}).items():
        # Definição canônica de grupo (memory.is_party_member): party_member,
        # protagonista ou em campaign["party"]. Antes dependia só de
        # campaign["party"] e PULAVA o protagonista criado via ficha D&D.
        if not memory.is_party_member(char):
            continue
        sheet = char.get("sheet")
        if not sheet:
            continue

        nivel_atual = sheet.get("nivel", 1)
        xp_atual    = sheet.get("xp", 0)

        if nivel_atual >= 20:
            continue
        if xp_atual < XP_THRESHOLDS[nivel_atual]:
            continue

        # XP suficiente mas o nível não foi incrementado — aplica agora
        while sheet.get("nivel", 1) < 20 and sheet.get("xp", 0) >= XP_THRESHOLDS[sheet.get("nivel", 1)]:
            sheet["nivel"]       += 1
            sheet["proficiencia"] = _proficiency_bonus(sheet["nivel"])

            info    = CLASS_DATA.get(sheet.get("classe", "").lower(), {"hit_die": 8, "mana_per_level": 0, "mana_stat": None})
            con_mod = (sheet.get("constituicao", 10) - 10) // 2
            hp_gain = max(1, random.randint(1, info["hit_die"]) + con_mod)
            sheet["vida_max"]   += hp_gain
            sheet["vida_atual"] += hp_gain

            # Mana pela tabela Spell Points do DMG (igual ao grant_xp e ao
            # wizard de criação) — NÃO usar mana_per_level (fórmula legada).
            novo_mana_max = _max_mana_for(sheet.get("classe", ""), sheet["nivel"])
            if novo_mana_max != sheet.get("mana_max", 0):
                sheet["mana_max"]   = novo_mana_max
                sheet["mana_atual"] = novo_mana_max

            sheet["xp_proximo"] = XP_THRESHOLDS[sheet["nivel"]] if sheet["nivel"] < 20 else sheet["xp"]
            _apply_class_features(char, sheet, sheet["nivel"])
            leveled.append(f"{char.get('name', key)} → Nível {sheet['nivel']}")

    if leveled:
        memory.save_campaign()
        print(f"[LEVEL UP AUTO] {', '.join(leveled)}")

    return leveled


def _build_correction_prompt(violations: list[str], already_called: set | None = None) -> str:
    """Monta a mensagem de correção re-injetada no agente."""
    lines = [
        "[VERIFICAÇÃO AUTOMÁTICA DO SISTEMA — RESPOSTA ANTERIOR REJEITADA]\n",
        f"Detectei {len(violations)} violação(ões) das regras obrigatórias:\n",
    ]
    for i, v in enumerate(violations, 1):
        lines.append(f"  {i}. {v}")

    # Ferramentas que modificam estado e JÁ foram executadas neste turno.
    # Re-chamá-las causaria efeitos duplicados (dano duplo, mana dupla, etc.).
    # roll_initiative NÃO entra aqui: ela SUBSTITUI o estado de combate inteiro
    # (ordem, rodada, log, turno) em vez de somar efeito, então re-chamá-la no
    # mesmo turno não duplica nada — e é justamente o conserto quando a
    # iniciativa saiu com gente que não estava na cena.
    # add_item fica de fora: quando a correção é sobre um item inventado, o
    # conserto passa por remove_item + add_item com o item certo.
    # buy_item e sell_item ENTRAM: mexem na bolsa e no estoque, e agora
    # disparam a conferência de item inventado — sem isso, a rodada de
    # correção cobraria o ouro do jogador uma segunda vez pelo mesmo item.
    stateful = {"attack_roll", "modify_hp", "use_ability", "modify_mana",
                "apply_condition", "learn_spell", "learn_ability",
                "grant_xp", "set_flag", "clear_flag",
                "buy_item", "sell_item"}
    already_stateful = (already_called or set()) & stateful

    lines += [
        "\nCORRIJA AGORA — reescreva a resposta do zero:",
        "• Use os números EXATOS retornados pelas ferramentas",
        "• A narrativa imersiva vem DEPOIS dos resultados das ferramentas, nunca antes",
    ]

    if already_stateful:
        tools_str = ", ".join(sorted(already_stateful))
        lines += [
            f"\n⚠️  ATENÇÃO: as seguintes ferramentas JÁ foram chamadas neste turno e NÃO devem ser chamadas novamente: {tools_str}",
            "   Re-chamá-las causaria efeitos duplicados (dano duplo, mana dupla, etc.).",
            "   Apenas narre o resultado já obtido, corrigindo o formato.",
        ]
    else:
        lines.append("• NÃO repita a resposta rejeitada — comece do início com as ferramentas corretas")

    return "\n".join(lines)

app = Flask(__name__, static_folder="static")
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0   # desativa cache de arquivos estáticos
# Teto de tamanho de payload — bloqueia POSTs gigantes (DoS de memória).
# 4 MB cobre com folga a maior campanha legítima (histórico limitado a 200 falas).
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024

# ---------------------------------------------------------------------------
# Segurança — rate limiting, CORS allowlist e política de senha
# ---------------------------------------------------------------------------

# Origens permitidas para CORS. O app serve o frontend SAME-ORIGIN (login.html,
# menu.html… vêm deste mesmo Flask), então em produção CORS nem é necessário.
# A allowlist cobre dev local e é configurável via env ALLOWED_ORIGINS
# (separado por vírgula). NUNCA mais usar "*".
_ALLOWED_ORIGINS = {
    o.strip() for o in os.environ.get(
        "ALLOWED_ORIGINS",
        "http://localhost:5000,http://127.0.0.1:5000,http://localhost:3000",
    ).split(",") if o.strip()
}

# Rate limiting in-memory (sliding window). Suficiente para o porte do app;
# para multi-worker robusto, migrar o storage para Redis. Cada chave guarda
# os timestamps dos hits recentes.
_rate_buckets: dict = collections.defaultdict(list)
_rate_lock = threading.Lock()
_rate_sweep = 0


def _client_ip() -> str:
    """IP real do cliente atrás de Cloudflare/Render."""
    cf = request.headers.get("CF-Connecting-IP")
    if cf:
        return cf.strip()
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _rate_hit(key: str, max_hits: int, window_s: int) -> int:
    """
    Registra um hit em `key` numa janela deslizante. Retorna 0 se permitido,
    ou os segundos de espera (Retry-After) se o limite foi estourado.
    """
    global _rate_sweep
    now = time.time()
    with _rate_lock:
        hits = _rate_buckets[key]
        cutoff = now - window_s
        hits[:] = [t for t in hits if t > cutoff]
        if len(hits) >= max_hits:
            wait = int(window_s - (now - hits[0])) + 1
        else:
            hits.append(now)
            wait = 0
        # Sweep periódico: remove chaves antigas para não vazar memória.
        _rate_sweep += 1
        if _rate_sweep % 500 == 0:
            for k in list(_rate_buckets.keys()):
                _rate_buckets[k][:] = [t for t in _rate_buckets[k] if t > now - 3600]
                if not _rate_buckets[k]:
                    del _rate_buckets[k]
        return wait


def _enforce_rate(scope: str, email: str, ip_max: int, email_max: int,
                  window_s: int = 900):
    """
    Aplica rate limit por IP e (se email informado) por email. Retorna uma
    Response 429 pronta se o limite estourou, ou None se liberado.
    """
    wait = _rate_hit(f"{scope}:ip:{_client_ip()}", ip_max, window_s)
    if not wait and email:
        wait = _rate_hit(f"{scope}:em:{email.lower()}", email_max, window_s)
    if wait:
        resp = jsonify({"error": "Muitas tentativas. Aguarde alguns "
                                 "minutos e tente novamente."})
        resp.status_code = 429
        resp.headers["Retry-After"] = str(wait)
        return resp
    return None


def _rate_guard(key: str, max_hits: int, window_s: int):
    """
    Rate limit genérico por chave arbitrária (ex.: por user_id em endpoints
    caros de LLM). Retorna Response 429 pronta ou None se liberado.
    """
    wait = _rate_hit(key, max_hits, window_s)
    if wait:
        resp = jsonify({"error": "Muitas requisições em pouco tempo. "
                                 "Aguarde um momento e tente novamente."})
        resp.status_code = 429
        resp.headers["Retry-After"] = str(wait)
        return resp
    return None


def _validate_password(password: str) -> str | None:
    """Retorna mensagem de erro se a senha for fraca; None se aceitável."""
    if len(password) < 8:
        return "A senha deve ter ao menos 8 caracteres."
    if len(password) > 128:
        return "A senha é longa demais (máximo 128 caracteres)."
    if not any(c.isalpha() for c in password):
        return "A senha deve conter ao menos uma letra."
    if not any(c.isdigit() for c in password):
        return "A senha deve conter ao menos um número."
    if password.lower() in (
        "password", "12345678", "123456789", "senha123", "11111111",
        "qwertyui", "password1", "senha1234",
    ):
        return "Essa senha é comum demais. Escolha uma senha mais forte."
    return None

# ---------------------------------------------------------------------------
# Asyncio bridge — loop dedicado rodando em thread daemon
# ---------------------------------------------------------------------------

_loop = None

def _start_background_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

def get_loop():
    global _loop
    if _loop is None:
        _loop = asyncio.new_event_loop()
        t = threading.Thread(target=_start_background_loop, args=(_loop,), daemon=True, name="adk-loop")
        t.start()
    return _loop

def run_async(coro):
    """Submete coroutine ao loop dedicado e aguarda resultado (bloqueante)."""
    loop = get_loop()
    return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=120)

# ---------------------------------------------------------------------------
# Estado global — isolado por user_id
# ---------------------------------------------------------------------------

# {user_id: {"runner": ..., "session_service": ..., "is_ollama": bool}}
_sessions: dict = {}

# ---------------------------------------------------------------------------
# CORS (allowlist) + headers de segurança
# ---------------------------------------------------------------------------

def _apply_cors(resp):
    """Reflete a origem SOMENTE se estiver na allowlist (_ALLOWED_ORIGINS)."""
    origin = request.headers.get("Origin", "")
    if origin and origin in _ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"]  = origin
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
        # Vary: Origin evita cache servir a resposta de uma origem para outra.
        existing_vary = resp.headers.get("Vary", "")
        resp.headers["Vary"] = (existing_vary + ", Origin").lstrip(", ") \
            if "origin" not in existing_vary.lower() else existing_vary
    return resp


@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        return _apply_cors(app.make_default_options_response())


@app.after_request
def add_security_headers(resp):
    _apply_cors(resp)
    # Defense-in-depth para todas as respostas.
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"]        = "DENY"
    resp.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
    # HSTS — TLS é terminado no Cloudflare/Render; força HTTPS no browser.
    resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp

# ---------------------------------------------------------------------------
# Static
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory("static", "login.html")

@app.route("/login.html")
def login_page():
    return send_from_directory("static", "login.html")

@app.route("/menu.html")
def menu_page():
    resp = send_from_directory("static", "menu.html")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp

@app.route("/game.html")
def game_page():
    return send_from_directory("static", "game.html")

# --- PWA ---------------------------------------------------------------------
# O service worker precisa ser servido a partir da raiz para o seu escopo
# cobrir /menu.html e /game.html (um SW só controla páginas no seu path ou
# abaixo). Por isso /sw.js em vez de /static/sw.js.
@app.route("/sw.js")
def service_worker():
    resp = send_from_directory("static", "sw.js", mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache"  # garante atualização do SW
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp

@app.route("/manifest.webmanifest")
def web_manifest():
    return send_from_directory(
        "static", "manifest.webmanifest", mimetype="application/manifest+json"
    )

@app.route("/offline.html")
def offline_page():
    # Tela "A despertar…" servida pelo service worker durante o cold start.
    return send_from_directory("static", "offline.html")

@app.route("/healthz")
def healthz():
    # Endpoint propositadamente trivial: o app já está totalmente importado
    # (gunicorn --preload) quando qualquer rota responde, então um 200 aqui
    # significa "servidor acordado". Usado pela tela de despertar para saber
    # quando recarregar. Sem cache e sem auth.
    resp = jsonify({"status": "ok"})
    resp.headers["Cache-Control"] = "no-store"
    return resp

# ---------------------------------------------------------------------------
# Autenticação
# ---------------------------------------------------------------------------

@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.json or {}
    email    = data.get("email", "").strip()
    password = data.get("password", "")
    if not email or not password:
        return jsonify({"error": "Email e senha são obrigatórios."}), 400

    # Política de senha no servidor (não confia só no front nem no Supabase).
    pw_err = _validate_password(password)
    if pw_err:
        return jsonify({"error": pw_err}), 400

    # Rate limit — registro é raro; limites mais apertados.
    limited = _enforce_rate("register", email, ip_max=15, email_max=5)
    if limited:
        return limited

    try:
        result = auth_register(email, password)

        # Token presente → conta criada e já confirmada (confirmação desligada).
        if result.get("access_token"):
            return jsonify({"ok": True, "needs_confirmation": False, **result})

        # Sem token: conta nova aguardando confirmação OU email já cadastrado.
        # NÃO distinguimos os dois casos — resposta idêntica para não permitir
        # enumeração de emails. (O Supabase com confirmação de email ligada já
        # devolve um usuário ofuscado para emails existentes.)
        return jsonify({"ok": True, "needs_confirmation": True, "email": email})

    except Exception as e:
        # Erro real (rede, email malformado, etc.) — log interno, mensagem
        # genérica ao cliente. Não revela se o email existe nem detalhes.
        app.logger.warning("Falha no registro (%s): %s", email, e)
        return jsonify({"error": "Não foi possível concluir o registro. "
                                 "Verifique o email e tente novamente."}), 400


@app.route("/api/auth/confirm", methods=["POST"])
def confirm_email():
    """
    Recebe o access_token que o Supabase coloca no hash da URL de confirmação
    e devolve ok=True para o frontend salvar a sessão.

    O token é VALIDADO contra o Supabase aqui — não confiamos cegamente no
    que o cliente envia.
    """
    from rpg.auth import get_user_id

    data         = request.json or {}
    access_token = data.get("access_token", "")
    if not access_token:
        return jsonify({"error": "Token ausente."}), 400

    # Valida de verdade: get_user_id retorna None se o token for inválido.
    user_id = get_user_id(access_token)
    if not user_id:
        return jsonify({"error": "Token inválido ou expirado."}), 401

    return jsonify({"ok": True, "access_token": access_token})


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.json or {}
    email    = data.get("email", "").strip()
    password = data.get("password", "")
    if not email or not password:
        return jsonify({"error": "Email e senha são obrigatórios."}), 400

    # Rate limit — barra brute-force / credential stuffing.
    limited = _enforce_rate("login", email, ip_max=30, email_max=8)
    if limited:
        return limited

    try:
        result = auth_login(email, password)
        return jsonify({"ok": True, **result})
    except Exception as e:
        # Log interno detalhado; resposta genérica ao cliente.
        app.logger.warning("Falha no login (%s): %s", email, e)
        msg = str(e).lower()
        # O aviso de "email não confirmado" NÃO é vetor de enumeração: o
        # Supabase só o emite quando a senha está correta — ou seja, o
        # atacante já precisaria da senha. Mantemos por UX.
        if any(w in msg for w in ("confirm", "not confirmed", "verified")):
            return jsonify({"error": "Confirme seu email antes de entrar.",
                            "reason": "unconfirmed"}), 401
        return jsonify({"error": "Email ou senha incorretos."}), 401


@app.route("/api/auth/refresh", methods=["POST"])
def refresh_token():
    """
    Rota chamada silenciosamente pelo frontend para renovar o JWT expirado.
    """
    data = request.json or {}
    token = data.get("refresh_token")

    if not token:
        return jsonify({"error": "Refresh token ausente."}), 400

    # Rate limit frouxo por IP — o refresh legítimo é raro (~1×/hora), mas
    # ainda assim limitamos para não virar oráculo de tokens.
    limited = _enforce_rate("refresh", "", ip_max=60, email_max=0)
    if limited:
        return limited

    try:
        result = refresh_session(token)
        return jsonify({"ok": True, **result})
    except Exception as e:
        # 401 sinaliza ao frontend que a renovação falhou de vez.
        app.logger.warning("Falha no refresh: %s", e)
        return jsonify({"error": "Sessão expirada. Faça login novamente."}), 401

# ---------------------------------------------------------------------------
# Campanhas
# ---------------------------------------------------------------------------

@app.route("/api/campaigns")
@require_auth
def list_campaigns():
    try:
        result = database.list_campaigns(g.user_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _payload_de_campanha(name: str, dados: dict, personagens: dict) -> dict:
    """
    Monta o dict que vai para o banco, a partir de um JSON de campanha vindo
    de fora (wizard de criação ou importação de arquivo).

    UM lugar só, de propósito. Antes as duas rotas repetiam a mesma lista
    branca de chaves, e foi assim que a onda 4 passou: missões, relógio e
    lojas eram gravados pelo jogo e sumiam ao importar, porque as duas listas
    não sabiam deles. Chave nova entra AQUI e as duas rotas ganham junto.

    A lista de chaves espelha memory._defaults() — se você acrescentar uma
    coisa lá, acrescente aqui também, ou ela não sobrevive à importação.
    """
    return {
        "name":                 name,
        "campaign_type":        dados.get("campaign_type", "fantasia"),
        "dnd_mode":             dados.get("dnd_mode", False),
        # Preferência de como o combate é jogado ("narrado" ou "tela"). Não
        # estava aqui: quem importava uma campanha do modo tela caía no
        # narrado sem entender por quê.
        "combat_mode":          dados.get("combat_mode", "narrado"),
        "protagonist":          dados.get("protagonist", ""),
        "chapter":              dados.get("chapter", 1),
        "current_location":     dados.get("current_location", ""),
        "current_scene":        dados.get("current_scene", ""),
        "story_summary":        dados.get("story_summary", ""),
        "quest_flags":          dados.get("quest_flags", {}),
        "party":                dados.get("party", []),
        "characters":           personagens,
        "locations":            dados.get("locations", {}),
        "events":               dados.get("events", []),
        "diary":                dados.get("diary", []),
        "conversation_history": [],
        "combat_state":         dados.get("combat_state", {
            "is_active": False, "initiative_order": [],
            "current_turn_index": 0, "round": 1,
        }),
        # Onda 4 — mundo, missões e economia. Sem estas linhas, exportar e
        # reimportar uma campanha jogava fora tudo o que o grupo construiu:
        # o diário de missões, a hora do mundo, as lojas abertas.
        "relogio":              dados.get("relogio", {}),
        "quests":               dados.get("quests", {}),
        "lojas":                dados.get("lojas", {}),
        "_turno":               dados.get("_turno", 0),
        "_upkeep":              dados.get("_upkeep", {}),
    }


@app.route("/api/campaigns", methods=["POST"])
@require_auth
def create_campaign():
    """
    Cria uma campanha nova a partir do wizard do menu.
    Payload: { name: str, campaign: dict }
    Mesmo formato do /api/campaigns/import, mas destinado ao wizard de criação.
    """
    data          = request.get_json(force=True) or {}
    name          = "".join(c for c in data.get("name", "") if c.isalnum() or c in " _-").strip()
    campaign_data = data.get("campaign", {})

    if not name:
        return jsonify({"error": "Nome inválido"}), 400
    if not campaign_data:
        return jsonify({"error": "Dados da campanha ausentes"}), 400
    if database.campaign_exists(g.user_id, name):
        return jsonify({"error": f"Já existe uma campanha com o nome '{name}'"}), 409

    # Normaliza chaves de personagens para lowercase + normaliza sheet.classe
    from rpg.tools_dnd import reconcile_character_archetypes
    raw_chars = campaign_data.get("characters", {})
    normalized_chars = {}
    for k, v in raw_chars.items():
        char = dict(v)
        if char.get("sheet") and isinstance(char["sheet"].get("classe"), str):
            char["sheet"] = dict(char["sheet"])
            char["sheet"]["classe"] = char["sheet"]["classe"].lower()
        # Materializa sub-features de arquétipos escolhidos no editor/wizard.
        reconcile_character_archetypes(char)
        normalized_chars[k.lower().strip().replace("_", " ")] = char

    payload = _payload_de_campanha(name, campaign_data, normalized_chars)

    try:
        database.save_campaign(g.user_id, name, payload)
        return jsonify({"ok": True, "name": name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/campaigns/<name>", methods=["GET"])
@require_auth
def get_campaign(name):
    try:
        data = database.get_campaign(g.user_id, name)
        if data is None:
            return jsonify({"error": "Campanha não encontrada"}), 404
        return jsonify({"ok": True, "campaign": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/campaigns/<name>", methods=["PUT"])
@require_auth
def update_campaign(name):
    """Atualiza os dados de uma campanha existente (sem sobrescrever conversation_history)."""
    data = request.get_json(force=True) or {}
    campaign_data = data.get("campaign", {})

    existing = database.get_campaign(g.user_id, name)
    if existing is None:
        return jsonify({"error": "Campanha não encontrada"}), 404

    new_name = campaign_data.get("name", name)
    new_name = "".join(c for c in new_name if c.isalnum() or c in " _-").strip()
    if not new_name:
        return jsonify({"error": "Nome inválido"}), 400

    # Materializa sub-features de arquétipos escolhidos no editor antes de
    # persistir (o picker do editor só grava a escolha em feature_choices).
    from rpg.tools_dnd import reconcile_character_archetypes
    edited_chars = campaign_data.get("characters", existing.get("characters", {}))
    if isinstance(edited_chars, dict):
        for _ch in edited_chars.values():
            if isinstance(_ch, dict):
                reconcile_character_archetypes(_ch)

    # Preserve fields that should not be overwritten by the editor
    payload = dict(existing)
    payload.update({
        "name":             new_name,
        "campaign_type":    campaign_data.get("campaign_type", existing.get("campaign_type", "fantasia")),
        "dnd_mode":         campaign_data.get("dnd_mode", existing.get("dnd_mode", False)),
        "protagonist":      campaign_data.get("protagonist", existing.get("protagonist", "")),
        "story_summary":    campaign_data.get("story_summary", existing.get("story_summary", "")),
        "current_scene":    campaign_data.get("current_scene", existing.get("current_scene", "")),
        "current_location": campaign_data.get("current_location", existing.get("current_location", "")),
        "characters":       edited_chars,
        "locations":        campaign_data.get("locations", existing.get("locations", {})),
        "events":           campaign_data.get("events", existing.get("events", [])),
        "party":            campaign_data.get("party", existing.get("party", [])),
    })

    try:
        if new_name != name:
            if database.campaign_exists(g.user_id, new_name):
                return jsonify({"error": f"Já existe uma campanha com o nome '{new_name}'"}), 409
            database.delete_campaign(g.user_id, name)
        database.save_campaign(g.user_id, new_name, payload)
        return jsonify({"ok": True, "name": new_name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/dnd/class-spells")
@require_auth
def get_class_spells():
    """Retorna magias de uma classe até um nível máximo (usa Open5e + fallback local)."""
    from rpg.tools_dnd import _CLASS_SLUG_MAP, SPELL_MANA_COST, DEFAULT_SPELLS_BY_CLASS
    from rpg.open5e import http as _req   # SRD com cache, sessão e retry

    classe          = request.args.get("class", "").lower().strip()
    max_level       = min(int(request.args.get("max_level", 9) or 9), 9)
    query           = request.args.get("q", "").strip().lower()
    spell_level_str = request.args.get("spell_level")   # filtro de nível exato (opcional)

    en_class = _CLASS_SLUG_MAP.get(classe, "")
    spells   = []

    try:
        # Sem classe (modo livre): busca em todas as magias. Com classe:
        # filtra por `dnd_class__icontains` — o filtro exato `dnd_class` casa
        # só o texto inteiro ("Sorcerer, Wizard" != "Wizard"), excluindo
        # magias multiclasse, e retorna 0 quando combinado com `search`.
        # `__icontains` é substring, case-insensitive e funciona com `search`.
        # Sem query usamos limit maior para obter variedade entre níveis.
        params = {
            "spell_level__lte": max_level,
            "limit":            100 if query else 250,
            "ordering":         "spell_level",
        }
        if en_class:
            params["dnd_class__icontains"] = en_class
        if query:
            params["search"] = query
        # Filtro de nível exato (substituí lte quando presente)
        if spell_level_str is not None:
            try:
                params["spell_level"] = int(spell_level_str)
                del params["spell_level__lte"]
            except (ValueError, TypeError):
                pass
        r = _req.get("https://api.open5e.com/v1/spells/", params=params, timeout=6)
        if r.ok:
            seen = set()
            for s in r.json().get("results", []):
                nome = s.get("name", "")
                key  = nome.lower().strip()
                if not nome or key in seen:
                    continue
                seen.add(key)
                lvl  = int(s.get("spell_level", 0) or 0)
                dado = ""
                dmg  = s.get("damage", {})
                if isinstance(dmg, dict):
                    dado = dmg.get("damage_dice", "") or ""
                    if not dado:
                        # Cantrips: dado em damage_at_character_level (ex: Fire Bolt → 1d10)
                        atcl = dmg.get("damage_at_character_level", {})
                        if isinstance(atcl, dict) and atcl:
                            dado = (atcl.get("1") or
                                    next(iter(v for v in
                                         (atcl[k] for k in sorted(atcl, key=lambda x: int(x) if x.isdigit() else 99))
                                         if v), ""))
                    if not dado:
                        # Magias escaláveis: dado em damage_at_slot_level (ex: Fireball → 8d6)
                        atsl = dmg.get("damage_at_slot_level", {})
                        if isinstance(atsl, dict) and atsl:
                            dado = (atsl.get("3") or
                                    next(iter(v for v in
                                         (atsl[k] for k in sorted(atsl, key=lambda x: int(x) if x.isdigit() else 99))
                                         if v), ""))
                if not dado:
                    # Fallback: extrai primeira notação de dados da descrição
                    # (ex: Magic Missile "1d4 + 1", Healing Word "1d4")
                    _desc = s.get("desc", "") or ""
                    _m = re.search(r'\d+d\d+(?:\s*[+\-]\s*\d+)?', _desc)
                    if _m:
                        dado = _m.group(0).replace(" ", "")
                spells.append({
                    "nome":          nome,
                    "nivel_magia":   lvl,
                    "escola":        s.get("school", ""),
                    "descricao":     (" ".join((s.get("desc","") or "").split()))[:250],
                    "custo_mana":    SPELL_MANA_COST.get(lvl, 4),
                    "dado":          dado,
                    "ritual":        bool(s.get("ritual")),
                    "concentracao":  bool(s.get("concentration")),
                    # Alcance vindo direto do Open5e — usado pelo engine para
                    # decidir target_mode ("Self" → self-only; "Self (X cone)"
                    # → área; resto → alvo único). Evita listas hardcoded.
                    "alcance":       (s.get("range", "") or "").strip(),
                })
            # A busca full-text da Open5e também casa na descrição (ex.:
            # "fireball" traz "Antimagic Field"). Prioriza nome; sort
            # estável preserva a ordem por nível dentro de cada grupo.
            if query:
                spells.sort(key=lambda sp: 0 if query in sp["nome"].lower() else 1)
    except Exception:
        pass

    # Fallback local só quando uma classe foi pedida e a Open5e falhou.
    if not spells and classe:
        fallback = DEFAULT_SPELLS_BY_CLASS.get(classe, [])
        if query:
            fallback = [s for s in fallback if query in s.get("nome","").lower() or query in s.get("descricao","").lower()]
        spells = fallback[:50]

    return jsonify({"ok": True, "spells": spells})


@app.route("/api/dnd/items/search")
@require_auth
def search_dnd_items():
    """Busca itens D&D no Open5e: armas, armaduras e itens mágicos."""
    from rpg.open5e import http as _req   # SRD com cache, sessão e retry

    q         = request.args.get("q", "").strip()
    item_type = request.args.get("type", "all")

    if not q or len(q) < 2:
        return jsonify({"ok": True, "items": []})

    results = []
    try:
        if item_type in ("all", "weapon"):
            r = _req.get("https://api.open5e.com/v1/weapons/", params={"search": q, "limit": 6}, timeout=5)
            if r.ok:
                for it in r.json().get("results", []):
                    props = it.get("properties", [])
                    prop_str = ", ".join(props) if isinstance(props, list) else str(props or "")
                    results.append({
                        "nome":    it.get("name", ""),
                        "tipo":    "arma",
                        "descricao": f"Dano: {it.get('damage_dice','?')}. {prop_str}".strip(". "),
                        "qtd":     1,
                    })

        if item_type in ("all", "armor"):
            r = _req.get("https://api.open5e.com/v1/armor/", params={"search": q, "limit": 6}, timeout=5)
            if r.ok:
                for it in r.json().get("results", []):
                    ac = it.get("armor_class", {}) or {}
                    base = ac.get("base", "?")
                    results.append({
                        "nome":    it.get("name", ""),
                        "tipo":    "armadura",
                        "descricao": f"CA base: {base}.",
                        "qtd":     1,
                    })

        if item_type in ("all", "magic"):
            r = _req.get("https://api.open5e.com/v1/magicitems/", params={"search": q, "limit": 6}, timeout=5)
            if r.ok:
                for it in r.json().get("results", []):
                    desc = (it.get("desc", "") or "")
                    results.append({
                        "nome":    it.get("name", ""),
                        "tipo":    "mágico",
                        "descricao": " ".join(desc.split())[:180],
                        "qtd":     1,
                    })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "items": []})

    return jsonify({"ok": True, "items": results[:18]})


@app.route("/api/dnd/monsters/search")
@require_auth
def search_dnd_monsters():
    """Busca monstros D&D no Open5e e retorna atributos prontos para a ficha."""
    from rpg.open5e import http as _req   # SRD com cache, sessão e retry

    q = request.args.get("q", "").strip()
    if not q or len(q) < 2:
        return jsonify({"ok": True, "monsters": []})

    def parse_monster(m):
        ac_raw = m.get("armor_class", 10)
        if isinstance(ac_raw, list):
            ca = ac_raw[0].get("value", 10) if ac_raw else 10
        else:
            ca = int(ac_raw or 10)

        # Ataques do stat block — mesma extração usada por spawn_monster, para
        # que a ficha montada pela UI e a criada pelo motor não divirjam.
        from rpg.tools_dnd import _extract_monster_attacks
        atk = _extract_monster_attacks(m)

        return {
            "nome":           m.get("name", ""),
            "tipo":           m.get("type", ""),
            "tamanho":        m.get("size", ""),
            "cr":             str(m.get("challenge_rating", "?")),
            "forca":          int(m.get("strength",     10) or 10),
            "destreza":       int(m.get("dexterity",    10) or 10),
            "constituicao":   int(m.get("constitution", 10) or 10),
            "inteligencia":   int(m.get("intelligence", 10) or 10),
            "sabedoria":      int(m.get("wisdom",       10) or 10),
            "carisma":        int(m.get("charisma",     10) or 10),
            "ca":             ca,
            "vida":           int(m.get("hit_points",   10) or 10),
            "hit_dice":       m.get("hit_dice", ""),
            "arma_principal": atk["arma_principal"],
            "arma_secundaria":atk["arma_secundaria"],
            "arma_dado":      atk["arma_dado"],
            "arma_dado_secundaria": atk["arma_dado_secundaria"],
            "ataques":        atk["ataques"],
            "multiattack":    atk["multiattack"],
        }

    try:
        # 1. Tenta busca direta pelo slug (ex: "goblin" → /v1/monsters/goblin/)
        slug = q.lower().strip().replace(" ", "-")
        direct = _req.get(f"https://api.open5e.com/v1/monsters/{slug}/", timeout=5)
        if direct.ok:
            data = direct.json()
            if data.get("name"):
                return jsonify({"ok": True, "monsters": [parse_monster(data)]})

        # 2. Fallback: busca textual, mas ordena por similaridade de nome
        r = _req.get(
            "https://api.open5e.com/v1/monsters/",
            params={"search": q, "limit": 20},
            timeout=6,
        )
        if not r.ok:
            return jsonify({"ok": True, "monsters": []})

        q_lower = q.lower()
        results = r.json().get("results", [])

        # Ordena: nome exato > começa com query > contém query > resto
        def sort_key(m):
            name = m.get("name", "").lower()
            if name == q_lower:            return 0
            if name.startswith(q_lower):   return 1
            if q_lower in name:            return 2
            return 3

        results.sort(key=sort_key)
        monsters = [parse_monster(m) for m in results[:10]]
        return jsonify({"ok": True, "monsters": monsters})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "monsters": []})


@app.route("/api/dnd/class-features")
@require_auth
def get_class_features():
    """Retorna habilidades de classe disponíveis até o nível informado."""
    from rpg.tools_dnd import CLASS_LEVEL_FEATURES, CLASS_FEATURE_DESCS

    classe = request.args.get("class", "").lower().strip()
    nivel  = int(request.args.get("level", 1) or 1)

    features_by_level = CLASS_LEVEL_FEATURES.get(classe, {})
    result = []
    for lvl in sorted(features_by_level.keys()):
        if lvl > nivel:
            break
        for feat_name in features_by_level[lvl]:
            desc_data = CLASS_FEATURE_DESCS.get(feat_name, {})
            result.append({
                "nome":       feat_name,
                "nivel":      lvl,
                "descricao":  desc_data.get("descricao", f"Habilidade de classe — {feat_name}."),
                "custo_mana": desc_data.get("custo_mana", 0),
                "dado":       desc_data.get("dado", ""),
            })
    return jsonify({"ok": True, "features": result})


@app.route("/api/dnd/feature_variants", methods=["GET"])
@require_auth
def get_feature_variants():
    """
    Retorna metadata de features com subescolha (Estilo de Combate, Inimigo
    Favorecido, Metamagia, etc.). A UI usa para renderizar o picker em vez
    do card descritivo padrão.

    Sem query → devolve TODAS as features e suas opções.
    Com ?feature=<nome> → só essa feature, com options resolvido (ex.:
    "Inimigo Favorecido Adicional" herda options de "Inimigo Favorecido").
    """
    from rpg.tools_dnd import FEATURE_VARIANTS, _get_variants

    feat = request.args.get("feature", "").strip()
    if feat:
        meta = _get_variants(feat)
        if not meta:
            return jsonify({"ok": False, "error": "feature sem variantes"}), 404
        return jsonify({"ok": True, "feature": feat, "variants": meta})

    # Lista completa — útil para o frontend cachear de uma vez.
    out = {}
    for name in FEATURE_VARIANTS.keys():
        out[name] = _get_variants(name)
    return jsonify({"ok": True, "variants": out})


@app.route("/api/dnd/feature_choice", methods=["POST"])
@require_auth
def set_feature_choice_route():
    """
    Aplica/remove uma subescolha de feature. Body JSON:
      { "char": "<nome>", "feature": "<feature>", "choice": "<opção>" }
    Para remover: "choice": "remove:<opção>".

    Despacha para tools_dnd.set_feature_choice — a função aplica a regra
    de validação (pick limit, opção existir, etc.) e recalcula CA quando
    necessário (Defesa).
    """
    from rpg.tools_dnd import set_feature_choice
    from rpg import memory as _mem

    data    = request.get_json() or {}
    char    = (data.get("char") or "").strip()
    feature = (data.get("feature") or "").strip()
    choice  = (data.get("choice") or "").strip()
    campaign = (data.get("campaign") or "").strip()

    if not char or not feature or not choice:
        return jsonify({"ok": False, "error": "char, feature e choice obrigatórios"}), 400

    # Bind à campanha do usuário e carrega — set_feature_choice opera sobre
    # memory.campaign (em sessão). Mesmo padrão de outros endpoints que
    # mutam a ficha do personagem em jogo.
    if campaign:
        _mem.bind(g.user_id, campaign)
        _mem.load_campaign()

    msg = set_feature_choice(char, feature, choice)
    ok = msg.startswith("✅") or msg.startswith("🗑️")
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/campaigns/<name>", methods=["DELETE"])
@require_auth
def delete_campaign(name):
    try:
        database.delete_campaign(g.user_id, name)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/campaigns/<name>/rename", methods=["POST"])
@require_auth
def rename_campaign(name):
    new_name = "".join(
        c for c in request.json.get("name", "")
        if c.isalnum() or c in " _-"
    ).strip()
    if not new_name:
        return jsonify({"error": "Nome inválido"}), 400
    if database.campaign_exists(g.user_id, new_name):
        return jsonify({"error": "Já existe uma campanha com esse nome"}), 409
    try:
        database.rename_campaign(g.user_id, name, new_name)
        return jsonify({"name": new_name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------------------------------------------------------------------------
# Início de sessão
# ---------------------------------------------------------------------------

@app.route("/api/ollama/models")
@require_auth
def ollama_models():
    import urllib.request, urllib.error
    base = os.environ.get("OLLAMA_API_BASE", "http://localhost:11434")
    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=3) as r:
            data   = json.loads(r.read())
            models = [m["name"] for m in data.get("models", [])]
            return jsonify({"ok": True, "models": models})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "models": []})


# ---------------------------------------------------------------------------
# Catálogo de modelos
#
# A lista do menu costumava ser fixa no HTML e envelhecia a cada modelo novo
# que o Google lançava. Agora ela é montada a partir do que a CHAVE DO
# USUÁRIO realmente enxerga (rota /api/gemini/models abaixo) — os IDs vêm da
# própria API, então nunca ficam desatualizados nem são adivinhados.
#
# MODEL_LIMITS continua existindo para os limites de cota (RPM/RPD), que a
# API de listagem NÃO informa. Modelo desconhecido cai em "default".
# ---------------------------------------------------------------------------

MODEL_LIMITS = {
    # Família Gemini 3.x
    "gemini-3.1-flash-lite-preview": {"rpd": 500,   "rpm": 15},
    "gemini-3-flash":                {"rpd": 20,    "rpm": 5},
    "gemini-3.1-flash-tts":          {"rpd": 10,    "rpm": 3},

    # Família Gemini 2.5
    "gemini-2.5-flash":              {"rpd": 20,    "rpm": 5},
    "gemini-2.5-flash-lite":         {"rpd": 20,    "rpm": 10},

    # Família Gemma (IDs técnicos com -it)
    "gemma-3-27b-it":                {"rpd": 14400, "rpm": 30},
    "gemma-4-26b-it":                {"rpd": 14400, "rpm": 30},
    "gemma-4-31b-it":                {"rpd": 14400, "rpm": 30},

    "default":                       {"rpd": 500,   "rpm": 15}
}

# Modelos que existem na API mas não servem para narrar uma campanha:
# geradores de imagem/vídeo/áudio, embeddings e sessões ao vivo. Filtrar aqui
# evita encher o menu de opções que quebrariam no primeiro turno.
_MODELOS_IGNORADOS = (
    "embedding", "aqa", "imagen", "image", "veo", "lyria",
    "computer-use", "robotics", "live", "learnlm",
)


def _familia_do_modelo(model_id: str) -> str:
    """Rótulo do optgroup no menu, a partir do ID do modelo."""
    if model_id.startswith("gemma"):
        return "Google Gemma"
    if model_id.startswith("gemini-3"):
        return "Google Gemini 3.x"
    if model_id.startswith("gemini-2"):
        return "Google Gemini 2.x"
    return "Outros modelos Google"


@app.route("/api/gemini/models", methods=["POST"])
@require_auth
def gemini_models():
    """
    Lista os modelos de texto que a chave Google do usuário enxerga.

    A chave chega no CORPO (nunca na URL) e é repassada ao Google no cabeçalho
    x-goog-api-key — assim ela não aparece em log de acesso nem no histórico.
    Nada é guardado no servidor.

    Devolve sempre 200 com {ok, models, error}: sem chave ou com a API fora do
    ar, o menu simplesmente mantém a lista fixa de reserva do HTML.
    """
    import urllib.error
    import urllib.request

    limited = _rate_guard(f"models:user:{g.user_id}", 20, 300)
    if limited:
        return limited

    data    = request.get_json(silent=True) or {}
    api_key = data.get("google_api_key", "").strip() or os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        return jsonify({"ok": False, "error": "sem_chave", "models": []})

    modelos, pagina, token = [], 0, ""
    try:
        while pagina < 5:                       # teto de segurança na paginação
            url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200"
            if token:
                url += f"&pageToken={token}"
            req = urllib.request.Request(url, headers={"x-goog-api-key": api_key})
            with urllib.request.urlopen(req, timeout=8) as r:
                corpo = json.loads(r.read())

            for m in corpo.get("models", []):
                if "generateContent" not in (m.get("supportedGenerationMethods") or []):
                    continue
                mid = (m.get("name") or "").replace("models/", "")
                if not mid or any(t in mid for t in _MODELOS_IGNORADOS):
                    continue
                limites = MODEL_LIMITS.get(mid)
                modelos.append({
                    "id":      mid,
                    "label":   m.get("displayName") or mid,
                    "familia": _familia_do_modelo(mid),
                    "rpm":     limites["rpm"] if limites else None,
                    "rpd":     limites["rpd"] if limites else None,
                })

            token = corpo.get("nextPageToken") or ""
            pagina += 1
            if not token:
                break
    except urllib.error.HTTPError as e:
        motivo = "chave_invalida" if e.code in (400, 401, 403) else f"http_{e.code}"
        return jsonify({"ok": False, "error": motivo, "models": []})
    except Exception:
        # Log interno; para o cliente basta saber que deve usar a reserva.
        app.logger.warning("Falha ao listar modelos Gemini", exc_info=True)
        return jsonify({"ok": False, "error": "indisponivel", "models": []})

    modelos.sort(key=lambda m: (m["familia"], m["label"]))
    return jsonify({"ok": True, "models": modelos, "error": ""})

@app.route("/api/session/start", methods=["POST"])
@require_auth
def start_session():
    user_id = g.user_id

    data          = request.json
    campaign_name = data.get("campaign")
    model_id      = data.get("model", "gemini-2.5-flash")
    campaign_type = data.get("campaign_type", "fantasia")
    story_mode    = data.get("story_mode", "ask")
    story_input   = data.get("story_input", "")
    genre         = data.get("genre", "")

    # Chaves de API fornecidas pelo usuário (fallback para variáveis de ambiente)
    user_google_key   = data.get("google_api_key", "").strip()
    user_deepseek_key = data.get("deepseek_api_key", "").strip()
    google_key        = user_google_key
    deepseek_key      = user_deepseek_key

    # Vincula o contexto à campanha DESTE usuário (estado por sessão).
    memory.bind(user_id, campaign_name)
    has_history = memory.load_campaign()

    memory.campaign["name"] = campaign_name

    if not has_history:
        memory.campaign["campaign_type"] = campaign_type
        memory.save_campaign()
    else:
        campaign_type = memory.campaign.get("campaign_type", campaign_type)

    if model_id.startswith("ollama:"):
        from google.adk.models.lite_llm import LiteLlm
        os.environ.setdefault("OLLAMA_API_BASE", "http://localhost:11434")
        model       = LiteLlm(model=f"ollama_chat/{model_id[7:]}")
        model_label = f"Ollama — {model_id[7:]}"
        is_ollama   = True
    elif model_id.startswith("deepseek:"):
        from google.adk.models.lite_llm import LiteLlm
        if not deepseek_key:
            return jsonify({"error": "Chave de API do DeepSeek não configurada. Adicione-a nas configurações."}), 400
        model_name  = model_id[9:]
        model       = LiteLlm(
            model=f"deepseek/{model_name}",
            api_key=deepseek_key,
        )
        model_label = f"DeepSeek — {model_name}"
        is_ollama   = False
    else:
        if not google_key:
            return jsonify({"error": "Chave de API do Google não configurada. Adicione-a nas configurações."}), 400
        os.environ["GOOGLE_API_KEY"] = google_key
        model       = model_id
        model_label = f"Gemini — {model_id}"
        is_ollama   = False

    _dbg("\n" + "▓" * 70)
    _dbg("🚀 [MENU] Iniciando sessão de jogo — montando o agente")
    _dbg(f"   • Usuário ............ {user_id}")
    _dbg(f"   • Campanha ........... {campaign_name}")
    _dbg(f"   • Estilo (instrução) . {campaign_type}  (define a 'política' do agente)")
    _dbg(f"   • Modelo (LLM) ....... {model_label}")
    _dbg(f"   • Histórico salvo? ... {'sim — vai gerar recap' if has_history else 'não — campanha nova'}")

    agent = create_agent(model, campaign_type)
    runner, session_service = create_runner(agent)
    _n_tools = len(getattr(agent, "tools", []) or [])
    _dbg(f"   ✅ Agente '{getattr(agent, 'name', 'rpg_master_agent')}' criado "
         f"com {_n_tools} ferramentas (ações disponíveis).")
    _dbg("▓" * 70 + "\n")

    # Identidade ADK POR USUÁRIO/CAMPANHA (antes era fixa "jogador1"/"sessao1"
    # → o histórico de conversa do LLM vazava entre todos os usuários).
    adk_user    = str(user_id)
    adk_session = f"{user_id}::{campaign_name}"
    run_async(session_service.create_session(
        app_name=APP_NAME, user_id=adk_user, session_id=adk_session
    ))

    _sessions[user_id] = {
    "runner":          runner,
    "session_service": session_service,
    "is_ollama":       is_ollama,
    "model_id":        model_id,
    "adk_user":        adk_user,
    "adk_session":     adk_session,
    }

    # Distingue "campanha com histórico de conversa de verdade" de "campanha
    # recém-criada pelo wizard que já tem setup (resumo, cena, personagens)
    # mas nunca foi jogada". A flag `has_history` retornada por
    # memory.load_campaign() é True em ambos os casos — precisamos olhar
    # diretamente para conversation_history aqui.
    real_history = len(memory.campaign.get("conversation_history", [])) > 0
    has_setup    = (
        bool((memory.campaign.get("story_summary")    or "").strip()) or
        bool((memory.campaign.get("current_scene")    or "").strip()) or
        bool((memory.campaign.get("current_location") or "").strip()) or
        bool(memory.campaign.get("characters") or {}) or
        bool(memory.campaign.get("locations")  or {}) or
        bool(memory.campaign.get("party")      or []) or
        bool(memory.campaign.get("events")     or [])
    )

    if real_history:
        opening      = _build_recap()
        opening_type = "recap"
    elif has_setup:
        # Campanha criada pelo wizard: já temos resumo/cena/personagens.
        # NÃO perguntar ao jogador o tema — ele já preencheu tudo.
        opening      = _build_fresh_start_opening()
        opening_type = "new"
    elif story_mode == "custom" and story_input:
        opening = (
            f"O jogador quer começar uma campanha com o seguinte cenário:\n\n"
            f"{story_input}\n\n"
            "Use essa descrição como ponto de partida. Apresente o mundo, "
            "introduza o personagem do jogador e inicie a narrativa."
        )
        opening_type = "new"
    elif story_mode == "random":
        opening = (
            f"Crie uma campanha aleatória de {genre if genre else 'fantasia'}. "
            "Apresente o mundo, o personagem do jogador e a situação inicial "
            "de forma imersiva, sem perguntar nada — comece narrando."
        )
        opening_type = "new"
    else:
        opening      = "Olá! Pergunte ao jogador o tema ou cenário da campanha."
        opening_type = "ask"

    # Debug: este é o PRIMEIRO contexto que o agente recebe sobre o mundo.
    # Para recap/campanha nova, embute o get_full_context() (personagens,
    # local, eventos, flags, resumo) — é "como o agente sabe o que existe".
    _dbg(f"\n📜 [CONTEXTO INICIAL] Mensagem de abertura injetada no agente "
         f"(tipo: {opening_type}):")
    _dbg_block(opening, title="CONTEXTO INJETADO NO AGENTE")
    _dbg("")

    limits = MODEL_LIMITS.get(model_id, {"rpd": 500, "rpm": 15})

    return jsonify({
        "ok":                   True,
        "has_history":          has_history,
        "opening":              opening,
        "opening_type":         opening_type,
        "model_label":          model_label,
        "campaign":             campaign_name,
        "campaign_type":        campaign_type,
        "campaign_config":      get_campaign_config(campaign_type),
        "model_limits": limits,
        "conversation_history": memory.campaign.get("conversation_history", []),
    })


def _build_fresh_start_opening() -> str:
    """
    Prompt de abertura para campanhas recém-criadas pelo wizard: já existe
    resumo, cena inicial, local, personagens e/ou eventos preenchidos pelo
    jogador, mas ainda não há nenhuma conversa. O mestre deve começar
    narrando a partir desse setup, sem perguntar nada que já foi informado.
    """
    from rpg.tools import get_full_context
    contexto = get_full_context()
    protagonist = (memory.campaign.get("protagonist") or "").strip()
    proto_line  = (
        f"O protagonista do jogador é {protagonist}. " if protagonist else ""
    )

    # Se o wizard já gerou fichas D&D, o agente NÃO deve recriá-las (recriar
    # zera CA/atributos/equipamento e duplica itens). Aviso explícito.
    chars_com_ficha = [
        c.get("name", "")
        for c in memory.campaign.get("characters", {}).values()
        if c.get("sheet")
    ]
    ficha_line = ""
    if chars_com_ficha:
        ficha_line = (
            "• ⚠️ Os personagens a seguir JÁ possuem ficha D&D pronta (criada "
            f"pelo wizard): {', '.join(chars_com_ficha)}. NÃO chame "
            "create_character_sheet para eles — as fichas já existem com "
            "atributos, vida, CA e equipamento corretos. Recriar destruiria "
            "esses dados. Apenas comece a narrar.\n"
        )

    return (
        "Esta é uma campanha NOVA que o jogador acabou de criar pelo "
        "wizard. Os dados abaixo (resumo, cena inicial, local, personagens, "
        "eventos) foram preenchidos por ele — trate-os como verdade do "
        "mundo e ponto de partida da narrativa.\n\n"
        f"{contexto}\n\n"
        "INSTRUÇÕES DE ABERTURA:\n"
        f"{ficha_line}"
        "• NÃO pergunte ao jogador qual é o tema, cenário, gênero, "
        "personagem ou local — ele já forneceu tudo isso.\n"
        "• NÃO peça para o jogador escolher entre estilos de campanha.\n"
        "• COMECE narrando imediatamente a cena inicial descrita acima de "
        "forma imersiva e sensorial (no mínimo 3–5 parágrafos), "
        "estabelecendo atmosfera, local e personagens presentes.\n"
        f"• {proto_line}Use segunda pessoa (\"você...\").\n"
        "• Termine a abertura entregando a vez ao jogador com uma situação "
        "concreta para ele reagir (uma escolha, um estímulo, alguém "
        "falando com ele, um som, uma decisão a tomar)."
    )


def _build_recap() -> str:
    from rpg.tools import get_full_context
    contexto = get_full_context()
    hist = memory.campaign["conversation_history"][-40:]
    lines = [
        f"[{'Jogador' if e['role']=='user' else 'Mestre'}]: {e['text']}"
        for e in hist
    ]

    # Injeta estado de combate explicitamente para evitar que o agente
    # re-execute turnos já processados ao retomar a sessão.
    cs = memory.campaign.get("combat_state", {})
    combat_block = ""
    if cs.get("is_active"):
        order   = cs.get("initiative_order", [])
        idx     = cs.get("current_turn_index", 0)
        round_n = cs.get("round", 1)
        current = order[idx] if order and idx < len(order) else "?"
        vez_msg = (
            f"Aguarde a ação do jogador — é a vez de {current}."
            if not _is_npc(current)
            else f"Anuncie que é a vez de {current} e aguarde o jogador digitar 'continuar'. NÃO execute o ataque ainda."
        )
        combat_block = (
            f"\n\n⚔️  COMBATE ATIVO — ESTADO ATUAL (NÃO RE-EXECUTE TURNOS ANTERIORES):\n"
            f"   Rodada: {round_n}\n"
            f"   Ordem: {' → '.join(f'[{n}]' if i == idx else n for i, n in enumerate(order))}\n"
            f"   Turno atual: {current}\n"
            f"   INSTRUÇÃO CRÍTICA: o histórico acima já contém ações processadas. {vez_msg}"
        )

    return (
        "Estamos retomando uma aventura em andamento. "
        "Abaixo está o estado completo do mundo e o histórico recente.\n\n"
        f"{contexto}\n\n"
        f"--- HISTÓRICO RECENTE ---\n{chr(10).join(lines)}\n"
        f"{combat_block}\n\n"
        "Faça um breve recap ao jogador do ponto em que estávamos "
        "e aguarde a próxima ação dele para continuar a narrativa. "
        "NÃO tome nenhuma ação de combate por conta própria ao retomar."
    )


def _is_npc(name: str) -> bool:
    """Retorna True se o personagem não é membro do grupo (é NPC/inimigo)."""
    party_names = {
        m.get("name", "").lower().strip()
        for m in memory.campaign.get("party", [])
    }
    return name.lower().strip() not in party_names

# ---------------------------------------------------------------------------
# Chat com SSE
# ---------------------------------------------------------------------------

@app.route("/api/chat", methods=["POST"])
@require_auth
def chat():
    user_id = g.user_id

    # Rate limit por usuário — /api/chat aciona a LLM (custo/token). Barra
    # abuso e contém o dano de um token roubado. 40 mensagens / 5 min.
    limited = _rate_guard(f"chat:user:{user_id}", 40, 300)
    if limited:
        return limited

    sess    = _sessions.get(user_id)
    if not sess:
        return jsonify({"error": "Sessão não iniciada"}), 400

    runner    = sess["runner"]
    is_ollama = sess["is_ollama"]
    model_id  = sess.get("model_id", "")

    texto     = request.json.get("message", "").strip()
    registrar = request.json.get("registrar", True)
    if not texto:
        return jsonify({"error": "Mensagem vazia"}), 400

    texto_agente = texto
    if is_ollama or "gemma" in model_id.lower():
        # Força o modelo a separar o pensamento da narrativa usando tags[cite: 10]
        texto_agente = (
            "<system>\n"
            "INSTRUÇÃO CRÍTICA: Você DEVE separar seu planejamento da sua resposta final.\n"
            "Use as tags <think> e </think> para todo o seu raciocínio lógico, lista de tarefas ou recapitulação interna (em inglês ou português).\n"
            "Após fechar a tag </think>, escreva APENAS a narração imersiva da cena em Português do Brasil.\n"
            "Exemplo de formato obrigatório:\n"
            "<think>\n"
            "The player is Dante. I need to describe the frost on the table...\n"
            "</think>\n"
            "Diante de você, a superfície de madeira da taverna começa a congelar...\n"
            "</system>\n\n"
            f"<user_input>\n{texto}\n</user_input>"
        )
        
    if registrar:
        memory.campaign["conversation_history"].append({"role": "user", "text": texto})

    result_q = queue.Queue()
    MAX_RETRIES = 3

    WRITE_TOOLS = {
        "save_character", "save_location", "save_event", "set_flag",
        "add_diary_entry", "update_character_status", "update_story_summary",
        "update_world_state", "add_party_member", "remove_party_member", "clear_flag",
    }

    # Estado de combate ANTES desta resposta (para comparação na verificação)
    _combat_was_active = memory.campaign.get("combat_state", {}).get("is_active", False)

    # Personagens já MORTOS antes deste turno — usado pela trava de coerência.
    # Capturado aqui (antes do agente rodar) para não acusar falso-positivo no
    # próprio turno em que um inimigo morre (sua última ação pode ser narrada).
    _dead_before = {
        (c.get("name") or "").lower().strip()
        for c in memory.campaign.get("characters", {}).values()
        if (c.get("status") or "").lower() == "morto" and c.get("name")
    }

    adk_user    = sess.get("adk_user", str(user_id))
    adk_session = sess.get("adk_session", f"{user_id}::sessao")

    async def run_agent(texto: str):
        import random
        # Re-vincula o contexto de memória DENTRO da corrotina do agente.
        # O ContextVar definido na thread Flask (via require_auth) NÃO
        # propaga para a Task no loop de fundo — então fixamos aqui, no
        # contexto desta Task, garantindo que as tools operem na campanha
        # do usuário correto.
        memory.bind_request(user_id)
        msg          = gtypes.Content(role="user", parts=[gtypes.Part(text=texto)])
        MAX_RETRIES  = 5

        _dbg("\n" + "═" * 70)
        _dbg(f"🎲 [AGENTE] Novo turno  |  usuário={adk_user}  campanha={memory.campaign.get('name', '?')}")
        _dbg(f"   ▶ Entrada: {_short(texto, 300)}")
        _dbg("─" * 70)

        for attempt in range(MAX_RETRIES):
            full         = ""
            tools_called = set()
            if attempt > 0:
                _dbg(f"🔁 [AGENTE] Tentativa {attempt + 1}/{MAX_RETRIES} (retry após erro recuperável)")
            try:
                async for event in runner.run_async(
                    user_id=adk_user, session_id=adk_session, new_message=msg
                ):
                    if event.content and event.content.parts:
                        for part in event.content.parts:
                            fc = getattr(part, "function_call", None)
                            if fc and getattr(fc, "name", None):
                                name = fc.name
                                args = dict(fc.args) if fc.args else {}
                                kind = "write" if name in WRITE_TOOLS else "read"
                                tools_called.add(name)
                                # Debug: o agente DECIDIU agir sobre o ambiente.
                                icon     = "✏️  WRITE" if kind == "write" else "👁️  READ "
                                args_str = ", ".join(f"{k}={_short(v, 60)}" for k, v in args.items())
                                _dbg(f"  🔧 [AÇÃO ] {icon} → {name}({args_str})")
                                result_q.put(("tool_call", {"name": name, "args": args, "kind": kind}))

                            fr = getattr(part, "function_response", None)
                            if fr and getattr(fr, "name", None):
                                resp_dict = dict(fr.response) if fr.response else {}
                                conteudo  = resp_dict.get("result", "")
                                # Debug: o ambiente RESPONDEU à ação (observação).
                                if fr.name in _CONTEXT_TOOLS:
                                    # Percepção: é exatamente o que informa o agente
                                    # sobre personagens, local, eventos e flags.
                                    # Mostra o bloco COMPLETO (não truncado).
                                    _dbg(f"  📥 [OBSERV] {fr.name} → PERCEPÇÃO DA CENA (contexto que o agente lê):")
                                    _dbg_block(conteudo)
                                else:
                                    # Limite maior aqui para não esconder marcações
                                    # importantes que vêm no fim do texto (ex.: morte,
                                    # "INCONSCIENTE", XP concedido, level up).
                                    _dbg(f"  📥 [OBSERV] {fr.name} → {_short(conteudo, 600)}")
                                if conteudo:
                                    # Remove trechos marcados como instrução interna
                                    # ao modelo ([[llm]]…[[/llm]]) antes de exibir
                                    # na UI. A LLM já consumiu o conteúdo completo
                                    # via function_response; este queue só serve
                                    # para o stream visual de tool_result.
                                    visible = re.sub(
                                        r'\s*\[\[llm\]\][\s\S]*?\[\[/llm\]\]\s*',
                                        '\n',
                                        str(conteudo),
                                    ).strip()
                                    if visible:
                                        result_q.put(("tool_result", {"tool_name": fr.name, "content": visible}))

                    if event.usage_metadata:
                        um = event.usage_metadata
                        # cached_content_token_count: parte do prompt servida
                        # do cache do provedor. Os ~11k tokens de schema das
                        # ferramentas ficam no INÍCIO da requisição, então são
                        # o bloco mais cacheável que existe — este contador é
                        # o que diz se eles estão custando 100% ou uma fração.
                        cached = int(getattr(um, "cached_content_token_count", 0) or 0)
                        prompt = int(um.prompt_token_count or 0)
                        usage = {
                            "prompt_tokens":     prompt,
                            "candidates_tokens": um.candidates_token_count,
                            "total_tokens":      um.total_token_count,
                            "cached_tokens":     cached,
                            # Fração do prompt que veio do cache, em [0,1].
                            "cache_hit_ratio":   round(cached / prompt, 3) if prompt else 0.0,
                            # Tokens de raciocínio (modelos com thinking).
                            "thoughts_tokens":   int(getattr(um, "thoughts_token_count", 0) or 0),
                        }
                        _cache_str = (
                            f" | cache={cached} ({usage['cache_hit_ratio']:.0%} do prompt)"
                            if cached else " | cache=0 ⚠️ nada aproveitado"
                        )
                        _dbg(
                            f"  🧮 [TOKENS] prompt={usage['prompt_tokens']} "
                            f"resposta={usage['candidates_tokens']} "
                            f"total={usage['total_tokens']}{_cache_str}"
                        )
                        result_q.put(("quota_update", usage))

                    if event.is_final_response() and event.content and event.content.parts:
                        for part in event.content.parts:
                            if part.text and not getattr(part, "thought", False):
                                full += part.text

                if not full.strip():
                    full = "*(O Mestre observa os registros em silêncio por um momento, parecendo organizar as memórias da aventura...)*"

                _dbg("─" * 70)
                _dbg(f"💬 [AGENTE] Resposta final ({len(tools_called)} ferramenta(s) usada(s): "
                     f"{', '.join(sorted(tools_called)) or 'nenhuma'})")
                _dbg(f"   {_short(full, 400)}")
                _dbg("═" * 70 + "\n")

                result_q.put(("done", {
                    "text":              full,
                    "tools_called":      tools_called,
                    "combat_was_active": _combat_was_active,
                    "dead_before":       _dead_before,
                }))
                return

            except Exception as exc:
                err          = str(exc).lower()
                is_retryable = any(k in err for k in (
                    "overloaded", "429", "503", "500", "504",
                    "rate limit", "quota", "resource exhausted", "deadline",
                ))
                if is_retryable and attempt < MAX_RETRIES - 1:
                    wait = (2 ** (attempt + 1)) + random.uniform(0, 1)
                    result_q.put(("retrying", f"Mestre ocupado (Tentativa {attempt + 1}/{MAX_RETRIES}). Retomando em {wait:.1f}s..."))
                    await asyncio.sleep(wait)
                else:
                    result_q.put(("error", f"O RPG AGENT silenciou: {str(exc)}"))
                    return

    # Inicia a thread e atrela um "capturador de desastres" a ela
    future = asyncio.run_coroutine_threadsafe(run_agent(texto_agente), _loop)

    def on_thread_done(fut):
        try:
            fut.result()
        except Exception as e:
            result_q.put(("error", f"Erro fatal interno na thread da IA: {e}"))

    future.add_done_callback(on_thread_done)

    def generate():
        correction_attempted = False   # Máximo de 1 correção por resposta

        while True:
            try:
                kind, content = result_q.get(timeout=120)

                if kind == "retrying":
                    yield f"data: {json.dumps({'type': 'retrying', 'content': content})}\n\n"

                elif kind == "tool_call":
                    yield f"data: {json.dumps({'type': 'tool_call', 'tool': content})}\n\n"

                elif kind == "tool_result":
                    yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': content['tool_name'], 'content': content['content']})}\n\n"

                elif kind == "quota_update":
                    yield f"data: {json.dumps({'type': 'quota', 'content': content})}\n\n"

                elif kind == "error":
                    yield f"data: {json.dumps({'type': 'error', 'content': content})}\n\n"
                    return

                elif kind == "done":
                    response_text      = content["text"]
                    tools_called       = content.get("tools_called", set())
                    combat_was_active  = content.get("combat_was_active", False)
                    dead_before        = content.get("dead_before", set())

                    # ── Loop de verificação pós-resposta ──────────────────
                    if not correction_attempted:
                        mech_violations = _verify_agent_response(
                            response_text, tools_called, combat_was_active, dead_before
                        )
                        if mech_violations:
                            correction_attempted = True
                            correction_prompt    = _build_correction_prompt(mech_violations, tools_called)

                            _dbg("\n" + "🛑" * 35)
                            _dbg(f"🔎 [VERIFICADOR] {len(mech_violations)} violação(ões) detectada(s) "
                                 f"— a resposta do agente quebrou regras mecânicas:")
                            for v in mech_violations:
                                _dbg(f"     • {_short(v, 160)}")
                            _dbg("↩️  [VERIFICADOR] Re-injetando o seguinte prompt de correção no agente:")
                            _dbg("┌" + "─" * 68)
                            for line in correction_prompt.splitlines():
                                _dbg("│ " + line)
                            _dbg("└" + "─" * 68)
                            _dbg("🛑" * 35 + "\n")

                            # Notifica o frontend que está corrigindo
                            yield f"data: {json.dumps({'type': 'correction', 'violations': mech_violations})}\n\n"

                            # Re-executa o agente com a mensagem de correção
                            corr_future = asyncio.run_coroutine_threadsafe(
                                run_agent(correction_prompt), _loop
                            )
                            corr_future.add_done_callback(on_thread_done)
                            continue   # Continua lendo da fila — a correção vai colocar novo "done"

                    # ── Conclusão normal ───────────────────────────────────
                    if registrar and response_text:
                        memory.campaign["conversation_history"].append(
                            {"role": "assistant", "text": response_text}
                        )
                        memory.save_campaign()

                    result = validate(response_text)
                    violations = [
                        {"severity": v.severity, "rule": v.rule, "message": v.message, "detail": v.detail}
                        for v in result.violations
                    ]

                    # Fecha o ciclo da manutenção de memória.
                    #
                    # Estes avisos ("Fulano parece novo mas não foi salvo",
                    # "local X não registrado") só chegavam ao JOGADOR, que não
                    # pode fazer nada com eles — quem esqueceu foi o mestre.
                    # Guardados aqui, o provedor de instrução os devolve ao
                    # agente no turno seguinte, junto com há quantos turnos o
                    # resumo, o diário e o local não são atualizados. Custa
                    # zero chamada de API: a instrução é recomputada de todo
                    # jeito a cada turno.
                    if registrar:
                        memory.avancar_turno()
                        memory.campaign["_pendencias"] = [
                            v["message"] for v in violations
                            if v["rule"] in ("unsaved_character", "unknown_location")
                        ][:6]
                        memory.save_campaign()

                    yield f"data: {json.dumps({'type': 'text', 'content': response_text})}\n\n"

                    if violations:
                        yield f"data: {json.dumps({'type': 'violations', 'violations': violations})}\n\n"

                    # Safety net: verifica level ups que o LLM pode ter perdido
                    leveled_up = _check_all_level_ups()
                    if leveled_up:
                        yield f"data: {json.dumps({'type': 'level_up', 'characters': leveled_up})}\n\n"

                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    return

            except queue.Empty:
                yield f"data: {json.dumps({'type': 'error', 'content': 'Timeout: A API da IA não respondeu em 120s. Verifique sua conexão ou se o serviço está operante.'})}\n\n"
                return

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

# ---------------------------------------------------------------------------
# Memória
# ---------------------------------------------------------------------------

@app.route("/api/memory")
@require_auth
def get_memory_state():
    c  = memory.campaign
    ct = c.get("campaign_type", "fantasia")

    all_chars_map = c.get("characters", {})

    # Enriquece cada membro do party com dados completos (sheet, inventario, habilidades)
    # vindos de characters — o array party só guarda {name, role, notes}
    enriched_party = []
    for member in c.get("party", []):
        key  = member.get("name", "").lower().strip().replace("_", " ")
        full = all_chars_map.get(key, {})
        enriched_party.append({**full, **member})

    # NPCs/personagens que já estão no party não aparecem de novo em "Personagens"
    party_keys = {m.get("name", "").lower().strip() for m in c.get("party", [])}
    chars_only = [
        v for k, v in all_chars_map.items()
        if v.get("name", "").lower().strip() not in party_keys
    ]

    return jsonify({
        "campaign_type":    ct,
        "dnd_mode":         c.get("dnd_mode", False),
        "campaign_config":  get_campaign_config(ct),
        "chapter":          c.get("chapter", 1),
        "current_location": c.get("current_location", ""),
        "current_scene":    c.get("current_scene", ""),
        "story_summary":    c.get("story_summary", ""),
        "quest_flags":      c.get("quest_flags", {}),
        "party":            enriched_party,
        "characters":       chars_only,
        "locations":        list(c.get("locations", {}).values()),
        "events":           c.get("events", []),
        "diary":            c.get("diary", []),
        "combat_state":     c.get("combat_state", {
            "is_active":          False,
            "initiative_order":   [],
            "current_turn_index": 0,
            "round":              1,
        }),
        "conversation_history": c.get("conversation_history", []),
        # Onda 4 — o que a tela precisa para mostrar mundo e missões.
        # Campanha antiga não tem essas chaves; o default mantém o front
        # funcionando sem migração nenhuma.
        "relogio":          c.get("relogio", {}),
        "quests":           list((c.get("quests") or {}).values()),
    })


@app.route("/api/diary/export", methods=["POST"])
@require_auth
def export_diary():
    content  = memory.export_diary_md()
    filename = f"{memory.CAMPAIGN_NAME or 'campanha'}.diario.md"
    return Response(
        content,
        mimetype="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/api/campaigns/generate-lore", methods=["POST"])
@require_auth
def generate_lore():
    """
    Gera resumo, cena, locais E personagens a partir de uma ideia básica.
    Roteia para Google Gemini, DeepSeek ou Ollama conforme o prefixo do modelo.
    """
    # Rate limit por usuário — geração de lore aciona a LLM (custo alto).
    # 12 gerações / 15 min é folgado para uso legítimo e barra abuso.
    limited = _rate_guard(f"lore:user:{g.user_id}", 12, 900)
    if limited:
        return limited

    data            = request.get_json()
    user_prompt     = data.get("prompt", "").strip()
    model           = data.get("model", "").strip()
    campaign_type   = data.get("campaign_type", "fantasia").strip()
    api_key         = data.get("google_api_key", "").strip()  or os.environ.get("GOOGLE_API_KEY", "")
    ds_key          = data.get("deepseek_api_key", "").strip() or os.environ.get("DEEPSEEK_API_KEY", "")

    if not user_prompt:
        return jsonify({"error": "Prompt vazio."}), 400

    is_deepseek = model.startswith("deepseek:")
    is_ollama   = model.startswith("ollama:")

    if is_deepseek and not ds_key:
        return jsonify({"error": "Chave DeepSeek não encontrada. Salve-a nas configurações."}), 400
    if not is_deepseek and not is_ollama and not api_key:
        return jsonify({"error": "Chave Google API não encontrada. Salve-a nas configurações."}), 400

    is_dnd = campaign_type == "dnd"

    # Lista curada de slugs SRD (Open5e) — usada como enum mecânico de "raca"
    # para NPCs/inimigos. O nome do personagem ("name") continua livre em
    # português; o "raca" é só a referência ao bloco de stats.
    SRD_MONSTER_SLUGS = (
        # Humanoides civilizados / mercenários
        "bandit, bandit-captain, guard, thug, scout, spy, veteran, knight, "
        "noble, commoner, acolyte, priest, cultist, cult-fanatic, "
        "mage, archmage, assassin, berserker, druid, tribal-warrior, "
        # Humanoides monstruosos
        "goblin, hobgoblin, bugbear, orc, kobold, gnoll, lizardfolk, drow, "
        # Mortos-vivos
        "skeleton, zombie, ghoul, ghost, wight, wraith, specter, mummy, "
        "vampire-spawn, banshee, "
        # Bestas
        "wolf, dire-wolf, brown-bear, giant-spider, giant-eagle, panther, "
        # Plantas e natureza (criaturas feitas de raízes/madeira/pedra viva)
        "treant, awakened-tree, awakened-shrub, shambling-mound, vine-blight, "
        "dryad, "
        # Elementais
        "fire-elemental, water-elemental, earth-elemental, air-elemental, "
        "magma-mephit, dust-mephit, mud-mephit, "
        # Gigantes
        "ogre, troll, ettin, hill-giant, frost-giant, fire-giant, "
        # Constructos
        "animated-armor, flying-sword, gargoyle, scarecrow, "
        "clay-golem, stone-golem, iron-golem, "
        # Demônios / diabos
        "imp, quasit, dretch, succubus, vrock, hezrou, "
        # Aberrações
        "mimic, gibbering-mouther, intellect-devourer, "
        # Feras monstruosas
        "owlbear, basilisk, manticore, displacer-beast, griffon, hippogriff, "
        "harpy, minotaur, centaur, "
        # Dragões
        "young-red-dragon, young-blue-dragon, young-green-dragon, "
        "young-white-dragon, young-black-dragon, wyvern, pseudodragon, "
        # Fey
        "satyr, sprite, pixie, blink-dog"
    )

    # Schema D&D: inclui tipo (jogador/aliado/inimigo) e classe apenas para PCs.
    # O campo "raca" tem semântica DIFERENTE conforme o tipo:
    #   • PC          → raça D&D em PT (humano, elfo, …)
    #   • aliado/inim → slug SRD em INGLÊS (resolve no Open5e p/ CR/HP/CA reais)
    char_schema = (
        '{"name":"","description":"","traits":"","notes":"","role":"",'
        '"tipo":"<jogador|aliado|inimigo>",'
        '"classe":"<bárbaro|guerreiro|paladino|patrulheiro|bardo|clérigo|druida|monge|ladino|mago|feiticeiro|bruxo|npc>",'
        '"raca":"<PC: humano|elfo|anão|halfling|draconato|gnomo|meio-elfo|meio-orc|tiferino · '
                'NPC: slug SRD em INGLÊS da lista fornecida no texto>"}'
        if is_dnd else
        '{"name":"","description":"","traits":"","notes":"","role":"","tipo":"<jogador|aliado|inimigo>"}'
    )
    char_tip = (
        'Para D&D use o campo "tipo" para classificar cada personagem: '
        '"jogador" = herói/aventureiro com classe PC (bárbaro, guerreiro, mago, etc.); '
        '"aliado" = NPC amigável sem classe PC (use classe "npc"); '
        '"inimigo" = monstro/antagonista sem classe PC (use classe "npc"). '
        "Apenas personagens do tipo jogador devem ter classes de PC. "
        "REGRA CRÍTICA para o campo 'raca' de NPCs (tipo=aliado ou inimigo, classe=npc): "
        "escolha OBRIGATORIAMENTE um slug de monstro SRD em INGLÊS desta lista, "
        "pegando o que melhor representa MECANICAMENTE a criatura — o campo "
        "'name' continua sendo livre/criativo em português e é o que o jogador "
        "verá. O 'raca' é só a referência ao stat block. Lista permitida: "
        f"{SRD_MONSTER_SLUGS}. "
        "Exemplos de mapeamento name→raca: "
        "'Guardião da Floresta' (criatura de raízes e pedras) → raca: 'treant'; "
        "'Capitão dos Bandidos' → raca: 'bandit-captain'; "
        "'Servo Esquelético' → raca: 'skeleton'; "
        "'Senhor do Fogo' (elemental) → raca: 'fire-elemental'; "
        "'Lobo Negro' → raca: 'dire-wolf'; "
        "'Bruxa do Pântano' → raca: 'hag' não está na lista, use 'mage' ou 'druid' como aproximação. "
        "JAMAIS use 'humanoide', 'monstro', 'outro' nem termos genéricos em "
        "português para o 'raca' de NPCs — se nenhuma opção da lista couber "
        "perfeitamente, escolha a APROXIMAÇÃO mais próxima (NUNCA deixe vazio "
        "nem invente um slug fora da lista). "
        if is_dnd else
        'Use "tipo" para classificar: "jogador", "aliado" ou "inimigo". Não inclua classe ou raça. '
    )

    system = (
        "Você é um Mestre de RPG criativo. Dado uma ideia básica, gere um JSON com EXATAMENTE esta estrutura:\n"
        '{"story_summary":"<resumo de 5-8 linhas>","current_scene":"<cena inicial vívida>",'
        '"current_location":"<nome do local inicial>",'
        '"locations":[{"name":"","description":"","details":"","notes":""}],'
        '"events":[{"summary":"","location":"","characters_involved":"","consequence":""}],'
        f'"characters":[' + char_schema + ']}' + '}\n'
        "Gere 2-3 locais relevantes. "
        "Gere 2-3 eventos iniciais importantes na array 'events'. "
        "Gere TODOS os personagens mencionados na ideia (máximo 4), um por pessoa citada. "
        "Preencha obrigatoriamente o campo 'notes' dos personagens com o seu histórico ou motivação. "
        f"{char_tip}"
        "IMPORTANTE: Nos campos dos personagens (description, traits, notes) NÃO mencione nomes de magias, "
        "habilidades mecânicas, equipamentos ou atributos numéricos — apenas narrativa pura, personalidade e história. "
        "Magias, habilidades e equipamentos serão aplicados automaticamente pelo sistema com base na classe escolhida. "
        "Responda APENAS com JSON válido, sem markdown, sem comentários."
    )
    
    full_prompt = f"{system}\n\nIdeia: {user_prompt}\n\nTipo de campanha: {campaign_type}"

    _route = "DeepSeek" if is_deepseek else ("Ollama" if is_ollama else "Gemini")
    _dbg("\n" + "✨" * 35)
    _dbg(f"🧙 [MENU/LORE] Gerando mundo da campanha via {_route} ({model})")
    _dbg(f"   • Tipo: {campaign_type}  |  Ideia do jogador: {_short(user_prompt, 200)}")
    _dbg("✨" * 35 + "\n")

    try:
        raw = ""

        if is_deepseek:
            import requests as _req
            model_id = model.replace("deepseek:", "")
            resp = _req.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {ds_key}", "Content-Type": "application/json"},
                json={"model": model_id, "messages": [{"role": "user", "content": full_prompt}], "max_tokens": 1500},
                timeout=30,
            )
            raw = resp.json()["choices"][0]["message"]["content"].strip()

        elif is_ollama:
            import requests as _req
            model_id = model.replace("ollama:", "")
            resp = _req.post(
                "http://localhost:11434/api/generate",
                json={"model": model_id, "prompt": full_prompt, "stream": False},
                timeout=60,
            )
            raw = resp.json().get("response", "").strip()

        else:
            # Google Gemini — usa o modelo exato escolhido pelo usuário
            from google import genai as _genai
            client   = _genai.Client(api_key=api_key)
            response = client.models.generate_content(model=model, contents=full_prompt)
            raw      = response.text.strip()

        raw  = re.sub(r'^```(?:json)?\s*', '', raw)
        raw  = re.sub(r'\s*```$', '', raw)
        lore = json.loads(raw)
        return jsonify({"ok": True, "lore": lore})

    except json.JSONDecodeError as e:
        return jsonify({"error": f"IA retornou JSON inválido: {e}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/campaigns/import", methods=["POST"])
@require_auth
def import_campaign():
    data         = request.json
    name         = "".join(c for c in data.get("name", "") if c.isalnum() or c in " _-").strip()
    campaign_data = data.get("campaign", {})

    if not name:
        return jsonify({"error": "Nome inválido"}), 400
    if not campaign_data:
        return jsonify({"error": "JSON de campanha vazio"}), 400
    if database.campaign_exists(g.user_id, name):
        return jsonify({"error": f"Já existe uma campanha com o nome '{name}'"}), 409

    # Normaliza chaves do dict characters para lowercase (padrão char_key).
    # Sem isso, uma campanha importada com "Sonael" e o backend buscando "sonael"
    # cria entradas duplicadas a cada chamada de ferramenta.
    raw_chars = campaign_data.get("characters", {})
    normalized_chars = {}
    for k, v in raw_chars.items():
        char = dict(v)
        # Normaliza sheet.classe para lowercase — o sistema usa "bárbaro", não "Bárbaro"
        if char.get("sheet") and isinstance(char["sheet"].get("classe"), str):
            char["sheet"] = dict(char["sheet"])
            char["sheet"]["classe"] = char["sheet"]["classe"].lower()
        normalized_chars[k.lower().strip().replace("_", " ")] = char

    payload = _payload_de_campanha(name, campaign_data, normalized_chars)

    database.save_campaign(g.user_id, name, payload)
    return jsonify({"ok": True, "name": name})


@app.route("/api/session/end", methods=["POST"])
@require_auth
def end_session():
    user_id = g.user_id

    if memory.campaign and memory.campaign.get("name"):
        try:
            print(f"Salvando estado final de '{memory.campaign['name']}' antes de encerrar...")
            memory.save_campaign()
        except Exception as e:
            print(f"Falha ao salvar durante o encerramento: {e}")
            return jsonify({"ok": False, "error": "Falha ao persistir dados"}), 500

    _sessions.pop(user_id, None)
    memory.unbind(user_id)
    return jsonify({"ok": True})


@app.route("/api/memory/characters/<name>", methods=["PUT"])
@require_auth
def update_character(name):
    data = request.json
    key  = name.lower()
    if key not in memory.campaign["characters"]:
        return jsonify({"error": "Não encontrado"}), 404
    ch = memory.campaign["characters"][key]
    ch.update({k: v for k, v in data.items() if k in ch})
    # Se o nome mudou, remigra a chave
    new_name = data.get("name", "").strip()
    if new_name and new_name.lower() != key:
        memory.campaign["characters"][new_name.lower()] = ch
        del memory.campaign["characters"][key]
    memory.save_campaign()
    return jsonify({"ok": True})


@app.route("/api/memory/characters/<name>", methods=["DELETE"])
@require_auth
def delete_character(name):
    key = name.lower()
    if key not in memory.campaign["characters"]:
        return jsonify({"error": "Não encontrado"}), 404
    del memory.campaign["characters"][key]
    memory.save_campaign()
    return jsonify({"ok": True})


@app.route("/api/memory/locations/<name>", methods=["PUT"])
@require_auth
def update_location(name):
    data = request.json
    key  = name.lower()
    if key not in memory.campaign["locations"]:
        return jsonify({"error": "Não encontrado"}), 404
    loc = memory.campaign["locations"][key]
    loc.update({k: v for k, v in data.items() if k in loc})
    new_name = data.get("name", "").strip()
    if new_name and new_name.lower() != key:
        memory.campaign["locations"][new_name.lower()] = loc
        del memory.campaign["locations"][key]
    memory.save_campaign()
    return jsonify({"ok": True})


@app.route("/api/memory/locations/<name>", methods=["DELETE"])
@require_auth
def delete_location(name):
    key = name.lower()
    if key not in memory.campaign["locations"]:
        return jsonify({"error": "Não encontrado"}), 404
    del memory.campaign["locations"][key]
    memory.save_campaign()
    return jsonify({"ok": True})


@app.route("/api/memory/flags/<name>", methods=["PUT"])
@require_auth
def update_flag(name):
    value = request.json.get("value", "")
    memory.campaign["quest_flags"][name] = value
    memory.save_campaign()
    return jsonify({"ok": True})


@app.route("/api/memory/flags/<name>", methods=["DELETE"])
@require_auth
def delete_flag(name):
    memory.campaign["quest_flags"].pop(name, None)
    memory.save_campaign()
    return jsonify({"ok": True})


@app.route("/api/memory/party/<name>", methods=["PUT"])
@require_auth
def update_party_member(name):
    data  = request.json
    party = memory.campaign["party"]
    for m in party:
        if m["name"].lower() == name.lower():
            m.update({k: v for k, v in data.items() if k in m})
            memory.save_campaign()
            return jsonify({"ok": True})
    return jsonify({"error": "Não encontrado"}), 404


@app.route("/api/memory/party/<name>", methods=["DELETE"])
@require_auth
def delete_party_member(name):
    before = len(memory.campaign["party"])
    memory.campaign["party"] = [m for m in memory.campaign["party"] if m["name"].lower() != name.lower()]
    if len(memory.campaign["party"]) == before:
        return jsonify({"error": "Não encontrado"}), 404
    memory.save_campaign()
    return jsonify({"ok": True})


@app.route("/api/memory/events/<int:index>", methods=["PUT"])
@require_auth
def update_event(index):
    data   = request.json
    events = memory.campaign["events"]
    for e in events:
        if e["index"] == index:
            e.update({k: v for k, v in data.items() if k in e})
            memory.save_campaign()
            return jsonify({"ok": True})
    return jsonify({"error": "Não encontrado"}), 404


@app.route("/api/memory/events/<int:index>", methods=["DELETE"])
@require_auth
def delete_event(index):
    before = len(memory.campaign["events"])
    memory.campaign["events"] = [e for e in memory.campaign["events"] if e["index"] != index]
    if len(memory.campaign["events"]) == before:
        return jsonify({"error": "Não encontrado"}), 404
    memory.save_campaign()
    return jsonify({"ok": True})


@app.route("/api/memory/diary/<int:index>", methods=["PUT"])
@require_auth
def update_diary(index):
    data  = request.json
    diary = memory.campaign["diary"]
    if index < 0 or index >= len(diary):
        return jsonify({"error": "Não encontrado"}), 404
    diary[index].update({k: v for k, v in data.items() if k in diary[index]})
    memory.save_campaign()
    return jsonify({"ok": True})


@app.route("/api/memory/diary/<int:index>", methods=["DELETE"])
@require_auth
def delete_diary(index):
    diary = memory.campaign["diary"]
    if index < 0 or index >= len(diary):
        return jsonify({"error": "Não encontrado"}), 404
    diary.pop(index)
    memory.save_campaign()
    return jsonify({"ok": True})


@app.route("/api/memory/world", methods=["PUT"])
@require_auth
def update_world():
    data = request.json
    for field in ("chapter", "current_location", "current_scene", "story_summary"):
        if field in data:
            memory.campaign[field] = data[field]
    memory.save_campaign()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# COMBATE NA TELA (sem LLM) — wrappers finos sobre tools_dnd (motor fuzzado).
# require_auth já faz memory.bind_request(g.user_id) → isolado por usuário.
# ---------------------------------------------------------------------------

@app.route("/api/combat/state", methods=["GET"])
@require_auth
def combat_state_route():
    from rpg import tools_dnd
    return jsonify(tools_dnd.combat_snapshot())


@app.route("/api/combat/action", methods=["POST"])
@require_auth
def combat_action_route():
    from rpg import tools_dnd
    d = request.json or {}
    action = (d.get("action") or "").strip()
    if not action:
        return jsonify({"ok": False, "message": "Ação ausente."}), 400
    res = tools_dnd.combat_action(
        action,
        actor=(d.get("actor") or "").strip(),
        target=(d.get("target") or "").strip(),
        weapon=(d.get("weapon") or "").strip(),
        ability=(d.get("ability") or "").strip(),
        item=(d.get("item") or "").strip(),
    )
    return jsonify(res)


@app.route("/api/shop/state", methods=["GET"])
@require_auth
def shop_state_route():
    from rpg import tools_dnd
    return jsonify(tools_dnd.shop_snapshot(
        (request.args.get("loja") or "").strip(),
        (request.args.get("comprador") or "").strip(),
    ))


@app.route("/api/shop/action", methods=["POST"])
@require_auth
def shop_action_route():
    from rpg import tools_dnd
    d = request.json or {}
    action = (d.get("action") or "").strip()
    if not action:
        return jsonify({"ok": False, "message": "Ação ausente."}), 400
    return jsonify(tools_dnd.shop_action(
        action,
        shop=(d.get("shop") or "").strip(),
        char=(d.get("char") or "").strip(),
        item=(d.get("item") or "").strip(),
        quantity=d.get("quantity", 1),
    ))


@app.route("/api/combat/recap", methods=["GET"])
@require_auth
def combat_recap_route():
    from rpg import tools_dnd
    return jsonify({"text": tools_dnd.combat_recap_payload()})


@app.route("/api/combat/mode", methods=["GET", "POST"])
@require_auth
def combat_mode_route():
    if request.method == "GET":
        return jsonify({"mode": memory.campaign.get("combat_mode", "narrado")})
    mode = ((request.json or {}).get("mode") or "").strip().lower()
    if mode not in ("narrado", "tela"):
        return jsonify({"ok": False, "error": "mode inválido"}), 400
    memory.campaign["combat_mode"] = mode
    memory.save_campaign()
    return jsonify({"ok": True, "mode": mode})

# ---------------------------------------------------------------------------
# Inicialização
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 50)
    print("   RPG Agent — Interface Web")
    # Agora o print reflete que ele está aberto para a rede
    print("   Acesse: http://0.0.0.0:7777") 
    print("=" * 50)
    
    # O segredo está no host='0.0.0.0'
    app.run(host='0.0.0.0', debug=False, port=7777, threaded=True)