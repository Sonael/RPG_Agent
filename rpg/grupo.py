"""
grupo.py
Visão geral do grupo: os heróis lado a lado.

Para decidir DESCANSO e DIVISÃO DE ITENS o jogador abria a ficha de cada um,
uma por vez, e fazia a conta de cabeça: quem está ferido, quem ainda tem dado
de vida, quem já pode dormir, quem aguenta carregar a cota de malha.

Nenhuma regra nova aqui. Cada número vem da mesma conta do resto do jogo:
a ficha do herói (hero_snapshot), a tela de descanso (reserva de dados, as 24
horas do descanso longo, o que a noite devolve) e a carga (capacidade e
metade dela, a partir da qual o herói fica sobrecarregado). O que este módulo
acrescenta é o JUNTAR: o que cada um precisa e o resumo do grupo.
"""

from __future__ import annotations

from rpg import memory


class _MotorTardio:
    """tools_dnd importa muita coisa; carregar só quando a tela pede."""

    def __getattr__(self, nome):
        from rpg import tools_dnd
        return getattr(tools_dnd, nome)


td = _MotorTardio()

# Carga a partir da qual o cartão avisa "perto do limite": 80% do ponto em que
# o herói fica sobrecarregado (metade da capacidade).
_PERTO_DO_LIMITE = 0.8


def _pct(atual: int, maximo: int) -> int:
    return max(0, min(100, round(atual / maximo * 100))) if maximo > 0 else 0


def _carga(ch: dict) -> dict:
    estado, kg, cap = td._estado_de_carga(ch)
    limite = round(cap / 2, 1)
    return {
        "kg": round(kg, 1),
        "capacidade": cap,
        "limite_sobrecarga": limite,
        "folga_kg": round(max(0.0, limite - kg), 1),
        "estado": estado,
        "perto_do_limite": estado == "livre" and limite > 0 and kg >= limite * _PERTO_DO_LIMITE,
        "pct": _pct(kg, cap),
        "pct_limite": 50,
    }


def _heroi(ch: dict) -> dict:
    nome = ch.get("name", "")
    p = td.hero_snapshot(nome)["personagem"]
    s = ch["sheet"]
    morto = (ch.get("status") or "").lower() == "morto"
    pode_longo, faltam = td._situacao_descanso_longo(s)
    vida, mana, dados = p["vida"], p["mana"], p["dados_de_vida"]

    # O que falta a ele, na ordem em que pesa numa decisão de descanso.
    precisa = []
    if not morto:
        if vida["atual"] == 0:
            precisa.append("caído")
        elif vida["atual"] < vida["teto"]:
            precisa.append(f"vida {vida['atual']}/{vida['max']}")
        if mana["max"] and mana["atual"] < mana["max"]:
            precisa.append(f"mana {mana['atual']}/{mana['max']}")
        if p["exaustao"]:
            precisa.append(f"exaustão {p['exaustao']}")

    return {
        "nome": nome,
        "classe": p["classe"],
        "raca": p["raca"],
        "nivel": p["nivel"],
        "morto": morto,
        "vida": {**vida, "pct": _pct(vida["atual"], vida["max"])},
        "mana": {**mana, "pct": _pct(mana["atual"], mana["max"])},
        "ca": p["ca"],
        "dados_de_vida": {**dados, "no_longo": td._dados_devolvidos_no_longo(s)},
        "exaustao": p["exaustao"],
        "testes_de_morte": p["testes_de_morte"],
        "concentracao": p["concentracao"],
        "condicoes": p["condicoes"],
        "efeitos": p["efeitos"],
        "carga": _carga(ch),
        "moedas": p["moedas"],
        "itens": p["itens"],
        "nivel_pendente": bool(p["pode_subir"] or p["escolhas_pendentes"]),
        "pode_subir": p["pode_subir"],
        "escolhas_pendentes": p["escolhas_pendentes"],
        "conjura": p["conjura"],
        "descanso": {
            "pode_longo": pode_longo and not morto,
            "faltam_horas": faltam,
            # Curto só adianta a quem está ferido e ainda tem dado para gastar.
            "curto_ajuda": (not morto and 0 < vida["atual"] < vida["teto"]
                            and dados["restantes"] > 0),
        },
        "precisa": precisa,
    }


def _nomes(lista: list[str]) -> str:
    if len(lista) <= 1:
        return "".join(lista)
    return ", ".join(lista[:-1]) + " e " + lista[-1]


def _resumo(herois: list[dict], em_combate: bool) -> dict:
    vivos = [h for h in herois if not h["morto"]]
    feridos = [h["nome"] for h in vivos if h["precisa"]]
    curto = [h["nome"] for h in vivos if h["descanso"]["curto_ajuda"]]
    sem_dado = [h["nome"] for h in vivos
                if 0 < h["vida"]["atual"] < h["vida"]["teto"] and h["dados_de_vida"]["restantes"] == 0]
    podem_longo = [h["nome"] for h in vivos if h["descanso"]["pode_longo"]]
    esperam = sorted(((h["nome"], h["descanso"]["faltam_horas"]) for h in vivos
                      if not h["descanso"]["pode_longo"]), key=lambda x: -x[1])

    if em_combate:
        descanso = "Em combate: descanso só depois da luta."
    elif not feridos:
        descanso = "Ninguém precisa de descanso agora."
    else:
        partes = []
        if curto:
            partes.append(f"O descanso curto ajuda {_nomes(curto)}.")
        if sem_dado:
            partes.append(f"{_nomes(sem_dado)} sem dado de vida: só o longo cura.")
        if podem_longo and not esperam:
            partes.append("O descanso longo está disponível para todos.")
        elif podem_longo:
            nome, horas = esperam[0]
            partes.append(f"Descanso longo: {_nomes(podem_longo)} já podem; "
                          f"{nome} só daqui a {horas}h.")
        else:
            horas = esperam[0][1] if esperam else 0
            partes.append(f"Descanso longo só daqui a {horas}h.")
        descanso = " ".join(partes)

    # Divisão de itens: quem tem mais folga antes de ficar sobrecarregado.
    por_folga = sorted(vivos, key=lambda h: -h["carga"]["folga_kg"])
    pesados = [h["nome"] for h in vivos if h["carga"]["estado"] != "livre"]
    perto = [h["nome"] for h in vivos if h["carga"]["perto_do_limite"]]
    partes = []
    if por_folga:
        partes.append("Mais folga para carregar: "
                      + ", ".join(f"{h['nome']} ({h['carga']['folga_kg']:g} kg)" for h in por_folga[:3])
                      + ".")
    if pesados:
        partes.append(f"Sobrecarregado: {_nomes(pesados)}.")
    if perto:
        partes.append(f"Perto do limite: {_nomes(perto)}.")

    return {
        "descanso": descanso,
        "carga": " ".join(partes),
        "nivel_pendente": [h["nome"] for h in vivos if h["nivel_pendente"]],
        "feridos": feridos,
        "curto_ajuda": curto,
        "longo_disponivel": bool(podem_longo),
        "mais_folga": por_folga[0]["nome"] if por_folga else "",
    }


def _sem_ficha() -> list[dict]:
    """
    Quem está no grupo sem ficha de regras: o companheiro que o mestre
    recrutou pela narrativa e nunca recebeu atributos.

    Numa campanha D&D essa gente sumia da barra lateral e da visão geral, que
    só conheciam quem tem ficha — como se não estivesse no grupo. Aqui eles
    voltam com o que existe deles: nome, papel e a descrição.
    """
    chars = memory.campaign.get("characters", {}) or {}
    papeis = {memory.char_key(m.get("name", "")): (m.get("role") or "")
              for m in (memory.campaign.get("party") or []) if isinstance(m, dict)}
    fora = []
    for ch in chars.values():
        if not memory.is_party_member(ch) or (ch.get("sheet") or {}):
            continue
        nome = ch.get("name", "")
        fora.append({
            "nome": nome,
            "papel": papeis.get(memory.char_key(nome), "") or (ch.get("role") or ""),
            "descricao": (ch.get("description") or "").strip(),
            "morto": (ch.get("status") or "").lower() == "morto",
        })
    return sorted(fora, key=lambda x: x["nome"].lower())


def group_snapshot() -> dict:
    """O grupo lado a lado e o resumo (JSON-serializável)."""
    herois = [_heroi(ch) for ch in td._grupo_com_ficha()]
    em_combate = td._em_combate()
    return {
        "herois": herois,
        "sem_ficha": _sem_ficha(),
        "em_combate": em_combate,
        "hora": td._hora_legivel(),
        "resumo": _resumo(herois, em_combate),
    }
