"""
mapa.py
O mapa do mundo para a tela: a árvore de lugares (o que fica dentro de quê),
onde o grupo está, o que está a um passo e quem está em cada lugar.

A hierarquia já existia (locais.py: "fica dentro de" nos locais, "onde está"
nos personagens, lojas dentro da cidade), mas só se via um lugar por vez, na
ficha do local. Não havia como olhar o mundo inteiro de uma vez nem achar
"onde estava mesmo o Brom?".

Não é um mapa com coordenadas: o motor não tem distância nem direção, e
desenhar lugares num plano inventaria uma geografia que a campanha não tem.
É uma árvore, que é exatamente o que os dados dizem.

Nada aqui inventa lugar. Um nome que aparece como "onde está" de alguém ou
como local atual, mas nunca foi registrado, entra marcado como sem registro
para não sumir da vista.
"""
from rpg import locais, memory

_FORA = ("morto", "desaparecido", "preso", "exilado", "fugiu")


def _todos_os_lugares() -> dict:
    """norm(nome) → {"nome", "tipo", "dentro_de", "descricao"} de locais e lojas."""
    saida = {}
    for loc in (memory.campaign.get("locations") or {}).values():
        if isinstance(loc, dict) and (loc.get("name") or "").strip():
            saida[locais.norm(loc["name"])] = {
                "nome": loc["name"], "tipo": "local",
                "dentro_de": loc.get("dentro_de", "") or "",
                "descricao": (loc.get("description", "") or "")[:140],
                "mudancas": len(loc.get("mudancas") or [])}
    for loja in (memory.campaign.get("lojas") or {}).values():
        if not isinstance(loja, dict) or not (loja.get("nome") or "").strip():
            continue
        chave = locais.norm(loja["nome"])
        if chave in saida:
            continue                   # também salva como local: não repete
        saida[chave] = {"nome": loja["nome"], "tipo": "loja",
                        "dentro_de": loja.get("local", "") or "", "descricao": ""}
    return saida


def mapa_snapshot() -> dict:
    lugares = _todos_os_lugares()
    atual = memory.campaign.get("current_location", "") or ""
    chars = [c for c in (memory.campaign.get("characters") or {}).values() if isinstance(c, dict)]
    grupo = [c.get("name", "") for c in chars if memory.is_party_member(c)]

    # Nomes citados e nunca registrados: o local atual e o "onde está" de alguém.
    citados = [atual] + [c.get("local", "") for c in chars if not memory.is_party_member(c)]
    for nome in citados:
        chave = locais.norm(nome)
        if chave and chave not in lugares:
            lugares[chave] = {"nome": nome.strip(), "tipo": "sem_registro",
                              "dentro_de": "", "descricao": ""}

    pessoas = {}
    sem_paradeiro = []
    for c in chars:
        if memory.is_party_member(c):
            continue
        chave = locais.norm(c.get("local", ""))
        status = (c.get("status") or "vivo")
        if not chave:
            sem_paradeiro.append({"nome": c.get("name", ""), "status": status})
            continue
        pessoas.setdefault(chave, []).append({"nome": c.get("name", ""), "status": status,
                                              "fora": status.lower() in _FORA})

    filhos: dict[str, list[str]] = {}
    raizes = []
    for chave, lug in lugares.items():
        pai = locais.norm(lug["dentro_de"])
        if pai and pai in lugares and pai != chave:
            filhos.setdefault(pai, []).append(chave)
        else:
            raizes.append(chave)

    caminho_atual = {locais.norm(n) for n in locais.caminho(atual)} if atual else set()

    visitados: set[str] = set()

    def no(chave: str, profundidade: int, vistos: frozenset) -> dict:
        visitados.add(chave)
        lug = lugares[chave]
        sub = [] if chave in vistos else [
            no(f, profundidade + 1, vistos | {chave})
            for f in sorted(filhos.get(chave, []), key=lambda k: locais.norm(lugares[k]["nome"]))]
        aqui = pessoas.get(chave, [])
        total = len(aqui) + sum(n["pessoas_total"] for n in sub)
        return {
            "nome": lug["nome"], "tipo": lug["tipo"], "descricao": lug["descricao"],
            "mudancas": lug.get("mudancas", 0),
            "alcance": locais.alcance(lug["nome"]),
            "grupo_aqui": chave == locais.norm(atual) and bool(atual),
            # O caminho até onde o grupo está vem aberto na árvore.
            "no_caminho_do_grupo": chave in caminho_atual,
            "pessoas": aqui, "pessoas_total": total,
            "filhos": sub, "profundidade": profundidade,
        }

    arvore = [no(r, 0, frozenset())
              for r in sorted(raizes, key=lambda k: (not (k in caminho_atual), locais.norm(lugares[k]["nome"])))]
    # Um ciclo de "dentro de" (dado editado à mão) não tem raiz e sumiria da
    # árvore: entra pelo primeiro lugar dele que ninguém visitou.
    for chave in sorted(lugares):
        if chave not in visitados:
            arvore.append(no(chave, 0, frozenset()))

    ao_alcance = sorted(
        ({"nome": l["nome"], "tipo": l["tipo"], "alcance": locais.alcance(l["nome"])}
         for l in lugares.values() if locais.alcance(l["nome"]) in ("dentro", "acima", "vizinho")),
        key=lambda x: ({"dentro": 0, "vizinho": 1, "acima": 2}[x["alcance"]], locais.norm(x["nome"])))

    return {
        "local_atual": locais.nome_canonico(atual) if atual else "",
        "caminho_atual": locais.caminho(atual) if atual else [],
        "grupo": grupo,
        "arvore": arvore,
        "ao_alcance": ao_alcance,
        "sem_paradeiro": sem_paradeiro,
        "total_lugares": len(lugares),
    }
