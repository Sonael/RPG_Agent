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
│  tools.py + tools_dnd.py  (84 ferramentas expostas)         │
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
    # Onda 3 — posicionamento. Ausentes = combate sem zonas.
    "zonas":      [str],              # trilha; vizinhas são adjacentes
    "zona_desc":  {zona: str},
    "posicoes":   {char_key: zona},
  },
  # ── Onda 4 ───────────────────────────────────────────────────────────
  "relogio":  {"dia": int, "hora": int},   # {} = campanha nunca usou relógio
  "quests":   {chave: {titulo, descricao, status, objetivos,
                       quem_deu, recompensa, cap_inicio}},
  "lojas":    {chave: {nome, local, estoque: [{nome, preco, qtd}]}},
  "_turno":   int,                          # contador de turnos concluídos
  "_upkeep":  {tarefa: turno},              # quando cada manutenção foi feita
}
```

**Toda chave nova precisa entrar em `memory._defaults()`.** Não é organização:
`load_campaign` percorre `_defaults()` e copia só o que encontra nele. O que
ficar de fora é gravado no banco e **descartado na leitura seguinte** — foi
exatamente o que aconteceu com missões, relógio e lojas entre a onda 4 e a
correção que veio depois dela. O mesmo vale para
`server._payload_de_campanha`, a lista branca por onde passa toda campanha
criada pelo wizard ou importada de arquivo.

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

### Carga e loja

O inventário era uma lista sem peso e sem preço: dava para carregar oito
armaduras de placas e uma bigorna, e "comprar" era o mestre digitar um número
de ouro de cabeça. Duas consequências chatas — saque nunca era **escolha**
(leva tudo), e o preço do mesmo item variava conforme o humor da cena.

Peso e preço de **arma e armadura** saem de duas tabelas locais com os valores
do SRD (`_ARMAS_SRD`, `_ARMADURAS_SRD`), e a conversão de libra para quilo é
feita no motor. Fora delas, uma tabela curta de aproximação só do que aparece
numa mesa (poção, corda, tocha); depois disso o Open5e; e 0,5 kg como último
recurso.

As tabelas são locais por dois motivos concretos, os dois medidos:

- **O SRD é em inglês.** As consultas iam com o nome em português, então
  `open_shop("Forja do Torbin", "Espada Longa; Cota de Malha; Escudo")`
  respondia *"Nenhum item com preço. O SRD não conhece: Espada Longa, …"* e
  recusava o estoque inteiro. `_traduzir_para_srd` resolve o caso geral
  (reusa o `WEAPON_PT_TO_EN` que já existia e o novo campo `srd` de
  `ARMOR_TABLE`), mas a tabela local torna a loja independente da API estar
  no ar — um `HTTP 0` da Open5e não pode fechar o comércio da campanha.
- **`/v1/armor/` não tem peso.** O campo `weight` volta vazio nas 13
  armaduras; conferido uma a uma. Não existe fonte remota para isso.

Enquanto `_peso_do_srd` não era chamado por ninguém — código morto, com um
docstring que prometia o contrário —, uma Cota de Malha pesava os 0,5 kg do
último recurso em vez de 25 kg. O sistema de carga inteiro foi construído
para que armadura pesada seja uma escolha, e armadura era exatamente o que
ele não enxergava.

#### Os nomes de armadura

Ligar `ARMOR_TABLE` ao SRD expôs que três nomes estavam com a estatística de
**outra** armadura. Em pt-BR "Cota de Malha" é *chain mail* — CA 16, pesada,
75 po, 25 kg —, e a tabela dava a ela CA 14 média com bônus de DES, que é
brunea. Quem tinha os números certos era `armadura de cota de malha`, um nome
que ninguém digita. O `menu.js` já mostrava "Cota de Malha — CA 16. Armadura
pesada" no wizard: o motor era o lado errado.

| nome | antes | agora | por quê |
|---|---|---|---|
| `cota de malha` | CA 14, média | CA 16, pesada | é *chain mail* |
| `cota de placas` | CA 16 | CA 18 | é o que o wizard já prometia |
| `gibão de peles` | CA 11, leve | CA 12, média | é *hide* |

Nenhuma chave antiga foi removida — todas continuam como apelido, então nenhum
personagem salvo perde a armadura na atualização; ele passa a receber a
estatística certa. A CA só é recalculada ao equipar, importar ou salvar pelo
editor, nunca ao abrir a campanha, então a mudança não acontece no meio de uma
cena. Faltavam ainda os nomes oficiais de metade da tabela (*camisão de malha*,
*peitoral*, *brunea*, *armadura de talas*, *acolchoada*, *cota de anéis*): foram
acrescentados, e agora as 13 armaduras do SRD têm nome em português.

Dois efeitos colaterais que só apareceram na conferência cruzada:

- `escudo sagrado` é o escudo que o preset de **paladino** do wizard equipa, e
  não estava na `ARMOR_TABLE`. Todo paladino criado pelo wizard saía com 2 de
  CA a menos, calado.
- Os três call sites faziam `ARMOR_TABLE.get(nome.lower())` — casamento exato.
  Quem escrevesse `cota de aneis` sem acento ficava sem armadura nenhuma.
  Agora passam por `_armadura_na_tabela`, que ignora caixa e acento.

`wzArmorCA` em `static/js/menu.js` é o **espelho** dessa tabela: é o número que
o jogador vê no wizard, contra o número que ele recebe em jogo. Duas tabelas
independentes é o que gerou o problema, então
`test_o_wizard_promete_a_ca_que_o_motor_entrega` lê o `menu.js` de dentro do
pytest e compara entrada por entrada.

Capacidade = **FOR × 7,5 kg**. Acima da metade o personagem fica
**sobrecarregado**: desvantagem em ataques e em testes de FOR, DES e CON — não
em INT, SAB ou CAR, porque a mochila atrapalha o corpo, não o raciocínio.
Acima do total, não anda. `check_encumbrance` mostra a conta e os itens mais
pesados.

Lojas: `open_shop`, `list_shop`, `buy_item`, `sell_item`. A compra desconta da
bolsa **trocando ouro/prata/cobre sozinha** (50 pp pagam 5 po) e uma compra
recusada por falta de dinheiro não tira nada do estoque. A venda paga
**metade** da tabela: sem isso, comprar e revender pelo mesmo preço seria uma
torneira de ouro.

`open_shop` na mesma loja **acrescenta** ao estoque — item repetido tem preço
e quantidade atualizados, o resto fica. Antes ela substituía, então a segunda
chamada para pôr um item a mais apagava a loja, e o que o grupo já tinha
esgotado voltava cheio.

Cada item aceita uma **descrição** depois de `|`
(`"Amuleto do Corvo:75:1|dá vantagem em Furtividade"`), e ela viaja com o item
até o inventário de quem comprar. Sem isso a loja era desvio da conferência de
item inventado: `buy_item` chamava `add_item` sem descrição, `_tem_efeito_mecanico`
não tinha o que ler, e uma "Lâmina Rúnica de Vhar" de 200 po era arquivada como
"só sabor" — o verificador não dizia nada.

Fechar só isso não bastava, porque o mestre pode simplesmente não descrever.
Nome mágico fora do SRD **sem descrição nenhuma** agora é uma terceira
categoria (`efeito_desconhecido`), e ela é cobrada: não dá para saber se é
lembrança de família ou espada +3, e "não faz nada, é sentimental" é resposta
válida que encerra o assunto. `buy_item` entrou em `_ITEM_TOOLS` para que a
conferência rode no turno da compra, e em `stateful` para que a rodada de
correção não cobre o ouro do jogador duas vezes pelo mesmo item.

**O motor não tem categoria de loja.** Uma forja vendendo poção passa sem
aviso: `open_shop` só cuida de preço, estoque e bolsa. Quem mantém a coerência
é o mestre, e a instrução dele diz isso explicitamente. O SRD traz `category`
(`Martial Melee Weapons`, `Medium Armor`), então dá para conferir um dia —
`test_forja_pode_vender_pocao` existe para avisar quando esse limite mudar.

### Missões como objetos

Missão era `quest_flags`: um dicionário plano de string para string. Cabia
`escoltar_princesa = aceito` e mais nada — sem objetivos, sem quem mandou, sem
recompensa combinada, sem saber o que já foi feito. Na prática o jogador
perguntava "o que a gente tinha que fazer mesmo?" e a resposta dependia de o
LLM lembrar de uma conversa de vinte cenas atrás.

`add_quest`, `update_quest_objective`, `complete_quest`, `list_quests`,
`get_quest`. Um objetivo é casado por **trecho** do texto, e um objetivo que
não existe é **registrado** em vez de recusado: missão que só aceita o plano
original não sobrevive à mesa.

As flags continuam intactas e não foram tocadas — elas são boas no que fazem,
que é guardar um fato do mundo ("a ponte caiu"). Missão é outra coisa: tem
estado, partes e um fim.

As missões ativas entram no bloco de cena que o agente recebe todo turno, com
o próximo passo pendente, e aparecem na barra lateral do jogo.

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

### Descanso, relógio e exaustão

- `short_rest` (gasta metade dos hit dice; recupera HP), `use_hit_die`,
  `long_rest` (full HP/MP + hit dice + condições; bloqueado em combate).
- **Um descanso longo por 24 horas do relógio**, e ele consome 8 delas. Antes
  disso `long_rest` era um botão de vida cheia: bastava chamá-lo depois de
  cada luta, infinitas vezes por "dia", porque não havia dia. O *dia de
  aventura* do 5e — o que faz mana e poderes diários serem recurso — não tinha
  como existir. Quando o grupo inteiro dorme, o relógio anda uma vez só, não
  8 horas por personagem.
- `advance_time(horas, motivo)` / `get_world_time`. O relógio é grosso de
  propósito: **dia e hora, sem minutos**. Numa mesa narrativa o que importa é
  "amanheceu" e "vocês estão acordados há 20 horas".
- `add_exhaustion` / `remove_exhaustion`, os seis níveis do 5e com só os
  efeitos que o motor consegue cobrar:

  | nível | efeito | onde é aplicado |
  |---|---|---|
  | 1 | desvantagem em testes | `make_skill_check` |
  | 2 | deslocamento pela metade | sem Disparada |
  | 3 | desvantagem em ataques e saves | `attack_roll`, `_concentration_save` |
  | 4 | PV máximo pela metade | `_hp_max_efetivo` |
  | 5 | deslocamento zero | não sai da zona |
  | 6 | morte | `status = "morto"` |

  O nível 4 é **calculado, nunca gravado** em `vida_max`: gravar destruiria o
  valor real da ficha e não teria como voltar quando a exaustão baixasse.
  O nível 3 vale no teste de concentração porque ali o motor é quem rola —
  nos demais saves o d20 chega já rolado pelo jogador, então não há o que
  aplicar, e cobrar seria mentira. Descanso longo remove um nível.

  Ser calculado só resolve metade do problema: alguém precisa **consultar** o
  cálculo. Por um tempo `_hp_max_efetivo` era chamada num lugar só, dentro do
  próprio `add_exhaustion`, como um corte de uma vez. Todo caminho de cura
  fechava em `vida_max` cru, então o corte durava até a primeira poção:

  ```
  depois de exaustão 4   vida 20/40  | teto 20
  depois da cura         vida 40/40  | teto 20   ← o teto virou enfeite
  ```

  Hoje os cinco caminhos de cura fecham no teto efetivo: `modify_hp`,
  `short_rest`, `use_hit_die`, a cura automática de `use_ability` e o
  `long_rest`. Quando o teto morde, o texto diz por quê — sem isso a ficha
  mostra `20/40` e ninguém entende onde a cura foi parar.

  No `long_rest` a **ordem** também estava errada: ele restaurava a vida e só
  então baixava a exaustão. Quem dorme com exaustão 4 acorda com 3, e em 3 não
  há corte — acordava com metade da vida por uma exaustão que já não tinha.

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
  estratégias (agressivo, tático, covarde, aleatório, suporte, **atirador**).
  Covarde foge quando HP<25%; atirador recua uma zona quando o corpo a corpo
  o alcança, e leva o ataque de oportunidade por isso.
- **Suporte cura de verdade.** A estratégia estava documentada como "cura
  aliados com HP < 50%" desde sempre e nunca curou ninguém: caía no `else` e
  atacava. Agora procura a magia de cura na ficha, confere mana e trata o
  aliado mais ferido.
- **Atitude** (`adjust_attitude`, `get_attitude`, `list_attitudes`): o que
  cada NPC sente pelo grupo, de -100 (hostil) a +100 (leal), com histórico
  curto do motivo de cada mudança. Antes isso não existia em lugar nenhum —
  ficava no texto livre de `notes`, se o mestre escrevesse. E tem peso
  mecânico: cada 20 pontos valem 1 de CD nos testes sociais contra aquele
  NPC, com teto de ±5. Vive em `rpg/tools.py`, fora do filtro do motor:
  atitude é matéria de romance e de mistério tanto quanto de masmorra.

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

Na onda 2, sem posicionamento no jogo, o único gatilho honesto era a
**fuga**: sair do combate deixou de ser grátis, que é exatamente o que a
regra existe para impedir. Cada inimigo consciente que ainda tem a reação da
rodada faz um ataque corpo-a-corpo contra quem foge — valendo para os dois
caminhos, o NPC covarde e o jogador clicando "Fugir" na tela.

O motor redireciona: se o fugitivo cai no primeiro bote, os demais não
desperdiçam a reação num corpo no chão.

Com as zonas da onda 3 a regra ganhou o gatilho de verdade: **sair de uma
zona onde há inimigo consciente também provoca**, e só reage quem está
naquela zona — senão o arqueiro do outro lado do pátio daria bote em quem
nunca esteve ao alcance dele.

### Zonas: posicionamento sem grid

O combate não tinha lugar nenhum. Todos alcançavam todos, corpo a corpo
acertava o arqueiro do outro lado do salão, e o ataque de oportunidade só
existia na fuga porque não havia movimento que ele pudesse punir.

Grid quadriculado seria pior que o problema: exigiria coordenadas do LLM a
cada turno e uma tela de tabuleiro. Zonas dão o que importa — perto/longe,
quem está trancado com quem, terreno com nome — ao custo de uma palavra por
combatente.

Topologia **linear**: as zonas formam uma trilha e a adjacência são os
vizinhos na lista. `["Portão", "Pátio", "Sacada"]` → Portão↔Pátio = 1,
Portão↔Sacada = 2.

| distância | regra |
|---|---|
| mesma zona | corpo a corpo vale; tiro sai com **desvantagem** (inimigo colado) |
| adjacente | só à distância, sem penalidade |
| 2 ou mais | só à distância, com desvantagem (alcance longo) |

Ferramentas: `set_battlefield` (2 a 6 zonas; grupo na primeira, inimigos na
última), `describe_battlefield`, `move_combatant` (uma zona; `dash=True` para
duas, gastando a Ação).

Três decisões que valem registro:

- **Distância desconhecida devolve `None`, não "longe".** Quem nunca foi
  posicionado não sofre penalidade inventada: o motor não pode cobrar uma
  regra a partir de dado que não tem.
- **A recusa de alcance vem antes de qualquer rolagem.** Recusar depois já
  teria mudado o estado.
- **Tudo é opcional.** Sem `set_battlefield` chamado, `cs["zonas"]` não existe
  e o combate se comporta como na onda 2. Campanhas em andamento não mudam de
  regra no meio do caminho.

### Chefes: recarga e ações lendárias

Duas coisas que separam um chefe de um saco de PV.

**Recarga** (`set_recharge_ability`) é o "Recharge 5–6" do 5e: o sopro do
dragão não é usável todo turno nem uma vez por luta — no início de cada turno
dele rola-se 1d6 e o poder volta se der 5 ou 6. É o que faz o grupo jogar
contra um relógio que ninguém controla. `execute_npc_turn` usa o poder assim
que ele estiver carregado: é a jogada mais forte que a criatura tem.

Por um tempo isso valia **só** para `execute_npc_turn`. `_recarga_pronta`
existia e não era chamada por ninguém, e `_gastar_recarga` só aparecia no
braço da IA de NPC — quando o mestre conduzia o chefe por `use_ability`, que é
o caminho normal deste app, nada era gasto nem conferido e o dragão soprava
toda rodada. Hoje `use_ability` recusa o poder gasto e o marca ao usar. A
conferência vem **antes** do desconto de mana: recusar depois deixaria o custo
pago por uma ação que não aconteceu.

A busca aceita os dois nomes do poder — a habilidade fica na ficha em inglês
(`Fire Breath`) e o mestre registra a recarga com o nome que narra (`Sopro de
Fogo`). Procurar só por um deixava a recarga solta, sem erro nenhum.

**Ações lendárias** (`set_legendary_actions`, `legendary_action`): um único
inimigo contra quatro jogadores age 1 vez a cada 5 turnos, e a luta vira
execução. O chefe passa a agir **fora do próprio turno**, no fim do turno dos
outros; o contador volta ao cheio no início do turno dele. Agir no próprio
turno é recusado — lá ele já tem ação, bônus e ataque múltiplo, e permitir
seria dar-lhe um turno duplo.

O motor gasta as ações **sozinho, uma por virada**. Isso não é conveniência:
no modo tela a luta corre sem LLM nenhum, então uma ação lendária que
dependesse de alguém lembrar de chamá-la nunca seria usada ali. Uma por
virada também é como um mestre humano joga — espalha as três pela rodada. Só
NPCs: um personagem lendário do grupo continua sendo jogado pelo jogador.

Os dois efeitos caem no mesmo gancho, `_inicio_de_turno()`, pendurado em
`_reset_turn_economy` — o único ponto por onde os três avanços de turno
passam (`next_turn`, `_auto_advance_turn` e a auto-cura do ponteiro).

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

## Tela de loja ("O Balcão")

A segunda tela do jogo, e a primeira construída depois de perguntar **por que**
o combate ganhou uma. A resposta não foi "combate é importante": foi que
combate é um **laço** — dezenas de decisões pequenas por sessão, em sequência,
cada uma com consequência mecânica — e pagar uma ida-e-volta de LLM por ataque
era o custo real. A tela existe para tirar o modelo de dentro de um laço
apertado.

Comprar é o único outro laço do jogo: olhar preço → conferir bolsa → conferir
peso → comprar → repetir. É também o único lugar onde ouro, peso e estoque
precisam ser vistos ao mesmo tempo — e sem isso o peso de armadura, que o
motor passou a calcular direito, não vira escolha nenhuma. Missões, atitudes e
relógio **não** ganharam tela: são listas, e lista se resolve com um cartão no
chat, como `/ficha` e `/inventario` já fazem.

A tela abre **sozinha** quando o grupo entra num local que tem loja
(`open_shop(..., location=...)`), e só na primeira vez que aquela loja
aparece: loja é estado que persiste, e reabrir a tela em toda cena por causa
de uma ferraria visitada no capítulo 2 seria intromissão. Fechada, fica uma
pílula no canto para voltar. "Encerrar as compras" manda
`[COMPRAS RESOLVIDAS NA TELA]` para a IA narrar a saída — o mesmo desenho do
recap de combate: a tela resolve os números, a narração continua sendo dela.

### Um cliente novo do motor, sem regra nova

`shop_action` é **só despacho**: ela chama `buy_item`/`sell_item`, as mesmas
funções que o mestre usa. O combate precisou de um dispatcher próprio
(`combat_action`) porque a economia de turno não tem equivalente nas
ferramentas do agente; comprar não tem nada disso.

Isso é deliberado, e a razão está no histórico deste motor: todo caminho
paralelo até uma regra é uma chance de os dois discordarem, e já aconteceu
duas vezes — o braço da IA de NPC cobrava a recarga do chefe e o do mestre
não; a loja marcava item inventado e o verificador não enxergava.
`test_a_tela_passa_pela_MESMA_funcao_do_mestre` existe para ficar vermelho no
dia em que alguém reimplementar a compra "para a tela ficar mais rápida".

### O primeiro teste de navegador do projeto

As capturas provam que a tela **desenha**; `test_tela_de_loja.py` prova que o
motor por trás dela funciona. Nenhum dos dois prova que **clicar** funciona —
e a tela existe inteira por causa do clique. Um `onclick` com nome errado
passaria pelos dois: o print sairia idêntico e a suíte continuaria verde.

`test_tela_de_loja_navegador.py` abre o Chromium, clica nos botões reais e
confere bolsa e carga. Verificado por injeção de regressão: trocar
`_comprar` por `_comprarr` derruba 3 testes que só ele pega. Depende do
Playwright, que não está em `requirements-dev.txt` — sem ele o teste é pulado
em vez de quebrar a suíte de quem instalou só o básico.

Um detalhe que só o navegador pega: `opacity: 0.55` no item caro é
**cosmética**. O que impede a compra é o atributo `disabled`, e o teste força
um clique no botão apagado para confirmar que a bolsa não se mexe.

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
│ Sua vez: Elara , Ação ● Bônus ● Movimento ● Reação ●      │
│ [⚔️ Atacar] [✨ Habilidade] [🧪 Item] [🏃 Mover]           │
│ [🛡️ Defender] [💨 Fugir] [💬 Ação Livre] [⏭️ Encerrar]    │
└────────────────────────────────────────────────────────────┘
```

Com zonas em jogo, uma faixa aparece acima do campo com a trilha e quem está
em cada ponto — o destaque marca a zona de quem joga agora:

```
┌ Portão ─────────┐ → ┌ Pátio ──────────┐ → ┌ Sacada ─────────┐
│ Helena  Natasha │   │ Stelar ◀ é a vez│   │ Victoria        │
└─────────────────┘   └─────────────────┘   └─────────────────┘
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

### Conjunto resolvido por turno (`rpg/toolsets.py`)

As 84 ferramentas custam **~10.500 tokens de schema em toda requisição**. Como
cada chamada de ferramenta é um novo round-trip, um turno de combate com três
chamadas manda ~31 mil tokens só de definição. As ondas 3 e 4 acrescentaram 23
ferramentas, e é justamente por isso que o filtro importa mais agora, não
menos.

| Cenário | Ferramentas | |
|---|---|---|
| D&D, combate narrado | 84 | base |
| D&D, combate na tela | 76 | −8 |
| Romance / horror / mistério… | 33 | **−51 (−61%)** |

O corte para campanhas sem regras encolheu em proporção porque missões,
atitude e relógio de mundo **não são regras de D&D** e ficam em toda campanha
— um mistério precisa que o prazo corra e que o suspeito guarde rancor tanto
quanto uma masmorra precisa do descanso longo.

São dois filtros, com motivações diferentes.

**1. Modo de combate `tela` — o motivo é correção, não custo.** A luta é
resolvida pela interface via `combat_action()`, e a instrução já proibia a LLM
de chamar `attack_roll`, `use_ability`, `next_turn`, `execute_npc_turn`,
`roll_death_save` e `resolve_saving_throw`. Proibir por prompt é esperança;
**retirar a ferramenta do conjunto é garantia** — o mesmo princípio já
aplicado ao snapshot de cena. Uma LLM que resolvesse chamar `attack_roll` no
meio de um combate da tela produziria turno duplicado: o motor avançaria por
fora da economia que a tela controla.

Ficam de fora do filtro de propósito: `roll_initiative` (é o gatilho que faz a
tela assumir), `end_combat` (escape barato se a tela não concluir),
`spawn_monster`/`set_npc_strategy` (usadas antes da luta) e
`modify_hp`/`apply_condition` (dano e condições fora de combate seguem na
narração).

**2. Campanha não-D&D — o motivo é custo, e é o maior dos dois.** Fantasia,
romance, horror, mistério, scifi e faroeste não têm regras: a contagem de
menções a `attack_roll`, `create_character_sheet`, `roll_initiative` e afins
nas instruções desses seis estilos é **zero**, e quase toda ferramenta do
motor exige `char["sheet"]`, que nem existe ali. São 51 ferramentas de peso
morto.

Exceções deliberadas, três: **`roll_dice`**, o único primitivo de
aleatoriedade do sistema, que não depende de ficha e é genérico de gênero; e
**`advance_time` / `get_world_time`**, porque relógio de mundo não é regra de
D&D — um horror precisa que anoiteça e um mistério precisa que o prazo corra,
e nenhum dos dois toca em ficha.

O `test_toolsets.py` escreve esse carve-out **à mão**, em vez de importar a
constante: importar tornaria o teste tautológico, e a graça dele é obrigar
quem mexer no carve-out a passar por ali e justificar a exceção. Foi o que
aconteceu quando o relógio saiu do filtro — o teste ficou vermelho na hora.

Salvaguarda que importa: além da flag `dnd_mode`, o filtro checa se **algum
personagem tem ficha**. Uma campanha importada de JSON sem a flag, mas com
fichas salvas, mantém o motor — perder as ferramentas no meio de uma campanha
em andamento seria bem pior que carregar schema a mais.

**Por que por MODO/TIPO e não por turno.** Os schemas ficam no início da
requisição — o bloco mais cacheável que existe. O tipo de campanha nunca muda,
e o modo de combate muda poucas vezes por sessão, então o prefixo continua
válido dentro de uma mesma fase. Filtrar com
sinais de granularidade fina destruiria o cache e sairia mais caro do que não
filtrar. Pelo mesmo motivo os `FunctionTool` são construídos uma vez e
reusados: schema idêntico entre turnos é o que mantém o prefixo cacheável.

O mecanismo é o `BaseToolset` do ADK, cujo `get_tools()` é chamado a cada
invocação — o conjunto é reavaliado por turno **sem recriar o Agent nem o
Runner**, e portanto sem perder o histórico da conversa. Falha de forma
segura: sem contexto de campanha, entrega tudo, porque uma ferramenta
faltando faz a LLM narrar a mecânica sozinha.

### Contador de cache de prompt

`/api/chat` passou a expor `cached_tokens`, `cache_hit_ratio` e
`thoughts_tokens` junto do `quota_update`, e o log de debug mostra a fração
do prompt servida do cache:

```
🧮 [TOKENS] prompt=14320 resposta=812 total=15132 | cache=11020 (77% do prompt)
```

É o número que diz se aqueles ~11 mil tokens de schema estão custando integral
ou uma fração — e portanto se vale a pena mexer em mais alguma coisa. Com
`cache=0` o aviso é explícito.

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
| `add_quest` / `update_quest_objective` / `complete_quest` | Missões como objetos |
| `list_quests` / `get_quest` | Lê missões |
| `adjust_attitude` / `get_attitude` / `list_attitudes` | Memória social dos NPCs |

As seis últimas valem em **qualquer estilo de campanha**, não só D&D: missão e
atitude são matéria de romance e de mistério tanto quanto de masmorra.

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

`static/css/style.css`, visual de livro/tomo (Lora, Playfair Display,
Caveat) + tela de combate "Pergaminho Épico", 7 temas alternáveis, totalmente
responsivo (`--app-height` cobre o quirk do iOS Safari).

**Escala de espaçamento.** Havia 34 valores distintos de padding/margin/gap em
428 declarações e nenhuma variável de espaçamento: 10, 11 e 12px faziam o
mesmo trabalho, assim como 14, 15 e 16, e 24, 25 e 26. Cada elemento tinha
sido espaçado no olho, isolado dos outros. Sem ritmo comum tudo fica "quase
certo", e o olho lê a tela como apertada.

Hoje é uma grade de 4px em `:root`, e **o número do nome é o multiplicador**:
`--esp-3` = 12px. Use sempre um degrau; se nenhum servir, o problema
provavelmente é outro (alinhamento, hierarquia, tamanho de fonte) e não meio
pixel de padding.

Ficam fora da escala, de propósito:

- **1px e 2px** — fio de cabelo, abaixo da grade;
- **espaço reservado para elemento fixo ou absoluto** (a folga da barra de
  rodapé, o padding que abre lugar para o botão do olho). Ali o número casa
  com o tamanho de *outra coisa*, não com o ritmo da página;
- **margens negativas de sangria**, que são pares — mexer num lado só descola
  os dois.

Ainda há ~114 espaçamentos escritos direto no `style=` do HTML, fora do
alcance da grade. Puxá-los para classes é o passo que fecha o sistema.

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

A suíte roda com **pytest** (382 testes). O `tests/conftest.py` isola tudo de rede
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

O `conftest.campanha` zera também `quests`, `lojas` e `relogio`. Sem isso uma
missão criada num teste vazava para o seguinte, e a falha saía no teste
errado, longe da causa — foi assim que apareceu escrevendo a onda 4.

**Verificação de JS.** `tests/js/authfetch_refresh.mjs` carrega o bloco de
auth real do `static/js/utils.js` num contexto isolado e o submete a um
Supabase simulado que gira o refresh token como o de verdade. A ponte
`tests/test_js_auth.py` transforma cada check num caso do pytest; sem `node`
no PATH os casos são **pulados**, não falham. O script é escrito para Node
antigo (o do apt no Ubuntu 22.04 é o 12): sem top-level await, sem
`import.meta.dirname`, e com uma `Response` própria em vez da global do
fetch — o alvo do teste é o utils.js, não o runtime.

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
│   ├── open5e.py          Acesso ao SRD: sessão, retry, cache, offline
│   └── toolsets.py        Conjunto de ferramentas resolvido por turno
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
│   ├── test_toolsets.py         Filtro de ferramentas por modo e por estilo
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
