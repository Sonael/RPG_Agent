"""
memory.py
Estado da campanha (por sessão) e persistência via Supabase.

ARQUITETURA (multiusuário, sem estado global compartilhado):
  • Cada (user_id, campanha) tem seu próprio dict de campanha em `_STORE`.
  • Um ContextVar (`_active_key`) define qual campanha está ativa no
    contexto de execução atual (request Flask OU corrotina do agente).
  • `memory.campaign` é um PROXY que resolve para a campanha do contexto
    ativo — então tools, validator e endpoints continuam usando
    `memory.campaign[...]` sem saber que o estado é por sessão.

Vínculo de contexto:
  • server.start_session  → memory.bind(user_id, nome)         (cria/ativa)
  • require_auth (auth.py) → memory.bind_request(user_id)        (reativa)
  • chat()/run_agent       → memory.bind_request(user_id)        (na corrotina)
  • session/end            → memory.unbind(user_id)
"""

import json
import contextvars

# ---------------------------------------------------------------------------
# Estado por sessão — substitui o antigo dict global único
# ---------------------------------------------------------------------------

# session_key -> dict de campanha
_STORE: dict[str, dict] = {}
# session_key -> (user_id, campaign_name)
_META: dict[str, tuple] = {}
# user_id -> session_key atualmente ativo para aquele usuário
_ACTIVE_BY_USER: dict[str, str] = {}

# Chave da campanha ativa NO CONTEXTO atual (thread/corrotina-safe)
_active_key: "contextvars.ContextVar[str | None]" = contextvars.ContextVar(
    "rpg_active_campaign_key", default=None
)

_FALLBACK_KEY = "__no_session__"


def _session_key(user_id: str, campaign_name: str) -> str:
    return f"{user_id or '?'}::{campaign_name or '?'}"


def _active_campaign() -> dict:
    """Retorna o dict da campanha do contexto ativo (cria se necessário)."""
    key = _active_key.get() or _FALLBACK_KEY
    camp = _STORE.get(key)
    if camp is None:
        camp = _defaults()
        _STORE[key] = camp
    return camp


def bind(user_id: str, campaign_name: str) -> str:
    """
    Vincula o contexto atual à campanha (user_id, nome), criando o slot
    se ainda não existir. Marca como a campanha ativa do usuário.
    Chamado por server.start_session.
    """
    key = _session_key(user_id, campaign_name)
    _META[key] = (user_id, campaign_name)
    _ACTIVE_BY_USER[user_id] = key
    _STORE.setdefault(key, _defaults())
    # Descarta o slot transitório "__none__" (criado por bind_request quando
    # o usuário estava autenticado mas sem jogo) — evita acúmulo de memória.
    _STORE.pop(_session_key(user_id, "__none__"), None)
    _active_key.set(key)
    return key


def bind_request(user_id: str) -> str | None:
    """
    Reativa, no contexto atual, a campanha que o usuário tem aberta.
    Usado por require_auth e pela corrotina do agente — garante que cada
    request/execução opere na campanha do SEU usuário.
    """
    key = _ACTIVE_BY_USER.get(user_id)
    if key is None:
        # Usuário autenticado sem sessão de jogo ativa: usa um slot
        # próprio e vazio (nunca o de outro usuário).
        key = _session_key(user_id, "__none__")
        _STORE.setdefault(key, _defaults())
    _active_key.set(key)
    return key


def unbind(user_id: str) -> None:
    """Encerra a sessão de jogo do usuário: remove o slot da memória."""
    key = _ACTIVE_BY_USER.pop(user_id, None)
    if key:
        _STORE.pop(key, None)
        _META.pop(key, None)
    # Também descarta o slot transitório "__none__" do usuário, se houver.
    _STORE.pop(_session_key(user_id, "__none__"), None)
    _active_key.set(None)


def current_user_id() -> str | None:
    key = _active_key.get()
    return _META.get(key, (None, None))[0] if key else None


def current_campaign_name() -> str | None:
    key = _active_key.get()
    return _META.get(key, (None, None))[1] if key else None


# Compatibilidade de leitura: memory.CURRENT_USER_ID / memory.CAMPAIGN_NAME
# continuam funcionando, mas agora são DERIVADOS do contexto ativo
# (read-only — escrever neles não tem efeito; use bind()/unbind()).
def __getattr__(name: str):
    if name == "CURRENT_USER_ID":
        return current_user_id()
    if name == "CAMPAIGN_NAME":
        return current_campaign_name()
    raise AttributeError(f"module 'memory' has no attribute {name!r}")


# ---------------------------------------------------------------------------
# Proxy: memory.campaign → campanha do contexto ativo
# ---------------------------------------------------------------------------

class _CampaignProxy:
    """
    Faz `memory.campaign` se comportar como o dict da campanha ativa.
    Implementa o subconjunto do protocolo de dict usado no código.
    """
    def __getitem__(self, k):            return _active_campaign()[k]
    def __setitem__(self, k, v):         _active_campaign()[k] = v
    def __delitem__(self, k):            del _active_campaign()[k]
    def __contains__(self, k):           return k in _active_campaign()
    def __iter__(self):                  return iter(_active_campaign())
    def __len__(self):                   return len(_active_campaign())
    def __bool__(self):                  return bool(_active_campaign())
    def __eq__(self, other):             return _active_campaign() == other
    def get(self, k, d=None):            return _active_campaign().get(k, d)
    def setdefault(self, k, d=None):     return _active_campaign().setdefault(k, d)
    def pop(self, *a):                   return _active_campaign().pop(*a)
    def update(self, *a, **k):           return _active_campaign().update(*a, **k)
    def keys(self):                      return _active_campaign().keys()
    def values(self):                    return _active_campaign().values()
    def items(self):                     return _active_campaign().items()
    def clear(self):                     return _active_campaign().clear()
    def copy(self):                      return _active_campaign().copy()
    def __repr__(self):                  return f"<CampaignProxy {self.get('name','?')!r}>"


# `campaign` agora é um proxy resolvido por contexto (não um dict global).
campaign = _CampaignProxy()


def _defaults() -> dict:
    return {
        "name":                 "",
        "campaign_type":        "fantasia",
        "dnd_mode":             False,   # True quando o estilo for "dnd"
        "protagonist":          "",      # Nome do personagem principal do jogador
        "characters":           {},
        "locations":            {},
        "events":               [],
        "conversation_history": [],
        "story_summary":        "",
        "current_scene":        "",
        "current_location":     "",
        "chapter":              1,
        "quest_flags":          {},
        "party":                [],
        "diary":                [],
        # "narrado" = LLM narra turno a turno (padrão, comportamento atual).
        # "tela"    = combate resolvido na tela tática; LLM só emoldura.
        "combat_mode":          "narrado",
        "combat_state": {
            "is_active":           False,
            "initiative_order":    [],
            "current_turn_index":  0,
            "round":               1,
            "turn_resolved":       False,  # True após attack_roll/use_ability; False ao chamar next_turn
            "npc_strategies":      {},
            "turn_auto_advanced":  False,
            # Token monotônico: +1 a cada avanço REAL de turno. Base da
            # idempotência (impede duplo-avanço) e dos invariantes de teste.
            "turn_token":          0,
            # Log estruturado de eventos do combate (para a tela tática e
            # para a narração final da LLM). Limitado a _MAX_COMBAT_LOG.
            "log":                 [],
            # Resultado do último combate (painel de fim na tela). None = nenhum.
            "result":              None,
            # Economia de ações DO TURNO ATUAL (regra 5e).
            # Resetada a cada avanço de turno. Em 5e cada turno tem 1 Ação +
            # 1 Ação Bônus + 1 Reação. A tela tática rastreia Ação/Bônus.
            "turn_economy":        {"acao_usada": False, "bonus_usada": False},
        },
    }


def _migrate_sheet_fields(char: dict) -> None:
    """
    Garante que fichas antigas (salvas antes da v2) tenham todos os campos
    novos com valores padrão. Chamado automaticamente após load_campaign.
    Nunca sobrescreve valores já existentes.
    """
    sheet = char.get("sheet")
    if sheet is None:
        return

    defaults_v2 = {
        "ouro":                 0,
        "prata":                0,
        "cobre":                0,
        "equipamentos":         {"armadura": None, "escudo": None, "arma_principal": None, "amuleto": None},
        "condicoes":            [],
        "death_saves_sucessos": 0,
        "death_saves_falhas":   0,
    }

    for key, default_val in defaults_v2.items():
        if key not in sheet:
            # Copiar para evitar objetos mutáveis compartilhados
            import copy
            sheet[key] = copy.deepcopy(default_val)


def _migrate_combat_state() -> None:
    """
    Garante que campanhas antigas tenham o campo combat_state com estrutura completa.
    """
    defaults = {
        "is_active":          False,
        "initiative_order":   [],
        "current_turn_index": 0,
        "round":              1,
        "turn_resolved":      False,
        "npc_strategies":     {},
        "turn_auto_advanced": False,
        "turn_token":         0,
        "log":                [],
        "result":             None,
        "turn_economy":       {"acao_usada": False, "bonus_usada": False},
    }
    cs = campaign.setdefault("combat_state", {})
    for key, val in defaults.items():
        if key not in cs:
            cs[key] = val
    # Campanhas antigas sem o modo de combate → padrão narrado.
    if "combat_mode" not in campaign:
        campaign["combat_mode"] = "narrado"


_SPELL_PLACEHOLDER = "Magia inicial da classe. Use learn_spell() para enriquecer com dados do Open5e."

def _migrate_spell_descriptions() -> None:
    """
    Substitui descrições placeholder de magias iniciais pelos dados reais de
    DEFAULT_SPELLS_BY_CLASS. Roda automaticamente ao carregar a campanha,
    corrigindo personagens criados antes da correção do wizard.
    """
    try:
        from tools_dnd import DEFAULT_SPELLS_BY_CLASS
    except ImportError:
        return  # ferramentas não disponíveis ainda

    for char in campaign.get("characters", {}).values():
        sheet = char.get("sheet")
        if not sheet:
            continue
        classe = sheet.get("classe", "").lower()
        spell_pool = DEFAULT_SPELLS_BY_CLASS.get(classe, [])
        if not spell_pool:
            continue
        # Índice nome→dados para lookup rápido
        spell_map = {s["nome"].lower(): s for s in spell_pool}

        for hab in char.get("habilidades", []):
            if hab.get("descricao") != _SPELL_PLACEHOLDER:
                continue
            data = spell_map.get(hab.get("nome", "").lower())
            if data:
                hab["descricao"]  = data["descricao"]
                hab["custo_mana"] = data["custo_mana"]
                hab["dado"]       = data.get("dado", hab.get("dado", ""))


def char_key(name: str) -> str:
    """
    Normaliza o nome de um personagem para uso como chave no dict `characters`.
    Garante que 'Bandido Raso', 'bandido raso', 'Bandido_Raso' e '  Bandido Raso  '
    sejam sempre tratados como a mesma chave — eliminando duplicatas e KeyErrors.
    """
    return name.lower().strip().replace("_", " ")


def is_party_member(char: dict) -> bool:
    """
    Definição ÚNICA e canônica de "pertence ao grupo do jogador".
    Usada por server.py (rede de level-up / verificação de XP) e
    tools_dnd.py (recrutamento / turno de NPC) para evitar três
    definições divergentes de grupo espalhadas pelo código.

    Um personagem é do grupo se QUALQUER um for verdadeiro:
      • char["party_member"] == True  (recrutado via recruit_character)
      • char["name"] == campaign["protagonist"]  (personagem principal)
      • o nome está em campaign["party"]  (add_party_member)

    Não filtra por status (morto/fugiu) — cada chamador aplica o
    filtro de status que precisar.
    """
    if not isinstance(char, dict):
        return False
    if char.get("party_member"):
        return True
    name_norm = (char.get("name") or "").lower().strip()
    if not name_norm:
        return False
    protagonist = (campaign.get("protagonist") or "").lower().strip()
    if protagonist and name_norm == protagonist:
        return True
    for m in campaign.get("party", []):
        if (m.get("name") or "").lower().strip() == name_norm:
            return True
    return False


def reset_campaign() -> None:
    """Reseta o estado para os valores padrão."""
    campaign.clear()
    campaign.update(_defaults())


def load_campaign() -> bool:
    """
    Carrega a campanha ativa do Supabase para o dict em memória.
    Usa CURRENT_USER_ID e CAMPAIGN_NAME definidos pelo server.py.
    Retorna True se a campanha contém dados (não é nova).
    """
    import database

    uid  = current_user_id()
    name = current_campaign_name()
    if not uid or not name:
        reset_campaign()
        return False

    try:
        data = database.get_campaign(uid, name)

        if data is None:
            # Campanha nova — ainda não existe no banco
            reset_campaign()
            campaign["name"] = name
            return False

        defaults = _defaults()
        reset_campaign()

        for key, default_val in defaults.items():
            loaded = data.get(key, default_val)
            if isinstance(default_val, dict):
                # Um campo gravado como null no banco viria como None e
                # quebraria .update(None), abortando TODA a carga (e resetando
                # a campanha). Ignora valores de tipo inesperado.
                if isinstance(loaded, dict):
                    campaign[key].update(loaded)
            elif isinstance(default_val, list):
                if isinstance(loaded, list):
                    campaign[key].extend(loaded)
            else:
                campaign[key] = loaded if loaded is not None else default_val

        # Garante que o nome está sempre preenchido
        campaign["name"] = name

        chars = len(campaign["characters"])
        locs  = len(campaign["locations"])
        evts  = len(campaign["events"])
        diary = len(campaign["diary"])
        hist  = len(campaign["conversation_history"])

        # Migra fichas antigas para incluir campos da v2 (ouro, condições, etc.)
        for char in campaign["characters"].values():
            _migrate_sheet_fields(char)

        # Migra estrutura de estado de combate para campanhas antigas
        _migrate_combat_state()

        # Substitui descrições placeholder de magias pelos dados reais
        _migrate_spell_descriptions()

        print(
            f"Campanha carregada: {chars} personagens, {locs} locais, "
            f"{evts} eventos, {diary} entradas no diário, {hist} falas no histórico."
        )

        return hist > 0 or chars > 0 or locs > 0 or evts > 0

    except Exception as e:
        print(f"Aviso: erro ao carregar campanha ({e}). Iniciando do zero.")
        reset_campaign()
        campaign["name"] = name or ""
        return False


MAX_HISTORY_SAVED = 200

def save_campaign() -> None:
    """
    Persiste o estado da campanha no Supabase com as travas de segurança originais.
    """
    import database

    # TRAVA 1: Só salva se tiver nome definido
    if not campaign or not campaign.get("name"):
        print("⚠️ [ALERTA] Tentativa de salvar abortada: Memória sem nome de campanha.")
        return

    # TRAVA 2: Protege contra sobrescrever dados existentes com memória vazia
    uid  = current_user_id()
    name = current_campaign_name()
    if uid and name:
        try:
            existing = database.get_campaign(uid, name)
            if existing:
                has_history = len(campaign.get("conversation_history", [])) > 0
                has_summary = len(campaign.get("story_summary", "")) > 0
                has_chars   = len(campaign.get("characters", {})) > 0
                if not has_history and not has_summary and not has_chars:
                    print(f"⚠️ [PROTEÇÃO] Bloqueado sobrescrever '{campaign['name']}' com dados vazios.")
                    return
        except Exception:
            pass  # Se não conseguir checar, deixa salvar

    # Limita o histórico
    hist = campaign.get("conversation_history", [])
    if len(hist) > MAX_HISTORY_SAVED:
        campaign["conversation_history"] = hist[-MAX_HISTORY_SAVED:]

    if not uid or not name:
        print("⚠️ [ALERTA] Save abortado: contexto de sessão não vinculado.")
        return

    try:
        database.save_campaign(uid, name, dict(campaign))
        print(f"✅ Campanha '{campaign['name']}' persistida no Supabase.")
    except Exception as e:
        print(f"❌ Erro crítico ao salvar no Supabase: {e}")


def export_diary_md() -> str:
    """
    Exporta o diário como string Markdown.
    Retorna o conteúdo (não salva em disco — o server.py envia como download).
    """
    lines = [f"# Diário de Campanha — {campaign.get('name', 'Sem título')}\n"]
    if not campaign.get("diary"):
        lines.append("_Nenhuma entrada no diário ainda._")
    else:
        for entry in campaign["diary"]:
            lines.append(
                f"## Capítulo {entry.get('chapter', '?')} — {entry.get('title', 'Sem título')}"
            )
            lines.append(entry.get("content", ""))
            lines.append("")
    return "\n".join(lines)