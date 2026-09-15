"""
saque.py
Tela de saque ("O Espólio"): o mestre põe o que caiu no chão e o grupo decide
quem fica com o quê, vendo a carga de cada um.

Antes, no fim do combate, o mestre chamava add_item e modify_currency direto
na ficha de quem ele achasse melhor. O peso existe justamente para o saque
virar escolha (levar a cota de malha deixa o guerreiro sobrecarregado na
próxima luta), e essa escolha era do mestre, não do jogador.

Fluxo, o mesmo do descanso:
  1. o mestre chama offer_loot("Espada Curta; Poção de Cura:2", gold=25);
     a conferência de item inventado roda AQUI, e os avisos voltam para ele;
  2. a tela abre sozinha (fila de telas), o jogador distribui item a item e
     escolhe como dividir as moedas;
  3. ao concluir, os itens entram nos inventários e a tela manda
     [SAQUE RESOLVIDO NA TELA]; o mestre narra sem dar nada de novo.

O que ninguém pegou fica para trás. A proposta mora na campanha (não no
navegador) porque é estado do mundo: vale em qualquer aba ou aparelho.
"""
from rpg import memory


class _MotorTardio:
    """
    tools_dnd importa offer_loot deste módulo para pô-la em DND_TOOLS, e este
    módulo usa as funções de tools_dnd. Importar tools_dnd no topo fechava o
    ciclo pela metade quando saque era importado primeiro; aqui o import só
    acontece no primeiro uso, com os dois módulos já prontos.
    """
    def __getattr__(self, nome):
        from rpg import tools_dnd
        return getattr(tools_dnd, nome)


td = _MotorTardio()

_MOEDAS = ("ouro", "prata", "cobre")
_ABREV = {"ouro": "po", "prata": "pp", "cobre": "pc"}


# ---------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------

def _saque() -> dict | None:
    s = memory.campaign.get("saque_proposto")
    return s if isinstance(s, dict) and isinstance(s.get("itens"), list) else None


def _grupo() -> list[dict]:
    return td._grupo_com_ficha()


def _vivos() -> list[dict]:
    return [c for c in _grupo() if (c.get("status") or "").lower() != "morto"]


def _membro(nome: str) -> dict | None:
    alvo = td._norm_txt(nome or "")
    return next((c for c in _vivos() if td._norm_txt(c.get("name", "")) == alvo), None)


def _item(saque: dict, item: str) -> dict | None:
    """Por id (o que a tela manda) ou pelo nome."""
    for it in saque["itens"]:
        if str(it.get("id")) == str(item).strip():
            return it
    alvo = td._norm_txt(item or "")
    return next((it for it in saque["itens"] if td._norm_txt(it.get("nome", "")) == alvo), None)


def _sobra(it: dict) -> int:
    return int(it.get("qtd", 0)) - sum(int(v) for v in (it.get("divisao") or {}).values())


def _texto_moedas(m: dict) -> str:
    partes = [f"{int(m.get(k, 0))} {_ABREV[k]}" for k in _MOEDAS if int(m.get(k, 0) or 0)]
    return " ".join(partes)


def _divisao_das_moedas(saque: dict) -> dict:
    """
    Quanto de cada moeda vai para cada um. "igual": divide entre os vivos, e o
    resto de cada moeda vai, uma unidade por vez, para os primeiros do grupo.
    Um nome: tudo para essa pessoa.
    """
    vivos = [c.get("name", "") for c in _vivos()]
    saida = {n: {k: 0 for k in _MOEDAS} for n in vivos}
    if not vivos:
        return saida
    moedas = saque.get("moedas") or {}
    destino = saque.get("moedas_para") or "igual"
    dono = next((n for n in vivos if td._norm_txt(n) == td._norm_txt(destino)), None)
    for k in _MOEDAS:
        total = int(moedas.get(k, 0) or 0)
        if dono:
            saida[dono][k] = total
            continue
        cota, resto = divmod(total, len(vivos))
        for i, n in enumerate(vivos):
            saida[n][k] = cota + (1 if i < resto else 0)
    return saida


# ---------------------------------------------------------------------------
# Ferramenta do mestre
# ---------------------------------------------------------------------------

def _ler_itens(items: str) -> list[tuple[str, int, str]]:
    """'Espada Curta; Poção de Cura:2; Anel de Osso:1:não faz nada' → (nome, qtd, descrição)."""
    lidos = []
    for bruto in (items or "").split(";"):
        partes = [p.strip() for p in bruto.split(":", 2)]
        nome = partes[0] if partes else ""
        if not nome:
            continue
        qtd = 1
        if len(partes) > 1 and partes[1]:
            try:
                qtd = max(1, int(partes[1]))
            except ValueError:
                qtd = 1
        desc = partes[2] if len(partes) > 2 else ""
        lidos.append((nome, qtd, desc))
    return lidos


def offer_loot(items: str = "", gold: int = 0, silver: int = 0, copper: int = 0,
               source: str = "") -> str:
    """
    Abre a TELA DE SAQUE: o que caiu (dos inimigos, de um baú, de um corpo)
    fica no chão e o JOGADOR decide quem do grupo leva o quê, vendo a carga de
    cada um. Chame no fim do combate ou ao abrir um baú, NO LUGAR de add_item e
    modify_currency: não entregue o saque direto na ficha de ninguém.

    Chamar de novo com o saque ainda aberto acrescenta ao que já está no chão.
    Quando o jogador concluir chega [SAQUE RESOLVIDO NA TELA] com quem ficou
    com o quê: aí narre, sem dar nada de novo.

    Args:
        items:  Itens separados por ';', com quantidade opcional após ':' e
                descrição opcional após o segundo ':'.
                Ex: "Espada Curta; Poção de Cura:2; Anel de Osso:1:lembrança, não faz nada"
        gold:   Peças de ouro no saque.
        silver: Peças de prata.
        copper: Peças de cobre.
        source: De onde vem (ex: "os bandidos da estrada", "o baú do capitão").
    """
    if td._em_combate():
        return "Erro: Há um combate em andamento. Abra o saque depois que a luta acabar."
    if not _grupo():
        return "Erro: Nenhum personagem com ficha no grupo para dividir o saque."
    lidos = _ler_itens(items)
    moedas = {"ouro": max(0, int(gold or 0)), "prata": max(0, int(silver or 0)),
              "cobre": max(0, int(copper or 0))}
    if not lidos and not any(moedas.values()):
        return "Aviso: O saque está vazio. Informe itens ou moedas."

    saque = _saque()
    if not saque:
        contador = int(memory.campaign.get("saques_oferecidos", 0) or 0) + 1
        memory.campaign["saques_oferecidos"] = contador
        saque = {"id": contador, "origem": (source or "").strip(), "itens": [],
                 "moedas": {k: 0 for k in _MOEDAS}, "moedas_para": "igual",
                 "proximo_item": 1}
        memory.campaign["saque_proposto"] = saque
    elif (source or "").strip() and not saque.get("origem"):
        saque["origem"] = source.strip()

    nivel = max((int((c.get("sheet") or {}).get("nivel", 1) or 1) for c in _grupo()), default=1)
    avisos, entrou = [], []
    for nome, qtd, desc in lidos:
        existente = next((it for it in saque["itens"]
                          if td._norm_txt(it.get("nome", "")) == td._norm_txt(nome)), None)
        if existente:
            existente["qtd"] = int(existente.get("qtd", 0)) + qtd
            entrou.append(f"{existente['nome']} ×{qtd}")
            continue
        # A mesma conferência de add_item: item inventado com regra é cobrado
        # AGORA, do mestre, e não quando o jogador já pôs na mochila.
        ficha, aviso = td._conferir_item_novo(nome, desc, nivel)
        ficha["qtd"] = qtd
        ficha["id"] = int(saque.get("proximo_item", 1))
        saque["proximo_item"] = ficha["id"] + 1
        ficha["peso"] = td._peso_do_item({"nome": nome})
        ficha["divisao"] = {}
        saque["itens"].append(ficha)
        entrou.append(f"{nome} ×{qtd} ({ficha['peso']:g} kg cada)")
        if aviso:
            avisos.append(aviso.strip())
    for k in _MOEDAS:
        saque["moedas"][k] = int(saque["moedas"].get(k, 0)) + moedas[k]
    memory.save_campaign()

    linhas = [f"Saque aberto na TELA DE SAQUE"
              + (f" ({saque['origem']})" if saque.get("origem") else "") + "."]
    if entrou:
        linhas.append("   No chão: " + "; ".join(entrou) + ".")
    if any(moedas.values()):
        linhas.append(f"   Moedas: {_texto_moedas(saque['moedas'])} no total.")
    linhas.append("   Quem decide quem leva o quê é o JOGADOR. Não chame add_item nem "
                  "modify_currency para estes itens.")
    linhas.append("   Aguarde [SAQUE RESOLVIDO NA TELA] para narrar.")
    linhas.extend(avisos)
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Tela
# ---------------------------------------------------------------------------

def _carga_de(ch: dict, extra_kg: float = 0.0) -> dict:
    estado, kg, cap = td._estado_de_carga(ch)
    previsto = round(kg + extra_kg, 2)
    if previsto > cap:
        est_prev = "imovel"
    elif previsto > cap / 2:
        est_prev = "sobrecarregado"
    else:
        est_prev = "livre"
    return {"kg": kg, "capacidade": cap, "metade": round(cap / 2, 1), "estado": estado,
            "kg_previsto": previsto, "estado_previsto": est_prev}


def loot_snapshot() -> dict:
    """Estado do saque para a tela (JSON-serializável)."""
    saque = _saque()
    base = {"tem_saque": bool(saque), "saque": None, "em_combate": td._em_combate(),
            "grupo": []}
    divisao_moedas = _divisao_das_moedas(saque) if saque else {}
    for c in _grupo():
        nome = c.get("name", "")
        morto = (c.get("status") or "").lower() == "morto"
        recebe, extra = [], 0.0
        for it in (saque or {}).get("itens", []):
            n = int((it.get("divisao") or {}).get(nome, 0))
            if n:
                recebe.append({"id": it["id"], "nome": it["nome"], "qtd": n})
                extra += float(it.get("peso", 0) or 0) * n
        s = c.get("sheet") or {}
        base["grupo"].append({
            "nome": nome, "classe": s.get("classe", ""), "nivel": int(s.get("nivel", 1) or 1),
            "morto": morto, "forca": int(s.get("forca", 10) or 10),
            "carga": _carga_de(c, extra),
            "recebe": recebe,
            "moedas_recebe": divisao_moedas.get(nome, {k: 0 for k in _MOEDAS}),
        })
    if saque:
        itens = []
        for it in saque["itens"]:
            itens.append({
                "id": it["id"], "nome": it["nome"], "qtd": int(it.get("qtd", 0)),
                "sobra": _sobra(it), "peso": float(it.get("peso", 0) or 0),
                "descricao": it.get("descricao", "") or "",
                "custom": bool(it.get("custom")),
                "divisao": dict(it.get("divisao") or {}),
            })
        base["saque"] = {
            "id": saque.get("id", 0), "origem": saque.get("origem", ""),
            "itens": itens, "moedas": dict(saque.get("moedas") or {}),
            "moedas_para": saque.get("moedas_para") or "igual",
            "sobrando": sum(i["sobra"] for i in itens),
        }
    return base


def loot_action(action: str, item: str = "", char: str = "", quantity: int = 1,
                coins_to: str = "") -> dict:
    """
    Aplica UMA intenção da tela de saque.

    actions: dar | devolver | moedas | concluir | deixar
    """
    a = (action or "").lower().strip()
    saque = _saque()

    def _resposta(ok, msg):
        return {"ok": ok, "message": msg, "snapshot": loot_snapshot()}

    if a not in ("dar", "devolver", "moedas", "concluir", "deixar"):
        return _resposta(False, f"Erro: Ação '{action}' desconhecida.")
    if not saque:
        return _resposta(False, "Erro: Nenhum saque aberto.")
    try:
        qtd = max(1, int(quantity or 1))
    except (TypeError, ValueError):
        qtd = 1

    if a in ("dar", "devolver"):
        it = _item(saque, item)
        if not it:
            return _resposta(False, f"Erro: '{item}' não está no saque.")
        membro = _membro(char)
        if not membro:
            return _resposta(False, f"Erro: '{char}' não é alguém do grupo que possa levar itens.")
        nome = membro["name"]
        divisao = it.setdefault("divisao", {})
        if a == "dar":
            if _sobra(it) < qtd:
                return _resposta(False, f"Aviso: Não sobrou {it['nome']} no chão para dar.")
            divisao[nome] = int(divisao.get(nome, 0)) + qtd
            msg = f"{it['nome']} ×{qtd} para {nome}."
        else:
            tem = int(divisao.get(nome, 0))
            if tem <= 0:
                return _resposta(False, f"Aviso: {nome} não está levando {it['nome']}.")
            divisao[nome] = tem - min(qtd, tem)
            if divisao[nome] <= 0:
                divisao.pop(nome, None)
            msg = f"{it['nome']} voltou para o chão."
        memory.save_campaign()
        return _resposta(True, msg)

    if a == "moedas":
        destino = (coins_to or "").strip()
        if destino.lower() != "igual":
            membro = _membro(destino)
            if not membro:
                return _resposta(False, f"Erro: '{destino}' não é alguém do grupo.")
            destino = membro["name"]
        else:
            destino = "igual"
        saque["moedas_para"] = destino
        memory.save_campaign()
        return _resposta(True, "Moedas divididas por igual." if destino == "igual"
                         else f"Todas as moedas para {destino}.")

    if a == "deixar":
        memory.campaign.pop("saque_proposto", None)
        memory.save_campaign()
        return _resposta(True, "O grupo deixou o saque para trás.")

    # concluir
    if td._em_combate():
        return _resposta(False, "Erro: Um combate começou. Dá para dividir o saque depois.")
    por_membro: dict[str, list[str]] = {}
    for it in saque["itens"]:
        for nome, n in (it.get("divisao") or {}).items():
            n = int(n)
            membro = _membro(nome)
            if not membro or n <= 0:
                continue
            _guardar(membro, it, n)
            por_membro.setdefault(membro["name"], []).append(
                f"{n}x {it['nome']}" if n > 1 else it["nome"])
    moedas = _divisao_das_moedas(saque)
    for nome, m in moedas.items():
        membro = _membro(nome)
        if not membro:
            continue
        s = membro["sheet"]
        for k in _MOEDAS:
            if m[k]:
                s[k] = int(s.get(k, 0) or 0) + m[k]
        texto = _texto_moedas(m)
        if texto:
            por_membro.setdefault(membro["name"], []).append(texto)
    deixados = [f"{_sobra(it)}x {it['nome']}" if _sobra(it) > 1 else it["nome"]
                for it in saque["itens"] if _sobra(it) > 0]
    memory.campaign.pop("saque_proposto", None)
    memory.save_campaign()

    partes = [f"{nome}: {', '.join(coisas)}" for nome, coisas in por_membro.items()]
    msg = ("Saque dividido — " + ("; ".join(partes) if partes else "ninguém levou nada") + "."
           + (f" Ficaram para trás: {', '.join(deixados)}." if deixados else ""))
    return _resposta(True, msg)


def _guardar(membro: dict, it: dict, qtd: int) -> None:
    """Põe `qtd` unidades de um item do saque no inventário, empilhando como add_item."""
    inv = membro.setdefault("inventario", [])
    existente = next((i for i in inv if isinstance(i, dict)
                      and td._norm_txt(i.get("nome", "")) == td._norm_txt(it["nome"])), None)
    if existente:
        existente["qtd"] = int(existente.get("qtd", 0) or 0) + qtd
        return
    novo = {k: v for k, v in it.items() if k not in ("id", "divisao", "qtd")}
    novo["qtd"] = qtd
    inv.append(novo)


def pile_items_with_flags() -> list[dict]:
    """Itens do saque aberto, para a conferência de item inventado no servidor."""
    saque = _saque()
    return list(saque["itens"]) if saque else []
