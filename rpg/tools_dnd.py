"""
tools_dnd.py
Ferramentas do motor de regras D&D para o modo de jogo estruturado.

Todas as funções aqui seguem a lógica de D&D 5e simplificado com um
sistema de mana em lugar de slots de magia (mais amigável para videogame).

Novidades (v2):
  • Vantagem / Desvantagem em attack_roll e make_skill_check
  • Saving Throws em use_ability (dano pela metade se passar)
  • equip_item / unequip_item com recálculo dinâmico de CA
  • apply_condition / remove_condition com efeitos mecânicos automáticos
  • Campos separados de moedas (ouro / prata / cobre) + modify_currency
  • roll_death_save estruturado
"""

import copy
import functools
import os
import random
import re
from rpg import memory

# ---------------------------------------------------------------------------
# Debug do motor de regras (para demonstração ao vivo).
# Mostra no terminal quando o motor consulta a base externa Open5e (grounding):
# em vez de "alucinar" stats, o agente busca dados reais de D&D 5e via HTTP.
# DESLIGADO por padrão. Para ver o debug ao vivo, rode com RPG_DEBUG=1
# (ex.: RPG_DEBUG=1 python server.py). Aceita: 1/true/yes/on.
# ---------------------------------------------------------------------------

DEBUG_ENGINE = os.environ.get("RPG_DEBUG", "0").strip().lower() in ("1", "true", "yes", "on")


def _edbg(msg: str = "") -> None:
    """Imprime uma linha de debug do motor de regras se RPG_DEBUG estiver ligado."""
    if DEBUG_ENGINE:
        print(msg, flush=True)


# ---------------------------------------------------------------------------
# Mapeamento de nomes de magias/habilidades PT-BR → EN (para tolerar o AI
# chamando use_ability com nomes traduzidos em vez do nome armazenado)
# ---------------------------------------------------------------------------
_SPELL_PT_TO_EN: dict[str, str] = {
    # Cantrips
    "prestidigitação": "prestidigitation",
    "luz": "light",
    "raio de gelo": "ray of frost",
    "raio de frio": "ray of frost",
    "choque do trovão": "thunderclap",
    "choque elétrico": "shocking grasp",
    "toque gélido": "chill touch",
    "explosão eldrica": "eldritch blast",
    "chama sagrada": "sacred flame",
    "orientação": "guidance",
    "resistência": "resistance",
    "palavra de cura": "spare the dying",
    "produzir chama": "produce flame",
    "druidcraft": "druidcraft",
    "veneno aspergido": "poison spray",
    "amigos": "friends",
    "mensagem": "message",
    "ilusão menor": "minor illusion",
    "mão de mago": "mage hand",
    "dança das luzes": "dancing lights",
    "truque": "thaumaturgy",
    # Nível 1
    "míssil mágico": "magic missile",
    "missil magico": "magic missile",
    "mãos flamejantes": "burning hands",
    "maos flamejantes": "burning hands",
    "sono": "sleep",
    "escudo": "shield",
    "armadura de mago": "mage armor",
    "identificar": "identify",
    "graxa": "grease",
    "cor em spray": "color spray",
    "encantamento": "charm person",
    "enfeitiçar pessoa": "charm person",
    "emaranhar": "entangle",
    "criar ou destruir água": "create or destroy water",
    "cura de ferimentos": "cure wounds",
    "detectar magia": "detect magic",
    "disfarçar-se": "disguise self",
    "falar com animais": "speak with animals",
    "guia espiritual": "guiding bolt",
    "raio guia": "guiding bolt",
    "cura": "healing word",
    "palavra curativa": "healing word",
    "inflict wounds": "inflict wounds",
    "infligir ferimentos": "inflict wounds",
    "saltar": "jump",
    "longa passada": "longstrider",
    "proteção contra o mal e o bem": "protection from evil and good",
    "punição vingativa": "wrathful smite",
    "onda trovejante": "thunderwave",
    "mergulho de bruxa": "witch bolt",
    "raio de bruxa": "witch bolt",
    # Nível 2
    "invisibilidade": "invisibility",
    "sugestão": "suggestion",
    "web": "web",
    "teia": "web",
    "porta dimensional": "misty step",
    "passo nebuloso": "misty step",
    "trevas": "darkness",
    "bola de fogo": "fireball",
    "relâmpago": "lightning bolt",
    "raio de enfraquecimento": "ray of enfeeblement",
    "segurar pessoa": "hold person",
    "levitação": "levitate",
    "imagem espelhada": "mirror image",
    "nuvem de adormecimento": "sleep",
    "blindagem": "blur",
    "flecha ácida de melf": "melf's acid arrow",
    "toque de aranha": "spider climb",
    "escuridão": "darkness",
    # Nível 3
    "contrafeitiço": "counterspell",
    "dissipar magia": "dispel magic",
    "voo": "fly",
    "bola de fogo": "fireball",
    "raio relampejante": "lightning bolt",
    "pressa": "haste",
    "lentidão": "slow",
    "hipnose": "hypnotic pattern",
    "padrão hipnótico": "hypnotic pattern",
    "animar mortos": "animate dead",
    # Nível 4+
    "banimento": "banishment",
    "muralha de fogo": "wall of fire",
    "polimorfismo": "polymorph",
    "mudar forma": "polymorph",
    "porta dimensional": "dimension door",
    "teleporte": "teleport",
    "desejo": "wish",
    # Habilidades de classe comuns
    "recuperação arcana": "recuperação arcana",
    "tradição arcana": "tradição arcana",
    "segundo fôlego": "second wind",
    "surto de ação": "action surge",
    "esquiva astuta": "cunning action",
    "ataque furtivo": "sneak attack",
    "cura das mãos": "lay on hands",
    "sentido divino": "divine sense",
    "combate com duas armas": "two-weapon fighting",
    "fúria": "rage",
}


# ---------------------------------------------------------------------------
# Helpers de controle de turno
# ---------------------------------------------------------------------------

# Status que ENCERRAM a participação no combate — o combatente está
# definitivamente fora (morto, caído a 0 HP, fugiu). Usado para decidir
# QUANDO O COMBATE ACABA e para classificar caídos × sobreviventes.
DEFEATED_STATUSES = {
    "morto", "inconsciente", "estabilizado", "fugiu", "exilado",
    # Largou as armas (Pedir rendição): fora da luta, vivo, não é saque.
    "rendido",
}
# Status que fazem o combatente PULAR A VEZ na ordem de turno. Inclui
# "dormindo" (Sleep): a criatura está incapacitada (não age), mas continua
# VIVA e no combate — por isso "dormindo" NÃO entra em DEFEATED_STATUSES
# (dormir um inimigo não encerra a luta; é preciso derrotá-lo de fato).
OUT_OF_COMBAT_STATUSES = DEFEATED_STATUSES | {"dormindo"}

_MAX_COMBAT_LOG = 300


def _log_combat_event(etype: str, actor: str = "", target: str = "",
                      msg: str = "", **extra) -> None:
    """
    Acrescenta um evento estruturado ao log do combate.
    Usado pela tela tática (feed) e pela narração final da LLM.
    Falha de forma silenciosa fora de combate — nunca quebra uma ação.
    """
    cs = memory.campaign.get("combat_state")
    if not isinstance(cs, dict):
        return
    log = cs.setdefault("log", [])
    ev = {
        "round":  cs.get("round", 1),
        "type":   etype,
        "actor":  actor,
        "target": target,
        "msg":    msg,
    }
    if extra:
        ev.update(extra)
    log.append(ev)
    if len(log) > _MAX_COMBAT_LOG:
        del log[:-_MAX_COMBAT_LOG]


def _mark_at_zero_hp(target: dict, source_name: str = "", nocaute: bool = False) -> str:
    """
    Resolve um alvo que chegou a 0 HP aplicando a regra de D&D 5e:
      • Jogador / aliado do grupo → cai INCONSCIENTE (depois faz testes de morte).
      • Monstro / NPC comum        → MORRE na hora (sem teste de morte).
      • Nocaute (golpe corpo a corpo não letal) → cai inconsciente e ESTÁVEL,
        qualquer um; o NPC acorda com 1 PV depois de 1d4 horas do relógio.
    Define o status, registra o evento de combate e devolve o sufixo de texto
    a ser anexado ao resultado da ferramenta.
    """
    name = target.get("name", "")
    from rpg import manobras as _manobras
    _manobras.soltar_quem_agarrou(name)
    _queda = ""
    if _manobras.cavaleiro_de(target):
        _queda = " " + _manobras.queda_da_montaria(target, "a montaria caiu")
    elif _manobras.montaria_de(target):
        _manobras.desmontar(name, "caiu da sela")
    if nocaute:
        target["status"] = "estabilizado"
        s_n = target.setdefault("sheet", {})
        s_n["death_saves_sucessos"] = s_n["death_saves_falhas"] = 0
        if not memory.is_party_member(target):
            s_n["acorda_hora"] = _agora_em_horas() + random.randint(1, 4)
        _log_combat_event("down", source_name, name, msg=f"{name} foi nocauteado (estável)")
        return " NOCAUTEADO! (estável — não morre)" + _queda
    if memory.is_party_member(target):
        target["status"] = "inconsciente"
        _log_combat_event("down", source_name, name, msg=f"{name} caiu inconsciente")
        return " CAIU INCONSCIENTE!" + _queda
    target["status"] = "morto"
    (target.get("sheet") or {})["morreu_hora"] = _agora_em_horas()
    _log_combat_event("down", source_name, name, msg=f"{name} foi derrotado")
    return " DERROTADO!" + _queda


def poupado(ch: dict | None) -> str:
    """
    O inimigo que está fora da luta sem ter caído: "rendido", ou
    "enfeitiçado"/"dominado" por alguém do lado do grupo. '' quando não.
    Só eles sobrando, a luta acaba — ninguém é obrigado a matar quem já não
    luta contra o grupo.
    """
    if not ch or memory.luta_com_o_grupo(ch):
        return ""
    if (ch.get("status") or "").lower() == "rendido":
        return "rendido"
    if (ch.get("status") or "").lower() in DEFEATED_STATUSES:
        return ""
    from rpg import encantos
    e = encantos.ativo(ch)
    if not e:
        return ""
    por = memory.campaign.get("characters", {}).get(memory.char_key(e.get("por_nome", "")))
    if por and memory.luta_com_o_grupo(por):
        return "dominado" if e.get("tipo") == "dominado" else "enfeitiçado"
    return ""


def _is_out_of_combat(name: str) -> bool:
    ch = memory.campaign["characters"].get(memory.char_key(name))
    return (ch.get("status", "") if ch else "").lower() in OUT_OF_COMBAT_STATUSES


def _wake_sleeper(char: dict) -> None:
    """
    Acorda uma criatura que está DORMINDO (efeito de Sleep): restaura o
    status para vivo/inimigo e remove a condição 'Dormindo'. Idempotente —
    não faz nada se a criatura não estiver dormindo.
    """
    if not isinstance(char, dict):
        return
    if (char.get("status", "") or "").lower() == "dormindo":
        char["status"] = "vivo" if memory.is_party_member(char) else "inimigo"
    sh = char.get("sheet") or {}
    conds = sh.get("condicoes")
    if isinstance(conds, list):
        sh["condicoes"] = [
            c for c in conds
            if not (isinstance(c, dict)
                    and (c.get("nome", "") or "").lower() == "dormindo")
        ]


def _normalize_for_new_combat(char: dict) -> None:
    """
    Sanitiza estados transitórios herdados ao INICIAR uma luta nova:
    ninguém entra dormindo, e quem está com HP > 0 não pode estar
    inconsciente/estabilizado. Remove as condições incapacitantes
    transitórias (Dormindo / Inconsciente) que jamais devem vazar entre
    combates. Não mexe em personagens genuinamente mortos.
    """
    if not isinstance(char, dict):
        return
    sh = char.get("sheet") or {}
    st = (char.get("status", "") or "").lower()
    hp = int(sh.get("vida_atual", 0) or 0)
    if st == "dormindo" or (hp > 0 and st in ("inconsciente", "estabilizado")):
        char["status"] = "vivo" if memory.is_party_member(char) else "inimigo"
    # A Reação é marcada pelo NÚMERO da rodada. Quem reagiu na rodada 1 da
    # luta anterior entrava na rodada 1 da seguinte já sem Reação.
    sh.pop("reacao_rodada", None)
    conds = sh.get("condicoes")
    if isinstance(conds, list):
        sh["condicoes"] = [
            c for c in conds
            if not (isinstance(c, dict)
                    and (c.get("nome", "") or "").lower() in ("dormindo", "inconsciente"))
        ]


# ===========================================================================
# DURAÇÃO DAS CONDIÇÕES
# ---------------------------------------------------------------------------
# apply_condition(..., duration_turns=2) gravava {"duracao": 2} e nada no
# motor contava: "Envenenado (2 turnos)" ficava para sempre no card, na ficha
# e na régua, até o mestre lembrar de remover.
#
# A duração é em TURNOS DO PRÓPRIO AFETADO e desconta no FIM de cada turno
# dele. Condição aplicada durante o turno do próprio afetado não conta aquele
# turno (marca `token_aplicacao`): "Envenenado por 1 turno" dura sempre um
# turno inteiro dele, seja aplicada na vez dele ou na de outro.
#
# Quem está fora de combate (inconsciente, dormindo) não tem turno, então não
# desconta. As condições com duração acabam com o combate; as indefinidas
# (duracao None) só saem com remove_condition ou pela regra própria delas.
# ===========================================================================

def _turnos_restantes(cond) -> int:
    if not isinstance(cond, dict):
        return 0
    try:
        return max(0, int(cond.get("duracao") or 0))
    except (TypeError, ValueError):
        return 0


def _fim_do_turno(nome: str, token: int) -> list[str]:
    """
    Desconta um turno das condições de `nome`, cujo turno (marcado por
    `token`) acabou de terminar. Devolve as linhas do que acabou.
    """
    ch = memory.campaign.get("characters", {}).get(memory.char_key(nome or ""))
    if not ch:
        return []
    # Efeitos que duram "até o fim do próximo turno" de quem os sofre
    # (Zombaria Viciosa) acabam aqui; e as condições presas ao turno de
    # alguém (o Atordoado do Ataque Atordoante dura até o fim do próximo
    # turno do monge).
    _expirar_efeitos(memory.char_key(nome or ""), "fim", token)
    _acabou_com_o_turno = [f"{x} acabou" for x in
                           _expirar_efeitos(memory.char_key(nome or ""), "fim", token, "condicoes")]
    # Piscar: d20 no fim do turno; 11+ e ele some para o Plano Etéreo até o
    # início do próximo turno dele.
    if any(e.get("piscar") for e in _efeitos_de(ch)):
        _d20_p = random.randint(1, 20)
        if _d20_p >= 11:
            ch.setdefault("sheet", {}).setdefault("condicoes", []).append(
                {"nome": "Etéreo", "duracao": None, "ate_turno_de": memory.char_key(nome or "")})
            _acabou_com_o_turno.append(f"{ch.get('name', nome)} pisca (d20={_d20_p}) e some para o Plano Etéreo")
        else:
            _acabou_com_o_turno.append(f"{ch.get('name', nome)} não pisca desta vez (d20={_d20_p})")
    s = ch.get("sheet") or {}
    _limpar_condicoes(ch)
    conds = s.get("condicoes")
    if not isinstance(conds, list) or not conds:
        return _acabou_com_o_turno
    # Imobilizar Pessoa, Confusão, Medo: o alvo repete a salvaguarda no fim
    # do turno dele e se livra ao passar.
    livres = list(_acabou_com_o_turno)
    for c in list(conds):
        sv = c.get("salvaguarda_fim") if isinstance(c, dict) else None
        if not sv:
            continue
        passou, linha_sv = _rolar_salvaguarda(ch, sv.get("atributo", "sabedoria"), int(sv.get("cd", 10)))
        if passou:
            conds.remove(c)
            msg = f"{ch.get('name', nome)} se livra de {c.get('nome', 'condição')} ({linha_sv})"
            _log_combat_event("condition_end", "", ch.get("name", nome), msg=msg, condicao=c.get("nome", ""))
            livres.append(msg)
    if not conds:
        return livres
    ficam, acabaram = [], []
    for c in conds:
        if _turnos_restantes(c) <= 0:
            ficam.append(c)
            continue
        if c.get("token_aplicacao") == token:
            # Aplicada neste mesmo turno do afetado: não conta.
            c.pop("token_aplicacao", None)
            ficam.append(c)
            continue
        c.pop("token_aplicacao", None)
        c["duracao"] = _turnos_restantes(c) - 1
        if c["duracao"] <= 0:
            acabaram.append(c.get("nome", "condição"))
        else:
            ficam.append(c)
    if not acabaram:
        return livres
    s["condicoes"] = ficam
    linhas = list(livres)
    for cond in acabaram:
        linha = f"{cond} de {ch.get('name', nome)} acabou"
        _log_combat_event("condition_end", "", ch.get("name", nome), msg=linha, condicao=cond)
        linhas.append(linha)
    return linhas


def _heal_current_turn() -> None:
    """
    AUTO-CURA do ponteiro de turno: se o combatente do turno atual estiver
    fora de combate (morto/inconsciente/fugiu/etc.), avança para o próximo
    combatente válido — incrementando rodada no wrap e o token. Encerra o
    combate se ninguém restar. Idempotente se o atual já for válido.

    Chamada no INÍCIO de toda tool de turno → nenhuma ferramenta opera
    com o ponteiro preso num combatente fora de combate.
    """
    cs = memory.campaign.get("combat_state")
    if not cs or not cs.get("is_active"):
        return
    order = cs.get("initiative_order", [])
    if not order:
        return

    idx = cs.get("current_turn_index", 0)
    if not isinstance(idx, int) or not (0 <= idx < len(order)):
        idx = 0
        cs["current_turn_index"] = 0

    if not _is_out_of_combat(order[idx]):
        return  # atual já é válido

    round_num = cs.get("round", 1)
    for _ in range(len(order) + 1):
        idx += 1
        if idx >= len(order):
            idx = 0
            round_num += 1
        if not _is_out_of_combat(order[idx]):
            cs["current_turn_index"] = idx
            cs["round"]              = round_num
            cs["turn_resolved"]      = False
            cs["turn_token"]         = cs.get("turn_token", 0) + 1
            _reset_turn_economy(cs)
            memory.save_campaign()
            return

    # Ninguém em combate — encerra
    cs["is_active"]          = False
    cs["initiative_order"]   = []
    cs["current_turn_index"] = 0
    cs["round"]              = 1
    memory.save_campaign()


def _mark_turn_resolved() -> None:
    """Marca o turno como mecanicamente resolvido."""
    cs = memory.campaign.get("combat_state")
    if cs and cs.get("is_active"):
        cs["turn_resolved"] = True


def _auto_advance_turn(actor_name: str = "") -> str:
    """
    Avança o turno e retorna o anúncio do próximo como string.
    Injetado no final de attack_roll(), use_ability() e roll_death_save().
    Pula automaticamente personagens mortos/inconscientes/fugidos.
    Marca turn_auto_advanced=True para que next_turn() não duplique o avanço.
    Retorna string vazia fora do combate.

    actor_name: quem REALMENTE agiu. O avanço é ancorado na posição do ator
      na ordem de iniciativa — não no ponteiro global. Isso impede que ações
      fora de ordem (jogador agindo na vez de um NPC) corrompam o ponteiro e
      inflem o número da rodada (ex.: pular de Rodada 3 para 5).
    """
    cs = memory.campaign.get("combat_state")
    if not cs or not cs.get("is_active"):
        return ""
    order = cs.get("initiative_order", [])
    if not order:
        return ""

    OUT_OF_COMBAT = OUT_OF_COMBAT_STATUSES   # inclui "dormindo" → pula a vez

    round_num     = cs.get("round", 1)
    initial_round = round_num

    # Âncora: posição de quem agiu (se estiver na ordem). Senão, o ponteiro atual.
    idx = cs.get("current_turn_index", 0)
    if actor_name:
        akey = memory.char_key(actor_name)
        for i, n in enumerate(order):
            if memory.char_key(n) == akey:
                idx = i
                break

    skipped = []
    # O turno de quem agiu termina aqui: as condições dele descontam um turno.
    fim_msgs = _fim_do_turno(order[idx], cs.get("turn_token", 0)) if 0 <= idx < len(order) else []
    # Quem já teve um turno (o Assassinato tem vantagem contra quem ainda não).
    if 0 <= idx < len(order):
        _ag = cs.setdefault("agiram", [])
        if memory.char_key(order[idx]) not in _ag:
            _ag.append(memory.char_key(order[idx]))

    for _ in range(len(order) + 1):
        idx += 1
        if idx >= len(order):
            idx        = 0
            round_num += 1

        current_name = order[idx]
        char         = memory.campaign["characters"].get(memory.char_key(current_name))
        status       = (char.get("status", "") if char else "").lower()

        if status in OUT_OF_COMBAT:
            skipped.append(f"{current_name} ({status})")
            continue

        cs["current_turn_index"] = idx
        cs["round"]              = round_num
        cs["turn_resolved"]      = False
        cs["turn_auto_advanced"] = True   # impede next_turn() de avançar de novo
        cs["turn_token"]         = cs.get("turn_token", 0) + 1  # avanço real
        _reset_turn_economy(cs)
        memory.save_campaign()

        skip_msg      = f"\n   Pulados: {', '.join(skipped)}" if skipped else ""
        new_round_msg = f"\n   Nova rodada! Rodada {round_num} começa." if round_num > initial_round else ""
        order_str     = " → ".join(f"[{n}]" if i == idx else n for i, n in enumerate(order))
        # O que acabou no fim do turno e o que aconteceu na virada (ações
        # lendárias, chamas). Antes só next_turn() mostrava a virada.
        virada = fim_msgs + list(cs.pop("_lendarias_msg", None) or [])
        virada_msg = "".join(f"\n   {m}" for m in virada)
        return (
            f"\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"TURNO AVANÇADO — Rodada {round_num}{new_round_msg}{skip_msg}{virada_msg}\n"
            f"Próxima vez: **{current_name}**\n"
            f"   Ordem: {order_str}"
        )

    # Todos fora de combate — encerra
    cs["is_active"]          = False
    cs["initiative_order"]   = []
    cs["current_turn_index"] = 0
    cs["round"]              = 1
    memory.save_campaign()
    return "\n\nTodos os personagens estão fora de combate. Combate encerrado automaticamente."


def _combat_current_actor() -> str:
    """Nome do combatente cujo turno é AGORA (string vazia se não houver)."""
    cs = memory.campaign.get("combat_state", {})
    if not cs.get("is_active"):
        return ""
    order = cs.get("initiative_order", [])
    if not order:
        return ""
    idx = cs.get("current_turn_index", 0)
    if not isinstance(idx, int) or not (0 <= idx < len(order)):
        return ""
    return order[idx]


def _combat_turn_violation(actor_name: str) -> str | None:
    """
    Retorna mensagem de erro se `actor_name` tentar agir FORA do seu turno,
    ou None se a ação é permitida.

    Regras (a tool é a AUTORIDADE — não confia no LLM seguir a ordem):
      • Fora de combate ativo → permitido (sem ordem a impor).
      • Ator não está na iniciativa → permitido (ex.: invocação não listada;
        não dá pra impor ordem a quem não está na lista).
      • Ator está na iniciativa mas NÃO é o atual → BLOQUEADO.
    """
    cs = memory.campaign.get("combat_state", {})
    if not cs.get("is_active"):
        return None
    order = cs.get("initiative_order", [])
    if not order:
        return None
    akey = memory.char_key(actor_name)
    if not any(memory.char_key(n) == akey for n in order):
        return None
    cur = _combat_current_actor()
    if not cur or memory.char_key(cur) == akey:
        return None
    return (
        f"Erro: FORA DE ORDEM: não é o turno de {actor_name}. "
        f"É a vez de **{cur}**.\n"
        f"   • Se {cur} é um NPC inimigo → chame execute_npc_turn().\n"
        f"   • Se o jogador tentou agir adiantado → diga 'ainda não é sua vez' "
        f"e resolva o turno de {cur} primeiro.\n"
        f"   Nenhum dado foi rolado e nada mudou."
    )


# ---------------------------------------------------------------------------
# Tabelas e constantes do sistema
# ---------------------------------------------------------------------------

XP_THRESHOLDS = [
    0,      # Nível 1
    300,    # Nível 2
    900,    # Nível 3
    2700,   # Nível 4
    6500,   # Nível 5
    14000,  # Nível 6
    23000,  # Nível 7
    34000,  # Nível 8
    48000,  # Nível 9
    64000,  # Nível 10
    85000,  # Nível 11
    100000, # Nível 12
    120000, # Nível 13
    140000, # Nível 14
    165000, # Nível 15
    195000, # Nível 16
    225000, # Nível 17
    265000, # Nível 18
    305000, # Nível 19
    355000, # Nível 20
]

CLASS_DATA: dict[str, dict] = {
    "bárbaro":     {"hit_die": 12, "mana_per_level": 0,  "mana_stat": None,          "saves": ["forca", "constituicao"]},
    "guerreiro":   {"hit_die": 10, "mana_per_level": 2,  "mana_stat": "forca",       "saves": ["forca", "constituicao"]},
    "paladino":    {"hit_die": 10, "mana_per_level": 5,  "mana_stat": "carisma",     "saves": ["sabedoria", "carisma"]},
    "patrulheiro": {"hit_die": 8,  "mana_per_level": 4,  "mana_stat": "sabedoria",   "saves": ["forca", "destreza"]},
    "bardo":       {"hit_die": 8,  "mana_per_level": 6,  "mana_stat": "carisma",     "saves": ["destreza", "carisma"]},
    "clérigo":     {"hit_die": 8,  "mana_per_level": 8,  "mana_stat": "sabedoria",   "saves": ["sabedoria", "carisma"]},
    "druida":      {"hit_die": 8,  "mana_per_level": 8,  "mana_stat": "sabedoria",   "saves": ["inteligencia", "sabedoria"]},
    "monge":       {"hit_die": 8,  "mana_per_level": 4,  "mana_stat": "sabedoria",   "saves": ["forca", "destreza"]},
    "ladino":      {"hit_die": 8,  "mana_per_level": 2,  "mana_stat": "destreza",    "saves": ["destreza", "inteligencia"]},
    "mago":        {"hit_die": 6,  "mana_per_level": 10, "mana_stat": "inteligencia","saves": ["inteligencia", "sabedoria"]},
    "feiticeiro":  {"hit_die": 6,  "mana_per_level": 10, "mana_stat": "carisma",     "saves": ["constituicao", "carisma"]},
    "bruxo":       {"hit_die": 8,  "mana_per_level": 8,  "mana_stat": "carisma",     "saves": ["sabedoria", "carisma"]},
    "arcanista":   {"hit_die": 6,  "mana_per_level": 12, "mana_stat": "inteligencia","saves": ["inteligencia", "sabedoria"]},
}

STAT_NAMES = {"forca", "destreza", "constituicao", "inteligencia", "sabedoria", "carisma"}
# ── Sistema de mana: variante oficial Spell Points do D&D 5e (DMG p.288) ────
# Custo de cada magia em Pontos de Magia (mana), por nível da magia.
# Truques (nível 0) são gratuitos. Substitui o antigo custo homebrew (nível×4).
SPELL_MANA_COST = {0: 0, 1: 2, 2: 3, 3: 5, 4: 6, 5: 7, 6: 9, 7: 10, 8: 11, 9: 13}

# Pool de mana por NÍVEL DE CONJURADOR — tabela oficial da variante Spell
# Points (DMG p.288). O pool depende SÓ do nível: todo conjurador de um dado
# nível tem o mesmo pool, independentemente do atributo de conjuração.
SPELL_POINTS_BY_LEVEL = {
    1: 4,    2: 6,    3: 14,   4: 17,   5: 27,
    6: 32,   7: 38,   8: 44,   9: 57,   10: 64,
    11: 73,  12: 73,  13: 83,  14: 83,  15: 94,
    16: 94,  17: 107, 18: 114, 19: 123, 20: 133,
}

# Fração de conjuração por classe → define o nível de conjurador efetivo.
# Chaves SEM acento — a comparação normaliza acentos (ver _max_mana_for).
_FULL_CASTERS  = {"mago", "feiticeiro", "clerigo", "druida", "bardo",
                  "bruxo", "arcanista"}
_HALF_CASTERS  = {"paladino", "patrulheiro"}             # metade do progresso
_THIRD_CASTERS = {"guerreiro", "ladino"}                 # Cav. Élditch / Trapaceiro Arcano


def _max_mana_for(classe: str, char_level: int) -> int:
    """
    Pool máximo de mana de um personagem pela tabela oficial de Pontos de
    Magia (DMG p.288). NÃO depende do atributo de conjuração, depende só do
    nível de conjurador efetivo:

      • Conjurador pleno  → nível de conjurador = nível do personagem.
      • Meio-conjurador   → ceil(nível / 2); nada antes do nível 2.
      • Terço-conjurador  → ceil(nível / 3); nada antes do nível 3.
      • Monge             → Ki = 1 ponto por nível (regra real do monge).
      • Bárbaro / demais  → 0.
    """
    c   = _norm_txt(classe)   # minúsculas, sem acento (clérigo → clerigo)
    lvl = max(1, min(20, int(char_level or 1)))
    if c in _FULL_CASTERS:
        cl = lvl
    elif c in _HALF_CASTERS:
        cl = (lvl + 1) // 2 if lvl >= 2 else 0          # ceil(lvl/2)
    elif c in _THIRD_CASTERS:
        cl = (lvl + 2) // 3 if lvl >= 3 else 0          # ceil(lvl/3)
    elif c == "monge":
        return lvl                                       # pool de Ki = nível
    else:
        return 0                                         # bárbaro / não-conjuradores
    return SPELL_POINTS_BY_LEVEL.get(cl, 0)

# ── Tradução PT → EN para busca no Open5e ───────────────────────────────────
# ── Níveis reais de magias comuns para validar/corrigir respostas da API ────
# Evita que a busca fuzzy do Open5e retorne nível errado
SPELL_LEVEL_OVERRIDE: dict[str, int] = {
    # Cantrips (0)
    "prestidigitation": 0, "ray of frost": 0, "light": 0, "sacred flame": 0,
    "eldritch blast": 0, "toll the dead": 0, "mage hand": 0, "fire bolt": 0,
    "chill touch": 0, "minor illusion": 0, "shocking grasp": 0, "guidance": 0,
    "produce flame": 0, "vicious mockery": 0, "friends": 0,
    # Nível 1
    "magic missile": 1, "cure wounds": 1, "healing word": 1, "bless": 1,
    "shield of faith": 1, "fog cloud": 1, "sleep": 1, "burning hands": 1,
    "mage armor": 1, "shield": 1, "hex": 1, "charm person": 1,
    "feather fall": 1, "detect magic": 1, "identify": 1, "thunderwave": 1,
    "entangle": 1, "speak with animals": 1, "divine favor": 1, "hunters mark": 1,
    "hunter's mark": 1, "inflict wounds": 1, "guiding bolt": 1,
    # Nível 2
    "misty step": 2, "invisibility": 2, "mirror image": 2, "suggestion": 2,
    "spider climb": 2, "hold person": 2, "spiritual weapon": 2, "aid": 2,
    "enhance ability": 2, "pass without trace": 2, "silence": 2, "web": 2,
    "darkness": 2, "blur": 2, "locate object": 2, "lesser restoration": 2,
    # Nível 3
    "fireball": 3, "lightning bolt": 3, "counterspell": 3, "fly": 3,
    "dispel magic": 3, "slow": 3, "haste": 3, "fear": 3, "hypnotic pattern": 3,
    "mass healing word": 3, "call lightning": 3, "erupting earth": 3,
    "bestow curse": 3, "vampiric touch": 3, "animate dead": 3,
    # Nível 4
    "greater invisibility": 4, "polymorph": 4, "banishment": 4,
    "dimension door": 4, "stone shape": 4, "confusion": 4,
    "ice storm": 4, "wall of fire": 4, "blight": 4,
    # Nível 5
    "cloudkill": 5, "cone of cold": 5, "hold monster": 5, "telekinesis": 5,
    "wall of force": 5, "animate objects": 5, "mass cure wounds": 5,
    "raise dead": 5, "planar binding": 5, "conjure elemental": 5,
    # Nível 6+
    "disintegrate": 6, "chain lightning": 6, "flesh to stone": 6,
    "heal": 6, "true seeing": 6, "word of recall": 6,
    "teleport": 7, "plane shift": 7, "regenerate": 7, "reverse gravity": 7,
    "abi-dalzim's horrid wilting": 8, "mind blank": 8, "power word stun": 8,
    "true resurrection": 9, "wish": 9, "power word kill": 9, "foresight": 9,
}

# ── Armas, armaduras e itens: o compêndio local (rpg/itens.py) ───────────
# Dano, propriedades, CA, preço e peso vêm de rpg/dados/srd_itens.json, gerado
# do SRD e revisado à mão (scripts/gerar_itens.py). As tabelas que moravam
# aqui (WEAPON_PT_TO_EN, _ARMAS_SRD) tinham o preço das armas sem o dano e
# cobriam 30 das 37; o dano vinha do Open5e em tempo de jogo, pelo nome. Sem
# rede, toda arma causava 1d6; com rede, "Espada Longa +1" também (o "+1"
# quebrava a busca), e a arma mágica batia menos que a comum.
from rpg import itens as _itens


# ── Tradução PT→EN para busca de raças no Open5e ─────────────────────────────
RACE_PT_TO_EN: dict[str, str] = {
    "humano":    "human",
    "elfo":      "elf",
    "anão":      "dwarf",
    "halfling":  "halfling",
    "draconato": "dragonborn",
    "gnomo":     "gnome",
    "meio-elfo": "half-elf",
    "meio-orc":  "half-orc",
    "tiferino":  "tiefling",
    "tiefling":  "tiefling",
    "orc":       "orc",
    "goblin":    "goblin",
}


SPELL_PT_TO_EN: dict[str, str] = {
    "bola de fogo":          "fireball",
    "míssil mágico":         "magic missile",
    "cura ferimentos":       "cure wounds",
    "palavra curativa":      "healing word",
    "bênção":                "bless",
    "escudo da fé":          "shield of faith",
    "sono":                  "sleep",
    "mãos ardentes":         "burning hands",
    "relâmpago":             "lightning bolt",
    "raio":                  "lightning bolt",
    "dissipar magia":        "dispel magic",
    "bola de fogo da magia": "fireball",
    "nuvem mortífera":       "cloudkill",
    "muralha de fogo":       "wall of fire",
    "invocar raio":          "call lightning",
    "raio de gelo":          "ray of frost",
    "chamas sagradas":       "sacred flame",
    "luz":                   "light",
    "escuridão":             "darkness",
    "voo":                   "fly",
    "invisibilidade":        "invisibility",
    "teia":                  "web",
    "névoa":                 "fog cloud",
    "emaranhar":             "entangle",
    "queda suave":           "feather fall",
    "escudo":                "shield",
    "armadura de mago":      "mage armor",
    "raio enfraquecedor":    "ray of enfeeblement",
    "encantamento":          "charm person",
    "enfeitiçar pessoa":     "charm person",
    "detectar magia":        "detect magic",
    "identificar":           "identify",
    "hex":                   "hex",
    "sentinela espiritual":  "spiritual weapon",
    "arma espiritual":       "spiritual weapon",
    "cura em massa":         "mass cure wounds",
    "reviver":               "revivify",
    "ressuscitar":           "raise dead",
    "palavra de cura em massa": "mass healing word",
    "fúria divina":          "divine smite",
    "punição divina":        "divine smite",
    "tempestade de espadas": "conjure barrage",
    "atirar múltiplo":       "conjure barrage",
    "passo da tempestade":   "thunder step",
    "portal dimensional":    "dimension door",
    "transporte via plantas":"transport via plants",
    "metamorfose":           "polymorph",
    "petrificar":            "flesh to stone",
    "nuvem de adormecimento":"sleep",
    "silêncio":              "silence",
    "auxílio":               "aid",
    "proteção contra o mal": "protection from evil and good",
    "localizar objeto":      "locate object",
}

# ── Habilidades de classe por nível (progressão automática) ─────────────────
# Apenas habilidades mecânicas significativas — o LLM narra o fluff.
CLASS_LEVEL_FEATURES: dict[str, dict[int, list[str]]] = {
    "bárbaro": {
        1:  ["Fúria", "Defesa Sem Armadura"],
        2:  ["Movimento Imprudente", "Senso de Perigo"],
        3:  ["Caminho Primitivo"],
        5:  ["Ataque Extra", "Movimento Rápido"],
        7:  ["Instinto Selvagem"],
        9:  ["Resistência Brutal"],
        11: ["Fúria Implacável"],
        15: ["Ira Persistente"],
        17: ["Fúria Devastadora"],
        18: ["Força Indômita"],
        20: ["Guerreiro Primordial"],
    },
    "guerreiro": {
        1:  ["Estilo de Combate", "Segunda Fôlego"],
        2:  ["Surto de Ação"],
        3:  ["Arquétipo Marcial"],
        5:  ["Ataque Extra"],
        9:  ["Indomável"],
        11: ["Ataque Extra Adicional"],
        17: ["Surto de Ação Adicional"],
        20: ["Campeão Eterno"],
    },
    "paladino": {
        1:  ["Sentido Divino", "Imposição de Mãos"],
        2:  ["Combate Divino", "Conjuração"],
        3:  ["Saúde Divina", "Juramento Sagrado"],
        5:  ["Ataque Extra"],
        6:  ["Aura de Proteção"],
        10: ["Aura de Coragem"],
        11: ["Golpe Divino Aprimorado"],
        14: ["Pureza do Espírito"],
        18: ["Aura Aprimorada"],
        20: ["Campeão Sagrado"],
    },
    "patrulheiro": {
        1:  ["Inimigo Favorecido", "Explorador Natural"],
        2:  ["Estilo de Combate", "Conjuração"],
        3:  ["Arquétipo do Patrulheiro", "Consciência Primitiva"],
        5:  ["Ataque Extra"],
        6:  ["Inimigo Favorecido Adicional", "Explorador Natural Adicional"],
        8:  ["Passagem pela Terra"],
        10: ["Escondes-te à Vista"],
        14: ["Desaparecer"],
        20: ["Inimigo do Inimigo"],
    },
    "bardo": {
        1:  ["Conjuração", "Inspiração Bárdica"],
        2:  ["Canção de Repouso", "Versatilidade"],
        3:  ["Colégio Bárdico", "Especialização"],
        5:  ["Inspiração Bárdica Aprimorada", "Fonte de Inspiração"],
        6:  ["Segredo da Magia"],
        10: ["Segredos Mágicos", "Inspiração Superior"],
        14: ["Segredos Mágicos Adicionais"],
        18: ["Sapiência"],
        20: ["Inspiração Superior Aprimorada"],
    },
    "clérigo": {
        1:  ["Conjuração", "Domínio Divino"],
        2:  ["Canalizar Divindade"],
        5:  ["Destruição de Mortos-Vivos"],
        8:  ["Intervenção Divina Inicial"],
        10: ["Intervenção Divina"],
        14: ["Destruição de Mortos-Vivos Aprimorada"],
        20: ["Intervenção Divina Superior"],
    },
    "druida": {
        1:  ["Druídico", "Conjuração"],
        2:  ["Forma Selvagem", "Círculo Druídico"],
        4:  ["Forma Selvagem Aprimorada"],
        6:  ["Uso de Forma Selvagem Adicional"],
        18: ["Forma Selvagem do Druida de Besta"],
        20: ["Arquidruida"],
    },
    "monge": {
        1:  ["Artes Marciais", "Defesa Sem Armadura"],
        2:  ["Ki", "Movimento Sem Armadura"],
        3:  ["Desviar Projéteis", "Tradição Monástica"],
        4:  ["Queda Lenta"],
        5:  ["Ataque Extra", "Atordoamento"],
        6:  ["Golpes Ki-Aprimorados"],
        7:  ["Evasão", "Tranquilidade"],
        9:  ["Correr Pelas Paredes"],
        10: ["Pureza de Corpo"],
        11: ["Língua do Sol e da Lua"],
        12: ["Alma do Diamante"],
        14: ["Alma Sem Idade"],
        15: ["Mente Vazia"],
        18: ["Corpo Vazio"],
        20: ["Ser Perfeito"],
    },
    "ladino": {
        1:  ["Ataque Furtivo", "Linguagem dos Ladrões", "Especialização"],
        2:  ["Ação Ardilosa"],
        3:  ["Arquétipo de Ladrão"],
        5:  ["Esquiva Incrivelmente Baixa"],
        6:  ["Especialização Adicional"],
        7:  ["Evasão"],
        11: ["Talento Confiável"],
        14: ["Visão às Cegas"],
        15: ["Mente Escorregadia"],
        18: ["Elusivo"],
        20: ["Assassino Reflexivo"],
    },
    "mago": {
        1:  ["Recuperação Arcana", "Tradição Arcana"],
        2:  ["Feitiço de Tradição"],
        6:  ["Habilidade de Tradição"],
        10: ["Habilidade de Tradição Adicional"],
        14: ["Habilidade de Tradição Superior"],
        18: ["Maestria de Feitiço"],
        20: ["Assinatura de Feitiço"],
    },
    "feiticeiro": {
        1:  ["Origem de Feiticeiro", "Conjuração"],
        2:  ["Pontos de Feitiçaria", "Metamagia"],
        3:  ["Metamagia Adicional"],
        6:  ["Habilidade de Origem"],
        14: ["Habilidade de Origem Adicional"],
        17: ["Metamagia Adicional"],
        18: ["Habilidade de Origem Superior"],
        20: ["Restauração de Feitiçaria"],
    },
    "bruxo": {
        1:  ["Patrono Sobrenatural", "Magia do Pacto"],
        2:  ["Invocações Sobrenaturais"],
        3:  ["Bênção do Pacto"],
        5:  ["Invocações Sobrenaturais Adicionais"],
        6:  ["Habilidade do Patrono"],
        7:  ["Invocações Sobrenaturais Adicionais"],
        9:  ["Invocações Sobrenaturais Adicionais"],
        10: ["Habilidade do Patrono Adicional"],
        11: ["Magia Mística"],
        14: ["Habilidade do Patrono Superior"],
        15: ["Invocações Sobrenaturais Adicionais"],
        18: ["Invocações Sobrenaturais Adicionais"],
        20: ["Mestre Sobrenatural"],
    },
    "npc": {},
}

# ── Descrições básicas para habilidades de classe automáticas ────────────────
# Cobertura: TODAS as entradas de CLASS_LEVEL_FEATURES devem estar aqui.
# Se faltar uma, o backend cai num fallback genérico ("Habilidade de classe —
# X") que é inútil para o jogador. Mantenha sincronizado ao adicionar novas
# features. Estilo: 1 frase curta (~100-180 chars) baseada no SRD 5e em PT-BR.
CLASS_FEATURE_DESCS: dict[str, dict] = {
    # ── Genéricas / compartilhadas ─────────────────────────────────────────
    "Ataque Extra":              {"descricao": "Pode atacar duas vezes em vez de uma ao usar a ação Atacar.", "custo_mana": 0, "dado": ""},
    "Ataque Extra Adicional":    {"descricao": "Pode atacar três vezes em vez de duas ao usar a ação Atacar (nv. 11+).", "custo_mana": 0, "dado": ""},
    "Defesa Sem Armadura":       {"descricao": "Sem armadura, CA = 10 + mod. DES + mod. CON (Bárbaro) ou + mod. SAB (Monge). Pode usar escudo (Bárbaro).", "custo_mana": 0, "dado": ""},
    "Estilo de Combate":         {"descricao": "Escolhe um estilo (Arquearia, Defesa, Duelo, Combate com Duas Armas, Proteção, Grande Arma) com bônus passivo permanente.", "custo_mana": 0, "dado": ""},
    "Especialização":            {"descricao": "Dobra o bônus de proficiência em 2 perícias ou ferramentas escolhidas em que já tem proficiência.", "custo_mana": 0, "dado": ""},
    "Evasão":                    {"descricao": "Em saves de DES bem-sucedidos contra efeitos de área: nenhum dano. Em falhas: metade do dano.", "custo_mana": 0, "dado": ""},
    "Conjuração":                {"descricao": "Ganha acesso a magias da classe. Usa o atributo de conjuração próprio (CAR/SAB/INT) para CD e ataques mágicos.", "custo_mana": 0, "dado": ""},

    # ── Bárbaro ───────────────────────────────────────────────────────────
    "Fúria":                     {"descricao": "Ação bônus: +2 dano com armas FOR, vantagem em testes/saves de FOR, resistência a dano físico. Dura 1 minuto. Usos = 2 + nível (até 6 no 17º).", "custo_mana": 0, "dado": ""},
    "Movimento Imprudente":      {"descricao": "Ao atacar com FOR no 1º ataque do turno: ganha vantagem, mas ataques contra você também ganham vantagem até o próximo turno.", "custo_mana": 0, "dado": ""},
    "Senso de Perigo":           {"descricao": "Vantagem em saves de DES contra efeitos visíveis (armadilhas, magias) — desde que não esteja cego, surdo ou incapacitado.", "custo_mana": 0, "dado": ""},
    "Caminho Primitivo":         {"descricao": "Escolhe uma trilha (Berserker, Guerreiro Totêmico, etc.) que define habilidades temáticas do 3º nível em diante.", "custo_mana": 0, "dado": ""},
    "Movimento Rápido":          {"descricao": "Deslocamento +3m enquanto não estiver usando armadura pesada.", "custo_mana": 0, "dado": ""},
    "Instinto Selvagem":         {"descricao": "Vantagem em testes de iniciativa. Não é considerado surpreso se entrar em fúria no primeiro turno.", "custo_mana": 0, "dado": ""},
    "Resistência Brutal":        {"descricao": "Pode reduzir qualquer dano físico recebido em 3 + nível de bárbaro, uma vez por turno.", "custo_mana": 0, "dado": ""},
    "Fúria Implacável":          {"descricao": "Se for reduzido a 0 PV durante a fúria (sem morrer na hora), fica com 1 PV. 1 uso por descanso longo.", "custo_mana": 0, "dado": ""},
    "Ira Persistente":           {"descricao": "Sua fúria só termina cedo se você ficar inconsciente ou escolher terminá-la — não mais pela falta de ações ou dano.", "custo_mana": 0, "dado": ""},
    "Fúria Devastadora":         {"descricao": "Ao acertar um crítico com arma corpo a corpo, role um dado extra de dano da arma.", "custo_mana": 0, "dado": ""},
    "Força Indômita":            {"descricao": "Sua FOR e CON sobem para 24 e o limite máximo das duas vai para 24 (nv. 20).", "custo_mana": 0, "dado": ""},
    "Guerreiro Primordial":      {"descricao": "Ganha +4 em FOR e CON (nv. 20), com limite máximo 24 nesses dois atributos.", "custo_mana": 0, "dado": ""},

    # ── Guerreiro ─────────────────────────────────────────────────────────
    "Segunda Fôlego":            {"descricao": "Ação bônus: recupera 1d10 + nível de guerreiro de PV. 1 uso por descanso curto ou longo.", "custo_mana": 0, "dado": "1d10"},
    "Surto de Ação":             {"descricao": "1 uso por descanso curto: ganha uma Ação adicional neste turno (além da Ação e Bônus normais).", "custo_mana": 0, "dado": ""},
    "Surto de Ação Adicional":   {"descricao": "Pode usar Surto de Ação 2 vezes entre descansos curtos (nv. 17+).", "custo_mana": 0, "dado": ""},
    "Arquétipo Marcial":         {"descricao": "Escolhe um arquétipo (Campeão, Mestre de Batalha, Cavaleiro Élditch, etc.) — define habilidades temáticas a partir do 3º nível.", "custo_mana": 0, "dado": ""},
    "Indomável":                 {"descricao": "1 vez por descanso longo: pode refazer um teste de resistência que falhou (2 usos no 13º, 3 no 17º).", "custo_mana": 0, "dado": ""},
    "Campeão Eterno":            {"descricao": "Sua FOR ou CON aumenta em 4 (limite máximo 24). Ganha resistência adicional contra ataques (nv. 20).", "custo_mana": 0, "dado": ""},

    # ── Paladino ──────────────────────────────────────────────────────────
    "Sentido Divino":            {"descricao": "Ação: detecta criaturas celestiais, infernais e mortos-vivos em até 18m. Usos = 1 + mod. CAR por descanso longo.", "custo_mana": 0, "dado": ""},
    "Imposição de Mãos":         {"descricao": "Pool de cura = nível × 5 PV. Pode dividir entre cura ou gastar 5 PV para neutralizar um veneno/doença em um toque.", "custo_mana": 0, "dado": ""},
    "Combate Divino":            {"descricao": "Pode gastar slots de magia ao acertar com arma corpo a corpo para causar +2d8 (slot 1) até +5d8 radiante extra (Smite Divino).", "custo_mana": 0, "dado": "2d8"},
    "Saúde Divina":              {"descricao": "Imune a doenças mágicas e naturais (nv. 3+).", "custo_mana": 0, "dado": ""},
    "Juramento Sagrado":         {"descricao": "Escolhe um juramento (Devoção, Antigos, Vingança, etc.) que define preceitos, magias bônus e usos de Canalizar Divindade.", "custo_mana": 0, "dado": ""},
    "Aura de Proteção":          {"descricao": "Você e aliados em 3m (6m no 18º) ganham +mod. CAR em todos os saves enquanto você estiver consciente.", "custo_mana": 0, "dado": ""},
    "Aura de Coragem":           {"descricao": "Você e aliados em 3m (6m no 18º) são imunes à condição Amedrontado enquanto você estiver consciente.", "custo_mana": 0, "dado": ""},
    "Golpe Divino Aprimorado":   {"descricao": "Seus ataques com arma corpo a corpo causam +1d8 radiante extra automático (nv. 11+).", "custo_mana": 0, "dado": "1d8"},
    "Pureza do Espírito":        {"descricao": "Permanentemente sob efeito da magia Proteção contra o Mal e Bem (nv. 14+).", "custo_mana": 0, "dado": ""},
    "Aura Aprimorada":           {"descricao": "Suas auras de Proteção e Coragem têm alcance ampliado para 9m (nv. 18+).", "custo_mana": 0, "dado": ""},
    "Campeão Sagrado":           {"descricao": "+4 em FOR ou CAR (limite máximo 24). Recupera 10 PV no início de cada turno se estiver com ≥ 1 PV (nv. 20).", "custo_mana": 0, "dado": ""},

    # ── Patrulheiro ───────────────────────────────────────────────────────
    "Inimigo Favorecido":        {"descricao": "Escolhe um tipo de criatura — vantagem em testes para rastreá-la, +PROF de info, +2 dano em armas contra ela.", "custo_mana": 0, "dado": ""},
    "Inimigo Favorecido Adicional":{"descricao": "Escolhe um 2º tipo de inimigo favorecido (nv. 6+).", "custo_mana": 0, "dado": ""},
    "Explorador Natural":        {"descricao": "Escolhe um terreno: viaja em ritmo normal mesmo em terreno difícil, sempre alerta, +PROF na busca por suprimentos.", "custo_mana": 0, "dado": ""},
    "Explorador Natural Adicional":{"descricao": "Escolhe um 2º terreno favorável (nv. 6+).", "custo_mana": 0, "dado": ""},
    "Arquétipo do Patrulheiro":  {"descricao": "Escolhe um arquétipo (Caçador, Senhor das Feras, etc.) — define habilidades temáticas a partir do 3º nível.", "custo_mana": 0, "dado": ""},
    "Consciência Primitiva":     {"descricao": "Ação: detecta tipos de criaturas (feéricos, mortos-vivos, celestiais…) em até 1,5km — varia conforme o terreno (3º+).", "custo_mana": 0, "dado": ""},
    "Passagem pela Terra":       {"descricao": "Move-se em terreno difícil natural sem penalidade. Imune a magias que manipulam plantas vivas. Não deixa rastros (nv. 8+).", "custo_mana": 0, "dado": ""},
    "Escondes-te à Vista":       {"descricao": "1 minuto de preparo em cobertura natural → camuflagem perfeita; pode se esconder mesmo apenas levemente obscurecido (nv. 10+).", "custo_mana": 0, "dado": ""},
    "Desaparecer":               {"descricao": "Pode usar Esconder como ação bônus em seu turno. Não pode ser rastreado magicamente (nv. 14+).", "custo_mana": 0, "dado": ""},
    "Inimigo do Inimigo":        {"descricao": "Uma vez por turno: usa Inimigo Favorecido contra QUALQUER criatura sem gastar slot — escolha o tipo na hora (nv. 20).", "custo_mana": 0, "dado": ""},

    # ── Bardo ─────────────────────────────────────────────────────────────
    "Inspiração Bárdica":        {"descricao": "Ação bônus: aliado em 18m ganha 1d6 (1d8 no 5º, 1d10 no 10º, 1d12 no 15º) para somar a 1 teste/save em 10 min.", "custo_mana": 0, "dado": "1d6"},
    "Inspiração Bárdica Aprimorada":{"descricao": "Seu dado de Inspiração Bárdica sobe (1d8 no 5º; 1d10 no 10º; 1d12 no 15º).", "custo_mana": 0, "dado": "1d8"},
    "Inspiração Superior":       {"descricao": "Em iniciativa, se nenhum uso de Inspiração Bárdica estiver disponível, ganha 1 de volta (nv. 10+).", "custo_mana": 0, "dado": ""},
    "Inspiração Superior Aprimorada":{"descricao": "Recupera todos os usos de Inspiração Bárdica ao rolar iniciativa (nv. 20).", "custo_mana": 0, "dado": ""},
    "Canção de Repouso":         {"descricao": "No descanso curto, aliados que ouvirem você recuperam +1d6 PV extra (escala: 1d8 no 9º, 1d10 no 13º, 1d12 no 17º).", "custo_mana": 0, "dado": "1d6"},
    "Versatilidade":             {"descricao": "Ganha proficiência em qualquer perícia/ferramenta com bônus = metade do PROF (Bardic Jack of All Trades).", "custo_mana": 0, "dado": ""},
    "Colégio Bárdico":           {"descricao": "Escolhe um colégio (Saber, Coragem, etc.) — define habilidades temáticas a partir do 3º nível.", "custo_mana": 0, "dado": ""},
    "Fonte de Inspiração":       {"descricao": "Recupera todos os usos de Inspiração Bárdica em descansos curtos (não apenas longos) (nv. 5+).", "custo_mana": 0, "dado": ""},
    "Segredo da Magia":          {"descricao": "Aprende 2 magias de qualquer classe e as adiciona à sua lista permanentemente (nv. 6+).", "custo_mana": 0, "dado": ""},
    "Segredos Mágicos":          {"descricao": "Aprende mais 2 magias de qualquer classe e as adiciona à sua lista (nv. 10+).", "custo_mana": 0, "dado": ""},
    "Segredos Mágicos Adicionais":{"descricao": "Aprende mais 2 magias de qualquer classe (nv. 14+).", "custo_mana": 0, "dado": ""},
    "Sapiência":                 {"descricao": "+4 em INT ou CAR, limite máximo 24 (nv. 18+).", "custo_mana": 0, "dado": ""},

    # ── Clérigo ───────────────────────────────────────────────────────────
    "Domínio Divino":            {"descricao": "Escolhe um domínio (Vida, Guerra, Conhecimento, Tempestade, etc.) — concede magias bônus e habilidades temáticas.", "custo_mana": 0, "dado": ""},
    "Canalizar Divindade":       {"descricao": "Ação: usa Expulsar Mortos-Vivos ou um efeito do seu domínio. 1 uso por descanso curto (2 no 6º, 3 no 18º).", "custo_mana": 0, "dado": ""},
    "Destruição de Mortos-Vivos":{"descricao": "Ao Expulsar Mortos-Vivos, criaturas com CR ≤ 1/2 (escala com nível) que falharem no save são destruídas (nv. 5+).", "custo_mana": 0, "dado": ""},
    "Destruição de Mortos-Vivos Aprimorada":{"descricao": "O CR máximo destruído por Expulsar sobe (1 no 8º, 2 no 11º, 3 no 14º, 4 no 17º).", "custo_mana": 0, "dado": ""},
    "Intervenção Divina Inicial":{"descricao": "1 vez por descanso longo: implora ajuda divina — 1% × nível de chance de sucesso (nv. 8+).", "custo_mana": 0, "dado": ""},
    "Intervenção Divina":        {"descricao": "Suas chances de Intervenção Divina aumentam (até 30% no 17º) (nv. 10+).", "custo_mana": 0, "dado": ""},
    "Intervenção Divina Superior":{"descricao": "Sua Intervenção Divina tem sucesso automático, sem rolagem (nv. 20).", "custo_mana": 0, "dado": ""},

    # ── Druida ────────────────────────────────────────────────────────────
    "Druídico":                  {"descricao": "Aprende Druídico — idioma secreto dos druidas, falado e escrito (cifras em marcações naturais).", "custo_mana": 0, "dado": ""},
    "Forma Selvagem":            {"descricao": "Ação: transforma-se em besta com CR ≤ ¼ do seu nível (½ no 4º, 1 no 8º). 2 usos por descanso curto ou longo.", "custo_mana": 0, "dado": ""},
    "Círculo Druídico":          {"descricao": "Escolhe um círculo (Terra, Lua, Sonhos, etc.) — define habilidades temáticas a partir do 2º nível.", "custo_mana": 0, "dado": ""},
    "Forma Selvagem Aprimorada": {"descricao": "Sua Forma Selvagem pode adotar bestas com CR maior e formas aquáticas/voadoras (4º: aquática; 8º: voadora).", "custo_mana": 0, "dado": ""},
    "Uso de Forma Selvagem Adicional":{"descricao": "Forma Selvagem agora tem 3 usos por descanso (nv. 6+).", "custo_mana": 0, "dado": ""},
    "Forma Selvagem do Druida de Besta":{"descricao": "Pode usar Forma Selvagem com criaturas mais poderosas e mantê-la por mais tempo (nv. 18+).", "custo_mana": 0, "dado": ""},
    "Arquidruida":               {"descricao": "Forma Selvagem com usos ilimitados. Conjura magias druídicas sem componente material ou verbal (nv. 20).", "custo_mana": 0, "dado": ""},

    # ── Monge ─────────────────────────────────────────────────────────────
    "Artes Marciais":            {"descricao": "Sem armadura/escudo: usa DES no lugar de FOR em ataques desarmados/marciais. Dado marcial 1d4 (sobe até 1d10 no 17º). Bônus: ataque desarmado extra.", "custo_mana": 0, "dado": "1d4"},
    "Ki":                        {"descricao": "Pool de pontos de Ki = seu nível de monge. Gasta em Rajada de Golpes, Defesa Paciente, Passo do Vento, Atordoamento, etc.", "custo_mana": 0, "dado": ""},
    "Movimento Sem Armadura":    {"descricao": "Deslocamento aumenta sem armadura/escudo: +3m no 2º, escalando até +9m no 18º.", "custo_mana": 0, "dado": ""},
    "Desviar Projéteis":         {"descricao": "Reação: reduz dano de ataque à distância em 1d10 + DES + nível de monge. Se zerar, pode arremessar a munição de volta gastando 1 Ki.", "custo_mana": 0, "dado": "1d10"},
    "Tradição Monástica":        {"descricao": "Escolhe uma tradição (Mão Aberta, Sombras, Quatro Elementos, etc.) — define habilidades temáticas a partir do 3º nível.", "custo_mana": 0, "dado": ""},
    "Queda Lenta":               {"descricao": "Reação: reduz dano de queda em 5 × nível de monge.", "custo_mana": 0, "dado": ""},
    "Atordoamento":              {"descricao": "Após acertar um golpe marcial, gasta 1 Ki: alvo faz save de CON; se falhar, fica Atordoado até o fim do próximo turno.", "custo_mana": 0, "dado": ""},
    "Golpes Ki-Aprimorados":     {"descricao": "Ataques desarmados contam como mágicos para resistência/imunidade a dano (nv. 6+).", "custo_mana": 0, "dado": ""},
    "Tranquilidade":             {"descricao": "Ao fim do descanso longo, recebe efeito de Santuário gratuito até o próximo descanso longo (nv. 7+).", "custo_mana": 0, "dado": ""},
    "Correr Pelas Paredes":      {"descricao": "Pode correr em paredes verticais e na água (sem cair) durante o seu turno (nv. 9+).", "custo_mana": 0, "dado": ""},
    "Pureza de Corpo":           {"descricao": "Imune a doenças e venenos (nv. 10+).", "custo_mana": 0, "dado": ""},
    "Língua do Sol e da Lua":    {"descricao": "Compreende todas as línguas faladas (nv. 13+).", "custo_mana": 0, "dado": ""},
    "Alma do Diamante":          {"descricao": "Proficiência em todos os saves. Pode gastar 1 Ki para refazer um save que falhou (nv. 14+).", "custo_mana": 0, "dado": ""},
    "Alma Sem Idade":            {"descricao": "Não envelhece e não precisa de comida ou água (nv. 15+).", "custo_mana": 0, "dado": ""},
    "Mente Vazia":               {"descricao": "Imune a Enfeitiçado e Amedrontado (nv. 15+).", "custo_mana": 0, "dado": ""},
    "Corpo Vazio":               {"descricao": "Ação: gasta 4 Ki — fica invisível por 1 minuto e ganha resistência a todo dano exceto força (nv. 18+).", "custo_mana": 0, "dado": ""},
    "Ser Perfeito":              {"descricao": "Recupera 4 Ki ao rolar iniciativa se estiver com 0. SAB e DES máximos sobem para 24 (nv. 20).", "custo_mana": 0, "dado": ""},

    # ── Ladino ────────────────────────────────────────────────────────────
    "Ataque Furtivo":            {"descricao": "1 vez por turno: +1d6 dano (escala até 10d6 no 19º) em ataque com vantagem OU aliado adjacente ao alvo.", "custo_mana": 0, "dado": "1d6"},
    "Linguagem dos Ladrões":     {"descricao": "Aprende cifra secreta usada por ladinos — mensagens ocultas em conversas, gírias e marcações.", "custo_mana": 0, "dado": ""},
    "Ação Ardilosa":             {"descricao": "Ação bônus: pode Disparar (Disengage), Esconder, ou Correr (Dash) no seu turno.", "custo_mana": 0, "dado": ""},
    "Arquétipo de Ladrão":       {"descricao": "Escolhe um arquétipo (Ladrão, Assassino, Trapaceiro Arcano) — define habilidades temáticas a partir do 3º nível.", "custo_mana": 0, "dado": ""},
    "Especialização Adicional":  {"descricao": "Dobra o bônus de proficiência em 2 perícias/ferramentas extras (nv. 6+).", "custo_mana": 0, "dado": ""},
    "Esquiva Incrivelmente Baixa":{"descricao": "Reação: ao ser atingido por ataque visível, reduz o dano pela metade.", "custo_mana": 0, "dado": ""},
    "Talento Confiável":         {"descricao": "Em testes de perícia com proficiência, qualquer rolagem ≤ 9 é tratada como 10 (nv. 11+).", "custo_mana": 0, "dado": ""},
    "Visão às Cegas":            {"descricao": "Visão às cegas em raio de 3m — percebe ao redor sem usar a visão (nv. 14+).", "custo_mana": 0, "dado": ""},
    "Mente Escorregadia":        {"descricao": "Ganha proficiência em saves de SAB (nv. 15+).", "custo_mana": 0, "dado": ""},
    "Elusivo":                   {"descricao": "Nenhum ataque tem vantagem contra você enquanto estiver consciente (nv. 18+).", "custo_mana": 0, "dado": ""},
    "Assassino Reflexivo":       {"descricao": "Pode refazer uma rolagem de ataque, teste de atributo ou save por turno (nv. 20).", "custo_mana": 0, "dado": ""},

    # ── Mago ──────────────────────────────────────────────────────────────
    "Recuperação Arcana":        {"descricao": "1 vez por dia, em descanso curto: recupera slots de magia totalizando ≤ metade do seu nível (arredondado para cima, nenhum slot > nv. 5).", "custo_mana": 0, "dado": ""},
    "Tradição Arcana":           {"descricao": "Escolhe uma tradição (Evocação, Abjuração, Necromancia, Ilusão, Encantamento, Transmutação, Adivinhação, Conjuração) — define habilidades temáticas.", "custo_mana": 0, "dado": ""},
    "Feitiço de Tradição":       {"descricao": "Habilidade temática da Tradição Arcana no 2º nível — varia conforme a escola escolhida.", "custo_mana": 0, "dado": ""},
    "Habilidade de Tradição":    {"descricao": "Habilidade adicional da Tradição Arcana no 6º nível — varia conforme a escola escolhida.", "custo_mana": 0, "dado": ""},
    "Habilidade de Tradição Adicional":{"descricao": "Habilidade adicional da Tradição Arcana no 10º nível.", "custo_mana": 0, "dado": ""},
    "Habilidade de Tradição Superior":{"descricao": "Habilidade culminante da Tradição Arcana no 14º nível.", "custo_mana": 0, "dado": ""},
    "Maestria de Feitiço":       {"descricao": "Escolhe 1 magia de nível 1 e 1 de nível 2 do seu livro — pode conjurá-las à vontade sem gastar slot (nv. 18+).", "custo_mana": 0, "dado": ""},
    "Assinatura de Feitiço":     {"descricao": "Escolhe 2 magias de nível 3 do livro — cada uma pode ser conjurada uma vez por descanso curto sem gastar slot (nv. 20).", "custo_mana": 0, "dado": ""},

    # ── Feiticeiro ────────────────────────────────────────────────────────
    "Origem de Feiticeiro":      {"descricao": "Escolhe a origem do seu poder (Linhagem Dracônica, Magia Selvagem, etc.) — define habilidades temáticas e atributos passivos.", "custo_mana": 0, "dado": ""},
    "Pontos de Feitiçaria":      {"descricao": "Pool de pontos = seu nível de feiticeiro. Use para criar slots de magia, alimentar Metamagia ou trocar slot ↔ ponto.", "custo_mana": 0, "dado": ""},
    "Metamagia":                 {"descricao": "Escolhe 2 efeitos (Sutil, Empoderada, Distante, Gêmea, Cuidadosa, Estendida, etc.) que alteram magias gastando pontos de feitiçaria.", "custo_mana": 0, "dado": ""},
    "Metamagia Adicional":       {"descricao": "Aprende mais 1 efeito de Metamagia (no 10º e no 17º nível).", "custo_mana": 0, "dado": ""},
    "Habilidade de Origem":      {"descricao": "Habilidade temática da sua Origem de Feiticeiro no 6º nível.", "custo_mana": 0, "dado": ""},
    "Habilidade de Origem Adicional":{"descricao": "Habilidade adicional da Origem de Feiticeiro no 14º nível.", "custo_mana": 0, "dado": ""},
    "Habilidade de Origem Superior":{"descricao": "Habilidade culminante da Origem de Feiticeiro no 18º nível.", "custo_mana": 0, "dado": ""},
    "Restauração de Feitiçaria": {"descricao": "1 vez por descanso curto: recupera 4 Pontos de Feitiçaria (nv. 20).", "custo_mana": 0, "dado": ""},

    # ── Bruxo ─────────────────────────────────────────────────────────────
    "Patrono Sobrenatural":      {"descricao": "Faz um pacto com um patrono (Senhor Lich, Arquifada, Senhor das Sombras, Grande Antigo, etc.) — define habilidades temáticas.", "custo_mana": 0, "dado": ""},
    "Magia do Pacto":             {"descricao": "Conjuração via pacto: poucos slots, mas todos sobem juntos para o nível máximo. Recuperados em descanso CURTO (não longo).", "custo_mana": 0, "dado": ""},
    "Invocações Sobrenaturais":  {"descricao": "Aprende invocações (Eldritch Invocations) — habilidades passivas/at-will que modificam magias e perícias.", "custo_mana": 0, "dado": ""},
    "Invocações Sobrenaturais Adicionais":{"descricao": "Aprende mais 1 Invocação Sobrenatural.", "custo_mana": 0, "dado": ""},
    "Bênção do Pacto":           {"descricao": "Escolhe um pacto: Lâmina (arma mágica), Tomo (livro com 3 truques extras) ou Corrente (familiar especial).", "custo_mana": 0, "dado": ""},
    "Habilidade do Patrono":     {"descricao": "Habilidade temática do seu Patrono no 6º nível — varia conforme o patrono escolhido.", "custo_mana": 0, "dado": ""},
    "Habilidade do Patrono Adicional":{"descricao": "Habilidade adicional do Patrono no 10º nível.", "custo_mana": 0, "dado": ""},
    "Habilidade do Patrono Superior":{"descricao": "Habilidade culminante do Patrono no 14º nível.", "custo_mana": 0, "dado": ""},
    "Magia Mística":             {"descricao": "Aprende 1 magia de QUALQUER lista de classe, conjurada com slot separado recuperado a cada descanso longo (nv. 11+).", "custo_mana": 0, "dado": ""},
    "Mestre Sobrenatural":       {"descricao": "Pode recuperar 1 slot de pacto como ação no combate, 1 vez por descanso longo (nv. 20).", "custo_mana": 0, "dado": ""},
}


# ────────────────────────────────────────────────────────────────────────────
# FEATURE_VARIANTS — subescolhas mecânicas de habilidades de classe.
# (Fase 1: features "escolha 1/N de uma lista finita" com efeito bem definido.)
#
# Estrutura:
#   FEATURE_VARIANTS[<nome da feature em PT-BR>] = {
#     "pick":        int        # quantas opções escolher
#     "pick_label":  str        # rótulo da unidade (ex.: "estilo", "tipo")
#     "options": {
#         <nome>: {"descricao": str, "narrative_hint": "passive"|"reaction"|"active"}
#     },
#   }
#
# Storage por personagem: char["sheet"]["feature_choices"][feature_name].
#   • pick=1 → string única ("Arquearia")
#   • pick>1 → lista ([..])
#
# Para LIGAR o efeito mecânico, ver _combat_style_bonus / _recalculate_ca /
# attack_roll. Variantes sem hook engine valem como nota narrativa que a
# IA-mestre lê na descrição da ficha.
# ────────────────────────────────────────────────────────────────────────────
FEATURE_VARIANTS: dict[str, dict] = {
    # Guerreiro / Patrulheiro / Paladino — 1º nível (e Bardo de Coragem no 3º)
    "Estilo de Combate": {
        "pick": 1,
        "pick_label": "estilo",
        "options": {
            "Arquearia":               {"descricao": "+2 nos rolls de ataque com armas à distância.", "narrative_hint": "passive"},
            "Defesa":                  {"descricao": "+1 CA enquanto estiver usando qualquer armadura.", "narrative_hint": "passive"},
            "Duelo":                   {"descricao": "+2 dano com arma corpo a corpo de uma mão, desde que não esteja empunhando outra arma.", "narrative_hint": "passive"},
            "Combate com Duas Armas":  {"descricao": "Adiciona o modificador de atributo ao dano do ataque com a 2ª arma (off-hand).", "narrative_hint": "passive"},
            "Proteção":                {"descricao": "Reação (precisa estar com escudo): impõe desvantagem em um ataque contra aliado adjacente.", "narrative_hint": "reaction"},
            "Grande Arma":             {"descricao": "Quando rola 1 ou 2 nos dados de dano de arma de duas mãos, pode re-rolar uma vez por dado.", "narrative_hint": "passive"},
        },
    },
    # Patrulheiro — 1º nível (segundo tipo no 6º via "Inimigo Favorecido Adicional")
    "Inimigo Favorecido": {
        "pick": 1,
        "pick_label": "tipo",
        "options": {
            "Aberrações":     {"descricao": "Especialista em aberrações: vantagem para rastreá-las e +PROF info; +2 dano contra esse tipo.", "narrative_hint": "passive"},
            "Bestas":         {"descricao": "Especialista em bestas (animais): vantagem para rastrear, +PROF info, +2 dano.",                  "narrative_hint": "passive"},
            "Celestiais":     {"descricao": "Especialista em celestiais: vantagem para rastrear, +PROF info, +2 dano.",                       "narrative_hint": "passive"},
            "Constructos":    {"descricao": "Especialista em constructos: vantagem para rastrear, +PROF info, +2 dano.",                      "narrative_hint": "passive"},
            "Dragões":        {"descricao": "Especialista em dragões: vantagem para rastrear, +PROF info, +2 dano.",                          "narrative_hint": "passive"},
            "Elementais":     {"descricao": "Especialista em elementais: vantagem para rastrear, +PROF info, +2 dano.",                       "narrative_hint": "passive"},
            "Feéricos":       {"descricao": "Especialista em feéricos: vantagem para rastrear, +PROF info, +2 dano.",                         "narrative_hint": "passive"},
            "Infernais":      {"descricao": "Especialista em infernais (demônios/diabos): vantagem para rastrear, +PROF info, +2 dano.",      "narrative_hint": "passive"},
            "Gigantes":       {"descricao": "Especialista em gigantes: vantagem para rastrear, +PROF info, +2 dano.",                         "narrative_hint": "passive"},
            "Humanoides":     {"descricao": "Especialista em humanoides: vantagem para rastrear, +PROF info, +2 dano.",                       "narrative_hint": "passive"},
            "Mortos-vivos":   {"descricao": "Especialista em mortos-vivos: vantagem para rastrear, +PROF info, +2 dano.",                     "narrative_hint": "passive"},
            "Monstruosidades":{"descricao": "Especialista em monstruosidades: vantagem para rastrear, +PROF info, +2 dano.",                  "narrative_hint": "passive"},
            "Plantas":        {"descricao": "Especialista em plantas: vantagem para rastrear, +PROF info, +2 dano.",                          "narrative_hint": "passive"},
            "Limos":          {"descricao": "Especialista em limos: vantagem para rastrear, +PROF info, +2 dano.",                            "narrative_hint": "passive"},
        },
    },
    # Guerreiro Mestre de Batalha — 3º nível (mais duas no 10º e no 15º).
    # As que o motor resolve (rpg/superioridade.py).
    "Manobras de Combate": {
        "pick": 3,
        "pick_label": "manobras",
        "options": {
            "Ataque Ameaçador":   {"descricao": "+dado no dano; SAB ou fica Amedrontado até o fim do seu próximo turno.", "narrative_hint": "active"},
            "Ataque Derrubador":  {"descricao": "+dado no dano; FOR ou fica Caído.", "narrative_hint": "active"},
            "Ataque de Empurrão": {"descricao": "+dado no dano; FOR ou é empurrado para a zona vizinha.", "narrative_hint": "active"},
            "Ataque Desarmante":  {"descricao": "+dado no dano; FOR ou larga a arma.", "narrative_hint": "active"},
            "Ataque Distrativo":  {"descricao": "+dado no dano; o próximo ataque de um aliado contra o alvo tem vantagem.", "narrative_hint": "active"},
            "Ataque Provocador":  {"descricao": "+dado no dano; SAB ou tem desvantagem para atacar outros que não você.", "narrative_hint": "active"},
            "Ataque Varredor":    {"descricao": "Se acertar, o dado fere outro inimigo ao alcance.", "narrative_hint": "active"},
            "Ataque Preciso":     {"descricao": "Soma o dado a um ataque que errou.", "narrative_hint": "active"},
            "Finta":              {"descricao": "Ação bônus: vantagem no próximo ataque contra o alvo e +dado no dano.", "narrative_hint": "active"},
            "Reagrupar":          {"descricao": "Ação bônus: um aliado ganha PV temporários (dado + CAR).", "narrative_hint": "active"},
            "Contra-Ataque":      {"descricao": "Reação: quando um inimigo erra você corpo a corpo, você ataca (+dado).", "narrative_hint": "reaction"},
            "Aparar":             {"descricao": "Reação: reduz o dano de um ataque corpo a corpo em dado + DES.", "narrative_hint": "reaction"},
        },
    },
    "Manobras Aprimoradas": {"pick": 2, "pick_label": "manobras", "options": "ref:Manobras de Combate"},
    "Manobras Relâmpago":   {"pick": 2, "pick_label": "manobras", "options": "ref:Manobras de Combate"},
    "Inimigo Favorecido Adicional": {  # 6º nível — herda mesmas opções
        "pick": 1,
        "pick_label": "tipo",
        "options": "ref:Inimigo Favorecido",  # resolvido em _get_variants()
    },
    # Patrulheiro — 1º nível (segundo terreno no 6º via "Explorador Natural Adicional")
    "Explorador Natural": {
        "pick": 1,
        "pick_label": "terreno",
        "options": {
            "Ártico":       {"descricao": "Em ambiente ártico: viagem normal em terreno difícil, sempre alerta, +PROF na busca por suprimentos.",     "narrative_hint": "passive"},
            "Costa":        {"descricao": "Em ambiente costeiro: viagem normal em terreno difícil, sempre alerta, +PROF na busca por suprimentos.",  "narrative_hint": "passive"},
            "Deserto":      {"descricao": "Em ambiente desértico: viagem normal em terreno difícil, sempre alerta, +PROF na busca por suprimentos.", "narrative_hint": "passive"},
            "Floresta":     {"descricao": "Em florestas: viagem normal em terreno difícil, sempre alerta, +PROF na busca por suprimentos.",          "narrative_hint": "passive"},
            "Pântano":      {"descricao": "Em pântanos: viagem normal em terreno difícil, sempre alerta, +PROF na busca por suprimentos.",           "narrative_hint": "passive"},
            "Montanha":     {"descricao": "Em montanhas: viagem normal em terreno difícil, sempre alerta, +PROF na busca por suprimentos.",          "narrative_hint": "passive"},
            "Planície":     {"descricao": "Em planícies: viagem normal em terreno difícil, sempre alerta, +PROF na busca por suprimentos.",          "narrative_hint": "passive"},
            "Subterrâneo":  {"descricao": "No subterrâneo: viagem normal em terreno difícil, sempre alerta, +PROF na busca por suprimentos.",        "narrative_hint": "passive"},
        },
    },
    "Explorador Natural Adicional": {  # 6º nível
        "pick": 1,
        "pick_label": "terreno",
        "options": "ref:Explorador Natural",
    },
    # Feiticeiro — 3º nível, escolhe 2 (+1 no 10º, +1 no 17º via "Metamagia Adicional")
    "Metamagia": {
        "pick": 2,
        "pick_label": "efeitos",
        "options": {
            "Sutil":       {"descricao": "1 ponto: conjura sem componente verbal nem somático (ignora silêncio/restrição de mãos).",                "narrative_hint": "active"},
            "Empoderada":  {"descricao": "1 ponto: re-rola até CAR (mín. 1) dados de dano de uma magia, usando o novo resultado.",                  "narrative_hint": "active"},
            "Distante":    {"descricao": "1 ponto: dobra o alcance da magia; ou em magias de Toque, vira alcance de 9m.",                            "narrative_hint": "active"},
            "Estendida":   {"descricao": "1 ponto: dobra a duração de magias com duração ≥ 1 min (máx. 24h).",                                       "narrative_hint": "active"},
            "Gêmea":       {"descricao": "Custo = nível da magia: alveja 1 criatura adicional (somente magias de alvo único).",                      "narrative_hint": "active"},
            "Cuidadosa":   {"descricao": "1 ponto: ao conjurar magia com save em área, até CAR aliados passam automaticamente.",                     "narrative_hint": "active"},
            "Acelerada":   {"descricao": "2 pontos: uma magia que normalmente tem tempo de conjuração 1 Ação vira 1 Ação Bônus.",                    "narrative_hint": "active"},
            "Intensificada":{"descricao": "3 pontos: 1 alvo da magia tem desvantagem no 1º save de resistência.",                                   "narrative_hint": "active"},
        },
    },
    "Metamagia Adicional": {
        "pick": 1,
        "pick_label": "efeito",
        "options": "ref:Metamagia",
    },
    # Bruxo — 2º nível, escolhe N (escala com nível)
    "Invocações Sobrenaturais": {
        "pick": 2,
        "pick_at_level": {2: 2, 5: 3, 7: 4, 9: 5, 12: 6, 15: 7, 18: 8},
        "pick_label": "invocações",
        "options": {
            "Agonizing Blast":     {"descricao": "Quando conjura Eldritch Blast, soma o mod. de CAR ao dano de cada raio.",            "narrative_hint": "passive"},
            "Repelling Blast":     {"descricao": "Eldritch Blast empurra criatura Grande ou menor em 3m.",                              "narrative_hint": "passive"},
            "Devil's Sight":       {"descricao": "Enxerga normalmente em escuridão mágica em raio de 36m.",                              "narrative_hint": "passive"},
            "Armor of Shadows":    {"descricao": "Conjura Mage Armor (em si) à vontade, sem gastar slot.",                              "narrative_hint": "active"},
            "Eldritch Sight":      {"descricao": "Conjura Detect Magic à vontade, sem gastar slot.",                                    "narrative_hint": "active"},
            "Fiendish Vigor":      {"descricao": "Conjura False Life (nv. 1) em si à vontade.",                                          "narrative_hint": "active"},
            "Mask of Many Faces":  {"descricao": "Conjura Disguise Self à vontade.",                                                     "narrative_hint": "active"},
            "Misty Visions":       {"descricao": "Conjura Silent Image à vontade.",                                                      "narrative_hint": "active"},
            "Beast Speech":        {"descricao": "Pode falar com bestas como na magia Speak with Animals, à vontade.",                  "narrative_hint": "active"},
            "Book of Ancient Secrets":{"descricao": "Pacto do Tomo: escreve magias de ritual (qualquer classe) no livro.",              "narrative_hint": "passive"},
            "Thirsting Blade":     {"descricao": "Pacto da Lâmina (nv.5+): ataca duas vezes com a arma do pacto ao usar Atacar.",       "narrative_hint": "passive"},
            "Lifedrinker":         {"descricao": "Pacto da Lâmina (nv.12+): arma causa +CAR dano necrótico extra.",                     "narrative_hint": "passive"},
            "Voice of the Chain Master":{"descricao": "Pacto da Corrente: comunica telepaticamente com o familiar.",                    "narrative_hint": "passive"},
            "Eldritch Mind":       {"descricao": "Vantagem em saves de CON para manter concentração em magias.",                         "narrative_hint": "passive"},
            "Gaze of Two Minds":   {"descricao": "Toca um humanoide consciente: vê pelos olhos dele por até 1h.",                       "narrative_hint": "active"},
        },
    },
}


def _get_variants(feature_name: str) -> dict | None:
    """Retorna metadata da feature com 'options' resolvido (se for ref:)."""
    v = FEATURE_VARIANTS.get(feature_name)
    if not v:
        return None
    opts = v.get("options")
    if isinstance(opts, str) and opts.startswith("ref:"):
        target = opts.split(":", 1)[1]
        ref = FEATURE_VARIANTS.get(target, {})
        return {**v, "options": ref.get("options", {})}
    return v


def _get_feature_choice(char: dict, feature_name: str):
    """Retorna a(s) escolha(s) atual(is) ou None."""
    fc = ((char or {}).get("sheet") or {}).get("feature_choices") or {}
    return fc.get(feature_name)


def _has_combat_style(char: dict, style: str) -> bool:
    """True se o personagem escolheu o estilo de combate informado."""
    return _get_feature_choice(char, "Estilo de Combate") == style


def _favored_enemy_types(char: dict) -> set[str]:
    """Conjunto normalizado de tipos de criatura favorecidos (em PT-BR)."""
    result = set()
    for feat in ("Inimigo Favorecido", "Inimigo Favorecido Adicional"):
        v = _get_feature_choice(char, feat)
        if isinstance(v, str) and v:
            result.add(_norm_txt(v))
        elif isinstance(v, list):
            for x in v:
                if x: result.add(_norm_txt(x))
    return result


# ── Fase 3: hooks mecânicos de sub-features de arquétipo ──────────────────
def _char_has_feature(char: dict, feature_name: str) -> bool:
    """True se o personagem tem a habilidade/feature pelo nome exato (case-insensitive)."""
    target = (feature_name or "").lower().strip()
    return any((h.get("nome", "") or "").lower().strip() == target
               for h in (char.get("habilidades") or []))


def _crit_threshold(char: dict) -> int:
    """
    Menor resultado de d20 que conta como acerto crítico.
    Campeão: Crítico Aprimorado (nv.3) → 19; Crítico Superior (nv.15) → 18.
    Padrão: 20.
    """
    if _char_has_feature(char, "Crítico Superior"):
        return 18
    if _char_has_feature(char, "Crítico Aprimorado"):
        return 19
    return 20


def _golpe_divino_info(char: dict) -> tuple[int, str] | None:
    """
    Detecta Golpe Divino (domínio de clérigo) ou Golpe Divino Aprimorado
    (paladino). Retorna (n_dados_d8, rótulo_do_tipo) ou None.

    • Clérigo: +1d8 (sobe a 2d8 a partir do nv. 14).
    • Paladino "Golpe Divino Aprimorado": +1d8 fixo, sempre radiante.
    """
    nivel = int((char.get("sheet") or {}).get("nivel", 1) or 1)
    for h in (char.get("habilidades") or []):
        nome = (h.get("nome", "") or "")
        if nome == "Golpe Divino Aprimorado":
            return (1, "radiante")
        if nome.startswith("Golpe Divino"):
            # Extrai o tipo de dano entre parênteses, se houver.
            tipo = "radiante"
            if "(" in nome and ")" in nome:
                inside = nome[nome.find("(") + 1:nome.find(")")].strip().lower()
                _TIPO_MAP = {
                    "vida": "radiante", "guerra": "do tipo escolhido",
                    "luz": "radiante", "conhecimento": "psíquico",
                    "natureza": "elemental", "tempestade": "trovão",
                    "ardil": "veneno",
                }
                tipo = _TIPO_MAP.get(inside, "radiante")
            return (2 if nivel >= 14 else 1, tipo)
    return None


# ── Armas pesadas (two-handed) — usado por Estilo de Combate ──────────────
TWO_HANDED_WEAPONS = {
    "espada grande", "espada de duas mãos", "greatsword",
    "machado grande", "greataxe",
    "maul", "marreta", "alabarda", "halberd",
    "pike", "pica",
    "glaive", "lança serrilhada",
    "arco longo", "longbow", "besta pesada", "heavy crossbow",
    "maça grande", "maul de guerra",
}


def _arma_de_duas_maos(nome: str) -> bool:
    """
    A arma pede as duas mãos? O compêndio decide; a lista acima só vale para
    nome fora do SRD. Antes era a lista, por pedaço do nome: "lança" estava
    nela, e a Lança e a Lança Curta (azagaia) perdiam o Duelo e ganhavam a
    Grande Arma — no SRD a lança é versátil e a azagaia, de uma mão.
    """
    a = _itens.arma(nome)
    if a:
        return "duas_maos" in a["propriedades"]
    n = _norm_txt(nome or "")
    return bool(n) and any(_norm_txt(w) in n for w in TWO_HANDED_WEAPONS)


def _arma_de_tiro(nome: str) -> bool:
    """Arco, besta, funda, zarabatana, dardo, rede: o compêndio, e a lista para o resto."""
    a = _itens.arma(nome)
    if a:
        return a["distancia"]
    n = (nome or "").lower()
    return bool(n) and any(r in n for r in RANGED_WEAPONS)


# ────────────────────────────────────────────────────────────────────────────
# ARCHETYPE_FEATURES — arquétipos de classe e suas sub-features por nível.
#
# Cada feature de arquétipo (ex.: "Arquétipo Marcial") é uma escolha entre
# arquétipos (ex.: Campeão, Mestre de Batalha, Cavaleiro Élditch). Cada
# arquétipo concede sub-features automáticas em níveis específicos.
#
# Estrutura:
#   ARCHETYPE_FEATURES[<feature pai>][<nome do arquétipo>] = {
#     "descricao": str,         # 1 linha que descreve a temática
#     "features": {
#         <nível>: [
#             {"nome": str, "descricao": str, "dado": str, "custo_mana": int},
#             ...
#         ],
#         ...
#     },
#   }
#
# Ao module-load, _register_archetypes() flat-mapeia isso em:
#   • FEATURE_VARIANTS[<feature pai>]   — picker reusa o sistema da Fase 1.
#   • CLASS_FEATURE_DESCS[<sub-feat>]   — descrição visível em todo lugar.
#
# Para CONCEDER as sub-features quando o jogador escolhe (ou sobe de nível),
# ver _apply_archetype_features().
# ────────────────────────────────────────────────────────────────────────────
ARCHETYPE_FEATURES: dict[str, dict[str, dict]] = {
    # ── Guerreiro (Arquétipo Marcial — nv. 3) ──────────────────────────────
    "Arquétipo Marcial": {
        "Campeão": {
            "descricao": "Foco em força bruta, atletismo e críticos.",
            "features": {
                3:  [{"nome": "Crítico Aprimorado", "descricao": "Seus acertos críticos com armas ocorrem em 19 ou 20 no d20.", "dado": "", "custo_mana": 0}],
                7:  [{"nome": "Atleta Notável", "descricao": "Vantagem em testes de FOR (Atletismo). Pode saltar +mod. FOR metros e correr enquanto se levanta sem gastar deslocamento.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Estilo de Combate Adicional", "descricao": "Aprende um 2º Estilo de Combate da lista do Guerreiro.", "dado": "", "custo_mana": 0}],
                15: [{"nome": "Crítico Superior", "descricao": "Seus acertos críticos com armas ocorrem em 18, 19 ou 20 no d20.", "dado": "", "custo_mana": 0}],
                18: [{"nome": "Sobrevivente", "descricao": "No início do seu turno, recupera 5 + mod. CON de PV se estiver com ≤ metade dos PV (e ≥ 1).", "dado": "", "custo_mana": 0}],
            },
        },
        "Mestre de Batalha": {
            "descricao": "Manobras táticas, dados de superioridade.",
            "features": {
                3:  [
                    {"nome": "Manobras de Combate", "descricao": "Aprende 3 manobras da lista do Mestre de Batalha (Aparar, Desarmar, Empurrar, Investida, etc.).", "dado": "", "custo_mana": 0},
                    {"nome": "Dado de Superioridade", "descricao": "Pool de 4 dados d8 (sobe a d10 no 10º, d12 no 18º). Gasta-os para alimentar manobras. Recupera no descanso curto/longo.", "dado": "1d8", "custo_mana": 0},
                    {"nome": "Saber Estudante", "descricao": "Ganha proficiência em uma perícia OU ferramenta de artesão.", "dado": "", "custo_mana": 0},
                ],
                7:  [{"nome": "Resposta Tática", "descricao": "Vantagem em testes de iniciativa. Aliados adjacentes (1,5m) ganham +PROF em rolagens contra criaturas que você golpeou no turno.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Manobras Aprimoradas", "descricao": "Aprende mais 2 manobras. Dado de Superioridade sobe para d10.", "dado": "1d10", "custo_mana": 0}],
                15: [{"nome": "Manobras Relâmpago", "descricao": "Aprende mais 2 manobras. Mais 1 Dado de Superioridade no pool (total 6).", "dado": "", "custo_mana": 0}],
                18: [{"nome": "Manobra Suprema", "descricao": "Quando rola iniciativa sem Dados de Superioridade, recupera 1. Dado sobe para d12.", "dado": "1d12", "custo_mana": 0}],
            },
        },
        "Cavaleiro Élditch": {
            "descricao": "Combatente que mistura magia arcana com armas.",
            "features": {
                3:  [
                    {"nome": "Conjuração (Cavaleiro Élditch)", "descricao": "Conjura magias da lista de mago (foco em Abjuração e Evocação). Atributo de conjuração: INT.", "dado": "", "custo_mana": 0},
                    {"nome": "Vínculo com Arma", "descricao": "Ritual de 1h: vincula-se a até 2 armas. Pode invocá-las à mão como ação bônus.", "dado": "", "custo_mana": 0},
                ],
                7:  [{"nome": "Golpe Mágico", "descricao": "Ao acertar um ataque com arma, gasta uma reação para conjurar uma magia de truque contra o mesmo alvo.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Disparo Mágico", "descricao": "Conjura uma magia como ação e faz 1 ataque como ação bônus.", "dado": "", "custo_mana": 0}],
                15: [{"nome": "Vínculo Aprimorado", "descricao": "Quando acerta um crítico, pode rolar mais 1 dado de dano. Suas armas vinculadas contam como mágicas.", "dado": "", "custo_mana": 0}],
                18: [{"nome": "Vínculo Superior", "descricao": "Pode fazer 2 ataques no lugar de 1 ao usar Conjuração na mesma ação.", "dado": "", "custo_mana": 0}],
            },
        },
    },

    # ── Bárbaro (Caminho Primitivo — nv. 3) ────────────────────────────────
    "Caminho Primitivo": {
        "Berserker": {
            "descricao": "Caminho da fúria descontrolada e da carnificina.",
            "features": {
                3:  [{"nome": "Frenesi", "descricao": "Durante a fúria, pode entrar em Frenesi: ataque bônus corpo-a-corpo a cada turno, mas exaustão (1 nível) após a fúria.", "dado": "", "custo_mana": 0}],
                6:  [{"nome": "Furioso Implacável", "descricao": "Imune a Enfeitiçado e Amedrontado durante a fúria. Se já estava, o efeito é suspenso.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Presença Intimidadora", "descricao": "Ação: criatura em 9m faz save de SAB ou fica Amedrontada por 1 minuto.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Retaliação", "descricao": "Reação ao receber dano de criatura adjacente: faz um ataque corpo-a-corpo contra ela.", "dado": "", "custo_mana": 0}],
            },
        },
        "Guerreiro Totêmico": {
            "descricao": "Caminho da conexão com espíritos animais.",
            "features": {
                3:  [
                    {"nome": "Espírito Selvagem (Totem)", "descricao": "Escolhe um totem animal (Urso, Águia, Lobo, etc.) que concede um benefício passivo na fúria.", "dado": "", "custo_mana": 0},
                    {"nome": "Aspecto do Totem", "descricao": "Benefício passivo permanente baseado no totem (visão de Águia, rastreio de Lobo, etc.).", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Caminho do Andarilho", "descricao": "Comer/beber metade do normal. Resistência a clima extremo. Andar sobre superfícies não-sólidas (totem da Águia).", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Andarilho Espiritual", "descricao": "Conjura Sentir Inferior e Comungar com Natureza como rituais sem gastar slot.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Sintonia Totem", "descricao": "Outro benefício do totem escolhido, mais poderoso (ex.: Urso = aliados adjacentes têm vantagem em saves).", "dado": "", "custo_mana": 0}],
            },
        },
    },

    # ── Paladino (Juramento Sagrado — nv. 3) ───────────────────────────────
    "Juramento Sagrado": {
        "Devoção": {
            "descricao": "Juramento clássico do paladino justo.",
            "features": {
                3:  [
                    {"nome": "Canalizar Divindade (Arma Sagrada)", "descricao": "Ação: arma corpo-a-corpo brilha; +CAR atk e dano por 1 min ou até soltar.", "dado": "", "custo_mana": 0},
                    {"nome": "Canalizar Divindade (Repelir Mortos-Vivos)", "descricao": "Ação: mortos-vivos em 9m fazem save de SAB ou fogem amedrontados por 1 min.", "dado": "", "custo_mana": 0},
                ],
                7:  [{"nome": "Aura de Devoção", "descricao": "Você e aliados em 3m (6m no 18º) imunes a Enfeitiçado enquanto consciente.", "dado": "", "custo_mana": 0}],
                15: [{"nome": "Pureza de Espírito (Devoção)", "descricao": "Permanentemente sob Proteção contra o Mal e Bem.", "dado": "", "custo_mana": 0}],
                20: [{"nome": "Avatar Sagrado", "descricao": "Ação: 1 hora aura sagrada (vantagem em ataques contra você e aliados próximos resistem a dano).", "dado": "", "custo_mana": 0}],
            },
        },
        "Antigos": {
            "descricao": "Juramento da luz contra a corrupção e treva.",
            "features": {
                3:  [
                    {"nome": "Natureza Selvagem", "descricao": "Aprende Falar com Animais como magia de paladino.", "dado": "", "custo_mana": 0},
                    {"nome": "Canalizar Divindade (Tornado de Folhas)", "descricao": "Ação: criatura em 3m faz save de SAB ou fica Amedrontada de você por 1 min.", "dado": "", "custo_mana": 0},
                ],
                7:  [{"nome": "Aura de Combate", "descricao": "Você e aliados em 3m (6m no 18º) ganham resistência a dano de magias.", "dado": "", "custo_mana": 0}],
                15: [{"nome": "Inalterável", "descricao": "Imune a doença. Veneno sofre desvantagem e você resiste.", "dado": "", "custo_mana": 0}],
                20: [{"nome": "Campeão da Natureza", "descricao": "Ação: 1 min forma feérica (vantagem em saves de magia, cura 10 PV/turno, ataques causam +1d10 radiante).", "dado": "1d10", "custo_mana": 0}],
            },
        },
        "Vingança": {
            "descricao": "Juramento de retribuição contra a injustiça.",
            "features": {
                3:  [
                    {"nome": "Marca da Vingança", "descricao": "Reação ao ver criatura atacar aliado em 3m: ataque corpo-a-corpo contra ela.", "dado": "", "custo_mana": 0},
                    {"nome": "Canalizar Divindade (Voto de Inimizade)", "descricao": "Ação bônus: até 1 min, vantagem em todos os ataques contra a criatura marcada.", "dado": "", "custo_mana": 0},
                ],
                7:  [{"nome": "Implacável", "descricao": "Velocidade aumenta em 3m quando se move em direção a inimigo. Imune a Amedrontado.", "dado": "", "custo_mana": 0}],
                15: [{"nome": "Alma de Vingança", "descricao": "Ao usar Marca da Vingança, faz 2 ataques em vez de 1.", "dado": "", "custo_mana": 0}],
                20: [{"nome": "Anjo Vingador", "descricao": "Ação: 1h forma com asas voadora (18m), criaturas próximas amedrontadas, +CAR dano em ataques.", "dado": "", "custo_mana": 0}],
            },
        },
    },

    # ── Patrulheiro (Arquétipo do Patrulheiro — nv. 3) ─────────────────────
    "Arquétipo do Patrulheiro": {
        "Caçador": {
            "descricao": "Patrulheiro especialista em matar monstros perigosos.",
            "features": {
                3:  [{"nome": "Presa do Caçador", "descricao": "Escolhe uma das técnicas: Colossal (mais dano em alvos Grandes+), Massa (+atk vs grupos), Furtivo (+atk vs alvos isolados).", "dado": "", "custo_mana": 0}],
                7:  [{"nome": "Tática Defensiva", "descricao": "Escolhe Esquiva (não há vantagem contra você de criaturas a +1,5m), Coberta (escudo +1 CA contra projéteis) ou Bestial (CA +2 vs uma criatura Grande).", "dado": "", "custo_mana": 0}],
                11: [{"nome": "Ataque Múltiplo", "descricao": "Escolhe Volley (ataque ranged contra área 3m de raio) ou Tempestade Giratória (corpo-a-corpo contra todos os adjacentes).", "dado": "", "custo_mana": 0}],
                15: [{"nome": "Defesa Superior do Caçador", "descricao": "Escolhe Evasivo (+1 reação por turno), Inalterável (vantagem em saves de medo) ou Vingança Selvagem (+1d8 dano ao ser atingido).", "dado": "1d8", "custo_mana": 0}],
            },
        },
        "Senhor das Feras": {
            "descricao": "Patrulheiro com um companheiro animal devotado.",
            "features": {
                3:  [{"nome": "Companheiro Animal", "descricao": "Adquire uma besta CR ≤ 1/4 como aliado leal. Você compartilha iniciativa e ela age sob seu comando.", "dado": "", "custo_mana": 0}],
                7:  [{"nome": "Comunicação Exemplar", "descricao": "Pode dar 2 ordens à fera por turno e ela age automaticamente. Telepatia em 30m.", "dado": "", "custo_mana": 0}],
                11: [{"nome": "Defesa de Mestre", "descricao": "Atributos da fera escalam com seu nível. Ataques dela causam dano extra.", "dado": "", "custo_mana": 0}],
                15: [{"nome": "Recuperação Bestial", "descricao": "Pode usar uma reação para receber o dano destinado à sua fera.", "dado": "", "custo_mana": 0}],
            },
        },
    },

    # ── Bardo (Colégio Bárdico — nv. 3) ────────────────────────────────────
    "Colégio Bárdico": {
        "Saber": {
            "descricao": "Bardo erudito de magias secretas e perícias.",
            "features": {
                3:  [
                    {"nome": "Saber Estudante (Bardo)", "descricao": "Ganha proficiência em 3 perícias quaisquer.", "dado": "", "custo_mana": 0},
                    {"nome": "Especialização Cortês", "descricao": "Como reação ao ser alvo de atk/teste/save de habilidade visível, gasta Inspiração para diminuir o resultado.", "dado": "1d6", "custo_mana": 0},
                ],
                6:  [{"nome": "Segredos Adicionais (Saber)", "descricao": "Aprende 2 magias de qualquer classe (sem precisar esperar nv. 10).", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Inspiração Cortês", "descricao": "Aliado com seu d6 de inspiração pode reutilizá-lo após o efeito original.", "dado": "", "custo_mana": 0}],
            },
        },
        "Coragem": {
            "descricao": "Bardo guerreiro inspirador de combate.",
            "features": {
                3:  [
                    {"nome": "Inspiração de Combate", "descricao": "Aliado com seu dado de inspiração pode usá-lo como dado de dano OU para reagir e ganhar +CA.", "dado": "", "custo_mana": 0},
                    {"nome": "Estilo de Combate (Bardo)", "descricao": "Ganha proficiência em armaduras médias, escudo e armas marciais.", "dado": "", "custo_mana": 0},
                ],
                6:  [
                    {"nome": "Talento de Combate", "descricao": "Pode fazer 2 ataques em vez de 1 ao usar Atacar.", "dado": "", "custo_mana": 0},
                    {"nome": "Conjuração em Armadura", "descricao": "Pode conjurar magias usando armadura de combate.", "dado": "", "custo_mana": 0},
                ],
                14: [{"nome": "Batalha Inspiradora", "descricao": "Inicia o combate concedendo Inspiração a todos os aliados em 9m.", "dado": "", "custo_mana": 0}],
            },
        },
    },

    # ── Clérigo (Domínio Divino — nv. 1) ────────────────────────────────────
    "Domínio Divino": {
        "Vida": {
            "descricao": "Clérigo curandeiro consagrado à preservação.",
            "features": {
                1:  [
                    {"nome": "Treinamento em Armadura Pesada", "descricao": "Ganha proficiência em armaduras pesadas.", "dado": "", "custo_mana": 0},
                    {"nome": "Discípulo da Vida", "descricao": "Magias de cura curam +2 + nível da magia PV adicionais.", "dado": "", "custo_mana": 0},
                ],
                2:  [{"nome": "Canalizar Divindade (Preservar Vida)", "descricao": "Ação: divide nv. × 5 PV de cura entre aliados em 9m (cada um até metade do HP máx).", "dado": "", "custo_mana": 0}],
                6:  [{"nome": "Bênção do Cura", "descricao": "Quando cura, alvo ganha PV temporários iguais a 2× nv. clérigo.", "dado": "", "custo_mana": 0}],
                8:  [{"nome": "Golpe Divino (Vida)", "descricao": "1×/turno: ataque corpo-a-corpo causa +1d8 dano radiante (sobe a 2d8 no 14º).", "dado": "1d8", "custo_mana": 0}],
                17: [{"nome": "Renovação Suprema", "descricao": "Cura máxima rolada sempre (sem rolar dados de cura).", "dado": "", "custo_mana": 0}],
            },
        },
        "Guerra": {
            "descricao": "Clérigo de batalha, marcial e direto.",
            "features": {
                1:  [
                    {"nome": "Treinamento em Armadura Pesada", "descricao": "Ganha proficiência em armaduras pesadas e armas marciais.", "dado": "", "custo_mana": 0},
                    {"nome": "Sacerdote de Guerra", "descricao": "Ação bônus: faz 1 ataque adicional. Usos = mod. SAB por descanso longo.", "dado": "", "custo_mana": 0},
                ],
                2:  [{"nome": "Canalizar Divindade (Guiar Ataque)", "descricao": "Reação após errar atk: +10 no resultado (suficiente para acertar?).", "dado": "", "custo_mana": 0}],
                6:  [{"nome": "Ataque Vindouro", "descricao": "Quando crítica com arma, próximo ataque tem vantagem.", "dado": "", "custo_mana": 0}],
                8:  [{"nome": "Golpe Divino (Guerra)", "descricao": "1×/turno: ataque corpo-a-corpo causa +1d8 dano do tipo de sua escolha (sobe a 2d8 no 14º).", "dado": "1d8", "custo_mana": 0}],
                17: [{"nome": "Avatar da Batalha", "descricao": "1 min de resistência a todo dano físico não-mágico.", "dado": "", "custo_mana": 0}],
            },
        },
        "Conhecimento": {
            "descricao": "Clérigo erudito, buscador de segredos.",
            "features": {
                1:  [{"nome": "Bênção do Conhecimento", "descricao": "2 idiomas extras. Proficiência em 2 perícias (Arcana/Religião/História/Natureza) — dobradas.", "dado": "", "custo_mana": 0}],
                2:  [{"nome": "Canalizar Divindade (Ler Pensamentos)", "descricao": "Ação: criatura em 18m, save de SAB; falha = lê pensamentos por 1 min.", "dado": "", "custo_mana": 0}],
                6:  [{"nome": "Ler Pensamentos Aprimorado", "descricao": "Após ler pensamentos, pode lançar Sugestão sem gastar slot.", "dado": "", "custo_mana": 0}],
                8:  [{"nome": "Dano Potencializado (Conhecimento)", "descricao": "1×/turno: truque de dano causa +1d8 (sobe a 2d8 no 14º).", "dado": "1d8", "custo_mana": 0}],
                17: [{"nome": "Visões do Passado", "descricao": "1 min de meditação: ganha visões sobre criatura ou objeto.", "dado": "", "custo_mana": 0}],
            },
        },
        "Luz": {
            "descricao": "Clérigo de divindades solares e radiantes.",
            "features": {
                1:  [
                    {"nome": "Truque Bônus (Chamas Sagradas)", "descricao": "Aprende Chamas Sagradas (sacred flame) sem ocupar slot de truque.", "dado": "1d8", "custo_mana": 0},
                    {"nome": "Bandeira de Aviso", "descricao": "Reação ao ser atingido: impõe desvantagem no ataque. Usos = mod. SAB por descanso longo.", "dado": "", "custo_mana": 0},
                ],
                2:  [{"nome": "Canalizar Divindade (Radiância do Amanhecer)", "descricao": "Ação: esfera de luz 9m raio; criaturas hostis fazem save de CON ou 2d10+nv. dano radiante.", "dado": "2d10", "custo_mana": 0}],
                6:  [{"nome": "Bandeira de Aviso Aprimorada", "descricao": "Bandeira de Aviso também protege aliados em 9m.", "dado": "", "custo_mana": 0}],
                8:  [{"nome": "Golpe Divino (Luz)", "descricao": "1×/turno: truque/atk causa +1d8 radiante (sobe a 2d8 no 14º).", "dado": "1d8", "custo_mana": 0}],
                17: [{"nome": "Coroa da Luz", "descricao": "Ação: 1 min de coroa luminosa; magias hostis com save sofrem desvantagem perto.", "dado": "", "custo_mana": 0}],
            },
        },
        "Natureza": {
            "descricao": "Clérigo druídico, ponte entre fé e natureza.",
            "features": {
                1:  [
                    {"nome": "Acólito da Natureza", "descricao": "Truque de druida bônus + proficiência em uma perícia (Natureza, Sobrevivência, Adestramento).", "dado": "", "custo_mana": 0},
                    {"nome": "Treinamento em Armadura Pesada", "descricao": "Proficiência em armaduras pesadas.", "dado": "", "custo_mana": 0},
                ],
                2:  [{"nome": "Canalizar Divindade (Encantar Animais e Plantas)", "descricao": "Ação: animais/plantas em 9m, save de SAB; falha = Enfeitiçado por 1 min.", "dado": "", "custo_mana": 0}],
                6:  [{"nome": "Servidor da Natureza", "descricao": "Tropeça e mata animais menores com facilidade. Vantagem em saves contra magias de Encantamento.", "dado": "", "custo_mana": 0}],
                8:  [{"nome": "Golpe Divino (Natureza)", "descricao": "1×/turno: ataque com arma causa +1d8 elemental (escolha) (sobe a 2d8 no 14º).", "dado": "1d8", "custo_mana": 0}],
                17: [{"nome": "Mestre da Natureza", "descricao": "Comanda criaturas Enfeitiçadas por Encantar Animais e Plantas com mais precisão.", "dado": "", "custo_mana": 0}],
            },
        },
        "Tempestade": {
            "descricao": "Clérigo de deuses do raio e do trovão.",
            "features": {
                1:  [
                    {"nome": "Treinamento em Armadura Pesada e Marciais (Tempestade)", "descricao": "Proficiência em armaduras pesadas e armas marciais.", "dado": "", "custo_mana": 0},
                    {"nome": "Cólera Temporal", "descricao": "Reação ao ser atingido por inimigo em 1,5m: +2d8 dano de trovão a ele. Usos = mod. SAB por descanso longo.", "dado": "2d8", "custo_mana": 0},
                ],
                2:  [{"nome": "Canalizar Divindade (Trovão Destrutivo)", "descricao": "Ação: criaturas em 9m fazem save de CON; falha = 2d6 + nv. dano trovão (sucesso = metade).", "dado": "2d6", "custo_mana": 0}],
                6:  [{"nome": "Resistência da Tempestade", "descricao": "Resistência a dano de relâmpago e trovão.", "dado": "", "custo_mana": 0}],
                8:  [{"nome": "Golpe Divino (Tempestade)", "descricao": "1×/turno: ataque com arma causa +1d8 trovão (sobe a 2d8 no 14º).", "dado": "1d8", "custo_mana": 0}],
                17: [{"nome": "Trovão Estrondoso", "descricao": "Quando crítica, dano de trovão/relâmpago é maximizado.", "dado": "", "custo_mana": 0}],
            },
        },
        "Ardil": {
            "descricao": "Clérigo de deuses trapaceiros e ladinos.",
            "features": {
                1:  [{"nome": "Bênção do Trapaceiro", "descricao": "Ação: toca um aliado, dá vantagem em testes de DES (Furtividade) por 1 hora.", "dado": "", "custo_mana": 0}],
                2:  [{"nome": "Canalizar Divindade (Invocar Duplicação)", "descricao": "Ação: cria uma ilusão sua até 9m que pode falar e mover por 1 min.", "dado": "", "custo_mana": 0}],
                6:  [{"nome": "Bênção do Trapaceiro Aprimorada", "descricao": "Pode usar Bênção do Trapaceiro como ação bônus em 9m. Múltiplos alvos.", "dado": "", "custo_mana": 0}],
                8:  [{"nome": "Golpe Divino (Ardil)", "descricao": "1×/turno: ataque com arma causa +1d8 veneno (sobe a 2d8 no 14º).", "dado": "1d8", "custo_mana": 0}],
                17: [{"nome": "Trapaça Improvisada", "descricao": "Pode usar Canalizar Divindade duas vezes seguidas se inspirado.", "dado": "", "custo_mana": 0}],
            },
        },
    },

    # ── Druida (Círculo Druídico — nv. 2) ──────────────────────────────────
    "Círculo Druídico": {
        "Terra": {
            "descricao": "Druida do círculo dos sábios e dos lugares sagrados.",
            "features": {
                2:  [
                    {"nome": "Recuperação Natural", "descricao": "Em descanso curto: recupera slots de magia até metade do nível (1x/dia).", "dado": "", "custo_mana": 0},
                    {"nome": "Magias do Círculo (Terra)", "descricao": "Ganha magias adicionais ligadas ao terreno escolhido (Ártico, Costa, Deserto, etc.).", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Passos da Terra", "descricao": "Move-se em terreno difícil mágico sem penalidade. Imune a magias que retardam.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Refúgio da Natureza", "descricao": "Imune a doenças, venenos e proteção contra envelhecimento.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Santuário da Natureza", "descricao": "Bestas e plantas não atacam você a menos que provocadas.", "dado": "", "custo_mana": 0}],
            },
        },
        "Lua": {
            "descricao": "Druida especializado em Forma Selvagem de combate.",
            "features": {
                2:  [
                    {"nome": "Forma Selvagem do Combate", "descricao": "Pode adotar Forma Selvagem com CR ≤ 1 já no 2º nível. Forma Selvagem como ação bônus.", "dado": "", "custo_mana": 0},
                    {"nome": "Magias Lunares", "descricao": "Pode lançar Cura Ferimentos como ação bônus enquanto em Forma Selvagem.", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Forma Selvagem Primal", "descricao": "Suas formas selvagens contam como mágicas para resistência a dano.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Golpes Elementais", "descricao": "Ataques em Forma Selvagem causam +1d6 dano elemental escolhido.", "dado": "1d6", "custo_mana": 0}],
                14: [{"nome": "Mudança Imediata", "descricao": "Forma Selvagem como reação ao receber dano.", "dado": "", "custo_mana": 0}],
            },
        },
    },

    # ── Monge (Tradição Monástica — nv. 3) ──────────────────────────────────
    "Tradição Monástica": {
        "Mão Aberta": {
            "descricao": "Tradição clássica do monge artista marcial puro.",
            "features": {
                3:  [{"nome": "Técnicas da Mão Aberta", "descricao": "Ao usar Rajada de Golpes: pode derrubar, empurrar 4,5m, ou impedir reações do alvo.", "dado": "", "custo_mana": 0}],
                6:  [{"nome": "Corpo Curativo", "descricao": "Ação: cura nv. monge × 3 PV em si.", "dado": "", "custo_mana": 0}],
                11: [{"nome": "Trinta Anos de Tranquilidade", "descricao": "Ao fim do descanso longo, recebe efeito de Santuário gratuito.", "dado": "", "custo_mana": 0}],
                17: [{"nome": "Palma Vibrante Trêmula", "descricao": "1 Ki: atinge criatura com vibração; até 23 dias depois, ação para detonar e causar 10d10 necrótico (save CON metade).", "dado": "10d10", "custo_mana": 0}],
            },
        },
        "Sombras": {
            "descricao": "Tradição do monge furtivo, manipulador de sombras.",
            "features": {
                3:  [{"nome": "Artes Sombrias", "descricao": "Conjura Mãos Mágicas, Escuridão, Silêncio, Visão no Escuro, Passar sem Deixar Rastro com Ki.", "dado": "", "custo_mana": 0}],
                6:  [{"nome": "Salto Sombrio", "descricao": "Em áreas de escuridão: teletransporta-se até 18m para outra área sombra como ação bônus.", "dado": "", "custo_mana": 0}],
                11: [{"nome": "Manto Sombrio", "descricao": "Em luz fraca/escuridão: torna-se invisível como ação.", "dado": "", "custo_mana": 0}],
                17: [{"nome": "Oportunista", "descricao": "Reação: faz um ataque corpo-a-corpo contra criatura adjacente que foi atingida por um aliado.", "dado": "", "custo_mana": 0}],
            },
        },
        "Quatro Elementos": {
            "descricao": "Tradição do monge que canaliza elementais via Ki.",
            "features": {
                3:  [
                    {"nome": "Discípulo dos Elementos", "descricao": "Aprende uma Disciplina Elemental + a básica (Elemental Attunement).", "dado": "", "custo_mana": 0},
                    {"nome": "Conjuração Elemental", "descricao": "Gasta Ki para conjurar efeitos elementais (Sopro de Fogo, Punho de Pedra, etc.).", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Disciplina Elemental Adicional", "descricao": "Aprende mais 1 Disciplina Elemental.", "dado": "", "custo_mana": 0}],
                11: [{"nome": "Disciplina Elemental Avançada", "descricao": "Aprende mais 1 Disciplina (até nv. 5 de magia equivalente).", "dado": "", "custo_mana": 0}],
                17: [{"nome": "Mestre dos Elementos", "descricao": "Aprende todas as Disciplinas Elementais restantes.", "dado": "", "custo_mana": 0}],
            },
        },
    },

    # ── Ladino (Arquétipo de Ladrão — nv. 3) ───────────────────────────────
    "Arquétipo de Ladrão": {
        "Ladrão": {
            "descricao": "Arquétipo clássico de ladrão ágil e versátil.",
            "features": {
                3:  [
                    {"nome": "Mãos Rápidas", "descricao": "Ação Ardilosa pode incluir Prestidigitação, Roubar (Sleight of Hand), ou usar item.", "dado": "", "custo_mana": 0},
                    {"nome": "Acrobata de Combate", "descricao": "Subir e descer não custa deslocamento extra. Salto melhorado.", "dado": "", "custo_mana": 0},
                ],
                9:  [{"nome": "Ladrão Supremo", "descricao": "Vantagem em testes contra armadilhas e portas trancadas.", "dado": "", "custo_mana": 0}],
                13: [{"nome": "Uso Mágico de Itens", "descricao": "Pode usar itens mágicos como pergaminhos e varinhas mesmo de outras classes.", "dado": "", "custo_mana": 0}],
                17: [{"nome": "Reflexos do Ladrão", "descricao": "Tem 2 turnos no primeiro round (1 turno de iniciativa real, outro de iniciativa-PROF).", "dado": "", "custo_mana": 0}],
            },
        },
        "Assassino": {
            "descricao": "Ladrão letal especializado em mortes súbitas.",
            "features": {
                3:  [
                    {"nome": "Maestria do Disfarce", "descricao": "Proficiência em Kit de Envenenamento e Kit de Disfarce.", "dado": "", "custo_mana": 0},
                    {"nome": "Assassinato", "descricao": "Vantagem em atk contra alvo que ainda não agiu. Acerto contra surpreso = crítico.", "dado": "", "custo_mana": 0},
                ],
                9:  [{"nome": "Identidade Falsa", "descricao": "Pode criar identidades falsas críveis (1 semana para preparar).", "dado": "", "custo_mana": 0}],
                13: [{"nome": "Impostor", "descricao": "Pode imitar voz, modo de falar e comportamento de outra pessoa com perícia.", "dado": "", "custo_mana": 0}],
                17: [{"nome": "Golpe da Morte", "descricao": "Ao acertar atk com surpresa, save de CON ou dano dobrado.", "dado": "", "custo_mana": 0}],
            },
        },
        "Trapaceiro Arcano": {
            "descricao": "Ladrão que combina furtividade com magia arcana.",
            "features": {
                3:  [
                    {"nome": "Conjuração (Trapaceiro Arcano)", "descricao": "Conjura magias da lista de mago (foco em Encantamento/Ilusão). Atributo: INT.", "dado": "", "custo_mana": 0},
                    {"nome": "Mão Mística (Trapaceiro)", "descricao": "Aprende Mãos Mágicas (Mage Hand) que é invisível e usa Furtividade.", "dado": "", "custo_mana": 0},
                ],
                9:  [{"nome": "Truques da Mão Mística", "descricao": "Pode usar Mãos Mágicas para roubar bolsos, abrir trancas, sabotar à distância.", "dado": "", "custo_mana": 0}],
                13: [{"nome": "Versátil (Trapaceiro)", "descricao": "Pode trocar 1 magia conhecida quando sobe de nível.", "dado": "", "custo_mana": 0}],
                17: [{"nome": "Ladrão Élditch", "descricao": "Mãos Mágicas pode entregar magias de truque à distância.", "dado": "", "custo_mana": 0}],
            },
        },
    },

    # ── Mago (Tradição Arcana — nv. 2) — 8 escolas ─────────────────────────
    "Tradição Arcana": {
        "Abjuração": {
            "descricao": "Escola da proteção e bloqueio mágico.",
            "features": {
                2:  [
                    {"nome": "Salvaguarda do Abjurador", "descricao": "Ao conjurar magia de Abjuração: ganha pool de PV temporários = 2× nv. magia + INT.", "dado": "", "custo_mana": 0},
                    {"nome": "Recuperação Arcana (Abjuração)", "descricao": "Aprende a copiar magias de Abjuração no livro por metade do tempo/custo.", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Resistência Mágica Projetada", "descricao": "Reação: aliado em 9m alvo de magia pode usar SEU bônus de save em vez do dele.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Quebra de Magia Aprimorada", "descricao": "Dispelar magia tem +PROF e funciona automaticamente contra magias até nv. 3.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Resistência a Magia", "descricao": "Vantagem em saves contra magias.", "dado": "", "custo_mana": 0}],
            },
        },
        "Adivinhação": {
            "descricao": "Escola da clarividência e leitura do destino.",
            "features": {
                2:  [
                    {"nome": "Lampejos de Adivinhação", "descricao": "Após descanso longo: rola 2d20 e guarda. Pode substituir QUALQUER d20 (atk/teste/save) por um dos guardados.", "dado": "2d20", "custo_mana": 0},
                    {"nome": "Reservas de Adivinhação", "descricao": "Aprende a copiar magias de Adivinhação por metade do custo/tempo.", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Visão Aprofundada", "descricao": "Lampejos guardados sobem para 3d20 por descanso longo.", "dado": "3d20", "custo_mana": 0}],
                10: [{"nome": "Terceiro Olho", "descricao": "Visão Verdadeira por 1 min sem gastar slot. 1×/descanso curto.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Lampejos Aprimorados", "descricao": "Lampejos sobem para 4d20 por descanso longo.", "dado": "4d20", "custo_mana": 0}],
            },
        },
        "Conjuração": {
            "descricao": "Escola de invocação e manipulação de seres.",
            "features": {
                2:  [
                    {"nome": "Conjurador Minucioso", "descricao": "Aprende a copiar magias de Conjuração por metade do custo/tempo.", "dado": "", "custo_mana": 0},
                    {"nome": "Conjurar Item Menor", "descricao": "Ação: invoca item não-mágico pesando até 5kg na mão por 1 hora.", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Conjuração Veloz", "descricao": "Magias de Conjuração de 1 ação viram 1 ação bônus, 1×/descanso curto.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Teletransporte Pequeno", "descricao": "Ação bônus: teleporta-se até 9m a um local visível, 1×/turno.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Aliado Convocado Aprimorado", "descricao": "Criaturas convocadas por suas magias ganham +CD AC e +AC dano.", "dado": "", "custo_mana": 0}],
            },
        },
        "Encantamento": {
            "descricao": "Escola da manipulação mental e charme.",
            "features": {
                2:  [
                    {"nome": "Sussurros Encantadores", "descricao": "Aprende a copiar magias de Encantamento por metade do custo/tempo.", "dado": "", "custo_mana": 0},
                    {"nome": "Lapso de Memória", "descricao": "Quando enfeitiça humanoide, sua vítima esquece o evento depois.", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Mente Dividida", "descricao": "Mantém concentração em 2 magias de Encantamento simultaneamente.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Mago Encantador", "descricao": "Vantagem em saves contra Encantamento. Pode lançar uma cópia da magia recebida no atacante.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Encantamento Alterado", "descricao": "Quando enfeitiça humanoide, pode alterar sua personalidade durante a duração.", "dado": "", "custo_mana": 0}],
            },
        },
        "Evocação": {
            "descricao": "Escola do dano elemental direto.",
            "features": {
                2:  [
                    {"nome": "Esculpir Magias", "descricao": "Em magias de Evocação com save de DEX: até 1+nv. magia aliados na área passam automaticamente sem sofrer dano.", "dado": "", "custo_mana": 0},
                    {"nome": "Recuperação Arcana (Evocação)", "descricao": "Aprende a copiar magias de Evocação por metade do custo/tempo.", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Truque Potente", "descricao": "Magias de truque de Evocação causam dano + INT mesmo em falha (se aplicável).", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Truque Empoderado", "descricao": "Soma INT ao dano de TODOS os truques de Evocação.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Sobrecarga", "descricao": "1×/descanso longo: maximiza o dano da próxima magia de Evocação de nv. 1-5.", "dado": "", "custo_mana": 0}],
            },
        },
        "Ilusão": {
            "descricao": "Escola da falsidade e do engano.",
            "features": {
                2:  [
                    {"nome": "Ilusionista Melhorado", "descricao": "Aprende a copiar magias de Ilusão por metade do custo/tempo.", "dado": "", "custo_mana": 0},
                    {"nome": "Ilusão Menor Aprimorada", "descricao": "Pode lançar Ilusão Menor (Minor Illusion) com ambos os componentes (som E imagem).", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Ilusão Maleável", "descricao": "Pode alterar a forma/conteúdo de ilusões em andamento como ação.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Auto-Ilusão", "descricao": "Reação ao ser atingido: cria duplicata ilusória que assume o dano.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Realidade Ilusória", "descricao": "Suas ilusões podem se tornar reais por 1 min (objetos não-mágicos).", "dado": "", "custo_mana": 0}],
            },
        },
        "Necromancia": {
            "descricao": "Escola da morte, dos mortos e da vida drenada.",
            "features": {
                2:  [
                    {"nome": "Macabro", "descricao": "Aprende a copiar magias de Necromancia por metade do custo/tempo.", "dado": "", "custo_mana": 0},
                    {"nome": "Colhedor de Ceifa", "descricao": "Quando mata criatura com magia de Necromancia: ganha PV temporários = 2× nv. magia + INT.", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Comando dos Mortos-Vivos", "descricao": "Aprende Animar Mortos. Pode controlar mais esqueletos/zumbis que o normal.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Resiliência Insidiosa", "descricao": "Resistência a dano necrótico. Limite máximo de PV não pode ser reduzido.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Senhor dos Mortos-Vivos", "descricao": "Esqueletos e zumbis sob seu comando têm +PV e +dano.", "dado": "", "custo_mana": 0}],
            },
        },
        "Transmutação": {
            "descricao": "Escola da mudança de forma e propriedades.",
            "features": {
                2:  [
                    {"nome": "Aluno da Transmutação", "descricao": "Aprende a copiar magias de Transmutação por metade do custo/tempo.", "dado": "", "custo_mana": 0},
                    {"nome": "Pedra Transmutadora", "descricao": "Cria pedra mágica: dá um benefício escolhido (visão escuro/cativeiro/CON/resistência) por 8h.", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Recuperação do Transmutador", "descricao": "Pode usar Pedra Transmutadora para conjurar Cura Ferimentos nv. 5.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Mestre Transmutador", "descricao": "Usa Pedra Transmutadora para conjurar Polimorfismo (em si) sem slot.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Transmutação Suprema", "descricao": "Pedra Transmutadora ganha efeitos extras: rejuvenescimento, restaurar atributo, etc.", "dado": "", "custo_mana": 0}],
            },
        },
    },

    # ── Feiticeiro (Origem de Feiticeiro — nv. 1) ──────────────────────────
    "Origem de Feiticeiro": {
        "Linhagem Dracônica": {
            "descricao": "Poder vem de ancestral dragão.",
            "features": {
                1:  [
                    {"nome": "Ancestral Dracônico", "descricao": "Escolhe a cor do ancestral (vermelho/azul/verde/branco/preto/ouro/prata/etc) — define o tipo de dano resistido.", "dado": "", "custo_mana": 0},
                    {"nome": "Resistência Dracônica", "descricao": "+1 PV/nível. CA = 13 + DES quando sem armadura.", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Magia Elemental Afim", "descricao": "Magias do tipo de dano do ancestral causam +CAR de dano. Custo de mana reduzido em 1.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Asas Dracônicas", "descricao": "Ação bônus: faz crescer asas (mov. voo 18m) por 1 min.", "dado": "", "custo_mana": 0}],
                18: [{"nome": "Presença Dracônica", "descricao": "Ação: 1 min de aura de medo/admiração (3 pontos de feitiçaria).", "dado": "", "custo_mana": 0}],
            },
        },
        "Magia Selvagem": {
            "descricao": "Poder caótico e imprevisível das tempestades arcanas.",
            "features": {
                1:  [
                    {"nome": "Surto de Magia Selvagem", "descricao": "Quando conjura magia de nv. 1+: rola d20; em 1, mestre rola na tabela de Surto Selvagem (efeito aleatório).", "dado": "1d20", "custo_mana": 0},
                    {"nome": "Marés do Caos", "descricao": "1×/descanso longo: vantagem em 1 atk/teste/save. Mestre pode acionar Surto Selvagem depois.", "dado": "", "custo_mana": 0},
                ],
                6:  [{"nome": "Esculpir o Caos", "descricao": "Gasta 2 PF para rolar na tabela de Surto Selvagem manualmente.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Recuperação Mágica (Selvagem)", "descricao": "Após Surto Selvagem, recupera 2d4 de Pontos de Feitiçaria.", "dado": "2d4", "custo_mana": 0}],
                18: [{"nome": "Magia Espontânea", "descricao": "Quando rola Surto Selvagem: pode escolher qualquer resultado da tabela.", "dado": "", "custo_mana": 0}],
            },
        },
    },

    # ── Bruxo (Patrono Sobrenatural — nv. 1) ───────────────────────────────
    "Patrono Sobrenatural": {
        "Arquifada": {
            "descricao": "Patrono é um senhor/senhora do reino feérico.",
            "features": {
                1:  [{"nome": "Presença Feérica", "descricao": "Ação: criaturas em cone 3m fazem save de SAB; falha = Enfeitiçado OU Amedrontado por 1 turno.", "dado": "", "custo_mana": 0}],
                6:  [{"nome": "Refúgio Feérico", "descricao": "Reação ao receber dano: teleporta-se 18m para outra área visível. Usos = PROF/descanso curto.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Visão Feérica", "descricao": "Imune a Enfeitiçado. Magias e itens não afetam sua mente.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Apenas Para Mim", "descricao": "Ação: criatura humanoide alvo, save SAB; falha = Enfeitiçada e fica entorpecida em transe.", "dado": "", "custo_mana": 0}],
            },
        },
        "Senhor Lich": {
            "descricao": "Patrono é um senhor lich, demônio ou diabo.",
            "features": {
                1:  [{"nome": "Resistência Sombria", "descricao": "Quando reduz humanoide a 0 PV, ganha PV temporários = nv. bruxo + CAR.", "dado": "", "custo_mana": 0}],
                6:  [{"nome": "Maldição do Patrono Sombrio", "descricao": "Ao errar atk contra criatura, próximo atk dela contra você falha.", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Resistência Aprimorada", "descricao": "Resistência a 1 tipo de dano de sua escolha (entre fogo/frio/elétrico/necrótico).", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Hurl Through Hell", "descricao": "Ao acertar atk: alvo passa 1 turno no inferno; 10d10 dano psíquico ao voltar.", "dado": "10d10", "custo_mana": 0}],
            },
        },
        "Grande Antigo": {
            "descricao": "Patrono é uma entidade alienígena/cósmica.",
            "features": {
                1:  [{"nome": "Telepatia Tenebrosa", "descricao": "Comunicação telepática com qualquer criatura em 9m.", "dado": "", "custo_mana": 0}],
                6:  [{"nome": "Vingança do Grande Antigo", "descricao": "Quando alguém te ataca: dano psíquico = 1+CAR ao atacante (reação).", "dado": "", "custo_mana": 0}],
                10: [{"nome": "Pensamento Inquebrantável", "descricao": "Imune a Enfeitiçado e Amedrontado. Vantagem em saves contra outras magias mentais.", "dado": "", "custo_mana": 0}],
                14: [{"nome": "Mestrado do Grande Antigo", "descricao": "Ação: força criatura visível em 18m a fazer atk/save por você (CAR vs INT/CAR).", "dado": "", "custo_mana": 0}],
            },
        },
    },

    # ── Bruxo (Bênção do Pacto — nv. 3) ────────────────────────────────────
    "Bênção do Pacto": {
        "Pacto da Lâmina": {
            "descricao": "Pacto que dá uma arma mágica vinculada.",
            "features": {
                3: [{"nome": "Arma do Pacto", "descricao": "Cria arma mágica em 1 hora ritual. Atk usa CAR. Pode invocar/dispensar como ação.", "dado": "", "custo_mana": 0}],
            },
        },
        "Pacto do Tomo": {
            "descricao": "Pacto que dá um livro com truques mágicos extras.",
            "features": {
                3: [{"nome": "Livro das Sombras", "descricao": "Recebe um livro com 3 truques de qualquer classe. Pode lançá-los à vontade enquanto o livro está em mãos.", "dado": "", "custo_mana": 0}],
            },
        },
        "Pacto da Corrente": {
            "descricao": "Pacto que dá um familiar único.",
            "features": {
                3: [{"nome": "Encontrar Familiar Aprimorado", "descricao": "Aprende Encontrar Familiar; pode invocar criaturas como imp, pseudodragão, quasit, sprite. Familiar pode atacar com sua reação.", "dado": "", "custo_mana": 0}],
            },
        },
    },
}


def _register_archetypes() -> None:
    """
    Module-load: popula FEATURE_VARIANTS e CLASS_FEATURE_DESCS a partir de
    ARCHETYPE_FEATURES. Mantém uma única fonte de verdade pros arquétipos.
    """
    for feat_name, archetypes in ARCHETYPE_FEATURES.items():
        # Registra a feature-pai como subescolha de arquétipo.
        if feat_name not in FEATURE_VARIANTS:
            FEATURE_VARIANTS[feat_name] = {
                "pick": 1,
                "pick_label": "arquétipo",
                "options": {
                    arch_name: {
                        "descricao": data.get("descricao", ""),
                        "narrative_hint": "passive",
                    }
                    for arch_name, data in archetypes.items()
                },
            }
        # Registra as descrições de cada sub-feature.
        for arch_name, data in archetypes.items():
            for lvl, sub_feats in (data.get("features") or {}).items():
                for sf in sub_feats:
                    name = sf.get("nome")
                    if not name:
                        continue
                    # Só registra se ainda não existir (não sobrescreve descrições
                    # personalizadas já em CLASS_FEATURE_DESCS).
                    if name not in CLASS_FEATURE_DESCS:
                        CLASS_FEATURE_DESCS[name] = {
                            "descricao":  sf.get("descricao", ""),
                            "custo_mana": int(sf.get("custo_mana", 0) or 0),
                            "dado":       sf.get("dado", ""),
                        }


_register_archetypes()


def _apply_archetype_features(char: dict, archetype_feature: str) -> list[str]:
    """
    Concede ao personagem todas as sub-features do arquétipo escolhido cujo
    nível de desbloqueio ≤ nível atual do char. Não duplica. Retorna lista
    de nomes recém-adicionados.

    Chamado de set_feature_choice (logo após escolher um arquétipo) e de
    _apply_class_features (quando o char sobe e novas sub-features liberam).
    """
    archetype = _get_feature_choice(char, archetype_feature)
    if not isinstance(archetype, str) or not archetype:
        return []
    arch_table = ARCHETYPE_FEATURES.get(archetype_feature, {}).get(archetype)
    if not arch_table:
        return []

    nivel    = int((char.get("sheet") or {}).get("nivel", 1) or 1)
    existing = {h.get("nome", "").lower() for h in char.get("habilidades", [])}
    added: list[str] = []
    for lvl_unlock, sub_feats in (arch_table.get("features") or {}).items():
        if lvl_unlock > nivel:
            continue
        for sf in sub_feats:
            name = sf.get("nome", "")
            if not name or name.lower() in existing:
                continue
            char.setdefault("habilidades", []).append({
                "nome":       name,
                "descricao":  sf.get("descricao", ""),
                "custo_mana": int(sf.get("custo_mana", 0) or 0),
                "dado":       sf.get("dado", ""),
            })
            existing.add(name.lower())
            added.append(name)
    return added


def rules_catalog() -> dict:
    """
    Todas as tabelas de regra que o wizard e os editores usam, geradas das
    MESMAS funções do motor.

    Elas existiam copiadas no menu.js e no game.js, e as cópias já discordavam:
    círculo máximo de magia pela metade do nível para toda classe (paladino de
    nível 3 com magia de 2º círculo), incremento de atributo só nos níveis 4,
    8, 12, 16 e 19 (o guerreiro também ganha no 6 e no 14, o ladino no 10).
    Uma rota que devolve o que o motor calcula acaba com a divergência na raiz:
    não há mais segunda tabela para ficar para trás.
    """
    niveis = range(1, 21)
    classes = {}
    for classe, info in CLASS_DATA.items():
        ficha = lambda n, c=classe: {"classe": c, "nivel": n}
        limites = [_limite_de_magias(ficha(n)) for n in niveis]
        classes[classe] = {
            "hit_die":         info.get("hit_die", 8),
            "conjurador":      classe in CASTER_CLASSES,
            "niveis_asi":      sorted(_niveis_asi(classe)),
            "mana":            [_max_mana_for(classe, n) for n in niveis],
            "nivel_max_magia": [_nivel_maximo_de_magia(ficha(n)) for n in niveis],
            "truques":         [(l or {}).get("truques", 0) for l in limites],
            "magias":          [(l or {}).get("magias", 0) for l in limites] if limites[0] is not None
                               else None,
        }
    return {
        "xp_por_nivel":           list(XP_THRESHOLDS[:20]),
        "proficiencia_por_nivel": [_proficiency_bonus(n) for n in niveis],
        "custo_mana_por_nivel":   {str(k): v for k, v in SPELL_MANA_COST.items()},
        "pontos_por_asi":         _PONTOS_POR_ASI,
        "teto_atributo":          _TETO_ATRIBUTO,
        "classes":                classes,
    }


# Campos que definem O QUE o personagem é. Durante o jogo quem os muda são as
# telas (nível, Grimório, Mochila) pelas ferramentas do motor; um editor que
# os gravasse livremente contornaria todas elas.
_CAMPOS_DE_CONSTRUCAO = (
    "classe", "raca", "nivel", "xp", "xp_proximo", "proficiencia",
    "forca", "destreza", "constituicao", "inteligencia", "sabedoria", "carisma",
    "ca", "vida_max", "mana_max", "hit_die", "equipamentos",
    "feature_choices", "asi_pontos_gastos", "hit_dice_remaining",
    "ultimo_descanso_longo", "ultimo_descanso_curto", "exaustao",
)


def normalize_edited_character(novo: dict, antigo: dict | None,
                               correcao_manual: bool = False) -> list[str]:
    """
    Aplica as regras a um personagem que um editor (menu ou "Editar Ficha
    Completa") vai gravar. Muta `novo`; devolve os campos que foram mantidos
    como estavam (para o editor avisar).

    Sem correção manual, num personagem JÁ salvo e jogável, os campos de
    construção e as habilidades voltam ao valor gravado: os editores os
    mostram só para leitura, e isto protege também de um cliente antigo em
    cache. Com correção manual (o "Modo de correção" declarado), aceita.

    Sempre — com ou sem correção — ajusta o que não pode ficar incoerente: a
    reserva de dados de vida entre 0 e o nível, vida e mana atuais abaixo do
    máximo, o nível de cada magia gravado na ficha, e item tirado da mochila
    sai do corpo.
    """
    if not isinstance(novo, dict):
        return []
    novo.pop("correcao_manual", None)
    # Campos gravados como null viram o padrão (a mesma migração da carga).
    memory._migrate_sheet_fields(novo)
    s = novo.get("sheet")
    if not isinstance(s, dict):
        return []

    mantidos = []
    jogavel = (s.get("classe") or "").lower() not in ("", "npc")
    antiga = (antigo or {}).get("sheet") if isinstance(antigo, dict) else None
    if jogavel and isinstance(antiga, dict) and not correcao_manual:
        for campo in _CAMPOS_DE_CONSTRUCAO:
            if campo in antiga and s.get(campo) != antiga[campo]:
                s[campo] = copy.deepcopy(antiga[campo])
                mantidos.append(campo)
        habs_antigas = antigo.get("habilidades")
        if isinstance(habs_antigas, list) and novo.get("habilidades") != habs_antigas:
            novo["habilidades"] = copy.deepcopy(habs_antigas)
            mantidos.append("habilidades")
    if jogavel and isinstance(antiga, dict):
        # Item tirado da mochila pelo editor sai do corpo, como no remove_item.
        # Vale também na correção: é coerência, não construção.
        antes = {_norm_txt(i.get("nome", "")) for i in (antigo.get("inventario") or [])
                 if isinstance(i, dict)}
        depois = {_norm_txt(i.get("nome", "")) for i in (novo.get("inventario") or [])
                  if isinstance(i, dict)}
        equip = s.get("equipamentos") or {}
        soltou = False
        for slot, item in list(equip.items()):
            if item and _norm_txt(item) in antes and _norm_txt(item) not in depois:
                equip[slot] = None
                soltou = True
        if soltou:
            mantidos.append("equipamentos (item removido da mochila)")
            # Só recalcula quando algo saiu do corpo: recalcular sempre
            # apagaria uma CA posta pelo mestre (Armadura Arcana, anel).
            _recalculate_ca(novo)

    # Coerência, sempre.
    if "hit_dice_remaining" in s:
        s["hit_dice_remaining"] = _reserva_de_dados(s)[0]
    for atual, maximo in (("vida_atual", None), ("mana_atual", "mana_max")):
        if atual not in s:
            continue
        try:
            valor = int(s.get(atual) or 0)
            teto = _hp_max_efetivo(s) if atual == "vida_atual" else int(s.get(maximo) or 0)
        except (TypeError, ValueError):
            continue
        s[atual] = max(0, min(valor, teto))
    for h in (novo.get("habilidades") or []):
        if isinstance(h, dict) and _e_magia(h) and not isinstance(h.get("nivel_magia"), int):
            h["nivel_magia"] = _nivel_da_magia(h)
    return mantidos


def reconcile_character_archetypes(char: dict) -> list[str]:
    """
    Garante que um personagem tenha TODAS as sub-features de arquétipo
    correspondentes às suas escolhas (sheet.feature_choices) e ao nível
    atual. Idempotente — seguro chamar várias vezes.

    Usado no save da campanha pelo editor: o picker do editor grava só a
    escolha localmente; esta função materializa as sub-features no backend
    antes de persistir. NÃO chama save_campaign (só muta o dict).

    Retorna lista de nomes de sub-features adicionadas.
    """
    if not isinstance(char, dict) or not char.get("sheet"):
        return []
    added: list[str] = []
    for arch_feat in ARCHETYPE_FEATURES.keys():
        if _get_feature_choice(char, arch_feat):
            added.extend(_apply_archetype_features(char, arch_feat))
    # Sub-features podem mexer na CA (ex.: Resistência Dracônica). Recalcula
    # se algo foi concedido.
    if added:
        try:
            _recalculate_ca(char)
        except Exception:
            pass
    return added


# Nomes em português E em inglês: as armas dos monstros chegam do stat block do
# Open5e ("scimitar", "shortbow"). Só com os nomes em português, o goblin
# atacava de cimitarra e de arco curto com a Força (8, -1) em vez da Destreza
# (14, +2), e acertava com +1 em vez do +4 do livro. A rapieira do ladino e do
# bardo também caía na Força: a lista tinha "rapier", não "rapieira".
RANGED_WEAPONS = {
    "arco", "arco curto", "arco longo", "besta", "besta leve", "besta de mão",
    "besta pesada", "funda", "zarabatana", "dardo", "virote", "flecha", "shuriken",
    "shortbow", "longbow", "crossbow", "sling", "blowgun", "dart",
}
FINESSE_WEAPONS = {
    "adaga", "espada curta", "rapieira", "rapier", "florete", "cimitarra", "chicote",
    "sabre", "espada de duelo",
    "dagger", "shortsword", "short sword", "scimitar", "whip",
}
# Armas leves (SRD): as que permitem o ataque da outra mão como ação bônus.
LIGHT_WEAPONS = {
    "adaga", "espada curta", "cimitarra", "machadinha", "martelo leve", "foice curta", "clava",
    "dagger", "shortsword", "short sword", "scimitar", "handaxe", "light hammer", "sickle", "club",
}


def _arma_da_outra_mao(ch: dict, ja_usada: str) -> str:
    """A outra arma leve: a secundária equipada, outra do inventário, ou a mesma se houver duas."""
    eq = ((ch.get("sheet") or {}).get("equipamentos") or {})
    candidatas = [eq.get("arma_secundaria") or ""] + [
        (i.get("nome") or "") for i in (ch.get("inventario") or []) if isinstance(i, dict)]
    for c in candidatas:
        if c and _arma_leve(c) and _norm_txt(c) != _norm_txt(ja_usada):
            return c
    for i in ch.get("inventario") or []:
        if (isinstance(i, dict) and _norm_txt(i.get("nome", "")) == _norm_txt(ja_usada)
                and int(i.get("qtd", 1) or 1) >= 2):
            return i["nome"]
    return ""


def _arma_leve(nome: str) -> bool:
    a = _itens.arma(nome)
    if a:
        return "leve" in a["propriedades"] and not a["distancia"]
    n = _norm_txt(nome or "")
    return any(_norm_txt(w) in n for w in LIGHT_WEAPONS) and not any(r in n for r in RANGED_WEAPONS)


HEALING_KEYWORDS = {
    "cura", "cura ferimentos", "curar", "restaura", "restaurar",
    "palavra curativa", "imposição de mãos", "healing", "heal",
    "bênção vital", "toque do curandeiro", "word of healing",
}

# ---------------------------------------------------------------------------
# Magias de controle/condição — NÃO causam dano, aplicam condições.
# "pool": True → o resultado do dado é um pool de HP (ex: Sleep):
#     o alvo dorme se HP_atual ≤ pool; pool é decrementado pelo HP do alvo.
# "pool": False → aplica a condição diretamente (Hold Person, Charm, etc.)
# ---------------------------------------------------------------------------
CONTROL_SPELL_EFFECTS: dict[str, dict] = {
    # Nível 1
    # O "dado" das magias de pool é o tamanho do pool de HP, e o SRD o
    # escreve de um jeito que nenhuma leitura de dano pega ("Roll 5d8; the
    # total is how many hit points of creatures this spell can affect").
    # Sem ele aqui, Sleep dormia zero criaturas.
    "sleep":                 {"condition": "Dormindo",     "pool": True, "dado": "5d8"},
    "color spray":           {"condition": "Cego",         "pool": True, "dado": "6d10"},
    # Nível 2
    "hold person":           {"condition": "Paralisado",   "pool": False},
    "blindness/deafness":    {"condition": "Cego",         "pool": False},
    "blindness deafness":    {"condition": "Cego",         "pool": False},
    "silence":               {"condition": "Silenciado",   "pool": False},
    "entangle":              {"condition": "Imobilizado",  "pool": False},
    # Nível 2–3
    "web":                   {"condition": "Imobilizado",  "pool": False},
    "hypnotic pattern":      {"condition": "Incapacitado", "pool": False},
    "fear":                  {"condition": "Amedrontado",  "pool": False},
    "slow":                  {"condition": "Lentidão",     "pool": False},
    "stinking cloud":        {"condition": "Envenenado",   "pool": False},
    # Encantamento
    "charm person":          {"condition": "Enfeitiçado",  "pool": False},
    "charm monster":         {"condition": "Enfeitiçado",  "pool": False},
    # Nível 4+
    "hold monster":          {"condition": "Paralisado",   "pool": False},
    "confusion":             {"condition": "Confuso",      "pool": False},
    "dominate person":       {"condition": "Dominado",     "pool": False},
    "dominate monster":      {"condition": "Dominado",     "pool": False},
    "banishment":            {"condition": "Banido",       "pool": False},
    "polymorph":             {"condition": "Transformado", "pool": False},
    "contagion":             {"condition": "Envenenado",   "pool": False},
    # Nível 5+
    "hold person (level 5)": {"condition": "Paralisado",   "pool": False},
    "wall of force":         {"condition": "Imobilizado",  "pool": False},
    "feeblemind":            {"condition": "Incapacitado", "pool": False},
    "power word stun":       {"condition": "Atordoado",    "pool": False},
    "power word kill":       {"condition": "Morto",        "pool": False},
}


def _get_control_effect(hab: dict) -> dict | None:
    """
    Retorna o efeito de controle se a habilidade for uma magia de condição, ou None.
    Aceita o nome em inglês (como armazenado) OU em português (magias do kit
    padrão / aprendidas com nome PT, ex: "Sono" → "sleep").
    """
    name_lower = hab.get("nome", "").lower().strip()
    eff = CONTROL_SPELL_EFFECTS.get(name_lower)
    if eff is None:
        en = _SPELL_PT_TO_EN.get(name_lower)
        if en:
            eff = CONTROL_SPELL_EFFECTS.get(en)
    if eff is None:
        # A tabela acima tem 30 magias; o SRD tem 47 de condição. As outras
        # caíam no ramo de DANO do use_ability, com dado vazio: "0 de dano" no
        # registro e a condição nunca aplicada. O compêndio sabe a condição.
        srd = _srd(hab)
        if srd is not None:
            srd_en = _norm_txt(srd.get("nome_srd", ""))
            eff = CONTROL_SPELL_EFFECTS.get(srd_en)
            if eff is None and srd.get("efeito") == "condicao" and srd.get("condicao"):
                eff = {"condition": srd["condicao"].capitalize(), "pool": False}
    return eff

def _weapon_attr(weapon_name: str, sheet: dict) -> tuple[str, int]:
    """Ranged→DEX. Finesse→max(FOR,DEX). Melee→FOR."""
    w = weapon_name.lower().strip()
    a = _itens.arma(weapon_name)
    if a:
        is_ranged  = a["distancia"]
        is_finesse = "acuidade" in a["propriedades"]
    else:
        is_ranged  = any(r in w for r in RANGED_WEAPONS)
        is_finesse = any(f in w for f in FINESSE_WEAPONS)
    str_mod = _modifier(sheet.get("forca", 10))
    dex_mod = _modifier(sheet.get("destreza", 10))
    if is_ranged:
        return "destreza", dex_mod
    if is_finesse:
        return ("destreza", dex_mod) if dex_mod >= str_mod else ("forca", str_mod)
    return "forca", str_mod

def _match_ability(char: dict, name: str) -> dict | None:
    """Retorna a habilidade cujo nome bate (case-insensitive) ou None."""
    nl = name.lower().strip()
    for hab in char.get("habilidades", []):
        if hab.get("nome", "").lower().strip() == nl:
            return hab
    return None

def _is_healing_ability(hab: dict) -> bool:
    """True se a habilidade restaura vida em vez de causar dano."""
    name = hab.get("nome", "").lower()
    desc = hab.get("descricao", "").lower()
    return (
        any(k in name for k in HEALING_KEYWORDS)
        or "restaura" in desc or "cura" in desc
        or "recupera" in desc or "heal" in desc
        # O SRD escreve cura assim, em inglês, e nenhuma das palavras acima
        # aparece: "A creature you touch regains a number of hit points".
        or "regains" in desc or "hit points" in desc
    )


# ── O QUE O DADO DA HABILIDADE SIGNIFICA ──────────────────────────────────
# Três defeitos vinham de tratar todo dado como dano:
#
#  • habilidade SEM dado rolava 1d6 e tirava vida de quem fosse o alvo. O
#    _parse_dice cai em (1,6,0) quando não entende a fórmula, e "" não é
#    fórmula. Na campanha medida eram 25 habilidades assim — Segunda Fôlego,
#    Canalizar Divindade, Mending, Inflict Wounds —, e benzer um aliado o
#    machucava;
#  • Bênção guardava "1d4", que é o bônus que ela DÁ aos ataques, não dano:
#    lançá-la no companheiro tirava 1d4 de vida dele;
#  • magia de dano aprendida pelo Open5e chegava sem dado nenhum, porque a
#    API não tem campo de dano para magias — ele está no texto.
#
# Agora o dado tem tipo, e o tipo decide o que acontece com a vida do alvo.
_DADO = r"(\d+\s*d\s*\d+(?:\s*[+-]\s*\d+)?)"
_DANO_NO_TEXTO = re.compile(
    _DADO + r"[^.;]{0,40}?\b(?:damage|dano)\b"
    r"|\b(?:deals?|causa|inflige|sofre)\b[^.;]{0,40}?" + _DADO,
    re.IGNORECASE)
_CURA_NO_TEXTO = re.compile(
    r"\b(?:regains?|heals?|restaura\w*|recupera\w*|cura\w*)\b[^.;]{0,60}?" + _DADO
    + r"|" + _DADO + r"[^.;]{0,40}?\b(?:hit points|pontos de vida)\b",
    re.IGNORECASE)


def _primeiro_dado(achado) -> str:
    """O grupo que casou, de qualquer um dos lados da alternativa."""
    if not achado:
        return ""
    return " ".join((next(g for g in achado.groups() if g)).split()).replace(" ", "")


def _sem_ponto_de_abreviacao(texto: str) -> str:
    """
    "2d10+nv. dano radiante": o ponto de "nv." encerrava a frase para as
    expressões acima, que não atravessam ponto — e a Radiância do Amanhecer
    de uma clériga real era lida como reforço, sem dano.
    """
    return re.sub(r"\b(nv|niv|nivel|mod|lv|lvl|prof|car|sab|int|des|con|for)\.",
                  r"\1", texto or "", flags=re.IGNORECASE)


def dado_de_dano_no_texto(texto: str) -> str:
    """"8d6 fire damage" → "8d6". "adiciona 1d4 aos ataques" → ""."""
    return _primeiro_dado(_DANO_NO_TEXTO.search(_sem_ponto_de_abreviacao(texto)))


def dado_de_cura_no_texto(texto: str) -> str:
    """"regains hit points equal to 1d8 + mod" → "1d8"."""
    return _primeiro_dado(_CURA_NO_TEXTO.search(_sem_ponto_de_abreviacao(texto)))


# ── O COMPÊNDIO DO SRD VEM PRIMEIRO ───────────────────────────────────────
# As funções abaixo (efeito_do_dado, dado_efetivo, salvaguarda, área, origem,
# alvos) eram seis palpites independentes sobre o texto de cada magia. Quando
# dois discordavam, a tela mostrava uma coisa e o motor fazia outra:
# Infligir Ferimentos aparecia sem dado e rolava 3d10; uma magia que só fere
# criaturas HOSTIS queimava os aliados da zona.
#
# Agora cada uma pergunta primeiro ao compêndio (rpg/compendio.py), que tem a
# magia já interpretada e revisada à mão. O texto só decide quando a
# habilidade NÃO é do SRD — a que o mestre criou, a da ficha antiga — e é
# assim que todo chamador existente recebe o dado revisado sem mudar uma
# linha.

def _srd(hab: dict) -> dict | None:
    """A magia do SRD desta habilidade, ou None se ela não for do SRD."""
    if not isinstance(hab, dict):
        return None
    try:
        from rpg import compendio
    except Exception:                                            # pragma: no cover
        return None
    return (compendio.magia(hab.get("nome_srd") or "")
            or compendio.magia(hab.get("nome") or ""))


_EFEITO_DO_COMPENDIO = {"dano": "dano", "cura": "cura", "pool": "pool",
                        "condicao": "condicao"}


def efeito_do_dado(hab: dict) -> str:
    """
    O que o dado desta habilidade faz: 'cura', 'dano', 'bonus' ou 'nenhum'.

    'bonus' é o caso da Bênção e da Orientação: o dado existe e é rolado — o
    jogador quer ver o número —, mas ele NÃO entra na vida de ninguém.
    """
    if not isinstance(hab, dict):
        return "nenhum"
    srd = _srd(hab)
    if srd is not None:
        if srd["efeito"] in _EFEITO_DO_COMPENDIO:
            return _EFEITO_DO_COMPENDIO[srd["efeito"]]
        # Reforço com dado (a Bênção soma 1d4) rola e mostra, mas não fere.
        return "bonus" if srd.get("dado") else "nenhum"
    # Magia de controle é o que a tabela do motor disser que ela é — o dado
    # dela é pool ou duração, nunca ferida.
    _ctrl = _get_control_effect(hab)
    if _ctrl is not None:
        return "pool" if _ctrl.get("pool") else "condicao"
    texto = f"{hab.get('nome', '')} {hab.get('descricao', '')}"
    tem_dado = bool((hab.get("dado") or "").strip())
    if _is_healing_ability(hab):
        return "cura" if tem_dado or dado_de_cura_no_texto(texto) else "nenhum"
    if tem_dado:
        # Dado guardado sem nada no texto ligando-o a dano é bônus, não ferida.
        return "dano" if dado_de_dano_no_texto(texto) or not hab.get("descricao") else "bonus"
    return "dano" if dado_de_dano_no_texto(texto) else "nenhum"


# ── A SALVAGUARDA DA MAGIA ────────────────────────────────────────────────
# Até aqui ela só acontecia se o MESTRE passasse saving_throw_stat e a CD na
# chamada. Quando ele esquecia — e esquecer é o problema medido deste
# projeto —, a Bola de Fogo causava dano cheio em todo mundo, sem teste
# nenhum. O SRD diz qual é o teste no texto da magia; dá para ler de lá.
_SAVE_NO_TEXTO = re.compile(
    r"\b(?:on\s+a\s+|make\s+a\s+|succeed\s+on\s+a\s+)?"
    r"(strength|dexterity|constitution|intelligence|wisdom|charisma|"
    r"for[çc]a|destreza|constitui[çc][ãa]o|intelig[êe]ncia|sabedoria|carisma)"
    r"\s+(?:saving\s+throw|save)"
    r"|salvaguarda\s+de\s+"
    r"(for[çc]a|destreza|constitui[çc][ãa]o|intelig[êe]ncia|sabedoria|carisma)",
    re.IGNORECASE)
_SAVE_PT = {
    "strength": "forca", "dexterity": "destreza", "constitution": "constituicao",
    "intelligence": "inteligencia", "wisdom": "sabedoria", "charisma": "carisma",
}


def salvaguarda_da_habilidade(hab: dict) -> str:
    """O atributo do teste de resistência desta habilidade, ou ""."""
    srd = _srd(hab)
    if srd is not None:
        return srd.get("salvaguarda") or ""
    guardada = _norm_txt((hab or {}).get("salvaguarda", "") or "")
    if guardada:
        return _SAVE_PT.get(guardada, guardada)
    achado = _SAVE_NO_TEXTO.search(f"{(hab or {}).get('descricao', '')}")
    if not achado:
        # A ficha escrita à mão usa a SIGLA: "save de CON", "teste de SAB".
        sigla = re.search(r"\b(?:save|salvaguarda|teste|resist\w*)\s+de\s+"
                          r"(FOR|DES|CON|INT|SAB|CAR)\b",
                          f"{(hab or {}).get('descricao', '')}")
        if sigla:
            return {"FOR": "forca", "DES": "destreza", "CON": "constituicao",
                    "INT": "inteligencia", "SAB": "sabedoria",
                    "CAR": "carisma"}[sigla.group(1)]
        return ""
    bruto = _norm_txt(next(g for g in achado.groups() if g))
    return _SAVE_PT.get(bruto, bruto)


def _rolar_salvaguarda(alvo: dict, atributo: str, cd: int,
                       vantagem: bool = False, desvantagem: bool = False,
                       contra: str = "") -> tuple[bool, str]:
    """
    O alvo resiste? Mesma conta da salvaguarda de item arremessado, para
    qualquer atributo: d20 + modificador (+ proficiência quando a classe tem
    a salvaguarda).

    `contra` é a condição que a falha traria (Amedrontado, Enfeitiçado): o
    Contra-Encanto dá vantagem só contra essas.
    """
    s = alvo.get("sheet") or {}
    status = (alvo.get("status") or "").lower()
    conds = {_norm_txt(c.get("nome", "") if isinstance(c, dict) else str(c))
             for c in (s.get("condicoes") or [])}
    if atributo == "destreza" and (conds & set(_FALHA_AUTOMATICA_EM_DES)
                                   or status in ("inconsciente", "dormindo")):
        return False, f"falha automática na salvaguarda de DES (CD {cd})"
    mod = _modifier(int(s.get(atributo, 10) or 10))
    classe = (s.get("classe") or "").lower()
    # Alma do Diamante: proficiência em todas as salvaguardas.
    if (atributo in CLASS_DATA.get(classe, {}).get("saves", [])
            or _tem_habilidade(alvo, "alma do diamante", "diamond soul")):
        mod += int(s.get("proficiencia", 2) or 2)
    # Contido: desvantagem nas salvaguardas de DES.
    if atributo == "destreza" and conds & {"contido", "imobilizado"}:
        desvantagem = True
    notas_extra = []
    _desv_arm_sv = _desvantagem_da_armadura(alvo, atributo)
    if _desv_arm_sv:
        desvantagem = True
        notas_extra.append(f"desvantagem: {_desv_arm_sv}")
    # Cobertura: +2 (meia) ou +5 (três quartos) nas salvaguardas de DES.
    _cob_sv = _cobertura_de(alvo)
    if atributo == "destreza" and _COBERTURA.get(_cob_sv):
        mod += _COBERTURA[_cob_sv]
        notas_extra.append(f"{_COBERTURA_NOME[_cob_sv]}: +{_COBERTURA[_cob_sv]}")
    from rpg import tracos as _tracos_s
    if _tracos_s.contra_magia(alvo):
        vantagem = True
        notas_extra.append("vantagem: Resistência à Magia")
    from rpg import reacoes as _reacoes_s
    mod, _nota_proj = _reacoes_s.bonus_projetado(alvo, atributo, mod)
    if _nota_proj:
        notas_extra.append(_nota_proj)
    for e in _efeitos(s):
        if _norm_txt(atributo) in {_norm_txt(x) for x in e.get("vantagem_save_atributos") or []}:
            vantagem = True
            notas_extra.append(f"vantagem: {e.get('nome', 'efeito')}")
            break
    if contra:
        for e in _efeitos(s):
            if _norm_txt(contra) in {_norm_txt(x) for x in e.get("vantagem_save_contra") or []}:
                vantagem = True
                notas_extra.append(f"vantagem: {e.get('nome', 'efeito')}")
                break

    def _rolar() -> tuple[bool, str]:
        d20 = random.randint(1, 20)
        if vantagem and not desvantagem:
            d20 = max(d20, random.randint(1, 20))
        elif desvantagem and not vantagem:
            d20 = min(d20, random.randint(1, 20))
        # Bênção, Perdição, Resistência: o dado do efeito entra na conta.
        extra, nota = _bonus_de_salvaguarda(alvo)
        total = d20 + mod + extra
        sigla = _ATRIBUTO_SIGLA.get(atributo, atributo[:3].upper())
        extra_txt = f" {extra:+d} ({nota})" if nota else ""
        return total >= cd, f"salvaguarda de {sigla}: {d20}{mod:+d}{extra_txt} = {total} vs CD {cd}"

    passou, linha = _rolar()
    if notas_extra:
        linha += f" ({'; '.join(notas_extra)})"
    if passou:
        return passou, linha
    _passou_l, _linha_l = _reacoes_s.lampejo_na_salvaguarda(alvo, mod, cd)
    if _passou_l:
        return True, f"{linha}; {_linha_l}"
    # Indomável (guerreiro) e Alma do Diamante (monge, 1 ki): refaz a
    # salvaguarda que falhou. O motor usa sozinho, se o jogador não desligou.
    if (_tem_habilidade(alvo, "indomavel", "indomitable") and reacao_automatica(alvo, "indomavel")
            and (usos_restantes(alvo, "Indomável") or 0) > 0
            and _reacoes_s._confirmar(alvo, "indomavel", f"{alvo.get('name')} falhou ({linha}). Usar Indomável "
                                                         f"e rolar de novo ({usos_restantes(alvo, 'Indomável')} "
                                                         f"uso(s))?")):
        _gastar_uso(alvo, "Indomável")
        passou2, linha2 = _rolar()
        return passou2, f"{linha}; Indomável, de novo: {linha2}"
    if (_tem_habilidade(alvo, "alma do diamante", "diamond soul")
            and reacao_automatica(alvo, "alma do diamante")
            and (usos_restantes(alvo, "Ki") or 0) > 0
            and _reacoes_s._confirmar(alvo, "alma do diamante", f"{alvo.get('name')} falhou ({linha}). Gastar 1 "
                                                                f"ki (Alma do Diamante) e rolar de novo?")):
        _gastar_uso(alvo, "Ki")
        passou2, linha2 = _rolar()
        return passou2, f"{linha}; Alma do Diamante (1 ki), de novo: {linha2}"
    # Resistência Lendária: o chefe troca a falha por sucesso, enquanto houver uso.
    _rl = s.get("resistencia_lendaria") if isinstance(s.get("resistencia_lendaria"), dict) else None
    if _rl and int(_rl.get("restantes", 0) or 0) > 0 and not memory.is_party_member(alvo):
        _rl["restantes"] = int(_rl["restantes"]) - 1
        _log_combat_event("legendary_resistance", alvo.get("name", ""), "",
                          msg=f"{alvo.get('name')} usa Resistência Lendária")
        return True, (f"{linha}; Resistência Lendária: a falha vira SUCESSO "
                      f"(restam {_rl['restantes']}/{_rl.get('max', 3)})")
    return passou, linha


def reacao_automatica(char: dict, chave: str) -> bool:
    """
    O motor usa esta reação (ou recurso que reage) sozinho? Sim, a menos que
    o jogador a tenha desligado na tela de combate.
    """
    desligadas = ((char or {}).get("sheet") or {}).get("reacoes_desligadas") or []
    return _norm_txt(chave) not in {_norm_txt(x) for x in desligadas}


# Mente Vazia: imune a Amedrontado e Enfeitiçado.
_IMUNIDADES_DE_CLASSE = {
    "mente vazia": ("amedrontado", "enfeiticado"),
}


def _imune_a_condicao(char: dict | None, condicao: str) -> bool:
    if not char:
        return False
    c = _norm_txt(condicao)
    # A criatura: o elemental não é agarrado, o zumbi não é envenenado.
    if c in {_norm_txt(x) for x in (char.get("sheet") or {}).get("imunidades_condicao") or []}:
        return True
    for hab, conds in _IMUNIDADES_DE_CLASSE.items():
        if c in conds and _tem_habilidade(char, hab):
            return True
    for e in _efeitos_de(char):
        if c in {_norm_txt(x) for x in e.get("imune_condicoes") or []}:
            return True
    return False


# ---------------------------------------------------------------------------
# Área
# ---------------------------------------------------------------------------
#
# Bola de Fogo, Mãos Flamejantes e Sopro do Dragão atingiam UM alvo. O motor
# lia o dado certo, rolava a salvaguarda certa e aplicava tudo numa criatura
# só — a magia que existe para pegar o grupo inteiro custava o mesmo e valia
# um terço.
#
# O tabuleiro já tem zonas (set_battlefield), e a zona é a unidade natural de
# área aqui: "quem está no Pátio" é uma pergunta que o motor sabe responder.
# Sem zonas em jogo nada muda — a magia cai no caminho de alvo único, como
# antes. Isso é de propósito: o modo narrado e as campanhas antigas não podem
# mudar de regra no meio do combate.

_FORMAS_DE_AREA = {
    "cone": "cone", "radius": "raio", "sphere": "esfera", "line": "linha",
    "cube": "cubo", "cylinder": "cilindro", "square": "quadrado",
    "raio": "raio", "esfera": "esfera", "linha": "linha", "cubo": "cubo",
    "cilindro": "cilindro", "cone de": "cone",
}
# "15-foot cone", "20-foot-radius sphere", "30 foot line", "cone de 4,5 m"
_AREA_RE = re.compile(
    r"(\d{1,3})(?:[.,]\d)?\s*[-\s]?\s*(?:foot|feet|ft\b|p[ée]s?\b|metros?\b|m\b)"
    r"\s*[-\s]?\s*(" + "|".join(sorted(_FORMAS_DE_AREA, key=len, reverse=True)) + r")\b",
    re.IGNORECASE)
_AREA_PT_RE = re.compile(
    r"\b(cone|esfera|cubo|linha|cilindro|raio)\s+de\s+(\d{1,3})(?:[.,](\d))?\s*m\b",
    re.IGNORECASE)


def _em_metros(pes: float) -> str:
    """Pés do SRD em metros de meio em meio, como o resto do jogo escreve."""
    m = round(pes * 0.3048 * 2) / 2
    return f"{m:g}".replace(".", ",")


def area_da_habilidade(hab: dict) -> str:
    """
    A forma e o tamanho da área desta habilidade, ou "" quando ela pega um
    alvo só.

    Duas fontes, nesta ordem: o campo `alcance` do Open5e, que traz a área
    entre parênteses ("Self (15-foot cone)"), e o texto da descrição, que é
    onde ela aparece nas magias de alcance normal ("each creature in a
    20-foot-radius sphere centered on a point you choose").
    """
    if not isinstance(hab, dict):
        return ""
    srd = _srd(hab)
    if srd is not None:
        area = srd.get("area")
        if not area:
            return ""
        return f"{area['forma']} de {area['tamanho_m']:g} m".replace(".", ",")
    for texto in ((hab.get("alcance") or ""), (hab.get("descricao") or "")):
        achado = _AREA_RE.search(texto)
        if achado:
            forma = _FORMAS_DE_AREA[achado.group(2).lower()]
            unidade_pt = re.search(r"\d\s*[-\s]?\s*(?:m\b|metros?\b|p[ée]s?\b)", texto,
                                   re.IGNORECASE)
            bruto = float(achado.group(1))
            if unidade_pt and re.search(r"m\b|metro", unidade_pt.group(0), re.IGNORECASE):
                return f"{forma} de {bruto:g} m".replace(".", ",")
            return f"{forma} de {_em_metros(bruto)} m"
        achado = _AREA_PT_RE.search(texto)
        if achado:
            medida = achado.group(2) + ("," + achado.group(3) if achado.group(3) else "")
            return f"{_FORMAS_DE_AREA[achado.group(1).lower()]} de {medida} m"
    return ""


def origem_da_area(hab: dict) -> str:
    """
    De onde a área nasce: "self" (cone/linha saindo do conjurador) ou "alvo"
    (esfera posta à distância, como a Bola de Fogo).
    """
    srd = _srd(hab)
    if srd is not None:
        return "self" if srd.get("origem") == "si" else "alvo"
    alcance = _norm_txt((hab or {}).get("alcance", "") or "")
    if alcance.startswith("self") or alcance.startswith("pessoal"):
        return "self"
    # Habilidade escrita à mão, sem campo de alcance: o texto ainda pode dizer
    # que a área nasce em quem usa ("ao seu redor", "a partir de você").
    texto = _norm_txt((hab or {}).get("descricao", "") or "")
    if re.search(r"ao seu redor|em volta de voce|ao redor de voce|"
                 r"centrad[ao] em voce|a partir de voce|around you|centered on you", texto):
        return "self"
    return "alvo"


# ── QUEM A HABILIDADE ATINGE ──────────────────────────────────────────────
# O campo que faltava, e cuja falta queimou aliados: a área era tratada como
# indiscriminada mesmo quando a regra diz "criaturas hostis" ou "à sua
# escolha". O fogo amigo continua sendo regra do jogo — a Bola de Fogo pega
# quem estiver na esfera —, mas só nas magias em que a regra manda.
#
#   hostis  — só os adversários de quem usa
#   escolha — quem usa escolhe; o motor poupa os aliados
#   todos   — todo mundo na área, aliados inclusive
#   uma     — um alvo
#   si      — só quem usa

def alvos_da_habilidade(hab: dict) -> str:
    srd = _srd(hab)
    if srd is not None:
        return srd.get("alvos") or "uma"
    texto = _norm_txt(f"{(hab or {}).get('descricao', '')}")
    if re.search(r"\bhostis\b|\binimig[oa]s\b|\bhostile\b", texto):
        return "hostis"
    if re.search(r"a sua escolha|que voce escolher|of your choice|you choose|"
                 r"aliados? escolhid|ate \w+ criaturas", texto):
        return "escolha"
    if area_da_habilidade(hab):
        return "todos"
    return "si" if origem_da_area(hab) == "self" and _e_traco_passivo_seguro(hab) else "uma"


def _e_traco_passivo_seguro(hab: dict) -> bool:
    """
    Habilidade de alcance pessoal SEM área só é 'em si' quando ela não fere
    ninguém. Toque Vampírico nasce em você e fere o inimigo: tratá-la como
    'si' aplicaria o dano em quem conjura.
    """
    return efeito_do_dado(hab) not in ("dano",)


def _alvos_em_area(char_name: str, hab: dict, target_name: str) -> tuple[str, list[dict]]:
    """
    Quem a área pega, e em que zona.

    Devolve ("", []) sempre que a regra não se aplica — sem zonas no combate,
    zona desconhecida, ou habilidade que não é de área. Quem chama cai no
    caminho de alvo único nesse caso.

    O conjurador fica FORA. No SRD ele estaria dentro da esfera que pusesse em
    cima de si, mas aqui a área é uma zona inteira e o mestre não escolhe o
    ponto: cobrar dano dele seria inventar uma decisão que ninguém tomou.

    QUEM MAIS ENTRA depende da magia (alvos_da_habilidade):
      • "todos"  — os aliados na zona entram. É o fogo amigo, e é regra: a
                   Bola de Fogo pega quem estiver na esfera, e é isso que faz a
                   magia de área ser uma escolha.
      • "hostis" / "escolha" — só os adversários de quem conjura. Foi o
                   defeito que queimou aliados numa partida: uma magia que só
                   fere criaturas HOSTIS era tratada como indiscriminada.
    """
    if not area_da_habilidade(hab):
        return "", []
    if not _zonas_ativas():
        return "", _alvos_sem_zonas(char_name, hab, target_name)
    so_adversarios = alvos_da_habilidade(hab) in ("hostis", "escolha")
    if origem_da_area(hab) == "self":
        zona = _zona_de(char_name)
    else:
        primeiro = (target_name or "").split(",")[0].strip()
        zona = _zona_de(primeiro) if primeiro else ""
    if not zona:
        return "", []

    eu = memory.char_key(char_name)
    chars = memory.campaign.get("characters", {})
    conjurador = chars.get(eu) or {}
    lado_de_quem_conjura = memory.luta_com_o_grupo(conjurador) if conjurador else None
    cs = memory.campaign.get("combat_state") or {}
    pegos = []
    for nome in cs.get("initiative_order", []) or []:
        chave = memory.char_key(nome)
        if chave == eu:
            continue
        alvo = chars.get(chave)
        if not alvo or not alvo.get("sheet"):
            continue
        if (alvo.get("status", "vivo") or "").lower() in OUT_OF_COMBAT_STATUSES:
            continue
        if int((alvo.get("sheet") or {}).get("vida_atual", 0) or 0) <= 0:
            continue
        if _zona_de(nome) != zona:
            continue
        if (so_adversarios and lado_de_quem_conjura is not None
                and memory.luta_com_o_grupo(alvo) == lado_de_quem_conjura):
            continue
        pegos.append(alvo)
    return (zona, pegos) if pegos else ("", [])


def max_alvos_da_area(hab: dict) -> int:
    """
    Sem zonas, quantas criaturas a área pega, pela tabela do Guia do Mestre
    ("Targets in Areas of Effect"): esfera, cilindro e cubo, tamanho ÷ 5 pés;
    cone, ÷ 10; linha, ÷ 30. A Bola de Fogo (6 m de raio = 20 pés) pega 4.
    """
    import math
    area = area_da_habilidade(hab)
    achado = re.match(r"(\w+) de ([\d,\.]+) m", area or "")
    if not achado:
        return 1
    forma = _norm_txt(achado.group(1))
    pes = float(achado.group(2).replace(",", ".")) * 10 / 3
    divisor = 10 if forma == "cone" else (30 if forma == "linha" else 5)
    return max(1, math.ceil(pes / divisor - 1e-9))


def _alvos_sem_zonas(char_name: str, hab: dict, target_name: str) -> list[dict]:
    """
    Combate sem zonas: a área pega as criaturas que a tela escolheu (nomes
    por vírgula), até o tamanho dela. Antes pegava só a primeira, e a Bola de
    Fogo virava magia de um alvo. Um nome só segue o caminho de alvo único.
    """
    nomes = [n.strip() for n in (target_name or "").split(",") if n.strip()]
    if len(nomes) < 2:
        return []
    eu = memory.char_key(char_name)
    chars = memory.campaign.get("characters", {})
    conjurador = chars.get(eu) or {}
    so_adversarios = alvos_da_habilidade(hab) in ("hostis", "escolha")
    pegos = []
    for nome in nomes:
        alvo = chars.get(memory.char_key(nome))
        if not alvo or not alvo.get("sheet") or alvo in pegos or memory.char_key(nome) == eu:
            continue
        if (alvo.get("status", "vivo") or "").lower() in OUT_OF_COMBAT_STATUSES:
            continue
        if int((alvo.get("sheet") or {}).get("vida_atual", 0) or 0) <= 0:
            continue
        if (so_adversarios and conjurador
                and memory.luta_com_o_grupo(alvo) == memory.luta_com_o_grupo(conjurador)):
            continue
        pegos.append(alvo)
        # A área que pega todos pega também quem está colado no alvo (trocou
        # golpes com ele nesta rodada ou na anterior): a Bola de Fogo no orc
        # que luta com o guerreiro queima o guerreiro.
        if not so_adversarios:
            for colado in _colados(alvo):
                if colado not in pegos and memory.char_key(colado.get("name", "")) != eu:
                    pegos.append(colado)
    return pegos[:max_alvos_da_area(hab)]


def _colados(alvo: dict) -> list[dict]:
    """Quem trocou golpes corpo a corpo com `alvo` nesta rodada ou na anterior (e está de pé)."""
    cs = memory.campaign.get("combat_state") or {}
    rodada = int(cs.get("round", 1) or 1)
    chave = memory.char_key(alvo.get("name", ""))
    saida = []
    for a, b, r in cs.get("engajados") or []:
        if int(r) < rodada - 1 or chave not in (a, b):
            continue
        outro = memory.campaign["characters"].get(b if a == chave else a)
        if (outro and (outro.get("status") or "").lower() not in OUT_OF_COMBAT_STATUSES
                and int((outro.get("sheet") or {}).get("vida_atual", 0) or 0) > 0):
            saida.append(outro)
    return saida


def prever_area(char_name: str, ability_name: str, target_name: str = "") -> dict:
    """
    Quem a habilidade VAI atingir, antes de ela acontecer — para a tela pedir
    confirmação mostrando os aliados que estão no caminho.

    O fogo amigo é regra e continua; o que não pode é acontecer sem aviso. Na
    partida relatada, o jogador conjurou uma magia sem descrição visível e
    atingiu os companheiros sem saber que eles estavam na área.
    """
    char = memory.campaign.get("characters", {}).get(memory.char_key(char_name))
    if not char:
        return {"ok": False, "erro": "personagem não encontrado"}
    hab = next((h for h in (char.get("habilidades") or [])
                if isinstance(h, dict) and _norm_txt(h.get("nome", "")) == _norm_txt(ability_name)),
               None)
    if hab is None:
        return {"ok": False, "erro": "habilidade não encontrada"}
    area = area_da_habilidade(hab)
    alvos = alvos_da_habilidade(hab)
    zona, pegos = _alvos_em_area(char_name, hab, target_name)
    lado = memory.luta_com_o_grupo(char)
    atingidos = [{"nome": a.get("name", ""),
                  "aliado": memory.luta_com_o_grupo(a) == lado}
                 for a in pegos]
    return {
        "ok": True,
        "area": area,
        "zona": zona,
        # Sem zonas: quantas criaturas a tela deixa escolher.
        "max_alvos": max_alvos_da_area(hab) if area and not _zonas_ativas() else None,
        "alvos": alvos,
        "atingidos": atingidos,
        "aliados_atingidos": [a["nome"] for a in atingidos if a["aliado"]],
    }


# ---------------------------------------------------------------------------
# Usos por descanso
# ---------------------------------------------------------------------------
#
# O guerreiro usava Surto de Ação todo turno. O bárbaro entrava em Fúria de
# novo na luta seguinte, e na outra. A ficha não tinha contador nenhum: a
# descrição dizia "1 uso por descanso curto" e isso era texto para o mestre
# ler — nada no motor cobrava.
#
# Mana já era recurso (custo_mana, restaurado no descanso longo). As
# habilidades de classe do SRD que NÃO custam mana ficavam de fora, e são
# exatamente as que definem o ritmo do dia de aventura.
#
# O contador mora em sheet["usos"], com o que SOBRA de cada habilidade.
# Ausente = cheio, então ficha antiga entra neste mundo com tudo disponível e
# nenhuma migração.

def _usos_de_furia(nivel: int) -> int:
    """Tabela do bárbaro no SRD: 2, 3, 4, 5 e 6."""
    for limite, usos in ((17, 6), (12, 5), (6, 4), (3, 3)):
        if nivel >= limite:
            return usos
    return 2


def _mod_da_ficha(s: dict, atributo: str) -> int:
    return _modifier(int((s or {}).get(atributo, 10) or 10))


# nome normalizado → (qual descanso devolve, quantos usos pelo nível e ficha)
_USOS_POR_DESCANSO = {
    "segunda folego":      ("curto", lambda n, s: 1),
    "surto de acao":       ("curto", lambda n, s: 2 if n >= 17 else 1),
    "canalizar divindade": ("curto", lambda n, s: 3 if n >= 18 else (2 if n >= 6 else 1)),
    "furia":               ("longo", lambda n, s: _usos_de_furia(n)),
    "furia implacavel":    ("longo", lambda n, s: 1),
    # O texto da ficha dizia "Usos = mod. SAB por descanso longo" e nada
    # contava: o clérigo de guerra atacava de bônus todo turno.
    "sacerdote de guerra": ("longo", lambda n, s: max(1, _mod_da_ficha(s, "sabedoria"))),
    "inspiracao de bardo": ("longo", lambda n, s: max(1, _mod_da_ficha(s, "carisma"))),
    # Pontos de ki: um por nível de monge, a partir do 2º.
    "ki":                  ("curto", lambda n, s: n if n >= 2 else 0),
    # Reserva de cura, não usos: 5 × nível; a Cura pelas Mãos gasta o que cura.
    "cura pelas maos":     ("longo", lambda n, s: 5 * n),
    # Reserva, como a Cura pelas Mãos: a Fonte de Magia gasta e devolve.
    "pontos de feiticaria": ("longo", lambda n, s: n if n >= 2 else 0),
    "forma selvagem":      ("curto", lambda n, s: 2),
    "golpe de sorte":      ("curto", lambda n, s: 1),
    "intervencao divina":  ("longo", lambda n, s: 1),
    "toque purificador":   ("longo", lambda n, s: max(1, _mod_da_ficha(s, "carisma"))),
    "corpo curativo":      ("longo", lambda n, s: 1),
    "indomavel":           ("longo", lambda n, s: 3 if n >= 17 else (2 if n >= 13 else 1)),
    "bandeira de aviso":   ("longo", lambda n, s: max(1, _mod_da_ficha(s, "sabedoria"))),
    "eu ilusorio":         ("curto", lambda n, s: 1),
    # O unicórnio do Conjurar Celestial: três curas por invocação.
    "toque curativo":      ("longo", lambda n, s: 3),
    # Mestre de Batalha: 4 dados por descanso curto, 5 no 7º, 6 no 15º.
    "dados de superioridade": ("curto", lambda n, s: 6 if n >= 15 else (5 if n >= 7 else 4)),
    "mestre sobrenatural": ("longo", lambda n, s: 1),
    "avatar sagrado":      ("longo", lambda n, s: 1),
    "anjo vingador":       ("longo", lambda n, s: 1),
    "terceiro olho":       ("curto", lambda n, s: 1),
    "conjuracao veloz":    ("curto", lambda n, s: 1),
    "presenca feerica":    ("curto", lambda n, s: 1),
    "apenas para mim":     ("curto", lambda n, s: 1),
    "mestrado do grande antigo": ("longo", lambda n, s: 1),
    "refugio feerico":     ("curto", lambda n, s: max(2, int(s.get("proficiencia", 2) or 2))),
}


def _chave_de_uso(nome: str) -> str:
    """
    A chave da tabela. "Canalizar Divindade (Arma Sagrada)" e "Canalizar
    Divindade (Preservar Vida)" são efeitos DIFERENTES do MESMO recurso — o
    paladino não ganha um uso a mais por conhecer dois efeitos. Rajada de
    Golpes, Defesa Paciente e Passo do Vento gastam o mesmo ki.
    """
    n = _norm_txt(nome or "")
    if n.startswith("canalizar divindade"):
        return "canalizar divindade"
    if n in _USOS_POR_DESCANSO:
        return n
    from rpg import resolucao
    chave, acao = resolucao.acao_de_classe(nome)
    if acao:
        uso = acao.get("uso") or chave
        if uso in _USOS_POR_DESCANSO:
            return uso
    return ""


def usos_maximos(char: dict, nome: str) -> int | None:
    """Quantos usos a habilidade tem por descanso, ou None quando é livre."""
    chave = _chave_de_uso(nome)
    if not chave:
        return None
    s = (char or {}).get("sheet") or {}
    nivel = int(s.get("nivel", 1) or 1)
    # Só o Canalizar Divindade do CLÉRIGO escala (1/2/3 nos níveis 2/6/18). O
    # do paladino é 1 por descanso curto em qualquer nível, e esta tabela dava
    # 2 a partir do 6 para os dois. Achado ao gerar o compêndio do SRD.
    if chave == "canalizar divindade" and _norm_txt(s.get("classe", "")) == "paladino":
        return 1
    if chave == "forma selvagem" and _tem_habilidade(char, "uso de forma selvagem adicional"):
        return 3
    return _USOS_POR_DESCANSO[chave][1](nivel, s)


def _tem_habilidade(char: dict, *nomes: str) -> bool:
    """A ficha tem alguma destas habilidades (nome normalizado, inteiro ou entre parênteses)?"""
    alvo = {_norm_txt(n) for n in nomes}
    for h in (char or {}).get("habilidades") or []:
        if not isinstance(h, dict):
            continue
        n = _norm_txt(h.get("nome", ""))
        if n in alvo or any(f"({a})" in n for a in alvo):
            return True
    return False


def usos_restantes(char: dict, nome: str) -> int | None:
    maximo = usos_maximos(char, nome)
    if maximo is None:
        return None
    guardado = ((char.get("sheet") or {}).get("usos") or {}).get(_chave_de_uso(nome))
    if guardado is None:
        return maximo
    return max(0, min(int(guardado), maximo))


def _gastar_uso(char: dict, nome: str, quantos: int = 1) -> None:
    chave = _chave_de_uso(nome)
    if not chave:
        return
    restam = usos_restantes(char, nome)
    char.setdefault("sheet", {}).setdefault("usos", {})[chave] = max(0, (restam or 0) - quantos)


def restaurar_usos(char: dict, descanso: str) -> list[str]:
    """
    Devolve os usos que este descanso recupera. O longo devolve tudo — quem
    descansa a noite inteira também teve a hora do descanso curto.

    Devolve a lista de nomes recuperados, para a linha do descanso na tela.
    """
    s = char.get("sheet") or {}
    usos = s.get("usos")
    if not isinstance(usos, dict) or not usos:
        return []
    voltaram = []
    for chave in list(usos):
        quando = (_USOS_POR_DESCANSO.get(chave) or ("longo", None))[0]
        if descanso == "longo" or quando == "curto":
            if usos.pop(chave, None) is not None:
                voltaram.append(chave)
    return voltaram


def dado_efetivo(hab: dict, char: dict | None = None) -> str:
    """
    A fórmula que vale. Quando a ficha não tem dado — o caso de toda magia
    vinda do Open5e, que não expõe dano —, ele é lido do texto do SRD.

    Com `char`, o truque cresce com o nível do personagem como manda o SRD:
    Raio de Fogo é 1d10 no nível 1 e 2d10 no 5. Antes ele ficava em 1d10 para
    sempre.
    """
    srd = _srd(hab)
    if srd is not None and srd.get("efeito") in ("dano", "cura", "pool"):
        dado = srd.get("dado") or ""
        if char is not None and srd.get("nivel") == 0 and srd.get("escala_personagem"):
            from rpg import compendio
            nivel = int(((char or {}).get("sheet") or {}).get("nivel", 1) or 1)
            dado = compendio.progressao_no_nivel(srd["escala_personagem"], nivel) or dado
        return dado
    if srd is not None:
        # Reforço e condição do SRD: o dado, se houver, é o da tabela.
        return srd.get("dado") or ""
    guardado = (hab.get("dado") or "").strip()
    if guardado:
        return guardado
    _ctrl = _get_control_effect(hab)
    if _ctrl is not None:
        # Pool tem o seu tamanho na tabela; condição pura não rola nada.
        return _ctrl.get("dado", "")
    texto = f"{hab.get('nome', '')} {hab.get('descricao', '')}"
    return dado_de_cura_no_texto(texto) if _is_healing_ability(hab) else dado_de_dano_no_texto(texto)

# ---------------------------------------------------------------------------
# Armaduras — a CA sai do compêndio (rpg/itens.py)
# dex_bonus: "full" = DEX inteira | "cap2" = no máximo +2 | "none" = sem DEX
# ---------------------------------------------------------------------------

# Nome em português → estatística, DERIVADO do compêndio (só leitura). Cada
# armadura aparece com o nome oficial e com os apelidos que o mestre digita; o
# assistente de criação usa os mesmos nomes (test_loja_e_peso confere). Para
# corrigir, edite scripts/srd_itens_pt.json e gere de novo.
#
# Antes esta era uma tabela à mão, e três nomes tinham a estatística de OUTRA
# armadura ("Cota de Malha" com CA 14 de brunea). Os apelidos antigos estão
# todos no compêndio: nenhum personagem salvo perde a armadura.
ARMOR_TABLE: dict[str, dict] = {
    nome.lower(): {"ca_base": e["armadura"]["ca_base"], "dex_bonus": e["armadura"]["dex"],
                   "slot": "escudo" if e["categoria"] == "escudo" else "armadura",
                   "srd": e["nome_srd"].lower()}
    for e in _itens.comuns().values() if e["categoria"] in ("armadura", "escudo")
    for nome in (e["nome"], *e.get("aliases", []))
}

# Custo (po) e peso (lb) por armadura do SRD, pelo nome em inglês.
_ARMADURAS_SRD: dict[str, tuple[float, float]] = {
    e["nome_srd"].lower(): (e["preco_pc"] / 100, round(e["peso_kg"] / 0.4536))
    for e in _itens.comuns().values() if e["categoria"] in ("armadura", "escudo")
}


def _armadura_na_tabela(nome: str) -> dict | None:
    """
    A armadura ou o escudo com este nome, ignorando caixa e acento:
    {ca_base, dex_bonus, slot, srd, bonus, forca_min, furtividade_desvantagem}.

    Aceita o nome em inglês ("Chain Mail"), o bônus mágico ("Cota de Malha
    +1", "Escudo +2") e o item mágico feito de armadura ("Placas Anãs",
    "Cota de Malha de Mithral"). Antes, armadura mágica não equipava, e o nome
    em inglês ia ao Open5e, que devolvia o primeiro resultado da busca sem
    conferir o nome: "Chain Mail" equipava com CA 10 + DES inteira.
    """
    a = _itens.armadura(nome)
    if not a:
        return None
    magico = _itens.magicos().get(a.get("item_magico") or "") or {}
    efeito = magico.get("efeito") or {}
    return {"ca_base": a["ca_base"], "dex_bonus": a["dex"],
            "slot": "escudo" if a["tipo"] == "escudo" else "armadura",
            "tipo": a["tipo"], "srd": a["nome_srd"].lower(), "bonus": int(a["bonus"] or 0),
            # Mithral: sem Força mínima e sem desvantagem em Furtividade.
            "forca_min": 0 if efeito.get("sem_forca_minima") else a["forca_min"],
            "furtividade_desvantagem": (a["furtividade_desvantagem"]
                                        and not efeito.get("sem_desvantagem_furtividade")),
            "item_magico": magico.get("chave", ""),
            "sintonizacao": bool(magico.get("sintonizacao")),
            "proficiente": bool(efeito.get("proficiente"))}


# ---------------------------------------------------------------------------
# Condições D&D 5e com efeitos mecânicos
# ---------------------------------------------------------------------------

# Efeitos suportados mecanicamente:
#   attack_disadvantage  → atacante rola com desvantagem
#   attack_advantage     → atacante rola com vantagem
#   defense_disadvantage → defensores rolam com vantagem contra este alvo
#                          (i.e. ataques CONTRA ele ganham vantagem)
#   auto_crit            → qualquer ataque corpo-a-corpo acerta automaticamente como crítico
#   check_disadvantage   → testes de atributo rolam com desvantagem

# ── Tradução PT→EN para busca de condições no Open5e ─────────────────────────
CONDITION_PT_TO_EN: dict[str, str] = {
    "cego":        "blinded",
    "enfeitiçado": "charmed",
    "surdo":       "deafened",
    "exausto":     "exhaustion",
    "assustado":   "frightened",
    "agarrado":    "grappled",
    "incapacitado":"incapacitated",
    "invisível":   "invisible",
    "paralisado":  "paralyzed",
    "petrificado": "petrified",
    "envenenado":  "poisoned",
    "caído":       "prone",
    "amedrontado": "restrained",
    "atordoado":   "stunned",
    "inconsciente":"unconscious",
}


#   no_actions   → não age no turno (o turno passa sozinho)
#   no_movement  → não sai da zona
#   untargetable → ninguém o alcança (Banimento)
#
# Até aqui o turno do inimigo não olhava condição nenhuma: o orc Paralisado
# pelo Imobilizar Pessoa atacava, só com desvantagem; o Atordoado e o
# Inconsciente (Padrão Hipnótico) também. E metade das condições que as magias
# aplicam não tinha linha nenhuma nesta tabela — "contido" (Teia, Constrição),
# "aprisionado" (Prisão de Força), "banido" — e não faziam nada.
CONDITION_EFFECTS: dict[str, dict] = {
    "cego":        {"attack_disadvantage": True, "defense_disadvantage": True},
    "envenenado":  {"attack_disadvantage": True, "check_disadvantage": True},
    "amedrontado": {"attack_disadvantage": True},
    "caído":       {"attack_disadvantage": True, "defense_disadvantage": True},
    # Ataques contra o paralisado têm vantagem (faltava) e ele não age.
    "paralisado":  {"attack_disadvantage": True, "defense_disadvantage": True, "auto_crit": True,
                    "no_actions": True, "no_movement": True},
    "atordoado":   {"attack_disadvantage": True, "defense_disadvantage": True,
                    "no_actions": True, "no_movement": True},
    "invisível":   {"attack_advantage": True},
    # Ação Ardilosa (Esconder): o primeiro ataque sai com vantagem e revela
    # quem estava escondido (attack_roll tira a condição).
    "escondido":   {"attack_advantage": True},
    # Enfeitiçado e dominado: o efeito é QUEM ele não ataca (rpg/encantos.py).
    "enfeitiçado": {},
    "dominado":    {},
    "agarrado":    {"no_movement": True},
    # Emboscada: no primeiro turno não age, não se move e não reage.
    "surpreso":    {"no_actions": True, "no_movement": True},
    "incapacitado":{"attack_disadvantage": True, "no_actions": True},
    "petrificado": {"attack_disadvantage": True, "defense_disadvantage": True, "auto_crit": True,
                    "no_actions": True, "no_movement": True},
    "surdo":       {},
    "assustado":   {"attack_disadvantage": True, "check_disadvantage": True},
    "exausto":     {"attack_disadvantage": True, "check_disadvantage": True},
    # Inconsciente (Sleep, 0 HP): não age; ataques contra ele têm vantagem e
    # acertos corpo-a-corpo a até 1,5m são CRÍTICOS automáticos (regra 5e).
    "inconsciente":{"attack_disadvantage": True, "defense_disadvantage": True, "auto_crit": True,
                    "no_actions": True, "no_movement": True},
    "imobilizado": {"attack_disadvantage": True, "defense_disadvantage": True, "no_movement": True},
    # "contido" é o nome do SRD em português (Teia, Constrição); o motor só
    # conhecia "imobilizado".
    "contido":     {"attack_disadvantage": True, "defense_disadvantage": True, "no_movement": True},
    "aprisionado": {"no_movement": True},
    "lentidão":    {"attack_disadvantage": True},
    "silenciado":  {},
    # Rogar Maldição: desvantagem nos ataques contra quem amaldiçoou (attack_roll).
    "amaldiçoado": {},
    # Confusão: o turno é sorteado (ver _turno_confuso).
    "confuso":     {},
    # Banimento: some da luta enquanto durar a concentração.
    "banido":      {"no_actions": True, "untargetable": True},
    # Piscar: no Plano Etéreo até o início do próximo turno — ninguém alcança.
    "etéreo":      {"untargetable": True},
    # Polimorfia Verdadeira em objeto: fora da luta.
    "objeto":      {"no_actions": True, "no_movement": True, "untargetable": True},
    # Dança Irresistível, Esfera Resiliente, Labirinto, Forma Gasosa, Levitação.
    "dançando":    {"attack_disadvantage": True, "defense_disadvantage": True, "no_movement": True},
    "na esfera":   {"no_actions": True, "no_movement": True, "untargetable": True},
    "no labirinto": {"no_actions": True, "no_movement": True, "untargetable": True},
    "forma gasosa": {"no_actions": True},
    "levitando":   {"no_movement": True, "fora_do_corpo_a_corpo": True},
    "em transe":   {"no_actions": True},
    # Raio do Enfraquecimento: metade do dano com armas de FOR.
    "enfraquecido": {"metade_dano_for": True},
    "transformado":{},
}


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _modifier(score: int) -> int:
    return (score - 10) // 2


def _proficiency_bonus(level: int) -> int:
    return 2 + (level - 1) // 4


def _mod_str(score: int) -> str:
    mod = _modifier(score)
    sign = "+" if mod >= 0 else ""
    return f"{score} ({sign}{mod})"


def _parse_dice(formula: str) -> tuple[int, int, int]:
    """
    Parseia fórmulas de dado com bonus opcional.
    '2d6'    → (2, 6, 0)
    '1d12+3' → (1, 12, 3)
    '2d8-1'  → (2, 8, -1)
    Fallback para (1, 6, 0) em caso de erro.
    """
    try:
        f     = formula.lower().strip().replace(" ", "")
        bonus = 0
        if "d" in f:
            d_idx = f.index("d")
            rest  = f[d_idx + 1:]       # ex: "12+3", "8-1", "6"
            if "+" in rest:
                sides_str, bonus_str = rest.split("+", 1)
                bonus = int(bonus_str)
            elif "-" in rest:
                sides_str, bonus_str = rest.split("-", 1)
                bonus = -int(bonus_str)
            else:
                sides_str = rest
            n_str = f[:d_idx]
            n     = int(n_str) if n_str else 1
            s     = int(sides_str)
            return max(1, n), max(2, s), bonus
        return 1, 6, 0
    except (ValueError, IndexError, AttributeError):
        return 1, 6, 0


def _normalize_sheet(sheet: dict) -> None:
    """
    Garante que todos os campos numéricos da ficha sejam int.
    JSON importado pode trazer valores como strings — isso corrige silenciosamente.
    Chamado em _get_char toda vez que uma ficha é acessada.
    """
    INT_FIELDS = (
        "nivel", "xp", "xp_proximo", "proficiencia", "hit_die",
        "vida_atual", "vida_max", "mana_atual", "mana_max", "ca",
        "forca", "destreza", "constituicao", "inteligencia", "sabedoria", "carisma",
        "ouro", "prata", "cobre",
        "death_saves_sucessos", "death_saves_falhas",
        "vida_temp",
    )
    for field in INT_FIELDS:
        if field in sheet and not isinstance(sheet[field], int):
            try:
                sheet[field] = int(sheet[field])
            except (ValueError, TypeError):
                sheet[field] = 0
    # Campos da Onda 2 — fichas antigas não os têm.
    sheet.setdefault("vida_temp", 0)
    sheet.setdefault("concentracao", None)
    for campo in ("resistencias", "imunidades", "vulnerabilidades"):
        sheet.setdefault(campo, [])


# ===========================================================================
# TIPOS DE DANO, PV TEMPORÁRIOS E CONCENTRAÇÃO
# ---------------------------------------------------------------------------
# Antes, o dano era subtraído cru do HP: `vida_atual -= dmg`. Sem tipo de
# dano não existe resistência, imunidade nem vulnerabilidade — o esqueleto
# morria de veneno, o elemental do fogo se queimava, e a decisão "qual arma
# eu uso contra ISTO", que é o coração do combate 5e, não existia.
#
# Todo dano do jogo passa agora por _apply_damage(), na ordem do PHB:
#   modificador de tipo (imunidade/resistência/vulnerabilidade)
#     → PV temporários absorvem
#       → PV reais
#         → teste de concentração
# ===========================================================================

# Os 13 tipos canônicos do 5e. A chave é o nome em inglês (como vem do SRD).
DAMAGE_TYPES = (
    "acid", "bludgeoning", "cold", "fire", "force", "lightning", "necrotic",
    "piercing", "poison", "psychic", "radiant", "slashing", "thunder",
)

# Aliases PT-BR e variantes → tipo canônico. As descrições de habilidade da
# ficha estão em português ("3d6 dano de fogo"), o SRD vem em inglês.
_DAMAGE_TYPE_ALIASES = {
    "acido": "acid", "ácido": "acid",
    "concussao": "bludgeoning", "concussão": "bludgeoning",
    "contundente": "bludgeoning", "esmagamento": "bludgeoning",
    "frio": "cold", "gelo": "cold", "gelado": "cold",
    "fogo": "fire", "ígneo": "fire", "igneo": "fire",
    "forca": "force", "força": "force",
    "eletrico": "lightning", "elétrico": "lightning",
    "raio": "lightning", "relampago": "lightning", "relâmpago": "lightning",
    "necrotico": "necrotic", "necrótico": "necrotic",
    "perfurante": "piercing", "perfuracao": "piercing", "perfuração": "piercing",
    "veneno": "poison", "venenoso": "poison", "toxico": "poison", "tóxico": "poison",
    "psiquico": "psychic", "psíquico": "psychic", "mental": "psychic",
    "radiante": "radiant", "sagrado": "radiant",
    "cortante": "slashing", "corte": "slashing",
    "trovejante": "thunder", "trovao": "thunder", "trovão": "thunder",
    "sonico": "thunder", "sônico": "thunder",
}


def _norm_damage_type(texto: str) -> str:
    """Normaliza um nome de tipo de dano (PT ou EN) para o canônico. '' se não reconhecer."""
    t = _norm_txt(texto)
    if not t:
        return ""
    if t in DAMAGE_TYPES:
        return t
    return _DAMAGE_TYPE_ALIASES.get(t, "")


def _damage_type_from_text(texto: str) -> str:
    """
    Descobre o tipo de dano varrendo um texto livre.
    Serve tanto para o SRD  ("Hit: 14 (2d8 + 5) slashing damage")
    quanto para a ficha em PT ("[Evocação] Cone de 4,5m, 3d6 dano de fogo").
    Devolve '' quando não há tipo — dano sem tipo não sofre nenhum modificador.
    """
    t = _norm_txt(texto)
    if not t:
        return ""
    # Inglês: "<tipo> damage" é o padrão do SRD.
    for tipo in DAMAGE_TYPES:
        if f"{tipo} damage" in t:
            return tipo
    # Português: "dano de fogo", "dano necrótico", "dano radiante".
    import re as _re
    m = _re.search(r"dano\s+(?:de\s+|do\s+|da\s+)?([a-z]+)", t)
    if m:
        canon = _norm_damage_type(m.group(1))
        if canon:
            return canon
    # Último recurso: qualquer alias solto no texto.
    for alias, canon in _DAMAGE_TYPE_ALIASES.items():
        if _norm_txt(alias) in t:
            return canon
    for tipo in DAMAGE_TYPES:
        if tipo in t:
            return tipo
    return ""


def _parse_damage_traits(raw) -> list[dict]:
    """
    Lê um campo de resistência/imunidade do Open5e e devolve entradas
    estruturadas.

    O SRD escreve coisas como:
      "poison"
      "fire, cold"
      "bludgeoning, piercing, and slashing from nonmagical attacks"

    A última é a armadilha: aplicar essa resistência sem modelar armas
    mágicas deixaria o lobisomem praticamente imune ao grupo. Então a
    qualificação é PRESERVADA em `requer_magica`, e _damage_multiplier só
    ignora a resistência quando o golpe é mágico.
    """
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        raw = ", ".join(str(x) for x in raw)
    texto = _norm_txt(str(raw))
    if not texto:
        return []

    # "from nonmagical attacks", "that aren't silvered", "nao magicas"…
    requer_magica = any(marca in texto for marca in (
        "nonmagical", "non-magical", "nao magic", "silvered", "adamantine",
    ))

    tipos = []
    for tipo in DAMAGE_TYPES:
        if tipo in texto and tipo not in tipos:
            tipos.append(tipo)
    for alias, canon in _DAMAGE_TYPE_ALIASES.items():
        if _norm_txt(alias) in texto and canon not in tipos:
            tipos.append(canon)

    if not tipos:
        return []
    return [{"tipos": tipos, "requer_magica": requer_magica, "origem": str(raw)}]


def _traits_lookup(sheet: dict, campo: str) -> list[dict]:
    """Lê resistencias/imunidades/vulnerabilidades da ficha, tolerando formatos antigos."""
    bruto = (sheet or {}).get(campo)
    if not bruto:
        base = []
    elif isinstance(bruto, list) and bruto and isinstance(bruto[0], dict):
        base = bruto
    else:
        # Lista simples de strings (ex.: preenchida à mão) → normaliza.
        base = _parse_damage_traits(bruto)
    if campo == "resistencias":
        # Poção de Resistência: vale enquanto o efeito estiver na ficha.
        # Fúria e Pele de Pedra: vários tipos de uma vez (`resistencias`).
        extra = [{"tipos": [e["resistencia"]] if e.get("resistencia") else list(e["resistencias"]),
                  "requer_magica": False, "origem": e.get("origem", e.get("nome", ""))}
                 for e in _efeitos(sheet or {})
                 if e.get("resistencia") or e.get("resistencias")]
        if extra:
            return list(base) + extra
    if campo == "imunidades":
        extra = [{"tipos": list(e["imunidades"]), "requer_magica": False,
                  "origem": e.get("origem", e.get("nome", ""))}
                 for e in _efeitos(sheet or {}) if e.get("imunidades")]
        if extra:
            return list(base) + extra
    return base


# Materiais que furam a resistência "de ataques não-mágicos" sem a arma ser
# mágica. O SRD escreve "that aren't silvered" / "that aren't adamantine";
# sem isto, a espada prateada comprada justamente para caçar lobisomem não
# faria nada.
_MATERIAIS_ESPECIAIS = (
    "prata", "pratead", "silver", "adamant", "gelido", "gélido", "cold iron",
    "ferro frio",
)


def _bypasses_material_resistance(weapon: str) -> bool:
    """A arma fura resistências qualificadas — por ser mágica ou pelo material."""
    nome = _norm_txt(weapon)
    if not nome:
        return False
    a = _itens.arma(weapon)
    if (a and a["magica"]) or _looks_magic(weapon):
        return True
    return any(_norm_txt(m) in nome for m in _MATERIAIS_ESPECIAIS)


# ── Defesas descobertas ────────────────────────────────────────────────────
# Resistência, imunidade e vulnerabilidade de um INIMIGO são informação de
# jogo: quem enfrenta um zumbi só sabe que o fogo dói mais nele depois de
# atear fogo nele (ou de estudar o bicho). A ficha guarda o que o grupo já
# viu; o card da tela mostra só isso.
_CAMPOS_DE_DEFESA = ("resistencias", "imunidades", "vulnerabilidades")


def _marcar_descoberta(sheet: dict, campo: str, tipo: str) -> None:
    """Anota que o grupo viu esta defesa. Idempotente."""
    if not tipo or campo not in _CAMPOS_DE_DEFESA:
        return
    desc = sheet.get("descobertas")
    if not isinstance(desc, dict):
        desc = {}
        sheet["descobertas"] = desc
    lista = desc.get(campo)
    if not isinstance(lista, list):
        lista = []
        desc[campo] = lista
    if tipo not in lista:
        lista.append(tipo)


def _ja_descoberto(sheet: dict, campo: str, tipo: str) -> bool:
    desc = sheet.get("descobertas")
    if not isinstance(desc, dict):
        return False
    return tipo in (desc.get(campo) or [])


def _damage_multiplier(sheet: dict, tipo: str,
                       arma_magica: bool = False) -> tuple[float, str]:
    """
    Multiplicador de dano do alvo para um tipo. Devolve (multiplicador, nota).

    Regras 5e: imunidade zera; resistência corta pela metade (arredonda para
    baixo, feito no chamador); vulnerabilidade dobra. Resistência e
    vulnerabilidade ao mesmo tipo se cancelam, e imunidade vence as duas.
    Dano SEM tipo nunca é modificado.
    """
    if not tipo:
        return 1.0, ""

    def _casa(campo: str) -> bool:
        for entrada in _traits_lookup(sheet, campo):
            if tipo not in entrada.get("tipos", []):
                continue
            if entrada.get("requer_magica") and arma_magica:
                continue        # arma mágica fura a resistência qualificada
            return True
        return False

    imune   = _casa("imunidades")
    resiste = _casa("resistencias")
    vulner  = _casa("vulnerabilidades")

    if imune:
        return 0.0, f"IMUNE a dano {tipo} — nenhum dano aplicado"
    if resiste and vulner:
        return 1.0, f"Resistência e vulnerabilidade a {tipo} se cancelam"
    if resiste:
        return 0.5, f"Resistente a dano {tipo} — dano pela metade"
    if vulner:
        return 2.0, f"VULNERÁVEL a dano {tipo} — dano dobrado"
    return 1.0, ""


# ── PV temporários ─────────────────────────────────────────────────────────

def _temp_hp(sheet: dict) -> int:
    try:
        return max(0, int(sheet.get("vida_temp", 0) or 0))
    except (TypeError, ValueError):
        return 0


# ── Concentração ───────────────────────────────────────────────────────────

def _requires_concentration(hab: dict) -> bool:
    """A habilidade exige concentração? Lê a descrição (PT e EN)."""
    if not isinstance(hab, dict):
        return False
    if hab.get("concentracao") is not None:
        return bool(hab["concentracao"])
    # Magia do SRD: o compêndio sabe. Pelo texto, Imobilizar Pessoa com
    # descrição curta na ficha não concentrava — e a paralisia, presa à
    # concentração, caía na mesma hora.
    srd = _srd(hab)
    if srd is not None:
        return bool(srd.get("concentracao"))
    texto = _norm_txt(f"{hab.get('descricao', '')} {hab.get('nome', '')}")
    return "concentracao" in texto or "concentration" in texto


def _break_concentration(char: dict, motivo: str = "") -> str:
    """Derruba a concentração ativa. Devolve a nota, ou '' se não havia nenhuma."""
    sheet = char.get("sheet") or {}
    atual = sheet.get("concentracao")
    if not atual:
        return ""
    sheet["concentracao"] = None
    magia = (atual or {}).get("magia", "magia")
    sufixo = f" ({motivo})" if motivo else ""
    _log_combat_event("concentration_break", char.get("name", ""), "",
                      msg=f"{char.get('name','')} perdeu a concentração em {magia}{sufixo}")
    from rpg import criaturas
    sumiram = criaturas.limpar()
    return (f"{char.get('name','')} PERDEU a concentração em {magia}{sufixo}!"
            + (" " + " ".join(sumiram) if sumiram else ""))


def _start_concentration(char: dict, magia: str) -> str:
    """
    Passa a concentrar numa magia. Em 5e só se concentra numa por vez — a
    anterior cai. Antes disto, um clérigo mantinha Bênção, Escudo da Fé e
    Arma Espiritual ao mesmo tempo.
    """
    sheet = char.get("sheet") or {}
    nota  = ""
    atual = sheet.get("concentracao")
    if atual and (atual or {}).get("magia", "").lower() != (magia or "").lower():
        nota = (f"\n   {char.get('name','')} solta a concentração em "
                f"{atual['magia']} para conjurar {magia}.")
    cs = memory.campaign.get("combat_state", {}) or {}
    sheet["concentracao"] = {"magia": magia, "rodada": int(cs.get("round", 1) or 1)}
    if nota:
        from rpg import criaturas
        sumiram = criaturas.limpar()
        if sumiram:
            nota += "\n   " + " ".join(sumiram)
    return nota


def _concentration_save(char: dict, dano: int) -> str:
    """
    Teste de CON para manter a concentração ao sofrer dano.
    CD = maior entre 10 e metade do dano (PHB).

    O dado é rolado pelo sistema, inclusive para personagens jogáveis: o
    teste dispara no meio do turno do INIMIGO, e parar tudo para pedir um d20
    ao jogador quebraria o fluxo do combate. O resultado é sempre mostrado.
    """
    sheet = char.get("sheet") or {}
    if not sheet.get("concentracao"):
        return ""
    magia = sheet["concentracao"].get("magia", "magia")
    dc    = max(10, dano // 2)
    mod   = _modifier(sheet.get("constituicao", 10))
    # Exaustão 3+: desvantagem em testes de resistência. Este é o único save
    # que o MOTOR rola (os demais chegam com o d20 já rolado pelo jogador),
    # então é o único em que dá para cobrar a regra em vez de só avisar.
    exausto = _exaustao(sheet) >= 3
    d20, log_d20 = _roll_d20_with_adv(False, exausto)
    total = d20 + mod
    sinal = "+" if mod >= 0 else ""
    marca = " (desvantagem: exaustão)" if exausto else ""

    if total >= dc:
        return (f"Concentração ({magia}): {log_d20}{sinal}{mod} = {total} "
                f"vs CD {dc}{marca} → mantida")
    quebra = _break_concentration(char, f"falhou no teste CD {dc}")
    return (f"Concentração ({magia}): {log_d20}{sinal}{mod} = {total} "
            f"vs CD {dc}{marca} → FALHOU\n   {quebra}")


# ── Aplicação de dano — caminho único de todo dano do jogo ─────────────────

def _apply_damage(target: dict, amount: int = 0, damage_type: str = "",
                  source_name: str = "", arma_magica: bool = False,
                  components: list | None = None, critico: bool = False) -> dict:
    """
    Aplica dano a um alvo na ordem do 5e e devolve o que aconteceu.

    `components` permite um golpe com tipos MISTOS — o caso do Golpe Divino,
    que soma 1d8 radiante ao corte da arma. Cada componente recebe o próprio
    modificador de resistência, e só depois a soma encontra os PV temporários
    e um único teste de concentração (RAW: dano simultâneo de um mesmo ataque
    provoca um teste, não um por parcela).

    Devolve dict com: dano (efetivo em PV reais), bruto, hp_antes, hp_depois,
    temp_absorvido e notas (lista de linhas para o texto da ferramenta).

    NÃO mexe em status (inconsciente/morto) nem avança turno — isso continua
    com quem chamou, que tem o contexto para narrar.
    """
    sheet = target.get("sheet") or {}
    notas: list[str] = []

    if components is None:
        components = [(int(amount or 0), damage_type)]

    bruto = 0
    dano  = 0
    tipo  = _norm_damage_type(damage_type) if damage_type else ""
    for valor, tipo_comp in components:
        parcela_bruta = max(0, int(valor or 0))
        if not parcela_bruta:
            continue
        bruto += parcela_bruta
        canon = _norm_damage_type(tipo_comp) if tipo_comp else ""
        if not tipo:
            tipo = canon
        # Silêncio: dentro dele, dano de trovão não fere. É a zona, não a
        # criatura — não vira imunidade descoberta da ficha.
        if canon == "thunder" and _zona_silenciada(target.get("name", "")):
            notas.append(f"{_zona_silenciada(target.get('name', ''))}: imune a trovão "
                         f"({parcela_bruta} de dano trovejante anulado)")
            continue
        mult, nota_tipo = _damage_multiplier(sheet, canon, arma_magica)
        if nota_tipo:
            # O golpe mostrou a defesa na prática: ela deixa de ser segredo.
            if mult == 0.0:
                _marcar_descoberta(sheet, "imunidades", canon)
            elif mult == 0.5:
                _marcar_descoberta(sheet, "resistencias", canon)
            elif mult == 2.0:
                _marcar_descoberta(sheet, "vulnerabilidades", canon)
            else:   # resistência e vulnerabilidade se cancelando
                _marcar_descoberta(sheet, "resistencias", canon)
                _marcar_descoberta(sheet, "vulnerabilidades", canon)
            if len(components) > 1:
                nota_tipo += f" ({parcela_bruta} de dano {canon or 'sem tipo'})"
            notas.append(nota_tipo)
        parcela = int(parcela_bruta * mult) if mult != 1.0 else parcela_bruta
        # Resistência nunca zera um golpe que acertou; só imunidade zera.
        if mult > 0:
            parcela = max(1, parcela)
        dano += parcela

    # PV temporários absorvem primeiro e não voltam.
    temp = _temp_hp(sheet)
    absorvido = 0
    if temp > 0 and dano > 0:
        absorvido = min(temp, dano)
        sheet["vida_temp"] = temp - absorvido
        dano -= absorvido
        restante = sheet["vida_temp"]
        notas.append(f"PV temporários absorveram {absorvido} "
                     f"({'restam ' + str(restante) if restante else 'esgotados'})")

    hp_antes = int(sheet.get("vida_atual", 0) or 0)
    sheet["vida_atual"] = max(0, hp_antes - dano)
    hp_depois = sheet["vida_atual"]

    # Forma Selvagem: a fera caiu, o druida volta e leva o dano que sobrou.
    if hp_depois == 0 and hp_antes > 0 and not sheet.get("_forma_selvagem"):
        _guarda_m = next((e for e in _efeitos(sheet) if e.get("protecao_morte")), None)
        if _guarda_m:
            sheet["vida_atual"] = hp_depois = 1
            sheet["efeitos"] = [x for x in sheet.get("efeitos") or [] if x is not _guarda_m]
            notas.append(f"{_guarda_m.get('nome', 'Proteção contra a Morte')}: {target.get('name')} fica com 1 PV "
                         f"(a magia acaba)")

    # Fortitude Morta-Viva (zumbi): CON contra 5 + dano, e fica com 1 PV.
    if hp_depois == 0 and hp_antes > 0 and not sheet.get("_forma_selvagem"):
        from rpg import tracos as _tracos_d
        _tipos_d = {_norm_damage_type(t) for v, t in components if t and int(v or 0) > 0}
        _fort = _tracos_d.fortitude_morta_viva(target, dano, _tipos_d, critico)
        if _fort:
            notas.append(_fort)
            if _fort.endswith("1 PV"):
                sheet["vida_atual"] = hp_depois = 1

    if hp_depois == 0 and sheet.get("_forma_selvagem"):
        from rpg import criaturas
        notas.append(criaturas.quando_a_fera_cai(target, max(0, dano - hp_antes)))
        hp_depois = int(sheet.get("vida_atual", 0) or 0)

    # Vínculo Protetor: quem conjurou leva o mesmo dano (sem resistência).
    if dano > 0:
        for _e in _efeitos(sheet):
            _guarda = memory.campaign.get("characters", {}).get(_e.get("vinculo") or "")
            if _guarda and _guarda is not target and (_guarda.get("sheet") or {}).get("vida_atual", 0):
                _gs = _guarda["sheet"]
                _antes_g = int(_gs.get("vida_atual", 0) or 0)
                _gs["vida_atual"] = max(0, _antes_g - dano)
                notas.append(f"Vínculo Protetor: {_guarda.get('name')} leva {dano} "
                             f"({_antes_g} → {_gs['vida_atual']})")
                if _gs["vida_atual"] == 0:
                    notas.append(_mark_at_zero_hp(_guarda, "Vínculo Protetor").strip())

    # O enfeitiçado ferido por quem o enfeitiçou (ou pelo lado dele): o
    # encanto quebra. É a regra do Enfeitiçar Pessoa.
    if dano > 0 and source_name:
        from rpg import encantos
        quebrou = encantos.ferido_por(target, source_name)
        if quebrou:
            notas.append(quebrou)

    # Concentração: só testa se realmente perdeu PV reais.
    if dano > 0 and sheet.get("concentracao"):
        if hp_depois == 0:
            quebra = _break_concentration(target, "caiu a 0 PV")
            if quebra:
                notas.append(quebra)
        else:
            nota_conc = _concentration_save(target, dano)
            if nota_conc:
                notas.append(nota_conc)

    return {
        "dano": dano, "bruto": bruto, "hp_antes": hp_antes,
        "hp_depois": hp_depois, "temp_absorvido": absorvido,
        "tipo": tipo, "notas": notas,
    }


def _fmt_notas(notas: list[str], indent: str = "   ") -> str:
    """Formata as notas de _apply_damage como linhas prontas para anexar."""
    return "".join(f"\n{indent}{n}" for n in notas if n)


# ===========================================================================
# ZONAS — posicionamento sem grid
# ---------------------------------------------------------------------------
# O combate não tinha lugar nenhum: todos podiam acertar todos, corpo-a-corpo
# alcançava o arqueiro do outro lado do salão e o ataque de oportunidade só
# existia na fuga, porque não havia movimento que ele pudesse punir.
#
# Grid quadriculado seria pior que o problema — exigiria coordenadas do LLM a
# cada turno e uma tela de tabuleiro. Zonas dão o que importa (perto/longe,
# quem está trancado com quem, terreno com nome) a um custo de uma palavra por
# combatente.
#
# Topologia LINEAR: as zonas formam uma trilha, e a adjacência são os vizinhos
# na lista. Distância = diferença de índice.
#
#     ["Portão", "Pátio", "Sacada"]     Portão↔Pátio = 1     Portão↔Sacada = 2
#
# Regras que isso passa a sustentar:
#     mesma zona (0)   corpo-a-corpo vale; à distância fica com desvantagem
#                      (5e: atirar com inimigo colado em você)
#     adjacente (1)    só à distância, sem penalidade
#     2 ou mais        só à distância, com desvantagem (alcance longo)
#     sair de uma zona com inimigo consciente provoca ataque de oportunidade
#
# TUDO É OPCIONAL. Sem set_battlefield() chamado, cs["zonas"] não existe e o
# combate se comporta exatamente como antes — campanhas antigas e o modo
# narrado não mudam de regra no meio do caminho.
# ===========================================================================

def _zonas() -> list[str]:
    cs = memory.campaign.get("combat_state") or {}
    z  = cs.get("zonas")
    return list(z) if isinstance(z, list) else []


def _zonas_ativas() -> bool:
    return len(_zonas()) > 1


def _zona_canonica(nome: str) -> str:
    """Casa o nome informado com uma zona existente, ignorando caixa/acento."""
    alvo = _norm_txt(nome or "")
    for z in _zonas():
        if _norm_txt(z) == alvo:
            return z
    return ""


def _zona_de(char_name: str) -> str:
    cs = memory.campaign.get("combat_state") or {}
    return (cs.get("posicoes") or {}).get(memory.char_key(char_name), "")


# ===========================================================================
# EFEITOS DE ZONA: Escuridão, Névoa Obscurecente, Silêncio
# ---------------------------------------------------------------------------
# A área da magia é a zona escolhida. Vale enquanto quem conjurou mantém a
# concentração nela, e acaba com o combate.
#   escuridao / nevoa  ninguém vê quem está lá, e quem está lá não vê nada:
#                      nos ataques, vantagem e desvantagem se anulam; magia
#                      que exige ver o alvo não passa; esconder-se é automático
#   silencio           nada de componente verbal lá dentro; imune a trovão
# ===========================================================================

def _efeitos_de_zona(zona: str) -> list[dict]:
    cs = memory.campaign.get("combat_state") or {}
    if not zona or not cs.get("is_active"):
        return []
    saida = []
    for e in cs.get("efeitos_de_zona") or []:
        if not isinstance(e, dict):
            continue
        onde = _zona_de(e["segue"]) if e.get("segue") else e.get("zona")
        if onde != zona:
            continue
        if e.get("concentracao_de") and not _concentracao_segue(e):
            continue
        saida.append(e)
    return saida


def _areas_sobre(nome: str) -> list[dict]:
    """
    As áreas que cobrem `nome`: a da zona dele, com zonas; sem zonas, as
    centradas nele.
    """
    if _zonas_ativas():
        return _efeitos_de_zona(_zona_de(nome))
    cs = memory.campaign.get("combat_state") or {}
    if not cs.get("is_active"):
        return []
    chave = memory.char_key(nome or "")
    return [e for e in cs.get("efeitos_de_zona") or []
            if isinstance(e, dict) and e.get("criatura") == chave
            and not (e.get("concentracao_de") and not _concentracao_segue(e))]


# ── Luz e visão no escuro ────────────────────────────────────────────────────
# A luz de cada lugar: "clara" (padrão), "penumbra" ou "escuridao". O Mestre
# marca com set_light (zona, ou o campo inteiro); a Luz, as Luzes Dançantes,
# a Luz do Dia e a tocha acesa iluminam. Na escuridão, quem não tem visão no
# escuro não vê: ataca com desvantagem, é atacado com vantagem, não mira
# magia que exige ver, e esconder-se de quem não vê é automático. Na
# penumbra, a Percepção de quem não tem visão no escuro cai 5.
_NIVEIS_DE_LUZ = {"clara": "clara", "luz": "clara", "dia": "clara", "bright": "clara",
                  "penumbra": "penumbra", "meia luz": "penumbra", "dim": "penumbra",
                  "escuridao": "escuridao", "escuro": "escuridao", "dark": "escuridao", "darkness": "escuridao"}
_VISAO_DA_RACA = {"anao": 18, "elfo": 18, "meio-elfo": 18, "meio elfo": 18, "gnomo": 18, "meio-orc": 18,
                  "meio orc": 18, "tiefling": 18, "drow": 36, "orc": 18, "goblin": 18, "kobold": 18,
                  "hobgoblin": 18, "bugbear": 18, "gnoll": 18}


def _tem_tocha(ch: dict | None) -> bool:
    return any(isinstance(i, dict) and any(p in _norm_txt(i.get("nome", "")) for p in ("tocha", "lanterna", "torch",
                                                                                       "lantern", "vela"))
               and int(i.get("qtd", 1) or 1) > 0 for i in (ch or {}).get("inventario") or [])


def _ilumina(ch: dict | None) -> bool:
    """Carrega uma luz acesa (tocha, lanterna)."""
    s = (ch or {}).get("sheet") or {}
    return bool(s.get("luz_acesa")) and _tem_tocha(ch) and \
        (ch.get("status") or "").lower() not in ("morto", "fugiu")


def _luz_no_lugar(nome: str) -> str:
    """A luz onde `nome` está."""
    cs = memory.campaign.get("combat_state") or {}
    if not cs.get("is_active"):
        return "clara"
    if any(e.get("tipo") == "luz" for e in _areas_sobre(nome)):
        return "clara"
    chars = memory.campaign.get("characters") or {}
    na_luta = [chars.get(memory.char_key(n)) for n in cs.get("initiative_order") or []]
    if _zonas_ativas():
        zona = _zona_de(nome)
        if any(c and _ilumina(c) and _zona_de(c.get("name", "")) == zona for c in na_luta):
            return "clara"
        return (cs.get("luz") or {}).get(zona) or cs.get("luz_geral") or "clara"
    # Sem zonas, não há "longe": uma luz acesa ilumina a luta.
    if any(c and _ilumina(c) for c in na_luta) or any(
            isinstance(e, dict) and e.get("tipo") == "luz"
            and not (e.get("concentracao_de") and not _concentracao_segue(e))
            for e in cs.get("efeitos_de_zona") or []):
        return "clara"
    return cs.get("luz_geral") or "clara"


def _visao_no_escuro(ch: dict | None) -> int:
    """Alcance da visão no escuro em metros (0 = não tem)."""
    if not ch:
        return 0
    s = ch.get("sheet") or {}
    dos_itens = max([int(e.get("visao_no_escuro", 0) or 0) for e in _efeitos_dos_itens(s)] or [0])
    if s.get("visao_no_escuro"):
        return max(int(s["visao_no_escuro"]), dos_itens)
    raca = _norm_txt(str(s.get("raca") or ""))
    for chave, metros in _VISAO_DA_RACA.items():
        if re.search(rf"\b{re.escape(chave)}\b", raca):
            return max(metros, dos_itens)
    return dos_itens


def _ve_no_escuro(obs: dict | None, alvo: dict | None) -> bool:
    """`obs` enxerga `alvo` com a luz que há onde o alvo está? (A Escuridão mágica é à parte.)"""
    if not obs or not alvo:
        return True
    if _luz_no_lugar(alvo.get("name", "")) != "escuridao":
        return True
    return _visao_no_escuro(obs) > 0


def set_light(where: str = "", level: str = "clara") -> str:
    """
    A luz do lugar: "clara", "penumbra" ou "escuridao". `where` é uma zona do
    campo de batalha, ou vazio/"todas" para o campo inteiro (o padrão das
    zonas sem nível próprio). Na escuridão, quem não tem visão no escuro
    (anões, elfos, gnomos, meio-orcs, tieflings, muitos monstros têm) não vê:
    ataca com desvantagem, é atacado com vantagem e não mira magia que exige
    ver. Na penumbra, a Percepção dele cai 5. Tocha acesa, Luz, Luzes
    Dançantes e Luz do Dia iluminam a zona.
    """
    nivel = _NIVEIS_DE_LUZ.get(_norm_txt(level or "").replace("ã", "a"))
    if not nivel:
        return 'Erro: nível de luz: "clara", "penumbra" ou "escuridao".'
    cs = memory.campaign.setdefault("combat_state", {})
    alvo = (where or "").strip()
    if not alvo or _norm_txt(alvo) in ("todas", "todo", "geral", "campo"):
        cs["luz_geral"] = nivel
        cs.pop("luz", None) if not _zonas_ativas() else None
        memory.save_campaign()
        return f"Luz do campo inteiro: {nivel}."
    zona = next((z for z in _zonas() if _norm_txt(z) == _norm_txt(alvo)), "")
    if not zona:
        return f"Erro: zona desconhecida: {alvo}. Zonas: {', '.join(_zonas()) or 'nenhuma (use o campo inteiro)'}."
    cs.setdefault("luz", {})[zona] = nivel
    memory.save_campaign()
    return f"Luz em {zona}: {nivel}."


# ── Componente material caro ────────────────────────────────────────────────
# A bolsa de componentes não cobre o que tem preço ("um diamante de 300 po").
# A magia do personagem do grupo pede o item na mochila (pelo nome), e gasta
# um quando a magia o consome. Revivificar e as ressurreições já cobram o
# diamante no caminho delas (rpg/resolucao.py).
_MATERIAIS = (
    ("diamond", ("diamante", "diamond")), ("black pearl", ("perola negra", "black pearl")),
    ("pearl", ("perola", "pearl")), ("ruby", ("rubi", "ruby")), ("sapphire", ("safira", "sapphire")),
    ("emerald", ("esmeralda", "emerald")), ("jacinth", ("jacinto", "jacinth")), ("agate", ("agata", "agate")),
    ("jade", ("jade",)), ("gold dust", ("po de ouro", "ouro em po", "gold dust")),
    ("platinum", ("platina", "platinum")), ("ink", ("tinta", "ink")), ("incense", ("incenso", "incense")),
    ("holy water", ("agua benta", "holy water")), ("silver", ("prata", "silver")),
    ("crystal ball", ("bola de cristal",)), ("mirror", ("espelho", "mirror")), ("statuette", ("estatueta",)),
    ("bowl", ("tigela", "taca", "bowl")), ("reliquary", ("relicario", "reliquary")), ("rod", ("bastao", "forquilha", "rod")),
    ("ivory", ("marfim", "ivory")), ("circlet", ("diadema", "tiara", "circlet")), ("chest", ("bau", "chest")),
    ("oils", ("oleo", "unguento", "oil")), ("herbs", ("ervas", "herbs")), ("charcoal", ("carvao", "charcoal")),
    ("jewel", ("joia", "gema", "jewel", "gem")), ("gem", ("joia", "gema", "gem")),
    ("focus", ("foco", "chifre", "olho de vidro", "focus")),
    ("sticks", ("varetas", "ossos", "runas", "cartas", "sticks")), ("tools", ("varetas", "ossos", "runas", "cartas")),
)


def componente_caro(hab: dict) -> dict | None:
    """{"texto", "custo", "consome", "palavras"} da magia do SRD com componente de preço; None se não tem."""
    from rpg import resolucao as _r
    m = _r._magia_srd(hab) or {}
    texto = m.get("material") or ""
    achado = (re.search(r"worth (?:at least )?([\d,]+) ?gp", texto, re.I)
              or re.search(r"([\d,]+) ?gp worth", texto, re.I))
    if not achado:
        return None
    t = texto.lower()
    palavras = next((pt for en, pt in _MATERIAIS if en in t), ())
    if not palavras:
        return None
    return {"texto": texto, "custo": int(achado.group(1).replace(",", "")),
            "consome": "consume" in t, "palavras": palavras}


def _item_do_componente(char: dict, comp: dict) -> dict | None:
    for it in char.get("inventario") or []:
        if not isinstance(it, dict) or int(it.get("qtd", 1) or 1) <= 0:
            continue
        nome = _norm_txt(it.get("nome", ""))
        if any(_norm_txt(p) in nome for p in comp["palavras"]):
            valor = it.get("valor_po", it.get("valor"))
            try:
                if valor is not None and float(valor) < comp["custo"]:
                    continue
            except (TypeError, ValueError):
                pass
            return it
    return None


def _zona_obscurecida(nome: str) -> str:
    """O nome da magia que cega a área de `nome` (Escuridão, Névoa), ou ''."""
    for e in _areas_sobre(nome):
        if e.get("tipo") in ("escuridao", "nevoa"):
            return e.get("nome", "Escuridão")
    return ""


def _area_do_tipo(nome: str, tipo: str) -> dict | None:
    return next((e for e in _areas_sobre(nome) if e.get("tipo") == tipo), None)


def _protegido_pelo_globo(conjurador: str, alvo: str, circulo: int) -> str:
    """O Globo de Invulnerabilidade barra a magia de até 5º círculo vinda de fora."""
    if circulo > 5:
        return ""
    globo = _area_do_tipo(alvo, "globo")
    if not globo or _area_do_tipo(conjurador, "globo") is globo:
        return ""
    return globo.get("nome", "Globo de Invulnerabilidade")


def _zona_silenciada(nome: str) -> str:
    for e in _areas_sobre(nome):
        if e.get("tipo") == "silencio":
            return e.get("nome", "Silêncio")
    return ""


def _por_zona(char_name: str, zona: str, _junto: bool = True) -> None:
    cs = memory.campaign.setdefault("combat_state", {})
    if cs.get("posicoes", {}).get(memory.char_key(char_name)) != zona:
        # Sair do lugar é sair de trás da cobertura.
        (cs.get("cobertura") or {}).pop(memory.char_key(char_name), None)
    cs.setdefault("posicoes", {})[memory.char_key(char_name)] = zona
    # Montado: cavaleiro e montaria andam juntos.
    if _junto:
        from rpg import manobras as _mb_z
        ch = memory.campaign.get("characters", {}).get(memory.char_key(char_name))
        par = _mb_z.montaria_de(ch) or _mb_z.cavaleiro_de(ch)
        if par:
            _por_zona(par.get("name", ""), zona, _junto=False)


def _distancia(a: str, b: str) -> int | None:
    """
    Zonas entre dois combatentes. None quando não há como saber — sem zonas
    definidas, ou alguém que ninguém posicionou. None significa "a regra de
    alcance não se aplica", nunca "estão longe": o motor não pode inventar
    uma penalidade a partir de dado que não tem.
    """
    zonas = _zonas()
    if len(zonas) < 2:
        return None
    za, zb = _zona_de(a), _zona_de(b)
    if za not in zonas or zb not in zonas:
        return None
    return abs(zonas.index(za) - zonas.index(zb))


def _inimigos_na_zona(char_name: str, zona: str = "") -> list[str]:
    """Adversários conscientes na mesma zona — quem 'tranca' o combatente."""
    if not _zonas_ativas():
        return []
    chars = memory.campaign.get("characters", {})
    eu    = chars.get(memory.char_key(char_name))
    if not eu:
        return []
    zona = zona or _zona_de(char_name)
    if not zona:
        return []
    eu_grupo = memory.luta_com_o_grupo(eu)
    cs = memory.campaign.get("combat_state") or {}
    presos = []
    for nome in cs.get("initiative_order", []) or []:
        outro = chars.get(memory.char_key(nome))
        if not outro or outro is eu:
            continue
        if memory.luta_com_o_grupo(outro) == eu_grupo:
            continue
        if (outro.get("status", "vivo") or "").lower() in OUT_OF_COMBAT_STATUSES:
            continue
        if int((outro.get("sheet") or {}).get("vida_atual", 0) or 0) <= 0:
            continue
        if _zona_de(nome) == zona:
            presos.append(outro.get("name", nome))
    return presos


def _checar_alcance(attacker_name: str, target_name: str, weapon: str) -> tuple[str, bool]:
    """
    Aplica a regra de alcance a um ataque.

    Devolve (recusa, desvantagem):
      recusa != ""  → o ataque não pode acontecer (corpo-a-corpo fora da zona)
      desvantagem   → acontece, mas com desvantagem

    Sem zonas em jogo devolve ("", False) — nada muda.
    """
    dist = _distancia(attacker_name, target_name)
    if dist is None:
        return "", False

    a_ranged = _weapon_is_ranged(weapon)
    if not a_ranged:
        if dist > 0:
            za, zb = _zona_de(attacker_name), _zona_de(target_name)
            return (
                f"Erro: FORA DE ALCANCE: {attacker_name} está em **{za}** e "
                f"{target_name}, em **{zb}**. Corpo-a-corpo só na mesma zona — "
                f"use move_combatant('{attacker_name}', '{zb}') primeiro "
                f"(sair de uma zona com inimigo provoca ataque de oportunidade)."
            ), False
        return "", False

    # À distância: colado no inimigo atrapalha; muito longe também.
    if dist == 0 and _inimigos_na_zona(attacker_name):
        return "", True
    if dist >= 2:
        return "", True
    return "", False


def _weapon_is_ranged(weapon: str) -> bool:
    """
    Arma à distância? Usa a lista do motor (RANGED_WEAPONS, em inglês do SRD)
    mais os termos em português que a mesa usa.
    """
    w = _norm_txt(weapon or "")
    if not w:
        return False
    a = _itens.arma(weapon)
    if a and a["distancia"]:
        return True
    if any(_norm_txt(r) in w for r in RANGED_WEAPONS):
        return True
    return any(t in w for t in ("arco", "besta", "dardo", "funda", "azagaia",
                                "lanca arremess", "flecha", "virote"))


def set_battlefield(zones: str, description: str = "") -> str:
    """
    Define as ZONAS do campo de batalha — o terreno em que o combate acontece.

    As zonas formam uma trilha na ordem informada: vizinhas na lista são
    adjacentes. Corpo-a-corpo só funciona dentro da MESMA zona; ataques à
    distância alcançam qualquer zona, com desvantagem a partir de duas de
    distância. Sair de uma zona ocupada por inimigo provoca ataque de
    oportunidade.

    Chame ANTES ou logo depois de roll_initiative(). Por padrão o grupo entra
    na primeira zona e os inimigos na última — mova quem começar em outro
    lugar com move_combatant(). Chamar de novo com as mesmas zonas não
    reposiciona ninguém.

    Args:
        zones:       Zonas separadas por vírgula, da frente para o fundo.
                     Ex: "Portão, Pátio, Sacada"
        description: Opcional. Descrições na MESMA ordem, separadas por ';'.
                     Ex: "portas de ferro; lama e barris; arqueiros no alto"
    """
    cs = memory.campaign.get("combat_state", {})
    if not cs.get("is_active"):
        return "Nenhum combate ativo. Chame roll_initiative() primeiro."

    nomes = [z.strip() for z in (zones or "").split(",") if z.strip()]
    if len(nomes) < 2:
        return ("Informe pelo menos DUAS zonas separadas por vírgula "
                "(ex: 'Portão, Pátio, Sacada'). Com uma só não há distância.")
    if len(nomes) > 6:
        return "No máximo 6 zonas — acima disso a mesa perde o mapa de vista."
    if len({_norm_txt(n) for n in nomes}) != len(nomes):
        return "Há zonas com o mesmo nome. Dê nomes distintos."

    descs = [d.strip() for d in (description or "").split(";")]

    # O mesmo campo de novo, com a luta rolando: reposicionar todo mundo
    # desfazia os movimentos já feitos. Mantém as posições; só quem ainda não
    # tem zona (quem entrou depois) ganha a padrão.
    atuais = cs.get("zonas") or []
    if cs.get("posicoes") and [_norm_txt(z) for z in atuais] == [_norm_txt(n) for n in nomes]:
        chars = memory.campaign.get("characters", {})
        for nome in cs.get("initiative_order", []) or []:
            ch = chars.get(memory.char_key(nome))
            if ch and _zona_de(nome) not in atuais:
                _por_zona(nome, atuais[0] if memory.luta_com_o_grupo(ch) else atuais[-1])
        if any(descs):
            cs["zona_desc"] = {n: (descs[i] if i < len(descs) else "")
                               for i, n in enumerate(atuais)}
        memory.save_campaign()
        return ("Nota: o campo já está dividido assim; ninguém foi reposicionado.\n"
                + describe_battlefield())

    cs["zonas"]     = nomes
    cs["zona_desc"] = {n: (descs[i] if i < len(descs) else "")
                       for i, n in enumerate(nomes)}

    # Posicionamento inicial: grupo e aliados na frente, inimigos no fundo. É
    # o arranjo de quase todo encontro, e sem um padrão o campo nasceria vazio.
    chars = memory.campaign.get("characters", {})
    cs["posicoes"] = {}
    for nome in cs.get("initiative_order", []) or []:
        ch = chars.get(memory.char_key(nome))
        if not ch:
            continue
        _por_zona(nome, nomes[0] if memory.luta_com_o_grupo(ch) else nomes[-1])

    _log_combat_event("battlefield", msg="Campo dividido em zonas: " + " → ".join(nomes),
                      zonas=nomes)
    memory.save_campaign()
    return describe_battlefield()


def set_combat_side(name: str, side: str) -> str:
    """
    Diz de que lado um personagem luta: "aliado", "inimigo" ou "grupo".

    O motor já deduz sozinho (criatura de spawn_monster é inimigo; personagem
    da história que entra na luta é aliado; NPC hostil ao grupo é inimigo).
    Use esta ferramenta quando a dedução não bastar:

      • o NPC que escoltava o grupo trai no meio da luta
        → set_combat_side("Pip", "inimigo")
      • o vilão que já era personagem da história entra lutando contra vocês
        → set_combat_side("Barão Corvo", "inimigo") ANTES de roll_initiative()
      • o inimigo se rende e passa a lutar com o grupo
        → set_combat_side("Goblin 2", "aliado")

    O aliado luta ao lado do grupo mas NÃO é do grupo: não ganha XP, não sobe
    de nível e não entra na divisão do saque. Para trazer alguém para o grupo
    de verdade, use recruit_character().

    Args:
        name: Nome do personagem.
        side: "aliado", "inimigo", "grupo" ou "rendido" (larga as armas e sai
              da luta, vivo — não precisa morrer para a luta acabar).
    """
    lado = (side or "").strip().lower()
    apelidos = {"aliada": "aliado", "amigo": "aliado", "amiga": "aliado",
                "inimiga": "inimigo", "hostil": "inimigo",
                "party": "grupo", "jogador": "grupo"}
    lado = apelidos.get(lado, lado)
    if lado in ("rendido", "rendida", "rende", "rendicao"):
        char_r, err_r = _get_char(name)
        if not char_r:
            return err_r
        char_r["status"] = "rendido"
        _log_combat_event("surrender", char_r.get("name", name), "", msg=f"{char_r.get('name', name)} se rende")
        memory.save_campaign()
        return (f"{char_r.get('name', name)} se rende: larga as armas e sai da luta, vivo. Se só restarem "
                f"inimigos rendidos, enfeitiçados ou dominados, encerre com end_combat().")
    if lado not in memory.LADOS:
        return ('Erro: lado inválido. Use "aliado", "inimigo", "grupo" ou "rendido".')

    char, err = _get_char(name)
    if not char:
        return err

    if lado == "grupo" and not memory.is_party_member(char):
        return (f'Erro: "grupo" é para quem está no grupo do jogador. Para {char.get("name", name)} '
                f'lutar ao lado do grupo sem entrar nele, use side="aliado"; para trazer de vez, '
                f'use recruit_character().')

    char["lado"] = lado
    # Status e lado eram a mesma coisa: quem lutava contra o grupo ficava com
    # status "inimigo". Agora o lado é dele; o status volta a ser só o estado
    # (vivo, ferido, morto) de quem não é mais inimigo.
    if lado == "inimigo":
        if (char.get("status") or "vivo").lower() not in OUT_OF_COMBAT_STATUSES:
            char["status"] = "inimigo"
    elif (char.get("status") or "").lower() == "inimigo":
        char["status"] = "vivo"
    memory.save_campaign()

    onde = ""
    cs = memory.campaign.get("combat_state") or {}
    if cs.get("is_active") and _zonas_ativas():
        zonas = _zonas()
        alvo  = zonas[0] if lado != "inimigo" else zonas[-1]
        if _zona_de(char.get("name", name)) != alvo:
            _por_zona(char.get("name", name), alvo)
            memory.save_campaign()
            onde = f" Reposicionado em {alvo}."
    return f"{char.get('name', name)} agora luta como {lado}.{onde}"


def describe_battlefield() -> str:
    """
    Mostra as zonas do combate e quem está em cada uma.
    Use para se situar antes de decidir movimento e alvos.
    """
    zonas = _zonas()
    if not zonas:
        return ("Sem zonas definidas — o combate está sendo resolvido sem "
                "posicionamento. Use set_battlefield() para dividir o terreno.")
    cs    = memory.campaign.get("combat_state") or {}
    descs = cs.get("zona_desc") or {}
    chars = memory.campaign.get("characters", {})

    linhas = ["**Campo de batalha:** " + " → ".join(zonas)]
    for z in zonas:
        ocupantes = []
        for nome in cs.get("initiative_order", []) or []:
            if _zona_de(nome) != z:
                continue
            ch = chars.get(memory.char_key(nome))
            if not ch:
                continue
            caido = ((ch.get("status", "vivo") or "").lower() in OUT_OF_COMBAT_STATUSES
                     or int((ch.get("sheet") or {}).get("vida_atual", 0) or 0) <= 0)
            marca = f"[{memory.lado_no_combate(ch)}]"
            ocupantes.append(f"{marca} {ch.get('name', nome)}" + (" (fora)" if caido else ""))
        desc = descs.get(z) or ""
        linhas.append(f"  • **{z}**{' — ' + desc if desc else ''}: "
                      + (", ".join(ocupantes) if ocupantes else "vazia"))
    return "\n".join(linhas)


def move_combatant(name: str, zone: str, dash: bool = False,
                   sem_oportunidade: bool = False) -> str:
    """
    Move um combatente para outra zona.

    Move UMA zona por turno (as zonas vizinhas na trilha). Com dash=True
    (ação de Disparada) move DUAS, gastando a ação do turno.

    Sair de uma zona onde há inimigo consciente provoca ataque de
    oportunidade de cada um deles — é a regra que dá peso ao posicionamento.

    Args:
        name: Nome do combatente.
        zone: Zona de destino.
        dash: True para usar a ação de Disparada e mover duas zonas.
    """

    cs = memory.campaign.get("combat_state", {})
    if not cs.get("is_active"):
        return "Nenhum combate ativo."
    if not _zonas_ativas():
        return ("O campo não tem zonas. Chame set_battlefield() antes de "
                "mover alguém.")

    ch, err = _get_char(name)
    if not ch:
        return err
    nome_real = ch.get("name", name)

    if (ch.get("status", "vivo") or "").lower() in OUT_OF_COMBAT_STATUSES:
        return f"Erro: {nome_real} está fora de combate e não se move."

    destino = _zona_canonica(zone)
    if not destino:
        return (f"Aviso: Zona '{zone}' não existe. Zonas do combate: "
                + ", ".join(_zonas()))

    origem = _zona_de(nome_real)
    if origem == destino:
        return f"Aviso: {nome_real} já está em **{destino}**."

    zonas = _zonas()
    if origem not in zonas:
        # Nunca foi posicionado: entra direto, sem gastar movimento.
        _por_zona(nome_real, destino)
        memory.save_campaign()
        return f"{nome_real} entra em **{destino}**."

    passos  = abs(zonas.index(destino) - zonas.index(origem))
    maximo  = 2 if dash else 1
    if passos > maximo:
        extra = "" if dash else " — ou passe dash=True para usar a Disparada"
        return (f"Erro: **{destino}** está a {passos} zonas de **{origem}**. "
                f"O movimento alcança {maximo}{extra}.")

    # O bote de quem fica: só dispara se havia inimigo trancando a origem —
    # e não para quem desengajou (Ação Ardilosa, Passo do Vento).
    oportunidade = ""
    if _inimigos_na_zona(nome_real, origem) and not sem_oportunidade:
        oportunidade = _provoke_opportunity_attacks(nome_real, "sair da zona")
    elif _inimigos_na_zona(nome_real, origem):
        oportunidade = "\n   Desengajou: sai sem provocar ataque de oportunidade."

    # Um ataque de oportunidade pode ter derrubado quem estava saindo.
    if int((ch.get("sheet") or {}).get("vida_atual", 0) or 0) <= 0:
        memory.save_campaign()
        return (f"{nome_real} tenta ir de **{origem}** para **{destino}**…"
                f"{oportunidade}\n   Cai antes de chegar.")

    _por_zona(nome_real, destino)
    from rpg import manobras as _manobras
    _soltos = _manobras.soltar_quem_agarrou(nome_real)
    if _soltos:
        oportunidade += "\n   " + "; ".join(_soltos) + "."
    verbo = "dispara" if dash else "avança"
    _log_combat_event("move", nome_real, "",
                      msg=f"{nome_real} move-se de {origem} para {destino}",
                      de=origem, para=destino)
    memory.save_campaign()

    trancado = _inimigos_na_zona(nome_real, destino)
    aviso = ""
    if trancado:
        aviso = "\n   Em contato com: " + ", ".join(trancado)
    return (f"{nome_real} {verbo} de **{origem}** para **{destino}**."
            f"{oportunidade}{aviso}")


# ===========================================================================
# RECARGA E AÇÕES LENDÁRIAS
# ---------------------------------------------------------------------------
# Duas coisas que separam um chefe de 5e de um saco de PV, e que faltavam:
#
# RECARGA ("Recharge 5–6"): o sopro do dragão não é usável todo turno nem uma
# vez por luta — no início de cada turno dele rola-se 1d6 e o poder volta se
# der 5 ou 6. É o que faz o grupo jogar contra um relógio que ninguém controla.
#
# AÇÕES LENDÁRIAS: o chefe age FORA do próprio turno, no fim do turno dos
# outros. Sem isso, um único inimigo contra quatro jogadores age 1 vez a cada
# 5 turnos e a luta vira execução. O contador volta ao cheio no início do turno
# do chefe — as duas coisas caem no mesmo gancho, _inicio_de_turno().
# ===========================================================================

def _rolar_recargas(char: dict) -> list[str]:
    """
    Rola a recarga dos poderes gastos deste combatente. Devolve os avisos dos
    que voltaram (lista vazia quando não há nada a recarregar).
    """
    sheet = char.get("sheet") or {}
    recs  = sheet.get("recargas")
    if not isinstance(recs, dict):
        return []
    voltaram = []
    for nome, cfg in recs.items():
        if not isinstance(cfg, dict) or cfg.get("pronto", True):
            continue
        minimo = int(cfg.get("min", 5) or 5)
        d6     = random.randint(1, 6)
        cfg["ultimo_d6"] = d6
        if d6 >= minimo:
            cfg["pronto"] = True
            voltaram.append(f"**{nome}** recarregou (d6={d6}, precisa {minimo}+).")
    if voltaram:
        for aviso in voltaram:
            _log_combat_event("recharge", char.get("name", ""), "", msg=aviso)
    return voltaram


def _repor_lendarias(char: dict) -> None:
    """Devolve as ações lendárias ao cheio no início do turno do chefe."""
    lend = (char.get("sheet") or {}).get("lendarias")
    if isinstance(lend, dict) and lend.get("total"):
        lend["restantes"] = int(lend["total"])


def set_recharge_ability(name: str, ability: str, min_roll: int = 5) -> str:
    """
    Marca um poder como sendo de RECARGA ("Recharge 5–6" do 5e).

    Depois de usado, o poder fica indisponível até que, no início de um turno
    do dono, um d6 role min_roll ou mais. É o que dá ritmo a um sopro de dragão.

    Args:
        name:     Nome da criatura.
        ability:  Nome do poder (ex: 'Sopro de Fogo').
        min_roll: Valor mínimo no d6 para recarregar (5 = 'Recarga 5–6').
    """
    ch, err = _get_char(name)
    if not ch:
        return err
    if not ability.strip():
        return "Informe o nome do poder."
    minimo = max(2, min(6, int(min_roll or 5)))
    sheet  = ch.setdefault("sheet", {}) or ch["sheet"]
    sheet.setdefault("recargas", {})[ability.strip()] = {"min": minimo, "pronto": True}
    memory.save_campaign()
    chance = int(round((7 - minimo) / 6 * 100))
    return (f"**{ability.strip()}** de {ch.get('name', name)} agora é poder de "
            f"recarga {minimo}–6 (~{chance}% por turno).")


def _nome_da_recarga(char: dict, *nomes: str) -> str:
    """
    Sob qual nome esse poder está registrado como recarga, se estiver.

    Recebe VÁRIOS nomes porque a habilidade fica na ficha em inglês e o mestre
    registra a recarga com o nome que ele narra: set_recharge_ability('Sopro
    de Fogo') e a habilidade 'Fire Breath' são o mesmo poder. Procurar só por
    um dos dois deixava a recarga sem efeito, calada.
    """
    recs = (char.get("sheet") or {}).get("recargas") or {}
    for nome in nomes:
        if not nome:
            continue
        for chave in recs:
            if _norm_txt(chave) == _norm_txt(nome):
                return chave
    return ""


def _recarga_pronta(char: dict, ability: str) -> bool:
    recs = (char.get("sheet") or {}).get("recargas") or {}
    for nome, cfg in recs.items():
        if _norm_txt(nome) == _norm_txt(ability):
            return bool(cfg.get("pronto", True))
    return True     # poder sem recarga configurada está sempre disponível


def _gastar_recarga(char: dict, ability: str) -> None:
    recs = (char.get("sheet") or {}).get("recargas") or {}
    for nome, cfg in recs.items():
        if _norm_txt(nome) == _norm_txt(ability):
            cfg["pronto"] = False
            return


def set_legendary_actions(name: str, options: str, count: int = 3) -> str:
    """
    Torna uma criatura LENDÁRIA: ela passa a agir fora do próprio turno.

    Uma criatura lendária tem `count` ações lendárias por rodada, gastas ao
    FINAL do turno de outro combatente (nunca no próprio turno), com
    legendary_action(). O contador volta ao cheio no início do turno dela.

    Args:
        name:    Nome do chefe.
        options: Opções separadas por vírgula. Custo opcional após ':'
                 (padrão 1). Ex: "Ataque de Cauda, Investida Alada:2"
        count:   Ações lendárias por rodada (padrão 3).
    """
    ch, err = _get_char(name)
    if not ch:
        return err

    opcoes = []
    for bruto in (options or "").split(","):
        bruto = bruto.strip()
        if not bruto:
            continue
        nome, _, custo = bruto.partition(":")
        nome = nome.strip()
        if not nome:
            continue
        try:
            c = max(1, int(custo.strip())) if custo.strip() else 1
        except ValueError:
            c = 1
        opcoes.append({"nome": nome, "custo": c})

    if not opcoes:
        return ("Informe pelo menos uma opção. "
                "Ex: set_legendary_actions('Dragão', 'Ataque de Cauda, Investida Alada:2')")

    total = max(1, min(5, int(count or 3)))
    sheet = ch.setdefault("sheet", {}) or ch["sheet"]
    sheet["lendarias"] = {"total": total, "restantes": total, "opcoes": opcoes}
    memory.save_campaign()

    lista = ", ".join(f"{o['nome']} ({o['custo']})" for o in opcoes)
    return (f"{ch.get('name', name)} agora é LENDÁRIA — {total} ações "
            f"lendárias por rodada.\n   Opções: {lista}\n"
            f"   Gaste com legendary_action() no fim do turno de OUTRO "
            f"combatente; o contador volta ao cheio no turno dela.")


def set_legendary_resistance(name: str, uses: int = 3) -> str:
    """
    Resistência Lendária: o chefe pode transformar uma salvaguarda que falhou
    em sucesso, `uses` vezes por dia (3 no SRD). O motor usa sozinho, na
    salvaguarda que o chefe falhar. uses=0 tira.
    """
    ch, err = _get_char(name)
    if not ch:
        return err
    n = max(0, int(uses or 0))
    s = ch.setdefault("sheet", {})
    if not n:
        s.pop("resistencia_lendaria", None)
        memory.save_campaign()
        return f"{ch['name']} não tem mais Resistência Lendária."
    s["resistencia_lendaria"] = {"max": n, "restantes": n}
    memory.save_campaign()
    return (f"{ch['name']}: Resistência Lendária {n}/dia — ao falhar numa salvaguarda, o motor a "
            f"transforma em sucesso enquanto houver uso.")


def set_lair_actions(name: str, actions: str) -> str:
    """
    Ações de covil: no início de cada rodada (contagem 20), o chefe no próprio
    covil usa UMA destas habilidades, nunca a mesma duas rodadas seguidas. O
    motor escolhe e resolve sozinho, num alvo do grupo.

    Args:
        name:    O chefe.
        actions: Nomes das habilidades da ficha dele, separados por vírgula
                 (crie antes com dado, salvaguarda e descrição, como um poder).
    """
    ch, err = _get_char(name)
    if not ch:
        return err
    nomes = [a.strip() for a in (actions or "").split(",") if a.strip()]
    habs = {_norm_txt(h.get("nome", "")): h.get("nome") for h in ch.get("habilidades") or []
            if isinstance(h, dict)}
    faltam = [n for n in nomes if _norm_txt(n) not in habs]
    if faltam:
        return (f"Erro: {ch['name']} não tem estas habilidades: {', '.join(faltam)}. Crie-as na ficha "
                f"antes (nome, dado, salvaguarda e descrição).")
    s = ch.setdefault("sheet", {})
    if not nomes:
        s.pop("acoes_de_covil", None)
        memory.save_campaign()
        return f"{ch['name']} não tem mais ações de covil."
    s["acoes_de_covil"] = [habs[_norm_txt(n)] for n in nomes]
    memory.save_campaign()
    return (f"{ch['name']}: ações de covil {', '.join(s['acoes_de_covil'])} — uma por rodada, no início "
            f"dela, nunca a mesma duas vezes seguidas.")


def _acoes_de_covil(cs: dict, idx: int = 0) -> list[str]:
    """
    No começo de cada rodada (contagem 20), cada chefe com covil usa uma ação
    — não a mesma da rodada anterior. Só na virada: a luta montada no meio de
    uma rodada espera a próxima.
    """
    rodada = int(cs.get("round", 1) or 1)
    if cs.get("_covil_rodada") == rodada:
        return []
    primeira_vez = cs.get("_covil_rodada") is None
    cs["_covil_rodada"] = rodada
    if primeira_vez and idx != 0:
        return []
    linhas = []
    for nm in list(cs.get("initiative_order") or []):
        ch = memory.campaign["characters"].get(memory.char_key(nm))
        s = (ch or {}).get("sheet") or {}
        acoes = s.get("acoes_de_covil") or []
        if (not acoes or (ch.get("status") or "").lower() in OUT_OF_COMBAT_STATUSES
                or int(s.get("vida_atual", 0) or 0) <= 0 or _impedido_de_agir(ch)):
            continue
        opcoes = [a for a in acoes if a != s.get("_covil_ultima")] or acoes
        acao = random.choice(opcoes)
        lado = memory.luta_com_o_grupo(ch)
        alvos = [memory.campaign["characters"].get(memory.char_key(n)) for n in cs.get("initiative_order") or []]
        alvos = [c for c in alvos if c and memory.luta_com_o_grupo(c) != lado
                 and (c.get("status") or "").lower() not in OUT_OF_COMBAT_STATUSES
                 and int((c.get("sheet") or {}).get("vida_atual", 0) or 0) > 0]
        if not alvos:
            continue
        alvo = random.choice(alvos)
        s["_covil_ultima"] = acao
        saida = use_ability(ch["name"], acao, alvo["name"], end_turn=False, _skip_turn_check=True,
                            _motor_rola=True)
        linhas.append(f"AÇÃO DE COVIL (rodada {rodada}) — {ch['name']}: {acao}\n"
                      + saida.replace(_BONUS_ACTION_HINT, "").replace(
                          "\n   Ação bônus disponível — próxima habilidade/ataque neste turno.", ""))
    return linhas


def legendary_action(boss_name: str, option: str, target_name: str = "") -> str:
    """
    Gasta uma ação lendária do chefe, ao final do turno de outro combatente.

    Se a opção casar com um ataque da ficha (ou uma arma), o motor rola o
    ataque de verdade contra o alvo. Caso contrário, apenas debita o custo —
    a opção é narrativa (mover-se, detectar, uivar) e quem narra é você.

    Args:
        boss_name:   Nome da criatura lendária.
        option:      Nome da opção (como definido em set_legendary_actions).
        target_name: Alvo, quando a opção for um ataque.
    """
    cs = memory.campaign.get("combat_state", {})
    if not cs.get("is_active"):
        return "Nenhum combate ativo."

    ch, err = _get_char(boss_name)
    if not ch:
        return err
    nome_real = ch.get("name", boss_name)

    lend = (ch.get("sheet") or {}).get("lendarias")
    if not isinstance(lend, dict) or not lend.get("opcoes"):
        return (f"Aviso: {nome_real} não é uma criatura lendária. "
                f"Use set_legendary_actions() antes.")

    if (ch.get("status", "vivo") or "").lower() in OUT_OF_COMBAT_STATUSES:
        return f"Erro: {nome_real} está fora de combate."
    if int((ch.get("sheet") or {}).get("vida_atual", 0) or 0) <= 0:
        return f"Erro: {nome_real} está caído e não age."

    # A regra: ação lendária acontece no turno DOS OUTROS. No próprio turno o
    # chefe já tem ação, bônus e ataque múltiplo — deixar passar aqui daria a
    # ele um turno duplo.
    order = cs.get("initiative_order") or []
    idx   = cs.get("current_turn_index", 0)
    atual = order[idx] if 0 <= idx < len(order) else ""
    if memory.char_key(atual) == memory.char_key(nome_real):
        return (f"Erro: É o turno de {nome_real}. Ação lendária é gasta no fim do "
                f"turno de OUTRO combatente — use as ações normais dela agora.")

    escolhida = None
    for o in lend["opcoes"]:
        if _norm_txt(o["nome"]) == _norm_txt(option):
            escolhida = o
            break
    if not escolhida:
        disponiveis = ", ".join(o["nome"] for o in lend["opcoes"])
        return f"Aviso: Opção '{option}' não existe. Disponíveis: {disponiveis}"

    restantes = int(lend.get("restantes", 0) or 0)
    custo     = int(escolhida.get("custo", 1) or 1)
    if restantes < custo:
        return (f"Erro: {nome_real} tem {restantes} ação(ões) lendária(s) nesta "
                f"rodada e '{escolhida['nome']}' custa {custo}. "
                f"O contador volta ao cheio no turno dela.")

    lend["restantes"] = restantes - custo
    sobra = lend["restantes"]

    # Ataque de verdade quando a opção casa com algo que a criatura empunha.
    ataque = _npc_attack_entry(ch.get("sheet") or {}, escolhida["nome"])
    e_ataque = bool(ataque) or _weapon_is_ranged(escolhida["nome"]) or bool(target_name)

    cabecalho = (f"**Ação lendária** — {nome_real} usa "
                 f"**{escolhida['nome']}** ({custo}; restam {sobra}).")
    _log_combat_event("legendary", nome_real, target_name,
                      msg=f"{nome_real} usa ação lendária: {escolhida['nome']}",
                      custo=custo, restantes=sobra)

    if not (e_ataque and target_name):
        memory.save_campaign()
        return cabecalho

    golpe = attack_roll(
        attacker_name     = nome_real,
        target_name       = target_name,
        weapon            = escolhida["nome"],
        damage_dice_sides = 6,     # sobrescrito pelo stat block / SRD
        damage_dice_count = 1,
        attack_attribute  = "destreza" if _weapon_is_ranged(escolhida["nome"]) else "forca",
        is_proficient     = True,
        end_turn          = False,   # não é o turno dele: não avança nada
        _skip_turn_check  = True,
    )
    memory.save_campaign()
    return f"{cabecalho}\n{golpe}"


# ===========================================================================
# REAÇÃO E ATAQUE DE OPORTUNIDADE
# ---------------------------------------------------------------------------
# A economia do turno rastreava só Ação e Ação Bônus. Faltava a terceira
# perna do 5e: a Reação — a única coisa que acontece FORA do seu turno.
#
# Na onda 2, sem posicionamento no jogo, o único gatilho honesto era a FUGA:
# sair do combate deixava de ser grátis. Com as zonas da onda 3 a regra ganhou
# o gatilho de verdade — sair de uma zona onde há inimigo consciente também
# provoca (ver move_combatant), e só reage quem está NAQUELA zona.
#
# A reação recarrega por RODADA (em 5e, no início do próprio turno) — daí
# guardarmos o número da rodada em que foi gasta.
# ===========================================================================

# Cobertura (SRD): meia +2 de CA e nas salvaguardas de DES; três quartos +5;
# total, ninguém mira. Com zonas, vale contra quem ataca de outra zona; sem
# zonas, contra ataque à distância. Acaba quando a criatura se move.
_COBERTURA = {"meia": 2, "tres_quartos": 5, "total": 0}
_COBERTURA_NOME = {"meia": "meia cobertura", "tres_quartos": "três quartos de cobertura",
                   "total": "cobertura total"}
_COBERTURA_APELIDO = {"meia": "meia", "half": "meia", "1/2": "meia", "metade": "meia",
                      "tres quartos": "tres_quartos", "tres_quartos": "tres_quartos", "3/4": "tres_quartos",
                      "three-quarters": "tres_quartos", "three quarters": "tres_quartos",
                      "total": "total", "nenhuma": "", "none": "", "sem": "", "": ""}


def _cobertura_de(ch: dict | None) -> str:
    cs = memory.campaign.get("combat_state") or {}
    return (cs.get("cobertura") or {}).get(memory.char_key((ch or {}).get("name", "")), "")


def _cobertura_contra(atacante: dict, alvo: dict, a_distancia: bool) -> tuple[str, int]:
    """(nível, bônus de CA) da cobertura do alvo contra este ataque; ("", 0) quando não vale."""
    nivel = _cobertura_de(alvo)
    if not nivel:
        return "", 0
    if _zonas_ativas():
        if _zona_de(atacante.get("name", "")) == _zona_de(alvo.get("name", "")) and not a_distancia:
            return "", 0
    elif not a_distancia:
        return "", 0
    return nivel, _COBERTURA[nivel]


def set_cover(name: str, level: str = "meia") -> str:
    """
    Cobertura: o que protege uma criatura dos ataques de longe (SRD).

      • meia          +2 de CA e nas salvaguardas de DES (mureta, árvore, outra criatura)
      • tres_quartos  +5 (seteira, tronco grosso)
      • total         ninguém mira nela diretamente (muralha, porta fechada)
      • nenhuma       tira a cobertura

    `name` é uma criatura OU uma zona do campo de batalha. Na zona, diz que
    cobertura há ali: quem usa a manobra "Buscar cobertura" nela recebe esse
    nível. Com zonas, a cobertura vale contra quem ataca de outra zona; sem
    zonas, contra ataque à distância. Acaba quando a criatura se move.
    """
    nivel = _COBERTURA_APELIDO.get(_norm_txt(level or "").replace("ê", "e"), None)
    if nivel is None:
        return 'Erro: nível de cobertura: "meia", "tres_quartos", "total" ou "nenhuma".'
    cs = memory.campaign.setdefault("combat_state", {})
    if name in _zonas() or _norm_txt(name) in {_norm_txt(z) for z in _zonas()}:
        zona = next(z for z in _zonas() if _norm_txt(z) == _norm_txt(name))
        if nivel:
            cs.setdefault("cobertura_zona", {})[zona] = nivel
        else:
            (cs.get("cobertura_zona") or {}).pop(zona, None)
        memory.save_campaign()
        return (f"{zona}: " + (f"{_COBERTURA_NOME[nivel]} para quem se proteger ali." if nivel
                               else "sem cobertura."))
    ch, err = _get_char(name)
    if not ch:
        return err
    if nivel:
        cs.setdefault("cobertura", {})[memory.char_key(ch["name"])] = nivel
    else:
        (cs.get("cobertura") or {}).pop(memory.char_key(ch["name"]), None)
    memory.save_campaign()
    return (f"{ch['name']}: " + (f"{_COBERTURA_NOME[nivel]}"
                                 + (f" (+{_COBERTURA[nivel]} de CA e nas salvaguardas de DES)" if _COBERTURA[nivel]
                                    else " (nenhum ataque o alcança)") if nivel else "sem cobertura."))


def _buscar_cobertura(ator: str) -> str:
    """A manobra: protege-se atrás do que houver (o nível que o Mestre deu à zona, ou meia)."""
    ch = memory.campaign["characters"].get(memory.char_key(ator))
    if not ch:
        return f"Erro: '{ator}' não encontrado."
    cs = memory.campaign.setdefault("combat_state", {})
    zona = _zona_de(ch["name"])
    nivel = (cs.get("cobertura_zona") or {}).get(zona, "meia") if zona else "meia"
    cs.setdefault("cobertura", {})[memory.char_key(ch["name"])] = nivel
    return (f"{ch['name']} se protege atrás do que há{' em ' + zona if zona else ''}: {_COBERTURA_NOME[nivel]}"
            + (f" (+{_COBERTURA[nivel]} de CA e nas salvaguardas de DES contra quem está longe)."
               if _COBERTURA[nivel] else " — nenhum ataque de longe o alcança."))


def _reaction_available(char: dict) -> bool:
    sheet = char.get("sheet") or {}
    # Surpreso não reage até o fim do primeiro turno dele.
    if any(_norm_txt(c.get("nome", "") if isinstance(c, dict) else str(c)) == "surpreso"
           for c in sheet.get("condicoes") or []):
        return False
    cs    = memory.campaign.get("combat_state", {}) or {}
    rodada_atual = int(cs.get("round", 1) or 1)
    usada = sheet.get("reacao_rodada")
    return usada is None or int(usada) != rodada_atual


def _consume_reaction(char: dict) -> None:
    sheet = char.get("sheet") or {}
    cs    = memory.campaign.get("combat_state", {}) or {}
    sheet["reacao_rodada"] = int(cs.get("round", 1) or 1)


def _melee_weapon_of(char: dict) -> str:
    """Arma corpo-a-corpo que a criatura usaria numa reação."""
    sheet = char.get("sheet") or {}
    for atk in (sheet.get("ataques") or []):
        if isinstance(atk, dict) and not atk.get("ranged") and atk.get("nome"):
            return atk["nome"]
    equip = sheet.get("equipamentos", {}) or {}
    return equip.get("arma_principal") or "ataque desarmado"


def _provoke_opportunity_attacks(leaving_name: str, motivo: str = "fugir") -> str:
    """
    Dispara os ataques de oportunidade contra quem está deixando o combate
    (fuga) ou saindo de uma zona ocupada por inimigos.

    Cada inimigo consciente que ainda tem a reação da rodada faz UM ataque
    corpo-a-corpo. Devolve o texto a anexar ('' quando ninguém reagiu).

    Com zonas em jogo, só reage quem está NA MESMA ZONA de quem sai — do
    contrário o arqueiro do outro lado do pátio daria bote em quem nunca
    esteve ao alcance dele.
    """
    cs = memory.campaign.get("combat_state", {}) or {}
    if not cs.get("is_active"):
        return ""

    chars    = memory.campaign.get("characters", {})
    saindo   = chars.get(memory.char_key(leaving_name))
    if not saindo:
        return ""
    saindo_e_grupo = memory.luta_com_o_grupo(saindo)
    zona_saida     = _zona_de(leaving_name) if _zonas_ativas() else ""

    linhas = []
    for nome in list(cs.get("initiative_order", []) or []):
        oponente = chars.get(memory.char_key(nome))
        if not oponente or oponente is saindo:
            continue
        # Só inimigos do lado oposto reagem.
        if memory.luta_com_o_grupo(oponente) == saindo_e_grupo:
            continue
        if (oponente.get("status", "vivo") or "").lower() in OUT_OF_COMBAT_STATUSES:
            continue
        if int((oponente.get("sheet") or {}).get("vida_atual", 0) or 0) <= 0:
            continue
        if not _reaction_available(oponente):
            continue
        # Quem não age (Paralisado, Atordoado) não reage; o enfeitiçado não
        # dá bote em quem o enfeitiçou.
        if _impedido_de_agir(oponente):
            continue
        from rpg import encantos
        if encantos.pode_atacar(oponente, saindo):
            continue
        # Só dá bote quem está em contato — a zona é o "alcance" aqui.
        if zona_saida and _zona_de(nome) != zona_saida:
            continue
        # O alvo pode ter caído num ataque de oportunidade anterior.
        if int((saindo.get("sheet") or {}).get("vida_atual", 0) or 0) <= 0:
            break

        _consume_reaction(oponente)
        golpe = attack_roll(
            attacker_name    = oponente.get("name", nome),
            target_name      = saindo.get("name", leaving_name),
            weapon           = _melee_weapon_of(oponente),
            damage_dice_sides= 6,
            damage_dice_count= 1,
            end_turn         = False,
            _skip_turn_check = True,
        ).replace(_BONUS_ACTION_HINT, "")
        linhas.append(golpe)

    if not linhas:
        return ""
    cabecalho = (f"\n\nATAQUE(S) DE OPORTUNIDADE — {leaving_name} tenta "
                 f"{motivo} e baixa a guarda:")
    return cabecalho + "\n" + "\n".join(linhas)


def _get_char(name: str, allow_dead: bool = False) -> tuple[dict | None, str]:
    """Retorna (char_dict, erro). char é None se não encontrado, sem ficha ou morto."""
    char = memory.campaign["characters"].get(memory.char_key(name))
    if not char:
        return None, f"Erro: Personagem '{name}' não encontrado."
    if not char.get("sheet"):
        return None, f"Erro: '{name}' não tem ficha D&D. Use create_character_sheet primeiro."
    if not allow_dead and char.get("status") == "morto":
        return None, f"Erro: {char['name']} está morto e não pode realizar ações."
    _normalize_sheet(char["sheet"])
    return char, ""


def _hp_bar(current: int, maximum: int, width: int = 10) -> str:
    pct    = current / maximum if maximum > 0 else 0
    filled = int(pct * width)
    return "▓" * filled + "░" * (width - filled)


def _condicao_vale(c, char: dict) -> bool:
    """
    A condição ainda vale? A de magia de concentração (Imobilizar Pessoa)
    cai com a concentração de quem conjurou; a de prazo (`ate_hora`), com o
    relógio; a de encanto, com o encanto (rpg/encantos.py). Antes toda
    condição de magia ficava na ficha para sempre — o orc continuava
    "Paralisado" depois da luta.
    """
    if not isinstance(c, dict):
        return True
    if c.get("ate_hora") is not None and _agora_em_horas() >= int(c["ate_hora"]):
        return False
    if c.get("concentracao_de"):
        conj = memory.campaign.get("characters", {}).get(c["concentracao_de"]) or {}
        atual = ((conj.get("sheet") or {}).get("concentracao") or {})
        if _norm_txt(atual.get("magia", "")) != _norm_txt(c.get("magia", "")):
            return False
    if c.get("encanto"):
        from rpg import encantos
        return encantos.ativo(char) is not None
    return True


def _limpar_condicoes(char: dict) -> None:
    s = (char or {}).get("sheet") or {}
    conds = s.get("condicoes")
    if not isinstance(conds, list) or not conds:
        return
    ficam = [c for c in conds if _condicao_vale(c, char)]
    if len(ficam) != len(conds):
        s["condicoes"] = ficam


def _get_conditions(char: dict) -> list[dict]:
    """Retorna a lista de condições ativas do personagem."""
    _limpar_condicoes(char)
    return (char.get("sheet") or {}).get("condicoes") or []


def _condicao_com(char: dict, chave: str) -> str:
    """O nome da primeira condição ativa com o efeito `chave`, ou ''."""
    for c in _get_conditions(char):
        nome = (c.get("nome", "") if isinstance(c, dict) else str(c)).lower()
        if CONDITION_EFFECTS.get(nome, {}).get(chave):
            return c.get("nome", "") if isinstance(c, dict) else str(c)
    return ""


def _invisivel(char: dict) -> bool:
    return any(_norm_txt(c.get("nome", "") if isinstance(c, dict) else str(c)) == "invisivel"
               for c in _get_conditions(char))


def _ve_invisivel(char: dict) -> bool:
    """Ver o Invisível (e Visão da Verdade): enxerga o invisível."""
    return any(e.get("ver_invisivel") for e in _efeitos_de(char))


def _impedido_de_agir(char: dict) -> str:
    """Paralisado, Atordoado, Incapacitado, Banido…: não age. '' quando age."""
    return _condicao_com(char, "no_actions")


# Magias cujo alvo repete a salvaguarda no FIM de cada turno dele e se livra
# ao passar (SRD). Sem isto, Imobilizar Pessoa prendia até a luta acabar.
_REPETE_SALVAGUARDA = {"Hold Person", "Hold Monster", "Tasha's Hideous Laughter",
                       "Hideous Laughter", "Confusion", "Blindness/Deafness", "Slow",
                       "Fear", "Phantasmal Killer", "Flesh to Stone", "Eyebite"}
# Duram um turno só.
_UM_TURNO = {"Command"}


def _condicao_de_magia(conjurador: dict, hab: dict, cond: str, s_conj: dict) -> dict:
    """A condição que a magia deixa, com o que a faz acabar."""
    from rpg import resolucao
    m = resolucao._magia_srd(hab) or {}
    c = {"nome": cond.capitalize(), "duracao": None, "por": conjurador.get("name", ""),
         "magia": hab.get("nome", "")}
    if m.get("nome_srd") in _UM_TURNO:
        c["duracao"] = 1
    if m.get("concentracao") or _requires_concentration(hab):
        c["concentracao_de"] = memory.char_key(conjurador.get("name", ""))
    if m.get("nome_srd") in _REPETE_SALVAGUARDA and m.get("salvaguarda"):
        conj = _conjuracao(s_conj) or {}
        c["salvaguarda_fim"] = {"atributo": m["salvaguarda"],
                                "cd": int(conj.get("cd") or (8 + int(s_conj.get("proficiencia", 2) or 2)))}
    return c


def _como_a_condicao_acaba(c: dict) -> str:
    partes = []
    if c.get("concentracao_de"):
        partes.append("acaba se a concentração cair")
    if c.get("salvaguarda_fim"):
        sv = c["salvaguarda_fim"]
        partes.append(f"o alvo repete a salvaguarda de "
                      f"{_ATRIBUTO_SIGLA.get(sv['atributo'], sv['atributo'][:3].upper())} "
                      f"(CD {sv['cd']}) no fim de cada turno dele")
    if c.get("duracao") == 1:
        partes.append("dura um turno")
    return ("Como acaba: " + "; ".join(partes) + ".") if partes else ""


def _has_condition_effect(char: dict, effect_key: str) -> bool:
    """Verifica se alguma condição ativa possui o efeito mecânico indicado."""
    for cond in _get_conditions(char):
        name = (cond.get("nome", "") if isinstance(cond, dict) else str(cond)).lower()
        effects = CONDITION_EFFECTS.get(name, {})
        if effects.get(effect_key):
            return True
    return False


def _roll_d20_with_adv(advantage: bool, disadvantage: bool) -> tuple[int, str]:
    """
    Rola 1d20 ou 2d20 conforme vantagem/desvantagem.
    Retorna (resultado_final, texto_log).
    Se ambos estiverem ativos, cancelam-se (rola 1d20 normal).
    """
    if advantage and disadvantage:
        # Cancelam-se
        roll = random.randint(1, 20)
        return roll, f"d20={roll} (vantagem e desvantagem se cancelam)"

    if advantage:
        r1, r2 = random.randint(1, 20), random.randint(1, 20)
        best   = max(r1, r2)
        return best, f"d20 com VANTAGEM: [{r1}, {r2}] → usa **{best}**"

    if disadvantage:
        r1, r2 = random.randint(1, 20), random.randint(1, 20)
        worst  = min(r1, r2)
        return worst, f"d20 com DESVANTAGEM: [{r1}, {r2}] → usa **{worst}**"

    roll = random.randint(1, 20)
    return roll, f"d20={roll}"


# Habilidades que trocam a conta da CA sem armadura: conceder ou tirar uma
# delas muda a CA na hora, sem esperar o personagem vestir alguma coisa.
_HABILIDADES_DE_CA = ("Defesa Sem Armadura", "Resistência Dracônica")


def _defesa_sem_armadura(char: dict, dex: int) -> int | None:
    """
    CA da Defesa Sem Armadura, que só vale sem armadura equipada.

    Bárbaro: 10 + mod. DES + mod. CON, e pode usar escudo.
    Monge:   10 + mod. DES + mod. SAB, e a habilidade para de valer com escudo.
    Outra classe com a habilidade (homebrew do mestre) segue o bárbaro.

    Devolve None quando a habilidade não se aplica.
    """
    if not _char_has_feature(char, "Defesa Sem Armadura"):
        return None
    s = char["sheet"]
    if _norm_txt(s.get("classe", "")) == "monge":
        if (s.get("equipamentos") or {}).get("escudo"):
            return None
        return 10 + dex + _modifier(s.get("sabedoria", 10))
    return 10 + dex + _modifier(s.get("constituicao", 10))


# ── Conjuração ─────────────────────────────────────────────────────────────
# CD de magia = 8 + proficiência + mod. do atributo de conjuração da classe;
# ataque mágico = proficiência + o mesmo mod. O motor não tinha nenhuma das
# duas: o mestre chutava a CD de cabeça e o jogador não sabia a sua.

def _atributo_de_conjuracao(sheet: dict) -> str:
    """Atributo de conjuração da classe, ou "" para quem não conjura."""
    if sheet.get("atributo_conjuracao"):
        return sheet["atributo_conjuracao"]
    classe = _norm_txt(sheet.get("classe", ""))
    for nome, dados in CLASS_DATA.items():
        if _norm_txt(nome) == classe:
            if not dados.get("mana_per_level"):
                return ""
            return dados.get("mana_stat") or ""
    return ""


def _conjuracao(sheet: dict) -> dict | None:
    """
    {atributo, sigla, cd, ataque} ou None quando a classe não conjura.

    Enquanto a magia sai de um item (_conjurando_pelo_item), a CD e o ataque
    são os do item quando ele tem (Varinha de Bolas de Fogo: CD 15;
    pergaminho de 3º círculo: CD 15, +7), e quem não conjura usa o melhor
    atributo mental.
    """
    atributo = _atributo_de_conjuracao(sheet)
    item = _item_conjurando(sheet)
    if not atributo and not item:
        return None
    if not atributo:
        atributo = max(("inteligencia", "sabedoria", "carisma"),
                       key=lambda a: int(sheet.get(a, 10) or 10))
    prof = int(sheet.get("proficiencia", _proficiency_bonus(int(sheet.get("nivel", 1) or 1))) or 2)
    mod  = _modifier(int(sheet.get(atributo, 10) or 10))
    cd, ataque = 8 + prof + mod, prof + mod
    if item:
        cd = int(item.get("cd") or cd)
        ataque = ataque if item.get("ataque") is None else int(item["ataque"])
    return {"atributo": _ATRIBUTO_PT[atributo], "sigla": _ATRIBUTO_SIGLA[atributo],
            "cd": cd, "ataque": _fmt_bonus(ataque)}


# ── Magia que sai de um item (pergaminho, varinha, cajado) ────────────────
# Quem conjura é o personagem, pelo mesmo use_ability das magias da ficha; o
# item muda o que a magia custa (cargas, o pergaminho que se desfaz) e, às
# vezes, a CD e o ataque. A troca vale só para a ficha de quem usa o item.
_CONJURACAO_DE_ITEM: dict | None = None


def _item_conjurando(sheet: dict) -> dict | None:
    c = _CONJURACAO_DE_ITEM
    return c if c is not None and c.get("sheet") is sheet else None


class _conjurando_pelo_item:
    def __init__(self, sheet: dict, cd: int | None, ataque: int | None):
        self.novo = {"sheet": sheet, "cd": cd, "ataque": ataque}

    def __enter__(self):
        global _CONJURACAO_DE_ITEM
        self.antes, _CONJURACAO_DE_ITEM = _CONJURACAO_DE_ITEM, self.novo
        return self

    def __exit__(self, *exc):
        global _CONJURACAO_DE_ITEM
        _CONJURACAO_DE_ITEM = self.antes
        return False


# ── Deslocamento ───────────────────────────────────────────────────────────
# Em metros, como o resto da mesa. O SRD dá 30 pés (9 m) para quase todo
# mundo; anões, halflings e gnomos andam 25 pés (7,5 m).
_DESLOCAMENTO_BASE_M = 9.0
_DESLOCAMENTO_POR_RACA = {"anao": 7.5, "halfling": 7.5, "gnomo": 7.5}

# Monge, Movimento Sem Armadura: +3 m no 2º nível, subindo até +9 m no 18º.
_MOVIMENTO_DO_MONGE = ((18, 9.0), (14, 7.5), (10, 6.0), (6, 4.5), (2, 3.0))


def _deslocamento(char: dict) -> dict:
    """
    {metros, base, notas} — o quanto o personagem anda num turno e por quê.

    Soma o que a classe dá sem armadura (monge) ou sem armadura pesada
    (bárbaro), e desconta o que o motor já modela: exaustão de nível 2 corta
    pela metade, de nível 5 zera, e carga acima do limite prende no lugar.
    """
    sheet = char.get("sheet") or {}
    base  = _DESLOCAMENTO_POR_RACA.get(_norm_txt(sheet.get("raca", "")), _DESLOCAMENTO_BASE_M)
    metros = base
    notas: list[str] = []

    equip = sheet.get("equipamentos") or {}
    armadura = _armadura_na_tabela((equip.get("armadura") or "").lower())
    pesada = bool(armadura and armadura["dex_bonus"] == "none")
    nivel  = int(sheet.get("nivel", 1) or 1)

    if _char_has_feature(char, "Movimento Sem Armadura") and not equip.get("armadura") \
            and not equip.get("escudo"):
        ganho = next((m for lv, m in _MOVIMENTO_DO_MONGE if nivel >= lv), 0.0)
        if ganho:
            metros += ganho
            notas.append(f"+{_metros(ganho)} de Movimento Sem Armadura")
    if _char_has_feature(char, "Movimento Rápido") and not pesada:
        metros += 3.0
        notas.append("+3 m de Movimento Rápido")

    exaustao = _exaustao(sheet)
    if exaustao >= 5:
        metros = 0.0
        notas.append("exaustão 5: não anda")
    elif exaustao >= 2:
        metros /= 2
        notas.append("exaustão 2: metade")

    estado, _carga, _cap = _estado_de_carga(char)
    if estado == "imovel":
        metros = 0.0
        notas.append("carga acima do limite: não anda")
    elif estado == "sobrecarregado":
        metros = max(0.0, metros - 3.0)
        notas.append("-3 m de sobrecarga")

    # Armadura pesada sem a Força que ela pede: -3 m (anão não sente).
    if armadura and armadura.get("forca_min") and int(sheet.get("forca", 10) or 10) < armadura["forca_min"] \
            and "anao" not in _norm_txt(sheet.get("raca", "")) and exaustao < 5:
        metros = max(0.0, metros - 3.0)
        notas.append(f"-3 m: {equip.get('armadura')} pede FOR {armadura['forca_min']}")

    # Botas de Passos Largos e Saltos: pelo menos 9 m, com carga ou sem.
    minimo = max([float(e.get("deslocamento_min", 0) or 0) for e in _efeitos_dos_itens(sheet)] or [0])
    if minimo and metros < minimo and exaustao < 5 and estado != "imovel":
        metros = minimo
        notas.append(f"no mínimo {_metros(minimo)} pelas botas")

    return {"metros": round(metros, 1), "base": base, "notas": notas}


def _metros(v: float) -> str:
    """9.0 → "9 m"; 7.5 → "7,5 m" (vírgula, como o resto da mesa)."""
    texto = f"{v:.1f}".rstrip("0").rstrip(".")
    return texto.replace(".", ",") + " m"


def _recalculate_ca(char: dict) -> None:
    """
    Recalcula a CA do personagem com base nos equipamentos ativos.
    Hierarquia: armadura equipada > CA base (10 + DES).
    Escudo sempre soma +2. Armadura e escudo mágicos somam o próprio +N.
    """
    s    = char["sheet"]
    # Os atributos dos itens primeiro (Manoplas de Força de Ogro: FOR 19).
    _aplicar_atributos_dos_itens(char)
    dex  = _modifier(s["destreza"])
    equip = s.get("equipamentos", {})

    armor_name  = (equip.get("armadura") or "").lower()
    shield_name = (equip.get("escudo")   or "").lower()

    armor_data  = _armadura_na_tabela(armor_name)
    if armor_data and armor_data["slot"] != "armadura":
        armor_data = None
    shield_data = _armadura_na_tabela(shield_name)

    if armor_data:
        dex_rule = armor_data["dex_bonus"]
        ca_base  = armor_data["ca_base"]
        if dex_rule == "full":
            new_ca = ca_base + dex
        elif dex_rule == "cap2":
            new_ca = ca_base + min(2, dex)
        else:  # "none"
            new_ca = ca_base
        # Armadura mágica: o +1 da "Cota de Malha +1", o +2 das Placas Anãs
        # (a Armadura Demoníaca só depois de sintonizada).
        if not armor_data["sintonizacao"] or _esta_sintonizado(s, armor_name):
            new_ca += armor_data["bonus"]
    else:
        # Sem armadura: CA padrão 10 + DES. Duas habilidades põem outra conta
        # no lugar dela, e nenhuma se soma à outra: fica a maior.
        # Defesa Sem Armadura (bárbaro, monge) e Resistência Dracônica
        # (Feiticeiro de Linhagem Dracônica): 13 + DES.
        contas = [10 + dex]
        sem_armadura = _defesa_sem_armadura(char, dex)
        if sem_armadura is not None:
            contas.append(sem_armadura)
        if _char_has_feature(char, "Resistência Dracônica"):
            contas.append(13 + dex)
        new_ca = max(contas)

    if shield_data and shield_data["dex_bonus"] == "shield":
        new_ca += shield_data["ca_base"]
        if not shield_data["sintonizacao"] or _esta_sintonizado(s, shield_name):
            new_ca += shield_data["bonus"]

    # Anel e Manto de Proteção (+1), Braçadeiras de Defesa (+2 sem armadura
    # e sem escudo): o que os itens vestidos e sintonizados dão.
    for _nome_i, _mag_i in _itens_ativos(s):
        _ef_i = _mag_i.get("efeito") or {}
        new_ca += int(_ef_i.get("ca", 0) or 0)
        if _ef_i.get("ca_sem_armadura") and not armor_data and not shield_data:
            new_ca += int(_ef_i["ca_sem_armadura"])

    # ── Estilo de Combate: Defesa → +1 CA enquanto usando QUALQUER armadura.
    if armor_data and _has_combat_style(char, "Defesa"):
        new_ca += 1

    s["ca"] = new_ca


# ---------------------------------------------------------------------------
# 1. Dado
# ---------------------------------------------------------------------------

def roll_dice(sides: int, count: int = 1, modifier: int = 0) -> str:
    """
    Rola dados e retorna o resultado detalhado.
    Use para qualquer teste, ataque ou dano quando não houver ferramenta mais específica.

    Args:
        sides:    Faces do dado (2, 4, 6, 8, 10, 12, 20 ou 100).
        count:    Quantidade de dados (padrão: 1).
        modifier: Modificador fixo somado ao total (pode ser negativo).
    """
    if sides < 2:
        return "Erro: sides deve ser >= 2."
    if count < 1:
        return "Erro: count deve ser >= 1."

    rolls   = [random.randint(1, sides) for _ in range(count)]
    total   = sum(rolls) + modifier
    mod_str = (f" {'+' if modifier >= 0 else ''}{modifier}") if modifier != 0 else ""
    detail  = " + ".join(str(r) for r in rolls) if count > 1 else str(rolls[0])

    return f"{count}d{sides}{mod_str}: [{detail}]{mod_str} = **{total}**"


# ---------------------------------------------------------------------------
# 2. Criação de personagem
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Bônus de raça e dados de arma — Open5e helpers
# ---------------------------------------------------------------------------

# Bônus canônicos do SRD para fallback offline
_RACE_BONUS_FALLBACK: dict[str, dict[str, int]] = {
    "human":      {"forca":1,"destreza":1,"constituicao":1,"inteligencia":1,"sabedoria":1,"carisma":1},
    "elf":        {"destreza":2},
    "dwarf":      {"constituicao":2},
    "halfling":   {"destreza":2},
    "dragonborn": {"forca":2,"carisma":1},
    "gnome":      {"inteligencia":2},
    "half-elf":   {"carisma":2},
    "half-orc":   {"forca":2,"constituicao":1},
    "tiefling":   {"inteligencia":1,"carisma":2},
}

# Atributo D&D 5e → chave do sistema
_ATTR_MAP = {
    "strength":     "forca",
    "dexterity":    "destreza",
    "constitution": "constituicao",
    "intelligence": "inteligencia",
    "wisdom":       "sabedoria",
    "charisma":     "carisma",
}


def _fetch_race_data(race_name: str) -> dict | None:
    """Busca dados da raça no Open5e. Retorna dict com ability_bonuses e traits, ou None."""
    from rpg.open5e import http as _req   # SRD com cache, sessão e retry
    en_name = RACE_PT_TO_EN.get(race_name.lower(), race_name.lower())
    slug    = en_name.replace(" ", "-").replace("'", "")
    try:
        r = _req.get(f"https://api.open5e.com/v1/races/{slug}/", timeout=5)
        if r.ok and r.json().get("name"):
            return r.json()
    except Exception:
        pass
    try:
        r = _req.get("https://api.open5e.com/v1/races/",
                     params={"search": en_name, "limit": 3}, timeout=5)
        if r.ok:
            results = r.json().get("results", [])
            for res in results:
                if en_name.lower() in res.get("name","").lower():
                    return res
            if results:
                return results[0]
    except Exception:
        pass
    return None


def _apply_race_bonuses(char: dict, sheet: dict, race_name: str) -> dict[str, int]:
    """
    Aplica bônus de atributo e traços raciais ao personagem.
    Tenta Open5e primeiro; usa tabela offline como fallback.
    Retorna dict {stat: bonus} com os bônus aplicados.
    """
    en_key  = RACE_PT_TO_EN.get(race_name.lower(), race_name.lower())
    bonuses: dict[str, int] = {}
    traits:  list[str]      = []

    race_data = _fetch_race_data(race_name)

    if race_data:
        # Bônus de atributo da API
        for bonus_entry in race_data.get("ability_bonuses", []):
            if not isinstance(bonus_entry, dict):
                continue
            attr_name = bonus_entry.get("ability_score", {}).get("name", "").lower()                         if isinstance(bonus_entry.get("ability_score"), dict)                         else bonus_entry.get("attribute", "")
            bonus_val = bonus_entry.get("bonus", 0)
            stat = _ATTR_MAP.get(attr_name.lower(), "")
            if stat and bonus_val:
                bonuses[stat] = bonuses.get(stat, 0) + bonus_val

        # Traços raciais — a API v1 retorna "traits" como STRING (texto markdown),
        # mas outras coleções podem trazer lista de dicts ou de strings.
        raw_traits = race_data.get("traits", [])
        if isinstance(raw_traits, list):
            for trait in raw_traits:
                if isinstance(trait, dict):
                    t_name = trait.get("name", "")
                    t_desc = " ".join((trait.get("desc") or "").split())[:200]
                    if t_name:
                        traits.append({"nome": t_name, "descricao": t_desc,
                                        "custo_mana": 0, "dado": ""})
                elif isinstance(trait, str) and trait.strip():
                    traits.append({"nome": trait.strip()[:60], "descricao": "",
                                    "custo_mana": 0, "dado": ""})

        # Se a API não trouxe bônus de atributo, usa a tabela offline canônica
        # (sem isso, raças como anão perdem o +CON racial e o HP fica errado).
        if not bonuses:
            bonuses = dict(_RACE_BONUS_FALLBACK.get(en_key, {}))
    else:
        # Fallback offline
        bonuses = dict(_RACE_BONUS_FALLBACK.get(en_key, {}))

    # Captura o modificador de CON ANTES dos bônus raciais para ajustar o HP
    # pelo delta sem destruir o HP acumulado nível-a-nível.
    con_before = _modifier(sheet.get("constituicao", 10))

    # Aplica bônus aos atributos da ficha
    for stat, bonus in bonuses.items():
        if stat in sheet:
            sheet[stat] += bonus

    # Ajusta stats derivados pelo DELTA do bônus racial.
    # CRÍTICO: NÃO recalcular vida_max pela fórmula de nível 1 — isso apagaria
    # todo o HP acumulado de personagens/NPCs de nível alto. Em D&D, cada nível
    # soma o modificador de CON ao HP, então um +1 de CON racial = +nivel de HP.
    con_after = _modifier(sheet.get("constituicao", 10))
    con_delta = con_after - con_before
    if con_delta:
        nivel     = sheet.get("nivel", 1)
        hp_adjust = con_delta * nivel
        sheet["vida_max"]   = max(1, sheet.get("vida_max", 1) + hp_adjust)
        sheet["vida_atual"] = sheet["vida_max"]
    # CA base (ainda sem equipamento na criação) — usa DES já com bônus racial
    sheet["ca"] = 10 + _modifier(sheet["destreza"])

    # Adiciona traços raciais como habilidades (sem duplicar)
    existing_names = {h.get("nome","").lower() for h in char.get("habilidades", [])}
    for trait in traits:
        if trait["nome"].lower() not in existing_names:
            char.setdefault("habilidades", []).append(trait)

    return bonuses


def _fetch_weapon_data(weapon_name: str) -> tuple[int, int] | None:
    """
    O dado de dano de uma arma do SRD: (n_dados, faces), ou None quando o nome
    não é de arma do SRD (ou a arma não causa dano, como a Rede).
    Ex: "Espada Longa" → (1, 8); "Espada Longa +1" → (1, 8); "Defensora" → (1, 8).

    Vem do compêndio local (rpg/itens.py), sem rede.
    """
    a = _itens.arma(weapon_name)
    if not a or "d" not in (a.get("dado") or ""):
        return (1, 1) if a and a.get("dado") == "1" else None
    n, s, _ = _parse_dice(a["dado"])
    return n, s


def _versatil_a_duas_maos(char: dict, weapon: str, mao_inabil: bool = False) -> tuple[int, int] | None:
    """
    O dado da arma VERSÁTIL empunhada com as duas mãos (espada longa 1d10,
    lança 1d8), ou None. Vale quando a outra mão está livre: sem escudo, sem
    outra arma equipada. Com o Estilo Duelo o motor mantém uma mão só, porque
    o +2 do Duelo rende mais que o dado maior.
    """
    if mao_inabil:
        return None
    a = _itens.arma(weapon)
    if not a or "versatil" not in a["propriedades"] or a["distancia"] or not a.get("versatil"):
        return None
    eq = ((char or {}).get("sheet") or {}).get("equipamentos") or {}
    if eq.get("escudo"):
        return None
    if any(v and _norm_txt(v) != _norm_txt(weapon)
           for s, v in eq.items() if s in ("arma_principal", "arma_secundaria")):
        return None
    if _get_feature_choice(char, "Estilo de Combate") == "Duelo":
        return None
    n, s, _ = _parse_dice(a["versatil"])
    return n, s


# ── Magias iniciais padrão por classe (fallback offline) ─────────────────────
# Cantrips (nível 0) + magias de nível 1 mais representativas do SRD.
# Usado quando Open5e não responde E o wizard não mandou lista customizada.
DEFAULT_SPELLS_BY_CLASS: dict[str, list[dict]] = {
    "mago": [
        {"nome": "Míssil Mágico",  "descricao": "[Evocação] 3 dardos de força, 1d4+1 dano cada. Automático.", "custo_mana": 4,  "dado": "1d4"},
        {"nome": "Mãos Ardentes",  "descricao": "[Evocação] Cone de 4,5m, 3d6 dano de fogo. DEX salva metade.", "custo_mana": 4,  "dado": "3d6"},
        {"nome": "Sono",           "descricao": "[Encantamento] Afeta 5d8 PV de criaturas, começando pelas mais fracas.", "custo_mana": 4, "dado": "5d8"},
        {"nome": "Prestidigitação","descricao": "[Truque] Efeitos mágicos menores: acender velas, limpar objetos, criar sons.", "custo_mana": 0,  "dado": ""},
        {"nome": "Luz",            "descricao": "[Truque de evocação] Objeto toca emite luz como tocha por 1 hora.", "custo_mana": 0,  "dado": ""},
        {"nome": "Raio de Gelo",   "descricao": "[Truque] Ataque mágico à distância: 1d8 dano de frio + velocidade -3m.", "custo_mana": 0,  "dado": "1d8"},
    ],
    "feiticeiro": [
        {"nome": "Míssil Mágico",  "descricao": "[Evocação] 3 dardos de força, 1d4+1 dano cada. Automático.", "custo_mana": 4,  "dado": "1d4"},
        {"nome": "Mãos Ardentes",  "descricao": "[Evocação] Cone de 4,5m, 3d6 dano de fogo. DEX salva metade.", "custo_mana": 4,  "dado": "3d6"},
        {"nome": "Bola de Fogo",   "descricao": "[Evocação] Esfera de 6m de raio, 8d6 dano de fogo. DEX salva metade.", "custo_mana": 12, "dado": "8d6"},
        {"nome": "Chamas Sagradas","descricao": "[Truque] Ataque de magia: 1d8 dano radiante (DEX não conta para CA).", "custo_mana": 0,  "dado": "1d8"},
        {"nome": "Luz",            "descricao": "[Truque] Objeto emite luz como tocha por 1 hora.", "custo_mana": 0,  "dado": ""},
        {"nome": "Raio de Gelo",   "descricao": "[Truque] Ataque mágico à distância: 1d8 dano de frio.", "custo_mana": 0,  "dado": "1d8"},
    ],
    "bruxo": [
        {"nome": "Golpe Místico",  "descricao": "[Truque] Ataque mágico à distância: 1d10 dano de força.", "custo_mana": 0,  "dado": "1d10"},
        {"nome": "Hex",            "descricao": "[Encantamento] Amaldiçoa alvo: +1d6 dano necrótico nos ataques. Concentração.", "custo_mana": 4,  "dado": "1d6"},
        {"nome": "Armadura do Agathys","descricao": "[Abjuração] Ganha 5 PV temporários; atacante leva 5 dano de frio.", "custo_mana": 4, "dado": ""},
        {"nome": "Ilusão Menor",   "descricao": "[Truque] Cria som ou imagem ilusória por 1 minuto.", "custo_mana": 0,  "dado": ""},
    ],
    "clérigo": [
        {"nome": "Cura Ferimentos","descricao": "[Evocação] Cura 1d8 + modificador de SAB de PV.", "custo_mana": 4,  "dado": "1d8"},
        {"nome": "Bênção",         "descricao": "[Encantamento] Até 3 criaturas ganham +1d4 em ataques e salvaguardas. Concentração.", "custo_mana": 4, "dado": "1d4"},
        {"nome": "Guia Divino",    "descricao": "[Evocação] Ataque mágico à distância: 4d6 dano radiante. Vantagem contra alvos.", "custo_mana": 4, "dado": "4d6"},
        {"nome": "Chamas Sagradas","descricao": "[Truque] Ataque de magia: 1d8 dano radiante (DEX não conta para CA).", "custo_mana": 0,  "dado": "1d8"},
        {"nome": "Orientação",     "descricao": "[Truque] Toque: criatira ganha +1d4 em um teste de atributo.", "custo_mana": 0,  "dado": "1d4"},
    ],
    "druida": [
        {"nome": "Emaranhar",      "descricao": "[Conjuração] Área de 6m quadrada emaranha criaturas. Concentração 1 min.", "custo_mana": 4,  "dado": ""},
        {"nome": "Cura Ferimentos","descricao": "[Evocação] Cura 1d8 + modificador de SAB de PV.", "custo_mana": 4,  "dado": "1d8"},
        {"nome": "Névoa",          "descricao": "[Conjuração] Nuvem de névoa 6m de raio, bloqueia visão. Concentração.", "custo_mana": 4,  "dado": ""},
        {"nome": "Produzir Chama", "descricao": "[Truque] Chama na mão: ilumina 3m ou ataca à distância por 1d8 dano de fogo.", "custo_mana": 0,  "dado": "1d8"},
        {"nome": "Orientação",     "descricao": "[Truque] Toque: criatura ganha +1d4 em um teste de atributo.", "custo_mana": 0,  "dado": "1d4"},
    ],
    "bardo": [
        {"nome": "Palavra Curativa","descricao": "[Evocação] Ação bônus: cura 1d4 + modificador de CAR de PV.", "custo_mana": 4,  "dado": "1d4"},
        {"nome": "Encantamento",   "descricao": "[Encantamento] Enfeitiça uma criatura humanóide por 1 hora. Concentração.", "custo_mana": 4, "dado": ""},
        {"nome": "Sono",           "descricao": "[Encantamento] Afeta 5d8 PV de criaturas, começando pelas mais fracas.", "custo_mana": 4,  "dado": "5d8"},
        {"nome": "Insulto Cruel",  "descricao": "[Truque] Ataque psíquico verbal: 1d4 dano psíquico + desvantagem no próximo ataque.", "custo_mana": 0, "dado": "1d4"},
        {"nome": "Luz",            "descricao": "[Truque] Objeto emite luz como tocha por 1 hora.", "custo_mana": 0,  "dado": ""},
    ],
    "paladino": [
        {"nome": "Punição Divina", "descricao": "[Evocação] Quando acerta: +2d8 dano radiante. Ação bônus. Concentração.", "custo_mana": 4,  "dado": "2d8"},
        {"nome": "Escudo da Fé",   "descricao": "[Abjuração] Alvo ganha +2 de CA. Concentração, 10 min.", "custo_mana": 4,  "dado": ""},
        {"nome": "Cura Ferimentos","descricao": "[Evocação] Cura 1d8 + modificador de CAR de PV.", "custo_mana": 4,  "dado": "1d8"},
    ],
    "patrulheiro": [
        {"nome": "Marca do Caçador","descricao": "[Adivinhação] Designa inimigo: +1d6 dano nos ataques contra ele. Concentração.", "custo_mana": 4, "dado": "1d6"},
        {"nome": "Névoa",          "descricao": "[Conjuração] Nuvem de névoa 6m de raio, bloqueia visão. Concentração.", "custo_mana": 4,  "dado": ""},
        {"nome": "Cura Ferimentos","descricao": "[Evocação] Cura 1d8 + modificador de SAB de PV.", "custo_mana": 4,  "dado": "1d8"},
    ],
}

# Classes que têm magias (para exibir o painel no wizard e aplicar defaults)
CASTER_CLASSES = {
    "mago", "feiticeiro", "bruxo", "clérigo", "druida",
    "bardo", "paladino", "patrulheiro",
}

def _sim_do_srd(valor) -> bool:
    """
    Os campos sim/não do Open5e v1 vêm como TEXTO: "yes" ou "no". bool("no")
    é True, e por isso toda magia saía marcada como ritual e concentração —
    no modal de edição, no texto do learn_spell e na ficha.
    """
    if isinstance(valor, str):
        return valor.strip().lower() in ("yes", "true", "sim", "1")
    return bool(valor)


# Mapa classe PT → slug Open5e para /v1/spelllist/
_CLASS_SLUG_MAP = {
    "mago":        "wizard",
    "feiticeiro":  "sorcerer",
    "bruxo":       "warlock",
    "clérigo":     "cleric",
    "druida":      "druid",
    "bardo":       "bard",
    "paladino":    "paladin",
    "patrulheiro": "ranger",
}


def _classe_en(classe: str) -> str:
    """
    Classe no nome do Open5e, ignorando caixa e ACENTO. Com `.get(classe)`,
    "clerigo" (sem acento, como vem de ficha antiga e do editor) não achava
    nada, o filtro por classe caía e a lista trazia magias de todas as classes.
    """
    alvo = _norm_txt(classe or "")
    return next((en for pt, en in _CLASS_SLUG_MAP.items() if _norm_txt(pt) == alvo), "")


def _fetch_class_spells(classe: str, max_spell_level: int = 1) -> list[dict]:
    """
    Busca as magias de nível 0 e 1 da classe no Open5e (/v1/spells/).
    Retorna lista de dicts {nome, descricao, custo_mana, dado}.
    Usa DEFAULT_SPELLS_BY_CLASS como fallback.
    """
    from rpg.open5e import http as _req   # SRD com cache, sessão e retry

    en_class = _classe_en(classe)
    if not en_class:
        return DEFAULT_SPELLS_BY_CLASS.get(classe.lower(), [])

    try:
        r = _req.get(
            "https://api.open5e.com/v1/spells/",
            params={
                "dnd_class": en_class.capitalize(),
                "spell_level__lte": max_spell_level,
                "limit": 30,
            },
            timeout=6,
        )
        if not r.ok:
            raise ValueError("API error")

        results = r.json().get("results", [])
        if not results:
            raise ValueError("Empty results")

        spells = []
        for s in results:
            lvl      = int(s.get("spell_level", 0) or 0)
            escola   = s.get("school", "")
            ritual   = " (ritual)" if _sim_do_srd(s.get("ritual")) else ""
            concentr = " (concentração)" if _sim_do_srd(s.get("concentration")) else ""
            desc_raw = s.get("desc", "")
            desc     = " ".join(desc_raw.split())[:200]

            dado = ""
            dmg  = s.get("damage", {})
            if isinstance(dmg, dict):
                dado = dmg.get("damage_dice", "") or ""

            mana = SPELL_MANA_COST.get(lvl, 4)

            spells.append({
                "nome":       s.get("name", ""),
                "descricao":  f"[{escola}{ritual}{concentr}] {desc}",
                "custo_mana": mana,
                "dado":       dado,
            })
        return spells

    except Exception:
        return DEFAULT_SPELLS_BY_CLASS.get(classe.lower(), [])


def _apply_initial_spells(
    char_obj: dict,
    classe: str,
    chosen_spells: list[str] | None = None,
) -> list[str]:
    """
    Adiciona as magias iniciais ao personagem.
    Se chosen_spells for fornecida (lista de nomes), aplica apenas essas.
    Caso contrário, aplica o conjunto padrão de DEFAULT_SPELLS_BY_CLASS.
    Não duplica magias já existentes.
    Retorna lista de nomes adicionados.
    """
    if classe.lower() not in CASTER_CLASSES:
        return []

    pool    = DEFAULT_SPELLS_BY_CLASS.get(classe.lower(), [])
    existing = {h.get("nome", "").lower() for h in char_obj.get("habilidades", [])}
    added   = []

    if chosen_spells:
        # Filtra do pool as magias escolhidas pelo jogador
        selected = {s.lower() for s in chosen_spells}
        to_add   = [s for s in pool if s["nome"].lower() in selected]
    else:
        to_add = pool  # Aplica tudo do default

    for spell in to_add:
        if spell["nome"].lower() not in existing:
            char_obj["habilidades"].append({**spell})
            added.append(spell["nome"])

    return added


# ---------------------------------------------------------------------------
# Kit inicial
# ---------------------------------------------------------------------------
# create_character_sheet entregava a ficha de mãos vazias: CA 10, nenhuma
# arma, nenhuma poção e 0 de ouro. A instrução pedia ao mestre add_item e
# modify_currency logo depois, e ele esquecia: a clériga recrutada no meio da
# campanha entrou na primeira luta sem armadura e sem maça.
#
# O kit é o padrão de cada classe no wizard (CLASS_EQUIP_CHOICES_WZ em
# static/js/menu.js, a primeira opção de cada escolha), para as duas portas de
# criação entregarem o mesmo herói. Duas diferenças de propósito: a peça
# vestida também vai para a mochila, porque equip_item só veste o que está
# nela; e mago e feiticeiro não levam armadura, que a classe não sabe usar.
# A peça é vestida por equip_item, então a CA sai da mesma tabela do resto
# do jogo.
_POCAO = ("Poção de Cura", 1, "Restaura 2d4+2 de vida. Ação para beber.")
_PACOTE_EXPLORADOR = ("Pacote de Explorador", 1, "Mochila, saco de dormir, corda, archotes, rações e cantil.")
_PACOTE_MASMORRA = ("Pacote de Masmorra", 1, "Mochila, pé de cabra, martelo, pítons, archotes e rações.")

KIT_INICIAL: dict[str, dict] = {
    "bárbaro": {
        "itens": [("Armadura de Peles", 1, "CA 12 + DES (máx. +2)."),
                  ("Machado Grande", 1, "1d12 cortante. Pesado, duas mãos."),
                  ("Javelin", 4, "1d6 perfurante. Arremesso (9/36 m)."),
                  _PACOTE_EXPLORADOR, _POCAO],
        "vestir": [("Armadura de Peles", "armadura"), ("Machado Grande", "arma_principal")],
    },
    "bardo": {
        "itens": [("Armadura de Couro", 1, "CA 11 + DES."),
                  ("Rapieira", 1, "1d8 perfurante. Acuidade."),
                  ("Adaga", 1, "1d4 perfurante. Leve, arremesso."),
                  ("Alaúde", 1, "Foco bárdico."),
                  ("Pacote de Diplomata", 1, "Baú, roupas finas, tinta, pena e pergaminhos."),
                  _POCAO],
        "vestir": [("Armadura de Couro", "armadura"), ("Rapieira", "arma_principal")],
    },
    "bruxo": {
        "itens": [("Armadura de Couro", 1, "CA 11 + DES."),
                  ("Adaga", 2, "1d4 perfurante. Leve, arremesso."),
                  ("Besta Leve", 1, "1d8 perfurante. Alcance 24 m."),
                  ("Virotes", 20, "Munição para besta."),
                  ("Bolsa de Componentes", 1, "Componentes materiais para magias."),
                  ("Pacote de Estudioso", 1, "Livro, tinta, pena e pergaminhos."),
                  _POCAO],
        "vestir": [("Armadura de Couro", "armadura"), ("Adaga", "arma_principal")],
    },
    "clérigo": {
        "itens": [("Cota de Malha", 1, "CA 16. Armadura pesada."),
                  ("Escudo", 1, "+2 CA."),
                  ("Maça", 1, "1d6 concussão."),
                  ("Símbolo Sagrado", 1, "Foco divino para conjuração."),
                  ("Besta Leve", 1, "1d8 perfurante. Alcance 24 m."),
                  ("Virotes", 20, "Munição para besta."),
                  ("Poção de Cura", 2, _POCAO[2])],
        "vestir": [("Cota de Malha", "armadura"), ("Escudo", "escudo"), ("Maça", "arma_principal")],
    },
    "druida": {
        "itens": [("Armadura de Couro", 1, "CA 11 + DES."),
                  ("Escudo de Madeira", 1, "+2 CA."),
                  ("Cimitarra", 1, "1d6 cortante. Acuidade, leve."),
                  ("Bolsa de Componentes", 1, "Ervas, pedras e componentes naturais."),
                  _PACOTE_EXPLORADOR, _POCAO],
        "vestir": [("Armadura de Couro", "armadura"), ("Escudo de Madeira", "escudo"),
                   ("Cimitarra", "arma_principal")],
    },
    "feiticeiro": {
        "itens": [("Adaga", 2, "1d4 perfurante. Leve, arremesso."),
                  ("Besta Leve", 1, "1d8 perfurante. Alcance 24 m."),
                  ("Virotes", 20, "Munição para besta."),
                  ("Bolsa de Componentes", 1, "Componentes materiais para magias."),
                  _PACOTE_EXPLORADOR, _POCAO],
        "vestir": [("Adaga", "arma_principal")],
    },
    "guerreiro": {
        "itens": [("Cota de Malha", 1, "CA 16. Armadura pesada."),
                  ("Espada Longa", 1, "1d8 cortante (1d10 com duas mãos). Versátil."),
                  ("Escudo", 1, "+2 CA."),
                  ("Besta Leve", 1, "1d8 perfurante. Alcance 24 m."),
                  ("Virotes", 20, "Munição para besta."),
                  _PACOTE_MASMORRA, _POCAO],
        "vestir": [("Cota de Malha", "armadura"), ("Escudo", "escudo"),
                   ("Espada Longa", "arma_principal")],
    },
    "ladino": {
        "itens": [("Armadura de Couro", 1, "CA 11 + DES."),
                  ("Rapieira", 1, "1d8 perfurante. Acuidade."),
                  ("Adaga", 2, "1d4 perfurante. Leve, arremesso."),
                  ("Arco Curto", 1, "1d6 perfurante. Alcance 24 m."),
                  ("Flechas", 20, "Munição para arco."),
                  ("Ferramentas de Ladrão", 1, "Para abrir fechaduras e desarmar armadilhas."),
                  ("Pacote de Assaltante", 1, "Mochila, esferas, corda, pé de cabra e lanterna."),
                  _POCAO],
        "vestir": [("Armadura de Couro", "armadura"), ("Rapieira", "arma_principal")],
    },
    "mago": {
        "itens": [("Cajado", 1, "Foco arcano. 1d6 concussão (1d8 com duas mãos)."),
                  ("Adaga", 1, "1d4 perfurante. Leve, arremesso."),
                  ("Grimório", 1, "Livro com as magias aprendidas."),
                  ("Bolsa de Componentes", 1, "Componentes materiais para magias."),
                  ("Pacote de Estudioso", 1, "Livro, tinta, pena e pergaminhos."),
                  _POCAO],
        "vestir": [("Cajado", "arma_principal")],
    },
    "monge": {
        "itens": [("Espada Curta", 1, "1d6 perfurante. Acuidade, leve."),
                  ("Dardos", 10, "1d4 perfurante. Arremesso (6/18 m)."),
                  _PACOTE_MASMORRA, _POCAO],
        "vestir": [("Espada Curta", "arma_principal")],
    },
    "paladino": {
        "itens": [("Cota de Malha", 1, "CA 16. Armadura pesada."),
                  ("Espada Longa", 1, "1d8 cortante (1d10 com duas mãos). Versátil."),
                  ("Escudo", 1, "+2 CA."),
                  ("Javelin", 5, "1d6 perfurante. Arremesso (9/36 m)."),
                  ("Símbolo Sagrado", 1, "Foco divino para conjuração."),
                  ("Pacote Sacerdotal", 1, "Mochila, cobertor, velas, incenso e roupas de vestimenta."),
                  ("Poção de Cura", 2, _POCAO[2])],
        "vestir": [("Cota de Malha", "armadura"), ("Escudo", "escudo"),
                   ("Espada Longa", "arma_principal")],
    },
    "patrulheiro": {
        "itens": [("Armadura de Escamas", 1, "CA 14 + DES (máx. +2)."),
                  ("Espada Curta", 2, "1d6 perfurante. Acuidade, leve."),
                  ("Arco Longo", 1, "1d8 perfurante. Alcance 45 m."),
                  ("Flechas", 20, "Munição para arco."),
                  _PACOTE_MASMORRA, _POCAO],
        "vestir": [("Armadura de Escamas", "armadura"), ("Espada Curta", "arma_principal"),
                   ("Espada Curta", "arma_secundaria")],
    },
}

# Classe fora da tabela (homebrew, artífice): o mínimo para não entrar de
# mãos nuas.
_KIT_GENERICO = {
    "itens": [("Adaga", 1, "1d4 perfurante. Leve, arremesso."), _PACOTE_EXPLORADOR, _POCAO],
    "vestir": [("Adaga", "arma_principal")],
}

# As mesmas moedas do wizard.
_MOEDAS_INICIAIS = {"ouro": 10, "prata": 5, "cobre": 0}


def _kit_da_classe(classe: str) -> dict | None:
    alvo = _norm_txt(classe)
    if alvo in ("", "npc"):
        return None
    for nome, kit in KIT_INICIAL.items():
        if _norm_txt(nome) == alvo:
            return kit
    return _KIT_GENERICO


def _dar_kit_inicial(char: dict) -> str:
    """
    Põe o kit da classe na mochila, veste o que é para vestir e dá as moedas.
    Só age em quem chega de mãos vazias: um NPC que já carregava coisas
    (dadas antes com add_item) fica com o que tem. Devolve a linha do resumo.
    """
    s = char["sheet"]
    kit = _kit_da_classe(s.get("classe", ""))
    if not kit or char.get("inventario"):
        return ""

    char["inventario"] = [{"nome": nome, "qtd": qtd, "descricao": desc}
                          for nome, qtd, desc in kit["itens"]]
    for moeda, valor in _MOEDAS_INICIAIS.items():
        if not int(s.get(moeda, 0) or 0):
            s[moeda] = valor

    vestidos = []
    for nome, slot in kit["vestir"]:
        r = equip_item(char["name"], nome, slot)
        if not r.startswith(("Erro", "Nota")):
            vestidos.append(nome)
    itens = ", ".join(f"{nome}{f' x{qtd}' if qtd > 1 else ''}" for nome, qtd, _ in kit["itens"])
    return (f"\n   Kit inicial: {itens}"
            f"\n   Equipado: {', '.join(dict.fromkeys(vestidos)) or 'nada'}")


def create_character_sheet(
    name: str,
    classe: str,
    raca: str,
    forca: int,
    destreza: int,
    constituicao: int,
    inteligencia: int,
    sabedoria: int,
    carisma: int,
    description: str = "",
    nivel: int = 1,
    **kwargs,
) -> str:
    """
    Cria a ficha D&D completa de um personagem. Use ao iniciar uma campanha D&D
    ou ao criar um NPC importante com regras mecânicas.

    Args:
        name:          Nome do personagem.
        classe:        Classe (bárbaro, guerreiro, mago, clérigo, ladino, paladino, etc.)
        raca:          Raça (humano, elfo, anão, halfling, tiefling, draconato, etc.)
        forca:         Valor de Força (3–20 para personagem inicial).
        destreza:      Valor de Destreza.
        constituicao:  Valor de Constituição.
        inteligencia:  Valor de Inteligência.
        sabedoria:     Valor de Sabedoria.
        carisma:       Valor de Carisma.
        description:   Descrição narrativa (aparência, história, personalidade).
        nivel:         Nível inicial (1–20). Para NPCs de nível alto, passe o valor
                       correto aqui — HP, mana, proficiência e habilidades de classe
                       são calculados automaticamente para todos os níveis até este.
    """
    nivel        = max(1, min(20, int(nivel)))
    classe_lower = classe.lower()
    info         = CLASS_DATA.get(classe_lower, {"hit_die": 8, "mana_per_level": 4, "mana_stat": "inteligencia", "saves": []})

    con_mod  = _modifier(constituicao)
    dex_mod  = _modifier(destreza)
    hit_die  = info["hit_die"]

    # Nível 1: dado máximo + CON (regra do Player's Handbook para personagens de nível 1)
    hp_max = max(1, hit_die + con_mod)
    # Níveis 2+: rola hit die para cada nível adicional
    for _ in range(nivel - 1):
        hp_max += max(1, random.randint(1, hit_die) + con_mod)

    # Pool de mana pela tabela oficial de Pontos de Magia (DMG p.288):
    # depende só do nível de conjurador, nunca do atributo de conjuração.
    mana_max = _max_mana_for(classe_lower, nivel)

    prof = _proficiency_bonus(nivel)
    xp_threshold = XP_THRESHOLDS[nivel] if nivel < 20 else XP_THRESHOLDS[19]
    xp_start     = XP_THRESHOLDS[nivel - 1] if nivel > 1 else 0

    sheet = {
        "classe":       classe,
        "raca":         raca,
        "nivel":        nivel,
        "xp":           xp_start,
        "xp_proximo":   xp_threshold,
        "forca":        forca,
        "destreza":     destreza,
        "constituicao": constituicao,
        "inteligencia": inteligencia,
        "sabedoria":    sabedoria,
        "carisma":      carisma,
        "vida_atual":   hp_max,
        "vida_max":     hp_max,
        "mana_atual":   mana_max,
        "mana_max":     mana_max,
        "ca":           10 + dex_mod,
        "proficiencia": prof,
        "hit_die":      hit_die,
        # ── Novos campos v2 ──────────────────────────────
        "ouro":                  0,
        "prata":                 0,
        "cobre":                 0,
        "equipamentos":          {"armadura": None, "escudo": None, "arma_principal": None, "amuleto": None},
        "condicoes":             [],          # lista de {"nome": str, "duracao": int|None}
        "death_saves_sucessos":  0,
        "death_saves_falhas":    0,
        # ─────────────────────────────────────────────────
    }

    char_key_val = memory.char_key(name)
    existing = memory.campaign["characters"].get(char_key_val, {})

    # PROTEÇÃO: não sobrescrever uma ficha D&D que JÁ existe (ex.: criada pelo
    # wizard de criação). Recriar zeraria CA/atributos/equipamento e duplicaria
    # itens. Se o personagem já tem ficha, recusa e devolve o estado atual.
    # (Personagem sem ficha — ex.: NPC salvo só com save_character — segue
    # normalmente, pois aqui estamos ADICIONANDO a ficha, não sobrescrevendo.)
    if existing.get("sheet"):
        s = existing["sheet"]
        return (
            f"Nota: {name} JÁ possui ficha D&D — não recriei (evita zerar atributos "
            f"e duplicar itens). Estado atual: {s.get('classe')} {s.get('raca')} "
            f"Nv.{s.get('nivel')}, {s.get('vida_atual')}/{s.get('vida_max')} "
            f"CA {s.get('ca')}. Para ajustar use set_stat / learn_spell / "
            f"add_item etc. — NÃO recrie a ficha."
        )

    # Personagem que já existia sem ficha (NPC do save_character): mantém o
    # que a campanha sabe dele (local, atitude, o que o grupo sabe, se já é
    # do grupo). Antes o dict inteiro era trocado e isso tudo sumia.
    char_obj = dict(existing) if isinstance(existing, dict) else {}
    char_obj.update({
        "name":        existing.get("name") or name,
        "description": description or existing.get("description", ""),
        "traits":      existing.get("traits", ""),
        "status":      existing.get("status") if existing.get("status") not in (None, "", "morto", "inimigo") else "vivo",
        "notes":       existing.get("notes", ""),
        "sheet":       sheet,
        "inventario":  existing.get("inventario") or [],
        "habilidades": existing.get("habilidades") or [],
    })
    memory.campaign["characters"][char_key_val] = char_obj

    # Aplica bônus de raça (Open5e) — modifica sheet e adiciona traços raciais
    race_bonuses = _apply_race_bonuses(char_obj, sheet, raca)
    bonus_str = ", ".join(f"{k.upper()[:3]} +{v}" for k, v in race_bonuses.items()) if race_bonuses else "nenhum"

    # (O pool de mana NÃO é recalculado por bônus racial: na variante de
    # Pontos de Magia o pool depende só do nível, não do atributo.)

    # Aplica habilidades de classe para TODOS os níveis até o nível inicial
    all_feats: list[str] = []
    for lv in range(1, nivel + 1):
        all_feats.extend(_apply_class_features(char_obj, sheet, lv))

    # Aplica magias iniciais para classes conjuradoras (usa chosen_spells se fornecida)
    chosen = kwargs.get("initial_spells")  # lista opcional de nomes escolhidos pelo wizard
    spells_added = _apply_initial_spells(char_obj, classe, chosen_spells=chosen)
    spells_str = f"\n   Magias iniciais: {', '.join(spells_added)}" if spells_added else ""
    feats_str  = f"\n   Habilidades de classe: {', '.join(all_feats)}" if all_feats else ""

    if not memory.campaign.get("protagonist"):
        memory.campaign["protagonist"] = name

    kit_str = _dar_kit_inicial(char_obj)
    # A CA da criação era 10 + DES, tirada antes das habilidades de classe:
    # bárbaro e monge nasciam sem a Defesa Sem Armadura na conta.
    _recalculate_ca(char_obj)

    memory.save_campaign()
    return (
        f"Ficha criada para {name}!\n"
        f"   Classe: {classe} | Raça: {raca} | Nível: {nivel} | Prof: +{prof}\n"
        f"   Bônus racial: {bonus_str}{spells_str}{feats_str}\n"
        f"   Vida: {sheet['vida_max']}/{sheet['vida_max']} | Mana: {sheet['mana_max']}/{sheet['mana_max']} | CA: {sheet['ca']}\n"
        f"   FOR {_mod_str(sheet['forca'])}  DES {_mod_str(sheet['destreza'])}  CON {_mod_str(sheet['constituicao'])}\n"
        f"   INT {_mod_str(sheet['inteligencia'])}  SAB {_mod_str(sheet['sabedoria'])}  CAR {_mod_str(sheet['carisma'])}\n"
        f"   Ouro: {sheet.get('ouro', 0)} | Prata: {sheet.get('prata', 0)} | Cobre: {sheet.get('cobre', 0)}"
        f"{kit_str}"
    )


# ---------------------------------------------------------------------------
# 3. Consulta de ficha
# ---------------------------------------------------------------------------

def get_character_sheet(name: str) -> str:
    """
    Retorna a ficha D&D completa de um personagem: atributos, vida, mana,
    habilidades, inventário, moedas, equipamentos e condições ativas.
    Use antes de qualquer teste ou ação mecânica para checar os valores corretos.

    Args:
        name: Nome do personagem.
    """
    char, err = _get_char(name, allow_dead=True)
    if not char:
        return err

    s     = char["sheet"]
    nivel = s["nivel"]
    xp    = s["xp"]
    xp_p  = s.get("xp_proximo", 300)

    habs = char.get("habilidades", [])
    hab_lines = (
        [f"  • {h['nome']} ({h['dado']}, {h['custo_mana']} mana): {h['descricao']}" for h in habs]
        if habs else ["  Nenhuma"]
    )

    inv = char.get("inventario", [])
    inv_lines = (
        [f"  • {i['nome']} x{i['qtd']}" + (f" — {i['descricao']}" if i.get("descricao") else "") for i in inv]
        if inv else ["  Vazio"]
    )

    bar = _hp_bar(s["vida_atual"], s["vida_max"])

    # Equipamentos
    equip = s.get("equipamentos", {})
    equip_parts = []
    for slot, item in equip.items():
        if item:
            equip_parts.append(f"{slot.capitalize()}: {item}")
    equip_str = ", ".join(equip_parts) if equip_parts else "Nenhum"

    # Condições
    conds = s.get("condicoes", [])
    cond_str = (
        ", ".join(
            f"{c['nome']}" + (f" ({c['duracao']} turnos)" if c.get("duracao") else "")
            for c in conds
        )
        if conds else "Nenhuma"
    )

    # Moedas
    moedas = f"Ouro: {s.get('ouro', 0)} | Prata: {s.get('prata', 0)} | Cobre: {s.get('cobre', 0)}"

    # Death saves (só relevante se HP = 0)
    death_str = ""
    if s["vida_atual"] == 0:
        death_str = (
            f"\n  Testes de Morte — Sucessos: {s.get('death_saves_sucessos', 0)}/3"
            f" | Falhas: {s.get('death_saves_falhas', 0)}/3"
        )

    # PV temporários, concentração e defesas por tipo de dano.
    temp     = _temp_hp(s)
    temp_str = f"  +{temp} PV temporários\n" if temp else ""

    conc     = s.get("concentracao") or {}
    conc_str = f"  Concentrado em: {conc.get('magia')}\n" if conc else ""

    def _linha_traits(rotulo: str, campo: str) -> str:
        entradas = _traits_lookup(s, campo)
        tipos = sorted({t for e in entradas for t in e.get("tipos", [])})
        if not tipos:
            return ""
        cond = " (exceto de armas mágicas)" if any(
            e.get("requer_magica") for e in entradas) else ""
        return f"  {rotulo}: {', '.join(tipos)}{cond}\n"

    defesas_str = (
        _linha_traits("Imunidades",        "imunidades")
        + _linha_traits("Resistências",    "resistencias")
        + _linha_traits("Vulnerabilidades", "vulnerabilidades")
    )

    # CD de magia e ataque mágico: o mestre pedia "role CD 14" de cabeça.
    conj = _conjuracao(s)
    conjuracao_str = (f"  CD de magia: {conj['cd']}   Ataque mágico: {conj['ataque']}"
                      f"   ({conj['sigla']})\n" if conj else "")
    desloc = _deslocamento(char)
    desloc_str = f"  Deslocamento: {_metros(desloc['metros'])}"
    if desloc["notas"]:
        desloc_str += f" ({'; '.join(desloc['notas'])})"
    desloc_str += "\n"

    return (
        f"╔══ {char['name']} — {s['classe']} {s['raca']} Nível {nivel} ══╗\n"
        f"  XP: {xp}/{xp_p}\n"
        f"  Vida [{bar}] {s['vida_atual']}/{s['vida_max']}{death_str}\n"
        f"{temp_str}"
        f"  Mana: {s['mana_atual']}/{s['mana_max']}   CA: {s['ca']}   Prof: +{s['proficiencia']}\n"
        f"{conjuracao_str}{desloc_str}"
        f"{conc_str}{defesas_str}"
        f"  ───────────────────────────────────\n"
        f"  FOR {_mod_str(s['forca'])}  DES {_mod_str(s['destreza'])}  CON {_mod_str(s['constituicao'])}\n"
        f"  INT {_mod_str(s['inteligencia'])}  SAB {_mod_str(s['sabedoria'])}  CAR {_mod_str(s['carisma'])}\n"
        f"  ───────────────────────────────────\n"
        f"  Equipamentos: {equip_str}\n"
        f"  Condições: {cond_str}\n"
        f"  {moedas}\n"
        f"  ───────────────────────────────────\n"
        f"  Habilidades:\n" + "\n".join(hab_lines) + "\n"
        f"  Inventário:\n" + "\n".join(inv_lines) + "\n"
        f"╚{'═' * 43}╝"
    )


def get_combat_status() -> str:
    """
    Mostra o status de combate de todos os personagens com ficha D&D (vivos ou inconscientes).
    Inclui condições ativas. Chame SEMPRE no início de um turno de combate para se situar.
    """
    chars_with_sheet = [
        ch for ch in memory.campaign["characters"].values()
        if ch.get("sheet") and ch.get("status") != "morto"
    ]
    if not chars_with_sheet:
        return "Nenhum personagem com ficha D&D em campo."

    lines = ["Status de Combate:"]
    for ch in chars_with_sheet:
        s    = ch["sheet"]
        bar  = _hp_bar(s["vida_atual"], s["vida_max"])
        pct  = s["vida_atual"] / s["vida_max"] if s["vida_max"] > 0 else 0
        warn = " INCONSCIENTE" if s["vida_atual"] == 0 else (" CRÍTICO" if pct <= 0.25 else "")

        conds = s.get("condicoes", [])
        cond_tag = ""
        if conds:
            names    = ", ".join(
                c["nome"].capitalize()
                + (f" ({_turnos_restantes(c)} turno{'s' if _turnos_restantes(c) > 1 else ''})"
                   if _turnos_restantes(c) else "")
                for c in conds)
            cond_tag = f"\n    Condições: {names}"

        lines.append(
            f"  {ch['name']} (Nv.{s['nivel']} {s['classe']}){warn}\n"
            f"    [{bar}] {s['vida_atual']}/{s['vida_max']}"
            f"   {s['mana_atual']}/{s['mana_max']}"
            f"   CA {s['ca']}{cond_tag}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. Vida e Mana
# ---------------------------------------------------------------------------

def modify_hp(char_name: str, amount: int, reason: str = "",
              damage_type: str = "") -> str:
    """
    Modifica os pontos de vida de um personagem.
    Valor NEGATIVO = dano. Valor POSITIVO = cura.
    Atualiza o status automaticamente (vivo / inconsciente).
    Se curar alguém com HP=0, zera os contadores de testes de morte.

    Dano passa pelas resistências/imunidades do alvo e é absorvido primeiro
    pelos PV temporários; cura, não.

    Args:
        char_name:   Nome do personagem.
        amount:      Quantidade (negativo = dano, positivo = cura).
        reason:      Causa (ex: 'golpe de espada', 'poção de cura', 'queda').
        damage_type: Só para dano. Tipo ('fogo', 'veneno', 'frio', 'radiante'…).
                     Informe sempre que souber — é o que faz o esqueleto ignorar
                     veneno e o elemental do fogo se queimar com gelo.
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    s        = char["sheet"]
    notas: list[str] = []

    if amount < 0:
        _res     = _apply_damage(char, -amount, damage_type,
                                 source_name=reason, arma_magica=False)
        hp_antes = _res["hp_antes"]
        notas    = _res["notas"]
    else:
        hp_antes = s["vida_atual"]
        s["vida_atual"] = max(0, min(_hp_max_efetivo(s), s["vida_atual"] + amount))
    delta    = s["vida_atual"] - hp_antes

    acao       = "curou" if delta > 0 else "sofreu"
    reason_str = f" ({reason})" if reason else ""
    pct        = s["vida_atual"] / s["vida_max"] if s["vida_max"] > 0 else 0

    extra = ""
    if s["vida_atual"] == 0:
        warn = _mark_at_zero_hp(char, reason or "")
    elif pct <= 0.25:
        warn = " Estado crítico!"
    elif pct <= 0.5:
        warn = " Ferido."
    else:
        warn = ""
        if hp_antes == 0 and delta > 0:
            # Ressuscitou — zera testes de morte
            s["death_saves_sucessos"] = 0
            s["death_saves_falhas"]   = 0
            char["status"]            = "vivo"
            extra = "\n   Testes de morte resetados. Personagem estabilizado!"

    memory.save_campaign()
    return (
        f"{char['name']} {acao} {abs(delta)} pv{reason_str}."
        + _fmt_notas(notas, indent="") +
        f"\nVida: {hp_antes} → {s['vida_atual']}/{s['vida_max']}{warn}{extra}"
    )


def grant_temp_hp(char_name: str, amount: int, source: str = "") -> str:
    """
    Concede Pontos de Vida Temporários (Ajuda, Falsa Vida, Armadura de Agathys,
    Inspiração Heroica, Fôlego do Guerreiro…).

    Regra 5e: PV temporários NÃO se acumulam — ao receber uma nova quantia, o
    alvo fica com a MAIOR das duas, nunca com a soma. Eles absorvem dano antes
    dos PV reais, não podem ser curados e somem no descanso longo.

    Args:
        char_name: Nome do personagem.
        amount:    Quantidade de PV temporários (positivo).
        source:    Origem (ex: 'Ajuda', 'Armadura de Agathys').
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    novo = max(0, int(amount or 0))
    if novo <= 0:
        return f"Erro: Quantidade inválida de PV temporários: {amount}."

    s      = char["sheet"]
    atual  = _temp_hp(s)
    origem = f" ({source})" if source else ""

    if novo <= atual:
        return (f"{char['name']} já tem {atual} PV temporários — "
                f"os {novo}{origem} não se acumulam e são descartados "
                f"(5e: vale o maior, nunca a soma).")

    s["vida_temp"] = novo
    _log_combat_event("temp_hp", char["name"], "",
                      msg=f"{char['name']} ganhou {novo} PV temporários{origem}")
    substituiu = f" (substitui os {atual} anteriores)" if atual else ""
    memory.save_campaign()
    return (f"{char['name']} ganhou **{novo} PV temporários**{origem}"
            f"{substituiu}.\n"
            f"   Eles absorvem dano antes dos PV reais e somem no descanso longo.")


def modify_mana(char_name: str, amount: int, reason: str = "") -> str:
    """
    Modifica os pontos de mana de um personagem.
    Valor NEGATIVO = gasta. Valor POSITIVO = restaura.

    Args:
        char_name: Nome do personagem.
        amount:    Quantidade (negativo = gasta, positivo = restaura).
        reason:    Motivo (ex: 'Bola de Fogo', 'descanso curto').
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    s = char["sheet"]
    if amount < 0 and s["mana_atual"] < abs(amount):
        return (
            f"Erro: {char['name']} não tem mana suficiente!\n"
            f"Mana atual: {s['mana_atual']}/{s['mana_max']} (necessário: {abs(amount)})"
        )

    mana_antes    = s["mana_atual"]
    s["mana_atual"] = max(0, min(s["mana_max"], s["mana_atual"] + amount))
    acao          = "restaurou" if amount > 0 else "gastou"
    reason_str    = f" ({reason})" if reason else ""

    memory.save_campaign()
    return (
        f"{char['name']} {acao} {abs(amount)} de mana{reason_str}.\n"
        f"Mana: {mana_antes} → {s['mana_atual']}/{s['mana_max']}"
    )


# ---------------------------------------------------------------------------
# 5. Testes e combate
# ---------------------------------------------------------------------------

# Mapa de perícias D&D 5e → atributo correspondente
# Perícias em que cada classe é proficiente (simplificado: a lista de opções
# da classe inteira, sem a escolha de duas ou quatro do PHB). Lida pelo
# social_check, pelo make_skill_check e pela ficha do herói, para o bônus
# mostrado ser o bônus usado.
PERICIAS_DA_CLASSE: dict[str, set[str]] = {
    "guerreiro": {"atletismo", "intimidação", "percepção", "sobrevivência", "história", "acrobacia"},
    "bárbaro":   {"atletismo", "intimidação", "percepção", "sobrevivência", "natureza", "manusear animais"},
    "ladino":    {"acrobacia", "atletismo", "enganação", "furtividade", "intimidação", "investigação",
                  "percepção", "atuação", "persuasão", "prestidigitação"},
    "bardo":     {"acrobacia", "enganação", "história", "intuição", "atuação", "persuasão"},
    "mago":      {"arcana", "história", "intuição", "investigação", "medicina", "religião"},
    "arcanista": {"arcana", "história", "intuição", "investigação", "medicina", "religião"},
    "clérigo":   {"história", "intuição", "medicina", "persuasão", "religião"},
    "druida":    {"arcana", "intuição", "manusear animais", "medicina", "natureza", "percepção", "religião", "sobrevivência"},
    "paladino":  {"atletismo", "intuição", "intimidação", "medicina", "persuasão", "religião"},
    "patrulheiro": {"atletismo", "furtividade", "investigação", "natureza", "percepção", "sobrevivência"},
    "monge":     {"acrobacia", "atletismo", "história", "intuição", "religião", "furtividade"},
    "feiticeiro": {"arcana", "enganação", "intuição", "intimidação", "persuasão", "religião"},
    "bruxo":     {"arcana", "enganação", "história", "intimidação", "investigação", "natureza"},
}


def _proficiente_na_pericia(sheet: dict, pericia: str) -> bool:
    nome = (pericia or "").lower().strip()
    if nome == "lidar com animais":
        nome = "manusear animais"
    classe = (sheet.get("classe") or "").lower().strip()
    return nome in PERICIAS_DA_CLASSE.get(classe, set())


SKILL_ATTR_MAP: dict[str, str] = {
    "atletismo":          "forca",
    "acrobacia":          "destreza",
    "furtividade":        "destreza",
    "prestidigitação":    "destreza",
    "manusear animais":   "sabedoria",
    "arcana":             "inteligencia",
    "história":           "inteligencia",
    "investigação":       "inteligencia",
    "natureza":           "inteligencia",
    "religião":           "inteligencia",
    "percepção":          "sabedoria",
    "intuição":           "sabedoria",
    "medicina":           "sabedoria",
    "sobrevivência":      "sabedoria",
    "enganação":          "carisma",
    "intimidação":        "carisma",
    "atuação":            "carisma",
    "persuasão":          "carisma",
    "lidar com animais":  "sabedoria",
}


def make_skill_check(
    char_name: str,
    attribute: str,
    difficulty: int,
    advantage: bool = False,
    disadvantage: bool = False,
    skill: str = "",
    player_roll: int = 0,
) -> str:
    """
    Realiza um teste de atributo: 1d20 + modificador vs Classe de Dificuldade.
    Suporta Vantagem (rola 2d20, usa o maior) e Desvantagem (rola 2d20, usa o menor).
    Condições ativas (ex: Envenenado) podem forçar desvantagem automaticamente.

    Classes de Dificuldade sugeridas:
    • 5  = Trivial   • 10 = Fácil   • 15 = Médio
    • 20 = Difícil   • 25 = Muito difícil   • 30 = Quase impossível

    Args:
        char_name:    Nome do personagem.
        attribute:    Atributo: forca, destreza, constituicao, inteligencia, sabedoria ou carisma.
        difficulty:   Classe de Dificuldade (CD) a superar.
        advantage:    Se True, rola 2d20 e usa o maior.
        disadvantage: Se True, rola 2d20 e usa o menor.
        skill:        Nome da perícia (ex: 'atletismo', 'furtividade'). Resolve o atributo automaticamente.
        player_roll:  Resultado do d20 JÁ ROLADO pelo jogador (1–20). Quando o
                      teste é de um PERSONAGEM JOGÁVEL e o jogador rolou pela
                      bandeja de dados ("[DADO DO JOGADOR …] rolei X"), passe X
                      aqui — NUNCA role um d20 novo nem invente o valor. Deixe
                      0 para o mestre rolar (testes de NPC). Com player_roll,
                      vantagem/desvantagem são ignoradas (o jogador rolou uma
                      vez só).
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    # Se skill informada, resolve o atributo automaticamente
    if skill:
        resolved = SKILL_ATTR_MAP.get(skill.lower().strip())
        if resolved:
            attribute = resolved

    s        = char["sheet"]
    attr_key = attribute.lower()
    if attr_key not in STAT_NAMES:
        return f"Atributo '{attribute}' inválido. Use: {', '.join(sorted(STAT_NAMES))}."

    # Condições forçam desvantagem nos testes
    if _has_condition_effect(char, "check_disadvantage"):
        disadvantage = True
    # Exaustão nível 1+: desvantagem em testes de perícia e atributo.
    if _exaustao(s) >= 1:
        disadvantage = True
    # Sobrecarga pesa em Força, Destreza e Constituição — não em Inteligência,
    # Sabedoria ou Carisma: a mochila atrapalha o corpo, não o raciocínio.
    if attr_key in ("forca", "destreza", "constituicao")             and _estado_de_carga(char)[0] != "livre":
        disadvantage = True
    _desv_armadura = _desvantagem_da_armadura(char, attr_key, skill)
    if _desv_armadura:
        disadvantage = True

    attr_val = s[attr_key]
    mod      = _modifier(attr_val)
    # Perícia da classe soma a proficiência. Antes só o social_check somava, e
    # o mesmo "percepção" dava totais diferentes conforme a ferramenta.
    prof_pericia = 0
    if skill and _proficiente_na_pericia(s, skill):
        prof_pericia = int(s.get("proficiencia", _proficiency_bonus(int(s.get("nivel", 1) or 1))) or 2)
    # Usa a rolagem do JOGADOR quando fornecida e válida (1–20); senão o
    # mestre/sistema rola (com vantagem/desvantagem se aplicável).
    _bonus_ef, _vant_ef, _notas_ef = _efeitos_no_teste(char, attr_key, skill)
    if isinstance(player_roll, int) and 1 <= player_roll <= 20:
        d20      = player_roll
        roll_log = f"d20={d20} (rolado pelo jogador)"
        if _vant_ef and not disadvantage:
            _segundo = random.randint(1, 20)
            roll_log += f", vantagem: segundo d20 = {_segundo}"
            d20 = max(d20, _segundo)
    else:
        d20, roll_log = _roll_d20_with_adv(advantage or _vant_ef, disadvantage)
    total    = d20 + mod + prof_pericia + _bonus_ef
    if _notas_ef:
        roll_log += f" [{'; '.join(_notas_ef)}]"
    if _desv_armadura:
        roll_log += f" [desvantagem: {_desv_armadura}]"
    sign     = "+" if mod >= 0 else ""
    prof_str = (f" +{prof_pericia}(prof)" if prof_pericia else "") + (f" {_bonus_ef:+d}(efeitos)" if _bonus_ef else "")

    critico       = d20 == 20
    falha_critica = d20 == 1
    sucesso       = critico or (not falha_critica and total >= difficulty)

    skill_label = f"{skill.capitalize()} ({attribute.capitalize()})" if skill else attribute.capitalize()
    result = (
        f"Teste de {skill_label} — CD {difficulty}\n"
        f"   {char['name']}: {roll_log} {sign}{mod}(mod){prof_str} = **{total}**\n"
    )
    if critico:
        result += "   CRÍTICO NATURAL! Sucesso automático."
    elif falha_critica:
        result += "   FALHA CRÍTICA! Falha automática."
    elif sucesso:
        result += f"   SUCESSO! ({total} ≥ CD {difficulty})"
    else:
        result += f"   FALHA. ({total} < CD {difficulty})"

    return result


def social_check(
    char_name: str,
    skill: str,
    dc: int,
    player_roll: int,
    target_name: str = "",
) -> str:
    """
    Resolve um teste de interação social (Persuasão, Intimidação, Enganação, etc.)
    após o jogador informar o resultado do dado.

    FLUXO CORRETO:
      1. Mestre narra a situação e diz: "Role Persuasão (Carisma) — CD X"
      2. Jogador informa o resultado do d20 (ex: "tirei 14")
      3. Mestre chama social_check(char_name, 'persuasão', dc, player_roll=14)
      4. A ferramenta aplica o modificador e retorna sucesso/falha

    Use para: convencer NPCs, intimidar guardas, enganar vilões, barganhar preços,
    reunir informações, recrutar aliados.

    Args:
        char_name:   Nome do personagem que está fazendo a ação social.
        skill:       Perícia: 'persuasão', 'intimidação', 'enganação', 'atuação',
                     'intuição', 'percepção', 'investigação', 'história', 'arcana'.
        dc:          Classe de Dificuldade do teste.
        player_roll: Resultado do dado d20 informado pelo jogador (1–20).
        target_name: Nome do NPC alvo (opcional — usado para contextualizar o resultado).
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    skill_lower  = skill.lower().strip()
    attr_key     = SKILL_ATTR_MAP.get(skill_lower, "carisma")
    s            = char["sheet"]
    mod          = _modifier(s.get(attr_key, 10))
    prof         = s.get("proficiencia", 2)

    is_proficient = _proficiente_na_pericia(s, skill_lower)
    total_mod    = mod + (prof if is_proficient else 0)

    # A ATITUDE DO ALVO mexe na CD. É o que faz a memória social ter peso
    # mecânico: convencer quem te deve a vida não pode custar o mesmo que
    # convencer quem você roubou. Cada 20 pontos de atitude valem 1 de CD,
    # com teto de ±5 — o suficiente para importar, longe de decidir sozinho.
    ajuste_atitude, alvo_rotulo = 0, ""
    if target_name:
        from rpg.tools import atitude_de as _atitude, _faixa_atitude as _faixa
        alvo = memory.campaign["characters"].get(memory.char_key(target_name))
        if alvo:
            valor = _atitude(alvo)
            if valor:
                ajuste_atitude = max(-5, min(5, -(valor // 20)))
                alvo_rotulo    = _faixa(valor)[0]
    dc_efetiva = max(1, dc + ajuste_atitude)

    d20          = max(1, min(20, int(player_roll)))
    # Quem enfeitiçou tem vantagem nos testes sociais com o enfeitiçado: o
    # jogador rolou um d20, o motor rola o segundo e fica com o maior.
    nota_encanto = ""
    if target_name:
        from rpg import encantos
        _alvo_enc = memory.campaign["characters"].get(memory.char_key(target_name))
        _e = encantos.ativo(_alvo_enc) if _alvo_enc else None
        if _e and memory.char_key(_e.get("por_nome", "")) == memory.char_key(char["name"]):
            segundo = random.randint(1, 20)
            nota_encanto = (f"   Vantagem: {target_name} está enfeitiçado por {char['name']} "
                            f"(segundo d20 = {segundo}).\n")
            d20 = max(d20, segundo)
    _bonus_ef, _vant_ef, _notas_ef = _efeitos_no_teste(char, attr_key, skill_lower)
    if _vant_ef and not nota_encanto:
        _seg_ef = random.randint(1, 20)
        nota_encanto += f"   Vantagem ({'; '.join(_notas_ef)}): segundo d20 = {_seg_ef}.\n"
        d20 = max(d20, _seg_ef)
    elif _notas_ef:
        nota_encanto += f"   {'; '.join(_notas_ef)}\n"
    total_mod += _bonus_ef
    total        = d20 + total_mod
    sign         = "+" if total_mod >= 0 else ""

    critico      = d20 == 20
    falha_critica= d20 == 1
    sucesso      = critico or (not falha_critica and total >= dc_efetiva)

    target_str   = f" com {target_name}" if target_name else ""
    if ajuste_atitude:
        nota_atitude = (f"  (base {dc} {ajuste_atitude:+d} — {target_name} está "
                        f"{alvo_rotulo})")
    else:
        nota_atitude = ""
    prof_tag     = " (com prof.)" if is_proficient else ""
    skill_cap    = skill.capitalize()

    result = (
        f"Teste de {skill_cap}{prof_tag} — CD {dc_efetiva}{nota_atitude}\n"
        f"{nota_encanto}"
        f"   {char['name']}{target_str}: d20={d20} {sign}{total_mod}(mod) = **{total}**\n"
    )
    if critico:
        result += "   CRÍTICO NATURAL! Sucesso total — reação excepcionalmente positiva."
    elif falha_critica:
        result += "   FALHA CRÍTICA! Falha total — reação negativa ou hostil."
    elif sucesso:
        result += f"   SUCESSO! ({total} ≥ CD {dc_efetiva})"
    else:
        result += f"   FALHA. ({total} < CD {dc_efetiva})"

    memory.save_campaign()
    return result


# Aviso anexado por attack_roll(end_turn=False). Fica numa constante porque o
# Ataque Múltiplo precisa removê-lo dos golpes intermediários — ali o turno não
# avança por ser multiattack, não porque sobrou uma ação bônus.
_BONUS_ACTION_HINT = "\n   Ação bônus disponível — ataque extra pendente neste turno."


def _npc_attack_entry(sheet: dict, weapon: str) -> dict | None:
    """Entrada de `ataques` que corresponde ao golpe pedido, ou None."""
    if not isinstance(sheet, dict):
        return None
    alvo = _norm_txt(weapon)
    if not alvo:
        return None
    for atk in (sheet.get("ataques") or []):
        if isinstance(atk, dict) and _norm_txt(atk.get("nome", "")) == alvo:
            return atk
    return None


def _npc_attack_dice(sheet: dict, weapon: str) -> tuple[int, int] | None:
    """
    Dado de dano de um ataque natural de monstro ("bite", "claw", "slam"…),
    lido do stat block do Open5e que spawn_monster gravou na ficha.

    Devolve (n_dados, faces) ou None quando o ataque não está na ficha — aí o
    chamador segue para a busca normal de arma do SRD.

    O bônus fixo do stat block é ignorado de propósito: ele É o modificador de
    atributo do monstro, que attack_roll já soma. Somar os dois dobraria o
    bônus de dano de todo inimigo do jogo.
    """
    if not isinstance(sheet, dict):
        return None
    alvo = _norm_txt(weapon)
    if not alvo:
        return None

    entrada = _npc_attack_entry(sheet, weapon)
    if entrada and entrada.get("dado"):
        n, s, _bonus = _parse_dice(entrada["dado"])
        return n, s

    # Compatibilidade com fichas criadas antes do campo "ataques".
    equip = sheet.get("equipamentos", {}) or {}
    if _norm_txt(equip.get("arma_principal") or "") == alvo and sheet.get("arma_dado"):
        n, s, _bonus = _parse_dice(sheet["arma_dado"])
        return n, s
    if _norm_txt(sheet.get("arma_secundaria") or "") == alvo and sheet.get("arma_dado_secundaria"):
        n, s, _bonus = _parse_dice(sheet["arma_dado_secundaria"])
        return n, s
    return None


def _resolve_damage_type(attacker_sheet: dict, weapon: str,
                         matched_hab: dict | None) -> str:
    """
    Tipo de dano de um ataque, na mesma ordem de prioridade do dado:
      1. habilidade da ficha (campo explícito ou descrição em PT);
      2. ataque natural do monstro, lido do stat block;
      3. arma do SRD (tabela local, depois Open5e);
      4. palpite pelo nome da arma (adaga → perfurante, maça → concussão).
    Devolve '' quando não dá para saber — dano sem tipo não sofre modificador,
    que é o comportamento seguro.
    """
    if matched_hab:
        explicito = _norm_damage_type(matched_hab.get("tipo_dano", "") or "")
        if explicito:
            return explicito
        pelo_texto = _damage_type_from_text(matched_hab.get("descricao", ""))
        if pelo_texto:
            return pelo_texto

    entrada = _npc_attack_entry(attacker_sheet, weapon)
    if entrada and entrada.get("tipo"):
        return entrada["tipo"]

    return _weapon_damage_type(weapon)


# Tipo de dano das armas mais comuns, por palavra no nome. Evita um
# round-trip ao SRD só para descobrir que espada corta e maça esmaga.
_WEAPON_DAMAGE_TYPE = (
    ("slashing",    ("espada", "sword", "machado", "axe", "cimitarra", "scimitar",
                     "foice", "sickle", "scythe", "alabarda", "halberd", "glaive",
                     "sabre", "falchion", "greataxe", "battleaxe", "handaxe",
                     "claws", "claw", "garra", "talon")),
    ("piercing",    ("adaga", "dagger", "arco", "bow", "flecha", "arrow", "besta",
                     "crossbow", "virote", "bolt", "lanca", "lança", "spear",
                     "lance", "pike", "rapieira", "rapier", "estoque", "azagaia",
                     "javelin", "tridente", "trident", "dardo", "dart", "bite",
                     "mordida", "presa", "sting", "ferrao", "ferrão", "beak")),
    ("bludgeoning", ("maca", "maça", "mace", "martelo", "hammer", "clava", "club",
                     "porrete", "cajado", "bordao", "bordão", "quarterstaff",
                     "staff", "funda", "sling", "flail", "mangual", "slam",
                     "desarmado", "unarmed", "punho", "fist", "tail", "cauda")),
)


def _weapon_damage_type(weapon: str) -> str:
    nome = _norm_txt(weapon)
    if not nome:
        return ""
    # O SRD primeiro: "Machadinha" e "Maça-Estrela" não estavam nas listas
    # de palavras, e o golpe saía sem tipo — sem resistência nem vulnerabilidade.
    a = _itens.arma(weapon)
    if a and a.get("tipo_dano"):
        return a["tipo_dano"]
    for tipo, palavras in _WEAPON_DAMAGE_TYPE:
        if any(p in nome for p in (_norm_txt(x) for x in palavras)):
            return tipo
    return ""


# ── A ARMA NA MÃO ─────────────────────────────────────────────────────────
# Três coisas que o motor não olhava, e por isso o equipamento não pesava na
# luta: a espada +1 não somava nada, a besta atirava para sempre sem virote, e
# uma arma que o personagem não tem funcionava igual a uma que ele tem.

_MAGICO_NO_NOME = re.compile(r"(?:^|\s)\+\s*([123])\b")
_MAGICO_NA_DESCRICAO = re.compile(
    r"\+\s*([123])\s*(?:em|de|no|nos|para)?\s*(?:ataque|dano|acerto|attack|damage)"
    r"|(?:b[ôo]nus|bonus)\s*(?:m[áa]gico\s*)?(?:de\s*)?\+\s*([123])",
    re.IGNORECASE)


def _item_do_inventario(char: dict, nome: str) -> dict | None:
    alvo = _norm_txt(nome)
    for it in (char.get("inventario") or []):
        if isinstance(it, dict) and _norm_txt(it.get("nome", "")) == alvo:
            return it
    return None


def _bonus_magico_da_arma(char: dict, weapon: str) -> int:
    """
    O +1/+2/+3 de uma arma mágica, do nome ("Espada Longa +1") ou da descrição
    gravada no inventário ("+2 em ataque e dano"). Zero quando não há.
    """
    a = _itens.arma(weapon)
    if a and a["bonus"]:
        magico = _itens.magicos().get(a.get("item_magico") or "") or {}
        # A Defensora (+3) só é +3 sintonizada; sem isso é uma espada longa.
        if magico.get("sintonizacao") and not _esta_sintonizado(char.get("sheet") or {}, weapon):
            return 0
        return int(a["bonus"])
    achado = _MAGICO_NO_NOME.search(weapon or "")
    if achado:
        return int(achado.group(1))
    item = _item_do_inventario(char, weapon)
    if item:
        achado = _MAGICO_NO_NOME.search(item.get("nome", "")) or \
                 _MAGICO_NA_DESCRICAO.search(item.get("descricao", "") or "")
        if achado:
            return int(next(g for g in achado.groups() if g))
    return 0


# ── O QUE A ARMA CARREGA ALÉM DO CORTE ────────────────────────────────────
# A adaga besuntada de veneno e a espada que o ferreiro encantou eram, para o
# motor, adaga e espada: a descrição era enfeite. Agora o que está ESCRITO no
# item acontece — um dado extra do seu tipo e, se for o caso, uma condição
# com teste de resistência.
#
# Por que ler da descrição em vez de criar uma ferramenta nova: a mesa do
# mestre já tem mais de cem, e a lição medida neste projeto é que ferramenta
# a mais é ferramenta esquecida. Ele já escreve a descrição — no add_item, na
# loja, quando o ferreiro devolve a lâmina. Escrever passa a bastar.
#
# O TETO existe porque essa mesma facilidade é a porta de "espada +5d6": duas
# faces de d8 no máximo, que é o rider de um item mágico de verdade
# (Flame Tongue é 2d6).
_RIDER_MAX_DADOS, _RIDER_MAX_FACES = 2, 8

_RIDER_DANO = re.compile(
    r"(\d)\s*d\s*(\d{1,2})\s*(?:de\s+)?(?:dano\s+)?(?:de\s+|d[eo]\s+)?"
    r"(fogo|gelo|frio|[áa]cido|veneno|el[ée]trico|rel[âa]mpago|radiante|"
    r"necr[óo]tico|ps[íi]quico|trovejante|for[çc]a|sagrado)",
    re.IGNORECASE)
_RIDER_CONDICAO = re.compile(
    r"\b(?:fica|ficar|deixa|aplica|causa|torna|imp[õo]e)\w*\b[^.;]{0,40}?"
    r"\b(envenenad\w+|ceg\w+|paralisad\w+|queimand\w+|amedrontad\w+|atordoad\w+|"
    r"imobilizad\w+|surd\w+|ca[íi]d\w+|incapacitad\w+)\b",
    re.IGNORECASE)
_RIDER_CD = re.compile(
    r"\bCD\s*(\d{1,2})\b[^.;]{0,25}?\b(CON|DES|FOR|SAB|INT|CAR|constitui\w*|destreza|"
    r"for[çc]a|sabedoria|intelig\w*|carisma)\b"
    r"|\b(CON|DES|FOR|SAB|INT|CAR|constitui\w*|destreza|for[çc]a|sabedoria|intelig\w*|"
    r"carisma)\b[^.;]{0,25}?\bCD\s*(\d{1,2})\b",
    re.IGNORECASE)
_RIDER_ATRIBUTO = {
    "con": "constituicao", "des": "destreza", "for": "forca",
    "sab": "sabedoria", "int": "inteligencia", "car": "carisma",
}
_RIDER_CONDICAO_PT = {
    "envenenad": "Envenenado", "ceg": "Cego", "paralisad": "Paralisado",
    "queimand": "Queimando", "amedrontad": "Amedrontado", "atordoad": "Atordoado",
    "imobilizad": "Imobilizado", "surd": "Surdo", "caid": "Caído",
    "incapacitad": "Incapacitado",
}


def _rider_atributo(bruto: str) -> str:
    n = _norm_txt(bruto)
    if n in _RIDER_ATRIBUTO:
        return _RIDER_ATRIBUTO[n]
    for sigla, nome in _RIDER_ATRIBUTO.items():
        if n.startswith(nome[:5]):
            return nome
    return ""


def efeito_extra_da_arma(char: dict, weapon: str) -> dict | None:
    """
    O que a DESCRIÇÃO do item promete além do dano normal:

        {"dados": (1, 6), "tipo": "poison", "condicao": "Envenenado",
         "salvaguarda": "constituicao", "cd": 12, "nota": "…"}

    None quando o item não promete nada — que é o caso da esmagadora maioria.
    """
    magico = _magico_por_nome(weapon or "")
    extra = ((magico or {}).get("efeito") or {}).get("dano_extra")
    if extra and (not magico.get("sintonizacao") or _esta_sintonizado(char.get("sheet") or {}, weapon)):
        n, faces, _b = _parse_dice(extra["dado"])
        return {"dados": (n, faces), "tipo": extra.get("tipo", ""),
                "contra": list(extra.get("contra") or []), "nota": ""}

    item = _item_do_inventario(char, weapon)
    desc = (item or {}).get("descricao", "") or ""
    if not desc.strip():
        return None

    efeito: dict = {}
    nota = []

    achado = _RIDER_DANO.search(desc)
    if achado:
        n, faces = int(achado.group(1)), int(achado.group(2))
        if n > _RIDER_MAX_DADOS or faces > _RIDER_MAX_FACES:
            nota.append(f"dano extra do item limitado a {_RIDER_MAX_DADOS}d{_RIDER_MAX_FACES}")
            n, faces = min(n, _RIDER_MAX_DADOS), min(faces, _RIDER_MAX_FACES)
        efeito["dados"] = (max(1, n), max(2, faces))
        efeito["tipo"] = _norm_damage_type(achado.group(3)) or ""

    achado = _RIDER_CONDICAO.search(desc)
    if achado:
        bruto = _norm_txt(achado.group(1))
        for raiz, nome in _RIDER_CONDICAO_PT.items():
            if bruto.startswith(raiz):
                efeito["condicao"] = nome
                break

    achado = _RIDER_CD.search(desc)
    if achado:
        g = achado.groups()
        cd, atributo = (g[0], g[1]) if g[0] else (g[3], g[2])
        efeito["cd"] = int(cd)
        efeito["salvaguarda"] = _rider_atributo(atributo or "")

    if not efeito:
        return None
    efeito["nota"] = " · ".join(nota)
    return efeito


def _nota_de_posse(char: dict, weapon: str, matched_hab) -> str:
    """
    Aviso quando um personagem do GRUPO ataca com o que não tem. Não recusa:
    bater com uma cadeira, com a tocha ou com o punho é jogo legítimo, e a
    recusa atrapalharia mais do que o aviso. Monstro não entra: as armas dele
    vêm do stat block, não do inventário.
    """
    if matched_hab or not memory.is_party_member(char) or not weapon:
        return ""
    if _item_do_inventario(char, weapon):
        return ""
    equipados = {_norm_txt(v) for v in (char.get("sheet", {}).get("equipamentos") or {}).values() if v}
    if _norm_txt(weapon) in equipados:
        return ""
    if _npc_attack_dice(char.get("sheet") or {}, weapon):
        return ""
    return (f"Aviso: '{weapon}' não está no inventário nem equipado em "
            f"{char.get('name', '')} — improviso ou item esquecido?")


# Cada arma de tiro come a sua munição. Nome do SRD em inglês e em português,
# porque a ficha guarda os dois conforme a origem.
_MUNICAO_DA_ARMA = (
    (("besta", "crossbow"),           ("virote", "virotes", "bolt", "bolts")),
    (("arco", "bow", "longbow", "shortbow"), ("flecha", "flechas", "arrow", "arrows")),
    (("funda", "sling"),              ("bala", "balas", "pedra", "pedras", "bullet", "bullets")),
    (("zarabatana", "blowgun"),       ("dardo", "dardos", "agulha", "needle", "needles")),
)


def _gastar_municao(char: dict, weapon: str) -> tuple[str, str]:
    """
    Gasta uma munição do inventário. Devolve (recusa, nota).

    A recusa só acontece quando a munição EXISTE na ficha e acabou: quem nunca
    registrou virote nenhum continua atirando, porque travar a luta por uma
    mochila mal preenchida seria pior do que a regra que se quer aplicar. Uma
    vez que a munição está anotada, ela passa a valer de verdade.
    """
    nome = _norm_txt(weapon or "")
    if not nome or not memory.is_party_member(char):
        return "", ""
    tipos = next((munis for chaves, munis in _MUNICAO_DA_ARMA
                  if any(c in nome for c in chaves)), None)
    if not tipos:
        return "", ""

    for it in (char.get("inventario") or []):
        if not isinstance(it, dict):
            continue
        n = _norm_txt(it.get("nome", ""))
        if not any(t in n for t in tipos):
            continue
        qtd = int(it.get("qtd", 0) or 0)
        if qtd <= 0:
            return (f"Erro: {char.get('name')} não tem mais {it.get('nome')} para "
                    f"a {weapon}. Recolha as que atirou ou compre mais."), ""
        it["qtd"] = qtd - 1
        _anotar_gasto(char, "_municao_gasta", it.get("nome", ""))
        if it["qtd"] <= 0:
            (char.get("inventario") or []).remove(it)
            return "", f"Última {it.get('nome')} gasta — a {weapon} está sem munição."
        return "", f"{it.get('nome')}: {it['qtd']} restantes."
    return "", ""


def _jogada_que_pergunta(fn):
    """
    attack_roll e use_ability chamados de fora: podem parar numa reação em
    "perguntar" (como o turno do inimigo). E a magia em curso liga a
    Resistência à Magia nas salvaguardas que ela provoca.
    """
    import functools

    @functools.wraps(fn)
    def envolto(*args, **kwargs):
        from rpg import tracos as _tr
        nome = fn.__name__
        if _pode_perguntar_agora(kwargs):
            pendente = _aviso_de_pergunta_pendente()
            if pendente:
                return pendente
            params = list(__import__("inspect").signature(fn).parameters)
            kw = dict(zip(params, args))
            kw.update(kwargs)
            return _com_perguntas({"fn": nome, "kw": kw}, [], None)
        magia = nome == "use_ability" and _tr_e_magia(args, kwargs)
        if magia:
            _tr._magias_em_curso += 1
        try:
            return fn(*args, **kwargs)
        finally:
            if magia:
                _tr._magias_em_curso -= 1
    return envolto


def _tr_e_magia(args, kwargs) -> bool:
    """A habilidade do use_ability é magia do SRD (a Resistência à Magia vale contra ela)."""
    from rpg import resolucao as _r
    nome_ator = kwargs.get("char_name", args[0] if args else "")
    nome_hab = kwargs.get("ability_name", args[1] if len(args) > 1 else "")
    ch = memory.campaign.get("characters", {}).get(memory.char_key(nome_ator or "")) or {}
    hab = next((h for h in ch.get("habilidades") or [] if isinstance(h, dict)
                and _norm_txt(h.get("nome", "")) == _norm_txt(nome_hab or "")), None)
    if hab is None:
        en = _SPELL_PT_TO_EN.get((nome_hab or "").lower())
        hab = {"nome": en or nome_hab or ""}
    return bool(_r._magia_srd(hab))


@_jogada_que_pergunta
def attack_roll(
    attacker_name: str,
    target_name: str,
    weapon: str,
    damage_dice_sides: int,
    damage_dice_count: int = 1,
    attack_attribute: str = "forca",
    is_proficient: bool = True,
    advantage: bool = False,
    disadvantage: bool = False,
    end_turn: bool = True,
    nao_letal: bool = False,
    _mao_inabil: bool = False,
    _skip_turn_check: bool = False,
) -> str:
    """
    Realiza um ataque completo: testa d20 contra a CA do alvo e, se acertar,
    rola o dano e aplica automaticamente ao alvo. Avança o turno ao final
    (a menos que end_turn=False para ataques extras/ações bônus).

    Suporta Vantagem/Desvantagem e aplica condições ativas automaticamente.

    Condições verificadas automaticamente:
    • Atacante Cego/Envenenado/Atordoado/etc. → desvantagem automática
    • Alvo Paralisado → ataque com vantagem + crítico automático em corpo-a-corpo
    • Alvo Cego/Caído → atacante ganha vantagem

    Args:
        attacker_name:     Nome do atacante.
        target_name:       Nome do alvo.
        weapon:            Nome da arma (ex: 'espada longa', 'arco curto', 'adaga').
        damage_dice_sides: Faces do dado de dano (ex: 8 para 1d8).
        damage_dice_count: Quantidade de dados de dano (padrão: 1).
        attack_attribute:  Atributo de ataque: 'forca' (corpo a corpo) ou 'destreza' (à distância/finesse).
        is_proficient:     Se o atacante é proficiente com a arma (padrão: True).
        advantage:         Se True, rola 2d20 e usa o maior.
        disadvantage:      Se True, rola 2d20 e usa o menor.
        end_turn:          Se True (padrão), avança o turno automaticamente.
                           Passe False para ataques extras/ações bônus na mesma rodada.
    """
    attacker = memory.campaign["characters"].get(memory.char_key(attacker_name))
    target   = memory.campaign["characters"].get(memory.char_key(target_name))

    if not attacker or not attacker.get("sheet"):
        return f"Atacante '{attacker_name}' não encontrado ou sem ficha D&D."
    if attacker.get("status") == "morto":
        return f"Erro: {attacker_name} está morto e não pode atacar."
    if (attacker.get("status") or "").lower() in ("inconsciente", "estabilizado", "dormindo"):
        return f"Erro: {attacker_name} está {attacker['status']} e não pode atacar."
    if not target or not target.get("sheet"):
        return f"Alvo '{target_name}' não encontrado ou sem ficha D&D."

    # Auto-cura: nunca operar com o ponteiro preso num combatente fora de combate.
    _heal_current_turn()

    # AUTORIDADE DE TURNO: recusa ação fora de ordem antes de qualquer
    # mutação/dado. (_skip_turn_check=True só para chamadas internas do motor.)
    if not _skip_turn_check:
        _viol = _combat_turn_violation(attacker_name)
        if _viol:
            return _viol

    if (attacker.get("sheet") or {}).get("nao_ataca"):
        return (f"Erro: {attacker_name} é um familiar e não ataca (SRD). Use Ajudar (Manobras): o "
                f"próximo ataque do grupo contra o alvo tem vantagem.")

    # O enfeitiçado não ataca quem o enfeitiçou; o banido não é alcançado.
    # Antes o orc enfeitiçado pelo clérigo o atacou no turno seguinte.
    from rpg import encantos
    _motivo_encanto = encantos.pode_atacar(attacker, target)
    if _motivo_encanto:
        return f"Erro: {_motivo_encanto}"
    _fora = _condicao_com(target, "untargetable")
    if _fora:
        return f"Erro: {target['name']} está {_fora} e ninguém o alcança agora."
    # Atacar quem se rendeu: ele volta a lutar, e os outros inimigos não se
    # rendem mais (viram o que acontece com quem larga as armas).
    _nota_rendido = ""
    if ((target.get("status") or "").lower() == "rendido"
            and memory.luta_com_o_grupo(attacker) != memory.luta_com_o_grupo(target)):
        target["status"] = "inimigo" if memory.lado_no_combate(target) == "inimigo" else "vivo"
        for _nm_r in (memory.campaign.get("combat_state") or {}).get("initiative_order") or []:
            _c_r = memory.campaign["characters"].get(memory.char_key(_nm_r))
            if _c_r and memory.luta_com_o_grupo(_c_r) == memory.luta_com_o_grupo(target):
                _c_r.setdefault("sheet", {})["recusa_rendicao"] = True
        _log_combat_event("atacou_rendido", attacker["name"], target["name"],
                          msg=f"{attacker['name']} ataca {target['name']}, que tinha se rendido")
        _nota_rendido = (f"   {target['name']} tinha se rendido: volta a lutar, e nenhum dos seus aliados se "
                         f"rende mais. (Mestre: quem viu vai contar.)\n")
    _cob_nivel, _cob_bonus = _cobertura_contra(attacker, target,
                                               any(r in (weapon or "").lower() for r in RANGED_WEAPONS))
    if _cob_nivel == "total":
        return (f"Erro: {target['name']} está atrás de cobertura total: nenhum ataque o alcança daqui. "
                f"Mude de posição ou espere ele sair. Nada foi gasto.")

    _no_ar = _condicao_com(target, "fora_do_corpo_a_corpo") or _condicao_com(attacker, "fora_do_corpo_a_corpo")
    if _no_ar and not any(r in (weapon or "").lower() for r in RANGED_WEAPONS) \
            and not (_npc_attack_entry(attacker.get("sheet") or {}, weapon) or {}).get("ranged"):
        return (f"Erro: {'quem ataca' if _condicao_com(attacker, 'fora_do_corpo_a_corpo') else target['name']} "
                f"está {_no_ar}: fora do alcance corpo a corpo. Use um ataque à distância.")

    _notas_santuario = []
    _meu_sant = [e for e in _efeitos_de(attacker) if e.get("santuario")]
    if _meu_sant and memory.luta_com_o_grupo(attacker) != memory.luta_com_o_grupo(target):
        attacker["sheet"]["efeitos"] = [e for e in attacker["sheet"].get("efeitos") or []
                                        if not e.get("santuario")]
        _notas_santuario.append(f"{attacker['name']} ataca e perde o Santuário")
    _sant = next((e for e in _efeitos_de(target) if e.get("santuario")), None)
    if _sant and memory.luta_com_o_grupo(attacker) != memory.luta_com_o_grupo(target):
        _passou_s, _linha_s = _rolar_salvaguarda(attacker, "sabedoria", int(_sant["santuario"]))
        if not _passou_s:
            _msg_s = (f"{attacker['name']} tenta atacar {target['name']}, mas o Santuário o detém "
                      f"({_linha_s}): perde o ataque.")
            _log_combat_event("attack_miss", attacker["name"], target["name"], msg=_msg_s)
            _marcar_que_atacou(attacker)
            if end_turn:
                _msg_s += _auto_advance_turn(attacker_name)
            memory.save_campaign()
            return _msg_s
        _notas_santuario.append(f"Santuário de {target['name']}: {_linha_s} — passa")

    # ALCANCE: quando o campo tem zonas, corpo-a-corpo exige a mesma zona e
    # tiro longo (ou com inimigo colado) sai com desvantagem. Vem antes de
    # qualquer dado — recusar depois de rolar já teria mudado o estado.
    # Sem zonas definidas, _checar_alcance devolve ("", False) e nada muda.
    _recusa_alcance, _desv_alcance = _checar_alcance(attacker_name, target_name, weapon)
    if _recusa_alcance:
        return _recusa_alcance
    if _desv_alcance:
        disadvantage = True

    # Exaustão nível 3+: desvantagem em ataques (e em saves, ver
    # resolve_saving_throw). É o degrau em que ficar de pé sem dormir começa
    # a custar a luta, não só a perícia.
    if _exaustao(attacker.get("sheet") or {}) >= 3:
        disadvantage = True

    # Sobrecarga: desvantagem em ataques. É o que faz o saque ser uma ESCOLHA
    # — levar tudo passa a custar a próxima luta.
    if _estado_de_carga(attacker)[0] != "livre":
        disadvantage = True

    sa = attacker["sheet"]
    st = target["sheet"]

    # Se "weapon" é nome de uma habilidade da ficha do atacante, usa seus dados
    matched_hab = _match_ability(attacker, weapon)
    if matched_hab:
        hab_dado = matched_hab.get("dado", "")
        hab_mana = matched_hab.get("custo_mana", 0)
        if hab_mana > 0:
            return use_ability(attacker_name, weapon, target_name,
                               _skip_turn_check=_skip_turn_check)
        if hab_dado:
            n_dice_hab, sides_hab, bonus_hab = _parse_dice(hab_dado)
            damage_dice_count = n_dice_hab
            damage_dice_sides = sides_hab
            _hab_bonus = bonus_hab
        else:
            _hab_bonus = 0
    else:
        _hab_bonus = 0

    # Auto-detecção de atributo: usa arma equipada quando weapon é nome de habilidade
    if attack_attribute.lower() == "forca":
        weapon_for_attr = weapon
        if matched_hab:
            weapon_for_attr = sa.get("equipamentos", {}).get("arma_principal", weapon) or weapon
        attack_attribute, mod = _weapon_attr(weapon_for_attr, sa)
    else:
        mod = _modifier(sa.get(attack_attribute.lower(), sa["forca"]))

    # Dado de dano, em ordem de prioridade:
    #   1. habilidade da ficha que já traz o próprio dado (tratado acima);
    #   2. ataque natural do monstro, vindo do stat block do Open5e;
    #   3. arma do SRD, buscada por nome.
    # O passo 2 é o que impede "bite"/"claw" (que não existem em /weapons/)
    # de cair no fallback genérico de 1d6 e achatar o dano de todo monstro.
    _nota_versatil = ""
    if not matched_hab or not matched_hab.get("dado"):
        npc_dice = _npc_attack_dice(sa, weapon)
        if npc_dice:
            damage_dice_count, damage_dice_sides = npc_dice
        else:
            weapon_data = _fetch_weapon_data(weapon)
            if weapon_data:
                damage_dice_count, damage_dice_sides = weapon_data
            _versatil = _versatil_a_duas_maos(attacker, weapon, _mao_inabil)
            if _versatil:
                damage_dice_count, damage_dice_sides = _versatil
                _nota_versatil = f"{weapon} nas duas mãos ({_versatil[0]}d{_versatil[1]})"

    # Artes Marciais: o monge sem armadura usa DES quando é melhor e o dado
    # de artes marciais nos golpes desarmados e nas armas de monge.
    _ma = _artes_marciais_no_golpe(attacker, weapon, matched_hab)
    if _ma:
        _ma_attr, _ma_die = _ma
        _ma_mod = _modifier(int(sa.get(_ma_attr, 10) or 10))
        if _ma_mod > mod:
            attack_attribute, mod = _ma_attr, _ma_mod
        if damage_dice_count * damage_dice_sides < _ma_die or "desarmad" in _norm_txt(weapon):
            damage_dice_count, damage_dice_sides = 1, _ma_die

    if (any(e.get("arma_conjuracao") for e in _efeitos(sa))
            and any(k in _norm_txt(weapon) for k in ("clava", "club", "bordao", "cajado", "quarterstaff"))):
        _attr_c = _atributo_de_conjuracao(sa) or "sabedoria"
        _mod_c = _modifier(int(sa.get(_attr_c, 10) or 10))
        if _mod_c > mod:
            attack_attribute, mod = _attr_c, _mod_c
        if damage_dice_count * damage_dice_sides < 8:
            damage_dice_count, damage_dice_sides = 1, 8

    # Tipo de dano do golpe — o que decide se o alvo resiste, é imune ou
    # vulnerável. '' quando não dá para saber (dano sem tipo, sem modificador).
    dmg_type = _resolve_damage_type(sa, weapon, matched_hab)

    _nota_prof = ""
    if is_proficient and not matched_hab and not _proficiente_com_arma(attacker, weapon):
        is_proficient = False
        _nota_prof = f"{attacker['name']} não tem proficiência com {weapon}: sem o bônus de proficiência"
    prof = sa.get("proficiencia", _proficiency_bonus(sa.get("nivel", 1))) if is_proficient else 0

    # ── Verificação automática de condições ─────────────────────────────────
    cond_notes = [n for n in (_nota_versatil, _nota_prof) if n]
    _arm_sem_prof = _armadura_sem_proficiencia(attacker)
    if _arm_sem_prof:
        disadvantage = True
        cond_notes.append(f"{_arm_sem_prof} sem proficiência → desvantagem")

    # Atacante tem condição que força desvantagem?
    if _has_condition_effect(attacker, "attack_disadvantage"):
        active_conds = [c["nome"] for c in _get_conditions(attacker)
                        if CONDITION_EFFECTS.get(c["nome"].lower(), {}).get("attack_disadvantage")]
        disadvantage = True
        cond_notes.append(f"{attacker['name']} está {', '.join(active_conds)} → desvantagem automática")

    # Atacante tem condição que concede vantagem (ex: invisível)? Contra quem
    # vê o invisível, a invisibilidade não conta.
    if _has_condition_effect(attacker, "attack_advantage"):
        active_conds = [c["nome"] for c in _get_conditions(attacker)
                        if CONDITION_EFFECTS.get(c["nome"].lower(), {}).get("attack_advantage")
                        and not (_norm_txt(c["nome"]) == "invisivel" and _ve_invisivel(target))]
        if active_conds:
            advantage = True
            cond_notes.append(f"{attacker['name']} está {', '.join(active_conds)} → vantagem automática")

    # Alvo invisível: quem ataca não o vê (desvantagem), a menos que veja o invisível.
    if _invisivel(target) and not _ve_invisivel(attacker):
        disadvantage = True
        cond_notes.append(f"{target['name']} está Invisível → desvantagem")

    # Alvo tem condição que concede vantagem ao atacante (Cego, Paralisado, etc.)?
    if _has_condition_effect(target, "defense_disadvantage"):
        active_conds = [c["nome"] for c in _get_conditions(target)
                        if CONDITION_EFFECTS.get(c["nome"].lower(), {}).get("defense_disadvantage")]
        advantage = True
        cond_notes.append(f"{target['name']} está {', '.join(active_conds)} → atacante ganha vantagem")

    # Rogar Maldição: desvantagem nos ataques contra quem amaldiçoou.
    if any(_norm_txt(c.get("nome", "")) == "amaldicoado"
           and _norm_txt(c.get("por", "")) == _norm_txt(target.get("name", ""))
           for c in _get_conditions(attacker) if isinstance(c, dict)):
        disadvantage = True
        cond_notes.append(f"{attacker['name']} está amaldiçoado por {target['name']} → desvantagem")

    # Alvo paralisado / petrificado → crítico automático (melee implícito)
    force_crit = _has_condition_effect(target, "auto_crit")
    if force_crit:
        cond_notes.append(f"{target['name']} está paralisado/petrificado → crítico automático!")

    # ── Bônus por Estilo de Combate / Inimigo Favorecido ────────────────────
    # Calcula UMA vez e reusa para a linha de log e para o cálculo final.
    weapon_l   = (weapon or "").lower()
    is_ranged  = _arma_de_tiro(weapon)
    # A versátil nas duas mãos conta como arma de duas mãos para a Grande Arma.
    is_2h_wpn  = _arma_de_duas_maos(weapon) or bool(
        not matched_hab and _versatil_a_duas_maos(attacker, weapon, _mao_inabil))
    has_off    = bool(sa.get("equipamentos", {}).get("arma_secundaria"))
    style      = _get_feature_choice(attacker, "Estilo de Combate")
    style_atk_bonus = 0   # +2 atk (Arquearia)
    style_dmg_bonus = 0   # +2 dmg (Duelo / Combate Duas Armas via mod off-hand)
    style_reroll_low = False  # Grande Arma re-rola 1s e 2s no dado de dano
    style_note     = ""
    if style == "Arquearia" and is_ranged:
        style_atk_bonus = 2
        style_note     = "Estilo: Arquearia → +2 atk à distância"
    elif style == "Duelo" and not is_ranged and not is_2h_wpn and not has_off:
        style_dmg_bonus = 2
        style_note      = "Estilo: Duelo → +2 dano (arma 1h, sem off-hand)"
    elif style == "Grande Arma" and not is_ranged and is_2h_wpn:
        style_reroll_low = True
        style_note       = "Estilo: Grande Arma → re-rola 1s/2s no dado"
    # Ataque com a outra mão (ação bônus, arma leve): o dano não soma o
    # modificador positivo, a menos que o estilo seja Combate com Duas Armas.
    _mod_dano = mod
    if _mao_inabil and mod > 0:
        if style == "Combate com Duas Armas":
            style_note = (style_note + " · " if style_note else "") + \
                "Estilo: Combate com Duas Armas → a outra mão soma o modificador"
        else:
            _mod_dano = 0

    # Inimigo Favorecido: +2 dano contra criatura cujo tipo de monstro
    # bate com o tipo escolhido. Usa o campo sheet["tipo"] (preenchido por
    # spawn_monster / create_npcs_with_real_stats via Open5e) ou cai no
    # raca como fallback.
    favored = _favored_enemy_types(attacker)
    favored_bonus = 0
    if favored:
        target_type = _norm_txt(
            st.get("tipo", "") or st.get("raca", "")
        )
        # Match por substring — "humanoid (orc)" casa com "humanoides"
        if target_type and any(t.rstrip("s") in target_type for t in favored):
            favored_bonus = 2
            style_note = (style_note + " · " if style_note else "") + "Inimigo Favorecido → +2 dano"
    if not favored_bonus and _tem_habilidade(attacker, "inimigo do inimigo"):
        _tk_ii = (memory.campaign.get("combat_state") or {}).get("turn_token")
        if sa.get("_inimigo_token") != _tk_ii:
            sa["_inimigo_token"] = _tk_ii
            favored_bonus = 2
            style_note = (style_note + " · " if style_note else "") + "Inimigo do Inimigo → +2 dano"

    # ── Golpe Divino (Domínio de Clérigo / Paladino) ────────────────────────
    # +1d8 (2d8 a partir do nv. 14) de dano elemental UMA vez por turno, ao
    # acertar com arma corpo-a-corpo. Gating 1×/turno via turn_token quando
    # há combate ativo; fora de combate, aplica a cada ataque.
    gd_info = None          # (n_dados, tipo) ou None
    if not is_ranged and not matched_hab:
        _gd = _golpe_divino_info(attacker)
        if _gd:
            _cs_gd   = memory.campaign.get("combat_state", {}) or {}
            _tk_now  = int(_cs_gd.get("turn_token", 0) or 0)
            _gd_used = sa.get("_gd_turn_token")
            if (not _cs_gd.get("is_active")) or _gd_used != _tk_now:
                gd_info = _gd

    # ── Crítico Aprimorado / Superior (Campeão) ─────────────────────────────
    crit_min = _crit_threshold(attacker)

    # ── Efeitos de combate (Bênção, Esquiva, Fúria, Marca do Caçador…) ──────
    # Antes eles eram texto: a Bênção rolava 1d4 na hora de conjurar e o
    # número não ia para ataque nenhum; a Esquiva não impunha desvantagem.
    _corpo_for = (not is_ranged) and attack_attribute.lower() == "forca"
    _mods = _mods_de_ataque(attacker, target, _corpo_for)
    if _mods["vantagem"]:
        advantage = True
    if _mods["desvantagem"]:
        disadvantage = True
    cond_notes.extend(_mods["notas"])
    cond_notes.extend(_notas_santuario)
    # Quem troca golpes de perto fica "colado" (sem zonas, é o que diz quem
    # está ao lado de quem para a área).
    _cs_eng = memory.campaign.get("combat_state") or {}
    if (_cs_eng.get("is_active") and not any(r in (weapon or "").lower() for r in RANGED_WEAPONS)
            and memory.luta_com_o_grupo(attacker) != memory.luta_com_o_grupo(target)):
        _par = sorted([memory.char_key(attacker["name"]), memory.char_key(target["name"])])
        _eng = [e for e in _cs_eng.get("engajados") or [] if e[:2] != _par]
        _eng.append(_par + [int(_cs_eng.get("round", 1) or 1)])
        _cs_eng["engajados"] = _eng
    from rpg import tracos as _tracos_a
    _matilha = _tracos_a.matilha(attacker, target)
    if _matilha:
        advantage = True
        cond_notes.append(_matilha)
    # Assassinato: vantagem contra quem ainda não teve um turno no combate.
    _cs_at = memory.campaign.get("combat_state") or {}
    _assassino = _tem_habilidade(attacker, "assassinato", "assassinate")
    if (_assassino and _cs_at.get("is_active")
            and memory.char_key(target.get("name", "")) not in (_cs_at.get("agiram") or [])):
        advantage = True
        cond_notes.append(f"Assassinato: {target['name']} ainda não agiu — vantagem")
    # Escuridão, Névoa: quem ataca não vê o alvo (desvantagem) e o alvo não
    # vê quem ataca (vantagem) — as duas se anulam, como manda o SRD.
    _cego_por = _zona_obscurecida(attacker_name) or _zona_obscurecida(target_name)
    if _cego_por:
        advantage = disadvantage = True
        cond_notes.append(f"{_cego_por}: ninguém vê ninguém — vantagem e desvantagem se anulam")
    else:
        # Escuridão natural: quem não tem visão no escuro não vê.
        if not _ve_no_escuro(attacker, target):
            disadvantage = True
            cond_notes.append(f"no escuro, {attacker['name']} não vê {target['name']} — desvantagem")
        if not _ve_no_escuro(target, attacker):
            advantage = True
            cond_notes.append(f"no escuro, {target['name']} não vê {attacker['name']} — vantagem")

    # ── A arma existe? Tem munição? É mágica? Carrega algo? ─────────────────
    _mag = _bonus_magico_da_arma(attacker, weapon)
    _rider = efeito_extra_da_arma(attacker, weapon)
    _nota_arma = _nota_de_posse(attacker, weapon, matched_hab)
    _recusa_mun, _nota_mun = _gastar_municao(attacker, weapon)
    if _recusa_mun:
        return _recusa_mun
    # Arremessada de longe (a azagaia na zona vizinha): sai da mão e fica no
    # chão até o fim da luta.
    _nota_arremesso = ""
    _a_arr = _itens.arma(weapon)
    if (_a_arr and "arremesso" in _a_arr["propriedades"] and not _a_arr["distancia"]
            and memory.is_party_member(attacker) and not matched_hab
            and (_distancia(attacker["name"], target["name"]) or 0) >= 1):
        _item_arr = _item_do_inventario(attacker, weapon)
        if _item_arr:
            _gastar_unidade(attacker, _item_arr)
            _anotar_gasto(attacker, "_arremessadas", _item_arr["nome"])
            _nota_arremesso = f"{_item_arr['nome']} arremessada: fica no chão até o fim da luta"

    # Reação do alvo antes do dado (Bandeira de Aviso).
    from rpg import reacoes as _reacoes
    _desv_reacao, _linhas_antes = _reacoes.antes_do_ataque(attacker, target, disadvantage)
    if _desv_reacao:
        disadvantage = True
        cond_notes.extend(_linhas_antes)

    # ── Rolagem do ataque ───────────────────────────────────────────────────
    d20, roll_log = _roll_d20_with_adv(advantage, disadvantage)
    attack_total  = d20 + mod + prof + style_atk_bonus + _mag + _mods["bonus"]
    # CA com os efeitos do alvo (Escudo da Fé, Pele de Árvore).
    target_ca     = _ca_efetiva(target) + _cob_bonus
    if _cob_bonus:
        cond_notes.append(f"{target['name']} tem {_COBERTURA_NOME[_cob_nivel]}: +{_cob_bonus} de CA")
    # Uso único (Guiar Ataque, o Raio Guia que marcou o alvo) acaba neste golpe.
    for _sh_e, _e in _mods["gastar"]:
        _gastar_efeito(_sh_e, _e)
    # Manto Sombrio: a invisibilidade das sombras acaba ao atacar.
    if any(isinstance(c, dict) and c.get("some_ao_atacar") for c in sa.get("condicoes") or []):
        sa["condicoes"] = [c for c in sa.get("condicoes") or [] if not (isinstance(c, dict) and c.get("some_ao_atacar"))]
        cond_notes.append(f"{attacker['name']} sai das sombras ao atacar")
    # Escondido: atacar revela quem estava escondido.
    _conds_atk = sa.get("condicoes") or []
    if any(_norm_txt(c.get("nome", "") if isinstance(c, dict) else str(c)) == "escondido"
           for c in _conds_atk):
        sa["condicoes"] = [c for c in _conds_atk
                           if _norm_txt(c.get("nome", "") if isinstance(c, dict) else str(c)) != "escondido"]
        cond_notes.append(f"{attacker['name']} sai do esconderijo ao atacar")
    _novo_d20, _linha_lamp = _reacoes.lampejo_no_ataque(attacker, target, d20, attack_total, target_ca)
    if _linha_lamp:
        attack_total += _novo_d20 - d20
        d20 = _novo_d20
        cond_notes.append(_linha_lamp)
    critico       = force_crit or (d20 >= crit_min)
    falha_critica = (not force_crit) and (d20 == 1)
    # Golpe de Sorte: o ataque que errou vira acerto.
    _sorte = ""
    if not critico and (falha_critica or attack_total < target_ca):
        for _e in _efeitos(sa):
            if _e.get("acerto_garantido"):
                sa["efeitos"] = [x for x in sa.get("efeitos") or [] if x is not _e]
                _sorte = _e.get("nome", "Golpe de Sorte")
                falha_critica = False
                break
    _prec = next((e for e in _efeitos(sa) if e.get("precisao")), None)
    if (_prec and not _sorte and not falha_critica and not critico and attack_total < target_ca
            and (usos_restantes(attacker, "Dados de Superioridade") or 0) > 0):
        _v_prec, _t_prec = _rolar_expr(_prec["precisao"])
        _gastar_uso(attacker, "Dados de Superioridade")
        sa["efeitos"] = [x for x in sa.get("efeitos") or [] if x is not _prec]
        attack_total += _v_prec
        cond_notes.append(f"Ataque Preciso: o ataque errava; +{_t_prec} → {attack_total}")
    _ca_antes_da_reacao = target_ca
    _linhas_reacao = []
    _erra_por_reacao = False
    _imgs = next((e for e in _efeitos(st) if int(e.get("imagens", 0) or 0) > 0), None)
    if _imgs and not falha_critica and memory.luta_com_o_grupo(attacker) != memory.luta_com_o_grupo(target):
        _n_img = int(_imgs["imagens"])
        _d20_img = random.randint(1, 20)
        if _d20_img >= {3: 6, 2: 8}.get(_n_img, 11):
            _ca_img = 10 + _modifier(int(st.get("destreza", 10) or 10))
            if attack_total >= _ca_img or critico:
                _imgs["imagens"] = _n_img - 1
                if _imgs["imagens"] <= 0:
                    st["efeitos"] = [e for e in st.get("efeitos") or [] if e is not _imgs]
                _linhas_reacao.append(f"Imagem Espelhada (d20={_d20_img}): o golpe acerta uma cópia, "
                                      f"que some (restam {_imgs['imagens']}).")
            else:
                _linhas_reacao.append(f"Imagem Espelhada (d20={_d20_img}): o golpe vai numa cópia e erra.")
            _erra_por_reacao = True
    if (not _erra_por_reacao and not _sorte and not falha_critica
            and (critico or attack_total >= target_ca)):
        _erra_por_reacao, _linhas_reacao = _reacoes.ao_ser_atingido(
            attacker, target, attack_total, target_ca, critico)
    if _erra_por_reacao:
        critico = False
    # Assassinato: todo acerto contra quem está Surpreso é crítico.
    if (_assassino and not critico and not falha_critica and not _erra_por_reacao
            and (attack_total >= target_ca or _sorte) and _surpreso(target)):
        critico = True
        cond_notes.append(f"Assassinato: {target['name']} está Surpreso — o acerto é crítico")
    # Armadura de Adamante: o crítico contra quem a veste vira acerto normal.
    if critico and any(e.get("critico_vira_normal") for e in _efeitos(st)):
        critico = False
        _adamante_acerta = True
        cond_notes.append(f"a armadura de adamante de {target['name']} desfaz o crítico")
    else:
        _adamante_acerta = False
    _acerta = ((critico or attack_total >= target_ca or bool(_sorte) or _adamante_acerta)
               and not _erra_por_reacao)
    if critico and crit_min < 20 and not force_crit and d20 < 20:
        style_note = (style_note + " · " if style_note else "") + \
                     f"Crítico ampliado ({crit_min}-20)"

    result = f"{attacker['name']} ataca {target['name']} com {weapon}!\n" + _nota_rendido
    if cond_notes:
        result += "   " + "\n   ".join(cond_notes) + "\n"
    if style_note:
        result += f"   {style_note}\n"
    for _nota in (_nota_arma, _nota_mun, _nota_arremesso):
        if _nota:
            result += f"   {_nota}\n"
    _atk_style_str = f" +{style_atk_bonus}(estilo)" if style_atk_bonus else ""
    _atk_mag_str = f" +{_mag}(mágica)" if _mag else ""
    _atk_efeito_str = f" {_mods['bonus']:+d}(efeitos)" if _mods["bonus"] else ""
    result += (f"   {roll_log} +{mod}(mod) +{prof}(prof){_atk_style_str}{_atk_mag_str}{_atk_efeito_str} "
               f"= **{attack_total}** vs CA {_ca_antes_da_reacao}\n")
    for _l in _linhas_reacao:
        result += f"   {_l}\n"

    if falha_critica:
        result += "   ERRO CRÍTICO! O ataque falha miseravelmente."
        _log_combat_event("attack_fumble", attacker["name"], target["name"],
                          msg=(f"{attacker['name']} → {target['name']} ({weapon}): "
                               f"d20=1 → ERRO CRÍTICO"),
                          weapon=weapon, d20=1, atk_total=attack_total,
                          ca=target_ca)
        _marcar_que_atacou(attacker)
        if end_turn:
            result += _auto_advance_turn(attacker_name)
        memory.save_campaign()
        return result

    if _acerta:
        if _sorte:
            result += f"   {_sorte}: o erro vira acerto.\n"
        n_dice = damage_dice_count * (2 if critico else 1)
        rolls  = [random.randint(1, damage_dice_sides) for _ in range(n_dice)]
        # Grande Arma: re-rola UMA VEZ cada 1 ou 2 inicial (mantém o novo
        # resultado mesmo que seja 1/2 de novo). Marca o que foi re-rolado.
        rerolled = []
        if style_reroll_low:
            for i, r in enumerate(rolls):
                if r <= 2:
                    new_r = random.randint(1, damage_dice_sides)
                    rerolled.append((i, r, new_r))
                    rolls[i] = new_r
        # Golpe Divino: dados extras d8 (dobram no crítico, como smite).
        gd_rolls: list[int] = []
        gd_total = 0
        if gd_info:
            gd_n, gd_tipo = gd_info
            gd_count = gd_n * (2 if critico else 1)
            gd_rolls = [random.randint(1, 8) for _ in range(gd_count)]
            gd_total = sum(gd_rolls)
            # Consome o uso do turno (1×/turno via turn_token).
            sa["_gd_turn_token"] = int(
                (memory.campaign.get("combat_state", {}) or {}).get("turn_token", 0) or 0
            )

        extra_dmg = style_dmg_bonus + favored_bonus
        # Dano da ARMA (sem o Golpe Divino, que tem tipo próprio e vira um
        # componente separado logo abaixo). O bônus mágico entra aqui: uma
        # espada +1 soma +1 no ataque E no dano, que é o que faz dela uma
        # espada +1 — antes ela era uma espada com nome comprido.
        # Braçadeiras de Arquearia: +2 de dano com arco.
        _arco = (sum(int(e.get("dano_arco", 0) or 0) for e in _efeitos(sa))
                 if (_itens.arma(weapon) or {}).get("chave") in ("longbow", "shortbow") else 0)
        dmg_arma = max(1, sum(rolls) + _mod_dano + _hab_bonus + extra_dmg + _mag + _arco)
        _enfraq = _condicao_com(attacker, "metade_dano_for")
        if _enfraq and attack_attribute.lower() == "forca":
            dmg_arma = max(1, dmg_arma // 2)
            result += f"   {attacker['name']} está {_enfraq}: metade do dano da arma.\n"
        dmg    = dmg_arma + gd_total
        detail = " + ".join(str(r) for r in rolls)
        bonus_str = f" +{_hab_bonus}" if _hab_bonus > 0 else (f" {_hab_bonus}" if _hab_bonus < 0 else "")
        if extra_dmg:
            bonus_str += f" +{extra_dmg}(estilo/favor)"
        if _mag:
            bonus_str += f" +{_mag}(mágica)"
        if _arco:
            bonus_str += f" +{_arco}(braçadeiras)"
        if gd_total:
            bonus_str += f" +{gd_total}(golpe divino)"

        result += f"   {'CRÍTICO! ' if critico else ''}ACERTO!\n"
        if rerolled:
            _rr = ", ".join(f"{old}→{new}" for _, old, new in rerolled)
            result += f"   Grande Arma re-rolou: {_rr}\n"
        if gd_rolls:
            result += (f"   Golpe Divino: {len(gd_rolls)}d8 "
                       f"[{' + '.join(str(r) for r in gd_rolls)}] = {gd_total} "
                       f"dano {gd_tipo}\n")
        _tipo_str = f" ({dmg_type})" if dmg_type else ""
        result += (f"   Dano{_tipo_str}: [{detail}] +{_mod_dano}(mod"
                   + (", outra mão" if _mao_inabil else "") + f"){bonus_str} = **{dmg}**\n")

        # Caminho único de dano: tipo → resistência → PV temporários → PV.
        # O Golpe Divino entra como componente próprio porque seu tipo é
        # outro (radiante/gélido/…), e um alvo pode resistir a um e não ao
        # outro dentro do MESMO golpe.
        _componentes = [(dmg_arma, dmg_type)]
        if gd_total:
            _componentes.append((gd_total, gd_info[1] if gd_info else ""))

        # O que a arma carrega: o veneno da lâmina, o fogo que o ferreiro
        # pôs nela. Entra como componente PRÓPRIO, com o seu tipo — um alvo
        # pode ser imune ao veneno e não ao corte do mesmo golpe. Dobra no
        # crítico, como todo dado extra de arma.
        _rider_rolls: list[int] = []
        if _rider and _rider.get("dados") and _rider_vale_contra(_rider, target):
            _rn, _rfaces = _rider["dados"]
            _rider_rolls = [random.randint(1, _rfaces)
                            for _ in range(_rn * (2 if critico else 1))]
            _componentes.append((sum(_rider_rolls), _rider.get("tipo", "")))
            result += (f"   {len(_rider_rolls)}d{_rfaces} de {weapon}: "
                       f"[{' + '.join(str(r) for r in _rider_rolls)}] = "
                       f"{sum(_rider_rolls)}"
                       + (f" ({_rider['tipo']})" if _rider.get("tipo") else "") + "\n")
            if _rider.get("nota"):
                result += f"   ({_rider['nota']})\n"

        # Ataque Furtivo: uma vez por turno, com o tipo da arma.
        _furtivo_d, _furtivo_motivo = _ataque_furtivo(attacker, target, weapon, advantage,
                                                      disadvantage, is_ranged)
        if _furtivo_d:
            _fr = [random.randint(1, 6) for _ in range(_furtivo_d * (2 if critico else 1))]
            _componentes.append((sum(_fr), dmg_type))
            sa["_furtivo_token"] = (memory.campaign.get("combat_state") or {}).get("turn_token")
            result += (f"   Ataque Furtivo ({_furtivo_motivo}): {len(_fr)}d6 "
                       f"[{' + '.join(map(str, _fr))}] = {sum(_fr)}\n")

        # Efeitos de quem ataca: Marca do Caçador, Favor Divino, Fúria.
        for _x in _dano_de_efeitos(attacker, target, _corpo_for, critico):
            if _x["valor"] < 0:
                _v0, _t0 = _componentes[0]
                _componentes[0] = (max(1, _v0 + _x["valor"]), _t0)
            else:
                _componentes.append((_x["valor"], _x["tipo"] or dmg_type))
            result += f"   {_x['texto']}\n"

        # Golpe Divino Aprimorado (paladino 11): 1d8 radiante em todo acerto
        # corpo a corpo com arma.
        if (not is_ranged and not matched_hab
                and _tem_habilidade(attacker, "golpe divino aprimorado", "improved divine smite")):
            _gda = [random.randint(1, 8) for _ in range(2 if critico else 1)]
            _componentes.append((sum(_gda), "radiant"))
            result += (f"   Golpe Divino Aprimorado: {len(_gda)}d8 "
                       f"[{' + '.join(map(str, _gda))}] = {sum(_gda)} radiante\n")

        # O que estava armado para o próximo acerto: Destruição Divina,
        # Ataque Atordoante, Destruição Marcante.
        _g_comps, _g_linhas, _g_conds, _g_manobras = _golpes_armados(attacker, target, is_ranged,
                                                                     matched_hab, critico, dmg_type)
        _componentes.extend(_g_comps)
        for _l in _g_linhas:
            result += f"   {_l}\n"
        # Golpe da Morte (assassino 17): acerto em quem está Surpreso pede CON
        # (CD 8 + DES + proficiência); falhou, o dano dobra.
        if _tem_habilidade(attacker, "golpe da morte", "death strike") and _surpreso(target):
            _cd_gm = 8 + _modifier(int(sa.get("destreza", 10) or 10)) + int(sa.get("proficiencia", 2) or 2)
            _passou_gm, _linha_gm = _rolar_salvaguarda(target, "constituicao", _cd_gm)
            if _passou_gm:
                result += f"   Golpe da Morte: {_linha_gm} — resiste.\n"
            else:
                _componentes = [(int(v or 0) * 2, t) for v, t in _componentes]
                result += f"   Golpe da Morte: {_linha_gm} — o dano DOBRA.\n"
        _componentes, _linhas_reducao = _reacoes.reduzir_dano(attacker, target, _componentes,
                                                              is_ranged, not matched_hab)
        for _l in _linhas_reducao:
            result += f"   {_l}\n"

        _res = _apply_damage(target, components=_componentes,
                             source_name=attacker["name"],
                             arma_magica=(_bypasses_material_resistance(weapon)
                                          or _tracos_a.armas_magicas(attacker)),
                             critico=bool(critico))
        hp_antes  = _res["hp_antes"]
        hp_depois = _res["hp_depois"]
        dmg       = _res["dano"]
        pct       = hp_depois / st["vida_max"] if st["vida_max"] > 0 else 0

        result += _fmt_notas(_res["notas"])
        result += f"\n   {target['name']}: {hp_antes} → {hp_depois}/{st['vida_max']}"
        _dmg_expr = f"[{detail}] +{mod}(mod){bonus_str} = {dmg}"
        _log_combat_event(
            "attack_crit" if critico else "attack_hit",
            attacker["name"], target["name"],
            msg=(f"{attacker['name']} → {target['name']} ({weapon}): "
                 f"d20={d20} +{mod}+{prof} = {attack_total} vs CA {target_ca} • "
                 f"{'CRÍTICO ' if critico else ''}ACERTO • "
                 f"dano {_dmg_expr} → HP {hp_antes}→{hp_depois}/{st['vida_max']}"),
            weapon=weapon, d20=d20, atk_total=attack_total, ca=target_ca,
            dmg=dmg, dmg_dice=detail, hp=hp_depois, hp_max=st["vida_max"],
            crit=bool(critico),
        )
        # A condição que a arma promete ("o alvo fica Envenenado"). O teste de
        # resistência é rolado aqui: reagir a um golpe não é escolha de
        # ninguém, e é assim que o ácido arremessado já funcionava.
        if _rider and _rider.get("condicao") and hp_depois > 0:
            _cond = _rider["condicao"]
            _save = _rider.get("salvaguarda") or "constituicao"
            _cd_rider = int(_rider.get("cd") or 0) or (8 + prof + mod)
            _passou, _linha_save = _rolar_salvaguarda(target, _save, _cd_rider)
            result += f"\n   {target['name']}: {_linha_save}"
            if _passou:
                result += f" — resistiu, {_cond} não pega."
            else:
                _conds_alvo = st.setdefault("condicoes", [])
                if not any(_norm_txt(c.get("nome", "") if isinstance(c, dict) else str(c))
                           == _norm_txt(_cond) for c in _conds_alvo):
                    _conds_alvo.append({"nome": _cond, "duracao": None})
                result += f" — **{_cond}**!"
                _log_combat_event("condition", attacker["name"], target["name"],
                                  msg=f"{target['name']} ficou {_cond} por {weapon}")

        # O que o golpe natural carrega (veneno, derrubar, agarrar, fogo) e a
        # Forma de Fogo de quem foi tocado (rpg/tracos.py).
        for _l in _tracos_a.depois_do_acerto(attacker, target, weapon, bool(critico), is_ranged):
            result += f"\n   {_l}"
        hp_depois = int(st.get("vida_atual", 0) or 0)

        if hp_depois > 0:
            for _nome_g, _cfg_g in _g_conds:
                result += _aplicar_condicao_de_golpe(attacker, target, _nome_g, _cfg_g)
            _escudo_f = next((e for e in _efeitos(st) if e.get("escudo_de_fogo")), None)
            if _escudo_f and not is_ranged and attacker.get("sheet", {}).get("vida_atual", 0) > 0:
                _ef_d = [random.randint(1, 8), random.randint(1, 8)]
                _res_f = _apply_damage(attacker, sum(_ef_d), _escudo_f["escudo_de_fogo"],
                                       source_name=target["name"], arma_magica=True)
                result += (f"\n   {_escudo_f.get('nome', 'Escudo de Fogo')} de {target['name']}: {attacker['name']} "
                           f"leva 2d8 [{' + '.join(map(str, _ef_d))}] = {_res_f['dano']} "
                           f"({_res_f['hp_antes']} → {_res_f['hp_depois']})")
                if _res_f["hp_depois"] == 0 and _res_f["hp_antes"] > 0:
                    result += _mark_at_zero_hp(attacker, target["name"])
            if _g_manobras:
                from rpg import superioridade as _sup
                for _e_m in _g_manobras:
                    result += _sup.depois_do_acerto(attacker, target, _e_m, dmg_type)
            for _l in _reacoes.depois_do_dano(attacker, target, dmg):
                result += f"\n   {_l}"

        _was_asleep = (target.get("status", "") or "").lower() == "dormindo"
        if hp_depois == 0:
            # Golpe não letal: só corpo a corpo, e só quando este golpe derrubou.
            _nocaute = bool((nao_letal or sa.get("nao_letal")) and not is_ranged and not matched_hab
                            and hp_antes > 0)
            result += _mark_at_zero_hp(target, attacker["name"], nocaute=_nocaute)
        elif _was_asleep:
            # 5e: uma criatura dormindo (Sleep) acorda ao sofrer dano.
            _wake_sleeper(target)
            result += f" {target['name']} acordou com o golpe!"
            _log_combat_event("wake", attacker["name"], target["name"],
                              msg=f"{target['name']} acordou ao sofrer dano")
        elif pct <= 0.25:
            result += " Estado crítico!"

        memory.save_campaign()
    else:
        result += (f"   ERROU! ({attack_total} < CA {target_ca})" if not _erra_por_reacao
                   else "   ERROU! (reação)")
        for _l in _reacoes.ao_errar(attacker, target, is_ranged):
            result += f"\n   {_l}"
        _log_combat_event("attack_miss", attacker["name"], target["name"],
                          msg=(f"{attacker['name']} → {target['name']} ({weapon}): "
                               f"d20={d20} +{mod}+{prof} = {attack_total} "
                               f"vs CA {target_ca} • ERROU"),
                          weapon=weapon, d20=d20, atk_total=attack_total,
                          ca=target_ca)

    _marcar_que_atacou(attacker)
    for _l in _reacoes.depois_do_ataque(attacker, target, _acerta, is_ranged, weapon):
        result += f"\n   {_l}"

    if end_turn:
        result += _auto_advance_turn(attacker_name)
    else:
        result += _BONUS_ACTION_HINT
    memory.save_campaign()
    return result


# ---------------------------------------------------------------------------
# 6. Habilidades
# ---------------------------------------------------------------------------

def learn_ability(
    char_name: str,
    ability_name: str,
    description: str,
    mana_cost: int = 0,
    damage_dice: str = "1d6",
) -> str:
    """
    Ensina uma nova habilidade ao personagem (ataque especial, magia, técnica, etc.)
    Use ao criar o personagem, ao subir de nível ou ao encontrar um mentor/grimório.

    Args:
        char_name:    Nome do personagem.
        ability_name: Nome da habilidade (ex: 'Bola de Fogo', 'Golpe Poderoso').
        description:  Efeito narrativo e mecânico da habilidade.
        mana_cost:    Custo em mana por uso (0 = sem custo, usável à vontade).
        damage_dice:  Dado de efeito (ex: '2d6', '3d8', '1d4'). Padrão: '1d6'.
    """
    char = memory.campaign["characters"].get(memory.char_key(char_name))
    if not char:
        return f"Personagem '{char_name}' não encontrado."

    if "habilidades" not in char:
        char["habilidades"] = []

    mexe_na_ca = any(_norm_txt(ability_name) == _norm_txt(h) for h in _HABILIDADES_DE_CA)

    existing = next((h for h in char["habilidades"] if h["nome"].lower() == ability_name.lower()), None)
    if existing:
        existing.update({"descricao": description, "custo_mana": mana_cost, "dado": damage_dice})
        memory.save_campaign()
        return f"Habilidade '{ability_name}' de {char['name']} atualizada."

    char["habilidades"].append({
        "nome":       ability_name,
        "descricao":  description,
        "custo_mana": mana_cost,
        "dado":       damage_dice,
    })
    # Defesa Sem Armadura e Resistência Dracônica entram na CA na mesma hora:
    # sem isto, a CA só mudava quando o personagem vestisse ou tirasse algo.
    ca_texto = ""
    if mexe_na_ca and char.get("sheet"):
        ca_antes = char["sheet"].get("ca", 10)
        _recalculate_ca(char)
        if char["sheet"].get("ca", ca_antes) != ca_antes:
            ca_texto = f"\n   CA: {ca_antes} → {char['sheet']['ca']}"

    memory.save_campaign()
    return (
        f"{char['name']} aprendeu '{ability_name}'!\n"
        f"   Dado: {damage_dice} | Custo: {mana_cost} mana\n"
        f"   Efeito: {description}{ca_texto}"
    )


@_jogada_que_pergunta
def use_ability(
    char_name: str,
    ability_name: str,
    target_name: str = "",
    saving_throw_stat: str = "",
    saving_throw_dc: int = 0,
    end_turn: bool = True,
    _skip_turn_check: bool = False,
    modo: str = "",
    _ritual: bool = False,
    _motor_rola: bool = False,
    _sem_custo: bool = False,
) -> str:
    """
    Usa uma habilidade do personagem: verifica mana, desconta o custo,
    rola o dado de efeito e retorna o resultado para narrar.

    Ações de classe com escolha (Ação Ardilosa: disparada, desengajar ou
    esconder) recebem a escolha em `modo`. Habilidade sem regra no motor
    (Taumaturgia, Luz) gasta o que custa e devolve a nota para o Mestre narrar.
    Avança o turno ao final (a menos que end_turn=False para ações bônus).

    Saving Throw (opcional): se saving_throw_stat e saving_throw_dc forem fornecidos,
    pausa o combate e aguarda o jogador rolar o teste — use resolve_saving_throw()
    depois para aplicar o dano e avançar o turno.

    Args:
        char_name:         Nome do personagem usando a habilidade.
        ability_name:      Nome exato da habilidade (sempre em inglês, como armazenado na ficha).
        target_name:       Alvo(s). Para magias de área com pool (Sleep, Color Spray):
                           passe nomes separados por vírgula ("Goblin A, Goblin B, Goblin C").
                           A magia ordena automaticamente por HP crescente e drena o pool.
                           Para dano/cura/condição direta: apenas um nome.
                           Se vazio em magias de pool, auto-detecta inimigos do combate.
        saving_throw_stat: Atributo do alvo para resistência (ex: 'destreza', 'constituicao').
        saving_throw_dc:   CD do saving throw (ex: 14). Ignorado se saving_throw_stat vazio.
        end_turn:          Se True (padrão), avança o turno ao final.
                           Passe False para habilidades de ação bônus.
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    # Auto-cura do ponteiro de turno antes de validar/gastar mana.
    _heal_current_turn()

    # AUTORIDADE DE TURNO: recusa uso fora de ordem antes de gastar mana/dado.
    if not _skip_turn_check:
        _viol = _combat_turn_violation(char_name)
        if _viol:
            return _viol

    habs = char.get("habilidades", [])
    # Exact match (case-insensitive)
    hab  = next((h for h in habs if h["nome"].lower() == ability_name.lower()), None)
    # Fallback: try PT-BR → EN translation
    if not hab:
        en_name = _SPELL_PT_TO_EN.get(ability_name.lower())
        if en_name:
            hab = next((h for h in habs if h["nome"].lower() == en_name.lower()), None)
    if not hab:
        available = ", ".join(h["nome"] for h in habs) if habs else "nenhuma"
        return f"'{char_name}' não conhece '{ability_name}'. Habilidades disponíveis: {available}."

    # ── Traço não é ação ──────────────────────────────────────────────────
    # Tradição Arcana, Arquétipo, Aumento de Atributo: são ESCOLHAS de ficha.
    # Usá-las gastava o turno e produzia a linha sem sentido que apareceu na
    # partida ("Sonael usou Tradição Arcana em Mineiro Corrompido 2").
    # Conjuração, Estilo de Combate, Ataque Furtivo: passivas. A tela deixava
    # "usar" e o Ataque Furtivo rolava 1d6 de dano solto, fora de qualquer
    # ataque. Agora o motor aplica sozinho onde vale (rpg/resolucao.py).
    from rpg import resolucao as _resolucao
    _como = _resolucao.como_resolve(hab, char)
    if _como["tipo"] == "reacao":
        return (f"Erro: '{hab.get('nome', ability_name)}' é reação: acontece no turno do inimigo, "
                f"e o motor a usa sozinho quando faz diferença. {_como['texto']} "
                f"Para impedir, desligue na tela de combate. Nada foi gasto.")
    if (_e_traco_passivo(hab.get("nome", "")) or _e_traco_passivo(ability_name)
            or _como["tipo"] == "passiva"):
        _porque = f" {_como['texto']}" if _como["tipo"] == "passiva" and _como["texto"] else ""
        return (
            f"Erro: '{hab.get('nome', ability_name)}' é um traço da ficha de "
            f"{char['name']}, não uma ação — não se usa em ninguém e não gasta "
            f"o turno. Ele já vale sozinho; narre o efeito, se houver.{_porque}"
        )

    # ── Coerção de alvo por modo da habilidade ────────────────────────────
    # Self-only (Segunda Fôlego, Fúria, Surto de Ação…) sempre afeta o
    # próprio conjurador, ignorando o que a UI/LLM passou como target.
    _alvo_escolha = _resolucao.alvo_do_modo(hab, char, modo)
    if _alvo_escolha in ("inimigo", "aliado"):
        pass                                   # Finta, Reagrupar: o alvo é o escolhido
    elif (_is_self_only_ability(hab.get("nome", "")) or _is_self_only_ability(ability_name)
            or _como.get("alvo") == "si"):
        target_name = char["name"]
    elif _como.get("alvo") == "nenhum":
        target_name = ""

    # ── Escuridão, Névoa, Silêncio ────────────────────────────────────────
    _m_zona = _resolucao._magia_srd(hab) or {}
    _arm_conj = _armadura_sem_proficiencia(char) if _m_zona else ""
    if _arm_conj:
        return (f"Erro: {char['name']} veste {_arm_conj} sem proficiência e não consegue "
                f"conjurar com ela. Nada foi gasto.")
    if _m_zona:
        _alvo_am = (target_name or "").split(",")[0].strip()
        _campo = _area_do_tipo(char["name"], "antimagia") or (
            _area_do_tipo(_alvo_am, "antimagia") if _alvo_am else None)
        if _campo and _m_zona.get("nome_srd") != "Antimagic Field":
            return (f"Erro: {_campo.get('nome', 'Campo Antimagia')}: nenhuma magia funciona ali. "
                    f"Nada foi gasto.")
        if _alvo_am and memory.char_key(_alvo_am) != memory.char_key(char["name"]):
            _circ_g = _resolucao.circulo_do_modo(hab, modo) or int(_m_zona.get("nivel", 0) or 0)
            _globo = _protegido_pelo_globo(char["name"], _alvo_am, _circ_g)
            if _globo:
                return (f"Erro: o {_globo} protege {_alvo_am}: magia de até 5º círculo vinda de fora não "
                        f"o afeta. Nada foi gasto.")
        from rpg import subclasses as _sub_s
        _cala = "" if _sub_s.metamagia_armada(char, "sutil") else _zona_silenciada(char["name"])
        if _cala and "V" in [c.strip() for c in str(_m_zona.get("componentes") or "").split(",")]:
            return (f"Erro: {char['name']} está no {_cala}: {hab['nome']} tem componente verbal e não "
                    f"sai sem som. Saia da zona ou use outra coisa. Nada foi gasto.")
        _alvo_z = (target_name or "").split(",")[0].strip()
        if (_alvo_z and memory.char_key(_alvo_z) != memory.char_key(char["name"])
                and _m_zona.get("origem") == "alvo"
                and "you can see" in (_m_zona.get("descricao_en") or "")):
            _nao_ve = (_zona_obscurecida(char["name"]) or _zona_obscurecida(_alvo_z)
                       or ("escuro" if not _ve_no_escuro(
                           char, memory.campaign["characters"].get(memory.char_key(_alvo_z))) else ""))
            if _nao_ve:
                return (f"Erro: {hab['nome']} exige ver o alvo, e o {_nao_ve} não deixa "
                        f"{char['name']} ver {_alvo_z}. Nada foi gasto.")

    # ── Tipo de criatura (Imobilizar Pessoa: só humanoides) ───────────────
    # A regra existia só no Enfeitiçar Pessoa: Imobilizar Pessoa paralisava o
    # lobo, e Curar Ferimentos curava o zumbi. Recusa ANTES de gastar; com
    # vários alvos, o que não serve fica de fora.
    from rpg import tracos as _tracos
    _nota_tipo = ""
    _nomes_t = [n.strip() for n in (target_name or "").split(",") if n.strip()]
    if _resolucao._magia_srd(hab) and _nomes_t and not (_get_control_effect(hab) or {}).get("pool"):
        _recusas_t, _ficam_t = [], []
        for _n_t in _nomes_t:
            _rec_t = _tracos.recusa_de_tipo(hab, memory.campaign["characters"].get(memory.char_key(_n_t)))
            if _rec_t:
                _recusas_t.append(_rec_t)
            else:
                _ficam_t.append(_n_t)
        if _recusas_t and not _ficam_t:
            return f"Aviso: {_recusas_t[0]}. Nada foi gasto."
        if _recusas_t:
            target_name = ", ".join(_ficam_t)
            _nota_tipo = "".join(f"\n   {r} — fica de fora." for r in _recusas_t)

    # ── Componente material caro ──────────────────────────────────────────
    _comp = componente_caro(hab) if memory.is_party_member(char) and not _sem_custo else None
    _ef_comp = _resolucao.efeito_de_magia(hab)[1] if _comp else {}
    _item_comp = None
    if _comp and not (_ef_comp or {}).get("reviver"):
        _item_comp = _item_do_componente(char, _comp)
        if not _item_comp:
            return (f"Aviso: {hab['nome']} pede um componente de {_comp['custo']} po "
                    f"({_comp['palavras'][0]}) na mochila de {char['name']}"
                    + (", que a magia consome" if _comp["consome"] else "") + ". A bolsa de componentes "
                    f"não cobre o que tem preço. Nada foi gasto.")

    # ── Alcance da habilidade ─────────────────────────────────────────────
    # Cone e toque nascem no conjurador: só pegam quem está na zona dele. Só
    # o ataque com arma conferia isso, e por isso Burning Hands acertava
    # inimigo do outro lado da câmara. A recusa vem ANTES de gastar mana.
    _motivo_zona = _habilidade_nasce_no_conjurador(hab, ability_name)
    if _motivo_zona and target_name and _norm_txt(target_name) != _norm_txt(char["name"]):
        _dist = _distancia(char["name"], target_name.split(",")[0].strip())
        if _dist:
            _za, _zb = _zona_de(char["name"]), _zona_de(target_name.split(",")[0].strip())
            return (
                f"Erro: FORA DE ALCANCE: {hab['nome']} {_motivo_zona} e só pega "
                f"quem está em **{_za}**; {target_name} está em **{_zb}**. "
                f"Mova-se até lá ou escolha outro alvo. Nada foi gasto."
            )

    s     = char["sheet"]
    custo = hab.get("custo_mana", 0)
    # Arma Espiritual em campo: atacar de novo é ação bônus, sem mana.
    if _resolucao.reuso_gratis(char, hab):
        custo = 0
        if _resolucao.circulo_do_modo(hab, modo):
            modo = ""
    # Ritual (fora do combate, pelo Grimório): sem mana, dez minutos a mais.
    if _ritual:
        if not _resolucao.pode_ritual(char, hab):
            return (f"Aviso: {hab['nome']} não pode ser conjurada como ritual por {char['name']} "
                    f"(a magia não é ritual, ou a classe não conjura rituais). Nada foi gasto.")
        custo = 0

    # ── Conjurar com mais mana (círculo acima do da magia) ────────────────
    _circulo = _resolucao.circulo_do_modo(hab, modo)
    if _circulo and _item_conjurando(s):
        pass            # o item paga o círculo (cargas), não a mana nem o nível
    elif _circulo:
        _opcoes = _resolucao.circulos_da_magia(hab, char)
        if f"c{_circulo}" not in _opcoes:
            return (f"Aviso: {hab['nome']} não pode ser conjurada no {_circulo}º círculo agora "
                    f"(círculo acima do que o nível alcança, ou mana insuficiente). Nada foi gasto.")
        _base_c = int((_resolucao._magia_srd(hab) or {}).get("nivel", 1) or 1)
        if _circulo > _base_c:
            custo = SPELL_MANA_COST[_circulo]

    from rpg import subclasses as _sub
    _nota_graca = ""
    if _sem_custo:
        custo = 0
    elif custo and _resolucao._magia_srd(hab):
        _gratis = _sub.custo_de_graca(char, hab, _circulo)
        if _gratis:
            custo = 0
            _nota_graca = f"\n   {_gratis}: sem mana."

    # ── RECARGA 5–6 ────────────────────────────────────────────────────────
    # O poder de recarga gasto não pode ser usado de novo até o d6 devolvê-lo
    # no início do turno (_rolar_recargas). Antes, só o braço da IA de NPC
    # cobrava isso: quando o MESTRE conduzia o chefe por use_ability — que é o
    # caso normal — nada era gasto nem conferido, e o dragão soprava toda
    # rodada. A cobrança vem antes da mana: recusar depois de descontar
    # deixaria o custo pago por uma ação que não aconteceu.
    _rec = _nome_da_recarga(char, hab.get("nome", ""), ability_name)
    if _rec:
        _cfg = s["recargas"][_rec]
        if not _cfg.get("pronto", True):
            _d6 = _cfg.get("ultimo_d6")
            _rolagem = f" (último d6: {_d6})" if _d6 else ""
            return (
                f"Erro: **{_rec}** de {char['name']} está GASTO{_rolagem}. "
                f"Recarrega com {int(_cfg.get('min', 5) or 5)}+ no d6, rolado "
                f"sozinho no início do turno dele.\n"
                f"   Use outra ação nesta rodada."
            )

    # ── USOS POR DESCANSO ──────────────────────────────────────────────────
    # Surto de Ação, Fúria, Segunda Fôlego e Canalizar Divindade não custam
    # mana, e por isso não custavam NADA: a ficha não tinha contador e o
    # guerreiro tinha uma ação extra em todo turno. Como a recarga, a cobrança
    # vem antes da mana — recusar depois de descontar deixaria o custo pago
    # por uma ação que não aconteceu.
    _usos_max = usos_maximos(char, hab.get("nome", ""))
    # Corpo Vazio gasta 4 de ki; a Forma Selvagem e a Fonte de Magia cobram
    # (ou não) conforme a escolha, e quem cobra é a própria ação; o Ataque
    # Atordoante só gasta o ki quando o golpe acerta.
    _cfg_acao = ((_resolucao.ACOES_DE_CLASSE.get(_como.get("chave", "")) or {})
                 if _como["tipo"] == "acao_de_classe" else {})
    _custo_uso = int(_cfg_acao.get("custo_uso", 1) or 1)
    _uso_manual = bool(_cfg_acao.get("uso_manual") or _cfg_acao.get("pool"))
    if _usos_max is not None and not _uso_manual:
        _restam = usos_restantes(char, hab.get("nome", ""))
        if _restam < _custo_uso:
            _quando = _USOS_POR_DESCANSO[_chave_de_uso(hab["nome"])][0]
            _falta = (f"precisa de {_custo_uso}, restam {_restam}" if _custo_uso > 1
                      else f"0 de {_usos_max}")
            return (
                f"Erro: **{hab['nome']}** de {char['name']} está gasto "
                f"({_falta}). Volta no descanso {_quando}"
                + (" (short_rest)." if _quando == "curto" else " (long_rest).")
                + "\n   Use outra ação nesta rodada. Nada foi gasto."
            )

    # Na forma de fera o druida não conjura (SRD: Forma Selvagem).
    from rpg import criaturas as _criaturas
    _fera = _criaturas.em_forma_selvagem(char)
    if (_fera and _resolucao._magia_srd(hab)
            and not (_tem_habilidade(char, "magias lunares")
                     and (_resolucao._magia_srd(hab) or {}).get("nome_srd") == "Cure Wounds")):
        return (f"Erro: {char['name']} está na forma de {_fera['forma']} e não conjura magias. "
                f"Volte à forma normal primeiro (Forma Selvagem → voltar). Nada foi gasto.")

    # Ação de classe e magia de efeito conferem o que precisam (a escolha, o
    # alvo, ter atacado antes) ANTES de gastar mana ou uso.
    if _como["tipo"] in ("acao_de_classe", "efeito"):
        _recusa = _resolucao.validar(char, hab, target_name, modo)
        if _recusa:
            return _recusa

    # Pontos de magia (a variante que o jogo usa): do 6º círculo em diante,
    # cada círculo só uma vez por descanso longo.
    _circ_alto = 0
    if custo > 0 and int(s.get("mana_max", 0) or 0) > 0:
        _m_alto = _resolucao._magia_srd(hab) or {}
        _circ_alto = _circulo or int(_m_alto.get("nivel", 0) or 0)
        if _circ_alto >= 6 and _circ_alto in (s.get("circulos_altos_usados") or []):
            return (f"Aviso: {char['name']} já conjurou uma magia de {_circ_alto}º círculo desde o último "
                    f"descanso longo — com pontos de magia, do 6º em diante é uma de cada por descanso. "
                    f"Nada foi gasto.")

    if custo > 0:
        if s["mana_atual"] < custo:
            return (
                f"Erro: {char['name']} não tem mana suficiente para '{ability_name}'!\n"
                f"Mana: {s['mana_atual']}/{s['mana_max']} (necessário: {custo})"
            )
        s["mana_atual"] -= custo
        if _circ_alto >= 6:
            s.setdefault("circulos_altos_usados", []).append(_circ_alto)
    # O componente que a magia consome vai embora com ela.
    if _item_comp is not None and _comp and _comp["consome"]:
        _item_comp["qtd"] = int(_item_comp.get("qtd", 1) or 1) - 1
        if _item_comp["qtd"] <= 0:
            char["inventario"] = [i for i in char.get("inventario") or [] if i is not _item_comp]

    # A reserva da Cura pelas Mãos é gasta pelo quanto curou, não por uso.
    _por_reserva = (_como["tipo"] == "acao_de_classe"
                    and (_resolucao.ACOES_DE_CLASSE.get(_como.get("chave", "")) or {}).get("pool"))
    if _usos_max is not None and not _uso_manual and not _cfg_acao.get("gasta_no_acerto"):
        _gastar_uso(char, hab["nome"], _custo_uso)

    if _rec:
        _gastar_recarga(char, _rec)

    # ── Contramágica de quem está do outro lado ────────────────────────────
    # A mana já foi: a magia anulada gasta o espaço (SRD).
    from rpg import reacoes as _reacoes
    _nota_meta = _nota_graca
    if _resolucao._magia_srd(hab) and any(isinstance(c, dict) and c.get("some_ao_atacar")
                                          for c in s.get("condicoes") or []):
        s["condicoes"] = [c for c in s.get("condicoes") or [] if not (isinstance(c, dict) and c.get("some_ao_atacar"))]
        _nota_meta += f"\n   {char['name']} sai das sombras ao conjurar."
    if _resolucao._magia_srd(hab) and _sub.metamagia_armada(char, "sutil") and not _sem_custo:
        _sub.consumir_metamagia(char, "sutil")
        _nota_meta += "\n   Magia Sutil (1 ponto): sem som nem gesto — ninguém percebe a conjuração."
        _contra = ""
    else:
        _contra = _reacoes.contramagica(char, hab) if _como["tipo"] != "acao_de_classe" else ""
    if _contra and not _contra.startswith("("):
        result = (f"{char['name']} conjura {hab['nome']}"
                  + (f" em {target_name}" if target_name else "") + "!\n"
                  f"   Custo: {custo} mana | Mana restante: {s['mana_atual']}/{s['mana_max']}\n"
                  f"   {_contra}")
        _log_combat_event("ability", char["name"], target_name,
                          msg=f"{char['name']} usou {hab['nome']} — anulada por Contramágica",
                          ability=hab["nome"])
        memory.save_campaign()
        if end_turn and _como.get("slot") != "livre":
            result += _auto_advance_turn(char_name)
        memory.save_campaign()
        return result
    _nota_contra = (f"\n   {_contra}" if _contra else "") + _nota_meta + _nota_tipo
    if _resolucao._magia_srd(hab) and not _sem_custo:
        for _tipo_m in ("distante", "estendida"):
            if _sub.consumir_metamagia(char, _tipo_m):
                _nota_contra += f"\n   {_sub.METAMAGIAS[_tipo_m][0]} (1 ponto): {_sub.METAMAGIAS[_tipo_m][2]}."
        _nota_contra += _sub.surto(char, hab)
        _cs_c = memory.campaign.get("combat_state") or {}
        _ord_c = _cs_c.get("initiative_order") or []
        _i_c = _cs_c.get("current_turn_index", 0)
        if (_cs_c.get("is_active") and isinstance(_i_c, int) and 0 <= _i_c < len(_ord_c)
                and memory.char_key(_ord_c[_i_c]) == memory.char_key(char["name"])):
            _resolucao._eco()["conjurou"] = True
    # Intensificada e Cuidadosa valem para as salvaguardas desta magia.
    _desv_primeira = bool(_resolucao._magia_srd(hab) and salvaguarda_da_habilidade(hab) and not _sem_custo
                          and _sub.consumir_metamagia(char, "intensificada"))
    if _desv_primeira:
        _nota_contra += "\n   Magia Intensificada (3 pontos): o primeiro alvo faz a salvaguarda com desvantagem."
    _cuidadosa = bool(_resolucao._magia_srd(hab) and area_da_habilidade(hab) and not _sem_custo
                      and _sub.consumir_metamagia(char, "cuidadosa"))
    if _cuidadosa:
        _nota_contra += "\n   Magia Cuidadosa (1 ponto): os aliados na área passam na salvaguarda."

    # ── Efeito, ação de classe e narrativa: caminho próprio ────────────────
    # (rpg/resolucao.py). Nenhum deles rola o "dado" da ficha como dano ou
    # cura: a Bênção vira +1d4 nos ataques, a Ação Ardilosa vira movimento, a
    # Taumaturgia vira nota para o Mestre.
    if _como["tipo"] in ("efeito", "acao_de_classe", "narrativa"):
        _alvo_txt = (f" em {target_name}" if target_name
                     and memory.char_key(target_name) != memory.char_key(char["name"]) else "")
        result = (f"{char['name']} usa {hab['nome']}{_alvo_txt}!\n"
                  f"   Custo: {custo} mana | Mana restante: {s['mana_atual']}/{s['mana_max']}"
                  + _nota_contra)
        if _usos_max is not None:
            _chave_u = _chave_de_uso(hab["nome"])
            _quando_volta = _USOS_POR_DESCANSO[_chave_u][0]
            result += (f"\n   {'Reserva' if _por_reserva else 'Usos'}: "
                       f"{usos_restantes(char, hab['nome'])}/{_usos_max} "
                       f"(volta no descanso {_quando_volta})")
        _magia = _resolucao._magia_srd(hab) or {}
        if _requires_concentration(hab) or _magia.get("concentracao"):
            result += _start_concentration(char, hab["nome"])
            result += f"\n   {char['name']} está concentrado em {hab['nome']}."
        result += _resolucao.executar(char, hab, target_name, modo)
        _log_combat_event(
            "ability", char["name"], target_name,
            msg=(f"{char['name']} usou {hab['nome']}"
                 + (f" ({modo})" if modo else "")
                 + (f" em {target_name}" if _alvo_txt else "")
                 + (" — efeito narrado pelo Mestre" if _como["tipo"] == "narrativa" else "")),
            ability=hab["nome"], resolucao=_como["tipo"],
        )
        memory.save_campaign()
        # Sem custo de ação (Guiar Ataque, Ataque Imprudente) não encerra turno.
        if end_turn and _como.get("slot") != "livre":
            result += _auto_advance_turn(char_name)
        memory.save_campaign()
        return result

    # O dado só existe se a habilidade tiver um — e só vira ferida se o texto
    # disser que é dano (ver efeito_do_dado). Sem isso, benzer um aliado
    # tirava 1d6 de vida dele.
    _efeito = efeito_do_dado(hab)
    _formula = dado_efetivo(hab, char)
    if _circulo:
        _formula = _resolucao.dado_no_circulo(hab, _formula, _circulo)
    # Mísseis Mágicos e Raio Ardente: um dado por dardo (ou raio), cada um no
    # alvo escolhido. O motor rolava um dado só, num alvo só: o 1d4+1 de um
    # dardo, e conjurar no 3º círculo gastava 5 de mana pelo mesmo dardo.
    _n_proj = _resolucao.projeteis(hab, _circulo) if (_efeito == "dano" and target_name) else 0
    _formula_proj = ""
    if _n_proj and _formula:
        _formula_proj, _formula = _formula, ""
    if _formula:
        n_dice, sides, bonus = _parse_dice(_formula)
        # Curar Ferimentos, Palavra Curativa: o SRD soma o modificador de
        # conjuração. O compêndio marcava (soma_mod) e o motor ignorava.
        if _efeito == "cura" and (_resolucao._magia_srd(hab) or {}).get("soma_mod"):
            _attr_cura = _atributo_de_conjuracao(s) or "sabedoria"
            bonus += max(0, _modifier(int(s.get(_attr_cura, 10) or 10)))
        rolls      = [random.randint(1, sides) for _ in range(n_dice)]
        if (_efeito == "dano" and not _sem_custo and _resolucao._magia_srd(hab)
                and _sub.consumir_metamagia(char, "potencializada")):
            _quantos = max(1, _modifier(int(s.get("carisma", 10) or 10)))
            _baixos = sorted(range(len(rolls)), key=lambda i: rolls[i])[:_quantos]
            _antes_p = list(rolls)
            for _i_p in _baixos:
                if rolls[_i_p] <= sides // 2:
                    rolls[_i_p] = random.randint(1, sides)
            _nota_contra += (f"\n   Magia Potencializada (1 ponto): dados {_antes_p} → {rolls}.")
        total_dano = sum(rolls) + bonus
    else:
        n_dice, sides, bonus = 0, 0, 0
        rolls, total_dano = [], 0

    target_str = f" em {target_name}" if target_name else ""
    detail     = " + ".join(str(r) for r in rolls)
    bonus_str  = f" + {bonus}" if bonus > 0 else (f" - {abs(bonus)}" if bonus < 0 else "")

    if _formula:
        rotulo = {"cura": "cura", "dano": "dano", "bonus": "bônus"}.get(_efeito, "")
        _linha_dado = (f"   {n_dice}d{sides}: [{detail}]{bonus_str} = **{total_dano}**"
                       + (f" ({rotulo})" if rotulo else "") + "\n")
    else:
        _linha_dado = ""

    result = (
        f"{char['name']} usa {hab['nome']}{target_str}!\n"
        f"   Custo: {custo} mana | Mana restante: {s['mana_atual']}/{s['mana_max']}\n"
        + (_nota_contra.lstrip("\n") + "\n" if _nota_contra else "")
        + f"{_linha_dado}"
        f"   Efeito: {hab['descricao']}"
    )

    # O recurso gasto aparece na hora, como a mana. Sem isto, o jogador só
    # descobre que a Fúria acabou quando o motor recusa a próxima.
    if _usos_max is not None:
        _quando_volta = _USOS_POR_DESCANSO[_chave_de_uso(hab["nome"])][0]
        result += (f"\n   Usos: {usos_restantes(char, hab['nome'])}/{_usos_max} "
                   f"(volta no descanso {_quando_volta})")

    # Concentração: só se mantém UMA magia por vez. Antes disto, um clérigo
    # sustentava Bênção, Escudo da Fé e Arma Espiritual ao mesmo tempo.
    if _requires_concentration(hab):
        result += _start_concentration(char, hab["nome"])
        result += f"\n   {char['name']} está concentrado em {hab['nome']}."

    # ── Aplica efeito ao alvo ────────────────────────────────────────────────
    ctrl_effect = _get_control_effect(hab)
    # Inicializa lista de afetados por pool spell — usada no log mesmo
    # quando o branch pool não roda (mantém escopo seguro).
    slept: list[str] = []

    # Área: só para dano, e só com zonas em jogo. Sem isso, ("", []) e a
    # habilidade segue pelo caminho de alvo único — que é como ela se
    # comportava antes de existir área nenhuma.
    _zona_area, _alvos_area = ("", [])
    if _efeito == "dano" and ctrl_effect is None and not _n_proj:
        _zona_area, _alvos_area = _alvos_em_area(char_name, hab, target_name)

    # Imobilizar Pessoa no 3º círculo pega duas pessoas, no 4º três: a tela
    # manda os nomes separados por vírgula. O motor cobrava o círculo e
    # paralisava um só.
    _alvos_ctrl: list[dict] = []
    _nomes_ctrl = [n.strip() for n in (target_name or "").split(",") if n.strip()]
    _cap_ctrl = 1
    if ctrl_effect is not None and not ctrl_effect["pool"] and len(_nomes_ctrl) > 1:
        _cap_ctrl = _resolucao.alvos_no_circulo(hab, _circulo)
        if _cap_ctrl > 1:
            for _n_c in _nomes_ctrl:
                _ch_c = memory.campaign["characters"].get(memory.char_key(_n_c))
                if (_ch_c and _ch_c.get("sheet") and _ch_c not in _alvos_ctrl
                        and (_ch_c.get("status") or "").lower() not in OUT_OF_COMBAT_STATUSES):
                    _alvos_ctrl.append(_ch_c)
            _alvos_ctrl = _alvos_ctrl[:_cap_ctrl] if len(_alvos_ctrl) > 1 else []

    # ══════════════════════════════════════════════════════════════════════════
    # POOL SPELLS (Sleep, Color Spray, …)
    # Mechanic D&D 5e: rola dado → pool de HP.
    # Ordena alvos por HP crescente; vai "gastando" o pool do menor para o maior.
    # Nenhum dano é aplicado — criaturas apenas adormecem/ficam cegas.
    # target_name: nomes separados por vírgula OU vazio (auto-detecta inimigos).
    # ══════════════════════════════════════════════════════════════════════════
    if ctrl_effect is not None and ctrl_effect["pool"]:
        pool = total_dano
        cond = ctrl_effect["condition"]
        caster_key = memory.char_key(char_name)

        # Pool spells (Sleep, Color Spray) são SEMPRE área: ignoram o
        # target_name passado pela UI e afetam TODOS os inimigos vivos da
        # ordem de iniciativa, ordenados por HP crescente. O target_name
        # serve apenas como hint visual no log.
        cs = memory.campaign.get("combat_state", {})
        raw_names = [
            k for k in cs.get("initiative_order", [])
            if memory.char_key(k) != caster_key
            and not memory.campaign["characters"]
                       .get(memory.char_key(k), {}).get("party_member")
        ]
        # Se ainda assim a UI passou nomes explícitos (uso narrado pela LLM),
        # mescla — preserva intenção sem perder a natureza de área.
        if target_name:
            for t in target_name.split(","):
                t = t.strip()
                if t and t not in raw_names:
                    raw_names.append(t)

        # Resolve personagens válidos (vivos, com sheet)
        candidates: list[dict] = []
        for raw in raw_names:
            key   = memory.char_key(raw)
            tchar = memory.campaign["characters"].get(key) \
                    or memory.campaign["characters"].get(raw)
            if (tchar and tchar.get("sheet")
                    and not _tracos.recusa_de_tipo(hab, tchar)
                    and memory.char_key(tchar.get("name", "")) != caster_key
                    and (tchar.get("status") or "").lower()
                        not in ("morto", "inconsciente", "fugiu", "dormindo")):
                candidates.append(tchar)

        # Ordena por HP atual crescente (mais fraco dorme primeiro)
        candidates.sort(key=lambda c: c["sheet"]["vida_atual"])

        remaining = pool
        for tchar in candidates:
            if remaining <= 0:
                break
            hp = tchar["sheet"]["vida_atual"]
            if hp <= remaining:
                remaining -= hp
                tconds = tchar["sheet"].setdefault("condicoes", [])
                if not any(c["nome"].lower() == cond.lower() for c in tconds):
                    tconds.append({"nome": cond.capitalize(), "duracao": None})
                # Sleep → status "dormindo": a criatura fica incapacitada
                # (pula a vez), mas continua VIVA — o combate NÃO acaba só
                # por isso. Color Spray apenas cega (a criatura ainda age),
                # então não mexe no status.
                if cond.lower() in ("dormindo", "inconsciente"):
                    tchar["status"] = "dormindo"
                slept.append(f"{tchar['name']} ({hp} HP)")

        # Monta linha de resultado do pool
        result += f"\n   Pool: **{pool} HP**"
        if slept:
            result += f"\n   Dormindo: {', '.join(slept)}"
            result += f"\n   Pool usado: {pool - remaining} HP | Restante: {remaining} HP"
        else:
            result += "\n   Nenhum alvo foi afetado — todos têm HP alto demais."

    # ══════════════════════════════════════════════════════════════════════════
    # PROJÉTEIS (Mísseis Mágicos, Raio Ardente)
    # Cada dardo é um dado e um alvo. A tela manda os nomes por vírgula; um
    # nome repetido recebe mais de um dardo, e nomes a menos que dardos
    # repartem em rodízio. O dardo nunca erra; o raio rola acerto, um a um.
    # ══════════════════════════════════════════════════════════════════════════
    elif _n_proj:
        _cfg_p = _resolucao.PROJETEIS[(_resolucao._magia_srd(hab) or {}).get("nome_srd", "")]
        _nomes_p = [n.strip() for n in target_name.split(",") if n.strip()]
        _alvos_p = []
        for _n_p in _nomes_p:
            _ch_p = memory.campaign["characters"].get(memory.char_key(_n_p))
            if _ch_p and _ch_p.get("sheet"):
                _alvos_p.append(_ch_p)
        _tipo_p = (_norm_damage_type(hab.get("tipo_dano", "") or "")
                   or _norm_damage_type((_resolucao._magia_srd(hab) or {}).get("tipo_dano", "") or "")
                   or _damage_type_from_text(hab.get("descricao", "")))
        _nd_p, _faces_p, _bonus_p = _parse_dice(_formula_proj)
        result += f"\n   {_n_proj} {_cfg_p['rotulo']}s de {_formula_proj}"
        rolls = []
        for _i_p in range(_n_proj if _alvos_p else 0):
            _a_p = _alvos_p[_i_p % len(_alvos_p)]
            _st_p = _a_p["sheet"]
            _rot = f"{_cfg_p['rotulo'].capitalize()} {_i_p + 1} → {_a_p['name']}"
            if int(_st_p.get("vida_atual", 0) or 0) <= 0:
                result += f"\n   {_rot}: já está caído."
                continue
            _dobra = 1
            if _cfg_p["ataque"]:
                _ok_p, _crit_p, _linha_p = _rolar_ataque_magico(char, _a_p, hab)
                result += f"\n   {_rot}:" + _linha_p.replace("\n   ", " ", 1)
                if not _ok_p:
                    continue
                _dobra = 2 if _crit_p else 1
            elif any(_norm_txt(e.get("nome", "")) == "escudo arcano" for e in _efeitos(_st_p)):
                result += f"\n   {_rot}: o Escudo Arcano de {_a_p['name']} absorve o dardo."
                continue
            _r_p = [random.randint(1, _faces_p) for _ in range(_nd_p * _dobra)]
            rolls += _r_p
            _dano_p = max(0, sum(_r_p) + _bonus_p)
            total_dano += _dano_p
            _res_p = _apply_damage(_a_p, _dano_p, _tipo_p, source_name=char["name"], arma_magica=True)
            result += (f"\n   {_rot}: [{' + '.join(map(str, _r_p))}]"
                       + (f" + {_bonus_p}" if _bonus_p else "") + f" = {_dano_p}"
                       + _fmt_notas(_res_p["notas"]).replace("\n", " ")
                       + f" ({_res_p['hp_antes']} → {_st_p['vida_atual']}/{_st_p['vida_max']})")
            if _st_p["vida_atual"] == 0 and _res_p["hp_antes"] > 0:
                result += _mark_at_zero_hp(_a_p, char["name"])
        if not _alvos_p:
            result += f"\n   Nenhum alvo válido em '{target_name}'."

    # ══════════════════════════════════════════════════════════════════════════
    # CONDIÇÃO EM VÁRIOS ALVOS (Imobilizar Pessoa no 3º círculo ou acima)
    # A salvaguarda de cada alvo é rolada aqui, inclusive a de personagem do
    # jogador — como na área, uma bandeja por alvo travaria o turno.
    # ══════════════════════════════════════════════════════════════════════════
    elif _alvos_ctrl:
        _cond_m = ctrl_effect["condition"]
        _save_m = salvaguarda_da_habilidade(hab)
        _conj_m = _conjuracao(s) or {}
        _cd_m = int(saving_throw_dc or _conj_m.get("cd") or (8 + int(s.get("proficiencia", 2) or 2)))
        result += (f"\n   {len(_alvos_ctrl)} alvos"
                   + (f" (no máximo {_cap_ctrl} neste círculo)" if len(_nomes_ctrl) > _cap_ctrl else ""))
        for _a_m in _alvos_ctrl:
            _globo_m = _protegido_pelo_globo(char["name"], _a_m.get("name", ""),
                                             _circulo or int((_resolucao._magia_srd(hab) or {}).get("nivel", 0) or 0))
            if _globo_m:
                result += f"\n   {_a_m['name']}: dentro do {_globo_m} — a magia não o alcança."
                continue
            if _imune_a_condicao(_a_m, _cond_m):
                result += f"\n   {_a_m['name']} é imune a {_cond_m.capitalize()}."
                continue
            if _save_m:
                _passou_m, _linha_m = _rolar_salvaguarda(
                    _a_m, _save_m, _cd_m, desvantagem=_desv_primeira or _sub.coroa_contra(_a_m, hab),
                    contra=_cond_m)
                _desv_primeira = False
                if _passou_m:
                    result += f"\n   {_a_m['name']}: {_linha_m} — resistiu, {_cond_m} não pega."
                    continue
                result += f"\n   {_a_m['name']}: {_linha_m}"
            _conds_m = _a_m["sheet"].setdefault("condicoes", [])
            if not any((c.get("nome", "") if isinstance(c, dict) else str(c)).lower() == _cond_m.lower()
                       for c in _conds_m):
                _conds_m.append(_condicao_de_magia(char, hab, _cond_m, s))
            result += f"\n   {_a_m['name']}: {_cond_m.upper()}! (sem dano)"

    # ══════════════════════════════════════════════════════════════════════════
    # DANO EM ÁREA (Bola de Fogo, Mãos Flamejantes, Sopro do Dragão…)
    # Um dado só para a área inteira, como manda o SRD, e uma salvaguarda por
    # criatura. Quem passa leva metade.
    #
    # Aqui o motor rola a salvaguarda de TODO MUNDO, inclusive dos
    # personagens do jogador — diferente do alvo único, em que a bandeja de
    # dados abre e quem rola é ele. Uma bandeja por criatura pegaria o combate
    # inteiro numa fila de pausas; o dado de cada um aparece escrito no
    # resultado, que é o que a pausa existia para mostrar.
    # ══════════════════════════════════════════════════════════════════════════
    elif _alvos_area:
        _save_area = salvaguarda_da_habilidade(hab)
        _conj = _conjuracao(s) or {}
        _cd_area = int(saving_throw_dc
                       or hab.get("cd")
                       or _conj.get("cd")
                       or (8 + int(s.get("proficiencia", 2) or 2)))
        _tipo_area = (_norm_damage_type(hab.get("tipo_dano", "") or "")
                      or _damage_type_from_text(hab.get("descricao", "")))
        result += (f"\n   Área: {area_da_habilidade(hab)} "
                   + (f"em **{_zona_area}** " if _zona_area
                      else f"(sem zonas: até {max_alvos_da_area(hab)} criaturas escolhidas) ")
                   + f"— {len(_alvos_area)} "
                   f"{'criatura' if len(_alvos_area) == 1 else 'criaturas'}")
        for _alvo in _alvos_area:
            _dano_nele = total_dano
            _linha_save = ""
            _passou = True
            _globo_a = _protegido_pelo_globo(char["name"], _alvo.get("name", ""),
                                             _circulo or int((_resolucao._magia_srd(hab) or {}).get("nivel", 0) or 0))
            if _globo_a:
                result += f"\n   {_alvo['name']}: dentro do {_globo_a} — a magia não o alcança."
                continue
            if _save_area and _cuidadosa and memory.luta_com_o_grupo(_alvo) == memory.luta_com_o_grupo(char):
                _passou, _linha_save = True, "Magia Cuidadosa: passa"
                _dano_nele = total_dano // 2 if _metade_se_passar(hab) else 0
                _linha_save = f" ({_linha_save} — {'metade' if _dano_nele else 'nada'})"
            elif _save_area:
                _passou, _linha_save = _rolar_salvaguarda(_alvo, _save_area, _cd_area,
                                                          desvantagem=_desv_primeira or _sub.coroa_contra(_alvo, hab))
                _desv_primeira = False
                if _passou:
                    _dano_nele = total_dano // 2
                _linha_save = (f" ({_linha_save} — "
                               f"{'metade' if _passou else 'dano cheio'})")
            _res = _apply_damage(_alvo, _dano_nele, _tipo_area,
                                 source_name=char["name"], arma_magica=True)
            _st_alvo = _alvo["sheet"]
            if _save_area and not _passou and hab.get("condicao_se_falhar") and _st_alvo["vida_atual"] > 0:
                result += "\n   " + _tracos._por_condicao(char, _alvo, hab["condicao_se_falhar"])
            result += _fmt_notas(_res["notas"])
            result += (f"\n   {_alvo['name']}: {_res['hp_antes']} → "
                       f"{_st_alvo['vida_atual']}/{_st_alvo['vida_max']}"
                       f" (-{_dano_nele}){_linha_save}")
            if _st_alvo["vida_atual"] == 0:
                result += _mark_at_zero_hp(_alvo, char["name"])

    # ══════════════════════════════════════════════════════════════════════════
    # EFEITOS DE ALVO ÚNICO (cura / condição direta / dano)
    # ══════════════════════════════════════════════════════════════════════════
    elif target_name:
        # Para condições diretas e dano, pega o primeiro nome (ignora vírgulas extras)
        primary_target = target_name.split(",")[0].strip()
        target = memory.campaign["characters"].get(memory.char_key(primary_target))
        if target and target.get("sheet"):
            st = target["sheet"]

            # ── MAGIA DE ATAQUE ROLA ACERTO ──────────────────────────────
            # Raio Guia, Raio de Fogo, Infligir Ferimentos: o SRD manda
            # rolar ataque mágico contra a CA. O motor aplicava o dano
            # direto — magia de ataque nunca errava.
            _tipo_atk = _ataque_da_magia(hab)
            if (_tipo_atk and _efeito == "dano"
                    and memory.char_key(target.get("name", "")) != memory.char_key(char["name"])):
                _acertou, _critico, _linha_atk = _rolar_ataque_magico(char, target, hab)
                result += _linha_atk
                if not _acertou:
                    _log_combat_event(
                        "ability", char["name"], target["name"],
                        msg=f"{char['name']} usou {hab['nome']} em {target['name']} • ERROU",
                        ability=hab["nome"])
                    memory.save_campaign()
                    if end_turn:
                        result += _auto_advance_turn(char_name)
                    memory.save_campaign()
                    return result
                if _critico and sides:
                    _extra = [random.randint(1, sides) for _ in range(n_dice)]
                    rolls = list(rolls) + _extra
                    total_dano += sum(_extra)
                    detail = " + ".join(str(r) for r in rolls)
                    result += f"\n   Crítico: dados dobrados [{' + '.join(map(str, _extra))}] → {total_dano}"

            # ── A MAGIA TEM TESTE E O MESTRE NÃO PEDIU ───────────────────
            # O SRD diz qual é o teste; quando o alvo é um NPC, o motor rola
            # e resolve na hora. Antes, mestre que esquecia a salvaguarda
            # fazia a Bola de Fogo causar dano cheio em todo mundo, sempre.
            # Contra personagem do JOGADOR continua sendo ele quem rola: a
            # pausa abaixo pede o dado, e a bandeja abre sozinha.
            _save_auto = salvaguarda_da_habilidade(hab)
            _falhou_cond = False
            if (_save_auto and not saving_throw_stat
                    and (_efeito == "dano" or ctrl_effect is not None)):
                _conj = _conjuracao(s) or {}
                # O poder do monstro diz a própria CD (Redemoinho: 13).
                _cd = int(hab.get("cd") or 0) or int(_conj.get("cd") or (8 + int(s.get("proficiencia", 2) or 2)))
                # O motor rola também a do personagem do grupo: o combate é na
                # tela tática, e ela mostra cada dado. (A pausa esperando o dado
                # do jogador ficava parada: a tela não tinha como resolvê-la.)
                _passou, _linha = _rolar_salvaguarda(
                    target, _save_auto, _cd,
                    desvantagem=_desv_primeira or _sub.coroa_contra(target, hab),
                    contra=(ctrl_effect or {}).get("condition", ""))
                _desv_primeira = False
                _falhou_cond = not _passou
                result += f"\n   {target['name']}: {_linha}"
                if ctrl_effect is not None:
                    if _passou:
                        result += f" — resistiu, {ctrl_effect['condition']} não pega."
                        memory.save_campaign()
                        return result + (_auto_advance_turn(char_name) if end_turn else "")
                else:
                    # Chama Sagrada, Zombaria Viciosa: quem passa não leva
                    # NADA. O motor dava metade a toda magia de teste.
                    _metade = _metade_se_passar(hab)
                    if _passou:
                        total_dano = total_dano // 2 if _metade else 0
                    result += ((f" — passou: metade do dano ({total_dano})" if _metade
                                else " — passou: nenhum dano")
                               if _passou else f" — falhou: dano cheio ({total_dano})")
                    if _passou and not _metade:
                        _log_combat_event(
                            "ability", char["name"], target["name"],
                            msg=(f"{char['name']} usou {hab['nome']} em {target['name']} "
                                 f"• {target['name']} passou na salvaguarda"),
                            ability=hab["nome"])
                        memory.save_campaign()
                        return result + (_auto_advance_turn(char_name) if end_turn else "")

            # ── MODO INTERATIVO: saving throw → PAUSA, não aplica efeito ──────
            if saving_throw_stat and saving_throw_dc > 0:
                # O que a falha traz fica guardado para resolve_saving_throw:
                # a condição (Imobilizar Pessoa, o Redemoinho que derruba) e se
                # quem passa leva metade ou nada.
                _registrar_salvaguarda_pendente(
                    target, saving_throw_stat, saving_throw_dc, char, hab,
                    dano=0 if ctrl_effect is not None else total_dano,
                    tipo=(_norm_damage_type(hab.get("tipo_dano", "") or "")
                          or _damage_type_from_text(hab.get("descricao", ""))),
                    metade=_metade_se_passar(hab),
                    condicao=(_condicao_de_magia(char, hab, ctrl_effect["condition"], s)
                              if ctrl_effect is not None else (hab.get("condicao_se_falhar") or "")))
                memory.save_campaign()
                if ctrl_effect is not None:
                    cond_nome = ctrl_effect["condition"]
                    efeito_falha   = f"{cond_nome.upper()} aplicado"
                    efeito_sucesso = "sem efeito"
                    return (
                        result +
                        f"\n\n**AGUARDANDO TESTE DE RESISTÊNCIA**\n"
                        f"   Alvo: {target['name']}\n"
                        f"   Atributo: {saving_throw_stat.capitalize()} | CD: {saving_throw_dc}\n"
                        f"   Efeito (falha): **{efeito_falha}** | Efeito (sucesso): **{efeito_sucesso}**\n"
                        f"\nMestre: Role {saving_throw_stat.capitalize()} CD {saving_throw_dc}!\n"
                        f"   Com o dado do jogador: resolve_saving_throw('{target['name']}', "
                        f"'{saving_throw_stat}', {saving_throw_dc}, <total>, 0) — o motor aplica {cond_nome} "
                        f"se falhar."
                    )
                else:
                    return (
                        result +
                        f"\n\n**AGUARDANDO TESTE DE RESISTÊNCIA**\n"
                        f"   Alvo: {target['name']}\n"
                        f"   Atributo: {saving_throw_stat.capitalize()} | CD: {saving_throw_dc}\n"
                        f"   Dano (falha): **{total_dano}** | Sucesso: "
                        f"**{total_dano // 2 if _metade_se_passar(hab) else 0}**\n"
                        f"\nMestre: Role {saving_throw_stat.capitalize()} CD {saving_throw_dc}!\n"
                        f"   Com o dado do jogador: resolve_saving_throw('{target['name']}', "
                        f"'{saving_throw_stat}', {saving_throw_dc}, <total>, {total_dano}) — o motor aplica o "
                        f"dano certo" + (f" e {hab['condicao_se_falhar']} se falhar"
                                         if hab.get("condicao_se_falhar") else "") + "."
                    )

            # ── MODO AUTOMÁTICO: aplica efeito imediatamente ─────────────────
            hp_antes = st["vida_atual"]

            # Dado que não é dano nem cura (o 1d4 da Bênção, o da Orientação)
            # é rolado e mostrado, e a vida de ninguém muda. Habilidade sem
            # dado nenhum também não encosta em vida.
            # "condicao" sem efeito de controle conhecido (Perdição, Confusão:
            # o efeito é narrado, não é uma condição do SRD) também não mexe
            # na vida. Sem isto ela caía no ramo de dano, com dado vazio.
            if _efeito in ("bonus", "nenhum", "condicao") and ctrl_effect is None:
                result += f"\n   {target['name']}: sem mudança na vida."

            # O compêndio também decide: Curar Ferimentos com a descrição vazia
            # na ficha caía no ramo de dano e FERIA o aliado.
            elif _efeito == "cura" or _is_healing_ability(hab):
                if sides and any(e.get("cura_maxima") for e in _efeitos(st)):
                    total_dano = n_dice * sides + bonus
                    result += f"\n   Sinal de Esperança: a cura rola o máximo ({total_dano})."
                st["vida_atual"] = min(_hp_max_efetivo(st), st["vida_atual"] + total_dano)
                result += f"\n   {target['name']}: {hp_antes} → {st['vida_atual']}/{st['vida_max']}"
                if hp_antes == 0:
                    target["status"] = "vivo"
                    st["death_saves_sucessos"] = 0
                    st["death_saves_falhas"]   = 0
                    result += " Estabilizado!"
                elif st["vida_atual"] == st["vida_max"]:
                    result += " Vida plena!"

            elif ctrl_effect is not None:
                # Condição direta (Hold Person, Charm, Web, etc.) — sem dano
                cond  = ctrl_effect["condition"]
                conds = st.setdefault("condicoes", [])
                if _imune_a_condicao(target, cond):
                    result += f"\n   {target['name']} é imune a {cond.capitalize()}."
                    memory.save_campaign()
                    return result + (_auto_advance_turn(char_name) if end_turn else "")
                if not any(c["nome"].lower() == cond.lower() for c in conds):
                    conds.append(_condicao_de_magia(char, hab, cond, s))
                result += f"\n   {target['name']}: {cond.upper()}! (sem dano)"
                _como_acaba = _como_a_condicao_acaba(conds[-1])
                if _como_acaba:
                    result += f"\n   {_como_acaba}"

            else:
                # Dano direto — passa pelo pipeline de tipo/resistência.
                _tipo_hab = (_norm_damage_type(hab.get("tipo_dano", "") or "")
                             or _damage_type_from_text(hab.get("descricao", "")))
                _res = _apply_damage(target, total_dano, _tipo_hab,
                                     source_name=char["name"], arma_magica=True)
                hp_antes = _res["hp_antes"]
                result += _fmt_notas(_res["notas"])
                result += f"\n   {target['name']}: {hp_antes} → {st['vida_atual']}/{st['vida_max']}"
                # O poder que derruba ou agarra quem falhou (Redemoinho, Engolfar).
                if _falhou_cond and hab.get("condicao_se_falhar") and st["vida_atual"] > 0:
                    result += "\n   " + _tracos._por_condicao(char, target, hab["condicao_se_falhar"])
                if st["vida_atual"] == 0:
                    result += _mark_at_zero_hp(target, char["name"])
                else:
                    # O que a magia deixa no alvo: o Raio Guia marca (o
                    # próximo ataque tem vantagem), a Zombaria Viciosa abala.
                    from rpg import resolucao as _resolucao_r
                    result += _resolucao_r.aplicar_rider(char, hab, target)

    # ── Linha do log da habilidade ────────────────────────────────────────
    # Para pool spells (Sleep, Color Spray) o dado representa um POOL de HP,
    # NÃO dano. Mostra explicitamente quem foi afetado para não parecer dano.
    _abil_dice = ""
    if _n_proj:
        _abil_dice = f" • {_n_proj} {_cfg_p['rotulo']}s = {total_dano}"
    elif hab.get("dado"):
        _abil_dice = (f" • {n_dice}d{sides}: [{detail}]{bonus_str} "
                      f"= {total_dano}")
    if ctrl_effect is not None and ctrl_effect.get("pool"):
        if hab.get("dado"):
            _abil_dice = (f" • {n_dice}d{sides} (pool): [{detail}]{bonus_str} "
                          f"= {total_dano} HP")
        if slept:
            _abil_dice += f" • afetados: {', '.join(slept)}"
        else:
            _abil_dice += " • ninguém foi afetado (HP alto demais)"

    _log_combat_event(
        "ability", char["name"], target_name,
        msg=(f"{char['name']} usou {hab['nome']}"
             + (f" em {target_name}" if target_name and not (ctrl_effect and ctrl_effect.get('pool')) else "")
             + _abil_dice),
        ability=hab["nome"], dado=hab.get("dado", ""),
        rolls=list(rolls), total=total_dano,
    )
    memory.save_campaign()
    if end_turn:
        result += _auto_advance_turn(char_name)
    else:
        result += "\n   Ação bônus disponível — próxima habilidade/ataque neste turno."
    memory.save_campaign()
    return result


# ---------------------------------------------------------------------------
# 7. Equipamentos e CA Dinâmica  (NOVO)
# ---------------------------------------------------------------------------

# Ordem dos slots em toda a interface. Os cinco primeiros são os de sempre; os
# outros recebem os itens mágicos de vestir (anel, manto, botas...), para que
# dois mantos não deem +2 de CA. A Mochila só mostra os novos quando ocupados.
_SLOTS = ("armadura", "escudo", "arma_principal", "arma_secundaria", "amuleto",
          "anel_1", "anel_2", "capa", "botas", "luvas", "cabeca", "cinto")
_SLOTS_BASICOS = _SLOTS[:5]
_PALAVRAS_DE_AMULETO = ("amuleto", "colar", "pingente", "talisma", "medalhao", "periapto",
                        "escaravelho", "broche")
# O slot do compêndio ("anel") → os slots da ficha.
_SLOTS_DO_MAGICO = {"anel": ["anel_1", "anel_2"], "capa": ["capa"], "botas": ["botas"],
                    "luvas": ["luvas"], "cabeca": ["cabeca"], "cinto": ["cinto"],
                    "amuleto": ["amuleto"]}
# Item fora do SRD: a primeira palavra diz onde ele vai ("Anel de Vhar").
_PRIMEIRA_PALAVRA_DO_SLOT = {
    "anel": "anel", "manto": "capa", "capa": "capa", "tunica": "capa", "robe": "capa",
    "botas": "botas", "sapatilhas": "botas", "luvas": "luvas", "manoplas": "luvas",
    "bracadeiras": "luvas", "elmo": "cabeca", "capacete": "cabeca", "chapeu": "cabeca",
    "diadema": "cabeca", "tiara": "cabeca", "faixa": "cabeca", "oculos": "cabeca",
    "cinto": "cinto",
}


def _slots_para_item(nome: str) -> list[str]:
    """
    Onde um item pode ser equipado, pelo que o motor SABE dele.

    Antes, equip_item sem slot mandava para "armadura" tudo o que não
    reconhecia: uma Corda de Cânhamo equipada tirava a cota de malha do corpo
    e deixava a CA em 10 + DES. Item que o motor não reconhece não tem slot;
    quem sabe o que ele é informa o slot.
    """
    armadura = _armadura_na_tabela(nome)
    if armadura:
        return [armadura["slot"]]
    magico = _itens.magico(nome)
    if magico and magico.get("slot") in _SLOTS_DO_MAGICO:
        return list(_SLOTS_DO_MAGICO[magico["slot"]])
    base = _norm_txt(nome)
    if _itens.arma(nome) or any(_norm_txt(k) in base for k in _WEAPON_KEYWORDS):
        return ["arma_principal", "arma_secundaria"]
    if any(k in base for k in _PALAVRAS_DE_AMULETO):
        return ["amuleto"]
    primeira = base.split(" ")[0] if base else ""
    if primeira in _PRIMEIRA_PALAVRA_DO_SLOT:
        return list(_SLOTS_DO_MAGICO[_PRIMEIRA_PALAVRA_DO_SLOT[primeira]])
    return []


def _conflito_de_maos(equip: dict, slot: str, nome: str) -> str:
    """
    Duas mãos, não três: arma de duas mãos não divide a mão com escudo nem
    com outra arma, e duas armas não cabem com um escudo. Devolve a recusa,
    ou "" quando cabe. A versátil conta uma mão (a outra é a escolha de
    empunhá-la com as duas, que o ataque decide).
    """
    if slot not in ("arma_principal", "arma_secundaria", "escudo"):
        return ""
    novo = dict(equip)
    novo[slot] = nome
    nas_maos, maos = [], 0
    for s in ("arma_principal", "arma_secundaria", "escudo"):
        if novo.get(s):
            duas = s != "escudo" and _arma_de_duas_maos(novo[s])
            maos += 2 if duas else 1
            nas_maos.append(f"{novo[s]}" + (" (duas mãos)" if duas else ""))
    if maos <= 2:
        return ""
    return (f"Erro: não cabe nas mãos: {', '.join(nas_maos)}. Tire algo primeiro "
            f"(arma de duas mãos não divide a mão com escudo nem com outra arma).")


def _slots_ocupados_por(equip: dict, nome: str, exceto: str = "") -> list[str]:
    alvo = _norm_txt(nome)
    return [s for s, v in equip.items() if s != exceto and v and _norm_txt(v) == alvo]


def equip_item(char_name: str, item_name: str, slot: str = "") -> str:
    """
    Equipa um item de um personagem, recalculando a CA automaticamente.
    O item deve estar no inventário do personagem.

    Slots: armadura, escudo, arma_principal, arma_secundaria, amuleto,
    anel_1, anel_2, capa, botas, luvas, cabeca, cinto.
    Sem slot, a ferramenta usa o que sabe do item (armadura e escudo pela
    tabela, arma pelo nome, item mágico pelo SRD: o anel vai num dedo livre);
    item que ela não reconhece exige o slot. Arma de duas mãos não divide a
    mão com escudo nem com outra arma.

    Item mágico que exige sintonização só faz efeito depois de attune_item.

    Armaduras pesadas ignoram o modificador de Destreza na CA.
    Armaduras médias limitam o bônus de Destreza a +2.
    Armaduras leves somam o modificador completo de Destreza.
    Escudo sempre acrescenta +2 à CA independentemente da armadura.

    Args:
        char_name: Nome do personagem.
        item_name: Nome exato do item no inventário.
        slot:      Slot de equipamento. Pode ficar vazio se o item for óbvio.
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    inv  = char.get("inventario", [])
    item = next((i for i in inv if isinstance(i, dict)
                 and _norm_txt(i.get("nome", "")) == _norm_txt(item_name)), None)
    if not item:
        return (f"Erro: '{item_name}' não está no inventário de {char['name']}. "
                f"Adicione com add_item primeiro.")

    s     = char["sheet"]
    equip = s.setdefault("equipamentos", {})
    for nome_slot in _SLOTS:
        equip.setdefault(nome_slot, None)

    possiveis   = _slots_para_item(item["nome"])
    armor_entry = _armadura_na_tabela(item["nome"])
    slot = (slot or "").strip().lower()
    if not slot:
        if not possiveis:
            return (f"Erro: Não sei onde equipar '{item['nome']}'. Informe o slot: "
                    f"{', '.join(_SLOTS)}.")
        # Arma: a mão principal, ou a secundária se a principal já tem outra.
        # Anel: o primeiro dedo livre.
        slot = possiveis[0]
        if slot == "arma_principal" and equip.get("arma_principal") \
                and not equip.get("arma_secundaria"):
            slot = "arma_secundaria"
        if slot == "anel_1" and equip.get("anel_1") and not equip.get("anel_2"):
            slot = "anel_2"
    if slot not in _SLOTS:
        return f"Erro: Slot '{slot}' inválido. Use: {', '.join(_SLOTS)}."

    # Armadura e escudo mexem na CA: só entra o que o motor sabe o que é. Com
    # slot explícito isto era livre, e "Bugiganga do Vhar" ia para o corpo.
    if slot in ("armadura", "escudo"):
        dados = armor_entry
        if not dados or dados.get("slot", "armadura") != slot:
            return (f"Erro: '{item['nome']}' não é {'armadura' if slot == 'armadura' else 'escudo'} "
                    f"que o motor conheça — a CA não teria de onde vir.")
    elif armor_entry:
        return f"Erro: '{item['nome']}' é {armor_entry['slot']}, não vai no slot [{slot}]."

    if equip.get(slot) and _norm_txt(equip[slot]) == _norm_txt(item["nome"]):
        return f"Nota: {char['name']} já está com '{item['nome']}' em [{slot}]."

    maos = _conflito_de_maos(equip, slot, item["nome"])
    if maos:
        return maos

    # Uma unidade não ocupa dois slots: com 1 adaga no inventário, pô-la nas
    # duas mãos dava dois ataques com uma arma só.
    em_uso = len(_slots_ocupados_por(equip, item["nome"], exceto=slot))
    if em_uso >= int(item.get("qtd", 1) or 1):
        return (f"Erro: {char['name']} tem {item.get('qtd', 1)}x '{item['nome']}' e já "
                f"está usando {'todas' if em_uso > 1 else 'essa'} em outro slot.")

    ca_antes     = s["ca"]
    old_item     = equip.get(slot)
    equip[slot]  = item["nome"]

    _recalculate_ca(char)
    ca_depois = s["ca"]

    memory.save_campaign()
    swap_msg = f"(substituiu {old_item})" if old_item else ""
    return (
        f"{char['name']} equipou '{item['nome']}' no slot [{slot}]. {swap_msg}\n"
        f"   CA: {ca_antes} → {ca_depois}"
        + (f"\n   (Armadura {'pesada — DES ignorada' if armor_entry and armor_entry.get('dex_bonus') == 'none' else 'média — DES limitada a +2' if armor_entry and armor_entry.get('dex_bonus') == 'cap2' else 'leve — DES completa' if armor_entry else ''})"
           if armor_entry and slot == "armadura" else "")
    )


def unequip_item(char_name: str, slot: str) -> str:
    """
    Remove o item equipado de um slot, recalculando a CA.

    Args:
        char_name: Nome do personagem.
        slot:      Slot a desocupar: armadura, escudo, arma_principal,
                   arma_secundaria, amuleto, anel_1, anel_2, capa, botas,
                   luvas, cabeca, cinto.
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    s     = char["sheet"]
    equip = s.setdefault("equipamentos", {})
    slot  = (slot or "").strip().lower()

    if slot not in _SLOTS:
        return f"Erro: Slot '{slot}' inválido. Use: {', '.join(_SLOTS)}."

    item_removido = equip.get(slot)
    if not item_removido:
        return f"Nota: {char['name']} não tem nada equipado no slot [{slot}]."

    ca_antes   = s["ca"]
    equip[slot] = None
    _recalculate_ca(char)
    ca_depois  = s["ca"]

    memory.save_campaign()
    return (
        f"{char['name']} desequipou '{item_removido}' do slot [{slot}].\n"
        f"   CA: {ca_antes} → {ca_depois}"
    )


# ── Sintonização ──────────────────────────────────────────────────────────
# O item mágico que pede sintonização não faz nada até o personagem passar um
# descanso curto com ele (no 5e, no máximo três de cada vez). Antes o motor
# lia "requer sintonização" do SRD e não fazia nada com isso.
_LIMITE_DE_SINTONIA = 3

# "requires attunement by a cleric" → quem pode.
_SINTONIA_POR_CLASSE = (("cleric", "clérigo"), ("druid", "druida"), ("wizard", "mago"),
                        ("sorcerer", "feiticeiro"), ("warlock", "bruxo"), ("bard", "bardo"),
                        ("paladin", "paladino"), ("ranger", "patrulheiro"))


def _esta_sintonizado(sheet: dict, nome: str) -> bool:
    alvo = _norm_txt(nome or "")
    return bool(alvo) and any(_norm_txt(n) == alvo for n in (sheet or {}).get("sintonizados") or []
                              if isinstance(n, str))


def _quem_pode_sintonizar(char: dict, magico: dict) -> str:
    """Recusa (texto) quando o item pede uma classe ou raça que o personagem não tem."""
    detalhe = (magico.get("sintonizacao_detalhe") or "").lower()
    if not detalhe:
        return ""
    s = char.get("sheet") or {}
    classe = _norm_txt(s.get("classe", ""))
    aceitas = [pt for en, pt in _SINTONIA_POR_CLASSE if en in detalhe]
    if "spellcaster" in detalhe:
        if not _atributo_de_conjuracao(s):
            return "só um conjurador pode se sintonizar com ele"
        return ""
    if aceitas and classe not in {_norm_txt(c) for c in aceitas}:
        return f"só se sintoniza com {', '.join(aceitas)}"
    if "dwarf" in detalhe and "anao" not in _norm_txt(s.get("raca", "")):
        return "só um anão se sintoniza com ele"
    return ""


def attune_item(char_name: str, item_name: str) -> str:
    """
    Sintoniza o personagem com um item mágico que exige sintonização: só
    então o item faz efeito. No 5e leva um descanso curto (uma hora) com o
    item, e ninguém fica sintonizado com mais de três ao mesmo tempo.
    Sintonizar também revela o que o item é.

    Args:
        char_name: Quem se sintoniza.
        item_name: O item (precisa estar no inventário).
    """
    char, err = _get_char(char_name)
    if not char:
        return err
    if _em_combate():
        return "Aviso: sintonizar leva um descanso curto; não dá no meio da luta."
    item = _item_do_inventario(char, item_name)
    if not item:
        return f"Erro: '{item_name}' não está no inventário de {char['name']}."
    magico = _item_magico_do_srd(item["nome"])
    if not magico:
        return (f"Nota: '{item['nome']}' não é item mágico do SRD; se ele pede "
                f"sintonização, diga isso na descrição e narre.")
    if not magico.get("sintonizacao"):
        return f"Nota: {magico['nome']} não precisa de sintonização: já funciona."
    s = char["sheet"]
    if _esta_sintonizado(s, item["nome"]):
        return f"Nota: {char['name']} já está sintonizado com {item['nome']}."
    recusa = _quem_pode_sintonizar(char, magico)
    if recusa:
        return f"Erro: {magico['nome']}: {recusa}."
    atuais = [n for n in s.get("sintonizados") or [] if isinstance(n, str)]
    if len(atuais) >= _LIMITE_DE_SINTONIA:
        return (f"Erro: {char['name']} já está sintonizado com {_LIMITE_DE_SINTONIA} itens "
                f"({', '.join(atuais)}). Desfaça uma sintonia antes (end_attunement).")
    s["sintonizados"] = atuais + [item["nome"]]
    item["identificado"] = True
    item["custom"] = False
    item["nome_srd"] = magico["nome_srd"]
    item["srd"] = _dados_srd_do_item(magico)
    _recalculate_ca(char)
    memory.save_campaign()
    nota = (magico.get("efeito") or {}).get("nota", "")
    vestir = ""
    if magico.get("slot") in _SLOTS_DO_MAGICO and not _slots_ocupados_por(s.get("equipamentos") or {}, item["nome"]):
        vestir = " Vista o item (equip_item) para ele fazer efeito."
    return (f"{char['name']} se sintonizou com {item['nome']} ({len(atuais) + 1}/{_LIMITE_DE_SINTONIA})."
            + (f" Efeito: {nota}" if nota else "") + vestir)


def end_attunement(char_name: str, item_name: str) -> str:
    """
    Desfaz a sintonia do personagem com um item (libera uma das três vagas).

    Args:
        char_name: Quem desfaz.
        item_name: O item.
    """
    char, err = _get_char(char_name, allow_dead=True)
    if not char:
        return err
    s = char["sheet"]
    if not _esta_sintonizado(s, item_name):
        return f"Nota: {char['name']} não está sintonizado com '{item_name}'."
    s["sintonizados"] = [n for n in s.get("sintonizados") or []
                         if _norm_txt(n) != _norm_txt(item_name)]
    _recalculate_ca(char)
    memory.save_campaign()
    return f"{char['name']} desfez a sintonia com {item_name}."


@functools.lru_cache(maxsize=512)
def _magico_por_nome(nome: str) -> dict | None:
    """O item mágico do compêndio com este nome — só leitura, em cache."""
    return _itens.magico(nome)


def _itens_ativos(sheet: dict) -> list[tuple[str, dict]]:
    """
    (nome, item mágico) dos itens cujo efeito vale agora: vestido no slot
    dele, ou carregado quando é de carregar (Pedra da Sorte), e sintonizado
    quando o SRD exige. Um item de cada tipo: dois Anéis de Proteção não
    somam +2.
    """
    equip = (sheet or {}).get("equipamentos") or {}
    vestidos = {_norm_txt(v) for v in equip.values() if isinstance(v, str) and v}
    nomes = [v for v in equip.values() if isinstance(v, str) and v]
    nomes += [n for n in (sheet or {}).get("sintonizados") or [] if isinstance(n, str)]
    ativos, vistos = [], set()
    for nome in nomes:
        magico = _magico_por_nome(nome)
        if not magico or magico["chave"] in vistos:
            continue
        if magico.get("sintonizacao") and not _esta_sintonizado(sheet, nome):
            continue
        if _norm_txt(nome) not in vestidos and magico.get("slot") != "carregado":
            continue
        vistos.add(magico["chave"])
        ativos.append((nome, magico))
    return ativos


_CAMPOS_DE_EFEITO_DE_ITEM = ("save_fixo", "teste_dado", "vantagem_pericias", "resistencias",
                             "imunidades", "visao_no_escuro", "deslocamento_min", "dano_arco",
                             "critico_vira_normal", "resistencia_a_magia", "proficiencia_armas")


def _efeitos_dos_itens(sheet: dict) -> list[dict]:
    """
    Os itens vestidos viram efeitos no mesmo formato dos de combate (Bênção,
    Pele de Árvore), e por isso valem nos mesmos lugares: a salvaguarda, o
    teste, a resistência. Não ficam gravados na ficha: tirar o anel tira o
    efeito.
    """
    saida = []
    for nome, magico in _itens_ativos(sheet):
        ef = magico.get("efeito") or {}
        d = {"nome": nome, "origem": nome, "de_item": True}
        for campo in _CAMPOS_DE_EFEITO_DE_ITEM:
            if ef.get(campo):
                d[campo] = ef[campo]
        if ef.get("resistencia_do_nome"):
            tipo = _damage_type_from_text(nome)
            if tipo:
                d["resistencias"] = list(d.get("resistencias") or []) + [tipo]
        if len(d) > 3:
            saida.append(d)
    return saida


def _aplicar_atributos_dos_itens(char: dict) -> None:
    """
    Manoplas de Força de Ogro (FOR 19), Amuleto da Saúde (CON 19), Cinto de
    Força de Gigante: o atributo vira o do item enquanto ele vale, se for
    maior. O valor de antes fica guardado e volta quando o item sai; se
    alguém mudar o atributo por fora (aumento de nível), o novo vira a base.
    A Constituição mexe na vida máxima, como no 5e.
    """
    s = char.get("sheet") or {}
    alvo: dict[str, int] = {}
    for _nome, magico in _itens_ativos(s):
        for attr, v in ((magico.get("efeito") or {}).get("atributo") or {}).items():
            alvo[attr] = max(alvo.get(attr, 0), int(v))
    # Poção de Força do Gigante: o mesmo, enquanto o efeito dura.
    for e in s.get("efeitos") or []:
        if isinstance(e, dict) and e.get("atributo") and e in _efeitos(s):
            for attr, v in e["atributo"].items():
                alvo[attr] = max(alvo.get(attr, 0), int(v))
    registro = s.get("_atributos_dos_itens") or {}
    novo = {}
    for attr in sorted(STAT_NAMES):
        atual = int(s.get(attr, 10) or 10)
        r = registro.get(attr)
        base = int(r["base"]) if r and int(r.get("aplicado", -1)) == atual else atual
        valor = max(base, alvo[attr]) if attr in alvo else base
        if valor != base:
            novo[attr] = {"base": base, "aplicado": valor}
        if valor != atual:
            s[attr] = valor
            if attr == "constituicao":
                delta = (_modifier(valor) - _modifier(atual)) * int(s.get("nivel", 1) or 1)
                s["vida_max"] = max(1, int(s.get("vida_max", 1) or 1) + delta)
                s["vida_atual"] = max(0, min(s["vida_max"],
                                             int(s.get("vida_atual", 0) or 0) + max(0, delta)))
    if novo:
        s["_atributos_dos_itens"] = novo
    else:
        s.pop("_atributos_dos_itens", None)


# ── Proficiência com armadura e arma ──────────────────────────────────────
# A ficha dizia "mago" e o mago vestia placas e brandia um machado grande com
# a proficiência inteira. No 5e, armadura sem proficiência dá desvantagem em
# tudo o que usa FOR e DES e impede de conjurar; arma sem proficiência não
# soma o bônus de proficiência no ataque. Vale para o grupo; NPC e monstro
# usam o stat block.
_ARMADURAS_DA_CLASSE = {
    "barbaro": {"leve", "media", "escudo"}, "bardo": {"leve"}, "bruxo": {"leve"},
    "clerigo": {"leve", "media", "escudo"}, "druida": {"leve", "media", "escudo"},
    "feiticeiro": set(), "guerreiro": {"leve", "media", "pesada", "escudo"},
    "ladino": {"leve"}, "mago": set(), "monge": set(),
    "paladino": {"leve", "media", "pesada", "escudo"},
    "patrulheiro": {"leve", "media", "escudo"}, "arcanista": {"leve", "media", "escudo"},
}
_SIMPLES_E_MARCIAIS = {"simples", "marcial"}
_ARMAS_DA_CLASSE = {
    "barbaro": _SIMPLES_E_MARCIAIS, "guerreiro": _SIMPLES_E_MARCIAIS,
    "paladino": _SIMPLES_E_MARCIAIS, "patrulheiro": _SIMPLES_E_MARCIAIS,
    "bardo": {"simples", "crossbow-hand", "longsword", "rapier", "shortsword"},
    "ladino": {"simples", "crossbow-hand", "longsword", "rapier", "shortsword"},
    "bruxo": {"simples"}, "clerigo": {"simples"}, "arcanista": {"simples"},
    "monge": {"simples", "shortsword"},
    "druida": {"club", "dagger", "dart", "javelin", "mace", "quarterstaff", "scimitar",
               "sickle", "sling", "spear"},
    "feiticeiro": {"dagger", "dart", "sling", "quarterstaff", "crossbow-light"},
    "mago": {"dagger", "dart", "sling", "quarterstaff", "crossbow-light"},
}
_ARMAS_DA_RACA = {"elfo": {"longsword", "shortsword", "shortbow", "longbow"},
                  "anao": {"battleaxe", "handaxe", "light-hammer", "warhammer"}}
_TIPO_DA_ARMADURA = {"full": "leve", "cap2": "media", "none": "pesada", "shield": "escudo"}


def _classe_com_tabela(char: dict) -> str:
    classe = _norm_txt(((char or {}).get("sheet") or {}).get("classe", ""))
    return classe if classe in _ARMADURAS_DA_CLASSE else ""


def _habilidade_que_diz(char: dict, trecho: str) -> bool:
    """Alguma habilidade da ficha fala disso (\"Treinamento em Armadura Pesada\")."""
    alvo = _norm_txt(trecho)
    return any(alvo in _norm_txt(f"{h.get('nome', '')} {h.get('descricao', '')}")
               for h in (char.get("habilidades") or []) if isinstance(h, dict))


def _proficiente_com_armadura(char: dict, nome: str) -> bool:
    if not memory.is_party_member(char) or not _classe_com_tabela(char):
        return True
    dados = _armadura_na_tabela(nome)
    if not dados or dados.get("proficiente"):
        return True                        # desconhecida, ou a Cota Élfica
    tipo = _TIPO_DA_ARMADURA.get(dados["dex_bonus"], "")
    if tipo in _ARMADURAS_DA_CLASSE[_classe_com_tabela(char)]:
        return True
    return tipo == "pesada" and _habilidade_que_diz(char, "armadura pesada")


def _armadura_sem_proficiencia(char: dict) -> str:
    """O nome da armadura ou do escudo vestido sem proficiência, ou ''."""
    equip = ((char or {}).get("sheet") or {}).get("equipamentos") or {}
    for slot in ("armadura", "escudo"):
        nome = equip.get(slot)
        if nome and not _proficiente_com_armadura(char, nome):
            return nome
    return ""


def _proficiente_com_arma(char: dict, arma: str) -> bool:
    if not memory.is_party_member(char) or not _classe_com_tabela(char):
        return True
    a = _itens.arma(arma)
    if not a:
        return True                        # arma fora do SRD: o mestre decide
    profs = _ARMAS_DA_CLASSE[_classe_com_tabela(char)]
    if a["grupo"] in profs or a["chave"] in profs:
        return True
    raca = _norm_txt(((char.get("sheet") or {}).get("raca") or ""))
    if any(r in raca for r, armas in _ARMAS_DA_RACA.items() if a["chave"] in armas):
        return True
    if a["grupo"] == "marcial" and _habilidade_que_diz(char, "armas marciais"):
        return True
    return any(a["nome_srd"].lower() in (e.get("proficiencia_armas") or [])
               or a["chave"] in (e.get("proficiencia_armas") or [])
               for e in _efeitos((char.get("sheet") or {})))


def _desvantagem_da_armadura(char: dict, atributo: str, pericia: str = "") -> str:
    """
    Por que a armadura impõe desvantagem neste teste, ou ''. Sem proficiência:
    tudo de FOR e DES. Armadura que pesa (placas, talas, cota de malha...):
    Furtividade, menos a de mithral.
    """
    equip = ((char or {}).get("sheet") or {}).get("equipamentos") or {}
    sem_prof = _armadura_sem_proficiencia(char)
    if sem_prof and _norm_txt(atributo) in ("forca", "destreza"):
        return f"{sem_prof} sem proficiência"
    if pericia and _norm_txt(pericia) == "furtividade" and equip.get("armadura"):
        dados = _armadura_na_tabela(equip["armadura"])
        if dados and dados.get("furtividade_desvantagem"):
            return f"{equip['armadura']}: desvantagem em Furtividade"
    return ""


def _rider_vale_contra(rider: dict, alvo: dict) -> bool:
    """O dano extra que só vale contra um tipo (Matadora de Dragões) acerta este alvo?"""
    if not rider.get("contra"):
        return True
    from rpg import tracos as _tracos_r
    return _tracos_r.tipo_de_criatura(alvo) in rider["contra"]


def _desequipar_o_que_saiu(char: dict, nome: str) -> str:
    """
    Tira do corpo o que não está mais na mochila.

    remove_item e sell_item diminuíam a quantidade sem olhar os slots: vender
    a cota de malha na loja deixava a CA 16 de uma armadura que já era da
    loja. Chamada depois de toda remoção; devolve a nota para o texto da
    ferramenta (vazia se nada mudou).
    """
    sheet = char.get("sheet") or {}
    equip = sheet.get("equipamentos") or {}
    item = next((i for i in (char.get("inventario") or []) if isinstance(i, dict)
                 and _norm_txt(i.get("nome", "")) == _norm_txt(nome)), None)
    restam = int(item.get("qtd", 1) or 1) if item else 0
    if not restam and _esta_sintonizado(sheet, nome):
        sheet["sintonizados"] = [n for n in sheet.get("sintonizados") or []
                                 if _norm_txt(n) != _norm_txt(nome)]
    # A mão secundária solta primeiro: a arma principal é a do ataque.
    ocupados = sorted(_slots_ocupados_por(equip, nome),
                      key=lambda s: 0 if s == "arma_secundaria" else 1)
    tirados = []
    while len(ocupados) > restam:
        slot = ocupados.pop(0)
        equip[slot] = None
        tirados.append(slot)
    if not tirados:
        return ""
    ca_antes = sheet.get("ca")
    _recalculate_ca(char)
    return (f"\n   '{nome}' saiu do slot [{', '.join(tirados)}]"
            + (f" — CA {ca_antes} → {sheet['ca']}" if ca_antes != sheet.get("ca") else "") + ".")


# ---------------------------------------------------------------------------
# 8. Condições e Status Temporários  (NOVO)
# ---------------------------------------------------------------------------

def reveal_defenses(char_name: str, damage_types: str = "") -> str:
    """
    Revela ao grupo as defesas de uma criatura: resistência, imunidade ou
    vulnerabilidade a tipos de dano.

    A tela de combate só mostra a defesa de um INIMIGO depois que o grupo a
    descobre — levando o golpe daquele tipo, ou por esta ferramenta. Chame
    depois de um teste de conhecimento bem-sucedido (Natureza, Arcanismo,
    Religião), quando alguém do grupo já enfrentou a criatura antes, ou
    quando a cena entrega a informação (um livro, um sobrevivente, o cheiro
    de enxofre). As defesas dos personagens do grupo não precisam disto: a
    ficha deles é do jogador.

    Args:
        char_name:    Nome da criatura.
        damage_types: Tipos a revelar, separados por vírgula (ex.: "fogo,
                      radiante"). Vazio revela todas as defesas dela.
    """
    char, err = _get_char(char_name)
    if not char:
        return err
    sheet = char.get("sheet") or {}
    if not sheet:
        return f"Nota: {char.get('name', char_name)} não tem ficha com defesas."

    pedidos = [_norm_damage_type(x.strip()) or x.strip().lower()
               for x in (damage_types or "").split(",") if x.strip()]

    rotulos = {"resistencias": "Resistente a", "imunidades": "Imune a",
               "vulnerabilidades": "Vulnerável a"}
    reveladas, ja_sabidas = [], []
    for campo in _CAMPOS_DE_DEFESA:
        tipos = sorted({tp for e in _traits_lookup(sheet, campo)
                        for tp in e.get("tipos", [])})
        for tp in tipos:
            if pedidos and tp not in pedidos:
                continue
            if _ja_descoberto(sheet, campo, tp):
                ja_sabidas.append(f"{rotulos[campo]} {tp}")
                continue
            _marcar_descoberta(sheet, campo, tp)
            reveladas.append(f"{rotulos[campo]} {tp}")

    memory.save_campaign()
    nome = char.get("name", char_name)
    if not reveladas and not ja_sabidas:
        alvo = f" de {', '.join(pedidos)}" if pedidos else ""
        return (f"Nota: nada a revelar — {nome} não tem resistência, imunidade "
                f"nem vulnerabilidade{alvo}. Diga isso ao grupo: descobrir que "
                f"não há fraqueza também é informação.")
    partes = [f"O grupo agora sabe sobre {nome}:"]
    if reveladas:
        partes.append("   " + " | ".join(reveladas))
    if ja_sabidas:
        partes.append(f"   (já sabia: {' | '.join(ja_sabidas)})")
    return "\n".join(partes)


def apply_condition(char_name: str, condition: str, duration_turns: int = 0) -> str:
    """
    Aplica uma condição D&D a um personagem. Condições afetam rolagens automaticamente:
    Cego → desvantagem em ataques e testes; Paralisado → crítico automático para atacantes;
    Envenenado → desvantagem em ataques e testes; Invisível → vantagem em ataques.

    Busca a descrição oficial da condição no Open5e (SRD). Usa texto interno como fallback.

    Args:
        char_name:      Nome do personagem.
        condition:      Nome da condição (ex: 'Cego', 'Envenenado', 'Paralisado').
        duration_turns: Duração em turnos DO PRÓPRIO AFETADO (0 = indefinida, até ser
                        removida manualmente). Desconta no fim de cada turno dele,
                        e acaba sozinha; condições com duração acabam com o combate.
    """
    from rpg.open5e import http as _req   # SRD com cache, sessão e retry

    char, err = _get_char(char_name)
    if not char:
        return err

    s     = char["sheet"]
    conds = s.setdefault("condicoes", [])
    c_low = condition.lower()

    if any(c["nome"].lower() == c_low for c in conds):
        return f"Aviso: {char['name']} já possui a condição '{condition}'."

    nova = {
        "nome":    condition.capitalize(),
        "duracao": duration_turns if duration_turns > 0 else None,
    }
    cs_ac = memory.campaign.get("combat_state") or {}
    if duration_turns > 0 and cs_ac.get("is_active"):
        # Aplicada na vez do próprio afetado: aquele turno não conta.
        if memory.char_key(_combat_current_actor()) == memory.char_key(char["name"]):
            nova["token_aplicacao"] = cs_ac.get("turn_token", 0)
    conds.append(nova)

    # Busca descrição oficial no Open5e
    srd_desc = ""
    en_slug  = CONDITION_PT_TO_EN.get(c_low, c_low)
    _edbg(f"  [OPEN5E] Buscando descrição oficial da condição '{condition}' (slug: {en_slug})…")
    try:
        r = _req.get(f"https://api.open5e.com/v1/conditions/{en_slug}/", timeout=4)
        if r.ok:
            raw = r.json().get("desc", "")
            srd_desc = " ".join(raw.split())[:300] if raw else ""
            _edbg(f"  [OPEN5E] Descrição da condição '{condition}' obtida do SRD.")
    except Exception:
        pass

    effects    = CONDITION_EFFECTS.get(c_low, {})
    efeito_str = []
    if effects.get("attack_disadvantage"):  efeito_str.append("desvantagem em ataques")
    if effects.get("attack_advantage"):     efeito_str.append("vantagem em ataques")
    if effects.get("defense_disadvantage"): efeito_str.append("atacantes ganham vantagem")
    if effects.get("check_disadvantage"):   efeito_str.append("desvantagem em testes")
    if effects.get("auto_crit"):            efeito_str.append("crítico automático em corpo-a-corpo")

    if c_low == "envenenado" and _tem_antitoxina(s):
        efeito_str_antitoxina = (f"\n   Nota: {char['name']} está sob Antitoxina: a salvaguarda "
                                 f"contra Envenenado tinha vantagem. Se ele passou, use remove_condition.")
    else:
        efeito_str_antitoxina = ""

    dur_str        = (f" por {duration_turns} turno(s) de {char['name']}" if duration_turns > 0
                      else " (indefinidamente)")
    efeito_mecanico = f"\n   Mecânica: {', '.join(efeito_str)}." if efeito_str \
                      else "\n   (Condição narrativa — sem efeito mecânico automático.)"
    desc_oficial   = f"\n   {srd_desc}" if srd_desc else ""

    memory.save_campaign()
    return (
        f"{char['name']} recebeu a condição **{condition.capitalize()}**{dur_str}."
        f"{efeito_mecanico}{efeito_str_antitoxina}{desc_oficial}"
    )


def remove_condition(char_name: str, condition: str) -> str:
    """
    Remove uma condição ativa de um personagem.

    Args:
        char_name: Nome do personagem.
        condition: Nome da condição a remover (ex: 'Cego', 'Envenenado').
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    s     = char["sheet"]
    conds = s.get("condicoes", [])
    c_low = condition.lower()

    before = len(conds)
    s["condicoes"] = [c for c in conds if c["nome"].lower() != c_low]

    if len(s["condicoes"]) == before:
        return f"Aviso: {char['name']} não possui a condição '{condition}'."

    memory.save_campaign()
    return f"Condição **{condition.capitalize()}** removida de {char['name']}."


# ---------------------------------------------------------------------------
# 9. Moedas  (NOVO)
# ---------------------------------------------------------------------------

def modify_currency(char_name: str, currency_type: str, amount: int) -> str:
    """
    Adiciona ou remove moedas da bolsa do personagem.
    Valor POSITIVO = recebe moedas. Valor NEGATIVO = gasta moedas.
    Use para cobrar estadias, compras de itens, recompensas de missão ou saque de baús.

    Args:
        char_name:     Nome do personagem.
        currency_type: Tipo de moeda: 'ouro', 'prata' ou 'cobre'.
        amount:        Quantidade (positivo = recebe, negativo = gasta).
    """
    char, err = _get_char(char_name, allow_dead=True)
    if not char:
        return err

    s    = char["sheet"]
    tipo = currency_type.lower()

    if tipo not in ("ouro", "prata", "cobre"):
        return "Tipo de moeda inválido. Use: 'ouro', 'prata' ou 'cobre'."

    atual = s.get(tipo, 0)

    if amount < 0 and atual < abs(amount):
        return (
            f"Erro: {char['name']} não tem {currency_type} suficiente!\n"
            f"   {currency_type.capitalize()} atual: {atual} (necessário: {abs(amount)})"
        )

    s[tipo] = max(0, atual + amount)
    acao    = "recebeu" if amount > 0 else "gastou"

    memory.save_campaign()
    return (
        f"{char['name']} {acao} {abs(amount)} {currency_type}.\n"
        f"   Ouro: {s.get('ouro', 0)} | Prata: {s.get('prata', 0)} | Cobre: {s.get('cobre', 0)}"
    )


# ---------------------------------------------------------------------------
# 10. Teste de Morte  (NOVO)
# ---------------------------------------------------------------------------

def roll_death_save(char_name: str, player_roll: int = 0) -> str:
    """
    Realiza um Teste de Morte para um personagem com HP = 0 (inconsciente).
    Avalia 1d20 limpo:
    • Natural 20: recupera 1 ponto de vida e estabiliza (testes zerados).
    • 10 ou mais: 1 sucesso (3 sucessos = estabilizado).
    • 9 ou menos: 1 falha (3 falhas = morto).
    • Natural 1: conta como 2 falhas.

    Chame esta ferramenta a cada turno enquanto o personagem estiver inconsciente
    e sem aliados para estabilizá-lo.

    Args:
        char_name:   Nome do personagem inconsciente.
        player_roll: Resultado do d20 JÁ ROLADO pelo jogador (1–20). Quando o
                     teste de morte é de um PERSONAGEM JOGÁVEL, peça o dado ao
                     jogador, espere a resposta ("[DADO DO JOGADOR …] rolei X")
                     e passe esse X aqui. NUNCA role um d20 novo nem invente o
                     valor — isso descartaria a rolagem real do jogador. Deixe
                     0 apenas para NPCs, quando o sistema deve rolar sozinho.
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    s = char["sheet"]

    if s["vida_atual"] > 0:
        return f"Aviso: {char['name']} não está inconsciente (HP: {s['vida_atual']}). Teste de Morte não aplicável."

    # Usa a rolagem do JOGADOR quando fornecida e válida (1–20). Só rola
    # internamente quando nenhum valor veio (teste de morte de NPC).
    if isinstance(player_roll, int) and 1 <= player_roll <= 20:
        roll = player_roll
    else:
        roll = random.randint(1, 20)
    # Sinal de Esperança: vantagem — o motor rola o segundo d20.
    _nota_esperanca = ""
    if any(e.get("vantagem_morte") for e in _efeitos(s)):
        _segundo = random.randint(1, 20)
        _nota_esperanca = f" (Sinal de Esperança: vantagem, segundo d20 = {_segundo})"
        roll = max(roll, _segundo)

    # Natural 20: milagre — recupera 1 pv
    if roll == 20:
        s["vida_atual"]          = 1
        s["death_saves_sucessos"] = 0
        s["death_saves_falhas"]   = 0
        char["status"]            = "vivo"
        memory.save_campaign()
        return (
            f"CRÍTICO NATURAL! {char['name']} se recupera milagrosamente!{_nota_esperanca}\n"
            f"   d20={roll} → Recupera 1 ponto de vida e estabiliza.\n"
            f"   Vida: 1/{s['vida_max']}"
        )

    # Natural 1: conta como 2 falhas
    if roll == 1:
        s["death_saves_falhas"] = min(3, s.get("death_saves_falhas", 0) + 2)
        falhas = s["death_saves_falhas"]
        result = (
            f"FALHA CRÍTICA nos Testes de Morte! {char['name']} sofre 2 falhas!\n"
            f"   d20={roll}\n"
            f"   Sucessos: {s.get('death_saves_sucessos', 0)}/3 | Falhas: {falhas}/3"
        )
    elif roll >= 10:
        s["death_saves_sucessos"] = min(3, s.get("death_saves_sucessos", 0) + 1)
        sucessos = s["death_saves_sucessos"]
        result = (
            f"Teste de Morte bem-sucedido! ({char['name']}){_nota_esperanca}\n"
            f"   d20={roll} ≥ 10 → 1 sucesso.\n"
            f"   Sucessos: {sucessos}/3 | Falhas: {s.get('death_saves_falhas', 0)}/3"
        )
    else:
        s["death_saves_falhas"] = min(3, s.get("death_saves_falhas", 0) + 1)
        falhas = s["death_saves_falhas"]
        result = (
            f"Erro: Teste de Morte falhou. ({char['name']})\n"
            f"   d20={roll} < 10 → 1 falha.\n"
            f"   Sucessos: {s.get('death_saves_sucessos', 0)}/3 | Falhas: {falhas}/3"
        )

    # Resolução final
    if s.get("death_saves_sucessos", 0) >= 3:
        s["death_saves_sucessos"] = 0
        s["death_saves_falhas"]   = 0
        char["status"]            = "estabilizado"
        result += (f"\n   {char['name']} ESTABILIZOU! Permanece inconsciente (0 HP) "
                   f"mas não morrerá. Precisa de cura para voltar a agir.")

        _log_combat_event("stabilize", char["name"], "",
                          msg=f"{char['name']} estabilizou (d20={roll}, inconsciente)",
                          d20=roll)
    elif s.get("death_saves_falhas", 0) >= 3:
        s["death_saves_sucessos"] = 0
        s["death_saves_falhas"]   = 0
        char["status"]            = "morto"
        s["morreu_hora"]          = _agora_em_horas()
        result += f"\n   {char['name']} MORREU. Narre a cena de forma dramática e definitiva."
        _log_combat_event("death", char["name"], "",
                          msg=f"{char['name']} morreu (d20={roll})", d20=roll)

    memory.save_campaign()
    result += _auto_advance_turn(char_name)
    memory.save_campaign()
    return result


# ---------------------------------------------------------------------------
# 11. Inventário
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Detecção e identificação de itens mágicos (Open5e)
# ---------------------------------------------------------------------------

# RAÍZES, não palavras inteiras — e sem acento, porque a comparação passa por
# _norm_txt.
#
# A lista antiga era de palavras completas e SÓ NO MASCULINO: "mágico",
# "encantado", "rúnico", "sagrado", "arcano", "divino", "abençoado". Em
# português metade do vocabulário de item mágico é feminino — espada, lâmina,
# adaga, armadura, coroa, varinha, relíquia — então "Espada Mágica",
# "Lâmina Rúnica" e "Coroa Sagrada" passavam sem nenhuma conferência.
# Medido: 7 de 8 pares só detectavam a forma masculina. "amaldiçoada" era a
# única exceção, acrescentada à mão — sinal de que alguém tropeçou nela e
# corrigiu só aquele caso.
#
# Casar pela raiz resolve gênero e plural de uma vez: "magic" pega mágico,
# mágica, mágicos, magical.
_MAGIC_ITEM_ROOTS = (
    "magic", "encantad", "amaldicoad", "sagrad", "profan", "divin",
    "arcan", "runic", "elfic", "bendit", "abencoad", "lendari",
    "ancient", "legendary", "of the", "da tempestade", "do fogo", "do caos",
    "da sombra", "da luz", "da escuridao", "da morte", "da vida",
)

# O que denuncia EFEITO MECÂNICO na descrição, mesmo num item de nome comum.
# Uma "Bússola de Osso" não preocupa ninguém; uma que "dá vantagem em testes
# de Sobrevivência" preocupa — e o nome dela não tem uma única palavra mágica.
_EFEITO_MECANICO_ROOTS = (
    "dano", "cura", "curar", "vantagem", "desvantagem", "resistenc",
    "imunidad", "bonus", "penalidad", "recarga", "por dia", "por descanso",
    "aumenta", "reduz", "concede", "ignora", "absorve",
)
# As siglas precisam de FRONTEIRA DE PALAVRA, não de substring. Com "ca " na
# lista acima, "lembrança do pai" virava efeito mecânico — porque "lembranca "
# contém "ca ". Um punhal de recordação era cobrado como item desequilibrado.
_SIGLA_REGRA_RE = re.compile(r"\b(?:cd|ca|pv|hp|xp|mp)\b", re.IGNORECASE)
_DADO_RE = re.compile(r"\b\d*d(?:4|6|8|10|12|20|100)\b", re.IGNORECASE)
_BONUS_NUM_RE = re.compile(r"[+\-][1-9]\d*\b")
_MAGIC_BONUS_RE = re.compile(r'\+[1-5]\b')
_MAGIC_OF_RE    = re.compile(
    r'\b(?:espada|machado|arco|adaga|cajado|anel|amuleto|manto|armadura|elmo|luvas|botas|cinto|varinha|orbe)\s+'
    r'(?:d[aeo]|do|da|dos|das)\s+\w+',
    re.IGNORECASE,
)

def _looks_magic(item_name: str, description: str = "") -> bool:
    """True se o item parece mágico pelo nome ou pela descrição."""
    combinado = _norm_txt(item_name + " " + description)
    if _MAGIC_BONUS_RE.search(item_name):
        return True
    if any(raiz in combinado for raiz in _MAGIC_ITEM_ROOTS):
        return True
    if _MAGIC_OF_RE.search(item_name):
        return True
    return False


def _tem_efeito_mecanico(item_name: str, description: str = "") -> bool:
    """
    A descrição promete algo que o motor teria de sustentar (dano, cura,
    vantagem, bônus numérico, dado)?

    Isto é o que separa sabor de regra. "Aponta para a pessoa amada" é sabor:
    não muda nenhuma conta e não precisa de balanceamento. "Dá vantagem em
    testes de Sobrevivência" é regra, e regra inventada desequilibra a mesa
    sem ninguém perceber.
    """
    texto = _norm_txt(item_name + " " + description)
    if any(raiz in texto for raiz in _EFEITO_MECANICO_ROOTS):
        return True
    bruto = item_name + " " + description
    return bool(_DADO_RE.search(bruto) or _BONUS_NUM_RE.search(bruto)
                or _SIGLA_REGRA_RE.search(bruto))


def _precisa_de_conferencia(item_name: str, description: str = "") -> bool:
    """
    Vale gastar uma consulta ao SRD por este item?

    Sim quando ele parece mágico OU quando a descrição promete efeito. Não
    para o resto: corda, tocha e ração não estão no SRD de itens mágicos, e
    marcá-las como "customizadas" seria gritar lobo a cada saque.
    """
    return (_looks_magic(item_name, description)
            or _tem_efeito_mecanico(item_name, description))


# ── Nomes de item mágico: português → SRD ───────────────────────────────────
#
# Os nomes inteiros ("Manto Élfico" → Cloak of Elvenkind) estão no compêndio
# (rpg/itens.py, scripts/srd_itens_pt.json), com os apelidos. O que fica aqui é
# a COMPOSIÇÃO, que pega a variação que ninguém cadastrou: "Anel da Proteção",
# "Varinha das Bolas de Fogo". Ela só gera candidatos; nenhum é aceito sem que
# o compêndio tenha o nome exato.
# "Cabeça de complemento": o grosso do SRD é "Ring of X", "Wand of X"...
_ITEM_CABECA_PT_TO_EN: dict[str, tuple[str, ...]] = {
    "anel": ("Ring",), "varinha": ("Wand",), "cajado": ("Staff",), "bastao": ("Rod", "Staff"),
    "cetro": ("Rod",), "haste": ("Rod",), "pocao": ("Potion",), "amuleto": ("Amulet",),
    "manto": ("Cloak", "Mantle", "Robe"), "capa": ("Cloak", "Cape"), "botas": ("Boots",),
    "elmo": ("Helm",), "capacete": ("Helm",), "luvas": ("Gloves",), "manoplas": ("Gauntlets",),
    "bracadeiras": ("Bracers",), "braceletes": ("Bracers",), "cinto": ("Belt",),
    "tunica": ("Robe",), "robe": ("Robe",), "tomo": ("Tome",), "manual": ("Manual",),
    "colar": ("Necklace",), "broche": ("Brooch",), "espada": ("Sword",), "maca": ("Mace",),
    "escudo": ("Shield",), "armadura": ("Armor",), "oleo": ("Oil",), "po": ("Dust",),
    "corda": ("Rope",), "pedra": ("Stone",), "gema": ("Gem",), "olhos": ("Eyes",),
    "talisma": ("Talisman",), "periapto": ("Periapt",), "trompa": ("Horn",), "chifre": ("Horn",),
    "flauta": ("Pipes",), "gaita": ("Pipes",), "ferraduras": ("Horseshoes",),
    "chinelos": ("Slippers",), "sapatilhas": ("Slippers",), "diadema": ("Circlet",),
    "tiara": ("Circlet",), "faixa": ("Headband",), "oculos": ("Goggles",), "chapeu": ("Hat",),
    "lanterna": ("Lantern",), "medalhao": ("Medallion",), "perola": ("Pearl",),
    "incensario": ("Censer",), "braseiro": ("Brazier",), "tigela": ("Bowl",),
    "sino": ("Chime",), "carrilhao": ("Chime",),
}

_ITEM_COMPLEMENTO_PT_TO_EN: dict[str, str] = {
    "protecao": "Protection", "invisibilidade": "Invisibility", "cura": "Healing",
    "velocidade": "Speed", "rapidez": "Speed", "levitacao": "Levitation", "saude": "Health",
    "voo": "Flying", "forca de gigante": "Giant Strength", "forca do gigante": "Giant Strength",
    "forca gigante": "Giant Strength", "forca de ogro": "Ogre Power", "forca do ogro": "Ogre Power",
    "poder de ogro": "Ogre Power", "bolas de fogo": "Fireballs", "misseis magicos": "Magic Missiles",
    "relampagos": "Lightning Bolts", "raios": "Lightning Bolts", "teia": "Web", "teias": "Web",
    "medo": "Fear", "paralisia": "Paralysis", "polimorfia": "Polymorph", "metamorfose": "Polymorph",
    "segredos": "Secrets", "prodigios": "Wonder", "maravilhas": "Wonder",
    "deteccao de magia": "Magic Detection", "deteccao de inimigos": "Enemy Detection",
    "amarracao": "Binding", "prisao": "Binding", "resistencia": "Resistance", "evasao": "Evasion",
    "queda suave": "Feather Falling", "queda de pena": "Feather Falling", "acao livre": "Free Action",
    "salto": "Jumping", "saltos": "Jumping", "regeneracao": "Regeneration", "natacao": "Swimming",
    "telecinesia": "Telekinesis", "tres desejos": "Three Wishes", "calor": "Warmth",
    "andar sobre as aguas": "Water Walking", "caminhar sobre as aguas": "Water Walking",
    "visao de raio x": "X-ray Vision", "estrelas": "Stars", "arquimago": "the Archmagi",
    "fogo": "Fire", "gelo": "Frost", "frio": "Frost", "poder": "Power", "golpe": "Striking",
    "golpes": "Striking", "mago": "the Magi", "magos": "the Magi", "encantamento": "Charming",
    "arquearia": "Archery", "defesa": "Defense", "disfarce": "Disguise", "intelecto": "Intellect",
    "telepatia": "Telepathy", "teletransporte": "Teleportation",
    "compreensao de idiomas": "Comprehending Languages", "compreender idiomas": "Comprehending Languages",
    "brilho": "Brilliance", "respiracao aquatica": "Water Breathing", "respirar na agua": "Water Breathing",
    "escalada": "Climbing", "crescimento": "Growth", "diminuicao": "Diminution", "heroismo": "Heroism",
    "forma gasosa": "Gaseous Form", "clarividencia": "Clairvoyance", "leitura da mente": "Mind Reading",
    "ler mentes": "Mind Reading", "veneno": "Poison", "amizade animal": "Animal Friendship",
    "amizade com animais": "Animal Friendship", "influencia animal": "Animal Influence",
    "comando elemental": "Elemental Command", "armazenar magia": "Spell Storing",
    "armazenamento de magia": "Spell Storing", "reflexao de magia": "Spell Turning",
    "estrelas cadentes": "Shooting Stars", "carneiro": "the Ram", "blindagem mental": "Mind Shielding",
    "escudo mental": "Mind Shielding", "convocacao de djinni": "Djinni Summoning",
    "ruptura": "Disruption", "punicao": "Smiting", "terror": "Terror", "ferimento": "Wounding",
    "ferimentos": "Wounding", "roubo de vida": "Life Stealing", "afiada": "Sharpness", "corte": "Sharpness",
    "invulnerabilidade": "Invulnerability", "vulnerabilidade": "Vulnerability",
    "resistencia a magia": "Spell Resistance", "arrebatamento": "Blasting", "explosao": "Blasting",
    "explosoes": "Blasting", "etereo": "Etherealness", "eterealidade": "Etherealness",
    "afiacao": "Sharpness", "escorregadio": "Slipperiness", "desaparecimento": "Disappearance",
    "secura": "Dryness", "adaptacao": "Adaptation", "pensamentos": "Thoughts",
    "encantar": "Charming", "visao minuciosa": "Minute Seeing", "aguia": "the Eagle",
    "visao noturna": "Night", "noite": "Night", "morcego": "the Bat", "arraia": "the Manta Ray",
    "aranha": "Arachnida", "deslocamento": "Displacement", "alerta": "Alertness", "seguranca": "Security",
    "absorcao": "Absorption", "dominio": "Rulership", "poder senhorial": "Lordly Might",
    "escalar": "Climbing", "enredar": "Entanglement", "enredamento": "Entanglement",
    "fechamento de feridas": "Wound Closure", "fechar feridas": "Wound Closure",
    "imunidade a veneno": "Proof against Poison", "lideranca e influencia": "Leadership and Influence",
    "pensamento claro": "Clear Thought", "compreensao": "Understanding", "exercicio": "Gainful Exercise",
    "golens": "Golems", "saude corporal": "Bodily Health", "rapidez de acao": "Quickness of Action",
    "revelacao": "Revealing", "insetos": "Swarming Insects", "trovao e relampago": "Thunder and Lightning",
    "definhamento": "Withering", "piton": "the Python", "floresta": "the Woodlands", "bosques": "the Woodlands",
    "planos": "the Planes", "valhalla": "Valhalla", "bolas": "Fireballs", "luz": "Brightness",
    "visao": "Seeing", "encanto": "Charming", "comandar elementais da agua": "Commanding Water Elementals",
    "invernia": "the Winterlands", "terras invernais": "the Winterlands",
    "passos largos e saltos": "Striding and Springing", "natacao e escalada": "Swimming and Climbing",
    "apanhar projeteis": "Missile Snaring", "atracao de projeteis": "Missile Attraction",
    "escudo": "Shielding", "blindagem": "Shielding", "abertura": "Opening", "zefir": "a Zephyr",
}

def _candidatos_srd(item_name: str) -> list[str]:
    """Nomes em inglês compostos por "Cabeça de Complemento" ('Anel da X' → 'Ring of X')."""
    alvo = _norm_txt(_itens.separar_bonus(item_name or "")[0])
    candidatos: list[str] = []
    m = re.match(r"^(\S+)\s+(?:de|da|do|das|dos)\s+(.+)$", alvo)
    if m:
        cabecas = _ITEM_CABECA_PT_TO_EN.get(m.group(1), ())
        resto = re.sub(r"^(?:o|a|os|as)\s+", "", m.group(2))
        complemento = _ITEM_COMPLEMENTO_PT_TO_EN.get(resto)
        if cabecas and complemento:
            candidatos = [f"{cabeca} of {complemento}" for cabeca in cabecas]
    return candidatos


def _mesmo_item(nome_srd: str, candidato: str) -> bool:
    """
    O nome do SRD é o candidato? Casamento EXATO (sem caixa, acento e
    pontuação), aceitando o parêntese: "Stone of Good Luck (Luckstone)" casa
    com "Stone of Good Luck" e com "Luckstone". Nunca por palavras em comum.
    """
    def limpo(t: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", _norm_txt(t)).strip()
    a, b = limpo(nome_srd), limpo(candidato)
    if not a or not b:
        return False
    if a == b:
        return True
    m = re.match(r"^(.*)\((.*)\)\s*$", _norm_txt(nome_srd))
    return bool(m) and b in (limpo(m.group(1)), limpo(m.group(2)))


def _item_magico_do_srd(item_name: str) -> dict | None:
    """
    O item mágico do SRD com este nome, do compêndio local (rpg/itens.py), ou
    None. "Espada Longa +2" é a Arma +N rara; "Anel da Proteção" acha o Anel
    de Proteção pela composição.

    Antes era o Open5e v1 em tempo de jogo, com o nome traduzido: cada item
    novo custava até seis consultas, e a rede caída deixava a dúvida entre
    "não existe" e "não consegui perguntar".
    """
    e = _itens.magico(item_name)
    if e:
        return e
    _base, bonus = _itens.separar_bonus(item_name or "")
    for cand in _candidatos_srd(item_name):
        e = _itens.magico(f"{cand} +{bonus}" if bonus else cand)
        if e:
            return e
    return None


def _resumo_do_magico(e: dict) -> str:
    """'Anel — raro, requer sintonização.' A linha que a Mochila mostra, em português."""
    return _itens.resumo_magico(e)


def _dados_srd_do_item(e: dict) -> dict:
    """O que a Mochila guarda do SRD num item: em português, sem o texto em inglês."""
    return {"nome": e["nome"], "tipo": e.get("tipo", ""), "raridade": e.get("raridade", ""),
            "sintonizacao": bool(e.get("sintonizacao"))}


def identify_item(char_name: str, item_name: str) -> str:
    """
    Identifica um item mágico pelo SRD de D&D 5e. Use quando o grupo estudar
    o item (um descanso curto com ele), usar a magia Identificar, ou alguém
    que o conhece contar o que ele é.

    Devolve o nome no SRD, tipo, raridade, sintonização e o texto do SRD (em
    inglês: traduza ao narrar). Se o item não existir no SRD, informa que é
    item próprio da campanha.

    Args:
        char_name: Nome do personagem que possui o item.
        item_name: Nome do item a identificar.
    """
    char, err = _get_char(char_name, allow_dead=True)
    if not char:
        return err

    e = _item_magico_do_srd(item_name)
    alvo = _item_do_inventario(char, item_name)

    if e:
        # O item conferido fica marcado: a Mochila só oferece "Identificar"
        # para o que ainda não foi estudado, e mostra o que foi achado.
        if alvo:
            alvo["custom"] = False          # conferido e canônico
            alvo["identificado"] = True
            alvo["nome_srd"] = e["nome_srd"]
            alvo["srd"] = _dados_srd_do_item(e)
            if not (alvo.get("descricao") or "").strip():
                alvo["descricao"] = _resumo_do_magico(e)
            memory.save_campaign()
        cabeca = (f"**{item_name}** é **{e['nome']}** ({e['nome_srd']}) no SRD"
                  if not _mesmo_item(e["nome"], item_name) else f"**{e['nome']}** ({e['nome_srd']})")
        sint = " · requer sintonização" if e.get("sintonizacao") else ""
        bonus = f" · +{e['bonus']}" if e.get("bonus") else ""
        texto = " ".join(_itens.texto_srd(e, item_name).split())[:700]
        return (f"{cabeca}\n"
                f"   Tipo: {e.get('tipo', '')} · Raridade: {e.get('raridade', '')}{bonus}{sint}\n"
                f"   Texto do SRD (em inglês; narre em português): {texto}")

    if alvo:
        # Fora do SRD: a mesma marca que add_item dá, e conferido.
        alvo["custom"] = True
        alvo["identificado"] = True
        memory.save_campaign()
    nivel = (char.get("sheet") or {}).get("nivel", 1)
    return (
        f"Aviso: '{item_name}' não existe no SRD de D&D 5e.\n"
        f"   Este parece ser um item customizado/homebrew.\n"
        f"   Certifique-se de que seus efeitos são balanceados para "
        f"um grupo nível {nivel}. Ajuste a descrição se necessário."
    )


def add_item(char_name: str, item_name: str, quantity: int = 1, description: str = "") -> str:
    """
    Adiciona um item ao inventário do personagem (empilha se já existir).
    Todo item é conferido no SRD de D&D 5e:
    • item mágico do SRD → entra com tipo e raridade, ainda por identificar
      (o grupo descobre o que é estudando o item ou com a magia Identificar);
    • não está no SRD → aceito como item da campanha, com aviso de balanço se
      a descrição prometer efeito mecânico.

    Args:
        char_name:   Nome do personagem.
        item_name:   Nome do item (ex: 'Poção de Cura', 'Espada Longa +1').
        quantity:    Quantidade a adicionar (padrão: 1). Com 0, só troca a
                     descrição de um item que o personagem já tem (o ferreiro
                     que tempera a lâmina).
        description: Descrição das propriedades do item (opcional).
    """
    char = memory.campaign["characters"].get(memory.char_key(char_name))
    if not char:
        return f"Personagem '{char_name}' não encontrado."
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        quantity = -1

    char.setdefault("inventario", [])
    inv = char["inventario"]

    # Empilha pelo nome sem caixa e sem acento, como o resto do motor procura:
    # "Pocao de cura" e "Poção de Cura" eram duas pilhas.
    existing = _item_do_inventario(char, item_name)
    if quantity < 0 or (quantity == 0 and not (existing and description)):
        return (f"Erro: quantidade inválida ({quantity}). Para tirar itens do "
                f"inventário, use remove_item; com 0, só se troca a descrição "
                f"de um item que o personagem já tem.")
    if existing:
        existing["qtd"] = int(existing.get("qtd", 1) or 1) + quantity
        if description:
            existing["descricao"] = description
        memory.save_campaign()
        return f"{char['name']} agora tem {existing['qtd']}x {existing['nome']}."

    nivel = (char.get("sheet") or {}).get("nivel", 1)
    item_dict, warning = _conferir_item_novo(item_name, description, nivel)
    item_dict["qtd"] = quantity
    inv.append(item_dict)
    memory.save_campaign()
    return f"{item_name} (×{quantity}) adicionado ao inventário de {char['name']}.{warning}"


def _conferir_item_novo(item_name: str, description: str = "", nivel: int = 1) -> tuple[dict, str]:
    """
    A conferência de item que add_item faz na entrada, separada para o saque
    (rpg/saque.py) cobrar o mestre no momento em que ele põe o item no chão.

    Devolve (item sem quantidade, aviso). O aviso começa com quebra de linha,
    como add_item sempre anexou.
    """
    item_dict: dict = {"nome": item_name, "descricao": description}
    warning = ""

    # O compêndio é local: todo item passa por ele, sem custo. Antes a
    # consulta ia à rede, e por isso só disparava para nome mágico ou efeito
    # descrito — a "Bolsa de Contenção" (sem palavra mágica) passava direto.
    srd_data = _item_magico_do_srd(item_name)
    if srd_data:
        item_dict["custom"] = False
        item_dict["nome_srd"] = srd_data["nome_srd"]
        item_dict["srd"] = _dados_srd_do_item(srd_data)
        # O que o item faz fica para quando o grupo o estudar (identify_item).
        # O comum (Poção de Cura, Pergaminho de truque) todo mundo reconhece.
        item_dict["identificado"] = srd_data.get("raridade") == "comum"
        if not (description or "").strip() and item_dict["identificado"]:
            item_dict["descricao"] = _resumo_do_magico(srd_data)
    elif _precisa_de_conferencia(item_name, description):
        # Fora do SRD: fica marcado. A marca é FATO, não julgamento — vale
        # tanto para um item de sabor quanto para um que mexe na regra.
        item_dict["custom"] = True
        if _tem_efeito_mecanico(item_name, description):
            # Este o motor vai cobrar: item inventado COM regra é o que
            # desequilibra a mesa sem ninguém perceber.
            item_dict["efeito_mecanico"] = True
            warning = (
                f"\nAviso: '{item_name}' NÃO EXISTE no SRD de D&D 5e e a "
                f"descrição promete efeito mecânico.\n"
                f"   Ou troque por um item real do SRD, ou declare aqui "
                f"por que ele é equilibrado para um grupo de nível {nivel} "
                f"— e prefira efeitos pequenos (+1, 1d4, uma vez por "
                f"descanso) a números redondos e grandes."
            )
        elif not (description or "").strip():
            # Nome mágico e NENHUMA descrição: não dá para dizer se é
            # sabor ou se quebra a mesa. Isso não é "sabor", é lacuna —
            # e era o buraco por onde a loja passava, porque buy_item
            # chamava add_item sem descrição nenhuma.
            item_dict["efeito_desconhecido"] = True
            warning = (
                f"\nAviso: '{item_name}' NÃO EXISTE no SRD e entrou sem "
                f"descrição. Diga o que ele faz — mesmo que seja nada — "
                f"com add_item(..., description='...') ou "
                f"justify_custom_item(). Sem isso não há como saber se "
                f"é lembrança de família ou espada +3."
            )
        else:
            warning = (
                f"\n'{item_name}' não está no SRD — registrado como "
                f"item próprio da sua campanha. Sem efeito mecânico "
                f"declarado, então é sabor: nada a balancear."
            )
    return item_dict, warning


def justify_custom_item(char_name: str, item_name: str, reason: str) -> str:
    """
    Registra por que um item inventado é equilibrado, e encerra a cobrança.

    Use quando decidir MANTER um item que não existe no SRD e que tem efeito
    mecânico. A justificativa fica na ficha: quem abrir a campanha meses
    depois vê por que aquele item existe e com que critério foi calibrado.

    Args:
        char_name: Dono do item.
        item_name: Nome do item.
        reason:    Por que é equilibrado (ex: "+1 só contra mortos-vivos,
                   equivalente a uma arma +1 de nível 3").
    """
    char = memory.campaign["characters"].get(memory.char_key(char_name))
    if not char:
        return f"Personagem '{char_name}' não encontrado."
    if not (reason or "").strip():
        return ("Informe a justificativa. Um item inventado sem critério "
                "declarado é exatamente o que esta trava existe para pegar.")

    for it in (char.get("inventario") or []):
        if isinstance(it, dict) and _norm_txt(it.get("nome", "")) == _norm_txt(item_name):
            if not it.get("custom"):
                return (f"'{it.get('nome')}' é item canônico do SRD — "
                        f"não precisa de justificativa.")
            it["balanco_justificado"] = reason.strip()
            memory.save_campaign()
            return (f"Balanço de '{it.get('nome')}' registrado: "
                    f"{reason.strip()}")
    # O item ainda pode estar no chão, no saque aberto (offer_loot).
    from rpg.saque import pile_items_with_flags
    for it in pile_items_with_flags():
        if _norm_txt(it.get("nome", "")) == _norm_txt(item_name) and it.get("custom"):
            it["balanco_justificado"] = reason.strip()
            memory.save_campaign()
            return (f"Balanço de '{it.get('nome')}' (no saque) registrado: "
                    f"{reason.strip()}")
    return f"Aviso: '{item_name}' não está no inventário de {char.get('name', char_name)}."


def list_custom_items() -> str:
    """
    Lista TODOS os itens da campanha que não existem no SRD de D&D 5e,
    separando os que só têm sabor dos que prometem efeito mecânico.

    Serve de auditoria: é aqui que se vê, de uma vez, o que foi inventado ao
    longo da campanha e quanto disso mexe nas regras.
    """
    com_regra, so_sabor = [], []
    for ch in memory.campaign.get("characters", {}).values():
        dono = ch.get("name", "?")
        for it in (ch.get("inventario") or []):
            if not isinstance(it, dict) or not it.get("custom"):
                continue
            linha = (f"  • {it.get('nome')} ×{it.get('qtd', 1)}  "
                     f"({dono})\n      {(it.get('descricao') or '—')[:110]}")
            (com_regra if it.get("efeito_mecanico") else so_sabor).append(linha)

    if not com_regra and not so_sabor:
        return ("Nenhum item fora do SRD nesta campanha — tudo o que o "
                "grupo carrega é canônico.")

    partes = []
    if com_regra:
        partes.append(f"Aviso: COM EFEITO MECÂNICO ({len(com_regra)}) — "
                      f"inventados E mexendo na regra:\n" + "\n".join(com_regra))
    if so_sabor:
        partes.append(f"Só sabor ({len(so_sabor)}) — inventados, sem efeito "
                      f"declarado:\n" + "\n".join(so_sabor))
    return "\n\n".join(partes)


def remove_item(char_name: str, item_name: str, quantity: int = 1) -> str:
    """
    Remove um item do inventário do personagem.

    Args:
        char_name: Nome do personagem.
        item_name: Nome do item.
        quantity:  Quantidade a remover (padrão: 1).
    """
    char = memory.campaign["characters"].get(memory.char_key(char_name))
    if not char:
        return f"Erro: Personagem '{char_name}' não encontrado."

    inv  = char.get("inventario", [])
    item = next((i for i in inv if isinstance(i, dict)
                 and _norm_txt(i.get("nome", "")) == _norm_txt(item_name)), None)
    if not item:
        return f"Erro: '{item_name}' não está no inventário de {char['name']}."

    nome = item["nome"]
    if item["qtd"] <= quantity:
        inv.remove(item)
        nota = _desequipar_o_que_saiu(char, nome)
        memory.save_campaign()
        return f"{nome} removido do inventário de {char['name']}.{nota}"

    item["qtd"] -= quantity
    nota = _desequipar_o_que_saiu(char, nome)
    memory.save_campaign()
    return f"{char['name']} agora tem {item['qtd']}x {nome}.{nota}"


def list_inventory(char_name: str) -> str:
    """
    Lista o inventário completo de um personagem, incluindo moedas e equipamentos.
    Itens customizados (não encontrados no SRD D&D 5e) são marcados com .

    Args:
        char_name: Nome do personagem.
    """
    char = memory.campaign["characters"].get(memory.char_key(char_name))
    if not char:
        return f"Personagem '{char_name}' não encontrado."

    s   = char.get("sheet") or {}
    inv = char.get("inventario") or []

    lines = [f"Inventário de {char['name']}:"]

    # Moedas
    lines.append(
        f"  Ouro: {s.get('ouro', 0)} | Prata: {s.get('prata', 0)} | Cobre: {s.get('cobre', 0)}"
    )

    # Equipamentos ativos
    equip   = s.get("equipamentos", {})
    equipped = [(slot, item) for slot, item in equip.items() if item]
    if equipped:
        lines.append("  ── Equipados ──")
        for slot, item in equipped:
            lines.append(f"  [{slot}] {item}")

    # Inventário geral
    if inv:
        lines.append("  ── Itens ──")
        for item in inv:
            custom_tag = " [CUSTOMIZADO]" if item.get("custom") else ""
            desc = f" — {item['descricao']}" if item.get("descricao") else ""
            lines.append(f"  • {item['nome']} ×{item['qtd']}{custom_tag}{desc}")
    else:
        lines.append("  (Bolsa vazia)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 12. XP e nível
# ---------------------------------------------------------------------------

def _derrotados_citados(reason: str) -> list[dict]:
    """
    Inimigos fora de combate (DEFEATED_STATUSES) citados no motivo do XP, pelo
    nome inteiro ou pela primeira palavra do nome ("Derrota do Espreitador"
    cita "Espreitador das Sombras"). Motivo sem inimigo citado (missão, marco
    narrativo) devolve lista vazia e não tem trava.
    """
    motivo = _norm_txt(reason or "")
    if not motivo:
        return []
    palavras = set(re.findall(r"[a-z0-9]+", motivo))
    achados = []
    for ch in memory.campaign.get("characters", {}).values():
        # Aliado caído não é inimigo derrotado: não conta para XP.
        if not isinstance(ch, dict) or memory.luta_com_o_grupo(ch):
            continue
        if (ch.get("status", "") or "").lower() not in DEFEATED_STATUSES:
            continue
        nome = _norm_txt(ch.get("name", ""))
        if not nome:
            continue
        primeira = re.findall(r"[a-z]+", nome)
        cita = nome in motivo or (primeira and len(primeira[0]) >= 4 and
                                  (primeira[0] in palavras or primeira[0] + "s" in palavras))
        if cita:
            achados.append(ch)
    return achados


def grant_xp(char_name: str, amount: int, reason: str = "") -> str:
    """
    Concede XP ao personagem e verifica automaticamente se houve aumento de nível.
    Chame após derrotar inimigos, completar missões ou marcos narrativos importantes.

    XP sugerido por encontro:
    • Inimigo fraco (goblin, rato gigante): 25–50 XP
    • Inimigo médio (orc, guarda): 100–200 XP
    • Inimigo forte (líder, mago): 300–500 XP
    • Chefão: 800–2000 XP
    • Missão completada: 150–500 XP

    Args:
        char_name: Nome do personagem.
        amount:    Quantidade de XP a conceder.
        reason:    Motivo (ex: 'goblin derrotado', 'missão da aldeia completada').
    """
    char, err = _get_char(char_name, allow_dead=True)
    if not char:
        return err

    # XP pela derrota de um inimigo é uma vez por personagem. Ao retomar a
    # campanha o mestre relia o recap da tela tática ("conceda XP a cada
    # membro do grupo") e concedia de novo o XP do mesmo monstro.
    derrotados = _derrotados_citados(reason)
    if derrotados:
        chave = memory.char_key(char.get("name", char_name))
        novos = [d for d in derrotados if chave not in (d.get("xp_concedido_a") or [])]
        if not novos:
            nomes = ", ".join(d.get("name", "") for d in derrotados)
            return (f"Aviso: {char['name']} já recebeu XP pela derrota de {nomes}. "
                    f"Nada foi concedido de novo.")
        for d in novos:
            d.setdefault("xp_concedido_a", []).append(chave)

    s            = char["sheet"]
    # Ancora o contador de ASI no que ele JÁ tinha, antes de qualquer
    # nível novo. Sem isso, um personagem de nível 12 criado antes
    # deste contador apareceria devendo 10 pontos de atributo que talvez
    # já tenham sido aplicados à mão com set_stat.
    _carimbar_asi(s)
    s["xp"]     += amount
    reason_str   = f" ({reason})" if reason else ""
    result       = f"{char['name']} ganhou {amount} XP{reason_str}. Total: {s['xp']}"

    while s["nivel"] < 20 and s["xp"] >= XP_THRESHOLDS[s["nivel"]]:
        s["nivel"]        += 1
        s["proficiencia"]  = _proficiency_bonus(s["nivel"])

        info    = CLASS_DATA.get(s.get("classe", "").lower(), {"hit_die": 8, "mana_per_level": 0, "mana_stat": None})
        hit_die = info["hit_die"]
        con_mod = _modifier(s["constituicao"])
        hp_gain = max(1, random.randint(1, hit_die) + con_mod)
        s["vida_max"]   += hp_gain
        s["vida_atual"] += hp_gain
        # Um nível é um dado de vida a mais na reserva. Sem isto, quem subia
        # do 4 para o 5 continuava com 4 dados até o próximo descanso longo.
        if "hit_dice_remaining" in s:
            _rest, _max = _reserva_de_dados(s)
            s["hit_dice_remaining"] = min(_max, _rest + 1)

        # Mana recalculada pela tabela oficial (DMG p.288). É um lookup por
        # nível, não um acumulador — isso corrige a inconsistência antiga em
        # que o modificador de atributo era perdido a cada level-up.
        mana_antes    = s.get("mana_max", 0)
        novo_mana_max = _max_mana_for(s.get("classe", ""), s["nivel"])
        mana_gain     = novo_mana_max - mana_antes
        if novo_mana_max != mana_antes:
            s["mana_max"]   = novo_mana_max
            s["mana_atual"] = novo_mana_max

        s["xp_proximo"] = XP_THRESHOLDS[s["nivel"]] if s["nivel"] < 20 else s["xp"]

        result += (
            f"\nLEVEL UP! {char['name']} agora é Nível {s['nivel']}!"
            f"\n   Vida máxima: +{hp_gain} → {s['vida_max']}"
            f"\n   Proficiência: +{s['proficiencia']}"
        )
        if mana_gain > 0:
            result += f"\n   Mana máxima: +{mana_gain} → {s['mana_max']}"

        # Aplica habilidades de classe do novo nível automaticamente
        new_feats = _apply_class_features(char, s, s["nivel"])
        if new_feats:
            result += f"\n   Novas habilidades: {', '.join(new_feats)}"
        else:
            result += "\n   Escolha uma nova habilidade ou magia com learn_spell() ou learn_ability()."

        pend = _escolhas_pendentes(char)
        if pend:
            quais = ", ".join(f"{q['rotulo']} ({q['faltam']})" for q in pend)
            result += (f"\n   Escolhas PENDENTES: {quais}."
                       f" Quem escolhe é o JOGADOR, na tela de nível"
                       f" — não escolha por ele.")

    # Fora do laço: o que conta é a vaga depois do último nível subido.
    _vagas = _vagas_de_magia(char) if "LEVEL UP" in result else None
    if _vagas and (_vagas["truques"] or _vagas["magias"]):
        result += (f"\n   Magias a aprender: {_vagas['truques']} truque(s), "
                   f"{_vagas['magias']} magia(s). Quem escolhe é o JOGADOR, no Grimório"
                   f" — não chame learn_spell por ele.")

    if s["nivel"] < 20:
        result += f" / {s['xp_proximo']} para o próximo nível."

    memory.save_campaign()
    return result


# ===========================================================================
# SUBIDA DE NÍVEL — escolhas pendentes, ASI e tela
# ===========================================================================
# O motor sempre soube SUBIR de nível (grant_xp dá PV, proficiência, mana e as
# features automáticas da classe) e sempre soube APLICAR uma escolha
# (set_feature_choice, choose_feat, set_stat). O que faltava era o meio:
# saber que o personagem DEVE uma escolha.
#
# Sem isso, "escolha um Estilo de Combate" era uma frase no fim do texto de
# level-up. Se ninguém escolhesse, nada acontecia e nada cobrava — e o
# guerreiro seguia a campanha inteira sem o +1 de CA a que tinha direito.
#
# Quase tudo aqui é CALCULADO, não gravado: um personagem tem a habilidade
# "Estilo de Combate" na ficha e não tem entrada em feature_choices, logo
# deve essa escolha. Isso vale para fichas salvas antes desta mudança, sem
# migração nenhuma.
#
# A exceção é o ASI, que não deixa rastro: um +2 em FORÇA é indistinguível de
# uma força alta na criação. Esse precisa de contador.

# Níveis de Incremento de Atributo no SRD 5e. Guerreiro e Ladino ganham
# extras — é parte do que compensa a falta de magia deles.
_NIVEIS_ASI_BASE = {4, 8, 12, 16, 19}
_NIVEIS_ASI_EXTRA = {"guerreiro": {6, 14}, "ladino": {10}}

_PONTOS_POR_ASI = 2          # +2 num atributo ou +1 em dois
_TETO_ATRIBUTO  = 20         # o limite do 5e; set_stat sozinho não impõe


def _niveis_asi(classe: str) -> set[int]:
    return _NIVEIS_ASI_BASE | _NIVEIS_ASI_EXTRA.get(_norm_txt(classe), set())


def _asi_ganhos(sheet: dict) -> int:
    """Quantos incrementos o nível atual já concedeu."""
    nivel = int(sheet.get("nivel", 1) or 1)
    return sum(1 for n in _niveis_asi(sheet.get("classe", "")) if n <= nivel)


def _asi_pontos_pendentes(sheet: dict) -> int:
    """
    Pontos de atributo que o personagem tem a gastar.

    `asi_pontos_gastos` ausente significa ficha ANTERIOR a este contador, e
    aí a resposta é zero: reivindicar retroativamente todos os incrementos de
    um personagem de nível 12 daria +10 de atributo de presente, e não há
    como saber se o mestre já os aplicou à mão com set_stat. grant_xp carimba
    o contador no próximo level-up, e dali em diante a conta é exata.
    """
    if "asi_pontos_gastos" not in sheet:
        return 0
    gastos = int(sheet.get("asi_pontos_gastos", 0) or 0)
    return max(0, _asi_ganhos(sheet) * _PONTOS_POR_ASI - gastos)


def _carimbar_asi(sheet: dict) -> None:
    """
    Ancora o contador no que o personagem JÁ tinha, sem cobrar o passado.
    Chamado por grant_xp antes de subir o nível.
    """
    if "asi_pontos_gastos" not in sheet:
        sheet["asi_pontos_gastos"] = _asi_ganhos(sheet) * _PONTOS_POR_ASI


_ATRIBUTOS = ("forca", "destreza", "constituicao",
              "inteligencia", "sabedoria", "carisma")
_ATRIBUTO_PT = {
    "forca": "Força", "destreza": "Destreza", "constituicao": "Constituição",
    "inteligencia": "Inteligência", "sabedoria": "Sabedoria", "carisma": "Carisma",
}
# A sigla de três letras do 5e. Vai no payload em vez de ser recortada no JS
# porque "Constituição"[:3] daria "Con", e a mesa escreve CON.
_ATRIBUTO_SIGLA = {
    "forca": "FOR", "destreza": "DES", "constituicao": "CON",
    "inteligencia": "INT", "sabedoria": "SAB", "carisma": "CAR",
}


def _escolhas_pendentes(char: dict) -> list[dict]:
    """
    O que este personagem deve escolher. Derivado da ficha, não gravado.

    Uma feature com variantes (Estilo de Combate, Metamagia, um arquétipo)
    está pendente quando ele TEM a habilidade e escolheu menos que o `pick`
    dela. É a mesma pergunta que set_feature_choice já responde para validar
    — só que feita do lado de fora.
    """
    sheet = char.get("sheet") or {}
    pendentes = []

    for hab in (char.get("habilidades") or []):
        nome = (hab.get("nome") or "").strip()
        meta = _get_variants(nome)
        if not meta:
            continue
        pick = int(meta.get("pick", 1) or 1)
        atual = _get_feature_choice(char, nome)
        escolhidos = ([atual] if isinstance(atual, str) and atual
                      else list(atual or []))
        faltam = pick - len(escolhidos)
        if faltam <= 0:
            continue
        pendentes.append({
            "tipo":       "arquetipo" if nome in ARCHETYPE_FEATURES else "variante",
            "feature":    nome,
            "rotulo":     nome,
            "descricao":  meta.get("descricao", ""),
            "pick":       pick,
            "pick_label": meta.get("pick_label", "opção"),
            "escolhidos": escolhidos,
            "faltam":     faltam,
            "opcoes": [
                {"nome": k, "descricao": (v or {}).get("descricao", "")}
                for k, v in sorted((meta.get("options") or {}).items())
                if k not in escolhidos
            ],
        })

    pontos = _asi_pontos_pendentes(sheet)
    if pontos > 0:
        pendentes.append({
            "tipo":      "asi",
            "feature":   "Incremento de Atributo",
            "rotulo":    "Incremento de Atributo",
            "descricao": (f"{pontos} ponto(s) a distribuir: +1 em dois "
                          f"atributos ou +2 em um. Teto de {_TETO_ATRIBUTO}. "
                          f"Um talento consome {_PONTOS_POR_ASI} pontos."),
            "pick":      pontos,
            "faltam":    pontos,
            "escolhidos": [],
            "opcoes": [
                {"nome": _ATRIBUTO_PT[a], "chave": a,
                 "valor": int(sheet.get(a, 10) or 10),
                 "mod": _modifier(int(sheet.get(a, 10) or 10)),
                 "no_teto": int(sheet.get(a, 10) or 10) >= _TETO_ATRIBUTO}
                for a in _ATRIBUTOS
            ],
        })

    return pendentes


def apply_asi(char_name: str, stat_name: str, points: int = 1) -> str:
    """
    Gasta pontos de Incremento de Atributo (níveis 4, 8, 12, 16, 19 — e 6 e 14
    do Guerreiro, 10 do Ladino).

    Existe separada de set_stat porque ASI tem REGRA: sai de um pool que o
    nível concede e para no 20. set_stat é um ajuste livre do mestre, sem
    teto e sem pool — usar ela para ASI deixava o atributo subir sem limite e
    sem gastar nada.

    Args:
        char_name: Nome do personagem.
        stat_name: forca, destreza, constituicao, inteligencia, sabedoria ou carisma.
        points:    Quantos pontos gastar (1 ou 2).
    """
    char, err = _get_char(char_name)
    if not char:
        return err
    sheet = char["sheet"]

    chave = _norm_txt(stat_name).replace(" ", "")
    if chave not in _ATRIBUTOS:
        return (f"Erro: '{stat_name}' não é atributo. Use: "
                f"{', '.join(_ATRIBUTOS)}.")
    try:
        pts = max(1, min(_PONTOS_POR_ASI, int(points)))
    except (TypeError, ValueError):
        pts = 1

    disponiveis = _asi_pontos_pendentes(sheet)
    if disponiveis <= 0:
        return (f"Erro: {char['name']} não tem incremento de atributo pendente. "
                f"Eles vêm nos níveis {sorted(_niveis_asi(sheet.get('classe','')))}.")
    if pts > disponiveis:
        return (f"Erro: Só restam {disponiveis} ponto(s) de incremento para "
                f"{char['name']}.")

    antes = int(sheet.get(chave, 10) or 10)
    if antes >= _TETO_ATRIBUTO:
        return (f"Erro: {_ATRIBUTO_PT[chave]} de {char['name']} já está em "
                f"{antes} — o teto do 5e é {_TETO_ATRIBUTO}. "
                f"Escolha outro atributo ou um talento.")
    depois = min(_TETO_ATRIBUTO, antes + pts)
    usados = depois - antes

    sheet[chave] = depois
    sheet["asi_pontos_gastos"] = int(sheet.get("asi_pontos_gastos", 0) or 0) + usados

    # Derivados: CON mexe em PV, DES na CA, o atributo de conjuração na mana.
    extra = ""
    if chave == "constituicao":
        ganho = (_modifier(depois) - _modifier(antes)) * int(sheet.get("nivel", 1) or 1)
        if ganho:
            sheet["vida_max"] = max(1, int(sheet.get("vida_max", 1) or 1) + ganho)
            sheet["vida_atual"] = min(_hp_max_efetivo(sheet),
                                      int(sheet.get("vida_atual", 0) or 0) + ganho)
            extra += f"\n   Vida máxima: {ganho:+d} → {sheet['vida_max']}"
    if chave in ("destreza", "constituicao", "sabedoria"):
        ca_antes = sheet.get("ca", 10)
        _recalculate_ca(char)
        if sheet.get("ca", ca_antes) != ca_antes:
            extra += f"\n   CA agora: {sheet['ca']}"
    novo_mana = _max_mana_for(sheet.get("classe", ""), int(sheet.get("nivel", 1) or 1))
    if novo_mana != int(sheet.get("mana_max", 0) or 0):
        ganho_mana = novo_mana - int(sheet.get("mana_max", 0) or 0)
        sheet["mana_max"] = novo_mana
        sheet["mana_atual"] = min(novo_mana,
                                  int(sheet.get("mana_atual", 0) or 0) + max(0, ganho_mana))
        extra += f"\n   Mana máxima: {ganho_mana:+d} → {novo_mana}"

    memory.save_campaign()
    restam = _asi_pontos_pendentes(sheet)
    sobra = f" Restam {restam} ponto(s)." if restam else " Incremento concluído."
    return (f"{char['name']}: {_ATRIBUTO_PT[chave]} {antes} → **{depois}** "
            f"(modificador {_modifier(depois):+d}).{extra}\n  {sobra}")


def apply_asi_distribution(char_name: str, distribution) -> str:
    """
    Aplica de UMA VEZ os pontos que o jogador distribuiu na tela de nível.

    A tela funciona como o wizard de criação: o jogador sobe e desce os
    atributos com + e − num rascunho local, e só no "Confirmar" os pontos são
    gravados. Por isso o lote é ATÔMICO: tudo é validado antes de o primeiro
    ponto ser aplicado. Aplicar ponto a ponto e parar no erro deixaria meio
    incremento gravado (+1 em Força aceito, +1 em Carisma recusado) e um
    jogador olhando uma ficha que não é nem o que ele tinha nem o que ele
    escolheu.

    Cada ponto passa por apply_asi — a função do mestre —, então pool, teto de
    20 e os derivados (PV por CON, CA por DES, mana) continuam num lugar só.

    Args:
        char_name:    Nome do personagem.
        distribution: {"forca": 1, "constituicao": 1} ou "forca:1, constituicao:1".
    """
    char, err = _get_char(char_name)
    if not char:
        return err
    sheet = char["sheet"]

    # Aceita o dict da tela e o texto que um agente escreveria.
    if isinstance(distribution, str):
        bruto = {}
        for parte in distribution.split(","):
            if not parte.strip():
                continue
            nome, _, qtd = parte.partition(":")
            bruto[nome.strip()] = qtd.strip() or "1"
    elif isinstance(distribution, dict):
        bruto = dict(distribution)
    else:
        return "Distribuição inválida. Use {'forca': 1, 'constituicao': 1}."

    plano: dict[str, int] = {}
    for nome, qtd in bruto.items():
        chave = _norm_txt(str(nome)).replace(" ", "")
        if chave not in _ATRIBUTOS:
            return (f"Erro: '{nome}' não é atributo. Use: {', '.join(_ATRIBUTOS)}. "
                    f"Nenhum ponto foi aplicado.")
        try:
            n = int(qtd)
        except (TypeError, ValueError):
            return f"Erro: Quantidade inválida para {nome}: {qtd!r}. Nenhum ponto foi aplicado."
        if n < 0:
            return (f"Erro: Incremento não retira ponto de atributo ({nome}: {n}). "
                    f"Nenhum ponto foi aplicado.")
        if n:
            plano[chave] = plano.get(chave, 0) + n

    total = sum(plano.values())
    if total <= 0:
        return "Nenhum ponto distribuído."

    disponiveis = _asi_pontos_pendentes(sheet)
    if total > disponiveis:
        return (f"Erro: {total} ponto(s) distribuídos, mas {char['name']} só tem "
                f"{disponiveis} de incremento. Nenhum ponto foi aplicado.")

    for chave, n in plano.items():
        antes = int(sheet.get(chave, 10) or 10)
        if antes + n > _TETO_ATRIBUTO:
            return (f"Erro: {_ATRIBUTO_PT[chave]} iria a {antes + n}, acima do teto de "
                    f"{_TETO_ATRIBUTO}. Nenhum ponto foi aplicado.")

    # Tudo validado: agora aplica. apply_asi recebe no máximo 2 por chamada
    # (um incremento é +2 num atributo ou +1 em dois); quem deve dois
    # incrementos pode legitimamente pôr +3 num atributo, então o ponto sobe
    # em fatias.
    linhas = []
    for chave, n in plano.items():
        restam = n
        while restam > 0:
            fatia = min(_PONTOS_POR_ASI, restam)
            msg = apply_asi(char_name, chave, fatia)
            if msg.lstrip().startswith("Erro:"):          # não deveria: validado acima
                linhas.append(msg)
                break
            linhas.append(msg.split("\n")[0])
            restam -= fatia

    sobra = _asi_pontos_pendentes(sheet)
    fim = (f"   Restam {sobra} ponto(s) de incremento." if sobra
           else "   Incremento concluído.")
    return "\n".join(linhas + [fim])


def _assinatura_pendencias(grupo: list) -> str:
    """
    Resumo estável de TUDO que o grupo deve escolher, para a tela saber se algo
    mudou desde a última vez que abriu.

    É calculada aqui, sobre o grupo inteiro, e não no navegador sobre o
    personagem selecionado: antes, trocar o seletor para quem não devia nada
    mudava a assinatura e a tela achava que havia pendência nova.
    """
    partes = []
    for c in grupo:
        pend = _escolhas_pendentes(c)
        if pend:
            itens = ",".join(f"{q['rotulo']}/{q['faltam']}" for q in pend)
            partes.append(f"{c.get('name', '')}:{itens}")
    return "|".join(sorted(partes))


def levelup_snapshot(char_name: str = "") -> dict:
    """Estado da subida de nível para a tela (JSON-serializável)."""
    grupo = [c for c in memory.campaign.get("characters", {}).values()
             if memory.is_party_member(c) and (c.get("sheet") or {})]

    alvo = None
    if char_name:
        alvo = next((c for c in grupo
                     if _norm_txt(c.get("name", "")) == _norm_txt(char_name)), None)
    if not alvo:
        # Sem nome, abre em quem DEVE escolha — é para isso que a tela serve.
        alvo = next((c for c in grupo if _escolhas_pendentes(c)), None)
    if not alvo:
        alvo = grupo[0] if grupo else None

    if not alvo:
        return {"tem_personagem": False, "grupo": [], "pendencias": [],
                "devendo": [], "personagem": None, "assinatura": ""}

    s = alvo.get("sheet") or {}
    nivel = int(s.get("nivel", 1) or 1)
    xp = int(s.get("xp", 0) or 0)
    prox = int(s.get("xp_proximo", 0) or 0)
    base = XP_THRESHOLDS[nivel - 1] if 0 < nivel <= len(XP_THRESHOLDS) else 0
    faixa = max(1, prox - base)

    return {
        "tem_personagem": True,
        "assinatura": _assinatura_pendencias(grupo),
        "grupo": [c.get("name", "") for c in grupo],
        # Quem mais está devendo escolha: a tela avisa sem fazer o jogador
        # abrir um por um.
        "devendo": [c.get("name", "") for c in grupo if _escolhas_pendentes(c)],
        "personagem": {
            "nome":         alvo.get("name", ""),
            "classe":       s.get("classe", ""),
            "raca":         s.get("raca", ""),
            "nivel":        nivel,
            "xp":           xp,
            "xp_proximo":   prox,
            "xp_pct":       max(0, min(100, round((xp - base) / faixa * 100))),
            "vida_max":     int(s.get("vida_max", 0) or 0),
            "ca":           int(s.get("ca", 10) or 10),
            "proficiencia": int(s.get("proficiencia", 2) or 2),
            "atributos": [
                {"chave": a, "nome": _ATRIBUTO_PT[a],
                 "sigla": _ATRIBUTO_SIGLA[a],
                 "valor": int(s.get(a, 10) or 10),
                 "mod": _modifier(int(s.get(a, 10) or 10))}
                for a in _ATRIBUTOS
            ],
            "habilidades": [h.get("nome", "") for h in (alvo.get("habilidades") or [])],
            "escolhas_feitas": dict(s.get("feature_choices") or {}),
        },
        "pendencias": _escolhas_pendentes(alvo),
    }


def levelup_action(action: str, char: str = "", feature: str = "",
                   choice: str = "", points: int = 1,
                   distribution: dict | None = None) -> dict:
    """
    Aplica UMA escolha de subida de nível vinda da tela.

    actions: variante | asi | asi_lote | talento | subir

    'subir' é o selo "NÍVEL!" da ficha. Ele gravava o nível direto pela
    rota de edição, com PV calculados no navegador, e pulava tudo o que o
    grant_xp faz: habilidades da classe, mana, contador de incremento. Agora é
    grant_xp com 0 de XP — o laço de subida roda com o XP que a ficha já tem.

    Só despacho, igual à tela de loja: quem valida e aplica é
    set_feature_choice / apply_asi / choose_feat — as mesmas do mestre.
    """
    a = (action or "").lower().strip()
    if a == "variante":
        msg = set_feature_choice(char, feature, choice)
    elif a == "asi":
        msg = apply_asi(char, choice, points)
    elif a == "asi_lote":
        msg = apply_asi_distribution(char, distribution or {})
    elif a == "talento":
        msg = choose_feat(char, choice)
    elif a == "subir":
        alvo, err = _get_char(char, allow_dead=True)
        if not alvo:
            return {"ok": False, "message": err, "snapshot": levelup_snapshot(char)}
        sh = alvo["sheet"]
        antes = int(sh.get("nivel", 1) or 1)
        msg = grant_xp(char, 0, "subida de nível confirmada na ficha")
        if int(sh.get("nivel", 1) or 1) == antes:
            return {"ok": False,
                    "message": (f"Erro: {alvo['name']} ainda não tem XP para o nível "
                                f"{antes + 1} ({sh.get('xp', 0)}/{sh.get('xp_proximo', '?')})."),
                    "snapshot": levelup_snapshot(char)}
    else:
        return {"ok": False, "message": f"Ação '{action}' desconhecida.",
                "snapshot": levelup_snapshot(char)}

    ok = not msg.lstrip().startswith(("Aviso:", "Erro:", "Nota:"))
    return {"ok": ok, "message": msg, "snapshot": levelup_snapshot(char)}

# ===========================================================================
# FICHA DO HERÓI (leitura)
# ---------------------------------------------------------------------------
# A ficha completa de um membro do grupo para a tela: tudo o que o jogador
# precisa para decidir e rolar, calculado AQUI com as mesmas funções que o
# motor usa na hora de resolver. A tela não soma nada: o bônus de ataque é o
# de attack_roll, o de perícia é o de make_skill_check, a salvaguarda soma a
# proficiência das salvaguardas da classe (CLASS_DATA["saves"]).
#
# Não muda nada: nível, atributos e escolhas mudam pela tela de nível; itens
# pela Mochila; magias pelo Grimório. A tela só leva até elas.
# ===========================================================================

_TIPO_DE_DANO_PT = {
    "acid": "ácido", "bludgeoning": "concussão", "cold": "frio", "fire": "fogo",
    "force": "força", "lightning": "elétrico", "necrotic": "necrótico",
    "piercing": "perfurante", "poison": "veneno", "psychic": "psíquico",
    "radiant": "radiante", "slashing": "cortante", "thunder": "trovejante",
}

_PERICIAS_DA_FICHA = sorted(k for k in SKILL_ATTR_MAP if k != "lidar com animais")


def _fmt_bonus(n: int) -> str:
    return f"+{n}" if n >= 0 else str(n)


def _ataque_da_ficha(char: dict, arma: str) -> dict:
    """O ataque com uma arma equipada, com as contas de attack_roll."""
    s = char.get("sheet") or {}
    atributo, mod = _weapon_attr(arma, s)
    prof = int(s.get("proficiencia", _proficiency_bonus(int(s.get("nivel", 1) or 1))) or 2)
    distancia = _arma_de_tiro(arma)
    versatil = _versatil_a_duas_maos(char, arma)
    duas_maos = _arma_de_duas_maos(arma) or bool(versatil)
    estilo = _get_feature_choice(char, "Estilo de Combate")
    bonus_acerto, bonus_dano, notas = 0, 0, []
    if estilo == "Arquearia" and distancia:
        bonus_acerto = 2
        notas.append("Arquearia: +2 no acerto")
    elif (estilo == "Duelo" and not distancia and not duas_maos
          and not (s.get("equipamentos") or {}).get("arma_secundaria")):
        bonus_dano = 2
        notas.append("Duelo: +2 no dano")
    elif estilo == "Grande Arma" and not distancia and duas_maos:
        notas.append("Grande Arma: rola de novo 1 e 2 no dano")
    critico = _crit_threshold(char)
    if critico < 20:
        notas.append(f"crítico com {critico} ou mais")

    dado = ""
    dados = _npc_attack_dice(s, arma) or versatil or _fetch_weapon_data(arma)
    if versatil:
        notas.append("nas duas mãos")
    magico = _bonus_magico_da_arma(char, arma)
    if magico:
        bonus_acerto += magico
        bonus_dano += magico
        notas.append(f"+{magico} mágica")
    if dados:
        n, faces = dados
        extra = mod + bonus_dano
        dado = f"{n}d{faces}" + (f"{'+' if extra >= 0 else '-'}{abs(extra)}" if extra else "")
    tipo = _weapon_damage_type(arma)
    return {
        "arma": arma,
        "atributo": _ATRIBUTO_SIGLA.get(atributo, atributo.upper()),
        "acerto": _fmt_bonus(mod + prof + bonus_acerto),
        "dano": dado,
        "tipo": _TIPO_DE_DANO_PT.get(tipo, ""),
        "alcance": "à distância" if distancia else "corpo a corpo",
        "notas": notas,
    }


def hero_snapshot(char_name: str = "") -> dict:
    """Ficha de leitura de um membro do grupo para a tela (JSON-serializável)."""
    grupo = _grupo_com_ficha()
    alvo = None
    if char_name:
        alvo = next((c for c in grupo
                     if _norm_txt(c.get("name", "")) == _norm_txt(char_name)), None)
    base = {"tem_personagem": bool(alvo), "grupo": [c.get("name", "") for c in grupo],
            "personagem": None}
    if not alvo:
        return base

    s = alvo["sheet"]
    classe = (s.get("classe") or "").lower().strip()
    nivel = int(s.get("nivel", 1) or 1)
    prof = int(s.get("proficiencia", _proficiency_bonus(nivel)) or 2)
    xp = int(s.get("xp", 0) or 0)
    prox = int(s.get("xp_proximo", 0) or 0)
    piso = XP_THRESHOLDS[nivel - 1] if 0 < nivel <= len(XP_THRESHOLDS) else 0
    saves_da_classe = set(CLASS_DATA.get(classe, {}).get("saves", []))

    atributos = []
    for a in _ATRIBUTOS:
        valor = int(s.get(a, 10) or 10)
        mod = _modifier(valor)
        proficiente = a in saves_da_classe
        atributos.append({
            "chave": a, "nome": _ATRIBUTO_PT[a], "sigla": _ATRIBUTO_SIGLA[a],
            "valor": valor, "mod": _fmt_bonus(mod),
            "salvaguarda": _fmt_bonus(mod + (prof if proficiente else 0)),
            "salvaguarda_proficiente": proficiente,
        })

    pericias = []
    for nome in _PERICIAS_DA_FICHA:
        atributo = SKILL_ATTR_MAP[nome]
        proficiente = _proficiente_na_pericia(s, nome)
        bonus = _modifier(int(s.get(atributo, 10) or 10)) + (prof if proficiente else 0)
        pericias.append({"nome": nome, "sigla": _ATRIBUTO_SIGLA[atributo],
                         "bonus": _fmt_bonus(bonus), "proficiente": proficiente,
                         "_valor": bonus})
    percepcao = next((p["_valor"] for p in pericias if p["nome"] == "percepção"), 0)
    for p in pericias:
        p.pop("_valor")

    equip = s.get("equipamentos") or {}
    ataques = [_ataque_da_ficha(alvo, equip[slot])
               for slot in ("arma_principal", "arma_secundaria") if equip.get(slot)]

    condicoes = []
    for c in (s.get("condicoes") or []):
        if isinstance(c, dict) and c.get("nome"):
            condicoes.append({"nome": c["nome"], "duracao": c.get("duracao") or 0})
        elif isinstance(c, str) and c:
            condicoes.append({"nome": c, "duracao": 0})

    def _tipos(campo):
        entradas = _traits_lookup(s, campo)
        return sorted({_TIPO_DE_DANO_PT.get(tp, tp) for e in entradas for tp in e.get("tipos", [])})

    restantes, maximo = _reserva_de_dados(s)
    estado, carga, cap = _estado_de_carga(alvo)
    vida = int(s.get("vida_atual", 0) or 0)
    conc = s.get("concentracao") or {}

    base["personagem"] = {
        "nome": alvo.get("name", ""),
        "classe": s.get("classe", ""), "raca": s.get("raca", ""),
        "nivel": nivel, "xp": xp, "xp_proximo": prox,
        "xp_pct": max(0, min(100, round((xp - piso) / max(1, prox - piso) * 100))),
        "pode_subir": bool(prox) and xp >= prox and nivel < 20,
        "escolhas_pendentes": len(_escolhas_pendentes(alvo)),
        "escolhas": dict(s.get("feature_choices") or {}),
        "descricao": alvo.get("description", "") or "",
        "tracos": alvo.get("traits", "") or "",
        "vida": {"atual": vida, "max": int(s.get("vida_max", 0) or 0),
                 "teto": _hp_max_efetivo(s), "temp": _temp_hp(s)},
        "mana": {"atual": int(s.get("mana_atual", 0) or 0), "max": int(s.get("mana_max", 0) or 0)},
        "ca": int(s.get("ca", 10) or 10),
        "proficiencia": _fmt_bonus(prof),
        "conjuracao": _conjuracao(s),
        "deslocamento": _deslocamento(alvo),
        "iniciativa": _fmt_bonus(_modifier(int(s.get("destreza", 10) or 10))),
        "percepcao_passiva": 10 + percepcao,
        "dados_de_vida": {"restantes": restantes, "max": maximo, "dado": f"d{_dado_de_vida(s)}"},
        "exaustao": _exaustao(s),
        "testes_de_morte": ({"sucessos": int(s.get("death_saves_sucessos", 0) or 0),
                             "falhas": int(s.get("death_saves_falhas", 0) or 0)}
                            if vida == 0 else None),
        "concentracao": conc.get("magia", "") if isinstance(conc, dict) else "",
        "condicoes": condicoes,
        "efeitos": [e.get("nome", "") for e in _efeitos(s)],
        "defesas": {"resistencias": _tipos("resistencias"), "imunidades": _tipos("imunidades"),
                    "vulnerabilidades": _tipos("vulnerabilidades")},
        "atributos": atributos,
        "pericias": pericias,
        "ataques": ataques,
        # Os slots de item mágico só entram ocupados, como na Mochila.
        "equipados": [{"rotulo": _ROTULO_DO_SLOT[slot], "item": equip.get(slot) or ""}
                      for slot in _SLOTS if slot in _SLOTS_BASICOS or equip.get(slot)],
        "sintonizados": [n for n in s.get("sintonizados") or [] if isinstance(n, str)],
        "moedas": {"ouro": int(s.get("ouro", 0) or 0), "prata": int(s.get("prata", 0) or 0),
                   "cobre": int(s.get("cobre", 0) or 0)},
        "carga": {"kg": carga, "capacidade": cap, "estado": estado},
        "itens": sum(1 for i in (alvo.get("inventario") or []) if isinstance(i, dict)),
        "habilidades": [{"nome": h.get("nome", ""), "descricao": h.get("descricao", "") or "",
                         "custo_mana": int(h.get("custo_mana", 0) or 0), "dado": h.get("dado", "") or ""}
                        for h in (alvo.get("habilidades") or []) if isinstance(h, dict)],
        "conjura": _max_mana_for(classe, nivel) > 0,
    }
    return base


# ===========================================================================
# CARGA E LOJA
# ---------------------------------------------------------------------------
# O inventário era uma lista sem peso e sem preço: dava para carregar oito
# armaduras de placas e uma bigorna, e "comprar" era o mestre digitar um
# número de ouro de cabeça. Duas consequências chatas — saque nunca era uma
# ESCOLHA (leva tudo), e o preço de um item variava conforme o humor da cena.
#
# PESO e PREÇO vêm do compêndio do SRD (rpg/itens.py) quando o item existe
# lá, e de uma tabela curta para o resto. Em quilos e em peças de cobre: a
# mesa é em português, e uma tocha custa 1 pc, não 1 po.
#
# CAPACIDADE segue o 5e: FOR × 7,5 kg. Acima da metade disso o personagem
# fica SOBRECARREGADO (desvantagem em testes e ataques de FOR/DES/CON);
# acima do total, não anda.
# ===========================================================================

_LB_PARA_KG = 0.4536

# Aproximação para o que não está no SRD ("Poção Estranha", "Grimório do
# Mestre Vhar"): só o que aparece de verdade numa mesa.
_PESO_PADRAO_KG = {
    "poção": 0.25, "pocao": 0.25, "frasco": 0.25, "ampola": 0.25,
    "pergaminho": 0.05, "rolo": 0.05, "livro": 2.3, "grimório": 1.4,
    "corda": 4.5, "tocha": 0.5, "lampião": 0.9, "lanterna": 0.9,
    "ração": 0.9, "racao": 0.9, "odre": 2.3, "saco": 0.2,
    "chave": 0.05, "moeda": 0.01, "gema": 0.01, "anel": 0.02,
    "amuleto": 0.5, "escudo": 2.7, "elmo": 1.4, "manto": 1.8,
    "armadura": 9.0, "espada": 1.4, "adaga": 0.5, "arco": 0.9,
    "machado": 2.0, "martelo": 1.4, "lança": 1.4, "besta": 2.3,
    "flecha": 0.05, "virote": 0.07,
}


def _peso_do_item(item: dict) -> float:
    """
    Peso de UMA unidade, em kg, nesta ordem:

        1. o que o mestre gravou no item;
        2. o compêndio do SRD (rpg/itens.py): o item, ou a arma ou armadura
           de que ele é feito ("Espada Longa +1" pesa a espada longa);
        3. a tabela de aproximação, para o que não está no SRD;
        4. 0,5 kg — pequeno e honesto, não faz a mochila estourar sozinha.

    Nada aqui vai à rede. Antes, o 3º passo era o Open5e: a Mochila e a Loja
    passavam pelo inventário inteiro e cada item desconhecido custava até duas
    consultas de 4 s, entre o jogador e a tela.
    """
    if item.get("peso") is not None:
        try:
            return max(0.0, float(item["peso"]))
        except (TypeError, ValueError):
            pass

    bruto = item.get("nome", "")
    do_srd = _itens.peso_kg(bruto)
    if do_srd is not None:
        return do_srd

    nome = _norm_txt(bruto)
    for termo, kg in _PESO_PADRAO_KG.items():
        if _norm_txt(termo) in nome:
            return kg
    return 0.5


def _capacidade_kg(sheet: dict) -> float:
    """Capacidade de carga do 5e: FOR × 15 lb, em quilos."""
    return round(int(sheet.get("forca", 10) or 10) * 15 * _LB_PARA_KG, 1)


def _carga_atual(char: dict) -> float:
    total = 0.0
    for item in (char.get("inventario") or []):
        if not isinstance(item, dict):
            continue
        total += _peso_do_item(item) * max(0, int(item.get("qtd", 1) or 1))
    return round(total, 2)


def _estado_de_carga(char: dict) -> tuple[str, float, float]:
    """('livre'|'sobrecarregado'|'imovel', carga, capacidade)."""
    sheet = char.get("sheet") or {}
    carga = _carga_atual(char)
    cap   = _capacidade_kg(sheet)
    if carga > cap:
        return "imovel", carga, cap
    if carga > cap / 2:
        return "sobrecarregado", carga, cap
    return "livre", carga, cap


def check_encumbrance(char_name: str) -> str:
    """
    Quanto o personagem está carregando e o que isso custa.

    Acima de METADE da capacidade: sobrecarregado (desvantagem em ataques e
    testes de Força, Destreza e Constituição). Acima do total: não anda.

    Args:
        char_name: Nome do personagem.
    """
    char, err = _get_char(char_name, allow_dead=True)
    if not char:
        return err
    estado, carga, cap = _estado_de_carga(char)
    linhas = [f"{char['name']}: **{carga:.1f} kg** de {cap:.1f} kg "
              f"(FOR {(char.get('sheet') or {}).get('forca', 10)}) — {estado}"]
    if estado == "sobrecarregado":
        linhas.append("   Desvantagem em ataques e testes de FOR/DES/CON.")
    elif estado == "imovel":
        linhas.append("   Carga acima da capacidade — não consegue se mover.")
    pesados = sorted(
        ((_peso_do_item(i) * int(i.get("qtd", 1) or 1), i) for i in (char.get("inventario") or [])
         if isinstance(i, dict)),
        key=lambda par: par[0], reverse=True)[:5]
    if pesados:
        linhas.append("   Mais pesados:")
        for kg, i in pesados:
            if kg <= 0:
                continue
            q = int(i.get("qtd", 1) or 1)
            linhas.append(f"     {kg:5.1f} kg  {i.get('nome')}" + (f" ×{q}" if q > 1 else ""))
    return "\n".join(linhas)


# ── Mochila ────────────────────────────────────────────────────────────────
# A tela junta o que estava espalhado em três ferramentas e no editor livre:
# o que está no corpo (e a CA que isso dá), o que está na mochila (e o peso),
# e o que ainda não foi conferido no SRD. Como nas outras telas, ela só
# despacha: quem equipa, larga e identifica são equip_item, unequip_item,
# remove_item e identify_item.

_ROTULO_DO_SLOT = {
    "armadura": "Armadura", "escudo": "Escudo", "arma_principal": "Mão principal",
    "arma_secundaria": "Mão secundária", "amuleto": "Pescoço",
    "anel_1": "Anel", "anel_2": "Segundo anel", "capa": "Capa ou manto",
    "botas": "Pés", "luvas": "Mãos e pulsos", "cabeca": "Cabeça", "cinto": "Cintura",
}
_TIPO_DE_ARMADURA = {"full": "leve", "cap2": "média", "none": "pesada", "shield": "escudo"}


def _a_identificar(item: dict) -> bool:
    """
    Item mágico do SRD que o grupo ainda não estudou, ou item que parece
    mágico e nunca foi conferido. add_item confere na entrada (e grava
    `custom` e `srd`); item vindo do editor, do wizard ou de saque antigo não
    passou por lá.
    """
    if item.get("identificado"):
        return False
    if item.get("srd"):
        return True
    if "custom" in item:
        return False
    return _looks_magic(item.get("nome", ""), item.get("descricao", ""))


def _ca_se_equipar(char: dict, nome: str, slot: str) -> int | None:
    """
    CA que o personagem teria com o item no slot — a prévia do botão.
    Só para o que está na tabela de armaduras: prévia não pode ir à rede.
    """
    if slot not in ("armadura", "escudo") or not _armadura_na_tabela(nome):
        return None
    copia = copy.deepcopy(char)
    copia["sheet"].setdefault("equipamentos", {})[slot] = nome
    _recalculate_ca(copia)
    return copia["sheet"]["ca"]


def _item_identificado(dono: dict, nome: str) -> bool:
    """O item da mochila com este nome já foi identificado (ou nunca precisou)?"""
    item = _item_do_inventario(dono, nome)
    return not item or not _a_identificar(item)


def _sintonia_na_mochila(dono: dict, item: dict) -> dict | None:
    """
    O botão de sintonizar do item, ou None quando o item não pede sintonia:
    {sintonizado, pode, motivo, efeito}. O efeito só aparece depois de
    identificado: sintonizar também identifica.
    """
    magico = _magico_por_nome(item.get("nome", ""))
    if not magico or not magico.get("sintonizacao"):
        return None
    s = dono.get("sheet") or {}
    sintonizado = _esta_sintonizado(s, item["nome"])
    motivo = ""
    if not sintonizado:
        motivo = _quem_pode_sintonizar(dono, magico)
        usados = len([n for n in s.get("sintonizados") or [] if isinstance(n, str)])
        if not motivo and usados >= _LIMITE_DE_SINTONIA:
            motivo = f"já sintonizado com {_LIMITE_DE_SINTONIA} itens: desfaça uma sintonia antes"
        if not motivo and (memory.campaign.get("combat_state") or {}).get("is_active"):
            motivo = "sintonizar leva um descanso curto; não dá no meio da luta"
    return {"sintonizado": sintonizado, "pode": not motivo, "motivo": motivo,
            "efeito": (magico.get("efeito") or {}).get("nota", "") if not _a_identificar(item) else ""}


def _uso_na_mochila(dono: dict, item: dict) -> dict | None:
    """
    O botão de usar do item na Mochila, fora do combate. None quando o item
    não é consumível. A regra é a da tela tática (_efeito_de_item); o que
    muda é que fora do combate não há economia de ações nem zonas.
    """
    ficha = _efeito_de_item(item.get("nome", ""))
    if not ficha:
        return None
    efeito = ficha["efeito"]
    rotulo = "Beber" if efeito in ("cura", "resistencia", "pocao") else "Usar"
    uso = {"efeito": efeito, "rotulo": rotulo, "pode": True, "motivo": "",
           "detalhe": ficha.get("rotulo", ""), "alvos": []}
    if efeito == "magia":
        restam = ""
        if ficha["uso"].get("tipo") == "cargas":
            restam = f" ({_cargas_do_item(item, ficha['uso'])}/{ficha['uso'].get('cargas')} cargas)"
        uso.update(pode=False, rotulo="Conjurar", detalhe=ficha.get("rotulo", "") + restam,
                   motivo="Conjura pela tela tática (botão Habilidade), ou peça ao mestre fora da luta.")
        return uso
    cs = memory.campaign.get("combat_state") or {}
    if cs.get("is_active"):
        uso.update(pode=False, motivo="Em combate, use pela tela tática: custa Ação ou Ação Bônus.")
    elif (dono.get("status") or "").lower() in ("inconsciente", "dormindo", "estabilizado"):
        uso.update(pode=False, motivo=(f"{dono.get('name', '')} está {dono.get('status')}: "
                                       f"outro do grupo precisa dar a poção pela mochila dele."))
    elif efeito == "desconhecido":
        uso.update(pode=False, motivo=("O motor não conhece o efeito deste item. "
                                       "Descreva o uso no chat para o mestre resolver."))
    elif efeito == "arremesso":
        uso.update(pode=False, motivo="Arremesso contra um alvo: só em combate, pela tela tática.")
    elif efeito == "estabilizar":
        caidos = [c.get("name", "") for c in _grupo_com_ficha()
                  if int((c.get("sheet") or {}).get("vida_atual", 0) or 0) <= 0
                  and (c.get("status") or "").lower() not in ("morto", "estabilizado")]
        uso["alvos"] = caidos
        if not caidos:
            uso.update(pode=False, motivo="Ninguém do grupo está caído morrendo.")
    elif efeito == "pocao" and ficha["uso"].get("duracao") == "1min":
        uso.update(pode=False, motivo="Dura um minuto: beba na luta, pela tela tática.")
    elif efeito == "cura":
        # Fora do combate não há zonas: qualquer um do grupo que não esteja morto.
        eu = dono.get("name", "")
        outros = [c.get("name", "") for c in _grupo_com_ficha()
                  if (c.get("status") or "").lower() != "morto"
                  and memory.char_key(c.get("name", "")) != memory.char_key(eu)]
        uso["alvos"] = [eu] + outros
    return uso


def _usar_na_mochila(char: str, item_nome: str, alvo_nome: str = "") -> str:
    """Aplica o uso de um consumível fora do combate. Texto com o prefixo de recusa."""
    dono, err = _get_char(char, allow_dead=False)
    if not dono:
        return err
    inv = dono.get("inventario") or []
    slot_inv = next((i for i in inv if isinstance(i, dict)
                     and _norm_txt(i.get("nome", "")) == _norm_txt(item_nome)
                     and int(i.get("qtd", 1) or 1) > 0), None)
    if not slot_inv:
        return f"Erro: {dono['name']} não tem '{item_nome}'."
    uso = _uso_na_mochila(dono, slot_inv)
    if not uso:
        return f"Aviso: '{slot_inv['nome']}' não é algo que se use assim."
    if not uso["pode"]:
        return f"Aviso: {slot_inv['nome']}: {uso['motivo']} O item não foi gasto."

    ficha = _efeito_de_item(slot_inv["nome"])
    s = dono["sheet"]

    if ficha["efeito"] == "cura":
        alvo_nome = (alvo_nome or dono["name"]).strip()
        if memory.char_key(alvo_nome) not in {memory.char_key(n) for n in uso["alvos"]}:
            return f"Aviso: {alvo_nome} não pode receber {slot_inv['nome']} agora."
        recv = memory.campaign["characters"].get(memory.char_key(alvo_nome))
        st = recv["sheet"]
        n_d, sides, bonus = ficha["dado"]
        rolls = [random.randint(1, sides) for _ in range(n_d)]
        cura = sum(rolls) + bonus
        antes = int(st.get("vida_atual", 0) or 0)
        teto = _hp_max_efetivo(st)
        st["vida_atual"] = max(antes, min(teto, antes + cura))
        depois = st["vida_atual"]
        if antes == 0 and depois > 0 and (recv.get("status") or "").lower() in ("inconsciente", "estabilizado"):
            recv["status"] = "vivo"
            st["death_saves_sucessos"] = 0
            st["death_saves_falhas"] = 0
        quem = "bebeu" if recv is dono else f"deu a {recv['name']}"
        nota_teto = f" (teto {teto} pela exaustão)" if teto < int(st.get("vida_max", 0) or 0) else ""
        msg = (f"{dono['name']} {quem} {slot_inv['nome']}: {n_d}d{sides} "
               f"[{' + '.join(str(r) for r in rolls)}] +{bonus} = +{cura} PV "
               f"• {recv['name']} {antes}→{depois}/{int(st.get('vida_max', 0) or 0)}{nota_teto}")
    elif ficha["efeito"] == "resistencia":
        tipo = ficha["tipo_dano"]
        pt = _TIPO_DANO_ITEM_PT.get(tipo, tipo)
        _dar_efeito(s, {"nome": f"Resistência a {pt}", "resistencia": tipo,
                        "origem": slot_inv["nome"], "ate_hora": _agora_em_horas() + 1})
        msg = f"{dono['name']} bebeu {slot_inv['nome']}: resistência a dano de {pt} por 1 hora."
    elif ficha["efeito"] == "antitoxina":
        _dar_efeito(s, {"nome": "Antitoxina", "antitoxina": True,
                        "descricao": "vantagem em salvaguardas contra Envenenado",
                        "origem": slot_inv["nome"], "ate_hora": _agora_em_horas() + 1})
        msg = f"{dono['name']} tomou {slot_inv['nome']}: vantagem contra Envenenado por 1 hora."
    elif ficha["efeito"] == "pocao":
        msg = _beber_pocao(dono, slot_inv["nome"], ficha["uso"])
    elif ficha["efeito"] == "estabilizar":
        recv = memory.campaign["characters"].get(memory.char_key((alvo_nome or "").strip()))
        if not recv or recv.get("name") not in uso["alvos"]:
            return f"Aviso: {alvo_nome or 'ninguém'} não está caído morrendo. O kit não foi gasto."
        msg = _estabilizar_com_kit(dono, recv, slot_inv, ficha)
        memory.save_campaign()
        return msg
    else:
        return f"Aviso: {slot_inv['nome']}: não dá para usar fora do combate."

    slot_inv["qtd"] = int(slot_inv.get("qtd", 1) or 1) - 1
    if slot_inv["qtd"] <= 0:
        inv.remove(slot_inv)
    memory.save_campaign()
    return msg


def inventory_snapshot(char_name: str = "") -> dict:
    """Estado da Mochila para a tela (JSON-serializável)."""
    grupo = _grupo_com_ficha()
    alvo = None
    if char_name:
        alvo = next((c for c in grupo
                     if _norm_txt(c.get("name", "")) == _norm_txt(char_name)), None)
    alvo = alvo or (grupo[0] if grupo else None)
    base = {"tem_personagem": bool(alvo), "grupo": [c.get("name", "") for c in grupo],
            "personagem": None}
    if not alvo:
        return base

    s = alvo["sheet"]
    equip = s.get("equipamentos") or {}
    estado, carga, cap = _estado_de_carga(alvo)

    equipados = []
    for slot in _SLOTS:
        nome = equip.get(slot)
        detalhe = ""
        dados = _armadura_na_tabela(nome) if nome else None
        if dados:
            # "base": a CA do cabeçalho já soma a Destreza, e "CA 13" ao lado de
            # uma CA 14 parecia conta errada.
            detalhe = (f"+{dados['ca_base'] + dados['bonus']} CA" if dados["dex_bonus"] == "shield"
                       else f"CA base {dados['ca_base']} · {_TIPO_DE_ARMADURA.get(dados['dex_bonus'], '')}"
                       + (f" · +{dados['bonus']} mágica" if dados["bonus"] else ""))
        if not dados and nome:
            magico_s = _magico_por_nome(nome)
            if magico_s and (magico_s.get("efeito") or {}).get("nota") and _item_identificado(alvo, nome):
                ativo = any(_norm_txt(n) == _norm_txt(nome) for n, _m in _itens_ativos(s))
                detalhe = (magico_s["efeito"]["nota"] if ativo
                           else "sem efeito até sintonizar")
        equipados.append({"slot": slot, "rotulo": _ROTULO_DO_SLOT[slot],
                          # Os slots de item mágico só aparecem ocupados.
                          "basico": slot in _SLOTS_BASICOS,
                          "item": nome or "", "detalhe": detalhe,
                          # Equipado sem estar na mochila: ficha antiga ou do
                          # editor. Continua valendo; a tela só avisa.
                          "fora_da_mochila": bool(nome) and not any(
                              isinstance(i, dict) and _norm_txt(i.get("nome", "")) == _norm_txt(nome)
                              for i in (alvo.get("inventario") or []))})

    itens = []
    ca_atual = int(s.get("ca", 10) or 10)
    for it in (alvo.get("inventario") or []):
        if not isinstance(it, dict):
            continue
        nome = it.get("nome", "")
        qtd = int(it.get("qtd", 1) or 1)
        peso = _peso_do_item(it)
        em = _slots_ocupados_por(equip, nome)
        opcoes = []
        for slot in _slots_para_item(nome):
            if slot in em:
                continue
            # Sem unidade livre, o botão não aparece: a regra é do equip_item,
            # aqui só não se oferece o clique que ele vai recusar.
            if len(em) >= qtd:
                continue
            opcoes.append({"slot": slot, "rotulo": _ROTULO_DO_SLOT[slot],
                           "ca_previa": _ca_se_equipar(alvo, nome, slot),
                           "substitui": equip.get(slot) or ""})
        itens.append({
            "nome": nome, "qtd": qtd, "descricao": it.get("descricao", ""),
            "peso": round(peso, 2), "peso_total": round(peso * qtd, 2),
            "custom": bool(it.get("custom")),
            # O nome oficial, em português, só depois de identificado.
            "nome_srd": ((it.get("srd") or {}).get("nome") or "") if it.get("identificado") else "",
            "equipado_em": [_ROTULO_DO_SLOT[x] for x in em if x in _ROTULO_DO_SLOT],
            "opcoes_de_equipar": opcoes,
            "a_identificar": _a_identificar(it),
            # Item de nome mágico que entrou sem descrição. A marca existia só
            # para cobrar o MESTRE (server._itens_sem_balanco) e o jogador
            # carregava a coisa sem nunca saber que ninguém declarou o que ela
            # faz. Na Mochila isso vira pergunta em cena — que é o jeito de
            # resolver, porque quem responde é o mestre.
            "efeito_desconhecido": bool(it.get("efeito_desconhecido")),
            "uso": _uso_na_mochila(alvo, it),
            "sintonia": _sintonia_na_mochila(alvo, it),
        })

    base["personagem"] = {
        "nome": alvo.get("name", ""), "classe": s.get("classe", ""),
        "nivel": int(s.get("nivel", 1) or 1), "forca": int(s.get("forca", 10) or 10),
        "ca": ca_atual,
        "moedas": {"ouro": int(s.get("ouro", 0) or 0), "prata": int(s.get("prata", 0) or 0),
                   "cobre": int(s.get("cobre", 0) or 0)},
        "carga": {"kg": carga, "capacidade": cap, "estado": estado,
                  "metade": round(cap / 2, 1)},
        "sintonizados": {"usados": len([n for n in s.get("sintonizados") or [] if isinstance(n, str)]),
                         "limite": _LIMITE_DE_SINTONIA},
        "equipados": equipados,
        "itens": itens,
    }
    return base


def inventory_action(action: str, char: str = "", item: str = "", slot: str = "",
                     alvo: str = "") -> dict:
    """
    Aplica UMA intenção da Mochila.

    actions: equipar | desequipar | largar | identificar | usar | sintonizar | dessintonizar

    Só despacho: equip_item, unequip_item, remove_item (uma unidade) e
    identify_item — as mesmas ferramentas do mestre. "usar" aplica um
    consumível fora do combate com a ficha da tela tática (_efeito_de_item).
    """
    a = (action or "").lower().strip()
    if a == "usar":
        msg = _usar_na_mochila(char, item, alvo)
    elif a == "sintonizar":
        # Um descanso curto com o item: a hora passa no relógio, como no
        # "Identificar" (attune_item, a ferramenta do mestre, não mexe nele).
        msg = attune_item(char, item)
        if not msg.lstrip().startswith(("Aviso:", "Erro:", "Nota:")):
            avancar_minutos(60, f"{char} se sintonizou com {item}")
    elif a == "dessintonizar":
        msg = end_attunement(char, item)
    elif a == "equipar":
        msg = equip_item(char, item, slot)
    elif a == "desequipar":
        msg = unequip_item(char, slot)
    elif a == "largar":
        msg = remove_item(char, item, 1)
    elif a == "identificar":
        # Identificar custa o que custa no 5e: a poção, um gole; o resto, um
        # descanso curto estudando o item (1 hora no relógio). O botão era de
        # graça e a hora não passava.
        dono_i = next((c for c in _grupo_com_ficha()
                       if _norm_txt(c.get("name", "")) == _norm_txt(char)), None)
        gravado_i = _item_do_inventario(dono_i, item) if dono_i else None
        if gravado_i is None:
            return {"ok": False, "message": f"Erro: {char} não tem '{item}'.",
                    "snapshot": inventory_snapshot(char)}
        pocao = ((gravado_i.get("srd") or {}).get("tipo") == "poção"
                 or bool(_efeito_de_item(gravado_i.get("nome", ""))))
        if not pocao and _em_combate():
            return {"ok": False,
                    "message": "Aviso: estudar um item leva uma hora; não dá no meio da luta.",
                    "snapshot": inventory_snapshot(char)}
        msg = identify_item(char, item)
        como = ""
        if not msg.lstrip().startswith("Erro:"):
            if pocao:
                como = f"{dono_i['name']} provou um gole."
            else:
                avancar_minutos(60, f"{dono_i['name']} estudou {gravado_i['nome']}")
                como = f"{dono_i['name']} estudou o item por uma hora."
        # "Aviso: não está no SRD" é resultado da conferência, não recusa.
        ok = not msg.lstrip().startswith("Erro:")
        # O que foi achado vem do item gravado, não do texto do mestre: a tela
        # monta a mensagem em português sem interpretar markdown.
        dono = next((c for c in _grupo_com_ficha()
                     if _norm_txt(c.get("name", "")) == _norm_txt(char)), None)
        gravado = next((i for i in ((dono or {}).get("inventario") or [])
                        if isinstance(i, dict) and _norm_txt(i.get("nome", "")) == _norm_txt(item)),
                       {})
        srd_i = gravado.get("srd") or {}
        resultado = {"item": item, "consultou": ok, "como": como,
                     "encontrado": ok and bool(gravado.get("nome_srd")),
                     "nome_srd": srd_i.get("nome", "") if ok else "",
                     "tipo": srd_i.get("tipo", "") if ok else "",
                     "raridade": srd_i.get("raridade", "") if ok else "",
                     "sintonizacao": bool(srd_i.get("sintonizacao")) if ok else False}
        return {"ok": ok, "message": msg, "resultado": resultado,
                "snapshot": inventory_snapshot(char)}
    else:
        return {"ok": False, "message": f"Erro: Ação '{action}' desconhecida.",
                "snapshot": inventory_snapshot(char)}

    ok = not msg.lstrip().startswith(("Aviso:", "Erro:", "Nota:"))
    return {"ok": ok, "message": msg, "snapshot": inventory_snapshot(char)}


# ── Loja ───────────────────────────────────────────────────────────────────

# ── Loja gerada pelo tipo e pelo porte do lugar ────────────────────────────
# O mestre digitava o estoque inteiro de cabeça, e uma aldeia vendia espada
# +3. Com `kind` e `size`, open_shop monta o estoque do SRD: o que uma forja,
# um armazém, um boticário, um templo, uma loja arcana ou um joalheiro têm,
# e quanto de mágico cabe no porte do lugar.
_PORTES = {
    # porte: (raridade máxima à venda, itens mágicos (mín, máx), bolsa do lojista em po)
    "vilarejo":  ("comum", (0, 1), 50),
    "vila":      ("comum", (1, 2), 200),
    "cidade":    ("incomum", (2, 4), 1000),
    "metropole": ("raro", (4, 7), 5000),
}
_APELIDOS_DE_PORTE = {"aldeia": "vilarejo", "povoado": "vilarejo", "vilarejo": "vilarejo",
                      "vila": "vila", "cidade pequena": "vila", "cidade": "cidade",
                      "metropole": "metropole", "capital": "metropole", "cidade grande": "metropole"}
_SIMPLES_SO = ("club", "dagger", "handaxe", "javelin", "light-hammer", "mace", "quarterstaff",
               "sickle", "spear", "crossbow-light", "dart", "shortbow", "sling")
_ARMADURAS_POR_PORTE = {
    "vilarejo": ("padded-armor", "leather-armor", "hide-armor", "shield"),
    "vila": ("padded-armor", "leather-armor", "studded-leather-armor", "hide-armor", "chain-shirt",
             "scale-mail", "ring-mail", "chain-mail", "shield"),
    "cidade": ("padded-armor", "leather-armor", "studded-leather-armor", "hide-armor", "chain-shirt",
               "scale-mail", "breastplate", "half-plate", "ring-mail", "chain-mail", "splint-armor",
               "shield"),
}
_ARMADURAS_POR_PORTE["metropole"] = _ARMADURAS_POR_PORTE["cidade"] + ("plate-armor",)
# Estoque comum de cada tipo: (chave do compêndio, quantidade; 99 = sempre tem).
_ESTOQUE_COMUM = {
    "armazem": [("backpack", 99), ("bedroll", 99), ("blanket", 99), ("candle", 99), ("chalk-1-piece", 99),
                ("crowbar", 5), ("grappling-hook", 3), ("hammer", 5), ("lamp", 5), ("lamp-oil-flask", 99),
                ("lantern-hooded", 3), ("mess-kit", 99), ("piton", 99), ("pole-10-foot", 5),
                ("pouch", 99), ("rations-1-day", 99), ("rope-hempen-50-feet", 99), ("sack", 99),
                ("tinderbox", 99), ("torch", 99), ("waterskin", 99), ("whetstone", 99),
                ("clothes-common", 99), ("clothes-travelers", 99), ("healers-kit", 3),
                ("climbers-kit", 1), ("chain-10-feet", 3), ("lock", 2), ("manacles", 2),
                ("arrow-bow", 99), ("crossbow-bolt", 99), ("sling-bullets", 99)],
    "boticario": [("antitoxin-vial", 4), ("acid-vial", 3), ("alchemists-fire-flask", 3),
                  ("healers-kit", 3), ("herbalism-kit", 1), ("vial", 99), ("perfume-vial", 5), ("soap", 99)],
    "templo": [("holy-water-flask", 4), ("healers-kit", 3), ("amulet", 3), ("emblem", 3),
               ("reliquary", 2), ("candle", 99), ("robes", 5)],
    "arcana": [("component-pouch", 3), ("crystal", 2), ("orb", 2), ("rod", 1), ("staff", 2), ("wand", 2),
               ("spellbook", 2), ("ink-1-ounce-bottle", 5), ("ink-pen", 99),
               ("parchment-one-sheet", 99), ("case-map-or-scroll", 5)],
    "joalheiro": [("signet-ring", 3), ("jewelers-tools", 1), ("magnifying-glass", 1), ("scale-merchants", 2)],
}
_TIPOS_DE_LOJA = {"forja", "armazem", "boticario", "templo", "arcana", "joalheiro"}
_APELIDOS_DE_TIPO = {"ferreiro": "forja", "ferraria": "forja", "armeiro": "forja", "forja": "forja",
                     "armazem": "armazem", "emporio": "armazem", "mercado": "armazem", "mercador": "armazem",
                     "boticario": "boticario", "alquimista": "boticario", "herbalista": "boticario",
                     "templo": "templo", "santuario": "templo", "arcana": "arcana", "magia": "arcana",
                     "loja de magia": "arcana", "joalheiro": "joalheiro", "joalheria": "joalheiro"}


def _porte(texto: str) -> str:
    return _APELIDOS_DE_PORTE.get(_norm_txt(texto or ""), "")


def _tipo_de_loja(texto: str) -> str:
    return _APELIDOS_DE_TIPO.get(_norm_txt(texto or ""), "")


def _raridade_cabe(raridade: str, porte: str) -> bool:
    teto = _PORTES[porte][0]
    return (raridade in _ORDEM_DE_RARIDADE
            and _ORDEM_DE_RARIDADE.index(raridade) <= _ORDEM_DE_RARIDADE.index(teto))


def _linha_de_estoque(nome: str, preco: int, qtd: int, descricao: str = "") -> dict:
    return {"nome": nome, "preco_pc": int(preco), "qtd": int(qtd), "base": int(qtd), "descricao": descricao}


def _gerar_estoque(tipo: str, porte: str, semente: str) -> list[dict]:
    """
    O estoque do SRD que uma loja deste tipo tem num lugar deste porte. A
    semente (o nome da loja e a reposição) torna o sorteio repetível: a mesma
    forja, na mesma semana, tem as mesmas espadas.
    """
    from rpg import compendio
    sorte = random.Random(semente)
    comuns = _itens.comuns()
    linhas: list[dict] = []

    def comum(chave: str, qtd: int) -> None:
        e = comuns.get(chave)
        if e and e.get("preco_pc"):
            linhas.append(_linha_de_estoque(e["nome"], e["preco_pc"], qtd))

    if tipo == "forja":
        for chave, e in comuns.items():
            if e["categoria"] == "arma" and (porte != "vilarejo" or chave in _SIMPLES_SO):
                comum(chave, sorte.randint(1, 3))
        for chave in _ARMADURAS_POR_PORTE[porte]:
            comum(chave, sorte.randint(1, 2))
        for chave in ("arrow-bow", "crossbow-bolt", "sling-bullets"):
            comum(chave, 99)
    else:
        for chave, qtd in _ESTOQUE_COMUM.get(tipo, []):
            comum(chave, qtd)
    if tipo in ("boticario", "templo"):
        linhas.append(_linha_de_estoque("Poção de Cura", 5000, sorte.randint(2, 5)))

    # O que é mágico, dentro da raridade do porte.
    candidatos: list[str] = []
    if tipo == "forja":
        candidatos = [f"{comuns[k]['nome']} +1" for k in ("longsword", "shortsword", "dagger", "longbow",
                                                          "battleaxe", "warhammer", "rapier")]
        candidatos += ["Escudo +1"]
    elif tipo == "boticario":
        candidatos = [e["nome"] for e in _itens.magicos().values() if e.get("tipo") == "poção"
                      and e["chave"] not in ("potion-of-healing", "potion-of-poison")]
    elif tipo in ("templo", "arcana"):
        classe = "clérigo" if tipo == "templo" else "mago"
        for m in compendio.magias_da_classe(classe, 9):
            candidatos.append(f"Pergaminho de {m['nome']}")
        if tipo == "arcana":
            candidatos += [e["nome"] for e in _itens.magicos().values()
                           if e.get("tipo") in ("varinha", "anel", "item maravilhoso", "cajado")
                           and not e.get("sintetico")]
    elif tipo == "joalheiro":
        candidatos = [e["nome"] for e in _itens.magicos().values()
                      if e.get("tipo") == "anel" or e.get("slot") == "amuleto"]
    cabem = [n for n in candidatos if _raridade_do_item(n) and _raridade_cabe(_raridade_do_item(n), porte)
             and _preco_de_raridade_pc(n)]
    minimo, maximo = _PORTES[porte][1]
    for nome in sorte.sample(cabem, min(len(cabem), sorte.randint(minimo, maximo))):
        linhas.append(_linha_de_estoque(nome, _preco_de_raridade_pc(nome), 1))
    return linhas


_REPOSICAO_H = 7 * 24        # a loja se repõe uma vez por semana


def _repor_se_passou_a_semana(loja: dict) -> None:
    """
    Uma semana depois, a loja se repõe: a gerada sorteia o estoque da semana
    de novo; a montada à mão volta às quantidades de quando foi aberta. A
    bolsa do lojista volta a pelo menos o que ele tinha.
    """
    agora = _agora_em_horas()
    if loja.get("reposta_em") is None:
        loja["reposta_em"] = agora
        return
    semanas = (agora - int(loja["reposta_em"])) // _REPOSICAO_H
    if semanas <= 0:
        return
    loja["reposta_em"] = int(loja["reposta_em"]) + semanas * _REPOSICAO_H
    loja["semana"] = int(loja.get("semana", 0) or 0) + semanas
    if loja.get("tipo") and loja.get("porte") in _PORTES:
        manuais = [l for l in loja.get("estoque") or [] if l.get("manual")]
        loja["estoque"] = _gerar_estoque(loja["tipo"], loja["porte"],
                                         f"{_norm_txt(loja['nome'])}:{loja['semana']}") + manuais
    for linha in loja.get("estoque") or []:
        if int(linha.get("base", 0) or 0) > int(linha.get("qtd", 0) or 0):
            linha["qtd"] = int(linha["base"])
    if loja.get("bolsa_base_pc") is not None:
        loja["bolsa_pc"] = max(int(loja.get("bolsa_pc", 0) or 0), int(loja["bolsa_base_pc"]))


def _loja_daqui(loja: dict) -> bool:
    """
    O grupo está na loja? No lugar dela, dentro dele (a taverna da mesma
    cidade), ou um dos dois sem lugar definido. buy_item vendia de uma loja de
    outra cidade, sem o grupo sair do lugar.
    """
    from rpg import locais as _locais_l
    aqui = memory.campaign.get("current_location", "") or ""
    onde = loja.get("local", "") or ""
    if not aqui or not onde:
        return True
    if _norm_txt(aqui) in (_norm_txt(onde), _norm_txt(loja.get("nome", ""))):
        return True
    return _locais_l.esta_dentro(aqui, onde) or _locais_l.esta_dentro(aqui, loja.get("nome", ""))


def _lojas() -> dict:
    lojas = memory.campaign.setdefault("lojas", {})
    for loja in lojas.values():
        for linha in (loja or {}).get("estoque") or []:
            _preco_pc_da_linha(linha)
        if isinstance(loja, dict):
            _repor_se_passou_a_semana(loja)
    return lojas


# ── Atitude do lojista no preço ────────────────────────────────────────────
# A atitude já valia 1 de CD social a cada 20 pontos (social_check). No balcão
# ela não valia nada: o ferreiro que devia a vida ao grupo cobrava do mesmo
# jeito que o que tinha sido roubado por ele. Mesma escala, mesma ideia: 5% a
# cada 20 pontos, teto de 25% para os dois lados.
_PASSO_DE_PRECO = 0.05
_TETO_DE_PASSOS = 5


def _passos_de_atitude(valor: int) -> int:
    """Quantos degraus de 20 pontos, com teto — o mesmo do social_check."""
    return max(-_TETO_DE_PASSOS, min(_TETO_DE_PASSOS, int(valor) // 20))


def _dono_da_loja(loja: dict) -> dict | None:
    """O personagem dono da loja, quando ela tem um e ele existe na campanha."""
    nome = (loja or {}).get("dono", "") or ""
    if not nome:
        return None
    return memory.campaign.get("characters", {}).get(memory.char_key(nome))


def _atitude_da_loja(loja: dict) -> dict | None:
    """
    {dono, valor, rotulo, pct, compra, venda} ou None quando a loja não tem
    dono, o dono sumiu ou a atitude dele é neutra o bastante para não mexer
    em nada. `compra` e `venda` são fatores: preço pedido e preço pago.
    """
    dono = _dono_da_loja(loja)
    if not dono:
        return None
    from rpg.tools import _faixa_atitude, atitude_de
    valor  = atitude_de(dono)
    passos = _passos_de_atitude(valor)
    if not passos:
        return None
    rotulo, _conduta = _faixa_atitude(valor)
    return {
        "dono":   dono.get("name", ""),
        "valor":  valor,
        "rotulo": rotulo,
        "pct":    -passos * int(_PASSO_DE_PRECO * 100),
        "compra": 1 - passos * _PASSO_DE_PRECO,
        "venda":  1 + passos * _PASSO_DE_PRECO,
    }


# ── Pechincha ──────────────────────────────────────────────────────────────
# Barganhar era conversa solta: o jogador pedia desconto no chat e o mestre
# decidia de cabeça. Aqui é um teste de Persuasão contra o lojista, UMA vez
# por visita, e o resultado entra no preço como número.
_PECHINCHA_CD_BASE = 13
_PECHINCHA_GANHO = -10     # % no preço quando passa
_PECHINCHA_OFENSA = 5      # % quando o d20 dá 1 e o lojista se ofende


def _pechincha_valida(loja: dict) -> dict | None:
    """
    A pechincha desta visita, ou None. Sair do local encerra a conversa: o
    desconto arrancado na forja não vale quando o grupo volta semanas depois.
    """
    p = loja.get("pechincha")
    if not isinstance(p, dict):
        return None
    aqui = _norm_txt(memory.campaign.get("current_location", "") or "")
    if p.get("visita") != aqui:
        loja.pop("pechincha", None)
        return None
    return p


def _fator_de_pechincha(loja: dict) -> float:
    p = _pechincha_valida(loja)
    return 1 + (int(p.get("pct", 0) or 0) / 100) if p else 1.0


def haggle(char_name: str, shop_name: str = "") -> str:
    """
    Pechincha com o lojista: um teste de Persuasão que muda o preço da loja.

    Vale UMA vez por visita ao local. Passando, a loja cobra 10% menos;
    falhando, o preço fica como está; tirando 1 no dado, o lojista se ofende,
    cobra 5% a mais e perde um pouco da atitude. A CD sobe ou desce com a
    relação dele com o grupo, como em qualquer teste social.

    Args:
        char_name: Quem puxa a conversa.
        shop_name: Nome da loja (padrão: a loja do local atual).
    """
    char, err = _get_char(char_name)
    if not char:
        return err
    lojas = _lojas()
    loja = lojas.get(_norm_txt(shop_name)) if shop_name else None
    if not loja:
        local = _norm_txt(memory.campaign.get("current_location", "") or "")
        loja = next((l for l in lojas.values()
                     if local and local in (_norm_txt(l.get("local", "")),
                                            _norm_txt(l.get("nome", "")))), None)
    if not loja:
        return f"Aviso: Loja '{shop_name}' não encontrada."

    if not _loja_daqui(loja):
        return f"Aviso: {loja['nome']} fica em {loja.get('local')}; o grupo não está lá."
    if _pechincha_valida(loja):
        return (f"Nota: já pechincharam em {loja['nome']} nesta visita. "
                f"O lojista não vai baixar o preço de novo agora.")

    sheet = char["sheet"] or {}
    prof = int(sheet.get("proficiencia", _proficiency_bonus(int(sheet.get("nivel", 1) or 1))) or 2)
    mod = _modifier(int(sheet.get("carisma", 10) or 10))
    proficiente = _proficiente_na_pericia(sheet, "persuasão")
    bonus = mod + (prof if proficiente else 0)

    dono = _dono_da_loja(loja)
    ajuste_cd = 0
    if dono:
        from rpg.tools import atitude_de as _atitude
        ajuste_cd = -_passos_de_atitude(_atitude(dono))
    cd = max(1, _PECHINCHA_CD_BASE + ajuste_cd)

    d20 = random.randint(1, 20)
    total = d20 + bonus
    passou = total >= cd

    if d20 == 1:
        pct = _PECHINCHA_OFENSA
        fecho = f"o lojista se ofende e sobe {pct}% no preço"
        if dono:
            from rpg.tools import adjust_attitude as _mexer
            _mexer(dono.get("name", ""), -5, f"{char['name']} pechinchou de forma grosseira")
    elif passou:
        pct = _PECHINCHA_GANHO
        fecho = f"o lojista cede: {abs(pct)}% de desconto nesta visita"
    else:
        pct = 0
        fecho = "o lojista não se move do preço"

    if pct:
        loja["pechincha"] = {"pct": pct, "quem": char["name"],
                             "visita": _norm_txt(memory.campaign.get("current_location", "") or "")}
    else:
        # Falhou, mas a conversa aconteceu: não dá para tentar de novo.
        loja["pechincha"] = {"pct": 0, "quem": char["name"],
                             "visita": _norm_txt(memory.campaign.get("current_location", "") or "")}
    memory.save_campaign()

    prof_tag = f" +{prof}(prof)" if proficiente else ""
    nota_cd = ""
    if dono and ajuste_cd:
        rotulo = ""
        from rpg.tools import _faixa_atitude, atitude_de as _atitude
        rotulo, _ = _faixa_atitude(_atitude(dono))
        nota_cd = f" (base {_PECHINCHA_CD_BASE} {ajuste_cd:+d} — {dono.get('name','')} está {rotulo})"
    return (f"{char['name']} pechincha em {loja['nome']}: Persuasão d20={d20} "
            f"{bonus:+d}{prof_tag} = **{total}** vs CD {cd}{nota_cd}\n"
            f"   {'SUCESSO' if passou and d20 != 1 else 'FALHA'} — {fecho}.")


def _preco_com_atitude(preco: int, loja: dict) -> int:
    """Preço pedido por uma unidade, em cobre: a atitude do dono e a pechincha da visita."""
    ajuste = _atitude_da_loja(loja)
    fator = (ajuste["compra"] if ajuste else 1.0) * _fator_de_pechincha(loja)
    if fator == 1.0:
        return int(preco)
    return max(1, int(round(int(preco) * fator)))


def _ganho_com_atitude(tabela: int, loja: dict) -> int:
    """O que a loja paga por uma unidade, em cobre: metade da tabela, com a atitude."""
    base = max(1, int(tabela) // 2)
    ajuste = _atitude_da_loja(loja)
    if not ajuste:
        return base
    return max(1, int(round(base * ajuste["venda"])))


# Preço de item mágico pela raridade (faixas do Guia do Mestre: comum 50-100
# po, incomum 101-500, raro 501-5.000, muito raro 5.001-50.000, lendário
# 50.001+). O SRD não dá preço a item mágico, e a loja recusava vender ou
# comprar a Varinha de Teia. Consumível (poção, pergaminho, munição) custa a
# metade, como no Guia de Xanathar.
_PRECO_POR_RARIDADE_PO = {"comum": 75, "incomum": 300, "raro": 2500, "muito raro": 25000,
                          "lendário": 100000}
_ORDEM_DE_RARIDADE = ["comum", "incomum", "raro", "muito raro", "lendário", "artefato"]
# Pergaminho de magia: a raridade sai do círculo (SRD, Spell Scroll).
_RARIDADE_DO_PERGAMINHO = {0: "comum", 1: "comum", 2: "incomum", 3: "incomum", 4: "raro",
                           5: "raro", 6: "muito raro", 7: "muito raro", 8: "muito raro", 9: "lendário"}


def _raridade_do_item(nome: str) -> str:
    """A raridade de um item mágico do SRD (ou de um pergaminho de magia), ou ''."""
    magia = _magia_do_pergaminho(nome)
    if magia:
        return _RARIDADE_DO_PERGAMINHO[int(magia.get("nivel", 0) or 0)]
    magico = _magico_por_nome(nome or "")
    return (magico or {}).get("raridade", "")


def _preco_de_raridade_pc(nome: str) -> int | None:
    """Preço de tabela de um item mágico, em cobre: o fixo (Poção de Cura) ou o da raridade."""
    if _magia_do_pergaminho(nome):
        return _PRECO_POR_RARIDADE_PO[_raridade_do_item(nome)] * 100 // 2
    magico = _magico_por_nome(nome or "")
    if not magico:
        return None
    if magico.get("preco_pc"):
        return int(magico["preco_pc"])
    po = _PRECO_POR_RARIDADE_PO.get(magico.get("raridade", ""))
    if not po:
        return None                       # artefato não tem preço
    pc = po * 100
    if magico.get("tipo") in ("poção", "pergaminho", "munição"):
        pc //= 2
    base = _itens.arma(nome) or _itens.armadura(nome)
    return pc + (int(base["preco_pc"]) if base else 0)


def _preco_pc_do_srd(nome: str) -> int | None:
    """
    Preço de tabela em PEÇAS DE COBRE, do compêndio do SRD. None quando não há.

    Antes era ouro inteiro: tudo abaixo de 1 po custava 1 po (a tocha de 1 pc,
    a ração de 5 pp, a clava de 1 pp), e 20 tochas saíam por 20 po. Equipamento
    de aventura não tinha preço nenhum. Item mágico tem o preço da raridade.
    """
    return _itens.preco_pc(nome) or _preco_de_raridade_pc(nome)


_PRECO_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(po|pp|pc|ouro|prata|cobre|gp|sp|cp)?\s*$",
                       re.IGNORECASE)
_PECAS_POR_MOEDA = {"po": 100, "ouro": 100, "gp": 100, "pp": 10, "prata": 10, "sp": 10,
                    "pc": 1, "cobre": 1, "cp": 1}


def _ler_preco_pc(texto: str) -> int | None:
    """'50' → 5000 (ouro é o padrão); '5 pp' → 50; '2pc' → 2; '0.5' → 50."""
    m = _PRECO_RE.match(str(texto or ""))
    if not m:
        return None
    valor = float(m.group(1).replace(",", "."))
    return max(0, int(round(valor * _PECAS_POR_MOEDA[(m.group(2) or "po").lower()])))


def _fmt_pc(pc: int) -> str:
    """1550 → '15 po 5 pp'; 5 → '5 pc'; 0 → '0 pc'."""
    po, resto = divmod(max(0, int(pc)), 100)
    pp, pc_ = divmod(resto, 10)
    partes = [f"{po} po" if po else "", f"{pp} pp" if pp else "", f"{pc_} pc" if pc_ else ""]
    return " ".join(p for p in partes if p) or "0 pc"


def _preco_pc_da_linha(linha: dict) -> int:
    """
    O preço de uma linha do estoque, em cobre. Loja salva antes da troca
    guardava `preco` em ouro inteiro: a linha é convertida na primeira leitura.
    """
    if "preco_pc" not in linha:
        linha["preco_pc"] = int(linha.pop("preco", 0) or 0) * 100
    return int(linha.get("preco_pc") or 0)


# Tesouro (gema, obra de arte, mercadoria) vale o preço cheio: no 5e ele é
# quase moeda. Só equipamento usado sai pela metade.
_PALAVRAS_DE_TESOURO = ("gema", "joia", "rubi", "safira", "esmeralda", "diamante", "perola",
                        "ametista", "topazio", "opala", "onix", "jade", "obra de arte",
                        "estatueta", "tapecaria", "lingote", "barra de ouro", "barra de prata")
_VALOR_ESCRITO = re.compile(r"(\d+(?:[.,]\d+)?)\s*(po|pp|pc)\b", re.IGNORECASE)


def _e_tesouro(item: dict) -> bool:
    if item.get("tesouro"):
        return True
    e = _itens.comum(item.get("nome", ""))
    if e:
        return e["categoria"] == "mercadoria"
    nome = _norm_txt(item.get("nome", ""))
    return any(p in nome for p in _PALAVRAS_DE_TESOURO)


def _valor_de_referencia_pc(item: dict) -> int | None:
    """
    Quanto vale UMA unidade, em cobre: o valor gravado no item (`valor_po` ou
    `valor`, que o mestre põe em gema e obra de arte), o preço do SRD, ou o
    valor escrito no nome ou na descrição ("Rubi (50 po)"). None quando nada
    disso existe: a loja não chuta valor.
    """
    for campo in ("valor_po", "valor"):
        v = item.get(campo)
        if v not in (None, ""):
            try:
                return max(0, int(round(float(v) * 100)))
            except (TypeError, ValueError):
                pass
    nome = item.get("nome", "")
    srd = _preco_pc_do_srd(nome)
    if srd:
        return srd
    for texto in (nome, item.get("descricao", "") or ""):
        m = _VALOR_ESCRITO.search(texto)
        if m:
            return _ler_preco_pc(f"{m.group(1)} {m.group(2)}")
    return None


def open_shop(shop_name: str, items: str = "", location: str = "", owner: str = "",
              kind: str = "", size: str = "") -> str:
    """
    Monta uma loja com estoque e preços. O que é do SRD (armas, armaduras,
    equipamento de aventura, ferramentas, a Poção de Cura) já sai com o custo
    oficial ('Espada Longa' → 15 po, 'Tocha' → 1 pc); para o resto, informe.

    Chamar de novo com o mesmo nome de loja ACRESCENTA ao estoque — item já
    existente tem preço e quantidade atualizados, o resto continua lá.

    Nada aqui confere se o estoque combina com a loja: uma forja vendendo
    poção passa. Coerência é escolha sua na narrativa.

    Args:
        shop_name: Nome da loja ('Forja do Torbin').
        items:     Itens separados por ';'. Formato por item:
                   "nome" ou "nome:preço" ou "nome:preço:quantidade",
                   com descrição opcional depois de '|'. O preço é em ouro
                   ("50"), ou com a moeda ("5 pp", "2 pc").
                   Ex: "Espada Longa; Poção de Cura:50:3; Vela:1 pc"
                   Ex: "Amuleto do Corvo:75:1|dá vantagem em Furtividade"
                   Descreva SEMPRE o que não for item do SRD — a descrição
                   vai junto para o inventário de quem comprar, e é por ela
                   que o motor confere se o item desequilibra a mesa.
        location:  Onde o GRUPO está agora, dentro da loja (padrão: o local
                   atual). Se for outro local, ele passa a ser o local atual
                   do grupo — é o que faz a tela de loja abrir. Para
                   reabastecer uma loja de outro lugar, não informe.
        owner:     Nome do personagem que atende ('Torbin'). A atitude dele
                   mexe no preço: 5% a cada 20 pontos, até 25% para menos ou
                   para mais, e a ficha dele passa a mostrar o estoque.
        kind:      Tipo da loja, para o motor montar o estoque do SRD sozinho:
                   forja, armazem, boticario, templo, arcana, joalheiro. Com
                   kind, `items` é opcional (o que você quiser A MAIS).
        size:      Porte do lugar: vilarejo, vila, cidade ou metropole. Decide
                   quanto de mágico há à venda (vilarejo e vila: só comum;
                   cidade: até incomum; metrópole: até raro) e quanto o
                   lojista tem para comprar do grupo. A loja se repõe a cada
                   semana do relógio.
    """
    nome_loja = (shop_name or "").strip()
    if not nome_loja:
        return "A loja precisa de um nome."

    tipo, porte = _tipo_de_loja(kind), _porte(size)
    if kind and not tipo:
        return (f"Erro: tipo de loja '{kind}' desconhecido. Use: "
                f"{', '.join(sorted(_TIPOS_DE_LOJA))}.")
    if size and not porte:
        return f"Erro: porte '{size}' desconhecido. Use: vilarejo, vila, cidade ou metropole."
    if tipo and not porte:
        porte = "vila"

    estoque = []
    sem_preco = []
    for bruto in (items or "").split(";"):
        bruto = bruto.strip()
        if not bruto:
            continue
        # Descrição opcional depois de '|'. Fica fora do split de ':' porque
        # texto livre tem dois-pontos ("efeito: +1") e comeria o preço.
        bruto, _, descricao = bruto.partition("|")
        descricao = descricao.strip()
        partes = [p.strip() for p in bruto.split(":")]
        nome   = partes[0]
        if not nome:
            continue
        preco = _ler_preco_pc(partes[1]) if len(partes) > 1 and partes[1] else None
        if preco is None:
            preco = _preco_pc_do_srd(nome)
        if preco is None:
            sem_preco.append(nome)
            continue
        try:
            qtd = max(1, int(partes[2])) if len(partes) > 2 and partes[2] else 99
        except ValueError:
            qtd = 99
        estoque.append({"nome": nome, "preco_pc": preco, "qtd": qtd, "base": qtd,
                        "descricao": descricao, "manual": True})

    gerado = []
    if tipo:
        gerado = _gerar_estoque(tipo, porte, f"{_norm_txt(nome_loja)}:0")
    if not estoque and not gerado:
        return ("Nenhum item com preço. O SRD não conhece: "
                + ", ".join(sem_preco) + ". Informe o preço no formato "
                "'nome:preço' (ex: 'Amuleto do Corvo:75', 'Vela:1 pc').") if sem_preco else \
               "Informe ao menos um item."

    # Chamar open_shop de novo ACRESCENTA ao estoque; antes substituía, e uma
    # segunda chamada para pôr um item a mais apagava a loja inteira.
    chave = _norm_txt(nome_loja)
    loja  = _lojas().get(chave)
    ja_existia = loja is not None
    if not ja_existia:
        loja = {"nome": nome_loja, "local": "", "dono": "", "estoque": []}
        _lojas()[chave] = loja
    if owner:
        loja["dono"] = owner.strip()
    if tipo:
        loja["tipo"], loja["porte"] = tipo, porte
    if porte and loja.get("bolsa_base_pc") is None:
        loja["bolsa_base_pc"] = _PORTES[porte][2] * 100
        loja["bolsa_pc"] = loja["bolsa_base_pc"]
    loja.setdefault("reposta_em", _agora_em_horas())
    if location or not loja.get("local"):
        loja["local"] = location or memory.campaign.get("current_location", "")

    # `location` é, pelo contrato, ONDE O GRUPO ESTÁ. Se ele difere do local
    # atual, o grupo chegou lá e o mestre não chamou update_world_state: a
    # loja ficava em "Cliviate", o grupo continuava "na Clareira", e a tela
    # (que só mostra lojas do local atual) nem abria nem mostrava a pílula.
    aviso_local = ""
    local_atual = memory.campaign.get("current_location", "") or ""
    from rpg import locais as _locais
    # Já estar DENTRO do local informado (na própria forja, que fica em
    # Cliviate) é estar lá: não tira o grupo da loja para pô-lo na rua.
    if (location and _norm_txt(location) != _norm_txt(local_atual)
            and not _locais.esta_dentro(local_atual, location)):
        salvo = (memory.campaign.get("locations") or {}).get(location.strip().lower()) or {}
        novo_local = salvo.get("name") or location.strip()
        memory.campaign["current_location"] = novo_local
        loja["local"] = novo_local
        memory.marcar_upkeep("mundo")
        aviso_local = (f"\n   Nota: o local atual do grupo passou de "
                       f"'{local_atual or '—'}' para '{novo_local}'. Para "
                       f"reabastecer uma loja de outro lugar sem mover o grupo, "
                       f"não informe location.")

    novos, repostos = [], []
    for item in gerado:
        if not any(_norm_txt(i["nome"]) == _norm_txt(item["nome"]) for i in loja["estoque"]):
            loja["estoque"].append(item)
    for item in estoque:
        antigo = next((i for i in loja["estoque"]
                       if _norm_txt(i["nome"]) == _norm_txt(item["nome"])), None)
        if antigo:
            antigo.pop("preco", None)
            antigo["preco_pc"] = item["preco_pc"]
            antigo["qtd"]   = item["qtd"]
            antigo["base"]  = item["qtd"]
            antigo["manual"] = True
            if item.get("descricao"):
                antigo["descricao"] = item["descricao"]
            repostos.append(item["nome"])
        else:
            loja["estoque"].append(item)
            novos.append(item["nome"])
    memory.save_campaign()

    cabeca = (f"**{nome_loja}** atualizada" if ja_existia
              else f"**{nome_loja}** aberta")
    if loja.get("tipo"):
        cabeca += f" ({loja['tipo']}, {loja['porte']})"
    linhas = [cabeca + (f" em {loja['local']}" if loja.get("local") else "") + ":"]
    for i in loja["estoque"]:
        q = "" if i["qtd"] >= 99 else f"  (x{i['qtd']})"
        marca = "  ← novo" if i["nome"] in novos and ja_existia else ""
        linhas.append(f"   • {i['nome']} — {_fmt_pc(_preco_pc_da_linha(i))}{q}{marca}")
    if repostos and ja_existia:
        linhas.append("   ↻ Preço/estoque atualizados: " + ", ".join(repostos))
    if sem_preco:
        linhas.append("   Sem preço (fora do SRD, não entraram): "
                      + ", ".join(sem_preco))
    if loja.get("bolsa_pc") is not None:
        linhas.append(f"   O lojista tem {_fmt_pc(loja['bolsa_pc'])} para comprar do grupo.")
    return "\n".join(linhas) + aviso_local


def list_shop(shop_name: str) -> str:
    """
    Mostra o estoque e os preços de uma loja.

    Args:
        shop_name: Nome da loja.
    """
    loja = _lojas().get(_norm_txt(shop_name))
    if not loja:
        abertas = ", ".join(l["nome"] for l in _lojas().values()) or "nenhuma"
        return f"Aviso: Loja '{shop_name}' não encontrada. Abertas: {abertas}."
    linhas = [f"**{loja['nome']}**"
              + (f" — {loja['local']}" if loja.get("local") else "")]
    for i in loja["estoque"]:
        if int(i.get("qtd", 0) or 0) <= 0:
            q = "  (esgotado até a reposição)"
        else:
            q = "" if i["qtd"] >= 99 else f"  (restam {i['qtd']})"
        linhas.append(f"   • {i['nome']} — {_fmt_pc(_preco_pc_da_linha(i))}{q}")
    return "\n".join(linhas)


# ===========================================================================
# TELA DE LOJA — snapshot e despacho
# ===========================================================================
# Mesma disciplina da tela de combate: nenhuma REGRA mora aqui. A diferença é
# que o combate precisou de um dispatcher próprio (combat_action) porque a
# economia de turno não tem equivalente nas ferramentas do agente. Compra não
# tem nada disso, então shop_action apenas CHAMA buy_item/sell_item — as
# mesmas funções que o mestre usa.
#
# Isso é de propósito. Todo caminho paralelo até uma regra é uma chance de os
# dois discordarem, e já aconteceu duas vezes neste motor: o braço da IA de
# NPC cobrava a recarga e o do mestre não; a loja marcava item inventado e o
# verificador não via. Uma função, um comportamento.


def _linha_de_venda(char: dict, item: dict, loja: dict) -> dict | None:
    """
    O que o personagem consegue vender e por quanto (em cobre). None quando
    não há valor de referência — a loja não chuta valor de item sem tabela.

    Equipamento sai pela METADE da tabela, com a atitude do lojista; tesouro
    (gema, obra de arte, mercadoria) pelo valor cheio. Antes a loja só sabia o
    preço de arma e armadura: a poção e o rubi achados no saque não vendiam.
    """
    nome = item.get("nome", "")
    if not nome:
        return None
    na_loja = next((i for i in loja.get("estoque", [])
                    if _norm_txt(i["nome"]) == _norm_txt(nome)), None)
    tabela = _preco_pc_da_linha(na_loja) if na_loja else _valor_de_referencia_pc(item)
    if not tabela or tabela <= 0:
        return None
    tesouro = _e_tesouro(item)
    ganho = int(tabela) if tesouro else _ganho_com_atitude(tabela, loja)
    return {
        "nome":    nome,
        "qtd":     int(item.get("qtd", 1) or 1),
        "tabela_pc": int(tabela),
        "ganho_pc":  ganho,
        "tabela_texto": _fmt_pc(tabela),
        "ganho_texto":  _fmt_pc(ganho),
        "tesouro": tesouro,
        "peso":    round(_peso_do_item(item), 2),
        "custom":  bool(item.get("custom")),
    }


def shop_snapshot(shop_name: str = "", buyer: str = "") -> dict:
    """Estado completo da loja para a tela (JSON-serializável)."""
    from rpg import locais as _locais
    lojas = _lojas()
    local = memory.campaign.get("current_location", "")

    # A loja DAQUI é a que o grupo acabou de entrar. Sem ela a tela não se
    # abre sozinha: loja é estado que persiste, e reabrir a tela em toda cena
    # só porque existe uma ferraria em outra cidade seria intromissão.
    # Dentro da própria loja (o grupo foi "até a Forja de Cliviate") ela
    # também é daqui.
    aqui = [l for l in lojas.values()
            if local and _norm_txt(local) in (_norm_txt(l.get("local", "")),
                                              _norm_txt(l.get("nome", "")))]

    escolhida = None
    if shop_name:
        escolhida = lojas.get(_norm_txt(shop_name))
    if not escolhida:
        escolhida = aqui[0] if aqui else (next(iter(lojas.values()), None))

    grupo = []
    for c in memory.campaign.get("characters", {}).values():
        if memory.is_party_member(c) and (c.get("sheet") or {}):
            grupo.append(c)

    comprador = None
    if buyer:
        comprador = next((c for c in grupo
                          if _norm_txt(c.get("name", "")) == _norm_txt(buyer)), None)
    if not comprador:
        comprador = grupo[0] if grupo else None

    dados_comprador, inventario = None, []
    if comprador:
        sh = comprador.get("sheet") or {}
        estado, carga, cap = _estado_de_carga(comprador)
        dados_comprador = {
            "nome":   comprador.get("name", ""),
            "ouro":   int(sh.get("ouro", 0) or 0),
            "prata":  int(sh.get("prata", 0) or 0),
            "cobre":  int(sh.get("cobre", 0) or 0),
            "bolsa_em_cobre": _cobre_total(sh),
            "bolsa_texto": _fmt_pc(_cobre_total(sh)),
            "carga":      round(carga, 1),
            "capacidade": round(cap, 1),
            "meia_capacidade": round(cap / 2, 1),
            "estado_carga":   estado,
        }
        if escolhida:
            for it in (comprador.get("inventario") or []):
                if isinstance(it, dict):
                    linha = _linha_de_venda(comprador, it, escolhida)
                    if linha:
                        inventario.append(linha)

    estoque = []
    if escolhida:
        for i in escolhida.get("estoque", []):
            if int(i.get("qtd", 0) or 0) <= 0:
                continue                   # esgotado até a reposição
            tabela = _preco_pc_da_linha(i)
            pedido = _preco_com_atitude(tabela, escolhida)
            estoque.append({
                "nome":      i["nome"],
                # `preco_pc` é o que a tela mostra e o que buy_item cobra: já
                # com a atitude. `tabela_pc` fica ao lado para a tela explicar.
                "preco_pc":  pedido,
                "tabela_pc": tabela,
                "preco_texto":  _fmt_pc(pedido),
                "tabela_texto": _fmt_pc(tabela),
                "qtd":       int(i["qtd"]),
                "ilimitado": int(i["qtd"]) >= 99,
                "descricao": i.get("descricao", ""),
                "peso":      round(_peso_do_item({"nome": i["nome"]}), 2),
                "custom":    not (_itens.comum(i["nome"]) or _itens.magico(i["nome"])),
            })

    return {
        "tem_loja":  bool(escolhida),
        "loja_aqui": bool(aqui),
        "dono":      (escolhida or {}).get("dono", ""),
        "tipo":      (escolhida or {}).get("tipo", ""),
        "porte":     (escolhida or {}).get("porte", ""),
        # Quanto o lojista tem para comprar do grupo (None: sem limite).
        "bolsa_loja_pc": (escolhida or {}).get("bolsa_pc"),
        "bolsa_loja_texto": (_fmt_pc(escolhida["bolsa_pc"])
                             if escolhida and escolhida.get("bolsa_pc") is not None else ""),
        "atitude":   _atitude_da_loja(escolhida) if escolhida else None,
        "pechincha": (_pechincha_valida(escolhida) if escolhida else None),
        # TODAS as lojas deste local. Antes a tela só conhecia aqui[0]: com uma
        # forja e um boticário na mesma cidade, o boticário nunca aparecia —
        # nem sozinho, nem pela pílula.
        "lojas_aqui": [{"nome": l.get("nome", ""), "chave": _norm_txt(l.get("nome", ""))}
                       for l in aqui],
        # A tela abre sozinha UMA vez por visita a um local. Ela precisa de uma
        # chave estável do local para lembrar disso entre recargas da página.
        "local_chave": _norm_txt(local),
        # Lugares que ficam dentro do local atual. Voltar da forja para a rua
        # da cidade não é visita nova: a tela não reabre por isso.
        "filhos_chaves": [_norm_txt(f["nome"]) for f in _locais.filhos(local)],
        "loja": {
            "nome":  escolhida.get("nome", "") if escolhida else "",
            "local": escolhida.get("local", "") if escolhida else "",
            "chave": _norm_txt(escolhida.get("nome", "")) if escolhida else "",
        },
        "lojas":     [{"nome": l.get("nome", ""), "local": l.get("local", "")}
                      for l in lojas.values()],
        "grupo":     [c.get("name", "") for c in grupo],
        "comprador": dados_comprador,
        "estoque":   estoque,
        "inventario": inventario,
        "local_atual": local,
        # A tela guarda este número ao abrir e, ao encerrar, pede o resumo do
        # que foi negociado depois dele (shop_recap_payload).
        "negocios_seq": _seq_de_negocios(),
    }


def shop_action(action: str, shop: str = "", char: str = "",
                item: str = "", quantity: int = 1) -> dict:
    """
    Aplica UMA intenção da tela de loja. Devolve {ok, message, snapshot}.

    actions: buy | sell

    O corpo é só despacho: quem cobra a bolsa, confere o estoque, marca item
    inventado e avisa da carga é buy_item/sell_item, iguais às do mestre.
    """
    a = (action or "").lower().strip()
    try:
        qtd = max(1, int(quantity))
    except (TypeError, ValueError):
        qtd = 1

    if a == "buy":
        msg = buy_item(char, shop, item, qtd)
    elif a == "sell":
        msg = sell_item(char, shop, item, qtd)
    elif a in ("pechinchar", "haggle"):
        msg = haggle(char, shop)
    else:
        return {"ok": False, "message": f"Ação '{action}' desconhecida.",
                "snapshot": shop_snapshot(shop, char)}

    # As ferramentas sinalizam recusa pelo PREFIXO da mensagem ("Erro:",
    # "Aviso:"). Era um emoji até o repositório abandonar emoji; o contrato é
    # o mesmo, só que em texto — legível no log e para a IA.
    ok = not msg.lstrip().startswith(("Aviso:", "Erro:"))
    return {"ok": ok, "message": msg, "snapshot": shop_snapshot(shop, char)}


# ── Negócios da visita ──────────────────────────────────────────────────────
# Ao encerrar, a tela mandava sempre "O grupo terminou de negociar em X" —
# sem dizer se houve negócio. O grupo saía do boticário sem comprar nada e o
# mestre narrava "guardam os novos suprimentos nas mochilas". Cada compra e
# venda (da tela ou do mestre) entra aqui com um número de sequência; a tela
# guarda o número de quando abriu e pede o resumo do que veio depois.

def _registrar_negocio(tipo: str, quem: str, loja: str, item: str, qtd: int) -> None:
    neg = memory.campaign.setdefault("negocios", {"seq": 0, "lista": []})
    neg["seq"] = int(neg.get("seq", 0) or 0) + 1
    lista = neg.setdefault("lista", [])
    lista.append({"seq": neg["seq"], "tipo": tipo, "quem": quem,
                  "loja": loja, "item": item, "qtd": int(qtd)})
    neg["lista"] = lista[-50:]


def _seq_de_negocios() -> int:
    return int((memory.campaign.get("negocios") or {}).get("seq", 0) or 0)


def shop_recap_payload(desde_seq: int = 0, loja: str = "") -> str:
    """
    O texto que a tela manda ao mestre ao encerrar as compras: o que foi
    comprado e vendido desde `desde_seq` (o número de quando a tela abriu),
    ou que nada foi negociado.
    """
    try:
        desde = int(desde_seq)
    except (TypeError, ValueError):
        desde = 0
    feitos = [n for n in (memory.campaign.get("negocios") or {}).get("lista", []) or []
              if int(n.get("seq", 0) or 0) > desde]
    onde = loja or (feitos[-1]["loja"] if feitos else "a loja")

    if not feitos:
        return (f"[COMPRAS RESOLVIDAS NA TELA] O grupo olhou o estoque de {onde} e saiu "
                f"SEM comprar nem vender nada. Narre a saída em uma ou duas frases, "
                f"sem mencionar compras, frascos ou itens novos.")

    lojas = {n["loja"] for n in feitos}
    partes = []
    for n in feitos:
        verbo = "comprou" if n["tipo"] == "compra" else "vendeu"
        em = f" em {n['loja']}" if len(lojas) > 1 else ""
        partes.append(f"{n['quem']} {verbo} {n['qtd']}x {n['item']}{em}")
    return (f"[COMPRAS RESOLVIDAS NA TELA] O grupo terminou de negociar em {onde}. "
            f"Negócios feitos: {'; '.join(partes)}. Os itens e as moedas já estão nas "
            f"fichas — não chame buy_item, sell_item nem add_item por eles. Narre a "
            f"saída da loja em uma ou duas frases, sem repetir preços nem citar item "
            f"que não está nesta lista.")


def _cobre_total(sheet: dict) -> int:
    return (int(sheet.get("ouro", 0) or 0) * 100
            + int(sheet.get("prata", 0) or 0) * 10
            + int(sheet.get("cobre", 0) or 0))


def _receber(sheet: dict, cobre: int) -> None:
    """Põe `cobre` na bolsa, nas moedas maiores: 1550 pc viram 15 po e 5 pp."""
    po, resto = divmod(max(0, int(cobre)), 100)
    sheet["ouro"]  = int(sheet.get("ouro", 0) or 0) + po
    sheet["prata"] = int(sheet.get("prata", 0) or 0) + resto // 10
    sheet["cobre"] = int(sheet.get("cobre", 0) or 0) + resto % 10


def _pagar(sheet: dict, cobre: int) -> bool:
    """Debita `cobre` da bolsa, trocando moeda quando preciso. False se falta."""
    total = _cobre_total(sheet)
    if total < cobre:
        return False
    resto = total - cobre
    sheet["ouro"]  = resto // 100
    sheet["prata"] = (resto % 100) // 10
    sheet["cobre"] = resto % 10
    return True


def buy_item(char_name: str, shop_name: str, item_name: str, quantity: int = 1) -> str:
    """
    Compra um item de uma loja: confere o estoque, cobra da bolsa (trocando
    ouro/prata/cobre sozinho) e põe no inventário.

    Args:
        char_name: Quem compra.
        shop_name: Nome da loja.
        item_name: Item desejado.
        quantity:  Quantas unidades (padrão 1).
    """
    char, err = _get_char(char_name)
    if not char:
        return err
    loja = _lojas().get(_norm_txt(shop_name))
    if not loja:
        return f"Aviso: Loja '{shop_name}' não encontrada."

    if not _loja_daqui(loja):
        return (f"Aviso: {loja['nome']} fica em {loja.get('local')}; o grupo está em "
                f"{memory.campaign.get('current_location')}. Para comprar, é preciso ir até lá.")
    linha = next((i for i in loja["estoque"]
                  if _norm_txt(i["nome"]) == _norm_txt(item_name)), None)
    if not linha:
        return (f"Aviso: '{item_name}' não está à venda em {loja['nome']}. "
                f"Use list_shop('{loja['nome']}').")

    try:
        qtd = max(1, int(quantity))
    except (TypeError, ValueError):
        qtd = 1
    if linha["qtd"] < qtd:
        if linha["qtd"] <= 0:
            return (f"Aviso: {linha['nome']} esgotou em {loja['nome']}; a loja se repõe "
                    f"a cada semana.")
        return f"Aviso: {loja['nome']} tem só {linha['qtd']}x {linha['nome']}."

    sheet = char["sheet"]
    tabela = _preco_pc_da_linha(linha)
    unitario = _preco_com_atitude(tabela, loja)
    custo = unitario * qtd
    if not _pagar(sheet, custo):
        return (f"Erro: {char['name']} não tem como pagar: "
                f"{_fmt_pc(custo)} pedidos, {_fmt_pc(_cobre_total(sheet))} na bolsa.")

    linha["qtd"] -= qtd
    if linha["qtd"] <= 0 and not int(linha.get("base", 0) or 0):
        loja["estoque"].remove(linha)
    elif linha["qtd"] <= 0:
        linha["qtd"] = 0                  # esgotado: volta na reposição da semana
    if loja.get("bolsa_pc") is not None:
        loja["bolsa_pc"] = int(loja["bolsa_pc"]) + custo
    _registrar_negocio("compra", char["name"], loja["nome"], linha["nome"], qtd)
    # A descrição VAI JUNTO. Sem ela o add_item não tem o que auditar, e a
    # loja virava desvio da conferência de item inventado: uma "Lâmina Rúnica
    # de Vhar" comprada ficava marcada como custom mas sem efeito declarado,
    # e o verificador não cobrava nada.
    add_item(char["name"], linha["nome"], qtd, linha.get("descricao", ""))
    # A loja sabe o que vende: o que sai do balcão não chega "a identificar".
    comprado = _item_do_inventario(char, linha["nome"])
    if comprado and comprado.get("srd"):
        comprado["identificado"] = True

    estado, carga, cap = _estado_de_carga(char)
    aviso = ""
    if estado != "livre":
        aviso = (f"\n   Carga: {carga:.1f}/{cap:.1f} kg — **{estado}**. "
                 f"Veja check_encumbrance().")
    ajuste = _atitude_da_loja(loja)
    nota_atitude = ""
    if ajuste:
        nota_atitude = (f" (tabela {_fmt_pc(tabela * qtd)}, {ajuste['pct']:+d}% — "
                        f"{ajuste['dono']} está {ajuste['rotulo']})")
    return (f"{char['name']} comprou {qtd}x {linha['nome']} por "
            f"{_fmt_pc(custo)} em {loja['nome']}{nota_atitude}.\n"
            f"   Bolsa: {sheet['ouro']} po, {sheet['prata']} pp, {sheet['cobre']} pc{aviso}")


def sell_item(char_name: str, shop_name: str, item_name: str, quantity: int = 1) -> str:
    """
    Vende um item para uma loja. Pela regra da mesa, a loja paga METADE do
    preço de tabela — é o que impede o inventário de virar uma torneira de
    ouro (comprar e revender pelo mesmo valor seria dinheiro de graça). Tesouro
    (gema, obra de arte, mercadoria) vale o preço cheio. O pagamento vem nas
    moedas certas: metade de uma clava são 5 pc, não 1 po.

    Args:
        char_name: Quem vende.
        shop_name: Nome da loja.
        item_name: Item a vender.
        quantity:  Quantas unidades (padrão 1).
    """
    char, err = _get_char(char_name)
    if not char:
        return err
    loja = _lojas().get(_norm_txt(shop_name))
    if not loja:
        return f"Aviso: Loja '{shop_name}' não encontrada."

    if not _loja_daqui(loja):
        return (f"Aviso: {loja['nome']} fica em {loja.get('local')}; o grupo está em "
                f"{memory.campaign.get('current_location')}. Para vender, é preciso ir até lá.")
    inv  = char.get("inventario") or []
    item = next((i for i in inv
                 if isinstance(i, dict)
                 and _norm_txt(i.get("nome", "")) == _norm_txt(item_name)), None)
    if not item:
        return f"Aviso: {char['name']} não tem '{item_name}'."

    try:
        qtd = max(1, int(quantity))
    except (TypeError, ValueError):
        qtd = 1
    if int(item.get("qtd", 1) or 1) < qtd:
        return f"Aviso: {char['name']} tem só {item.get('qtd', 1)}x {item['nome']}."

    na_loja = next((i for i in loja["estoque"]
                    if _norm_txt(i["nome"]) == _norm_txt(item_name)), None)
    linha = _linha_de_venda(char, item, loja)
    if not linha:
        return (f"Aviso: Sem preço de referência para '{item['nome']}'. "
                f"Ponha o item na loja com open_shop() informando o preço.")

    ganho = linha["ganho_pc"] * qtd
    if loja.get("bolsa_pc") is not None and ganho > int(loja["bolsa_pc"]):
        return (f"Aviso: {loja.get('dono') or 'o lojista'} só tem {_fmt_pc(loja['bolsa_pc'])} "
                f"para pagar, e {qtd}x {item['nome']} valem {_fmt_pc(ganho)} para ele. "
                f"Venda menos, ou procure uma loja maior.")
    sheet = char["sheet"]
    _receber(sheet, ganho)
    if loja.get("bolsa_pc") is not None:
        loja["bolsa_pc"] = int(loja["bolsa_pc"]) - ganho

    item["qtd"] = int(item.get("qtd", 1) or 1) - qtd
    if item["qtd"] <= 0:
        inv.remove(item)
    nota_equip = _desequipar_o_que_saiu(char, item["nome"])
    if na_loja:
        na_loja["qtd"] = min(99, na_loja["qtd"] + qtd)
    else:
        # O que o grupo vende fica na prateleira, pelo preço de tabela.
        loja["estoque"].append({"nome": item["nome"], "preco_pc": linha["tabela_pc"], "qtd": qtd,
                                "base": 0, "descricao": item.get("descricao", "") or "",
                                "manual": True})
    _registrar_negocio("venda", char["name"], loja["nome"], item["nome"], qtd)
    memory.save_campaign()

    # Na venda o sinal se inverte: o lojista que cobra 20% a menos paga 20% a
    # mais. `pct` é sempre do ponto de vista do preço pedido.
    ajuste = _atitude_da_loja(loja)
    nota_atitude = (f", {-ajuste['pct']:+d}% pela relação com {ajuste['dono']}"
                    if ajuste and not linha["tesouro"] else "")
    regra = ("tesouro: valor cheio" if linha["tesouro"]
             else f"metade da tabela: {linha['tabela_texto']}{nota_atitude}")
    return (f"{char['name']} vendeu {qtd}x {item_name} por {_fmt_pc(ganho)} "
            f"({regra}) em {loja['nome']}.\n"
            f"   Bolsa: {sheet['ouro']} po, {sheet.get('prata', 0)} pp, "
            f"{sheet.get('cobre', 0)} pc{nota_equip}")


# ===========================================================================
# RELÓGIO DE MUNDO E EXAUSTÃO
# ---------------------------------------------------------------------------
# Sem tempo, descansar era de graça: bastava pedir long_rest() depois de cada
# luta e o grupo voltava inteiro, infinitas vezes por "dia". O recurso que o
# 5e usa para dar peso ao dia de aventura — o descanso longo ser um por 24h —
# não tinha como existir, porque não havia 24h.
#
# O relógio é deliberadamente grosso: DIA e HORA, sem minutos. Numa mesa
# narrativa o que importa é "amanheceu", "a caravana parte ao meio-dia",
# "vocês estão acordados há 20 horas" — minuto a minuto seria ruído que o
# mestre teria de inventar a cada turno.
#
# EXAUSTÃO é o outro lado: o custo de não dormir, da marcha forçada, da fome.
# Os seis níveis do 5e, com só os efeitos que o motor consegue mesmo cobrar.
# ===========================================================================

_PERIODOS = (
    (0,  6,  "madrugada"),
    (6,  12, "manhã"),
    (12, 18, "tarde"),
    (18, 24, "noite"),
)

# Nível → (efeito legível, o que o motor cobra)
EXAUSTAO_EFEITOS = {
    1: "Desvantagem em testes de perícia e atributo",
    2: "Deslocamento pela metade — não pode usar a Disparada",
    3: "Desvantagem em ataques e testes de resistência",
    4: "PV máximo pela metade",
    5: "Deslocamento zero — não sai da zona em que está",
    6: "Morte",
}


def _relogio() -> dict:
    return memory.campaign.setdefault("relogio", {"dia": 1, "hora": 8})


def hora_do_relogio(r: dict) -> int:
    """
    A hora gravada, de 0 a 23; 8 só quando não há hora nenhuma.

    Era `int(r.get("hora", 8) or 8)`: 0 é falso em Python, e meia-noite virava
    8h da manhã — o relógio pulava 8 horas a cada dia que virava à meia-noite,
    e os encontros marcados para depois dela chegavam 8 horas atrasados.
    """
    h = (r or {}).get("hora")
    if h is None or h == "":
        return 8
    try:
        return int(h) % 24
    except (TypeError, ValueError):
        return 8


def _periodo(hora: int) -> str:
    for ini, fim, nome in _PERIODOS:
        if ini <= hora < fim:
            return nome
    return "madrugada"


def _agora_em_horas() -> int:
    """Instante atual como horas absolutas desde o dia 1 — facilita subtrair."""
    r = _relogio()
    return int(r.get("dia", 1) or 1) * 24 + hora_do_relogio(r)


def _minuto_do_relogio(r: dict) -> int:
    try:
        return int((r or {}).get("minuto", 0) or 0) % 60
    except (TypeError, ValueError):
        return 0


def _hora_legivel() -> str:
    r = _relogio()
    h = hora_do_relogio(r)
    mi = _minuto_do_relogio(r)
    return f"Dia {int(r.get('dia', 1) or 1)}, {h:02d}h{f'{mi:02d}' if mi else ''} ({_periodo(h)})"


def avancar_minutos(minutos: int, reason: str = "") -> str:
    """
    O tempo curto: o ritual de dez minutos, a conjuração de um minuto. O
    relógio do mundo contava só horas, e por isso o ritual "somava dez
    minutos" só no texto. Os minutos se acumulam; a cada 60, passa uma hora
    de verdade (com tudo o que advance_time faz).
    """
    try:
        m = int(minutos)
    except (TypeError, ValueError):
        return ""
    if m <= 0:
        return ""
    r = _relogio()
    antes = _hora_legivel()
    total = _minuto_do_relogio(r) + m
    r["minuto"] = total % 60
    if total // 60:
        r["_antes_minutos"] = antes      # advance_time mostra o início com os minutos
        return advance_time(total // 60, reason)
    memory.save_campaign()
    motivo = f" — {reason}" if reason else ""
    return f"{antes} → **{_hora_legivel()}**{motivo}"


def minutos_de_conjuracao(tempo: str) -> int:
    """'1 minuto' → 1; '10 minutos' → 10; '1 hora' → 60; ação, reação: 0."""
    t = _norm_txt(tempo or "")
    achado = re.search(r"(\d+)\s*(minuto|hora)", t)
    if not achado:
        return 0
    n = int(achado.group(1))
    return n * 60 if achado.group(2) == "hora" else n


def advance_time(hours: int, reason: str = "") -> str:
    """
    Faz o tempo passar no mundo. Chame sempre que a ficção consumir horas:
    viagem, vigília, pesquisa na biblioteca, espera pelo anoitecer.

    O relógio é o que torna o descanso longo um recurso (um por 24 horas) e o
    que deixa "amanheceu" ser um fato, não uma escolha de narração.

    Args:
        hours:  Horas a avançar (1 a 720 — 30 dias).
        reason: O que consumiu esse tempo (aparece no registro).
    """
    try:
        h = int(hours)
    except (TypeError, ValueError):
        return "Informe as horas como número inteiro."
    if h <= 0:
        return "Informe pelo menos 1 hora."
    if h > 720:
        return "No máximo 720 horas (30 dias) por chamada."

    r     = _relogio()
    antes = _hora_legivel()
    _inicio_h = _agora_em_horas()
    if r.get("_antes_minutos"):
        antes = r.pop("_antes_minutos")
    total = hora_do_relogio(r) + h
    r["dia"]  = int(r.get("dia", 1) or 1) + total // 24
    r["hora"] = total % 24
    # Para a cobrança do relógio parado (agent._pendencias_block) e o aviso de
    # narração que fez o tempo passar sem ele (validator).
    memory.marcar_upkeep("relogio")
    # Enfeitiçar Pessoa dura uma hora: passada a hora, o encanto acaba (e o
    # alvo sabe o que fizeram com ele). O mestre recebe a linha para narrar.
    from rpg import criaturas, encantos
    acabaram = encantos.expirar()
    # Animar Mortos dura 24 horas: o morto-vivo some quando o relógio chega lá.
    acabaram += criaturas.limpar()
    # Resistência Lendária é "por dia": o dia que vira devolve os usos.
    if total >= 24:
        for _ch_rl in (memory.campaign.get("characters") or {}).values():
            _rl_d = ((_ch_rl or {}).get("sheet") or {}).get("resistencia_lendaria") if isinstance(_ch_rl, dict) else None
            if isinstance(_rl_d, dict):
                _rl_d["restantes"] = int(_rl_d.get("max", 3) or 3)
    # Nocaute: depois de 1d4 horas, o NPC estável acorda com 1 PV.
    for _ch_n in (memory.campaign.get("characters") or {}).values():
        _s_n = (_ch_n or {}).get("sheet") if isinstance(_ch_n, dict) else None
        if (not _s_n or _s_n.get("acorda_hora") is None
                or (_ch_n.get("status") or "").lower() != "estabilizado"):
            continue
        if _agora_em_horas() >= int(_s_n["acorda_hora"]):
            _s_n.pop("acorda_hora", None)
            _s_n["vida_atual"] = max(1, int(_s_n.get("vida_atual", 0) or 0))
            _ch_n["status"] = "inimigo" if memory.lado_no_combate(_ch_n) == "inimigo" else "vivo"
            acabaram.append(f"{_ch_n.get('name')} acorda do nocaute com 1 PV")
    # Bom Fruto: a magia acaba em 24 horas, e as frutas viram frutas comuns.
    for _ch_f in (memory.campaign.get("characters") or {}).values():
        _inv_f = (_ch_f or {}).get("inventario")
        if not isinstance(_inv_f, list):
            continue
        _vencidas = [i for i in _inv_f if isinstance(i, dict) and i.get("expira_hora") is not None
                     and _agora_em_horas() >= int(i["expira_hora"])]
        for i in _vencidas:
            _inv_f.remove(i)
            acabaram.append(f"{i.get('nome')} de {_ch_f.get('name')} perdeu a magia ({i.get('qtd', 1)})")
    # Varinhas e cajados recuperam as cargas ao amanhecer (6h).
    _amanheceres = (_agora_em_horas() - 6) // 24 - (_inicio_h - 6) // 24
    if _amanheceres > 0:
        acabaram += _recarregar_itens(_amanheceres)
    # A poção de Força do Gigante que acabou devolve a Força.
    for _ch_p in (memory.campaign.get("characters") or {}).values():
        if isinstance(_ch_p, dict) and memory.is_party_member(_ch_p) and (_ch_p.get("sheet") or {}).get("_atributos_dos_itens"):
            _recalculate_ca(_ch_p)
    memory.save_campaign()

    motivo = f" — {reason}" if reason else ""
    virou  = "\n   O dia virou." if total >= 24 else ""
    fim_encanto = "".join(f"\n   {l}" for l in acabaram)
    return f"{antes} → **{_hora_legivel()}**{motivo}{virou}{fim_encanto}"


def _recarregar_itens(amanheceres: int) -> list[str]:
    """Cada amanhecer devolve as cargas do item (1d6+1 na Varinha de Teia), até o máximo."""
    linhas = []
    for ch in (memory.campaign.get("characters") or {}).values():
        for it in (ch or {}).get("inventario") or [] if isinstance(ch, dict) else []:
            if not isinstance(it, dict) or it.get("cargas") is None:
                continue
            uso = _uso_do_item(it.get("nome", ""))
            if not uso or uso.get("tipo") != "cargas" or not uso.get("recarga"):
                continue
            maximo, antes = int(uso.get("cargas", 0) or 0), int(it["cargas"])
            for _ in range(int(amanheceres)):
                v, _txt = _rolar_expr(uso["recarga"])
                it["cargas"] = min(maximo, int(it["cargas"]) + max(0, v))
            if it["cargas"] != antes:
                linhas.append(f"{it['nome']} de {ch.get('name')} recupera cargas: {antes} → {it['cargas']}/{maximo}")
    return linhas


def get_world_time() -> str:
    """Que horas são no mundo, e há quanto tempo o grupo não dorme."""
    linhas = [f"{_hora_legivel()}"]
    agora  = _agora_em_horas()
    for ch in memory.campaign.get("characters", {}).values():
        if not memory.is_party_member(ch) or not ch.get("sheet"):
            continue
        ultimo = (ch.get("sheet") or {}).get("ultimo_descanso_longo")
        nome   = ch.get("name", "?")
        if ultimo is None:
            linhas.append(f"   • {nome}: ainda não fez descanso longo nesta campanha.")
            continue
        horas = agora - int(ultimo)
        aviso = "  acima de 24h" if horas >= 24 else ""
        linhas.append(f"   • {nome}: {horas}h desde o último descanso longo{aviso}")
    exaustos = [
        f"{c.get('name')} ({(c.get('sheet') or {}).get('exaustao')})"
        for c in memory.campaign.get("characters", {}).values()
        if int(((c.get("sheet") or {}).get("exaustao") or 0)) > 0
    ]
    if exaustos:
        linhas.append("   Exaustão: " + ", ".join(exaustos))
    return "\n".join(linhas)


# ── Exaustão ───────────────────────────────────────────────────────────────

def _exaustao(sheet: dict) -> int:
    try:
        return max(0, min(6, int(sheet.get("exaustao", 0) or 0)))
    except (TypeError, ValueError):
        return 0


def _hp_max_efetivo(sheet: dict) -> int:
    """
    PV máximo depois da exaustão. Nível 4+ corta pela metade.

    O corte é CALCULADO, nunca gravado em vida_max: gravar destruiria o valor
    real da ficha e não teria como voltar quando a exaustão baixasse.
    """
    bruto = int(sheet.get("vida_max", 0) or 0)
    return max(1, bruto // 2) if _exaustao(sheet) >= 4 else bruto


def _nota_teto(sheet: dict) -> str:
    """
    Lembrete de que o PV máximo está cortado. Sem isso a ficha mostra
    '20/40' e ninguém entende por que a cura parou na metade.
    """
    teto  = _hp_max_efetivo(sheet)
    bruto = int(sheet.get("vida_max", 0) or 0)
    if teto >= bruto:
        return ""
    return f" — teto {teto} (exaustão {_exaustao(sheet)} corta o PV máximo pela metade)"


def add_exhaustion(char_name: str, levels: int = 1, reason: str = "") -> str:
    """
    Adiciona níveis de exaustão. É o custo de marcha forçada, noite em claro,
    fome, sede, frio — e de alguns poderes (o Frenesi do bárbaro).

    Escala 5e:
      1 Desvantagem em testes de perícia
      2 Deslocamento pela metade (sem Disparada)
      3 Desvantagem em ataques e saves
      4 PV máximo pela metade
      5 Deslocamento zero
      6 Morte

    Um descanso longo remove UM nível.

    Args:
        char_name: Nome do personagem.
        levels:    Quantos níveis somar (padrão 1).
        reason:    Por quê (marcha forçada, sem dormir, fome…).
    """
    char, err = _get_char(char_name)
    if not char:
        return err
    s     = char["sheet"]
    antes = _exaustao(s)
    try:
        n = max(1, int(levels))
    except (TypeError, ValueError):
        n = 1
    depois = min(6, antes + n)
    s["exaustao"] = depois

    motivo = f" ({reason})" if reason else ""
    linhas = [f"{char['name']}: exaustão {antes} → **{depois}**{motivo}"]
    for nivel in range(1, depois + 1):
        linhas.append(f"   {nivel}. {EXAUSTAO_EFEITOS[nivel]}")

    if depois >= 6:
        char["status"] = "morto"
        s["vida_atual"] = 0
        linhas.append("   Exaustão nível 6 — o personagem MORRE.")
        _log_combat_event("death", char["name"], "",
                          msg=f"{char['name']} morreu de exaustão")
    elif depois >= 4:
        # O teto caiu; a vida atual não pode ficar acima dele.
        teto = _hp_max_efetivo(s)
        if int(s.get("vida_atual", 0) or 0) > teto:
            s["vida_atual"] = teto
            linhas.append(f"   PV máximo efetivo agora é {teto} — vida ajustada.")

    memory.save_campaign()
    return "\n".join(linhas)


def remove_exhaustion(char_name: str, levels: int = 1) -> str:
    """
    Remove níveis de exaustão (comida quente, magia, uma noite de verdade).

    Args:
        char_name: Nome do personagem.
        levels:    Quantos níveis tirar (padrão 1).
    """
    char, err = _get_char(char_name)
    if not char:
        return err
    s     = char["sheet"]
    antes = _exaustao(s)
    if antes == 0:
        return f"{char['name']} não está exausto."
    try:
        n = max(1, int(levels))
    except (TypeError, ValueError):
        n = 1
    s["exaustao"] = max(0, antes - n)
    memory.save_campaign()
    if s["exaustao"] == 0:
        return f"{char['name']}: exaustão {antes} → **0**. Recuperado."
    return (f"{char['name']}: exaustão {antes} → **{s['exaustao']}** "
            f"({EXAUSTAO_EFEITOS[s['exaustao']]}).")


# ---------------------------------------------------------------------------
# 13. Descanso
# ---------------------------------------------------------------------------

# A CURA INFINITA. short_rest() rolava nível/2 dados de vida e curava, mas não
# tirava nada da reserva — a mesma que use_hit_die() controlava direitinho.
# As duas não conversavam: bastava pedir "descanso curto" três vezes seguidas
# para o grupo voltar inteiro, sem gastar dado nenhum e sem passar hora
# nenhuma. O descanso longo tinha ganhado o limite de 24h justamente para
# acabar com isso, e o curto continuava sendo a porta dos fundos.
#
# Agora há UMA reserva e UM caminho de gasto (_gastar_dados_de_vida), que as
# duas ferramentas e a tela de descanso usam. A reserva é o que limita a cura:
# esvaziou, o descanso curto ainda passa a hora, mas não cura — só o descanso
# longo, que é um por dia, devolve dados — e só metade da reserva.

def _dado_de_vida(sheet: dict) -> int:
    """Faces do dado de vida: da classe; da ficha para NPC/monstro; senão d8."""
    classe = CLASS_DATA.get((sheet.get("classe") or "").lower(), {})
    return int(classe.get("hit_die") or sheet.get("hit_die") or 8)


def _reserva_de_dados(sheet: dict) -> tuple[int, int]:
    """
    (restantes, máximo). O máximo é o nível.

    Ficha sem contador ainda não gastou nada: começa cheia. Um valor gravado
    acima do máximo (ficha editada à mão, nível que desceu) é lido como o
    máximo — ler é só ler, quem grava é o gasto.
    """
    maximo = max(1, int(sheet.get("nivel", 1) or 1))
    try:
        restantes = int(sheet.get("hit_dice_remaining", maximo))
    except (TypeError, ValueError):
        restantes = maximo
    return max(0, min(restantes, maximo)), maximo


def _dados_devolvidos_no_longo(sheet: dict) -> int:
    """
    Quantos dados o descanso longo devolve AGORA: os gastos, até metade do
    total (mínimo 1), como no PHB.

    Devolver a reserva inteira fazia um dia ruim sumir numa noite de sono. Com
    metade, quem torrou os dados numa masmorra acorda com parte deles e sente
    o custo no dia seguinte — é o que dá peso a guardar dado.
    """
    restantes, maximo = _reserva_de_dados(sheet)
    return min(maximo - restantes, max(1, maximo // 2))


def _gastar_dados_de_vida(char: dict, quantos: int) -> dict:
    """
    Gasta até `quantos` dados da reserva, UM de cada vez, e para quando a vida
    chega ao teto — dado rolado com a vida cheia é dado jogado fora, e é o
    jogador que perderia.

    Cada dado cura 1d[dado] + CON, no mínimo 1 (a mesma conta de antes). O teto
    é o efetivo: exaustão 4 corta a cura na metade do PV máximo.
    """
    s = char["sheet"]
    restantes, maximo = _reserva_de_dados(s)
    faces   = _dado_de_vida(s)
    con_mod = _modifier(int(s.get("constituicao", 10) or 10))
    teto    = _hp_max_efetivo(s)
    antes   = int(s.get("vida_atual", 0) or 0)

    rolagens = []
    vida = antes
    while len(rolagens) < quantos and restantes > 0 and vida < teto:
        r = random.randint(1, faces)
        rolagens.append(r)
        restantes -= 1
        vida = min(teto, vida + max(1, r + con_mod))

    if rolagens:
        s["vida_atual"] = vida
        s["hit_dice_remaining"] = restantes
    return {"rolagens": rolagens, "faces": faces, "con_mod": con_mod,
            "antes": antes, "depois": vida, "restantes": restantes,
            "maximo": maximo}


def _linha_de_rolagem(g: dict) -> str:
    n = len(g["rolagens"])
    con = f" {g['con_mod']:+d} CON por dado" if g["con_mod"] else ""
    return (f"{n}d{g['faces']}: [{' + '.join(str(r) for r in g['rolagens'])}]{con}"
            f" = +{g['depois'] - g['antes']} PV")


def _em_combate() -> bool:
    return bool((memory.campaign.get("combat_state") or {}).get("is_active"))


def _passar_hora_do_descanso_curto(sheet: dict) -> None:
    """
    O descanso curto dura uma hora. Avança o relógio UMA vez para o grupo —
    no primeiro que descansa; os outros descansam na mesma hora, igual ao
    descanso longo faz com as 8 horas.
    """
    agora = _agora_em_horas()
    ja_passou = any(
        (c.get("sheet") or {}).get("ultimo_descanso_curto") == agora
        for c in memory.campaign.get("characters", {}).values()
        if c.get("sheet") is not sheet
    )
    if not ja_passou:
        advance_time(1, "descanso curto")
    sheet["ultimo_descanso_curto"] = _agora_em_horas()


def short_rest(char_name: str, hit_dice: int = -1) -> str:
    """
    Descanso curto (1 hora): o personagem gasta dados de vida da RESERVA para
    curar. Não restaura mana. A reserva só volta no descanso longo, e pela
    metade — é ela
    que impede descanso curto em série de curar o grupo inteiro de graça.

    Se a tela de descanso estiver disponível, prefira offer_rest("curto"):
    quantos dados gastar é escolha do jogador.

    Args:
        char_name: Nome do personagem.
        hit_dice:  Quantos dados de vida gastar. -1 (padrão) gasta até metade
                   do nível, parando quando a vida enche. 0 descansa sem
                   gastar dado.
    """
    char, err = _get_char(char_name, allow_dead=True)
    if not char:
        return err
    if char.get("status") == "morto":
        return f"Erro: {char['name']} está morto — descanso não cura quem morreu."
    if _em_combate():
        return (f"Erro: Impossível descansar — há um combate em andamento.\n"
                f"   Encerre o combate com end_combat() antes de descansar.")

    s = char["sheet"]
    restantes, maximo = _reserva_de_dados(s)
    try:
        pedido = int(hit_dice)
    except (TypeError, ValueError):
        pedido = -1
    quantos = max(1, int(s.get("nivel", 1) or 1) // 2) if pedido < 0 else pedido

    _passar_hora_do_descanso_curto(s)
    g = _gastar_dados_de_vida(char, quantos)
    # Surto de Ação, Segunda Fôlego e Canalizar Divindade voltam aqui — é a
    # hora do descanso curto que os devolve no SRD, e sem isto o contador que
    # o motor passou a cobrar seria uma via de mão única.
    _usos_voltaram = restaurar_usos(char, "curto")
    (char.get("sheet") or {}).pop("assinatura_usada", None)
    if _tem_habilidade(char, "restauracao de feiticaria"):
        _s_rf = char["sheet"]
        _pts = int(usos_restantes(char, "Fonte de Magia") or 0)
        _s_rf.setdefault("usos", {})["pontos de feiticaria"] = min(
            int(usos_maximos(char, "Fonte de Magia") or 0), _pts + 4)
    memory.save_campaign()

    linhas = [f"{char['name']} faz um descanso curto (1 hora — agora {_hora_legivel()})."]
    if g["rolagens"]:
        linhas.append(f"   Rola {_linha_de_rolagem(g)}")
    elif quantos > 0 and restantes == 0:
        linhas.append("   Sem dados de vida na reserva: a hora passa, mas não cura. "
                      "O descanso longo devolve até metade dos dados.")
    elif quantos > 0:
        linhas.append("   Vida já estava no máximo: nenhum dado gasto.")
    linhas.append(f"   Vida: {g['antes']} → {g['depois']}/{s['vida_max']}{_nota_teto(s)}")
    linhas.append(f"   Dados de vida: {g['restantes']}/{g['maximo']}")
    if _usos_voltaram:
        linhas.append("   Recuperado: " + ", ".join(sorted(_usos_voltaram)))
    return "\n".join(linhas)


def use_hit_die(char_name: str, count: int = 1) -> str:
    """
    Gasta dados de vida da reserva para curar (1d[dado] + CON por dado).
    A reserva tem tantos dados quanto o nível; o descanso longo devolve
    até metade dela.
    Para de rolar quando a vida enche — não desperdiça dado.

    Use quando o jogador escolhe gastar dados de vida específicos.

    Args:
        char_name: Nome do personagem.
        count:     Número de dados de vida a usar (padrão: 1).
    """
    char, err = _get_char(char_name, allow_dead=True)
    if not char:
        return err
    if char.get("status") == "morto":
        return f"Erro: {char['name']} está morto — dado de vida não cura quem morreu."
    if _em_combate():
        return ("Erro: Dados de vida se gastam em descanso, não no meio do combate.")

    s = char["sheet"]
    restantes, maximo = _reserva_de_dados(s)
    if restantes <= 0:
        return (
            f"Erro: {char['name']} não tem dados de vida disponíveis (0/{maximo}).\n"
            f"   O descanso longo devolve até metade dos dados."
        )
    if int(s.get("vida_atual", 0) or 0) >= _hp_max_efetivo(s):
        return (f"Nota: {char['name']} já está com a vida no máximo"
                f"{_nota_teto(s)} — nenhum dado gasto.")

    try:
        pedido = max(1, int(count))
    except (TypeError, ValueError):
        pedido = 1
    g = _gastar_dados_de_vida(char, pedido)
    memory.save_campaign()

    return (
        f"{char['name']} usa {_linha_de_rolagem(g)}\n"
        f"   {g['antes']} → {g['depois']}/{s['vida_max']}{_nota_teto(s)}\n"
        f"   Dados de vida restantes: {g['restantes']}/{g['maximo']}"
    )


def long_rest(char_name: str) -> str:
    """
    Descanso longo (~8 horas): restaura toda a vida e toda a mana.
    Remove condições temporárias (exceto Doença e Maldição).
    Reseta os contadores de Testes de Morte.
    Use quando o grupo encontra um local seguro para dormir.

    Args:
        char_name: Nome do personagem.
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    # Bloqueia descanso longo durante combate ativo
    cs = memory.campaign.get("combat_state", {})
    if cs.get("is_active"):
        return (
            f"Erro: Impossível descansar — {char_name} está em combate!\n"
            f"   Encerre o combate com end_combat() antes de descansar."
        )

    s = char["sheet"]

    # UM POR 24 HORAS. Sem o relógio, long_rest() era um botão de vida cheia
    # que o grupo apertava depois de cada luta — o "dia de aventura" do 5e,
    # que é o recurso que faz mana e habilidades diárias significarem algo,
    # simplesmente não existia.
    agora  = _agora_em_horas()
    ultimo = s.get("ultimo_descanso_longo")
    if ultimo is not None and agora - int(ultimo) < 24:
        faltam = 24 - (agora - int(ultimo))
        return (
            f"Erro: {char['name']} já descansou nas últimas 24 horas "
            f"({agora - int(ultimo)}h atrás). Faltam **{faltam}h**.\n"
            f"   Agora: {_hora_legivel()}. Um descanso longo por dia — é o que\n"
            f"   faz mana e poderes diários serem recurso.\n"
            f"   Se o grupo forçar a marcha sem dormir, use "
            f"add_exhaustion('{char['name']}', 1, 'noite em claro')."
        )

    # O descanso CONSOME 8 horas do mundo. Avança o relógio uma vez só, no
    # primeiro personagem a descansar — os outros dormem na mesma noite.
    if ultimo is None or agora - int(ultimo) >= 24:
        _grupo_ja_avancou = any(
            (c.get("sheet") or {}).get("ultimo_descanso_longo") == agora
            for c in memory.campaign.get("characters", {}).values()
        )
        if not _grupo_ja_avancou:
            advance_time(8, "descanso longo")
    s["ultimo_descanso_longo"] = _agora_em_horas()

    # Descanso longo remove UM nível de exaustão (PHB). É o único jeito de
    # sair dela sem magia — e por isso o relógio importa: sem 24h, sem alívio.
    #
    # Tem que vir ANTES de restaurar a vida. Quem dorme com exaustão 4 acorda
    # com 3, e em 3 não há corte de PV máximo: restaurar antes deixaria o
    # personagem na metade da vida por uma exaustão que ele já não tem.
    _exa_antes = _exaustao(s)
    if _exa_antes > 0:
        s["exaustao"] = _exa_antes - 1

    s["vida_atual"] = _hp_max_efetivo(s)
    if s.get("_forma_selvagem"):
        from rpg import criaturas
        criaturas.voltar(char, "descanso longo")
    s["mana_atual"] = s["mana_max"]
    s.pop("circulos_altos_usados", None)
    # O longo devolve TUDO: quem dorme a noite inteira também teve a hora do
    # descanso curto.
    restaurar_usos(char, "longo")
    s.pop("assinatura_usada", None)
    s.pop("lampejos", None)          # novos dados de Lampejos de Adivinhação
    dados_antes, dados_max = _reserva_de_dados(s)
    s["hit_dice_remaining"] = dados_antes + _dados_devolvidos_no_longo(s)
    s["death_saves_sucessos"] = 0
    s["death_saves_falhas"]   = 0
    # PV temporários expiram no descanso longo; a concentração também cai.
    temp_perdidos   = _temp_hp(s)
    s["vida_temp"]  = 0
    conc_msg        = _break_concentration(char, "descanso longo")

    if char.get("status") in ("inconsciente", "ferido"):
        char["status"] = "vivo"

    # Remove condições temporárias (com duração definida)
    conds_antes = s.get("condicoes", [])
    # Condições sem duração (indefinidas) são mantidas; com duração são removidas
    # Exceção: "doença" e "maldição" não são curadas por descanso
    persistentes = {"doença", "doenca", "maldição", "maldicao", "amaldiçoado", "amaldicoado"}
    # O filtro antigo removia justamente as persistentes: doença e maldição
    # sumiam numa noite de sono, ao contrário do que o comentário acima diz.
    s["condicoes"] = [c for c in conds_antes
                      if isinstance(c, dict)
                      and ((c.get("nome") or "").lower() in persistentes
                           or c.get("duracao") is None)]

    removidas = len(conds_antes) - len(s["condicoes"])
    cond_msg  = f"\n   {removidas} condição(ões) temporária(s) removida(s)." if removidas else ""

    memory.save_campaign()
    return (
        f"{char['name']} faz um descanso longo.\n"
        f"   Vida restaurada: {s['vida_atual']}/{s['vida_max']}{_nota_teto(s)}\n"
        f"   Mana restaurada: {s['mana_max']}/{s['mana_max']}\n"
        f"   Dados de vida: {dados_antes} → {s['hit_dice_remaining']}/{dados_max}"
        f" (o descanso longo devolve até metade)"
        f"{cond_msg}"
        + (f"\n   {temp_perdidos} PV temporários expiraram." if temp_perdidos else "")
        + (f"\n   {conc_msg}" if conc_msg else "")
    )


# ── Tela de descanso ("A Fogueira") ────────────────────────────────────────
# Descansar era uma frase no chat e o motor decidia tudo: quantos dados de vida
# rolar, quem descansava. No 5e quem escolhe é o JOGADOR, um dado de cada vez,
# vendo quanto curou — guardar dado para depois é a decisão que dá peso à
# reserva.
#
# Quem decide SE dá para descansar continua sendo o mestre: é a ficção que diz
# se o acampamento é seguro. Ele chama offer_rest(); a tela abre para o jogador;
# ao concluir, a tela manda [DESCANSO RESOLVIDO NA TELA] e o mestre narra.
#
# A proposta mora na campanha (não no navegador) porque é estado do mundo: o
# grupo está parado descansando, e isso vale em qualquer aba ou aparelho.

_TIPOS_DE_DESCANSO = {"curto": "curto", "short": "curto",
                      "longo": "longo", "long": "longo"}


def _grupo_com_ficha() -> list[dict]:
    return [c for c in memory.campaign.get("characters", {}).values()
            if memory.is_party_member(c) and (c.get("sheet") or {})]


def _descanso_proposto() -> dict | None:
    d = memory.campaign.get("descanso_proposto")
    return d if isinstance(d, dict) and d.get("tipo") in ("curto", "longo") else None


def _situacao_descanso_longo(sheet: dict) -> tuple[bool, int]:
    """(pode descansar agora, horas que faltam). A regra é a do long_rest."""
    ultimo = sheet.get("ultimo_descanso_longo")
    if ultimo is None:
        return True, 0
    passou = _agora_em_horas() - int(ultimo)
    return passou >= 24, max(0, 24 - passou)


def offer_rest(kind: str, reason: str = "") -> str:
    """
    Abre a TELA DE DESCANSO para o jogador. Chame quando a ficção permitir
    descansar (lugar seguro, sem combate) e o grupo quiser parar.

    Na tela o jogador gasta os dados de vida um a um (descanso curto) ou
    confirma a noite de sono (descanso longo). NÃO chame short_rest,
    use_hit_die ou long_rest por ele enquanto a tela estiver aberta: quando
    ele concluir chega [DESCANSO RESOLVIDO NA TELA], e aí você narra.

    Args:
        kind:   "curto" (1 hora) ou "longo" (8 horas, um por dia).
        reason: Onde e como descansam (ex: "acampamento na clareira").
    """
    tipo = _TIPOS_DE_DESCANSO.get((kind or "").strip().lower())
    if not tipo:
        return "Erro: Tipo de descanso inválido. Use \"curto\" ou \"longo\"."
    if _em_combate():
        return "Erro: Impossível descansar — há um combate em andamento."
    grupo = _grupo_com_ficha()
    if not grupo:
        return "Erro: Nenhum personagem com ficha no grupo para descansar."

    atual = _descanso_proposto()
    if atual:
        if atual["tipo"] == tipo:
            return f"Nota: O descanso {tipo} já está aberto na tela do jogador."
        if atual.get("gastos"):
            return ("Erro: Há um descanso curto em andamento com dados já gastos. "
                    "O jogador precisa concluí-lo na tela antes de outro descanso.")

    # O id identifica ESTA proposta para a tela saber se já abriu por ela. Vem
    # de um contador que sobrevive à proposta: se viesse da própria proposta,
    # que é apagada ao concluir, o próximo descanso nasceria com o mesmo id e a
    # tela acharia que já tinha aberto.
    contador = int(memory.campaign.get("descansos_oferecidos", 0) or 0) + 1
    memory.campaign["descansos_oferecidos"] = contador
    memory.campaign["descanso_proposto"] = {
        "id": contador, "tipo": tipo, "motivo": (reason or "").strip(),
        "hora": _agora_em_horas(), "gastos": {},
    }
    memory.save_campaign()

    linhas = [f"Descanso {tipo} aberto na TELA DE DESCANSO para o jogador"
              + (f" ({reason.strip()})." if (reason or "").strip() else ".")]
    if tipo == "curto":
        linhas.append("   Quem decide quantos dados de vida gastar é o JOGADOR. "
                      "Não chame short_rest/use_hit_die por ele.")
    else:
        sem = []
        for c in grupo:
            pode, faltam = _situacao_descanso_longo(c["sheet"])
            if not pode:
                sem.append(f"{c.get('name')} (faltam {faltam}h)")
        if sem:
            linhas.append("   Ainda não podem fazer descanso longo: " + ", ".join(sem) + ".")
        linhas.append("   Não chame long_rest por ele.")
    linhas.append("   Aguarde [DESCANSO RESOLVIDO NA TELA] para narrar.")
    return "\n".join(linhas)


def rest_snapshot() -> dict:
    """Estado do descanso para a tela (JSON-serializável)."""
    proposta = _descanso_proposto()
    grupo = []
    for c in _grupo_com_ficha():
        s = c["sheet"]
        restantes, maximo = _reserva_de_dados(s)
        teto   = _hp_max_efetivo(s)
        vida   = int(s.get("vida_atual", 0) or 0)
        morto  = c.get("status") == "morto"
        pode_longo, faltam = _situacao_descanso_longo(s)
        exa = _exaustao(s)

        # Por que o botão de dado está travado — a tela mostra o motivo em vez
        # de só apagar o botão.
        if morto:
            bloqueio = "morto"
        elif restantes <= 0:
            bloqueio = "sem dados na reserva"
        elif vida >= teto:
            bloqueio = "vida no máximo"
        else:
            bloqueio = ""

        grupo.append({
            "nome":            c.get("name", ""),
            "classe":          s.get("classe", ""),
            "nivel":           int(s.get("nivel", 1) or 1),
            "morto":           morto,
            "vida_atual":      vida,
            "vida_max":        int(s.get("vida_max", 0) or 0),
            "teto":            teto,
            "vida_temp":       _temp_hp(s),
            "mana_atual":      int(s.get("mana_atual", 0) or 0),
            "mana_max":        int(s.get("mana_max", 0) or 0),
            "dado":            _dado_de_vida(s),
            "con_mod":         _modifier(int(s.get("constituicao", 10) or 10)),
            "dados_restantes": restantes,
            "dados_max":       maximo,
            # O cartão do descanso longo mostra quantos voltam; a conta fica
            # aqui para a regra da metade não ir parar no navegador.
            "dados_no_longo":  _dados_devolvidos_no_longo(s),
            "gastos_agora":    int(((proposta or {}).get("gastos") or {}).get(c.get("name", ""), 0)),
            "bloqueio_dado":   bloqueio,
            "exaustao":        exa,
            "exaustao_efeito": EXAUSTAO_EFEITOS.get(exa, "") if exa else "",
            "condicoes":       [cd.get("nome", "") for cd in (s.get("condicoes") or [])
                                if isinstance(cd, dict)],
            "pode_longo":      pode_longo,
            "faltam_horas":    faltam,
        })

    return {
        "tem_descanso": bool(proposta),
        "descanso": ({"id": proposta.get("id", 0), "tipo": proposta["tipo"],
                      "motivo": proposta.get("motivo", ""),
                      "com_gastos": bool(proposta.get("gastos"))}
                     if proposta else None),
        "em_combate": _em_combate(),
        "hora": _hora_legivel(),
        "grupo": grupo,
    }


def rest_action(action: str, char: str = "") -> dict:
    """
    Aplica UMA intenção da tela de descanso.

    actions: dado | concluir | cancelar

    Só despacho, como nas telas de loja e nível: quem cura, gasta a reserva,
    passa o relógio e aplica o limite de 24h é use_hit_die / short_rest /
    long_rest — as mesmas funções do mestre.
    """
    a = (action or "").lower().strip()
    proposta = _descanso_proposto()

    def _resposta(ok, msg):
        return {"ok": ok, "message": msg, "snapshot": rest_snapshot()}

    if a not in ("dado", "concluir", "cancelar"):
        return _resposta(False, f"Erro: Ação '{action}' desconhecida.")
    if not proposta:
        return _resposta(False, "Erro: Nenhum descanso aberto. Peça ao mestre para acampar.")

    if a == "dado":
        if proposta["tipo"] != "curto":
            return _resposta(False, "Erro: Dados de vida se gastam no descanso curto.")
        msg = use_hit_die(char, 1)
        ok = not msg.lstrip().startswith(("Aviso:", "Erro:", "Nota:"))
        if ok:
            alvo, _ = _get_char(char, allow_dead=True)
            nome = alvo.get("name", char) if alvo else char
            gastos = proposta.setdefault("gastos", {})
            gastos[nome] = int(gastos.get(nome, 0)) + 1
            memory.save_campaign()
        return _resposta(ok, msg)

    if a == "cancelar":
        # Dado gasto já curou. Cancelar agora apagaria a hora de descanso que
        # pagou por essa cura — o mesmo buraco da cura infinita, pela tela.
        if proposta.get("gastos"):
            return _resposta(False, "Erro: Já há dados de vida gastos neste descanso. "
                                    "Conclua o descanso para a hora passar.")
        memory.campaign.pop("descanso_proposto", None)
        memory.save_campaign()
        return _resposta(True, "Descanso cancelado. O grupo segue sem parar.")

    # concluir
    if _em_combate():
        return _resposta(False, "Erro: Um combate começou — não dá para concluir o descanso agora.")
    vivos = [c for c in _grupo_com_ficha() if c.get("status") != "morto"]
    if proposta["tipo"] == "curto":
        for c in vivos:
            short_rest(c["name"], hit_dice=0)       # só a hora; os dados já foram
        gastos = proposta.get("gastos") or {}
        partes = [f"{n}: {q} dado(s)" for n, q in gastos.items() if q]
        msg = (f"Descanso curto concluído — {_hora_legivel()}."
               + (f" Dados gastos: {', '.join(partes)}." if partes
                  else " Ninguém gastou dado de vida."))
        memory.campaign.pop("descanso_proposto", None)
        memory.save_campaign()
        return _resposta(True, msg)

    # Quem pode dormir é decidido ANTES de alguém dormir. O primeiro long_rest
    # avança o relógio 8 horas, e decidir no meio do laço deixava o resultado
    # depender da ordem do grupo: quem descansou há 20h era recusado se viesse
    # primeiro e aceito se viesse depois de alguém ter passado a noite.
    aptos, recusados = [], []
    for c in vivos:
        pode, faltam = _situacao_descanso_longo(c["sheet"])
        if pode:
            aptos.append(c)
        else:
            recusados.append(f"{c['name']} (faltam {faltam}h)")
    descansaram = []
    for c in aptos:
        saida = long_rest(c["name"])
        if saida.lstrip().startswith(("Erro:", "Aviso:")):
            recusados.append(c["name"])
        else:
            descansaram.append(c["name"])
    if not descansaram:
        return _resposta(False, "Erro: Ninguém do grupo pode fazer descanso longo agora: "
                                + ", ".join(recusados) + ".")
    memory.campaign.pop("descanso_proposto", None)
    memory.save_campaign()
    msg = (f"Descanso longo concluído — {_hora_legivel()}. "
           f"Descansaram: {', '.join(descansaram)}."
           + (f" Não puderam: {', '.join(recusados)}." if recusados else ""))
    return _resposta(True, msg)


# ---------------------------------------------------------------------------
# 14. Ajuste manual de atributos
# ---------------------------------------------------------------------------

def set_stat(char_name: str, stat_name: str, value: int) -> str:
    """
    Define manualmente um valor numérico na ficha do personagem.
    Use para ajustes de balanceamento, efeitos de magia ou equipamentos.
    Para moedas, prefira modify_currency. Para CA via armadura, prefira equip_item.

    Args:
        char_name: Nome do personagem.
        stat_name: Atributo a alterar: forca, destreza, constituicao, inteligencia,
                   sabedoria, carisma, ca, vida_max, mana_max, nivel, xp,
                   vida_atual, mana_atual, proficiencia, ouro, prata, cobre.
        value:     Novo valor inteiro.
    """
    char, err = _get_char(char_name, allow_dead=True)
    if not char:
        return err

    VALID = {
        "forca", "destreza", "constituicao", "inteligencia", "sabedoria", "carisma",
        "ca", "vida_max", "mana_max", "nivel", "xp", "vida_atual", "mana_atual",
        "proficiencia", "ouro", "prata", "cobre",
    }
    s = char["sheet"]
    if stat_name.lower() not in VALID:
        return f"Atributo '{stat_name}' inválido. Válidos: {', '.join(sorted(VALID))}."

    key     = stat_name.lower()
    old_val = s.get(key, "?")

    # Se for um atributo (ability score), recalcula os derivados:
    # CON → HP por nível | DES → CA | atributo de conjuração → mana.
    extra = ""
    if key in STAT_NAMES and isinstance(old_val, int):
        old_mod = _modifier(old_val)
        s[key]  = value
        new_mod = _modifier(value)
        delta   = new_mod - old_mod
        nivel   = s.get("nivel", 1)

        if key == "constituicao" and delta:
            hp_adj          = delta * nivel
            s["vida_max"]   = max(1, s.get("vida_max", 1) + hp_adj)
            s["vida_atual"] = max(0, min(s["vida_max"], s.get("vida_atual", 0) + hp_adj))
            extra += f"\n   Vida máx: {hp_adj:+d} → {s['vida_max']}"

        # CON e SAB entram na CA de quem tem Defesa Sem Armadura (bárbaro e
        # monge), então o recálculo não é mais só da destreza.
        if key in ("destreza", "constituicao", "sabedoria"):
            ca_antes = s.get("ca", 10)
            _recalculate_ca(char)
            if s.get("ca", ca_antes) != ca_antes:
                extra += f"\n   CA: {ca_antes} → {s['ca']}"

        # O pool de mana NÃO muda ao alterar o atributo de conjuração — na
        # variante de Pontos de Magia ele depende só do nível. O atributo
        # segue afetando CD de magia e ataques mágicos, não o tamanho do pool.
    else:
        s[key] = value

    memory.save_campaign()
    return f"{char['name']}: {stat_name} {old_val} → {value}.{extra}"


# ---------------------------------------------------------------------------
# 15. Sistema de Iniciativa
# ---------------------------------------------------------------------------

def _default_npc_sheet() -> dict:
    """
    Ficha mínima razoável para NPCs sem stats específicos.
    Aproxima CR 1/4 — suficiente para combate funcionar imediatamente.
    Para chefes, use create_character_sheet() ANTES de roll_initiative().
    """
    return {
        "classe":               "npc",
        "raca":                 "humano",
        "nivel":                1,
        "xp":                   0,
        "xp_proximo":           100,
        "forca":                12,
        "destreza":             12,
        "constituicao":         12,
        "inteligencia":         10,
        "sabedoria":            10,
        "carisma":              10,
        "vida_atual":           12,
        "vida_max":             12,
        "mana_atual":           0,
        "mana_max":             0,
        "ca":                   12,
        "proficiencia":         2,
        "hit_die":              8,
        "ouro":                 0,
        "prata":                0,
        "cobre":                0,
        "equipamentos":         {"armadura": None, "escudo": None, "arma_principal": None, "amuleto": None},
        "condicoes":            [],
        "death_saves_sucessos": 0,
        "death_saves_falhas":   0,
    }


def _marcar_lado_na_entrada(char: dict) -> None:
    """
    Congela o lado de quem entra na luta (memory.lado_no_combate).

    A dedução lê o status ("inimigo") — e o status do inimigo vira "morto"
    assim que ele cai. Sem congelar, o goblin derrotado deixava de ser inimigo
    no meio da luta, e matar todos não encerrava o combate. Quem é do grupo
    não é marcado: entrar e sair do grupo é decisão do jogo, não da luta.
    """
    if not isinstance(char, dict):
        return
    if char.get("lado") or memory.is_party_member(char):
        return
    char["lado"] = memory.lado_no_combate(char)


def _combatente_para_a_luta(name: str) -> tuple[dict, bool]:
    """O personagem pronto para lutar: quem não existe ou não tem ficha ganha a
    ficha padrão de NPC. Devolve (personagem, se a ficha foi criada agora)."""
    key  = memory.char_key(name)
    char = memory.campaign["characters"].get(key)
    if not char:
        memory.campaign["characters"][key] = {
            "name":        name,
            "description": "NPC — registrado ao iniciar combate (ficha padrão).",
            "traits":      "",
            "status":      "inimigo",
            # Nome que a campanha não conhecia e entrou na luta: inimigo.
            # Quem já era personagem da história entra como aliado, a menos
            # que o mestre marque (memory.lado_no_combate, set_combat_side).
            "lado":        "inimigo",
            "notes":       "",
            "sheet":       _default_npc_sheet(),
            "inventario":  [],
            "habilidades": [],
        }
        return memory.campaign["characters"][key], True
    _marcar_lado_na_entrada(char)
    if char.get("sheet") is None:
        char["sheet"]       = _default_npc_sheet()
        char["inventario"]  = char.get("inventario") or []
        char["habilidades"] = char.get("habilidades") or []
        return char, True
    return char, False


def _rolar_iniciativa(name: str, char: dict) -> dict:
    dex_mod = _modifier(char["sheet"]["destreza"])
    roll    = random.randint(1, 20)
    total   = roll + dex_mod
    sign    = "+" if dex_mod >= 0 else ""
    return {
        "name":       name,
        "initiative": total,
        "roll":       roll,
        "mod":        dex_mod,
        "log":        f"d20={roll} {sign}{dex_mod} = **{total}**",
    }


def _entrar_no_combate_em_andamento(names: list[str], cs: dict) -> str:
    """
    roll_initiative com a luta já rolando.

    Quem já está na ordem fica como está: ordem, rodada, vez, log e vida.
    Se todos os nomes já lutam, é uma chamada repetida e nada muda. Quem é
    novo (reforço, aliado que chegou) rola e entra no lugar do total dele; se
    esse lugar já passou nesta rodada, age a partir da próxima.
    """
    ordem  = list(cs.get("initiative_order") or [])
    idx    = int(cs.get("current_turn_index", 0) or 0)
    vez    = ordem[idx] if 0 <= idx < len(ordem) else "?"
    rodada = cs.get("round", 1)

    na_luta = {memory.char_key(n) for n in ordem}
    novos, vistos = [], set()
    for n in names:
        k = memory.char_key(n)
        if k not in na_luta and k not in vistos:
            vistos.add(k)
            novos.append(n)

    if not novos:
        return (f"Nota: o combate já está em andamento (Rodada {rodada}, vez de **{vez}**). "
                f"A iniciativa NÃO foi rolada de novo e nada mudou.\n"
                f"   Ordem: {' → '.join(ordem)}\n"
                f"   Siga a luta. Para pôr alguém novo nela, chame roll_initiative só "
                f"com o nome de quem chegou.")

    totais = cs.setdefault("iniciativas", {})
    zonas  = _zonas()
    linhas = [f"Combate em andamento (Rodada {rodada}, vez de **{vez}**). Entram na luta:"]
    for name in novos:
        char, criado = _combatente_para_a_luta(name)
        _normalize_for_new_combat(char)
        r = _rolar_iniciativa(name, char)
        # Sem o total de quem já lutava (combate de antes desta regra), entra
        # no fim da ordem.
        pos = len(ordem)
        for i, outro in enumerate(ordem):
            total_outro = totais.get(memory.char_key(outro))
            if total_outro is not None and r["initiative"] > total_outro:
                pos = i
                break
        ordem.insert(pos, name)
        totais[memory.char_key(name)] = r["initiative"]
        if pos <= idx:
            idx += 1
        quando = "age ainda nesta rodada" if pos > idx else "age a partir da próxima rodada"
        if len(zonas) > 1 and _zona_de(name) not in zonas:
            _por_zona(name, zonas[0] if memory.luta_com_o_grupo(char) else zonas[-1])
        linhas.append(f"  + {name}: {r['log']} — {quando}"
                      + (" (ficha padrão)" if criado else ""))

    cs["initiative_order"]   = ordem
    cs["current_turn_index"] = idx
    _log_combat_event("combat_join", msg="Entram na luta: " + ", ".join(novos), names=novos)
    memory.save_campaign()
    linhas.append(f"\n   Ordem: {' → '.join(ordem)}")
    return "\n".join(linhas)


def _surpreso(ch: dict | None) -> bool:
    return any(_norm_txt(c.get("nome", "") if isinstance(c, dict) else str(c)) == "surpreso"
               for c in ((ch or {}).get("sheet") or {}).get("condicoes") or [])


def _marcar_surpresos(nomes: list[str], surpresos: str) -> list[str]:
    """
    Quem foi pego de surpresa: Surpreso até o fim do primeiro turno dele (não
    age, não se move, não reage). `surpresos` é "inimigos", "grupo" ou nomes
    separados por vírgula. O talento Alerta impede.
    """
    alvo = _norm_txt(surpresos or "")
    if not alvo:
        return []
    escolhidos = []
    for nome in nomes:
        ch = memory.campaign["characters"].get(memory.char_key(nome))
        if not ch:
            continue
        do_grupo = memory.luta_com_o_grupo(ch)
        if alvo in ("inimigos", "inimigo", "enemies") and do_grupo:
            continue
        if alvo in ("grupo", "party", "aliados") and not do_grupo:
            continue
        if alvo not in ("inimigos", "inimigo", "enemies", "grupo", "party", "aliados") and \
                memory.char_key(nome) not in {memory.char_key(n.strip()) for n in surpresos.split(",")}:
            continue
        if _tem_habilidade(ch, "alerta", "alert"):
            continue
        conds = ch.setdefault("sheet", {}).setdefault("condicoes", [])
        if not _surpreso(ch):
            conds.append({"nome": "Surpreso", "duracao": None, "ate_fim_turno_de": memory.char_key(nome)})
        escolhidos.append(ch.get("name", nome))
    return escolhidos


def roll_initiative(characters_names: str, allies: str = "", surprised: str = "") -> str:
    """
    Rola iniciativa para todos os participantes do combate (aliados e inimigos).
    Ordena do maior para o menor resultado e salva no combat_state.
    DEVE ser chamada no INÍCIO de todo combate.

    QUEM LUTA DO LADO DO GRUPO: o grupo do jogador entra sozinho do lado dele.
    Todo NPC que entrar na luta é tratado como INIMIGO, a não ser que você o
    cite em `allies` — é assim que o mercador que o grupo escolta, o guarda
    que socorre ou o companheiro emprestado lutam com vocês em vez de contra.
    O lado fica gravado; para mudar depois (traição, rendição) use
    set_combat_side(). A resposta mostra quem entrou de cada lado.

    Para inimigos GENÉRICOS desconhecidos, cria fichas padrão automaticamente
    (HP 12, CA 12). Para CHEFES importantes, chame create_character_sheet()
    ANTES desta ferramenta para definir stats específicos.

    Com o combate JÁ em andamento, NÃO reinicia a luta: quem já está na ordem
    fica como está, e só os nomes novos (reforços) rolam e entram na ordem.
    Chame UMA vez por combate.

    Args:
        characters_names: Nomes separados por vírgula. Ex: "Aria, Goblin, Orc Líder"
        allies:           NPCs que lutam AO LADO do grupo, separados por vírgula.
                          Ex: allies="Pip" numa escolta. Eles não entram no
                          grupo: sem XP, sem nível e sem saque.
        surprised:        Quem foi pego de surpresa (emboscada): "inimigos",
                          "grupo" ou nomes separados por vírgula. Surpreso não
                          age, não se move e não reage no primeiro turno. Decida
                          pela Furtividade de quem embosca contra a Percepção
                          passiva de quem é emboscado. O talento Alerta impede.
    """
    names = (
        characters_names if isinstance(characters_names, list)
        else [n.strip() for n in characters_names.split(",") if n.strip()]
    )
    if not names:
        return "Informe ao menos um personagem."
    from rpg import criaturas as _criaturas
    names = names + [n for n in _criaturas.companheiros_de(names)
                     if memory.char_key(n) not in {memory.char_key(x) for x in names}]

    # Marca os aliados ANTES de montar a ordem: o lado de cada um é congelado
    # ao entrar na luta (_marcar_lado_na_entrada).
    for nome in (allies if isinstance(allies, list)
                 else [n.strip() for n in (allies or "").split(",")]):
        if not nome:
            continue
        aliado = memory.campaign["characters"].get(memory.char_key(nome))
        if aliado and not memory.is_party_member(aliado):
            aliado["lado"] = "aliado"
            if (aliado.get("status") or "").lower() == "inimigo":
                aliado["status"] = "vivo"

    # Luta já rolando: rolar de novo zerava a ordem, a rodada e o log no meio
    # do combate. Numa campanha o mestre chamou roll_initiative três vezes
    # seguidas na mesma emboscada, e a tela reiniciou a luta a cada uma.
    cs_atual = memory.campaign.get("combat_state") or {}
    if cs_atual.get("is_active") and cs_atual.get("initiative_order"):
        return _entrar_no_combate_em_andamento(names, cs_atual)

    results      = []
    auto_created = []

    # Inspiração Superior Aprimorada: rolar iniciativa devolve a Inspiração.
    for _nm_is in names:
        _ch_is = memory.campaign["characters"].get(memory.char_key(_nm_is))
        if _ch_is and _tem_habilidade(_ch_is, "inspiracao superior aprimorada"):
            ((_ch_is.get("sheet") or {}).get("usos") or {}).pop("inspiracao de bardo", None)

    for name in names:
        char, criado = _combatente_para_a_luta(name)
        if criado:
            auto_created.append(name)

        # Combate NOVO: limpa estados transitórios herdados da luta anterior
        # — ninguém entra dormindo nem "inconsciente" com a vida cheia.
        _normalize_for_new_combat(char)

        results.append(_rolar_iniciativa(name, char))

    results.sort(key=lambda x: x["initiative"], reverse=True)

    cs = memory.campaign.setdefault("combat_state", {})
    # Emboscada no acampamento: o descanso aberto na tela foi interrompido.
    # Sem isto a tela de descanso reabriria depois da luta como se nada tivesse
    # acontecido — e o jogador concluiria uma hora de sossego que não houve.
    memory.campaign.pop("descanso_proposto", None)
    cs["is_active"]          = True
    cs["initiative_order"]   = [r["name"] for r in results]
    # O total de cada um fica guardado para quem entrar no meio da luta
    # achar o lugar dele na ordem.
    cs["iniciativas"]        = {memory.char_key(r["name"]): r["initiative"] for r in results}
    cs["current_turn_index"] = 0
    cs["round"]              = 1
    # Combate NOVO: zera o rastreamento de turno (não herdar do anterior).
    cs["turn_resolved"]      = False
    cs["turn_auto_advanced"] = False
    cs["turn_token"]         = cs.get("turn_token", 0) + 1
    cs["log"]                = []     # log limpo a cada combate
    cs["result"]             = None   # resultado do combate anterior limpo
    cs["agiram"]             = []     # quem já teve um turno (Assassinato)
    cs["cobertura"]          = {}
    _surpresos = _marcar_surpresos([r["name"] for r in results], surprised)
    _log_combat_event("combat_start", msg="Combate iniciado",
                      order=[r["name"] for r in results])
    # A economia do turno também é do combate anterior: sem isto o primeiro
    # da ordem herdava a "Ação usada" do último turno da luta passada e
    # começava a luta sem poder atacar (relatado numa partida: "várias vezes
    # o primeiro personagem na vez fica sem ação"). É também o início do
    # turno dele: recargas e efeitos de "no início do seu turno" valem.
    _reset_turn_economy(cs)

    memory.save_campaign()

    lines = ["Iniciativa rolada! Ordem de combate:"]
    for i, r in enumerate(results):
        marker = " ◀ PRIMEIRO" if i == 0 else ""
        lines.append(f"  {i + 1}. {r['name']}: {r['log']}{marker}")
    lines.append(f"\nRodada 1 — vez de: **{results[0]['name']}**")
    if _surpresos:
        lines.append(f"Surpresos (não agem, não se movem e não reagem no primeiro turno): "
                     f"{', '.join(_surpresos)}")

    # Quem entrou de cada lado, em voz alta: o erro de lado é invisível até
    # alguém atacar quem não devia, e aqui ele aparece antes do primeiro turno.
    por_lado = {"grupo": [], "aliado": [], "inimigo": []}
    for r in results:
        ch = memory.campaign["characters"].get(memory.char_key(r["name"]))
        por_lado[memory.lado_no_combate(ch)].append(r["name"])
    lines.append("\nLados — grupo: " + (", ".join(por_lado["grupo"]) or "ninguém")
                 + (f" · aliados: {', '.join(por_lado['aliado'])}" if por_lado["aliado"] else "")
                 + " · contra: " + (", ".join(por_lado["inimigo"]) or "ninguém"))
    if por_lado["inimigo"]:
        lines.append("Se algum deles luta COM o grupo, corrija agora: "
                     "set_combat_side(nome, \"aliado\").")

    if auto_created:
        lines.append(
            f"\nNota: Ficha padrão criada para: {', '.join(auto_created)} "
            "(HP 12, CA 12). Use create_character_sheet para customizar."
        )

    return "\n".join(lines)


def next_turn() -> str:
    """
    Avança para o próximo turno na ordem de iniciativa.
    Pula AUTOMATICAMENTE personagens mortos, inconscientes ou que fugiram.
    Se todos estiverem fora de combate, encerra automaticamente.
    Chame UMA vez quando a ação de um personagem terminar — nunca duas vezes seguidas.
    """
    cs = memory.campaign.get("combat_state", {})
    if not cs.get("is_active"):
        return "Nenhum combate ativo. Use roll_initiative para iniciar."

    order = cs.get("initiative_order", [])
    if not order:
        return "Ordem de iniciativa vazia. Rode roll_initiative primeiro."

    # Auto-cura: se o atual morreu/fugiu "no lugar", desencalha o ponteiro
    # ANTES da trava de idempotência (senão ela reportaria um morto).
    _tk_before_heal = cs.get("turn_token", 0)
    _heal_current_turn()
    cs = memory.campaign.get("combat_state", {})
    if not cs.get("is_active"):
        return "Combate encerrado — nenhum combatente restante."
    order = cs.get("initiative_order", [])
    if not order:
        return "Combate encerrado."

    # Se a auto-cura JÁ avançou o ponteiro (o atual havia saído de combate),
    # ESSE foi o avanço deste next_turn() — não avançar de novo (senão pula
    # um combatente vivo). Apenas reporta.
    if cs.get("turn_token", 0) != _tk_before_heal:
        cs["turn_auto_advanced"] = False
        memory.save_campaign()
        idx = cs.get("current_turn_index", 0)
        cur = order[idx] if 0 <= idx < len(order) else "?"
        round_n = cs.get("round", 1)
        order_str = " → ".join(f"[{n}]" if i == idx else n for i, n in enumerate(order))
        return (
            f"Turno avançado (combatente anterior saiu de combate) — "
            f"Rodada {round_n}\nVez de: **{cur}**\n   Ordem: {order_str}"
        )

    # Trava de idempotência: se a ferramenta de ação (attack_roll / use_ability /
    # roll_death_save) já avançou o turno automaticamente, next_turn() não avança
    # de novo — apenas confirma quem é a vez atual e limpa a flag.
    if cs.get("turn_auto_advanced", False):
        cs["turn_auto_advanced"] = False
        memory.save_campaign()
        idx      = cs.get("current_turn_index", 0)
        current  = order[idx] if idx < len(order) else "?"
        round_n  = cs.get("round", 1)
        order_str = " → ".join(f"[{n}]" if i == idx else n for i, n in enumerate(order))
        return (
            f"Nota: Turno já avançado pela ferramenta de ação.\n"
            f"Rodada {round_n} — vez de: **{current}**\n"
            f"   Ordem: {order_str}"
        )

    OUT_OF_COMBAT = OUT_OF_COMBAT_STATUSES   # inclui "dormindo" → pula a vez

    idx       = cs.get("current_turn_index", 0)
    round_num = cs.get("round", 1)
    new_round = False
    skipped   = []
    # O turno do atual termina aqui: as condições dele descontam um turno.
    fim_msgs  = _fim_do_turno(order[idx], cs.get("turn_token", 0)) if 0 <= idx < len(order) else []

    for _ in range(len(order) + 1):
        idx += 1
        if idx >= len(order):
            idx        = 0
            round_num += 1
            new_round  = True

        current_name = order[idx]
        char         = memory.campaign["characters"].get(memory.char_key(current_name))
        status       = (char.get("status", "") if char else "").lower()

        if status in OUT_OF_COMBAT:
            skipped.append(f"{current_name} ({status})")
            continue

        cs["current_turn_index"] = idx
        cs["round"]              = round_num
        cs["turn_resolved"]      = False
        cs["turn_token"]         = cs.get("turn_token", 0) + 1  # avanço real
        _reset_turn_economy(cs)
        memory.save_campaign()

        skip_msg  = f"\nPulados: {', '.join(skipped)}" if skipped else ""
        round_msg = f"\nNova rodada! Rodada {round_num} começa." if new_round else ""
        # O que os chefes lendários fizeram na virada (ver _inicio_de_turno).
        lend_msg = "".join("\n" + m for m in fim_msgs + list(cs.pop("_lendarias_msg", None) or []))
        return (
            f"Turno avançado — Rodada {round_num}{round_msg}{skip_msg}{lend_msg}\n"
            f"Vez de: **{current_name}**\n"
            f"   Ordem: {' → '.join(f'[{n}]' if i == idx else n for i, n in enumerate(order))}"
        )

    cs["is_active"]          = False
    cs["initiative_order"]   = []
    cs["current_turn_index"] = 0
    cs["round"]              = 1
    memory.save_campaign()
    return "Todos os personagens estão fora de combate.\nCombate encerrado automaticamente."


def end_combat() -> str:
    """
    Encerra o combate atual, limpa a ordem de iniciativa e desativa o rastreador de turnos.
    Chame após a derrota de todos os inimigos ou fuga do combate.
    """
    cs = memory.campaign.get("combat_state", {})
    _log_combat_event("combat_end", msg="Combate encerrado")
    from rpg import criaturas
    criaturas.limpar(fim_do_combate=True)
    cs.pop("efeitos_de_zona", None)
    cs["is_active"]           = False
    cs["initiative_order"]    = []
    cs["current_turn_index"]  = 0
    cs["round"]               = 1
    # Acorda quem ficou DORMINDO — o efeito de Sleep não persiste após a
    # luta (jamais deve vazar para o próximo combate ou para a ficha).
    for _ch in memory.campaign.get("characters", {}).values():
        _wake_sleeper(_ch)
        # Concentração e reação também não vazam para a próxima luta.
        _sh = _ch.get("sheet") or {}
        if _sh.get("concentracao"):
            _sh["concentracao"] = None
        _sh.pop("reacao_rodada", None)
        # A fera volta a ser druida, e o Frenesi cobra a exaustão.
        if _sh.get("_forma_selvagem") and not _sh["_forma_selvagem"].get("permanente"):
            from rpg import criaturas
            criaturas.voltar(_ch, "fim do combate")
        if _sh.pop("_frenesi", None):
            _sh["exaustao"] = min(6, int(_sh.get("exaustao", 0) or 0) + 1)
        # Efeitos de item duram o combate; as chamas também não passam dele.
        if _sh.get("efeitos"):
            # _efeitos traz também os efeitos dos itens vestidos, que não se
            # gravam: gravados, o Anel de Proteção valia mesmo sem o anel.
            _sh["efeitos"] = [e for e in _efeitos(_sh)
                              if e.get("ate") != "fim_do_combate" and not e.get("de_item")]
        if _sh.get("condicoes"):
            # Duração em turnos só existe dentro do combate; as chamas também.
            # Condição de magia (Imobilizar Pessoa, Cegueira, Lentidão: um
            # minuto) também acaba com a luta — só o encanto, que dura horas,
            # continua (rpg/encantos.py).
            _sh["condicoes"] = [c for c in _sh["condicoes"]
                                if not (isinstance(c, dict)
                                        and ((c.get("nome") or "").lower() == "queimando"
                                             or _turnos_restantes(c) > 0
                                             or (c.get("magia") and not c.get("encanto"))))]
    # A poção de Força do Gigante que acabou com a luta devolve a Força.
    for _ch_a in memory.campaign.get("characters", {}).values():
        if memory.is_party_member(_ch_a) and (_ch_a.get("sheet") or {}).get("equipamentos") is not None:
            _recalculate_ca(_ch_a)
    recolhido = _recolher_municao_e_arremessos()
    memory.save_campaign()
    return "Combate encerrado. Iniciativa e rastreador de turnos limpos." + recolhido


# ---------------------------------------------------------------------------
# Recrutamento de NPC para o grupo
# ---------------------------------------------------------------------------

def recruit_character(npc_name: str, role: str = "aliado") -> str:
    """
    Recruta um NPC para o grupo do jogador, transformando-o em aliado ativo.
    Use quando um NPC convencido, salvo ou contratado passa a acompanhar o grupo.

    O personagem é marcado como 'aliado' e passa a:
    • Receber XP junto com o grupo após combates
    • Aparecer no painel de personagens como membro do grupo
    • Participar de combates como aliado (não inimigo)
    • Ganhar turnos automáticos via execute_npc_turn() se o mestre quiser

    Se o NPC ainda não tem uma ficha D&D completa (tem apenas ficha padrão
    com classe='npc'), o sistema preserva a ficha genérica mas muda o status.
    Para um aliado importante, crie a ficha completa antes com
    create_character_sheet() se quiser regras de classe reais.

    Args:
        npc_name: Nome exato do NPC a recrutar.
        role:     'aliado' (padrão) — membro do grupo.
                  'neutro' — acompanha mas não é aliado de combate.
    """
    key  = memory.char_key(npc_name)
    char = memory.campaign["characters"].get(key)

    if not char:
        return (
            f"Erro: '{npc_name}' não encontrado na campanha. "
            f"Crie a ficha primeiro com create_character_sheet() ou roll_initiative()."
        )

    # ── Verificação de disparidade de nível ─────────────────────────────────
    npc_sheet   = char.get("sheet") or {}
    npc_nivel   = npc_sheet.get("nivel", 1)

    # Calcula nível médio do grupo usando a definição canônica de grupo
    # (memory.is_party_member: party_member, protagonista ou campaign["party"]).
    # Exclui NPCs soltos, mortos/inimigos/fugidos e o próprio NPC sendo recrutado.
    party_chars = [
        c for c in memory.campaign.get("characters", {}).values()
        if memory.is_party_member(c)
        and c.get("status") not in ("morto", "inimigo", "fugiu")
        and memory.char_key(c["name"]) != key
    ]
    if party_chars:
        avg_nivel = sum((c.get("sheet") or {}).get("nivel", 1) for c in party_chars) / len(party_chars)
    else:
        avg_nivel = 1

    level_gap = npc_nivel - avg_nivel

    # Bloqueia recrutamento de NPCs muito mais poderosos — narrativamente impossível
    if level_gap >= 10:
        return (
            f"RECRUTAMENTO BLOQUEADO — disparidade de poder extrema.\n"
            f"   {char['name']} é Nível {npc_nivel}; grupo em torno de Nível {avg_nivel:.0f}.\n"
            f"   Um personagem {int(level_gap)} níveis acima não tem motivo narrativo para "
            f"se juntar como subordinado a um grupo iniciante.\n"
            f"   ALTERNATIVAS VÁLIDAS:\n"
            f"   • Mentor: {char['name']} oferece treinamento ou informação ao grupo.\n"
            f"   • Missão: aceita ajudar SE o grupo completar uma tarefa para ele.\n"
            f"   • Aliança temporária: coopera em uma situação específica sem sair com o grupo.\n"
            f"   • Promessa futura: 'Quando forem dignos, voltem me ver.'\n"
            f"   Não chame recruit_character() — narre uma dessas alternativas."
        )

    # Aviso para disparidade moderada (5-9 níveis) — possível com justificativa forte
    if level_gap >= 5:
        warning = (
            f"Aviso: {char['name']} é Nível {npc_nivel}, "
            f"{int(level_gap)} níveis acima do grupo (Nível ~{avg_nivel:.0f}).\n"
            f"   Recrutamento só faz sentido com justificativa narrativa muito forte\n"
            f"   (dívida de vida, missão pessoal urgente, único capaz de ajudar, etc.).\n"
        )
    else:
        warning = ""
    # ────────────────────────────────────────────────────────────────────────

    old_status   = char.get("status", "desconhecido")
    valid_roles  = {"aliado", "neutro"}
    role_clean   = role.strip().lower() if role.strip().lower() in valid_roles else "aliado"

    char["status"] = role_clean

    # Garante que o personagem apareça na lista do grupo (campo party_member)
    char["party_member"] = True

    sheet  = char.get("sheet") or {}
    classe = sheet.get("classe") or "npc"
    nivel  = sheet.get("nivel", 1)
    hp     = sheet.get("vida_atual", "?")
    hp_max = sheet.get("vida_max", "?")

    memory.save_campaign()

    role_label = "membro do grupo" if role_clean == "aliado" else "acompanhante neutro"
    classe_note = (
        " (ficha genérica — use create_character_sheet() para dar classe real)"
        if classe.lower() == "npc" else f" | Classe: {classe} | Nível: {nivel}"
    )
    return (
        f"{warning}"
        f"{char['name']} agora é {role_label}!\n"
        f"   Status anterior: {old_status} → {role_clean}\n"
        f"   Vida: {hp}/{hp_max} | CA: {sheet.get('ca', '?')}{classe_note}\n"
        f"   {char['name']} passará a receber XP junto com o grupo e participará "
        f"de combates como aliado."
    )


# ---------------------------------------------------------------------------
# Macro-tool: Resolução de Saving Throw Interativo
# ---------------------------------------------------------------------------

def _registrar_salvaguarda_pendente(alvo: dict, atributo: str, cd: int, por: dict, hab: dict, *,
                                    dano: int = 0, tipo: str = "", metade: bool = True, condicao=None) -> None:
    cs = memory.campaign.setdefault("combat_state", {})
    cs.setdefault("salvaguardas_pendentes", []).append({
        "alvo": alvo.get("name", ""), "atributo": atributo, "cd": int(cd), "por": por.get("name", ""),
        "magia": hab.get("nome", ""), "dano": int(dano or 0), "tipo": tipo, "metade": bool(metade),
        "condicao": condicao or ""})


def resolve_saving_throw(
    target_name: str,
    attribute: str,
    dc: int,
    player_roll: int,
    damage_if_fail: int,
    damage_type: str = "",
) -> str:
    """
    Resolve um Saving Throw interativo após o jogador informar o resultado do dado.
    Aplica o dano correto (total se falhar, metade se passar) e avança o turno.

    Use esta ferramenta APÓS o jogador responder à pergunta "Role um teste de X CD Y!".
    Ela substitui a sequência make_skill_check + modify_hp + next_turn().

    Args:
        target_name:     Nome do personagem que está resistindo (geralmente o jogador).
        attribute:       Atributo do saving throw (ex: 'destreza', 'constituicao').
        dc:              Classe de Dificuldade do efeito (ex: 14).
        player_roll:     Valor TOTAL informado pelo jogador (dado + modificador já somados).
        damage_if_fail:  Dano total caso o saving throw falhe.
        damage_type:     Tipo do dano ('fogo', 'frio', 'veneno', 'radiante', 'ácido',
                         'elétrico', 'necrótico', 'psíquico', 'trovejante', 'força',
                         'cortante', 'perfurante', 'concussão'). Informe SEMPRE que
                         souber — é o que decide se o alvo resiste, é imune ou
                         vulnerável. Vazio = dano sem tipo, sem modificador.
    """
    char, err = _get_char(target_name)
    if not char:
        return err

    # O que a magia deixou guardado para esta salvaguarda (a condição, se
    # quem passa leva metade ou nada) manda sobre o que o Mestre informou.
    cs_sv = memory.campaign.get("combat_state") or {}
    pend = next((p for p in cs_sv.get("salvaguardas_pendentes") or []
                 if memory.char_key(p.get("alvo", "")) == memory.char_key(char["name"])), None)
    metade = True
    condicao = None
    if pend:
        cs_sv["salvaguardas_pendentes"].remove(pend)
        attribute = pend.get("atributo") or attribute
        dc = int(pend.get("cd") or dc)
        damage_if_fail = int(pend.get("dano", damage_if_fail) or 0) if "dano" in pend else damage_if_fail
        damage_type = pend.get("tipo") or damage_type
        metade = bool(pend.get("metade", True))
        condicao = pend.get("condicao") or None

    s          = char["sheet"]
    attr_key   = attribute.lower()
    mod        = _modifier(s.get(attr_key, 10))
    passou     = player_roll >= dc
    dano_real  = (damage_if_fail // 2 if metade else 0) if passou else damage_if_fail

    sign       = "+" if mod >= 0 else ""
    resultado  = "PASSOU" if passou else "FALHOU"
    reducao    = ((" (metade do dano)" if metade else " (nenhum dano)") if passou else " (dano completo)")

    result = (
        f"Saving Throw — {char['name']} ({attribute.capitalize()} CD {dc})\n"
        f"   Resultado informado: **{player_roll}** {sign}{mod}(mod) vs CD {dc} → {resultado}\n"
        f"   Dano aplicado: **{dano_real}**{reducao}\n"
    )

    _res      = _apply_damage(char, dano_real, damage_type,
                              source_name="saving throw", arma_magica=True)
    hp_antes  = _res["hp_antes"]
    hp_depois = _res["hp_depois"]
    pct       = hp_depois / s["vida_max"] if s["vida_max"] > 0 else 0

    result += "".join(f"   {n}\n" for n in _res["notas"])
    result += f"   {char['name']}: {hp_antes} → {hp_depois}/{s['vida_max']}"
    if hp_depois == 0:
        result += _mark_at_zero_hp(char)
    elif pct <= 0.25:
        result += " Estado crítico!"
    # A condição que a falha traz (Paralisado do Imobilizar Pessoa, Caído do Redemoinho).
    if condicao and not passou and hp_depois > 0:
        from rpg import tracos as _tracos_sv
        if isinstance(condicao, dict):
            if _imune_a_condicao(char, condicao.get("nome", "")):
                result += f"\n   {char['name']} é imune a {condicao.get('nome')}."
            else:
                s.setdefault("condicoes", []).append(dict(condicao))
                result += f"\n   {char['name']}: **{str(condicao.get('nome', '')).upper()}**"
                _acaba = _como_a_condicao_acaba(condicao)
                if _acaba:
                    result += f"\n   {_acaba}"
        else:
            por_sv = memory.campaign["characters"].get(memory.char_key((pend or {}).get("por", ""))) or {"name": ""}
            result += "\n   " + _tracos_sv._por_condicao(por_sv, char, str(condicao))

    # Ainda há salvaguardas da mesma magia esperando o dado: o turno espera.
    faltam = [p.get("alvo") for p in cs_sv.get("salvaguardas_pendentes") or []]
    if faltam:
        memory.save_campaign()
        return result + (f"\n   Ainda esperam o dado: {', '.join(faltam)} — resolve_saving_throw de "
                         f"cada um antes do próximo turno.")

    # O save ocorre durante o turno do CONJURADOR (use_ability pausou sem
    # avançar). O ponteiro ainda aponta para ele → avança a partir do atual.
    memory.save_campaign()
    result += _auto_advance_turn()
    memory.save_campaign()
    return result


# ---------------------------------------------------------------------------
# Lista exportável para tools.py
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Balanceamento de encontros — D&D 5e (DMG p.82 e p.274)
# ---------------------------------------------------------------------------

_XP_THRESHOLDS = {
    1:  (25,50,75,100),      2:  (50,100,150,200),
    3:  (75,150,225,400),    4:  (125,250,375,500),
    5:  (250,500,750,1100),  6:  (300,600,900,1400),
    7:  (350,750,1100,1700), 8:  (450,900,1400,2100),
    9:  (550,1100,1600,2400),10: (600,1200,1900,2800),
    11: (800,1600,2400,3600),12: (1000,2000,3000,4500),
    13: (1100,2200,3400,5100),14:(1250,2500,3800,5700),
    15: (1400,2800,4300,6400),16:(1600,3200,4800,7200),
    17: (2000,3900,5900,8800),18:(2100,4200,6300,9500),
    19: (2400,4900,7300,10900),20:(2800,5700,8500,12700),
}

_CR_XP = {
    0:10, 0.125:25, 0.25:50, 0.5:100,
    1:200, 2:450, 3:700, 4:1100, 5:1800,
    6:2300, 7:2900, 8:3900, 9:5000, 10:5900,
    11:7200, 12:8400, 13:10000, 14:11500, 15:13000,
    16:15000, 17:18000, 18:20000, 19:22000, 20:25000,
}

_CR_STATS = {
    0:    {"hp":4,  "ca":12,"atk":2,"dmg":"1d4",    "f":8, "d":10,"c":10,"i":6, "w":10,"ch":6},
    0.125:{"hp":11, "ca":13,"atk":3,"dmg":"1d6+1",  "f":10,"d":12,"c":10,"i":8, "w":10,"ch":8},
    0.25: {"hp":18, "ca":13,"atk":3,"dmg":"1d6+2",  "f":12,"d":14,"c":12,"i":8, "w":11,"ch":8},
    0.5:  {"hp":30, "ca":13,"atk":3,"dmg":"1d8+2",  "f":13,"d":13,"c":13,"i":10,"w":10,"ch":10},
    1:    {"hp":45, "ca":13,"atk":4,"dmg":"2d6+2",  "f":14,"d":12,"c":14,"i":10,"w":12,"ch":10},
    2:    {"hp":65, "ca":13,"atk":4,"dmg":"2d6+3",  "f":16,"d":12,"c":14,"i":10,"w":12,"ch":11},
    3:    {"hp":85, "ca":13,"atk":4,"dmg":"2d8+3",  "f":16,"d":14,"c":15,"i":12,"w":12,"ch":12},
    4:    {"hp":105,"ca":14,"atk":5,"dmg":"2d10+3", "f":17,"d":14,"c":16,"i":12,"w":13,"ch":12},
    5:    {"hp":130,"ca":15,"atk":6,"dmg":"3d8+4",  "f":18,"d":14,"c":17,"i":12,"w":14,"ch":13},
    6:    {"hp":155,"ca":15,"atk":6,"dmg":"3d10+4", "f":18,"d":14,"c":18,"i":12,"w":14,"ch":14},
    7:    {"hp":180,"ca":15,"atk":6,"dmg":"4d8+4",  "f":19,"d":14,"c":18,"i":14,"w":14,"ch":14},
    8:    {"hp":205,"ca":16,"atk":7,"dmg":"4d10+5", "f":20,"d":14,"c":19,"i":14,"w":15,"ch":15},
    9:    {"hp":230,"ca":16,"atk":7,"dmg":"5d8+5",  "f":20,"d":14,"c":19,"i":14,"w":15,"ch":16},
    10:   {"hp":255,"ca":17,"atk":7,"dmg":"5d10+5", "f":21,"d":14,"c":20,"i":14,"w":16,"ch":16},
    11:   {"hp":280,"ca":17,"atk":8,"dmg":"6d8+5",  "f":22,"d":14,"c":20,"i":16,"w":16,"ch":17},
    12:   {"hp":305,"ca":17,"atk":8,"dmg":"6d10+6", "f":22,"d":14,"c":21,"i":16,"w":17,"ch":17},
    13:   {"hp":330,"ca":18,"atk":8,"dmg":"7d8+6",  "f":23,"d":14,"c":21,"i":16,"w":17,"ch":18},
    14:   {"hp":355,"ca":18,"atk":8,"dmg":"7d10+6", "f":23,"d":14,"c":22,"i":16,"w":18,"ch":18},
    15:   {"hp":380,"ca":18,"atk":8,"dmg":"8d8+7",  "f":24,"d":14,"c":22,"i":16,"w":18,"ch":19},
    16:   {"hp":400,"ca":18,"atk":9,"dmg":"8d10+7", "f":24,"d":14,"c":23,"i":18,"w":18,"ch":19},
    17:   {"hp":445,"ca":19,"atk":10,"dmg":"9d10+7","f":25,"d":14,"c":23,"i":18,"w":19,"ch":20},
    18:   {"hp":478,"ca":19,"atk":10,"dmg":"10d10+8","f":26,"d":14,"c":24,"i":18,"w":19,"ch":20},
    19:   {"hp":511,"ca":19,"atk":11,"dmg":"11d10+8","f":27,"d":14,"c":24,"i":18,"w":20,"ch":21},
    20:   {"hp":544,"ca":19,"atk":11,"dmg":"12d10+8","f":28,"d":14,"c":25,"i":18,"w":20,"ch":22},
}

_MONSTER_FLAVORS = {
    0:    ["rato comum","morcego","vagabundo"],
    0.125:["bandido raso","kobold","cultista novato"],
    0.25: ["goblin","esqueleto","lobo","zumbi","acólito"],
    0.5:  ["orc","hobgoblin","gnoll","espadachim","lobo enorme"],
    1:    ["bugbear","ogro pequeno","espião","cultista de elite"],
    2:    ["ogro","sahuagin","cavaleiro","mago aprendiz","centauro"],
    3:    ["manticora","mago","líder bandido","minotauro","wyvern jovem"],
    4:    ["assassino","draco-tartaruga","gigante das colinas"],
    5:    ["troll","gigante de pedra","mago veterano"],
    6:    ["ciclope","dragão jovem branco","lich aprendiz"],
    7:    ["gigante das nuvens","dragão prata jovem"],
    8:    ["hidra","archmago","gigante do gelo"],
    9:    ["lich menor","gigante de fogo","dragão adulto branco"],
    10:   ["deva","dragão adulto rubro","demônio chefe"],
    11:   ["djinn","dragão adulto bronze","beholder"],
    12:   ["arcimago veterano","dragão adulto verde","marilith"],
    13:   ["beholder antigo","dragão adulto azul","rakshasa"],
    14:   ["dragão adulto vermelho","lich poderoso"],
    15:   ["mestre lich","dragão anciente jovem","demônio supremo"],
    16:   ["dragão anciente bronze","anjo solar"],
    17:   ["dragão anciente azul","leviatã"],
    18:   ["dragão anciente vermelho","guardião de plano"],
    19:   ["semideus caído","lich-rei"],
    20:   ["tarrasque","deus encarnado","rei demônio"],
}


def _enc_multiplier(count: int) -> float:
    if count <= 1:  return 1.0
    if count == 2:  return 1.5
    if count <= 6:  return 2.0
    if count <= 10: return 2.5
    if count <= 14: return 3.0
    return 4.0


def _xp_to_cr(target: float):
    return min(_CR_XP.keys(), key=lambda cr: abs(_CR_XP[cr] - target))


def _cr_label(cr) -> str:
    return {0.125:"1/8", 0.25:"1/4", 0.5:"1/2"}.get(cr, str(int(cr)))


def _enc_block(label: str, count: int, cr, budget: int) -> str:
    s  = _CR_STATS.get(cr, _CR_STATS[1])
    fl = (_MONSTER_FLAVORS.get(cr) or ["criatura genérica"])[0]
    total = int(_CR_XP[cr] * count * _enc_multiplier(count))
    diff  = total - budget
    diff_str = f"({'+' if diff>=0 else ''}{diff} XP)" if diff else "(no orçamento)"
    return (
        f"━━━ {label} ━━━\n"
        f"  {count}× **{fl.title()}** — CR {_cr_label(cr)}\n"
        f"  HP {s['hp']}  |  CA {s['ca']}  |  Ataque +{s['atk']}  |  Dano {s['dmg']}\n"
        f"  FOR {s['f']} DES {s['d']} CON {s['c']} INT {s['i']} SAB {s['w']} CAR {s['ch']}\n"
        f"  XP do encontro: {total} {diff_str}"
    )


# ---------------------------------------------------------------------------
# Progressão automática de classe — chamada pelo grant_xp
# ---------------------------------------------------------------------------

def _apply_class_features(char: dict, sheet: dict, new_level: int) -> list[str]:
    """
    Adiciona automaticamente as habilidades de classe do novo nível.
    Também concede sub-features de arquétipos já escolhidos cujo nível
    de desbloqueio bate com o novo nível (ex.: Crítico Superior do
    Campeão libera no 15º). Não duplica habilidades já existentes.

    Retorna lista de nomes adicionados (incluindo sub-features de arquétipo).
    """
    classe   = sheet.get("classe", "").lower()
    features = CLASS_LEVEL_FEATURES.get(classe, {}).get(new_level, [])
    existing = {h.get("nome", "").lower() for h in char.get("habilidades", [])}
    added: list[str] = []

    for feat_name in features:
        if feat_name.lower() in existing:
            continue
        desc_data = CLASS_FEATURE_DESCS.get(feat_name, {
            "descricao": f"Habilidade de {classe.capitalize()} adquirida no nível {new_level}.",
            "custo_mana": 0, "dado": "",
        })
        char.setdefault("habilidades", []).append({
            "nome":       feat_name,
            "descricao":  desc_data.get("descricao", ""),
            "custo_mana": desc_data.get("custo_mana", 0),
            "dado":       desc_data.get("dado", ""),
        })
        existing.add(feat_name.lower())
        added.append(feat_name)

    # Sub-features de arquétipos: para cada feature de arquétipo já escolhida,
    # concede o que o novo nível desbloqueou. Idempotente (não duplica).
    for arch_feat in ARCHETYPE_FEATURES.keys():
        if _get_feature_choice(char, arch_feat):
            sub_added = _apply_archetype_features(char, arch_feat)
            for s in sub_added:
                if s.lower() not in {a.lower() for a in added}:
                    added.append(s)

    return added


# ===========================================================================
# GRIMÓRIO — magias conhecidas, limites e o catálogo da classe
# ---------------------------------------------------------------------------
# Até aqui o motor sabia APRENDER uma magia e não sabia quantas o personagem
# podia ter. A tabela de limites vivia só no JavaScript do modal de edição;
# o learn_spell, que é o caminho do mestre, não a conhecia. Uma regra em dois
# lugares, um deles no navegador — o mesmo desenho que já fez a recarga do
# chefe valer num caminho e não no outro.
#
# As tabelas são as que o jogo já usava no modal (truques e magias conhecidas
# por nível, D&D 5e). Para as classes que no livro PREPARAM magias (clérigo,
# druida, mago) o número vale como o tamanho do repertório.
# ===========================================================================

_TRUQUES_CONHECIDOS = {
    "bardo":      [2,2,2,3,3,3,3,3,3,4,4,4,4,4,4,4,4,4,4,4],
    "clerigo":    [3,3,3,4,4,4,4,4,4,5,5,5,5,5,5,5,5,5,5,5],
    "druida":     [2,2,2,3,3,3,3,3,3,4,4,4,4,4,4,4,4,4,4,4],
    "feiticeiro": [4,4,4,5,5,5,6,6,6,6,6,6,6,6,6,6,6,6,6,6],
    "bruxo":      [2,2,2,3,3,3,4,4,4,4,4,4,4,4,4,4,4,4,4,4],
    "mago":       [3,3,3,4,4,4,4,4,4,5,5,5,5,5,5,5,5,5,5,5],
}
_MAGIAS_CONHECIDAS = {
    "mago":        [6,8,10,12,14,16,18,20,22,24,26,28,30,32,34,36,38,40,42,44],
    "clerigo":     [3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22],
    "druida":      [3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22],
    "paladino":    [0,3,3,4,4,5,5,6,6,7,7,8,8,9,9,10,10,11,11,12],
    "bardo":       [4,5,6,7,8,9,10,11,12,14,15,15,16,18,19,19,20,22,22,22],
    "feiticeiro":  [2,3,4,5,6,7,8,9,10,11,12,12,13,13,14,14,15,15,15,15],
    "bruxo":       [2,3,4,5,6,7,8,9,10,10,11,11,12,12,13,13,14,14,14,15],
    "patrulheiro": [0,2,3,3,4,4,5,5,6,6,7,7,8,8,9,9,10,10,11,11],
}
_CUSTO_PARA_NIVEL = {v: k for k, v in SPELL_MANA_COST.items()}


def _limite_de_magias(sheet: dict) -> dict | None:
    """{"truques": n, "magias": n} da classe no nível; None se não conjura."""
    c = _norm_txt(sheet.get("classe", ""))
    if c not in _MAGIAS_CONHECIDAS:
        return None
    i = max(1, min(20, int(sheet.get("nivel", 1) or 1))) - 1
    return {"truques": (_TRUQUES_CONHECIDOS.get(c) or [0] * 20)[i],
            "magias":  _MAGIAS_CONHECIDAS[c][i]}


def _nivel_maximo_de_magia(sheet: dict) -> int:
    """
    Maior nível de magia que a classe alcança no nível do personagem.

    O learn_spell exigia nível 2L−1 para toda classe, o que é a tabela do
    conjurador PLENO. Paladino e patrulheiro são meio-conjuradores: magia de
    1º no nível 2, de 2º no 5, de 3º no 9 — com a regra antiga um paladino de
    nível 3 aprendia magia de 2º círculo.
    """
    c = _norm_txt(sheet.get("classe", ""))
    nivel = max(1, min(20, int(sheet.get("nivel", 1) or 1)))
    if c in _HALF_CASTERS:
        return 0 if nivel < 2 else min(5, (nivel - 1) // 4 + 1)
    if c in _FULL_CASTERS:
        return min(9, (nivel + 1) // 2)
    return 0


def _nomes_srd(nome: str) -> set[str]:
    base = (nome or "").strip().lower()
    return {base, SPELL_PT_TO_EN.get(base, base)} - {""}


def _e_magia(hab: dict) -> bool:
    """
    Habilidade que é magia. Toda magia do jogo — learn_spell, wizard, magias
    padrão da classe — tem a descrição começando por "[escola]"; as de agora
    em diante também têm nivel_magia.
    """
    if (isinstance(hab.get("nivel_magia"), int)
            or str(hab.get("descricao", "")).lstrip().startswith("[")):
        return True
    # Fichas importadas ou escritas à mão trazem a magia sem a marca, só com
    # o nome ("Chama Sagrada"). Se o nome é de uma magia do SRD que o motor
    # conhece, é magia — senão é um poder próprio da campanha, que não ocupa
    # vaga de magia.
    nome = str(hab.get("nome", "")).strip().lower()
    return nome in SPELL_PT_TO_EN or nome in SPELL_LEVEL_OVERRIDE


def _nivel_da_magia(hab: dict) -> int:
    """
    Nível de uma magia da ficha. Ficha antiga não gravava o nível: vem da
    tabela de níveis do SRD pelo nome; senão, truque se não custa mana; senão,
    do custo pela tabela de pontos de magia; senão, 1.
    """
    if isinstance(hab.get("nivel_magia"), int):
        return hab["nivel_magia"]
    for n in _nomes_srd(hab.get("nome_srd", "")) | _nomes_srd(hab.get("nome", "")):
        if n in SPELL_LEVEL_OVERRIDE:
            return SPELL_LEVEL_OVERRIDE[n]
    custo = int(hab.get("custo_mana", 0) or 0)
    if custo == 0:
        return 0
    return _CUSTO_PARA_NIVEL.get(custo, 1)


def _magias_da_ficha(char: dict) -> list[dict]:
    return [h for h in (char.get("habilidades") or []) if isinstance(h, dict) and _e_magia(h)]


def _contagem_de_magias(char: dict) -> tuple[int, int]:
    """(truques, magias de nível 1+) que o personagem conhece."""
    niveis = [_nivel_da_magia(h) for h in _magias_da_ficha(char)]
    return sum(1 for n in niveis if n == 0), sum(1 for n in niveis if n > 0)


def _ja_conhece_magia(char: dict, *nomes: str) -> bool:
    procurados = set().union(*(_nomes_srd(n) for n in nomes))
    for h in _magias_da_ficha(char):
        if procurados & (_nomes_srd(h.get("nome", "")) | _nomes_srd(h.get("nome_srd", ""))):
            return True
    return False


def _magia_conhecida_localmente(spell_name: str, en_query: str) -> dict | None:
    """
    A magia no formato de resposta do Open5e, montada só com o que o motor
    tem sem rede: as magias padrão das classes (com descrição) e a tabela de
    níveis do SRD (só o nível). None se o motor não a conhece.
    """
    alvo = _nomes_srd(spell_name) | _nomes_srd(en_query)
    classes, entrada = [], None
    for classe, pool in DEFAULT_SPELLS_BY_CLASS.items():
        for sp in pool:
            if _nomes_srd(sp.get("nome", "")) & alvo:
                entrada = entrada or sp
                slug = _classe_en(classe)
                if slug and slug not in classes:
                    classes.append(slug)
    nivel = next((SPELL_LEVEL_OVERRIDE[n] for n in alvo if n in SPELL_LEVEL_OVERRIDE), None)
    if entrada is None and nivel is None:
        return None

    escola, desc = "", "Magia do SRD (descrição indisponível sem conexão)."
    if entrada:
        texto = entrada.get("descricao", "")
        if texto.startswith("[") and "]" in texto:
            escola, desc = texto[1:texto.index("]")], texto[texto.index("]") + 1:].strip()
        else:
            desc = texto
        if nivel is None:
            nivel = _nivel_da_magia(entrada)
    return {
        "name": spell_name, "spell_level": nivel, "school": escola, "desc": desc,
        "dnd_class": ", ".join(c.capitalize() for c in classes),
        "damage": {"damage_dice": (entrada or {}).get("dado", "")},
        "concentration": "concentra" in desc.lower(), "ritual": False, "range": "",
    }


def _resumir(texto: str, limite: int) -> str:
    if len(texto) <= limite:
        return texto
    corte = texto[:limite].rsplit(" ", 1)[0].rstrip(".,;:")
    return corte + "…"


# ── O SRD fala inglês ──────────────────────────────────────────────────────
# O catálogo do Grimório vem do Open5e: "Cure Wounds", "Evocation", e a
# descrição em inglês. A mesa é em português, e o jogador escolhia magia por
# um nome que não é o que ele lê na ficha depois de aprendê-la — a ficha usa
# o nome em português.
#
# O que dá para traduzir sem inventar: o NOME, pela mesma tabela que o
# learn_spell já usa para achar a magia no SRD (SPELL_PT_TO_EN, invertida), e
# a ESCOLA, que é um conjunto fechado de oito. A DESCRIÇÃO fica como veio, e
# a tela diz que é do SRD, em inglês — menos a das magias que o motor já
# descreve em português (DEFAULT_SPELLS_BY_CLASS).
_MAGIA_EN_PARA_PT = {en.lower(): pt for pt, en in SPELL_PT_TO_EN.items()}

_ESCOLA_PT = {
    "abjuration": "Abjuração", "conjuration": "Conjuração", "divination": "Adivinhação",
    "enchantment": "Encantamento", "evocation": "Evocação", "illusion": "Ilusão",
    "necromancy": "Necromancia", "transmutation": "Transmutação",
}


def _nome_de_magia_pt(nome_srd: str) -> str:
    """Nome em português da magia do SRD, ou "" quando não há tradução."""
    pt = _MAGIA_EN_PARA_PT.get((nome_srd or "").lower().strip(), "")
    return pt.title() if pt else ""


def _escola_pt(escola_srd: str) -> str:
    return _ESCOLA_PT.get((escola_srd or "").lower().strip(), escola_srd or "")


def _descricao_pt_da_magia(nome_pt: str) -> str:
    """
    Descrição em português que o motor já tem para a magia, quando tem.
    DEFAULT_SPELLS_BY_CLASS é a lista de reserva das classes: as mesmas magias
    aparecem no catálogo do SRD, e ali elas já estão descritas em português.
    """
    if not nome_pt:
        return ""
    alvo = _norm_txt(nome_pt)
    for lista in DEFAULT_SPELLS_BY_CLASS.values():
        for sp in lista:
            if _norm_txt(sp.get("nome", "")) == alvo:
                texto = sp.get("descricao", "") or ""
                # A descrição da reserva começa com "[Escola] "; a escola já
                # tem coluna própria no cartão.
                if texto.startswith("[") and "]" in texto:
                    texto = texto[texto.index("]") + 1:].strip()
                return texto
    return ""


def class_spell_catalog(classe: str, max_level: int = 9, query: str = "",
                        spell_level: int | None = None,
                        _status: dict | None = None) -> list[dict]:
    """
    Magias da lista de uma classe até um nível — do Open5e, com as magias
    padrão da classe como reserva quando o SRD não responde.

    Era o corpo da rota /api/dnd/class-spells. Veio para o motor porque agora
    tem dois clientes (o modal de edição e o Grimório) e a tela precisa das
    marcas "já conhece" e "limite", que são regra.

    `_status`, quando passado, recebe {"respondeu": bool}: lista vazia com o
    SRD respondendo é regra (nada a aprender), sem resposta é falha de rede.
    """
    import re
    from rpg.open5e import http as _req

    classe   = (classe or "").lower().strip()
    max_level = max(0, min(int(max_level if max_level is not None else 9), 9))
    query    = (query or "").strip().lower()
    en_class = _classe_en(classe)
    spells: list[dict] = []
    if _status is not None:
        _status["respondeu"] = False

    # document__slug: o Open5e junta o SRD com livros de terceiros (Deep Magic
    # e outros), e a lista da classe vinha com "Black Goat's Blessing" ao lado
    # de "Bless". O jogo diz "SRD" — então é só o SRD.
    params = {"spell_level__lte": max_level, "limit": 100 if query else 250,
              "ordering": "spell_level", "document__slug": "wotc-srd"}
    # `dnd_class__icontains`: o filtro exato casa só o texto inteiro
    # ("Sorcerer, Wizard" != "Wizard") e zera quando combinado com `search`.
    if en_class:
        params["dnd_class__icontains"] = en_class
    if query:
        params["search"] = query
    if spell_level is not None:
        try:
            params["spell_level"] = int(spell_level)
            del params["spell_level__lte"]
        except (TypeError, ValueError):
            pass

    # Classe informada e desconhecida: sem o filtro, a consulta traria a lista
    # de todas as classes. Fica só com a reserva local.
    if classe and not en_class:
        r = None
    else:
        r = _req.get("https://api.open5e.com/v1/spells/", params=params, timeout=6)
    if _status is not None and r is not None:
        _status["respondeu"] = bool(r.status_code)
    if r is not None and r.ok:
        vistos = set()
        for s in r.json().get("results", []):
            nome = s.get("name", "")
            chave = nome.lower().strip()
            if not nome or chave in vistos:
                continue
            vistos.add(chave)
            lvl = int(s.get("spell_level", 0) or 0)
            dado = ""
            dmg = s.get("damage", {})
            if isinstance(dmg, dict):
                dado = dmg.get("damage_dice", "") or ""
                for campo, preferido in (("damage_at_character_level", "1"),
                                         ("damage_at_slot_level", "3")):
                    tabela = dmg.get(campo, {})
                    if not dado and isinstance(tabela, dict) and tabela:
                        dado = tabela.get(preferido) or next(
                            (tabela[k] for k in sorted(tabela, key=lambda x: int(x) if str(x).isdigit() else 99)
                             if tabela[k]), "")
            if not dado:
                m = re.search(r'\d+d\d+(?:\s*[+\-]\s*\d+)?', s.get("desc", "") or "")
                if m:
                    dado = m.group(0).replace(" ", "")
            nome_pt = _nome_de_magia_pt(nome)
            descricao_pt = _descricao_pt_da_magia(nome_pt)
            spells.append({
                # O nome em português é o nome do jogo: é ele que vai para a
                # ficha quando a magia é aprendida, e learn_spell sabe achá-lo
                # no SRD. O nome do SRD vai junto, para o cartão mostrar.
                "nome":         nome_pt or nome,
                "nome_srd":     nome,
                "nivel_magia":  lvl,
                "escola":       _escola_pt(s.get("school", "")),
                # Corta na palavra e marca o corte: "[:250]" deixava "Completely
                # covering the objec" no cartão, e parecia defeito.
                "descricao":    descricao_pt or _resumir(
                    " ".join((s.get("desc", "") or "").split()), 250),
                "em_ingles":    not descricao_pt,
                "custo_mana":   SPELL_MANA_COST.get(lvl, 4),
                "dado":         dado,
                "ritual":       _sim_do_srd(s.get("ritual")),
                "concentracao": _sim_do_srd(s.get("concentration")),
                "alcance":      (s.get("range", "") or "").strip(),
            })
        # A busca textual também casa na descrição ("fireball" traz "Antimagic
        # Field"). Prioriza nome; o sort é estável e preserva a ordem por nível.
        if query:
            spells.sort(key=lambda sp: 0 if query in sp["nome"].lower() else 1)

    if not spells and classe:
        chave_local = next((k for k in DEFAULT_SPELLS_BY_CLASS if _norm_txt(k) == _norm_txt(classe)), classe)
        for sp in DEFAULT_SPELLS_BY_CLASS.get(chave_local, []):
            lvl = _nivel_da_magia(sp)
            texto = sp.get("descricao", "")
            if lvl > max_level and spell_level is None:
                continue
            if spell_level is not None and lvl != int(spell_level):
                continue
            if query and query not in sp.get("nome", "").lower() and query not in texto.lower():
                continue
            escola = texto[1:texto.index("]")] if texto.startswith("[") and "]" in texto else ""
            spells.append({
                "nome": sp["nome"], "nome_srd": "", "nivel_magia": lvl, "escola": escola,
                "descricao": texto[texto.index("]") + 1:].strip() if escola else texto,
                "em_ingles": False,
                "custo_mana": SPELL_MANA_COST.get(lvl, 4), "dado": sp.get("dado", ""),
                "ritual": False, "concentracao": "concentra" in texto.lower(), "alcance": "",
            })
        spells.sort(key=lambda sp: sp["nivel_magia"])
        spells = spells[:50]
    return spells


def _vagas_de_magia(char: dict) -> dict | None:
    limite = _limite_de_magias(char.get("sheet") or {})
    if not limite:
        return None
    truques, magias = _contagem_de_magias(char)
    return {"truques": max(0, limite["truques"] - truques),
            "magias":  max(0, limite["magias"] - magias),
            "truques_usados": truques, "magias_usadas": magias,
            "truques_max": limite["truques"], "magias_max": limite["magias"]}


def _grupo_que_conjura() -> list[dict]:
    return [c for c in memory.campaign.get("characters", {}).values()
            if memory.is_party_member(c) and (c.get("sheet") or {})
            and _limite_de_magias(c["sheet"])]


def grimoire_snapshot(char_name: str = "", query: str = "",
                      spell_level: int | None = None,
                      com_catalogo: bool = True) -> dict:
    """
    Estado do Grimório para a tela (JSON-serializável).

    com_catalogo=False é o que a fila de telas pede a cada turno com a tela
    fechada: só vagas e assinatura, sem ir ao SRD buscar a lista da classe.
    """
    grupo = _grupo_que_conjura()

    def _deve(c):
        v = _vagas_de_magia(c)
        return bool(v and (v["truques"] or v["magias"]))

    alvo = None
    if char_name:
        alvo = next((c for c in grupo if _norm_txt(c.get("name", "")) == _norm_txt(char_name)), None)
    if not alvo:
        # Sem nome, abre em quem tem magia a aprender — é para isso que a tela abre.
        alvo = next((c for c in grupo if _deve(c)), None) or (grupo[0] if grupo else None)

    # A assinatura diz à tela se há vaga NOVA. Cada entrada é "Nome:nível" de
    # quem tem vaga — sem a quantidade de vagas. Com a quantidade, aprender
    # uma magia pelo chat mudava a assinatura e a tela pulava de novo; sem o
    # nível, a vaga aberta por um nível novo parecia a mesma de antes.
    partes = []
    for c in grupo:
        v = _vagas_de_magia(c)
        if v and (v["truques"] or v["magias"]):
            partes.append(f"{c.get('name', '')}:{(c['sheet'].get('nivel') or 1)}")
    base = {"tem_personagem": bool(alvo), "grupo": [c.get("name", "") for c in grupo],
            "devendo": [c.get("name", "") for c in grupo if _deve(c)],
            "assinatura": "|".join(sorted(partes)), "personagem": None, "catalogo": []}
    if not alvo:
        return base

    s = alvo["sheet"]
    vagas = _vagas_de_magia(alvo)
    nivel_max = _nivel_maximo_de_magia(s)
    # Para conjurar fora do combate pela tela: o que acontece ao usar e quem
    # a magia mira (rpg/resolucao.py), como no cartão do combate.
    from rpg import habilidade as _habilidade
    from rpg import resolucao as _resolucao_g

    def _conhecida(h: dict) -> dict:
        r = _habilidade.resolver(h, alvo)
        return {"nome": h.get("nome", ""), "nome_exibido": r["nome"], "nivel": _nivel_da_magia(h),
                "custo_mana": int(h.get("custo_mana", 0) or 0), "dado": h.get("dado", ""),
                "descricao": h.get("descricao", ""), "resumo": r["resumo"],
                "resolucao": r["resolucao"], "resolucao_texto": r["resolucao_texto"],
                "alvo_modo": r["alvo_modo"] or ("si" if r["alvos"] == "si" else ""),
                # Convocar Familiar pede a forma; círculos não fazem sentido aqui.
                "modos": [m for m in r["modos"] if not str(m["id"]).startswith("c")
                          or not str(m["id"])[1:].isdigit()],
                "ritual": bool(_resolucao_g._magia_srd(h) and _resolucao_g._magia_srd(h).get("ritual")),
                "pode_ritual": _resolucao_g.pode_ritual(alvo, h)}

    conhecidas = sorted((_conhecida(h) for h in _magias_da_ficha(alvo)),
                        key=lambda m: (m["nivel"], m["nome"].lower()))

    # Por que a lista pode vir vazia. A tela dizia "A lista da classe não
    # respondeu" para qualquer lista vazia — inclusive a de um patrulheiro de
    # nível 1, que ainda não tem truque nem magia e cuja lista vem vazia por
    # regra, com o SRD respondendo normalmente.
    sem_nada_a_aprender = not (vagas["truques_max"] or vagas["magias_max"])
    status = {}
    catalogo = []
    fonte = (class_spell_catalog(s.get("classe", ""), nivel_max, query, spell_level, _status=status)
             if com_catalogo and not sem_nada_a_aprender else [])
    for sp in fonte:
        if _ja_conhece_magia(alvo, sp["nome"]):
            bloqueio = "já conhece"
        elif sp["nivel_magia"] == 0 and not vagas["truques"]:
            bloqueio = "limite de truques"
        elif sp["nivel_magia"] > 0 and not vagas["magias"]:
            bloqueio = "limite de magias"
        else:
            bloqueio = ""
        catalogo.append({**sp, "bloqueio": bloqueio})

    motivo = ""
    if com_catalogo and not catalogo:
        classe_rotulo = (s.get("classe", "") or "A classe").capitalize()
        if sem_nada_a_aprender:
            primeiro = _primeiro_nivel_com_magia(s.get("classe", ""))
            motivo = (f"{classe_rotulo} ainda não aprende magias no nível "
                      f"{int(s.get('nivel', 1) or 1)}."
                      + (f" As primeiras chegam no nível {primeiro}." if primeiro else ""))
        elif query:
            motivo = "Nenhuma magia da lista da classe com esse nome."
        elif spell_level is not None:
            motivo = ("Nenhum truque na lista da classe." if int(spell_level) == 0
                      else f"Nenhuma magia de {int(spell_level)}º círculo na lista da classe.")
        elif not status.get("respondeu"):
            motivo = "A lista da classe não respondeu. Tente de novo em instantes."
        else:
            motivo = "A lista da classe está vazia até este círculo."

    base.update({
        "personagem": {
            "nome": alvo.get("name", ""), "classe": s.get("classe", ""),
            "nivel": int(s.get("nivel", 1) or 1),
            "mana_atual": int(s.get("mana_atual", 0) or 0),
            "mana_max": int(s.get("mana_max", 0) or 0),
            "nivel_max_magia": nivel_max,
            "vagas": vagas,
            "conhecidas": conhecidas,
        },
        "catalogo": catalogo,
        "catalogo_motivo": motivo,
        # Em combate, conjurar é pela tela de combate (que cobra a economia).
        "em_combate": bool((memory.campaign.get("combat_state") or {}).get("is_active")),
    })
    return base


def alvos_fora_de_combate(ator: str) -> dict:
    """
    Quem pode ser alvo de uma magia conjurada fora do combate: quem está aqui
    (o grupo e quem tem o local atual como paradeiro) primeiro; os demais
    vivos depois — o paradeiro gravado nem sempre acompanha a história, e o
    guarda do portão pode não ter local nenhum.
    """
    from rpg import locais
    aqui, outros = [], []
    for ch in (memory.campaign.get("characters") or {}).values():
        if not isinstance(ch, dict) or not ch.get("name"):
            continue
        if (ch.get("status") or "").lower() in ("morto", "fugiu"):
            continue
        local = ch.get("local") or ""
        perto = memory.is_party_member(ch) or (local and locais.alcance(local) == "aqui")
        (aqui if perto else outros).append(ch["name"])
    return {"aqui": sorted(aqui, key=str.lower), "outros": sorted(outros, key=str.lower)}


def conjurar_fora_de_combate(ator: str, habilidade: str, alvo: str = "", modo: str = "",
                             ritual: bool = False) -> dict:
    """
    Conjura uma magia FORA do combate pela tela (Grimório): o motor gasta a
    mana, rola o que é dele rolar (salvaguarda, cura, o encanto) e devolve o
    texto para o Mestre narrar a cena.

    Antes o único caminho era escrever no chat e torcer: o Mestre podia narrar
    sem chamar a ferramenta, e aí nem a mana era gasta, nem o encanto existia.
    """
    cs = memory.campaign.get("combat_state") or {}
    if cs.get("is_active"):
        return {"ok": False, "message": ("Aviso: há um combate em andamento — conjure pela "
                                         "tela de combate, que cobra a ação do turno.")}
    msg = use_ability(ator, habilidade, alvo, end_turn=False, modo=modo, _ritual=ritual)
    recusou = msg.startswith(("Erro:", "Aviso:")) or "não conhece" in msg.split("\n")[0]
    if recusou:
        return {"ok": False, "message": msg}
    from rpg import subclasses as _sub_f
    msg += _sub_f.lancar_gemea(ator, habilidade, modo)
    # O tempo de conjuração passa no relógio: uma hora (Convocar Familiar),
    # um minuto (Conjurar Elemental, Identificar), e o ritual soma dez.
    from rpg import resolucao as _res
    _m = _res._magia_srd({"nome": habilidade}) or {}
    _ch_c = memory.campaign["characters"].get(memory.char_key(ator)) or {}
    _hab_c = next((h for h in _ch_c.get("habilidades") or []
                   if isinstance(h, dict) and _norm_txt(h.get("nome", "")) == _norm_txt(habilidade)), None)
    _m = _res._magia_srd(_hab_c or {"nome": habilidade}) or _m
    _minutos = minutos_de_conjuracao(_m.get("tempo_de_conjuracao", "")) + (10 if ritual else 0)
    if ritual:
        msg += "\n   Como ritual: sem mana, e dez minutos a mais de conjuração."
    if _minutos:
        msg += "\n   " + avancar_minutos(_minutos, f"conjurar {habilidade}"
                                         + (" como ritual" if ritual else "")).split("\n")[0]
    memory.save_campaign()
    em = f" em {alvo}" if alvo and memory.char_key(alvo) != memory.char_key(ator) else ""
    para_o_mestre = (f"[MAGIA FORA DE COMBATE, resolvida na tela] {ator} conjurou "
                     f"{habilidade}{em}. O motor já gastou a mana e resolveu o que é regra:\n"
                     f"{msg}\n"
                     f"Narre o efeito na cena e a reação de quem estiver lá, de acordo com "
                     f"o resultado acima. Não chame use_ability de novo.")
    return {"ok": True, "message": msg, "para_o_mestre": para_o_mestre}


def _primeiro_nivel_com_magia(classe: str) -> int | None:
    """Nível em que a classe aprende o primeiro truque ou magia (None se nunca)."""
    for n in range(1, 21):
        limite = _limite_de_magias({"classe": classe, "nivel": n}) or {}
        if limite.get("truques") or limite.get("magias"):
            return n
    return None


def grimoire_action(action: str, char: str = "", spell: str = "", query: str = "",
                    spell_level: int | None = None) -> dict:
    """
    Aplica UMA intenção do Grimório. actions: aprender.

    Só despacho, como nas outras telas: quem valida classe, nível de magia,
    limite e duplicata é o learn_spell — a mesma função do mestre.
    """
    a = (action or "").lower().strip()
    if a != "aprender":
        return {"ok": False, "message": f"Erro: Ação '{action}' desconhecida.",
                "snapshot": grimoire_snapshot(char, query, spell_level)}
    msg = learn_spell(char, spell)
    ok = not msg.lstrip().startswith(("Aviso:", "Erro:", "Nota:"))
    return {"ok": ok, "message": msg, "snapshot": grimoire_snapshot(char, query, spell_level)}


def learn_spell(char_name: str, spell_name: str) -> str:
    """
    Busca a magia no Open5e e adiciona à ficha do personagem.
    Valida classe, nível mínimo e evita duplicatas.

    Use quando o personagem sobe de nível e escolhe uma nova magia,
    ou quando aprende por item mágico, pacto ou dom narrativo.

    Args:
        char_name:  Nome do personagem.
        spell_name: Nome da magia (português ou inglês).
    """
    from rpg.open5e import http as _req   # SRD com cache, sessão e retry

    char, err = _get_char(char_name)
    if not char:
        return err

    sheet  = char["sheet"]
    nivel  = sheet.get("nivel", 1)

    en_query = SPELL_PT_TO_EN.get(spell_name.lower().strip(), spell_name.lower().strip())
    # Slug: "magic missile" → "magic-missile"
    slug     = en_query.lower().strip().replace(" ", "-").replace("'", "")
    _edbg(f"  [OPEN5E] Buscando magia '{spell_name}' (en: '{en_query}') na base SRD (grounding)…")

    try:
        # Tentativa 1: busca por slug exato (mais precisa)
        r_slug = _req.get(
            f"https://api.open5e.com/v1/spells/{slug}/",
            timeout=5,
        )
        if r_slug.ok and r_slug.json().get("name"):
            results = [r_slug.json()]
        else:
            raise ValueError("slug not found")
    except Exception:
        try:
            # Tentativa 2: busca por nome exato
            r_name = _req.get(
                "https://api.open5e.com/v1/spells/",
                params={"name": en_query.title(), "limit": 5},
                timeout=5,
            )
            results = r_name.json().get("results", []) if r_name.ok else []
            if not results:
                raise ValueError("name not found")
        except Exception:
            try:
                # Tentativa 3: busca fuzzy como fallback
                r_search = _req.get(
                    "https://api.open5e.com/v1/spells/",
                    params={"search": en_query, "limit": 10},
                    timeout=6,
                )
                if not r_search.ok:
                    raise Exception("API error")
                all_results = r_search.json().get("results", [])
                # Filtra pelo nome mais próximo para evitar resultados errados.
                # Sem NENHUMA palavra em comum não há "mais próximo": a busca
                # textual também casa na descrição, e um nome inventado voltava
                # com os dados da primeira magia da lista.
                en_words = set(en_query.lower().split())
                results = [s for s in sorted(
                    all_results,
                    key=lambda s: len(en_words & set(s.get("name","").lower().split())),
                    reverse=True,
                )[:1] if en_words & set(s.get("name", "").lower().split())]
            except Exception:
                # SRD fora do ar. Antes, aqui a magia entrava na ficha SEM
                # validação nenhuma — qualquer nome, qualquer classe, qualquer
                # nível, custo 4 fixo. Era o único caminho do motor em que uma
                # magia inventada passava. Agora só entra o que o motor conhece
                # localmente (as magias padrão das classes e a tabela de
                # níveis), e com as mesmas checagens do caminho online.
                local = _magia_conhecida_localmente(spell_name, en_query)
                if not local:
                    return (f"Erro: Não consegui confirmar '{spell_name}' no SRD (sem conexão). "
                            f"Tente de novo mais tarde — magia não confirmada não entra na ficha.")
                results = [local]

    if not results:
        return f"Erro: Magia '{spell_name}' não encontrada. Verifique o nome ou use learn_ability()."

    spell       = results[0]
    # Corrige nível com banco local quando a API retorna valor incorreto.
    # `is not None`: um truque tem nível 0, e `or` o trocava pelo da API.
    spell_level = next((v for v in (SPELL_LEVEL_OVERRIDE.get(en_query.lower()),
                                    SPELL_LEVEL_OVERRIDE.get(spell.get("name", "").lower()))
                        if v is not None),
                       int(spell.get("spell_level", 0) or 0))
    nivel_max = _nivel_maximo_de_magia(sheet)

    if spell_level > nivel_max:
        return (
            f"Erro: {char['name']} ({sheet.get('classe', '')} nível {nivel}) só aprende magias "
            f"até o nível {nivel_max}; {spell_name} é de nível {spell_level}."
        )

    # Valida se a magia pertence à lista da classe do personagem
    char_class = sheet.get("classe", "").lower()
    en_class   = _CLASS_SLUG_MAP.get(char_class, "")
    if en_class and spell:
        spell_classes = spell.get("dnd_class", "").lower()
        if spell_classes and en_class not in spell_classes:
            return (
                f"Erro: **{spell_name}** não está na lista de magias de {char_class.capitalize()}.\n"
                f"   Disponível para: {spell.get('dnd_class', 'desconhecido')}\n"
                f"   Use learn_spell() com uma magia adequada para {char_class}."
            )

    nome_srd = spell.get("name", "") or spell_name
    if _ja_conhece_magia(char, spell_name, nome_srd):
        return f"Nota: {char['name']} já conhece {spell_name}."

    # Limite de magias conhecidas. Ele existia só no JavaScript do modal de
    # edição: o mestre, pelo learn_spell, dava a décima magia a um clérigo de
    # nível 3 sem que nada reclamasse. A regra agora mora aqui, e a tela do
    # Grimório e o modal leem o mesmo número.
    limite = _limite_de_magias(sheet)
    if limite:
        truques, magias = _contagem_de_magias(char)
        if spell_level == 0 and truques >= limite["truques"]:
            return (f"Erro: {char['name']} já conhece {truques}/{limite['truques']} truques "
                    f"— o máximo de {sheet.get('classe', '')} no nível {nivel}.")
        if spell_level > 0 and magias >= limite["magias"]:
            return (f"Erro: {char['name']} já conhece {magias}/{limite['magias']} magias "
                    f"— o máximo de {sheet.get('classe', '')} no nível {nivel}.")

    dado  = ""
    dmg   = spell.get("damage", {})
    if isinstance(dmg, dict):
        dado = dmg.get("damage_dice", "") or ""

    desc_raw   = spell.get("desc", "Sem descrição disponível.")
    desc_clean = " ".join(desc_raw.split())[:300]

    # O Open5e NÃO tem campo de dano para magia — conferido na API: `damage`
    # vem nulo em todas elas, inclusive Bola de Fogo. O dado está escrito no
    # texto ("8d6 fire damage", "regains ... 1d8"), e é de lá que ele sai.
    # Sem isto, toda magia aprendida chegava sem dado e o motor rolava 1d6.
    _texto_todo = " ".join(f"{desc_raw} {spell.get('higher_level', '') or ''}".split())
    if not dado:
        dado = (dado_de_cura_no_texto(_texto_todo)
                if _is_healing_ability({"nome": nome_srd, "descricao": _texto_todo})
                else dado_de_dano_no_texto(_texto_todo))
    # O teste de resistência também está no texto, e é o que faz a magia ter
    # defesa: sem ele, o mestre que esquecesse de pedir o teste aplicava dano
    # cheio em todo mundo.
    _save = salvaguarda_da_habilidade({"descricao": _texto_todo})
    escola     = spell.get("school", "")
    ritual     = " (ritual)"       if _sim_do_srd(spell.get("ritual"))        else ""
    concentr   = " (concentração)" if _sim_do_srd(spell.get("concentration")) else ""
    mana       = SPELL_MANA_COST.get(spell_level, 4)

    char.setdefault("habilidades", []).append({
        "nome":       spell_name,
        "descricao":  f"[{escola}{ritual}{concentr}] {desc_clean}",
        "custo_mana": mana,
        "dado":       dado,
        # Alcance vindo direto do Open5e — fonte de verdade para target_mode.
        # Ex.: "Self" (Mage Armor), "Self (15-foot cone)" (Burning Hands),
        # "60 feet" (Magic Missile), "Touch" (Cure Wounds).
        "alcance":    (spell.get("range", "") or "").strip(),
        # O nível e o nome no SRD ficam gravados. Sem o nível, a contagem de
        # truques e magias tinha de adivinhar pelo custo de mana; sem o nome
        # do SRD, "Bola de Fogo" e "Fireball" eram duas magias diferentes.
        "nivel_magia": spell_level,
        "nome_srd":   nome_srd,
        # Campo booleano em vez de só a palavra na descrição: é o que
        # _requires_concentration prefere quando existe.
        "concentracao": bool(_sim_do_srd(spell.get("concentration"))
                             or spell.get("requires_concentration")),
        **({"salvaguarda": _save} if _save else {}),
    })
    memory.save_campaign()

    return (
        f"{char['name']} aprendeu **{spell_name}** "
        f"(nível {spell_level}, {mana} mana{ritual}{concentr})!\n"
        f"   {escola} · Dado: {dado or 'sem dano direto'}"
        + (f" · Resistência: {_ATRIBUTO_PT.get(_save, _save)}" if _save else "")
    )


def _cr_to_open5e_str(cr: float) -> str:
    """Converte CR numérico para o formato string do Open5e (1/8, 1/4, 1/2, 1, 2...)."""
    if cr <= 0.1:    return "0"
    elif cr <= 0.15: return "1/8"
    elif cr <= 0.3:  return "1/4"
    elif cr <= 0.6:  return "1/2"
    else:            return str(max(1, int(round(cr))))


def _extract_damage_from_action(action: dict) -> str:
    """Extrai dado de dano de uma action Open5e. Tenta damage_dice, depois regex no desc."""
    import re
    # Campo direto
    dd = action.get("damage_dice") or action.get("damage_bonus") or ""
    if dd and dd != "0":
        return str(dd)
    # Extrai do texto da descrição: "Hit: 11 (2d6 + 4) bludgeoning damage"
    desc = action.get("desc", "")
    m = re.search(r'\(([0-9]+d[0-9]+(?:\s*[+\-]\s*[0-9]+)?)\)', desc)
    if m:
        return m.group(1).replace(" ", "")
    return ""


def _cr_str_to_float(cr) -> float:
    """Converte CR do Open5e (string ou número) para float."""
    FRAC = {"0": 0.0, "1/8": 0.125, "1/4": 0.25, "1/2": 0.5}
    s = str(cr).strip()
    if s in FRAC:
        return FRAC[s]
    try:
        return float(s)
    except ValueError:
        return 0.0


def _fetch_open5e_monsters(cr: float, limit: int = 15) -> list[dict]:
    """Busca monstros do Open5e com CR correto. Retorna lista vazia se falhar."""
    from rpg.open5e import http as _req   # SRD com cache, sessão e retry
    cr_str = _cr_to_open5e_str(cr)
    _edbg(f"  [OPEN5E] Buscando monstros reais com CR≈{cr_str} na base SRD (grounding)…")
    try:
        r = _req.get(
            "https://api.open5e.com/v1/monsters/",
            params={"challenge_rating": cr_str, "limit": limit},
            timeout=5,
        )
        if not r.ok:
            _edbg(f"  [OPEN5E] Resposta HTTP {r.status_code} ao buscar monstros CR {cr_str}")
            return []
        results = r.json().get("results", [])
        # Filtra monstros cujo CR real está próximo do solicitado
        # Tolerância: ±0.5 para CRs baixos, ±50% para CRs altos
        target = _cr_str_to_float(cr_str)
        tol    = max(0.5, target * 0.5)
        filtrados = [m for m in results if abs(_cr_str_to_float(m.get("challenge_rating", 0)) - target) <= tol]
        _edbg(f"  [OPEN5E] {len(filtrados)} monstro(s) com CR compatível: "
              f"{', '.join(m.get('name', '?') for m in filtrados[:6])}")
        return filtrados
    except Exception as e:
        _edbg(f"  [OPEN5E] Falha de rede ao buscar monstros (API offline?): {e}")
        return []


def _open5e_monster_to_block(m: dict, label: str) -> str:
    """Converte um monstro Open5e para bloco de encontro."""
    name  = m.get("name", "Monstro")
    hp    = m.get("hit_points", 10)
    ac    = m.get("armor_class", 12)
    cr    = m.get("challenge_rating", "?")
    size  = m.get("size", "")
    type_ = m.get("type", "")
    spd   = m.get("speed", {})
    spd_str = f"{spd.get('walk', 9)}m" if isinstance(spd, dict) else str(spd)
    stats = {
        "FOR": m.get("strength", 10), "DES": m.get("dexterity", 10),
        "CON": m.get("constitution", 10), "INT": m.get("intelligence", 10),
        "SAB": m.get("wisdom", 10), "CAR": m.get("charisma", 10),
    }
    stats_line = "  ".join(f"{k} {v}({_modifier(v):+d})" for k, v in stats.items())
    actions = m.get("actions", [])
    atk_line = ""
    if actions:
        atk  = actions[0]
        dado = _extract_damage_from_action(atk)
        atk_line = f"\n   {atk.get('name', 'Ataque')}: {dado or 'ver descrição'} dano"
    return (
        f"── {label}: **{name}** (CR {cr}) ──\n"
        f"   {size} {type_} | {hp} HP | CA {ac} | {spd_str}\n"
        f"   {stats_line}{atk_line}\n"
        f"   → create_character_sheet('{name}', hp_max={hp}, ca={ac})"
    )


def suggest_encounter(party_level: int, party_size: int = 4, difficulty: str = "medium") -> str:
    """
    Sugere encontros balanceados. Busca monstros reais do Open5e (CR correto)
    e cai para tabelas internas se a API estiver indisponível.

    Use ANTES de criar inimigos para garantir desafio justo para o grupo.

    Args:
        party_level: Nível médio do grupo (1-20).
        party_size:  Quantidade de aventureiros (padrão: 4).
        difficulty:  'easy', 'medium', 'hard' ou 'deadly'.
    """
    import random as _rnd
    party_level = max(1, min(20, party_level))
    party_size  = max(1, min(8,  party_size))

    diff_map  = {"easy":0,"medium":1,"hard":2,"deadly":3}
    diff_idx  = diff_map.get(difficulty.lower(), 1)
    diff_name = ["FÁCIL","MÉDIO","DIFÍCIL","MORTAL"][diff_idx]

    per_char  = _XP_THRESHOLDS[party_level][diff_idx]
    budget    = per_char * party_size
    boss_cr   = _xp_to_cr(budget)
    mid_cr    = _xp_to_cr(budget / 2.0 / 3)
    horde_cnt = max(5, party_size + 2)
    horde_cr  = _xp_to_cr(budget / _enc_multiplier(horde_cnt) / horde_cnt)

    header = (
        f"ENCONTRO BALANCEADO — Grupo Nv.{party_level} × {party_size}\n"
        f"Dificuldade: **{diff_name}**  |  Orçamento: {budget} XP ({per_char}/personagem)\n"
    )

    boss_list  = _fetch_open5e_monsters(boss_cr)
    mid_list   = _fetch_open5e_monsters(mid_cr)
    horde_list = _fetch_open5e_monsters(horde_cr)

    lines = [header]
    sugeridos: list[str] = []            # para a medição, mais abaixo

    if boss_list:
        chefe = _rnd.choice(boss_list)
        sugeridos.append(chefe.get("name", ""))
        lines.append(_open5e_monster_to_block(chefe, "OPÇÃO A — Chefão Solitário"))
    else:
        lines.append(_enc_block("OPÇÃO A — Chefão Solitário", 1, boss_cr, budget))

    lines.append("")

    if mid_list:
        m = _rnd.choice(mid_list)
        sugeridos.append(m.get("name", ""))
        lines.append(_open5e_monster_to_block(m, f"OPÇÃO B — Bando ×3: {m.get('name','?')}"))
    else:
        lines.append(_enc_block("OPÇÃO B — Bando Médio", 3, mid_cr, budget))

    lines.append("")

    if horde_list:
        h = _rnd.choice(horde_list)
        sugeridos.append(h.get("name", ""))
        lines.append(_open5e_monster_to_block(h, f"OPÇÃO C — Horda ×{horde_cnt}: {h.get('name','?')}"))
    else:
        lines.append(_enc_block(f"OPÇÃO C — Horda ×{horde_cnt}", horde_cnt, horde_cr, budget))

    # A sugestão fica anotada para a medição: na partida de 91 turnos o mestre
    # pediu o encontro balanceado e criou os próprios monstros por fora. Antes
    # de obrigar alguma coisa, é preciso saber se aquilo foi uma vez ou é a
    # regra. Medir não muda o jogo (ver rpg/medicao.py).
    try:
        from rpg import medicao
        medicao.registrar_sugestao([n for n in sugeridos if n], budget)
    except Exception:
        pass

    # Instrução interna à LLM — filtrada antes de exibir na UI (server.py).
    lines += ["", "[[llm]]Use os stats em create_character_sheet ANTES de roll_initiative.",
              "   Adapte os nomes ao tema da campanha.[[/llm]]"]
    return "\n".join(lines)


# ── Bônus de pré-requisito de nível para talentos ───────────────────────────
_FEAT_LEVEL_REQUIREMENTS: dict[str, int] = {
    "great weapon master": 4, "sharpshooter": 4, "polearm master": 4,
    "sentinel": 4, "war caster": 4, "resilient": 4, "lucky": 1,
    "alert": 1, "tough": 1, "mobile": 1, "observant": 1,
}

# ── Antecedentes do SRD com fallback offline ─────────────────────────────────
_BACKGROUND_FALLBACK: dict[str, dict] = {
    "acolyte":     {"skills": ["Insight","Religion"],       "languages": 2, "equipment": ["Holy symbol","Prayer book","5 candles"]},
    "criminal":    {"skills": ["Deception","Stealth"],      "tools": ["Thieves tools","Gaming set"], "equipment": ["Crowbar","Dark clothes"]},
    "folk hero":   {"skills": ["Animal Handling","Survival"],"tools": ["Artisan tools","Vehicles (land)"], "equipment": ["Artisan tools","Shovel"]},
    "noble":       {"skills": ["History","Persuasion"],     "languages": 1, "equipment": ["Fine clothes","Signet ring","Scroll of pedigree"]},
    "sage":        {"skills": ["Arcana","History"],         "languages": 2, "equipment": ["Bottle of ink","Quill","Small knife"]},
    "soldier":     {"skills": ["Athletics","Intimidation"], "tools": ["Gaming set","Vehicles (land)"], "equipment": ["Insignia of rank","Trophy"]},
    "charlatan":   {"skills": ["Deception","Sleight of Hand"],"tools": ["Disguise kit","Forgery kit"], "equipment": ["Fine clothes","Disguise kit"]},
    "entertainer": {"skills": ["Acrobatics","Performance"], "tools": ["Disguise kit","Musical instrument"], "equipment": ["Musical instrument","Costume"]},
    "guild artisan":{"skills": ["Insight","Persuasion"],   "tools": ["Artisan tools"], "languages": 1, "equipment": ["Artisan tools","Letter of introduction"]},
    "hermit":      {"skills": ["Medicine","Religion"],      "tools": ["Herbalism kit"], "languages": 1, "equipment": ["Scroll case","Winter blanket"]},
    "outlander":   {"skills": ["Athletics","Survival"],     "tools": ["Musical instrument"], "languages": 1, "equipment": ["Staff","Hunting trap"]},
    "sailor":      {"skills": ["Athletics","Perception"],   "tools": ["Navigators tools","Vehicles (water)"], "equipment": ["Belaying pin","50ft silk rope"]},
    "urchin":      {"skills": ["Sleight of Hand","Stealth"],"tools": ["Disguise kit","Thieves tools"], "equipment": ["Small knife","City map"]},
    # Traduções PT
    "acólito":     {"skills": ["Percepção","Religião"],     "languages": 2, "equipment": ["Símbolo sagrado","Livro de orações"]},
    "criminoso":   {"skills": ["Enganação","Furtividade"],  "tools": ["Ferramentas de ladrão"], "equipment": ["Pé-de-cabra","Roupas escuras"]},
    "herói do povo":{"skills": ["Adestrar Animais","Sobrevivência"],"equipment": ["Ferramentas de artesão","Pá"]},
    "nobre":       {"skills": ["História","Persuasão"],     "languages": 1, "equipment": ["Roupas finas","Anel de sinete"]},
    "sábio":       {"skills": ["Arcanismo","História"],     "languages": 2, "equipment": ["Tinta","Pena","Canivete"]},
    "soldado":     {"skills": ["Atletismo","Intimidação"],  "equipment": ["Insígnia de patente","Troféu de inimigo"]},
    "charlatão":   {"skills": ["Enganação","Prestidigitação"],"equipment": ["Roupas finas","Kit de disfarce"]},
    "artesão de guilda":{"skills": ["Perspicácia","Persuasão"],"languages": 1, "equipment": ["Ferramentas de artesão"]},
    "eremita":     {"skills": ["Medicina","Religião"],      "equipment": ["Estojo de pergaminhos","Cobertor de inverno"]},
    "forasteiro":  {"skills": ["Atletismo","Sobrevivência"],"languages": 1, "equipment": ["Cajado","Armadilha de caça"]},
    "marinheiro":  {"skills": ["Atletismo","Percepção"],    "equipment": ["Belaying pin","Corda 15m"]},
    "pivete":      {"skills": ["Prestidigitação","Furtividade"],"equipment": ["Canivete","Mapa da cidade"]},
}


def _fetch_background(bg_name: str) -> dict | None:
    """
    Busca um antecedente no Open5e. Retorna o dict ou None se falhar.
    Usa fallback offline automaticamente.
    """
    from rpg.open5e import http as _req   # SRD com cache, sessão e retry
    en_name = bg_name.lower().strip()
    slug    = en_name.replace(" ", "-").replace("'", "")
    try:
        r = _req.get(f"https://api.open5e.com/v1/backgrounds/{slug}/", timeout=5)
        if r.ok and r.json().get("name"):
            return r.json()
        r2 = _req.get("https://api.open5e.com/v1/backgrounds/",
                      params={"search": en_name, "limit": 3}, timeout=5)
        if r2.ok:
            results = r2.json().get("results", [])
            if results:
                return results[0]
    except Exception:
        pass
    return _BACKGROUND_FALLBACK.get(en_name)


def set_feature_choice(char_name: str, feature_name: str, choice: str) -> str:
    """
    Define a subescolha de uma feature de classe que tem variantes — por
    exemplo, qual estilo de combate (Arquearia/Defesa/Duelo/...), qual tipo
    de Inimigo Favorecido, qual terreno de Explorador Natural, qual efeito
    de Metamagia, qual Invocação Sobrenatural.

    Use sempre que o jogador escolher (ou trocar) uma variante. O efeito
    mecânico (bônus de ataque/CA/dano) passa a valer imediatamente nas
    rolagens seguintes.

    Para features com múltiplas escolhas (Metamagia: 2; Invocações: N),
    chame uma vez por escolha — a função acumula numa lista e RECUSA se
    passar do limite, instruindo a remover a antiga primeiro.

    Args:
        char_name:    Nome do personagem.
        feature_name: Nome exato da feature (ex.: "Estilo de Combate",
                      "Inimigo Favorecido", "Metamagia").
        choice:       Nome da variante (ex.: "Arquearia", "Dragões",
                      "Sutil"). Para REMOVER uma escolha, passe "remove:X".
    """
    char, err = _get_char(char_name)
    if not char:
        return err

    meta = _get_variants(feature_name)
    if not meta:
        avail = ", ".join(sorted(FEATURE_VARIANTS.keys()))
        return (
            f"Erro: Feature '{feature_name}' não tem variantes registradas.\n"
            f"   Features com subescolha: {avail}."
        )

    # Personagem precisa de fato ter a feature na ficha (concedida pela classe).
    has_feat = any(
        h.get("nome", "").lower() == feature_name.lower()
        for h in (char.get("habilidades") or [])
    )
    if not has_feat:
        return (
            f"Erro: {char['name']} ainda não tem a habilidade '{feature_name}'. "
            f"Suba de nível ou conceda a feature antes de escolher variante."
        )

    options = meta.get("options", {}) or {}
    pick    = int(meta.get("pick", 1) or 1)

    sheet  = char.setdefault("sheet", {})
    fc     = sheet.setdefault("feature_choices", {})
    cur    = fc.get(feature_name)

    # Remoção explícita: "remove:Sutil"
    if choice.lower().startswith("remove:"):
        target = choice.split(":", 1)[1].strip()
        if pick == 1:
            if cur == target:
                fc.pop(feature_name, None)
                memory.save_campaign()
                return f"Removida a escolha '{target}' de {feature_name}."
            return f"Nota: {target!r} não estava marcado em {feature_name}."
        cur_list = list(cur or [])
        if target in cur_list:
            cur_list.remove(target)
            fc[feature_name] = cur_list
            memory.save_campaign()
            return f"Removido {target!r} de {feature_name}."
        return f"Nota: {target!r} não estava marcado em {feature_name}."

    # Validação
    if choice not in options:
        opts_str = ", ".join(sorted(options.keys()))
        return (
            f"Erro: '{choice}' não é uma opção de {feature_name}.\n"
            f"   Opções disponíveis: {opts_str}."
        )

    if pick == 1:
        fc[feature_name] = choice
        # Se for um arquétipo, concede as sub-features do nível atual.
        archetype_granted: list[str] = []
        if feature_name in ARCHETYPE_FEATURES:
            archetype_granted = _apply_archetype_features(char, feature_name)
        # Recalcula CA: Estilo de Combate (Defesa) ou sub-feature de
        # arquétipo que mexe na CA (Resistência Dracônica).
        if feature_name == "Estilo de Combate" or archetype_granted:
            _recalculate_ca(char)
        memory.save_campaign()
        desc = options[choice].get("descricao", "")
        granted_str = ""
        if archetype_granted:
            granted_str = (
                f"\n   Sub-features concedidas neste nível: "
                f"{', '.join(archetype_granted)}."
            )
        return (
            f"{char['name']} agora tem {feature_name}: **{choice}**.\n"
            f"   {desc}{granted_str}"
        )

    # Multi-pick
    cur_list = list(cur or [])
    if choice in cur_list:
        return f"Nota: {choice!r} já está marcado em {feature_name}."
    if len(cur_list) >= pick:
        atual = ", ".join(cur_list)
        return (
            f"Erro: {char['name']} já escolheu {len(cur_list)}/{pick} em {feature_name}: {atual}.\n"
            f"   Remova uma antes: set_feature_choice('{char['name']}', "
            f"'{feature_name}', 'remove:<nome>')."
        )
    cur_list.append(choice)
    fc[feature_name] = cur_list
    memory.save_campaign()
    desc = options[choice].get("descricao", "")
    return (
        f"{char['name']} aprendeu {feature_name}: **{choice}** "
        f"({len(cur_list)}/{pick}).\n   {desc}"
    )


def choose_feat(char_name: str, feat_name: str) -> str:
    """
    Permite ao personagem escolher um talento nos níveis 4, 8, 12, 16 ou 19,
    em vez de uma Melhoria de Atributo (+2).

    Busca o talento no Open5e, valida pré-requisitos e aplica os bônus à ficha.

    Use quando o jogador chegar em um nível de Melhoria de Atributo e escolher
    explicitamente um talento em vez do +2.

    Args:
        char_name: Nome do personagem.
        feat_name: Nome do talento em inglês (como aparece no SRD).
    """
    from rpg.open5e import http as _req   # SRD com cache, sessão e retry

    char, err = _get_char(char_name)
    if not char:
        return err

    sheet = char["sheet"]
    nivel = sheet.get("nivel", 1)

    # Um talento é TROCADO por um incremento de atributo, então ele sai do
    # mesmo pool. Antes esta função não descontava nada: na tela de nível,
    # quem escolhia talento ficava com o talento E com os 2 pontos pendentes.
    #
    # Ficha COM contador: vale o pool — inclusive para quem subiu ao 5 ainda
    # devendo o incremento do 4, que a checagem por nível exato barrava.
    # Ficha SEM contador (anterior a ele): mantém a regra antiga por nível,
    # agora com os extras do Guerreiro e do Ladino.
    rastreado = "asi_pontos_gastos" in sheet
    if rastreado:
        if _asi_pontos_pendentes(sheet) < _PONTOS_POR_ASI:
            return (
                f"Erro: {char['name']} não tem um incremento inteiro pendente "
                f"({_asi_pontos_pendentes(sheet)} ponto(s)). Um talento substitui "
                f"um incremento completo, de {_PONTOS_POR_ASI} pontos."
            )
    elif nivel not in _niveis_asi(sheet.get("classe", "")):
        return (
            f"Erro: {char['name']} está no nível {nivel}. Talentos só podem ser "
            f"escolhidos nos níveis {sorted(_niveis_asi(sheet.get('classe', '')))}."
        )

    # Verifica se já tem esse talento
    existing_names = {h.get("nome", "").lower() for h in char.get("habilidades", [])}
    if feat_name.lower() in existing_names:
        return f"Nota: {char['name']} já possui o talento '{feat_name}'."

    # Busca no Open5e
    feat_data = None
    slug      = feat_name.lower().strip().replace(" ", "-").replace("'", "")
    try:
        r = _req.get(f"https://api.open5e.com/v1/feats/{slug}/", timeout=5)
        if r.ok and r.json().get("name"):
            feat_data = r.json()
        else:
            r2 = _req.get("https://api.open5e.com/v1/feats/",
                          params={"search": feat_name, "limit": 5}, timeout=5)
            if r2.ok:
                results = r2.json().get("results", [])
                feat_words = set(feat_name.lower().split())
                best = max(results, key=lambda f: len(feat_words & set(f.get("name","").lower().split())), default=None)
                if best:
                    feat_data = best
    except Exception:
        pass

    if not feat_data:
        return (
            f"Erro: Talento '{feat_name}' não encontrado no Open5e (SRD).\n"
            f"   Verifique o nome em inglês ou use learn_ability() para habilidades customizadas."
        )

    name_en  = feat_data.get("name", feat_name)
    desc_raw = feat_data.get("desc", "Sem descrição disponível.")
    desc     = " ".join(desc_raw.split())[:350]

    # Aplica bônus de atributo se o talento conceder (+1 em atributo)
    bonus_applied = []
    prereq_str    = feat_data.get("prerequisite", "")

    # Tenta extrair bônus de atributo da descrição (+1 a FOR, DEX, etc.)
    attr_map_en = {
        "strength": "forca", "dexterity": "destreza", "constitution": "constituicao",
        "intelligence": "inteligencia", "wisdom": "sabedoria", "charisma": "carisma",
    }
    import re as _re
    for en_attr, pt_attr in attr_map_en.items():
        if _re.search(rf"increase your {en_attr}.*by 1|{en_attr}.*increases? by 1", desc_raw, _re.IGNORECASE):
            if pt_attr in sheet:
                # Teto do 5e é 20 (era 30 aqui, divergindo de apply_asi).
                sheet[pt_attr] = min(_TETO_ATRIBUTO, sheet[pt_attr] + 1)
                bonus_applied.append(f"{pt_attr.upper()[:3]} +1")

    char.setdefault("habilidades", []).append({
        "nome":       feat_name,
        "descricao":  desc,
        "custo_mana": 0,
        "dado":       "",
    })
    if rastreado:
        sheet["asi_pontos_gastos"] = (int(sheet.get("asi_pontos_gastos", 0) or 0)
                                      + _PONTOS_POR_ASI)
    memory.save_campaign()

    prereq_info = f"\n   Pré-requisito: {prereq_str}" if prereq_str else ""
    bonus_info  = f"\n   Bônus aplicado: {', '.join(bonus_applied)}" if bonus_applied else ""

    return (
        f"{char['name']} aprendeu o talento **{name_en}**!{prereq_info}{bonus_info}\n"
        f"   {desc}"
    )


# ---------------------------------------------------------------------------
# Spawn de monstro com dados reais do Open5e
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Leitura do bloco de ações de um monstro do Open5e
# ---------------------------------------------------------------------------

_MULTIATTACK_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "um": 1, "dois": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6,
}
# Teto defensivo: se o parser interpretar mal uma descrição, o pior caso é
# um monstro com 4 ataques — não um loop de 40.
_MULTIATTACK_MAX = 4


def _parse_multiattack(actions: list) -> int:
    """
    Quantos ataques a ação 'Multiattack' concede. 1 quando o monstro não tem.

    O Open5e traz o Multiattack só como texto em inglês, então lemos a frase:
      "The owlbear makes two attacks: one with its beak and one with its claws."
      "The bandit captain makes three attacks: two with its scimitar and one..."
      "The mage makes 2 ranged attacks."
    """
    import re as _re
    for action in (actions or []):
        if _norm_txt(action.get("name", "")) not in ("multiattack", "ataque multiplo"):
            continue
        desc = _norm_txt(action.get("desc", ""))
        m = _re.search(r"\bmakes?\s+([\w-]+)\s+(?:[\w-]+\s+){0,3}attacks\b", desc)
        if not m:
            continue
        bruto = m.group(1)
        n = _MULTIATTACK_WORDS.get(bruto, int(bruto) if bruto.isdigit() else 0)
        if n >= 2:
            return min(n, _MULTIATTACK_MAX)
    return 1


def _extract_monster_attacks(monster: dict) -> dict:
    """
    Extrai os ataques REAIS do bloco de ações do Open5e.

    Por que isto existe: "bite", "claw", "slam" não são armas do SRD — buscá-las
    em /weapons/ devolve 404, e o motor caía no fallback genérico de 1d6. Com o
    dado guardado na ficha, o urso-coruja volta a bater os 2d8 do stat block e o
    CR do encontro volta a significar alguma coisa.

    Devolve: ataques (lista completa), arma principal/secundária com seus dados,
    e quantos ataques o Multiattack concede.
    """
    import re as _re

    ataques: list[dict] = []

    for action in (monster.get("actions") or []):
        aname = (action.get("name") or "").strip()
        if not aname:
            continue
        # O próprio Multiattack não é um golpe — e a descrição dele CONTÉM
        # "melee attacks:" (Bandit Captain: "makes three melee attacks: two
        # with its scimitar…"). Sem esta guarda ele era classificado como
        # ataque, virava a arma principal SEM dado, e o motor caía de volta
        # no 1d6 genérico: exatamente o bug que esta função existe para matar.
        if _norm_txt(aname) in ("multiattack", "ataque multiplo"):
            continue

        desc = (action.get("desc") or "").lower()
        # Marcador confiável de um ataque de verdade: todo ataque do SRD traz
        # o bônus de acerto ("+7 to hit"). Descrições que apenas CITAM ataques
        # não têm isso.
        if "to hit" not in desc:
            continue

        is_melee  = "melee" in desc
        is_ranged = "ranged" in desc
        if not (is_melee or is_ranged):
            continue

        dado = (action.get("damage_dice") or "").strip()
        if not dado:
            _m  = _re.search(r"(\d+d\d+)", desc)
            dado = _m.group(1) if _m else ""
        # "Hit: 14 (2d8 + 5) slashing damage" → slashing.
        tipo = _norm_damage_type(action.get("damage_type") or "") \
               or _damage_type_from_text(desc)
        from rpg import tracos as _tracos_m
        ataques.append({"nome": aname.lower(), "dado": dado, "tipo": tipo,
                        "ranged": bool(is_ranged and not is_melee),
                        **_tracos_m.efeitos_do_texto(desc)})

    def _primeiro(*testes):
        """Primeiro ataque que satisfaz algum dos testes, em ordem de preferência."""
        for teste in testes:
            for a in ataques:
                if teste(a):
                    return a
        return None

    # Um ataque COM dado vale mais que um sem: arma principal sem dado é o
    # caminho de volta para o fallback genérico.
    _com_dado = lambda a: bool(a["dado"])
    principal = _primeiro(
        lambda a: not a["ranged"] and _com_dado(a),   # corpo-a-corpo com dado
        _com_dado,                                    # qualquer um com dado
        lambda a: not a["ranged"],                    # corpo-a-corpo sem dado
        lambda a: True,                               # o que houver
    )
    secundaria = _primeiro(
        lambda a: a["ranged"] and _com_dado(a) and a is not principal,
        lambda a: a["ranged"] and a is not principal,
    )

    return {
        "ataques":               ataques,
        "arma_principal":        (principal  or {}).get("nome", ""),
        "arma_dado":             (principal  or {}).get("dado", ""),
        "arma_secundaria":       (secundaria or {}).get("nome", ""),
        "arma_dado_secundaria":  (secundaria or {}).get("dado", ""),
        "multiattack":           _parse_multiattack(monster.get("actions") or []),
    }


def spawn_monster(
    monster_name: str,
    display_name: str = "",
    quantity: int = 1,
) -> str:
    """
    Busca um monstro no Open5e e cria a ficha com os stats reais (HP, CA, atributos,
    ataques). Use SEMPRE que um monstro conhecido aparecer durante o jogo — assim
    o goblin tem HP 7 e CA 15 reais, não os valores genéricos do roll_initiative().

    Para múltiplos exemplares (ex: 3 goblins), passe quantity=3. Os personagens
    serão criados como "Goblin 1", "Goblin 2", "Goblin 3".

    Após spawn_monster(), chame roll_initiative() com os nomes gerados.
    Com o combate em andamento, não recria quem já está lutando; reforços
    precisam de outro display_name.

    Args:
        monster_name:  Nome do monstro em inglês (ex: 'goblin', 'orc', 'zombie',
                       'bandit', 'wolf', 'skeleton', 'hobgoblin', 'bugbear').
        display_name:  Nome de exibição no jogo (ex: 'Goblin Batedouro'). Se vazio,
                       usa o nome do Open5e.
        quantity:      Quantos exemplares criar (1–10). Se > 1, cria "Nome 1", "Nome 2"…
    """
    from rpg.open5e import http as _req   # SRD com cache, sessão e retry

    quantity = max(1, min(10, int(quantity)))

    # Busca no Open5e pelo nome
    slug = monster_name.strip().lower().replace(" ", "-").replace("'", "")
    monster_data = None

    # Tentativa 1: slug direto
    try:
        r = _req.get(f"https://api.open5e.com/v1/monsters/{slug}/", timeout=5)
        if r.ok:
            monster_data = r.json()
    except Exception:
        pass

    # Tentativa 2: busca por texto
    if not monster_data:
        try:
            r = _req.get(
                "https://api.open5e.com/v1/monsters/",
                params={"search": monster_name.strip(), "limit": 5},
                timeout=5,
            )
            if r.ok:
                results = r.json().get("results", [])
                # Preferência: nome exato, depois nome que começa com a busca
                exact = [m for m in results if m.get("name", "").lower() == monster_name.lower()]
                monster_data = exact[0] if exact else (results[0] if results else None)
        except Exception:
            pass

    if not monster_data:
        return (
            f"Aviso: Monstro '{monster_name}' não encontrado no Open5e. "
            f"Usando ficha padrão via roll_initiative() ou crie manualmente com "
            f"create_character_sheet(). Verifique o nome em inglês "
            f"(ex: 'goblin', 'orc', 'zombie', 'bandit', 'wolf')."
        )

    # Extrai stats
    m          = monster_data
    base_name  = display_name.strip() if display_name.strip() else m.get("name", monster_name)
    hp_max     = int(m.get("hit_points", 10))
    ac         = int(m.get("armor_class", 12))
    str_       = int(m.get("strength",    10))
    dex        = int(m.get("dexterity",   10))
    con        = int(m.get("constitution",10))
    int_       = int(m.get("intelligence",10))
    wis        = int(m.get("wisdom",      10))
    cha        = int(m.get("charisma",    10))
    cr_raw     = m.get("challenge_rating", "?")
    cr_label   = str(cr_raw)
    monster_type = m.get("type", "").lower()
    prof       = 2  # CR 0–4; ajusta para CRs maiores
    cr_float   = _cr_str_to_float(cr_raw)
    if cr_float >= 17: prof = 6
    elif cr_float >= 13: prof = 5
    elif cr_float >= 9: prof = 4
    elif cr_float >= 5: prof = 3

    # Ataques reais do stat block (dado de dano incluso) + Multiattack.
    # Resistências / imunidades / vulnerabilidades — o Open5e já devolve
    # esses campos e eles eram simplesmente jogados fora.
    resistencias      = _parse_damage_traits(m.get("damage_resistances"))
    imunidades        = _parse_damage_traits(m.get("damage_immunities"))
    vulnerabilidades  = _parse_damage_traits(m.get("damage_vulnerabilities"))

    atk_data        = _extract_monster_attacks(m)
    ataques         = atk_data["ataques"]
    arma_principal  = atk_data["arma_principal"]
    arma_dado       = atk_data["arma_dado"]
    arma_secundaria = atk_data["arma_secundaria"]
    arma_dado_sec   = atk_data["arma_dado_secundaria"]
    multiattack     = atk_data["multiattack"]

    # Com a luta rolando, recriar quem já está nela devolvia a vida cheia a um
    # goblin ferido (o personagem inteiro era trocado por um novo). Numa
    # campanha o mestre chamou spawn_monster duas vezes na mesma emboscada.
    cs_atual = memory.campaign.get("combat_state") or {}
    if cs_atual.get("is_active"):
        na_luta = {memory.char_key(n) for n in (cs_atual.get("initiative_order") or [])}
        nomes = [base_name if quantity == 1 else f"{base_name} {i + 1}" for i in range(quantity)]
        repetidos = [n for n in nomes if memory.char_key(n) in na_luta]
        if repetidos:
            verbo = "está" if len(repetidos) == 1 else "estão"
            return (f"Nota: {', '.join(repetidos)} já {verbo} neste combate. Nada foi criado "
                    f"nem curado.\n   Se chegaram reforços de verdade, chame spawn_monster "
                    f"com outro display_name (ex.: '{base_name} Reforço') e depois "
                    f"roll_initiative só com os nomes novos.")

    created_names = []
    for i in range(quantity):
        name = base_name if quantity == 1 else f"{base_name} {i + 1}"
        key  = memory.char_key(name)

        sheet = {
            "classe":               "npc",
            "raca":                 base_name.lower(),
            "nivel":                max(1, int(cr_float)) if cr_float >= 1 else 1,
            "xp":                   0,
            "xp_proximo":           100,
            "forca":                str_,
            "destreza":             dex,
            "constituicao":         con,
            "inteligencia":         int_,
            "sabedoria":            wis,
            "carisma":              cha,
            "vida_atual":           hp_max,
            "vida_max":             hp_max,
            "mana_atual":           0,
            "mana_max":             0,
            "ca":                   ac,
            "proficiencia":         prof,
            "hit_die":              8,
            "ouro":                 0,
            "prata":                0,
            "cobre":                0,
            "equipamentos":         {
                "armadura":      None,
                "escudo":        None,
                "arma_principal": arma_principal or None,
                "amuleto":       None,
            },
            # Ataques do stat block: sem isto, attack_roll não encontra
            # "bite"/"claw" em /weapons/ e cai no fallback genérico de 1d6.
            "ataques":              ataques,
            "arma_dado":            arma_dado,
            "arma_secundaria":      arma_secundaria or None,
            "arma_dado_secundaria": arma_dado_sec,
            "multiattack":          multiattack,
            "resistencias":         resistencias,
            "imunidades":           imunidades,
            "vulnerabilidades":     vulnerabilidades,
            "vida_temp":            0,
            "concentracao":         None,
            "condicoes":            [],
            "death_saves_sucessos": 0,
            "death_saves_falhas":   0,
            "cr":                   cr_label,
            # O tipo (Imobilizar Pessoa: só humanoides) e o que não o afeta.
            "tipo":                 monster_type,
            "visao_no_escuro":      (round(int(_m_vis.group(1)) * 0.3)
                                     if (_m_vis := re.search(r"darkvision (\d+)", str(m.get("senses") or "").lower()))
                                     else 0),
            "imunidades_condicao":  __import__("rpg.tracos", fromlist=["x"]).imunidades_de_condicao(
                                        m.get("condition_immunities")),
        }

        # Resistência Lendária do bloco ("Legendary Resistance (3/Day)").
        for _sa_rl in (m.get("special_abilities") or []):
            _m_rl = re.search(r"legendary resistance\s*\((\d+)/day\)", (_sa_rl.get("name") or "").lower())
            if _m_rl:
                sheet["resistencia_lendaria"] = {"max": int(_m_rl.group(1)), "restantes": int(_m_rl.group(1))}

        # Extrai habilidades especiais (special abilities) do Open5e
        habilidades = []
        # O mago do Open5e trazia "Spellcasting" como texto cortado em 200
        # letras: nenhuma magia virava habilidade e ele só atacava de adaga.
        for sa in (m.get("special_abilities") or []):
            if "spellcasting" in (sa.get("name", "") or "").lower():
                _dar_magias_do_bloco(sheet, habilidades, sa.get("desc", "") or "")
        for sa in (m.get("special_abilities") or [])[:3]:
            sa_name = sa.get("name", "")
            sa_desc = (sa.get("desc", "") or "")[:200]
            if sa_name:
                habilidades.append({
                    "nome":       sa_name,
                    "descricao":  sa_desc,
                    "custo_mana": 0,
                    "dado":       "",
                })

        memory.campaign["characters"][key] = {
            "name":        name,
            "description": f"{m.get('size','')} {monster_type} — CR {cr_label}.",
            "traits":      "",
            "status":      "inimigo",
            # Criatura de luta nasce do lado inimigo (memory.lado_no_combate).
            "lado":        "inimigo",
            "notes":       "",
            "sheet":       sheet,
            "inventario":  [],
            "habilidades": habilidades,
        }
        created_names.append(name)

    # Para a medição: qual monstro do SRD foi realmente chamado à mesa. É o
    # que permite comparar com o encontro que o sistema sugeriu.
    try:
        from rpg import medicao
        medicao.registrar_inimigo(m.get("name", "") or monster_name)
    except Exception:
        pass

    memory.save_campaign()

    names_str  = ", ".join(created_names)
    atk_info   = f" | {arma_principal} ({arma_dado})" if arma_principal else ""
    sec_info   = f" + {arma_secundaria}" if arma_secundaria else ""
    ma_info    = f" | Ataque Múltiplo ×{multiattack}" if multiattack > 1 else ""
    qty_label  = f"{quantity}×" if quantity > 1 else ""

    def _traits_line(rotulo: str, entradas: list) -> str:
        tipos = sorted({t for e in entradas for t in e.get("tipos", [])})
        if not tipos:
            return ""
        cond = " (só de armas não-mágicas)" if any(
            e.get("requer_magica") for e in entradas) else ""
        return f"\n   {rotulo}: {', '.join(tipos)}{cond}"

    traits_info = (
        _traits_line("Imunidades",      imunidades)
        + _traits_line("Resistências",  resistencias)
        + _traits_line("Vulnerabilidades", vulnerabilidades)
    )

    return (
        f"{qty_label}{base_name} criado(s) com stats reais (Open5e)!\n"
        f"   CR {cr_label} | HP {hp_max} | CA {ac}{atk_info}{sec_info}{ma_info}\n"
        f"   FOR {str_}  DES {dex}  CON {con}  INT {int_}  SAB {wis}  CAR {cha}"
        f"{traits_info}\n"
        f"   Personagens: {names_str}"
        # Instrução interna à LLM — filtrada antes de exibir na UI (server.py).
        f"\n[[llm]]→ Agora chame roll_initiative() incluindo: {names_str}[[/llm]]"
    )


# ---------------------------------------------------------------------------
# Estratégia de NPC — sistema determinístico de combate
# ---------------------------------------------------------------------------

NPC_STRATEGIES = {
    "agressivo":  "Ataca o alvo com mais HP (mais ameaçador).",
    "tático":     "Ataca o alvo com menos HP (terminar logo).",
    "covarde":    "Foge quando HP < 25%; senão ataca o mais fraco.",
    "aleatório":  "Escolhe alvo e ação aleatoriamente.",
    "suporte":    "Cura aliados com HP < 50% se possível; senão ataca.",
    "atirador":   "Recua da zona se estiver no corpo-a-corpo; depois atira no mais fraco.",
    "capturar":   "Quer o alvo vivo: golpes corpo a corpo nocauteiam (estável) em vez de matar.",
}


def set_npc_strategy(npc_name: str, strategy: str) -> str:
    """
    Define a estratégia de combate de um NPC para o sistema de turno automático.
    A estratégia determina como execute_npc_turn() escolhe o alvo.

    Estratégias disponíveis:
    • agressivo  — ataca o alvo com mais HP (mais ameaçador)
    • tático     — ataca o alvo com menos HP (eliminar o mais fraco)
    • covarde    — foge quando HP < 25%; senão ataca o mais fraco
    • aleatório  — escolhe alvo aleatoriamente
    • suporte    — cura aliados com HP < 50%; senão ataca
    • atirador   — recua da zona se estiver trancado no corpo-a-corpo, depois atira
    • capturar   — quer o alvo vivo: o corpo a corpo que derruba nocauteia

    Todas usam o poder de RECARGA (set_recharge_ability) assim que ele estiver
    carregado — é a jogada mais forte que a criatura tem.

    Args:
        npc_name: Nome do NPC.
        strategy: Nome da estratégia (agressivo, tático, covarde, aleatório, suporte, atirador).
    """
    cs = memory.campaign.get("combat_state", {})
    if not cs.get("is_active"):
        return "Nenhum combate ativo."
    strategy = strategy.lower().strip()
    if strategy not in NPC_STRATEGIES:
        opts = ", ".join(NPC_STRATEGIES.keys())
        return f"Aviso: Estratégia '{strategy}' inválida. Opções: {opts}"
    cs.setdefault("npc_strategies", {})[npc_name.lower()] = strategy
    memory.save_campaign()
    return f"Estratégia de {npc_name} definida: **{strategy}** — {NPC_STRATEGIES[strategy]}"


# ── Repertório do NPC ──────────────────────────────────────────────────────
# O turno automático sabia fazer uma coisa só: escolher alvo e bater. Um
# clérigo inimigo com Curar Ferimentos na ficha batia; um dragão com sopro
# carregado batia; um arqueiro trancado no corpo-a-corpo continuava atirando
# com desvantagem. Estes três auxiliares dão ao motor as jogadas que a ficha
# já prometia.

def _npc_habilidade(char: dict, *termos: str) -> dict | None:
    """Primeira habilidade da ficha cujo nome contenha um dos termos."""
    for hab in (char.get("habilidades") or []):
        nome = _norm_txt(hab.get("nome", ""))
        if nome and any(_norm_txt(t) in nome for t in termos):
            return hab
    return None


def _npc_tentar_curar(npc: dict, npc_name: str) -> str:
    """
    Suporte: cura o aliado mais ferido abaixo de 50% de PV.
    Devolve "" quando não há quem curar, com o que curar, ou mana para isso.
    """
    hab = _npc_habilidade(npc, "cura", "curar", "cure", "heal", "palavra curativa")
    if not hab:
        return ""
    sheet = npc.get("sheet") or {}
    custo = int(hab.get("custo_mana", 0) or 0)
    if custo and int(sheet.get("mana_atual", 0) or 0) < custo:
        return ""

    cs      = memory.campaign.get("combat_state", {}) or {}
    chars   = memory.campaign.get("characters", {})
    do_lado = memory.luta_com_o_grupo(npc)

    ferido, pior = None, 1.0
    for nome in cs.get("initiative_order", []) or []:
        outro = chars.get(memory.char_key(nome))
        if not outro:
            continue
        if memory.luta_com_o_grupo(outro) != do_lado:
            continue
        if (outro.get("status", "vivo") or "").lower() in OUT_OF_COMBAT_STATUSES:
            continue
        s = outro.get("sheet") or {}
        atual, maximo = int(s.get("vida_atual", 0) or 0), int(s.get("vida_max", 1) or 1)
        if atual <= 0:
            continue
        pct = atual / max(1, maximo)
        if pct < 0.5 and pct < pior:
            ferido, pior = outro, pct

    if not ferido:
        return ""

    return use_ability(
        char_name        = npc_name,
        ability_name     = hab.get("nome", ""),
        target_name      = ferido.get("name", ""),
        end_turn         = True,
        _skip_turn_check = True,
    )


# Quando o inimigo bebe: metade da vida ou menos, o "ferido" do 5e.
_NPC_LIMIAR_DE_POCAO = 0.5


def _npc_beber_pocao(npc: dict, npc_name: str) -> str:
    """
    Poção de cura da mochila do próprio inimigo, na vez dele.

    Passa pelo mesmo caminho do jogador (`combat_action`), que gasta a Ação
    Bônus, rola o dado, respeita o teto da exaustão e dá baixa na unidade —
    beber não custa o ataque do turno. Devolve "" quando não há poção, ele
    não está ferido, ou o motor recusou (bônus já gasto, por exemplo).
    """
    sheet = npc.get("sheet") or {}
    hp     = int(sheet.get("vida_atual", 0) or 0)
    hp_max = max(1, int(sheet.get("vida_max", 1) or 1))
    if hp <= 0 or hp / hp_max > _NPC_LIMIAR_DE_POCAO:
        return ""

    for item in (npc.get("inventario") or []):
        if not isinstance(item, dict) or int(item.get("qtd", 1) or 1) <= 0:
            continue
        ficha = _efeito_de_item(item.get("nome", ""))
        if not ficha or ficha.get("efeito") != "cura":
            continue
        resposta = combat_action("item", actor=npc_name, target=npc_name,
                                 item=item.get("nome", ""))
        # Recusa do motor não vira segunda tentativa: o inimigo parte para o
        # ataque, que é o que ele faria de qualquer jeito.
        return resposta.get("message", "") if resposta.get("ok") else ""
    return ""


def _npc_poder_de_recarga(npc: dict) -> str:
    """Nome do poder de recarga que está carregado agora (ou "")."""
    for nome, cfg in ((npc.get("sheet") or {}).get("recargas") or {}).items():
        if isinstance(cfg, dict) and cfg.get("pronto", False):
            return nome
    return ""


# ── Conjuração do monstro (bloco "Spellcasting" do Open5e) ─────────────────
_ATRIBUTO_EN = {"intelligence": "inteligencia", "wisdom": "sabedoria", "charisma": "carisma"}
_LINHA_CIRCULO_RE = re.compile(r"(cantrips|(\d)(?:st|nd|rd|th)[- ]level)[^:]*:\s*(.+)", re.I)
_LINHA_INATA_RE = re.compile(r"(at will|\d+/day(?: each)?)\s*:\s*(.+)", re.I)


def _magias_do_bloco(texto: str) -> dict:
    """
    Lê o bloco "Spellcasting"/"Innate Spellcasting" do stat block:
    {nivel_conjurador, atributo, magias: [(nome_srd, nivel, a_vontade)]}.
    Só entram as magias que o compêndio conhece.
    """
    from rpg import compendio
    texto = texto or ""
    nivel = re.search(r"(\d+)(?:st|nd|rd|th)-level spellcaster", texto, re.I)
    attr = re.search(r"spellcasting ability is (\w+)", texto, re.I)
    magias = []
    for linha in re.split(r"[\n•]+", texto):
        linha = linha.strip(" -*")
        m1 = _LINHA_CIRCULO_RE.search(linha)
        m2 = None if m1 else _LINHA_INATA_RE.search(linha)
        if not (m1 or m2):
            continue
        lista = (m1.group(3) if m1 else m2.group(2))
        a_vontade = bool((m1 and m1.group(1).lower() == "cantrips") or (m2 and m2.group(1).lower() == "at will"))
        for bruto in lista.split(","):
            nome = re.sub(r"\(.*?\)", "", bruto).replace("*", "").replace("_", "").strip(" .")
            m = compendio.magia(nome) if nome else None
            if m and all(m["nome_srd"] != x[0] for x in magias):
                magias.append((m["nome_srd"], int(m.get("nivel", 0) or 0), a_vontade))
    return {"nivel_conjurador": int(nivel.group(1)) if nivel else 0,
            "atributo": _ATRIBUTO_EN.get((attr.group(1) if attr else "").lower(), ""),
            "magias": magias}


def _dar_magias_do_bloco(sheet: dict, habilidades: list, texto: str) -> int:
    """Põe na ficha do monstro as magias do bloco, com mana de conjurador. Devolve quantas."""
    from rpg import compendio
    bloco = _magias_do_bloco(texto)
    if not bloco["magias"]:
        return 0
    if bloco["atributo"]:
        sheet["atributo_conjuracao"] = bloco["atributo"]
    if bloco["nivel_conjurador"]:
        pontos = SPELL_POINTS_BY_LEVEL.get(min(20, bloco["nivel_conjurador"]), 0)
        sheet["mana_max"] = sheet["mana_atual"] = max(int(sheet.get("mana_max", 0) or 0), pontos)
    for nome_srd, nivel, a_vontade in bloco["magias"]:
        m = compendio.magia(nome_srd) or {}
        habilidades.append({
            "nome": nome_srd, "nivel_magia": nivel,
            "descricao": f"[{m.get('escola', 'Magia')}] {m.get('resumo', '')}",
            "custo_mana": 0 if (a_vontade or nivel == 0) else SPELL_MANA_COST.get(nivel, 2),
            "dado": "",
        })
    # Inata sem nível de conjurador: mana para as magias por dia.
    if not bloco["nivel_conjurador"] and not sheet.get("mana_max"):
        sheet["mana_max"] = sheet["mana_atual"] = sum(
            SPELL_MANA_COST.get(n, 2) for _, n, a in bloco["magias"] if not a and n > 0)
    return len(bloco["magias"])


def _media_da_formula(formula: str) -> float:
    if not formula:
        return 0.0
    n, faces, bonus = _parse_dice(formula)
    return n * (faces + 1) / 2 + bonus


def _npc_conjurar(npc: dict, npc_name: str, alvo_nome: str, targets: list, golpe_medio: float) -> str:
    """
    O NPC conjura em vez de atacar quando a magia rende mais: dano esperado
    maior (somando os inimigos que a área pega, e nunca com aliado dentro),
    ou uma magia de controle quando ele ainda não está concentrado.
    Devolve "" quando não vale a pena ou o motor recusa (aí ele ataca).
    """
    from rpg import resolucao
    s = npc.get("sheet") or {}
    mana = int(s.get("mana_atual", 0) or 0)
    lado = memory.luta_com_o_grupo(npc)
    alvo_ch = memory.campaign["characters"].get(memory.char_key(alvo_nome)) or {}
    opcoes = []
    for h in npc.get("habilidades") or []:
        m = resolucao._magia_srd(h) if isinstance(h, dict) else None
        if not m or int(h.get("custo_mana", 0) or 0) > mana:
            continue
        tipo = resolucao.como_resolve(h, npc)["tipo"]
        if tipo != "motor":
            continue
        if m.get("efeito") == "dano" and dado_efetivo(h, npc):
            valor = _media_da_formula(dado_efetivo(h, npc))
            if area_da_habilidade(h):
                _z, atingidos = _alvos_em_area(npc_name, h, alvo_nome)
                if atingidos:
                    if any(memory.luta_com_o_grupo(a) == lado for a in atingidos):
                        continue
                    valor *= len(atingidos)
            opcoes.append((valor, h))
        elif (m.get("efeito") == "condicao" and m.get("condicao") and not s.get("concentracao")
              and not any(_norm_txt(c.get("nome", "") if isinstance(c, dict) else str(c))
                          == _norm_txt(m["condicao"]) for c in (alvo_ch.get("sheet") or {}).get("condicoes") or [])):
            opcoes.append((max(12.0, golpe_medio + 1), h))
    if not opcoes:
        return ""
    valor, hab = max(opcoes, key=lambda x: x[0])
    if valor <= golpe_medio:
        return ""
    resultado = use_ability(npc_name, hab["nome"], alvo_nome, end_turn=True, _skip_turn_check=True)
    if resultado.startswith(("Erro", "Aviso")):
        return ""
    return f"{npc_name} conjura **{(resolucao._magia_srd(hab) or {}).get('nome', hab['nome'])}**!\n{resultado}"


def _npc_usar_poder(npc: dict, npc_name: str, poder: str, alvo: str) -> str:
    """
    Dispara um poder de recarga e o marca como gasto.
    Devolve "" se a ficha não tiver a habilidade correspondente — sem ela o
    motor não sabe dado nem custo, e inventar seria pior que não usar.
    """
    hab = None
    for h in (npc.get("habilidades") or []):
        if _norm_txt(h.get("nome", "")) == _norm_txt(poder):
            hab = h
            break
    if not hab:
        return ""

    _gastar_recarga(npc, poder)
    resultado = use_ability(
        char_name        = npc_name,
        ability_name     = hab.get("nome", ""),
        target_name      = alvo,
        end_turn         = True,
        _skip_turn_check = True,
    )
    return f"{npc_name} descarrega **{poder}**!\n{resultado}"


def _npc_recuar_para_atirar(npc: dict, npc_name: str) -> str:
    """
    Atirador trancado no corpo-a-corpo recua uma zona para atirar limpo.
    Sai vazio se não houver zonas, se ninguém o estiver trancando, ou se não
    houver para onde ir. O recuo provoca ataque de oportunidade, como deve.
    """
    if not _zonas_ativas():
        return ""
    if not _inimigos_na_zona(npc_name):
        return ""

    zonas  = _zonas()
    atual  = _zona_de(npc_name)
    if atual not in zonas:
        return ""
    i = zonas.index(atual)

    # Recua para o lado oposto ao grosso do inimigo: se o NPC é do fundo da
    # trilha, afasta-se para o fundo; se está na ponta, tenta o outro sentido.
    candidatos = []
    if memory.luta_com_o_grupo(npc):
        candidatos = [i - 1, i + 1]
    else:
        candidatos = [i + 1, i - 1]
    for j in candidatos:
        if 0 <= j < len(zonas) and not _inimigos_na_zona(npc_name, zonas[j]):
            return "Recua para atirar: " + move_combatant(npc_name, zonas[j])
    return ""


def _npc_aproximar(npc_name: str, alvo: str) -> tuple[str, bool]:
    """
    NPC só de corpo-a-corpo, longe do alvo, anda até ele.

    A uma zona é movimento comum e ainda sobra a Ação para o golpe. A duas ou
    mais só a Disparada chega (duas zonas), e ela gasta a Ação: o golpe fica
    para o próximo turno. Devolve (texto, pode_atacar_agora).

    Antes disto o NPC chamava attack_roll de onde estava, o motor recusava
    por alcance e o turno não andava — a tela tática ficava presa em "Turno
    do Inimigo".
    """
    zonas = _zonas()
    za, zb = _zona_de(npc_name), _zona_de(alvo)
    if za not in zonas or zb not in zonas or za == zb:
        return "", True
    # Agarrado, Contido, Aprisionado: não sai da zona. Agarrado gasta a Ação
    # tentando escapar; o resto espera.
    _npc_ch = memory.campaign["characters"].get(memory.char_key(npc_name)) or {}
    _preso_mv = _condicao_com(_npc_ch, "no_movement")
    if _preso_mv:
        if _norm_txt(_preso_mv) == "agarrado":
            from rpg import manobras as _manobras
            return _manobras.escapar(npc_name), False
        return f"{npc_name} está {_preso_mv} e não sai da zona.", False
    i, j = zonas.index(za), zonas.index(zb)
    dist = abs(j - i)
    passo = 1 if j > i else -1
    if dist == 1:
        texto = move_combatant(npc_name, zb)
    else:
        texto = move_combatant(npc_name, zonas[i + 2 * passo], dash=True)

    npc = memory.campaign["characters"].get(memory.char_key(npc_name)) or {}
    de_pe = int((npc.get("sheet") or {}).get("vida_atual", 0) or 0) > 0
    return texto, (dist == 1 and de_pe and _zona_de(npc_name) == zb)


def execute_npc_turn(npc_name: str = "", _forcar: bool = False) -> str:
    """
    Executa o turno do NPC atual (ou do NPC especificado) de forma totalmente
    determinística: escolhe alvo com base na estratégia configurada e chama
    attack_roll() automaticamente. A IA só precisa narrar o resultado.

    Se nenhuma estratégia foi configurada, usa 'agressivo' por padrão.
    Se o NPC for covarde e estiver com HP < 25%, foge do combate.
    Com zonas, o NPC de corpo-a-corpo anda até o alvo antes de golpear.

    Args:
        npc_name: Nome do NPC (opcional — se omitido, usa o NPC do turno atual).
    """
    cs = memory.campaign.get("combat_state", {}) or {}
    _pend = cs.get("reacao_pendente")
    if _pend:
        return (f"Aviso: o turno de {_pend.get('npc')} está parado esperando o jogador decidir: "
                f"{_pend.get('texto')} Pergunte e chame responder_reacao(usar=True ou False).")
    from rpg import reacoes as _rea
    if _rea._respostas is None and _rea.alguem_pergunta():
        return _com_perguntas({"fn": "execute_npc_turn", "kw": {"npc_name": npc_name, "_forcar": _forcar}},
                              [], None)
    token = cs.get("turn_token", 0)
    vez   = _combat_current_actor()
    from rpg import criaturas as _cri_t
    _ch_vez = memory.campaign["characters"].get(memory.char_key(vez)) if vez else None
    if _ch_vez and _cri_t.controlada_pelo_jogador(_ch_vez) and not _forcar:
        _dono = (memory.campaign["characters"].get(_ch_vez["invocacao"].get("por", "")) or {}).get("name", "")
        return (f"Aviso: {vez} é invocação de {_dono}: o turno é do jogador. Pergunte o que {vez} faz e "
                f"use attack_roll / use_ability com ela (ou end_turn). Se o jogador pedir, "
                f"combat_action('auto') deixa o motor jogar esta vez.")
    saida = _executar_turno_npc(npc_name)

    # O turno de um NPC SEMPRE termina. Se algo sobrou recusado (um alvo que
    # ninguém alcança, um golpe que o motor não aceitou), passar a vez é
    # melhor que prender a luta: a tela tática chamaria de novo até desistir.
    cs = memory.campaign.get("combat_state", {}) or {}
    ainda_ele = (vez and cs.get("is_active")
                 and cs.get("turn_token", 0) == token
                 and _combat_current_actor() == vez)
    if ainda_ele:
        ch = memory.campaign["characters"].get(memory.char_key(vez)) or {}
        if ch and not memory.is_party_member(ch) and (_forcar or not _cri_t.controlada_pelo_jogador(ch)):
            _log_combat_event("pass", vez, "", msg=f"{vez} não conseguiu agir e passou a vez")
            saida += f"\n{vez} não consegue agir e passa a vez." + _auto_advance_turn(vez)
    return saida


def _com_perguntas(chamada: dict, respostas: list, rng):
    """
    Uma jogada que pode parar para o jogador decidir uma reação (rpg/reacoes.py,
    modo "perguntar"): o turno do inimigo, a ação do jogador na tela, o
    attack_roll ou o use_ability do Mestre. Guarda a campanha e o sorteio; se a
    pergunta chega, desfaz a jogada inteira e grava a pergunta pendente com a
    jogada. A resposta (responder_reacao) roda a jogada de novo com o mesmo
    sorteio — os mesmos dados, até a mesma pergunta, que agora tem resposta.
    """
    import copy
    from rpg import reacoes as _rea
    vez = _combat_current_actor()
    token = (memory.campaign.get("combat_state") or {}).get("turn_token", 0)
    copia = copy.deepcopy(memory.campaign.copy())
    if rng is None:
        rng = random.getstate()
    else:
        random.setstate(rng)
    _rea._respostas, _rea._indice = list(respostas), 0
    try:
        if chamada["fn"] not in ("execute_npc_turn", "combat_action", "attack_roll", "use_ability"):
            raise ValueError(f"jogada desconhecida: {chamada['fn']}")
        return globals()[chamada["fn"]](**chamada["kw"])
    except _rea.PerguntaDeReacao as p:
        memory.campaign.clear()
        memory.campaign.update(copia)
        cs = memory.campaign.get("combat_state") or {}
        cs["reacao_pendente"] = {"npc": vez, "token": token, "quem": p.quem, "chave": p.chave,
                                 "texto": p.texto, "nome": _rea.REACOES.get(p.chave, {}).get("nome", p.chave),
                                 "respostas": list(respostas), "chamada": chamada,
                                 "rng": [rng[0], list(rng[1]), rng[2]]}
        memory.save_campaign()
        texto = (f"**REAÇÃO — {p.quem} decide**\n   {p.texto}\n"
                 f"   A jogada de {vez} está parada. Pergunte ao jogador e chame "
                 f"responder_reacao(usar=True ou False).")
        if chamada["fn"] == "combat_action":
            return {"ok": True, "message": texto, "snapshot": combat_snapshot()}
        return texto
    finally:
        _rea._respostas, _rea._indice = None, 0


def _pode_perguntar_agora(kw: dict) -> bool:
    """attack_roll / use_ability chamados de fora (o Mestre), em combate, com alguém em 'perguntar'."""
    from rpg import reacoes as _rea
    return (_rea._respostas is None and not kw.get("_skip_turn_check")
            and bool((memory.campaign.get("combat_state") or {}).get("is_active"))
            and _rea.alguem_pergunta())


def _aviso_de_pergunta_pendente() -> str:
    pend = (memory.campaign.get("combat_state") or {}).get("reacao_pendente")
    if not pend:
        return ""
    return (f"Aviso: a jogada de {pend.get('npc')} está parada esperando o jogador decidir: "
            f"{pend.get('texto')} Pergunte e chame responder_reacao(usar=True ou False). Nada foi feito.")


def responder_reacao(usar: bool) -> str:
    """
    Responde à reação que parou o turno do inimigo (modo "perguntar" da tela de
    combate): o motor usa ou não a reação e o turno do inimigo continua com os
    mesmos dados.

    Args:
        usar: True para usar a reação (Escudo Arcano, Esquiva Sobrenatural,
              Contramágica...), False para deixar passar.
    """
    cs = memory.campaign.get("combat_state") or {}
    pend = cs.get("reacao_pendente")
    if not pend:
        return "Aviso: nenhuma reação esperando decisão."
    cs.pop("reacao_pendente", None)
    if (not cs.get("is_active")
            or memory.char_key(_combat_current_actor()) != memory.char_key(pend.get("npc", ""))
            or ("token" in pend and cs.get("turn_token", 0) != pend["token"])):
        memory.save_campaign()
        return "Aviso: o turno mudou e a pergunta caducou. Nada foi feito."
    estado = pend.get("rng") or []
    rng = (estado[0], tuple(estado[1]), estado[2]) if len(estado) == 3 else None
    respostas = list(pend.get("respostas") or []) + [bool(usar)]
    chamada = pend.get("chamada") or {"fn": "execute_npc_turn",
                                      "kw": {"npc_name": pend.get("npc", ""), "_forcar": bool(pend.get("forcar"))}}
    decisao = (f"{pend.get('quem')}: {'usa' if usar else 'não usa'} {pend.get('nome', pend.get('chave'))}.\n")
    saida = _com_perguntas(chamada, respostas, rng)
    if isinstance(saida, dict):
        saida = saida.get("message", "")
    return decisao + saida


def _turno_confuso(npc: dict, npc_name: str) -> str:
    """
    Confusão (SRD), um d10 no começo do turno:
      1     anda para uma zona vizinha qualquer e não age;
      2–6   não faz nada;
      7–8   ataca uma criatura qualquer ao alcance — aliada inclusive;
      9–10  age normalmente ('' — o turno segue o caminho de sempre).
    """
    d10 = random.randint(1, 10)
    if d10 >= 9:
        return ""
    if d10 == 1:
        zonas, aqui = _zonas(), _zona_de(npc_name)
        if aqui in zonas:
            i = zonas.index(aqui)
            vizinhas = [zonas[j] for j in (i - 1, i + 1) if 0 <= j < len(zonas)]
            if vizinhas:
                destino = random.choice(vizinhas)
                movido = move_combatant(npc_name, destino)
                linha = f"{npc_name} está Confuso (d10={d10}): vaga sem rumo.\n{movido}"
                _log_combat_event("pass", npc_name, "", msg=f"{npc_name} vaga confuso")
                return linha + _auto_advance_turn(npc_name)
        msg = f"{npc_name} está Confuso (d10={d10}): cambaleia sem rumo e não age."
    elif d10 <= 6:
        msg = f"{npc_name} está Confuso (d10={d10}): não faz nada neste turno."
    else:
        cs = memory.campaign.get("combat_state") or {}
        arma = _melee_weapon_of(npc)
        perto = []
        for nm in cs.get("initiative_order") or []:
            ch = memory.campaign["characters"].get(memory.char_key(nm))
            if (not ch or ch is npc
                    or (ch.get("status") or "").lower() in OUT_OF_COMBAT_STATUSES
                    or int((ch.get("sheet") or {}).get("vida_atual", 0) or 0) <= 0):
                continue
            if _checar_alcance(npc_name, ch.get("name", nm), arma)[0]:
                continue
            perto.append(ch.get("name", nm))
        if perto:
            alvo = random.choice(perto)
            golpe = attack_roll(npc_name, alvo, arma, 6, end_turn=True, _skip_turn_check=True)
            return f"{npc_name} está Confuso (d10={d10}): ataca quem estiver perto — {alvo}.\n{golpe}"
        msg = f"{npc_name} está Confuso (d10={d10}): não há ninguém ao alcance para atacar."
    _log_combat_event("pass", npc_name, "", msg=msg)
    memory.save_campaign()
    return msg + _auto_advance_turn(npc_name)


def _executar_turno_npc(npc_name: str = "") -> str:
    cs = memory.campaign.get("combat_state", {})
    if not cs.get("is_active"):
        return "Nenhum combate ativo."

    # Auto-cura: desencalha o ponteiro se o atual saiu de combate.
    _heal_current_turn()
    cs = memory.campaign.get("combat_state", {})
    if not cs.get("is_active"):
        return "Combate encerrado — nenhum combatente restante."

    order = cs.get("initiative_order", [])
    if not order:
        return "Ordem de iniciativa vazia."

    # O motor é a autoridade: age SEMPRE pelo combatente do turno atual,
    # ignorando um npc_name divergente que o LLM possa ter passado.
    idx      = cs.get("current_turn_index", 0)
    npc_name = order[idx] if 0 <= idx < len(order) else ""
    if not npc_name:
        return "Não foi possível determinar o NPC atual."

    npc, err = _get_char(npc_name)
    if not npc:
        return f"Erro: NPC '{npc_name}' não encontrado: {err.removeprefix('Erro: ')}"

    # Definição canônica de grupo (memory.is_party_member): party_member,
    # protagonista ou campaign["party"].
    chars = memory.campaign.get("characters", {})

    if memory.is_party_member(npc):
        return (
            f"Aviso: {npc_name} é um personagem do grupo — use attack_roll() "
            f"conforme instrução do jogador."
        )

    # Paralisado, Atordoado, Incapacitado, Banido: não age. Antes o orc
    # Paralisado pelo Imobilizar Pessoa atacava normalmente, só com desvantagem.
    from rpg import encantos
    encantos.expirar()
    preso = _impedido_de_agir(npc)
    if preso:
        _log_combat_event("pass", npc_name, "", msg=f"{npc_name} está {preso} e não age")
        memory.save_campaign()
        return f"{npc_name} está **{preso}** e não age neste turno." + _auto_advance_turn(npc_name)

    # Familiar: não ataca (SRD). Ajuda contra o inimigo da zona dele, ou se esquiva.
    if (npc.get("sheet") or {}).get("nao_ataca"):
        from rpg import manobras as _manobras
        _inimigos_aqui = _inimigos_na_zona(npc_name, _zona_de(npc_name)) if _zonas_ativas() else [
            c["name"] for c in (memory.campaign.get("characters") or {}).values()
            if memory.char_key(c.get("name", "")) in {memory.char_key(n) for n in
                                                      (memory.campaign["combat_state"].get("initiative_order") or [])}
            and not memory.luta_com_o_grupo(c) and (c.get("status") or "").lower() not in OUT_OF_COMBAT_STATUSES]
        if _inimigos_aqui:
            _txt_f = _manobras.ajudar(npc_name, _inimigos_aqui[0])
        else:
            dar_efeito_de_combate(npc, {"nome": "Esquiva", "desvantagem_contra_mim": True,
                                        "ate_turno_de": memory.char_key(npc_name)})
            _txt_f = f"{npc_name} se esquiva e fica por perto."
        memory.save_campaign()
        return _txt_f + _auto_advance_turn(npc_name)

    # Quem preparou um ataque contra ele (ação Preparar) ataca antes.
    from rpg import manobras as _manobras
    _preparados = _manobras.disparar_preparadas(npc_name)
    if _preparados and int((npc.get("sheet") or {}).get("vida_atual", 0) or 0) <= 0:
        memory.save_campaign()
        return "\n".join(_preparados) + _auto_advance_turn(npc_name)

    # Confusão: o d10 decide o turno (SRD).
    if any(_norm_txt(c.get("nome", "") if isinstance(c, dict) else str(c)) == "confuso"
           for c in _get_conditions(npc)):
        confuso = _turno_confuso(npc, npc_name)
        if confuso:
            return confuso

    strategy = cs.get("npc_strategies", {}).get(npc_name.lower(), "agressivo")
    npc_sheet = npc.get("sheet", {}) or {}

    # O que voltou a estar disponível neste turno. _inicio_de_turno já rolou os
    # d6 quando o ponteiro chegou aqui; isto só traz o aviso para a narração.
    avisos_recarga = list(_preparados)
    for _nome_rec, _cfg in (npc_sheet.get("recargas") or {}).items():
        if _cfg.get("pronto") and _cfg.get("ultimo_d6"):
            avisos_recarga.append(
                f"**{_nome_rec}** recarregou (d6={_cfg.pop('ultimo_d6')}).")

    # Lógica de fuga (covarde)
    if strategy == "covarde":
        hp_pct = (npc_sheet.get("vida_atual", 1) /
                  max(1, npc_sheet.get("vida_max", 1)))
        if hp_pct <= 0.25:
            # Fugir não é grátis: quem está em contato leva o bote.
            oportunidade = _provoke_opportunity_attacks(npc_name, "fugir")
            npc["status"] = "fugiu"
            _log_combat_event("flee", npc_name, "",
                              msg=f"{npc_name} fugiu do combate")
            memory.save_campaign()
            advance = _auto_advance_turn(npc_name)
            return (
                f"{npc_name} está com {int(hp_pct * 100)}% de HP e FOGE do combate!"
                f"{oportunidade}{advance}"
            )

    # Monta lista de alvos válidos: o lado oposto ao do NPC, vivo e em pé. Um
    # aliado (o mercador que você escolta) mira nos inimigos, não no grupo.
    OUT = ("morto", "estabilizado", "inconsciente", "fugiu", "exilado", "rendido")
    meu_lado = memory.luta_com_o_grupo(npc)
    # Só quem está NA luta: a lista varria a campanha inteira e o motor
    # chegou a mandar um aliado atacar um NPC que estava noutra cidade.
    na_luta = [chars.get(memory.char_key(n)) for n in (cs.get("initiative_order") or [])]
    targets = []
    for p_char in na_luta:
        if not p_char:
            continue
        if memory.luta_com_o_grupo(p_char) == meu_lado:
            continue
        if p_char.get("status", "vivo").lower() in OUT:
            continue
        p_sheet = p_char.get("sheet", {}) or {}
        if p_sheet.get("vida_atual", 0) <= 0:
            continue
        # Enfeitiçado não mira quem o enfeitiçou; ninguém alcança o banido.
        if encantos.pode_atacar(npc, p_char) or _condicao_com(p_char, "untargetable"):
            continue
        targets.append({
            "name":   p_char.get("name", ""),
            "hp":     p_sheet.get("vida_atual", 0),
            "hp_max": p_sheet.get("vida_max", 1),
        })

    if not targets:
        e_enc = encantos.ativo(npc)
        if e_enc:
            _log_combat_event("pass", npc_name, "",
                              msg=f"{npc_name} está enfeitiçado por {e_enc['por_nome']} e não ataca")
            memory.save_campaign()
            return (f"{npc_name} está {'Dominado' if e_enc['tipo'] == 'dominado' else 'Enfeitiçado'} "
                    f"por {e_enc['por_nome']} e não ataca ninguém do lado dele."
                    + _auto_advance_turn(npc_name))
        return (f"{npc_name} não encontra alvos válidos. Verifique se o combate deve encerrar com "
                f"end_combat() — inimigos enfeitiçados, dominados ou rendidos não precisam morrer.")

    # Golpes do turno. O Ataque Múltiplo do urso-coruja é "um com o bico e um
    # com as garras" — então alternamos entre os ataques do stat block em vez
    # de repetir o mesmo, que erraria o dado (1d10 vs 2d8) e a narrativa.
    npc_equip = npc_sheet.get("equipamentos", {}) or {}
    repertorio = [a for a in (npc_sheet.get("ataques") or [])
                  if isinstance(a, dict) and a.get("nome")]
    if not repertorio:
        repertorio = [{"nome": npc_equip.get("arma_principal") or "shortsword",
                       "ranged": False}]
    # Mesmo critério de _checar_alcance: é o nome da arma que o motor julga.
    golpes_de_tiro = [a for a in repertorio if _weapon_is_ranged(a["nome"])]

    # Com zonas, quem só luta corpo-a-corpo vai no mais próximo: atravessar o
    # campo atrás do de mais PV, passando por quem está do lado, seria perder
    # turnos e levar ataque de oportunidade à toa.
    if _zonas_ativas() and not golpes_de_tiro:
        dists = {t["name"]: _distancia(npc_name, t["name"]) for t in targets}
        conhecidas = [d for d in dists.values() if d is not None]
        if conhecidas:
            menor = min(conhecidas)
            targets = [t for t in targets if dists[t["name"]] == menor]

    # Seleção de alvo por estratégia
    if strategy == "agressivo":
        target = max(targets, key=lambda t: t["hp"])
    elif strategy in ("tático", "covarde", "atirador"):
        target = min(targets, key=lambda t: t["hp"])
    elif strategy == "aleatório":
        target = random.choice(targets)
    else:  # suporte ou padrão
        target = min(targets, key=lambda t: t["hp"])

    # 0) POÇÃO DE CURA do próprio inimigo, se ele está ferido. É Ação Bônus:
    #    entra na lista de avisos e o turno segue para a jogada principal.
    #    Sem isto, um inimigo com poção na mochila morria com ela na mão.
    gole = _npc_beber_pocao(npc, npc_name)
    if gole:
        avisos_recarga.append(gole)

    # ── Repertório: o NPC não é só uma sequência de ataques com arma ────────
    #
    # 1) SUPORTE curando de verdade. A estratégia estava documentada como
    #    "cura aliados com HP < 50%" desde sempre e nunca curou ninguém: caía
    #    no `else` e atacava. A promessa agora é cumprida.
    if strategy == "suporte":
        socorro = _npc_tentar_curar(npc, npc_name)
        if socorro:
            return "\n".join(avisos_recarga + [socorro])

    # 2) PODER DE RECARGA pronto (sopro de dragão e afins). É a jogada mais
    #    forte disponível e a razão de o poder existir — se está carregado,
    #    o monstro usa.
    poder = _npc_poder_de_recarga(npc)
    if poder:
        disparo = _npc_usar_poder(npc, npc_name, poder, target["name"])
        if disparo:
            return "\n".join(avisos_recarga + [disparo])

    # 2b) MAGIA. O inimigo que conjura só atacava de arma: o mago da partida
    #     morreu de adaga na mão com a Bola de Fogo na ficha. Agora ele conjura
    #     quando a magia rende mais que os golpes.
    _rep_m = [a for a in (npc_sheet.get("ataques") or []) if isinstance(a, dict) and a.get("nome")]
    _dado_m = _npc_attack_dice(npc_sheet, _rep_m[0]["nome"]) if _rep_m else None
    _golpe_medio = ((_dado_m[0] * (_dado_m[1] + 1) / 2 if _dado_m else 3.5)
                    + max(_modifier(int(npc_sheet.get("forca", 10) or 10)),
                          _modifier(int(npc_sheet.get("destreza", 10) or 10))))
    _golpe_medio *= max(1, min(_MULTIATTACK_MAX, int(npc_sheet.get("multiattack", 1) or 1)))
    magia = _npc_conjurar(npc, npc_name, target["name"], targets, _golpe_medio)
    if magia:
        return "\n".join(avisos_recarga + [magia])

    # 3) ATIRADOR trancado no corpo-a-corpo recua antes de atirar. Sem isso,
    #    um arqueiro com inimigo colado ficava atirando com desvantagem para
    #    sempre, que nenhum arqueiro faria.
    aviso_recuo = ""
    if strategy == "atirador":
        aviso_recuo = _npc_recuar_para_atirar(npc, npc_name)

    _RANGED_PT = ("arco", "besta", "dardo", "funda")

    def _atributo(atk: dict) -> str:
        """Destreza para ataques à distância; força para o resto."""
        if atk.get("ranged"):
            return "destreza"
        nome = (atk.get("nome") or "").lower()
        return "destreza" if any(k in nome for k in _RANGED_PT) else "forca"

    # Ataque Múltiplo: quantos golpes o stat block concede neste turno.
    n_ataques = max(1, min(_MULTIATTACK_MAX,
                           int(npc_sheet.get("multiattack", 1) or 1)))

    # Executa o(s) ataque(s). Só o ÚLTIMO avança o turno.
    # _skip_turn_check=True: o motor já garante que está agindo pelo NPC
    # correto do turno — a checagem de ordem não se aplica aqui.
    def _alvo_valido(nome: str) -> bool:
        ch = memory.campaign["characters"].get(memory.char_key(nome))
        if not ch or (ch.get("status", "vivo") or "").lower() in OUT:
            return False
        return int((ch.get("sheet") or {}).get("vida_atual", 0) or 0) > 0

    partes    = list(avisos_recarga)
    if aviso_recuo:
        partes.append(aviso_recuo)
    alvo_nome = target["name"]

    # Alcance. Longe do alvo: quem tem golpe de tiro atira de onde está (com
    # a desvantagem que o motor aplicar); quem não tem, anda até lá.
    if _zonas_ativas() and _distancia(npc_name, alvo_nome):
        if golpes_de_tiro:
            repertorio = golpes_de_tiro
        else:
            aproximacao, pode_atacar = _npc_aproximar(npc_name, alvo_nome)
            if aproximacao:
                partes.append(aproximacao)
            # Chegou na zona de quem preparou "o primeiro que chegar".
            partes.extend(_manobras.disparar_preparadas(npc_name))
            if int((npc.get("sheet") or {}).get("vida_atual", 0) or 0) <= 0:
                partes.append(_auto_advance_turn(npc_name))
                return "\n".join(partes)
            if not pode_atacar:
                partes.append(_auto_advance_turn(npc_name))
                return "\n".join(partes)

    if n_ataques > 1:
        partes.append(f"{npc_name} usa Ataque Múltiplo ({n_ataques} ataques):")

    for i in range(n_ataques):
        # O alvo pode ter caído no golpe anterior — 5e manda redirecionar os
        # ataques restantes, não desperdiçá-los num corpo no chão.
        if not _alvo_valido(alvo_nome):
            # Só redireciona para quem o golpe alcança: outro alvo em outra
            # zona seria uma recusa, não um ataque.
            golpe_nome = repertorio[i % len(repertorio)]["nome"]
            restantes = [t["name"] for t in targets
                         if t["name"] != alvo_nome and _alvo_valido(t["name"])
                         and not _checar_alcance(npc_name, t["name"], golpe_nome)[0]]
            if not restantes:
                partes.append(f"   Sem alvos de pé — {npc_name} interrompe a investida.")
                partes.append(_auto_advance_turn(npc_name))
                break
            alvo_nome = restantes[0]

        ultimo = (i == n_ataques - 1)
        golpe_atual = repertorio[i % len(repertorio)]
        golpe  = attack_roll(
            attacker_name    = npc_name,
            target_name      = alvo_nome,
            weapon           = golpe_atual["nome"],
            damage_dice_sides= 6,   # fallback; sobrescrito pelo stat block/SRD
            damage_dice_count= 1,
            attack_attribute = _atributo(golpe_atual),
            is_proficient    = True,
            end_turn         = ultimo,
            nao_letal        = (strategy == "capturar"),
            _skip_turn_check = True,
        )
        if not ultimo:
            # Não é ação bônus pendente — é o próximo golpe do Multiattack.
            golpe = golpe.replace(_BONUS_ACTION_HINT, "")
        partes.append(golpe)

    return "\n".join(partes)


# ===========================================================================
# API de COMBATE NA TELA (sem LLM)
# ---------------------------------------------------------------------------
# Funções puras sobre memory.campaign. O server.py só faz wrapper JSON.
# TODA a mecânica continua no motor já fuzzado (attack_roll/use_ability/
# execute_npc_turn/next_turn/roll_death_save) — estas funções NÃO recalculam
# nada: só orquestram intents e fotografam o estado para a tela.
# ===========================================================================

# ── Economia de ações 5e: o que é Ação Bônus por nome ──────────────────────
# Heurística por substring (case/acento-insensível). Default = Ação.
# Regras combinam SRD 2014 + revisão 2024 (poção como Bônus).
_ABILITY_BONUS_PATTERNS = (
    "healing word", "palavra curativa", "palavra de cura",
    "misty step", "passo brumoso",
    "second wind", "segunda folego", "segundo folego",
    # Surto de Ação saiu daqui: pela regra ele não custa ação NENHUMA — ele
    # DEVOLVE uma. Ver _e_surto_de_acao, logo abaixo.
    "cunning action", "acao astuta",
    "bardic inspiration", "inspiracao de bardo",
    "spiritual weapon", "arma espiritual",
    "shillelagh", "shillelah",
    "healing spirit", "espirito curativo",
    "hex",  # cast inicial é Bônus
    "mass healing word",
)


def _slot_da_habilidade(name: str, hab: dict | None = None, char: dict | None = None) -> str | None:
    """
    O que a habilidade gasta da economia do turno: "acao", "bonus" ou None
    (sem custo de ação — Guiar Ataque, Ataque Imprudente). A ação de classe
    diz o próprio slot (rpg/resolucao.py); o resto segue _ability_action_type.
    """
    if hab is not None:
        from rpg import resolucao
        slot = resolucao.como_resolve(hab, char).get("slot")
        if slot == "livre":
            return None
        if slot in ("acao", "bonus"):
            return slot
    return "bonus" if _ability_action_type(name, hab) == "bonus" else "acao"


def _ability_action_type(name: str, hab: dict | None = None) -> str:
    """
    'bonus' se a habilidade é Ação Bônus pela regra 5e; senão 'acao'.

    Com `hab`, pergunta ao compêndio primeiro. A lista de nomes abaixo não
    conhecia Palavra Curativa nem Arma Espiritual — ações bônus no SRD —, e a
    tela tática gastava a AÇÃO do turno inteira para usá-las. Reação continua
    contando como ação: a economia de turno ainda não tem reação.
    """
    srd = _srd(hab) if hab is not None else _srd({"nome": name})
    if srd is not None:
        return "bonus" if srd.get("acao") == "bonus" else "acao"
    n = _norm_txt(name)
    if not n:
        return "acao"
    for p in _ABILITY_BONUS_PATTERNS:
        if _norm_txt(p) in n:
            return "bonus"
    return "acao"


# ── Surto de Ação ─────────────────────────────────────────────────────────
# "Você pode se superar por um momento: no seu turno, pode tomar uma ação
# adicional." Ele não custa Ação nem Bônus — dá uma Ação a mais. O motor
# tratava como Ação Bônus e não devolvia nada, então o guerreiro gastava o
# Bônus e continuava com a mesma ação de antes: pelo jogo, usar Surto de Ação
# era pior do que não usar.
_SURTO_DE_ACAO = ("action surge", "surto de acao")


def _e_surto_de_acao(nome: str) -> bool:
    n = _norm_txt(nome)
    return bool(n) and any(p in n for p in _SURTO_DE_ACAO)


# ── Traços que não são ação ───────────────────────────────────────────────
# A ficha guarda numa lista só o que se USA (Segunda Fôlego, Fúria) e o que se
# ESCOLHE (Tradição Arcana, Arquétipo, Aumento de Atributo). O segundo grupo
# não tem alvo nem efeito: quando o mestre "usava" um deles, saía no log a
# linha sem sentido que o jogador viu — "Sonael usou Tradição Arcana em
# Mineiro Corrompido 2" — e ainda gastava o turno dele.
_TRACOS_PASSIVOS = (
    "tradicao", "arquetipo", "aumento de atributo", "aumento no valor de atributo",
    "estilo de luta", "especializacao", "caminho", "juramento", "circulo druidico",
    "dominio divino", "patrono", "origem magica", "escola arcana", "linhagem",
    "colegio", "conclave", "proficiencia", "pacto", "subclasse",
)


def _e_traco_passivo(nome: str) -> bool:
    n = _norm_txt(nome)
    return bool(n) and any(p in n for p in _TRACOS_PASSIVOS)


# ── Onde a habilidade nasce ───────────────────────────────────────────────
# Burning Hands é "Self (15-foot cone)": o cone sai das MÃOS do conjurador.
# O motor só conferia alcance de ataque com arma, então a magia de cone
# acertava alguém do outro lado da câmara.
_HABILIDADE_NA_PROPRIA_ZONA = (
    "burning hands", "maos flamejantes", "maos ardentes",
    "thunderwave", "onda trovejante",
    "color spray", "borrifo prismatico", "jorro de cores",
    "cone of cold", "cone de frio",
    "breath weapon", "sopro",
)


def _habilidade_nasce_no_conjurador(hab: dict | None, nome: str) -> str:
    """
    Devolve o motivo (texto curto) quando a habilidade só alcança a própria
    zona; "" quando ela pode atravessar o campo.
    """
    alcance = _norm_txt((hab or {}).get("alcance") or "")
    if alcance.startswith("self") or alcance.startswith("pessoal"):
        return "sai do próprio conjurador"
    if alcance.startswith("touch") or alcance.startswith("toque"):
        return "é de toque"
    if not alcance and any(p in _norm_txt(nome) for p in _HABILIDADE_NA_PROPRIA_ZONA):
        return "sai do próprio conjurador"
    return ""


# ── Habilidades que afetam SOMENTE o conjurador (sem picker de alvo) ──────
# Match por substring no nome normalizado.
_ABILITY_SELF_ONLY_PATTERNS = (
    "second wind", "segunda folego", "segundo folego",
    "rage", "furia",
    "wild shape", "forma selvagem",
    "action surge", "surto de acao",
    "patient defense", "defesa paciente",
    "step of the wind", "passo do vento",
    # O Escudo da Fé estava aqui: no SRD ele vai em "uma criatura à sua
    # escolha". Como era só texto, ninguém notou; agora que ele dá +2 de CA
    # de verdade, mandá-lo sempre para quem conjura roubava o aliado.
)


def _is_self_only_ability(name: str) -> bool:
    n = _norm_txt(name)
    return bool(n) and any(p in n for p in _ABILITY_SELF_ONLY_PATTERNS)


def _ability_target_mode(name: str, hab: dict | None = None) -> str:
    """
    Modo de alvo para a UI tática decidir se mostra picker.

    Fonte primária de verdade: o campo `alcance` do habilidade (vem do
    Open5e — "Self", "Self (15-foot cone)", "60 feet", "Touch"…). Não
    mantemos lista hardcoded de magias.

    Fallbacks (para dados que NÃO vêm do Open5e):
      • Class features SRD (Segunda Fôlego, Fúria…): lista pequena fixa.
      • Pool spells (Sleep, Color Spray): tabela CONTROL_SPELL_EFFECTS
        — são 2 itens no SRD, e a mecânica "pool de HP" é única do 5e.
      • Heurística por nome para legados sem `alcance`.

    Retornos:
      "self"   → afeta só o conjurador (sem picker).
      "pool"   → área com pool de HP, múltiplos alvos (Sleep). Sem picker.
      "area_self" → área que nasce no conjurador (cone das Mãos Flamejantes):
                 pega a zona dele, sem picker.
      "area"   → área posta à distância (Bola de Fogo): o picker escolhe uma
                 criatura, e a magia pega a ZONA dela inteira.
      "single" → alvo único.

    Área só vale com zonas no campo (set_battlefield). Sem elas, use_ability
    resolve como alvo único e o rótulo da UI seria mentira — por isso os dois
    modos de área viram "single" quando o combate não tem zonas.
    """
    # 1. Class features SRD — sempre self-only (lista fixa pequena).
    if _is_self_only_ability(name):
        return "self"

    # 2. Pool spells — só Sleep e Color Spray no SRD, mecânica peculiar.
    if hab is not None:
        eff = _get_control_effect(hab)
        if eff is not None and eff.get("pool"):
            return "pool"

    # 3. Área — o motor distribui o dano pela zona (ver _alvos_em_area).
    if hab is not None and area_da_habilidade(hab) and _zonas_ativas():
        return "area_self" if origem_da_area(hab) == "self" else "area"

    # 4. Fonte primária: campo `alcance` (do Open5e via learn_spell/wizard).
    alcance = ((hab or {}).get("alcance") or "").strip().lower()
    if alcance == "self":
        return "self"
    if alcance.startswith("self (") or alcance.startswith("self("):
        # Área saindo do conjurador, mas sem zonas no campo: o motor resolve
        # como alvo único, e é isso que a UI precisa mostrar.
        return "single"
    if alcance in ("", "n/a", "none"):
        # Sem dado de alcance — pode ser feature de classe ou legado.
        # Heurística por nome só para esses casos.
        n = _norm_txt(name)
        if any(k in n for k in ("sleep", "sono", "color spray")):
            return "pool"

    # Default: alvo único (Touch, X feet, …).
    return "single"


def _reset_turn_economy(cs: dict) -> None:
    """
    Início do turno de um combatente: zera Ação/Bônus e roda o que a regra
    manda acontecer "no início do seu turno" — recarga de poderes e recomposição
    das ações lendárias.

    É o único ponto por onde os três avanços de turno passam (next_turn,
    _auto_advance_turn e a auto-cura do ponteiro), e nos três o
    current_turn_index já está no combatente novo quando chega aqui.
    """
    if not isinstance(cs, dict):
        return
    cs["turn_economy"] = {"acao_usada": False, "bonus_usada": False,
                          "movimento_usado": False}
    _inicio_de_turno(cs)
    _ordem = cs.get("initiative_order") or []
    _i = cs.get("current_turn_index", 0)
    if isinstance(_i, int) and 0 <= _i < len(_ordem):
        _quem = memory.campaign.get("characters", {}).get(memory.char_key(_ordem[_i]))
        _extra = sum(int(e.get("movimento_por_turno", 0) or 0) for e in _efeitos_de(_quem))
        if _extra:
            cs["turn_economy"]["movimento_extra"] = _extra


def _inicio_de_turno(cs: dict) -> None:
    """Efeitos de 'no início do seu turno' do combatente da vez."""
    order = cs.get("initiative_order") or []
    idx   = cs.get("current_turn_index", 0)
    if not (isinstance(idx, int) and 0 <= idx < len(order)):
        return
    ch = memory.campaign.get("characters", {}).get(memory.char_key(order[idx]))
    if not ch:
        return
    # A Esquiva, o Ataque Imprudente e o Raio Guia duram "até o seu próximo
    # turno": acabam aqui, quando ele começa. O Etéreo do Piscar também.
    _expirar_efeitos(memory.char_key(order[idx]), "inicio")
    _expirar_efeitos(memory.char_key(order[idx]), "inicio", qual="condicoes")
    from rpg import manobras as _manobras
    _manobras.expirar_preparadas(order[idx])
    _rolar_recargas(ch)
    _repor_lendarias(ch)
    # Ações de covil: na virada de rodada (contagem 20), antes de quem começa.
    _covil = _acoes_de_covil(cs, idx) if cs.get("is_active") else []
    cs["_lendarias_msg"] = _covil + _gastar_lendarias_dos_chefes(order[idx])
    queimou = _queimar_no_inicio_do_turno(ch)
    if queimou:
        cs["_lendarias_msg"] = list(cs.get("_lendarias_msg") or []) + queimou


def _gastar_lendarias_dos_chefes(quem_comeca: str) -> list[str]:
    """
    Chefes inimigos gastam UMA ação lendária na virada de turno.

    Sem isto, ação lendária só existiria se a LLM lembrasse de chamá-la — e no
    modo tela, onde a luta corre sem LLM, nunca seria usada. Uma por virada é
    também como um mestre humano joga: espalha as três pela rodada em vez de
    despejar tudo de uma vez.

    Só NPCs. Um personagem lendário do GRUPO continua sendo jogado pelo
    jogador — o motor não decide por ele.
    """
    cs    = memory.campaign.get("combat_state") or {}
    chars = memory.campaign.get("characters", {})
    avisos = []

    for nome in cs.get("initiative_order", []) or []:
        if memory.char_key(nome) == memory.char_key(quem_comeca):
            continue                      # nunca no próprio turno
        chefe = chars.get(memory.char_key(nome))
        if not chefe or memory.luta_com_o_grupo(chefe):
            continue
        lend = (chefe.get("sheet") or {}).get("lendarias")
        if not isinstance(lend, dict) or not lend.get("opcoes"):
            continue
        if int(lend.get("restantes", 0) or 0) <= 0:
            continue
        if (chefe.get("status", "vivo") or "").lower() in OUT_OF_COMBAT_STATUSES:
            continue
        if int((chefe.get("sheet") or {}).get("vida_atual", 0) or 0) <= 0:
            continue

        # A opção mais cara que ainda cabe no saldo — é a mais forte.
        cabem = [o for o in lend["opcoes"]
                 if int(o.get("custo", 1) or 1) <= int(lend["restantes"])]
        if not cabem:
            continue
        escolha = max(cabem, key=lambda o: int(o.get("custo", 1) or 1))

        alvo = _alvo_de_lendaria(chefe)
        saida = legendary_action(chefe.get("name", nome), escolha["nome"], alvo)
        if not saida.startswith(("Erro:", "Aviso:")):
            avisos.append(saida)
    return avisos


def _alvo_de_lendaria(chefe: dict) -> str:
    """Adversário consciente com menos PV — o alvo que um chefe escolheria."""
    cs    = memory.campaign.get("combat_state") or {}
    chars = memory.campaign.get("characters", {})
    lado  = memory.luta_com_o_grupo(chefe)
    melhor, menos = "", None
    for nome in cs.get("initiative_order", []) or []:
        outro = chars.get(memory.char_key(nome))
        if not outro or memory.luta_com_o_grupo(outro) == lado:
            continue
        if (outro.get("status", "vivo") or "").lower() in OUT_OF_COMBAT_STATUSES:
            continue
        hp = int((outro.get("sheet") or {}).get("vida_atual", 0) or 0)
        if hp <= 0:
            continue
        if menos is None or hp < menos:
            melhor, menos = outro.get("name", nome), hp
    return melhor


# Marcadores de habilidade PASSIVA (não aparecem como botão de ação na tela).
_ABILITY_PASSIVE_NAME_PREFIX = (
    "proficiencia", "proficiência", "idioma", "resistencia a", "resistência a",
    "imunidade", "visao no escuro", "visão no escuro", "sentido", "tamanho",
    "deslocamento", "estilo de combate",
)
_ABILITY_PASSIVE_DESC_MARKERS = (
    "proficiencia de pericia", "proficiência de perícia",
    "concedida pelo antecedente", "proficiência concedida",
    "habilidade de classe —", "habilidade de classe -",
    "passiv",  # "passiva", "passivo"
)


def _norm_txt(t: str) -> str:
    import unicodedata
    t = (t or "").lower().strip()
    return "".join(c for c in unicodedata.normalize("NFD", t)
                   if unicodedata.category(c) != "Mn")


def _ability_is_passive(hab: dict) -> bool:
    """
    True quando a 'habilidade' é passiva/proficiência e NÃO deve virar botão
    de ação na tela tática (ex: 'Proficiência: Atletismo', 'Estilo de Combate').
    Conservador: na dúvida, considera USÁVEL (mantém magias/ataques/curas).
    """
    nome = _norm_txt(hab.get("nome", ""))
    if not nome:
        return True
    for p in _ABILITY_PASSIVE_NAME_PREFIX:
        if nome.startswith(_norm_txt(p)):
            return True
    # Tem efeito ativo claro → usável (dado de dano/cura ou custo de mana).
    if hab.get("dado") or int(hab.get("custo_mana", 0) or 0) > 0:
        return False
    desc = _norm_txt(hab.get("descricao", ""))
    for m in _ABILITY_PASSIVE_DESC_MARKERS:
        if _norm_txt(m) in desc:
            return True
    return False


# ===========================================================================
# ITENS DE COMBATE
# ---------------------------------------------------------------------------
# Antes só a Poção de Cura fazia alguma coisa. Todo o resto que parecia
# consumível pelo nome (ácido, fogo alquímico, antídoto, poção de resistência)
# virava um botão "genérico" que gastava a Ação e a unidade e não aplicava
# efeito nenhum: o item sumia da mochila em silêncio.
#
# Agora cada item tem uma ficha com o efeito do SRD (regras de 2024, as mesmas
# da Poção de Cura como Ação Bônus). O que o motor não conhece continua
# aparecendo na lista, TRAVADO e com o motivo, e é recusado com "Aviso:" antes
# de gastar qualquer coisa: quem resolve é o mestre, pela Ação Livre.
#
#   Poção de Cura            Bônus   em si ou num aliado da MESMA zona
#   Poção de Resistência a X Bônus   em si: resistência a X até o fim do combate
#   Antitoxina / Antídoto    Bônus   em si: vantagem contra Envenenado
#   Frasco de Ácido          Ação    arremesso até a zona vizinha, salvaguarda
#                                    de DES (CD 8 + DES + proficiência) ou 2d6 ácido
#   Fogo Alquímico           Ação    idem, 1d4 fogo e o alvo fica Queimando
#   Água Benta               Ação    idem, 2d8 radiante, só mortos-vivos e infernais
#
# Simplificações assumidas, porque o motor mede duração em combate e não em
# horas: os efeitos de 1 hora (resistência, antitoxina) acabam com o combate;
# quem está Queimando toma 1d4 de fogo no início de cada turno e faz sozinho
# o teste de DES CD 10 para apagar (no livro, isso gasta a Ação dele).
# ===========================================================================

# Itens que claramente NÃO são consumíveis (filtro contra falso positivo).
_NON_CONSUMABLE_KEYWORDS = (
    "espada", "arco", "besta", "adaga", "lança", "lanca", "machado",
    "armadura", "escudo", "capa", "amuleto", "anel", "elmo", "bota",
    "luva", "gibão", "gibao", "cota", "calça", "calca", "túnica", "tunica",
    "manopla", "virote", "flecha", "munição", "municao", "tocha", "corda",
    "pacote", "saco", "mochila",
)
# Palavras que fazem um item PARECER consumível de combate. Os que não têm
# ficha abaixo entram na lista travados, com o motivo.
_CONSUMABLE_KEYWORDS = (
    "poção", "pocao", "potion", "elixir", "frasco", "ampola", "vial",
    "pergaminho", "scroll", "óleo", "oleo",
    "ácido", "acido", "acid", "fogo alquímico", "fogo alquimico", "alchemist",
    "água benta", "agua benta", "holy water", "bomba", "granada", "explosivo",
    "tônico", "tonico", "veneno", "antídoto", "antidoto", "antitoxina",
    "antitoxin", "remédio", "remedio",
)

# Poções de cura (SRD) → (n_dados, faces, bônus).
_HEAL_POTIONS = [
    ("suprema",    (10, 4, 20)),   # 10d4+20
    ("supreme",    (10, 4, 20)),
    ("superior",   (8,  4,  8)),   # 8d4+8
    ("greater",    (4,  4,  4)),   # 4d4+4
    ("maior",      (4,  4,  4)),
]
_HEAL_BASE = (2, 4, 2)             # poção de cura básica → 2d4+2

# Fichas dos itens com efeito, na ordem em que são testadas.
_ITENS_COM_EFEITO = (
    (("fogo alquimico", "alchemist"),
     {"efeito": "arremesso", "slot": "acao", "dado": (1, 4, 0), "tipo_dano": "fire",
      "queimando": True, "rotulo": "1d4 fogo · queimando"}),
    (("agua benta", "holy water"),
     {"efeito": "arremesso", "slot": "acao", "dado": (2, 8, 0), "tipo_dano": "radiant",
      "so_profanos": True, "rotulo": "2d8 radiante · mortos-vivos e infernais"}),
    (("acido", "acid"),
     {"efeito": "arremesso", "slot": "acao", "dado": (2, 6, 0), "tipo_dano": "acid",
      "rotulo": "2d6 ácido"}),
    (("antitoxina", "antidoto", "antitoxin"),
     {"efeito": "antitoxina", "slot": "bonus",
      "rotulo": "vantagem contra envenenado"}),
    # Frasco de óleo aceso: 5 de fogo (SRD), sem dado.
    (("frasco de oleo", "oleo de lamparina", "oil flask", "flask of oil"),
     {"efeito": "arremesso", "slot": "acao", "dado": (0, 1, 5), "tipo_dano": "fire",
      "rotulo": "5 fogo (óleo aceso)"}),
    # Kit de Curandeiro: estabiliza quem está a 0 PV, sem teste (10 usos).
    (("kit de curandeiro", "kit medico", "kit de primeiros socorros", "healer"),
     {"efeito": "estabilizar", "slot": "acao", "usos": 10,
      "rotulo": "estabiliza quem está caído (10 usos)"}),
)

_TIPO_DANO_ITEM_PT = {
    "acid": "ácido", "bludgeoning": "concussão", "cold": "frio", "fire": "fogo",
    "force": "força", "lightning": "elétrico", "necrotic": "necrótico",
    "piercing": "perfurante", "poison": "veneno", "psychic": "psíquico",
    "radiant": "radiante", "slashing": "cortante", "thunder": "trovejante",
}

_MOTIVO_DESCONHECIDO = ("O motor não conhece o efeito deste item. Descreva o uso "
                        "em Ação Livre para o mestre resolver.")


# CD e ataque do pergaminho pelo círculo da magia (SRD, Spell Scroll).
_PERGAMINHO_CD_ATAQUE = {0: (13, 5), 1: (13, 5), 2: (13, 5), 3: (15, 7), 4: (15, 7),
                         5: (17, 9), 6: (17, 9), 7: (18, 10), 8: (18, 10), 9: (19, 11)}
_PERGAMINHO_RE = re.compile(
    r"^\s*(?:pergaminho(?:\s+de\s+magia)?|spell\s+scroll|scroll(?:\s+of)?)\s*"
    r"(?:de|da|do|of|:|-|\()?\s*(.+?)\s*\)?\s*$", re.IGNORECASE)


def _magia_do_pergaminho(nome: str) -> dict | None:
    """'Pergaminho de Bola de Fogo', 'Pergaminho de Magia: Teia' → a magia do compêndio."""
    from rpg import compendio
    m = _PERGAMINHO_RE.match(nome or "")
    if not m or not m.group(1).strip():
        return None
    return compendio.magia(m.group(1).strip())


def _uso_do_item(nome: str) -> dict | None:
    """
    Como o item se usa, do compêndio: poção ({tipo: "pocao"}), varinha ou
    cajado ({tipo: "cargas", magias}), ou pergaminho de magia ({tipo:
    "pergaminho"}, com a CD e o ataque do círculo). None para o resto.
    """
    magico = _magico_por_nome(nome or "")
    if magico and magico.get("uso"):
        return magico["uso"]
    magia = _magia_do_pergaminho(nome)
    if magia:
        cd, ataque = _PERGAMINHO_CD_ATAQUE[int(magia.get("nivel", 0) or 0)]
        return {"tipo": "pergaminho", "cd": cd, "ataque": ataque,
                "magias": [{"magia": magia["nome_srd"], "cargas": 0}],
                "nota": f"Pergaminho de {magia['nome']}: conjura a magia uma vez (CD {cd}, +{ataque}) e se desfaz."}
    return None


def _cargas_do_item(item: dict, uso: dict) -> int:
    """As cargas que restam no item; o item novo vem cheio."""
    if item.get("cargas") is None:
        item["cargas"] = int(uso.get("cargas", 0) or 0)
    return int(item["cargas"])


def _efeito_de_item(item_name: str) -> dict | None:
    """
    Ficha de combate de um item, ou None quando ele não é consumível.

    efeito: "cura" | "resistencia" | "antitoxina" | "arremesso" | "desconhecido"
    slot:   "acao" | "bonus"
    """
    n = _norm_txt(item_name or "")
    if not n:
        return None
    uso = _uso_do_item(item_name)
    if uso and uso.get("tipo") in ("cargas", "pergaminho"):
        # Varinha, cajado, pergaminho: conjuram pelo botão Habilidade da tela.
        return {"efeito": "magia", "slot": "acao", "rotulo": uso.get("nota", ""), "uso": uso}
    if any(kw in n for kw in (_norm_txt(k) for k in _NON_CONSUMABLE_KEYWORDS)):
        return None

    if ("pocao de cura" in n or "potion of healing" in n or "healing potion" in n
            or "pocao de vida" in n):
        dado = next((d for tag, d in _HEAL_POTIONS if _norm_txt(tag) in n), _HEAL_BASE)
        return {"efeito": "cura", "slot": "bonus", "dado": dado,
                "rotulo": f"{dado[0]}d{dado[1]}+{dado[2]} PV"}

    if "bom fruto" in n or "goodberry" in n:
        return {"efeito": "cura", "slot": "acao", "dado": (1, 1, 0), "rotulo": "1 PV"}

    if ("resistencia" in n or "resistance" in n) and ("pocao" in n or "potion" in n):
        tipo = _damage_type_from_text(item_name)
        if not tipo:
            return {"efeito": "desconhecido", "slot": "bonus",
                    "motivo": "O nome não diz a que tipo de dano a poção dá resistência."}
        return {"efeito": "resistencia", "slot": "bonus", "tipo_dano": tipo,
                "rotulo": f"resistência a {_TIPO_DANO_ITEM_PT.get(tipo, tipo)}"}

    for chaves, ficha in _ITENS_COM_EFEITO:
        if any(k in n for k in chaves):
            return dict(ficha)

    if uso and uso.get("tipo") == "pocao":
        return {"efeito": "pocao", "slot": "bonus", "rotulo": uso.get("nota", ""), "uso": uso}
    # Item comum do SRD sem uso no motor (o pergaminho em branco, o frasco
    # vazio) não é consumível de combate.
    if _itens.comum(item_name):
        return None

    if any(kw in n for kw in (_norm_txt(k) for k in _CONSUMABLE_KEYWORDS)):
        return {"efeito": "desconhecido", "slot": "acao", "motivo": _MOTIVO_DESCONHECIDO}
    return None


_PROFANOS = ("undead", "morto-vivo", "morto vivo", "mortos-vivos", "fiend", "infernal",
             "demon", "demonio", "devil", "diabo", "zombie", "zumbi", "skeleton",
             "esqueleto", "ghoul", "carnical", "vampir", "wight", "wraith", "espectro",
             "specter", "ghost", "fantasma", "lich", "mummy", "mumia", "imp", "diabrete")


def _e_profano(ch: dict) -> bool:
    """Morto-vivo ou infernal: o que a Água Benta fere."""
    s = ch.get("sheet") or {}
    texto = _norm_txt(" ".join(str(x or "") for x in (
        s.get("tipo"), s.get("raca"), ch.get("description"), ch.get("name"))))
    return any(_norm_txt(p) in texto for p in _PROFANOS)


_FALHA_AUTOMATICA_EM_DES = ("paralisado", "atordoado", "inconsciente", "petrificado")


def _salvaguarda_de_destreza(alvo: dict, cd: int) -> tuple[bool, str]:
    """Salvaguarda de DES do alvo contra um item arremessado."""
    s = alvo.get("sheet") or {}
    conds = {_norm_txt(c.get("nome", "") if isinstance(c, dict) else str(c))
             for c in (s.get("condicoes") or [])}
    status = (alvo.get("status") or "").lower()
    if conds & set(_FALHA_AUTOMATICA_EM_DES) or status in ("inconsciente", "dormindo"):
        return False, f"falha automática na salvaguarda de DES (CD {cd})"
    mod = _modifier(int(s.get("destreza", 10) or 10))
    classe = (s.get("classe") or "").lower()
    if memory.is_party_member(alvo) and "destreza" in CLASS_DATA.get(classe, {}).get("saves", []):
        mod += int(s.get("proficiencia", 2) or 2)
    d20 = random.randint(1, 20)
    total = d20 + mod
    return total >= cd, f"salvaguarda de DES {d20}{mod:+d} = {total} vs CD {cd}"


def _cd_de_arremesso(ator: dict) -> int:
    s = ator.get("sheet") or {}
    prof = int(s.get("proficiencia", _proficiency_bonus(int(s.get("nivel", 1) or 1))) or 2)
    return 8 + _modifier(int(s.get("destreza", 10) or 10)) + prof


def _estabilizar_com_kit(quem: dict, caido: dict, kit: dict, ficha: dict) -> str:
    """O Kit de Curandeiro estabiliza sem teste e gasta um dos 10 usos."""
    s = caido["sheet"]
    caido["status"] = "estabilizado"
    s["death_saves_sucessos"] = 0
    s["death_saves_falhas"] = 0
    if kit.get("usos") is None:
        kit["usos"] = int(ficha.get("usos", 10) or 10) * int(kit.get("qtd", 1) or 1)
    kit["usos"] = int(kit["usos"]) - 1
    resto = kit["usos"]
    if resto <= 0:
        inv = quem.get("inventario") or []
        if kit in inv:
            inv.remove(kit)
    return (f"{quem['name']} usa {kit['nome']} em {caido['name']}: estabilizado, sem teste"
            + (f" (restam {resto} usos)." if resto > 0 else " (o kit acabou)."))


def _beber_pocao(dono: dict, nome: str, uso: dict) -> str:
    """
    Aplica uma poção do SRD em quem bebe. Dentro da luta, a de um minuto vale
    até o fim dela; as de uma hora correm no relógio. Devolve o texto.
    """
    s = dono["sheet"]
    prazo = ({"ate": "fim_do_combate"} if uso.get("duracao") == "1min"
             else {"ate_hora": _agora_em_horas() + 1})
    partes = []
    efeito = dict(uso.get("efeito") or {})
    if uso.get("atributo"):
        efeito["atributo"] = dict(uso["atributo"])
    if efeito:
        _dar_efeito(s, {"nome": nome, "origem": nome, **efeito, **prazo})
    if uso.get("pv_temp"):
        s["vida_temp"] = max(int(s.get("vida_temp", 0) or 0), int(uso["pv_temp"]))
        partes.append(f"{int(uso['pv_temp'])} PV temporários")
    for cond in uso.get("tira") or []:
        antes = len(s.get("condicoes") or [])
        s["condicoes"] = [c for c in s.get("condicoes") or []
                          if _norm_txt(c.get("nome", "") if isinstance(c, dict) else str(c)) != _norm_txt(cond)]
        if len(s["condicoes"]) != antes:
            partes.append(f"deixa de estar {cond}")
    if uso.get("condicao"):
        conds = s.setdefault("condicoes", [])
        if not any(_norm_txt(c.get("nome", "")) == _norm_txt(uso["condicao"]) for c in conds if isinstance(c, dict)):
            conds.append({"nome": uso["condicao"], "duracao": None, "magia": nome})
    if uso.get("dano"):
        d = uso["dano"]
        n_d, faces, bonus = _parse_dice(d["dado"])
        bruto = sum(random.randint(1, faces) for _ in range(n_d)) + bonus
        res = _apply_damage(dono, bruto, d.get("tipo", ""), source_name=nome, arma_magica=True)
        partes.append(f"{res['dano']} de dano ({_TIPO_DANO_ITEM_PT.get(d.get('tipo', ''), d.get('tipo', ''))})")
        if d.get("condicao") and res["hp_depois"] > 0:
            passou, linha = _rolar_salvaguarda(dono, d.get("salvaguarda", "constituicao"), int(d.get("cd", 10)))
            if not passou:
                s.setdefault("condicoes", []).append({"nome": d["condicao"], "duracao": None})
            partes.append(f"{linha}: {'resiste' if passou else d['condicao']}")
    if uso.get("atributo"):
        _recalculate_ca(dono)
    return (f"{dono['name']} bebeu {nome}: {uso.get('nota', '')}"
            + (f" ({'; '.join(partes)})" if partes else ""))


def _alcance_de_item(ator_nome: str, alvo: dict, ficha: dict) -> str:
    """
    "ok" | "fora" | "sem_efeito" para usar o item de `ator_nome` em `alvo`.
    Poção num aliado: mesma zona. Arremesso: a própria zona ou a vizinha
    (6 metros). Sem zonas em jogo, tudo alcança.
    """
    nome = alvo.get("name", "")
    if ficha.get("so_profanos") and not _e_profano(alvo):
        return "sem_efeito"
    if memory.char_key(nome) == memory.char_key(ator_nome):
        return "ok"
    dist = _distancia(ator_nome, nome)
    if dist is None:
        return "ok"
    limite = 0 if ficha["efeito"] in ("cura", "estabilizar") else 1
    return "ok" if dist <= limite else "fora"


def _alvos_de_item(ator_nome: str, ficha: dict) -> dict:
    """Quem cada item alcança, para a tela não oferecer o alvo que o motor recusa."""
    if ficha["efeito"] not in ("cura", "arremesso", "estabilizar"):
        return {}
    cs = memory.campaign.get("combat_state") or {}
    chars = memory.campaign.get("characters", {})
    saida = {}
    for nm in cs.get("initiative_order", []) or []:
        ch = chars.get(memory.char_key(nm))
        if not ch or not ch.get("sheet"):
            continue
        status = (ch.get("status") or "").lower()
        if status in ("morto", "fugiu"):
            continue
        eu = memory.char_key(nm) == memory.char_key(ator_nome)
        if ficha["efeito"] in ("cura", "estabilizar") and not memory.luta_com_o_grupo(ch):
            continue
        if ficha["efeito"] == "arremesso" and eu:
            continue
        saida[ch.get("name", nm)] = _alcance_de_item(ator_nome, ch, ficha)
    return saida


# ── Efeitos temporários (resistência de poção, antitoxina) ─────────────────

def _efeitos(sheet: dict) -> list[dict]:
    """
    Efeitos ativos. Os de combate valem até end_combat; os bebidos fora dele
    têm prazo no relógio do mundo (`ate_hora`) e somem quando a hora passa.

    Efeito de magia de concentração (`concentracao_de` + `magia`) só vale
    enquanto quem conjurou continua concentrado NELA: a Bênção cai sozinha
    quando o clérigo perde a concentração ou conjura outra magia que exige
    concentração. Não precisa de gancho em cada lugar onde a concentração cai.
    """
    agora = None
    ativos = []
    for e in (sheet.get("efeitos") or []):
        if not isinstance(e, dict):
            continue
        if e.get("ate_hora") is not None:
            agora = _agora_em_horas() if agora is None else agora
            if int(e["ate_hora"]) <= agora:
                continue
        if e.get("concentracao_de") and not _concentracao_segue(e):
            continue
        ativos.append(e)
    # Anel de Proteção, Manto Élfico: o que os itens vestidos dão.
    ativos.extend(_efeitos_dos_itens(sheet))
    return ativos


# ===========================================================================
# EFEITOS DE COMBATE
# ---------------------------------------------------------------------------
# Bênção, Escudo da Fé, Marca do Caçador, Fúria, Esquiva: até aqui o motor
# rolava o dado da magia, escrevia "sem mudança na vida" e nada mais
# acontecia — o +1d4 da Bênção nunca entrava num ataque, a Esquiva não impunha
# desvantagem a ninguém. Agora cada um vira um efeito na ficha, e os pontos que
# decidem a luta (o ataque, a CA, o dano, a salvaguarda) o consultam.
#
# Campos de um efeito (todos opcionais, além de "nome"):
#   atk_dado "1d4"/"-1d4"     somado a cada ataque de quem tem o efeito
#   atk_fixo  10              somado ao próximo ataque (Guiar Ataque)
#   save_dado "1d4"/"-1d4"    somado a cada salvaguarda
#   teste_dado "1d4"          somado ao próximo teste de atributo
#   ca 2 / ca_minima 16       CA de quem tem o efeito
#   dano_dado "1d6", dano_tipo, contra   dano extra nos ataques (contra = só
#                                        no alvo marcado: Marca do Caçador)
#   dano_fixo_for 2           dano extra em ataque corpo a corpo de FOR (Fúria)
#   vantagem_ataque / vantagem_ataque_for / desvantagem_ataque
#   vantagem_contra_mim / desvantagem_contra_mim   ataques CONTRA quem tem
#   resistencias [tipos]      resistência enquanto durar
#   usos 1                    acaba depois de consumido N vezes
#   ate "fim_do_combate"      limpo por end_combat
#   ate_turno_de chave        acaba no INÍCIO do próximo turno de `chave`
#   ate_fim_turno_de chave    acaba no FIM do próximo turno de `chave`
#   concentracao_de chave + magia   cai com a concentração de quem conjurou
# ===========================================================================

def _concentracao_segue(e: dict) -> bool:
    """O conjurador do efeito ainda está concentrado nesta magia?"""
    conj = memory.campaign.get("characters", {}).get(e.get("concentracao_de") or "")
    if not conj:
        return False
    atual = ((conj.get("sheet") or {}).get("concentracao") or {})
    return _norm_txt(atual.get("magia", "")) == _norm_txt(e.get("magia", ""))


def _efeitos_de(char: dict | None) -> list[dict]:
    return _efeitos((char or {}).get("sheet") or {}) if char else []


def dar_efeito_de_combate(char: dict, efeito: dict) -> None:
    """Grava um efeito de combate; o mesmo nome de novo só renova."""
    efeito = dict(efeito)
    efeito.setdefault("ate", "fim_do_combate")
    _dar_efeito(char.setdefault("sheet", {}), efeito)


def _rolar_expr(expr) -> tuple[int, str]:
    """'1d4' → (3, '1d4=3'); '-1d4' → (-2, '-1d4=-2'); 5 → (5, '5')."""
    if isinstance(expr, (int, float)):
        return int(expr), str(int(expr))
    texto = str(expr or "").strip()
    if not texto:
        return 0, ""
    sinal = -1 if texto.startswith("-") else 1
    corpo = texto.lstrip("+-")
    if "d" not in corpo.lower():
        # Número puro: _parse_dice o leria como 1d6.
        try:
            v = sinal * int(corpo)
        except ValueError:
            return 0, ""
        return v, f"{v:+d}"
    n, faces, bonus = _parse_dice(corpo)
    rolls = [random.randint(1, faces) for _ in range(n)]
    total = sinal * (sum(rolls) + bonus)
    return total, f"{texto}={total:+d}"


def _gastar_efeito(sheet: dict, efeito: dict) -> None:
    """Consome um uso de efeito de usos contados; some no zero."""
    if efeito.get("usos") is None:
        return
    efeito["usos"] = int(efeito["usos"]) - 1
    if efeito["usos"] <= 0:
        sheet["efeitos"] = [e for e in (sheet.get("efeitos") or []) if e is not efeito]


def _expirar_efeitos(chave: str, momento: str, token: int | None = None,
                     qual: str = "efeitos") -> list[str]:
    """
    Tira os efeitos que acabam no início ('inicio') ou no fim ('fim') do turno
    de `chave` — a Esquiva dura até o próximo turno de quem esquivou, a
    Zombaria Viciosa até o fim do próximo turno de quem a sofreu.

    `desde_token`: o efeito nasceu NESTE turno de `chave` e dura até o fim do
    PRÓXIMO (Contra-Encanto, o Atordoado do Ataque Atordoante). O fim deste
    turno não conta; só tira a marca.

    `qual` = "condicoes" faz o mesmo com as condições presas ao turno de
    alguém (o Atordoado do Ataque Atordoante).
    """
    campo = "ate_turno_de" if momento == "inicio" else "ate_fim_turno_de"
    acabaram = []

    def _fica(x) -> bool:
        if not (isinstance(x, dict) and x.get(campo) == chave):
            return True
        if token is not None and x.get("desde_token") == token:
            x.pop("desde_token", None)
            return True
        return False

    for ch in (memory.campaign.get("characters") or {}).values():
        s = (ch or {}).get("sheet") or {}
        for campo_lista in (qual,):
            lista = s.get(campo_lista)
            if not isinstance(lista, list) or not lista:
                continue
            ficam = []
            for e in lista:
                if _fica(e):
                    ficam.append(e)
                else:
                    acabaram.append(f"{e.get('nome', 'efeito')} de {ch.get('name', '')}")
            if len(ficam) != len(lista):
                s[campo_lista] = ficam
    return acabaram


def _ca_efetiva(char: dict) -> int:
    """CA da ficha com os efeitos (Escudo da Fé +2, Pele de Árvore no mínimo 16)."""
    s = (char or {}).get("sheet") or {}
    ca = int(s.get("ca", 10) or 10)
    minima = 0
    for e in _efeitos(s):
        ca += int(e.get("ca", 0) or 0)
        minima = max(minima, int(e.get("ca_minima", 0) or 0))
    return max(ca, minima)


def _mods_de_ataque(atacante: dict, alvo: dict, corpo_for: bool, com_arma: bool = True) -> dict:
    """
    O que os efeitos fazem com UM ataque de `atacante` em `alvo`:
    {vantagem, desvantagem, bonus, notas, gastar}. `gastar` são os efeitos de
    uso único que este ataque consome — só depois de rolar.
    """
    r = {"vantagem": False, "desvantagem": False, "bonus": 0, "notas": [], "gastar": []}
    sa = (atacante or {}).get("sheet") or {}
    for e in _efeitos(sa):
        nome = e.get("nome", "efeito")
        if e.get("so_arma") and not com_arma:
            continue
        if e.get("provocado_por") and e["provocado_por"] != memory.char_key((alvo or {}).get("name", "")):
            r["desvantagem"] = True
            r["notas"].append(f"{nome}: desvantagem")
        if e.get("atk_dado"):
            v, txt = _rolar_expr(e["atk_dado"])
            r["bonus"] += v
            r["notas"].append(f"{nome}: {txt}")
            # Inspiração de Bardo: um dado só, no primeiro uso que aparecer.
            if e.get("usos") is not None:
                r["gastar"].append((sa, e))
        if e.get("atk_fixo"):
            r["bonus"] += int(e["atk_fixo"])
            r["notas"].append(f"{nome}: {int(e['atk_fixo']):+d}")
            r["gastar"].append((sa, e))
        # Arma Sagrada: bônus que fica, não se gasta.
        if e.get("atk_bonus"):
            r["bonus"] += int(e["atk_bonus"])
            r["notas"].append(f"{nome}: {int(e['atk_bonus']):+d}")
        # Voto de Inimizade, Golpe Certeiro: vantagem só contra o alvo marcado.
        if e.get("contra") and e["contra"] != memory.char_key((alvo or {}).get("name", "")):
            if e.get("vantagem_ataque"):
                continue
        if e.get("vantagem_ataque") or (e.get("vantagem_ataque_for") and corpo_for):
            r["vantagem"] = True
            r["notas"].append(f"{nome}: vantagem")
            if e.get("vantagem_ataque") and e.get("usos") is not None:
                r["gastar"].append((sa, e))
        if e.get("desvantagem_ataque"):
            r["desvantagem"] = True
            r["notas"].append(f"{nome}: desvantagem")
            if e.get("usos") is not None:
                r["gastar"].append((sa, e))
    st = (alvo or {}).get("sheet") or {}
    for e in _efeitos(st):
        nome = e.get("nome", "efeito")
        if e.get("vantagem_contra_mim"):
            r["vantagem"] = True
            r["notas"].append(f"{nome} em {alvo.get('name', '')}: vantagem")
            if e.get("usos") is not None:
                r["gastar"].append((st, e))
        if e.get("desvantagem_contra_mim"):
            r["desvantagem"] = True
            r["notas"].append(f"{nome} em {alvo.get('name', '')}: desvantagem")
        if e.get("desvantagem_de_extraplanares"):
            from rpg import resolucao
            if resolucao._e_do_tipo(atacante or {}, resolucao._EXTRAPLANARES):
                r["desvantagem"] = True
                r["notas"].append(f"{nome} em {alvo.get('name', '')}: desvantagem")
    return r


def _dano_de_efeitos(atacante: dict, alvo: dict, corpo_for: bool, critico: bool) -> list[dict]:
    """
    Dano extra que os efeitos somam a um golpe que ACERTOU: [{valor, tipo,
    texto}]. Dados extras dobram no crítico, como todo dado de dano.
    """
    saida = []
    sa = (atacante or {}).get("sheet") or {}
    alvo_chave = memory.char_key((alvo or {}).get("name", ""))
    for e in _efeitos(sa):
        nome = e.get("nome", "efeito")
        if e.get("dano_dado") and (not e.get("contra") or e["contra"] == alvo_chave):
            sinal = -1 if str(e["dano_dado"]).strip().startswith("-") else 1
            n, faces, bonus = _parse_dice(str(e["dano_dado"]).strip().lstrip("+-"))
            rolls = [random.randint(1, faces) for _ in range(n * (2 if critico else 1))]
            valor = sinal * (sum(rolls) + bonus)
            saida.append({"valor": valor, "tipo": e.get("dano_tipo", ""),
                          "texto": f"{nome}: [{' + '.join(map(str, rolls))}] = {valor:+d}"})
        if e.get("dano_fixo"):
            saida.append({"valor": int(e["dano_fixo"]), "tipo": "",
                          "texto": f"{nome}: {int(e['dano_fixo']):+d}"})
        if e.get("dano_fixo_for") and corpo_for:
            valor = int(e["dano_fixo_for"])
            saida.append({"valor": valor, "tipo": "", "texto": f"{nome}: +{valor}"})
    return saida


def _bonus_de_salvaguarda(alvo: dict) -> tuple[int, str]:
    """Bênção (+1d4), Perdição (-1d4), Resistência (+1d4, uma vez)."""
    s = (alvo or {}).get("sheet") or {}
    total, notas = 0, []
    for e in list(_efeitos(s)):
        if e.get("save_dado"):
            v, txt = _rolar_expr(e["save_dado"])
            total += v
            notas.append(f"{e.get('nome', 'efeito')} {txt}")
            _gastar_efeito(s, e)
        if e.get("save_fixo"):
            total += int(e["save_fixo"])
            notas.append(f"{e.get('nome', 'efeito')} {int(e['save_fixo']):+d}")
    return total, ("; ".join(notas))


def _efeitos_no_teste(char: dict, atributo: str, pericia: str = "") -> tuple[int, bool, list[str]]:
    """
    (bônus, vantagem, notas) dos efeitos num teste de atributo ou perícia:
    Orientação e Inspiração de Bardo (o dado, uma vez), Aprimorar Habilidade
    (vantagem no atributo), Passos sem Pegadas (+10 em Furtividade).

    Antes, _bonus_de_teste existia e ninguém o chamava: a Orientação nunca
    entrou num teste.
    """
    bonus, notas = _bonus_de_teste(char)
    notas = [notas] if notas else []
    vantagem = False
    s = (char or {}).get("sheet") or {}
    for e in _efeitos(s):
        if _norm_txt(atributo) in {_norm_txt(x) for x in e.get("vantagem_teste_atributos") or []}:
            vantagem = True
            notas.append(f"{e.get('nome', 'efeito')}: vantagem")
        if pericia and _norm_txt(pericia) in {_norm_txt(x) for x in e.get("vantagem_pericias") or []}:
            vantagem = True
            notas.append(f"{e.get('nome', 'efeito')}: vantagem")
        extra = (e.get("bonus_pericia") or {}).get(_norm_txt(pericia)) if pericia else None
        if extra:
            bonus += int(extra)
            notas.append(f"{e.get('nome', 'efeito')}: {int(extra):+d}")
    if _norm_txt(pericia) == "atletismo" and _tem_habilidade(char, "atleta notavel"):
        vantagem = True
        notas.append("Atleta Notável: vantagem")
    return bonus, vantagem, notas


def _bonus_de_teste(alvo: dict) -> tuple[int, str]:
    """Orientação: +1d4 no próximo teste de atributo, e acaba."""
    s = (alvo or {}).get("sheet") or {}
    total, notas = 0, []
    for e in list(_efeitos(s)):
        if e.get("teste_dado"):
            v, txt = _rolar_expr(e["teste_dado"])
            total += v
            notas.append(f"{e.get('nome', 'efeito')} {txt}")
            _gastar_efeito(s, e)
    return total, ("; ".join(notas))


# ── Ataque Furtivo ─────────────────────────────────────────────────────────
# O dano que define o ladino não existia no motor: a ficha tinha o texto, o
# ataque rolava só a arma. Agora, uma vez por turno, com arma de acuidade ou à
# distância, e com vantagem OU um aliado de pé ao lado do alvo (sem
# desvantagem), soma 1d6 a cada dois níveis de ladino.
_ARMAS_DE_ACUIDADE = ("adaga", "dagger", "rapieira", "rapier", "espada curta",
                      "shortsword", "cimitarra", "scimitar", "chicote", "whip")


def _tem_ataque_furtivo(char: dict) -> bool:
    nomes = {_norm_txt(h.get("nome", "")) for h in (char.get("habilidades") or [])
             if isinstance(h, dict)}
    return bool(nomes & {"ataque furtivo", "sneak attack"})


def _dados_do_furtivo(char: dict) -> int:
    nivel = int(((char.get("sheet") or {}).get("nivel", 1)) or 1)
    return max(1, (nivel + 1) // 2)


def _aliado_ao_lado_do_alvo(atacante: dict, alvo: dict) -> bool:
    """Um aliado de quem ataca, de pé, na zona do alvo (sem zonas: na luta)."""
    lado = memory.luta_com_o_grupo(atacante)
    zona_alvo = _zona_de(alvo.get("name", "")) if _zonas_ativas() else ""
    cs = memory.campaign.get("combat_state") or {}
    for nm in cs.get("initiative_order") or []:
        ch = memory.campaign["characters"].get(memory.char_key(nm))
        if not ch or ch is atacante or ch is alvo:
            continue
        if memory.luta_com_o_grupo(ch) != lado:
            continue
        if (ch.get("status") or "").lower() in OUT_OF_COMBAT_STATUSES:
            continue
        if not zona_alvo or _zona_de(ch.get("name", "")) == zona_alvo:
            return True
    return False


def _ataque_furtivo(atacante: dict, alvo: dict, arma: str, vantagem: bool,
                    desvantagem: bool, a_distancia: bool) -> tuple[int, str]:
    """Quantos d6 de Ataque Furtivo este golpe ganha (0 = nenhum) e por quê."""
    if not _tem_ataque_furtivo(atacante):
        return 0, ""
    arma_n = _norm_txt(arma or "")
    if not (a_distancia or any(a in arma_n for a in _ARMAS_DE_ACUIDADE)):
        return 0, ""
    sa = atacante.get("sheet") or {}
    cs = memory.campaign.get("combat_state") or {}
    if cs.get("is_active") and sa.get("_furtivo_token") == cs.get("turn_token"):
        return 0, ""
    vale_vantagem = vantagem and not desvantagem
    if vale_vantagem:
        return _dados_do_furtivo(atacante), "com vantagem"
    if not desvantagem and _aliado_ao_lado_do_alvo(atacante, alvo):
        return _dados_do_furtivo(atacante), "com um aliado ao lado do alvo"
    return 0, ""


# ── Artes Marciais ─────────────────────────────────────────────────────────
_ARMAS_DE_MONGE = ("desarmad", "unarmed", "espada curta", "shortsword", "clava", "club",
                   "adaga", "dagger", "azagaia", "javelin", "maca", "mace", "bordao", "cajado",
                   "quarterstaff", "lanca", "spear", "machadinha", "handaxe", "foice curta",
                   "sickle", "martelo leve", "light hammer")


def _artes_marciais_no_golpe(atacante: dict, arma: str, habilidade) -> tuple[str, int] | None:
    """(atributo, dado) das Artes Marciais neste golpe, ou None quando não valem."""
    if habilidade or not _tem_habilidade(atacante, "artes marciais", "martial arts"):
        return None
    s = atacante.get("sheet") or {}
    eq = s.get("equipamentos") or {}
    if eq.get("armadura") or eq.get("escudo"):
        return None
    a = _norm_txt(arma or "")
    if any(r in a for r in RANGED_WEAPONS) and "azagaia" not in a and "javelin" not in a:
        return None
    if not any(m in a for m in _ARMAS_DE_MONGE):
        return None
    from rpg import resolucao
    attr = "destreza" if _modifier(int(s.get("destreza", 10) or 10)) >= _modifier(int(s.get("forca", 10) or 10)) else "forca"
    return attr, resolucao._dado_de_artes_marciais(atacante)


# ── Golpes armados ─────────────────────────────────────────────────────────
# Destruição Divina, Ataque Atordoante, Destruição Marcante: o efeito é
# preparado antes e vale no próximo acerto com arma. O custo (mana, ki) só é
# cobrado quando o golpe acerta — quem erra não perde nada.
def _e_profano(ch: dict) -> bool:
    from rpg import resolucao
    return resolucao._e_do_tipo(ch, resolucao._MORTOS_VIVOS + resolucao._INFERNAIS)


def _golpes_armados(atacante: dict, alvo: dict, a_distancia: bool, habilidade,
                    critico: bool, tipo_arma: str = "") -> tuple[list, list, list, list]:
    """(componentes de dano, linhas, condições a aplicar depois do dano, manobras)."""
    comps, linhas, conds, manobras = [], [], [], []
    if habilidade:
        return comps, linhas, conds, manobras
    sa = atacante.get("sheet") or {}
    for e in list(_efeitos(sa)):
        if not any(e.get(k) for k in ("golpe_dado", "golpe_condicao")):
            continue
        if e.get("golpe_so_corpo") and a_distancia:
            continue
        nome = e.get("nome", "golpe")
        sa["efeitos"] = [x for x in sa.get("efeitos") or [] if x is not e]
        custo = []
        if e.get("golpe_mana"):
            mana = int(sa.get("mana_atual", 0) or 0)
            if mana < int(e["golpe_mana"]):
                linhas.append(f"{nome}: sem mana ({mana}/{e['golpe_mana']}) — não sai.")
                continue
            sa["mana_atual"] = mana - int(e["golpe_mana"])
            custo.append(f"{e['golpe_mana']} mana")
        if e.get("golpe_ki"):
            if (usos_restantes(atacante, "Ki") or 0) < int(e["golpe_ki"]):
                linhas.append(f"{nome}: sem ki — não sai.")
                continue
            _gastar_uso(atacante, "Ki", int(e["golpe_ki"]))
            custo.append(f"{e['golpe_ki']} ki")
        if e.get("golpe_superioridade"):
            if (usos_restantes(atacante, "Dados de Superioridade") or 0) < 1:
                linhas.append(f"{nome}: sem Dado de Superioridade — não sai.")
                continue
            _gastar_uso(atacante, "Dados de Superioridade")
            custo.append("1 Dado de Superioridade")
        if e.get("golpe_dado"):
            n, faces, bonus = _parse_dice(str(e["golpe_dado"]))
            extra = ""
            if e.get("golpe_contra_profanos") and _e_profano(alvo):
                n += 1
                extra = " (+1d8: morto-vivo ou infernal)"
            rolls = [random.randint(1, faces) for _ in range(n * (2 if critico else 1))]
            valor = sum(rolls) + bonus
            comps.append((valor, tipo_arma if e.get("golpe_tipo_da_arma") else e.get("golpe_tipo", "")))
            linhas.append(f"{nome}: {len(rolls)}d{faces} [{' + '.join(map(str, rolls))}] = {valor}"
                          f"{' ' + e['golpe_tipo'] if e.get('golpe_tipo') else ''}{extra}"
                          + (f" — gasta {', '.join(custo)}" if custo else ""))
        elif custo:
            linhas.append(f"{nome}: gasta {', '.join(custo)}")
        if e.get("golpe_condicao"):
            conds.append((nome, e["golpe_condicao"]))
        if e.get("manobra"):
            manobras.append(e)
    return comps, linhas, conds, manobras


def _aplicar_condicao_de_golpe(atacante: dict, alvo: dict, nome: str, cfg: dict) -> str:
    cond_nome = cfg["nome"]
    if _imune_a_condicao(alvo, cond_nome):
        return f"\n   {nome}: {alvo['name']} é imune a {cond_nome}."
    if cfg.get("salvaguarda"):
        passou, linha = _rolar_salvaguarda(alvo, cfg["salvaguarda"], int(cfg.get("cd", 10)),
                                           contra=cond_nome)
        if passou:
            return f"\n   {nome}: {alvo['name']}: {linha} — resistiu."
    else:
        linha = ""
    st = alvo.setdefault("sheet", {})
    st["condicoes"] = [c for c in st.get("condicoes") or []
                       if _norm_txt(c.get("nome", "") if isinstance(c, dict) else str(c)) != _norm_txt(cond_nome)]
    c = {"nome": cond_nome, "duracao": None, "por": atacante.get("name", "")}
    quando = ""
    if cfg.get("ate_fim_do_proximo_turno_de"):
        c["ate_fim_turno_de"] = cfg["ate_fim_do_proximo_turno_de"]
        c["desde_token"] = int((memory.campaign.get("combat_state") or {}).get("turn_token", 0) or 0)
        quando = f" até o fim do próximo turno de {atacante.get('name')}"
    st["condicoes"].append(c)
    _log_combat_event("condition", atacante.get("name", ""), alvo.get("name", ""),
                      msg=f"{alvo.get('name')} ficou {cond_nome} ({nome})")
    return f"\n   {nome}: {alvo['name']}: {linha + ' — ' if linha else ''}**{cond_nome.upper()}**{quando}."


def _marcar_que_atacou(atacante: dict) -> None:
    """
    Quem está na vez atacou: Sacerdote de Guerra e Rajada de Golpes só valem
    depois da ação Atacar. Marca no attack_roll para valer pela tela e pelo
    Mestre (que chama attack_roll direto).
    """
    cs = memory.campaign.get("combat_state") or {}
    ordem = cs.get("initiative_order") or []
    i = cs.get("current_turn_index", 0)
    if (cs.get("is_active") and isinstance(i, int) and 0 <= i < len(ordem)
            and memory.char_key(ordem[i]) == memory.char_key(atacante.get("name", ""))):
        cs.setdefault("turn_economy", {})["atacou"] = True


# ── Magia de ataque e magia de teste ───────────────────────────────────────

def _ataque_da_magia(hab: dict) -> str:
    """'corpo' | 'distancia' | '' — a magia rola ataque mágico?"""
    from rpg import resolucao
    m = resolucao._magia_srd(hab)
    if m is not None:
        return m.get("ataque") or ""
    texto = _norm_txt(hab.get("descricao", ""))
    if any(k in texto for k in ("ataque magico", "ataque de magia", "spell attack")):
        return "corpo" if "corpo a corpo" in texto or "melee" in texto else "distancia"
    return ""


def _metade_se_passar(hab: dict) -> bool:
    """Quem passa no teste leva metade? Truques de teste: nada."""
    from rpg import resolucao
    m = resolucao._magia_srd(hab)
    if m is not None and m.get("salvaguarda"):
        return bool(m.get("metade_se_passar"))
    if "metade" in (hab or {}):                  # o poder do monstro diz
        return bool(hab["metade"])
    return True


def _rolar_ataque_magico(char: dict, alvo: dict, hab: dict) -> tuple[bool, bool, str]:
    """(acertou, crítico, linha) do ataque mágico de `char` em `alvo`."""
    s = char.get("sheet") or {}
    prof = int(s.get("proficiencia", _proficiency_bonus(int(s.get("nivel", 1) or 1))) or 2)
    attr = _atributo_de_conjuracao(s)
    if attr:
        mod = _modifier(int(s.get(attr, 10) or 10))
    else:
        # Monstro ou classe sem conjuração na tabela: o melhor dos três.
        mod = max(_modifier(int(s.get(a, 10) or 10)) for a in ("inteligencia", "sabedoria", "carisma"))
    vantagem = ((_has_condition_effect(char, "attack_advantage") and not (_invisivel(char) and _ve_invisivel(alvo)))
                or _has_condition_effect(alvo, "defense_disadvantage"))
    _cob_n, _cob_b = _cobertura_contra(char, alvo, True)
    desvantagem = (_has_condition_effect(char, "attack_disadvantage")
                   or (_invisivel(alvo) and not _ve_invisivel(char)))
    mods = _mods_de_ataque(char, alvo, False, com_arma=False)
    vantagem = vantagem or mods["vantagem"]
    desvantagem = desvantagem or mods["desvantagem"]
    _cego_por = _zona_obscurecida(char.get("name", "")) or _zona_obscurecida(alvo.get("name", ""))
    if _cego_por:
        vantagem = desvantagem = True
        mods["notas"].append(f"{_cego_por}: vantagem e desvantagem se anulam")
    else:
        if not _ve_no_escuro(char, alvo):
            desvantagem = True
            mods["notas"].append(f"no escuro, {char.get('name')} não vê {alvo.get('name')} — desvantagem")
        if not _ve_no_escuro(alvo, char):
            vantagem = True
            mods["notas"].append(f"no escuro, {alvo.get('name')} não vê {char.get('name')} — vantagem")
    d20, log = _roll_d20_with_adv(vantagem, desvantagem)
    # Pergaminho: o ataque é o do pergaminho (+5 a +11 pelo círculo).
    _do_item = _item_conjurando(s)
    if _do_item and _do_item.get("ataque") is not None:
        prof, mod = 0, int(_do_item["ataque"])
    total = d20 + prof + mod + mods["bonus"]
    ca = _ca_efetiva(alvo) + _cob_b
    if _cob_b:
        mods["notas"].append(f"{alvo.get('name')} tem {_COBERTURA_NOME[_cob_n]}: +{_cob_b} de CA")
    for sh, e in mods["gastar"]:
        _gastar_efeito(sh, e)
    critico = d20 == 20
    acertou = critico or (d20 != 1 and total >= ca)
    efeitos = f" {mods['bonus']:+d}(efeitos)" if mods["bonus"] else ""
    notas = f" [{'; '.join(mods['notas'])}]" if mods["notas"] else ""
    veredito = "CRÍTICO" if critico else ("ACERTO" if acertou else "ERROU")
    return acertou, critico, (f"\n   Ataque mágico: {log} {prof + mod:+d}{efeitos} = **{total}** "
                              f"vs CA {ca}{notas} — {veredito}")


# ── Ataque Extra ───────────────────────────────────────────────────────────
# Guerreiro, bárbaro, paladino, patrulheiro e monge do 5º nível atacam duas
# vezes com a ação Atacar; o guerreiro três no 11º e quatro no 20º. O motor
# não tinha isso: a ficha dizia "Ataque Extra" e o turno acabava no 1º golpe.
def _numero_de_ataques(char: dict) -> int:
    s = (char or {}).get("sheet") or {}
    nomes = {_norm_txt(h.get("nome", "")) for h in ((char or {}).get("habilidades") or [])
             if isinstance(h, dict)}
    classe = _norm_txt(s.get("classe", ""))
    nivel = int(s.get("nivel", 1) or 1)
    n = 1
    if nomes & {"ataque extra", "extra attack"}:
        n = 2
    if nomes & {"ataque extra adicional"}:
        n = 3
    if classe == "guerreiro":
        n = max(n, 4 if nivel >= 20 else 3 if nivel >= 11 else 2 if nivel >= 5 else 1)
    elif classe in ("barbaro", "paladino", "patrulheiro", "monge") and nivel >= 5:
        n = max(n, 2)
    # O Multiataque do bloco: o urso da Forma Selvagem, o elemental invocado.
    if s.get("_forma_selvagem") or isinstance((char or {}).get("invocacao"), dict):
        n = max(n, int(s.get("multiattack", 1) or 1))
    return n


def _dar_efeito(sheet: dict, efeito: dict) -> None:
    """Grava um efeito na ficha; o mesmo efeito de novo só renova."""
    lista = [e for e in _efeitos(sheet) if e.get("nome") != efeito["nome"]]
    lista.append(efeito)
    sheet["efeitos"] = lista


def _tem_antitoxina(sheet: dict) -> bool:
    return any(e.get("antitoxina") for e in _efeitos(sheet))


def _queimar_no_inicio_do_turno(ch: dict) -> list[str]:
    """
    Fogo Alquímico: 1d4 de fogo no início do turno de quem está Queimando,
    e em seguida o teste de DES CD 10 para apagar.
    """
    s = ch.get("sheet") or {}
    conds = s.get("condicoes") or []
    if not any(_norm_txt(c.get("nome", "") if isinstance(c, dict) else str(c)) == "queimando"
               for c in conds):
        return []
    nome = ch.get("name", "")
    _fogo = next((c for c in conds if isinstance(c, dict)
                  and _norm_txt(c.get("nome", "")) == "queimando"), {}) or {}
    _n_f, _faces_f, _b_f = _parse_dice(_fogo.get("dado") or "1d4")
    dano = sum(random.randint(1, _faces_f) for _ in range(_n_f)) + _b_f
    res = _apply_damage(ch, dano, "fire", source_name=_fogo.get("por") or "fogo alquímico")
    linha = (f"{nome} queima: {dano} de fogo"
             f"{' (' + '; '.join(res['notas']) + ')' if res['notas'] else ''} "
             f"• HP {res['hp_antes']}→{res['hp_depois']}")
    apagou = False
    if res["hp_depois"] == 0:
        if res["hp_antes"] > 0:
            linha += _mark_at_zero_hp(ch, "fogo alquímico")
        apagou = True                     # caído, as chamas não contam mais
    else:
        d20 = random.randint(1, 20)
        mod = _modifier(int(s.get("destreza", 10) or 10))
        if d20 + mod >= 10:
            apagou = True
            linha += f" • apagou as chamas (DES {d20}{mod:+d} vs CD 10)"
        else:
            linha += f" • continua em chamas (DES {d20}{mod:+d} vs CD 10)"
    if apagou:
        s["condicoes"] = [c for c in conds
                          if _norm_txt(c.get("nome", "") if isinstance(c, dict) else str(c))
                          != "queimando"]
    _log_combat_event("burning", "", nome, msg=linha, dano=res["dano"], hp=res["hp_depois"])
    return [linha]


_WEAPON_KEYWORDS = (
    "espada", "arco", "besta", "adaga", "lança", "lanca", "machado", "maça",
    "maca", "martelo", "cajado", "bordão", "bordao", "clava", "porrete",
    "rapieira", "florete", "sabre", "cimitarra", "foice", "chicote", "funda",
    "tridente", "alabarda", "azagaia", "dardo", "zarabatana", "varinha",
)


def _combatant_weapons(ch: dict) -> list[dict]:
    """Armas que o combatente pode usar: equipadas + inventário + desarmado."""
    s = ch.get("sheet") or {}
    eq = s.get("equipamentos", {}) or {}
    out, seen = [], set()
    # Na Forma Selvagem, só os ataques da fera; a invocação, os dela.
    if s.get("_forma_selvagem") or (isinstance(ch.get("invocacao"), dict) and s.get("ataques")):
        return [{"nome": a.get("nome", ""), "origem": (s.get("_forma_selvagem") or {}).get("forma", "fera")}
                for a in (s.get("ataques") or []) if isinstance(a, dict) and a.get("nome")]

    def _add(nm, origem):
        n = (nm or "").strip()
        k = n.lower()
        if not n or k in seen:
            return
        seen.add(k)
        out.append({"nome": n, "origem": origem})

    _add(eq.get("arma_principal"), "equipada")
    _add(eq.get("arma_secundaria"), "equipada")
    for it in (ch.get("inventario") or []):
        if not isinstance(it, dict):
            continue
        inm = (it.get("nome") or "")
        if _itens.arma(inm) or any(kw in inm.lower() for kw in _WEAPON_KEYWORDS):
            _add(inm, "inventário")
    _add("Ataque desarmado", "desarmado")
    return out


def _cartao_de_habilidade(h: dict, ch: dict, r: dict) -> dict:
    """O cartão de uma habilidade na tela tática (r: habilidade.resolver)."""
    from rpg import resolucao as _resolucao_snap
    return {
        # `nome` é o da FICHA: é por ele que use_ability procura. O que a
        # tela mostra é `nome_exibido`, o nome oficial em português.
        "nome":         h.get("nome", ""),
        "nome_exibido": r["nome"],
        "custo_mana":   int(h.get("custo_mana", 0) or 0),
        "dado":         r["dado"],
        "descricao":    r["descricao"],
        "resumo":       r["resumo"],
        "efeito":       r["efeito"],
        "rotulo":       r["rotulo"],
        "tipo_dano":    r["tipo_dano"],
        "salvaguarda":  r["salvaguarda"],
        "area":         r["area"],
        "alvos":        r["alvos"],
        "alcance":      r["alcance"],
        "concentracao": r["concentracao"],
        "reacao":       r["acao"] == "reacao",
        # "acao" | "bonus" | "livre" (Guiar Ataque, Ataque Imprudente).
        "tipo_acao":    (_slot_da_habilidade(h.get("nome", ""), h, ch) or "livre"),
        # O que acontece ao usar: motor | efeito | acao_de_classe |
        # narrativa (o Mestre decide). O cartão mostra o texto.
        "resolucao":    r["resolucao"],
        "resolucao_texto": r["resolucao_texto"],
        "modos":        r["modos"],
        "alvo_modo":    r["alvo_modo"],
        "exige_ataque": r["exige_ataque"],
        # Modo de alvo: "self" | "pool" | "single". A UI usa para decidir
        # se mostra o picker ou despacha direto (self/pool não pedem alvo).
        "target_mode": _ability_target_mode(h.get("nome", ""), h),
        # Vários alvos: por círculo (Imobilizar Pessoa, Mísseis Mágicos) e,
        # sem zonas, pelo tamanho da área (Bola de Fogo: 4).
        "alvos_por_modo": _resolucao_snap.alvos_por_modo(h, ch),
        # Mísseis Mágicos, Raio Ardente: cada toque no alvo é um dardo.
        "projeteis": bool(_resolucao_snap.projeteis(h)),
        "max_alvos": (max_alvos_da_area(h) if r["area"] and not _zonas_ativas() else 1),
        # Usos por descanso (Surto de Ação, Fúria…). None quando a
        # habilidade é livre — a tela não desenha contador nesse caso.
        "usos":     usos_restantes(ch, h.get("nome", "")),
        "usos_max": usos_maximos(ch, h.get("nome", "")),
    }


def _magias_de_itens(ch: dict) -> list[dict]:
    """
    As magias que os itens do personagem conjuram (pergaminho, varinha,
    cajado), como cartões de habilidade. O nome é "Magia [Item]": é por ele
    que combat_action manda a conjuração para o item, que paga com cargas ou
    se desfaz. Os círculos acima são as cargas a mais.
    """
    from rpg import compendio, habilidade as _habilidade
    saida = []
    s = ch.get("sheet") or {}
    for it in ch.get("inventario") or []:
        if not isinstance(it, dict) or int(it.get("qtd", 1) or 1) <= 0:
            continue
        uso = _uso_do_item(it.get("nome", ""))
        if not uso or uso.get("tipo") not in ("cargas", "pergaminho"):
            continue
        magico = _magico_por_nome(it["nome"])
        if magico and magico.get("sintonizacao") and not _esta_sintonizado(s, it["nome"]):
            continue
        restam = _cargas_do_item(it, uso) if uso["tipo"] == "cargas" else int(it.get("qtd", 1) or 1)
        for entrada in uso.get("magias") or []:
            m = compendio.magia(entrada["magia"])
            if not m:
                continue
            h = {"nome": m["nome"], "descricao": m.get("resumo", ""), "custo_mana": 0, "dado": ""}
            r = _habilidade.resolver(h, ch)
            if r["passiva"] or r["resolucao"] == "narrativa":
                continue                   # Detectar Magia: o Mestre narra (use_magic_item)
            cartao_i = _cartao_de_habilidade(h, ch, r)
            circulos = _circulos_do_item(m, entrada, uso, restam)
            if not circulos:
                continue
            cartao_i.update({
                "nome": f"{m['nome']} [{it['nome']}]",
                "nome_exibido": f"{m['nome']} ({it['nome']})",
                "custo_mana": 0, "tipo_acao": "acao", "de_item": it["nome"],
                "usos": restam, "usos_max": (int(uso.get("cargas", 0) or 0) if uso["tipo"] == "cargas" else None),
                "modos": ([{"id": f"c{c}", "texto": f"{c}º círculo: {k} carga{'s' if k > 1 else ''}", "alvo": ""}
                           for c, k in circulos] if len(circulos) > 1 else []),
                "alvos_por_modo": _alvos_por_circulo_do_item(h, [c for c, _k in circulos]),
            })
            saida.append(cartao_i)
    return saida


def _circulos_do_item(m: dict, entrada: dict, uso: dict, restam: int) -> list[tuple[int, int]]:
    """(círculo, cargas) que o item consegue agora. Pergaminho: o círculo da magia."""
    base = int(m.get("nivel", 0) or 0)
    if uso.get("tipo") != "cargas":
        return [(base, 0)]
    custo = int(entrada.get("cargas", 1) or 1)
    if not entrada.get("extra"):
        return [(base, custo)] if custo <= restam else []
    teto = min(9, int(entrada.get("max_circulo", 9) or 9))
    return [(c, custo + c - base) for c in range(base, teto + 1) if custo + c - base <= restam]


def _alvos_por_circulo_do_item(h: dict, circulos: list[int]) -> dict:
    from rpg import resolucao as _r
    m = _r._magia_srd(h) or {}
    if not m or not (m.get("alvos_por_espaco") or _r.projeteis(h)):
        return {}
    if not _r.projeteis(h) and (_get_control_effect(h) or {}).get("pool", True):
        return {}
    saida = {f"c{c}": _r.alvos_no_circulo(h, c) for c in circulos}
    return saida if any(v > 1 for v in saida.values()) else {}


_MAGIA_DE_ITEM_RE = re.compile(r"^(.+?)\s*\[(.+)\]\s*$")


def _magia_de_item_no_nome(nome: str) -> tuple[str, str] | None:
    """"Bola de Fogo [Varinha de Bolas de Fogo]" → ("Bola de Fogo", "Varinha de Bolas de Fogo")."""
    m = _MAGIA_DE_ITEM_RE.match(nome or "")
    return (m.group(1).strip(), m.group(2).strip()) if m else None


def _ler_pergaminho(char: dict, m: dict) -> tuple[str, str]:
    """
    (recusa, nota do teste) para ler um pergaminho de magia. No 5e, só lê
    quem tem a magia na lista da classe (ou o ladino com Uso Mágico de
    Itens); magia acima do círculo que se alcança pede um teste de
    Arcanismo, CD 10 + círculo, e na falha o pergaminho se desfaz à toa.
    """
    from rpg import compendio
    s = char.get("sheet") or {}
    if _char_has_feature(char, "Uso Mágico de Itens"):
        return "", ""
    classe = _norm_txt(s.get("classe", ""))
    na_lista = any(x.get("nome_srd") == m.get("nome_srd")
                   for x in compendio.magias_da_classe(classe, 9))
    if not na_lista or not _atributo_de_conjuracao(s):
        return (f"Erro: {m['nome']} não está na lista de magias de {s.get('classe') or 'quem não conjura'}: "
                f"{char.get('name')} não consegue ler o pergaminho. Nada foi gasto."), ""
    nivel = int(m.get("nivel", 0) or 0)
    if nivel <= _nivel_maximo_de_magia(s):
        return "", ""
    cd = 10 + nivel
    attr = _atributo_de_conjuracao(s)
    bonus = _modifier(int(s.get(attr, 10) or 10))
    if _proficiente_na_pericia(s, "arcanismo") or _proficiente_na_pericia(s, "arcana"):
        bonus += int(s.get("proficiencia", 2) or 2)
    d20 = random.randint(1, 20)
    total = d20 + bonus
    linha = f"teste de Arcanismo para ler acima do círculo: {d20}{bonus:+d} = {total} vs CD {cd}"
    if total < cd:
        return f"FALHOU: {linha}", linha
    return "", linha


def _conjurar_do_item(actor: str, item_nome: str, magia_nome: str, target: str = "",
                      modo: str = "", end_turn: bool = False) -> str:
    """
    Conjura uma magia de um item: varinha e cajado gastam cargas (as a mais
    sobem o círculo), o pergaminho se desfaz. A CD e o ataque são os do item
    quando ele tem; quem conjura é o personagem, pelo mesmo use_ability.
    """
    from rpg import compendio, resolucao as _resolucao_i
    char, err = _get_char(actor)
    if not char:
        return err
    s = char["sheet"]
    item = _item_do_inventario(char, item_nome)
    if not item or int(item.get("qtd", 1) or 1) <= 0:
        return f"Erro: {char['name']} não tem '{item_nome}'."
    uso = _uso_do_item(item["nome"])
    if not uso or uso.get("tipo") not in ("cargas", "pergaminho"):
        return f"Aviso: {item['nome']} não conjura magia."
    magico = _magico_por_nome(item["nome"])
    if magico and magico.get("sintonizacao") and not _esta_sintonizado(s, item["nome"]):
        return f"Erro: {item['nome']} só funciona sintonizado (attune_item). Nada foi gasto."
    m = compendio.magia(magia_nome)
    entrada = next((e for e in uso.get("magias") or []
                    if m and (compendio.magia(e["magia"]) or {}).get("nome_srd") == m.get("nome_srd")), None)
    if not m or not entrada:
        opcoes = ", ".join((compendio.magia(e["magia"]) or {}).get("nome", e["magia"])
                           for e in uso.get("magias") or [])
        return f"Erro: {item['nome']} não conjura '{magia_nome}'. Conjura: {opcoes}."
    base = int(m.get("nivel", 0) or 0)
    circulo = _resolucao_i.circulo_do_modo({}, modo) or base
    nota_teste = ""
    if uso["tipo"] == "cargas":
        restam = _cargas_do_item(item, uso)
        possiveis = dict(_circulos_do_item(m, entrada, uso, 10 ** 6))
        if circulo not in possiveis:
            return f"Aviso: {item['nome']} não conjura {m['nome']} no {circulo}º círculo. Nada foi gasto."
        custo = possiveis[circulo]
        if custo > restam:
            return (f"Aviso: {item['nome']} tem {restam} carga{'s' if restam != 1 else ''}; "
                    f"{m['nome']} no {circulo}º círculo pede {custo}. Nada foi gasto.")
    else:
        circulo, custo = base, 0
        recusa, nota_teste = _ler_pergaminho(char, m)
        if recusa.startswith("Erro:"):
            return recusa
        if recusa.startswith("FALHOU"):
            _gastar_unidade(char, item)
            memory.save_campaign()
            return (f"{char['name']} tenta ler {item['nome']}: {nota_teste}. As palavras se "
                    f"embaralham e o pergaminho se desfaz sem efeito.")

    ja_tinha = any(isinstance(h, dict) and _norm_txt(h.get("nome", "")) == _norm_txt(m["nome"])
                   for h in char.get("habilidades") or [])
    temp = {"nome": m["nome"], "descricao": m.get("resumo", ""), "custo_mana": 0, "dado": "", "_do_item": True}
    if not ja_tinha:
        char.setdefault("habilidades", []).append(temp)
    try:
        with _conjurando_pelo_item(s, uso.get("cd"), uso.get("ataque")):
            msg = use_ability(char["name"], m["nome"], target, end_turn=end_turn, _skip_turn_check=True,
                              modo=(f"c{circulo}" if circulo > base else ""), _sem_custo=True)
    finally:
        if not ja_tinha:
            char["habilidades"] = [h for h in char.get("habilidades") or [] if h is not temp]
    if msg.lstrip().startswith(("Erro:", "Aviso:")):
        return msg
    if uso["tipo"] == "cargas":
        item["cargas"] = _cargas_do_item(item, uso) - custo
        nota = f"\n   {item['nome']}: {item['cargas']}/{uso.get('cargas')} cargas."
        # A última carga: num 1 no d20, a varinha se desfaz (SRD).
        if item["cargas"] <= 0 and random.randint(1, 20) == 1:
            _gastar_unidade(char, item)
            nota = f"\n   A última carga de {item['nome']} se foi, e o item se desfaz em pó."
    else:
        _gastar_unidade(char, item)
        nota = f"\n   O pergaminho se desfaz." + (f" ({nota_teste})" if nota_teste else "")
    memory.save_campaign()
    return f"{char['name']} usa {item['nome']}.\n" + msg + nota


def _gastar_unidade(char: dict, item: dict) -> None:
    item["qtd"] = int(item.get("qtd", 1) or 1) - 1
    if item["qtd"] <= 0:
        inv = char.get("inventario") or []
        if item in inv:
            inv.remove(item)
        _desequipar_o_que_saiu(char, item.get("nome", ""))


def use_magic_item(char_name: str, item_name: str, spell: str = "", target: str = "",
                   charges: int = 0) -> str:
    """
    Usa um item mágico que conjura: pergaminho de magia, varinha ou cajado
    (Varinha de Mísseis Mágicos, Cajado da Cura...). Fora da luta é aqui; na
    luta o jogador usa pela tela tática. O motor gasta as cargas (ou o
    pergaminho), aplica a CD do item e cobra quem pode ler o pergaminho.

    Args:
        char_name: Quem usa o item.
        item_name: O item, como está no inventário.
        spell:     A magia (vazio = a primeira que o item conjura).
        target:    Alvo(s), separados por vírgula.
        charges:   Cargas a gastar quando cada carga a mais sobe o círculo
                   (0 = o mínimo).
    """
    from rpg import compendio
    char, err = _get_char(char_name)
    if not char:
        return err
    item = _item_do_inventario(char, item_name)
    uso = _uso_do_item(item["nome"]) if item else None
    if not uso or uso.get("tipo") not in ("cargas", "pergaminho"):
        return f"Erro: '{item_name}' não é item que conjure magia."
    if not spell:
        spell = uso["magias"][0]["magia"]
    modo = ""
    if charges:
        m = compendio.magia(spell) or {}
        entrada = next((e for e in uso["magias"]
                        if (compendio.magia(e["magia"]) or {}).get("nome_srd") == m.get("nome_srd")), {})
        if entrada.get("extra"):
            modo = f"c{int(m.get('nivel', 1) or 1) + max(0, int(charges) - int(entrada.get('cargas', 1)))}"
    return _conjurar_do_item(char["name"], item["nome"], spell, target, modo)


# ── Munição e arremesso: o que se recolhe depois da luta ──────────────────
# No 5e, depois da luta se recupera metade da munição gasta, e a arma
# arremessada fica no chão até alguém pegar. O motor gastava a flecha e a
# azagaia ia e voltava sozinha para a mão.

def _anotar_gasto(char: dict, campo: str, nome: str) -> None:
    if not (memory.campaign.get("combat_state") or {}).get("is_active"):
        return
    gasto = (char.get("sheet") or {}).setdefault(campo, {})
    gasto[nome] = int(gasto.get(nome, 0) or 0) + 1


def _recolher_municao_e_arremessos() -> str:
    linhas = []
    for ch in (memory.campaign.get("characters") or {}).values():
        s = (ch or {}).get("sheet") if isinstance(ch, dict) else None
        if not s:
            continue
        for campo, metade in (("_municao_gasta", True), ("_arremessadas", False)):
            for nome, n in (s.pop(campo, None) or {}).items():
                volta = int(n) // 2 if metade else int(n)
                if volta <= 0:
                    continue
                item = _item_do_inventario(ch, nome)
                if item:
                    item["qtd"] = int(item.get("qtd", 0) or 0) + volta
                else:
                    ch.setdefault("inventario", []).append({"nome": nome, "qtd": volta, "descricao": ""})
                linhas.append(f"{ch.get('name')} recolhe {volta}x {nome}"
                              + (f" (de {n} atiradas)" if metade else ""))
    return "".join(f"\n   {l}" for l in linhas)


def _defesas_visiveis(ch: dict, sheet: dict, campo: str) -> list[str]:
    """
    Os tipos daquele campo que a tela pode mostrar: todos, nos personagens do
    grupo (a ficha é do jogador), e só os descobertos nos demais.
    """
    tipos = sorted({t for e in _traits_lookup(sheet, campo) for t in e.get("tipos", [])})
    if memory.is_party_member(ch):
        return tipos
    return [t for t in tipos if _ja_descoberto(sheet, campo, t)]


def _combatant_snapshot(name: str) -> dict | None:
    ch = memory.campaign["characters"].get(memory.char_key(name))
    if not ch:
        return None
    _limpar_condicoes(ch)
    s = ch.get("sheet") or {}
    conds = []
    _seen_cond = set()
    if not _zonas_ativas():
        for _area in _areas_sobre(ch.get("name", "")):
            if _area.get("nome") and _area["nome"].lower() not in _seen_cond:
                _seen_cond.add(_area["nome"].lower())
                conds.append(_area["nome"])
    for c in (s.get("condicoes") or []):
        nm  = (c.get("nome", "") if isinstance(c, dict) else str(c)) or ""
        key = nm.lower().strip()
        if key and key not in _seen_cond:        # dedup por nome
            _seen_cond.add(key)
            conds.append(nm)
    # Montado: aparece com as condições.
    from rpg import manobras as _mb_s
    if _mb_s.montaria_de(ch):
        conds.append(f"Montado em {_mb_s.montaria_de(ch).get('name', '')}")
    # A luz onde ele está, quando não é clara.
    _luz_c = _luz_no_lugar(ch.get("name", ""))
    if _luz_c != "clara":
        conds.append("Na escuridão" if _luz_c == "escuridao" else "Na penumbra")
    # Cobertura aparece com as condições: é o que muda a CA contra quem atira.
    if _cobertura_de(ch):
        conds.append(_COBERTURA_NOME[_cobertura_de(ch)].capitalize())
    habs = []        # só ATIVAS (viram botão)
    passivas = []    # exibição informativa
    # O botão de cada habilidade sai do MODELO ÚNICO (rpg/habilidade.py), que
    # lê das mesmas funções que o motor usa para resolvê-la. Antes saía do
    # campo cru da ficha: Infligir Ferimentos aparecia sem dado e rolava 3d10,
    # a descrição só existia ao passar o mouse, e a mesma Chama Sagrada vinha
    # duas vezes.
    from rpg import habilidade as _habilidade, resolucao as _resolucao_snap
    for h in _habilidade.sem_duplicatas(ch.get("habilidades") or []):
        r = _habilidade.resolver(h, ch)
        entry = _cartao_de_habilidade(h, ch, r)
        if r["passiva"]:
            passivas.append(entry["nome_exibido"])
        else:
            habs.append(entry)
    habs.extend(_magias_de_itens(ch))
    itens = []
    itens_combate = []   # subconjunto consumível (usável na tela tática)
    for it in (ch.get("inventario") or []):
        if not isinstance(it, dict):
            continue
        entry = {
            "nome": it.get("nome", ""),
            "qtd":  int(it.get("qtd", 1) or 1),
            "descricao": it.get("descricao", ""),
        }
        itens.append(entry)
        ficha = _efeito_de_item(entry["nome"])
        if ficha and entry["qtd"] > 0:
            # kind: o que a tela faz ao clicar. "heal" abre "Curar quem",
            # "arremesso" abre o alvo, "si" aplica direto, "desconhecido" fica
            # travado com o motivo.
            if ficha["efeito"] == "magia":
                continue           # conjura pelo botão Habilidade (magias_de_itens)
            kind = {"cura": "heal", "estabilizar": "heal", "arremesso": "arremesso", "pocao": "si",
                    "resistencia": "si", "antitoxina": "si"}.get(ficha["efeito"], "desconhecido")
            itens_combate.append({
                **entry,
                "kind": kind,
                "efeito": ficha["efeito"],
                "tipo_acao": ficha["slot"],
                "dice": ficha.get("rotulo", ""),
                "usavel": kind != "desconhecido",
                "motivo": ficha.get("motivo", ""),
                "alvos": _alvos_de_item(ch.get("name", name), ficha),
            })
    # Anota a subescolha de cada habilidade de classe (Estilo de Combate,
    # Inimigo Favorecido, Metamagia…) na entrada correspondente — assim a UI
    # mostra "Estilo de Combate: Arquearia" no card sem buscar de novo.
    _choices = (s.get("feature_choices") or {})
    for h in habs:
        v = _choices.get(h["nome"])
        if v is not None:
            h["choice"] = v
    return {
        "name":       ch.get("name", name),
        "status":     (ch.get("status", "vivo") or "vivo"),
        "is_party":   bool(memory.is_party_member(ch)),
        # Invocação que o jogador comanda: a tela dá a barra de ação a ela.
        "invocacao_de": ((memory.campaign["characters"].get((ch.get("invocacao") or {}).get("por", "")) or {})
                         .get("name", "") if isinstance(ch.get("invocacao"), dict) else ""),
        "controlada": __import__("rpg.criaturas", fromlist=["x"]).controlada_pelo_jogador(ch),
        # Golpe não letal ligado: o corpo a corpo que derruba nocauteia.
        "nao_letal": bool(s.get("nao_letal")),
        "cobertura": _cobertura_de(ch),
        "visao_no_escuro": _visao_no_escuro(ch),
        "montado_em": ((__import__("rpg.manobras", fromlist=["x"]).montaria_de(ch) or {}).get("name", "")),
        "montaria_de": ((__import__("rpg.manobras", fromlist=["x"]).cavaleiro_de(ch) or {}).get("name", "")),
        "pode_montar": bool(__import__("rpg.manobras", fromlist=["x"]).montarias_livres(ch)),
        "tem_tocha": _tem_tocha(ch),
        "luz_acesa": bool(s.get("luz_acesa")),
        # Pode atacar com a outra mão: tem outra arma leve além da principal.
        "outra_mao": bool(_arma_da_outra_mao(ch, ((s.get("equipamentos") or {}).get("arma_principal") or ""))),
        # Rendido, ou enfeitiçado/dominado pelo grupo: não precisa morrer.
        "poupado": poupado(ch),
        # "grupo" | "aliado" | "inimigo": a tela pinta o aliado do seu lado,
        # mas quem o joga é o motor (is_party continua sendo só o grupo).
        "lado":       memory.lado_no_combate(ch),
        # Onda 3 — posição no campo. "" quando o combate não usa zonas.
        "zona":       _zona_de(ch.get("name", name)),
        "trancado":   _inimigos_na_zona(ch.get("name", name)),
        "lendarias":  ((s.get("lendarias") or {}).get("restantes")
                       if isinstance(s.get("lendarias"), dict) else None),
        "recargas":   {k: bool(v.get("pronto", True))
                       for k, v in (s.get("recargas") or {}).items()
                       if isinstance(v, dict)},
        "hp":         int(s.get("vida_atual", 0) or 0),
        "hp_max":     int(s.get("vida_max", 0) or 0),
        # Onda 2 — a tela precisa mostrar por que um golpe deu metade do dano.
        "hp_temp":    _temp_hp(s),
        "concentracao": (s.get("concentracao") or {}).get("magia", ""),
        "reacao_disponivel": _reaction_available(ch),
        "reacoes":    (__import__("rpg.reacoes", fromlist=["x"]).disponiveis(ch)
                       if memory.is_party_member(ch) else []),
        "resistencias":     _defesas_visiveis(ch, s, "resistencias"),
        "imunidades":       _defesas_visiveis(ch, s, "imunidades"),
        "vulnerabilidades": _defesas_visiveis(ch, s, "vulnerabilidades"),
        "mp":         int(s.get("mana_atual", 0) or 0),
        "mp_max":     int(s.get("mana_max", 0) or 0),
        # A CA que os ataques enfrentam: com Escudo da Fé, Pele de Árvore.
        "ca":         _ca_efetiva(ch),
        "nivel":      int(s.get("nivel", 1) or 1),
        "classe":     s.get("classe", ""),
        "arma":       (s.get("equipamentos", {}) or {}).get("arma_principal") or "",
        "armas":      _combatant_weapons(ch),
        "condicoes":  conds,
        # Turnos restantes de cada condição com duração (nome → turnos).
        "condicoes_turnos": {(c.get("nome") or ""): _turnos_restantes(c)
                             for c in (s.get("condicoes") or [])
                             if _turnos_restantes(c) > 0},
        # Efeitos de item que duram o combate (resistência, antitoxina).
        "efeitos":    [e.get("nome", "") for e in _efeitos(s)],
        # Paralisado, Atordoado, Banido…: a tela mostra por que ele não age.
        "impedido":   _impedido_de_agir(ch),
        # Enfeitiçado por quem, até quando (rpg/encantos.py).
        "encanto":    _encanto_nota(ch),
        "habilidades": habs,
        "passivas":   passivas,
        "inventario": itens,
        "itens_combate": itens_combate,
    }


def _encanto_nota(ch: dict) -> str:
    from rpg import encantos
    return encantos.nota(ch)


def combat_snapshot() -> dict:
    """Estado completo do combate para a tela tática (JSON-serializável)."""
    from rpg import criaturas, encantos
    encantos.expirar()
    criaturas.limpar()
    camp = memory.campaign
    cs   = camp.get("combat_state", {}) or {}
    order = list(cs.get("initiative_order", []) or [])
    idx   = cs.get("current_turn_index", 0)
    if not isinstance(idx, int) or not (0 <= idx < len(order)):
        idx = 0
    combatants = []
    for nm in order:
        snap = _combatant_snapshot(nm)
        if snap:
            snap["is_current"] = (order.index(nm) == idx) if nm in order else False
            combatants.append(snap)
    current = order[idx] if order else ""
    return {
        "combat_mode": "tela",          # o único modo de combate
        "is_active":   bool(cs.get("is_active")),
        "round":       int(cs.get("round", 1) or 1),
        "turn_index":  idx,
        "turn_token":  int(cs.get("turn_token", 0) or 0),
        "current":     current,
        "current_is_party": bool(
            memory.is_party_member(
                memory.campaign["characters"].get(memory.char_key(current), {})
            ) or criaturas.controlada_pelo_jogador(
                memory.campaign["characters"].get(memory.char_key(current), {}))
        ) if current else False,
        "order":       order,
        # Campo de batalha: lista vazia = combate sem posicionamento.
        "zonas":       _zonas(),
        "zona_desc":   dict(cs.get("zona_desc") or {}),
        "zonas_efeito": {z: [e.get("nome", "") for e in _efeitos_de_zona(z)] for z in _zonas()},
        "combatants":  combatants,
        # O turno do inimigo parado numa reação em "perguntar" (rpg/reacoes.py).
        "reacao_pendente": ({k: (cs.get("reacao_pendente") or {}).get(k, "")
                             for k in ("npc", "quem", "chave", "nome", "texto")}
                            if cs.get("reacao_pendente") else None),
        "log":         list(cs.get("log", []) or [])[-60:],
        "result":      cs.get("result"),   # painel de fim (None até acabar)
        "turn_economy": dict(cs.get("turn_economy") or
                             {"acao_usada": False, "bonus_usada": False,
                              "movimento_usado": False}),
        "alcance":     _alcance_do_turno(current) if cs.get("is_active") else {},
    }


def _alcance_do_turno(nome: str) -> dict:
    """
    Para o combatente do grupo que está na vez: cada arma dele contra cada
    outro combatente, "ok" | "desvantagem" | "fora". A tela usa isto para não
    oferecer como alvo quem a arma não alcança — a regra continua sendo a de
    _checar_alcance, a tela só lê. Vazio sem zonas ou na vez de um NPC.
    """
    if not nome or not _zonas_ativas():
        return {}
    chars = memory.campaign.get("characters", {})
    ch = chars.get(memory.char_key(nome))
    from rpg import criaturas as _cri_a
    if not ch or not (memory.is_party_member(ch) or _cri_a.controlada_pelo_jogador(ch)):
        return {}
    cs = memory.campaign.get("combat_state") or {}
    outros = []
    for n in cs.get("initiative_order", []) or []:
        o = chars.get(memory.char_key(n))
        if o and o is not ch:
            outros.append(o.get("name", n))
    tabela = {}
    for arma in _combatant_weapons(ch):
        linha = {}
        for alvo in outros:
            recusa, desv = _checar_alcance(nome, alvo, arma["nome"])
            linha[alvo] = "fora" if recusa else ("desvantagem" if desv else "ok")
        tabela[arma["nome"]] = linha
    return tabela


def combat_action(action: str, actor: str = "", target: str = "",
                  weapon: str = "", ability: str = "", item: str = "") -> dict:
    """
    Aplica UMA intenção de combate vinda da tela, delegando ao motor
    determinístico já fuzzado. Retorna {ok, message, snapshot}.

    actions: attack | ability | item | move | enemy | pass | defend | flee |
             death_save | end

    move: `target` é a zona de destino; weapon="dash" usa a Disparada
    (custa a Ação) para cruzar duas zonas.
    """
    cs = memory.campaign.get("combat_state", {}) or {}
    if action not in ("end",) and not cs.get("is_active"):
        return {"ok": False, "message": "Nenhum combate ativo.",
                "snapshot": combat_snapshot()}

    msg = ""
    a = (action or "").lower().strip()

    # Uma reação em "perguntar" parou a jogada: só a resposta segue.
    from rpg import reacoes as _rea_ca
    if a not in ("reagir", "end", "enemy") and cs.get("reacao_pendente"):
        return {"ok": False, "message": _aviso_de_pergunta_pendente(), "snapshot": combat_snapshot()}
    # A ação do jogador também pode chamar uma reação que pergunta: o
    # Oportunista do monge quando o guerreiro acerta, o Golpe Mágico.
    if (a not in ("reagir", "end", "enemy", "auto", "death_save", "nao_letal", "cover", "light", "dismount",
                  "flee_all")
            and _rea_ca._respostas is None and _rea_ca.alguem_pergunta()):
        return _com_perguntas({"fn": "combat_action",
                               "kw": {"action": action, "actor": actor, "target": target, "weapon": weapon,
                                      "ability": ability, "item": item}}, [], None)

    # Helper local: tenta marcar slot ("acao"|"bonus") na economia do turno.
    # Retorna mensagem de erro (string) ou None se ok.
    def _use_slot(eco: dict, slot: str) -> str | None:
        key = slot + "_usada"
        if eco.get(key):
            rotulo = "Ação" if slot == "acao" else "Ação Bônus"
            return (f"Erro: {actor} já usou sua {rotulo} neste turno. "
                    f"Use 'Encerrar Turno' ou a outra parte da economia.")
        eco[key] = True
        return None

    # Caminhos que NÃO usam a economia do jogador (o motor cuida do avanço):
    if a == "enemy":
        msg = execute_npc_turn()

    elif a == "reagir":
        # A reação em "perguntar": Usar / Não usar (weapon = "sim" | "nao").
        msg = responder_reacao(_norm_txt(weapon or "") in ("sim", "usar", "true", "1"))
        if msg.startswith("Aviso:"):
            return {"ok": False, "message": msg, "snapshot": combat_snapshot()}

    elif a == "auto":
        # A invocação do jogador, jogada pelo motor só desta vez.
        from rpg import criaturas as _cri_auto
        _vez_a = memory.campaign["characters"].get(memory.char_key(_combat_current_actor())) or {}
        if not _cri_auto.controlada_pelo_jogador(_vez_a):
            return {"ok": False, "message": "Erro: o motor só joga por uma invocação do grupo, na vez dela.",
                    "snapshot": combat_snapshot()}
        msg = execute_npc_turn(_forcar=True)

    elif a == "death_save":
        if not actor:
            return {"ok": False, "message": "Teste de morte exige actor.",
                    "snapshot": combat_snapshot()}
        msg = roll_death_save(actor)

    elif a == "end":
        # Encerrar pela tela com inimigos ainda lutando: o Mestre decide como
        # (trégua, fuga, rendição) — sem a vitória automática.
        _ainda = [n for n in cs.get("initiative_order") or []
                  if (lambda c: c and not memory.luta_com_o_grupo(c) and not poupado(c)
                      and (c.get("status") or "").lower() not in DEFEATED_STATUSES)(
                      memory.campaign["characters"].get(memory.char_key(n)))]
        if _ainda and cs.get("is_active"):
            cs["result"] = {"outcome": "interrompido", "title": "Luta encerrada",
                            "sobreviventes": [], "caidos": [], "poupados": [],
                            "de_pe": _ainda}
        msg = end_combat()

    elif a == "flee_all":
        msg = _fugir_em_grupo()

    else:
        # Daqui pra baixo: ações DE JOGADOR. Aplicam a economia 5e (Ação,
        # Bônus). Engine NÃO avança turno por conta própria (end_turn=False)
        # — esta função decide o avanço com base na economia.
        if not actor:
            return {"ok": False, "message": f"Ação '{a}' exige actor.",
                    "snapshot": combat_snapshot()}
        v = _combat_turn_violation(actor)
        if v:
            return {"ok": False, "message": v, "snapshot": combat_snapshot()}
        # Paralisado, Atordoado, Banido: o personagem do jogador também não age.
        ch_ator = memory.campaign["characters"].get(memory.char_key(actor)) or {}
        preso = _impedido_de_agir(ch_ator) if ch_ator else ""
        if preso and a not in ("pass", "end_turn"):
            return {"ok": False,
                    "message": f"Erro: {actor} está {preso} e não pode agir neste turno. Encerre o turno.",
                    "snapshot": combat_snapshot()}
        eco = cs.setdefault("turn_economy",
                            {"acao_usada": False, "bonus_usada": False})
        force_end = False  # se True ao final, encerra o turno (flee/pass)
        narrar = False     # habilidade sem regra no motor: a tela chama o Mestre

        if a == "attack":
            if not target:
                return {"ok": False, "message": "Ataque exige target.",
                        "snapshot": combat_snapshot()}
            # Ataque Extra: os golpes seguintes da MESMA ação Atacar não gastam
            # outra Ação. Antes o turno do guerreiro de nível 5 acabava no 1º.
            ch_atk = memory.campaign["characters"].get(memory.char_key(actor), {}) or {}
            restantes = int(eco.get("ataques_restantes", 0) or 0)
            golpe_extra = restantes > 0
            if golpe_extra:
                eco["ataques_restantes"] = restantes - 1
            else:
                err = _use_slot(eco, "acao")
                if err:
                    return {"ok": False, "message": err, "snapshot": combat_snapshot()}
                eco["ataques_restantes"] = _numero_de_ataques(ch_atk) - 1

            def _devolver_ataque():
                if golpe_extra:
                    eco["ataques_restantes"] = int(eco.get("ataques_restantes", 0) or 0) + 1
                else:
                    eco["acao_usada"] = False
                    eco["ataques_restantes"] = 0

            if not weapon:
                weapon = ((ch_atk.get("sheet", {}) or {}).get("equipamentos", {}) or {}
                          ).get("arma_principal") or "ataque desarmado"
            # Mesma checagem que attack_roll faz, antes de gastar: recusa de
            # alcance não é ataque, e a Ação tem de continuar disponível.
            recusa, _ = _checar_alcance(actor, target, weapon)
            if recusa:
                _devolver_ataque()
                zona_alvo = _zona_de(target) or "outra zona"
                return {"ok": False,
                        "message": (f"Fora de alcance: {target} está em {zona_alvo}. "
                                    f"Corpo-a-corpo só na mesma zona; mova-se ou use "
                                    f"uma arma à distância. A Ação não foi gasta."),
                        "snapshot": combat_snapshot()}
            msg = attack_roll(actor, target, weapon, 6, end_turn=False)
            if not msg.startswith(("Erro:", "Aviso:")) and _arma_leve(weapon):
                eco["ataque_leve"] = weapon
            if msg.startswith(("Erro:", "Aviso:")):
                _devolver_ataque()
                return {"ok": False, "message": msg + "\nA Ação não foi gasta.",
                        "snapshot": combat_snapshot()}
            if int(eco.get("ataques_restantes", 0) or 0) > 0:
                n = eco["ataques_restantes"]
                msg += (f"\n   Ataque Extra: mais {n} {'ataque' if n == 1 else 'ataques'} "
                        f"nesta mesma ação.")

        elif a == "ability" and _magia_de_item_no_nome(ability or ""):
            _magia_i, _item_i = _magia_de_item_no_nome(ability)
            err = _use_slot(eco, "acao")
            if err:
                return {"ok": False, "message": err, "snapshot": combat_snapshot()}
            msg = _conjurar_do_item(actor, _item_i, _magia_i, target, modo=(weapon or "").strip())
            if msg.lstrip().startswith(("Erro:", "Aviso:")):
                eco["acao_usada"] = False
                return {"ok": False, "message": msg, "snapshot": combat_snapshot()}

        elif a == "ability":
            if not ability:
                return {"ok": False, "message": "Habilidade exige ability.",
                        "snapshot": combat_snapshot()}
            # Pré-checa mana ANTES de consumir slot — sem isso, uma magia
            # recusada por falta de mana ainda gastaria a Ação/Bônus do turno.
            ch_pre = memory.campaign["characters"].get(memory.char_key(actor)) or {}
            habs_pre = ch_pre.get("habilidades") or []
            hab_pre = next((h for h in habs_pre
                            if isinstance(h, dict)
                            and (h.get("nome") or "").lower() == ability.lower()), None)
            if hab_pre is None:
                # Tenta tradução PT→EN
                en_alt = _SPELL_PT_TO_EN.get(ability.lower())
                if en_alt:
                    hab_pre = next((h for h in habs_pre
                                    if isinstance(h, dict)
                                    and (h.get("nome") or "").lower() == en_alt.lower()), None)
            if hab_pre is not None:
                custo_pre = int(hab_pre.get("custo_mana", 0) or 0)
                sheet_pre = ch_pre.get("sheet") or {}
                mp_atual  = int(sheet_pre.get("mana_atual", 0) or 0)
                if custo_pre > mp_atual:
                    mp_max = int(sheet_pre.get("mana_max", 0) or 0)
                    return {
                        "ok": False,
                        "message": (f"Erro: {actor} não tem mana suficiente para "
                                    f"'{hab_pre.get('nome', ability)}' "
                                    f"(precisa {custo_pre}, tem {mp_atual}/{mp_max}). "
                                    f"A Ação/Bônus deste turno NÃO foi gasta."),
                        "snapshot": combat_snapshot(),
                    }
            # Surto de Ação não custa ação nenhuma: ele DEVOLVE a Ação do
            # turno. Uma vez por turno, senão viraria turno infinito.
            surto = _e_surto_de_acao(ability)
            if surto and eco.get("surto_usado"):
                return {"ok": False,
                        "message": f"Erro: {actor} já usou Surto de Ação neste turno.",
                        "snapshot": combat_snapshot()}

            slot = None if surto else _slot_da_habilidade(ability, hab_pre, ch_pre)
            # A escolha muda o custo: voltar da Forma Selvagem e Finta são ação
            # bônus; as manobras de golpe não custam ação.
            if hab_pre is not None and not surto:
                from rpg import resolucao as _res_slot
                _ov = _res_slot.slot_do_modo(hab_pre, ch_pre, (weapon or "").strip())
                if _ov:
                    slot = None if _ov == "livre" else _ov
            from rpg import subclasses as _sub_c
            _rapida = _sub_c.conjuracao_rapida(ch_pre, hab_pre) if (slot == "acao" and hab_pre) else ""
            if _rapida:
                slot = "bonus"
            if slot:
                err = _use_slot(eco, slot)
                if err:
                    return {"ok": False, "message": err, "snapshot": combat_snapshot()}
            # A escolha da ação (Ação Ardilosa: disparada, desengajar ou
            # esconder) viaja em `weapon`, como a Disparada no movimento.
            msg = use_ability(actor, ability, target, end_turn=False, modo=(weapon or "").strip())
            if hab_pre is not None:
                from rpg import resolucao as _res_mod
                narrar = _res_mod.como_resolve(hab_pre, ch_pre)["tipo"] == "narrativa"
            if msg.startswith(("Erro:", "Aviso:")):
                if slot:
                    eco[slot + "_usada"] = False
                return {"ok": False, "message": msg, "snapshot": combat_snapshot()}
            if _rapida:
                msg += _sub_c.consumir_rapida(ch_pre, _rapida)
            msg += _sub_c.lancar_gemea(actor, ability, (weapon or "").strip())
            if surto:
                eco["acao_usada"] = False
                eco["surto_usado"] = True
                msg += ("\n   Surto de Ação: a Ação deste turno volta a estar "
                        "disponível — ataque de novo, conjure ou corra.")

        elif a == "item":
            item_name = (item or weapon or "").strip()
            if not item_name:
                return {"ok": False, "message": "Especifique o item.",
                        "snapshot": combat_snapshot()}
            ch = memory.campaign["characters"].get(memory.char_key(actor))
            if not ch:
                return {"ok": False, "message": f"'{actor}' não encontrado.",
                        "snapshot": combat_snapshot()}
            inv = ch.get("inventario") or []
            slot_inv = next((it for it in inv
                             if isinstance(it, dict)
                             and _norm_txt(it.get("nome") or "") == _norm_txt(item_name)
                             and int(it.get("qtd", 1) or 1) > 0), None)
            if not slot_inv:
                return {"ok": False,
                        "message": f"Erro: '{actor}' não tem '{item_name}' utilizável.",
                        "snapshot": combat_snapshot()}
            ficha = _efeito_de_item(slot_inv.get("nome", ""))
            if not ficha:
                return {"ok": False,
                        "message": f"Aviso: '{slot_inv['nome']}' não é consumível de combate.",
                        "snapshot": combat_snapshot()}
            if ficha["efeito"] == "desconhecido":
                return {"ok": False,
                        "message": f"Aviso: {slot_inv['nome']}: {ficha['motivo']} O item não foi gasto.",
                        "snapshot": combat_snapshot()}

            # Alvo validado ANTES de gastar a economia e a unidade: uma recusa
            # nunca custa o turno nem o item.
            chars = memory.campaign["characters"]
            if ficha["efeito"] == "magia":
                return {"ok": False,
                        "message": (f"Aviso: {slot_inv['nome']} conjura pelo botão Habilidade. "
                                    f"O item não foi gasto."),
                        "snapshot": combat_snapshot()}
            if ficha["efeito"] in ("resistencia", "antitoxina", "pocao"):
                recv = ch
            else:
                recv_name = (target or ("" if ficha["efeito"] == "arremesso" else actor)).strip()
                if not recv_name:
                    return {"ok": False, "message": f"Aviso: escolha em quem usar {slot_inv['nome']}.",
                            "snapshot": combat_snapshot()}
                recv = chars.get(memory.char_key(recv_name))
                if not recv or not recv.get("sheet"):
                    return {"ok": False, "message": f"Erro: alvo '{recv_name}' inválido.",
                            "snapshot": combat_snapshot()}
                if (recv.get("status") or "").lower() in ("morto", "fugiu"):
                    return {"ok": False,
                            "message": f"Aviso: {recv['name']} está fora do combate.",
                            "snapshot": combat_snapshot()}
                if ficha["efeito"] == "arremesso" and recv is ch:
                    return {"ok": False,
                            "message": f"Aviso: escolha outro alvo para {slot_inv['nome']}.",
                            "snapshot": combat_snapshot()}
                if ficha["efeito"] == "estabilizar" and (
                        int((recv.get("sheet") or {}).get("vida_atual", 0) or 0) > 0
                        or (recv.get("status") or "").lower() == "estabilizado"):
                    return {"ok": False,
                            "message": (f"Aviso: {recv['name']} não está caído morrendo; "
                                        f"o kit não foi gasto."),
                            "snapshot": combat_snapshot()}
                alcance = _alcance_de_item(actor, recv, ficha)
                if alcance == "fora":
                    za, zb = _zona_de(actor), _zona_de(recv["name"])
                    regra = ("dar a poção a outra pessoa só na mesma zona"
                             if ficha["efeito"] == "cura"
                             else "o arremesso alcança a própria zona ou a vizinha")
                    return {"ok": False,
                            "message": (f"Erro: FORA DE ALCANCE: {actor} está em **{za}** e "
                                        f"{recv['name']}, em **{zb}**: {regra}."),
                            "snapshot": combat_snapshot()}
                if alcance == "sem_efeito":
                    return {"ok": False,
                            "message": (f"Aviso: {slot_inv['nome']} só fere mortos-vivos e "
                                        f"infernais; em {recv['name']} não faria nada. "
                                        f"O item não foi gasto."),
                            "snapshot": combat_snapshot()}

            slot = ficha["slot"]
            err = _use_slot(eco, slot)
            if err:
                return {"ok": False, "message": err, "snapshot": combat_snapshot()}
            tag_eco = "Bônus" if slot == "bonus" else "Ação"
            st = recv["sheet"]

            if ficha["efeito"] == "cura":
                n_d, sides, bonus = ficha["dado"]
                rolls = [random.randint(1, sides) for _ in range(n_d)]
                heal  = sum(rolls) + bonus
                hp_antes = int(st.get("vida_atual", 0) or 0)
                hp_max   = int(st.get("vida_max", 0) or 0)
                # O teto da exaustão vale para a poção como vale para o descanso.
                teto     = _hp_max_efetivo(st)
                st["vida_atual"] = max(0, min(teto, hp_antes + heal))
                hp_depois = st["vida_atual"]
                if hp_antes == 0 and hp_depois > 0 and (recv.get("status", "") or "").lower() in ("inconsciente", "estabilizado"):
                    recv["status"] = "vivo"
                    st["death_saves_sucessos"] = 0
                    st["death_saves_falhas"]   = 0
                detail = " + ".join(str(r) for r in rolls)
                nota_teto = f" (teto {teto} pela exaustão)" if teto < hp_max else ""
                _log_combat_event(
                    "item_heal", actor, recv["name"],
                    msg=(f"{actor} usou {slot_inv['nome']} em {recv['name']} "
                         f"[{tag_eco}]: {n_d}d{sides}: [{detail}] +{bonus} = "
                         f"{heal} cura • HP {hp_antes}→{hp_depois}/{hp_max}{nota_teto}"),
                    item=slot_inv["nome"], rolls=list(rolls), heal=heal,
                    hp=hp_depois, hp_max=hp_max, slot=slot,
                )
                msg = (f"{actor} usou {slot_inv['nome']} em {recv['name']} "
                       f"[{tag_eco}]: +{heal} HP ({hp_antes}→{hp_depois}/{hp_max}){nota_teto}.")

            elif ficha["efeito"] == "resistencia":
                tipo = ficha["tipo_dano"]
                pt = _TIPO_DANO_ITEM_PT.get(tipo, tipo)
                _dar_efeito(st, {"nome": f"Resistência a {pt}", "resistencia": tipo,
                                 "origem": slot_inv["nome"], "ate": "fim_do_combate"})
                msg = f"{actor} bebeu {slot_inv['nome']} [{tag_eco}]: resistência a dano de {pt} até o fim do combate."
                _log_combat_event("item_buff", actor, actor, msg=msg, item=slot_inv["nome"], slot=slot)

            elif ficha["efeito"] == "estabilizar":
                msg = _estabilizar_com_kit(ch, recv, slot_inv, ficha) + f" [{tag_eco}]"
                _log_combat_event("item_buff", actor, recv["name"], msg=msg, item=slot_inv["nome"], slot=slot)

            elif ficha["efeito"] == "pocao":
                msg = _beber_pocao(recv, slot_inv["nome"], ficha["uso"]) + f" [{tag_eco}]"
                _log_combat_event("item_buff", actor, actor, msg=msg, item=slot_inv["nome"], slot=slot)

            elif ficha["efeito"] == "antitoxina":
                _dar_efeito(st, {"nome": "Antitoxina", "antitoxina": True,
                                 "descricao": "vantagem em salvaguardas contra Envenenado",
                                 "origem": slot_inv["nome"], "ate": "fim_do_combate"})
                msg = (f"{actor} tomou {slot_inv['nome']} [{tag_eco}]: vantagem em "
                       f"salvaguardas contra Envenenado até o fim do combate.")
                _log_combat_event("item_buff", actor, actor, msg=msg, item=slot_inv["nome"], slot=slot)

            else:   # arremesso
                cd = _cd_de_arremesso(ch)
                passou, texto_save = _salvaguarda_de_destreza(recv, cd)
                n_d, sides, bonus = ficha["dado"]
                if passou:
                    linha = (f"{actor} arremessou {slot_inv['nome']} em {recv['name']} "
                             f"[{tag_eco}]: {texto_save} — passou, sem dano")
                    _log_combat_event("item_attack", actor, recv["name"], msg=linha,
                                      item=slot_inv["nome"], slot=slot, dano=0)
                    msg = linha + "."
                else:
                    rolls = [random.randint(1, sides) for _ in range(n_d)]
                    bruto = sum(rolls) + bonus
                    res = _apply_damage(recv, bruto, ficha["tipo_dano"],
                                        source_name=actor, arma_magica=True)
                    pt = _TIPO_DANO_ITEM_PT.get(ficha["tipo_dano"], ficha["tipo_dano"])
                    _dado_txt = (f"{n_d}d{sides} [{' + '.join(str(r) for r in rolls)}]"
                                 + (f" +{bonus}" if bonus else "")) if n_d else f"{bonus}"
                    linha = (f"{actor} arremessou {slot_inv['nome']} em {recv['name']} "
                             f"[{tag_eco}]: {texto_save} — falhou: {_dado_txt} "
                             f"= {res['dano']} de {pt} "
                             f"• HP {res['hp_antes']}→{res['hp_depois']}/{int(st.get('vida_max', 0) or 0)}")
                    if res["notas"]:
                        linha += " (" + "; ".join(res["notas"]) + ")"
                    if res["hp_depois"] == 0 and res["hp_antes"] > 0:
                        linha += _mark_at_zero_hp(recv, actor)
                    elif ficha.get("queimando") and res["hp_depois"] > 0:
                        conds = st.setdefault("condicoes", [])
                        if not any((c.get("nome", "") if isinstance(c, dict) else str(c)).lower() == "queimando"
                                   for c in conds):
                            conds.append({"nome": "Queimando", "duracao": None})
                        linha += f" • {recv['name']} está QUEIMANDO"
                    _log_combat_event("item_attack", actor, recv["name"], msg=linha,
                                      item=slot_inv["nome"], slot=slot, dano=res["dano"],
                                      hp=res["hp_depois"])
                    msg = linha + "."

            if ficha["efeito"] != "estabilizar":
                slot_inv["qtd"] = int(slot_inv.get("qtd", 1) or 1) - 1
                if slot_inv["qtd"] <= 0:
                    try: inv.remove(slot_inv)
                    except ValueError: pass
            memory.save_campaign()

        elif a == "move":
            # Movimento NÃO é Ação em 5e: acontece ao lado dela, uma vez por
            # turno. Só a Disparada (dash) custa a Ação — e é o que permite
            # cruzar duas zonas.
            destino = (target or item or "").strip()
            if not destino:
                return {"ok": False, "message": "Movimento exige a zona de destino.",
                        "snapshot": combat_snapshot()}
            # Agarrado, Contido (Teia), Aprisionado: não sai da zona.
            preso_mv = _condicao_com(ch_ator, "no_movement") if ch_ator else ""
            if preso_mv:
                return {"ok": False,
                        "message": f"Erro: {actor} está {preso_mv} e não sai da zona.",
                        "snapshot": combat_snapshot()}
            # Zonas de movimento do turno: a de sempre, mais as da Disparada
            # de bônus (Ação Ardilosa, Passo do Vento). A Disparada de Ação
            # (dash) soma mais uma.
            extra = int(eco.get("movimento_extra", 0) or 0)
            livres = (0 if eco.get("movimento_usado") else 1) + extra
            dash = bool(weapon and weapon.lower() == "dash")
            if livres <= 0 and not dash:
                return {"ok": False,
                        "message": f"Erro: {actor} já se moveu neste turno.",
                        "snapshot": combat_snapshot()}
            origem_mv = _zona_de(actor)
            zonas_mv = _zonas()
            destino_mv = _zona_canonica(destino)
            passos = (abs(zonas_mv.index(destino_mv) - zonas_mv.index(origem_mv))
                      if origem_mv in zonas_mv and destino_mv in zonas_mv else 1)
            if dash:
                err = _use_slot(eco, "acao")
                if err:
                    return {"ok": False, "message": err, "snapshot": combat_snapshot()}
            alcance_mv = livres + (1 if dash else 0)
            if passos > alcance_mv:
                if dash:
                    eco["acao_usada"] = False
                return {"ok": False,
                        "message": (f"Erro: **{destino_mv or destino}** está a {passos} zonas; "
                                    f"o movimento que resta neste turno alcança {alcance_mv}."),
                        "snapshot": combat_snapshot()}
            msg = move_combatant(actor, destino, dash=passos > 1,
                                 sem_oportunidade=bool(eco.get("desengajado")))
            # Só marca o movimento como gasto se ele realmente aconteceu —
            # uma recusa (zona inexistente, longe demais) não pode queimar o
            # turno do jogador.
            if not msg.startswith(("Erro:", "Aviso:")):
                gastar = max(1, passos) - (1 if dash else 0)
                if gastar > 0 and not eco.get("movimento_usado"):
                    eco["movimento_usado"] = True
                    gastar -= 1
                if gastar > 0:
                    eco["movimento_extra"] = max(0, extra - gastar)
                # Sem movimento nenhum sobrando, a régua mostra "Movimento" gasto.
                if int(eco.get("movimento_extra", 0) or 0) == 0:
                    eco["movimento_usado"] = True
            elif dash:
                eco["acao_usada"] = False

        elif a == "defend":
            err = _use_slot(eco, "acao")  # Dodge = Ação
            if err:
                return {"ok": False, "message": err, "snapshot": combat_snapshot()}
            # A Esquiva escrevia "esquiva-se" e nada mudava. Agora os ataques
            # contra ele têm desvantagem até o próximo turno dele.
            ch_def = memory.campaign["characters"].get(memory.char_key(actor))
            if ch_def:
                dar_efeito_de_combate(ch_def, {"nome": "Esquiva", "desvantagem_contra_mim": True,
                                               "ate_turno_de": memory.char_key(actor)})
            _log_combat_event("defend", actor, "",
                              msg=f"{actor} defendeu-se (Esquivar — Ação)")
            msg = (f"{actor} esquiva-se (Dodge): ataques contra {actor} têm desvantagem "
                   f"até o próximo turno.")

        elif a == "offhand":
            # Duas armas: depois do Atacar com arma leve, a ação bônus ataca
            # com a outra arma leve (sem somar o modificador positivo no dano).
            if not eco.get("ataque_leve"):
                return {"ok": False, "message": (f"Erro: o ataque da outra mão vem depois de atacar com uma "
                                                 f"arma leve (adaga, espada curta, cimitarra...) neste turno."),
                        "snapshot": combat_snapshot()}
            _ch_oh = memory.campaign["characters"].get(memory.char_key(actor)) or {}
            _outra = (weapon or "").strip() or _arma_da_outra_mao(_ch_oh, eco["ataque_leve"])
            if not _outra or not _arma_leve(_outra):
                return {"ok": False, "message": (f"Erro: {actor} não tem outra arma leve de corpo a corpo "
                                                 f"para a outra mão."), "snapshot": combat_snapshot()}
            if not target:
                return {"ok": False, "message": "Erro: escolha o alvo do ataque da outra mão.",
                        "snapshot": combat_snapshot()}
            err = _use_slot(eco, "bonus")
            if err:
                return {"ok": False, "message": err, "snapshot": combat_snapshot()}
            msg = attack_roll(actor, target, _outra, 6, end_turn=False, _mao_inabil=True)
            if msg.startswith(("Erro:", "Aviso:")):
                eco["bonus_usada"] = False
                return {"ok": False, "message": msg, "snapshot": combat_snapshot()}
            eco["ataque_leve"] = ""
            msg = "Ataque com a outra mão (ação bônus):\n" + msg

        elif a in ("mount", "dismount"):
            # Montar e desmontar gastam o movimento.
            if eco.get("movimento_usado") and int(eco.get("movimento_extra", 0) or 0) <= 0:
                return {"ok": False, "message": f"Erro: {actor} já usou o movimento neste turno.",
                        "snapshot": combat_snapshot()}
            from rpg import manobras as _mb_m
            msg = _mb_m.montar(actor, (target or "").strip()) if a == "mount" else _mb_m.desmontar(actor)
            if msg.startswith("Erro:"):
                return {"ok": False, "message": msg, "snapshot": combat_snapshot()}
            eco["movimento_usado"] = True

        elif a == "light":
            # Acender ou apagar a tocha: interação com objeto, não gasta a Ação.
            _ch_l = memory.campaign["characters"].get(memory.char_key(actor)) or {}
            if not _tem_tocha(_ch_l):
                return {"ok": False, "message": f"Erro: {actor} não tem tocha nem lanterna.",
                        "snapshot": combat_snapshot()}
            _s_l = _ch_l.setdefault("sheet", {})
            _s_l["luz_acesa"] = not _s_l.get("luz_acesa")
            memory.save_campaign()
            return {"ok": True, "message": (f"{actor} acende a luz: a zona dele fica clara."
                                            if _s_l["luz_acesa"] else f"{actor} apaga a luz."),
                    "snapshot": combat_snapshot()}

        elif a == "cover":
            # Buscar cobertura: gasta o movimento, não a Ação.
            if eco.get("movimento_usado") and int(eco.get("movimento_extra", 0) or 0) <= 0:
                return {"ok": False, "message": f"Erro: {actor} já usou o movimento neste turno.",
                        "snapshot": combat_snapshot()}
            msg = _buscar_cobertura(actor)
            if msg.startswith("Erro:"):
                return {"ok": False, "message": msg, "snapshot": combat_snapshot()}
            eco["movimento_usado"] = True
            _log_combat_event("cover", actor, "", msg=msg)

        elif a == "nao_letal":
            # Golpe não letal: liga ou desliga, sem gastar nada do turno.
            _ch_nl = memory.campaign["characters"].get(memory.char_key(actor)) or {}
            _s_nl = _ch_nl.setdefault("sheet", {})
            _s_nl["nao_letal"] = _norm_txt(weapon or "") in ("sim", "true", "1", "ligar")
            memory.save_campaign()
            return {"ok": True,
                    "message": (f"{actor}: golpes corpo a corpo que derrubam passam a NOCAUTEAR (estável, não morre)."
                                if _s_nl["nao_letal"] else f"{actor}: golpes voltam a ser letais."),
                    "snapshot": combat_snapshot()}

        elif a in ("help", "hide", "grapple", "escape", "shove", "ready", "surrender"):
            # Ajudar, Esconder-se, Agarrar, Escapar, Empurrar, Preparar: todas
            # gastam a Ação (rpg/manobras.py).
            from rpg import manobras as _manobras
            err = _use_slot(eco, "acao")
            if err:
                return {"ok": False, "message": err, "snapshot": combat_snapshot()}
            alvo_m = (target or "").strip()
            if a == "help":
                msg = _manobras.ajudar(actor, alvo_m)
            elif a == "hide":
                msg = _manobras.esconder(actor)
            elif a == "grapple":
                msg = _manobras.agarrar(actor, alvo_m)
            elif a == "escape":
                msg = _manobras.escapar(actor)
            elif a == "shove":
                msg = _manobras.empurrar(actor, alvo_m, (weapon or "").strip())
            elif a == "surrender":
                msg = _manobras.pedir_rendicao(actor, alvo_m, (weapon or "").strip())
            else:
                msg = _manobras.preparar(actor, alvo_m, (weapon or "").strip())
            if msg.startswith(("Erro:", "Aviso:")):
                eco["acao_usada"] = False
                return {"ok": False, "message": msg, "snapshot": combat_snapshot()}
            _log_combat_event(a, actor, alvo_m, msg=msg.split("\n")[0])

        elif a == "flee":
            err = _use_slot(eco, "acao")
            if err:
                return {"ok": False, "message": err, "snapshot": combat_snapshot()}
            ch = memory.campaign["characters"].get(memory.char_key(actor))
            if not ch:
                return {"ok": False, "message": f"'{actor}' não encontrado.",
                        "snapshot": combat_snapshot()}
            # Ataque de oportunidade ANTES de marcar como fugido — senão o
            # motor considera o alvo fora de combate e ninguém reage. Quem
            # desengajou (Ação Ardilosa) sai sem provocar.
            oportunidade = ("" if eco.get("desengajado")
                            else _provoke_opportunity_attacks(actor, "fugir"))
            ch["status"] = "fugiu"
            _log_combat_event("flee", actor, "", msg=f"{actor} fugiu do combate")
            memory.save_campaign()
            msg = f"{actor} fugiu do combate!{oportunidade}"
            force_end = True

        elif a in ("pass", "end_turn"):
            # Encerrar o turno explicitamente (sem ação especial).
            _log_combat_event("pass", actor, "",
                              msg=f"{actor} encerrou o turno")
            msg = ""
            force_end = True

        else:
            return {"ok": False, "message": f"Ação '{action}' desconhecida.",
                    "snapshot": combat_snapshot()}

        # ── Decisão de AVANÇO de turno (regra 5e) ────────────────────────
        cs_now  = memory.campaign.get("combat_state", {}) or {}
        eco_now = cs_now.get("turn_economy", {}) or {}
        # Com golpe do Ataque Extra pendente o turno ainda não acabou.
        if force_end or (eco_now.get("acao_usada") and eco_now.get("bonus_usada")
                         and not eco_now.get("ataques_restantes")):
            msg += _auto_advance_turn(actor)
        if narrar:
            return {"ok": True, "message": msg, "narrar": True, "snapshot": combat_snapshot()}

    # FIM AUTOMÁTICO: na tela tática, se um lado foi todo derrotado/fugiu,
    # encerra o combate (o motor só encerrava se TODOS estavam fora).
    cs2 = memory.campaign.get("combat_state", {}) or {}
    if a != "end" and cs2.get("is_active"):
        order = cs2.get("initiative_order", []) or []
        party_alive = enemy_alive = party_seen = enemy_seen = False
        for nm in order:
            ch = memory.campaign["characters"].get(memory.char_key(nm))
            if not ch:
                continue
            # O aliado conta do lado do grupo: com ele no lado errado, matar
            # todos os inimigos não encerrava a luta.
            is_p = bool(memory.luta_com_o_grupo(ch))
            # DEFEATED (não OUT): uma criatura DORMINDO está incapacitada mas
            # ainda viva — não conta como derrotada, então não encerra a luta.
            out  = (ch.get("status", "") or "").lower() in DEFEATED_STATUSES
            if is_p:
                party_seen = True
                party_alive = party_alive or (not out)
            else:
                enemy_seen = True
                # Enfeitiçado ou dominado pelo grupo, ou rendido: não luta
                # mais contra vocês, e não é preciso matá-lo para a luta acabar.
                enemy_alive = enemy_alive or (not out and not poupado(ch))
        if (enemy_seen and not enemy_alive) or (party_seen and not party_alive):
            party_win = enemy_seen and not enemy_alive
            quem = "inimigos" if party_win else "o grupo"
            # Captura o RESULTADO antes de end_combat() limpar a ordem,
            # para a tela mostrar um painel de fim (sem fechar bruscamente).
            sobrev, caidos, poupados = [], [], []
            for nm in order:
                snp = _combatant_snapshot(nm)
                if not snp:
                    continue
                linha = {"name": snp["name"], "is_party": snp["is_party"],
                         "lado": snp["lado"],
                         "hp": snp["hp"], "hp_max": snp["hp_max"],
                         "status": snp["status"]}
                _pou = poupado(memory.campaign["characters"].get(memory.char_key(nm)))
                if _pou:
                    poupados.append(dict(linha, status=_pou))
                elif snp["status"].lower() in DEFEATED_STATUSES:
                    caidos.append(linha)
                else:
                    sobrev.append(linha)
            cs2["result"] = {
                "outcome":      "vitoria" if party_win else "derrota",
                "title":        "Vitória!" if party_win else "Derrota…",
                "sobreviventes": sobrev,
                "caidos":        caidos,
                "poupados":      poupados,
            }
            _log_combat_event("side_wiped", msg=f"Combate decidido — {quem} fora de ação")
            msg += "\n" + end_combat()

    # Se chegou até aqui, a ação foi aceita pelo motor. "" pode aparecer
    # na narrativa de um ataque que ERROU — ainda é sucesso da ação.
    # Recusas reais retornam ok=False mais cedo (early returns).
    return {"ok": True, "message": msg, "snapshot": combat_snapshot()}


def _fugir_em_grupo() -> str:
    """
    O grupo inteiro foge: cada um provoca os ataques de oportunidade de quem
    está colado nele (como a Fuga de um só), e a luta acaba como FUGA — sem XP
    nem saque. Quem cair no caminho fica para trás.
    """
    cs = memory.campaign.get("combat_state") or {}
    linhas, fugiram, ficaram = [], [], []
    for nm in list(cs.get("initiative_order") or []):
        ch = memory.campaign["characters"].get(memory.char_key(nm))
        if (not ch or not memory.luta_com_o_grupo(ch)
                or (ch.get("status") or "").lower() in DEFEATED_STATUSES):
            continue
        ops = _provoke_opportunity_attacks(ch["name"], "fugir")
        if ops:
            linhas.append(ops.strip())
        if (ch.get("status") or "").lower() in DEFEATED_STATUSES or int((ch.get("sheet") or {}).get("vida_atual", 0) or 0) <= 0:
            ficaram.append(ch["name"])
        else:
            fugiram.append(ch["name"])
    _log_combat_event("flee", "", "", msg=f"O grupo foge: {', '.join(fugiram) or 'ninguém'}")
    cs["result"] = {"outcome": "fuga", "title": "Fuga",
                    "sobreviventes": [{"name": n, "is_party": True, "status": "fugiu",
                                       "hp": int((memory.campaign["characters"][memory.char_key(n)].get("sheet") or {}).get("vida_atual", 0) or 0),
                                       "hp_max": int((memory.campaign["characters"][memory.char_key(n)].get("sheet") or {}).get("vida_max", 0) or 0)}
                                      for n in fugiram],
                    "caidos": [{"name": n, "is_party": True, "status": "ficou para trás", "hp": 0, "hp_max": 0}
                               for n in ficaram], "poupados": []}
    fim = end_combat()
    return ("O grupo foge da luta!" + ("".join(f"\n   {l}" for l in linhas))
            + (f"\n   Fugiram: {', '.join(fugiram)}." if fugiram else "")
            + (f"\n   Ficaram para trás: {', '.join(ficaram)}." if ficaram else "") + "\n" + fim)


def combat_recap_payload() -> str:
    """
    Texto compacto do combate (do log estruturado) para a LLM narrar a luta
    inteira de uma vez e gerar o saque. Usado quando o combate acaba na tela.
    """
    cs  = memory.campaign.get("combat_state", {}) or {}
    log = cs.get("log", []) or []
    linhas = []
    for ev in log:
        r = ev.get("round", "?")
        linhas.append(f"[R{r}] {ev.get('msg', ev.get('type',''))}")

    # Estado final vem do RESULTADO capturado (a ordem já foi limpa por
    # end_combat). Inclui quem caiu (alvos de saque) e quem sobreviveu.
    res = cs.get("result") or {}
    desfecho = res.get("outcome", "fim")
    finais = []
    for c in (res.get("sobreviventes", []) + res.get("caidos", []) + res.get("poupados", [])):
        lado = c.get("lado") or ("grupo" if c.get("is_party") else "inimigo")
        finais.append(f"{c.get('name')} [{lado}]: {c.get('status')} "
                      f"({c.get('hp')}/{c.get('hp_max')} HP)")

    if str(desfecho).lower() == "fuga":
        instrucao = (
            "Desfecho: FUGA. O grupo largou a luta e escapou (quem caiu no caminho ficou para trás). "
            "NÃO gere saque e NÃO conceda XP. Narre a fuga com base no log, e o que os inimigos fazem: "
            "perseguem, desistem, levam os caídos. Siga a história."
        )
    elif str(desfecho).lower() == "interrompido":
        instrucao = (
            "Desfecho: LUTA ENCERRADA PELO JOGADOR, com inimigos ainda de pé ("
            + ", ".join(res.get("de_pe") or []) + "). Decida o que isso foi — trégua, rendição, "
            "fuga, intervenção — de acordo com a cena e o log, e narre. XP e saque só se a cena justificar "
            "(inimigo que se rendeu e entregou o que tinha, por exemplo). Siga a história."
        )
    elif str(desfecho).lower() == "derrota":
        instrucao = (
            "Desfecho: DERROTA. Narre a queda do grupo de forma cinematográfica "
            "e contínua, com base no log abaixo. NÃO gere saque e NÃO conceda "
            "XP — perder a luta não dá recompensa nenhuma. Conduza as "
            "consequências (captura, resgate, quase-morte, fuga…) e siga a história."
        )
    else:
        instrucao = (
            "Desfecho: VITÓRIA. Narre a luta INTEIRA de forma cinematográfica e "
            "contínua (não turno a turno), com base no log abaixo. Ponha o SAQUE "
            "dos inimigos derrotados no chão com offer_loot(itens, gold=...): quem "
            "decide quem leva o quê é o jogador, na tela de saque; NÃO use "
            "add_item/modify_currency para o saque. Conceda XP a cada membro do "
            "grupo com grant_xp(). Depois siga a história."
        )
        if res.get("poupados"):
            instrucao += (
                " POUPADOS (" + ", ".join(f"{c.get('name')}: {c.get('status')}" for c in res["poupados"])
                + "): estão vivos, não são saque e contam para o XP da vitória. Narre a rendição (ou o "
                "encanto) e o que eles fazem agora — prisioneiros, informantes, fuga."
            )
    payload = (
        "[COMBATE RESOLVIDO NA TELA TÁTICA]\n"
        + instrucao + "\n\n"
        + "— Eventos —\n" + "\n".join(linhas)
        + "\n\n— Estado final —\n" + "\n".join(finais)
    )
    # Acknowledged: limpa o resultado para não reabrir o painel de fim.
    if isinstance(cs, dict):
        cs["result"] = None
    return payload


DND_TOOLS = [
    # O combate é jogado só na tela tática: as ferramentas de turno
    # (attack_roll, use_ability, next_turn, execute_npc_turn, move_combatant,
    # legendary_action, responder_reacao) não são do Mestre. A tela as chama
    # por combat_action; o Mestre abre a luta e narra o fim.
    suggest_encounter,
    learn_spell,
    roll_dice,
    create_character_sheet,
    get_character_sheet,
    get_combat_status,
    modify_hp,
    modify_mana,
    grant_temp_hp,
    make_skill_check,
    social_check,
    learn_ability,
    equip_item,
    unequip_item,
    apply_condition,
    remove_condition,
    reveal_defenses,
    haggle,
    modify_currency,
    roll_death_save,
    add_item,
    remove_item,
    list_custom_items,
    justify_custom_item,
    list_inventory,
    identify_item,
    attune_item,
    end_attunement,
    use_magic_item,
    choose_feat,
    apply_asi,
    set_feature_choice,
    grant_xp,
    short_rest,
    long_rest,
    use_hit_die,
    set_stat,
    # Sistema de Iniciativa (v3)
    roll_initiative,
    end_combat,
    # Recrutamento de NPC
    recruit_character,
    # Spawn de monstro com stats reais
    spawn_monster,
    # NPC strategy system
    set_npc_strategy,
    # Onda 3 — posicionamento por zonas
    set_battlefield,
    set_combat_side,
    describe_battlefield,
    # Onda 3 — chefes: recarga e ações lendárias
    set_recharge_ability,
    set_legendary_actions,
    set_legendary_resistance,
    set_lair_actions,
    set_cover,
    set_light,
    # Onda 4 — relógio, exaustão, carga e loja
    advance_time,
    get_world_time,
    add_exhaustion,
    remove_exhaustion,
    check_encumbrance,
    offer_rest,
    open_shop,
    list_shop,
    buy_item,
    sell_item,
    # Macro-tools (v4)
    resolve_saving_throw,
]

# Tela de saque: offer_loot mora em rpg/saque.py, que importa este módulo.
# O import vem depois de tudo definido, então não há ciclo pela metade.
from rpg.saque import offer_loot  # noqa: E402

DND_TOOLS.append(offer_loot)