"""
resolucao.py
Como o motor resolve cada habilidade e cada magia no combate.

POR QUE EXISTE
──────────────
Numa partida, o clérigo usou Taumaturgia e o ladino usou Ação Ardilosa: os
dois gastaram a Ação, o motor escreveu "usa X no Orc!" e nada aconteceu. A
pergunta do jogador foi a certa — "isso faz alguma coisa no combate?" — e a
resposta, medida com as fichas da campanha, era não para quase metade delas:

  • Taumaturgia, Linguagem dos Ladrões: sem regra nenhuma, gastavam a Ação;
  • Sacerdote de Guerra, Ação Ardilosa, Canalizar Divindade, Guiar Ataque,
    Fúria: o texto prometia um efeito que o motor não tinha;
  • Bênção, Escudo da Fé, Marca do Caçador: rolavam um número e o número não
    entrava em ataque nenhum;
  • Conjuração, Estilo de Combate, Ataque Furtivo: traços passivos que a tela
    deixava "usar" — o Ataque Furtivo até rolava 1d6 de dano solto.

Agora toda habilidade tem UMA resposta para "o que acontece quando eu uso?":

  motor           o motor resolve: dano, cura, condição, pool (já existia)
  efeito          a magia vira um efeito que os ataques, a CA, o dano e as
                  salvaguardas consultam (Bênção, Escudo da Fé, Fúria…)
  acao_de_classe  ação de classe com regra própria, implementada aqui
                  (Ação Ardilosa, Sacerdote de Guerra, Canalizar Divindade…)
  passiva         não se usa: ou o motor aplica sozinho (Ataque Furtivo,
                  Estilo de Combate) ou vale fora do combate (Especialização)
  narrativa       o motor não tem regra: gasta o que custa e o Mestre decide o
                  efeito (Taumaturgia, Luz, Mãos Mágicas…)

O jogador vê a resposta no cartão da habilidade, antes de gastar o turno.
"""

from __future__ import annotations

import random
import re
import unicodedata

from rpg import memory


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s.lower().replace("-", " ")).strip()


def _partes_do_nome(nome: str) -> list[str]:
    """
    "Canalizar Divindade (Guiar Ataque)" → ["canalizar divindade guiar ataque",
    "guiar ataque", "canalizar divindade"]: o efeito específico antes do
    recurso de onde ele sai.
    """
    n = norm(nome)
    m = re.match(r"^(.*?)\s*\((.*)\)\s*$", n)
    if not m:
        return [n]
    return [f"{m.group(1)} {m.group(2)}".strip(), m.group(2).strip(), m.group(1).strip()]


# ===========================================================================
# AÇÕES DE CLASSE COM REGRA PRÓPRIA
# ===========================================================================
# slot: o que gasta da economia do turno ("acao", "bonus" ou "livre").
# alvo: "inimigo" | "aliado" | "si" | "nenhum" — o que a tela pede.
# modos: a escolha que a ação exige (Ação Ardilosa: disparar, desengajar…).
# exige_ataque: só depois de usar a ação Atacar neste turno.
# uso: a chave do recurso que ela gasta, quando não é a do próprio nome.

MODOS_DE_MOVIMENTO = {
    "disparada": "Disparada: mais uma zona de movimento neste turno",
    "desengajar": "Desengajar: sair de zona sem ataque de oportunidade neste turno",
    "esconder": "Esconder: Furtividade contra a Percepção dos inimigos; escondido, o próximo ataque tem vantagem",
}

ACOES_DE_CLASSE: dict[str, dict] = {
    "acao ardilosa": {
        "slot": "bonus", "alvo": "nenhum",
        "modos": ["disparada", "desengajar", "esconder"],
        "texto": "Ação bônus: disparar (mais uma zona), desengajar (sem ataque de oportunidade) ou esconder-se (vantagem no próximo ataque).",
    },
    "sacerdote de guerra": {
        "slot": "bonus", "alvo": "inimigo", "exige_ataque": True,
        "texto": "Ação bônus, depois de usar a ação Atacar: mais um ataque com a arma. Usos = mod. de SAB por descanso longo.",
    },
    "expulsar mortos vivos": {
        "slot": "acao", "alvo": "nenhum", "uso": "canalizar divindade",
        "texto": "Mortos-vivos na sua zona e nas vizinhas fazem salvaguarda de SAB contra a sua CD; quem falha fica Amedrontado por 10 turnos.",
    },
    "expulsar o profano": {
        "slot": "acao", "alvo": "nenhum", "uso": "canalizar divindade",
        "texto": "Mortos-vivos e infernais na sua zona e nas vizinhas fazem salvaguarda de SAB contra a sua CD; quem falha fica Amedrontado por 10 turnos.",
    },
    "preservar a vida": {
        "slot": "acao", "alvo": "nenhum", "uso": "canalizar divindade",
        "texto": "Distribui 5 × nível de clérigo em cura entre os aliados da sua zona, os mais feridos primeiro, até metade da vida de cada um.",
    },
    "guiar ataque": {
        "slot": "livre", "alvo": "si", "uso": "canalizar divindade",
        "texto": "Sem gastar ação: +10 no próximo ataque deste turno.",
    },
    "furia": {
        "slot": "bonus", "alvo": "si",
        "texto": "Ação bônus: até o fim do combate, +2 de dano em ataque corpo a corpo de FOR (+3 no 9º, +4 no 16º) e resistência a dano contundente, cortante e perfurante.",
    },
    "ataque imprudente": {
        "slot": "livre", "alvo": "si",
        "texto": "Sem gastar ação: vantagem nos ataques corpo a corpo de FOR deste turno, e os ataques contra você têm vantagem até o seu próximo turno.",
    },
    "inspiracao de bardo": {
        "slot": "bonus", "alvo": "aliado",
        "texto": "Ação bônus: um aliado ganha um dado (d6; d8 no 5º, d10 no 10º, d12 no 15º) para somar ao próximo ataque, salvaguarda ou teste.",
    },
    "rajada de golpes": {
        "slot": "bonus", "alvo": "inimigo", "exige_ataque": True, "uso": "ki",
        "texto": "Ação bônus, depois de usar a ação Atacar, 1 ponto de ki: dois golpes desarmados.",
    },
    "defesa paciente": {
        "slot": "bonus", "alvo": "si", "uso": "ki",
        "texto": "Ação bônus, 1 ponto de ki: Esquivar (ataques contra você com desvantagem até o seu próximo turno).",
    },
    "passo do vento": {
        "slot": "bonus", "alvo": "nenhum", "uso": "ki", "modos": ["disparada", "desengajar"],
        "texto": "Ação bônus, 1 ponto de ki: disparar (mais uma zona) ou desengajar (sem ataque de oportunidade).",
    },
    "cura pelas maos": {
        "slot": "acao", "alvo": "aliado", "pool": True,
        "texto": "Toque: cura o que falta na vida do alvo, tirando da reserva de 5 × nível de paladino (volta no descanso longo).",
    },
}

APELIDOS_DE_ACAO = {
    "cunning action": "acao ardilosa",
    "war priest": "sacerdote de guerra",
    "turn undead": "expulsar mortos vivos",
    "expulsar mortos vivos": "expulsar mortos vivos",
    "turn the unholy": "expulsar o profano",
    "preserve life": "preservar a vida",
    "preservar vida": "preservar a vida",
    "guided strike": "guiar ataque",
    "golpe guiado": "guiar ataque",
    "rage": "furia",
    "reckless attack": "ataque imprudente",
    "movimento imprudente": "ataque imprudente",
    "bardic inspiration": "inspiracao de bardo",
    "flurry of blows": "rajada de golpes",
    "patient defense": "defesa paciente",
    "step of the wind": "passo do vento",
    "lay on hands": "cura pelas maos",
}


def acao_de_classe(nome: str, classe: str = "") -> tuple[str, dict] | tuple[None, None]:
    """(chave, ficha) da ação de classe com este nome, ou (None, None)."""
    for parte in _partes_do_nome(nome):
        chave = APELIDOS_DE_ACAO.get(parte, parte)
        if chave in ACOES_DE_CLASSE:
            return chave, ACOES_DE_CLASSE[chave]
    # O recurso sozinho: "Canalizar Divindade" é, para o clérigo, Expulsar
    # Mortos-Vivos; para o paladino, Expulsar o Profano.
    if norm(nome) in ("canalizar divindade", "channel divinity"):
        chave = "expulsar o profano" if norm(classe) == "paladino" else "expulsar mortos vivos"
        return chave, ACOES_DE_CLASSE[chave]
    return None, None


# ===========================================================================
# MAGIAS QUE VIRAM EFEITO
# ===========================================================================
# alvos: "si" | "aliado" | "aliados" (até `max`) | "inimigos" (até `max`,
#        com salvaguarda) | "marca" (efeito em quem conjura, contra o alvo) |
#        "area" (todos na zona do alvo, com salvaguarda — aliados inclusive)
# efeito: os campos de efeito de combate (ver tools_dnd, EFEITOS DE COMBATE).
# pv_temp: PV temporários na hora ("mod" = o modificador de conjuração).
EFEITOS_DE_MAGIA: dict[str, dict] = {
    "Bless": {"alvos": "aliados", "max": 3, "efeito": {"atk_dado": "1d4", "save_dado": "1d4"},
              "texto": "+1d4 nos ataques e nas salvaguardas de até 3 aliados"},
    "Bane": {"alvos": "inimigos", "max": 3, "save": "carisma",
             "efeito": {"atk_dado": "-1d4", "save_dado": "-1d4"},
             "texto": "-1d4 nos ataques e nas salvaguardas de até 3 inimigos que falharem em CAR"},
    "Shield of Faith": {"alvos": "aliado", "efeito": {"ca": 2}, "texto": "+2 de CA num aliado"},
    "Hunter's Mark": {"alvos": "marca", "efeito": {"dano_dado": "1d6"},
                      "texto": "+1d6 de dano nos seus ataques contra o alvo marcado"},
    "Hex": {"alvos": "marca", "efeito": {"dano_dado": "1d6", "dano_tipo": "necrotic"},
            "texto": "+1d6 necrótico nos seus ataques contra o alvo amaldiçoado"},
    "Divine Favor": {"alvos": "si", "efeito": {"dano_dado": "1d4", "dano_tipo": "radiant"},
                     "texto": "+1d4 radiante nos seus ataques com arma"},
    "Guidance": {"alvos": "aliado", "efeito": {"teste_dado": "1d4", "usos": 1},
                 "texto": "+1d4 no próximo teste de atributo de um aliado"},
    "Resistance": {"alvos": "aliado", "efeito": {"save_dado": "1d4", "usos": 1},
                   "texto": "+1d4 na próxima salvaguarda de um aliado"},
    "Blur": {"alvos": "si", "efeito": {"desvantagem_contra_mim": True},
             "texto": "ataques contra você com desvantagem"},
    "Faerie Fire": {"alvos": "area", "save": "destreza", "efeito": {"vantagem_contra_mim": True},
                    "texto": "quem estiver na zona do alvo e falhar em DES: ataques contra ele com vantagem (aliados inclusive)"},
    "Haste": {"alvos": "aliado", "efeito": {"ca": 2},
              "texto": "+2 de CA num aliado (a ação extra o Mestre arbitra)"},
    "Barkskin": {"alvos": "aliado", "efeito": {"ca_minima": 16}, "texto": "CA mínima 16 num aliado"},
    "Mage Armor": {"alvos": "aliado", "armadura_arcana": True,
                   "texto": "CA 13 + DES num aliado sem armadura"},
    "Stoneskin": {"alvos": "aliado", "efeito": {"resistencias": ["bludgeoning", "piercing", "slashing"]},
                  "texto": "resistência a dano contundente, cortante e perfurante num aliado"},
    "False Life": {"alvos": "si", "pv_temp": "1d4+4", "texto": "1d4+4 PV temporários"},
    "Heroism": {"alvos": "aliado", "pv_temp": "mod", "tira": ["amedrontado"],
                "texto": "PV temporários iguais ao seu modificador e fim do medo num aliado"},
    "Aid": {"alvos": "aliados", "max": 3, "pv_temp": "5",
            "texto": "+5 de vida (temporária) em até 3 aliados"},
    "Invisibility": {"alvos": "aliado", "condicao": "Invisível",
                     "texto": "um aliado fica Invisível (vantagem nos ataques dele)"},
    "Greater Invisibility": {"alvos": "aliado", "condicao": "Invisível",
                             "texto": "um aliado fica Invisível (vantagem nos ataques dele)"},
}

# Efeito que uma magia de DANO deixa no alvo atingido.
RIDERS_DE_MAGIA: dict[str, dict] = {
    "Guiding Bolt": {"nome": "Raio Guia", "vantagem_contra_mim": True, "usos": 1,
                     "ate_turno_de": "<conjurador>",
                     "texto": "o próximo ataque contra o alvo tem vantagem"},
    "Vicious Mockery": {"nome": "Zombaria Viciosa", "desvantagem_ataque": True, "usos": 1,
                        "ate_fim_turno_de": "<alvo>",
                        "texto": "o próximo ataque do alvo tem desvantagem"},
    "Shocking Grasp": {"sem_reacao": True, "texto": "o alvo perde a reação"},
}


# O que cada condição faz no motor, em uma linha (o cartão mostra). Condição
# que não está aqui não tem regra: a magia que só a aplica é narrativa.
TEXTO_DA_CONDICAO = {
    "paralisado": "não age, ataques contra ele têm vantagem e crítico de perto",
    "atordoado": "não age e ataques contra ele têm vantagem",
    "incapacitado": "não age",
    "inconsciente": "não age, ataques contra ele têm vantagem e crítico de perto",
    "petrificado": "não age e ataques contra ele têm vantagem",
    "caído": "ataca com desvantagem e ataques de perto contra ele têm vantagem",
    "cego": "ataca com desvantagem e ataques contra ele têm vantagem",
    "amedrontado": "ataca com desvantagem",
    "envenenado": "ataca com desvantagem",
    "contido": "não sai da zona, ataca com desvantagem e ataques contra ele têm vantagem",
    "imobilizado": "não sai da zona, ataca com desvantagem e ataques contra ele têm vantagem",
    "agarrado": "não sai da zona",
    "aprisionado": "não sai da zona",
    "lentidão": "ataca com desvantagem",
    "banido": "some da luta: não age e ninguém o alcança",
    "confuso": "o d10 decide o turno: não faz nada, vaga ou ataca quem estiver perto",
    "amaldiçoado": "ataca com desvantagem quem o amaldiçoou",
}

# Aplicam "Enfeitiçado" no compêndio, mas o efeito é uma ordem, um transe ou
# uma calma que só o Mestre sabe narrar. O motor rola o teste; o Mestre narra.
NARRATIVAS_COM_TESTE = {"Suggestion", "Mass Suggestion", "Enthrall", "Calm Emotions",
                        "Compulsion", "Geas", "Polymorph", "True Polymorph",
                        "Gust of Wind", "Divine Word"}


def _condicao_da_magia(hab: dict, m: dict) -> str:
    from rpg import tools_dnd as td
    ctrl = td._get_control_effect(hab)
    return norm((ctrl or {}).get("condition") or m.get("condicao") or "")


def _magia_srd(hab: dict) -> dict | None:
    from rpg import compendio
    for chave in (hab.get("nome_srd"), hab.get("nome")):
        if chave:
            m = compendio.magia(chave)
            if m:
                return m
    return None


def efeito_de_magia(hab: dict) -> tuple[str, dict] | tuple[None, None]:
    m = _magia_srd(hab)
    if m and m["nome_srd"] in EFEITOS_DE_MAGIA:
        return m["nome_srd"], EFEITOS_DE_MAGIA[m["nome_srd"]]
    return None, None


def rider_de_magia(hab: dict) -> dict | None:
    m = _magia_srd(hab)
    return RIDERS_DE_MAGIA.get(m["nome_srd"]) if m else None


# ===========================================================================
# PASSIVAS
# ===========================================================================
# O motor aplica sozinho, nos ataques e na CA. A tela mostra como passiva e o
# motor recusa "usar".
PASSIVAS_NO_MOTOR = {
    "ataque furtivo": "o motor soma o Ataque Furtivo uma vez por turno, com vantagem ou com um aliado ao lado do alvo",
    "sneak attack": "o motor soma o Ataque Furtivo uma vez por turno, com vantagem ou com um aliado ao lado do alvo",
    "estilo de combate": "o motor aplica o estilo escolhido nos ataques e na CA",
    "fighting style": "o motor aplica o estilo escolhido nos ataques e na CA",
    "estilo de combate adicional": "o motor aplica o estilo escolhido nos ataques e na CA",
    "inimigo favorecido": "o motor soma +2 de dano contra o tipo escolhido",
    "golpe divino": "o motor soma o dano extra uma vez por turno no ataque corpo a corpo",
    "divine strike": "o motor soma o dano extra uma vez por turno no ataque corpo a corpo",
    "critico aprimorado": "o motor considera crítico a partir do 19",
    "critico superior": "o motor considera crítico a partir do 18",
    "ataque extra": "o motor libera mais ataques na mesma ação Atacar",
    "extra attack": "o motor libera mais ataques na mesma ação Atacar",
    "ataque extra adicional": "o motor libera mais ataques na mesma ação Atacar",
    "defesa sem armadura": "o motor calcula a CA sem armadura",
    "unarmored defense": "o motor calcula a CA sem armadura",
}

# Ativas que o motor já resolvia por caminho próprio (não passam por aqui).
MOTOR_PROPRIO = {"segunda folego", "segundo folego", "second wind", "surto de acao", "action surge"}

# Palavras que fazem de uma descrição de característica uma ATIVA (gasta algo).
_ATIVA_RE = re.compile(r"^\s*(acao|reacao|1 vez|uma vez)|\b(acao bonus|como acao|usos?\b|por descanso|"
                       r"\d+ pontos? de|gasta|reacao)", re.I)


def _descricao_de_jogo(nome: str) -> str:
    from rpg import tools_dnd as td
    d = getattr(td, "CLASS_FEATURE_DESCS", {}).get(nome)
    return (d or {}).get("descricao", "") if isinstance(d, dict) else ""


def tipo_de_caracteristica(nome: str, descricao: str = "", classe: str = "") -> tuple[str, str]:
    """
    (tipo, texto) de uma característica de classe pelo nome — a usada nas
    fichas que o jogo cria. Cobre os 326 nomes do jogo (teste em
    test_resolucao.py) e qualquer outro pelo texto.
    """
    from rpg import compendio
    chave, acao = acao_de_classe(nome, classe)
    if acao:
        return "acao_de_classe", acao["texto"]
    for parte in _partes_do_nome(nome):
        if parte in PASSIVAS_NO_MOTOR:
            return "passiva", "Passiva: " + PASSIVAS_NO_MOTOR[parte] + "."
        if parte in MOTOR_PROPRIO:
            return "motor", ""
    c = compendio.caracteristica(nome, classe, exato=True)
    if c and c.get("tipo") == "passiva":
        return "passiva", "Passiva: vale sozinha, sem gastar ação."
    texto = norm(descricao or _descricao_de_jogo(nome))
    if c and c.get("tipo") in ("acao", "bonus", "reacao", "livre"):
        return "narrativa", _TEXTO_NARRATIVA
    if texto and _ATIVA_RE.search(texto):
        return "narrativa", _TEXTO_NARRATIVA
    return "passiva", "Passiva: vale sozinha, sem gastar ação."


_TEXTO_NARRATIVA = ("Sem regra no motor: gasta o que custa e o Mestre decide o efeito "
                    "— descreva o que você quer fazer.")


# ===========================================================================
# A RESPOSTA PARA UMA HABILIDADE DA FICHA
# ===========================================================================

def como_resolve(hab: dict, char: dict | None = None) -> dict:
    """
    {tipo, texto, slot, alvo, modos} para uma habilidade da ficha.

    slot: "acao" | "bonus" | "livre" | "" (quando quem decide é o caminho de
    sempre, _ability_action_type).
    """
    from rpg import tools_dnd as td
    hab = hab or {}
    nome = hab.get("nome", "")
    classe = ((char or {}).get("sheet") or {}).get("classe", "")
    saida = {"tipo": "motor", "texto": "", "slot": "", "alvo": "", "modos": []}

    chave, acao = acao_de_classe(nome, classe)
    if acao:
        saida.update(tipo="acao_de_classe", texto=acao["texto"], slot=acao["slot"],
                     alvo=acao["alvo"], modos=list(acao.get("modos") or []), chave=chave)
        return saida

    m = _magia_srd(hab)
    if m:
        from rpg import encantos
        if encantos.do_encanto(m["nome_srd"]):
            cfg = encantos.do_encanto(m["nome_srd"])
            if cfg["tipo"] == "dominado":
                texto = ("O motor aplica: salvaguarda de SAB; se falhar, fica Dominado enquanto "
                         "durar a concentração — não ataca o seu lado e obedece às suas ordens "
                         "(o Mestre narra). Funciona fora do combate.")
            else:
                texto = (f"O motor aplica: salvaguarda de SAB (com vantagem se ele está lutando "
                         f"contra vocês); se falhar, fica Enfeitiçado por {cfg['horas']}h — não "
                         f"ataca você, trata você como amigo, e quebra se o grupo o ferir. "
                         f"Funciona fora do combate.")
            saida.update(tipo="efeito", texto=texto)
            return saida
        chave_ef, ef = efeito_de_magia(hab)
        if ef:
            saida.update(tipo="efeito", texto="O motor aplica: " + ef["texto"]
                         + (", enquanto durar a concentração" if m.get("concentracao") else "") + ".")
            return saida
        efeito = m.get("efeito")
        if efeito in ("dano", "cura", "pool") and (m.get("dado") or efeito == "pool"):
            rider = RIDERS_DE_MAGIA.get(m["nome_srd"])
            if rider:
                saida["texto"] = "Além do dano: " + rider["texto"] + "."
            return saida
        cond = _condicao_da_magia(hab, m)
        textos = {norm(k): (k, v) for k, v in TEXTO_DA_CONDICAO.items()}
        if (efeito == "condicao" and m["nome_srd"] not in NARRATIVAS_COM_TESTE
                and cond in textos):
            nome_cond, texto_cond = textos[cond]
            saida["texto"] = (f"O motor aplica: {nome_cond.capitalize()} — {texto_cond}"
                              + (", enquanto durar a concentração" if m.get("concentracao") else "")
                              + ".")
            return saida
        saida.update(tipo="narrativa", texto=_TEXTO_NARRATIVA
                     + (" O motor rola a salvaguarda do alvo." if m.get("salvaguarda") else ""))
        return saida

    # Característica de classe ou habilidade feita pelo mestre.
    for parte in _partes_do_nome(nome):
        if parte in PASSIVAS_NO_MOTOR:
            saida.update(tipo="passiva", texto="Passiva: " + PASSIVAS_NO_MOTOR[parte] + ".")
            return saida
        if parte in MOTOR_PROPRIO:
            return saida
    if td._e_traco_passivo(nome):
        saida.update(tipo="passiva", texto="Passiva: vale sozinha, sem gastar ação.")
        return saida
    # Habilidade com dado de dano ou cura, ou com condição conhecida: o motor
    # resolve pelo caminho de sempre — inclusive a magia que o mestre inventou.
    efeito = td.efeito_do_dado(hab)
    if efeito in ("dano", "cura") and td.dado_efetivo(hab, char):
        return saida
    if td._get_control_effect(hab):
        return saida
    if td._ability_is_passive(hab):
        saida.update(tipo="passiva", texto="Passiva: vale sozinha, sem gastar ação.")
        return saida
    # Pelo texto, só vira passiva o que não custa nada: com dado, mana ou
    # recarga (o Sopro do dragão) é algo que se USA, mesmo com descrição curta.
    sem_custo = (not hab.get("dado") and not int(hab.get("custo_mana", 0) or 0)
                 and not (((char or {}).get("sheet") or {}).get("recargas") or {}).get(nome))
    if sem_custo:
        tipo, texto = tipo_de_caracteristica(nome, hab.get("descricao", ""), classe)
        if tipo == "passiva":
            saida.update(tipo="passiva", texto=texto)
            return saida
    saida.update(tipo="narrativa", texto=_TEXTO_NARRATIVA)
    return saida


# ===========================================================================
# EXECUÇÃO
# ===========================================================================

def _eco() -> dict:
    cs = memory.campaign.get("combat_state") or {}
    return cs.setdefault("turn_economy", {"acao_usada": False, "bonus_usada": False})


def _char(nome: str) -> dict | None:
    return memory.campaign.get("characters", {}).get(memory.char_key(nome or ""))


def _combatentes_vivos() -> list[dict]:
    from rpg import tools_dnd as td
    cs = memory.campaign.get("combat_state") or {}
    saida = []
    for nm in cs.get("initiative_order") or []:
        ch = _char(nm)
        if ch and ch.get("sheet") and (ch.get("status") or "").lower() not in td.OUT_OF_COMBAT_STATUSES:
            saida.append(ch)
    return saida


def _mesmo_lado(a: dict, b: dict) -> bool:
    return memory.luta_com_o_grupo(a) == memory.luta_com_o_grupo(b)


def _perto(a: dict, b: dict, passos: int = 0) -> bool:
    """Na mesma zona (ou a até `passos` zonas). Sem zonas, todos estão perto."""
    from rpg import tools_dnd as td
    d = td._distancia(a.get("name", ""), b.get("name", ""))
    return d is None or d <= passos


def _cd(char: dict) -> int:
    from rpg import tools_dnd as td
    s = char.get("sheet") or {}
    conj = td._conjuracao(s) or {}
    if conj.get("cd"):
        return int(conj["cd"])
    prof = int(s.get("proficiencia", 2) or 2)
    attr = "carisma" if norm(s.get("classe", "")) == "paladino" else "sabedoria"
    return 8 + prof + td._modifier(int(s.get(attr, 10) or 10))


def _mod(char: dict, atributo: str) -> int:
    from rpg import tools_dnd as td
    return td._modifier(int(((char.get("sheet") or {}).get(atributo, 10)) or 10))


_MORTOS_VIVOS = ("undead", "morto vivo", "mortos vivos", "zombie", "zumbi", "skeleton", "esqueleto",
                 "ghoul", "carnical", "vampir", "wight", "wraith", "espectro", "specter", "ghost",
                 "fantasma", "lich", "mummy", "mumia", "aparicao", "inumano")
_INFERNAIS = ("fiend", "infernal", "demon", "demonio", "devil", "diabo", "diabrete")


def _e_do_tipo(ch: dict, palavras) -> bool:
    s = ch.get("sheet") or {}
    texto = norm(" ".join(str(x or "") for x in (s.get("tipo"), s.get("raca"), ch.get("description"),
                                                   ch.get("name"))))
    return any(re.search(rf"\b{re.escape(p)}", texto) for p in palavras)


def validar(char: dict, hab: dict, alvo: str, modo: str) -> str:
    """Recusa ANTES de gastar qualquer coisa. '' quando pode."""
    classe = (char.get("sheet") or {}).get("classe", "")
    chave, acao = acao_de_classe(hab.get("nome", ""), classe)
    if acao:
        if acao.get("modos") and modo not in acao["modos"]:
            return (f"Aviso: {hab['nome']} pede uma escolha: "
                    + ", ".join(acao["modos"]) + ". Nada foi gasto.")
        if acao.get("exige_ataque") and not _eco().get("atacou"):
            return (f"Aviso: {hab['nome']} só vale depois de usar a ação Atacar neste "
                    f"turno. Ataque primeiro. Nada foi gasto.")
        if acao["alvo"] in ("inimigo", "aliado") and not _char(alvo):
            return f"Aviso: escolha o alvo de {hab['nome']}. Nada foi gasto."
        if acao["alvo"] == "inimigo" and _char(alvo) and _mesmo_lado(char, _char(alvo)):
            return f"Aviso: {hab['nome']} é contra um inimigo. Nada foi gasto."
        if chave in ("expulsar mortos vivos", "expulsar o profano"):
            tipos = _MORTOS_VIVOS + (_INFERNAIS if chave == "expulsar o profano" else ())
            if not [c for c in _combatentes_vivos()
                    if not _mesmo_lado(char, c) and _e_do_tipo(c, tipos) and _perto(char, c, 1)]:
                return (f"Aviso: nenhum {'morto-vivo ou infernal' if chave == 'expulsar o profano' else 'morto-vivo'} "
                        f"ao alcance (na sua zona ou nas vizinhas). Canalizar Divindade não foi gasto.")
        if chave == "cura pelas maos":
            from rpg import tools_dnd as td
            if (td.usos_restantes(char, "cura pelas maos") or 0) <= 0:
                return "Aviso: a reserva de Cura pelas Mãos acabou. Volta no descanso longo."
            st = (_char(alvo) or {}).get("sheet") or {}
            if int(st.get("vida_atual", 0) or 0) >= int(st.get("vida_max", 0) or 0):
                return f"Aviso: {alvo} já está com a vida cheia. Nada foi gasto."
        return ""
    m = _magia_srd(hab) or {}
    from rpg import encantos
    if encantos.do_encanto(m.get("nome_srd", "")):
        if not _char(alvo):
            if (alvo or "").strip():
                return f"Aviso: {alvo} não está entre os personagens da história. Nada foi gasto."
            return f"Aviso: escolha quem {m.get('nome', hab.get('nome'))} vai enfeitiçar. Nada foi gasto."
        if not encantos.tipo_combina(_char(alvo), m["nome_srd"]):
            return (f"Aviso: {m.get('nome')} não afeta {alvo}: "
                    f"{'só humanoides' if m['nome_srd'] == 'Charm Person' else 'só bestas'}. "
                    f"Nada foi gasto.")
        return ""
    _, ef = efeito_de_magia(hab)
    if ef and ef["alvos"] in ("marca", "inimigos", "area") and not _char(alvo):
        return f"Aviso: escolha o alvo de {hab['nome']}. Nada foi gasto."
    # A regra deixa abençoar quem quiser: a tela oferece os aliados primeiro,
    # e o motor não recusa o que o SRD permite.
    return ""


def executar(char: dict, hab: dict, alvo: str, modo: str) -> str:
    """Resolve uma habilidade `efeito`, `acao_de_classe` ou `narrativa`."""
    info = como_resolve(hab, char)
    if info["tipo"] == "acao_de_classe":
        return _ACOES[info["chave"]](char, hab, alvo, modo)
    m = _magia_srd(hab) or {}
    if info["tipo"] == "efeito":
        from rpg import encantos
        if encantos.do_encanto(m.get("nome_srd", "")):
            return encantos.conjurar(char, hab, alvo, m["nome_srd"], m.get("nome") or hab.get("nome", ""))
        return aplicar_magia(char, hab, alvo)
    if info["tipo"] == "narrativa":
        teste = _teste_da_narrativa(char, m, alvo)
        return (f"\n   Sem regra no motor para {hab.get('nome', '')}: o Mestre narra o efeito.{teste}"
                f"\n   (Mestre: decida o efeito pela descrição, pelo resultado do teste e pelo "
                f"que o jogador pediu.)")
    return ""


def _teste_da_narrativa(char: dict, m: dict, alvo_nome: str) -> str:
    """
    Sugestão, Missão, Acalmar Emoções: o efeito é do Mestre, mas o teste não
    precisa ser — o motor rola a salvaguarda e o Mestre narra a partir dela.
    """
    from rpg import tools_dnd as td
    alvo = _char(alvo_nome)
    if not m.get("salvaguarda") or not alvo:
        return ""
    cd = _cd(char)
    if alvo.get("sheet"):
        passou, linha = td._rolar_salvaguarda(alvo, m["salvaguarda"], cd)
    else:
        d20 = random.randint(1, 20)
        passou, linha = d20 >= cd, f"salvaguarda: {d20}+0 = {d20} vs CD {cd}"
    return (f"\n   {alvo.get('name')}: {linha} — "
            + ("passou: a magia não pega." if passou else "falhou: o efeito vale."))


# ── Magias de efeito ─────────────────────────────────────────────────────────

def _alvos_da_magia(char: dict, ef: dict, alvo_nome: str) -> list[dict]:
    alvo = _char(alvo_nome)
    tipo = ef["alvos"]
    if tipo in ("si", "marca"):
        return [char]
    if tipo == "aliado":
        return [alvo or char]
    if tipo == "aliados":
        lista = []
        for c in [alvo, char] + _combatentes_vivos():
            if c and _mesmo_lado(char, c) and c not in lista:
                lista.append(c)
        perto = [c for c in lista if c is alvo or c is char or _perto(char, c)]
        resto = [c for c in lista if c not in perto]
        return (perto + resto)[:int(ef.get("max", 1))]
    if tipo == "inimigos":
        lista = [alvo] if alvo else []
        for c in _combatentes_vivos():
            if c not in lista and not _mesmo_lado(char, c) and alvo and _perto(alvo, c):
                lista.append(c)
        return lista[:int(ef.get("max", 1))]
    if tipo == "area":
        if not alvo:
            return []
        return [c for c in _combatentes_vivos() if _perto(alvo, c)]
    return []


def aplicar_magia(char: dict, hab: dict, alvo_nome: str) -> str:
    from rpg import tools_dnd as td
    chave, ef = efeito_de_magia(hab)
    m = _magia_srd(hab) or {}
    nome_pt = m.get("nome") or hab.get("nome", "")
    alvos = _alvos_da_magia(char, ef, alvo_nome)
    if not alvos:
        return f"\n   Ninguém ao alcance de {nome_pt}."
    linhas = []
    cd = _cd(char)
    for a in alvos:
        if ef.get("save"):
            passou, linha = td._rolar_salvaguarda(a, ef["save"], cd)
            if passou:
                linhas.append(f"{a['name']}: {linha} — resistiu")
                continue
            linhas.append(f"{a['name']}: {linha} — falhou")
        efeito = dict(ef.get("efeito") or {})
        if ef.get("armadura_arcana"):
            efeito["ca_minima"] = 13 + _mod(a, "destreza")
        if efeito:
            efeito["nome"] = nome_pt
            efeito["origem"] = char.get("name", "")
            if ef["alvos"] == "marca":
                efeito["contra"] = memory.char_key(alvo_nome)
            if m.get("concentracao"):
                efeito["concentracao_de"] = memory.char_key(char.get("name", ""))
                efeito["magia"] = hab.get("nome", "")
            td.dar_efeito_de_combate(a, efeito)
        if ef.get("pv_temp"):
            expr = ef["pv_temp"]
            if expr == "mod":
                attr = td._atributo_de_conjuracao(char.get("sheet") or {}) or "sabedoria"
                valor = max(1, _mod(char, attr))
            else:
                valor, _ = td._rolar_expr(expr)
            st = a.setdefault("sheet", {})
            st["vida_temp"] = max(int(st.get("vida_temp", 0) or 0), valor)
            linhas.append(f"{a['name']}: {st['vida_temp']} PV temporários")
        if ef.get("condicao"):
            conds = a.setdefault("sheet", {}).setdefault("condicoes", [])
            if not any(norm(c.get("nome", "") if isinstance(c, dict) else c) == norm(ef["condicao"])
                       for c in conds):
                conds.append({"nome": ef["condicao"], "duracao": None})
        for tirar in ef.get("tira") or []:
            st = a.setdefault("sheet", {})
            st["condicoes"] = [c for c in (st.get("condicoes") or [])
                               if norm(c.get("nome", "") if isinstance(c, dict) else c) != norm(tirar)]
        if ef["alvos"] == "marca":
            linhas.append(f"{char['name']} marca {alvo_nome}")
        elif not ef.get("save"):
            linhas.append(f"{a['name']}")
    return (f"\n   {nome_pt}: {ef['texto']}."
            + "".join(f"\n   • {l}" for l in linhas))


def aplicar_rider(char: dict, hab: dict, alvo: dict) -> str:
    """O efeito que a magia de dano deixa no alvo atingido (Raio Guia…)."""
    from rpg import tools_dnd as td
    rider = rider_de_magia(hab)
    if not rider or not alvo:
        return ""
    if rider.get("sem_reacao"):
        cs = memory.campaign.get("combat_state") or {}
        alvo.setdefault("sheet", {})["reacao_rodada"] = int(cs.get("round", 1) or 1)
        return f"\n   {alvo['name']} perde a reação até o próximo turno."
    efeito = {k: v for k, v in rider.items() if k != "texto"}
    for campo in ("ate_turno_de", "ate_fim_turno_de"):
        if efeito.get(campo) == "<conjurador>":
            efeito[campo] = memory.char_key(char.get("name", ""))
        elif efeito.get(campo) == "<alvo>":
            efeito[campo] = memory.char_key(alvo.get("name", ""))
    td.dar_efeito_de_combate(alvo, efeito)
    return f"\n   {rider['nome']}: {rider['texto']}."


# ── Ações de classe ──────────────────────────────────────────────────────────

def _acao_de_movimento(char: dict, modo: str, nome: str) -> str:
    from rpg import tools_dnd as td
    eco = _eco()
    if modo == "disparada":
        eco["movimento_extra"] = int(eco.get("movimento_extra", 0) or 0) + 1
        return f"\n   {nome}: Disparada — mais uma zona de movimento neste turno."
    if modo == "desengajar":
        eco["desengajado"] = True
        return f"\n   {nome}: Desengajar — sair de zona não provoca ataque de oportunidade neste turno."
    # Esconder: Furtividade contra a melhor Percepção passiva dos inimigos.
    s = char.get("sheet") or {}
    bonus = _mod(char, "destreza")
    if td._proficiente_na_pericia(s, "furtividade"):
        bonus += int(s.get("proficiencia", 2) or 2)
    d20 = random.randint(1, 20)
    total = d20 + bonus
    inimigos = [c for c in _combatentes_vivos() if not _mesmo_lado(char, c)]
    melhor = max([10 + _mod(c, "sabedoria") for c in inimigos] or [10])
    if total >= melhor:
        conds = s.setdefault("condicoes", [])
        if not any(norm(c.get("nome", "") if isinstance(c, dict) else c) == "escondido" for c in conds):
            conds.append({"nome": "Escondido", "duracao": None})
        return (f"\n   {nome}: Furtividade {d20}{bonus:+d} = {total} contra Percepção passiva "
                f"{melhor} — ESCONDIDO. O próximo ataque tem vantagem.")
    return (f"\n   {nome}: Furtividade {d20}{bonus:+d} = {total} contra Percepção passiva "
            f"{melhor} — foi visto.")


def _acao_ardilosa(char, hab, alvo, modo):
    return _acao_de_movimento(char, modo, "Ação Ardilosa")


def _passo_do_vento(char, hab, alvo, modo):
    return _acao_de_movimento(char, modo, "Passo do Vento")


def _arma_de(char: dict) -> str:
    return (((char.get("sheet") or {}).get("equipamentos") or {}).get("arma_principal")
            or "ataque desarmado")


def _sacerdote_de_guerra(char, hab, alvo, modo):
    from rpg import tools_dnd as td
    return "\n" + td.attack_roll(char["name"], alvo, _arma_de(char), 6,
                                 end_turn=False, _skip_turn_check=True)


def _dado_de_artes_marciais(char: dict) -> int:
    nivel = int(((char.get("sheet") or {}).get("nivel", 1)) or 1)
    return 10 if nivel >= 17 else 8 if nivel >= 11 else 6 if nivel >= 5 else 4


def _rajada_de_golpes(char, hab, alvo, modo):
    from rpg import tools_dnd as td
    attr = "destreza" if _mod(char, "destreza") >= _mod(char, "forca") else "forca"
    saida = ""
    for _ in range(2):
        alvo_ch = _char(alvo)
        if not alvo_ch or int((alvo_ch.get("sheet") or {}).get("vida_atual", 0) or 0) <= 0:
            break
        saida += "\n" + td.attack_roll(char["name"], alvo, "ataque desarmado",
                                       _dado_de_artes_marciais(char), attack_attribute=attr,
                                       end_turn=False, _skip_turn_check=True)
    return saida


def _esquivar(char: dict, nome: str) -> str:
    from rpg import tools_dnd as td
    td.dar_efeito_de_combate(char, {"nome": "Esquiva", "desvantagem_contra_mim": True,
                                    "ate_turno_de": memory.char_key(char.get("name", ""))})
    return f"\n   {nome}: ataques contra {char['name']} têm desvantagem até o próximo turno dele."


def _defesa_paciente(char, hab, alvo, modo):
    return _esquivar(char, "Defesa Paciente")


def _expulsar(char, hab, alvo, modo, tipos, rotulo):
    from rpg import tools_dnd as td
    cd = _cd(char)
    linhas = []
    for c in _combatentes_vivos():
        if _mesmo_lado(char, c) or not _e_do_tipo(c, tipos) or not _perto(char, c, 1):
            continue
        passou, linha = td._rolar_salvaguarda(c, "sabedoria", cd)
        if passou:
            linhas.append(f"{c['name']}: {linha} — resiste")
            continue
        conds = c.setdefault("sheet", {}).setdefault("condicoes", [])
        conds[:] = [x for x in conds if norm(x.get("nome", "") if isinstance(x, dict) else x) != "amedrontado"]
        conds.append({"nome": "Amedrontado", "duracao": 10})
        linhas.append(f"{c['name']}: {linha} — EXPULSO (Amedrontado por 10 turnos)")
    return f"\n   {rotulo} (CD {cd}):" + "".join(f"\n   • {l}" for l in linhas)


def _expulsar_mortos_vivos(char, hab, alvo, modo):
    return _expulsar(char, hab, alvo, modo, _MORTOS_VIVOS, "Expulsar Mortos-Vivos")


def _expulsar_o_profano(char, hab, alvo, modo):
    return _expulsar(char, hab, alvo, modo, _MORTOS_VIVOS + _INFERNAIS, "Expulsar o Profano")


def _preservar_a_vida(char, hab, alvo, modo):
    nivel = int(((char.get("sheet") or {}).get("nivel", 1)) or 1)
    reserva = 5 * nivel
    aliados = [c for c in _combatentes_vivos() + [char]
               if _mesmo_lado(char, c) and _perto(char, c)]
    vistos, lista = set(), []
    for c in aliados:
        if id(c) not in vistos:
            vistos.add(id(c))
            lista.append(c)
    lista.sort(key=lambda c: (c["sheet"].get("vida_atual", 0) or 0) / max(1, c["sheet"].get("vida_max", 1) or 1))
    linhas = []
    for c in lista:
        st = c["sheet"]
        teto = int(st.get("vida_max", 0) or 0) // 2
        falta = max(0, teto - int(st.get("vida_atual", 0) or 0))
        cura = min(falta, reserva)
        if cura <= 0:
            continue
        reserva -= cura
        antes = int(st.get("vida_atual", 0) or 0)
        st["vida_atual"] = antes + cura
        if antes == 0 and (c.get("status") or "").lower() in ("inconsciente", "estabilizado"):
            c["status"] = "vivo"
        linhas.append(f"{c['name']}: +{cura} ({antes} → {st['vida_atual']}/{st.get('vida_max')})")
    if not linhas:
        return "\n   Preservar a Vida: ninguém na sua zona está abaixo da metade da vida."
    return (f"\n   Preservar a Vida ({5 * nivel} de cura, sobraram {reserva}):"
            + "".join(f"\n   • {l}" for l in linhas))


def _guiar_ataque(char, hab, alvo, modo):
    from rpg import tools_dnd as td
    td.dar_efeito_de_combate(char, {"nome": "Guiar Ataque", "atk_fixo": 10, "usos": 1,
                                    "ate_turno_de": memory.char_key(char.get("name", ""))})
    return "\n   Guiar Ataque: +10 no próximo ataque deste turno."


def _furia(char, hab, alvo, modo):
    from rpg import tools_dnd as td
    nivel = int(((char.get("sheet") or {}).get("nivel", 1)) or 1)
    extra = 4 if nivel >= 16 else 3 if nivel >= 9 else 2
    td.dar_efeito_de_combate(char, {"nome": "Fúria", "dano_fixo_for": extra,
                                    "resistencias": ["bludgeoning", "piercing", "slashing"]})
    return (f"\n   Fúria: +{extra} de dano nos ataques corpo a corpo de FOR e resistência a "
            f"dano contundente, cortante e perfurante até o fim do combate.")


def _ataque_imprudente(char, hab, alvo, modo):
    from rpg import tools_dnd as td
    chave = memory.char_key(char.get("name", ""))
    td.dar_efeito_de_combate(char, {"nome": "Ataque Imprudente", "vantagem_ataque_for": True,
                                    "ate_turno_de": chave})
    td.dar_efeito_de_combate(char, {"nome": "Exposto (Ataque Imprudente)",
                                    "vantagem_contra_mim": True, "ate_turno_de": chave})
    return ("\n   Ataque Imprudente: vantagem nos ataques corpo a corpo de FOR neste turno; "
            "ataques contra você têm vantagem até o seu próximo turno.")


def _inspiracao_de_bardo(char, hab, alvo, modo):
    from rpg import tools_dnd as td
    nivel = int(((char.get("sheet") or {}).get("nivel", 1)) or 1)
    faces = 12 if nivel >= 15 else 10 if nivel >= 10 else 8 if nivel >= 5 else 6
    alvo_ch = _char(alvo)
    dado = f"1d{faces}"
    td.dar_efeito_de_combate(alvo_ch, {"nome": "Inspiração de Bardo", "atk_dado": dado,
                                       "save_dado": dado, "teste_dado": dado, "usos": 1})
    return f"\n   {alvo_ch['name']} ganha 1d{faces} de Inspiração para o próximo ataque, salvaguarda ou teste."


def _cura_pelas_maos(char, hab, alvo, modo):
    from rpg import tools_dnd as td
    alvo_ch = _char(alvo) or char
    st = alvo_ch["sheet"]
    reserva = int(td.usos_restantes(char, "cura pelas maos") or 0)
    antes = int(st.get("vida_atual", 0) or 0)
    cura = min(reserva, int(st.get("vida_max", 0) or 0) - antes)
    st["vida_atual"] = antes + cura
    if antes == 0 and cura > 0 and (alvo_ch.get("status") or "").lower() in ("inconsciente", "estabilizado"):
        alvo_ch["status"] = "vivo"
    char.setdefault("sheet", {}).setdefault("usos", {})["cura pelas maos"] = reserva - cura
    return (f"\n   Cura pelas Mãos: +{cura} em {alvo_ch['name']} ({antes} → {st['vida_atual']}/"
            f"{st.get('vida_max')}). Reserva: {reserva - cura}.")


_ACOES = {
    "acao ardilosa": _acao_ardilosa,
    "passo do vento": _passo_do_vento,
    "sacerdote de guerra": _sacerdote_de_guerra,
    "rajada de golpes": _rajada_de_golpes,
    "defesa paciente": _defesa_paciente,
    "expulsar mortos vivos": _expulsar_mortos_vivos,
    "expulsar o profano": _expulsar_o_profano,
    "preservar a vida": _preservar_a_vida,
    "guiar ataque": _guiar_ataque,
    "furia": _furia,
    "ataque imprudente": _ataque_imprudente,
    "inspiracao de bardo": _inspiracao_de_bardo,
    "cura pelas maos": _cura_pelas_maos,
}
assert set(_ACOES) == set(ACOES_DE_CLASSE), "toda ação de classe precisa de quem a execute"
