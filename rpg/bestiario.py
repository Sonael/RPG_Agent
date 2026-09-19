"""
bestiario.py
Bestiário: as criaturas que o grupo enfrentou ou das quais ouviu falar.

O que o grupo aprende sobre um monstro — que teme fogo, que só caça à noite,
que a prata o fere — se perdia entre uma luta e outra. Agora cada criatura
tem uma página com o que se sabe dela, separado em fatos e fraquezas, quantas
vezes foi encontrada e quantas derrotada. Só entra o que o grupo descobriu.
"""
from rpg import locais, memory

MAX_CRIATURAS = 80
MAX_NOTAS = 12
TIPOS_DE_NOTA = ("fato", "fraqueza")


def _texto(s) -> str:
    return " ".join(str(s or "").split())


def _todas() -> dict:
    return memory.campaign.setdefault("bestiario", {})


def _criatura(nome: str):
    return _todas().get(locais.norm(nome or ""))


def registrar(nome: str, descricao: str = "", tipo: str = "", encontro: bool = True, derrotada: bool = False) -> str:
    nome = _texto(nome)
    if not nome:
        return "Informe o nome da criatura."
    c = _criatura(nome)
    if not c:
        if len(_todas()) >= MAX_CRIATURAS:
            return f"Já são {MAX_CRIATURAS} criaturas no bestiário."
        c = _todas()[locais.norm(nome)] = {"nome": nome, "tipo": _texto(tipo), "descricao": _texto(descricao),
                                          "fatos": [], "fraquezas": [], "encontros": 0, "derrotadas": 0,
                                          "cap": memory.campaign.get("chapter", 1)}
        novo = True
    else:
        novo = False
        if _texto(descricao):
            c["descricao"] = _texto(descricao)
        if _texto(tipo):
            c["tipo"] = _texto(tipo)
    if encontro:
        c["encontros"] = int(c.get("encontros", 0) or 0) + 1
    if derrotada:
        c["derrotadas"] = int(c.get("derrotadas", 0) or 0) + 1
    memory.save_campaign()
    return (f"{'Nova página no bestiário' if novo else 'Bestiário atualizado'}: **{c['nome']}**"
            f" (encontrada {c['encontros']}x, derrotada {c['derrotadas']}x).")


def anotar(nome: str, nota: str, tipo: str = "fato") -> str:
    c = _criatura(nome)
    if not c:
        return f"'{nome}' não está no bestiário. Use registrar_criatura primeiro."
    nota = _texto(nota)
    if not nota:
        return "Escreva o que o grupo descobriu."
    tipo = locais.norm(tipo or "fato")
    if tipo not in TIPOS_DE_NOTA:
        return "Use tipo=\"fato\" ou tipo=\"fraqueza\"."
    campo = "fatos" if tipo == "fato" else "fraquezas"
    if any(locais.norm(n.get("texto", "")) == locais.norm(nota) for n in c[campo]):
        return "O grupo já sabe disso."
    c[campo].append({"texto": nota, "cap": memory.campaign.get("chapter", 1)})
    del c[campo][:-MAX_NOTAS]
    memory.save_campaign()
    return f"{c['nome']}: agora o grupo sabe — {nota}" + (" (fraqueza)" if campo == "fraquezas" else "")


def visiveis() -> list[dict]:
    lista = [{"nome": c["nome"], "tipo": c.get("tipo", ""), "descricao": c.get("descricao", ""),
              "fatos": [n.get("texto", "") for n in c.get("fatos") or [] if isinstance(n, dict)],
              "fraquezas": [n.get("texto", "") for n in c.get("fraquezas") or [] if isinstance(n, dict)],
              "encontros": int(c.get("encontros", 0) or 0), "derrotadas": int(c.get("derrotadas", 0) or 0)}
             for c in _todas().values() if isinstance(c, dict)]
    return sorted(lista, key=lambda c: locais.norm(c["nome"]))


def resumo_para_o_mestre() -> str:
    linhas = []
    for c in visiveis():
        if c["fraquezas"]:
            linhas.append(f"• {c['nome']}: o grupo sabe das fraquezas — {'; '.join(c['fraquezas'])}")
    return "\n".join(linhas)


def importar(valor) -> dict:
    """O bestiário de um JSON importado: lista ou dicionário, chave pelo nome, notas em texto ou lista."""
    def notas(lista):
        # Um texto solto (outra IA mandou "fatos": "caça à noite") é um fato só.
        if isinstance(lista, str):
            lista = [lista]
        saida = []
        for n in lista or []:
            texto = n.get("texto") if isinstance(n, dict) else n
            if _texto(texto) and locais.norm(texto) not in {locais.norm(x["texto"]) for x in saida}:
                saida.append({"texto": _texto(texto), "cap": (n.get("cap") if isinstance(n, dict) else None) or 1})
        return saida[-MAX_NOTAS:]

    def inteiro(v):
        try:
            return max(0, int(v or 0))
        except (TypeError, ValueError):
            return 0

    itens = valor.values() if isinstance(valor, dict) else (valor or [])
    saida = {}
    for c in itens:
        if not isinstance(c, dict) or not _texto(c.get("nome")) or locais.norm(c["nome"]) in saida:
            continue
        saida[locais.norm(c["nome"])] = {
            "nome": _texto(c["nome"]), "tipo": _texto(c.get("tipo")), "descricao": _texto(c.get("descricao")),
            "fatos": notas(c.get("fatos")), "fraquezas": notas(c.get("fraquezas")),
            "encontros": inteiro(c.get("encontros")), "derrotadas": inteiro(c.get("derrotadas")),
            "cap": c.get("cap") or 1,
        }
        if len(saida) >= MAX_CRIATURAS:
            break
    return saida
