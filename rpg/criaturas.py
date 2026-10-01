"""
criaturas.py
As feras e servos que um personagem do grupo traz para a luta: a Forma
Selvagem do druida e as invocações (Conjurar Animais, Convocar Familiar,
Encontrar Montaria, Animar Mortos).

POR QUE EXISTE
──────────────
Os monstros do jogo vêm do Open5e (spawn_monster), pela rede. A Forma
Selvagem e as invocações não podem depender disso: o druida vira lobo no meio
da luta, e a luta não espera a rede. Aqui ficam as fichas do SRD 5.1 das
criaturas que essas regras usam, no mesmo formato que spawn_monster grava.

`ataques` segue o formato de _extract_monster_attacks: o dado sem o bônus,
porque attack_roll soma o modificador do atributo.
"""
from __future__ import annotations

import copy

# nd: o nível de desafio, como fração ("1/4") ou inteiro.
# voa/nada: a Forma Selvagem só libera essas formas em níveis maiores.
FICHAS: dict[str, dict] = {
    # ── Feras de Forma Selvagem e de Conjurar Animais ────────────────────
    "lobo": {"nome": "Lobo", "nd": "1/4", "tipo": "beast", "ca": 13, "pv": 11,
             "atr": (12, 15, 12, 3, 12, 6),
             "ataques": [{"nome": "mordida", "dado": "2d4", "tipo": "piercing",
                          "derruba": {"salvaguarda": "forca", "cd": 11}}],
             "nota": "Táticas de Matilha: vantagem com um aliado ao lado do alvo."},
    "pantera": {"nome": "Pantera", "nd": "1/4", "tipo": "beast", "ca": 12, "pv": 13,
                "atr": (14, 15, 10, 3, 14, 7),
                "ataques": [{"nome": "mordida", "dado": "1d6", "tipo": "piercing"},
                            {"nome": "garra", "dado": "1d4", "tipo": "slashing"}]},
    "urso negro": {"nome": "Urso-Negro", "nd": "1/2", "tipo": "beast", "ca": 11, "pv": 19,
                   "atr": (15, 10, 14, 2, 12, 7), "multiataque": 2,
                   "ataques": [{"nome": "mordida", "dado": "1d6", "tipo": "piercing"},
                               {"nome": "garras", "dado": "2d4", "tipo": "slashing"}]},
    "macaco": {"nome": "Macaco", "nd": "1/2", "tipo": "beast", "ca": 12, "pv": 19,
               "atr": (16, 14, 14, 6, 12, 7), "multiataque": 2,
               "ataques": [{"nome": "punho", "dado": "1d6", "tipo": "bludgeoning"}]},
    "urso pardo": {"nome": "Urso-Pardo", "nd": "1", "tipo": "beast", "ca": 11, "pv": 34,
                   "atr": (19, 10, 16, 2, 13, 7), "multiataque": 2,
                   "ataques": [{"nome": "mordida", "dado": "1d8", "tipo": "piercing"},
                               {"nome": "garras", "dado": "2d6", "tipo": "slashing"}]},
    "lobo atroz": {"nome": "Lobo Atroz", "nd": "1", "tipo": "beast", "ca": 14, "pv": 37,
                   "atr": (17, 15, 15, 3, 12, 7),
                   "ataques": [{"nome": "mordida", "dado": "2d6", "tipo": "piercing",
                                "derruba": {"salvaguarda": "forca", "cd": 13}}],
                   "nota": "Táticas de Matilha: vantagem com um aliado ao lado do alvo."},
    "aranha gigante": {"nome": "Aranha Gigante", "nd": "1", "tipo": "beast", "ca": 14, "pv": 26,
                       "atr": (14, 16, 12, 2, 11, 4),
                       "ataques": [{"nome": "mordida", "dado": "1d8", "tipo": "piercing"}]},
    "urso polar": {"nome": "Urso-Polar", "nd": "2", "tipo": "beast", "ca": 12, "pv": 42,
                   "atr": (20, 10, 16, 2, 13, 7), "multiataque": 2,
                   "ataques": [{"nome": "mordida", "dado": "1d8", "tipo": "piercing"},
                               {"nome": "garras", "dado": "2d6", "tipo": "slashing"}]},
    "aguia gigante": {"nome": "Águia Gigante", "nd": "1", "tipo": "beast", "ca": 13, "pv": 26,
                      "atr": (16, 17, 13, 8, 14, 10), "multiataque": 2, "voa": True,
                      "ataques": [{"nome": "bico", "dado": "1d6", "tipo": "piercing"},
                                  {"nome": "garras", "dado": "2d6", "tipo": "slashing"}]},
    "crocodilo": {"nome": "Crocodilo", "nd": "1/2", "tipo": "beast", "ca": 12, "pv": 19,
                  "atr": (15, 10, 13, 2, 10, 5), "nada": True,
                  "ataques": [{"nome": "mordida", "dado": "1d10", "tipo": "piercing"}]},

    # ── Familiares (Convocar Familiar): não atacam ──────────────────────
    "coruja": {"nome": "Coruja", "nd": "0", "tipo": "beast", "ca": 11, "pv": 1,
               "atr": (3, 13, 8, 2, 12, 7), "voa": True, "nao_ataca": True, "ataques": []},
    "gato": {"nome": "Gato", "nd": "0", "tipo": "beast", "ca": 12, "pv": 2,
             "atr": (3, 15, 10, 3, 12, 7), "nao_ataca": True, "ataques": []},
    "corvo": {"nome": "Corvo", "nd": "0", "tipo": "beast", "ca": 12, "pv": 1,
              "atr": (2, 14, 8, 2, 12, 6), "voa": True, "nao_ataca": True, "ataques": []},
    "morcego": {"nome": "Morcego", "nd": "0", "tipo": "beast", "ca": 12, "pv": 1,
                "atr": (2, 15, 8, 2, 12, 4), "voa": True, "nao_ataca": True, "ataques": []},
    "rato": {"nome": "Rato", "nd": "0", "tipo": "beast", "ca": 10, "pv": 1,
             "atr": (2, 11, 9, 2, 10, 4), "nao_ataca": True, "ataques": []},
    "aranha": {"nome": "Aranha", "nd": "0", "tipo": "beast", "ca": 12, "pv": 1,
               "atr": (2, 14, 8, 1, 10, 2), "nao_ataca": True, "ataques": []},

    # ── Montarias (Encontrar Montaria) ──────────────────────────────────
    "cavalo de guerra": {"nome": "Cavalo de Guerra", "nd": "1/2", "tipo": "celestial", "ca": 11, "pv": 19,
                         "atr": (18, 12, 13, 6, 12, 7),
                         "ataques": [{"nome": "cascos", "dado": "2d6", "tipo": "bludgeoning"}]},
    "ponei": {"nome": "Pônei", "nd": "1/8", "tipo": "celestial", "ca": 10, "pv": 11,
              "atr": (15, 10, 13, 6, 11, 7),
              "ataques": [{"nome": "cascos", "dado": "2d4", "tipo": "bludgeoning"}]},

    # ── Mortos-vivos (Animar Mortos) ────────────────────────────────────
    "esqueleto": {"nome": "Esqueleto", "nd": "1/4", "tipo": "undead", "ca": 13, "pv": 13,
                  "atr": (10, 14, 15, 6, 8, 5),
                  "ataques": [{"nome": "espada curta", "dado": "1d6", "tipo": "piercing"},
                              {"nome": "arco curto", "dado": "1d6", "tipo": "piercing", "ranged": True}],
                  "vulnerabilidades": ["bludgeoning"], "imunidades": ["poison"]},
    "zumbi": {"nome": "Zumbi", "nd": "1/4", "tipo": "undead", "ca": 8, "pv": 22,
              "atr": (13, 6, 16, 3, 6, 5),
              "ataques": [{"nome": "pancada", "dado": "1d6", "tipo": "bludgeoning"}],
              "imunidades": ["poison"]},
}


def nd_valor(nd: str) -> float:
    s = str(nd or "0")
    if "/" in s:
        a, b = s.split("/", 1)
        return int(a) / int(b)
    return float(s)


def ficha(chave: str) -> dict | None:
    return FICHAS.get(chave)


def montar_sheet(chave: str) -> dict:
    """A ficha no formato de spawn_monster (o motor lê igual a de um monstro)."""
    f = FICHAS[chave]
    nd = nd_valor(f["nd"])
    prof = 3 if nd >= 5 else 2
    forca, des, con, intel, sab, car = f["atr"]
    ataques = [{"nome": a["nome"], "dado": a["dado"], "tipo": a.get("tipo", ""),
                "ranged": bool(a.get("ranged"))} for a in f.get("ataques") or []]
    return {
        "classe": "npc", "raca": f["nome"].lower(), "tipo": f["tipo"],
        "nivel": max(1, int(nd)), "xp": 0, "xp_proximo": 100,
        "forca": forca, "destreza": des, "constituicao": con,
        "inteligencia": intel, "sabedoria": sab, "carisma": car,
        "vida_atual": f["pv"], "vida_max": f["pv"], "mana_atual": 0, "mana_max": 0,
        "ca": f["ca"], "proficiencia": prof, "hit_die": 8,
        "ouro": 0, "prata": 0, "cobre": 0,
        "equipamentos": {"armadura": None, "escudo": None,
                         "arma_principal": ataques[0]["nome"] if ataques else None, "amuleto": None},
        "ataques": ataques,
        "arma_dado": ataques[0]["dado"] if ataques else "",
        "multiattack": int(f.get("multiataque", 1)),
        "resistencias": [{"tipos": [t]} for t in f.get("resistencias", [])],
        "imunidades": [{"tipos": [t]} for t in f.get("imunidades", [])],
        "vulnerabilidades": [{"tipos": [t]} for t in f.get("vulnerabilidades", [])],
        "vida_temp": 0, "concentracao": None, "condicoes": [],
        "death_saves_sucessos": 0, "death_saves_falhas": 0, "cr": f["nd"],
    }


# ===========================================================================
# FORMA SELVAGEM
# ===========================================================================
# O druida vira a fera: a ficha passa a ter a vida, a CA, FOR/DES/CON e os
# ataques dela. INT, SAB, CAR, a proficiência e a concentração continuam do
# druida. Quando a vida da fera chega a 0, ele volta à forma normal e o dano
# que sobrou passa para ele (_apply_damage chama `quando_a_fera_cai`).

_CAMPOS_DA_FERA = ("forca", "destreza", "constituicao", "ca", "vida_atual", "vida_max",
                   "ataques", "arma_dado", "multiattack", "equipamentos",
                   "resistencias", "imunidades", "vulnerabilidades")


def nd_maximo(nivel: int, circulo_da_lua: bool) -> float:
    if circulo_da_lua:
        return max(1.0, nivel // 3) if nivel >= 6 else 1.0
    return 1.0 if nivel >= 8 else 0.5 if nivel >= 4 else 0.25


def formas_permitidas(nivel: int, circulo_da_lua: bool = False) -> list[str]:
    """As feras que este druida pode adotar (ND e, no começo, sem voar/nadar)."""
    teto = nd_maximo(nivel, circulo_da_lua)
    saida = []
    for chave, f in FICHAS.items():
        if f["tipo"] != "beast" or f.get("nao_ataca"):
            continue
        if nd_valor(f["nd"]) > teto:
            continue
        if f.get("voa") and nivel < 8:
            continue
        if f.get("nada") and nivel < 4:
            continue
        saida.append(chave)
    return saida


def em_forma_selvagem(char: dict) -> dict | None:
    return ((char or {}).get("sheet") or {}).get("_forma_selvagem")


def transformar(char: dict, chave: str) -> str:
    s = char.setdefault("sheet", {})
    if s.get("_forma_selvagem"):
        voltar(char, "")
    fera = montar_sheet(chave)
    s["_forma_selvagem"] = {"forma": FICHAS[chave]["nome"], "chave": chave,
                            "original": {k: copy.deepcopy(s.get(k)) for k in _CAMPOS_DA_FERA}}
    for k in _CAMPOS_DA_FERA:
        s[k] = copy.deepcopy(fera.get(k))
    return (f"{char['name']} assume a forma de {FICHAS[chave]['nome']}: "
            f"{s['vida_atual']} PV, CA {s['ca']}, ataques: "
            f"{', '.join(a['nome'] for a in s['ataques']) or 'nenhum'}."
            + (f" {FICHAS[chave]['nota']}" if FICHAS[chave].get("nota") else ""))


def voltar(char: dict, motivo: str = "") -> str:
    s = (char or {}).get("sheet") or {}
    fs = s.pop("_forma_selvagem", None)
    if not fs:
        return ""
    for k, v in (fs.get("original") or {}).items():
        s[k] = v
    return (f"{char.get('name')} volta à forma normal"
            + (f" ({motivo})" if motivo else "") + f": {s.get('vida_atual')}/{s.get('vida_max')} PV.")


def quando_a_fera_cai(char: dict, sobra: int) -> str:
    """A fera chegou a 0 PV: o druida volta e o dano que sobrou passa a ele."""
    linha = voltar(char, "a fera caiu")
    s = char.get("sheet") or {}
    if sobra > 0:
        antes = int(s.get("vida_atual", 0) or 0)
        s["vida_atual"] = max(0, antes - sobra)
        linha += f" O dano que sobrou ({sobra}) passa para ele: {antes} → {s['vida_atual']}."
    return linha
