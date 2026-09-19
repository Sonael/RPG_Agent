# RPG Agent

> Um RPG narrado por uma IA que age como Mestre, com memória persistente, regras
> de D&D 5e mecanicamente fiéis e uma tela de combate tática opcional.

**Jogue agora: [rpg-agent.onrender.com](https://rpg-agent.onrender.com)**

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
3. [Gênero e regras](#gênero-e-regras)
4. [Sistema de memória (estado por sessão)](#sistema-de-memória-estado-por-sessão)
5. [Persistência (Supabase) e autenticação](#persistência-supabase-e-autenticação)
6. [Modo D&D, mecânicas](#modo-dd-mecânicas)
7. [Sistema de combate](#sistema-de-combate)
8. [A barra lateral do jogo](#a-barra-lateral-do-jogo)
9. [Tela de nível ("A Ascensão")](#tela-de-nível-a-ascensão)
10. [Tela de magias ("O Grimório")](#tela-de-magias-o-grimório)
11. [Tela de equipamento ("A Mochila")](#tela-de-equipamento-a-mochila)
12. [Ficha do local](#ficha-do-local)
13. [Ficha do personagem](#ficha-do-personagem)
14. [Ficha do herói](#ficha-do-herói)
15. [Mapa do mundo](#mapa-do-mundo)
16. [Visão geral do grupo](#visão-geral-do-grupo)
17. [O diário como livro](#o-diário-como-livro)
18. [Índice de personagens](#índice-de-personagens)
19. [Tela de loja ("O Balcão")](#tela-de-loja-o-balcão)
20. [Tela de missões ("O Livro de Missões")](#tela-de-missões-o-livro-de-missões)
21. [Tela de saque ("O Espólio")](#tela-de-saque-o-espólio)
22. [Tela de descanso ("A Fogueira")](#tela-de-descanso-a-fogueira)
23. [Wizard e editores de ficha](#wizard-e-editores-de-ficha)
24. [Tela de combate tática (Pergaminho Épico)](#tela-de-combate-tática-pergaminho-épico)
25. [Tools, o catálogo do agente](#tools-o-catálogo-do-agente)
26. [Endpoints HTTP](#endpoints-http)
27. [Frontend](#frontend)
28. [PWA e instalação](#pwa-e-instalação)
29. [Testes e garantias](#testes-e-garantias)
30. [Estrutura de arquivos](#estrutura-de-arquivos)
31. [Configuração e execução](#configuração-e-execução)
32. [Limitações conhecidas](#limitações-conhecidas)

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

## Gênero e regras

Uma campanha tem dois campos independentes:

- **Gênero** (`campaign_type`) — o tom do mundo: `fantasia`, `dark_fantasy`,
  `romance`, `horror`, `misterio`, `scifi`, `faroeste`.
- **Regras** (`dnd_mode`) — com D&D 5e ligado, a campanha tem fichas, combate
  tático, loja, grimório e as demais telas de regra; sem, a narrativa é livre,
  com memória estruturada.

As regras de D&D valem em fantasia, dark fantasy, horror e mistério
(`memory.GENEROS_COM_REGRAS`). O D&D 5e não é um sistema genérico: o catálogo
é de fantasia medieval (espada longa, bola de fogo, peça de ouro, guerreiro e
mago), e serve ao horror gótico e ao mistério num mundo de fantasia. Romance,
sci-fi e faroeste são sempre narrativos: numa nave ou num saloon a loja de
espadas e o grimório não fecham, e num romance o combate tático atrapalha.
`regras_e_genero` desliga as regras nesses gêneros em toda campanha criada,
editada ou carregada; no menu, o seletor de regras trava em "Narrativa livre"
com uma dica do porquê, e a caixa da importação também. O romance dentro de
uma aventura continua possível: fantasia ou dark fantasy com D&D, e as cenas
românticas narradas no registro do gênero (abaixo).

Antes, `dnd` era um valor de `campaign_type`, no mesmo seletor dos gêneros.
Quem escolhia D&D ganhava uma instrução quase toda mecânica, sem direção de
atmosfera nenhuma; quem escolhia um gênero perdia o motor. `memory.regras_e_genero`
converte o formato antigo (`campaign_type: "dnd"` vira `fantasia` com as
regras ligadas) e roda em toda campanha carregada, em toda campanha criada ou
editada pelo menu e na geração de lore.

### A instrução do mestre é composta

`agent.instrucao_da_campanha(genero, dnd_mode)` junta quatro blocos:

1. **O gênero** — o tom, de `_STYLE_INSTRUCTIONS`.
2. **O tom vale para toda cena** — combate, romance, investigação, viagem,
   descanso. Uma cena íntima numa campanha sombria é íntima *e* sombria: o
   afeto acontece apesar do mundo, e o mundo continua lá. Sem isto, cada
   gênero só sabia narrar o próprio tipo de cena.
3. **Como narrar cada tipo de cena neste gênero** — `_CENAS_POR_GENERO`:
   combate, romance e intimidade, investigação, viagem e exploração, conversa
   e negociação, descanso e pausa, perda e luto, cada um com uma orientação
   própria do gênero. O mestre identifica o tipo da cena (às vezes mais de
   um: um romance durante uma viagem) e combina as orientações. O romance no
   horror não é o romance do gênero romance com um monstro ao lado: "amor
   sob ameaça", o afeto é o que se tem a perder. Só a tabela do gênero da
   campanha entra na instrução.
4. **As regras de D&D**, quando ligadas — e elas avisam que não mudam o tom:
   as regras dizem o que acontece, o gênero diz como isso é contado.

`create_agent` recebe os dois campos. Ele fazia `dnd_mode = (campaign_type ==
"dnd")`, o que desligaria o motor de uma campanha de horror com fichas assim
que ela fosse aberta.

| Gênero | Rótulo do grupo | Foco da instrução |
|---|---|---|
| `fantasia` | Grupo de Aventureiros | Aventura ampla, mundo rico, magia narrativa |
| `dark_fantasy` | Companhia | Mundo que fere, poder com custo, moral cinzenta, violência com peso |
| `romance` | Pessoas Próximas | Emoções, diálogo, subtexto, relações (afeto e confiança) |
| `horror` | Sobreviventes | Tensão, ritmo lento, vulnerabilidade real, trauma |
| `misterio` | Aliados | Pistas, dedução, suspeitos com álibis |
| `scifi` | Tripulação | Tech consistente, dilemas morais, facções |
| `faroeste` | Comparsas | Reputação, duelo, lei frágil |

Com as regras ligadas, o rótulo de papel vira "Classe" e o nome ganha "· D&D"
(`get_campaign_config(genero, dnd_mode)`).

No menu, o wizard e o editor têm os dois seletores, e a importação tem as
abas de gênero e uma caixa de regras. Os campos de um personagem seguem a
REGRA: com D&D, ficha; sem, os campos do gênero (o dark fantasy usa os do
fantasia, com outro nome — o que muda é o tom, e o tom é do mestre).

### Cada gênero dá nome às telas

A barra lateral dizia "Grupo" e "Missões" num romance. `CAMPAIGN_CONFIGS[g]["telas"]`
tem o nome do grupo, das missões e do mapa em cada gênero, e a barra (atalhos
e barra inferior do celular), os títulos das telas de missões e do mapa e o
filtro do grupo no índice de personagens usam esses nomes (`nomeDaTela` em
`utils.js`). `/api/memory` passou a mandar a configuração com as regras
(`server._config_da_campanha`); antes o rótulo perdia o "· D&D".

| Gênero | Grupo | Missões | Mapa |
|---|---|---|---|
| `fantasia` | Grupo | Missões | Mapa |
| `dark_fantasy` | Companhia | Missões | Mapa |
| `romance` | **Relações** (abre a tela de relações) | Tramas | Lugares |
| `horror` | Sobreviventes | Objetivos | Mapa |
| `misterio` | Aliados | Casos | Mapa |
| `scifi` | Tripulação | Contratos | Mapa |
| `faroeste` | Comparsas | Serviços | Mapa |

### Relações do romance (`rpg/relacoes.py`, `GET /api/relacoes`)

No romance o coração do jogo é a relação, e ela só existia como flag solta
(`confianca_lucas=alta`) e como a atitude das fichas, pensada para a loja e os
testes sociais do D&D. Agora cada pessoa tem:

- **Afeto** (-100 a +100): o quanto gosta do protagonista. É o mesmo campo
  `atitude` das fichas, então o que o mestre já registrou com
  `adjust_attitude` continua valendo (e, no romance, entra no histórico da
  relação também). Faixas: aversão, atrito, neutro, afeição, devoção.
- **Confiança** (-100 a +100), separada do afeto porque o drama mora na
  diferença: dá para amar quem não se confia. Faixas: desconfia de você, com
  um pé atrás, ainda não sabe, confia em você, confia de olhos fechados.
- **Vínculo**: a natureza da relação ("interesse romântico", "namoro", "ex",
  "rival"), que começa pelo papel da pessoa no grupo.
- **O porquê**: as últimas 12 mudanças, com o eixo, o motivo e o capítulo.

- **Estágio**: onde a relação está numa escada — conhecidos, amizade, flerte,
  namoro, compromisso — ou fora dela, no rompimento, que guarda até onde ela
  chegou ("rompimento, chegaram a namoro"). Sem registro, quem é próximo está
  na amizade e o resto em conhecidos. Uma amizade pode ficar na amizade: a
  escada não obriga ninguém a virar romance. Afeto e confiança dizem ao
  MESTRE quando o próximo degrau está maduro (flerte pede afeto +35; namoro,
  +55 e confiança +20; compromisso, +75 e +50); a tela não mostra isso, para
  não virar placar. Passo cedo demais não é recusado, só avisado: amor à
  primeira vista existe.
- **Momentos marcantes**: a memória da relação — o primeiro beijo, a briga na
  chuva, o segredo contado —, uma linha do tempo por pessoa (até 20), com
  título, descrição e capítulo. Toda mudança de estágio vira um momento
  sozinha ("Começaram a namorar", "Reconciliação: viraram amigos").

O mestre usa `ajustar_relacao(nome, afeto, confianca, motivo, vinculo)`,
`mudar_estagio(nome, estagio, motivo)`, `marcar_momento(nome, titulo,
descricao)` e `ver_relacoes()`; as quatro só entram no conjunto de
ferramentas do romance (`toolsets.FERRAMENTAS_SO_DO_ROMANCE`). A instrução do
romance manda usá-las, e deixa as flags para fatos, não para sentimentos.

No romance, o bloco de cena de cada turno ganha as RELAÇÕES
(`relacoes.bloco_de_cena`): estágio, afeto e confiança de cada pessoa, se o
próximo passo está maduro e os dois momentos mais recentes. Sem isso o
mestre só sabia deles chamando `ver_relacoes()`, e não chamava: o primeiro
beijo do capítulo 2 não voltava na conversa do capítulo 5.

No romance o atalho do grupo abre a tela de Relações (`static/js/relacoes.js`):
um cartão por pessoa, as próximas primeiro e do afeto maior para o menor, com
o estágio (cinco segmentos, cheios até onde a relação está), os dois
medidores, o vínculo, o último momento e as últimas mudanças; o nome abre a
ficha do personagem, que no romance mostra "Relação com você" (o estágio, os
dois eixos e a linha do tempo inteira, para todos, inclusive quem é do grupo)
no lugar da atitude. Fora do D&D a ficha
também deixou de prometer os efeitos da atitude na CD e no preço da loja, que
são regras de D&D.

### Segredos do romance (`rpg/segredos.py`)

A tensão do romance mora no que não se diz. Um segredo era uma flag ou uma
nota do mestre, e contar ou ser descoberto não mudava nada entre as pessoas.
Agora há dois tipos:

- **Os seus**: o que o protagonista esconde, de quem esconde e quem já sabe.
  Contar a quem se escondia é honestidade (+10 de confiança); contar a outro
  é cumplicidade (+5); quem descobre sozinho o que você escondia dele perde
  confiança (-25). Contar ou ser descoberto por quem estava no escuro vira
  momento na linha do tempo da pessoa.
- **Os dos outros**: o mestre registra desde o começo, mas o jogador só os vê
  depois de revelados (`segredos.visiveis` não os manda antes). Quem conta
  confia (+10); o que o protagonista descobre sozinho fica marcado como "não
  sabe que você sabe".

O mestre usa `guardar_segredo(dono, titulo, descricao, escondido_de, sabem)`,
`revelar_segredo(titulo, a_quem, como)` e `ver_segredos()`, só no romance. O
bloco de RELAÇÕES do turno ganha os SEGREDOS, todos, com o aviso de não
revelar os que o protagonista ainda não sabe. A tela de Relações ganha a aba
"Segredos" (os seus, com de quem esconde, quem sabe e como cada um ficou
sabendo; e os dos outros que você já sabe), e o cartão e a ficha de cada
pessoa mostram o que você esconde dela, o que ela sabe do seu e o que você
sabe dela.

`test_genero_e_regras.py` (27), `test_genero_e_regras_navegador.py` (9),
`test_segredos.py` (18),
`test_relacoes.py` (28) e `test_relacoes_navegador.py` (13).

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
  "campaign_type":        "fantasia" | "dark_fantasy" | ...,   # gênero
  "dnd_mode":             bool,                             # regras
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
- Entrega o **kit inicial** da classe (`KIT_INICIAL`): armadura, escudo e
  arma vestidos por `equip_item` (a CA sai da mesma `ARMOR_TABLE` do resto do
  jogo), poções, pacote e 10 po e 5 pp, as mesmas moedas do wizard. Antes a
  ficha nascia de mãos vazias (CA 10, sem arma, 0 de ouro) e dependia de o
  mestre lembrar de `add_item`; uma clériga recrutada no meio da campanha
  entrou na luta sem armadura. O kit é o padrão de cada classe no wizard (a
  primeira opção de cada escolha), com duas diferenças: a peça vestida
  também vai para a mochila, porque `equip_item` só veste o que está nela, e
  mago e feiticeiro não levam armadura. Classe fora da tabela ganha adaga,
  pacote e poção; `npc` não ganha nada.
- Quem já carregava itens fica com eles (sem kit), e um NPC que já existia
  sem ficha mantém local, atitude, o que o grupo sabe e se é do grupo. Antes
  o personagem inteiro era trocado por um dict novo e isso sumia.

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
- `_weapon_attr` decide DEX×STR (ranged→DEX, finesse→max, melee→STR). As
  listas `RANGED_WEAPONS` e `FINESSE_WEAPONS` têm os nomes em português **e**
  em inglês: a arma do monstro chega do stat block como "scimitar" ou
  "shortbow", e só com os nomes em português o goblin (FOR 8, DES 14) atacava
  de cimitarra e de arco com a Força, acertando com +1 em vez do +4 do livro.
  "Rapieira" também faltava (a lista tinha "rapier"), e a rapieira do ladino e
  do bardo usava a Força. `test_atributo_da_arma.py` trava os dois idiomas.
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
- Sem armadura, a CA é a maior entre 10 + DES e o que as habilidades põem no
  lugar dela: Defesa Sem Armadura (bárbaro 10 + DES + CON; monge 10 + DES +
  SAB, e nenhuma delas com armadura vestida) e Resistência Dracônica
  (13 + DES). O escudo soma +2 depois, e é justamente ele que desliga a do
  monge. `learn_ability` recalcula quando concede uma dessas duas: antes a CA
  só mudaria quando o personagem vestisse ou tirasse alguma coisa.
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
- **XP por derrota é uma vez por personagem.** Ao reabrir uma campanha, o
  grupo ganhava de novo o XP de um monstro já derrotado e já pago: o mestre
  relia o recap da tela tática ("conceda XP a cada membro do grupo") e
  obedecia. `grant_xp` agora procura no motivo os inimigos fora de combate
  que ele cita (`_derrotados_citados`: nome inteiro ou a primeira palavra do
  nome, então "vitória sobre o espreitador" cita o Espreitador das Sombras).
  Cada inimigo guarda em `xp_concedido_a` quem já recebeu por ele. Se todos
  os citados já pagaram aquele personagem, a resposta é `Aviso:` e nada é
  somado. Motivo sem inimigo citado (missão, marco narrativo) não tem trava.
  A outra metade da correção está na retomada: veja "O recap não é fala do
  jogador".

### Descanso, relógio e exaustão

- `short_rest` (1 hora; gasta dados de vida **da reserva**), `use_hit_die`,
  `long_rest` (full HP/MP + metade da reserva de dados + condições; bloqueado em
  combate), `offer_rest` (abre a [tela de descanso](#tela-de-descanso-a-fogueira)
  para o jogador decidir).
- **Uma reserva de dados de vida, um caminho de gasto.** `short_rest` rolava
  nível/2 dados e curava sem tirar nada da reserva que `use_hit_die`
  controlava — e sem passar hora nenhuma. Era a cura infinita. Medido no commit
  anterior à correção, guerreira de nível 5 com 5 dados, dados rolando o
  máximo:

  ```
  descanso curto 1   vida  5 → 29   reserva 5/5   0 horas
  descanso curto 2   vida 29 → 53   reserva 5/5   0 horas
  descanso curto 3   vida 53 → 60   reserva 5/5   0 horas
  ```

  Hoje as duas ferramentas passam por `_gastar_dados_de_vida`: um dado de cada
  vez, parando quando a vida enche (dado rolado com vida cheia é dado jogado
  fora). Esvaziou a reserva, o descanso curto ainda passa a hora, mas não cura
  — e só o descanso longo, que é um por dia, devolve dados: **até metade da
  reserva** (mínimo 1), como no PHB. Devolver a reserva inteira fazia um dia
  ruim sumir numa noite de sono; com metade, quem torrou os dados numa
  masmorra sente o custo no dia seguinte. Subir de nível
  soma um dado à reserva; morto não descansa; em combate nenhum dos dois roda.
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
- **O inimigo abre a própria mochila.** Com metade da vida ou menos, bebe a
  poção de cura que estiver com ele (`_npc_beber_pocao`) antes da jogada do
  turno. Beber é Ação Bônus, então o ataque continua acontecendo, e a poção
  passa pelo mesmo `combat_action` da tela do jogador: mesmo dado, mesmo teto
  de exaustão, mesma baixa na unidade. Antes o turno do NPC nunca olhava o
  inventário — um bandido morria com a poção no cinto.
- **A atitude no balcão.** `open_shop(..., owner="Torbin")` guarda quem
  atende, e o preço passa pela relação dele com o grupo: a mesma escala do
  teste social, 5% a cada 20 pontos, teto de 25% para os dois lados. Desconto
  na compra, ágio na venda; `buy_item` e `sell_item` cobram e pagam por ela, e
  a tela do balcão mostra o preço pedido com a tabela ao lado e diz de onde
  vem a diferença. Sem dono, a loja cobra a tabela para todo mundo.
  A ficha do personagem ganhou o estoque de quem atende (evita a viagem até a
  tela da loja, que só abre no local dela) e a lista do que a atitude vale em
  número — antes ela dizia "leal" e o jogador não sabia o que ganhava com
  isso. `test_atitude_no_preco.py` (14) e
  `test_atitude_no_preco_navegador.py` (5).
- **As últimas cenas com ele**, bloco próprio na ficha do personagem. Os
  eventos em que ele aparece já entravam na lista de Ligações, oito de uma
  vez, das mais antigas para a frente e só com resumo e local: quem tinha
  acabado de falar com o ferreiro lia primeiro o encontro de três capítulos
  atrás. Agora são as cinco mais recentes, da última para trás, com o
  capítulo e a consequência que `save_event` grava — e a ficha diz quantas
  existem ao todo. É o que o jogador quer lembrar antes de falar com alguém
  de novo.
- **Pechincha** (`haggle`, botão na tela do balcão): um teste de Persuasão
  contra o lojista, UMA vez por visita ao local. Passando, a loja cobra 10%
  menos até o grupo sair dali; falhando, o preço fica como está; tirando 1 no
  dado, o lojista se ofende, cobra 5% a mais e perde 5 de atitude. A CD (13)
  sobe ou desce com a relação, como em qualquer teste social, e a
  proficiência da classe em Persuasão entra na rolagem. Antes barganhar era
  conversa solta: o jogador pedia desconto no chat e o mestre decidia de
  cabeça, sem a perícia do personagem entrar na conta.
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
  derivados automaticamente: HP por CON, mana pelo atributo de conjuração e
  a CA por DES — e também por CON ou SAB, que entram nela pela Defesa Sem
  Armadura. O mesmo vale para `apply_asi`.

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
- Defesa Sem Armadura (bárbaro e monge), CA sem armadura = 10 + DES + CON
  (bárbaro, pode usar escudo) ou 10 + DES + SAB (monge, que perde a
  habilidade se pegar um escudo).

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

`rpg/tools_dnd.py:_ability_action_type` detecta Bônus por nome (PT e EN), com
Ação como padrão. O custo de um item vem da ficha dele (`_efeito_de_item`, ver
[Submenu Item](#submenu-item-itens-com-efeito)).

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

### Duração das condições

`apply_condition(..., duration_turns=N)` gravava `{"duracao": N}` e nada no
motor contava: "Envenenado (2 turnos)" ficava para sempre no card, na ficha
do herói e na barra lateral, até o mestre lembrar de remover.

- A duração é em **turnos do próprio afetado** e desconta no **fim** de cada
  turno dele (`_fim_do_turno`, chamado por `next_turn` e `_auto_advance_turn`
  antes de mover o ponteiro). Chegou a zero, a condição sai, o diário registra
  `condition_end` e o texto do avanço diz "Envenenado de Goblin acabou".
- Aplicada **na vez do próprio afetado**, aquele turno não conta
  (`token_aplicacao`): "Envenenado por 1 turno" dura sempre um turno inteiro
  dele.
- Quem está fora de combate (inconsciente, dormindo) não tem turno e não
  desconta.
- Condições com duração **acabam com o combate**; as indefinidas ficam.
- As telas mostram os turnos restantes: selo "Envenenado 2t" no card do
  combate, "(2 turnos)" na ficha do herói, em `get_combat_status` e na barra
  lateral.
- O texto do avanço de turno pela ferramenta de ação (`_auto_advance_turn`)
  passou a incluir também o que acontece na virada (ações lendárias, chamas
  do Fogo Alquímico), que antes só `next_turn` mostrava.

`test_duracao_das_condicoes.py` (9) cobre a contagem, o turno de aplicação, a
indefinida, a tela tática, quem está fora de combate, o fim do combate e o
texto das telas. `test_combate_alcance_navegador.py` confere o selo com os
turnos no card.

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

#### Dois defeitos que as zonas criaram na tela tática

**O inimigo de corpo-a-corpo travava a luta.** `set_battlefield` põe os
inimigos na última zona, e `execute_npc_turn` atacava de onde estava. O motor
recusava por alcance, o turno não avançava, e a tela tática ficava presa em
"Turno do Inimigo" depois de repetir a chamada 80 vezes. Agora:

- o NPC que só luta corpo a corpo escolhe entre os alvos mais próximos e
  anda até o alvo (`_npc_aproximar`). A uma zona de distância, move e ataca no
  mesmo turno; a duas ou mais, usa a Disparada, que gasta a Ação, e o golpe
  fica para o turno seguinte;
- o NPC que tem golpe à distância atira de onde está;
- no Ataque Múltiplo, o golpe só é redirecionado para um alvo que ele
  alcança;
- `execute_npc_turn` envolve o turno com uma garantia: se, ao final, a vez
  ainda é do mesmo NPC e o turno não andou, ele passa a vez e isso vai para o
  log. Uma recusa que sobrar nunca mais prende a luta.

**O jogador perdia a Ação num ataque recusado.** `combat_action` marcava a
Ação como gasta antes de chamar `attack_roll`, e a recusa de alcance voltava
com `ok: true`. O jogador não via aviso nenhum e só podia encerrar o turno.
Agora o alcance é checado antes de gastar a Ação, e qualquer recusa de
`attack_roll` ou `use_ability` devolve a Ação e responde com `ok: false` e uma
mensagem que a tela mostra ("A Ação não foi gasta").

O snapshot ganhou `alcance`: para o combatente do grupo que está na vez, cada
arma contra cada outro combatente, `ok`, `desvantagem` ou `fora`, calculado
por `_checar_alcance`. O seletor de alvo da tela desabilita quem está `fora` e
marca a desvantagem, sem ter regra própria.
`test_combate_alcance_na_tela.py` cobre o motor e
`test_combate_alcance_navegador.py` abre a tela com o inimigo duas zonas
longe na vez dele.

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

Toggle do modo: engrenagem → "Esta campanha" → "Narrado pela IA" / "Tela
tática".

### A mesma luta não recomeça

Numa campanha o mestre, num único turno, chamou `spawn_monster`,
`roll_initiative`, `set_battlefield`, `roll_initiative`, `spawn_monster`,
`roll_initiative` e `set_battlefield` para os mesmos dois goblins, e a tela
mostrou três ordens de iniciativa diferentes. Cada chamada repetida desfazia
algo:

- **`roll_initiative`** com o combate ativo zerava ordem, rodada e log. Agora
  quem já está na ordem fica como está; se todos os nomes já lutam, a resposta
  é `Nota: o combate já está em andamento` e nada muda. Nomes novos são
  reforços: rolam e entram no lugar do total deles (os totais ficam em
  `combat_state["iniciativas"]`), a vez de quem está agindo não muda, e quem
  entra antes dela age a partir da próxima rodada. Combate antigo, sem os
  totais guardados, põe o reforço no fim.
- **`spawn_monster`** com o combate ativo trocava o goblin ferido por um novo,
  de vida cheia. Agora recusa se algum nome gerado já está na ordem; reforço
  de verdade usa outro `display_name`. Fora de combate nada mudou.
- **`set_battlefield`** com as mesmas zonas repunha todo mundo na posição
  inicial, desfazendo os movimentos. Agora mantém as posições e só posiciona
  quem ainda não tem zona. Zonas diferentes redefinem o campo, como antes.

O servidor também deixou de reenviar a fala do jogador quando o modelo cai no
meio do turno (503, sobrecarga) **depois** de já ter chamado ferramentas que
mexem no jogo. A nova tentativa recebe `[TURNO INTERROMPIDO]` com a lista do
que já foi feito e a instrução de não refazer; ferramentas de consulta
(`get_`, `list_`, `describe_`, `check_`, `suggest_`) não entram na lista.
`test_combate_repetido.py` refaz a sequência da campanha e testa a retomada
pela rota `/api/chat`, com um runner que chama `roll_initiative` e cai com 503.

### Log estruturado

Cada evento mecânico do combate vira uma entrada em `combat_state["log"]`
(cap 300). Inclui os **dados rolados**:

```
[R1] Combate iniciado
[R1] Valerius → Goblin 4 (Espada Longa): d20=20 +3+2 = 25 vs CA 5
     • CRÍTICO ACERTO • dano [6 + 6] +3(mod) = 15 → HP 7→0/7
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

## A barra lateral do jogo

A barra era um livro de listas em três abas (Mundo, Enciclopédia e Diário),
numa coluna de 320 px com rolagem própria. O cabeçalho (título em duas linhas,
local, "Uso do modelo" e as abas) ocupava quase metade da altura, e "Menu
Principal" e "Sair do Sistema" ficavam fixos embaixo. Ela também tinha
envelhecido: grupo, missões, mapa, diário e fichas viraram telas, e a barra
repetia, em miniatura, o que elas mostram melhor. Validação, Observações e
Uso do modelo não são do jogador.

### O que ela mostra (`static/js/barra.js`)

**O relance**, sempre à vista e sem rolagem:

- local atual, capítulo e hora do mundo numa linha só, cada um clicável (ficha
  do local, página do capítulo no diário, visão geral do grupo);
- uma linha por herói: nome (abre a ficha), barra e números de vida e as marcas
  que pedem atenção: condição (com as outras na dica), caído ou morto,
  sobrecarregado ou imóvel e **nível**, o mesmo selo de antes, que abre o aviso
  de subir de nível (ou a tela de nível, se é escolha pendente). Os números vêm
  do motor, por `/api/party/overview`; em campanha sem regras aparecem só o
  nome e o papel;
- a missão principal com o progresso ("2/3"), que abre a tela de missões nela.
  A principal é a ativa do capítulo mais recente; no empate, a mais adiantada.
  Não dá para usar a ordem da lista: o banco guarda as missões num objeto, e a
  ordem das chaves não é a de criação;
- os avisos do verificador, só quando há algum: um botão discreto com a
  contagem (em vermelho se há erro) que abre a lista, com dispensar e
  "Limpar todos". Antes era uma seção fixa da aba Mundo, e um erro trocava a
  aba.

**Os atalhos**, logo abaixo: Grupo, Missões, Mapa, Diário, Personagens e
Mochila (só em campanha D&D; em campanha sem regras, Grupo leva ao índice de
personagens filtrado no grupo). Contador quando diz algo: heróis que pedem
atenção (nível pendente ou caído), missões ativas e personagens fora do grupo.

### Para onde foi o resto

| Antes, na barra | Agora |
|---|---|
| Uso do modelo, Status do sistema | engrenagem, seção "Esta campanha" |
| Modo de combate | engrenagem, seção "Esta campanha" |
| Menu Principal, Sair do Sistema | engrenagem, seção "Esta campanha" |
| Resumo (e "editar" do estado) | página "Até aqui" do diário |
| Observações | editor da campanha, no menu |
| Validação | aviso discreto no relance |
| Grupo (cartões) e "+ Membro" | relance, visão geral do grupo e índice de personagens |
| Personagens e "+ Personagem" | índice de personagens |
| Locais e "+ Local" | mapa ("Novo local" no rodapé) |
| Entradas do diário, "+ Entrada", exportar | diário |
| Missões ativas | missão principal no relance e tela de missões |

### Desktop e celular

- **Recolher** (as setas no alto): a barra vira uma coluna de 76 px só com os
  ícones dos atalhos, com o contador sobre o ícone. A escolha fica em
  `localStorage` (`rpg_barra_recolhida`) e volta ao recarregar.
- **Celular**: o botão de menu saiu. Sob o título fica uma faixa com o local, a
  hora e a vida do grupo (inicial e barra de cada herói); tocar nela abre o
  painel. Embaixo, uma barra fixa com Grupo, Missões, Mapa, Diário e **Mais**,
  que abre a gaveta com o relance inteiro e os seis atalhos. Um atalho tocado
  na gaveta fecha a gaveta antes de abrir a tela.

O guia "Como Jogar" descreve a barra nova, e as capturas do jogo ganharam
`jogo-barra-recolhida`, `jogo-avisos` e `jogo-painel-mobile` no lugar das
abas antigas. A semente das capturas apaga `rpg_barra_recolhida` junto com a
memória das telas: o `localStorage` sobrevive entre as capturas do mesmo
navegador, e sem apagar a captura da barra recolhida deixava recolhidas todas
as capturas de desktop seguintes.

### Barras do navegador e do sistema

No celular, `100vh` é a altura com as barras do navegador escondidas. Quando
a barra de endereço aparece (ou a de sistema encolhe a área), tudo que mede
`100vh` passa do fim da área visível. Por isso a altura do jogo vem de
`--app-height`, que `utils.js` mantém igual a `visualViewport.height`:

- `body.game-page` usa `--app-height` com `min-height: 0` (o
  `body { min-height: 100vh }` geral vencia e empurrava o campo de texto e a
  barra de baixo para trás das barras);
- as telas cheias do celular (combate, loja, nível, descanso, Mochila,
  grimório, saque, local, personagem, herói, missões, mapa, grupo, diário,
  índice) e o painel da engrenagem usam `var(--app-height, 100vh)`;
- a gaveta do "Mais" é presa pelo topo e mede 85% de `--app-height`;
- a barra de baixo soma `env(safe-area-inset-bottom)` ao padding, para os
  botões ficarem acima da barra de gestos quando o navegador desenha por baixo
  dela.

Com o teclado aberto a barra de baixo sai (classe `teclado-aberto` no
`<html>`): campo de texto com foco e a área visível mais de 150 px menor que
a altura cheia nessa largura. A barra de endereço sozinha não passa do limite,
e o foco que o jogo dá ao campo ao abrir, sem teclado, também não.

### Testes

`test_barra_navegador.py` (20) confere a linha de onde, capítulo e hora (lado
a lado, sem sobrepor e sem cortar), cada um abrindo a sua tela; uma linha por
herói com a vida do motor e as marcas; o nome abrindo a ficha e o selo abrindo
o aviso de nível; carga pesada como marca; a missão principal e o bloco sumindo
sem missão ativa; os seis atalhos abrindo as telas; os contadores; os avisos só
quando há algum; a engrenagem com o modo de combate funcionando; que nada da
barra antiga ficou na página e que a barra não precisa de rolagem nem corta
rótulo; recolher e lembrar depois de recarregar; a campanha sem regras; e, no
celular, a faixa, a barra de baixo, o "Mais" com a gaveta e o toque na faixa.
As barras do celular são simuladas, porque o Playwright não as desenha: a margem
segura de 34 px emulada pelo Chromium (os botões da barra de baixo ficam acima
dela) e a área visível 90 px menor que a janela (barra de baixo, campo de
texto, rodapés de Grupo, Missões, Mapa e Diário, a gaveta, o Sair da
engrenagem e a altura de todas as telas cheias dentro dela), além do teclado
escondendo a barra de baixo só quando a área encolhe muito. Um teste a mais
segura a pílula de tela reaberta acima do campo de texto, com e sem a barra de
baixo. Os testes das telas que entravam pelas abas (nível, grimório, Mochila, ficha
do local, do personagem e do herói, missões, mapa, grupo, diário) passaram a
entrar pelos caminhos novos. Regressões injetadas (missão principal pela ordem
da lista, contador sem nível pendente, avisos que não chegam, engrenagem
vazia, recolhida esquecida, tudo tratado como D&D, gaveta aberta atrás da
tela, sem barra de baixo, linha de onde sobreposta, herói abrindo a ficha de
NPC) foram todas pegas, e também as da área visível: sem o `min-height: 0`,
gaveta em `85vh`, diário, loja ou engrenagem em `100vh`, teclado que não
esconde a barra, teclado detectado só pelo foco, barra sem a margem segura e pílula sem
acompanhar a barra de baixo.

## Tela de nível ("A Ascensão")

A terceira tela, e a primeira construída por um motivo que **não** é o das
outras duas. Combate e loja são laços: muitas decisões pequenas em sequência,
e a tela tira a LLM de dentro do laço. Subir de nível acontece umas dez vezes
numa campanha inteira — não há laço nenhum, e não há round-trip a economizar.

O que há é um punhado de escolhas que valem o resto da campanha e que o modelo
inventaria de bom grado: estilo de combate, arquétipo, para onde vão os pontos
de atributo. **Aqui a tela não economiza tempo, ela impede invenção.**

### O custo estava no motor, não no front

O motor sempre soube **subir** de nível (`grant_xp` dá PV, proficiência, mana e
as features automáticas) e sempre soube **aplicar** uma escolha
(`set_feature_choice`, `choose_feat`, `set_stat`). Faltava o meio: saber que o
personagem **deve** uma escolha.

Sem isso, "escolha um Estilo de Combate" era uma frase no fim do texto de
level-up. Se ninguém escolhesse, nada acontecia e nada cobrava — e um
guerreiro atravessava a campanha inteira sem o estilo a que tinha direito
desde o nível 1.

`_escolhas_pendentes(char)` é **calculada, não gravada**, a mesma disciplina do
teto de PV da exaustão: o personagem tem a habilidade na ficha e não tem
entrada em `feature_choices`, logo deve a escolha. Vale para fichas salvas
antes desta mudança, sem migração nenhuma, e é a mesma pergunta que
`set_feature_choice` já respondia para validar — só que feita de fora.

### O Incremento de Atributo precisou de contador

É a exceção, porque não deixa rastro: um +2 em Força é indistinguível de uma
força alta na criação. `asi_pontos_gastos` conta os pontos, e a chave AUSENTE
significa ficha anterior ao contador — nesse caso a resposta é **zero
pendente**. Cobrar retroativamente os cinco incrementos de um personagem de
nível 19 daria +10 de atributo de presente, e não há como saber se o mestre já
os aplicou à mão.

`grant_xp` carimba o contador no próximo level-up, ancorando-o no presente:
o passado não é cobrado, o futuro é. `test_o_proximo_nivel_passa_a_ser_cobrado`
é o que garante que a âncora não virou "desligar a conta para sempre".

`apply_asi` é função nova em vez de reuso do `set_stat` porque ASI tem regra:
sai de um pool que o nível concede e para no 20. `set_stat` é ajuste livre do
mestre, sem teto e sem pool — usá-lo para ASI deixava o atributo subir sem
limite e sem gastar nada. Guerreiro ganha incrementos extras no 6 e no 14,
Ladino no 10; está em `_NIVEIS_ASI_EXTRA`.

**Talento sai do mesmo pool.** Um talento é trocado por um incremento inteiro,
então `choose_feat` desconta os 2 pontos. A primeira versão desta tela não
descontava: quem escolhia talento ficava com o talento **e** com os 2 pontos
pendentes. A checagem antiga, por nível exato (4, 8, 12, 16, 19), também
barrava quem subiu ao 5 ainda devendo o incremento do 4; em ficha com contador
agora vale o pool, e em ficha sem contador continua valendo o nível — com os
extras do Guerreiro e do Ladino. O bônus de atributo que alguns talentos dão
parava em 30; agora para no mesmo teto de 20 do `apply_asi`.

### A tela

Abre sozinha quando a **assinatura** das pendências muda — ou seja, quando um
nível novo criou escolha. Abrir sempre que houvesse pendência prenderia numa
tela que reabre a cada turno quem decidiu deixar para depois.

A assinatura é calculada **no servidor, sobre o grupo inteiro**
(`_assinatura_pendencias`), e lembrada no `localStorage` por campanha — fechar
no ✕ e dar F5 não reabre. Quando ninguém deve nada, a memória é apagada: sem
isso uma pendência que voltasse igual à anterior (o incremento de 2 pontos do
nível 8, com a mesma assinatura do nível 4) nunca mais abria a tela.

### A fila das telas

Combate, nível e loja decidem sozinhos se aparecem, e antes não sabiam uns dos
outros: os três `sync()` rodavam em paralelo, e quem carregava a página parado
numa forja com escolha de nível pendente via as duas telas abrirem juntas, uma
empilhada na outra.

`sincronizarTelas()` em `game.js` roda os três **em série e nesta ordem**:
combate, nível, loja. Nível vem antes da loja porque a escolha muda a compra —
um ponto em Força muda a carga que cabe na mochila. Cada tela também se recusa
a abrir sozinha por cima de outra já aberta e, nesse caso, **não** marca que
abriu; quando uma tela fecha, ela dispara `rpg:tela-fechou` e a fila roda de
novo, dando a vez para quem esperava. A série também resolve outra corrida:
`refreshMemory()` costuma ser chamado duas vezes seguidas (resultado de
ferramenta e fim do turno).

### O selo "Subir de nível"

O selo na linha do herói, no relance da barra lateral, aparece quando o XP já passa
do limite e o nível não subiu — XP ajustado à mão, por exemplo. Ele gravava o
nível direto pela rota de edição, com PV calculados no navegador pela média do
dado, e pulava tudo o que o `grant_xp` faz: habilidades da classe, mana,
contador de incremento. Depois abria o modal de edição.

Agora o popup só confirma, e não promete número que não controla ("1d10 + CON,
rolado na confirmação"). A confirmação chama `levelup_action('subir')`, que é
`grant_xp` com 0 de XP — o laço de subida roda com o XP que a ficha já tem — e
a tela de nível abre no personagem. Magia nova continua em "Editar Ficha
Completa": a tela de nível não trata escolha de magias.

O popup usava `background: var(--page-bg)`, variável que não existe no CSS: o
cartão sempre saiu transparente, com o texto da página atravessando o conteúdo.
Agora usa `--page-right`, como os outros diálogos, e há teste medindo a cor.

O botão do rodapé muda de **função**, não só de rótulo: desabilitado enquanto
este personagem deve algo (sair devendo é o que a tela existe para impedir; o
✕ continua fechando), atalho para o próximo do grupo quando outro deve, e
"Concluir" só quando ninguém deve. Um botão escrito "Agora Helena →" que
concluísse a cena seria mentira.

O incremento de atributo usa o **mesmo stepper `− valor +` do wizard de
criação**, e pelo mesmo modelo: um rascunho local. `+` e `−` não vão ao
servidor; só "Confirmar incremento" grava. A diferença para o wizard é o piso:
lá o `−` desce até o mínimo da criação, aqui ele só retira os pontos postos
**agora** — o valor que a ficha já tinha não é negociável, incremento não é
redistribuição. O `+` trava quando o pool acaba ou o atributo chega a 20.
Confirmar exige todos os pontos distribuídos, porque um ponto esquecido
viraria pendência que o jogador não entenderia; a exceção é não haver mais
onde pôr. Talento fica bloqueado enquanto há ponto no rascunho.

Rascunho local foi a escolha em vez de "gravar a cada clique e desfazer no
`−`" porque desfazer um ponto de CON exigiria desfazer os PV que ele deu, um
de DES a CA, e o atributo de conjuração a mana. Com o rascunho, o servidor
nunca precisa desfazer nada.

A confirmação chama `apply_asi_distribution`, que é **atômica**: valida o lote
inteiro antes de aplicar o primeiro ponto. Aplicar ponto a ponto e parar no
erro deixaria meio incremento gravado — +1 em Força aceito, +1 em Carisma
recusado — e uma ficha que não é nem a de antes nem a escolhida. Depois de
validar, cada ponto passa por `apply_asi`, então pool, teto e derivados
continuam num lugar só.

O rascunho é descartado sempre que não há incremento pendente. Sem isso,
depois de confirmar o bloco sumia com o rascunho ainda guardado, e no PRÓXIMO
incremento do mesmo personagem — também de 2 pontos — os pontos antigos
voltavam já postos. `test_o_rascunho_nao_reaparece_no_proximo_incremento`
guarda esse caso.

No mobile a régua de atributos usa a sigla de três letras da mesa (FOR, DES,
CON…). Com o nome inteiro ela quebrava em 4+2 e comia 280px dos 812 da tela —
um terço do espaço, justamente na tela em que o conteúdo que importa são as
escolhas.

`levelup_action` é só despacho, igual à loja: chama `set_feature_choice`,
`apply_asi` e `choose_feat`, as mesmas do mestre.
`test_a_tela_passa_pelas_MESMAS_funcoes_do_mestre` guarda isso.

### Um efeito colateral nos testes de navegador

Com o segundo arquivo de teste de navegador, os dois passavam sozinhos e
**erravam juntos**: `_subir_servidor` registrava `/__estado` via
`@app.route`, e o Flask recusa registrar rota depois que o app atendeu a
primeira requisição.

A primeira tentativa de conserto foi contar referências do servidor — e não
resolveu, porque o primeiro módulo solta o servidor antes de o segundo pedir.
O que precisava de guarda era **a rota**, não o servidor: são coisas
separadas, e reusar o servidor ficou como otimização.

## Tela de magias ("O Grimório")

A quinta tela, e a irmã da de nível: existe porque **escolher magia é escolha do
jogador**, e no chat quem acabava escolhendo era o modelo — "Lyra aprende Bola
de Fogo" saía na narração do level up sem ninguém ter perguntado. O Grimório
mostra a lista da classe, as vagas que sobram e o que cada magia faz, e o
botão **Aprender** chama `learn_spell`, a mesma função do mestre.

**Quando abre.** Sozinho, quando surge **vaga nova** — na prática, um
conjurador que subiu de nível (na fila de telas ele vem logo depois da de
nível, porque é o nível novo que abre a vaga). A assinatura do motor é a
lista "Nome:nível" de quem tem vaga, e o navegador guarda o conjunto de
entradas já vistas:

- entrada que **aparece** ("Helena:4") abre a tela;
- entrada que **some** ou vaga que só diminui (o mestre ensinou uma magia pelo
  chat) não abre nada — com a quantidade de vagas na assinatura, cada magia
  aprendida reabria a tela;
- a **primeira visita** de um navegador a uma campanha não abre: marca o que
  existe como visto e deixa só a pílula. Quase todo conjurador de campanha
  antiga tem vaga sobrando, e o Grimório pularia no primeiro carregamento de
  todo mundo por uma vaga que ninguém acabou de ganhar.

Fechado, fica a pílula "Helena: magias a aprender"; e todo conjurador ganha um
atalho **Grimório** no cartão do grupo, numa linha própria embaixo das barras
(no cabeçalho ele espremia a CA em duas linhas). Com a tela fechada, a fila
pede só o resumo (`?resumo=1`): vagas e assinatura, sem ir ao SRD buscar a
lista a cada turno.

**O que mostra.** No cabeçalho, as vagas ("Truques 2/3 · 1 a aprender",
"Magias 3/5 · 2 a aprender") e até que círculo a classe chega — fora do corpo
que rola, porque é o número conferido a cada magia olhada. À esquerda a lista
da classe, com busca pelo nome e filtro por círculo; à direita as conhecidas,
agrupadas por círculo. Cada cartão diz círculo, escola, concentração, ritual,
custo em mana, dado e alcance, e o botão trava dizendo o motivo: *Já conhece*,
*Sem vaga de truque*, *Sem vaga de magia*. Concluir depois de aprender manda
`[GRIMÓRIO RESOLVIDO NA TELA]` com a lista para a IA narrar; sem nada
aprendido, só fecha.

### A regra que vivia no navegador

A tabela de truques e magias conhecidas por nível existia **só no JavaScript
do modal de edição**. O `learn_spell` não a conhecia: o mestre dava a décima
magia a um clérigo de nível 3 e nada reclamava. Agora `_limite_de_magias` mora
no motor, o `learn_spell` recusa acima dela, e o Grimório marca o botão pelo
mesmo número. Junto vieram outras correções no `learn_spell`, todas do mesmo
feitio (a regra existia num caminho e não no outro):

- **Nível de magia por tipo de conjurador.** A exigência era nível 2L−1 para
  toda classe — a tabela do conjurador pleno. Paladino e patrulheiro são
  meio-conjuradores (1º círculo no nível 2, 2º no 5, 3º no 9): com a regra
  antiga um paladino de nível 3 aprendia magia de 2º círculo.
- **Sem conexão, qualquer nome entrava.** Com o SRD fora do ar a magia ia
  para a ficha sem checagem de classe nem de nível, com custo 4 fixo — o único
  caminho do motor em que uma magia inventada passava. Agora só entra o que o
  motor conhece localmente (as magias padrão das classes e a tabela de
  níveis), com as mesmas checagens.
- **A busca aproximada escolhia qualquer uma.** Sem nenhuma palavra em comum
  com o nome pedido, "a mais próxima" era a primeira da lista — a busca
  textual casa também na descrição, e um nome inventado voltava com os dados
  de outra magia.
- **Sim e não do Open5e são texto.** Os campos `ritual` e `concentration` vêm
  como `"yes"`/`"no"`, e `bool("no")` é verdadeiro: toda magia saía marcada
  como ritual e concentração — no modal, no texto do `learn_spell` e na ficha.
- **A lista da classe misturava livros de terceiros.** O Open5e junta o SRD
  com outros livros; a lista do clérigo vinha com "Black Goat's Blessing" ao
  lado de "Bless". O catálogo pede `document__slug=wotc-srd`.
- **A ficha grava `nivel_magia` e `nome_srd`.** Sem o nível, a contagem
  adivinhava pelo custo de mana; sem o nome do SRD, "Bola de Fogo" e
  "Fireball" eram duas magias. Ficha antiga continua funcionando: o nível sai
  da tabela do SRD pelo nome (inclusive o nome em português), senão do custo.

O corpo da rota `/api/dnd/class-spells` virou `class_spell_catalog` no motor:
agora ela tem dois clientes (o modal e o Grimório) e a tela precisa das marcas
de limite, que são regra.

### Dois defeitos que já existiam

**O harness de capturas não devolvia os dublês.** `capturar_telas.py` troca o
banco e o `memory.save_campaign` por versões que não gravam — e nunca os
devolvia. Dentro do pytest, depois de qualquer teste de navegador o processo
seguia com um `save_campaign` mudo, e `test_o_ciclo_completo_preserva_missao_e_relogio`
via "a missão sumiu". Ficou escondido enquanto os testes de navegador rodavam
por último na ordem alfabética; `test_grimorio_navegador.py` é o primeiro que
vem antes de `test_persistencia_estado.py`. Agora os dublês são registrados e
devolvidos quando o servidor de captura para.

**A tela de nível reabria ao fechar.**

Carregava isso desde o começo: só a assinatura que **abriu** a tela ficava
marcada como vista.
Escolher o estilo de combate muda a assinatura das pendências; fechar dispara
a fila; a fila via uma assinatura "nova" e reabria a tela na cara do jogador.
As duas telas agora marcam como vista a assinatura que está na tela enquanto
ela está aberta. `test_escolher_e_fechar_nao_reabre_sozinha` falha com o
`levelup.js` anterior e passa com o corrigido.

### Lista vazia não é falha de rede

A tela dizia "A lista da classe não respondeu. Tente de novo em instantes."
para qualquer lista vazia. Um patrulheiro ou paladino de nível 1 ainda não
tem truque nem magia: a lista dele vem vazia por regra, com o SRD respondendo,
e a mensagem ficava lá para sempre.

`grimoire_snapshot` agora devolve `catalogo_motivo`, e a tela só o exibe:

- quem ainda não aprende magias nem consulta o SRD: "Patrulheiro ainda não
  aprende magias no nível 1. As primeiras chegam no nível 2."
  (`_primeiro_nivel_com_magia`);
- busca sem resultado e filtro de círculo vazio têm mensagens próprias;
- "não respondeu" só quando `class_spell_catalog` informa que o SRD não
  respondeu (`_status`).

Junto, um defeito de classe: `_CLASS_SLUG_MAP.get(classe)` casava só com o
acento. "clerigo" (ficha antiga, editor) não achava a classe, o filtro caía e
a lista trazia magias de todas as classes (73 contra 31 no nível 1). As três
consultas passam por `_classe_en`, que ignora caixa e acento, e uma classe
informada que não conjura não consulta o SRD sem filtro.

## Tela de equipamento ("A Mochila")

A sexta tela junta o que estava espalhado em três ferramentas e no editor
livre da ficha: **o que está no corpo** (e a CA que isso dá), **o que está na
mochila** (e quanto pesa) e **o que ainda não foi conferido no SRD**.

**Não abre sozinha.** Nada no mundo pede "agora arrume a mochila"; ela abre
pelo atalho **Mochila** no cartão de cada personagem do grupo (ao lado do
Grimório, para quem conjura). Fechar não manda nada ao mestre — vestir uma
armadura não é cena. Com ela aberta, as outras telas esperam, e a fila só a
redesenha com o que mudar no chat (saque, compra, venda).

**O que mostra.** No cabeçalho, os três números que mudam a cada clique: a
CA, a barra de carga com a marca da metade (acima dela, desvantagem) e as
moedas. À esquerda os cinco slots, sempre na mesma ordem — armadura, escudo,
mão principal, mão secundária, pescoço —, com o botão **Tirar**. À direita os
itens, cada um com peso, onde está equipado, a marca "próprio da campanha" e
os botões:

- **vestir/empunhar** num slot possível, com a **prévia de CA** ("Armadura
  CA 14 → 16") antes de vestir — é o que faz a troca ser decisão;
- **Identificar**, só para item que parece mágico e nunca passou pelo SRD
  (`add_item` confere na entrada; item vindo do editor ou de saque antigo não
  passou);
- **Largar 1**.

A regra de onde cada item pode ir, a prévia e o peso vêm do motor
(`inventory_snapshot`); os botões chamam `equip_item`, `unequip_item`,
`remove_item` e `identify_item` (`inventory_action`, só despacho).

### O que a Mochila expôs

Construí-la passou por `equip_item`, `remove_item` e `sell_item`, e os três
tinham defeitos que nenhum teste via. Medidos no commit anterior, guerreira
de DES 10:

```
vestiu Cota de Malha                       CA 16
vendeu a Cota de Malha na loja             CA 16, inventário vazio, slot armadura: "Cota de Malha"
equip_item("Corda de Cânhamo") sem slot    foi para [armadura], tirou a cota, CA 10
1 Adaga em arma_principal e arma_secundaria  aceitou
equip_item de item que não existe          "'Espada Inexistente' não está..." (sem prefixo)
```

- **O que sai da mochila sai do corpo.** `remove_item` e `sell_item` agora
  chamam `_desequipar_o_que_saiu`: se sobram menos unidades do que slots
  ocupados, o slot solta (a mão secundária primeiro) e a CA é recalculada — o
  texto da ferramenta diz "CA 16 → 10". Item equipado que nunca esteve no
  inventário (ficha antiga, editor) não é tocado; a tela o marca como "fora
  da mochila".
- **Item desconhecido não tem slot.** Sem slot, `equip_item` usa o que sabe
  (`_slots_para_item`: armadura e escudo pela tabela, arma pelo nome, amuleto
  por palavra); o resto é recusado pedindo o slot. Armadura e escudo, mesmo
  com slot explícito, só entram se o motor souber a CA; armadura não entra em
  slot de arma.
- **Uma unidade, um slot.** Duas adagas vão nas duas mãos; uma não.
- **Recusas com prefixo** (`Erro:`/`Nota:`) em `equip_item`, `unequip_item`,
  `remove_item` e `identify_item`, que também passou a usar `_get_char`.
- `arma_secundaria` virou slot de primeira classe no `equip_item` (antes só
  existia se o editor a tivesse criado na ficha).
- `identify_item` marca o item como conferido (`identificado`, e `custom`
  quando não está no SRD), para a Mochila não oferecer "Identificar" de novo.

### Identificar: nome em português, casamento exato e retorno na tela

Três defeitos no botão, e mais um na conferência que vinha junto:

- **O SRD é em inglês.** "Manto Élfico" não achava "Cloak of Elvenkind" e saía
  como item da campanha. `_candidatos_srd` gera os nomes em inglês a tentar:
  - nomes inteiros para o que não se compõe (`_ITEM_MAGICO_PT_TO_EN`: Bolsa
    Devoradora, Língua de Fogo, Pedra da Sorte...);
  - "cabeça de complemento" para o grosso do SRD (`_ITEM_CABECA_PT_TO_EN` ×
    `_ITEM_COMPLEMENTO_PT_TO_EN`: Anel de Proteção → Ring of Protection);
  - arma com bônus ("Espada Longa +1") → "Weapon, +1, +2, or +3";
  - e o próprio nome, para quem já escreve em inglês.

  Todos os nomes em inglês dos dois dicionários foram conferidos contra os 237
  itens do SRD no Open5e.
- **A busca aceitava qualquer resultado.** A busca textual do Open5e procura
  também nas descrições ("longsword" devolvia a Excalibur's Scabbard). O
  código ficava com o resultado de mais palavras em comum mesmo quando
  nenhuma coincidia, e gravava a descrição de outro item. Agora
  `_consultar_item_srd` só aceita o item do SRD oficial (`wotc-srd`, a busca
  vai filtrada por documento) cujo nome confere **exatamente** com um
  candidato (`_mesmo_item`, que também aceita o parêntese de "Stone of Good
  Luck (Luckstone)"). Uma tradução errada só deixa de achar; nunca troca o
  item por outro.
- **Sem conexão não é homebrew.** Com o Open5e fora do ar, o item era marcado
  como "próprio da campanha" e o botão sumia para sempre. Agora
  `identify_item` responde `Erro:` com "tente de novo" e não marca nada. Só um
  "não existe" de verdade marca.
- **O clique não dava sinal.** A consulta leva de meio a um segundo e pouco,
  e nesse tempo a tela não mudava. Agora o botão vira "Consultando…" com um
  indicador girando, o rodapé diz "Consultando o SRD de D&D 5e para Manto
  Élfico…", e os outros botões ficam desabilitados até a resposta. No fim, o
  rodapé diz o resultado em português ("Manto Élfico é Cloak of Elvenkind no
  SRD (item maravilhoso, incomum, requer sintonização)"), o item ganha a
  marca "SRD: Cloak of Elvenkind" e fica destacado por um instante.

A tela continua passando por `identify_item`. O resultado em dados
(`resultado` na resposta de `inventory_action`) sai do item gravado (`nome_srd`
e `srd`, com tipo e raridade em português), não do texto do mestre.

### Usar fora do combate

A Mochila só equipava, tirava, largava e identificava: beber uma poção depois
da luta exigia pedir ao mestre. Cada item consumível agora traz `uso` no
snapshot, calculado por `_uso_na_mochila` a partir da mesma ficha da tela
tática (`_efeito_de_item`), e `inventory_action("usar", char, item, alvo)`
aplica.

- **Poção de Cura**: "Beber" em si, e "Dar a …" para cada um do grupo que não
  esteja morto (fora do combate não há zonas). Rola a cura, respeita o teto da
  exaustão e levanta quem está caído. Quem está inconsciente ou dormindo não
  bebe sozinho: o botão dele fica travado e outro precisa dar a poção.
- **Poção de Resistência** e **Antitoxina**: duram **1 hora no relógio do
  mundo** (`ate_hora`). `_efeitos` descarta o que passou da hora, então
  `advance_time` encerra o efeito sem nenhum passo extra, e um combate no meio
  não o apaga. Os mesmos itens tomados na tela tática duram o combate.
- **Arremessos** (ácido, fogo alquímico, água benta) e **itens sem efeito
  conhecido** aparecem com o botão travado e o motivo **escrito** embaixo
  (no celular não há hover). O motor recusa com "Aviso:" e não gasta nada.
- **Em combate**, o uso é travado na Mochila com "use pela tela tática": lá ele
  custa Ação ou Ação Bônus, e a Mochila não pode ser um atalho para pular a
  economia do turno.
- O botão travado continua travado depois de outra ação na tela (`ocupar`
  respeita `data-travado`).
- Como o resto da Mochila, usar não manda nada ao mestre: a vida e os efeitos
  ficam na ficha, que ele lê.

`test_mochila_usar.py` (10) cobre o que dá para usar e por quê, beber, dar a
outro e levantar caído, caído que não bebe, teto da exaustão, alvo inválido,
arremesso e desconhecido sem gastar, combate, resistência de 1 hora (sobrevive
a um combate e acaba com `advance_time`) e antitoxina. `test_mochila_navegador.py`
ganhou os botões Beber e Dar a, a cura em outro do grupo, o travado com o
motivo e o combate.

## O mesmo acontecimento, duas vezes

`save_event` aceitava qualquer resumo, quantas vezes viesse. O mestre narrava
a emboscada, registrava, e no turno seguinte registrava de novo com outra
consequência: a ficha do local e a do personagem, que agora mostram o que
aconteceu, exibiam a cena em dobro, com dois textos que se contradiziam.

Resumo igual — sem caixa, acento nem pontuação — passa a COMPLETAR o evento
que já existe: os campos vazios dele recebem o que veio agora, o que já
estava escrito não é trocado, e a ferramenta responde com uma Nota dizendo
qual evento já registra aquilo. Acontecimento diferente continua entrando
normalmente. `test_evento_duplicado.py` (6).

## Ficha do local

Os locais eram uma lista plana: Cliviate, a Forja de Cliviate e o Boticário
não se conheciam, e personagem nenhum tinha paradeiro. Só o grupo tinha
(`current_location`). O jogador sabia que estava numa cidade, mas não tinha
como ver o que havia nela nem quem encontrar.

### Dados

- **Local dentro de local.** `save_location(..., dentro_de="Cliviate")` grava
  onde o lugar fica. Chamar de novo sem `dentro_de` mantém o que estava, e um
  local não pode ficar dentro de si nem de um lugar que já fica dentro dele.
- **Lojas entram sozinhas.** `open_shop` já grava a cidade da loja
  (`lojas[...]["local"]`); `rpg/locais.py` trata a loja como um lugar dentro
  dela, sem registro duplicado.
- **Onde o personagem está.** `save_character(..., local="Forja de Cliviate")`
  e a ferramenta nova `set_character_location(nome, local)`, para quando o
  NPC muda de lugar. O grupo não tem `local`: ele está no local atual.
- `save_character` agora parte do que já existia. Antes o personagem era
  recriado só com os campos da ferramenta, e perdia o resto (a atitude, por
  exemplo).
- Nomes casam sem caixa nem acento e são gravados como o lugar está salvo.
  Renomear um local no editor leva junto os lugares de dentro, os
  personagens, as lojas e o local atual (`_renomear_referencias_de_local`).

### Alcance

`locais.alcance(destino)` responde se dá para ir até lá **com um passo** a
partir de onde o grupo está:

| alcance | quando |
|---|---|
| `aqui` | é o local atual |
| `dentro` | fica dentro do local atual (a forja, estando na cidade) |
| `acima` | é onde o local atual fica (a cidade, estando na forja) |
| `vizinho` | fica dentro do mesmo lugar (o boticário, estando na forja) |
| vazio | longe: viagem continua sendo com o mestre |

### A tela

Abre ao clicar num lugar do mapa, no local do relance da barra lateral, ou em
qualquer tela que cite o lugar (`static/js/locais.js`,
`GET /api/locations/state?local=`). Mostra:

- o caminho até o lugar ("Cliviate ›"), com cada trecho clicável;
- se o grupo está ali, ao lado ou longe;
- **Quem está aqui**: o grupo em destaque, quando é o local atual, e os
  personagens com `local` ali;
- **Aqui dentro**: os lugares e as lojas, com quantas pessoas há em cada um.

"Ir até lá" (lugar ao alcance) e "Falar com" (personagem ao alcance e vivo)
mandam ao mestre uma fala comum do jogador: "Vamos até Forja de Cliviate." ou
"Quero falar com Brom.". A fala aparece no chat como se o jogador a tivesse
digitado, e quem narra a ida e muda o local atual é o mestre. Com o mestre
ainda respondendo, a tela avisa e não manda nada. "Editar local" abre o editor
de sempre, que ganhou "Fica dentro de"; o de personagem ganhou "Onde está".

### O mestre vê o mesmo mapa

O bloco de cena (`get_scene_context`) ganhou "Mapa do local atual": onde o
local fica, o que há dentro e quem está ali. O "onde está" gravado também
passa a contar para escolher os personagens relevantes da cena. A instrução
ganhou a seção MAPA: `dentro_de` para lugar dentro de lugar, `local` e
`set_character_location` para personagens, e `update_world_state` ao narrar
um "Vamos até ..." para um lugar ao alcance.

### No editor da campanha (menu)

O personagem ganhou "Onde está" e o local ganhou "Fica dentro de", com as
mesmas sugestões que servem ao "Local Atual" do passo 1: os locais do passo
3 e as lojas da campanha.

O salvamento desse editor apagava o que ele não conhecia. O
`PUT /api/campaigns/<nome>` recebia personagens e locais remontados só com os
campos do editor, e salvar pelo menu apagava a atitude, a marca de XP por
derrota, o "onde está" e o "fica dentro de". Além disso, a chave do local ia
com sublinhado ("praça_de_cliviate"), e o mestre depois criava
"praça de cliviate" ao lado. Agora `locais.normalizar_campanha_editada`, no
servidor:

- grava a chave do local pelo nome em minúsculas, como `save_location`;
- preserva, no local e no personagem, todo campo que o editor não mandou;
- grava `dentro_de` e `local` com o nome do lugar salvo (loja inclusive), e
  vazio apaga;
- recusa ciclo com 400 e a mensagem aparece no editor.

A marca `party_member` antiga não sobrevive a um "membro do grupo" desmarcado:
quem manda é a lista `party` enviada. `test_editor_campanha_lugares.py` cobre
a normalização e a rota; `test_editor_campanha_lugares_navegador.py` abre o
editor, confere os campos e as sugestões, muda o paradeiro de um personagem e
o "fica dentro de" de um local, salva e confere o que chegou ao servidor
(inclusive a atitude preservada).

### No wizard de criação

Os mesmos dois campos, com sugestões dos locais digitados no próprio wizard
(também no "Local Atual"). O wizard gravava a chave do local com sublinhado,
como o editor; agora usa o nome em minúsculas.

A criação (`POST /api/campaigns`) e a importação de arquivo
(`POST /api/campaigns/import`) passam por `_payload_de_campanha`, que agora
aplica `normalizar_campanha_editada` antes de gravar: chave pelo nome, nomes
canônicos em `dentro_de` e `local`, e ciclo devolvido como 400.

"Gerar com IA" pede ao modelo `dentro_de` em cada local ("preencha com o nome
exato desse outro") e `local` em cada NPC ("o nome exato do local gerado onde
ele está"). A campanha gerada já nasce com o mapa, e o wizard mostra esses
valores para revisão.

#### O que "Gerar com IA" preenche, conferido

Uma verificação do botão, com a resposta de IA no formato exato que o prompt
pede, encontrou:

- **Resposta com texto em volta falhava.** A rota só tirava as cercas de
  markdown do começo e do fim. Uma frase antes do JSON ("Aqui está o mundo da
  sua campanha:"), comum em modelo que conversa, virava erro 500.
  `_extrair_json_da_ia` tenta o texto inteiro, o bloco entre cercas e do
  primeiro "{" ao último "}".
- **Resposta cortada chegava crua ao jogador** ("Unterminated string starting
  at: line 1 column 111"). Agora a rota responde 502 com "A IA devolveu uma
  resposta incompleta (cortada antes do fim). Tente gerar de novo." (ou "não
  devolveu o mundo no formato esperado"), e o texto recebido fica no log de
  depuração.
- **O DeepSeek limitava a resposta a 1500 tokens.** Locais, eventos e até 4
  personagens passam disso, e no deepseek-reasoner o raciocínio conta no mesmo
  limite. Subiu para 8000.
- **"Personagens envolvidos" dos eventos era descartado.** A criação gravava
  o grupo inteiro em todos os eventos. O cartão de evento do wizard ganhou o
  campo, a IA o preenche, e vazio continua sendo o grupo.
- **As notas dos locais não apareciam.** A IA gera notas (segredos, história
  do lugar) e elas iam para a campanha sem ter onde revisar. O cartão de local
  ganhou o campo.
- "4 personagems" virou "4 personagens".

O resto já estava ligado: resumo, cena, local atual, os locais (com "fica
dentro de" e detalhes), os eventos (local e consequência) e os personagens
(função, grupo, descrição, traços, notas, "onde está", classe e raça). Com o
SRD no ar, os NPCs recebem a ficha do monstro (um `commoner` com CR 0 e 4 PV,
um `dire-wolf` com CR 1 e 37 PV).

`test_gerar_lore.py` simula o cliente do Gemini e o DeepSeek (os testes não
têm chave de API): texto em volta, cortada, sem JSON, os campos pedidos no
prompt e o limite do DeepSeek. `test_gerar_lore_navegador.py` clica em
"Gerar com IA" no wizard com a rota interceptada, confere cada campo dos dois
passos e o que segue para a criação, e confere que um erro da IA aparece sem
apagar o que o jogador já tinha escrito.

`test_wizard_lugares.py` cobre a criação, o ciclo, a importação, o prompt e o
que o wizard monta; `test_wizard_lugares_navegador.py` preenche locais e um
personagem, confere as sugestões e intercepta o POST de criação para conferir
o que foi enviado.

O harness de captura (`_subir_servidor`) passou a registrar a rota
`/__estado` mesmo depois de um teste com `app.test_client()` ter feito o
Flask atender a primeira requisição. Sem isso, rodar os testes de rota antes
dos de navegador na mesma sessão quebrava a subida do servidor.

### A loja com hierarquia

- Dentro da própria loja (o grupo foi "até a Forja de Cliviate"), ela é a loja
  daqui; na cidade, as duas lojas são.
- `open_shop(..., location="Cliviate")` com o grupo dentro da forja não o
  tira da loja: estar dentro do local informado é estar lá.
- Voltar da forja para a rua da cidade não é visita nova: `shop_snapshot`
  manda `filhos_chaves`, e a tela troca a marca da visita para a cidade sem
  reabrir. Entrar de novo numa loja é chegada nova.

### Testes

`test_locais.py` cobre dados, ciclo, preservação no `save_character`, alcance
a partir da cidade e da forja, a ficha, o bloco do mestre, a loja com
hierarquia e a renomeação. `test_locais_navegador.py` abre a ficha pela
Enciclopédia, pela barra lateral e pelo cartão do personagem; "Ir até lá" e
"Falar com" mandam a fala; lugar longe não tem botão; mestre ocupado não
manda nada. Capturas: `local-cidade`, `local-onde-o-grupo-esta` e
`local-loja`.

A fixture `campanha` dos testes passou a zerar também `locations`,
`current_location` e `negocios`: um local salvo num teste aparecia como lugar
"dentro" de outro no teste seguinte.

### O passado do lugar

A ficha dizia quem está lá AGORA, o que fica dentro e o caminho até lá. Tudo
o que o lugar já viu — a emboscada na estrada, o acordo na taverna — estava
gravado nos eventos e não aparecia em tela nenhuma; e a missão que o ferreiro
daquela cidade encomendou só se via na ficha dele.

- **O que aconteceu aqui** (`locais.acontecimentos`): os eventos do lugar, do
  mais recente para trás, com o capítulo e a consequência que `save_event`
  grava. Conta também o que aconteceu nos lugares de dentro — a história da
  cidade inclui a briga na forja dela —, e cada linha diz onde foi quando não
  é o lugar da ficha. Cinco na tela, com o total ao lado.
- **Missões daqui** (`locais.missoes_daqui`): missão não guarda local, então a
  ligação é achada e a ficha diz por quê — *encomendada* por quem está no
  lugar, ou *citada*, quando o nome do lugar aparece no título, na descrição
  ou num objetivo. Melhor uma ligação explicada do que um campo novo que o
  mestre teria de lembrar de preencher em toda missão. As encerradas
  continuam na lista com o status: o que já foi feito ali é parte da história
  do lugar. O botão abre a tela de missões nela.

### Lugar que o mestre citou e não registrou

O mestre narra "a trilha da montanha", o grupo vai até lá e o `current_location`
passa a ser um nome que não existe em `locations`: a ficha abre dizendo que o
lugar não foi registrado, sem descrição, sem nada dentro e sem "Editar local"
— não há o que editar. O jogador ficava com o buraco na mão.

O rodapé ganhou **"Pedir ao mestre para registrar"**, que aparece só nesse
caso e manda a fala do jogador pedindo o registro com descrição e onde o lugar
fica. Como toda fala da tela, ela entra na crônica, fecha a ficha e respeita o
mestre ocupado.

`test_historia_do_local.py` (11) e seis casos novos em
`test_locais_navegador.py`. A fixture `campanha` passou a zerar `events`:
agora que duas fichas mostram o que aconteceu, um `save_event` de um teste
aparecia na ficha do teste seguinte.

## Ficha do personagem

Quase tudo o que o jogo sabe sobre um NPC já estava gravado e não aparecia em
lugar nenhum: a atitude (-100 a +100) e o motivo de cada mudança
(`adjust_attitude` guarda as últimas cinco), as missões que ele encomendou
(`quests[...]["quem_deu"]`), os eventos em que aparece
(`events[...]["characters_involved"]`) e onde ele está. O cartão da
Enciclopédia abria direto o editor e mostrava as `notes`, campo que o editor
sugeria para "objetivos secretos": spoiler na frente do jogador.

### Dados

- `rpg/personagens.py`, `ficha(nome)`: quem é (descrição, traços, status),
  onde está e o alcance (o do grupo é o local atual), a atitude com a faixa e a
  conduta de `_faixa_atitude` e o histórico do mais recente para o mais antigo,
  o que o grupo sabe, as missões que deu, os eventos em que aparece (os
  últimos oito), a loja onde trabalha (quando o `local` é uma loja) e se dá
  para falar com ele agora (perto, vivo, não preso nem desaparecido).
- Nomes casam sem caixa nem acento. Nos eventos, o nome precisa ser um item da
  lista ("Brom, Lyra" ou "Guarda Tiel; Brom") ou uma palavra inteira do texto:
  "Bromwell" não conta como Brom.
- **O que o grupo sabe** é campo novo, `conhecido`: uma lista de fatos, sem
  repetidos, no máximo trinta (`limpar_conhecido`). O mestre registra com a
  ferramenta nova `add_character_knowledge(nome, fato)` quando o grupo
  descobre algo. Fato repetido volta com "Nota:", vazio com "Aviso:".
- **As `notes` continuam do mestre** e não entram na ficha. A instrução do
  agente explica a diferença: segredo ainda não revelado vai em `notes`, o que
  o jogador já descobriu vai em `add_character_knowledge`.
- O bloco de cena mostra ao mestre, em cada personagem relevante, "Grupo sabe:"
  com os três fatos mais recentes, para ele não contar de novo nem contradizer.

### A tela

`static/js/personagens.js`, `GET /api/characters/sheet?nome=`. Usa a moldura e
as classes da ficha do local, para as duas lerem igual. Abre pelo cartão do
personagem na Enciclopédia (o do grupo continua abrindo o editor) e pelo "Ver
ficha" em "Quem está aqui" na ficha do local. Mostra:

- nome, status, "Em Forja de Cliviate" (abre a ficha do local), descrição e
  traços;
- **Relação com o grupo**: a barra de hostil a leal com o meio marcado, a
  faixa, a conduta e cada mudança com o sinal, o motivo e o capítulo;
- **O que o grupo sabe**;
- **Ligações**: a loja onde trabalha, as missões que deu e os eventos.

"Falar com" e "Ir até onde está" mandam ao mestre a mesma fala comum da ficha
do local ("Quero falar com Brom.", "Vamos até Forja de Cliviate."). Longe do
grupo, "Falar com" fica travado e diz por quê. "Editar personagem" abre o
editor de sempre.

### Nos editores

O editor do jogo e o da campanha (menu) ganharam "O que o grupo sabe (um fato
por linha; aparece na ficha)", e "Notas" virou "Notas do mestre (segredos; não
aparecem na ficha)". O `PUT /api/memory/characters/<nome>` aceita `conhecido`
mesmo em personagem que ainda não tinha o campo, e
`normalizar_campanha_editada` limpa a lista e a preserva quando o editor não a
manda.

### Testes

`test_personagens.py` cobre a ficha (notas fora, alcance, morto perto, membro do
grupo), a atitude e o histórico, as missões, os eventos sem confundir nomes
parecidos, `add_character_knowledge` (repetido, vazio, desconhecido, limite),
o bloco de cena, a rota e os dois editores no servidor.
`test_personagens_navegador.py` abre a ficha pela Enciclopédia e pela ficha do
local, confere cada seção e que as notas não aparecem nem no cartão, clica em
"Falar com" e "Ir até onde está", confere o personagem longe e sem histórico e
grava pelo editor o que o grupo sabe. `test_editor_campanha_lugares_navegador.py`
ganhou o campo no menu, salvando sem perder o histórico da atitude. Capturas:
`personagem-ficha` e `personagem-longe`.

## Ficha do herói

Clicar no cartão de um membro do grupo abria o editor da ficha: um formulário
de campos travados (as telas controlam nível, atributos, itens e magias) que
não respondia a pergunta que o jogador faz na mesa, "quanto eu somo nisso?".
O bônus de perícia, a salvaguarda e o acerto com a arma não apareciam em
lugar nenhum; o `/ficha` do chat mostrava só atributos, CA e equipamento.

### Motor

`tools_dnd.hero_snapshot(nome)` monta a ficha de leitura com as mesmas funções
que resolvem as jogadas, para o número mostrado ser o número usado:

- vida (com PV temporários e o teto da exaustão), mana, CA, iniciativa,
  proficiência, percepção passiva e dados de vida;
- **CD de magia e ataque mágico** de quem conjura: 8 + proficiência + o
  atributo de conjuração da classe, e proficiência + o mesmo atributo. O
  motor não tinha nenhum dos dois — o mestre pedia "role Destreza CD 14" de
  cabeça e o jogador não sabia a CD das próprias magias. Os números também
  entram em `get_character_sheet`, que é onde o mestre lê a ficha, e a
  instrução dele manda usar a do conjurador em vez de chutar;
- **deslocamento** em metros: 9 m, ou 7,5 m para anão, halfling e gnomo; mais
  o Movimento Sem Armadura do monge (que cai com armadura ou escudo) e o
  Movimento Rápido do bárbaro (que cai com armadura pesada); menos o que o
  motor já modela — exaustão de nível 2 corta pela metade e a de 5 zera,
  sobrecarga tira 3 m e carga acima do limite prende no lugar. As notas do
  que somou ou cortou aparecem ao lado do número;
- atributos com modificador e salvaguarda, que soma a proficiência só nas
  salvaguardas da classe (`CLASS_DATA["saves"]`);
- perícias com o bônus e a marca de proficiente;
- ataques das armas equipadas com as contas de `attack_roll`: atributo pela
  arma (distância usa DES, acuidade usa o maior), proficiência, Arquearia no
  acerto, Duelo no dano, a nota da Grande Arma e o crítico aprimorado. O dado
  vem do SRD; arma que não está lá mostra "dado do mestre", como no combate;
- estado: condições com duração, exaustão, concentração, testes de morte (com
  0 PV) e carga, além de resistências, imunidades e vulnerabilidades;
- habilidades, equipamento, moedas, XP e se pode subir de nível.

Não grava nada.

### Um desencontro que a ficha expôs

A lista de perícias de cada classe vivia dentro do `social_check`, e só ele
somava a proficiência. O `make_skill_check(..., skill="percepção")` rolava
só o atributo: a mesma perícia dava totais diferentes conforme a ferramenta
que o mestre chamava. A tabela virou `PERICIAS_DA_CLASSE`, no módulo, lida
pelas duas ferramentas e pela ficha; `make_skill_check` com perícia da classe
soma a proficiência e mostra "+2(prof)" no resultado. Sem `skill`, continua
sendo teste de atributo puro.

### A tela

`test_conjuracao_e_deslocamento.py` (10) cobre as duas contas por classe e
raça, o que a armadura tira do monge e do bárbaro, exaustão e carga, e as
linhas na ficha que o mestre lê.

`static/js/herois.js`, `GET /api/heroes/sheet?personagem=`. Mesma moldura das
fichas do local e do personagem, mais larga. Cabeçalho com seletor de herói,
classe, raça, nível, barra de XP e as marcas de estado; a faixa de recursos;
à esquerda atributos e salvaguardas e as perícias; à direita ataques,
habilidades (a descrição abre no clique), equipamento e quem é.

Os botões levam às telas que mudam a ficha: "Subir de nível" (ou "Escolhas
de nível", com escolha pendente), "Grimório" para quem conjura, "Mochila" e
"Corrigir ficha", que abre o editor de antes. Aberta, a fila de telas a
redesenha quando o mestre muda algo no chat. No celular a ficha rola inteira
com o rodapé preso embaixo.

O cartão do grupo com ficha D&D abre a ficha do herói; membro sem ficha D&D
continua no editor.

### Testes

`test_ficha_heroi.py` (11) cobre quem entra, recursos, salvaguardas, perícias
e percepção passiva, o bônus igual ao do `make_skill_check`, o ataque com as
contas do `attack_roll`, Arquearia e crítico aprimorado, estado e defesas,
"pode subir", que a ficha não muda nada e a rota.
`test_ficha_heroi_navegador.py` (7) abre pelo cartão (e não o editor), confere
os números da tela contra o motor, condições e habilidades, troca de herói,
os botões para Mochila e tela de nível, "Corrigir ficha" e o redesenho.
Capturas: `heroi-ficha` e `heroi-conjuradora`.

## Mapa do mundo

A hierarquia de locais ("dentro de") e o paradeiro de cada personagem já
existiam, mas só se viam um lugar por vez, na ficha do local. O mapa mostra o
mundo inteiro de uma vez: onde o grupo está, o que está a um passo e quem está
em cada lugar.

Não é um mapa desenhado. O motor não tem distância nem direção, e pôr os
lugares num plano inventaria uma geografia que a campanha não tem. É uma
árvore.

### Motor (`rpg/mapa.py`)

`mapa_snapshot()` devolve:

- `local_atual`, `caminho_atual` (da raiz até onde o grupo está) e `grupo`.
- `arvore`: cada nó com `nome`, `tipo` (`local`, `loja` ou `sem_registro`),
  `descricao`, `alcance` (o mesmo de `rpg/locais.py`: aqui, dentro, vizinho,
  acima), `grupo_aqui`, `no_caminho_do_grupo`, `pessoas` (com `fora` para
  mortos e desaparecidos), `pessoas_total` (o ramo inteiro), `filhos` e
  `profundidade`. As lojas entram dentro do local delas.
- Lugar **citado mas nunca registrado** (o local atual ou o `local` de um
  personagem) entra como `sem_registro`, em vez de sumir com quem está lá.
- A raiz de onde o grupo está vem primeiro. Um "dentro de" circular não trava
  a árvore: o que sobra vira raiz.
- `ao_alcance`: os lugares a um passo, na ordem dentro, ao lado e saída.
- `sem_paradeiro`: personagens sem local.

### A tela (`static/js/mapa.js`, `GET /api/map/state`)

- Abre pelo atalho **Mapa** da barra lateral e pelo **Ver
  no mapa** da ficha do local, que abre a árvore até aquele lugar e o destaca.
- Mesma moldura das fichas. À esquerda, a árvore: o caminho até o grupo
  começa aberto, o resto abre e fecha pela seta; cada lugar mostra as marcas
  (grupo aqui, aqui dentro, ao lado, saída, loja, sem registro), quantas
  pessoas há no ramo e **Ir até lá** quando está a um passo. À direita, **A um
  passo** e **Paradeiro desconhecido**.
- **Busca** por lugar ou pessoa, sem caixa nem acento: fica só o que casa (e
  os ramos até lá), aberto e destacado.
- O nome do lugar abre a ficha do local; o nome da pessoa, a ficha do
  personagem. **Ir até lá** manda ao mestre a fala do jogador "Vamos até X.",
  como na ficha do local; com o mestre respondendo, avisa e não manda.
- As telas que abrem sozinhas (nível, grimório, saque, descanso, loja) esperam
  o mapa fechar.

### Testes

`test_mapa.py` (9) cobre a árvore com as lojas dentro da cidade, o caminho do
grupo, a ordem do que está a um passo, pessoas e o total do ramo, sem paradeiro
e sem registro, local atual não registrado, ciclo, campanha vazia e a rota.
`test_mapa_navegador.py` (8) confere o Ver o mapa com o caminho aberto, abrir e
fechar um ramo, a busca por pessoa e por lugar sem acento, Ir até lá, o mestre
ocupado, lugar e pessoa levando às fichas (e o Ver no mapa voltando com foco),
o foco num lugar fora do caminho e o saque esperando o mapa fechar. Regressões
injetadas (caminho fechado, saque por cima, mestre ocupado ignorado, busca com
acento, foco sem abrir os ancestrais, Ver no mapa sem foco, fala errada, tudo
aberto) foram todas pegas. Capturas novas (ainda não geradas): `mapa-mundo` e
`mapa-busca`.

## Visão geral do grupo

Para decidir descanso e divisão de itens o jogador abria a ficha de cada
herói, uma por vez, e fazia a conta de cabeça: quem está ferido, quem ainda
tem dado de vida, quem já pode dormir, quem aguenta carregar a cota de malha.

### Motor (`rpg/grupo.py`, `GET /api/party/overview`)

Nenhuma regra nova: cada número sai da mesma conta do resto do jogo (a ficha
do herói, a tela de descanso e a carga). `group_snapshot()` devolve:

- `herois`: um por membro do grupo com ficha, com vida (e o teto da
  exaustão), mana, CA, dados de vida (e quantos o descanso longo devolve),
  exaustão, testes de morte, concentração, condições, efeitos, moedas, itens,
  nível pendente (`pode_subir` ou escolhas por fazer) e se conjura.
- Por herói, `descanso`: `pode_longo` e `faltam_horas` (as 24 horas do
  `long_rest`) e `curto_ajuda`, que só é verdade para quem está ferido e ainda
  tem dado de vida. Vida no teto da exaustão conta como cheia.
- Por herói, `carga`: kg, capacidade, `limite_sobrecarga` (metade da
  capacidade), `folga_kg` antes de ficar sobrecarregado e `perto_do_limite`
  (80% dessa metade).
- `precisa`: o que falta a ele (caído, vida, mana, exaustão).
- `resumo`: a frase do descanso ("O descanso curto ajuda Stelar. Helena sem
  dado de vida: só o longo cura. Descanso longo: Helena e Natasha já podem;
  Stelar só daqui a 14h."), a da carga ("Mais folga para carregar: ...
  Perto do limite: Natasha."), quem tem nível pendente e o que os botões
  precisam saber. Morto aparece no cartão e fica fora das contas.

### A tela (`static/js/grupo.js`)

- Abre pelo atalho **Grupo** e pela hora do relance, na barra lateral. Mesma
  moldura das fichas.
- No alto, o resumo e **Pedir descanso curto** / **Pedir descanso longo**, que
  mandam ao mestre a fala do jogador ("Vamos fazer um descanso curto."); ele
  decide se a ficção permite e abre a tela de descanso. Os botões travam em
  combate, sem ninguém ferido, ou quando ninguém ganha com aquele descanso;
  com o mestre respondendo, avisam e não mandam.
- Um cartão por herói: nome (abre a ficha), classe, nível e CA, selo **Subir
  de nível** / **Escolha de nível** (abre a tela de nível), marcas de estado,
  barras de vida e mana, dados de vida, situação do descanso, barra de carga
  com o traço onde começa a sobrecarga, itens e moedas, o que precisa, e os
  atalhos para a Mochila e o Grimório.
- Aberta, a fila de telas a redesenha: dano ou item dado pelo mestre aparece
  na hora. As telas que abrem sozinhas esperam ela fechar.

### Testes

`test_grupo.py` (13) cobre o cartão por membro com ficha, vida, mana e dados
de vida, o teto da exaustão, o descanso de cada um e o resumo, sem feridos e
em combate, a carga com folga e perto do limite, sobrecarregado, nível
pendente, condições e caído, morto fora das contas, grupo vazio e a rota.
`test_grupo_navegador.py` (9) confere a abertura pela barra lateral, os
números do motor nos cartões, o resumo, pedir descanso, o mestre ocupado, os
botões travados sem ferido, os atalhos para ficha, Mochila e nível, o
redesenho com a tela aberta e o saque esperando ela fechar. Regressões
injetadas (saque por cima, mestre ocupado, sem redesenho, botão livre sem
ferido, nível abrindo a ficha, curto sem dado de vida, sem aviso de limite,
morto nas contas, teto da exaustão ignorado) foram todas pegas. Captura nova
(ainda não gerada): `grupo-visao-geral`.

### Companheiro sem ficha de regras

`group_snapshot` só conhecia quem tem ficha, e a barra lateral desenhava a
mesma lista. Numa campanha D&D, o companheiro que o mestre recrutou pela
narrativa e nunca recebeu atributos **sumia das duas telas** — estava no
grupo para o motor (`is_party_member`), mas não aparecia em lugar nenhum
onde o jogador olha o grupo.

O snapshot passa a devolver `sem_ficha`: nome, papel (da lista `party` ou do
próprio personagem), descrição e se está morto. A barra lista essas pessoas
depois dos heróis, sem números — não há de onde tirá-los —, e a visão geral
dá a elas um cartão de borda tracejada com o papel, a descrição e um botão
para a ficha do personagem, que é onde vivem a história e o que o grupo sabe
delas. Elas não entram no resumo de descanso nem na conta de carga, que
falam de vida, dados de vida e quilos que elas não têm.

`test_grupo.py` ganhou três casos (a lista própria, o resumo intocado e quem
tem ficha nunca caindo nela, com um NPC sem ficha fora do grupo para provar
que a porta não abriu demais) e `test_grupo_navegador.py` mais dois (o cartão
levando à ficha do personagem e a volta à barra lateral).

## O diário como livro

O diário era uma lista de entradas na barra lateral que abria um modal de
edição, e os eventos da linha do tempo não apareciam em lugar nenhum da tela
(só na ficha do personagem). Para reler a campanha o jogador exportava um .md.

### Motor (`rpg/diario.py`, `GET /api/diary/book`)

`diary_snapshot()` devolve os capítulos em ordem (os do diário, os dos
eventos e o atual, mesmo vazio). Cada capítulo traz:

- `entradas` do diário daquele capítulo, com o `indice` na lista (para o
  editor) e o título da primeira como título do capítulo;
- `eventos` registrados nele, cada um com local, consequência e os
  personagens separados (`tem_ficha` diz se vira link);
- `personagens` ligados: os dos eventos mais os citados no texto das
  entradas, casados como palavra inteira, sem caixa nem acento ("Ana" não
  casa em "banana"), os mais citados primeiro;
- `locais`: os dos eventos mais os locais e lojas citados no texto;
- `missoes` que começaram (`cap_inicio`) ou terminaram (`cap_fim`) ali.

Capítulo gravado como `"2"` (JSON importado) vale como 2.

**Eventos e capítulo.** `save_event` não guardava o capítulo; agora guarda.
Evento gravado antes não tem como ser datado e aparece em
`eventos_sem_capitulo`. `mover_evento` (`POST /api/diary/move-event`) põe um
evento no capítulo que o jogador escolher.

Dois defeitos antigos corrigidos no caminho:

- **"+ Entrada" não gravava.** O editor manda a entrada nova para a posição
  logo depois da última, e o servidor respondia "Não encontrado". Agora essa
  posição cria a entrada.
- **Evento com número gravado como texto** (`"index": "3"`, de JSON
  importado) não era achado pela edição, que comparava com o número 3.

### A tela (`static/js/diario.js`)

- Abre pelo atalho **Diário** e pelo **Capítulo** do relance (no capítulo
  atual), na barra lateral; `Diario._abrir(capítulo, entrada)` abre numa
  entrada, em destaque.
- Índice à esquerda com cada capítulo (título, entradas, eventos, o atual
  marcado) e "Sem capítulo" quando há eventos antigos. À direita, a página:
  as entradas como texto corrido, com capitular, e o **Neste capítulo** com os
  eventos, os personagens (fichas), os locais (fichas dos locais) e as
  missões (tela de missões). **Capítulo anterior** e **Próximo capítulo**
  viram as páginas.
- A escrita continua no editor de sempre: **Editar** em cada entrada e **Nova
  entrada**, já com o capítulo da página.
- Na página "Sem capítulo", cada evento tem um seletor (sugere o capítulo
  atual) e **Pôr no capítulo**.
- Aberto, a fila de telas o redesenha: a entrada que o mestre acabou de
  escrever aparece na página. As telas que abrem sozinhas esperam ele fechar.

### Até aqui e exportar

- A primeira página do livro é **Até aqui**: o resumo da história (que morava
  na barra lateral), o capítulo atual, o local e a cena, com **Editar resumo e
  estado do mundo**. `diary_snapshot()` traz `ate_aqui` com o resumo, a cena e
  o local. As páginas seguem a ordem Até aqui, capítulos, Sem capítulo, e os
  botões do rodapé viraram **Página anterior** e **Próxima página**.
- **Exportar (.md)** no rodapé baixa o diário. O botão da barra lateral nunca
  funcionou: a rota devolve o próprio arquivo, e o `exportDiary` lia a
  resposta como JSON e quebrava antes de baixar. A rota também usava
  `memory.CAMPAIGN_NAME`, que não é o nome da campanha, e agora monta o nome
  do arquivo só com letras, números, espaço, hífen e sublinhado.

### Testes

`test_diario.py` (14) cobre os capítulos em ordem com as entradas, o capítulo
gravado no evento, personagens com e sem ficha, os mais citados primeiro,
nome só como palavra inteira, locais do evento e do texto, missão que começou
e terminou, capítulo gravado como texto, evento sem capítulo e o mover,
capítulo atual vazio, diário vazio, as rotas, o "+ Entrada" e o evento com
número em texto. `test_diario_navegador.py` (10) confere a abertura pelo "Ler
o diário", pelo capítulo da aba Mundo e pela entrada da barra lateral, virar
as páginas, os links do "Neste capítulo", Editar, Nova entrada gravando de
verdade, pôr evento no capítulo, o redesenho com o livro aberto e o saque
esperando ele fechar. Regressões injetadas (entrada abrindo o editor, entrada
nova com 404, sem destaque, sem nomes do texto, evento sem capítulo, mover
quebrado, sem redesenho, saque por cima, eventos de todos os capítulos, nome
dentro de palavra, número do evento em texto) foram todas pegas. Capturas
novas (ainda não geradas): `diario-capitulo` e `diario-sem-capitulo`.

A página Até aqui e o exportar somam dois testes de motor (o `ate_aqui` e o
nome de arquivo seguro) e três de navegador (o resumo com o local e a volta ao
capítulo, o editor do mundo e o download com o conteúdo em Markdown).
Regressões injetadas (exportar lendo JSON, virar sem a página Até aqui,
resumo vazio) foram pegas.

## Índice de personagens

A Enciclopédia da barra lateral era o único lugar que listava todos os
personagens, numa coluna estreita e sem busca. O índice é uma tela.

### Motor (`rpg/personagens.py`, `indice`; `GET /api/characters/index`)

- Cada personagem com a **categoria** (grupo, conhecido, inimigo, morto; um
  membro do grupo morto vai para os mortos), se está **aqui** (no mesmo lugar
  que o grupo, pela mesma regra de alcance da ficha do local; morto não conta),
  onde está, a descrição curta e a relação com o grupo, só para quem o mestre
  já mexeu na atitude.
- Ordem: o grupo, quem está aqui, depois conhecidos, inimigos e mortos, por
  nome.
- A contagem por filtro: todos, aqui, grupo, conhecidos, inimigos, mortos.

### A tela (`static/js/elenco.js`)

- Busca sem caixa nem acento pelo nome, pelo lugar, pela descrição e pela
  situação; filtros com a contagem do motor.
- Clicar abre a ficha que já existe: a do herói para quem é do grupo e tem
  ficha, a do personagem para os demais.
- **Novo personagem** e **Novo membro do grupo** abrem o editor de sempre.
- Aberta, a fila de telas a redesenha; as telas que abrem sozinhas esperam
  ela fechar.

### Testes

`test_indice_personagens.py` (9) cobre a ordem, as categorias, quem está aqui,
a contagem, a atitude só quando mexida, a descrição curta, membro do grupo
morto e a rota. `test_elenco_navegador.py` (7) confere a lista com a contagem,
os filtros, a busca sem acento por nome, lugar e descrição, a ficha certa ao
clicar, o editor para novo personagem e novo membro, o redesenho com a tela
aberta e o saque esperando. Regressões injetadas (sem redesenho, saque por
cima, busca só no nome, herói abrindo a ficha de NPC, filtro "aqui" ignorado,
morto contado como presente, membro morto no grupo) foram todas pegas.
Capturas novas (ainda não geradas): `personagens-indice` e
`personagens-aqui`.

## Grimório: o SRD fala inglês

O catálogo vem do Open5e: "Cure Wounds", "Evocation" e a descrição em inglês.
A mesa é em português, e o jogador escolhia a magia por um nome que não é o
que ele lê na ficha depois de aprendê-la.

Traduz o que dá sem inventar: o **nome**, pela mesma tabela que o
`learn_spell` usa para achar a magia no SRD (`SPELL_PT_TO_EN`, invertida), e a
**escola**, que é um conjunto fechado de oito. A **descrição** fica como veio
e o cartão a identifica como do SRD — menos a das magias que o motor já
descreve em português (`DEFAULT_SPELLS_BY_CLASS`). O nome do SRD vai junto no
snapshot e aparece pequeno ao lado, porque é por ele que se procura a magia em
qualquer livro.

## A mana era diferente em cada tela

A mesma clériga aparecia com 28 de mana na ficha do herói e 14 no Grimório.
O motor corrige o pool pela tabela oficial de Pontos de Magia ao carregar a
campanha (`_migrate_mana_pool`), mas quem semeia estado por outro caminho — o
harness de capturas e os testes de tela — pulava a correção, e a tela mostrava
um número que o jogo nunca mostraria.

As correções de carga viraram `memory.normalizar_campanha()`, chamada pelo
`load_campaign` e por quem semeia estado. `test_mana_e_nomes_do_grimorio.py`
(6) cobre o pool corrigido, as duas telas dizendo o mesmo, o NPC que não é
mexido, e a tradução de nome, escola e descrição.

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

A tela abre **sozinha uma vez por visita** a um local que tem loja
(`open_shop(..., location=...)`). Loja é estado que persiste, e reabrir a tela
em toda cena por causa de uma ferraria visitada no capítulo 2 seria
intromissão. Recarregar a página parado na forja não reabre; sair da cidade e
voltar é uma visita nova e reabre. A memória da visita fica no `localStorage`,
por campanha: é conveniência de quem joga naquele navegador, não estado do
mundo. Antes ela vivia numa variável, e um F5 bastava para a loja pular na
cara de novo.

**Chegar a outra cidade e entrar na loja.** O grupo seguiu da Clareira das
Brumas Eternas para Cliviate e entrou na forja. O mestre salvou o local e
abriu a loja com `location="Cliviate"`, mas não chamou `update_world_state`.
O local atual do grupo continuou na Clareira; como a tela só mostra lojas do
local atual, ela não abriu e nem a pílula apareceu. A instrução do mestre já
dizia que `location` é **onde o grupo está**, e agora o motor honra isso: se
difere do local atual, `open_shop` passa a ser o local atual do grupo (com o
nome do local salvo, se houver) e avisa com `Nota:`. Para reabastecer uma
loja de outro lugar sem mover o grupo, omite-se `location`.
`test_loja_ao_chegar.py` cobre a chegada, o mesmo local escrito diferente e
o reabastecimento.

Junto veio o cartão de Cliviate na Enciclopédia, que mostrava "Salva ou
atualiza um local na memória da campanha.": o modelo copiou o texto de ajuda
da ferramenta para `description`. `save_location` agora reconhece a cópia
(`_copia_da_ajuda`). Se `details` for texto de verdade, ele vira a descrição;
senão, a resposta é `Erro:` pedindo a descrição do ambiente.

Com mais de uma loja no mesmo local, o cabeçalho ganha um seletor e a pílula
diz "2 lojas em Oakhaven". Antes a tela só conhecia a primeira loja do
local — o boticário ao lado da forja era inalcançável. Fechada, fica a pílula
no canto para voltar.

No mobile a pílula (e as de combate e nível, que dividem o canto) fica **acima
do bloco de entrada**, não na borda da tela. O `#input-area` tem
`padding-bottom` largo de propósito, para a barra do sistema — gestos, 3
botões, home indicator —, e a pílula caía por cima da dica "Digite / para ver
os comandos". A posição é medida por `posicionarPilulas()` em `game.js` e vai
para `--pilula-base`: um valor fixo no CSS não serviria, porque o bloco cresce
para cima quando a bandeja de dados abre, e o menu de comandos flutua acima
dele sem entrar na sua altura. A barra de baixo do celular entra na mesma
conta: ela nasce vazia e ganha altura quando a barra lateral desenha os botões,
e some quando o teclado abre, e das duas vezes o bloco de entrada muda de lugar
sem mudar de tamanho. Um `ResizeObserver` nos três reposiciona. No
desktop a variável não é definida e vale o padrão de 20px da borda. "Encerrar as compras" manda
`[COMPRAS RESOLVIDAS NA TELA]` para a IA narrar a saída — o mesmo desenho do
recap de combate: a tela resolve os números, a narração continua sendo dela.

**O resumo diz o que foi negociado.** O texto ao encerrar era sempre "O grupo
terminou de negociar em X. Narre a saída da loja". O grupo saiu do boticário
sem comprar nada, e o mestre narrou "guardam os novos suprimentos em suas
mochilas". Agora `buy_item` e `sell_item` (da tela ou do mestre) registram
cada negócio com um número de sequência (`campaign["negocios"]`, os últimos
50). A tela guarda o número de quando a visita começou (`negocios_seq` do
snapshot, no `localStorage`, então vale também depois de fechar no ✕,
reabrir pela pílula ou recarregar a página). Ao encerrar, pede o texto a
`GET /api/shop/recap?desde=N` (`shop_recap_payload`), que lista "Alden
comprou 2x Poção de Cura; Lyra vendeu 1x Adaga" e avisa que os itens já
estão nas fichas. Sem negócio, diz que o grupo saiu SEM comprar nem vender
nada. Compra recusada não conta.

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

## Tela de missões ("O Livro de Missões")

As missões apareciam só na barra lateral, e só as ativas: sem recompensa, sem
desfecho e sem o histórico do que o grupo já fez ou deixou de fazer.

### Quem decide o quê

O que aconteceu na história continua sendo decisão do mestre:

- **Marcar objetivo** é a lista de tarefas do jogador. Cada marcação fica
  anotada, marcar e desmarcar o mesmo objetivo se cancelam, e ao **fechar** a
  tela o mestre recebe **um** aviso `[MISSÕES ATUALIZADAS NA TELA]` com o que
  mudou. A instrução dele diz para confirmar na narração ou desfazer com
  `update_quest_objective(..., done=False)`, e para não concluir missão nem
  entregar recompensa por causa do aviso.
- **Abandonar** é decisão do grupo e fica na tela (com dois cliques, porque
  não tem volta por ela). **Concluir** e **falhar** ficam com o mestre, que é
  quem entrega ou não a recompensa.
- Com todos os objetivos feitos, a missão aparece como **pronta para
  entregar** e ganha **Falar com <quem deu>**, que manda ao mestre a fala do
  jogador ("Quero falar com Kaelen sobre a missão ..."), como a ficha do local.
  Se havia marcações, o aviso vai antes da fala.

### Motor (`rpg/missoes.py`)

- `quest_snapshot()`: todas as missões ordenadas por situação, com os
  objetivos, quem deu (e se é uma ficha, para virar link), recompensa,
  capítulos, desfecho e `pronta_para_entregar`; a contagem por situação e
  quantas mudanças esperam o aviso.
- `quest_action`: `marcar` e `desmarcar` pelo **índice** do objetivo (o
  `update_quest_objective` casa por trecho de texto, e "Chegar" marcaria
  "Chegar a Luminas" e "Chegar ao porto"), `abandonar` (por `complete_quest`) e
  `fechar` (devolve o aviso e limpa as anotações).
- **Chave sem acento.** Missão gravada com a chave `a divida de torbin` e o
  título "A dívida de Torbin" não era encontrada pela tela nem pelas
  ferramentas do mestre, que procuravam pela chave exata. `_achar_missao`
  (`rpg/tools.py`) procura pela chave e, se não bater, pelo título sem caixa
  nem acento; `update_quest_objective`, `complete_quest`, `get_quest` e a tela
  usam a mesma busca.

### A tela (`static/js/missoes.js`)

- Abre pelo atalho **Missões** da barra lateral (com a contagem das ativas)
  e pela missão principal do relance (aberta na aba dela e destacada).
- Mesma moldura das fichas. Abas: **Ativas**, **Concluídas** e **Falhadas e
  abandonadas**, com a contagem. Cada missão: título, progresso, capítulos,
  descrição, **Encomendada por** (link para a ficha do personagem quando ele
  existe), **Recompensa**, objetivos com caixa de marcar (travadas nas
  encerradas) e o **Desfecho**.
- As telas que abrem sozinhas esperam a de missões fechar.

### Testes

`test_missoes.py` (12) cobre o snapshot, marcar pelo índice, pronta para
entregar sem concluir, o aviso único ao fechar com marcações que se cancelam,
fechar sem mudanças, abandonar, encerrada que não se mexe, chave sem acento
(na tela e nas ferramentas do mestre), recusas e rotas.
`test_missoes_navegador.py` (7) confere Ver todas com as abas, a missão da
barra lateral abrindo a tela nela, a encerrada na aba certa, marcar com a
barra lateral acompanhando e o aviso ao fechar (e nenhum aviso sem mudanças),
Falar com quem deu, o link para a ficha do personagem e o abandono com
confirmação. Capturas novas (ainda não geradas): `missoes-ativas` e
`missoes-encerradas`.

## Tela de saque ("O Espólio")

No fim do combate o mestre chamava `add_item` e `modify_currency` direto na
ficha de quem ele achasse melhor. O sistema de carga existe para o saque virar
escolha (levar a cota de malha deixa o guerreiro sobrecarregado na próxima
luta), e essa escolha era do mestre, não do jogador.

### Motor (`rpg/saque.py`)

- **`offer_loot(items, gold, silver, copper, source)`** põe o saque no chão:
  `"Espada Curta; Poção de Cura:2; Anel de Osso:1:lembrança, não faz nada"`
  (quantidade e descrição opcionais). Chamar de novo com o saque aberto
  acrescenta. Recusa em combate e sem grupo.
- A **conferência de item inventado** do `add_item` foi extraída para
  `_conferir_item_novo` e roda no `offer_loot`: o aviso de item fora do SRD com
  efeito mecânico volta para o mestre na hora de pôr no chão. O verificador do
  servidor (`_check_itens_inventados`) passou a olhar também o saque aberto, e
  `justify_custom_item` aceita o item que ainda está no chão.
- O peso de cada item é gravado no saque (`_peso_do_item`), sem ir à rede de
  novo a cada redesenho.
- `loot_snapshot()`: os itens com quanto sobra no chão, e cada um do grupo com
  o que vai levar, a **carga atual e a prevista** (com o estado: livre,
  sobrecarregado, imóvel) e as moedas que recebe.
- `loot_action`:
  - `dar` / `devolver` (item por id ou nome, uma unidade por vez; morto e
    quem não é do grupo não levam);
  - `moedas` (`igual`, com o resto de cada moeda uma unidade para cada um dos
    primeiros; ou tudo para uma pessoa);
  - `concluir` (os itens entram nos inventários, empilhando como o
    `add_item`, e o que ninguém pegou fica para trás);
  - `deixar` (ninguém leva nada).
- O resumo do combate vencido (`combat_recap_payload`) e a instrução do mestre
  mandam usar `offer_loot` para o saque, e não `add_item`/`modify_currency`,
  que ficam para o que é dado a uma pessoa.

### A tela (`static/js/loot.js`)

- Abre **sozinha pela fila**, depois do nível e do grimório (a Força nova muda
  a carga) e antes do descanso. Fechada no ✕ vira a pílula "Saque para
  dividir"; o saque continua no chão.
- À esquerda o que está **no chão**, com um botão por pessoa ("Dar para:") e as
  moedas com a escolha de divisão. À direita **quem leva**: a barra de carga
  com o peso atual, a parte que o saque acrescenta em cor mais forte, a marca
  da metade e o estado que piora em vermelho ("livre → sobrecarregado"), além
  do que cada um leva com "Devolver".
- **Concluir** diz quantos itens ficam para trás, põe tudo nas fichas e manda
  `[SAQUE RESOLVIDO NA TELA]` com quem ficou com o quê; **Deixar tudo para
  trás** manda `[SAQUE DEIXADO NA TELA]`. As duas são mensagens internas: não
  aparecem no chat ao reabrir a campanha.

### Nenhuma tela abre por cima das fichas

As telas que abrem sozinhas (nível, grimório, descanso, loja e saque) só
conheciam umas às outras e a Mochila. As fichas do local, do personagem e do
herói ficaram de fora da lista, e o descanso ou a loja podiam abrir por cima
delas. Agora todas esperam a ficha fechar.

### Testes

`test_saque.py` (13) cobre o saque no chão sem tocar nas fichas, acrescentar,
recusas, dar e devolver com a carga prevista, unidades divididas, morto e nome
inválido, moedas por igual com resto e tudo para um, concluir com empilhamento
e o que fica para trás, deixar, combate, item inventado cobrado no chão (e a
justificativa), a ferramenta e o resumo do combate, e as rotas.
`test_saque_navegador.py` (6) confere a abertura sozinha, dar e devolver com a
carga prevista, moedas para uma pessoa, concluir com a mensagem ao mestre e o
item na mochila, a pílula, e que o saque espera a ficha do herói fechar.
`test_ficha_heroi_navegador.py` confere o mesmo para o descanso. Capturas
novas (ainda não geradas): `saque-no-chao` e `saque-divisao`.

## Tela de descanso ("A Fogueira")

A quarta tela. Ela não existe por ser um laço (como combate e loja) nem para
impedir invenção de regra (como a de nível): existe porque, no 5e, **quem gasta
os dados de vida é o jogador**, um de cada vez, olhando quanto curou. Guardar
dado para amanhã é a decisão que dá peso à reserva — e no chat ninguém tomava
essa decisão: o motor rolava tudo de uma vez.

**Quem abre é o mestre.** A tela não tem botão de "descansar agora": é a ficção
que diz se o acampamento é seguro. A IA chama `offer_rest("curto")` ou
`offer_rest("longo", "na estalagem do Passo de Vhar")`, a proposta fica gravada
na campanha (é estado do mundo, vale em qualquer aba) e a tela abre sozinha,
uma vez por proposta. Cada proposta tem um id tirado de um contador que
sobrevive a ela — se o id viesse da própria proposta, apagada ao concluir, o
próximo descanso nasceria com o mesmo número e a tela acharia que já tinha
aberto.

### Descanso curto

Um cartão por personagem do grupo, lado a lado: descansar é uma decisão
coletiva, e só dá para decidir quem gasta e quem guarda vendo todos. Cada
cartão mostra a vida, **um marcador por dado da reserva** (cheio = disponível,
vazio = gasto), a regra do dado (`1d10 +3 por dado`) e o botão **Gastar 1
dado**. Quando o botão trava, ele diz por quê — *Vida cheia*, *Reserva vazia*,
*Morto* — em vez de só apagar.

**Não descansar** trava depois do primeiro dado. A cura já aconteceu, e
cancelar apagaria a hora de descanso que pagou por ela: seria a cura infinita
de volta, pela tela. O motor recusa também; o botão travado só evita oferecer
o clique. **Concluir descanso** passa a hora (uma vez para o grupo) sem gastar
mais nenhum dado.

### Descanso longo

Não há decisão por personagem, então o cartão mostra o que a noite vai fazer
(vida e mana cheias, quantos dados de vida voltam — metade da reserva, conta
feita no motor —, exaustão menos um) e, principalmente,
**quem não pode dormir ainda e quanto falta** para as 24 horas. Quem pode dormir
é decidido *antes* de alguém dormir: o primeiro `long_rest` avança o relógio 8
horas, e decidir dentro do laço fazia o resultado depender da ordem do grupo —
quem descansou há 20 horas era recusado se viesse primeiro e aceito se viesse
depois de outro ter passado a noite. Se ninguém pode, **Dormir 8 horas** trava.

A noite tira as condições com duração e mantém as indefinidas. Doença e
maldição **não** saem com o descanso: o código dizia isso no comentário e fazia
o contrário, removendo justamente as duas (coberto por
`test_duracao_das_condicoes.py`).

### O que fecha a tela

- **Concluir** manda `[DESCANSO RESOLVIDO NA TELA]` com o resumo (dados
  gastos, hora nova) para a IA narrar; **Não descansar** manda
  `[DESCANSO CANCELADO NA TELA]`.
- **Emboscada:** `roll_initiative` apaga a proposta. A tela aberta se fecha no
  próximo sincronismo, em vez de oferecer depois da luta uma hora de sossego
  que não houve.
- O **✕** só fecha: a proposta continua, e fica a pílula "Descanso curto
  aberto". Recarregar a página não reabre.

Na fila de telas o descanso vem depois do nível e antes da loja: é o mestre
que abre o descanso no meio da cena, e a loja é só um lugar onde o grupo por
acaso está parado.

### Mesmo contrato das outras telas

`rest_action` é **só despacho**: `dado` chama `use_hit_die`, `concluir` chama
`short_rest(nome, hit_dice=0)` ou `long_rest` para cada um, `cancelar` apaga a
proposta. `test_a_tela_passa_pelas_MESMAS_funcoes_do_mestre` espia as três.

### Quatro pílulas no mesmo canto

O empilhamento das pílulas de voltar era CSS de irmão — uma regra por
combinação de pílulas visíveis. Com três eram três regras; com a quarta seriam
sete. Agora `empilharPilulas()` (em `game.js`) dá a cada pílula visível a sua
posição na pilha (`--pilula-ordem`), um `MutationObserver` na classe `hidden`
refaz a conta, e o CSS só multiplica por 56px. As telas continuam sem saber
umas das outras. `test_pilulas_de_loja_e_descanso_nao_se_sobrepoem` mede as
duas caixas.

## Wizard e editores de ficha

O wizard de criação de campanha e os dois editores de ficha (o da campanha, no
menu, e o "Editar Ficha Completa", no jogo) são mais antigos que as telas. Cada
um tinha as suas tabelas de regra, copiadas do motor à mão, e gravava por cima
do que as telas controlam. As cópias já discordavam do motor:

| Regra | No navegador | No motor |
|---|---|---|
| Círculo máximo de magia | `ceil(nível / 2)` para toda classe: paladino de nível 3 recebia 2º círculo | meio conjurador só chega ao 1º círculo no nível 3 |
| Incremento de atributo | só nos níveis 4, 8, 12, 16 e 19 | guerreiro também no 6 e no 14, ladino no 10 |
| Nível da magia inicial | `Math.round(custo_mana / 4)`: 3º círculo (custo 5) virava 1º | `SPELL_MANA_COST` e `SPELL_LEVEL_OVERRIDE` |

### As regras saem de um lugar só

`rules_catalog()` (em `tools_dnd.py`, rota `GET /api/dnd/regras`) monta as
tabelas chamando as mesmas funções que o jogo usa: `_limite_de_magias`,
`_nivel_maximo_de_magia`, `_niveis_asi`, `_max_mana_for`, `_proficiency_bonus`,
`XP_THRESHOLDS`, `SPELL_MANA_COST`. No navegador, o módulo `Regras` (em
`utils.js`) carrega o catálogo uma vez e oferece leitores síncronos
(`limiteDeMagias`, `circuloMaximo`, `incrementos`, `mana`, `dadoDeVida`,
`xpProximo`, `proficiencia`, `nivelPorCusto`). O wizard e os editores esperam
`Regras.carregar()` antes de abrir; `menu.js` e `game.js` ficaram só com os
rótulos das classes.

`test_js_nao_define_tabela_de_regra` falha se uma das tabelas antigas voltar a
ser declarada em `menu.js` ou `game.js`, e
`test_magias_iniciais_do_wizard_tem_nivel_e_custo_do_motor` confere o nível e o
custo de cada magia inicial do wizard contra o motor.

### O editor para de competir com as telas

Numa ficha **já salva e jogável** (classe diferente de `npc`), os editores
mostram nível, XP, atributos, CA, vida e mana máximas, dado de vida,
equipamento e habilidades **só para leitura**, dentro de um
`<fieldset class="ed-trava" disabled>`, com o aviso de qual tela cuida de cada
coisa. O "Editar Ficha Completa" traz atalhos para a Mochila, o Grimório e a
tela de nível. Continua livre o estado do momento: nome, descrição, notas,
vida e mana atuais, moedas, inventário.

Personagem novo e NPC não são travados. Para consertar uma ficha que o mestre
estragou, há o **Modo de correção** ("passa por cima das regras"): destrava
tudo e o salvamento vai com `correcao_manual: true`.

A trava do navegador é conforto; a garantia está no servidor.
`normalize_edited_character(novo, antigo, correcao_manual)` roda no
`PUT /api/campaigns/<name>`, no `PUT /api/memory/characters/<name>` e na
criação:

- sem correção, cada campo de construção que mudou volta ao valor gravado, e
  as habilidades também. Isso cobre um cliente antigo em cache ou um campo
  forçado por script. Os campos mantidos voltam na resposta (`mantidos`) e o
  editor avisa;
- sempre, com ou sem correção, ajusta o que não pode ficar incoerente: reserva
  de dados de vida entre 0 e o nível, vida e mana atuais abaixo do máximo,
  `nivel_magia` gravado em cada magia, e item tirado da mochila sai do corpo. A
  CA só é recalculada quando algo sai do corpo, para não apagar uma CA posta
  pelo mestre (Armadura Arcana, anel);
- a flag `correcao_manual` não é gravada na ficha.

### Observações do mestre no editor da campanha

As observações (`quest_flags`, fatos do mundo como "ponte_caiu = sim") saíram
da barra lateral do jogo e ficam no primeiro passo do editor da campanha, no
menu: uma linha por observação, com nome e valor, **+ Observação** e remover.
O salvar descarta linha sem nome e tira espaço das pontas. O
`PUT /api/campaigns/<name>` grava `quest_flags` e, se um cliente antigo não
mandar o campo, mantém as que existem.

No caminho, o salvar do editor parou de apagar o capítulo de cada evento: os
eventos eram remontados só com resumo, personagens, local e consequência, e o
diário mandava todos para "Sem capítulo".

`test_editor_observacoes_navegador.py` (3) confere as observações no primeiro
passo, adicionar, mudar e remover gravando, e o capítulo dos eventos mantido;
`test_rota_grava_observacoes_e_cliente_antigo_nao_apaga` cobre a rota.

### A mesma moldura das telas

Os três modais (wizard, editor da campanha e editor de registro do jogo)
tinham a caixa branca genérica, com letra cursiva e botão preto, e pareciam
de outro aplicativo ao lado da Ascensão e da Mochila. A classe `.moldura-tela`
no overlay traz a moldura das telas: papel creme, borda dourada, título
vermelho centrado, faixa de rodapé, botão principal vermelho, campos em Lora
e atributos nas células da régua da Ascensão. No mobile os três viram tela
cheia, como as outras.

As telas não seguem o tema das configurações, e a moldura também não: ela
redefine as variáveis de tema (`--page-edge`, `--ink-user`, `--text-main`...)
dentro do overlay. Assim os estilos inline que o `menu.js` e o `game.js` já
usavam passam a desenhar na paleta das telas sem precisarem ser reescritos.
`test_wizard_usa_a_moldura_das_telas_mesmo_com_tema_escuro` liga o tema
"noite-tinta" e mede as cores calculadas.

`test_regras_e_editores.py` cobre o catálogo e a normalização;
`test_editores_navegador.py` (Playwright) abre os dois editores, confirma a
trava, força o nível por JS e verifica que ele não é gravado enquanto a vida
atual é, liga o Modo de correção e grava a CA.

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
│ [Atacar] [Habilidade] [Item] [Mover]                       │
│ [Defender] [Fugir] [Ação Livre] [Encerrar]                 │
└────────────────────────────────────────────────────────────┘
```

Com zonas em jogo, uma faixa aparece acima do campo com a trilha e quem está
em cada ponto — o destaque marca a zona de quem joga agora:

```
┌ Portão ─────────┐ → ┌ Pátio ──────────┐ → ┌ Sacada ─────────┐
│ Helena  Natasha │   │ Stelar ◀ é a vez│   │ Victoria        │
└─────────────────┘   └─────────────────┘   └─────────────────┘
```

### Submenu Atacar, escolha de arma

- Lista armas **equipadas** (principal + secundária) + **armas do inventário**
  (espada, arco, besta, adaga, lança, machado, martelo, cajado, etc.) +
  "Ataque desarmado".
- Depois mostra o picker de alvo. A intenção `{action:'attack', actor,
  target, weapon}` vai para `/api/combat/action`.

### Submenu Habilidade, só ativas, etiquetadas

- **Filtra passivas** (Proficiência: Atletismo, Estilo de Combate,
  Resistência a X, Idioma…), vão pra `passivas` (só info, sem botão).
- Cada ativa traz etiqueta `[Ação]` (azul) ou `[Bônus]` (verde).
- Desabilitada se o slot já foi gasto.

### Submenu Item, itens com efeito

Antes só a Poção de Cura fazia alguma coisa. Todo o resto que parecia
consumível pelo nome (ácido, fogo alquímico, antídoto, poção de resistência)
gastava a Ação e a unidade sem efeito nenhum, e a própria poção chegava a
aliado em outra zona e curava acima do teto da exaustão.

`_efeito_de_item` dá a cada item uma ficha com o efeito do SRD (regras de
2024):

| Item | Custo | Alvo | Efeito |
|---|---|---|---|
| Poção de Cura (básica, maior, superior, suprema) | Bônus | em si ou aliado da **mesma zona** | 2d4+2 / 4d4+4 / 8d4+8 / 10d4+20 PV, até o teto da exaustão; levanta quem está caído |
| Poção de Resistência a X | Bônus | em si | resistência a dano X até o fim do combate |
| Antitoxina / Antídoto | Bônus | em si | vantagem em salvaguardas contra Envenenado até o fim do combate |
| Frasco de Ácido | Ação | qualquer outro na zona ou na vizinha | salvaguarda de DES (CD 8 + DES + proficiência) ou 2d6 ácido |
| Fogo Alquímico | Ação | idem | idem, 1d4 fogo, e o alvo fica **Queimando** |
| Água Benta | Ação | idem, só mortos-vivos e infernais | idem, 2d8 radiante |

- O arremesso vale para aliados também (fogo amigo), e o dano passa pelas
  resistências e imunidades do alvo como qualquer outro.
- **Queimando**: 1d4 de fogo no início de cada turno de quem está em chamas
  (gancho `_inicio_de_turno`), seguido do teste de DES CD 10 para apagar.
  No livro o teste gasta a Ação da criatura; aqui ele é automático, porque a
  vez do inimigo corre sem escolha. Cair a 0 PV ou o combate acabar apaga.
- Os efeitos de 1 hora (resistência, antitoxina) tomados **em combate** ficam
  em `sheet["efeitos"]` e acabam com o combate, porque o combate não avança o
  relógio do mundo. Tomados fora dele, pela Mochila, duram 1 hora no relógio
  (ver [Usar fora do combate](#usar-fora-do-combate)). A resistência entra no cálculo de dano por `_traits_lookup`; a
  antitoxina aparece no card e na ficha do herói, e `apply_condition` lembra o
  mestre dela quando ele aplica Envenenado.
- **Item que o motor não conhece** (Poção de Força de Gigante, pergaminhos,
  óleos) continua na lista, **travado**, com o motivo ("descreva o uso em
  Ação Livre para o mestre resolver"). Chamado mesmo assim, o motor recusa com
  "Aviso:" e o item não é gasto.
- Alvo, alcance e "sem efeito" são validados **antes** de gastar a economia e
  a unidade: uma recusa não custa o turno nem o item. O snapshot traz, para
  cada item, quem ele alcança (`alvos`: ok, fora, sem_efeito), e a tela só
  trava o que o motor recusaria.
- Consome 1 unidade; remove do inventário quando qtd zera.

`test_itens_de_combate.py` (19) cobre as fichas, o item desconhecido, alcance
e teto da poção, arremessos (salvaguarda, dano, alcance, fogo amigo,
resistência, água benta, derrubar), Queimando e os efeitos em si.
`test_itens_de_combate_navegador.py` (4) confere na tela o item travado, a
poção só oferecendo a mesma zona, o ácido alcançando a zona vizinha e a água
benta "sem efeito". Capturas: `combate-itens`, `combate-pocao-alcance` e
`combate-agua-benta`.

### Defesas do inimigo como informação conquistada

Resistência, imunidade e vulnerabilidade apareciam no card desde o primeiro
round: o jogador abria a luta contra o zumbi já sabendo que ele resiste a
corte e queima com radiante, sem nada no jogo ter pago por isso.

Agora a ficha guarda o que o grupo já viu (`sheet["descobertas"]`, por campo)
e `_defesas_visiveis` filtra o snapshot: dos inimigos, só o descoberto; dos
personagens do grupo, tudo — a ficha é do jogador.

Descobre-se de duas formas:

- **Batendo.** `_apply_damage` anota o tipo quando o multiplicador aparece:
  zero vira imunidade, metade vira resistência, dobro vira vulnerabilidade, e
  o caso em que as duas se cancelam anota as duas. O texto da rolagem já dizia
  "Resistente a dano necrotic — dano pela metade": esconder no card depois
  disso seria mentira.
- **`reveal_defenses(char_name, damage_types)`.** O mestre chama depois de um
  teste de conhecimento bem-sucedido, quando alguém do grupo já enfrentou a
  criatura, ou quando a cena entrega a dica. Sem tipos, revela todas; com
  tipos, só os pedidos. Diz o que já era sabido e, quando não há defesa
  daquele tipo, devolve Nota pedindo que o mestre conte isso ao grupo —
  descobrir que não há fraqueza também é informação.

`test_defesas_descobertas.py` (14) e `test_defesas_descobertas_navegador.py`
(3) cobrem o card mudo no começo, cada tipo de golpe revelando a sua defesa e
só ela, o que fica anotado, o grupo continuando aberto, a ferramenta com e sem
tipos, e o selo aparecendo na tela com o marcador certo.

### Outros botões

- **Defender**, Esquivar (Dodge), Ação.
- **Fugir**, Ação + encerra turno (sai do combate, status "fugiu").
- **Ação Livre**, no próprio painel: um campo de texto embaixo dos botões, o
  pedido vai ao mestre e a arbitragem volta ali mesmo, formatada, sem fechar
  a tela. Enter envia, Shift+Enter quebra linha, Esc fecha; o painel divide o
  espaço com o seletor de alvo, então abrir um fecha o outro. Antes o botão
  fechava o overlay e devolvia o foco ao chat: para pedir a manobra que o
  motor não tem botão — empurrar a mesa, cortar a corda do lustre —, o
  jogador perdia o campo de batalha de vista.
  O pedido e a resposta continuam indo para o chat (`appendUser` e
  `appendMaster`), que é onde a crônica mora; `sendToAgent` ganhou um
  parâmetro `aoTexto` para entregar a fala também a quem pediu. Terminada a
  arbitragem, a tela é relida do motor, porque o mestre pode ter aplicado
  dano, condição ou mudança de zona.
  `test_combate_acao_livre_navegador.py` (6) cobre o pedido e a resposta com
  a tela aberta, Enter e Esc, o pedido vazio, o seletor de alvo fechando o
  painel, a releitura do motor e o caminho inteiro pelo SSE de verdade.
- **Encerrar Turno**, força avanço sem gastar slot.

O título "O que fará Stelar?" fica grudado no topo do painel de ação, também
no desktop. Abrir o seletor de arma, alvo ou item faz o painel rolar por
dentro, e o título saía de vista cortado ao meio; agora os selos e botões
passam por baixo dele, com uma sombra que só aparece com o painel rolado.

### Fechar a tela durante o combate

O botão **✕** no cabeçalho fecha a tela **sem encerrar o combate**: o
jogador pode acessar o menu e sair do jogo no meio da luta. O combate fica
pausado e o `combat_state` é persistido; ao voltar, retoma de onde parou.
Uma pílula flutuante **"Retomar combate"** reabre a tela. A flag
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

- **Vitória!** / **Derrota…**
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
[R1] Valerius → Goblin 4 (Espada Longa): d20=20 +3+2 = 25 vs CA 5 ...
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

#### O recap não é fala do jogador

O recap vai ao mestre pelo mesmo `/api/chat` do jogador, com `registrar` ligado
(a narração precisa entrar no histórico e o turno precisa contar). Por isso
ele era gravado no histórico como mensagem do jogador, e ao reabrir a campanha
o chat mostrava o log inteiro, instruções ao mestre incluídas. O mesmo valia
para o fechamento das outras telas (loja, descanso, nível, Grimório), para a
rolagem de dado e para os pedidos que /local, /personagem e /evento mandam.

Agora essas mensagens vão marcadas: `sendToAgent(texto, true, interno)`, com
`interno` sendo `tela`, `dado` ou `comando`. O servidor grava a marca na
entrada do histórico e continua guardando o texto, que o mestre usa como
contexto. No resumo de retomada (`_build_recap`) elas entram só como registro
(`_linha_do_recap`): "[Sistema]: [COMBATE RESOLVIDO NA TELA TÁTICA] Desfecho:
VITÓRIA. (já resolvido e narrado)", sem o corpo. Com o corpo inteiro, o
mestre relia "conceda XP a cada membro do grupo com grant_xp()" ao retomar e
dava o XP do mesmo monstro de novo. O resumo também diz que as linhas
`[Sistema]` já foram resolvidas e que XP, saque, itens e moedas não devem ser
concedidos de novo por causa delas. As campanhas gravadas antes da marca são
reconhecidas pelo prefixo (`_tipo_de_mensagem_interna`), e as rotas que
entregam o histórico passam por `_historico_para_a_tela`. Ao reabrir,
`renderHistory` não desenha fechamento de tela nem pedido de comando, e a
rolagem volta como uma linha curta ("Sua rolagem: 1d20: rolei 14, total 14").

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

### Quando uma chamada de ferramenta falha (`rpg/erros_de_ferramenta.py`)

Numa campanha nova o turno inteiro caía com "O RPG AGENT silenciou" em dois
casos: a LLM chamou uma ferramenta que não existe (`modify_amount`) e uma
ferramenta levantou exceção por dentro (`'NoneType' object has no attribute
'get'`). O ADK trata os dois como fatais e desiste do turno, deixando sem
narração o que o mestre já tinha feito.

O `Agent` agora tem `on_tool_error_callback`, e a falha vira o **resultado**
da chamada, que o mestre lê como leria uma recusa do motor:

- **Nome inventado:** `Erro: a ferramenta modify_amount não existe. Talvez
  você queira: modify_mana, modify_currency, modify_hp.`
- **Ferramenta que saiu do conjunto:** `attack_roll` no combate da tela diz
  para esperar o `[COMBATE RESOLVIDO NA TELA TÁTICA]`; ferramenta de D&D numa
  campanha sem regras diz para resolver pela narração.
- **Exceção dentro da ferramenta:** `Erro: X falhou por um problema interno
  (TipoDoErro: ...)`, com a orientação de não repetir a chamada e conferir o
  estado. O traceback completo vai para o log do servidor.

A causa do `NoneType` era um NPC salvo só com `save_character`, que fica com
`"sheet": None`: `recruit_character` e `add_item` faziam
`char.get("sheet", {}).get(...)`, e o `{}` padrão não vale quando a chave
existe com `None`. Esses pontos passaram a usar `or {}`. Campos gravados como
`null` numa ficha (inventário, habilidades, equipamentos, condições, recargas)
quebravam outras 14 ferramentas e agora viram o padrão na carga da campanha e
quando um editor grava o personagem.

`test_varredura_de_ferramentas.py` chama **todas** as ferramentas em sete
estados de campanha nova (NPC sem ficha, membro do grupo sem ficha, personagem
inexistente, campos `null`, com e sem combate), refazendo a campanha antes de
cada chamada, e exige que nenhuma levante exceção. Refazer importa:
`roll_initiative` dá ficha padrão a quem não tem e escondia a quebra do
`recruit_character` que viesse depois. `test_erros_de_ferramenta.py` roda um
turno de verdade pelo `Runner` do ADK com um modelo de mentira que chama
`modify_amount` e depois uma ferramenta que levanta, e confere que o turno
termina.

### Contador de cache de prompt

`/api/chat` passou a expor `cached_tokens`, `cache_hit_ratio` e
`thoughts_tokens` junto do `quota_update`, e o log de debug mostra a fração
do prompt servida do cache:

```
[TOKENS] prompt=14320 resposta=812 total=15132 | cache=11020 (77% do prompt)
```

É o número que diz se aqueles ~11 mil tokens de schema estão custando integral
ou uma fração — e portanto se vale a pena mexer em mais alguma coisa. Com
`cache=0` o aviso é explícito.

### Narrativas (`rpg/tools.py`)

| Função | Função no jogo |
|---|---|
| `save_character` | Cria/atualiza NPC ou personagem do grupo (com `local` opcional) |
| `set_character_location` | Onde um NPC está agora (aparece na ficha do local) |
| `add_character_knowledge` | O que o grupo descobriu sobre alguém (aparece na ficha do personagem) |
| `get_character` / `list_characters` | Lê personagem(ns) |
| `update_character_status` | Muda status (vivo, ferido, morto, aliado…) |
| `add_party_member` / `remove_party_member` / `list_party` | Gerencia o grupo |
| `save_location` / `get_location` / `list_locations` | Locais (com `dentro_de` opcional) |
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
| `short_rest` / `use_hit_die` / `long_rest` | Descansos (a reserva de dados de vida é uma só) |
| `offer_rest` | Abre a tela de descanso para o jogador |
| `offer_loot` | Põe o saque no chão e abre a tela de saque para o jogador dividir |
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
- `GET /api/locations/state?local=` → ficha do local (caminho, alcance, o que
  fica dentro, quem está lá). O `PUT` de local aceita `dentro_de` (e recusa
  ciclo); o de personagem aceita `local`. Veja [Ficha do local](#ficha-do-local).
- `GET /api/characters/sheet?nome=` → ficha do personagem (onde está, atitude e
  histórico, o que o grupo sabe, missões, eventos, loja). O `PUT` de personagem
  aceita `conhecido`. Veja [Ficha do personagem](#ficha-do-personagem).
- `GET /api/heroes/sheet?personagem=` → ficha de leitura de um membro do grupo
  (bônus de salvaguarda, perícia e ataque calculados pelo motor). Veja
  [Ficha do herói](#ficha-do-herói).
- O `PUT` de personagem (e o `PUT /api/campaigns/<name>`) passa por
  `normalize_edited_character`; aceita `correcao_manual` e devolve `mantidos`.
  Veja [Wizard e editores de ficha](#wizard-e-editores-de-ficha).

### Diário

- `POST /api/diary/export`, devolve um `.md`.

### D&D auxiliares

- `GET /api/dnd/regras`, tabelas de regra geradas pelo motor (limites de
  magia, círculo máximo, incrementos, mana, XP, proficiência, dado de vida),
  lidas pelo wizard e pelos editores.
- `GET /api/dnd/class-spells?classe=mago&level=3`, magias do SRD.
- `GET /api/dnd/items/search?q=...`, busca item.
- `GET /api/dnd/monsters/search?q=...`, busca monstro.
- `GET /api/dnd/class-features?classe=guerreiro&nivel=5`, features.
- `GET /api/dnd/feature_variants`, catálogo de subescolhas (variantes/arquétipos).
- `POST /api/dnd/feature_choice`, aplica/remove uma subescolha de habilidade.

### Combate em tela

- `GET /api/combat/state` → snapshot completo (inclui `alcance` por arma e
  alvo quando o combate tem zonas).
- `POST /api/combat/action` `{action, actor, target, weapon, ability, item}`
  → executa intenção, retorna `{ok, message, snapshot}`.
- `GET /api/combat/recap` → texto para a IA narrar a luta + limpa
  `result`.
- `GET/POST /api/combat/mode` → lê/grava `combat_mode`.

### Telas de nível, loja e descanso

Todas devolvem `{ok, message, snapshot}` na ação, e a ação só despacha para as
ferramentas do mestre.

- `GET /api/levelup/state?personagem=` / `POST /api/levelup/action`
  `{action: variante|asi|asi_lote|talento|subir, char, feature, choice, points, distribution}`.
- `GET /api/shop/state?loja=&comprador=` / `POST /api/shop/action`
  `{action: buy|sell, shop, char, item, quantity}` /
  `GET /api/shop/recap?desde=&loja=` → `{text}` com o que foi negociado na visita.
- `GET /api/rest/state` / `POST /api/rest/action`
  `{action: dado|concluir|cancelar, char}`.
- `GET /api/characters/index` → todos os personagens com a categoria, se estão
  aqui e a contagem por filtro. Veja [Índice de personagens](#índice-de-personagens).
- `GET /api/diary/book` → o diário por capítulo, com eventos, personagens,
  locais e missões / `POST /api/diary/move-event` `{index, chapter}`. Veja
  [O diário como livro](#o-diário-como-livro).
- `GET /api/party/overview` → os heróis lado a lado com o resumo de descanso e
  carga. Veja [Visão geral do grupo](#visão-geral-do-grupo).
- `GET /api/map/state` → a árvore de lugares, onde o grupo está, o que está a
  um passo e quem está onde. Veja [Mapa do mundo](#mapa-do-mundo).
- `GET /api/quests/state` / `POST /api/quests/action`
  `{action: marcar|desmarcar|abandonar|fechar, quest, objective}`; `fechar`
  devolve `recap`. Veja [Tela de missões](#tela-de-missões-o-livro-de-missões).
- `GET /api/loot/state` / `POST /api/loot/action`
  `{action: dar|devolver|moedas|concluir|deixar, item, char, quantity, coins_to}`.
  Veja [Tela de saque](#tela-de-saque-o-espólio).
- `GET /api/inventory/state?personagem=` / `POST /api/inventory/action`
  `{action: equipar|desequipar|largar|identificar|usar, char, item, slot, alvo}`.
- `GET /api/grimoire/state?personagem=&q=&nivel=&resumo=1` /
  `POST /api/grimoire/action` `{action: aprender, char, spell, q, spell_level}`.

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
- **`static/game.html`**, chat principal + barra lateral (relance e atalhos,
  `barra.js`) + dice tray + tela de combate (`combat.js`).
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
- **`levelup.js`**, **`grimoire.js`**, **`inventory.js`**, **`shop.js`** e
  **`rest.js`**, as telas de nível, magias, equipamento, loja e descanso.
- **`locais.js`**, a ficha do local (o que fica dentro, quem está lá, "Ir até
  lá" e "Falar com").
- **`personagens.js`**, a ficha do personagem (relação com o grupo e o porquê,
  o que o grupo sabe, ligações, "Falar com" e "Ir até onde está").
- **`herois.js`**, a ficha de leitura do herói (atributos, salvaguardas,
  perícias, ataques, estado e os atalhos para as telas que mudam a ficha).
- **`loot.js`**, a tela de saque (quem leva o quê, com a carga prevista).
- **`missoes.js`**, o livro de missões (abas por situação, objetivos marcáveis,
  quem deu e desfecho).
- **`barra.js`**, a barra lateral do jogo (relance, atalhos com contador,
  avisos, recolher, faixa e barra de baixo no celular, e a seção "Esta
  campanha" da engrenagem).
- **`elenco.js`**, o índice de personagens (busca, filtros e a ficha de cada
  um).
- **`diario.js`**, o diário como livro (capítulos, entradas em texto
  corrido, eventos, personagens, locais e missões ligados).
- **`grupo.js`**, a visão geral do grupo (heróis lado a lado, resumo de
  descanso e carga, pedir descanso).
- **`mapa.js`**, o mapa do mundo (árvore de lugares, quem está onde, o que está
  a um passo e busca).
  Mesma regra: renderizam o snapshot do motor e despacham intenções. A fila
  que decide qual abre primeiro (combate, nível, grimório, saque, descanso,
  loja; a Mochila, as fichas, as missões, o mapa, a visão geral do grupo, o diário e o índice de personagens só abrem pelo clique) e o empilhamento das
  pílulas ficam em `game.js`.

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

**Sem emoji.** O projeto não usa emoji em lugar nenhum: interface, mensagens
do motor, instrução da IA, logs do servidor e esta documentação. Emoji muda de
desenho em cada sistema operacional, some em fontes sem suporte e dá à tela um
ar de chat, não de livro. Onde havia um, hoje há:

- **texto**, nos rótulos de botão, abas, títulos e pílulas ("Retomar
  combate", "Loja: Forja do Torbin", "Subir de nível");
- **SVG em linha**, onde o ícone é o elemento inteiro (botão de dado,
  ilustrações do login) — herda a cor do tema via `currentColor`;
- **CSS**, nos indicadores (ponto de vida do `/status`, caixa de objetivo de
  missão).

O emoji também era **sinal**: o servidor e as telas decidiam sucesso ou recusa
pelo primeiro caractere da mensagem da ferramenta. O contrato agora é em texto
— a ferramenta que recusa começa com **`Erro:`** ou **`Aviso:`**, e **`Nota:`**
indica que nada mudou (a magia já era conhecida, a opção já estava marcada).
Personagem inexistente, que antes voltava sem prefixo nenhum e passava por
sucesso nas telas, também é `Erro:`. O front reconhece linhas de rolagem pela
notação (`d20=`, `2d6:`), não por um ícone de dado. `tests/test_sem_emoji.py`
varre todos os arquivos versionados e falha se um emoji voltar; ficam
permitidos só sinais tipográficos (✕ ✓ ★ ☰ e setas simples).

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

A seção **"Instalar como aplicativo"** no guia de ajuda ("Como Jogar",
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

Os avisos aparecem no relance da barra lateral, num botão discreto que só existe quando há algum.

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
│   ├── locais.py          Hierarquia de locais, paradeiro e ficha do local
│   ├── personagens.py     Ficha do personagem: relação, o que o grupo sabe, ligações
│   ├── saque.py           Tela de saque: offer_loot, divisão e carga prevista
│   ├── missoes.py         Tela de missões: snapshot, marcar, abandonar, aviso ao mestre
│   ├── mapa.py            Mapa do mundo: árvore de lugares, alcance e paradeiro
│   ├── grupo.py           Visão geral do grupo: descanso, carga e nível lado a lado
│   ├── diario.py          O diário como livro: capítulos com eventos, personagens e missões
│   ├── tools_dnd.py       Motor D&D 5e + combate (~7900 linhas, 38 tools)
│   ├── memory.py          Estado por sessão, proxy, persistência
│   ├── database.py        Camada Supabase
│   ├── auth.py            Supabase Auth + @require_auth
│   ├── session.py         Runner ADK
│   ├── validator.py       Validador narrativo pós-resposta
│   ├── open5e.py          Acesso ao SRD: sessão, retry, cache, offline
│   ├── toolsets.py        Conjunto de ferramentas resolvido por turno
│   └── erros_de_ferramenta.py  Falha de ferramenta vira "Erro:" em vez de derrubar o turno
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
│   ├── test_varredura_de_ferramentas.py  Nenhuma ferramenta levanta exceção
│   ├── test_kit_inicial.py      Ficha criada pelo mestre vem com o kit da classe
│   ├── test_combate_repetido.py A mesma emboscada não reinicia a luta
│   ├── test_atributo_da_arma.py Acuidade e distância em português e em inglês
│   ├── test_erros_de_ferramenta.py       Turno segue após ferramenta inventada ou quebrada
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
