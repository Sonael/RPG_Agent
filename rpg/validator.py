"""
validator.py
Validação determinística de consistência narrativa.

Roda APÓS a resposta do agente, sem custo de tokens adicional.
Detecta contradições entre o texto gerado e a memória estruturada.
"""

import re
from dataclasses import dataclass, field

from rpg import memory


# ---------------------------------------------------------------------------
# Tipos
# ---------------------------------------------------------------------------

@dataclass
class Violation:
    """
    Uma inconsistência achada na resposta do mestre.

    Há DOIS textos de propósito. `message` é para o mestre (vai nas
    pendências da instrução do turno seguinte) e pode falar de ferramentas:
    "chame save_character". `jogador` é o que aparece no painel do jogo, e
    fala da história, não do motor — o jogador não chama ferramenta nenhuma,
    e ler "o agente deveria ter chamado save_character automaticamente" só
    mostra a engrenagem. Sem `jogador`, o aviso é só do mestre.
    """
    severity: str          # "erro" | "aviso"
    rule:     str          # identificador da regra
    message:  str          # o que o mestre lê (pode citar ferramentas)
    detail:   str = ""     # trecho da narração, para os dois
    titulo:   str = ""     # rótulo curto para o painel do jogo
    jogador:  str = ""     # o que o jogador lê; vazio = não aparece para ele


@dataclass
class ValidationResult:
    violations: list[Violation] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(v.severity == "erro" for v in self.violations)

    @property
    def has_warnings(self) -> bool:
        return bool(self.violations)

    def summary(self) -> str:
        if not self.violations:
            return ""
        lines = []
        for v in self.violations:
            prefix = "ERRO" if v.severity == "erro" else "AVISO"
            lines.append(f"[{prefix}] {v.message}")
            if v.detail:
                lines.append(f"         ↳ {v.detail}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Utilitários de texto
# ---------------------------------------------------------------------------

# Status que indicam que o personagem não deve mais interagir normalmente.
# São RADICAIS, sem a vogal final: o mestre escreve "morta", "desaparecida",
# "presa", e procurar "morto" deixava passar metade dos personagens.
_DEAD_STATUSES = {"mort", "falecid", "assassinad", "eliminad", "destruid"}
_GONE_STATUSES = {"desaparecid", "pres", "capturad", "exilad", "partid"}

def _status_comeca_com(status: str, radicais: set) -> bool:
    """
    O status bate com algum radical, palavra por palavra.

    Palavra inteira, e não pedaço: "morto em combate" e "morta" contam, e um
    status como "impressionado" não vira "preso".
    """
    return any(palavra.startswith(r)
               for palavra in _normalize(status).split()
               for r in radicais)


def _normalize(text) -> str:
    """Lowercase sem acentos para comparação fuzzy simples.
    Aceita não-string (ex: flag importada como bool/número) sem quebrar."""
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    replacements = str.maketrans(
    "áàãâäéèêëíìîïóòõôöúùûüçñ",
    "aaaaaeeeeiiiiooooouuuucn"
    )
    return text.lower().translate(replacements)


def _name_in_text(name: str, text: str) -> bool:
    """Verifica se o nome do personagem aparece no texto (palavra inteira)."""
    pattern = r'\b' + re.escape(name) + r'\b'
    return bool(re.search(pattern, text, re.IGNORECASE))


def _snippet(text: str, name: str, window: int = 60) -> str:
    """Extrai trecho ao redor do nome para contexto do erro."""
    idx = text.lower().find(name.lower())
    if idx == -1:
        return ""
    start = max(0, idx - window)
    end   = min(len(text), idx + len(name) + window)
    snippet = text[start:end].replace("\n", " ").strip()
    return f"\"...{snippet}...\""


# ---------------------------------------------------------------------------
# Regras de validação
# ---------------------------------------------------------------------------

def _check_dead_characters(response: str, c: dict) -> list[Violation]:
    """
    Personagens mortos não devem falar, agir ou aparecer como ativos.
    Exceções: flashbacks explícitos, fantasmas, ressurreições narrativas.
    """
    violations = []
    chars = c.get("characters", {})

    for data in chars.values():
        if not _status_comeca_com(data.get("status", ""), _DEAD_STATUSES):
            continue
        if not _name_in_text(data["name"], response):
            continue

        # Heurística: se o texto mencionar "espírito", "fantasma", "memória",
        # "lembrança", "visão" perto do nome, provavelmente é intencional.
        ctx = _snippet(response, data["name"], 100).lower()
        ghost_keywords = {"espírito", "fantasma", "memória", "lembrança",
                          "visão", "sonho", "passado", "era", "havia", "fora"}
        if any(kw in ctx for kw in ghost_keywords):
            continue

        violations.append(Violation(
            severity="erro",
            rule="dead_character_active",
            message=f"'{data['name']}' está marcado como '{data['status']}' mas aparece ativo na narrativa.",
            detail=_snippet(response, data["name"]),
            titulo="Alguém que já morreu aparece em cena",
            jogador=(f"A campanha registra {data['name']} como {data['status']}, "
                     f"mas a cena mostra {data['name']} agindo agora. "
                     "Se for lembrança, visão ou fantasma, é só seguir."),
        ))

    return violations


def _check_gone_characters(response: str, c: dict) -> list[Violation]:
    """
    Personagens desaparecidos/presos não devem interagir presencialmente
    sem evento de retorno registrado.
    """
    violations = []
    chars = c.get("characters", {})

    # Verbos de presença física
    presence_verbs = {
        "diz", "fala", "responde", "grita", "sussurra", "ataca", "entra",
        "sai", "olha", "sorri", "franze", "aproxima", "entrega", "pega"
    }

    for data in chars.values():
        if not _status_comeca_com(data.get("status", ""), _GONE_STATUSES):
            continue
        if not _name_in_text(data["name"], response):
            continue

        ctx = _snippet(response, data["name"], 120).lower()
        if any(v in ctx for v in presence_verbs):
            violations.append(Violation(
                severity="aviso",
                rule="gone_character_present",
                message=f"'{data['name']}' ({data['status']}) parece interagir presencialmente.",
                detail=_snippet(response, data["name"]),
                titulo="Alguém que não deveria estar aqui",
                jogador=(f"A campanha registra {data['name']} como {data['status']}, "
                         "mas a cena mostra essa pessoa aqui, em carne e osso."),
            ))

    return violations


def _check_unknown_locations(response: str, c: dict) -> list[Violation]:
    """
    Detecta menções a locais que parecem ser novos mas não foram salvos.
    Usa heurística: frases como "na [Local]", "o [Local]", etc.
    """
    # Esta regra é um aviso leve — falsos positivos são comuns em narrativa
    violations = []
    known_locs  = {_normalize(k).replace("_", " ") for k in c.get("locations", {}).keys()}
    known_chars = {_normalize(k).replace("_", " ") for k in c.get("characters", {}).keys()}

    # Padrão: "na Taverna do Corvo", "rumo ao Castelo de Ferro".
    # Só com preposição de lugar: com o artigo solto ("o", "a") qualquer nome
    # próprio virava lugar — "o Mestre de Guilda Brom" entrava como lugar novo.
    pattern = re.compile(
        r'(?:\b(?:n[ao]|ao|à|em|pel[ao]|para [ao]|até [ao]|rumo a[o]?|dentro d[ao]'
        r'|sa(?:i|iu|íram|iram) d[ao]|chega(?:m|ram)? a[o]?))\s+'
        r'([A-ZÁÀÃÂÉÈÊÍÌÎÓÒÕÔÚÙÛÇ][a-záàãâéèêíìîóòõôúùûç]+'
        r'(?:\s+d[aeo]\s+[A-ZÁÀÃÂÉÈÊÍÌÎÓÒÕÔÚÙÛÇ][a-záàãâéèêíìîóòõôúùûç]+)?'
        r'(?:\s+[A-ZÁÀÃÂÉÈÊÍÌÎÓÒÕÔÚÙÛÇ][a-záàãâéèêíìîóòõôúùûç]+)*)'
    )

    found = set()
    for m in pattern.finditer(response):
        candidate      = m.group(1).strip()
        candidate_norm = _normalize(candidate)

        # Ignora se já conhecido, se é nome de personagem, ou muito curto
        if candidate_norm in known_locs:
            continue
        if candidate_norm in known_chars:
            continue
        if len(candidate.split()) > 5 or len(candidate) < 4:
            continue
        # Ignora palavras comuns que não são locais, incluindo as exceções da campanha
        skip = {"você", "ele", "ela", "eles", "elas", "isso", "este", "esta",
                "neste", "nesta", "aquele", "aquela", "grupo", "party",
                "duelo", "lâmina carmesim", "cidade branca", "érebo"}
        if candidate.lower() in skip:
            continue

        found.add(candidate)

    for loc_name in found:
        violations.append(Violation(
            severity="aviso",
            rule="unknown_location",
            message=(f"Local '{loc_name}' mencionado mas não registrado na memória. "
                     "Considere chamar save_location se for um local importante."),
            detail=_snippet(response, loc_name),
            titulo="Lugar novo ainda fora do mapa",
            jogador=(f"“{loc_name}” apareceu na história e ainda não está no mapa da "
                     "campanha. Pode ser só um nome de passagem; se virar um lugar "
                     "de verdade, o mestre registra."),
        ))

    return violations


def _check_flag_contradictions(response: str, c: dict) -> list[Violation]:
    """
    Verifica contradições simples com flags booleanas.
    Ex: flag 'portao_aberto = fechado' mas texto descreve o portão como aberto.
    """
    violations = []
    flags = c.get("quest_flags", {})

    for key, value in flags.items():
        val_norm = _normalize(value)

        # Pares de contradição: {flag_value: [palavras_contraditórias]}
        contradictions = {
            "fechado":    ["aberto", "destrancado", "acessível"],
            "aberto":     ["fechado", "trancado", "bloqueado"],
            "destruído":  ["intacto", "inteiro", "de pé", "erguido"],
            "vivo":       ["morto", "falecido", "caiu"],
            "morto":      ["vivo", "acordado", "em pé", "falando"],
            "aliado":     ["inimigo", "atacou", "ameaçou"],
            "inimigo":    ["aliado", "ajudou", "protegeu"],
        }

        if val_norm not in contradictions:
            continue

        # Normaliza o nome da flag para procurar no texto
        key_words = key.replace("_", " ").replace("-", " ")
        if not _name_in_text(key_words, response) and key_words not in response.lower():
            continue

        for contra in contradictions[val_norm]:
            ctx = _snippet(response, key_words, 80).lower()
            if contra in ctx:
                violations.append(Violation(
                    severity="aviso",
                    rule="flag_contradiction",
                    message=f"Flag '{key}={value}' pode estar sendo contradita.",
                    detail=_snippet(response, key_words),
                    titulo="A cena contradiz o que está anotado",
                    jogador=(f"A campanha anota “{key.replace('_', ' ')}: {value}”, "
                             "e a cena parece dizer o contrário."),
                ))
                break

    return violations


def _check_new_characters_unsaved(response: str, c: dict) -> list[Violation]:
    """
    Detecta NPCs que parecem ser introduzidos (com nome próprio + papel)
    mas não foram salvos ainda.
    Heurística conservadora para evitar falsos positivos.
    """
    violations = []
    known_chars = {_normalize(k).replace("_", " ") for k in c.get("characters", {}).keys()}
    known_locs  = {_normalize(k).replace("_", " ") for k in c.get("locations", {}).keys()}
    known_all   = known_chars.union(known_locs) # Junta os dois sets

    # Padrão: "Aldric, o ferreiro" / "a maga Seraphina" / "Sir Tormund"
    patterns = [
        re.compile(r'\b([A-ZÁÀÃÂÉÈÊÍÌÎÓÒÕÔÚÙÛÇ][a-záàãâéèêíìîóòõôúùûç]{2,})'
                   r',\s+o\s+\w+'),
        re.compile(r'\b([A-ZÁÀÃÂÉÈÊÍÌÎÓÒÕÔÚÙÛÇ][a-záàãâéèêíìîóòõôúùûç]{2,})'
                   r',\s+a\s+\w+'),
        re.compile(r'\b(?:Sir|Dom|Lady|Lorde|Mestre|Maga?|Capitão)\s+'
                   r'([A-ZÁÀÃÂÉÈÊÍÌÎÓÒÕÔÚÙÛÇ][a-záàãâéèêíìîóòõôúùûç]{2,})'),
    ]

    found = set()
    for pat in patterns:
        for m in pat.finditer(response):
            name      = m.group(1)
            name_norm = _normalize(name)
            if name_norm not in known_all:
                found.add(name)

    for name in found:
        violations.append(Violation(
            severity="aviso",
            rule="unsaved_character",
            message=(f"'{name}' parece ser um personagem novo mas não foi salvo. "
                     "O agente deveria ter chamado save_character automaticamente."),
            detail=_snippet(response, name),
            titulo="Gente nova ainda sem ficha",
            jogador=(f"“{name}” entrou na história agora e ainda não tem ficha na "
                     "campanha. Pode ser figurante de uma cena só; se essa pessoa "
                     "voltar, o mestre registra."),
        ))

    return violations


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

# Frases de narração em que o tempo PASSOU (no passado ou no presente
# narrativo). De propósito fica de fora o que costuma ser plano ou fala sobre
# o futuro ("ao anoitecer", "amanhã"): o aviso é para o mestre, e um aviso
# falso a cada turno ensinaria a ignorá-lo.
_NUMERO = r"(?:uma?|duas|dois|tres|quatro|cinco|seis|sete|oito|nove|dez|doze|algumas|varias|muitas|\d+)"
_TEMPO_PASSOU = re.compile(
    r"\b(?:no dia seguinte|na (?:manha|tarde|noite|madrugada) seguinte"
    r"|(?:horas|dias|semanas|meses) (?:depois|mais tarde|se passa\w*|passa\w*)"
    rf"|{_NUMERO} (?:horas?|dias?|semanas?) (?:depois|mais tarde|de (?:viagem|caminhada|marcha|estrada|cavalgada|espera))"
    r"|amanheceu|anoiteceu|o sol (?:nasceu|se pos)|a noite (?:caiu|passou)|caiu a noite"
    r"|passa(?:m|ram) a noite|dorm(?:em|iram) ate)\b"
)


def _check_time_passed(response: str, c: dict) -> list[Violation]:
    """
    A narração fez o tempo passar e o relógio não andou neste turno.

    O relógio só anda por advance_time(); se o mestre narra "no dia seguinte"
    e não chama, o mundo fica parado: o encontro marcado não chega, o descanso
    longo não volta a valer. Vai para o mestre no turno seguinte (pendências),
    não para o jogador.
    """
    if memory.turnos_sem("relogio") == 0:      # andou neste turno
        return []
    achado = _TEMPO_PASSOU.search(_normalize(response))
    if not achado:
        return []
    return [Violation(
        severity="aviso",
        rule="time_not_advanced",
        message=(f"A narração fez o tempo passar (\"{achado.group(0)}\") e o relógio não andou. "
                 "Se o tempo passou mesmo, chame advance_time(horas, motivo)."),
    )]


# Avisos que o jogador não tem como resolver nem conferir: o relógio só anda
# por ferramenta do mestre.
SO_PARA_O_MESTRE = ("time_not_advanced",)


def para_o_jogador(violations: list[dict]) -> list[dict]:
    """
    O que o painel do jogo recebe, a partir dos avisos já em dicionário.

    Regra única: aparece quem tem texto de jogador. É o que mantém o relógio
    parado (e qualquer outro recado de motor) fora da tela, sem depender de
    uma segunda lista de exceções.

    Fica aqui, e não na rota, para poder ser testado sem subir o servidor: é
    esta função que garante que o texto de mestre ("chame save_character")
    não vaza para a tela do jogador.
    """
    return [
        {"severity": v["severity"], "rule": v["rule"], "titulo": v.get("titulo", ""),
         "message": v.get("jogador", ""), "detail": v.get("detail", "")}
        for v in violations
        if v.get("jogador")
    ]


def validate(response: str) -> ValidationResult:
    """
    Valida a resposta do agente contra a memória atual.
    Retorna um ValidationResult com todas as violações encontradas.

    Args:
        response: Texto gerado pelo agente.
    """
    c      = memory.campaign
    result = ValidationResult()

    result.violations.extend(_check_dead_characters(response, c))
    result.violations.extend(_check_gone_characters(response, c))
    result.violations.extend(_check_unknown_locations(response, c))
    result.violations.extend(_check_flag_contradictions(response, c))
    result.violations.extend(_check_new_characters_unsaved(response, c))
    result.violations.extend(_check_time_passed(response, c))

    return result