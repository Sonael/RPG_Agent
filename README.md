# RPG Agent

> Um RPG narrado por uma IA que age como Mestre, com memória persistente, regras
> de D&D 5e mecanicamente fiéis e uma tela de combate tática opcional.

**🎲 Jogue agora: [rpg-agent.onrender.com](https://rpg-agent.onrender.com)**

> A aplicação está hospedada no plano gratuito do Render; a primeira
> requisição após um período ocioso pode levar alguns segundos enquanto o
> serviço acorda. O app é um **PWA instalável** (Android/iOS) e exibe uma
> tela "Acordando o servidor…" com retry automático durante esse cold start,
> em vez de travar. Veja [PWA e instalação](#pwa-e-instalação).

A IA não é só um chatbot que escreve narrativa: ela é um **agente** com
ferramentas (function calling) que **lê e altera o estado do mundo**:
personagens, locais, fichas D&D, inventário, condições, combate. Um verificador
determinístico **valida cada resposta** e reinjeta correção quando a IA narra
uma mecânica sem chamar a ferramenta correspondente.

O resultado é um RPG onde:
- a narrativa é livre e criativa (a IA conduz),
- mas os números são **decididos por dados**, não pela vontade do modelo,
- e o estado do mundo **persiste corretamente** entre sessões.

---

## Motivação, o "esquecimento" das LLMs

Quando alguém usa uma LLM crua (ChatGPT, Gemini, etc.) para jogar RPG, surge
sempre o mesmo problema: **a IA esquece**. Conforme a aventura cresce, ela
perde o fio da meada. Troca nomes de NPCs, esquece locais já visitados,
ignora itens do inventário, contradiz decisões anteriores e "reinventa" a
ficha do personagem. Tudo o que importa numa campanha (quem é quem, onde se
foi, o que aconteceu, quanto de vida o personagem tem) vive apenas na
**janela de contexto** do modelo, e some quando ela enche, é compactada ou
quando a sessão recomeça do zero.

Este projeto nasceu para resolver exatamente esse esquecimento. A ideia
central é **tirar o estado do jogo de dentro do texto da conversa** e
tratá-lo como **dados estruturados e persistentes**: personagens, locais,
fichas D&D, inventário, condições, combate e flags de missão vivem num
estado central, gravado em banco e **reinjetado** a cada sessão. A IA não
precisa "lembrar" de nada: ela **consulta e atualiza** esse estado através
de ferramentas. O contexto da conversa pode encher e ser resumido; a
memória da campanha **não se perde**.

## Por que a IA é um agente

O foco do projeto é a IA atuando como um **agente de verdade**: não um
gerador de texto passivo, mas uma entidade que **percebe**, **delibera** e
**age** sobre um ambiente, sob supervisão.

Mapeando o projeto para o vocabulário de agentes:

- **Ambiente**, o estado do mundo do jogo (personagens, locais, combate,
  inventário, flags), estruturado e persistente (`rpg/memory.py` + Supabase).
- **Percepção**, a cada turno o agente *lê* o ambiente por ferramentas de
  consulta (`get_scene_context`, `get_character_sheet`, `get_combat_status`…).
  Ele não age "às cegas": primeiro observa o estado atual.
- **Ação**, o agente *altera* o ambiente **exclusivamente por ferramentas**
  (`attack_roll`, `save_character`, `apply_condition`, `grant_xp`…). Ele não
  pode mudar um número apenas "narrando", só chamando a ferramenta. A
  narrativa vem **depois** da ação, descrevendo o que as ferramentas decidiram.
- **Deliberação**, o LLM decide *quais* ferramentas chamar e *em que ordem*,
  encadeando múltiplas `function_call` num único turno até produzir a
  resposta final (o loop está detalhado na próxima seção).
- **Autonomia supervisionada**, um **verificador determinístico** valida
  cada resposta e **força o agente a se corrigir** quando ele narra uma
  mecânica sem executar a ação correspondente. O agente é livre para narrar,
  mas não para burlar as regras do ambiente.
- **Múltiplos agentes no ambiente**, NPCs e inimigos têm comportamento
  próprio (`execute_npc_turn` com estratégias: agressivo, tático, covarde,
  suporte, aleatório), tomando turnos de combate **sem o LLM no meio**.
- **Isolamento de agentes**, cada usuário tem seu próprio runner ADK e seu
  próprio estado por sessão; agentes de jogadores diferentes não se enxergam.

A seção [Como a IA é usada como agente](#como-a-ia-é-usada-como-agente)
abre o loop **percepção → deliberação → ação → verificação** em detalhe.

---

## Sumário

1. [Visão geral](#visão-geral)
2. [Como a IA é usada como agente](#como-a-ia-é-usada-como-agente)
3. [Estilos de campanha](#estilos-de-campanha)
4. [Sistema de memória (estado por sessão)](#sistema-de-memória-estado-por-sessão)
5. [Persistência (Supabase) e autenticação](#persistência-supabase-e-autenticação)
6. [Modo D&D, mecânicas](#modo-dd-mecânicas)
7. [Sistema de combate](#sistema-de-combate)
8. [Tela de combate tática (Pergaminho Épico)](#tela-de-combate-tática-pergaminho-épico)
9. [Tools, o catálogo do agente](#tools-o-catálogo-do-agente)
10. [Endpoints HTTP](#endpoints-http)
11. [Frontend](#frontend)
12. [PWA e instalação](#pwa-e-instalação)
13. [Testes e garantias](#testes-e-garantias)
14. [Estrutura de arquivos](#estrutura-de-arquivos)
15. [Configuração e execução](#configuração-e-execução)
16. [Limitações conhecidas](#limitações-conhecidas)

---

## Visão geral

O sistema é uma aplicação web Flask (server.py) que orquestra um agente LLM
para conduzir sessões de RPG. O usuário cria campanhas no navegador, escolhe um
estilo (D&D, fantasia, horror, romance…), e joga em um chat onde o **Mestre é a
IA**. Tudo o que importa do mundo, personagens, locais, fichas, inventários,
combate, vive num estado central que tanto a IA quanto a interface enxergam.

**Pilares do design:**

- **Agente com ferramentas**, não chatbot. A IA chama funções Python pra
  ler/escrever o mundo. Narrativa vem **depois** dos números.
- **Determinismo onde importa**. Dados, HP, ordem de turno são decididos por
  código fuzzado, nunca pelo texto do modelo.
- **Validador pós-resposta**. Se a IA narra "Goblin morreu" sem chamar
  `attack_roll`, o sistema **detecta e força uma correção**.
- **Memória persistente**. Cada campanha é um estado JSON gravado em Supabase,
  reinjetado quando você volta à sessão.
- **Multimodelo**. Gemini (Google), DeepSeek e Ollama (modelos locais), o
  usuário escolhe na hora de iniciar a sessão.
- **Isolamento multiusuário**. Cada usuário tem seu próprio estado por sessão
  ADK; nada vaza entre contas.

---

## Como a IA é usada como agente

### A pilha

```
┌─────────────────────────────────────────────────────────────┐
│  Browser (login.html → menu.html → game.html)               │
│  game.js (chat) + combat.js (tela tática) + utils.js (UI)   │
└─────────────────────────────────────────────────────────────┘
                    │  HTTP + SSE
┌─────────────────────────────────────────────────────────────┐
│  server.py, Flask + SSE                                    │
│  • /api/auth/*    → Supabase Auth (auth.py)                 │
│  • /api/session/* → cria runner ADK por usuário/campanha    │
│  • /api/chat      → streaming da resposta da IA + tools     │
│  • /api/combat/*  → motor de combate sem-LLM (modo tela)    │
│  • /api/memory/*  → CRUD do estado para a sidebar           │
└─────────────────────────────────────────────────────────────┘
                    │
┌─────────────────────────────────────────────────────────────┐
│  Google ADK Runner (1 por usuário/campanha)                 │
│   ├─ Agent(instruction, model, tools=ALL_TOOLS)             │
│   ├─ InMemorySessionService                                 │
│   └─ Loop: LLM → function_call → tool_response → texto…     │
└─────────────────────────────────────────────────────────────┘
                    │
┌─────────────────────────────────────────────────────────────┐
│  tools.py + tools_dnd.py  (60 ferramentas expostas)         │
│  Operam sobre memory.campaign (proxy resolvido por contexto)│
└─────────────────────────────────────────────────────────────┘
                    │
┌─────────────────────────────────────────────────────────────┐
│  memory.py  →  ContextVar → _STORE[user::campanha] → dict   │
│         │                                                    │
│  database.py  →  Supabase Postgres (upsert/load por (user,  │
│                  campaign))                                  │
└─────────────────────────────────────────────────────────────┘
```

### O loop do agente em uma requisição de chat

1. O usuário envia uma mensagem em `/api/chat`.
2. `require_auth` valida o JWT da Supabase e **vincula o contexto de memória**
   (`memory.bind_request(user_id)`) à campanha desse usuário.
3. `server.py` invoca o `runner.run_async` da ADK. A coroutine roda numa loop
   assíncrona dedicada e **re-vincula o contexto na própria Task** (porque
   `ContextVar` não propaga automaticamente do thread Flask para a Task
   asyncio em outro thread).
4. A ADK envia ao LLM:
   - a **instrução** (estilo da campanha + regras de memória + regras D&D);
   - o histórico da conversa (compactado a 200 turnos);
   - a lista de **tools** (cada função Python vira um schema JSON Schema);
   - a nova mensagem.
5. O modelo responde com:
   - texto narrativo, **ou**
   - chamadas de função (`function_call`) com argumentos JSON.
6. Para cada `function_call`, a ADK executa a função Python correspondente
   (`attack_roll`, `save_character`, etc.), recebe o retorno, e devolve o
   `function_response` ao modelo. O modelo continua até produzir o texto
   final.
7. Tudo isso é **streamado por SSE** ao navegador (`tool_call`, `tool_result`,
   `text`, `quota`, `done`).

### O verificador pós-resposta

`server.py:_verify_agent_response` roda no `done` da resposta da IA. Ele
detecta **mecânica narrada sem ferramenta** (regex sobre o texto) e força
uma re-execução do agente com prompt corretivo. Os checks:

| # | Detecta | Quando |
|---|---|---|
| 1 | Início de combate sem `roll_initiative()` | "Rodada 1", "iniciativa rolada" |
| 2 | HP modificado narrativamente | "perdeu 6 PV", "12 → 7" |
| 3 | Resultado de ataque sem `attack_roll()` | "acertou", "errou o golpe" (em combate) |
| 4 | Mana modificada narrativamente | "Mana: 8 → 4" |
| 5 | Magia/habilidade "aprendida" sem `learn_spell()` | "Kael aprendeu Bola de Fogo" |
| 6 | Condição aplicada sem `apply_condition()` | "ficou envenenado", "tornou-se cego" |
| 7 | `end_combat()` numa **vitória** sem `grant_xp()` | derrota/fuga não exige XP |

Se houver violação, o sistema **reenvia ao modelo** uma mensagem de correção
explicando o que faltou e **quais ferramentas já foram chamadas** (pra evitar
duplo-dano por re-execução). Só uma rodada de correção por turno.

Além disso, `_check_all_level_ups()` roda no fim de cada resposta: se algum
membro do grupo tem `xp >= xp_proximo` mas a IA esqueceu de aplicar o level
up, o sistema **aplica programaticamente** (PHB + class features + proficiência)
e notifica o frontend.

### A instrução do agente

`agent.py:create_agent` monta a instrução combinando:

- **Estilo da campanha** (fantasia, romance, horror, dnd, etc.), define tom,
  ritmo, foco temático;
- **Regras de memória** (quando chamar `save_character`/`save_location`/
  `update_world_state`/`add_diary_entry`, regras de consistência);
- **Regras D&D** (somente em modo dnd): fluxo de combate, autoridade de turno,
  saving throws, XP obrigatório, modos de combate, ASI, recrutamento;
- **Diretiva de combate em tela** (se `combat_mode == "tela"`): "monte a cena +
  `roll_initiative()` e PARE; não narre turnos; vou te chamar com o log no
  fim".

### Modelos suportados

Selecionados no menu (chave de API gerenciada pelo usuário no `localStorage`):

- **Google Gemini**, `gemini-3.1-flash-lite-preview`, `gemini-3-flash`,
  `gemini-2.5-flash`, etc.
- **Google Gemma**, `gemma-3-27b-it`, `gemma-4-26b-it`, `gemma-4-31b-it`.
- **DeepSeek**, `deepseek-chat`, `deepseek-reasoner` (via `LiteLlm`).
- **Ollama**, qualquer modelo local com tool calling (qwen2.5, llama3.2,
  mistral, …). Conecta em `OLLAMA_API_BASE` (default `http://localhost:11434`).

Para Ollama/Gemma, o sistema injeta automaticamente um wrapper
`<think>…</think>` que separa raciocínio interno de narrativa final.

---

## Estilos de campanha

`agent.py:CAMPAIGN_CONFIGS` e `_STYLE_INSTRUCTIONS`, cada estilo muda a
instrução do mestre e as labels da UI:

| Estilo | Label da UI | Foco da instrução |
|---|---|---|
| `dnd` | Grupo de Aventureiros | Mecânica rigorosa, combate por turnos, classes/raças, XP |
| `fantasia` | Grupo de Aventureiros | Aventura ampla, mundo rico, magia narrativa |
| `romance` | Pessoas Próximas | Emoções, diálogo, subtexto, flags emocionais |
| `horror` | Sobreviventes | Tensão, ritmo lento, vulnerabilidade real, trauma |
| `misterio` | Aliados | Pistas, dedução, suspeitos com álibis |
| `scifi` | Tripulação | Tech consistente, dilemas morais, facções |
| `faroeste` | Comparsas | Reputação, duelo, lei frágil |

O modo D&D é o único com mecânicas D&D 5e completas (ficha, combate em
turnos, etc.). Os outros são puramente narrativos com memória estruturada.

---

## Sistema de memória (estado por sessão)

`rpg/memory.py` é o coração do estado. Foi redesenhado para ser **multiusuário-safe**.

### Modelo

```
_STORE[ "user_id::campanha" ] = {dict da campanha}

_active_key (ContextVar) → escolhe qual entrada do _STORE responde a
                            memory.campaign no contexto atual

memory.campaign  (proxy)  → resolve em tempo de acesso
```

`memory.campaign` é um **proxy de dict**: cada `campaign["characters"]` resolve
para a campanha **da request atual**. Threads Flask diferentes (usuários
diferentes) e Tasks asyncio diferentes têm contextos isolados.

### API principal

```python
memory.bind(user_id, nome)        # start_session, cria/ativa o slot
memory.bind_request(user_id)      # require_auth, reativa por request
memory.unbind(user_id)            # end_session, descarta o slot
memory.current_user_id()          # do contexto
memory.current_campaign_name()    # do contexto
memory.char_key(name)             # normaliza nome → chave do dict
memory.is_party_member(char)      # definição CANÔNICA de "grupo"
memory.load_campaign() / memory.save_campaign()
```

`memory.is_party_member` é a definição única de "está no grupo do jogador":
`party_member=True` **OU** `name == protagonist` **OU** está em
`campaign["party"]`. Usado por server (level-up, XP), tools_dnd
(recrutamento, turno de NPC), sem mais definições divergentes pelo código.

### O dict da campanha (esquema)

```python
{
  "name":                 str,
  "campaign_type":        "dnd" | "fantasia" | ...,
  "dnd_mode":             bool,
  "combat_mode":          "narrado" | "tela",
  "protagonist":          str,
  "characters":           {char_key: {...}},
  "locations":            {loc_key:  {...}},
  "events":               [ {index, summary, location, ...} ],
  "conversation_history": [ {role, text} ],          # cap 200
  "story_summary":        str,
  "current_scene":        str,
  "current_location":     str,
  "chapter":              int,
  "quest_flags":          {name: value},
  "party":                [ {name, role, notes} ],
  "diary":                [ {chapter, title, content} ],
  "combat_state":         {
    "is_active": bool, "initiative_order": [...],
    "current_turn_index": int, "round": int,
    "turn_resolved": bool, "turn_auto_advanced": bool,
    "turn_token": int,                # +1 por avanço REAL (idempotência)
    "turn_economy": {"acao_usada": bool, "bonus_usada": bool},
    "log": [...],                     # eventos estruturados (até 300)
    "result": {...} | None,           # painel de fim na tela
    "npc_strategies": {npc: estrategia},
  },
}
```

Migrações automáticas em `_migrate_*` rodam no `load_campaign` para
preencher campos novos em campanhas antigas.

### Personagem D&D, esquema

```python
{
  "name", "description", "traits", "status", "notes",
  "party_member": bool,
  "sheet": {
    "classe", "raca", "nivel", "xp", "xp_proximo",
    "forca", "destreza", "constituicao",
    "inteligencia", "sabedoria", "carisma",
    "vida_atual", "vida_max", "mana_atual", "mana_max", "ca",
    "proficiencia", "hit_die",
    "ouro", "prata", "cobre",
    "equipamentos": {"armadura", "escudo", "arma_principal", ...},
    "condicoes":    [ {"nome": "Envenenado", "duracao": 3} ],
    "death_saves_sucessos", "death_saves_falhas",
  },
  "habilidades": [ {"nome", "descricao", "custo_mana", "dado"} ],
  "inventario":  [ {"nome", "qtd", "descricao", "custom"} ],
}
```

---

## Persistência (Supabase) e autenticação

`rpg/database.py`, camada fina sobre Postgrest:

- `list_campaigns(user_id)`, `get_campaign`, `save_campaign` (upsert),
  `delete_campaign`, `rename_campaign`, `campaign_exists`.
- Schema mínimo: tabela `campaigns(user_id, name, data jsonb, updated_at)`.

`auth.py`, sessão de usuário via Supabase Auth (gotrue):

- `register(email, password)` / `login(email, password)` / `refresh_session(rt)`.
- `@require_auth` decora os endpoints autenticados, valida o JWT, popula
  `g.user_id` e chama **`memory.bind_request(g.user_id)`**, isso é o que
  garante que cada request opere no estado do próprio usuário.
- Confirmação de e-mail é obrigatória (HTTP 403 se `email_confirmed_at` for
  null).

Tokens (`access_token` + `refresh_token`) vivem no `localStorage` do
navegador. `static/js/utils.js:authFetch` tenta refresh silencioso em 401.

### Endurecimento de segurança

- **Rate limiting** (sliding-window in-memory) em `/api/auth/*` (anti
  brute-force / credential stuffing) e nos endpoints de LLM `/api/chat` e
  `/api/campaigns/generate-lore` (anti abuso de custo).
- **CORS por allowlist** (`ALLOWED_ORIGINS`), sem `Access-Control-Allow-Origin: *`.
- **Anti-enumeração**: registro não revela se um e-mail já existe; erros de
  auth são genéricos (exceções internas só no log).
- **Política de senha** no servidor (mínimo 8 caracteres, letra + número).
- **`/api/auth/confirm`** valida o token contra o Supabase de verdade.
- **XSS**: a narração da IA passa por DOMPurify antes de ir ao DOM
  (`renderMarkdown`); `marked` sozinho deixaria passar `<script>`.
- **Escopo de usuário estrutural**: `rpg/database.py` só acessa a tabela
  `campaigns` por helpers que exigem `user_id` válido e embutem o filtro,
  tornando impossível montar uma query sem escopo. Complementado por RLS no Supabase.
- Headers: HSTS, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`.
- `MAX_CONTENT_LENGTH` de 4 MB contra payloads gigantes.

---

## Modo D&D, mecânicas

`tools_dnd.py` (~7900 linhas, 38 ferramentas + helpers) é o motor de regras D&D 5e
(usa a variante oficial de Pontos de Magia do DMG p.288 no lugar de spell
slots; casos comuns cobertos). Resumo:

### Criação de personagem

`create_character_sheet(name, classe, raca, força, destreza, …, nivel=1)`:

- Calcula HP correto **nível-a-nível** (max no nível 1 + roll por nível).
- Aplica **bônus raciais** do Open5e (`_apply_race_bonuses`), ajusta HP pelo
  delta de CON corretamente (não mais reseta nível 1).
- Aplica **habilidades de classe** de todos os níveis até o informado
  (`_apply_class_features` + `CLASS_LEVEL_FEATURES`).
- Aplica **magias iniciais** da classe (`_apply_initial_spells`, com fallback
  ao Open5e).
- Calcula proficiência por nível (`_proficiency_bonus`).
- Sheet completa: 6 atributos, HP/MP/CA, equipamentos, condições, moedas, etc.

### Raças / classes (Open5e)

- Classes suportadas em `CLASS_DATA`: bárbaro, guerreiro, paladino,
  patrulheiro, bardo, clérigo, druida, monge, ladino, mago, feiticeiro,
  bruxo, arcanista.
- Cada classe tem hit_die, mana_per_level, mana_stat, saving throws
  proficientes.
- Raças resolvidas via Open5e (`_fetch_race_data`); fallback offline em
  `_RACE_BONUS_FALLBACK`.

### Armas

- `_npc_attack_dice` resolve primeiro os **ataques naturais de monstro**
  ("bite", "claw", "slam") pelo stat block gravado na ficha. Só depois cai
  para a busca de arma no SRD. Sem esse passo, esses nomes não existem em
  `/weapons/`, tomam 404 e o motor usava o fallback genérico de 1d6, o que
  achatava o dano de **todo** inimigo do jogo.
- `_fetch_weapon_data` busca dano/tipo de armas no Open5e (PT→EN via
  `WEAPON_PT_TO_EN`).
- `_weapon_attr` decide DEX×STR (ranged→DEX, finesse→max, melee→STR).
- `ARMOR_TABLE` fixa CA base e bônus de DEX por tipo de armadura.

### Camada de acesso ao SRD (`rpg/open5e.py`)

Todas as consultas ao Open5e passam por um módulo único, em vez de
`requests.get` soltos espalhados pelo motor:

- **Sessão reaproveitada** com pool de conexões e retry/backoff em
  transitórios (429/5xx), em vez de um handshake TLS novo por consulta.
- **Cache em memória + disco** (`.cache/open5e.json`). O SRD é estático: um
  goblin é o mesmo goblin para sempre. Quatro spawns repetidos caem de
  ~2,8 s para ~1 ms, e isso acontece **dentro** do tempo de resposta do chat.
- **Cache negativo curto**: "bite" não é arma do SRD e nunca será. Sem ele,
  todo ataque de monstro repetiria o mesmo 404 no caminho quente. Erro de
  *rede*, ao contrário, não é cacheado: um timeout é transitório e a próxima
  chamada tenta de novo.
- **Modo offline** (`open5e.offline()`, env `RPG_SRD_OFFLINE=1`) para testes
  e para rodar sem rede.
- **`open5e.stats()`** expõe hits/misses/erros. Antes, quando a API caía, o
  motor degradava em silêncio para 1d6 e CA 12 e ninguém ficava sabendo.

Os call sites usam `from open5e import http as _req`: a resposta expõe
`.ok` e `.json()`, então trocar a camada não mexeu na lógica de ninguém.

### Inventário e moedas

- `add_item`, `remove_item`, `list_inventory`.
- `equip_item` recalcula CA via `_recalculate_ca`.
- `modify_currency(char, "ouro"|"prata"|"cobre", amount)`.
- `identify_item` busca o item no SRD via Open5e, distingue **mágicos
  canônicos** de **customizados** e marca pra IA não exceder no efeito.

### Testes e dados

- `roll_dice(sides, count, modifier)`.
- `make_skill_check(char, atributo, dificuldade, advantage, disadvantage, skill, player_roll)`
  resolve o atributo automaticamente pela perícia (Atletismo → FOR,
  Furtividade → DES, etc.). Para personagem **jogável**, passe `player_roll`
  com o d20 que o jogador rolou; para NPC, o mestre/sistema rola.
- `social_check(char, skill, dc, player_roll, target)`, **o jogador informa
  o d20**, o sistema aplica modificador + proficiência. Usado em
  Persuasão/Intimidação/Enganação/Recrutamento.

> **Regra única de rolagem:** todo teste de d20 de um personagem jogável
> honra o dado REAL do jogador. `make_skill_check`, `social_check`,
> `resolve_saving_throw` e `roll_death_save` aceitam `player_roll`; a
> ferramenta nunca inventa o número quando o jogador rolou.

### Combate (resumido, detalhe na próxima seção)

- `roll_initiative(nomes)`, d20+DEX, ordena, ativa combate.
- `attack_roll(atacante, alvo, arma, dano)`, d20+mod+prof vs CA, aplica
  dano, KO em 0 HP. Suporta vantagem/desvantagem e condições.
- `use_ability(char, habilidade, alvo, saving_throw_*)`, gasta mana,
  rola dado, aplica efeito. Suporta **magias de pool** (Sleep, Color Spray),
  **magias de condição** (Hold Person, Charm Person…), cura, dano.
- `roll_death_save(char, player_roll)`, d20: 20=acorda 1 HP, 1=2 falhas, 3
  sucessos estabiliza, 3 falhas mata. PC informa o `player_roll`; NPC rola.
- `apply_condition` / `remove_condition`, busca descrição no SRD.
- `next_turn`, `end_combat`.

> **XP só por vitória.** `end_combat()` numa derrota (grupo todo caído ou
> fuga) **não** concede XP: perder a luta não dá recompensa. O verificador
> do servidor só cobra `grant_xp()` quando alguém do grupo ficou de pé.

### XP / Level-up

- `grant_xp(char, amount, reason)`, aplica e dispara level up automático
  (HP, proficiência, mana, class features, threshold). Loop interno até
  consumir todo o XP excedente.
- Safety net (`_check_all_level_ups`) roda no servidor, se a IA esqueceu de
  conceder XP, aplica o level up de qualquer forma.

### Descanso

- `short_rest` (gasta metade dos hit dice; recupera HP), `use_hit_die`,
  `long_rest` (full HP/MP + hit dice + condições; bloqueado em combate).

### NPCs

- `spawn_monster(slug, display_name, quantity)`, stats reais Open5e.
  `_extract_monster_attacks` lê o bloco de ações e grava na ficha **todos os
  ataques com seus dados** (`ataques`) e quantos golpes o **Multiattack**
  concede. A ação "Multiattack" em si é descartada como golpe: a descrição
  dela contém "melee attacks:" (Bandit Captain: *"makes three melee attacks:
  two with its scimitar…"*), e sem essa guarda ela virava a arma principal
  sem dado, de volta ao 1d6. O filtro confiável é o `+X to hit`, presente em
  todo ataque real do SRD e ausente em descrições que só citam ataques.
- `recruit_character(npc, role)`, bloqueia recrutamento de NPCs com 10+
  níveis acima do grupo (narrativamente impossível); aviso a partir de 5.
- `set_npc_strategy` / `execute_npc_turn`, turno automático de NPC com
  estratégias (agressivo, tático, covarde, aleatório, suporte). Covarde
  foge quando HP<25%.

### Encontros

- `suggest_encounter(party_level, party_size, difficulty)`, calcula
  budget de XP por DMG p.82, sugere combinações de monstros via Open5e.

### Talentos / ASI

- `choose_feat(char, feat_name)`, busca no SRD, valida pré-requisitos
  (ability score mínimo), aplica.
- `set_stat(char, stat, value)`, usado para ASI (+1/+1 ou +2). Recalcula
  derivados automaticamente: HP por CON, CA por DES, mana pelo atributo de
  conjuração.

### Subescolhas de habilidade e arquétipos

Muitas habilidades de classe são "escolha 1 de N". Duas tabelas em
`tools_dnd.py` cobrem isso:

- **`FEATURE_VARIANTS`**, features com variante direta: Estilo de Combate
  (Arquearia, Defesa, Duelo, Grande Arma…), Inimigo Favorecido, Explorador
  Natural, Metamagia, Invocações Sobrenaturais.
- **`ARCHETYPE_FEATURES`**, 13 arquétipos de classe (Campeão, Mestre de
  Batalha, Berserker, os 8 domínios de clérigo, as 8 tradições de mago,
  etc.) com **sub-features que escalam por nível** (~200 entradas).

`set_feature_choice(char, feature, escolha)` grava a escolha em
`sheet.feature_choices`; ao escolher um arquétipo, concede automaticamente
as sub-features liberadas no nível atual. Em level-up, `_apply_class_features`
materializa as novas sub-features do arquétipo.

**Efeitos ligados ao motor de combate** (não só descrição):

- Estilo de Combate, Arquearia (+2 atk à distância), Defesa (+1 CA),
  Duelo (+2 dano), Grande Arma (re-rola 1s/2s no dado de dano).
- Inimigo Favorecido, +2 dano contra o tipo de criatura escolhido.
- Crítico Aprimorado / Superior (Campeão), faixa de crítico vai a 19-20 / 18-20.
- Golpe Divino (domínio de clérigo), +1d8 (2d8 no nv. 14) 1×/turno.
- Resistência Dracônica (feiticeiro), CA sem armadura = 13 + DES.

O **modo de alvo** de cada habilidade (`self` / `pool` / `single`) é
derivado do campo `alcance` que vem do Open5e, não de listas hardcoded.
O picker de variante aparece no editor de campanha e no wizard.

### Descrições de habilidade de classe

`CLASS_FEATURE_DESCS` cobre as **126 habilidades** de classe do SRD com
descrição mecânica real (cada feature de `CLASS_LEVEL_FEATURES` tem entrada,
sem cair num texto de fallback genérico).

---

## Sistema de combate

### Engine determinístico (fundação fuzzada)

O motor de turnos vive em `tools_dnd.py` e tem **garantias formais
demonstradas por fuzz** (`tests/legacy/tests_combat_fuzz.py`, 8k+ combates aleatórios,
0 violações de invariantes):

| Garantia | Mecanismo |
|---|---|
| **Avanço sempre +1 por ação** | `turn_token` monotônico, base de idempotência |
| **Não há "ataque fora de ordem"** | `_combat_turn_violation` recusa antes de rolar dado |
| **Ponteiro nunca preso em morto** | `_heal_current_turn` em toda entrada de tool |
| **Sem duplo-avanço** | `turn_auto_advanced` + token; `next_turn` é idempotente |
| **Avanço ancorado no ator** | `_auto_advance_turn(actor_name)`, não no ponteiro stale |
| **Fim automático** | Quando um lado é DERROTADO (morto / 0 HP / fugiu). Um inimigo apenas DORMINDO não encerra a luta |

Cada ferramenta de combate (attack_roll, use_ability, roll_death_save,
execute_npc_turn) chama `_combat_turn_violation` no início. Se for ação fora
de ordem, recusa com mensagem clara, **nada muda, nenhum dado rolado**. O
agente é instruído a obedecer ("se a ferramenta retornar FORA DE ORDEM, não
repita; use execute_npc_turn ou avise 'ainda não é sua vez'").

### Economia de ações (5e: PHB 2014 + revisão 2024)

Cada turno tem:

- **1 Ação**, Atacar, magia de Ação, Esquivar, Disengajar
- **1 Ação Bônus**, só se algo permitir (Healing Word, Misty Step, Second
  Wind, Action Surge, Cunning Action, Bardic Inspiration, Spiritual Weapon,
  Shillelagh, Healing Spirit, Hex, **Poção de Cura (regra 2024)**)
- **1 Reação**, fora do próprio turno (ver "Reação e ataque de oportunidade")
- Movimento

O turno **só avança** quando:
- ambos os slots foram gastos, ou
- o jogador clica **Encerrar Turno**, ou
- o jogador foge (consome Ação + sai), ou
- o sistema detecta que um lado foi todo derrotado.

Classificadores (`rpg/tools_dnd.py:_ability_action_type` e `_item_action_type`)
detectam Bônus por nome (PT e EN). Default: Ação.

### Tipos de dano, resistência, imunidade e vulnerabilidade

Todo dano do jogo passa por `_apply_damage()`, na ordem do PHB:

```
modificador de tipo → PV temporários absorvem → PV reais → teste de concentração
```

Antes, o dano era subtraído cru do HP (`vida_atual -= dmg`). Sem tipo não
existe resistência: o esqueleto morria de veneno, o elemental do fogo se
queimava, e escolher a arma certa contra um alvo não mudava nada.

De onde vem o tipo, em ordem de confiança:

1. campo `tipo_dano` da habilidade, se houver;
2. descrição da habilidade em PT ("3d6 dano de fogo");
3. `ataques` do stat block do monstro ("slashing damage");
4. nome da arma (espada → cortante, maça → concussão).

Sem tipo identificado, o dano é aplicado **sem modificador** — o
comportamento seguro.

`spawn_monster` importa `damage_resistances`, `damage_immunities` e
`damage_vulnerabilities` do Open5e, que antes eram descartados. Verificado
contra a API real:

| Monstro | Efeito |
|---|---|
| Esqueleto | resiste a veneno, **vulnerável a concussão** (dano dobrado) |
| Elemental do Fogo | **imune a fogo** — bola de fogo causa 0 |
| Lobisomem | imune a corte/perfuração/concussão **de armas não-mágicas** |

**A armadilha da qualificação.** O SRD escreve *"bludgeoning, piercing, and
slashing from nonmagical attacks"*. Aplicar isso sem modelar armas mágicas
deixaria o lobisomem praticamente imune ao grupo. Então a qualificação é
preservada em `requer_magica`, e a resistência é ignorada quando o golpe vem
de arma mágica **ou de material especial** — "espada prateada", "adaga de
prata", "machado adamantino". A espada de prata existe justamente para caçar
lobisomem; sem reconhecer o material ela faria zero dano igual a um pau.

Medido ao vivo contra o lobisomem: espada longa comum → **0 de dano**;
Espada Longa +1 → **8**.

### PV temporários

`grant_temp_hp(char, amount, source)`. Absorvem dano antes dos PV reais, não
podem ser curados e expiram no descanso longo. **Não se acumulam**: ao
receber uma nova quantia o alvo fica com a maior das duas, nunca com a soma
— e a ferramenta avisa quando descarta a menor.

Aplicados **depois** do modificador de tipo, como manda o PHB: 10 de fogo
contra um alvo resistente com 10 PV temporários consome 5, não 10.

### Concentração

"Concentração" era só texto decorativo nas descrições. Hoje
`sheet["concentracao"]` guarda a magia ativa, e:

- só **uma** magia de concentração por vez — conjurar outra derruba a
  anterior, com aviso (antes, um clérigo sustentava Bênção + Escudo da Fé +
  Arma Espiritual ao mesmo tempo);
- sofrer dano exige teste de Constituição, CD = maior entre 10 e metade do
  dano;
- cair a 0 PV derruba sem teste;
- dano totalmente absorvido por PV temporários, ou zerado por imunidade, não
  ameaça a concentração;
- descanso longo e fim de combate limpam — a concentração nunca vaza para a
  luta seguinte.

O d20 desse teste é rolado pelo sistema, inclusive para personagens
jogáveis: ele dispara no meio do turno do inimigo, e parar tudo para pedir um
dado quebraria o fluxo do combate. O resultado é sempre mostrado.

### Reação e ataque de oportunidade

A economia rastreava só Ação e Bônus. A **Reação** — a única coisa que
acontece fora do próprio turno — agora existe: uma por rodada, guardada em
`sheet["reacao_rodada"]`.

Sem posicionamento no jogo, o gatilho honesto para o ataque de oportunidade
é a **fuga**. Sair do combate deixou de ser grátis, que é exatamente o que a
regra existe para impedir. Cada inimigo consciente que ainda tem a reação da
rodada faz um ataque corpo-a-corpo contra quem foge — valendo para os dois
caminhos, o NPC covarde e o jogador clicando "Fugir" na tela.

O motor redireciona: se o fugitivo cai no primeiro bote, os demais não
desperdiçam a reação num corpo no chão.

Quando houver zonas/alcance, `_provoke_opportunity_attacks` passa a ser
chamado também no movimento — o resto já está no lugar.

### Status "dormindo" (Sleep)

`Sleep` aplica o status **`dormindo`**, distinto de `inconsciente` (caído a
0 HP). Uma criatura dormindo pula a vez (incapacitada), mas continua **viva
e no combate**; derrotá-la ainda exige dano. Por isso `dormindo` entra em
`OUT_OF_COMBAT_STATUSES` (pula turno) mas **não** em `DEFEATED_STATUSES`
(encerra a luta). Sofrer dano acorda a criatura (regra 5e); `end_combat()` e
`roll_initiative()` acordam/normalizam para o status nunca vazar entre lutas.

### Dois modos de combate

A escolha persiste por campanha (`combat_mode` em `memory.campaign`):

- **`"narrado"`** (default), a IA narra cada turno no chat. Validador
  pós-resposta detecta mecânica narrada sem ferramenta e corrige.
- **`"tela"`**, abre a [tela tática](#tela-de-combate-tática-jrpg). A IA
  monta a cena, chama `roll_initiative` e **para**. O combate inteiro é
  resolvido por chamadas determinísticas a `/api/combat/*` (sem LLM no
  meio). No fim, o servidor monta um log estruturado e a IA é chamada **uma
  vez** para narrar a luta inteira + gerar saque.

Toggle do modo: sidebar do jogo → aba Mundo → "📖 Narrado pela IA" / "⚔️
Tela tática".

### Log estruturado

Cada evento mecânico do combate vira uma entrada em `combat_state["log"]`
(cap 300). Inclui os **dados rolados**:

```
[R1] Combate iniciado
[R1] Valerius → Goblin 4 (Espada Longa): 🎲 d20=20 +3+2 = 25 vs CA 5
     • 🌟 CRÍTICO ACERTO • 💥 dano [6 + 6] +3(mod) = 15 → HP 7→0/7
[R1] Goblin 4 caiu inconsciente
[R1] Combate decidido, inimigos fora de ação
[R1] Combate encerrado
```

Eventos: `combat_start`, `attack_hit`, `attack_crit`, `attack_miss`,
`attack_fumble`, `ability` (com dados), `item_heal` (com dados),
`item_use`, `down`, `stabilize` (com d20), `death` (com d20), `flee`,
`side_wiped`, `combat_end`. Cada evento traz campos estruturados (`d20`,
`atk_total`, `ca`, `dmg`, `dmg_dice`, `crit`, `rolls`, `total`,
`hp`/`hp_max`), úteis para a narração final da IA.

---

## Tela de combate tática (Pergaminho Épico)

Quando `combat_mode == "tela"`:

- A IA monta a cena → chama `roll_initiative` → `is_active` vira true.
- O cliente (`combat.js`) detecta via `Combat.sync()` (chamado em
  `renderMemory` após qualquer tool de estado).
- Um overlay full-screen abre no tema **"Pergaminho Épico"** (paleta
  creme/dourado/vermelho, Playfair Display + Lora): cabeçalho com título e
  a ordem de iniciativa em pílulas; campo de batalha **heróis × Vs ×
  inimigos** com cards de HP/MP; painel inferior dividido em **ações** +
  **Diário de Combate**; modal sobreposto no fim da luta. Responsivo,
  em telas estreitas vira coluna única.

### O que o jogador vê

```
┌── Rodada 3 │ Valerius › Goblin 2 › Elara ▶ ──────────────┐
│                                                            │
│           Goblin 2          Goblin 3                       │
│           HP 4/7            HP 7/7                         │
│                                                            │
│                   ⚔️                                        │
│                                                            │
│   Valerius           Elara ▶                               │
│   HP 18/24 MP 7/7    HP 8/11 MP 10/10                      │
│                                                            │
│ ┌── Log ────────────────────────────────────────────────┐  │
│ │ [R3] Valerius → Goblin 2 (Espada Longa): d20=15 +3+2 │  │
│ │      = 20 vs CA 14 • ACERTO • dano [5]+3 = 8 → HP 12→4│  │
│ │ [R3] Goblin 2 → Elara: d20=8 +1 = 9 vs CA 16 • ERROU │  │
│ └──────────────────────────────────────────────────────┘  │
│                                                            │
│ Sua vez: Elara , Ação ○ Bônus ○                          │
│ [⚔️ Atacar (Ação)] [✨ Habilidade] [🧪 Item] [🛡️ Defender] │
│ [💨 Fugir]  [💬 Ação Livre]  [⏭️ Encerrar Turno]          │
└────────────────────────────────────────────────────────────┘
```

### Submenu ⚔️ Atacar, escolha de arma

- Lista armas **equipadas** (principal + secundária) + **armas do inventário**
  (espada, arco, besta, adaga, lança, machado, martelo, cajado, etc.) +
  "Ataque desarmado".
- Depois mostra o picker de alvo. A intenção `{action:'attack', actor,
  target, weapon}` vai para `/api/combat/action`.

### Submenu ✨ Habilidade, só ativas, etiquetadas

- **Filtra passivas** (Proficiência: Atletismo, Estilo de Combate,
  Resistência a X, Idioma…), vão pra `passivas` (só info, sem botão).
- Cada ativa traz etiqueta `[Ação]` (azul) ou `[Bônus]` (verde).
- Desabilitada se o slot já foi gasto.

### Submenu 🧪 Item, consumíveis classificados

- Filtra inventário por **consumíveis** (`_CONSUMABLE_KEYWORDS`: poção,
  pergaminho, óleo, frasco, ácido, fogo alquímico, água benta…) e exclui
  armas/armaduras/utilidades.
- Poções de cura: detecta automaticamente o nível (básica → 2d4+2, maior →
  4d4+4, superior → 8d4+8, suprema → 10d4+20). Rola, aplica cura, gasta o
  slot **Bônus** (regra 2024).
- Cura abre picker de alvo (qualquer membro do grupo, **inclusive
  inconsciente**, restaura status para `vivo`). Outros itens aplicam no
  próprio personagem.
- Consome 1 unidade; remove do inventário quando qtd zera.

### Outros botões

- 🛡️ **Defender**, Esquivar (Dodge), Ação.
- 💨 **Fugir**, Ação + encerra turno (sai do combate, status "fugiu").
- 💬 **Ação Livre**, fecha temporariamente o overlay, devolve foco ao chat;
  o jogador descreve o improviso e a IA arbitra (`make_skill_check`, etc.).
  O overlay reabre no próximo `sync()` se o combate ainda estiver ativo.
- ⏭️ **Encerrar Turno**, força avanço sem gastar slot.

### Fechar a tela durante o combate

O botão **✕** no cabeçalho fecha a tela **sem encerrar o combate**: o
jogador pode acessar o menu e sair do jogo no meio da luta. O combate fica
pausado e o `combat_state` é persistido; ao voltar, retoma de onde parou.
Uma pílula flutuante **"⚔️ Retomar combate"** reabre a tela. A flag
`_userClosed` impede a reabertura automática no `sync()` enquanto o jogador
mantém a tela fechada.

### Turno de inimigo

`execute_npc_turn()` roda **sem LLM**. O cliente detecta `current_is_party
== false` e chama automaticamente após ~650ms (com teto de segurança de 80
turnos NPC consecutivos para evitar loop). O motor:

- Aplica a estratégia (`agressivo`/`tático`/`covarde`/`aleatório`/`suporte`).
- Covarde foge se HP < 25%.
- Escolhe o alvo e executa **quantos golpes o Multiattack conceder**,
  alternando entre os ataques do stat block: o urso-coruja faz *"um com o
  bico e um com as garras"* (1d10 e 2d8), não o mesmo golpe duas vezes.
- Se o alvo cai no meio da investida, os golpes restantes **redirecionam**
  para outro alvo de pé; não sobrando ninguém, a investida é interrompida.
- Avança o turno **uma vez**, no último golpe (nunca uma vez por golpe).

### Painel de fim (não fecha bruscamente)

Quando um lado é derrotado, o servidor **captura o resultado** (vitória/
derrota, sobreviventes, caídos) antes de `end_combat()` limpar a ordem. O
cliente renderiza um painel com:

- 🏆 **Vitória!** / 💀 **Derrota…**
- Duas colunas: **De pé** vs **Caídos**, com status e HP.
- Botões: **Continuar a história ▶** (chama `/api/combat/recap`, envia o
  texto ao chat → a IA narra a luta inteira + saque) e **Apenas fechar**.

### Recap

`combat_recap_payload()` monta um texto com:

```
[COMBATE RESOLVIDO NA TELA TÁTICA]
Desfecho: vitoria.
Narre a luta INTEIRA de forma cinematográfica e contínua (não turno a
turno) com base no log abaixo, e gere o SAQUE dos inimigos derrotados
(use add_item/modify_currency se houver). Depois siga a história.

- Eventos
[R1] Valerius → Goblin 4 (Espada Longa): 🎲 d20=20 +3+2 = 25 vs CA 5 ...
[R1] Goblin 4 caiu inconsciente
…

- Estado final
Valerius [grupo]: vivo (24/24 HP)
Goblin 4 [inimigo]: inconsciente (0/7 HP)
```

O `result` é limpo no servidor após a busca, não reaparece. O agente em
modo tela tem instrução específica pra reconhecer esse marcador e narrar a
luta inteira de uma vez. O texto do recap é **ciente do desfecho**: numa
vitória instrui saque (`add_item`/`modify_currency`) + `grant_xp()`; numa
derrota instrui explicitamente **não** gerar saque nem XP.

---

## Tools, o catálogo do agente

A lista completa exposta ao agente (`tools.py:ALL_TOOLS` = narrativas +
`tools_dnd.DND_TOOLS`):

### Narrativas (`rpg/tools.py`)

| Função | Função no jogo |
|---|---|
| `save_character` | Cria/atualiza NPC ou personagem do grupo |
| `get_character` / `list_characters` | Lê personagem(ns) |
| `update_character_status` | Muda status (vivo, ferido, morto, aliado…) |
| `add_party_member` / `remove_party_member` / `list_party` | Gerencia o grupo |
| `save_location` / `get_location` / `list_locations` | Locais |
| `save_event` / `get_recent_events` | Eventos importantes |
| `update_world_state` / `update_story_summary` | Estado do mundo, resumo |
| `set_flag` / `get_flag` / `list_flags` / `clear_flag` | Variáveis de quest |
| `add_diary_entry` / `get_diary` | Diário da campanha |
| `get_scene_context` | Contexto da cena (uso a cada turno) |
| `get_full_context` | Dump completo (reancoragem após retomar) |

### D&D (`tools_dnd.py`)

| Função | O que faz |
|---|---|
| `roll_dice(sides, count, modifier)` | Rola dados genéricos |
| `create_character_sheet(...)` | Cria ficha D&D completa (nível 1–20) |
| `get_character_sheet` / `get_combat_status` | Lê ficha / status do combate |
| `modify_hp(char, amount, reason, damage_type)` | Aplica HP (positivo cura, negativo dano com tipo) |
| `modify_mana(char, amount, reason)` | Aplica mana |
| `grant_temp_hp(char, amount, source)` | PV temporários (não acumulam: vale o maior) |
| `make_skill_check(char, atr, dc, adv/dis, skill, player_roll)` | Teste de atributo (PC informa o d20; NPC o sistema rola) |
| `social_check(char, skill, dc, player_roll)` | Jogador informa o d20 |
| `attack_roll(atacante, alvo, arma, dado)` | Ataque completo: d20 → dano → KO |
| `learn_ability(char, nome, desc, mana, dado)` | Adiciona habilidade |
| `learn_spell(char, nome)` | Busca magia no Open5e, valida classe/nível |
| `use_ability(char, hab, alvo, save_*)` | Magia/skill, com saving throw opcional, suporta pool e condição |
| `apply_condition` / `remove_condition` | Condições com efeitos automáticos |
| `equip_item` / `unequip_item` | Equipamento, recalcula CA |
| `add_item` / `remove_item` / `list_inventory` | Inventário |
| `identify_item(char, nome)` | Valida item mágico contra o SRD |
| `modify_currency(char, "ouro"\|"prata"\|"cobre", amount)` | Moedas |
| `roll_death_save(char, player_roll)` | Teste de morte (PC informa o d20; NPC o sistema rola) |
| `short_rest` / `use_hit_die` / `long_rest` | Descansos |
| `grant_xp(char, amount, reason)` | XP + level up automático |
| `set_stat(char, stat, value)` | ASI manual; recalcula derivados |
| `choose_feat(char, feat_name)` | Talento via SRD, valida pré-requisitos |
| `set_feature_choice(char, feature, escolha)` | Subescolha de habilidade/arquétipo (Estilo de Combate, domínio, etc.) |
| `roll_initiative(nomes)` | Inicia combate |
| `next_turn` / `end_combat` | Controle de turno |
| `recruit_character(npc, role)` | NPC vira aliado (com guarda de nível) |
| `spawn_monster(slug, display, quantity)` | Cria monstro com stats reais |
| `set_npc_strategy` / `execute_npc_turn` | Turno de NPC automático |
| `resolve_saving_throw(target, atr, dc, roll, dmg, damage_type)` | Macro-tool de save interativo |
| `suggest_encounter(level, size, difficulty)` | Sugere encontro balanceado |

Cada função tem **docstring detalhada**, a ADK gera o schema JSON
automaticamente a partir dela, que vira a descrição que o LLM enxerga.

---

## Endpoints HTTP

`server.py` (~2500 linhas, todas as rotas atrás de `@require_auth` quando
acessam memória):

### Autenticação

- `POST /api/auth/register` `{email, password}` → cria conta (precisa
  confirmar e-mail).
- `POST /api/auth/login` → `{access_token, refresh_token}`.
- `POST /api/auth/refresh` `{refresh_token}`.
- `POST /api/auth/confirm`, pós-confirmação de e-mail Supabase.

### Campanhas

- `GET /api/campaigns`, lista.
- `POST /api/campaigns`, cria (com payload do wizard).
- `GET /api/campaigns/<name>` / `PUT` / `DELETE` / `POST /rename`.
- `POST /api/campaigns/generate-lore`, IA gera mundo a partir de uma ideia.
- `POST /api/campaigns/import`, importa JSON gerado por outra IA.

### Sessão

- `POST /api/session/start` `{campaign, model, campaign_type, story_mode,
  story_input, genre, google_api_key, deepseek_api_key}` → cria runner,
  retorna recap se for retomada.
- `POST /api/session/end` → salva, descarta sessão.

### Chat (streaming SSE)

- `POST /api/chat` `{message, registrar}` → stream de eventos:
  - `tool_call`, `tool_result`, `text`, `correction`, `violations`,
    `level_up`, `retrying`, `quota`, `error`, `done`.

### Memória (CRUD para a sidebar)

- `GET /api/memory`, dump consolidado.
- `PUT/DELETE /api/memory/characters/<name>`,
  `/locations/<name>`, `/flags/<name>`, `/party/<name>`,
  `/events/<index>`, `/diary/<index>`, `/world`.

### Diário

- `POST /api/diary/export`, devolve um `.md`.

### D&D auxiliares

- `GET /api/dnd/class-spells?classe=mago&level=3`, magias do SRD.
- `GET /api/dnd/items/search?q=...`, busca item.
- `GET /api/dnd/monsters/search?q=...`, busca monstro.
- `GET /api/dnd/class-features?classe=guerreiro&nivel=5`, features.
- `GET /api/dnd/feature_variants`, catálogo de subescolhas (variantes/arquétipos).
- `POST /api/dnd/feature_choice`, aplica/remove uma subescolha de habilidade.

### Combate em tela

- `GET /api/combat/state` → snapshot completo.
- `POST /api/combat/action` `{action, actor, target, weapon, ability, item}`
  → executa intenção, retorna `{ok, message, snapshot}`.
- `GET /api/combat/recap` → texto para a IA narrar a luta + limpa
  `result`.
- `GET/POST /api/combat/mode` → lê/grava `combat_mode`.

### Outros

- `GET /api/ollama/models`, descobre modelos locais.

### PWA (sem autenticação)

- `GET /healthz` → `{status: "ok"}`, health check trivial usado pela tela de
  cold start para saber quando o servidor acordou.
- `GET /manifest.webmanifest`, manifesto do app (nome, ícones, tema).
- `GET /sw.js`, service worker, servido da raiz (escopo `/`) com header
  `Service-Worker-Allowed: /`.
- `GET /offline.html`, tela "Acordando o servidor…" servida pelo service
  worker durante o cold start.

---

## Frontend

4 páginas estáticas + 5 scripts JS (+ os assets de PWA):

### Páginas

- **`static/login.html`**, login/cadastro (book/tome theme, Caveat font),
  confirma e-mail via hash do Supabase.
- **`static/menu.html`**, lista de campanhas, wizard de criação (mundo +
  personagens), edição, importação por prompt, escolha de modelo e chave
  de API.
- **`static/game.html`**, chat principal + sidebar (Mundo, Enciclopédia,
  Diário) + dice tray + tela de combate (`combat.js`).
- **`static/offline.html`**, tela "Acordando o servidor…" do PWA (CSS/JS
  inline, autossuficiente), exibida pelo service worker durante o cold
  start do Render; faz polling em `/healthz` e recarrega sozinha quando o
  servidor responde.

### Scripts

- **`utils.js`**, `authFetch` com refresh silencioso, sistema de toast/
  dialog, temas (Pergaminho, Noite de Tinta, Ardósia…), fontes
  configuráveis, painel de configurações unificado, guia de ajuda "Como
  Jogar" (com a seção **"Instalar como aplicativo"**, que aciona o
  instalador nativo no Android e mostra instruções do Safari no iOS).
- **`auth.js`**, login/registro/refresh, processamento do link de
  confirmação Supabase.
- **`menu.js`** (~4290 linhas), wizard de campanha (etapa 1 mundo, etapa
  2 personagens com seleção D&D), edição completa de campanha, busca de
  monstros/magias/features na hora.
- **`game.js`** (~2040 linhas), chat com SSE, parser de eventos do
  agente, comandos `/` (autocompletar `/ficha`, `/inventário`,
  `/habilidades`, `/status`, `/condicoes`, `/combate`, `/rolar`,
  `/personagens`, …), modal de edição rica (ficha D&D inline, level up,
  busca de spells/feats), turn tracker, dice tray do jogador.
- **`combat.js`** (~580 linhas), overlay "Pergaminho Épico", action bar com
  economia 5e, submenus de arma/habilidade/item, picker de variantes,
  modal de fim, botão de fechar + pílula de retomar, toggle de modo.
  **Zero regra de jogo no cliente**, só renderiza snapshot e envia intents.

### Tema

`static/css/style.css` (~1640 linhas), visual de livro/tomo (Lora,
Playfair Display, Caveat) + tela de combate "Pergaminho Épico", 7 temas
alternáveis, totalmente responsivo (`--app-height` cobre o quirk do iOS
Safari).

---

## PWA e instalação

O app é um **Progressive Web App**: pode ser instalado na tela inicial
(Android e iOS) e aberto em tela cheia, como um aplicativo nativo, sem
passar por nenhuma loja.

### Arquivos

- **`static/manifest.webmanifest`**, nome, ícones, `display: standalone`,
  `theme_color`, `start_url: /menu.html`. Servido em `/manifest.webmanifest`
  (a extensão `.webmanifest` evita o `*.json` do `.gitignore`).
- **`static/sw.js`**, o service worker. Servido da **raiz** (`/sw.js`) para
  o escopo cobrir `/menu.html` e `/game.html`.
- **`static/offline.html`**, a tela "Acordando o servidor…".
- **`static/icons/`**, ícones PNG (192/512, versão `maskable` e
  `apple-touch-icon` de 180px).
- Meta tags PWA (`manifest`, `theme-color`, `apple-mobile-web-app-*`) e o
  registro do service worker estão no `<head>` de `login/menu/game.html`.

### Service worker, conservador por design

`sw.js` é deliberadamente cauteloso para **nunca** interferir em
autenticação nem no streaming SSE do `/api/chat`:

- **Navegações** (`mode === "navigate"`), *network-first com timeout* de
  ~4,5s. Servidor quente → página fresca (respeita o `no-store` do menu);
  servidor frio/sem rede → serve a tela de despertar.
- **Assets `/static/*`**, *stale-while-revalidate* (resposta instantânea do
  cache + atualização em segundo plano).
- **Tudo o mais** (`/api/*`, `/healthz`, terceiros, métodos não-GET), passa
  direto para a rede, sem cache.

### Cold start do Render (free tier)

Quando o serviço está adormecido, a primeira requisição demoraria 30–60s.
Em vez de a navegação ficar pendurada (e, no iOS standalone, possivelmente
estourar o timeout com erro), o service worker mostra `offline.html`, que:

1. abre **instantaneamente** do cache, com a marca do app;
2. faz polling em `/healthz` a cada ~3s (uma verificação por vez, sem
   acúmulo) — esse próprio ping é o que acorda o Render;
3. recarrega a URL original assim que o servidor responde 200, já com o
   backend quente.

O wakeup do Render **não é alterado**; a melhoria é puramente de UX no
cliente. O primeiro acesso de sempre (antes do SW instalar) ainda pega o
cold start "cru"; a partir daí a tela amigável entra em ação.

### Instalar como aplicativo

A seção **"📲 Instalar como aplicativo"** no guia de ajuda ("Como Jogar",
em `utils.js`) é adaptativa:

- **Android (Chrome/Edge)**, capta o evento `beforeinstallprompt` e mostra
  um botão **"Instalar agora"** que dispara o instalador nativo.
- **iPhone/iPad (Safari)**, como o iOS não expõe essa API, mostra o passo a
  passo (Compartilhar → "Adicionar à Tela de Início").
- **Já instalado** (`display-mode: standalone`), esconde tudo e confirma que
  o app já está rodando instalado.

---

## Testes e garantias

A suíte roda com **pytest** (212 testes). O `tests/conftest.py` isola tudo de rede
e de banco: o `database` (Supabase) vira stub e a camada SRD entra em modo
offline, então nenhum teste depende da internet. Ele também expõe a fábrica
`criar_ficha()` e as fixtures `campanha`/`povoar`, para um teste de motor
montar um combate em três linhas.

**Como substituir um submódulo por um dublê.** Com o código dentro do pacote
`rpg/`, mexer só em `sys.modules` não basta: `from rpg import memory` resolve
pelo **atributo** do pacote quando ele já existe. Use
`rpg.registrar_duble(nome, modulo)`, que faz as duas coisas. É por isso que
`rpg/__init__.py` é deliberadamente vazio de imports — se ele importasse os
submódulos na carga, os verdadeiros venceriam a corrida e a substituição não
teria efeito.

As duas suítes legadas forçam `RPG_SRD_OFFLINE=1` por padrão. Sem isso,
rodá-las à mão sai para a api.open5e.com e elas travam quando a API está
lenta — o que já aconteceu de verdade, e nunca aparecia sob o pytest porque o
conftest já forçava offline. Para exercitar a rede de propósito:
`RPG_SRD_OFFLINE=0 python tests/legacy/tests.py`.

```bash
pip install -r requirements-dev.txt
pytest                  # tudo
pytest -m "not slow"    # sem o fuzzer
```

### `tests/legacy/tests.py`, suíte funcional

13 blocos cobrindo:
- Funções matemáticas base (modifier, proficiência, parse_dice).
- Criação de personagem em vários níveis.
- Combate simulado (Kael + Ignis vs Goblins) com initiative, ataques,
  habilidades e KOs.
- XP / level-up.
- Equipamento, condições, descansos, moedas.

Continua rodável à mão (`python tests/legacy/tests.py`) e agora **sai com código != 0**
quando algum check falha. Isso não era verdade antes: o script só imprimia
`✗` e saía com 0, e tinha 5 checks falhando havia tempos sem ninguém ver —
higiene de fixture, o Goblin morria num bloco e os seguintes testavam um
cadáver. Resolvido com o helper `revive()`; hoje são 70/70.

`--json=<caminho>` despeja os resultados. É o que o `tests/conftest.py` usa para
transformar **cada check num caso de pytest com nome próprio**, em vez de
tudo virar um único "o script falhou" — sem reescrever ~50 mil caracteres
de asserts.

### `test_monster_attacks.py` / `test_open5e_cache.py`

Testes nativos das garantias mais recentes:

- O monstro rola o dado do stat block, nunca o 1d6 do fallback (a asserção
  conta as faces roladas: `[(1,8), (1,8)]` para as garras 2d8).
- A ação Multiattack não vira arma; arma principal nunca fica sem dado.
- Multiattack executa N golpes, alterna entre os ataques e avança o turno
  uma vez só — inclusive quando o alvo cai no primeiro golpe.
- Cache do SRD: acerto e 404 são cacheados, erro de rede não é, `get()`
  nunca levanta exceção.

### `test_damage_types.py` / `test_concentration.py` / `test_reactions.py`

- Imunidade zera, resistência corta pela metade (mas **nunca zera um acerto**),
  vulnerabilidade dobra, resistência e vulnerabilidade se cancelam, imunidade
  vence as duas, e dano sem tipo nunca é modificado.
- Arma mágica e material especial furam a resistência qualificada; arma
  mágica **não** fura resistência incondicional.
- PV temporários absorvem antes dos PV reais, entram depois do modificador de
  tipo, e não se acumulam.
- Só uma concentração por vez; CD do teste = `max(10, dano/2)`; cair a 0 PV
  derruba sem teste; dano absorvido ou anulado por imunidade não ameaça.
- Reação recarrega por rodada; aliado não bate em aliado que foge; quem já
  gastou a reação não reage; o bote para quando o fugitivo cai.

### `tests/legacy/tests_combat_fuzz.py`, fuzzer de invariantes

Dois modos:

- **engine**: chama `attack_roll`/`next_turn`/`death_save` diretamente em
  milhares de combates aleatórios, com mortes no meio, ações fora de
  ordem, `next_turn` repetido.
- **screen**: dirige tudo via `combat_action`/`combat_snapshot`, o exato
  caminho que o frontend usa.

Em cada passo, verifica:
- `turn_token` monotônico, passo 0 ou 1.
- Rodada nunca regride; sobe no máximo 1 por avanço real.
- Ator atual nunca está fora de combate (exceção legítima: transição
  terminal `end_combat()` resetando `round=1`).
- Sem estado mudando "sem avanço de token".
- Snapshots sempre JSON-serializáveis.
- Log com cap respeitado (≤ 300).
- Combate **sempre termina** (sem loop infinito).
- Ações de jogador fora de ordem são recusadas sem aplicar dano nem
  avançar.

**Métrica atual** (8000 combates motor + 4000 combates tela, seeds variados):
~307k chamadas de tool, **0 violações** em todos os invariantes.

### Validador narrativo (`rpg/validator.py`)

Roda em toda resposta do agente; emite avisos (não interrompe) para:
- Personagem morto narrado como ativo.
- Personagem desaparecido/preso interagindo presencialmente.
- Local mencionado mas não salvo.
- Contradições com flags ("portao_aberto=fechado" + texto descreve aberto).
- NPC novo introduzido sem `save_character`.

Os avisos aparecem na sidebar (aba Mundo → Validação).

### Verificador mecânico (`server.py:_verify_agent_response`)

Já descrito, força correção quando a IA narra mecânica sem ferramenta
(7 regras, listadas acima).

---

## Estrutura de arquivos

A raiz guarda só o ponto de entrada e a configuração. O código da aplicação
vive no pacote `rpg/`, os testes em `tests/`, os utilitários em `scripts/`.

O pacote se chama `rpg` e não `app` de propósito: `server.py` precisa expor
uma variável chamada `app` (a instância do Flask que o Render sobe com
`gunicorn server:app`), e ter as duas coisas com o mesmo nome no mesmo
arquivo é armadilha de leitura garantida.

**Nada no Render precisa mudar.** `server.py` continua na raiz, então
`gunicorn server:app` e `pip install -r requirements.txt` seguem idênticos —
`server:app` aponta para a variável Flask dentro de `server.py`, nunca para
o nome do pacote. Também não há variável de ambiente nova.

```
.
├── server.py              Flask + SSE + endpoints + segurança (~2500 linhas)
│                          Entrypoint do Render: `gunicorn server:app`
├── pytest.ini             Configuração do pytest (testpaths, pythonpath)
├── requirements.txt       Dependências fixadas (é o que o Render instala)
├── requirements-dev.txt   Dependências de teste (pytest)
├── render.yaml            Deploy no Render (gunicorn + envs Supabase)
│
├── rpg/                   Código da aplicação
│   ├── __init__.py        Vazio de imports de propósito + registrar_duble()
│   ├── agent.py           Instruções de estilo + create_agent
│   ├── tools.py           Tools narrativas + ALL_TOOLS
│   ├── tools_dnd.py       Motor D&D 5e + combate (~7900 linhas, 38 tools)
│   ├── memory.py          Estado por sessão, proxy, persistência
│   ├── database.py        Camada Supabase
│   ├── auth.py            Supabase Auth + @require_auth
│   ├── session.py         Runner ADK
│   ├── validator.py       Validador narrativo pós-resposta
│   └── open5e.py          Acesso ao SRD: sessão, retry, cache, offline
│
├── tests/                 Suíte pytest
│   ├── conftest.py        Isolamento + fábrica criar_ficha + ponte legada
│   ├── test_legacy_dnd.py     Portão: um caso por check do tests.py
│   ├── test_fuzz_invariants.py  Portão: roda o fuzzer na suíte
│   ├── test_monster_attacks.py  Dado de dano de monstro + Multiattack
│   ├── test_open5e_cache.py     Comportamento do cache do SRD
│   ├── test_damage_types.py     Tipos de dano, resistências, PV temporários
│   ├── test_concentration.py    Concentração em magias
│   ├── test_reactions.py        Reação e ataque de oportunidade
│   └── legacy/            Suítes em formato de script (não coletadas)
│       ├── tests.py             Suíte funcional (13 blocos, 70 checks)
│       └── tests_combat_fuzz.py Fuzzer de invariantes de combate
│
├── scripts/               Utilitários fora do runtime
│   ├── capturar_telas.py  Captura screenshots de todas as telas
│   └── temp.json          Campanha de exemplo usada nas capturas
│
└── static/
    ├── login.html
    ├── menu.html
    ├── game.html
    ├── offline.html       Tela "Acordando o servidor…" (PWA cold start)
    ├── manifest.webmanifest  Manifesto do PWA
    ├── sw.js              Service worker (servido em /sw.js)
    ├── icons/             Ícones do PWA (192/512/maskable/apple-touch)
    ├── css/style.css      Tema livro/tomo + tela de combate
    └── js/
        ├── utils.js       authFetch, toast, dialog, temas, fontes, guia/PWA
        ├── auth.js        Login / cadastro / confirmação
        ├── menu.js        Wizard, edição, importação, modelos
        ├── game.js        Chat, comandos, sidebar, dice tray
        └── combat.js      Tela tática "Pergaminho Épico"
```

---

## Configuração e execução

### Pré-requisitos

- Python 3.10+
- Projeto Supabase com:
  - Auth habilitado (confirmação de e-mail recomendada).
  - Tabela `campaigns(user_id uuid, name text, data jsonb,
    updated_at timestamptz)` + chave composta `(user_id, name)`.
  - RLS configurada (opcional, service key é usada do servidor).

### Variáveis de ambiente

```bash
export SUPABASE_URL="https://xxxx.supabase.co"
export SUPABASE_ANON_KEY="..."           # GoTrue (login do navegador)
export SUPABASE_SERVICE_KEY="..."        # Postgrest (servidor escreve campanhas)

# Opcional, modelos locais via Ollama
export OLLAMA_API_BASE="http://localhost:11434"
```

As chaves de **Gemini** e **DeepSeek** são fornecidas pelo usuário no menu
(persistidas em `localStorage` e injetadas em `/api/session/start`).

### Dependências

O `requirements.txt` do repositório fixa as versões testadas (Python 3.10+).
Núcleo mínimo:

```
Flask, gunicorn, google-adk (1.31.1), google-genai, litellm,
postgrest, gotrue, authlib, requests
```

```bash
pip install -r requirements.txt
```

Para desenvolver e rodar os testes, `requirements-dev.txt` acrescenta o
`pytest`. Ele fica **fora** do `requirements.txt` de propósito: esse é o que
o Render instala em produção, e o runtime não precisa de pytest.

```bash
pip install -r requirements-dev.txt
```

### Rodar local

```bash
python server.py
# Acesse http://0.0.0.0:7777
```

### Deploy (Render)

O repositório vem com `render.yaml` configurado:

```yaml
services:
  - type: web
    runtime: python
    buildCommand: pip install -r requirements.txt
    # --preload: importa o app no master antes de abrir a porta, evita o
    # "Port scan timeout" do Render (porta aberta = app pronto).
    startCommand: gunicorn server:app --worker-class gthread
                  --threads 4 --timeout 120 --preload --bind 0.0.0.0:$PORT
    envVars:
      - SUPABASE_URL / SUPABASE_ANON_KEY / SUPABASE_SERVICE_KEY
```

As chaves do Supabase ficam nos *Environment* do Render. As chaves de
Gemini/DeepSeek vêm do usuário (localStorage do navegador), não do servidor.

### Rodar testes

```bash
pytest                    # suíte completa (110 testes)
pytest -m "not slow"      # sem o fuzzer
pytest tests/test_monster_attacks.py -v

python tests/legacy/tests.py   # suíte funcional isolada (sai != 0 se falhar)
python tests/legacy/tests_combat_fuzz.py both 10000        # fuzz completo, antes de publicar
python tests/legacy/tests_combat_fuzz.py engine 5000 1234  # só motor
python tests/legacy/tests_combat_fuzz.py screen 5000 1234  # só caminho da tela
```

O `pytest` roda o fuzzer com um N modesto para a suíte continuar rápida; o
fuzz cheio (10k combates) fica como passo manual antes de publicar.

---

## Limitações conhecidas

Documentadas honestamente, coisas que sei que poderiam estar melhores:

- **Restrição de magia "Bônus + Ação"** (PHB: se lançar magia Bônus, sua
  Ação só pode ser cantrip) **não está modelada**. Exige flag `is_cantrip`
  nas habilidades. Default tolerante.
- **Detecção de habilidades Bônus por nome** cobre ~12 padrões 5e
  conhecidos. Habilidades caseiras com nomes incomuns ficam como Ação.
  Fix futuro: campo `tipo_acao` explícito em `learn_ability`/`learn_spell`.
- **Itens consumíveis genéricos** (pergaminhos, ácido, fogo alquímico) são
  consumidos + logados, mas o efeito mecânico é narrado pela IA no recap
  (não tem regra inline). Poções de cura têm regra mecânica direta.
- **Reação só dispara na fuga.** A Reação existe na economia e o ataque de
  oportunidade funciona, mas o único gatilho é sair do combate — sem
  posicionamento no jogo, não há "afastar-se de um inimigo adjacente" para
  detectar. Shield e Counterspell (reações *escolhidas* pelo jogador) ainda
  não existem: exigem interromper o turno de outra criatura para perguntar.
- **Arma customizada de jogador cai em 1d6.** `combat_action("attack")`
  passa um dado padrão e conta com `_fetch_weapon_data` para corrigi-lo;
  isso funciona para armas reais do SRD, mas uma arma inventada pela
  narrativa ("Lâmina do Crepúsculo") não é encontrada e fica no fallback.
  É a mesma classe de bug já corrigida do lado dos monstros, e o conserto é
  o mesmo: gravar o dado na ficha em vez de redescobri-lo a cada golpe.
- **Tipo de dano em magia depende da descrição.** Ataques com arma e stat
  blocks de monstro têm o tipo resolvido com segurança; magias da ficha são
  lidas do texto ("3d6 dano de fogo"). Uma habilidade caseira com descrição
  vaga sai sem tipo — e dano sem tipo não sofre modificador nenhum, que é o
  comportamento seguro, mas silencioso. Fix futuro: campo `tipo_dano`
  explícito em `learn_ability`.
- **Teste de concentração é rolado pelo sistema**, inclusive para
  personagens jogáveis, ao contrário dos testes de perícia e de morte. O
  gatilho acontece no meio do turno do inimigo, e parar para pedir um d20
  quebraria o fluxo. O resultado é sempre mostrado.
- **Prata/adamante são detectados pelo NOME do item.** "espada prateada"
  fura a imunidade do lobisomem; "espada longa (revestida em prata)" não.
  Enquanto o inventário não tiver campo de material, é heurística de texto.
- **Sub-features de arquétipo**, só as de efeito numérico claro têm hook no
  motor (faixa de crítico, Golpe Divino, Resistência Dracônica, Estilo de
  Combate). Manobras, reações e recursos de pool (Ki, Dado de Superioridade)
  ficam como descrição que a IA-mestre arbitra; exigiriam um subsistema de
  reações/recursos.
- **Tokens em `localStorage`**, o XSS está mitigado (sanitização DOMPurify),
  mas a migração do refresh token para cookie `httpOnly` é um item pendente
  de endurecimento.
- **`main.py` (CLI)** foi removido, o sistema só roda via servidor web.
- **Multimodal**: a IA hoje só lê/escreve texto (sem imagens).
- **Reset do `_active_by_user` em memória**: se o processo do servidor
  reinicia, sessões ativas perdem o bind, o próximo request reconstrói o
  contexto, mas a campanha "ativa" do usuário precisa de um `start_session`
  novo. Em produção long-running isso não é problema; em dev com hot-reload
  pode confundir.

---

## Sobre o projeto

Construído com Python (Flask + Google ADK), Supabase (Auth + Postgres),
e o SRD da Open5e como fonte de verdade para raças/classes/itens/magias/
monstros. O foco é **mecânica fiel + narrativa imersiva**, com a IA tratada
como **agente que age sobre o estado**, não como gerador de texto solto.

A confiança nas garantias de combate vem de **fuzzing real**: o motor
foi exercitado com centenas de milhares de combates aleatórios e
invariantes verificados a cada passo. O resto se apoia em testes
funcionais, validadores determinísticos e o princípio de que **a IA pode
narrar livremente, mas não decide números**.
