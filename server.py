"""
server.py
Backend Flask do RPG Agent.
Execute com: python server.py
Acesse em:  http://localhost:5000
"""

import asyncio
import json
import queue
import re
import threading
import time
import os

from flask import Flask, Response, g, jsonify, request, send_from_directory, stream_with_context
from google.genai import types as gtypes

import memory
import database
from auth import require_auth, register as auth_register, login as auth_login, refresh_session
from agent import create_agent, get_campaign_config
from session import APP_NAME, USER_ID, SESSION_ID, create_runner
from validator import validate


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


def _verify_agent_response(
    text: str,
    tools_called: set,
    combat_was_active: bool,
) -> list[str]:
    """
    Verifica se o agente narrou eventos mecânicos sem chamar as ferramentas.
    Só atua em campanhas com dnd_mode=True.
    Retorna lista de strings descrevendo cada violação encontrada.
    """
    if not memory.campaign.get("dnd_mode", False):
        return []

    violations = []

    # 1. Início de combate sem roll_initiative
    if (not combat_was_active
            and not _INIT_TOOLS.intersection(tools_called)
            and _COMBAT_START_RE.search(text)):
        violations.append(
            "Narrou início de combate ('rodada 1', 'iniciativa rolada', etc.) "
            "sem chamar roll_initiative(). Chame a ferramenta com TODOS os participantes."
        )

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

    # 7. end_combat() chamado sem grant_xp() para os membros do grupo
    if ("end_combat" in tools_called and not _XP_TOOLS.intersection(tools_called)):
        party = [
            c["name"]
            for c in memory.campaign.get("characters", {}).values()
            if (
                c.get("sheet", {}).get("classe", "").lower() != "npc"
                or c.get("party_member")
            ) and c.get("status") not in ("morto", "fugiu")
        ]
        if party:
            names = ", ".join(party)
            violations.append(
                f"Encerrou o combate com end_combat() mas não chamou grant_xp() "
                f"para nenhum membro do grupo. "
                f"Chame grant_xp() para CADA personagem jogável: {names}. "
                f"Use o XP adequado ao inimigo derrotado (25–2000 XP conforme a tabela)."
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
    from tools_dnd import XP_THRESHOLDS, _proficiency_bonus, _apply_class_features, CLASS_DATA
    import random

    if not memory.campaign.get("dnd_mode", False):
        return []

    leveled = []
    party_keys = {m.get("name", "").lower().strip() for m in memory.campaign.get("party", [])}

    for key, char in memory.campaign.get("characters", {}).items():
        # Só verifica membros do grupo
        if key not in party_keys:
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

            mana_stat      = info.get("mana_stat")
            mana_per_level = info.get("mana_per_level", 0)
            if mana_stat and mana_per_level > 0:
                sheet["mana_max"]  += mana_per_level
                sheet["mana_atual"] = sheet["mana_max"]

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
    stateful = {"attack_roll", "modify_hp", "use_ability", "modify_mana",
                "roll_initiative", "apply_condition", "learn_spell", "learn_ability",
                "grant_xp", "set_flag", "clear_flag"}
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
# CORS (aplicação local, qualquer origem)
# ---------------------------------------------------------------------------

@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        resp = app.make_default_options_response()
        resp.headers.update({
            "Access-Control-Allow-Origin":  "*",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
        })
        return resp

@app.after_request
def add_cors(resp):
    resp.headers.update({
        "Access-Control-Allow-Origin":  "*",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
    })
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
    try:
        result = auth_register(email, password)

        # Se voltou com token, conta criada e confirmada imediatamente
        if result.get("access_token"):
            return jsonify({"ok": True, "needs_confirmation": False, **result})

        # access_token é null: pode ser conta nova (aguarda confirmação)
        # OU email duplicado. Tentamos login para distinguir os dois casos.
        try:
            auth_login(email, password)
            # Login OK → email já está cadastrado e confirmado
            return jsonify({"error": "Este email já está cadastrado. Faça login."}), 400
        except Exception as login_err:
            login_msg = str(login_err).lower()
            if any(w in login_msg for w in ["confirm", "verified", "not confirmed", "email"]):
                # Conta nova, aguardando clique no link de confirmação
                return jsonify({"ok": True, "needs_confirmation": True, **result})
            elif any(w in login_msg for w in ["invalid", "credentials", "password", "wrong"]):
                # Email já existe mas com senha diferente
                return jsonify({"error": "Este email já está cadastrado. Faça login ou recupere sua senha."}), 400
            else:
                # Caso inesperado: assume confirmação pendente
                return jsonify({"ok": True, "needs_confirmation": True, **result})

    except Exception as e:
        err = str(e).lower()
        if any(w in err for w in ["already", "registered", "exists", "unique"]):
            return jsonify({"error": "Este email já está cadastrado. Faça login."}), 400
        return jsonify({"error": str(e)}), 400


@app.route("/api/auth/confirm", methods=["POST"])
def confirm_email():
    """
    Recebe o access_token que o Supabase coloca no hash da URL de confirmação
    e devolve ok=True para o frontend salvar a sessão.
    """
    data          = request.json or {}
    access_token  = data.get("access_token", "")
    if not access_token:
        return jsonify({"error": "Token ausente."}), 400
    # O token já foi validado pelo Supabase — apenas o retornamos confirmado
    return jsonify({"ok": True, "access_token": access_token})


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.json or {}
    email    = data.get("email", "").strip()
    password = data.get("password", "")
    if not email or not password:
        return jsonify({"error": "Email e senha são obrigatórios."}), 400
    try:
        result = auth_login(email, password)
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 401
    
@app.route("/api/auth/refresh", methods=["POST"])
def refresh_token():
    """
    Rota chamada silenciosamente pelo frontend para renovar o JWT expirado.
    """
    data = request.json or {}
    token = data.get("refresh_token")
    
    if not token:
        return jsonify({"error": "Refresh token ausente."}), 400
        
    try:
        # Chama a função que acabamos de criar no auth.py
        result = refresh_session(token)
        return jsonify({"ok": True, **result})
    except Exception as e:
        # Retorna 401 para que o frontend saiba que a renovação falhou de vez
        return jsonify({"error": str(e)}), 401

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
    raw_chars = campaign_data.get("characters", {})
    normalized_chars = {}
    for k, v in raw_chars.items():
        char = dict(v)
        if char.get("sheet") and isinstance(char["sheet"].get("classe"), str):
            char["sheet"] = dict(char["sheet"])
            char["sheet"]["classe"] = char["sheet"]["classe"].lower()
        normalized_chars[k.lower().strip().replace("_", " ")] = char

    payload = {
        "name":                 name,
        "campaign_type":        campaign_data.get("campaign_type", "fantasia"),
        "dnd_mode":             campaign_data.get("dnd_mode", False),
        "protagonist":          campaign_data.get("protagonist", ""),
        "chapter":              campaign_data.get("chapter", 1),
        "current_location":     campaign_data.get("current_location", ""),
        "current_scene":        campaign_data.get("current_scene", ""),
        "story_summary":        campaign_data.get("story_summary", ""),
        "quest_flags":          campaign_data.get("quest_flags", {}),
        "party":                campaign_data.get("party", []),
        "characters":           normalized_chars,
        "locations":            campaign_data.get("locations", {}),
        "events":               campaign_data.get("events", []),
        "diary":                campaign_data.get("diary", []),
        "conversation_history": [],
        "combat_state":         campaign_data.get("combat_state", {
            "is_active": False, "initiative_order": [],
            "current_turn_index": 0, "round": 1,
        }),
    }

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
        "characters":       campaign_data.get("characters", existing.get("characters", {})),
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
    from tools_dnd import _CLASS_SLUG_MAP, SPELL_MANA_COST, DEFAULT_SPELLS_BY_CLASS
    import requests as _req

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
    import requests as _req

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
    import requests as _req

    q = request.args.get("q", "").strip()
    if not q or len(q) < 2:
        return jsonify({"ok": True, "monsters": []})

    def parse_monster(m):
        ac_raw = m.get("armor_class", 10)
        if isinstance(ac_raw, list):
            ca = ac_raw[0].get("value", 10) if ac_raw else 10
        else:
            ca = int(ac_raw or 10)

        # Extrai arma principal (primeiro ataque corpo-a-corpo) e arma secundária
        # (primeiro ataque à distância) das ações do monstro.
        arma_principal  = ""
        arma_secundaria = ""
        arma_dado       = ""  # dado de dano da arma principal (ex: "1d6")
        for action in (m.get("actions") or []):
            desc = (action.get("desc") or "").lower()
            name = action.get("name") or ""
            if not name:
                continue
            is_melee  = "melee weapon attack"  in desc or "melee attack" in desc
            is_ranged = "ranged weapon attack" in desc or "ranged attack" in desc
            # Extrai dado de dano do campo damage_dice ou da descrição
            dado = action.get("damage_dice", "")
            if not dado:
                m_dado = re.search(r'(\d+d\d+)', desc)
                dado = m_dado.group(1) if m_dado else ""
            if is_melee and not arma_principal:
                arma_principal = name.lower()
                arma_dado = dado
            elif is_ranged and not arma_secundaria:
                arma_secundaria = name.lower()
            if arma_principal and arma_secundaria:
                break

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
            "arma_principal": arma_principal,
            "arma_secundaria":arma_secundaria,
            "arma_dado":      arma_dado,
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
    from tools_dnd import CLASS_LEVEL_FEATURES, CLASS_FEATURE_DESCS

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


# No server.py — Dicionário completo com 8 modelos
# No server.py — Dicionário completo e corrigido (8 modelos)
MODEL_LIMITS = {
    # Família Gemini 3.x
    "gemini-3.1-flash-lite-preview": {"rpd": 500,   "rpm": 15},
    "gemini-3-flash":                {"rpd": 20,    "rpm": 5},
    "gemini-3.1-flash-tts":          {"rpd": 10,    "rpm": 3},

    # Família Gemini 2.5
    "gemini-2.5-flash":              {"rpd": 20,    "rpm": 5},
    "gemini-2.5-flash-lite":         {"rpd": 20,    "rpm": 10},

    # Família Gemma (IDs técnicos com -it
    "gemma-3-27b-it":                {"rpd": 14400, "rpm": 30},
    "gemma-4-26b-it":                {"rpd": 1500,  "rpm": 15},
    "gemma-4-31b-it":                {"rpd": 1500,  "rpm": 15},
    
    "default":                       {"rpd": 500,   "rpm": 15}
}

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

    # Define identidade da sessão no memory
    memory.CURRENT_USER_ID = user_id
    memory.CAMPAIGN_NAME   = campaign_name
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

    agent = create_agent(model, campaign_type)
    runner, session_service = create_runner(agent)
    run_async(session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID
    ))

    _sessions[user_id] = {
    "runner":          runner,
    "session_service": session_service,
    "is_ollama":       is_ollama,
    "model_id":        model_id,  # ADICIONE ESTA LINHA AQUI
    }

    if has_history:
        opening      = _build_recap()
        opening_type = "recap"
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


def _build_recap() -> str:
    from tools import get_full_context
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

    async def run_agent(texto: str):
        import random
        msg          = gtypes.Content(role="user", parts=[gtypes.Part(text=texto)])
        MAX_RETRIES  = 5

        for attempt in range(MAX_RETRIES):
            full         = ""
            tools_called = set()
            try:
                async for event in runner.run_async(
                    user_id=USER_ID, session_id=SESSION_ID, new_message=msg
                ):
                    if event.content and event.content.parts:
                        for part in event.content.parts:
                            fc = getattr(part, "function_call", None)
                            if fc and getattr(fc, "name", None):
                                name = fc.name
                                args = dict(fc.args) if fc.args else {}
                                kind = "write" if name in WRITE_TOOLS else "read"
                                tools_called.add(name)
                                result_q.put(("tool_call", {"name": name, "args": args, "kind": kind}))

                            fr = getattr(part, "function_response", None)
                            if fr and getattr(fr, "name", None):
                                resp_dict = dict(fr.response) if fr.response else {}
                                conteudo  = resp_dict.get("result", "")
                                if conteudo:
                                    result_q.put(("tool_result", {"tool_name": fr.name, "content": str(conteudo)}))

                    if event.usage_metadata:
                        usage = {
                            "prompt_tokens":     event.usage_metadata.prompt_token_count,
                            "candidates_tokens": event.usage_metadata.candidates_token_count,
                            "total_tokens":      event.usage_metadata.total_token_count,
                        }
                        result_q.put(("quota_update", usage))

                    if event.is_final_response() and event.content and event.content.parts:
                        for part in event.content.parts:
                            if part.text and not getattr(part, "thought", False):
                                full += part.text

                if not full.strip():
                    full = "*(O Mestre observa os registros em silêncio por um momento, parecendo organizar as memórias da aventura...)*"

                result_q.put(("done", {
                    "text":              full,
                    "tools_called":      tools_called,
                    "combat_was_active": _combat_was_active,
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

                    # ── Loop de verificação pós-resposta ──────────────────
                    if not correction_attempted:
                        mech_violations = _verify_agent_response(
                            response_text, tools_called, combat_was_active
                        )
                        if mech_violations:
                            correction_attempted = True
                            correction_prompt    = _build_correction_prompt(mech_violations, tools_called)

                            print(f"[VERIFICADOR] {len(mech_violations)} violação(ões) — re-injetando correção.")
                            for v in mech_violations:
                                print(f"  • {v}")

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
    
    # Schema D&D: inclui tipo (jogador/aliado/inimigo) e classe apenas para PCs
    char_schema = (
        '{"name":"","description":"","traits":"","notes":"","role":"",'
        '"tipo":"<jogador|aliado|inimigo>",'
        '"classe":"<bárbaro|guerreiro|paladino|patrulheiro|bardo|clérigo|druida|monge|ladino|mago|feiticeiro|bruxo|npc>",'
        '"raca":"<humano|elfo|anão|halfling|draconato|meio-elfo|tiferino|goblin|orc|draconato|outro>"}'
        if is_dnd else
        '{"name":"","description":"","traits":"","notes":"","role":"","tipo":"<jogador|aliado|inimigo>"}'
    )
    char_tip = (
        'Para D&D use o campo "tipo" para classificar cada personagem: '
        '"jogador" = herói/aventureiro com classe PC (bárbaro, guerreiro, mago, etc.); '
        '"aliado" = NPC amigável sem classe PC (use classe "npc"); '
        '"inimigo" = monstro ou antagonista sem classe PC (use classe "npc", raça pode ser goblin/orc/outro). '
        "Apenas personagens do tipo jogador devem ter classes de PC. "
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

    payload = {
        "name":                 name,
        "campaign_type":        campaign_data.get("campaign_type", "fantasia"),
        "dnd_mode":             campaign_data.get("dnd_mode", False),
        "protagonist":          campaign_data.get("protagonist", ""),
        "chapter":              campaign_data.get("chapter", 1),
        "current_location":     campaign_data.get("current_location", ""),
        "current_scene":        campaign_data.get("current_scene", ""),
        "story_summary":        campaign_data.get("story_summary", ""),
        "quest_flags":          campaign_data.get("quest_flags", {}),
        "party":                campaign_data.get("party", []),
        "characters":           normalized_chars,
        "locations":            campaign_data.get("locations", {}),
        "events":               campaign_data.get("events", []),
        "diary":                campaign_data.get("diary", []),
        "conversation_history": [],
        "combat_state":         campaign_data.get("combat_state", {
            "is_active": False, "initiative_order": [],
            "current_turn_index": 0, "round": 1,
        }),
    }

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
    memory.reset_campaign()
    memory.CURRENT_USER_ID = None
    memory.CAMPAIGN_NAME   = None
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