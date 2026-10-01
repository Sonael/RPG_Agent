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
               "atr": (3, 13, 8, 2, 12, 7), "voa": True, "nao_ataca": True, "ataques": [{"nome": "garras", "dado": "1d1", "tipo": "slashing"}]},
    "gato": {"nome": "Gato", "nd": "0", "tipo": "beast", "ca": 12, "pv": 2,
             "atr": (3, 15, 10, 3, 12, 7), "nao_ataca": True, "ataques": [{"nome": "garras", "dado": "1d1", "tipo": "slashing"}]},
    "corvo": {"nome": "Corvo", "nd": "0", "tipo": "beast", "ca": 12, "pv": 1,
              "atr": (2, 14, 8, 2, 12, 6), "voa": True, "nao_ataca": True, "ataques": [{"nome": "bico", "dado": "1d1", "tipo": "piercing"}]},
    "morcego": {"nome": "Morcego", "nd": "0", "tipo": "beast", "ca": 12, "pv": 1,
                "atr": (2, 15, 8, 2, 12, 4), "voa": True, "nao_ataca": True, "ataques": [{"nome": "mordida", "dado": "1d1", "tipo": "piercing"}]},
    "rato": {"nome": "Rato", "nd": "0", "tipo": "beast", "ca": 10, "pv": 1,
             "atr": (2, 11, 9, 2, 10, 4), "nao_ataca": True, "ataques": [{"nome": "mordida", "dado": "1d1", "tipo": "piercing"}]},
    "aranha": {"nome": "Aranha", "nd": "0", "tipo": "beast", "ca": 12, "pv": 1,
               "atr": (2, 14, 8, 1, 10, 2), "nao_ataca": True, "ataques": [{"nome": "mordida", "dado": "1d1", "tipo": "piercing"}]},

    # ── Montarias (Encontrar Montaria) ──────────────────────────────────
    "cavalo de guerra": {"nome": "Cavalo de Guerra", "nd": "1/2", "tipo": "celestial", "ca": 11, "pv": 19,
                         "atr": (18, 12, 13, 6, 12, 7),
                         "ataques": [{"nome": "cascos", "dado": "2d6", "tipo": "bludgeoning"}]},
    "ponei": {"nome": "Pônei", "nd": "1/8", "tipo": "celestial", "ca": 10, "pv": 11,
              "atr": (15, 10, 13, 6, 11, 7),
              "ataques": [{"nome": "cascos", "dado": "2d4", "tipo": "bludgeoning"}]},

    # ── Elementais (Conjurar Elemental), ND 5 ───────────────────────────
    "elemental do ar": {"nome": "Elemental do Ar", "nd": "5", "tipo": "elemental", "ca": 15, "pv": 90,
                        "atr": (14, 20, 14, 6, 10, 6), "multiataque": 2, "voa": True,
                        "ataques": [{"nome": "pancada", "dado": "2d8", "tipo": "bludgeoning"}],
                        "resistencias": ["lightning", "thunder"],
                        "resistencias_nao_magicas": ["bludgeoning", "piercing", "slashing"],
                        "imunidades": ["poison"]},
    "elemental da terra": {"nome": "Elemental da Terra", "nd": "5", "tipo": "elemental", "ca": 17, "pv": 126,
                           "atr": (20, 8, 20, 5, 10, 5), "multiataque": 2,
                           "ataques": [{"nome": "pancada", "dado": "2d8", "tipo": "bludgeoning"}],
                           "vulnerabilidades": ["thunder"],
                           "resistencias_nao_magicas": ["bludgeoning", "piercing", "slashing"],
                           "imunidades": ["poison"]},
    "elemental do fogo": {"nome": "Elemental do Fogo", "nd": "5", "tipo": "elemental", "ca": 13, "pv": 102,
                          "atr": (10, 17, 16, 6, 10, 7), "multiataque": 2,
                          "ataques": [{"nome": "toque", "dado": "2d6", "tipo": "fire"}],
                          "resistencias_nao_magicas": ["bludgeoning", "piercing", "slashing"],
                          "imunidades": ["fire", "poison"]},
    "elemental da agua": {"nome": "Elemental da Água", "nd": "5", "tipo": "elemental", "ca": 14, "pv": 114,
                          "atr": (18, 14, 18, 5, 10, 8), "multiataque": 2, "nada": True,
                          "ataques": [{"nome": "pancada", "dado": "2d8", "tipo": "bludgeoning"}],
                          "resistencias": ["acid"],
                          "resistencias_nao_magicas": ["bludgeoning", "piercing", "slashing"],
                          "imunidades": ["poison"]},

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
        "resistencias": ([{"tipos": [t]} for t in f.get("resistencias", [])]
                         + ([{"tipos": list(f["resistencias_nao_magicas"]), "requer_magica": True}]
                            if f.get("resistencias_nao_magicas") else [])),
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
# Polimorfia troca também a mente (SRD): INT, SAB, CAR e a proficiência.
_CAMPOS_DA_MENTE = ("inteligencia", "sabedoria", "carisma", "proficiencia")


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


def transformar(char: dict, chave: str, origem: str = "Forma Selvagem", concentracao_de: str = "",
                magia: str = "", mental: bool = False, permanente_em: int | None = None) -> str:
    """
    A ficha vira a da fera. Forma Selvagem mantém a mente do druida;
    Polimorfia (`mental`) troca tudo e acaba com a concentração de quem conjurou.
    """
    s = char.setdefault("sheet", {})
    if s.get("_forma_selvagem"):
        voltar(char, "")
    fera = montar_sheet(chave)
    campos = _CAMPOS_DA_FERA + (_CAMPOS_DA_MENTE if mental else ())
    s["_forma_selvagem"] = {"forma": FICHAS[chave]["nome"], "chave": chave, "origem": origem,
                            "concentracao_de": concentracao_de, "magia": magia,
                            "permanente_em": permanente_em,
                            "original": {k: copy.deepcopy(s.get(k)) for k in campos}}
    for k in campos:
        s[k] = copy.deepcopy(fera.get(k))
    return (f"{char['name']} assume a forma de {FICHAS[chave]['nome']}"
            + (f" ({origem})" if origem != "Forma Selvagem" else "") + ": "
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


# ===========================================================================
# INVOCAÇÕES
# ===========================================================================
# A criatura invocada entra na história como personagem do lado "aliado": o
# motor conduz o turno dela, como o de qualquer aliado (memory.lado_no_combate).
# `invocacao` guarda de onde ela veio e o que a faz sumir:
#   por          chave de quem invocou
#   magia        o nome da magia na ficha
#   concentracao some quando quem invocou perde a concentração nesta magia
#   persistente  fica depois do combate (familiar, montaria, mortos animados)
#   ate_hora     some quando o relógio do mundo chega lá (Animar Mortos: 24 h)

def _invocadas() -> list[dict]:
    from rpg import memory
    return [c for c in (memory.campaign.get("characters") or {}).values()
            if isinstance(c, dict) and isinstance(c.get("invocacao"), dict)]


def invocar(conjurador: dict, chave: str, quantos: int, magia: str, *,
            concentracao: bool, persistente: bool, ate_hora: int | None = None,
            acompanha: bool | None = None, hostil_ao_perder: bool = False) -> list[str]:
    """Cria as criaturas e, com combate em andamento, põe na iniciativa e na zona de quem invocou."""
    from rpg import memory, tools_dnd as td
    f = FICHAS[chave]
    dono = conjurador.get("name", "")
    nomes = []
    for i in range(quantos):
        nome = f"{f['nome']} de {dono}" + (f" {i + 1}" if quantos > 1 else "")
        sheet = montar_sheet(chave)
        if f.get("nao_ataca"):
            sheet["nao_ataca"] = True
        memory.campaign["characters"][memory.char_key(nome)] = {
            "name": nome, "description": f"{f['nome']} invocado por {dono} ({magia}).",
            "traits": "", "notes": f.get("nota", ""), "status": "vivo", "lado": "aliado",
            "sheet": sheet, "inventario": [], "habilidades": [],
            "invocacao": {"por": memory.char_key(dono), "magia": magia, "concentracao": concentracao,
                          "persistente": persistente, "ate_hora": ate_hora,
                          "acompanha": persistente if acompanha is None else acompanha,
                          "hostil_ao_perder": hostil_ao_perder},
        }
        nomes.append(nome)
    cs = memory.campaign.get("combat_state") or {}
    if cs.get("is_active") and nomes:
        td._entrar_no_combate_em_andamento(nomes, cs)
        zona = td._zona_de(dono)
        if zona:
            for n in nomes:
                cs.setdefault("posicoes", {})[memory.char_key(n)] = zona
    return nomes


def dispensar(criatura: dict, motivo: str) -> str:
    from rpg import memory
    nome = criatura.get("name", "")
    chave = memory.char_key(nome)
    cs = memory.campaign.get("combat_state") or {}
    ordem = cs.get("initiative_order") or []
    idx = next((i for i, n in enumerate(ordem) if memory.char_key(n) == chave), None)
    if idx is not None:
        ordem.pop(idx)
        atual = cs.get("current_turn_index", 0)
        if isinstance(atual, int) and idx < atual:
            cs["current_turn_index"] = atual - 1
        elif isinstance(atual, int) and atual >= len(ordem):
            cs["current_turn_index"] = 0
        (cs.get("posicoes") or {}).pop(chave, None)
    memory.campaign["characters"].pop(chave, None)
    return f"{nome} desaparece ({motivo})."


def dispensar_de(dono_chave: str, magia: str, motivo: str) -> list[str]:
    from rpg import resolucao
    return [dispensar(c, motivo) for c in _invocadas()
            if c["invocacao"].get("por") == dono_chave
            and resolucao.norm(c["invocacao"].get("magia", "")) == resolucao.norm(magia)]


def limpar(fim_do_combate: bool = False) -> list[str]:
    """
    Tira as invocações que acabaram: concentração perdida, prazo do relógio
    vencido, quem invocou morto, ou (no fim do combate) as que só duram a luta.
    """
    from rpg import memory, resolucao, tools_dnd as td
    linhas = []
    for c in list((memory.campaign.get("characters") or {}).values()):
        s_c = ((c or {}).get("sheet") or {}) if isinstance(c, dict) else {}
        # Polimorfia Verdadeira com uma hora de concentração: fica para sempre.
        for marca in [s_c.get("_forma_selvagem")] + [x for x in s_c.get("condicoes") or []
                                                     if isinstance(x, dict) and x.get("permanente_em") is not None]:
            if not marca or not marca.get("concentracao_de") or marca.get("permanente_em") is None:
                continue
            conj = memory.campaign["characters"].get(marca["concentracao_de"]) or {}
            atual = ((conj.get("sheet") or {}).get("concentracao") or {})
            segue = resolucao.norm(atual.get("magia", "")) == resolucao.norm(marca.get("magia", ""))
            if segue and td._agora_em_horas() >= int(marca["permanente_em"]):
                marca.update(concentracao_de="", permanente=True)
                if marca is not s_c.get("_forma_selvagem"):
                    # A condição sem "magia" sobrevive ao fim do combate.
                    marca.pop("magia", None)
                linhas.append(f"A {marca.get('origem', 'Polimorfia Verdadeira')} sobre {c.get('name')} "
                              f"agora é permanente.")
        fs = s_c.get("_forma_selvagem")
        if not fs or not fs.get("concentracao_de"):
            continue
        conj = memory.campaign["characters"].get(fs["concentracao_de"]) or {}
        atual = ((conj.get("sheet") or {}).get("concentracao") or {})
        if resolucao.norm(atual.get("magia", "")) != resolucao.norm(fs.get("magia", "")):
            linhas.append(voltar(c, "a concentração caiu"))
    for c in _invocadas():
        inv = c["invocacao"]
        dono = memory.campaign["characters"].get(inv.get("por", ""))
        motivo = ""
        if not dono or (dono.get("status") or "").lower() == "morto":
            motivo = "quem a invocou se foi"
        elif inv.get("concentracao"):
            atual = ((dono.get("sheet") or {}).get("concentracao") or {})
            if resolucao.norm(atual.get("magia", "")) != resolucao.norm(inv.get("magia", "")):
                motivo = "a concentração caiu"
        if not motivo and inv.get("ate_hora") is not None and td._agora_em_horas() >= int(inv["ate_hora"]):
            motivo = "o tempo da magia acabou"
        if not motivo and fim_do_combate and not inv.get("persistente"):
            motivo = "fim do combate"
        if not motivo and (c.get("status") or "").lower() == "morto":
            motivo = "caiu em combate"
        # Conjurar Elemental: perdida a concentração, o elemental não some —
        # vira inimigo de quem o chamou, até o prazo da magia acabar.
        if motivo == "a concentração caiu" and inv.get("hostil_ao_perder"):
            inv.update(concentracao=False, hostil_ao_perder=False, acompanha=False, persistente=False)
            c["lado"] = "inimigo"
            c["status"] = "inimigo"
            linhas.append(f"{c.get('name')} se liberta do controle de {dono.get('name')} e se volta "
                          f"contra o grupo!")
            continue
        if motivo:
            linhas.append(dispensar(c, motivo))
    return linhas


def companheiros_de(nomes: list[str]) -> list[str]:
    """Os companheiros persistentes (familiar, montaria, mortos animados) destes personagens."""
    from rpg import memory
    donos = {memory.char_key(n) for n in nomes}
    return [c["name"] for c in _invocadas()
            if c["invocacao"].get("acompanha", c["invocacao"].get("persistente"))
            and c["invocacao"].get("por") in donos
            and (c.get("status") or "").lower() not in ("morto", "fugiu")]


def quando_a_fera_cai(char: dict, sobra: int) -> str:
    """A fera chegou a 0 PV: o druida volta e o dano que sobrou passa a ele."""
    linha = voltar(char, "a fera caiu")
    s = char.get("sheet") or {}
    if sobra > 0:
        antes = int(s.get("vida_atual", 0) or 0)
        s["vida_atual"] = max(0, antes - sobra)
        linha += f" O dano que sobrou ({sobra}) passa para ele: {antes} → {s['vida_atual']}."
    return linha
