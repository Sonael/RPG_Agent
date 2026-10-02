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
  reacao          acontece no turno do inimigo e o motor usa sozinho, quando
                  faz diferença (Escudo Arcano, Esquiva Sobrenatural) — ver
                  rpg/reacoes.py
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
    # ── Paladino ────────────────────────────────────────────────────────────
    "destruicao divina": {
        "slot": "livre", "alvo": "si", "modos_dinamicos": True,
        "texto": "Sem gastar ação: o próximo acerto corpo a corpo neste turno soma 2d8 radiante "
                 "(+1d8 por círculo acima do 1º, até 5d8; +1d8 contra morto-vivo ou infernal). "
                 "A mana do círculo só é gasta se acertar.",
    },
    "arma sagrada": {
        "slot": "acao", "alvo": "si", "uso": "canalizar divindade",
        "texto": "Ação: até o fim do combate, soma o seu modificador de CAR (mínimo +1) aos ataques com arma.",
    },
    "voto de inimizade": {
        "slot": "bonus", "alvo": "inimigo", "uso": "canalizar divindade",
        "texto": "Ação bônus: vantagem em todos os seus ataques contra o alvo até o fim do combate.",
    },
    "toque purificador": {
        "slot": "acao", "alvo": "aliado",
        "texto": "Ação: encerra uma magia sobre você ou um aliado (encanto, condição ou efeito de magia inimiga). Usos = mod. de CAR por descanso longo.",
    },
    # ── Monge ───────────────────────────────────────────────────────────────
    "artes marciais": {
        "slot": "bonus", "alvo": "inimigo", "exige_ataque": True,
        "texto": "O motor usa DES (se for melhor) e o dado de artes marciais nos golpes desarmados e armas de monge. "
                 "Ação bônus, depois de usar a ação Atacar: um golpe desarmado.",
    },
    "ataque atordoante": {
        "slot": "livre", "alvo": "si", "uso": "ki", "gasta_no_acerto": True,
        "texto": "Sem gastar ação: no próximo acerto corpo a corpo neste turno, gasta 1 ponto de ki e o alvo faz "
                 "salvaguarda de CON (CD de ki); se falhar, fica Atordoado até o fim do seu próximo turno.",
    },
    "mente tranquila": {
        "slot": "acao", "alvo": "si",
        "texto": "Ação: encerra Amedrontado e Enfeitiçado em você.",
    },
    "corpo vazio": {
        "slot": "acao", "alvo": "si", "uso": "ki", "custo_uso": 4,
        "texto": "Ação, 4 pontos de ki: fica Invisível e com resistência a todo dano, exceto força, até o fim do combate.",
    },
    "corpo curativo": {
        "slot": "acao", "alvo": "si",
        "texto": "Ação: recupera 3 × nível de monge em vida. Uma vez por descanso longo.",
    },
    # ── Ladino, patrulheiro ────────────────────────────────────────────────
    "golpe de sorte": {
        "slot": "livre", "alvo": "si",
        "texto": "Sem gastar ação: o próximo ataque que errar neste turno vira acerto. Uma vez por descanso curto.",
    },
    "desaparecer": {
        "slot": "bonus", "alvo": "nenhum",
        "texto": "Ação bônus: esconder-se (Furtividade contra a Percepção dos inimigos; escondido, o próximo ataque tem vantagem).",
    },
    # ── Clérigo, bardo, druida, feiticeiro, bárbaro ───────────────────────
    "intervencao divina": {
        "slot": "acao", "alvo": "nenhum",
        "texto": "Ação: o motor rola d100; se sair até o seu nível de clérigo, a divindade intervém e o Mestre narra como. "
                 "Uma vez por descanso longo.",
    },
    "contra encanto": {
        "slot": "acao", "alvo": "nenhum",
        "texto": "Ação: você e os aliados na sua zona têm vantagem nas salvaguardas contra Amedrontado e Enfeitiçado até o fim do seu próximo turno.",
    },
    "forma selvagem": {
        "slot": "acao", "alvo": "si", "modos_dinamicos": True, "uso_manual": True,
        "texto": "Vira uma fera: a ficha passa a ter a vida, a CA, FOR/DES/CON e os ataques dela. Quando a vida da fera "
                 "chega a 0, você volta e o dano que sobrou passa para você. Não conjura magias na forma de fera.",
    },
    "fonte de magia": {
        "slot": "bonus", "alvo": "si", "modos_dinamicos": True, "uso_manual": True,
        "uso": "pontos de feiticaria",
        "texto": "Ação bônus: troca pontos de feitiçaria por mana (1 por 1) ou mana por pontos (2 de mana dão 1 ponto, "
                 "3 dão 2, 5 dão 3, 6 dão 4, 7 dão 5).",
    },
    "presenca intimidadora": {
        "slot": "acao", "alvo": "inimigo",
        "texto": "Ação: o alvo faz salvaguarda de SAB (CD 8 + prof. + CAR); se falhar, fica Amedrontado até o fim do seu próximo turno.",
    },
    # ── Subclasses e nível alto (rpg/subclasses.py) ─────────────────────────
    "maestria de feitico": {"slot": "livre", "alvo": "si", "modos_dinamicos": True,
                            "texto": "Escolha a magia de 1º e a de 2º círculo que saem sem mana no círculo delas."},
    "assinatura de feitico": {"slot": "livre", "alvo": "si", "modos_dinamicos": True,
                              "texto": "Escolha duas magias de 3º círculo; cada uma sai sem mana uma vez por descanso curto."},
    "metamagia": {"slot": "livre", "alvo": "si", "modos_dinamicos": True, "uso": "pontos de feiticaria",
                  "uso_manual": True,
                  "texto": "Arma uma Metamagia para a próxima magia deste turno (Acelerada, Gêmea, Cuidadosa, "
                           "Intensificada, Potencializada, Sutil...), paga com pontos de feitiçaria quando a magia sai."},
    "mestre sobrenatural": {"slot": "acao", "alvo": "si",
                            "texto": "Ação: o pacto devolve um espaço de 5º círculo (mana). Uma vez por descanso longo."},
    "disparo magico": {"slot": "bonus", "alvo": "inimigo",
                       "texto": "Ação bônus, depois de conjurar uma magia neste turno: um ataque com a arma."},
    "avatar sagrado": {"slot": "acao", "alvo": "nenhum",
                       "texto": "Ação: você e os aliados da sua zona resistem a todo dano até o fim do combate. "
                                "Uma vez por descanso longo."},
    "tornado de folhas": {"slot": "acao", "alvo": "inimigo", "uso": "canalizar divindade",
                          "texto": "Ação: SAB ou o alvo fica Amedrontado até o fim do combate."},
    "anjo vingador": {"slot": "acao", "alvo": "nenhum",
                      "texto": "Ação: asas (mais uma zona por turno), +CAR de dano, e os inimigos da zona fazem SAB "
                               "ou ficam Amedrontados. Uma vez por descanso longo."},
    "ler pensamentos": {"slot": "acao", "alvo": "inimigo", "uso": "canalizar divindade",
                        "texto": "Ação: SAB; se falhar, você lê os pensamentos dele por um minuto (o Mestre diz o que "
                                 "ele pensa)."},
    "coroa da luz": {"slot": "acao", "alvo": "si",
                     "texto": "Ação: até o fim do combate, inimigos fazem com desvantagem as salvaguardas contra "
                              "magias de fogo e radiantes do grupo."},
    "encantar animais e plantas": {"slot": "acao", "alvo": "nenhum", "uso": "canalizar divindade",
                                   "texto": "Ação: animais e plantas inimigos perto fazem SAB ou ficam Enfeitiçados."},
    "bencao do trapaceiro": {"slot": "acao", "alvo": "aliado",
                             "texto": "Ação: um aliado tem vantagem em Furtividade por uma hora."},
    "invocar duplicacao": {"slot": "acao", "alvo": "si", "uso": "canalizar divindade",
                           "texto": "Ação: uma cópia ilusória confunde os inimigos — vantagem nos seus ataques "
                                    "enquanto durar a concentração."},
    "palma vibrante": {"slot": "livre", "alvo": "si", "modos_dinamicos": True, "uso": "ki",
                       "uso_manual": True,
                       "texto": "Vibrar: o próximo golpe que acertar planta a vibração (1 ki). Detonar (ação): CON; "
                                "falha cai a 0 PV, sucesso leva 10d10 necrótico."},
    "salto sombrio": {"slot": "bonus", "alvo": "si", "modos_dinamicos": True,
                      "texto": "Ação bônus, nas sombras (Escuridão ou Névoa): teleporta até duas zonas e ganha "
                               "vantagem no próximo ataque corpo a corpo."},
    "manto sombrio": {"slot": "acao", "alvo": "si",
                      "texto": "Ação, nas sombras: fica Invisível até atacar ou conjurar."},
    "conjuracao elemental": {"slot": "acao", "alvo": "inimigo", "modos_dinamicos": True, "uso": "ki",
                             "custo_uso": 2,
                             "texto": "Ação, 2 ki: Varredura de Fogo (3d6 de fogo na zona) ou Punho do Ar Desatado "
                                      "(3d10 e empurrão)."},
    "terceiro olho": {"slot": "acao", "alvo": "si",
                      "texto": "Ação: você vê o invisível até o fim do combate. Uma vez por descanso curto."},
    "conjuracao veloz": {"slot": "livre", "alvo": "si",
                         "texto": "A próxima magia de conjuração deste turno sai como ação bônus. Uma vez por descanso curto."},
    "teletransporte pequeno": {"slot": "bonus", "alvo": "si", "modos_dinamicos": True,
                               "texto": "Ação bônus: teleporta para a zona vizinha, uma vez por turno."},
    "asas draconicas": {"slot": "bonus", "alvo": "si",
                        "texto": "Ação bônus: asas — mais uma zona de movimento por turno até o fim do combate."},
    "presenca draconica": {"slot": "acao", "alvo": "nenhum", "modos_dinamicos": True,
                           "uso": "pontos de feiticaria", "uso_manual": True,
                           "texto": "Ação, 3 pontos de feitiçaria, concentração: inimigos da zona fazem SAB ou ficam "
                                    "Amedrontados (ou Enfeitiçados)."},
    "esculpir o caos": {"slot": "livre", "alvo": "si", "uso": "pontos de feiticaria", "uso_manual": True,
                        "texto": "2 pontos de feitiçaria: o motor rola o Surto de Magia Selvagem (d100) e o Mestre "
                                 "aplica o efeito."},
    "presenca feerica": {"slot": "acao", "alvo": "nenhum", "modos_dinamicos": True,
                         "texto": "Ação: inimigos da zona fazem SAB ou ficam Enfeitiçados (ou Amedrontados) até o fim do "
                                  "seu próximo turno. Uma vez por descanso curto."},
    "apenas para mim": {"slot": "acao", "alvo": "inimigo",
                        "texto": "Ação: um humanoide faz SAB ou fica Em Transe (não age; SAB no fim de cada turno). "
                                 "Uma vez por descanso curto."},
    "mestrado do grande antigo": {"slot": "acao", "alvo": "inimigo",
                                  "texto": "Ação: SAB ou o alvo ataca um aliado dele. Uma vez por descanso longo."},
    "manobras de combate": {
        "slot": "livre", "alvo": "si", "modos_dinamicos": True, "uso": "dados de superioridade",
        "gasta_no_acerto": True,
        "texto": "Manobras do Mestre de Batalha, pagas com um Dado de Superioridade: as de golpe se armam "
                 "sem gastar ação e valem no próximo acerto com arma do turno (o dado só é gasto se acertar); "
                 "Finta e Reagrupar são ação bônus; Contra-Ataque e Aparar o motor usa sozinho, como reação.",
    },
    "frenesi": {
        "slot": "bonus", "alvo": "inimigo",
        "texto": "Durante a Fúria, ação bônus: um ataque corpo a corpo. Ao fim do combate, ganha 1 nível de exaustão.",
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
    # Os nomes que o jogo grava nas fichas (CLASS_FEATURE_DESCS) caíam como
    # narrativa, embora o motor tenha a regra sob outro nome.
    "ataque descuidado": "ataque imprudente",
    "imposicao de maos": "cura pelas maos",
    "inspiracao bardica": "inspiracao de bardo",
    "repelir mortos vivos": "expulsar mortos vivos",
    "bardic inspiration": "inspiracao de bardo",
    "flurry of blows": "rajada de golpes",
    "patient defense": "defesa paciente",
    "step of the wind": "passo do vento",
    "lay on hands": "cura pelas maos",
    "divine smite": "destruicao divina",
    "combate divino": "destruicao divina",
    "punicao divina": "destruicao divina",
    "smite divino": "destruicao divina",
    "sacred weapon": "arma sagrada",
    "vow of enmity": "voto de inimizade",
    "cleansing touch": "toque purificador",
    "martial arts": "artes marciais",
    "stunning strike": "ataque atordoante",
    "atordoamento": "ataque atordoante",
    "stillness of mind": "mente tranquila",
    "empty body": "corpo vazio",
    "wholeness of body": "corpo curativo",
    "stroke of luck": "golpe de sorte",
    "vanish": "desaparecer",
    "divine intervention": "intervencao divina",
    "intervencao divina inicial": "intervencao divina",
    "countercharm": "contra encanto",
    "contraencanto": "contra encanto",
    "wild shape": "forma selvagem",
    "font of magic": "fonte de magia",
    "intimidating presence": "presenca intimidadora",
    "frenzy": "frenesi",
    "combat superiority": "manobras de combate",
    "spell mastery": "maestria de feitico", "signature spells": "assinatura de feitico",
    "metamagic": "metamagia", "eldritch master": "mestre sobrenatural", "war magic": "disparo magico",
    "eldritch strike": "disparo magico", "holy nimbus": "avatar sagrado", "avenging angel": "anjo vingador",
    "read thoughts": "ler pensamentos", "corona of light": "coroa da luz",
    "charm animals and plants": "encantar animais e plantas", "blessing of the trickster": "bencao do trapaceiro",
    "invoke duplicity": "invocar duplicacao", "quivering palm": "palma vibrante",
    "palma vibrante tremula": "palma vibrante", "shadow step": "salto sombrio", "cloak of shadows": "manto sombrio",
    "disciple of the elements": "conjuracao elemental", "the third eye": "terceiro olho",
    "minor conjuration": "conjuracao veloz", "benign transposition": "teletransporte pequeno",
    "dragon wings": "asas draconicas", "draconic presence": "presenca draconica",
    "controlled chaos": "esculpir o caos", "fey presence": "presenca feerica",
    "dark delirium": "apenas para mim", "create thrall": "mestrado do grande antigo",
    "superioridade em combate": "manobras de combate",
    "maneuvers": "manobras de combate",
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
    # ── Lote 3: magias de combate que eram narrativas ───────────────────────
    "Shillelagh": {"alvos": "si", "efeito": {"arma_conjuracao": True},
                   "texto": "a clava ou o bordão usa o seu atributo de conjuração no ataque e no dano, com dado d8"},
    "True Strike": {"alvos": "marca", "efeito": {"vantagem_ataque": True, "usos": 1},
                    "texto": "vantagem no seu primeiro ataque contra o alvo"},
    "Magic Weapon": {"alvos": "aliado", "efeito": {"atk_bonus": 1, "dano_fixo": 1, "so_arma": True},
                     "escala_bonus": {4: 2, 6: 3},
                     "texto": "+1 no ataque e no dano com a arma de um aliado (+2 no 4º círculo, +3 no 6º)"},
    "Branding Smite": {"alvos": "si", "efeito": {"golpe_dado": "2d6", "golpe_tipo": "radiant"},
                       "escala_golpe": True,
                       "texto": "o próximo acerto com arma soma 2d6 radiante (+1d6 por círculo acima do 2º)"},
    "Sanctuary": {"alvos": "aliado", "efeito": {"santuario": "<cd>"},
                  "texto": "quem quiser atacar o aliado faz salvaguarda de SAB; se falhar, perde o ataque. "
                           "Acaba se o protegido atacar"},
    "Mirror Image": {"alvos": "si", "efeito": {"imagens": 3},
                     "texto": "três cópias: cada ataque pode acertar uma cópia (6+ com três, 8+ com duas, 11+ com uma)"},
    "Blink": {"alvos": "si", "efeito": {"piscar": True},
              "texto": "no fim de cada turno seu, d20 11+: você some para o Plano Etéreo até o seu próximo turno"},
    "Protection from Evil and Good": {"alvos": "aliado", "efeito": {"desvantagem_de_extraplanares": True},
                                      "texto": "aberrações, celestiais, elementais, fadas, infernais e "
                                               "mortos-vivos atacam o aliado com desvantagem"},
    "Warding Bond": {"alvos": "aliado", "efeito": {"ca": 1, "save_fixo": 1, "vinculo": "<conjurador>",
                                                   "resistencias": ["acid", "bludgeoning", "cold", "fire",
                                                                    "force", "lightning", "necrotic",
                                                                    "piercing", "poison", "psychic",
                                                                    "radiant", "slashing", "thunder"]},
                     "texto": "o aliado ganha +1 de CA e nas salvaguardas e resistência a todo dano; "
                              "você leva o mesmo dano que ele"},
    "Beacon of Hope": {"alvos": "aliados", "max": 6,
                       "efeito": {"vantagem_save_atributos": ["sabedoria"], "vantagem_morte": True,
                                  "cura_maxima": True},
                       "texto": "até 6 aliados: vantagem nas salvaguardas de SAB e nos testes contra a morte, "
                                "e toda cura neles rola o máximo"},
    "Protection from Poison": {"alvos": "aliado", "tira": ["envenenado"],
                               "efeito": {"resistencias": ["poison"], "vantagem_save_contra": ["envenenado"]},
                               "texto": "tira Envenenado, dá resistência a veneno e vantagem contra ficar envenenado"},
    "Fly": {"alvos": "aliado", "efeito": {"movimento_por_turno": 1},
            "texto": "o aliado voa: mais uma zona de movimento a cada turno"},
    "Expeditious Retreat": {"alvos": "si", "efeito": {"movimento_por_turno": 1}, "movimento_agora": True,
                            "texto": "Disparada agora e mais uma zona de movimento a cada turno"},
    "Enlarge/Reduce": {"alvos": "aliado", "save_se_inimigo": "constituicao",
                       "modos": {"aumentar": "Aumentar: +1d4 de dano nos ataques com arma",
                                 "reduzir": "Reduzir: -1d4 de dano nos ataques com arma"},
                       "efeito_por_modo": {"aumentar": {"dano_dado": "1d4", "so_arma": True},
                                           "reduzir": {"dano_dado": "-1d4", "so_arma": True}},
                       "texto": "aumenta (+1d4 de dano com arma) ou reduz (-1d4) uma criatura; "
                                "inimigo faz salvaguarda de CON"},
    "Ray of Enfeeblement": {"alvos": "inimigo_ataque",
                            "condicao_magia": {"nome": "Enfraquecido", "salvaguarda_fim": "constituicao"},
                            "texto": "ataque mágico à distância; se acertar, o alvo causa metade do dano com "
                                     "armas de FOR e repete CON no fim de cada turno"},
    "Lesser Restoration": {"alvos": "aliado", "tira_um": ["paralisado", "cego", "envenenado", "surdo"],
                           "texto": "encerra Paralisado, Cego, Envenenado ou Surdo no aliado"},
    "Greater Restoration": {"alvos": "aliado", "tira_um": ["petrificado", "enfeiticado", "amaldicoado", "exaustao"],
                            "texto": "encerra Petrificado, Enfeitiçado ou Amaldiçoado, ou tira 1 nível de exaustão"},
    "Remove Curse": {"alvos": "aliado", "tira": ["amaldicoado"],
                     "texto": "encerra as maldições sobre o aliado"},
    "Spare the Dying": {"alvos": "aliado", "estabilizar": True,
                        "texto": "estabiliza um aliado a 0 PV (para de fazer testes contra a morte)"},
    "Revivify": {"alvos": "aliado", "reviver": True,
                 "texto": "traz de volta, com 1 PV, quem morreu há pouco (na mesma hora do relógio); "
                          "gasta um diamante da mochila"},
    "Misty Step": {"alvos": "si", "teleporte": True,
                   "texto": "teleporta você para uma zona vizinha, sem ataque de oportunidade"},
    # ── Zonas e transformação ───────────────────────────────────────────────
    "Darkness": {"alvos": "nenhum", "zona": "escuridao",
                 "texto": "a zona escolhida fica em escuridão mágica até a concentração cair: quem está nela "
                          "não vê nem é visto (nos ataques, vantagem e desvantagem se anulam), magia que exige "
                          "ver o alvo não entra nem sai dela, e esconder-se lá dentro é automático"},
    "Fog Cloud": {"alvos": "nenhum", "zona": "nevoa",
                  "texto": "a zona escolhida fica tomada por névoa espessa até a concentração cair: quem está "
                           "nela não vê nem é visto (nos ataques, vantagem e desvantagem se anulam), magia que "
                           "exige ver o alvo não entra nem sai dela, e esconder-se lá dentro é automático"},
    "Silence": {"alvos": "nenhum", "zona": "silencio",
                "texto": "nenhum som na zona escolhida até a concentração cair: ninguém lá dentro conjura magia "
                         "com componente verbal, e quem está nela fica surdo e imune a dano de trovão"},
    "Polymorph": {"alvos": "aliado", "transformar": True, "save_se_inimigo": "sabedoria",
                  "texto": "transforma uma criatura numa fera de ND até o nível (ou ND) dela: a ficha vira a da "
                           "fera, inclusive a mente; não fala nem conjura. Inimigo faz SAB. Quando a vida da fera "
                           "chega a 0, volta com o dano que sobrou. Acaba se a concentração cair"},
    "True Polymorph": {"alvos": "aliado", "transformar": True, "verdadeira": True,
                       "save_se_inimigo": "sabedoria",
                       "texto": "transforma uma criatura em outra de ND até o nível (ou ND) dela — fera, "
                                "elemental, morto-vivo — ou num objeto, que sai da luta. Inimigo faz SAB. "
                                "Com uma hora de concentração, fica permanente"},
    "Conjure Elemental": {"alvos": "si", "fora_de_combate": "1 minuto",
                          "invocar": {"concentracao": True, "persistente": False, "acompanha": True,
                                      "hostil_ao_perder": True, "horas": 1},
                          "modos": {"elemental do ar:1": "Elemental do Ar (ND 5)",
                                    "elemental da terra:1": "Elemental da Terra (ND 5)",
                                    "elemental do fogo:1": "Elemental do Fogo (ND 5)",
                                    "elemental da agua:1": "Elemental da Água (ND 5)"},
                          "texto": "um elemental de ND 5 obedece a você enquanto durar a concentração (até "
                                   "1 hora) e entra na próxima luta ao seu lado; se a concentração cair, "
                                   "ele não some: vira inimigo do grupo"},
    # ── Magias que se ligam aos sistemas do jogo ────────────────────────────
    "Identify": {"alvos": "si", "identificar": True, "fora_de_combate": "1 minuto",
                 "texto": "identifica um item da sua mochila (o que ele é, raridade, propriedades)"},
    "Goodberry": {"alvos": "si", "bom_fruto": True,
                  "texto": "dez frutas vão para a mochila; cada uma cura 1 PV ao ser comida, e a magia acaba em "
                           "24 horas"},
    "Enhance Ability": {"alvos": "aliado",
                        "modos": {"touro": "Força do Touro: vantagem nos testes de FOR",
                                  "gato": "Graça do Gato: vantagem nos testes de DES",
                                  "urso": "Vigor do Urso: vantagem nos testes de CON e 2d6 PV temporários",
                                  "aguia": "Esplendor da Águia: vantagem nos testes de CAR",
                                  "raposa": "Astúcia da Raposa: vantagem nos testes de INT",
                                  "coruja": "Sabedoria da Coruja: vantagem nos testes de SAB"},
                        "efeito_por_modo": {"touro": {"vantagem_teste_atributos": ["forca"]},
                                            "gato": {"vantagem_teste_atributos": ["destreza"]},
                                            "urso": {"vantagem_teste_atributos": ["constituicao"]},
                                            "aguia": {"vantagem_teste_atributos": ["carisma"]},
                                            "raposa": {"vantagem_teste_atributos": ["inteligencia"]},
                                            "coruja": {"vantagem_teste_atributos": ["sabedoria"]}},
                        "pv_temp_por_modo": {"urso": "2d6"},
                        "texto": "vantagem nos testes de um atributo (o motor rola o segundo d20 nos testes "
                                 "de perícia e sociais)"},
    "Pass without Trace": {"alvos": "aliados", "max": 8, "efeito": {"bonus_pericia": {"furtividade": 10}},
                           "texto": "+10 nos testes de Furtividade do grupo"},
    "See Invisibility": {"alvos": "si", "horas": 1, "efeito": {"ver_invisivel": True},
                         "texto": "você vê quem está Invisível: atacar não tem desvantagem, e ele não tem "
                                  "vantagem contra você"},
    "True Seeing": {"alvos": "aliado", "horas": 1, "efeito": {"ver_invisivel": True},
                    "texto": "o aliado vê quem está Invisível (e o que é ilusão, o Mestre narra)"},
    "Light": {"alvos": "si", "zona": "luz", "zona_do_conjurador": True, "sem_concentracao": True,
              "texto": "luz clara em torno de você (a zona onde estiver): quem não tem visão no escuro "
                       "passa a ver ali"},
    "Dancing Lights": {"alvos": "si", "zona": "luz", "zona_do_conjurador": True,
                       "texto": "luzes flutuantes iluminam a zona onde você estiver, enquanto durar a "
                                "concentração"},
    "Daylight": {"alvos": "nenhum", "zona": "luz",
                 "texto": "luz do dia na zona escolhida; a Escuridão nela acaba"},
    # ── Segunda leva: magias de combate que faltavam ────────────────────────
    "Dispel Magic": {"alvos": "aliado", "dissipar": True,
                     "texto": "encerra as magias sobre uma criatura (efeitos, condições, encanto, transformação); "
                              "até o círculo usado, sem teste; acima, teste de conjuração contra 10 + círculo. "
                              "Criatura invocada some"},
    "Death Ward": {"alvos": "aliado", "efeito": {"protecao_morte": True}, "horas": 8,
                   "texto": "a primeira vez que a vida do aliado chegaria a 0, fica em 1 (e a magia acaba)"},
    "Protection from Energy": {"alvos": "aliado",
                               "modos": {"acid": "Ácido", "cold": "Frio", "fire": "Fogo",
                                         "lightning": "Elétrico", "thunder": "Trovejante"},
                               "efeito_por_modo": {t: {"resistencias": [t]} for t in
                                                   ("acid", "cold", "fire", "lightning", "thunder")},
                               "texto": "resistência ao tipo de dano escolhido"},
    "Freedom of Movement": {"alvos": "aliado", "horas": 1,
                            "tira": ["paralisado", "contido", "imobilizado", "agarrado"],
                            "efeito": {"imune_condicoes": ["paralisado", "contido", "imobilizado", "agarrado"]},
                            "texto": "o aliado não fica Paralisado, Contido nem Agarrado (e sai disso agora)"},
    "Dimension Door": {"alvos": "si", "teleporte": True, "teleporte_longe": True,
                       "texto": "teleporta você para qualquer zona, sem ataque de oportunidade"},
    "Power Word Kill": {"alvos": "inimigo", "palavra_matar": True,
                        "texto": "quem tem 100 de vida ou menos morre; acima disso, nada"},
    "Irresistible Dance": {"alvos": "inimigo",
                           "condicao_direta": {"nome": "Dançando", "salvaguarda_fim": "sabedoria",
                                               "imune_se": "Enfeitiçado"},
                           "texto": "o alvo dança: não sai do lugar, ataca e esquiva com desvantagem (ataques "
                                    "contra ele têm vantagem); repete SAB no fim de cada turno"},
    "Resilient Sphere": {"alvos": "aliado", "save_se_inimigo": "destreza",
                         "condicao_direta": {"nome": "Na Esfera"},
                         "texto": "uma esfera de força envolve a criatura: nada entra nem sai (ninguém a alcança, "
                                  "ela não age). Inimigo faz DES"},
    "Maze": {"alvos": "inimigo",
             "condicao_direta": {"nome": "No Labirinto", "salvaguarda_fim": "inteligencia", "cd_fixa": 20},
             "texto": "o alvo some num labirinto: não age e ninguém o alcança; INT CD 20 no fim de cada turno "
                      "para sair"},
    "Raise Dead": {"alvos": "aliado", "reviver": True, "prazo_horas": 240, "vida": "1",
                   "fora_de_combate": "1 hora",
                   "texto": "traz de volta, com 1 PV, quem morreu há até 10 dias; gasta um diamante"},
    "Resurrection": {"alvos": "aliado", "reviver": True, "prazo_horas": None, "vida": "max",
                     "fora_de_combate": "1 hora",
                     "texto": "traz de volta, com a vida cheia, quem morreu (não de velhice); gasta um diamante"},
    "True Resurrection": {"alvos": "aliado", "reviver": True, "prazo_horas": None, "vida": "max",
                          "fora_de_combate": "1 hora",
                          "texto": "traz de volta, com a vida cheia, quem morreu; gasta um diamante"},
    "Fire Shield": {"alvos": "si",
                    "modos": {"quente": "Quente: resistência a frio; quem o acertar corpo a corpo leva 2d8 de fogo",
                              "frio": "Frio: resistência a fogo; quem o acertar corpo a corpo leva 2d8 de frio"},
                    "efeito_por_modo": {"quente": {"resistencias": ["cold"], "escudo_de_fogo": "fire"},
                                        "frio": {"resistencias": ["fire"], "escudo_de_fogo": "cold"}},
                    "texto": "chamas quentes ou frias: resistência a frio ou a fogo, e quem acertar você corpo "
                             "a corpo leva 2d8"},
    "Gaseous Form": {"alvos": "aliado", "condicao_direta": {"nome": "Forma Gasosa"},
                     "efeito": {"resistencias": ["bludgeoning", "piercing", "slashing"]},
                     "texto": "vira névoa: resistência a corte, perfuração e concussão, mas não ataca nem conjura"},
    "Levitate": {"alvos": "aliado", "save_se_inimigo": "constituicao",
                 "condicao_direta": {"nome": "Levitando"},
                 "texto": "a criatura flutua: não sai do lugar, e ninguém a alcança corpo a corpo (nem ela "
                          "alcança). Inimigo faz CON"},
    "Gust of Wind": {"alvos": "inimigo", "lufada": True,
                     "texto": "quem está na zona do alvo faz FOR; quem falha é empurrado para longe de você"},
    "Divine Word": {"alvos": "nenhum", "palavra_divina": True,
                    "texto": "inimigos perto fazem CAR; quem falha sofre pela vida que tem: até 50, Surdo; até 40, "
                             "também Cego; até 30, também Atordoado; até 20, morre. Celestiais, elementais, fadas e "
                             "infernais que falham são banidos"},
    "Telekinesis": {"alvos": "inimigo", "telecinese": True,
                    "modos": {"segurar": "Segurar: o alvo fica Contido até o fim do seu próximo turno",
                              "afastar": "Afastar: o alvo vai para a zona vizinha e fica Contido"},
                    "texto": "disputa do seu atributo de conjuração contra a FOR do alvo; nos turnos seguintes, "
                             "usar de novo não gasta mana"},
    "Holy Aura": {"alvos": "aliados", "max": 8,
                  "efeito": {"vantagem_save_atributos": ["forca", "destreza", "constituicao", "inteligencia", "sabedoria", "carisma"], "desvantagem_contra_mim": True},
                  "texto": "você e até 7 aliados: vantagem em todas as salvaguardas, e ataques contra vocês têm "
                           "desvantagem"},
    "Foresight": {"alvos": "aliado", "horas": 8, "fora_de_combate": "1 minuto",
                  "efeito": {"vantagem_ataque": True, "vantagem_save_atributos": ["forca", "destreza", "constituicao", "inteligencia", "sabedoria", "carisma"],
                             "desvantagem_contra_mim": True},
                  "texto": "por 8 horas: vantagem em ataques e salvaguardas, e ataques contra o alvo têm desvantagem"},
    "Globe of Invulnerability": {"alvos": "nenhum", "zona": "globo", "zona_do_conjurador": True,
                                 "texto": "magias de até 5º círculo conjuradas de fora não afetam quem está na sua "
                                          "zona (sem zonas, você)"},
    "Antimagic Field": {"alvos": "nenhum", "zona": "antimagia", "zona_do_conjurador": True,
                        "texto": "na sua zona (sem zonas, em você), que o acompanha, nenhuma magia é conjurada nem "
                                 "atinge quem está lá"},
    "Conjure Minor Elementals": {"alvos": "si", "fora_de_combate": "1 minuto",
                                 "invocar": {"concentracao": True, "persistente": False, "acompanha": True,
                                             "horas": 1},
                                 "modos": {"gargula:1": "1 gárgula (ND 2)",
                                           "mefita de magma:4": "4 mefitas de magma (ND 1/2)",
                                           "mefita de vapor:8": "8 mefitas de vapor (ND 1/4)"},
                                 "texto": "elementais menores obedecem a você enquanto durar a concentração e entram "
                                          "na próxima luta ao seu lado"},
    "Conjure Woodland Beings": {"alvos": "si", "invocar": {"concentracao": True, "persistente": False},
                                "modos": {"driade:2": "2 dríades (ND 1)", "satiro:4": "4 sátiros (ND 1/2)",
                                          "sprite:8": "8 sprites (ND 1/4)"},
                                "texto": "seres feéricos lutam ao seu lado enquanto durar a concentração"},
    "Conjure Fey": {"alvos": "si", "fora_de_combate": "1 minuto",
                    "invocar": {"concentracao": True, "persistente": False, "acompanha": True,
                                "hostil_ao_perder": True, "horas": 1},
                    "modos": {"mamute:1": "Espírito em forma de mamute (ND 6)",
                              "urso polar:1": "Espírito em forma de urso-polar (ND 2)",
                              "escorpiao gigante:1": "Espírito em forma de escorpião gigante (ND 3)"},
                    "texto": "um espírito feérico obedece a você enquanto durar a concentração; se ela cair, ele "
                             "vira inimigo"},
    "Conjure Celestial": {"alvos": "si", "fora_de_combate": "1 minuto",
                          "invocar": {"concentracao": True, "persistente": False, "acompanha": True, "horas": 1},
                          "modos": {"couatl:1": "Couatl (ND 4)"},
                          "texto": "um celestial obedece a você enquanto durar a concentração e entra na próxima "
                                   "luta ao seu lado"},
    "Giant Insect": {"alvos": "si", "invocar": {"concentracao": True, "persistente": False},
                     "modos": {"centopeia gigante:10": "10 centopeias gigantes", "aranha gigante:3": "3 aranhas gigantes",
                               "vespa gigante:5": "5 vespas gigantes", "escorpiao gigante:1": "1 escorpião gigante"},
                     "texto": "insetos gigantes lutam ao seu lado enquanto durar a concentração"},
    "Animate Objects": {"alvos": "si", "invocar": {"concentracao": True, "persistente": False},
                        "modos": {"objeto miudo:10": "10 objetos miúdos", "objeto pequeno:10": "10 objetos pequenos",
                                  "objeto medio:5": "5 objetos médios", "objeto grande:2": "2 objetos grandes",
                                  "objeto enorme:1": "1 objeto enorme"},
                        "texto": "objetos ganham vida e lutam ao seu lado enquanto durar a concentração"},
    "Create Undead": {"alvos": "si", "fora_de_combate": "1 minuto",
                      "invocar": {"concentracao": False, "persistente": True, "horas": 24},
                      "modos": {"carnical:3": "3 carniçais"},
                      "texto": "três carniçais obedecem a você por 24 horas (precisa de cadáveres, à noite)"},
    "Planar Ally": {"alvos": "si", "fora_de_combate": "10 minutos",
                    "invocar": {"concentracao": False, "persistente": True, "horas": 24},
                    "modos": {"couatl:1": "Um couatl (celestial)", "elemental do fogo:1": "Um elemental do fogo",
                              "elemental da terra:1": "Um elemental da terra",
                              "elemental do ar:1": "Um elemental do ar", "elemental da agua:1": "Um elemental da água"},
                    "texto": "uma criatura enviada pela sua divindade serve por um dia (o pagamento, o Mestre "
                             "negocia)"},
    # ── Lote 5: invocações ──────────────────────────────────────────────────
    "Spiritual Weapon": {"alvos": "inimigo", "arma_espiritual": True,
                         "texto": "uma arma espectral ataca agora (ataque mágico corpo a corpo, 1d8 + seu "
                                  "modificador de força); nos turnos seguintes, ação bônus para atacar de novo "
                                  "sem gastar mana, até o fim do combate"},
    "Conjure Animals": {"alvos": "si", "invocar": {"concentracao": True, "persistente": False},
                        "modos": {"urso polar:1": "1 urso-polar (ND 2)",
                                  "lobo atroz:2": "2 lobos atrozes (ND 1)",
                                  "urso pardo:2": "2 ursos-pardos (ND 1)",
                                  "urso negro:4": "4 ursos-negros (ND 1/2)",
                                  "lobo:8": "8 lobos (ND 1/4)"},
                        "texto": "feras do seu lado entram na luta; o motor conduz o turno delas e elas somem "
                                 "se a concentração cair ou no fim do combate"},
    "Find Familiar": {"alvos": "si", "invocar": {"concentracao": False, "persistente": True, "um_so": True},
                      "fora_de_combate": "1 hora",
                      "modos": {"coruja:1": "Coruja", "gato:1": "Gato", "corvo:1": "Corvo",
                                "morcego:1": "Morcego", "rato:1": "Rato", "aranha:1": "Aranha"},
                      "texto": "um familiar acompanha você (não ataca; na luta, ajuda: o próximo ataque contra "
                               "o inimigo ao lado dele tem vantagem)"},
    "Find Steed": {"alvos": "si", "invocar": {"concentracao": False, "persistente": True, "um_so": True},
                   "fora_de_combate": "10 minutos",
                   "modos": {"cavalo de guerra:1": "Cavalo de guerra", "ponei:1": "Pônei"},
                   "texto": "uma montaria leal acompanha você e luta ao seu lado"},
    "Animate Dead": {"alvos": "si", "invocar": {"concentracao": False, "persistente": True, "horas": 24},
                     "fora_de_combate": "1 minuto",
                     "modos": {"esqueleto:1": "Esqueleto", "zumbi:1": "Zumbi"},
                     "texto": "um morto-vivo obedece a você por 24 horas e luta ao seu lado (precisa de um "
                              "cadáver ou ossos, que o Mestre narra)"},
}

# Quem a Proteção contra o Bem e o Mal protege.
_EXTRAPLANARES = ("aberracao", "aberration", "celestial", "elemental", "fada", "fey", "feerico",
                  "fiend", "infernal", "demon", "demonio", "devil", "diabo", "undead", "morto vivo",
                  "zumbi", "esqueleto", "fantasma", "vampir")

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
                        "Compulsion", "Geas"}


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
    "ki": "pontos de ki = nível de monge; o motor gasta nas ações de ki (Rajada de Golpes, Defesa Paciente, "
          "Passo do Vento, Ataque Atordoante, Corpo Vazio) e devolve no descanso curto",
    "indomavel": "quando você falha numa salvaguarda, o motor rola de novo sozinho e fica com o novo resultado "
                 "(1 uso por descanso longo; 2 no 13º, 3 no 17º)",
    "indomitable": "quando você falha numa salvaguarda, o motor rola de novo sozinho e fica com o novo resultado "
                   "(1 uso por descanso longo; 2 no 13º, 3 no 17º)",
    "alma do diamante": "proficiência em todas as salvaguardas; quando você falha numa, o motor gasta 1 ponto de ki "
                        "e rola de novo",
    "diamond soul": "proficiência em todas as salvaguardas; quando você falha numa, o motor gasta 1 ponto de ki "
                    "e rola de novo",
    "mente vazia": "o motor não deixa você ficar Amedrontado nem Enfeitiçado",
    "golpe divino aprimorado": "o motor soma 1d8 radiante a todo acerto com arma corpo a corpo",
    "improved divine smite": "o motor soma 1d8 radiante a todo acerto com arma corpo a corpo",
    "uso de forma selvagem adicional": "a Forma Selvagem passa a ter 3 usos por descanso",
    "forma selvagem do combate": "a Forma Selvagem vira ação bônus e aceita feras de ND 1 já no 2º nível",
    "inspiracao bardica aprimorada": "o motor já rola o dado de Inspiração maior conforme o nível",
    "inspiracao superior aprimorada": "ao rolar iniciativa, o motor devolve todos os usos de Inspiração de Bardo",
    "visao aprofundada": "o motor guarda 3 dados de Lampejos de Adivinhação por descanso longo",
    "lampejos aprimorados": "o motor guarda 4 dados de Lampejos de Adivinhação por descanso longo",
    "atleta notavel": "o motor dá vantagem nos seus testes de Atletismo",
    "bencao do trapaceiro aprimorada": "o motor cobra a Bênção do Trapaceiro como ação bônus",
    "magias lunares": "na Forma Selvagem, o motor deixa conjurar Curar Ferimentos, como ação bônus",
    "restauracao de feiticaria": "no descanso curto, o motor devolve 4 pontos de feitiçaria",
    "inimigo do inimigo": "uma vez por turno, o motor soma os +2 do Inimigo Favorecido contra qualquer criatura",
    "surto de magia selvagem": "a cada magia de 1º círculo ou mais, o motor rola o d20; no 1, rola o d100 do "
                               "Surto e o Mestre aplica o efeito",
    "encontrar familiar aprimorado": "o motor oferece diabrete, pseudodragão, quasit e sprite no Convocar "
                                     "Familiar, e o familiar ataca",
    "dado de superioridade": "o motor gasta os dados nas Manobras de Combate (d8; d10 no 10º, d12 no 18º; "
                             "4 por descanso curto, 5 no 7º, 6 no 15º)",
    "superiority dice": "o motor gasta os dados nas Manobras de Combate",
    "manobras aprimoradas": "o motor sobe o Dado de Superioridade para d10 e oferece as manobras escolhidas",
    "manobras relampago": "o motor dá mais um Dado de Superioridade e oferece as manobras escolhidas",
    "combat wild shape": "a Forma Selvagem vira ação bônus e aceita feras de ND 1 já no 2º nível",
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
        modos = modos_de(chave, char)
        # Destruição Divina do paladino de nível baixo só tem o 1º círculo:
        # perguntar "qual círculo?" com uma opção só seria um clique à toa.
        lista = list(modos) if (len(modos) > 1 or chave in ("forma selvagem", "fonte de magia")) else []
        slot = acao["slot"]
        if chave == "forma selvagem" and char and _circulo_da_lua(char):
            slot = "bonus"
        saida.update(tipo="acao_de_classe", texto=acao["texto"], slot=slot,
                     alvo=acao["alvo"], modos=lista, modos_texto=modos, chave=chave)
        if chave == "manobras de combate":
            from rpg import superioridade
            saida["modos_alvo"] = {m: superioridade.alvo_do_modo(m) for m in lista}
        else:
            from rpg import subclasses
            if any(k[0] == chave for k in subclasses.ALVO_DO_MODO):
                saida["modos_alvo"] = {m: subclasses.ALVO_DO_MODO.get((chave, m), "") for m in lista}
        return saida

    # "Mente Vazia" é a característica do monge e também o nome em português
    # de Mind Blank. Sem custo de mana e sem marca de magia do SRD, é a
    # característica.
    if not int(hab.get("custo_mana", 0) or 0) and not hab.get("nome_srd"):
        for parte in _partes_do_nome(nome):
            if parte in PASSIVAS_NO_MOTOR:
                saida.update(tipo="passiva", texto="Passiva: " + PASSIVAS_NO_MOTOR[parte] + ".")
                return saida

    from rpg import reacoes
    chave_r = reacoes.chave_do_nome(nome)
    if chave_r and not reacoes.REACOES[chave_r].get("recurso"):
        saida.update(tipo="reacao", texto=reacoes.REACOES[chave_r]["texto"], reacao=chave_r)
        return saida

    m = _magia_srd(hab)
    if m and reacoes.chave_da_magia(m["nome_srd"]):
        saida.update(tipo="reacao", texto=reacoes.REACOES[reacoes.chave_da_magia(m["nome_srd"])]["texto"],
                     reacao=reacoes.chave_da_magia(m["nome_srd"]))
        return saida
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
            modos = dict(ef.get("modos") or {})
            if ef.get("zona") and not ef.get("zona_do_conjurador"):
                from rpg import tools_dnd as td
                modos = {z: f"{z}: a área cobre esta zona" for z in td._zonas()} if td._zonas_ativas() else {}
                if not td._zonas_ativas() and (memory.campaign.get("combat_state") or {}).get("is_active"):
                    saida["texto"] = (saida["texto"]
                                      .replace("a zona escolhida", "a área (centrada na criatura que você escolher)")
                                      .replace("na zona escolhida", "na área (centrada na criatura que você escolher)")
                                      .replace("na zona", "na área").replace("da zona", "da área"))
            if ef.get("transformar"):
                modos = _modos_da_polimorfia(bool(ef.get("verdadeira")))
            if m["nome_srd"] == "Find Familiar" and char:
                from rpg import criaturas
                if criaturas._corrente(char):
                    modos.update({"diabrete:1": "Diabrete", "pseudodragao:1": "Pseudodragão",
                                  "quasit:1": "Quasit", "sprite:1": "Sprite"})
            if ef.get("invocar") and char:
                modos.update(modos_de_invocacao_no_circulo(hab, m, ef, char))
            if ef.get("identificar") and char:
                modos = {i["nome"]: i["nome"] for i in (char.get("inventario") or [])
                         if isinstance(i, dict) and i.get("nome") and not i.get("identificado")}
            if ef.get("teleporte") and char:
                from rpg import tools_dnd as td
                if td._zonas_ativas():
                    if ef.get("teleporte_longe"):
                        modos = {z: f"{z}" for z in td._zonas() if z != td._zona_de(char["name"])}
                    else:
                        modos = {z: f"{z}: zona vizinha" for z in _zonas_vizinhas(char)}
            if not modos and not (ef.get("arma_espiritual") and char and reuso_gratis(char, hab)):
                modos = circulos_da_magia(hab, char)
            saida.update(modos=list(modos), modos_texto=modos)
            if ef.get("arma_espiritual") and char and reuso_gratis(char, hab):
                saida["texto"] = "A arma espectral já está em campo: ação bônus para atacar de novo, sem gastar mana."
            return saida
        efeito = m.get("efeito")
        if efeito in ("dano", "cura", "pool") and (m.get("dado") or efeito == "pool"):
            rider = RIDERS_DE_MAGIA.get(m["nome_srd"])
            if rider:
                saida["texto"] = "Além do dano: " + rider["texto"] + "."
            modos = circulos_da_magia(hab, char)
            saida.update(modos=list(modos), modos_texto=modos)
            return saida
        cond = _condicao_da_magia(hab, m)
        textos = {norm(k): (k, v) for k, v in TEXTO_DA_CONDICAO.items()}
        if (efeito == "condicao" and m["nome_srd"] not in NARRATIVAS_COM_TESTE
                and cond in textos):
            nome_cond, texto_cond = textos[cond]
            saida["texto"] = (f"O motor aplica: {nome_cond.capitalize()} — {texto_cond}"
                              + (", enquanto durar a concentração" if m.get("concentracao") else "")
                              + ".")
            if m.get("alvos_por_espaco"):
                modos = circulos_da_magia(hab, char)
                saida.update(modos=list(modos), modos_texto=modos)
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
        if acao.get("modos_dinamicos"):
            modos = modos_de(chave, char)
            if modo not in modos and not (chave == "destruicao divina" and not modo):
                if not modos:
                    return f"Aviso: {hab['nome']} não tem o que fazer agora. Nada foi gasto."
                return (f"Aviso: {hab['nome']} pede uma escolha: "
                        + "; ".join(modos.values()) + ". Nada foi gasto.")
        if chave == "destruicao divina":
            from rpg import tools_dnd as td
            custo = td.SPELL_MANA_COST[int(modo or 1)]
            mana = int((char.get("sheet") or {}).get("mana_atual", 0) or 0)
            if mana < custo:
                return (f"Aviso: Destruição Divina no {int(modo or 1)}º círculo precisa de {custo} "
                        f"mana; {char['name']} tem {mana}. Nada foi gasto.")
        if chave == "forma selvagem" and modo != "voltar":
            from rpg import tools_dnd as td
            if (td.usos_restantes(char, "Forma Selvagem") or 0) <= 0:
                return "Aviso: a Forma Selvagem está gasta. Volta no descanso curto. Nada foi gasto."
        from rpg import subclasses
        if chave in subclasses.EXECUTORES:
            recusa = subclasses.validar(chave, char, alvo, modo)
            if recusa:
                return recusa
        if chave == "manobras de combate" and alvo_do_modo(hab, char, modo) in ("inimigo", "aliado") \
                and not _char(alvo):
            return f"Aviso: escolha o alvo da manobra. Nada foi gasto."
        if chave == "frenesi":
            from rpg import tools_dnd as td
            if not any(e.get("nome") == "Fúria" for e in td._efeitos_de(char)):
                return "Aviso: o Frenesi só vale durante a Fúria. Entre em Fúria primeiro. Nada foi gasto."
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
    if ef and ef["alvos"] in ("marca", "inimigos", "area", "inimigo_ataque") and not _char(alvo):
        return f"Aviso: escolha o alvo de {hab['nome']}. Nada foi gasto."
    circulos = circulos_da_magia(hab, char)
    if modo and modo.startswith("c") and modo[1:].isdigit() and modo not in circulos:
        return f"Aviso: {hab['nome']} não pode ser conjurada nesse círculo agora. Nada foi gasto."
    if ef:
        nome_pt = m.get("nome") or hab.get("nome", "")
        a = _char(alvo)
        _modos_ok = dict(ef.get("modos") or {})
        if m.get("nome_srd") == "Find Familiar":
            from rpg import criaturas
            if criaturas._corrente(char):
                _modos_ok.update({"diabrete:1": "", "pseudodragao:1": "", "quasit:1": "", "sprite:1": ""})
        if ef.get("invocar"):
            _modos_ok.update(modos_de_invocacao_no_circulo(hab, m, ef, char))
        if ef.get("modos") and modo not in _modos_ok:
            return (f"Aviso: {nome_pt} pede uma escolha: " + "; ".join(ef["modos"].values())
                    + ". Nada foi gasto.")
        if ef.get("estabilizar"):
            if not a or int((a.get("sheet") or {}).get("vida_atual", 0) or 0) > 0 \
                    or (a.get("status") or "").lower() == "morto":
                return f"Aviso: {nome_pt} só vale em quem está caído a 0 PV (e vivo). Nada foi gasto."
        if ef.get("reviver"):
            from rpg import tools_dnd as td
            if not a or (a.get("status") or "").lower() != "morto":
                return f"Aviso: {nome_pt} só vale em quem morreu. Nada foi gasto."
            hora = (a.get("sheet") or {}).get("morreu_hora")
            prazo = ef.get("prazo_horas", 1)
            if prazo is not None and (hora is None or td._agora_em_horas() - int(hora) >= prazo):
                return (f"Aviso: {a['name']} morreu há tempo demais para {nome_pt} "
                        f"(só vale logo depois da morte). Nada foi gasto.")
            if not _diamante(char):
                return (f"Aviso: {nome_pt} precisa de um diamante (300 po) na mochila de "
                        f"{char['name']}. Nada foi gasto.")
        if ef.get("zona") and not ef.get("zona_do_conjurador"):
            from rpg import tools_dnd as td
            if td._zonas_ativas() and modo not in td._zonas():
                return (f"Aviso: escolha a zona de {nome_pt} ({', '.join(td._zonas())}). Nada foi gasto.")
            if (not td._zonas_ativas() and (memory.campaign.get("combat_state") or {}).get("is_active")
                    and not a):
                return (f"Aviso: sem zonas, {nome_pt} fica centrada numa criatura: escolha em quem "
                        f"(pode ser você). Nada foi gasto.")
        if ef.get("identificar"):
            itens = [i.get("nome") for i in (char.get("inventario") or []) if isinstance(i, dict)]
            if modo not in itens:
                return f"Aviso: escolha o item da mochila que {nome_pt} vai identificar. Nada foi gasto."
        if ef.get("transformar"):
            from rpg import criaturas
            if not a or not a.get("sheet"):
                return f"Aviso: escolha quem {nome_pt} transforma. Nada foi gasto."
            if modo not in _modos_da_polimorfia(bool(ef.get("verdadeira"))):
                return (f"Aviso: escolha a forma de {nome_pt}. Nada foi gasto.")
            nd_fera = criaturas.nd_valor(criaturas.FICHAS[modo]["nd"]) if modo != "objeto" else 0.0
            if nd_fera > _nd_de(a):
                return (f"Aviso: {criaturas.FICHAS[modo]['nome']} (ND {criaturas.FICHAS[modo]['nd']}) é forte "
                        f"demais para {a['name']}: a fera precisa de ND até o nível (ou ND) dele. Nada foi gasto.")
        if ef.get("fora_de_combate") and (memory.campaign.get("combat_state") or {}).get("is_active"):
            return (f"Aviso: {nome_pt} leva {ef['fora_de_combate']} para conjurar — não dá no meio da luta. "
                    f"Nada foi gasto.")
        if ef.get("arma_espiritual") and not a:
            return f"Aviso: escolha quem a Arma Espiritual ataca. Nada foi gasto."
        if ef.get("teleporte"):
            from rpg import tools_dnd as td
            destinos = ([z for z in td._zonas() if z != td._zona_de(char["name"])]
                        if ef.get("teleporte_longe") else _zonas_vizinhas(char))
            if td._zonas_ativas() and modo not in destinos:
                return (f"Aviso: escolha para qual zona vizinha {nome_pt} leva "
                        f"({', '.join(_zonas_vizinhas(char)) or 'nenhuma'}). Nada foi gasto.")
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
        return aplicar_magia(char, hab, alvo, modo)
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
        # Fora do combate não há ordem de iniciativa: os aliados são o grupo.
        grupo = ([] if (memory.campaign.get("combat_state") or {}).get("is_active") else
                 [c for c in (memory.campaign.get("characters") or {}).values()
                  if isinstance(c, dict) and c.get("sheet") and memory.is_party_member(c)
                  and (c.get("status") or "").lower() not in ("morto", "fugiu")])
        for c in [alvo, char] + _combatentes_vivos() + grupo:
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
    if tipo in ("inimigo_ataque", "inimigo"):
        return [alvo] if alvo else []
    return []


def aplicar_magia(char: dict, hab: dict, alvo_nome: str, modo: str = "") -> str:
    from rpg import tools_dnd as td
    chave, ef = efeito_de_magia(hab)
    m = _magia_srd(hab) or {}
    nome_pt = m.get("nome") or hab.get("nome", "")
    base = int(m.get("nivel", 1) or 1)
    circ = circulo_do_modo(hab, modo) or base
    extra_circ = max(0, circ - base)
    if ef.get("alvos") in ("aliados", "inimigos") and extra_circ and m.get("alvos_por_espaco"):
        ef = dict(ef, max=int(ef.get("max", 1)) + extra_circ)
    if ef.get("zona"):
        return _magia_de_zona(char, hab, ef, modo, nome_pt, alvo_nome)
    if ef.get("palavra_divina"):
        return _palavra_divina(char, nome_pt)
    alvos = _alvos_da_magia(char, ef, alvo_nome)
    if not alvos:
        return f"\n   Ninguém ao alcance de {nome_pt}."
    especial = _magia_especial(char, hab, ef, alvos[0], modo, nome_pt)
    if especial is not None:
        return especial
    linhas = []
    cd = _cd(char)
    for a in alvos:
        if ef.get("save"):
            passou, linha = td._rolar_salvaguarda(a, ef["save"], cd)
            if passou:
                linhas.append(f"{a['name']}: {linha} — resistiu")
                continue
            linhas.append(f"{a['name']}: {linha} — falhou")
        if ef.get("save_se_inimigo") and not _mesmo_lado(char, a):
            passou, linha = td._rolar_salvaguarda(a, ef["save_se_inimigo"], cd)
            if passou:
                linhas.append(f"{a['name']}: {linha} — resistiu")
                continue
            linhas.append(f"{a['name']}: {linha} — falhou")
        efeito = dict(ef.get("efeito") or {})
        efeito.update((ef.get("efeito_por_modo") or {}).get(modo) or {})
        for k, v in list(efeito.items()):
            if v == "<cd>":
                efeito[k] = cd
            elif v == "<conjurador>":
                efeito[k] = memory.char_key(char.get("name", ""))
        if ef.get("escala_bonus"):
            for minimo, bonus in sorted(ef["escala_bonus"].items()):
                if circ >= minimo:
                    efeito["atk_bonus"] = efeito["dano_fixo"] = bonus
        if ef.get("escala_golpe") and extra_circ and efeito.get("golpe_dado"):
            n, faces, _b = td._parse_dice(efeito["golpe_dado"])
            efeito["golpe_dado"] = f"{n + extra_circ}d{faces}"
        if ef.get("armadura_arcana"):
            efeito["ca_minima"] = 13 + _mod(a, "destreza")
        if efeito and ef.get("horas"):
            efeito["ate_hora"] = td._agora_em_horas() + int(ef["horas"])
            efeito["ate"] = "horas"
        if efeito:
            efeito["nome"] = nome_pt
            efeito["origem"] = char.get("name", "")
            efeito["magia"] = hab.get("nome", "")
            if ef["alvos"] == "marca":
                efeito["contra"] = memory.char_key(alvo_nome)
            if m.get("concentracao"):
                efeito["concentracao_de"] = memory.char_key(char.get("name", ""))
            td.dar_efeito_de_combate(a, efeito)
        if (ef.get("pv_temp_por_modo") or {}).get(modo):
            valor_pv, _ = td._rolar_expr(ef["pv_temp_por_modo"][modo])
            st_pv = a.setdefault("sheet", {})
            st_pv["vida_temp"] = max(int(st_pv.get("vida_temp", 0) or 0), valor_pv)
            linhas.append(f"{a['name']}: {st_pv['vida_temp']} PV temporários")
        if ef.get("movimento_agora"):
            _eco()["movimento_extra"] = int(_eco().get("movimento_extra", 0) or 0) + 1
        if ef.get("pv_temp"):
            expr = ef["pv_temp"]
            if expr == "mod":
                attr = td._atributo_de_conjuracao(char.get("sheet") or {}) or "sabedoria"
                valor = max(1, _mod(char, attr))
            else:
                valor, _ = td._rolar_expr(expr)
            # Ajuda e Vida Falsa: +5 por círculo acima do base.
            valor += 5 * extra_circ if chave in ("Aid", "False Life") else 0
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


def _diamante(char: dict) -> dict | None:
    for it in (char or {}).get("inventario") or []:
        if isinstance(it, dict) and any(p in norm(it.get("nome", "")) for p in ("diamante", "diamond")):
            if int(it.get("qtd", 1) or 1) > 0:
                return it
    return None


def _zonas_vizinhas(char: dict) -> list[str]:
    from rpg import tools_dnd as td
    zonas = td._zonas()
    aqui = td._zona_de(char.get("name", ""))
    if aqui not in zonas:
        return []
    i = zonas.index(aqui)
    return [z for j, z in enumerate(zonas) if abs(j - i) == 1]


def _magia_especial(char: dict, hab: dict, ef: dict, a: dict, modo: str, nome_pt: str) -> str | None:
    """
    As magias de efeito que não são um efeito de combate: restauração,
    estabilizar, reviver, teleporte, raio que precisa acertar. None = segue o
    caminho comum de aplicar_magia.
    """
    from rpg import encantos, tools_dnd as td
    if ef.get("invocar"):
        return _invocar(char, hab, ef, modo, nome_pt)
    if ef.get("dissipar"):
        return _dissipar(char, hab, a, modo, nome_pt)
    if ef.get("identificar"):
        return f"\n   {nome_pt}: " + td.identify_item(char["name"], modo)
    if ef.get("bom_fruto"):
        inv = char.setdefault("inventario", [])
        inv.append({"nome": "Bom Fruto", "qtd": 10, "descricao": "Cura 1 PV ao ser comido. Perde a magia em 24 h.",
                    "expira_hora": td._agora_em_horas() + 24, "identificado": True, "custom": False})
        return f"\n   {nome_pt}: dez Bons Frutos na mochila de {char['name']} (1 PV cada, por 24 horas)."

    if ef.get("palavra_matar"):
        st_a = a.setdefault("sheet", {})
        vida = int(st_a.get("vida_atual", 0) or 0)
        if vida > 100:
            return f"\n   {nome_pt}: {a['name']} tem {vida} de vida — mais de 100, nada acontece."
        if any(e.get("protecao_morte") for e in td._efeitos(st_a)):
            st_a["efeitos"] = [e for e in st_a.get("efeitos") or [] if not e.get("protecao_morte")]
            return f"\n   {nome_pt}: a Proteção contra a Morte de {a['name']} se desfaz no lugar dele."
        st_a["vida_atual"] = 0
        td._mark_at_zero_hp(a, char["name"])
        a["status"] = "morto"
        st_a["morreu_hora"] = td._agora_em_horas()
        return f"\n   {nome_pt}: {a['name']} ({vida} de vida) MORRE."
    if ef.get("lufada"):
        return _lufada(char, a, nome_pt)
    if ef.get("telecinese"):
        return _telecinese(char, a, modo, nome_pt)
    if ef.get("condicao_direta"):
        cfg = ef["condicao_direta"]
        pre = ""
        if ef.get("save_se_inimigo") and not _mesmo_lado(char, a):
            passou, linha = td._rolar_salvaguarda(a, ef["save_se_inimigo"], _cd(char))
            if passou:
                return f"\n   {nome_pt}: {a['name']}: {linha} — resistiu."
            pre = f"\n   {a['name']}: {linha} — falhou."
        if cfg.get("imune_se") and td._imune_a_condicao(a, cfg["imune_se"]):
            return f"\n   {nome_pt}: {a['name']} não pode ser {cfg['imune_se']} — imune."
        _tirar_condicoes(a, (cfg["nome"],))
        cond = {"nome": cfg["nome"], "duracao": None, "por": char["name"], "magia": hab.get("nome", "")}
        m_c = _magia_srd(hab) or {}
        if m_c.get("concentracao"):
            cond["concentracao_de"] = memory.char_key(char.get("name", ""))
        if cfg.get("salvaguarda_fim"):
            cond["salvaguarda_fim"] = {"atributo": cfg["salvaguarda_fim"], "cd": int(cfg.get("cd_fixa") or _cd(char))}
        a.setdefault("sheet", {}).setdefault("condicoes", []).append(cond)
        if ef.get("efeito"):
            efeito = dict(ef["efeito"], nome=nome_pt, origem=char.get("name", ""), magia=hab.get("nome", ""))
            if m_c.get("concentracao"):
                efeito["concentracao_de"] = memory.char_key(char.get("name", ""))
            td.dar_efeito_de_combate(a, efeito)
        return pre + f"\n   {nome_pt}: {a['name']} — {ef['texto']}."
    if ef.get("palavra_divina"):
        return _palavra_divina(char, nome_pt)
    if ef.get("transformar"):
        from rpg import criaturas
        if not _mesmo_lado(char, a):
            passou, linha = td._rolar_salvaguarda(a, "sabedoria", _cd(char))
            if passou:
                return f"\n   {nome_pt}: {a['name']}: {linha} — resistiu."
            pre = f"\n   {a['name']}: {linha} — falhou."
        else:
            pre = ""
        permanente_em = td._agora_em_horas() + 1 if ef.get("verdadeira") else None
        if modo == "objeto":
            _tirar_condicoes(a, ("objeto",))
            a.setdefault("sheet", {}).setdefault("condicoes", []).append(
                {"nome": "Objeto", "duracao": None, "por": char["name"], "magia": hab.get("nome", ""),
                 "concentracao_de": memory.char_key(char.get("name", "")), "permanente_em": permanente_em,
                 "origem": nome_pt})
            return (pre + f"\n   {nome_pt}: {a['name']} vira um objeto inerte — sai da luta enquanto "
                    f"durar a concentração (permanente depois de uma hora).")
        return pre + "\n   " + criaturas.transformar(
            a, modo, origem=nome_pt, concentracao_de=memory.char_key(char.get("name", "")),
            magia=hab.get("nome", ""), mental=True, permanente_em=permanente_em)
    if ef.get("arma_espiritual"):
        return _arma_espiritual(char, hab, a, modo, nome_pt)
    st = a.setdefault("sheet", {})
    if ef.get("tira_um"):
        for alvo_c in ef["tira_um"]:
            if alvo_c == "exaustao" and int(st.get("exaustao", 0) or 0) > 0:
                st["exaustao"] = int(st["exaustao"]) - 1
                return f"\n   {nome_pt}: {a['name']} perde 1 nível de exaustão (agora {st['exaustao']})."
            if alvo_c == "enfeiticado" and encantos.ativo(a):
                return f"\n   {nome_pt}: {encantos.quebrar(a, nome_pt)}"
            tiradas = _tirar_condicoes(a, (alvo_c,))
            if tiradas:
                return f"\n   {nome_pt}: {a['name']} se livra de {tiradas[0]}."
        return f"\n   {nome_pt}: {a['name']} não tinha nada que a magia encerre."
    if ef.get("estabilizar"):
        a["status"] = "estabilizado"
        st["death_saves_sucessos"] = st["death_saves_falhas"] = 0
        return f"\n   {nome_pt}: {a['name']} está ESTABILIZADO (0 PV, não faz mais testes contra a morte)."
    if ef.get("reviver"):
        pedra = _diamante(char)
        pedra["qtd"] = int(pedra.get("qtd", 1) or 1) - 1
        if pedra["qtd"] <= 0:
            char["inventario"] = [x for x in char.get("inventario") or [] if x is not pedra]
        a["status"] = "vivo" if memory.is_party_member(a) else (a.get("lado") or "aliado")
        st["vida_atual"] = int(st.get("vida_max", 1) or 1) if ef.get("vida") == "max" else 1
        st["death_saves_sucessos"] = st["death_saves_falhas"] = 0
        st.pop("morreu_hora", None)
        return (f"\n   {nome_pt}: {a['name']} volta à vida com {st['vida_atual']} PV. "
                f"O diamante ({pedra.get('nome')}) virou pó.")
    if ef.get("teleporte"):
        if not td._zonas_ativas():
            return (f"\n   {nome_pt}: sem zonas neste combate, o motor não tem para onde mover. "
                    f"(Mestre: narre o teletransporte de até 9 m.)")
        cs = memory.campaign.get("combat_state") or {}
        de = td._zona_de(char.get("name", ""))
        cs.setdefault("posicoes", {})[memory.char_key(char.get("name", ""))] = modo
        return f"\n   {nome_pt}: {char['name']} some de {de} e aparece em {modo}, sem ataque de oportunidade."
    if ef.get("alvos") == "inimigo_ataque":
        acertou, _crit, linha = td._rolar_ataque_magico(char, a, hab)
        if not acertou:
            return linha
        cfg = ef.get("condicao_magia") or {}
        _tirar_condicoes(a, (cfg.get("nome", ""),))
        cond = {"nome": cfg["nome"], "duracao": None, "por": char["name"], "magia": hab.get("nome", ""),
                "concentracao_de": memory.char_key(char.get("name", ""))}
        if cfg.get("salvaguarda_fim"):
            cond["salvaguarda_fim"] = {"atributo": cfg["salvaguarda_fim"], "cd": _cd(char)}
        st.setdefault("condicoes", []).append(cond)
        return linha + f"\n   {nome_pt}: {a['name']} fica {cfg['nome'].upper()} — {ef['texto']}."
    return None


# ── Dissipar Magia, Lufada de Vento, Telecinésia, Palavra Divina ─────────────

def _nivel_da_magia_nome(nome: str) -> int:
    m = _magia_srd({"nome": nome or ""}) or {}
    return int(m.get("nivel", 0) or 0)


def _dissipar(char: dict, hab: dict, a: dict, modo: str, nome_pt: str) -> str:
    """Encerra as magias sobre a criatura: até o círculo usado sem teste; acima, teste."""
    from rpg import criaturas, encantos, tools_dnd as td
    circ = circulo_do_modo(hab, modo) or 3
    attr = td._atributo_de_conjuracao(char.get("sheet") or {}) or "sabedoria"
    linhas = []

    def _vence(nivel: int, rotulo: str) -> bool:
        if nivel <= circ:
            return True
        d20 = random.randint(1, 20)
        total = d20 + _mod(char, attr)
        ok = total >= 10 + nivel
        linhas.append(f"{rotulo} ({nivel}º círculo): teste {d20} + mod = {total} vs CD {10 + nivel} — "
                      + ("dissipada" if ok else "resiste"))
        return ok

    if isinstance(a.get("invocacao"), dict):
        n = _nivel_da_magia_nome(a["invocacao"].get("magia", ""))
        if _vence(n, a["invocacao"].get("magia", "")):
            return f"\n   {nome_pt}: " + criaturas.dispensar(a, "dissipada")
    st = a.setdefault("sheet", {})
    if encantos.ativo(a):
        n = _nivel_da_magia_nome(encantos.ativo(a).get("magia_srd", ""))
        if _vence(n, "encanto"):
            linhas.append(encantos.quebrar(a, nome_pt))
    fs = st.get("_forma_selvagem")
    if fs and fs.get("magia"):
        if _vence(_nivel_da_magia_nome(fs["magia"]), fs.get("origem", "transformação")):
            linhas.append(criaturas.voltar(a, nome_pt))
    for c in list(st.get("condicoes") or []):
        if isinstance(c, dict) and c.get("magia") and not c.get("encanto"):
            if _vence(_nivel_da_magia_nome(c["magia"]), c.get("nome", "")):
                st["condicoes"].remove(c)
                linhas.append(f"{c.get('nome')} acaba")
    for e in list(td._efeitos(st)):
        if e.get("magia"):
            if _vence(_nivel_da_magia_nome(e["magia"]), e.get("nome", "")):
                st["efeitos"] = [x for x in st.get("efeitos") or [] if x is not e]
                linhas.append(f"{e.get('nome')} acaba")
    if not linhas:
        return f"\n   {nome_pt}: nenhuma magia sobre {a['name']} para dissipar."
    return f"\n   {nome_pt} em {a['name']}:" + "".join(f"\n   • {l}" for l in linhas)


def _empurrar_para_longe(quem: dict, de: dict) -> str:
    from rpg import tools_dnd as td
    zonas = td._zonas()
    za, zq = td._zona_de(de["name"]), td._zona_de(quem["name"])
    if zq not in zonas:
        return ""
    i = zonas.index(zq)
    passo = 1 if (za not in zonas or zonas.index(za) <= i) else -1
    j = i + passo if 0 <= i + passo < len(zonas) else i - passo
    if not 0 <= j < len(zonas) or j == i:
        return ""
    memory.campaign["combat_state"].setdefault("posicoes", {})[memory.char_key(quem["name"])] = zonas[j]
    return zonas[j]


def _lufada(char: dict, a: dict, nome_pt: str) -> str:
    from rpg import tools_dnd as td
    afetados = [c for c in _combatentes_vivos() if c is not char and _perto(a, c)] if td._zonas_ativas() else [a]
    linhas = []
    for c in afetados:
        passou, linha = td._rolar_salvaguarda(c, "forca", _cd(char))
        if passou:
            linhas.append(f"{c['name']}: {linha} — firme")
            continue
        destino = _empurrar_para_longe(c, char) if td._zonas_ativas() else ""
        linhas.append(f"{c['name']}: {linha} — empurrado" + (f" para {destino}" if destino else " (o Mestre narra)"))
    return f"\n   {nome_pt}:" + "".join(f"\n   • {l}" for l in linhas)


def _telecinese(char: dict, a: dict, modo: str, nome_pt: str) -> str:
    from rpg import tools_dnd as td
    attr = td._atributo_de_conjuracao(char.get("sheet") or {}) or "inteligencia"
    d1, d2 = random.randint(1, 20), random.randint(1, 20)
    meu, dele = d1 + _mod(char, attr), d2 + _mod(a, "forca")
    if meu <= dele:
        return (f"\n   {nome_pt}: {meu} contra FOR {dele} de {a['name']} — ele resiste.")
    onde = ""
    if modo == "afastar" and td._zonas_ativas():
        destino = _empurrar_para_longe(a, char)
        onde = f" e o leva para {destino}" if destino else ""
    _tirar_condicoes(a, ("contido",))
    a.setdefault("sheet", {}).setdefault("condicoes", []).append(
        {"nome": "Contido", "duracao": None, "por": char["name"], "magia": "Telekinesis",
         "ate_fim_turno_de": memory.char_key(char.get("name", "")), "desde_token": _token()})
    return (f"\n   {nome_pt}: {meu} contra FOR {dele} de {a['name']} — {char['name']} o ergue{onde}: "
            f"CONTIDO até o fim do próximo turno de {char['name']}.")


_BANIDOS_PELA_PALAVRA = ("celestial", "elemental", "fey", "fada", "feerico", "fiend", "infernal", "demon", "devil")


def _palavra_divina(char: dict, nome_pt: str) -> str:
    from rpg import tools_dnd as td
    linhas = []
    for c in _combatentes_vivos():
        if _mesmo_lado(char, c) or not _perto(char, c, 1):
            continue
        passou, linha = td._rolar_salvaguarda(c, "carisma", _cd(char))
        if passou:
            linhas.append(f"{c['name']}: {linha} — resiste")
            continue
        st = c.setdefault("sheet", {})
        vida = int(st.get("vida_atual", 0) or 0)
        if _e_do_tipo(c, _BANIDOS_PELA_PALAVRA):
            _tirar_condicoes(c, ("banido",))
            st.setdefault("condicoes", []).append({"nome": "Banido", "duracao": None, "magia": "Divine Word"})
            linhas.append(f"{c['name']}: {linha} — BANIDO para o plano de origem")
            continue
        if vida <= 20:
            st["vida_atual"] = 0
            td._mark_at_zero_hp(c, char["name"])
            c["status"] = "morto"
            st["morreu_hora"] = td._agora_em_horas()
            linhas.append(f"{c['name']}: {linha} — MORRE ({vida} de vida)")
            continue
        novas = ["Surdo"] + (["Cego"] if vida <= 40 else []) + (["Atordoado"] if vida <= 30 else [])
        if vida > 50:
            linhas.append(f"{c['name']}: {linha} — com {vida} de vida, nada sofre")
            continue
        for n in novas:
            _tirar_condicoes(c, (n,))
            st.setdefault("condicoes", []).append({"nome": n, "duracao": None, "magia": "Divine Word"})
        linhas.append(f"{c['name']}: {linha} — {', '.join(novas).upper()} ({vida} de vida)")
    if not linhas:
        return f"\n   {nome_pt}: nenhum inimigo perto o bastante para ouvir."
    return f"\n   {nome_pt}:" + "".join(f"\n   • {l}" for l in linhas)


# ── Magias de zona (Escuridão, Névoa Obscurecente, Silêncio) ──────────────────

def _magia_de_zona(char: dict, hab: dict, ef: dict, modo: str, nome_pt: str, alvo_nome: str = "") -> str:
    """
    Com zonas, a área cobre a zona escolhida. Sem zonas — o combate não sabe
    quem está ao lado de quem — a área fica centrada numa criatura escolhida
    e cobre a ela, como a Bola de Fogo sem zonas cai no alvo escolhido.
    """
    from rpg import tools_dnd as td
    cs = memory.campaign.get("combat_state") or {}
    if not cs.get("is_active"):
        return (f"\n   {nome_pt}: fora do combate, o motor não tem área para marcar. "
                f"(Mestre: narre a área e o efeito.)")
    lista = [z for z in cs.get("efeitos_de_zona") or []
             if not (z.get("concentracao_de") == memory.char_key(char.get("name", ""))
                     and norm(z.get("magia", "")) == norm(hab.get("nome", "")))]
    entrada = {"tipo": ef["zona"], "nome": nome_pt,
               "concentracao_de": memory.char_key(char.get("name", "")), "magia": hab.get("nome", "")}
    if ef.get("sem_concentracao"):
        entrada.pop("concentracao_de")
    if ef["zona"] == "luz":
        alvo_luz = memory.char_key((_char(alvo_nome) or char).get("name", ""))
        lista = [z for z in lista if not (z.get("tipo") == "escuridao" and (
            (td._zonas_ativas() and z.get("zona") == modo) or (not td._zonas_ativas() and z.get("criatura") == alvo_luz)))]
    if ef.get("zona_do_conjurador"):
        # Acompanha quem conjurou: a zona é calculada na hora (_efeitos_de_zona).
        entrada["segue"] = memory.char_key(char.get("name", ""))
        entrada["criatura"] = entrada["segue"]
        onde = f"em torno de {char['name']}"
    elif td._zonas_ativas():
        entrada["zona"] = modo
        onde = f"em {modo}"
    else:
        a = _char(alvo_nome) or char
        entrada["criatura"] = memory.char_key(a.get("name", ""))
        onde = f"centrada em {a['name']}"
    lista.append(entrada)
    cs["efeitos_de_zona"] = lista
    texto = ef["texto"] if td._zonas_ativas() else ef["texto"].replace("a zona escolhida", "a área")\
        .replace("na zona escolhida", "na área").replace("na zona", "na área").replace("da zona", "da área")
    return f"\n   {nome_pt} {onde}: {texto}."


def _modos_da_polimorfia(verdadeira: bool = False) -> dict:
    """Polimorfia: só feras. Polimorfia Verdadeira: qualquer criatura, ou um objeto."""
    from rpg import criaturas
    saida = {chave: f"{f['nome']}: ND {f['nd']}, {f['pv']} PV, CA {f['ca']}"
             for chave, f in criaturas.FICHAS.items() if verdadeira or f["tipo"] == "beast"}
    if verdadeira:
        saida["objeto"] = "Objeto: vira uma coisa inerte e sai da luta"
    return saida


def _nd_de(ch: dict) -> float:
    from rpg import criaturas
    s = ch.get("sheet") or {}
    if memory.is_party_member(ch) or norm(s.get("classe", "")) not in ("npc", ""):
        return float(int(s.get("nivel", 1) or 1))
    try:
        return criaturas.nd_valor(str(s.get("cr") or s.get("nivel", 1)))
    except (ValueError, ZeroDivisionError):
        return float(int(s.get("nivel", 1) or 1))


# ── Invocações ───────────────────────────────────────────────────────────────

def _invocar(char: dict, hab: dict, ef: dict, modo: str, nome_pt: str) -> str:
    from rpg import criaturas, tools_dnd as td
    cfg = ef["invocar"]
    chave, _, n = (modo or "").split("@")[0].partition(":")
    quantos = int(n or 1)
    if cfg.get("um_so"):
        criaturas.dispensar_de(memory.char_key(char.get("name", "")), hab.get("nome", ""), "substituído")
    ate = td._agora_em_horas() + int(cfg["horas"]) if cfg.get("horas") else None
    nomes = criaturas.invocar(char, chave, quantos, hab.get("nome", ""),
                              concentracao=bool(cfg.get("concentracao")),
                              persistente=bool(cfg.get("persistente")), ate_hora=ate,
                              acompanha=cfg.get("acompanha"),
                              hostil_ao_perder=bool(cfg.get("hostil_ao_perder")))
    na_luta = (memory.campaign.get("combat_state") or {}).get("is_active")
    return (f"\n   {nome_pt}: " + ", ".join(nomes) + (" entram na luta ao lado de " + char["name"]
                                                    + " (o turno delas é seu, na ordem de iniciativa)."
                                                    if na_luta and len(nomes) > 1
                                                    else (" entra na luta ao lado de " + char["name"] + "."
                                                          if na_luta else f" acompanha {char['name']}."))
            + (f" Some em {cfg['horas']} hora{'s' if int(cfg['horas']) > 1 else ''}."
               if cfg.get("horas") else ""))


def _arma_espiritual(char: dict, hab: dict, alvo: dict, modo: str, nome_pt: str) -> str:
    """Cria (ou reusa) a arma espectral e ataca: 1d8 + mod de força, +1d8 a cada 2 círculos acima do 2º."""
    from rpg import tools_dnd as td
    ativa = next((e for e in td._efeitos_de(char) if e.get("arma_espiritual")), None)
    if not ativa:
        circ = circulo_do_modo(hab, modo) or 2
        dados = 1 + max(0, circ - 2) // 2
        ativa = {"nome": "Arma Espiritual", "arma_espiritual": f"{dados}d8", "magia": hab.get("nome", "")}
        td.dar_efeito_de_combate(char, ativa)
        abre = f"\n   {nome_pt}: uma arma espectral surge ao lado de {alvo['name']}."
    else:
        abre = f"\n   {nome_pt}: a arma espectral ataca de novo (sem gastar mana)."
    acertou, critico, linha = td._rolar_ataque_magico(char, alvo, hab)
    if not acertou:
        return abre + linha
    n, faces, _b = td._parse_dice(ativa["arma_espiritual"])
    rolls = [random.randint(1, faces) for _ in range(n * (2 if critico else 1))]
    attr = td._atributo_de_conjuracao(char.get("sheet") or {}) or "sabedoria"
    total = sum(rolls) + max(0, _mod(char, attr))
    res = td._apply_damage(alvo, total, "force", source_name=char["name"], arma_magica=True)
    texto = (abre + linha + f"\n   Dano: [{' + '.join(map(str, rolls))}] + mod = **{total}** de força"
             + td._fmt_notas(res["notas"])
             + f"\n   {alvo['name']}: {res['hp_antes']} → {res['hp_depois']}/{alvo['sheet'].get('vida_max')}")
    if res["hp_depois"] == 0 and res["hp_antes"] > 0:
        texto += td._mark_at_zero_hp(alvo, char["name"])
    return texto


def reuso_gratis(char: dict, hab: dict) -> bool:
    """A Arma Espiritual já está em campo: atacar de novo não gasta mana."""
    from rpg import tools_dnd as td
    m = _magia_srd(hab) or {}
    if m.get("nome_srd") == "Telekinesis":
        atual = ((char.get("sheet") or {}).get("concentracao") or {})
        return norm(atual.get("magia", "")) == norm(hab.get("nome", ""))
    return m.get("nome_srd") == "Spiritual Weapon" and any(
        e.get("arma_espiritual") for e in td._efeitos_de(char))


# ── Rituais ──────────────────────────────────────────────────────────────────
_CLASSES_DE_RITUAL = ("bardo", "clerigo", "druida", "mago")


def pode_ritual(char: dict, hab: dict) -> bool:
    """A magia é ritual e a classe conjura rituais (bruxo só com o Livro das Sombras)."""
    from rpg import tools_dnd as td
    m = _magia_srd(hab) or {}
    if not m.get("ritual"):
        return False
    classe = norm((char.get("sheet") or {}).get("classe", ""))
    if classe in _CLASSES_DE_RITUAL:
        return True
    return classe == "bruxo" and td._tem_habilidade(
        char, "livro das sombras", "pacto do tomo", "book of ancient secrets", "livro de segredos antigos")


# ── Conjurar com mais mana ───────────────────────────────────────────────────
_ESCALA_RE = re.compile(r"increases? by (\d+)d(\d+) for (each|every two) slot levels? above", re.I)


def dado_no_circulo(hab: dict, formula: str, circulo: int) -> str:
    """O dado da magia conjurada num círculo acima do dela (SRD: 'At Higher Levels')."""
    from rpg import tools_dnd as td
    m = _magia_srd(hab) or {}
    base = int(m.get("nivel", 1) or 1)
    if circulo <= base:
        return formula
    tabela = m.get("escala_espaco") or {}
    if str(circulo) in tabela:
        return tabela[str(circulo)]
    achado = _ESCALA_RE.search(m.get("nivel_superior_en") or "")
    if not achado or not formula:
        return formula
    n_extra, faces = int(achado.group(1)), int(achado.group(2))
    passos = circulo - base
    if achado.group(3).lower().startswith("every two"):
        passos //= 2
    n, f, bonus = td._parse_dice(formula)
    if f != faces:
        return formula
    return f"{n + n_extra * passos}d{f}" + (f"+{bonus}" if bonus > 0 else (str(bonus) if bonus < 0 else ""))


def _escala(m: dict) -> bool:
    return bool(m.get("escala_espaco") or m.get("alvos_por_espaco")
                or _ESCALA_RE.search(m.get("nivel_superior_en") or "")
                or m.get("nome_srd") in ("Aid", "False Life", "Magic Weapon", "Branding Smite",
                                         "Spiritual Weapon", "Dispel Magic")
                or m.get("nome_srd") in ESCALA_DE_INVOCACAO)


def circulos_da_magia(hab: dict, char: dict | None) -> dict:
    """
    id ("c3") → texto, quando a magia escala e o personagem alcança um círculo
    acima do dela com a mana que tem. {} quando não há escolha a fazer.
    """
    from rpg import tools_dnd as td
    m = _magia_srd(hab) or {}
    base = int(m.get("nivel", 0) or 0)
    if not char or base < 1 or not _escala(m):
        return {}
    s = char.get("sheet") or {}
    teto = td._nivel_maximo_de_magia(s)
    mana = int(s.get("mana_atual", 0) or 0)
    if teto <= base:
        return {}
    saida = {}
    formula = td.dado_efetivo(hab, char)
    for c in range(base, teto + 1):
        custo = int(hab.get("custo_mana", 0) or 0) if c == base else td.SPELL_MANA_COST[c]
        if c > base and custo > mana:
            break
        dado = dado_no_circulo(hab, formula, c) if formula else ""
        n_proj = projeteis(hab, c)
        if n_proj and dado:
            rotulo = PROJETEIS[(_magia_srd(hab) or {}).get("nome_srd", "")]["rotulo"]
            dado = f"{n_proj} {rotulo}s de {dado}"
        elif (m.get("alvos_por_espaco") and not formula and c > base):
            dado = f"{alvos_no_circulo(hab, c)} alvos"
        saida[f"c{c}"] = f"{c}º círculo: {custo} mana" + (f" · {dado}" if dado else "")
    return saida if len(saida) > 1 else {}


def circulo_do_modo(hab: dict, modo: str) -> int:
    modo = modo or ""
    if "@" in modo:                       # invocação num círculo acima: "lobo:16@c5"
        modo = modo.rsplit("@", 1)[1]
    if modo.startswith("c") and modo[1:].isdigit():
        return int(modo[1:])
    return 0


# ── Mais criaturas (ou mais fortes) num círculo acima (SRD, "At Higher Levels") ──
#   vezes    círculo → multiplicador do número de criaturas (Conjurar Animais)
#   objetos  dois objetos miúdos a mais por círculo (Animar Objetos)
#   mais_um  uma criatura a mais por círculo (Criar Mortos-Vivos)
#   extras   círculo → modos que só existem dali para cima (ND maior)
ESCALA_DE_INVOCACAO = {
    "Conjure Animals": {"vezes": {5: 2, 7: 3, 9: 4}},
    "Conjure Minor Elementals": {"vezes": {6: 2, 8: 3}},
    "Conjure Woodland Beings": {"vezes": {6: 2, 8: 3}},
    "Animate Objects": {"objetos": True},
    "Create Undead": {"mais_um": True},
    "Conjure Elemental": {"extras": {6: {"perseguidor invisivel:1": "Perseguidor Invisível (ND 6)"}}},
    # ND +1 por círculo acima do 6º: as feras do SRD de ND 7 e 8.
    "Conjure Fey": {"extras": {7: {"gorila gigante:1": "Espírito em forma de gorila gigante (ND 7)"},
                               8: {"tiranossauro:1": "Espírito em forma de tiranossauro (ND 8)"}}},
    # No 9º círculo, um celestial de ND 5.
    "Conjure Celestial": {"extras": {9: {"unicornio:1": "Unicórnio (ND 5)"}}},
}


def modos_de_invocacao_no_circulo(hab: dict, m: dict, ef: dict, char: dict | None) -> dict:
    """
    Os modos de invocação conjurada num círculo acima do da magia, com o
    círculo no id ("lobo:16@c5"). Só os círculos que a mana alcança, e só
    onde o número (ou a criatura) muda.
    """
    from rpg import tools_dnd as td
    regra = ESCALA_DE_INVOCACAO.get((m or {}).get("nome_srd", ""))
    if not regra or not char:
        return {}
    base = int(m.get("nivel", 0) or 0)
    circulos = sorted(int(k[1:]) for k in circulos_da_magia(hab, char))
    saida = {}
    for c in circulos:
        if c <= base:
            continue
        custo = td.SPELL_MANA_COST[c]
        k = c - base
        for id_m, txt in (ef.get("modos") or {}).items():
            chave, _, n = id_m.partition(":")
            n = int(n or 1)
            if regra.get("vezes"):
                if c not in regra["vezes"]:
                    continue
                novo = n * regra["vezes"][c]
            elif regra.get("objetos"):
                novo = n * (10 + 2 * k) // 10
            elif regra.get("mais_um"):
                novo = n + k
            else:
                continue
            if novo != n:
                saida[f"{chave}:{novo}@c{c}"] = f"{txt.split(' (')[0]} → {novo} ({c}º círculo, {custo} mana)"
        for minimo, extras in (regra.get("extras") or {}).items():
            if c == minimo:
                saida.update({f"{i}@c{c}": f"{t} ({c}º círculo, {custo} mana)" for i, t in extras.items()})
    return saida


# ── Projéteis: um dado por dardo ou raio, cada um num alvo à escolha ──────────
#   base: quantos no círculo da magia; ataque: cada raio rola acerto
PROJETEIS = {
    "Magic Missile": {"base": 3, "rotulo": "dardo", "ataque": False},
    "Scorching Ray": {"base": 3, "rotulo": "raio", "ataque": True},
}


def projeteis(hab: dict, circulo: int = 0) -> int:
    """Quantos dardos (Mísseis Mágicos) ou raios (Raio Ardente) a magia solta neste círculo; 0 se não é dessas."""
    m = _magia_srd(hab) or {}
    cfg = PROJETEIS.get(m.get("nome_srd", ""))
    if not cfg:
        return 0
    base = int(m.get("nivel", 1) or 1)
    return cfg["base"] + max(0, (circulo or base) - base)


def alvos_no_circulo(hab: dict, circulo: int = 0) -> int:
    """
    Quantas criaturas a magia de alvo pega neste círculo (Imobilizar Pessoa:
    uma no 2º, duas no 3º...). Os projéteis podem ir cada um num alvo.
    """
    n = projeteis(hab, circulo)
    if n:
        return n
    m = _magia_srd(hab) or {}
    base = int(m.get("nivel", 1) or 1)
    um = max(1, int(m.get("alvo_max", 1) or 1))
    c = circulo or base
    if c <= base:
        return um
    tabela = m.get("alvos_por_espaco") or {}
    return int(tabela.get(str(c)) or (um + c - base))


def alvos_por_modo(hab: dict, char: dict | None) -> dict:
    """modo (círculo) → quantos alvos, para a tela escolher vários. {} quando é um só sempre."""
    m = _magia_srd(hab) or {}
    if not m or not (m.get("alvos_por_espaco") or projeteis(hab)):
        return {}
    from rpg import tools_dnd as td
    if not projeteis(hab) and (td._get_control_effect(hab) or {}).get("pool", True):
        return {}
    base = int(m.get("nivel", 1) or 1)
    ids = list(circulos_da_magia(hab, char)) or [f"c{base}"]
    saida = {i: alvos_no_circulo(hab, int(i[1:])) for i in ids}
    return saida if any(v > 1 for v in saida.values()) else {}


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
    # Na Escuridão ou na Névoa, ninguém vê: esconder-se é automático.
    s = char.get("sheet") or {}
    obsc = td._zona_obscurecida(char.get("name", ""))
    if obsc:
        conds = s.setdefault("condicoes", [])
        if not any(norm(c.get("nome", "") if isinstance(c, dict) else c) == "escondido" for c in conds):
            conds.append({"nome": "Escondido", "duracao": None})
        return f"\n   {nome}: dentro da {obsc}, ninguém o vê — ESCONDIDO. O próximo ataque tem vantagem."
    # Esconder: Furtividade contra a melhor Percepção passiva dos inimigos.
    # No escuro, quem não tem visão no escuro não vê (esconder-se dele é
    # automático); na penumbra, a Percepção dele cai 5.
    bonus = _mod(char, "destreza")
    if td._proficiente_na_pericia(s, "furtividade"):
        bonus += int(s.get("proficiencia", 2) or 2)
    d20 = random.randint(1, 20)
    total = d20 + bonus
    inimigos = [c for c in _combatentes_vivos() if not _mesmo_lado(char, c)]
    luz = td._luz_no_lugar(char.get("name", ""))
    veem = [c for c in inimigos if td._ve_no_escuro(c, char)]
    if inimigos and not veem:
        conds = s.setdefault("condicoes", [])
        if not any(norm(c.get("nome", "") if isinstance(c, dict) else c) == "escondido" for c in conds):
            conds.append({"nome": "Escondido", "duracao": None})
        return f"\n   {nome}: no escuro, nenhum inimigo o vê — ESCONDIDO. O próximo ataque tem vantagem."
    melhor = max([10 + _mod(c, "sabedoria") - (5 if luz == "penumbra" and not td._visao_no_escuro(c) else 0)
                  for c in veem] or [10])
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
        if td._imune_a_condicao(c, "Amedrontado"):
            linhas.append(f"{c['name']}: imune a Amedrontado")
            continue
        passou, linha = td._rolar_salvaguarda(c, "sabedoria", cd, contra="amedrontado")
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


# ── Ações de classe do lote 1 ────────────────────────────────────────────────

def _nivel(char: dict) -> int:
    return int(((char.get("sheet") or {}).get("nivel", 1)) or 1)


def _token() -> int:
    return int((memory.campaign.get("combat_state") or {}).get("turn_token", 0) or 0)


def _chave_de(char: dict) -> str:
    return memory.char_key(char.get("name", ""))


def _prof(char: dict) -> int:
    return int(((char.get("sheet") or {}).get("proficiencia", 2)) or 2)


def circulo_max_de_paladino(nivel: int) -> int:
    return 5 if nivel >= 17 else 4 if nivel >= 13 else 3 if nivel >= 9 else 2 if nivel >= 5 else 1


def _modos_da_destruicao(char: dict) -> dict:
    from rpg import tools_dnd as td
    saida = {}
    for c in range(1, circulo_max_de_paladino(_nivel(char)) + 1):
        saida[str(c)] = (f"{c}º círculo: +{min(5, c + 1)}d8 radiante no próximo acerto "
                         f"({td.SPELL_MANA_COST[c]} mana, só se acertar)")
    return saida


def _destruicao_divina(char, hab, alvo, modo):
    from rpg import tools_dnd as td
    c = int(modo or 1)
    dados = min(5, c + 1)
    custo = td.SPELL_MANA_COST[c]
    td.dar_efeito_de_combate(char, {
        "nome": "Destruição Divina", "golpe_dado": f"{dados}d8", "golpe_tipo": "radiant",
        "golpe_mana": custo, "golpe_contra_profanos": "1d8", "golpe_so_corpo": True,
        "ate_fim_turno_de": _chave_de(char)})
    return (f"\n   Destruição Divina pronta ({c}º círculo): o próximo acerto corpo a corpo neste "
            f"turno soma {dados}d8 radiante (+1d8 contra morto-vivo ou infernal) e gasta {custo} "
            f"mana. Se não acertar neste turno, nada é gasto.")


def _cd_de_ki(char: dict) -> int:
    return 8 + _prof(char) + _mod(char, "sabedoria")


def _ataque_atordoante(char, hab, alvo, modo):
    from rpg import tools_dnd as td
    td.dar_efeito_de_combate(char, {
        "nome": "Ataque Atordoante", "golpe_ki": 1, "golpe_so_corpo": True,
        "golpe_condicao": {"nome": "Atordoado", "salvaguarda": "constituicao", "cd": _cd_de_ki(char),
                           "ate_fim_do_proximo_turno_de": _chave_de(char)},
        "ate_fim_turno_de": _chave_de(char)})
    return (f"\n   Ataque Atordoante pronto: no próximo acerto corpo a corpo neste turno, 1 ponto "
            f"de ki e salvaguarda de CON (CD {_cd_de_ki(char)}) do alvo; se falhar, fica Atordoado "
            f"até o fim do seu próximo turno.")


def _artes_marciais(char, hab, alvo, modo):
    from rpg import tools_dnd as td
    attr = "destreza" if _mod(char, "destreza") >= _mod(char, "forca") else "forca"
    return "\n" + td.attack_roll(char["name"], alvo, "ataque desarmado",
                                 _dado_de_artes_marciais(char), attack_attribute=attr,
                                 end_turn=False, _skip_turn_check=True)


def _tirar_condicoes(char: dict, nomes) -> list[str]:
    st = char.setdefault("sheet", {})
    alvo = {norm(n) for n in nomes}
    tiradas, ficam = [], []
    for c in st.get("condicoes") or []:
        nm = c.get("nome", "") if isinstance(c, dict) else str(c)
        (tiradas if norm(nm) in alvo else ficam).append(c)
    st["condicoes"] = ficam
    return [c.get("nome", "") if isinstance(c, dict) else str(c) for c in tiradas]


def _mente_tranquila(char, hab, alvo, modo):
    from rpg import encantos
    tiradas = _tirar_condicoes(char, ("amedrontado", "enfeiticado"))
    linha = encantos.quebrar(char, "Mente Tranquila") if encantos.ativo(char) else ""
    if not tiradas and not linha:
        return f"\n   Mente Tranquila: {char['name']} não estava Amedrontado nem Enfeitiçado."
    return (f"\n   Mente Tranquila: {char['name']} se livra de "
            f"{', '.join(tiradas) or 'Enfeitiçado'}." + (f"\n   {linha}" if linha else ""))


_TODOS_OS_DANOS_MENOS_FORCA = ["acid", "bludgeoning", "cold", "fire", "lightning", "necrotic",
                               "piercing", "poison", "psychic", "radiant", "slashing", "thunder"]


def _corpo_vazio(char, hab, alvo, modo):
    from rpg import tools_dnd as td
    conds = char.setdefault("sheet", {}).setdefault("condicoes", [])
    if not any(norm(c.get("nome", "") if isinstance(c, dict) else c) == "invisivel" for c in conds):
        conds.append({"nome": "Invisível", "duracao": None, "magia": "Corpo Vazio"})
    td.dar_efeito_de_combate(char, {"nome": "Corpo Vazio", "resistencias": list(_TODOS_OS_DANOS_MENOS_FORCA)})
    return (f"\n   Corpo Vazio: {char['name']} fica Invisível e com resistência a todo dano, "
            f"exceto força, até o fim do combate.")


def _corpo_curativo(char, hab, alvo, modo):
    st = char["sheet"]
    antes = int(st.get("vida_atual", 0) or 0)
    st["vida_atual"] = min(int(st.get("vida_max", 0) or 0), antes + 3 * _nivel(char))
    return f"\n   Corpo Curativo: {char['name']} {antes} → {st['vida_atual']}/{st.get('vida_max')}."


def _golpe_de_sorte(char, hab, alvo, modo):
    from rpg import tools_dnd as td
    td.dar_efeito_de_combate(char, {"nome": "Golpe de Sorte", "acerto_garantido": True,
                                    "ate_fim_turno_de": _chave_de(char)})
    return "\n   Golpe de Sorte: o próximo ataque que errar neste turno vira acerto."


def _desaparecer(char, hab, alvo, modo):
    return _acao_de_movimento(char, "esconder", "Desaparecer")


def _intervencao_divina(char, hab, alvo, modo):
    nivel = _nivel(char)
    d100 = random.randint(1, 100)
    if nivel >= 20 or d100 <= nivel:
        return (f"\n   Intervenção Divina: d100 = {d100} (precisa de até {nivel}"
                f"{'; no 20º nível é automática' if nivel >= 20 else ''}) — A DIVINDADE INTERVÉM."
                f"\n   (Mestre: narre a intervenção conforme o pedido do clérigo e a natureza da divindade.)")
    return (f"\n   Intervenção Divina: d100 = {d100} (precisa de até {nivel}) — o pedido não foi atendido."
            f"\n   (Mestre: a divindade não responde desta vez.)")


def _contra_encanto(char, hab, alvo, modo):
    from rpg import tools_dnd as td
    afetados = [c for c in _combatentes_vivos() if _mesmo_lado(char, c) and _perto(char, c)]
    if char not in afetados:
        afetados.append(char)
    for c in afetados:
        td.dar_efeito_de_combate(c, {"nome": "Contra-Encanto",
                                     "vantagem_save_contra": ["amedrontado", "enfeiticado"],
                                     "ate_fim_turno_de": _chave_de(char), "desde_token": _token()})
    return (f"\n   Contra-Encanto: vantagem contra Amedrontado e Enfeitiçado até o fim do próximo "
            f"turno de {char['name']} para " + ", ".join(c["name"] for c in afetados) + ".")


def _arma_sagrada(char, hab, alvo, modo):
    from rpg import tools_dnd as td
    bonus = max(1, _mod(char, "carisma"))
    td.dar_efeito_de_combate(char, {"nome": "Arma Sagrada", "atk_bonus": bonus})
    return f"\n   Arma Sagrada: +{bonus} nos ataques com arma até o fim do combate."


def _voto_de_inimizade(char, hab, alvo, modo):
    from rpg import tools_dnd as td
    td.dar_efeito_de_combate(char, {"nome": "Voto de Inimizade", "vantagem_ataque": True,
                                    "contra": memory.char_key(alvo)})
    return f"\n   Voto de Inimizade: vantagem em todos os ataques de {char['name']} contra {alvo}."


def _toque_purificador(char, hab, alvo, modo):
    from rpg import encantos, tools_dnd as td
    a = _char(alvo) or char
    if encantos.ativo(a):
        return f"\n   Toque Purificador: {encantos.quebrar(a, 'Toque Purificador')}"
    st = a.setdefault("sheet", {})
    for c in list(st.get("condicoes") or []):
        if isinstance(c, dict) and c.get("magia"):
            st["condicoes"].remove(c)
            return f"\n   Toque Purificador: {a['name']} se livra de {c.get('nome')} ({c.get('magia')})."
    for e in td._efeitos(st):
        origem = _char(e.get("origem", ""))
        if e.get("magia") and origem and not _mesmo_lado(a, origem):
            st["efeitos"] = [x for x in st.get("efeitos") or [] if x is not e]
            return f"\n   Toque Purificador: {a['name']} se livra de {e.get('nome')}."
    return f"\n   Toque Purificador: nenhuma magia sobre {a['name']} para encerrar."


def _presenca_intimidadora(char, hab, alvo, modo):
    from rpg import tools_dnd as td
    a = _char(alvo)
    cd = 8 + _prof(char) + _mod(char, "carisma")
    if td._imune_a_condicao(a, "Amedrontado"):
        return f"\n   Presença Intimidadora: {a['name']} é imune a Amedrontado."
    passou, linha = td._rolar_salvaguarda(a, "sabedoria", cd, contra="amedrontado")
    if passou:
        return f"\n   Presença Intimidadora: {a['name']}: {linha} — resiste."
    _tirar_condicoes(a, ("amedrontado",))
    a["sheet"].setdefault("condicoes", []).append(
        {"nome": "Amedrontado", "duracao": None, "por": char["name"],
         "ate_fim_turno_de": _chave_de(char), "desde_token": _token()})
    return (f"\n   Presença Intimidadora: {a['name']}: {linha} — AMEDRONTADO até o fim do próximo "
            f"turno de {char['name']}.")


def _frenesi(char, hab, alvo, modo):
    from rpg import tools_dnd as td
    char["sheet"]["_frenesi"] = True
    return "\n" + td.attack_roll(char["name"], alvo, _arma_de(char), 6,
                                 end_turn=False, _skip_turn_check=True)


# Forma Selvagem ------------------------------------------------------------

def _circulo_da_lua(char: dict) -> bool:
    from rpg import tools_dnd as td
    s = char.get("sheet") or {}
    sub = norm(" ".join(str(s.get(k) or "") for k in ("subclasse", "circulo", "arquetipo")))
    return ("lua" in sub or "moon" in sub
            or td._tem_habilidade(char, "forma selvagem do combate", "combat wild shape"))


def _modos_da_forma(char: dict) -> dict:
    from rpg import criaturas
    saida = {}
    if criaturas.em_forma_selvagem(char):
        saida["voltar"] = "Voltar à forma normal: ação bônus, sem gastar uso"
    for chave in criaturas.formas_permitidas(_nivel(char), _circulo_da_lua(char)):
        f = criaturas.FICHAS[chave]
        saida[chave] = f"{f['nome']}: ND {f['nd']}, {f['pv']} PV, CA {f['ca']}"
    return saida


def _forma_selvagem(char, hab, alvo, modo):
    from rpg import criaturas, tools_dnd as td
    if modo == "voltar":
        return "\n   " + (criaturas.voltar(char) or f"{char['name']} já está na forma normal.")
    td._gastar_uso(char, "Forma Selvagem")
    return "\n   " + criaturas.transformar(char, modo)


# Fonte de Magia ------------------------------------------------------------
# A mana do jogo é a variante de pontos de magia do SRD: criar um espaço de
# 1º círculo custa 2 pontos de feitiçaria, e conjurar no 1º custa 2 de mana. A
# troca de pontos por mana é 1 por 1; a de mana por pontos segue a tabela do
# círculo (o espaço de 1º círculo vale 1 ponto, o de 2º vale 2...).
_MANA_EM_PONTOS = {2: 1, 3: 2, 5: 3, 6: 4, 7: 5}


def _modos_da_fonte(char: dict) -> dict:
    from rpg import tools_dnd as td
    s = char.get("sheet") or {}
    pontos = int(td.usos_restantes(char, "Fonte de Magia") or 0)
    maximo = int(td.usos_maximos(char, "Fonte de Magia") or 0)
    mana, mana_max = int(s.get("mana_atual", 0) or 0), int(s.get("mana_max", 0) or 0)
    saida = {}
    for m in (2, 3, 5, 6, 7):
        if pontos >= m and mana + m <= mana_max:
            saida[f"mana:{m}"] = f"Criar {m} de mana: gasta {m} pontos de feitiçaria"
    for m, p in _MANA_EM_PONTOS.items():
        if mana >= m and pontos + p <= maximo:
            saida[f"pontos:{m}"] = f"Recuperar {p} {'ponto' if p == 1 else 'pontos'}: gasta {m} de mana"
    return saida


def _fonte_de_magia(char, hab, alvo, modo):
    from rpg import tools_dnd as td
    s = char["sheet"]
    tipo, _, n = (modo or "").partition(":")
    n = int(n or 0)
    pontos = int(td.usos_restantes(char, "Fonte de Magia") or 0)
    usos = s.setdefault("usos", {})
    if tipo == "mana":
        usos["pontos de feiticaria"] = pontos - n
        s["mana_atual"] = int(s.get("mana_atual", 0) or 0) + n
        return (f"\n   Fonte de Magia: {n} pontos viram {n} de mana. Mana {s['mana_atual']}/{s.get('mana_max')}, "
                f"pontos {pontos - n}.")
    p = _MANA_EM_PONTOS[n]
    usos["pontos de feiticaria"] = pontos + p
    s["mana_atual"] = int(s.get("mana_atual", 0) or 0) - n
    return (f"\n   Fonte de Magia: {n} de mana viram {p} {'ponto' if p == 1 else 'pontos'}. "
            f"Mana {s['mana_atual']}/{s.get('mana_max')}, pontos {pontos + p}.")


def modos_de(chave: str, char: dict | None) -> dict:
    """id → texto dos modos de uma ação de classe, para esta ficha."""
    acao = ACOES_DE_CLASSE.get(chave) or {}
    if not acao.get("modos_dinamicos"):
        return {m: MODOS_DE_MOVIMENTO.get(m, m) for m in acao.get("modos") or []}
    if not char:
        return {}
    from rpg import subclasses, superioridade
    if chave in subclasses.MODOS:
        return subclasses.MODOS[chave](char)
    return {"destruicao divina": _modos_da_destruicao, "forma selvagem": _modos_da_forma,
            "fonte de magia": _modos_da_fonte, "manobras de combate": superioridade.modos}[chave](char)


def alvo_do_modo(hab: dict, char: dict | None, modo: str) -> str:
    """O alvo que a ESCOLHA pede, quando muda com ela (Finta: inimigo; Reagrupar: aliado)."""
    chave, _ = acao_de_classe((hab or {}).get("nome", ""), ((char or {}).get("sheet") or {}).get("classe", ""))
    if chave == "manobras de combate" and modo:
        from rpg import superioridade
        return superioridade.alvo_do_modo(modo)
    from rpg import subclasses
    return subclasses.ALVO_DO_MODO.get((chave, modo), "")


def slot_do_modo(hab: dict, char: dict | None, modo: str) -> str:
    """O custo de ação que a ESCOLHA muda: voltar da Forma Selvagem, Finta, Reagrupar."""
    chave, _ = acao_de_classe((hab or {}).get("nome", ""), ((char or {}).get("sheet") or {}).get("classe", ""))
    if chave == "forma selvagem" and modo == "voltar":
        return "bonus"
    if chave == "manobras de combate" and modo:
        from rpg import superioridade
        return superioridade.slot_do_modo(modo)
    from rpg import subclasses
    if chave == "bencao do trapaceiro" and char:
        from rpg import tools_dnd as td
        if td._tem_habilidade(char, "bencao do trapaceiro aprimorada"):
            return "bonus"
    return subclasses.SLOT_DO_MODO.get((chave, modo), "")


def _manobras_de_combate(char, hab, alvo, modo):
    from rpg import superioridade
    return superioridade.usar(char, modo, alvo)


def _da_subclasse(chave):
    def _executar(char, hab, alvo, modo):
        from rpg import subclasses
        return subclasses.EXECUTORES[chave](char, hab, alvo, modo)
    return _executar


_ACOES = {
    **{k: _da_subclasse(k) for k in (
        "maestria de feitico", "assinatura de feitico", "metamagia", "mestre sobrenatural", "disparo magico",
        "avatar sagrado", "tornado de folhas", "anjo vingador", "ler pensamentos", "coroa da luz",
        "encantar animais e plantas", "bencao do trapaceiro", "invocar duplicacao", "palma vibrante",
        "salto sombrio", "manto sombrio", "conjuracao elemental", "terceiro olho", "conjuracao veloz",
        "teletransporte pequeno", "asas draconicas", "presenca draconica", "esculpir o caos",
        "presenca feerica", "apenas para mim", "mestrado do grande antigo")},
    "manobras de combate": _manobras_de_combate,
    "destruicao divina": _destruicao_divina,
    "arma sagrada": _arma_sagrada,
    "voto de inimizade": _voto_de_inimizade,
    "toque purificador": _toque_purificador,
    "artes marciais": _artes_marciais,
    "ataque atordoante": _ataque_atordoante,
    "mente tranquila": _mente_tranquila,
    "corpo vazio": _corpo_vazio,
    "corpo curativo": _corpo_curativo,
    "golpe de sorte": _golpe_de_sorte,
    "desaparecer": _desaparecer,
    "intervencao divina": _intervencao_divina,
    "contra encanto": _contra_encanto,
    "forma selvagem": _forma_selvagem,
    "fonte de magia": _fonte_de_magia,
    "presenca intimidadora": _presenca_intimidadora,
    "frenesi": _frenesi,
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
