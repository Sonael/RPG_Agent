"""
gerar_compendio.py
Gera o compêndio local do SRD 5.1 a partir dos dados brutos do Open5e v2.

    python scripts/gerar_compendio.py            # gera rpg/dados/*.json
    python scripts/gerar_compendio.py --baixar   # baixa o SRD de novo antes

POR QUE EXISTE
──────────────
O motor lia as magias do Open5e EM TEMPO DE JOGO e interpretava a prosa em
inglês com expressões regulares — em seis lugares diferentes, cada um com o
seu palpite. Quando dois discordavam, a tela dizia uma coisa e o motor fazia
outra: Infligir Ferimentos aparecia sem dado na tela e rolava 3d10 no motor; a
Radiância do Amanhecer, que só atinge criaturas HOSTIS, queimava os aliados da
zona.

Aqui a interpretação acontece UMA vez, fora do jogo, e o resultado é revisável:
um JSON com um campo para cada coisa que o motor e a tela precisam saber.

DE ONDE VEM CADA VALOR
──────────────────────
O Open5e v2 já traz a mecânica em campos (dano, tipo, salvaguarda, ataque,
forma e tamanho da área, escala por nível). Ele é a fonte primária. Mas ele
NÃO é confiável sozinho, e medir isso foi o primeiro passo:

  • `damage_roll` só existe em 61 das 319 magias. Cura nunca vem nele;
    Mísseis Mágicos e a base da Chama Sagrada também não.
  • `attack_roll` está ERRADO em Infligir Ferimentos (diz False; o texto diz
    "faça um ataque corpo a corpo com magia").
  • Área sem forma em casos claros: Espíritos Guardiões, Sono, Relâmpago.
  • E nenhum campo diz QUEM é atingido. "Criaturas à sua escolha" só existe
    no texto.

Então: o campo vale quando existe; o texto completa quando falta; e cada valor
registra de onde veio (`origem_dos_dados`). Toda divergência entre campo e
texto vai para scripts/srd_relatorio.txt — visível, em vez de engolida.

LICENÇA
───────
Este material vem do System Reference Document 5.1 da Wizards of the Coast,
disponível sob a licença Creative Commons Atribuição 4.0 Internacional
(https://creativecommons.org/licenses/by/4.0/legalcode). Só o SRD é aberto: o
resto do D&D é conteúdo protegido e NÃO entra aqui.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BRUTO = RAIZ / "scripts" / "srd_bruto"
DESTINO = RAIZ / "rpg" / "dados"
NOMES_PT = RAIZ / "scripts" / "srd_nomes_pt.json"
RELATORIO = RAIZ / "scripts" / "srd_relatorio.txt"

ATRIBUICAO = (
    "Este trabalho inclui material do System Reference Document 5.1 (\"SRD "
    "5.1\") da Wizards of the Coast LLC, disponível em "
    "https://dnd.wizards.com/resources/systems-reference-document. O SRD 5.1 é "
    "licenciado sob a Creative Commons Atribuição 4.0 Internacional, disponível "
    "em https://creativecommons.org/licenses/by/4.0/legalcode. Nomes e resumos "
    "em português e a estrutura dos campos são obra derivada."
)

# ---------------------------------------------------------------------------
# Vocabulário
# ---------------------------------------------------------------------------

PES_PARA_M = 0.3            # convenção do D&D em português: 5 pés = 1,5 m

ESCOLA_PT = {
    "abjuration": "abjuração", "conjuration": "conjuração",
    "divination": "adivinhação", "enchantment": "encantamento",
    "evocation": "evocação", "illusion": "ilusão",
    "necromancy": "necromancia", "transmutation": "transmutação",
}
CLASSE_PT = {
    "Bard": "bardo", "Cleric": "clérigo", "Druid": "druida",
    "Paladin": "paladino", "Ranger": "patrulheiro", "Sorcerer": "feiticeiro",
    "Warlock": "bruxo", "Wizard": "mago", "Barbarian": "bárbaro",
    "Fighter": "guerreiro", "Monk": "monge", "Rogue": "ladino",
}
SALVAGUARDA_PT = {
    "strength": "forca", "dexterity": "destreza", "constitution": "constituicao",
    "intelligence": "inteligencia", "wisdom": "sabedoria", "charisma": "carisma",
}
SIGLA = {"forca": "FOR", "destreza": "DES", "constituicao": "CON",
         "inteligencia": "INT", "sabedoria": "SAB", "carisma": "CAR"}
TIPOS_DANO = ("acid", "bludgeoning", "cold", "fire", "force", "lightning",
              "necrotic", "piercing", "poison", "psychic", "radiant",
              "slashing", "thunder")
TIPO_DANO_PT = {
    "acid": "ácido", "bludgeoning": "concussão", "cold": "frio", "fire": "fogo",
    "force": "força", "lightning": "elétrico", "necrotic": "necrótico",
    "piercing": "perfurante", "poison": "veneno", "psychic": "psíquico",
    "radiant": "radiante", "slashing": "cortante", "thunder": "trovejante",
}
CONDICOES = {
    "blinded": "cego", "charmed": "enfeitiçado", "deafened": "surdo",
    "frightened": "amedrontado", "grappled": "agarrado",
    "incapacitated": "incapacitado", "invisible": "invisível",
    "paralyzed": "paralisado", "petrified": "petrificado",
    "poisoned": "envenenado", "prone": "caído", "restrained": "contido",
    "stunned": "atordoado", "unconscious": "inconsciente",
}
FORMA_PT = {"sphere": "esfera", "cone": "cone", "cube": "cubo",
            "cylinder": "cilindro", "line": "linha", "radius": "esfera",
            "square": "quadrado", "emanation": "esfera"}
ACAO = {
    "action": ("acao", "1 ação"), "bonus-action": ("bonus", "1 ação bônus"),
    "reaction": ("reacao", "1 reação"), "1minute": ("longa", "1 minuto"),
    "10minutes": ("longa", "10 minutos"), "1hour": ("longa", "1 hora"),
    "8hours": ("longa", "8 horas"), "12hours": ("longa", "12 horas"),
    "24hours": ("longa", "24 horas"),
}
DURACAO_PT = [
    (r"instantaneous", "instantânea"), (r"until dispelled", "até ser dissipada"),
    (r"special", "especial"), (r"\bround(s)?\b", r"rodada\1"),
    (r"\bminute(s)?\b", r"minuto\1"), (r"\bhour(s)?\b", r"hora\1"),
    (r"\bday(s)?\b", r"dia\1"), (r"\bor\b", "ou"), (r"\btriggered\b", "ativada"),
]

_DADO = r"\d+d\d+(?:\s*[+]\s*\d+)?"
_TIPO = "(" + "|".join(TIPOS_DANO) + ")"


# ---------------------------------------------------------------------------
# REVISÃO À MÃO
# ---------------------------------------------------------------------------
# A primeira versão deixava o texto completar livremente o que o campo não
# dizia, e o relatório mostrou o custo:
#
#   Teia ................... "dano 2d4 de fogo"   (é se a teia PEGAR fogo)
#   Fundir-se às Rochas .... "dano 6d6"           (é em VOCÊ, se a pedra quebrar)
#   Porta Dimensional ...... "dano 4d6 de força"  (em você, se chegar ocupado)
#   Contato Extraplanar .... "dano 6d6 psíquico"  (em você, se falhar)
#   Luz, Detectar Magia .... "área"               (é o raio da luz, da percepção)
#   Desintegrar ............ "cubo de 3 m"        (é para OBJETOS)
#
# Conjurar Teia queimaria o alvo. Era a mesma classe de erro que este gerador
# existe para eliminar — agora vinda do próprio gerador.
#
# Então o texto só completa o que foi REVISADO: as listas abaixo são as magias
# cujo dano ou área vindo do texto eu conferi contra a regra. O resto é
# ignorado e aparece no relatório como "ignorado", para alguém revisar depois.
# O SRD 5.1 é congelado: estes nomes não mudam.

DANO_DO_TEXTO_REVISADO = {
    "Acid Splash", "Poison Spray", "Sacred Flame", "Vicious Mockery",
    "Magic Missile", "Phantasmal Killer", "Weird",
}
AREA_DO_TEXTO_REVISADA = {
    "Spirit Guardians", "Sleep", "Lightning Bolt", "Ice Storm", "Flame Strike",
    "Black Tentacles", "Entangle", "Grease", "Spike Growth", "Moonbeam",
    "Earthquake", "Sunburst", "Holy Aura", "Antilife Shell",
    "Globe of Invulnerability", "Plant Growth", "Pass without Trace",
    # Revelados quando o hífen invisível do SRD deixou de esconder a área:
    "Shatter", "Confusion",
}

# Ajustes campo a campo, cada um com o porquê. Valem por cima de tudo.
AJUSTES: dict[str, dict] = {
    "Web": {"efeito": "condicao", "condicao": "contido", "porque":
            "o 2d4 de fogo é se a teia pegar fogo; a magia prende"},
    "Bestow Curse": {"efeito": "condicao", "condicao": "amaldiçoado", "porque":
                     "o 1d8 necrótico é UMA das maldições possíveis, à escolha"},
    "Divine Favor": {"efeito": "buff", "alvos": "si", "resumo":
                     "Suas armas causam +1d4 radiante · concentração", "porque":
                     "é reforço das SUAS armas, não dano num alvo"},
    "Branding Smite": {"efeito": "buff", "alvos": "si", "resumo":
                       "O próximo acerto com arma causa +2d6 radiante · concentração",
                       "porque": "dano extra no próximo golpe, não um ataque"},
    "Fire Shield": {"efeito": "buff", "alvos": "si", "area": None, "resumo":
                    "Resistência a fogo ou frio; quem te acertar corpo a corpo leva 2d8",
                    "porque": "é escudo em você; o dano é retaliação"},
    "Faithful Hound": {"efeito": "invocacao", "porque": "o 4d8 é a mordida do cão invocado"},
    "Sunbeam": {"area": {"forma": "linha", "tamanho_m": 18}, "porque":
                "a área é a linha de 18 m; o raio de 9 m é a luz que fica"},
    "Disintegrate": {"area": None, "alvos": "uma", "porque":
                     "o cubo de 3 m é para objetos; contra criatura é um alvo"},

    # Erros do CAMPO do Open5e, achados revisando as 50 magias de área que
    # afetam criaturas. O campo às vezes guarda o raio da LUZ ou da nuvem, não
    # o da área de efeito — e o motor queimaria todo mundo nesse raio.
    "Flaming Sphere": {"area": {"forma": "esfera", "tamanho_m": 1.5}, "porque":
                       "o campo traz 20 pés, que é a LUZ; o dano é a 1,5 m da esfera"},
    "Call Lightning": {"area": {"forma": "esfera", "tamanho_m": 1.5}, "porque":
                       "o cilindro de 18 m é a nuvem; cada raio cai num círculo de 1,5 m"},
    "Reverse Gravity": {"area": {"forma": "cilindro", "tamanho_m": 15}, "porque":
                        "o campo traz os 100 pés de ALTURA; o raio do cilindro é de 50 pés"},
    "Teleport": {"efeito": "utilidade", "area": None, "alvos": "escolha", "porque":
                 "o 3d10 é o acidente da viagem; o cubo é o que você leva junto"},
    "Delayed Blast Fireball": {"efeito": "dano", "dado": "12d6", "tipo_dano": "fire",
                               "salvaguarda": "destreza", "metade_se_passar": True,
                               "porque": "o texto diz 'o dano base é 12d6', sem o tipo colado"},
    "Stinking Cloud": {"efeito": "condicao", "condicao": "envenenado", "porque":
                       "é névoa venenosa; 'imune a' na regra de reforço era sobre quem não respira"},
    "Fabricate": {"efeito": "utilidade", "area": None, "porque": "transforma material; não toca criatura"},
    "Wall of Force": {"efeito": "utilidade", "area": None, "porque": "é barreira, não efeito em criatura"},
    "Antimagic Field": {"efeito": "utilidade", "area": None, "alvos": "si", "porque":
                        "suprime magia ao seu redor; não é reforço"},
    "Silence": {"efeito": "utilidade", "porque": "a área cala todos; não é reforço de ninguém"},
    "Holy Aura": {"efeito": "buff", "porque": "é proteção para quem você escolhe; a cegueira é retaliação"},
    "Calm Emotions": {"alvos": "todos", "porque":
                      "todo humanoide na esfera faz o teste; quem quiser pode falhar de propósito"},

    # ALCANCE "PESSOAL" NÃO É ALVO "SI". A magia nasce em você e o dano vai no
    # inimigo. Com alvo "si", o motor poderia aplicar o dano em quem conjura.
    "Vampiric Touch": {"alvos": "uma", "porque": "nasce em você; o toque é num inimigo"},
    "Flame Blade": {"alvos": "uma", "porque": "a lâmina é sua; o golpe é num inimigo"},
    "Produce Flame": {"alvos": "uma", "alcance": "9 m", "alcance_m": 9, "porque":
                      "a chama nasce na sua mão e é arremessada a até 9 m"},

    # Muralhas: na grade de zonas, quem está na linha da muralha é atingido.
    "Wind Wall": {"area": {"forma": "linha", "tamanho_m": 15}, "alvos": "todos",
                  "porque": "muralha de 15 m: quem estiver na linha é atingido"},
    "Wall of Fire": {"area": {"forma": "linha", "tamanho_m": 18}, "alvos": "todos",
                     "porque": "muralha de 18 m"},
    "Blade Barrier": {"area": {"forma": "linha", "tamanho_m": 30}, "alvos": "todos",
                      "porque": "muralha de 30 m"},
    "Wall of Ice": {"area": {"forma": "linha", "tamanho_m": 30}, "alvos": "todos",
                    "porque": "dez painéis de 3 m"},
    "Wall of Thorns": {"area": {"forma": "linha", "tamanho_m": 18}, "alvos": "todos",
                       "porque": "muralha de 18 m"},
    "Prismatic Wall": {"area": {"forma": "linha", "tamanho_m": 27}, "alvos": "todos",
                       "porque": "muralha de 27 m"},
    "Gust of Wind": {"efeito": "condicao", "condicao": "empurrado",
                     "area": {"forma": "linha", "tamanho_m": 18}, "alvos": "todos",
                     "porque": "linha de 18 m que empurra todos nela"},
    "Guardian of Faith": {"alvos": "hostis", "area": {"forma": "esfera", "tamanho_m": 3},
                          "porque": "só fere criaturas HOSTIS a 3 m do guardião"},
    "Storm of Vengeance": {"area": {"forma": "esfera", "tamanho_m": 108}, "alvos": "todos",
                           "porque": "a tempestade cobre 108 m de raio"},

    # Classificação errada, sem efeito no combate mas enganando a tela.
    "Light": {"efeito": "utilidade", "alvos": "uma", "porque":
              "o teste de DES é só se o objeto estiver com um inimigo"},
    "Sanctuary": {"efeito": "buff", "porque": "protege um aliado; quem ataca é que faz o teste"},
    "Detect Thoughts": {"efeito": "utilidade", "porque": "adivinhação"},
    "Gaseous Form": {"efeito": "buff", "condicao": "", "porque": "transforma um aliado disposto"},
    "Magic Circle": {"efeito": "utilidade", "porque": "proteção de área montada antes"},
    "Polymorph": {"condicao": "transformado", "resumo":
                  "Transforma uma criatura em besta · SAB · 18 m · concentração",
                  "porque": "'inconsciente' é o que acontece se a forma nova cair a 0"},
    "True Polymorph": {"condicao": "transformado", "porque": "transforma, não deixa inconsciente"},
    "Shapechange": {"efeito": "buff", "alvos": "si", "condicao": "", "porque": "você se transforma"},
    "Contact Other Plane": {"efeito": "utilidade", "porque": "adivinhação; o teste é seu"},
    "Dispel Evil and Good": {"efeito": "buff", "porque": "proteção em você"},
    "Hallow": {"efeito": "utilidade", "porque": "consagra um lugar"},
    "Planar Binding": {"efeito": "utilidade", "porque": "ritual de 1 hora"},
    "Scrying": {"efeito": "utilidade", "condicao": "", "porque": "adivinhação à distância"},
    "Seeming": {"efeito": "utilidade", "porque": "ilusão de aparência"},
    "Plane Shift": {"efeito": "utilidade", "ataque": None, "porque": "viagem entre planos"},
    "Heroes' Feast": {"efeito": "buff", "condicao": "", "porque": "banquete que fortalece"},
    "Forcecage": {"condicao": "aprisionado", "porque": "'invisível' é o tipo de jaula, não o efeito"},
    "Glyph of Warding": {"efeito": "utilidade", "porque": "armadilha montada fora do combate"},
    "Control Water": {"efeito": "utilidade", "porque": "o 2d8 é o redemoinho, efeito secundário"},
    "Dream": {"efeito": "utilidade", "porque": "o dano é ao acordar do pesadelo, fora de combate"},
    "Geas": {"efeito": "condicao", "condicao": "enfeitiçado", "porque":
             "o 5d10 é a punição por desobedecer"},
    "Forbiddance": {"efeito": "utilidade", "porque": "proteção de um lugar por 1 dia"},
    "Command": {"resumo": "Uma ordem de uma palavra: aproxime-se, largue, fuja, rasteje ou pare · SAB · 18 m",
                "porque": "'caído' é só uma das ordens possíveis"},
    "Bane": {"resumo": "Até 3 criaturas subtraem 1d4 de ataques e salvaguardas · CAR · 9 m · concentração",
             "porque": "é penalidade, não condição com nome"},
    "Confusion": {"resumo": "Criaturas agem ao acaso · SAB · esfera de 3 m · TODOS na área, "
                            "aliados inclusive · 27 m · concentração",
                  "porque": "'confuso' não é condição do SRD; o efeito precisa ser dito"},

    # "Reforço" sozinho não diz nada. As defesas mais usadas em combate ganham
    # o efeito escrito, que é o que faz o jogador escolher uma e não a outra.
    "Shield": {"resumo": "+5 de CA até o seu próximo turno; anula Mísseis Mágicos · reação",
               "porque": "'Reforço · em si' não dizia o que ele faz"},
    "Mage Armor": {"resumo": "CA base vira 13 + DES por 8 horas · toque", "porque": "idem"},
    "Shield of Faith": {"resumo": "+2 de CA · ação bônus · 18 m · concentração", "porque": "idem"},
    "Bless": {"resumo": "Até 3 criaturas somam 1d4 a ataques e salvaguardas · 9 m · concentração",
              "porque": "idem"},
    "Haste": {"resumo": "Dobra o deslocamento, +2 de CA e uma ação extra · 9 m · concentração",
              "porque": "idem"},
    "Heroism": {"resumo": "Imune a medo e PV temporários a cada turno · toque · concentração",
                "porque": "idem"},
    "Aid": {"resumo": "+5 de PV máximo e atual para até 3 criaturas · 9 m", "porque": "idem"},
    "False Life": {"resumo": "1d4 + 4 de PV temporários · em si", "porque": "idem"},
    "Mirror Image": {"resumo": "Três cópias ilusórias desviam ataques · em si", "porque": "idem"},
    "Blur": {"resumo": "Ataques contra você têm desvantagem · em si · concentração", "porque": "idem"},
    "Protection from Evil and Good": {"resumo": "Aberrações, celestiais, elementais, fadas, "
                                                "corruptores e mortos-vivos atacam com desvantagem "
                                                "· toque · concentração", "porque": "idem"},
    "Resistance": {"resumo": "+1d4 numa salvaguarda · toque · concentração", "porque": "idem"},
    "Guidance": {"resumo": "+1d4 num teste de atributo · toque · concentração", "porque": "idem"},
    "Spare the Dying": {"resumo": "Estabiliza uma criatura a 0 PV · toque", "porque": "idem"},
    "Misty Step": {"resumo": "Teletransporta você até 9 m · ação bônus", "porque": "idem"},
    "Expeditious Retreat": {"resumo": "Disparada como ação bônus a cada turno · concentração",
                            "porque": "idem"},
    "Longstrider": {"resumo": "+3 m de deslocamento por 1 hora · toque", "porque": "idem"},
    "Greater Invisibility": {"resumo": "Invisível mesmo atacando · toque · concentração",
                             "porque": "idem"},
    "Invisibility": {"resumo": "Invisível até atacar ou conjurar · toque · concentração",
                     "porque": "idem"},
    "Stoneskin": {"resumo": "Resistência a dano físico não mágico · toque · concentração",
                  "porque": "idem"},
}


# ---------------------------------------------------------------------------
# Leitura do texto — só para completar o que o campo não diz
# ---------------------------------------------------------------------------

def _limpa(texto: str) -> str:
    """
    O texto do SRD vem com HÍFEN INVISÍVEL (U+00AD) e traços duplicados:
    Despedaçar diz "10-­--foot-­--radius sphere". A Confusão escreve "10 foot
    radius", sem hífen. A leitura esperava "10-foot" e perdia a área das duas
    em silêncio — esferas de 3 m que pegam todo mundo viravam alvo único, sem
    aviso de fogo amigo e acertando uma criatura só.
    """
    t = (texto or "").replace("­", "").replace("‐", "-").replace("‑", "-")
    t = re.sub(r"-{2,}", "-", t)
    return re.sub(r"[ \t]+", " ", t).strip()


def _pes_para_m(pes) -> float | None:
    try:
        v = float(pes)
    except (TypeError, ValueError):
        return None
    m = round(v * PES_PARA_M, 1)
    return int(m) if m == int(m) else m


def _fmt_m(m) -> str:
    if m is None:
        return ""
    return f"{m:g}".replace(".", ",") + " m"


def _danos_no_texto(desc: str) -> list[dict]:
    """
    Todos os 'XdY tipo damage' do texto, na ordem em que aparecem — menos as
    ALTERNATIVAS. Espíritos Guardiões diz "3d8 radiant damage (if you are good
    or neutral) or 3d8 necrotic damage (if you are evil)": é um OU o outro. A
    primeira versão somava os dois e a tela mostrava 3d8 + 3d8.
    """
    vistos, saida = set(), []
    fim_anterior = None
    for achado in re.finditer(rf"({_DADO})\s+{_TIPO}\s+damage", desc, re.I):
        dado = re.sub(r"\s+", "", achado.group(1))
        tipo = achado.group(2).lower()
        if fim_anterior is not None:
            entre = desc[fim_anterior:achado.start()].lower()
            if re.search(r"\bor\b", entre) and len(entre) < 60:
                fim_anterior = achado.end()
                continue
        fim_anterior = achado.end()
        chave = (dado, tipo)
        if chave not in vistos:
            vistos.add(chave)
            saida.append({"dado": dado, "tipo": tipo})
    return saida


def _cura_no_texto(desc: str) -> tuple[str, bool] | None:
    """(dado da cura, soma o modificador?) — ou None se a magia não cura."""
    t = desc.lower()
    # "recupera 4d8 + 15" (Regenerar) e "restaura até 700" (Cura Completa em
    # Massa) escapavam: a regra só conhecia "recupera N pontos de vida".
    if not re.search(r"regains?\s+(?:a number of\s+)?(?:[\dd+\s]+)?hit points", t) \
            and not re.search(r"restores?\s+(?:up to\s+)?\d+\s+hit points", t) \
            and "regain hit points" not in t and "regain all its hit points" not in t:
        return None
    soma_mod = "spellcasting ability modifier" in t
    m = re.search(rf"(?:equal to|regains?)\s+({_DADO})", t)
    if m:
        return re.sub(r"\s+", "", m.group(1)), soma_mod
    m = re.search(r"(?:regains?|restores?(?:\s+up to)?)\s+(\d+)\s+hit points", t)
    if m:
        return m.group(1), soma_mod
    m = re.search(r"up to\s+(\d+)\s+hit points", t)
    if m:
        return m.group(1), soma_mod
    return "", soma_mod


def _area_no_texto(desc: str) -> tuple[str, float] | None:
    t = desc.lower()
    # "10-foot-radius, 40-foot-high cylinder": o raio é do CILINDRO. A busca
    # genérica abaixo parava no "radius" e chamava a Coluna de Chamas de esfera.
    m = re.search(r"(\d+)[\s-]*foot[\s-]*radius,?\s+\d+[\s-]*foot[\s-]*(?:high|tall)\s+cylinder", t)
    if m:
        return "cylinder", float(m.group(1))
    m = re.search(r"(\d+)[\s-]*foot[\s-]*(radius|cone|cube|line|square|cylinder|sphere)", t)
    if m:
        return m.group(2), float(m.group(1))
    m = re.search(r"line\s+(\d+)\s+feet\s+long", t)
    if m:
        return "line", float(m.group(1))
    m = re.search(r"(\d+)\s+feet\s+(?:of|around)\s+you\b", t)
    if m:
        return "radius", float(m.group(1))
    m = re.search(r"within\s+(\d+)\s+feet\s+of\s+(?:a point|that point|the point|you)", t)
    if m:
        return "radius", float(m.group(1))
    m = re.search(r"to a distance of\s+(\d+)\s+feet", t)
    if m:
        return "radius", float(m.group(1))
    return None


def _ataque_no_texto(desc: str) -> str | None:
    m = re.search(r"make an?\s+(melee|ranged)\s+spell attack", desc, re.I)
    if not m:
        return None
    return "corpo" if m.group(1).lower() == "melee" else "distancia"


def _salvaguarda_no_texto(desc: str) -> str:
    m = re.search(r"(strength|dexterity|constitution|intelligence|wisdom|charisma)"
                  r"\s+saving throw", desc, re.I)
    return SALVAGUARDA_PT[m.group(1).lower()] if m else ""


def _condicao_no_texto(desc: str) -> str:
    t = desc.lower()
    melhor = None
    for en, pt in CONDICOES.items():
        i = t.find(en)
        if i >= 0 and (melhor is None or i < melhor[0]):
            melhor = (i, pt)
    return melhor[1] if melhor else ""


def _alvos_no_texto(desc: str, tem_area: bool, origem: str) -> str:
    """
    QUEM a magia atinge. É o campo que o Open5e não tem, e cuja falta queimou
    aliados: magia seletiva tratada como indiscriminada.

      hostis  — "hostile creature(s)"
      escolha — "of your choice", "you choose", "designate ... unaffected",
                "up to N creatures", "any number of creatures"
      todos   — área sem escolha: aliados INCLUSIVE (o fogo amigo é regra)
      si      — só em quem conjura
      uma     — um alvo escolhido
    """
    t = desc.lower()
    if re.search(r"\bhostile creatures?\b", t):
        return "hostis"
    # "à sua escolha" tem de falar de CRIATURAS. "Um ponto à sua escolha" diz
    # ONDE a magia cai, não quem ela atinge — e confundir os dois marcava Teia
    # como seletiva: aliado saindo ileso do que deveria prendê-lo.
    if re.search(r"creatures? of your choice|creatures? (?:that )?you choose|"
                 r"designate any number of creatures|"
                 r"up to (?:\w+ )?(?:willing )?creatures|any number of creatures|"
                 r"choose up to \w+ creatures|choose any number of creatures|"
                 r"creatures? you can see .{0,20}of your choice", t):
        return "escolha"
    if tem_area:
        return "todos"
    if origem == "si":
        return "si"
    return "uma"


def _efeito(desc: str, danos: list, cura, salva: str, condicao: str, nome: str) -> str:
    t = desc.lower()
    if re.search(r"roll \d+d\d+; the total is how many hit points", t):
        return "pool"
    if danos:
        return "dano"
    if cura is not None:
        return "cura"
    if salva and condicao:
        return "condicao"
    if re.search(r"\b(summon|conjure|you call forth|appears in an unoccupied)\b", t) \
            or nome.startswith(("Conjure", "Find ", "Animate", "Create Undead",
                                "Planar Ally", "Gate", "Giant Insect")):
        return "invocacao"
    if re.search(r"bonus to (?:its )?ac|\+\d+ bonus|advantage on|add (?:a|the) d\d|"
                 r"roll a d\d+ and add|temporary hit points|resistance to|"
                 r"can't be|immune to|hit point maximum .{0,20}increases", t):
        return "buff"
    if salva:
        return "condicao"
    return "utilidade"


def _duracao(texto: str, concentracao: bool) -> str:
    t = (texto or "").strip().lower()
    for padrao, troca in DURACAO_PT:
        t = re.sub(padrao, troca, t)
    if concentracao and t and "conc" not in t:
        t = f"concentração, até {t}"
    return t


def _alcance(m: dict) -> tuple[str, float | None, str]:
    """(texto em PT, metros, origem: si|toque|ponto|alvo)."""
    txt = (m.get("range_text") or "").strip()
    tl = txt.lower()
    if tl.startswith("self"):
        return "pessoal", 0, "si"
    if tl == "touch":
        return "toque", 1.5, "toque"
    unidade = (m.get("range_unit") or "").lower()
    alcance = m.get("range")
    if unidade == "feet" and alcance:
        metros = _pes_para_m(alcance)
        return _fmt_m(metros), metros, "alvo"
    if "mile" in tl:
        n = re.match(r"(\d+)", tl)
        km = round(int(n.group(1)) * 1.5, 1) if n else 1.5
        return f"{km:g} km".replace(".", ","), None, "alvo"
    traducao = {"sight": "à vista", "unlimited": "ilimitado", "special": "especial"}
    return traducao.get(tl, tl), None, "alvo"


def _escalas(m: dict) -> tuple[dict, dict, dict]:
    """(dano por espaço, dano por nível de personagem, alvos por espaço)."""
    por_espaco, por_personagem, alvos = {}, {}, {}
    anterior = None
    for op in m.get("casting_options") or []:
        tipo = op.get("type") or ""
        dano = op.get("damage_roll")
        if tipo.startswith("slot_level_"):
            nivel = tipo.rsplit("_", 1)[-1]
            if dano:
                por_espaco[nivel] = dano
            if op.get("target_count"):
                alvos[nivel] = op["target_count"]
        elif tipo.startswith("player_level_") and dano and dano != anterior:
            por_personagem[tipo.rsplit("_", 1)[-1]] = dano
            anterior = dano
    return por_espaco, por_personagem, alvos


def _resumo(r: dict) -> str:
    """
    O que a tela mostra em uma linha — no lugar do botão que só tinha o nome.
    "Dano 8d6 de fogo · esfera de 6 m · DES, metade se passar · TODOS na área"
    """
    partes = []
    ef = r["efeito"]
    if ef == "dano":
        txt = f"Dano {r['dado']} {TIPO_DANO_PT.get(r['tipo_dano'], '')}".strip()
        for extra in r.get("dano_extra") or []:
            txt += f" + {extra['dado']} {TIPO_DANO_PT.get(extra['tipo'], '')}"
        partes.append(txt)
    elif ef == "cura":
        cura = f"Cura {r['dado']}" if r.get("dado") else "Cura"
        partes.append(cura + (" + mod." if r.get("soma_mod") else ""))
    elif ef == "pool":
        partes.append(f"Afeta {r['dado']} PV de criaturas")
    elif ef == "condicao":
        partes.append((r.get("condicao") or "condição").capitalize())
    else:
        partes.append({"buff": "Reforço", "invocacao": "Invocação",
                       "utilidade": "Utilidade"}.get(ef, ef))
    if r.get("ataque"):
        partes.append("ataque " + ("corpo a corpo" if r["ataque"] == "corpo" else "à distância"))
    if r.get("salvaguarda"):
        s = f"{SIGLA[r['salvaguarda']]}"
        if r.get("metade_se_passar"):
            s += ", metade se passar"
        partes.append(s)
    if r.get("area"):
        partes.append(f"{r['area']['forma']} de {_fmt_m(r['area']['tamanho_m'])}")
    alvo = {"hostis": "só inimigos", "escolha": "à sua escolha",
            "todos": "TODOS na área, aliados inclusive", "si": "em si"}.get(r["alvos"])
    if r["alvos"] == "escolha" and not r.get("area") and (r.get("alvo_max") or 1) > 1:
        alvo = f"até {r['alvo_max']} criaturas à sua escolha"
    if alvo and (r.get("area") or r["alvos"] in ("hostis", "si")
                 or (r["alvos"] == "escolha" and (r.get("alvo_max") or 1) > 1)):
        partes.append(alvo)
    # No combate a economia de ação é decisão: reação e bônus precisam aparecer.
    if r.get("acao") == "bonus":
        partes.append("ação bônus")
    elif r.get("acao") == "reacao":
        partes.append("reação")
    if r.get("alcance") and r["alcance"] not in ("pessoal",):
        partes.append(r["alcance"])
    if r.get("concentracao"):
        partes.append("concentração")
    return " · ".join(p for p in partes if p)


# ---------------------------------------------------------------------------
# Uma magia
# ---------------------------------------------------------------------------

def magia(m: dict, nomes_pt: dict, divergencias: list) -> dict:
    nome_en = m["name"]
    desc = _limpa(m.get("desc") or "")
    origem = {}

    alcance_txt, alcance_m, origem_area = _alcance(m)
    if (m.get("target_type") == "point"
            or re.search(r"\ba point (?:you choose|of your choice)\b", desc, re.I)) \
            and origem_area == "alvo":
        origem_area = "ponto"

    # Dano
    danos_texto = _danos_no_texto(desc)
    if m.get("damage_roll"):
        tipo = (m.get("damage_types") or [""])[0] or (danos_texto[0]["tipo"] if danos_texto else "")
        danos = [{"dado": m["damage_roll"].replace(" ", ""), "tipo": tipo}]
        origem["dano"] = "campo"
        for d in danos_texto:
            if d["tipo"] != tipo and d not in danos:
                danos.append(d)
        if danos_texto and danos_texto[0]["dado"] != danos[0]["dado"]:
            divergencias.append(f"{nome_en}: damage_roll={m['damage_roll']!r} mas o "
                                f"texto diz {danos_texto[0]['dado']!r}")
    elif danos_texto and nome_en in DANO_DO_TEXTO_REVISADO:
        danos = danos_texto
        origem["dano"] = "texto (revisado)"
    else:
        danos = []
        if danos_texto:
            divergencias.append(f"{nome_en}: IGNORADO dano do texto "
                                f"{danos_texto[0]['dado']} {danos_texto[0]['tipo']} "
                                f"(não revisado)")

    cura = _cura_no_texto(desc) if not danos else None

    # Salvaguarda
    salva = SALVAGUARDA_PT.get((m.get("saving_throw_ability") or "").lower(), "")
    if salva:
        origem["salvaguarda"] = "campo"
    else:
        salva = _salvaguarda_no_texto(desc)
        if salva:
            origem["salvaguarda"] = "texto"

    # Ataque
    ataque_texto = _ataque_no_texto(desc)
    if ataque_texto:
        ataque = ataque_texto
        origem["ataque"] = "texto"
        if not m.get("attack_roll"):
            divergencias.append(f"{nome_en}: attack_roll=False mas o texto pede "
                                f"ataque {ataque_texto}")
    elif m.get("attack_roll"):
        ataque = "distancia" if (alcance_m or 0) > 1.5 else "corpo"
        origem["ataque"] = "campo"
    else:
        ataque = None

    # Área
    area = None
    if m.get("shape_type") and m.get("shape_size"):
        area = {"forma": FORMA_PT.get(m["shape_type"], m["shape_type"]),
                "tamanho_m": _pes_para_m(m["shape_size"])}
        origem["area"] = "campo"
    else:
        achada = _area_no_texto(desc)
        if achada and nome_en in AREA_DO_TEXTO_REVISADA:
            forma, pes = achada
            area = {"forma": FORMA_PT.get(forma, forma), "tamanho_m": _pes_para_m(pes)}
            origem["area"] = "texto (revisado)"
        elif achada:
            divergencias.append(f"{nome_en}: IGNORADA área do texto "
                                f"{achada[0]} de {achada[1]:g} pés (não revisada)")

    condicao = _condicao_no_texto(desc)
    efeito = _efeito(desc, danos, cura, salva, condicao, nome_en)
    alvos = _alvos_no_texto(desc, bool(area), origem_area)
    origem["alvos"] = "texto"

    dado = ""
    soma_mod = False
    if efeito == "dano":
        dado = danos[0]["dado"]
    elif efeito == "cura" and cura:
        dado, soma_mod = cura
    elif efeito == "pool":
        mm = re.search(r"roll (\d+d\d+)", desc, re.I)
        dado = mm.group(1) if mm else ""
    else:
        # O dado de BÔNUS ou PENALIDADE: o 1d4 da Bênção, da Orientação, da
        # Perdição. Não entra na vida de ninguém, mas o jogador quer vê-lo
        # rolado — e sem ele aqui a Bênção virava "Utilidade" sem número.
        # Só quando o dado é SOMADO ou SUBTRAÍDO: "role um d20" em Piscar e
        # Lentidão é teste, não bônus.
        mm = (re.search(r"roll a d(4|6|8|10|12) and (?:add|subtract)", desc, re.I)
              or re.search(r"(?:add|subtract) (?:a|the) d(4|6|8|10|12)\b", desc, re.I))
        if mm:
            dado = f"1d{mm.group(1)}"

    acao, tempo = ACAO.get(m.get("casting_time") or "", ("longa", m.get("casting_time") or ""))
    por_espaco, por_personagem, alvos_espaco = _escalas(m)
    componentes = ", ".join(c for c, tem in (("V", m.get("verbal")),
                                              ("S", m.get("somatic")),
                                              ("M", m.get("material"))) if tem)

    r = {
        "chave": m["key"].replace("srd_", ""),
        "nome": nomes_pt.get(nome_en, nome_en),
        "nome_srd": nome_en,
        "nivel": int(m.get("level") or 0),
        "escola": ESCOLA_PT.get(((m.get("school") or {}).get("key") or ""), ""),
        "classes": sorted({CLASSE_PT[c["name"]] for c in (m.get("classes") or [])
                           if c.get("name") in CLASSE_PT}),
        "acao": acao,
        "tempo_de_conjuracao": tempo,
        "alcance": alcance_txt,
        "alcance_m": alcance_m,
        "origem": origem_area,
        "area": area,
        "alvos": alvos,
        "alvo_max": int(m.get("target_count") or 1),
        "efeito": efeito,
        "dado": dado,
        "soma_mod": soma_mod,
        "tipo_dano": danos[0]["tipo"] if danos else "",
        "dano_extra": danos[1:],
        "salvaguarda": salva,
        "metade_se_passar": bool(re.search(r"half as much damage", desc, re.I)),
        "ataque": ataque,
        "condicao": condicao if efeito == "condicao" else "",
        "escala_espaco": por_espaco,
        "escala_personagem": por_personagem,
        "alvos_por_espaco": alvos_espaco,
        "concentracao": bool(m.get("concentration")),
        "ritual": bool(m.get("ritual")),
        "duracao": _duracao(m.get("duration") or "", bool(m.get("concentration"))),
        "componentes": componentes,
        "material": m.get("material_specified") or "",
        "descricao_en": desc,
        "nivel_superior_en": (m.get("higher_level") or "").strip(),
        "origem_dos_dados": origem,
    }

    ajuste = AJUSTES.get(nome_en)
    if ajuste:
        efeito_antes = r["efeito"]
        for campo, valor in ajuste.items():
            if campo in ("porque", "resumo"):
                continue
            r[campo] = valor
            r["origem_dos_dados"][campo] = "ajuste"
        # Só o ajuste que TIRA a magia do dano apaga o que era de dano. A
        # primeira versão apagava o dado de toda magia ajustada que não fosse
        # de dano — e a Bênção, ajustada só para ganhar um resumo melhor,
        # perdia o 1d4.
        if efeito_antes == "dano" and r["efeito"] != "dano":
            r["tipo_dano"] = ""
            r["dano_extra"] = []
            if "dado" not in ajuste:
                r["dado"] = ""
        r["ajuste"] = ajuste["porque"]
        # As alvos dependem da área: se o ajuste tirou a área, recalcula.
        if "alvos" not in ajuste:
            r["alvos"] = _alvos_no_texto(desc, bool(r["area"]), r["origem"])

    r["resumo"] = (ajuste or {}).get("resumo") or _resumo(r)
    return r


# ---------------------------------------------------------------------------
# Classes, subclasses e características
# ---------------------------------------------------------------------------

CLASSES_PT = RAIZ / "scripts" / "srd_classes_pt.json"

# Progressões que o SRD tem e o Open5e NÃO expõe como coluna da tabela: elas
# ficam na prosa ("aumenta conforme a coluna Ataque Furtivo") e a coluna não
# vem. Copiadas da tabela de cada classe no SRD 5.1.
PROGRESSOES = {
    "Sneak Attack": {str(n): f"{(n + 1) // 2}d6" for n in range(1, 21)},
    "Martial Arts": {**{str(n): "1d4" for n in range(1, 5)},
                     **{str(n): "1d6" for n in range(5, 11)},
                     **{str(n): "1d8" for n in range(11, 17)},
                     **{str(n): "1d10" for n in range(17, 21)}},
    "Bardic Inspiration": {**{str(n): "1d6" for n in range(1, 5)},
                           **{str(n): "1d8" for n in range(5, 10)},
                           **{str(n): "1d10" for n in range(10, 15)},
                           **{str(n): "1d12" for n in range(15, 21)}},
    "Brutal Critical": {**{str(n): "+1 dado" for n in range(9, 13)},
                        **{str(n): "+2 dados" for n in range(13, 17)},
                        **{str(n): "+3 dados" for n in range(17, 21)}},
}

# Usos por descanso que dependem de uma coluna da tabela da classe.
USOS_DA_TABELA = {"Rage": "furias", "Ki": "pontos_de_ki", "Font of Magic": "pontos_de_feiticaria"}

# Resumo de jogo das características que o jogador ATIVA em combate — é o que
# a tela mostra no botão. As passivas ficam com a descrição.
RESUMO_CARACTERISTICA = {
    "Rage": "Vantagem em FOR, +dano com armas de FOR, resistência a dano físico · ação bônus",
    "Reckless Attack": "Vantagem nos seus ataques com FOR; ataques contra você também têm",
    "Action Surge": "Uma ação a mais neste turno",
    "Second Wind": "Recupera 1d10 + nível de guerreiro de PV · ação bônus",
    "Indomitable": "Rola de novo uma salvaguarda que falhou",
    "Cunning Action": "Disparada, Desengajar ou Esconder como ação bônus",
    "Uncanny Dodge": "Corta pela metade o dano de um ataque que você vê · reação",
    "Sneak Attack": "Dano extra uma vez por turno com vantagem ou aliado adjacente ao alvo",
    "Bardic Inspiration": "Um aliado ganha um dado para somar a um teste · ação bônus",
    "Cutting Words": "Subtrai seu dado de inspiração de um ataque, teste ou dano inimigo · reação",
    "Channel Divinity": "Expulsar Mortos-Vivos ou o efeito do seu domínio · ação",
    "Channel Divinity: Preserve Life": "Distribui 5 × nível de clérigo em PV entre aliados a 9 m · ação",
    "Destroy Undead": "Mortos-vivos fracos expulsos são destruídos",
    "Divine Intervention": "Pede ajuda direta à sua divindade · ação",
    "Divine Smite": "Ao acertar, gasta um espaço: +2d8 radiante (+1d8 por nível acima do 1º)",
    "Lay on Hands": "Reserva de 5 × nível de PV para curar por toque · ação",
    "Divine Sense": "Sente celestiais, corruptores e mortos-vivos a 18 m · ação",
    "Wild Shape": "Assume a forma de uma besta já vista · ação",
    "Martial Arts": "Ataque desarmado como ação bônus depois de atacar",
    "Ki": "Rajada de Golpes, Defesa Paciente ou Passo do Vento · ação bônus",
    "Stunning Strike": "Gasta 1 ki ao acertar: o alvo faz CON ou fica atordoado",
    "Deflect Missiles": "Reduz o dano de um projétil em 1d10 + DES + nível · reação",
    "Wholeness of Body": "Recupera 3 × nível de monge de PV · ação",
    "Quivering Palm": "Vibrações letais num alvo; você decide quando disparar",
    "Font of Magic": "Troca pontos de feitiçaria por espaços de magia e vice-versa · ação bônus",
    "Arcane Recovery": "Recupera espaços de magia num descanso curto",
    "Hunter's Prey": "Matador de Colossos, Matador de Gigantes ou Quebra-Hordas",
    "Frenzy": "Durante a fúria, um ataque corpo a corpo extra como ação bônus",
    "Intimidating Presence": "Amedronta uma criatura a 9 m · SAB · ação",
    "Retaliation": "Ataque corpo a corpo em quem te feriu · reação",
    "Open Hand Technique": "A Rajada de Golpes derruba, empurra ou impede reações",
    "Dark One's Blessing": "PV temporários ao reduzir um inimigo a 0",
    "Dark One's Own Luck": "+1d10 num teste ou salvaguarda",
    "Hurl Through Hell": "Manda o alvo ao inferno: 10d10 psíquico",
    "Overchannel": "Dano máximo numa magia de até 5º nível",
}


# O tipo de ação lido da prosa erra quando a característica é uma LISTA de
# opções ou MODIFICA uma ação existente: Estilo de Luta saía "reação" porque um
# dos estilos (Proteção) usa reação; Ataque Extra saía "ação" porque o texto
# diz "quando você faz a ação de Atacar". Estes são decididos à mão.
TIPO_REVISADO = {
    "Fighting Style": "passiva", "Additional Fighting Style": "passiva",
    "Extra Attack": "passiva", "Spellcasting": "passiva", "Pact Magic": "passiva",
    "Eldritch Invocations": "passiva", "Metamagic": "passiva", "Expertise": "passiva",
    "Sneak Attack": "passiva", "Martial Arts": "bonus", "Ki": "bonus",
    "Divine Smite": "livre", "Improved Divine Smite": "passiva",
    "Brutal Critical": "passiva", "Improved Critical": "passiva",
    "Superior Critical": "passiva", "Hunter's Prey": "passiva",
    "Defensive Tactics": "passiva", "Superior Hunter's Defense": "reacao",
    "Multiattack": "passiva", "Favored Enemy": "passiva", "Natural Explorer": "passiva",
    "Evasion": "passiva", "Reliable Talent": "passiva", "Arcane Recovery": "passiva",
    "Open Hand Technique": "passiva", "Frenzy": "bonus", "Stunning Strike": "livre",
    "Song of Rest": "passiva", "Jack of All Trades": "passiva",
    "Channel Divinity": "acao", "Wild Shape": "acao", "Action Surge": "livre",
    # Segunda revisão, depois de listar as 43 que viram botão:
    "Pact Boon": "passiva", "Eldritch Invocation List": "passiva",
    "Cunning Action": "bonus", "Reckless Attack": "livre",
    "Indomitable": "livre", "Stroke of Luck": "livre",
    "Dark One's Own Luck": "livre", "Hurl Through Hell": "livre",
}

# Usos que a prosa não deixa claro, conferidos contra o SRD.
USOS_REVISADOS = {
    "Second Wind": {"max": 1, "descanso": "curto"},
    "Action Surge": {"max": "nivel:1@2,2@17", "descanso": "curto"},
    "Channel Divinity": {"max": "nivel:1@2,2@6,3@18", "descanso": "curto"},
    "Indomitable": {"max": "nivel:1@9,2@13,3@17", "descanso": "longo"},
    "Wild Shape": {"max": 2, "descanso": "curto"},
    "Bardic Inspiration": {"max": "mod_carisma", "descanso": "longo"},
    "Relentless Rage": None,
    "Lay on Hands": {"max": "nivel:x5", "descanso": "longo"},
    "Divine Sense": {"max": "mod_carisma+1", "descanso": "longo"},
    "Wholeness of Body": {"max": 1, "descanso": "longo"},
    "Arcane Recovery": {"max": 1, "descanso": "longo"},
    "Divine Intervention": {"max": 1, "descanso": "longo"},
    "Dark One's Own Luck": {"max": 1, "descanso": "curto"},
    "Hurl Through Hell": {"max": 1, "descanso": "longo"},
    "Stroke of Luck": {"max": 1, "descanso": "curto"},
}


def _tipo_de_uso(desc: str, nome: str) -> str:
    if nome in TIPO_REVISADO:
        return TIPO_REVISADO[nome]
    t = desc.lower()
    if re.search(r"as a bonus action|use a bonus action|bonus action on your turn", t):
        return "bonus"
    if re.search(r"use your reaction|as a reaction|can use your reaction", t):
        return "reacao"
    if re.search(r"as an action|use your action|you can use an action", t):
        return "acao"
    return "passiva"


def _usos(desc: str, nome: str = "") -> dict | None:
    if nome in USOS_REVISADOS:
        return USOS_REVISADOS[nome]
    t = desc.lower()
    # "precisa terminar um descanso ANTES de usar de novo" — o jeito mais comum
    # de o SRD dizer isso, e o que a primeira versão não reconhecia (Retomar o
    # Fôlego e Surto de Ação saíam sem limite).
    m = (re.search(r"until you finish a (short or long|long) rest", t)
         or re.search(r"must finish a (short or long|long) rest before", t)
         or re.search(r"when you finish a (short or long|long) rest", t))
    descanso = None
    if m:
        descanso = "curto" if "short" in m.group(1) else "longo"
    if re.search(r"a number of times equal to your (\w+) modifier", t):
        atributo = re.search(r"a number of times equal to your (\w+) modifier", t).group(1)
        return {"max": f"mod_{SALVAGUARDA_PT.get(atributo, atributo)}",
                "descanso": descanso or "longo"}
    if descanso and re.search(r"once you use this feature|once you do so|"
                              r"you can't use this feature again|once you use it", t):
        return {"max": 1, "descanso": descanso}
    return None


def _linha_da_tabela(feature: dict) -> dict:
    saida = {}
    for item in feature.get("data_for_class_table") or []:
        nivel, valor = item.get("level"), item.get("column_value")
        if nivel is not None and valor not in (None, "", "-"):
            saida[str(nivel)] = str(valor)
    return saida


def _descricoes_existentes() -> dict:
    """As descrições em português que o jogo já tinha, por nome normalizado."""
    try:
        sys.path.insert(0, str(RAIZ))
        import ast
        fonte = (RAIZ / "rpg" / "tools_dnd.py").read_text(encoding="utf-8")
        arvore = ast.parse(fonte)
        for no in arvore.body:
            alvo = getattr(no, "target", None) or (getattr(no, "targets", [None]) or [None])[0]
            if getattr(alvo, "id", "") == "CLASS_FEATURE_DESCS":
                tabela = ast.literal_eval(no.value)
                return {_chave(k): v.get("descricao", "") for k, v in tabela.items()}
    except Exception as e:                                     # pragma: no cover
        print(f"(sem descrições antigas: {e})")
    return {}


def _chave(texto: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def gerar_classes() -> tuple[dict, list]:
    brutas = json.loads((BRUTO / "classes.json").read_text(encoding="utf-8"))
    pt = json.loads(CLASSES_PT.read_text(encoding="utf-8"))
    descricoes_pt = _descricoes_existentes()
    avisos: list[str] = []
    classes: dict = {}

    def caracteristica(f: dict, classe: str, subclasse: str = "") -> dict | None:
        if f["feature_type"] in ("STARTING_EQUIPMENT", "PROFICIENCIES", "PROFICIENCY_BONUS"):
            return None
        info = pt["caracteristicas"].get(f["name"])
        if not info:
            avisos.append(f"SEM NOME EM PORTUGUÊS: {f['name']} ({classe})")
            info = {"nome": f["name"]}
        desc = _limpa(f.get("desc") or "")
        niveis = sorted({g["level"] for g in (f.get("gained_at") or []) if g.get("level")})
        tipo = _tipo_de_uso(desc, f["name"])
        usos = _usos(desc, f["name"])
        if f["name"] in USOS_DA_TABELA:
            # Ki volta no descanso curto; Pontos de Feitiçaria e Fúria, só no
            # longo. A primeira versão punha Feitiçaria junto com o Ki.
            usos = {"max": f"tabela:{USOS_DA_TABELA[f['name']]}",
                    "descanso": "curto" if f["name"] == "Ki" else "longo"}
        if classe == "paladino" and f["name"] == "Channel Divinity":
            # Só o Canalizar Divindade do CLÉRIGO escala (1/2/3). O do paladino
            # é sempre 1 por descanso curto — e o motor dava 2 a partir do 6.
            usos = {"max": 1, "descanso": "curto"}
        progressao = _linha_da_tabela(f) or PROGRESSOES.get(f["name"], {})
        descricao_pt = (descricoes_pt.get(_chave(info["nome"]))
                        or next((descricoes_pt.get(_chave(a)) for a in info.get("apelidos", [])
                                 if descricoes_pt.get(_chave(a))), ""))
        resumo = RESUMO_CARACTERISTICA.get(f["name"], "")
        if not resumo:
            partes = {"passiva": "Passiva", "acao": "Ação", "bonus": "Ação bônus",
                      "reacao": "Reação", "livre": "Livre"}[tipo]
            resumo = partes
        if usos and usos.get("descanso"):
            quantos = usos["max"]
            if quantos == 1:
                resumo += f" · 1 vez por descanso {usos['descanso']}"
            elif isinstance(quantos, int):
                resumo += f" · {quantos} vezes por descanso {usos['descanso']}"
            else:
                resumo += f" · volta no descanso {usos['descanso']}"
        return {
            "chave": _chave(info["nome"]),
            "nome": info["nome"],
            "nome_srd": f["name"],
            "apelidos": info.get("apelidos", []),
            "classe": classe,
            "subclasse": subclasse,
            "niveis": niveis,
            "tipo": tipo,
            "usos": usos,
            "progressao": progressao,
            "resumo": resumo,
            "descricao": descricao_pt,
            "descricao_en": desc,
        }

    base = {c["name"]: c for c in brutas if not c.get("subclass_of")}
    for nome_en, c in sorted(base.items()):
        meta = pt["classes"][nome_en]
        tabela, caracteristicas = {}, []
        for f in c.get("features") or []:
            if f.get("data_for_class_table") and not f.get("gained_at"):
                coluna = pt["colunas"].get(f["name"])
                if coluna:
                    tabela[coluna] = _linha_da_tabela(f)
                continue
            r = caracteristica(f, meta["chave"])
            if r:
                caracteristicas.append(r)
        hp = c.get("hit_points") or {}
        classes[meta["chave"]] = {
            "chave": meta["chave"],
            "nome": meta["nome"],
            "nome_srd": nome_en,
            "dado_de_vida": int(str(c.get("hit_dice") or "D8").upper().lstrip("D") or 8),
            "salvaguardas": [SALVAGUARDA_PT.get((s.get("name") if isinstance(s, dict) else str(s)).lower(), "")
                             for s in (c.get("saving_throws") or [])],
            "conjurador": {"FULL": "completo", "HALF": "metade", "THIRD": "terço",
                           "PACT": "pacto", "NONE": "nenhum"}.get(c.get("caster_type") or "NONE", "nenhum"),
            "pv": hp,
            "tabela": tabela,
            "caracteristicas": sorted(caracteristicas, key=lambda x: (x["niveis"][:1] or [99], x["nome"])),
            "subclasses": {},
        }

    for c in brutas:
        mae = c.get("subclass_of")
        if not mae:
            continue
        classe_pt = pt["classes"][mae["name"]]["chave"]
        nome_sub = pt["subclasses"].get(c["name"], c["name"])
        caracteristicas = [r for r in (caracteristica(f, classe_pt, nome_sub)
                                       for f in (c.get("features") or [])) if r]
        classes[classe_pt]["subclasses"][_chave(nome_sub)] = {
            "chave": _chave(nome_sub), "nome": nome_sub, "nome_srd": c["name"],
            "caracteristicas": sorted(caracteristicas, key=lambda x: (x["niveis"][:1] or [99], x["nome"])),
        }
    return classes, avisos


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

def baixar() -> None:
    BRUTO.mkdir(parents=True, exist_ok=True)
    for nome, caminho in (("magias", "spells/?document__key=srd-2014&limit=100"),
                          ("classes", "classes/?document__key=srd-2014&limit=100")):
        url, tudo = f"https://api.open5e.com/v2/{caminho}", []
        while url:
            pedido = urllib.request.Request(url, headers={"User-Agent": "rpg-agent-srd/1.0"})
            with urllib.request.urlopen(pedido, timeout=60) as r:
                pagina = json.loads(r.read())
            tudo.extend(pagina.get("results") or [])
            url = pagina.get("next")
            time.sleep(0.2)
        (BRUTO / f"{nome}.json").write_text(
            json.dumps(tudo, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"baixado: {nome} ({len(tudo)})")


def gerar_magias() -> tuple[dict, list]:
    brutas = json.loads((BRUTO / "magias.json").read_text(encoding="utf-8"))
    nomes_pt = json.loads(NOMES_PT.read_text(encoding="utf-8"))
    divergencias: list[str] = []
    magias = {}
    for m in sorted(brutas, key=lambda x: (x.get("level") or 0, x["name"])):
        r = magia(m, nomes_pt, divergencias)
        magias[r["chave"]] = r
    sem_nome = [m["name"] for m in brutas if m["name"] not in nomes_pt]
    if sem_nome:
        divergencias.insert(0, f"SEM NOME EM PORTUGUÊS: {sem_nome}")
    return magias, divergencias


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--baixar", action="store_true", help="baixa o SRD de novo antes")
    ap.add_argument("--destino", default="", help="pasta de saída (padrão: rpg/dados)")
    args = ap.parse_args()
    if args.baixar:
        baixar()

    # Pasta própria para quem só quer CONFERIR (o teste de reprodução): gerar
    # no lugar reescreveria o JSON enquanto outros testes, em paralelo, o leem.
    destino = Path(args.destino) if args.destino else DESTINO
    relatorio = destino / "srd_relatorio.txt" if args.destino else RELATORIO
    destino.mkdir(parents=True, exist_ok=True)
    magias, divergencias = gerar_magias()
    (destino / "srd_magias.json").write_text(json.dumps(
        {"_licenca": ATRIBUICAO, "_fonte": "Open5e v2, documento srd-2014",
         "magias": magias}, ensure_ascii=False, indent=1), encoding="utf-8")

    classes, avisos_classes = gerar_classes()
    (destino / "srd_classes.json").write_text(json.dumps(
        {"_licenca": ATRIBUICAO, "_fonte": "Open5e v2, documento srd-2014",
         "classes": classes}, ensure_ascii=False, indent=1), encoding="utf-8")
    n_caract = sum(len(c["caracteristicas"]) + sum(len(s["caracteristicas"])
                                                   for s in c["subclasses"].values())
                   for c in classes.values())
    print(f"classes: {len(classes)}  subclasses: "
          f"{sum(len(c['subclasses']) for c in classes.values())}  características: {n_caract}")
    divergencias = avisos_classes + divergencias

    from collections import Counter
    efeitos = Counter(m["efeito"] for m in magias.values())
    alvos = Counter(m["alvos"] for m in magias.values())
    linhas = [
        f"magias: {len(magias)}",
        f"por efeito: {dict(efeitos)}",
        f"por alvo: {dict(alvos)}",
        f"dano sem dado: {[m['nome_srd'] for m in magias.values() if m['efeito'] == 'dano' and not m['dado']]}",
        f"cura sem dado: {[m['nome_srd'] for m in magias.values() if m['efeito'] == 'cura' and not m['dado']]}",
        "",
        f"DIVERGÊNCIAS ENTRE CAMPO E TEXTO ({len(divergencias)}):",
        *[f"  {d}" for d in divergencias],
    ]
    relatorio.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    print("\n".join(linhas[:5]))
    print(f"divergências: {len(divergencias)} (ver {relatorio})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
