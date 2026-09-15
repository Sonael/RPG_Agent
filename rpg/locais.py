"""
locais.py
Hierarquia de locais e onde cada personagem está.

Os locais eram uma lista plana: Cliviate, a Forja de Cliviate e o Boticário
não se conheciam, e personagem nenhum tinha paradeiro — só o grupo tinha
(`current_location`). Isto dá aos locais um "fica dentro de" e aos
personagens um "onde está", e monta a ficha do local que a tela mostra.

Lojas entram na hierarquia sem precisar de registro próprio: `open_shop` já
grava em `lojas[...]["local"]` a cidade onde a loja fica, e isto a trata como
um lugar dentro dela.

Nada aqui inventa lugar nem pessoa. Campanha antiga, sem `dentro_de` nem
`local`, só mostra menos.
"""
import unicodedata

from rpg import memory


def norm(texto: str) -> str:
    """Sem caixa, acento e espaço duplicado — para casar nomes."""
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(t.split())


def _locais() -> dict:
    return memory.campaign.get("locations") or {}


def _lojas() -> dict:
    return memory.campaign.get("lojas") or {}


def lugar(nome: str) -> dict | None:
    """
    O lugar com esse nome: um local salvo, ou uma loja tratada como lugar
    ({"name", "description", "dentro_de", "tipo": "loja"}). None se não há.
    """
    alvo = norm(nome)
    if not alvo:
        return None
    for loc in _locais().values():
        if isinstance(loc, dict) and norm(loc.get("name", "")) == alvo:
            return {**loc, "tipo": "local"}
    for loja in _lojas().values():
        if isinstance(loja, dict) and norm(loja.get("nome", "")) == alvo:
            return {"name": loja.get("nome", ""), "description": "",
                    "details": "", "notes": "", "tipo": "loja",
                    "dentro_de": loja.get("local", "")}
    return None


def nome_canonico(nome: str) -> str:
    """O nome como está gravado, se o lugar existe; senão o próprio texto."""
    achado = lugar(nome)
    return achado["name"] if achado else (nome or "").strip()


def pai_de(nome: str) -> str:
    """Nome do lugar onde este fica ("" se nenhum ou desconhecido)."""
    achado = lugar(nome)
    return (achado or {}).get("dentro_de", "") or ""


def caminho(nome: str) -> list[str]:
    """Do lugar mais de fora até este: ["Cliviate", "Forja de Cliviate"]."""
    trilha, vistos = [], set()
    atual = nome_canonico(nome)
    while atual and norm(atual) not in vistos:
        vistos.add(norm(atual))
        trilha.append(atual)
        atual = nome_canonico(pai_de(atual)) if pai_de(atual) else ""
    return list(reversed(trilha))


def esta_dentro(nome: str, de: str) -> bool:
    """`nome` é `de` ou fica (em qualquer nível) dentro de `de`?"""
    alvo = norm(de)
    return bool(alvo) and any(norm(p) == alvo for p in caminho(nome))


def filhos(nome: str) -> list[dict]:
    """Os lugares que ficam diretamente dentro deste (locais e lojas)."""
    alvo = norm(nome)
    if not alvo:
        return []
    saida, vistos = [], set()
    for loc in _locais().values():
        if isinstance(loc, dict) and norm(loc.get("dentro_de", "")) == alvo:
            vistos.add(norm(loc.get("name", "")))
            saida.append({"nome": loc.get("name", ""), "tipo": "local",
                          "descricao": loc.get("description", "") or ""})
    for loja in _lojas().values():
        if not isinstance(loja, dict) or norm(loja.get("local", "")) != alvo:
            continue
        if norm(loja.get("nome", "")) in vistos:
            continue           # a loja também foi salva como local: não repete
        saida.append({"nome": loja.get("nome", ""), "tipo": "loja", "descricao": ""})
    return saida


def alcance(destino: str) -> str:
    """
    De onde o grupo está, dá para ir até `destino` com um passo?
      "aqui"    — é onde o grupo está;
      "dentro"  — fica dentro do local atual;
      "acima"   — é o lugar onde o local atual fica (sair da loja para a rua);
      "vizinho" — fica dentro do mesmo lugar que o local atual;
      ""        — longe: viagem é com o mestre, não com um clique.
    """
    atual = memory.campaign.get("current_location", "") or ""
    d, a = norm(destino), norm(atual)
    if not d or not a:
        return ""
    if d == a:
        return "aqui"
    if norm(pai_de(destino)) == a:
        return "dentro"
    pai_atual = norm(pai_de(atual))
    if pai_atual and d == pai_atual:
        return "acima"
    if pai_atual and norm(pai_de(destino)) == pai_atual:
        return "vizinho"
    return ""


def pessoas_em(nome: str) -> list[dict]:
    """Personagens cujo "onde está" é este lugar (fora do grupo)."""
    alvo = norm(nome)
    if not alvo:
        return []
    saida = []
    for ch in (memory.campaign.get("characters") or {}).values():
        if not isinstance(ch, dict) or memory.is_party_member(ch):
            continue
        if norm(ch.get("local", "")) == alvo:
            saida.append(ch)
    return saida


def normalizar_campanha_editada(novos_locais: dict, antigos_locais: dict,
                                novos_chars: dict, antigos_chars: dict,
                                lojas: dict) -> tuple[dict, str]:
    """
    Aplica ao que o editor da campanha (menu) mandou as regras de lugar, sem
    depender da campanha carregada em memória. Devolve (locais, erro).

    - Chave do local = nome em minúsculas, como save_location grava. O editor
      gravava "praça_de_cliviate" e o mestre depois criava "praça de cliviate"
      ao lado: o mesmo lugar duas vezes.
    - Campo que o editor não manda fica como estava gravado (no local e no
      personagem): atitude, marca de XP por derrota, "onde está" antigo.
    - dentro_de e local gravados com o nome como o lugar está salvo;
      dentro_de vazio apaga; ciclo é erro.
    """
    antigos_locais = antigos_locais or {}
    antigos_por_nome = {norm((l or {}).get("name", k)): l for k, l in antigos_locais.items()
                        if isinstance(l, dict)}

    locais_saida = {}
    for chave, loc in (novos_locais or {}).items():
        if not isinstance(loc, dict) or not (loc.get("name") or "").strip():
            continue
        nome = loc["name"].strip()
        antigo = antigos_locais.get(chave) or antigos_por_nome.get(norm(nome)) or {}
        junto = {**antigo, **loc, "name": nome}
        if "dentro_de" in loc and not (loc.get("dentro_de") or "").strip():
            junto.pop("dentro_de", None)
        locais_saida[nome.lower()] = junto

    nomes = {norm(l["name"]): l["name"] for l in locais_saida.values()}
    for loja in (lojas or {}).values():
        if isinstance(loja, dict) and loja.get("nome"):
            nomes.setdefault(norm(loja["nome"]), loja["nome"])

    def canonico(texto: str) -> str:
        return nomes.get(norm(texto), (texto or "").strip())

    for loc in locais_saida.values():
        if loc.get("dentro_de"):
            loc["dentro_de"] = canonico(loc["dentro_de"])

    # Ciclo: subir pelo dentro_de a partir de cada local não pode voltar nele.
    pai_de_nome = {norm(l["name"]): norm(l.get("dentro_de", "")) for l in locais_saida.values()}
    for loc in locais_saida.values():
        vistos, atual = {norm(loc["name"])}, pai_de_nome.get(norm(loc["name"]), "")
        while atual:
            if atual in vistos:
                return locais_saida, (f"'{loc['name']}' não pode ficar dentro de "
                                      f"'{loc['dentro_de']}': um dos dois já fica dentro do outro.")
            vistos.add(atual)
            atual = pai_de_nome.get(atual, "")

    antigos_chars = antigos_chars or {}
    for chave, ch in (novos_chars or {}).items():
        if not isinstance(ch, dict):
            continue
        antigo = (antigos_chars.get(chave)
                  or antigos_chars.get((ch.get("name") or "").lower().strip())
                  or next((a for a in antigos_chars.values()
                           if isinstance(a, dict) and norm(a.get("name", "")) == norm(ch.get("name", ""))), None)
                  or {})
        for campo, valor in antigo.items():
            ch.setdefault(campo, valor)
        if "conhecido" in ch:
            from rpg.personagens import limpar_conhecido
            ch["conhecido"] = limpar_conhecido(ch["conhecido"])
        if "local" in ch:
            if (ch.get("local") or "").strip():
                ch["local"] = canonico(ch["local"])
            else:
                ch.pop("local", None)
    return locais_saida, ""


_FORA_DE_ALCANCE = ("morto", "desaparecido", "preso", "exilado", "fugiu")


def ficha(nome: str = "") -> dict:
    """
    A ficha do local para a tela: o lugar, o caminho até ele, o que fica
    dentro, quem está lá e o que dá para fazer com um clique.
    Sem nome, é o local atual do grupo.
    """
    atual = memory.campaign.get("current_location", "") or ""
    alvo_nome = (nome or atual or "").strip()
    achado = lugar(alvo_nome)
    nome_final = achado["name"] if achado else alvo_nome
    e_atual = bool(nome_final) and norm(nome_final) == norm(atual)

    grupo = []
    if e_atual:
        for ch in (memory.campaign.get("characters") or {}).values():
            if isinstance(ch, dict) and memory.is_party_member(ch):
                grupo.append(ch.get("name", ""))

    pessoas = []
    alcance_aqui = alcance(nome_final)
    for ch in pessoas_em(nome_final):
        status = (ch.get("status", "") or "vivo").lower()
        pessoas.append({
            "nome": ch.get("name", ""),
            "status": ch.get("status", "") or "vivo",
            "descricao": (ch.get("description", "") or "")[:160],
            # Falar é com quem está onde o grupo está, ou a um passo.
            "pode_falar": bool(alcance_aqui) and status not in _FORA_DE_ALCANCE,
        })

    pai = pai_de(nome_final)
    return {
        "existe": bool(achado),
        "nome": nome_final,
        "tipo": (achado or {}).get("tipo", "local"),
        "descricao": (achado or {}).get("description", "") or "",
        "detalhes": (achado or {}).get("details", "") or "",
        "caminho": caminho(nome_final) if nome_final else [],
        "pai": {"nome": nome_canonico(pai), "alcance": alcance(pai)} if pai else None,
        "e_o_local_atual": e_atual,
        "local_atual": atual,
        "alcance": alcance_aqui,
        "grupo_aqui": grupo,
        "dentro": [{**f, "alcance": alcance(f["nome"]),
                    "pessoas": len(pessoas_em(f["nome"]))}
                   for f in filhos(nome_final)],
        "pessoas": pessoas,
    }
