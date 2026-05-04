"""
server.py
Backend Flask do RPG Agent.
Execute com: python server.py
Acesse em:  http://localhost:5000
"""

import asyncio
import json
import queue
import threading
import time
import os

from flask import Flask, Response, g, jsonify, request, send_from_directory, stream_with_context
from google.genai import types as gtypes

import memory
import database
from auth import require_auth, register as auth_register, login as auth_login
from agent import create_agent, get_campaign_config
from session import APP_NAME, USER_ID, SESSION_ID, create_runner
from validator import validate

app = Flask(__name__, static_folder="static")

# ---------------------------------------------------------------------------
# Asyncio bridge — loop dedicado rodando em thread daemon
# ---------------------------------------------------------------------------

_loop = asyncio.new_event_loop()
threading.Thread(target=_loop.run_forever, daemon=True, name="adk-loop").start()

def run_async(coro):
    """Submete coroutine ao loop dedicado e aguarda resultado (bloqueante)."""
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout=120)

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
    return send_from_directory("static", "menu.html")

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
    return (
        "Estamos retomando uma aventura em andamento. "
        "Abaixo está o estado completo do mundo e o histórico recente.\n\n"
        f"{contexto}\n\n"
        f"--- HISTÓRICO RECENTE ---\n{chr(10).join(lines)}\n\n"
        "Faça um breve recap ao jogador do ponto em que estávamos "
        "e aguarde a próxima ação dele para continuar a narrativa."
    )

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

    async def run_agent():
        import random
        msg = gtypes.Content(role="user", parts=[gtypes.Part(text=texto_agente)])
        
        # Aumentamos o limite para sobreviver a picos de tráfego na API
        MAX_RETRIES = 5 

        for attempt in range(MAX_RETRIES):
            full = ""
            try:
                async for event in runner.run_async(
                    user_id=USER_ID, session_id=SESSION_ID, new_message=msg
                ):
                    # Captura de chamadas de ferramentas (tool_calls)
                    if event.content and event.content.parts:
                        for part in event.content.parts:
                            fc = getattr(part, "function_call", None)
                            if fc and getattr(fc, "name", None):
                                name = fc.name
                                args = dict(fc.args) if fc.args else {}
                                kind = "write" if name in WRITE_TOOLS else "read"
                                result_q.put(("tool_call", {"name": name, "args": args, "kind": kind}))
                                
                    # Atualização de cota/tokens
                    if event.usage_metadata:
                        usage = {
                            "prompt_tokens": event.usage_metadata.prompt_token_count,
                            "candidates_tokens": event.usage_metadata.candidates_token_count,
                            "total_tokens": event.usage_metadata.total_token_count
                        }
                        result_q.put(("quota_update", usage))
                        
                    # Captura do texto final com filtragem de pensamentos nativos (ADK/DeepSeek/Gemini Thinking)
                    if event.is_final_response() and event.content and event.content.parts:
                        for part in event.content.parts:
                            if part.text and not getattr(part, 'thought', False):
                                full += part.text

                # Proteção contra vácuo: Se o modelo não falar nada, enviamos uma ação narrativa
                if not full.strip():
                    full = "*(O Mestre observa os registros em silêncio por um momento, parecendo organizar as memórias da aventura...)*"

                result_q.put(("done", full))
                return

            except Exception as exc:
                err = str(exc).lower()
                # Adicionamos 'deadline', '500' e '504' que ocorrem muito no Free Tier
                is_retryable = any(k in err for k in (
                    "overloaded", "429", "503", "500", "504", 
                    "rate limit", "quota", "resource exhausted", "deadline"
                ))
                
                if is_retryable and attempt < MAX_RETRIES - 1:
                    # Cálculo: 2s, 4s, 8s, 16s... + um pequeno aleatório (jitter) para evitar colisões
                    wait = (2 ** (attempt + 1)) + random.uniform(0, 1)
                    
                    result_q.put(("retrying", f"Mestre ocupado (Tentativa {attempt + 1}/{MAX_RETRIES}). Retomando em {wait:.1f}s..."))
                    await asyncio.sleep(wait)
                else:
                    # Se esgotar as tentativas ou for um erro crítico (como chave inválida)
                    result_q.put(("error", f"O RPG AGENT silenciou: {str(exc)}"))
                    return

    # Inicia a thread e atrela um "capturador de desastres" a ela
    future = asyncio.run_coroutine_threadsafe(run_agent(), _loop)

    def on_thread_done(fut):
        try:
            fut.result() # Se a thread explodiu, o erro será revelado aqui
        except Exception as e:
            result_q.put(("error", f"Erro fatal interno na thread da IA: {e}"))

    future.add_done_callback(on_thread_done)

    def generate():
        while True:
            try:
                # O try/except queue.Empty garante que erros de timeout não quebrem o servidor
                kind, content = result_q.get(timeout=120)
                
                if kind == "retrying":
                    # Envia atualização de tentativa do backoff exponencial para o frontend
                    yield f"data: {json.dumps({'type': 'retrying', 'content': content})}\n\n"

                elif kind == "tool_call":
                    # Registra a chamada de ferramenta (leitura ou escrita)
                    yield f"data: {json.dumps({'type': 'tool_call', 'tool': content})}\n\n"

                elif kind == "quota_update":
                    # NOVIDADE: Envia os dados de consumo de tokens (RPM/TPM) para o painel de métricas
                    yield f"data: {json.dumps({'type': 'quota', 'content': content})}\n\n"

                elif kind == "error":
                    # Reporta erro fatal e encerra o stream SSE[cite: 5]
                    yield f"data: {json.dumps({'type': 'error', 'content': content})}\n\n"
                    return

                elif kind == "done":
                    # Processamento final ao concluir a resposta da IA[cite: 5]
                    if registrar and content:
                        memory.campaign["conversation_history"].append({"role": "assistant", "text": content})
                        memory.save_campaign()

                    # Executa a validação de fidelidade narrativa e regras[cite: 5]
                    result = validate(content)
                    violations = [
                        {"severity": v.severity, "rule": v.rule, "message": v.message, "detail": v.detail}
                        for v in result.violations
                    ]

                    # Envia o texto final da resposta[cite: 5]
                    yield f"data: {json.dumps({'type': 'text', 'content': content})}\n\n"

                    # Se houver violações de validação, envia-as logo em seguida[cite: 5]
                    if violations:
                        yield f"data: {json.dumps({'type': 'violations', 'violations': violations})}\n\n"

                    # Sinaliza ao frontend que o stream terminou com sucesso[cite: 5]
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    return

            except queue.Empty:
                # Tratamento de timeout caso a thread da IA trave ou demore demais[cite: 5]
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
    c = memory.campaign
    ct = c.get("campaign_type", "fantasia")
    return jsonify({
        "campaign_type":    ct,
        "campaign_config":  get_campaign_config(ct),
        "chapter":          c.get("chapter", 1),
        "current_location": c.get("current_location", ""),
        "current_scene":    c.get("current_scene", ""),
        "story_summary":    c.get("story_summary", ""),
        "quest_flags":      c.get("quest_flags", {}),
        "party":            c.get("party", []),
        "characters":       list(c.get("characters", {}).values()),
        "locations":        list(c.get("locations", {}).values()),
        "events":           c.get("events", []),
        "diary":            c.get("diary", []),
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

    payload = {
        "name":                 name,
        "campaign_type":        campaign_data.get("campaign_type", "fantasia"),
        "chapter":              campaign_data.get("chapter", 1),
        "current_location":     campaign_data.get("current_location", ""),
        "current_scene":        campaign_data.get("current_scene", ""),
        "story_summary":        campaign_data.get("story_summary", ""),
        "quest_flags":          campaign_data.get("quest_flags", {}),
        "party":                campaign_data.get("party", []),
        "characters":           campaign_data.get("characters", {}),
        "locations":            campaign_data.get("locations", {}),
        "events":               campaign_data.get("events", []),
        "diary":                campaign_data.get("diary", []),
        "conversation_history": [],
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