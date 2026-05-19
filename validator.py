"""
validator.py
Validação determinística de consistência narrativa.

Roda APÓS a resposta do agente, sem custo de tokens adicional.
Detecta contradições entre o texto gerado e a memória estruturada.
"""

import re
from dataclasses import dataclass, field

import memory


# ---------------------------------------------------------------------------
# Tipos
# ---------------------------------------------------------------------------

@dataclass
class Violation:
    severity: str          # "erro" | "aviso"
    rule:     str          # identificador da regra
    message:  str          # descrição legível
    detail:   str = ""     # contexto adicional (trecho do texto, etc.)


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

# Status que indicam que o personagem não deve mais interagir normalmente
_DEAD_STATUSES = {"morto", "falecido", "assassinado", "eliminado", "destruído"}
_GONE_STATUSES = {"desaparecido", "preso", "capturado", "exilado", "partido"}

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
        status_norm = _normalize(data.get("status", ""))
        if not any(s in status_norm for s in _DEAD_STATUSES):
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
        status_norm = _normalize(data.get("status", ""))
        if not any(s in status_norm for s in _GONE_STATUSES):
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

    # Padrão: "na Taverna do Corvo", "o Castelo de Ferro", etc.
    # Captura substantivos próprios (iniciais maiúsculas consecutivas)
    pattern = re.compile(
        r'(?:na|no|ao|à|em|pelo|pela|para o|para a|o|a)\s+'
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
            message=f"Local '{loc_name}' mencionado mas não registrado na memória.",
            detail="Considere chamar save_location se for um local importante.",
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
            message=f"'{name}' parece ser um personagem novo mas não foi salvo.",
            detail="O agente deveria ter chamado save_character automaticamente.",
        ))

    return violations


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

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

    return result