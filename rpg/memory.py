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

import contextlib
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

# ---------------------------------------------------------------------------
# Gravação adiada — uma ida ao banco por turno, não sete
# ---------------------------------------------------------------------------
# Cada ferramenta do motor chama save_campaign() quando termina, e um turno
# normal aciona várias: um turno com cinco ações gravava SETE vezes, 169 KB
# cada, e cada gravação ainda lia a campanha antes (a trava contra sobrescrever
# com memória vazia). Eram catorze idas à rede dentro do tempo de resposta do
# jogador, todas para o MESMO documento, que só a última versão importa.
#
# Com o adiamento, as ferramentas continuam chamando save_campaign() — nada
# muda para quem escreve motor — mas a escrita de verdade acontece UMA vez, no
# fim do turno.
#
# As duas marcas são por CHAVE DE SESSÃO e moram no módulo, não num
# ContextVar: as ferramentas rodam na thread do agente, e um ContextVar
# copiado para lá não devolveria a marca para quem fecha o escopo.
_ADIADAS: set[str] = set()      # sessões com gravação adiada agora
_SUJAS: set[str] = set()        # sessões com mudança esperando flush
# session_key -> versão da campanha que ESTA sessão leu do banco. É o que
# permite descobrir que outra aba gravou por cima (ver database.CAMPO_VERSAO).
_VERSAO: dict[str, int] = {}


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
        # A versão lida morre com a sessão. Sem isto, a sessão seguinte
        # começaria achando que está numa versão que não leu — e a primeira
        # gravação dela pareceria um conflito que não houve.
        _VERSAO.pop(key, None)
        _SUJAS.discard(key)
        _ADIADAS.discard(key)
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

# Onde o relógio do mundo começa: manhã do primeiro dia. Toda campanha tem
# hora desde o primeiro turno; o mestre move daí com advance_time().
RELOGIO_INICIAL = {"dia": 1, "hora": 8}


def _defaults() -> dict:
    return {
        "name":                 "",
        "campaign_type":        "fantasia",
        # Regras e gênero são coisas diferentes: dnd_mode liga fichas,
        # combate tático e as telas de regra; campaign_type é o GÊNERO (o
        # tom do mundo). "dnd" já foi um valor de campaign_type — ver
        # regras_e_genero.
        "dnd_mode":             False,
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
        # ── Onda 4 ────────────────────────────────────────────────────────
        # Estas chaves PRECISAM estar aqui, e não é detalhe de organização:
        # load_campaign() percorre _defaults() e copia só as chaves que
        # encontra nele. O que não estiver aqui é gravado no banco e
        # DESCARTADO na leitura seguinte — foi o que aconteceu com missões,
        # relógio e lojas até esta correção.
        #
        # A hora do mundo existe desde o primeiro turno (_migrate_relogio):
        # antes ela só nascia no primeiro advance_time(), e até lá a linha de
        # Tempo não aparecia na barra.
        "relogio":              dict(RELOGIO_INICIAL),
        "quests":               {},
        "lojas":                {},
        # Manutenção de memória (ver memory.marcar_upkeep). O prefixo _ marca
        # que é contabilidade do sistema, não conteúdo da história.
        "_turno":               0,
        "_upkeep":              {},
        "_pendencias":          [],
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
    # Listas do personagem gravadas como null (JSON importado, editor antigo)
    # quebravam toda ferramenta que percorre o inventário ou as habilidades.
    for campo in ("inventario", "habilidades"):
        if not isinstance(char.get(campo), list):
            char[campo] = []

    sheet = char.get("sheet")
    if not isinstance(sheet, dict):
        # Sem ficha é um estado válido (NPC salvo só com save_character).
        return

    # Campos opcionais que o motor cria sob demanda com setdefault: null no
    # lugar de ausente fazia o setdefault devolver None.
    for campo in ("recargas", "efeitos", "feature_choices", "lendarias"):
        if campo in sheet and sheet[campo] is None:
            del sheet[campo]

    defaults_v2 = {
        "ouro":                 0,
        "prata":                0,
        "cobre":                0,
        "equipamentos":         {"armadura": None, "escudo": None, "arma_principal": None, "amuleto": None},
        "condicoes":            [],
        "death_saves_sucessos": 0,
        "death_saves_falhas":   0,
        # v3 — tipos de dano, PV temporários e concentração.
        "vida_temp":            0,
        "concentracao":         None,
        "resistencias":         [],
        "imunidades":           [],
        "vulnerabilidades":     [],
        # v4 — o que o grupo já descobriu das defesas desta criatura.
        "descobertas":          {},
    }

    for key, default_val in defaults_v2.items():
        # null conta como ausente, menos na concentração, onde None é o valor
        # normal de "não está concentrado".
        if key not in sheet or (sheet[key] is None and default_val is not None):
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
        from rpg.tools_dnd import DEFAULT_SPELLS_BY_CLASS
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


def _migrate_mana_pool() -> None:
    """
    Recalcula o pool de mana das fichas para a tabela oficial de Pontos de
    Magia (DMG p.288), corrigindo personagens criados com a fórmula homebrew
    antiga (que dependia do atributo e crescia errado no level-up). Roda no
    load_campaign. Só afeta classes de PC reconhecidas; NPCs e classes
    desconhecidas ficam intactos. `mana_atual` é apenas limitada ao novo
    máximo (não recarrega mana gasta).
    """
    try:
        from rpg.tools_dnd import _max_mana_for, CLASS_DATA
    except ImportError:
        return
    for char in campaign.get("characters", {}).values():
        sheet = char.get("sheet")
        if not sheet:
            continue
        classe = (sheet.get("classe", "") or "").lower().strip()
        if classe not in CLASS_DATA:
            continue                       # NPC / classe não-PC: não mexe
        novo_max = _max_mana_for(classe, int(sheet.get("nivel", 1) or 1))
        sheet["mana_max"]   = novo_max
        atual               = int(sheet.get("mana_atual", 0) or 0)
        sheet["mana_atual"] = max(0, min(atual, novo_max))


# Gêneros: o tom do mundo, combinável com qualquer modo de regras.
GENEROS = ("fantasia", "dark_fantasy", "romance", "horror", "misterio", "scifi", "faroeste")

# Os gêneros em que as regras de D&D fazem sentido. O D&D 5e não é um sistema
# genérico: o catálogo é de fantasia medieval (espada longa, bola de fogo, peça
# de ouro, guerreiro e mago). Serve a fantasia e dark fantasy, ao horror gótico
# e ao mistério num mundo de fantasia; numa nave, num faroeste ou num romance,
# a loja de espadas e o grimório não fecham, e o combate tático atrapalha.
GENEROS_COM_REGRAS = ("fantasia", "dark_fantasy", "horror", "misterio")


def regras_e_genero(campaign_type, dnd_mode) -> tuple[str, bool]:
    """
    (gênero, usa as regras de D&D) a partir do que a campanha guarda.

    "dnd" era um valor de campaign_type, no mesmo seletor dos gêneros: quem
    queria fichas e combate tático tinha de abrir mão do tom, e quem queria
    horror ou romance perdia o motor. D&D é modo de jogar, não gênero — uma
    campanha "dnd" antiga vira fantasia com as regras ligadas, que é o que
    ela era de fato. Gênero desconhecido vira fantasia.

    As regras só valem nos GENEROS_COM_REGRAS: romance, sci-fi e faroeste são
    sempre narrativos.
    """
    genero = (campaign_type or "fantasia").strip().lower()
    if genero == "dnd":
        return "fantasia", True
    genero = genero if genero in GENEROS else "fantasia"
    return genero, bool(dnd_mode) and genero in GENEROS_COM_REGRAS


def _migrate_regras_e_genero() -> None:
    genero, dnd = regras_e_genero(campaign.get("campaign_type"), campaign.get("dnd_mode"))
    campaign["campaign_type"] = genero
    campaign["dnd_mode"] = dnd


def _migrate_relogio() -> None:
    """
    Toda campanha tem uma hora do dia, desde o primeiro turno.

    O relógio nascia vazio e só passava a existir quando o mestre chamava
    advance_time() — o que ele só é cobrado de fazer depois de dez turnos.
    Até lá a linha do tempo não aparecia na barra, e o jogador não tinha como
    saber que horas eram na história. Agora a campanha começa no Dia 1, às 8h,
    e as que foram criadas antes ganham o mesmo começo ao carregar.
    """
    rel = campaign.get("relogio")
    if not isinstance(rel, dict) or not rel:
        campaign["relogio"] = dict(RELOGIO_INICIAL)


def normalizar_campanha() -> None:
    """
    As correções que TODA campanha carregada recebe, num lugar só:

      • campos da v2 nas fichas antigas (ouro, condições, etc.);
      • gênero e regras em campos separados ("dnd" deixou de ser gênero);
      • estrutura do estado de combate;
      • descrições de magia que ficaram como placeholder;
      • pool de mana pela tabela oficial de Pontos de Magia.

    Existe separada do load_campaign porque quem semeia campanha por outro
    caminho (o harness de capturas e os testes de tela) precisa das mesmas —
    sem elas, a tela mostrava número que o jogo nunca mostraria: a mesma
    clériga aparecia com 28 de mana numa tela e 14 na outra.
    """
    for char in campaign.get("characters", {}).values():
        _migrate_sheet_fields(char)
    _migrate_regras_e_genero()
    _migrate_relogio()
    _migrate_combat_state()
    _migrate_spell_descriptions()
    _migrate_mana_pool()


def char_key(name: str) -> str:
    """
    Normaliza o nome de um personagem para uso como chave no dict `characters`.
    Garante que 'Bandido Raso', 'bandido raso', 'Bandido_Raso' e '  Bandido Raso  '
    sejam sempre tratados como a mesma chave — eliminando duplicatas e KeyErrors.
    """
    return name.lower().strip().replace("_", " ")


# ---------------------------------------------------------------------------
# Manutenção da memória — há quantos turnos cada tarefa não é feita
# ---------------------------------------------------------------------------
#
# O agente esquece de salvar personagem, trocar o local, escrever no diário e
# atualizar o resumo. Instrução sozinha não resolveu: são oito bullets de
# "faça sempre" competindo com um prompt de 800 linhas.
#
# Aqui o esquecimento vira NÚMERO. O contador é lido a cada turno pelo provedor
# de instrução (rpg.agent._pendencias_block), que injeta a cobrança no próprio
# prompt do turno seguinte — sem gastar uma chamada de API a mais, porque a
# instrução já é recomputada mesmo.

def turno_atual() -> int:
    return int(campaign.get("_turno", 0) or 0)


def avancar_turno() -> int:
    """Chamado uma vez por resposta concluída do agente."""
    n = turno_atual() + 1
    campaign["_turno"] = n
    return n


def marcar_upkeep(chave: str) -> None:
    """Anota que a tarefa `chave` acabou de ser feita."""
    campaign.setdefault("_upkeep", {})[chave] = turno_atual()


def turnos_sem(chave: str) -> int:
    """
    Turnos desde a última vez que `chave` foi feita.
    -1 = nunca foi feita nesta campanha.
    """
    marcas = campaign.get("_upkeep") or {}
    if chave not in marcas:
        return -1
    return turno_atual() - int(marcas.get(chave) or 0)


LADOS = ("grupo", "aliado", "inimigo")


def lado_no_combate(char: dict) -> str:
    """
    De que lado um personagem luta: "grupo", "aliado" ou "inimigo".

    O combate tinha dois lados: quem estava no grupo do jogador, e todo o
    resto. Escoltar um mercador virava luta contra ele — o NPC entrava na
    iniciativa, caía na zona dos inimigos e o motor o mandava atacar o grupo.

    Agora existe o aliado: luta ao lado do grupo, mas não é do grupo (não
    ganha XP, não sobe de nível, não entra no saque e não é jogado pelo
    jogador — o motor age por ele, como age pelos inimigos).

    A dedução, em ordem:
      1. char["lado"], quando o mestre marcou (roll_initiative(allies=...) ou
         set_combat_side);
      2. quem é do grupo (is_party_member) é "grupo";
      3. quem foi criado como criatura de luta é "inimigo" (spawn_monster e a
         ficha padrão do roll_initiative gravam status "inimigo");
      4. NPC de quem a campanha já gosta (atitude >= 30) é "aliado"; NPC
         hostil (atitude <= -30) é "inimigo";
      5. no resto, "inimigo" — o padrão antigo, e o seguro: numa ficha comum
         o mercador que o grupo escolta e a rival que veio duelar são
         idênticos, e adivinhar "aliado" transformaria todo duelo numa luta
         sem inimigo. Quem luta ao lado do grupo é declarado: roll_initiative
         (allies=...) ou set_combat_side.
    """
    if not isinstance(char, dict):
        return "inimigo"
    lado = (char.get("lado") or "").strip().lower()
    if lado in LADOS:
        return lado
    if is_party_member(char):
        return "grupo"
    if (char.get("status") or "").strip().lower() == "inimigo":
        return "inimigo"
    try:
        atitude = int(char.get("atitude", 0) or 0)
    except (TypeError, ValueError):
        atitude = 0
    if atitude >= 30:
        return "aliado"
    return "inimigo"


def luta_com_o_grupo(char: dict) -> bool:
    """Está do lado do jogador nesta luta (do grupo ou aliado)."""
    return lado_no_combate(char) != "inimigo"


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
    from rpg import database

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

        # A versão lida fica guardada POR SESSÃO, fora do documento: é com ela
        # que a próxima gravação prova que ninguém escreveu no meio do caminho.
        _VERSAO[_active_key.get() or _FALLBACK_KEY] = database.versao_de(data)

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

        normalizar_campanha()

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

@contextlib.contextmanager
def gravacao_adiada():
    """
    Junta as gravações de um turno numa só.

    Dentro do escopo, save_campaign() apenas MARCA que há mudança; a escrita
    acontece ao sair, uma vez. Escopos aninhados não gravam antes da hora: só
    o mais externo fecha.

    Sair SEMPRE grava, inclusive por exceção ou por o jogador fechar a aba no
    meio do stream — o `finally` corre de qualquer jeito. O que se perde, se o
    processo morrer no meio do turno, é o turno; antes se perdia metade dele,
    que é pior de arrumar do que nenhum.
    """
    chave = _active_key.get() or _FALLBACK_KEY
    ja_estava = chave in _ADIADAS
    _ADIADAS.add(chave)
    try:
        yield
    finally:
        if not ja_estava:
            _ADIADAS.discard(chave)
            if chave in _SUJAS:
                _SUJAS.discard(chave)
                _persistir(chave)


def save_campaign() -> None:
    """
    Persiste o estado da campanha no Supabase com as travas de segurança
    originais — ou, dentro de um escopo de gravação adiada, só marca que há o
    que gravar (ver gravacao_adiada).
    """
    chave = _active_key.get() or _FALLBACK_KEY
    if chave in _ADIADAS:
        _SUJAS.add(chave)
        return
    _persistir(chave)


def _persistir(chave: str) -> None:
    """
    A gravação de verdade. Trabalha pela CHAVE, e não pelo contexto ativo,
    porque o flush pode acontecer noutra thread que não a que mexeu na
    campanha.
    """
    from rpg import database

    camp = _STORE.get(chave)
    uid, name = _META.get(chave, (None, None))

    # TRAVA 1: Só salva se tiver nome definido
    if not camp or not camp.get("name"):
        print("[ALERTA] Tentativa de salvar abortada: Memória sem nome de campanha.")
        return

    # TRAVA 2: memória vazia não sobrescreve o que está gravado.
    #
    # Antes isto custava uma LEITURA do banco por gravação, só para saber se
    # já existia linha lá. A pergunta certa é outra e não precisa de rede: uma
    # campanha sem histórico, sem resumo e sem personagem não tem o que
    # salvar — exista linha ou não. Quem cria a linha da campanha nova é a
    # rota de criação, que chama database.save_campaign direto.
    if not (camp.get("conversation_history") or camp.get("story_summary")
            or camp.get("characters")):
        print(f"Aviso: [PROTEÇÃO] Nada a salvar em '{camp['name']}': memória vazia.")
        return

    # Limita o histórico
    hist = camp.get("conversation_history", [])
    if len(hist) > MAX_HISTORY_SAVED:
        camp["conversation_history"] = hist[-MAX_HISTORY_SAVED:]

    if not uid or not name:
        print("[ALERTA] Save abortado: contexto de sessão não vinculado.")
        return

    try:
        _VERSAO[chave] = database.save_campaign(uid, name, dict(camp),
                                                _VERSAO.get(chave))
        print(f"Campanha '{camp['name']}' persistida no Supabase.")
    except database.ConflitoDeGravacao as conflito:
        # Outra aba (ou outra tela) gravou esta campanha depois de esta sessão
        # tê-la lido. Até aqui isso acontecia em silêncio e alguém perdia o
        # turno sem nunca saber.
        #
        # O turno continua sendo gravado, DE PROPÓSITO: recusar agora jogaria
        # fora a cena que o jogador acabou de jogar e já leu na tela. O que
        # muda é que o fato passa a existir — no log e na medição. Com número
        # na mão dá para decidir se vale recusar, ou fundir as duas versões.
        print(f"[CONFLITO] '{camp['name']}': {conflito}. Outra aba gravou "
              f"depois desta sessão ler. Gravando assim mesmo.")
        try:
            from rpg import medicao
            medicao.registrar_conflito(camp.get("name", ""), conflito.esperada,
                                       conflito.encontrada)
        except Exception:
            pass
        try:
            _VERSAO[chave] = database.save_campaign(uid, name, dict(camp))
        except Exception as e:
            print(f"Erro crítico ao salvar no Supabase: {e}")
    except Exception as e:
        print(f"Erro crítico ao salvar no Supabase: {e}")


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